"""Relevé du spectre HF PAR HAMLIB (rigctld, données asynchrones diffusées en UDP) : outil d'essai autonome.

    python -m trxstation.devtools.hamlib_scope --duree 15                  (poste de station.toml)
    python -m trxstation.devtools.hamlib_scope --config station.toml --duree 30
    python -m trxstation.devtools.hamlib_scope --config station.toml --duree 5 --essai-coupure [--sans-async]

Question posée : rigctld 4.6+ sait-il nous transmettre le spectre (`async=1` + `multicast_data_addr`), en
restant sur la machine, sans gêner la relecture de la fréquence et du PTT ? La station doit être ARRÊTÉE.

L'outil lance SON PROPRE rigctld (127.0.0.1:4542, jamais exposé) avec les réglages de station.toml, plus :
async=1, multicast_data_addr=127.0.0.1 (ou --adresse-donnees), multicast_data_port=4572 et
multicast_cmd_addr=0.0.0.0 (serveur de commandes UDP DÉSACTIVÉ : il n'a aucune authentification et
pourrait mettre le poste en émission). Vers rigctld ne partent que les commandes de la liste fermée
ALLOWED : lecture de la fréquence et du PTT, lecture et marche/arrêt de SCOPE et SPECTRUM, et « T 0 »
(ordre de COUPURE, seulement avec --essai-coupure). Jamais « T 1 » : l'outil ne peut pas émettre.
--essai-coupure : « T 0 » envoyé toutes les 0,5 s pour vérifier que l'ordre de coupure aboutit avec async=1
(rigctld très bavard dans rigctld.log). --sans-async : même essai SANS async ni diffusion, pour comparer.
Les deux fonctions touchées sont relues au départ et remises telles quelles à la fin, même après Ctrl+C.

Résultats dans spectre-hamlib-<date>/ : resume.txt, paquets.txt (premiers paquets bruts), balayages.jsonl,
rapport.html (waterfall), rigctld.log (messages de rigctld).
"""
from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import re
import select
import socket
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .civ_scope import Sweep, ascii_line, station_running, write_html

RIGCTLD_PORT = 4542                   # rigctld privé de l'essai (la station utilise 4532)
DATA_PORT = 4572
ALLOWED = re.compile(r"^(f|t|T 0|u (SCOPE|SPECTRUM)|U (SCOPE|SPECTRUM) [01])$")   # « T 0 » = couper ; jamais « T 1 »
MAX_PACKET = 65535


class CommandRefused(ValueError):
    """Commande rigctld hors de la liste fermée : jamais envoyée."""


# ------------------------------------------------------------------ rigctld (liste fermée)

class RigctlLink:
    def __init__(self, host: str, port: int, timeout: float = 2.0):
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        self.buf = b""

    def command(self, cmd: str) -> tuple[int | None, dict[str, str]]:
        """(code RPRT, valeurs « clé: valeur ») en protocole étendu."""
        if not ALLOWED.fullmatch(cmd):
            raise CommandRefused(f"commande rigctld refusée : {cmd!r}")
        self.sock.sendall(f"+{cmd}\n".encode())
        values: dict[str, str] = {}
        while True:
            while b"\n" not in self.buf:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionError("rigctld a fermé la connexion")
                self.buf += chunk
            line, self.buf = self.buf.split(b"\n", 1)
            text = line.decode(errors="replace").strip()
            if text.startswith("RPRT"):
                try:
                    return int(text.split()[1]), values
                except (IndexError, ValueError):
                    return None, values
            if ": " in text:
                key, value = text.split(": ", 1)
                values[key.strip()] = value.strip()
            elif text and not text.endswith(":"):        # Hamlib répond parfois SANS libellé (« 1 » seul)
                values.setdefault("", text)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def first_value(values: dict[str, str]) -> str | None:
    for key, value in values.items():
        if key not in ("get_func", "set_func", "get_freq", "get_ptt"):
            return value
    return None


# ------------------------------------------------------------------ paquets JSON de Hamlib

