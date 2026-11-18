# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Comparaison de deux qualifications du MÊME poste (`trx-qualif --comparer A B`) : la valise donne-t-elle le même
résultat quel que soit celui qui la joue ? (demande de l'utilisateur du 2026-11-18 : qualification de l'IC-705 faite
deux fois, par Claude puis par le qualifieur, sur le même PC.)

Entrées : deux rapports de la valise (zip, ou dossier de session `terrain-…`). Comparés : contexte (poste, versions,
réglages), verdicts, tests de la qualification Q1 (résultat et mesures), essais de sécurité (à la main et
automatiques), constats de l'exploration, relevés de départ et remise en état, carte son. Chaque écart a une gravité
(important, à vérifier, pour information) et une cause probable (poste, environnement, opérateur, outil). Lecture
seule : rien n'est envoyé au poste. Document produit en français (`ecarts.md`, `ecarts.json`).
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

IMPORTANT, CHECK, INFO = "important", "a_verifier", "info"
GRAVITY_ORDER = {IMPORTANT: 0, CHECK: 1, INFO: 2}
CUT_RE = re.compile(r"en (\d+(?:[.,]\d+)?) s")
TOL_CUT_S = 0.5               # coupure (battements, TOT, déconnexion, perte CAT) mesurée par la qualification
TOL_MARK_S = 1.0              # délai depuis un repère tapé à la main (réaction humaine)
TOL_AUTO_S = 0.5              # délai mesuré par le client automatique
TOL_LEVEL_DB = 6.0            # niveau reçu par la carte son
TOL_LATENCY = (0.5, 2.0)      # temps de réponse CAT : écart relatif ET absolu (ms) pour le signaler


@dataclass
class Gap:
    category: str
    item: str
    a: object
    b: object
    gravity: str
    cause: str
    detail: str = ""


class CompareError(Exception):
    pass


# --------------------------------------------------------------------------- lecture d'un rapport

class _Source:
    """Fichiers d'un rapport : zip de la valise (un dossier racine) ou dossier de session."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if path.is_file() and zipfile.is_zipfile(path):
            self.zip = zipfile.ZipFile(path)
            names = self.zip.namelist()
            roots = {n.split("/", 1)[0] for n in names if "/" in n}
            if len(roots) != 1:
                raise CompareError(f"{path} : zip inattendu (un seul dossier de session attendu)")
            self.root = roots.pop() + "/"
            self.names = [n[len(self.root):] for n in names if n.startswith(self.root)]
        elif path.is_dir():
            self.zip, self.root = None, ""
            self.names = [p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()]
        else:
            raise CompareError(f"{path} : ni zip de la valise ni dossier de session")

    def json(self, name: str):
        try:
            raw = self.zip.read(self.root + name) if self.zip else (self.path / name).read_bytes()
        except (KeyError, OSError):
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return None

    def latest(self, prefix: str, file: str, prefer=None) -> tuple[str | None, object]:
        """Dernier dossier `prefix-*` (ordre des noms = ordre des dates) qui contient `file` ; avec `prefer`, le
        dernier qui le satisfait s'il y en a un."""
        folders = sorted({n.split("/", 1)[0] for n in self.names if n.startswith(prefix) and n.endswith("/" + file)})
        found = [(f, d) for f in reversed(folders) if (d := self.json(f"{f}/{file}")) is not None]
        if prefer is not None:
            for folder, data in found:
                if prefer(data):
                    return folder, data
        return found[0] if found else (None, None)


def _with_emission(q1: dict) -> bool:
    """Qualification où la phase d'émission a été jouée (PTT essayé) : c'est elle qu'on compare (une qualification
    « sans émission » faite après ne doit pas la masquer, vu sur l'IC-705)."""
    return any(t.get("id") == "ptt_cycle" and t.get("ok") is not None for t in q1.get("tests", []))


def load_report(path: str | Path) -> dict:
    src = _Source(Path(path))
    report = {"name": Path(path).name, "qualification": src.json("qualification.json"),
              "session": src.json("session.json"), "drills": {}}
    report["q1_folder"], report["q1"] = src.latest("qualif-", "results.json", prefer=_with_emission)
    report["explore_folder"], report["explore"] = src.latest("explore-", "exploration.json")
    for name in src.names:
        if name.startswith("essais/") and name.endswith(".json"):
            record = src.json(name)
            if isinstance(record, dict) and record.get("id"):
                report["drills"][record["id"]] = record
    report["before"] = src.json("reglages/releve-avant.json")
    report["after"] = src.json("reglages/releve-apres.json")
    if report["qualification"] is None and report["session"] is None:
        raise CompareError(f"{path} : ni qualification.json ni session.json (pas un rapport de la valise)")
    return report


# --------------------------------------------------------------------------- comparaison

