"""trx-setup : assistant d'installation interactif (stdlib uniquement).

Étapes : modèle de TRX (Hamlib) -> port CAT -> PTT -> test de liaison -> audio
         -> bandes autorisées -> TOT -> écriture de station.toml.

Le test de liaison ne déclenche JAMAIS d'émission : il lit la fréquence, le mode et
l'état du PTT, et force un retour en RX si le PTT est déjà actif.
"""
from __future__ import annotations

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
from .audio_devices import list_audio_devices, parse_audio_list  # noqa: F401 (parse_audio_list réexporté)
from .config import DEFAULT_BANDS_R1, DUMMY_MODEL, ClientAuth, Config, Rig
from .fsperm import protect
from .gateway.cat.capabilities import ALL_DATA_MODES, CapabilitiesError, _run_dump_caps, parse_dump_caps
from .hamlib import find_tool
from .migrate import is_desktop
from .passwords import generate_password, hash_password, password_problem
from .ports import list_serial_ports
from .spectrum.probe import USB_SEND_WARNING, CheckFailed, CivPort, check, detect_address, open_serial

TEST_TCP_PORT = 4533  # port temporaire, distinct de celui du service (4532)


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
        raise SetupError("`rigctl` introuvable : installe Hamlib (Linux : sudo apt install libhamlib-utils ; "
                         "Windows : décompresse hamlib-w64 et renseigne son dossier).")
    out = subprocess.run([rigctl, "-l"], capture_output=True, text=True, timeout=30).stdout
    return parse_rig_list(out)


def ensure_hamlib() -> str:
    """Retourne le dossier de Hamlib à enregistrer (vide si rigctl est déjà dans le PATH)."""
    if find_tool("rigctl"):
        return ""
    if sys.platform != "win32":
        raise SetupError("`rigctl` introuvable : installe Hamlib (sudo apt install libhamlib-utils).")
    print("\nHamlib est introuvable. Télécharge hamlib-w64-*.zip (hamlib.github.io), décompresse-le, "
          "puis indique son dossier.")
    while True:
        folder = ask("Dossier de Hamlib (celui qui contient bin\\rigctl.exe)")
        if find_tool("rigctl", folder):
            return folder
        print("rigctl.exe introuvable dans ce dossier, réessaie.")


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
        raise SetupError("`rigctld` introuvable : installe Hamlib ou renseigne son dossier.")
    command = [rigctld, *rig.rigctld_args("127.0.0.1", TEST_TCP_PORT)[1:]]
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    sock = None
    try:
        deadline = time.monotonic() + timeout
        while sock is None:
            if proc.poll() is not None:
                raise SetupError(f"rigctld s'est arrêté : {(proc.stderr.read() or '').strip()[:300]}")
            try:
                sock = socket.create_connection(("127.0.0.1", TEST_TCP_PORT), 0.5)
            except OSError:
                if time.monotonic() > deadline:
                    raise SetupError("rigctld ne répond pas (délai dépassé).")
                time.sleep(0.3)
        yield sock
    except (OSError, ValueError) as exc:
        raise SetupError(f"échec de la communication : {exc}") from exc
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
                raise SetupError(f"commande '{cmd}' en erreur (RPRT {code}) : "
                                 "vérifie modèle, port et débit.")
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
        raise SetupError("spectre par le second port : postes Icom seulement (modèle Hamlib 3xxx).")
    if port.strip().lower() in {p.strip().lower() for p in (cfg.rig.port, cfg.rig.ptt_port) if p}:
        raise SetupError(f"{port} est le port CAT ou PTT du poste : il faut le SECOND port, réglé en CI-V.")
    if link is None and _station_running(cfg):
        raise SetupError("la station tourne (rigctld tient le port CAT) : arrête-la d'abord (TRX Console).")
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
            raise SetupError(f"DANGER : le poste est passé en ÉMISSION {when} de {port}. Un réglage « USB SEND » ou "
                             "« USB Keying » du poste utilise ce port : corrige-le avant toute nouvelle tentative. "
                             "Coupure envoyée ; spectre NON activé.")

        if ptt() != "0":
            raise SetupError("le poste n'est pas en réception confirmée (PTT actif ou illisible) : essai annulé.")
        try:
            ser = opener(port, baud)
        except ImportError as exc:
            raise SetupError("module pyserial absent : pip install pyserial") from exc
        except (OSError, ValueError) as exc:
            raise SetupError(CheckFailed("open_failed", str(exc)).message(port)) from exc
        try:
            for _ in range(4):                     # l'ouverture a-t-elle touché au PTT ?
                time.sleep(settle_s)
                if ptt() != "0":
                    ser.close()
                    refuse_keyed("à l'ouverture")
            civ = CivPort(ser, address or 0)
            if address is None:
                address = detect_address(civ)
                if address is None:
                    raise SetupError(CheckFailed("no_answer").message(port))
                civ.address = address
                say(f"  Poste trouvé sur {port} à l'adresse CI-V {address:02X}h.")
            try:
                check(civ, freq)
            except CheckFailed as exc:
                raise SetupError(exc.message(port, address)) from exc
        finally:
            ser.close()
        time.sleep(settle_s)
        if ptt() != "0":
            refuse_keyed("à la fermeture")
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
    print("\nSpectre HF (waterfall du poste) : certains Icom (IC-7300MK2...) ont un SECOND port série USB, "
          "réglable en CI-V, qui le transmet sans toucher au port CAT.")
    if not ask_yes_no("Ce poste a-t-il un second port réglé en CI-V à utiliser pour le spectre", current):
        if current:
            disable_spectrum(cfg)
            print("Spectre désactivé : un seul port, sans waterfall HF.")
        return
    ports = [p for p in list_serial_ports() if p.strip().lower() != cfg.rig.port.strip().lower()]
    port = choose("Second port du poste (CI-V)", [(p, p) for p in ports], current=cfg.spectrum.port or None)
    print("\n" + USB_SEND_WARNING)
    if ask("Tape OUI si ces réglages sont vérifiés", "").strip().upper() != "OUI":
        disable_spectrum(cfg)
        print("Second port non ouvert : spectre désactivé (mode normal).")
        return
    try:
        address = check_spectrum_port(cfg, port, cfgmod.parse_civ_address(cfg.spectrum.civ_address) if current else None)
    except SetupError as exc:
        disable_spectrum(cfg)
        print(f"  PROBLÈME DE CONFIGURATION : {exc}\n  Spectre désactivé : la station fonctionnera en mode normal "
              "(un seul port, sans waterfall HF). Corrige le réglage puis : trx-setup --spectre " + port)
        return
    apply_spectrum(cfg, port, address)
    print(f"  OK : spectre disponible sur {port} (adresse CI-V {address:02X}h). La station le revérifiera à chaque démarrage.")


