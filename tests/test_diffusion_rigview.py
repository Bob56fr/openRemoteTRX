# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Diffusion : infos du poste pour les auditeurs, comme le POC (étape 248) : S-mètre animé, squelch, filtre,
voyants ; tout coché par défaut (décision de l'utilisateur du 2026-11-18)."""
from __future__ import annotations

import re
import socket
from pathlib import Path
from types import SimpleNamespace

from trxstation.diffusion import audio as au, protocol as p, rigview
from trxstation.diffusion.service import DiffusionService
from trxstation.setup_wizard import dummy_config

ROOT = Path(__file__).resolve().parents[1]
TOKEN = au.audio_token("secret")


def test_width_s_text_and_squelch():
    assert (rigview.width_text(2400), rigview.width_text(3000), rigview.width_text(500)) == ("2.4k", "3k", "500")
    assert rigview.width_text(None) is None
    assert [rigview.s_text(d) for d in (-12, 0, 20, -60)] == ["S7", "S9", "S9+20", "S0"]
    assert rigview.squelch_open({}, -10, -20) is None                       # squelch non réglé
    assert rigview.squelch_open({"SQL": 0.2}, 10, -20) is True              # seuil ≈ S5 (raw 51)
    assert rigview.squelch_open({"SQL": 0.2}, -40, -20) is False
    assert rigview.squelch_open({"SQL": 0.2}, 10, -90) is False             # son coupé par le poste


def test_indicators_like_the_page_of_the_station():
    v = rigview.indicators({"RIT": True, "XIT": False, "NB": True, "NR": False, "ANF": False},
                           {"PREAMP": 20, "ATT": 0}, False, {"RIT": -120}, (10, 20))
    assert v == [["P.AMP 2", True], ["ATT", False], ["RIT -120", True], ["ΔTX", False], ["SPLIT", False],
                 ["NOTCH", False], ["NB", True], ["NR", False]]
    p.check_meta({"voyants": v})                                            # accepté par le protocole


def test_snapshot_and_info_packet_round_trip():
    state = SimpleNamespace(strength_db=-12, levels={"SQL": 0.0, "PREAMP": 0}, passband_hz=2400,
                            functions={"NB": True}, split=None, offsets={})
    info = rigview.snapshot(state, (), -30.0)
    assert info == {"s": -12.0, "q": None, "w": "2.4k", "v": [["P.AMP", False], ["NB", True]], "off": False}
    packet = au.pack_info(TOKEN, info)
    assert au.unpack_info(TOKEN, packet) == info
    assert au.unpack_info(au.audio_token("autre"), packet) is None          # mauvais jeton
    assert au.unpack(TOKEN, packet) is None                                 # jamais pris pour du son


def module(tmp_path):
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    svc = DiffusionService(cfg, tmp_path / "station.toml")
    svc._session = {"access": "public", "voice": False, "phase": "en_direct", "meta_choice": list(p.DEFAULT_META_CHOICE)}
    svc.token = TOKEN
    return svc


def test_module_keeps_s_points_and_sends_everything_by_default(tmp_path):
    svc = module(tmp_path)
    svc._s_hist = [(90.0, -6.0, None)]                                      # trop vieux : jeté au passage
    for i, db in enumerate((-30, -12, 4)):
        svc.on_info({"s": db, "q": True, "w": "2.4k", "v": [["NB", True]]}, now=100.0 + i * 0.2)
    pts = svc.s_points(now=100.5)
    assert pts[0] == [100, 4.0, True] and len(pts) == 3                    # le plus récent d'abord
    svc.values.update({"pseudo": "BOB", "frequence_hz": 7074000, "s": pts})
    meta = p.pick_meta(svc._session["meta_choice"], svc.values)
    assert meta["s_metre"] == "S9+4" and meta["filtre"] == "2.4k" and meta["voyants"] == [["NB", True]]
    assert meta["s"] == pts and meta["frequence_hz"] == 7074000
    assert "s" not in p.pick_meta(["pseudo"], svc.values)                   # « s » suit seulement « s_metre »
    assert p.meta_body("bob56fr", 1, "public", meta)                        # tient dans le corps


def test_module_ignores_bad_info(tmp_path):
    svc = module(tmp_path)
    svc.on_info({"s": "fort", "w": "x" * 20, "v": [["NB", "oui"]]}, now=1.0)
    assert svc._s_hist == [] and svc.values["filtre"] is None and svc.values["voyants"] is None


def test_info_packet_reaches_the_module_by_udp(tmp_path):
    svc = module(tmp_path)
    svc.on_packet(au.pack_info(TOKEN, {"s": -12, "q": None, "w": "3k", "v": []}))
    assert svc.values["filtre"] == "3k" and svc.values["s_metre"] == "S7"


def test_page_choice_list_matches_the_protocol():
    js = (ROOT / "trxstation" / "gateway" / "api" / "static" / "diffusion.js").read_text(encoding="utf-8")
    block = js[js.index("const META = ["):js.index("];", js.index("const META = ["))]
    assert tuple(re.findall(r'\["(\w+)", "', block)) == p.CHOICE_FIELDS


def test_gateway_sends_info_every_10_frames():
    import asyncio

    from trxstation.gateway.audio.diffusion_out import DiffusionOut
    from trxstation.gateway.audio.listeners import TxTap

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    port = rx.getsockname()[1]

    class Hub:
        def __init__(self):
            self.q = asyncio.Queue()

        def subscribe(self):
            for _ in range(20):
                self.q.put_nowait(b"\x10\x00" * au.BLOCK)
            return self.q

        def unsubscribe(self, q):
            pass

    out = DiffusionOut(port, TOKEN, Hub(), TxTap(), lambda: False, None, info=lambda rms: {"s": -12, "rms": rms})

    async def go():
        task = asyncio.ensure_future(out._feed_loop())
        await asyncio.sleep(0.2)
        task.cancel()
    asyncio.run(go())
    kinds = []
    try:
        while True:
            kinds.append(rx.recv(4096)[:4])
    except OSError:
        pass
    rx.close()
    assert kinds.count(au.INFO_MAGIC) == 2 and kinds.count(au.MAGIC) == 20


def test_module_reads_frequency_and_mode_at_connection(tmp_path):
    """Les événements ne viennent qu'au changement : à la (re)connexion au bus, le module lit l'état actuel."""
    import asyncio

    svc = module(tmp_path)

    class Bus:
        async def get_state(self):
            return {"freq": 7074000, "mode": "USB", "ptt": False, "ptt_state": "RX", "trx_connected": True}

    svc.bus = Bus()

    async def go():
        svc._bus_seen = False
        svc._session = None                             # pas de diffusion : rien à arrêter
        await svc.on_connect()
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert (svc.values["frequence_hz"], svc.values["mode"], svc.values["bande"], svc.values["tx"]) == (
        7074000, "USB", "40m", False)
