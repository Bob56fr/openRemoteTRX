# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Import d'une configuration venue d'un autre PC (typiquement Windows) vers cette machine Linux.

Tout ce qui ne dépend pas de la machine est conservé : comptes ([[clients]]), alertes (notify_url),
bandes, sécurité, modèle du poste, modes d'émission, puissance... Ce qui désigne du matériel ou des
chemins de l'ancienne machine est vidé, et l'assistant (trx-setup --base) le redemande :
port CAT, cartes son, dossier Hamlib, certificat TLS, adresse d'écoute.

Le résultat est un point de DÉPART, pas une configuration de service : il peut rester incomplet
(port vide pour un vrai poste) ; seul trx-setup écrit la configuration finale, validée.
"""
from __future__ import annotations

import argparse
import copy
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from . import config as cfgmod
from .config import Config, is_loopback
from .fsperm import protect

LINUX_STATUS_PATH = "/run/trx-remote/gateway-status.json"
LINUX_STATE_DIR = "/var/lib/trx-remote"
SYNTHETIC_AUDIO = ("file:", "tone:", "click:")


def _windows_port(value: str) -> bool:
    return bool(re.fullmatch(r"(\\\\\.\\)?COM\d+", value.strip(), re.IGNORECASE))


def _windows_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or "\\" in value


def _real_audio(value: str) -> bool:
    value = value.strip()
    return bool(value) and value != "null" and not value.startswith(SYNTHETIC_AUDIO)


def is_desktop(run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
               platform: str | None = None) -> bool:
    """Vrai sur un PC Linux de bureau (démarrage graphique) : on n'y redémarre jamais la machine."""
    if not (platform or sys.platform).startswith("linux") or shutil.which("systemctl") is None:
        return False
    try:
        out = run(["systemctl", "get-default"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return out.strip() == "graphical.target"


def import_config(source: Config, *, desktop: bool) -> tuple[Config, list[str]]:
    """Adapte `source` à cette machine Linux : (nouvelle config, notes lisibles)."""
    cfg = copy.deepcopy(source)
    notes: list[str] = []
    r, a, n, v = cfg.rig, cfg.audio, cfg.network, cfg.supervisor

    if r.port and (_windows_port(r.port) or not Path(r.port).exists()):
        notes.append(f"Port CAT « {r.port} » inconnu ici : à choisir dans l'assistant.")
        r.port = ""
    if r.ptt_port and (_windows_port(r.ptt_port) or not Path(r.ptt_port).exists()):
        notes.append(f"Port PTT « {r.ptt_port} » inconnu ici : à choisir dans l'assistant.")
        r.ptt_port = ""
    for name in ("capture_device", "playback_device"):
        value = getattr(a, name)
        if _real_audio(value):
            notes.append(f"Carte son « {value} » ({name}) propre à l'ancien PC : à choisir dans l'assistant.")
            setattr(a, name, "")
    sp = cfg.spectrum
    if sp.port and (_windows_port(sp.port) or not Path(sp.port).exists()):
        if sp.enabled:
            notes.append(f"Spectre HF : second port « {sp.port} » inconnu ici, spectre désactivé (adresse CI-V {sp.civ_address or '?'} "
                         "gardée). Une fois le poste branché : trx-setup --spectre <second port> (vérification complète).")
        sp.port, sp.enabled = "", False
    if cfg.tools.hamlib_dir:
        notes.append("Dossier Hamlib de l'ancien PC oublié : Hamlib est installé par le système ici.")
        cfg.tools.hamlib_dir = ""

    for name in ("tls_cert", "tls_key"):
        value = getattr(n, name)
        if value and (_windows_path(value) or not Path(value).exists()):
            setattr(n, name, "")
    if not (n.tls_cert and n.tls_key):
        if source.network.tls_cert:
            notes.append("Certificat TLS de l'ancien PC non repris : l'assistant en génère un pour ce PC.")
        n.tls_cert = n.tls_key = ""
    if n.gateway_bind not in ("0.0.0.0", "::") and not is_loopback(n.gateway_bind):
        notes.append(f"Adresse d'écoute « {n.gateway_bind} » propre à l'ancien PC : accès limité à cette machine "
                     "jusqu'au réglage de l'accès dans l'assistant.")
        n.gateway_bind = "127.0.0.1"

    v.status_path, v.state_dir = LINUX_STATUS_PATH, LINUX_STATE_DIR
    extra = cfg.modules.extra_dir
    if extra and (_windows_path(extra) or not Path(extra).is_dir()):
        notes.append(f"Dossier de modules « {extra} » propre à l'ancien PC oublié : modules fournis seulement.")
        cfg.modules.extra_dir = ""
    if v.service_mode == "managed":
        notes.append("Mode « géré » (Windows) remplacé par auto : sous Linux, systemd gère les services.")
        v.service_mode = "auto"
    if desktop and v.max_reboots_per_hour != 0:
        notes.append(f"PC de bureau : redémarrages automatiques désactivés (max_reboots_per_hour {v.max_reboots_per_hour} -> 0). "
                     "En dernier recours, le superviseur passe en mode sûr au lieu de redémarrer le PC.")
        v.max_reboots_per_hour = 0

    kept = [c for c in cfg.clients if c.id and (c.password_hash or c.token)]
    if len(kept) != len(cfg.clients):
        notes.append(f"{len(cfg.clients) - len(kept)} compte(s) incomplet(s) ignoré(s) (sans identifiant ou sans mot de passe).")
    cfg.clients = kept
    if kept:
        notes.append("Comptes repris : " + ", ".join(c.id for c in kept) + " (mêmes mots de passe).")
    if v.notify_url:
        notes.append("Alertes ntfy reprises (notify_url).")
    with_secret = [s.name for s in cfg.cluster.source if s.secret]
    if with_secret:
        notes.append(f"Cluster DX : mots de passe de {', '.join(with_secret)} NON repris (secrets.toml ne voyage pas) : "
                     "à ressaisir avec TRX Console, menu 12.")
    return cfg, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-import", description="Importe une station.toml d'un autre PC comme point de départ")
    ap.add_argument("source", type=Path, help="station.toml de l'ancien PC")
    ap.add_argument("destination", type=Path, help="fichier de départ à écrire (ex. /etc/trx-remote/station.import.toml)")
    ap.add_argument("--bureau", action="store_true", help="PC de bureau : jamais de redémarrage automatique")
    args = ap.parse_args(argv)
    try:
        source, problems = cfgmod.load_unchecked(args.source)
    except (OSError, cfgmod.ConfigError) as exc:
        print(f"Import impossible : {exc}", file=sys.stderr)
        return 2
    cfg, notes = import_config(source, desktop=args.bureau or is_desktop())
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    previous = args.destination.stat() if args.destination.exists() else None
    args.destination.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    protect(args.destination, previous)
    print(f"Configuration importée : {args.destination}")
    for note in notes:
        print(f"  - {note}")
    remaining = cfgmod.validate(cfg)
    if remaining:
        print("À compléter dans l'assistant :")
        for problem in remaining:
            print(f"  - {problem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
