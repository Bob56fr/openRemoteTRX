# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lecture SEULE de l'état publié par une station openRemoteTRX -> signes vitaux normalisés (view.vitals_template).

Sources (Debian, valeurs par défaut de la station) :
  - /run/trx-remote/gateway-status.json : état de la passerelle, réécrit 4 fois par seconde (schema 1) ;
    fraîcheur jugée sur le changement de (pid, seq) avec NOTRE horloge monotone, jamais sur `written_at` ;
  - /var/lib/trx-remote/safe_mode : présent = mise en sécurité, contenu = raison ;
  - /var/lib/trx-remote/sdr/status.json, cluster/status.json : modules ;
  - /var/lib/trx-remote/journal-*.jsonl : événements (alertes) ; chauffe.jsonl : 24 h de température et charge ;
  - /etc/trx-remote/station.toml : TOT ([safety] tot_s) ;
  - systemd : état des services rigctld, trx-gateway, trx-supervisor.
Le programme n'importe PAS le paquet trxstation (il change à chaque mise à jour de la station) et n'écrit rien chez elle.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import tomllib
from datetime import datetime
from pathlib import Path

GATEWAY_STALE_S = 2.0            # même seuil que trx-monitor
SDR_STALE_S = 30.0
SDR_HIDE_S = 86400.0
CLUSTER_STALE_S = 30.0
TOT_WARNING_S = 10.0             # bip d'avertissement 10 s avant la coupure
EPISODE_S = 900                  # regroupement des alertes répétées
JOURNALS = ("journal-superviseur.jsonl", "journal-passerelle.jsonl")
SEVERITY = {"avertissement": "warn", "erreur": "crit", "critique": "crit"}
AGC = {0: "OFF", 1: "TRÈS RAP.", 2: "RAPIDE", 3: "LENTE", 4: "UTIL.", 5: "MOY.", 6: "AUTO"}
SERVICES = (("Passerelle", "trx-gateway.service"), ("Superviseur", "trx-supervisor.service"),
            ("rigctld", "rigctld.service"))
CLUSTER_HEALTH = {"green": ("ok", "OK"), "ok": ("ok", "OK"), "yellow": ("warn", "partiel"),
                  "orange": ("warn", "partiel"), "red": ("crit", "en panne"), "grey": ("off", "en pause"),
                  "gray": ("off", "en pause")}
SDR_DRIVERS = {"sdrplay": "SDRplay", "rtlsdr": "RTL-SDR", "rtl": "RTL-SDR"}


