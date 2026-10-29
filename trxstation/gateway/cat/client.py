# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Client asynchrone du protocole rigctld (Hamlib), protocole étendu ('+').

RÈGLE DE SÉCURITÉ : le PTT se LIT librement, mais n'a qu'UN SEUL chemin d'écriture,
`write_ptt`, que seul `gateway/safety/ptt.py` (PttController : toggle, TOT, heartbeat,
verrou, bandes) a le droit d'appeler. CatLink et l'API ne l'exposent jamais. Un test
parcourt le code source et échoue si un autre fichier y fait référence.

Toute valeur envoyée à rigctld est validée (entiers, noms de mode filtrés) : un saut de
ligne dans un paramètre permettrait sinon d'injecter une seconde commande (ex. « T 1 »).
"""
from __future__ import annotations

import asyncio
import math
import re

MAX_RESPONSE_LINES = 64
MODE_RE = re.compile(r"^[A-Za-z0-9\-]{1,16}$")
LEVEL_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,23}$")
FUNC_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")
# Écritures autorisées : une liste FERMÉE (jamais de nom libre vers rigctld). Aucune n'agit sur le PTT.
WRITABLE_FUNCS = ("NR", "NB", "AIP", "COMP", "TUNER", "ANF", "MN", "RIT", "XIT")   # AIP = IP+ ; TUNER = tuner d'antenne ; ANF/MN = notch auto/manuel ; RIT/XIT = clarifieur (XIT = ΔTX, décale l'ÉMISSION)
OFFSET_MAX_HZ = 99_999                                       # décalage RIT / XIT : borne large ; la passerelle resserre avec « Max RIT/XIT » du poste
WRITABLE_LEVELS = ("SQL", "AGC", "PREAMP", "RFPOWER", "ATT", "NR", "NB")
POWER_STEPS = (0.05, 0.10, 0.25, 0.50, 0.80, 1.00)         # RFPOWER : fraction de la puissance maximale (5, 10, 25, 50, 80, 100 %)
INT_LEVELS = {"AGC": (0, 6), "PREAMP": (0, 30), "ATT": (0, 60)}   # AGC : 0 OFF … 6 AUTO ; PREAMP et ATT en dB (0 = arrêt)
# Niveaux décimaux : bornes LARGES (toutes versions de Hamlib) ; la passerelle resserre avec la plage déclarée par le poste.
FLOAT_LEVELS = {"SQL": (0.0, 1.0), "NR": (0.0, 1.0), "NB": (0.0, 10.0)}
_HEADER_RE = re.compile(r"^(get|set)_[a-z_]+:")        # écho de la commande : « get_level: STRENGTH »

VFO_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,11}")
RIG_ENIMPL = -4    # non implémenté par le backend
RIG_ENAVAIL = -11  # fonction indisponible sur ce poste
HAMLIB_ERRORS = {
    -1: "paramètre invalide", -2: "configuration invalide", -3: "mémoire insuffisante",
    -4: "non implémenté", -5: "délai dépassé côté poste", -6: "erreur d'entrée/sortie",
    -7: "erreur interne", -8: "erreur de protocole", -9: "commande rejetée par le poste",
    -10: "réponse tronquée", -11: "fonction indisponible", -12: "cible inexistante",
    -13: "erreur de bus", -14: "bus occupé", -15: "argument invalide",
    -16: "VFO invalide", -17: "argument hors domaine",
}


class CatConnectionError(ConnectionError):
    """Lien avec rigctld perdu ou illisible : la connexion est abandonnée."""


class CatProtocolError(Exception):
    """Réponse bien terminée mais d'un format inattendu (champ manquant ou illisible)."""


class RigError(Exception):
    """rigctld a répondu RPRT <code non nul> : le poste (ou Hamlib) refuse la commande."""

    def __init__(self, code: int, command: str):
        self.code = code
        self.command = command
        meaning = HAMLIB_ERRORS.get(code, "erreur inconnue")
        super().__init__(f"rigctld a refusé '{command}' : RPRT {code} ({meaning})")


class RigctldClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 4532, timeout: float = 3.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()  # une seule commande en vol à la fois

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        await self.close()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout)
        except (asyncio.TimeoutError, OSError) as exc:
            self._reader = self._writer = None
            raise CatConnectionError(f"connexion à rigctld impossible ({self.host}:{self.port}) : {exc!r}") from exc

    async def close(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def _command(self, line: str) -> dict[str, str]:
        if "\n" in line or "\r" in line:
            raise ValueError("saut de ligne interdit dans une commande rigctld")
        async with self._lock:
            if not self.connected:
                raise CatConnectionError("non connecté à rigctld")
            assert self._reader is not None and self._writer is not None
            try:
                self._writer.write(f"+{line}\n".encode())
                await asyncio.wait_for(self._writer.drain(), self.timeout)
                values: dict[str, str] = {}
                payloads: list[str] = []        # valeurs dans l'ordre, avec ou sans libellé
                for _ in range(MAX_RESPONSE_LINES):
                    raw = await asyncio.wait_for(self._reader.readline(), self.timeout)
                    if not raw:
                        raise CatConnectionError("connexion fermée par rigctld")
                    text = raw.decode(errors="replace").strip()
                    if text.startswith("RPRT"):
                        try:
                            code = int(text.split()[1])
                        except (IndexError, ValueError):
                            raise CatConnectionError(f"ligne RPRT illisible : {text!r}") from None
                        if code != 0:
                            raise RigError(code, line)  # le flux reste synchronisé
                        values.update({f"#{i}": p for i, p in enumerate(payloads, 1)})
                        return values
                    if _HEADER_RE.match(text):
                        continue
                    if ": " in text:
                        key, value = text.split(": ", 1)
                        values[key.strip()] = value.strip()
                        payloads.append(value.strip())
                    elif text:
                        payloads.append(text)    # valeur sans libellé (selon la version de Hamlib)
                raise CatConnectionError("réponse trop longue, flux désynchronisé")
            except (asyncio.TimeoutError, OSError, CatConnectionError) as exc:
                await self.close()  # après un délai ou une erreur, le flux n'est plus fiable
                if isinstance(exc, CatConnectionError):
                    raise
                raise CatConnectionError(f"liaison rigctld perdue : {exc!r}") from exc

    @staticmethod
    def _pick(values: dict[str, str], *keys: str, command: str) -> str:
        """Premier libellé présent, sinon la valeur par position (#1, #2...). Le message d'erreur montre la réponse."""
        for key in keys:
            if key in values:
                return values[key]
        seen = {k: v for k, v in values.items()} or "réponse vide"
        raise CatProtocolError(f"réponse inattendue à '{command}' : {str(seen)[:200]}")

    # ------------------------------------------------------------------ lecture

    async def get_frequency(self) -> int:
        """Fréquence en Hz."""
        raw = self._pick(await self._command("f"), "Frequency", "#1", command="f")
        try:
            return int(float(raw))
        except ValueError:
            raise CatProtocolError(f"fréquence illisible : {raw!r}") from None

    async def get_mode(self) -> tuple[str, int]:
        """(mode, largeur de filtre en Hz)."""
        values = await self._command("m")
        mode = self._pick(values, "Mode", "#1", command="m")
        try:
            return mode, int(float(self._pick(values, "Passband", "#2", command="m")))
        except ValueError:
            raise CatProtocolError("largeur de filtre illisible") from None

    async def get_strength(self) -> int:
        """S-mètre en dB relatifs à S9 (valeur brute Hamlib, 0 = S9). RigError -11 si absent."""
        raw = self._pick(await self._command("l STRENGTH"), "Level Value", "STRENGTH", "#1", command="l STRENGTH")
        try:
            return int(float(raw))
        except ValueError:
            raise CatProtocolError(f"niveau illisible : {raw!r}") from None

    async def get_level(self, name: str) -> float:
        """Niveau Hamlib en lecture seule (ALC, SWR, RFPOWER_METER, STRENGTH...). RigError -11 si absent."""
        if not isinstance(name, str) or not LEVEL_RE.fullmatch(name):
            raise ValueError(f"nom de niveau invalide : {name!r}")
        raw = self._pick(await self._command(f"l {name}"), "Level Value", name, "#1", command=f"l {name}")
        try:
            return float(raw)
        except ValueError:
            raise CatProtocolError(f"niveau illisible : {raw!r}") from None

    async def get_func(self, name: str) -> bool:
        """État d'une fonction Hamlib en lecture seule (NR, NB, AIP = IP+, ANF...). RigError si le poste ne la gère pas."""
        if not isinstance(name, str) or not FUNC_RE.fullmatch(name):
            raise ValueError(f"nom de fonction invalide : {name!r}")
        raw = self._pick(await self._command(f"u {name}"), "Func Status", name, "#1", command=f"u {name}")
        try:
            return int(float(raw)) != 0
        except ValueError:
            raise CatProtocolError(f"état de fonction illisible : {raw!r}") from None

    async def get_ptt(self) -> bool:
        """État du PTT, LECTURE SEULE. Toute valeur non nulle (1, 2, 3) signifie émission."""
        raw = self._pick(await self._command("t"), "PTT", "#1", command="t")
        try:
            return int(raw) != 0
        except ValueError:
            raise CatProtocolError(f"état PTT illisible : {raw!r}") from None

    async def get_split(self) -> bool:
        """Split en service ? (« Split: 0 / TX VFO: currVFO » sur un vrai rigctld). RigError si le poste ne le dit pas."""
        raw = self._pick(await self._command("s"), "Split", "#1", command="s")
        try:
            return int(float(raw)) != 0
        except ValueError:
            raise CatProtocolError(f"split illisible : {raw!r}") from None

    async def get_vfo(self) -> str:
        """VFO actif (« VFO: VFOA » sur un vrai rigctld : VFOA, VFOB, MEM, Main, Sub...). RigError si le poste ne le dit pas
        (IC-7300MK2 : RPRT -11)."""
        raw = self._pick(await self._command("v"), "VFO", "#1", command="v")
        if not VFO_RE.fullmatch(raw):
            raise CatProtocolError(f"VFO illisible : {raw!r}")
        return raw

    async def get_split_frequency(self) -> int:
        """Fréquence d'ÉMISSION en split, en Hz (« TX Frequency: 0 » hors split)."""
        raw = self._pick(await self._command("i"), "TX Frequency", "#1", command="i")
        try:
            return int(float(raw))
        except ValueError:
            raise CatProtocolError(f"fréquence d'émission illisible : {raw!r}") from None

    async def get_offset(self, which: str) -> int:
        """Décalage du clarifieur en Hz : `which` = « RIT » (réception) ou « XIT » (ΔTX, émission)."""
        letter = {"RIT": "j", "XIT": "z"}.get(which)
        if letter is None:
            raise ValueError(f"décalage inconnu : {which!r}")
        raw = self._pick(await self._command(letter), which, "#1", command=letter)
        try:
            return int(float(raw))
        except ValueError:
            raise CatProtocolError(f"décalage illisible : {raw!r}") from None

    # ------------------------------------------------------------------ PTT (réservé)

    async def write_ptt(self, tx: bool) -> None:
        """RÉSERVÉ à PttController. Ne jamais appeler ailleurs, ne jamais exposer à l'API."""
        await self._command(f"T {1 if tx else 0}")

    # ------------------------------------------------------------------ écriture

    async def set_frequency(self, hz: int) -> None:
        if isinstance(hz, bool) or not isinstance(hz, int) or not 0 < hz < 10_000_000_000:
            raise ValueError(f"fréquence invalide : {hz!r}")
        await self._command(f"F {hz}")

    async def set_level(self, name: str, value) -> None:
        """Réglage d'un niveau de la liste WRITABLE_LEVELS : SQL (0 à 1), AGC et PREAMP (entiers)."""
        if name not in WRITABLE_LEVELS:
            raise ValueError(f"niveau non modifiable : {name!r}")
        if name in INT_LEVELS:
            low, high = INT_LEVELS[name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"valeur invalide ({low} à {high}, entier attendu) : {value!r}")
            text = str(value)
        elif name == "RFPOWER":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or round(float(value), 3) not in POWER_STEPS:
                raise ValueError(f"puissance invalide (parmi {', '.join(str(round(p * 100)) for p in POWER_STEPS)} %) : {value!r}")
            text = f"{float(value):.3f}"
        else:
            low, high = FLOAT_LEVELS[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"valeur invalide ({low:g} à {high:g} attendu) : {value!r}")
            text = f"{float(value):.3f}"
        await self._command(f"L {name} {text}")

    async def set_offset(self, which: str, hz: int) -> None:
        """Décalage RIT (« J ») ou XIT / ΔTX (« Z ») en Hz, entier borné : jamais d'autre valeur vers rigctld."""
        letter = {"RIT": "J", "XIT": "Z"}.get(which)
        if letter is None:
            raise ValueError(f"décalage inconnu : {which!r}")
        if isinstance(hz, bool) or not isinstance(hz, int) or not -OFFSET_MAX_HZ <= hz <= OFFSET_MAX_HZ:
            raise ValueError(f"décalage invalide (entier de {-OFFSET_MAX_HZ} à {OFFSET_MAX_HZ} Hz) : {hz!r}")
        await self._command(f"{letter} {hz}")

    async def set_func(self, name: str, on: bool) -> None:
        """Met en ou hors service une fonction de la liste WRITABLE_FUNCS (NR, NB, IP+, compresseur, tuner)."""
        if name not in WRITABLE_FUNCS:
            raise ValueError(f"fonction non modifiable : {name!r}")
        if not isinstance(on, bool):
            raise ValueError(f"état invalide (vrai ou faux attendu) : {on!r}")
        await self._command(f"U {name} {1 if on else 0}")

    async def set_mode(self, mode: str, passband_hz: int = 0) -> None:
        """passband_hz = 0 : largeur par défaut du backend (cf. man rigctl)."""
        if not isinstance(mode, str) or not MODE_RE.fullmatch(mode):
            raise ValueError(f"mode invalide : {mode!r}")
        if isinstance(passband_hz, bool) or not isinstance(passband_hz, int) or not 0 <= passband_hz <= 20_000:
            raise ValueError(f"largeur de filtre invalide : {passband_hz!r}")
        await self._command(f"M {mode} {passband_hz}")
