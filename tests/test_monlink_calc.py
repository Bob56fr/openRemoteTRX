# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Monitoring inter-stations, lot R1 : calculs purs (docs/cdc-monitoring.md § 17, docs/protocole-monlink.md)."""
from __future__ import annotations

import ast
import json
import zlib
from pathlib import Path

import pytest

from trxstation.monlink import envelope as env, invite, pairing, profiles as pr, redact, vectors, wire
from trxstation.monlink.identity import Identity, load_key_file, save_key_file, station_id_of
from trxstation.presence import crypto
from trxstation.presence.codec import b64d, b64e, cjson
from trxstation.presence.identity import station_id_of as presence_id_of
from trxstation.presence.wire import RequestRefused

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "protocol" / "monlink_vectors.json"
NOW = vectors.NOW
IDS = vectors.identities()
HELPER, AIDED, OTHER = IDS["helper"], IDS["aided"], IDS["other"]
CODE = invite.new_code(vectors.CODE_RAND)
KEYS = invite.derive(CODE)                     # scrypt : calculé une fois pour tout le fichier


# ------------------------------------------------------------------ identité
def test_identity_is_separate_from_the_presence_and_the_key_file_round_trips(tmp_path):
    assert station_id_of(AIDED.ed_pub) == AIDED.station_id
    assert AIDED.station_id != presence_id_of(AIDED.ed_pub)          # même clé, identifiants sans lien
    path = tmp_path / "monlink.key"
    save_key_file(path, AIDED)
    assert load_key_file(path) == AIDED
    assert "ed_seed" not in repr(AIDED) and b64e(AIDED.ed_seed) not in repr(AIDED)


# ------------------------------------------------------------------ code d'invitation
def test_code_alphabet_typing_tolerance_and_refusals():
    assert len(CODE) == 10 and all(c in invite.ALPHABET for c in CODE)
    assert invite.normalize_code(invite.display_code(CODE).lower()) == CODE
    assert invite.normalize_code(" " + CODE[:3] + " " + CODE[3:] + "\t") == CODE
    assert invite.normalize_code("O1IL0-ABCDE") == "01110ABCDE"                  # O = 0, I et L = 1
    for bad in ("ABCDE-FGHJ", "ABCDE-FGHJKM", "ABCDE-FGHJU", 12345, None, "x" * 50):
        with pytest.raises(invite.InviteRefused):
            invite.normalize_code(bad)
    assert len({invite.new_code() for _ in range(50)}) == 50


def test_code_derivation_is_stable_and_splits_address_from_key():
    again = invite.derive(invite.display_code(CODE).lower())
    assert again == KEYS and len(KEYS.address) == 32 and len(KEYS.key) == 32
    assert KEYS.key.hex() not in repr(KEYS)


def test_invitation_round_trip_wrong_code_tampering_and_expiry():
    dep = invite.seal_invitation(HELPER, "Dev 56", KEYS, now=NOW)
    assert dep["a"] == KEYS.address and dep["e"] == NOW + invite.INVITE_TTL_S
    assert HELPER.station_id not in json.dumps(dep)                    # le relais ne voit pas qui invite
    inv = invite.open_invitation(KEYS, dep["box"], now=NOW + 60)
    assert (inv.id, inv.ed, inv.x, inv.pseudo) == (HELPER.station_id, HELPER.ed_pub, HELPER.x_pub, "Dev 56")
    wrong = invite.CodeKeys(KEYS.address, bytes(32))
    with pytest.raises(invite.InviteRefused, match="decrypt"):
        invite.open_invitation(wrong, dep["box"], now=NOW)
    box = bytearray(b64d(dep["box"]))
    box[-1] ^= 1
    with pytest.raises(invite.InviteRefused, match="decrypt"):
        invite.open_invitation(KEYS, b64e(bytes(box)), now=NOW)
    with pytest.raises(invite.InviteRefused, match="expired"):
        invite.open_invitation(KEYS, dep["box"], now=dep["e"])
    with pytest.raises(invite.InviteRefused, match="malformed"):
        invite.open_invitation(KEYS, "pas du base64 !", now=NOW)
    with pytest.raises(ValueError):
        invite.seal_invitation(HELPER, "Dev 56", KEYS, now=NOW, ttl_s=3600)      # 15 min au plus


# ------------------------------------------------------------------ appairage
def _pending(expires: int = NOW + 900) -> dict:
    return {KEYS.address: pairing.PendingInvite(KEYS, expires)}


