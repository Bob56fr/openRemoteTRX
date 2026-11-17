# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglage du Cluster DX sans éditer de fichier (TRX Console, menu 5.1).

    python -m trxstation.cluster.setup --config /etc/trx-remote/station.toml

- Première fois : questions de FLUX (clusters radioamateurs, RBN, cibistes) et
  de MODES suivis ; les sources correspondantes sont proposées.
- Ajouter, modifier, supprimer, monter en priorité, activer/désactiver une source.
- Mot de passe ou clé saisis en masqué, écrits SEULEMENT dans secrets.toml.
- TEST OBLIGATOIRE avant d'enregistrer une source nouvelle ou modifiée
  (connexion, identification, un spot en 60 s) ; un échec n'est gardé que
  sur demande explicite.
- Filtres (bandes, continents, liste noire) et durées de vie.
- Rien n'est écrit avant « Enregistrer » ; station.toml est validée avant.

Textes en quatre langues (lot L3) : `trxstation/i18n/cluster.<langue>.json`, langue de TRX Console (`TRX_LANG`).
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import getpass
import re
import sys
from pathlib import Path
from typing import Callable

from .. import config as cfgmod
from .. import formhint, secretstore
from ..answers import yes_no
from ..i18n import tool_translator
from ..paths import default_config_path
from .bandplan import BAND_NAMES, MODES
from .cty import CONTINENTS
from .feed import Source
from .servers import KNOWN, KnownServer
from .tester import SourceReport, check_source
from .text import check_own_call, own_call_problem

KIND_LABELS = {"telnet": "cluster", "rbn": "RBN", "web": "CB (web)"}
# (type de source, cochée par défaut) ; libellé : clé `flux.<type>` du catalogue
FLUX = (("telnet", True), ("rbn", False), ("web", False))
_HOSTPORT = re.compile(r"([A-Za-z0-9.-]{1,253}):(\d{1,5})")


def _t(key: str, **fields) -> str:
    """Texte montré à l'opérateur, dans la langue de l'outil (lot L3 : `TRX_LANG` posée par TRX Console, sinon
    menu 0, sinon le système) ; catalogues `trxstation/i18n/cluster.<langue>.json`, le français en référence.
    Lu À CHAQUE APPEL (jamais au chargement du module : les tests changent la langue après l'import)."""
    return tool_translator("cluster")(key, **fields)


def flux_label(kind: str) -> str:
    return _t(f"flux.{kind}")


def mode_label(mode: str) -> str:
    return _t(f"mode.{mode}")


def run_check(src: Source, call: str, password: str | None) -> SourceReport:
    return asyncio.run(check_source(src, call, password))


