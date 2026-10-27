"""Module Cluster DX, lot 1 : analyse, plan de bande, cty.dat, cache, telnet, bascule."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from trxstation.cluster import bandplan, clusterdx, cty as ctymod, feed as feedmod, telnet
from trxstation.cluster.cache import SpotCache, SpotFilter
from trxstation.cluster.engine import Engine
from trxstation.cluster.feed import Feed, Source
from trxstation.cluster.parse import parse_dx_line
from trxstation.cluster.text import check_own_call, check_password, clean_line
from trxstation.devtools.fake_cluster import SAMPLE_SPOTS, FakeCluster

# ------------------------------------------------------------------ jeu de lignes valides (critère : 100 % lues)

VALID = [
    # (ligne, fréquence, dx, spotteur, mode, heure, skimmer)
    ("DX de F5XYZ:     14025.0  K1ABC        CW 599 tnx                     1847Z JN18",
     14025.0, "K1ABC", "F5XYZ", "CW", "1847", False),
    ("DX de DL1ABC-12:14025.0  K1ABC        up 2                           1847Z",
     14025.0, "K1ABC", "DL1ABC", None, "1847", False),
    ("DX de W3LPL:     14025.0  K1ABC        CW                             1847Z MD",
     14025.0, "K1ABC", "W3LPL", "CW", "1847", False),
    ("DX de DK8NE-#:   14025.10 OH2BH        CW    18 dB  25 WPM  CQ        1847Z",
     14025.1, "OH2BH", "DK8NE", "CW", "1847", True),
    ("DX de KM3T-2-#:  14074.0  JA1XXX       FT8   -12 dB  CQ               0003Z",
     14074.0, "JA1XXX", "KM3T", "FT8", "0003", True),
    ("DX de ea5wu:     21074.5  zs6aaa       ft8 -08                        2359Z",
     21074.5, "ZS6AAA", "EA5WU", "FT8", "2359", False),
    ("DX de G4ABC:     144300.0 F6XYZ/P      JN18AA<ES>IO91 SSB 55          1200Z",
     144300.0, "F6XYZ/P", "G4ABC", "SSB", "1200", False),
    ("DX de OH8X:      10368100.0  OZ1ABC    EME                            1200Z",
     10368100.0, "OZ1ABC", "OH8X", None, "1200", False),
    ("DX de VE7CC-1:   7004.0   3B8/F4XXX                                   0815Z",
     7004.0, "3B8/F4XXX", "VE7CC", None, "0815", False),
    ("DX de JA1ZZZ:    18100.0  VK9DX        RTTY ok                        0101Z <PM96>",
     18100.0, "VK9DX", "JA1ZZZ", "RTTY", "0101", False),
    ("DX de PA3GCV:    3790.0   EA8/DL1XX    USB tnx 1234Z test             1847Z",
     3790.0, "EA8/DL1XX", "PA3GCV", "SSB", "1847", False),
    ("DX de N1MM:      1823.5   9A1A         cq contest\x07\x07",
     None, None, None, None, None, None),          # pas d'heure : mal formée (voir ci-dessous)
]

MALFORMED = [
    "DX de N1MM:      1823.5   9A1A         cq contest",       # pas d'heure
    "DX de :     14025.0  K1ABC   CW   1847Z",                  # pas de spotteur
    "DX de F5XYZ:     abc  K1ABC   CW   1847Z",
    "DX de F5XYZ:     14025.0  K1ABC   CW   2561Z",            # heure impossible
    "DX de F5XYZ:     14025.0  ABCDEF   CW   1847Z",           # pas un indicatif
    "DX de F5XYZ:     50.0  K1ABC   CW   1847Z",               # fréquence absurde
    "DX de " + "X" * 300,
]


@pytest.mark.parametrize("line,freq,dx,spotter,mode,t,skim", [v for v in VALID if v[1] is not None])
def test_valid_lines_all_parsed(line, freq, dx, spotter, mode, t, skim):
    s = parse_dx_line(clean_line(line.encode()))
    assert s is not None, line
    assert (s.freq_khz, s.dx, s.spotter, s.mode, s.time_utc, s.skimmer) == (freq, dx, spotter, mode, t, skim)


@pytest.mark.parametrize("line", MALFORMED)
def test_malformed_lines_rejected(line):
    assert parse_dx_line(line) is None


def test_sample_spots_of_fake_cluster_all_parse():
    for line in SAMPLE_SPOTS:
        assert parse_dx_line(line.format(t="1234")) is not None, line


def test_clean_line_strips_control_and_bidi():
    raw = "DX de F5XYZ: 14025.0 K1ABC \x1b[31mCW\u202e evil\x07 1847Z".encode()
    out = clean_line(raw)
    assert "\x1b" not in out and "\u202e" not in out and "\x07" not in out
    assert clean_line(b"caf\xe9") == "café"                  # Latin-1 accepté


def test_own_call_and_password_checks():
    assert check_own_call(" f4xxx ") == "F4XXX"
    for good in ("F-80123", "14AT123", "VP2E/K1ABC/P", "SWL", "3DA0ZZ", "R1ANA"):     # aucun contrôle de forme
        assert check_own_call(good) == good
    for bad in ("", "  ", None, "F4 XXX", "F4XXX\r\nSH/DX", "F4XXX\tX", "A" * 21, "F4\x00X"):
        with pytest.raises(ValueError):
            check_own_call(bad)
    with pytest.raises(ValueError):
        check_password("abc\r\nset/spots")                   # pas d'injection de commande
    assert check_password("s3cret!") == "s3cret!"

# ------------------------------------------------------------------ plan de bande


@pytest.mark.parametrize("freq,band,mode", [
    (14025.0, "20m", "CW"), (14075.2, "20m", "FT8"), (14081.0, "20m", "FT4"), (14090.0, "20m", "DIGI"),
    (14205.0, "20m", "SSB"), (7010.0, "40m", "CW"), (7150.0, "40m", "SSB"), (10120.0, "30m", "CW"),
    (10145.0, "30m", "DIGI"), (29600.0, "10m", "FM"), (3790.0, "80m", "SSB"), (9000.0, None, None),
    (27555.0, "11m", "SSB"), (26085.0, "11m", "SSB"),
])
def test_bandplan(freq, band, mode):
    assert bandplan.band_of(freq) == band
    assert bandplan.guess_mode(freq) == mode


def test_hamlib_mode_for_future_qsy():
    assert bandplan.hamlib_mode("SSB", 7150.0) == "LSB"
    assert bandplan.hamlib_mode("SSB", 14200.0) == "USB"
    assert bandplan.hamlib_mode("FREEDV", 14236.0) == "USB"
    assert bandplan.hamlib_mode("SSB", 27555.0) == "USB"
    assert bandplan.hamlib_mode("FT8", 14074.0) is None       # numérique : jamais de QSY
    assert bandplan.hamlib_mode("WHATEVER", 14074.0) is None

# ------------------------------------------------------------------ cty.dat

CTY_SAMPLE = """\
France:                   14:  27:  EU:   46.00:    -2.00:    -1.0:  F:
    F,HW,HX,TM,=F6DXB/YL,TO0(9){NA};
