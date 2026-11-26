# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Écran partagé de TRX Console (étape 403, docs/protocole-ecran.md) : calculs, envoi, lecture, menu 6.7.

Le faux relais reprend les règles de `ScreenApi.php` (dépôt openRemoteTRX-relay) ; l'essai contre le vrai relais est
`tests/e2e_screen.py` de ce dépôt-là.
"""
from __future__ import annotations

import hashlib
import io
import os
import sys

import pytest

from trxstation.screenshare import calc
from trxstation.screenshare.relay import RelayRefused, RelayUnavailable
from trxstation.screenshare.share import Uploader
from trxstation.screenshare.view import Viewer, run_view

CODE = "7K3MQ-P9X2D"


class FakeScreenRelay:
    """Mêmes réponses que le relais PHP (routes open, put, get, close), en mémoire."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.frames: list[dict] = []
        self.down = False
        self.now = 0
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def call(self, route: str, f: dict) -> dict:
        if self.down:
            raise RelayUnavailable("coupé")
        a = f["a"]
        s = self.sessions.get(a)
        if route == "open":
            if s is not None:
                if s["h"] != f["h"]:
                    raise RelayRefused(409, "exists")
                return {"ok": True, "expires": s["expires"], "resumed": True}
            self.sessions[a] = {"h": f["h"], "last_seq": 0, "refresh": False, "ended": False, "watch": -99,
                                "expires": self.now + 7200}
            return {"ok": True, "expires": self.now + 7200, "resumed": False}
        if s is None:
            raise RelayRefused(404, "unknown_session")
        if route in ("put", "close"):
            if hashlib.sha256(calc.b64d(f["w"], 32)).hexdigest() != s["h"]:
                raise RelayRefused(403, "forbidden")
            if route == "close":
                s["ended"] = True
                self.frames = [x for x in self.frames if x["a"] != a]
                return {"ok": True}
            if s["ended"] or self.now >= s["expires"]:
                raise RelayRefused(410, "ended")
            if f["s"] <= s["last_seq"]:
                raise RelayRefused(409, "sequence", reply={"last": s["last_seq"]})
            s["last_seq"] = f["s"]
            self.frames.append({"id": len(self.frames) + 1, "a": a, "s": f["s"], "d": f["d"]})
            refresh, s["refresh"] = s["refresh"], False
            return {"ok": True, "watching": self.now - s["watch"] <= 10, "refresh": refresh, "expires": s["expires"]}
        if route == "get":
            if s["ended"] or self.now >= s["expires"]:
                return {"ok": True, "frames": [], "more": False, "ended": True,
                        "reason": "closed" if s["ended"] else "expired"}
            s["watch"] = self.now
            if f.get("refresh"):
                s["refresh"] = True
            out = [{"id": x["id"], "s": x["s"], "d": x["d"]} for x in self.frames
                   if x["a"] == a and x["id"] > f["after"]]
            return {"ok": True, "frames": out, "more": False, "ended": False, "last_put": 0}
        raise AssertionError(route)


def _t(key: str, **fields) -> str:
    return key + (" " + " ".join(f"{k}={v}" for k, v in sorted(fields.items())) if fields else "")


@pytest.fixture(scope="module")
def keys() -> calc.ScreenKeys:
    return calc.derive(CODE)


# ------------------------------------------------------------------ calculs
def test_code_gives_address_key_and_write_token_independent_of_the_monitoring(keys):
    assert calc.derive("7k3mq p9x2d") == keys                 # casse, espaces et tirets libres
    assert len(keys.address) == 32 and len(keys.key) == 32 and len(keys.write) == 32
    assert len({keys.address, keys.key.hex(), keys.write.hex()}) == 3
    assert keys.write_hash == hashlib.sha256(keys.write).hexdigest()
    from trxstation.monlink.invite import derive as mon_derive
    assert mon_derive(CODE).address != keys.address           # autre sel que le code du monitoring
    # Valeur figée : un changement de la dérivation casserait l'aidant d'une autre version.
    assert keys.address == hashlib.scrypt(b"7K3MQP9X2D", salt=b"orx-screen v1", n=2**15, r=8, p=1,
                                          maxmem=64 * 1024 * 1024, dklen=80)[:16].hex()
    with pytest.raises(calc.InviteRefused):
        calc.derive("trop court")