# --------------------------------------------------------------------------- dialogue

def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{prompt}{suffix} : ").strip()
        if answer:
            return answer
        if default is not None:
            return default


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    answer = ask(f"{prompt} ({'O/n' if default else 'o/N'})", "o" if default else "n").lower()
    return answer in ("o", "oui", "y", "yes")


def choose(title: str, options: list[tuple[str, str]], manual_label: str = "Saisir à la main",
           current: str = "") -> str:
    """Menu numéroté. `current` (valeur déjà réglée) est placé en tête et proposé par défaut."""
    if current:
        options = [(v, f"{lbl}  (réglage actuel)") for v, lbl in options if v == current] + \
                  [(v, lbl) for v, lbl in options if v != current]
        if not any(v == current for v, _ in options):
            options = [(current, f"{current}  (réglage actuel, introuvable pour l'instant)")] + options
    print(f"\n{title}")
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i}) {label}")
    print(f"  m) {manual_label}")
    while True:
        answer = ask("Choix", "1" if options else "m")
        if answer.lower() == "m":
            return ask("Valeur")
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        print("Choix invalide.")


def select_model(hamlib_dir: str = "") -> int:
    rigs = list_rig_models(hamlib_dir)
    print(f"\n{len(rigs)} modèles connus de Hamlib. (« dummy » = poste factice pour tester sans matériel)")
    while True:
        term = ask("Marque ou modèle à chercher (ex. ic-7300, ft-991, dummy)").lower()
        found = [r for r in rigs if term in f"{r[1]} {r[2]}".lower()]
        if not found:
            print("Aucun résultat, essaie un autre terme.")
            continue
        shown = found[:20]
        if len(found) > len(shown):
            print(f"({len(found)} résultats, 20 premiers affichés : affine ta recherche si besoin)")
        picked = choose("Modèles trouvés", [(str(n), f"{n:>5}  {mfg} {model}") for n, mfg, model in shown],
                        manual_label="Nouvelle recherche")
        if picked.isdigit() and any(int(picked) == n for n, _, _ in rigs):
            return int(picked)


