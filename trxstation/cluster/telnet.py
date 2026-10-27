"""Une connexion telnet à un cluster ou au RBN, en LECTURE SEULE.

Seuls envois : l'indicatif, et le mot de passe si le serveur le demande ET
qu'il est fourni. Aucune commande, aucun spot, aucune réponse aux
négociations telnet (elles sont retirées du flux).

`run_session` rend toujours un `SessionResult` (jamais d'exception réseau) :
le code dit pourquoi la connexion s'est terminée, ce qui sert aussi au
bouton « Tester » de la console (lot 2).
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from .text import MAX_LINE, check_own_call, check_password, clean_line

CONNECT_TIMEOUT_S = 15.0
LOGIN_SILENT_S = 10.0          # aucune invite après ce délai : l'indicatif est envoyé quand même
IDLE_TIMEOUT_S = 300.0         # aucune donnée depuis 5 min = connexion morte
REFUSAL_WAIT_S = 5.0

# codes de fin
OK_CLOSED = "closed"                     # le serveur a fermé après une connexion réussie
UNREACHABLE = "unreachable"
IDLE = "idle"
CALL_REFUSED = "callsign_refused"
PASSWORD_REFUSED = "password_refused"
PASSWORD_REQUIRED = "password_required"
STOPPED = "stopped"
FATAL_CODES = frozenset({CALL_REFUSED, PASSWORD_REFUSED, PASSWORD_REQUIRED})

MESSAGES = {
    OK_CLOSED: "connexion fermée par le serveur",
    UNREACHABLE: "serveur injoignable",
    IDLE: "aucune donnée depuis 5 min (connexion morte)",
    CALL_REFUSED: "indicatif refusé",
    PASSWORD_REFUSED: "mot de passe refusé",
    PASSWORD_REQUIRED: "le serveur demande un mot de passe (aucun n'est enregistré)",
    STOPPED: "arrêt demandé",
}

_CALL_PROMPT = re.compile(r"(login|call(sign)?|indicatif)\s*[:>]?\s*$", re.I)
_PASS_PROMPT = re.compile(r"(password|passwd|mot de passe)\s*[:>]?\s*$", re.I)
_REFUSED = re.compile(r"invalid|not a valid|not allowed|not permitted|refused|denied|"
                      r"sorry|bad call|unknown call|incorrect|wrong", re.I)
_TYPES = (("dxspider", re.compile(r"dx\s*spider", re.I)), ("ar", re.compile(r"ar-?cluster", re.I)),
          ("cc", re.compile(r"cc[ -]?clus|cc user|ccc\b", re.I)), ("rbn", re.compile(r"reverse beacon|\brbn\b", re.I)))

IAC, SB, SE = 255, 250, 240


def detect_type(text: str) -> str | None:
    for name, rx in _TYPES:
        if rx.search(text):
            return name
    return None


class LineSplitter:
    """Découpe le flux en lignes bornées ; retire les négociations telnet ; garde la ligne en cours (invites)."""

    def __init__(self, max_line: int = MAX_LINE) -> None:
        self.max_line = max_line
        self.buf = bytearray()
        self._iac: list[int] = []          # séquence IAC en cours
        self._in_sb = False
        self._skip_overlong = False
        self.dropped = 0                   # lignes trop longues jetées

    def _strip_telnet(self, data: bytes) -> bytes:
        out = bytearray()
        for b in data:
            if self._in_sb:
                if self._iac and b == SE:
                    self._in_sb, self._iac = False, []
                else:
                    self._iac = [b] if b == IAC else []
                continue
            if self._iac:
                self._iac.append(b)
                if len(self._iac) == 2:
                    if b == IAC:
                        out.append(IAC)
                        self._iac = []
                    elif b == SB:
                        self._in_sb, self._iac = True, []
                    elif b < 251:                     # commande sans option
                        self._iac = []
                elif len(self._iac) == 3:             # WILL / WONT / DO / DONT + option
                    self._iac = []
                continue
            if b == IAC:
                self._iac = [b]
            else:
                out.append(b)
        return bytes(out)

    def feed(self, data: bytes) -> list[str]:
        lines: list[str] = []
        for b in self._strip_telnet(data):
            if b in (10, 13):
                if self._skip_overlong:
                    self._skip_overlong = False
                elif self.buf:
                    lines.append(clean_line(bytes(self.buf)))
                self.buf.clear()
                continue
            if self._skip_overlong:
                continue
            self.buf.append(b)
            if len(self.buf) > self.max_line:
                self.buf.clear()
                self._skip_overlong = True
                self.dropped += 1
        return [ln for ln in lines if ln]

    def pending(self) -> str:
        return clean_line(bytes(self.buf))


@dataclass
class SessionResult:
    code: str
    logged_in: bool = False
    spots: int = 0                     # lignes « DX de » reçues (lisibles ou non)
    duration_s: float = 0.0
    cluster_type: str | None = None
    detail: str = ""

    @property
    def fatal(self) -> bool:
        return self.code in FATAL_CODES

    @property
    def message(self) -> str:
        text = MESSAGES.get(self.code, self.code)
        return f"{text} ({self.detail})" if self.detail else text


OpenConn = Callable[..., Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


async def run_session(host: str, port: int, call: str, *, password: str | None = None,
                      on_line: Callable[[str], None], on_login: Callable[[str | None], None] | None = None,
                      stop: asyncio.Event | None = None, open_connection: OpenConn = asyncio.open_connection,
                      connect_timeout: float = CONNECT_TIMEOUT_S, login_silent: float = LOGIN_SILENT_S,
                      idle_timeout: float = IDLE_TIMEOUT_S, refusal_wait: float = REFUSAL_WAIT_S, clock: Callable[[], float] = time.monotonic,
                      ) -> SessionResult:
    """Une connexion complète : identification puis lecture jusqu'à la fin. `on_line` reçoit chaque ligne nettoyée."""
    call = check_own_call(call)
    if password is not None:
        password = check_password(password)
    start = clock()
    res = SessionResult(code=UNREACHABLE)
    try:
        reader, writer = await asyncio.wait_for(open_connection(host, port), connect_timeout)
    except (OSError, asyncio.TimeoutError, ValueError) as exc:
        res.detail = type(exc).__name__ if not str(exc) else str(exc)[:120]
        return res

    split = LineSplitter()
    banner: list[str] = []
    sent_call = sent_pass = False
    call_sent_at = 0.0
    last_data = clock()

    def send(text: str) -> None:
        writer.write(text.encode("utf-8") + b"\r\n")

    def login_done() -> None:
        res.logged_in = True
        res.cluster_type = detect_type(" ".join(banner))
        if on_login is not None:
            on_login(res.cluster_type)

    try:
        while True:
            if stop is not None and stop.is_set():
                res.code = STOPPED
                break
            try:
                data = await asyncio.wait_for(reader.read(4096), 1.0)
            except asyncio.TimeoutError:
                data = None
            except (OSError, asyncio.IncompleteReadError) as exc:
                res.code, res.detail = (OK_CLOSED if res.logged_in else UNREACHABLE), type(exc).__name__
                break
            now = clock()
            if data == b"":
                if sent_call and not res.logged_in:
                    # fermé juste après l'identification : le serveur a refusé
                    res.code = PASSWORD_REFUSED if sent_pass else CALL_REFUSED
                    res.detail = res.detail or "connexion fermée après l'identification"
                else:
                    res.code = OK_CLOSED if res.logged_in else UNREACHABLE
                break
            if data:
                last_data = now
                lines = split.feed(data)
            else:
                lines = []
                if now - last_data >= idle_timeout:
                    res.code = IDLE
                    break

            for line in lines:
                if not res.logged_in:
                    if len(banner) < 40:
                        banner.append(line)
                    if sent_call and _REFUSED.search(line):
                        res.code = PASSWORD_REFUSED if sent_pass else CALL_REFUSED
                        res.detail = line[:120]
                        return res
                if line.lstrip().startswith("DX de"):
                    res.spots += 1
                    if not res.logged_in and sent_call:
                        login_done()
                if res.logged_in:
                    on_line(line)

            if not res.logged_in:
                prompt = split.pending() or (lines[-1] if lines else "")
                if not sent_call and (_CALL_PROMPT.search(prompt) or now - start >= login_silent):
                    send(call)
                    sent_call, call_sent_at = True, now
                    split.buf.clear()
                elif sent_call and not sent_pass and _PASS_PROMPT.search(prompt):
                    if password is None:
                        res.code = PASSWORD_REQUIRED
                        return res
                    send(password)
                    sent_pass, call_sent_at = True, now
                    split.buf.clear()
                elif sent_call and now - call_sent_at >= refusal_wait:
                    login_done()                       # aucun refus dans les 5 s : identification acceptée
                if sent_call or sent_pass:
                    await writer.drain()
    except (OSError, ConnectionError) as exc:
        res.code, res.detail = (OK_CLOSED if res.logged_in else UNREACHABLE), type(exc).__name__
    finally:
        res.duration_s = clock() - start
        try:
            writer.close()
        except Exception:                               # le flux est peut-être déjà fermé
            pass
    return res