def test_frames_round_trip_and_cannot_be_moved_or_forged(keys):
    box = calc.seal_frame(keys, 7, calc.KIND_OUTPUT, 120, 40, b"\x1b[1mbonjour\x1b[0m")
    frame = calc.open_frame(keys, 7, box)
    assert frame == calc.Frame(calc.KIND_OUTPUT, 120, 40, b"\x1b[1mbonjour\x1b[0m")
    with pytest.raises(calc.FrameRefused) as err:
        calc.open_frame(keys, 8, box)                         # numéro changé par le relais
    assert err.value.reason == "decrypt"
    with pytest.raises(calc.FrameRefused):
        calc.open_frame(calc.derive("AAAAA-AAAAA"), 7, box)   # autre code
    with pytest.raises(calc.FrameRefused) as err:
        calc.open_frame(keys, 7, "!!")
    assert err.value.reason == "malformed"
    big = calc.seal_frame(keys, 1, calc.KIND_KEYFRAME, 80, 24, os.urandom(calc.MAX_DATA))
    assert len(big) <= calc.MAX_BOX
    with pytest.raises(ValueError):
        calc.seal_frame(keys, 1, calc.KIND_OUTPUT, 80, 24, b"x" * (calc.MAX_DATA + 1))


def test_tape_keeps_the_screen_since_the_last_full_clear():
    tape = calc.Tape(keep=100)
    tape.feed(b"vieux texte\r\n")
    tape.feed(b"\x1b[?1049h\x1b[2Jmenu")
    assert tape.alt is True
    assert tape.keyframe() == b"\x1b[?1049h" + calc.RESET + b"\x1b[2Jmenu"
    tape.feed(b"\x1b[?10")                                    # séquence coupée entre deux lectures
    tape.feed(b"49l fin")
    assert tape.alt is False
    tape.feed(b"".join(b"ligne %d\n" % i for i in range(50)))
    assert len(tape.buf) <= 100 and tape.buf.startswith(b"ligne ")
    tape.feed(b"\x1bcpropre")
    assert bytes(tape.buf) == b"\x1bcpropre"


# ------------------------------------------------------------------ envoi et lecture
def test_operator_screen_reaches_the_helper_who_joins_late(keys):
    relay = FakeScreenRelay()
    relay.call("open", {"a": keys.address, "h": keys.write_hash})
    up = Uploader(relay, keys, clock=lambda: relay.now)
    up.resize(100, 30)
    up.feed(b"\x1b[2JTRX Console\r\n")
    up.step()                                                 # premier envoi : écran complet
    up.feed(b"menu 1\r\n")
    up.step()
    viewer = Viewer(relay, keys)                              # l'aidant arrive après coup
    out = viewer.poll()
    assert b"".join(out).endswith(b"\x1b[2JTRX Console\r\nmenu 1\r\n")
    assert (viewer.cols, viewer.rows) == (100, 30)
    up.feed(b"choix 2\r\n")
    up.step()
    assert up.watching is True
    assert viewer.poll() == [b"choix 2\r\n"]


def test_helper_asks_for_a_full_screen_after_lost_frames(keys):
    relay = FakeScreenRelay()
    relay.call("open", {"a": keys.address, "h": keys.write_hash})
    up = Uploader(relay, keys, clock=lambda: relay.now)
    up.feed(b"\x1b[2Jdebut ")
    up.step()
    viewer = Viewer(relay, keys)
    viewer.poll()
    up.feed(b"perdu ")
    up.step()
    relay.frames = [x for x in relay.frames if x["s"] != 2]  # image effacée par le relais (10 min, 4 Mo)
    up.feed(b"suite ")
    up.step()
    assert viewer.poll() == [] and viewer.synced is False    # trou : rien d'appliqué
    assert viewer.poll() == []                                # relevé suivant : écran complet demandé
    relay.now += 3
    up.step()                                                 # battement : le relais transmet la demande
    assert up.nudge.is_set()
    up.step()
    assert b"".join(viewer.poll()).endswith(b"\x1b[2Jdebut perdu suite ")


