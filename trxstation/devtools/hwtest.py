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
"""
from __future__ import annotations

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
from ..asyncio_noise import install_quiet_handler
from ..config import Config
from ..gateway.audio import AudioConfigError, AudioPipeline
from ..gateway.audio.devices import WavSink
from ..gateway.audio.pcm import FLOOR_DB, FRAME_S, FRAME_SAMPLES, rms_dbfs, tone
from ..gateway.cat import Capabilities, CatLink, load_capabilities
from ..gateway.cat.capabilities import data_mode_for
from ..gateway.safety import PttController, PttLimits, Refused
from ..hamlib import rigctld_command
from ..paths import default_config_path

CLIENT = "hwtest"
EMIT_WORD = "EMETTRE"

PREFLIGHT = """
================  ESSAI SUR UN VRAI POSTE : À LIRE AVANT DE CONTINUER  ================
 1. L'ANTENNE est DÉBRANCHÉE : une CHARGE FICTIVE (50 ohms, puissance suffisante) est connectée.
 2. La PUISSANCE d'émission du poste est au MINIMUM (5 W ou moins).
 3. Le VOX est désactivé. La TEMPORISATION D'ÉMISSION (TOT) INTERNE du poste est réglée
    (1 à 3 minutes) : c'est le dernier filet si l'ordinateur, le logiciel ou le câble USB lâche.
 4. Les SONS WINDOWS (notifications) ne partent PAS vers la carte son du poste : ni sortie par
    défaut, ni sons système, ni autre logiciel (WSJT-X, HRD...) qui utilise le poste.
 5. Tu restes PRÈS DU POSTE : tu peux couper l'alimentation ou débrancher la charge à tout moment.
 6. Ta licence t'autorise à émettre sur la fréquence affichée.
=========================================================================================
"""


RX_ONLY_NOTICE = """
================  ESSAI EN RÉCEPTION SEULE : AUCUNE ÉMISSION  ================
 Le poste est relu, la fréquence, la largeur du filtre et l'écran du spectre sont changés puis remis.
 Tu restes près du poste : deux étapes te demandent d'agir sur lui (touches MENU puis EXIT).
