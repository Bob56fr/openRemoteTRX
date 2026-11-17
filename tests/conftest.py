# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglages communs des tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_installation(monkeypatch, tmp_path_factory):
    """Aucun chemin par défaut (station.toml, état de la passerelle, dossier d'état) ne doit viser l'installation RÉELLE
    de la machine qui lance les tests (étape 211 : sur le PC « tour radio », où une station est installée, le menu
    Réseau lisait le vrai fichier d'état). Un test qui vérifie les chemins par défaut retire la variable lui-même."""
    monkeypatch.setenv("TRX_REMOTE_HOME", str(tmp_path_factory.mktemp("trx-home")))
    # Préférences de TRX Console (langue, niveau d'affichage : étape 234) : jamais celles du compte qui lance les tests.
    from trxstation import console
    from trxstation.console_web import server
    prefs = tmp_path_factory.mktemp("prefs") / "console.json"
    monkeypatch.setattr(console, "prefs_path", lambda home=None, env=None: prefs)
    monkeypatch.setattr(server, "prefs_path", lambda home=None, env=None: prefs)


@pytest.fixture(autouse=True)
def _console_as_on_debian(monkeypatch):
    """TRX Console pilote la station par systemd (Debian) ou par la tâche planifiée (Windows, étape 201). Les tests de
    la console décrivent le cas Debian sur toutes les machines ; les tests Windows posent IS_WINDOWS = True."""
    from trxstation import console
    monkeypatch.setattr(console, "IS_WINDOWS", False)
