# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Diffusion en direct, lot D1b : module « diffusion », secrets, son de la passerelle (faux Icecast, sans réseau)."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import time
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation.devtools.fake_icecast import FakeIcecast
from trxstation.diffusion import audio as au, keyfile, protocol as p, service as sv
from trxstation.gateway.audio.diffusion_out import DiffusionOut
from trxstation.gateway.audio.listeners import TxTap
from trxstation.modules.registry import selected_manifests

KEY = "ab" * 32
SECRETS = keyfile.Secrets("MotSource42", KEY, "auditeur", "")


class Clock:
    def __init__(self) -> None:
        self.t = time.time()                    # le serveur compare ts_ms à SON heure (fenêtre de 2 min)

    def __call__(self) -> float:
        return self.t


def make_cfg(tmp_path: Path, port: int = 0, http: int = 0, **kw) -> cfgmod.Config:
    cfg = cfgmod.Config()
    cfg.supervisor.state_dir = str(tmp_path / "state")
    cfg.modules.run = ["diffusion"]
    d = dict(enabled=True, server="127.0.0.1", station="bob56fr", source_port=port or 1, api_port=http or 1,
             tls=False, audio_port=47999)
    d.update(kw)
    for k, v in d.items():
        setattr(cfg.diffusion, k, v)
    return cfg


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(p, "BACKOFF_S", (0.05, 0.05, 0.05))


async def started(tmp_path, fake=None, clock=None, secrets=SECRETS, **kw):
    fake = fake or FakeIcecast(meta_key=bytes.fromhex(KEY))
    sp, hp = await fake.start()
    cfg = make_cfg(tmp_path, sp, hp, **kw)
    if secrets is not None:
        keyfile.save(cfgmod.diffusion_key_path(cfg, tmp_path / "station.toml"), secrets)
    service = sv.DiffusionService(cfg, tmp_path / "station.toml", clock=clock or Clock())
    service.token = au.audio_token("secret-du-module")
    return fake, service


