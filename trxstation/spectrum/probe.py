"""Second port CI-V d'un Icom : ouverture prudente, lecture des trames et vérification du réglage du poste.

Le poste doit avoir un second port série réglé en CI-V (IC-7300MK2 : « Serial Port B »). À CHAQUE ouverture, on
vérifie que la configuration n'a pas changé depuis l'assistant :
  1. le poste répond à SON adresse CI-V (sinon : port pas en CI-V, débit ou adresse changés) ;
  2. il accepte les réglages du spectre (27 10 / 27 11 lisibles) ;
  3. il affiche la MÊME fréquence que sur le port CAT (sinon : c'est un autre appareil).
Un échec lève CheckFailed(code) : l'appelant revient au mode normal (un seul port, pas de waterfall HF).

Sécurité : RTS et DTR à zéro AVANT l'ouverture (une ligne affectée à « USB SEND » déclencherait l'émission) ;
seules les commandes de la liste fermée de civ.py partent vers le poste (jamais 1C) ; ce module n'a aucun
moyen de mettre le poste en émission. La vérification du PTT après l'ouverture est faite par l'appelant,
qui seul lit le port CAT.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from .civ import (BROADCAST, CONTROLLERS, NG, OK, Frame, FrameReader, ScopeAssembler, Sweep, bcd_le,
                  encode_request)

STATION_CONTROLLER = 0xE1     # adresse de la station sur le port B ; rigctld parle en E0h sur le port A
SCOPE_DISPLAY, SCOPE_OUTPUT = 0x10, 0x11

FALLBACK = "Mode normal : un seul port, sans waterfall HF."
USB_SEND_WARNING = """\
AVANT D'OUVRIR LE SECOND PORT, vérifie sur le poste (MENU > SET > Connecteurs) :
  - « USB SEND », « USB Keying (CW) » et « USB Keying (RTTY) » : aucun ne doit utiliser ce port
    (OFF, ou une ligne du port CAT seulement). Sinon son ouverture peut METTRE LE POSTE EN ÉMISSION.
  - fonction du second port (« USB Serial Function » ou équivalent) : CI-V.
  - charge fictive ou antenne branchée, puissance au minimum (par précaution : rien n'est émis).
"""
MESSAGES = {
    "open_failed": "port {port} impossible à ouvrir ({detail}) : poste éteint, câble débranché, numéro de port changé, "
                   "ou port tenu par un autre programme.",
    "no_answer": "aucune réponse CI-V sur {port} : le second port n'est pas (ou plus) réglé en CI-V dans le menu du poste "
                 "(MENU > SET > Connecteurs), ou son débit a changé.",
    "wrong_address": "le poste répond sur {port} à l'adresse {detail} au lieu de {expected} : adresse CI-V changée "
                     "dans le menu du poste (corrige-la, ou relance trx-setup --spectre {port}).",
    "no_scope": "le poste refuse les réglages du spectre sur {port} : ce poste ne fournit pas le spectre par le CI-V.",
    "other_rig": "{port} n'affiche pas la même fréquence que le port CAT ({detail}) : ce n'est pas le même poste.",
    "ptt_on_open": "l'ouverture de {port} a mis le poste en ÉMISSION : un réglage « USB SEND » ou « USB Keying » du "
                   "poste utilise ce port. Coupure faite ; spectre désactivé jusqu'au redémarrage de la station.",
    "ptt_unknown": "état d'émission illisible juste après l'ouverture de {port} : par prudence, port refermé.",
    "ptt_busy": "le poste est passé en émission juste après l'ouverture de {port}, mais pas à cause de ce port (l'émission "
                "a continué port refermé : micro du poste ?). Coupure faite par prudence ; nouvel essai plus tard.",
    "silent": "plus aucune donnée du spectre sur {port} depuis {detail} s (écran du poste sur un menu ou un autre "
              "écran que le spectre, spectre éteint sur le poste, réglage modifié ou câble).",
    "port_lost": "port {port} perdu ({detail}).",
    "no_pyserial": "module pyserial absent : pip install pyserial (spectre désactivé).",
    "internal": "erreur interne du spectre ({detail}).",
}


class CheckFailed(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")

    def message(self, port: str, expected: int | None = None) -> str:
        text = MESSAGES.get(self.code, self.code).format(port=port, detail=self.detail,
                                                         expected=f"{expected:02X}h" if expected is not None else "?")
        return text[0].upper() + text[1:]


def open_serial(port: str, baud: int):
    """Ouvre le port avec RTS et DTR à zéro AVANT l'ouverture (pyserial les applique à l'ouverture)."""
    import serial
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, baud, 0.02
    ser.rts, ser.dtr = False, False
    ser.open()
    return ser


class CivPort:
    """Dialogue CI-V sur le second port : demandes une par une, balayages du spectre recomposés au passage."""

    def __init__(self, ser, address: int, *, controller: int = STATION_CONTROLLER,
                 on_sweep: Callable[[Sweep], None] | None = None, clock: Callable[[], float] = time.monotonic):
        self.ser, self.address, self.controller, self.on_sweep, self.clock = ser, address, controller, on_sweep, clock
        self.reader, self.scope = FrameReader(), ScopeAssembler()
        self.t0 = clock()
        self.last_sweep_at: float | None = None
        self.sweeps = 0

    def _send(self, to: int, cmd: int, sub: int | None = None, data: bytes | None = None) -> None:
        self.ser.write(encode_request(to, cmd, sub, data, frm=self.controller))

    def poll(self) -> list[Frame]:
        """Lit ce qui est arrivé (attend au plus le délai du port) ; renvoie les trames qui nous sont adressées."""
        chunk = self.ser.read(self.ser.in_waiting or 1)
        if not chunk:
            return []
        mine = []
        for frame in self.reader.feed(chunk):
            if frame.frm == self.controller or frame.frm in CONTROLLERS:     # écho, ou commande d'un autre contrôleur
                continue
            if frame.payload[:2] == b"\x27\x00":
                sweep = self.scope.feed(frame.payload[2:], self.clock() - self.t0)
                if sweep is not None:
                    self.sweeps += 1
                    self.last_sweep_at = self.clock()
                    if self.on_sweep is not None:
                        self.on_sweep(sweep)
                continue
            if frame.to in (self.controller, BROADCAST):
                mine.append(frame)
        return mine

    def request(self, cmd: int, sub: int | None = None, data: bytes | None = None, *, to: int | None = None,
                timeout: float = 1.0) -> Frame | None:
        """Réponse (FB, FA ou données) à une commande de la liste fermée ; None sans réponse."""
        self._send(self.address if to is None else to, cmd, sub, data)
        prefix = bytes([cmd]) + (bytes([sub]) if sub is not None else b"")
        end = self.clock() + timeout
        while self.clock() < end:
            for frame in self.poll():
                if frame.payload[:1] in (bytes([OK]), bytes([NG])) or frame.payload.startswith(prefix):
                    return frame
        return None

    def identify(self, to: int | None = None, timeout: float = 0.6) -> int | None:
        """Adresse renvoyée par le poste à « 19 00 » ; None sans réponse."""
        reply = self.request(0x19, 0x00, to=to, timeout=timeout)
        if reply is None or reply.payload[:2] != b"\x19\x00":
            return None
        return reply.payload[2] if len(reply.payload) > 2 else reply.frm

    def read_freq(self) -> int | None:
        reply = self.request(0x03)
        if reply is None or reply.payload[:1] != b"\x03" or len(reply.payload) < 6:
            return None
        return bcd_le(reply.payload[1:6])

    def read_setting(self, sub: int) -> int | None:
        reply = self.request(0x27, sub)
        if reply is None or reply.payload[:2] != bytes([0x27, sub]) or len(reply.payload) < 3:
            return None
        return reply.payload[-1]

    def set_setting(self, sub: int, value: int) -> bool:
        reply = self.request(0x27, sub, bytes([value]))
        return reply is not None and reply.payload[:1] == bytes([OK])


def detect_address(port: CivPort, candidates: tuple[int, ...] = (0x94, 0xA4, 0xB6)) -> int | None:
    """Adresse du poste sur ce port (demande diffusée, puis adresses courantes) ; None si personne ne répond."""
    for to in (BROADCAST, *candidates):
        found = port.identify(to=to)
        if found is not None:
            return found
    return None


def check(port: CivPort, cat_freq: Callable[[], int | None], *, attempts: int = 3,
          sleep: Callable[[float], None] = time.sleep) -> dict[int, int]:
    """Vérifie que le second port est bien celui du MÊME poste, en CI-V, avec le spectre. Renvoie l'état de départ
    des deux réglages du spectre {27 10: x, 27 11: y}. CheckFailed sinon."""
    if port.identify() != port.address:
        other = detect_address(port)
        if other is not None and other != port.address:
            raise CheckFailed("wrong_address", f"{other:02X}h")
        raise CheckFailed("no_answer")
    settings = {sub: port.read_setting(sub) for sub in (SCOPE_DISPLAY, SCOPE_OUTPUT)}
    if None in settings.values():
        raise CheckFailed("no_scope")
    seen = ""
    for attempt in range(attempts):                 # le bouton peut tourner entre les deux lectures : on réessaie
        mine, cat = port.read_freq(), cat_freq()
        if mine is None:
            raise CheckFailed("no_answer")
        if cat is None or mine == cat:
            return settings                         # CAT illisible : identité et spectre suffisent
        seen = f"{mine} Hz contre {cat} Hz"
        if attempt + 1 < attempts:
            sleep(0.3)
    raise CheckFailed("other_rig", seen)
