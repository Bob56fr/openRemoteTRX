# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Présence de groupe, lot 1 : calculs purs (docs/presence-cahier-des-charges.md, docs/protocole-presence.md)."""
from __future__ import annotations

import ast
import json
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trxstation.presence import crypto, invite, pow as pw, roster as ro, state as st, status as stt, vectors, wire
from trxstation.presence.codec import Malformed, b64d, b64e, cjson
from trxstation.presence.identity import Identity, load_key_file, save_key_file, station_id_of

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "protocol" / "presence_vectors.json"
NOW = vectors.NOW
TZ = timezone(timedelta(hours=1))
IDS = vectors.identities()
ADMIN, MEMBER, OTHER = IDS["admin"], IDS["member"], IDS["other"]
KEY = vectors.GROUP_KEY
GROUP = vectors.GROUP


# ------------------------------------------------------------------ primitives
def test_hchacha20_and_xchacha20_poly1305_match_the_published_vectors():
    """draft-irtf-cfrg-xchacha-03 § 2.2.1 et A.3.1 (valeurs recopiées du document, indépendantes du code)."""
    out = crypto.hchacha20(bytes(range(32)), bytes.fromhex("000000090000004a0000000031415927"))
    assert out.hex() == "82413b4227b27bfed30e42508a877d73a0f9e4d58a74a853c12ec41326d3ecdc"
    ct = crypto.xchacha_encrypt(bytes(range(0x80, 0xA0)), bytes(range(0x40, 0x58)), vectors.SUNSCREEN.encode(),
                                bytes.fromhex("50515253c0c1c2c3c4c5c6c7"))
    assert ct[:32].hex() == "bd6d179d3e83d43b9576579493c0e939572a1700252bfaccbed2902c21396cbb"
    assert ct[-16:].hex() == "c0875924c1c7987947deafd8780acf49"
    assert crypto.xchacha_decrypt(bytes(range(0x80, 0xA0)), bytes(range(0x40, 0x58)), ct,
                                  bytes.fromhex("50515253c0c1c2c3c4c5c6c7")) == vectors.SUNSCREEN.encode()
    with pytest.raises(crypto.DecryptError):
        crypto.xchacha_decrypt(bytes(range(0x80, 0xA0)), bytes(range(0x40, 0x58)), ct, b"autre")


def test_seal_opens_only_for_its_recipient_and_its_context():
    box = crypto.seal(KEY, MEMBER.x_pub, b"ctx")
    assert crypto.unseal(box, MEMBER.x_seed, b"ctx") == KEY
    with pytest.raises(crypto.DecryptError):
        crypto.unseal(box, OTHER.x_seed, b"ctx")
    with pytest.raises(crypto.DecryptError):
        crypto.unseal(box, MEMBER.x_seed, b"autre")
    with pytest.raises(crypto.DecryptError):
        crypto.seal(KEY, bytes(32), b"ctx")              # point de petit ordre


def test_base64url_refuses_padding_foreign_characters_and_non_canonical_forms():
    assert b64d(b64e(b"\x00\xff\x10")) == b"\x00\xff\x10"
    for bad in ("AA==", "A+/", "A", "AB", 3):            # "AB" : bits de fin non nuls
        with pytest.raises(Malformed):
            b64d(bad)
    with pytest.raises(Malformed):
        b64d(b64e(b"12"), 3)


def test_station_id_is_the_fingerprint_and_the_key_file_round_trips(tmp_path):
    ident = Identity.generate()
    assert ident.station_id == station_id_of(ident.ed_pub) and len(ident.station_id) == 32
    assert ident.station_id != station_id_of(OTHER.ed_pub)
    path = tmp_path / "presence.key"
    save_key_file(path, ident)
    assert load_key_file(path) == ident
    assert ident.station_id in repr(ident) and b64e(ident.ed_seed) not in repr(ident)
    with pytest.raises(Malformed):
        Identity.from_text('{"format": 2, "ed": "", "x": ""}')