class ClusterEditor:
    def __init__(self, cfg: cfgmod.Config, config_path: Path, *, ask: Callable[[str], str] = input,
                 say: Callable[[str], None] = print, ask_secret: Callable[[str], str] = getpass.getpass,
                 check: Callable[[Source, str, str | None], SourceReport] = run_check,
                 secrets: dict[str, str] | None = None,
                 write: Callable[[cfgmod.Config, dict[str, str] | None], None] | None = None) -> None:
        self.cfg = copy.deepcopy(cfg)
        self.c = self.cfg.cluster
        self.config_path = config_path
        self.ask, self.say, self.ask_secret, self.check = ask, say, ask_secret, check
        self.secrets = dict(secrets or {})
        self.secrets_changed = False
        self.write = write or self._write
        self.dirty = False

    # ------------------------------------------------------------------ saisie

    def yes(self, question: str, default: bool) -> bool:
        while True:
            text = _t("yesno.prompt", question=question,
                      choices=_t("yesno.default_yes") if default else _t("yesno.default_no"))
            formhint.emit("yesno", question.strip(), text, default=default)       # console web : Oui / Non
            answer = self.ask(text).strip()
            if not answer:
                return default
            if yes_no(answer) is not None:
                return bool(yes_no(answer))
            self.say(_t("yesno.retry"))

    def choose(self, question: str, count: int, *, allow_empty: bool = True) -> int | None:
        """Numéro de 1 à count (renvoyé à partir de 0) ; Entrée = None."""
        while True:
            answer = self.ask(question).strip()
            if not answer and allow_empty:
                return None
            if answer.isdigit() and 1 <= int(answer) <= count:
                return int(answer) - 1
            self.say(_t("choose.range", count=count))

    # ------------------------------------------------------------------ affichage

    def describe(self, s: cfgmod.ClusterSource) -> str:
        where = s.url if s.type == "web" else f"{s.host}:{s.port}"
        pw = _t("describe.pw_set") if s.secret and s.secret in self.secrets else (
            _t("describe.pw_missing") if s.secret else _t("describe.pw_none"))
        prio = _t("describe.priority", priority=s.priority) if s.type == "telnet" else ""
        state = f"{_t('describe.on') if s.enabled else _t('describe.off'):<8}"
        return f"[{state}] {s.name:<14} {KIND_LABELS[s.type]:<9} {where:<34} {prio}{pw}"

    def show(self) -> None:
        c = self.c
        none = _t("show.none")
        self.say(_t("show.header", state=_t("show.on") if c.enabled else _t("show.off"),
                    call=c.call or none, cb_call=c.cb_call or none))
        if not c.source:
            self.say(_t("show.no_source"))
        for i, s in enumerate(self.ordered(), start=1):
            self.say(f"  {i}. {self.describe(s)}")
        modes = " ".join(c.modes) if c.modes else _t("show.all_modes", modes=" ".join(MODES))
        self.say(_t("show.modes", modes=modes))
        self.say(_t("show.filters", bands=" ".join(c.bands) or _t("show.all_bands"),
                    continents=" ".join(c.continents) or _t("word.all"),
                    blacklist=" ".join(c.blacklist) or _t("word.empty")))
        self.say(_t("show.ttl", ttl=f"{c.ttl_min:g}", rbn_ttl=f"{c.rbn_ttl_min:g}"))

    def ordered(self) -> list[cfgmod.ClusterSource]:
        order = {"telnet": 0, "rbn": 1, "web": 2}
        return sorted(self.c.source, key=lambda s: (order.get(s.type, 9), s.priority, s.name))

    # ------------------------------------------------------------------ questions de flux

    def flux(self) -> None:
        """Quels spots recevoir, et dans quels modes ; ajoute ou désactive les sources correspondantes."""
        self.say(_t("flux.title"))
        wanted = {}
        for kind, default in FLUX:
            has = [s for s in self.c.source if s.type == kind]
            current = any(s.enabled for s in has) if has else default
            wanted[kind] = self.yes("  " + flux_label(kind), current)
        self.say(_t("flux.modes_title"))
        followed = []
        for mode in MODES:
            default = (mode in self.c.modes) if self.c.modes else (mode != "CW" or wanted["rbn"])
            if self.yes("  " + mode_label(mode), default):
                followed.append(mode)
        if not followed:
            self.say(_t("flux.no_mode"))
        if wanted["rbn"] and followed and "CW" not in followed:
            self.say(_t("flux.rbn_cw_only"))
            if self.yes("  " + _t("flux.add_cw"), True):
                followed.append("CW")
        self.c.modes = [] if set(followed) in (set(MODES), set()) else [m for m in MODES if m in followed]
        self.dirty = True
        for kind, _ in FLUX:
            has = [s for s in self.c.source if s.type == kind]
            for s in has:
                s.enabled = wanted[kind]
            if wanted[kind] and not has:
                self.say(_t("flux.adding", kind=KIND_LABELS[kind]))
                self.add_source(kind)
                if kind == "telnet" and any(s.type == "telnet" for s in self.c.source) \
                        and self.yes(_t("flux.backup"), True):
                    self.add_source("telnet")

    # ------------------------------------------------------------------ sources

    def ensure_cb_call(self) -> None:
        """Indicatif de cibiste, facultatif (la page clusterdx.org se lit sans compte)."""
        if self.c.cb_call:
            return
        while True:
            answer = self.ask(_t("call.cb_ask")).strip().upper()
            if not answer:
                return
            if own_call_problem(answer):
                self.say(own_call_problem(answer))
                continue
            self.c.cb_call = answer
            self.dirty = True
            return

    def ensure_call(self) -> bool:
        if self.c.call:
            return True
        while True:
            answer = self.ask(_t("call.ask")).strip().upper()
            if not answer:
                return False
            try:
                self.c.call = check_own_call(answer)
                self.dirty = True
                return True
            except ValueError as exc:
                self.say(str(exc))

    def _free_name(self, base: str) -> str:
        names = {s.name for s in self.c.source}
        base = re.sub(r"[^A-Za-z0-9_-]", "-", base)[:28] or "source"
        name, n = base, 2
        while name in names:
            name, n = f"{base}-{n}", n + 1
        return name

    def pick_server(self, kind: str) -> tuple[str, str, int, str] | None:
        """(nom, hôte, port, url) choisi dans la liste ou saisi ; None = abandon."""
        known = [k for k in KNOWN if k.kind == kind]
        used = {(s.host, s.port, s.url) for s in self.c.source}
        known = [k for k in known if (k.host, k.port, k.url) not in used]
        for i, k in enumerate(known, start=1):
            self.say(f"  {i}. {k.name:<12} {k.address:<34} {k.where}")
        self.say(_t("server.other", n=len(known) + 1))
        idx = self.choose(_t("ask.choice_or_cancel"), len(known) + 1)
        if idx is None:
            return None
        if idx < len(known):
            k: KnownServer = known[idx]
            return k.name, k.host, k.port, k.url
        return self.ask_address(kind)

    def ask_address(self, kind: str, current: str = "") -> tuple[str, str, int, str] | None:
        while True:
            hint = _t("ask.enter_keeps", current=current) if current else ""
            if kind == "web":
                url = self.ask(_t("address.url_ask", hint=hint)).strip() or current
                if not url:
                    return None
                if re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?(/[^\s\"']*)?", url):
                    return self._free_name(url.split("/")[2].split(".")[0]), "", 0, url
                self.say(_t("address.url_refused"))
            else:
                text = self.ask(_t("address.hostport_ask", hint=hint)).strip() or current
                if not text:
                    return None
                m = _HOSTPORT.fullmatch(text)
                if m and 1 <= int(m.group(2)) <= 65535:
                    return self._free_name(m.group(1).split(".")[0]), m.group(1), int(m.group(2)), ""
                self.say(_t("address.hostport_refused"))

    def ask_password(self, s: cfgmod.ClusterSource) -> None:
        if s.type == "web":
            return
        has = bool(s.secret and s.secret in self.secrets)
        prompt = _t("password.ask_change") if has else _t("password.ask_new")
        while True:
            if formhint.enabled() and self.ask_secret is getpass.getpass:   # console web : champ masqué de la page
                formhint.emit("password", prompt, prompt)
                value = input(prompt)
            else:
                value = self.ask_secret(prompt)
            if not value:
                return
            if value == "-" and has:
                self.secrets.pop(s.secret, None)
                s.secret = ""
                self.secrets_changed = True
                return
            try:
                secretstore.check_value(value)
            except secretstore.SecretsError as exc:
                self.say(_t("password.refused", reason=exc))
                continue
            s.secret = s.secret or s.name
            self.secrets[s.secret] = value
            self.secrets_changed = True
            return

    def test(self, s: cfgmod.ClusterSource) -> bool:
        """Test obligatoire ; vrai si la source peut être enregistrée."""
        src = Source(s.name, s.type, s.host, s.port, s.priority, True, s.call,
                     self.secrets.get(s.secret) if s.secret else None, s.url)
        while True:
            self.say(_t("test.running", name=s.name, address=src.address))
            report = self.check(src, s.call or self.c.call, src.password)
            self.say(_t("test.result", message=report.message))
            if report.sample:
                self.say(_t("test.sample", sample=report.sample))
            if report.ok:
                return True
            self.say(_t("test.choices"))
            idx = self.choose(_t("ask.choice"), 3, allow_empty=False)
            if idx == 1:
                return self.yes(_t("test.save_anyway"), False)
            if idx == 2:
                return False

    def add_source(self, kind: str | None = None) -> None:
        if kind is None:
            for i, (k, _) in enumerate(FLUX, start=1):
                self.say(f"  {i}. {flux_label(k)}")
            idx = self.choose(_t("source.kind_ask"), len(FLUX))
            if idx is None:
                return
            kind = FLUX[idx][0]
        if kind != "web" and not self.ensure_call():
            self.say(_t("source.no_call"))
            return
        if kind == "web":
            self.ensure_cb_call()
        picked = self.pick_server(kind)
        if picked is None:
            return
        name, host, port, url = picked
        s = cfgmod.ClusterSource(name=self._free_name(name), type=kind, host=host, port=port, url=url,
                                 priority=1 + max((x.priority for x in self.c.source if x.type == kind), default=0))
        if kind != "web":
            answer = self.ask(_t("source.call_ask", call=self.c.call)).strip().upper()
            if answer and answer != self.c.call:
                if not own_call_problem(answer):
                    s.call = answer
                else:
                    self.say(_t("source.call_invalid"))
        before = dict(self.secrets)
        self.ask_password(s)
        if self.test(s):
            self.c.source.append(s)
            self.dirty = True
            self.say(_t("source.added", name=s.name))
        else:
            self.secrets = before
            self.say(_t("source.not_added"))

    def pick_existing(self, prompt_key: str) -> cfgmod.ClusterSource | None:
        items = self.ordered()
        if not items:
            self.say(_t("source.none"))
            return None
        for i, s in enumerate(items, start=1):
            self.say(f"  {i}. {self.describe(s)}")
        idx = self.choose(_t(prompt_key), len(items))
        return None if idx is None else items[idx]

    def modify_source(self) -> None:
        s = self.pick_existing("pick.modify")
        if s is None:
            return
        work = copy.deepcopy(s)
        before = dict(self.secrets)
        current = work.url if work.type == "web" else f"{work.host}:{work.port}"
        picked = self.ask_address(work.type, current)
        if picked is None:
            return
        _, work.host, work.port, work.url = picked
        if work.type != "web":
            answer = self.ask(_t("source.call_ask", call=work.call or self.c.call)).strip().upper()
            if answer:
                work.call = "" if answer == self.c.call else (answer if not own_call_problem(answer) else work.call)
        self.ask_password(work)
        if self.test(work):
            self.c.source[self.c.source.index(s)] = work
            self.dirty = True
            self.say(_t("source.modified"))
        else:
            self.secrets = before
            self.say(_t("source.modify_cancelled"))

    def delete_source(self) -> None:
        s = self.pick_existing("pick.delete")
        if s is None or not self.yes(_t("source.delete_ask", name=s.name), False):
            return
        self.c.source.remove(s)
        if s.secret and not any(x.secret == s.secret for x in self.c.source):
            self.secrets_changed = self.secrets.pop(s.secret, None) is not None or self.secrets_changed
        self.dirty = True

    def raise_priority(self) -> None:
        s = self.pick_existing("pick.first")
        if s is None:
            return
        if s.type != "telnet":
            self.say(_t("source.priority_clusters_only"))
            return
        group = [s] + [x for x in sorted(self.c.source, key=lambda x: x.priority) if x.type == "telnet" and x is not s]
        for i, x in enumerate(group, start=1):
            x.priority = i
        self.dirty = True

    def toggle_source(self) -> None:
        s = self.pick_existing("pick.toggle")
        if s is not None:
            s.enabled = not s.enabled
            self.dirty = True

    def _ask_list(self, question: str, allowed: tuple[str, ...], current: list[str]) -> list[str]:
        while True:
            answer = self.ask(_t("list.ask", question=question, allowed=" ".join(allowed),
                                 current=" ".join(current) or _t("word.all"))).strip().upper()
            if not answer:
                return current
            if answer == "-":
                return []
            items = answer.replace(",", " ").split()
            bad = [x for x in items if x not in {a.upper() for a in allowed}]
            if not bad:
                lookup = {a.upper(): a for a in allowed}
                return [lookup[x] for x in dict.fromkeys(items)]
            self.say(_t("list.unknown", items=" ".join(bad)))

    def filters(self) -> None:
        c = self.c
        c.bands = self._ask_list(_t("filters.bands"), BAND_NAMES, c.bands)
        c.continents = self._ask_list(_t("filters.continents"), CONTINENTS, c.continents)
        answer = self.ask(_t("filters.blacklist_ask",
                             current=" ".join(c.blacklist) or _t("word.empty"))).strip().upper()
        if answer == "-":
            c.blacklist = []
        elif answer:
            items = answer.replace(",", " ").split()
            good = [x for x in items if re.fullmatch(r"[A-Z0-9/]{1,15}\*?", x)]
            if len(good) != len(items):
                self.say(_t("filters.blacklist_bad"))
            c.blacklist = good
        for key, label in (("ttl_min", "filters.ttl"), ("rbn_ttl_min", "filters.rbn_ttl")):
            answer = self.ask(_t("filters.ttl_ask", label=_t(label),
                                 current=f"{getattr(c, key):g}")).strip().replace(",", ".")
            try:
                if answer and 1 <= float(answer) <= 120:
                    setattr(c, key, float(answer))
                elif answer:
                    self.say(_t("filters.out_of_range"))
            except ValueError:
                self.say(_t("filters.not_a_number"))
        self.dirty = True

    def change_cb_call(self) -> None:
        old, self.c.cb_call = self.c.cb_call, ""
        self.ensure_cb_call()
        if not self.c.cb_call and old and not self.yes(_t("call.cb_delete"), False):
            self.c.cb_call = old
        self.dirty = True

    def change_call(self) -> None:
        old, self.c.call = self.c.call, ""
        if not self.ensure_call():
            self.c.call = old

    # ------------------------------------------------------------------ enregistrement

    def _write(self, cfg: cfgmod.Config, secrets: dict[str, str] | None) -> None:
        from ..setup_wizard import write_config
        if secrets is not None:
            secretstore.save(secretstore.path_for(self.config_path), secrets)
        write_config(cfg, self.config_path)

    def save(self) -> bool:
        run = [m for m in self.cfg.modules.run if m != "cluster"]
        if self.c.enabled:
            run.append("cluster")
        self.cfg.modules.run = run
        problems = cfgmod.validate(self.cfg)
        if problems:
            self.say(_t("save.impossible", problems="\n  - ".join(problems)))
            return False
        used = {s.secret for s in self.c.source if s.secret}
        if set(self.secrets) - used:
            self.secrets = {k: v for k, v in self.secrets.items() if k in used}
            self.secrets_changed = True
        self.write(self.cfg, self.secrets if self.secrets_changed else None)
        self.dirty = self.secrets_changed = False
        self.say(_t("save.done"))
        return True

    # ------------------------------------------------------------------ menu

    # Lettres du menu : LES MÊMES dans toutes les langues (la console web en fait des boutons) ; libellés traduits.
    ACTIONS = (("f", "flux", "flux"), ("a", "add", "add_source"), ("m", "modify", "modify_source"),
               ("s", "delete", "delete_source"), ("p", "first", "raise_priority"), ("d", "toggle", "toggle_source"),
               ("r", "filters", "filters"), ("i", "call", "change_call"), ("c", "cb_call", "change_cb_call"),
               ("e", "module", "_toggle_module"))

    def run(self) -> int:
        if not self.c.source:
            self.say(_t("run.first_time"))
            self.flux()
            if self.c.source and self.yes(_t("run.enable"), True):
                self.c.enabled = True
        actions = {letter: (key, getattr(self, method)) for letter, key, method in self.ACTIONS}
        while True:
            self.show()
            for letter, (key, _) in actions.items():
                self.say(f"  {letter}) {_t('menu.' + key)}")
            self.say(_t("menu.save_quit"))
            try:
                choice = self.ask(_t("ask.choice")).strip().lower()
            except EOFError:
                return 1
            if choice == "w":
                if self.save():
                    return 0
            elif choice == "q":
                if not self.dirty or self.yes(_t("run.quit_lose"), False):
                    return 1
            elif choice in actions:
                actions[choice][1]()
            else:
                self.say(_t("run.unknown"))

    def _toggle_module(self) -> None:
        self.c.enabled = not self.c.enabled
        self.dirty = True
        if self.c.enabled and any(s.type != "web" and s.enabled for s in self.c.source):
            self.ensure_call()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.cluster.setup", description="Réglage du Cluster DX")
    ap.add_argument("--config", type=Path, default=default_config_path())
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except FileNotFoundError:
        print(_t("main.no_config", path=args.config), file=sys.stderr)
        return 2
    except (cfgmod.ConfigError, OSError) as exc:
        print(_t("main.bad_config", path=args.config, reason=exc), file=sys.stderr)
        return 2
    try:
        secrets = secretstore.load(secretstore.path_for(args.config))
    except secretstore.SecretsError as exc:
        print(_t("main.bad_secrets", reason=exc), file=sys.stderr)
        return 2
    try:
        return ClusterEditor(cfg, args.config, secrets=secrets).run()
    except KeyboardInterrupt:
        print(_t("main.interrupted"))
        return 130


if __name__ == "__main__":
    sys.exit(main())
