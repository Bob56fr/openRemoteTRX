# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Garde de fin (Windows) : remet le poste en réception si le superviseur disparaît sans s'arrêter proprement.

Cahier `docs/store-microsoft-cahier-des-charges.md` § 4.1. Une mise à jour forcée ou une désinstallation du paquet
MSIX, ou le Gestionnaire des tâches, TUE net le superviseur et la passerelle ; rigctld, programme hors du paquet,
survit et garde le poste EN ÉMISSION (essai S0). La garde est un petit processus lancé par le superviseur HORS DU
TRAVAIL de l'application (`CREATE_BREAKAWAY_FROM_JOB`, qui la fait survivre à la fermeture du paquet, essai S0 bis).
Elle attend la mort du superviseur, envoie « T 0 » à rigctld, relit, arrête le rigctld lancé par la station, alerte.

Un arrêt NORMAL de la station tue la garde en dernier, après son propre « T 0 » : elle n'agit pas.
Elle ne peut que COUPER (règle : le superviseur et les outils ne déclenchent jamais une émission).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
from pathlib import Path

from ..errors import codes
from ..errors.emit import emit_event
from ..logsetup import setup_logging
from ..procutil import pid_alive
from .rigctl import RigctlProbe

log = logging.getLogger("trxstation.supervisor.guard")

NOTIFY_URL_ENV = "TRX_GUARD_NOTIFY_URL"   # adresse ntfy : par l'environnement, jamais sur la ligne de commande
RIGCTLD_PID_FILE = "rigctld-pid.json"   # dans state_dir : {"pid": …, "exe": …} du rigctld lancé par la station
RX_RETRY_S = 5.0                         # rigctld peut refuser une connexion juste après la mort du superviseur
SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INFINITE = 0xFFFFFFFF


def process_image(pid: int) -> str | None:
    """Chemin complet de l'exécutable du processus `pid` (None si introuvable)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32                                  # type: ignore[attr-defined]
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            return buf.value
        finally:
            k32.CloseHandle(handle)
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return None


def same_image(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def write_rigctld_pid(state_dir: str | Path, pid: int, exe: str | None) -> None:
    """Noté par le superviseur à chaque lancement de rigctld : la garde n'arrête QUE ce processus-là."""
    path = Path(state_dir) / RIGCTLD_PID_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": pid, "exe": exe or process_image(pid)}), encoding="utf-8")
    except OSError:
        pass                                    # sans ce fichier, la garde coupe quand même ; rigctld reste en RX


def wait_for_exit(pid: int, *, poll_s: float = 0.2) -> None:
    """Attend la fin du processus `pid` (retour immédiat s'il n'existe déjà plus)."""
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32                                  # type: ignore[attr-defined]
        handle = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            try:
                k32.WaitForSingleObject(handle, INFINITE)
            finally:
                k32.CloseHandle(handle)
            return
    while pid_alive(pid):
        time.sleep(poll_s)


def force_rx(probe: RigctlProbe, *, retry_s: float = RX_RETRY_S, sleep=time.sleep,
             clock=time.monotonic) -> tuple[bool | None, bool]:
    """(PTT lu avant ou None, réception confirmée). Réessaie pendant `retry_s` : rigctld peut être occupé."""
    deadline = clock() + retry_s
    before: bool | None = None
    while True:
        reading = probe.read()
        if reading.ok:
            before = reading.ptt if before is None else before
            if probe.force_rx():
                return before, True
        if clock() >= deadline:
            return before, False
        sleep(0.3)


def stop_rigctld(state_dir: str | Path) -> str:
    """Arrête le rigctld noté par la station, seulement si le processus est toujours CE programme-là."""
    try:
        data = json.loads((Path(state_dir) / RIGCTLD_PID_FILE).read_text(encoding="utf-8"))
        pid, exe = int(data["pid"]), str(data.get("exe") or "")
    except (OSError, ValueError, KeyError, TypeError):
        return "aucun rigctld noté par la station"
    if not pid_alive(pid):
        return f"rigctld {pid} déjà arrêté"
    if not same_image(process_image(pid), exe):
        return f"processus {pid} n'est plus rigctld : laissé"
    try:
        os.kill(pid, signal.SIGTERM)               # Windows : TerminateProcess
    except OSError as exc:
        return f"rigctld {pid} impossible à arrêter ({exc})"
    return f"rigctld {pid} arrêté"


def run(parent: int, host: str, port: int, state_dir: str | Path, *, notify=None,
        probe: RigctlProbe | None = None, retry_s: float = RX_RETRY_S) -> int:
    log.info("garde en place : superviseur %d, rigctld %s:%d", parent, host, port)
    wait_for_exit(parent)
    probe = probe or RigctlProbe(host, port)
    before, rx = force_rx(probe, retry_s=retry_s)
    detail = stop_rigctld(state_dir)
    avant = "inconnu" if before is None else ("émission" if before else "réception")
    if rx:
        emit_event(codes.ORT_8027, logger=log, ptt_avant=avant, rigctld=detail)
    else:
        emit_event(codes.ORT_8028, logger=log, ptt_avant=avant, rigctld=detail)
    if notify is not None:
        try:
            notify(codes.ORT_8027 if rx else codes.ORT_8028, ptt_avant=avant, rigctld=detail)
        except Exception:                          # noqa: BLE001 - une alerte ratée ne change rien au poste
            pass
    return 0 if rx else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-guard", description="Garde de fin de la station (Windows)")
    ap.add_argument("--parent", type=int, required=True, help="numéro du superviseur à surveiller")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True, help="port de rigctld")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--notify-lang", default="fr")
    args = ap.parse_args(argv)
    setup_logging("garde")
    notify = None
    url = os.environ.get(NOTIFY_URL_ENV, "")
    if url:
        from .notify import Notifier
        notifier = Notifier(url, threaded=False, lang=args.notify_lang)
        notify = notifier.alert
    try:
        return run(args.parent, args.host, args.port, args.state_dir, notify=notify)
    except Exception:                              # noqa: BLE001 - dernière ligne : journaliser
        emit_event(codes.ORT_8028, logger=log, trace=True, ptt_avant="inconnu", rigctld="erreur inattendue (voir la trace)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
