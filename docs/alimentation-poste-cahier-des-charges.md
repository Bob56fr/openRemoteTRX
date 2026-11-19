# Allumer et éteindre le poste à distance : cahier des charges (v1, 2026-11-19)

Demande de l'utilisateur (2026-11-19) : allumer et éteindre le TRX depuis la page web et l'application Android.
Idée d'origine : `docs/boite-a-idees.md` (2026-11-14) : après une coupure de courant, une station distante reste muette
tant que personne n'appuie sur ON/OFF. Aucun code à ce stade.

## 1. Ce que l'on sait

### 1.1 Hamlib

- Commandes `\set_powerstat 0|1|2` (éteint, allumé, veille) et `\get_powerstat` ; `dump_caps` annonce « Can set Power
  Stat » / « Can get Power Stat ».
- Icom (IC-7300MK2 : Y / Y dans nos relevés Hamlib 4.7.2 et 5.0) : CI-V `18 00` / `18 01`, Hamlib envoie d'abord une
  longue suite de `FE` pour réveiller le poste.
- Yaesu newcat (FTDX10 : Y / Y en Hamlib 4.7.2) : `PS0;` / `PS1;`, Hamlib répète `PS1;` pour réveiller le poste.

### 1.2 Essai réel du FTDX10 (2026-11-19, PC Windows, Hamlib 4.7.2, `rigctl` direct, sans station ni émission)

| Étape | Constat |
|---|---|
| Avant | `get_powerstat` = 1 (`PS1;`), 28,074 MHz USB 3000 Hz, PTT 0 |
| `set_powerstat 0` | accepté en 0,6 s |
| Poste éteint (30 s) | COM6, COM9 et la carte son « USB AUDIO CODEC » restent présents (Windows : OK) ; le poste répond `get_powerstat` = 0 en 2,1 s (0,7 s allumé) ; `rigctl` ouvre le poste éteint sans erreur |
| `set_powerstat 1` | accepté en 7,9 s, sans recours au `PS1;` brut |
| Après | répond 1 s après ; 28,074 MHz USB 3000 Hz, PTT 0 : état retrouvé |

Conséquences : poste éteint, le port reste là (le superviseur ne voit pas « poste débranché », `rig_absent`) mais la
CAT est presque muette ; `get_powerstat` distingue de façon sûre « éteint » de « liaison cassée » ; l'allumage
bloque environ 8 s.

### 1.3 Pas encore vérifié (lot P0)

1. IC-7300MK2 (minix-bzh, puis Windows) : même essai ; port CAT, port B (`-if02`) et carte son C-Media restent-ils
   présents poste éteint ? Hamlib ouvre-t-il un Icom éteint (l'ouverture l'interroge) ?
2. Les deux postes : le même cycle À TRAVERS le rigctld de la station (`-C cache_timeout=0`), et le son : carte
   ouverte par la passerelle pendant l'extinction, son revenu après l'allumage sans relancer la passerelle.
3. Station démarrée poste éteint (port présent) : comportement actuel de la passerelle et du superviseur (échelle de
   reprise lancée à tort ?).
