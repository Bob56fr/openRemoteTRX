# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console plein écran (Textual) : même arborescence, mêmes menus que la console texte (console.py).

À gauche, l'arbre des thèmes et de leurs menus, avec un pictogramme par thème ; à droite, l'aide du menu sélectionné
(textes de la touche « h », console_help.json) ; en tête, l'état de la station. Entrée sur un menu met l'écran plein
en pause (`App.suspend`) et déroule le menu EXACTEMENT comme la console texte, dans le même terminal (questions, mot de
passe sudo, éditeur, outils lancés), puis revient à l'arbre. Aucune logique de menu n'est recopiée ici.

Même rendu sous Linux et Windows (Windows Terminal, terminaux Linux, SSH compris). `trx-console --texte` garde la
console texte (terminal trop simple, enregistrement d'une session, habitude).
"""
from __future__ import annotations

import contextlib
import os
from collections.abc import Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Static, Tree

from .console import MENU_THEMES, Console

# Pictogrammes des thèmes (identifiants de MENU_THEMES). Console texte Linux (TERM=linux) : sans pictogramme.
THEME_ICONS = {"station": "📡", "hardware": "📻", "safety": "🚨", "access": "🔑", "features": "✨",
               "troubleshooting": "🔧", "updates": "🔄", "expert": "🔬"}
LANGUAGE_ICON = "🌐"
STATUS_EVERY_S = 5.0


def icons_wanted(environ: dict | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("TERM") != "linux" and not env.get("TRX_CONSOLE_SANS_ICONES")


def short_label(label: str) -> str:
    """Libellé court de l'arbre : sans le détail entre parenthèses (il est dans l'aide, à droite)."""
    return label.split(" (", 1)[0].strip() or label


def help_text(con: Console, key: str) -> str:
    """Aide d'un menu ou d'un thème (mêmes textes que la touche « h »), capturée au lieu d'être affichée."""
    lines: list[str] = []
    saved = con.say
    con.say = lines.append
    try:
        con.help_menu(key)
    finally:
        con.say = saved
    return "\n".join(lines).strip()


class ConsoleApp(App):
    """Arbre des menus + aide + état ; un menu se déroule hors de l'écran plein (suspend)."""

    CSS = """
    #status { height: auto; padding: 0 1; background: $boost; }
    #body { height: 1fr; }
    #menus { width: 48%; min-width: 34; border-right: solid $primary; }
    #help-box { padding: 0 1; }
    #hint { height: 1; padding: 0 1; color: $text-muted; }
    """

    def __init__(self, con: Console, *, icons: bool | None = None):
        super().__init__()
        self.con = con
        self.icons = icons_wanted() if icons is None else icons
        self.title = "TRX Console"
        self.ran: list[str] = []                      # menus ouverts (journal de la session, tests)
        self._bindings_ready = False

    # ------------------------------------------------------------------ construction

    def compose(self) -> ComposeResult:
        yield Static(id="status")
        with Horizontal(id="body"):
            yield Tree("TRX Console", id="menus")
            with VerticalScroll(id="help-box"):
                yield Static(id="help")
        yield Static(id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.bind("q", "quit", description=self.con.t("tui.quit"))
        self.bind("r", "refresh_all", description=self.con.t("tui.refresh"))
        self.refresh_all()
        self.set_interval(STATUS_EVERY_S, self.refresh_status)
        self.query_one(Tree).focus()

    def refresh_all(self) -> None:
        self.refresh_status()
        self.build_tree()
        self.query_one("#hint", Static).update(self.con.t("tui.hint"))

    def action_refresh_all(self) -> None:
        self.refresh_all()

    def refresh_status(self) -> None:
        try:
            header = self.con.header()
        except Exception as exc:                       # l'en-tête ne doit jamais faire tomber l'écran
            header = f"TRX Console ({exc})"
        self.query_one("#status", Static).update(Text.from_ansi(header.strip("\n")))

    def icon(self, theme_id: str) -> str:
        return (THEME_ICONS.get(theme_id, "•") + " ") if self.icons else ""

    def build_tree(self) -> None:
        tree = self.query_one(Tree)
        tree.clear()
        tree.show_root = False
        t = self.con.t
        tree.root.add_leaf(f"{LANGUAGE_ICON + ' ' if self.icons else ''}0  {t('menu.language')}",
                           data=("0", t("menu.language"), self.con.language))
        items = {key: (key, label, fn) for key, label, fn in self.con.items}
        first = None
        for number, theme_id, methods in MENU_THEMES:
            title = self.con.menu_label(number, t(f"theme.{theme_id}"))
            # Thèmes repliés : la hiérarchie se lit d'un coup d'œil ; Entrée ou → déplie.
            node = tree.root.add(f"{self.icon(theme_id)}{number}  {title}", data=("theme", number), expand=False)
            for n in range(1, len(methods) + 1):
                key = f"{number}.{n}"
                _, label, fn = items[key]
                leaf = node.add_leaf(f"{key}  {self.con.menu_label(key, short_label(label))}", data=(key, label, fn))
                if first is None and not self.con.config.exists() and methods[n - 1] == "assistant":
                    first = leaf
        tree.root.expand()
        if first is not None:                          # première utilisation : l'assistant en évidence
            first.parent.expand()
        target = first if first is not None else tree.root.children[1]      # sinon le thème 1 (après « Langue »)
        self.call_after_refresh(tree.move_cursor, target)

    # ------------------------------------------------------------------ arbre

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data
        if not data:
            return
        if data[0] == "theme":
            text = help_text(self.con, data[1])
        elif data[0] == "0":
            text = self.con.t("menu.language")
        else:
            text = help_text(self.con, data[0])
        self.query_one("#help", Static).update(text)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not data or data[0] == "theme":
            return
        self.run_menu(data)

    def paused(self) -> contextlib.AbstractContextManager:
        """Écran plein en pause le temps d'un menu (remplacé dans les tests)."""
        return self.suspend()

    def run_menu(self, item: tuple[str, str, Callable[[], None]]) -> None:
        key, label, fn = item
        self.ran.append(key)
        with self.paused():
            print("\033[2J\033[H", end="")             # écran propre (terminaux VT, Windows Terminal compris)
            print(f"\n=== {key}  {label} ===")
            if key == "0":
                try:
                    fn()
                except EOFError:
                    pass
                keep = True
            else:
                keep = self.con.run_item(item)
        if not keep:                                    # terminal fermé pendant une question
            self.exit(0)
            return
        self.refresh_all()                               # langue, nouvelle version, état


def run_tui(con: Console) -> int:
    ConsoleApp(con).run()
    return 0
