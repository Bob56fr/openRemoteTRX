# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Essai « deux ports CI-V » d'un Icom : rigctld sur le port A, spectre lu directement sur le port B.

    python -m trxstation.devtools.civ_dual --port-b COM7 --duree 30
    python -m trxstation.devtools.civ_dual --config station.toml --port-b COM7 --adresse B6

Question posée : le poste peut-il servir le CAT à rigctld (port A de station.toml, SANS async, réglages de la
station inchangés) et en même temps les données du spectre sur son second port (« Serial Port B » réglé en
CI-V), sans que l'un gêne l'autre ? Si oui, plus besoin d'async ni de relais : rigctld reste seul maître du
port A et la passerelle lirait le spectre sur le port B. La station doit être ARRÊTÉE.

Ce que l'outil mesure :
  - ouverture du port B sans effet sur le PTT (relu par rigctld juste avant et juste après) ;
  - adresse CI-V et fréquence vues sur le port B, comparées à celles de rigctld ;
  - balayages du spectre reçus sur le port B (cadence, format) ;
  - lectures f et t par rigctld PENDANT le flux (latence, échecs, valeurs du PTT) ;
  - bus partagé ou non : l'outil parle en E1h sur le port B (rigctld parle en E0h), donc toute trame E0h vue
    sur B vient du trafic de rigctld ; trames 27 00 vues par rigctld relevées dans son journal (-vvvv).