4. Prise RS-232C d'un Yaesu : allumage impossible (manuel CAT) ; à confirmer si un tel poste se présente.
5. Coupure de courant réelle (poste et PC) : le FTDX10 revient-il éteint ? (sinon la fonction n'aide pas ce cas).

## 2. Périmètre

- Commandes « Éteindre le poste » et « Allumer le poste » depuis la PAGE et l'APPLICATION (smartphone, tablette).
- Réservées aux OPÉRATEURS ; jamais aux visiteurs (liste blanche de `ControlSession.on_message` inchangée).
- Proposées seulement si le poste les déclare (`dump_caps`) ET si la station les autorise (§ 6).
- Android Auto : état seulement (« POSTE ÉTEINT » en titre), AUCUN bouton (à confirmer, § 10).
- TRX Console et `trx-monitor` : état affiché ; commande dans la console : voir § 10.
- Hors périmètre : prise ou alimentation pilotée (relais, prise connectée) pour un poste qui ne s'allume pas par la
  CAT : plus tard, autre cahier si besoin.

## 3. Règles de sécurité

Ces commandes ne touchent pas au PTT, mais elles agissent sur le poste à distance ; règles retenues :

1. **Jamais automatique** : pas d'allumage au démarrage de la station ni à la reconnexion d'un client, pas d'extinction
   sur délai (sauf décision contraire, § 10). Le `auto_power_on` de Hamlib n'est jamais passé à rigctld.
2. **Éteindre** est refusé pendant une émission (client, locale, mesure de TOS, SELCALL, rediffusion, bip de fin) et
   pendant les 2 minutes qui suivent une action sur le poste (opérateur sur place présent). Avant l'ordre : PTT relu à
   0 sur le poste (jamais depuis le cache) ; sinon refus.
3. **Allumer** ne met jamais en émission : après l'allumage, la passerelle relit le PTT ; s'il est à 1 (ligne RTS / DTR
   d'un PTT série au démarrage du poste, avertissement de Yaesu) : `T 0` immédiat, alerte, et le poste est traité comme
   une émission qui résiste. Puis mêmes étapes qu'à une connexion : VOX coupé (`switch_vox_off`), état relu, RX.
4. **Confirmation** dans la page et l'application (« Éteindre le poste ? Personne ne pourra plus l'écouter. ») ;
   allumer sans confirmation (sans risque), mais un seul ordre à la fois.
5. Pendant l'allumage (jusqu'à 20 s) et poste éteint : toute prise d'émission est refusée (`rig_off`), toute commande de
   réglage aussi.
6. Le superviseur NE commande jamais l'alimentation (ni allumage ni extinction) ; il reconnaît seulement l'état « éteint
   volontairement » (§ 5). Fail-safe : poste éteint = réception seule, par construction.
