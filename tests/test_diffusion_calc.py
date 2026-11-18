# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Diffusion en direct, lot D1a : calculs purs du protocole (docs/protocole-diffusion.md)."""
from __future__ import annotations

import ast
import base64
import json
import random
from pathlib import Path

import pytest

from trxstation.diffusion import protocol as p, vectors

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "protocol" / "diffusion_vectors.json"


def test_vectors_file_is_up_to_date():
    """Refabriquer : python -m trxstation.diffusion.vectors (le même fichier sert aux tests du serveur)."""
    assert json.loads(VECTORS.read_text(encoding="utf-8")) == vectors.build()


def test_signatures_of_the_vectors():
    for v in json.loads(VECTORS.read_text(encoding="utf-8"))["signatures"]:
        body = v["corps"].encode("utf-8")
        assert p.sign(bytes.fromhex(v["cle"]), v["methode"], v["chemin"], body) == v["signature"], v["nom"]
        assert json.loads(body)["station"] == "bob56fr"


def test_signature_covers_the_path_and_every_byte():
    key = bytes.fromhex(vectors.KEY)
    body = p.meta_body("bob56fr", 1, "prive", {"pseudo": "A"})
    sig = p.sign(key, "POST", "/api/v1/bob56fr/meta", body)
    assert sig != p.sign(key, "POST", "/api/v1/bob56fr/auditeur", body)
    assert sig != p.sign(key, "POST", "/api/v1/bob56fr/meta", body + b" ")
    assert sig != p.sign(b"autre", "POST", "/api/v1/bob56fr/meta", body)
    headers = p.signed_headers(key, "/api/v1/bob56fr/meta", body)
    assert headers[p.SIGNATURE_HEADER] == sig and headers["Content-Type"] == "application/json"


def test_body_is_compact_utf8_json():
    body = p.meta_body("bob56fr", 5, "public", {"message": "Écoute"})
    assert body == '{"v":1,"station":"bob56fr","ts_ms":5,"acces":"public","meta":{"message":"Écoute"}}'.encode()


def test_meta_refusals_of_the_vectors_and_never_sent():
    for v in json.loads(VECTORS.read_text(encoding="utf-8"))["meta_refusees"]:
        with pytest.raises(p.DiffusionRefused):
            p.check_meta(v["meta"])
        with pytest.raises(p.DiffusionRefused):
            p.meta_body("bob56fr", 1, "prive", v["meta"])
    with pytest.raises(p.DiffusionRefused):
        p.check_meta(["pseudo"])


def test_pick_meta_keeps_only_the_operator_choice():
    values = {"pseudo": "BOB", "frequence_hz": 7074000, "mode": "USB", "tx": False, "s_metre": None,
              "adresse_ip": "192.0.2.1"}
    assert p.pick_meta(p.DEFAULT_META_CHOICE, values) == {"pseudo": "BOB", "frequence_hz": 7074000, "mode": "USB",
                                                         "tx": False}       # tout par défaut (étape 248), absents omis
    assert p.pick_meta(["pseudo", "frequence_hz", "tx", "s_metre", "adresse_ip"], values) == {
        "pseudo": "BOB", "frequence_hz": 7074000, "tx": False}                               # absents et inconnus omis
    assert list(p.CHOICE_FIELDS) == ["pseudo", "indicatif", "frequence_hz", "mode", "bande", "tx", "s_metre", "filtre",
                                     "voyants", "message"]


def test_station_names_mounts_and_addresses():
    assert p.mount("bob56fr", "prive") == "/bob56fr-prive"
    assert p.stream_url("diffusion.example.org", "bob56fr", "public") == "https://diffusion.example.org/bob56fr-public"
    assert p.listen_page("diffusion.example.org", "bob56fr") == "https://diffusion.example.org/ecoute/bob56fr"
    for bad in ("B", "Bob56fr", "a/b", "x" * 33, "", None):
        with pytest.raises(p.DiffusionRefused):
            p.check_station(bad)
    for bad in ("", "Prive", "tous"):
        with pytest.raises(p.DiffusionRefused):
            p.check_access(bad)
    with pytest.raises(p.DiffusionRefused):
        p.api_path("bob56fr", "etat")
    assert p.DEFAULT_ACCESS == "prive"


