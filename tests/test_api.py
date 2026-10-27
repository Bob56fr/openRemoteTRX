"""API client : protocole, authentification, session de contrôle (sans aucun transport réseau)."""
import asyncio
import contextlib
import json

import pytest

from trxstation import config as cfgmod
from trxstation.config import Audio, ClientAuth
from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.gateway.api.auth import ClientRegistry, client_source
from trxstation.gateway.api.protocol import MAX_MESSAGE_BYTES, ProtocolError, parse_command
from trxstation.gateway.api.session import ControlSession, build_state
from trxstation.gateway.audio import AudioPipeline
from trxstation.gateway.audio.devices import RecordingSink, SilenceSource
from trxstation.gateway.audio.pcm import tone
from trxstation.gateway.cat import Capabilities, CatLink
from trxstation.gateway.memories import MemoryStore
from trxstation.gateway.safety import PttController, PttLimits
from trxstation.passwords import hash_password
from trxstation.setup_wizard import SetupError, add_client, dummy_config, set_password
from trxstation.status import GatewayStatus, read_status, write_status


# --------------------------------------------------------------------------- protocole

def cmd(**fields):
    return parse_command(json.dumps(fields))


def test_valid_commands_parse():
    assert cmd(cmd="toggle", id=7).name == "toggle" and cmd(cmd="toggle", id=7).id == 7
    assert cmd(cmd="heartbeat").id is None
    assert cmd(cmd="set_frequency", hz=14_200_000).params == {"hz": 14_200_000}
    assert cmd(cmd="set_mode", mode="USB", passband=2400).params == {"mode": "USB", "passband": 2400}
    assert cmd(cmd="set_mode", mode="LSB").params["passband"] == 0
    assert cmd(cmd="toggle", extra="ignoré").name == "toggle"
    assert parse_command(b'{"cmd": "stop"}').name == "stop"


@pytest.mark.parametrize("raw,code", [
    ("pas du json", "bad_json"), ("[1, 2]", "bad_message"), ('"texte"', "bad_message"),
    ('{"cmd": "format_disk"}', "unknown_command"), ('{}', "unknown_command"),
    ('{"cmd": "toggle", "id": "x"}', "invalid_params"), ('{"cmd": "toggle", "id": true}', "invalid_params"),
    ('{"cmd": "toggle", "id": -1}', "invalid_params"),
    ('{"cmd": "set_frequency"}', "invalid_params"), ('{"cmd": "set_frequency", "hz": 0}', "invalid_params"),
    ('{"cmd": "set_frequency", "hz": 14.2e6}', "invalid_params"), ('{"cmd": "set_frequency", "hz": true}', "invalid_params"),
    ('{"cmd": "set_frequency", "hz": "14200000"}', "invalid_params"),
    ('{"cmd": "set_frequency", "hz": 99999999999}', "invalid_params"),
    ('{"cmd": "set_mode", "mode": "USB\\nT 1"}', "invalid_params"), ('{"cmd": "set_mode", "mode": ""}', "invalid_params"),
    ('{"cmd": "set_mode", "mode": 5}', "invalid_params"), ('{"cmd": "set_mode", "mode": "USB", "passband": 99999}', "invalid_params"),
])
def test_malformed_commands_are_rejected_with_a_code(raw, code):
    with pytest.raises(ProtocolError) as exc:
        parse_command(raw)
    assert exc.value.code == code


def test_oversized_message_is_rejected_before_parsing():
    with pytest.raises(ProtocolError) as exc:
        parse_command("x" * (MAX_MESSAGE_BYTES + 1))
    assert exc.value.code == "too_large"


# --------------------------------------------------------------------------- authentification

PASSWORD = "Un mot de passe correct 42"


def hashed_registry(**kwargs):
    return ClientRegistry([ClientAuth("phone", password_hash=hash_password(PASSWORD))], **kwargs)


def test_registry_accepts_only_the_right_password():
    registry = hashed_registry()
    assert registry and registry.verify("phone", PASSWORD, "1.2.3.4")
    assert not registry.verify("phone", "Un mot de passe faux 4242", "1.2.3.4")
    assert not registry.verify("inconnu", PASSWORD, "1.2.3.4")
    assert not registry.verify("phone", "", "1.2.3.4") and not registry.verify("", "", "1.2.3.4")
    assert not registry.verify("phone", "x" * 1000, "1.2.3.4") and not registry.verify(None, PASSWORD, "1.2.3.4")
    assert not ClientRegistry([])


