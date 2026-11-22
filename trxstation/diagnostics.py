# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Diagnostic complet de la station (commande `trx-console --diagnostic`).

Chaque test rend un résultat : OK, ATTENTION (fonctionne mais à surveiller), ERREUR (bloquant) ou INFO,
avec une phrase en langage courant et, si possible, le geste qui corrige. Aucun test ne déclenche
d'émission ni ne modifie le système : le diagnostic se contente de lire.

Textes dans la langue de l'outil (lot L3) : catalogues `trxstation/i18n/diagnostic.<langue>.json`, le français en
référence. Restent tels quels : noms de services, fichiers, commandes, réglages, et les textes venus d'ailleurs
(validation de station.toml, conseils du son du bureau, messages des modules, sorties des commandes).

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
from .audio_devices import card_name, desktop_audio_advice, list_audio_devices, parse_audio_list, real_device_names
from .config import Config
from .fsperm import SERVICE_GROUP
from .hamlib import find_tool
from .i18n import tool_translator
from .paths import default_config_path
from .ports import list_serial_ports

CONFIG_PATH = default_config_path()             # /etc/trx-remote/station.toml ; Windows : %PROGRAMDATA%\trx-remote
UNITS = ("rigctld.service", "trx-gateway.service", "trx-supervisor.service")
# Chemins Linux : PurePosixPath pour qu'ils gardent leurs « / » même quand les tests tournent sous Windows
MM_RULE = PurePosixPath("/etc/udev/rules.d/99-trx-remote-modemmanager.rules")
BRLTTY_RULE_NAMES = ("85-brltty.rules",)
UDEV_SYSTEM_DIRS = (PurePosixPath("/usr/lib/udev/rules.d"), PurePosixPath("/lib/udev/rules.d"))
# (module, indispensable) ; son rôle : clé « module.role.<module> » des catalogues
MODULES = (("aiohttp", True), ("aiortc", True), ("sounddevice", True), ("cryptography", False),
           ("textual", False), ("serial", False))

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
# Marques en français (référence) ; affichées dans la langue de l'outil par la clé « label.<état> », toutes reconnues
# et colorées par la page (TONES de console_web/static/flow.js).
LABELS = {OK: "[OK]", WARN: "[ATTENTION]", FAIL: "[ERREUR]", INFO: "[INFO]"}
COLORS = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", INFO: "\033[36m"}
CLUSTER_STATES = ("connected", "connecting", "reconnecting", "failed", "disabled")   # clés « cluster.state.<état> »


def _t(key: str, **fields) -> str:
    """Texte montré à l'opérateur, dans la langue de l'outil (`TRX_LANG` posée par openRemoteTRX Console, sinon menu 0, sinon
    le système) ; lu À CHAQUE APPEL (les tests changent la langue après l'import)."""
    return tool_translator("diagnostic")(key, **fields)


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

    def wifi_interfaces(self) -> list[str]:
        """Interfaces Wi-Fi de la machine (Linux : /sys/class/net/<nom>/wireless) ; [] ailleurs."""
        try:
            return sorted(p.parent.name for p in Path("/sys/class/net").glob("*/wireless"))
        except OSError:
            return []

    def local_addresses(self) -> list[str]:
        from .setup_wizard import local_addresses
        return local_addresses()

    def previous_version(self) -> str | None:
        from .update.apply import previous_version
        return previous_version()


# --------------------------------------------------------------------------- tests


def check_system(sysm: System) -> list[Check]:
    s = _t("section.system")
    out: list[Check] = []
    release = sysm.read_text("/etc/os-release")
    if release is None:
        out.append(Check(s, _t("name.os"), INFO, _t("system.os_partial", platform=sysm.platform)))
    else:
        info = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', release, re.M))
        name, ident, version = info.get("PRETTY_NAME", "?"), info.get("ID", ""), info.get("VERSION_ID", "0")
        family = f"{ident} {info.get('ID_LIKE', '')}"
        major = int(re.match(r"\d*", version).group() or 0)
        if "debian" in family and major >= 12:
            out.append(Check(s, _t("name.os"), OK, name))
        elif "debian" in family or "raspbian" in family:
            out.append(Check(s, _t("name.os"), WARN, _t("system.debian_old", name=name)))
        else:
            out.append(Check(s, _t("name.os"), WARN, _t("system.not_debian", name=name)))
    version = sys.version_info
    out.append(Check(s, "Python", OK if version >= (3, 11) else FAIL, f"{version.major}.{version.minor}.{version.micro}",
                     "" if version >= (3, 11) else _t("fix.python")))
    try:
        free_gb = sysm.free_bytes("/") / 1e9
        status = OK if free_gb >= 1 else WARN if free_gb >= 0.3 else FAIL
        out.append(Check(s, _t("name.disk"), status, _t("system.disk_free", free=f"{free_gb:.1f}"),
                         "" if status == OK else _t("fix.disk")))
    except OSError:
        pass
    if sysm.platform.startswith("linux"):                       # journal système lisible par CE compte (étape 354)
        out.extend(check_journal(sysm))
    from .cpu_temp import read_cpu_temp
    temp = read_cpu_temp(getattr(sysm, "sys_root", "/sys"))     # processeur (coretemp...), jamais la carte mère
    if temp is not None:
        celsius = temp.celsius
        out.append(Check(s, _t("name.cpu_temp"), OK if celsius < 80 else WARN, f"{celsius:.0f} °C ({temp.source})",
                         "" if celsius < 80 else _t("fix.cpu_temp")))
    return out


JOURNAL_DENIED = ("insufficient permissions", "no journal files were opened", "not seeing messages from other")


def check_journal(sysm: System) -> list[Check]:
    """Le journal système (démarrages des services, messages de rigctld, noyau) est-il lisible par ce compte ? Sinon le
    rapport de dépannage (menu 6.3) perd ses journaux : compte hors des groupes systemd-journal / adm (cas réel d'un
    bêta-testeur, rapport du 2026-11-19)."""
    code, out = sysm.run(["journalctl", "--no-pager", "-q", "-n", "1"])
    if code == 127 or "introuvable" in (out or "").lower() or "not found" in (out or "").lower():
        return []                                              # pas de systemd : rien à dire
    user = os.environ.get("SUDO_USER") or os.environ.get("USER") or os.environ.get("LOGNAME") or "?"
    if any(word in (out or "").lower() for word in JOURNAL_DENIED):
        return [Check(_t("section.system"), _t("name.journal"), WARN, _t("system.journal_denied", user=user),
                      _t("fix.journal_denied", user=user))]
    return [Check(_t("section.system"), _t("name.journal"), OK, _t("system.journal_ok"))]


def hamlib_version(text: str) -> tuple[int, ...] | None:
    """(4, 7, 2) de « rigctld Hamlib 4.7.2 2026-06-21... » ; None si illisible."""
    match = re.search(r"Hamlib\s+(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(g) for g in match.groups() if g is not None) if match else None


def check_software(sysm: System, cfg: Config | None) -> list[Check]:
    s = _t("section.software")
    out: list[Check] = []
    for module, needed in MODULES:
        role = _t(f"module.role.{module}")
        if sysm.module_present(module):
            out.append(Check(s, _t("name.module", module=module), OK, role))
        else:
            out.append(Check(s, _t("name.module", module=module), FAIL if needed else WARN,
                             _t("software.module_missing", role=role), _t("fix.reinstall")))
    hamlib_dir = cfg.tools.hamlib_dir if cfg else ""
    rigctld = sysm.find_tool("rigctld", hamlib_dir)
    if rigctld is None:
        out.append(Check(s, "Hamlib (rigctld)", FAIL, _t("software.not_found"), "sudo apt install libhamlib-utils"))
    else:
        _, text = sysm.run([rigctld, "--version"])
        out.append(Check(s, "Hamlib (rigctld)", OK, (text.strip().splitlines() or [rigctld])[0]))
        if cfg is not None and cfg.spectrum.enabled and cfg.spectrum.source == "rigctld":
            version = hamlib_version(text)
            if version is None:
                out.append(Check(s, _t("name.spectrum"), WARN, _t("software.hamlib_unreadable")))
            elif version < (4, 6):
                out.append(Check(s, _t("name.spectrum"), FAIL,
                                 _t("software.hamlib_too_old", version=".".join(map(str, version))),
                                 _t("fix.hamlib_update")))
            else:
                out.append(Check(s, _t("name.spectrum"), OK, _t("software.hamlib_ok")))
    return out


def check_config(sysm: System, path: Path) -> tuple[list[Check], Config | None]:
    s = _t("section.config")
    name = _t("name.config_file")
    if not sysm.exists(path):
        return [Check(s, name, WARN, _t("config.absent", path=path), _t("fix.assistant"))], None
    try:
        cfg = cfgmod.load(path)
    except cfgmod.ConfigError as exc:
        return [Check(s, name, FAIL, _t("config.invalid", path=path, problems=" ; ".join(exc.problems)),
                      _t("fix.assistant"))], None
    except PermissionError:
        return [Check(s, name, WARN, _t("config.unreadable", path=path), _t("fix.relogin_or_reinstall"))], None
    out = [Check(s, name, OK, str(path))]
    st = sysm.stat(path)
    gid, _ = sysm.group_members(SERVICE_GROUP)
    if st is not None and gid is not None and not (st.st_gid == gid and st.st_mode & 0o040):
        out.append(Check(s, _t("name.file_rights"), FAIL, _t("config.service_cannot_read"),
                         f"sudo chgrp {SERVICE_GROUP} {path} && sudo chmod 640 {path}"))
    elif st is not None and st.st_mode & 0o007:
        out.append(Check(s, _t("name.file_rights"), WARN, _t("config.world_readable"), f"sudo chmod 640 {path}"))
    for warning in cfgmod.warnings(cfg):
        out.append(Check(s, _t("name.setting"), WARN, warning))
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
    s = _t("section.hardware")
    out: list[Check] = []
    linux = sysm.platform.startswith("linux")
    if linux:
        user = sysm.user()
        for group, role in (("dialout", _t("hardware.role_dialout")), (SERVICE_GROUP, _t("hardware.role_trx"))):
            state = _membership(sysm, user, group)
            if state == "ok":
                out.append(Check(s, _t("name.group", group=group), OK, role))
            elif state == "relogin":
                out.append(Check(s, _t("name.group", group=group), WARN, _t("hardware.group_relogin", user=user),
                                 _t("fix.group_relogin")))
            else:
                out.append(Check(s, _t("name.group", group=group), WARN,
                                 _t("hardware.group_absent", user=user, role=role),
                                 _t("fix.group_add", group=group, user=user)))
    ports = sysm.serial_ports()
    out.append(Check(s, _t("name.serial_ports"), INFO if ports else WARN, ", ".join(ports) or _t("common.none"),
                     "" if ports else _t("fix.serial_ports")))
    if cfg is not None and cfg.rig.model != cfgmod.DUMMY_MODEL and cfg.rig.port:
        models = _hamlib_models(sysm, cfg)
        if models and cfg.rig.model not in models:
            out.append(Check(s, _t("name.rig_model"), FAIL, _t("hardware.model_unknown", model=cfg.rig.model),
                             _t("fix.model_unknown")))
        elif models:
            out.append(Check(s, _t("name.rig_model"), OK, f"{cfg.rig.model} : {models[cfg.rig.model]}"))
        if sysm.exists(cfg.rig.port):
            out.append(Check(s, _t("name.cat_port"), OK, cfg.rig.port))
        else:
            out.append(Check(s, _t("name.cat_port"), FAIL, _t("hardware.cat_absent", port=cfg.rig.port),
                             _t("fix.cat_absent")))
    if linux:
        out += _check_usb_intruders(sysm)
        out += _check_audio(sysm, cfg)
    return out


def _check_usb_intruders(sysm: System) -> list[Check]:
    s = _t("section.hardware")
    out: list[Check] = []
    code, state = sysm.run(["systemctl", "is-active", "ModemManager"])
    if state.strip() == "active" and not sysm.exists(MM_RULE):
        out.append(Check(s, "ModemManager", WARN, _t("hardware.modemmanager"), _t("fix.modemmanager")))
    for name in BRLTTY_RULE_NAMES:
        system_rule = any(sysm.exists(d / name) for d in UDEV_SYSTEM_DIRS)
        if system_rule and not sysm.exists(PurePosixPath("/etc/udev/rules.d") / name):
            out.append(Check(s, "brltty", WARN, _t("hardware.brltty"), _t("fix.brltty")))
    return out


def _check_audio(sysm: System, cfg: Config | None) -> list[Check]:
    s = _t("section.hardware")
    out: list[Check] = []
    captures = sysm.audio_devices("capture")
    playbacks = sysm.audio_devices("playback")
    out.append(Check(s, _t("name.sound_cards"), INFO if captures else WARN,
                     _t("audio.count", inputs=len(captures), outputs=len(playbacks)),
                     "" if captures else _t("fix.sound_cards")))
    if cfg is not None:
        for kind, spec, devices in (("capture", cfg.audio.capture_device, captures),
                                    ("playback", cfg.audio.playback_device, playbacks)):
            label = _t(f"name.card_{kind}")
            for name in real_device_names(spec):
                wanted = name.lower()
                found = any(wanted == d.lower() or wanted in d.lower() or wanted in lbl.lower() for d, lbl in devices)
                if found:
                    out.append(Check(s, label, OK, name))
                    continue
                # Absente de la liste du son, mais la carte est-elle branchée ? Une carte OCCUPÉE (station en marche,
                # son du bureau PipeWire) n'apparaît pas dans la liste de PortAudio ; le noyau, lui, la voit toujours.
                hardware = _alsa_hardware(sysm, kind)
                card = _card_of(name, hardware)
                if card is None:
                    out.append(Check(s, label, FAIL, name, _t("fix.card_missing")))
                elif _gateway_active(sysm):
                    out.append(Check(s, label, OK, _t("audio.used_by_station", name=name)))
                else:
                    out.append(Check(s, label, WARN, _t("audio.busy", name=name, card=card),
                                     desktop_audio_advice("linux") + "\n" + _t("fix.rerun")))
    code, _ = sysm.run(["pgrep", "-x", "pipewire"])
    if code == 0:
        specs = real_device_names(cfg.audio.capture_device, cfg.audio.playback_device) if cfg is not None else []
        cards = {card_name(spec).lower() for spec in specs} - {""}
        taken = []
        for target, label in (("@DEFAULT_AUDIO_SINK@", "out"), ("@DEFAULT_AUDIO_SOURCE@", "in")):
            code, text = sysm.run(["wpctl", "inspect", target])
            if code == 0 and any(c and c in text.lower() for c in cards):
                taken.append(label)
        if taken:
            which = "both" if len(taken) == 2 else taken[0]
            out.append(Check(s, _t("name.pipewire"), WARN, _t(f"audio.desktop_default_{which}"),
                             desktop_audio_advice("linux")))
        else:
            out.append(Check(s, _t("name.pipewire"), INFO, _t("audio.pipewire_active"), _t("fix.pipewire")))
    return out


def _alsa_hardware(sysm: System, kind: str) -> list[tuple[str, str]]:
    """Cartes vues par le noyau (`arecord -l` / `aplay -l`), occupées ou non."""
    code, text = sysm.run(["arecord" if kind == "capture" else "aplay", "-l"])
    return parse_audio_list(text) if code == 0 else []


def _card_of(spec: str, hardware: list[tuple[str, str]]) -> str | None:
    """Carte du noyau correspondant à un nom PortAudio « Nom de la carte: ... (hw:N,M) » ; None si aucune."""
    m = re.search(r"\(hw:(\d+),(\d+)\)\s*$", spec)
    card_name = spec.split(":", 1)[0].strip().lower()
    for device, label in hardware:
        dev = re.search(r"DEV=(\d+)", device)
        name, _, number = label.rpartition(" (carte ")
        if name.strip().lower() == card_name and (m is None or (dev and dev.group(1) == m.group(2))):
            return _t("audio.card_number", number=number.rstrip(")"))
    return None


def _gateway_active(sysm: System) -> bool:
    code, state = sysm.run(["systemctl", "is-active", "trx-gateway"])
    return state.strip() == "active"


def _last_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[-1].strip() if lines else ""


def check_services(sysm: System, cfg: Config | None) -> list[Check]:
    s = _t("section.services")
    if not sysm.platform.startswith("linux") or sysm.which("systemctl") is None:
        return [Check(s, s, INFO, _t("services.no_systemd"))]
    out: list[Check] = []
    for unit in UNITS:
        active = _last_line(sysm.run(["systemctl", "is-active", unit])[1])
        enabled = _last_line(sysm.run(["systemctl", "is-enabled", unit])[1])
        if active == "active":
            out.append(Check(s, unit, OK, _t("services.running", enabled=enabled)))
        elif active == "failed":
            out.append(Check(s, unit, FAIL, _t("services.failed"), _t("fix.service_failed", unit=unit)))
        elif enabled in ("enabled", "static", "indirect"):
            out.append(Check(s, unit, WARN, _t("services.stopped", state=active or _t("common.unknown")),
                             _t("fix.start")))
        else:
            out.append(Check(s, unit, WARN, _t("services.not_installed", state=enabled or _t("common.unknown")),
                             _t("fix.reinstall")))
    if cfg is not None:
        safe_path = Path(cfg.supervisor.state_dir) / "safe_mode"
        safe = sysm.read_text(safe_path)
        if safe is None and sysm.exists(safe_path):
            safe = _t("services.safe_unreadable")     # présent mais illisible : il est bien actif
        if safe is not None:
            out.append(Check(s, _t("name.safe_mode"), FAIL,
                             _t("services.safe_active", reason=safe.strip() or _t("services.reason_unknown")),
                             _t("fix.safe_mode")))
        mtime = sysm.mtime(cfg.supervisor.status_path)
        if mtime is None:
            out.append(Check(s, _t("name.gateway_state"), WARN, _t("services.no_state")))
        else:
            age = sysm.now() - mtime
            out.append(Check(s, _t("name.gateway_state"), OK if age < 5 else WARN,
                             _t("services.state_fresh") if age < 5 else _t("services.state_stale", age=f"{age:.0f}")))
    return out


def check_spectrum(sysm: System, cfg: Config | None) -> list[Check]:
    """Spectre HF par le second port CI-V : état publié par la passerelle (vérifié par elle à chaque ouverture)."""
    if cfg is None or not cfg.spectrum.enabled or cfg.spectrum.source != "civ_port":
        return []
    s, name = _t("section.spectrum"), _t("name.second_port", port=cfg.spectrum.port)
    if not sysm.module_present("serial"):
        return [Check(s, name, FAIL, _t("spectrum.no_pyserial"), _t("fix.pyserial"))]
    text = sysm.read_text(cfg.supervisor.status_path)
    try:
        sp = json.loads(text).get("spectrum", {}) if text else {}
    except (ValueError, AttributeError):
        sp = {}
    state = sp.get("state") if isinstance(sp, dict) else None
    if not state:
        return [Check(s, name, INFO, _t("spectrum.unknown"))]
    if state == "ok":
        return [Check(s, name, OK, _t("spectrum.ok", fps=sp.get("fps", "?")))]
    if state == "error":
        return [Check(s, name, FAIL, _t("spectrum.config_problem", message=str(sp.get("message", ""))[:300]),
                      _t("fix.spectrum", port=cfg.spectrum.port))]
    return [Check(s, name, INFO, _t("spectrum.waiting") if state == "waiting" else _t("spectrum.checking"))]


def _cluster_state_text(state: str) -> str:
    return _t(f"cluster.state.{state}") if state in CLUSTER_STATES else state


def check_cluster(sysm: System, cfg: Config | None, path: Path = CONFIG_PATH) -> list[Check]:
    """Module Cluster DX : sources, droits de secrets.toml, état publié par le module (sans rien lui demander)."""
    if cfg is None:
        return []
    s, c = _t("section.cluster"), cfg.cluster
    module = _t("name.cluster_module")
    if not c.enabled:
        return [Check(s, module, INFO, _t("cluster.disabled"), _t("fix.cluster_menu"))] if c.source else []
    active = [x for x in c.source if x.enabled]
    out = [Check(s, _t("name.cluster_sources"), OK if active else FAIL,
                 _t("cluster.sources_active", count=len(active), names=", ".join(x.name for x in active)) if active
                 else _t("cluster.no_source"), "" if active else _t("fix.cluster_menu"))]
    from .secretstore import path_for
    spath = path_for(path)
    named = sorted({x.secret for x in active if x.secret})
    st = sysm.stat(spath)
    if named and st is None:
        out.append(Check(s, "secrets.toml", FAIL, _t("cluster.secrets_absent", names=", ".join(named)),
                         _t("fix.cluster_password")))
    elif st is not None:
        mode = st.st_mode & 0o777
        if sysm.platform != "win32" and mode & 0o077:
            out.append(Check(s, "secrets.toml", FAIL, _t("cluster.secrets_rights", mode=oct(mode)[2:]),
                             f"sudo chmod 600 {spath} && sudo chown {cfg.modules.run_as} {spath}"))
        else:
            out.append(Check(s, "secrets.toml", OK, _t("cluster.secrets_ok_unix")
                             if sysm.platform != "win32" else _t("cluster.secrets_ok")))
    text = sysm.read_text(Path(cfg.supervisor.state_dir) / "cluster" / "status.json")
    try:
        data = json.loads(text) if text else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        out.append(Check(s, module, WARN, _t("cluster.no_state"), _t("fix.cluster_run")))
        return out
    age = sysm.now() - float(data.get("time") or 0)
    if age > 30:
        out.append(Check(s, module, WARN, _t("cluster.state_old", age=f"{age:.0f}"), _t("fix.cluster_journal")))
        return out
    for name, src in (data.get("sources") or {}).items():
        if not isinstance(src, dict):
            continue
        state = str(src.get("state", ""))
        level = OK if state == "connected" else FAIL if state == "failed" else WARN
        why = "" if state == "connected" else f" ({str(src.get('message', ''))[:160]})" if src.get("message") else ""
        out.append(Check(s, _t("name.cluster_source", name=str(name)[:32]), level,
                         f"{_cluster_state_text(state)}{why}",
                         "" if level == OK else _t("fix.cluster_test")))
    counters = data.get("counters") or {}
    last = counters.get("last_spot_age_s")
    if last is None:
        out.append(Check(s, _t("name.last_spot"), WARN, _t("cluster.no_spot")))
    else:
        out.append(Check(s, _t("name.last_spot"), OK if last < 900 else WARN,
                         _t("cluster.last_spot", age=f"{last:.0f}", per_minute=counters.get("per_minute", 0),
                            cache=counters.get("cache", 0), malformed=counters.get("malformed", 0))))
    cty = data.get("cty") or {}
    if cty.get("problem"):
        out.append(Check(s, "cty.dat", WARN, _t("cluster.cty", problem=str(cty["problem"])[:200]), _t("fix.cty")))
    return out


def check_network(sysm: System, cfg: Config | None) -> list[Check]:
    s = _t("section.network")
    out: list[Check] = []
    addresses = sysm.local_addresses()
    out.append(Check(s, _t("name.addresses"), INFO if addresses else WARN, ", ".join(addresses) or _t("common.none_f"),
                     "" if addresses else _t("fix.network")))
    wifi = sysm.wifi_interfaces() if sysm.platform.startswith("linux") else []
    if wifi and not sysm.which("iw"):                       # rapport de dépannage sans signal ni veille du Wi-Fi
        out.append(Check(s, _t("name.iw"), WARN, _t("network.iw_missing", interfaces=", ".join(wifi)), _t("fix.iw")))
    if cfg is None:
        return out
    n = cfg.network
    problem = cfgmod.exposure_problem(cfg)
    if problem:
        out.append(Check(s, _t("name.access_security"), FAIL, problem, _t("fix.access_step")))
    scheme = "https" if n.tls_cert else "http"
    if n.gateway_bind in ("0.0.0.0", "::"):
        urls = ([f"{scheme}://{a}:{n.gateway_port}" for a in addresses]
                or [f"{scheme}://{_t('network.address_placeholder')}:{n.gateway_port}"])
        out.append(Check(s, _t("name.phone_access"), INFO, _t("network.or").join(urls)))
    elif cfgmod.is_loopback(n.gateway_bind):
        out.append(Check(s, _t("name.phone_access"), INFO, _t("network.local_only"), _t("fix.access_step")))
    if n.tls_cert:
        present = sysm.exists(n.tls_cert) and sysm.exists(n.tls_key)
        out.append(Check(s, _t("name.https_cert"), OK if present else FAIL, n.tls_cert,
                         "" if present else _t("fix.access_step")))
    host = "127.0.0.1" if n.gateway_bind in ("0.0.0.0", "::") else n.gateway_bind
    if cfg.clients and not problem:
        if sysm.can_connect(host, n.gateway_port):
            out.append(Check(s, _t("name.station_port"), OK, _t("network.port_listening", port=n.gateway_port)))
        else:
            out.append(Check(s, _t("name.station_port"), WARN, _t("network.port_closed", port=n.gateway_port),
                             _t("fix.journal_reason")))
    if sysm.which("ufw"):
        _, text = sysm.run(["ufw", "status"])
        if "active" in text.lower() and "inactive" not in text.lower():
            out.append(Check(s, _t("name.firewall"), WARN, _t("network.ufw", port=n.gateway_port),
                             f"sudo ufw allow {n.gateway_port}/tcp"))
    return out


def check_update(sysm: System, cfg: Config | None) -> list[Check]:
    from . import __version__
    from .update.check import clean_text, parse_state, parse_version, state_path
    from .update.pubkey import PUBLIC_KEYS

    s = _t("section.update")
    search = _t("name.update_search")
    out = [Check(s, _t("name.installed"), INFO, __version__)]
    previous = sysm.previous_version()
    if previous:
        out.append(Check(s, _t("name.previous"), INFO, _t("update.previous", version=previous)))
    if not PUBLIC_KEYS:
        out.append(Check(s, _t("name.signing_key"), WARN, _t("update.no_key"), _t("fix.install_published")))
    if cfg is None:
        return out
    if not cfg.update.enabled:
        out.append(Check(s, search, INFO, _t("update.disabled")))
        return out
    text = sysm.read_text(state_path(cfg.supervisor.state_dir))
    state = parse_state(text) if text is not None else None
    if state is None:
        out.append(Check(s, search, INFO, _t("update.not_yet")))
        return out
    age_h = max(0.0, sysm.now() - state.checked_at) / 3600
    stale = state.ok and age_h > 72
    if not state.ok:
        out.append(Check(s, search, WARN,
                         _t("update.failed", error=clean_text(state.error, 200, single_line=True)),
                         _t("fix.internet")))
    elif stale:
        out.append(Check(s, search, WARN, _t("update.stale", days=f"{age_h / 24:.0f}"),
                         "systemctl status trx-update-check.timer"))
    release = state.release
    if release is not None and (parse_version(release.version) or ()) > (parse_version(__version__) or ()):
        out.append(Check(s, _t("name.new_version"), INFO, _t("update.available", version=release.version),
                         _t("fix.update_menu")))
    elif state.ok and not stale:
        out.append(Check(s, search, OK, _t("update.up_to_date", hours=f"{age_h:.0f}")))
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
    checks += check_cluster(sysm, cfg, path)
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
        label = _t(f"label.{check.status}")
        if color:
            label = f"{COLORS[check.status]}{label}\033[0m"
        lines.append("  " + _t("format.line", label=label, name=check.name, message=check.message))
        if check.fix and check.status in (WARN, FAIL):
            lines.append("      -> " + check.fix.replace("\n", "\n         "))
    lines.append("\n" + _t("format.summary", ok=counts[OK], warn=counts[WARN], fail=counts[FAIL]))
    if counts[FAIL] == 0 and counts[WARN] == 0:
        lines.append(_t("format.all_green"))
    return "\n".join(lines).lstrip("\n")


def exit_code(checks: Iterable[Check]) -> int:
    return 1 if any(c.status == FAIL for c in checks) else 0
