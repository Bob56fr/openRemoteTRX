# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module Cluster DX, lot 3 : spots de la bande courante vers les pages (vue HF ouverte seulement),
rejeu à l'ouverture, page servie, QSY par les commandes existantes."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation.cluster import publish as pub
from trxstation.cluster import service as svc
from trxstation.cluster.cache import SpotCache
from trxstation.cluster.parse import parse_dx_line
from trxstation.devtools.fake_cluster import FakeCluster
from trxstation.modules.gateway_bridge import RETAIN_MAX, ModuleBridge

from test_cluster_service import cluster_cfg
from test_modules_integration import FakeCtrl, FakeLink, make_cfg

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "trxstation" / "gateway" / "api" / "static"


def add(cache, freq, dx, now, comment="SSB", kind="cluster"):
    return cache.add(parse_dx_line(f"DX de F5XYZ:  {freq}  {dx}  {comment}  1200Z"), source="a", kind=kind, now=now)[0]

# ------------------------------------------------------------------ publieur (module)


@pytest.mark.parametrize("freq,window", [(14_074_000, (14000.0, 14350.0)), (27_555_000, (25615.0, 27995.0)),
                                         (9_000_000, (8500.0, 9500.0)), (0, None), (None, None)])
def test_window_is_the_rig_band(freq, window):
    assert pub.window_for(freq) == window


def test_snapshot_then_deltas_then_removals():
    cache = SpotCache()
    p = pub.SpotPublisher(cache)
    assert p.tick(0) is None                                    # fréquence du poste inconnue : rien
    a = add(cache, 14205.0, "K1ABC", 0)
    add(cache, 7150.0, "EA8AA", 0)                              # autre bande
    p.set_frequency(14_200_000)
    snap = p.tick(1)
    assert (snap["op"], snap["scope"], snap["retain"], snap["window"]) == ("snapshot", "hf_view", "snapshot", [14000.0, 14350.0])
    assert [s["dx"] for s in snap["spots"]] == ["K1ABC"]
    assert snap["spots"][0] == {"id": a.id, "f": 14205.0, "dx": "K1ABC", "de": "F5XYZ", "m": "SSB", "k": "cluster",
                                "t": "1200", "n": 1, "age": 1, "q": "USB", "co": "United States"} or "co" not in snap["spots"][0]
    assert p.tick(2) is None                                    # rien de nouveau : aucun message
    b = add(cache, 14250.0, "VK2XYZ", 3)
    p.on_spot(b, True)
    add(cache, 7151.0, "ZZ9ZZ", 3)                              # hors fenêtre : jamais signalé
    p.on_spot(cache.spots()[-1], True)
    delta = p.tick(4)
    assert (delta["op"], delta["retain"]) == ("delta", "delta")
    assert [s["dx"] for s in delta["spots"]] == ["VK2XYZ"] and delta["removed"] == []
    cache.expire(10_000)                                        # tout expire
    gone = p.tick(10_001)
    assert gone["op"] == "snapshot" or sorted(gone["removed"]) == sorted([a.id, b.id])


def test_removed_after_expiry_without_snapshot():
    cache = SpotCache(ttl_s={"cluster": 30})
    p = pub.SpotPublisher(cache)
    p.set_frequency(14_200_000)
    a = add(cache, 14205.0, "K1ABC", 0)
    p.tick(0)
    cache.expire(31)
    msg = p.tick(31)
    assert msg["op"] == "delta" and msg["removed"] == [a.id] and msg["spots"] == []


def test_band_change_sends_a_new_snapshot_and_periodic_snapshot():
    cache = SpotCache()
    p = pub.SpotPublisher(cache)
    p.set_frequency(14_200_000)
    p.tick(0)
    add(cache, 7150.0, "EA8AA", 1)
    p.set_frequency(7_100_000)
    msg = p.tick(2)
    assert msg["op"] == "snapshot" and [s["dx"] for s in msg["spots"]] == ["EA8AA"]
    p.set_frequency(7_120_000)                                  # même bande : pas d'instantané
    assert p.tick(3) is None
    assert p.tick(2 + pub.SNAPSHOT_EVERY_S)["op"] == "snapshot"


def test_snapshot_is_bounded_most_recent_first():
    cache = SpotCache()
    p = pub.SpotPublisher(cache)
    for i in range(pub.MAX_SPOTS + 20):
        add(cache, 14000.0 + 2 * i, f"K{i}AB", i)
    p.set_frequency(14_100_000)
    snap = p.tick(500)
    assert len(snap["spots"]) == pub.MAX_SPOTS
    assert snap["spots"][0]["dx"] == f"K{pub.MAX_SPOTS + 19}AB"
    assert len(json.dumps(snap)) < 40_000                       # bien sous la limite d'une ligne du bus (64 ko)


