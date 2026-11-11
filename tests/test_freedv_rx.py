# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Moteur de réception RADE (lot F1) : lecture des messages, filtres, rééchantillonnage, pannes.

Les décodeurs sont remplacés par trxstation/devtools/fake_freedv_decoder.py (aucun poste, aucun vrai décodeur).
"""
from __future__ import annotations

import asyncio
import math
import struct
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from trxstation.freedv.parse import DemodState, parse_ka9q_line, parse_radae_line
from trxstation.freedv.quality import Sequence, SyncFilter, quality_note
from trxstation.freedv.resample import ToRadaeIQ
from trxstation.freedv.rx_engine import (Callsign, RadeRxEngine, RxEngineConfig, SequenceEnd,
                                         Status, Voice)

FAKE = str(Path(__file__).resolve().parents[1] / "trxstation" / "devtools" / "fake_freedv_decoder.py")
CHUNK = b"\x00\x00" * 960          # 20 ms à 48 kHz


def cmd(role: str, *opts: str) -> tuple[str, ...]:
    return (sys.executable, FAKE, role, *opts)


def cfg(ka9q: tuple[str, ...] = (), radae: tuple[str, ...] = (), **kw) -> RxEngineConfig:
    base = RxEngineConfig(ka9q=ka9q or cmd("ka9q"), radae_rx=radae or cmd("radae"), freeze_s=1.0,
                          startup_grace_s=1.0, write_timeout_s=1.0, backoff_s=(0.1, 0.2), max_restarts=3,
                          restart_window_s=60.0, min_sync_s=2.0)
    return replace(base, **kw)


async def drive(engine: RadeRxEngine, seconds: float, speed: float = 4.0, stop_when=None) -> None:
    """Alimente le moteur avec du son nul à `speed` fois le temps réel pendant `seconds` d'horloge."""
    # Le compte se fait sur l'horloge : sous Windows, un sleep court rend la main presque tout de suite.
    t0 = time.monotonic()
    sent = 0
    while (now := time.monotonic()) < t0 + seconds:
        while sent < (now - t0) * speed / 0.02:
            engine.feed(CHUNK)
            sent += 1
        await asyncio.sleep(0.01)
        if stop_when is not None and stop_when():
            return


def run(c: RxEngineConfig, seconds: float, stop_when=None, after=None) -> tuple[list, RadeRxEngine]:
    events: list = []

    async def main() -> RadeRxEngine:
        e = RadeRxEngine(c, events.append)
        await e.start()
        try:
            await drive(e, seconds, stop_when=(lambda: stop_when(events)) if stop_when else None)
            if after is not None:
                await after(e)
        finally:
            await e.stop()
        return e

    return events, asyncio.run(main())


def statuses(events: list) -> list[Status]:
    return [e for e in events if isinstance(e, Status)]


# ---------------------------------------------------------------- lecture des messages (lignes réelles)
def test_parse_real_radae_lines() -> None:
    sync = "2000 state:       sync valid: 1 0 25 Dthresh:     0.70 Dtmax12:     1.04     0.28 tmax:  299 fmax:   0.77 SNRdB:  6.80 uw_err: 0"
    search = "  90 state:     search valid: 0 0  1 Dthresh:     0.26 Dtmax12:     0.24     1.20 tmax:  854 fmax: -35.00 SNRdB: 17.32"
    cand = "2717 state:  candidate valid: 1 0  1 Dthresh:     0.18 Dtmax12:     0.28     1.32 tmax:   21 fmax:  45.00 SNRdB: 12.63"
    assert parse_radae_line(sync) == DemodState("sync", 6.8, 0.77)
    assert parse_radae_line(search) == DemodState("search", None, None)     # SNR hors synchro ignoré
    assert parse_radae_line(cand) == DemodState("candidate", None, None)
    assert parse_radae_line("End-of-over detected") == "eoo"
    assert parse_radae_line("rade_open: V1 n_features_in=432 Nmf=960") is None


def test_parse_real_ka9q_lines() -> None:
    txt = "11:45:15 INFO /x/rade_text.cpp:401: rxCRC: 63, calcCRC: 63, decodedStr: VK5KVA"
    rep = "11:45:15 INFO /x/ReportingController.cpp:228: Reporting RX callsign VK5KVA (SNR 19) to FreeDV Reporter"
    assert parse_ka9q_line(txt) == ("VK5KVA", None)
    assert parse_ka9q_line(rep) == ("VK5KVA", 19)
    assert parse_ka9q_line("x rxCRC: 63, calcCRC: 12, decodedStr: VK5KVA") is None       # CRC faux
    assert parse_ka9q_line("x rxCRC: 1, calcCRC: 1, decodedStr: <script>") is None       # pas un indicatif
    assert parse_ka9q_line("11:45:15 DEBUG /x/rade_text.cpp:380: RX symbol: -0.97, 0.21, amp: 0.71") is None


