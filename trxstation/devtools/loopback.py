# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Banc de test en boucle : faux poste + passerelle complète (audio, sécurité, API WebRTC) dans UN
processus, sans matériel. Sert aux tests de bout en bout et à `devtools/latency.py`.

Nécessite aiortc et aiohttp.
"""
from __future__ import annotations

import asyncio

from ..asyncio_noise import install_quiet_handler
from ..config import ClientAuth
from ..passwords import hash_password
from ..gateway.api.auth import ClientRegistry
from ..gateway.api.server import make_app, start_server
from ..gateway.api.webrtc import PeerManager
from ..gateway.audio import AudioPipeline
from ..gateway.audio.devices import RecordingSink, ToneSource
from ..gateway.cat import CatLink
from ..gateway.memories import MemoryStore
from ..gateway.safety import PttController, PttLimits
from ..setup_wizard import dummy_config
from .fake_rigctld import FakeRigctld

PASSWORDS = {"phone": "Mot de passe de test n°1", "car": "Mot de passe de test n°2"}
TOKENS = PASSWORDS          # ancien nom, conservé


class Loopback:
    def __init__(self, *, source=None, sink=None, limits: PttLimits | None = None, spectrum=None):
        self._source, self._sink, self._limits = source, sink, limits
        self._spectrum = spectrum            # objet du type SpectrumService (facultatif, essais du canal « spectrum »)
        self.fake = FakeRigctld()

    async def __aenter__(self) -> "Loopback":
        install_quiet_handler(asyncio.get_running_loop())
        await self.fake.start()
        self.cfg = dummy_config()
        self.cfg.network.rigctld_port = self.fake.port
        self.cfg.clients = [ClientAuth(i, password_hash=hash_password(pw)) for i, pw in PASSWORDS.items()]
        self.link = CatLink("127.0.0.1", self.fake.port, poll_fast_s=0.05, slow_every=2, backoff_min_s=0.05,
                            backoff_max_s=0.2, timeout=1.0)
        self.sink = self._sink or RecordingSink()
        self.pipeline = AudioPipeline(self.cfg.audio, source=self._source or ToneSource(440.0), sink=self.sink)
        limits = self._limits or PttLimits(tot_s=30, warn_before_s=5, heartbeat_timeout_s=1.0, tick_s=0.02,
                                           rekey_cooldown_s=0.0, unkey_retry_s=0.05, unkey_deadline_s=1.0)
        self.ctrl = PttController(self.link, self.cfg, limits=limits, audio_gate=self.pipeline.gate.set_open)
        self.pipeline.gate.owner_provider = lambda: self.ctrl.snapshot().owner
        self.registry = ClientRegistry(self.cfg.clients)
        self.memories = MemoryStore()
        self.manager = PeerManager(self.ctrl, self.link, self.pipeline, None, peer_timeout_s=10.0, memories=self.memories,
                                   spectrum=self._spectrum)
        self.runner = await start_server(make_app(self.registry, self.manager), "127.0.0.1", 0)
        self.port = self.runner.addresses[0][1]
        self._link_task = asyncio.ensure_future(self.link.run())
        await self.pipeline.start()
        await self.ctrl.start()
        for _ in range(200):
            if self.link.state.connected and not self.ctrl.starting:
                break
            await asyncio.sleep(0.05)
        return self

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def __aexit__(self, *exc) -> None:
        await self.manager.close_all()
        await self.ctrl.close()
        await self.pipeline.stop()
        self.link.stop()
        await asyncio.gather(self._link_task, return_exceptions=True)
        await self.runner.cleanup()
        await self.fake.stop()
