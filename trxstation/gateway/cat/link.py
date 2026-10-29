# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""CatLink : maintient la liaison avec rigctld, interroge le poste et publie l'état.

Principe : une valeur inconnue vaut None, jamais « dernière valeur connue ». Si la liaison
tombe, fréquence, mode, S-mètre et PTT repassent à None : un consommateur (superviseur,
écran) ne doit pas prendre une valeur périmée pour l'état réel du poste.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace

from .capabilities import Capabilities
from .client import (RIG_ENAVAIL, RIG_ENIMPL, CatConnectionError, CatProtocolError,
                     RigctldClient, RigError)

log = logging.getLogger(__name__)

POWER_METER = "RFPOWER_METER"                       # lu à chaque cycle PENDANT l'émission
TX_METERS = ("SWR", "ALC", "COMP_METER")            # lus à tour de rôle pendant l'émission
EXTRA_FUNCTIONS = ("NR", "NB", "AIP", "COMP", "TUNER", "ANF", "MN", "RIT", "XIT")   # AIP = IP+ chez Icom ; TUNER = tuner d'antenne ; MN = notch manuel ; RIT/XIT = clarifieur
OFFSETS = ("RIT", "XIT")                            # décalages du clarifieur, lus à tour de rôle avec les lectures facultatives
EXTRA_LEVELS = ("PREAMP", "ATT", "AGC", "SQL", "RFPOWER", "VD_METER", "TEMP_METER", "NR", "NB")
PERMANENT_ERRORS = (-1, -4, -11, -15, -17)          # paramètre invalide / non géré : inutile de redemander
MAX_TRANSIENT_FAILURES = 5


@dataclass
class RigState:
    connected: bool = False            # lien avec rigctld
    frequency_hz: int | None = None
    mode: str | None = None
    passband_hz: int | None = None
    strength_db: int | None = None     # dB relatifs à S9
    ptt: bool | None = None            # None = inconnu (à traiter comme un risque)
    last_error: str = ""
    updated_at: float | None = None    # horloge murale, pour affichage
    functions: dict = field(default_factory=dict)   # NR, NB, AIP (IP+)... -> bool ; seulement ce que le poste fournit
    levels: dict = field(default_factory=dict)      # PREAMP, ATT, AGC, SQL, RFPOWER_METER, SWR, ALC... -> nombre
    split: bool | None = None          # split en service ; None = inconnu (poste qui ne le dit pas)
    tx_frequency_hz: int | None = None  # fréquence d'ÉMISSION en split ; None hors split ou inconnue
    offsets: dict = field(default_factory=dict)     # « RIT », « XIT » -> décalage en Hz (affichage ; la sécurité relit le poste)

    def to_dict(self) -> dict:
        return asdict(self)

    def _key(self) -> tuple:
        return (self.connected, self.frequency_hz, self.mode, self.passband_hz,
                self.strength_db, self.ptt, self.last_error,
                tuple(sorted(self.functions.items())), tuple(sorted(self.levels.items())),
                self.split, self.tx_frequency_hz, tuple(sorted(self.offsets.items())))


