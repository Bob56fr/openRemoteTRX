# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""API interne des modules : le cœur n'attend jamais un module."""
import asyncio
import json
import time

import pytest

from trxstation.modules.bus import BusServer, CommandRefused
from trxstation.modules.client import BusRefused, ModuleClient, RequestFailed
from trxstation.modules.manifest import parse_manifest
from trxstation.modules.tokens import TokenAuthority


def make_manifest(name="demo", events=("ptt", "freq_mode"), commands=(),
                  client_messages=True, verify_tokens=False):
    return parse_manifest({
        "module": {"name": name, "version": "0.1.0", "api": "1.0", "entry": "a.b"},
        "rights": {"events": list(events), "commands": list(commands),
                   "client_messages": client_messages, "verify_tokens": verify_tokens}})


async def wait_until(pred, timeout=3.0, step=0.01):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return True
        await asyncio.sleep(step)
    return pred()

SECRETS = {"demo": "secret-demo", "cluster": "secret-cluster", "video": "secret-video"}


def make_bus(state=None, **kw):
    manifests = {
        "demo": make_manifest("demo"),
        "cluster": make_manifest("cluster", events=("ptt", "freq_mode"), commands=("qsy",)),
        "video": make_manifest("video", events=("ptt",), client_messages=True,
                               verify_tokens=True),
    }
    state = state if state is not None else {"ptt": False, "freq": 14074000}
    return BusServer(manifests, SECRETS, state_provider=lambda: state, **kw), state


async def start_client(bus, name, **kw):
    client = ModuleClient(name, SECRETS[name], port=bus.port, heartbeat_s=0.05, **kw)
    task = asyncio.ensure_future(client.run_session())
    await asyncio.wait_for(client.connected.wait(), 2)
    assert await wait_until(lambda: name in bus.sessions)
    return client, task


async def close(client, task, bus):
    client.stop()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, ConnectionError, OSError):
        pass
    await bus.stop()


def test_bus_refuse_toute_adresse_non_locale():
    with pytest.raises(ValueError):
        BusServer({}, {}, state_provider=dict, host="0.0.0.0")


def test_evenements_recus_par_les_abonnes_seulement():
    async def scenario():
        bus, _ = make_bus()
        await bus.start()
        got = []
        client, task = await start_client(bus, "video")
        client.on_event = lambda n, d: got.append((n, d))
        bus.publish("freq_mode", {"freq": 7074000})     # video n'y est pas abonné
        bus.publish("ptt", {"active": True})
        assert await wait_until(lambda: got)
        await asyncio.sleep(0.05)
        assert got == [("ptt", {"active": True})]
        await close(client, task, bus)
    asyncio.run(scenario())


def test_secret_invalide_refuse():
    async def scenario():
        bus, _ = make_bus()
        await bus.start()
        client = ModuleClient("demo", "mauvais", port=bus.port)
        with pytest.raises(BusRefused) as exc:
            await client.connect()
        assert exc.value.code == "auth"
        assert "demo" not in bus.sessions
        await bus.stop()
    asyncio.run(scenario())


def test_module_inconnu_refuse():
    async def scenario():
        bus, _ = make_bus()
        await bus.start()
        with pytest.raises(BusRefused):
            await ModuleClient("intrus", "x", port=bus.port).connect()
        await bus.stop()
    asyncio.run(scenario())


def test_presentation_absente_refusee():
    async def scenario():
        bus, _ = make_bus(hello_timeout_s=0.2)
        await bus.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", bus.port)
        line = await asyncio.wait_for(reader.readline(), 2)
        assert json.loads(line)["code"] == "hello"
        writer.close()
        await bus.stop()
    asyncio.run(scenario())