def test_legacy_plaintext_token_is_still_accepted():
    registry = ClientRegistry([ClientAuth("phone", "token-phone-0123456789")])
    assert registry.verify("phone", "token-phone-0123456789", "1.2.3.4")
    assert not registry.verify("phone", "token-phone-0123456780", "1.2.3.4")


def test_unknown_account_cannot_be_distinguished_from_a_wrong_password_by_timing():
    import time
    registry = hashed_registry(max_failures=10_000)
    def timed(client_id):
        start = time.perf_counter()
        for _ in range(3):
            registry.verify(client_id, "Un mot de passe faux 4242", "1.1.1.1")
        return (time.perf_counter() - start) / 3
    known, unknown = timed("phone"), timed("fantome")
    assert unknown > 0.5 * known                                  # un hachage factice est calculé aussi pour un compte inconnu


def test_registry_locks_out_a_source_after_repeated_failures_then_recovers():
    now = [0.0]
    registry = hashed_registry(clock=lambda: now[0], max_failures=3, window_s=60)
    for _ in range(3):
        assert not registry.verify("phone", "faux faux faux faux", "attaquant")
    assert registry.locked("attaquant")
    assert not registry.verify("phone", PASSWORD, "attaquant")           # même avec le bon mot de passe
    assert registry.verify("phone", PASSWORD, "ami")                      # une autre origine n'est pas touchée
    now[0] = 61.0
    assert registry.verify("phone", PASSWORD, "attaquant")                # le verrou expire


def test_account_is_throttled_across_many_sources_but_recovers():
    now = [0.0]
    registry = hashed_registry(clock=lambda: now[0], max_failures=5, account_max_failures=8, account_window_s=900)
    for i in range(8):                                             # attaque répartie : 8 origines différentes
        assert not registry.verify("phone", "faux faux faux faux", f"origine-{i}")
    assert not registry.verify("phone", PASSWORD, "origine-neuve")        # le compte est verrouillé
    now[0] = 901.0
    assert registry.verify("phone", PASSWORD, "origine-neuve")


def test_locked_attempts_do_not_burn_cpu():
    import time
    registry = hashed_registry(max_failures=2)
    for _ in range(2):
        registry.verify("phone", "faux faux faux faux", "attaquant")
    start = time.perf_counter()
    for _ in range(50):
        assert not registry.verify("phone", PASSWORD, "attaquant")
    assert time.perf_counter() - start < 0.5                       # 50 refus sans hachage (50 hachages dureraient ~5 s)


def test_failure_tables_stay_bounded_under_a_flood_of_sources():
    now = [0.0]
    registry = hashed_registry(clock=lambda: now[0], window_s=1.0)
    for i in range(25):
        registry._record_failure(f"s{i}", "")
    now[0] = 100.0
    from trxstation.gateway.api import auth
    for i in range(auth.MAX_TRACKED + 5):
        registry._by_source[f"x{i}"].append(0.0)
    registry._record_failure("nouvelle", "")
    assert len(registry._by_source) <= 2                            # les entrées expirées sont purgées


def test_client_source_trusts_forwarded_for_only_from_trusted_proxies():
    assert client_source("127.0.0.1", "100.64.0.9") == "100.64.0.9"
    assert client_source("203.0.113.5", "198.51.100.7") == "203.0.113.5"             # en-tête forgé : ignoré
    assert client_source("192.168.1.1", "198.51.100.7", trusted=["192.168.1.0/24"]) == "198.51.100.7"   # proxy du réseau local
    assert client_source("192.168.2.1", "198.51.100.7", trusted=["192.168.1.0/24"]) == "192.168.2.1"
    assert client_source("127.0.0.1", "198.51.100.7", trusted=[]) == "127.0.0.1"
    assert client_source("127.0.0.1", "198.51.100.7", trusted=["pas une adresse"]) == "127.0.0.1"


# --------------------------------------------------------------------------- configuration des clients

def test_client_config_validation_and_roundtrip(tmp_path):
    cfg = dummy_config()
    cfg.clients = [ClientAuth("phone", password_hash=hash_password(PASSWORD)), ClientAuth("car", "token-car-0123456789ab")]
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    assert cfgmod.load(path) == cfg
    assert "scrypt$" in path.read_text(encoding="utf-8") and PASSWORD not in path.read_text(encoding="utf-8")
    good = hash_password(PASSWORD)
    for clients, fragment in (([ClientAuth("a b", "x" * 20)], "invalide"), ([ClientAuth("a", "court")], "trop court"),
                              ([ClientAuth("a", "x" * 20), ClientAuth("a", "y" * 20)], "double"),
                              ([ClientAuth("a")], "exactement un secret"),
                              ([ClientAuth("a", "x" * 20, good)], "exactement un secret"),
                              ([ClientAuth("a", password_hash="scrypt$bidon")], "password_hash invalide")):
        bad = dummy_config()
        bad.clients = clients
        assert any(fragment in p for p in cfgmod.validate(bad)), fragment
    bad = dummy_config()
    bad.audio.sample_rate = 44100
    bad.audio.tx_gain_db = 50
    assert len([p for p in cfgmod.validate(bad) if "[audio]" in p]) == 2


