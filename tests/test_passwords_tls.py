# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mots de passe (scrypt) et HTTPS natif."""
import ssl
import time

import pytest

from trxstation.passwords import (MIN_LENGTH, generate_password, hash_password, is_valid_hash, parse_hash,
                                  password_problem, verify_password)


def test_hash_and_verify_roundtrip_with_unique_salts():
    first, second = hash_password("Une phrase de passe"), hash_password("Une phrase de passe")
    assert first != second                                            # sel aléatoire : deux empreintes différentes
    assert verify_password("Une phrase de passe", first) and verify_password("Une phrase de passe", second)
    assert not verify_password("Une phrase de passe.", first) and not verify_password("", first)
    assert verify_password("Éàü ™ 日本語 passe", hash_password("Éàü ™ 日本語 passe"))        # Unicode accepté


def test_hash_has_a_cost_that_slows_guessing_but_stays_usable():
    start = time.perf_counter()
    hash_password("Une phrase de passe")
    assert 0.02 < time.perf_counter() - start < 3.0


def test_malformed_or_dangerous_hashes_are_rejected_not_executed():
    good = hash_password("x" * 16)
    assert is_valid_hash(good)
    n = good.split("$")
    for bad in ("", "pas un hash", "scrypt$1$1$1$AA==$AA==", "bcrypt$32768$8$1$" + n[4] + "$" + n[5],
                f"scrypt$1048576$32$16${n[4]}${n[5]}",                # coût démesuré : refusé (déni de service)
                f"scrypt$32768$8$1$@@@${n[5]}", f"scrypt$32767$8$1${n[4]}${n[5]}", "scrypt$32768$8$1$AAAA$AAAA"):
        assert not is_valid_hash(bad), bad
        assert not verify_password("x" * 16, bad)
    assert parse_hash(good)[:3] == (32768, 8, 1) and not verify_password(None, good)


def test_password_policy_and_generator():
    assert password_problem("court") and str(MIN_LENGTH) in password_problem("court")
    assert password_problem("aaaaaaaaaaaaaaaa") and password_problem("abababababababab")
    assert password_problem("mon-phone-secret", "phone") and password_problem(" espace au début 123")
    assert password_problem("Un mot de passe correct 42", "phone") is None
    generated = {generate_password() for _ in range(20)}
    assert len(generated) == 20 and all(password_problem(g) is None and len(g) >= 20 for g in generated)


def test_self_signed_certificate_can_be_generated_and_loaded_by_the_tls_context(tmp_path):
    from trxstation.gateway.api.tls import generate_self_signed, make_ssl_context
    cert, key = tmp_path / "tls" / "cert.pem", tmp_path / "tls" / "key.pem"
    generate_self_signed(["station.example.org", "192.168.1.10"], cert, key)
    assert cert.read_text().startswith("-----BEGIN CERTIFICATE-----") and "PRIVATE KEY" in key.read_text()
    context = make_ssl_context(str(cert), str(key))
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    from cryptography import x509
    parsed = x509.load_pem_x509_certificate(cert.read_bytes())
    san = parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "station.example.org" in san.get_values_for_type(x509.DNSName)
    assert [str(i) for i in san.get_values_for_type(x509.IPAddress)] == ["192.168.1.10"]
    import os
    if os.name == "posix":
        assert oct(key.stat().st_mode & 0o777) == "0o600"                 # clé privée lisible par son seul propriétaire
    with pytest.raises(ValueError):
        generate_self_signed([], cert, key)
    with pytest.raises((OSError, ssl.SSLError)):
        make_ssl_context(str(cert), str(tmp_path / "absente.pem"))


def test_tls_context_actually_serves_https_to_a_client_that_trusts_the_certificate(tmp_path):
    import asyncio

    from trxstation.gateway.api.tls import generate_self_signed, make_ssl_context
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    generate_self_signed(["localhost", "127.0.0.1"], cert, key)

    async def scenario():
        async def handle(reader, writer):
            await reader.read(100)
            writer.write(b"bonjour en TLS")
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=make_ssl_context(str(cert), str(key)))
        port = server.sockets[0].getsockname()[1]
        trusting = ssl.create_default_context(cafile=str(cert))
        reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=trusting, server_hostname="localhost")
        writer.write(b"salut")
        assert await reader.read(100) == b"bonjour en TLS"
        writer.close()
        with pytest.raises(ssl.SSLError):                                    # sans confiance dans ce certificat : refus
            await asyncio.open_connection("127.0.0.1", port, ssl=ssl.create_default_context(), server_hostname="localhost")
        server.close()
        await server.wait_closed()
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_certificate_fingerprint_is_the_sha256_of_the_certificate_as_browsers_show_it(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    from trxstation.gateway.api.tls import certificate_fingerprint, generate_self_signed
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    generate_self_signed(["192.168.1.10"], cert, key)
    expected = x509.load_pem_x509_certificate(cert.read_bytes()).fingerprint(hashes.SHA256()).hex().upper()
    fingerprint = certificate_fingerprint(cert)
    assert fingerprint.replace(":", "") == expected and len(fingerprint) == 95     # 32 octets « AB:CD:… »
    with pytest.raises(ValueError):
        certificate_fingerprint(key)                                              # une clé n'est pas un certificat


def test_pairing_lines_show_address_accounts_and_fingerprint_never_a_password(tmp_path):
    from trxstation.gateway.api.tls import certificate_fingerprint
    from trxstation.setup_wizard import _make_certificate, add_client, dummy_config, pairing_lines
    cfg = dummy_config()
    assert "cette machine" in "\n".join(pairing_lines(cfg))                         # 127.0.0.1 : aucun téléphone possible
    add_client(cfg, "phone", "Un mot de passe correct 42")
    _make_certificate(["192.168.1.10"], tmp_path / "tls", cfg)
    cfg.network.gateway_bind = "0.0.0.0"
    text = "\n".join(pairing_lines(cfg, addresses=lambda: ["192.168.1.10"]))
    fingerprint = certificate_fingerprint(cfg.network.tls_cert)
    assert "https://192.168.1.10:8443" in text and "phone" in text
    assert fingerprint[:47] in text and fingerprint[48:] in text
    assert "Un mot de passe correct 42" not in text and "scrypt" not in text
    cfg.network.tls_cert = cfg.network.tls_key = ""
    cfg.network.allow_insecure_http = True
    assert "proxy" in "\n".join(pairing_lines(cfg, addresses=lambda: ["192.168.1.10"]))
