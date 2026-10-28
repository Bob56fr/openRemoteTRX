# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Moteur de qualification d'un poste (lot Q1) : trois phases, sur la base de trx-hwtest.

  Phase 1, automatique, SANS émission : socle fréquence et mode, filtres, lectures et écritures
           générées depuis Hamlib, endurance et temps de réponse CAT. L'état du poste est relevé
           avant et rétabli après.
  Phase 2, guidée : l'opérateur confirme ce qu'il voit et entend (réponses « déclaratives »).
  Phase 3, émission : étapes de trx-hwtest (PTT, audio TX, pannes), chacune après confirmation,
           plus la perte de la liaison CAT pendant l'émission, simulée par le relais de trace.
  Enfin, et seulement si l'opérateur le demande : reprise après débranchement USB (en réception).

SÉCURITÉ : toute émission passe par PttController (hérité de trx-hwtest) ; toutes les écritures
passent par PttController, qui les refuse hors réception confirmée. Le tuner n'est jamais activé
automatiquement. La puissance n'est jamais laissée plus haute qu'au départ.
"""
from __future__ import annotations

import asyncio
import json
import math
import statistics
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from ..answers import typed, yes_no
from ..config import Config
from ..devtools.hwtest import PREFLIGHT, HwTest
from ..gateway.cat.client import FLOAT_LEVELS, HAMLIB_ERRORS, INT_LEVELS, POWER_STEPS, RigError
from .plan import DECLARATIF, FIXE, GENERE, SOCLE, TestPlan, build_plan, core_modes, label, render_plan
from .profile import HamlibProfile
from .results import Check, compute_verdict, draft_sheet
from .sheet import render_sheet
from .trace import TraceProxy

DEFAULT_BANDS_MHZ = ((3.5, 3.8), (7.0, 7.2), (14.0, 14.35), (21.0, 21.45), (28.0, 29.7))
FREQ_OFFSET_HZ = 123              # décalage « au hertz » pour vérifier la résolution
MAX_RESOLUTION_HZ = 10
POWER_TOLERANCE = 0.015           # même tolérance que l'application (±1,5 %)
TOOL_NAME = "trx-qualif"

# Résultats de trx-hwtest -> tests de la qualification.
HW_MAP = {"CAT": ("cat", SOCLE), "Audio RX": ("audio_rx", SOCLE), "Audio (ouverture)": ("audio_rx", SOCLE),
          "PTT": ("ptt_cycle", SOCLE), "PTT / Audio TX / Pannes": ("ptt_cycle", SOCLE),
          "Audio TX": ("audio_tx", FIXE), "Panne : perte du heartbeat": ("drill_heartbeat", FIXE),
          "Panne : déconnexion du client": ("drill_disconnect", FIXE), "Pannes": ("drills", FIXE),
          "Panne : perte de la liaison CAT": ("cat_loss_rx", SOCLE),
          "Bande d'essai": ("prep_band", "preparation"), "Mode d'émission": ("prep_mode", "preparation")}
# Échecs dus à l'installation (configuration, câble, carte son) et non au poste : qualification
# INCOMPLÈTE plutôt que refus, pour ne jamais refuser un poste sur une erreur de réglage.
SETUP_FAILURES = {"Audio (ouverture)", "PTT / Audio TX / Pannes"}


def _yes(answer: str) -> bool | None:
    return yes_no(answer)


def _rprt(exc: Exception) -> str:
    if isinstance(exc, RigError):
        return f"RPRT {exc.code} ({HAMLIB_ERRORS.get(exc.code, 'erreur inconnue')})"
    return str(exc) or type(exc).__name__


def _mhz(hz: int | None) -> str:
    if hz is None:
        return "?"
    text = f"{hz:09d}"
    return f"{int(text[:-6])}.{text[-6:-3]}.{text[-3:-1]}"


class Qualification(HwTest):
    def __init__(self, cfg: Config, *, profile: HamlibProfile, dump_text: str = "", proxy: TraceProxy | None = None,
                 endurance_cycles: int = 1000, cat_cut_s: float = 1.5, settle_s: float = 2.0, **kwargs):
        super().__init__(cfg, capabilities=profile.caps, **kwargs)
        self.profile, self.dump_text, self.proxy = profile, dump_text, proxy
        self.plan: TestPlan = build_plan(profile)
        self.endurance_cycles, self.cat_cut_s, self.settle_s = endurance_cycles, cat_cut_s, settle_s
        self.checks: list[Check] = []
        self.journal: list[str] = []
        self.firmware = ""
        self.started_at = datetime.now(timezone.utc)
        self._orig: dict = {}
        self._own_record = False
        self._write_ok: set[str] = set()
        user_out = self.out
        self.out = lambda text: (self.journal.append(text), user_out(text))[-1]

    # ------------------------------------------------------------------ résultats

    def record(self, name: str, ok: bool | None, detail: str) -> bool:
        mapped = None if self._own_record else HW_MAP.get(name)
        if mapped is None and not self._own_record and name.startswith("Panne : TOT"):
            mapped = ("drill_tot", FIXE)
        if mapped is not None:
            stored = ok
            if ok is False and (name in SETUP_FAILURES or (name == "CAT" and "pas lisible" not in detail)):
                detail += " — à corriger avant de conclure (qualification incomplète)"
                stored = None
            self.checks.append(Check(mapped[0], name, mapped[1], stored, detail))
        # La valeur renvoyée pilote le déroulé (arrêt après un échec) : c'est toujours le résultat RÉEL.
        return super().record(name, ok, detail)

    def check(self, item_id: str, name: str, category: str, ok: bool | None, detail: str, **data) -> bool:
        self.checks.append(Check(item_id, name, category, ok, detail, data))
        self._own_record = True
        try:
            return super().record(name, ok, detail)
        finally:
            self._own_record = False

    def note(self, text: str) -> None:
        if self.proxy is not None:
            self.proxy.note(text)

    # ------------------------------------------------------------------ outils

    async def _poll(self, read: Callable[[], Awaitable], expect: Callable[[object], bool]):
        """Relit jusqu'à obtenir la valeur attendue ou épuiser `settle_s` ; renvoie la dernière lecture."""
        end = time.monotonic() + self.settle_s
        last: object = None
        while True:
            try:
                last = await read()
            except Exception as exc:          # une erreur de lecture est un résultat, pas un plantage
                last = exc
            if not isinstance(last, Exception) and expect(last):
                return last
            if time.monotonic() >= end:
                return last
            await asyncio.sleep(0.1)

    def _items(self, action: str):
        return [i for i in self.plan.items if i.action == action]

    async def _snapshot(self) -> None:
        """Relève ce que la phase 1 va modifier, pour le rétablir ensuite."""
        client = self.link.client
        self._orig = {"funcs": {}, "levels": {}}
        try:
            self._orig["freq"] = await client.get_frequency()
            self._orig["mode"] = await client.get_mode()
        except Exception as exc:
            self.say(f"  (état initial illisible : {_rprt(exc)})")
        for item in self._items("write_func"):
            try:
                self._orig["funcs"][item.target] = await client.get_func(item.target)
            except Exception:
                pass
        for item in self._items("write_level"):
            try:
                self._orig["levels"][item.target] = await client.get_level(item.target)
            except Exception:
                pass

    async def _restore(self) -> None:
        """Rétablit l'état relevé, en réception seulement (PttController refuse sinon)."""
        if not self._orig or self.ctrl is None or self.ctrl.snapshot().state != "RX":
            return
        problems = []
        for name, on in self._orig["funcs"].items():
            try:
                await self.ctrl.set_function(name, on)
            except Exception as exc:
                problems.append(f"{label(name)} ({_rprt(exc)})")
        for name, value in self._orig["levels"].items():
            restore = self._level_value(name, value)
            if restore is None:
                continue
            try:
                await self.ctrl.set_level(name, restore)
            except Exception as exc:
                problems.append(f"{label(name)} ({_rprt(exc)})")
        if "mode" in self._orig:
            try:
                await self.ctrl.set_mode(self._orig["mode"][0], self._orig["mode"][1])
            except Exception as exc:
                problems.append(f"mode ({_rprt(exc)})")
        if "freq" in self._orig:
            try:
                await self.ctrl.set_frequency(self._orig["freq"])
            except Exception as exc:
                problems.append(f"fréquence ({_rprt(exc)})")
        if problems:
            self.say("  !!! état d'origine NON rétabli pour : " + ", ".join(problems) + " : vérifie le poste")

    @staticmethod
    def _level_value(name: str, value: float):
        """Valeur acceptée par la couche CAT pour rétablir un niveau, ou None si on ne doit pas y toucher."""
        if name in INT_LEVELS:                          # AGC, PREAMP, ATT : entiers (la relecture donne un décimal)
            low, high = INT_LEVELS[name]
            rounded = round(value)
            return rounded if low <= rounded <= high else None
        if name == "RFPOWER":
            return next((s for s in POWER_STEPS if abs(s - value) <= POWER_TOLERANCE), None)
        low, high = FLOAT_LEVELS.get(name, (0.0, 1.0))
        return min(high, max(low, round(float(value), 3)))

    # ------------------------------------------------------------------ phase 1 : automatique

    async def phase_auto(self) -> None:
        self.say("\n=== Phase 1 : tests automatiques (réception seulement, aucune émission) ===")
        self.note("PHASE 1")
        await self._snapshot()
        try:
            await self.test_frequency()
            await self.test_modes()
            await self.test_filters()
            await self.test_reads()
            await self.test_writes()
        finally:
            await self._restore()
        await self.test_endurance()

    async def test_frequency(self) -> None:
        bands = [(b.low_mhz, b.high_mhz) for b in self.cfg.bands] or list(DEFAULT_BANDS_MHZ)
        targets = [round((low + high) / 2 * 1000) * 1000 + FREQ_OFFSET_HZ for low, high in bands][:8]
        accepted, refused, diffs, lines = 0, [], [], []
        self.note("TEST freq_rw")
        for target in targets:
            try:
                await self.ctrl.set_frequency(target)
            except Exception as exc:
                refused.append(f"{_mhz(target)} ({_rprt(exc)})")
                continue
            accepted += 1
            read = await self._poll(self.link.client.get_frequency, lambda v, t=target: v == t)
            if isinstance(read, Exception) or read is None:
                diffs.append(math.inf)
                lines.append(f"{_mhz(target)} -> illisible")
            else:
                diffs.append(abs(read - target))
                lines.append(f"{_mhz(target)} -> {_mhz(read)}")
        needed = min(2, len(targets))
        worst = max(diffs) if diffs else math.inf
        ok = accepted >= needed and worst <= MAX_RESOLUTION_HZ
        resolution = 1 if worst == 0 else (int(worst) if worst <= MAX_RESOLUTION_HZ else None)
        detail = f"{accepted}/{len(targets)} fréquences acceptées ; " + ", ".join(lines)
        if refused:
            detail += " ; refusées (hors couverture ?) : " + ", ".join(refused)
        if ok and worst > 0:
            detail += f" ; résolution du poste ≈ {int(worst)} Hz"
        data = {"resolution_hz": resolution} if resolution else {}
        self.check("freq_rw", "Fréquence : écriture et relecture", SOCLE, ok, detail, **data)

    async def test_modes(self) -> None:
        modes = self.profile.modes or self.caps.modes
        core = core_modes(self.profile) or modes
        passed = set()
        self.note("TEST mode_rw")
        for mode in modes:
            try:
                await self.ctrl.set_mode(mode)
            except Exception as exc:
                self.check(f"mode_{mode}", f"Mode {mode}", GENERE, False, f"commande refusée : {_rprt(exc)}")
                continue
            read = await self._poll(self.link.client.get_mode, lambda v, m=mode: v[0] == m)
            ok = not isinstance(read, Exception) and read is not None and read[0] == mode
            if ok:
                passed.add(mode)
            got = _rprt(read) if isinstance(read, Exception) else (read[0] if read else "?")
            self.check(f"mode_{mode}", f"Mode {mode}", GENERE, ok, f"relu : {got}")
        missing = [m for m in core if m not in passed]
        self.check("mode_rw", "Mode : écriture et relecture", SOCLE, not missing,
                   f"modes du socle relus : {', '.join(m for m in core if m in passed) or 'aucun'}"
                   + (f" ; en échec : {', '.join(missing)}" if missing else ""))

    async def test_filters(self) -> None:
        filters = {m: w for m, w in self.caps.filters.items() if m in core_modes(self.profile)}
        if not filters:
            self.check("filters", "Filtres (largeur de bande)", FIXE, None, "Hamlib ne déclare aucune largeur pour ces modes")
            return
        self.note("TEST filters")
        # Un Icom choisit FIL1/2/3 et relit la largeur RÉGLÉE dans le poste : une valeur différente de Hamlib n'est
        # pas un défaut si chaque demande sélectionne bien un filtre distinct (même mode relu, largeurs distinctes).
        bad, lines, adjusted = [], [], []
        for mode, widths in filters.items():
            got_widths = []
            for width in widths:
                try:
                    await self.ctrl.set_mode(mode, width)
                except Exception as exc:
                    bad.append(f"{mode} {width} Hz ({_rprt(exc)})")
                    continue
                read = await self._poll(self.link.client.get_mode, lambda v, m=mode, w=width: v == (m, w))
                same_mode = not isinstance(read, Exception) and read is not None and read[0] == mode
                got = read[1] if same_mode else None
                lines.append(f"{mode} {width}->{got}")
                got_widths.append(got)
            if None in got_widths:
                bad.append(f"{mode} : mode ou largeur illisible après la commande")
            elif got_widths != list(widths):
                if len(set(got_widths)) == len(widths):
                    adjusted.append(mode)
                else:
                    bad.append(f"{mode} : les largeurs demandées ne sélectionnent pas des filtres distincts ({got_widths})")
        detail = ("en échec : " + ", ".join(bad) + " ; ") * bool(bad) + "relus : " + ", ".join(lines)
        if adjusted and not bad:
            detail += f" ; largeurs du poste différentes de Hamlib pour {', '.join(adjusted)} (réglages FIL du poste)"
        self.check("filters", "Filtres (largeur de bande)", FIXE, not bad, detail)

    async def test_reads(self) -> None:
        self.note("TEST lectures")
        client = self.link.client
        for item in self._items("read_func") + self._items("read_level"):
            try:
                value = await (client.get_func(item.target) if item.action == "read_func" else client.get_level(item.target))
            except Exception as exc:
                self.check(item.id, item.label, GENERE, False, _rprt(exc))
                continue
            self.check(item.id, item.label, GENERE, True, f"valeur lue : {value}")

    async def test_writes(self) -> None:
        self.note("TEST écritures")
        for item in self.plan.items:
            if item.action == "manual":
                self.check(item.id, item.label, GENERE, None, item.note)
            elif item.action == "write_func":
                await self._write_func(item.id, item.label, item.target)
            elif item.action == "write_level":
                await self._write_level(item.id, item.label, item.target)

    async def _write_func(self, item_id: str, name_label: str, name: str) -> None:
        client = self.link.client
        orig = self._orig.get("funcs", {}).get(name)
        if orig is None:
            self.check(item_id, name_label, GENERE, False, "état initial illisible : écriture non tentée")
            return
        steps = []
        for target in (not orig, orig):
            try:
                await self.ctrl.set_function(name, target)
            except Exception as exc:
                self.check(item_id, name_label, GENERE, False, f"commande refusée : {_rprt(exc)}")
                return
            read = await self._poll(lambda: client.get_func(name), lambda v, t=target: v == t)
            steps.append(read == target)
        ok = all(steps)
        if ok:
            self._write_ok.add(name)
        self.check(item_id, name_label, GENERE, ok, "activé puis rétabli, relu à chaque fois" if ok
                   else "la valeur relue ne suit pas la commande")

    async def _write_level(self, item_id: str, name_label: str, name: str) -> None:
        client = self.link.client
        orig = self._orig.get("levels", {}).get(name)
        if orig is None:
            self.check(item_id, name_label, GENERE, False, "valeur initiale illisible : écriture non tentée")
            return
        restore = self._level_value(name, orig)
        if restore is None:
            why = "hors des paliers de TRX Remote : non modifiée" if name == "RFPOWER" else "hors plage : non modifiée"
            self.check(item_id, name_label, GENERE, None, f"valeur actuelle {orig} {why}")
            return
        note = ""
        if name == "SQL":
            target, tol = (0.3 if abs(orig - 0.3) > 0.1 else 0.6), 0.02
        elif name == "RFPOWER":
            lower = [s for s in POWER_STEPS if s < restore]                     # jamais plus fort qu'au départ si possible
            target = lower[-1] if lower else next(s for s in POWER_STEPS if s > restore)
            tol = POWER_TOLERANCE
        elif name in FLOAT_LEVELS:                      # NR, NB : milieu de la plage (ou un cinquième si on y est déjà)
            low, high = FLOAT_LEVELS[name]
            middle = low + (high - low) / 2
            target = round(middle if abs(restore - middle) > (high - low) * 0.1 else low + (high - low) / 5, 3)
            tol = (high - low) * 0.07                   # le poste arrondit à son pas (NR : 1/15)
        else:
            if name == "AGC":
                values = self.profile.agc_levels
            elif name == "ATT":
                values = (0, *getattr(self.profile, "attenuators", ()))
            else:
                values = (0, *self.profile.preamps)
            low, high = INT_LEVELS.get(name, (0, 30))
            choices = [v for v in values if v != restore and low <= v <= high]
            if name == "AGC":
                choices.sort(key=lambda v: v == 0)      # AGC arrêtée (0 = OFF) en dernier recours seulement
            target, tol = (choices[0] if choices else restore), 0.5
            if not choices:
                note = " (valeur inchangée : autres valeurs inconnues de Hamlib)"
        results = []
        for value in (target, restore):
            try:
                await self.ctrl.set_level(name, value)
            except Exception as exc:
                self.check(item_id, name_label, GENERE, False, f"commande refusée : {_rprt(exc)}")
                return
            read = await self._poll(lambda: client.get_level(name), lambda v, t=value: abs(v - t) <= tol)
            results.append(None if isinstance(read, Exception) else read)
        ok = all(r is not None and abs(r - v) <= tol for r, v in zip(results, (target, restore)))
        if ok:
            self._write_ok.add(name)
        self.check(item_id, name_label, GENERE, ok, f"{restore} -> {target} -> {restore}, relu {results}{note}")

    async def test_endurance(self) -> None:
        cycles = self.endurance_cycles
        self.say(f"  Endurance : {cycles} lectures de fréquence…")
        self.note(f"TEST endurance {cycles}")
        latencies, errors, first_error = [], 0, ""
        for i in range(cycles):
            t0 = time.perf_counter()          # monotonic() n'avance que par pas de ~15,6 ms sous Windows
            try:
                await self.link.client.get_frequency()
            except Exception as exc:
                errors += 1
                first_error = first_error or _rprt(exc)
                if errors >= 20:
                    break
                await asyncio.sleep(0.2)
                continue
            latencies.append((time.perf_counter() - t0) * 1000)
            if (i + 1) % 250 == 0:
                self.say(f"    {i + 1}/{cycles}")
        done = len(latencies) + errors
        self.check("cat_endurance", "Endurance de la liaison CAT", SOCLE, errors == 0 and done == cycles,
                   f"{len(latencies)}/{cycles} lectures réussies, {errors} erreur(s)" + (f" (1re : {first_error})" if first_error else ""))
        if len(latencies) >= 10:
            ordered = sorted(latencies)
            p50 = statistics.median(ordered)
            p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
            data = {"latence_cat_ms": round(p50, 2), "latence_cat_p95_ms": round(p95, 2)}
            rate = ""
            if p95 > 0:                       # une mesure nulle ne donne pas une cadence : on n'en écrit pas
                data["polling_max_hz"] = round(1000 / p95, 1)
                rate = f" (≈ {data['polling_max_hz']:g} lectures/s)"
            self.check("latency", "Temps de réponse CAT", FIXE, True,
                       f"médiane {p50:.1f} ms, 95 % sous {p95:.1f} ms, max {ordered[-1]:.1f} ms{rate}", **data)
        else:
            self.check("latency", "Temps de réponse CAT", FIXE, False, "pas assez de mesures")

    # ------------------------------------------------------------------ phase 2 : guidée

    async def phase_guided(self) -> None:
        self.say("\n=== Phase 2 : vérifications visuelles (aucune émission) ===")
        if (await self.prompt("  Faire les vérifications visuelles (quelques questions) ? [O/n] : ")).lower() in ("n", "non"):
            self.check("decl_skipped", "Vérifications visuelles", DECLARATIF, None, "non faites")
            return
        self.say("  Réponds o (oui), n (non), ou Entrée si tu ne sais pas. Ces réponses sont notées comme déclaratives.")
        freq = self.link.state.frequency_hz
        answer = await self.prompt(f"  L'afficheur du poste indique-t-il {_mhz(freq)} MHz ? : ")
        self.check("decl_freq", "Afficheur : fréquence", DECLARATIF, _yes(answer), f"question : {_mhz(freq)} MHz")
        await self._snapshot()
        try:
            for name in [n for n in ("NR", "NB", "AIP", "COMP") if n in self._write_ok]:
                orig = self._orig["funcs"].get(name)
                if orig is None:
                    continue
                try:
                    await self.ctrl.set_function(name, not orig)
                except Exception as exc:
                    self.say(f"  {label(name)} : commande refusée ({_rprt(exc)})")
                    continue
                await asyncio.sleep(0.5)
                state = "ACTIVÉ" if not orig else "DÉSACTIVÉ"
                answer = await self.prompt(f"  Sur le poste, {label(name)} est-il maintenant {state} ? : ")
                self.check(f"decl_func_{name}", f"Afficheur : {label(name)}", DECLARATIF, _yes(answer), f"attendu : {state}")
                await self.ctrl.set_function(name, orig)
        finally:
            await self._restore()
        answer = await self.prompt(f"  Ouvre {self.record_wav} : entends-tu le son du poste ? : ")
        self.check("decl_audio_rx", "Écoute du son reçu", DECLARATIF, _yes(answer), f"fichier : {self.record_wav}")

    # ------------------------------------------------------------------ phase 3 : émission

    async def phase_tx(self) -> None:
        self.say("\n=== Phase 3 : émission (chaque étape demande une confirmation) ===")
        self.note("PHASE 3")
        await self.stage_band()
        await self.stage_tx_mode()
        freq = self.link.state.frequency_hz or 0
        if self.cfg.safety.enforce_bands and not self.cfg.bands:
            self.record("PTT / Audio TX / Pannes", None, "aucune bande autorisée dans station.toml : émission impossible")
        elif self.cfg.safety.enforce_bands and not self.cfg.tx_allowed(freq):
            self.record("PTT / Audio TX / Pannes", False, f"{freq} Hz hors des bandes autorisées : accorde le poste dans une bande autorisée")
        elif await self.stage_ptt():
            if await self.stage_tx_audio():
                await self.stage_drills()
            else:
                self.record("Pannes", None, "ignoré : l'étape audio TX a échoué, on n'émet plus")
                self.record("Panne : perte de la liaison CAT", None, "ignoré : l'étape audio TX a échoué")

    async def stage_drills(self) -> bool:
        ok = await super().stage_drills()
        if self.results and self.results[-1].name == "Pannes":          # exercices non confirmés
            return self.record("Panne : perte de la liaison CAT", None, "non confirmé : ignoré")
        if self.proxy is None:
            return self.record("Panne : perte de la liaison CAT", None, "relais de trace absent : exercice impossible")
        if not await self.confirm_emission(f"Panne : perte de la liaison CAT pendant l'émission (coupure de {self.cat_cut_s:g} s ; "
                                           "le poste reste en émission jusqu'au retour de la liaison)"):
            return self.record("Panne : perte de la liaison CAT", None, "non confirmé : ignoré")

        async def cut() -> None:
            await self.proxy.interrupt(self.cat_cut_s)

        ok &= await self._drill("Panne : perte de la liaison CAT", "cat_down", self.cat_cut_s, self.cat_cut_s + 3.0, cut)
        return ok

    # ------------------------------------------------------------------ USB (facultatif, en réception)

    async def test_usb_replug(self, wait_s: float = 30.0) -> None:
        answer = await self.prompt("\n  Tester la reprise après débranchement du câble USB du poste ? [o/N] : ")
        if _yes(answer) is not True:
            self.check("usb_replug", "Reprise après débranchement USB", FIXE, None, "non demandé")
            return
        self.note("TEST usb_replug")
        self.say("  Débranche MAINTENANT le câble USB du poste (côté ordinateur)…")
        lost = await self._wait_state(lambda s: not s.connected or s.frequency_hz is None, wait_s)
        if not lost:
            self.check("usb_replug", "Reprise après débranchement USB", FIXE, False, f"aucune perte détectée en {wait_s:.0f} s")
            return
        await self.prompt("  Perte détectée. Rebranche le câble, puis appuie sur Entrée : ")
        t0 = time.monotonic()
        back = await self._wait_state(lambda s: s.connected and s.frequency_hz is not None, wait_s)
        self.check("usb_replug", "Reprise après débranchement USB", FIXE, back,
                   f"liaison reprise en {time.monotonic() - t0:.1f} s" if back else
                   "le poste ne répond plus : rigctld doit être relancé (le superviseur le fait en service normal)")

    async def _wait_state(self, condition, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if condition(self.link.state):
                return True
            await asyncio.sleep(0.2)
        return False

    # ------------------------------------------------------------------ déroulement

    async def ask_firmware(self) -> None:
        answer = (await asyncio.to_thread(self.ask, "Version du firmware affichée par le poste (Entrée si inconnue) : ")).strip()
        if answer and len(answer) <= 20 and all(c.isalnum() or c in ".-_ " for c in answer):
            self.firmware = answer

    async def run(self) -> list:
        self.say(f"Qualification : {self.profile.name} (Hamlib {self.profile.hamlib_version or '?'}, "
                 f"backend {self.profile.backend_status or '?'})")
        self.say(PREFLIGHT)
        if not typed(await asyncio.to_thread(self.ask, "Tape OUI pour confirmer ces 6 points : "), "OUI"):
            self.say("Qualification annulée.")
            return []
        await self.ask_firmware()
        try:
            if not await self.setup():
                return self.results
            if not await self.stage_cat():
                self.say("\nLiaison CAT impossible : on s'arrête ici (aucune émission n'a été tentée).")
                return self.results
            await self.phase_auto()
            await self.stage_rx_audio()
            await self.phase_guided()
            await self.phase_tx()
            await self._restore_mode()
            await self.test_usb_replug()
        finally:
            await self._restore_mode()
            await self.teardown()
            self.say("\nRetour en réception demandé au poste.")
        return self.results

    # ------------------------------------------------------------------ rapport

    def summary(self) -> list[str]:
        verdict = compute_verdict(self.checks)
        lines = ["", "================  BILAN DE QUALIFICATION  ================"]
        titles = {SOCLE: "Socle", FIXE: "Tests fixes", GENERE: "Tests générés", DECLARATIF: "Déclaratif"}
        latest = {c.id: c for c in self.checks}
        for category in (SOCLE, FIXE, GENERE, DECLARATIF):
            items = [c for c in latest.values() if c.category == category]
            if items:
                lines.append(f"{titles[category]} :")
                lines += [f"  {'OK    ' if c.ok else 'IGNORÉ' if c.ok is None else 'ÉCHEC '}  {c.label}" for c in items]
        lines.append(f"\nVerdict proposé : {verdict.status.upper()}")
        lines += [f"  - {r}" for r in verdict.reasons]
        if self.plan.unused:
            lines.append("Disponible dans Hamlib, non exploité par TRX Remote : " + ", ".join(self.plan.unused))
        return lines

    def write_report(self, directory: Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        sheet, verdict = draft_sheet(self.checks, self.profile, firmware=self.firmware)
        header = ["BROUILLON généré par trx-qualif : à relire par l'éditeur avant toute publication.",
                  f"Verdict proposé : {verdict.status} ; date : {self.started_at:%Y-%m-%d %H:%M} UTC"]
        (directory / "fiche.toml").write_text(render_sheet(sheet, header), encoding="utf-8")
        report = {
            "outil": TOOL_NAME, "version": _tool_version(), "format": 1,
            "date": self.started_at.isoformat(timespec="seconds"),
            "poste": {"modele_hamlib": self.profile.model, "nom": self.profile.name, "firmware": self.firmware},
            "hamlib": self.profile.to_dict(), "verdict": verdict.to_dict(),
            "tests": [c.to_dict() for c in self.checks], "plan": self.plan.to_dict(),
        }
        (directory / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (directory / "plan.txt").write_text(render_plan(self.plan, self.profile) + "\n", encoding="utf-8")
        if self.dump_text:
            (directory / "dump_caps.txt").write_text(self.dump_text, encoding="utf-8")
        if self.proxy is not None:
            self.proxy.write(directory / "cat_trace.log")
        (directory / "journal.txt").write_text("\n".join(self.journal) + "\n", encoding="utf-8")
        return directory


def _tool_version() -> str:
    from .. import __version__
    return __version__
