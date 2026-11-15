# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Liste des SDR de la machine et commande `trx-sdr` (lecture seule : n'ouvre AUCUN SDR).

L'API du fabricant ne liste que les SDR LIBRES (essai S0 : celui d'une autre application n'apparaît pas) ; on croise
donc avec les appareils USB du fabricant vus par le noyau (Linux, sysfs) pour signaler « présent mais pris ».
Le numéro de série retenu est celui de l'API : sysfs le montre parfois en retard (le RSP s'énumère sans numéro).
"""
from __future__ import annotations

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
    local = Path(sys.executable).with_name(name)
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
    if data.get("error"):
        return [], "service du fabricant injoignable" if data["error"] == "service" else str(data["error"])
    devices = [d for d in data.get("devices", []) if isinstance(d, dict) and isinstance(d.get("serial"), str)]
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-sdr", description="SDR de la machine (lecture seule : n'ouvre aucun SDR)")
    ap.add_argument("--list", action="store_true", help="liste des SDR (par défaut)")
    ap.add_argument("--core", default="", help="chemin de sdr-core (défaut : installé avec la station)")
    ap.add_argument("--json", action="store_true", help="sortie JSON")
    args = ap.parse_args(argv)
    core = core_path(args.core)
    api, error = api_devices(core) if core else ([], "sdr-core introuvable (installer l'API du fabricant puis la station)")
    devices = merge(api, usb_devices())
    if args.json:
        print(json.dumps({"error": error, "devices": [d.__dict__ for d in devices]}, ensure_ascii=False))
        return 0 if not error else 1
    if error:
        print(f"Attention : {error}")
    if not devices:
        print("Aucun SDR vu sur cette machine.")
        return 1 if error else 0
    print(f"{'Numéro de série':<18} {'État':<38} Port USB")
    for d in devices:
        state = "libre" if d.state == "libre" else "pris par une autre application"
        print(f"{d.serial:<18} {state:<38} {d.usb_port or '—'}")
    print("\nPour cette station : [sdr] serial = \"<numéro>\" dans station.toml (jamais celui d'un SDR pris).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
