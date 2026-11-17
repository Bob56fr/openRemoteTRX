# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""trx-setup : assistant d'installation interactif (stdlib uniquement).

Étapes : modèle de TRX (Hamlib) -> port CAT -> PTT -> test de liaison -> audio
         -> bandes autorisées -> TOT -> écriture de station.toml.

Le test de liaison ne déclenche JAMAIS d'émission : il lit la fréquence, le mode et
l'état du PTT, et force un retour en RX si le PTT est déjà actif.
"""
from __future__ import annotations

from .crashguard import guarded

import argparse
import copy
import getpass
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from . import config as cfgmod
from . import formhint
from .answers import typed, yes_no
from .audio_devices import list_audio_devices, parse_audio_list  # noqa: F401 (parse_audio_list réexporté)
from .config import DEFAULT_BANDS_R1, DUMMY_MODEL, ClientAuth, Config, Rig
from .fsperm import protect
from .gateway.cat.capabilities import ALL_DATA_MODES, CapabilitiesError, _run_dump_caps, parse_dump_caps
from .hamlib import find_tool
from .i18n import tool_translator
from .migrate import is_desktop
from .passwords import generate_password, hash_password, password_problem
from .ports import list_serial_ports
from .rig_hints import RigHint, checklist_lines, hint_for, port_label, port_role, usb_voice_question, windows_port_advice
from .spectrum.probe import CheckFailed, CivPort, check, detect_address, open_serial, usb_send_warning

TEST_TCP_PORT = 4533  # port temporaire, distinct de celui du service (4532)


def _t(key: str, **fields) -> str:
    """Texte montré à l'opérateur, dans la langue de l'outil (lot L3 : `TRX_LANG` posée par TRX Console, sinon
    menu 0, sinon le système) ; catalogues `trxstation/i18n/setup.<langue>.json`, le français en référence.
    Lu À CHAQUE APPEL (jamais au chargement du module : les tests changent la langue après l'import)."""
    return tool_translator("setup")(key, **fields)


def _typed_yes(answer: str | None) -> bool:
    """Mot de confirmation : celui de la langue choisie OU le mot français OUI (toujours accepté, comme TRX Console)."""
    return any(typed(answer, word) for word in {_t("word.yes"), "OUI"})


class SetupError(RuntimeError):
    pass


# --------------------------------------------------------------------------- détection

_RIG_RE = re.compile(r"^\s*(\d+)\s+(\S.*?)\s{2,}(\S.*?)\s{2,}(\S+)\s+(\S+)\s+(\S+)\s*$")


def parse_rig_list(text: str) -> list[tuple[int, str, str]]:
    """Analyse la sortie de `rigctl -l` -> [(numéro, fabricant, modèle)]."""
    rigs = []
    for line in text.splitlines():
        m = _RIG_RE.match(line)
        if m:
            rigs.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip()))
    return rigs


def list_rig_models(hamlib_dir: str = "") -> list[tuple[int, str, str]]:
    rigctl = find_tool("rigctl", hamlib_dir)
    if rigctl is None:
        raise SetupError(_t("hamlib.rigctl_missing_windows"))
    out = subprocess.run([rigctl, "-l"], capture_output=True, text=True, timeout=30).stdout
    return parse_rig_list(out)


def ensure_hamlib() -> str:
    """Retourne le dossier de Hamlib à enregistrer (vide si rigctl est déjà dans le PATH)."""
    if find_tool("rigctl"):
        return ""
    if sys.platform != "win32":
        raise SetupError(_t("hamlib.rigctl_missing_linux"))
    print(_t("hamlib.download"))
    while True:
        folder = ask(_t("hamlib.folder"))
        if find_tool("rigctl", folder):
            return folder
        print(_t("hamlib.not_in_folder"))


# --------------------------------------------------------------------------- test de liaison

def _query(sock: socket.socket, cmd: str, timeout: float = 3.0) -> tuple[int | None, dict[str, str]]:
    """Envoie une commande rigctld en protocole étendu ('+') et lit jusqu'à la ligne RPRT."""
    sock.settimeout(timeout)
    sock.sendall(f"+{cmd}\n".encode())
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
        last = buf.decode(errors="replace").strip().splitlines()[-1:]
        if last and last[0].startswith("RPRT"):
            break
    code, values = None, {}
    for line in buf.decode(errors="replace").splitlines():
        if line.startswith("RPRT"):
            code = int(line.split()[1])
        elif ": " in line:
            key, value = line.split(": ", 1)
            values[key.strip()] = value.strip()
    return code, values


@contextmanager
def _temp_rigctld(rig: Rig, timeout: float = 10.0, hamlib_dir: str = "") -> Iterator[socket.socket]:
    """rigctld temporaire (127.0.0.1:TEST_TCP_PORT) ; donne la connexion, arrête rigctld en sortant."""
    rigctld = find_tool("rigctld", hamlib_dir)
    if rigctld is None:
        raise SetupError(_t("link.rigctld_missing"))
    command = [rigctld, *rig.rigctld_args("127.0.0.1", TEST_TCP_PORT)[1:]]
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    sock = None
    try:
        deadline = time.monotonic() + timeout
        while sock is None:
            if proc.poll() is not None:
                raise SetupError(_t("link.rigctld_stopped", error=(proc.stderr.read() or '').strip()[:300]))
            try:
                sock = socket.create_connection(("127.0.0.1", TEST_TCP_PORT), 0.5)
            except OSError:
                if time.monotonic() > deadline:
                    raise SetupError(_t("link.timeout"))
                time.sleep(0.3)
        yield sock
    except (OSError, ValueError) as exc:
        raise SetupError(_t("link.comm_failed", error=exc)) from exc
    finally:
        if sock:
            sock.close()
        proc.terminate()
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_link(rig: Rig, timeout: float = 10.0, hamlib_dir: str = "") -> dict[str, str]:
    """Lance rigctld temporairement et lit freq/mode/PTT. Lève SetupError en cas d'échec."""
    with _temp_rigctld(rig, timeout, hamlib_dir) as sock:
        result: dict[str, str] = {}
        for key, cmd in (("freq", "f"), ("mode", "m"), ("ptt", "t")):
            code, values = _query(sock, cmd)
            if code != 0:
                raise SetupError(_t("link.command_failed", cmd=cmd, code=code))
            result[key] = next(iter(values.values()), "")
        if result["ptt"] == "1":  # fail-safe : on ne peut que couper
            _query(sock, "T 0")
            result["ptt_forced_rx"] = "1"
        return result


