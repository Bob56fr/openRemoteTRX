# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique le paquet MSIX de la station pour le Microsoft Store : dist/openRemoteTRX-X.Y.Z.0-x64.msix.

Cahier `docs/store-microsoft-cahier-des-charges.md` § 3 et § 8. Contenu :
- `python\\` : Python embarqué officiel (empreinte vérifiée), modules de `requirements.lock` (empreintes vérifiées,
  roues Windows x64 seulement) et la station, prise dans une COPIE PROPRE du dernier commit (`git archive HEAD`,
  jamais les fichiers en cours d'autres conversations) ;
- `python\\trx-station.exe` : lanceur SANS paramètre de la station (tâche de démarrage, `trxstation/store_boot.py`) ;
- `freedv\\` (facultatif, `--freedv DOSSIER`) : décodeurs FreeDV, trouvés par `freedv/service.py` (`bundled_dir`) ;
- Hamlib n'est PAS dans le paquet (décision 3) : openRemoteTRX Console guide l'opérateur pour l'installer.

Le paquet produit n'est PAS signé : le Store le signe lui-même. Pour un essai local seulement, `--signer FICHIER.pfx`
(certificat dont le sujet est EXACTEMENT le `publisher` de windows/msix/identity.toml, mot de passe dans la variable
d'environnement TRX_MSIX_PFX_PASSWORD) ; `--certificat-essai` en fabrique un (dist\\msix-essai.pfx / .cer).

Outils (téléchargés une fois, empreintes vérifiées, dans %LOCALAPPDATA%\\trx-remote-build) : Python embarqué et
paquet NuGet Microsoft.Windows.SDK.BuildTools (makeappx, signtool), aucun SDK Windows à installer.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
IDENTITY = ROOT / "windows" / "msix" / "identity.toml"
LOGO = ROOT / "docs" / "marque" / "logo-rond.png"

PY_VERSION = "3.12.10"
PY_TAG = "312"
PY_EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
PY_EMBED_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
SDK_VERSION = "10.0.28000.2957"
SDK_URL = f"https://www.nuget.org/api/v2/package/Microsoft.Windows.SDK.BuildTools/{SDK_VERSION}"
SDK_SHA256 = "b7163fc6f636172726d0985963e4f7f11c41afe1c7fdfe78f8051877360ed696"

MIN_WINDOWS = "10.0.19045.0"           # Windows 10 22H2 (cahier § 12)
MAX_TESTED = "10.0.26100.0"
LANGUAGES = ("fr-FR", "en-US", "de-DE", "es-ES")
LAUNCHER = "trx-station.exe"
# Commandes tapables dans tout terminal (alias d'exécution) = [project.scripts] moins les services (comme $Commands
# d'installer.ps1 et COMMANDS d'install.sh) ; la station elle-même se lance par l'application « Supervisor ».
SERVICES = ("trx-gateway", "trx-rigctld", "trx-supervisor")
CONSOLE = "trx-console"
DESCRIPTIONS = {
    CONSOLE: "openRemoteTRX Console : démarrer, configurer, essayer et dépanner la station",
}


def identity() -> dict[str, str]:
    data = tomllib.loads(IDENTITY.read_text(encoding="utf-8"))
    for key in ("name", "publisher", "publisher_display_name", "display_name"):
        if not str(data.get(key, "")).strip():
            raise SystemExit(f"{IDENTITY} : « {key} » manquant")
    return data


def station_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def package_version(version: str) -> str:
    """X.Y.Z -> X.Y.Z.0 (le Store exige 0 en dernier nombre)."""
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"version de la station illisible : {version}")
    return ".".join(parts) + ".0"


def commands() -> dict[str, str]:
    """Commande -> module lancé par `python -m` (toutes ont un `if __name__ == "__main__"`)."""
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    return {name: target.split(":")[0] for name, target in scripts.items() if name not in SERVICES}


def manifest(ident: dict[str, str], version: str) -> str:
    vis = ('Square150x150Logo="Assets\\Square150x150Logo.png" Square44x44Logo="Assets\\Square44x44Logo.png" '
           'BackgroundColor="transparent"')
    display = escape(ident["display_name"])
    # Le Store refuse plus de 8 applications et toute application cachée du menu Démarrer (AppListEntry="none") :
    # UNE application porte TOUS les alias (aiguillage par le nom de l'alias, trxstation/store_cli.py) et la station
    # a sa propre entrée visible « openRemoteTRX station » (un clic = démarrer la station).
    aliases = "\n".join(f'            <uap5:ExecutionAlias Alias="{command}.exe"/>' for command in commands())
    apps = [f"""    <Application Id="Console" Executable="python\\python.exe" EntryPoint="Windows.FullTrustApplication"
      uap10:Parameters="-m trxstation.store_cli">
      <uap:VisualElements DisplayName="{display}" Description={quoteattr(DESCRIPTIONS[CONSOLE])} {vis}/>
      <Extensions>
        <uap5:Extension Category="windows.appExecutionAlias">
          <uap5:AppExecutionAlias>
{aliases}
          </uap5:AppExecutionAlias>
        </uap5:Extension>
      </Extensions>
    </Application>"""]
    # Station : lanceur SANS paramètre (la tâche de démarrage ignore uap10:Parameters), jamais d'alias (un alias de
    # pythonw avec paramètres ne lance rien) ; démarrée aussi par openRemoteTRX Console (shell:AppsFolder\\…!Supervisor).
    apps.append(f"""    <Application Id="Supervisor" Executable="python\\{LAUNCHER}" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="{display} station" Description="Démarre la station openRemoteTRX (sans fenêtre ; déjà en marche = rien)" {vis}/>
      <Extensions>
        <desktop:Extension Category="windows.startupTask">
          <desktop:StartupTask TaskId="openRemoteTRXStation" Enabled="true" DisplayName="{display} station"/>
        </desktop:Extension>
      </Extensions>
    </Application>""")
    # Pare-feu : réseaux PRIVÉS seulement, par programme (page web, console réseau, WebRTC à ports variables).
    firewall = "\n".join(f"""    <desktop2:Extension Category="windows.firewallRules">
      <desktop2:FirewallRules Executable="python\\{exe}">
        <desktop2:Rule Direction="in" IPProtocol="TCP" Profile="private"/>
        <desktop2:Rule Direction="in" IPProtocol="UDP" Profile="private"/>
      </desktop2:FirewallRules>
    </desktop2:Extension>""" for exe in ("python.exe", "pythonw.exe", LAUNCHER))
    resources = "".join(f'<Resource Language="{lang}"/>' for lang in LANGUAGES)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:uap5="http://schemas.microsoft.com/appx/manifest/uap/windows10/5"
  xmlns:uap10="http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
  xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
  xmlns:desktop2="http://schemas.microsoft.com/appx/manifest/desktop/windows10/2"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap uap5 uap10 desktop desktop2 rescap">
  <Identity Name={quoteattr(ident["name"])} Publisher={quoteattr(ident["publisher"])} Version="{version}" ProcessorArchitecture="x64"/>
  <Properties>
    <DisplayName>{display}</DisplayName>
    <PublisherDisplayName>{escape(ident["publisher_display_name"])}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="{MIN_WINDOWS}" MaxVersionTested="{MAX_TESTED}"/>
  </Dependencies>
  <Resources>{resources}</Resources>
  <Applications>
{chr(10).join(apps)}
  </Applications>
  <Extensions>
{firewall}
  </Extensions>
  <Capabilities><rescap:Capability Name="runFullTrust"/></Capabilities>
</Package>
"""


BOOT_MODULE = '''# Lanceur de la station du paquet MSIX (fabriqué par scripts/build_msix.py) : lu par trx_boot.pth à chaque démarrage
# de Python ; n'agit que pour trx-station.exe lancé SANS argument (tâche de démarrage, openRemoteTRX Console menu 1.1).
import os
import sys

if os.path.basename(sys.executable).lower() == "trx-station.exe" and sys.argv in ([], [""]):
    from trxstation.store_boot import maybe_boot
    maybe_boot()
'''
# Les lignes « import » d'un ._pth sont IGNORÉES (essai S0) : seul `import site` compte, puis les .pth de site-packages.
PTH = f"python{PY_TAG}.zip\n.\nLib\\site-packages\nimport site\n"


# --------------------------------------------------------------------------- outils


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    folder = Path(base) / "trx-remote-build"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def fetch(url: str, expected: str, name: str) -> Path:
    """Téléchargé une fois ; refusé si l'empreinte diffère (jamais contourné)."""
    path = cache_dir() / name
    if not path.exists() or sha256(path) != expected:
        print(f"Téléchargement : {url}", flush=True)
        part = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(url, timeout=120) as response, part.open("wb") as out:   # noqa: S310 (adresse fixe)
            shutil.copyfileobj(response, out)
        got = sha256(part)
        if got != expected:
            part.unlink(missing_ok=True)
            raise SystemExit(f"EMPREINTE DIFFÉRENTE pour {url} : {got} (attendu {expected}). Fabrication arrêtée.")
        os.replace(part, path)
    return path


def sdk_tool(name: str) -> Path:
    folder = cache_dir() / f"sdk-buildtools-{SDK_VERSION}"
    if not folder.exists():
        with zipfile.ZipFile(fetch(SDK_URL, SDK_SHA256, f"sdk-buildtools-{SDK_VERSION}.nupkg")) as archive:
            archive.extractall(folder)
    found = sorted(folder.glob(f"bin/*/x64/{name}"))
    if not found:
        raise SystemExit(f"{name} introuvable dans le paquet NuGet {SDK_VERSION}")
    return found[-1]


# --------------------------------------------------------------------------- fabrication


def build(out_dir: Path, *, freedv: Path | None) -> Path:
    ident = identity()
    version = package_version(station_version())
    work = Path(tempfile.mkdtemp(prefix="trx-msix-"))
    pkg, src = work / "pkg", work / "src"
    src.mkdir()
    try:
        # 1. Station : copie propre du dernier commit
        archive = work / "src.tar"
        run(["git", "-C", str(ROOT), "archive", "--format=tar", "-o", str(archive), "HEAD"])
        with tarfile.open(archive) as tar:
            tar.extractall(src, filter="data")
        committed = tomllib.loads((src / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        if package_version(committed) != version:
            raise SystemExit(f"version du commit ({committed}) différente de la copie de travail : commiter d'abord")
        # 2. Python embarqué
        with zipfile.ZipFile(fetch(PY_EMBED_URL, PY_EMBED_SHA256, f"python-{PY_VERSION}-embed-amd64.zip")) as z:
            z.extractall(pkg / "python")
        python = pkg / "python"
        (python / f"python{PY_TAG}._pth").write_text(PTH, encoding="ascii")
        shutil.copy2(python / "pythonw.exe", python / LAUNCHER)
        (python / LAUNCHER.replace(".exe", "._pth")).write_text(PTH, encoding="ascii")
        # 3. Modules (roues Windows x64 de CE Python, empreintes vérifiées) puis la station
        site = python / "Lib" / "site-packages"
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "--require-hashes",
             "--no-deps", "--only-binary=:all:", "--platform", "win_amd64", "--implementation", "cp",
             "--python-version", PY_VERSION.rsplit(".", 1)[0], "--abi", f"cp{PY_TAG}", "--target", str(site),
             "-r", str(src / "requirements.lock")])
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "--no-deps",
             "--no-build-isolation", "--target", str(site), str(src)])
        shutil.rmtree(site / "bin", ignore_errors=True)              # lanceurs .exe de pip : inutiles (alias)
        (site / "_trx_boot.py").write_text(BOOT_MODULE, encoding="utf-8")
        (site / "trx_boot.pth").write_text("import _trx_boot\n", encoding="ascii")
        # 4. FreeDV (facultatif), licence, images
        if freedv is not None:
            if not (freedv / "radae_rx.exe").exists():
                raise SystemExit(f"{freedv} : pas de radae_rx.exe (dossier fabriqué par compiler-freedv.sh --windows)")
            shutil.copytree(freedv, pkg / "freedv")
        else:
            print("ATTENTION : paquet SANS décodeurs FreeDV (--freedv DOSSIER pour les inclure)", flush=True)
        shutil.copy2(src / "LICENSE", pkg / "LICENSE.txt")
        from PIL import Image
        logo = Image.open(LOGO).convert("RGBA")
        (pkg / "Assets").mkdir()
        for name, size in (("StoreLogo", 50), ("Square44x44Logo", 44), ("Square150x150Logo", 150)):
            logo.resize((size, size), Image.LANCZOS).save(pkg / "Assets" / f"{name}.png")
        # 5. Manifeste et paquet
        (pkg / "AppxManifest.xml").write_text(manifest(ident, version), encoding="utf-8")
        out_dir.mkdir(parents=True, exist_ok=True)
        msix = out_dir / f"openRemoteTRX-{version}-x64.msix"
        run([str(sdk_tool("makeappx.exe")), "pack", "/o", "/d", str(pkg), "/p", str(msix)])
        return msix
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_certificate(out_dir: Path) -> Path:
    """Certificat d'ESSAI (sujet = publisher de l'identité) : jamais envoyé au Store. À approuver sur le PC d'essai
    (Personnes autorisées de l'ordinateur local) avec le .cer."""
    subject = identity()["publisher"]
    pfx, cer = out_dir / "msix-essai.pfx", out_dir / "msix-essai.cer"
    password = os.environ.get("TRX_MSIX_PFX_PASSWORD") or "essai"
    script = (
        f"$c = New-SelfSignedCertificate -Type Custom -Subject '{subject}' -KeyUsage DigitalSignature "
        "-FriendlyName 'openRemoteTRX essai MSIX' -CertStoreLocation Cert:\\CurrentUser\\My "
        "-TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}');"
        f"$p = ConvertTo-SecureString -String $env:TRX_MSIX_PFX_PASSWORD -Force -AsPlainText;"
        f"Export-PfxCertificate -Cert $c -FilePath '{pfx}' -Password $p | Out-Null;"
        f"Export-Certificate -Cert $c -FilePath '{cer}' | Out-Null")
    out_dir.mkdir(parents=True, exist_ok=True)
    run(["powershell", "-NoProfile", "-Command", script], env={**os.environ, "TRX_MSIX_PFX_PASSWORD": password})
    print(f"Certificat d'essai : {pfx} (mot de passe : TRX_MSIX_PFX_PASSWORD, « essai » par défaut) et {cer}")
    return pfx