def _request(**kw) -> dict:
    inv = invite.open_invitation(KEYS, invite.seal_invitation(HELPER, "Dev 56", KEYS, now=NOW)["box"], now=NOW)
    return pairing.pair_request(inv, KEYS, kw.pop("ident", AIDED), kw.pop("pseudo", "F4XYZ"), now=NOW + 10, **kw)


def test_pairing_accepted_and_both_sides_show_the_same_fingerprint():
    peer = pairing.check_pair(_request(), HELPER, _pending(), now=NOW + 20)
    assert (peer.id, peer.ed, peer.x, peer.pseudo) == (AIDED.station_id, AIDED.ed_pub, AIDED.x_pub, "F4XYZ")
    fp = pairing.fingerprint(HELPER.ed_pub, AIDED.ed_pub)
    assert fp == pairing.fingerprint(AIDED.ed_pub, HELPER.ed_pub)
    assert len(fp) == 7 and fp[3] == " " and fp.replace(" ", "").isdigit()
    assert fp != pairing.fingerprint(HELPER.ed_pub, OTHER.ed_pub)


def test_pairing_refusals():
    def reason(req, *, pending=None, now=NOW + 20, ident=HELPER):
        with pytest.raises(pairing.PairRefused) as err:
            pairing.check_pair(req, ident, _pending() if pending is None else pending, now=now)
        return err.value.reason

    good = _request()
    assert reason(good, pending={}) == "unknown_invite"
    assert reason(good, pending=_pending(expires=NOW + 5)) == "expired"
    assert reason(good, now=NOW + 10 + pairing.PAIR_MAX_AGE_S + 1) == "expired"
    assert reason(good, ident=OTHER) == "malformed"                       # pas pour elle
    assert reason({**good, "s": b64e(OTHER.sign(b"x"))}) == "signature"
    assert reason({**good, "box": good["box"][:-4] + "AAAA"}) in ("decrypt", "malformed")
    assert reason({**good, "extra": 1}) == "malformed"
    assert reason("pas un objet") == "malformed"
    # Quelqu'un qui a l'adresse (le relais) mais pas le code : sa preuve est fausse.
    inv = invite.Inviter(HELPER.station_id, HELPER.ed_pub, HELPER.x_pub, "Dev 56", NOW + 900)
    forged = pairing.pair_request(inv, invite.CodeKeys(KEYS.address, bytes(32)), OTHER, "Intrus", now=NOW + 10)
    assert reason(forged) == "proof"
    with pytest.raises(pairing.PairRefused, match="self"):
        pairing.pair_request(inv, KEYS, HELPER, "Dev 56", now=NOW)


def test_the_relay_cannot_swap_the_sender_without_being_seen():
    """Le relais remplace `from` par une autre station : l'identifiant sous le sceau ne correspond plus."""
    good = _request()
    with pytest.raises(pairing.PairRefused):
        pairing.check_pair({**good, "from": OTHER.station_id}, HELPER, _pending(), now=NOW + 20)


def test_link_key_is_the_same_on_both_sides_and_differs_per_link():
    k1 = pairing.link_key(AIDED, HELPER.station_id, HELPER.x_pub)
    assert k1 == pairing.link_key(HELPER, AIDED.station_id, AIDED.x_pub)
    assert k1 != pairing.link_key(AIDED, OTHER.station_id, OTHER.x_pub)
    with pytest.raises(ValueError):
        pairing.link_key(AIDED, AIDED.station_id, AIDED.x_pub)


# ------------------------------------------------------------------ messages
KEY = pairing.link_key(AIDED, HELPER.station_id, HELPER.x_pub)
A, H = AIDED.station_id, HELPER.station_id


def test_message_round_trip_and_direction():
    m = env.seal_message(KEY, A, H, "ev", 7, {"code": "ORT-2104", "ctx": {"n": 3}})
    assert "ORT-2104" not in json.dumps(m)                                # le relais ne lit rien
    assert env.open_message(KEY, m, me=H, peer=A, peer_is_emitter=True) == ("ev", 7, {"code": "ORT-2104",
                                                                                      "ctx": {"n": 3}})
    with pytest.raises(env.MessageRefused, match="direction"):            # la station aidée ne reçoit pas d'« ev »
        env.open_message(KEY, env.seal_message(KEY, H, A, "ev", 1, {}), me=A, peer=H, peer_is_emitter=False)
    rq = env.seal_message(KEY, H, A, "rq", 1, {"assist": 7200})
    assert env.open_message(KEY, rq, me=A, peer=H, peer_is_emitter=False)[0] == "rq"
    with pytest.raises(ValueError):
        env.seal_message(KEY, A, H, "shell", 1, {})


