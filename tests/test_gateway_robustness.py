"""Robustesse : fichier d'état tenu ouvert (Windows), port d'écoute impossible à ouvrir."""
from __future__ import annotations

import asyncio
import logging
import socket
import sys

import pytest

from trxstation import status as st
from trxstation.config import ClientAuth
from trxstation.gateway.status import publisher as pub


# ------------------------------------------------------------------ remplacement atomique

def test_replace_retries_while_a_reader_holds_the_file(monkeypatch, tmp_path):
    calls, waits = [], []
    real = st.os.replace

    def busy_twice(src, dst):
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError(13, "Accès refusé")
        real(src, dst)
    monkeypatch.setattr(st.os, "replace", busy_twice)
    src, dst = tmp_path / "a.tmp", tmp_path / "b.json"
    src.write_text("x", encoding="utf-8")
    st.replace_atomic(src, dst, sleep=waits.append)
    assert dst.read_text(encoding="utf-8") == "x" and len(calls) == 3
    assert sum(waits) < 0.05                                                 # attente totale bornée : la boucle asyncio n'est pas gênée


def test_replace_gives_up_after_a_few_tries_and_never_retries_other_errors(monkeypatch, tmp_path):
    calls = []

    def always_busy(src, dst):
        calls.append(1)
        raise PermissionError(13, "Accès refusé")
    monkeypatch.setattr(st.os, "replace", always_busy)
    with pytest.raises(PermissionError):
        st.replace_atomic(tmp_path / "a", tmp_path / "b", sleep=lambda s: None)
    assert len(calls) == st.REPLACE_RETRIES + 1
    calls.clear()

    def missing(src, dst):
        calls.append(1)
        raise FileNotFoundError(2, "absent")
    monkeypatch.setattr(st.os, "replace", missing)
    with pytest.raises(FileNotFoundError):
        st.replace_atomic(tmp_path / "a", tmp_path / "b", sleep=lambda s: None)
    assert len(calls) == 1


def test_failed_status_write_leaves_no_temporary_file(monkeypatch, tmp_path):
    def always_busy(src, dst):
        raise PermissionError(13, "Accès refusé")
    monkeypatch.setattr(st.os, "replace", always_busy)
    monkeypatch.setattr(st.time, "sleep", lambda s: None)
    status = st.GatewayStatus(pid=1, seq=1, written_at=0.0, ptt={"state": "RX"}, rig={})
    with pytest.raises(PermissionError):
        st.write_status(tmp_path / "gateway-status.json", status)
    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------------------------ journal du publieur

class _Snap:
    def to_dict(self):
        return {"state": "RX"}


class _Ctrl:
    clients: list[str] = []

    def snapshot(self):
        return _Snap()


class _Link:
    class state:
        @staticmethod
        def to_dict():
            return {}


def test_publisher_logs_refusals_sparingly(monkeypatch, tmp_path, caplog):
    outcomes = iter([PermissionError(13, "occupé")] * 25 + [None])

    def fake_write(path, status):
        exc = next(outcomes)
        if exc is not None:
            raise exc
    monkeypatch.setattr(pub, "write_status", fake_write)
    publisher = pub.StatusPublisher(tmp_path / "s.json", _Link(), _Ctrl())
    with caplog.at_level(logging.INFO, logger=pub.__name__):
        results = [publisher.write_once() for _ in range(26)]
    assert results == [False] * 25 + [True]
    levels = [r.levelname for r in caplog.records]
    assert levels == ["WARNING", "ERROR", "INFO"]                            # 1er refus, 20e refus, retour : pas 25 lignes
    assert "muette" in caplog.records[1].getMessage() and "25 refus" in caplog.records[2].getMessage()


def test_single_refusal_is_not_followed_by_a_recovery_line(monkeypatch, tmp_path, caplog):
    outcomes = iter([PermissionError(13, "occupé"), None])

    def fake_write(path, status):
        exc = next(outcomes)
        if exc is not None:
            raise exc
    monkeypatch.setattr(pub, "write_status", fake_write)
    publisher = pub.StatusPublisher(tmp_path / "s.json", _Link(), _Ctrl())
    with caplog.at_level(logging.INFO, logger=pub.__name__):
        publisher.write_once(), publisher.write_once()
    assert [r.levelname for r in caplog.records] == ["WARNING"]


# ------------------------------------------------------------------ port d'écoute impossible

def _api_available() -> bool:
    try:
        import aiohttp, aiortc  # noqa: F401
        return True
    except ImportError:
        return False


def _config(bind: str, port: int):
    from trxstation.passwords import hash_password
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.network.gateway_bind, cfg.network.gateway_port = bind, port
    cfg.network.allow_insecure_http = True
    cfg.clients = [ClientAuth("phone", password_hash=hash_password("une phrase de passe assez longue"))]
    return cfg


@pytest.mark.skipif(not _api_available(), reason="aiohttp/aiortc absents")
def test_busy_port_keeps_the_gateway_in_receive_only(tmp_path, caplog):
    from trxstation.gateway import main as gw

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    cfg = _config("127.0.0.1", port)
    cfg.supervisor.state_dir = str(tmp_path)
    try:
        with caplog.at_level(logging.ERROR, logger="trx-gateway"):
            manager, runner = asyncio.run(gw._start_api(cfg, None, None, None, None))
    finally:
        blocker.close()
    assert (manager, runner) == (None, None)                                 # pas d'exception : la passerelle continue, en RX
    message = caplog.records[-1].getMessage()
    assert "API NON DÉMARRÉE" in message and f"127.0.0.1:{port}" in message and "déjà pris" in message


@pytest.mark.skipif(not _api_available(), reason="aiohttp/aiortc absents")
def test_address_no_longer_on_this_machine_is_explained(tmp_path, caplog):
    from trxstation.gateway import main as gw

    cfg = _config("192.0.2.1", 8443)                                         # adresse de documentation : jamais sur cette machine
    cfg.supervisor.state_dir = str(tmp_path)
    with caplog.at_level(logging.ERROR, logger="trx-gateway"):
        assert asyncio.run(gw._start_api(cfg, None, None, None, None)) == (None, None)
    message = caplog.records[-1].getMessage()
    assert "192.0.2.1:8443" in message and "n'a peut-être plus l'adresse" in message


def test_bind_hint_wording():
    from trxstation.gateway.main import bind_hint
    assert "déjà pris" in bind_hint("0.0.0.0") and "déjà pris" in bind_hint("127.0.0.1")
    assert "Accès" in bind_hint("192.168.1.21")
