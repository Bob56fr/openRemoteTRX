# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Clé de signature des mises à jour : créée hors du dépôt, jamais écrasée, clé publique inscrite."""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import stat
import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from trxstation.update import keyfile, signing  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PASS = "une phrase de passe assez longue"


def _script():
    spec = importlib.util.spec_from_file_location("gen_update_key", ROOT / "scripts" / "gen_update_key.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pubkey_copy(tmp_path):
    """Copie de pubkey.py, ramenée à une liste VIDE (le vrai fichier contient la clé de l'auteur)."""
    target = tmp_path / "pubkey.py"
    shutil.copy(ROOT / "trxstation" / "update" / "pubkey.py", target)
    text = target.read_text(encoding="utf-8")
    target.write_text(re.sub(r"PUBLIC_KEYS: tuple\[str, \.\.\.\] = \([^)]*\)", "PUBLIC_KEYS: tuple[str, ...] = ()", text),
                      encoding="utf-8")
    assert _keys_of(target) == ()
    return target


def _keys_of(path: Path) -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location("pubkey_copy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PUBLIC_KEYS


def _answers(*values):
    it = iter(values)
    return lambda _prompt: next(it)


def test_script_creates_encrypted_key_and_registers_public_key(tmp_path, pubkey_copy, capsys):
    key = tmp_path / "profil" / "cle.pem"
    code = _script().main(["--output", str(key)], ask=_answers(PASS, PASS), pubkey_file=pubkey_copy)
    assert code == 0 and keyfile.is_encrypted(key)
    private = keyfile.load(key, PASS.encode())
    public = keyfile.public_text(private)
    assert _keys_of(pubkey_copy) == (public,)
    assert "à sauvegarder hors ligne" in capsys.readouterr().out
    # La paire sert bien à signer puis vérifier un paquet.
    package = tmp_path / "trx-remote-debian-0.23.0.zip"
    package.write_bytes(b"PK")
    sig = signing.sign_file(package, "0.23.0", private)
    signing.verify_file(package, sig, expected_file=package.name, expected_version="0.23.0",
                        public_keys=_keys_of(pubkey_copy))


def test_existing_key_is_never_overwritten(tmp_path, pubkey_copy):
    key = tmp_path / "cle.pem"
    key.write_bytes(b"ancienne cle")
    code = _script().main(["--output", str(key), "--sans-phrase"], ask=_answers(), pubkey_file=pubkey_copy)
    assert code == 1 and key.read_bytes() == b"ancienne cle"
    assert _keys_of(pubkey_copy) == ()


def test_key_inside_the_repository_is_refused(tmp_path, pubkey_copy):
    repo = tmp_path / "depot"
    repo.mkdir()
    code = _script().main(["--output", str(repo / "sous" / "cle.pem"), "--sans-phrase"], ask=_answers(),
                          repo=repo, pubkey_file=pubkey_copy)
    assert code == 1 and not (repo / "sous" / "cle.pem").exists()


def test_default_location_is_outside_the_repository(monkeypatch, tmp_path):
    monkeypatch.delenv(keyfile.ENV_VAR, raising=False)
    assert not keyfile.inside(keyfile.default_key_path(), ROOT)
    monkeypatch.setenv(keyfile.ENV_VAR, str(tmp_path / "x.pem"))
    assert keyfile.default_key_path() == tmp_path / "x.pem"


def test_short_or_mismatched_passphrase_is_asked_again(tmp_path, pubkey_copy):
    key = tmp_path / "cle.pem"
    code = _script().main(["--output", str(key)], pubkey_file=pubkey_copy,
                          ask=_answers("court", PASS, PASS + "x", PASS, PASS))
    assert code == 0
    keyfile.load(key, PASS.encode())


def test_wrong_passphrase_is_a_clear_refusal(tmp_path):
    key = tmp_path / "cle.pem"
    keyfile.create(key, PASS.encode())
    with pytest.raises(keyfile.KeyFileError, match="phrase de passe"):
        keyfile.load(key, b"mauvaise phrase de passe")
    with pytest.raises(keyfile.KeyFileError, match="illisible"):
        keyfile.load(tmp_path / "absente.pem", None)


def test_show_public_key_of_existing_key(tmp_path, capsys):
    key = tmp_path / "cle.pem"
    public = keyfile.public_text(keyfile.create(key, PASS.encode()))
    assert _script().main(["--output", str(key), "--afficher"], ask=_answers(PASS)) == 0
    assert capsys.readouterr().out.strip() == public


def test_register_is_idempotent_and_keeps_previous_keys(pubkey_copy):
    assert keyfile.register_public_key(pubkey_copy, "A" * 43 + "=")
    assert not keyfile.register_public_key(pubkey_copy, "A" * 43 + "=")
    assert keyfile.register_public_key(pubkey_copy, "B" * 43 + "=")
    assert _keys_of(pubkey_copy) == ("A" * 43 + "=", "B" * 43 + "=")


@pytest.mark.skipif(sys.platform == "win32", reason="droits POSIX")
def test_private_key_is_readable_by_owner_only(tmp_path):
    key = tmp_path / "cle.pem"
    keyfile.create(key, None)
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o600


def test_private_keys_are_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert "*.pem" in ignored and "*.key" in ignored