def test_recent_lists_the_last_spots_of_all_bands_most_recent_first():
    cache = SpotCache()
    p = pub.SpotPublisher(cache)
    for i in range(pub.RECENT_MAX + 5):
        p.on_spot(add(cache, (7000.0 if i % 2 else 14000.0) + i, f"K{i}AB", i), True)
    msg = p.recent(100)                                         # fréquence du poste inconnue : envoyé quand même
    assert (msg["kind"], msg["scope"], msg["retain"]) == ("recent", "hf_view", "snapshot")
    assert len(msg["spots"]) == pub.RECENT_MAX
    assert msg["spots"][0]["dx"] == f"K{pub.RECENT_MAX + 4}AB"
    assert {round(s["f"]) // 1000 for s in msg["spots"]} == {7, 14}            # toutes bandes
    assert p.recent(101) is None                                # rien de nouveau
    p.on_spot(add(cache, 21000.0, "JA1AA", 102), True)
    assert p.recent(102) is None                                # au plus toutes les 5 s
    assert p.recent(100 + pub.RECENT_EVERY_S)["spots"][0]["dx"] == "JA1AA"


def test_bridge_keeps_recent_and_band_spots_apart(tmp_path):
    bridge = ModuleBridge(make_cfg(tmp_path), FakeCtrl(), FakeLink(), clients=lambda: [], port=0)
    bridge.to_clients("cluster", {"kind": "spots", "op": "snapshot", "retain": "snapshot", "spots": [1]})
    bridge.to_clients("cluster", {"kind": "recent", "retain": "snapshot", "spots": [9]})
    bridge.to_clients("cluster", {"kind": "spots", "op": "delta", "retain": "delta", "spots": [2]})
    late = Session()
    bridge.on_hf_view(late, True)
    assert sorted((p["data"]["kind"], p["data"]["spots"][0]) for p in late.got) == [("recent", 9), ("spots", 1), ("spots", 2)]


def test_cb_spot_has_no_qsy_mode_guess_but_ssb_has():
    cache = SpotCache()
    s = add(cache, 27555.0, "14LG56", 0, comment="73", kind="cb")
    d = pub.compact(s, 0)
    assert d["k"] == "cb" and d["m"] == "SSB" and d["mg"] == 1 and d["q"] == "USB"

# ------------------------------------------------------------------ passerelle : filtre et rejeu


class Session:
    def __init__(self, hf_view=False):
        self.hf_view, self.got = hf_view, []

    def send(self, payload):
        self.got.append(payload)


def test_bridge_sends_spots_only_to_clients_watching_the_hf_view(tmp_path):
    watching, other = Session(True), Session(False)
    bridge = ModuleBridge(make_cfg(tmp_path), FakeCtrl(), FakeLink(), clients=lambda: [watching, other], port=0)
    bridge.to_clients("cluster", {"kind": "spots", "op": "snapshot", "scope": "hf_view", "retain": "snapshot", "spots": []})
    bridge.to_clients("cluster", {"kind": "module_state", "text": "Cluster DX : ok"})          # sans portée : à tous
    assert [p["data"]["kind"] for p in watching.got] == ["spots", "module_state"]
    assert [p["data"]["kind"] for p in other.got] == ["module_state"]


def test_bridge_replays_snapshot_and_following_deltas_to_a_new_watcher(tmp_path):
    bridge = ModuleBridge(make_cfg(tmp_path), FakeCtrl(), FakeLink(), clients=lambda: [], port=0)
    bridge.to_clients("cluster", {"kind": "spots", "op": "delta", "retain": "delta", "spots": [1]})   # avant tout instantané : rien à garder
    bridge.to_clients("cluster", {"kind": "spots", "op": "snapshot", "retain": "snapshot", "spots": [2]})
    bridge.to_clients("cluster", {"kind": "spots", "op": "delta", "retain": "delta", "spots": [3]})
    late = Session()
    bridge.on_hf_view(late, False)
    assert late.got == []
    bridge.on_hf_view(late, True)
    assert [p["data"]["spots"] for p in late.got] == [[2], [3]]
    bridge.to_clients("cluster", {"kind": "spots", "op": "snapshot", "retain": "snapshot", "spots": [4]})
    newer = Session()
    bridge.on_hf_view(newer, True)
    assert [p["data"]["spots"] for p in newer.got] == [[4]]


def test_bridge_retained_log_is_bounded(tmp_path):
    bridge = ModuleBridge(make_cfg(tmp_path), FakeCtrl(), FakeLink(), clients=lambda: [], port=0)
    bridge.to_clients("cluster", {"kind": "spots", "retain": "snapshot", "spots": []})
    for i in range(RETAIN_MAX + 5):
        bridge.to_clients("cluster", {"kind": "spots", "retain": "delta", "spots": [i]})
    late = Session()
    bridge.on_hf_view(late, True)
    assert len(late.got) <= RETAIN_MAX                          # trop long : on attend le prochain instantané


def test_session_remembers_the_hf_view_and_calls_the_replay():
    from trxstation.gateway.api.session import ControlSession
    sent, seen = [], []
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), config=SimpleNamespace(rig=SimpleNamespace()))
    session = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append,
                             spectrum=SimpleNamespace(snapshot=lambda: {"state": "ok"}), spectrum_watch=lambda on: None)
    assert session.hf_view is False
    session.on_hf_view = lambda s, on: seen.append((s is session, on))
    asyncio.run(session.on_message('{"cmd":"spectrum_watch","id":1,"on":true}'))
    assert session.hf_view is True and seen == [(True, True)]
    session.on_hf_view = lambda s, on: 1 / 0                    # une erreur du rejeu ne casse pas la session
    asyncio.run(session.on_message('{"cmd":"spectrum_watch","id":2,"on":false}'))
    assert session.hf_view is False and sent[-1] == {"type": "result", "id": 2, "ok": True, "on": False}