7. Qui a éteint, quand : ligne au journal (code ORT d'information, comme ORT-4019) et alerte ntfy facultative.

## 4. Passerelle

- **État** `rig.power` publié : `on`, `off`, `starting`, `stopping`, `unknown` ; plus `power_by` (pseudo de l'opérateur)
  et `power_since`.
- **Poste éteint** : `CatLink` suspend toutes les lectures périodiques (fréquence, mode, S-mètre…) et ne lit plus que
  `\get_powerstat` (toutes les 5 s) ; aucune lecture lente qui ferait tomber la liaison (piège « poste lent »). Une
  liaison qui casse poste éteint reste une panne normale.
- **Allumage** : envoyé hors de la boucle CAT habituelle, délai 20 s ; puis attente de `get_powerstat` = 1 (30 s au plus) ;
  échec = retour à `off` (ou `unknown`) avec le refus `power_on_failed` montré à celui qui a cliqué.
- **Après l'allumage** : tout l'état relu (pas de reprise du cache), capacités inchangées (pas de nouveau `dump_caps`),
  règles du § 3.3.
- **Son** : la carte du poste reste ouverte si elle est présente (FTDX10) ; si elle disparaît, mécanisme de l'étape 284
  (`gateway/audio/rigcard.py`, ORT-3012 / 3013) sans alerte « carte perdue » pendant un `off` voulu.
- **Démarrage de la station** : un poste trouvé éteint (`get_powerstat` = 0) est publié `off`, sans panne ni mode sûr.
  Un poste qui ne répond pas du tout reste une panne comme aujourd'hui.
- **Visiteurs** : poste éteint = silence avec la raison (« poste éteint »), comme le silence hors bandes.
- **Diffusion en direct** : raison de silence `poste_eteint` (règle de l'étape 247), diffusion non arrêtée.

## 5. Superviseur

- Lit `rig.power` sur le bus d'état ET le vérifie lui-même par `\get_powerstat` : `off` confirmé = ni « passerelle
  muette » pour la CAT, ni relance de rigctld, ni reset USB, ni mode sûr.
- `get_powerstat` = 0 alors que la passerelle publie `on` : avertissement (poste éteint à la main, coupure de courant
  du poste) ; c'est un état sûr, pas une escalade.
- L'échelle de reprise reste lancée par une émission qui résiste à `T 0`, comme aujourd'hui.

## 6. Réglages (`station.toml`, station seulement)

- `[rig] power_control = false` par défaut : la commande n'est proposée que si `true` et si `dump_caps` la déclare.
  Proposé par `trx-setup` (partie poste, menu 2.5) après un essai réussi (lot P0 automatisé : éteindre, relire,
  allumer, relire), avec l'avertissement « un poste éteint à distance ne se rallume que par la CAT : vérifiez que
  votre poste garde l'USB alimenté » ; jamais modifiable depuis le téléphone.
- `[rig] power_on_timeout_s = 30` (5 à 120).
- Profils de poste : nouvelle clé de `[rig]` => `PROFILE_FORMAT` + 1 et migration (convention).
- Notice de station.toml (`docs/station-toml/contenu.toml`) à compléter.

## 7. Protocole client (`docs/protocole.md`)

- `hello.features` : `power` (opérateurs seulement, et seulement si autorisé et déclaré).
- Commandes : `power_off` (avec `confirm: true`), `power_on`. Réponse : `ok` ou refus avec code ORT : `tx_active`,
  `local_active`, `power_unsupported`, `power_disabled`, `power_busy`, `power_on_failed`, `rig_off` (toute autre
  commande poste éteint).
- `state.rig.power`, `power_by`, `power_since`.
- Exemples dans `tests/protocol/`, `docs/parite-web-android.md`, commandes `Command` / `NAMES` de `android/protocol`.

## 8. Interfaces

- **Page** : bouton « Alimentation » dans la rubrique du poste (pas à côté du PTT ni du STOP) ; poste éteint = grand
  bandeau « POSTE ÉTEINT » avec « Allumer le poste », tout le reste grisé ; `starting` = sablier et compte à rebours.
- **Application** : même chose (onglet Station, et Réglages) ; bandeau plein écran poste éteint ; jamais en mode
  conduite.
- **Android Auto** : titre « POSTE ÉTEINT », lecteur sans son ; aucun bouton (§ 10).
- **trx-monitor et tableau de bord 1.3** : ligne « Poste : éteint par <pseudo> depuis HH:MM ».
- **Indicateurs GNOME / Windows** : couleur neutre « poste éteint » (`status.js` et vecteurs).

## 9. Erreurs, tests, documentation

- Codes ORT nouveaux (catalogue, 4 langues pour les messages de console) : refus ci-dessus, information « poste
  éteint / allumé par … », avertissement « poste éteint hors de la station », échec de l'allumage.
- Tests (modèle factice Hamlib 1 : vérifier qu'il accepte `set_powerstat`, sinon faux rigctld) : extinction refusée
  pendant chaque sorte d'émission et pendant une émission locale ; PTT relu à 1 après l'allumage => `T 0` et alerte ;
  aucune prise d'émission pendant `starting` et `off` ; client perdu pendant l'allumage (rien ne change, pas
  d'émission) ; superviseur : poste éteint = aucune escalade, poste éteint hors station = avertissement seul ; passerelle
  gelée poste éteint = escalade normale ; visiteur : commandes refusées.
- Documentation : guide de l'opérateur (page, application, réglage 2.5), fiche des postes (`docs/postes/`), notice de
  station.toml, mode d'emploi de la console si le menu 2.5 change.

## 10. Questions à l'utilisateur

1. Android Auto : état seulement (proposé) ou aussi un bouton « Allumer » ?
2. Commande dans TRX Console (ex. menu 1.5 « Allumer / éteindre le poste ») utile ?
3. Allumage automatique après une coupure de courant (option désactivée par défaut, seulement au démarrage de la
   station) : voulu ? (le cahier propose NON pour la v1).
4. Extinction automatique après N heures sans client : voulue ? (proposé : NON pour la v1).
5. Alerte ntfy à chaque allumage / extinction : oui, ou journal seulement ?
6. Qui peut éteindre quand plusieurs opérateurs sont connectés : n'importe lequel (proposé), ou seulement s'il est
   seul ?

## 11. Lots

- **P0** : essais à la main du § 1.3 (IC-7300MK2, rigctld de la station, son, démarrage poste éteint).
- **P1** : station : réglages, passerelle (§ 4), superviseur (§ 5), protocole (§ 7), codes, tests de panne.
- **P2** : page web.
- **P3** : application (et Android Auto en état seul).
- **P4** : trx-setup (essai et réglage), trx-monitor, tableau de bord, indicateurs, guide, notices.
