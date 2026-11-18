# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Valise de qualification, version 0 (`trx-qualif --terrain`, docs/qualification-terrain-cahier-des-charges.md).

Ce que fait la v0 :
- une SESSION = un dossier `terrain-<modèle>-<date>` ; l'exploration et la qualification existantes y écrivent ;
- les essais de sécurité du guide (partie 3.5) sont JOUÉS À LA MAIN par le qualifieur et l'opérateur ; un
  OBSERVATEUR les chronomètre en relisant le PTT du poste par rigctld toutes les 200 ms ;
- un rapport zip pour Claude (`qualification.json`, `rapport.html`, `LISEZMOI-CLAUDE.md`, `empreintes.sha256`).

SÉCURITÉ : la v0 n'ajoute AUCUN chemin d'émission. L'observateur n'envoie QUE la lecture « t » (liste fermée
`OBSERVER_COMMANDS`, vérifiée à chaque envoi) et seulement à un rigctld en 127.0.0.1. Les émissions des essais sont
faites par la station elle-même (page, application, micro du poste), avec toutes ses sécurités.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import html
import ipaddress
import json
import os
import re
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .. import __version__
from ..answers import yes_no
from .bus import DONE, YES_NO, Bus, KeyboardClient, ask_typed, ask_word, bus_of
from .texts import _t

FORMAT = 1
OBSERVER_COMMANDS = frozenset({"t"})      # lecture du PTT, RIEN d'autre
OBSERVER_PERIOD_S = 0.2
MARK_SLACK_S = 1.0                        # repère tapé à la main : réaction humaine + une période d'observation


class ObserverError(RuntimeError):
    pass


# --------------------------------------------------------------------------- observateur (lecture seule)

class Observer:
    """Relit le PTT par rigctld ; garde les CHANGEMENTS (instant, valeur) : 1 émission, 0 réception, None illisible."""

    def __init__(self, host: str, port: int, *, period: float = OBSERVER_PERIOD_S, timeout: float = 1.0,
                 clock: Callable[[], float] = time.time) -> None:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise ObserverError("rigctld doit être en 127.0.0.1")
        self.host, self.port, self.period, self.timeout, self.clock = host, port, period, timeout, clock
        self.events: list[tuple[float, int | None]] = []
        self.reads = 0
        self.failures = 0
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    def _note(self, value: int | None) -> None:
        if not self.events or self.events[-1][1] != value:
            self.events.append((self.clock(), value))

    async def _send(self, command: str) -> str:
        if command not in OBSERVER_COMMANDS:
            raise ObserverError(f"commande refusée à l'observateur : {command!r}")
        if self._writer is None:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout)
        self._writer.write((command + "\n").encode("ascii"))
        await self._writer.drain()
        first = await self._line()
        if not first.endswith(":"):
            return first                         # réponse simple : « 0 », « 1 » ou « RPRT -n »
        value = ""                               # réponse étendue : « get_ptt: », « PTT: 0 », « RPRT 0 »
        for _ in range(8):
            line = await self._line()
            if line.startswith("RPRT"):
                return value or line
            value = line.rsplit(":", 1)[-1].strip()
        raise ConnectionError("réponse étendue sans RPRT")

    async def _line(self) -> str:
        line = await asyncio.wait_for(self._reader.readline(), self.timeout)
        if not line:
            raise ConnectionError("rigctld a fermé la connexion")
        return line.decode("ascii", "replace").strip()

    async def read_once(self) -> int | None:
        try:
            answer = await self._send("t")
        except (OSError, asyncio.TimeoutError, ConnectionError):
            self._close()
            return None
        return int(answer) if answer in ("0", "1") else None

    def _close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:                    # noqa: BLE001 : fermeture au mieux
                pass
        self._reader = self._writer = None

    async def run(self, stop: asyncio.Event) -> None:
        next_at = time.perf_counter()
        try:
            while not stop.is_set():
                value = await self.read_once()
                self.reads += 1
                if value is None:
                    self.failures += 1
                self._note(value)
                next_at += self.period
                delay = next_at - time.perf_counter()
                if delay < 0:
                    next_at = time.perf_counter()
                    delay = 0
                try:
                    await asyncio.wait_for(stop.wait(), delay)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._close()


# --------------------------------------------------------------------------- essais

@dataclass(frozen=True)
class Drill:
    id: str
    kind: str          # stop, tot, link, refusal, local, startup, reboot
    optional: bool = False
    bound_s: float = 0.0


DRILLS: tuple[Drill, ...] = (
    Drill("stop_page", "stop", bound_s=MARK_SLACK_S),
    Drill("tot", "tot", bound_s=2.0),
    Drill("wifi", "link", bound_s=2.5 + MARK_SLACK_S),
    Drill("screen_lock", "link", bound_s=2.5 + MARK_SLACK_S),
    Drill("out_of_band", "refusal"),
    Drill("local_operator", "local"),
    Drill("stop_dashboard", "stop", bound_s=MARK_SLACK_S),
    Drill("station_stop", "link", bound_s=2.0 + MARK_SLACK_S),
    Drill("startup", "startup"),
    Drill("reboot", "reboot", optional=True),
)
NEEDS_MARK = {"stop", "link"}


def analyse(events: list[tuple[float, int | None]], start: float, end: float, mark: float | None) -> dict:
    """Mesures d'un essai : début et fin d'émission vus, durée, délai depuis le repère, lectures illisibles."""
    tx_start = rx_after = None
    unreadable = False
    value: int | None = None                     # état au début de l'essai, puis état courant
    for ts, v in sorted(events, key=lambda e: e[0]):
        if ts > end:
            break
        if ts >= start:
            if v is None:
                unreadable = True
            if v == 1 and tx_start is None:
                tx_start = ts
            if v == 0 and tx_start is not None and rx_after is None:
                rx_after = ts
        value = v
        if ts < start and v == 1:
            tx_start = start                     # déjà en émission au début de l'essai
        elif ts < start:
            tx_start = None
    tx_seen = tx_start is not None
    out = {"tx_seen": tx_seen, "tx_start": tx_start, "rx_after": rx_after, "unreadable": unreadable,
           "still_tx_at_end": value == 1, "tx_duration_s": None, "delay_from_mark_s": None}
    if tx_start is not None and rx_after is not None:
        out["tx_duration_s"] = round(rx_after - tx_start, 3)
    if mark is not None and rx_after is not None and rx_after >= mark - 0.05:
        out["delay_from_mark_s"] = round(max(0.0, rx_after - mark), 3)
    return out


