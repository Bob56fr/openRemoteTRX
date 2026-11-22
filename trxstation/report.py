# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Rapport de dépannage : un zip à joindre à une demande d'aide, SANS secret.

Contenu : résultat du diagnostic, configuration expurgée (empreintes de mots de passe, jetons et sujet
ntfy masqués), journaux des services, journal d'installation, versions et matériel détecté, état du
Cluster DX (status.json), et les 10 derniers rapports « Signaler un problème » envoyés par la page (texte relu et
validé par l'utilisateur avant l'envoi). JAMAIS secrets.toml, ni le journal du cluster (texte venu d'internet).

Format FIGÉ, décrit dans docs/rapport-format.md (lu par l'analyseur des rapports, dépôt openRemoteTRX-analyseur) : un
nouveau fichier ou champ s'y ajoute, rien ne se renomme. Depuis la station 0.266.0 (étape 354) : `rapport.json` (format,
version, heure UTC, fuseau), `noyau.txt` (messages du noyau, démarrages en cours et précédent), modèle et sous-tension du
Pi dans `materiel.txt`, numéros de série et adresses MAC masqués, journal relu par `sudo -n` si le compte n'a pas les
droits (l'échec du premier essai reste écrit). Depuis 0.268.0 (étape 356) : `reseau.txt` (liaisons, Wi-Fi, signal, mise en
veille du Wi-Fi ; MAC, SSID et adresses IP publiques masqués) et `reseau/donnees.json` (historique ANONYME de la sonde
réseau, celui de l'export de netprobe).
"""
from __future__ import annotations

import datetime
import ipaddress
import io
import json
import os
import re
import tomllib
import zipfile
from pathlib import Path

from .diagnostics import CONFIG_PATH, UNITS, System, format_checks, run_all
from .station_id import id_path

INSTALL_LOG = Path("/var/log/trx-remote-install.log")
COMMANDS = {
    "systeme.txt": [["uname", "-a"], ["cat", "/etc/os-release"], ["systemctl", "get-default"]],
    "materiel.txt": [["ls", "-l", "/dev/serial/by-id/"], ["lsusb"], ["arecord", "-l"], ["aplay", "-l"],
                     ["cat", "/proc/device-tree/model"], ["vcgencmd", "get_throttled"]],      # modèle et sous-tension du Pi
    "hamlib.txt": [["rigctld", "--version"]],
    "python.txt": [["/opt/trx-remote/venv/bin/python", "-m", "pip", "freeze"]],
    "services.txt": [["systemctl", "status", "--no-pager", *UNITS]],
}


REPORT_FORMAT = 1                                     # docs/rapport-format.md
# Messages du noyau : démarrage en cours, puis le précédent (cause d'un arrêt brutal, si le journal est persistant)
KERNEL = [["journalctl", "-k", "-b", "--no-pager", "-n", "400"], ["journalctl", "-k", "-b", "-1", "--no-pager", "-n", "200"]]
KERNEL_FALLBACK = ["dmesg", "--ctime"]
DENIED = re.compile(r"insufficient permissions|permission denied|operation not permitted|not seeing messages from other",
                    re.I)
SERIAL_LINE = re.compile(r"(?i)\b(SerialNumber|Serial Number|iSerial)([ \t]*[:=]?[ \t]*(?:\d+[ \t]+)?)(\S[^\r\n]*)")
BY_ID_SERIAL = re.compile(r"_([A-Za-z0-9]*\d[A-Za-z0-9]*)(-if\d+)")     # usb-Icom_…_13003336-if00 : dernier mot avant -ifNN
MAC = re.compile(r"(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b")


# Numéros de série de CETTE station, relevés dans le rapport puis masqués dans TOUS ses fichiers (étape 358 : un numéro
# peut contenir une espace, « IC-7300MK2 13003336 », et revient dans station.toml, journal.txt, les journaux JSON…)
SERIAL_SOURCES = (
    re.compile(r"\busb-[^\s\"'/]*_([A-Za-z0-9]*\d[A-Za-z0-9]*)-if\d+"),             # noms /dev/serial/by-id
    re.compile(r"\bSN=([^\s\"]+)"),                                                    # [rig] port_usb
    re.compile(r"(?m)^\s*serial\s*=\s*\"([^\"]+)\""),                                    # [sdr] serial
    re.compile(r"(?i)\bSerialNumber:[ \t]*([^\r\n]+)"),                                  # messages USB du noyau
)


def station_serials(texts) -> set[str]:
    """Numéros de série trouvés dans les textes du rapport, et leurs morceaux (« IC-7300MK2 13003336 » donne aussi
    « 13003336 », mais JAMAIS « IC-7300MK2 », nom du modèle que l'analyseur doit garder) ; seulement ce qui ressemble à un numéro (6 caractères au moins, un chiffre au moins)."""
    found: set[str] = set()
    for text in texts:
        for pattern in SERIAL_SOURCES:
            for match in pattern.finditer(text):
                value = match.group(1).strip()
                for part in (value, re.split(r"[\s_]+", value)[-1]):     # jamais le début : c'est le modèle
                    if len(part) >= 6 and any(c.isdigit() for c in part):
                        found.add(part)
    return found


def redact_everywhere(text: str, serials: set[str]) -> str:
    """Masquage final d'un fichier du rapport : numéros de série relevés, puis le masquage des formes connues."""
    for serial in sorted(serials, key=len, reverse=True):
        text = text.replace(serial, "***")
    return redact_hardware(text)


class _Pending(list):
    """Fichiers du rapport gardés en mémoire jusqu'au masquage final (même ordre que l'écriture)."""

    def writestr(self, name: str, text: str) -> None:
        self.append((name, text))

    def __enter__(self) -> "_Pending":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def redact_hardware(text: str) -> str:
    """Numéros de série (messages USB du noyau, noms /dev/serial/by-id) et adresses MAC masqués ; la FORME des lignes
    est gardée (l'analyseur reconnaît toujours le poste par son nom)."""
    text = SERIAL_LINE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    text = BY_ID_SERIAL.sub(r"_***\2", text)
    return MAC.sub("**:**:**:**:**:**", text)


NETWORK = [["ip", "-br", "link"], ["iw", "dev"], ["cat", "/proc/net/wireless"]]
NETWORK_DAYS = 30                                     # historique de la sonde réseau joint au rapport
SSID = re.compile(r"(?im)^(\s*ssid:?[ \t]+)\S.*$")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6 = re.compile(r"(?i)(?<![\w:.])[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?![\w:])")    # vérifiée par ipaddress


def _mask_public(match: re.Match) -> str:
    try:
        return "adresse-publique" if ipaddress.ip_address(match.group(0)).is_global else match.group(0)
    except ValueError:
        return match.group(0)


def redact_network(text: str) -> str:
    """reseau.txt : MAC (et BSSID), nom du réseau Wi-Fi (SSID) et adresses IP PUBLIQUES masqués ; les adresses privées
    restent (elles aident au dépannage et ne désignent personne)."""
    text = SSID.sub(lambda m: m.group(1) + "***", redact_hardware(text))
    return IPV6.sub(_mask_public, IPV4.sub(_mask_public, text))


def wifi_interfaces(iw_dev: str) -> list[str]:
    """Interfaces Wi-Fi d'une sortie de `iw dev` (« Interface wlan0 »)."""
    return re.findall(r"(?m)^\s*Interface\s+(\S+)", iw_dev or "")


def network_output(sysm: System) -> str:
    """reseau.txt : liaisons (`ip -br link`), Wi-Fi (`iw dev`, signal de /proc/net/wireless), puis pour chaque interface
    Wi-Fi sa liaison (`iw dev X link` : signal, débit) et sa mise en veille (`iw dev X get power_save`, cause classique
    de coupures sur un Pi)."""
    code, iw = sysm.run(["iw", "dev"], timeout=30)
    commands = list(NETWORK)
    for name in wifi_interfaces(iw if code == 0 else ""):
        commands += [["iw", "dev", name, "link"], ["iw", "dev", name, "get", "power_save"]]
    return redact_network(_command_output(sysm, commands))


def network_history(state_dir: Path | None, station_id: str) -> tuple[str | None, str]:
    """(donnees.json de l'export ANONYME de la sonde réseau, ou None ; ligne d'explication pour reseau.txt)."""
    if state_dir is None:
        return None, "# historique de la sonde réseau : dossier d'état inconnu (configuration illisible)"
    folder = state_dir / "netprobe"
    if not folder.is_dir():
        return None, "# historique de la sonde réseau : absent (sonde jamais lancée, ou [netprobe] enabled = false)"
    try:
        from . import __version__
        from .netprobe.export import build_export, store_of
        blob = build_export(store_of(state_dir), NETWORK_DAYS, version=__version__, station_id=station_id)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            data = z.read("donnees.json").decode("utf-8")
        return data, f"# historique de la sonde réseau : reseau/donnees.json ({NETWORK_DAYS} jours, anonyme)"
    except Exception as exc:                          # jamais bloquant : l'échec reste écrit dans reseau.txt
        return None, f"# historique de la sonde réseau : illisible ({type(exc).__name__} : {exc})"


def redact_config(text: str) -> str:
    """Masque les secrets d'une station.toml (le reste est utile au dépannage)."""
    text = re.sub(r'(?m)^(\s*(?:password_hash|token|password|api_key|key)\s*=\s*)".*?"', r'\1"***"', text)
    text = re.sub(r'(?m)^(\s*notify_url\s*=\s*")(https?://[^/"]+)?[^"]*(")',
                  lambda m: f"{m.group(1)}{m.group(2) + '/***' if m.group(2) else ''}{m.group(3)}", text)
    return text


def _state_dir(sysm: System, config_path: Path) -> Path | None:
    from . import config as cfgmod
    text = sysm.read_text(config_path)
    if text is None:
        return None
    try:
        cfg, _ = cfgmod.build(tomllib.loads(text))
    except (cfgmod.ConfigError, tomllib.TOMLDecodeError):
        return None
    return Path(cfg.supervisor.state_dir)


MAX_PAGE_REPORTS = 10
JSON_JOURNALS = ("passerelle", "superviseur")      # logsetup.add_json_journal
PAGE_REPORT_NAME = re.compile(r"^page-\d{8}-\d{6}-[A-Za-z0-9_-]{1,32}\.txt$")


def page_reports(state_dir: Path | None) -> list[Path]:
    """Rapports de problème envoyés par la page (gateway/bugreports.py), du plus ancien au plus récent."""
    if state_dir is None:
        return []
    try:
        return sorted(p for p in (state_dir / "reports").iterdir() if PAGE_REPORT_NAME.match(p.name) and p.is_file())
    except OSError:
        return []


def desktop_dir(home: Path | None = None, sysm: System | None = None) -> Path:
    home = home or Path(os.path.expanduser("~" + (os.environ.get("SUDO_USER") or "")))
    sysm = sysm or System()
    code, out = sysm.run(["xdg-user-dir", "DESKTOP"])
    if code == 0 and out.strip() and Path(out.strip()).is_dir():
        return Path(out.strip())
    for name in ("Bureau", "Desktop"):
        if (home / name).is_dir():
            return home / name
    return home


def _command_output(sysm: System, commands: list[list[str]], *, sudo_retry: bool = False) -> str:
    """Sorties au format FIGÉ « $ commande  (code n) » puis la sortie. `sudo_retry` : un refus de droits est relancé
    par `sudo -n` (jamais de mot de passe demandé) ; les DEUX essais restent écrits, l'échec n'est jamais caché."""
    parts = []
    for cmd in commands:
        code, out = sysm.run(cmd, timeout=30)
        parts.append(f"$ {' '.join(cmd)}  (code {code})\n{out.rstrip()}\n")
        if sudo_retry and DENIED.search(out or "") and getattr(sysm, "platform", "linux").startswith("linux"):
            retry = ["sudo", "-n", *cmd]
            code, out = sysm.run(retry, timeout=30)
            parts.append(f"$ {' '.join(retry)}  (code {code})\n{out.rstrip()}\n")
    return "\n".join(parts)


def kernel_output(sysm: System) -> str:
    """noyau.txt : journalctl -k (démarrages en cours et précédent) ; dmesg si journalctl ne donne rien."""
    text = _command_output(sysm, KERNEL, sudo_retry=True)
    if "(code 0)" not in text:
        text += "\n" + _command_output(sysm, [KERNEL_FALLBACK], sudo_retry=True)
    return redact_hardware(text)


def report_meta(sysm: System, now_utc: datetime.datetime | None = None) -> str:
    """rapport.json : format, version de la station, heure UTC de création, fuseau et décalage avec l'UTC (journal.txt
    est en heure locale sans fuseau)."""
    from . import __version__
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    offset = now_utc.astimezone().utcoffset()
    zone = None
    if getattr(sysm, "platform", "linux").startswith("linux"):
        code, out = sysm.run(["timedatectl", "show", "-p", "Timezone", "--value"])
        zone = out.strip() if code == 0 and out.strip() else (sysm.read_text("/etc/timezone") or "").strip() or None
    return json.dumps({"format": REPORT_FORMAT, "station": __version__,
                       "cree_utc": now_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                       "fuseau": zone, "decalage_min": int(offset.total_seconds() // 60) if offset is not None else None},
                      ensure_ascii=False, indent=1) + "\n"


MAX_CRASH_FILES = 10


def crash_files(state_dir: Path | None) -> list[Path]:
    """Traces des outils arrêtés sur une erreur inattendue (crashguard), les plus anciennes d'abord, sans doublon."""
    from .crashguard import CRASH_DIR_NAME, crash_dirs
    folders = ([state_dir / CRASH_DIR_NAME] if state_dir is not None else []) + crash_dirs()
    found: dict[str, Path] = {}
    for folder in folders:
        try:
            for path in folder.glob("*.txt"):
                found.setdefault(path.name, path)
        except OSError:
            continue
    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    return sorted(found.values(), key=mtime)


def make_report(destination: Path | None = None, *, sysm: System | None = None,
                config_path: Path = CONFIG_PATH, now: datetime.datetime | None = None) -> Path:
    sysm = sysm or System()
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M")
    folder = destination or desktop_dir(sysm=sysm)
    target = folder / f"trx-remote-rapport-{stamp}.zip"
    with _Pending() as archive:
        archive.writestr("rapport.json", report_meta(sysm))                  # en tête du zip (format, fuseau)
        archive.writestr("diagnostic.txt", format_checks(run_all(sysm, config_path)) + "\n")
        config_text = sysm.read_text(config_path)
        archive.writestr("station.toml", redact_config(config_text) if config_text is not None
                         else "# configuration absente ou illisible pour ce compte\n")
        for name, commands in COMMANDS.items():
            text = _command_output(sysm, commands)
            archive.writestr(name, redact_hardware(text) if name == "materiel.txt" else text)
        archive.writestr("journal.txt", _command_output(sysm, [["journalctl", "--no-pager", "-n", "400",
                                                                *[f"--unit={u}" for u in UNITS]]], sudo_retry=True))
        archive.writestr("noyau.txt", kernel_output(sysm))
        state_dir = _state_dir(sysm, config_path)
        cluster = sysm.read_text(state_dir / "cluster" / "status.json") if state_dir else None
        archive.writestr("cluster-etat.json", cluster if cluster is not None else "{}\n")
        station_id = sysm.read_text(id_path(state_dir)) if state_dir else None    # GUID de la station
        archive.writestr("station-id.txt", (station_id or "inconnu (station jamais démarrée ?)\n").strip() + "\n")
        for process in JSON_JOURNALS:                # journaux structurés (codes d'erreur), fichier courant seulement
            text = sysm.read_text(state_dir / f"journal-{process}.jsonl") if state_dir else None
            if text is not None:
                archive.writestr(f"journaux/journal-{process}.jsonl", text)
        for page in page_reports(state_dir)[-MAX_PAGE_REPORTS:]:    # « Signaler un problème » de la page, relus par l'utilisateur
            text = sysm.read_text(page)
            if text is not None:
                archive.writestr(f"rapports-page/{page.name}", text)
        for crash in crash_files(state_dir)[-MAX_CRASH_FILES:]:      # outils arrêtés sur une erreur (ORT-9312, étape 201)
            text = sysm.read_text(crash)
            if text is not None:
                archive.writestr(f"plantages/{crash.name}", text)
        history, note = network_history(state_dir, (station_id or "").strip())
        archive.writestr("reseau.txt", network_output(sysm) + "\n" + note + "\n")
        if history is not None:
            archive.writestr("reseau/donnees.json", history)
        log = sysm.read_text(INSTALL_LOG)
        archive.writestr("installation.log", log if log is not None else "# journal d'installation absent ou illisible\n")
    serials = station_serials(text for _, text in archive)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, text in archive:                    # numéros de série et MAC masqués dans TOUS les fichiers
            zipped.writestr(name, redact_everywhere(text, serials))
    return target
