# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""HTTPS natif de la passerelle : contexte TLS et génération d'un certificat auto-signé.

Un certificat auto-signé chiffre la liaison mais le navigateur affiche un avertissement : à réserver à un essai.
Pour un usage durable, préfère un certificat reconnu (Let's Encrypt) via un proxy inverse (Caddy, nginx) ou tls_cert/tls_key.
"""
from __future__ import annotations

import datetime
import hashlib
import ipaddress
import os
import ssl
from pathlib import Path


def make_ssl_context(cert_file: str, key_file: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_file, key_file)          # ssl.SSLError / OSError si fichiers absents ou incohérents
    return context


def certificate_fingerprint(cert_file: str | Path) -> str:
    """Empreinte SHA-256 du certificat (le premier du fichier PEM), « AB:CD:… » comme l'affichent les navigateurs.

    C'est elle que l'application Android épingle à l'appairage : sans dépendance (stdlib), ValueError si le
    fichier ne contient pas de certificat, OSError s'il est illisible.
    """
    text = Path(cert_file).read_text(encoding="ascii", errors="replace")
    begin, end = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
    start = text.find(begin)
    stop = text.find(end, start + 1) if start >= 0 else -1
    if stop < 0:
        raise ValueError("aucun certificat PEM dans ce fichier")
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(text[start:stop + len(end)])).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def generate_self_signed(hostnames: list[str], cert_path: str | Path, key_path: str | Path, days: int = 825) -> None:
    """Certificat + clé EC P-256, valables `days` jours, pour les noms ou adresses IP donnés."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    if not hostnames:
        raise ValueError("au moins un nom ou une adresse IP est nécessaire")
    names: list[x509.GeneralName] = []
    for host in hostnames:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0][:64])])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
                   .not_valid_after(now + datetime.timedelta(days=days))
                   .add_extension(x509.SubjectAlternativeName(names), critical=False)
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .sign(key, hashes.SHA256()))
    cert_path, key_path = Path(cert_path), Path(key_path)
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    if os.name == "posix":
        os.chmod(key_path, 0o600)                         # la clé privée ne doit être lisible que par son propriétaire