def judge(drill: Drill, m: dict, *, tot_s: float) -> tuple[str, str]:
    """(résultat MESURÉ : reussi / echec / non_mesure, raison en français pour le rapport)."""
    if m["still_tx_at_end"]:
        return "echec", "le poste était encore en émission à la fin de l'essai"
    if drill.kind in ("stop", "link"):
        if not m["tx_seen"]:
            return "non_mesure", "aucune émission vue pendant l'essai"
        d = m["delay_from_mark_s"]
        if d is None:
            return "non_mesure", "repère absent ou retour en réception avant le repère"
        return ("reussi" if d <= drill.bound_s else "echec"), f"réception {d:.2f} s après le repère (borne {drill.bound_s:.1f} s)"
    if drill.kind == "tot":
        dur = m["tx_duration_s"]
        if dur is None:
            return "non_mesure", "émission complète non vue"
        ok = abs(dur - tot_s) <= drill.bound_s
        return ("reussi" if ok else "echec"), f"émission coupée après {dur:.1f} s (TOT {tot_s:.0f} s ± {drill.bound_s:.0f})"
    if drill.kind in ("refusal", "startup"):
        return ("echec", "émission vue") if m["tx_seen"] else ("reussi", "aucune émission vue")
    if drill.kind == "local":
        return ("reussi", "émission locale vue") if m["tx_seen"] else ("non_mesure", "aucune émission locale vue")
    return ("echec", "émission vue") if m["tx_seen"] else ("non_mesure", "déclaratif (aucune mesure pendant l'arrêt du PC)")


def all_drills() -> tuple[Drill, ...]:
    """Essais à la main puis essais automatiques (lot T2)."""
    from .autodrills import AUTO_DRILLS
    return DRILLS + AUTO_DRILLS


def final_result(measured: str, declared_ok: bool | None) -> str:
    if measured == "echec" or declared_ok is False:
        return "echec"
    if measured == "reussi" and declared_ok:
        return "reussi"
    if measured == "non_mesure" and declared_ok:
        return "declare"
    return "incomplet"


# --------------------------------------------------------------------------- session

@dataclass
class Session:
    folder: Path
    model: int
    model_name: str = ""
    manufacturer: str = ""
    hamlib_version: str = ""
    backend_status: str = ""
    started: str = ""
    drills: dict[str, dict] = field(default_factory=dict)
    runs: list[dict] = field(default_factory=list)
    snapshots: dict[str, dict] = field(default_factory=dict)
    crashers: list[str] = field(default_factory=list)       # lectures qui font tomber rigctld (constat Hamlib)
    audio: dict = field(default_factory=dict)               # dernier contrôle de la carte son du poste (choix 9)
    connection: str = ""                                    # « antenne » ou « charge » (confirmé par l'opérateur)
    reception: dict = field(default_factory=dict)           # mesure de réception sur antenne (choix r)
    spectrum: dict = field(default_factory=dict)            # contrôle du spectre HF (choix s)
    filters: dict = field(default_factory=dict)             # préréglages FIL1 / 2 / 3 par le second port (choix f)

    FILE = "session.json"

    @classmethod
    def open(cls, folder: Path, **fields) -> "Session":
        path = folder / cls.FILE
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(folder=folder, **{k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "folder"})
        folder.mkdir(parents=True, exist_ok=True)
        s = cls(folder=folder, started=_now(), **fields)
        s.save()
        return s

    def save(self) -> None:
        data = asdict(self)
        data.pop("folder")
        tmp = self.folder / (self.FILE + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.folder / self.FILE)


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_ts(text: str) -> float | None:
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def journal_lines(state_dir: Path, start: float, end: float, redact: Callable[[str], str]) -> list[dict]:
    """Lignes des journaux JSON de la passerelle et du superviseur entre start et end (masquées)."""
    lines = []
    for name in ("passerelle", "superviseur"):
        path = state_dir / f"journal-{name}.jsonl"
        try:
            raw = path.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]
        except OSError:
            continue
        for line in raw:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            ts = _parse_ts(item.get("ts", ""))
            if ts is not None and start <= ts <= end:
                lines.append(json.loads(redact(json.dumps(item, ensure_ascii=False))))
    lines.sort(key=lambda i: i.get("ts", ""))
    return lines


def _redactor() -> Callable[[str], str]:
    from ..monlink.redact import Redactor
    return Redactor(os.urandom(16)).text


Ask = Callable[[str], str]