def test_network_exposure_settings_are_validated_and_roundtrip(tmp_path):
    cfg = dummy_config()
    cfg.network.tls_cert, cfg.network.tls_key = "/etc/trx/cert.pem", "/etc/trx/key.pem"
    cfg.network.trusted_proxies = ["127.0.0.1", "192.168.1.0/24"]
    cfg.network.ice_servers = []
    cfg.network.allow_insecure_http = True
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    assert cfgmod.load(path) == cfg
    for change, fragment in ((lambda n: setattr(n, "tls_cert", "x"), "vont ensemble"),
                             (lambda n: setattr(n, "trusted_proxies", ["abc"]), "trusted_proxies"),
                             (lambda n: setattr(n, "ice_servers", ["http://x"]), "ice_servers")):
        bad = dummy_config()
        change(bad.network)
        assert any(fragment in p for p in cfgmod.validate(bad)), fragment


def test_exposure_check_refuses_clear_text_on_the_network_unless_explicitly_allowed():
    cfg = dummy_config()
    assert cfgmod.exposure_problem(cfg) == ""                                   # boucle locale : rien à dire
    for host in ("127.0.0.1", "::1", "localhost"):
        cfg.network.gateway_bind = host
        assert cfgmod.exposure_problem(cfg) == ""
    cfg.network.gateway_bind = "0.0.0.0"
    assert "SANS chiffrement" in cfgmod.exposure_problem(cfg)
    assert any("SANS chiffrement" in w for w in cfgmod.warnings(cfg))
    cfg.network.allow_insecure_http = True                                      # VPN qui chiffre déjà
    assert cfgmod.exposure_problem(cfg) == ""
    cfg.network.allow_insecure_http = False
    cfg.network.tls_cert, cfg.network.tls_key = "c.pem", "k.pem"                # HTTPS natif
    assert cfgmod.exposure_problem(cfg) == ""
    cfg.network.tls_cert = cfg.network.tls_key = ""
    cfg.network.gateway_bind = "192.168.1.10"
    assert cfgmod.exposure_problem(cfg) != ""


def test_add_client_stores_only_a_hash_and_enforces_the_password_policy():
    cfg = dummy_config()
    password = add_client(cfg, "phone")                                         # généré
    from trxstation.passwords import verify_password
    assert len(password) >= 16 and cfg.clients[0].token == "" and verify_password(password, cfg.clients[0].password_hash)
    assert cfgmod.validate(cfg) == [] and password not in cfgmod.render_toml(cfg)
    assert add_client(cfg, "car", "Une phrase de passe très longue") and len(cfg.clients) == 2
    for call in (lambda: add_client(cfg, "phone", "Un mot de passe correct 42"),   # identifiant en double
                 lambda: add_client(cfg, "nom invalide !"),
                 lambda: add_client(cfg, "tablet", "court"),
                 lambda: add_client(cfg, "tablet", "aaaaaaaaaaaaaaaaaaaa"),
                 lambda: add_client(cfg, "tablet", "contient-tablet-dans-le-mot")):
        try:
            call()
            assert False, "SetupError attendue"
        except SetupError:
            pass


def test_set_password_replaces_the_secret_and_drops_a_legacy_token():
    from trxstation.passwords import verify_password
    cfg = dummy_config()
    cfg.clients = [ClientAuth("phone", "token-phone-0123456789")]
    new = set_password(cfg, "phone", "Une nouvelle phrase de passe")
    assert cfg.clients[0].token == "" and verify_password(new, cfg.clients[0].password_hash) and cfgmod.validate(cfg) == []
    try:
        set_password(cfg, "inconnu", "Une nouvelle phrase de passe")
        assert False, "SetupError attendue"
    except SetupError:
        pass


# --------------------------------------------------------------------------- fichier d'état