def sign(msix: Path, pfx: Path) -> None:
    password = os.environ.get("TRX_MSIX_PFX_PASSWORD") or "essai"
    run([str(sdk_tool("signtool.exe")), "sign", "/fd", "SHA256", "/f", str(pfx), "/p", password, str(msix)])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paquet MSIX de la station (Microsoft Store)")
    ap.add_argument("--output", type=Path, default=DIST, help="dossier du paquet (dist par défaut)")
    ap.add_argument("--freedv", type=Path, help="décodeurs FreeDV pour Windows (compiler-freedv.sh --windows)")
    ap.add_argument("--signer", type=Path, help="ESSAI LOCAL : signer avec ce .pfx (jamais pour le Store)")
    ap.add_argument("--certificat-essai", action="store_true", help="fabrique dist\\msix-essai.pfx / .cer puis signe")
    ap.add_argument("--manifeste", action="store_true", help="affiche seulement le manifeste")
    args = ap.parse_args(argv)
    if args.manifeste:
        print(manifest(identity(), package_version(station_version())))
        return 0
    if sys.platform != "win32":
        raise SystemExit("makeappx ne tourne que sous Windows")
    msix = build(args.output, freedv=args.freedv)
    pfx = test_certificate(args.output) if args.certificat_essai else args.signer
    if pfx is not None:
        sign(msix, pfx)
        print(f"Paquet d'ESSAI signé : {msix} (ne pas l'envoyer au Store)")
    else:
        print(f"Paquet pour le Store (non signé) : {msix}")
    print(f"Taille : {msix.stat().st_size / 1e6:.0f} Mo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