async def play_drill(drill: Drill, session: Session, *, host: str, port: int, tot_s: float, state_dir: Path,
                     ask: Ask = input, out: Callable[[str], None] = print, period: float = OBSERVER_PERIOD_S) -> dict:
    """Un essai : consignes, observation, repère, mesures, avis de l'opérateur ; enregistré dans la session."""
    out(_t(f"terrain.drill.{drill.id}.title"))
    out(_t(f"terrain.drill.{drill.id}.how", tot=f"{tot_s:.0f}"))
    out(_t("terrain.expected", text=_t(f"terrain.drill.{drill.id}.expected", tot=f"{tot_s:.0f}")))
    bus = bus_of(ask)
    if (await asyncio.to_thread(ask, _t("terrain.start_or_skip"))).strip().lower() in ("s", "skip"):
        return {}
    if drill.kind not in ("startup", "reboot") and await Observer(host, port, period=period).read_once() is None:
        out(_t("terrain.unreadable"))                    # station d'essai arrêtée : essai ni joué ni enregistré
        return {}
    observer = Observer(host, port, period=period)
    stop = asyncio.Event()
    task = asyncio.create_task(observer.run(stop))
    start = time.time()
    mark = None
    try:
        out(_t("terrain.observing"))
        if drill.kind in NEEDS_MARK:
            await asyncio.to_thread(ask_typed, ask, _t("terrain.mark_prompt"), DONE)
            mark = time.time()
        await asyncio.to_thread(ask_typed, ask, _t("terrain.end_prompt"), DONE)
        await asyncio.sleep(period * 2)          # dernière lecture après la fin annoncée
    finally:
        end = time.time()
        stop.set()
        await task
    m = analyse(observer.events, start, end, mark)
    measured, reason = judge(drill, m, tot_s=tot_s)
    out(_t("terrain.measured", result=_t(f"terrain.result.{measured}"), reason=reason))
    declared = yes_no(await asyncio.to_thread(ask_typed, ask, _t("terrain.declared_prompt"), YES_NO))
    note = (await asyncio.to_thread(ask, _t("terrain.note_prompt"))).strip()
    result = final_result(measured, declared)
    record = {
        "id": drill.id, "kind": drill.kind, "optional": drill.optional, "bound_s": drill.bound_s or None,
        "start": _iso(start), "end": _iso(end), "mark": _iso(mark),
        "measures": {k: (_iso(v) if k in ("tx_start", "rx_after") else v) for k, v in m.items()},
        "measured": measured, "reason": reason, "declared_ok": declared, "note": note, "result": result,
        "observer": {"period_s": period, "reads": observer.reads, "unreadable": observer.failures,
                     "changes": [[_iso(ts), v] for ts, v in observer.events]},
    }
    (session.folder / "essais").mkdir(exist_ok=True)
    redact = _redactor()
    record["note"] = redact(note)
    record["journal"] = journal_lines(state_dir, start - 2, end + 2, redact)
    (session.folder / "essais" / f"{drill.id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    session.drills[drill.id] = {k: record[k] for k in ("result", "measured", "reason", "declared_ok", "note")}
    session.save()
    out(_t("terrain.drill_saved", result=_t(f"terrain.result.{result}")))
    if bus is not None:
        bus.state(drill.id, result, mesure=measured, raison=reason)
    return record


# --------------------------------------------------------------------------- rapport

def verdict(session: Session) -> tuple[str, list[str]]:
    """Verdict PROPOSÉ (la décision reste à l'éditeur) et ses raisons."""
    reasons = []
    results = {d.id: session.drills.get(d.id, {}).get("result") for d in DRILLS}
    failed = [k for k, v in session.drills.items() if v.get("result") == "echec"]   # automatiques compris
    if failed:
        return "refuse", [f"essai {k} en échec" for k in failed]
    qualif = [r for r in session.runs if r.get("kind") == "qualif"]
    if not qualif:
        reasons.append("qualification Q1 non faite")
    elif qualif[-1].get("verdict") == "refuse":
        return "refuse", ["qualification Q1 : refus"]
    elif qualif[-1].get("verdict") != "validation_en_cours":
        reasons.append(f"qualification Q1 : {qualif[-1].get('verdict') or 'verdict inconnu'}")
    for d in DRILLS:
        r = results[d.id]
        if r is None and not d.optional:
            reasons.append(f"essai {d.id} non fait")
        elif r in ("incomplet",):
            reasons.append(f"essai {d.id} incomplet")
    return ("validation_en_cours" if not reasons else "incomplet"), reasons


def _qualif_verdict(folder: Path) -> str | None:
    """Statut du verdict de la qualification Q1 : `results.json` le range en `{"statut": …, "raisons": […]}` (lu
    comme une chaîne avant l'étape 256 : un refus passait pour « incomplet »)."""
    try:
        verdict = json.loads((folder / "results.json").read_text(encoding="utf-8")).get("verdict")
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(verdict, dict):
        verdict = verdict.get("statut")
    return verdict if isinstance(verdict, str) else None


def note_runs(session: Session) -> None:
    """Dossiers explore-* et qualif-* de la session (écrits par les outils existants)."""
    runs = []
    for p in sorted(session.folder.iterdir()):
        if p.is_dir() and p.name.startswith("explore-"):
            runs.append({"kind": "explore", "folder": p.name})
        elif p.is_dir() and p.name.startswith("qualif-"):
            runs.append({"kind": "qualif", "folder": p.name, "verdict": _qualif_verdict(p)})
    session.runs = runs
    session.save()


def _html_report(data: dict) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(d['id'])}</td><td>{e(str(d.get('result') or '—'))}</td><td>{e(str(d.get('reason') or ''))}</td>"
        f"<td>{e(str(d.get('note') or ''))}</td></tr>" for d in data["essais"])
    runs = "".join(f"<li>{e(r['kind'])} : {e(r['folder'])} {e(str(r.get('verdict') or ''))}</li>" for r in data["runs"])
    reasons = "".join(f"<li>{e(r)}</li>" for r in data["verdict"]["raisons"]) or "<li>—</li>"
    rest = data["remise_en_etat"]
    if not rest["compare"]:
        restore = "<li>relevé de départ ou de fin manquant : remise en état NON vérifiée</li>"
    elif not rest["differences"]:
        restore = "<li>aucune différence entre le départ et la fin</li>"
    else:
        restore = "".join(f"<li>À REMETTRE À LA MAIN : {e(d['lecture'])} {e(str(d['avant']))} → {e(str(d['apres']))}</li>"
                          for d in rest["differences"])
    return f"""<!doctype html>
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<html lang="fr"><head><meta charset="utf-8"><title>Qualification {e(data['poste']['nom'])}</title>
<style>body{{font-family:sans-serif;margin:2em;max-width:60em}}td,th{{border:1px solid #999;padding:.3em .6em}}
table{{border-collapse:collapse}}</style></head><body>
<h1>Qualification sur place : {e(data['poste']['fabricant'])} {e(data['poste']['nom'])}</h1>
<p>Modèle Hamlib {data['poste']['hamlib_model']}, Hamlib {e(data['versions']['hamlib'])}, station {e(data['versions']['station'])}.
Session commencée le {e(data['session']['debut'])}.</p>
<h2>Verdict proposé : {e(data['verdict']['propose'])}</h2><ul>{reasons}</ul>
<h2>Essais de sécurité</h2><table><tr><th>Essai</th><th>Résultat</th><th>Mesure</th><th>Remarque</th></tr>{rows}</table>
<h2>Outils lancés</h2><ul>{runs or '<li>—</li>'}</ul>
<h2>Remise en état du poste</h2><ul>{restore}</ul>
<p>Photos : {len(data['photos'])}.</p>
<p>Le statut « valide » reste une décision de l'équipe (docs/qualification-terrain-cahier-des-charges.md § 7).</p>
</body></html>
"""


README = """# Rapport de qualification sur place (valise v0)

Pour la conversation Claude qui reçoit ce zip, dans le dépôt openRemoteTRX :
1. Vérifier `empreintes.sha256` (sha256 de chaque fichier) ; un écart = demander un nouveau zip.
2. Lire `qualification.json` (format {format}) : poste, versions, essais de sécurité chronométrés, verdict PROPOSÉ.
3. Lire les dossiers `explore-*` (constats, fiche-poste.md, rapport-hamlib.md) et `qualif-*` (results.json, fiche.toml).
4. Suivre `docs/qualification-terrain-cahier-des-charges.md` § 7 : fiches du poste, catalogue, statut décidé
   avec l'utilisateur.
"""


