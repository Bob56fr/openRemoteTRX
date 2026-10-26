"""Relevé du spectre HF d'un poste Icom par le port CI-V, SANS rigctld (outil d'essai autonome) :

    python -m trxstation.devtools.civ_scope --port COM8 --duree 15
    python -m trxstation.devtools.civ_scope --port COM8 --adresse B6     (adresse CI-V lue dans le menu du poste)

But : savoir si l'on sait déjà recevoir les données du spectre (commande CI-V 27 00) avant d'écrire quoi que
ce soit dans la station. La station (rigctld, superviseur) doit être ARRÊTÉE : le port n'a qu'un seul maître.

Sécurité : AUCUNE émission possible. Seules les commandes de la liste fermée ALLOWED partent vers le poste
(identification, lecture de la fréquence, marche/arrêt de l'affichage du spectre et de sa sortie CI-V) ;
la commande d'émission 1C n'y est pas et `encode_request` refuse tout le reste. RTS et DTR sont forcés à
zéro AVANT l'ouverture du port (une ligne réglée en « USB SEND » sur le poste déclencherait l'émission).
Les deux réglages du spectre touchés sont relus au départ et remis tels quels à la fin, même après Ctrl+C.

Résultats dans spectre-<date>/ : resume.txt (bilan), trames.txt (trames brutes horodatées), balayages.jsonl
(un balayage décodé par ligne), rapport.html (waterfall à ouvrir dans un navigateur).
Le format des trames 27 00 est décodé de façon tolérante (avec ou sans octet de choix du spectre) : le bilan
dit lequel a été vu. C'est justement ce que l'essai doit établir sur le vrai poste.
"""
from __future__ import annotations

import argparse
import json
import socket
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ..spectrum.civ import (  # noqa: F401 - réexportés (outils d'essai et tests)
    PREAMBLE, END, OK, NG, COLLISION, CONTROLLER, CONTROLLERS,
    BROADCAST, MAX_FRAME, LEVEL_MAX, ALLOWED,
    CivRefused, encode_request, Frame, FrameReader, is_bcd, bcd_byte, bcd_le,
    Sweep, ScopeAssembler, ascii_line)

# ------------------------------------------------------------------ rapport

HTML = """<!doctype html><html lang="fr"><meta charset="utf-8"><title>Relevé du spectre HF</title>
<style>body{{background:#0b1220;color:#dbe4f0;font:14px system-ui,sans-serif;margin:16px}}canvas{{width:100%;image-rendering:pixelated;border:1px solid #2a3a55}}pre{{white-space:pre-wrap}}</style>
<h1>Relevé du spectre HF</h1><pre>{summary}</pre><canvas id="wf"></canvas>
<script>
const sweeps = {data};
const c = document.getElementById("wf"), w = Math.max(1, ...sweeps.map((s) => s.points.length)), h = sweeps.length;
c.width = w; c.height = Math.max(1, h);
const ctx = c.getContext("2d"), img = ctx.createImageData(c.width, c.height);
sweeps.forEach((s, y) => s.points.forEach((v, x) => {{
  const f = Math.min(1, v / {level_max}), i = (y * c.width + x) * 4;
  img.data[i] = Math.round(255 * Math.max(0, f - 0.6) / 0.4); img.data[i + 1] = Math.round(255 * Math.min(1, f * 1.4));
  img.data[i + 2] = Math.round(120 + 135 * f); img.data[i + 3] = 255;
}}));
ctx.putImageData(img, 0, 0);
</script></html>
"""


def write_html(path: Path, summary: str, sweeps: list[Sweep], limit: int = 600) -> None:
    data = json.dumps([{"points": s.points} for s in sweeps[-limit:]])
    safe = summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    path.write_text(HTML.format(summary=safe, data=data, level_max=LEVEL_MAX), encoding="utf-8")


# ------------------------------------------------------------------ relevé

def station_running(host: str = "127.0.0.1", ports: tuple[int, ...] = (4532, 47321)) -> int | None:
    """Port de rigctld ou du superviseur en écoute : la station tourne (renvoie le port), sinon None."""
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return port
        except OSError:
            continue
    return None


