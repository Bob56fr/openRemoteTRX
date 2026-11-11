# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Activité FreeDV par fréquence, d'après FreeDV Reporter (qso.freedv.org) lu en OBSERVATEUR : calculs purs.

`ReporterState` tient la liste des stations connectées au service, à partir de ses événements (`new_connection`,
`freq_change`, `tx_report`, `rx_report`, `message_update`, `remove_connection`) ; tout ce qui vient du réseau est
borné et vérifié (nombre de stations, longueur et forme des textes, nombres). `snapshot()` rend le message envoyé
aux clients : l'activité HF (1,8 à 29,7 MHz) regroupée par fréquence (pas de 500 Hz), avec une note de chance de
réception CHEZ NOUS (RADE V1 seulement) :

- une station qui émet en ce moment compte 2, une qui a émis dans les 15 dernières minutes 1 ; × 0,4 au-delà de
  3 000 km de la station (ou distance inconnue) ;
- un voisin (moins de 1 500 km) qui décode en ce moment avec un SNR d'au moins 3 dB ajoute 3 (moins de 800 km)
  ou 2 : la propagation vient jusqu'à nous.

Les distances demandent le locator de la station (`[freedv] locator`) ; sans lui, elles sont absentes.
"""
from __future__ import annotations

import datetime as _dt
import math
import re

HF_MIN_HZ, HF_MAX_HZ = 1_800_000, 29_700_000
GROUP_HZ = 500
TX_RECENT_S = 15 * 60
RX_RECENT_S = 180
MAX_STATIONS = 3000
MAX_FREQS = 20
MAX_TX, MAX_RX = 8, 6
NEAR_TX_KM, NEAR_RX_KM, VERY_NEAR_RX_KM = 3000, 1500, 800
RADE_V1 = "RADEV1"
EVENTS = ("new_connection", "freq_change", "tx_report", "rx_report", "message_update", "remove_connection")

_GRID = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$")
_CALL = re.compile(r"[^A-Z0-9/\-]")
_MODE = re.compile(r"[^A-Za-z0-9_\-]")


def valid_locator(grid: str) -> bool:
    return bool(_GRID.match(str(grid or "").strip().upper()))


def locator_latlon(grid: str) -> tuple[float, float] | None:
    """Centre du carré Maidenhead (4 ou 6 caractères), en degrés ; None s'il est illisible."""
    g = str(grid or "").strip().upper()[:6]
    if len(g) == 6 and not _GRID.match(g):
        g = g[:4]
    if not _GRID.match(g):
        return None
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2 + 1
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3]) + 0.5
    if len(g) == 6:
        lon += (ord(g[4]) - 65) / 12 - 1 + 1 / 24
        lat += (ord(g[5]) - 65) / 24 - 0.5 + 1 / 48
    return lat, lon


def distance_km(a: str, b: str) -> int | None:
    pa, pb = locator_latlon(a), locator_latlon(b)
    if pa is None or pb is None:
        return None
    p1, p2, dl = math.radians(pa[0]), math.radians(pb[0]), math.radians(pb[1] - pa[1])
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return round(6371 * math.acos(max(-1.0, min(1.0, c))))


def clean_call(v) -> str:
    return _CALL.sub("", str(v or "").upper())[:12]


def clean_mode(v) -> str:
    return _MODE.sub("", str(v or ""))[:12]


def iso_time(v) -> float | None:
    """Heure ISO 8601 de FreeDV Reporter -> heure Unix ; None si illisible."""
    if not isinstance(v, str) or len(v) > 40:
        return None
    try:
        t = _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return t.timestamp()


def _int(v, lo: int, hi: int) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    v = int(v)
    return v if lo <= v <= hi else None


class ReporterState:
    """Stations connectées à FreeDV Reporter (clé : `sid` de la connexion), tenues à jour par ses événements."""

    def __init__(self) -> None:
        self.stations: dict[str, dict] = {}
        self.rx: dict[str, tuple[float | None, int | None, str, str]] = {}   # sid -> (heure, snr, indicatif entendu, mode)

    def clear(self) -> None:
        self.stations.clear()
        self.rx.clear()

    def apply(self, name: str, data) -> None:
        if name not in EVENTS or not isinstance(data, dict):
            return
        sid = data.get("sid")
        if not isinstance(sid, str) or not 0 < len(sid) <= 64:
            return
        if name == "remove_connection":
            self.stations.pop(sid, None)
            self.rx.pop(sid, None)
            return
        if name == "rx_report":
            if sid in self.stations or len(self.stations) < MAX_STATIONS:
                self.rx[sid] = (iso_time(data.get("last_update")), _int(data.get("snr"), -50, 60),
                                clean_call(data.get("callsign")), clean_mode(data.get("mode")))
            return
        st = self.stations.get(sid)
        if st is None:
            if len(self.stations) >= MAX_STATIONS:
                return
            st = self.stations[sid] = {}
        for key in ("callsign", "grid_square", "mode"):
            if key in data:
                st[key] = clean_call(data[key]) if key == "callsign" else clean_mode(data[key])[:6 if key == "grid_square" else 12]
        if "freq" in data:
            st["freq"] = _int(data.get("freq"), 0, 1_000_000_000) or 0
        if "transmitting" in data:
            st["transmitting"] = data.get("transmitting") is True
        if "last_tx" in data:
            st["last_tx"] = iso_time(data.get("last_tx"))

    def snapshot(self, now: float, my_grid: str = "") -> list[dict]:
        """Activité HF par fréquence, la plus prometteuse en tête (MAX_FREQS au plus ; clés courtes)."""
        groups: dict[int, dict] = {}
        for sid, s in self.stations.items():
            f = s.get("freq") or 0
            if not HF_MIN_HZ <= f <= HF_MAX_HZ:
                continue
            key = round(f / GROUP_HZ) * GROUP_HZ
            g = groups.setdefault(key, {"f": key, "note": 0.0, "tx": [], "rx": []})
            km = distance_km(my_grid, s.get("grid_square") or "") if my_grid else None
            call = s.get("callsign") or "?"
            last_tx = s.get("last_tx")
            emits = bool(s.get("transmitting"))
            ago = now - last_tx if last_tx else None
            if emits or (ago is not None and 0 <= ago <= TX_RECENT_S):
                mode = s.get("mode") or ""
                g["tx"].append({"c": call, "km": km, "on": emits, "min": None if emits else round(ago / 60), "m": mode})
                if mode == RADE_V1:
                    g["note"] += (2.0 if emits else 1.0) * (1.0 if km is not None and km < NEAR_TX_KM else 0.4)
            rx = self.rx.get(sid)
            if rx and rx[0] is not None and 0 <= now - rx[0] < RX_RECENT_S and rx[1] is not None:
                g["rx"].append({"c": call, "km": km, "snr": rx[1], "m": rx[3]})
                if rx[3] == RADE_V1 and km is not None and km < NEAR_RX_KM and rx[1] >= 3:
                    g["note"] += 3.0 if km < VERY_NEAR_RX_KM else 2.0
        out = [g for g in groups.values() if g["tx"] or g["rx"]]
        for g in out:
            g["tx"].sort(key=lambda t: (not t["on"], t["min"] or 0))
            g["rx"].sort(key=lambda r: r["km"] if r["km"] is not None else 1e9)
            g["tx"], g["rx"] = g["tx"][:MAX_TX], g["rx"][:MAX_RX]
            g["note"] = round(g["note"], 1)
        out.sort(key=lambda g: (-g["note"], -len(g["tx"]), g["f"]))
        return out[:MAX_FREQS]
