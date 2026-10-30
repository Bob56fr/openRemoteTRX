# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique le paquet d'installation Debian : dist/trx-remote-debian-<version>.zip.

    python scripts/build_debian_zip.py                  zip + signature (.zip.sig) à joindre à la Release
    python scripts/build_debian_zip.py --sans-signature zip seul (essais locaux)
    python scripts/build_debian_zip.py --cle F          clé privée ailleurs que l'emplacement par défaut

Fonctionne sous Windows comme sous Linux. Les fichiers texte passent en fins de ligne
Linux (LF) : un install.sh en CRLF, tel que Git peut le produire sous Windows, échouerait sous Debian.
Le zip ne contient ni configuration, ni certificat, ni cache : seulement ce qu'il faut pour installer.
HAMLIB : à chaque fabrication, la dernière Release publique de Hamlib (GitHub) et son empreinte SHA-256 sont
écrites dans le compiler-hamlib.sh du zip. Sans réseau : valeurs figées dans debian/compiler-hamlib.sh, avec un
avertissement pour un zip d'essai, refus pour un paquet signé (Release).
La signature (module cryptography) utilise la clé créée par scripts/gen_update_key.py, hors du dépôt.
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import urllib.request
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
    # Indicateur GNOME (barre du haut), installé dans /usr/share/gnome-shell/extensions/trx-distant@rf-diy.com
    "gnome-extension/metadata.json": "debian/gnome-extension/metadata.json",
    "gnome-extension/extension.js": "debian/gnome-extension/extension.js",
    "gnome-extension/status.js": "debian/gnome-extension/status.js",
    "gnome-extension/stylesheet.css": "debian/gnome-extension/stylesheet.css",
}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", "node_modules"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".bak", ".wav", ".pem"}
EXCLUDED_NAMES = {"station.toml", "secrets.toml", "cty.dat",      # configuration et secrets locaux, données téléchargées
                  "deploy_debian.ps1"}                              # script personnel de l'auteur (hors dépôt)


def version(root: Path = ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _app_files(root: Path) -> list[tuple[str, Path]]:
    files = [("app/pyproject.toml", root / "pyproject.toml"), ("app/LICENSE", root / "LICENSE")]   # AGPL : le texte suit le code
    # tests/ et les dossiers qu'ils lisent (debian/, systemd/, scripts/, config/), même disposition que le dépôt :
    # TRX Console > menu expert lance toute la suite sur la station (python -m pytest app/tests).
    for base in ("trxstation", "docs", "tests", "debian", "systemd", "scripts", "config"):
        for path in sorted((root / base).rglob("*")):
            rel = path.relative_to(root)
            if (path.is_file() and not EXCLUDED_PARTS.intersection(rel.parts)
                    and path.suffix not in EXCLUDED_SUFFIXES and path.name not in EXCLUDED_NAMES):
                files.append((f"app/{rel.as_posix()}", path))
    return files


def manifest(root: Path = ROOT) -> list[tuple[str, Path]]:
    """[(nom dans le zip, fichier source)], sans le dossier racine."""
    files = [("install.sh", root / "debian" / "install.sh"), ("releases.sh", root / "debian" / "releases.sh"),
             ("LISEZMOI.txt", root / "debian" / "LISEZMOI.txt"), ("LICENSE", root / "LICENSE"),
             ("compiler-hamlib.sh", root / "debian" / "compiler-hamlib.sh")]   # Hamlib récent (postes absents de Debian)
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


HAMLIB_SCRIPT = "compiler-hamlib.sh"
HAMLIB_API = "https://api.github.com/repos/Hamlib/Hamlib/releases/latest"
HAMLIB_SUMS = "https://github.com/Hamlib/Hamlib/releases/download/{v}/SHA256SUM-{v}"
HAMLIB_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+(\.[0-9]+)?$")
HAMLIB_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class HamlibLookupError(Exception):
    pass


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "openRemoteTRX-build"})
    with urllib.request.urlopen(request, timeout=20) as answer:         # adresses fixes, en https
        return answer.read(1_000_000).decode("utf-8", errors="replace")