Fed. Rep. of Germany:     14:  28:  EU:   51.00:   -10.00:    -1.0:  DL:
    DA,DB,DC,DD,DF,DG,DH,DJ,DK,DL,DM,DN,DO,DP,DQ,DR;
United States:            05:  08:  NA:   37.60:    91.87:     5.0:  K:
    AA,AB,K,N,W,
    K6(3)[6],=N2NL/MM(7);
Canary Islands:           33:  36:  AF:   28.32:    15.85:     0.0:  EA8:
    AM8,AN8,EA8,EB8;
Spain:                    14:  37:  EU:   40.32:     3.43:    -1.0:  EA:
    AM,AN,AO,EA,EB,EC;
Japan:                    25:  45:  AS:   36.40:  -138.38:    -9.0:  JA:
    7J,7K,JA,JR;
"""


def test_cty_parse_and_lookup():
    t = ctymod.Cty.parse(CTY_SAMPLE)
    assert len(t) == 6
    assert t.lookup("F4XXX").entity.name == "France"
    assert t.lookup("DK8NE").continent == "EU"
    assert t.lookup("K1ABC").continent == "NA"
    assert t.lookup("K6ABC").cq_zone == 3                    # zone corrigée par préfixe
    assert t.lookup("TO0ABC").continent == "NA"              # continent corrigé
    assert t.lookup("F6DXB/YL").entity.name == "France"      # indicatif exact
    assert t.lookup("EA8/DL1XX").entity.name == "Canary Islands"
    assert t.lookup("DL1XX/EA8").entity.name == "Canary Islands"
    assert t.lookup("EA8ABC").entity.name == "Canary Islands"  # préfixe le plus long
    assert t.lookup("F4XXX/P").entity.name == "France"
    assert t.lookup("K1ABC/MM") is None                      # maritime mobile
    assert t.lookup("Q1ZZZ") is None


@pytest.mark.parametrize("bad", ["France: 14: 27: XX: 0: 0: 0: F:\n    F;\n",
                                 "France:   14:  27:  EU:   46.00:    -2.00:    -1.0:  F:\n    F,HW\n",
                                 "    F;\n"])
def test_cty_rejects_broken_file(bad):
    with pytest.raises(ctymod.CtyError):
        ctymod.Cty.parse(bad)


def test_cty_missing_file_gives_empty_table(tmp_path):
    t, problem = ctymod.load_or_empty(tmp_path / "absent.dat")
    assert len(t) == 0 and "absent" in problem
    (tmp_path / "small.dat").write_text(CTY_SAMPLE)
    t, problem = ctymod.load_or_empty(tmp_path / "small.dat")
    assert len(t) == 0 and "incomplet" in problem            # moins de 300 entités : suspect


class _Resp:
    def __init__(self, data):
        self.data = data

    def read(self, n):
        return self.data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _big_cty(n=ctymod.MIN_ENTITIES):
    return "".join(f"Entity {i}:  14:  27:  EU:   0.0:   0.0:   0.0:  Q{i}:\n    Q{i}A;\n" for i in range(n))


def test_cty_download_replaces_only_after_check(tmp_path):
    path = tmp_path / "cty.dat"
    path.write_text("ancien")
    with pytest.raises(ctymod.CtyError):
        ctymod.download(path, opener=lambda u, timeout: _Resp(b"<html>erreur</html>"))
    assert path.read_text() == "ancien"                      # ancien fichier intact
    with pytest.raises(ctymod.CtyError):
        ctymod.download(path, "http://example.org/cty.dat", opener=lambda u, timeout: _Resp(b""))
    t = ctymod.download(path, opener=lambda u, timeout: _Resp(_big_cty().encode()))
    assert len(t) == ctymod.MIN_ENTITIES and path.read_text().startswith("Entity 0")
    assert not ctymod.is_stale(path)
    assert ctymod.is_stale(tmp_path / "absent")

# ------------------------------------------------------------------ cache


def _raw(line):
    s = parse_dx_line(line)
    assert s is not None
    return s


def L(freq, dx, spotter="F5XYZ", comment="CW", t="1200"):
    return f"DX de {spotter}:  {freq}  {dx}  {comment}  {t}Z"


def test_cache_dedup_counts_spotters_and_updates():
    c = SpotCache(ctymod.Cty.parse(CTY_SAMPLE))
    s, new = c.add(_raw(L(14025.0, "K1ABC")), source="a", kind="cluster", now=0)
    assert new and s.country == "United States" and s.spotter_continent == "EU"
    s2, new2 = c.add(_raw(L(14025.8, "K1ABC", spotter="DL1AA")), source="a", kind="cluster", now=30)
    assert s2 is s and not new2 and s.count == 2 and s.last_seen == 30 and s.freq_khz == 14025.8
    s3, new3 = c.add(_raw(L(14027.0, "K1ABC")), source="a", kind="cluster", now=31)
    assert new3 and len(c) == 2                              # au-delà de 1 kHz : autre spot
    c.add(_raw(L(14025.5, "K1ABC", spotter="DK8NE-#")), source="rbn", kind="rbn", now=40)
    assert s.kind == "cluster" and s.kinds == {"cluster", "rbn"}   # un humain l'a vu


def test_cache_expiry_per_source():
    c = SpotCache()
    a, _ = c.add(_raw(L(14025.0, "K1ABC")), source="a", kind="cluster", now=0)
    b, _ = c.add(_raw(L(7010.0, "K2ABC")), source="r", kind="rbn", now=0)
    assert c.expire(599) == []
    assert c.expire(600) == [b]                               # RBN : 10 min
    assert c.expire(900) == [a]                               # cluster : 15 min
    assert len(c) == 0 and c.counters["expired"] == 2


def test_cache_is_bounded_oldest_out():
    c = SpotCache(max_spots=3)
    for i in range(5):
        c.add(_raw(L(14000.0 + 10 * i, f"K{i}ABC")), source="a", kind="cluster", now=i)
    assert [s.dx for s in c.spots()] == ["K2ABC", "K3ABC", "K4ABC"]
    assert c.counters["evicted"] == 2
    c.add(_raw(L(14020.0, "K2ABC")), source="a", kind="cluster", now=9)   # rafraîchi : devient le plus récent
    c.add(_raw(L(14100.0, "K9ABC")), source="a", kind="cluster", now=10)
    assert [s.dx for s in c.spots()] == ["K4ABC", "K2ABC", "K9ABC"]


def test_cache_filters():
    t = ctymod.Cty.parse(CTY_SAMPLE)
    flt = SpotFilter(bands=frozenset({"20m"}), modes=frozenset({"SSB", "FREEDV"}),
                     continents=frozenset({"EU"}), blacklist=frozenset({"K9BAD", "SPAM*"}))
    c = SpotCache(t, flt)
    assert c.add(_raw(L(7150.0, "K1ABC")), source="a", kind="cluster", now=0) is None
    assert c.add(_raw(L(14200.0, "K1ABC", comment="CW")), source="a", kind="cluster", now=0) is None
    assert c.add(_raw(L(14200.0, "K1ABC", spotter="JA1ZZ", comment="tnx")), source="a", kind="cluster", now=0) is None
    assert c.add(_raw(L(14200.0, "K9BAD")), source="a", kind="cluster", now=0) is None
    assert c.add(_raw(L(14200.0, "K1ABC", spotter="SPAM1X")), source="a", kind="cluster", now=0) is None
    assert c.add(_raw(L(14205.0, "K1ABC", comment="tnx")), source="a", kind="cluster", now=0) is not None
    s = c.spots()[0]
    assert s.mode == "SSB" and s.mode_guessed                 # déduit du plan de bande
    assert c.add(_raw(L(14236.0, "K2ABC", comment="FreeDV 700E")), source="a", kind="cluster", now=0)
    assert c.spots()[1].mode == "FREEDV" and not c.spots()[1].mode_guessed
    for reason in ("band", "mode", "continent", "blacklist"):
        assert c.counters[f"filtered_{reason}"] >= 1
    assert c.in_range(14200, 14210) == [s] and c.in_range(14000, 14100) == []


@pytest.mark.parametrize("line", [L(14074.5, "K1ABC", comment="tnx"),          # fenêtre FT8 sans mode
                                  L(14025.0, "K1ABC", comment="FT8 -12dB"),
                                  L(14085.0, "K1ABC", comment="RTTY"),
                                  L(14090.0, "K1ABC", comment="tnx"),            # segment numérique
                                  L(7047.6, "K1ABC", comment="FT4")])
def test_digital_modes_always_dropped(line):
    c = SpotCache()                                          # même sans aucun filtre
    assert c.add(_raw(line), source="a", kind="cluster", now=0) is None
    assert c.counters["filtered_digital"] == 1


def test_digital_mode_cannot_be_selected():
    for mode in ("FT8", "FT4", "RTTY", "DIGI"):
        with pytest.raises(ValueError):
            SpotFilter(modes=frozenset({mode}))


def test_continent_filter_inoperative_without_cty():
    c = SpotCache(None, SpotFilter(continents=frozenset({"EU"})))
    assert c.add(_raw(L(14025.0, "K1ABC", spotter="JA1ZZ")), source="a", kind="cluster", now=0) is not None


def test_filter_rejects_unknown_values():
    with pytest.raises(ValueError):
        SpotFilter(bands=frozenset({"13m"}))
    with pytest.raises(ValueError):
        SpotFilter(continents=frozenset({"XX"}))


def test_engine_counts_malformed_and_other_lines():
    seen = []
    e = Engine(SpotCache(), on_spot=lambda s, new: seen.append((s.dx, new)), clock=lambda: 100.0)
    src = Source("a", "telnet", "h", 1)
    for line in ["Hello F4XXX", MALFORMED[0], L(14025.0, "K1ABC"), L(14025.2, "K1ABC", spotter="G4AAA")]:
        e.handle_line(src, line)
    c = e.counters()
    assert (c["malformed"], c["received"], c["duplicates"], c["per_minute"]) == (1, 2, 1, 2)
    assert e.other_lines == 1 and seen == [("K1ABC", True), ("K1ABC", False)]
    e.handle_line(src, L(7010.0, "K2ABC", spotter="DK8NE-#"))
    assert e.cache.in_range(7000, 7020)[0].kind == "rbn"     # skimmer sur un cluster = RBN

# ------------------------------------------------------------------ telnet contre le faux cluster


def _session(fake: FakeCluster, call="F4XXX", **kw):
    lines: list[str] = []
    stop = asyncio.Event()

    def on_line(line):
        lines.append(line)
        if sum(1 for ln in lines if ln.startswith("DX de")) >= 4:
            stop.set()

    kw.setdefault("login_silent", 2.0)
    res = asyncio.run(_run(fake, call, on_line, stop, kw))
    return res, lines


async def _run(fake, call, on_line, stop, kw):
    await fake.start()
    try:
        return await telnet.run_session("127.0.0.1", fake.port, call, on_line=on_line, stop=stop, **kw)
    finally:
        await fake.close()


def test_session_reads_spots_and_sends_only_the_call():
    fake = FakeCluster(telnet_negotiation=True)
    res, lines = _session(fake)
    assert res.code == telnet.STOPPED and res.logged_in and res.cluster_type == "dxspider"
    assert fake.received == ["F4XXX"]                         # rien d'autre que l'indicatif
    assert all(parse_dx_line(ln) for ln in lines if ln.startswith("DX de"))
    assert not any("\x07" in ln or "\xff" in ln for ln in lines)


def test_session_password_flow():
    fake = FakeCluster(password="s3cret")
    res, _ = _session(fake, password="s3cret")
    assert res.logged_in and fake.received == ["F4XXX", "s3cret"]
    res, _ = _session(FakeCluster(password="s3cret"), password="faux")
    assert res.code == telnet.PASSWORD_REFUSED and res.fatal
    fake = FakeCluster(password="s3cret")
    res, _ = _session(fake)
    assert res.code == telnet.PASSWORD_REQUIRED and fake.received == ["F4XXX"]


def test_session_call_refused():
    res, lines = _session(FakeCluster(refuse_calls=("F4XXX",)))
    assert res.code == telnet.CALL_REFUSED and res.fatal and not res.logged_in and lines == []


def test_session_server_closes_after_spots():
    res, _ = _session(FakeCluster(close_after=2))
    assert res.code == telnet.OK_CLOSED and res.logged_in and res.spots == 2


def test_session_unreachable():
    async def refuse(host, port):
        raise ConnectionRefusedError(10061, "refusé")
    res = asyncio.run(telnet.run_session("h", 1, "F4XXX", on_line=lambda _: None, open_connection=refuse))
    assert res.code == telnet.UNREACHABLE and not res.fatal


def test_session_idle_timeout():
    res, _ = _session(FakeCluster(spots=("not a spot",), interval=60), idle_timeout=1.5,
                      refusal_wait=0.3)
    assert res.code == telnet.IDLE and res.logged_in


def test_session_no_prompt_sends_call_after_silence():
    fake = FakeCluster(prompt="")
    res, _ = _session(fake, login_silent=0.5)
    assert res.logged_in and fake.received == ["F4XXX"]


def test_splitter_drops_overlong_lines():
    sp = telnet.LineSplitter(max_line=20)
    out = sp.feed(b"A" * 50 + b"\r\nshort\r\n")
    assert out == ["short"] and sp.dropped == 1
    assert sp.feed(bytes([255, 250, 24, 1, 255, 240]) + b"ok\n") == ["ok"]   # sous-négociation retirée
    assert sp.feed(b"x\xff\xffy\n") == ["xÿy"]                                  # IAC IAC = octet 255

# ------------------------------------------------------------------ bascule et délais


class Scripted:
    """Fausse session : rejoue des résultats par source."""

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []

    async def __call__(self, host, port, call, *, password, on_line, on_login, stop):
        self.calls.append(host)
        await asyncio.sleep(0)
        queue = self.script.get(host) or [telnet.SessionResult(telnet.UNREACHABLE)]
        res = queue.pop(0) if len(queue) > 1 else queue[0]
        if res.logged_in:
            on_login("dxspider")
        if len(self.calls) >= 12:
            stop.set()
        return res


def _run_feed(sources, script):
    delays = []

    async def fake_sleep(d):
        delays.append(d)

    sess = Scripted(script)
    states = []
    f = Feed(sources, "F4XXX", lambda s, l: None, session=sess, sleep=fake_sleep,
             on_state=lambda s, st: states.append((s.name, st.state)))
    asyncio.run(f.run())
    return f, sess, delays, states


def test_failover_after_three_failures_and_backoff():
    srcs = [Source("p", "telnet", "p", 1, priority=1), Source("s", "telnet", "s", 1, priority=2)]
    ok = telnet.SessionResult(telnet.OK_CLOSED, logged_in=True, spots=5)
    f, sess, delays, states = _run_feed(srcs, {"p": [telnet.SessionResult(telnet.UNREACHABLE)], "s": [ok]})
    assert sess.calls[:4] == ["p", "p", "p", "s"]
    assert delays[:3] == [10.0, 30.0, 10.0]                  # remis à zéro à la bascule
    assert ("p", feedmod.FAILED) in states
    assert all(d == 10.0 for d in delays[3:])                # connexions réussies : délai minimal


def test_backoff_caps_at_five_minutes():
    _, _, delays, _ = _run_feed([Source("p", "telnet", "p", 1)], {})
    assert delays[:6] == [10.0, 30.0, 60.0, 120.0, 300.0, 300.0]


def test_refused_call_is_never_retried():
    srcs = [Source("p", "telnet", "p", 1, priority=1), Source("s", "telnet", "s", 1, priority=2)]
    _, sess, _, states = _run_feed(srcs, {"p": [telnet.SessionResult(telnet.CALL_REFUSED)],
                                          "s": [telnet.SessionResult(telnet.OK_CLOSED, logged_in=True, spots=1)]})
    assert sess.calls.count("p") == 1 and ("p", feedmod.FAILED) in states


def test_all_sources_refused_stops_group():
    f, sess, _, _ = _run_feed([Source("p", "telnet", "p", 1)], {"p": [telnet.SessionResult(telnet.CALL_REFUSED)]})
    assert sess.calls == ["p"] and f.states["p"].state == feedmod.FAILED


def test_rbn_has_its_own_connection_and_loss_accounting():
    srcs = [Source("c", "telnet", "c", 1), Source("r", "rbn", "r", 1)]
    ok = telnet.SessionResult(telnet.OK_CLOSED, logged_in=True, spots=3)
    f, sess, _, _ = _run_feed(srcs, {"c": [ok], "r": [ok]})
    assert "c" in sess.calls and "r" in sess.calls
    st = f.streams["clusters"]
    assert st.losses >= 2 and st.recovered == st.losses - 1  # la dernière perte peut être en cours
    assert set(f.streams) == {"clusters", "r"}


def test_disabled_source_not_connected():
    _, sess, _, _ = _run_feed([Source("c", "telnet", "c", 1), Source("x", "rbn", "x", 1, enabled=False)],
                              {"c": [telnet.SessionResult(telnet.OK_CLOSED, logged_in=True, spots=1)]})
    assert "x" not in sess.calls

# ------------------------------------------------------------------ outil console et structure


CDX_PAGE = """<table class="spots" border="1" cellpadding="4" cellspacing="0"><thead><tr><th>ID</th>\
<th class="timestamp">Time</th><th class="spotter">Spotter</th><th class="freq">Freq</th>\
<th class="dxcall">DX Call</th><th class="comment">Comment</th></tr></thead><tbody>\
<tr data-id="3919063"><td>3919063</td><td class="timestamp">2026-10-27 15:47:58</td><td class="spotter">136BCS</td>\
<td class="freq">27505</td><td class="dxcall">14LG56</td><td class="comment">73 Laurent</td></tr>\
<tr data-id="3919052"><td>3919052</td><td class="timestamp">2026-10-27 15:39:54</td><td class="spotter">30AIR666</td>\
<td class="freq">27580</td><td class="dxcall">12EK060</td><td class="comment">Complimenti per l&#039;ottimo QSO</td></tr>\
<tr data-id="3919040"><td>3919040</td><td class="timestamp">2026-10-27 15:40:00</td><td class="spotter">1AT/H688</td>\
<td class="freq">27265</td><td class="dxcall">10/108AT150</td><td class="comment"></td></tr>\
<tr data-id="3918934"><td>3918934</td><td class="timestamp">2026-10-27 15:45:11</td><td class="spotter">19DCG955</td>\
<td class="freq">27265</td><td class="dxcall">165AT448</td><td class="comment">Good DX 73 Ronald FT8</td></tr>\
<tr data-id="3918900"><td>3918900</td><td class="timestamp">pas une date</td><td class="spotter">1AT014</td>\
<td class="freq">27265</td><td class="dxcall">2EK309</td><td class="comment"></td></tr>\
<tr data-id="3918800"><td>3918800</td><td class="timestamp">2026-10-27 12:00:00</td><td class="spotter">1AT014</td>\
<td class="freq">27265</td><td class="dxcall">3SD040</td><td class="comment"></td></tr>\
</tbody></table>"""
CDX_NOW = clusterdx.datetime(2026, 10, 27, 14, 48, 43, tzinfo=clusterdx.timezone.utc)   # en-tête Date relevé


def test_paris_time_to_utc():
    dt = clusterdx.datetime
    assert clusterdx.paris_to_utc(dt(2026, 10, 27, 15, 47, 58)) == dt(2026, 10, 27, 14, 47, 58, tzinfo=clusterdx.timezone.utc)
    assert clusterdx.paris_to_utc(dt(2026, 7, 1, 12, 0)).hour == 10                       # heure d'été
    assert clusterdx.paris_to_utc(dt(2026, 3, 29, 3, 30)).hour == 1                       # juste après le passage
    assert clusterdx.paris_to_utc(dt(2026, 3, 29, 1, 30)).hour == 0                       # juste avant
    assert clusterdx.paris_to_utc(dt(2026, 10, 25, 3, 30)).hour == 2                      # après le retour


def test_clusterdx_page_parsed():
    spots, bad = clusterdx.parse_page(CDX_PAGE, CDX_NOW)
    assert bad == 1                                                  # la date illisible
    first = spots[0]
    assert (first.id, first.raw.dx, first.raw.spotter, first.raw.freq_khz) == (3919063, "14LG56", "136BCS", 27505.0)
    assert 40 <= first.age_s <= 50 and first.raw.time_utc == "1447"
    assert spots[1].raw.comment == "Complimenti per l'ottimo QSO"   # entité HTML décodée
    assert spots[2].raw.dx == "10/108AT150" and spots[2].raw.spotter == "1AT/H688"
    assert spots[3].raw.mode == "FT8"


@pytest.mark.parametrize("page", ["<html><body>Maintenance</body></html>",
                                  '<table class="spots"><tr data-id="1"><td>1</td><td class="x">?</td></tr></table>'])
def test_clusterdx_changed_page_is_an_error(page):
    with pytest.raises(clusterdx.FormatError):
        clusterdx.parse_page(page, CDX_NOW)


def test_clusterdx_fetch_is_bounded_and_https_only():
    class Resp(_Resp):
        headers = {"Date": "Tue, 27 Oct 2026 14:48:43 GMT"}
    page, now = clusterdx.fetch(opener=lambda req, timeout: Resp(CDX_PAGE.encode()))
    assert now == CDX_NOW and "14LG56" in page
    with pytest.raises(clusterdx.FormatError):
        clusterdx.fetch(opener=lambda req, timeout: Resp(b"x" * (clusterdx.MAX_BYTES + 5)))
    with pytest.raises(ValueError):
        clusterdx.fetch("http://clusterdx.org/spots.php")


def test_cb_spots_in_cache_without_country_or_continent_filter():
    seen = []
    t = ctymod.Cty.parse(CTY_SAMPLE)
    e = Engine(SpotCache(t, SpotFilter(continents=frozenset({"EU"}))), on_spot=lambda s, n: seen.append(s),
               clock=lambda: 10_000.0)
    spots, bad = clusterdx.parse_page(CDX_PAGE, CDX_NOW)
    e.handle_web(Source("clusterdx", "web", url=clusterdx.URL), spots, bad)
    assert [s.dx for s in seen] == ["14LG56", "12EK060", "10/108AT150"]   # FT8 écarté, 2 h trop vieux
    assert all(s.kind == "cb" and s.country is None and s.band == "11m" and s.mode == "SSB" for s in seen)
    assert seen[0].last_seen == pytest.approx(10_000.0 - 45, abs=6)        # âge réel conservé
    c = e.counters()
    assert (c["malformed"], e.cache.counters["too_old"], e.cache.counters["filtered_digital"]) == (1, 1, 1)


def test_web_feed_polls_once_a_minute_and_only_new_ids():
    pages = [CDX_PAGE, OSError("réseau"), CDX_PAGE.replace("3919063", "3919070"), CDX_PAGE]
    calls, delays, batches = [], [], []

    def fetch(url):
        calls.append(url)
        item = pages[min(len(calls), len(pages)) - 1]
        if isinstance(item, Exception):
            raise item
        return item, CDX_NOW

    async def go():
        f = None

        async def fake_sleep(d):
            delays.append(d)
            if len(calls) >= 4:
                f.stop()

        f = Feed([Source("clusterdx", "web", url=clusterdx.URL)], "", lambda s, l: None, fetch=fetch,
                 sleep=fake_sleep, on_web=lambda s, spots, bad: batches.append([w.id for w in spots]),
                 poll_s=1.0)
        await f.run()
        return f
    f = asyncio.run(go())
    assert delays == [60.0, 10.0, 60.0, 60.0]               # 1 relevé/min au plus ; échec : 10 s
    assert batches[0] == sorted(batches[0]) and len(batches[0]) == 5
    assert batches[1] == [3919070]                           # seulement le nouveau numéro
    st = f.streams["clusterdx"]
    assert (st.losses, st.recovered) == (1, 1)


def test_cli_web_only_needs_no_call(monkeypatch):
    from trxstation.cluster import cli
    ran = {}

    async def fake_run(args, call, sources):
        ran.update(call=call, kinds=[s.kind for s in sources])
        return 0
    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["--connu", "clusterdx"]) == 0 and ran == {"call": "", "kinds": ["web"]}
    assert cli.main(["--cb"]) == 2                           # avec les clusters par défaut : indicatif exigé
    assert cli.main(["--indicatif", "F4XXX", "--cb", "--connu", "clusterdx"]) == 0
    assert ran["kinds"] == ["web"]                           # pas de doublon


def test_known_servers_have_no_digital_feed():
    from trxstation.cluster.servers import KNOWN
    assert all(k.port != 7001 for k in KNOWN)
    assert any(k.kind == "web" and k.url == clusterdx.URL for k in KNOWN)


def test_cli_requires_own_call(capsys):
    from trxstation.cluster import cli
    assert cli.main(["--duree", "1"]) == 2
    assert "indicatif vide" in capsys.readouterr().err


def test_cli_end_to_end_with_fake_cluster(capsys, tmp_path):
    from trxstation.cluster import cli

    async def go():
        fake = FakeCluster(interval=0.01)
        await fake.start()
        args = cli.argparse.Namespace(source=[("127.0.0.1", fake.port)], connu=None, rbn=False, cb=False,
                                      mot_de_passe=False, bandes=None, modes=["CW"], continent=None,
                                      liste_noire=None, duree_vie=15.0, duree_vie_rbn=10.0, duree=0.5,
                                      cty=str(tmp_path / "absent.dat"), maj_cty=False, tout=False)
        orig = asyncio.wait

        async def short_wait(fs, timeout=None, **kw):           # cycle d'état de 60 s ramené à 1 s
            return await orig(fs, timeout=min(timeout or 1, 1.0), **kw)
        cli.asyncio.wait = short_wait
        try:
            return await cli.run(args, "F4XXX", cli.build_sources(args))
        finally:
            cli.asyncio.wait = orig
            await fake.close()
    assert asyncio.run(go()) == 0
    out = capsys.readouterr().out
    assert "K1ABC" in out and "VK2XYZ" not in out             # filtre de mode CW
    assert "RÉSULTAT : aucune coupure non rattrapée" in out


def test_cluster_package_never_touches_the_rig():
    """Lot 1 : aucun accès au poste, à rigctld, au PTT ni au bus des modules."""
    root = Path(__file__).resolve().parents[1] / "trxstation" / "cluster"
    forbidden = re.compile(r"rigctl|ptt|PttController|gateway|modules\.bus|serial", re.I)
    for path in root.glob("*.py"):
        code = "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines()
                         if not ln.lstrip().startswith("#"))
        imports = [ln for ln in code.splitlines() if ln.lstrip().startswith(("import ", "from "))]
        assert not any(forbidden.search(ln) for ln in imports), path.name


def test_only_writes_are_call_and_password():
    """Les seuls `send(` de la session telnet portent sur l'indicatif et le mot de passe."""
    src = (Path(__file__).resolve().parents[1] / "trxstation" / "cluster" / "telnet.py").read_text(encoding="utf-8")
    sends = re.findall(r"\bsend\(([^)]*)\)", src)
    assert sorted(sends) == ["call", "password", "text: str"]
    assert src.count("writer.write(") == 1
