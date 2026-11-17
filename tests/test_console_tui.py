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


def test_digits_open_a_theme_then_run_its_menu_like_the_text_console(tmp_path):
    con = console(tmp_path)
    ran = []
    con.run_item = lambda item: ran.append(item[0]) or True
    con.language = lambda: ran.append("langue")

    async def scenario():
        app = ConsoleApp(con, icons=False)
        app.paused = contextlib.nullcontext
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("3")                               # thème 3 ouvert, les autres repliés
            await pilot.pause(0.2)
            tree = app.query_one("Tree")
            assert tree.cursor_node.data == ("theme", "3") and tree.cursor_node.is_expanded
            await pilot.press("2")                               # menu 3.2 lancé
            await pilot.pause(0.2)
            await pilot.press("9")                               # pas de menu 3.9 : rien
            await pilot.pause(0.1)
            await pilot.press("r")                               # retour aux thèmes
            await pilot.pause(0.2)
            assert app.digit_theme is None
            await pilot.press("0")                               # langue
            await pilot.pause(0.2)
            await pilot.press("7", "1")                          # 7.1 au clavier, comme « 7 » puis « 1 »
            await pilot.pause(0.2)
        assert ran == ["3.2", "langue", "7.1"]
    asyncio.run(scenario())


def test_plus_and_minus_expand_and_collapse_every_theme(tmp_path):
    con = console(tmp_path)

    async def scenario():
        app = ConsoleApp(con, icons=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            themes = [n for n in app.query_one("Tree").root.children if n.children]
            await pilot.press("plus")
            await pilot.pause(0.2)
            assert all(n.is_expanded for n in themes) and len(themes) == len(MENU_THEMES)
            await pilot.press("minus")
            await pilot.pause(0.2)
            assert not any(n.is_expanded for n in themes)
    asyncio.run(scenario())


def test_when_everything_is_unfolded_a_digit_still_chooses_a_theme_first(tmp_path):
    con = console(tmp_path)
    ran = []
    con.run_item = lambda item: ran.append(item[0]) or True

    async def scenario():
        app = ConsoleApp(con, icons=False)
        app.paused = contextlib.nullcontext
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("plus")                             # tout déplié, curseur sur le thème 1
            await pilot.pause(0.2)
            await pilot.press("4")                                # thème 4, PAS le menu 1.4
            await pilot.pause(0.2)
            assert ran == [] and app.query_one("Tree").cursor_node.data == ("theme", "4")
            await pilot.press("3")
            await pilot.pause(0.2)
        assert ran == ["4.3"]
    asyncio.run(scenario())


def test_keypad_plus_and_minus_work_by_their_character(tmp_path):
    con = console(tmp_path)

    async def scenario():
        from textual import events
        app = ConsoleApp(con, icons=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            themes = [n for n in app.query_one("Tree").root.children if n.children]
            app.on_key(events.Key("kp_add", "+"))                 # nom de touche inconnu, caractère « + »
            await pilot.pause(0.2)
            assert all(n.is_expanded for n in themes)
            app.on_key(events.Key("kp_subtract", "-"))
            await pilot.pause(0.2)
            assert not any(n.is_expanded for n in themes)
    asyncio.run(scenario())


def test_mouse_hover_shows_the_help_one_click_chooses_a_second_click_opens(tmp_path):
    con = console(tmp_path)
    ran = []
    con.run_item = lambda item: ran.append(item[0]) or True

    async def scenario():
        app = ConsoleApp(con, icons=False)
        app.paused = contextlib.nullcontext
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("enter")                            # thème 1 déplié : lignes 2 à 5 = 1.1 à 1.4
            await pilot.pause(0.2)
            help_box = app.query_one("#help")
            await pilot.hover("#menus", offset=(12, 3))           # survol de 1.2
            await pilot.pause(0.2)
            assert "Arrêter la station" in str(help_box.render()) and ran == []
            await pilot.click("#menus", offset=(12, 4))           # un clic sur 1.3 : choisi, rien de lancé
            await pilot.pause(0.2)
            assert ran == [] and app.query_one("Tree").cursor_node.data[0] == "1.3"
            assert "Tableau de bord" in str(help_box.render())
            await pilot.click("#menus", offset=(12, 4))           # second clic : ouvert
            await pilot.pause(0.2)
        assert ran == ["1.3"]
    asyncio.run(scenario())