def test_proof_of_work():
    sid = ADMIN.station_id
    nonce = pw.pow_solve(sid, 10)
    assert pw.pow_ok(sid, nonce, 10) and pw.leading_zero_bits(pw.pow_hash(sid, nonce)) >= 10
    assert not pw.pow_ok(OTHER.station_id, nonce, 30)
    assert not pw.pow_ok(sid, -1, 0) and not pw.pow_ok(sid, True, 0) and not pw.pow_ok(sid, 2**53, 0)
    assert pw.leading_zero_bits(bytes(32)) == 256 and pw.leading_zero_bits(b"\x01") == 7


# ------------------------------------------------------------------ requêtes au relais
def test_signed_request_and_every_refusal():
    body, headers = wire.build_request(ADMIN, "/v1/sync", {"states": []}, t=NOW, n=5)
    assert headers["X-Orx-Station"] == ADMIN.station_id
    sig = headers["X-Orx-Signature"]
    assert wire.verify_request(ADMIN.ed_pub, "/v1/sync", body, sig, now=NOW, last_n=4)["n"] == 5
    cases = [(OTHER.ed_pub, "/v1/sync", body, sig, NOW, 0, "bad_signature"),
             (ADMIN.ed_pub, "/v1/register", body, sig, NOW, 0, "bad_signature"),     # autre chemin
             (ADMIN.ed_pub, "/v1/sync", body, "AAAA", NOW, 0, "bad_signature"),
             (ADMIN.ed_pub, "/v1/sync", body, sig, NOW + 601, 0, "clock"),
             (ADMIN.ed_pub, "/v1/sync", body, sig, NOW, 5, "replay"),
             (ADMIN.ed_pub, "/v1/sync", b"x" * (wire.MAX_BODY + 1), sig, NOW, 0, "too_large")]
    for pub, path, b, s, now, last, reason in cases:
        with pytest.raises(wire.RequestRefused) as err:
            wire.verify_request(pub, path, b, s, now=now, last_n=last)
        assert err.value.reason == reason
    unsigned_t, _ = wire.build_request(ADMIN, "/v1/sync", {}, t=NOW, n=1)
    body2 = unsigned_t.replace(b'"n":1', b'"n":true')
    sig2 = b64e(ADMIN.sign(wire.signed_bytes("/v1/sync", body2)))
    with pytest.raises(wire.RequestRefused) as err:
        wire.verify_request(ADMIN.ed_pub, "/v1/sync", body2, sig2, now=NOW, last_n=0)
    assert err.value.reason == "malformed"


def test_counter_always_grows_even_if_the_clock_goes_back():
    clock = iter([100.0, 100.0, 50.0, 200.0])
    c = wire.Counter(clock=lambda: next(clock))
    values = [c.next() for _ in range(4)]
    assert values == [100000, 100001, 100002, 200000]


def test_filters():
    assert wire.mode_ok("PKTUSB") and not wire.mode_ok("usb") and not wire.mode_ok("A" * 13)
    assert wire.freq_ok(14_205_000) and not wire.freq_ok(True) and not wire.freq_ok(99_999) and not wire.freq_ok(1.5)
    assert wire.clean_text(None) is None and wire.clean_pseudo(12) is None


# ------------------------------------------------------------------ statut
def _tracker(**kw) -> stt.StatusTracker:
    return stt.StatusTracker(started=NOW - 86400, tz=TZ, **kw)


def test_qso_lasts_ten_minutes_after_the_last_transmission_and_keeps_its_start():
    t = _tracker()
    t.tx(True, NOW)
    assert t.status(NOW + 30) == stt.Status("Q", NOW, NOW + 30, None)
    t.tx(False, NOW + 60)
    t.tx(True, NOW + 400)                     # reprise d'antenne : même QSO
    t.tx(False, NOW + 460)
    s = t.status(NOW + 460 + 599)
    assert s.code == "Q" and s.since == NOW and s.last_tx == NOW + 460
    s = t.status(NOW + 460 + 600)
    assert s.code == "A" and s.since == NOW + 460 + 600
    t.tx(True, NOW + 5000)
    assert t.status(NOW + 5001).since == NOW + 5000      # nouveau QSO


def test_rx_lasts_five_minutes_after_the_last_action_and_follows_a_qso():
    t = _tracker()
    t.activity(NOW)
    t.activity(NOW + 200)
    assert t.status(NOW + 499) == stt.Status("R", NOW, None, None)
    assert t.status(NOW + 500) == stt.Status("A", NOW + 500, None, None)
    t2 = _tracker()
    t2.tx(True, NOW)
    t2.tx(False, NOW + 10)
    t2.activity(NOW + 550)
    assert t2.status(NOW + 620) == stt.Status("R", NOW + 610, NOW + 10, None)   # R commence à la fin du QSO