# --------------------------------------------------------------------------- spectre (second port CI-V)

def _station_running(cfg: Config) -> bool:
    try:
        with socket.create_connection((cfg.network.rigctld_host, cfg.network.rigctld_port), timeout=0.3):
            return True
    except OSError:
        return False


def check_spectrum_port(cfg: Config, port: str, address: int | None = None, baud: int = 115200, *,
                        opener: Callable = open_serial, link: Callable | None = None,
                        settle_s: float = 0.4, say: Callable[[str], None] = print) -> int:
    """Vérifie le second port CI-V du poste, station arrêtée, avec un rigctld temporaire sur le port CAT : PTT relu
    avant et après l'ouverture (actif = coupure et refus), poste qui répond, spectre disponible, même fréquence que
    sur le port CAT. Renvoie l'adresse CI-V vérifiée ; SetupError sinon. N'émet jamais."""
    if not cfgmod.is_icom_model(cfg.rig.model):
        raise SetupError(_t("spectrum.icom_only"))
    if port.strip().lower() in {p.strip().lower() for p in (cfg.rig.port, cfg.rig.ptt_port) if p}:
        raise SetupError(_t("spectrum.same_port", port=port))
    if link is None and _station_running(cfg):
        raise SetupError(_t("spectrum.station_running"))
    with (link() if link is not None else _temp_rigctld(cfg.rig, hamlib_dir=cfg.tools.hamlib_dir)) as sock:
        def ptt() -> str:
            code, values = _query(sock, "t")
            return next(iter(values.values()), "") if code == 0 else ""

        def freq() -> int | None:
            code, values = _query(sock, "f")
            try:
                return int(float(next(iter(values.values()), ""))) if code == 0 else None
            except ValueError:
                return None

        def refuse_keyed(when: str) -> None:
            _query(sock, "T 0")                    # on ne peut que couper
            raise SetupError(_t("spectrum.keyed", when=_t(when), port=port))

        if ptt() != "0":
            raise SetupError(_t("spectrum.not_rx"))
        try:
            ser = opener(port, baud)
        except ImportError as exc:
            raise SetupError(_t("spectrum.no_pyserial")) from exc
        except (OSError, ValueError) as exc:
            raise SetupError(CheckFailed("open_failed", str(exc)).message(port)) from exc
        try:
            for _ in range(4):                     # l'ouverture a-t-elle touché au PTT ?
                time.sleep(settle_s)
                if ptt() != "0":
                    ser.close()
                    refuse_keyed("spectrum.when_open")
            civ = CivPort(ser, address or 0)
            if address is None:
                address = detect_address(civ)
                if address is None:
                    raise SetupError(CheckFailed("no_answer").message(port))
                civ.address = address
                say(_t("spectrum.found", port=port, address=f"{address:02X}"))
            try:
                check(civ, freq)
            except CheckFailed as exc:
                raise SetupError(exc.message(port, address)) from exc
        finally:
            ser.close()
        time.sleep(settle_s)
        if ptt() != "0":
            refuse_keyed("spectrum.when_close")
    return address


def apply_spectrum(cfg: Config, port: str, address: int, baud: int = 115200) -> None:
    sp = cfg.spectrum
    sp.enabled, sp.source, sp.port, sp.civ_address, sp.baud = True, "civ_port", port, f"{address:02X}", baud


def disable_spectrum(cfg: Config) -> None:
    cfg.spectrum.enabled = False


def ask_spectrum(cfg: Config) -> None:
    """Icom : propose le waterfall HF par le second port CI-V ; échec = mode normal (un seul port)."""
    if cfg.rig.model == DUMMY_MODEL or not cfgmod.is_icom_model(cfg.rig.model):
        return
    current = cfg.spectrum.enabled and cfg.spectrum.source == "civ_port"
    print(_t("spectrum.intro"))
    if not ask_yes_no(_t("spectrum.question"), current):
        if current:
            disable_spectrum(cfg)
            print(_t("spectrum.disabled"))
        return
    ports = [p for p in list_serial_ports() if p.strip().lower() != cfg.rig.port.strip().lower()]
    port = choose(_t("spectrum.port"), [(p, p) for p in ports], current=cfg.spectrum.port or None)
    print("\n" + usb_send_warning())
    word = _t("word.yes")
    _expect(kind="word", word=word)
    if not _typed_yes(ask(_t("spectrum.type_word", word=word), "")):
        disable_spectrum(cfg)
        print(_t("spectrum.not_opened"))
        return
    try:
        address = check_spectrum_port(cfg, port, cfgmod.parse_civ_address(cfg.spectrum.civ_address) if current else None)
    except SetupError as exc:
        disable_spectrum(cfg)
        print(_t("spectrum.problem", error=exc, port=port))
        return
    apply_spectrum(cfg, port, address)
    print(_t("spectrum.ok", port=port, address=f"{address:02X}"))


# --------------------------------------------------------------------------- dialogue

# Nature de la PROCHAINE question (console web en formulaires, `formhint`) : posée par les fonctions qui savent
# ce qu'elles demandent (choix, oui / non, nombre, mot à taper), lue et effacée par `ask`.
_hint: dict | None = None


def _expect(**hint) -> None:
    global _hint
    _hint = hint


