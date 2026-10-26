"""Réinitialisation USB par sysfs (Linux uniquement)."""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)


def find_usb_authorized(port: str, sys_root: str = "/sys") -> Path | None:
    """Remonte de /dev/ttyUSBx jusqu'au périphérique USB parent et retourne son fichier `authorized`."""
    name = os.path.basename(os.path.realpath(port))
    node = Path(os.path.realpath(Path(sys_root) / "class" / "tty" / name / "device"))
    for candidate in (node, *node.parents):
        if (candidate / "authorized").is_file() and (candidate / "idVendor").exists():
            return candidate / "authorized"
        if str(candidate) == sys_root:
            break
    return None


def reset_usb_sysfs(port: str, sys_root: str = "/sys", sleep: Callable[[float], None] = time.sleep) -> bool:
    authorized = find_usb_authorized(port, sys_root) if port else None
    if authorized is None:
        log.error("réinitialisation USB impossible : périphérique introuvable dans /sys")
        return False
    try:
        authorized.write_text("0")
        sleep(1.0)
        authorized.write_text("1")
        sleep(2.0)
        return True
    except OSError as exc:
        log.error("réinitialisation USB en erreur : %s", exc)
        return False