def preamp_text(value: float | None) -> str | None:
    """PREAMP de Hamlib : numéro du préampli (1, 2) sur les Icom, dB sur d'autres postes ; 0 = coupé ("")."""
    if value is None:
        return None
    if not value:
        return ""
    return f"P{int(value)}" if value <= 3 and float(value).is_integer() else f"{value:g} dB"


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def parse_ts(value) -> float | None:
    """Horodatage du journal : ISO UTC (« …Z ») ou nombre de secondes."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def station_version(opt: Path = Path("/opt/trx-remote")) -> str | None:
    """Version active : cible du lien /opt/trx-remote/current (releases/<version>)."""
    try:
        return Path(os.readlink(opt / "current")).name or None
    except OSError:
        return None


def read_station_toml(station_toml: Path) -> tuple[float | None, list[dict] | None]:
    """(TOT en s, comptes opérateurs [{"id", "pseudo"}]) ; (None, None) si le fichier est illisible.

    Comptes : [[clients]] hors visiteurs (role « listener »), dans l'ordre du fichier ; jamais de mot de passe lu."""
    try:
        with open(station_toml, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None, None
    tot = data.get("safety", {}).get("tot_s")
    accounts = []
    for c in data.get("clients", []):
        if isinstance(c, dict) and c.get("role", "operator") != "listener" and isinstance(c.get("id"), str):
            accounts.append({"id": c["id"], "pseudo": c.get("pseudo") if isinstance(c.get("pseudo"), str) else None})
    return (float(tot) if isinstance(tot, (int, float)) else None), accounts


async def unit_state(unit: str) -> str | None:
    """« active », « failed », « inactive »… ; None si systemctl est absent (poste de développement)."""
    if shutil.which("systemctl") is None:
        return None
    proc = await asyncio.create_subprocess_exec("systemctl", "is-active", unit, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    return out.decode(errors="replace").strip() or None


class JournalTail:
    """Suit les journaux d'événements de la station ; rend les alertes nouvelles (clé unique par ligne)."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.pos: dict[str, tuple[int, int]] = {}       # fichier -> (inode, position)

    @staticmethod
    def alert_of(line: str, process: str) -> dict | None:
        try:
            ev = json.loads(line)
        except ValueError:
            return None
        if not isinstance(ev, dict):
            return None
        msg = str(ev.get("message") or "")
        level = SEVERITY.get(str(ev.get("gravite") or "").lower())
        if level is None and msg.startswith("ALERTE"):          # alerte ntfy du superviseur
            level = "crit"
        if level is None and ev.get("niveau") in ("ERROR", "CRITICAL") and ev.get("code"):
            level = "crit"
        if level is None:
            return None
        t = parse_ts(ev.get("ts"))
        if t is None:
            return None
        text = str(ev.get("titre") or msg)[:160]
        # un même événement répété (ORT-5030 en boucle par exemple) = UN épisode par quart d'heure
        key = f"{process}|{ev.get('code') or msg[:40]}|{int(t // EPISODE_S)}"
        return {"t": t, "level": level, "text": text, "key": key}

    def initial(self, since: float) -> list[dict]:
        """Au démarrage : les alertes des 24 dernières heures, rotations comprises (.3 à .1 puis le fichier)."""
        out = []
        for name in JOURNALS:
            process = name.removeprefix("journal-").removesuffix(".jsonl")
            for suffix in (".3", ".2", ".1", ""):
                path = self.state_dir / (name + suffix)
                try:
                    with open(path, encoding="utf-8", errors="replace") as handle:
                        for line in handle:
                            a = self.alert_of(line, process)
                            if a and a["t"] >= since:
                                out.append(a)
                        if suffix == "":
                            self.pos[name] = (os.fstat(handle.fileno()).st_ino, handle.tell())
                except OSError:
                    continue
        return out

    def new(self) -> list[dict]:
        out = []
        for name in JOURNALS:
            path = self.state_dir / name
            process = name.removeprefix("journal-").removesuffix(".jsonl")
            try:
                st = path.stat()
            except OSError:
                continue
            inode, pos = self.pos.get(name, (st.st_ino, st.st_size))
            if inode != st.st_ino or st.st_size < pos:      # fichier tourné : on repart du début du nouveau
                pos = 0
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    handle.seek(pos)
                    for line in handle:
                        a = self.alert_of(line, process)
                        if a:
                            out.append(a)
                    self.pos[name] = (st.st_ino, handle.tell())
            except OSError:
                continue
        return out


def heat_history(state_dir: Path, since: float) -> list[dict]:
    """chauffe.jsonl (relevé du superviseur toutes les 10 s) -> [{"t", "cpu", "temp"}], pour pré-remplir l'historique."""
    out = []
    for suffix in (".2", ".1", ""):
        try:
            with open(state_dir / ("chauffe.jsonl" + suffix), encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    t = parse_ts(ev.get("ts")) if isinstance(ev, dict) else None
                    if t is None or t < since:
                        continue
                    num = lambda k: ev.get(k) if isinstance(ev.get(k), (int, float)) else None
                    out.append({"t": t, "cpu": num("cpu_pct"), "temp": num("temp_c")})
        except OSError:
            continue
    return out


class StationReader:
    def __init__(self, status_path: Path, state_dir: Path, station_toml: Path, *, rig_name: str = "",
                 rig_max_w: float = 100.0, clock=time.monotonic, wall=time.time):
        self.status_path, self.state_dir, self.station_toml = status_path, state_dir, station_toml
        self.rig_name, self.rig_max_w = rig_name, rig_max_w
        self.clock, self.wall = clock, wall
        self._key = None                  # (pid, seq) du dernier état lu
        self._fresh_at = None             # horloge monotone du dernier changement
        self._lost_at = None              # liaison CAT perdue depuis
        self._last_freq = (None, None)    # dernière fréquence et mode connus
        self._local_tx_at = None          # début d'une émission locale (pas de TOT publié)
        self.services: list[dict] = []
        self.version = station_version()
        self.tot_s, accounts = read_station_toml(station_toml)
        self.accounts: list[dict] = accounts or []     # comptes opérateurs de station.toml (relus toutes les 10 s)

    async def refresh_services(self) -> None:
        out = []
        for name, unit in SERVICES:
            state = await unit_state(unit)
            if state is None:
                continue
            level = {"active": "ok", "activating": "warn", "reloading": "warn", "failed": "crit"}.get(state, "crit")
            text = {"active": "OK", "activating": "démarre", "failed": "EN PANNE", "inactive": "ARRÊTÉ"}.get(state, state)
            out.append({"name": name, "level": level, "text": text})
        cluster = read_json(self.state_dir / "cluster/status.json")
        if cluster is not None:
            try:
                age = self.wall() - (self.state_dir / "cluster/status.json").stat().st_mtime
            except OSError:
                age = None
            health = str(cluster.get("health") or "").lower()
            if cluster.get("enabled") is False:
                pass                                       # module coupé : pas de ligne
            elif age is not None and age > CLUSTER_STALE_S:
                out.append({"name": "Cluster DX", "level": "off", "text": "arrêté"})
            else:
                level, text = CLUSTER_HEALTH.get(health, ("warn", health or "?"))
                out.append({"name": "Cluster DX", "level": level, "text": text})
        self.services = out
        self.version = station_version() or self.version
        tot, accounts = read_station_toml(self.station_toml)
        self.tot_s = tot or self.tot_s
        if accounts is not None:                           # fichier illisible un instant : on garde la liste connue
            self.accounts = accounts

    # ------------------------------------------------------------------ lecture

    def read(self) -> dict:
        now = self.clock()
        status = read_json(self.status_path)
        if status is not None and status.get("schema") not in (None, 1):
            status = None                                 # format inconnu : on n'interprète pas
        if status is not None:
            key = (status.get("pid"), status.get("seq"))
            if key != self._key:
                self._key, self._fresh_at = key, now
        age = None if self._fresh_at is None else now - self._fresh_at
        ok = status is not None and age is not None and age <= GATEWAY_STALE_S

        safe_path = self.state_dir / "safe_mode"
        try:
            safe_reason = safe_path.read_text(encoding="utf-8").strip() if safe_path.exists() else None
        except OSError:
            safe_reason = None

        v = {"station": {"ok": ok, "age_s": age, "version": self.version},
             "safe": {"active": safe_reason is not None, "reason": safe_reason or None},
             "services": self._services(ok), "sdr": self._sdr()}
        if status is not None:
            v.update(self._from_status(status, now))
        return v

    def _services(self, fresh: bool) -> list[dict]:
        out = []
        for s in self.services:
            if s["name"] == "Passerelle" and s["level"] == "ok" and not fresh:
                s = {**s, "level": "crit", "text": "muette"}   # active pour systemd mais n'écrit plus son état
            out.append(s)
        return out

    def _from_status(self, st: dict, now: float) -> dict:
        rig = st.get("rig") if isinstance(st.get("rig"), dict) else {}
        ptt = st.get("ptt") if isinstance(st.get("ptt"), dict) else {}
        fn = rig.get("functions") if isinstance(rig.get("functions"), dict) else {}
        lv = rig.get("levels") if isinstance(rig.get("levels"), dict) else {}
        offsets = rig.get("offsets") if isinstance(rig.get("offsets"), dict) else {}
        num = lambda d, k: d.get(k) if isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool) else None

        connected = rig.get("connected")
        if connected is False:
            self._lost_at = self._lost_at or now
        elif connected:
            self._lost_at = None
        if connected and rig.get("frequency_hz"):
            self._last_freq = (rig.get("frequency_hz"), rig.get("mode"))

        # VFO : la passerelle publie la fréquence du VFO courant ; l'autre n'est connu qu'en split (fréquence TX)
        vfo_raw = str(rig.get("vfo") or "").upper()
        vfo = "B" if vfo_raw.endswith("B") or vfo_raw == "SUB" else "A"
        freq, txf = num(rig, "frequency_hz"), num(rig, "tx_frequency_hz")
        other = txf if rig.get("split") else None
        vfo_a, vfo_b = (freq, other) if vfo == "A" else (other, freq)

        notch = "auto" if fn.get("ANF") else "manual" if fn.get("MN") else (False if ("ANF" in fn or "MN" in fn) else None)
        nr_lv, comp_lv = num(lv, "NR"), num(lv, "COMP_METER")
        preamp, att, agc = num(lv, "PREAMP"), num(lv, "ATT"), num(lv, "AGC")
        rfpower, po, alc = num(lv, "RFPOWER"), num(lv, "RFPOWER_METER"), num(lv, "ALC")
        sql = num(lv, "SQL")

        state = str(ptt.get("state") or "RX").upper()
        tx = state in ("KEYING", "TX", "UNKEYING") or bool(rig.get("ptt"))
        local = bool(ptt.get("local_tx"))
        remaining = num(ptt, "tot_remaining_s")
        elapsed = tot = None
        if tx and remaining is not None and self.tot_s:
            tot, elapsed = self.tot_s, max(0.0, self.tot_s - remaining)
        elif tx and local:
            self._local_tx_at = self._local_tx_at or now
            elapsed = now - self._local_tx_at
        if not tx:
            self._local_tx_at = None

        presence = st.get("presence") if isinstance(st.get("presence"), dict) else {}
        conns = [c for c in presence.get("connections", []) if isinstance(c, dict)]
        owner_id = ptt.get("owner")
        operators, seen = [], set()
        for c in conns:
            if c.get("role") != "operator":
                continue
            account = str(c.get("id") or "").strip()
            name = str(c.get("pseudo") or "").strip() or account or "Opérateur"
            is_tx = tx and owner_id is not None and account == str(owner_id)
            if (account or name) in seen:                 # un même compte deux fois : une pastille, émission gardée
                operators = [{**o, "tx": o["tx"] or is_tx} if (o["id"] or o["name"]) == (account or name) else o
                             for o in operators]
                continue
            seen.add(account or name)
            operators.append({"id": account, "name": name, "tx": is_tx})
        owner = next((str(c.get("pseudo") or c.get("id")) for c in conns
                      if owner_id is not None and str(c.get("id")) == str(owner_id)), None)
        visitors = presence.get("listeners") if isinstance(presence.get("listeners"), int) else \
            sum(1 for c in conns if c.get("role") == "listener")

        def offset(name: str) -> int | None:
            """Décalage RIT / XIT en Hz : 0 si la fonction existe mais est coupée, None si le poste ne l'a pas."""
            if name in fn:
                return int(offsets.get(name) or 0) if fn[name] else 0
            return int(offsets[name]) if isinstance(offsets.get(name), (int, float)) else None

        temp = num(ptt, "temp_c")
        return {
            "rig": {
                "model": self.rig_name or None, "connected": connected if isinstance(connected, bool) else None,
                "lost_s": None if self._lost_at is None else now - self._lost_at,
                "power": rig.get("power") if rig.get("power") in ("on", "off") else None,
                "freq_hz": freq, "mode": rig.get("mode"), "passband_hz": num(rig, "passband_hz"),
                "strength_db": num(rig, "strength_db"),
                "vfo": vfo, "vfo_a_hz": vfo_a, "vfo_b_hz": vfo_b,
                "split": bool(rig.get("split")) if "split" in rig else None,
                "rit_hz": offset("RIT"), "xit_hz": offset("XIT"),
                "tuner": fn.get("TUNER"), "nb": fn.get("NB"), "nr": fn.get("NR"),
                "nr_level": None if nr_lv is None else (str(round(nr_lv * 15)) if nr_lv <= 1 else f"{nr_lv:g}"),
                "notch": notch,
                "att_db": att, "preamp": preamp_text(preamp),
                "agc": None if agc is None else AGC.get(int(agc), str(int(agc))),
                "comp": fn.get("COMP"), "comp_level": None if comp_lv is None else f"{comp_lv:g}",
                "vox": None, "squelch": None if sql is None else sql > 0, "monitor": None,
                "power_set_w": None if rfpower is None else rfpower * self.rig_max_w,
                "po_w": None if po is None else (po * self.rig_max_w if po <= 1 else po),
                "swr": num(lv, "SWR"), "alc_pct": None if alc is None else (alc * 100 if alc <= 1 else alc),
                "temp_c": temp, "vd_v": num(lv, "VD_METER"),
                "last_freq_hz": self._last_freq[0], "last_mode": self._last_freq[1],
            },
            "ptt": {"tx": tx, "elapsed_s": elapsed, "tot_s": tot,
                    "warn_s": None if tot is None else max(0.0, tot - TOT_WARNING_S),
                    "owner": owner, "local": local, "heartbeat_s": None},
            "operators": operators, "visitors": visitors or 0,
        }

    def _sdr(self) -> dict | None:
        path = self.state_dir / "sdr/status.json"
        data = read_json(path)
        if data is None:
            return None                                    # module jamais lancé : bloc masqué
        t = data.get("t") if isinstance(data.get("t"), (int, float)) else None
        if t is None:
            try:
                t = path.stat().st_mtime
            except OSError:
                return None
        ago = self.wall() - t
        if ago > SDR_HIDE_S:
            return None
        driver = str(data.get("driver") or "").lower()
        model = next((v for k, v in SDR_DRIVERS.items() if k in driver), "SDR")
        state = str(data.get("state") or "")
        present = ago <= SDR_STALE_S and state != "error"
        fs = data.get("fs") if isinstance(data.get("fs"), (int, float)) else None
        load = data.get("cpu") if isinstance(data.get("cpu"), (int, float)) else None
        return {"present": present, "model": model, "state": "error" if state == "error" else state,
                "freq_hz": data.get("dfreq") if isinstance(data.get("dfreq"), (int, float)) else None,
                "mode": data.get("mode") if isinstance(data.get("mode"), str) else None,
                "rate": None if not fs else f"{fs / 1e6:g} MS/s", "load_pct": load,
                "seen_ago_s": ago}
