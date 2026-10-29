# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Protocole SELCALL (cahier des charges § 3) : constantes nommées et construction de la trame, sans numpy.

Trame : pilote F0 (1 s), puis les chiffres du code, puis le chiffre de contrôle (somme des chiffres modulo 10),
300 ms par symbole, contigus et à phase continue. Un symbole identique au précédent est remplacé par R.
En BLU, un défaut d'accord décale toutes les fréquences de la même valeur Δ : le pilote la mesure.
"""
from __future__ import annotations

F0_HZ = 1000.0                 # pilote nominal
PILOT_S = 1.0
SYMBOL_S = 0.3
DIGIT_BASE_HZ = 200.0          # chiffre d : F0 + 200 + 100 × d (1200 à 2100 Hz)
DIGIT_STEP_HZ = 100.0
REPEAT_OFFSET_HZ = 1200.0      # symbole R : F0 + 1200 (2200 Hz)
CODE_MIN, CODE_MAX = 3, 8
RAMP_S = 0.005                 # rampe en cosinus au début et à la fin de chaque ton (pas de clic)
TX_LEVEL_DBFS = -6.0           # niveau d'émission par défaut (sous le seuil d'ALC)
MAX_OFFSET_HZ = 300.0          # décalage d'accord toléré

REPEAT = "R"


class CodeError(ValueError):
    """Code SELCALL invalide (chiffres seulement, 3 à 8)."""


def validate_code(code: str) -> str:
    """Code saisi par l'utilisateur -> code sûr ; CodeError sinon."""
    if not isinstance(code, str) or not code.isascii() or not code.isdigit() or not CODE_MIN <= len(code) <= CODE_MAX:
        raise CodeError(f"code SELCALL invalide : {CODE_MIN} à {CODE_MAX} chiffres attendus")
    return code


def check_digit(code: str) -> int:
    return sum(int(c) for c in code) % 10


def symbols(code: str) -> list[str]:
    """Chiffres du code puis contrôle, chaque répétition remplacée par R (« 4477 » -> 4 R 7 R 2)."""
    raw = list(validate_code(code)) + [str(check_digit(code))]
    out: list[str] = []
    for i, s in enumerate(raw):
        out.append(REPEAT if i > 0 and s == raw[i - 1] else s)
    return out


def symbol_hz(symbol: str, offset_hz: float = 0.0) -> float:
    if symbol == REPEAT:
        return F0_HZ + REPEAT_OFFSET_HZ + offset_hz
    return F0_HZ + DIGIT_BASE_HZ + DIGIT_STEP_HZ * int(symbol) + offset_hz


GRID = [str(d) for d in range(10)] + [REPEAT]      # les 11 symboles possibles après le pilote


def tones(code: str, offset_hz: float = 0.0) -> list[tuple[float, float]]:
    """(fréquence, durée) de toute la trame : pilote puis symboles."""
    return [(F0_HZ + offset_hz, PILOT_S)] + [(symbol_hz(s, offset_hz), SYMBOL_S) for s in symbols(code)]


def duration_s(code: str) -> float:
    return PILOT_S + (len(validate_code(code)) + 1) * SYMBOL_S


def unpack(received: list[str]) -> str | None:
    """Symboles décodés (après le pilote) -> code si la trame est valide (R remplacés, contrôle juste, 3 à 8 chiffres)."""
    if not received or received[0] == REPEAT:
        return None
    digits: list[str] = []
    for s in received:
        if s == REPEAT:
            digits.append(digits[-1])
        elif s.isdigit() and len(s) == 1:
            if digits and s == digits[-1]:
                return None                            # un chiffre répété aurait dû être émis en R
            digits.append(s)
        else:
            return None
    code, check = "".join(digits[:-1]), digits[-1]
    if not CODE_MIN <= len(code) <= CODE_MAX or check_digit(code) != int(check):
        return None
    return code
