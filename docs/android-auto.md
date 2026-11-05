# Android Auto : audit (étape 0) et pochettes

Cahier des charges « Android Auto et audio client » du 2026-11-05 (F1 à F6). Livraison 1 : audit, cadenas (F6),
pochettes (F5) ; plus la correction du son perdu sous Android Auto (étape 127, application 0.46.0). Livraison 2 :
favoris au volant (F1), réglages du poste en sous-titre (F3) (étape 128, application 0.47.0).

## 1. Audit de l'existant

### 1.1 API de l'écran de la voiture

Lecteur média standard du système (pas la Car App Library) : `RigAutoService` (`android.service.media.MediaBrowserService`,
API du système, pas `MediaBrowserServiceCompat` ni Media3) et UNE `MediaSession` commune (`RigMedia`), partagée avec le
PTT par le bouton du casque. Logique pure et testée dans `logic/Car.kt` (`CarTest`) ; `RigMedia` ne fait que l'afficher.
Conséquence : F1, F3 et F5 se font avec les champs média standard (titre, sous-titre, pochette, Parcourir).

### 1.2 Actions personnalisées et état du lecteur

`PlaybackState` est construit par `RigMedia.playback()` et republié par `RigMedia.refresh()` à CHAQUE changement de
`RigHub.ui` (seulement si le texte, les boutons ou la pochette ont changé).

| Action | Pictogramme | Effet |
|---|---|---|
| `ptt` ÉMETTRE / FIN D'ÉMISSION | micro | PTT toggle, visible seulement si « Émission autorisée » ; prendre l'émission : Android Auto et l'application seulement |
| `stop` STOP | carré | ne fait que couper |
| `arm` / `disarm` | cadenas | « Émission autorisée » |
| `release_local` | main | « Reprendre la main » après une action sur le poste |
| Lecture / Pause | standard | réception audible ou muette ; jamais le PTT |
| Arrêt (`onStop`) | standard | STOP de l'émission |

Touches du volant : Lecture/Pause seulement ; avec le réglage « PTT par le bouton », la touche Lecture/Pause du volant ou
du casque devient le PTT toggle (`RigService.mediaButton`). Suivant / Précédent : non déclarées aujourd'hui (F1).

### 1.3 Chaîne audio du téléphone

- Réception : piste WebRTC (Opus) -> crochet `setRenderPreProcessing` (`VoiceHub.RxProcessor` : débrouillage du
  scrambler, enregistrement de rediffusion) -> sortie média (`USAGE_MEDIA`). Spatialisation ST : `SpatialHub`
  (`AudioTrackSink` + `AudioTrack` de l'application, piste WebRTC à volume 0). Aucun égaliseur ni effet en réception.
- Émission : micro -> annulation d'écho -> `VoiceHub.Processor` (porte de bruit, égaliseur 10 bandes, chorus,
  réverbération, limiteur) -> Opus. Réglages enregistrés sur le téléphone, profils ★ sur la station.
- À NOTER pour F4 : l'égaliseur, le chorus et la réverbération agissent sur la VOIX ÉMISE, pas sur le son reçu. Un
  interrupteur général « Égaliseur et effets » existe déjà (réglages gardés quand il est coupé) : F4 consistera surtout à
  le rendre visible sur l'écran principal et sur la voiture, avec le fondu de 50 ms. F2 (squelch vocal) agit sur la
  RÉCEPTION, avant le débrouillage.

### 1.4 Données exposées par la station

Tout ce que demandent F1 et F3 est déjà publié (aucune modification de la station) : `state.rig.functions` (NB, NR…),
`state.rig.levels` (PREAMP, ATT, RFPOWER), `hello.max_power_w` (puissance en watts), `hello.capabilities` (ce que le poste
gère), état du PTT (`state.ptt`), mémoires avec `favorite` (`hello.memories`). « Émission autorisée » n'est PAS un état
de la station : c'est la sécurité E4 du CLIENT (`RigSession.arming`, remise à zéro à chaque reconnexion) ; la station
reste maître du PTT. Le cadenas montre donc l'état de `RigSession`, jamais un état supposé par l'écran.

### 1.5 Pourquoi le cadenas restait fermé (F6)

`RigMedia.icon()` donnait `ic_car_arm` (cadenas fermé) aux DEUX actions `arm` et `disarm` : l'état changeait bien
(bouton ÉMETTRE apparu), mais le pictogramme jamais. Corrigé : `CarButton.icon` choisi par `logic.Car` selon l'état
(fermé, ouvert, en émission, inconnu) ; test `cadenas - quatre etats distincts…` (non-régression).

### 1.6 Son perdu sous Android Auto

Le focus audio n'était demandé qu'une fois, à la connexion. Après une perte PASSAGÈRE (assistant vocal, guidage, appel
par la voiture), la réception restait muette jusqu'à ce qu'Android rende le focus ; s'il ne le rendait pas, seule une
relance de l'application rétablissait le son. Désormais Lecture (voiture, volant) et la connexion d'Android Auto
redemandent le focus (`RigService.regainAudio`) ; la réception reste muette tant qu'un appel le garde. Hypothèse la
plus probable, À CONFIRMER en voiture ; si le son se perd encore : `adb logcat` pris au moment de la perte.

## 2. Cadenas (F6)

