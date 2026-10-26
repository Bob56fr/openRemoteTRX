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
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

PREAMBLE, END, OK, NG, COLLISION = 0xFE, 0xFD, 0xFB, 0xFA, 0xFC
CONTROLLER = 0xE0                     # adresse CI-V habituelle d'un ordinateur
BROADCAST = 0x00
MAX_FRAME = 256
LEVEL_MAX = 160                       # niveau maximal d'un point du spectre (0xA0)

# Liste FERMÉE : (commande, sous-commande) -> valeurs de données permises (None = lecture sans donnée).
ALLOWED: dict[tuple[int, int | None], set[bytes | None]] = {
    (0x19, 0x00): {None},             # identification du poste (renvoie son adresse)
    (0x03, None): {None},             # lecture de la fréquence affichée
    (0x27, 0x10): {None, b"\x00", b"\x01"},   # affichage du spectre : lecture, arrêt, marche
    (0x27, 0x11): {None, b"\x00", b"\x01"},   # sortie des données du spectre sur le CI-V : lecture, arrêt, marche
}


class CivRefused(ValueError):
    """Commande hors de la liste fermée : jamais envoyée."""


# ------------------------------------------------------------------ trames

def encode_request(to: int, cmd: int, sub: int | None = None, data: bytes | None = None, *,
                   frm: int = CONTROLLER) -> bytes:
    if data is not None and len(data) == 0:
        data = None
    if (cmd, sub) not in ALLOWED or data not in ALLOWED[(cmd, sub)]:
        raise CivRefused(f"commande CI-V refusée : {cmd:02X}{'' if sub is None else f' {sub:02X}'}"
                         f"{'' if data is None else ' ' + data.hex(' ').upper()}")
    for value in (to, frm):
        if not 0 <= value <= 0xDF and value != CONTROLLER:
            raise CivRefused(f"adresse CI-V invalide : {value:02X}")
    body = bytes([to, frm, cmd]) + (bytes([sub]) if sub is not None else b"") + (data or b"")
    return bytes([PREAMBLE, PREAMBLE]) + body + bytes([END])


@dataclass(frozen=True)
class Frame:
    to: int
    frm: int
    payload: bytes                    # commande, sous-commande et données

    @property
    def cmd(self) -> int | None:
        return self.payload[0] if self.payload else None


