"""Démonstration autonome du socle, sans TRX ni passerelle.

    python -m trxstation.modules.demo [--duree 20]

Démarre un faux cœur (bus + état simulé), lance le module factice comme un
vrai superviseur le ferait (processus séparé, priorité basse), bascule le PTT
toutes les 3 secondes et affiche ce que le terminal recevrait.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from .bus import BusServer
from .keys import load_or_create_key, module_secrets
from .launcher import ModuleLauncher, RestartPolicy
from .manifest import load_manifest
from .registry import BUILTIN_DIR


async def run(duration_s: float) -> int:
    manifests = [load_manifest(BUILTIN_DIR / "demo" / "manifest.toml")]
    tmp = Path(tempfile.mkdtemp(prefix="trx-demo-"))
    secrets = module_secrets(load_or_create_key(tmp / "modules.key"), [m.name for m in manifests])
    state = {"ptt": False, "freq": 14_074_000, "mode": "PKTUSB", "trx": "connecté"}

    def on_client(module: str, msg: dict) -> None:
        print(f"  -> terminal : [{module}] {msg.get('text', msg)}")

    def on_health(module: str, metrics: dict) -> None:
        pass

    def on_notify(module: str, st: str, message: str) -> None:
        print(f"  [superviseur] {module} ({st}) : {message}")

    bus = BusServer({m.name: m for m in manifests}, secrets,
                    state_provider=lambda: state, client_sink=on_client,
                    health_sink=on_health)
    port = await bus.start()
    print(f"Faux cœur : API interne sur 127.0.0.1:{port}")
    launcher = ModuleLauncher(manifests, secrets, bus_port=port, notify=on_notify,
                              policy=RestartPolicy(first_delay_s=1))
    sup = asyncio.ensure_future(launcher.run())

    try:
        elapsed = 0.0
        while elapsed < duration_s:
            await asyncio.sleep(3)
            elapsed += 3
            state["ptt"] = not state["ptt"]
            print(f"PTT {'ACTIF' if state['ptt'] else 'inactif'}")
            bus.publish("ptt", {"active": state["ptt"]})
            for name, st in bus.module_status().items():
                print(f"  état {name} : {st['metrics']}, dernier signal il y a "
                      f"{st['heartbeat_age_s']} s")
        await asyncio.sleep(1)
    finally:
        state["ptt"] = False
        sup.cancel()
        try:
            await sup
        except asyncio.CancelledError:
            pass
        await bus.stop()
    print("Démo terminée : le poste serait revenu en réception.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--duree", type=float, default=15.0, help="durée en secondes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(name)s %(message)s")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return asyncio.run(run(args.duree))


if __name__ == "__main__":
    sys.exit(main())
