# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Exploration d'un poste jamais essayé (`trx-qualif --explorer`) : aller le plus loin possible SANS ÉMETTRE.

Pour un expert, avant la qualification : tout ce que Hamlib déclare est sondé, pas seulement ce que TRX Remote
exploite, et chaque écart entre la déclaration et la réponse du poste devient un constat (voir coherence.py).

  1. PTT relu au repos (10 fois) : s'il n'est pas en réception, on s'arrête sans rien toucher.
  2. Indicateurs « Can get … » de dump_caps comparés aux réponses réelles (commandes de LECTURE seulement).
  3. Lecture de TOUTES les fonctions, niveaux et paramètres déclarés, deux fois : refus, instabilité, valeur hors
     de la plage déclarée, temps de réponse.
  4. Couverture : bords des plages de réception, puis une fréquence HORS couverture (doit être refusée).
  5. Commande inconnue : le flux doit rester synchronisé.
  6. Écritures avec relecture et remise à la valeur d'origine, LISTE FERMÉE de réglages sans effet sur l'émission
     (EXPLORE_WRITE_FUNCS / EXPLORE_WRITE_LEVELS) ; les réglages déjà exploités par TRX Remote sont essayés par la
     qualification (phase 1), pas ici.
  7. Rafale de lectures mêlées (fréquence, mode, PTT, S-mètre) : réponses décalées ou incohérentes.
  8. Reconnexions à rigctld.
  Fréquence et mode d'origine rétablis à la fin.

