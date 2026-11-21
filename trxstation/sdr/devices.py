# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Liste des SDR de la machine et commande `trx-sdr` (lecture seule : n'ouvre AUCUN SDR).

L'API du fabricant ne liste que les SDR LIBRES (essai S0 : celui d'une autre application n'apparaît pas) ; on croise
donc avec les appareils USB du fabricant vus par le noyau (Linux, sysfs) pour signaler « présent mais pris ».
Le numéro de série retenu est celui de l'API : sysfs le montre parfois en retard (le RSP s'énumère sans numéro).
"""
from __future__ import annotations

from ..crashguard import guarded

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

VENDOR_IDS = {"1df7": "SDRplay"}
LIST_TIMEOUT_S = 15.0

# Recherche USB (étape 196) : SDR reconnus par leur identifiant USB, sur TOUS les ports, hubs compris.
SDRPLAY_MODELS = {"2500": "RSP1", "3000": "RSP1A", "3010": "RSP2 / RSP2pro", "3020": "RSPduo", "3050": "RSPdx"}
RTL_IDS = {("0bda", "2838"), ("0bda", "2832")}        # puce RTL2832U (clés RTL-SDR, dont la RTL-SDR Blog V4)
RADIO_VENDORS = {"0c26", "10c4"}                       # Icom ; ponts CP210x des Yaesu : « même hub que le poste »
TV_DRIVERS = ("dvb_usb_rtl28xxu", "rtl2832", "rtl2830")


@dataclass(frozen=True)
class Device:
    serial: str
    state: str           # "libre" (l'API le propose) ou "pris" (vu par le noyau, absent de l'API)
    hw: int | None = None
    usb_port: str = ""


def core_path(configured: str = "") -> str | None:
    """Programme sdr-core : réglé, sinon à côté de l'interpréteur (venv/bin, installé par install.sh), sinon le PATH."""
    if configured:
        return configured if (os.path.sep in configured or "/" in configured) else shutil.which(configured)
    name = "sdr-core.exe" if os.name == "nt" else "sdr-core"
    from ..packaging import python_executable
    local = Path(python_executable()).with_name(name)
    if local.is_file():
        return str(local)
    return shutil.which(name)


def api_devices(core: str, run=subprocess.run) -> tuple[list[dict], str]:
    """(SDR libres selon l'API, erreur lisible ou "")."""
    try:
        done = run([core, "--list"], capture_output=True, timeout=LIST_TIMEOUT_S, text=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"sdr-core injoignable : {exc}"
    try:
        data = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        return [], "réponse de sdr-core illisible"
    devices = [d for d in data.get("devices", []) if isinstance(d, dict) and isinstance(d.get("serial"), str)]
    if data.get("error"):                     # service SDRplay injoignable : les clés RTL-SDR listées restent valables
        error = "service du fabricant injoignable" if data["error"] == "service" else str(data["error"])
        return [d for d in devices if d.get("driver") == "rtlsdr"], error
    return devices, ""


def usb_devices(sysfs: Path = Path("/sys/bus/usb/devices")) -> list[dict]:
    """SDR du fabricant vus par le noyau (Linux) : [{"serial", "port", "vendor"}] ; vide ailleurs."""
    found = []
    if not sysfs.is_dir():
        return found
    for dev in sorted(sysfs.iterdir()):
        try:
            vid = (dev / "idVendor").read_text().strip()
        except OSError:
            continue
        if vid in VENDOR_IDS:
            try:
                serial = (dev / "serial").read_text().strip()
            except OSError:
                serial = ""
            found.append({"serial": serial, "port": dev.name, "vendor": VENDOR_IDS[vid]})
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return ""


def location_text(name: str) -> str:
    """« 3-2.1 » -> « bus 3, port 2 -> hub, port 1 » (nom sysfs : bus-port[.port du hub]…)."""
    bus, _, path = name.partition("-")
    ports = path.split(".") if path else []
    if not ports:
        return name
    text = f"bus {bus}, port {ports[0]}"
    for p in ports[1:]:
        text += f" -> hub, port {p}"
    return text


def _holder(busnum: str, devnum: str, proc: Path) -> str:
    """Programme qui tient l'appareil (/dev/bus/usb/BBB/DDD ouvert), "" si aucun trouvé, "?" si illisible (droits)."""
    try:
        target = f"/dev/bus/usb/{int(busnum):03d}/{int(devnum):03d}"
        pids = [p for p in proc.iterdir() if p.name.isdigit()]
    except (ValueError, OSError):
        return "?"
    unreadable = False
    for pid in pids:
        try:
            for fd in (pid / "fd").iterdir():
                try:
                    if os.readlink(fd) == target:
                        return _read(pid / "comm") or pid.name
                except OSError:
                    continue
        except PermissionError:
            unreadable = True
        except OSError:
            continue
    return "?" if unreadable else ""


def driver_of(sysfs: Path, name: str) -> str:
    """Pilote de la première interface (« usbfs » = tenue par un programme), "" sans pilote."""
    iface = sysfs / f"{name}:1.0" / "driver"
    return os.path.basename(os.path.realpath(iface)) if iface.exists() else ""


def scan_usb(sysfs: Path = Path("/sys/bus/usb/devices"), proc: Path = Path("/proc")) -> list[dict]:
    """Tous les SDR reconnus vus par le noyau (Linux), sur tous les ports, hubs compris, SANS en ouvrir aucun :
    [{"kind", "model", "serial", "name", "location", "driver", "holder", "radio_hub"}] ; vide ailleurs."""
    found: list[dict] = []
    if not sysfs.is_dir():
        return found
    seen = {}
    for dev in sorted(sysfs.iterdir()):
        vid = _read(dev / "idVendor")
        if vid and ":" not in dev.name:
            seen[dev.name] = (vid, _read(dev / "idProduct"), dev)
    for name, (vid, pid, dev) in seen.items():
        if vid == "1df7":
            kind, model = "sdrplay", SDRPLAY_MODELS.get(pid, "SDRplay")
        elif (vid, pid) in RTL_IDS:
            kind = "rtlsdr"
            label = " ".join(x for x in (_read(dev / "manufacturer"), _read(dev / "product")) if x)
            model = f"RTL-SDR ({label})" if label else "RTL-SDR (RTL2832U)"
        else:
            continue
        driver = driver_of(sysfs, name)
        parent = name.rsplit(".", 1)[0] if "." in name else ""
        radio_hub = bool(parent) and any(n.startswith(parent + ".") and v in RADIO_VENDORS
                                         for n, (v, _p, _d) in seen.items() if n != name)
        holder = _holder(_read(dev / "busnum"), _read(dev / "devnum"), proc) if kind == "rtlsdr" and driver == "usbfs" else ""
        found.append({"kind": kind, "model": model, "serial": _read(dev / "serial"), "name": name,
                      "location": location_text(name), "driver": driver, "holder": holder, "radio_hub": radio_hub})
    return found


def scan(core: str | None, configured: str = "", *, sysfs: Path = Path("/sys/bus/usb/devices"),
         proc: Path = Path("/proc"), run=subprocess.run) -> tuple[list[dict], list[str]]:
    """Recherche complète, en LECTURE SEULE : (SDR trouvés avec leur état, avertissements).
    État : "libre", "pris" (avec `holder` si connu), "noyau" (pilote TV du noyau), "station" ([sdr] serial), "?".
    SDRplay : le service du fabricant tient tous les RSP ouverts ; seuls ceux que son API PROPOSE sont libres."""
    warnings: list[str] = []
    usb = scan_usb(sysfs, proc)
    api, error = api_devices(core, run) if core else ([], "sdr-core introuvable")
    if error and any(u["kind"] == "sdrplay" for u in usb):
        warnings.append(f"SDRplay : {error} (état des RSP inconnu)")
    free = {d["serial"] for d in api if d.get("driver", "sdrplay") == "sdrplay"}
    out = []
    for u in usb:
        if u["kind"] == "sdrplay":
            state = "libre" if u["serial"] in free else ("?" if error else "pris")
        elif u["driver"] in TV_DRIVERS:
            state = "noyau"
        elif u["driver"] == "usbfs":
            state = "pris"
        else:
            state = "libre"
        if configured and u["serial"] == configured and state != "noyau":
            state = "station"
        out.append({**u, "state": state})
    for d in api:                                          # proposé par l'API sans être vu par le noyau (Windows)
        if not any(o["serial"] == d["serial"] for o in out):
            rtl = d.get("driver") == "rtlsdr"
            out.append({"kind": "rtlsdr" if rtl else "sdrplay",
                        "model": f"RTL-SDR ({d.get('product') or 'RTL2832U'})" if rtl else "SDRplay",
                        "serial": d["serial"], "name": "", "location": "",
                        "driver": "", "holder": "", "radio_hub": False,
                        "state": "station" if d["serial"] == configured else "libre"})
    serials = [o["serial"] for o in out if o["serial"]]
    doubles = {s for s in serials if serials.count(s) > 1}
    for s in sorted(doubles):
        warnings.append(f"numéro de série {s} en DOUBLE : ces SDR ne peuvent pas être distingués (RTL-SDR : en "
                        "réécrire un, voir le guide)")
    for o in out:
        o["duplicate"] = o["serial"] in doubles
        name = f"{o['model']} {o['serial']}".strip()
        if o["radio_hub"]:
            warnings.append(f"{name} branché sur le MÊME hub que le poste : à déplacer sur son propre port")
        if o["state"] == "noyau":
            warnings.append(f"{name} tenu par le pilote TV du noyau ({o['driver']}) : à écarter "
                            "(l'installation de la station le fait)")
    return out, warnings


STATE_TEXT = {"libre": "libre", "pris": "pris par un programme", "noyau": "pris par le pilote TV du noyau",
              "station": "SDR DE CETTE STATION", "?": "état inconnu"}


def merge(api: list[dict], usb: list[dict]) -> list[Device]:
    """Libres = ceux de l'API ; pris = vus sur l'USB mais absents de l'API (numéro lisible ou non)."""
    free = {d["serial"] for d in api}
    ports = {u["serial"]: u["port"] for u in usb if u["serial"]}
    out = [Device(d["serial"], "libre", d.get("hw"), ports.get(d["serial"], "")) for d in api]
    for u in usb:
        if u["serial"] in free:
            continue
        out.append(Device(u["serial"] or "?", "pris", None, u["port"]))
    return out


@guarded("trx-sdr")
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-sdr", description="SDR de la machine (lecture seule : n'ouvre aucun SDR)")
    ap.add_argument("--list", action="store_true", help="liste des SDR (par défaut)")
    ap.add_argument("--core", default="", help="chemin de sdr-core (défaut : installé avec la station)")
    ap.add_argument("--json", action="store_true", help="sortie JSON")
    ap.add_argument("--serial", default="", help="numéro du SDR de cette station (marqué dans la liste)")
    args = ap.parse_args(argv)
    found, warnings = scan(core_path(args.core), args.serial)
    if args.json:
        print(json.dumps({"devices": found, "warnings": warnings}, ensure_ascii=False))
        return 0
    if not found:
        print("Aucun SDR reconnu sur cette machine (SDRplay, RTL-SDR), sur aucun port USB ni hub.")
    else:
        print(f"{'N°':<3} {'Type':<30} {'Numéro de série':<16} {'État':<32} Emplacement USB")
        for i, d in enumerate(found, 1):
            holder = d.get("holder") or ""
            state = STATE_TEXT.get(d["state"], d["state"]) + (f" ({holder})" if holder not in ("", "?") else "")
            print(f"{i:<3} {d['model'][:30]:<30} {(d['serial'] or '—')[:16]:<16} {state[:32]:<32} {d['location'] or '—'}")
    for w in warnings:
        print(f"Attention : {w}")
    if os.name == "nt":
        print("Windows : recherche par l'API du fabricant seulement (SDRplay) ; les clés RTL-SDR ne sont pas encore vues.")
    print("\nLe SDR de la station se choisit par son NUMÉRO DE SÉRIE (openRemoteTRX Console, menu 2.4), jamais celui d'un SDR pris.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
