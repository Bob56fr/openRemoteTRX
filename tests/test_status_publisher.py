import asyncio

from trxstation.config import Audio
from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.gateway.audio import AudioPipeline
from trxstation.gateway.audio.devices import RecordingSink, ToneSource
from trxstation.gateway.cat import CatLink
from trxstation.gateway.safety import PttController, PttLimits
from trxstation.gateway.status import StatusPublisher
from trxstation.setup_wizard import dummy_config
from trxstation.status import read_status


def run(scenario):
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        try:
            await asyncio.wait_for(scenario(fake), 15)
        finally:
            await fake.stop()
    asyncio.run(wrapper())


async def until(predicate, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("condition jamais atteinte")
        await asyncio.sleep(0.01)


def test_publisher_writes_live_state_with_increasing_seq(tmp_path):
    async def scenario(fake):
        path = tmp_path / "run" / "gateway-status.json"
        link = CatLink("127.0.0.1", fake.port, poll_fast_s=0.02, slow_every=2, timeout=0.5)
        ctrl = PttController(link, dummy_config(), limits=PttLimits(
            tot_s=5, warn_before_s=1, heartbeat_timeout_s=1, tick_s=0.02, rekey_cooldown_s=0,
            unkey_retry_s=0.05, unkey_deadline_s=0.5))
        ctrl.connect_client("phone")
        publisher = StatusPublisher(path, link, ctrl, interval_s=0.05)
        link_task = asyncio.create_task(link.run())
        pub_task = asyncio.create_task(publisher.run())
        await ctrl.start()
        try:
            await until(lambda: (s := read_status(path)) is not None and s.rig.get("connected")
                        and s.ptt["state"] == "RX" and s.rig.get("frequency_hz") == 14_200_000)
            first = read_status(path)
            assert first.clients == ["phone"] and first.rig["mode"] == "USB"
            # lectures tolérantes : sous Windows, un remplacement de fichier peut échouer un instant
            await until(lambda: (s := read_status(path)) is not None and s.seq > first.seq)

            await ctrl.toggle("phone")
            await until(lambda: (s := read_status(path)) is not None and s.ptt["state"] == "TX")
            await until(lambda: (s := read_status(path)) is not None and s.ptt["owner"] == "phone")
        finally:
            await ctrl.close()
            publisher.stop()
            link.stop()
            await asyncio.wait_for(asyncio.gather(link_task, pub_task), 3)
    run(scenario)


def test_publisher_survives_unwritable_destination(tmp_path):
    async def scenario(fake):
        blocker = tmp_path / "pas_un_dossier"
        blocker.write_text("je suis un fichier")
        link = CatLink("127.0.0.1", fake.port, timeout=0.5)
        ctrl = PttController(link, dummy_config())
        publisher = StatusPublisher(blocker / "status.json", link, ctrl, interval_s=0.05)
        task = asyncio.create_task(publisher.run())
        await asyncio.sleep(0.3)                  # l'écriture échoue à chaque tour, sans tuer la boucle
        assert not task.done()
        publisher.stop()
        await asyncio.wait_for(task, 2)
    run(scenario)


def test_publisher_includes_audio_stats_when_a_pipeline_is_given(tmp_path):
    async def scenario(fake):
        path = tmp_path / "status.json"
        link = CatLink("127.0.0.1", fake.port, timeout=0.5)
        ctrl = PttController(link, dummy_config())
        pipeline = AudioPipeline(Audio(), source=ToneSource(1000, -10), sink=RecordingSink())
        publisher = StatusPublisher(path, link, ctrl, interval_s=0.05, pipeline=pipeline)
        await pipeline.start()
        task = asyncio.create_task(publisher.run())
        try:
            await until(lambda: (s := read_status(path)) is not None and s.audio.get("rx_db", -90) > -30)
            audio = read_status(path).audio
            assert audio["gate_open"] is False and audio["listeners"] == 0
        finally:
            publisher.stop()
            await asyncio.wait_for(task, 2)
            await pipeline.stop()
    run(scenario)
