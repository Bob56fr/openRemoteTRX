# Cahier des charges — Version tablette de l'application « TRX distant » (lot A5)

État : **à faire**, rien n'est codé. Rédigé le 2026-10-29. Complète [`android-cahier-des-charges.md`](android-cahier-des-charges.md) : tout ce qui y est écrit (sécurité, protocole, essais de panne, parité) s'applique ici sans exception.

## 1. Objet

Offrir sur tablette Android (et téléphone pliant ouvert, fenêtre partagée large, ChromeOS) une interface qui profite de la place : afficheur, spectre HF et commandes visibles **en même temps**, sans passer d'un onglet à l'autre.

## 2. Principes (décisions proposées)

1. **Une seule application, un seul APK** (`com.rfdiy.openremotetrx`). La disposition dépend de la **taille de la fenêtre**, pas du type d'appareil. Ainsi, une tablette en fenêtre partagée étroite reçoit l'interface téléphone, et un pliant ouvert reçoit l'interface tablette.
2. **Rien ne change sous l'interface** : `:protocol`, `:logic`, `:core` (RigService, WebRTC, sécurités, battements, TOT, Android Auto) restent communs. Le lot ne touche que `:app`.
3. **Aucun changement de protocole** ni de station. Une tablette est un client comme un autre : même verrou mono-client d'émission, mêmes battements, même retour en RX.
4. **La page web pour PC sert de modèle** (§ 4), adaptée au doigt (§ 5).

## 3. Classes de fenêtre (Material 3, `WindowSizeClass`)

| Largeur de fenêtre | Disposition | Correspond à |
|---|---|---|
| < 600 dp (Compact) | **interface téléphone actuelle**, onglets en bas | téléphone, fenêtre partagée étroite |
| 600 à 839 dp (Medium) | **deux volets** : afficheur + spectre à gauche, rubrique choisie à droite ; rail de navigation à gauche | tablette 8 pouces en portrait, pliant ouvert |
| ≥ 840 dp (Expanded) | **disposition « page PC »** (§ 4) | tablette 10 à 13 pouces en paysage, ChromeOS |

- Seuils alignés avec la page, qui bascule sur le plus petit côté : moins de 600 = téléphone, moins de 900 = tablette (`layout.js`, `detectDevice`). Les deux règles seront rapprochées et testées avec les mêmes cas.
- Changer de taille (rotation, fenêtre partagée, pliage) ne doit **rien** interrompre : ni l'écoute, ni une émission en cours, ni la liaison. L'état vit dans `RigService` et non dans l'écran ; un essai le prouve.

## 4. S'inspirer de la page PC : oui, en grande partie

Aujourd'hui, la page en paysage large (`#app.landscape`) affiche deux colonnes :
- **à gauche** (environ 36 rem) : mode, fréquence, voyants, S-mètre, Po/SWR/ALC, waterfall audio, boutons du poste ;
- **à droite** : spectre HF intégré en haut (interrupteur « Waterfall HF permanent ») et rubriques en accordéons (connexion, accord, mémoires, audio, SELCALL, égaliseur, scrambler, instruments, affichage, cluster, diagnostic, rapport).

Elle convient à une tablette en paysage. Pour l'adapter :

| Page PC | Tablette (Expanded, paysage) |
|---|---|
| Colonne gauche « afficheur » | **Reprise telle quelle** (largeur fixe environ 380 à 420 dp) : mode, fréquence, voyants, bargraphs, boutons du poste, PTT/STOP en bas de colonne |
| Spectre HF intégré en haut à droite | **Toujours affiché** par défaut en haut à droite (hauteur réglable par une poignée, 35 à 60 % de la hauteur), masquable |
| Accordéons empilés à droite | **Volet de rubriques** sous le spectre, choisi par un **rail de navigation** (Mémoires, Cluster DX, Égaliseur/Scrambler, SELCALL, Réglages…) au lieu d'un long défilement |
| Infobulles au survol (`title`) | Pas de survol au doigt : **appui long** = aide courte |
| Molette sur la fréquence | Glisser par chiffre (déjà prévu) ; molette et pavé tactile acceptés si une souris est branchée |

- **Portrait (Medium)** : afficheur et spectre HF empilés en haut (environ 55 % de la hauteur), rubrique en bas, rail à gauche. C'est le portrait de la page agrandi.
- **Les mises en page du designer** (`layouts`) ont déjà une variante `tablet` (grille de 8 colonnes, `docs/mises-en-page.md`). Elles restent « plus tard » dans l'application (lot A4). La disposition d'usine de la tablette reprend la même idée de grille, ce qui facilitera le branchement futur.

## 5. Ce qui change par rapport au PC

