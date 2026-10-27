# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Signature Ed25519 des paquets de mise à jour : tout écart est un refus."""
from __future__ import annotations

import base64

import pytest

pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from trxstation.update import pubkey, signing  # noqa: E402
from trxstation.update.signing import SignatureError, parse_signature, sign_file, verify_file  # noqa: E402

NAME, VERSION = "trx-remote-debian-0.23.0.zip", "0.23.0"


def _pub(private: Ed25519PrivateKey) -> str:
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture
def signed(tmp_path):
    private = Ed25519PrivateKey.generate()
    package = tmp_path / NAME
    package.write_bytes(b"PK contenu du paquet" * 100)
    return package, sign_file(package, VERSION, private), (_pub(private),)


def _verify(package, sig, keys, **kw):
    args = {"expected_file": NAME, "expected_version": VERSION, "public_keys": keys} | kw
    return verify_file(package, sig, **args)


def test_valid_signature_is_accepted(signed):
    package, sig, keys = signed
    info = _verify(package, sig, keys)
    assert (info.file, info.version) == (NAME, VERSION)
    assert sig.startswith(signing.MAGIC + "\n") and sig.endswith("\n")


def test_windows_line_endings_are_tolerated(signed):
    package, sig, keys = signed
    _verify(package, sig.replace("\n", "\r\n"), keys)


def test_modified_or_truncated_package_is_refused(signed):
    package, sig, keys = signed
    data = package.read_bytes()
    package.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(SignatureError, match="ne correspond pas"):
        _verify(package, sig, keys)
    package.write_bytes(data[:-10])
    with pytest.raises(SignatureError):
        _verify(package, sig, keys)


def test_missing_package_is_a_refusal_not_a_crash(signed, tmp_path):
    _, sig, keys = signed
    with pytest.raises(SignatureError, match="illisible"):
        _verify(tmp_path / "absent.zip", sig, keys)


def test_unknown_key_and_empty_key_list_are_refused(signed):
    package, sig, _ = signed
    with pytest.raises(SignatureError, match="clé inconnue"):
        _verify(package, sig, (_pub(Ed25519PrivateKey.generate()),))
    with pytest.raises(SignatureError, match="aucune clé"):
        _verify(package, sig, ())


def test_shipped_key_list_is_used_by_default(signed, monkeypatch):
    package, sig, keys = signed
    monkeypatch.setattr(signing, "PUBLIC_KEYS", ())
    with pytest.raises(SignatureError, match="aucune clé"):
        verify_file(package, sig, expected_file=NAME, expected_version=VERSION)
    monkeypatch.setattr(signing, "PUBLIC_KEYS", keys)
    verify_file(package, sig, expected_file=NAME, expected_version=VERSION)


def test_signature_from_another_key_with_same_key_id_line_is_refused(signed):
    package, sig, keys = signed
    forged = sign_file(package, VERSION, Ed25519PrivateKey.generate()).splitlines()
    lines = sig.splitlines()
    lines[-1] = forged[-1]                             # signature d'une autre clé, identifiant de la bonne
    with pytest.raises(SignatureError, match="signature invalide"):
        _verify(package, "\n".join(lines), keys)


def test_other_version_or_file_name_is_refused(signed):
    package, sig, keys = signed
    with pytest.raises(SignatureError, match="version"):
        _verify(package, sig, keys, expected_version="0.24.0")
    with pytest.raises(SignatureError, match="concerne"):
        _verify(package, sig, keys, expected_file="trx-remote-debian-0.24.0.zip")


def test_editing_a_signed_field_breaks_the_signature(signed):
    package, sig, keys = signed
    tampered = sig.replace("version = 0.23.0", "version = 0.99.0")
    with pytest.raises(SignatureError, match="signature invalide"):
        _verify(package, tampered, keys, expected_version="0.99.0")


@pytest.mark.parametrize("mutate", [
    lambda s: "",
    lambda s: s.replace(signing.MAGIC, "trx-remote-signature 2"),
    lambda s: s.replace("file = ", "file= "),
    lambda s: s.replace("version = 0.23.0", "version = 0.23.0 "),
    lambda s: "\n".join(s.splitlines()[:-1]),                        # ligne manquante
    lambda s: s + "extra = 1\n",                                     # ligne en trop
    lambda s: "\n".join(reversed(s.splitlines())),                   # ordre changé
    lambda s: s.replace("file = trx", "file = ../trx"),
    lambda s: s.replace("signature = ", "signature = !!"),
    lambda s: s.replace("key = ", "key = zz"),
    lambda s: s + "#" * signing.MAX_SIG_BYTES,
])
def test_malformed_signature_files_are_refused(signed, mutate):
    package, sig, keys = signed
    with pytest.raises(SignatureError):
        _verify(package, mutate(sig), keys)


def test_parse_rejects_non_text_and_bad_lengths():
    with pytest.raises(SignatureError):
        parse_signature(None)  # type: ignore[arg-type]
    short_sig = base64.b64encode(b"x" * 10).decode()
    text = (f"{signing.MAGIC}\nfile = {NAME}\nversion = {VERSION}\nsha256 = {'0' * 64}\n"
            f"key = {'0' * 16}\nsignature = {short_sig}\n")
    with pytest.raises(SignatureError, match="longueur"):
        parse_signature(text)


def test_malformed_trusted_key_is_refused(signed):
    package, sig, _ = signed
    with pytest.raises(SignatureError, match="clé publique"):
        _verify(package, sig, ("pas une clé",))
    with pytest.raises(SignatureError, match="longueur"):
        _verify(package, sig, (base64.b64encode(b"x" * 31).decode(),))


def test_sign_file_refuses_dangerous_version(tmp_path):
    package = tmp_path / NAME
    package.write_bytes(b"x")
    with pytest.raises(SignatureError):
        sign_file(package, "0.23.0\nsha256 = faux", Ed25519PrivateKey.generate())


def test_shipped_public_keys_are_well_formed():
    for key in pubkey.PUBLIC_KEYS:
        assert len(base64.b64decode(key, validate=True)) == 32
