# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Rapport de dépannage envoyé par le monitoring (cahier § 10 et § 17.6, lot R4).

C'est le rapport du menu 6.3 (`trxstation/report.py`, déjà sans mot de passe), fabriqué par la station AIDÉE, puis
REPASSÉ ENTIÈREMENT dans le masquage de la liaison (`redact.Redactor` : nom de machine, comptes, adresses, numéros de
série, URL) avant de partir : tout fichier du zip est du texte. S'il dépasse la taille permise, les plus gros fichiers
ne gardent que leur fin (le plus récent d'un journal est à la fin), avec une ligne qui le dit.
"""
from __future__ import annotations

import io
import zipfile

from .envelope import SNAP_MAX
from .redact import Redactor

KEEP_TAIL = 200 * 1024                  # fin gardée d'un fichier trop gros (octets de texte)
CUT_NOTE = "[… début coupé pour l'envoi par le monitoring : rapport complet sur la station (menu 6.3)]\n"


def redact_zip(data: bytes, redactor: Redactor, *, max_bytes: int = SNAP_MAX) -> bytes:
    """Nouveau zip : chaque fichier masqué ; coupé par la fin des plus gros si le total dépasse `max_bytes`."""
    with zipfile.ZipFile(io.BytesIO(data)) as src:
        texts = {}
        for info in src.infolist():
            if info.is_dir():
                continue
            raw = src.read(info)
            texts[info.filename] = redactor.text(raw.decode("utf-8", errors="replace"))
    keep = None
    while True:
        out = _write(texts, keep)
        if len(out) <= max_bytes:
            return out
        keep = KEEP_TAIL if keep is None else keep // 2
        if keep < 4096:
            raise ValueError("rapport trop grand même réduit")


def _write(texts: dict[str, str], keep: int | None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for name, text in texts.items():
            if keep is not None and len(text) > keep:
                text = CUT_NOTE + text[-keep:]
            dst.writestr(_safe_name(name), text)
    return buf.getvalue()


def _safe_name(name: str) -> str:
    """Pas de chemin absolu ni de « .. » dans un zip qui partira chez quelqu'un d'autre."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return "/".join(parts) or "fichier.txt"


def check_received(data: bytes, *, max_files: int = 200, max_unpacked: int = 50 * 1024 * 1024) -> None:
    """Station qui AIDE : refuse un zip reçu dangereux à ouvrir (chemins, bombe de décompression)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > max_files:
            raise ValueError("trop de fichiers")
        total = 0
        for info in infos:
            if info.filename.startswith(("/", "\\")) or ".." in info.filename.replace("\\", "/").split("/") \
                    or ":" in info.filename:
                raise ValueError(f"chemin refusé : {info.filename[:60]}")
            total += info.file_size
        if total > max_unpacked:
            raise ValueError("contenu décompressé trop grand")