def _model_label(rigs: list[tuple[int, str, str]], model: int) -> str:
    return next((f"{mfg} {name}" for n, mfg, name in rigs if n == model), "modèle inconnu de ce Hamlib")


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


def interactive(base: Config | None = None, tls_dir: Path | None = None) -> Config:
    """Questions de configuration. `base` : configuration existante, dont chaque réglage est repris par défaut
    (comptes, alertes, bandes, sécurité... ne sont jamais perdus en relançant l'assistant)."""
    cfg = copy.deepcopy(base) if base is not None else Config()
    print("=== trx-setup : configuration de la station ===")
    if base is not None:
        print("Configuration existante reprise : Entrée garde le réglage actuel.")
    elif is_desktop():
        cfg.supervisor.max_reboots_per_hour = 0
        print("PC de bureau : le superviseur ne redémarrera jamais ce PC (mode sûr en dernier recours).")
    cfg.tools.hamlib_dir = ensure_hamlib() if not cfg.tools.hamlib_dir else cfg.tools.hamlib_dir
    rigs = list_rig_models(cfg.tools.hamlib_dir)
    keep_model = (base is not None and cfg.rig.model > 0
                  and ask_yes_no(f"Garder le poste {cfg.rig.model} ({_model_label(rigs, cfg.rig.model)})", True))
    if not keep_model:
        cfg.rig.model = select_model(cfg.tools.hamlib_dir)
        cfg.rig.tx_modes = []
        maker = next((m for n, m, _ in rigs if n == cfg.rig.model), "")
        if maker.lower() == "icom":
            print("\nIcom : l'audio USB n'est émis qu'en MODES DONNÉES (USB-D, LSB-D, AM-D, FM-D). Dans un autre mode, le poste modulerait avec son propre micro.")
            if ask_yes_no("Limiter l'émission à ces modes données (recommandé)", True):
                cfg.rig.tx_modes = data_modes_for_model(cfg.rig.model, cfg.tools.hamlib_dir)
                print("Modes d'émission permis : " + ", ".join(cfg.rig.tx_modes))

    if cfg.rig.model != DUMMY_MODEL:
        ports = list_serial_ports()
        cfg.rig.port = choose("Port CAT du TRX (de préférence /dev/serial/by-id/...)",
                              [(p, p) for p in ports], current=cfg.rig.port)
        speed = ask("Débit série (Entrée = " + (f"{cfg.rig.speed}" if cfg.rig.speed else "défaut Hamlib du modèle") + ")",
                    str(cfg.rig.speed) if cfg.rig.speed else "auto")
        cfg.rig.speed = int(speed) if speed.isdigit() else None

        ptt = choose("Méthode PTT", [("RIG", "CAT (commande envoyée au poste)"),
                                     ("RTS", "ligne RTS du port série"),
                                     ("DTR", "ligne DTR du port série"),
                                     ("GPIO", "broche GPIO du Pi"),
                                     ("NONE", "aucune (réception seule)")],
                     manual_label="Autre type Hamlib", current=cfg.rig.ptt_type)
        cfg.rig.ptt_type = ptt.upper()
        if cfg.rig.ptt_type in ("RTS", "DTR"):
            cfg.rig.ptt_port = ask("Port de la ligne PTT", cfg.rig.ptt_port or cfg.rig.port)
        elif cfg.rig.ptt_type in ("GPIO", "GPION"):
            cfg.rig.ptt_port = ask("Identifiant GPIO (voir doc Hamlib)", cfg.rig.ptt_port or None)
        else:
            cfg.rig.ptt_port = ""
    else:
        cfg.rig.port = ""

    while True:
        print("\nTest de liaison (lecture seule, aucune émission)...")
        try:
            res = test_link(cfg.rig, hamlib_dir=cfg.tools.hamlib_dir)
            print(f"  OK : fréquence {res['freq']} Hz, mode {res['mode']}, PTT {res['ptt']}")
            if res.get("ptt_forced_rx"):
                print("  ATTENTION : le PTT était actif, retour en réception forcé.")
            break
        except SetupError as exc:
            print(f"  ÉCHEC : {exc}")
            if not ask_yes_no("Réessayer", True):
                if ask_yes_no("Continuer sans test (déconseillé)", False):
                    break
                raise SystemExit("Abandon.")

    if cfg.rig.model != DUMMY_MODEL:
        cap = choose("Audio reçu du TRX (capture)", [(d, lbl) for d, lbl in list_audio_devices("capture")],
                     current=cfg.audio.capture_device)
        play = choose("Audio vers le TRX (lecture)", [(d, lbl) for d, lbl in list_audio_devices("playback")],
                      current=cfg.audio.playback_device)
        cfg.audio.capture_device, cfg.audio.playback_device = cap, play

    ask_spectrum(cfg)
    ask_bands(cfg, keep_offer=base is not None)
    ask_network(cfg, tls_dir)
    if cfg.clients:
        print("\nComptes déjà autorisés : " + ", ".join(c.id for c in cfg.clients))
        if not ask_yes_no("Les garder", True):
            cfg.clients = []
    ask_clients(cfg)
    power = ask("Puissance maximale du poste en watts (0 = inconnue : la page affichera des %)", str(cfg.rig.max_power_w))
    cfg.rig.max_power_w = int(power) if power.isdigit() and int(power) <= 2000 else cfg.rig.max_power_w
    tot = ask("Durée max d'une émission en secondes (TOT)", str(cfg.safety.tot_s))
    cfg.safety.tot_s = int(tot) if tot.isdigit() else cfg.safety.tot_s
    return cfg


