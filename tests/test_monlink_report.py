# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Monitoring inter-stations, lot R4 : rapport de dépannage masqué, journaux pendant l'assistance, alertes ntfy de la
station qui aide (absence de nouvelles, retour, événement critique), menu 6.5 choix 6, 7 et 10."""
from __future__ import annotations

import asyncio
import io
import json
import re
import zipfile

import pytest

from trxstation.devtools.fake_monlink_relay import FakeMonRelay
from trxstation.monlink import engine as eng_mod, snapshot
from trxstation.monlink.engine import ActionRefused, Engine
from trxstation.monlink.identity import Identity
from trxstation.monlink.redact import Redactor
from trxstation.monlink.store import Store
from trxstation.status import GatewayStatus, read_status, write_status

NOW = 1_795_100_000
SECRET_ZIP_FILES = {
    "diagnostic.txt": "machine minix-bzh : port /dev/serial/by-id/usb-Icom_IC-7300_13003336-if00 OK\n",
    "station.toml": 'notify_url = "https://ntfy.sh/sujet-perso"\npassword_hash = "***"\n',
    "journal.txt": "connexion depuis 86.247.12.34, compte bob, /home/bob/.trx\n",
    "../evasion.txt": "rien\n",
}


def secret_zip(extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in {**SECRET_ZIP_FILES, **(extra or {})}.items():
            z.writestr(name, text)
    return buf.getvalue()


class Clock:
    def __init__(self) -> None:
        self.t = float(NOW)

    def __call__(self) -> float:
        return self.t


class Monitor:
    def summary(self) -> dict:
        return {"cpu": 5}


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def alert(self, code, detail="", *, key="", **contexte):
        self.sent.append((code, contexte))
        return True


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def pair(tmp_path):
    """HELPER (avec alertes) et AIDED (avec un rapport plein de secrets), appairés, profil « diagnostic »."""
    clock = Clock()
    relay = FakeMonRelay(clock=clock)
    notifier = FakeNotifier()
    reports = {"calls": 0, "data": secret_zip()}

    def make_report():
        reports["calls"] += 1
        if isinstance(reports["data"], Exception):
            raise reports["data"]
        return reports["data"]

    def make(name, pseudo, **kw):
        folder = tmp_path / name
        folder.mkdir()
        ident = Identity.generate()
        store = Store(folder / "monlink")
        store.data["pseudo"] = pseudo
        e = Engine(store, ident, relay.transport(ident), status_path=folder / "gw.json", state_dir=folder,
                   clock=clock, monitor=Monitor(), known_words={"minix-bzh": "<host>", "bob": "<user>"}, **kw)
        e.folder = folder
        return e

    helper = make("helper", "Dev 56", notifier=notifier)
    aided = make("aided", "F4XYZ", make_report=make_report)
    write_status(aided.status_path, GatewayStatus(pid=1, seq=1, written_at=clock(), ptt={"state": "RX"},
                                                   rig={"connected": True}))
    code = run(helper.invite())["code"]
    run(aided.join(code))
    run(helper.cycle())
    run(helper.confirm(aided.me))
    run(aided.confirm(helper.me, "diagnostic"))
    return helper, aided, clock, relay, notifier, reports


def cycle(clock, *engines, step=61.0):
    async def go():
        clock.t += step
        for e in engines:
            gw = read_status(e.status_path)
            if gw is not None:
                gw.written_at = clock()
                write_status(e.status_path, gw)
            await e.cycle()
    run(go())


def journal(e, **line):
    with (e.folder / "journal-passerelle.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2026-11-21T10:00:00.000Z", "processus": "passerelle", "niveau": "WARNING",
                             "message": "…", **line}) + "\n")


# ------------------------------------------------------------------ masquage du zip
def test_report_zip_is_fully_masked_cut_and_checked():
    red = Redactor(b"sel-de-liaison-16o", known={"minix-bzh": "<host>", "bob": "<user>"})
    out = snapshot.redact_zip(secret_zip(), red)
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        names = z.namelist()
        text = "".join(z.read(n).decode("utf-8") for n in names)
    assert "evasion.txt" in names and not any(".." in n for n in names)          # chemin nettoyé
    for secret in ("minix-bzh", "13003336", "sujet-perso", "86.247.12.34", "/home/bob"):
        assert secret not in text, secret
    import os
    noise = os.urandom(1_500_000).hex()                                         # se compresse mal (comme un journal)
    big = snapshot.redact_zip(secret_zip({"gros.txt": noise + "FIN"}), red, max_bytes=200_000)
    assert len(big) <= 200_000
    with zipfile.ZipFile(io.BytesIO(big)) as z:
        gros = z.read("gros.txt").decode()
    assert gros.startswith(snapshot.CUT_NOTE) and gros.endswith("FIN")         # la fin (le plus récent) est gardée
    with pytest.raises(ValueError):                                             # impossible même réduit
        snapshot.redact_zip(secret_zip({"bruit.txt": noise}), red, max_bytes=1_000)
    with pytest.raises(ValueError):
        snapshot.check_received(secret_zip())                                   # « ../ » refusé à la réception
    snapshot.check_received(out)


# ------------------------------------------------------------------ rapport demandé, accepté, reçu
def test_report_requested_accepted_received_masked_and_kept(pair, caplog):
    import logging
    helper, aided, clock, relay, notifier, reports = pair
    caplog.set_level(logging.INFO)
    run(helper.request_report(aided.me))
    cycle(clock, aided)
    assert aided.view()["links"][0]["request"] == {"snapshot": True, "at": int(clock())}
    assert reports["calls"] == 0                                                # rien sans l'accord de l'opérateur
    run(aided.answer(helper.me, True))
    cycle(clock, aided, helper)
    assert reports["calls"] == 1
    path = run_last(helper, aided.me)
    with zipfile.ZipFile(path) as z:
        text = "".join(z.read(n).decode() for n in z.namelist())
    assert "diagnostic.txt" in zipfile.ZipFile(path).namelist()
    for secret in ("minix-bzh", "13003336", "sujet-perso", "86.247.12.34"):
        assert secret not in text
    assert helper.view()["links"][0]["reports"] == 1
    assert helper.store.links[aided.me]["answer"]["snapshot"] is True
    assert "ORT-7053" in caplog.text
    for m in relay.msgs:
        assert "diagnostic" not in json.dumps(m["msg"])                         # chiffré de bout en bout


def run_last(helper, peer):
    return helper.last_report(peer)["path"]


def test_report_refused_spontaneous_and_failure(pair, caplog):
    import logging
    helper, aided, clock, relay, notifier, reports = pair
    caplog.set_level(logging.INFO)
    run(helper.request_report(aided.me))
    cycle(clock, aided)
    run(aided.answer(helper.me, False))
    cycle(clock, aided, helper)
    assert reports["calls"] == 0 and helper.store.links[aided.me]["answer"]["accepted"] is False
    with pytest.raises(ActionRefused):
        helper.last_report(aided.me)
    assert aided.send_report(helper.me) == {"queued": True}                     # sans demande
    with pytest.raises(ActionRefused) as err:
        helper.send_report(aided.me)
    assert err.value.reason == "role"
    cycle(clock, aided, helper)
    assert reports["calls"] == 1 and helper.last_report(aided.me)["path"].endswith(".zip")
    reports["data"] = OSError("disque plein")
    aided.send_report(helper.me)
    cycle(clock, aided)
    assert "ORT-7054" in caplog.text and aided.problem == ""                    # échec signalé, module intact
    assert aided.store.links[helper.me]["report_due"] is False                  # pas de boucle sur l'échec


def test_only_five_reports_are_kept(pair):
    helper, aided, clock, relay, notifier, reports = pair
    for _ in range(7):
        aided.send_report(helper.me)
        cycle(clock, aided, helper, step=2)
    assert len(helper.store.links[aided.me]["reports"]) == 5
    assert len(list((helper.store.folder / "rapports").glob("*.zip"))) == 5


# ------------------------------------------------------------------ journaux pendant l'assistance
def test_log_lines_only_during_assistance(pair):
    helper, aided, clock, relay, notifier, reports = pair
    cycle(clock, aided, helper)
    journal(aided, message="avertissement sans code, compte bob")
    cycle(clock, aided, helper)
    assert helper.store.recent(aided.me, ("lg",)) == []                          # hors assistance : rien
    run(helper.request_assist(aided.me, 3600))
    cycle(clock, aided)
    run(aided.answer(helper.me, True))
    journal(aided, message="avertissement sans code, compte bob")
    cycle(clock, aided, helper, step=121)
    lines = helper.store.recent(aided.me, ("lg",))
    assert lines and "avertissement sans code" in json.dumps(lines)
    assert "bob" not in json.dumps(lines)                                        # masqué


# ------------------------------------------------------------------ alertes de la station qui aide
def test_silence_alert_once_then_return_and_none_during_pause(pair):
    helper, aided, clock, relay, notifier, reports = pair
    cycle(clock, aided, helper)
    assert not notifier.sent
    cycle(clock, helper, step=16 * 60)                                           # 3 rythmes de 5 min sans nouvelles
    assert [c for c, _ in notifier.sent] == ["ORT-7050"]
    assert helper.view()["links"][0]["silent"] is True
    cycle(clock, helper, step=20 * 60)
    assert [c for c, _ in notifier.sent] == ["ORT-7050"]                         # pas de répétition
    cycle(clock, aided, helper, step=1)
    assert [c for c, _ in notifier.sent] == ["ORT-7050", "ORT-7051"]
    assert notifier.sent[1][1]["minutes"] >= 15
    run(aided.pause(helper.me, True))
    cycle(clock, helper, step=1)
    cycle(clock, helper, step=3600)
    assert [c for c, _ in notifier.sent] == ["ORT-7050", "ORT-7051"]             # en pause : aucune alerte


def test_critical_event_alerts_once_per_code_and_the_hourly_ceiling(pair):
    helper, aided, clock, relay, notifier, reports = pair
    cycle(clock, aided, helper)
    journal(aided, code="ORT-5024", gravite="critique", titre="TOT absolu dépassé")
    journal(aided, code="ORT-5024", gravite="critique", titre="TOT absolu dépassé")
    journal(aided, code="ORT-2104", gravite="erreur", titre="CAT lent")
    cycle(clock, aided, helper, step=1)
    sent = [(c, x.get("code_recu")) for c, x in notifier.sent]
    assert sent == [("ORT-7052", "ORT-5024")]                                    # une fois ; l'erreur n'alerte pas
    helper._alerted.clear()
    for i in range(30):
        helper._alert("ORT-7052", f"k{i}", station="x", code_recu="ORT-0000", titre="t")
    assert len(notifier.sent) == 1 + eng_mod.ALERTS_PER_HOUR - 1                 # plafond de 20 par heure



def test_safe_mode_reason_reaches_the_helper_and_reminders_are_grouped(pair):
    """Étape 338 : la RAISON du mode sûr (message « ALERTE ORT-8008 <raison> ») part dans l'alerte ORT-7052 et
    s'affiche ; les rappels toutes les 10 min ne masquent plus la panne d'origine."""
    helper, aided, clock, relay, notifier, reports = pair
    cycle(clock, aided, helper)
    journal(aided, code="ORT-8001", gravite="erreur", titre="Redémarrage", message="ORT-8001 passerelle relancée")
    for _ in range(7):
        journal(aided, code="ORT-8008", gravite="critique", titre="Mode sûr : station en réception, accès coupé",
                message="ALERTE ORT-8008 pannes persistantes : rigctld")
    cycle(clock, aided, helper, step=1)
    (code, ctx), = notifier.sent
    assert code == "ORT-7052" and ctx["texte_recu"] == "pannes persistantes : rigctld"
    events = helper.received(aided.me, 2)
    assert [(e["content"]["code"], e["count"], e["text"]) for e in events] == [
        ("ORT-8008", 7, "pannes persistantes : rigctld"), ("ORT-8001", 1, "passerelle relancée")]
    assert len(helper.received(aided.me, 1)) == 1


def test_event_text_drops_the_code_and_a_message_equal_to_the_title():
    assert eng_mod.event_text({"code": "ORT-8008", "message": "ALERTE ORT-8008 trop de redémarrages"}) ==         "trop de redémarrages"
    assert eng_mod.event_text({"code": "ORT-2104", "titre": "CAT lent", "message": "CAT lent"}) == ""
    assert eng_mod.event_text({"code": "ORT-2104"}) == ""
    rows = [{"content": {"code": "A", "ts": "3"}}, {"content": {"code": "A", "ts": "2"}},
            {"content": {"code": "B", "ts": "1"}}, {"content": {"code": "A", "ts": "0"}}]
    out = eng_mod.group_events(rows, 10)
    assert [(e["content"]["code"], e["count"], e["first"]) for e in out] == [("A", 2, "2"), ("B", 1, "1"), ("A", 1, "0")]


# ------------------------------------------------------------------ menu 6.5 (choix 6, 7, 10)
def test_console_report_round_trip(tmp_path, monkeypatch):
    from test_monlink_console import Clock as CClock, Station          # module voisin (tests/ dans sys.path)
    clock = CClock()
    relay = FakeMonRelay(clock=clock)
    helper, aided = Station(tmp_path, "helper", relay, clock), Station(tmp_path, "aided", relay, clock)
    aided.service.engine.make_report = lambda: secret_zip({"../x": ""} and {})
    helper.menu("1", "Dev 56")
    aided.menu("1", "F4XYZ")
    code = re.search(r"([0-9A-Z]{5}-[0-9A-Z]{5})", helper.menu("3")).group(1)
    aided.menu("4", code, "oui", "2", "non")
    helper.cycle()
    helper.menu("5", "oui")
    text = helper.menu("6", "2")                                                # demander le rapport
    assert "doit l'accepter" in text
    clock.t += 61
    aided.cycle()
    text = aided.menu("7", "oui")
    assert "entièrement masqué" in text and "Rapport en préparation" in text
    clock.t += 61
    aided.cycle()
    helper.cycle()
    assert "1 rapport(s) reçu(s)" in helper.menu()
    desktop = tmp_path / "Bureau"
    desktop.mkdir()
    monkeypatch.setattr("trxstation.report.desktop_dir", lambda *a, **k: desktop)
    text = helper.menu("10")
    assert "Rapport copié" in text and list(desktop.glob("rapport-F4XYZ-*.zip"))


# ------------------------------------------------------------------ lignes INFO pendant l'assistance (étape 215)
def test_the_aided_station_writes_and_clears_the_assistance_deadline(pair):
    from trxstation.logsetup import ASSIST_FLAG
    helper, aided, clock, relay, notifier, reports = pair
    flag = aided.state_dir / ASSIST_FLAG
    assert not flag.exists()
    run(helper.request_assist(aided.me, 3600))
    cycle(clock, aided)
    run(aided.answer(helper.me, True))
    assert abs(float(flag.read_text(encoding="ascii")) - (clock() + 3600)) < 2
    clock.t += 3601
    run(aided.cycle())
    assert not flag.exists()                                               # échéance passée : effacé
    run(helper.request_assist(aided.me, 3600))
    cycle(clock, aided)
    run(aided.answer(helper.me, True))
    assert flag.exists()
    run(aided.end(helper.me))
    assert not flag.exists()                                               # fin de liaison : effacé tout de suite
