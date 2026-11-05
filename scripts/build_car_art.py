# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique les pochettes d'Android Auto fournies avec l'application (F5) :

    python scripts/build_car_art.py

Source : docs/marque/logo-rond.png. Sortie : android/core/src/main/assets/pochettes/<clé>.jpg, 512 x 512 px.
`logo` = le logo seul ; une image par bande (logo assombri et nom de la bande) ; `hors_bande`. Les clés sont celles de
logic/Artwork.kt (le test Kotlin ArtworkTest vérifie que chaque clé a son image). Texte FIXE seulement : aucune
fréquence ni mesure (règles de Google). L'utilisateur remplace une image en déposant `<clé>.png` ou `<clé>.jpg`
dans le dossier `pochettes` de l'application (docs/android-auto.md).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "marque" / "logo-rond.png"
OUT = ROOT / "android" / "core" / "src" / "main" / "assets" / "pochettes"
SIZE = 512

# Clé -> (texte principal, ligne du dessous). Même ordre que Radio.BANDS + VHF/UHF (Artwork.kt).
BANDS = {
    "160m": ("160 m", ""), "85m": ("85 m", "écoute"), "80m": ("80 m", ""), "60m": ("60 m", ""),
    "45m": ("45 m", "écoute"), "40m": ("40 m", ""), "30m": ("30 m", ""), "20m": ("20 m", ""),
    "17m": ("17 m", ""), "15m": ("15 m", ""), "12m": ("12 m", ""), "11m": ("11 m", "CB"),
    "10m": ("10 m", ""), "6m": ("6 m", ""), "2m": ("2 m", ""), "70cm": ("70 cm", ""),
    "hors_bande": ("Hors", "bande"),
}


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise SystemExit("Aucune police grasse trouvée (Segoe UI, Arial ou DejaVu Sans).")


def centered(draw: ImageDraw.ImageDraw, y: int, text: str, f: ImageFont.FreeTypeFont) -> None:
    box = draw.textbbox((0, 0), text, font=f)
    x = (SIZE - (box[2] - box[0])) // 2 - box[0]
    draw.text((x, y), text, font=f, fill=(255, 255, 255), stroke_width=6, stroke_fill=(0, 20, 60))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    logo = Image.open(SOURCE).convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    logo.save(OUT / "logo.jpg", quality=85, optimize=True)
    dim = ImageEnhance.Brightness(logo).enhance(0.35)
    big, small = font(150), font(64)
    for key, (main_text, sub) in BANDS.items():
        img = dim.copy()
        d = ImageDraw.Draw(img)
        if sub:
            centered(d, 120, main_text, big)
            centered(d, 300, sub, small)
        else:
            centered(d, 160, main_text, big)
        img.save(OUT / f"{key}.jpg", quality=85, optimize=True)
    print(f"{len(BANDS) + 1} pochettes écrites dans {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
