# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lot CW-0 : validation des paquets du canal `cw` (cahier § 5.2)."""
from __future__ import annotations

import pytest

from trxstation.cw.protocol import MAX_EDGES, parse_packet


def _msg(**over):
    m = {"type": "cw", "seq": 3, "edges": [[41, 1, 1532], [42, 0, 1592]], "lease": 1610}
    m.update(over)
    return m


def test_the_example_of_the_specification_is_accepted():
    p = parse_packet(_msg())
    assert p.seq == 3 and p.lease == 1610.0
    assert [(e.id, e.down, e.ts) for e in p.edges] == [(41, True, 1532.0), (42, False, 1592.0)]


def test_a_packet_without_edges_is_accepted():
    assert parse_packet(_msg(edges=[])).edges == ()


@pytest.mark.parametrize("over", [
    {"type": "control"},
    {"seq": -1}, {"seq": True}, {"seq": 1.5}, {"seq": "3"},
    {"edges": "x"}, {"edges": [[1, 1]]}, {"edges": [[1, 2, 0]]}, {"edges": [[1, True, 0]]},
    {"edges": [[-1, 1, 0]]}, {"edges": [[1, 1, -5]]}, {"edges": [[1, 1, float("nan")]]},
    {"edges": [[1, 1, float("inf")]]}, {"edges": [[1, 1, 10], [1, 0, 20]]},
    {"edges": [[1, 1, 20], [2, 0, 10]]},
    {"lease": 1500}, {"lease": None}, {"lease": float("nan")},
    {"edges": [[i, i % 2, i] for i in range(MAX_EDGES + 1)], "lease": 100},
])
def test_malformed_packets_are_refused(over):
    with pytest.raises(ValueError):
        parse_packet(_msg(**over))


def test_not_a_dict_is_refused():
    with pytest.raises(ValueError):
        parse_packet([1, 2, 3])


def test_shared_packet_vectors_are_up_to_date_and_valid():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("build_cw_vectors", root / "scripts" / "build_cw_vectors.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    on_disk = (root / "tests" / "protocol" / "cw_vectors.json").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert on_disk == module.render(), "python scripts/build_cw_vectors.py"
    import json
    for case in json.loads(on_disk)["cases"]:
        for p in case["packets"]:
            parse_packet(p["msg"])                                # chaque paquet attendu est accepté par la station
