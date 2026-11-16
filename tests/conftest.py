# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglages communs des tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _console_as_on_debian(monkeypatch):
    """TRX Console pilote la station par systemd (Debian) ou par la tâche planifiée (Windows, étape 201). Les tests de
    la console décrivent le cas Debian sur toutes les machines ; les tests Windows posent IS_WINDOWS = True."""
    from trxstation import console
    monkeypatch.setattr(console, "IS_WINDOWS", False)
