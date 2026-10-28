# Cahier des charges — Application Android « TRX distant »

Version du document : 1 (2026-10-28, étape 49). Station de référence : version 0.51.0, protocole 1.
Ce document couvre la création de l'application, ses essais, et la façon de faire évoluer ensemble la page web et l'application.

## 1. Objet et raison d'être

L'application est un **second client** de la passerelle existante, au même titre que la page web. Elle ne remplace pas la page : la page reste le client de référence sur PC et le recours si l'application manque.

Elle existe parce que la page web a des limites qu'aucun réglage ne lève (relevées à l'étape 8a-sexies) :

| Limite de la page web | Réponse de l'application |
|---|---|
| Page masquée, autre appli, écran verrouillé : le navigateur gèle la page, les battements s'arrêtent, l'émission est coupée | Service au premier plan (`RigService`) qui garde la connexion et l'audio écran éteint |
| Pas d'Android Auto | `MediaBrowserService` + `MediaSession` |
| Pas de boutons matériels (volant, bouton Bluetooth) | `onMediaButtonEvent`, touches média, bouton HID |
| Micro exige HTTPS, certificat auto-signé accepté « à la main » dans Chrome | Certificat de la station épinglé par son empreinte à l'appairage |
| Pas de mode conduite | Mode conduite propre à l'application |

## 2. Ce qui ne change PAS (exigences non négociables)

L'application **n'ajoute aucune sécurité côté poste et n'en retire aucune** : toutes les sécurités d'émission restent dans la station (passerelle + superviseur). L'application doit simplement ne jamais les contourner ni laisser croire autre chose que l'état réel.

- E1. **PTT en toggle uniquement**, jamais en maintien appuyé, sur tous les supports (écran, voiture, volant, bouton Bluetooth, voix).
- E2. **L'état RX/TX affiché est celui renvoyé par la station** (`state.ptt.state`). L'application envoie `toggle` ou `stop` et attend ; jamais d'affichage « émission » supposé.
- E3. **Battements** (`heartbeat`) toutes les 400 ms dès la demande de prise d'émission et pendant toute l'émission (la station attend 500 ms, coupe à 2 s). Les battements partent du service, jamais d'un écran.
- E4. **Toujours RX au démarrage et à la reconnexion** : après toute reconnexion, l'application est en réception et doit être réarmée par l'opérateur (même règle que la page, sons `lost` / `restored` / `failed`).
- E5. **Fail-safe** : en cas de doute, ne pas émettre. Exemples imposés : perte du focus audio (appel téléphonique entrant) pendant une émission => `stop` ; Bluetooth du micro perdu pendant une émission => `stop` ; application tuée => la station coupe d'elle-même (battements absents), rien à faire de plus.
- E6. Bip à l'activation et à la coupure de l'émission, état « ÉMISSION EN COURS » explicite (écran, voiture, notification).
- E7. **STOP toujours accessible** : bouton STOP sur l'écran principal, dans la notification du service, et action Android Auto.
- E8. Aucun code spécifique à un modèle de poste : l'interface se construit à partir de `hello.capabilities`, `hello.tx_modes`, `hello.spectrum`, etc.
- E9. Opérateur sur place : quand la station refuse le PTT pour émission locale (`local_*`), l'application l'affiche et propose « Reprendre la main » (`local_release`) seulement quand la station l'autorise ; jamais pendant une émission locale.
- E10. Rien n'est stocké en clair : mot de passe protégé par le Keystore Android ; aucun mot de passe dans les journaux ni dans les rapports de problème.

## 3. Interface avec la station (existante, à respecter telle quelle)

- Signalisation : `GET /config` (`protocol`, `ice_servers`, `rig_audio`), `POST /offer {client_id, password, sdp, type}` -> réponse SDP ; `401 unauthorized` (cause jamais précisée), `503 busy`. HTTPS dès qu'on sort de la boucle locale.
- WebRTC : une piste audio Opus 48 kHz mono dans chaque sens ; canal de données `control` (JSON, ordonné) ; canal `spectrum` (binaire, non ordonné, `maxRetransmits 0`) ouvert par le client seulement s'il affiche le spectre HF.
- Messages station -> client : `hello`, `state` (toutes les 250 ms), `result`, `error`, `memories`, `beeps`, `module`.
- Commandes client -> station : liste fermée `COMMANDS` de `trxstation/gateway/api/protocol.py` ; `id` = numéro de requête, `memory_id` = identifiant de mémoire ; message limité à 2 ko (sauf `layout_save` et `bug_report`), 64 ko au plus par message sur le canal (aiortc).
- Audio d'émission : pas d'annulation d'écho ni de contrôle automatique de gain (`autoGainControl: false`, `echoCancellation`/`noiseSuppression` selon le réglage de traitement, comme la page) ; la station garde la porte audio d'émission.

