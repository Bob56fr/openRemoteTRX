# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Page de secours : explique pourquoi une page de la station n'est pas servie (étape 405).

Demande de l'utilisateur du 2026-11-27 : « plutôt que rien du tout », car on ne sait pas d'où vient le problème.
Trois cas, chacun servi par celui qui le connaît :
- `safe_mode` (port de la page de pilotage, 8443) : par le SUPERVISEUR, qui a arrêté la passerelle ;
- `console_off` (port de la console web, 8444) : par le superviseur, tant que [remote_console] est désactivée ;
- `no_account` (8443) : par la PASSERELLE, qui ne démarre pas son API sans aucun compte.
Station arrêtée (menu 1.2), machine éteinte, réseau coupé : rien ne répond, et c'est voulu (décision du 2026-11-27).

Page vue SANS mot de passe : l'état, le code et le menu à ouvrir, jamais la cause détaillée de la mise en sécurité
(décision du 2026-11-16 : cause réservée aux appareils appairés, elle est dans la console). Aucune commande : toute
requête reçoit 503. Bibliothèque standard seulement (le superviseur reste quasi sans dépendance).
"""
from __future__ import annotations

import html
import json
import logging
import os
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .i18n import LANGS, catalog

log = logging.getLogger("trxstation.fallback")

KINDS = ("safe_mode", "console_off", "no_account")
# Numéros des menus cités (vérifiés contre console.menu_number par un test : jamais d'import de la console ici).
MENUS = {"diagnostic": "6.1", "journal": "6.2", "clear_safe_mode": "1.4", "remote_console": "4.6",
         "operators": "4.3", "stop": "1.2", "start": "1.1"}
CODES = {"safe_mode": "ORT-8008", "console_off": "", "no_account": "ORT-9710"}
JSON_PATHS = ("/safe-mode.json", "/fallback.json")
MAX_CONNECTIONS = 16
DOMAIN = "fallback"


def pick_lang(accept_language: str | None) -> str:
    """Langue du navigateur parmi les 4 de la station ; anglais pour une autre langue, français sans en-tête."""
    if not accept_language:
        return "fr"
    for part in accept_language.split(","):
        code = part.split(";", 1)[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return "en"


def _t(lang: str, key: str, **fields: str) -> str:
    text = catalog(lang, DOMAIN).get(key) or catalog("fr", DOMAIN).get(key, key)
    try:
        return text.format(**fields) if fields else text
    except (KeyError, IndexError, ValueError):
        return text


def _menu(lang: str, method: str) -> str:
    """« 4.3 « Comptes opérateurs » » : numéro et libellé du menu dans la langue (catalogue de la console)."""
    label = catalog(lang, "console").get(f"menu.{method}") or catalog("fr", "console").get(f"menu.{method}", "")
    label = label.split(" (", 1)[0]
    return _t(lang, "menu", number=MENUS[method], label=label)


def texts(kind: str, lang: str) -> dict[str, str]:
    """Titre, explication et marche à suivre d'un cas, dans une langue."""
    menus = {f"m_{name}": _menu(lang, name) for name in MENUS}
    return {"title": _t(lang, f"{kind}.title"), "text": _t(lang, f"{kind}.text"),
            "what": _t(lang, f"{kind}.what", **menus)}