def _num(text) -> float | None:
    m = CUT_RE.search(str(text or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def _q1_status(q1) -> str | None:
    verdict = (q1 or {}).get("verdict")
    return verdict.get("statut") if isinstance(verdict, dict) else verdict


def _context(a: dict, b: dict, gaps: list[Gap]) -> None:
    qa, qb = a["qualification"] or {}, b["qualification"] or {}
    ma = (qa.get("poste") or {}).get("hamlib_model") or (a["session"] or {}).get("model")
    mb = (qb.get("poste") or {}).get("hamlib_model") or (b["session"] or {}).get("model")
    if ma != mb:
        gaps.append(Gap("contexte", "modèle Hamlib", ma, mb, IMPORTANT, "outil",
                        "deux postes différents : la comparaison n'a pas de sens"))
    for key in ("station", "hamlib"):
        va, vb = (qa.get("versions") or {}).get(key), (qb.get("versions") or {}).get(key)
        if va != vb:
            gaps.append(Gap("contexte", f"version {key}", va, vb, INFO, "environnement"))
    ra, rb = qa.get("reglages") or {}, qb.get("reglages") or {}
    for key in sorted(set(ra) | set(rb)):
        if ra.get(key) != rb.get(key):
            gaps.append(Gap("contexte", f"réglage {key}", ra.get(key), rb.get(key), CHECK, "environnement"))


def _verdicts(a: dict, b: dict, gaps: list[Gap]) -> None:
    va = ((a["qualification"] or {}).get("verdict") or {}).get("propose")
    vb = ((b["qualification"] or {}).get("verdict") or {}).get("propose")
    if va != vb:
        gaps.append(Gap("verdict", "verdict proposé par la valise", va, vb, IMPORTANT, "poste"))
    qa, qb = _q1_status(a["q1"]), _q1_status(b["q1"])
    if qa != qb:
        gaps.append(Gap("verdict", "verdict de la qualification Q1", qa, qb, IMPORTANT, "poste"))


def _q1(a: dict, b: dict, gaps: list[Gap]) -> None:
    if not a["q1"] or not b["q1"]:
        if a["q1"] or b["q1"]:
            gaps.append(Gap("qualification", "qualification Q1", bool(a["q1"]), bool(b["q1"]), IMPORTANT, "opérateur",
                            "faite d'un seul côté"))
        return
    ta = {t["id"]: t for t in a["q1"].get("tests", [])}
    tb = {t["id"]: t for t in b["q1"].get("tests", [])}
    for tid in sorted(set(ta) | set(tb)):
        x, y = ta.get(tid), tb.get(tid)
        if x is None or y is None:
            gaps.append(Gap("qualification", tid, x is not None, y is not None, CHECK, "opérateur",
                            "test joué d'un seul côté (vérifications visuelles, débranchement USB…)"))
            continue
        if x.get("ok") != y.get("ok") and None in (x.get("ok"), y.get("ok")):
            gaps.append(Gap("qualification", x.get("label") or tid, x.get("ok"), y.get("ok"), CHECK, "opérateur",
                            "fait d'un seul côté"))
            continue
        if x.get("ok") != y.get("ok"):
            declared = x.get("category") == "declaratif"
            gaps.append(Gap("qualification", x.get("label") or tid, x.get("ok"), y.get("ok"),
                            CHECK if declared else IMPORTANT, "opérateur" if declared else "poste",
                            f"{x.get('detail', '')} | {y.get('detail', '')}"))
            continue
        cx, cy = _num(x.get("detail")), _num(y.get("detail"))
        if tid.startswith(("drill_", "cat_loss")):
            if cx is not None and cy is not None and abs(cx - cy) > TOL_CUT_S:
                gaps.append(Gap("qualification", x.get("label") or tid, cx, cy, CHECK, "poste",
                                f"coupure en {cx} s contre {cy} s (tolérance {TOL_CUT_S} s)"))
        if tid == "latency":
            la, lb = (x.get("data") or {}).get("latence_cat_ms"), (y.get("data") or {}).get("latence_cat_ms")
            if la and lb and abs(la - lb) > TOL_LATENCY[1] and abs(la - lb) / max(la, lb) > TOL_LATENCY[0]:
                gaps.append(Gap("qualification", "temps de réponse CAT (ms)", la, lb, INFO, "environnement"))


def _drills(a: dict, b: dict, gaps: list[Gap]) -> None:
    for did in sorted(set(a["drills"]) | set(b["drills"])):
        x, y = a["drills"].get(did), b["drills"].get(did)
        if x is None or y is None:
            gaps.append(Gap("essais", did, (x or {}).get("result"), (y or {}).get("result"), CHECK, "opérateur",
                            "essai joué d'un seul côté"))
            continue
        auto = did.startswith("auto_")
        if x.get("result") != y.get("result"):
            gaps.append(Gap("essais", did, x.get("result"), y.get("result"), IMPORTANT, "poste" if auto else "opérateur",
                            f"{x.get('reason', '')} | {y.get('reason', '')}"))
            continue
        mx, my = x.get("measures") or {}, y.get("measures") or {}
        for key, tol in (("delay_from_mark_s", TOL_MARK_S), ("tx_duration_s", TOL_CUT_S), ("delai_s", TOL_AUTO_S),
                         ("duree_s", TOL_AUTO_S)):
            vx, vy = mx.get(key), my.get(key)
            if isinstance(vx, (int, float)) and isinstance(vy, (int, float)) and abs(vx - vy) > tol:
                gaps.append(Gap("essais", f"{did} : {key}", vx, vy, CHECK, "poste" if auto else "opérateur",
                                f"écart {abs(vx - vy):.2f} s (tolérance {tol} s)"))


def _explore(a: dict, b: dict, gaps: list[Gap]) -> None:
    if not a["explore"] or not b["explore"]:
        if a["explore"] or b["explore"]:
            gaps.append(Gap("exploration", "exploration", bool(a["explore"]), bool(b["explore"]), CHECK, "opérateur",
                            "faite d'un seul côté"))
        return
    fa = {f["id"]: f for f in a["explore"].get("constats", [])}
    fb = {f["id"]: f for f in b["explore"].get("constats", [])}
    for fid in sorted(set(fa) ^ set(fb)):
        f = fa.get(fid) or fb.get(fid)
        gaps.append(Gap("exploration", f.get("title", fid), fid in fa, fid in fb, CHECK, "poste",
                        "constat trouvé d'un seul côté"))


def _snapshots(a: dict, b: dict, gaps: list[Gap]) -> None:
    from .terrain import differences
    if a["before"] and b["before"]:
        start = differences(a["before"], b["before"])
        for d in start:
            gaps.append(Gap("point de départ", d["lecture"], d["avant"], d["apres"], CHECK, "opérateur",
                            "poste pas dans le même état au départ des deux qualifications"))
    for side, rep in (("A", a), ("B", b)):
        rest = (rep["qualification"] or {}).get("remise_en_etat") or {}
        if rest.get("compare") and rest.get("differences"):
            gaps.append(Gap("remise en état", f"rapport {side}", len(rest["differences"]), None, CHECK, "outil",
                            "réglages laissés différents du départ"))
    ca = ((a["qualification"] or {}).get("carte_son") or {}).get("capture") or {}
    cb = ((b["qualification"] or {}).get("carte_son") or {}).get("capture") or {}
    la, lb = ca.get("level_dbfs"), cb.get("level_dbfs")
    if isinstance(la, (int, float)) and isinstance(lb, (int, float)) and abs(la - lb) > TOL_LEVEL_DB:
        gaps.append(Gap("carte son", "niveau reçu (dBFS)", la, lb, INFO, "environnement"))


def compare(a: dict, b: dict) -> list[Gap]:
    gaps: list[Gap] = []
    for step in (_context, _verdicts, _q1, _drills, _explore, _snapshots):
        step(a, b, gaps)
    gaps.sort(key=lambda g: (GRAVITY_ORDER[g.gravity], g.category, g.item))
    return gaps


# --------------------------------------------------------------------------- documents

GRAVITY_FR = {IMPORTANT: "IMPORTANT", CHECK: "à vérifier", INFO: "pour information"}


def render_markdown(a: dict, b: dict, gaps: list[Gap]) -> str:
    lines = [f"# Comparaison de deux qualifications", "", f"- A : `{a['name']}`", f"- B : `{b['name']}`", ""]
    if not gaps:
        return "\n".join(lines + ["Aucun écart : les deux qualifications donnent le même résultat.", ""])
    counts = {g: sum(1 for x in gaps if x.gravity == g) for g in GRAVITY_FR}
    lines += [", ".join(f"{n} {GRAVITY_FR[g]}" for g, n in counts.items() if n), "",
              "| Gravité | Catégorie | Élément | A | B | Cause probable | Détail |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for g in gaps:
        cells = [GRAVITY_FR[g.gravity], g.category, g.item, g.a, g.b, g.cause, g.detail]
        lines.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
    return "\n".join(lines + [""])


def write_outputs(a: dict, b: dict, gaps: list[Gap], folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ecarts.md").write_text(render_markdown(a, b, gaps), encoding="utf-8")
    (folder / "ecarts.json").write_text(json.dumps({"format": 1, "a": a["name"], "b": b["name"],
                                                    "ecarts": [asdict(g) for g in gaps]},
                                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return folder / "ecarts.md"