def ask(prompt: str, default: str | None = None) -> str:
    global _hint
    hint, _hint = (_hint or {}), None
    suffix = f" [{default}]" if default else ""
    text = f"{prompt}{suffix}{_t('ask.colon')}"
    while True:
        fields = {"kind": "text", "prompt": prompt, **hint}
        if default is not None:
            fields.setdefault("default", default)
        formhint.emit(fields.pop("kind"), fields.pop("prompt"), text, **fields)
        answer = input(text).strip()
        if answer:
            return answer
        if default is not None:
            return default


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    _expect(kind="yesno", default=default)
    shown = _t("yesno.default_yes") if default else _t("yesno.default_no")
    answer = ask(f"{prompt} ({shown})", _t("yesno.yes_letter") if default else _t("yesno.no_letter"))
    return yes_no(answer) is True


def choose(title: str, options: list[tuple[str, str]], manual_label: str | None = None,
           current: str = "") -> str:
    """Menu numéroté. `current` (valeur déjà réglée) est placé en tête et proposé par défaut.
    `manual_label` : libellé du choix « m » (défaut : « Saisir à la main » dans la langue de l'outil)."""
    manual_label = manual_label or _t("choose.manual")
    if current:
        options = [(v, _t("choose.current", label=lbl)) for v, lbl in options if v == current] + \
                  [(v, lbl) for v, lbl in options if v != current]
        if not any(v == current for v, _ in options):
            options = [(current, _t("choose.current_missing", value=current))] + options
    if not formhint.enabled():                   # page : titre et liste deviennent le formulaire
        print(f"\n{title}")
        for i, (_, label) in enumerate(options, 1):
            print(f"  {i}) {label}")
        print(f"  m) {manual_label}")
    while True:
        _expect(kind="choice", prompt=title,
                choices=[[str(i), label] for i, (_, label) in enumerate(options, 1)] + [["m", manual_label]])
        answer = ask(_t("choose.prompt"), "1" if options else "m")
        if answer.lower() == "m":
            return ask(_t("choose.value"))
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        print(_t("choose.invalid"))


def select_model(hamlib_dir: str = "") -> int:
    rigs = list_rig_models(hamlib_dir)
    print(_t("model.count", count=len(rigs)))
    while True:
        term = ask(_t("model.search")).lower()
        found = [r for r in rigs if term in f"{r[1]} {r[2]}".lower()]
        if not found:
            print(_t("model.none"))
            continue
        shown = found[:20]
        if len(found) > len(shown):
            print(_t("model.truncated", count=len(found)))
        picked = choose(_t("model.found"), [(str(n), f"{n:>5}  {mfg} {model}") for n, mfg, model in shown],
                        manual_label=_t("model.new_search"))
        if picked.isdigit() and any(int(picked) == n for n, _, _ in rigs):
            return int(picked)


def _model_label(rigs: list[tuple[int, str, str]], model: int) -> str:
    return next((f"{mfg} {name}" for n, mfg, name in rigs if n == model), _t("model.unknown"))


def data_modes_for_model(model: int, hamlib_dir: str = "", *, dump=_run_dump_caps) -> list[str]:
    """Modes données qui existent pour ce modèle dans le Hamlib installé (4.7 : FM-D et AM-D, et non PKTFM, PKTAM).

    Si Hamlib ne répond pas, tous les noms connus : la liste ne contient que des modes données, jamais un mode micro.
    """
    try:
        caps = parse_dump_caps(dump(model, hamlib_dir), model)
    except (CapabilitiesError, OSError):
        return list(ALL_DATA_MODES)
    found = [m for m in ALL_DATA_MODES if caps.complete and m in caps.modes]
    return found or list(ALL_DATA_MODES)


def apply_rig_hint(cfg: Config, hint: RigHint, *, data_modes: Callable[[], list[str]],
                   yes_no_fn: Callable[[str, bool], bool] | None = None, say: Callable[[str], None] = print) -> None:
    """Poste connu de l'assistant (Yaesu FTDX10/101...) : menus du poste à régler, puis modes d'émission permis.

    Fail-safe : sans réponse « oui » explicite, émission limitée aux modes données (sinon le poste modulerait avec son
    propre micro, celui de la pièce, et non avec l'audio du client)."""
    yes_no_fn = yes_no_fn or ask_yes_no
    say(_t("hint.title", name=hint.name))
    for line in checklist_lines(hint):
        say(f"  - {line}")
    if yes_no_fn(usb_voice_question(hint), False):
        cfg.rig.tx_modes = []
        say(_t("hint.all_modes"))
    else:
        cfg.rig.tx_modes = data_modes()
        say(_t("hint.data_only", modes=", ".join(cfg.rig.tx_modes)))


def choose_cat_port(ports: list[str], current: str, *, chooser: Callable[..., str] | None = None,
                    yes_no_fn: Callable[[str, bool], bool] | None = None, say: Callable[[str], None] = print) -> str:
    """Port CAT. Double port CP2105 (Yaesu...) : « Enhanced » proposé en tête ; « Standard » refusé sauf confirmation."""
    chooser, yes_no_fn = chooser or choose, yes_no_fn or ask_yes_no
    ordered = sorted(ports, key=lambda p: {"enhanced": 0, "": 1, "standard": 2}[port_role(p)])
    if sys.platform == "win32" and ports:
        say(windows_port_advice())
    while True:
        port = chooser(_t("cat.port"), [(p, port_label(p)) for p in ordered], current=current)
        if port_role(port) != "standard":
            return port
        say(_t("cat.standard_warning"))
        if yes_no_fn(_t("cat.take_anyway"), False):
            return port


# Parties de l'assistant (TRX Console : une partie = un menu, étape 220). L'assistant complet les enchaîne dans cet
# ordre ; chacune ne pose que ses questions et part de la configuration existante (Entrée = réglage gardé).
# Textes en français pour l'aide argparse ; à l'écran, `parts.<partie>` du catalogue (langue de l'outil).
PARTS = {
    "poste": "Poste et liaison CAT (modèle, port, débit, PTT, test de liaison)",
    "son": "Cartes son (son reçu du poste, voix vers le poste)",
    "spectre": "Spectre HF par le second port CI-V (Icom)",
    "bandes": "Bandes autorisées en émission",
    "reseau": "Accès réseau (adresse d'écoute, HTTPS, certificat)",
    "emission": "Puissance maximale du poste et durée maximale d'une émission (TOT)",
}


def interactive(base: Config | None = None, tls_dir: Path | None = None) -> Config:
    """Questions de configuration. `base` : configuration existante, dont chaque réglage est repris par défaut
    (comptes, alertes, bandes, sécurité... ne sont jamais perdus en relançant l'assistant)."""
    cfg = copy.deepcopy(base) if base is not None else Config()
    print(_t("wizard.title"))
    if base is not None:
        print(_t("wizard.existing"))
    elif is_desktop():
        cfg.supervisor.max_reboots_per_hour = 0
        print(_t("wizard.desktop"))
    ask_rig(cfg, keep_offer=base is not None)
    ask_audio(cfg)
    ask_spectrum(cfg)
    ask_bands(cfg, keep_offer=base is not None)
    ask_network(cfg, tls_dir)
    ask_accounts(cfg)
    ask_transmit(cfg)
    return cfg


def interactive_part(part: str, base: Config, tls_dir: Path | None = None) -> Config:
    """Une seule partie de l'assistant (`PARTS`), sur une configuration existante ; le reste n'est pas touché."""
    if part not in PARTS:
        raise SetupError(_t("part.unknown", part=part, parts=", ".join(PARTS)))
    cfg = copy.deepcopy(base)
    print(_t("part.title", title=_t(f"parts.{part}")))
    if part == "poste":
        ask_rig(cfg, keep_offer=True)
    elif part == "son":
        ask_audio(cfg)
    elif part == "spectre":
        if cfg.rig.model == DUMMY_MODEL or not cfgmod.is_icom_model(cfg.rig.model):
            print(_t("part.no_spectrum"))
        ask_spectrum(cfg)
    elif part == "bandes":
        ask_bands(cfg, keep_offer=True)
    elif part == "reseau":
        ask_network(cfg, tls_dir)
    else:
        ask_transmit(cfg)
    return cfg


def ask_rig(cfg: Config, keep_offer: bool) -> None:
    """Poste : modèle Hamlib (avec les conseils d'un poste connu), rediffusion à l'ajout d'un poste, port CAT, débit,
    méthode PTT, puis test de liaison EN LECTURE SEULE (aucune émission)."""
    cfg.tools.hamlib_dir = ensure_hamlib() if not cfg.tools.hamlib_dir else cfg.tools.hamlib_dir
    rigs = list_rig_models(cfg.tools.hamlib_dir)
    keep_model = (keep_offer and cfg.rig.model > 0
                  and ask_yes_no(_t("rig.keep", model=cfg.rig.model, label=_model_label(rigs, cfg.rig.model)), True))
    if not keep_model:
        cfg.rig.model = select_model(cfg.tools.hamlib_dir)
        cfg.rig.tx_modes = []
        maker = next((m for n, m, _ in rigs if n == cfg.rig.model), "")
        if maker.lower() == "icom":
            print(_t("rig.icom_data"))
            if ask_yes_no(_t("rig.limit_data"), True):
                cfg.rig.tx_modes = data_modes_for_model(cfg.rig.model, cfg.tools.hamlib_dir)
                print(_t("rig.tx_modes", modes=", ".join(cfg.rig.tx_modes)))
    hint = hint_for(cfg.rig.model)                         # poste connu de l'assistant (Yaesu FTDX10/101...)
    if hint is not None and not keep_model:
        apply_rig_hint(cfg, hint, data_modes=lambda: data_modes_for_model(cfg.rig.model, cfg.tools.hamlib_dir))
    if not keep_model:
        ask_replay(cfg)

    if cfg.rig.model != DUMMY_MODEL:
        cfg.rig.port = choose_cat_port(list_serial_ports(), cfg.rig.port)
        default_speed = cfg.rig.speed or (hint.speed if hint else None)
        speed = ask(_t("rig.speed", default=default_speed if default_speed else _t("rig.speed_hamlib")),
                    str(default_speed) if default_speed else "auto")
        cfg.rig.speed = int(speed) if speed.isdigit() else None

        ptt = choose(_t("ptt.title"), [("RIG", _t("ptt.rig")),
                                       ("RTS", _t("ptt.rts")),
                                       ("DTR", _t("ptt.dtr")),
                                       ("GPIO", _t("ptt.gpio")),
                                       ("NONE", _t("ptt.none"))],
                     manual_label=_t("ptt.other"), current=cfg.rig.ptt_type)
        cfg.rig.ptt_type = ptt.upper()
        if cfg.rig.ptt_type in ("RTS", "DTR"):
            cfg.rig.ptt_port = ask(_t("ptt.port"), cfg.rig.ptt_port or cfg.rig.port)
        elif cfg.rig.ptt_type in ("GPIO", "GPION"):
            cfg.rig.ptt_port = ask(_t("ptt.gpio_id"), cfg.rig.ptt_port or None)
        else:
            cfg.rig.ptt_port = ""
    else:
        cfg.rig.port = ""

    while True:
        print(_t("link.testing"))
        try:
            res = test_link(cfg.rig, hamlib_dir=cfg.tools.hamlib_dir)
            print(_t("link.ok", freq=res['freq'], mode=res['mode'], ptt=res['ptt']))
            if res.get("ptt_forced_rx"):
                print(_t("link.forced_rx"))
            break
        except SetupError as exc:
            print(_t("link.failed", error=exc))
            if not ask_yes_no(_t("link.retry"), True):
                if ask_yes_no(_t("link.skip"), False):
                    break
                raise SystemExit(_t("link.abandon"))


def ask_audio(cfg: Config) -> None:
    """Cartes son : capture (son reçu du poste) et lecture (voix vers le poste)."""
    if cfg.rig.model == DUMMY_MODEL:
        return
    cap = choose(_t("audio.capture"), [(d, lbl) for d, lbl in list_audio_devices("capture")],
                 current=cfg.audio.capture_device)
    play = choose(_t("audio.playback"), [(d, lbl) for d, lbl in list_audio_devices("playback")],
                  current=cfg.audio.playback_device)
    cfg.audio.capture_device, cfg.audio.playback_device = cap, play


def ask_accounts(cfg: Config) -> None:
    """Comptes : ceux d'avant TOUJOURS gardés (l'ancienne question « Les garder », non = tout effacer, coupait tout
    accès à distance : retirée à la demande de l'utilisateur, étape 239) ; ajout seulement si l'opérateur le veut.
    Supprimer un compte ou changer un mot de passe : un par un, menus 4.3 (opérateurs) et 4.2 (visiteurs)."""
    if cfg.clients:
        print(_t("accounts.kept", accounts=", ".join(c.id for c in cfg.clients)))
        print(_t("accounts.how"))
        if not ask_yes_no(_t("accounts.add_more"), False):
            return
    ask_clients(cfg)


def ask_number(prompt: str, current: int, low: int, high: int, why: str = "") -> int:
    """Nombre entier entre `low` et `high`, redemandé avec une explication claire tant qu'il n'y est pas : une
    réponse hors limites ne doit jamais aller jusqu'à l'enregistrement (message technique de la validation)."""
    current = min(max(current, low), high)
    while True:
        _expect(kind="int", low=low, high=high, current=current)
        answer = ask(_t("number.range", prompt=prompt, low=low, high=high), str(current))
        if answer.isdigit() and low <= int(answer) <= high:
            return int(answer)
        print(_t("number.refused", low=low, high=high) + (f" {why}" if why else ""))


def ask_transmit(cfg: Config) -> None:
    """Puissance maximale du poste (affichage en watts) et durée maximale d'une émission (TOT, sous le plafond)."""
    s = cfg.safety
    cfg.rig.max_power_w = ask_number(_t("transmit.power"), cfg.rig.max_power_w, 0, 2000)
    s.tot_s = ask_number(_t("transmit.tot"), s.tot_s, s.warn_before_s + 1, s.tot_ceiling_s,
                         _t("transmit.tot_why", ceiling=s.tot_ceiling_s, low=s.warn_before_s + 1, warn=s.warn_before_s))


def ask_replay(cfg: Config) -> None:
    """Accordée UNE FOIS, à l'ajout du poste, seulement à la demande expresse de l'opérateur (décision du 2026-11-02)."""
    print(_t("replay.warning"))
    cfg.safety.allow_replay = ask_yes_no(_t("replay.question"), False)


def ask_bands(cfg: Config, keep_offer: bool = False) -> None:
    if keep_offer:
        current = (_t("bands.delegated") if not cfg.safety.enforce_bands
                   else _t("bands.station", count=len(cfg.bands)) if cfg.bands else _t("bands.station_none"))
        if ask_yes_no(_t("bands.keep", current=current), True):
            return
    print(_t("bands.intro"))
    if ask_yes_no(_t("bands.rig_limits"), False):
        cfg.safety.enforce_bands = False
    else:
        cfg.safety.enforce_bands = True
        print(_t("bands.defaults_intro"))
        if ask_yes_no(_t("bands.load"), False):
            cfg.bands = list(DEFAULT_BANDS_R1)
        elif not cfg.bands:
            print(_t("bands.none"))


def local_addresses(run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                    platform: str | None = None) -> list[str]:
    """Adresses IPv4 de la machine sur le réseau (hors boucle locale), sans envoyer de trafic."""
    found: list[str] = []
    if (platform or sys.platform).startswith("linux"):          # « hostname -I » n'existe que sous Linux
        try:
            out = run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout
            found += [a for a in out.split() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", a)]
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))           # aucune donnée n'est envoyée : seule la route est choisie
            found.append(sock.getsockname()[0])
    except OSError:
        pass
    return [a for i, a in enumerate(found) if a not in found[:i] and not a.startswith("127.")]


def ask_network(cfg: Config, tls_dir: Path | None) -> None:
    n = cfg.network
    print(_t("network.intro"))
    options = [("local", _t("network.local")),
               ("lan", _t("network.lan"))]
    current = ""
    if n.gateway_bind not in ("127.0.0.1", "") or n.tls_cert:
        current = "keep"
        options.insert(0, ("keep", _t("network.keep", bind=n.gateway_bind, port=n.gateway_port,
                                      https=_t("network.with_https") if n.tls_cert else _t("network.without_https"))))
    picked = choose(_t("network.title"), options, manual_label=_t("network.manual"), current=current)
    if picked == "keep":
        return
    if picked == "local":
        n.gateway_bind, n.allow_insecure_http = "127.0.0.1", False
        return
    if picked != "lan":
        n.gateway_bind = picked
        return
    hosts = local_addresses() + [socket.gethostname(), f"{socket.gethostname()}.local"]
    folder = tls_dir or Path("tls")
    try:
        _make_certificate(hosts, folder, cfg)
    except ImportError:
        print(_t("network.no_crypto"))
        n.gateway_bind = "127.0.0.1"
        return
    n.gateway_bind, n.allow_insecure_http = "0.0.0.0", False
    print(_t("network.cert_for", hosts=", ".join(hosts)))
    for address in hosts[:-2] or [_t("network.this_pc")]:
        print(_t("network.open_on_phone", address=address, port=n.gateway_port))
    print(_t("network.ca_note"))
    from .gateway.api.tls import certificate_fingerprint
    print(_t("network.fingerprint", fingerprint=certificate_fingerprint(n.tls_cert)))


def pairing_lines(cfg: Config, addresses: Callable[[], list[str]] | None = None) -> list[str]:
    """Ce qu'on saisit dans l'application Android pour appairer cette station : adresse(s), comptes, empreinte du
    certificat. JAMAIS de mot de passe (seule son empreinte scrypt est connue). OSError si le certificat est illisible."""
    from .gateway.api.tls import certificate_fingerprint
    n = cfg.network
    lines = [_t("pairing.title")]
    if n.gateway_bind in ("127.0.0.1", "localhost", "::1", ""):
        return lines + [_t("pairing.local_only"), _t("pairing.open_lan")]
    hosts = _pairing_hosts(cfg, addresses)
    scheme = "https" if n.tls_cert else "http"
    lines.append(_t("pairing.address", addresses=", ".join(f"{scheme}://{h}:{n.gateway_port}" for h in hosts) or
                    f"{scheme}://{_t('network.this_pc')}:{n.gateway_port}"))
    lines.append(_t("pairing.accounts", accounts=", ".join(c.id for c in cfg.clients) or _t("pairing.no_account")))
    if not n.tls_cert:
        lines.append(_t("pairing.no_cert"))
        return lines
    fingerprint = certificate_fingerprint(n.tls_cert)       # 32 octets : deux lignes de 16, plus faciles à comparer
    return lines + [_t("pairing.fingerprint"), "    " + fingerprint[:47], "    " + fingerprint[48:]]


def _pairing_hosts(cfg: Config, addresses: Callable[[], list[str]] | None = None) -> list[str]:
    n = cfg.network
    return (addresses or local_addresses)() if n.gateway_bind in ("0.0.0.0", "::") else [n.gateway_bind]


def pairing_uri(name: str, url: str, user: str, fingerprint: str) -> str:
    """Contenu du QR code d'appairage (docs/protocole.md § 12, exemples tests/protocol/pairing.json).
    JAMAIS de mot de passe : seuls le nom, l'adresse, l'identifiant et l'empreinte du certificat."""
    from urllib.parse import quote
    fields = [("v", "1")] + [(key, value) for key, value in
                             (("n", name), ("u", url), ("id", user), ("fp", fingerprint.replace(":", ""))) if value]
    return "openremotetrx://pair?" + "&".join(f"{key}={quote(value, safe='')}" for key, value in fields)


def qr_lines(text: str, border: int = 2) -> list[str] | None:
    """QR code en caractères, deux rangées de modules par ligne, dessiné pour un terminal SOMBRE (modules clairs et
    marge = blocs pleins) ; l'application lit aussi un QR inversé (terminal clair). None si segno est absent."""
    try:
        import segno
    except ImportError:
        return None
    rows = [[bool(module) for module in row] for row in segno.make(text, error="m", micro=False).matrix]
    size = len(rows)
    height = width = size + 2 * border

    def light(r: int, c: int) -> bool:
        if r >= height:
            return False                                       # sous le dernier rang : fond du terminal
        r, c = r - border, c - border
        return not (0 <= r < size and 0 <= c < size and rows[r][c])

    return ["".join("█" if light(r, c) and light(r + 1, c) else "▀" if light(r, c) else "▄" if light(r + 1, c) else " "
                    for c in range(width)) for r in range(0, height, 2)]


def show_pairing(cfg: Config, ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
                 addresses: Callable[[], list[str]] | None = None, hostname: Callable[[], str] = socket.gethostname,
                 user: str | None = None) -> None:
    """Menu 4.1 et `--empreinte` : informations d'appairage, puis un QR code à scanner par l'application.
    Demande l'adresse et le compte seulement s'il y a un choix ; `user` : compte imposé (menu 4.3, compte qui vient
    d'être créé). OSError si le certificat est illisible."""
    from .gateway.api.tls import certificate_fingerprint
    say("\n".join(pairing_lines(cfg, addresses)))
    n = cfg.network
    if n.gateway_bind in ("127.0.0.1", "localhost", "::1", "") or not n.tls_cert:
        return
    hosts = _pairing_hosts(cfg, addresses)
    if not hosts:
        return
    host = _pick(hosts, _t("pairing.qr_address"), ask, say, default=hosts[0])
    accounts = [c.id for c in cfg.clients]
    if user is None or user not in accounts:
        user = _pick(accounts, _t("pairing.qr_account"), ask, say, default="") if accounts else ""
    lines = qr_lines(pairing_uri(hostname(), f"https://{host}:{n.gateway_port}", user, certificate_fingerprint(n.tls_cert)))
    if lines is None:
        say(_t("pairing.no_segno"))
        return
    say(_t("pairing.qr_intro"))
    say("\n".join("  " + line for line in lines))
    say(_t("pairing.qr_footer", host=host, port=n.gateway_port, account=user or _t("pairing.account_in_app")))


def _pick(choices: list[str], title: str, ask: Callable[[str], str], say: Callable[[str], None], default: str) -> str:
    """Un seul choix : pris d'office. Sinon liste numérotée ; Entrée ou réponse invalide = `default`."""
    if len(choices) == 1:
        return choices[0]
    say(_t("pick.title", title=title))
    for i, choice in enumerate(choices, 1):
        say(f"    {i}) {choice}")
    hint = (_t("pick.enter_default", number=choices.index(default) + 1) if default in choices
            else _t("pick.enter_none"))
    answer = ask(_t("pick.number", hint=hint)).strip()
    if answer.isdigit() and 1 <= int(answer) <= len(choices):
        return choices[int(answer) - 1]
    return default


def _make_certificate(hosts: list[str], folder: Path, cfg: Config) -> bool:
    """Certificat de la passerelle signé par l'AUTORITÉ DE LA STATION (étape 195), créée au besoin dans le même
    dossier. Rend vrai si l'autorité vient d'être (re)créée : à installer (de nouveau) sur chaque appareil."""
    from .gateway.api.tls import CA_CERT, ca_covers, generate_station_ca, generate_station_cert
    cert, key = folder / "station-cert.pem", folder / "station-key.pem"
    created = not ca_covers(folder, hosts)
    if created:                                           # absente, ou ses contraintes ne couvrent pas un nouveau nom
        generate_station_ca(folder, hosts, label=socket.gethostname())
        protect(folder / CA_CERT)                         # lu par la passerelle (téléchargement) ; sa clé reste 0600
    generate_station_cert(hosts, folder, cert, key)
    protect(cert)
    protect(key)
    cfg.network.tls_cert, cfg.network.tls_key = str(cert), str(key)
    return created