- **Cibles tactiles de 48 dp au moins**, y compris pour les boutons compacts du poste (la page PC suppose une souris).
- **PTT et STOP** toujours visibles, à la même place quelle que soit la rubrique ouverte. STOP est séparé du PTT d'au moins 16 dp, pour ne pas se tromper de bouton. L'état « ÉMISSION EN COURS » et le compte à rebours du TOT sont lisibles à 1 m.
- **Une main** : sur 11 pouces en paysage, les commandes d'émission sont en bas de la colonne gauche, à portée du pouce.
- **Clavier physique** (housse-clavier, ChromeOS) : raccourcis de navigation et d'accord seulement (flèches = pas de fréquence, chiffres = saisie). **Aucun raccourci clavier pour le PTT dans ce lot** : une touche heurtée par erreur suffirait à émettre. Échap = STOP est possible, car couper est toujours permis.
- **Pas de mode conduite ni d'Android Auto** propres à la tablette : ils restent liés au téléphone. Une tablette fixée dans un véhicule en roulant n'est pas un usage prévu, et le PTT tactile y est désactivé par les mêmes règles que le téléphone (§ A3).

## 6. Particularités matérielles des tablettes

- **Souvent sans téléphonie** : la règle « appel entrant => STOP » ne s'applique pas, mais la **perte du focus audio** (visio, autre application) coupe toujours l'émission, comme sur le téléphone.
- **Souvent sans vibreur** : les alertes de liaison passent par le son et un bandeau bien visible.
- **Micro** : souvent loin de la bouche, ou en réseau de micros avec traitement agressif. Il faut conseiller un casque ou un micro externe (USB-C, Bluetooth), et vérifier que l'égaliseur et le limiteur se comportent bien avec ce micro.
- **Wi-Fi seul** fréquent : les délais de reconnexion sont les mêmes ; un message clair s'affiche si le réseau disparaît.
- **Écran allumé** pendant la connexion (déjà fait sur le téléphone) : sur tablette posée, proposer un **mode station** (écran atténué, toujours allumé, branché sur secteur).
- **Écoute écran éteint** : même service au premier plan que sur le téléphone, à essayer sur la tablette, car certains fabricants arrêtent plus vite les applications en arrière-plan.

## 7. Travail à prévoir dans `:app`

1. **Découper `RigScreen.kt`** (858 lignes) en blocs réutilisables : afficheur, boutons du poste, PTT/STOP, mémoires, cluster, réglages. Chaque bloc ne connaît pas sa place à l'écran. C'est le préalable, et il rend aussi l'interface téléphone plus simple à maintenir.
2. Dans `MainActivity`, choisir l'une des trois dispositions selon `WindowSizeClass` (bibliothèque `material3-adaptive`, `NavigationSuiteScaffold` pour basculer entre barre et rail, `ListDetailPaneScaffold` ou disposition propre pour les volets).
3. Spectre HF : `HfScopeView` dans un volet de taille variable. La vue « plein écran en paysage » actuelle reste réservée au téléphone.
4. Réglages propres à l'appareil (mémorisés sur l'appareil, comme `trx.hfdock` dans la page) : spectre affiché ou non, hauteur du spectre, rubrique ouverte au démarrage, mode station.
5. Manifeste : rien de bloquant (`screenOrientation="fullSensor"` est déjà en place). Vérifier qu'aucune activité ne force l'orientation, que l'application est bien déclarée redimensionnable, et l'apparence sur ChromeOS.

## 8. Essais

- **Émulateurs** : Pixel Tablet (paysage et portrait), émulateur « redimensionnable » (téléphone, pliant, tablette), fenêtre partagée.
- **Tests d'interface** Compose : pour chaque classe de fenêtre, PTT et STOP sont présents et visibles, et l'état TX affiché suit l'état renvoyé par la station.
- **Panne pendant un changement de disposition** : émission en cours, puis rotation, pliage ou fenêtre partagée. La liaison et l'émission ne sont pas coupées par l'écran ; le STOP reste joignable ; le retour en RX se fait au TOT ou à la coupure de liaison comme d'habitude, constaté côté station.
- **Vraie tablette** (à fournir par l'utilisateur), sur charge fictive : 30 minutes d'écoute écran éteint, 10 émissions sans état affiché faux, égaliseur avec le micro de la tablette.
- **Matrice de parité** : une colonne n'est pas nécessaire ; on ajoute une ligne « disposition tablette » et une remarque sur les fonctions dont l'affichage diffère.

## 9. Quand l'intégrer

- **Après le lot A3** (interface smartphone complète, en cours : mode conduite). La tablette réutilise les mêmes écrans ; les découper avant qu'ils soient finis obligerait à le faire deux fois.
- **Ordre** : (1) découpage de `RigScreen` sans changement visible sur le téléphone, (2) disposition Expanded en paysage (le cas le plus utile), (3) Medium et portrait, (4) clavier physique et mode station.
- Le **designer** (`layouts`, variante `tablet`) vient éventuellement ensuite (lot A4).

## 10. Questions pour l'utilisateur

- Quelle tablette (marque, taille, version d'Android) servira aux essais ? A-t-elle un micro correct, un vibreur, une SIM ?
- Usage principal : tablette posée au salon (mode station), ou tenue en main ?
- Faut-il garder les onglets du téléphone dans l'interface tablette (même habitude), ou passer au rail de navigation proposé ?
- Raccourci clavier Échap = STOP : oui ou non ?
