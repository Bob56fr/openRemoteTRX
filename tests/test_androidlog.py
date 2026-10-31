# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Analyse des journaux Android des bêta-testeurs (trx-journal-android) : journaux d'exemple fabriqués."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

from trxstation.devtools import androidlog as al

APP = al.APP

LOG = f"""--------- beginning of main
10-30 14:00:01.100  1000  1500  1520 I ActivityManager: Start proc 4321:{APP}/u0a321 for top-activity {{{APP}/.MainActivity}}
10-30 14:00:02.000  1000  1500  1520 I wifi    : connected SSID: "LaBoxDeJean" bssid aa:bb:cc:dd:ee:ff ip 192.168.1.42
10-30 14:00:03.000 10321  4321  4400 E PeerConnection: ICE failed to 192.168.1.19
10-30 14:00:04.000 10321  4321  4400 E PeerConnection: ICE failed to 192.168.1.19
10-30 14:00:05.000 10200  2222  2223 E AndroidRuntime: FATAL EXCEPTION: main
10-30 14:00:05.000 10200  2222  2223 E AndroidRuntime: Process: com.autre.appli, PID: 2222
10-30 14:00:05.000 10200  2222  2223 E AndroidRuntime: java.lang.IllegalStateException: pas nous
10-30 14:00:06.000 10321  4321  4321 E AndroidRuntime: FATAL EXCEPTION: main
10-30 14:00:06.000 10321  4321  4321 E AndroidRuntime: Process: {APP}, PID: 4321
10-30 14:00:06.000 10321  4321  4321 E AndroidRuntime: android.app.ForegroundServiceStartNotAllowedException: startForegroundService() not allowed
10-30 14:00:06.000 10321  4321  4321 E AndroidRuntime: \tat android.app.ContextImpl.startServiceCommon(ContextImpl.java:1945)
10-30 14:00:06.000 10321  4321  4321 E AndroidRuntime: \tat {APP}.core.RigService.start(RigService.kt:120)
10-30 14:00:06.000 10321  4321  4321 E AndroidRuntime: Caused by: java.lang.RuntimeException: interne
10-30 14:00:06.100  1000  1500  1520 I ActivityManager: Process {APP} (pid 4321) has died: fg  TOP
10-30 14:01:00.000  1000  1500  1520 E ActivityManager: ANR in {APP} ({APP}/.MainActivity)
10-30 14:01:00.000  1000  1500  1520 E ActivityManager: PID: 4400
10-30 14:01:00.000  1000  1500  1520 E ActivityManager: Reason: Input dispatching timed out
10-30 14:02:00.000 10050  3000  3010 E Finsky  : [77] Install failure for com.whatsapp: error 2
10-30 14:02:01.000 10050  3000  3010 E Finsky  : [77] Download error for {APP}: DF-DFERH-01
10-30 14:02:02.000  1000  1500  1600 W PackageManager: Package {APP} signatures do not match previously installed version; ignoring!
10-30 14:02:03.000  1000  1500  1600 E PackageInstaller: Commit of session 12 failed: INSTALL_FAILED_UPDATE_INCOMPATIBLE: user.name@exemple.fr
10-30 14:03:00.000     0  6000  6000 F DEBUG   : *** *** *** *** *** *** *** *** *** *** *** *** *** *** *** ***
10-30 14:03:00.000     0  6000  6000 F DEBUG   : pid: 4500, tid: 4510, name: AudioRecordJava  >>> {APP} <<<
10-30 14:03:00.000     0  6000  6000 F DEBUG   : signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0
10-30 14:03:00.000     0  6000  6000 F DEBUG   :       #00 pc 00000000004a1b2c  /data/app/~~x/lib/arm64/libjingle_peerconnection_so.so
10-30 14:03:00.000     0  6000  6000 F DEBUG   :       #01 pc 0000000000123456  /apex/com.android.runtime/lib64/bionic/libc.so
"""

BUGREPORT_HEAD = f"""========================================================
== dumpstate: 2026-10-30 14:05:00
========================================================
[ro.build.version.release]: [16]
[ro.build.version.sdk]: [36]
[ro.product.manufacturer]: [samsung]
[ro.product.model]: [SM-A556B]
  Package [{APP}] (abc123):
    versionCode=31 minSdk=29 targetSdk=36
    versionName=0.27.0
    installerPackageName=com.android.vending
------ SYSTEM LOG (logcat -v threadtime -v printable -v uid -d *:v) ------
"""


