# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Crée la paire de clés Ed25519 qui signe les paquets de mise à jour.

    python scripts/gen_update_key.py              crée la clé (phrase de passe demandée) et inscrit la clé publique
    python scripts/gen_update_key.py --afficher   affiche la clé publique d'une clé existante

La clé PRIVÉE est écrite hors du dépôt (par défaut ~/.trx-remote/update-signing-key.pem, ou TRX_SIGNING_KEY),
jamais écrasée. La clé PUBLIQUE est ajoutée à trxstation/update/pubkey.py, à committer.
Sauvegarde la clé privée hors ligne (clé USB rangée) : sans elle, plus aucune mise à jour signée possible.
"""
from __future__ import annotations

import argparse
import getpass as _getpass
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trxstation.update import keyfile  # noqa: E402

PUBKEY_FILE = ROOT / "trxstation" / "update" / "pubkey.py"
MIN_PASSPHRASE = 12


def _ask_passphrase(ask: Callable[[str], str]) -> bytes | None:
    while True:
        first = ask(f"Phrase de passe de la clé ({MIN_PASSPHRASE} caractères min., Entrée = aucune) : ")
        if not first:
            print("ATTENTION : clé non chiffrée. Toute personne qui copie le fichier pourra signer des paquets.")
            return None
        if len(first) < MIN_PASSPHRASE:
            print(f"Trop courte : {MIN_PASSPHRASE} caractères au minimum.")
            continue
        if ask("Phrase de passe, encore une fois : ") != first:
            print("Les deux saisies diffèrent, recommence.")
            continue
        return first.encode("utf-8")


def main(argv: list[str] | None = None, *, ask: Callable[[str], str] = _getpass.getpass,
         repo: Path = ROOT, pubkey_file: Path = PUBKEY_FILE) -> int:
    ap = argparse.ArgumentParser(prog="gen_update_key", description="Clé de signature des mises à jour")
    ap.add_argument("--output", type=Path, default=None, help="emplacement de la clé privée (hors du dépôt)")
    ap.add_argument("--sans-phrase", action="store_true", help="clé privée non chiffrée (déconseillé)")
    ap.add_argument("--sans-inscrire", action="store_true", help="ne pas modifier trxstation/update/pubkey.py")
    ap.add_argument("--afficher", action="store_true", help="affiche la clé publique d'une clé existante")
    args = ap.parse_args(argv)
    try:
        import cryptography  # noqa: F401
    except ImportError:
        print("Le module cryptography est nécessaire : pip install cryptography", file=sys.stderr)
        return 1
    path = args.output or keyfile.default_key_path()
    try:
        if args.afficher:
            passphrase = ask("Phrase de passe de la clé : ").encode("utf-8") if keyfile.is_encrypted(path) else None
            print(keyfile.public_text(keyfile.load(path, passphrase)))
            return 0
        passphrase = None if args.sans_phrase else _ask_passphrase(ask)
        private = keyfile.create(path, passphrase, forbidden_dir=repo)
    except keyfile.KeyFileError as exc:
        print(f"Refusé : {exc}", file=sys.stderr)
        return 1
    public = keyfile.public_text(private)
    print(f"Clé privée créée : {path}\n  -> à sauvegarder hors ligne, à ne JAMAIS committer ni envoyer.")
    print(f"Clé publique : {public}")
    if args.sans_inscrire:
        print(f'Ajoute-la à PUBLIC_KEYS dans {pubkey_file} : "{public}",')
    elif keyfile.register_public_key(pubkey_file, public):
        print(f"Clé publique ajoutée à {pubkey_file} : à committer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