def open_serial(port: str, baud: int):
    """Ouvre le port avec RTS et DTR à zéro AVANT l'ouverture (pyserial les applique à l'ouverture)."""
    import serial
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, baud, 0.02
    ser.rts, ser.dtr = False, False
    ser.open()
    return ser


class ScopeProbe:
    def __init__(self, ser, *, address: int | None, say: Callable[[str], None] = print,
                 clock: Callable[[], float] = time.perf_counter, controller: int = CONTROLLER):
        self.ser, self.address, self.say, self.clock = ser, address, say, clock
        self.controller = controller
        self.reader, self.scope = FrameReader(), ScopeAssembler()
        self.t0 = clock()
        self.raw: list[str] = []
        self.sweeps: list[Sweep] = []
        self.cat_ms: list[float] = []
        self.counts: Counter[str] = Counter()
        self.notes: list[str] = []
        self.echo = 0

    # -- envoi et réception

    def _send(self, to: int, cmd: int, sub: int | None = None, data: bytes | None = None) -> None:
        frame = encode_request(to, cmd, sub, data, frm=self.controller)
        self.ser.write(frame)
        self._log("->", frame)

    def _log(self, direction: str, raw: bytes) -> None:
        if len(self.raw) < 5000:
            self.raw.append(f"{self.clock() - self.t0:9.3f} {direction} {raw.hex(' ').upper()}")

    def _frames(self) -> Iterator[Frame]:
        chunk = self.ser.read(self.ser.in_waiting or 1)
        if not chunk:
            return
        for frame in self.reader.feed(chunk):
            if frame.frm == self.controller:                   # écho de nos propres trames (réglage « CI-V USB Echo Back »)
                self.echo += 1
                continue
            if frame.frm in CONTROLLERS:                       # commande d'un AUTRE contrôleur (bus CI-V partagé)
                self.counts["commandes d'un autre contrôleur"] += 1
                self._log("<-", bytes([PREAMBLE, PREAMBLE, frame.to, frame.frm]) + frame.payload + bytes([END]))
                continue
            if frame.to in CONTROLLERS and frame.to != self.controller:
                self.counts["réponses pour un autre contrôleur"] += 1
                self._log("<-", bytes([PREAMBLE, PREAMBLE, frame.to, frame.frm]) + frame.payload + bytes([END]))
                continue
            self._log("<-", bytes([PREAMBLE, PREAMBLE, frame.to, frame.frm]) + frame.payload + bytes([END]))
            if frame.payload[:2] == b"\x27\x00":
                self.counts["spectre"] += 1
                sweep = self.scope.feed(frame.payload[2:], self.clock() - self.t0)
                if sweep is not None:
                    self.sweeps.append(sweep)
                continue
            yield frame

    def request(self, cmd: int, sub: int | None = None, data: bytes | None = None, *, to: int | None = None,
                timeout: float = 1.0) -> Frame | None:
        """Envoie une commande permise ; renvoie la réponse (FB, FA ou données), None sans réponse."""
        target = self.address if to is None else to
        self._send(target, cmd, sub, data)
        prefix = bytes([cmd]) + (bytes([sub]) if sub is not None else b"")
        end = self.clock() + timeout
        while self.clock() < end:
            for frame in self._frames():
                if frame.to not in (self.controller, BROADCAST):
                    continue
                if frame.payload[:1] in (bytes([OK]), bytes([NG])) or frame.payload.startswith(prefix):
                    if self.address is None:
                        self.address = frame.frm
                    return frame
        return None

    # -- déroulé

    def detect(self, candidates: tuple[int, ...]) -> bool:
        if self.address is not None:
            reply = self.request(0x19, 0x00)
            if reply is None:
                self.say(f"Pas de réponse à l'adresse {self.address:02X}h : vérifie l'adresse CI-V et le débit.")
                return False
            self.say(f"Poste trouvé à l'adresse {self.address:02X}h.")
            return True
        for to in (BROADCAST, *candidates):
            reply = self.request(0x19, 0x00, to=to, timeout=0.6)
            if reply is not None and reply.payload[:2] == b"\x19\x00":
                self.address = reply.payload[2] if len(reply.payload) > 2 else reply.frm
                self.say(f"Poste trouvé à l'adresse {self.address:02X}h (demande envoyée à {to:02X}h).")
                return True
        self.say("Aucun poste n'a répondu. Indique --adresse (MENU > SET > Connecteurs > CI-V > Adresse CI-V) "
                 "et vérifie que le port est celui du CI-V (« Serial Port A (CI-V) »).")
        return False

    def read_setting(self, sub: int) -> int | None:
        reply = self.request(0x27, sub)
        if reply is None or reply.payload[:2] != bytes([0x27, sub]) or len(reply.payload) < 3:
            return None
        return reply.payload[-1]

    def set_setting(self, sub: int, value: int) -> bool:
        reply = self.request(0x27, sub, bytes([value]))
        return reply is not None and reply.payload[:1] == bytes([OK])

    def run(self, duration_s: float, *, show: bool = True, tick: Callable[[], None] | None = None) -> None:
        """`tick` : appelé à chaque tour de boucle (essai à deux ports) ; une exception arrête le relevé, réglages remis."""
        before = {sub: self.read_setting(sub) for sub in (0x10, 0x11)}
        self.notes.append(f"état de départ : affichage du spectre {before[0x10]}, sortie CI-V {before[0x11]} (None = illisible)")
        changed: list[tuple[int, int]] = []
        try:
            for sub, label in ((0x10, "affichage du spectre"), (0x11, "sortie des données sur le CI-V")):
                if before[sub] != 1:
                    if self.set_setting(sub, 1):
                        changed.append((sub, before[sub] if before[sub] is not None else 0))
                        self.say(f"{label} : activé pour l'essai (sera remis à la fin).")
                    else:
                        self.say(f"{label} : le poste a REFUSÉ l'activation (FA ou pas de réponse).")
                        self.notes.append(f"activation refusée : 27 {sub:02X} 01")
            end = self.clock() + duration_s
            next_cat = next_show = self.clock()
            while self.clock() < end:
                now = self.clock()
                if now >= next_cat:                               # la liaison reste-t-elle réactive sous le flux du spectre ?
                    next_cat = now + 0.5
                    start = self.clock()
                    reply = self.request(0x03, timeout=1.0)
                    if reply is not None and reply.payload[:1] == b"\x03":
                        self.cat_ms.append((self.clock() - start) * 1000)
                    else:
                        self.counts["fréquence sans réponse"] += 1
                for _ in self._frames():
                    self.counts["autres trames"] += 1
                if tick is not None:
                    tick()
                if show and now >= next_show:
                    next_show = now + 1.0
                    self.say(self.status_line())
        finally:
            for sub, value in reversed(changed):                 # toujours remis, même après Ctrl+C ; chacun indépendamment
                try:
                    restored = self.set_setting(sub, value)
                except (Exception, KeyboardInterrupt):           # un second Ctrl+C ne doit pas empêcher l'autre remise
                    restored = False
                if not restored:
                    self.say(f"ATTENTION : réglage 27 {sub:02X} non remis à {value} : vérifie le menu du spectre du poste.")
                    self.notes.append(f"remise en état NON confirmée : 27 {sub:02X} {value:02X}")

    def status_line(self) -> str:
        elapsed = max(1e-6, self.clock() - self.t0)
        last = self.sweeps[-1] if self.sweeps else None
        head = f"{elapsed:5.1f} s  balayages {len(self.sweeps):4d} ({len(self.sweeps) / elapsed:4.1f}/s)"
        if last is None:
            return head + f"  trames du spectre {self.counts['spectre']}"
        return head + f"  {len(last.points)} points  |{ascii_line(last.points)}|"

    def summary(self, port: str, baud: int) -> str:
        elapsed = max(1e-6, self.clock() - self.t0)
        lines = [f"Port {port}, {baud} bauds, adresse du poste {self.address:02X}h" if self.address is not None
                 else f"Port {port}, {baud} bauds, poste non trouvé",
                 f"Durée {elapsed:.1f} s ; trames du spectre {self.counts['spectre']} ; balayages complets "
                 f"{self.scope.complete} ({self.scope.complete / elapsed:.1f}/s) ; incomplets {self.scope.incomplete} ; "
                 f"illisibles {self.scope.unreadable}",
                 "Format vu : " + (", ".join(f"{k} ({n})" for k, n in self.scope.layouts.most_common()) or "aucun"),
                 "Points par balayage : " + (", ".join(f"{k} ({n})" for k, n in self.scope.lengths.most_common()) or "—")]
        last = self.sweeps[-1] if self.sweeps else None
        if last is not None:
            lines.append(f"Dernier balayage : mode {last.mode}, valeur 1 {last.f1_hz} Hz, valeur 2 {last.f2_hz} Hz, "
                         f"hors plage {last.out_of_range}, niveaux {min(last.points, default=0)}..{max(last.points, default=0)}")
        if self.cat_ms:
            ordered = sorted(self.cat_ms)
            lines.append(f"Lecture de fréquence pendant le flux : {len(ordered)} réponses, min {ordered[0]:.0f} ms, "
                         f"médiane {statistics.median(ordered):.0f} ms, max {ordered[-1]:.0f} ms ; "
                         f"sans réponse {self.counts['fréquence sans réponse']}")
        lines.append(f"Octets ignorés {self.reader.dropped} ; échos de nos trames {self.echo} ; "
                     f"autres trames du poste {self.counts['autres trames']}")
        lines += self.notes
        return "\n".join(lines)


