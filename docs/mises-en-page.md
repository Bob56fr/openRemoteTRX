# Mises en page personnalisées (format 1)

Référence du format produit par le designer et lu par les clients (page web, application Android).
Cahier des charges complet : Claude Doc « Cahier des charges — Designer d'interface Remote TRX ».

## Principe

Un **profil** est un fichier JSON purement déclaratif : aucun code, aucun droit. La station applique
ses règles de sécurité quel que soit le profil. Il est stocké sur la station, un par compte, dans
`<state_dir>/layouts/<identifiant>.json`. Sans profil, la station sert le **profil d'usine**.

```json
{
  "format": 1,
  "name": "Mon interface",
  "rig_model": 3073,
  "theme": {"preset": "icom", "dark": true, "colors": {"accent": "#3fa9f5"}},
  "fonts": {"ui": "system", "display": "DSEG7 Classic", "numeric": "system", "base_size": 16},
  "variants": {
    "phone":  {"portrait": {"widgets": [ ... ]}, "landscape": {"widgets": [ ... ]}},
    "tablet": {"landscape": {"widgets": [ ... ]}}
  }
}
```

## Variantes et cascade

Appareils : `phone` (grille de 4 colonnes), `tablet` (8), `desktop` (12). Chaque appareil utilise sa
variante, sinon la plus proche **en dessous** (affichée centrée, jamais étirée). Sans variante de taille
inférieure ou égale : écran de sécurité. Orientation absente : le portrait s'affiche centré en paysage ;
un paysage seul demande de tourner l'appareil. Voir `trxstation/layout/cascade.py`.

## Widgets

```json
{"id": "nr", "type": "switch", "x": 0, "y": 5, "w": 1, "h": 1,
 "bind": "NR", "target": "main", "appearance": "toggle", "label": "NR", "hidden": false}
```

- `x`, `y`, `w`, `h` : position et taille en cases de grille ; aucun chevauchement (sauf widget masqué).
- `bind` : nom Hamlib d'une fonction (`switch`) ou d'un niveau (`slider`, `select`, `meter`).
  Un nom que le poste ne déclare pas est accepté avec un avertissement : le client masque le widget.
- `target` : `current`, `main`, `sub`, `vfoa`, `vfob` (postes à deux récepteurs).
- `appearance` : une des apparences du type (la première est celle par défaut).
- Un même `id` garde le même type, la même liaison et la même cible dans toutes les variantes.

Types et apparences : `trxstation/layout/catalog.py`.

**Widgets verrouillés** (sécurité) : `ptt` (apparence `toggle` seulement, 2 × 2 cases minimum, un seul
par écran), `tx_indicator`, `link_status`, `tx_armed`. Obligatoires et visibles dans chaque variante et
chaque orientation, au premier niveau, jamais dans un conteneur.

**Conteneurs** (pas de conteneur dans un conteneur ; grille interne = largeur du conteneur) :

- `accordion` : `"sections": [{"title": "...", "open": true, "widgets": [...]}]` (1 à 12 sections).
- `layers` : `"groups": [[{"title": "...", "widgets": [...]}, ...], ...]` (1 à 8 groupes de 1 à 8 calques),
  `"gestures": {"next_layer": "tap", "next_group": "double_tap"}` parmi `tap`, `double_tap`,
  `long_press`, `swipe` (deux gestes différents).

## Thème et polices

Couleurs par rôle : `background`, `surface`, `text`, `text_secondary`, `accent`, `measure`, `alert`,
`emission`. Chartes : `icom` (défaut), `nuit`, `plein_soleil`, `rack_studio`, `sobre`, en sombre ou clair.
Contraste minimal 4,5:1 pour le texte, 3:1 pour les éléments graphiques ; aucune couleur ne doit
ressembler à celle de l'émission. Polices autorisées : `trxstation/layout/theme.py`.

## Protocole (canal « control »)

| Commande | Réponse |
| --- | --- |
| `{"cmd":"layout_get","id":1}` | `result` avec `profile`, `source` (`user` ou `factory`), `warnings` |
| `{"cmd":"layout_save","id":2,"profile":{...}}` | `ok` + `warnings`, ou refus `layout_invalid` + `errors` |
| `{"cmd":"layout_reset","id":3}` | profil d'usine |

`layout_save` est le seul message autorisé au-delà de 2 ko (61 ko au plus) : il doit commencer
exactement par `{"cmd":"layout_save"` (c'est le cas avec `JSON.stringify` du client de référence).

## Rendu dans la page web (`static/layout.js`)

- La page écrite est l'interface d'usine : un profil d'origine `factory` ne la modifie pas.
- Un profil `user` déplace les éléments existants de la page dans une grille ; les accordéons vont dans
  la partie qui défile, tout le reste dans la partie haute.
- Un élément absent du profil est masqué ; un widget sans élément dans la page (fonction pas encore prise
  en charge, ou cible `sub`/`vfob`) est ignoré et signalé dans le journal.
- Sans variante utilisable, en paysage seul tenu en portrait, ou si un widget de sécurité manque :
  écran de sécurité (état de liaison, état d'émission, STOP, défaut).
- Réglages « Affichage » : catégorie d'appareil forcée (seulement vers une catégorie plus petite) et
  retour à l'interface d'usine.