def _ts(y, mo, d, h, mi) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


def test_shack_rules_once_suspension_and_return_after_activity():
    wed_13 = _ts(2026, 11, 11, 13, 0)                 # mercredi
    rule = stt.ShackRule(frozenset({2}), "12:00", "14:00")
    t = _tracker(rules=[rule])
    assert t.status(wed_13) == stt.Status("S", _ts(2026, 11, 11, 12, 0), None, _ts(2026, 11, 11, 14, 0))
    s = t.status(_ts(2026, 11, 11, 15, 0))
    assert s.code == "A" and s.since == _ts(2026, 11, 11, 14, 0)
    t.activity(wed_13)
    assert t.status(wed_13 + 60).code == "R"
    assert t.status(wed_13 + 300) == stt.Status("S", wed_13 + 300, None, _ts(2026, 11, 11, 14, 0))
    t.suspended_until = _ts(2026, 11, 20, 0, 0)
    assert t.status(wed_13 + 400).code == "A"
    night = _tracker(rules=[stt.ShackRule(frozenset({4}), "22:00", "01:00")])   # vendredi, minuit franchi
    assert night.status(_ts(2026, 11, 14, 0, 30)).code == "S"
    assert night.status(_ts(2026, 11, 14, 1, 0)).code == "A"
    once = _tracker()
    once.shack_for(NOW, 7200)
    assert once.status(NOW + 7199).shack_until == NOW + 7200
    once.shack_cancel()
    assert once.status(NOW + 10).code == "A"
    with pytest.raises(ValueError):
        stt.ShackRule(frozenset({7}), "12:00", "14:00")
    with pytest.raises(ValueError):
        stt.ShackRule(frozenset({1}), "12:00", "12:00")


def test_display_sort_and_age():
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    for case in data["display"]:
        assert stt.display_code(case["st"], case["age"]) == case["out"]
    for case in data["format_age"]:
        assert stt.format_age(case["s"]) == case["out"]
    names = sorted([("A", "zed"), ("O", "alpha"), ("Q", "Bob"), ("R", "amy"), ("Q", "al")],
                   key=lambda c: stt.sort_key(*c))
    assert names == [("Q", "al"), ("Q", "Bob"), ("R", "amy"), ("A", "zed"), ("O", "alpha")]


# ------------------------------------------------------------------ état
STATUS = stt.Status("R", NOW - 120, NOW - 900, None)


def _seal(ident, content, *, group=GROUP, key=KEY, kv=1):
    return st.seal_state(ident, group, key, kv, content)


def _open(blob, *, station=MEMBER.station_id, ed=MEMBER.ed_pub, group=GROUP, key=KEY, kv=1, last_n=0, now=NOW):
    return st.open_state(blob, group=group, station=station, ed_pub=ed, key=key, key_version=kv, last_n=last_n,
                         now=now)


def test_state_round_trip_and_fixed_size_whatever_the_level():
    sizes = set()
    for share, extra in ((st.Share("f"), {"f": 14_205_000, "m": "USB"}), (st.Share("o"), {}),
                         (st.Share("x", "Test antenne"), {"x": "Test antenne"}), (st.Share(invisible=True), {})):
        c = st.content(STATUS, share, n=7, t=NOW, freq=14_205_000, mode="USB")
        blob = _seal(MEMBER, c)
        sizes.add(len(blob))
        got = _open(blob)
        assert got["n"] == 7 and all(got[k] == v for k, v in extra.items())
        assert ("f" in got) == (share.level == "f" and not share.invisible)
    assert len(sizes) == 1 and len(b64d(blob)) == st.BLOB_SIZE


