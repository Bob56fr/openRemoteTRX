"""Installation d'une mise à jour, ou retour à la version précédente (root, Debian) : `python -m trxstation.update.apply`.

    apply --config C install --version 0.23.0   installe la version annoncée (confirmée dans TRX Console)
    apply --config C rollback                   revient à la version précédente (sans réseau)

Ordre, et rien n'est installé au moindre écart :
  1. émission ? (fichier d'état de la passerelle ET relecture directe du poste) : refus si émission ou doute ;
  2. GitHub réinterrogé ICI (latest.json, écrit par le compte trx, ne sert qu'à l'affichage) ;
  3. téléchargement du zip et de sa signature, vérification Ed25519 par le code DÉJÀ installé ;
  4. contrôle du contenu (chemins, liens, taille, version) puis extraction dans un dossier root 0700 ;
  5. émission ? de nouveau, arrêt immédiat de la station (la passerelle coupe le PTT en s'arrêtant) ;
  6. install.sh du paquet vérifié : la version précédente et la configuration sont conservées.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .. import __version__
from ..status import GatewayStatus, read_status
from ..supervisor.rigctl import RigctlProbe, RigProbe
from . import check as chk
from .signing import MAX_SIG_BYTES, SignatureError, verify_file

APP_DIR = Path("/opt/trx-remote")
WORK_ROOT = Path("/var/cache/trx-remote")
TARGET = "trx-remote.target"
MAX_MEMBERS = 5000
MAX_UNPACKED_BYTES = 300 * 1024 * 1024
FRESH_WAIT_S = 0.8            # la passerelle écrit son état toutes les 0,25 s
REQUIRED = ("install.sh", "releases.sh", "app/pyproject.toml", "app/trxstation/__init__.py")

EXIT_OK, EXIT_FAILED, EXIT_TX, EXIT_REFUSED = 0, 1, 3, 4


class UpdateRefused(Exception):
    """Mise à jour refusée : rien n'a été installé."""


class TransmitRefused(UpdateRefused):
    """Refus parce que le poste émet, ou qu'on ne peut pas prouver qu'il n'émet pas."""


Download = Callable[[str, int], bytes]


def http_download(url: str, max_bytes: int) -> bytes:
    return chk.http_get(url, max_bytes=max_bytes, accept="application/octet-stream")


# ------------------------------------------------------------------ 1. émission en cours ?

def transmit_doubt(*, gateway_active: bool, rigctld_active: bool, first: GatewayStatus | None,
                   second: GatewayStatus | None, probe: RigProbe) -> str | None:
    """None si le poste est sûrement en réception ; sinon la raison du refus. En cas de doute : refus."""
    for status in (first, second):
        if status is not None and status.ptt.get("state") != "RX":
            return "émission en cours (passerelle) : coupe l'émission puis recommence"
    fresh = (second is not None and first is not None and (first.pid, first.seq) != (second.pid, second.seq))
    if gateway_active and not fresh:
        return "passerelle muette : état d'émission inconnu. Arrête la station (menu « Arrêter ») puis recommence"
    if probe.ok and probe.ptt is True:
        return "le poste est en émission : coupe l'émission puis recommence"
    if rigctld_active and not probe.ok:
        return "poste non relisible (rigctld ne répond pas). Arrête la station puis recommence"
    if probe.ok and probe.ptt is None and not (gateway_active and fresh):
        return "état d'émission du poste illisible. Arrête la station puis recommence"
    return None


# ------------------------------------------------------------------ 4. contenu du paquet