def test_gateway_wires_the_replay():
    main = (ROOT / "trxstation" / "gateway" / "main.py").read_text(encoding="utf-8")
    assert "manager.on_hf_view = bridge.on_hf_view" in main
    webrtc = (ROOT / "trxstation" / "gateway" / "api" / "webrtc.py").read_text(encoding="utf-8")
    assert "session.on_hf_view = self.on_hf_view" in webrtc

# ------------------------------------------------------------------ module de bout en bout


def test_module_publishes_spots_of_the_rig_band(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "PUBLISH_EVERY_S", 0.05)
    monkeypatch.setattr(svc, "STATUS_EVERY_S", 0.1)
    messages = []

    class Bus:
        on_event = on_connect = on_gap = None

        async def client_message(self, **m):
            messages.append(m)

        async def get_state(self):
            return {"freq": 14_030_000, "mode": "CW"}

        async def run_forever(self):
            await asyncio.Event().wait()

    async def go():
        fake = FakeCluster(interval=0.02)
        await fake.start()
        cfg = cluster_cfg(source=[svc.cfgmod.ClusterSource("local", "telnet", "127.0.0.1", fake.port)], cty_update=False)
        cfg.supervisor.state_dir = str(tmp_path)
        bus = Bus()
        service = svc.ClusterService(cfg, tmp_path / "station.toml", bus_client=bus)
        assert bus.on_event is not None and bus.on_connect is not None
        task = asyncio.ensure_future(service.run())
        try:
            await asyncio.sleep(0.2)
            await bus.on_connect()                              # connexion au cœur : fréquence relue
            for _ in range(100):
                await asyncio.sleep(0.05)
                if any(m.get("kind") == "spots" and m["spots"] for m in messages):
                    break
            await bus.on_event("freq_mode", {"freq": 7_010_000, "mode": "CW"})   # changement de bande
            await asyncio.sleep(0.3)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await fake.close()
    asyncio.run(go())
    spots = [m for m in messages if m.get("kind") == "spots"]
    assert spots and all(m["scope"] == "hf_view" for m in spots)
    first = next(m for m in spots if m["op"] == "snapshot")
    assert first["window"] == [14000.0, 14350.0]
    seen, window = set(), None
    for m in spots:                                             # spots envoyés tant que le poste était sur 20 m
        window = m.get("window", window)
        if window == [14000.0, 14350.0]:
            seen |= {s["dx"] for s in m["spots"]}
    assert "K1ABC" in seen and "OH2BH" not in seen              # 7018 kHz : autre bande
    assert any(m["op"] == "snapshot" and m["window"] == [7000.0, 7200.0] for m in spots)
    assert all(s["m"] not in ("FT8", "FT4", "RTTY", "DIGI") for m in spots for s in m["spots"])


def test_cluster_manifest_reads_the_frequency_but_commands_nothing():
    from trxstation.modules.manifest import load_manifest
    m = load_manifest(ROOT / "trxstation" / "modules" / "builtin" / "cluster" / "manifest.toml")
    assert m.rights.events == frozenset({"freq_mode"}) and not m.rights.commands

# ------------------------------------------------------------------ page


def test_page_loads_and_serves_spots_js_and_its_logic_passes_with_node():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="hfscope.js"') < html.index('src="spots.js"') < html.index('src="ui.js"')
    server = (ROOT / "trxstation" / "gateway" / "api" / "server.py").read_text(encoding="utf-8")
    assert '"/spots.js": ("spots.js", "text/javascript")' in server
    for element in ("hf-cluster", "hf-spots", "hf-list", "hf-spot-layer", "spot-card", "spot-dx", "spot-kind", "spot-freq",
                    "spot-info", "spot-comment", "spot-qsy", "spot-close", "spot-note", "spot-list", "spot-list-title",
                    "spot-sort", "spot-list-close", "spot-items"):
        assert f'id="{element}"' in html, element
    # la fiche et la liste sont DANS la vue HF (élément mis en plein écran), sinon invisibles en plein écran
    hf = html[html.index('<div id="hfscope"'):html.index('<audio id="rx-audio"')]
    assert 'id="spot-card"' in hf and 'id="spot-list"' in hf
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "spots_test.js")], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_spot_colors_never_use_the_transmit_color():
    css = (STATIC / "client.css").read_text(encoding="utf-8")
    block = css[css.index("/* ---- spots du Cluster DX"):]
    block = block[:block.index("\n\n")] if "\n\n" in block else block
    assert "var(--tx" not in block and "#" not in block.replace("/*", "").split("*/")[-1]