def kinds(a: al.Analyzer) -> dict[str, list[al.Finding]]:
    out: dict[str, list[al.Finding]] = {}
    for f in a.sorted_findings():
        out.setdefault(f.kind, []).append(f)
    return out


def test_parse_line_with_and_without_uid_column() -> None:
    e = al.parse_line("10-30 14:00:03.000 10321  4321  4400 E PeerConnection: ICE failed")
    assert e is not None and (e.pid, e.level, e.tag, e.msg) == (4321, "E", "PeerConnection", "ICE failed")
    e = al.parse_line("2026-10-30 14:00:03.000  4321  4400 W Tag avec espaces : message : deux-points")
    assert e is not None and (e.pid, e.level, e.tag, e.msg) == (4321, "W", "Tag avec espaces", "message : deux-points")
    assert al.parse_line("--------- beginning of main") is None


def test_findings_are_classified_and_explained() -> None:
    a = al.Analyzer()
    a.feed(LOG.splitlines())
    k = kinds(a)
    crash, = k["plantage"]                                   # le plantage d'une autre application est ignoré
    assert "ForegroundServiceStartNotAllowedException" in crash.title
    assert any("RigService.kt:120" in d for d in crash.details) and any("Caused by" in d for d in crash.details)
    assert "arrière-plan" in (crash.advice or "")
    anr, = k["blocage"]
    assert "Reason: Input dispatching timed out" in anr.details
    native, = k["natif"]
    assert native.title.startswith("signal 11") and "WebRTC" in (native.advice or "")
    assert native.details == ["#00 pc 00000000004a1b2c  /data/app/~~x/lib/arm64/libjingle_peerconnection_so.so"]
    assert len(k["arret"]) == 1
    install = "\n".join(f.title for f in k["installation"])
    assert "DF-DFERH-01" in install and "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in install and "signatures" in install
    assert "whatsapp" not in install                         # erreurs du Play Store pour d'autres applications
    errors, = k["erreur"]                                    # deux lignes identiques : un constat, compté 2 fois
    assert errors.count == 2 and errors.title.startswith("PeerConnection : ICE failed")
    assert 4321 in a.pids and 4500 in a.pids


def test_native_frames_hide_android_internals() -> None:
    lines = ["    #00 pc 07b9f0  /apex/com.android.runtime/lib64/bionic/libc.so (abort+160) (BuildId: 8d)",
             "    #01 pc 45c070  /data/app/~~Fx==/com.rfdiy.openremotetrx-B8==/base.apk!libjingle_peerconnection_so.so (offset 0x1)",
             "    #04 pc 288270  /apex/com.android.art/lib64/libart.so (art_quick_generic_jni_trampoline+144)",
             "    #09 pc 45e6a8  /data/app/~~Fx==/com.rfdiy.openremotetrx-B8==/base.apk (offset 0x1) (org.webrtc.ExternalAudioProcessingFactory.destroy+0)"]
    assert al.native_frames(lines) == [
        "#00 pc 07b9f0  /apex/com.android.runtime/lib64/bionic/libc.so (abort+160) (BuildId: 8d)",
        "#01 pc 45c070  base.apk!libjingle_peerconnection_so.so (offset 0x1)",
        "#09 pc 45e6a8  base.apk (offset 0x1) (org.webrtc.ExternalAudioProcessingFactory.destroy+0)"]


def test_report_hides_personal_data() -> None:
    a = al.Analyzer()
    a.feed(LOG.splitlines())
    text = al.text_report(a, "journal.txt")
    page = al.html_report(a, "journal.txt")
    for secret in ("user.name@exemple.fr", "192.168.1.19"):
        assert secret not in text and secret not in page
    assert "[IP]" in text and "[e-mail]" in text
    assert al.redact('SSID: "LaBoxDeJean" ip 10.0.0.2 mac aa:bb:cc:dd:ee:ff') == 'SSID: "[Wi-Fi]" ip [IP] mac [MAC]'
    assert al.redact("127.0.0.1:4532") == "127.0.0.1:4532"