def test_message_tampering_is_refused():
    m = env.seal_message(KEY, A, H, "hb", 5, {"up": 1})
    for change, reason in (({"k": "st"}, "decrypt"), ({"q": 6}, "decrypt"), ({"f": OTHER.station_id}, "malformed"),
                           ({"q": 0}, "malformed"), ({"k": "zz"}, "kind"), ({"b": "AAAA"}, "malformed")):
        with pytest.raises(env.MessageRefused) as err:
            env.open_message(KEY, {**m, **change}, me=H, peer=A, peer_is_emitter=True)
        assert err.value.reason == reason, change
    other_key = pairing.link_key(OTHER, H, HELPER.x_pub)
    with pytest.raises(env.MessageRefused, match="decrypt"):
        env.open_message(other_key, m, me=H, peer=A, peer_is_emitter=True)


def test_zlib_bomb_and_size_limits():
    bomb = zlib.compress(b'{"a":"' + b"x" * (env.MAX_PLAIN + 10) + b'"}', 9)
    nonce = crypto.random_nonce()
    box = nonce + crypto.xchacha_encrypt(KEY, nonce, bomb, env._aad(A, H, "lg", 1))
    with pytest.raises(env.MessageRefused, match="too_large"):
        env.open_message(KEY, {"f": A, "to": H, "k": "lg", "q": 1, "b": b64e(box)}, me=H, peer=A,
                         peer_is_emitter=True)
    import os
    with pytest.raises(ValueError):                                       # incompressible : > 64 ko
        env.seal_message(KEY, A, H, "lg", 1, {"d": b64e(os.urandom(60_000))})


def test_replay_window():
    w = env.ReplayWindow()
    for seq in (1, 2, 5, 3):
        w.accept(seq)
    for seq in (1, 5, 0, -1):
        assert not w.check(seq)
    w.accept(4)
    w.accept(3000)
    assert not w.check(3000 - env.WINDOW)                                 # trop vieux
    w.accept(3000 - env.WINDOW + 1)                                       # en retard mais dans la fenêtre
    with pytest.raises(env.MessageRefused, match="replay"):
        w.accept(3000 - env.WINDOW + 1)
    again = env.ReplayWindow.from_dict(json.loads(json.dumps(w.to_dict())))
    assert (again.top, again.bits) == (w.top, w.bits)
    assert env.ReplayWindow.from_dict({"top": "x"}).top == 0
    w.accept(10**6)                                                       # grand saut : fenêtre remise à 1 bit
    assert w.bits == 1


def test_snapshot_fragments_any_order_and_integrity():
    import os
    data = os.urandom(env.SNAP_CHUNK * 3 + 100)
    frags = env.split_snapshot(data, "s1")
    assert len(frags) == 4
    for f in frags:                                                       # chaque fragment tient dans une enveloppe
        env.seal_message(KEY, A, H, "sn", 1, f)
    r = env.Reassembler()
    assert [r.add(f) for f in reversed(frags[1:])] == [None, None, None]
    assert r.add(frags[0]) == data
    bad = env.Reassembler()
    for f in frags[:-1]:
        bad.add(f)
    with pytest.raises(env.MessageRefused):
        bad.add({**frags[-1], "d": b64e(b"autre")})
    with pytest.raises(ValueError):
        env.split_snapshot(b"x" * (env.SNAP_MAX + 1), "s2")
    with pytest.raises(env.MessageRefused):
        env.Reassembler().add({**frags[0], "n": 1000})


# ------------------------------------------------------------------ profils
def test_profiles_defaults_presets_and_refusals():
    p = pr.Profile()
    assert p.freq_mode is False and p.events_min == "avertissement" and p.period_s == 300
    assert pr.Profile.from_dict(p.to_dict()) == p
    assert pr.PRESETS["essentiel"].events_min == "erreur"
    for bad in ({"period_s": 10}, {"period_s": True}, {"events_min": "debug"}, {"freq_mode": "oui"},
                {"shell": True}, "x"):
        with pytest.raises(pr.ProfileRefused):
            pr.Profile.from_dict(bad)


def test_assistance_is_bounded_and_returns_to_the_profile():
    p = pr.PRESETS["essentiel"]
    until = pr.assist_until(NOW, pr.ASSIST_DEFAULT_S)
    e = pr.effective(p, until, NOW + 60)
    assert e.assistance and e.period_s == 30 and e.events_min == "info" and e.logs_every_s == 120
    assert e.freq_mode is False                                           # l'assistance n'ouvre pas la fréquence
    back = pr.effective(p, until, until)
    assert not back.assistance and back.period_s == 300 and back.events_min == "erreur" and back.logs_every_s is None
    for bad in (60, 25 * 3600, True):
        with pytest.raises(pr.ProfileRefused):
            pr.assist_until(NOW, bad)


