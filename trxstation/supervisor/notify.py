"""Alertes vers le téléphone (compatible ntfy : POST du texte, titre en en-tête)."""
from __future__ import annotations

import logging
import threading
import time
import urllib.request
from collections.abc import Callable

log = logging.getLogger(__name__)


def _default_post(url: str, title: str, message: str) -> None:
    safe_title = title.encode("ascii", "ignore").decode()  # en-têtes HTTP : ASCII uniquement
    request = urllib.request.Request(url, data=message.encode("utf-8"),
                                     headers={"Title": safe_title}, method="POST")
    with urllib.request.urlopen(request, timeout=5):  # noqa: S310 : schéma vérifié dans send()
        pass


class Notifier:
    def __init__(self, url: str = "", *, post: Callable[[str, str, str], None] | None = None,
                 clock: Callable[[], float] = time.monotonic, min_interval_s: float = 60.0,
                 threaded: bool = True):
        self.url, self._post, self._clock = url, post or _default_post, clock
        self.min_interval_s, self.threaded = min_interval_s, threaded
        self._last: dict[str, float] = {}

    def send(self, title: str, message: str) -> bool:
        """Retourne True si une alerte est partie. Ne bloque jamais la boucle de supervision."""
        log.warning("ALERTE %s : %s", title, message)
        if not self.url.startswith(("https://", "http://")):
            return False                      # pas d'URL valide (ou schéma file:// refusé)
        now = self._clock()
        last = self._last.get(title)
        if last is not None and now - last < self.min_interval_s:
            return False
        self._last[title] = now

        def work() -> None:
            try:
                self._post(self.url, title, message)
            except Exception as exc:          # une alerte ratée ne doit rien casser
                log.error("envoi d'alerte impossible : %s", exc)

        if self.threaded:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()
        return True
