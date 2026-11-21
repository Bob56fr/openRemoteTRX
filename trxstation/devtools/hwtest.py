# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Essai guidé sur un VRAI poste : `trx-hwtest --config station.toml` (Windows, Linux ou Raspberry Pi).

Étapes, de la plus sûre à la plus risquée (voir docs/essai-poste-reel.md) :
  1. CAT         : lecture seule (fréquence, mode, PTT, S-mètre).                      AUCUNE émission
  2. Audio RX    : mesure du niveau reçu, enregistrement d'un WAV à écouter.            AUCUNE émission
  3. Accord      : décale la fréquence de +1 kHz puis la rétablit.                      AUCUNE émission
  4. PTT         : 3 cycles porteuse SANS audio, temps de commutation.                  ÉMISSION (confirmation)
  5. Audio TX    : tonalité à niveau croissant, relevé ALC / SWR / puissance.           ÉMISSION (confirmation)
  6. Pannes      : perte du heartbeat, TOT, déconnexion du client.                      ÉMISSION (confirmation)

Étapes de réception ajoutées après l'accord (AUCUNE émission) :
  - Largeurs de filtre : chaque largeur candidate du mode actuel est demandée puis RELUE sur le poste (Hamlib ne
    déclare que quelques largeurs ; le poste en accepte peut-être d'autres) ; la largeur d'origine est remise.
  - Écran du spectre (second port CI-V) : balayages comptés écran normal, poste sur un MENU, puis après un nouvel
    envoi de « spectre allumé » (27 10 01, liste fermée) ; réglages du spectre remis comme au départ.
`trx-hwtest --reception-seule` : CAT, audio reçu, accord et ces deux étapes, sans aucune émission.

`trx-hwtest --coupure-poste` : CAT puis un seul exercice, la coupure faite SUR LE POSTE (touche TRANSMIT) :
la station doit la voir d'elle-même par sa relecture du PTT. À lancer avec [spectrum] enabled = false puis
true : avec async=1, Hamlib ne doit pas renvoyer un état d'émission gardé en mémoire.

Chaque étape d'émission exige de taper EMETTRE. Quoi qu'il arrive (erreur, Ctrl+C), l'émission est
coupée à la fin. Le PTT n'est jamais actif pendant qu'une question est posée.

Langues (lot L3) : tout ce que l'essai montre ou demande vient de `trxstation/i18n/hwtest.<langue>.json` (`_t`,
langue d'openRemoteTRX Console par `TRX_LANG`, sinon menu 0, sinon le système). Les mots de confirmation affichés sont
ceux de la langue ; le mot français (EMETTRE, OUI) reste TOUJOURS accepté, rien d'autre.
"""
from __future__ import annotations

from ..crashguard import guarded

import argparse
import asyncio
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import config as cfgmod
from ..answers import typed, yes_no
from ..asyncio_noise import install_quiet_handler
from ..config import Config
from ..gateway.audio import AudioConfigError, AudioPipeline
from ..gateway.audio.devices import WavSink
from ..gateway.audio.pcm import FLOOR_DB, FRAME_S, FRAME_SAMPLES, rms_dbfs, tone
from ..gateway.cat import Capabilities, CatLink, load_capabilities
from ..gateway.cat.capabilities import data_mode_for
from ..gateway.safety import PttController, PttLimits, Refused
from ..hamlib import rigctld_command
from ..i18n import catalog, tool_translator
from ..paths import default_config_path
from ..procutil import station_running
from ..errors import codes
from ..errors.emit import render

CLIENT = "hwtest"
EMIT_WORD = "EMETTRE"           # mot français : toujours accepté, quelle que soit la langue
YES_WORD = "OUI"


def _t(_key: str, **fields) -> str:
    """Texte montré à l'opérateur dans la langue de l'outil (`trxstation/i18n/hwtest.<langue>.json`, français en
    référence). Lu À CHAQUE APPEL (jamais au chargement du module : les tests changent la langue après l'import)."""
    return tool_translator("hwtest")(_key, **fields)


def emit_word() -> str:
    """Mot de confirmation d'émission AFFICHÉ (celui de la langue)."""
    return _t("word.emit")


def typed_emit(answer: str | None) -> bool:
    """Confirmation d'émission : le mot de la langue OU le mot français EMETTRE, en entier ; rien d'autre."""
    return any(typed(answer, word) for word in {emit_word(), EMIT_WORD})


def typed_yes(answer: str | None) -> bool:
    """Confirmation du préambule : le mot de la langue OU le mot français OUI, en entier ; rien d'autre."""
    return any(typed(answer, word) for word in {_t("word.yes"), YES_WORD})


def preflight_text() -> str:
    """Consignes de sécurité avant toute émission (charge fictive…), dans la langue de l'outil."""
    return _t("notice.preflight")


# Texte FRANÇAIS des consignes, gardé pour les outils qui l'importent encore (trx-qualif) : préférer preflight_text().
PREFLIGHT = catalog("fr", "hwtest").get("notice.preflight", "")


def _declined(answer: str) -> bool:
    """Question « [O/n] » : seul un non explicite (n, non, no, nein) refuse ; Entrée ou autre chose = oui."""
    return yes_no(answer) is False


# Largeurs essayées en plus de celles que Hamlib déclare (par famille de modes, pas par modèle de poste).
EXTRA_WIDTHS = {
    "ssb": (1800, 2100, 2400, 2700, 3000, 3600),
    "cw": (250, 500, 1200),
    "am": (3000, 6000, 9000),
}
SSB_MODES = ("USB", "LSB", "PKTUSB", "PKTLSB")
CW_MODES = ("CW", "CWR", "RTTY", "RTTYR")
AM_MODES = ("AM", "PKTAM", "AM-D")


def filter_candidates(mode: str | None, declared: list[int] | None) -> list[int]:
    """Largeurs à essayer pour ce mode : celles que Hamlib déclare, plus les largeurs usuelles de la famille."""
    family = "ssb" if mode in SSB_MODES else "cw" if mode in CW_MODES else "am" if mode in AM_MODES else None
    widths = set(int(w) for w in (declared or []) if isinstance(w, (int, float)) and w > 0)
    if family:
        widths.update(EXTRA_WIDTHS[family])
    return sorted(widths)


def khz(width: int) -> str:
    return f"{width / 1000:g}k" if width >= 1000 else f"{width} Hz"


def _hz(value: int) -> str:
    """14 200 000 (espaces entre les milliers, comme avant la traduction)."""
    return f"{value:,}".replace(",", " ")


@dataclass
class StageResult:
    name: str
    ok: bool | None            # None = ignoré
    detail: str


class HwTest:
    REKEY_GAP_S = 0.45          # > délai anti-rebond de la couche de sécurité (0,3 s)

    def __init__(self, cfg: Config, *, ask: Callable[[str], str] = input, out: Callable[[str], None] = print,
                 tot_s: float = 8.0, hold_s: float = 1.5, tx_seconds: float = 2.0, rx_listen_s: float = 5.0,
                 tx_levels_db: tuple[float, ...] = (-40.0, -30.0, -24.0), cat_timeout_s: float = 10.0,
                 record_wav: str = "hwtest_rx.wav", cycles: int = 3, capabilities: Capabilities | None = None,
                 only_rig_unkey: bool = False, rx_only: bool = False, scope_opener: Callable | None = None,
                 scope_measure_s: float = 3.0, selcall_listen_s: float = 20.0, alc_stop: float | None = None):
        """`alc_stop` : montée du niveau d'émission (valise, lot T3) : arrêt dès qu'une puissance est mesurée ET que
        l'ALC atteint ce seuil ; le niveau précédent est conseillé (None = comme avant, tous les paliers)."""
        self.alc_stop, self.tx_level_advice = alc_stop, None
        self.cfg, self.ask, self.out = cfg, ask, out
        self.only_rig_unkey, self.rx_only = only_rig_unkey, rx_only
        self.scope_opener, self.scope_measure_s = scope_opener, scope_measure_s
        self.selcall_listen_s = selcall_listen_s
        self.tot_s, self.hold_s, self.tx_seconds, self.rx_listen_s = tot_s, hold_s, tx_seconds, rx_listen_s
        self.tx_levels_db, self.cat_timeout_s, self.record_wav, self.cycles = tx_levels_db, cat_timeout_s, record_wav, cycles
        self.results: list[StageResult] = []
        self.audio_no_power = False      # étape 5 : puissance nulle partout (son ailleurs) ; exercices SANS audio permis
        self.caps = capabilities
        self._mode_to_restore: str | None = None
        self.link: CatLink | None = None
        self.pipeline: AudioPipeline | None = None
        self.ctrl: PttController | None = None
        self._link_task: asyncio.Task | None = None
        self.heartbeat_timeout_s = cfg.safety.heartbeat_timeout_ms / 1000
        if tot_s < self.heartbeat_timeout_s + 1.0:
            raise ValueError(_t("init.tot_ambiguous", tot=f"{tot_s:g}", heartbeat=f"{self.heartbeat_timeout_s:g}"))

    # ------------------------------------------------------------------ utilitaires

    def say(self, text: str = "") -> None:
        self.out(text)

    async def prompt(self, text: str, *, word: str | None = None, context: str | None = None) -> str:
        """`word` : mot de sécurité (EMETTRE…) ; par le bus de la valise, seul un humain au clavier peut le donner."""
        assert self.ctrl is None or self.ctrl.snapshot().state == "RX", "question posée pendant une émission"
        if word is None:
            return (await asyncio.to_thread(self.ask, text)).strip()   # la boucle (watchdog, CAT) continue de tourner
        from ..qualif.bus import ask_word
        return (await asyncio.to_thread(ask_word, self.ask, text, word, family="EMETTRE",
                                        context=context)).strip()

    def record(self, name: str, ok: bool | None, detail: str) -> bool:
        self.results.append(StageResult(name, ok, detail))
        tags = {True: _t("tag.ok"), False: _t("tag.fail"), None: _t("tag.skipped")}
        width = max(7, *(len(t) for t in tags.values()))
        self.say(_t("record.line", tag=tags[ok].ljust(width), name=name, detail=detail))
        return ok is not False

    async def confirm_emission(self, what: str) -> bool:
        self.say(_t("emit.title", what=what))
        self.say(_t("emit.reminder"))
        answer = await self.prompt(_t("emit.prompt", word=emit_word()), word=emit_word(),
                                   context=_t("emit.title", what=what).strip())
        return typed_emit(answer)

    async def read_ptt(self, wait_s: float = 0.0) -> bool | None:
        """État du PTT relu sur le poste ; None si illisible. `wait_s` > 0 (étape 1 seulement) : nouvel essai tant que la
        liaison se refait (lecture facultative trop lente abandonnée par CatLink : Yaesu FTDX10, « u COMP »)."""
        end = time.monotonic() + wait_s
        while True:
            try:
                return await self.link.client.get_ptt()
            except Exception:
                if time.monotonic() >= end:
                    return None
                await asyncio.sleep(0.2)

    async def key(self):
        """Prise d'émission, après le délai anti-rebond imposé par la couche de sécurité (0,3 s)."""
        await asyncio.sleep(self.REKEY_GAP_S)
        return await self.ctrl.toggle(CLIENT)

    async def sleep_with_heartbeat(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.ctrl.heartbeat(CLIENT)
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------------ mise en route

    async def setup(self) -> bool:
        cfg = self.cfg
        if self.caps is None:
            try:
                self.caps = await load_capabilities(cfg.rig.model, cfg.tools.hamlib_dir)
            except Exception as exc:
                self.say(_t("setup.no_caps", error=exc))
        caps = self.caps
        try:
            self.pipeline = AudioPipeline(cfg.audio)
            await self.pipeline.start()
        except AudioConfigError as exc:
            self.record(_t("stage.audio_open"), False, str(exc))
            return False
        self.link = CatLink(cfg.network.rigctld_host, cfg.network.rigctld_port, capabilities=caps, timeout=2.0)
        limits = PttLimits(tot_s=self.tot_s, warn_before_s=min(5.0, self.tot_s / 2),
                           heartbeat_timeout_s=self.heartbeat_timeout_s, rekey_cooldown_s=0.3)
        self.ctrl = PttController(self.link, cfg, limits=limits, audio_gate=self.pipeline.gate.set_open)
        self.pipeline.gate.owner_provider = lambda: self.ctrl.snapshot().owner
        self._link_task = asyncio.create_task(self.link.run())
        self._start_measures()
        await self.ctrl.start()
        self.ctrl.connect_client(CLIENT)
        return True

    def _start_measures(self) -> None:
        """Valise (lot G2b) : l'état du poste que CatLink RELIT déjà (aucune commande de plus) publié pour la page,
        deux fois par seconde au plus et seulement s'il change."""
        from ..qualif.bus import bus_of
        bus = bus_of(self.ask)
        if bus is None or self.link is None:
            return

        async def publish() -> None:
            last = None
            while True:
                st = self.link.state
                levels = st.levels or {}
                now = {"actif": True, "ptt": st.ptt, "freq_hz": st.frequency_hz, "mode": st.mode,
                       "s_db": st.strength_db, "po": levels.get("RFPOWER_METER"), "swr": levels.get("SWR"),
                       "alc": levels.get("ALC")}
                if now != last:
                    bus.measure("poste", now)
                    last = now
                await asyncio.sleep(0.5)
        self._measure_task = asyncio.create_task(publish())

    async def _stop_measures(self) -> None:
        task = getattr(self, "_measure_task", None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            from ..qualif.bus import bus_of
            bus = bus_of(self.ask)
            if bus is not None:
                bus.measure("poste", {"actif": False})
            self._measure_task = None

    async def teardown(self) -> None:
        """Toujours exécuté : coupe l'émission, ferme l'audio, arrête la liaison."""
        if self.ctrl is not None:
            try:
                await self.ctrl.close()
            except Exception as exc:
                self.say(_t("teardown.cut_error", error=repr(exc)))
        try:
            await self._stop_measures()                 # APRÈS la coupure : jamais rien avant elle
        except Exception:                               # noqa: BLE001 : la page perd une mesure, rien de plus
            pass
        if self.pipeline is not None:
            await self.pipeline.stop()
        if self.link is not None:
            self.link.stop()
        if self._link_task is not None:
            await asyncio.gather(self._link_task, return_exceptions=True)

    # ------------------------------------------------------------------ étape 1 : CAT

    async def stage_cat(self) -> bool:
        self.say(_t("cat.title"))
        name = _t("stage.cat")
        deadline = time.monotonic() + self.cat_timeout_s
        while time.monotonic() < deadline:
            if self.link.state.connected and self.link.state.frequency_hz is not None:
                break
            await asyncio.sleep(0.1)
        state = self.link.state
        if not state.connected:
            return self.record(name, False, _t("cat.unreachable"))
        if state.frequency_hz is None:
            return self.record(name, False, _t("cat.no_rig", error=state.last_error or _t("cat.no_answer")))
        samples = []
        for _ in range(5):
            samples.append(self.link.state.strength_db)
            await asyncio.sleep(0.2)
        caps = self.caps
        rig = (caps.manufacturer + " " + caps.model_name if caps and caps.model_name
               else _t("cat.model_number", model=self.cfg.rig.model))
        self.say(_t("cat.rig", rig=rig))
        self.say(_t("cat.frequency", freq=_hz(state.frequency_hz), mode=state.mode, passband=state.passband_hz))
        self.say(_t("cat.smeter", samples=samples))
        ptt = await self.read_ptt(wait_s=self.cat_timeout_s)
        if ptt is True:
            return self.record(name, False, _t("cat.transmitting"))
        if ptt is None:
            return self.record(name, False, _t("cat.ptt_unreadable"))
        # Le texte d'avant la traduction passait tout entier dans replace(",", " ") : gardé tel quel.
        return self.record(name, True, _t("cat.ok", freq=f"{state.frequency_hz:,}", mode=state.mode).replace(",", " "))

    # ------------------------------------------------------------------ étape 2 : audio RX

    async def stage_rx_audio(self) -> bool:
        self.say(_t("rx.title", seconds=f"{self.rx_listen_s:.0f}"))
        name = _t("stage.rx_audio")
        queue = self.pipeline.hub.subscribe(maxsize=500)
        levels, wav = [], WavSink(self.record_wav)
        try:
            end = time.monotonic() + self.rx_listen_s
            while time.monotonic() < end:
                try:
                    pcm = await asyncio.wait_for(queue.get(), 1.0)
                except asyncio.TimeoutError:
                    break
                levels.append(rms_dbfs(pcm))
                wav.write(pcm)
        finally:
            self.pipeline.hub.unsubscribe(queue)
            wav.close()
        if not levels:
            return self.record(name, False, _t("rx.no_frames"))
        mean, peak = sum(levels) / len(levels), max(levels)
        self.say(_t("rx.level", mean=f"{mean:.0f}", peak=f"{peak:.0f}", frames=len(levels), wav=self.record_wav))
        if peak <= FLOOR_DB + 1:
            return self.record(name, False, _t("rx.silence"))
        if peak > -3:
            return self.record(name, True, _t("rx.saturation", peak=f"{peak:.0f}"))
        hint = _t("rx.hint", gain=max(-40, min(20, round(-30 - mean)))) if abs(mean + 30) > 10 else ""
        return self.record(name, True, _t("rx.ok", mean=f"{mean:.0f}", peak=f"{peak:.0f}", hint=hint))

    # ------------------------------------------------------------------ SELCALL en réception (facultatif)

    SELCALL_OFFSETS_HZ = (0, 300, -300)        # docs/selcall-cahier-des-charges.md § 12 : tolérance ±300 Hz

    async def _selcall_listen(self, code: str) -> list:
        """Écoute jusqu'à une trame valide du `code` (ou la fin du délai) ; retourne toutes les trames décodées."""
        from ..selcall.receiver import SelcallReceiver, SelcallStore      # numpy : seulement pour cette étape
        store = SelcallStore(None)
        store.activate(code)
        frames: list = []
        receiver = SelcallReceiver(store, on_frame=lambda frame, _opened: frames.append(frame))
        queue = self.pipeline.hub.subscribe(maxsize=500)
        try:
            end = time.monotonic() + self.selcall_listen_s
            while time.monotonic() < end and not any(f.valid and f.code == code for f in frames):
                try:
                    pcm = await asyncio.wait_for(queue.get(), 1.0)
                except asyncio.TimeoutError:
                    continue
                receiver.process(pcm)
        finally:
            self.pipeline.hub.unsubscribe(queue)
        return frames

    async def _set_rit(self, hz: int) -> bool:
        try:
            await self.ctrl.set_offset("RIT", hz)
            await self.ctrl.set_function("RIT", hz != 0)
            return True
        except Exception as exc:
            self.say(_t("selcall.rit_refused", error=exc, offset=f"{hz:+d}"))
            return False

    async def stage_selcall_rx(self) -> bool:
        """Essai réel guidé du SELCALL (réception seule) : trame jouée par un second poste ou un fichier, décodage
        relevé, puis RIT à +300 et -300 Hz. Le RIT d'origine est TOUJOURS remis (sur l'IC-7300 il partage son
        décalage avec le ΔTX : un décalage oublié déplacerait les émissions des étapes suivantes)."""
        from ..selcall import protocol as sp
        name = _t("stage.selcall")
        self.say(_t("selcall.title"))
        answer = await self.prompt(_t("selcall.source", yn=_t("yn.default_no")))
        if yes_no(answer) is not True:
            return self.record(name, None, _t("detail.skipped"))
        try:
            code = sp.validate_code(await self.prompt(_t("selcall.code")))
        except sp.CodeError as exc:
            return self.record(name, None, _t("detail.skipped_because", error=exc))
        try:                                       # RIT d'origine relu SUR LE POSTE (l'état suivi ne le contient pas toujours)
            rit0 = await self.link.client.get_offset("RIT")
            fn0 = await self.link.client.get_func("RIT")
        except Exception as exc:                   # illisible : on ne le touche pas, décalage de la source à la main
            self.say(_t("selcall.rit_unreadable", error=exc))
            rit0 = fn0 = None
        details, ok, touched = [], True, False
        try:
            for offset in self.SELCALL_OFFSETS_HZ:
                if offset:
                    if _declined(await self.prompt(_t("selcall.offset_prompt", offset=f"{offset:+d}",
                                                      yn=_t("yn.default_yes")))):
                        details.append(_t("selcall.offset_skipped", offset=f"{offset:+d}"))
                        continue
                    if rit0 is None:
                        self.say(_t("selcall.shift_source", offset=f"{offset:+d}"))
                    else:
                        touched = True
                        await self._set_rit(offset)
                self.say(_t("selcall.send_now", code=code, seconds=f"{self.selcall_listen_s:.0f}"))
                frames = await self._selcall_listen(code)
                good = [f for f in frames if f.valid and f.code == code]
                others = [f.code or f.reason for f in frames if not (f.valid and f.code == code)]
                label = f"{offset:+d} Hz" if offset else _t("selcall.no_offset")
                if good:
                    f = good[0]
                    details.append(_t("selcall.decoded", label=label, delta=f"{f.delta_hz:+.0f}", snr=f"{f.snr_db:.0f}"))
                else:
                    ok = False
                    details.append(_t("selcall.nothing", label=label)
                                   + (_t("selcall.frames", frames=", ".join(map(str, others[:3]))) if others else ""))
                self.say("  " + details[-1])
        finally:
            if touched:
                try:
                    await self.ctrl.set_offset("RIT", rit0)
                    await self.ctrl.set_function("RIT", fn0)
                except Exception as exc:
                    self.say(_t("selcall.rit_not_restored", error=exc, rit=rit0))
        return self.record(name, ok, " ; ".join(details))

    # ------------------------------------------------------------------ étape 3 : accord

    async def stage_tuning(self) -> bool:
        self.say(_t("tuning.title"))
        name = _t("stage.tuning")
        answer = await self.prompt(_t("tuning.prompt", yn=_t("yn.default_yes")))
        if _declined(answer):
            return self.record(name, None, _t("detail.skipped"))
        original = self.link.state.frequency_hz
        target = original + 1000
        try:
            await self.ctrl.set_frequency(target)
            ok1 = await self._wait_freq(target)
            await self.ctrl.set_frequency(original)
            ok2 = await self._wait_freq(original)
        except Exception as exc:
            return self.record(name, False, _t("detail.command_refused", error=exc))
        return self.record(name, ok1 and ok2, _t("tuning.ok", original=original, target=target)
                           if ok1 and ok2 else _t("detail.freq_mismatch"))

    # ------------------------------------------------------------------ réception : largeurs de filtre

    async def _wait_passband(self, width: int, timeout: float = 3.0) -> int | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.link.state.passband_hz == width:
                return width
            await asyncio.sleep(0.05)
        return self.link.state.passband_hz

    async def stage_filters(self) -> bool:
        self.say(_t("filters.title"))
        name = _t("stage.filters")
        mode, original = self.link.state.mode, self.link.state.passband_hz
        if not mode or not original:
            return self.record(name, None, _t("filters.unreadable"))
        declared = (self.caps.filters.get(mode) if self.caps is not None and self.caps.filters else None) or []
        candidates = filter_candidates(mode, declared)
        self.say(_t("filters.current", mode=mode, width=khz(original),
                    declared=", ".join(khz(w) for w in declared) or _t("filters.nothing")))
        self.say(_t("filters.icom_warning"))
        answer = await self.prompt(_t("filters.prompt", widths=", ".join(khz(w) for w in candidates),
                                      original=khz(original), yn=_t("yn.default_no")))
        if yes_no(answer) is not True:
            return self.record(name, None, _t("detail.skipped"))
        accepted, changed = [], []
        try:
            for width in candidates:
                await self.ctrl.set_mode(mode, width)
                got = await self._wait_passband(width)
                (accepted if got == width else changed).append((width, got))
        except Exception as exc:
            return self.record(name, False, _t("detail.command_refused", error=exc))
        finally:
            try:
                await self.ctrl.set_mode(mode, original)
                await self._wait_passband(original)
            except Exception as exc:
                self.say(_t("filters.not_restored", error=exc))
        detail = _t("filters.accepted", widths=", ".join(khz(w) for w, _ in accepted) or _t("filters.none"))
        if changed:
            detail += _t("filters.changed", widths=", ".join(f"{khz(w)} -> {khz(g) if g else '?'}" for w, g in changed))
        extra = [w for w, _ in accepted if w not in declared]
        if extra:
            detail += _t("filters.undeclared", widths=", ".join(khz(w) for w in extra))
        return self.record(name, bool(accepted), detail)

    # ------------------------------------------------------------------ réception : écran du spectre

    def _count_sweeps(self, port, seconds: float) -> int:
        start, end = port.sweeps, time.monotonic() + seconds
        while time.monotonic() < end:
            port.poll()
        return port.sweeps - start

    async def stage_scope_screen(self) -> bool:
        sp = self.cfg.spectrum
        name = _t("stage.scope")
        if not (sp.enabled and sp.source == "civ_port" and sp.port):
            self.say(_t("scope.not_configured"))
            return True
        self.say(_t("scope.title"))
        answer = await self.prompt(_t("scope.prompt", yn=_t("yn.default_yes")))
        if _declined(answer):
            return self.record(name, None, _t("detail.skipped"))
        from ..spectrum.probe import SCOPE_DISPLAY, SCOPE_OUTPUT, CivPort, open_serial
        try:
            ser = await asyncio.to_thread(self.scope_opener or open_serial, sp.port, sp.baud)
        except ImportError:
            return self.record(name, None, _t("scope.no_pyserial"))
        except (OSError, ValueError) as exc:
            return self.record(name, False, _t("scope.open_failed", port=sp.port, error=exc))
        port = CivPort(ser, cfgmod.parse_civ_address(sp.civ_address))
        before: dict[int, int | None] = {}
        try:
            await asyncio.sleep(1.5)                               # le PTT relu APRÈS l'ouverture (USB SEND sur ce port ?)
            if await self.read_ptt() is True:
                ser.close()
                await self.ctrl.force_rx("spectrum_port_keyed")
                return self.record(name, False, _t("scope.keyed", port=sp.port))
            before = {sub: await asyncio.to_thread(port.read_setting, sub) for sub in (SCOPE_DISPLAY, SCOPE_OUTPUT)}
            if None in before.values():
                return self.record(name, False, _t("scope.no_answer", port=sp.port))
            for sub in (SCOPE_DISPLAY, SCOPE_OUTPUT):
                await asyncio.to_thread(port.set_setting, sub, 1)
            s = self.scope_measure_s
            normal = await asyncio.to_thread(self._count_sweeps, port, s)
            await self.prompt(_t("scope.menu_prompt"))
            on_menu = await asyncio.to_thread(self._count_sweeps, port, s)
            shown = await asyncio.to_thread(port.read_setting, SCOPE_DISPLAY)
            await asyncio.to_thread(port.set_setting, SCOPE_DISPLAY, 1)   # renvoi de « spectre allumé »
            resent = await asyncio.to_thread(self._count_sweeps, port, s)
            await self.prompt(_t("scope.exit_prompt"))
            back = await asyncio.to_thread(self._count_sweeps, port, s)
        finally:
            for sub, value in before.items():
                if value is not None:
                    try:
                        await asyncio.to_thread(port.set_setting, sub, value)
                    except Exception:                               # noqa: BLE001 - port perdu : rien à remettre
                        pass
            try:
                ser.close()
            except Exception:                                       # noqa: BLE001
                pass
        rate = lambda n: f"{n / s:.1f}/s"                           # noqa: E731
        silent = lambda n: n <= max(1, normal * 0.2)                # un balayage déjà en route ne compte pas  # noqa: E731
        if normal == 0:
            verdict = _t("scope.verdict_none")
        elif not silent(on_menu):
            verdict = _t("scope.verdict_menu")
        elif not silent(resent):
            verdict = _t("scope.verdict_resend")
        else:
            verdict = _t("scope.verdict_screen")
        return self.record(name, normal > 0, _t("scope.detail", normal=rate(normal), menu=rate(on_menu), shown=shown,
                                                resent=rate(resent), back=rate(back), verdict=verdict))

    async def _wait_mode(self, mode: str, timeout: float = 3.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.link.state.mode == mode:
                return True
            await asyncio.sleep(0.05)
        return False

    async def stage_band(self) -> None:
        """Hors des bandes autorisées (ex. 27 MHz) : propose d'accorder le poste au milieu d'une bande autorisée."""
        freq = self.link.state.frequency_hz
        if freq is None or not self.cfg.safety.enforce_bands or not self.cfg.bands or self.cfg.tx_allowed(freq):
            return
        name = _t("stage.band")
        self.say(_t("band.title"))
        self.say(_t("band.outside", freq=_hz(freq)))
        centres = [round((b.low_mhz + b.high_mhz) / 2 * 1000) * 1000 for b in self.cfg.bands]
        for i, (band, centre) in enumerate(zip(self.cfg.bands, centres), 1):
            self.say(f"   {i:>2}) {band.name:<5} {_hz(centre)} Hz")
        answer = await self.prompt(_t("band.prompt"))
        if not answer.isdigit() or not 1 <= int(answer) <= len(centres):
            self.record(name, None, _t("band.unchanged"))
            return
        target = centres[int(answer) - 1]
        try:
            await self.ctrl.set_frequency(target)
        except Exception as exc:
            self.record(name, False, _t("band.refused", error=exc))
            return
        ok = await self._wait_freq(target)
        self.record(name, ok, _t("band.tuned", freq=_hz(target)) if ok else _t("detail.freq_mismatch"))

    async def stage_tx_mode(self) -> None:
        """Si `tx_modes` est défini et que le poste est dans un autre mode : propose le mode autorisé correspondant."""
        allowed = self.cfg.rig.tx_modes
        mode = self.link.state.mode
        if not allowed or mode in allowed:
            return
        target = data_mode_for(mode, allowed)
        if target not in allowed:
            target = allowed[0]
        name = _t("stage.tx_mode")
        self.say(_t("txmode.title"))
        if self.caps and self.caps.complete and target not in self.caps.modes:
            self.record(name, False, _t("txmode.absent", target=target, modes=", ".join(self.caps.modes)))
            return
        answer = await self.prompt(_t("txmode.prompt", mode=mode, allowed=", ".join(allowed), target=target,
                                      yn=_t("yn.default_yes")))
        if _declined(answer):
            self.record(name, None, _t("txmode.unchanged"))
            return
        try:
            await self.ctrl.set_mode(target)
        except Exception as exc:
            self.record(name, False, _t("txmode.refused", error=exc))
            return
        ok = await self._wait_mode(target)
        if ok:
            self._mode_to_restore = mode
        self.record(name, ok, f"{mode} -> {target}" if ok else _t("detail.mode_mismatch"))

    async def _offer_data_mode(self) -> None:
        """L'audio USB n'est émis, en général, qu'en mode données (Icom : USB-D, Hamlib PKTUSB)."""
        mode = self.link.state.mode
        target = data_mode_for(mode, self.caps.modes if self.caps else ())
        if not target or not self.caps or target not in self.caps.modes:
            return
        answer = await self.prompt(_t("datamode.prompt", mode=mode, target=target, yn=_t("yn.default_yes")))
        if _declined(answer):
            return
        try:
            await self.ctrl.set_mode(target)
        except Exception as exc:
            self.say(_t("datamode.refused", error=exc))
            return
        if await self._wait_mode(target):
            self._mode_to_restore = mode
            self.say(_t("datamode.active", target=target, mode=mode))
        else:
            self.say(_t("datamode.mismatch"))

    async def _restore_mode(self) -> None:
        if self._mode_to_restore and self.ctrl is not None and self.ctrl.snapshot().state != "RX":
            # Essai interrompu pendant une émission (STOP de la page, Ctrl+C) : le contrôleur se croit encore en
            # émission et le mode restait PKTUSB (vu le 2026-11-18). On COUPE d'abord (jamais refusé), puis on remet.
            try:
                await self.ctrl.force_rx("fin de l'essai : remise du mode")
            except Exception:                                  # noqa: BLE001 : la remise est sautée, dite ci-dessous
                pass
        if self._mode_to_restore and self.ctrl is not None and self.ctrl.snapshot().state != "RX":
            self.say(_t("mode.not_restored", error="poste pas en réception"))
            self._mode_to_restore = None
        if self._mode_to_restore and self.ctrl is not None and self.ctrl.snapshot().state == "RX":
            try:
                await self.ctrl.set_mode(self._mode_to_restore)
                await self._wait_mode(self._mode_to_restore)
                self.say(_t("mode.restored", mode=self._mode_to_restore))
            except Exception as exc:
                self.say(_t("mode.not_restored", error=exc))
            self._mode_to_restore = None

    async def _wait_freq(self, hz: int, timeout: float = 3.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.link.state.frequency_hz == hz:
                return True
            await asyncio.sleep(0.05)
        return False

    # ------------------------------------------------------------------ étape 4 : PTT

    async def stage_ptt(self) -> bool:
        name = _t("stage.ptt")
        if not await self.confirm_emission(_t("ptt.what")):
            return self.record(name, None, _t("detail.not_confirmed"))
        keys, unkeys = [], []
        for n in range(1, self.cycles + 1):
            await asyncio.sleep(self.REKEY_GAP_S)
            t0 = time.monotonic()
            try:
                await self.ctrl.toggle(CLIENT)
            except Refused as exc:
                await self.ctrl.force_rx("hwtest")
                return self.record(name, False, _t("ptt.refused", cycle=n, error=exc))
            keys.append(time.monotonic() - t0)
            await self.sleep_with_heartbeat(self.hold_s)
            tx_seen = await self.read_ptt()
            t1 = time.monotonic()
            await self.ctrl.toggle(CLIENT)
            unkeys.append(time.monotonic() - t1)
            rx_seen = await self.read_ptt()
            self.say(_t("ptt.cycle", cycle=n, key=f"{keys[-1] * 1000:.0f}", unkey=f"{unkeys[-1] * 1000:.0f}",
                        tx=tx_seen, rx=rx_seen))
            if tx_seen is not True or rx_seen is not False or self.ctrl.snapshot().state != "RX":
                await self.ctrl.force_rx("hwtest")
                return self.record(name, False, _t("ptt.mismatch", cycle=n))
        slow = max(keys + unkeys)
        return self.record(name, True, _t("ptt.ok", cycles=self.cycles, key=f"{max(keys) * 1000:.0f}",
                                          unkey=f"{max(unkeys) * 1000:.0f}")
                           + (_t("ptt.slow") if slow > 1.0 else ""))

    # ------------------------------------------------------------------ étape 5 : audio TX

    async def stage_tx_audio(self) -> bool:
        name = _t("stage.tx_audio")
        if not await self.confirm_emission(_t("txaudio.what")):
            return self.record(name, None, _t("detail.not_confirmed"))
        await self._offer_data_mode()
        self.say(_t("txaudio.watch"))
        lines = []
        powers: list[float | None] = []
        self.audio_no_power = False
        previous_good: float | None = None
        for level in self.tx_levels_db:
            try:
                await self.key()
            except Refused as exc:
                await self.ctrl.force_rx("hwtest")
                return self.record(name, False, _t("detail.key_refused", error=exc))
            sent, readings = await self._send_tone(level)
            await self.ctrl.toggle(CLIENT)
            powers.append(readings.get("RFPOWER_METER"))
            swr = readings.get("SWR")
            if readings:
                line = _t("txaudio.line", level=f"{level:.0f}", sent=sent,
                          readings=", ".join(f"{k}={v:.2f}" for k, v in readings.items()))
            else:
                line = _t("txaudio.line_none", level=f"{level:.0f}", sent=sent)
            self.say(f"  {line}")
            lines.append(line)
            if swr is not None and swr > 2.0:
                return self.record(name, False, _t("txaudio.high_swr", swr=f"{swr:.1f}"))
            if sent < 0.9 * (self.tx_seconds / FRAME_S):
                return self.record(name, False, _t("txaudio.not_sent", sent=sent))
            power, alc = readings.get("RFPOWER_METER") or 0.0, readings.get("ALC")
            if self.alc_stop is not None and power > 0 and alc is not None:
                if alc >= self.alc_stop:                 # ALC hors de la zone correcte : on s'arrête là
                    self.tx_level_advice = previous_good if previous_good is not None else level
                    self.say(_t("txaudio.alc_stop", alc=f"{alc:.2f}", advice=f"{self.tx_level_advice:.0f}"))
                    break
                previous_good = level
            if level != self.tx_levels_db[-1]:
                if _declined(await self.prompt(_t("txaudio.next", yn=_t("yn.default_yes")))):
                    break
        if powers and all(p is not None and p <= 0.0 for p in powers):
            # Puissance LISIBLE mais nulle à chaque niveau : le son part ailleurs (vu sur l'IC-7300MK2 sans sa carte son,
            # étape 255 : « OK » à tort). Jamais un succès.
            self.audio_no_power = True           # voie radio saine, modulation absente : exercices sans audio permis
            return self.record(name, False, _t("txaudio.no_power", last=lines[-1]))
        if self.alc_stop is not None and self.tx_level_advice is None and previous_good is not None:
            self.tx_level_advice = previous_good         # puissance vue, ALC jamais au seuil : dernier palier
        advice = _t("txaudio.advice", advice=f"{self.tx_level_advice:.0f}") if self.tx_level_advice is not None else ""
        return self.record(name, True, _t("txaudio.ok", count=len(lines), last=lines[-1]) + advice)

    async def _send_tone(self, level_db: float) -> tuple[int, dict[str, float]]:
        frames, sent, pos = int(self.tx_seconds / FRAME_S), 0, 0
        peaks: dict[str, float] = {}
        next_t = time.monotonic()
        for i in range(frames):
            if self.pipeline.gate.push(CLIENT, tone(1000.0, level_db, pos)):
                sent += 1
            pos += FRAME_SAMPLES
            if i % 5 == 0:
                self.ctrl.heartbeat(CLIENT)
            if i % 25 == 24:
                for name in ("ALC", "SWR", "RFPOWER_METER"):
                    try:
                        value = await self.link.client.get_level(name)
                        peaks[name] = max(peaks.get(name, value), value)
                    except Exception:
                        pass
            next_t += FRAME_S
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))
        return sent, peaks

    # ------------------------------------------------------------------ étape 6 : pannes

    async def _drill(self, name: str, expected_reason: str, expected_s: float, tolerance_s: float, trigger) -> bool:
        try:
            await self.key()
        except Refused as exc:
            await self.ctrl.force_rx("hwtest")
            return self.record(name, False, _t("detail.key_refused", error=exc))
        t0 = time.monotonic()
        await trigger()
        deadline = time.monotonic() + expected_s + tolerance_s + 3.0
        while self.ctrl.snapshot().state != "RX" and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        elapsed = time.monotonic() - t0
        snap = self.ctrl.snapshot()
        released = await self.read_ptt()
        if snap.state != "RX" or released is not False:
            await self.ctrl.force_rx("hwtest")
            return self.record(name, False, _t("detail.not_cut"))
        ok = snap.last_cut_reason == expected_reason and abs(elapsed - expected_s) <= tolerance_s
        return self.record(name, ok, _t("drill.cut", elapsed=f"{elapsed:.1f}", reason=snap.last_cut_reason,
                                        expected=expected_reason, expected_s=f"{expected_s:.1f}"))

    async def stage_drills(self) -> bool:
        if not await self.confirm_emission(_t("drills.what")):
            return self.record(_t("stage.drills"), None, _t("detail.not_confirmed"))

        async def nothing() -> None:                       # aucun heartbeat : le client « se tait »
            return None

        async def heartbeats_until_tot() -> None:          # le client se comporte bien : seul le TOT doit couper
            end = time.monotonic() + self.tot_s + 2.0
            while self.ctrl.snapshot().state != "RX" and time.monotonic() < end:
                self.ctrl.heartbeat(CLIENT)
                await asyncio.sleep(0.1)

        async def disconnect() -> None:
            await self.ctrl.disconnect_client(CLIENT)

        ok = await self._drill(_t("drill.heartbeat"), "heartbeat", self.heartbeat_timeout_s, 1.0, nothing)
        ok &= await self._drill(_t("drill.tot", tot=f"{self.tot_s:.0f}"), "tot", self.tot_s, 1.5, heartbeats_until_tot)
        ok &= await self._drill(_t("drill.disconnect"), "client_disconnected", 0.0, 1.0, disconnect)
        self.ctrl.connect_client(CLIENT)
        return ok

    # ------------------------------------------------------------------ étape 7 : coupure par le poste

    async def stage_rig_unkey(self) -> bool:
        """Le poste repasse en réception de lui-même : la relecture du PTT (pas une valeur en cache) doit le voir."""
        name = _t("unkey.name", spectrum=_t("unkey.spectrum_on" if self.cfg.spectrum.enabled else "unkey.spectrum_off"))
        if not await self.confirm_emission(_t("unkey.what")):
            return self.record(name, None, _t("detail.not_confirmed"))
        self.say(_t("unkey.howto"))
        self.say(_t("unkey.poll", poll=f"{self.ctrl.limits.rig_poll_s:g}", tot=f"{self.tot_s:g}"))
        await self.prompt(_t("unkey.ready"))                                      # question posée AVANT la prise d'émission
        try:
            await self.key()
        except Refused as exc:
            await self.ctrl.force_rx("hwtest")
            return self.record(name, False, _t("detail.key_refused", error=exc))
        self.say(_t("unkey.now"))
        t0 = time.monotonic()
        deadline = t0 + self.tot_s + 3.0
        while self.ctrl.snapshot().state != "RX" and time.monotonic() < deadline:
            self.ctrl.heartbeat(CLIENT)                                               # seul le poste doit provoquer la coupure
            await asyncio.sleep(0.05)
        elapsed = time.monotonic() - t0
        snap = self.ctrl.snapshot()
        if snap.state != "RX":
            await self.ctrl.force_rx("hwtest")
            return self.record(name, False, _t("detail.not_cut"))
        reason = snap.last_cut_reason
        if reason == "rig_reported_rx":
            return self.record(name, True, _t("unkey.seen", elapsed=f"{elapsed:.1f}"))
        if reason == "tot":
            return self.record(name, False, _t("unkey.not_seen"))
        return self.record(name, False, _t("unkey.other", reason=reason))

    # ------------------------------------------------------------------ déroulement

    async def run(self) -> list[StageResult]:
        if self.rx_only:
            self.say(_t("notice.rx_only"))
        else:
            self.say(preflight_text())
            if not typed_yes(await self.prompt(_t("preflight.prompt", word=_t("word.yes")))):
                self.say(_t("run.cancelled"))
                return []
        try:
            if not await self.setup():
                return self.results
            if not await self.stage_cat():
                self.say(_t("run.cat_failed"))
                return self.results
            if not self.only_rig_unkey:
                await self.stage_rx_audio()
                await self.stage_tuning()
                await self.stage_filters()
                await self.stage_scope_screen()
                if self.cfg.selcall.enabled:                 # proposé seulement à qui utilise SELCALL
                    await self.stage_selcall_rx()
            if self.rx_only:
                return self.results
            await self.stage_band()
            await self.stage_tx_mode()
            if self.cfg.safety.enforce_bands and not self.cfg.bands:
                self.record(_t("stage.tx_all"), None, _t("run.no_bands"))
            elif self.cfg.safety.enforce_bands and not self.cfg.tx_allowed(self.link.state.frequency_hz or 0):
                self.record(_t("stage.tx_all"), False, _t("run.out_of_band", freq=self.link.state.frequency_hz))
            elif self.only_rig_unkey:
                await self.stage_rig_unkey()
            else:
                if await self.stage_ptt():
                    if await self.stage_tx_audio() or self.audio_no_power:
                        await self.stage_drills()
                    else:                                    # ROS élevé, audio non transmis... : plus aucune émission
                        self.record(_t("stage.drills"), None, _t("run.drills_skipped"))
        finally:
            await self._restore_mode()
            await self.teardown()
            self.say("")
            self.say(_t("run.back_to_rx"))
        return self.results

    def report(self) -> int:
        self.say(_t("report.title"))
        tags = {True: _t("tag.ok"), False: _t("tag.fail"), None: _t("tag.skipped")}
        width = max(6, *(len(t) for t in tags.values()))
        for r in self.results:
            self.say(f"  {tags[r.ok if r.ok is None else bool(r.ok)].ljust(width)}  {r.name}")
        failed = [r for r in self.results if r.ok is False]
        self.say("\n" + (_t("report.all_ok") if not failed else _t("report.failed", count=len(failed))))
        return 1 if failed else 0


# ---------------------------------------------------------------------- ligne de commande

def _port_open(cfg: Config) -> bool:
    try:
        with socket.create_connection((cfg.network.rigctld_host, cfg.network.rigctld_port), 0.3):
            return True
    except OSError:
        return False


async def run_hwtest(cfg: Config, hw: HwTest, *, spawn: bool = True) -> int:
    install_quiet_handler(asyncio.get_running_loop())
    proc = None
    if not _port_open(cfg):
        if not spawn:
            hw.say(_t("cli.no_rigctld", host=cfg.network.rigctld_host, port=cfg.network.rigctld_port))
            return 3
        try:
            hw.say(_t("cli.starting_rigctld"))
            serial_ptt = cfg.rig.ptt_type in ("RTS", "DTR")
            hw.say(_t("cli.rts_dtr_warning") if serial_ptt else "")
            proc = subprocess.Popen(rigctld_command(cfg))
        except FileNotFoundError as exc:
            hw.say(str(exc))
            return 3
        for _ in range(50):
            if _port_open(cfg) or proc.poll() is not None:
                break
            await asyncio.sleep(0.1)
        if not _port_open(cfg):
            hw.say(_t("cli.rigctld_failed"))
            return 3
    elif station_running(cfg.supervisor.instance_lock_port):
        # Étape 201 : l'essai partageait le poste avec la station en marche (deux programmes qui pilotent le PTT).
        _, message = render(codes.ORT_9313, outil="trx-hwtest", comment=_t("cli.stop_station"))
        hw.say(f"{codes.ORT_9313} {message}")
        return 3
    else:
        hw.say(_t("cli.rigctld_running"))
    try:
        await hw.run()
        return hw.report()
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()


@guarded("trx-hwtest")
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-hwtest", description="Essai guidé sur un vrai poste")
    ap.add_argument("--config", type=Path, default=default_config_path())
    ap.add_argument("--tot", type=float, default=8.0, help="durée du TOT pendant l'essai, en secondes (défaut : 8)")
    ap.add_argument("--tx-levels", type=float, nargs="+", default=[-40.0, -30.0, -24.0], metavar="DBFS",
                    help="niveaux d'essai de la tonalité, en dBFS, séparés par des espaces (défaut : -40 -30 -24)")
    ap.add_argument("--no-spawn", action="store_true", help="ne pas lancer rigctld soi-même")
    ap.add_argument("--coupure-poste", action="store_true",
                    help="CAT puis seulement l'exercice « coupure faite sur le poste » (à comparer spectre activé / désactivé)")
    ap.add_argument("--reception-seule", action="store_true",
                    help="aucune émission : CAT, audio reçu, accord, largeurs de filtre, écran du spectre")
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except cfgmod.ConfigError as exc:
        print(_t("cli.config_invalid") + "\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    except OSError as exc:
        print(_t("cli.config_unreadable", path=args.config, error=exc), file=sys.stderr)
        return 2
    levels = tuple(args.tx_levels)
    if any(v > -12 for v in levels):
        print(_t("cli.level_too_high"), file=sys.stderr)
        return 2
    if not 2.0 <= args.tot <= 60.0:
        print(_t("cli.tot_range"), file=sys.stderr)
        return 2
    try:
        hw = HwTest(cfg, tot_s=args.tot, tx_levels_db=levels, only_rig_unkey=args.coupure_poste,
                    rx_only=args.reception_seule)
    except ValueError as exc:
        print(_t("cli.tot_error", error=exc), file=sys.stderr)
        return 2
    try:
        return asyncio.run(run_hwtest(cfg, hw, spawn=not args.no_spawn))
    except KeyboardInterrupt:
        print(_t("cli.interrupted"), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