def render(kind: str, lang: str) -> str:
    """Page HTML complète, sans script, sans ressource externe."""
    t = texts(kind, lang)
    code = CODES[kind]
    code_line = ""
    if code:
        url = f"https://bob56fr.github.io/openRemoteTRX/erreurs/{code}/"
        code_line = (f'<p class="code">{html.escape(_t(lang, "code"))} '
                     f'<a href="{url}" rel="noopener">{code}</a></p>')
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>openRemoteTRX — {html.escape(t["title"])}</title>
<style>
:root{{--bg:#10151c;--card:#1a222d;--fg:#e8edf3;--muted:#9fb0c2;--accent:#ffb340;--bad:#ff6b5e}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;display:flex;justify-content:center}}
main{{max-width:560px;margin:48px 16px;padding:24px;background:var(--card);border-radius:12px;border-left:6px solid var(--{"bad" if kind == "safe_mode" else "accent"})}}
h1{{font-size:1.3em;margin:0 0 12px}} .brand{{color:var(--muted);font-size:.85em;letter-spacing:.08em;text-transform:uppercase}}
.what{{background:rgba(255,255,255,.05);padding:12px;border-radius:8px}} .code,.note{{color:var(--muted);font-size:.9em}}
a{{color:var(--accent)}}
</style></head><body><main>
<div class="brand">openRemoteTRX</div>
<h1>{html.escape(t["title"])}</h1>
<p>{html.escape(t["text"])}</p>
<p class="what">{html.escape(t["what"])}</p>
{code_line}
<p class="note">{html.escape(_t(lang, "note"))}</p>
</main></body></html>
"""


def json_body(kind: str, lang: str) -> dict[str, str]:
    """Réponse JSON (application, `/offer` de la page, `/safe-mode.json`) : même forme qu'un refus d'accès."""
    t = texts(kind, lang)
    return {"error": kind, "code": CODES[kind], "message": f'{t["title"]} : {t["text"]} {t["what"]}'}


class _Handler(BaseHTTPRequestHandler):
    server_version = "openRemoteTRX"
    sys_version = ""
    timeout = 10

    def log_message(self, *_args) -> None:          # pas de ligne par requête dans le journal
        return

    def _answer(self, head_only: bool = False) -> None:
        kind = self.server.kind                     # type: ignore[attr-defined]
        lang = pick_lang(self.headers.get("Accept-Language"))
        path = self.path.split("?", 1)[0]
        if self.command != "GET" or path in JSON_PATHS:
            body = json.dumps(json_body(kind, lang), ensure_ascii=False).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            body = render(kind, lang).encode("utf-8")
            ctype = "text/html; charset=utf-8"
        self.send_response(503)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Retry-After", "60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
                         "frame-ancestors 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self) -> None: self._answer()
    def do_HEAD(self) -> None: self._answer(head_only=True)
    def do_POST(self) -> None:
        length = self.headers.get("Content-Length", "0")
        if length.isdigit() and int(length) <= 65536:
            self.rfile.read(int(length))            # corps lu (et ignoré) : la réponse arrive proprement
        self._answer()

    def handle(self) -> None:
        try:
            super().handle()
        except (OSError, ssl.SSLError):             # client qui part, poignée TLS ratée : sans importance
            pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # Linux : relance juste après un arrêt (TIME_WAIT). JAMAIS sous Windows : SO_REUSEADDR y laisse ouvrir un port
    # DÉJÀ PRIS (la page de secours doublerait la vraie passerelle) ; accès exclusif à la place.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, kind: str, context: ssl.SSLContext | None):
        self.kind, self.context = kind, context
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, _Handler)

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(10)
        if self.context is not None:                # poignée TLS dans le fil du client (pas dans celui qui accepte)
            sock = self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):  # trop de connexions : on ferme, rien de plus
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class FallbackServer:
    """Page de secours sur une adresse et un port. `start()` rend False si le port est pris (le vrai service tourne,
    ou autre chose) : jamais d'exception, jamais d'attente."""

    def __init__(self, kind: str, host: str, port: int, cert: str = "", key: str = ""):
        if kind not in KINDS:
            raise ValueError(kind)
        self.kind, self.host, self.port, self.cert, self.key = kind, host or "127.0.0.1", port, cert, key
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> bool:
        if self._server is not None:
            return True
        try:
            context = None
            if self.cert:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(self.cert, self.key or None)
            server = _Server((self.host, self.port), self.kind, context)
        except (OSError, ssl.SSLError, ValueError):
            return False
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                                        name=f"fallback-{self.port}", daemon=True)
        self._thread.start()
        log.info("Page de secours « %s » servie sur le port %s", self.kind, self.port)
        return True

    def stop(self) -> None:
        """Libère le port tout de suite (avant que le vrai service ne démarre)."""
        server, self._server = self._server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        log.info("Page de secours « %s » arrêtée (port %s libéré)", self.kind, self.port)


def is_local(bind: str) -> bool:
    return bind in ("", "127.0.0.1", "localhost", "::1")


def port_answers(host: str, port: int, timeout: float = 0.3) -> bool:
    """Quelque chose écoute-t-il ? 0.0.0.0 / :: se sondent sur la machine elle-même."""
    target = "127.0.0.1" if host in ("", "0.0.0.0") else "::1" if host == "::" else host
    try:
        with socket.create_connection((target, port), timeout=timeout):
            return True
    except OSError:
        return False