def station_authority(cfg: Config, output: Path, hosts: list[str] | None = None,
                      say: Callable[[str], None] = print) -> int:
    """Passe la station à son autorité de certification (TRX Console, menu 4.4) : noms du certificat actuel PLUS
    ceux donnés, même dossier ; empreinte affichée (l'application doit être appairée de nouveau)."""
    from .gateway.api.tls import certificate_fingerprint, certificate_hosts
    n = cfg.network
    current = Path(n.tls_cert) if n.tls_cert else None
    names = list(dict.fromkeys((certificate_hosts(current) if current else []) + list(hosts or [])))
    if not names:
        names = local_addresses() + [socket.gethostname(), f"{socket.gethostname()}.local"]
    folder = current.parent if current else output.resolve().parent / "tls"
    created = _make_certificate(names, folder, cfg)
    write_config(cfg, output)
    say(_t("authority.signed", names=", ".join(names)))
    url = f"https://{names[0]}:{n.gateway_port}/station-ca.crt"
    say(_t("authority.created", url=url) if created else _t("authority.unchanged", url=url))
    say(_t("authority.fingerprint", fingerprint=certificate_fingerprint(n.tls_cert)))
    return 0


def choose_password(login: str, ask_password: Callable[[str], str] = getpass.getpass,
                    say: Callable[[str], None] = print) -> str:
    """Saisie masquée avec double saisie et règle de robustesse ; Entrée = en générer un fort."""
    if ask_password is getpass.getpass and formhint.enabled():
        ask_password = _form_password                       # page : champ masqué du navigateur, pas de terminal
    while True:
        first = ask_password(_t("password.first"))
        if not first:
            generated = generate_password()
            say(_t("password.generated", password=generated))
            say(_t("password.note"))
            return generated
        problem = password_problem(first, login)
        if problem:
            say(_t("password.refused", problem=problem))
            continue
        if ask_password(_t("password.confirm")) != first:
            say(_t("password.differ"))
            continue
        return first


def _form_password(prompt: str) -> str:
    formhint.emit("password", prompt.strip(), prompt, generate=prompt == _t("password.first"))
    return input(prompt)


def _check_login_and_password(cfg: Config, name: str, password: str, existing: bool) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
        raise SetupError(_t("clients.invalid_id", name=repr(name)))
    if existing != any(c.id == name for c in cfg.clients):
        raise SetupError(_t("clients.unknown" if existing else "clients.duplicate", name=name))
    problem = password_problem(password, name)
    if problem:
        raise SetupError(_t("clients.password_refused", problem=problem))


def add_client(cfg: Config, name: str, password: str | None = None) -> str:
    """Autorise un client et retourne son mot de passe (généré si non fourni). Seule l'empreinte est enregistrée."""
    password = password or generate_password()
    _check_login_and_password(cfg, name, password, existing=False)
    cfg.clients.append(ClientAuth(id=name, password_hash=hash_password(password)))
    return password


def set_password(cfg: Config, name: str, password: str | None = None) -> str:
    """Remplace le secret d'un client existant (et supprime un éventuel ancien jeton en clair)."""
    password = password or generate_password()
    _check_login_and_password(cfg, name, password, existing=True)
    client = next(c for c in cfg.clients if c.id == name)
    client.password_hash, client.token = hash_password(password), ""
    return password


def ask_clients(cfg: Config) -> None:
    print(_t("clients.intro"))
    while True:
        name = ask(_t("clients.ask"), "")
        if not name:
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) or any(c.id == name for c in cfg.clients):
            print(_t("clients.invalid"))
            continue
        add_client(cfg, name, choose_password(name))


def dummy_config() -> Config:
    """Configuration de développement : poste factice, bandes par défaut."""
    cfg = Config()
    cfg.rig.model = DUMMY_MODEL
    cfg.bands = list(DEFAULT_BANDS_R1)
    return cfg


# --------------------------------------------------------------------------- écriture

def write_config(cfg: Config, output: Path) -> None:
    problems = cfgmod.validate(cfg)
    if problems:
        raise SetupError(_t("write.refused", problems="\n  - ".join(problems)))
    output.parent.mkdir(parents=True, exist_ok=True)
    previous = output.stat() if output.exists() else None
    if previous is not None:
        backup = output.with_suffix(output.suffix + ".bak")
        shutil.copy2(output, backup)                # copy2 garde les droits : la sauvegarde reste protégée
        print(_t("write.backup", path=backup))
    output.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    protect(output, previous)   # le fichier contient les empreintes des mots de passe : root + groupe trx, 0640 au plus
    cfgmod.load(output)  # relecture : garantit que le fichier écrit est bien valide
    print(_t("write.done", path=output))
    for w in cfgmod.warnings(cfg):
        print(f"  ! {w}")


def load_base(path: Path | None) -> Config | None:
    """Configuration de départ de l'assistant, même incomplète ; None si absente ou illisible."""
    if path is None:
        return None
    try:
        cfg, problems = cfgmod.load_unchecked(path)
    except (OSError, cfgmod.ConfigError) as exc:
        print(_t("base.unreadable", path=path, error=exc))
        return None
    if problems:
        print(_t("base.incomplete", path=path))
        for problem in problems:
            print(f"  - {problem}")
    return cfg