def test_rig_state_and_severity_filters():
    rig = {"cat": "ok", "tx": False, "freq": 7_074_000, "mode": "PKTUSB", "refusals": 2}
    e = pr.effective(pr.Profile(), None, NOW)
    assert pr.filter_rig(rig, e) == {"cat": "ok", "tx": False, "refusals": 2}
    assert pr.filter_rig(rig, pr.effective(pr.Profile(freq_mode=True), None, NOW)) == rig
    assert pr.filter_rig(rig, pr.effective(pr.Profile(rig=False), None, NOW)) is None
    assert pr.severity_passes("critique", "avertissement") and not pr.severity_passes("info", "avertissement")
    assert pr.severity_passes("inconnue", "erreur") and not pr.severity_passes("inconnue", "critique")


# ------------------------------------------------------------------ masquage (corpus piégé)
SALT = b"sel-de-liaison-16o"
SECRETS = ["hunter2", "s3cr3t-T0ken", "ntfy-sujet-perso-8f2a", "bob", "kriss@example.org", "86.247.12.34",
           "2a01:cb19:8a3:1200:9d1e:3c2b:aa10:4f7e", "13003336", "A1B2C3D4E5F6", "minix-bzh",
           "9f1c2e3a-4b5d-4c6e-8f70-112233445566", "abcdef0123456789"]
CORPUS = [
    "station.toml : password = hunter2",
    'auth_password="hunter2" refusé',
    "token: s3cr3t-T0ken ; retry",
    "Authorization: Bearer s3cr3t-T0ken",
    "ntfy : envoi vers https://ntfy.sh/ntfy-sujet-perso-8f2a?priority=5 échoué",
    "https://bob:hunter2@relay.example.org:8443/v1/sync",
    "Contact kriss@example.org",
    "client 86.247.12.34:55461 refusé",
    "liaison depuis [2a01:cb19:8a3:1200:9d1e:3c2b:aa10:4f7e]:443",
    "pair 2a01:cb19:8a3:1200:9d1e:3c2b:aa10:4f7e connecté",
    r"Fichier C:\Users\bob\AppData\Local\trx\journal.txt",
    "C:/Users/bob/Desktop/rapport.zip",
    "/home/bob/.trx-remote/state",
    "/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_13003336-if00-port0",
    "carte a1:b2:c3:d4:e5:f6 et A1-B2-C3-D4-E5-F6",
    "machine minix-bzh redémarrée",
    "station-id 9f1c2e3a-4b5d-4c6e-8f70-112233445566",
]


def test_redaction_corpus_lets_nothing_through():
    r = redact.Redactor(SALT, known={"minix-bzh": "<host>", "abcdef0123456789": "***"})
    for line in CORPUS:
        out = r.text(line)
        for secret in SECRETS:
            if secret == "bob":
                assert "\\bob" not in out and "/bob" not in out, (line, out)
            elif secret == "A1B2C3D4E5F6":
                assert "d4:e5:f6" not in out.lower() and "d4-e5-f6" not in out.lower(), (line, out)
            else:
                assert secret.lower() not in out.lower(), (line, out)


def test_redaction_keeps_what_helps_the_diagnosis():
    r = redact.Redactor(SALT)
    assert r.text("rigctld 127.0.0.1:4532 : délai dépassé") == "rigctld 127.0.0.1:4532 : délai dépassé"
    assert r.text("box 192.168.1.1, poste 10.0.0.5") == "box LAN, poste LAN"
    assert r.text("ntfy https://ntfy.sh/sujet") == "ntfy https://ntfy.sh"
    assert r.text("Hamlib 4.7.2, station 0.158.0, 12:34:56") == "Hamlib 4.7.2, station 0.158.0, 12:34:56"
    assert r.text("IC-7300 sur _13003336-if00") == "IC-7300 sur _13003336-if00"      # hors by-id : inchangé
    assert "IC-7300_130…-if00" in r.text("/dev/serial/by-id/usb-Icom_IC-7300_13003336-if00")
    assert r.text("adresse fe80::1%eth0") == "adresse LAN"
    pub = r.text("86.247.12.34")
    assert pub.startswith("ip-") and pub == r.text("86.247.12.34")              # stable dans la liaison
    assert pub != redact.Redactor(b"autre-sel-de-liaison").text("86.247.12.34")  # pas d'une liaison à l'autre