def test_state_content_rules():
    absent = stt.Status("A", NOW - 3000, None, None)
    assert "sd" not in st.content(absent, st.Share("o", hide_absence=True), n=1, t=NOW, freq=None, mode=None)
    assert "sd" in st.content(STATUS, st.Share("o", hide_absence=True), n=1, t=NOW, freq=None, mode=None)
    unknown_mode = st.content(STATUS, st.Share("f"), n=1, t=NOW, freq=14_205_000, mode=None)
    assert unknown_mode["lv"] == "o" and "f" not in unknown_mode
    assert st.content(STATUS, st.Share(invisible=True), n=1, t=NOW, freq=1, mode="USB") == \
        {"v": 1, "n": 1, "t": NOW, "st": "H"}
    with pytest.raises(ValueError):
        st.Share("x", "café")
    with pytest.raises(ValueError):
        st.seal_state(MEMBER, GROUP, KEY, 1, {"v": 1, "pad": "x" * 200})


def test_a_member_cannot_forge_the_state_of_another_member():
    """OTHER connaît la clé du groupe mais signe avec SA clé : refusé comme état de MEMBER."""
    c = st.content(STATUS, st.Share("f"), n=9, t=NOW, freq=27_555_000, mode="FM")
    head = st.header(GROUP, MEMBER.station_id, 1)
    body = cjson(c)
    plain = struct.pack(">H", len(body)) + body + OTHER.sign(head + body)
    plain += bytes(st.PLAIN_SIZE - len(plain))
    nonce = crypto.random_nonce()
    forged = b64e(nonce + crypto.xchacha_encrypt(KEY, nonce, plain, head))
    with pytest.raises(st.StateRefused) as err:
        _open(forged)
    assert err.value.reason == "signature"


def test_state_refusals():
    blob = _seal(MEMBER, st.content(STATUS, st.Share("o"), n=9, t=NOW, freq=None, mode=None))
    cases = [(dict(key=bytes(32)), "decrypt"), (dict(group="ff" * 16), "decrypt"),
             (dict(station=OTHER.station_id, ed=OTHER.ed_pub), "decrypt"), (dict(kv=2), "decrypt"),
             (dict(last_n=9), "replay"), (dict(now=NOW - 601), "future")]
    for kw, reason in cases:
        with pytest.raises(st.StateRefused) as err:
            _open(blob, **kw)
        assert err.value.reason == reason, kw
    raw = bytearray(b64d(blob))
    raw[40] ^= 1
    with pytest.raises(st.StateRefused) as err:
        _open(b64e(bytes(raw)))
    assert err.value.reason == "decrypt"
    with pytest.raises(st.StateRefused) as err:
        _open(blob[:-4])
    assert err.value.reason == "size"
    bad = _seal(MEMBER, {"v": 1, "n": 3, "t": NOW, "st": "R", "lv": "f", "f": 14_205_000, "m": "usb"})
    with pytest.raises(st.StateRefused) as err:
        _open(bad)
    assert err.value.reason == "malformed"
    extra = _seal(MEMBER, {"v": 1, "n": 3, "t": NOW, "st": "H", "f": 14_205_000})
    with pytest.raises(st.StateRefused) as err:
        _open(extra)
    assert err.value.reason == "malformed"


# ------------------------------------------------------------------ liste des membres
def _first() -> ro.Roster:
    return vectors.first_roster(IDS)


def _m(ident, role, joined=NOW - 10):
    return ro.new_member(ident.ed_pub, ident.x_pub, role, joined)


def test_first_roster_is_accepted_only_from_the_invitation_admin():
    env = ro.sign(_first(), ADMIN)
    assert ro.accept_first(env, group=GROUP, admin=ADMIN.station_id) == _first()
    for kw, reason in ((dict(group="ff" * 16, admin=ADMIN.station_id), "group"),
                       (dict(group=GROUP, admin=MEMBER.station_id), "signer")):
        with pytest.raises(ro.RosterRefused) as err:
            ro.accept_first(env, **kw)
        assert err.value.reason == reason
    with pytest.raises(ro.RosterRefused) as err:          # signée par un simple membre
        ro.accept_first(ro.sign(_first(), MEMBER), group=GROUP, admin=MEMBER.station_id)
    assert err.value.reason == "signer"