async def until(cond, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError("condition jamais remplie")
        await asyncio.sleep(0.02)


def feed(service, n=10, value=1000):
    pcm = (value.to_bytes(2, "little", signed=True)) * au.BLOCK
    for i in range(n):
        service.on_packet(au.pack(service.token, i, pcm))


# ------------------------------------------------------------------ manifeste et configuration
def test_manifest_gives_no_right_on_the_rig():
    manifests, problems = selected_manifests(cfgmod.Modules(run=["diffusion"]))
    assert not problems
    m = manifests[0]
    assert m.name == "diffusion" and m.entry == "trxstation.diffusion.service"
    assert list(m.rights.commands) == [] and m.rights.client_messages is False
    assert set(m.rights.events) == {"freq_mode", "ptt"}          # lecture seule, pour les métadonnées
    assert m.rights.client_commands is True


def test_section_is_off_by_default_and_validated(tmp_path):
    cfg = cfgmod.Config()
    assert cfg.diffusion.enabled is False and cfg.diffusion.server == "" and cfg.diffusion.codec == "opus"
    assert not [x for x in cfgmod.validate(cfg) if "[diffusion]" in x]
    cfg.diffusion.enabled = True
    msgs = " ".join(cfgmod.validate(cfg))
    assert "diffusion" in msgs                                    # module absent, serveur et station manquants
    good = make_cfg(tmp_path, 8443, 443, tls=True, server="diffusion.example.org")
    assert not [x for x in cfgmod.validate(good) if "[diffusion]" in x]
    for kw in ({"tls": False}, {"station": "Bob"}, {"codec": "aac"}, {"audio_port": good.modules.bus_port},
               {"audio_port": good.sdr.audio_port}, {"server": "a b"}, {"source_port": 0}):
        bad = make_cfg(tmp_path, 8443, 443, tls=True, server="diffusion.example.org")
        for k, v in kw.items():
            setattr(bad.diffusion, k, v)
        assert [x for x in cfgmod.validate(bad) if "[diffusion]" in x], kw


def test_station_toml_round_trip(tmp_path):
    cfg = make_cfg(tmp_path, 8443, 443, tls=True, server="diffusion.example.org", codec="mp3")
    text = cfgmod.render_toml(cfg)
    assert "[diffusion]" in text
    path = tmp_path / "station.toml"
    path.write_text(text, encoding="utf-8")
    back = cfgmod.load(path) if not cfgmod.validate(cfg) else None
    if back is not None:
        assert back.diffusion == cfg.diffusion


# ------------------------------------------------------------------ secrets et paquets
def test_keyfile_round_trip_and_never_shown(tmp_path):
    path = tmp_path / "diffusion.key"
    keyfile.save(path, keyfile.Secrets("MotSource42", KEY, "auditeur", "Abcdefgh2345"))
    s = keyfile.read(path)
    assert s.source_password == "MotSource42" and s.meta_key_bytes == bytes.fromhex(KEY)
    assert "MotSource42" not in repr(s) and "Abcdefgh2345" not in repr(s) and KEY not in repr(s)
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        path.chmod(0o644)
        with pytest.raises(keyfile.KeyFileError):
            keyfile.read(path)
    for bad in ({"source_password": "", "meta_key": KEY}, {"source_password": "x", "meta_key": "12"},
                {"source_password": "a:b", "meta_key": KEY}):
        path.write_text(json.dumps(bad), encoding="utf-8")
        if os.name == "posix":
            path.chmod(0o600)
        with pytest.raises(keyfile.KeyFileError):
            keyfile.read(path)
    with pytest.raises(keyfile.KeyFileError):
        keyfile.read(tmp_path / "absent.key")


def test_audio_packets_need_the_token():
    token = au.audio_token("secret")
    assert token == au.audio_token(b"secret") and len(token) == 16
    pcm = bytes(range(256)) * 7 + bytes(128)
    pkt = au.pack(token, 7, pcm)
    assert len(pkt) == au.PACKET_BYTES and au.unpack(token, pkt) == (7, pcm)
    assert au.unpack(au.audio_token("autre"), pkt) is None
    assert au.unpack(token, pkt[:-1]) is None and au.unpack(token, b"XXXX" + pkt[4:]) is None


# ------------------------------------------------------------------ module : lancement, son, arrêt
def test_start_private_sends_raw_audio_and_metadata(tmp_path):
    asyncio.run(_start_private_sends_raw_audio_and_metadata(tmp_path))


async def _start_private_sends_raw_audio_and_metadata(tmp_path):
    fake, service = await started(tmp_path)
    try:
        st = await service.act("start", {"access": "prive", "pseudo": "BOB-56-FR", "operator": "pc"})
        assert st["active"] and st["access"] == "prive" and st["voice"] is False
        await until(lambda: "/bob56fr-prive" in fake.live())
        assert fake.requests[-1] == "PUT /bob56fr-prive HTTP/1.1"
        feed(service, 50)
        await until(lambda: len(fake.received["/bob56fr-prive"]) > 500)
        assert bytes(fake.received["/bob56fr-prive"][:4]) == b"OggS"
        await until(lambda: fake.metas and fake.listener_updates)
        assert fake.metas[-1]["acces"] == "prive" and fake.metas[-1]["meta"] == {"pseudo": "BOB-56-FR"}
        pw = fake.listener_updates[-1]["password"]                  # généré une fois, gardé dans diffusion.key
        assert p.LISTENER_PASSWORD.match(pw)
        assert keyfile.read(service.key_path).listener_password == pw
        status = json.loads((service.folder / "status.json").read_text(encoding="utf-8"))
        assert status["active"] and status["listener_user"] == "auditeur"
        assert pw not in json.dumps(status) and "MotSource42" not in json.dumps(status)
        with pytest.raises(sv.ActionRefused):
            await service.act("start", {})                          # une seule diffusion à la fois
        await service.act("stop", {"operator": "tel"})
        assert not service.active and service.last_stop["cause"] == "operator"
        await until(lambda: not fake.live())
    finally:
        await service.stop("station_stop")
        await fake.stop()


def test_wrong_token_and_inactive_audio_are_ignored(tmp_path):
    asyncio.run(_wrong_token_and_inactive_audio_are_ignored(tmp_path))


async def _wrong_token_and_inactive_audio_are_ignored(tmp_path):
    fake, service = await started(tmp_path)
    try:
        feed(service, 5)
        assert service.audio.empty()                                # hors diffusion : rien gardé
        await service.act("start", {"access": "public"})
        service.on_packet(au.pack(au.audio_token("intrus"), 1, au.SILENCE))
        assert service.audio.empty()
    finally:
        await service.stop("station_stop")
        await fake.stop()


def test_silence_keeps_the_source_alive_without_gateway_audio(tmp_path):
    asyncio.run(_silence_keeps_the_source_alive_without_gateway_audio(tmp_path))


async def _silence_keeps_the_source_alive_without_gateway_audio(tmp_path):
    fake, service = await started(tmp_path)
    try:
        await service.act("start", {"access": "public"})
        await until(lambda: "/bob56fr-public" in fake.live())
        await until(lambda: len(fake.received["/bob56fr-public"]) > 300, timeout=8)   # Icecast coupe une source muette
    finally:
        await service.stop("station_stop")
        await fake.stop()


def test_reconnects_after_a_server_drop(tmp_path):
    asyncio.run(_reconnects_after_a_server_drop(tmp_path))


async def _reconnects_after_a_server_drop(tmp_path):
    fake, service = await started(tmp_path)
    try:
        await service.act("start", {"access": "public"})
        await until(lambda: "/bob56fr-public" in fake.live())
        n = len(fake.requests)
        await fake.drop()
        await until(lambda: len(fake.requests) > n and "/bob56fr-public" in fake.live(), timeout=8)
        assert service.active
    finally:
        await service.stop("station_stop")
        await fake.stop()


def test_refused_source_password_stops_without_retrying(tmp_path):
    asyncio.run(_refused_source_password_stops_without_retrying(tmp_path))


async def _refused_source_password_stops_without_retrying(tmp_path):
    fake, service = await started(tmp_path, secrets=keyfile.Secrets("faux", KEY))
    try:
        await service.act("start", {"access": "public"})
        await until(lambda: not service.active)
        assert service.last_stop["cause"] == "auth" and fake.statuses == [401]
    finally:
        await fake.stop()


def test_duration_ends_the_broadcast(tmp_path):
    asyncio.run(_duration_ends_the_broadcast(tmp_path))


async def _duration_ends_the_broadcast(tmp_path):
    clock = Clock()
    fake, service = await started(tmp_path, clock=clock)
    try:
        await service.act("start", {"access": "public", "hours": 1})
        await until(lambda: "/bob56fr-public" in fake.live())
        clock.t += 3601
        await until(lambda: not service.active)
        assert service.last_stop["cause"] == "duration"
    finally:
        await fake.stop()


def test_gateway_comeback_stops_and_nothing_resumes(tmp_path):
    asyncio.run(_gateway_comeback_stops_and_nothing_resumes(tmp_path))


async def _gateway_comeback_stops_and_nothing_resumes(tmp_path):
    fake, service = await started(tmp_path)
    try:
        await service.on_connect()                                  # premier contact : rien
        await service.act("start", {"access": "public"})
        await service.on_connect()                                  # retour de la passerelle (relance, mode sûr)
        assert not service.active and service.last_stop["cause"] == "gateway_restart"
        fresh = sv.DiffusionService(service.cfg, tmp_path / "station.toml", clock=Clock())
        assert not fresh.active                                     # jamais repris au démarrage
    finally:
        await fake.stop()


def test_refusals(tmp_path):
    asyncio.run(_refusals(tmp_path))


async def _refusals(tmp_path):
    fake, service = await started(tmp_path, secrets=None)
    try:
        with pytest.raises(sv.ActionRefused) as exc:
            await service.act("start", {})
        assert exc.value.reason == "no_secrets"                      # ORT-6105
        keyfile.save(service.key_path, SECRETS)
        for bad in ({"access": "tous"}, {"hours": 0}, {"hours": 25}, {"voice": "oui"}, {"meta": ["adresse_ip"]},
                    {"pseudo": "x" * 40}):
            with pytest.raises(sv.ActionRefused):
                await service.act("start", bad)
        with pytest.raises(sv.ActionRefused):
            await service.act("format", {})
        service.df.enabled = False
        with pytest.raises(sv.ActionRefused) as exc:
            await service.act("start", {})
        assert exc.value.reason == "disabled"
    finally:
        await fake.stop()


def test_metadata_follow_the_operator_choice_and_the_rig(tmp_path):
    asyncio.run(_metadata_follow_the_operator_choice_and_the_rig(tmp_path))


async def _metadata_follow_the_operator_choice_and_the_rig(tmp_path):
    fake, service = await started(tmp_path)
    try:
        await service.act("start", {"access": "public", "pseudo": "BOB", "meta": ["pseudo", "frequence_hz", "bande",
                                                                                   "mode", "tx"]})
        await service.on_event("freq_mode", {"freq": 7074000, "mode": "USB"})
        await service.on_event("ptt", {"active": True, "state": "TX"})
        await until(lambda: fake.metas and fake.metas[-1]["meta"].get("tx") is True, timeout=4)
        assert fake.metas[-1]["meta"] == {"pseudo": "BOB", "frequence_hz": 7074000, "bande": "40m", "mode": "USB",
                                          "tx": True}
        fake.listeners = {"prive": 0, "public": 3}
        service._meta_dirty = True
        await until(lambda: service.status().get("listeners") == 3, timeout=4)
    finally:
        await service.stop("station_stop")
        await fake.stop()


# ------------------------------------------------------------------ passerelle : son et arrêts
class FakeHub:
    def __init__(self) -> None:
        self.queues: set = set()

    def subscribe(self, maxsize: int = 10) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.queues.add(q)
        return q

    def unsubscribe(self, q) -> None:
        self.queues.discard(q)


def test_voice_is_silenced_unless_asked():
    tap = TxTap()
    out = DiffusionOut(47999, au.audio_token("s"), FakeHub(), tap, transmitting=lambda: True, call=None)
    from trxstation.gateway.audio.listeners import ListenerMix
    mix = ListenerMix(tap, None)
    rx = b"\x10\x00" * au.BLOCK
    out.voice = False
    assert out.frame(mix, rx) == au.SILENCE                         # émission (micro du poste compris) : silence
    out.transmitting = lambda: False
    assert out.frame(mix, rx) == rx                                 # réception : son du poste, sans filtre de bandes
    out.voice = True
    out.transmitting = lambda: True
    assert out.frame(mix, rx) == rx                                 # voix demandée : le son passe


def test_gateway_feeds_only_during_a_broadcast_and_stops_it_when_overloaded():
    asyncio.run(_gateway_feeds_only_during_a_broadcast_and_stops_it_when_overloaded())


async def _gateway_feeds_only_during_a_broadcast_and_stops_it_when_overloaded():
    hub, calls, state = FakeHub(), [], {"active": False, "voice": False}

    async def call(data):
        calls.append(data)
        if data["action"] == "stop":
            state["active"] = False
        return dict(state)

    over = {"on": False}
    out = DiffusionOut(47999, au.audio_token("s"), hub, TxTap(), lambda: False, call, overloaded=lambda: over["on"])
    await out.poll()
    assert out._feed is None and not hub.queues
    state["active"] = True
    await out.poll()
    await asyncio.sleep(0.05)
    assert out._feed is not None and len(hub.queues) == 1
    over["on"] = True
    await out.poll()
    assert calls[-1] == {"action": "stop", "args": {"cause": "overload"}}
    assert out._feed is None and not hub.queues


def test_gateway_sends_packets_the_module_accepts(tmp_path):
    asyncio.run(_gateway_sends_packets_the_module_accepts(tmp_path))


async def _gateway_sends_packets_the_module_accepts(tmp_path):
    fake, service = await started(tmp_path)
    service.token = au.audio_token("partagé")
    try:
        await service.act("start", {"access": "public"})
        assert await service.open_audio()
        hub = FakeHub()

        async def call(data):
            return service.status()

        out = DiffusionOut(service.df.audio_port, au.audio_token("partagé"), hub, TxTap(), lambda: False, call)
        await out.poll()
        await asyncio.sleep(0.05)
        q = next(iter(hub.queues))
        for _ in range(20):
            await q.put(b"\x22\x00" * au.BLOCK)
        await until(lambda: out.packets >= 20)
        await until(lambda: len(fake.received.get("/bob56fr-public", b"")) > 300)
        await out.close_feed()
    finally:
        await service.stop("station_stop")
        service._udp.close()
        await fake.stop()


def test_overloaded_status_never_carries_secrets(tmp_path):
    cfg = make_cfg(tmp_path)
    service = sv.DiffusionService(cfg, tmp_path / "station.toml")
    st = service.status()
    assert st["active"] is False and "listen_page" in st and "source_password" not in json.dumps(st)
