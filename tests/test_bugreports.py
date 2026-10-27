# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""« Signaler un problème » : rapports de la page rangés sur la station, puis joints au rapport de dépannage."""
from __future__ import annotations

import asyncio
import datetime
import json
import zipfile
from types import SimpleNamespace

import pytest

from trxstation.gateway.api.protocol import (MAX_BUG_MESSAGE_BYTES, MAX_BUG_REPORT_CHARS, ProtocolError,
                                             parse_command)
from trxstation.gateway.bugreports import KEEP, MIN_INTERVAL_S, ReportRefused, ReportStore, clean


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def store(tmp_path):
    clock = Clock()
    stamps = iter(datetime.datetime(2026, 10, 28, 10, 0, 0) + datetime.timedelta(seconds=i) for i in range(1000))
    return ReportStore(tmp_path / "reports", version="0.40.0", clock=clock, now=lambda: next(stamps)), clock


def test_report_is_stored_with_a_header_and_cleaned(tmp_path):
    reports, _ = store(tmp_path)
    name = reports.save("phone", "Le waterfall reste noir\r\nligne 2\x1b[31m rouge‮ caché")
    assert name == "page-20261028-100000-phone.txt"
    text = (tmp_path / "reports" / name).read_text(encoding="utf-8")
    assert "# compte : phone" in text and "version 0.40.0" in text
    assert "ligne 2" in text and "\x1b" not in text and "‮" not in text and "\r" not in text


def test_one_report_per_account_every_thirty_seconds_and_old_ones_pruned(tmp_path):
    reports, clock = store(tmp_path)
    reports.save("phone", "un")
    with pytest.raises(ReportRefused) as exc:
        reports.save("phone", "deux")
    assert exc.value.reason == "report_too_soon"
    reports.save("pc", "autre compte : permis")
    for _ in range(KEEP + 5):
        clock.t += MIN_INTERVAL_S
        reports.save("phone", "encore")
    assert len(reports.list()) == KEEP


def test_empty_report_and_odd_account_names(tmp_path):
    reports, _ = store(tmp_path)
    with pytest.raises(ReportRefused):
        reports.save("phone", "   ")
    name = reports.save("../../etc/x", "texte")                              # le nom vient de la session, mais prudence
    assert "/" not in name and ".." not in name and (tmp_path / "reports" / name).is_file()


def test_clean_bounds_the_text():
    assert len(clean("a" * (MAX_BUG_REPORT_CHARS + 50))) == MAX_BUG_REPORT_CHARS


def test_protocol_accepts_a_long_report_only_with_its_own_prefix():
    text = "é" * 20_000                                                       # 40 ko en UTF-8 : au-delà de 2 ko
    raw = json.dumps({"cmd": "bug_report", "id": 3, "text": text}, ensure_ascii=False, separators=(",", ":"))
    assert len(raw.encode("utf-8")) < MAX_BUG_MESSAGE_BYTES
    assert parse_command(raw.encode("utf-8")).params["text"] == text
    disguised = json.dumps({"cmd": "set_mode", "mode": "USB", "pad": text}, ensure_ascii=False, separators=(",", ":"))
    with pytest.raises(ProtocolError, match="too_large"):
        parse_command(disguised)                                              # seule exception : le préfixe exact
    for bad in ({"text": ""}, {"text": 12}, {"text": "x" * (MAX_BUG_REPORT_CHARS + 1)}):
        with pytest.raises(ProtocolError):
            parse_command(json.dumps({"cmd": "bug_report", **bad}, separators=(",", ":")))


def test_session_stores_the_report_under_the_session_account(tmp_path):
    from trxstation.gateway.api.session import ControlSession
    reports, _ = store(tmp_path)
    sent = []
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), config=SimpleNamespace(rig=SimpleNamespace()))
    session = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append, reports=reports)
    asyncio.run(session.on_message(json.dumps({"cmd": "bug_report", "id": 1, "text": "souci", "account": "pirate"})))
    assert sent[-1]["ok"] is True and sent[-1]["name"].endswith("-phone.txt")
    asyncio.run(session.on_message(json.dumps({"cmd": "bug_report", "id": 2, "text": "encore"})))
    assert sent[-1]["ok"] is False and sent[-1]["reason"] == "report_too_soon"
    bare = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append)
    asyncio.run(bare.on_message(json.dumps({"cmd": "bug_report", "id": 3, "text": "x"})))
    assert sent[-1]["reason"] == "reports_unavailable"


def test_troubleshooting_zip_includes_the_page_reports(tmp_path, monkeypatch):
    from trxstation import config as cfgmod
    from trxstation import report as rep
    from trxstation.setup_wizard import dummy_config
    monkeypatch.setattr(rep, "run_all", lambda *a, **k: [])                  # le diagnostic n'est pas l'objet du test
    monkeypatch.setattr(rep, "format_checks", lambda *a, **k: "")
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "state")
    config_path = tmp_path / "station.toml"
    config_path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    reports = ReportStore(tmp_path / "state" / "reports")
    reports.save("phone", "Le waterfall reste noir")
    (tmp_path / "state" / "reports" / "autre.txt").write_text("pas un rapport", encoding="utf-8")

    class Sys:
        def run(self, cmd, timeout=15):
            return 0, ""

        def read_text(self, path):
            try:
                return open(path, encoding="utf-8").read()
            except OSError:
                return None
    path = rep.make_report(tmp_path, sysm=Sys(), config_path=config_path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        page = [n for n in names if n.startswith("rapports-page/")]
        assert len(page) == 1 and "Le waterfall reste noir" in archive.read(page[0]).decode("utf-8")