def test_the_relay_cannot_slip_its_own_key_into_a_roster():
    env = ro.sign(_first(), ADMIN)
    obj = json.loads(b64d(env["p"]))
    obj["m"].append(_m(OTHER, "m").as_json())
    obj["m"].sort(key=lambda m: m["id"])
    tampered = dict(env, p=b64e(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()))
    with pytest.raises(ro.RosterRefused) as err:
        ro.accept_first(tampered, group=GROUP, admin=ADMIN.station_id)
    assert err.value.reason == "signature"
    spaced = dict(env, p=b64e(b64d(env["p"]).replace(b",", b", ", 1)))
    with pytest.raises(ro.RosterRefused) as err:
        ro.accept_first(spaced, group=GROUP, admin=ADMIN.station_id)
    assert err.value.reason == "malformed"


def test_roster_transitions():
    old = _first()
    a, m = old.member(ADMIN.station_id), old.member(MEMBER.station_id)
    add = old.next(t=NOW, members=[a, m, _m(OTHER, "m")])
    assert ro.accept_next(old, ro.sign(add, ADMIN), admin_last_seen=NOW, now=NOW) == add

    def refused(new, signer, reason, **kw):
        with pytest.raises(ro.RosterRefused) as err:
            ro.accept_next(old, ro.sign(new, signer), admin_last_seen=kw.get("seen", NOW), now=NOW)
        assert err.value.reason == reason

    refused(old.next(t=NOW, members=[a]), ADMIN, "rotation_missing")                 # exclusion sans nouvelle clé
    assert ro.accept_next(old, ro.sign(old.next(t=NOW, members=[a], kv=2), ADMIN), admin_last_seen=NOW, now=NOW)
    refused(old.next(t=NOW, members=[a, m], kv=0), ADMIN, "malformed")
    rotated = ro.accept_next(old, ro.sign(old.next(t=NOW, members=[a, m], kv=2), ADMIN), admin_last_seen=NOW, now=NOW)
    with pytest.raises(ro.RosterRefused) as err:                                     # la clé ne recule jamais
        ro.accept_next(rotated, ro.sign(rotated.next(t=NOW, members=[a, m], kv=1), ADMIN), admin_last_seen=NOW, now=NOW)
    assert err.value.reason == "rotation_missing"
    refused(add, MEMBER, "signer")
    refused(add, OTHER, "signer")
    changed = ro.Member(m.id, m.ed, OTHER.x_pub, "m", m.joined)
    refused(old.next(t=NOW, members=[a, changed]), ADMIN, "key_changed")
    refused(old.next(t=NOW, members=[ro.Member(a.id, a.ed, a.x, "m", a.joined), m]), ADMIN, "no_admin")
    refused(ro.Roster(GROUP, 3, old.digest(), NOW, 1, (a, m)), ADMIN, "version")
    refused(ro.Roster(GROUP, 2, "0" * 64, NOW, 1, (a, m)), ADMIN, "chain")
    refused(ro.Roster("ff" * 16, 2, old.digest(), NOW, 1, (a, m)), ADMIN, "group")


def test_co_admin_rights_and_takeover_after_90_days():
    base = _first()
    a, m = base.member(ADMIN.station_id), base.member(MEMBER.station_id)
    co = ro.Member(m.id, m.ed, m.x, "c", m.joined)
    old = ro.accept_next(base, ro.sign(base.next(t=NOW, members=[a, co]), ADMIN), admin_last_seen=NOW, now=NOW)
    add = old.next(t=NOW, members=[a, co, _m(OTHER, "m")])
    assert ro.accept_next(old, ro.sign(add, MEMBER), admin_last_seen=NOW, now=NOW) == add       # invite : permis
    demote = old.next(t=NOW, members=[ro.Member(a.id, a.ed, a.x, "m", a.joined), ro.Member(m.id, m.ed, m.x, "a", m.joined)])
    with pytest.raises(ro.RosterRefused) as err:
        ro.accept_next(old, ro.sign(demote, MEMBER), admin_last_seen=NOW - ro.TAKEOVER_S + 1, now=NOW)
    assert err.value.reason == "admin_rights"
    assert ro.accept_next(old, ro.sign(demote, MEMBER), admin_last_seen=NOW - ro.TAKEOVER_S, now=NOW) == demote


