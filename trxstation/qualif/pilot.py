# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""`trx-qualif --pilote …` : client de l'API de pilotage de la valise (lot G3,
docs/qualification-gui-cahier-des-charges.md § 4). Pour Claude, qui mène la qualification depuis la conversation.

La valise doit tourner avec sa page (`trx-qualif --terrain --page --output DOSSIER`) ; elle écrit l'adresse et le jeton
du pilote dans `DOSSIER/pilote.json`. Actions :

  etat                      où en est la valise : au menu ou non, ce qui attend l'opérateur, tuiles, mesures
  lancer CLE [SECONDES]     une action du menu (tuile « 5.N » / « 8.N », « r », « 3 »…, « tout », « echecs »,
                            « theme:<id> ») ; refusée si la valise n'est pas au menu ; puis suivie comme « attendre »
  attendre [SECONDES]       suit le journal jusqu'au retour au menu, une attente de l'opérateur ou la fin (600 s)
  demander [--oui-non|--fait] TEXTE
                            question à l'humain dans la page ; attend sa réponse (10 min au plus) et l'affiche
  reponse N                 réponse à la demande N (si « demander » a été interrompu)
  journal [N]               les N dernières lignes du journal (40)
  stop                      comme le bouton STOP de la page (« T 0 », puis l'essai en cours est interrompu)

Le pilote ne répond JAMAIS à une question de la valise : gestes, avis, mots de passe et mots de sécurité (CHARGE,
ANTENNE, EMETTRE) restent à l'humain, au clavier.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .page.server import PILOT_FILE, PILOT_HEADER

POLL_S = 1.0
WAIT_DEFAULT_S = 600.0
ASK_WAIT_S = 600.0


class PilotError(RuntimeError):
    pass


class Pilot:
    def __init__(self, port: int, token: str, *, timeout: float = 10.0) -> None:
        self.base, self.token, self.timeout = f"http://127.0.0.1:{port}", token, timeout

    @classmethod
    def from_folder(cls, folder: Path) -> "Pilot":
        path = folder / PILOT_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(int(data["port"]), str(data["jeton"]))
        except (OSError, ValueError, KeyError, TypeError):
            raise PilotError(f"aucune valise ouverte avec --page dans {folder} ({path.name} absent) : lancer "
                             f"trx-qualif --terrain --page --output {folder}") from None

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={PILOT_HEADER: self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise PilotError(f"la valise refuse ({exc.code}) : {exc.read().decode('utf-8', 'replace')[:200]}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise PilotError(f"valise injoignable ({exc}) : est-elle encore ouverte ?") from None

    def state(self) -> dict:
        return self.call("GET", "/pilote/etat")

    def journal(self, since: int = 0) -> list[dict]:
        return self.call("GET", f"/pilote/journal?depuis={since}")["lignes"]

    def launch(self, key: str) -> dict:
        return self.call("POST", "/pilote/lancer", {"cle": key})

    def ask(self, text: str, kind: str = "texte") -> dict:
        return self.call("POST", "/pilote/demander", {"genre": kind, "texte": text})

    def reply(self, n: int) -> dict:
        return self.call("GET", f"/pilote/reponse?demande={n}")

    def stop(self) -> dict:
        return self.call("POST", "/pilote/stop", {})


# --------------------------------------------------------------------------- affichage

def describe(state: dict) -> str:
    out = []
    st = state.get("statut") or {}
    out.append(f"Poste : {st.get('poste', '?')} ; station du PC : "
               f"{'en marche' if st.get('station') else 'arrêtée' if st.get('station') is False else '?'} ; "
               f"branchement : {st.get('branchement') or '?'}")
    if state.get("fin"):
        out.append("La valise est FERMÉE.")
    elif state.get("menu"):
        out.append("La valise attend au MENU : touches " + " ".join(k for k in state.get("touches") or [] if k))
    else:
        out.append("Essai en cours (la valise n'est pas au menu).")
    for q in state.get("attente_operateur") or []:
        what = f"mot {q['mot']} à taper par l'opérateur" if q.get("genre") == "mot" else q.get("genre")
        out.append(f"EN ATTENTE DE L'OPÉRATEUR ({what}) : {q.get('texte', '')}")
        if q.get("contexte"):
            out.append("  " + q["contexte"].replace("\n", "\n  "))
    m = state.get("mesures") or {}
    if m:
        out.append("Mesures : " + ", ".join(f"{k}={v}" for k, v in m.items()))
    tiles = state.get("tuiles") or {}
    if tiles:
        out.append(f"Progression : {tiles.get('faits', 0)} / {tiles.get('total', 0)}")
        for theme in tiles.get("themes") or []:
            items = " ".join(f"{i['cle']}={i['etat']}" for i in theme.get("essais") or [])
            out.append(f"  {theme.get('id')} : {items}")
    return "\n".join(out)


def wait(pilot: Pilot, max_s: float, out=print, since: int | None = None) -> dict:
    """Suit le journal jusqu'à : retour au menu (sans attente humaine), attente de l'opérateur, ou fin. `since` :
    numéro d'événement d'où suivre (celui rendu par « lancer » : rien de ce qu'a fait l'action n'est perdu)."""
    state = pilot.state()
    launched = since is not None
    since = state.get("dernier_evenement", 0) if since is None else since
    start = time.monotonic()
    end = start + max_s
    # une question DÉJÀ ouverte au départ est déjà connue du pilote : on attend la suivante (ou le menu), pas elle
    announced: set[int] = set() if launched else {q["id"] for q in state.get("attente_operateur") or []}
    left_menu = launched or not state.get("menu")
    while True:
        for line in pilot.journal(since):
            since = max(since, line["n"])
            text = str(line["texte"]).rstrip()
            if text:
                out(text)
        state = pilot.state()
        if state.get("fin"):
            out("== valise fermée")
            return state
        human = state.get("attente_operateur") or []
        new = [q for q in human if q["id"] not in announced]
        if new:
            for q in new:
                announced.add(q["id"])
            out("== en attente de l'opérateur :\n" + describe(state))
            return state
        # au menu : fini si la valise l'avait quitté (essai joué), ou si rien n'a démarré en 3 s
        if state.get("menu") and (left_menu or time.monotonic() - start > 3.0):
            out("== retour au menu")
            return state
        left_menu = left_menu or not state.get("menu")
        if time.monotonic() > end:
            out(f"== toujours en cours après {max_s:.0f} s")
            return state
        time.sleep(POLL_S)


def run_pilot(argv: list[str], folder: Path, out=print) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")         # sortie redirigée sous Windows : page de code 1252
    except (AttributeError, ValueError):
        pass
    action, rest = argv[0], argv[1:]
    try:
        pilot = Pilot.from_folder(folder)
        if action == "etat":
            out(describe(pilot.state()))
        elif action == "lancer" and rest and len(rest) <= 2:
            result = pilot.launch(rest[0])
            if not result.get("ok"):
                out(f"Refusé : {result.get('raison')}")
                return 1
            out(f"Lancé : {rest[0]}")
            # puis suivi jusqu'au retour au menu ou à une attente de l'opérateur (« attendre » reprend ensuite)
            wait(pilot, float(rest[1]) if len(rest) > 1 else WAIT_DEFAULT_S, out=out, since=result.get("depuis", 0))
        elif action == "attendre":
            wait(pilot, float(rest[0]) if rest else WAIT_DEFAULT_S, out=out)
        elif action == "demander" and rest:
            kind = "texte"
            if rest[0] in ("--oui-non", "--fait"):
                kind, rest = ("oui_non" if rest[0] == "--oui-non" else "fait"), rest[1:]
            result = pilot.ask(" ".join(rest), kind)
            if not result.get("ok"):
                out(f"Refusé : {result.get('raison')}")
                return 1
            n = result["demande"]
            out(f"Question n° {n} posée dans la page ; attente de la réponse…")
            end = time.monotonic() + ASK_WAIT_S
            while time.monotonic() < end:
                reply = pilot.reply(n)
                if reply.get("etat") != "attente":
                    out(f"Réponse : {reply.get('texte')!r}" if reply.get("etat") == "repondu"
                        else "Question annulée (STOP ou valise fermée).")
                    return 0
                time.sleep(POLL_S)
            out(f"Pas encore de réponse : trx-qualif --pilote reponse {n} --output {folder}")
        elif action == "reponse" and len(rest) == 1:
            out(json.dumps(pilot.reply(int(rest[0])), ensure_ascii=False))
        elif action == "journal":
            count = int(rest[0]) if rest else 40
            for line in pilot.journal(0)[-count:]:
                out(str(line["texte"]).rstrip())
        elif action == "stop":
            result = pilot.stop()
            out("STOP envoyé" + ("" if result.get("ok") else f" (T 0 : {result.get('message')})"))
        else:
            out(__doc__.split("Actions :", 1)[1].split("Le pilote", 1)[0])
            return 2
    except PilotError as exc:
        out(str(exc))
        return 1
    except ValueError as exc:
        out(f"Argument invalide : {exc}")
        return 2
    return 0