# ---------------------------------------------------------------- synchro confirmée et note
def test_short_false_sync_is_never_confirmed() -> None:
    f = SyncFilter(min_sync_s=2.0, hold_s=1.0)
    t = 0.0
    for _ in range(20):                       # 1 s de synchro, 1 s de recherche : fausses synchros du direct
        for st in ["sync"] * 8 + ["search"] * 8:
            assert not f.update(st, t)
            t += 0.12


def test_sync_confirmed_after_2_s_and_survives_brief_drop() -> None:
    f = SyncFilter(min_sync_s=2.0, hold_s=1.0)
    assert not f.update("sync", 0.0)
    assert not f.update("sync", 1.9)
    assert f.update("sync", 2.0)
    assert f.update("search", 2.1)
    assert f.update("candidate", 2.6)          # 0,5 s hors synchro : gardée
    assert f.update("sync", 2.7)
    assert f.update("search", 3.0)
    assert not f.update("search", 4.0)         # 1 s hors synchro : perdue


def test_quality_note() -> None:
    assert quality_note([(True, 12.2)] * 4, 0, 2.0)[0] == 2           # bon signal mais < 3 s
    assert quality_note([(True, 12.2)] * 14, 0, 6.7)[0] == 5          # W6GOK du 2026-11-10
    assert quality_note([(True, 12.2)] * 20, 0, 10.0)[0] == 5
    assert quality_note([(True, 3.4)] * 100, 1, 58.0)[0] == 4
    assert quality_note([(True, 0.2)] * 93 + [(False, 0)] * 7, 8, 394.0)[0] == 3
    assert quality_note([(True, 1.0)] * 60 + [(False, 0)] * 40, 0, 50.0)[0] == 2    # synchro < 80 %
    assert quality_note([(True, 5.0)] * 40, 10, 20.0)[0] == 3                     # coupures fréquentes
    assert quality_note([(False, 0.0)] * 40, 0, 20.0) == (1, "jamais synchronisé")
    assert quality_note([], 0, 20.0)[0] == 1
    s = Sequence(start=0.0, voice_s=60.0)
    for i in range(40):                        # une mesure toutes les 0,25 s, gardée toutes les 0,5 s
        s.sample(i / 4, synced=i not in (8, 9, 24, 25), snr=7.0)
    assert len(s.samples) == 20 and s.resyncs == 2 and s.note()[0] == 5


# ---------------------------------------------------------------- rééchantillonnage 48 kHz -> 8 kHz complexe
def tone(f: float, n: int, rate: int = 48000, amp: float = 8000) -> bytes:
    return (amp * np.sin(2 * np.pi * f * np.arange(n) / rate)).astype("<i2").tobytes()


def test_resample_keeps_voice_band_and_rejects_above_4_khz() -> None:
    r = ToRadaeIQ(48000)
    iq = np.frombuffer(r.process(tone(1000, 48000)), dtype="<f4")
    i, q = iq[0::2], iq[1::2]
    assert len(i) == 8000 and not q.any()
    assert abs(np.sqrt(2) * np.std(i[200:]) - 8000 / 8192) < 0.02          # échelle de rade_rx_wav
    r2 = ToRadaeIQ(48000)
    i2 = np.frombuffer(r2.process(tone(6000, 48000)), dtype="<f4")[0::2]
    assert 20 * np.log10(np.std(i2[200:]) / np.std(i[200:])) < -40


def test_resample_by_chunks_equals_one_block() -> None:
    x = tone(1234, 48000 * 2)
    whole = ToRadaeIQ(48000).process(x)
    r = ToRadaeIQ(48000)
    parts, pos = [], 0
    for n in [1918, 2, 960, 4802, 30000, 777 * 2]:
        parts.append(r.process(x[pos:pos + n])); pos += n
    parts.append(r.process(x[pos:]))
    assert b"".join(parts) == whole


def test_resample_refuses_unsupported_rate() -> None:
    with pytest.raises(ValueError):
        ToRadaeIQ(44100)


