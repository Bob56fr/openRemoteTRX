# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Page de la valise de qualification (lot G2a, docs/qualification-gui-cahier-des-charges.md) :
`trx-qualif --terrain --page`.

La page est un CLIENT du bus de la valise (`qualif/bus.py`) : elle affiche le journal et le menu, répond aux
questions, et ouvre la FENÊTRE D'INTERVENTION pour les mots de sécurité. Elle n'invente aucun essai.

Sécurité (mêmes protections que la console web locale, `console_web/server.py`) :
  * 127.0.0.1 SEULEMENT (décision de l'utilisateur, 2026-11-19 : PC de la valise seul) ; jeton à usage unique dans
    l'adresse ouverte, échangé contre un cookie de session (une seule session) ; en-tête Host vérifié (pas de
    « DNS rebinding ») ; Origin vérifié pour toute action et pour le WebSocket ; CSP stricte, aucun script en ligne ;
  * mots CHARGE / ANTENNE / EMETTRE : SEULEMENT par le message « mot » de la fenêtre d'intervention (source
    `fenetre`), tapé au clavier (collage et saisie simulée refusés par la page : `trusted`) ; la route ordinaire
    (`reponse`, source `page`) est refusée par le bus pour un mot ;
  * STOP : « T 0 » envoyé d'abord à rigctld (`monitor/actions.stop_tx`, ne peut que COUPER), puis l'enchaînement
    est interrompu (`Bus.request_stop`). La page ne peut déclencher aucune émission par elle-même : elle ne fait que
    répondre aux questions que la valise pose.

API DE PILOTAGE (lot G3, `/pilote/…`, client : `trx-qualif --pilote`, `qualif/pilot.py`) : pour Claude, qui mène la
qualification et a besoin de l'humain pour les gestes et les mots de sécurité.
  * jeton propre (en-tête `X-Valise-Pilote`), écrit dans `pilote.json` du dossier de sortie (même compte, retiré à
    la fin) ; une requête d'un NAVIGATEUR (en-tête Origin) est refusée : une page web ne peut pas piloter ;
  * le pilote LIT (état, tuiles, mesures, journal), LANCE une action du menu quand la valise y attend (tuile, thème,
    « Tout lancer » ; ni quitter, ni sous-menu), POSE une question à l'humain (texte, oui / non, « c'est fait »), ou
    ARRÊTE (même chemin que STOP) ;
  * il ne RÉPOND à aucune question de la valise : un geste, un avis, un mot de passe ou un mot de sécurité restent à
    l'humain (« en attente de l'opérateur ») ; une réponse de la source `pilote` à un mot de sécurité est de toute
    façon refusée par le bus (test).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

from aiohttp import WSMsgType, web

from ..bus import (DONE, SOURCE_PAGE, SOURCE_PILOT, SOURCE_WINDOW, TEXT, WORD, YES_NO, Bus, QuestionStopped,
                   RefusedAnswer)

DEFAULT_PORT = 8766
COOKIE = "trx_valise"
HERE = Path(__file__).parent
STATIC = HERE / "static"
STATIC_FILES = {"valise.js": "application/javascript", "valise.css": "text/css"}
LANGS = ("fr", "en")
HISTORY = 3000                    # événements gardés pour une page qui se (re)connecte
MAX_ANSWER = 200
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
EXPIRED_PAGE = ("<!doctype html><meta charset=utf-8><title>Valise</title>"
                "<p style='font-family:sans-serif;margin:2em'>Lien expiré ou déjà utilisé : relancer "
                "<code>trx-qualif --terrain --page</code> (la session du jour est reprise).<br>"
                "Link expired or already used: run <code>trx-qualif --terrain --page</code> again.</p>")


PILOT_HEADER = "X-Valise-Pilote"
PILOT_FILE = "pilote.json"
PILOT_KINDS = (TEXT, YES_NO, DONE)            # questions que le pilote peut POSER à l'humain (jamais un mot, un secret)
PILOT_REFUSED_KEYS = frozenset({"q", "5", "8"})   # quitter = l'humain ; 5 / 8 = sous-menus (clés directes 5.N / 8.N)
PILOT_MAX_TEXT = 600
PILOT_ACTIVE_S = 90.0                         # « Pilote : Claude » tant qu'il s'est manifesté depuis moins que cela
LINES_KEPT = 400