def ask_bands(cfg: Config, keep_offer: bool = False) -> None:
    if keep_offer:
        current = ("délégué au poste" if not cfg.safety.enforce_bands
                   else f"par la station, {len(cfg.bands)} bande(s)" if cfg.bands else "par la station, AUCUNE bande (réception seule)")
        if ask_yes_no(f"\nContrôle des bandes d'émission : {current}. Le garder", True):
            return
    print("\nContrôle des bandes d'émission. Beaucoup de postes l'assurent déjà eux-mêmes (réglage « TX limit » des Icom).")
    if ask_yes_no("Le poste interdit-il déjà d'émettre hors des bandes amateur (la station n'a alors pas à le vérifier)", False):
        cfg.safety.enforce_bands = False
    else:
        cfg.safety.enforce_bands = True
        print("Bandes autorisées en émission : points de départ région 1 IARU, À VÉRIFIER selon ta licence.")
        if ask_yes_no("Charger ces bandes par défaut (tu pourras les éditer dans station.toml)", False):
            cfg.bands = list(DEFAULT_BANDS_R1)
        elif not cfg.bands:
            print("Aucune bande chargée : réception seule tant que station.toml n'est pas complété.")


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
    print("\nAccès à la station depuis d'autres appareils (téléphone, tablette).")
    options = [("local", "Cette machine seulement (127.0.0.1) : essais sur ce PC"),
               ("lan", "Réseau local ou VPN, en HTTPS avec un certificat généré ici (recommandé)")]
    current = ""
    if n.gateway_bind not in ("127.0.0.1", "") or n.tls_cert:
        current = "keep"
        options.insert(0, ("keep", f"Garder le réglage actuel ({n.gateway_bind}:{n.gateway_port}, "
                                   f"{'HTTPS' if n.tls_cert else 'sans HTTPS'})"))
    picked = choose("Accès", options, manual_label="Adresse d'écoute à la main", current=current)
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
        print("  Module « cryptography » absent : certificat impossible. Accès limité à cette machine "
              "(relance l'installation pour l'ajouter).")
        n.gateway_bind = "127.0.0.1"
        return
    n.gateway_bind, n.allow_insecure_http = "0.0.0.0", False
    print(f"  Certificat créé pour : {', '.join(hosts)}")
    for address in hosts[:-2] or ["<adresse de ce PC>"]:
        print(f"  Adresse à ouvrir sur le téléphone : https://{address}:{n.gateway_port}")
    print("  Le navigateur affichera un avertissement (certificat non reconnu) : c'est attendu, voir le guide.")


