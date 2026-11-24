# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
import json

from trxstation.dashboard import view
from trxstation.dashboard.station import JournalTail, StationReader, heat_history


class Mono:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def status(seq=1, **over):
    st = {
        "pid": 42, "seq": seq, "written_at": 0, "schema": 1,
        "ptt": {"state": "RX", "owner": None, "tot_remaining_s": None, "temp_c": 36.0},
        "rig": {"connected": True, "frequency_hz": 14195000, "mode": "USB", "passband_hz": 2400, "strength_db": -12,
                "ptt": False, "functions": {"NR": True, "NB": False, "TUNER": True, "ANF": True, "RIT": True},
                "levels": {"PREAMP": 10, "ATT": 0, "AGC": 3, "RFPOWER": 0.5, "NR": 0.33, "VD_METER": 13.8},
                "split": False, "tx_frequency_hz": None, "offsets": {"RIT": 120}, "vfo": "VFOA", "power": "on"},
        "presence": {"listeners": 2, "connections": [
            {"id": "c1", "pseudo": "S25", "role": "operator"},
            {"id": "c2", "pseudo": "PC", "role": "operator"},
            {"id": "c3", "pseudo": "Visiteur 1", "role": "listener"}]},
    }
    for k, v in over.items():
        st[k].update(v)
    return st


def reader(tmp_path, mono, tot=90):
    (tmp_path / "station.toml").write_text(
        f"[safety]\ntot_s = {tot}\n\n"
        '[[clients]]\nid = "S25"\npassword_hash = "SECRET"\n\n'
        '[[clients]]\nid = "Thierry"\nrole = "listener"\npseudo = "Satanas"\n\n'
        '[[clients]]\nid = "tablette"\npseudo = "BOB"\n', encoding="utf-8")
    return StationReader(tmp_path / "gateway-status.json", tmp_path, tmp_path / "station.toml",
                         rig_name="IC-7300MK2", clock=mono)


def write(tmp_path, st):
    (tmp_path / "gateway-status.json").write_text(json.dumps(st), encoding="utf-8")


def test_reception(tmp_path):
    mono = Mono()
    r = reader(tmp_path, mono)
    write(tmp_path, status())
    v = view.merge(view.vitals_template(), r.read())
    assert v["station"]["ok"] and not v["safe"]["active"]
    rig = v["rig"]
    assert rig["freq_hz"] == 14195000 and rig["notch"] == "auto" and rig["rit_hz"] == 120
    assert rig["preamp"] == "10 dB" and __import__("trxstation.dashboard.station").dashboard.station.preamp_text(2.0) == "P2" and rig["agc"] == "LENTE" and rig["nr_level"] == "5"
    assert rig["power_set_w"] == 50 and rig["vd_v"] == 13.8 and rig["temp_c"] == 36.0
    assert rig["vox"] is None                       # absent de la passerelle : pastille masquée
    assert [o["id"] for o in v["operators"]] == ["c1", "c2"] and [o["name"] for o in v["operators"]] == ["S25", "PC"] and v["visitors"] == 2


def test_stale_by_seq_not_by_clock(tmp_path):
    mono = Mono()
    r = reader(tmp_path, mono)
    write(tmp_path, status(seq=1))
    assert r.read()["station"]["ok"]
    mono.t += 3                                      # même seq 3 s plus tard : passerelle muette
    assert not r.read()["station"]["ok"]
    write(tmp_path, status(seq=2))
    assert r.read()["station"]["ok"]


def test_tx_elapsed_from_tot(tmp_path):
    mono = Mono()
    r = reader(tmp_path, mono, tot=90)
    write(tmp_path, status(ptt={"state": "TX", "owner": "c1", "tot_remaining_s": 43},
                           rig={"levels": {"RFPOWER_METER": 0.48, "SWR": 1.2, "ALC": 0.32}}))
    v = view.merge(view.vitals_template(), r.read())
    assert v["ptt"]["tx"] and v["ptt"]["elapsed_s"] == 47 and v["ptt"]["tot_s"] == 90 and v["ptt"]["warn_s"] == 80
    assert v["ptt"]["owner"] == "S25"
    assert v["operators"][0] == {"id": "c1", "name": "S25", "tx": True}
    assert round(v["rig"]["po_w"]) == 48 and round(v["rig"]["alc_pct"]) == 32


