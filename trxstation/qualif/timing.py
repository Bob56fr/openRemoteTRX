# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Délais et comportements du poste mesurés par la valise (étape 400, décisions de l'utilisateur du 2026-11-25), SANS
émission, en phase 1 : ce qu'il faut pour remplir la fiche technique du poste (`trxstation/rigspec/models/<n>.toml`)
d'après un VRAI poste au lieu du manuel.
  * retard de relecture : temps entre la FIN d'une écriture (fréquence, mode) et la première lecture qui la montre ;
  * mémoire par bande : une fréquence envoyée sur une autre bande fait-elle changer le mode ? (`linked_changes`) ;
  * coupleur : en marche ou non pendant la mesure (les délais avec coupleur se mesurent coupleur en marche) ;
  * squelch réel : `\\get_dcd` lisible ? (`squelch.source`) ;
  * largeur par paliers (fiche `steps`) : la largeur demandée est-elle celle relue ?
Toutes les écritures passent par le PttController de la valise (refusées hors réception) ; l'état est remis par la
remise de la phase 1, la largeur d'origine aussi pour un poste à paliers. Le résultat est un BROUILLON de fiche, à
relire avant de le copier dans le dépôt.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field

from .. import rigspec

REPEATS = 3                  # écritures par mesure (le maximum compte : une relecture lente suffit à tromper la station)
READ_TIMEOUT_S = 8.0         # au-delà, la valeur n'a jamais été relue
POLL_S = 0.05
FREQ_STEP_HZ = 1000          # aller-retour de 1 kHz dans la même bande
BAND_CENTERS_HZ = (3_650_000, 7_100_000, 14_175_000, 21_225_000, 28_500_000)


@dataclass
class Timing:
    freq_delays_s: list[float] = field(default_factory=list)
    mode_delays_s: list[float] = field(default_factory=list)
    band_changes_mode: bool | None = None       # None = non mesuré
    tuner_on: bool | None = None
    dcd: bool | None = None                     # True = lisible ; False = refusé ; None = non essayé
    widths: list[tuple[int, int | None]] = field(default_factory=list)   # (demandée, relue)
    problems: list[str] = field(default_factory=list)

    @property
    def worst_s(self) -> float | None:
        values = self.freq_delays_s + self.mode_delays_s
        return max(values) if values else None

    def proposed_read_delay_s(self) -> float | None:
        """Marge de la fiche : deux fois le pire retard mesuré, arrondie au demi-seconde supérieur ; 0 sous 0,5 s."""
        worst = self.worst_s
        if worst is None:
            return None
        margin = 2 * worst
        return 0.0 if margin < 0.5 else math.ceil(margin * 2) / 2

    def to_dict(self) -> dict:
        return {"retard_frequence_s": [round(v, 3) for v in self.freq_delays_s],
                "retard_mode_s": [round(v, 3) for v in self.mode_delays_s],
                "bande_change_le_mode": self.band_changes_mode, "coupleur_en_marche": self.tuner_on,
                "squelch_lisible": self.dcd, "largeurs": [list(w) for w in self.widths],
                "read_delay_s_propose": self.proposed_read_delay_s(), "problemes": self.problems}


async def _until(read, expect, timeout: float = READ_TIMEOUT_S) -> tuple[float | None, object]:
    """Secondes jusqu'à une lecture qui satisfait `expect` (None si jamais), et la dernière valeur lue."""
    t0, last = time.perf_counter(), None
    while time.perf_counter() - t0 < timeout:
        try:
            last = await read()
            if expect(last):
                return time.perf_counter() - t0, last
        except Exception as exc:                   # une lecture refusée n'arrête pas la mesure
            last = exc
        await asyncio.sleep(POLL_S)
    return None, last


def _band_center(freq: int) -> int:
    """Centre d'une AUTRE bande amateur que celle de `freq` (la plus proche)."""
    others = [c for c in BAND_CENTERS_HZ if abs(c - freq) > 2_000_000]
    return min(others, key=lambda c: abs(c - freq)) if others else BAND_CENTERS_HZ[0]