def test_relay_outage_resumes_with_a_full_screen_and_the_end_stops_sharing(keys):
    relay = FakeScreenRelay()
    relay.call("open", {"a": keys.address, "h": keys.write_hash})
    up = Uploader(relay, keys, clock=lambda: relay.now)
    up.feed(b"\x1b[2Ja")
    up.step()
    relay.down = True
    up.feed(b"b")
    up.step()
    assert up.state == "interrupted" and up.sharing
    relay.down = False
    up.step()
    assert up.state == "ok"
    viewer = Viewer(relay, keys)
    assert b"".join(viewer.poll()).endswith(b"\x1b[2Jab")
    relay.now += 7200                                         # 2 h : le relais refuse
    up.feed(b"c")
    up.step()
    assert (up.state, up.stop_reason, up.sharing) == ("stopped", "ended", False)
    viewer.poll()
    assert viewer.ended == "expired"


def test_stopping_closes_the_session_and_the_helper_is_told(keys):
    relay = FakeScreenRelay()
    relay.call("open", {"a": keys.address, "h": keys.write_hash})
    up = Uploader(relay, keys, clock=lambda: relay.now)
    up.feed(b"x")
    up.step()
    up.stop("you")
    assert relay.sessions[keys.address]["ended"] and relay.frames == []
    up.feed(b"plus rien")
    up.step()
    assert relay.frames == []
    viewer = Viewer(relay, keys)
    viewer.poll()
    assert viewer.ended == "closed"


def test_helper_cannot_write_without_the_token(keys):
    relay = FakeScreenRelay()
    relay.call("open", {"a": keys.address, "h": keys.write_hash})
    with pytest.raises(RelayRefused) as err:
        relay.call("put", {"a": keys.address, "w": calc.b64e(b"\0" * 32), "s": 1, "d": "AAAA"})
    assert err.value.reason == "forbidden"


def test_run_view_shows_the_screen_then_the_end(keys):
    relay = FakeScreenRelay()
    relay.call("open", {"a": keys.address, "h": keys.write_hash})
    up = Uploader(relay, keys, clock=lambda: relay.now)
    up.feed(b"\x1b[2Jecran de l'ami")
    up.step()
    up.stop("you", close=False)
    calls = {"n": 0}
    real = relay.call

    def call(route, f):                                       # l'ami arrête au 2e relevé
        if route == "get":
            calls["n"] += 1
            if calls["n"] == 2:
                relay.sessions[keys.address]["ended"] = True
        return real(route, f)
    relay.call = call
    out = io.BytesIO()
    assert run_view(CODE, t=_t, relay_url="https://relais.invalid", relay=relay, out=out) == 0
    text = out.getvalue()
    assert b"ecran de l'ami" in text and b"screen_view.ended.closed" in text
    assert text.index(b"ecran de l'ami") < text.rindex(b"\x1b[?1049l")    # terminal remis à la fin
    assert relay.closed


def test_run_view_unknown_code_and_bad_code():
    out = io.BytesIO()
    assert run_view(CODE, t=_t, relay_url="https://relais.invalid", relay=FakeScreenRelay(), out=out) == 1
    assert b"screen_view.unknown" in out.getvalue()
    out = io.BytesIO()
    assert run_view("xx", t=_t, relay_url="https://relais.invalid", relay=FakeScreenRelay(), out=out) == 1
    assert b"screen_view.bad_code" in out.getvalue()


