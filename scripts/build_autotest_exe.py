# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique l'EXE Windows d'openRemoteTRX-Autotest (mode B) avec Nuitka : dist/openRemoteTRX-Autotest-X.Y.Z.exe.

À lancer avec un Python qui a nuitka, aiohttp et pyserial (un venv à part suffit :
`python -m venv venv-autotest && venv-autotest\\Scripts\\pip install nuitka aiohttp pyserial`) :
    venv-autotest\\Scripts\\python scripts\\build_autotest_exe.py
La page (autotest/web) est embarquée dans l'EXE. Refus si un module manque : sans pyserial, la liste des ports
série serait vide sans le dire (défaut de l'EXE 0.8.0). L'EXE n'est pas signé (avertissement de SmartScreen)."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"nuitka": "nuitka", "aiohttp": "aiohttp", "serial": "pyserial"}


def version() -> str:
    text = (ROOT / "autotest" / "web" / "report.js").read_text(encoding="utf-8")
    found = re.search(r'const VERSION = "(\d+\.\d+\.\d+)"', text)
    if not found:
        raise SystemExit("Version d'openRemoteTRX-Autotest introuvable dans autotest/web/report.js.")
    return found.group(1)


def main() -> int:
    missing = [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]
    if missing:
        print("Modules manquants dans ce Python : " + ", ".join(missing) + f"\n  {sys.executable} -m pip install " + " ".join(missing))
        return 1
    v = version()
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    name = f"openRemoteTRX-Autotest-{v}.exe"
    cmd = [sys.executable, "-m", "nuitka", "--onefile", "--assume-yes-for-downloads",
           f"--include-data-dir={ROOT / 'autotest' / 'web'}=trxstation/autotest/web",
           "--include-package-data=trxstation.i18n", "--include-module=serial.tools.list_ports",
           f"--output-dir={ROOT / 'build' / 'autotest-exe'}", f"--output-filename={name}",
           "--company-name=RF-DIY.COM", "--product-name=openRemoteTRX-Autotest",
           f"--product-version={v}", f"--file-version={v}",
           "--file-description=openRemoteTRX-Autotest (mode B, Hamlib)", "--copyright=AGPL-3.0-or-later, RF-DIY.COM",
           str(ROOT / "scripts" / "autotest_exe_entry.py")]
    done = subprocess.run(cmd, cwd=ROOT)
    if done.returncode:
        return done.returncode
    built = ROOT / "build" / "autotest-exe" / name
    target = out / name
    target.write_bytes(built.read_bytes())
    print(f"EXE : {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
