# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Suite de tests sur la machine la plus rapide disponible (étape 211).

    python scripts/tests.py                  suite complète, en parallèle (-q -n auto)
    python scripts/tests.py tests/test_x.py  arguments passés tels quels à pytest
    python scripts/tests.py --local …        toujours sur ce PC

Si une machine de test est déclarée et répond en SSH (même réseau, ou VPN de la maison), l'état COURANT du dépôt y
est envoyé (fichiers suivis et nouveaux fichiers non ignorés par .gitignore : ni clés, ni keystore, ni dist/), les
tests y tournent en priorité basse sur tous ses cœurs et le résultat revient ici ; sinon, ils tournent sur ce PC.

Machine de test : fichier `.tests-host` à la racine du dépôt (IGNORÉ par git : le dépôt est public, jamais d'adresse
ni de compte dedans), une ligne `compte@adresse` ; ou variable ORX_TESTS_HOST. Elle doit avoir (une fois) :
serveur OpenSSH avec la clé de ce PC, Python 3.12 et un environnement `C:\\dev\\openRemoteTRX-tests\\.venv` installé
depuis requirements.lock + pytest, pytest-xdist, pyyaml, et Node.js (tests de la page).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_FILE = ROOT / ".tests-host"
REMOTE_DIR = r"C:\dev\openRemoteTRX-tests"
REMOTE_PY = REMOTE_DIR + r"\.venv\Scripts\python.exe"
NODE_DIR = r"C:\Program Files\nodejs"
DEFAULT_ARGS = ["-q", "-n", "auto"]
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR"]


def test_host() -> str | None:
    host = os.environ.get("ORX_TESTS_HOST", "").strip()
    if not host and HOST_FILE.exists():
        host = HOST_FILE.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    return host or None


def reachable(host: str, timeout: float = 1.5) -> bool:
    address = host.rsplit("@", 1)[-1]
    try:
        with socket.create_connection((address, 22), timeout=timeout):
            return True
    except OSError:
        return False


def files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, check=True,
                         capture_output=True).stdout
    return [f for f in out.decode("utf-8").split("\0") if f and (ROOT / f).is_file()]


def run_local(args: list[str]) -> int:
    base = Path(tempfile.gettempdir()) / "orx-tests"
    print(f"Tests sur CE PC ({os.cpu_count()} cœurs).", flush=True)
    return subprocess.call([sys.executable, "-m", "pytest", *args, f"--basetemp={base}", "-p", "no:cacheprovider"],
                           cwd=ROOT)


def run_remote(host: str, args: list[str]) -> int:
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "src.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            for name in files():
                tar.add(ROOT / name, arcname=name)
        size = archive.stat().st_size // 1024
        sent = subprocess.run(["scp", "-q", *SSH_OPTS, str(archive), f"{host}:{REMOTE_DIR}/src.tgz".replace("\\", "/")])
        if sent.returncode != 0:
            print("Envoi vers la machine de test impossible : tests sur ce PC.", flush=True)
            return run_local(args)
    print(f"Tests sur {host.rsplit('@', 1)[-1]} (archive {size} ko envoyée en "
          f"{time.perf_counter() - start:.1f} s).", flush=True)
    pytest = " ".join(subprocess.list2cmdline([a]) for a in args)
    script = (f'cd /d {REMOTE_DIR} && (if exist src rmdir /s /q src) && mkdir src && tar -xzf src.tgz -C src '
              f'&& del src.tgz && cd src && set "PATH={NODE_DIR};%PATH%" && set "PYTHONUTF8=1" '      # guillemets : sinon cmd garde l'espace
              f'&& start "" /belownormal /b /wait {REMOTE_PY} -m pytest {pytest} '
              f'--basetemp={REMOTE_DIR}\\tmp -p no:cacheprovider')
    return subprocess.call(["ssh", *SSH_OPTS, host, script])


def main(argv: list[str]) -> int:
    local = "--local" in argv
    args = [a for a in argv if a != "--local"] or DEFAULT_ARGS
    if not any(a == "-n" or a.startswith("-n") or a.startswith("--numprocesses") for a in args):
        args = [*args, "-n", "auto"]
    host = None if local else test_host()
    if host and reachable(host):
        return run_remote(host, args)
    if host and not local:
        print(f"Machine de test {host.rsplit('@', 1)[-1]} injoignable : tests sur ce PC.", flush=True)
    return run_local(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