def test_safe_mode_and_unknown_schema(tmp_path):
    mono = Mono()
    r = reader(tmp_path, mono)
    (tmp_path / "safe_mode").write_text("TX sans client\n", encoding="utf-8")
    write(tmp_path, status() | {"schema": 2})
    v = r.read()
    assert v["safe"] == {"active": True, "reason": "TX sans client"}
    assert not v["station"]["ok"] and "rig" not in v


def test_cat_lost_keeps_last_frequency(tmp_path):
    mono = Mono()
    r = reader(tmp_path, mono)
    write(tmp_path, status(seq=1))
    r.read()
    write(tmp_path, status(seq=2, rig={"connected": False, "frequency_hz": None}))
    mono.t += 1
    r.read()
    mono.t += 30
    write(tmp_path, status(seq=3, rig={"connected": False, "frequency_hz": None}))
    rig = r.read()["rig"]
    assert rig["connected"] is False and rig["last_freq_hz"] == 14195000 and round(rig["lost_s"]) == 30


def test_sdr(tmp_path):
    mono = Mono()
    r = reader(tmp_path, mono)
    r.wall = lambda: 1000.0
    (tmp_path / "sdr").mkdir()
    (tmp_path / "sdr/status.json").write_text(json.dumps(
        {"state": "running", "driver": "sdrplay", "serial": "SECRET", "dfreq": 7074000, "mode": "USB", "fs": 2e6,
         "cpu": 18, "t": 995.0}), encoding="utf-8")
    s = r.read()["sdr"]
    assert s["present"] and s["model"] == "SDRplay" and s["rate"] == "2 MS/s" and "SECRET" not in json.dumps(s)
    r.wall = lambda: 1100.0
    assert r.read()["sdr"]["present"] is False


def test_journal(tmp_path):
    lines = [
        {"ts": "2026-11-24T10:00:00Z", "niveau": "WARNING", "message": "xruns", "code": "ORT-3010", "gravite": "avertissement"},
        {"ts": "2026-11-24T10:01:00Z", "niveau": "INFO", "message": "rien"},
        {"ts": "2026-11-24T10:02:00Z", "niveau": "ERROR", "message": "ALERTE température"},
    ]
    path = tmp_path / "journal-superviseur.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    j = JournalTail(tmp_path)
    got = j.initial(0)
    assert [a["level"] for a in got] == ["warn", "crit"]
    assert j.new() == []
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-11-24T10:05:00Z", "gravite": "critique", "message": "x", "code": "ORT-1"}) + "\n")
    assert [a["level"] for a in j.new()] == ["crit"]
    with open(path, "a", encoding="utf-8") as f:          # répétition dans le même quart d'heure : même clé
        for m in range(3):
            f.write(json.dumps({"ts": f"2026-11-24T10:0{6 + m}:00Z", "gravite": "critique", "message": "x", "code": "ORT-1"}) + "\n")
    assert len({a["key"] for a in j.new()}) == 1


def test_heat_history(tmp_path):
    (tmp_path / "chauffe.jsonl").write_text(
        json.dumps({"ts": "2026-11-24T10:00:00Z", "temp_c": 51.5, "cpu_pct": 22}) + "\nabîmé\n", encoding="utf-8")
    rows = heat_history(tmp_path, 0)
    assert rows == [{"t": rows[0]["t"], "cpu": 22, "temp": 51.5}]


def test_accounts_from_station_toml(tmp_path):
    """Terminaux = comptes opérateurs de station.toml, visiteurs exclus, sans jamais garder un mot de passe."""
    r = reader(tmp_path, Mono())
    assert r.accounts == [{"id": "S25", "pseudo": None}, {"id": "tablette", "pseudo": "BOB"}]
    assert "SECRET" not in json.dumps(r.accounts)