def pilot_key_allowed(key: str, menu: dict) -> bool:
    """Action du menu permise au pilote : une touche du menu (sauf quitter et les sous-menus), un essai « 5.N » /
    « 8.N », « tout », « echecs », « theme:<id> »."""
    from .. import tiles as tl
    if not isinstance(key, str) or not key or len(key) > 40 or key in PILOT_REFUSED_KEYS:
        return False
    if key in ("tout", "echecs") or tl.drill_of(key) is not None:
        return True
    if key.startswith("theme:"):
        return key[len("theme:"):] in {t for t, _, _ in tl.themes()}
    return key in {c.get("cle") for c in menu.get("choix") or [] if isinstance(c, dict)}


def load_texts(lang: str) -> dict:
    return json.loads((HERE / f"texts.{lang if lang in LANGS else 'en'}.json").read_text(encoding="utf-8"))


class ValisePage:
    def __init__(self, bus: Bus, *, stop_tx: Callable[[], tuple[bool, str]], lang: str = "fr",
                 port: int = DEFAULT_PORT, stop_station: Callable[[], int] | None = None,
                 pilot_file: Path | None = None) -> None:
        self.bus, self.stop_tx, self.port, self.stop_station = bus, stop_tx, port, stop_station
        self.pilot_file = pilot_file
        self.pilot_token = secrets.token_urlsafe(32)
        self.pilot_seen = 0.0                       # dernière requête du pilote (time.monotonic)
        self.pilot_asks: dict[int, dict] = {}       # questions posées par le pilote : n -> {id, etat, texte}
        self._pilot_n = 0
        self.lines: deque[dict] = deque(maxlen=LINES_KEPT)
        self.statut: dict = {}
        self.tuiles: dict | None = None
        self.mesures: dict = {}
        self.lang = lang if lang in LANGS else "en"
        self.token: str | None = secrets.token_urlsafe(32)
        self.session: str | None = None
        self.history: deque[dict] = deque(maxlen=HISTORY)
        self.open: dict[int, dict] = {}            # questions ouvertes (événement d'origine)
        self.finished = False
        self.report: str | None = None
        self.clients: set[web.WebSocketResponse] = set()
        self._lock = threading.Lock()
        self._outbox: deque[dict] = deque()
        self._drain_pending = False
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop: asyncio.Event | None = None
        bus.subscribe(self.on_event)

    # ------------------------------------------------------------------ événements du bus (fils de la valise)

    def on_event(self, event: dict) -> None:
        with self._lock:
            self.history.append(event)
            if event["type"] == "question":
                self.open[event["id"]] = event
            elif event["type"] in ("reponse", "annule"):
                self.open.pop(event.get("id"), None)
            elif event["type"] == "fin":
                self.finished = True
            elif event["type"] == "rapport":
                self.report = event.get("chemin")         # seul fichier que /api/open_report sait montrer
            elif event["type"] == "ligne" and not event.get("menu"):
                self.lines.append({"n": event["n"], "texte": event.get("texte", "")})
            elif event["type"] == "statut":
                self.statut.update({k: v for k, v in event.items() if k not in ("n", "t", "type")})
            elif event["type"] == "tuiles":
                self.tuiles = {k: v for k, v in event.items() if k not in ("n", "t", "type")}
            elif event["type"] == "mesure" and event.get("nom") == "poste" and isinstance(event.get("valeur"), dict):
                self.mesures.update(event["valeur"])
            if event["type"] == "question" and event.get("role") == "menu":
                self.mesures = {}                         # au menu, plus personne ne relit le poste
            self._outbox.append(event)
            if self.loop is None or self._drain_pending:
                return
            self._drain_pending = True                # un seul envoi en attente vers la boucle (piège « fils »)
        try:
            self.loop.call_soon_threadsafe(self._drain)
        except RuntimeError:                          # boucle déjà fermée
            pass

    def _drain(self) -> None:
        with self._lock:
            events, self._drain_pending = list(self._outbox), False
            self._outbox.clear()
        for event in events:
            self.broadcast(event)

    def broadcast(self, message: dict) -> None:
        for ws in list(self.clients):
            asyncio.ensure_future(self._send(ws, message))

    async def _send(self, ws: web.WebSocketResponse, message: dict) -> None:
        try:
            await ws.send_str(json.dumps(message, ensure_ascii=False))
        except (ConnectionError, RuntimeError):
            self.clients.discard(ws)

    # ------------------------------------------------------------------ application

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.guard])
        app.router.add_get("/", self.index)
        app.router.add_get("/static/{name:.+}", self.static)
        app.router.add_post("/api/stop", self.stop)
        app.router.add_post("/api/station_stop", self.station_stop)
        app.router.add_post("/api/open_report", self.open_report)
        app.router.add_get("/ws", self.websocket)
        app.router.add_get("/pilote/etat", self.pilot_state)
        app.router.add_get("/pilote/journal", self.pilot_journal)
        app.router.add_post("/pilote/lancer", self.pilot_launch)
        app.router.add_post("/pilote/demander", self.pilot_ask)
        app.router.add_get("/pilote/reponse", self.pilot_reply)
        app.router.add_post("/pilote/stop", self.pilot_stop)
        return app

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    @web.middleware
    async def guard(self, request: web.Request, handler):
        if request.host not in self.allowed_hosts():          # DNS rebinding
            return web.Response(status=403, text="Adresse refusée.")
        response = await handler(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    def has_session(self, request: web.Request) -> bool:
        value = request.cookies.get(COOKIE, "")
        return self.session is not None and bool(value) and hmac.compare_digest(value, self.session)

    def same_origin(self, request: web.Request) -> bool:
        return request.headers.get("Origin", "") in {f"http://{h}" for h in self.allowed_hosts()}

    async def index(self, request: web.Request) -> web.StreamResponse:
        token = request.query.get("t")
        if token is not None:
            if self.token is None or not hmac.compare_digest(token, self.token):
                return web.Response(status=403, content_type="text/html", text=EXPIRED_PAGE)
            self.token = None                                   # usage unique
            self.session = secrets.token_urlsafe(32)            # une seule session
            response = web.HTTPFound("/")
            response.set_cookie(COOKIE, self.session, httponly=True, samesite="Strict", path="/")
            raise response
        if not self.has_session(request):
            return web.Response(status=403, content_type="text/html", text=EXPIRED_PAGE)
        page = (STATIC / "index.html").read_text(encoding="utf-8").replace("{{lang}}", self.lang)
        return web.Response(text=page, content_type="text/html", charset="utf-8")

    async def static(self, request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        if name not in STATIC_FILES:                            # liste fermée : rien d'autre n'est servi
            raise web.HTTPNotFound()
        return web.FileResponse(STATIC / name, headers={"Content-Type": f"{STATIC_FILES[name]}; charset=utf-8"})

    async def stop(self, request: web.Request) -> web.StreamResponse:
        """STOP : d'abord « T 0 » au poste (ne peut que couper), ensuite l'enchaînement interrompu."""
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        try:
            ok, message = await asyncio.to_thread(self.stop_tx)
        except Exception as exc:                                # noqa: BLE001 : station.toml, rigctld absent…
            ok, message = False, str(exc)[:160]
        self.bus.request_stop()
        return web.json_response({"ok": ok, "message": message})

    # ------------------------------------------------------------------ API de pilotage (lot G3)

    def pilot_allowed(self, request: web.Request) -> bool:
        if "Origin" in request.headers:              # requête d'un navigateur : jamais un pilote
            return False
        value = request.headers.get(PILOT_HEADER, "")
        return bool(value) and hmac.compare_digest(value, self.pilot_token)

    def _pilot_touch(self) -> None:
        import time
        first = time.monotonic() - self.pilot_seen > PILOT_ACTIVE_S
        self.pilot_seen = time.monotonic()
        if first:
            self.bus.publish("pilote", actif=True)

    def _guard_pilot(self, request: web.Request) -> None:
        if not self.pilot_allowed(request):
            raise web.HTTPForbidden(text="pilote refusé")
        self._pilot_touch()

    def _menu(self) -> dict | None:
        return next((q for q in self.open.values() if q.get("role") == "menu"), None)

    def pilot_snapshot(self) -> dict:
        """Ce que voit le pilote : où en est la valise, et ce qui attend l'humain."""
        with self._lock:
            menu = self._menu()
            human = [q for q in self.open.values() if q.get("role") != "menu"
                     and not str(q.get("role") or "").startswith("pilote:")]
            asked = [q for q in self.open.values() if str(q.get("role") or "").startswith("pilote:")]
            return {
                "menu": menu is not None,
                "touches": [c.get("cle") for c in (menu or {}).get("choix") or [] if isinstance(c, dict)],
                "attente_operateur": [{"id": q["id"], "genre": q.get("genre"), "texte": q.get("texte", "").strip(),
                                       "mot": q.get("mot"), "role": q.get("role"),
                                       "contexte": (q.get("contexte") or "").strip()} for q in human],
                "questions_du_pilote": [q["id"] for q in asked],
                "statut": dict(self.statut), "tuiles": self.tuiles, "mesures": dict(self.mesures),
                "dernier_evenement": self.history[-1]["n"] if self.history else 0,
                "fin": self.finished,
            }

    async def pilot_state(self, request: web.Request) -> web.StreamResponse:
        self._guard_pilot(request)
        return web.json_response(self.pilot_snapshot())

    async def pilot_journal(self, request: web.Request) -> web.StreamResponse:
        """Lignes du journal (hors menu du terminal) après l'événement n° `depuis`."""
        self._guard_pilot(request)
        try:
            since = int(request.query.get("depuis", "0"))
        except ValueError:
            since = 0
        with self._lock:
            lines = [line for line in self.lines if line["n"] > since]
        return web.json_response({"lignes": lines})

    async def pilot_launch(self, request: web.Request) -> web.StreamResponse:
        """Action du menu : seulement quand la valise ATTEND au menu ; la valise fait ensuite ses préalables et pose
        ses questions à l'humain (CHARGE, EMETTRE…) comme pour un clic sur une tuile."""
        self._guard_pilot(request)
        try:
            data = await request.json()
        except ValueError:
            data = {}
        key = data.get("cle") if isinstance(data, dict) else None
        with self._lock:
            menu = self._menu()
        if menu is None:
            return web.json_response({"ok": False, "raison": "la valise n'est pas au menu (essai en cours ?)"})
        if not pilot_key_allowed(key, menu):
            return web.json_response({"ok": False, "raison": f"action refusée au pilote : {key!r}"})
        with self._lock:
            since = self.history[-1]["n"] if self.history else 0  # le pilote suit le journal à partir d'ici
        self.bus.publish("pilote", actif=True, cle=key)          # la page : petit bip, « Pilote : Claude »
        try:
            self.bus.answer(menu["id"], key, source=SOURCE_PILOT)
        except (KeyError, RefusedAnswer):
            return web.json_response({"ok": False, "raison": "menu déjà répondu"})
        return web.json_response({"ok": True, "depuis": since})

    async def pilot_ask(self, request: web.Request) -> web.StreamResponse:
        """Question du pilote à l'humain, montrée dans la page (« Claude a besoin de vous ») ; réponse lue par
        `/pilote/reponse?demande=N`. Jamais un mot de sécurité ni un secret."""
        self._guard_pilot(request)
        try:
            data = await request.json()
        except ValueError:
            data = {}
        kind = data.get("genre", TEXT) if isinstance(data, dict) else None
        text = data.get("texte") if isinstance(data, dict) else None
        if kind not in PILOT_KINDS or not isinstance(text, str) or not text.strip():
            return web.json_response({"ok": False, "raison": "genre : texte, oui_non ou fait ; texte non vide"})
        with self._lock:
            self._pilot_n += 1
            n = self._pilot_n
            self.pilot_asks[n] = {"etat": "attente", "texte": None}
        role = f"pilote:{n}"

        def ask() -> None:
            try:
                reply = self.bus.question(text.strip()[:PILOT_MAX_TEXT], kind, role=role)
                state = {"etat": "repondu", "texte": reply}
            except QuestionStopped:
                state = {"etat": "annule", "texte": None}
            with self._lock:
                self.pilot_asks[n] = state
        threading.Thread(target=ask, name=f"pilote-{n}", daemon=True).start()
        return web.json_response({"ok": True, "demande": n})

    async def pilot_reply(self, request: web.Request) -> web.StreamResponse:
        self._guard_pilot(request)
        try:
            n = int(request.query.get("demande", ""))
        except ValueError:
            n = -1
        with self._lock:
            state = self.pilot_asks.get(n)
        if state is None:
            return web.json_response({"ok": False, "raison": "demande inconnue"})
        return web.json_response({"ok": True, **state})

    async def pilot_stop(self, request: web.Request) -> web.StreamResponse:
        """STOP du pilote : même chemin que le bouton de la page (« T 0 » d'abord, ne peut que couper)."""
        self._guard_pilot(request)
        try:
            ok, message = await asyncio.to_thread(self.stop_tx)
        except Exception as exc:                                # noqa: BLE001
            ok, message = False, str(exc)[:160]
        self.bus.request_stop()
        return web.json_response({"ok": ok, "message": message})

    def write_pilot_file(self) -> None:
        """Adresse et jeton du pilote, pour `trx-qualif --pilote` (même compte ; fichier retiré à la fin)."""
        if self.pilot_file is None:
            return
        import os
        self.pilot_file.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"port": self.port, "jeton": self.pilot_token, "pid": os.getpid()}).encode("utf-8")
        fd = os.open(self.pilot_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(body)

    def remove_pilot_file(self) -> None:
        if self.pilot_file is not None:
            try:
                self.pilot_file.unlink()
            except OSError:
                pass

    async def station_stop(self, request: web.Request) -> web.StreamResponse:
        """Essai « station arrêtée pendant une émission » : le bouton de la fiche ARRÊTE la station (comme le menu
        1.2), au même instant que le repère. Ne peut qu'arrêter : jamais démarrer, jamais émettre."""
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        if self.stop_station is None:
            return web.json_response({"ok": False})
        try:
            code = await asyncio.to_thread(self.stop_station)
        except Exception:                                       # noqa: BLE001
            code = 1
        return web.json_response({"ok": code == 0})

    async def open_report(self, request: web.Request) -> web.StreamResponse:
        """Ouvre l'explorateur sur le DERNIER rapport fabriqué par la valise (chemin connu du serveur, jamais donné
        par la page). Windows : le zip sélectionné ; ailleurs : son dossier."""
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        path = Path(self.report) if self.report else None
        if path is None or not path.exists():
            return web.json_response({"ok": False})
        import os
        import subprocess
        import sys
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", f"/select,{path}"])
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path.parent)])
        except OSError:
            return web.json_response({"ok": False})
        return web.json_response({"ok": True})

    def handle(self, data: dict) -> dict | None:
        """Message de la page ; renvoie une erreur à montrer, ou None."""
        kind = data.get("type")
        qid, text = data.get("id"), data.get("text", "")
        if kind not in ("reponse", "mot") or not isinstance(qid, int) or not isinstance(text, str):
            return None
        text = text[:MAX_ANSWER]
        with self._lock:
            question = self.open.get(qid)
        if kind == "mot":
            # Fenêtre d'intervention : mot de sécurité SEULEMENT, tapé au clavier (aucun collage, aucune saisie simulée)
            if question is None or question.get("genre") != WORD:
                return {"type": "erreur", "cle": "err.not_word"}
            if data.get("trusted") is not True:
                return {"type": "erreur", "cle": "err.not_typed"}
            source = SOURCE_WINDOW
        else:
            source = SOURCE_PAGE
        try:
            self.bus.answer(qid, text, source=source)
        except RefusedAnswer:
            return {"type": "erreur", "cle": "err.word_window"}
        except KeyError:
            return {"type": "erreur", "cle": "err.closed"}
        return None

    async def websocket(self, request: web.Request) -> web.StreamResponse:
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16 * 1024)
        await ws.prepare(request)
        with self._lock:
            hello = {"type": "init", "lang": self.lang, "textes": load_texts(self.lang),
                     "evenements": list(self.history), "ouvertes": list(self.open.values()),
                     "fin": self.finished}
        self.clients.add(ws)
        await self._send(ws, hello)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if isinstance(data, dict):
                    error = self.handle(data)
                    if error is not None:
                        await self._send(ws, error)
        finally:
            self.clients.discard(ws)
        return ws

    # ------------------------------------------------------------------ lancement dans un fil à part

    def start(self, timeout: float = 10.0) -> str:
        """Serveur dans son propre fil (la valise garde le fil principal) ; renvoie l'adresse à usage unique."""
        ready, failure = threading.Event(), []

        async def main() -> None:
            self.loop, self._stop = asyncio.get_running_loop(), asyncio.Event()
            runner = web.AppRunner(self.app(), access_log=None)
            await runner.setup()
            site = None
            for port in range(self.port, self.port + 20):
                try:
                    site = web.TCPSite(runner, "127.0.0.1", port)
                    await site.start()
                    self.port = port
                    break
                except OSError:
                    site = None
            if site is None:
                failure.append(f"aucun port libre entre {self.port} et {self.port + 19}")
                await runner.cleanup()
                ready.set()
                return
            ready.set()
            try:
                await self._stop.wait()
            finally:
                await runner.cleanup()

        self._thread = threading.Thread(target=lambda: asyncio.run(main()), name="valise-page", daemon=True)
        self._thread.start()
        if not ready.wait(timeout) or failure:
            raise OSError(failure[0] if failure else "page de la valise non démarrée")
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def close(self, timeout: float = 5.0) -> None:
        if self.loop is not None and self._stop is not None:
            try:
                self.loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout)