def _make_certificate(hosts: list[str], folder: Path, cfg: Config) -> None:
    from .gateway.api.tls import generate_self_signed
    cert, key = folder / "station-cert.pem", folder / "station-key.pem"
    generate_self_signed(hosts, cert, key)
    protect(cert)
    protect(key)
    cfg.network.tls_cert, cfg.network.tls_key = str(cert), str(key)


def choose_password(login: str, ask_password: Callable[[str], str] = getpass.getpass,
                    say: Callable[[str], None] = print) -> str:
    """Saisie masquée avec double saisie et règle de robustesse ; Entrée = en générer un fort."""
    while True:
        first = ask_password("  Mot de passe (Entrée = en générer un fort) : ")
        if not first:
            generated = generate_password()
            say(f"  Mot de passe généré : {generated}")
            say("  Note-le maintenant : il n'est PAS enregistré en clair (seule son empreinte l'est).")
            return generated
        problem = password_problem(first, login)
        if problem:
            say(f"  Refusé : {problem}.")
            continue
        if ask_password("  Confirme le mot de passe : ") != first:
            say("  Les deux saisies diffèrent, recommence.")
            continue
        return first


def _check_login_and_password(cfg: Config, name: str, password: str, existing: bool) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
        raise SetupError(f"[[clients]] identifiant invalide : {name!r} (lettres, chiffres, _ et -, 32 max)")
    if existing != any(c.id == name for c in cfg.clients):
        raise SetupError(f"[[clients]] identifiant {'inconnu' if existing else 'en double'} : {name}")
    problem = password_problem(password, name)
    if problem:
        raise SetupError(f"mot de passe refusé : {problem}")


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
    print("\nClients autorisés à se connecter (smartphone, voiture...). Entrée pour terminer.")
    while True:
        name = input("Identifiant du client (ex. phone) : ").strip()
        if not name:
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) or any(c.id == name for c in cfg.clients):
            print("  Identifiant invalide ou déjà utilisé (lettres, chiffres, _ et -, 32 max).")
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
        raise SetupError("configuration invalide :\n  - " + "\n  - ".join(problems))
    output.parent.mkdir(parents=True, exist_ok=True)
    previous = output.stat() if output.exists() else None
    if previous is not None:
        backup = output.with_suffix(output.suffix + ".bak")
        shutil.copy2(output, backup)                # copy2 garde les droits : la sauvegarde reste protégée
        print(f"Ancienne configuration sauvegardée : {backup}")
    output.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    protect(output, previous)   # le fichier contient les empreintes des mots de passe : root + groupe trx, 0640 au plus
    cfgmod.load(output)  # relecture : garantit que le fichier écrit est bien valide
    print(f"Configuration écrite : {output}")
    for w in cfgmod.warnings(cfg):
        print(f"  ! {w}")


def load_base(path: Path | None) -> Config | None:
    """Configuration de départ de l'assistant, même incomplète ; None si absente ou illisible."""
    if path is None:
        return None
    try:
        cfg, problems = cfgmod.load_unchecked(path)
    except (OSError, cfgmod.ConfigError) as exc:
        print(f"Configuration {path} illisible, on repart de zéro : {exc}")
        return None
    if problems:
        print(f"Configuration reprise de {path}, à compléter :")
        for problem in problems:
            print(f"  - {problem}")
    return cfg


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
                    help="génère un certificat TLS auto-signé pour ces noms/adresses IP et l'active (--output)")
    ap.add_argument("--base", type=Path, metavar="FICHIER",
                    help="reprend ce fichier comme point de départ (ex. configuration importée d'un autre PC) ; "
                         "par défaut, le fichier --output s'il existe")
    ap.add_argument("--spectre", metavar="PORT",
                    help="vérifie le second port CI-V du poste (Icom, station arrêtée) et active le waterfall HF ; "
                         "« off » le désactive (--output)")
    ap.add_argument("--adresse-civ", metavar="HEX", help="avec --spectre : adresse CI-V attendue (ex. B6) ; défaut : recherche")
    ap.add_argument("--reglages-verifies", action="store_true",
                    help="avec --spectre : USB SEND / USB Keying déjà vérifiés (pas de question)")
    ap.add_argument("--dummy", action="store_true",
                    help="génère sans questions une config de développement (poste factice Hamlib)")
    args = ap.parse_args(argv)
    try:
        if args.spectre:
            return _cli_spectrum(args)
        if args.add_client or args.set_password or args.self_signed or args.tx_modes or args.bands or args.max_power is not None:
            cfg = cfgmod.load(args.output)
            if args.max_power is not None:
                if not 0 <= args.max_power <= 2000:
                    print("--max-power : une valeur de 0 à 2000 watts est attendue.", file=sys.stderr)
                    return 2
                cfg.rig.max_power_w = args.max_power
                print("Puissance maximale du poste : " + (f"{args.max_power} W" if args.max_power else "inconnue (affichage en %)"))
            if args.bands:
                cfg.safety.enforce_bands = args.bands == "on"
                print("Contrôle des bandes par la station : " + ("ACTIVÉ" if cfg.safety.enforce_bands else
                      "DÉSACTIVÉ (le poste doit l'assurer : vérifie son réglage « TX limit » ou équivalent)"))
            if args.tx_modes:
                cfg.rig.tx_modes = [] if [m.lower() for m in args.tx_modes] == ["aucun"] else list(args.tx_modes)
                print("Émission permise dans les modes : " + (", ".join(cfg.rig.tx_modes) or "tous (aucune restriction)"))
            if args.add_client:
                add_client(cfg, args.add_client, choose_password(args.add_client))
                print(f"Client « {args.add_client} » ajouté.")
            if args.set_password:
                set_password(cfg, args.set_password, choose_password(args.set_password))
                print(f"Mot de passe de « {args.set_password} » changé.")
            if args.self_signed:
                _make_certificate(args.self_signed, args.output.resolve().parent / "tls", cfg)
                print(f"Certificat auto-signé écrit : {cfg.network.tls_cert}\nLe navigateur affichera un avertissement (certificat non reconnu) : "
                      "à réserver à un essai. Pour un usage durable, voir docs/acces-distant.md.")
            write_config(cfg, args.output)
            return 0
        if args.dummy:
            cfg = dummy_config()
        else:
            base = load_base(args.base or (args.output if args.output.exists() else None))
            cfg = interactive(base, tls_dir=args.output.resolve().parent / "tls")
        write_config(cfg, args.output)
    except cfgmod.ConfigError as exc:
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    except SetupError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nInterrompu, rien n'a été écrit.", file=sys.stderr)
        return 130
    return 0


def _cli_spectrum(args) -> int:
    cfg = cfgmod.load(args.output)
    if args.spectre.strip().lower() == "off":
        disable_spectrum(cfg)
        write_config(cfg, args.output)
        print("Spectre HF désactivé : un seul port, sans waterfall HF. Redémarre la station pour l'appliquer.")
        return 0
    address = None
    if args.adresse_civ:
        address = cfgmod.parse_civ_address(args.adresse_civ)
        if address is None:
            print("--adresse-civ : un nombre hexadécimal de 01 à DF est attendu (ex. B6).", file=sys.stderr)
            return 2
    print(USB_SEND_WARNING)
    if not args.reglages_verifies and input("Tape OUI si ces réglages sont vérifiés : ").strip().upper() != "OUI":
        print("Annulé : le second port n'a pas été ouvert, configuration inchangée.")
        return 2
    print(f"Vérification de {args.spectre} (lecture seule, aucune émission)...")
    try:
        address = check_spectrum_port(cfg, args.spectre, address)
    except SetupError as exc:
        print(f"PROBLÈME DE CONFIGURATION : {exc}\nSpectre NON activé : la station reste en mode normal "
              "(un seul port, sans waterfall HF).", file=sys.stderr)
        return 1
    apply_spectrum(cfg, args.spectre, address)
    write_config(cfg, args.output)
    print(f"OK : spectre HF activé sur {args.spectre} (adresse CI-V {address:02X}h). Redémarre la station ; "
          "elle revérifiera ce port à chaque démarrage et reviendra au mode normal en cas de problème.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