def parse_hamlib_sums(text: str, version_text: str) -> str:
    """Empreinte de hamlib-<version>.tar.gz dans le fichier SHA256SUM-<version> de la Release."""
    wanted = f"hamlib-{version_text}.tar.gz"
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == wanted and HAMLIB_SHA_RE.match(parts[0].lower()):
            return parts[0].lower()
    raise HamlibLookupError(f"empreinte de {wanted} absente de SHA256SUM-{version_text}")


def latest_hamlib(fetch: Callable[[str], str] = _fetch) -> tuple[str, str]:
    """(version, sha256) de la dernière Release publique de Hamlib. HamlibLookupError si illisible."""
    try:
        tag = str(json.loads(fetch(HAMLIB_API)).get("tag_name", ""))
        if not HAMLIB_VERSION_RE.match(tag):
            raise HamlibLookupError(f"numéro de version inattendu : {tag!r}")
        return tag, parse_hamlib_sums(fetch(HAMLIB_SUMS.format(v=tag)), tag)
    except HamlibLookupError:
        raise
    except (OSError, ValueError, AttributeError) as exc:
        raise HamlibLookupError(f"GitHub injoignable ou réponse illisible ({exc})") from exc


def pinned_hamlib(root: Path = ROOT) -> str:
    """Version figée dans debian/compiler-hamlib.sh (utilisée sans réseau)."""
    text = (root / "debian" / HAMLIB_SCRIPT).read_text(encoding="utf-8")
    found = re.search(r"^HAMLIB_VERSION=(\S+)$", text, re.M)
    return found.group(1) if found else "?"


def with_hamlib(data: bytes, hamlib: tuple[str, str]) -> bytes:
    """compiler-hamlib.sh avec la version et l'empreinte données (une ligne chacune, sinon erreur)."""
    version_text, sha = hamlib
    if not HAMLIB_VERSION_RE.match(version_text) or not HAMLIB_SHA_RE.match(sha):
        raise ValueError(f"Hamlib {version_text!r} / {sha!r} refusés")
    text, n1 = re.subn(r"^HAMLIB_VERSION=\S+$", f"HAMLIB_VERSION={version_text}", data.decode("utf-8"), flags=re.M)
    text, n2 = re.subn(r"^HAMLIB_SHA256=\S+$", f"HAMLIB_SHA256={sha}", text, flags=re.M)
    if (n1, n2) != (1, 1):
        raise ValueError(f"{HAMLIB_SCRIPT} : lignes HAMLIB_VERSION / HAMLIB_SHA256 introuvables")
    return text.encode("utf-8")


def build(root: Path = ROOT, out_dir: Path | None = None, hamlib: tuple[str, str] | None = None) -> Path:
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
            data = _content(source)
            if arcname == HAMLIB_SCRIPT and hamlib is not None:
                data = with_hamlib(data, hamlib)
            archive.writestr(info, data)
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
         ask: Callable[[str], str] = getpass.getpass, public_keys: tuple[str, ...] | None = None,
         find_hamlib: Callable[[], tuple[str, str]] = latest_hamlib) -> int:
    ap = argparse.ArgumentParser(prog="build_debian_zip", description="Paquet d'installation Debian signé")
    ap.add_argument("--sans-signature", action="store_true", help="zip seul, sans .sig (essais locaux)")
    ap.add_argument("--cle", type=Path, default=None, help="clé privée de signature (hors du dépôt)")
    args = ap.parse_args(argv)
    pinned = pinned_hamlib(root)
    try:
        hamlib: tuple[str, str] | None = find_hamlib()
        print(f"Hamlib : dernière version publique {hamlib[0]} (SHA-256 {hamlib[1][:12]}…) mise dans {HAMLIB_SCRIPT}")
        if hamlib[0] != pinned:
            print(f"  (debian/{HAMLIB_SCRIPT} fige encore {pinned} : à mettre à jour pour les fabrications sans réseau)")
    except HamlibLookupError as exc:
        if not args.sans_signature:
            print(f"Paquet refusé : dernière version de Hamlib introuvable ({exc}).", file=sys.stderr)
            return 1
        hamlib = None
        print(f"ATTENTION : dernière version de Hamlib introuvable ({exc}) ; {pinned} (figée) gardée dans {HAMLIB_SCRIPT}")
    try:
        target = build(root, out_dir, hamlib)
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
