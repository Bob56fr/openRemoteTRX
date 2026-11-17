# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console plein écran (étape 223) : arbre des thèmes et des menus, aide du menu sélectionné, menu déroulé par la
console texte (écran en pause), et choix entre écran plein et console texte au lancement."""
from __future__ import annotations

import asyncio
import contextlib

from trxstation import config as cfgmod
from trxstation import console as module
from trxstation.console import MENU_THEMES, Console, menu_number
from trxstation.console_tui import THEME_ICONS, ConsoleApp, icons_wanted, short_label
from trxstation.setup_wizard import dummy_config


class Runner:
    def __init__(self):
        self.calls = []

    def run(self, cmd, *, admin=False):
        self.calls.append(cmd)
        return 0

    def output(self, cmd):
        return "inactive"


def console(tmp_path, configured=True):
    path = tmp_path / "station.toml"
    if configured:
        path.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    return Console(path, Runner(), ask=lambda _: "", say=print, python="py", installed="0.170.0", home=tmp_path)


def labels(node):
    out = []
    for child in node.children:
        out.append(str(child.label))
        out += labels(child)
    return out


def test_tree_shows_every_theme_with_its_icon_and_every_menu_number(tmp_path):
    con = console(tmp_path)

    async def scenario():
        app = ConsoleApp(con, icons=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            tree = app.query_one("Tree")
            shown = labels(tree.root)
            for number, theme_id, methods in MENU_THEMES:
                assert any(text.startswith(f"{THEME_ICONS[theme_id]} {number}  ") for text in shown), theme_id
                for n in range(1, len(methods) + 1):
                    assert any(text.startswith(f"{number}.{n}  ") for text in shown), f"{number}.{n}"
            assert any("0  Langue" in text for text in shown)
            assert all(not node.is_expanded for node in tree.root.children if node.children)   # thèmes repliés
    asyncio.run(scenario())


def test_highlight_shows_the_help_and_enter_runs_the_menu_like_the_text_console(tmp_path):
    con = console(tmp_path)
    ran = []
    con.run_item = lambda item: ran.append(item[0]) or True

    async def scenario():
        app = ConsoleApp(con, icons=False)
        app.paused = contextlib.nullcontext
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            assert app.query_one("Tree").cursor_node.data == ("theme", "1")   # curseur sur le thème 1
            await pilot.press("enter")                      # thème 1 déplié
            await pilot.pause(0.1)
            await pilot.press("down")                       # 1.1
            await pilot.pause(0.2)
            assert "Démarrer" in str(app.query_one("#help").render())
            await pilot.press("enter")
            await pilot.pause(0.2)
        assert ran == ["1.1"] and app.ran == ["1.1"]
    asyncio.run(scenario())


def test_first_use_highlights_the_wizard(tmp_path):
    con = console(tmp_path, configured=False)

    async def scenario():
        app = ConsoleApp(con, icons=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            node = app.query_one("Tree").cursor_node
            assert node is not None and node.data[0] == menu_number("assistant")
    asyncio.run(scenario())


def test_labels_icons_and_text_mode_choice(tmp_path, monkeypatch):
    assert short_label("Comptes opérateurs (un par appareil : ajouter)") == "Comptes opérateurs"
    assert not icons_wanted({"TERM": "linux"}) and icons_wanted({"TERM": "xterm-256color"})
    assert not icons_wanted({"TRX_CONSOLE_SANS_ICONES": "1"})
    started = []
    monkeypatch.setattr(module.Console, "loop", lambda self: started.append("texte") or 0)
    import trxstation.console_tui as tui
    monkeypatch.setattr(tui, "run_tui", lambda con: started.append("plein") or 0)
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(module.sys.stdout, "isatty", lambda: True, raising=False)
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    assert module.main(["--config", str(path)]) == 0
    assert module.main(["--config", str(path), "--texte"]) == 0
    assert started == ["plein", "texte"]
