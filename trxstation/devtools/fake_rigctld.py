"""Faux rigctld (protocole étendu) pour développer et tester sans Hamlib ni poste.

Usage manuel (ex. sous Windows, pour lancer la passerelle sans matériel) :
    python -m trxstation.devtools.fake_rigctld --port 4532

Usage en test : voir tests/test_cat.py. Les attributs `errors` (code RPRT par commande),
`delay_s` et `drop_connections()` permettent de simuler des pannes.
Le faux poste enregistre toutes les commandes reçues, dont tout PTT (`ptt_set_calls`).
"""
from __future__ import annotations

import argparse
import asyncio

from .loop_noise import install_quiet_reset_handler


class FakeRigctld:
    def __init__(self) -> None:
        self.freq = 14_200_000
        self.mode = "USB"
        self.passband = 2400
        self.strength = -54
        self.levels: dict[str, float] = {"ALC": 0.0, "SWR": 1.1, "RFPOWER_METER": 0.0, "COMP_METER": 0.0, "PREAMP": 10,
                                         "ATT": 0, "AGC": 3, "SQL": 0.2, "RFPOWER": 1.0, "VD_METER": 13.8, "TEMP_METER": 31.0}
        self.funcs: dict[str, int] = {"NR": 0, "NB": 1, "AIP": 0, "ANF": 0, "COMP": 0, "TUNER": 0}
        self.ptt = 0
        self.commands: list[str] = []
        self.errors: dict[str, int] = {}   # clé = lettre de commande (« l », « F »...) -> code RPRT
        self.delay_s = 0.0
        self.fail_t = 0            # les N prochaines commandes T échouent (RPRT -5)
        self.ignore_unkey = False  # « T 0 » accepté mais le PTT reste actif (poste bloqué)
        self.bare = False          # réponses SANS libellé (« 14200000 » au lieu de « Frequency: 14200000 »)
        self.broken_strength = False  # « l STRENGTH » répond sans aucune valeur
        self.port = 0
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    @property
    def ptt_set_calls(self) -> int:
        return sum(1 for c in self.commands if c[1:2] == "T" or c.lower().startswith("+\\set_ptt"))

    @property
    def ptt_commands(self) -> list[int]:
        """Valeurs successives envoyées par « T » (1 = émission, 0 = réception)."""
        return [int(c.split()[-1]) for c in self.commands if c[1:2] == "T" and c.split()[-1].lstrip("-").isdigit()]

    def count_command(self, text: str) -> int:
        """Nombre de fois qu'une commande exacte (ex. « l STRENGTH ») a été reçue."""
        return sum(1 for c in self.commands if c.lstrip("+") == text)

    def count(self, letter: str) -> int:
        return sum(1 for c in self.commands if c[1:].split(" ")[0] == letter)

    async def start(self, port: int = 0) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        self.drop_connections()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def drop_connections(self) -> None:
        for writer in list(self._writers):
            writer.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").strip()
                self.commands.append(line)
                if self.delay_s:
                    await asyncio.sleep(self.delay_s)
                writer.write(self._reply(line).encode())
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    def _out(self, label: str, value) -> str:
        return f"{value}\n" if self.bare else f"{label}: {value}\n"

    def _reply(self, line: str) -> str:
        parts = line.lstrip("+").split()
        if not parts:
            return "RPRT -1\n"
        key, args = parts[0], parts[1:]
        if key in self.errors:
            return f"RPRT {self.errors[key]}\n"
        try:
            if key == "f":
                return f"get_freq:\n{self._out('Frequency', self.freq)}RPRT 0\n"
            if key == "F":
                self.freq = int(float(args[0]))
                return f"set_freq: {args[0]}\nRPRT 0\n"
            if key == "m":
                return f"get_mode:\n{self._out('Mode', self.mode)}{self._out('Passband', self.passband)}RPRT 0\n"
            if key == "M":
                self.mode, self.passband = args[0], int(args[1])
                return f"set_mode: {args[0]} {args[1]}\nRPRT 0\n"
            if key == "l" and args[:1]:
                if self.broken_strength and args[0] == "STRENGTH":
                    return "get_level: STRENGTH\nRPRT 0\n"
                value = self.strength if args[0] == "STRENGTH" else self.levels.get(args[0])
                if value is None:
                    return "RPRT -11\n"
                return f"get_level: {args[0]}\n{self._out('Level Value', value)}RPRT 0\n"
            if key == "u" and args:
                if args[0] not in self.funcs:
                    return "RPRT -11\n"
                return f"get_func: {args[0]}\n{self._out('Func Status', self.funcs[args[0]])}RPRT 0\n"
            if key == "U" and len(args) == 2:
                if args[0] not in self.funcs or args[1] not in ("0", "1"):
                    return "RPRT -11\n"
                self.funcs[args[0]] = int(args[1])
                return f"set_func: {args[0]} {args[1]}\nRPRT 0\n"
            if key == "L" and len(args) == 2:
                if args[0] not in ("SQL", "AGC", "PREAMP", "RFPOWER"):
                    return "RPRT -11\n"
                self.levels[args[0]] = float(args[1]) if args[0] in ("SQL", "RFPOWER") else int(args[1])
                return f"set_level: {args[0]} {args[1]}\nRPRT 0\n"
            if key == "t":
                return f"get_ptt:\n{self._out('PTT', self.ptt)}RPRT 0\n"
            if key == "T":
                value = int(args[0])
                if self.fail_t > 0:
                    self.fail_t -= 1
                    return "RPRT -5\n"
                if not (value == 0 and self.ignore_unkey):
                    self.ptt = value
                return f"set_ptt: {args[0]}\nRPRT 0\n"
        except (IndexError, ValueError):
            return "RPRT -1\n"
        return "RPRT -4\n"


async def _serve(port: int) -> None:
    install_quiet_reset_handler(asyncio.get_running_loop())
    fake = FakeRigctld()
    await fake.start(port)
    print(f"Faux rigctld en écoute sur 127.0.0.1:{fake.port} (Ctrl+C pour arrêter)")
    await asyncio.Event().wait()


def main() -> None:
    ap = argparse.ArgumentParser(description="Faux rigctld pour le développement")
    ap.add_argument("--port", type=int, default=4532)
    args = ap.parse_args()
    try:
        asyncio.run(_serve(args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