def test_publish_ne_bloque_pas_avec_un_module_qui_ne_lit_jamais():
    """Un module figé ne doit jamais retarder le cœur."""
    async def scenario():
        bus, _ = make_bus(queue_size=32, write_timeout_s=0.3)
        await bus.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", bus.port)
        writer.write((json.dumps({"type": "hello", "module": "demo",
                                  "secret": SECRETS["demo"], "api": "1.0"}) + "\n").encode())
        await writer.drain()
        await reader.readline()                         # welcome, puis plus aucune lecture
        assert await wait_until(lambda: "demo" in bus.sessions)
        payload = {"blob": "x" * 2000}
        t0 = time.perf_counter()
        for _ in range(5000):
            bus.publish("ptt", payload)
        duree = time.perf_counter() - t0
        assert duree < 1.0, f"publish a pris {duree:.2f} s"
        # La file reste bornée…
        assert bus.sessions["demo"].queue.qsize() <= 32
        # …et un module qui ne lit plus finit déconnecté une fois les tampons
        # réseau pleins, le cœur continuant de publier normalement.
        gros = {"blob": "y" * 30000}
        loop = asyncio.get_running_loop()
        fin = loop.time() + 10
        while "demo" in bus.sessions and loop.time() < fin:
            for _ in range(50):
                bus.publish("ptt", gros)
            await asyncio.sleep(0.01)
        assert "demo" not in bus.sessions
        writer.close()
        await bus.stop()
    asyncio.run(scenario())


def test_trou_dans_les_evenements_declenche_une_relecture():
    async def scenario():
        bus, _ = make_bus(queue_size=4)
        await bus.start()
        client, task = await start_client(bus, "demo")
        gaps = []
        client.on_gap = lambda: gaps.append(True)
        sess = bus.sessions["demo"]
        sess.tasks[0].cancel()                          # gèle l'envoi vers ce module
        await asyncio.sleep(0.01)
        for i in range(10):
            bus.publish("ptt", {"i": i})
        assert sess.dropped >= 6
        # Reprise de l'envoi : le module voit un trou dans seq.
        sess.tasks.append(asyncio.ensure_future(bus._writer_loop(sess)))
        assert await wait_until(lambda: gaps)
        await close(client, task, bus)
    asyncio.run(scenario())


def test_get_state_depuis_un_rappel_devenement():
    async def scenario():
        bus, state = make_bus()
        await bus.start()
        client, task = await start_client(bus, "demo")
        lus = []

        async def on_event(name, data):
            lus.append(await client.get_state())
        client.on_event = on_event
        state["freq"] = 7074000
        bus.publish("freq_mode", {"freq": 7074000})
        assert await wait_until(lambda: lus)
        assert lus[0]["freq"] == 7074000
        await close(client, task, bus)
    asyncio.run(scenario())


def test_commande_non_declaree_refusee():
    async def scenario():
        calls = []
        bus, _ = make_bus(command_handler=lambda c, a, m: calls.append((c, a, m)))
        await bus.start()
        client, task = await start_client(bus, "demo")      # pas de droit qsy
        with pytest.raises(RequestFailed) as exc:
            await client.command("qsy", freq=7074000)
        assert exc.value.code == "forbidden" and not calls
        await close(client, task, bus)
    asyncio.run(scenario())


def test_qsy_refuse_pendant_le_ptt_et_accepte_sinon():
    async def scenario():
        calls = []
        bus, state = make_bus(command_handler=lambda c, a, m: calls.append((c, a, m)) or "ok")
        await bus.start()
        client, task = await start_client(bus, "cluster")
        state["ptt"] = True
        with pytest.raises(RequestFailed) as exc:
            await client.command("qsy", freq=7074000, mode="USB")
        assert exc.value.code == "ptt_active" and not calls
        state["ptt"] = False
        assert await client.command("qsy", freq=7074000, mode="USB") == "ok"
        assert calls == [("qsy", {"freq": 7074000, "mode": "USB"}, "cluster")]
        await close(client, task, bus)
    asyncio.run(scenario())


def test_messages_au_terminal_limites_en_debit():
    async def scenario():
        recus = []
        bus, _ = make_bus(client_sink=lambda m, msg: recus.append((m, msg)),
                          client_rate=0.001, client_burst=3)
        await bus.start()
        client, task = await start_client(bus, "demo")
        for i in range(3):
            await client.client_message(text=f"n{i}")
        with pytest.raises(RequestFailed) as exc:
            await client.client_message(text="de trop")
        assert exc.value.code == "rate_limited"
        assert [m["text"] for _, m in recus] == ["n0", "n1", "n2"]
        await close(client, task, bus)
    asyncio.run(scenario())


