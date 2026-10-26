"""Validation d'un profil de mise en page. Toute entrée externe passe par ici avant d'être stockée ou affichée.

`validate_profile` ne lève jamais d'exception sur une donnée mal formée : il renvoie un `Report`.
  * ERREURS : le profil est refusé (structure, géométrie, règles de sécurité, contraste...).
  * AVERTISSEMENTS : le profil est accepté, mais un widget est lié à une fonction que ce poste ne déclare pas :
    il reste dans le profil et l'interface le masque (§2 du cahier des charges).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .catalog import (DEVICE_LABELS, DEVICES, FORMAT_VERSION, GESTURES, GRID_COLUMNS, HAMLIB_NAME_RE, LOCKED,
                      MAX_LABEL, MAX_NAME, MAX_PROFILE_BYTES, MAX_ROWS, MAX_WIDGETS, ORIENTATIONS, TARGETS,
                      WIDGET_ID_RE, WIDGETS)
from .theme import BASE_SIZE_RANGE, FONTS, MIN_PHONE_BASE_SIZE, PRESETS, ROLES, HEX_RE, check_colors, resolve_colors

MAX_ERRORS = 50
TOP_KEYS = {"format", "name", "rig_model", "theme", "fonts", "variants"}
WIDGET_KEYS = {"id", "type", "x", "y", "w", "h", "appearance", "bind", "target", "label", "text", "hidden", "options",
               "sections", "groups", "gestures"}
MAX_OPTIONS = 10


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, message: str) -> None:
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(message)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": list(self.errors), "warnings": list(self.warnings)}


def _text(value, max_len: int) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= max_len and value.isprintable()


def _int(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


class _Checker:
    def __init__(self, report: Report, capabilities):
        self.r = report
        self.functions = set(getattr(capabilities, "functions", ()) or ())     # vide = inconnu : pas de contrôle
        self.levels = set(getattr(capabilities, "levels", ()) or ())
        self.count = 0
        self.identity: dict[str, tuple] = {}            # id -> (type, bind, target) : identique dans toutes les variantes

    # ------------------------------------------------------------------ un widget
    def widget(self, w, cols: int, where: str, ids: set[str], nested: bool) -> tuple | None:
        """Vérifie un widget ; renvoie son rectangle (x, y, w, h) s'il occupe de la place, sinon None."""
        r = self.r
        self.count += 1
        if not isinstance(w, dict):
            r.error(f"{where} : un widget doit être un objet")
            return None
        wid = w.get("id")
        label = f"{where} › {wid}" if isinstance(wid, str) else where
        unknown = set(w) - WIDGET_KEYS
        if unknown:
            r.error(f"{label} : champ(s) inconnu(s) {', '.join(sorted(unknown))}")
        if not isinstance(wid, str) or not WIDGET_ID_RE.fullmatch(wid):
            r.error(f"{label} : identifiant invalide (minuscules, chiffres, _ et -, 32 caractères max)")
            return None
        if wid in ids:
            r.error(f"{label} : identifiant en double")
        ids.add(wid)
        kind = w.get("type")
        spec = WIDGETS.get(kind) if isinstance(kind, str) else None
        if spec is None:
            r.error(f"{label} : type de widget inconnu « {str(kind)[:24]} »")
            return None

        # géométrie
        x, y, width, height = (w.get(k) for k in ("x", "y", "w", "h"))
        if not (_int(x, 0, cols - 1) and _int(y, 0, MAX_ROWS - 1) and _int(width, 1, cols) and _int(height, 1, MAX_ROWS)):
            r.error(f"{label} : position ou taille invalide (x, y, w, h entiers dans une grille de {cols} colonnes)")
            return None
        if x + width > cols or y + height > MAX_ROWS:
            r.error(f"{label} : dépasse de la grille ({cols} colonnes)")
        min_w, min_h = spec.min_size
        if width < min(min_w, cols) or height < min_h:
            r.error(f"{label} : trop petit pour un widget « {kind} » (minimum {min(min_w, cols)} × {min_h} cases)")

        # apparence, liaison, cible, textes
        appearance = w.get("appearance", spec.appearances[0])
        if appearance not in spec.appearances:
            r.error(f"{label} : apparence « {str(appearance)[:20]} » impossible pour « {kind} » "
                    f"(possibles : {', '.join(spec.appearances)})")
        bind = w.get("bind")
        if spec.bind == "none":
            if bind is not None:
                r.error(f"{label} : un widget « {kind} » ne se lie à aucune fonction")
        elif not isinstance(bind, str) or not HAMLIB_NAME_RE.fullmatch(bind):
            r.error(f"{label} : « bind » doit nommer {'une fonction' if spec.bind == 'func' else 'un niveau'} Hamlib (ex. NR, SQL)")
        else:
            known = self.functions if spec.bind == "func" else self.levels
            if known and bind not in known:
                self.r.warnings.append(f"{label} : « {bind} » n'est pas déclaré par ce poste ; le widget sera masqué")
        target = w.get("target")
        if spec.target:
            if target is not None and target not in TARGETS:
                r.error(f"{label} : cible invalide (possibles : {', '.join(TARGETS)})")
        elif target is not None:
            r.error(f"{label} : un widget « {kind} » n'a pas de cible")
        for key in ("label", "text"):
            if key in w and not _text(w[key], MAX_LABEL):
                r.error(f"{label} : « {key} » doit être un texte imprimable de 1 à {MAX_LABEL} caractères")
        hidden = w.get("hidden", False)
        if not isinstance(hidden, bool):
            r.error(f"{label} : « hidden » doit valoir true ou false")
        options = w.get("options", {})
        if not isinstance(options, dict) or len(options) > MAX_OPTIONS or not all(
                isinstance(k, str) and WIDGET_ID_RE.fullmatch(k)
                and (isinstance(v, (bool, int, float)) or (isinstance(v, str) and len(v) <= MAX_LABEL))
                for k, v in options.items()):
            r.error(f"{label} : « options » doit être un petit objet de valeurs simples ({MAX_OPTIONS} au plus)")

        # sécurité
        if spec.locked and nested:
            r.error(f"{label} : le widget « {kind} » est verrouillé : jamais dans un accordéon ni une zone à calques")
        if spec.locked and hidden:
            r.error(f"{label} : le widget « {kind} » est verrouillé : il ne peut pas être masqué")

        # identité commune à toutes les variantes (seules position, taille et visibilité changent)
        identity = (kind, bind, target or ("current" if spec.target else None))
        previous = self.identity.setdefault(wid, identity)
        if previous != identity:
            r.error(f"{label} : même identifiant qu'ailleurs dans le profil mais type, liaison ou cible différents")

        # conteneurs
        if spec.container:
            if nested:
                r.error(f"{label} : un conteneur ne peut pas contenir un autre conteneur")
            else:
                self.container(w, spec.container, width, label, ids)
        elif any(k in w for k in ("sections", "groups", "gestures")):
            r.error(f"{label} : seuls les conteneurs ont des sections, groupes ou gestes")
        return None if hidden else (x, y, width, height)

    def container(self, w: dict, kind: str, cols: int, label: str, ids: set[str]) -> None:
        r = self.r
        if kind == "accordion":
            sections = w.get("sections")
            if not isinstance(sections, list) or not 1 <= len(sections) <= 12:
                r.error(f"{label} : un accordéon a de 1 à 12 sections")
                return
            for i, section in enumerate(sections, 1):
                if not isinstance(section, dict) or set(section) - {"title", "open", "widgets"} \
                        or not _text(section.get("title"), MAX_LABEL) or not isinstance(section.get("open", False), bool):
                    r.error(f"{label} › section {i} : titre (texte) et « open » (vrai/faux) attendus")
                    continue
                self.grid(section.get("widgets"), cols, f"{label} › section {i}", ids, nested=True)
        else:
            groups = w.get("groups")
            if not isinstance(groups, list) or not 1 <= len(groups) <= 8:
                r.error(f"{label} : une zone à calques a de 1 à 8 groupes")
                return
            for g, group in enumerate(groups, 1):
                if not isinstance(group, list) or not 1 <= len(group) <= 8:
                    r.error(f"{label} › groupe {g} : de 1 à 8 calques")
                    continue
                for c, layer in enumerate(group, 1):
                    if not isinstance(layer, dict) or set(layer) - {"title", "widgets"} \
                            or ("title" in layer and not _text(layer["title"], MAX_LABEL)):
                        r.error(f"{label} › groupe {g} calque {c} : « widgets » et titre facultatif attendus")
                        continue
                    self.grid(layer.get("widgets"), cols, f"{label} › groupe {g} calque {c}", ids, nested=True)
            gestures = w.get("gestures", {})
            if not isinstance(gestures, dict) or set(gestures) - {"next_layer", "next_group"} \
                    or any(v not in GESTURES for v in gestures.values()):
                r.error(f"{label} : gestes « next_layer » / « next_group » parmi {', '.join(GESTURES)}")
            elif gestures.get("next_layer", "tap") == gestures.get("next_group", "double_tap"):
                r.error(f"{label} : le geste du calque suivant et celui du groupe suivant doivent être différents")

    # ------------------------------------------------------------------ une grille
    def grid(self, widgets, cols: int, where: str, ids: set[str], nested: bool) -> list[dict]:
        if not isinstance(widgets, list):
            self.r.error(f"{where} : « widgets » doit être une liste")
            return []
        placed: list[tuple[str, tuple]] = []
        for w in widgets:
            rect = self.widget(w, cols, where, ids, nested)
            if rect is None:
                continue
            for other_id, other in placed:
                if _overlap(rect, other):
                    self.r.error(f"{where} › {w['id']} : chevauche « {other_id} »")
                    break
            placed.append((w["id"], rect))
        return [w for w in widgets if isinstance(w, dict)]