SÉCURITÉ : aucune commande de PTT (ni « T », ni set_ptt) ; aucune fonction qui peut émettre n'est écrite (VOX,
tuner, envoi de morse ou de mémoire vocale, break-in…) : la liste des écritures est FERMÉE, un nom inconnu n'est
que LU. Avant chaque écriture, le PTT est relu : poste en émission (micro du poste) = arrêt immédiat, sans
remise en état (on n'écrit rien pendant une émission).
"""
from __future__ import annotations

import asyncio
import math
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from ..gateway.cat.client import (FUNC_RE, HAMLIB_ERRORS, LEVEL_RE, CatConnectionError, CatProtocolError,
                                  RigctldClient, RigError)
from .coherence import ATTENTION, BLOQUANT, HAMLIB, INFO, POSTE, TRX, Finding, analyse_caps
from .plan import WRITE_FUNCS, WRITE_LEVELS
from .profile import HamlibProfile, LevelRange

# Écritures essayées par l'exploration : réglages de RÉCEPTION ou de manipulation sans effet sur l'émission.
# Liste FERMÉE (fail-safe) : jamais VOX, TUNER, SEND_MORSE, SEND_VOICE_MEM, SBKIN/FBKIN, TRANSCEIVE, MICGAIN,
# RFPOWER, ni le volume AF (saut de son), ni le spectre (le port B de la station s'en sert), ni LOCK. COMP et
# MONITOR_GAIN ne changent que le traitement de l'émission, sans en provoquer une ; ils sont remis à leur valeur.
EXPLORE_WRITE_FUNCS = ("TONE", "TSQL", "APF", "FAGC")
EXPLORE_WRITE_LEVELS = ("RF", "PBT_IN", "PBT_OUT", "CWPITCH", "KEYSPD", "AGC_TIME", "NOTCHF", "NOTCHF_RAW", "APF", "IF",
                        "BKINDL", "MONITOR_GAIN", "COMP")
# Commandes de LECTURE comparées aux indicateurs « Can get … » de dump_caps (protocole étendu de rigctld).
CAN_PROBES = (
    ("get Frequency", "f"), ("get Mode", "m"), ("get VFO", "v"), ("get PTT", "t"), ("get DCD", "\\get_dcd"),
    ("get Split VFO", "s"), ("get Split Freq", "i"), ("get Split Mode", "x"), ("get RIT", "j"), ("get XIT", "z"),
    ("get Tuning Step", "n"), ("get CTCSS", "c"), ("get CTCSS Squelch", "\\get_ctcss_sql"), ("get DCS", "d"),
    ("get Repeater Duplex", "r"), ("get Repeater Offset", "o"), ("get Power Stat", "\\get_powerstat"),
    ("get Info", "_"),
)
ACTION_PREFIXES = ("SEND_",)          # fonctions d'action (SEND_MORSE, SEND_VOICE_MEM) : rien à lire
ROUNDING_SPAN = 0.06                  # écart de relecture toléré comme ARRONDI du poste (6 % de la plage)
CACHE_MS = 1.0                        # réponse plus rapide : servie par le cache de rigctld, pas par le poste
UNKNOWN_LEVEL = "ZZQUALIF"            # nom de niveau qui n'existe dans aucun Hamlib
OUT_OF_RANGE_STEP_HZ = 1_000_000
REFUSALS = (-1, -4, -9, -11, -12, -15, -17)


class TxDetected(Exception):
    """Le poste est en émission (ou son PTT est illisible) : l'exploration s'arrête sans rien écrire."""


@dataclass
class Probe:
    id: str
    kind: str                 # ptt, can, read_func, read_level, read_param, coverage, sync, write_func, write_level, burst, reconnect
    target: str
    ok: bool | None           # None = sans objet (non déclaré, non tenté)
    detail: str = ""
    ms: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExplorationResult:
    probes: list[Probe] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    timings: dict[str, dict] = field(default_factory=dict)
    stopped: str = ""         # cause d'un arrêt anticipé (émission détectée…)
    restored: bool | None = None

    def to_dict(self) -> dict:
        return {"sondes": [p.to_dict() for p in self.probes], "constats": [f.to_dict() for f in self.findings],
                "temps_ms": self.timings, "arret": self.stopped, "etat_retabli": self.restored}


def rprt(exc: BaseException) -> str:
    if isinstance(exc, RigError):
        return f"RPRT {exc.code} ({HAMLIB_ERRORS.get(exc.code, 'erreur inconnue')})"
    return str(exc) or type(exc).__name__


def _number(text: str | None) -> float | None:
    try:
        value = float(str(text).split()[0])
    except (TypeError, ValueError, IndexError):
        return None
    return value if math.isfinite(value) else None


def _snap(value: float, rng: LevelRange) -> float:
    if rng.step > 0:
        value = rng.low + round((value - rng.low) / rng.step) * rng.step
    return min(rng.high, max(rng.low, value))


def _as_text(value: float, rng: LevelRange) -> str:
    integer = rng.step >= 1 and float(rng.low).is_integer() and float(rng.high).is_integer()
    return str(int(round(value))) if integer else f"{value:.6f}".rstrip("0").rstrip(".")


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
    return {"n": len(ordered), "mediane": round(statistics.median(ordered), 2), "p95": round(p95, 2),
            "max": round(ordered[-1], 2)}


class Exploration:
    def __init__(self, client: RigctldClient, profile: HamlibProfile, *, out: Callable[[str], None] = print,
                 note: Callable[[str], None] = lambda text: None, writes: bool = True, burst: int = 300,
                 settle_s: float = 1.5, reconnects: int = 3):
        self.client, self.profile, self.out, self.note = client, profile, out, note
        self.writes, self.burst, self.settle_s, self.reconnects = writes, burst, settle_s, reconnects
        self.result = ExplorationResult()
        self._times: dict[str, list[float]] = {}
        self._orig: dict = {}

    # ------------------------------------------------------------------ outils

    def probe(self, *args, **kwargs) -> Probe:
        p = Probe(*args, **kwargs)
        self.result.probes.append(p)
        return p

    def find(self, *args, **kwargs) -> None:
        self.result.findings.append(Finding(*args, **kwargs))

    async def _send(self, line: str, family: str = "") -> tuple[dict | None, BaseException | None, float]:
        """Une commande rigctld ; (valeurs, erreur, durée en ms). Une liaison perdue est reprise une fois."""
        t0 = time.perf_counter()
        try:
            values = await self.client._command(line)      # lecture générique : la couche CAT n'expose que sa liste
        except RigError as exc:
            return None, exc, (time.perf_counter() - t0) * 1000
        except (CatConnectionError, CatProtocolError, OSError) as exc:
            ms = (time.perf_counter() - t0) * 1000
            try:
                await self.client.connect()
            except CatConnectionError:
                pass
            return None, exc, ms
        ms = (time.perf_counter() - t0) * 1000
        if family:
            self._times.setdefault(family, []).append(ms)
        return values, None, ms

    async def guard(self) -> None:
        """PTT relu : toute valeur autre que 0 (ou illisible) arrête l'exploration avant d'écrire quoi que ce soit."""
        values, error, _ = await self._send("t")
        raw = None if values is None else values.get("PTT", values.get("#1"))
        if error is not None or raw is None:
            raise TxDetected(f"état PTT illisible ({rprt(error) if error else 'réponse vide'})")
        if str(raw).strip() != "0":
            raise TxDetected(f"le poste est en émission (PTT = {raw}) : micro du poste ?")

    async def _poll(self, line: str, expect: Callable[[float], bool]) -> float | None:
        end = time.monotonic() + self.settle_s
        last = None
        while True:
            values, error, _ = await self._send(line)
            if error is None and values is not None:
                last = _number(values.get("#1"))
                if last is not None and expect(last):
                    return last
            if time.monotonic() >= end:
                return last
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------------ étapes

    async def step_ptt_idle(self) -> None:
        self.out("  PTT au repos…")
        for _ in range(10):
            await self.guard()
        self.probe("ptt_idle", "ptt", "t", True, "10 lectures : réception")

    async def snapshot(self) -> None:
        self._orig = {}
        try:
            self._orig["freq"] = await self.client.get_frequency()
            self._orig["mode"] = await self.client.get_mode()
        except (RigError, CatConnectionError, CatProtocolError) as exc:
            self.find("snapshot", BLOQUANT, POSTE, "Fréquence ou mode d'origine illisibles", rprt(exc))
            raise TxDetected("état d'origine illisible : rien ne sera modifié") from exc

    async def step_can(self) -> None:
        self.out("  Indicateurs « Can get … » de Hamlib…")
        lies, extras = [], []
        for key, line in CAN_PROBES:
            declared = self.profile.can.get(key)
            values, error, ms = await self._send(line)
            if error is None:
                shown = {k: v for k, v in values.items() if not k.startswith("#")}
                empty = all(str(v).strip() in ("", "None") for v in values.values())
                self.probe(f"can_{key}", "can", line, None if empty else True,
                           "réponse vide (« None »)" if empty else f"répond ({', '.join(f'{k}={v}' for k, v in shown.items())[:120]})", ms)
                if declared is False and not empty:
                    extras.append(key)
            else:
                refused = isinstance(error, RigError) and error.code in REFUSALS
                self.probe(f"can_{key}", "can", line, None if declared is not True else False, rprt(error), ms)
                if declared is True and refused:
                    lies.append(f"{key} ({rprt(error)})")
                elif declared is True:
                    lies.append(f"{key} (pas de réponse : {rprt(error)})")
        if lies:
            self.find("can_declared_but_refused", ATTENTION, HAMLIB, "Déclaré « Can … : Y » mais refusé par le poste : " + ", ".join(lies),
                      "Hamlib annonce la lecture, le poste (ou le backend) la refuse : ne pas s'en servir.",
                      "Declared \"Can ...: Y\" but the command fails: " + ", ".join(lies))
        if extras:
            self.find("can_undeclared_but_works", INFO, HAMLIB, "Déclaré « N » mais le poste répond : " + ", ".join(extras),
                      "La réponse peut venir d'une valeur par défaut de Hamlib : à vérifier sur l'afficheur.",
                      "Declared \"N\" but the command answers: " + ", ".join(extras))

    async def step_reads(self) -> None:
        self.out("  Lecture de tout ce que Hamlib déclare…")
        p = self.profile
        groups = (("read_func", "u", p.get_functions, FUNC_RE, {}), ("read_level", "l", p.get_levels, LEVEL_RE, p.get_level_ranges),
                  ("read_param", "p", p.get_params, LEVEL_RE, {}))
        refused, unstable, outside = [], [], []
        for kind, letter, names, pattern, ranges in groups:
            for name in names:
                if not pattern.fullmatch(name):
                    self.probe(f"{kind}_{name}", kind, name, None, "nom refusé par la couche CAT (caractères)")
                    continue
                if kind == "read_func" and name.startswith(ACTION_PREFIXES):
                    self.probe(f"{kind}_{name}", kind, name, None, "fonction d'action (envoi) : lecture sans objet, non lue")
                    continue
                first, error, ms = await self._send(f"{letter} {name}", family=letter)
                if error is not None:
                    self.probe(f"{kind}_{name}", kind, name, False, rprt(error), ms)
                    refused.append(f"{name} ({rprt(error)})")
                    continue
                second, error2, _ = await self._send(f"{letter} {name}")
                v1 = first.get("#1") if first else None
                v2 = second.get("#1") if second else None
                detail = f"valeur lue : {v1}"
                ok = True
                if error2 is not None:
                    detail += f" ; 2e lecture : {rprt(error2)}"
                    unstable.append(name)
                    ok = False
                elif name not in _VARYING:
                    if v1 != v2:
                        detail += f" ; 2e lecture différente : {v2}"
                        unstable.append(name)
                rng = ranges.get(name)
                value = _number(v1)
                if rng is not None and value is not None and rng.high > rng.low and not rng.low <= value <= rng.high:
                    detail += f" ; hors de la plage déclarée {rng.low:g}..{rng.high:g}"
                    outside.append(f"{name}={value:g} ({rng.low:g}..{rng.high:g})")
                self.probe(f"{kind}_{name}", kind, name, ok, detail, ms)
        if refused:
            self.find("reads_refused", ATTENTION, HAMLIB, f"{len(refused)} lecture(s) déclarée(s) mais refusée(s)",
                      ", ".join(refused), f"{len(refused)} declared read(s) fail", ", ".join(refused))
        if unstable:
            self.find("reads_unstable", INFO, POSTE, "Lectures instables (deux lectures de suite différentes) : " + ", ".join(unstable),
                      "Normal pour un appareil de mesure ; anormal pour un réglage (cache de Hamlib ? réponse décalée ?).")
        if outside:
            self.find("reads_outside_range", INFO, HAMLIB, "Valeurs lues hors de la plage déclarée : " + ", ".join(outside),
                      "La plage de dump_caps ne décrit pas les valeurs réelles : ne pas s'en servir pour l'affichage.",
                      "Values read outside the declared range: " + ", ".join(outside))

    async def _set_freq(self, hz: int) -> tuple[BaseException | None, int | None]:
        await self.guard()
        _, error, _ = await self._send(f"F {int(hz)}", family="F")
        if error is not None:
            return error, None
        read = await self._poll("f", lambda v: int(v) == int(hz))
        return None, None if read is None else int(read)

    async def step_coverage(self) -> None:
        if not self.writes:
            self.probe("coverage", "coverage", "", None, "non fait (--lecture-seule : la fréquence n'est pas changée)")
            return
        ranges = self.profile.rx_ranges
        if not ranges:
            self.probe("coverage", "coverage", "", None, "aucune plage de réception déclarée")
            return
        self.out("  Couverture en réception (bords et hors couverture)…")
        low, high = min(r.low_hz for r in ranges), max(r.high_hz for r in ranges)
        for name, target in (("bas", low + 1000), ("haut", high - 1000)):
            error, read = await self._set_freq(target)
            ok = error is None and read == target
            detail = rprt(error) if error else f"demandé {target} Hz, relu {read}"
            self.probe(f"coverage_{name}", "coverage", str(target), ok, detail)
            if not ok:
                self.find(f"coverage_edge_{name}", ATTENTION, HAMLIB, f"Bord {name} de la couverture déclarée non accepté ({target} Hz)",
                          detail, f"Declared RX range edge not accepted ({target} Hz)", detail)
        outside = [high + OUT_OF_RANGE_STEP_HZ] + ([low - 1000] if low > 2000 else [])
        for target in outside:
            error, read = await self._set_freq(target)
            if error is not None:
                self.probe(f"coverage_out_{target}", "coverage", str(target), True, f"refusée comme il faut : {rprt(error)}")
            elif read == target:
                self.probe(f"coverage_out_{target}", "coverage", str(target), True, "acceptée et appliquée (couverture plus large que déclarée)")
                self.find(f"coverage_wider_{target}", INFO, HAMLIB, f"{target} Hz accepté hors de la couverture déclarée",
                          "Le poste reçoit plus large que dump_caps ne le dit.", f"{target} Hz accepted outside the declared RX ranges")
            else:
                self.probe(f"coverage_out_{target}", "coverage", str(target), False, f"acceptée SANS erreur mais non appliquée (relu {read})")
                self.find(f"coverage_silent_{target}", ATTENTION, HAMLIB, f"Fréquence hors couverture acceptée sans erreur mais non appliquée ({target} Hz)",
                          f"rigctld répond RPRT 0, le poste reste sur {read} Hz : une erreur doit se voir.",
                          f"Out-of-range frequency {target} Hz returns RPRT 0 but is not applied (rig stays on {read} Hz)")
        await self.restore_freq()

    async def step_sync(self) -> None:
        self.out("  Commande inconnue et resynchronisation…")
        _, error, _ = await self._send(f"l {UNKNOWN_LEVEL}")
        values, error2, _ = await self._send("f")
        freq = _number(values.get("Frequency", values.get("#1"))) if values else None
        expected = self._orig.get("freq")
        if error is None:
            self.probe("sync_unknown", "sync", UNKNOWN_LEVEL, False, "niveau inexistant accepté (RPRT 0)")
            self.find("sync_unknown_accepted", ATTENTION, HAMLIB, f"Un niveau inexistant ({UNKNOWN_LEVEL}) est accepté sans erreur",
                      "", f"Unknown level {UNKNOWN_LEVEL} returns RPRT 0")
        else:
            self.probe("sync_unknown", "sync", UNKNOWN_LEVEL, True, f"refusé : {rprt(error)}")
        ok = error2 is None and freq is not None and (expected is None or int(freq) == expected)
        self.probe("sync_after_error", "sync", "f", ok, f"fréquence relue après l'erreur : {freq}" if error2 is None else rprt(error2))
        if not ok:
            self.find("sync_lost", ATTENTION, HAMLIB, "Après une commande refusée, la réponse suivante est fausse ou absente",
                      f"attendu {expected}, relu {freq if error2 is None else rprt(error2)}",
                      "After a rejected command the next reply is wrong or missing")

    def _writable_levels(self) -> list[str]:
        p = self.profile
        return [n for n in EXPLORE_WRITE_LEVELS if n in p.set_levels and n not in WRITE_LEVELS
                and (r := p.level_ranges.get(n)) is not None and r.high > r.low]

    async def step_writes(self) -> None:
        p = self.profile
        funcs = [n for n in EXPLORE_WRITE_FUNCS if n in p.set_functions and n not in WRITE_FUNCS]
        levels = self._writable_levels()
        skipped = sorted((set(p.set_functions) - set(funcs) - set(WRITE_FUNCS)) | (set(p.set_levels) - set(levels) - set(WRITE_LEVELS)))
        if skipped:
            self.probe("writes_skipped", "write", "", None, "non écrits (hors de la liste fermée de l'exploration, ou "
                       "sans plage déclarée ; réglages de TRX Remote : essayés par la qualification) : " + ", ".join(skipped))
        if not self.writes:
            self.probe("writes", "write", "", None, "écritures désactivées (--lecture-seule)")
            return
        if not funcs and not levels:
            return
        self.out(f"  Écritures avec relecture : {', '.join(funcs + levels)}…")
        self._w = {"not_restored": [], "not_followed": [], "refused": [], "rounded": []}
        for name in funcs:
            await self._write_func(name)
        for name in levels:
            await self._write_level(name)
        w = self._w
        if w["not_followed"]:
            self.find("writes_not_followed", ATTENTION, HAMLIB, "Réglages acceptés mais la relecture ne suit pas : " + ", ".join(w["not_followed"]),
                      "La commande est peut-être ignorée ou relue dans un cache : ne pas l'exploiter sans essai sur l'afficheur.",
                      "Settings accepted (RPRT 0) but the read-back does not follow: " + ", ".join(w["not_followed"]))
        if w["refused"]:
            self.find("writes_refused", INFO, POSTE, "Réglages refusés par le poste dans son état actuel : " + ", ".join(w["refused"]),
                      "Souvent selon le mode (ex. délai de break-in en CW seulement) : à refaire dans le mode concerné.")
        if w["rounded"]:
            self.find("writes_rounded", INFO, POSTE, "Pas réel plus grossier que le pas déclaré : " + ", ".join(w["rounded"]),
                      "Le poste arrondit la valeur demandée : afficher la valeur RELUE, pas la valeur envoyée.")
        if w["not_restored"]:
            self.find("writes_not_restored", ATTENTION, POSTE, "Valeur d'origine NON rétablie : " + ", ".join(w["not_restored"]),
                      "Vérifier ces réglages sur le poste.")

    async def _write_func(self, name: str) -> None:
        values, error, _ = await self._send(f"u {name}")
        orig = _number(values.get("#1")) if values else None
        if error is not None or orig is None:
            self.probe(f"write_func_{name}", "write_func", name, None, "état initial illisible : non écrit")
            return
        orig_on = int(orig) != 0
        steps = []
        for target in (not orig_on, orig_on):
            await self.guard()
            _, error, ms = await self._send(f"U {name} {int(target)}", family="U")
            if error is not None:
                self.probe(f"write_func_{name}", "write_func", name, False, f"commande refusée : {rprt(error)}", ms)
                self._w["refused"].append(f"{name} ({rprt(error)})")
                if target == orig_on:
                    self._w["not_restored"].append(name)
                return
            read = await self._poll(f"u {name}", lambda v, t=target: (int(v) != 0) == t)
            steps.append(read is not None and (int(read) != 0) == target)
        if not steps[-1]:
            self._w["not_restored"].append(name)
        ok = all(steps)
        if not ok:
            self._w["not_followed"].append(name)
        self.probe(f"write_func_{name}", "write_func", name, ok, "inversé puis rétabli, relu à chaque fois" if ok else f"relectures : {steps}")

    async def _write_level(self, name: str) -> None:
        rng = self.profile.level_ranges[name]
        values, error, _ = await self._send(f"l {name}")
        orig = _number(values.get("#1")) if values else None
        if error is not None or orig is None:
            self.probe(f"write_level_{name}", "write_level", name, None, "valeur initiale illisible : non écrite")
            return
        if not rng.low <= orig <= rng.high:
            self.probe(f"write_level_{name}", "write_level", name, None, f"valeur actuelle {orig:g} hors de la plage déclarée : non écrite")
            return
        span = rng.high - rng.low
        tol = max(rng.step * 1.01, span * 0.02)
        coarse = span * ROUNDING_SPAN      # au-delà de tol mais sous coarse : le poste arrondit (pas réel plus gros)
        target = _snap(rng.low + span / 2, rng)
        if abs(target - orig) <= max(tol, span * 0.1):
            target = _snap(rng.low + span / 4, rng)
        results = []
        for value in (target, orig):
            await self.guard()
            _, error, ms = await self._send(f"L {name} {_as_text(value, rng)}", family="L")
            if error is not None:
                self.probe(f"write_level_{name}", "write_level", name, False, f"commande refusée : {rprt(error)}", ms)
                self._w["refused"].append(f"{name} ({rprt(error)})")
                if value == orig:
                    self._w["not_restored"].append(f"{name} (origine {orig:g})")
                return
            results.append(await self._poll(f"l {name}", lambda v, t=value: abs(v - t) <= tol))
        gaps = [None if r is None else abs(r - v) for r, v in zip(results, (target, orig))]
        if gaps[-1] is None or gaps[-1] > coarse:
            self._w["not_restored"].append(f"{name} (origine {orig:g}, relu {results[-1]})")
        exact = all(g is not None and g <= tol for g in gaps)
        rounded = not exact and all(g is not None and g <= coarse for g in gaps)
        detail = f"{orig:g} -> {_as_text(target, rng)} -> {orig:g}, relu {[None if r is None else round(r, 6) for r in results]}"
        if rounded:
            worst = max(g for g in gaps if g is not None)
            detail += f" ; arrondi par le poste (écart {worst:.3g}, pas déclaré {rng.step:g})"
            self._w["rounded"].append(f"{name} (écart {worst:.3g} pour un pas de {rng.step:g})")
        elif not exact:
            self._w["not_followed"].append(name)
        self.probe(f"write_level_{name}", "write_level", name, exact or rounded, detail)

    async def step_burst(self) -> None:
        if self.burst <= 0:
            return
        self.out(f"  Rafale de {self.burst} lectures mêlées…")
        expected_freq, modes = self._orig.get("freq"), set(self.profile.modes)
        cycle = ["f", "m", "t"] + (["l STRENGTH"] if "STRENGTH" in self.profile.get_levels else [])
        errors, wrong, first = 0, 0, ""
        for i in range(self.burst):
            line = cycle[i % len(cycle)]
            values, error, _ = await self._send(line, family=f"rafale {line}")
            if error is not None:
                errors += 1
                first = first or f"{line} : {rprt(error)}"
                continue
            raw = values.get("#1")
            if line == "t" and str(raw).strip() != "0":
                raise TxDetected(f"le poste est passé en émission pendant la rafale (PTT = {raw})")
            bad = ((line == "f" and (_number(raw) is None or (expected_freq is not None and int(_number(raw)) != expected_freq)))
                   or (line == "m" and modes and raw not in modes)
                   or (line == "l STRENGTH" and _number(raw) is None))
            if bad:
                wrong += 1
                first = first or f"{line} -> {raw!r}"
        ok = errors == 0 and wrong == 0
        self.probe("burst", "burst", " ".join(cycle), ok, f"{self.burst} lectures, {errors} erreur(s), {wrong} réponse(s) incohérente(s)"
                   + (f" (1re : {first})" if first else ""))
        if wrong:
            self.find("burst_shifted", ATTENTION, HAMLIB, f"{wrong} réponse(s) incohérente(s) pendant une rafale de lectures",
                      f"1re : {first}. Réponses décalées ou valeurs d'un cache : limiter la cadence de lecture.",
                      f"{wrong} inconsistent replies during a burst of mixed reads (first: {first})")
        elif errors:
            self.find("burst_errors", ATTENTION, POSTE, f"{errors} erreur(s) pendant une rafale de lectures", first)

    async def step_reconnect(self) -> None:
        if self.reconnects <= 0:
            return
        self.out("  Reconnexions à rigctld…")
        times, failures = [], []
        for _ in range(self.reconnects):
            await self.client.close()
            t0 = time.perf_counter()
            try:
                await self.client.connect()
                await self.client.get_frequency()
            except (RigError, CatConnectionError, CatProtocolError) as exc:
                failures.append(rprt(exc))
                continue
            times.append((time.perf_counter() - t0) * 1000)
        self.probe("reconnect", "reconnect", "", not failures,
                   f"{len(times)}/{self.reconnects} reconnexions" + (f" ; échecs : {', '.join(failures)}" if failures else ""),
                   round(statistics.median(times), 1) if times else None)
        if failures:
            self.find("reconnect_failed", ATTENTION, TRX, "Reconnexion à rigctld en échec", ", ".join(failures))

    async def restore_freq(self) -> None:
        if "freq" in self._orig:
            await self.guard()
            await self._send(f"F {self._orig['freq']}")

    async def restore(self) -> bool:
        """Fréquence d'origine. Le mode n'est JAMAIS commandé par l'exploration (sur un Icom, « M mode largeur » réécrit
        le préréglage de filtre FIL1/2/3 choisi) : il est seulement relu et comparé."""
        if not self._orig:
            return False
        await self.guard()
        _, error, _ = await self._send(f"F {self._orig['freq']}")
        try:
            ok = (error is None and await self.client.get_frequency() == self._orig["freq"]
                  and await self.client.get_mode() == self._orig["mode"])
        except (RigError, CatConnectionError, CatProtocolError):
            ok = False
        return ok

    # ------------------------------------------------------------------ déroulement

    async def run(self) -> ExplorationResult:
        self.result.findings.extend(analyse_caps(self.profile))
        steps = (self.step_can, self.step_reads, self.step_coverage, self.step_sync, self.step_writes, self.step_burst,
                 self.step_reconnect)
        try:
            await self.step_ptt_idle()
            await self.snapshot()
            for step in steps:
                self.note(f"EXPLORATION {step.__name__}")
                await step()
        except TxDetected as exc:
            self.result.stopped = str(exc)
            self.find("stopped_tx", BLOQUANT, POSTE, "Exploration arrêtée", f"{exc} ; rien n'a été remis en état.")
            self.out(f"  !!! ARRÊT : {exc}")
            self.result.timings = {k: _stats(v) for k, v in self._times.items() if v}
            return self.result
        try:
            self.result.restored = await self.restore()
        except TxDetected as exc:
            self.result.stopped, self.result.restored = str(exc), False
        if self.result.restored is False:
            self.find("not_restored", ATTENTION, POSTE, "Fréquence ou mode d'origine non rétablis",
                      f"origine : {self._orig.get('freq')} Hz, {self._orig.get('mode')}")
        self.result.timings = {k: _stats(v) for k, v in self._times.items() if v}
        self._cache_finding()
        return self.result

    def _cache_finding(self) -> None:
        """Lectures plus rapides qu'un aller-retour sur le port série : rigctld répond depuis son cache."""
        names = {"rafale f": "fréquence", "rafale m": "mode", "rafale t": "PTT"}
        cached = [label for family, label in names.items()
                  if (s := self.result.timings.get(family)) and s["n"] >= 10 and s["mediane"] < CACHE_MS]
        if not cached:
            return
        severity = ATTENTION if "PTT" in cached else INFO
        self.find("rigctld_cache", severity, HAMLIB, "Servis par le cache de rigctld (réponse en moins de "
                  f"{CACHE_MS:g} ms) : " + ", ".join(cached),
                  "Un changement fait SUR le poste (bouton, émission au micro) peut se voir avec retard. Le PTT relu peut "
                  "être celui du cache : la station ne doit pas s'y fier seule (ni pour couper, ni pour conclure qu'elle a coupé).",
                  "Replies faster than a serial round trip (cache): " + ", ".join(
                      {"fréquence": "frequency", "mode": "mode", "PTT": "PTT"}[c] for c in cached))


# Niveaux qui bougent seuls (mesures) : deux lectures différentes ne sont pas un défaut.
_VARYING = {"STRENGTH", "RAWSTR", "SWR", "ALC", "RFPOWER_METER", "RFPOWER_METER_WATTS", "COMP_METER", "VD_METER",
            "ID_METER", "TEMP_METER", "TIME"}