==============================================================================
"""

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
                 scope_measure_s: float = 3.0):
        self.cfg, self.ask, self.out = cfg, ask, out
        self.only_rig_unkey, self.rx_only = only_rig_unkey, rx_only
        self.scope_opener, self.scope_measure_s = scope_opener, scope_measure_s
        self.tot_s, self.hold_s, self.tx_seconds, self.rx_listen_s = tot_s, hold_s, tx_seconds, rx_listen_s
        self.tx_levels_db, self.cat_timeout_s, self.record_wav, self.cycles = tx_levels_db, cat_timeout_s, record_wav, cycles
        self.results: list[StageResult] = []
        self.caps = capabilities
        self._mode_to_restore: str | None = None
        self.link: CatLink | None = None
        self.pipeline: AudioPipeline | None = None
        self.ctrl: PttController | None = None
        self._link_task: asyncio.Task | None = None
        self.heartbeat_timeout_s = cfg.safety.heartbeat_timeout_ms / 1000
        if tot_s < self.heartbeat_timeout_s + 1.0:
            raise ValueError(f"le TOT d'essai ({tot_s:g} s) doit dépasser d'au moins 1 s le délai de heartbeat "
                             f"({self.heartbeat_timeout_s:g} s), sinon l'exercice de panne est ambigu")

    # ------------------------------------------------------------------ utilitaires

    def say(self, text: str = "") -> None:
        self.out(text)

    async def prompt(self, text: str) -> str:
        assert self.ctrl is None or self.ctrl.snapshot().state == "RX", "question posée pendant une émission"
        return (await asyncio.to_thread(self.ask, text)).strip()       # la boucle (watchdog, CAT) continue de tourner

    def record(self, name: str, ok: bool | None, detail: str) -> bool:
        self.results.append(StageResult(name, ok, detail))
        tag = {True: "OK     ", False: "ÉCHEC  ", None: "IGNORÉ "}[ok]
        self.say(f"  [{tag}] {name} : {detail}")
        return ok is not False

    async def confirm_emission(self, what: str) -> bool:
        self.say(f"\n>>> {what}")
        self.say("    Charge fictive branchée, puissance minimale, tu es près du poste.")
        answer = await self.prompt(f"    Pour continuer, tape {EMIT_WORD} (autre chose = on passe) : ")
        return answer.upper() == EMIT_WORD

    async def read_ptt(self) -> bool | None:
        try:
            return await self.link.client.get_ptt()
        except Exception:
            return None

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
                self.say(f"  (capacités du poste indisponibles : {exc})")
        caps = self.caps
        try:
            self.pipeline = AudioPipeline(cfg.audio)
            await self.pipeline.start()
        except AudioConfigError as exc:
            self.record("Audio (ouverture)", False, str(exc))
            return False
        self.link = CatLink(cfg.network.rigctld_host, cfg.network.rigctld_port, capabilities=caps, timeout=2.0)
        limits = PttLimits(tot_s=self.tot_s, warn_before_s=min(5.0, self.tot_s / 2),
                           heartbeat_timeout_s=self.heartbeat_timeout_s, rekey_cooldown_s=0.3)
        self.ctrl = PttController(self.link, cfg, limits=limits, audio_gate=self.pipeline.gate.set_open)
        self.pipeline.gate.owner_provider = lambda: self.ctrl.snapshot().owner
        self._link_task = asyncio.create_task(self.link.run())
        await self.ctrl.start()
        self.ctrl.connect_client(CLIENT)
        return True

    async def teardown(self) -> None:
        """Toujours exécuté : coupe l'émission, ferme l'audio, arrête la liaison."""
        if self.ctrl is not None:
            try:
                await self.ctrl.close()
            except Exception as exc:
                self.say(f"!!! coupure finale en erreur : {exc!r}")
        if self.pipeline is not None:
            await self.pipeline.stop()
        if self.link is not None:
            self.link.stop()
        if self._link_task is not None:
            await asyncio.gather(self._link_task, return_exceptions=True)

    # ------------------------------------------------------------------ étape 1 : CAT

    async def stage_cat(self) -> bool:
        self.say("\n--- Étape 1 : liaison CAT (lecture seule, aucune émission) ---")
        deadline = time.monotonic() + self.cat_timeout_s
        while time.monotonic() < deadline:
            if self.link.state.connected and self.link.state.frequency_hz is not None:
                break
            await asyncio.sleep(0.1)
        state = self.link.state
        if not state.connected:
            return self.record("CAT", False, "rigctld injoignable : est-il lancé ? (trx-rigctld --config ...)")
        if state.frequency_hz is None:
            return self.record("CAT", False, f"rigctld répond mais pas le poste ({state.last_error or 'pas de réponse'}) : "
                                             "vérifie modèle, port COM, débit, poste allumé, câble USB")
        samples = []
        for _ in range(5):
            samples.append(self.link.state.strength_db)
            await asyncio.sleep(0.2)
        caps = self.caps
        self.say(f"  Poste : {caps.manufacturer + ' ' + caps.model_name if caps and caps.model_name else 'modèle ' + str(self.cfg.rig.model)}")
        self.say(f"  Fréquence {state.frequency_hz:,} Hz".replace(",", " ") + f", mode {state.mode}, filtre {state.passband_hz} Hz")
        self.say(f"  S-mètre (dB / S9) : {samples}")
        ptt = await self.read_ptt()
        if ptt is True:
            return self.record("CAT", False, "le poste est EN ÉMISSION alors qu'il ne devrait pas : vérifie le PTT/VOX")
        if ptt is None:
            return self.record("CAT", False, "l'état du PTT n'est pas lisible : l'émission serait refusée par sécurité")
        return self.record("CAT", True, f"{state.frequency_hz:,} Hz {state.mode}, PTT lisible et en réception".replace(",", " "))

    # ------------------------------------------------------------------ étape 2 : audio RX

    async def stage_rx_audio(self) -> bool:
        self.say(f"\n--- Étape 2 : audio reçu ({self.rx_listen_s:.0f} s ; aucune émission) ---")
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
            return self.record("Audio RX", False, "aucune trame reçue de la carte son : périphérique de capture inactif ?")
        mean, peak = sum(levels) / len(levels), max(levels)
        self.say(f"  Niveau : moyen {mean:.0f} dBFS, crête {peak:.0f} dBFS ({len(levels)} trames) ; écoute {self.record_wav}")
        if peak <= FLOOR_DB + 1:
            return self.record("Audio RX", False, "silence total : mauvais périphérique, sortie USB du poste coupée, ou volume nul")
        if peak > -3:
            return self.record("Audio RX", True, f"ATTENTION saturation (crête {peak:.0f} dBFS) : baisse le niveau de sortie USB du poste ou rx_gain_db")
        hint = f" ; suggestion rx_gain_db ≈ {max(-40, min(20, round(-30 - mean)))}" if abs(mean + 30) > 10 else ""
        return self.record("Audio RX", True, f"moyen {mean:.0f} dBFS, crête {peak:.0f} dBFS{hint}")

    # ------------------------------------------------------------------ étape 3 : accord

    async def stage_tuning(self) -> bool:
        self.say("\n--- Étape 3 : changement de fréquence (réception seulement) ---")
        answer = await self.prompt("  Décaler la fréquence de +1 kHz puis la rétablir ? [O/n] : ")
        if answer.lower() in ("n", "non"):
            return self.record("Accord", None, "ignoré")
        original = self.link.state.frequency_hz
        target = original + 1000
        try:
            await self.ctrl.set_frequency(target)
            ok1 = await self._wait_freq(target)
            await self.ctrl.set_frequency(original)
            ok2 = await self._wait_freq(original)
        except Exception as exc:
            return self.record("Accord", False, f"commande refusée : {exc}")
        return self.record("Accord", ok1 and ok2, f"{original} -> {target} -> {original} Hz relus sur le poste"
                           if ok1 and ok2 else "la fréquence relue ne correspond pas à la commande")

    # ------------------------------------------------------------------ réception : largeurs de filtre

    async def _wait_passband(self, width: int, timeout: float = 3.0) -> int | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.link.state.passband_hz == width:
                return width
            await asyncio.sleep(0.05)
        return self.link.state.passband_hz

    async def stage_filters(self) -> bool:
        self.say("\n--- Largeurs de filtre (réception seulement) ---")
        mode, original = self.link.state.mode, self.link.state.passband_hz
        if not mode or not original:
            return self.record("Largeurs de filtre", None, "mode ou largeur du filtre illisible")
        declared = (self.caps.filters.get(mode) if self.caps is not None and self.caps.filters else None) or []
        candidates = filter_candidates(mode, declared)
        self.say(f"  Mode {mode}, largeur actuelle {khz(original)} ; Hamlib déclare : "
                 f"{', '.join(khz(w) for w in declared) or 'rien'}")
        answer = await self.prompt(f"  Essayer {', '.join(khz(w) for w in candidates)} puis remettre {khz(original)} ? [O/n] : ")
        if answer.lower() in ("n", "non"):
            return self.record("Largeurs de filtre", None, "ignoré")
        accepted, changed = [], []
        try:
            for width in candidates:
                await self.ctrl.set_mode(mode, width)
                got = await self._wait_passband(width)
                (accepted if got == width else changed).append((width, got))
        except Exception as exc:
            return self.record("Largeurs de filtre", False, f"commande refusée : {exc}")
        finally:
            try:
                await self.ctrl.set_mode(mode, original)
                await self._wait_passband(original)
            except Exception as exc:
                self.say(f"  !!! largeur d'origine non remise ({exc}) : remets-la sur le poste")
        detail = "acceptées telles quelles : " + (", ".join(khz(w) for w, _ in accepted) or "aucune")
        if changed:
            detail += " ; ramenées par le poste : " + ", ".join(f"{khz(w)} -> {khz(g) if g else '?'}" for w, g in changed)
        extra = [w for w, _ in accepted if w not in declared]
        if extra:
            detail += f" ; NON déclarées par Hamlib mais acceptées : {', '.join(khz(w) for w in extra)}"
        return self.record("Largeurs de filtre", bool(accepted), detail)

    # ------------------------------------------------------------------ réception : écran du spectre

    def _count_sweeps(self, port, seconds: float) -> int:
        start, end = port.sweeps, time.monotonic() + seconds
        while time.monotonic() < end:
            port.poll()
        return port.sweeps - start

    async def stage_scope_screen(self) -> bool:
        sp = self.cfg.spectrum
        name = "Écran du spectre"
        if not (sp.enabled and sp.source == "civ_port" and sp.port):
            self.say("\n  (Écran du spectre : pas de spectre par le second port dans station.toml, étape sautée)")
            return True
        self.say("\n--- Écran du spectre par le second port (réception seulement) ---")
        answer = await self.prompt("  Mesurer le spectre écran normal, puis poste sur un menu ? [O/n] : ")
        if answer.lower() in ("n", "non"):
            return self.record(name, None, "ignoré")
        from ..spectrum.probe import SCOPE_DISPLAY, SCOPE_OUTPUT, CivPort, open_serial
        try:
            ser = await asyncio.to_thread(self.scope_opener or open_serial, sp.port, sp.baud)
        except ImportError:
            return self.record(name, None, "module pyserial absent")
        except (OSError, ValueError) as exc:
            return self.record(name, False, f"ouverture de {sp.port} impossible : {exc}")
        port = CivPort(ser, cfgmod.parse_civ_address(sp.civ_address))
        before: dict[int, int | None] = {}
        try:
            await asyncio.sleep(1.5)                               # le PTT relu APRÈS l'ouverture (USB SEND sur ce port ?)
            if await self.read_ptt() is True:
                ser.close()
                await self.ctrl.force_rx("spectrum_port_keyed")
                return self.record(name, False, f"l'ouverture de {sp.port} met le poste en ÉMISSION (réglage USB SEND) : coupé")
            before = {sub: await asyncio.to_thread(port.read_setting, sub) for sub in (SCOPE_DISPLAY, SCOPE_OUTPUT)}
            if None in before.values():
                return self.record(name, False, f"le poste ne répond pas aux réglages du spectre sur {sp.port}")
            for sub in (SCOPE_DISPLAY, SCOPE_OUTPUT):
                await asyncio.to_thread(port.set_setting, sub, 1)
            s = self.scope_measure_s
            normal = await asyncio.to_thread(self._count_sweeps, port, s)
            await self.prompt("  Mets le poste sur un MENU (touche MENU), puis appuie sur Entrée : ")
            on_menu = await asyncio.to_thread(self._count_sweeps, port, s)
            shown = await asyncio.to_thread(port.read_setting, SCOPE_DISPLAY)
            await asyncio.to_thread(port.set_setting, SCOPE_DISPLAY, 1)   # renvoi de « spectre allumé »
            resent = await asyncio.to_thread(self._count_sweeps, port, s)
            await self.prompt("  Remets le poste sur son écran habituel (touche EXIT), puis Entrée : ")
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
            verdict = "aucun balayage même écran normal : spectre éteint ou port mal réglé"
        elif not silent(on_menu):
            verdict = "le poste envoie le spectre même sur un menu"
        elif not silent(resent):
            verdict = "le renvoi de « spectre allumé » RAMÈNE le spectre depuis un menu : la station peut le faire"
        else:
            verdict = "rien ne ramène le spectre depuis un menu : il faut que l'écran du poste montre le spectre"
        return self.record(name, normal > 0, f"écran normal {rate(normal)}, sur un menu {rate(on_menu)} (affichage lu : "
                                             f"{shown}), après renvoi {rate(resent)}, retour {rate(back)} ; {verdict}")

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
        self.say("\n--- Fréquence d'essai ---")
        self.say(f"  Le poste est sur {freq:,} Hz, hors des bandes d'émission autorisées.".replace(",", " "))
        centres = [round((b.low_mhz + b.high_mhz) / 2 * 1000) * 1000 for b in self.cfg.bands]
        for i, (band, centre) in enumerate(zip(self.cfg.bands, centres), 1):
            self.say(f"   {i:>2}) {band.name:<5} {centre:,} Hz".replace(",", " "))
        answer = await self.prompt("  Numéro de la bande d'essai (Entrée = ne pas changer) : ")
        if not answer.isdigit() or not 1 <= int(answer) <= len(centres):
            self.record("Bande d'essai", None, "fréquence inchangée")
            return
        target = centres[int(answer) - 1]
        try:
            await self.ctrl.set_frequency(target)
        except Exception as exc:
            self.record("Bande d'essai", False, f"accord refusé : {exc}")
            return
        ok = await self._wait_freq(target)
        self.record("Bande d'essai", ok, f"accordé sur {target:,} Hz".replace(",", " ") if ok
                    else "la fréquence relue ne correspond pas à la commande")

    async def stage_tx_mode(self) -> None:
        """Si `tx_modes` est défini et que le poste est dans un autre mode : propose le mode autorisé correspondant."""
        allowed = self.cfg.rig.tx_modes
        mode = self.link.state.mode
        if not allowed or mode in allowed:
            return
        target = data_mode_for(mode, allowed)
        if target not in allowed:
            target = allowed[0]
        self.say("\n--- Mode d'émission ---")
        if self.caps and self.caps.complete and target not in self.caps.modes:
            self.record("Mode d'émission", False, f"{target} n'existe pas sur ce poste (modes : {', '.join(self.caps.modes)})")
            return
        answer = await self.prompt(f"  Le poste est en {mode}, mode non autorisé à l'émission ({', '.join(allowed)}). "
                                   f"Passer en {target} ? [O/n] : ")
        if answer.lower() in ("n", "non"):
            self.record("Mode d'émission", None, "inchangé : l'émission sera refusée")
            return
        try:
            await self.ctrl.set_mode(target)
        except Exception as exc:
            self.record("Mode d'émission", False, f"changement refusé : {exc}")
            return
        ok = await self._wait_mode(target)
        if ok:
            self._mode_to_restore = mode
        self.record("Mode d'émission", ok, f"{mode} -> {target}" if ok else "le mode relu ne correspond pas à la commande")

    async def _offer_data_mode(self) -> None:
        """L'audio USB n'est émis, en général, qu'en mode données (Icom : USB-D, Hamlib PKTUSB)."""
        mode = self.link.state.mode
        target = data_mode_for(mode, self.caps.modes if self.caps else ())
        if not target or not self.caps or target not in self.caps.modes:
            return
        answer = await self.prompt(f"  Le poste est en {mode}. Pour que l'audio USB soit émis il faut en général le "
                                   f"mode données ({target}) ; l'y mettre ? [O/n] : ")
        if answer.lower() in ("n", "non"):
            return
        try:
            await self.ctrl.set_mode(target)
        except Exception as exc:
            self.say(f"  changement de mode refusé : {exc}")
            return
        if await self._wait_mode(target):
            self._mode_to_restore = mode
            self.say(f"  Mode {target} actif (le mode {mode} sera rétabli à la fin).")
        else:
            self.say("  le mode relu ne correspond pas à la commande")

    async def _restore_mode(self) -> None:
        if self._mode_to_restore and self.ctrl is not None and self.ctrl.snapshot().state == "RX":
            try:
                await self.ctrl.set_mode(self._mode_to_restore)
                await self._wait_mode(self._mode_to_restore)
                self.say(f"  Mode {self._mode_to_restore} rétabli.")
            except Exception as exc:
                self.say(f"  mode d'origine non rétabli ({exc}) : vérifie le poste")
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
        if not await self.confirm_emission("Étape 4 : PTT, 3 cycles de porteuse SANS audio (en SSB : aucun signal)"):
            return self.record("PTT", None, "non confirmé : ignoré")
        keys, unkeys = [], []
        for n in range(1, self.cycles + 1):
            await asyncio.sleep(self.REKEY_GAP_S)
            t0 = time.monotonic()
            try:
                await self.ctrl.toggle(CLIENT)
            except Refused as exc:
                await self.ctrl.force_rx("hwtest")
                return self.record("PTT", False, f"prise d'émission refusée au cycle {n} : {exc}")
            keys.append(time.monotonic() - t0)
            await self.sleep_with_heartbeat(self.hold_s)
            tx_seen = await self.read_ptt()
            t1 = time.monotonic()
            await self.ctrl.toggle(CLIENT)
            unkeys.append(time.monotonic() - t1)
            rx_seen = await self.read_ptt()
            self.say(f"  cycle {n} : prise {keys[-1] * 1000:.0f} ms, coupure {unkeys[-1] * 1000:.0f} ms "
                     f"(poste relu : TX={tx_seen}, puis TX={rx_seen})")
            if tx_seen is not True or rx_seen is not False or self.ctrl.snapshot().state != "RX":
                await self.ctrl.force_rx("hwtest")
                return self.record("PTT", False, f"cycle {n} : l'état relu sur le poste ne correspond pas aux ordres")
        slow = max(keys + unkeys)
        return self.record("PTT", True, f"{self.cycles} cycles, prise max {max(keys) * 1000:.0f} ms, "
                           f"coupure max {max(unkeys) * 1000:.0f} ms" + (" (LENT : > 1 s)" if slow > 1.0 else ""))

    # ------------------------------------------------------------------ étape 5 : audio TX

    async def stage_tx_audio(self) -> bool:
        if not await self.confirm_emission("Étape 5 : audio d'émission, tonalité 1 kHz à niveau croissant (faible puissance)"):
            return self.record("Audio TX", None, "non confirmé : ignoré")
        await self._offer_data_mode()
        self.say("  Surveille la puissance et l'ALC sur le poste : l'ALC doit rester à peine visible.")
        lines = []
        for level in self.tx_levels_db:
            try:
                await self.key()
            except Refused as exc:
                await self.ctrl.force_rx("hwtest")
                return self.record("Audio TX", False, f"prise d'émission refusée : {exc}")
            sent, readings = await self._send_tone(level)
            await self.ctrl.toggle(CLIENT)
            swr = readings.get("SWR")
            line = f"{level:.0f} dBFS : {sent} trames passées ; " + ", ".join(
                f"{k}={v:.2f}" for k, v in readings.items()) if readings else f"{level:.0f} dBFS : {sent} trames passées (aucun niveau lisible)"
            self.say(f"  {line}")
            lines.append(line)
            if swr is not None and swr > 2.0:
                return self.record("Audio TX", False, f"ROS {swr:.1f} > 2 : charge/antenne en défaut, essai interrompu")
            if sent < 0.9 * (self.tx_seconds / FRAME_S):
                return self.record("Audio TX", False, f"seulement {sent} trames passées la porte : audio d'émission non transmis")
            if level != self.tx_levels_db[-1]:
                if (await self.prompt("  Niveau suivant, plus fort ? [O/n] : ")).lower() in ("n", "non"):
                    break
        return self.record("Audio TX", True, f"{len(lines)} niveau(x) essayé(s) ; dernier : {lines[-1]}")

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
            return self.record(name, False, f"prise d'émission refusée : {exc}")
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
            return self.record(name, False, "L'ÉMISSION N'A PAS ÉTÉ COUPÉE dans le délai : voir le superviseur")
        ok = snap.last_cut_reason == expected_reason and abs(elapsed - expected_s) <= tolerance_s
        return self.record(name, ok, f"coupée en {elapsed:.1f} s par « {snap.last_cut_reason} » "
                                     f"(attendu : {expected_reason}, ~{expected_s:.1f} s)")

    async def stage_drills(self) -> bool:
        if not await self.confirm_emission("Étape 6 : exercices de panne (porteuse sans audio : perte du heartbeat, TOT, déconnexion)"):
            return self.record("Pannes", None, "non confirmé : ignoré")

        async def nothing() -> None:                       # aucun heartbeat : le client « se tait »
            return None

        async def heartbeats_until_tot() -> None:          # le client se comporte bien : seul le TOT doit couper
            end = time.monotonic() + self.tot_s + 2.0
            while self.ctrl.snapshot().state != "RX" and time.monotonic() < end:
                self.ctrl.heartbeat(CLIENT)
                await asyncio.sleep(0.1)

        async def disconnect() -> None:
            await self.ctrl.disconnect_client(CLIENT)

        ok = await self._drill("Panne : perte du heartbeat", "heartbeat", self.heartbeat_timeout_s, 1.0, nothing)
        ok &= await self._drill(f"Panne : TOT ({self.tot_s:.0f} s)", "tot", self.tot_s, 1.5, heartbeats_until_tot)
        ok &= await self._drill("Panne : déconnexion du client", "client_disconnected", 0.0, 1.0, disconnect)
        self.ctrl.connect_client(CLIENT)
        return ok

    # ------------------------------------------------------------------ étape 7 : coupure par le poste

    async def stage_rig_unkey(self) -> bool:
        """Le poste repasse en réception de lui-même : la relecture du PTT (pas une valeur en cache) doit le voir."""
        name = "Coupure par le poste (" + ("spectre activé, async=1" if self.cfg.spectrum.enabled else "spectre désactivé") + ")"
        if not await self.confirm_emission("Étape 7 : coupure faite SUR LE POSTE (porteuse sans audio)"):
            return self.record(name, None, "non confirmé : ignoré")
        self.say("  Quand « COUPE MAINTENANT » s'affiche, appuie sur la touche TRANSMIT du poste pour repasser en réception.")
        self.say(f"  La station doit s'en apercevoir seule (relecture toutes les {self.ctrl.limits.rig_poll_s:g} s). "
                 f"Sinon, le TOT de l'essai coupe au bout de {self.tot_s:g} s.")
        await self.prompt("  Prêt ? Entrée pour commencer : ")                      # question posée AVANT la prise d'émission
        try:
            await self.key()
        except Refused as exc:
            await self.ctrl.force_rx("hwtest")
            return self.record(name, False, f"prise d'émission refusée : {exc}")
        self.say("  >>> COUPE MAINTENANT sur le poste (touche TRANSMIT) <<<")
        t0 = time.monotonic()
        deadline = t0 + self.tot_s + 3.0
        while self.ctrl.snapshot().state != "RX" and time.monotonic() < deadline:
            self.ctrl.heartbeat(CLIENT)                                               # seul le poste doit provoquer la coupure
            await asyncio.sleep(0.05)
        elapsed = time.monotonic() - t0
        snap = self.ctrl.snapshot()
        if snap.state != "RX":
            await self.ctrl.force_rx("hwtest")
            return self.record(name, False, "L'ÉMISSION N'A PAS ÉTÉ COUPÉE dans le délai : voir le superviseur")
        reason = snap.last_cut_reason
        if reason == "rig_reported_rx":
            return self.record(name, True, f"vue en {elapsed:.1f} s après le signal (ton temps de réaction compris)")
        if reason == "tot":
            return self.record(name, False, "PAS VUE : le TOT de l'essai a coupé. Si tu as bien appuyé sur TRANSMIT, la "
                                            "relecture du PTT renvoie un état ancien : NE PAS activer le spectre")
        return self.record(name, False, f"coupée par « {reason} » au lieu d'être vue comme une coupure du poste "
                                        "(fréquence ou mode touchés ?) : recommence")

    # ------------------------------------------------------------------ déroulement

    async def run(self) -> list[StageResult]:
        if self.rx_only:
            self.say(RX_ONLY_NOTICE)
        else:
            self.say(PREFLIGHT)
            if (await asyncio.to_thread(self.ask, "Tape OUI pour confirmer ces 6 points : ")).strip().upper() != "OUI":
                self.say("Essai annulé.")
                return []
        try:
            if not await self.setup():
                return self.results
            if not await self.stage_cat():
                self.say("\nLiaison CAT impossible : on s'arrête ici (aucune émission n'a été tentée).")
                return self.results
            if not self.only_rig_unkey:
                await self.stage_rx_audio()
                await self.stage_tuning()
                await self.stage_filters()
                await self.stage_scope_screen()
            if self.rx_only:
                return self.results
            await self.stage_band()
            await self.stage_tx_mode()
            if self.cfg.safety.enforce_bands and not self.cfg.bands:
                self.record("PTT / Audio TX / Pannes", None, "aucune bande autorisée dans station.toml : émission impossible")
            elif self.cfg.safety.enforce_bands and not self.cfg.tx_allowed(self.link.state.frequency_hz or 0):
                self.record("PTT / Audio TX / Pannes", False,
                            f"{self.link.state.frequency_hz} Hz hors des bandes autorisées : accorde le poste dans une bande autorisée")
            elif self.only_rig_unkey:
                await self.stage_rig_unkey()
            else:
                if await self.stage_ptt():
                    if await self.stage_tx_audio():
                        await self.stage_drills()
                    else:                                    # ROS élevé, audio non transmis... : plus aucune émission
                        self.record("Pannes", None, "ignoré : l'étape audio TX a échoué, on n'émet plus")
        finally:
            await self._restore_mode()
            await self.teardown()
            self.say("")
            self.say("Retour en réception demandé au poste.")
        return self.results

    def report(self) -> int:
        self.say("\n================  BILAN  ================")
        for r in self.results:
            self.say(f"  {'OK    ' if r.ok else 'IGNORÉ' if r.ok is None else 'ÉCHEC '}  {r.name}")
        failed = [r for r in self.results if r.ok is False]
        self.say("\n" + ("Tout ce qui a été essayé fonctionne." if not failed else
                         f"{len(failed)} étape(s) en échec : copie ce bilan pour le diagnostic."))
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
            hw.say("rigctld ne répond pas sur "
                   f"{cfg.network.rigctld_host}:{cfg.network.rigctld_port} : lance-le (trx-rigctld) ou retire --no-spawn.")
            return 3
        try:
            hw.say("Démarrage de rigctld...")
            hw.say("  (PTT par RTS/DTR : ouvrir le port peut déclencher une émission brève : charge fictive branchée)"
                   if cfg.rig.ptt_type in ("RTS", "DTR") else "")
            proc = subprocess.Popen(rigctld_command(cfg))
        except FileNotFoundError as exc:
            hw.say(str(exc))
            return 3
        for _ in range(50):
            if _port_open(cfg) or proc.poll() is not None:
                break
            await asyncio.sleep(0.1)
        if not _port_open(cfg):
            hw.say("rigctld n'a pas démarré (modèle, port COM ou débit incorrects ? poste éteint ?).")
            return 3
    else:
        hw.say("rigctld déjà actif : utilisé tel quel.")
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
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Configuration illisible ({args.config}) : {exc}. Indique-la avec --config station.toml.", file=sys.stderr)
        return 2
    levels = tuple(args.tx_levels)
    if any(v > -12 for v in levels):
        print("Refusé : un niveau d'essai supérieur à -12 dBFS n'est pas autorisé (risque de saturation).", file=sys.stderr)
        return 2
    if not 2.0 <= args.tot <= 60.0:
        print("--tot doit être compris entre 2 et 60 secondes.", file=sys.stderr)
        return 2
    try:
        hw = HwTest(cfg, tot_s=args.tot, tx_levels_db=levels, only_rig_unkey=args.coupure_poste,
                    rx_only=args.reception_seule)
    except ValueError as exc:
        print(f"--tot : {exc}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run_hwtest(cfg, hw, spawn=not args.no_spawn))
    except KeyboardInterrupt:
        print("\nInterrompu : l'émission a été coupée.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