def test_redaction_by_field():
    r = redact.Redactor(SALT)
    out = r.obj({"notify_url": "https://ntfy.sh/perso", "cluster": {"password": "hunter2", "host": "dx.example.org"},
                 "ptt": {"owner": "kriss-pc", "clients": ["kriss-pc", "s25"]}, "listeners": ["Loulou"],
                 "rig": {"serial": "13003336", "model": 3094}, "breizh_key": None, "tls": {"private_key": "-----"},
                 "lines": ["password=hunter2"], "enabled": True})
    assert out["notify_url"] == "https://ntfy.sh"
    assert out["cluster"] == {"password": "***", "host": "dx.example.org"}
    assert out["ptt"] == {"owner": "user-1", "clients": ["user-1", "user-2"]}
    assert out["listeners"] == ["visiteur-1"]
    assert out["rig"] == {"serial": "130…", "model": 3094}
    assert out["breizh_key"] is None and out["tls"] == {"private_key": "***"}
    assert out["lines"] == ["password=***"] and out["enabled"] is True
    deep: dict = {}
    cur = deep
    for _ in range(50):
        cur["a"] = {}
        cur = cur["a"]
    json.dumps(r.obj(deep))                                               # pas de récursion infinie
    with pytest.raises(ValueError):
        redact.Redactor(b"court")


# ------------------------------------------------------------------ requêtes au relais
def test_signed_requests_and_refusals():
    path, body, headers = wire.build_request(AIDED, "put", {"msg": {}}, t=NOW, n=5)
    assert headers["X-Orx-Station"] == AIDED.station_id and path == "/v1/mon/put"
    assert wire.verify_request(AIDED.ed_pub, path, body, headers["X-Orx-Signature"], now=NOW, last_n=4)["n"] == 5
    for kw, reason in (({"last_n": 5}, "replay"), ({"now": NOW + 700}, "clock")):
        args = {"now": NOW, "last_n": 0, **kw}
        with pytest.raises(RequestRefused, match=reason):
            wire.verify_request(AIDED.ed_pub, path, body, headers["X-Orx-Signature"], **args)
    with pytest.raises(ValueError):
        wire.build_request(AIDED, "exec", {}, t=NOW, n=1)


# ------------------------------------------------------------------ vecteurs et isolement
def test_shared_vectors_are_up_to_date():
    """Sinon : python -m trxstation.monlink.vectors"""
    assert VECTORS.read_text(encoding="utf-8") == vectors.render()


def test_shared_vectors_check_as_the_relay_and_the_peer_do():
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    for ident in data["identities"]:
        assert station_id_of(b64d(ident["ed_pub"], 32)) == ident["station_id"]
    for req in data["requests"]:
        ed = next(b64d(i["ed_pub"]) for i in data["identities"] if i["station_id"] == req["station"])
        wire.verify_request(ed, req["path"], req["body"].encode(), req["headers"]["X-Orx-Signature"],
                            now=data["now"], last_n=0)
    for case in data["refusals"]:
        with pytest.raises(RequestRefused) as err:
            wire.verify_request(b64d(case["ed_pub"]), case["path"], case["body"].encode(), case["signature"],
                                now=data["now"], last_n=case["last_n"])
        assert err.value.reason == case["reason"], case["case"]
    inv = data["invite"]
    keys = invite.derive(inv["code"])
    assert keys.address == inv["address"] and keys.key.hex() == inv["key_hex"]
    assert all(invite.normalize_code(v) == inv["code"] for v in inv["typed_variants"])
    pending = {keys.address: pairing.PendingInvite(keys, data["now"] + 900)}
    peer = pairing.check_pair(data["pair"]["request"], HELPER, pending, now=data["now"] + 60)
    assert pairing.fingerprint(HELPER.ed_pub, peer.ed) == data["pair"]["fingerprint"]
    link = data["link"]
    assert bytes.fromhex(link["key_hex"]) == pairing.link_key(HELPER, peer.id, peer.x)
    assert env.open_message(bytes.fromhex(link["key_hex"]), link["message"], me=HELPER.station_id, peer=peer.id,
                            peer_is_emitter=True)[2] == link["content"]


def test_monlink_package_never_touches_the_ptt_nor_the_cat():
    """Télémétrie seulement : ni sécurité d'émission, ni CAT, ni passerelle, ni appel `.command(`."""
    forbidden = ("safety", "cat", "rigctl", "ptt", "gateway", "subprocess")
    for path in (ROOT / "trxstation" / "monlink").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Attribute) and node.attr == "command":
                raise AssertionError(f"{path.name} : appel .command interdit au monitoring")
            for name in names:
                assert not any(part in forbidden for part in name.split(".")), f"{path.name} importe {name}"


def test_cjson_is_the_signed_form():
    assert cjson({"b": 1, "a": "é"}) == b'{"a":"\\u00e9","b":1}'
