# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique tests/protocol/cw_vectors.json (branche exp/cw) : paquets du canal cw attendus du client."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trxstation.cw.sim import vectors  # noqa: E402

TARGET = ROOT / "tests" / "protocol" / "cw_vectors.json"


def render() -> str:
    """Une ligne par paquet (fichier lisible, diff court)."""
    data = vectors()
    cases = data.pop("cases")
    out = [json.dumps(data, ensure_ascii=False)[:-1] + ', "cases": [']
    for i, case in enumerate(cases):
        packets = case.pop("packets")
        out.append("  " + json.dumps(case, ensure_ascii=False)[:-1] + ', "packets": [')
        out += ["    " + json.dumps(p, separators=(",", ":")) + ("," if j < len(packets) - 1 else "")
                for j, p in enumerate(packets)]
        out.append("  ]}" + ("," if i < len(cases) - 1 else ""))
    out.append("]}")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    TARGET.write_bytes(render().encode("utf-8"))
    print(f"écrit : {TARGET.relative_to(ROOT)}")
