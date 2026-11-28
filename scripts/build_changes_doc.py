# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Publie la liste des changements par poste (trxstation/changes/changes.toml) en JSON pour GitHub Pages (étape 408).

docs/site/changements/changes.json est lu par trx-update-check de chaque station (changes.PUBLIC_URL) : une station
connaît ainsi les changements d'une version avant de l'installer. À relancer après toute modification de changes.toml
(tests/test_changes.py refuse une copie périmée).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trxstation import changes  # noqa: E402

OUTPUT = ROOT / "docs" / "site" / "changements" / "changes.json"


def render() -> bytes:
    return (json.dumps(changes.to_public(changes.load()), ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(render())
    print(f"écrit : {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
