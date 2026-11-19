# Allumer et éteindre le poste à distance : cahier des charges (v3, 2026-11-19)

Demande de l'utilisateur (2026-11-19) : allumer et éteindre le TRX depuis la page web et l'application Android.
V2 le même jour (demande de l'utilisateur) : dans l'application, STOP maintenu 3 s = extinction après confirmation
(§ 8.1) ; connexion d'un opérateur à un poste éteint = allumage par la station après vérification des ports série,
avec une fenêtre qui montre les étapes et un message explicite en cas d'erreur (§ 4.1, § 8.2).
V3 le même jour (réponses de l'utilisateur) : MÊME fonctionnement dans la page web et l'application (§ 8.1, § 8.2) ;
allumage aussi depuis Android Auto et le mode conduite, sans fenêtre ; menu de TRX Console « Allumage et extinction
à distance » (2.8) en service / hors service, HORS SERVICE par défaut (§ 8.3).
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

1. **Jamais automatique, sauf une exception** : pas d'allumage au démarrage de la station ni à une reconnexion après une
   coupure réseau, pas d'extinction sur délai (sauf décision contraire, § 10). Le `auto_power_on` de Hamlib n'est
   jamais passé à rigctld. EXCEPTION (décision de l'utilisateur, 2026-11-19, v2) : la connexion d'un OPÉRATEUR lancée
   depuis l'écran de connexion de l'application allume un poste trouvé éteint (§ 8.2) ; c'est l'APPLICATION qui envoie
   `power_on` après le `hello`, jamais la station d'elle-même ; un visiteur ne l'allume jamais. Un opérateur présent au
   poste qui l'a éteint à la main le verra donc se rallumer (en réception) à la connexion suivante.
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
- **Étapes publiées** pendant l'allumage (message `power_progress` à celui qui l'a demandé, et `rig.power` =
  `starting` pour tous) : `ports`, `check_off`, `order`, `wait`, `readback`, `done`, ou `error` avec un code ORT, la
  cause en clair et « que faire ».
- **Après l'allumage** : tout l'état relu (pas de reprise du cache), capacités inchangées (pas de nouveau `dump_caps`),
  règles du § 3.3.
- **Son** : la carte du poste reste ouverte si elle est présente (FTDX10) ; si elle disparaît, mécanisme de l'étape 284
  (`gateway/audio/rigcard.py`, ORT-3012 / 3013) sans alerte « carte perdue » pendant un `off` voulu.
- **Démarrage de la station** : un poste trouvé éteint (`get_powerstat` = 0) est publié `off`, sans panne ni mode sûr.
  Un poste qui ne répond pas du tout reste une panne comme aujourd'hui.
- **Visiteurs** : poste éteint = silence avec la raison (« poste éteint »), comme le silence hors bandes.
- **Diffusion en direct** : raison de silence `poste_eteint` (règle de l'étape 247), diffusion non arrêtée.

### 4.1 Vérification des ports série avant l'allumage (v2)

Seule la STATION peut vérifier ses ports : l'application ne voit que le résultat. Avant tout ordre d'allumage, dans
l'ordre, arrêt à la première erreur (aucun ordre envoyé) :

1. **Port CAT présent** : le port de `[rig] port` existe (Linux : lien `by-id` ; Windows : COM listé).
2. **C'est bien le poste** : l'identité USB du port (fabricant:produit, numéro de série, numéro d'interface ; ex.
   CP2105 du FTDX10, interface 00 « Enhanced » et pas 01 « Standard ») est celle relevée à la mise en service (nouveau
   réglage `[rig] port_usb`, § 6). Sous Windows un numéro COM peut changer avec la prise USB (piège de l'étape 284 pour
   la carte son) : si le poste est retrouvé sur un AUTRE port, refus avec le nouveau port nommé (« Le poste est
   maintenant sur COM7 : menu 2.5 ») ; la passerelle ne réécrit jamais station.toml et n'ouvre jamais un autre port
   de sa propre initiative (un port série ouvert par erreur peut lever RTS / DTR, donc un PTT).
3. **Port du PTT** (PTT par RTS / DTR) : même vérification, ligne PTT relue au repos.
4. **Poste réellement éteint** : rigctld joint, `get_powerstat` = 0 lu sur le poste. Pas de réponse du tout = pas
   d'allumage (« Le poste ne répond pas : câble USB, alimentation 13,8 V, interrupteur arrière ») ; `1` = rien à faire.
5. **Carte son** : absente = avertissement seulement (le poste peut la faire apparaître en s'allumant), relue après.

Une station configurée avant la v2 (sans `port_usb`) : vérifications 1, 3 et 4 seulement, et l'avertissement « identité
du port non relevée : refaire la mise en service au menu 2.8 » dans la fenêtre.

## 5. Superviseur

- Lit `rig.power` sur le bus d'état ET le vérifie lui-même par `\get_powerstat` : `off` confirmé = ni « passerelle
  muette » pour la CAT, ni relance de rigctld, ni reset USB, ni mode sûr.
- `get_powerstat` = 0 alors que la passerelle publie `on` : avertissement (poste éteint à la main, coupure de courant
  du poste) ; c'est un état sûr, pas une escalade.
- L'échelle de reprise reste lancée par une émission qui résiste à `T 0`, comme aujourd'hui.

## 6. Réglages (`station.toml`, station seulement)

- `[rig] power_control = false` par défaut (HORS SERVICE : ni allumage ni extinction possibles) : la commande n'est
  proposée que si `true` et si `dump_caps` la déclare. Mis en service ou hors service par le menu 2.8 de TRX Console
  (§ 8.3), jamais depuis la page ni le téléphone ; une station existante reste hors service (une station.toml garde
  ses valeurs).
- `[rig] power_on_timeout_s = 30` (5 à 120).
- `[rig] port_usb` et `[rig] ptt_port_usb` (v2) : identité USB des ports relevée par le menu 2.8 à la mise en
  service, et de nouveau par le menu 2.5 (ou l'assistant 2.1) quand le port change (texte, ex.
  `10C4:EA70 SN=… IF=00`), vide = non relevée ; jamais d'adresse ni de nom de machine.
- Profils de poste : nouvelle clé de `[rig]` => `PROFILE_FORMAT` + 1 et migration (convention).
- Notice de station.toml (`docs/station-toml/contenu.toml`) à compléter.

## 7. Protocole client (`docs/protocole.md`)

- `hello.features` : `power` (opérateurs seulement, et seulement si autorisé et déclaré).
- Commandes : `power_off` (avec `confirm: true`), `power_on`. Réponse : `ok` ou refus avec code ORT : `tx_active`,
  `local_active`, `power_unsupported`, `power_disabled`, `power_busy`, `power_on_failed`, `rig_off` (toute autre
  commande poste éteint).
- `state.rig.power`, `power_by`, `power_since`.
- Message `power_progress` (v2) à celui qui a demandé l'allumage : `step`, `status` (`running`, `ok`, `error`),
  `ort`, `detail`, `remaining_s`.
- Exemples dans `tests/protocol/`, `docs/parite-web-android.md`, commandes `Command` / `NAMES` de `android/protocol`.

## 8. Interfaces

- **Page** : bouton « Alimentation » dans la rubrique du poste (pas à côté du PTT ni du STOP) ; poste éteint = grand
  bandeau « POSTE ÉTEINT » avec « Allumer le poste », tout le reste grisé ; `starting` = sablier et compte à rebours.
- **Application** : bandeau plein écran poste éteint avec « Allumer le poste » ; extinction par STOP maintenu (§ 8.1) ;
  allumage à la connexion (§ 8.2).

### 8.1 Page et application : STOP maintenu 3 s = extinction (v2, page v3)

Même fonctionnement dans la PAGE WEB et l'APPLICATION (décision de l'utilisateur, v3).

- L'appui sur STOP remet TOUJOURS en réception tout de suite, comme aujourd'hui : l'extinction ne retarde jamais
  STOP.
- Doigt gardé : anneau de progression autour de STOP et texte « Maintenir 3 s pour éteindre le TRX » ; relâcher avant
  3 s = rien de plus (la réception est déjà faite).
- À 3 s : vibration, puis fenêtre « Confirmer l'arrêt à distance de votre TRX ? » avec « Annuler » (par défaut) et
  « Éteindre le TRX » ; la fenêtre se ferme seule après 15 s sans réponse (= Annuler).
- Accepté : `power_off` avec `confirm: true` ; les refus de la station (§ 3.2 : émission en cours, opérateur sur place)
  s'affichent dans la fenêtre avec leur code ORT ; réussite = bandeau « POSTE ÉTEINT ».
- Seulement si `hello.features` annonce `power` (opérateur, `power_control = true`, poste qui le déclare) ; sinon le
  maintien n'a pas d'autre effet que STOP.
- Jamais en mode conduite ni depuis Android Auto (pas de fenêtre à lire en roulant) ; STOP y reste un STOP simple.
- Gros PTT rond : son STOP garde le même comportement.
- Page web : STOP maintenu 3 s n'y vaut PLUS déconnexion (étape 194) : la déconnexion reste au bouton
  « Déconnecter » de la rubrique Connexion, et le texte sous STOP devient « appui long : éteindre le TRX » quand
  `power` est annoncé (rien sinon). Fonction hors service (§ 8.3) : le maintien n'a pas d'autre effet que STOP, dans
  la page comme dans l'application.

### 8.2 Page et application : connexion à un poste éteint = allumage (v2, page v3)

Même fonctionnement dans la PAGE WEB (bouton « Se connecter ») et l'APPLICATION (écran de connexion), v3.

- Après le `hello` et le premier `state` : si `rig.power` = `off`, que le compte est opérateur et que `power` est
  annoncé, l'application envoie `power_on` (sans question : la connexion vaut demande, décision de l'utilisateur).
- Fenêtre « Allumage du TRX » qui ne bloque pas la réception du reste (on peut l'annuler, l'allumage déjà envoyé va
  jusqu'au bout) ; une ligne par étape de `power_progress`, cochée ou en cours, avec le temps restant :
  1. Vérification des ports série du poste (§ 4.1) ;
  2. Vérification que le poste est bien éteint ;
  3. Ordre d'allumage envoyé ;
  4. Démarrage du poste (jusqu'à 30 s ; environ 8 s pour un FTDX10) ;
  5. Relecture : réception confirmée, fréquence et mode.
  Réussite : « TRX allumé : 7 074,00 kHz USB, en réception », fenêtre fermée après 3 s.
- Erreur : la ligne en cause passe en rouge avec un message EXPLICITE (code ORT, cause, que faire) ; exemples :
  « Port COM6 absent : poste débranché ou câble USB ? », « Le poste est maintenant sur COM7 : refaire le menu 2.5 de
  TRX Console sur la station », « Le poste ne répond pas : câble USB, alimentation, interrupteur arrière »,
  « Le poste ne s'est pas allumé en 30 s », « Le poste s'est allumé en émission : remis en réception, vérifier la
  ligne PTT (RTS / DTR) », « Allumage à distance désactivé sur cette station (station.toml) » ; boutons
  « Réessayer » et « Continuer sans le poste » (reste connecté, réception impossible, bandeau « POSTE ÉTEINT »).
- Visiteur : aucun allumage, message « Le poste est éteint ; seul un opérateur peut l'allumer ».
- Connexion lancée depuis Android Auto ou en mode conduite : allumage aussi, sans fenêtre (décision v3) ; titre
  « ALLUMAGE DU POSTE… » puis l'état normal, ou « POSTE ÉTEINT : erreur » avec le code ORT.
- Fonction hors service (§ 8.3) et poste éteint : aucun ordre ; bandeau « POSTE ÉTEINT : allumage à distance hors
  service (menu 2.8 de TRX Console sur la station) ».
- Une reconnexion AUTOMATIQUE après une coupure réseau n'allume pas le poste (seule une connexion demandée par
  l'opérateur le fait).

### 8.3 TRX Console : menu 2.8 « Allumage et extinction à distance » (v3)

Interrupteur EN SERVICE / HORS SERVICE de la fonction, HORS SERVICE par défaut (décision de l'utilisateur) ; nouveau
menu en fin du thème 2 « Poste et matériel » (règle : un nouveau menu s'ajoute en fin de thème), méthode
`remote_power`, 4 langues, aide `h 2.8`, mode d'emploi, niveau Normal.

1. Affiche l'état : en service / hors service, poste déclaré capable ou non par Hamlib (`dump_caps`), identité USB
   relevée des ports, état actuel du poste (allumé / éteint) si la station tourne.
2. **Mettre en service** :
   - refus clair si le modèle ne déclare pas `set_powerstat` / `get_powerstat` (« Votre poste ne peut pas être allumé
     par la CAT d'après Hamlib ») ;
   - avertissement : « Un poste éteint à distance ne se rallume que par la CAT ; si votre poste coupe son USB une fois
     éteint, il faudra appuyer sur ON/OFF au shack. Yaesu : prise USB seulement, pas la prise RS-232C. » ;
   - essai proposé (oui par défaut, poste en réception, station arrêtée le temps de l'essai et redémarrée après) :
     éteindre, vérifier que les ports et la carte son restent présents et que le poste répond « éteint », rallumer,
     relire fréquence, mode et PTT ; un essai en échec = mise en service refusée, avec la cause ;
   - identité USB des ports relevée (`port_usb`, `ptt_port_usb`) ;
   - différences montrées, sudo, `power_control = true` écrit, station redémarrée.
3. **Mettre hors service** : `power_control = false`, station redémarrée ; un poste éteint à ce moment reste éteint
   (message : « Le poste est éteint : allumez-le au shack ou remettez la fonction en service »).
4. Aussi dans la console web (formulaires) et l'écran plein ; aucune commande d'allumage ou d'extinction dans la
   console elle-même (seulement l'interrupteur ; non demandé).
- Station elle-même injoignable (PC éteint) : hors périmètre (réveil par le réseau à étudier à part).
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
- Documentation : guide de l'opérateur (page, application, menu 2.8), fiche des postes (`docs/postes/`), notice de
  station.toml, mode d'emploi de la console (`docs/console/contenu*.toml`, menu 2.8).

## 10. Questions à l'utilisateur

1. Android Auto : état seulement (proposé) ou aussi un bouton « Allumer » ? (l'allumage à la connexion depuis la
   voiture est décidé, v3)
2. RÉPONDU (v3) : menu 2.8 = interrupteur en service / hors service, hors service par défaut ; pas de commande
   d'allumage dans la console.
3. Allumage automatique après une coupure de courant (option désactivée par défaut, seulement au démarrage de la
   station) : voulu ? (le cahier propose NON pour la v1).
4. Extinction automatique après N heures sans client : voulue ? (proposé : NON pour la v1).
5. Alerte ntfy à chaque allumage / extinction : oui, ou journal seulement ?
6. Qui peut éteindre quand plusieurs opérateurs sont connectés : n'importe lequel (proposé), ou seulement s'il est
   seul ?
7. RÉPONDU (v3) : même fonctionnement que l'application (§ 8.1, § 8.2). Question d'origine : page web, où STOP maintenu 3 s = déconnexion depuis l'étape 194 : garder la déconnexion seule, ou ouvrir une
   fenêtre « Se déconnecter » / « Éteindre le TRX » / « Annuler » (proposé, pour rester proche de l'application) ?
   Et l'allumage à la connexion de la page : oui comme l'application (proposé) ?
8. RÉPONDU (v3) : oui, sans fenêtre. Question d'origine : connexion lancée depuis Android Auto ou en mode conduite : allumer aussi (proposé, sans fenêtre), ou ne
   jamais allumer depuis la voiture ?

Réponses déjà données (v2, v3) : page et application identiques, allumage depuis la voiture, menu 2.8 hors service
par défaut ; extinction par STOP maintenu 3 s dans l'application avec confirmation ; allumage par la
connexion d'un opérateur dans l'application, ports série vérifiés, étapes montrées, erreurs explicites.

## 11. Lots

- **P0** : essais à la main du § 1.3 (IC-7300MK2, rigctld de la station, son, démarrage poste éteint).
- **P1** : station : réglages, menu 2.8 de TRX Console (§ 8.3, sans lui la fonction reste hors service), passerelle (§ 4 et vérification des ports § 4.1, avec `port_usb` relevé par
  trx-setup), superviseur (§ 5), protocole (§ 7, dont `power_progress`), codes, tests de panne (port renuméroté,
  mauvais port du CP2105, poste muet, allumé en émission).
- **P2** : page web : STOP maintenu 3 s (déconnexion retirée de ce geste), allumage à la connexion, fenêtre des étapes.
- **P3** : application : STOP maintenu 3 s (§ 8.1), fenêtre d'allumage à la connexion (§ 8.2), Android Auto en état.
- **P4** : `port_usb` relevé aussi par 2.1 / 2.5, trx-monitor, tableau de bord, indicateurs, guide, notices.
