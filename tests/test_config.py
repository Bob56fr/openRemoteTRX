import pytest

from trxstation import config as c
from trxstation.setup_wizard import dummy_config, parse_audio_list, parse_rig_list


def valid() -> c.Config:
    cfg = dummy_config()
    assert c.validate(cfg) == []
    return cfg


def test_roundtrip(tmp_path):
    cfg = valid()
    cfg.rig.extra_conf = ["serial_handshake=None"]
    path = tmp_path / "station.toml"
    path.write_text(c.render_toml(cfg), encoding="utf-8")
    loaded = c.load(path)
    assert loaded == cfg


def test_real_rig_requires_port():
    cfg = valid()
    cfg.rig.model = 3073
    assert any("port" in p for p in c.validate(cfg))


def test_rigctld_must_stay_local():
    cfg = valid()
    cfg.network.rigctld_host = "0.0.0.0"
    assert any("local" in p for p in c.validate(cfg))


@pytest.mark.parametrize("field,value", [
    ("tot_s", 500),            # dépasse le plafond
    ("warn_before_s", 90),     # >= tot_s
    ("heartbeat_timeout_ms", 600),  # < 2x l'intervalle
])
def test_safety_inconsistencies_are_rejected(field, value):
    cfg = valid()
    setattr(cfg.safety, field, value)
    assert c.validate(cfg)


def test_supervisor_tot_must_exceed_gateway_ceiling():
    cfg = valid()
    cfg.supervisor.tot_abs_s = cfg.safety.tot_ceiling_s
    assert any("tot_abs_s" in p for p in c.validate(cfg))


def test_tx_allowed_and_empty_bands_block_tx():
    cfg = valid()
    assert cfg.tx_allowed(14_200_000)
    assert not cfg.tx_allowed(14_500_000)
    cfg.bands = []
    assert not cfg.tx_allowed(14_200_000)
    assert any("IMPOSSIBLE" in w for w in c.warnings(cfg))


def test_unknown_keys_are_reported():
    with pytest.raises(c.ConfigError) as exc:
        c.from_dict({"rig": {"model": 1, "typo": 3}, "oups": 1})
    assert any("typo" in p for p in exc.value.problems)
    assert any("oups" in p for p in exc.value.problems)


def test_rigctld_args():
    rig = c.Rig(model=3073, port="/dev/ttyUSB0", speed=19200, ptt_type="RTS", ptt_port="/dev/ttyUSB0")
    args = rig.rigctld_args("127.0.0.1", 4532)
    assert args[:3] == ["rigctld", "-m", "3073"]
    assert "-P" in args and "RTS" in args and "-s" in args and "19200" in args
    assert "-P" not in c.Rig(model=1).rigctld_args("127.0.0.1", 4532)


def test_parse_rig_list():
    sample = (" Rig #  Mfg                    Model                   Version         Status      Macro\n"
              "     1  Hamlib                 Dummy                   20220109.0      Stable      RIG_MODEL_DUMMY\n"
              "  3073  Icom                   IC-7300                 20211214.1      Stable      RIG_MODEL_IC7300\n")
    assert parse_rig_list(sample) == [(1, "Hamlib", "Dummy"), (3073, "Icom", "IC-7300")]


def test_parse_audio_list():
    sample = "card 1: CODEC [USB Audio CODEC], device 0: USB Audio [USB Audio]\n"
    assert parse_audio_list(sample) == [("plughw:CARD=CODEC,DEV=0", "USB Audio CODEC (carte 1)")]