def test_source_request_is_raw_like_libshout():
    """Ni chunked ni longueur : Icecast 2.4 corrompt les pages Ogg d'un flux chunked (essai du 2026-11-17)."""
    v = json.loads(VECTORS.read_text(encoding="utf-8"))["source"]
    req = p.source_request(v["hote"], v["port"], v["station"], v["acces"], v["mot_de_passe"], v["codec"], v["nom"])
    assert req.decode() == v["requete"]
    text = req.decode()
    assert text.startswith("PUT /bob56fr-prive HTTP/1.1\r\n") and text.endswith("\r\n\r\n")
    assert "Transfer-Encoding" not in text and "Content-Length" not in text
    assert "Ice-Public: 0" in text and "Content-Type: audio/ogg" in text
    cred = base64.b64encode(b"source:MotSource42").decode()
    assert f"Authorization: Basic {cred}" in text
    assert "Content-Type: audio/mpeg" in p.source_request("h", 1, "bob56fr", "public", "x", "mp3").decode()
    assert "\n" not in p.source_request("h", 1, "bob56fr", "public", "x", "opus", "a\r\nX-Pirate: 1").decode() \
        .split("Ice-Name: ")[1].split("\r\n")[0]
    for codec, pw in (("aac", "x"), ("opus", ""), ("opus", "a\r\nb")):
        with pytest.raises(p.DiffusionRefused):
            p.source_request("h", 1, "bob56fr", "prive", pw, codec)


def test_source_reply_status():
    assert p.source_reply_status(b"HTTP/1.0 200 OK\r\n\r\n") == 200
    assert p.source_reply_status(b"HTTP/1.0 403 Forbidden\r\n") == 403      # montage occupé
    assert p.source_reply_status(b"") is None
    assert p.source_reply_status(b"\x00\x01garbage") is None


def test_backoff_and_ts_ms():
    assert json.loads(VECTORS.read_text(encoding="utf-8"))["reconnexion_s"] == [2, 4, 8, 16, 32, 60, 60, 60]
    assert p.backoff(0) == 2
    assert p.next_ts_ms(1000, 0) == 1000
    assert p.next_ts_ms(1000, 1000) == 1001          # même milliseconde : jamais rejoué (409)
    assert p.next_ts_ms(900, 1000) == 1001           # horloge qui recule


def test_listener_body_and_generated_password():
    body = json.loads(p.listener_body("bob56fr", 3, "auditeur", "Abcdef123456"))
    assert body == {"v": 1, "station": "bob56fr", "ts_ms": 3, "user": "auditeur", "password": "Abcdef123456"}
    for user, pw in (("a b", "Abcdef123456"), ("auditeur", "court1"), ("auditeur", "avec espace 1"), ("", "x" * 9)):
        with pytest.raises(p.DiffusionRefused):
            p.listener_body("bob56fr", 3, user, pw)
    pw = p.new_listener_password(random.Random(1))
    assert len(pw) == 12 and p.LISTENER_PASSWORD.match(pw)
    assert not set(pw) & set("0O1lI")
    assert len({p.new_listener_password() for _ in range(50)}) == 50
    assert p.masked("Abcdef123456") == "Ab…56" and "cdef" not in p.masked("Abcdef123456") and p.masked("abc") == "…"


def test_meta_reply_is_untrusted():
    assert p.parse_meta_reply({"ok": True, "auditeurs": {"prive": 2, "public": 0}}) == {"prive": 2, "public": 0}
    for bad in (None, [], {"ok": True}, {"ok": True, "auditeurs": None}, {"ok": "oui", "auditeurs": {}},
                {"ok": True, "auditeurs": {"prive": -1, "public": 0}},
                {"ok": True, "auditeurs": {"prive": True, "public": 0}},
                {"ok": True, "auditeurs": {"prive": 10**9, "public": 0}},
                {"ok": True, "auditeurs": {"prive": 1}}):
        assert p.parse_meta_reply(bad) is None, bad


def test_duration():
    assert p.DEFAULT_HOURS == 1
    assert p.end_time(1000.0, 1) == 4600.0
    assert p.end_time(1000.0, None) is None                           # sans limite : choix explicite
    for bad in (0, 25, -1, True, 1.5, "2"):
        with pytest.raises(p.DiffusionRefused):
            p.check_hours(bad)


def test_diffusion_package_never_touches_the_ptt_nor_the_cat():
    """Aucun droit sur le poste (cahier § 3) : ni sécurité d'émission, ni CAT, ni passerelle, ni `.command(`."""
    forbidden = ("safety", "cat", "rigctl", "ptt", "gateway", "subprocess")
    for path in (ROOT / "trxstation" / "diffusion").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Attribute) and node.attr == "command":
                raise AssertionError(f"{path.name} : appel .command interdit à la diffusion")
            for name in names:
                assert not any(part in forbidden for part in name.split(".")), f"{path.name} importe {name}"