def _overlap(a: tuple, b: tuple) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _check_theme(profile: dict, r: Report) -> None:
    theme = profile.get("theme", {})
    if not isinstance(theme, dict) or set(theme) - {"preset", "dark", "colors"}:
        r.error("theme : objet avec « preset », « dark » et « colors » attendu")
        return
    if theme.get("preset", "icom") not in PRESETS:
        r.error(f"theme : charte inconnue (possibles : {', '.join(PRESETS)})")
        return
    if not isinstance(theme.get("dark", True), bool):
        r.error("theme : « dark » doit valoir true ou false")
        return
    colors = theme.get("colors", {})
    if not isinstance(colors, dict) or any(k not in ROLES or not isinstance(v, str) or not HEX_RE.fullmatch(v)
                                           for k, v in colors.items()):
        r.error(f"theme : « colors » associe des rôles ({', '.join(ROLES)}) à des couleurs #rrggbb")
        return
    for problem in check_colors(resolve_colors(theme)):
        r.error(f"theme : {problem}")


def _check_fonts(profile: dict, r: Report) -> None:
    fonts = profile.get("fonts", {})
    if not isinstance(fonts, dict) or set(fonts) - {*FONTS, "base_size"}:
        r.error("fonts : objet avec « ui », « display », « numeric » et « base_size » attendu")
        return
    for role, allowed in FONTS.items():
        if fonts.get(role, "system") not in allowed:
            r.error(f"fonts : police « {str(fonts.get(role))[:30]} » non autorisée pour « {role} » "
                    f"(possibles : {', '.join(allowed)})")
    size = fonts.get("base_size", 16)
    if not _int(size, *BASE_SIZE_RANGE):
        r.error(f"fonts : « base_size » entier de {BASE_SIZE_RANGE[0]} à {BASE_SIZE_RANGE[1]} px")
    elif size < MIN_PHONE_BASE_SIZE and isinstance(profile.get("variants"), dict) and "phone" in profile["variants"]:
        r.error(f"fonts : sur smartphone, la taille de base est d'au moins {MIN_PHONE_BASE_SIZE} px")


