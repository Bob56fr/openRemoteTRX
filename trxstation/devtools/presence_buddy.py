# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Membre d'essai de la présence de groupe : une station JETABLE (aucun poste) qui rejoint un groupe avec une invitation,
annonce une fréquence fictive et change de statut, puis quitte le groupe et se désinscrit du relais.

    python -m trxstation.devtools.presence_buddy "<invitation>" [--minutes 20] [--pseudo ESSAI-PC]
                                                 [--freq 14205000] [--mode USB]

Pour voir la présence dans la page et l'application sans second poste. N'agit sur aucune station : il ne parle qu'au
relais (même code que le module « presence »). Ctrl+C : il quitte le groupe et se désinscrit quand même.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

from ..presence.engine import ActionRefused, Engine
from ..presence.identity import Identity
from ..presence.relay import HttpRelay
from ..presence.store import Store

STEP_S = 47                       # le relais permet une requête par station toutes les 45 s


def say(text: str) -> None:
    print(time.strftime("%H:%M:%S"), text, flush=True)


async def run(args) -> int:
    invite_relay = args.invitation.split("/i#", 1)[0] if "/i#" in args.invitation else args.relay
    ident = Identity.generate()
    store = Store(Path(tempfile.mkdtemp(prefix="orx-buddy-")))
    store.data["pseudo"] = args.pseudo
    eng = Engine(store, ident, HttpRelay(invite_relay, ident, version="essai"), relay_url=invite_relay, version="essai")
    g = None
    try:
        await eng.cycle()
        if not store.data["registered"]:
            say(f"enregistrement refusé : {eng.problem}")
            return 1
        say(f"{args.pseudo} enregistrée auprès de {invite_relay}")
        g = await eng.join(args.invitation, "Essai")
        say("adhésion demandée : validée à la prochaine requête de la station de l'administrateur (1 à 2 min)")
        eng.set_share(g, level="f")
        eng.set_rig(args.freq, args.mode)
        deadline = time.monotonic() + args.minutes * 60
        while time.monotonic() < deadline:
            await asyncio.sleep(STEP_S)
            left = deadline - time.monotonic()
            phase = (args.minutes * 60 - left) / (args.minutes * 60)
            if phase < 0.4:
                eng.on_activity()                                      # En RX (vert)
            elif phase < 0.7:
                eng.on_ptt(True)                                       # En QSO (rouge) ; aucune émission réelle
            else:
                eng.on_ptt(False)                                      # reste en QSO 10 min, puis Absent
            await eng.cycle()
            status = store.groups.get(g, {}).get("status", "?")
            say(f"groupe : {status} ; statut publié {eng.tracker.status(time.time()).code} ; {int(left // 60)} min restantes"
                + (f" ; problème : {eng.problem}" if eng.problem else ""))
            if status == "removed":
                say("exclu du groupe par l'administrateur : fin de l'essai")
                break
        return 0
    finally:
        if g is not None and g in store.groups:
            try:
                await eng.leave(g)
                say("groupe quitté")
            except ActionRefused as exc:
                say(f"départ : {exc.reason}")
        try:
            code, _ = await eng.relay.post("unregister", {})
            say(f"désinscrite du relais ({code})")
        except Exception as exc:
            say(f"désinscription impossible : {exc}")
        await eng.relay.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.devtools.presence_buddy", description="Membre d'essai")
    ap.add_argument("invitation", help="lien d'invitation complet (menu 5.3 ou « Inviter » de la page)")
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--pseudo", default="ESSAI-PC")
    ap.add_argument("--freq", type=int, default=14_205_000)
    ap.add_argument("--mode", default="USB")
    ap.add_argument("--relay", default="https://rf-diy.com/orx-relay/public")
    args = ap.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