**Manque à combler avant le code Android** : le protocole n'est décrit que dans le code (`protocol.py`, `session.py`, `client.js`). CLAUDE.md exige qu'il soit « figé et documenté côté Pi avant l'étape Android ». Première livraison du chantier : `docs/protocole.md` + jeux d'exemples partagés (voir § 8).

## 4. Architecture de l'application

Dépôt : dossier `android/` dans CE dépôt (voir § 8.1). Kotlin, Gradle (catalogue de versions), Compose + Material 3, Coroutines/Flow, kotlinx.serialization, Hilt, media3-session, stream-webrtc-android.

| Module Gradle | Rôle | Dépend d'Android ? |
|---|---|---|
| `:protocol` | Messages et commandes (kotlinx.serialization), validation, version de protocole, constantes (battement, reconnexion) | Non (Kotlin/JVM pur, testé sans émulateur) |
| `:logic` | Machines d'état pures : connexion/reconnexion, PTT affiché, battements, sons de liaison, saisie de fréquence, bandes | Non |
| `:core` | `RigService` (service au premier plan), WebRTC, audio, `StateFlow<RigState>` unique, stockage chiffré des comptes | Oui |
| `:app` | Écrans Compose du smartphone, mode conduite, réglages | Oui |
| `:auto` | `MediaBrowserService` / `MediaSession` Android Auto | Oui |

Règles :
- **Un seul propriétaire de la connexion** : `RigService`. Écran et voiture sont deux vues abonnées au même `StateFlow` ; aucune vue n'envoie de battement ni ne garde d'état propre.
- Service au premier plan de type `microphone|mediaPlayback` (`connectedDevice` si bouton Bluetooth). **Piège Android 14+** : un service au premier plan « micro » ne peut pas démarrer depuis l'arrière-plan. Le service (et la capture micro, porte fermée côté station) démarre à la connexion, application visible ; un PTT venu de la voiture ou du volant ne fait ensuite qu'envoyer `toggle`.
- Certificat TLS : **épinglé par empreinte SHA-256** saisie ou lue en QR code à l'appairage. Jamais de « faire confiance à tous les certificats ». Un changement d'empreinte bloque la connexion avec un message clair.
- Plusieurs stations possibles (liste de comptes : adresse, identifiant, empreinte).
- `minSdk` proposé : 29 (Android 10) ; `targetSdk` : la dernière version stable. À confirmer selon le téléphone de l'utilisateur (§ 10).

## 5. Fonctions, par lot

Le plan d'origine garde ses numéros (9, 10, 11). La parité complète avec la page n'est PAS un objectif du premier jet.