def test_status_file_carries_audio_stats_and_stays_backward_compatible(tmp_path):
    path = tmp_path / "s.json"
    write_status(path, GatewayStatus(pid=1, seq=1, written_at=0.0, ptt={"state": "RX"}, rig={}, audio={"rx_db": -30}))
    assert read_status(path).audio == {"rx_db": -30}
    path.write_text('{"schema": 1, "pid": 1, "seq": 1, "written_at": 0, "ptt": {"state": "RX"}, "rig": {}}')
    assert read_status(path).audio == {}                                            # ancien format : accepté
    path.write_text('{"schema": 1, "pid": 1, "seq": 1, "written_at": 0, "ptt": {"state": "RX"}, "rig": {}, "audio": 5}')
    assert read_status(path).audio == {}                                            # valeur absurde : ignorée


# --------------------------------------------------------------------------- session de contrôle

def run(scenario):
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        try:
            await asyncio.wait_for(scenario(fake), 20)
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


class Client:
    """Un client branché sur une ControlSession, qui enregistre tout ce qu'il reçoit."""

    def __init__(self, station, client_id, **kwargs):
        self.messages = []
        self.session = ControlSession(client_id, station.ctrl, station.link, station.pipeline,
                                      station.capabilities, self.messages.append, state_interval_s=0.05,
                                      memories=kwargs.pop("memories", getattr(station, "memories", None)), **kwargs)
        self.client_id = client_id

    async def say(self, **fields):
        await self.session.on_message(json.dumps(fields))

    def of_type(self, kind):
        return [m for m in self.messages if m.get("type") == kind]

    def result(self, ident):
        return next(m for m in self.messages if m.get("type") == "result" and m.get("id") == ident)


@contextlib.asynccontextmanager
async def station(fake, *, limits=None, capabilities=None):
    class Station:
        pass
    st = Station()
    cfg = dummy_config()
    st.link = CatLink("127.0.0.1", fake.port, poll_fast_s=0.02, slow_every=2, backoff_min_s=0.05,
                      backoff_max_s=0.2, timeout=0.5)
    st.sink = RecordingSink()
    st.pipeline = AudioPipeline(Audio(), source=SilenceSource(), sink=st.sink)
    st.capabilities = capabilities
    st.memories = MemoryStore()
    st.ctrl = PttController(st.link, cfg, limits=limits or PttLimits(
        tot_s=5, warn_before_s=1, heartbeat_timeout_s=1.0, tick_s=0.02, rekey_cooldown_s=0,
        unkey_retry_s=0.05, unkey_deadline_s=0.5), audio_gate=st.pipeline.gate.set_open)
    st.pipeline.gate.owner_provider = lambda: st.ctrl.snapshot().owner
    link_task = asyncio.create_task(st.link.run())
    await st.ctrl.start()
    await until(lambda: st.link.state.connected and not st.ctrl.starting)
    st.clients = []
    try:
        yield st
    finally:
        for client in st.clients:
            await client.session.close()
        await asyncio.wait_for(st.ctrl.close(), 5)
        st.link.stop()
        await asyncio.wait_for(link_task, 3)


async def connect(st, client_id, **kwargs):
    client = Client(st, client_id, **kwargs)
    st.clients.append(client)
    await client.session.start()
    return client


def test_session_greets_registers_and_closes_cleanly():
    async def scenario(fake):
        caps = Capabilities(model_name="Faux poste", modes=("USB", "LSB"), complete=True)
        async with station(fake, capabilities=caps) as st:
            phone = await connect(st, "phone")
            hello = phone.of_type("hello")[0]
            assert hello["protocol"] == 1 and hello["client_id"] == "phone"
            assert hello["capabilities"]["modes"] == ["USB", "LSB"] and hello["tx_modes"] == []
            assert hello["layouts"] is False                                        # pas de stockage de mises en page ici
            from trxstation import __version__
            assert hello["version"] == __version__                                  # affichée par la page à droite de « Connecté »
            assert phone.of_type("state")[0]["ptt"]["state"] == "RX" and st.ctrl.clients == ["phone"]
            await phone.session.close()
            await phone.session.close()                                             # idempotent
            assert st.ctrl.clients == []
    run(scenario)


def test_toggle_keys_opens_the_audio_gate_and_toggles_back():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await phone.say(cmd="toggle", id=1)
            result = phone.result(1)
            assert result["ok"] and result["ptt"]["state"] == "TX" and result["ptt"]["owner"] == "phone"
            assert fake.ptt == 1 and st.pipeline.gate.is_open
            await until(lambda: any(m["ptt"]["state"] == "TX" for m in phone.of_type("state")))   # diffusion d'état
            await phone.say(cmd="toggle", id=2)
            assert phone.result(2)["ok"] and fake.ptt == 0 and not st.pipeline.gate.is_open
    run(scenario)


