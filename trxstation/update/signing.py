# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Signature Ed25519 des paquets de mise à jour : fichier `<paquet>.zip.sig` à côté du zip.

Format (texte UTF-8, une clé par ligne, dans cet ordre) :

    trx-remote-signature 1
    file = trx-remote-debian-0.23.0.zip
    version = 0.23.0
    sha256 = <64 caractères hexadécimaux>
    key = <identifiant de la clé : 16 premiers caractères hex du SHA-256 de la clé publique>
    signature = <signature Ed25519 en base64>

La signature couvre les quatre premières lignes (message canonique) : le nom du fichier, la version
et l'empreinte du zip. Un ancien paquet signé ne peut donc pas être présenté comme une version plus
récente. Toute anomalie lève SignatureError : l'appelant n'installe rien.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .pubkey import PUBLIC_KEYS

MAGIC = "trx-remote-signature 1"
FIELDS = ("file", "version", "sha256", "key", "signature")
MAX_SIG_BYTES = 4096
_FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_VERSION_RE = re.compile(r"[0-9][0-9A-Za-z.+-]{0,39}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_KEYID_RE = re.compile(r"[0-9a-f]{16}")


class SignatureError(Exception):
    """Signature absente, mal formée, d'une clé inconnue ou qui ne correspond pas au fichier."""


@dataclass(frozen=True)
class SignedInfo:
    file: str
    version: str
    sha256: str

    def canonical(self) -> bytes:
        return f"{MAGIC}\nfile = {self.file}\nversion = {self.version}\nsha256 = {self.sha256}\n".encode()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_key(text: str) -> bytes:
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError("clé publique illisible") from exc
    if len(raw) != 32:
        raise SignatureError("clé publique de longueur invalide")
    return raw


def key_id(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


def _check_info(info: SignedInfo) -> None:
    if not _FILE_RE.fullmatch(info.file):
        raise SignatureError(f"nom de fichier refusé : {info.file!r}")
    if not _VERSION_RE.fullmatch(info.version):
        raise SignatureError(f"version refusée : {info.version!r}")
    if not _HEX64_RE.fullmatch(info.sha256):
        raise SignatureError("empreinte SHA-256 mal formée")


def sign_file(path: str | Path, version: str, private_key) -> str:
    """Texte du fichier .sig pour `path` (private_key : Ed25519PrivateKey de cryptography)."""
    from cryptography.hazmat.primitives import serialization

    info = SignedInfo(Path(path).name, version, file_sha256(path))
    _check_info(info)
    public_raw = private_key.public_key().public_bytes(serialization.Encoding.Raw,
                                                       serialization.PublicFormat.Raw)
    signature = base64.b64encode(private_key.sign(info.canonical())).decode("ascii")
    return info.canonical().decode() + f"key = {key_id(public_raw)}\nsignature = {signature}\n"


def parse_signature(text: str) -> tuple[SignedInfo, str, bytes]:
    """(infos signées, identifiant de clé, signature brute) ; SignatureError si le format n'est pas exact."""
    if not isinstance(text, str) or len(text.encode("utf-8", "replace")) > MAX_SIG_BYTES:
        raise SignatureError("fichier de signature absent ou trop grand")
    lines = [line.rstrip("\r") for line in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    if len(lines) != 1 + len(FIELDS) or lines[0] != MAGIC:
        raise SignatureError("format de signature inconnu")
    values: dict[str, str] = {}
    for name, line in zip(FIELDS, lines[1:]):
        key, sep, value = line.partition(" = ")
        if not sep or key != name or not value or value != value.strip():
            raise SignatureError(f"ligne de signature inattendue : {line[:60]!r}")
        values[name] = value
    info = SignedInfo(values["file"], values["version"], values["sha256"])
    _check_info(info)
    if not _KEYID_RE.fullmatch(values["key"]):
        raise SignatureError("identifiant de clé mal formé")
    try:
        raw_sig = base64.b64decode(values["signature"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError("signature illisible") from exc
    if len(raw_sig) != 64:
        raise SignatureError("signature de longueur invalide")
    return info, values["key"], raw_sig


def verify_file(path: str | Path, sig_text: str, *, expected_file: str, expected_version: str,
                public_keys: tuple[str, ...] | None = None) -> SignedInfo:
    """Vérifie `path` contre sa signature ; SignatureError au moindre écart (rien ne doit alors être installé).

    `expected_file` et `expected_version` viennent de la Release annoncée : la signature doit porter
    exactement ces valeurs, en plus de correspondre aux octets du fichier.
    """
    keys = PUBLIC_KEYS if public_keys is None else public_keys
    if not keys:
        raise SignatureError("aucune clé publique de confiance : mise à jour automatique impossible")
    info, kid, raw_sig = parse_signature(sig_text)
    known = {key_id(raw): raw for raw in (_decode_key(k) for k in keys)}
    if kid not in known:
        raise SignatureError("paquet signé par une clé inconnue")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise SignatureError("module cryptography absent : vérification impossible") from exc
    try:
        Ed25519PublicKey.from_public_bytes(known[kid]).verify(raw_sig, info.canonical())
    except InvalidSignature as exc:
        raise SignatureError("signature invalide") from exc
    if info.file != expected_file:
        raise SignatureError(f"la signature concerne {info.file}, pas {expected_file}")
    if info.version != expected_version:
        raise SignatureError(f"la signature concerne la version {info.version}, pas {expected_version}")
    try:
        actual = file_sha256(path)
    except OSError as exc:
        raise SignatureError(f"paquet illisible : {exc}") from exc
    if actual != info.sha256:
        raise SignatureError("le paquet ne correspond pas à sa signature (fichier modifié ou incomplet)")
    return info