def test_verification_de_jeton_par_le_module_video():
    async def scenario():
        ta = TokenAuthority()
        bus, _ = make_bus(tokens=ta)
        await bus.start()
        client, task = await start_client(bus, "video")
        tok = ta.issue("f4abc", sid="s9")
        assert (await client.verify_token(tok))["user"] == "f4abc"
        ta.revoke("s9")
        with pytest.raises(RequestFailed) as exc:
            await client.verify_token(tok)
        assert exc.value.code == "token_revoked"
        await close(client, task, bus)
    asyncio.run(scenario())


def test_verification_de_jeton_interdite_sans_droit():
    async def scenario():
        bus, _ = make_bus(tokens=TokenAuthority())
        await bus.start()
        client, task = await start_client(bus, "demo")
        with pytest.raises(RequestFailed) as exc:
            await client.verify_token("x.y")
        assert exc.value.code == "forbidden"
        await close(client, task, bus)
    asyncio.run(scenario())


def test_battements_et_metriques_remontes():
    async def scenario():
        sante = []
        bus, _ = make_bus(health_sink=lambda m, met: sante.append((m, met)))
        await bus.start()
        client, task = await start_client(bus, "demo")
        client.metrics = lambda: {"fps": 12}
        assert await wait_until(lambda: any(met.get("fps") == 12 for _, met in sante))
        assert bus.module_status()["demo"]["metrics"] == {"fps": 12}
        await close(client, task, bus)
    asyncio.run(scenario())


def test_rappel_du_coeur_en_erreur_ne_coupe_pas_le_module():
    async def scenario():
        def casse(m, met):
            raise RuntimeError("bug du cœur")
        bus, _ = make_bus(health_sink=casse)
        await bus.start()
        client, task = await start_client(bus, "demo")
        await asyncio.sleep(0.2)
        assert "demo" in bus.sessions
        assert (await client.get_state())["ptt"] is False
        await close(client, task, bus)
    asyncio.run(scenario())


def test_publish_depuis_un_autre_thread():
    async def scenario():
        bus, _ = make_bus()
        await bus.start()
        got = []
        client, task = await start_client(bus, "demo")
        client.on_event = lambda n, d: got.append(d)
        await asyncio.to_thread(bus.publish_threadsafe, "ptt", {"active": True})
        assert await wait_until(lambda: got == [{"active": True}])
        await close(client, task, bus)
    asyncio.run(scenario())


def test_consigne_de_degradation_a_un_seul_module():
    async def scenario():
        manifests = {"demo": make_manifest("demo", events=("degrade",)),
                     "video": make_manifest("video", events=("ptt",))}
        bus = BusServer(manifests, SECRETS, state_provider=dict)
        await bus.start()
        got = []
        client, task = await start_client(bus, "demo")
        client.on_event = lambda n, d: got.append((n, d))
        assert bus.send_to("demo", "degrade", {"level": 4})
        assert not bus.send_to("video", "degrade", {"level": 4})   # non abonné
        assert await wait_until(lambda: got == [("degrade", {"level": 4})])
        await close(client, task, bus)
    asyncio.run(scenario())


def test_refus_du_coeur_transmis_avec_son_code():
    async def scenario():
        def handler(c, a, m):
            raise CommandRefused("tx_active", "refusé pendant l'émission")
        bus, _ = make_bus(command_handler=handler)
        await bus.start()
        client, task = await start_client(bus, "cluster")
        with pytest.raises(RequestFailed) as exc:
            await client.command("qsy", freq=7074000)
        assert exc.value.code == "tx_active"
        await close(client, task, bus)
    asyncio.run(scenario())


def test_gestionnaire_asynchrone_trop_lent():
    async def scenario():
        async def handler(c, a, m):
            await asyncio.sleep(30)
        bus, _ = make_bus(command_handler=handler, command_timeout_s=0.1)
        await bus.start()
        client, task = await start_client(bus, "cluster")
        with pytest.raises(RequestFailed) as exc:
            await client.command("qsy", freq=7074000)
        assert exc.value.code == "timeout"
        await close(client, task, bus)
    asyncio.run(scenario())