def test_only_the_owner_audio_reaches_the_rig_and_any_client_can_cut():
    async def scenario(fake):
        async with station(fake) as st:
            phone, car = await connect(st, "phone"), await connect(st, "car")
            await phone.say(cmd="toggle", id=1)
            audio = tone(1000, -10)
            assert st.pipeline.gate.push("phone", audio) and not st.pipeline.gate.push("car", audio)
            assert len(st.sink.frames) == 1 and st.pipeline.gate.dropped_not_owner == 1
            await car.say(cmd="toggle", id=2)                                       # couper n'est jamais refusé
            assert car.result(2)["ok"] and fake.ptt == 0
            assert not st.pipeline.gate.push("phone", audio) and st.sink.flushes >= 1
    run(scenario)


def test_heartbeats_keep_transmission_alive_and_silence_cuts_it():
    async def scenario(fake):
        limits = PttLimits(tot_s=5, warn_before_s=1, heartbeat_timeout_s=0.3, tick_s=0.02, rekey_cooldown_s=0,
                           unkey_retry_s=0.05, unkey_deadline_s=0.5)
        async with station(fake, limits=limits) as st:
            phone = await connect(st, "phone")
            await phone.say(cmd="toggle", id=1)
            for _ in range(8):                                                      # 0,8 s de battements
                await phone.say(cmd="heartbeat")
                await asyncio.sleep(0.1)
            assert st.ctrl.snapshot().state == "TX"
            await until(lambda: st.ctrl.snapshot().state == "RX", 3)                # plus de battement : coupure
            assert st.ctrl.snapshot().last_cut_reason == "heartbeat" and fake.ptt == 0
    run(scenario)


def test_stop_command_cuts():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await phone.say(cmd="toggle", id=1)
            await phone.say(cmd="stop", id=2)
            assert phone.result(2)["ok"] and fake.ptt == 0 and st.ctrl.snapshot().last_cut_reason == "stop"
    run(scenario)


def test_tuning_commands_and_the_refusal_while_transmitting():
    async def scenario(fake):
        caps = Capabilities(modes=("USB", "LSB"), complete=True)
        async with station(fake, capabilities=caps) as st:
            st.link.capabilities = caps
            phone = await connect(st, "phone")
            await phone.say(cmd="set_frequency", id=1, hz=7_100_000)
            await phone.say(cmd="set_mode", id=2, mode="LSB", passband=2400)
            assert phone.result(1)["ok"] and phone.result(2)["ok"]
            assert fake.freq == 7_100_000 and fake.mode == "LSB" and fake.passband == 2400
            await phone.say(cmd="set_mode", id=3, mode="FM")                        # non supporté par ce poste
            assert not phone.result(3)["ok"] and phone.result(3)["reason"] == "invalid"
            await phone.say(cmd="toggle", id=4)
            await phone.say(cmd="set_frequency", id=5, hz=14_200_000)
            assert phone.result(5)["reason"] == "tx_active" and fake.freq == 7_100_000
    run(scenario)


def test_refusals_come_back_with_stable_reason_codes():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            fake.freq = 14_500_000
            await phone.say(cmd="toggle", id=1)
            assert not phone.result(1)["ok"] and phone.result(1)["reason"] == "out_of_band" and fake.ptt == 0
            fake.freq = 14_200_000
            await fake.stop()
            await until(lambda: not st.link.state.connected)
            await phone.say(cmd="toggle", id=2)
            assert phone.result(2)["reason"] == "cat_down"
            await phone.say(cmd="set_frequency", id=3, hz=7_000_000)
            assert phone.result(3)["reason"] in ("cat_down", "rig_error")
    run(scenario)


def test_bad_input_gets_error_messages_not_exceptions_and_rate_limit_applies():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone", max_msgs_per_s=30)
            for raw in ("n'importe quoi", '{"cmd": "reboot"}', '{"cmd": "set_frequency", "hz": "x"}'):
                await phone.session.on_message(raw)
            codes = [m["code"] for m in phone.of_type("error")]
            assert codes == ["bad_json", "unknown_command", "invalid_params"]
            for _ in range(40):
                await phone.session.on_message('{"cmd": "heartbeat"}')
            assert "rate_limited" in [m["code"] for m in phone.of_type("error")]
            assert st.ctrl.snapshot().state == "RX"                                 # rien d'anormal n'a été exécuté
    run(scenario)