ANNOUNCE = {
    "fr": ("\nPage de la valise : {url}\n"
           "  Adresse à usage unique, sur CE PC seulement (navigateur ouvert tout seul). Les questions se répondent\n"
           "  DANS LA PAGE ; ce terminal n'affiche plus que le journal. Ctrl+C ici arrête la valise.\n"
           "  Page fermée par erreur : la rouvrir dans le même navigateur (http://127.0.0.1:{port}/) ; navigateur\n"
           "  fermé : Ctrl+C puis relancer la commande (la session du jour est reprise).\n"),
    "en": ("\nSuitcase page: {url}\n"
           "  One-time address, on THIS PC only (browser opened automatically). Questions are answered IN THE PAGE;\n"
           "  this terminal now only shows the log. Ctrl+C here stops the suitcase.\n"
           "  Page closed by mistake: reopen it in the same browser (http://127.0.0.1:{port}/); browser closed:\n"
           "  Ctrl+C then run the command again (today's session is resumed).\n"),
}


def run_with_page(run: Callable[[Bus], int], *, stop_tx: Callable[[], tuple[bool, str]], lang: str,
                  announce: Callable[[str], None] = print, open_browser: bool = True,
                  port: int = DEFAULT_PORT, stop_station: Callable[[], int] | None = None,
                  pilot_file: Path | None = None) -> int:
    """La valise avec sa page : le terminal ne fait qu'afficher (DisplayClient), la page répond."""
    from ..bus import DisplayClient
    bus = Bus()
    DisplayClient(bus, out=announce)
    page = ValisePage(bus, stop_tx=stop_tx, lang=lang, port=port, stop_station=stop_station, pilot_file=pilot_file)
    url = page.start()
    page.write_pilot_file()
    announce(ANNOUNCE[page.lang].format(url=url, port=page.port))
    if open_browser:
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:                                       # noqa: BLE001 : pas de navigateur
            pass
    try:
        return run(bus)
    finally:
        bus.publish("fin")
        page.remove_pilot_file()
        page.close()