# ------------------------------------------------------------------ menu 6.7
def _console(tmp_path, answers):
    from trxstation.console import Console
    said: list[str] = []
    it = iter(answers)
    con = Console(tmp_path / "station.toml", ask=lambda _q: next(it, ""), say=said.append, lang="fr",
                  home=tmp_path, desktop=lambda: tmp_path)
    return con, said


def test_menu_refuses_outside_a_real_terminal(tmp_path):
    con, said = _console(tmp_path, [])
    con.screen_share()
    assert said == [con.t("screen_share.terminal_only")]


def test_menu_shares_or_views(tmp_path, monkeypatch):
    import trxstation.console as module
    con, said = _console(tmp_path, ["1", "2", "abcde-fghjk"])
    con.tty = True
    shared, viewed = [], []
    monkeypatch.setattr(con, "share_screen", lambda argv: shared.append(argv) or 0)
    monkeypatch.setattr(con, "view_screen", lambda code: viewed.append(code) or 0)
    monkeypatch.delenv(module.SCREEN_SHARED_ENV, raising=False)
    monkeypatch.setattr(module, "IS_WINDOWS", False)
    con.screen_share()
    assert shared and shared[0][1:4] == ["-m", "trxstation.console", "--config"]
    con.screen_share()
    assert viewed == ["abcde-fghjk"]
    monkeypatch.setattr(module, "IS_WINDOWS", True)
    con, said = _console(tmp_path, ["1"])
    con.tty = True
    con.screen_share()
    assert said[-1] == con.t("screen_share.linux_only")
    monkeypatch.setattr(module, "IS_WINDOWS", False)
    monkeypatch.setenv(module.SCREEN_SHARED_ENV, "1")
    con, said = _console(tmp_path, ["1"])
    con.tty = True
    con.screen_share()
    assert said[-1] == con.t("screen_share.already")
    assert con.t("head.screen_shared") in con.header()


def test_relay_of_the_station_or_rf_diy(tmp_path, monkeypatch):
    from trxstation.config import PRESENCE_DEFAULT_RELAY
    monkeypatch.delenv("TRX_SCREEN_RELAY", raising=False)
    con, _ = _console(tmp_path, [])
    assert con.screen_relay_url() == PRESENCE_DEFAULT_RELAY    # station pas encore configurée
    monkeypatch.setenv("TRX_SCREEN_RELAY", "http://127.0.0.1:9")
    assert con.screen_relay_url() == "http://127.0.0.1:9"


# ------------------------------------------------------------------ partage complet (Linux)
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="pseudo-terminal : Linux seulement")
def test_run_share_relays_the_child_console_screen(keys, monkeypatch):
    import pty
    from trxstation.screenshare import share
    monkeypatch.delenv(share.ENV_SHARED, raising=False)
    monkeypatch.setattr(share.calc, "new_code", lambda: CODE.replace("-", ""))
    relay = FakeScreenRelay()
    puts: list[dict] = []
    real = relay.call
    relay.call = lambda route, f: (puts.append(f) if route == "put" else None) or real(route, f)
    master, slave = pty.openpty()                             # le « terminal » de l'opérateur
    child = [sys.executable, "-c", "import os,time; print('bonjour', os.environ.get('TRX_SCREEN_SHARED')); "
                                   "time.sleep(0.8)"]
    code = share.run_share(child, t=_t, relay_url="https://relais.invalid", stdin=slave, stdout=slave,
                           ask_start=False, relay=relay)
    os.close(slave)
    seen = b""
    while True:
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
    os.close(master)
    sent = b"".join(calc.open_frame(keys, f["s"], f["d"]).data for f in puts)   # le relais efface à la fin
    assert code == 0, seen
    assert b"bonjour 1" in seen and b"screen_share.started" in seen and b"7K3MQ-P9X2D" in seen, seen
    assert b"bonjour 1" in sent, sent
    assert relay.sessions[keys.address]["ended"] is True      # session fermée à la fin de la console