def save(folder: Path, probe: ScopeProbe, summary: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "resume.txt").write_text(summary + "\n", encoding="utf-8")
    (folder / "trames.txt").write_text("\n".join(probe.raw) + "\n", encoding="utf-8")
    with open(folder / "balayages.jsonl", "w", encoding="utf-8") as out:
        for sweep in probe.sweeps:
            out.write(json.dumps(asdict(sweep)) + "\n")
    write_html(folder / "rapport.html", summary, probe.sweeps)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="civ_scope", description="Relevé du spectre HF d'un Icom par le CI-V (lecture seule)")
    ap.add_argument("--port", required=True, help="port CI-V du poste, ex. COM8 ou /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200, help="débit (défaut 115200, celui conseillé pour le spectre)")
    ap.add_argument("--adresse", default=None, help="adresse CI-V du poste en hexadécimal (ex. 94) ; défaut : recherche")
    ap.add_argument("--duree", type=float, default=15.0, help="durée du relevé en secondes (défaut 15)")
    ap.add_argument("--sortie", type=Path, default=None, help="dossier des résultats (défaut spectre-<date>)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):                    # console Windows redirigée : jamais d'arrêt sur un caractère
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if not 1 <= args.duree <= 300:
        print("--duree : de 1 à 300 secondes.", file=sys.stderr)
        return 2
    try:
        address = int(args.adresse, 16) if args.adresse else None
        if address is not None and not 0x01 <= address <= 0xDF:
            raise ValueError
    except ValueError:
        print("--adresse : un nombre hexadécimal de 01 à DF est attendu (ex. 94).", file=sys.stderr)
        return 2
    busy = station_running()
    if busy is not None:
        print(f"La station tourne (port {busy} en écoute : rigctld ou superviseur). Arrête-la d'abord : "
              "le port du poste n'a qu'un seul maître.", file=sys.stderr)
        return 3
    try:
        ser = open_serial(args.port, args.baud)
    except ImportError:
        print("Module pyserial absent : pip install pyserial", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Ouverture de {args.port} impossible : {exc}", file=sys.stderr)
        return 1
    print(f"{args.port} ouvert ({args.baud} bauds), RTS et DTR à zéro. Aucune commande d'émission n'existe dans cet outil.")
    probe = ScopeProbe(ser, address=address)
    try:
        if probe.detect((0x94, 0xA4, 0xB6)):
            print(f"Relevé pendant {args.duree:g} s (Ctrl+C pour arrêter plus tôt)...")
            try:
                probe.run(args.duree)
            except KeyboardInterrupt:
                print("\nInterrompu : réglages du poste remis en état.")
    finally:
        ser.close()
    summary = probe.summary(args.port, args.baud)
    folder = args.sortie or Path(f"spectre-{datetime.now():%Y%m%d-%H%M%S}")
    save(folder, probe, summary)
    print("\n" + summary + f"\n\nRésultats : {folder.resolve()} (ouvre rapport.html dans un navigateur).")
    return 0 if probe.scope.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
