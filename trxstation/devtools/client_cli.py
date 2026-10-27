# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Client interactif de développement : se connecte à une passerelle qui tourne, enregistre le son
reçu dans un WAV (pour l'écouter) et envoie une tonalité en guise de micro.

    python -m trxstation.devtools.client_cli --url http://127.0.0.1:8443 --id phone [--password <mot de passe>]

Commandes : t = PTT (bascule)   s = stop   f <Hz> = fréquence   m <mode> = mode   q = quitter
Nécessite aiortc et aiohttp (pip install -e ".[audio]").
"""
from __future__ import annotations

import argparse
import asyncio
import getpass

from ..asyncio_noise import install_quiet_handler
from .fake_client import FakeClient, ToneTrack


def describe_state(state: dict) -> str:
    ptt, rig = state["ptt"], state["rig"]
    freq = "--" if rig["frequency_hz"] is None else f"{rig['frequency_hz']:,}".replace(",", " ")
    owner = f" ({ptt['owner']})" if ptt["owner"] else ""
    return f"PTT {ptt['state']}{owner} | {freq} Hz {rig['mode'] or '--'} | S {rig['strength_db']} dB | " \
           f"audio RX {state['audio'].get('rx_db', '--')} dBFS"


async def watch(client: FakeClient) -> None:
    last = None
    while True:
        if client.state is not None:
            line = describe_state(client.state)
            if line != last:
                print(f"\r[état] {line}\n> ", end="", flush=True)
                last = line
        await asyncio.sleep(0.25)


async def main_async(args: argparse.Namespace) -> None:
    install_quiet_handler(asyncio.get_running_loop())
    client = FakeClient(args.url, args.id, args.password, track=ToneTrack(args.tone, -10.0, active=True),
                        record_wav=args.record)
    await client.connect()
    print(f"Connecté en tant que « {args.id} ». Le son reçu est enregistré dans {args.record}.")
    print("Commandes : t (PTT) | s (stop) | f <Hz> | m <mode> | q (quitter)")
    if not args.no_heartbeat:
        client.start_heartbeat()
    watcher = asyncio.ensure_future(watch(client))
    try:
        while True:
            line = (await asyncio.to_thread(input, "> ")).strip().split()
            if not line:
                continue
            command, *rest = line
            if command == "q":
                return
            try:
                if command == "t":
                    result = await client.command("toggle")
                elif command == "s":
                    result = await client.command("stop")
                elif command == "f" and rest:
                    result = await client.command("set_frequency", hz=int(rest[0]))
                elif command == "m" and rest:
                    result = await client.command("set_mode", mode=rest[0])
                else:
                    print("commande inconnue")
                    continue
            except (asyncio.TimeoutError, ValueError) as exc:
                print(f"erreur : {exc!r}")
                continue
            print("OK" if result.get("ok") else f"REFUSÉ : {result.get('reason')} {result.get('detail', '')}")
    finally:
        watcher.cancel()
        await client.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8443")
    ap.add_argument("--id", required=True)
    ap.add_argument("--password", help="mot de passe (sinon demandé sans affichage)")
    ap.add_argument("--tone", type=float, default=1000.0, help="fréquence de la tonalité envoyée comme micro")
    ap.add_argument("--record", default="rx_from_station.wav", help="fichier WAV du son reçu")
    ap.add_argument("--no-heartbeat", action="store_true", help="ne pas envoyer de heartbeat (teste la coupure)")
    try:
        args = ap.parse_args()
        if not args.password:
            args.password = getpass.getpass(f"Mot de passe de {args.id} : ")
        asyncio.run(main_async(args))
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
