# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Moteur de réception RADE avec les VRAIS décodeurs et un enregistrement sur l'air (30 s en temps réel).

Ignoré sans les variables :
  FREEDV_KA9Q   chemin de freedv-ka9q (freedv-integrations 2.4.1)
  FREEDV_RADAE  chemin de radae_rx (rade_c)
  FREEDV_SAMPLE enregistrement 48 kHz mono int16 contenant VK5KVA dans les 25 premières secondes
                (FDV_offair.wav de rade_c)
"""
from __future__ import annotations

import asyncio
import os
import time
import wave

import pytest

from trxstation.freedv.rx_engine import Callsign, RadeRxEngine, RxEngineConfig, Status, Voice

KA9Q, RADAE, SAMPLE = (os.environ.get(k) for k in ("FREEDV_KA9Q", "FREEDV_RADAE", "FREEDV_SAMPLE"))
pytestmark = pytest.mark.skipif(not (KA9Q and RADAE and SAMPLE), reason="vrais décodeurs absents")


def test_real_decoders_on_air_recording(tmp_path) -> None:
    w = wave.open(SAMPLE)
    assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (48000, 1, 2)
    pcm = w.readframes(48000 * 30)
    events: list = []

    async def main() -> RadeRxEngine:
        e = RadeRxEngine(RxEngineConfig(ka9q=(KA9Q,), radae_rx=(RADAE,), workdir=str(tmp_path)), events.append)
        await e.start()
        t0 = time.monotonic()
        for k in range(0, len(pcm), 1920):              # 20 ms, au rythme réel (freedv-ka9q est cadencé)
            e.feed(pcm[k:k + 1920])
            d = t0 + (k + 1920) / 96000 - time.monotonic()
            if d > 0:
                await asyncio.sleep(d)
        await asyncio.sleep(2.0)
        await e.stop()
        return e

    e = asyncio.run(main())
    st = [x for x in events if isinstance(x, Status)]
    calls = [x for x in events if isinstance(x, Callsign)]
    voice = sum(len(x.pcm) for x in events if isinstance(x, Voice)) / 2 / 48000
    assert not any(s.etat in ("relance", "panne") for s in st), [s.cause for s in st if s.cause]
    assert any(s.confirmed and s.snr_db is not None and s.snr_db > 10 for s in st)
    assert [c.callsign for c in calls] == ["VK5KVA"] and calls[0].snr_db is not None
    assert voice > 15, voice
    assert e.status.drops == 0
    assert (tmp_path / "eoo_rx.f32").exists()          # écrit dans le dossier de travail, pas ailleurs
