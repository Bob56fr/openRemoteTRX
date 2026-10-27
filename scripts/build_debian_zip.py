# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique le paquet d'installation Debian : dist/trx-remote-debian-<version>.zip.

    python scripts/build_debian_zip.py                  zip + signature (.zip.sig) à joindre à la Release
    python scripts/build_debian_zip.py --sans-signature zip seul (essais locaux)
    python scripts/build_debian_zip.py --cle F          clé privée ailleurs que l'emplacement par défaut

Fonctionne sous Windows comme sous Linux. Les fichiers texte passent en fins de ligne
Linux (LF) : un install.sh en CRLF, tel que Git peut le produire sous Windows, échouerait sous Debian.
Le zip ne contient ni configuration, ni certificat, ni cache : seulement ce qu'il faut pour installer.
La signature (module cryptography) utilise la clé créée par scripts/gen_update_key.py, hors du dépôt.
"""
from __future__ import annotations

import argparse
import getpass
import sys
import tomllib
import zipfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TEXT_SUFFIXES = {".sh", ".py", ".toml", ".service", ".target", ".timer", ".conf", ".rules", ".desktop", ".txt", ".md",
                 ".svg", ".js", ".html", ".css"}
SYSTEM_FILES = {                                   # dossier systeme/ du zip <- fichier du dépôt
    "rigctld.service": "systemd/rigctld.service",
    "trx-gateway.service": "systemd/trx-gateway.service",
    "trx-supervisor.service": "systemd/trx-supervisor.service",
    "trx-remote.target": "systemd/trx-remote.target",
    "trx-update-check.service": "systemd/trx-update-check.service",
    "trx-update-check.timer": "systemd/trx-update-check.timer",
    "trx-remote-tmpfiles.conf": "debian/trx-remote-tmpfiles.conf",
    "99-trx-remote-modemmanager.rules": "debian/99-trx-remote-modemmanager.rules",
    "trx-console.desktop": "debian/trx-console.desktop",
    "trx-console.svg": "debian/trx-console.svg",
}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", "node_modules"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".bak", ".wav", ".pem"}
EXCLUDED_NAMES = {"station.toml", "secrets.toml", "cty.dat"}      # configuration et secrets locaux, données téléchargées


def version(root: Path = ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _app_files(root: Path) -> list[tuple[str, Path]]:
    files = [("app/pyproject.toml", root / "pyproject.toml"),
             ("app/config/station.example.toml", root / "config" / "station.example.toml")]
    for base in ("trxstation", "docs"):
        for path in sorted((root / base).rglob("*")):
            rel = path.relative_to(root)
            if (path.is_file() and not EXCLUDED_PARTS.intersection(rel.parts)
                    and path.suffix not in EXCLUDED_SUFFIXES and path.name not in EXCLUDED_NAMES):
                files.append((f"app/{rel.as_posix()}", path))
    return files


def manifest(root: Path = ROOT) -> list[tuple[str, Path]]:
    """[(nom dans le zip, fichier source)], sans le dossier racine."""
    files = [("install.sh", root / "debian" / "install.sh"), ("releases.sh", root / "debian" / "releases.sh"),
             ("LISEZMOI.txt", root / "debian" / "LISEZMOI.txt")]
    files += [(f"systeme/{name}", root / source) for name, source in SYSTEM_FILES.items()]
    files += _app_files(root)
    missing = [str(src.relative_to(root)) for _, src in files if not src.is_file()]
    if missing:
        raise FileNotFoundError("fichiers manquants : " + ", ".join(missing))
    return files


def _content(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return data


def build(root: Path = ROOT, out_dir: Path | None = None) -> Path:
    name = f"trx-remote-debian-{version(root)}"
    out_dir = out_dir or root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.zip"
    signature_path(target).unlink(missing_ok=True)          # une ancienne signature ne vaut plus pour ce zip
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, source in manifest(root):
            info = zipfile.ZipInfo(f"{name}/{arcname}", date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3                                        # Unix : droits respectés par unzip
            info.external_attr = (0o100755 if arcname.endswith(".sh") else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, _content(source))
    return target


def signature_path(target: Path) -> Path:
    return target.with_name(target.name + ".sig")


class SigningError(Exception):
    pass


def sign(target: Path, version_text: str, key_path: Path, passphrase: Callable[[], bytes | None],
         public_keys: tuple[str, ...] | None = None) -> Path:
    """Écrit `<zip>.sig`, puis le revérifie comme le fera la station. SigningError si impossible."""
    try:
        from trxstation.update import keyfile, signing
        from trxstation.update.pubkey import PUBLIC_KEYS
    except ImportError as exc:
        raise SigningError(f"module manquant ({exc}) : pip install cryptography") from exc
    keys = PUBLIC_KEYS if public_keys is None else public_keys
    if not key_path.is_file():
        raise SigningError(f"clé privée introuvable : {key_path}. Crée-la avec scripts/gen_update_key.py, "
                           "ou --sans-signature pour un essai local")
    try:
        private = keyfile.load(key_path, passphrase() if keyfile.is_encrypted(key_path) else None)
    except keyfile.KeyFileError as exc:
        raise SigningError(str(exc)) from exc
    if keyfile.public_text(private) not in keys:
        raise SigningError("la clé publique de cette clé n'est pas dans trxstation/update/pubkey.py : "
                           "les stations refuseraient ce paquet")
    text = signing.sign_file(target, version_text, private)
    sig = signature_path(target)
    sig.write_text(text, encoding="utf-8", newline="\n")
    try:
        signing.verify_file(target, text, expected_file=target.name, expected_version=version_text,
                            public_keys=keys)
    except signing.SignatureError as exc:
        sig.unlink(missing_ok=True)
        raise SigningError(f"signature produite mais non vérifiable : {exc}") from exc
    return sig


def main(argv: list[str] | None = None, *, root: Path = ROOT, out_dir: Path | None = None,
         ask: Callable[[str], str] = getpass.getpass, public_keys: tuple[str, ...] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build_debian_zip", description="Paquet d'installation Debian signé")
    ap.add_argument("--sans-signature", action="store_true", help="zip seul, sans .sig (essais locaux)")
    ap.add_argument("--cle", type=Path, default=None, help="clé privée de signature (hors du dépôt)")
    args = ap.parse_args(argv)
    try:
        target = build(root, out_dir)
    except FileNotFoundError as exc:
        print(f"Paquet impossible : {exc}", file=sys.stderr)
        return 1
    print(f"Paquet Debian créé : {target}")
    if args.sans_signature:
        print("Paquet NON signé : les stations refuseront de l'installer par la mise à jour automatique.")
        return 0
    if args.cle is None:
        from trxstation.update.keyfile import default_key_path
        args.cle = default_key_path()
    try:
        sig = sign(target, version(root), args.cle,
                   lambda: ask("Phrase de passe de la clé de signature : ").encode("utf-8"), public_keys)
    except SigningError as exc:
        print(f"Signature impossible : {exc}", file=sys.stderr)
        return 1
    print(f"Signature créée : {sig}\nJoins les DEUX fichiers à la Release GitHub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