@guarded("trx-setup")
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-setup", description="Assistant de configuration de la station TRX")
    ap.add_argument("--output", "-o", type=Path, default=Path("station.toml"))
    ap.add_argument("--add-client", metavar="NOM", help="autorise un client dans la configuration existante (--output)")
    ap.add_argument("--set-password", metavar="NOM", help="change le mot de passe d'un client existant (--output)")
    ap.add_argument("--max-power", type=int, metavar="WATTS",
                    help="puissance maximale du poste (ex. 100) : la page affiche la puissance en watts ; 0 = inconnue, en pourcentage (--output)")
    ap.add_argument("--bands", choices=("on", "off"),
                    help="off : la station ne contrôle plus les bandes d'émission (le poste s'en charge) ; on : elle les contrôle (--output)")
    ap.add_argument("--tx-modes", metavar="MODE", nargs="+",
                    help="modes où l'émission est permise (ex. PKTUSB PKTLSB) ; « aucun » supprime la restriction (--output)")
    ap.add_argument("--self-signed", metavar="HÔTE", nargs="+",
                    help="génère un certificat TLS pour ces noms/adresses IP, signé par l'autorité de la station "
                         "(créée au besoin), et l'active (--output)")
    ap.add_argument("--autorite-station", metavar="HÔTE", nargs="*",
                    help="refait le certificat de la passerelle, signé par l'autorité de la station (noms de "
                         "l'actuel, plus ceux donnés) ; l'application devra être appairée de nouveau (--output)")
    ap.add_argument("--empreinte", action="store_true",
                    help="affiche adresse, comptes et empreinte du certificat pour appairer l'application Android (--output, lecture seule)")
    ap.add_argument("--compte", metavar="NOM", help="avec --empreinte : compte à mettre dans le QR code (sans question)")
    ap.add_argument("--base", type=Path, metavar="FICHIER",
                    help="reprend ce fichier comme point de départ (ex. configuration importée d'un autre PC) ; "
                         "par défaut, le fichier --output s'il existe")
    ap.add_argument("--spectre", metavar="PORT",
                    help="vérifie le second port CI-V du poste (Icom, station arrêtée) et active le waterfall HF ; "
                         "« off » le désactive (--output)")
    ap.add_argument("--adresse-civ", metavar="HEX", help="avec --spectre : adresse CI-V attendue (ex. B6) ; défaut : recherche")
    ap.add_argument("--reglages-verifies", action="store_true",
                    help="avec --spectre : USB SEND / USB Keying déjà vérifiés (pas de question)")
    ap.add_argument("--partie", choices=tuple(PARTS),
                    help="une seule partie de l'assistant, sur la configuration existante (--output) : "
                         + " ; ".join(f"{k} = {v}" for k, v in PARTS.items()))
    ap.add_argument("--dummy", action="store_true",
                    help="génère sans questions une config de développement (poste factice Hamlib)")
    args = ap.parse_args(argv)
    try:
        if args.spectre:
            return _cli_spectrum(args)
        if args.autorite_station is not None:
            return station_authority(cfgmod.load(args.output), args.output, args.autorite_station)
        if args.empreinte:
            cfg, _ = cfgmod.load_unchecked(args.output)
            try:                                               # sans terminal (journal, tube) : choix par défaut
                show_pairing(cfg, ask=input if sys.stdin.isatty() else (lambda _prompt: ""), user=args.compte)
            except (OSError, ValueError) as exc:
                print(_t("main.cert_unreadable", cert=cfg.network.tls_cert, error=exc), file=sys.stderr)
                return 1
            return 0
        if args.add_client or args.set_password or args.self_signed or args.tx_modes or args.bands or args.max_power is not None:
            cfg = cfgmod.load(args.output)
            if args.max_power is not None:
                if not 0 <= args.max_power <= 2000:
                    print(_t("main.max_power_range"), file=sys.stderr)
                    return 2
                cfg.rig.max_power_w = args.max_power
                print(_t("main.max_power", value=f"{args.max_power} W" if args.max_power else _t("main.power_unknown")))
            if args.bands:
                cfg.safety.enforce_bands = args.bands == "on"
                print(_t("main.bands_on") if cfg.safety.enforce_bands else _t("main.bands_off"))
            if args.tx_modes:
                cfg.rig.tx_modes = [] if [m.lower() for m in args.tx_modes] == ["aucun"] else list(args.tx_modes)
                print(_t("main.tx_modes", modes=", ".join(cfg.rig.tx_modes) or _t("main.all_modes")))
            if args.add_client:
                add_client(cfg, args.add_client, choose_password(args.add_client))
                print(_t("main.client_added", name=args.add_client))
            if args.set_password:
                set_password(cfg, args.set_password, choose_password(args.set_password))
                print(_t("main.password_changed", name=args.set_password))
            if args.self_signed:
                _make_certificate(args.self_signed, args.output.resolve().parent / "tls", cfg)
                print(_t("main.cert_written", cert=cfg.network.tls_cert))
                from .gateway.api.tls import certificate_fingerprint
                print(_t("main.fingerprint", fingerprint=certificate_fingerprint(cfg.network.tls_cert)))
            write_config(cfg, args.output)
            return 0
        if args.partie:
            if not args.output.exists():
                print(_t("main.no_config", path=args.output), file=sys.stderr)
                return 2
            base = load_base(args.output)
            if base is None:
                return 2
            cfg = interactive_part(args.partie, base, tls_dir=args.output.resolve().parent / "tls")
        elif args.dummy:
            cfg = dummy_config()
        else:
            base = load_base(args.base or (args.output if args.output.exists() else None))
            cfg = interactive(base, tls_dir=args.output.resolve().parent / "tls")
        write_config(cfg, args.output)
    except cfgmod.ConfigError as exc:
        print(_t("main.invalid", problems="\n  - ".join(exc.problems)), file=sys.stderr)
        return 2
    except SetupError as exc:
        print(_t("main.error", error=exc), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print(_t("main.interrupted"), file=sys.stderr)
        return 130
    return 0


def _cli_spectrum(args) -> int:
    cfg = cfgmod.load(args.output)
    if args.spectre.strip().lower() == "off":
        disable_spectrum(cfg)
        write_config(cfg, args.output)
        print(_t("cli_spectrum.off"))
        return 0
    address = None
    if args.adresse_civ:
        address = cfgmod.parse_civ_address(args.adresse_civ)
        if address is None:
            print(_t("cli_spectrum.bad_address"), file=sys.stderr)
            return 2
    print(usb_send_warning())
    if not args.reglages_verifies and not _typed_yes(input(_t("spectrum.type_word", word=_t("word.yes")) + _t("ask.colon"))):
        print(_t("cli_spectrum.cancelled"))
        return 2
    print(_t("cli_spectrum.checking", port=args.spectre))
    try:
        address = check_spectrum_port(cfg, args.spectre, address)
    except SetupError as exc:
        print(_t("cli_spectrum.problem", error=exc), file=sys.stderr)
        return 1
    apply_spectrum(cfg, args.spectre, address)
    write_config(cfg, args.output)
    print(_t("cli_spectrum.ok", port=args.spectre, address=f"{address:02X}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