def test_closing_the_owner_session_cuts_transmission_but_not_a_listener_session():
    async def scenario(fake):
        async with station(fake) as st:
            phone, car = await connect(st, "phone"), await connect(st, "car")
            await phone.say(cmd="toggle", id=1)
            await car.session.close()
            assert st.ctrl.snapshot().state == "TX" and fake.ptt == 1
            await phone.session.close()                                             # le propriétaire disparaît
            assert st.ctrl.snapshot().state == "RX" and fake.ptt == 0
            assert st.ctrl.snapshot().last_cut_reason == "client_disconnected"
    run(scenario)


def test_state_is_resent_at_least_every_second_and_get_state_works():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            before = len(phone.of_type("state"))
            await asyncio.sleep(1.2)
            assert len(phone.of_type("state")) >= before + 1                        # au moins un rappel
            await phone.say(cmd="get_state", id=9)
            state = phone.result(9)["state"]
            assert state["rig"]["frequency_hz"] == 14_200_000 and state["audio"]["gate_open"] is False
            assert state["type"] == "state" and set(build_state(st.link, st.ctrl, st.pipeline)) == set(state)
    run(scenario)


def test_tx_modes_roundtrip_validation_and_hello(tmp_path):
    cfg = dummy_config()
    cfg.rig.tx_modes = ["PKTUSB", "PKTLSB"]
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    assert cfgmod.load(path).rig.tx_modes == ["PKTUSB", "PKTLSB"]
    bad = dummy_config()
    bad.rig.tx_modes = ["USB\nT 1"]
    assert any("tx_modes" in p for p in cfgmod.validate(bad))

    async def scenario(fake):
        async with station(fake) as st:
            st.ctrl.config.rig.tx_modes = ["PKTUSB"]
            phone = await connect(st, "phone")
            assert phone.of_type("hello")[0]["tx_modes"] == ["PKTUSB"]
    run(scenario)


# --------------------------------------------------------------------------- mémoires, squelch, indicateurs

def test_protocol_parses_the_new_commands_and_refuses_bad_values():
    assert cmd(cmd="set_squelch", value=0.5).params == {"value": 0.5}
    assert cmd(cmd="set_squelch", value=1).params == {"value": 1.0} and cmd(cmd="set_squelch", value=0).params == {"value": 0.0}
    for bad in ('-0.1', '1.1', 'true', '"0.5"', 'null', 'NaN', 'Infinity'):
        with pytest.raises(ProtocolError):
            parse_command('{"cmd": "set_squelch", "value": %s}' % bad)
    saved = cmd(cmd="memory_save", id=7, name=" 40 m SSB ", hz=7_100_000, mode="LSB", favorite=True)
    assert saved.id == 7                                                          # « id » : le numéro de la requête
    assert saved.params == {"name": "40 m SSB", "hz": 7_100_000, "mode": "LSB", "favorite": True, "memory_id": None}
    assert cmd(cmd="memory_save", name="x", hz=1, mode="USB", memory_id="ab12cd").params["memory_id"] == "ab12cd"
    assert cmd(cmd="memory_delete", id=3, memory_id="ab12cd").params == {"memory_id": "ab12cd"}
    assert cmd(cmd="memory_recall", memory_id="ab12").name == "memory_recall"
    for raw in ({"cmd": "memory_save", "name": "", "hz": 1, "mode": "USB"}, {"cmd": "memory_save", "name": "x", "hz": 0, "mode": "USB"},
                {"cmd": "memory_save", "name": "x", "hz": 1, "mode": "USB\nT 1"},
                {"cmd": "memory_save", "name": "x", "hz": 1, "mode": "USB", "memory_id": "../x"},
                {"cmd": "memory_save", "name": "x", "hz": 1, "mode": "USB", "favorite": "oui"},
                {"cmd": "memory_delete", "memory_id": "../../etc"}, {"cmd": "memory_delete"}, {"cmd": "memory_recall", "memory_id": 5},
                {"cmd": "memory_recall", "id": 5}):                                  # sans memory_id : refusé
        with pytest.raises(ProtocolError) as exc:
            parse_command(json.dumps(raw))
        assert exc.value.code == "invalid_params", raw


