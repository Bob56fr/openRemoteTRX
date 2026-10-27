# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Interface Textual de trx-monitor. Couche mince : tout le contenu vient de model.py.

Touches : s = STOP TX (coupe l'émission), q = quitter.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer, Header, RichLog, Static

from .model import EventLog, Panel, Snapshot, build_panels
from .source import StatusSource

STYLES = {"ok": "green", "warn": "yellow", "bad": "bold red", "dim": "dim", "info": ""}


def render_markup(panel: Panel) -> str:
    width = max(len(r.label) for r in panel.rows)
    lines = []
    for row in panel.rows:
        style = STYLES.get(row.level, "")
        text = escape(row.text)
        text = f"[{style}]{text}[/]" if style else text
        lines.append(f"{escape(row.label).ljust(width)} : {text}")
    return "\n".join(lines)


class MonitorApp(App):
    TITLE = "trx-monitor"
    CSS = """
    #top { layout: grid; grid-size: 2; grid-gutter: 0 1; height: auto; }
    .panel { border: round $primary; padding: 0 1; height: auto; }
    #flash { height: 1; padding: 0 1; }
    #log { height: 1fr; border: round $secondary; }
    """
    BINDINGS = [Binding("s", "stop_tx", "STOP TX", priority=True), Binding("q", "quit", "Quitter")]

    def __init__(self, source: StatusSource, stop_tx: Callable[[], tuple[bool, str]], interval_s: float = 0.25):
        super().__init__()
        self.source, self.stop_tx, self.interval_s = source, stop_tx, interval_s
        self.events = EventLog()

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="top"):
            for key in ("radio", "audio", "connexion", "sante", "materiel"):
                yield Static("", id=key, classes="panel")
        yield Static("", id="flash")
        yield RichLog(id="log", wrap=True, markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()
        self.set_interval(self.interval_s, self.refresh_view)

    def refresh_view(self) -> None:
        snapshot: Snapshot = self.source.poll()
        for panel in build_panels(snapshot):
            widget = self.query_one(f"#{panel.key}", Static)
            widget.border_title = panel.title
            widget.update(render_markup(panel))
        log = self.query_one("#log", RichLog)
        for line in self.events.observe(snapshot):
            log.write(line)

    async def action_stop_tx(self) -> None:
        ok, message = await asyncio.to_thread(self.stop_tx)   # I/O réseau : hors de la boucle d'affichage
        self.query_one("#flash", Static).update(f"[{'green' if ok else 'bold red'}]{escape(message)}[/]")
        self.query_one("#log", RichLog).write(f"STOP TX : {message}")


def run_tui(source: StatusSource, stop_tx: Callable[[], tuple[bool, str]]) -> int:
    MonitorApp(source, stop_tx).run()
    return 0