Sécurité : AUCUNE émission possible. Port B : liste fermée de civ_scope (19 00, 03, 27 10, 27 11 ; jamais
1C), RTS et DTR à zéro AVANT l'ouverture, confirmation préalable des réglages USB SEND / USB Keying du poste
(une ligne RTS/DTR du port B affectée à l'émission déclencherait le PTT). rigctld : liste fermée de
hamlib_scope ; seul « T 0 » (COUPURE) peut partir, et seulement si le PTT est relu actif ou illisible.
PTT relu actif à n'importe quel moment = port B fermé, « T 0 », essai arrêté (code 4).
rigctld muet 3 fois de suite = essai arrêté (on n'a plus de moyen de couper). Réglages du spectre relus au
départ et remis à la fin, même après Ctrl+C.

Résultats dans deux-ports-<date>/ : resume.txt, trames-port-b.txt, balayages.jsonl, rapport.html, rigctld.log.
"""
from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import civ_scope
from .civ_scope import CONTROLLER, ScopeProbe, bcd_le, open_serial, station_running
from ..answers import typed
from ..spectrum.probe import USB_SEND_WARNING
from .hamlib_scope import RIGCTLD_PORT, RigctlLink, first_value, rigctld_probe_command, wait_port

SECOND_CONTROLLER = 0xE1
MAX_SILENT = 3                        # lectures rigctld sans réponse d'affilée avant d'arrêter l'essai
# Journal de rigctld -vvvv (Hamlib 4.7.2) : pas d'octets, seulement les fonctions appelées. Une trame non demandée
# reçue sur le port A passe par icom_process_async_frame ; si c'est le spectre, une fonction « spectrum »/« scope »
# suit. Indicatif (noms internes de Hamlib).
LOG_ASYNC = re.compile(r"icom_process_async_frame entered")
LOG_SCOPE = re.compile(r"spectrum|scope", re.IGNORECASE)
LOG_TROUBLE = re.compile(r"unknown async|read again|!= buf|timed out|WaitForMultipleObjects", re.IGNORECASE)

MENU_CHECK = USB_SEND_WARNING


class TransmitDetected(RuntimeError):
    """PTT relu actif alors que l'outil n'émet jamais : arrêt immédiat."""


class RigctldLost(RuntimeError):
    """rigctld ne répond plus : plus aucun moyen de couper, l'essai s'arrête."""


class DualProbe:
    """Surveille rigctld (port A) pendant que ScopeProbe lit le spectre sur le port B."""

    def __init__(self, link, *, say: Callable[[str], None] = print, clock: Callable[[], float] = time.perf_counter,
                 period_s: float = 0.5):
        self.link, self.say, self.clock, self.period_s = link, say, clock, period_s
        self.latency_ms: dict[str, list[float]] = {"f": [], "t": []}
        self.failures: Counter[str] = Counter()
        self.ptt_values: Counter[str] = Counter()
        self.freqs: Counter[int] = Counter()
        self.silent = 0
        self.next_query = 0.0
        self.notes: list[str] = []
        self.unkeys: list[str] = []

    def _timed(self, cmd: str) -> tuple[int | None, dict[str, str]] | None:
        start = self.clock()
        try:
            code, values = self.link.command(cmd)
        except (OSError, ConnectionError) as exc:
            self.failures[cmd] += 1
            self.silent += 1
            if self.silent >= MAX_SILENT:
                raise RigctldLost(f"rigctld ne répond plus ({type(exc).__name__} : {exc})") from exc
            return None
        self.silent = 0
        if code == 0:
            self.latency_ms[cmd].append((self.clock() - start) * 1000)
        else:
            self.failures[cmd] += 1
        return code, values

    def read_ptt(self) -> str | None:
        """Valeur du PTT relue par rigctld (« 0 », « 1 »...), None si illisible. Actif = TransmitDetected."""
        reply = self._timed("t")
        if reply is None or reply[0] != 0:
            return None
        value = first_value(reply[1]) or "?"
        self.ptt_values[value] += 1
        if value != "0":
            raise TransmitDetected(f"PTT relu à {value!r} par rigctld")
        return value

    def read_freq(self) -> int | None:
        reply = self._timed("f")
        if reply is None or reply[0] != 0:
            return None
        try:
            hz = int(float(first_value(reply[1]) or ""))
        except ValueError:
            return None
        self.freqs[hz] += 1
        return hz

    def tick(self) -> None:
        now = self.clock()
        if now < self.next_query:
            return
        self.next_query = now + self.period_s
        self.read_freq()
        self.read_ptt()

    def unkey(self, why: str) -> None:
        """Ordre de COUPURE (jamais d'émission) ; résultat noté, jamais d'exception."""
        try:
            code, _ = self.link.command("T 0")
            self.unkeys.append(f"T 0 ({why}) : RPRT {code}")
        except Exception as exc:   # noqa: BLE001 - la coupure est tentée quoi qu'il arrive
            self.unkeys.append(f"T 0 ({why}) : {type(exc).__name__} {exc}")

    def summary(self) -> list[str]:
        lines = []
        for cmd, label in (("f", "fréquence"), ("t", "PTT")):
            values = sorted(self.latency_ms[cmd])
            if values:
                lines.append(f"rigctld (port A), lecture {label} pendant le flux : {len(values)} réponses, "
                             f"min {values[0]:.0f} ms, médiane {statistics.median(values):.0f} ms, "
                             f"max {values[-1]:.0f} ms ; échecs {self.failures[cmd]}")
            else:
                lines.append(f"rigctld (port A), lecture {label} : aucune réponse (échecs {self.failures[cmd]})")
        lines.append("Valeurs du PTT relues : " + (", ".join(f"{k} ({n})" for k, n in self.ptt_values.items()) or "—"))
        lines.append("Fréquences relues par rigctld : "
                     + (", ".join(f"{k} Hz ({n})" for k, n in self.freqs.most_common(5)) or "—"))
        return lines + self.unkeys + self.notes


def read_freq_b(probe: ScopeProbe) -> int | None:
    reply = probe.request(0x03)
    if reply is None or reply.payload[:1] != b"\x03" or len(reply.payload) < 6:
        return None
    return bcd_le(reply.payload[1:6])


def detect_b(probe: ScopeProbe, say: Callable[[str], None]) -> bool:
    """Adresse du poste sur le port B en E1h ; si le poste ne répond pas à E1h, nouvel essai en E0h."""
    if probe.detect((0x94, 0xA4, 0xB6)):
        return True
    if probe.controller != CONTROLLER:
        say(f"Pas de réponse en tant que {probe.controller:02X}h : nouvel essai en E0h (même adresse que rigctld).")
        probe.notes.append(f"le poste n'a pas répondu au contrôleur {probe.controller:02X}h sur le port B ; essai en E0h")
        probe.controller = CONTROLLER
        return probe.detect((0x94, 0xA4, 0xB6))
    return False


def scan_log(path: Path) -> tuple[int, int, int, list[str]]:
    """(trames non demandées reçues par rigctld, lignes « spectre », lignes d'anomalie, premières anomalies)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0, 0, []
    lines = text.splitlines()
    trouble = [line.strip() for line in lines if LOG_TROUBLE.search(line)]
    scope = sum(1 for line in lines if LOG_SCOPE.search(line))
    return len(LOG_ASYNC.findall(text)), scope, len(trouble), trouble[:5]


def verdict(probe: ScopeProbe, dual: DualProbe, *, tx_seen: bool, lost: bool, freq_match: bool | None,
            log_scope: int) -> tuple[bool, list[str]]:
    ok = True
    lines = []
    if tx_seen:
        ok = False
        lines.append("ÉCHEC : PTT relu ACTIF. Le port B ou ses lignes RTS/DTR déclenchent l'émission : "
                     "revoir USB SEND / USB Keying avant tout nouvel essai.")
    if lost:
        ok = False
        lines.append("ÉCHEC : rigctld a cessé de répondre pendant le flux du spectre sur le port B.")
    if not probe.scope.complete:
        ok = False
        lines.append("ÉCHEC : aucun balayage complet reçu sur le port B.")
    else:
        lines.append(f"OK : spectre reçu sur le port B ({probe.scope.complete} balayages).")
    failures = dual.failures["f"] + dual.failures["t"]
    if failures:
        ok = False
        lines.append(f"ÉCHEC : {failures} lecture(s) rigctld en échec pendant le flux.")
    elif dual.latency_ms["t"]:
        lines.append("OK : rigctld a répondu à toutes les lectures pendant le flux.")
    if freq_match is False:
        ok = False
        lines.append("ÉCHEC : fréquence différente entre le port B et rigctld (bouton tourné pendant l'essai ?).")
    shared = probe.counts["commandes d'un autre contrôleur"] + probe.counts["réponses pour un autre contrôleur"]
    lines.append(f"Bus : {shared} trame(s) du trafic de rigctld vues sur le port B ; {log_scope} ligne(s) « spectre » "
                 "dans le journal de rigctld"
                 + (" => rigctld reçoit aussi le spectre sur le port A (à traiter)." if log_scope else "."))
    return ok, lines


def save(folder: Path, probe: ScopeProbe, summary: str) -> None:
    civ_scope.save(folder, probe, summary)
    (folder / "trames.txt").replace(folder / "trames-port-b.txt")


def main(argv: list[str] | None = None) -> int:
    from .. import config as cfgmod
    from ..qualif.main import find_config

    ap = argparse.ArgumentParser(prog="civ_dual",
                                 description="Essai rigctld sur le port A + spectre CI-V sur le port B (sans émission)")
    ap.add_argument("--port-b", required=True, help="second port série du poste, réglé en CI-V (ex. COM7)")
    ap.add_argument("--config", type=Path, default=None, help="station.toml (défaut : emplacement standard, sinon ./station.toml)")
    ap.add_argument("--baud-b", type=int, default=115200, help="débit du port B (défaut 115200)")
    ap.add_argument("--adresse", default=None, help="adresse CI-V du poste en hexadécimal (ex. B6) ; défaut : recherche")
    ap.add_argument("--duree", type=float, default=30.0, help="durée du relevé en secondes (défaut 30)")
    ap.add_argument("--sortie", type=Path, default=None, help="dossier des résultats (défaut deux-ports-<date>)")
    ap.add_argument("--reglages-verifies", action="store_true",
                    help="USB SEND / USB Keying déjà vérifiés (pas de question avant l'ouverture du port B)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if not 5 <= args.duree <= 300:
        print("--duree : de 5 à 300 secondes.", file=sys.stderr)
        return 2
    try:
        address = int(args.adresse, 16) if args.adresse else None
        if address is not None and not 0x01 <= address <= 0xDF:
            raise ValueError
    except ValueError:
        print("--adresse : un nombre hexadécimal de 01 à DF est attendu (ex. B6).", file=sys.stderr)
        return 2
    busy = station_running(ports=(4532, 47321, RIGCTLD_PORT))
    if busy is not None:
        print(f"Port {busy} déjà en écoute (station ou autre rigctld) : arrête-la d'abord.", file=sys.stderr)
        return 3
    path = args.config or find_config()
    try:
        cfg = cfgmod.load(path)
    except (cfgmod.ConfigError, OSError) as exc:
        print(f"Configuration {path} inutilisable : {exc}", file=sys.stderr)
        return 2
    if cfg.rig.port and cfg.rig.port.strip().lower() == args.port_b.strip().lower():
        print(f"--port-b {args.port_b} est le port CAT de station.toml : il faut le SECOND port du poste.", file=sys.stderr)
        return 2
    if cfg.rig.ptt_port and cfg.rig.ptt_port.strip().lower() == args.port_b.strip().lower():
        print(f"--port-b {args.port_b} est le port PTT de station.toml : refusé.", file=sys.stderr)
        return 2
    print(MENU_CHECK)
    if not args.reglages_verifies:
        try:
            answer = input("Tape OUI si ces réglages sont vérifiés : ")
        except EOFError:
            answer = ""
        if not typed(answer, "OUI"):
            print(f"Réponse {answer.strip()!r} : essai annulé, le port B n'a PAS été ouvert (rien n'a été tenté). "
                  "Relance et tape OUI, ou ajoute --reglages-verifies.")
            return 2
    try:
        command = rigctld_probe_command(cfg, "127.0.0.1", use_async=False, verbose="-vvvv")
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    folder = args.sortie or Path(f"deux-ports-{datetime.now():%Y%m%d-%H%M%S}")
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder / "rigctld.log"
    print("rigctld d'essai (port A, SANS async) : " + " ".join(command[1:]))
    tx_seen = lost = False
    freq_match: bool | None = None
    probe: ScopeProbe | None = None
    dual: DualProbe | None = None
    ser = None
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        link = None
        try:
            if not wait_port(RIGCTLD_PORT, proc):
                print(f"rigctld ne démarre pas (voir {log_path}).", file=sys.stderr)
                return 1
            link = RigctlLink("127.0.0.1", RIGCTLD_PORT)
            dual = DualProbe(link)
            if dual.read_ptt() is None:                         # sans relecture du PTT, on n'ouvre pas le port B
                print("PTT illisible par rigctld avant l'ouverture du port B : essai arrêté.", file=sys.stderr)
                dual.unkey("PTT illisible au départ")
                return 1
            freq_a = dual.read_freq()
            print(f"rigctld : PTT 0, fréquence {freq_a} Hz. Ouverture de {args.port_b} (RTS et DTR à zéro)...")
            try:
                ser = open_serial(args.port_b, args.baud_b)
            except ImportError:
                print("Module pyserial absent : pip install pyserial", file=sys.stderr)
                return 1
            except OSError as exc:
                print(f"Ouverture de {args.port_b} impossible : {exc}", file=sys.stderr)
                return 1
            for _ in range(3):                                  # l'ouverture a-t-elle touché au PTT ?
                time.sleep(0.3)
                dual.read_ptt()
            print(f"{args.port_b} ouvert, PTT toujours 0.")
            probe = ScopeProbe(ser, address=address, controller=SECOND_CONTROLLER)
            if detect_b(probe, print):
                freq_b = read_freq_b(probe)
                freq_a = dual.read_freq()
                freq_match = None if freq_a is None or freq_b is None else freq_a == freq_b
                print(f"Fréquence : port B {freq_b} Hz, rigctld {freq_a} Hz.")
                probe.notes.append(f"fréquence au départ : port B {freq_b} Hz, rigctld {freq_a} Hz")
                print(f"Relevé pendant {args.duree:g} s, rigctld interrogé toutes les 0,5 s (Ctrl+C pour arrêter)...")
                try:
                    probe.run(args.duree, tick=dual.tick)
                except KeyboardInterrupt:
                    print("\nInterrompu : réglages du spectre remis en état.")
                end_b, end_a = read_freq_b(probe), dual.read_freq()
                probe.notes.append(f"fréquence à la fin : port B {end_b} Hz, rigctld {end_a} Hz")
                if freq_match is not False and end_a is not None and end_b is not None:
                    freq_match = end_a == end_b
            ser.close()
            ser = None
            time.sleep(0.5)
            dual.read_ptt()                                     # la fermeture du port B a-t-elle touché au PTT ?
        except TransmitDetected as exc:
            tx_seen = True
            if ser is not None:
                ser.close()
                ser = None
            if dual is not None:
                dual.unkey("PTT relu actif")
                dual.notes.append(f"ARRÊT : {exc}")
            print(f"\nARRÊT : {exc}. Port B fermé, coupure « T 0 » envoyée. Vérifie le poste.", file=sys.stderr)
        except RigctldLost as exc:
            lost = True
            if dual is not None:
                dual.notes.append(f"ARRÊT : {exc}")
            print(f"\nARRÊT : {exc} (voir {log_path}).", file=sys.stderr)
        finally:
            if ser is not None:
                ser.close()
            if link is not None:
                link.close()
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    if probe is None or dual is None:
        return 4 if tx_seen else 1
    log_async, log_scope, log_trouble, trouble = scan_log(log_path)
    ok, verdict_lines = verdict(probe, dual, tx_seen=tx_seen, lost=lost, freq_match=freq_match, log_scope=log_scope)
    seen_cmds = probe.counts["commandes d'un autre contrôleur"]
    seen_replies = probe.counts["réponses pour un autre contrôleur"]
    summary = "\n".join([f"Port A : {cfg.rig.port} (rigctld, modèle {cfg.rig.model}, SANS async) ; port B : "
                         f"{args.port_b} {args.baud_b} bauds, contrôleur {probe.controller:02X}h",
                         *verdict_lines, "",
                         "--- Port B ---", probe.summary(args.port_b, args.baud_b),
                         f"Trames du trafic de rigctld vues sur B : commandes {seen_cmds}, réponses {seen_replies}",
                         "", "--- rigctld ---", *dual.summary(),
                         f"Journal de rigctld : {log_async} trame(s) non demandée(s) reçue(s) (changements de fréquence…), "
                         f"{log_scope} ligne(s) « spectre », {log_trouble} ligne(s) d'anomalie (indicatif)",
                         *trouble])
    save(folder, probe, summary)
    print("\n" + summary + f"\n\nRésultats : {folder.resolve()} (rapport.html, trames-port-b.txt, rigctld.log).")
    if tx_seen:
        return 4
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