def test_memories_are_saved_listed_recalled_and_shared_between_clients():
    async def scenario(fake):
        async with station(fake) as st:
            phone, car = await connect(st, "phone"), await connect(st, "car")
            assert phone.of_type("hello")[0]["memories"] == []
            await phone.say(cmd="memory_save", id=1, name="Réseau 40 m", hz=7_100_000, mode="LSB", favorite=True)
            saved = phone.result(1)["memory"]
            assert phone.result(1)["ok"] and saved["name"] == "Réseau 40 m" and saved["favorite"] is True
            assert car.of_type("memories")[-1]["items"][0]["id"] == saved["id"]           # l'autre client est prévenu aussitôt
            assert phone.of_type("memories")[-1]["items"] == car.of_type("memories")[-1]["items"]
            await phone.say(cmd="memory_save", id=2, memory_id=saved["id"], name="Renommée", hz=7_105_000, mode="LSB", favorite=False)
            assert phone.result(2)["ok"] and len(st.memories.list()) == 1 and st.memories.list()[0]["name"] == "Renommée"
            assert car.of_type("memories")[-1]["items"][0]["name"] == "Renommée"
            await car.say(cmd="memory_delete", id=3, memory_id=saved["id"])
            assert car.result(3)["ok"] and phone.of_type("memories")[-1]["items"] == []
            late = await connect(st, "tablet")                                              # un nouveau client reçoit la liste d'emblée
            st.memories.save(name="Déjà là", hz=3_700_000, mode="LSB")
            assert late.of_type("hello")[0]["memories"] == [] and late.of_type("memories")[-1]["items"][0]["name"] == "Déjà là"
            await late.session.close()
            count = len(late.of_type("memories"))
            st.memories.save(name="Après fermeture", hz=3_800_000, mode="LSB")
            assert len(late.of_type("memories")) == count                                    # une session fermée n'écoute plus
    run(scenario)


def test_recall_applies_mode_then_frequency_and_is_refused_while_transmitting():
    async def scenario(fake):
        caps = Capabilities(modes=("USB", "LSB", "PKTUSB"), complete=True)
        async with station(fake, capabilities=caps) as st:
            st.link.capabilities = caps
            phone = await connect(st, "phone")
            memory = st.memories.save(name="40 m", hz=7_074_000, mode="PKTUSB")
            await phone.say(cmd="memory_recall", id=1, memory_id=memory.id)
            assert phone.result(1)["ok"] and phone.result(1)["memory"]["name"] == "40 m"
            await until(lambda: fake.freq == 7_074_000 and fake.mode == "PKTUSB")
            sent = [c for c in fake.commands if c.startswith("+M ") or c.startswith("+F ")]
            assert sent[-2:] == ["+M PKTUSB 0", "+F 7074000"]                                # le mode d'abord, puis la fréquence
            await until(lambda: st.link.state.mode == "PKTUSB")
            before = fake.commands.count("+M PKTUSB 0")
            await phone.say(cmd="memory_recall", id=2, memory_id=memory.id)
            assert fake.commands.count("+M PKTUSB 0") == before                              # déjà dans ce mode : filtre intact
            await phone.say(cmd="toggle", id=3)
            other = st.memories.save(name="20 m", hz=14_200_000, mode="PKTUSB")
            await phone.say(cmd="memory_recall", id=4, memory_id=other.id)
            assert phone.result(4)["ok"] is False and phone.result(4)["reason"] == "tx_active" and fake.freq == 7_074_000
    run(scenario)


def test_memory_commands_report_clear_errors():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await phone.say(cmd="memory_recall", id=1)                                       # memory_id manquant : erreur de protocole
            assert phone.of_type("error")[-1]["code"] == "invalid_params"
            await phone.say(cmd="memory_delete", id=2, memory_id="ab12cd34")
            await phone.say(cmd="memory_recall", id=3, memory_id="ab12cd34")
            assert phone.result(2)["reason"] == "unknown_memory" and phone.result(3)["reason"] == "unknown_memory"
            out = []
            lonely = ControlSession("x", st.ctrl, st.link, st.pipeline, None, out.append, memories=None)
            await lonely.on_message(json.dumps({"cmd": "memory_delete", "id": 4, "memory_id": "ab12cd34"}))
            assert out[-1]["reason"] == "memories_unavailable"
    run(scenario)


def test_squelch_command_and_the_new_indicators_in_the_state():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await until(lambda: "SQL" in st.link.state.levels and "NB" in st.link.state.functions)
            await phone.say(cmd="set_squelch", id=1, value=0.6)
            assert phone.result(1)["ok"] and fake.levels["SQL"] == 0.6
            await phone.say(cmd="set_squelch", id=2, value=2)
            assert phone.of_type("error")[-1]["code"] == "invalid_params" and fake.levels["SQL"] == 0.6
            await phone.say(cmd="get_state", id=3)
            rig = phone.result(3)["state"]["rig"]
            assert rig["functions"]["NB"] is True and rig["levels"]["SQL"] == 0.6 and rig["levels"]["PREAMP"] == 10
            fake.errors["L"] = -11                                                            # le poste refuse : message clair
            await phone.say(cmd="set_squelch", id=4, value=0.3)
            assert phone.result(4)["ok"] is False and phone.result(4)["reason"] == "rig_error"
    run(scenario)


