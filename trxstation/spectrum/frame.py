# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Balayages du spectre vers les clients : format binaire compact et diffusion « au plus récent ».

Canal WebRTC « spectrum » ouvert par le client, NON ORDONNÉ et SANS RENVOI (maxRetransmits 0) : un balayage
perdu est remplacé par le suivant, jamais renvoyé ; il ne retarde ni le canal « control » ni l'audio.

Trame (petit-boutiste), FRAME_VERSION 1 :
  [0]     version (1)
  [1]     mode du poste (0 centré, 1 fixe, 2/3 défilement ; 255 inconnu)
  [2]     drapeaux : bit 0 = hors plage
  [3]     réservé (0)
  [4:8]   numéro de balayage (uint32, croissant ; le client jette un numéro plus ancien que le dernier vu)
  [8:12]  fréquence du bord gauche, Hz (uint32)
  [12:16] fréquence du bord droit, Hz (uint32)
  [16:]   points, un octet chacun, de 0 à LEVEL_MAX
Bords : si la 2e valeur de l'en-tête dépasse la 1re, ce sont les bornes (mode fixe, et défilement vu sur un
IC-7300MK2) ; sinon centre ± demi-largeur (mode centré). Déduit des relevés, à confirmer à l'écran.
"""
from __future__ import annotations

import struct
from collections.abc import Callable

from .civ import LEVEL_MAX, Sweep

FRAME_VERSION = 1
HEADER = struct.Struct("<BBBBIII")
MAX_BUFFERED = 64 * 1024              # au-delà, le client ne suit pas : on saute des balayages plutôt que d'empiler
U32 = 0xFFFFFFFF


def edges(sweep: Sweep) -> tuple[int, int] | None:
    f1, f2 = sweep.f1_hz, sweep.f2_hz
    if f1 is None or f2 is None or f1 <= 0 or f2 <= 0:
        return None
    if f2 > f1:
        return f1, f2
    return max(0, f1 - f2), f1 + f2


def encode(sweep: Sweep, seq: int) -> bytes | None:
    """Trame binaire, None si le balayage est inutilisable (fréquences illisibles, aucun point)."""
    bounds = edges(sweep)
    if bounds is None or not sweep.points or bounds[1] > U32:
        return None
    mode = sweep.mode if isinstance(sweep.mode, int) and 0 <= sweep.mode < 255 else 255
    flags = 1 if sweep.out_of_range else 0
    points = bytes(min(max(int(v), 0), LEVEL_MAX) for v in sweep.points)
    return HEADER.pack(FRAME_VERSION, mode, flags, 0, seq & U32, bounds[0], bounds[1]) + points


class SpectrumFanout:
    """Envoie chaque trame aux clients abonnés QUI REGARDENT la vue HF, au plus `max_fps` par seconde chacun,
    sans jamais empiler.

    Deux conditions par client : un canal « spectrum » ouvert (`add`) ET la vue HF affichée (`watch`, commande
    `spectrum_watch`). Vue fermée = rien n'est envoyé : pas de données mobiles consommées pour rien.
    """

    def __init__(self, max_fps: int, clock: Callable[[], float]):
        self.min_interval = 1.0 / max(1, max_fps)
        self.clock = clock
        self._subs: dict[str, dict] = {}
        self._watching: set[str] = set()     # indépendant du canal : la demande peut précéder son ouverture
        self.seq = 0

    def add(self, client_id: str, send: Callable[[bytes], None], buffered: Callable[[], int]) -> None:
        self._subs[client_id] = {"send": send, "buffered": buffered, "last": float("-inf"), "sent": 0, "skipped": 0}

    def remove(self, client_id: str, send: Callable[[bytes], None] | None = None) -> None:
        """`send` : ne désabonne que si c'est encore ce canal (la fermeture tardive d'une ancienne connexion
        ne doit pas désabonner la nouvelle). Sans `send` (client parti) : la demande de vue est oubliée aussi."""
        sub = self._subs.get(client_id)
        if sub is not None and (send is None or sub["send"] is send):
            del self._subs[client_id]
        if send is None:
            self._watching.discard(client_id)

    def watch(self, client_id: str, on: bool) -> None:
        """Vue HF ouverte (`on`) ou fermée chez ce client."""
        if on:
            self._watching.add(client_id)
        else:
            self._watching.discard(client_id)

    def watching(self, client_id: str) -> bool:
        return client_id in self._watching

    def __len__(self) -> int:
        return len(self._subs)

    def publish(self, sweep: Sweep) -> int:
        """Renvoie le nombre de clients servis. Une erreur d'envoi désabonne ce client seulement."""
        targets = [(c, s) for c, s in self._subs.items() if c in self._watching]
        if not targets:
            return 0
        self.seq += 1
        frame = encode(sweep, self.seq)
        if frame is None:
            return 0
        now, served = self.clock(), 0
        for client_id, sub in targets:
            if now - sub["last"] < self.min_interval:
                continue
            try:
                if sub["buffered"]() > MAX_BUFFERED:
                    sub["skipped"] += 1
                    continue
                sub["send"](frame)
            except Exception:                   # noqa: BLE001 - canal fermé entre-temps : désabonné (une reconnexion réabonne)
                self.remove(client_id, sub["send"])
                continue
            sub["last"], sub["sent"] = now, sub["sent"] + 1
            served += 1
        return served