class FrameReader:
    """Découpe le flux série en trames FE FE ... FD ; ignore le bruit, les collisions (FC) et les trames démesurées."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.dropped = 0

    def feed(self, chunk: bytes) -> Iterator[Frame]:
        self.buf += chunk
        while True:
            start = self.buf.find(bytes([PREAMBLE, PREAMBLE]))
            if start < 0:
                if self.buf[-1:] != bytes([PREAMBLE]):
                    self.dropped += len(self.buf)
                    self.buf.clear()
                else:
                    self.dropped += len(self.buf) - 1
                    del self.buf[:-1]
                return
            if start:
                self.dropped += start
                del self.buf[:start]
            while len(self.buf) > 2 and self.buf[2] == PREAMBLE:        # FE FE FE... : préambule plus long
                del self.buf[0]
            end = self.buf.find(bytes([END]), 2)
            restart = self.buf.find(bytes([PREAMBLE, PREAMBLE]), 2)
            if restart >= 0 and (end < 0 or restart < end):           # trame coupée : on se recale sur la suivante
                self.dropped += restart
                del self.buf[:restart]
                continue
            if end < 0:
                if len(self.buf) > MAX_FRAME:
                    self.dropped += len(self.buf)
                    self.buf.clear()
                return
            raw = bytes(self.buf[2:end])
            del self.buf[:end + 1]
            if len(raw) < 3 or COLLISION in raw or PREAMBLE in raw:
                self.dropped += len(raw) + 3
                continue
            yield Frame(raw[0], raw[1], raw[2:])


def is_bcd(byte: int) -> bool:
    return (byte >> 4) <= 9 and (byte & 0x0F) <= 9


def bcd_byte(byte: int) -> int:
    return (byte >> 4) * 10 + (byte & 0x0F)


def bcd_le(data: bytes) -> int | None:
    """Nombre BCD Icom, octet de poids faible en premier (fréquences) ; None si un chiffre est invalide."""
    if not all(is_bcd(b) for b in data):
        return None
    return sum(bcd_byte(b) * 100 ** i for i, b in enumerate(data))


# ------------------------------------------------------------------ assemblage des balayages (commande 27 00)

@dataclass
class Sweep:
    t: float                          # secondes depuis le début du relevé
    mode: int | None                  # 0 = centré, 1 = bornes fixes (selon le manuel CI-V)
    f1_hz: int | None                 # fréquence centrale (mode centré) ou borne basse
    f2_hz: int | None                 # largeur ou borne haute
    out_of_range: bool | None
    points: list[int] = field(default_factory=list)


class ScopeAssembler:
    """Recompose un balayage à partir de ses divisions (01..NN, numéros en BCD)."""

    def __init__(self) -> None:
        self.current: Sweep | None = None
        self.expected = 0
        self.complete = 0
        self.incomplete = 0
        self.unreadable = 0
        self.layouts: Counter[str] = Counter()     # « avec octet de choix » / « sans », nombre de divisions
        self.lengths: Counter[int] = Counter()

    def _split(self, data: bytes) -> tuple[int | None, int, int, bytes] | None:
        def valid(div: int, top: int) -> bool:
            return is_bcd(div) and is_bcd(top) and 1 <= bcd_byte(div) <= bcd_byte(top) <= 50
        if len(data) >= 3 and data[0] in (0, 1) and valid(data[1], data[2]):
            return data[0], bcd_byte(data[1]), bcd_byte(data[2]), data[3:]
        if len(data) >= 2 and valid(data[0], data[1]):
            return None, bcd_byte(data[0]), bcd_byte(data[1]), data[2:]
        return None

    def feed(self, data: bytes, t: float) -> Sweep | None:
        """`data` : octets qui suivent 27 00. Renvoie le balayage quand sa dernière division arrive."""
        parts = self._split(data)
        if parts is None:
            self.unreadable += 1
            return None
        selector, div, top, body = parts
        self.layouts[f"{'avec' if selector is not None else 'sans'} octet de choix, {top} division(s)"] += 1
        if div == 1:
            if self.current is not None:
                self.incomplete += 1
            header_ok = len(body) >= 12
            self.current = Sweep(t=t, mode=body[0] if header_ok else None,
                                 f1_hz=bcd_le(body[1:6]) if header_ok else None,
                                 f2_hz=bcd_le(body[6:11]) if header_ok else None,
                                 out_of_range=bool(body[11]) if header_ok else None,
                                 points=list(body[12:]) if header_ok else [])
            self.expected = 2
        elif self.current is None or div != self.expected:
            if self.current is not None:
                self.incomplete += 1
            self.current = None
            return None
        else:
            self.current.points.extend(body)
            self.expected += 1
        if div == top:
            sweep, self.current = self.current, None
            self.complete += 1
            self.lengths[len(sweep.points)] += 1
            return sweep
        return None


def ascii_line(points: list[int], width: int = 72) -> str:
    """Spectre en une ligne de terminal (maximum de chaque tranche)."""
    if not points:
        return ""
    marks = " ▁▂▃▄▅▆▇█"
    out = []
    n = len(points)
    for i in range(width):
        first = i * n // width
        chunk = points[first:max(first + 1, (i + 1) * n // width)]
        level = min(max(chunk), LEVEL_MAX) if chunk else 0
        out.append(marks[round(level / LEVEL_MAX * (len(marks) - 1))])
    return "".join(out)


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
                 clock: Callable[[], float] = time.perf_counter):
        self.ser, self.address, self.say, self.clock = ser, address, say, clock
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
        frame = encode_request(to, cmd, sub, data)
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
            if frame.frm == CONTROLLER:                        # écho de nos propres trames (réglage « CI-V USB Echo Back »)
                self.echo += 1
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
                if frame.to not in (CONTROLLER, BROADCAST):
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

    def run(self, duration_s: float, *, show: bool = True) -> None:
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
