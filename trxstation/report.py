# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Rapport de dépannage : un zip à joindre à une demande d'aide, SANS secret.

Contenu : résultat du diagnostic, configuration expurgée (empreintes de mots de passe, jetons et sujet
ntfy masqués), journaux des services, journal d'installation, versions et matériel détecté, état du
Cluster DX (status.json), et les 10 derniers rapports « Signaler un problème » envoyés par la page (texte relu et
validé par l'utilisateur avant l'envoi). JAMAIS secrets.toml, ni le journal du cluster (texte venu d'internet).
"""
from __future__ import annotations

import datetime
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
    "materiel.txt": [["ls", "-l", "/dev/serial/by-id/"], ["lsusb"], ["arecord", "-l"], ["aplay", "-l"]],
    "hamlib.txt": [["rigctld", "--version"]],
    "python.txt": [["/opt/trx-remote/venv/bin/python", "-m", "pip", "freeze"]],
    "services.txt": [["systemctl", "status", "--no-pager", *UNITS]],
}


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


def _command_output(sysm: System, commands: list[list[str]]) -> str:
    parts = []
    for cmd in commands:
        code, out = sysm.run(cmd, timeout=30)
        parts.append(f"$ {' '.join(cmd)}  (code {code})\n{out.rstrip()}\n")
    return "\n".join(parts)


def make_report(destination: Path | None = None, *, sysm: System | None = None,
                config_path: Path = CONFIG_PATH, now: datetime.datetime | None = None) -> Path:
    sysm = sysm or System()
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M")
    folder = destination or desktop_dir(sysm=sysm)
    target = folder / f"trx-remote-rapport-{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostic.txt", format_checks(run_all(sysm, config_path)) + "\n")
        config_text = sysm.read_text(config_path)
        archive.writestr("station.toml", redact_config(config_text) if config_text is not None
                         else "# configuration absente ou illisible pour ce compte\n")
        for name, commands in COMMANDS.items():
            archive.writestr(name, _command_output(sysm, commands))
        archive.writestr("journal.txt", _command_output(sysm, [["journalctl", "--no-pager", "-n", "400",
                                                                *[f"--unit={u}" for u in UNITS]]]))
        state_dir = _state_dir(sysm, config_path)
        cluster = sysm.read_text(state_dir / "cluster" / "status.json") if state_dir else None
        archive.writestr("cluster-etat.json", cluster if cluster is not None else "{}\n")
        station_id = sysm.read_text(id_path(state_dir)) if state_dir else None    # GUID de la station
        archive.writestr("station-id.txt", (station_id or "inconnu (station jamais démarrée ?)\n").strip() + "\n")
        for page in page_reports(state_dir)[-MAX_PAGE_REPORTS:]:    # « Signaler un problème » de la page, relus par l'utilisateur
            text = sysm.read_text(page)
            if text is not None:
                archive.writestr(f"rapports-page/{page.name}", text)
        log = sysm.read_text(INSTALL_LOG)
        archive.writestr("installation.log", log if log is not None else "# journal d'installation absent ou illisible\n")
    return target
