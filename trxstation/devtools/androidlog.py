# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Analyse d'un journal Android envoyé par un bêta-testeur : `trx-journal-android [fichier]`.

Fichiers acceptés (docs/site/android/journaux.html) : rapport de bug Android (`bugreport-….zip` ou `.txt`), journal
filtré `journal-openremotetrx.txt` (UTF-16 s'il vient de PowerShell 5), journal complet `adb logcat -d`.

Sans fichier donné, cherche les journaux récents dans le dossier Téléchargements (Windows, Debian) puis dans
/sdcard/Download d'un téléphone branché (adb), demande lequel analyser, ou le chemin. Avec un téléphone branché,
peut aussi lire son journal actuel.

Rapport : à l'écran et en HTML à côté du fichier ; adresses e-mail, IP, MAC et réseaux Wi-Fi masqués. Le fichier
d'origine n'est ni modifié ni envoyé ailleurs (il contient des données personnelles du testeur).
"""
from __future__ import annotations

import argparse
import fnmatch
import html
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from trxstation.answers import yes_no

APP = "com.rfdiy.openremotetrx"
PATTERNS = ("bugreport*.zip", "bugreport*.txt", "dumpstate*.zip", "journal*.txt", "*logcat*.txt", "*logcat*.log")
PHONE_DOWNLOAD = "/sdcard/Download"
MAX_ERRORS = 30                                # erreurs écrites par l'application : les plus fréquentes
MAX_DETAILS = 25                               # lignes gardées par constat (pile d'appels, extrait)

# 10-30 14:01:59.123  1000  1234  1250 E Tag : message ; « -v uid » ajoute une colonne, « -v year » l'année
LINE = re.compile(r"^(?:\d{4}-)?(\d\d-\d\d \d\d:\d\d:\d\d)(?:\.\d+)?\s+(?:\S+\s+)??(\d+)\s+\d+\s+([VDIWEFA])\s+"
                  r"(.*?)\s*: ?(.*)$")


@dataclass
class Entry:
    time: str
    pid: int
    level: str
    tag: str
    msg: str


def parse_line(line: str) -> Entry | None:
    m = LINE.match(line.rstrip("\r\n"))
    if not m:
        return None
    return Entry(m.group(1), int(m.group(2)), m.group(3), m.group(4).strip(), m.group(5))


# ---------------------------------------------------------------------------------------------- données personnelles
_REDACT = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[e-mail]"),
    (re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b"), "[MAC]"),
    (re.compile(r"\b(?!127\.0\.0\.1\b)(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
    (re.compile(r"(SSID[\"']?\s*[:=]\s*)\"[^\"]*\"", re.I), r'\1"[Wi-Fi]"'),
    (re.compile(r"(SSID[\"']?\s*[:=]\s*)(?!\")[^,\s}]+", re.I), r"\1[Wi-Fi]"),
    (re.compile(r"(Account \{name=)[^,}]+"), r"\1[compte]"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACT:
        text = pattern.sub(repl, text)
    return text


# ------------------------------------------------------------------------------------------------- explications
HINTS: list[tuple[re.Pattern[str], str]] = [(re.compile(p, re.I), h) for p, h in [
    (r"INSTALL_FAILED_UPDATE_INCOMPATIBLE|signatures do not match",
     "Une version signée autrement (debug, APK) est déjà installée : la désinstaller, puis installer depuis le Play Store."),
    (r"INSTALL_FAILED_INSUFFICIENT_STORAGE", "Place insuffisante sur le téléphone."),
    (r"INSTALL_FAILED_OLDER_SDK|requires newer sdk", "Android trop ancien : il faut Android 10 ou plus."),
    (r"INSTALL_FAILED_NO_MATCHING_ABIS", "Processeur non pris en charge par les bibliothèques WebRTC du paquet."),
    (r"INSTALL_FAILED_VERSION_DOWNGRADE", "Une version plus récente est déjà installée : la désinstaller d'abord."),
    (r"INSTALL_FAILED_USER_RESTRICTED", "Installation bloquée par le téléphone (profil professionnel, contrôle parental, "
                                        "réglage de sécurité)."),
    (r"DF-DFERH-01|DF-DLA-\d+|DF-BPA-\d+", "Erreur interne du Play Store : Paramètres > Applis > Google Play Store > "
                                          "Stockage > Vider le cache, puis réessayer."),
    (r"item not found|not available|not owned|no.*eligib", "Compte non inscrit au test, mauvais compte actif dans le "
                                                           "Play Store, ou version pas encore disponible pour les testeurs."),
    (r"ForegroundServiceStartNotAllowedException", "Service lancé alors que l'application était en arrière-plan : "
                                                    "Android 12+ l'interdit (RigService)."),
    (r"MissingForegroundServiceTypeException|FOREGROUND_SERVICE_MICROPHONE|Starting FGS with type",
     "Service au premier plan refusé : type (micro, lecture) ou autorisation du micro manquante au démarrage."),
    (r"RECORD_AUDIO|Permission Denial", "Autorisation refusée (micro, notifications…) : vérifier dans les réglages "
                                        "de l'application."),
    (r"OutOfMemoryError", "Mémoire de l'application épuisée."),
    (r"SSLHandshake|CertPathValidator|CertificateException|fingerprint", "Certificat de la station refusé "
                                                                         "(empreinte changée ? refaire l'appairage)."),
    (r"UnknownHostException|ConnectException|SocketTimeoutException|ENETUNREACH",
     "Station injoignable depuis ce réseau (adresse, VPN, port ouvert ?)."),
    (r"lowmemorykiller|lmkd|low memory", "Application tuée par Android faute de mémoire."),
    (r"has died.*(cch|cached|empty)|freezer|battery|restricted bucket",
     "Arrêtée en arrière-plan par l'économie d'énergie : régler la batterie de l'application sur « Sans restriction »."),
    (r"libjingle_peerconnection|webrtc", "Plantage dans WebRTC (audio, connexion) : joindre le rapport au ticket."),
]]


def hint(text: str) -> str | None:
    for pattern, h in HINTS:
        if pattern.search(text):
            return h
    return None


# ------------------------------------------------------------------------------------------------------- analyse
@dataclass
class Finding:
    kind: str                                   # installation, plantage, blocage, natif, arret, erreur
    title: str
    details: list[str] = field(default_factory=list)
    count: int = 1
    first: str = ""
    last: str = ""

    @property
    def advice(self) -> str | None:
        return hint(self.title + "\n" + "\n".join(self.details))


KIND_LABELS = {
    "plantage": "Plantage de l'application",
    "natif": "Plantage natif (WebRTC, audio)",
    "blocage": "Application bloquée (ANR)",
    "installation": "Installation (Play Store)",
    "arret": "Application arrêtée par Android",
    "erreur": "Erreurs écrites par l'application",
}

_DIGITS = re.compile(r"\d+")
_PID = re.compile(rf"(?:Start proc |pid[: ]\s*)(\d+)[:, ].{{0,80}}{re.escape(APP)}|{re.escape(APP)}.{{0,10}}PID: (\d+)")
_WEBRTC_TAG = re.compile(r"webrtc|peerconnection|javaaudio|audiorecord|audiotrack", re.I)


class Analyzer:
    """Lit un journal ligne à ligne (fichiers de 100 Mo : rien n'est gardé en entier)."""

    def __init__(self) -> None:
        self.findings: dict[tuple[str, str], Finding] = {}
        self.pids: set[int] = set()
        self.device: dict[str, str] = {}
        self.lines = 0
        self.entries = 0
        self.first = ""
        self.last = ""
        self._crash: dict[int, list[Entry]] = {}       # bloc AndroidRuntime en cours, par processus
        self._native: list[str] | None = None
        self._native_time = ""
        self._anr: Finding | None = None
        self._anr_left = 0
        self._package_left = 0

    # -- résultats
    def add(self, kind: str, title: str, details: list[str], when: str) -> None:
        key = (kind, _DIGITS.sub("#", title)[:200])
        f = self.findings.get(key)
        if f is None:
            self.findings[key] = Finding(kind, title, details[:MAX_DETAILS], 1, when, when)
        else:
            f.count += 1
            f.last = when

    def sorted_findings(self) -> list[Finding]:
        """Par catégorie, les plus fréquents d'abord ; erreurs écrites limitées aux MAX_ERRORS plus fréquentes."""
        order = list(KIND_LABELS)
        found = sorted(self.findings.values(), key=lambda f: (order.index(f.kind), -f.count))
        errors = [f for f in found if f.kind == "erreur"]
        return [f for f in found if f.kind != "erreur"] + errors[:MAX_ERRORS]

    # -- lecture
    def feed(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.lines += 1
            entry = parse_line(line)
            if entry is None:
                self._header(line)
                continue
            self.entries += 1
            self.first = self.first or entry.time
            self.last = entry.time
            self._entry(entry)
        self.close()

    def close(self) -> None:
        for pid in list(self._crash):
            self._end_crash(pid)
        self._end_native()

    def _header(self, line: str) -> None:
        """Lignes hors journal du rapport de bug : propriétés du téléphone, paquet installé."""
        m = re.match(r"\[(ro\.product\.model|ro\.product\.manufacturer|ro\.build\.version\.release|"
                     r"ro\.build\.version\.sdk|ro\.build\.fingerprint)\]: \[(.*)\]", line)
        if m:
            self.device.setdefault(m.group(1), m.group(2))
            return
        if line.startswith("== dumpstate:"):
            self.device.setdefault("dumpstate", line[13:].strip())
        if f"Package [{APP}]" in line:
            self._package_left = 60
            return
        if self._package_left:
            self._package_left -= 1
            for key in ("versionName", "versionCode", "installerPackageName", "installInitiatingPackageName"):
                m = re.search(rf"\b{key}=(\S+)", line)
                if m:
                    self.device.setdefault("app." + key, m.group(1))

    def _entry(self, e: Entry) -> None:
        msg = e.msg
        # processus de l'application
        if APP in msg:
            for m in _PID.finditer(msg):
                self.pids.add(int(m.group(1) or m.group(2)))

        # plantage Java/Kotlin
        if e.tag == "AndroidRuntime":
            if msg.startswith("FATAL EXCEPTION"):
                self._end_crash(e.pid)
                self._crash[e.pid] = [e]
                return
            if e.pid in self._crash:
                self._crash[e.pid].append(e)
                if len(self._crash[e.pid]) > 200:
                    self._end_crash(e.pid)
                return
        elif e.pid in self._crash:
            self._end_crash(e.pid)

        # plantage natif (crash_dump, tag DEBUG)
        if e.tag in ("DEBUG", "libc", "crash_dump64", "crash_dump32") and e.level == "F":
            if msg.startswith("*** *** ***"):
                self._end_native()
                self._native, self._native_time = [], e.time
                return
            if self._native is not None:
                self._native.append(msg)
                if len(self._native) > 120:
                    self._end_native()
                return
        elif self._native is not None and e.tag == "DEBUG":
            self._native.append(msg)
            return

        # ANR
        if e.tag == "ActivityManager" and msg.startswith("ANR in ") and APP in msg:
            self._anr_left = 15
            self.add("blocage", msg, [], e.time)
            self._anr = self.findings[("blocage", _DIGITS.sub("#", msg)[:200])]
            return
        if self._anr is not None and self._anr_left and e.tag == "ActivityManager":
            self._anr_left -= 1
            if re.match(r"(Reason|Subject|PID|Load|Frozen|Parent)", msg) and len(self._anr.details) < MAX_DETAILS:
                self._anr.details.append(msg)
            return

        # arrêt par Android
        if APP in msg and (re.search(r"has died|Killing \d+:" + re.escape(APP), msg)
                           or e.tag in ("lowmemorykiller", "lmkd")):
            self.add("arret", msg, [], e.time)
            return

        # installation
        # (Finsky = Play Store : beaucoup d'erreurs sur d'autres applications ; seulement la nôtre ou un code d'erreur)
        install_tag = e.tag.startswith("Finsky") or e.tag in ("PackageInstaller", "PackageManager", "InstallQueue")
        if "INSTALL_FAILED" in msg or "INSTALL_PARSE_FAILED" in msg or re.search(r"\bDF-[A-Z]+-\d+", msg) or (
                install_tag and APP in msg and (e.level in "EF" or re.search(r"error|fail|mismatch|do not match", msg, re.I))):
            self.add("installation", f"{e.tag} : {msg}", [], e.time)
            return

        # erreurs de l'application (son processus, ou WebRTC dans son processus)
        if e.level in "EF" and (e.pid in self.pids or (not self.pids and _WEBRTC_TAG.search(e.tag))):
            self.add("erreur", f"{e.tag} : {msg}", [], e.time)

    def _end_crash(self, pid: int) -> None:
        block = self._crash.pop(pid, None)
        if not block:
            return
        lines = [x.msg for x in block]
        text = "\n".join(lines)
        if APP not in text:
            return                              # plantage d'une autre application
        self.pids.add(pid)
        exc = next((x for x in lines[1:] if not x.startswith(("Process:", "\tat ", "at ", "\t..."))
                    and x.strip()), "exception inconnue")
        keep = [x for x in lines[1:] if x.startswith(("Process:", "Caused by")) or APP in x
                or (x.strip() and not x.strip().startswith("at ") and not x.startswith("\t"))]
        self.add("plantage", exc.strip(), keep, block[0].time)

    def _end_native(self) -> None:
        lines, self._native = self._native, None
        if not lines:
            return
        text = "\n".join(lines)
        if APP not in text:
            return
        signal = next((x for x in lines if x.startswith("signal ")), "signal inconnu")
        abort = [x for x in lines if x.startswith("Abort message")]
        frames = native_frames(lines)
        self.add("natif", signal, abort + frames, self._native_time)

    def tombstone(self, name: str, text: str) -> None:
        """Fichier FS/data/tombstones/… d'un rapport de bug : plantage natif."""
        if f">>> {APP}" not in text and f"Cmdline: {APP}" not in text:
            return
        lines = text.splitlines()
        signal = next((x for x in lines if x.startswith("signal ")), "signal inconnu")
        frames = native_frames(lines)
        timestamp = next((x[10:].strip() for x in lines if x.startswith("Timestamp:")), name)
        abort = [x for x in lines if x.startswith("Abort message")][:1]
        self.add("natif", signal, abort + frames, timestamp)


_NATIVE_FRAME = re.compile(r"\s*#\d+ pc")
_NOISE_FRAME = re.compile(r"/libart\.so|/libc\.so(?! \(abort)|/libbase\.so|/libutils\.so")


def native_frames(lines: list[str], limit: int = 15) -> list[str]:
    """Pile native utile : sans les étages internes d'Android (interpréteur ART…) qui cachent nos fonctions ; les
    chemins /data/app/~~…/ (aléatoires) raccourcis."""
    frames = [x.strip() for x in lines if _NATIVE_FRAME.match(x) and not _NOISE_FRAME.search(x)]
    return [re.sub(r"/data/app/[^ ]*?/(base\.apk)", r"\1", f) for f in frames[:limit]]


# -------------------------------------------------------------------------------------------- lecture des fichiers
def decode_lines(raw: io.BufferedIOBase | io.RawIOBase) -> Iterator[str]:
    """Lignes d'un flux d'octets : UTF-16 (PowerShell 5, avec BOM) ou UTF-8, octets invalides remplacés."""
    stream = io.BufferedReader(raw) if not isinstance(raw, io.BufferedReader) else raw   # type: ignore[arg-type]
    head = stream.peek(4)[:4]
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif len(head) >= 2 and head[1:2] == b"\x00" and head[0:1] != b"\x00":
        encoding = "utf-16-le"
    else:
        encoding = "utf-8-sig"
    yield from io.TextIOWrapper(stream, encoding=encoding, errors="replace", newline=None)


def analyze_file(path: Path) -> Analyzer:
    analyzer = Analyzer()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            main = None
            if "main_entry.txt" in names:
                main = z.read("main_entry.txt").decode("utf-8", "replace").strip()
            if main not in names:
                texts = [n for n in names if n.endswith(".txt") and "/" not in n and n.startswith(("bugreport", "dumpstate"))]
                main = max(texts, key=lambda n: z.getinfo(n).file_size) if texts else None
            if main is None:
                raise ValueError("ce zip n'est pas un rapport de bug Android (aucun bugreport-….txt dedans)")
            with z.open(main) as f:
                analyzer.feed(decode_lines(f))          # type: ignore[arg-type]
            for n in names:
                if "tombstone" in n and not n.endswith((".pb", "/")):
                    analyzer.tombstone(n, z.read(n).decode("utf-8", "replace"))
    else:
        with open(path, "rb") as f:
            analyzer.feed(decode_lines(f))              # type: ignore[arg-type]
    return analyzer


# ------------------------------------------------------------------------------------------------------- rapport
def device_lines(a: Analyzer) -> list[str]:
    d = a.device
    out = []
    model = " ".join(x for x in (d.get("ro.product.manufacturer"), d.get("ro.product.model")) if x)
    if model:
        out.append(f"Téléphone : {model}")
    if d.get("ro.build.version.release"):
        out.append(f"Android : {d['ro.build.version.release']} (API {d.get('ro.build.version.sdk', '?')})")
    if d.get("app.versionName"):
        installer = d.get("app.installerPackageName") or d.get("app.installInitiatingPackageName") or "?"
        source = {"com.android.vending": "Play Store", "null": "adb ou APK"}.get(installer, installer)
        out.append(f"Application : {d['app.versionName']} (versionCode {d.get('app.versionCode', '?')}), "
                   f"installée par {source}")
    elif d:
        out.append("Application : non installée sur ce téléphone")
    if d.get("dumpstate"):
        out.append(f"Rapport fait le : {d['dumpstate']}")
    if a.first:
        out.append(f"Période du journal : {a.first} -> {a.last} ({a.entries} lignes de journal sur {a.lines})")
    return out


def text_report(a: Analyzer, source: str) -> str:
    out = [f"Analyse de {source}", ""] + device_lines(a) + [""]
    findings = a.sorted_findings()
    if not a.entries:
        out.append("Aucune ligne de journal Android reconnue dans ce fichier.")
    elif not findings:
        out.append(f"Rien trouvé concernant {APP} (ni plantage, ni blocage, ni échec d'installation).")
        if not a.pids:
            out.append("L'application n'apparaît pas du tout : journal pris trop tard, ou problème non reproduit avant.")
    kind = None
    for f in findings:
        if f.kind != kind:
            kind = f.kind
            out += ["", f"== {KIND_LABELS[kind]} =="]
        when = f.first if f.count == 1 else f"{f.count} fois, {f.first} -> {f.last}"
        out.append(f"- [{when}] {f.title}")
        out += [f"      {d}" for d in f.details]
        if f.advice:
            out.append(f"   => {f.advice}")
    return redact("\n".join(out)) + "\n"


def html_report(a: Analyzer, source: str) -> str:
    e = html.escape
    parts = [f"<h1>Journal Android : {e(source)}</h1>", "<ul>" + "".join(f"<li>{e(x)}</li>" for x in device_lines(a)) + "</ul>"]
    findings = a.sorted_findings()
    if not findings:
        parts.append(f"<p>Rien trouvé concernant {APP}.</p>")
    kind = None
    for f in findings:
        if f.kind != kind:
            if kind is not None:
                parts.append("</div>")
            kind = f.kind
            parts.append(f'<h2>{e(KIND_LABELS[kind])}</h2><div class="groupe">')
        when = f.first if f.count == 1 else f"{f.count} fois, {f.first} → {f.last}"
        parts.append(f'<div class="carte"><p><span class="doux">{e(when)}</span><br><strong>{e(f.title)}</strong></p>')
        if f.details:
            parts.append("<pre>" + e("\n".join(f.details)) + "</pre>")
        if f.advice:
            parts.append(f'<p class="conseil">{e(f.advice)}</p>')
        parts.append("</div>")
    if kind is not None:
        parts.append("</div>")
    body = redact("\n".join(parts))
    return ("<!doctype html>\n<html lang=\"fr\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Journal Android</title><style>"
            ":root{color-scheme:dark}body{margin:0;background:#0f141c;color:#dbe3ee;font:15px/1.5 system-ui,sans-serif}"
            "main{max-width:60rem;margin:0 auto;padding:1rem 16px}h2{border-bottom:1px solid #2a3445}"
            ".carte{background:#171e29;border:1px solid #2a3445;border-radius:.5rem;padding:.4rem .8rem;margin:.6rem 0}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem;background:#0b1017;padding:.5rem}"
            ".doux{color:#9aa8bb}.conseil{border-left:4px solid #3fae72;padding-left:.6rem}"
            f"</style></head><body><main>\n{body}\n</main></body></html>\n")


# ---------------------------------------------------------------------------------------------- recherche du fichier
@dataclass
class Candidate:
    name: str
    size: int
    mtime: float
    path: Path | None = None                     # fichier local
    phone_path: str | None = None                # fichier du téléphone (adb)

    def describe(self, now: float | None = None) -> str:
        age = max(0.0, (now or time.time()) - self.mtime)
        when = (f"il y a {int(age // 60)} min" if age < 3600 else f"il y a {int(age // 3600)} h" if age < 172800
                else f"il y a {int(age // 86400)} jours")
        where = "téléphone" if self.phone_path else str(self.path.parent if self.path else "")
        return f"{self.name} ({self.size / 1e6:.1f} Mo, {when}, {where})"


def download_dirs(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    dirs = [home / "Downloads", home / "Téléchargements"]
    user_dirs = home / ".config" / "user-dirs.dirs"           # Debian : dossier choisi par le bureau
    try:
        m = re.search(r'^XDG_DOWNLOAD_DIR="(.*)"', user_dirs.read_text(encoding="utf-8"), re.M)
        if m:
            dirs.insert(0, Path(m.group(1).replace("$HOME", str(home))))
    except OSError:
        pass
    seen, out = set(), []
    for d in dirs:
        key = os.path.normcase(str(d))
        if key not in seen and d.is_dir():
            seen.add(key)
            out.append(d)
    return out


def matches(name: str) -> bool:
    return any(fnmatch.fnmatch(name.lower(), p) for p in PATTERNS)


def local_candidates(dirs: Iterable[Path]) -> list[Candidate]:
    out = []
    for d in dirs:
        try:
            for p in d.iterdir():
                if p.is_file() and matches(p.name):
                    st = p.stat()
                    out.append(Candidate(p.name, st.st_size, st.st_mtime, path=p))
        except OSError:
            continue
    return out


def find_adb() -> str | None:
    found = shutil.which("adb")
    if found:
        return found
    exe = "adb.exe" if os.name == "nt" else "adb"
    places = [Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools",
              Path.home() / "Android" / "Sdk" / "platform-tools"] + [d / "platform-tools" for d in download_dirs()]
    return next((str(p / exe) for p in places if (p / exe).is_file()), None)


def adb_run(adb: str, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([adb, *args], capture_output=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def phone_connected(adb: str) -> bool:
    try:
        out = adb_run(adb, "devices", timeout=15).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.strip().endswith("\tdevice") for line in out.splitlines()[1:])


def phone_candidates(adb: str) -> list[Candidate]:
    """Fichiers de /sdcard/Download (taille et date par stat : un appel pour tous)."""
    try:
        out = adb_run(adb, "shell", f"cd {PHONE_DOWNLOAD} && stat -c '%s %Y %n' *").stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and matches(parts[2]):
            found.append(Candidate(parts[2], int(parts[0]), float(parts[1]), phone_path=f"{PHONE_DOWNLOAD}/{parts[2]}"))
    return found


def pull(adb: str, cand: Candidate, dest: Path) -> Path:
    target = dest / cand.name
    result = adb_run(adb, "pull", cand.phone_path or "", str(target), timeout=600)
    if result.returncode != 0 or not target.is_file():
        raise OSError(result.stderr.decode("utf-8", "replace").strip() or "copie depuis le téléphone impossible")
    return target


def capture_logcat(adb: str, dest: Path) -> Path:
    target = dest / time.strftime("journal-telephone-%Y%m%d-%H%M.txt")
    result = adb_run(adb, "logcat", "-d", "-v", "threadtime", timeout=300)
    if result.returncode != 0:
        raise OSError(result.stderr.decode("utf-8", "replace").strip() or "lecture du journal impossible")
    target.write_bytes(result.stdout)
    return target


# ------------------------------------------------------------------------------------------------------ dialogue
def choose(candidates: list[Candidate], phone: bool, ask=input, say=print) -> Candidate | Path | str | None:
    """Fichier choisi (Candidate), chemin tapé (Path), « J » = journal actuel du téléphone, None = quitter."""
    candidates = sorted(candidates, key=lambda c: -c.mtime)
    if candidates:
        say(f"Journal trouvé : {candidates[0].describe()}")
        while True:
            answer = yes_no(ask("L'analyser ? [O/n] ") or "o")
            if answer is True:
                return candidates[0]
            if answer is False:
                break
            say("Répondre o ou n.")
    else:
        say("Aucun journal trouvé dans Téléchargements" + (" ni sur le téléphone." if phone else "."))
    for i, c in enumerate(candidates, 1):
        say(f"  {i}. {c.describe()}")
    if phone:
        say("  J. lire le journal actuel du téléphone branché")
    while True:
        text = ask("Numéro" + (", J" if phone else "") + " ou chemin du fichier (Entrée = quitter) : ").strip().strip('"')
        if not text:
            return None
        if text.isdigit() and 1 <= int(text) <= len(candidates):
            return candidates[int(text) - 1]
        if phone and text.upper() == "J":
            return "J"
        path = Path(text).expanduser()
        if path.is_file():
            return path
        say(f"Introuvable : {text}")


def report(path: Path, label: str, out: Path | None) -> int:
    try:
        analyzer = analyze_file(path)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Lecture impossible : {exc}")
        return 1
    print(text_report(analyzer, label))
    target = out or path.with_name(path.stem + "-analyse.html")
    try:
        target.write_text(html_report(analyzer, label), encoding="utf-8")
        print(f"Rapport HTML : {target}")
    except OSError as exc:
        print(f"Rapport HTML non écrit ({exc}).")
    print("Le journal d'origine contient des données personnelles du testeur : le supprimer après usage.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trx-journal-android", description=__doc__.splitlines()[0])
    parser.add_argument("fichier", nargs="?", type=Path, help="journal à analyser (sinon recherche et question)")
    parser.add_argument("--html", type=Path, help="chemin du rapport HTML (défaut : à côté du fichier)")
    parser.add_argument("--sans-telephone", action="store_true", help="ne pas chercher de téléphone branché")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")                   # console Windows : jamais d'arrêt sur un caractère

    if args.fichier:
        if not args.fichier.is_file():
            print(f"Introuvable : {args.fichier}")
            return 1
        return report(args.fichier, args.fichier.name, args.html)

    dirs = download_dirs()
    candidates = local_candidates(dirs)
    adb = None if args.sans_telephone else find_adb()
    phone = bool(adb) and phone_connected(adb)                    # type: ignore[arg-type]
    if phone:
        print("Téléphone branché : recherche dans " + PHONE_DOWNLOAD)
        candidates += phone_candidates(adb)                        # type: ignore[arg-type]
    try:
        picked = choose(candidates, phone)
    except (EOFError, KeyboardInterrupt):
        print()
        return 1
    if picked is None:
        return 1
    dest = dirs[0] if dirs else Path(tempfile.gettempdir())
    try:
        if picked == "J":
            print("Lecture du journal du téléphone…")
            path = capture_logcat(adb, dest)                       # type: ignore[arg-type]
            print(f"Journal enregistré : {path}")
        elif isinstance(picked, Candidate) and picked.phone_path:
            print("Copie depuis le téléphone…")
            path = pull(adb, picked, dest)                         # type: ignore[arg-type]
        else:
            path = picked.path if isinstance(picked, Candidate) else picked   # type: ignore[assignment]
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Téléphone : {exc}")
        return 1
    return report(path, path.name, args.html)                      # type: ignore[arg-type]


if __name__ == "__main__":
    sys.exit(main())