def _restore_summary(session: Session) -> dict:
    """Différences entre le relevé de départ et celui de fin (compare = False : un relevé manque)."""
    try:
        diff = json.loads((session.folder / "reglages" / "differences.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"compare": False, "differences": None}
    return {"compare": True, "differences": diff}


def build_report(session: Session, *, settings: dict, out_dir: Path) -> Path:
    note_runs(session)
    proposed, reasons = verdict(session)
    data = {
        "format": FORMAT,
        "signature": None,
        "session": {"debut": session.started, "fin": _now()},
        "versions": {"station": __version__, "hamlib": session.hamlib_version},
        "poste": {"fabricant": session.manufacturer, "nom": session.model_name, "hamlib_model": session.model,
                  "backend": session.backend_status},
        "reglages": settings,
        "essais": [{"id": d.id, "facultatif": d.optional, **session.drills.get(d.id, {})} for d in all_drills()],
        "runs": session.runs,
        "releves": session.snapshots,
        "lectures_qui_font_tomber_rigctld": session.crashers,
        "carte_son": session.audio,
        "reception_antenne": session.reception,
        "spectre": session.spectrum,
        "filtres": session.filters,
        "remise_en_etat": _restore_summary(session),
        "photos": sorted(p.relative_to(session.folder).as_posix() for p in (session.folder / "photos").rglob("*")
                         if p.is_file()) if (session.folder / "photos").is_dir() else [],
        "verdict": {"propose": proposed, "raisons": reasons},
    }
    folder = session.folder
    (folder / "qualification.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "rapport.html").write_text(_html_report(data), encoding="utf-8")
    (folder / "LISEZMOI-CLAUDE.md").write_text(README.format(format=FORMAT), encoding="utf-8")
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.name != "empreintes.sha256"
                   and not p.name.endswith(".tmp"))
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(folder).as_posix()}" for p in files]
    (folder / "empreintes.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{folder.name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files + [folder / "empreintes.sha256"]:
            z.write(p, f"{folder.name}/{p.relative_to(folder).as_posix()}")
    return target


def check_report(zip_path: Path) -> list[str]:
    """Fichiers dont l'empreinte ne correspond pas (vide = rapport intact)."""
    bad = []
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        manifest = next(n for n in names if n.endswith("/empreintes.sha256"))
        root = manifest.rsplit("/", 1)[0]
        for line in z.read(manifest).decode("utf-8").splitlines():
            digest, _, rel = line.partition("  ")
            name = f"{root}/{rel}"
            if name not in names or hashlib.sha256(z.read(name)).hexdigest() != digest:
                bad.append(rel)
    return bad


def settings_of(cfg) -> dict:
    """Réglages utiles à la fiche du poste (rien de secret : ni comptes, ni clés)."""
    return {"hamlib_model": cfg.rig.model, "port": cfg.rig.port, "speed": cfg.rig.speed, "ptt_type": cfg.rig.ptt_type,
            "capture_device": cfg.audio.capture_device, "playback_device": cfg.audio.playback_device,
            "tot_s": cfg.safety.tot_s, "spectrum_port": getattr(cfg.spectrum, "port", "")}


# --------------------------------------------------------------------------- déroulé

WINDOWS_NUMBERED = re.compile(r"\(\d+- ")                  # « Haut-parleurs (2- USB Audio Device) »
SILENCE_ZEROS_PCT = 99.0


def audio_check(cfg, *, sd=None, seconds: float = 2.0, windows: bool | None = None) -> dict:
    """Carte son du poste, SANS émission (poste en réception, station arrêtée) : choisie ? s'ouvre-t-elle en réception
    (niveau, silence numérique) et en émission (quelques dixièmes de seconde de SILENCE écrits) ? Sous Windows : nom
    numéroté qui change avec la prise USB, volume et améliorations (non lisibles ici : rappel). Vu le 2026-11-18 sur
    l'IC-7300MK2 : nom vide = silence sans erreur, volume Windows à 38 = émission sans puissance."""
    import sys
    from ..audio_devices import real_device_names, resolve_device
    windows = sys.platform == "win32" if windows is None else windows
    result: dict = {"capture": None, "playback": None, "problems": [], "advice": []}
    names = {"capture": cfg.audio.capture_device, "playback": cfg.audio.playback_device}
    if sd is None:
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            result["problems"].append({"key": "no_sounddevice", "error": str(exc)})
            return result
    for kind, name in names.items():
        if not real_device_names(name):
            result["problems"].append({"key": f"no_{kind}", "name": name or ""})
            continue
        try:
            index = resolve_device(name, kind, sd)
        except LookupError:
            result["problems"].append({"key": "not_found", "kind": kind, "name": name})
            continue
        try:
            if kind == "capture":
                import numpy as np
                data = sd.rec(int(48000 * seconds), samplerate=48000, channels=1, dtype="int16", device=index)
                sd.wait()
                x = data.astype(float).ravel()
                rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
                level = round(20 * np.log10(max(rms, 1e-9) / 32768), 1)
                zeros = round(float(np.mean(x == 0)) * 100, 1) if x.size else 100.0
                result["capture"] = {"name": name, "level_dbfs": level, "zeros_pct": zeros}
                if zeros >= SILENCE_ZEROS_PCT:
                    result["problems"].append({"key": "digital_silence", "name": name})
            else:
                import numpy as np
                sd.play(np.zeros(int(48000 * 0.3), dtype="float32"), 48000, device=index)
                sd.wait()
                result["playback"] = {"name": name, "opened": True}
        except Exception as exc:                 # noqa: BLE001 : carte tenue ailleurs, format refusé…
            result["problems"].append({"key": "open_failed", "kind": kind, "name": name, "error": str(exc)[:160]})
    if windows:
        if any(WINDOWS_NUMBERED.search(n or "") for n in names.values()):
            result["advice"].append({"key": "windows_numbered"})
        result["advice"].append({"key": "windows_volume"})
    return result


def show_audio_check(result: dict, out: Callable[[str], None]) -> None:
    cap = result.get("capture")
    if cap:
        out(_t("terrain.audio.capture", name=cap["name"], level=cap["level_dbfs"], zeros=cap["zeros_pct"]))
    if result.get("playback"):
        out(_t("terrain.audio.playback", name=result["playback"]["name"]))
    for p in result["problems"]:
        out(_t(f"terrain.audio.problem.{p['key']}", **{k: v for k, v in p.items() if k != "key"}))
    for a in result["advice"]:
        out(_t(f"terrain.audio.advice.{a['key']}"))
    out(_t("terrain.audio.ok" if not result["problems"] else "terrain.audio.ko"))


# Réception sur antenne : sur la fréquence et le mode OÙ EST LE POSTE (décision de l'utilisateur, 2026-11-19 : on ne
# sait pas quelle antenne a l'opérateur, cibiste ou radioamateur) ; l'opérateur peut en donner une autre (ex. 7,1 MHz).
RX_LOW_DBFS, RX_HIGH_DBFS = -65.0, -6.0
TX_LEVELS_DB = (-40.0, -30.0, -24.0, -18.0, -12.0, -6.0)
ALC_STOP = 0.5
LOAD_WORD = "CHARGE"
ANTENNA_WORD = "ANTENNE"


def judge_reception(level: float | None, zeros: float | None) -> str:
    """ok, faible, sature ou silence : le son reçu sur ANTENNE (un faible niveau sur charge fictive ne prouve rien)."""
    if level is None or (zeros is not None and zeros >= SILENCE_ZEROS_PCT):
        return "silence"
    if level < RX_LOW_DBFS:
        return "faible"
    if level > RX_HIGH_DBFS:
        return "sature"
    return "ok"


QUALIF_BAND_KINDS = ("amateur", "cb", "45m")   # décision de l'utilisateur (2026-11-19) : + 85 m, 45 m, 11 m ; pas le marine


def qualification_bands() -> list:
    """Bandes sur lesquelles une qualification doit pouvoir émettre (charge fictive) : toutes les bandes radioamateur
    de la région 1, le 85 m, le 45 m et le 11 m (CB 26 à 28 MHz), d'après la table de la mesure de TOS
    (`swr/plan.BANDS`). C'est l'opérateur qui sait sur lesquelles il a le droit d'émettre."""
    from ..config import Band
    from ..swr.plan import BANDS
    return [Band(b.name if b.name != "CB" else "11m", b.low_hz / 1e6, b.high_hz / 1e6)
            for b in BANDS if b.kind in QUALIF_BAND_KINDS]


def missing_qualification_bands(cfg) -> list[str]:
    """Bandes de qualification qu'aucune bande de station.toml ne couvre entièrement (contrôle des bandes actif)."""
    if not cfg.safety.enforce_bands:
        return []
    have = [(b.low_mhz, b.high_mhz) for b in cfg.bands]
    return [b.name for b in qualification_bands()
            if not any(lo <= b.low_mhz + 1e-9 and b.high_mhz <= hi + 1e-9 for lo, hi in have)]


def parse_rx_frequency(text: str) -> int | None:
    """Réponse de l'opérateur : vide = fréquence actuelle (None) ; « 7.1 » / « 7,1 » MHz ; ValueError sinon."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    mhz = float(text)
    if not 0.1 <= mhz <= 470:
        raise ValueError(text)
    return round(mhz * 1e6)


def reception_on_antenna(cfg, *, sd=None, seconds: float = 4.0, freq_hz: int | None = None,
                         mode: str | None = None) -> dict:
    """Réception sur ANTENNE, station arrêtée, SANS émission : sur la fréquence actuelle du poste (ou celle donnée par
    l'opérateur, remise ensuite), son mesuré, S-mètre lu."""
    from ..gateway.cat.client import RigctldClient
    from . import main as qmain

    async def go():
        async with qmain.rigctld_session(cfg, spawn=True, out=lambda s: None) as (h, p):
            client = RigctldClient(h, p, timeout=3.0)
            await client.connect()
            try:
                if await client.get_ptt():
                    raise ObserverError("poste en émission : rien n'est changé")
                orig_freq, (orig_mode, _) = await client.get_frequency(), await client.get_mode()
                moved = freq_hz is not None and freq_hz != orig_freq
                try:
                    if moved:
                        await client.set_frequency(freq_hz)
                        if mode:
                            await client.set_mode(mode, 0)
                        await asyncio.sleep(1.0)
                    # JAMAIS dans un fil secondaire : sous Windows la carte son ne s'y ouvre pas (vu le 2026-11-19).
                    check = audio_check(cfg, sd=sd, seconds=seconds, windows=False)
                    strength = await client.get_strength()
                    used = (await client.get_frequency(), (await client.get_mode())[0])
                finally:
                    if moved:
                        await client.set_frequency(orig_freq)
                        await client.set_mode(orig_mode, 0)
                return check, strength, used
            finally:
                await client.close()
    check, strength, (used_freq, used_mode) = asyncio.run(go())
    cap = check.get("capture") or {}
    verdict = judge_reception(cap.get("level_dbfs"), cap.get("zeros_pct"))
    return {"freq_hz": used_freq, "mode": used_mode, "level_dbfs": cap.get("level_dbfs"), "zeros_pct": cap.get("zeros_pct"),
            "s_metre_db": strength, "verdict": verdict, "problems": check.get("problems", [])}


def spectrum_check(cfg, folder: Path, *, run=None) -> dict:
    """Spectre HF, station arrêtée, SANS émission : poste Icom = relevé de 8 s par `devtools/civ_scope` (lecture seule,
    aucune commande d'émission n'y existe) sur le second port s'il est réglé, sinon sur le port CAT (faisabilité :
    l'IC-705 n'a pas de CI-V sur son second port) ; autre marque : non proposé par la CAT."""
    import subprocess
    import sys
    from ..config import is_icom_model
    if not is_icom_model(cfg.rig.model):
        return {"verdict": "non_propose", "detail": "pas de données du spectre par la CAT de ce constructeur"}
    port = cfg.spectrum.port or cfg.rig.port
    which = "second port" if cfg.spectrum.port else "port CAT"
    out = folder / "spectre"
    cmd = [sys.executable, "-m", "trxstation.devtools.civ_scope", "--port", port, "--duree", "8", "--sortie", str(out)]
    if cfg.spectrum.civ_address:
        cmd += ["--adresse", cfg.spectrum.civ_address]
    run = run or (lambda c: subprocess.run(c, capture_output=True, text=True, timeout=60))
    try:
        result = run(cmd)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"verdict": "erreur", "port": port, "which": which, "detail": str(exc)[:160]}
    summary = ""
    try:
        summary = (out / "resume.txt").read_text(encoding="utf-8")
    except OSError:
        summary = (getattr(result, "stdout", "") or "")[-600:]
    sweeps = re.search(r"balayages complets (\d+)", summary)
    count = int(sweeps.group(1)) if sweeps else 0
    return {"verdict": "ok" if count > 0 else "aucune_donnee", "port": port, "which": which, "sweeps": count,
            "detail": " ; ".join(summary.strip().splitlines()[:2])[:200] if summary.strip() else ""}


CIV_ADDRESSES = (0x94, 0xA4, 0xB6)          # IC-7300, IC-705, IC-7300MK2 : adresse cherchée si station.toml n'en donne pas


def filters_check(cfg, *, civ=None) -> dict:
    """Préréglages de filtre FIL1 / FIL2 / FIL3, station arrêtée, SANS émission, par le SECOND PORT CI-V (commande 26 00,
    comme la station et l'application) : filtre d'origine relevé, chaque préréglage CHOISI et relu, filtre d'origine
    remis. Les LARGEURS des préréglages ne sont jamais écrites (une largeur envoyée par Hamlib les réécrirait)."""
    from ..config import is_icom_model
    from ..spectrum.civ import FILTERS, OK, decode_mode_filter, encode_mode_filter
    if not is_icom_model(cfg.rig.model):
        return {"verdict": "non_propose", "detail": "préréglages FIL : propres au second port CI-V des Icom"}
    if civ is None and not cfg.spectrum.port:
        return {"verdict": "pas_de_port", "detail": "second port CI-V non réglé ([spectrum] port)"}
    ser = None
    if civ is None:
        from ..spectrum.probe import CivPort, open_serial
        ser = open_serial(cfg.spectrum.port, cfg.spectrum.baud)
        wanted = int(cfg.spectrum.civ_address, 16) if cfg.spectrum.civ_address else None
        address = None
        for candidate in ([wanted] if wanted else list(CIV_ADDRESSES)):
            probe = CivPort(ser, candidate)
            if probe.identify(to=candidate) is not None:
                address = candidate
                break
        if address is None:
            ser.close()
            return {"verdict": "erreur", "detail": "poste muet sur le second port (adresse CI-V ?)"}
        civ = CivPort(ser, address)

    def current():
        reply = civ.request(0x26, 0x00, timeout=0.6)
        return decode_mode_filter(reply.payload) if reply is not None else None
    try:
        start = current()
        if start is None:
            return {"verdict": "erreur", "detail": "filtre en cours illisible (commande 26 00 sans réponse)"}
        mode, data, orig = start
        seen = {}
        try:
            for f in FILTERS:
                reply = civ.request(0x26, 0x00, encode_mode_filter(mode, data, f))
                accepted = reply is not None and reply.payload[:1] == bytes([OK])
                after = current()
                seen[f"FIL{f}"] = bool(accepted and after == (mode, data, f))
        finally:
            civ.request(0x26, 0x00, encode_mode_filter(mode, data, orig))
        restored = current() == start
        ok = all(seen.values()) and restored
        return {"verdict": "ok" if ok else "echec", "filtres": seen, "origine": f"FIL{orig}", "remis": restored,
                "detail": ", ".join(f"{k} {'OK' if v else 'NON'}" for k, v in seen.items())}
    finally:
        if ser is not None:
            ser.close()


def confirm_load(session: "Session", *, ask: Ask, out: Callable[[str], None]) -> bool:
    out(_t("terrain.load.action"))
    if (ask_word(ask, _t("terrain.load.prompt", word=LOAD_WORD), LOAD_WORD) or "").strip().upper() != LOAD_WORD:
        out(_t("terrain.load.refused"))
        return False
    session.connection = "charge"
    session.save()
    out(_t("terrain.load.done"))
    return True


def station_control(config_path: Path | None, start: bool) -> int:
    """Démarre ou arrête la station du PC comme TRX Console (menus 1.1 et 1.2) ; code de retour de la commande."""
    import subprocess
    import sys
    from ..console import TARGET, WINDOWS_TASK
    if os.name == "nt":
        if start:
            cmd = ["schtasks", "/Run", "/TN", WINDOWS_TASK]
        else:
            cmd = [sys.executable, "-m", "trxstation.supervisor.main", "--stop"]
            if config_path is not None:
                cmd[3:3] = ["--config", str(config_path)]
    else:
        cmd = ["systemctl", "start" if start else "stop", TARGET]
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            cmd.insert(0, "sudo")
    try:
        return subprocess.run(cmd, check=False).returncode
    except OSError:
        return 1


def _resume_or_new(output: Path, model: int, *, ask: Ask, out: Callable[[str], None]) -> Path:
    """Session du même poste commencée AUJOURD'HUI : la reprendre (défaut) plutôt qu'en ouvrir une seconde (vu sur
    l'IC-705 : la valise relancée avait coupé les essais en deux sessions)."""
    today = f"terrain-{model}-{dt.datetime.now():%Y%m%d}-"
    sessions = sorted(p for p in output.glob(today + "*") if p.is_dir() and (p / Session.FILE).exists()) \
        if output.is_dir() else []
    if sessions:
        last = sessions[-1]
        if yes_no(ask_typed(ask, _t("terrain.resume", folder=last.name), YES_NO)) is not False:
            return last
    return output / f"terrain-{model}-{dt.datetime.now():%Y%m%d-%H%M}"


def run_terrain(cfg, profile, dump_text: str, output: Path, *, session_dir: Path | None = None,
                config_path: Path | None = None, ask: Ask | None = None, out: Callable[[str], None] | None = None,
                bus: Bus | None = None,
                explore: Callable | None = None, qualify: Callable | None = None,
                station: Callable[[], bool] | None = None, control: Callable[[bool], int] | None = None,
                snapshot: Callable[[], dict] | None = None, sound: Callable[[], dict] | None = None,
                receive: Callable[[], dict] | None = None, scope: Callable[[], dict] | None = None,
                filters: Callable[[], dict] | None = None) -> int:
    """La valise. Tout passe par le BUS (lot G1) : le terminal n'en est qu'un client clavier (`ask` / `out` donnés =
    ce client ; `input` / `print` par défaut) ; historique dans `evenements.jsonl` du dossier de la session."""
    from . import main as qmain
    if bus is None:
        bus = Bus()
        KeyboardClient(bus, ask or input, out or print)
    ask, out = bus.ask, bus.out
    folder = session_dir or _resume_or_new(output, profile.model, ask=ask, out=out)
    bus.attach(folder)
    caps = profile.caps
    session = Session.open(folder, model=profile.model, model_name=caps.model_name, manufacturer=caps.manufacturer,
                           hamlib_version=profile.hamlib_version, backend_status=profile.backend_status)
    for sub in ("avant", "apres"):
        (folder / "photos" / sub).mkdir(parents=True, exist_ok=True)
    state_dir = Path(cfg.supervisor.state_dir)
    explore = explore or (lambda: asyncio.run(qmain.run_explore(cfg, profile, dump_text, folder, ask=ask, out=out)))
    qualify = qualify or (lambda no_tx: asyncio.run(qmain.run_qualif(
        cfg, profile, dump_text, folder, ask=ask, out=out, endurance_cycles=1000, tot_s=8.0, no_tx=no_tx,
        filters_test=False,
        tx_levels_db=TX_LEVELS_DB, alc_stop=ALC_STOP)))
    station = station or (lambda: qmain.station_running(cfg.supervisor.instance_lock_port))
    control = control or (lambda start: station_control(config_path, start))
    snapshot = snapshot or (lambda: asyncio.run(snapshot_session(cfg, profile, out=out, skip=tuple(session.crashers))))
    sound = sound or (lambda: audio_check(cfg))
    receive = receive or (lambda wanted=None: reception_on_antenna(cfg, freq_hz=wanted))
    scope = scope or (lambda: spectrum_check(cfg, folder))
    filters = filters or (lambda: filters_check(cfg))
    missing = missing_qualification_bands(cfg)
    if missing:
        out(_t("terrain.bands_missing", bands=", ".join(missing)))
    while True:
        note_runs(session)
        running = station()
        out(_t("terrain.title", name=f"{caps.manufacturer} {caps.model_name}".strip(), folder=folder))
        out(_t("terrain.station_running" if running else "terrain.station_stopped"))
        done = {r["kind"] for r in session.runs}

        def tick(ok) -> str:
            return "x" if ok else " "
        out(_t("terrain.menu2", sound=tick(session.audio and not session.audio.get("problems")),
               before=tick(session.snapshots.get("avant")), explore=tick("explore" in done),
               qualif=tick("qualif" in done), drills=sum(1 for d in DRILLS if d.id in session.drills),
               total=len(DRILLS), auto=sum(1 for d in all_drills()[len(DRILLS):] if d.id in session.drills),
               auto_total=len(all_drills()) - len(DRILLS), after=tick(session.snapshots.get("apres")),
               photos=sum(1 for p in (folder / "photos").rglob("*") if p.is_file()), photo_dir=folder / "photos" / "avant"))
        out(_t("terrain.parts", rx=tick(session.reception), scope=tick(session.spectrum), fil=tick(session.filters),
               connection=_t(f"terrain.connection.{session.connection or 'inconnu'}")))
        choice = ask(_t("terrain.choice")).strip().lower()
        if choice in ("1", "2", "3", "4", "6", "9", "r", "s", "f") and running:
            out(_t("terrain.need_stopped"))
        elif choice in ("3", "5", "8") and session.connection != "charge":
            out(_t("terrain.need_load"))                 # aucune émission sans la charge fictive CONFIRMÉE
        elif choice == "c":
            confirm_load(session, ask=ask, out=out)
        elif choice == "r":
            out(_t("terrain.rx.action"))
            # Mot ANTENNE tapé par un humain (lot G1) : plus de « O/n » validé par Entrée.
            if (ask_word(ask, _t("terrain.rx.prompt", word=ANTENNA_WORD), ANTENNA_WORD) or "").strip().upper() \
                    != ANTENNA_WORD:
                out(_t("terrain.rx.refused"))
            else:
                try:
                    wanted = parse_rx_frequency(ask(_t("terrain.rx.freq_prompt")))
                except ValueError:
                    wanted = None
                    out(_t("terrain.rx.freq_invalid"))
                session.connection = "antenne"           # désormais : plus d'émission avant « CHARGE »
                session.save()
                try:
                    rx = receive(wanted)
                except Exception as exc:                 # noqa: BLE001 : rigctld absent, poste éteint…
                    out(_t("terrain.rx.failed", error=exc))
                else:
                    session.reception = {"at": _now(), **rx}
                    session.save()
                    out(_t(f"terrain.rx.{rx['verdict']}", level=rx.get("level_dbfs"), s=rx.get("s_metre_db"),
                           freq=f"{rx['freq_hz'] / 1e6:.3f}", mode=rx["mode"]))
        elif choice == "f":
            out(_t("terrain.fil.title"))
            try:
                result = filters()
            except Exception as exc:                     # noqa: BLE001 : port occupé, pyserial absent…
                result = {"verdict": "erreur", "detail": str(exc)[:160]}
            session.filters = {"at": _now(), **result}
            session.save()
            out(_t(f"terrain.fil.{result['verdict']}", detail=result.get("detail", ""),
                   origine=result.get("origine", "")))
        elif choice == "s":
            out(_t("terrain.scope.title"))
            sp = scope()
            session.spectrum = {"at": _now(), **sp}
            session.save()
            out(_t(f"terrain.scope.{sp['verdict']}", port=sp.get("port", ""), which=sp.get("which", ""),
                   sweeps=sp.get("sweeps", 0), detail=sp.get("detail", "")))
        elif choice == "1":
            take_snapshot(session, "avant", snapshot, out=out)
        elif choice == "2":
            explore()
        elif choice == "3":
            qualify(False)
        elif choice == "4":
            qualify(True)
        elif choice == "5":
            if not running:
                out(_t("terrain.need_running"))
            drills_menu(session, cfg, state_dir, ask=ask, out=out)
        elif choice == "9":
            out(_t("terrain.audio.title"))
            result = sound()
            show_audio_check(result, out)
            session.audio = {"at": _now(), **result}
            session.save()
        elif choice == "8":
            if not running:
                out(_t("terrain.need_running"))
            from .autodrills import auto_menu
            auto_menu(session, cfg, state_dir, ask=ask, out=out)
        elif choice == "6":
            take_snapshot(session, "apres", snapshot, out=out)
            show_differences(session, out=out)
        elif choice == "7":
            target = build_report(session, settings=settings_of(cfg), out_dir=output)
            out(_t("terrain.report_done", path=target))
        elif choice == "a":
            out(_t("terrain.control_done" if control(False) == 0 else "terrain.control_failed"))
        elif choice == "d":
            out(_t("terrain.control_done" if control(True) == 0 else "terrain.control_failed"))
        elif choice in ("q", "0", ""):
            out(_t("terrain.bye", folder=folder))
            return 0


# --------------------------------------------------------------------------- relevé du poste (lecture seule)

READ_COMMANDS = frozenset({"f", "m", "t", "s", "j", "z", "u", "l", "p"})   # lectures SEULEMENT
BASE_READS = ("f", "m", "s", "j", "z")
NOT_COMPARED = {"t"}


class ReadOnlyRig:
    """Enveloppe d'un client rigctld qui REFUSE toute commande hors de READ_COMMANDS (aucune écriture possible)."""

    def __init__(self, client) -> None:
        self._client = client

    async def read(self, line: str) -> dict:
        letter = line.split(" ", 1)[0]
        if letter not in READ_COMMANDS or "\n" in line or "\r" in line:
            raise ObserverError(f"commande refusée au relevé : {line!r}")
        return await self._client._command(line)


CRASHED = "RIGCTLD TOMBÉ sur cette lecture"
SKIPPED = "non lu (fait tomber rigctld)"
MAX_RESTARTS = 4
RESTART_PAUSE_S = 1.5        # port série libéré par le rigctld tombé


def state_lines(profile) -> list[str]:
    """Lectures du relevé : fréquence, mode, split, RIT, XIT, PTT, fonctions, niveaux et paramètres stables (ni les
    mesures ni l'horloge du poste : `_VARYING` de l'exploration)."""
    from ..gateway.cat.client import FUNC_RE, LEVEL_RE
    from .explore import _VARYING, ACTION_PREFIXES
    lines = list(BASE_READS) + ["t"]
    lines += [f"u {n}" for n in profile.get_functions if FUNC_RE.fullmatch(n) and not n.startswith(ACTION_PREFIXES)]
    lines += [f"l {n}" for n in profile.get_levels if LEVEL_RE.fullmatch(n) and n not in _VARYING]
    lines += [f"p {n}" for n in profile.get_params if LEVEL_RE.fullmatch(n) and n not in _VARYING]
    return lines


def _shown(values: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in sorted(values.items()) if not k.startswith("#")) or \
        " ".join(v for k, v in sorted(values.items()))


async def read_state(rig: ReadOnlyRig, lines: list[str], state: dict) -> str | None:
    """Lit `lines` dans `state` (« RPRT n » si refusée) ; renvoie la lecture qui a FAIT TOMBER rigctld, ou None."""
    from ..gateway.cat.client import CatConnectionError, RigError
    for line in lines:
        try:
            state[line] = _shown(await rig.read(line))
        except RigError as exc:
            state[line] = f"RPRT {exc.code}"
        except CatConnectionError:
            state[line] = CRASHED
            return line
    return None


async def snapshot_session(cfg, profile, *, out: Callable[[str], None] = print, skip=()) -> dict:
    """Relevé par un rigctld LANCÉ POUR L'OCCASION (station arrêtée). Une lecture qui fait tomber rigctld (vu :
    « p KEYERTYPE », IC-7300MK2 et Hamlib 4.7.2 sous Windows) est notée, rigctld relancé, la suite lue ; `skip` :
    lectures déjà connues pour le faire tomber, jamais refaites."""
    from ..gateway.cat.client import RigctldClient
    from . import main as qmain
    state = {line: SKIPPED for line in skip}
    todo = [line for line in state_lines(profile) if line not in state]
    for attempt in range(MAX_RESTARTS):
        if not todo:
            break
        if attempt:
            await asyncio.sleep(RESTART_PAUSE_S)
        async with qmain.rigctld_session(cfg, spawn=True, out=out) as (h, p):
            client = RigctldClient(h, p, timeout=3.0)
            await client.connect()
            try:
                crashed = await read_state(ReadOnlyRig(client), todo, state)
            finally:
                await client.close()
        if crashed is None:
            break
        todo = todo[todo.index(crashed) + 1:]
    return state


def take_snapshot(session: "Session", which: str, snapshot: Callable[[], dict], *, out: Callable[[str], None]) -> None:
    out(_t("terrain.snapshot_reading"))
    try:
        state = snapshot()
    except Exception as exc:                     # noqa: BLE001 : rigctld absent, poste éteint… : dit, jamais fatal
        out(_t("terrain.snapshot_failed", error=exc))
        return
    folder = session.folder / "reglages"
    folder.mkdir(exist_ok=True)
    (folder / f"releve-{which}.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    session.snapshots[which] = {"at": _now(), "count": len(state)}
    for line, value in state.items():
        if value == CRASHED and line not in session.crashers:
            session.crashers.append(line)
            out(_t("terrain.snapshot_crash", line=line))
    session.save()
    out(_t("terrain.snapshot_done", count=len(state)))


def differences(before: dict, after: dict) -> list[dict]:
    """Réglages différents ; jamais une lecture absente d'un côté ou qui fait tomber rigctld (rien de comparable)."""
    unknown = {CRASHED, SKIPPED, None}
    keys = sorted((set(before) | set(after)) - NOT_COMPARED)
    return [{"lecture": k, "avant": before.get(k), "apres": after.get(k)} for k in keys
            if before.get(k) != after.get(k) and before.get(k) not in unknown and after.get(k) not in unknown]


def show_differences(session: "Session", *, out: Callable[[str], None]) -> list[dict] | None:
    folder = session.folder / "reglages"
    try:
        before = json.loads((folder / "releve-avant.json").read_text(encoding="utf-8"))
        after = json.loads((folder / "releve-apres.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out(_t("terrain.diff_missing"))
        return None
    diff = differences(before, after)
    (folder / "differences.json").write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not diff:
        out(_t("terrain.diff_none"))
    else:
        out(_t("terrain.diff_title", count=len(diff)))
        for d in diff:
            out(f"  {d['lecture']:<22} {d['avant']}  ->  {d['apres']}")
    return diff


def drills_menu(session: Session, cfg, state_dir: Path, *, ask: Ask, out: Callable[[str], None]) -> None:
    out(_t("terrain.drills_intro"))
    while True:
        for n, d in enumerate(DRILLS, 1):
            r = session.drills.get(d.id, {}).get("result")
            label = _t(f"terrain.drill.{d.id}.title").strip()
            out(f"  {n:2d}  {label}  [{_t('terrain.result.' + r) if r else '-'}]")
        choice = ask(_t("terrain.drills_choice")).strip().lower()
        if choice in ("r", "q", ""):
            return
        if choice == "t":
            todo = [d for d in DRILLS if d.id not in session.drills and not d.optional]
        elif choice.isdigit() and 1 <= int(choice) <= len(DRILLS):
            todo = [DRILLS[int(choice) - 1]]
        else:
            continue
        for d in todo:
            asyncio.run(play_drill(d, session, host=cfg.network.rigctld_host, port=cfg.network.rigctld_port,
                                   tot_s=float(cfg.safety.tot_s), state_dir=state_dir, ask=ask, out=out))
