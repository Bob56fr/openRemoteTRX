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


# ---------------------------------------------------------------- autorité de certification de la station (étape 195)
# Le navigateur ne retient le mot de passe (et n'affiche plus d'avertissement) que si le certificat est reconnu. La
# station crée sa PROPRE autorité ; l'opérateur l'installe une fois sur chaque appareil (PC, téléphone). Pour qu'une
# clé d'autorité volée ne puisse pas servir à usurper un autre site, l'autorité est CONTRAINTE (NameConstraints) aux
# adresses privées (réseau local, VPN) et aux seuls noms de la station.
CA_CERT, CA_KEY = "station-ca.pem", "station-ca-key.pem"
PRIVATE_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "127.0.0.0/8",
                "fd00::/8", "::1/128")


def certificate_hosts(cert_file: str | Path) -> list[str]:
    """Noms et adresses (subjectAltName) du certificat ; liste vide si illisible."""
    from cryptography import x509
    try:
        cert = x509.load_pem_x509_certificate(Path(cert_file).read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return []
    return [str(ip) for ip in san.get_values_for_type(x509.IPAddress)] + list(san.get_values_for_type(x509.DNSName))


def _names(hostnames: list[str]):
    from cryptography import x509
    names = []
    for host in hostnames:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    return names


def _write_key(path: Path, key) -> None:
    from cryptography.hazmat.primitives import serialization
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    if os.name == "posix":
        os.chmod(path, 0o600)


def generate_station_ca(folder: str | Path, hostnames: list[str], label: str = "", days: int = 3650) -> Path:
    """Autorité de la station (EC P-256, 10 ans), contrainte aux adresses privées et aux noms DNS donnés.
    Rend le chemin du certificat de l'autorité ; la clé reste dans le même dossier (0600)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder = Path(folder)
    dns = sorted({h for h in hostnames if not _is_ip(h)})
    permitted = [x509.IPAddress(ipaddress.ip_network(n)) for n in PRIVATE_NETS] + [x509.DNSName(d) for d in dns]
    for host in hostnames:                                     # adresse publique donnée explicitement : permise aussi
        if _is_ip(host) and not any(ipaddress.ip_address(host) in ipaddress.ip_network(n) for n in PRIVATE_NETS):
            ip = ipaddress.ip_address(host)
            permitted.append(x509.IPAddress(ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}")))
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "openRemoteTRX"),
                      x509.NameAttribute(NameOID.COMMON_NAME, ("Station openRemoteTRX " + label).strip()[:64])])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=days))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / CA_CERT).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(folder / CA_KEY, key)
    return folder / CA_CERT


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def generate_station_cert(hostnames: list[str], ca_folder: str | Path, cert_path: str | Path, key_path: str | Path,
                          days: int = 825) -> None:
    """Certificat de la passerelle SIGNÉ par l'autorité de la station ; le fichier contient le certificat puis
    l'autorité (chaîne complète). L'empreinte épinglée par l'application est celle du PREMIER (la passerelle)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    if not hostnames:
        raise ValueError("au moins un nom ou une adresse IP est nécessaire")
    ca_folder = Path(ca_folder)
    ca_cert = x509.load_pem_x509_certificate((ca_folder / CA_CERT).read_bytes())
    ca_key = serialization.load_pem_private_key((ca_folder / CA_KEY).read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0][:64])]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(min(now + datetime.timedelta(days=days), ca_cert.not_valid_after_utc))
            .add_extension(x509.SubjectAlternativeName(_names(hostnames)), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    cert_path, key_path = Path(cert_path), Path(key_path)
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    _write_key(key_path, key)


def ca_covers(folder: str | Path, hostnames: list[str]) -> bool:
    """Vrai si l'autorité du dossier existe (certificat ET clé) et que ses contraintes couvrent ces noms et adresses."""
    from cryptography import x509
    folder = Path(folder)
    try:
        ca = x509.load_pem_x509_certificate((folder / CA_CERT).read_bytes())
        if not (folder / CA_KEY).is_file():
            return False
        nc = ca.extensions.get_extension_for_class(x509.NameConstraints).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False
    nets = [n.value for n in nc.permitted_subtrees or [] if isinstance(n, x509.IPAddress)]
    dns = {n.value.lower() for n in nc.permitted_subtrees or [] if isinstance(n, x509.DNSName)}
    for host in hostnames:
        if _is_ip(host):
            if not any(ipaddress.ip_address(host) in net for net in nets):
                return False
        elif host.lower() not in dns and not any(host.lower().endswith("." + d) for d in dns):
            return False
    return True


def station_ca_der(tls_cert: str | Path) -> bytes | None:
    """Certificat de l'autorité de la station (DER, à installer sur un appareil), à côté du certificat de la
    passerelle ; None s'il n'y en a pas. Ne lit JAMAIS une clé."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    if not tls_cert:
        return None
    try:
        cert = x509.load_pem_x509_certificate((Path(tls_cert).parent / CA_CERT).read_bytes())
    except (OSError, ValueError):
        return None
    return cert.public_bytes(serialization.Encoding.DER)