def validate_profile(profile, capabilities=None) -> Report:
    """Valide un profil complet. `capabilities` (descripteur du poste) sert seulement aux avertissements."""
    r = Report()
    if not isinstance(profile, dict):
        r.error("le profil doit être un objet JSON")
        return r
    try:
        size = len(json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        r.error("le profil contient des valeurs non représentables en JSON")
        return r
    if size > MAX_PROFILE_BYTES:
        r.error(f"profil trop volumineux ({size} octets, {MAX_PROFILE_BYTES} au plus)")
        return r
    version = profile.get("format")
    if not _int(version, 1, 10_000):
        r.error("format : numéro de version du format absent ou invalide")
        return r
    if version > FORMAT_VERSION:
        r.error(f"format {version} trop récent pour cette station (format {FORMAT_VERSION}) : mets la station à jour")
        return r
    unknown = set(profile) - TOP_KEYS
    if unknown:
        r.error(f"champ(s) inconnu(s) : {', '.join(sorted(unknown))}")
    if not _text(profile.get("name"), MAX_NAME):
        r.error(f"name : nom du profil de 1 à {MAX_NAME} caractères imprimables")
    rig_model = profile.get("rig_model")
    if rig_model is not None and not _int(rig_model, 1, 999_999):
        r.error("rig_model : numéro de modèle Hamlib (entier) ou null")
    _check_theme(profile, r)
    _check_fonts(profile, r)

    variants = profile.get("variants")
    if not isinstance(variants, dict) or not variants or set(variants) - set(DEVICES):
        r.error(f"variants : au moins une variante parmi {', '.join(DEVICES)}")
        return r
    checker = _Checker(r, capabilities)
    for device in DEVICES:
        orientations = variants.get(device)
        if orientations is None:
            continue
        name = DEVICE_LABELS[device]
        if not isinstance(orientations, dict) or not orientations or set(orientations) - set(ORIENTATIONS):
            r.error(f"{name} : au moins une orientation parmi {', '.join(ORIENTATIONS)}")
            continue
        for orientation in ORIENTATIONS:
            layout = orientations.get(orientation)
            if layout is None:
                continue
            where = f"{name}/{orientation}"
            if not isinstance(layout, dict) or set(layout) != {"widgets"}:
                r.error(f"{where} : objet {{\"widgets\": [...]}} attendu")
                continue
            widgets = checker.grid(layout["widgets"], GRID_COLUMNS[device], where, set(), nested=False)
            visible = [w.get("type") for w in widgets if not w.get("hidden", False)]
            for kind in LOCKED:
                if kind not in visible:
                    r.error(f"{where} : le widget de sécurité « {kind} » est obligatoire et doit rester visible")
            if visible.count("ptt") > 1:
                r.error(f"{where} : un seul bouton PTT par écran")
    if checker.count > MAX_WIDGETS:
        r.error(f"trop de widgets ({checker.count}, {MAX_WIDGETS} au plus)")
    return r
