# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Forme d'installation de la station : paquet MSIX du Microsoft Store, ou installation classique (zip, Debian).

Cahier `docs/store-microsoft-cahier-des-charges.md` (§ 3.4, § 11). Faits relevés à l'essai S0 :
- lancé par un ALIAS d'exécution (`%LOCALAPPDATA%\\Microsoft\\WindowsApps\\trx-….exe`), `sys.executable` vaut le chemin
  de l'alias, qui ajoute ses propres paramètres : un sous-processus se lance avec le VRAI interpréteur du paquet ;
- l'interpréteur du paquet est dans `sys.prefix` (Python embarqué : python.exe, pythonw.exe, trx-station.exe).
"""
from __future__ import annotations

import ctypes
import os
import sys
from functools import lru_cache
from pathlib import Path

APPMODEL_ERROR_NO_PACKAGE = 15700          # GetCurrentPackageFullName : processus hors de tout paquet
ERROR_INSUFFICIENT_BUFFER = 122


@lru_cache(maxsize=1)
def package_full_name() -> str | None:
    """Nom complet du paquet MSIX du processus (ex. « RFDIY.openRemoteTRX_0.245.0.0_x64__… »), None hors paquet."""
    if os.name != "nt":
        return None
    try:
        func = ctypes.windll.kernel32.GetCurrentPackageFullName     # type: ignore[attr-defined]
    except AttributeError:                  # Windows sans modèle d'application (ne devrait plus exister)
        return None
    length = ctypes.c_uint32(0)
    rc = func(ctypes.byref(length), None)
    if rc == APPMODEL_ERROR_NO_PACKAGE or rc != ERROR_INSUFFICIENT_BUFFER:
        return None
    buffer = ctypes.create_unicode_buffer(length.value)
    if func(ctypes.byref(length), buffer) != 0:
        return None
    return buffer.value or None


def is_store() -> bool:
    """Vrai si la station tourne depuis un paquet MSIX (version Microsoft Store)."""
    return package_full_name() is not None


# Nom de famille d'un paquet = « <Name>_<identifiant de l'éditeur> » ; l'identifiant est calculé par Windows à partir
# du champ Publisher : SHA-256 de son texte en UTF-16 LE, 8 premiers octets, 13 caractères de 5 bits (65 bits).
_PUBLISHER_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def publisher_id(publisher: str) -> str:
    """Identifiant d'éditeur de 13 caractères (ex. « 8wekyb3d8bbwe » pour Microsoft)."""
    import hashlib
    value = int.from_bytes(hashlib.sha256(publisher.encode("utf-16-le")).digest()[:8], "big") << 1
    return "".join(_PUBLISHER_ALPHABET[(value >> (60 - 5 * i)) & 0x1F] for i in range(13))


def family_name(name: str, publisher: str) -> str:
    return f"{name}_{publisher_id(publisher)}"


def package_family_name() -> str | None:
    """Nom de famille du paquet courant (« RF-DIY.COM.openRemoteTRX_… »), None hors paquet."""
    full = package_full_name()
    if not full:
        return None
    parts = full.split("_")                       # Name_Version_Arch_ResourceId_PublisherId
    return f"{parts[0]}_{parts[-1]}" if len(parts) >= 5 else None


def store_page_link(family: str | None = None) -> str | None:
    """Lien qui ouvre la fiche du paquet dans l'application Microsoft Store (mises à jour)."""
    family = family or package_family_name()
    return f"ms-windows-store://pdp/?PFN={family}" if family else None


def app_launch_command(app_id: str, family: str | None = None) -> list[str] | None:
    """Lance une application du paquet comme le fait Windows (tâche de démarrage, menu Démarrer) : seul moyen sûr de
    démarrer la station HORS de la fenêtre de TRX Console (essai S0)."""
    family = family or package_family_name()
    if not family:
        return None
    return ["explorer.exe", f"shell:AppsFolder\\{family}!{app_id}"]


def _is_alias(path: Path) -> bool:
    """Alias d'exécution d'une application empaquetée : fichier de `%LOCALAPPDATA%\\Microsoft\\WindowsApps`."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return False
    try:
        return path.parent.resolve() == (Path(local) / "Microsoft" / "WindowsApps").resolve()
    except OSError:
        return False


def python_executable(*, windowed: bool | None = None) -> str:
    """Interpréteur à utiliser pour lancer un sous-processus Python de la station.

    Hors paquet : `sys.executable` (comportement inchangé). Dans le paquet : le vrai python.exe / pythonw.exe de
    `sys.prefix`, jamais l'alias (qui ajoute ses paramètres) ; `windowed` force pythonw (True) ou python (False),
    None garde le genre de l'interpréteur courant (un trx-station.exe est un pythonw renommé)."""
    current = Path(sys.executable)
    if not is_store() and not _is_alias(current):
        return sys.executable
    if windowed is None:
        windowed = current.name.lower() in ("pythonw.exe", "trx-station.exe") or sys.stdout is None
    candidate = Path(sys.prefix) / ("pythonw.exe" if windowed else "python.exe")
    return str(candidate) if candidate.exists() else sys.executable
