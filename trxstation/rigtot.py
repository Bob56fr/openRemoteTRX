# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TOT du poste (minuterie d'émission interne) : LECTURE SEULE, à la connexion d'un opérateur.

Cahier `docs/tot-poste-cahier-des-charges.md`. Hamlib n'a aucun paramètre pour ce réglage (2026-11-20) : la station
le lit par une commande brute passée à rigctld (« W »), d'après une TABLE DE DONNÉES par modèle Hamlib. Un modèle n'y
entre qu'après une qualification réussie sur le vrai poste (lecture de chaque valeur, poste éteint = inconnu, coupure
réelle par le poste). Liste fermée : une seule trame par modèle, construite ici, jamais fournie par un client ; aucune
écriture.

Règle « à coup sûr » (§ 4 du cahier) : le poste vient de répondre à une autre lecture, la réponse a exactement la forme
attendue et une valeur connue, deux lectures successives sont identiques. Sinon : « unknown », JAMAIS « off » (chez
Yaesu, Hamlib répond 0 quand le poste est muet : piège de l'étape 287).
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CONTROLLER = 0xE0                     # adresse CI-V des commandes passées par rigctld


@dataclass(frozen=True)
class CivTot:
    """Menu « 1A 05 <menu> » d'un Icom : valeur lue -> minutes (0 = arrêt)."""
    name: str
    address: int                      # adresse CI-V du poste (réglage d'usine)
    menu: bytes                       # octets du menu après « 1A 05 »
    minutes: dict[int, int]           # code lu -> minutes ; 0 = OFF
    ptt_types: tuple[str, ...]        # méthodes PTT de station.toml pour lesquelles le TOT du poste protège
    validated: str                    # date de la qualification (TP0)


# modèle Hamlib -> lecture validée. Un modèle absent : TOT « unknown » (rappel à la configuration seulement).
RIG_TOT: dict[int, CivTot] = {
    # Icom IC-7300MK2 (manuel CI-V « SET > Function > Time-Out Timer (CI-V) » ; lot TP0 du 2026-11-20 : six valeurs
    # lues, poste éteint = délai dépassé, coupure seule du poste à 180,0 s). Le manuel : valable SEULEMENT pour une
    # émission lancée par une commande CI-V ou la touche TRANSMIT => PTT de la station par la CAT (« RIG »).
    3094: CivTot("Icom IC-7300MK2", 0xB6, b"\x00\x32", {0: 0, 1: 3, 2: 5, 3: 10, 4: 20, 5: 30}, ("RIG",), "2026-11-20"),
    # Icom IC-705 (étape 402) : D'APRÈS le guide CI-V (IC-705 CI-V Reference Guide 2020-07-21, menu « 0043 Time-Out
    # Timer », mêmes valeurs ; adresse d'usine A4h, comme Hamlib) ; PAS ENCORE MESURÉ sur le poste (TP0 à faire).
    3085: CivTot("Icom IC-705", 0xA4, b"\x00\x43", {0: 0, 1: 3, 2: 5, 3: 10, 4: 20, 5: 30}, ("RIG",), ""),
}

_HEX = re.compile(r"\\0x([0-9A-Fa-f]{2})")


def civ_command(entry: CivTot) -> str:
    """Commande rigctld « W » : trame de lecture et nombre d'octets attendus (écho CI-V + réponse)."""
    frame = bytes([0xFE, 0xFE, entry.address, CONTROLLER, 0x1A, 0x05]) + entry.menu + b"\xFD"
    reply_len = len(frame) + len(frame) + 1          # écho (même trame) + réponse (une donnée de plus)
    return "W " + "".join(f"\\0x{b:02X}" for b in frame) + f" {reply_len}"


def parse_civ_reply(entry: CivTot, text: str) -> int | None:
    """Code lu dans la réponse de rigctld (octets « \\0xFE… ») : seulement la trame ADRESSÉE AU CONTRÔLEUR par le poste
    (l'écho de la demande vient d'abord) ; None si absente, mal formée ou valeur inconnue."""
    data = [int(h, 16) for h in _HEX.findall(text or "")]
    head = [0xFE, 0xFE, CONTROLLER, entry.address, 0x1A, 0x05, *entry.menu]
    n = len(head)
    found = None
    for i in range(len(data) - n - 1):
        if data[i:i + n] == head and data[i + n + 1] == 0xFD:
            if found is not None and found != data[i + n]:
                return None                            # deux réponses différentes dans la même lecture
            found = data[i + n]
    return found if found in entry.minutes else None


@dataclass
class TotReading:
    state: str                        # "on", "off" ou "unknown"
    minutes: int | None = None        # durée réglée quand state == "on"
    reason: str = ""                  # pourquoi « unknown » : model, ptt, silent, unreadable, unstable, busy
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


async def read_tot(client, model: int, ptt_type: str) -> TotReading:
    """Lecture « à coup sûr » par le client rigctld de la station (`RigctldClient`). Jamais d'exception."""
    entry = RIG_TOT.get(model)
    if entry is None:
        return TotReading("unknown", reason="model")
    if ptt_type not in entry.ptt_types:
        return TotReading("unknown", reason="ptt")
    try:
        await client.get_frequency()                   # le poste répond-il en ce moment ?
    except Exception:                                  # noqa: BLE001 : poste muet, liaison perdue
        return TotReading("unknown", reason="silent")
    codes = []
    for _ in range(2):
        try:
            text = await client.send_raw(civ_command(entry))
        except Exception:                              # noqa: BLE001 : refus (RPRT), délai, liaison
            return TotReading("unknown", reason="unreadable")
        code = parse_civ_reply(entry, text)
        if code is None:
            return TotReading("unknown", reason="unreadable")
        codes.append(code)
    if codes[0] != codes[1]:
        return TotReading("unknown", reason="unstable")
    minutes = entry.minutes[codes[0]]
    return TotReading("off") if minutes == 0 else TotReading("on", minutes=minutes)


class RigTotStore:
    """Dernière lecture (trx-monitor) et jour du dernier avis par compte (une fois par jour, décision du 2026-11-20).
    Fichier `state_dir/rig_tot.json` ; une écriture ratée ne gêne jamais la connexion."""

    def __init__(self, path: str | Path, today=None):
        self.path = Path(path)
        self._today = today or (lambda: _dt.date.today().isoformat())
        self.last: TotReading | None = None
        self._shown: dict[str, str] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            shown = data.get("shown") if isinstance(data, dict) else None
            if isinstance(shown, dict):
                self._shown = {str(k): str(v) for k, v in shown.items() if isinstance(v, str)}
        except (OSError, ValueError):
            pass

    def snapshot(self) -> dict:
        return self.last.to_dict() if self.last is not None else {}

    def record(self, reading: TotReading) -> None:
        self.last = reading

    def due(self, account: str) -> bool:
        """L'avis « TOT sur OFF » n'a pas encore été donné aujourd'hui à ce compte."""
        return self._shown.get(account) != self._today()

    def shown(self, account: str) -> None:
        self._shown[account] = self._today()
        self._shown = {k: v for k, v in self._shown.items() if v == self._today()}   # les jours passés ne servent plus
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"shown": self._shown}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass
