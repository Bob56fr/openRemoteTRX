# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""openRemoteTRX-Autotest, mode B (docs/prequalif-web-cahier-des-charges.md § 8) : rigctld PROPRE à l'Autotest et
LISTE FERMÉE des commandes que la page peut lui faire passer.

La page ne parle jamais directement à rigctld : chaque ligne qu'elle envoie est vérifiée ici (`check_command`) ;
tout ce qui n'est pas dans la liste est refusé. JAMAIS : VOX (la station ne le met jamais en marche), split
(« S 1 VFOB » échange les VFO de l'IC-7300MK2, piège de l'étape 269), coupleur (selon le poste, l'écriture peut
lancer un accord = une émission), XIT, alimentation, commandes brutes (« W »), menus.

rigctld tourne dans un processus à part : une lecture qui le fait tomber (piège de l'étape 255) ne tue que lui ; il
est relancé et la commande fautive est retenue.
"""
from __future__ import annotations

import asyncio
import re
import socket
import subprocess
import time
from dataclasses import dataclass, field

from ..config import NO_CACHE_CONF
from ..hamlib import find_tool

# Niveaux LUS (mesures et réglages) et ÉCRITS (avec leurs bornes) ; fonctions lues et écrites.
READ_LEVELS = frozenset({"STRENGTH", "RFPOWER_METER", "RFPOWER_METER_WATTS", "SWR", "ALC", "RFPOWER", "ATT",
                         "PREAMP", "NR", "NB", "COMP", "AGC"})
WRITE_LEVELS = {"RFPOWER": (0.0, 1.0), "ATT": (0, 60), "PREAMP": (0, 40), "NR": (0.0, 1.0), "NB": (0.0, 10.0),
                "COMP": (0.0, 1.0)}
INT_LEVELS = frozenset({"ATT", "PREAMP", "AGC"})
READ_FUNCS = frozenset({"NB", "NB2", "NR", "ANF", "COMP", "MN", "APF", "RIT", "XIT", "TUNER", "VOX", "LOCK"})
WRITE_FUNCS = frozenset({"NB", "NB2", "NR", "ANF", "COMP", "MN", "APF", "RIT"})
MODE_RE = re.compile(r"^[A-Z]{2,8}$")
FREQ_MIN, FREQ_MAX = 10_000, 3_000_000_000
SPEEDS = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200)
PORT_RE = re.compile(r"^(COM\d{1,3}|/dev/[A-Za-z0-9_./:+-]{1,200})$")
DUMMY_MODEL = 1                    # poste factice de Hamlib : aucun port


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value == value and abs(value) < 1e12 else None     # ni NaN ni infini


def check_command(line: str) -> str | None:
    """Ligne rigctld (protocole court) permise, normalisée ; None = refusée."""
    if not isinstance(line, str) or len(line) > 60:
        return None
    parts = line.split()
    if not parts:
        return None
    key, args = parts[0], parts[1:]
    if key in ("f", "m", "t", "s", "j") and not args:
        return key
    if key == "l" and len(args) == 1 and args[0] in READ_LEVELS:
        return f"l {args[0]}"
    if key == "u" and len(args) == 1 and args[0] in READ_FUNCS:
        return f"u {args[0]}"
    if key == "F" and len(args) == 1 and args[0].isdigit() and FREQ_MIN <= int(args[0]) <= FREQ_MAX:
        return f"F {int(args[0])}"
    if key == "M" and len(args) == 2 and MODE_RE.match(args[0]) and args[1] == "0":
        return f"M {args[0]} 0"                    # largeur TOUJOURS 0 (préréglage du poste, piège des filtres Icom)
    if key == "T" and args in (["0"], ["1"]):
        return f"T {args[0]}"
    if key == "U" and len(args) == 2 and args[0] in WRITE_FUNCS and args[1] in ("0", "1"):
        return f"U {args[0]} {args[1]}"
    if key == "L" and len(args) == 2 and args[0] in WRITE_LEVELS:
        value = _number(args[1])
        low, high = WRITE_LEVELS[args[0]]
        if value is None or not low <= value <= high:
            return None
        if args[0] in INT_LEVELS:
            return None if value != int(value) else f"L {args[0]} {int(value)}"
        return f"L {args[0]} {value:g}"
    if key == "G" and args == ["XCHG"]:
        return "G XCHG"
    return None


def parse_reply(text: str) -> tuple[int | None, list[str]]:
    """Réponse du protocole étendu (« + ») : (code RPRT, valeurs dans l'ordre). La ligne d'écho de la commande
    (« get_freq: », « set_level: RFPOWER 0.1 ») n'est pas une valeur."""
    code, values = None, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("RPRT"):
            try:
                code = int(line.split()[1])
            except (IndexError, ValueError):
                code = -1
            continue
        if re.match(r"^[a-z_\\]+:", line):
            continue
        values.append(line.split(": ", 1)[1].strip() if ": " in line else line)
    return code, values


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class RigSettings:
    model: int
    port: str = ""
    speed: int | None = None

    def problems(self) -> list[str]:
        found = []
        if not isinstance(self.model, int) or not 1 <= self.model <= 99_999:
            found.append("modele")
        if self.model != DUMMY_MODEL and not PORT_RE.match(self.port or ""):
            found.append("port")
        if self.speed is not None and self.speed not in SPEEDS:
            found.append("vitesse")
        return found

    def args(self, exe: str, tcp_port: int) -> list[str]:
        command = [exe, "-m", str(self.model), "-T", "127.0.0.1", "-t", str(tcp_port)]
        if self.port and self.model != DUMMY_MODEL:
            command += ["-r", self.port]
        if self.speed:
            command += ["-s", str(self.speed)]
        return command + ["-C", NO_CACHE_CONF]     # jamais une valeur du cache de rigctld (piège de l'étape 176)


class RigError(Exception):
    """Message destiné à l'opérateur (clé du texte de la page + détail)."""

    def __init__(self, key: str, detail: str = "") -> None:
        super().__init__(f"{key}: {detail}" if detail else key)
        self.key, self.detail = key, detail


@dataclass
class Rigctld:
    """rigctld de l'Autotest : lancé sur un port libre de 127.0.0.1, relancé s'il tombe, arrêté à la fin (après
    « T 0 »)."""
    settings: RigSettings
    hamlib_dir: str = ""
    timeout_s: float = 5.0
    proc: subprocess.Popen | None = None
    tcp_port: int = 0
    crashes: list[str] = field(default_factory=list)       # commandes qui ont fait tomber rigctld
    restarts: int = 0
    _reader: asyncio.StreamReader | None = None
    _writer: asyncio.StreamWriter | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self) -> None:
        exe = find_tool("rigctld", self.hamlib_dir)
        if exe is None:
            raise RigError("hamlib_absent")
        self.tcp_port = free_port()
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        self.proc = subprocess.Popen(self.settings.args(exe, self.tcp_port), stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, creationflags=flags)
        deadline = time.monotonic() + 10.0
        while True:
            if self.proc.poll() is not None:
                error = (self.proc.stderr.read() or b"").decode(errors="replace").strip() if self.proc.stderr else ""
                raise RigError("rigctld_arrete", error[-300:])
            try:
                self._reader, self._writer = await asyncio.open_connection("127.0.0.1", self.tcp_port)
                return
            except OSError:
                if time.monotonic() > deadline:
                    await self.stop()
                    raise RigError("rigctld_muet")
                await asyncio.sleep(0.2)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def _reconnect(self) -> None:
        self._close_link()
        self._reader, self._writer = await asyncio.open_connection("127.0.0.1", self.tcp_port)

    def _close_link(self) -> None:
        if self._writer is not None:
            self._writer.close()
        self._reader = self._writer = None

    async def _exchange(self, line: str) -> str:
        assert self._reader is not None and self._writer is not None
        self._writer.write(f"+{line}\n".encode())
        await self._writer.drain()
        buf = b""
        while True:
            chunk = await self._reader.readline()
            if not chunk:
                raise ConnectionError("rigctld a fermé la connexion")
            buf += chunk
            if chunk.startswith(b"RPRT"):
                return buf.decode(errors="replace")

    async def query(self, line: str) -> dict:
        """Une commande (DÉJÀ vérifiée par `check_command`) : {rprt, valeurs, ms} ou {erreur, ms}."""
        async with self._lock:
            t0 = time.perf_counter()
            ms = lambda: round((time.perf_counter() - t0) * 1000)       # noqa: E731
            try:
                if self._writer is None:
                    await self._reconnect()
                text = await asyncio.wait_for(self._exchange(line), self.timeout_s)
            except asyncio.TimeoutError:
                self._close_link()                       # réponse en retard : la liaison n'est plus en phase
                return {"erreur": "delai", "ms": ms()}
            except (ConnectionError, OSError):
                self._close_link()
                await asyncio.sleep(0.5)
                if not self.alive():                     # cette commande a fait tomber rigctld : relancé, retenue
                    self.crashes.append(line)
                    self.restarts += 1
                    try:
                        await self.start()
                    except RigError:
                        return {"erreur": "rigctld_perdu", "ms": ms()}
                    return {"erreur": "rigctld_tombe", "ms": ms()}
                return {"erreur": "liaison", "ms": ms()}
            code, values = parse_reply(text)
            return {"rprt": code, "valeurs": values, "ms": ms()}

    async def ptt_off(self) -> bool:
        """« T 0 » par une connexion À PART (pas derrière une lecture en cours), puis PTT relu. Ne peut que couper."""
        return (await self.ptt_off_detail())["rx"]

    async def ptt_off_detail(self) -> dict:
        """Comme `ptt_off`, avec le détail des deux commandes pour la trace du rapport (étape 374 : le retour en
        réception d'urgence n'y figurait pas, le service du § 9.2 ne pouvait pas le recalculer) :
        {rx, trace: [{h, rprt, valeurs, ms} | {h, erreur, ms}]}."""
        steps: list[dict] = []
        if not self.tcp_port or not self.alive():
            return {"rx": False, "trace": [{"h": "T 0", "erreur": "rigctld_absent", "ms": 0}]}
        t_open = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", self.tcp_port), 2.0)
        except (OSError, asyncio.TimeoutError):
            return {"rx": False, "trace": [{"h": "T 0", "erreur": "connexion",
                                            "ms": round((time.perf_counter() - t_open) * 1000)}]}
        try:
            async def ask(line: str) -> tuple[int | None, list[str]]:
                t0 = time.perf_counter()
                try:
                    writer.write(f"+{line}\n".encode())
                    await writer.drain()
                    buf = b""
                    while not buf.startswith(b"RPRT") and b"\nRPRT" not in buf:
                        chunk = await asyncio.wait_for(reader.readline(), 3.0)
                        if not chunk:
                            break
                        buf += chunk
                except (OSError, asyncio.TimeoutError, ConnectionError):
                    steps.append({"h": line, "erreur": "liaison", "ms": round((time.perf_counter() - t0) * 1000)})
                    raise
                code, values = parse_reply(buf.decode(errors="replace"))
                steps.append({"h": line, "rprt": code, "valeurs": values,
                              "ms": round((time.perf_counter() - t0) * 1000)})
                return code, values
            await ask("T 0")
            code, values = await ask("t")
            return {"rx": code == 0 and bool(values) and values[0] == "0", "trace": steps}
        except (OSError, asyncio.TimeoutError, ConnectionError):
            return {"rx": False, "trace": steps}
        finally:
            writer.close()

    async def stop(self) -> None:
        self._close_link()
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                await asyncio.to_thread(self.proc.wait, 5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def rig_models(hamlib_dir: str = "") -> list[dict]:
    """Postes connus de Hamlib (`rigctl -l`) : [{n, fabricant, modele}]."""
    from ..setup_wizard import parse_rig_list
    rigctl = find_tool("rigctl", hamlib_dir)
    if rigctl is None:
        return []
    try:
        out = subprocess.run([rigctl, "-l"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [{"n": n, "fabricant": mfg, "modele": name} for n, mfg, name in parse_rig_list(out)]


def rig_profile(model: int, hamlib_dir: str = "") -> dict:
    """Capacités déclarées par Hamlib (`rigctl -m N -u`, sans ouvrir de port)."""
    from ..qualif.profile import parse_profile
    rigctl = find_tool("rigctl", hamlib_dir)
    if rigctl is None:
        return {}
    try:
        out = subprocess.run([rigctl, "-m", str(model), "-u"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return parse_profile(out, model).to_dict()


def serial_ports() -> list[dict]:
    """Ports série du PC (pyserial) : [{port, description}] ; vide si pyserial manque (saisie à la main)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [{"port": p.device, "description": p.description or ""} for p in sorted(list_ports.comports(),
                                                                                key=lambda p: p.device)]
