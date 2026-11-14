# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Alertes vers le téléphone (compatible ntfy : POST du texte, titre en en-tête).

Toute alerte part d'un code du catalogue d'erreurs : `Notifier.alert(codes.ORT_5024, "détail mesuré")`. Le
catalogue donne le titre, la priorité ntfy, la marche à suivre et le lien vers la page du code ; un code dont
`ntfy_defaut` est faux est seulement journalisé. Un code absent du catalogue part quand même (dans le doute,
prévenir). Le texte reste en français (langue du catalogue de référence).
"""
from __future__ import annotations

import logging
import threading
import time
import unicodedata
import urllib.request
from collections.abc import Callable

from ..errors import codes as emit_codes
from ..errors import emit

log = logging.getLogger(__name__)


def ascii_title(title: str) -> str:
    """En-têtes HTTP : ASCII uniquement ; « Émission coupée » devient « Emission coupee » (lettres gardées)."""
    return unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()


def _default_post(url: str, title: str, message: str, priority: str = "") -> None:
    safe_title = ascii_title(title)
    headers = {"Title": safe_title}
    if priority:
        headers["Priority"] = priority                       # ntfy : « min » = ni son ni vibration
    request = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=5):  # noqa: S310 : schéma vérifié dans send()
        pass


class Notifier:
    def __init__(self, url: str = "", *, post: Callable[[str, str, str, str], None] | None = None,
                 clock: Callable[[], float] = time.monotonic, min_interval_s: float = 60.0,
                 threaded: bool = True):
        self.url, self._post, self._clock = url, post or _default_post, clock
        self.min_interval_s, self.threaded = min_interval_s, threaded
        self._last: dict[str, float] = {}

    def alert(self, code: str, detail: str = "", *, key: str = "", **contexte: object) -> bool:
        """Alerte `code` du catalogue ; `detail` = texte mesuré (sinon le message du catalogue rempli par
        `contexte`) ; `key` distingue deux sujets d'un même code (module, action) pour la limite d'une alerte par
        minute. Journalisée au niveau de sa gravité ; retourne True si elle part vers ntfy. Ne lève jamais."""
        try:
            e = emit.entry(code)
            titre, message = emit.render(code, **contexte)
            if detail:
                message = detail
            event = emit.ErrorEvent(code=code, gravite=e["gravite"] if e else "erreur", titre=titre, message=message,
                                    contexte=dict(contexte), horodatage=time.time(), connu=e is not None)
            emit.publish(event, logger=log, prefix="" if e and e["gravite"] == "info" else "ALERTE")
            if e is not None and not e.get("ntfy_defaut"):
                return False
            body = message
            if e is not None:
                body += f"\n\n{e['preconisation']}" + (f"\n{e['doc']}" if e.get("doc") else "")
            priority = str(e["priorite_ntfy"]) if e is not None and e.get("priorite_ntfy") else ""
            return self._deliver(f"{code}:{key}", f"{code} {titre}", body, priority)
        except Exception:                      # une alerte ratée ne doit rien casser
            emit.emit_event(emit_codes.ORT_8013, logger=log, trace=True, detail=f"{code} : erreur inattendue (voir la trace)")
            return False

    def send(self, title: str, message: str, quiet: bool = False) -> bool:
        """Envoi BRUT, sans code : réservé aux essais. Le code de la station passe par `alert` (test qui le vérifie).
        `quiet` : message d'information, priorité minimale, journalisé sans « ALERTE »."""
        if quiet:
            log.info("%s : %s", title, message.replace("\n", " ; "))
        else:
            log.warning("ALERTE %s : %s", title, message)
        return self._deliver(title, title, message, "min" if quiet else "")

    def _deliver(self, key: str, title: str, message: str, priority: str) -> bool:
        """Retourne True si une alerte est partie. Ne bloque jamais la boucle de supervision."""
        if not self.url.startswith(("https://", "http://")):
            return False                      # pas d'URL valide (ou schéma file:// refusé)
        now = self._clock()
        last = self._last.get(key)
        if last is not None and now - last < self.min_interval_s:
            return False
        self._last[key] = now

        def work() -> None:
            try:
                self._post(self.url, title, message, priority)
            except Exception as exc:          # une alerte ratée ne doit rien casser
                emit.emit_event(emit_codes.ORT_8013, logger=log, detail=f"{title[:40]} : {exc}")

        if self.threaded:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()
        return True