def test_protocol_parses_function_and_level_commands_and_refuses_anything_else():
    assert cmd(cmd="set_function", name="NR", on=True).params == {"name": "NR", "on": True}
    assert cmd(cmd="set_function", name="TUNER", on=False).params == {"name": "TUNER", "on": False}
    assert cmd(cmd="set_level", name="AGC", value=5).params == {"name": "AGC", "value": 5}
    assert cmd(cmd="set_level", name="PREAMP", value=0).params == {"name": "PREAMP", "value": 0}
    bad = ({"cmd": "set_function", "name": "PTT", "on": True}, {"cmd": "set_function", "name": "VOX", "on": True},
           {"cmd": "set_function", "name": "NR", "on": 1}, {"cmd": "set_function", "name": "NR"}, {"cmd": "set_function", "on": True},
           {"cmd": "set_function", "name": "NR\nT 1", "on": True},
           {"cmd": "set_level", "name": "MICGAIN", "value": 1}, {"cmd": "set_level", "name": "SQL", "value": 1},
           {"cmd": "set_level", "name": "AGC", "value": 7}, {"cmd": "set_level", "name": "AGC", "value": 2.5},
           {"cmd": "set_level", "name": "AGC", "value": True}, {"cmd": "set_level", "name": "PREAMP", "value": 31},
           {"cmd": "set_level", "name": "AGC", "value": "2"}, {"cmd": "set_level", "name": "AGC"})
    for raw in bad:
        with pytest.raises(ProtocolError) as exc:
            parse_command(json.dumps(raw))
        assert exc.value.code == "invalid_params", raw


def test_session_applies_functions_and_levels_and_reports_refusals():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await until(lambda: "NR" in st.link.state.functions and "AGC" in st.link.state.levels)
            await phone.say(cmd="set_function", id=1, name="NR", on=True)
            await phone.say(cmd="set_level", id=2, name="AGC", value=3)
            assert phone.result(1)["ok"] and phone.result(2)["ok"] and fake.funcs["NR"] == 1 and fake.levels["AGC"] == 3
            await phone.say(cmd="get_state", id=3)
            rig = phone.result(3)["state"]["rig"]
            assert rig["functions"]["NR"] is True and rig["levels"]["AGC"] == 3
            await phone.say(cmd="toggle", id=4)
            await phone.say(cmd="set_function", id=5, name="TUNER", on=True)
            assert phone.result(5)["ok"] is False and phone.result(5)["reason"] == "tx_active" and fake.funcs["TUNER"] == 0
            await phone.say(cmd="set_level", id=6, name="AGC", value=9)
            assert phone.of_type("error")[-1]["code"] == "invalid_params"
    run(scenario)


def test_protocol_accepts_only_the_six_power_steps():
    for step in (0.05, 0.1, 0.25, 0.5, 0.8, 1, 1.0):
        assert cmd(cmd="set_level", name="RFPOWER", value=step).params == {"name": "RFPOWER", "value": float(step)}
    for bad in ('0', '0.3', '0.07', '1.01', '5', '100', '-0.5', 'true', '"0.5"', 'null', 'NaN', 'Infinity'):
        with pytest.raises(ProtocolError) as exc:
            parse_command('{"cmd": "set_level", "name": "RFPOWER", "value": %s}' % bad)
        assert exc.value.code == "invalid_params", bad


def test_session_sets_the_tx_power_and_announces_the_rig_maximum():
    async def scenario(fake):
        async with station(fake) as st:
            st.ctrl.config.rig.max_power_w = 100
            phone = await connect(st, "phone")
            assert phone.of_type("hello")[0]["max_power_w"] == 100
            await until(lambda: "RFPOWER" in st.link.state.levels)
            await phone.say(cmd="set_level", id=1, name="RFPOWER", value=0.05)
            assert phone.result(1)["ok"] and fake.levels["RFPOWER"] == 0.05
            await phone.say(cmd="get_state", id=2)
            assert phone.result(2)["state"]["rig"]["levels"]["RFPOWER"] == 0.05
            await phone.say(cmd="set_level", id=3, name="RFPOWER", value=0.3)
            assert phone.of_type("error")[-1]["code"] == "invalid_params" and fake.levels["RFPOWER"] == 0.05
    run(scenario)
