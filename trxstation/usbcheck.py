# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Ports USB de la station (Linux) : les périphériques sont-ils bien répartis ? (étape 384)

LECTURE SEULE de /sys/bus/usb/devices, bibliothèque standard, aucun port ouvert. Pour chaque bus (un contrôleur, ou la
moitié USB 2 / USB 3 d'un contrôleur) : périphériques, vitesse négociée, débit ESTIMÉ. Une prise USB 3 (bleue) ne donne
rien de plus à un périphérique USB 2 : il passe par la moitié USB 2 du contrôleur, 480 Mbit/s partagés.

Débits estimés (les seuls qui comptent sur une station) :
- SDR : SDRplay (1df7:*) 4 octets par échantillon, RTL-SDR 2 octets ; largeur du SDR de la station (`sdr_fs`), même
  valeur pour un SDR d'une autre application (débit inconnu : estimation prudente) ;
- carte son (classe audio) : 3 Mbit/s ; le reste (CAT, Bluetooth, clavier…) : négligeable, non compté.
Utilisable sur un bus USB 2 : ~280 Mbit/s (le reste part en protocole).

Constats (`code`, `level`, champs), textes à la charge de l'affichage (tableau de bord, diagnostic) :
- `saturated` (bad) / `busy` (warn) : bus estimé à 100 % / 70 % de l'utilisable ;
- `sdr_slow` (bad) : SDR (480 Mbit/s attendus) négocié plus lentement : hub ou câble USB 1.1 ;
- `sdr_on_rig_hub` (warn) : SDR derrière le même hub que le poste (déconseillé par le guide) ;
- `hub_power` (warn) : hub alimenté par le bus dont les périphériques déclarent plus de 500 mA.
Les numéros de série ne sortent jamais d'ici (comparés seulement à celui du SDR de la station).
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

SDRPLAY_VENDOR = "1df7"
RTLSDR_IDS = {("0bda", "2838"), ("0bda", "2832")}
USB2_USABLE_MBIT = 280.0
AUDIO_MBIT = 3.0
BUSY_PCT, SATURATED_PCT = 70.0, 100.0
BUS_POWER_MA = 500
DEFAULT_SDR_FS = 2_000_000
CACHE_S = 10.0


@dataclass
class Device:
    path: str                     # « 3-2.1 »
    bus: int
    speed: float                  # Mbit/s négociés
    kind: str                     # sdr | audio | rig | hub | other
    name: str                     # produit ou « vendeur:produit »
    mbit: float = 0.0             # débit estimé
    max_ma: int = 0
    parent: str | None = None     # hub parent (None : prise du contrôleur)
    station_sdr: bool = False


@dataclass
class Bus:
    number: int
    speed: float                  # Mbit/s du bus (480 = USB 2, 5000+ = USB 3)
    devices: list[Device] = field(default_factory=list)

    @property
    def mbit(self) -> float:
        return sum(d.mbit for d in self.devices)

    @property
    def usable(self) -> float:
        return USB2_USABLE_MBIT if self.speed <= 480 else self.speed * 0.6

    @property
    def load_pct(self) -> float:
        return 100.0 * self.mbit / self.usable if self.usable else 0.0


@dataclass
class Finding:
    code: str
    level: str                    # warn | bad
    fields: dict = field(default_factory=dict)


@dataclass
class UsbReport:
    buses: list[Bus]
    findings: list[Finding]

    @property
    def level(self) -> str:
        levels = {f.level for f in self.findings}
        return "bad" if "bad" in levels else "warn" if "warn" in levels else "ok"

    @property
    def busiest(self) -> Bus | None:
        loaded = [b for b in self.buses if b.devices]
        return max(loaded, key=lambda b: b.load_pct) if loaded else None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _int(text: str, default: int = 0) -> int:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else default


def _float(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 0.0


def _interface_classes(dev: Path) -> set[str]:
    classes = set()
    try:
        for sub in dev.iterdir():
            if (sub / "bInterfaceClass").is_file():          # « 3-2.1:1.0 » ; un sous-périphérique n'en a pas
                classes.add(_read(sub / "bInterfaceClass"))
    except OSError:
        pass
    return classes


def rig_device_path(rig_port: str | None, sys_root: Path) -> str | None:
    """Nom sysfs (« 3-2.1 ») du périphérique USB qui porte le port CAT du poste, ou None."""
    if not rig_port:
        return None
    try:
        tty = os.path.basename(os.path.realpath(rig_port))
        here = Path(os.path.realpath(sys_root / "class" / "tty" / tty / "device"))
    except OSError:
        return None
    for _ in range(4):
        if (here / "idVendor").exists():
            return here.name
        here = here.parent
    return None


def analyze(sys_root: str | Path = "/sys", *, rig_port: str | None = None, sdr_serial: str = "",
            sdr_fs: int | None = None) -> UsbReport | None:
    """Relevé des ports USB, ou None hors Linux (pas de /sys/bus/usb)."""
    root = Path(sys_root)
    base = root / "bus" / "usb" / "devices"
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return None
    fs = sdr_fs or DEFAULT_SDR_FS
    rig = rig_device_path(rig_port, root)
    buses: dict[int, Bus] = {}
    devices: dict[str, Device] = {}
    hubs_self_powered: dict[str, bool] = {}
    for entry in entries:                                    # racines d'abord : vitesse du bus
        if entry.name.startswith("usb") and (entry / "idVendor").exists():
            bus = _int(_read(entry / "busnum"))
            buses[bus] = Bus(bus, _float(_read(entry / "speed")))
    for entry in entries:
        if entry.name.startswith("usb") or not (entry / "idVendor").exists():
            continue
        bus = _int(_read(entry / "busnum"))
        speed = _float(_read(entry / "speed"))
        vendor, product = _read(entry / "idVendor"), _read(entry / "idProduct")
        classes = _interface_classes(entry)
        parent = entry.name.rsplit(".", 1)[0] if "." in entry.name else None
        name = _read(entry / "product") or f"{vendor}:{product}"
        dev = Device(entry.name, bus, speed, "other", name, max_ma=_int(_read(entry / "bMaxPower")), parent=parent)
        if vendor == SDRPLAY_VENDOR or (vendor, product) in RTLSDR_IDS:
            dev.kind = "sdr"
            dev.name = name if name != f"{vendor}:{product}" else ("SDRplay" if vendor == SDRPLAY_VENDOR else "RTL-SDR")
            dev.station_sdr = bool(sdr_serial) and _read(entry / "serial") == sdr_serial
            dev.mbit = fs * (32 if vendor == SDRPLAY_VENDOR else 16) / 1e6
        elif _read(entry / "bDeviceClass") == "09":
            dev.kind = "hub"
            try:
                attrs = int(_read(entry / "bmAttributes") or "0", 16)     # sysfs : hexadécimal (« e0 »)
            except ValueError:
                attrs = 0
            hubs_self_powered[entry.name] = bool(attrs & 0x40)          # bit 6 : alimenté par son bloc secteur
        elif "01" in classes:
            dev.kind = "audio"
            dev.mbit = AUDIO_MBIT
        if entry.name == rig:
            dev.kind = "rig"
        devices[entry.name] = dev
        buses.setdefault(bus, Bus(bus, speed)).devices.append(dev)
    findings: list[Finding] = []
    for b in sorted(buses.values(), key=lambda b: b.number):
        if not b.devices or b.mbit <= 0:
            continue
        pct = round(b.load_pct)
        if b.load_pct >= SATURATED_PCT:
            findings.append(Finding("saturated", "bad", {"bus": b.number, "mbit": round(b.mbit), "usable": round(b.usable),
                                                         "pct": pct}))
        elif b.load_pct >= BUSY_PCT:
            findings.append(Finding("busy", "warn", {"bus": b.number, "mbit": round(b.mbit), "usable": round(b.usable),
                                                     "pct": pct}))
    rig_hub = devices[rig].parent if rig in devices else None
    for d in devices.values():
        if d.kind != "sdr":
            continue
        if 0 < d.speed < 480:
            findings.append(Finding("sdr_slow", "bad", {"name": d.name, "port": d.path, "speed": f"{d.speed:g}"}))
        if rig_hub is not None and d.parent == rig_hub:
            findings.append(Finding("sdr_on_rig_hub", "warn", {"name": d.name, "port": d.path}))
    for hub, self_powered in hubs_self_powered.items():
        if self_powered:
            continue
        total = sum(d.max_ma for d in devices.values() if d.parent == hub)
        if total > BUS_POWER_MA:
            findings.append(Finding("hub_power", "warn", {"port": hub, "ma": total, "max": BUS_POWER_MA}))
    return UsbReport(sorted(buses.values(), key=lambda b: b.number), findings)


def cached_reader(sys_root: str | Path = "/sys", *, rig_port: str | None = None, sdr_serial: str = "",
                  sdr_fs: Callable[[], int | None] | int | None = None,
                  clock: Callable[[], float] = time.monotonic) -> Callable[[], UsbReport | None]:
    """Relevé gardé CACHE_S secondes (le tableau de bord se rafraîchit plusieurs fois par seconde)."""
    memo: dict = {"at": -1e18, "report": None}

    def read() -> UsbReport | None:
        now = clock()
        if now - memo["at"] >= CACHE_S:
            fs = sdr_fs() if callable(sdr_fs) else sdr_fs
            try:
                memo["report"] = analyze(sys_root, rig_port=rig_port, sdr_serial=sdr_serial, sdr_fs=fs)
            except Exception:                                # jamais de panne du tableau de bord pour ce relevé
                memo["report"] = None
            memo["at"] = now
        return memo["report"]
    return read


def for_config(cfg) -> dict:
    """Arguments d'`analyze` tirés de station.toml : port CAT du poste, SDR de la station (largeur PLAFOND : le pire
    cas, même SDR en veille)."""
    sd = getattr(cfg, "sdr", None)
    on = bool(sd is not None and sd.enabled)
    return {"rig_port": getattr(cfg.rig, "port", None) or None, "sdr_serial": sd.serial if on else "",
            "sdr_fs": sd.sample_rate_hz if on else None}


# --------------------------------------------------------------------------- textes (catalogue « monitor », 4 langues)

def finding_text(finding: Finding, t: Callable[..., str]) -> str:
    return t(f"usb.{finding.code}", **finding.fields)


def summary(report: UsbReport, t: Callable[..., str]) -> tuple[str, str]:
    """(texte, niveau ok | warn | bad) de la ligne « Ports USB » de la carte ORDINATEUR."""
    if report.findings:
        worst = sorted(report.findings, key=lambda f: f.level != "bad")
        text = finding_text(worst[0], t)
        if len(worst) > 1:
            text += t("usb.more", n=len(worst) - 1)
        return text, report.level
    busiest = report.busiest
    if busiest is None or busiest.mbit <= 0:
        return t("usb.ok"), "ok"
    return t("usb.ok_load", pct=round(busiest.load_pct)), "ok"


def speed_text(bus: Bus, t: Callable[..., str]) -> str:
    if bus.speed == 480:
        return t("usb.speed_usb2")
    if bus.speed >= 5000:
        return t("usb.speed_usb3", gbit=f"{bus.speed / 1000:g}")
    return t("usb.speed_other", speed=f"{bus.speed:g}")


def device_text(dev: Device, t: Callable[..., str]) -> str:
    key = "sdr_station" if dev.kind == "sdr" and dev.station_sdr else dev.kind
    return t(f"usb.dev.{key}", name=dev.name)


def bus_lines(report: UsbReport, t: Callable[..., str]) -> list[str]:
    """Une ligne par bus qui porte un périphérique compté (poste, son, SDR) : détail du diagnostic."""
    lines = []
    for b in report.buses:
        shown = [d for d in b.devices if d.kind in ("rig", "sdr", "audio")]
        if not shown:
            continue
        lines.append(t("usb.bus_line", bus=b.number, speed=speed_text(b, t),
                       devices=", ".join(device_text(d, t) for d in shown), mbit=round(b.mbit), pct=round(b.load_pct)))
    return lines
