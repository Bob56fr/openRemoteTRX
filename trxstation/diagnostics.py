"""Diagnostic complet de la station (commande `trx-console --diagnostic`).

Chaque test rend un résultat : OK, ATTENTION (fonctionne mais à surveiller), ERREUR (bloquant) ou INFO,
avec une phrase en français courant et, si possible, le geste qui corrige. Aucun test ne déclenche
d'émission ni ne modifie le système : le diagnostic se contente de lire.

Tous les accès au système passent par `System` : les tests le remplacent par un faux.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import config as cfgmod
from .audio_devices import list_audio_devices, real_device_names
from .config import Config
from .fsperm import SERVICE_GROUP
from .hamlib import find_tool
from .ports import list_serial_ports

CONFIG_PATH = Path("/etc/trx-remote/station.toml")
UNITS = ("rigctld.service", "trx-gateway.service", "trx-supervisor.service")
# Chemins Linux : PurePosixPath pour qu'ils gardent leurs « / » même quand les tests tournent sous Windows
MM_RULE = PurePosixPath("/etc/udev/rules.d/99-trx-remote-modemmanager.rules")
BRLTTY_RULE_NAMES = ("85-brltty.rules",)
UDEV_SYSTEM_DIRS = (PurePosixPath("/usr/lib/udev/rules.d"), PurePosixPath("/lib/udev/rules.d"))
MODULES = (("aiohttp", "serveur web de la station", True), ("aiortc", "audio WebRTC", True),
           ("sounddevice", "accès aux cartes son", True), ("cryptography", "certificat HTTPS", False),
           ("textual", "tableau de bord trx-monitor", False))

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
LABELS = {OK: "[OK]", WARN: "[ATTENTION]", FAIL: "[ERREUR]", INFO: "[INFO]"}
COLORS = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", INFO: "\033[36m"}


@dataclass(frozen=True)
class Check:
    section: str
    name: str
    status: str
    message: str
    fix: str = ""


class System:
    """Accès en LECTURE au système ; remplacé par un faux dans les tests."""

    platform = sys.platform

    def run(self, cmd: list[str], timeout: float = 15) -> tuple[int, str]:
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return done.returncode, (done.stdout or "") + (done.stderr or "")
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, str(exc)

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def read_text(self, path: str | Path) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def mtime(self, path: str | Path) -> float | None:
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return None

    def now(self) -> float:
        return time.time()

    def stat(self, path: str | Path) -> os.stat_result | None:
        try:
            return Path(path).stat()
        except OSError:
            return None

    def free_bytes(self, path: str) -> int:
        return shutil.disk_usage(path).free

    def module_present(self, name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    def user(self) -> str:
        return os.environ.get("SUDO_USER") or os.environ.get("USER") or ""

    def group_members(self, group: str) -> tuple[int | None, list[str]]:
        try:
            import grp
            entry = grp.getgrnam(group)
            return entry.gr_gid, list(entry.gr_mem)
        except (ImportError, KeyError):
            return None, []

    def process_gids(self) -> list[int]:
        return list(os.getgroups()) if hasattr(os, "getgroups") else []

    def primary_gid(self, user: str) -> int | None:
        try:
            import pwd
            return pwd.getpwnam(user).pw_gid
        except (ImportError, KeyError):
            return None

    def serial_ports(self) -> list[str]:
        return list_serial_ports()

    def audio_devices(self, kind: str) -> list[tuple[str, str]]:
        return list_audio_devices(kind)

    def find_tool(self, name: str, hamlib_dir: str = "") -> str | None:
        return find_tool(name, hamlib_dir)

    def can_connect(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            return False

    def local_addresses(self) -> list[str]:
        from .setup_wizard import local_addresses
        return local_addresses()

    def previous_version(self) -> str | None:
        from .update.apply import previous_version
        return previous_version()


# --------------------------------------------------------------------------- tests


def check_system(sysm: System) -> list[Check]:
    s = "Système"
    out: list[Check] = []
    release = sysm.read_text("/etc/os-release")
    if release is None:
        out.append(Check(s, "Système d'exploitation", INFO, f"{sysm.platform} (hors Debian : diagnostic partiel)"))
    else:
        info = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', release, re.M))
        name, ident, version = info.get("PRETTY_NAME", "?"), info.get("ID", ""), info.get("VERSION_ID", "0")
        family = f"{ident} {info.get('ID_LIKE', '')}"
        major = int(re.match(r"\d*", version).group() or 0)
        if "debian" in family and major >= 12:
            out.append(Check(s, "Système d'exploitation", OK, name))
        elif "debian" in family or "raspbian" in family:
            out.append(Check(s, "Système d'exploitation", WARN, f"{name} : Debian 12 ou plus récent est conseillé"))
        else:
            out.append(Check(s, "Système d'exploitation", WARN, f"{name} : seul Debian (et Raspberry Pi OS) est testé"))
    version = sys.version_info
    out.append(Check(s, "Python", OK if version >= (3, 11) else FAIL, f"{version.major}.{version.minor}.{version.micro}",
                     "" if version >= (3, 11) else "Python 3.11 ou plus récent est nécessaire (Debian 12 et plus)"))
    try:
        free_gb = sysm.free_bytes("/") / 1e9
        status = OK if free_gb >= 1 else WARN if free_gb >= 0.3 else FAIL
        out.append(Check(s, "Espace disque", status, f"{free_gb:.1f} Go libres",
                         "" if status == OK else "Libère de la place (corbeille, Téléchargements)"))
    except OSError:
        pass
    temp = sysm.read_text("/sys/class/thermal/thermal_zone0/temp")
    if temp and temp.strip().isdigit():
        celsius = int(temp) / 1000
        out.append(Check(s, "Température", OK if celsius < 80 else WARN, f"{celsius:.0f} °C",
                         "" if celsius < 80 else "Vérifie la ventilation du PC"))
    return out


def hamlib_version(text: str) -> tuple[int, ...] | None:
    """(4, 7, 2) de « rigctld Hamlib 4.7.2 2026-06-21... » ; None si illisible."""
    match = re.search(r"Hamlib\s+(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(g) for g in match.groups() if g is not None) if match else None


def check_software(sysm: System, cfg: Config | None) -> list[Check]:
    s = "Logiciels"
    out: list[Check] = []
    for module, role, needed in MODULES:
        if sysm.module_present(module):
            out.append(Check(s, f"Module {module}", OK, role))
        else:
            out.append(Check(s, f"Module {module}", FAIL if needed else WARN, f"absent : {role} indisponible",
                             "Relance l'installation : sudo bash install.sh"))
    hamlib_dir = cfg.tools.hamlib_dir if cfg else ""
    rigctld = sysm.find_tool("rigctld", hamlib_dir)
    if rigctld is None:
        out.append(Check(s, "Hamlib (rigctld)", FAIL, "introuvable", "sudo apt install libhamlib-utils"))
    else:
        _, text = sysm.run([rigctld, "--version"])
        out.append(Check(s, "Hamlib (rigctld)", OK, (text.strip().splitlines() or [rigctld])[0]))
        if cfg is not None and cfg.spectrum.enabled and cfg.spectrum.source == "rigctld":
            version = hamlib_version(text)
            if version is None:
                out.append(Check(s, "Spectre HF", WARN, "version de Hamlib illisible : le spectre exige Hamlib 4.6 ou plus"))
            elif version < (4, 6):
                out.append(Check(s, "Spectre HF", FAIL, f"Hamlib {'.'.join(map(str, version))} trop ancien : 4.6 ou plus "
                                 "nécessaire (rigctld refuserait de démarrer)", "Mets Hamlib à jour, ou [spectrum] enabled = false"))
            else:
                out.append(Check(s, "Spectre HF", OK, "Hamlib assez récent (diffusion locale du spectre)"))
    return out


def check_config(sysm: System, path: Path) -> tuple[list[Check], Config | None]:
    s = "Configuration"
    if not sysm.exists(path):
        return [Check(s, "Fichier de configuration", WARN, f"{path} absent : station pas encore configurée",
                      "TRX Console, menu « Assistant de configuration »")], None
    try:
        cfg = cfgmod.load(path)
    except cfgmod.ConfigError as exc:
        return [Check(s, "Fichier de configuration", FAIL, f"{path} invalide : " + " ; ".join(exc.problems),
                      "TRX Console, menu « Assistant de configuration »")], None
    except PermissionError:
        return [Check(s, "Fichier de configuration", WARN, f"{path} illisible pour ce compte",
                      "Déconnecte-toi puis reconnecte-toi (groupe trx), ou relance l'installation")], None
    out = [Check(s, "Fichier de configuration", OK, str(path))]
    st = sysm.stat(path)
    gid, _ = sysm.group_members(SERVICE_GROUP)
    if st is not None and gid is not None and not (st.st_gid == gid and st.st_mode & 0o040):
        out.append(Check(s, "Droits du fichier", FAIL, "le service (compte trx) ne peut pas le lire",
                         f"sudo chgrp {SERVICE_GROUP} {path} && sudo chmod 640 {path}"))
    elif st is not None and st.st_mode & 0o007:
        out.append(Check(s, "Droits du fichier", WARN, "lisible par tous les comptes (empreintes des mots de passe)",
                         f"sudo chmod 640 {path}"))
    for warning in cfgmod.warnings(cfg):
        out.append(Check(s, "Réglage", WARN, warning))
    return out, cfg


def _hamlib_models(sysm: System, cfg: Config) -> dict[int, str]:
    from .setup_wizard import parse_rig_list
    rigctl = sysm.find_tool("rigctl", cfg.tools.hamlib_dir)
    if rigctl is None:
        return {}
    _, text = sysm.run([rigctl, "-l"], timeout=30)
    return {n: f"{mfg} {model}" for n, mfg, model in parse_rig_list(text)}


def _membership(sysm: System, user: str, group: str) -> str:
    """« ok », « relogin » (inscrit mais session ouverte avant) ou « absent »."""
    gid, members = sysm.group_members(group)
    if gid is None:
        return "absent"
    if gid in sysm.process_gids():
        return "ok"
    if user in members or sysm.primary_gid(user) == gid:
        return "relogin"
    return "absent"


def check_hardware(sysm: System, cfg: Config | None) -> list[Check]:
    s = "Matériel"
    out: list[Check] = []
    linux = sysm.platform.startswith("linux")
    if linux:
        user = sysm.user()
        for group, role in (("dialout", "ports série (tests du poste)"), (SERVICE_GROUP, "lecture de la configuration")):
            state = _membership(sysm, user, group)
            if state == "ok":
                out.append(Check(s, f"Groupe {group}", OK, role))
            elif state == "relogin":
                out.append(Check(s, f"Groupe {group}", WARN, f"accordé à {user}, actif à la prochaine session",
                                 "Déconnecte-toi puis reconnecte-toi (étape 4 du guide)"))
            else:
                out.append(Check(s, f"Groupe {group}", WARN, f"{user} n'en fait pas partie : {role} impossible",
                                 f"sudo usermod -aG {group} {user}, puis déconnexion et reconnexion"))
    ports = sysm.serial_ports()
    out.append(Check(s, "Ports série détectés", INFO if ports else WARN, ", ".join(ports) or "aucun",
                     "" if ports else "Allume le poste et vérifie le câble USB (pas un câble de charge seule)"))
    if cfg is not None and cfg.rig.model != cfgmod.DUMMY_MODEL and cfg.rig.port:
        models = _hamlib_models(sysm, cfg)
        if models and cfg.rig.model not in models:
            out.append(Check(s, "Modèle du poste", FAIL, f"{cfg.rig.model} inconnu de ce Hamlib",
                             "Choisis un modèle proche dans l'assistant, ou installe un Hamlib plus récent"))
        elif models:
            out.append(Check(s, "Modèle du poste", OK, f"{cfg.rig.model} : {models[cfg.rig.model]}"))
        if sysm.exists(cfg.rig.port):
            out.append(Check(s, "Port CAT", OK, cfg.rig.port))
        else:
            out.append(Check(s, "Port CAT", FAIL, f"{cfg.rig.port} absent : poste éteint ou débranché",
                             "Allume le poste, vérifie le câble, puis relance le diagnostic"))
    if linux:
        out += _check_usb_intruders(sysm)
        out += _check_audio(sysm, cfg)
    return out


def _check_usb_intruders(sysm: System) -> list[Check]:
    s = "Matériel"
    out: list[Check] = []
    code, state = sysm.run(["systemctl", "is-active", "ModemManager"])
    if state.strip() == "active" and not sysm.exists(MM_RULE):
        out.append(Check(s, "ModemManager", WARN, "actif : il peut « tester » le port du poste et perturber le CAT",
                         "Relance l'installation : elle lui fait ignorer les ports série"))
    for name in BRLTTY_RULE_NAMES:
        system_rule = any(sysm.exists(d / name) for d in UDEV_SYSTEM_DIRS)
        if system_rule and not sysm.exists(PurePosixPath("/etc/udev/rules.d") / name):
            out.append(Check(s, "brltty", WARN, "peut s'approprier certains adaptateurs série USB (CP210x, CH340)",
                             "Relance l'installation et réponds non à la question sur l'afficheur braille"))
    return out


def _check_audio(sysm: System, cfg: Config | None) -> list[Check]:
    s = "Matériel"
    out: list[Check] = []
    captures = sysm.audio_devices("capture")
    playbacks = sysm.audio_devices("playback")
    out.append(Check(s, "Cartes son", INFO if captures else WARN,
                     f"{len(captures)} entrée(s), {len(playbacks)} sortie(s)",
                     "" if captures else "Branche le câble USB du poste (il contient souvent la carte son)"))
    if cfg is not None:
        for kind, spec, devices in (("capture", cfg.audio.capture_device, captures),
                                    ("lecture", cfg.audio.playback_device, playbacks)):
            for name in real_device_names(spec):
                wanted = name.lower()
                found = any(wanted == d.lower() or wanted in d.lower() or wanted in lbl.lower() for d, lbl in devices)
                out.append(Check(s, f"Carte son ({kind})", OK if found else FAIL, name,
                                 "" if found else "Poste éteint ou débranché ? Sinon rechoisis-la dans l'assistant"))
    code, _ = sysm.run(["pgrep", "-x", "pipewire"])
    if code == 0:
        out.append(Check(s, "Son du bureau (PipeWire)", INFO,
                         "actif : il peut occuper la carte son du poste quand une session est ouverte",
                         "Si la station n'a pas de son, voir « Dépannage » dans le guide"))
    return out


def _last_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[-1].strip() if lines else ""


def check_services(sysm: System, cfg: Config | None) -> list[Check]:
    s = "Services"
    if not sysm.platform.startswith("linux") or sysm.which("systemctl") is None:
        return [Check(s, "Services", INFO, "systemd absent : services non vérifiés")]
    out: list[Check] = []
    for unit in UNITS:
        active = _last_line(sysm.run(["systemctl", "is-active", unit])[1])
        enabled = _last_line(sysm.run(["systemctl", "is-enabled", unit])[1])
        if active == "active":
            out.append(Check(s, unit, OK, f"en marche ({enabled})"))
        elif active == "failed":
            out.append(Check(s, unit, FAIL, "en échec", f"journalctl -u {unit} -n 50 (menu « Journal » de TRX Console)"))
        elif enabled in ("enabled", "static", "indirect"):
            out.append(Check(s, unit, WARN, f"arrêté ({active or 'inconnu'})", "Menu « Démarrer la station »"))
        else:
            out.append(Check(s, unit, WARN, f"non installé ou désactivé ({enabled or 'inconnu'})",
                             "Relance l'installation : sudo bash install.sh"))
    if cfg is not None:
        safe = sysm.read_text(Path(cfg.supervisor.state_dir) / "safe_mode")
        if safe is not None:
            out.append(Check(s, "Mode sûr", FAIL, f"ACTIF : {safe.strip() or 'raison inconnue'}",
                             "Corrige la cause, puis menu « Sortir du mode sûr »"))
        mtime = sysm.mtime(cfg.supervisor.status_path)
        if mtime is None:
            out.append(Check(s, "État de la passerelle", WARN, "aucun fichier d'état : passerelle arrêtée"))
        else:
            age = sysm.now() - mtime
            out.append(Check(s, "État de la passerelle", OK if age < 5 else WARN,
                             "publié à l'instant" if age < 5 else f"figé depuis {age:.0f} s"))
    return out


def check_spectrum(sysm: System, cfg: Config | None) -> list[Check]:
    """Spectre HF par le second port CI-V : état publié par la passerelle (vérifié par elle à chaque ouverture)."""
    if cfg is None or not cfg.spectrum.enabled or cfg.spectrum.source != "civ_port":
        return []
    s, name = "Spectre HF", f"Second port {cfg.spectrum.port}"
    text = sysm.read_text(cfg.supervisor.status_path)
    try:
        sp = json.loads(text).get("spectrum", {}) if text else {}
    except (ValueError, AttributeError):
        sp = {}
    state = sp.get("state") if isinstance(sp, dict) else None
    if not state:
        return [Check(s, name, INFO, "état inconnu : passerelle arrêtée (vérifié à son démarrage)")]
    if state == "ok":
        return [Check(s, name, OK, f"spectre reçu ({sp.get('fps', '?')} balayages/s)")]
    if state == "error":
        return [Check(s, name, FAIL, f"PROBLÈME DE CONFIGURATION : {str(sp.get('message', ''))[:300]}",
                      f"Corrige le réglage du poste, puis vérifie : trx-setup --spectre {cfg.spectrum.port} "
                      "(station arrêtée) ; ou trx-setup --spectre off")]
    return [Check(s, name, INFO, "en attente de la réception confirmée pour ouvrir le port"
                  if state == "waiting" else "vérification en cours")]


def check_network(sysm: System, cfg: Config | None) -> list[Check]:
    s = "Réseau"
    out: list[Check] = []
    addresses = sysm.local_addresses()
    out.append(Check(s, "Adresses de ce PC", INFO if addresses else WARN, ", ".join(addresses) or "aucune",
                     "" if addresses else "Vérifie la connexion réseau (câble ou Wi-Fi)"))
    if cfg is None:
        return out
    n = cfg.network
    problem = cfgmod.exposure_problem(cfg)
    if problem:
        out.append(Check(s, "Sécurité de l'accès", FAIL, problem, "Menu « Assistant de configuration », étape Accès"))
    scheme = "https" if n.tls_cert else "http"
    if n.gateway_bind in ("0.0.0.0", "::"):
        urls = [f"{scheme}://{a}:{n.gateway_port}" for a in addresses] or [f"{scheme}://<adresse>:{n.gateway_port}"]
        out.append(Check(s, "Accès depuis le téléphone", INFO, " ou ".join(urls)))
    elif cfgmod.is_loopback(n.gateway_bind):
        out.append(Check(s, "Accès depuis le téléphone", INFO, "désactivé : station joignable depuis ce PC seulement",
                         "Menu « Assistant de configuration », étape Accès"))
    if n.tls_cert:
        present = sysm.exists(n.tls_cert) and sysm.exists(n.tls_key)
        out.append(Check(s, "Certificat HTTPS", OK if present else FAIL, n.tls_cert,
                         "" if present else "Menu « Assistant de configuration », étape Accès"))
    host = "127.0.0.1" if n.gateway_bind in ("0.0.0.0", "::") else n.gateway_bind
    if cfg.clients and not problem:
        if sysm.can_connect(host, n.gateway_port):
            out.append(Check(s, "Port de la station", OK, f"{n.gateway_port} en écoute"))
        else:
            out.append(Check(s, "Port de la station", WARN, f"{n.gateway_port} fermé : passerelle arrêtée ou API refusée",
                             "Menu « Journal » pour la raison"))
    if sysm.which("ufw"):
        _, text = sysm.run(["ufw", "status"])
        if "active" in text.lower() and "inactive" not in text.lower():
            out.append(Check(s, "Pare-feu (ufw)", WARN, f"actif : le port {n.gateway_port} doit être ouvert",
                             f"sudo ufw allow {n.gateway_port}/tcp"))
    return out


def check_update(sysm: System, cfg: Config | None) -> list[Check]:
    from . import __version__
    from .update.check import clean_text, parse_state, parse_version, state_path
    from .update.pubkey import PUBLIC_KEYS

    s = "Mise à jour"
    out = [Check(s, "Version installée", INFO, __version__)]
    previous = sysm.previous_version()
    if previous:
        out.append(Check(s, "Version précédente", INFO, f"{previous} gardée (retour possible : menu 11)"))
    if not PUBLIC_KEYS:
        out.append(Check(s, "Clé de signature", WARN, "aucune clé connue : mise à jour automatique impossible",
                         "Installe une version publiée (sudo bash install.sh)"))
    if cfg is None:
        return out
    if not cfg.update.enabled:
        out.append(Check(s, "Recherche de mise à jour", INFO, "désactivée ([update] enabled = false)"))
        return out
    text = sysm.read_text(state_path(cfg.supervisor.state_dir))
    state = parse_state(text) if text is not None else None
    if state is None:
        out.append(Check(s, "Recherche de mise à jour", INFO, "pas encore faite (2 minutes après le démarrage)"))
        return out
    age_h = max(0.0, sysm.now() - state.checked_at) / 3600
    stale = state.ok and age_h > 72
    if not state.ok:
        out.append(Check(s, "Recherche de mise à jour", WARN,
                         f"dernière recherche impossible : {clean_text(state.error, 200, single_line=True)}",
                         "Vérifie la connexion Internet ; nouvel essai automatique dans 24 h"))
    elif stale:
        out.append(Check(s, "Recherche de mise à jour", WARN, f"dernière recherche il y a {age_h / 24:.0f} jours",
                         "systemctl status trx-update-check.timer"))
    release = state.release
    if release is not None and (parse_version(release.version) or ()) > (parse_version(__version__) or ()):
        out.append(Check(s, "Nouvelle version", INFO, f"{release.version} disponible", "Menu 10 de TRX Console"))
    elif state.ok and not stale:
        out.append(Check(s, "Recherche de mise à jour", OK, f"à jour (vérifié il y a {age_h:.0f} h)"))
    return out


def run_all(sysm: System | None = None, path: Path = CONFIG_PATH) -> list[Check]:
    sysm = sysm or System()
    checks = check_system(sysm)
    config_checks, cfg = check_config(sysm, path)
    checks += check_software(sysm, cfg)
    checks += config_checks
    checks += check_hardware(sysm, cfg)
    checks += check_services(sysm, cfg)
    checks += check_spectrum(sysm, cfg)
    checks += check_network(sysm, cfg)
    checks += check_update(sysm, cfg)
    return checks


# --------------------------------------------------------------------------- affichage


def format_checks(checks: Iterable[Check], color: bool = False) -> str:
    lines: list[str] = []
    section = None
    counts = {OK: 0, WARN: 0, FAIL: 0, INFO: 0}
    for check in checks:
        counts[check.status] += 1
        if check.section != section:
            section = check.section
            lines.append(f"\n== {section} ==")
        label = LABELS[check.status]
        if color:
            label = f"{COLORS[check.status]}{label}\033[0m"
        lines.append(f"  {label} {check.name} : {check.message}")
        if check.fix and check.status in (WARN, FAIL):
            lines.append(f"      -> {check.fix}")
    lines.append(f"\nBilan : {counts[OK]} OK, {counts[WARN]} à surveiller, {counts[FAIL]} erreur(s).")
    if counts[FAIL] == 0 and counts[WARN] == 0:
        lines.append("Tout est vert.")
    return "\n".join(lines).lstrip("\n")


def exit_code(checks: Iterable[Check]) -> int:
    return 1 if any(c.status == FAIL for c in checks) else 0