async def measure(ctrl, client, *, spec: rigspec.RigSpec, modes: list[str], say=lambda text: None) -> Timing:
    out = Timing()
    try:
        freq = await client.get_frequency()
        mode, width = await client.get_mode()
    except Exception as exc:
        out.problems.append(f"état de départ illisible : {exc}")
        return out
    # 1. fréquence : aller-retour de 1 kHz, retard de relecture après la FIN de l'écriture
    for i in range(REPEATS):
        target = freq + FREQ_STEP_HZ if i % 2 == 0 else freq
        await ctrl.set_frequency(target)
        delay, last = await _until(client.get_frequency, lambda v, t=target: v == t)
        if delay is None:
            out.problems.append(f"fréquence {target} Hz jamais relue (dernière lecture : {last})")
        else:
            out.freq_delays_s.append(delay)
    await ctrl.set_frequency(freq)
    # 2. mode : un autre mode du poste, puis retour (largeur 0 : jamais de largeur réécrite sur un Icom)
    other = next((m for m in ("LSB", "USB", "CW", "AM") if m != mode and m in modes), None)
    if other is not None:
        for target in (other, mode, other):
            await ctrl.set_mode(target, 0)
            delay, last = await _until(lambda: client.get_mode(), lambda v, t=target: v[0] == t)
            if delay is None:
                out.problems.append(f"mode {target} jamais relu (dernière lecture : {last})")
            else:
                out.mode_delays_s.append(delay)
        await ctrl.set_mode(mode, 0)
        await _until(lambda: client.get_mode(), lambda v: v[0] == mode)
    # 3. mémoire par bande : une autre bande, le mode relu 2 s plus tard, puis retour
    try:
        await ctrl.set_frequency(_band_center(freq))
        await asyncio.sleep(2.0)
        moved_mode, _ = await client.get_mode()
        out.band_changes_mode = moved_mode != mode
    except Exception as exc:
        out.problems.append(f"changement de bande : {exc}")
    finally:
        await ctrl.set_frequency(freq)
        await ctrl.set_mode(mode, 0)
        await _until(client.get_frequency, lambda v: v == freq)
    # 4. coupleur (lu, jamais écrit) et squelch réel
    try:
        out.tuner_on = bool(await client.get_func("TUNER"))
    except Exception:
        out.tuner_on = None
    try:
        await client.get_dcd()
        out.dcd = True
    except Exception:
        out.dcd = False
    # 5. largeurs par paliers (fiche `steps`) : la liste courte, puis la largeur d'origine remise
    quick = rigspec.quick_widths(spec, mode)
    if quick:
        try:
            for w in quick[:3]:
                await ctrl.set_mode(mode, w)
                _, last = await _until(lambda: client.get_mode(), lambda v, w=w: v[1] == w, timeout=3.0)
                out.widths.append((w, last[1] if isinstance(last, tuple) else None))
        finally:
            await ctrl.set_mode(mode, width if width and width > 0 else 0)
    return out


def render_draft(spec: rigspec.RigSpec, model: int, name: str, timing: Timing) -> str:
    """Brouillon de `trxstation/rigspec/models/<model>.toml` : valeurs MESURÉES là où la valise les connaît, celles de
    la fiche actuelle (manuel) pour le reste ; `verified = true` seulement si les délais ont été mesurés."""
    read_delay = timing.proposed_read_delay_s()
    measured = read_delay is not None
    linked = timing.band_changes_mode if timing.band_changes_mode is not None else spec.timing.linked_changes
    source = spec.squelch.source if timing.dcd else "estimate"
    lines = [
        f"# BROUILLON écrit par trx-qualif (valise) : {name}, mesuré sur le poste ; à relire avant de le copier dans",
        f"# trxstation/rigspec/models/{model}.toml (les champs non mesurés gardent la valeur de la fiche actuelle).",
        f"# Retards mesurés : fréquence {[round(v, 2) for v in timing.freq_delays_s]} s, mode {[round(v, 2) for v in timing.mode_delays_s]} s",
        f"# ; coupleur {'en marche' if timing.tuner_on else 'coupé' if timing.tuner_on is False else 'inconnu'} pendant la mesure.",
        "format = 1",
        f"model = {model}",
        f'name = "{name}"',
        f"receivers = {spec.receivers}",
        f"verified = {'true' if measured else 'false'}",
        "",
        "[timing]",
        f"read_delay_s = {read_delay if measured else spec.timing.read_delay_s}",
        f"tuner_delay_s = {spec.timing.tuner_delay_s}   # à mesurer coupleur EN MARCHE (relancer la valise ainsi)",
        f"linked_changes = {'true' if linked else 'false'}" + ("   # mesuré : la bande change le mode" if timing.band_changes_mode
                                                                else "   # mesuré : le mode reste" if timing.band_changes_mode is False else ""),
        "",
        "[filters]",
        f'kind = "{spec.filters.kind}"',
    ]
    if spec.filters.kind == "presets":
        lines.append(f"presets = {spec.filters.presets}")
    if spec.filters.quick:
        lines.append(f"quick = [{', '.join(str(w) for w in spec.filters.quick)}]")
    if spec.filters.mode_width:
        lines.append(f"mode_width = {spec.filters.mode_width}   # repris de la fiche (largeur inchangée avec un mode)")
    if timing.widths:
        lines.append("# largeurs demandées -> relues : " + ", ".join(f"{a} -> {b}" for a, b in timing.widths))
    if spec.filters.steps:
        lines.append("")
        lines.append("[filters.steps]")
        lines += [f"{m} = [{', '.join(str(w) for w in ws)}]" for m, ws in spec.filters.steps.items()]
    t = spec.transmit
    if t.side_query:                               # poste à deux récepteurs : section reprise telle quelle (manuel)
        lines += ["", "[transmit]", f'side_query = "{t.side_query}"', f"side_reply = '{t.side_reply}'",
                  f'main_value = "{t.main_value}"', f'sub_value = "{t.sub_value}"', f'main_freq_query = "{t.main_freq_query}"',
                  f'sub_freq_query = "{t.sub_freq_query}"', f"freq_reply = '{t.freq_reply}'"]
    sq = spec.squelch
    if sq.query:                                   # lecture brute de la fiche (Yaesu « BY; ») : reprise telle quelle
        lines += ["", "[squelch]", f'source = "{sq.source}"   # lecture brute de la fiche, pas mesurée par la valise',
                  f'query = "{sq.query}"', f"reply = '{sq.reply}'", f'open_value = "{sq.open_value}"']
    else:
        lines += ["", "[squelch]", f'source = "{source}"' + ("   # mesuré : \\get_dcd lisible" if timing.dcd else "   # \\get_dcd refusé")]
    return "\n".join(lines) + "\n"