# ---------------------------------------------------------------- moteur : marche normale
def test_normal_reception_voice_callsign_and_confirmed_sync(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_ARGV_DIR", str(tmp_path))
    c = cfg(ka9q=cmd("ka9q", "--voice", "--callsign", "W6GOK"), radae=cmd("radae", "--states", "sync:7.5"))
    ev, e = run(c, 3.0, stop_when=lambda ev: any(isinstance(x, Status) and x.confirmed for x in ev)
                and any(isinstance(x, Callsign) for x in ev))
    calls = [x for x in ev if isinstance(x, Callsign)]
    assert calls == [Callsign("W6GOK", 9)]                     # decodedStr + Reporting = UN indicatif, avec SNR
    assert any(isinstance(x, Voice) and x.pcm for x in ev)
    st = [s for s in statuses(ev) if s.confirmed]
    assert st and st[0].snr_db == 7.5 and st[0].foff_hz == 1.5
    # jamais d'option de FreeDV Reporter (lot F6 : une seule connexion, par la passerelle)
    assert (tmp_path / "ka9q.txt").read_text() == "-i 48000 -o 48000"
    assert (tmp_path / "radae.txt").read_text() == "-v 1"
    assert e.status.etat == "arret" and all(p.returncode is not None for p in e.procs)


def test_false_syncs_on_noise_are_never_confirmed() -> None:
    states = ",".join(["sync:-7"] * 8 + ["search"] * 10)
    ev, _ = run(cfg(radae=cmd("radae", "--states", states)), 2.0)
    assert any(s.sync == "sync" for s in statuses(ev))
    assert not any(s.confirmed for s in statuses(ev))


def test_gated_voice_waits_for_confirmed_sync() -> None:
    c = cfg(ka9q=cmd("ka9q", "--voice"), radae=cmd("radae", "--states", "search"), gate_voice=True)
    ev, _ = run(c, 1.5)
    assert not any(isinstance(x, Voice) for x in ev)


def test_sequence_end_carries_note_and_callsign() -> None:
    c = cfg(ka9q=cmd("ka9q", "--voice", "--callsign", "N4WVE", "--crash-after", "4"),
            radae=cmd("radae", "--states", "sync:6.5"), max_restarts=10)
    ev, _ = run(c, 3.0, stop_when=lambda ev: any(isinstance(x, SequenceEnd) for x in ev))
    seq = [x for x in ev if isinstance(x, SequenceEnd)]
    assert seq and seq[0].callsigns == ("N4WVE",) and seq[0].note >= 4 and seq[0].duration_s >= 3


def test_a_failing_listener_does_not_stop_the_engine() -> None:
    n = {"calls": 0}

    def bad(ev) -> None:
        n["calls"] += 1
        raise RuntimeError("abonné fautif")

    async def main() -> str:
        e = RadeRxEngine(cfg(radae=cmd("radae", "--states", "sync:3")), bad)
        await e.start()
        await drive(e, 1.0)
        etat = e.status.etat
        await e.stop()
        return etat

    assert asyncio.run(main()) == "ecoute" and n["calls"] > 1


# ---------------------------------------------------------------- moteur : pannes
def _fault_then_recovery(ev: list, cause_part: str) -> None:
    st = statuses(ev)
    k = next(i for i, s in enumerate(st) if s.etat == "relance")
    assert cause_part in (st[k].cause or "")
    before = st[:k]
    # au moment de la panne, l'état est remis à « search » AVANT la relance : rien d'hérité
    assert before[-1].sync == "search" and not before[-1].confirmed and before[-1].snr_db is None
    assert any(s.etat == "ecoute" for s in st[k:])


def recovered(ev: list) -> bool:
    """Une relance puis un retour en écoute."""
    etats = [s.etat for s in statuses(ev)]
    return "relance" in etats and "ecoute" in etats[etats.index("relance"):]


def test_ka9q_crash_restarts_both_and_resets_sync() -> None:
    c = cfg(ka9q=cmd("ka9q", "--voice", "--crash-after", "12"), radae=cmd("radae", "--states", "sync:8"))
    ev, _ = run(c, 8.0, stop_when=recovered)
    _fault_then_recovery(ev, "freedv-ka9q s'est arrêté")
    assert any(s.confirmed for s in statuses(ev))


def test_radae_crash_is_detected() -> None:
    ev, _ = run(cfg(radae=cmd("radae", "--crash-after", "1")), 3.0,
                stop_when=lambda ev: any(s.etat == "relance" for s in statuses(ev)))
    assert any("radae_rx s'est arrêté" in (s.cause or "") for s in statuses(ev))


def test_radae_silent_while_fed_is_a_freeze() -> None:
    ev, _ = run(cfg(radae=cmd("radae", "--states", "sync:5", "--mute-after", "1")), 6.0,
                stop_when=lambda ev: any(s.etat == "relance" for s in statuses(ev)))
    _fault_then_recovery(ev + [Status(etat="ecoute")], "radae_rx gelé")


def test_decoder_that_stops_reading_is_a_freeze() -> None:
    ev, _ = run(cfg(ka9q=cmd("ka9q", "--freeze-after", "0.5")), 8.0,
                stop_when=lambda ev: any(s.etat == "relance" for s in statuses(ev)))
    assert any("entrée bloquée" in (s.cause or "") for s in statuses(ev))


def test_slow_ka9q_never_starves_radae() -> None:
    """freedv-ka9q lit par à-coups (cadencé en temps réel) : radae_rx doit être alimenté quand même."""
    c = cfg(ka9q=cmd("ka9q", "--pause-every", "1", "--pause-for", "0.8"),
            radae=cmd("radae", "--states", "sync:6"), freeze_s=0.6, write_timeout_s=1.5, startup_grace_s=0.3)
    ev, e = run(c, 4.0)
    st = statuses(ev)
    assert not any(s.etat in ("relance", "panne") for s in st), [s.cause for s in st if s.cause]
    assert any(s.confirmed for s in st)


def test_full_queue_drops_oldest_chunks_without_blocking() -> None:
    c = cfg(ka9q=cmd("ka9q", "--freeze-after", "0.5"), write_timeout_s=30.0, freeze_s=60.0)

    async def main() -> int:
        e = RadeRxEngine(c, lambda ev: None)
        await e.start()
        t0 = time.monotonic()
        await drive(e, 3.0, speed=8.0)
        assert time.monotonic() - t0 < 4.0                     # feed() n'a jamais bloqué
        drops = e._drops
        await e.stop()
        return drops

    assert asyncio.run(main()) > 0


def test_too_many_restarts_means_panne_and_feed_is_harmless() -> None:
    c = cfg(ka9q=cmd("ka9q", "--crash-after", "0.1"), max_restarts=2, backoff_s=(0.05,))

    async def check(e: RadeRxEngine) -> None:
        for _ in range(100):
            if e.status.etat == "panne":
                break
            e.feed(CHUNK)
            await asyncio.sleep(0.02)
        assert e.status.etat == "panne" and e.status.restarts == 3
        e.feed(CHUNK); e.feed_threadsafe(CHUNK)                # aucune exception, rien en file
        assert not e._queue
        assert all(p.returncode is not None for p in e.procs)
        await e.reset()                                        # l'opérateur relance
        assert e.status.etat in ("demarrage", "ecoute") and e.status.restarts == 0

    ev, _ = run(c, 0.0, after=check)
    assert any(s.etat == "panne" for s in statuses(ev))


def test_missing_program_ends_in_panne() -> None:
    c = cfg(ka9q=("/nexiste/pas/freedv-ka9q",), max_restarts=1, backoff_s=(0.05,))

    async def check(e: RadeRxEngine) -> None:
        for _ in range(100):
            if e.status.etat == "panne":
                break
            await asyncio.sleep(0.02)
        assert e.status.etat == "panne" and "lancement impossible de freedv-ka9q" in (e.status.cause or "")

    run(c, 0.0, after=check)


def test_unreadable_output_line_is_a_fault() -> None:
    ev, _ = run(cfg(ka9q=cmd("ka9q", "--bad-line")), 3.0,
                stop_when=lambda ev: any(s.etat == "relance" for s in statuses(ev)))
    assert any("lecture impossible de freedv-ka9q" in (s.cause or "") for s in statuses(ev))


def test_stop_kills_frozen_children() -> None:
    async def main() -> list:
        e = RadeRxEngine(cfg(ka9q=cmd("ka9q", "--no-read"), radae=cmd("radae", "--no-read")), lambda ev: None)
        await e.start()
        await drive(e, 0.5)
        await e.stop()
        return e.procs

    procs = asyncio.run(main())
    assert len(procs) == 2 and all(p.returncode is not None for p in procs)


def test_feed_from_a_thread_wakes_the_loop_once_at_a_time() -> None:
    async def main() -> tuple[int, int]:
        e = RadeRxEngine(cfg(), lambda ev: None)
        await e.start()
        while e.status.etat != "ecoute":
            await asyncio.sleep(0.01)
        loop = asyncio.get_running_loop()
        calls = {"n": 0}
        orig = loop.call_soon_threadsafe

        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        loop.call_soon_threadsafe = counting       # type: ignore[method-assign]
        th = threading.Thread(target=lambda: [e.feed_threadsafe(CHUNK) for _ in range(2000)])
        th.start()
        while th.is_alive():
            await asyncio.sleep(0.001)
        await asyncio.sleep(0.05)
        loop.call_soon_threadsafe = orig           # type: ignore[method-assign]
        etat = e.status.etat
        await e.stop()
        return calls["n"], 0 if etat == "ecoute" else 1

    n, bad = asyncio.run(main())
    assert bad == 0 and 1 <= n < 2000
