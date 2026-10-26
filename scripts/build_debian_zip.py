"""Fabrique le paquet d'installation Debian : dist/trx-remote-debian-<version>.zip.

    python scripts/build_debian_zip.py

Fonctionne sous Windows comme sous Linux (stdlib seule). Les fichiers texte passent en fins de ligne
Linux (LF) : un install.sh en CRLF, tel que Git peut le produire sous Windows, échouerait sous Debian.
Le zip ne contient ni configuration, ni certificat, ni cache : seulement ce qu'il faut pour installer.
"""
from __future__ import annotations

import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".sh", ".py", ".toml", ".service", ".target", ".conf", ".rules", ".desktop", ".txt", ".md",
                 ".svg", ".js", ".html", ".css"}
SYSTEM_FILES = {                                   # dossier systeme/ du zip <- fichier du dépôt
    "rigctld.service": "systemd/rigctld.service",
    "trx-gateway.service": "systemd/trx-gateway.service",
    "trx-supervisor.service": "systemd/trx-supervisor.service",
    "trx-remote.target": "systemd/trx-remote.target",
    "trx-remote-tmpfiles.conf": "debian/trx-remote-tmpfiles.conf",
    "99-trx-remote-modemmanager.rules": "debian/99-trx-remote-modemmanager.rules",
    "trx-console.desktop": "debian/trx-console.desktop",
    "trx-console.svg": "debian/trx-console.svg",
}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", "node_modules"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".bak", ".wav", ".pem"}


def version(root: Path = ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _app_files(root: Path) -> list[tuple[str, Path]]:
    files = [("app/pyproject.toml", root / "pyproject.toml"),
             ("app/config/station.example.toml", root / "config" / "station.example.toml")]
    for base in ("trxstation", "docs"):
        for path in sorted((root / base).rglob("*")):
            rel = path.relative_to(root)
            if (path.is_file() and not EXCLUDED_PARTS.intersection(rel.parts)
                    and path.suffix not in EXCLUDED_SUFFIXES):
                files.append((f"app/{rel.as_posix()}", path))
    return files


def manifest(root: Path = ROOT) -> list[tuple[str, Path]]:
    """[(nom dans le zip, fichier source)], sans le dossier racine."""
    files = [("install.sh", root / "debian" / "install.sh"), ("LISEZMOI.txt", root / "debian" / "LISEZMOI.txt")]
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
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, source in manifest(root):
            info = zipfile.ZipInfo(f"{name}/{arcname}", date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3                                        # Unix : droits respectés par unzip
            info.external_attr = (0o100755 if arcname.endswith(".sh") else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, _content(source))
    return target


def main() -> int:
    try:
        target = build()
    except FileNotFoundError as exc:
        print(f"Paquet impossible : {exc}", file=sys.stderr)
        return 1
    print(f"Paquet Debian créé : {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
