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

  Sans émission (`--sans-emission`) : la phase 3 n'est pas faite, le socle reste incomplet (verdict « incomplet »).
  Filtres : SEULEMENT sur demande (`--filtres`). Sur un Icom, « M mode largeur » écrit la largeur demandée DANS le
  préréglage FIL1/2/3 choisi par Hamlib : l'essai réécrirait les filtres de l'utilisateur. Pour la même raison, le
  mode d'origine est remis avec la largeur 0 (largeur par défaut du backend, comme le fait la passerelle).

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

from ..answers import yes_no
from ..config import Config
from ..devtools import hwtest as _hwtest
from ..devtools.hwtest import PREFLIGHT, HwTest, _declined
from ..i18n import Translator, tool_translator
from ..gateway.cat.client import FLOAT_LEVELS, HAMLIB_ERRORS, INT_LEVELS, POWER_STEPS, RigError
from .plan import (DECLARATIF, FIXE, GENERE, SOCLE, SOCLE_ITEMS, TestPlan, build_plan, core_modes, label, render_plan,
                   shown_label, shown_note)
from .profile import HamlibProfile
from .results import Check, compute_verdict, draft_sheet, latest
from .sheet import render_sheet
from .texts import _fr, _t, both, has, term, typed_yes
from .trace import TraceProxy

DEFAULT_BANDS_MHZ = ((3.5, 3.8), (7.0, 7.2), (14.0, 14.35), (21.0, 21.45), (28.0, 29.7))
FREQ_OFFSET_HZ = 123              # décalage « au hertz » pour vérifier la résolution
MAX_RESOLUTION_HZ = 10
POWER_TOLERANCE = 0.015           # même tolérance que l'application (±1,5 %)
LINK_WAIT_S = 6.0                 # phase 1 : attente de la reconnexion à rigctld après une lecture trop lente
CACHE_MS = 1.0                    # lecture plus rapide qu'un aller-retour série : cache de rigctld (Hamlib 5)
LATENCY_SAMPLES = 200
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
# Noms des étapes de trx-hwtest (affichés dans la langue de l'outil) -> nom français de HW_MAP : la correspondance et le
# rapport ne doivent JAMAIS dépendre de la langue. Clés de hwtest.<langue>.json, puis clés de qualif.<langue>.json.
HW_KEYS = {"stage.cat": "CAT", "stage.rx_audio": "Audio RX", "stage.audio_open": "Audio (ouverture)", "stage.ptt": "PTT",
           "stage.tx_all": "PTT / Audio TX / Pannes", "stage.tx_audio": "Audio TX",
           "drill.heartbeat": "Panne : perte du heartbeat", "drill.disconnect": "Panne : déconnexion du client",
           "stage.drills": "Pannes", "stage.band": "Bande d'essai", "stage.tx_mode": "Mode d'émission"}
OWN_KEYS = {"hw.tx_all": "PTT / Audio TX / Pannes", "hw.drills": "Pannes", "hw.cat_loss": "Panne : perte de la liaison CAT"}


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


TUNER_WATCH_S = 8.0                   # accord éventuel du coupleur (porteuse brève) : PTT relu jusqu'au retour en réception
SPLIT_TX_S = 1.5                      # émission en split : PTT et puissance relus
SPLIT_WAIT_S = 15.0                   # seconde émission : l'opérateur éteint le split, la station doit couper
VOX_WATCH_S = 4.0                     # VOX en marche, aucun son envoyé : le poste doit rester en réception
VOX_TONE_S = 2.0                      # puis tonalité vers la carte son : le poste doit passer en émission
VOX_TONE_DBFS = -18.0                 # niveau de la tonalité (sinon celui conseillé par la montée du niveau)
VOX_RELEASE_S = 4.0                   # retour en réception attendu après le délai du VOX
VOX_SPEAK_S = 10.0                    # l'opérateur parle au micro : émission attendue dans cette fenêtre


WORK_MODE = "USB"                     # mode de travail des écritures (règle de l'utilisateur : pas en CW ni en FM)
WORK_MODES = {"USB", "LSB", "PKTUSB", "PKTLSB", "AM"}
MODE_FOR = {                          # réglages qui n'existent que dans certains modes (règles de l'utilisateur, 2026-11-18)
    "COMP": ("USB", "LSB", "AM"),
    "BKINDL": ("CW",), "KEYSPD": ("CW",), "CWPITCH": ("CW",), "SBKIN": ("CW",), "FBKIN": ("CW",),
}