def test_bugreport_zip_with_device_and_tombstone(tmp_path: Path) -> None:
    path = tmp_path / "bugreport-a55-2026-10-30.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("main_entry.txt", "bugreport-a55-2026-10-30.txt")
        z.writestr("bugreport-a55-2026-10-30.txt", BUGREPORT_HEAD + LOG)
        z.writestr("FS/data/tombstones/tombstone_03", f"Timestamp: 2026-10-30 13:00:00\npid: 9, tid: 9, name: x  >>> {APP} <<<\n"
                                                      "Abort message: 'double free'\nsignal 6 (SIGABRT)\n"
                                                      "    #00 pc 0001  libc.so (abort+160)\n")
        z.writestr("FS/data/tombstones/tombstone_04", "pid: 1 >>> com.autre <<<\nsignal 11\n")
    a = al.analyze_file(path)
    text = al.text_report(a, path.name)
    assert "Téléphone : samsung SM-A556B" in text and "Android : 16 (API 36)" in text
    assert "Application : 0.27.0 (versionCode 31), installée par Play Store" in text
    assert [f.title for f in kinds(a)["natif"]] == ["signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0",
                                                    "signal 6 (SIGABRT)"]
    assert kinds(a)["natif"][1].details[0] == "Abort message: 'double free'"


def test_utf16_file_from_powershell(tmp_path: Path) -> None:
    path = tmp_path / "journal-openremotetrx.txt"
    path.write_bytes(LOG.replace("\n", "\r\n").encode("utf-16"))     # « > » de PowerShell 5 : UTF-16 avec BOM
    a = al.analyze_file(path)
    assert a.entries > 20 and "plantage" in kinds(a)
    plain = tmp_path / "journal-sans-bom.txt"
    plain.write_bytes(LOG.encode("utf-16-le"))
    assert al.analyze_file(plain).entries == a.entries


def test_nothing_found_says_so() -> None:
    a = al.Analyzer()
    a.feed(["10-30 14:00:01.100  1000  1500  1520 I ActivityManager: rien", "texte libre"])
    assert "Rien trouvé" in al.text_report(a, "x") and "n'apparaît pas" in al.text_report(a, "x")
    b = al.Analyzer()
    b.feed(["pas un journal"])
    assert "Aucune ligne de journal" in al.text_report(b, "x")


def test_candidates_in_download_folders(tmp_path: Path) -> None:
    dl = tmp_path / "Downloads"
    dl.mkdir()
    (tmp_path / ".config").mkdir()
    fr = tmp_path / "Téléchargements"
    fr.mkdir()
    (tmp_path / ".config" / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Téléchargements"\n', encoding="utf-8")
    for name in ("bugreport-a55.zip", "journal-openremotetrx.txt", "photo.jpg", "Logcat-complet.TXT"):
        (dl / name).write_text("x", encoding="utf-8")
    (fr / "journal-complet.txt").write_text("x", encoding="utf-8")
    dirs = al.download_dirs(tmp_path)
    assert dirs[0] == fr and dl in dirs
    names = sorted(c.name for c in al.local_candidates(dirs))
    assert names == ["Logcat-complet.TXT", "bugreport-a55.zip", "journal-complet.txt", "journal-openremotetrx.txt"]


def test_choose_dialogue(tmp_path: Path) -> None:
    old = al.Candidate("journal-ancien.txt", 1000, 1000.0, path=tmp_path / "a")
    new = al.Candidate("bugreport-neuf.zip", 2_000_000, 2000.0, path=tmp_path / "b")
    said: list[str] = []

    def run(*answers: str, phone: bool = False, cands=(old, new)):
        it = iter(answers)
        return al.choose(list(cands), phone, ask=lambda _q: next(it), say=said.append)

    assert run("") is new                                   # Entrée = oui, le plus récent
    assert run("OUI") is new
    assert run("peut-être", "o") is new                     # réponse incomprise : la question revient
    assert run("n", "2") is old
    assert run("N", "j", phone=True) == "J"
    assert run("n", "") is None
    other = tmp_path / "autre.txt"
    other.write_text("x", encoding="utf-8")
    assert run("n", "introuvable.txt", f'"{other}"') == other
    said.clear()
    assert run(str(other), cands=()) == other               # rien trouvé : le chemin est demandé tout de suite
    assert said[0].startswith("Aucun journal trouvé")


def test_main_with_a_file_writes_the_html_report(tmp_path: Path, capsys) -> None:
    path = tmp_path / "journal-openremotetrx.txt"
    path.write_bytes(LOG.encode("utf-8"))
    assert al.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "Plantage de l'application" in out and "Installation (Play Store)" in out
    page = (tmp_path / "journal-openremotetrx-analyse.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and "ForegroundServiceStartNotAllowedException" in page
    assert al.main([str(tmp_path / "absent.txt")]) == 1
    assert os.path.getsize(path) == len(LOG.encode("utf-8"))   # le journal d'origine n'est pas touché
