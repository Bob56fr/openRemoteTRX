# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglage du Cluster DX sans éditer de fichier (TRX Console, menu 12).

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
from .. import secretstore
from ..paths import default_config_path
from .bandplan import BAND_NAMES, MODES
from .cty import CONTINENTS
from .feed import Source
from .servers import KNOWN, KnownServer
from .tester import SourceReport, check_source
from .text import check_own_call, own_call_problem

KIND_LABELS = {"telnet": "cluster", "rbn": "RBN", "web": "CB (web)"}
FLUX = (("telnet", "Clusters radioamateurs : spots DX saisis par des opérateurs", True),
        ("rbn", "RBN : stations CW repérées automatiquement (beaucoup de spots, CW seulement)", False),
        ("web", "Cluster DX des cibistes (clusterdx.org, bande des 11 m)", False))
MODE_LABELS = {"SSB": "BLU (SSB)", "AM": "AM", "FM": "FM", "FREEDV": "FreeDV", "CW": "CW (télégraphie)"}
_HOSTPORT = re.compile(r"([A-Za-z0-9.-]{1,253}):(\d{1,5})")


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
            answer = self.ask(f"{question} ({'O/n' if default else 'o/N'}) : ").strip().lower()
            if not answer:
                return default
            if answer in ("o", "oui", "y", "yes"):
                return True
            if answer in ("n", "non", "no"):
                return False
            self.say("Répondre o ou n.")

    def choose(self, question: str, count: int, *, allow_empty: bool = True) -> int | None:
        """Numéro de 1 à count (renvoyé à partir de 0) ; Entrée = None."""
        while True:
            answer = self.ask(question).strip()
            if not answer and allow_empty:
                return None
            if answer.isdigit() and 1 <= int(answer) <= count:
                return int(answer) - 1
            self.say(f"Numéro de 1 à {count}.")

    # ------------------------------------------------------------------ affichage

    def describe(self, s: cfgmod.ClusterSource) -> str:
        where = s.url if s.type == "web" else f"{s.host}:{s.port}"
        pw = "mot de passe ****" if s.secret and s.secret in self.secrets else (
            "mot de passe ABSENT" if s.secret else "sans mot de passe")
        prio = f"priorité {s.priority}, " if s.type == "telnet" else ""
        state = "actif   " if s.enabled else "inactif "
        return f"[{state}] {s.name:<14} {KIND_LABELS[s.type]:<9} {where:<34} {prio}{pw}"

    def show(self) -> None:
        c = self.c
        self.say(f"\n=== Cluster DX : {'ACTIVÉ' if c.enabled else 'désactivé'} — indicatif {c.call or '(aucun)'}, cibiste {c.cb_call or '(aucun)'} ===")
        if not c.source:
            self.say("  (aucune source)")
        for i, s in enumerate(self.ordered(), start=1):
            self.say(f"  {i}. {self.describe(s)}")
        modes = " ".join(c.modes) if c.modes else "tous (" + " ".join(MODES) + ")"
        self.say(f"  Modes suivis : {modes} ; numérique (FT8...) toujours écarté")
        self.say(f"  Bandes : {' '.join(c.bands) or 'toutes'} ; continents des spotteurs : "
                 f"{' '.join(c.continents) or 'tous'} ; liste noire : {' '.join(c.blacklist) or 'vide'}")
        self.say(f"  Durées de vie : {c.ttl_min:g} min (cluster, CB), {c.rbn_ttl_min:g} min (RBN)")

    def ordered(self) -> list[cfgmod.ClusterSource]:
        order = {"telnet": 0, "rbn": 1, "web": 2}
        return sorted(self.c.source, key=lambda s: (order.get(s.type, 9), s.priority, s.name))

    # ------------------------------------------------------------------ questions de flux

    def flux(self) -> None:
        """Quels spots recevoir, et dans quels modes ; ajoute ou désactive les sources correspondantes."""
        self.say("\nQuels spots voulez-vous recevoir ?")
        wanted = {}
        for kind, label, default in FLUX:
            has = [s for s in self.c.source if s.type == kind]
            current = any(s.enabled for s in has) if has else default
            wanted[kind] = self.yes(f"  {label}", current)
        self.say("Modes suivis (le numérique, FT8, FT4, RTTY..., est toujours écarté) :")
        followed = []
        for mode in MODES:
            default = (mode in self.c.modes) if self.c.modes else (mode != "CW" or wanted["rbn"])
            if self.yes(f"  {MODE_LABELS[mode]}", default):
                followed.append(mode)
        if not followed:
            self.say("Aucun mode choisi : tous les modes sont gardés.")
        if wanted["rbn"] and followed and "CW" not in followed:
            self.say("ATTENTION : le RBN ne fournit que de la CW ; sans la CW il n'apporte rien.")
            if self.yes("  Ajouter la CW aux modes suivis", True):
                followed.append("CW")
        self.c.modes = [] if set(followed) in (set(MODES), set()) else [m for m in MODES if m in followed]
        self.dirty = True
        for kind, _, _ in FLUX:
            has = [s for s in self.c.source if s.type == kind]
            for s in has:
                s.enabled = wanted[kind]
            if wanted[kind] and not has:
                self.say(f"\nAjout d'une source « {KIND_LABELS[kind]} » :")
                self.add_source(kind)
                if kind == "telnet" and any(s.type == "telnet" for s in self.c.source) \
                        and self.yes("Ajouter un cluster de secours (bascule automatique)", True):
                    self.add_source("telnet")

    # ------------------------------------------------------------------ sources

    def ensure_cb_call(self) -> None:
        """Indicatif de cibiste, facultatif (la page clusterdx.org se lit sans compte)."""
        if self.c.cb_call:
            return
        while True:
            answer = self.ask("Votre indicatif de cibiste (facultatif, Entrée = aucun) : ").strip().upper()
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
            answer = self.ask("Votre indicatif radioamateur (le seul envoyé aux clusters et au RBN) : ").strip().upper()
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
        self.say(f"  {len(known) + 1}. autre serveur (saisie libre)")
        idx = self.choose("Choix (Entrée = abandon) : ", len(known) + 1)
        if idx is None:
            return None
        if idx < len(known):
            k: KnownServer = known[idx]
            return k.name, k.host, k.port, k.url
        return self.ask_address(kind)

    def ask_address(self, kind: str, current: str = "") -> tuple[str, str, int, str] | None:
        while True:
            hint = f" (Entrée = {current})" if current else ""
            if kind == "web":
                url = self.ask(f"Adresse de la page (https://…){hint} : ").strip() or current
                if not url:
                    return None
                if re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?(/[^\s\"']*)?", url):
                    return self._free_name(url.split("/")[2].split(".")[0]), "", 0, url
                self.say("Adresse refusée : https:// obligatoire, sans espace.")
            else:
                text = self.ask(f"Serveur HÔTE:PORT (ex. dxc.exemple.org:7300){hint} : ").strip() or current
                if not text:
                    return None
                m = _HOSTPORT.fullmatch(text)
                if m and 1 <= int(m.group(2)) <= 65535:
                    return self._free_name(m.group(1).split(".")[0]), m.group(1), int(m.group(2)), ""
                self.say("Format attendu HÔTE:PORT, port de 1 à 65535.")

    def ask_password(self, s: cfgmod.ClusterSource) -> None:
        if s.type == "web":
            return
        has = bool(s.secret and s.secret in self.secrets)
        prompt = ("Mot de passe ou clé (rien ne s'affiche ; Entrée = garder l'actuel, « - » = supprimer) : " if has
                  else "Mot de passe ou clé, si le serveur en demande un (rien ne s'affiche ; Entrée = aucun) : ")
        while True:
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
                self.say(f"Refusé : {exc}")
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
            self.say(f"Test de {s.name} ({src.address}) : connexion, identification, un spot (60 s au plus)...")
            report = self.check(src, s.call or self.c.call, src.password)
            self.say(f"  Résultat : {report.message}")
            if report.sample:
                self.say(f"  Exemple : {report.sample}")
            if report.ok:
                return True
            self.say("  1) Réessayer   2) Enregistrer quand même   3) Abandonner cette source")
            idx = self.choose("Choix : ", 3, allow_empty=False)
            if idx == 1:
                return self.yes("La source ne fonctionne pas aujourd'hui. L'enregistrer quand même", False)
            if idx == 2:
                return False

    def add_source(self, kind: str | None = None) -> None:
        if kind is None:
            for i, (k, label, _) in enumerate(FLUX, start=1):
                self.say(f"  {i}. {label}")
            idx = self.choose("Type de source (Entrée = abandon) : ", len(FLUX))
            if idx is None:
                return
            kind = FLUX[idx][0]
        if kind != "web" and not self.ensure_call():
            self.say("Sans indicatif, pas de cluster ni de RBN.")
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
            answer = self.ask(f"Indicatif pour cette source (Entrée = {self.c.call}) : ").strip().upper()
            if answer and answer != self.c.call:
                if not own_call_problem(answer):
                    s.call = answer
                else:
                    self.say("Indicatif invalide : celui de la station est gardé.")
        before = dict(self.secrets)
        self.ask_password(s)
        if self.test(s):
            self.c.source.append(s)
            self.dirty = True
            self.say(f"Source {s.name} ajoutée.")
        else:
            self.secrets = before
            self.say("Source non ajoutée.")

    def pick_existing(self, verb: str) -> cfgmod.ClusterSource | None:
        items = self.ordered()
        if not items:
            self.say("Aucune source.")
            return None
        for i, s in enumerate(items, start=1):
            self.say(f"  {i}. {self.describe(s)}")
        idx = self.choose(f"Source à {verb} (Entrée = abandon) : ", len(items))
        return None if idx is None else items[idx]

    def modify_source(self) -> None:
        s = self.pick_existing("modifier")
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
            answer = self.ask(f"Indicatif pour cette source (Entrée = {work.call or self.c.call}) : ").strip().upper()
            if answer:
                work.call = "" if answer == self.c.call else (answer if not own_call_problem(answer) else work.call)
        self.ask_password(work)
        if self.test(work):
            self.c.source[self.c.source.index(s)] = work
            self.dirty = True
            self.say("Source modifiée.")
        else:
            self.secrets = before
            self.say("Modification abandonnée.")

    def delete_source(self) -> None:
        s = self.pick_existing("supprimer")
        if s is None or not self.yes(f"Supprimer {s.name}", False):
            return
        self.c.source.remove(s)
        if s.secret and not any(x.secret == s.secret for x in self.c.source):
            self.secrets_changed = self.secrets.pop(s.secret, None) is not None or self.secrets_changed
        self.dirty = True

    def raise_priority(self) -> None:
        s = self.pick_existing("passer en premier (clusters)")
        if s is None:
            return
        if s.type != "telnet":
            self.say("La priorité ne concerne que les clusters (le RBN et la page CB ont chacun leur connexion).")
            return
        group = [s] + [x for x in sorted(self.c.source, key=lambda x: x.priority) if x.type == "telnet" and x is not s]
        for i, x in enumerate(group, start=1):
            x.priority = i
        self.dirty = True

    def toggle_source(self) -> None:
        s = self.pick_existing("activer ou désactiver")
        if s is not None:
            s.enabled = not s.enabled
            self.dirty = True

    def _ask_list(self, question: str, allowed: tuple[str, ...], current: list[str]) -> list[str]:
        while True:
            answer = self.ask(f"{question} [{' '.join(allowed)}] (Entrée = {' '.join(current) or 'tous'}, "
                              "« - » = tous) : ").strip().upper()
            if not answer:
                return current
            if answer == "-":
                return []
            items = answer.replace(",", " ").split()
            bad = [x for x in items if x not in {a.upper() for a in allowed}]
            if not bad:
                lookup = {a.upper(): a for a in allowed}
                return [lookup[x] for x in dict.fromkeys(items)]
            self.say(f"Inconnu : {' '.join(bad)}")

    def filters(self) -> None:
        c = self.c
        c.bands = self._ask_list("Bandes", BAND_NAMES, c.bands)
        c.continents = self._ask_list("Continents des spotteurs (EU = ce qui est entendu en Europe)",
                                      CONTINENTS, c.continents)
        answer = self.ask(f"Liste noire (indicatifs séparés par des espaces, « XX* » = préfixe ; Entrée = "
                          f"{' '.join(c.blacklist) or 'vide'}, « - » = vider) : ").strip().upper()
        if answer == "-":
            c.blacklist = []
        elif answer:
            items = answer.replace(",", " ").split()
            good = [x for x in items if re.fullmatch(r"[A-Z0-9/]{1,15}\*?", x)]
            if len(good) != len(items):
                self.say("Entrées invalides ignorées.")
            c.blacklist = good
        for key, label in (("ttl_min", "Durée de vie des spots de cluster et CB (minutes, 1 à 120)"),
                           ("rbn_ttl_min", "Durée de vie des spots du RBN (minutes, 1 à 120)")):
            answer = self.ask(f"{label} (Entrée = {getattr(c, key):g}) : ").strip().replace(",", ".")
            try:
                if answer and 1 <= float(answer) <= 120:
                    setattr(c, key, float(answer))
                elif answer:
                    self.say("Hors plage : valeur gardée.")
            except ValueError:
                self.say("Nombre attendu : valeur gardée.")
        self.dirty = True

    def change_cb_call(self) -> None:
        old, self.c.cb_call = self.c.cb_call, ""
        self.ensure_cb_call()
        if not self.c.cb_call and old and not self.yes("Supprimer l'indicatif de cibiste", False):
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
            self.say("Enregistrement impossible :\n  - " + "\n  - ".join(problems))
            return False
        used = {s.secret for s in self.c.source if s.secret}
        if set(self.secrets) - used:
            self.secrets = {k: v for k, v in self.secrets.items() if k in used}
            self.secrets_changed = True
        self.write(self.cfg, self.secrets if self.secrets_changed else None)
        self.dirty = self.secrets_changed = False
        self.say("Enregistré. Redémarrer la station pour appliquer (TRX Console, menu 5).")
        return True

    # ------------------------------------------------------------------ menu

    def run(self) -> int:
        if not self.c.source:
            self.say("Cluster DX : première configuration.")
            self.flux()
            if self.c.source and self.yes("Activer le Cluster DX", True):
                self.c.enabled = True
        actions = {
            "f": ("Spots et modes suivis (radioamateurs, RBN, CB)", self.flux),
            "a": ("Ajouter une source", self.add_source),
            "m": ("Modifier une source (adresse, indicatif, mot de passe)", self.modify_source),
            "s": ("Supprimer une source", self.delete_source),
            "p": ("Passer un cluster en premier (priorité)", self.raise_priority),
            "d": ("Activer ou désactiver une source", self.toggle_source),
            "r": ("Filtres et durées de vie", self.filters),
            "i": ("Changer l'indicatif radioamateur", self.change_call),
            "c": ("Changer l'indicatif de cibiste", self.change_cb_call),
            "e": ("Activer ou désactiver le Cluster DX", self._toggle_module),
        }
        while True:
            self.show()
            for key, (label, _) in actions.items():
                self.say(f"  {key}) {label}")
            self.say("  w) Enregistrer et quitter\n  q) Quitter sans enregistrer")
            try:
                choice = self.ask("Choix : ").strip().lower()
            except EOFError:
                return 1
            if choice == "w":
                if self.save():
                    return 0
            elif choice == "q":
                if not self.dirty or self.yes("Les changements seront perdus. Quitter", False):
                    return 1
            elif choice in actions:
                actions[choice][1]()
            else:
                self.say("Choix inconnu.")

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
        print(f"{args.config} absente : configure d'abord la station (assistant).", file=sys.stderr)
        return 2
    except (cfgmod.ConfigError, OSError) as exc:
        print(f"Configuration illisible ({args.config}) : {exc}", file=sys.stderr)
        return 2
    try:
        secrets = secretstore.load(secretstore.path_for(args.config))
    except secretstore.SecretsError as exc:
        print(f"secrets.toml : {exc}. Lancer en administrateur (sudo).", file=sys.stderr)
        return 2
    try:
        return ClusterEditor(cfg, args.config, secrets=secrets).run()
    except KeyboardInterrupt:
        print("\nInterrompu : rien n'a été enregistré.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