def test_roster_jump_needs_a_known_admin():
    old = _first()
    a, m = old.member(ADMIN.station_id), old.member(MEMBER.station_id)
    v2 = old.next(t=NOW, members=[a, m, _m(OTHER, "m")])
    v3 = v2.next(t=NOW, members=[a, m, _m(OTHER, "m")])
    assert ro.accept_jump(old, ro.sign(v3, ADMIN), admin_last_seen=NOW, now=NOW) == v3
    for signer, reason in ((MEMBER, "signer"), (OTHER, "signer")):
        with pytest.raises(ro.RosterRefused) as err:
            ro.accept_jump(old, ro.sign(v3, signer), admin_last_seen=NOW, now=NOW)
        assert err.value.reason == reason
    with pytest.raises(ro.RosterRefused) as err:
        ro.accept_jump(old, ro.sign(v2, ADMIN), admin_last_seen=NOW, now=NOW)     # la suivante : pas un saut
    assert err.value.reason == "version"
    got, refused = ro.follow(old, [ro.sign(v3, MEMBER), ro.sign(v2, ADMIN), ro.sign(v3, ADMIN)], group=GROUP,
                             invite_admin=None, admin_last_seen=NOW, now=NOW)
    assert got == v3 and refused == ["signer"]


def test_roster_size_limit():
    members = [ro.new_member(Identity(bytes([i]) * 32, bytes([i]) * 32).ed_pub, bytes(32), "a" if i == 1 else "m", NOW)
               for i in range(1, ro.MAX_MEMBERS + 2)]
    big = ro.Roster(GROUP, 1, "", NOW, 1, tuple(members))
    with pytest.raises(ro.RosterRefused) as err:
        ro.accept_first(ro.sign(big, Identity(bytes([1]) * 32, bytes([1]) * 32)), group=GROUP,
                        admin=members[0].id)
    assert err.value.reason == "malformed"


# ------------------------------------------------------------------ invitation, adhésion, clé
def _inv(**kw):
    return invite.new_invitation(vectors.RELAY, GROUP, KEY, 1, ADMIN.station_id, now=NOW, token=vectors.TOKEN, **kw)


def test_invitation_round_trip_code_only_expiry_and_relay_mismatch():
    inv = _inv()
    url = inv.to_url()
    assert invite.parse_invitation(url, now=NOW) == inv
    assert invite.parse_invitation(url.split("#")[1], now=NOW) == inv
    for text, now, reason in ((url, inv.expires, "expired"), ("https://evil.example/i#" + url.split("#")[1], NOW,
                              "relay_mismatch"), (url[:-3], NOW, "malformed"), ("x" * 2000, NOW, "malformed")):
        with pytest.raises(invite.InviteRefused) as err:
            invite.parse_invitation(text, now=now)
        assert err.value.reason == reason
    with pytest.raises(ValueError):
        invite.new_invitation("http://api.rf-diy.com", GROUP, KEY, 1, ADMIN.station_id, now=NOW)


def test_join_is_checked_by_the_admin_and_the_relay_cannot_forge_it():
    inv = _inv()
    tokens = {inv.token: inv.expires}
    req = invite.join_request(inv, OTHER, "F4XYZ")
    joiner = invite.check_join(req, group=GROUP, key=KEY, tokens=tokens, used=set(), now=NOW)
    assert joiner.id == OTHER.station_id and joiner.x == OTHER.x_pub

    def refused(r, reason, **kw):
        with pytest.raises(invite.InviteRefused) as err:
            invite.check_join(r, group=GROUP, key=KEY, tokens=kw.get("tokens", tokens), used=kw.get("used", set()),
                              now=kw.get("now", NOW))
        assert err.value.reason == reason

    refused(req, "token_used", used={inv.token})
    refused(req, "token_unknown", tokens={})
    refused(req, "expired", now=inv.expires)
    relay = Identity(bytes([0x99]) * 32, bytes([0x98]) * 32)       # le relais a vu le jeton, pas la clé du groupe
    stolen = dict(req, id=relay.station_id, ed=b64e(relay.ed_pub), x=b64e(relay.x_pub))
    refused(stolen, "proof")
    refused(dict(req, x=b64e(relay.x_pub)), "proof")                # clé de chiffrement remplacée en route
    refused(dict(req, id=MEMBER.station_id), "malformed")
    refused(dict(req, g="ff" * 16), "group")
    with pytest.raises(ValueError):
        invite.join_request(inv, OTHER, "<script>")


