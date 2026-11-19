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

from .capabilities import RIT_LIMIT_HZ, Capabilities
from .client import (RIG_ENAVAIL, RIG_ENIMPL, CatConnectionError, CatProtocolError,
                     RigctldClient, RigError)
from ...errors import codes
from ...errors.emit import emit_event

log = logging.getLogger(__name__)

POWER_METER = "RFPOWER_METER"                       # lu à chaque cycle PENDANT l'émission
TX_METERS = ("SWR", "ALC", "COMP_METER")            # lus à tour de rôle pendant l'émission
EXTRA_FUNCTIONS = ("NR", "NB", "AIP", "COMP", "TUNER", "ANF", "MN", "RIT", "XIT")   # AIP = IP+ chez Icom ; TUNER = tuner d'antenne ; MN = notch manuel ; RIT/XIT = clarifieur
OFFSETS = ("RIT", "XIT")                            # décalages du clarifieur, lus à tour de rôle avec les lectures facultatives
EXTRA_LEVELS = ("PREAMP", "ATT", "AGC", "SQL", "RFPOWER", "VD_METER", "TEMP_METER", "NR", "NB", "AF")
# AF = volume du poste : jamais écrit par la station, donc le meilleur indice d'un opérateur sur place (étape 206)
PERMANENT_ERRORS = (-1, -4, -11, -15, -17)          # paramètre invalide / non géré : inutile de redemander
MAX_TRANSIENT_FAILURES = 5
SLOW_REFUSAL_S = 1.5        # lecture facultative REFUSÉE après plus de 1,5 s (Hamlib a réessayé) : abandonnée aussitôt
OFF_REFUSED = (-9,)         # Icom éteint (IC-7300MK2, 2026-11-19) : « get_powerstat » REFUSÉ (RPRT -9) au lieu de « 0 »
OFF_POLL_S = 5.0            # poste éteint : seule l'alimentation (get_powerstat) est lue, toutes les 5 s (docs/alimentation-poste-cahier-des-charges.md)
POWER_SETTLE_S = 15.0       # poste qui vient de s'allumer : aucune lecture facultative abandonnée pendant ce délai


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
    vfo: str | None = None             # VFO actif (VFOA, VFOB, MEM, Main, Sub) ; None = non lisible (IC-7300MK2)
    # Alimentation : "on", "off" (éteint OU muet : Hamlib Yaesu répond 0 sans réponse du poste), None = inconnue (poste
    # qui ne déclare pas « get Power Stat »). Jamais une preuve de réception : un poste « off » n'est pas « RX confirmé ».
    power: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def _key(self) -> tuple:
        return (self.connected, self.frequency_hz, self.mode, self.passband_hz,
                self.strength_db, self.ptt, self.last_error,
                tuple(sorted(self.functions.items())), tuple(sorted(self.levels.items())),
                self.split, self.tx_frequency_hz, tuple(sorted(self.offsets.items())), self.vfo, self.power)


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
        self.ptt_cache_ok: bool | None = None           # cache du PTT de rigctld coupé ? (voir _disable_cache)
        self._cache_warned = False
        # Dernière ÉCRITURE de la station par réglage (« f:NR », « l:AF », « o:RIT » ; « * » = fréquence ou mode, qui
        # changent aussi les réglages mémorisés par bande du poste), horloge monotone. Lu par la présence sur place
        # (safety/local.py) : un changement relu juste après une écriture de la station n'est pas une action de l'opérateur.
        self.writes: dict[str, float] = {}
        # Allumage à distance (gateway/power.py) : `paused` = aucune lecture pendant l'ordre et le démarrage du poste
        # (PowerControl lit lui-même) ; `_settle_until` = poste tout juste allumé, lectures lentes NON abandonnées.
        self.paused = False
        self._settle_until = 0.0

    @property
    def power_readable(self) -> bool:
        """Le poste déclare « get Power Stat » : l'état éteint / allumé se lit (sinon `power` reste None)."""
        caps = self.capabilities
        return caps is not None and bool(getattr(caps, "can_get_power", False))

    def settle(self, seconds: float = POWER_SETTLE_S) -> None:
        """Poste qui démarre : ses refus des premières secondes ne disent rien de ce qu'il sait faire."""
        self._settle_until = time.monotonic() + seconds
        self._failures.clear()

    def mark_power(self, on: bool) -> None:
        """État d'alimentation constaté par PowerControl (après un ordre relu) : la boucle suit tout de suite."""
        if on:
            self._update(power="on")
            self._refresh_now = True
        else:
            self._mark_off()

    def _mark_off(self) -> None:
        self._update(power="off", frequency_hz=None, mode=None, passband_hz=None, strength_db=None, ptt=None,
                     split=None, tx_frequency_hz=None, vfo=None, levels={}, functions={}, offsets={}, last_error="")

    async def _check_off(self) -> bool:
        """Une lecture vient d'échouer : poste éteint ? (seulement s'il déclare « get Power Stat »). True = éteint, la
        boucle passe en veille ; False = allumé ou inconnu (l'échec est une vraie panne de lecture)."""
        if not self.power_readable or self.paused:
            return False
        try:
            on = await self.client.get_powerstat()
        except RigError as exc:
            if exc.code not in OFF_REFUSED:
                return False
            on = False                                      # Icom éteint : lecture refusée après une autre lecture ratée
        except CatProtocolError:
            return False
        if on:
            return False
        if self._state.power != "off":
            log.info("poste éteint (ou muet) : seule l'alimentation est lue, toutes les %.0f s", OFF_POLL_S)
        self._mark_off()
        return True

    def _stamp(self, key: str) -> None:
        self.writes[key] = time.monotonic()

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
                    emit_event(codes.ORT_1016, logger=log, trace=True, partie="état du poste", erreur="voir la trace")

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
                await self._disable_cache()
                backoff = self.backoff_min_s
                self._refresh_now = True
                self._update(connected=True, last_error="")
                await self._poll_loop()
            except (CatConnectionError, CatProtocolError, OSError) as exc:
                emit_event(codes.ORT_2005, logger=log, detail=str(exc))
                # Poste éteint : il le reste à travers une connexion refaite (sinon la reprise relirait tout un poste
                # éteint, lentement) ; `connected` = False dit quand même au superviseur que rigctld ne répond plus.
                off = "off" if self._state.power == "off" else None
                self._set_state(RigState(connected=False, last_error=str(exc), updated_at=time.time(), power=off))
            finally:
                await self.client.close()
            if self._stop.is_set():
                break
            if await self._sleep(backoff):
                break
            backoff = min(backoff * 2, self.backoff_max_s)
        self._set_state(RigState(connected=False, updated_at=time.time()))

    async def _disable_cache(self) -> None:
        """Cache de rigctld coupé (étape 176) : sinon, après « T 0 », la relecture du PTT renvoie pendant 0,5 à 1 s la
        valeur COMMANDÉE sans interroger le poste, et un poste resté en émission paraît coupé. rigctld est déjà lancé
        avec « -C cache_timeout=0 » ; ceci couvre un rigctld lancé autrement. Résultat dans `ptt_cache_ok` :
        True = cache coupé, False = cache ACTIF (la prise d'émission est refusée), None = commande inconnue."""
        try:
            await self.client.set_cache_timeout(0)
        except (RigError, CatProtocolError) as exc:
            emit_event(codes.ORT_2023, logger=log, detail=f"« \\set_cache 0 » refusé ({exc})")
        try:
            ms = await self.client.get_cache_timeout()          # relu même si le réglage a échoué : c'est lui qui décide
        except (RigError, CatProtocolError) as exc:
            if self.ptt_cache_ok is not None or not self._cache_warned:
                emit_event(codes.ORT_2023, logger=log, detail=f"réglage impossible ({exc})")
                self._cache_warned = True
            self.ptt_cache_ok = None
            return
        self.ptt_cache_ok = ms == 0
        if ms != 0:
            emit_event(codes.ORT_2024, logger=log, ms=ms)

    async def _poll_loop(self) -> None:
        tick = 0
        while not self._stop.is_set():
            if self.paused:                              # allumage ou extinction en cours : PowerControl lit lui-même
                if await self._sleep(self.poll_fast_s):
                    return
                continue
            if self._state.power == "off":
                await self._refresh_off()
                if await self._sleep(OFF_POLL_S):
                    return
                continue
            if self._strength_supported:
                if not await self._refresh_strength():
                    continue                             # poste éteint : rien d'autre à lire
            if self._state.ptt:
                await self._refresh_tx_meters()
            if self._state.power != "off":
                await self._refresh_one_extra()
            if self._state.power == "off":
                continue                                 # trouvé éteint pendant ce tour : la veille commence
            if self._refresh_now or tick % self.slow_every == 0:
                self._refresh_now = False
                await self._refresh_slow()
            tick += 1
            if await self._sleep(self.poll_fast_s):
                return

    async def _refresh_off(self) -> None:
        """Poste éteint : seule l'alimentation est lue. Allumé (à la main, ou par PowerControl) => lecture normale."""
        try:
            on = await self.client.get_powerstat()
        except RigError as exc:
            # Lecture refusée : Icom éteint, OU poste allumé qui refuse cette seule commande : la fréquence tranche
            if exc.code not in OFF_REFUSED:
                return
            try:
                await self.client.get_frequency()
                on = True
            except (RigError, CatProtocolError):
                return
        except CatProtocolError:
            return
        if on:
            log.info("poste de nouveau allumé : lecture normale")
            self.settle()
            self._update(power="on")
            self._refresh_now = True

    async def _refresh_strength(self) -> bool:
        """False = poste trouvé éteint (le reste du tour est sauté)."""
        try:
            self._update(strength_db=await self.client.get_strength())
        except RigError as exc:
            if exc.code in (RIG_ENAVAIL, RIG_ENIMPL):
                self._strength_supported = False  # ce poste n'a pas de S-mètre lisible
                self._update(strength_db=None)
            else:
                if await self._check_off():
                    return False
                self._update(strength_db=None, last_error=str(exc))
        except CatProtocolError as exc:           # réponse illisible : lecture facultative, la liaison reste valide
            if time.monotonic() < self._settle_until:
                return True                       # poste qui démarre : pas de conclusion
            emit_event(codes.ORT_2008, logger=log, commande="S-mètre (l STRENGTH), lecture désactivée", reponse=str(exc))
            self._strength_supported = False
            self._update(strength_db=None)
        return True

    async def _refresh_slow(self) -> None:
        """Fréquence, mode et PTT sont publiés ensemble : jamais d'état à moitié rafraîchi."""
        changes: dict = {}
        try:
            frequency = await self.client.get_frequency()
            mode, passband = await self.client.get_mode()
            changes.update(frequency_hz=frequency, mode=mode, passband_hz=passband, last_error="")
            if self.power_readable and self._state.power != "on":
                changes["power"] = "on"
        except (RigError, CatProtocolError) as exc:  # poste éteint/muet, ou réponse illisible : la liaison reste valide
            if isinstance(exc, RigError) and await self._check_off():
                return
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
        if "s:VFO" not in self._disabled:              # VFO actif (affichage seul ; lecture abandonnée si le poste ne le dit pas)
            try:
                changes["vfo"] = await self.client.get_vfo()
            except RigError as exc:
                changes["vfo"] = None
                if exc.code in PERMANENT_ERRORS:
                    self._disable("s", "VFO", f"RPRT {exc.code}")
            except CatProtocolError as exc:
                changes["vfo"] = None
                self._disable("s", "VFO", str(exc))
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
        started = time.monotonic()
        try:
            if kind == "o":
                value = await self.client.get_offset(name)
            else:
                value = await (self.client.get_func(name) if kind == "f" else self.client.get_level(name))
        except RigError as exc:
            key = f"{kind}:{name}"
            if time.monotonic() < self._settle_until or self.paused:
                return                                             # poste qui démarre : ses refus ne prouvent rien
            if exc.code not in PERMANENT_ERRORS and await self._check_off():
                return                                             # poste éteint : rien n'est abandonné
            self._failures[key] = self._failures.get(key, 0) + 1
            slow = time.monotonic() - started > SLOW_REFUSAL_S     # refus après des essais répétés de Hamlib : bloque le bus
            if exc.code in PERMANENT_ERRORS or slow or self._failures[key] >= MAX_TRANSIENT_FAILURES:
                self._disable(kind, name, f"RPRT {exc.code}" + (f" après {time.monotonic() - started:.1f} s" if slow else ""))
            return
        except CatProtocolError as exc:
            self._disable(kind, name, str(exc))
            return
        except CatConnectionError as exc:
            if time.monotonic() < self._settle_until:
                raise                                              # poste qui démarre : connexion refaite, rien d'abandonné
            # Lecture FACULTATIVE trop lente (Yaesu FTDX10 + Hamlib 4.7.2 : « u COMP » = « PR; » refusé par « ?; »,
            # réessayé par Hamlib, 2,5 s) : abandonnée pour ce poste, sinon la liaison tomberait à chaque tour et le
            # PTT deviendrait illisible. La connexion est quand même refaite (flux désynchronisé après un délai).
            self._disable(kind, name, f"pas de réponse dans le délai ({exc})")
            raise
        self._failures[f"{kind}:{name}"] = 0
        bucket = {"f": "functions", "l": "levels", "o": "offsets"}[kind]
        merged = dict(getattr(self._state, bucket))
        merged[name] = value if kind in ("f", "o") else round(float(value), 3)
        self._update(**{bucket: merged})

    def _disable(self, kind: str, name: str, why: str) -> None:
        key = f"{kind}:{name}"
        if key not in self._disabled:
            self._disabled.add(key)
            what = {"f": "fonction", "l": "niveau", "o": "décalage", "s": "lecture"}.get(kind, kind)
            emit_event(codes.ORT_2025, logger=log, nom=name, genre=what, detail=why)
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
        self._stamp("*")
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
        self._stamp("f:" + name)
        await self.client.set_func(name, on)
        self._update(functions={**self._state.functions, name: bool(on)})

    async def set_power_exact(self, value: float) -> None:
        """Puissance quelconque de 0 à 1 (station seulement : mesure de TOS) ; bornée au minimum déclaré par le poste."""
        caps = self.capabilities
        low = caps.level_ranges.get("RFPOWER", [0.0])[0] if caps is not None else 0.0
        value = max(float(low), float(value))
        self._stamp("l:RFPOWER")
        await self.client.set_power_exact(value)
        self._update(levels={**self._state.levels, "RFPOWER": round(value, 3)})

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
        self._stamp("l:" + name)
        await self.client.set_level(name, value)
        decimal = name in ("SQL", "RFPOWER", "NR", "NB")
        self._update(levels={**self._state.levels, name: round(float(value), 3) if decimal else int(value)})

    async def set_offset(self, which: str, hz: int) -> None:
        """Décalage RIT ou XIT (ΔTX). Borne : « Max RIT/XIT » du poste si connu, RIT à ±500 Hz au plus. La sécurité d'émission relit le poste."""
        self._check_known("f", which)
        caps = self.capabilities
        limit = (caps.max_rit_hz if which == "RIT" else caps.max_xit_hz) if caps is not None else 0
        if which == "RIT":
            limit = min(limit or RIT_LIMIT_HZ, RIT_LIMIT_HZ)                 # ±500 Hz même sans descripteur du poste
        if limit and isinstance(hz, int) and not isinstance(hz, bool) and abs(hz) > limit:
            raise ValueError(f"{which} : {hz} Hz hors de la plage du poste (±{limit} Hz)")
        self._stamp("o:" + which)
        await self.client.set_offset(which, hz)
        self._update(offsets={**self._state.offsets, which: hz})

    async def set_squelch(self, value: float) -> None:
        """Squelch du poste (0 à 1). Sans effet sur l'émission ; la valeur est reprise à la prochaine lecture."""
        await self.set_level("SQL", value)

    async def set_mode(self, mode: str, passband_hz: int = 0) -> None:
        caps = self.capabilities
        if caps is not None and caps.complete and mode not in caps.modes:
            raise ValueError(f"mode '{mode}' non supporté par ce poste (modes : {', '.join(caps.modes)})")
        self._stamp("*")
        await self.client.set_mode(mode, passband_hz)
        self._refresh_now = True