| État relu | Pictogramme | Libellé | Appui |
|---|---|---|---|
| Émission non autorisée | cadenas fermé | Émission verrouillée | autorise |
| Autorisée, en réception | cadenas ouvert | Émission autorisée | verrouille |
| En émission (la sienne) | cadenas ouvert et ondes | En émission | rien (FIN D'ÉMISSION ou STOP) |
| Réception seule (micro refusé) | cadenas fermé | Réception seule | rien |
| Liaison absente ou perdue | cadenas barré | État d'émission inconnu | rien |

Le cadenas ne déclenche jamais le PTT. L'écran est republié dès que l'état change.

## 3. Pochettes (F5)

L'image à droite de l'écran de lecture suit la fréquence du poste : `logo` sans liaison, une image par bande (`160m`,
`85m`, `80m`, `60m`, `45m`, `40m`, `30m`, `20m`, `17m`, `15m`, `12m`, `11m`, `10m`, `6m`, `2m`, `70cm`), `hors_bande`
ailleurs. Les mêmes images servent d'icônes aux bandes et aux mémoires dans Parcourir. Images des bandes : logo en
haut, nom de la bande dans un bandeau EN DESSOUS (« 45 m écoute », « 11 m CB », « Hors bande » ; demande de
l'utilisateur). Rien de dynamique n'est dessiné
dedans (règles de Google). Images fournies : `android/core/src/main/assets/pochettes/` (fabriquées par
`python scripts/build_car_art.py` depuis `docs/marque/logo-rond.png`).

### Remplacer une image (sans recompiler)

1. Préparer une image CARRÉE, 512 x 512 px conseillé (1024 au plus), PNG ou JPEG, lisible sur fond sombre, sans texte
   fin (l'écran de la voiture la réduit).
2. La nommer d'après la clé : `logo.png`, `40m.png`, `hors_bande.jpg`… (minuscules ; une autre clé est ignorée).
3. Ouvrir une fois l'application connectée à une station (le dossier est créé à ce moment-là).
4. Brancher le téléphone au PC en USB, mode « Transfert de fichiers », puis copier l'image dans
   `Ce PC > Galaxy S25 > Stockage interne > Android > data > com.rfdiy.openremotetrx > files > pochettes`.
   Si l'Explorateur ne montre pas ce dossier : `adb push 40m.png /sdcard/Android/data/com.rfdiy.openremotetrx/files/pochettes/`.
5. L'image est prise au prochain changement de bande ou à la prochaine connexion. Pour revenir à l'image fournie :
   supprimer le fichier.

Une image de l'utilisateur absente ou vide = image fournie ; clé inconnue = rien. Le dossier est effacé à la
désinstallation de l'application (pas lors d'une mise à jour).

## 4. Favoris au volant (F1)

- Suivant / Précédent (touches du volant ou de l'écran) font défiler les MÉMOIRES FAVORITES (★, décision de
  l'utilisateur), par fréquence, en boucle. Depuis une fréquence qui n'est pas un favori : Suivant = premier favori
  au-dessus, Précédent = premier en dessous.
- Appuis regroupés : le favori choisi s'affiche aussitôt en titre ; seul le dernier part vers la station, 300 ms après
  le dernier appui (`logic/Favorites.kt`, `FavoriteStepper`).
- En émission (la sienne ou celle d'un autre) : refusé, « Changement refusé : émission en cours » dans le journal ; la
  station refuse aussi (`tx_active`). Hors liaison : touche sans effet, sans erreur. Visiteur : aucune touche.
- Aucun favori : boutons Suivant / Précédent masqués.
- Parcourir > Favoris (en tête) : les mêmes favoris, avec leur pochette en icône ; un appui cale le poste.
- Lecture / Pause garde sa fonction (son muet ou audible ; PTT seulement avec le réglage « PTT par le bouton ») ;
  Suivant / Précédent ne commandent JAMAIS l'émission.
- DHU (pas de volant) : console du DHU, `keycode media_next` / `keycode media_previous`.
- À VÉRIFIER au DHU et en voiture : Suivant / Précédent prennent deux places du lecteur ; ÉMETTRE et STOP doivent
  rester visibles sans passer par le menu « ⋯ ».

## 5. Écran de lecture (F3)

| Champ | Contenu | Exemple |
|---|---|---|
| Titre | nom de la mémoire (ou du favori choisi), sinon fréquence et mode ; « ÉMISSION EN COURS 1:05 » en émission | `QSO 20` |
| Sous-titre | réglages ACTIFS seulement, ordre fixe : préampli (ou ATT), NB, NR, puissance au watt, EQ du téléphone | `P.AMP1 · NB · NR · 50 W · EQ` |
| Ligne secondaire (si la voiture l'affiche) | fréquence si le titre est un nom, S-mètre, poste utilisé sur place, réception seule / émission non autorisée, muet, SELCALL ouvert, station | `14 195,00 kHz USB · S7 · Maison` |

Un réglage que la station ne publie pas (poste qui ne le gère pas) n'apparaît jamais. Puissance en % si la station
ne connaît pas la puissance maximale. « EQ » = égaliseur de la voix ÉMISE en service, absent quand la voix passe par
Breizh. Sous-titre limité à 40 caractères (séparateurs resserrés, puis coupé). Texte mis à jour au plus une fois par
seconde ; boutons, cadenas et état d'émission aussitôt.
