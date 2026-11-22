# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Témoin de marche du superviseur : arrêt précédent propre ou non (étape 355)."""
from __future__ import annotations

import json

from trxstation.errors import codes
from trxstation.supervisor.runmark import MARK_FILE, REFRESH_S, RunMark


class Clock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def mark(tmp_path, clock, boot=500_000.0, platform="linux"):
    return RunMark(tmp_path, clock=clock, boot=lambda: boot, platform=platform)


def test_clean_stop_leaves_nothing_and_next_start_is_quiet(tmp_path):
    clock = Clock()
    m = mark(tmp_path, clock)
    assert m.start() is None and (tmp_path / MARK_FILE).exists()
    m.clean_stop()
    assert not (tmp_path / MARK_FILE).exists()
    assert mark(tmp_path, clock).start() is None


def test_supervisor_killed_while_the_machine_kept_running(tmp_path):
    clock = Clock()
    m = mark(tmp_path, clock)
    m.start()
    clock.t += REFRESH_S + 5
    m.refresh()                                                  # dernier signe de vie
    last = clock.t
    clock.t += 3600                                              # tué ; relancé une heure plus tard, même démarrage
    unclean = mark(tmp_path, clock).start()
    assert unclean is not None and not unclean.machine and unclean.last_seen == last


def test_machine_stopped_abruptly_is_seen_on_linux_only(tmp_path):
    clock = Clock()
    mark(tmp_path, clock, boot=500_000.0).start()
    clock.t += 7200
    unclean = mark(tmp_path, clock, boot=1_005_000.0).start()   # nouveau démarrage du système
    assert unclean is not None and unclean.machine
    mark(tmp_path, clock, boot=1_005_000.0).clean_stop()
    mark(tmp_path, clock, boot=500_000.0, platform="win32").start()
    # Windows : une extinction normale du PC tue la station sans prévenir, pas d'alerte pour un autre démarrage
    assert mark(tmp_path, clock, boot=1_005_000.0, platform="win32").start() is None


def test_refresh_writes_at_most_once_a_minute_and_a_broken_mark_still_counts(tmp_path):
    clock = Clock()
    m = mark(tmp_path, clock)
    m.start()
    first = json.loads((tmp_path / MARK_FILE).read_text())["vu"]
    clock.t += 10
    m.refresh()
    assert json.loads((tmp_path / MARK_FILE).read_text())["vu"] == first     # carte SD ménagée
    (tmp_path / MARK_FILE).write_text("{tronq")                              # écriture coupée par la panne
    assert mark(tmp_path, clock).start() is not None


def test_an_unwritable_state_dir_never_blocks(tmp_path):
    blocked = tmp_path / "fichier"
    blocked.write_text("x")
    m = RunMark(blocked, clock=Clock(), boot=lambda: None)
    assert m.start() is None
    m.refresh(force=True)
    m.clean_stop()


def test_both_codes_exist_in_the_catalogue():
    assert codes.ORT_8030 == "ORT-8030" and codes.ORT_8031 == "ORT-8031"
