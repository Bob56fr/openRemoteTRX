# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Station factice pour l'essai de l'onglet CW dans un émulateur (branche exp/cw, lot CW-2).

Vraie passerelle de la branche (dossier src/ à côté), poste FACTICE (faux rigctld, jamais un vrai poste) mis en PKTUSB
sur 7,030 MHz AVANT le démarrage de la passerelle (sinon « poste utilisé sur place »), [cw] enabled = true, son ÉMIS
enregistré dans un WAV (mesure de la manipulation). Ports à part (18443, 14532, 47910) : jamais ceux d'une station
installée. L'émulateur voit la machine en 10.0.2.2.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
sys.path.insert(0, str(SRC))

from trxstation import config as cfgmod  # noqa: E402
from trxstation.config import ClientAuth  # noqa: E402
from trxstation.gateway.api.tls import certificate_fingerprint, generate_self_signed  # noqa: E402
from trxstation.passwords import hash_password  # noqa: E402
from trxstation.setup_wizard import dummy_config  # noqa: E402

GATEWAY_PORT = 18443
RIGCTLD_PORT = 14532
BUS_PORT = 47910
CW_SECTION = """
[cw]
enabled = true
modes = ["A"]
data_mode = "PKTUSB"
tone_hz = 700
delay_ms = 300
ptt_variant = "{variant}"
"""


def build(folder: Path, password: str, account: str, sink: str, variant: str = "hold", bind: str = "127.0.0.1") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    cert, key = folder / "station.crt", folder / "station.key"
    if not cert.exists():
        generate_self_signed(["127.0.0.1", "10.0.2.2", "localhost"] + ([bind] if bind != "127.0.0.1" else []), cert, key)
    cfg = dummy_config()
    cfg.network.rigctld_port = RIGCTLD_PORT
    cfg.network.gateway_port = GATEWAY_PORT
    cfg.network.gateway_bind = bind
    cfg.network.tls_cert, cfg.network.tls_key = str(cert), str(key)
    cfg.network.ice_servers = []
    cfg.audio.capture_device = "tone:600"
    cfg.audio.playback_device = sink
    cfg.supervisor.state_dir = str(folder / "etat")
    cfg.supervisor.status_path = str(folder / "etat" / "status.json")
    cfg.modules.bus_port = BUS_PORT
    cfg.clients = [ClientAuth(id=account, password_hash=hash_password(password))]
    path = folder / "station.toml"
    path.write_text(cfgmod.render_toml(cfg) + CW_SECTION.format(variant=variant), encoding="utf-8")
    loaded = cfgmod.load(path)
    problems = cfgmod.validate(loaded)
    if problems or not loaded.cw.enabled:
        raise SystemExit("station.toml refusée :\n  - " + "\n  - ".join(problems or ["[cw] non pris"]))
    return path


def rig(cmd: str) -> str:
    with socket.create_connection(("127.0.0.1", RIGCTLD_PORT), timeout=3) as s:
        s.sendall((cmd + "\n").encode())
        time.sleep(0.2)
        return s.recv(4096).decode(errors="replace").strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dossier", type=Path, required=True)
    ap.add_argument("--mot-de-passe", required=True)
    ap.add_argument("--compte", default="cw")
    ap.add_argument("--enregistrer", type=Path, required=True, help="WAV du son émis (tonalité CW recréée)")
    ap.add_argument("--variante", choices=("hold", "hang"), default="hold", help="PTT : V1 tenu (hold) ou V2 relâché (hang)")
    ap.add_argument("--ecoute", default="127.0.0.1",
                    help="127.0.0.1 (émulateur) ou l'adresse de la machine dans le réseau local (vrai téléphone)")
    args = ap.parse_args()
    toml = build(args.dossier, args.mot_de_passe, args.compte, f"file:{args.enregistrer}", args.variante, args.ecoute)
    where = "10.0.2.2" if args.ecoute == "127.0.0.1" else args.ecoute
    print(f"Station factice CW : https://{where}:{GATEWAY_PORT}, compte {args.compte}, PTT {args.variante}", flush=True)
    print(f"Empreinte : {certificate_fingerprint(args.dossier / 'station.crt')}", flush=True)
    env = dict(os.environ, PYTHONPATH=str(SRC))
    fake = subprocess.Popen([sys.executable, "-m", "trxstation.devtools.fake_rigctld", "--port", str(RIGCTLD_PORT)], env=env)
    time.sleep(1.5)
    print("poste :", rig("F 7030000"), "|", rig("M PKTUSB 2400"), "|", rig("f"), "|", rig("m"), flush=True)
    try:
        return subprocess.call([sys.executable, "-m", "trxstation.gateway.main", "--config", str(toml)], env=env)
    finally:
        fake.terminate()


if __name__ == "__main__":
    sys.exit(main())