class CatLink:
    def __init__(self, host: str = "127.0.0.1", port: int = 4532, *,
                 capabilities: Capabilities | None = None, timeout: float = 3.0,
                 poll_fast_s: float = 0.25, slow_every: int = 4,
                 backoff_min_s: float = 0.5, backoff_max_s: float = 5.0):
        self.client = RigctldClient(host, port, timeout)
        self.capabilities = capabilities
        self.poll_fast_s = poll_fast_s      # cadence du S-mètre
        self.slow_every = max(1, slow_every)  # fréquence/mode/PTT : tous les N cycles
        self.backoff_min_s, self.backoff_max_s = backoff_min_s, backoff_max_s
        self._state = RigState()
        self._listeners: list[Callable[[RigState], None]] = []
        self._stop = asyncio.Event()
        self._refresh_now = True
        self._strength_supported = True
        self._disabled: set[str] = set()                # lectures facultatives abandonnées (non gérées par ce poste)
        self._failures: dict[str, int] = {}
        self._extra_index = self._tx_index = 0

    # ------------------------------------------------------------------ état

    @property
    def state(self) -> RigState:
        return replace(self._state)

    def add_listener(self, callback: Callable[[RigState], None]) -> None:
        """callback(état) est appelé à chaque changement (copie de l'état)."""
        self._listeners.append(callback)

    def _set_state(self, new: RigState) -> None:
        changed = new._key() != self._state._key()
        self._state = new
        if changed:
            for callback in self._listeners:
                try:
                    callback(replace(new))
                except Exception:  # un écouteur défaillant ne doit pas casser la liaison
                    log.exception("écouteur d'état en erreur")

    def _update(self, **changes) -> None:
        self._set_state(replace(self._state, updated_at=time.time(), **changes))

    # ------------------------------------------------------------------ boucle

    def stop(self) -> None:
        self._stop.set()

    async def _sleep(self, delay: float) -> bool:
        """Dort jusqu'à l'arrêt demandé ; retourne True si l'arrêt a été demandé."""
        try:
            await asyncio.wait_for(self._stop.wait(), delay)
            return True
        except asyncio.TimeoutError:
            return False

    async def run(self) -> None:
        backoff = self.backoff_min_s
        while not self._stop.is_set():
            try:
                await self.client.connect()
                backoff = self.backoff_min_s
                self._refresh_now = True
                self._update(connected=True, last_error="")
                await self._poll_loop()
            except (CatConnectionError, CatProtocolError, OSError) as exc:
                log.warning("liaison rigctld perdue : %s", exc)
                self._set_state(RigState(connected=False, last_error=str(exc), updated_at=time.time()))
            finally:
                await self.client.close()
            if self._stop.is_set():
                break
            if await self._sleep(backoff):
                break
            backoff = min(backoff * 2, self.backoff_max_s)
        self._set_state(RigState(connected=False, updated_at=time.time()))

    async def _poll_loop(self) -> None:
        tick = 0
        while not self._stop.is_set():
            if self._strength_supported:
                await self._refresh_strength()
            if self._state.ptt:
                await self._refresh_tx_meters()
            await self._refresh_one_extra()
            if self._refresh_now or tick % self.slow_every == 0:
                self._refresh_now = False
                await self._refresh_slow()
            tick += 1
            if await self._sleep(self.poll_fast_s):
                return

    async def _refresh_strength(self) -> None:
        try:
            self._update(strength_db=await self.client.get_strength())
        except RigError as exc:
            if exc.code in (RIG_ENAVAIL, RIG_ENIMPL):
                self._strength_supported = False  # ce poste n'a pas de S-mètre lisible
                self._update(strength_db=None)
            else:
                self._update(strength_db=None, last_error=str(exc))
        except CatProtocolError as exc:           # réponse illisible : lecture facultative, la liaison reste valide
            log.warning("S-mètre illisible, lecture désactivée : %s", exc)
            self._strength_supported = False
            self._update(strength_db=None)

    async def _refresh_slow(self) -> None:
        """Fréquence, mode et PTT sont publiés ensemble : jamais d'état à moitié rafraîchi."""
        changes: dict = {}
        try:
            frequency = await self.client.get_frequency()
            mode, passband = await self.client.get_mode()
            changes.update(frequency_hz=frequency, mode=mode, passband_hz=passband, last_error="")
        except (RigError, CatProtocolError) as exc:  # poste éteint/muet, ou réponse illisible : la liaison reste valide
            changes.update(frequency_hz=None, mode=None, passband_hz=None, last_error=str(exc))
        try:
            changes["ptt"] = await self.client.get_ptt()
        except (RigError, CatProtocolError):
            changes["ptt"] = None
        if "s:SPLIT" not in self._disabled:            # split (lecture abandonnée si le poste ne le dit pas)
            try:
                split = await self.client.get_split()
                changes["split"] = split
                changes["tx_frequency_hz"] = (await self.client.get_split_frequency() or None) if split else None
            except RigError as exc:
                changes["split"] = changes["tx_frequency_hz"] = None
                if exc.code in PERMANENT_ERRORS:
                    self._disable("s", "SPLIT", f"RPRT {exc.code}")
            except CatProtocolError as exc:
                changes["split"] = changes["tx_frequency_hz"] = None
                self._disable("s", "SPLIT", str(exc))
        if changes.get("ptt") is False:                 # fin d'émission : les mesures d'émission ne sont plus d'actualité
            stale = {k: v for k, v in self._state.levels.items() if k not in (POWER_METER, *TX_METERS)}
            if len(stale) != len(self._state.levels):
                changes["levels"] = stale
        self._update(**changes)

    # ------------------------------------------------------------------ lectures facultatives (une seule par cycle : le bus CAT est lent)

    def _supported(self, kind: str, name: str) -> bool:
        if f"{kind}:{name}" in self._disabled:             # NR et NB existent en fonction ET en niveau : clés distinctes
            return False
        caps = self.capabilities
        if kind == "o":                                    # décalage : seulement si le poste a la fonction RIT / XIT
            return caps is None or not caps.complete or not caps.functions or name in caps.functions
        if caps is not None and caps.complete:
            known = caps.functions if kind == "f" else caps.levels
            if known:
                return name in known
        return True

    async def _read_optional(self, kind: str, name: str) -> None:
        try:
            if kind == "o":
                value = await self.client.get_offset(name)
            else:
                value = await (self.client.get_func(name) if kind == "f" else self.client.get_level(name))
        except RigError as exc:
            key = f"{kind}:{name}"
            self._failures[key] = self._failures.get(key, 0) + 1
            if exc.code in PERMANENT_ERRORS or self._failures[key] >= MAX_TRANSIENT_FAILURES:
                self._disable(kind, name, f"RPRT {exc.code}")
            return
        except CatProtocolError as exc:
            self._disable(kind, name, str(exc))
            return
        self._failures[f"{kind}:{name}"] = 0
        bucket = {"f": "functions", "l": "levels", "o": "offsets"}[kind]
        merged = dict(getattr(self._state, bucket))
        merged[name] = value if kind in ("f", "o") else round(float(value), 3)
        self._update(**{bucket: merged})

    def _disable(self, kind: str, name: str, why: str) -> None:
        key = f"{kind}:{name}"
        if key not in self._disabled:
            self._disabled.add(key)
            what = {"f": "fonction", "l": "niveau", "o": "décalage", "s": "split"}.get(kind, kind)
            log.info("lecture de %s (%s) abandonnée pour ce poste (%s)", name, what, why)
        if kind == "s":
            return
        bucket = {"f": "functions", "l": "levels", "o": "offsets"}[kind]     # seulement la lecture abandonnée, pas son homonyme
        self._update(**{bucket: {k: v for k, v in getattr(self._state, bucket).items() if k != name}})

    async def _refresh_one_extra(self) -> None:
        items = ([("f", n) for n in EXTRA_FUNCTIONS] + [("l", n) for n in EXTRA_LEVELS] + [("o", n) for n in OFFSETS])
        items = [item for item in items if self._supported(*item)]
        if not items:
            return
        kind, name = items[self._extra_index % len(items)]
        self._extra_index += 1
        await self._read_optional(kind, name)

    async def _refresh_tx_meters(self) -> None:
        if self._supported("l", POWER_METER):
            await self._read_optional("l", POWER_METER)
        meters = [m for m in TX_METERS if self._supported("l", m)]
        if meters:
            name = meters[self._tx_index % len(meters)]
            self._tx_index += 1
            await self._read_optional("l", name)

    # ------------------------------------------------------------------ commandes

    async def set_frequency(self, hz: int) -> None:
        await self.client.set_frequency(hz)
        self._refresh_now = True

    def _check_known(self, kind: str, name: str) -> None:
        caps = self.capabilities
        if caps is not None and caps.complete:
            known = caps.functions if kind == "f" else caps.levels
            if known and name not in known:
                raise ValueError(f"{name} n'est pas géré par ce poste")

    async def set_function(self, name: str, on: bool) -> None:
        """NR, NB, IP+ (AIP), compresseur (COMP), tuner (TUNER). L'état affiché suit tout de suite, la lecture suivante le confirme."""
        self._check_known("f", name)
        await self.client.set_func(name, on)
        self._update(functions={**self._state.functions, name: bool(on)})

    async def set_level(self, name: str, value) -> None:
        """Voir WRITABLE_LEVELS. Plage déclarée par le poste (« Set level ») vérifiée en plus des bornes larges."""
        self._check_known("l", name)
        caps = self.capabilities
        declared = caps.level_ranges.get(name) if caps is not None and caps.level_ranges else None
        # Une liste de valeurs déclarée (« Attenuator: 20dB », « Preamp: 1dB 2dB ») prime sur la plage : Hamlib 5 déclare
        # pour l'IC-7300MK2 « Attenuator: 20dB » ET « ATT(0..12) » ; la plage bloquerait la seule valeur réelle.
        listed = {"ATT": caps.attenuators, "PREAMP": caps.preamps}.get(name) if caps is not None else None
        if listed and value in (0, *listed):
            declared = None
        if declared and isinstance(value, (int, float)) and not isinstance(value, bool) \
                and not declared[0] - 1e-9 <= value <= declared[1] + 1e-9:
            raise ValueError(f"{name} : {value!r} hors de la plage du poste ({declared[0]:g} à {declared[1]:g})")
        await self.client.set_level(name, value)
        decimal = name in ("SQL", "RFPOWER", "NR", "NB")
        self._update(levels={**self._state.levels, name: round(float(value), 3) if decimal else int(value)})

    async def set_offset(self, which: str, hz: int) -> None:
        """Décalage RIT ou XIT (ΔTX). Borne : « Max RIT/XIT » du poste si connu. La sécurité d'émission relit le poste."""
        self._check_known("f", which)
        caps = self.capabilities
        limit = (caps.max_rit_hz if which == "RIT" else caps.max_xit_hz) if caps is not None else 0
        if limit and isinstance(hz, int) and not isinstance(hz, bool) and abs(hz) > limit:
            raise ValueError(f"{which} : {hz} Hz hors de la plage du poste (±{limit} Hz)")
        await self.client.set_offset(which, hz)
        self._update(offsets={**self._state.offsets, which: hz})

    async def set_squelch(self, value: float) -> None:
        """Squelch du poste (0 à 1). Sans effet sur l'émission ; la valeur est reprise à la prochaine lecture."""
        await self.set_level("SQL", value)

    async def set_mode(self, mode: str, passband_hz: int = 0) -> None:
        caps = self.capabilities
        if caps is not None and caps.complete and mode not in caps.modes:
            raise ValueError(f"mode '{mode}' non supporté par ce poste (modes : {', '.join(caps.modes)})")
        await self.client.set_mode(mode, passband_hz)
        self._refresh_now = True