class Qualification(HwTest):
    def __init__(self, cfg: Config, *, profile: HamlibProfile, dump_text: str = "", proxy: TraceProxy | None = None,
                 endurance_cycles: int = 1000, cat_cut_s: float = 1.5, settle_s: float = 2.0, no_tx: bool = False,
                 filters_test: bool = False, **kwargs):
        super().__init__(cfg, capabilities=profile.caps, **kwargs)
        self.profile, self.dump_text, self.proxy = profile, dump_text, proxy
        self.plan: TestPlan = build_plan(profile)
        self.endurance_cycles, self.cat_cut_s, self.settle_s = endurance_cycles, cat_cut_s, settle_s
        self.no_tx, self.filters_test = no_tx, filters_test
        self.manual_restore: list[str] = []      # ce que l'opérateur doit remettre à la main (affiché dans le bilan)
        self.checks: list[Check] = []
        self.journal: list[str] = []
        self.firmware = ""
        self.started_at = datetime.now(timezone.utc)
        self._orig: dict = {}
        self._own_record = False
        self._write_ok: set[str] = set()
        self._shown: dict[str, tuple[str, str]] = {}   # id -> (nom, détail) MONTRÉS, dans la langue de l'outil (bilan)
        user_out = self.out
        self.out = lambda text: (self.journal.append(text), user_out(text))[-1]

    # ------------------------------------------------------------------ résultats

    def french_name(self, name: str) -> str:
        """Nom français d'une étape de trx-hwtest montrée dans une autre langue (sinon le nom tel quel)."""
        if name in HW_MAP or name.startswith("Panne : TOT"):
            return name
        tot = f"{self.tot_s:.0f}"
        shown, fr = tool_translator("hwtest"), Translator("fr", "hwtest")
        if shown("drill.tot", tot=tot) == name:
            return fr("drill.tot", tot=tot)
        for key, french_text in HW_KEYS.items():
            if shown(key) == name:
                return french_text
        for key, french_text in OWN_KEYS.items():
            if _t(key) == name:
                return french_text
        return name

    def record(self, name: str, ok: bool | None, detail: str, shown_detail: str | None = None) -> bool:
        shown_name, shown_detail = name, detail if shown_detail is None else shown_detail
        name = self.french_name(name)
        mapped = None if self._own_record else HW_MAP.get(name)
        if mapped is None and not self._own_record and name.startswith("Panne : TOT"):
            mapped = ("drill_tot", FIXE)
        if mapped is not None:
            stored = ok
            unreadable = "pas lisible" in detail or detail == tool_translator("hwtest")("cat.ptt_unreadable")
            if ok is False and (name in SETUP_FAILURES or (name == "CAT" and not unreadable)):
                detail += _fr("check.setup_failure")
                shown_detail += _t("check.setup_failure")
                stored = None
            self.checks.append(Check(mapped[0], name, mapped[1], stored, detail))
            self._shown[mapped[0]] = (shown_name, shown_detail)
        # La valeur renvoyée pilote le déroulé (arrêt après un échec) : c'est toujours le résultat RÉEL.
        return super().record(shown_name, ok, shown_detail)

    def check(self, item_id: str, name: str | tuple[str, str], category: str, ok: bool | None,
              detail: str | tuple[str, str], **data) -> bool:
        """Résultat d'un test : enregistré en français (rapport), montré dans la langue de l'outil. `name` et `detail`
        peuvent être des couples (français, montré), comme ceux de both()."""
        detail, shown_detail = detail if isinstance(detail, tuple) else (detail, detail)
        suffix = getattr(self, "_mode_suffix", None)
        if suffix:
            detail, shown_detail = detail + suffix[0], shown_detail + suffix[1]
        item = self.plan.by_id(item_id)
        if isinstance(name, tuple):
            name, shown_name = name
        elif item is not None:
            shown_name = shown_label(item, self.profile)
        else:
            shown_name = _t(f"check.{item_id}") if has(f"check.{item_id}") else name
        self.checks.append(Check(item_id, name, category, ok, detail, data))
        self._shown[item_id] = (shown_name, shown_detail)
        self._own_record = True
        try:
            return super().record(shown_name, ok, shown_detail)
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
            self.say(_t("run.snapshot_unreadable", error=_rprt(exc)))
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
                problems.append(f"{term(name)} ({_rprt(exc)})")
        for name, value in self._orig["levels"].items():
            restore = self._level_value(name, value)
            if restore is None:
                continue
            try:
                await self.ctrl.set_level(name, restore)
            except Exception as exc:
                problems.append(f"{term(name)} ({_rprt(exc)})")
        if "mode" in self._orig:
            mode, width = self._orig["mode"]
            try:
                await self.ctrl.set_mode(mode, 0)      # jamais de largeur explicite : elle réécrirait un préréglage FIL (Icom)
                now = await self._poll(self.link.client.get_mode, lambda v: v[0] == mode)
                if not isinstance(now, Exception) and now is not None and now[0] == mode and now[1] != width:
                    text = _t("restore.filter", mode=mode, before=width, now=now[1])
                    self.say(f"  {text[0].upper()}{text[1:]}.")
                    if text not in self.manual_restore:
                        self.manual_restore.append(text)
            except Exception as exc:
                problems.append(_t("restore.mode", error=_rprt(exc)))
        if "freq" in self._orig:
            try:
                await self.ctrl.set_frequency(self._orig["freq"])
            except Exception as exc:
                problems.append(_t("restore.freq", error=_rprt(exc)))
        if problems:
            self.say(_t("restore.failed", items=", ".join(problems)))

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
        self.say(_t("phase1.title"))
        self.note("PHASE 1")
        restore_command = self._patient_link()
        try:
            await self._snapshot()
            try:
                await self.test_frequency()
                await self.test_modes()
                await self.test_timing()
                await self.test_filters()
                await self.test_reads()
                await self.test_writes()
            finally:
                await self._restore()
        finally:
            restore_command()
        await self.test_endurance()

    def _patient_link(self, wait_s: float = LINK_WAIT_S) -> Callable[[], None]:
        """Phase 1 SEULEMENT (aucune émission) : une lecture plus lente que le délai de la liaison (Yaesu FTDX10 :
        « u COMP » refusé en 2,5 s, délai de 2 s ; valise du 2026-11-19) ferme la connexion à rigctld ; CatLink la
        refait en moins d'une seconde, mais sans attendre, TOUS les essais suivants échouaient en « non connecté ». La
        commande suivante attend donc la reconnexion (`wait_s` au plus) ; la lecture lente reste notée en échec. Les
        essais d'émission et de panne gardent le comportement de la station (échec immédiat). Rend la fonction qui
        remet la commande d'origine."""
        client = self.link.client if self.link is not None else None
        if client is None:
            return lambda: None
        raw = client._command

        async def command(line: str):
            end = time.monotonic() + wait_s
            while not client.connected and time.monotonic() < end:
                await asyncio.sleep(0.1)
            return await raw(line)

        client._command = command
        return lambda: setattr(client, "_command", raw)

    async def test_frequency(self) -> None:
        bands = [(b.low_mhz, b.high_mhz) for b in self.cfg.bands] or list(DEFAULT_BANDS_MHZ)
        targets = [round((low + high) / 2 * 1000) * 1000 + FREQ_OFFSET_HZ for low, high in bands][:8]
        accepted, refused, diffs, reads = 0, [], [], []
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
                reads.append((target, None))
            else:
                diffs.append(abs(read - target))
                reads.append((target, read))
        needed = min(2, len(targets))
        worst = max(diffs) if diffs else math.inf
        ok = accepted >= needed and worst <= MAX_RESOLUTION_HZ
        resolution = 1 if worst == 0 else (int(worst) if worst <= MAX_RESOLUTION_HZ else None)
        def detail(tr) -> str:
            lines = [f"{_mhz(t)} -> {_mhz(r) if r is not None else tr('freq.unreadable')}" for t, r in reads]
            text = tr("freq.accepted", accepted=accepted, total=len(targets)) + ", ".join(lines)
            if refused:
                text += tr("freq.refused", items=", ".join(refused))
            if ok and worst > 0:
                text += tr("freq.resolution", hz=int(worst))
            return text
        data = {"resolution_hz": resolution} if resolution else {}
        self.check("freq_rw", "Fréquence : écriture et relecture", SOCLE, ok, (detail(_fr), detail(_t)), **data)

    async def test_modes(self) -> None:
        modes = self.profile.modes or self.caps.modes
        core = core_modes(self.profile) or modes
        passed = set()
        self.note("TEST mode_rw")
        for mode in modes:
            try:
                await self.ctrl.set_mode(mode)
            except Exception as exc:
                self.check(f"mode_{mode}", f"Mode {mode}", GENERE, False, both("detail.refused", error=_rprt(exc)))
                continue
            read = await self._poll(self.link.client.get_mode, lambda v, m=mode: v[0] == m)
            ok = not isinstance(read, Exception) and read is not None and read[0] == mode
            if ok:
                passed.add(mode)
            got = _rprt(read) if isinstance(read, Exception) else (read[0] if read else "?")
            self.check(f"mode_{mode}", f"Mode {mode}", GENERE, ok, both("detail.read_back", value=got))
        if passed:
            self.manual_restore.append(_t("restore.modes", modes=", ".join(m for m in modes if m in passed)))
        missing = [m for m in core if m not in passed]

        def detail(tr) -> str:
            return (tr("mode.core_read", modes=", ".join(m for m in core if m in passed) or tr("mode.none"))
                    + (tr("mode.failed", modes=", ".join(missing)) if missing else ""))
        self.check("mode_rw", "Mode : écriture et relecture", SOCLE, not missing, (detail(_fr), detail(_t)))

    async def test_filters(self) -> None:
        if not self.filters_test:
            self.check("filters", "Filtres (largeur de bande)", FIXE, None, both("filters.not_done"))
            return
        filters = {m: w for m, w in self.caps.filters.items() if m in core_modes(self.profile)}
        if not filters:
            self.check("filters", "Filtres (largeur de bande)", FIXE, None, both("filters.none_declared"))
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
                bad.append(("filters.unreadable", {"mode": mode}))
            elif got_widths != list(widths):
                if len(set(got_widths)) == len(widths):
                    adjusted.append(mode)
                else:
                    bad.append(("filters.not_distinct", {"mode": mode, "widths": got_widths}))

        def detail(tr) -> str:
            failed = [tr(b[0], **b[1]) if isinstance(b, tuple) else b for b in bad]
            text = tr("filters.failed", items=", ".join(failed)) * bool(bad) + tr("filters.read", items=", ".join(lines))
            if adjusted and not bad:
                text += tr("filters.adjusted", modes=", ".join(adjusted))
            return text
        self.check("filters", "Filtres (largeur de bande)", FIXE, not bad, (detail(_fr), detail(_t)))

    async def test_reads(self) -> None:
        self.note("TEST lectures")
        client = self.link.client
        for item in self._items("read_func") + self._items("read_level"):
            try:
                value = await (client.get_func(item.target) if item.action == "read_func" else client.get_level(item.target))
            except Exception as exc:
                self.check(item.id, item.label, GENERE, False, _rprt(exc))
                continue
            self.check(item.id, item.label, GENERE, True, both("detail.value_read", value=value))

    async def test_writes(self) -> None:
        self.note("TEST écritures")
        await self._work_mode()
        for item in self.plan.items:
            if item.action == "manual":
                self.check(item.id, item.label, GENERE, None, (item.note, shown_note(item)))
            elif item.action in ("write_func", "write_level"):
                await self._write_in_its_mode(item)

    async def _work_mode(self) -> None:
        """Règle de l'utilisateur (2026-11-18) : ne pas rester en CW / FM pendant les écritures (beaucoup de réglages
        n'y existent pas) : le poste passe en USB le temps des écritures ; le mode d'origine est remis par _restore."""
        mode = (self._orig.get("mode") or (None, None))[0]
        if mode is None or mode in WORK_MODES or WORK_MODE not in self.profile.modes:
            return
        try:
            await self.ctrl.set_mode(WORK_MODE, 0)
            await self._poll(self.link.client.get_mode, lambda v: v[0] == WORK_MODE)
            self.say(_t("write.work_mode", mode=mode, work=WORK_MODE))
        except Exception as exc:
            self.say(_t("write.work_mode_failed", error=_rprt(exc)))

    async def _write_in_its_mode(self, item) -> None:
        """Écriture ; si le poste la REFUSE, nouvel essai dans le mode où ce réglage existe (MODE_FOR : compresseur en
        USB / LSB / AM, réglages CW en CW), puis retour au mode de travail. Le résultat dit dans quel mode."""
        write = self._write_func if item.action == "write_func" else self._write_level
        before = len(self.checks)
        await write(item.id, item.label, item.target)
        last = self.checks[-1] if len(self.checks) > before else None
        current = self.link.state.mode
        modes = [m for m in MODE_FOR.get(item.target, ()) if m != current and m in self.profile.modes]
        if last is None or last.ok is not False or "refus" not in last.detail or not modes:
            return
        target = modes[0]
        try:
            await self.ctrl.set_mode(target, 0)
            await self._poll(self.link.client.get_mode, lambda v: v[0] == target)
        except Exception:
            return
        try:
            client = self.link.client
            key = "funcs" if item.action == "write_func" else "levels"
            try:
                self._orig[key][item.target] = await (client.get_func(item.target) if key == "funcs"
                                                      else client.get_level(item.target))
            except Exception:
                pass
            self.checks.pop()                            # le refus dans le mauvais mode est remplacé par le nouvel essai
            self._mode_suffix = both("write.in_mode", mode=target)
            await write(item.id, item.label, item.target)
        finally:
            self._mode_suffix = None
            if current:
                try:
                    await self.ctrl.set_mode(current, 0)
                    await self._poll(self.link.client.get_mode, lambda v: v[0] == current)
                except Exception as exc:
                    self.say(_t("write.work_mode_failed", error=_rprt(exc)))

    async def _write_func(self, item_id: str, name_label: str, name: str) -> None:
        client = self.link.client
        orig = self._orig.get("funcs", {}).get(name)
        if orig is None:
            self.check(item_id, name_label, GENERE, False, both("write.func_unreadable"))
            return
        steps = []
        for target in (not orig, orig):
            try:
                await self.ctrl.set_function(name, target)
            except Exception as exc:
                self.check(item_id, name_label, GENERE, False, both("detail.refused", error=_rprt(exc)))
                return
            read = await self._poll(lambda: client.get_func(name), lambda v, t=target: v == t)
            steps.append(read == target)
        ok = all(steps)
        if ok:
            self._write_ok.add(name)
        self.check(item_id, name_label, GENERE, ok, both("write.func_ok" if ok else "write.not_followed"))

    async def _write_level(self, item_id: str, name_label: str, name: str) -> None:
        client = self.link.client
        orig = self._orig.get("levels", {}).get(name)
        if orig is None:
            self.check(item_id, name_label, GENERE, False, both("write.level_unreadable"))
            return
        restore = self._level_value(name, orig)
        if restore is None:
            self.check(item_id, name_label, GENERE, None,
                       both("write.power_off_steps" if name == "RFPOWER" else "write.out_of_range", value=orig))
            return
        notes: list[tuple[str, dict]] = []
        if name == "SQL":
            target, tol = (0.3 if abs(orig - 0.3) > 0.1 else 0.6), 0.02
        elif name == "RFPOWER":
            lower = [s for s in POWER_STEPS if s < restore]                     # jamais plus fort qu'au départ si possible
            target = lower[-1] if lower else next(s for s in POWER_STEPS if s > restore)
            tol = POWER_TOLERANCE
        elif name in FLOAT_LEVELS:                      # NR, NB : milieu de la plage (ou un cinquième si on y est déjà)
            low, high = FLOAT_LEVELS[name]
            declared = self.profile.caps.level_ranges.get(name) if getattr(self.profile, "caps", None) else None
            if declared:                                 # plage du poste (NB d'un Icom : 0 à 1, pas 0 à 10)
                low, high = max(low, declared[0]), min(high, declared[1])
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
                notes.append(("write.note_unchanged", {}))
        # NR, NB : beaucoup de postes refusent le NIVEAU quand la FONCTION est arrêtée (IC-7300MK2 : RPRT -9 pour NB).
        # La fonction est mise en marche le temps de l'essai, puis remise (elle fait aussi partie de l'état relevé).
        switched = False
        if name in self.profile.set_functions and name in self.profile.get_functions:
            try:
                if not await client.get_func(name):
                    await self.ctrl.set_function(name, True)
                    switched = True
                    notes.append(("write.note_switched", {"name": name}))
            except Exception:
                pass
        def note(tr) -> str:
            return "".join(tr(k, **f) for k, f in notes)
        results = []
        try:
            for value in (target, restore):
                try:
                    await self.ctrl.set_level(name, value)
                except Exception as exc:
                    self.check(item_id, name_label, GENERE, False,
                               tuple(tr("detail.refused", error=_rprt(exc)) + note(tr) for tr in (_fr, _t)))
                    return
                read = await self._poll(lambda: client.get_level(name), lambda v, t=value: abs(v - t) <= tol)
                results.append(None if isinstance(read, Exception) else read)
        finally:
            if switched:
                try:
                    await self.ctrl.set_function(name, False)
                except Exception as exc:
                    self.say(_t("write.func_left_on", name=name, error=_rprt(exc)))
        ok = all(r is not None and abs(r - v) <= tol for r, v in zip(results, (target, restore)))
        if ok:
            self._write_ok.add(name)
        self.check(item_id, name_label, GENERE, ok,
                   tuple(tr("write.level_detail", restore=restore, target=target, results=results) + note(tr)
                         for tr in (_fr, _t)))

    async def test_endurance(self) -> None:
        cycles = self.endurance_cycles
        self.say(_t("endurance.start", cycles=cycles))
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
                   tuple(tr("endurance.detail", done=len(latencies), cycles=cycles, errors=errors)
                         + (tr("endurance.first", error=first_error) if first_error else "") for tr in (_fr, _t)))
        if len(latencies) < 10:
            self.check("latency", "Temps de réponse CAT", FIXE, False, both("latency.too_few"))
            return
        source = both("latency.source_freq")
        if statistics.median(latencies) < CACHE_MS:
            # rigctld 5 répond à « f » depuis son cache : ce n'est pas le temps de réponse du POSTE. Le S-mètre, lui,
            # est toujours demandé au poste.
            measured = await self._strength_latencies(LATENCY_SAMPLES) if "STRENGTH" in self.profile.get_levels else []
            if len(measured) < 10:
                self.check("latency", "Temps de réponse CAT", FIXE, None,
                           both("latency.cache_only", median=f"{statistics.median(latencies):.2f}"))
                return
            latencies, source = measured, both("latency.source_smeter", count=len(measured),
                                               median=f"{statistics.median(latencies):.2f}")
        ordered = sorted(latencies)
        p50 = statistics.median(ordered)
        p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
        data = {"latence_cat_ms": round(p50, 2), "latence_cat_p95_ms": round(p95, 2)}
        rate = ("", "")
        if p95 > 0:                       # une mesure nulle ne donne pas une cadence : on n'en écrit pas
            data["polling_max_hz"] = round(1000 / p95, 1)
            rate = both("latency.rate", rate=f"{data['polling_max_hz']:g}")
        self.check("latency", "Temps de réponse CAT", FIXE, True,
                   tuple(tr("latency.detail", p50=f"{p50:.1f}", p95=f"{p95:.1f}", max=f"{ordered[-1]:.1f}", rate=r, source=src)
                         for tr, r, src in ((_fr, rate[0], source[0]), (_t, rate[1], source[1]))), **data)

    async def test_timing(self) -> None:
        """Délais et comportements du poste pour sa fiche technique (étape 400, `qualif/timing.py`), sans émission."""
        from .. import rigspec
        from . import timing as measure_timing
        self.say(_t("timing.start"))
        self.note("TEST délais du poste")
        spec = rigspec.load(self.profile.model)
        try:
            found = await measure_timing.measure(self.ctrl, self.link.client, spec=spec, modes=list(self.profile.modes))
        except Exception as exc:                       # une mesure ratée n'arrête pas la qualification
            self.check("timing", ("Délais du poste", _t("check.timing")), FIXE, None, both("timing.failed", error=_rprt(exc)))
            return
        self.timing = found
        worst = found.worst_s
        if worst is None:
            self.check("timing", ("Délais du poste", _t("check.timing")), FIXE, None,
                       both("timing.none", problems="; ".join(found.problems) or "—"), **found.to_dict())
            return
        fmt = lambda values: "/".join(f"{v:.2f}" for v in values) or "—"   # noqa: E731
        band = "timing.band_linked" if found.band_changes_mode else "timing.band_kept" if found.band_changes_mode is False             else "timing.band_unknown"
        dcd = "timing.dcd_yes" if found.dcd else "timing.dcd_no"
        self.check("timing", ("Délais du poste", _t("check.timing")), FIXE, not found.problems,
                   tuple(tr("timing.detail", freq=fmt(found.freq_delays_s), mode=fmt(found.mode_delays_s),
                            margin=found.proposed_read_delay_s()) + tr(band) + tr(dcd)
                         + (tr("timing.problems", problems="; ".join(found.problems)) if found.problems else "")
                         for tr in (_fr, _t)), **found.to_dict())

    async def _strength_latencies(self, count: int) -> list[float]:
        found = []
        for _ in range(count):
            t0 = time.perf_counter()
            try:
                await self.link.client.get_strength()
            except Exception:
                continue
            found.append((time.perf_counter() - t0) * 1000)
        return found

    # ------------------------------------------------------------------ phase 2 : guidée

    async def phase_guided(self) -> None:
        self.say(_t("phase2.title"))
        # Aucune émission dans cette phase : Entrée = oui, comme avant ; « n » (ou le non d'une autre langue) = on passe.
        answer = await self.prompt(_t("phase2.ask", yn=_t("yesno.default_yes")))
        if answer.lower() in ("n", "non") or yes_no(answer) is False:
            self.check("decl_skipped", "Vérifications visuelles", DECLARATIF, None, both("phase2.not_done"))
            return
        self.say(_t("phase2.how"))
        freq = self.link.state.frequency_hz
        answer = await self.prompt(_t("phase2.freq", freq=_mhz(freq)))
        self.check("decl_freq", "Afficheur : fréquence", DECLARATIF, _yes(answer), both("phase2.freq_detail", freq=_mhz(freq)))
        await self._snapshot()
        try:
            for name in [n for n in ("NR", "NB", "AIP", "COMP") if n in self._write_ok]:
                orig = self._orig["funcs"].get(name)
                if orig is None:
                    continue
                try:
                    await self.ctrl.set_function(name, not orig)
                except Exception as exc:
                    self.say(_t("phase2.refused", what=term(name), error=_rprt(exc)))
                    continue
                await asyncio.sleep(0.5)
                state = "phase2.on" if not orig else "phase2.off"
                answer = await self.prompt(_t("phase2.func", what=term(name), state=_t(state)))
                self.check(f"decl_func_{name}", (f"Afficheur : {label(name)}", _t("check.decl_func", what=term(name))),
                           DECLARATIF, _yes(answer),
                           tuple(tr("phase2.expected", state=tr(state)) for tr in (_fr, _t)))
                await self.ctrl.set_function(name, orig)
        finally:
            await self._restore()
        answer = await self.prompt(_t("phase2.audio", path=self.record_wav))
        self.check("decl_audio_rx", "Écoute du son reçu", DECLARATIF, _yes(answer), both("phase2.audio_detail", path=self.record_wav))

    # ------------------------------------------------------------------ phase 3 : émission

    async def phase_tx(self) -> None:
        self.say(_t("phase3.title"))
        self.note("PHASE 3")
        self.release_own_changes()
        await self.stage_band()
        await self.stage_tx_mode()
        freq = self.link.state.frequency_hz or 0
        if self.cfg.safety.enforce_bands and not self.cfg.bands:
            self.record(_t("hw.tx_all"), None, *both("phase3.no_bands"))
        elif self.cfg.safety.enforce_bands and not self.cfg.tx_allowed(freq):
            self.record(_t("hw.tx_all"), False, *both("phase3.out_of_band", freq=freq))
        elif await self.stage_ptt():
            if await self.stage_tx_audio() or self.audio_no_power:   # pas de son : exercices sans audio
                await self.stage_drills()
            else:
                self.record(_t("hw.drills"), None, *both("phase3.drills_skipped"))
                self.record(_t("hw.cat_loss"), None, *both("phase3.cat_loss_skipped"))
            await self.stage_tuner()
            await self.stage_split()
            await self.stage_vox()

    async def _rx_and_func(self, name: str) -> tuple[bool | None, bool | None]:
        try:
            ptt = await self.link.client.get_ptt()
        except Exception:
            ptt = None
        try:
            func = await self.link.client.get_func(name)
        except Exception:
            func = None
        return ptt, func

    async def stage_tuner(self) -> None:
        """Coupleur (demande de l'utilisateur, 2026-11-19) : mis en marche puis remis comme au départ, sur CHARGE
        FICTIVE après EMETTRE (un accord peut envoyer une porteuse brève) ; le PTT est relu jusqu'au retour en réception."""
        if not ("TUNER" in self.profile.set_functions and "TUNER" in self.profile.get_functions):
            return self.check("tuner_tx", ("Coupleur d'antenne", _t("tuner.label")), FIXE, None, both("tuner.not_declared"))
        if not await self.confirm_emission(_t("tuner.what")):
            return self.check("tuner_tx", ("Coupleur d'antenne", _t("tuner.label")), FIXE, None, both("phase3.not_confirmed"))
        _, orig = await self._rx_and_func("TUNER")
        steps, tx_seen = [], False
        try:
            for target in ((not orig) if orig is not None else True, orig if orig is not None else False):
                await self.ctrl.set_function("TUNER", target)
                end = time.monotonic() + TUNER_WATCH_S
                read = None
                while time.monotonic() < end:
                    ptt, read = await self._rx_and_func("TUNER")
                    tx_seen = tx_seen or bool(ptt)
                    if read == target and not ptt:
                        break
                    await asyncio.sleep(0.25)
                steps.append(read == target)
        except Exception as exc:
            return self.check("tuner_tx", ("Coupleur d'antenne", _t("tuner.label")), FIXE, False,
                              both("detail.refused", error=_rprt(exc)))
        ptt, _ = await self._rx_and_func("TUNER")
        if ptt:
            await self.ctrl.force_rx("hwtest")
        ok = all(steps) and not ptt
        self.check("tuner_tx", ("Coupleur d'antenne", _t("tuner.label")), FIXE, ok,
                   both("tuner.ok" if ok else "tuner.ko", tx="oui" if tx_seen else "non"))

    async def _key_retry(self) -> None:
        """Prise d'émission ; un refus PASSAGER (anti-rebond, démarrage, touche du poste juste avant) est retenté."""
        from ..gateway.safety.ptt import Refused
        for _ in range(20):
            try:
                self.ctrl.release_local(_hwtest.CLIENT)  # touche SPLIT de l'opérateur : reprise permise hors émission
            except Exception:
                pass
            try:
                await self.key()
                return
            except Refused as exc:
                if exc.reason not in ("cooldown", "starting", "local_active"):
                    raise
                await asyncio.sleep(0.5)
        raise RuntimeError("prise d'émission jamais acceptée")

    async def stage_split(self) -> None:
        """Split (demande de l'utilisateur, 2026-11-19), sur CHARGE FICTIVE après EMETTRE. L'OPÉRATEUR met le split et
        règle l'autre VFO à la touche du poste : l'essai n'écrit NI le split NI aucune fréquence (sur l'IC-7300MK2,
        « S 1 VFOB » de Hamlib échange les VFO et la fréquence de réception change). Relus : split, fréquence d'émission,
        fréquence de réception. Fréquence d'émission hors bande => la station doit REFUSER ; illisible => refus aussi
        (sûr, mais split inutilisable à distance) ; dans la bande : émission 1 (PTT, puissance, fréquences relus), puis
        émission 2 pendant laquelle l'opérateur éteint le split : la station doit couper (« split_changed »).
        `split_operator` (essais) : remplace l'appui de l'opérateur. « T 0 » QUOI QU'IL ARRIVE."""
        from ..gateway.safety.ptt import Refused
        label = ("Split", _t("split.label"))
        can = self.profile.can
        if not (can.get("get Split VFO") or can.get("set Split VFO")):
            return self.check("split_tx", label, FIXE, None, both("split.not_declared"))
        if not await self.confirm_emission(_t("split.what")):
            return self.check("split_tx", label, FIXE, None, both("phase3.not_confirmed"))
        if _declined(await self.prompt(_t("split.setup"))):
            return self.check("split_tx", label, FIXE, None, both("split.skipped"))
        client = self.link.client
        try:
            rx = await client.get_frequency()
            split = await client.get_split()
            tx = await client.get_split_frequency() if split else 0
        except Exception as exc:
            return self.check("split_tx", label, FIXE, None, both("detail.refused", error=_rprt(exc)))
        if not split:
            return self.check("split_tx", label, FIXE, None, both("split.not_on", rx=f"{rx / 1e6:.4f}"))
        try:
            if not tx or (self.cfg.safety.enforce_bands and not self.cfg.tx_allowed(tx)):
                expected = "split_unreadable" if not tx else "out_of_band"
                try:
                    await self._key_retry()
                    refused = ""
                except Refused as exc:
                    refused = exc.reason
                ptt = await self.read_ptt()
                ok = refused == expected and ptt is False
                key = "split.refused_unreadable" if not tx else "split.refused_out"
                return self.check("split_tx", label, FIXE, ok if tx else (None if ok else False),
                                  both(key, tx=f"{tx / 1e6:.4f}", reason=refused or "aucun refus"))
            await self._key_retry()
            await self.sleep_with_heartbeat(SPLIT_TX_S)
            ptt1 = await self.read_ptt()
            try:
                power = await client.get_level("RFPOWER_METER")
            except Exception:
                power = None
            tx1, rx1 = await client.get_split_frequency(), await client.get_frequency()
            await self.ctrl.toggle(_hwtest.CLIENT)
            first = ptt1 is True and (power is None or power > 0) and tx1 == tx and rx1 == rx
            await asyncio.sleep(1.0)
            await self._key_retry()
            t0 = time.monotonic()
            self.say(_t("split.now", s=f"{SPLIT_WAIT_S:.0f}"))
            hook = getattr(self, "split_operator", None)
            if hook is not None:
                hook()
            while self.ctrl.snapshot().state != "RX" and time.monotonic() - t0 < SPLIT_WAIT_S:
                self.ctrl.heartbeat(_hwtest.CLIENT)
                await asyncio.sleep(0.1)
            elapsed = time.monotonic() - t0
            reason = self.ctrl.snapshot().last_cut_reason if self.ctrl.snapshot().state == "RX" else ""
            rx2 = await client.get_frequency()
            cut = reason == "split_changed" and (await self.read_ptt()) is False
        except Exception as exc:
            return self.check("split_tx", label, FIXE, False, both("detail.refused", error=_rprt(exc)))
        finally:
            if self.ctrl.snapshot().state != "RX" or await self.read_ptt():
                await self.ctrl.force_rx("hwtest")
        ok = first and cut and rx2 == rx
        self.check("split_tx", label, FIXE, ok,
                   both("split.ok" if ok else "split.ko", rx=f"{rx / 1e6:.4f}", tx=f"{tx / 1e6:.4f}",
                        power=f"{power:.2f}" if power is not None else "?", first="OK" if first else "NON",
                        cut=f"{elapsed:.1f}", reason=reason or "aucune coupure"))

    async def stage_vox(self) -> None:
        """VOX (demandes de l'utilisateur, 2026-11-19), sur CHARGE FICTIVE après EMETTRE, en deux temps :
        1. VOX en marche VOX_WATCH_S s SANS son : le poste NE DOIT PAS passer en émission ;
        2. VOX toujours en marche, VOX_TONE_S s de tonalité envoyée DIRECTEMENT à la carte son du poste (c'est ce que
           fait un VOX : hors de la porte audio de la station, seulement dans cet essai) : le poste DOIT passer en
           émission, puis revenir en réception après le délai du VOX.
        VOX remis comme au départ, mode d'origine remis et « T 0 » de sécurité QUOI QU'IL ARRIVE (finally)."""
        label = ("VOX", _t("vox.label"))
        if not ("VOX" in self.profile.set_functions and "VOX" in self.profile.get_functions):
            return self.check("vox_tx", label, FIXE, None, both("vox.not_declared"))
        if not await self.confirm_emission(_t("vox.what")):
            return self.check("vox_tx", label, FIXE, None, both("phase3.not_confirmed"))
        _, orig = await self._rx_and_func("VOX")
        on_read, quiet_tx, keyed, back, error = None, False, None, None, None
        # La STATION refuse toute écriture du VOX (liste fermée de PttController et du client CAT : un VOX laissé en
        # marche à distance ferait émettre le poste sans contrôle). L'essai passe par la commande brute, et le remet.
        client = self.link.client
        try:
            await client._command("U VOX 1")
            end = time.monotonic() + VOX_WATCH_S
            while time.monotonic() < end:
                ptt, on_read = await self._rx_and_func("VOX")
                quiet_tx = quiet_tx or bool(ptt)
                await asyncio.sleep(0.25)
            if not quiet_tx:
                keyed, back = await self._vox_trigger()
        except Exception as exc:
            error = exc
        finally:
            # ORDRE IMPOSÉ (vu sur l'IC-7300MK2, 2026-11-19) : le VOX semble gardé à part en mode données ; coupé pendant
            # le PKTLSB, il restait EN MARCHE au retour en LSB. D'abord le mode d'origine, puis le VOX, puis relecture.
            ptt, _ = await self._rx_and_func("VOX")
            if ptt:
                await self.ctrl.force_rx("hwtest")
            wanted = bool(orig) if orig is not None else False
            now = None
            for _ in range(3):
                try:
                    await client._command(f"U VOX {1 if wanted else 0}")
                except Exception as exc:
                    self.say(_t("vox.left_on", error=_rprt(exc)))
                ptt, now = await self._rx_and_func("VOX")
                if now == wanted:
                    break
                await asyncio.sleep(0.3)
            if now != wanted:
                self.say(_t("vox.left_on", error=f"relu {now}"))
            if ptt:
                await self.ctrl.force_rx("hwtest")
        if error is not None:
            return self.check("vox_tx", label, FIXE, False, both("detail.refused", error=_rprt(error)))
        restored = now == (bool(orig) if orig is not None else False)
        if quiet_tx or on_read is not True or not restored:
            return self.check("vox_tx", label, FIXE, False, both("vox.ko", on=on_read, tx="oui" if quiet_tx else "non",
                                                                 now=now))
        if keyed is None:                                # opérateur absent ou refus : seul le premier temps est prouvé
            return self.check("vox_tx", label, FIXE, None, both("vox.quiet_only"))
        ok = keyed and back
        mode_note = (f" [mode relu pendant l'essai : {', '.join(getattr(self, 'vox_tone_modes', []))}]",) * 2
        detail = both("vox.keyed_ok" if ok else ("vox.not_keyed" if not keyed else "vox.stuck"),
                      level=f"{self._vox_level():.0f}")
        self.check("vox_tx", label, FIXE, ok, (detail[0] + mode_note[0], detail[1] + mode_note[1]))

    def _vox_level(self) -> float:
        advice = getattr(self, "tx_level_advice", None)
        return advice if advice is not None else VOX_TONE_DBFS

    async def _vox_trigger(self) -> tuple[bool | None, bool | None]:
        """Le VOX doit FAIRE ÉMETTRE : l'opérateur parle au micro du poste, en phonie (manuels Icom : VOX en SSB / AM /
        FM / DV, « with your voice » ; en mode données il ne marche pas, vu sur l'IC-7300MK2). `vox_player` (essais) :
        source de son simulée. (émission vue, retour en réception)."""
        play = getattr(self, "vox_player", None)
        if play is not None:
            if play(self.cfg, self._vox_level(), VOX_TONE_S) is None:
                return None, None
            window = VOX_TONE_S + 0.3
        else:
            answer = await self.prompt(_t("vox.speak"))
            if _declined(answer):
                return None, None
            window = VOX_SPEAK_S
        keyed = False
        end = time.monotonic() + window
        modes = set()
        while time.monotonic() < end:
            ptt, _ = await self._rx_and_func("VOX")
            keyed = keyed or bool(ptt)
            try:
                modes.add((await self.link.client.get_mode())[0])     # mode RELU pendant la tonalité (rapport)
            except Exception:
                pass
            await asyncio.sleep(0.2)
        self.vox_tone_modes = sorted(modes)
        back = False
        end = time.monotonic() + VOX_RELEASE_S
        while time.monotonic() < end:
            ptt, _ = await self._rx_and_func("VOX")
            if ptt is False:
                back = True
                break
            await asyncio.sleep(0.2)
        return keyed, back

    def release_own_changes(self) -> None:
        """Les réglages changés très vite par la phase 1 (modes, filtres) peuvent être vus comme une ACTION SUR LE POSTE
        (opérateur sur place, `local_active`) : la phase 3 serait refusée 2 minutes (vu sur l'IC-7300MK2, étape 255).
        Ces changements sont ceux de la qualification : elle « reprend la main » comme le bouton de la page, ce qui
        reste REFUSÉ pendant une émission au micro du poste (la phase 3 est alors refusée normalement)."""
        local = getattr(self.ctrl, "local", None)
        if local is None or not local.active():
            return
        reason = local.reason or "?"
        try:
            self.ctrl.release_local(_hwtest.CLIENT)
        except Exception as exc:                 # noqa: BLE001 : émission locale en cours : refus normal plus loin
            self.say(_t("phase3.local_kept", reason=reason, error=exc))
            return
        self.note(f"REPRISE DE LA MAIN (motif vu : {reason})")
        self.say(_t("phase3.local_released", reason=reason))

    async def stage_drills(self) -> bool:
        ok = await super().stage_drills()
        if self.results and self.french_name(self.results[-1].name) == "Pannes":          # exercices non confirmés
            return self.record(_t("hw.cat_loss"), None, *both("phase3.not_confirmed"))
        if self.proxy is None:
            return self.record(_t("hw.cat_loss"), None, *both("phase3.no_proxy"))
        if not await self.confirm_emission(_t("phase3.cat_cut_what", s=f"{self.cat_cut_s:g}")):
            return self.record(_t("hw.cat_loss"), None, *both("phase3.not_confirmed"))

        async def cut() -> None:
            await self.proxy.interrupt(self.cat_cut_s)

        ok &= await self._drill(_t("hw.cat_loss"), "cat_down", self.cat_cut_s, self.cat_cut_s + 3.0, cut)
        return ok

    # ------------------------------------------------------------------ USB (facultatif, en réception)

    async def test_usb_replug(self, wait_s: float = 30.0) -> None:
        answer = await self.prompt(_t("usb.ask", yn=_t("yesno.default_no")))
        if _yes(answer) is not True:
            self.check("usb_replug", "Reprise après débranchement USB", FIXE, None, both("usb.not_asked"))
            return
        self.note("TEST usb_replug")
        self.say(_t("usb.unplug"))
        lost = await self._wait_state(lambda s: not s.connected or s.frequency_hz is None, wait_s)
        if not lost:
            self.check("usb_replug", "Reprise après débranchement USB", FIXE, False, both("usb.no_loss", s=f"{wait_s:.0f}"))
            return
        await self.prompt(_t("usb.replug"))
        t0 = time.monotonic()
        back = await self._wait_state(lambda s: s.connected and s.frequency_hz is not None, wait_s)
        self.check("usb_replug", "Reprise après débranchement USB", FIXE, back,
                   both("usb.back", s=f"{time.monotonic() - t0:.1f}") if back else both("usb.lost"))

    async def _wait_state(self, condition, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if condition(self.link.state):
                return True
            await asyncio.sleep(0.2)
        return False

    # ------------------------------------------------------------------ déroulement

    async def ask_firmware(self) -> None:
        answer = (await asyncio.to_thread(self.ask, _t("ask.firmware"))).strip()
        if answer and len(answer) <= 20 and all(c.isalnum() or c in ".-_ " for c in answer):
            self.firmware = answer

    async def run(self) -> list:
        self.say(_t("run.title", name=self.profile.name, hamlib=self.profile.hamlib_version or "?",
                    backend=self.profile.backend_status or "?"))
        # Consignes de sécurité de trx-hwtest, dans la langue de l'outil quand il sait les traduire. Sans émission
        # (`no_tx`), les 6 points de l'émission (« antenne débranchée »…) faisaient confirmer le contraire de ce que
        # l'opérateur faisait (antenne branchée pour enregistrer un vrai son, valise du FTDX10, 2026-11-19).
        if self.no_tx:
            self.say(_t("run.no_tx_notice"))
            confirm = _t("run.no_tx_confirm", word=_t("word.yes"))
        else:
            self.say(getattr(_hwtest, "preflight_text", lambda: PREFLIGHT)())
            confirm = _t("run.confirm", word=_t("word.yes"))
        # Le mot de la langue OU le mot français OUI, en entier ; rien d'autre (jamais « oui » par défaut).
        if not typed_yes(await asyncio.to_thread(self.ask, confirm)):
            self.say(_t("run.cancelled"))
            return []
        await self.ask_firmware()
        try:
            if not await self.setup():
                return self.results
            if not await self.stage_cat():
                self.say(_t("run.no_cat"))
                return self.results
            await self.phase_auto()
            await self.stage_rx_audio()
            await self.phase_guided()
            if self.no_tx:
                self.say(_t("phase3.no_tx_title"))
                for item_id, name, category in (("ptt_cycle", "PTT activé puis désactivé, avec relecture", SOCLE),
                                                ("cat_loss_rx", "Retour en réception sur perte de la liaison CAT", SOCLE),
                                                ("audio_tx", "Audio en émission", FIXE)):
                    self.check(item_id, name, category, None, both("phase3.no_tx"))
            else:
                await self.phase_tx()
            await self._restore_mode()
            await self.test_usb_replug()
        finally:
            await self._restore_mode()
            await self.teardown()
            self.say(_t("run.back_to_rx"))
        return self.results

    # ------------------------------------------------------------------ rapport

    def summary(self) -> list[str]:
        """Bilan MONTRÉ à l'opérateur, dans la langue de l'outil (le rapport, lui, reste en français)."""
        verdict = compute_verdict(self.checks)
        lines = ["", _t("summary.title")]
        by_id = latest(self.checks)
        tags = {True: _t("summary.ok"), None: _t("summary.skipped"), False: _t("summary.failed")}
        width = max(6, *(len(t) for t in tags.values()))
        for category in (SOCLE, FIXE, GENERE, DECLARATIF):
            items = [c for c in by_id.values() if c.category == category]
            if items:
                lines.append(_t(f"summary.category.{category}"))
                lines += [f"  {tags[bool(c.ok) if c.ok is not None else None].ljust(width)}  {self._shown_label(c)}"
                          for c in items]
        lines.append(_t("summary.verdict", status=_t(f"verdict.{verdict.status}")))
        lines += [f"  - {r}" for r in self._shown_reasons(by_id)]
        if self.plan.unused:
            lines.append(_t("summary.unused", names=", ".join(self.plan.unused)))
        if self.manual_restore:
            lines.append(_t("summary.manual"))
            lines += [f"  - {m}" for m in self.manual_restore]
        return lines

    def _shown_label(self, check: Check) -> str:
        return self._shown.get(check.id, (check.label, ""))[0]

    def _shown_reasons(self, by_id: dict[str, Check]) -> list[str]:
        """Raisons du verdict (même calcul que compute_verdict), dans la langue de l'outil."""
        failed, missing = [], []
        for item_id, _ in SOCLE_ITEMS:
            check = by_id.get(item_id)
            if check is None or check.ok is None:
                missing.append(_t(f"check.{item_id}"))
            elif check.ok is False:
                detail = self._shown.get(item_id, ("", check.detail))[1]
                failed.append(_t("verdict.failed_item", label=_t(f"check.{item_id}"), detail=detail))
        if failed:
            return failed
        if missing:
            return [_t("verdict.missing_item", label=m) for m in missing]
        return [_t("verdict.ok")]

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
        timing = getattr(self, "timing", None)
        if timing is not None:                         # brouillon de la fiche technique du poste (étape 400)
            from .. import rigspec
            from .timing import render_draft
            text = render_draft(rigspec.load(self.profile.model), self.profile.model, self.profile.name, timing)
            (directory / "fiche-technique.toml").write_text(text, encoding="utf-8")
        return directory


def _tool_version() -> str:
    from .. import __version__
    return __version__
