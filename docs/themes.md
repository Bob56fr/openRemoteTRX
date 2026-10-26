# Thèmes de couleurs de la page de contrôle

La page propose quatre thèmes, choisis dans **Affichage > Thème des couleurs** et mémorisés sur chaque appareil :
Thème par défaut (apparence d'origine), Style Icom, Style Yaesu, Style Kenwood. Les trois styles de marque sont
sombres ; ils s'inspirent des afficheurs, sans logo ni graphisme des marques.

## Où sont les couleurs

| Fichier | Rôle |
|---|---|
| `docs/themes.json` | **référence unique** : 21 rôles par thème (et, plus tard, l'application Android) |
| `trxstation/gateway/api/static/client.css` | bloc `:root` = thème par défaut (valeurs exactes d'origine) ; blocs `:root[data-theme="…"]` générés |
| `trxstation/layout/palette.py` | calcul des teintes dérivées et contrôle des thèmes |
| `scripts/build_themes.py` | génère `client.css` et les teintes de `docs/themes.json` |
| `static/theme.js` | applique le thème mémorisé avant l'affichage (attribut `data-theme` de `<html>`) |

Aucune couleur n'est codée en dur ailleurs (vérifié par `tests/test_themes.py`). Le canvas du spectre audio et la
palette du waterfall lisent leurs couleurs dans les variables du thème.

## Les 21 rôles

`fond`, `fond-entete`, `fond-panneau`, `fond-champ`, `texte`, `texte-secondaire`, `texte-sur-accent`, `frequence`,
`accent`, `mesure`, `bouton-fond`, `bouton-texte`, `bouton-bord`, `smetre-bas`, `smetre-haut`, `mesure-haut`, `tx`,
`erreur`, `alerte`, `succes`, `favori`. Les autres teintes (fond du PTT au repos, fond d'alerte, palette du
waterfall…) sont **dérivées** des rôles par `palette.derive`.

## Retoucher une couleur ou ajouter un thème

1. Modifier les rôles du thème dans `docs/themes.json` (couleurs `#rrggbb`). Pour un nouveau thème, ajouter aussi
   son option dans `<select id="theme-select">` de `index.html` (le test vérifie la correspondance).
2. `python scripts/build_themes.py` : calcule les teintes dérivées, contrôle le thème et écrit les fichiers.
   Un thème non conforme n'est **pas** écrit ; le message dit quel couple de couleurs pose problème.
3. `pytest` ; `python scripts/build_themes.py --check` vérifie que tout est à jour sans rien écrire.

## Règles contrôlées

- Contraste WCAG AA : 4,5:1 pour le texte, 3:1 pour les graphiques, les grands chiffres et l'étiquette du PTT en
  émission (grand texte en gras).
- Couleur d'émission (`tx`) **réservée** : aucun autre rôle ne doit s'en approcher (distance RVB d'au moins 80).
- Le thème par défaut est le thème d'usine : il garde l'apparence d'origine et n'est pas contrôlé (il réutilise le
  rouge pour le S-mètre au-delà de S9 et pour les erreurs, comme la page d'origine).