def decode_points(data) -> tuple[list[int] | None, str]:
    """Points d'un spectre : chaîne hexadécimale, base64 ou liste ; (None, raison) si illisible."""
    if isinstance(data, list) and all(isinstance(v, int) and not isinstance(v, bool) for v in data):
        return list(data), "liste"
    if isinstance(data, str) and data:
        if len(data) % 2 == 0 and re.fullmatch(r"[0-9A-Fa-f]+", data):
            return list(bytes.fromhex(data)), "hexadécimal"
        try:
            return list(base64.b64decode(data, validate=True)), "base64"
        except (binascii.Error, ValueError):
            pass
    return None, "illisible"


def _number(obj: dict, *names: str) -> int | None:
    for name in names:
        value = obj.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def find_spectra(obj) -> list[dict]:
    """Objets « spectre » d'un paquet, où qu'ils soient (clé spectra/spectrum, ou objet avec data + fréquences)."""
    found: list[dict] = []

    def walk(node, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() in ("spectra", "spectrum") and isinstance(value, list):
                    found.extend(v for v in value if isinstance(v, dict))
                elif key.lower() in ("spectra", "spectrum") and isinstance(value, dict):
                    found.append(value)
                else:
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
    walk(obj)
    return found


class PacketStats:
    def __init__(self) -> None:
        self.packets = 0
        self.unreadable = 0
        self.with_spectrum = 0
        self.top_keys: Counter[str] = Counter()
        self.spectrum_keys: Counter[str] = Counter()
        self.encodings: Counter[str] = Counter()
        self.lengths: Counter[int] = Counter()
        self.samples: list[str] = []

    def feed(self, raw: bytes, t: float) -> list[Sweep]:
        self.packets += 1
        text = raw.decode("utf-8", errors="replace")
        if len(self.samples) < 40:
            self.samples.append(f"{t:9.3f} {text[:4000]}")
        try:
            obj = json.loads(text)
        except ValueError:
            self.unreadable += 1
            return []
        if isinstance(obj, dict):
            self.top_keys.update(obj.keys())
        sweeps = []
        spectra = find_spectra(obj)
        if spectra:
            self.with_spectrum += 1
        for spec in spectra:
            self.spectrum_keys.update(spec.keys())
            points, encoding = decode_points(spec.get("data"))
            self.encodings[encoding] += 1
            if points is None:
                continue
            self.lengths[len(points)] += 1
            low = _number(spec, "lowFreq", "low_freq", "lowEdgeFreq")
            high = _number(spec, "highFreq", "high_freq", "highEdgeFreq")
            center = _number(spec, "centerFreq", "center_freq")
            span = _number(spec, "span", "spanFreq")
            sweeps.append(Sweep(t=t, mode=None, f1_hz=low if low is not None else center,
                                f2_hz=high if high is not None else span, out_of_range=None, points=points))
        return sweeps


# ------------------------------------------------------------------ relevé

class HamlibScopeProbe:
    def __init__(self, link, recv: Callable[[float], bytes | None], *, say: Callable[[str], None] = print,
                 clock: Callable[[], float] = time.perf_counter, unkey_test: bool = False, use_spectrum: bool = True):
        self.link, self.recv, self.say, self.clock = link, recv, say, clock
        self.unkey_test, self.use_spectrum = unkey_test, use_spectrum
        self.unkey_codes: Counter[str] = Counter()
        self.t0 = clock()
        self.stats = PacketStats()
        self.sweeps: list[Sweep] = []
        self.latency_ms: dict[str, list[float]] = {"f": [], "t": [], "T 0": []}
        self.ptt_values: Counter[str] = Counter()
        self.failures: Counter[str] = Counter()
        self.notes: list[str] = []

    def timed(self, cmd: str) -> tuple[int | None, dict[str, str]]:
        start = self.clock()
        code, values = self.link.command(cmd)
        if code == 0:
            self.latency_ms[cmd].append((self.clock() - start) * 1000)
        else:
            self.failures[cmd] += 1
        return code, values

    def read_func(self, name: str) -> int | None:
        code, values = self.link.command(f"u {name}")
        value = first_value(values)
        if code != 0 or value not in ("0", "1"):
            self.notes.append(f"lecture « u {name} » : RPRT {code}, réponse {values}")
        return int(value) if code == 0 and value in ("0", "1") else None

    # État inconnu au départ : l'AFFICHAGE du spectre reste allumé (on ne l'éteint pas sur une supposition),
    # la SORTIE des données est éteinte à la fin (elle ne sert qu'à l'essai et charge la liaison CI-V).
    UNKNOWN_RESTORE = {"SCOPE": None, "SPECTRUM": 0}

    def run(self, duration_s: float, *, show: bool = True) -> None:
        names = ("SCOPE", "SPECTRUM") if self.use_spectrum else ()
        before = {name: self.read_func(name) for name in names}
        if self.use_spectrum:
            self.notes.append(f"état de départ : SCOPE {before['SCOPE']}, SPECTRUM {before['SPECTRUM']} (None = illisible)")
        changed: list[tuple[str, int]] = []
        try:
            for name in names:
                if before[name] != 1:
                    code, _ = self.link.command(f"U {name} 1")
                    if code == 0:
                        restore = before[name] if before[name] is not None else self.UNKNOWN_RESTORE[name]
                        if restore is not None:
                            changed.append((name, restore))
                            self.say(f"{name} : activé par rigctld pour l'essai (remis à {restore} à la fin).")
                        else:
                            self.say(f"{name} : activé par rigctld ; état de départ inconnu, laissé activé à la fin.")
                            self.notes.append(f"{name} laissé à 1 (état de départ illisible)")
                    else:
                        self.say(f"{name} : activation REFUSÉE par rigctld (RPRT {code}).")
                        self.notes.append(f"activation refusée : U {name} 1 (RPRT {code})")
            end = self.clock() + duration_s
            next_query = next_show = self.clock()
            while self.clock() < end:
                now = self.clock()
                if now >= next_query:                           # rigctld reste-t-il réactif sous le flux ?
                    next_query = now + 0.5
                    self.timed("f")
                    code, values = self.timed("t")
                    if code == 0:
                        self.ptt_values[first_value(values) or "?"] += 1
                    if self.unkey_test:                         # l'ordre de COUPURE aboutit-il ? (jamais « T 1 »)
                        try:
                            code, _ = self.timed("T 0")
                            self.unkey_codes[f"RPRT {code}"] += 1
                        except (OSError, ConnectionError) as exc:
                            self.unkey_codes[type(exc).__name__] += 1
                packet = self.recv(0.05)
                if packet:
                    self.sweeps.extend(self.stats.feed(packet, self.clock() - self.t0))
                if show and now >= next_show:
                    next_show = now + 1.0
                    self.say(self.status_line())
        finally:
            for name, value in reversed(changed):
                try:
                    restored = self.link.command(f"U {name} {value}")[0] == 0
                except (Exception, KeyboardInterrupt):
                    restored = False
                if not restored:
                    self.say(f"ATTENTION : {name} non remis à {value} : vérifie le menu du spectre du poste.")
                    self.notes.append(f"remise en état NON confirmée : U {name} {value}")

    def status_line(self) -> str:
        elapsed = max(1e-6, self.clock() - self.t0)
        head = f"{elapsed:5.1f} s  paquets {self.stats.packets:4d}  balayages {len(self.sweeps):4d} ({len(self.sweeps) / elapsed:4.1f}/s)"
        if not self.sweeps:
            return head
        return head + f"  {len(self.sweeps[-1].points)} points  |{ascii_line(self.sweeps[-1].points)}|"

    def summary(self, data_addr: str) -> str:
        s = self.stats
        elapsed = max(1e-6, self.clock() - self.t0)
        lines = [f"Données diffusées par rigctld vers {data_addr}:{DATA_PORT} ; serveur de commandes UDP désactivé",
                 f"Durée {elapsed:.1f} s ; paquets {s.packets} ({s.packets / elapsed:.1f}/s) ; illisibles {s.unreadable} ; "
                 f"avec spectre {s.with_spectrum} ; balayages décodés {len(self.sweeps)} ({len(self.sweeps) / elapsed:.1f}/s)",
                 "Clés des paquets : " + (", ".join(f"{k} ({n})" for k, n in s.top_keys.most_common(20)) or "—"),
                 "Clés d'un spectre : " + (", ".join(f"{k} ({n})" for k, n in s.spectrum_keys.most_common(20)) or "—"),
                 "Codage des points : " + (", ".join(f"{k} ({n})" for k, n in s.encodings.most_common()) or "—"),
                 "Points par balayage : " + (", ".join(f"{k} ({n})" for k, n in s.lengths.most_common()) or "—")]
        if self.sweeps:
            last = self.sweeps[-1]
            lines.append(f"Dernier balayage : valeur 1 {last.f1_hz} Hz, valeur 2 {last.f2_hz} Hz, "
                         f"niveaux {min(last.points)}..{max(last.points)}")
        if self.unkey_test:
            values = sorted(self.latency_ms["T 0"])
            lines.append("Ordre de coupure « T 0 » : " + (", ".join(f"{k} ({n})" for k, n in self.unkey_codes.items()) or "—")
                         + (f" ; réussis en {values[0]:.0f} à {values[-1]:.0f} ms" if values else ""))
        for cmd, label in (("f", "fréquence"), ("t", "PTT")):
            values = sorted(self.latency_ms[cmd])
            if values:
                lines.append(f"Lecture {label} par rigctld pendant le flux : {len(values)} réponses, min {values[0]:.0f} ms, "
                             f"médiane {statistics.median(values):.0f} ms, max {values[-1]:.0f} ms ; échecs {self.failures[cmd]}")
            else:
                lines.append(f"Lecture {label} par rigctld : aucune réponse (échecs {self.failures[cmd]})")
        lines.append("Valeurs du PTT relues : " + (", ".join(f"{k} ({n})" for k, n in self.ptt_values.items()) or "—"))
        lines += self.notes
        return "\n".join(lines)


def data_socket(address: str, port: int) -> socket.socket:
    """Socket UDP de réception ; une adresse multicast est rejointe (et signalée comme sortant de la machine)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ip = ipaddress.ip_address(address)
    if ip.is_multicast:
        sock.bind(("", port))
        membership = socket.inet_aton(address) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    else:
        sock.bind((address, port))
    return sock


def make_recv(sock: socket.socket) -> Callable[[float], bytes | None]:
    def recv(timeout: float) -> bytes | None:
        ready, _, _ = select.select([sock], [], [], timeout)
        return sock.recvfrom(MAX_PACKET)[0] if ready else None
    return recv


def rigctld_probe_command(cfg, data_addr: str, *, use_async: bool = True, verbose: str = "-vv") -> list[str]:
    from ..hamlib import find_tool
    exe = find_tool("rigctld", cfg.tools.hamlib_dir)
    if exe is None:
        raise FileNotFoundError("rigctld introuvable : installe Hamlib ou renseigne [tools] hamlib_dir")
    args = cfg.rig.rigctld_args("127.0.0.1", RIGCTLD_PORT)
    if not use_async:
        return [exe, *args[1:], verbose]
    conf = (f"async=1,multicast_data_addr={data_addr},multicast_data_port={DATA_PORT},"
            "multicast_cmd_addr=0.0.0.0")
    return [exe, *args[1:], "-C", conf, verbose]


def wait_port(port: int, proc: subprocess.Popen, timeout: float = 15.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def save(folder: Path, probe: HamlibScopeProbe, summary: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "resume.txt").write_text(summary + "\n", encoding="utf-8")
    (folder / "paquets.txt").write_text("\n".join(probe.stats.samples) + "\n", encoding="utf-8")
    with open(folder / "balayages.jsonl", "w", encoding="utf-8") as out:
        for sweep in probe.sweeps:
            out.write(json.dumps(asdict(sweep)) + "\n")
    write_html(folder / "rapport.html", summary, probe.sweeps)


def main(argv: list[str] | None = None) -> int:
    from .. import config as cfgmod
    from ..qualif.main import find_config

    ap = argparse.ArgumentParser(prog="hamlib_scope", description="Relevé du spectre HF par rigctld (lecture seule)")
    ap.add_argument("--config", type=Path, default=None, help="station.toml (défaut : emplacement standard, sinon ./station.toml)")
    ap.add_argument("--duree", type=float, default=15.0, help="durée du relevé en secondes (défaut 15)")
    ap.add_argument("--adresse-donnees", default="127.0.0.1",
                    help="destination des données de rigctld (défaut 127.0.0.1 : reste sur la machine)")
    ap.add_argument("--sortie", type=Path, default=None, help="dossier des résultats (défaut spectre-hamlib-<date>)")
    ap.add_argument("--essai-coupure", action="store_true", help="envoie aussi « T 0 » (coupure) toutes les 0,5 s ; jamais « T 1 »")
    ap.add_argument("--sans-async", action="store_true", help="rigctld SANS async ni diffusion (comparaison)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if not 1 <= args.duree <= 300:
        print("--duree : de 1 à 300 secondes.", file=sys.stderr)
        return 2
    try:
        data_ip = ipaddress.ip_address(args.adresse_donnees)
    except ValueError:
        print("--adresse-donnees : adresse IPv4 attendue (ex. 127.0.0.1).", file=sys.stderr)
        return 2
    if not (data_ip.is_loopback or data_ip.is_multicast) or data_ip.version != 4:
        print("--adresse-donnees : 127.0.0.1 (machine seule) ou une adresse multicast IPv4 seulement.", file=sys.stderr)
        return 2
    if data_ip.is_multicast:
        print("ATTENTION : avec une adresse multicast, l'état du poste et le spectre peuvent sortir sur le réseau local.")
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
    try:
        command = rigctld_probe_command(cfg, args.adresse_donnees, use_async=not args.sans_async,
                                        verbose="-vvvv" if args.essai_coupure else "-vv")
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    folder = args.sortie or Path(f"spectre-hamlib-{datetime.now():%Y%m%d-%H%M%S}")
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder / "rigctld.log"
    try:
        sock = data_socket(args.adresse_donnees, DATA_PORT)
    except OSError as exc:
        print(f"Réception UDP impossible sur {args.adresse_donnees}:{DATA_PORT} : {exc}", file=sys.stderr)
        return 1
    print("rigctld d'essai : " + " ".join(command[1:]))
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        link = None
        probe = None
        try:
            if not wait_port(RIGCTLD_PORT, proc):
                print(f"rigctld ne démarre pas (voir {log_path}).", file=sys.stderr)
                return 1
            link = RigctlLink("127.0.0.1", RIGCTLD_PORT)
            probe = HamlibScopeProbe(link, make_recv(sock), unkey_test=args.essai_coupure, use_spectrum=not args.sans_async)
            print(f"Relevé pendant {args.duree:g} s (Ctrl+C pour arrêter plus tôt)...")
            try:
                probe.run(args.duree)
            except KeyboardInterrupt:
                print("\nInterrompu : fonctions du poste remises en état.")
            except (OSError, ConnectionError) as exc:               # rigctld ne répond plus : c'est un résultat, pas un plantage
                probe.notes.append(f"rigctld NE RÉPOND PLUS ({type(exc).__name__} : {exc}) : relevé interrompu")
                print(f"\nrigctld ne répond plus ({exc}) : relevé interrompu (voir {log_path}).")
        finally:
            if link is not None:
                link.close()
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            sock.close()
    if probe is None:
        return 1
    summary = ("SANS async (comparaison)\n" if args.sans_async else "") + probe.summary(args.adresse_donnees)
    save(folder, probe, summary)
    print("\n" + summary + f"\n\nRésultats : {folder.resolve()} (rapport.html, paquets.txt, rigctld.log).")
    if args.essai_coupure:
        return 0 if probe.unkey_codes and set(probe.unkey_codes) == {"RPRT 0"} else 1
    return 0 if probe.sweeps else 1


if __name__ == "__main__":
    raise SystemExit(main())