def test_key_box_opens_only_for_the_member_from_an_admin_of_the_signed_roster():
    roster = _first()
    box = invite.key_box(ADMIN, roster, MEMBER.station_id, KEY)
    assert invite.open_key_box(box, MEMBER, roster) == KEY
    cases = [(box, OTHER, roster, "group"),
             (invite.key_box(MEMBER, roster, MEMBER.station_id, KEY), MEMBER, roster, "signer"),
             (dict(box, kv=2), MEMBER, roster, "version"),
             (dict(box, box=b64e(crypto.seal(bytes(32), MEMBER.x_pub, b"x"))), MEMBER, roster, "signature")]
    for env, who, r, reason in cases:
        with pytest.raises(invite.InviteRefused) as err:
            invite.open_key_box(env, who, r)
        assert err.value.reason == reason
    with pytest.raises(ValueError):
        invite.key_box(ADMIN, roster, OTHER.station_id, KEY)


# ------------------------------------------------------------------ vecteurs partagés et isolement
def test_shared_vectors_are_up_to_date():
    """Le fichier relu par le relais est exactement celui que fabrique le code (sinon :
    python -m trxstation.presence.vectors)."""
    assert VECTORS.read_text(encoding="utf-8") == vectors.render()


def test_shared_vectors_check_as_the_relay_does():
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    for ident in data["identities"]:
        assert station_id_of(b64d(ident["ed_pub"], 32)) == ident["station_id"]
        assert crypto.ed_public(b64d(ident["ed_seed"], 32)) == b64d(ident["ed_pub"])
    p = data["pow"]
    assert pw.pow_ok(p["station_id"], p["valid"]["nonce"], p["bits"])
    assert not pw.pow_ok(p["station_id"], p["invalid"]["nonce"], p["bits"])
    r = data["requests"]
    pub, sig = b64d(r["ed_pub"], 32), r["headers"]["X-Orx-Signature"]
    for case in r["valid"]:
        wire.verify_request(pub, r["path"], r["body"].encode(), sig, now=case["now"], last_n=case["last_n"])
    for case in r["refused"]:
        with pytest.raises(wire.RequestRefused) as err:
            wire.verify_request(pub, r["path"], case["body"].encode(), sig, now=case["now"], last_n=case["last_n"])
        assert err.value.reason == case["reason"], case["name"]
    for case in data["pseudo"]:
        assert wire.clean_pseudo(case["in"]) == case["out"]
    for case in data["text"]:
        assert wire.clean_text(case["in"]) == case["out"]
    s = data["state"]
    got = st.open_state(s["blob"], group=s["group"], station=s["station_id"], ed_pub=MEMBER.ed_pub,
                        key=b64d(s["key"]), key_version=s["kv"], now=data["now"])
    assert {k: v for k, v in s["content"].items() if k != "v"} == got
    roster = ro.accept_first(data["roster"]["envelope"], group=GROUP, admin=ADMIN.station_id)
    assert roster.digest() == data["roster"]["digest"]
    assert invite.open_key_box(data["key_box"], MEMBER, roster) == KEY
    inv = invite.parse_invitation(data["invitation"]["url"], now=data["now"])
    assert invite.check_join(data["join"], group=GROUP, key=inv.key, tokens={inv.token: inv.expires}, used=set(),
                             now=data["now"]).id == OTHER.station_id


def test_presence_package_never_touches_the_ptt_nor_the_cat():
    """La présence ne fait que montrer : son paquet n'importe ni la sécurité d'émission, ni le CAT, ni la passerelle ;
    seul service.py importe le CLIENT du bus (droits = manifeste, aucune commande) ; personne n'appelle `.command(`."""
    forbidden = ("safety", "cat", "rigctl", "ptt", "gateway")
    for path in (ROOT / "trxstation" / "presence").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Attribute) and node.attr in ("command", "client_message"):
                raise AssertionError(f"{path.name} : appel .{node.attr} interdit au module de présence")
            for name in names:
                assert not any(part in forbidden for part in name.split(".")), f"{path.name} importe {name}"
                if "modules" in name.split("."):
                    assert path.name == "service.py" and name.endswith("modules.client"), f"{path.name} importe {name}"
