# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Essais AUTOMATIQUES de la valise (lot T2) contre une station complète en un seul processus (passerelle + faux
poste + faux client WebRTC) : chaque essai réussit sur une station saine, et TOUTES les pannes de l'outil lui-même
(confirmation refusée, poste déjà en émission, erreur au milieu, poste bloqué en émission) finissent poste en
réception ou par l'alerte « coupe le poste »."""
from __future__ import annotations

import asyncio

import pytest

from trxstation.qualif import autodrills
from trxstation.qualif.autodrills import AUTO_DRILLS
from trxstation.qualif.terrain import Session


def _available() -> bool:
    try:
        import aiohttp, aiortc, av  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="aiortc / aiohttp / av absents")

TOT = 3.0
DRILL = {d.id: d for d in AUTO_DRILLS}


def _limits():
    from trxstation.gateway.safety.ptt import PttLimits
    return PttLimits(tot_s=TOT, warn_before_s=1.0, heartbeat_timeout_s=1.0, tick_s=0.02, rekey_cooldown_s=0.0,
                     unkey_retry_s=0.05, unkey_deadline_s=1.0)


def _play(tmp_path, drill_id, *, answers=("EMETTRE",), prepare=None, wrap=None):
    from trxstation.devtools.fake_client import FakeClient, ToneTrack
    from trxstation.devtools.loopback import PASSWORDS, Loopback
    session = Session.open(tmp_path / "s", model=1)
    shown, made = [], []

    async def go():
        lb = Loopback(limits=_limits())
        lb.fake.freq = 7_100_000            # AVANT le démarrage : sinon changement « non commandé » = opérateur sur place
        async with lb:
            lb.cfg.safety.tot_s = int(TOT)
            if prepare:
                prepare(lb)

            def factory():
                client = FakeClient(lb.url, "phone", PASSWORDS["phone"], track=ToneTrack(active=False))
                made.append(client)
                return wrap(client) if wrap else client
            it = iter(answers)
            record = await autodrills.play_auto(DRILL[drill_id], session, client_factory=factory, host="127.0.0.1",
                                                port=lb.fake.port, cfg=lb.cfg, state_dir=tmp_path, ask=lambda p: next(it),
                                                out=shown.append, period=0.05)
            return record, lb.fake.ptt, lb.fake.freq
    record, ptt, freq = asyncio.run(asyncio.wait_for(go(), 90))
    return record, ptt, freq, made, "\n".join(map(str, shown)), session


@pytest.mark.parametrize("drill_id", ["auto_stop", "auto_heartbeat", "auto_disconnect", "auto_tot"])
def test_each_automatic_drill_passes_on_a_sound_station_and_ends_in_receive(tmp_path, drill_id):
    record, ptt, _, _, shown, session = _play(tmp_path, drill_id)
    assert record["measured"] == "reussi", record["reason"]
    assert ptt == 0 and session.drills[drill_id]["result"] == "reussi"
    assert any(v == 1 for _, v in record["observer"]["changes"])          # il y a bien eu émission


def test_the_out_of_band_drill_is_refused_and_the_frequency_restored(tmp_path):
    record, ptt, freq, _, _, _ = _play(tmp_path, "auto_out_of_band")
    assert record["measured"] == "reussi", record["reason"]
    assert ptt == 0 and freq == 7_100_000
    assert not any(v == 1 for _, v in record["observer"]["changes"])


def test_nothing_is_sent_without_the_confirmation_word(tmp_path):
    record, ptt, _, made, shown, _ = _play(tmp_path, "auto_stop", answers=("oui",))
    assert record == {} and made == [] and ptt == 0


def test_a_rig_already_transmitting_is_never_touched(tmp_path):
    def keyed(lb):
        lb.fake.ptt = 1                     # émission au micro du poste, par exemple
    record, _, _, made, _, _ = _play(tmp_path, "auto_stop", prepare=keyed)
    assert made == [] and record["measured"] != "reussi"


def test_an_error_in_the_middle_still_ends_in_receive(tmp_path):
    class Broken:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def start_heartbeat(self, every_s=0.2):
            raise RuntimeError("panne de l'outil")
    record, ptt, _, made, _, _ = _play(tmp_path, "auto_stop", wrap=Broken)
    assert len(made) == 1 and ptt == 0
    assert record["measured"] == "non_mesure" and "panne de l'outil" in record["reason"]


def test_a_rig_stuck_in_transmission_is_a_failure_with_the_alert(tmp_path):
    def stuck(lb):
        lb.fake.ignore_unkey = True         # « T 0 » accepté mais le poste reste en émission
    record, _, _, _, shown, session = _play(tmp_path, "auto_stop", prepare=stuck)
    assert record["measured"] == "echec" and "COUPE" in shown
    assert session.drills["auto_stop"]["result"] == "echec"


def test_a_failed_automatic_drill_refuses_the_rig(tmp_path):
    from trxstation.qualif import terrain
    session = Session.open(tmp_path / "s", model=1)
    session.drills["auto_tot"] = {"result": "echec"}
    assert terrain.verdict(session)[0] == "refuse"


def test_out_of_band_frequency_is_outside_every_band():
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    hz = autodrills.out_of_band_frequency(cfg)
    assert hz and not any(b.low_mhz * 1e6 <= hz <= b.high_mhz * 1e6 for b in cfg.bands)
    cfg.safety.enforce_bands = False
    assert autodrills.out_of_band_frequency(cfg) is None


def test_the_station_certificate_is_pinned(tmp_path):
    from trxstation.gateway.api.tls import generate_self_signed
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    assert autodrills.pinned_ssl(cfg) is None and autodrills.station_url(cfg).startswith("http://127.0.0.1:")
    generate_self_signed(["127.0.0.1"], tmp_path / "c.pem", tmp_path / "k.pem")
    cfg.network.tls_cert = str(tmp_path / "c.pem")
    cfg.network.gateway_bind = "0.0.0.0"
    import aiohttp
    assert isinstance(autodrills.pinned_ssl(cfg), aiohttp.Fingerprint)
    assert autodrills.station_url(cfg) == f"https://127.0.0.1:{cfg.network.gateway_port}"


def test_an_unreadable_ptt_starts_nothing_and_never_claims_a_transmission(tmp_path):
    """Station d'essai arrêtée (vu sur l'IC-705) : « LE POSTE EST RESTÉ EN ÉMISSION » était affiché à tort."""
    session = Session.open(tmp_path / "s", model=1)
    made, shown = [], []
    from trxstation.setup_wizard import dummy_config
    record = asyncio.run(autodrills.play_auto(
        DRILL["auto_stop"], session, client_factory=lambda: made.append(1), host="127.0.0.1", port=1, cfg=dummy_config(),
        state_dir=tmp_path, ask=lambda p: "EMETTRE", out=shown.append, period=0.01))
    assert record == {} and made == [] and "auto_stop" not in session.drills
    assert not any("COUPE" in s for s in shown) and any("ILLISIBLE" in s for s in shown)