def safe_members(archive: zipfile.ZipFile, version: str) -> list[zipfile.ZipInfo]:
    """Membres du zip, tous sous `trx-remote-debian-<version>/`, sans lien ni chemin dangereux."""
    root = f"trx-remote-debian-{version}"
    infos = archive.infolist()
    if not infos or len(infos) > MAX_MEMBERS:
        raise UpdateRefused("paquet vide ou démesuré")
    total = 0
    names: set[str] = set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if ("\\" in name or name.startswith("/") or ":" in name or ".." in path.parts
                or not path.parts or path.parts[0] != root):
            raise UpdateRefused(f"chemin refusé dans le paquet : {name[:80]!r}")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode) or (mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
            raise UpdateRefused(f"lien ou fichier spécial refusé dans le paquet : {name[:80]!r}")
        if info.flag_bits & 0x1:
            raise UpdateRefused("paquet chiffré refusé")
        total += info.file_size
        if total > MAX_UNPACKED_BYTES:
            raise UpdateRefused("paquet trop gros une fois décompressé")
        if name in names:
            raise UpdateRefused(f"fichier en double dans le paquet : {name[:80]!r}")
        names.add(name)
    missing = [r for r in REQUIRED if f"{root}/{r}" not in names]
    if missing:
        raise UpdateRefused("paquet incomplet : " + ", ".join(missing))
    try:
        packaged = tomllib.loads(archive.read(f"{root}/app/pyproject.toml").decode("utf-8"))["project"]["version"]
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise UpdateRefused("version du paquet illisible") from exc
    if packaged != version:
        raise UpdateRefused(f"le paquet contient la version {packaged}, pas {version}")
    return infos


def extract(package: Path, version: str, dest: Path) -> Path:
    """Extrait le paquet vérifié dans `dest` ; retourne le dossier qui contient install.sh."""
    with zipfile.ZipFile(package) as archive:
        for info in safe_members(archive, version):
            target = dest.joinpath(*PurePosixPath(info.filename).parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            os.chmod(target, 0o755 if (info.external_attr >> 16) & 0o111 else 0o644)
    return dest / f"trx-remote-debian-{version}"


def previous_version(app_dir: Path = APP_DIR) -> str | None:
    """Version gardée pour un retour arrière (lien /opt/trx-remote/previous), ou None. Lecture seule."""
    link = app_dir / "previous"
    try:
        name = Path(os.readlink(link)).name
    except OSError:
        return None
    if chk.parse_version(name) is None or not (app_dir / "releases" / name / "install.sh").is_file():
        return None
    return name


# ------------------------------------------------------------------ orchestration

@dataclass
class System:
    """Accès au système, remplacé dans les tests."""
    is_active: Callable[[str], bool]
    stop_station: Callable[[], bool]
    run_script: Callable[[list[str]], int]
    read_status: Callable[[], GatewayStatus | None]
    probe: Callable[[], RigProbe]
    sleep: Callable[[float], None] = time.sleep


def real_system(cfg) -> System:
    def is_active(unit: str) -> bool:
        try:
            return subprocess.run(["systemctl", "is-active", "--quiet", unit], timeout=15).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return True                      # inconnu : on suppose actif (refus plus probable)

    def stop_station() -> bool:
        try:
            return subprocess.run(["systemctl", "stop", TARGET], timeout=60).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def run_script(cmd: list[str]) -> int:
        try:
            return subprocess.call(cmd)
        except OSError:
            return 127

    probe = RigctlProbe(cfg.network.rigctld_host, cfg.network.rigctld_port, timeout=1.0)
    return System(is_active=is_active, stop_station=stop_station, run_script=run_script,
                  read_status=lambda: read_status(cfg.supervisor.status_path), probe=probe.read)


class Updater:
    def __init__(self, cfg, system: System, *, say: Callable[[str], None] = print, fetch: chk.Fetch = chk.http_get,
                 download: Download = http_download, installed: str = __version__, app_dir: Path = APP_DIR,
                 work_root: Path = WORK_ROOT):
        self.cfg, self.sys, self.say, self.fetch, self.download = cfg, system, say, fetch, download
        self.installed, self.app_dir, self.work_root = installed, app_dir, work_root

    def ensure_receive(self) -> None:
        s = self.cfg.supervisor
        gateway_active, rigctld_active = self.sys.is_active(s.gateway_unit), self.sys.is_active(s.rigctld_unit)
        first = self.sys.read_status()
        self.sys.sleep(FRESH_WAIT_S)
        second = self.sys.read_status()
        reason = transmit_doubt(gateway_active=gateway_active, rigctld_active=rigctld_active,
                                first=first, second=second, probe=self.sys.probe())
        if reason:
            raise TransmitRefused(reason)

    def stop_station(self) -> None:
        self.ensure_receive()
        if not self.sys.stop_station():
            raise UpdateRefused("arrêt de la station impossible : rien n'a été installé")
        self.say("Station arrêtée (le poste reste en réception).")

    def install(self, version: str) -> int:
        self.ensure_receive()
        self.say("Recherche de la version sur GitHub...")
        state = chk.check(installed=self.installed, allow_prerelease=self.cfg.update.allow_prerelease, fetch=self.fetch)
        if not state.ok:
            raise UpdateRefused(f"GitHub : {state.error}")
        release = state.release
        if release is None or release.version != version:
            found = release.version if release else "aucune"
            raise UpdateRefused(f"la version {version} n'est pas (ou plus) la dernière proposée (GitHub : {found})")
        self.work_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.work_root, 0o700)
        work = Path(tempfile.mkdtemp(prefix=f"maj-{version}-", dir=self.work_root))
        try:
            package = work / release.zip_name
            self.say(f"Téléchargement de {release.zip_name} ({release.zip_size // 1024} ko)...")
            data = self._download(release.zip_url, release.zip_size)
            if len(data) != release.zip_size:
                raise UpdateRefused("paquet incomplet (taille différente de celle annoncée)")
            package.write_bytes(data)
            sig_text = self._download(release.sig_url, MAX_SIG_BYTES).decode("utf-8", "replace")
            try:
                verify_file(package, sig_text, expected_file=release.zip_name, expected_version=release.version)
            except SignatureError as exc:
                raise UpdateRefused(f"SIGNATURE REFUSÉE : {exc}") from exc
            self.say("Signature vérifiée.")
            source = extract(package, release.version, work / "paquet")
            self.stop_station()
            self.say(f"Installation de la version {release.version} (la version {self.installed} est gardée)...")
            code = self.sys.run_script(["bash", str(source / "install.sh")])
            if code != 0:
                self.say(f"L'installation a échoué (code {code}) : la version {self.installed} reste active.")
                return EXIT_FAILED
            return EXIT_OK
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _download(self, url: str, max_bytes: int) -> bytes:
        try:
            return self.download(url, max_bytes)
        except chk.CheckError as exc:
            raise UpdateRefused(f"téléchargement impossible : {exc}") from exc

    def previous_release(self) -> Path | None:
        link = self.app_dir / "previous"
        if not link.is_symlink():
            return None
        target = link.resolve()
        releases = (self.app_dir / "releases").resolve()
        if target.parent != releases or not (target / "install.sh").is_file():
            return None
        return target

    def rollback(self) -> int:
        previous = self.previous_release()
        if previous is None:
            raise UpdateRefused("aucune version précédente installée")
        self.stop_station()
        self.say(f"Retour à la version {previous.name}...")
        code = self.sys.run_script(["bash", str(previous / "install.sh"), "--reactiver"])
        if code != 0:
            self.say(f"Le retour a échoué (code {code}).")
            return EXIT_FAILED
        return EXIT_OK


def main(argv: list[str] | None = None, *, system: System | None = None, fetch: chk.Fetch = chk.http_get,
         download: Download = http_download, app_dir: Path = APP_DIR, work_root: Path = WORK_ROOT) -> int:
    from .. import config as cfgmod
    from ..paths import default_config_path

    ap = argparse.ArgumentParser(prog="trx-update", description="Installe une mise à jour signée ou revient en arrière")
    ap.add_argument("--config", type=Path, default=default_config_path())
    sub = ap.add_subparsers(dest="action", required=True)
    inst = sub.add_parser("install", help="installe la version annoncée")
    inst.add_argument("--version", required=True)
    sub.add_parser("rollback", help="revient à la version précédente")
    args = ap.parse_args(argv)
    if system is None:
        if not sys.platform.startswith("linux") or os.geteuid() != 0:
            print("Mise à jour possible seulement sous Linux (Debian), en administrateur (sudo).", file=sys.stderr)
            return EXIT_FAILED
    try:
        cfg = cfgmod.load(args.config)
    except cfgmod.ConfigError as exc:
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    updater = Updater(cfg, system or real_system(cfg), fetch=fetch, download=download, app_dir=app_dir,
                      work_root=work_root)
    try:
        return updater.install(args.version) if args.action == "install" else updater.rollback()
    except UpdateRefused as exc:
        print(f"Refusé : {exc}\nRien n'a été installé.", file=sys.stderr)
        return EXIT_TX if isinstance(exc, TransmitRefused) else EXIT_REFUSED
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"Mise à jour interrompue : {exc}\nRien n'a été installé.", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