### Lot A0 — préalables (station, sans Kotlin)
- `docs/protocole.md` : chaque commande, chaque message, chaque code d'erreur, avec exemples.
- `tests/protocol/` : exemples JSON partagés et tests pytest qui prouvent que la station les accepte / les produit (§ 8.3).
- Empreinte du certificat affichée par `trx-setup` et TRX Console (et QR code d'appairage : adresse + identifiant + empreinte, JAMAIS le mot de passe).
- Faut-il un champ `hello.features` (liste de fonctions offertes) ? Recommandé (§ 8.2).

### Lot A1 (étape Android 9) — socle : connexion, écoute, émission
- Appairage d'une station, connexion, reconnexion automatique (mêmes délais que la page : premier essai 400 ms, puis 1,5 / 3 / 4,5 s, fenêtre réglable, 300 s au plus).
- Écoute en continu écran éteint ; volume, sourdine.
- PTT toggle, STOP, compte à rebours du TOT et avertissement, motif de la dernière coupure (`last_cut_reason`), défaut (`fault`).
- Notification permanente : station, fréquence, mode, état RX/TX, bouton STOP.
- Sons de liaison (`lost`, `restored`, `failed`) et vibration.
- Gestion du focus audio et des appels (E5).

### Lot A2 (étape Android 10) — Android Auto
- Lecteur du flux RX, Mute/Volume, présélections = mémoires de la station (actions personnalisées), PTT toggle en action personnalisée avec état explicite, STOP.
- Fréquence, mode, mémoire et S-mètre en texte dans titre/sous-titre ; aucun graphique, aucune saisie.
- Commande vocale (`onPlayFromSearch` : « mémoire 40 mètres », « fréquence 7 074 »), touches du volant (`onMediaButtonEvent`).
- Essais sur le Desktop Head Unit (DHU) puis dans la voiture.

### Lot A3 (étape Android 11) — interface smartphone complète
- S-mètre, fréquence (glisser par chiffre, clavier, bandes), modes et filtres permis par les capacités, mémoires (créer, rappeler, favoris), fonctions du poste (NR NB P.AMP IP+ AGC COMP FIL TUNER, ATT, Notch selon capacités), puissance, squelch.
- Mode conduite : interface réduite, PTT tactile désactivé en roulant (vitesse ou connexion voiture), seulement voix, voiture, volant ou bouton Bluetooth.
- Bips de fin (`beeps_set`), « Reprendre la main », rapport de problème (`bug_report`).

### Lot A4 — plus tard, si utile
Waterfall audio, spectre HF (canal `spectrum`), spots du cluster DX (`module`), mises en page du designer (`layout_get`), thèmes. À décider fonction par fonction dans la matrice de parité.

## 6. Essais

### 6.1 Principes
- Les tests n'utilisent jamais un vrai poste : station en essai avec le **modèle factice Hamlib (1)** ou `fake_rigctld`, sauf validation finale explicite sur charge fictive.
- **Ce qui fait foi pour la sécurité, c'est la station** : un essai de panne est réussi quand la station est revenue en RX dans le délai (état publié, journal), pas quand l'application l'affiche.

### 6.2 Niveaux d'essai

| Niveau | Outil | Contenu | Où |
|---|---|---|---|
| Unitaire | JUnit + kotlinx-coroutines-test (temps virtuel) | `:protocol` et `:logic` : décodage de tous les exemples partagés, cadence des battements, reconnexion, PTT affiché, saisie de fréquence (mêmes cas que `client.js`) | PC, CI |
| Contrat | Exemples JSON de `tests/protocol/` | Les MÊMES fichiers lus par pytest, Node et JUnit (§ 8.3) | PC, CI |
| Intégration | Émulateur Android + station d'essai sur le PC (passerelle, `fake_rigctld`, superviseur en mode géré) | Connexion, mauvais mot de passe, mauvaise empreinte, `busy`, audio, toutes les commandes | PC |
| Panne | Émulateur puis téléphone, `adb` | Liste § 6.3 | PC + téléphone |
| Android Auto | DHU (Desktop Head Unit) puis voiture à l'arrêt | Lot A2 + pannes voiture | PC, voiture |
| Réel | Téléphone, IC-7300MK2 sur charge fictive, Wi-Fi puis 4G/5G | Recette (§ 7) | Station |

### 6.3 Scénarios de panne obligatoires (chacun : station en RX en ≤ 2 s ou au TOT, constaté côté station)
1. Application tuée pendant l'émission (`adb shell am force-stop`, puis `kill -9` du processus).
2. Application gelée (débogueur en pause, `kill -STOP`) pendant l'émission.
3. Réseau coupé pendant l'émission (mode avion), puis rétabli : application en RX, réarmement exigé.
4. Changement de réseau Wi-Fi -> 4G pendant l'émission.
5. Écran éteint, puis Doze forcé (`adb shell dumpsys deviceidle force-idle`) pendant l'écoute puis pendant l'émission.
6. TOT atteint : avertissement affiché et sonore 10 s avant, coupure, motif affiché.
7. Appel entrant pendant l'émission : `stop` envoyé (E5).
8. Téléphone débranché de la voiture / Bluetooth perdu pendant l'émission.
9. Station redémarrée (passerelle relancée par le superviseur) : reconnexion, RX.
10. Deux clients (page + application) : verrou mono-client, le second voit l'émission sans pouvoir la prendre ; STOP de l'un coupe l'émission de l'autre.
11. Opérateur sur place (émission locale) : PTT refusé, « Reprendre la main » invisible pendant l'émission locale.
12. Mise à jour Android de l'application pendant une connexion (processus remplacé) : la station coupe.

### 6.4 Intégration continue
GitHub Actions : construction et tests JVM (`:protocol`, `:logic`) à chaque envoi touchant `android/` ou `tests/protocol/` ; tests pytest de contrat à chaque envoi touchant la station. Essais sur émulateur : à la main au début, automatisés plus tard si utile.

## 7. Critères de recette (par lot)

- Tous les tests unitaires, de contrat et pytest passent.
- Les 12 scénarios de panne du § 6.3 qui concernent le lot sont passés et notés dans `docs/historique.md` (date, téléphone, version Android, réseau).
- Lot A1 : 30 minutes d'écoute écran éteint sans coupure en Wi-Fi et en 4G ; 10 émissions sur charge fictive sans état affiché faux.
- Lot A2 : utilisation complète au DHU, puis dans la voiture À L'ARRÊT ; aucun écran ne demande de saisie.
- APK signé avec une clé de l'utilisateur, conservée hors du dépôt (jamais dans git).

## 8. Faire évoluer ensemble la page web et l'application

### 8.1 Un seul dépôt
L'application vit dans `android/` de ce dépôt. Un changement de protocole touche alors station, page, application et exemples dans **une seule livraison**, avec un seul numéro d'étape. Un second dépôt obligerait à synchroniser deux historiques et deux versions de protocole à la main : c'est la principale source de divergence, on l'évite.

### 8.2 Le protocole est le contrat ; la station en est la seule source
- Les deux clients restent **minces** : toute règle de sécurité ou de validation est dans la station, pas dans un client. Une règle qui n'existe que dans un client est un défaut.
- `PROTOCOL_VERSION` (aujourd'hui 1) suit des règles simples :
  - **ajout** (nouvelle commande, nouveau champ, nouveau type de message, nouveau code d'erreur) : la version ne change pas ; tout client **ignore** ce qu'il ne connaît pas (`ignoreUnknownKeys` côté Kotlin) ;
  - **retrait ou changement de sens** : version + 1 ; la station accepte l'ancienne version pendant au moins une version de l'application ; un client trop ancien affiche « mettre à jour l'application » et **reste en réception** ;
- Recommandé : `hello.features` (liste de mots : `memories`, `spectrum`, `beeps`, `local_release`…). Un client affiche une fonction parce que la station l'annonce, pas parce qu'il compare des numéros de version. Une station plus ancienne que l'application fonctionne alors sans rien casser.

### 8.3 Exemples partagés (tests de contrat)
- `tests/protocol/commands/*.json` et `tests/protocol/messages/*.json` : un exemple valide (et des exemples invalides) par commande et par message.
- pytest : chaque commande de `COMMANDS` a un exemple ; chaque exemple valide passe `parse_command`, chaque invalide est refusé ; un `hello` et un `state` produits par la station respectent les exemples.
- Node (`tests/js/`) et JUnit (`android/`) lisent les mêmes fichiers.
- Même principe pour la logique pure dupliquée (saisie de fréquence, bandes, formats) : cas partagés en JSON, comme `tests/js/layout_cases.json` le fait déjà pour Python et JavaScript.
- Un test échoue si une commande est ajoutée sans exemple (sur le modèle de `test_profile_format_matches_the_current_configuration_fields`).

On **ne partage pas de code** entre la page (JavaScript) et l'application (Kotlin) : Kotlin Multiplatform vers JavaScript alourdirait la page pour peu de gain. On partage le contrat, les exemples et les cas d'essai.

### 8.4 Matrice de parité
`docs/parite-web-android.md` : une ligne par fonction, colonnes « station », « page », « application », « remarque » (fait / à faire / volontairement absent). Toute livraison qui ajoute ou modifie une fonction visible met la ligne à jour. Les absences volontaires sont écrites (ex. : designer de mise en page absent de l'application ; Android Auto absent de la page).

### 8.5 Ordre de travail pour une nouvelle fonction
1. Station : commande ou champ, validation, tests (dont pannes si l'émission est concernée), `docs/protocole.md`, exemples partagés.
2. Page web : plus rapide à faire et à essayer, elle sert de banc d'essai.
3. Application : quand la fonction est stable, en reprenant les mêmes exemples et cas d'essai.
Exception : ce qui n'a de sens que sur le téléphone (Android Auto, boutons matériels, mode conduite) se fait directement dans l'application.

### 8.6 Versions
- La station garde sa version (`pyproject.toml`, 0.x.y). L'application a sa propre version (`versionName` 0.1.0, 0.2.0…) et déclare le protocole minimal qu'elle exige.
- `hello.version` permet à l'application d'afficher la version de la station ; une entrée de `docs/historique.md` cite les deux versions quand elle touche les deux.
- Règles à ajouter à CLAUDE.md quand le chantier démarre : arborescence `android/`, mise à jour de `docs/protocole.md`, des exemples partagés et de la matrice de parité à chaque changement de protocole.

## 9. Sécurité et cadre légal (rappels)
- Pas d'émission depuis un écran tactile en roulant (mode conduite) ; vérifier le cadre réglementaire de la licence pour l'émission à distance et en mobile.
- Diffusion : APK installé à la main et mode développeur d'Android Auto (refus probable du Play Store en catégorie voiture). Une application installée à la main pilotant un émetteur : la clé de signature et le certificat épinglé sont les deux garanties d'origine, ne pas les négliger.
- Les rapports de problème de l'application suivent les mêmes règles que ceux de la page (texte relu par l'utilisateur, aucun mot de passe).

## 10. Questions ouvertes (à trancher avant le lot A1)
1. Android Studio est-il installé sur le PC Windows ? Le code Kotlin est-il écrit ici avec Claude Code (recommandé : même dépôt, mêmes conversations) ?
2. Téléphone(s) d'essai et version d'Android ; voiture compatible Android Auto, filaire ou sans fil ?
3. `minSdk` 29 convient-il ?
4. Nom du paquet (proposition : `com.rfdiy.trxremote`) et nom affiché de l'application.
5. Ajout de `hello.features` côté station : d'accord ?
6. Bouton Bluetooth HID prévu (lequel) ?
