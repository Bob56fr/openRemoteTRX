# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique les pochettes d'Android Auto fournies avec l'application (F5) :

    python scripts/build_car_art.py

Source : docs/marque/logo-rond.png. Sortie : android/core/src/main/assets/pochettes/<clé>.jpg, 512 x 512 px.
`logo` = le logo seul ; une image par bande (logo réduit en haut, nom de la bande dans un bandeau SOUS l'image,
demande de l'utilisateur) ; `hors_bande`. Les clés sont celles de
logic/Artwork.kt (le test Kotlin ArtworkTest vérifie que chaque clé a son image). Texte FIXE seulement : aucune
fréquence ni mesure (règles de Google). L'utilisateur remplace une image en déposant `<clé>.png` ou `<clé>.jpg`
dans le dossier `pochettes` de l'application (docs/android-auto.md).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "marque" / "logo-rond.png"
OUT = ROOT / "android" / "core" / "src" / "main" / "assets" / "pochettes"
SIZE = 512

LOGO_SIZE = 384                     # logo réduit en haut ; le bandeau du texte occupe le bas
BACKGROUND = (8, 12, 22)            # fond sombre du logo

# Clé -> (texte principal, précision en plus petit). Même ordre que Radio.BANDS + VHF/UHF (Artwork.kt).
BANDS = {
    "160m": ("160 m", ""), "85m": ("85 m", "écoute"), "80m": ("80 m", ""), "60m": ("60 m", ""),
    "45m": ("45 m", "écoute"), "40m": ("40 m", ""), "30m": ("30 m", ""), "20m": ("20 m", ""),
    "17m": ("17 m", ""), "15m": ("15 m", ""), "12m": ("12 m", ""), "11m": ("11 m", "CB"),
    "10m": ("10 m", ""), "6m": ("6 m", ""), "2m": ("2 m", ""), "70cm": ("70 cm", ""),
    "hors_bande": ("Hors bande", ""),
}


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise SystemExit("Aucune police grasse trouvée (Segoe UI, Arial ou DejaVu Sans).")


def caption(draw: ImageDraw.ImageDraw, main: str, sub: str) -> None:
    """Texte centré dans le bandeau sous le logo : principal en grand, précision en plus petit sur la même ligne ;
    taille réduite tant que la ligne ne tient pas dans l'image (marges de 24 px)."""
    for size in range(96, 40, -4):
        parts = [(main, font(size), (255, 255, 255))] + ([("  " + sub, font(size * 52 // 96), (120, 180, 255))] if sub else [])
        widths = [draw.textbbox((0, 0), t, font=f)[2] for t, f, _ in parts]
        if sum(widths) <= SIZE - 48:
            break
    x = (SIZE - sum(widths)) // 2
    baseline = LOGO_SIZE + (SIZE - LOGO_SIZE) // 2 + 34          # même ligne de base pour les deux tailles
    for (text, f, color), w in zip(parts, widths):
        draw.text((x, baseline), text, font=f, fill=color, anchor="ls")
        x += w


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    logo = Image.open(SOURCE).convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    logo.save(OUT / "logo.jpg", quality=85, optimize=True)
    small_logo = logo.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
    for key, (main_text, sub) in BANDS.items():
        img = Image.new("RGB", (SIZE, SIZE), BACKGROUND)
        img.paste(small_logo, ((SIZE - LOGO_SIZE) // 2, 0))
        caption(ImageDraw.Draw(img), main_text, sub)
        img.save(OUT / f"{key}.jpg", quality=85, optimize=True)
    print(f"{len(BANDS) + 1} pochettes écrites dans {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
