"""Module factice : valide le socle sans matériel.

Il se comporte comme le futur service vidéo vis-à-vis du PTT : il se met en
pause à « PTT actif », reprend à « PTT inactif », et le signale au terminal.
Lancé par le superviseur (variables TRX_MODULE_*), ou à la main :

    python -m trxstation.modules.demo_module
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .client import BusRefused, ModuleClient

log = logging.getLogger("trx.demo")


class DemoModule:
    def __init__(self, client: ModuleClient) -> None:
        self.client = client
        self.paused = False
        self.events_seen = 0
        self.resyncs = 0
        self.state: dict = {}
        client.on_event = self.on_event
        client.on_gap = self.on_gap
        client.on_connect = self.on_gap          # lit l'état à chaque connexion
        client.metrics = lambda: {"paused": self.paused, "events": self.events_seen}

    async def on_gap(self) -> None:
        self.resyncs += 1
        self.state = await self.client.get_state()
        await self._apply_ptt(bool(self.state.get("ptt")))

    async def on_event(self, name: str, data: dict) -> None:
        self.events_seen += 1
        if name == "ptt":
            await self._apply_ptt(bool(data.get("active")))

    async def _apply_ptt(self, active: bool) -> None:
        if active == self.paused:
            return
        self.paused = active
        text = "Démo en pause pendant l'émission" if active else "Démo reprise"
        log.info(text)
        try:
            await self.client.client_message(kind="module_state", module="demo",
                                             paused=active, text=text)
        except Exception as exc:              # le message est facultatif
            log.warning("message au terminal refusé : %s", exc)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s demo %(message)s")
    try:
        client = ModuleClient.from_env()
    except KeyError:
        print("Variables TRX_MODULE_NAME et TRX_MODULE_SECRET absentes : "
              "ce module est normalement lancé par le superviseur.", file=sys.stderr)
        return 2
    DemoModule(client)
    try:
        asyncio.run(client.run_forever())
    except BusRefused as exc:
        print(f"Connexion refusée par le cœur : {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
