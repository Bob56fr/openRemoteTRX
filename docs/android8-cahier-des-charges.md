# Cahier des charges — openRemoteTRX Lite (application Android 8 et 9)

État : **projet monté** (étape 365, 2026-11-22), fonctions à retirer au lot 1. v1 (étape 364) : même APK avec
`minSdk` 26 ; **v2** : projet séparé (décisions de l'utilisateur du 2026-11-22). Complète
[`android-cahier-des-charges.md`](android-cahier-des-charges.md) : sécurité, protocole et essais de panne
s'appliquent sans exception.

## 1. Objet

Proposer une application aux téléphones sous **Android 8.0, 8.1 et 9** (API 26 à 28), que l'application principale
(Android 10 minimum) écarte : vieux téléphone gardé au shack, prêté à un visiteur, téléphone modeste.

## 2. Décisions de l'utilisateur (2026-11-22)

1. **Projet indépendant** : « openRemoteTRX Lite », dépôt PUBLIC `Bob56fr/openRemoteTRX-lite`
   (`C:\dev\openRemoteTRX-lite`), licence AGPL-3.0-or-later, sa propre numérotation (0.1.0), son CLAUDE.md, son
   journal, sa fiche dans le tableau de pilotage.
2. **Code partagé pour ce qui ne dépend pas d'Android** : `:protocol` et `:logic` (Kotlin/JVM : protocole, RigSession,
   battements, refus, textes et catalogues de langue) viennent du dépôt principal par le **sous-module Git
   `upstream/`**, figé sur un commit. Jamais copiés : une correction de sécurité arrive d'un seul geste (mise à jour du
   sous-module). `:core` et `:app` sont **propres à Lite** (copie de départ : application 0.90.0, historique Git gardé
   par `git subtree split`).
3. **Identifiant** `com.rfdiy.openremotetrx.lite` (jamais changé ensuite) : les deux applications cohabitent sur un
   téléphone ; sur Google Play, seconde fiche.
4. **Toute fonction non supportée par Android 8 / 9 est SUPPRIMÉE** du code de Lite (pas masquée, pas simulée).
5. **Plancher Android 8.0** (API 26) : canaux de notification et service au premier plan tels qu'utilisés.

## 3. Règles communes aux deux dépôts

- **Station et protocole** : Lite est un client comme un autre. La station ne casse JAMAIS un client qui ne connaît
  pas une fonction récente (fonctions facultatives annoncées par `hello.features`, commandes inconnues ignorées par le
  client). Les exemples `tests/protocol/` restent le contrat, rejoués par les tests de `:protocol` dans Lite.
- **`:protocol` et `:logic`** : aucun appel Android (modules JVM) ; leurs chemins Gradle sont relatifs au MODULE
  (`project.file("../..")`), jamais au projet racine, pour rester compilables depuis le sous-module de Lite.
- **Textes** : les textes de `:core` et `:app` de Lite utilisent les clés du catalogue commun
  (`android/logic/src/main/resources/i18n/app.<langue>.json`, 4 langues) ; un texte propre à Lite s'y ajoute (dans le
  dépôt principal, 4 langues), jamais en dur.
- **Sécurité d'émission inchangée** (portée par la station) ; PTT en toggle, STOP toujours visible ; Lite garde les
  tests de panne de `:logic` et ajoute les siens pour `:core`.

## 4. Fonctions supprimées dans Lite (relevé du lot 0 : lint `NewApi` avec `minSdk` 26)

| Fonction | Cause | Lot 1 |
|---|---|---|
| **Android Auto** (`RigAutoService`, `automotive_app_desc`, mode conduite automatique à la connexion de la voiture) | Google exige Android 11 pour Android Auto depuis 2026 (Android 9 en 2025) | supprimé ; la session média reste (touches du casque et du volant Bluetooth) |
| Détail radio du téléphone (4G / 5G, dBm, cellule) dans la qualité du réseau | API 28 à 30 (`getSignalStrength`, `CellInfoNr`…) | supprimé (`NetRadio`), option « antenne-relais » des Réglages retirée ; la sonde réseau reste |
| Image de la mesure de TOS enregistrée dans Images/OpenRemoteTRX | API 29 (`MediaStore … RELATIVE_PATH`) | bouton « Enregistrer » retiré, partage gardé |
| Export SELCALL dans Téléchargements | API 29 (`MediaStore.Downloads`) | bouton retiré |
| Application appelante d'une commande média (`currentControllerInfo`) | API 28 | supprimé (servait à reconnaître Android Auto) |

Gardé avec une méthode plus ancienne (fonction supportée, seule l'API change) : QR code d'appairage lu dans une image
(`ImageDecoder`, API 28 -> `BitmapFactory`). Déjà prévu dans le code : micro du casque Bluetooth (SCO avant
Android 12), langue de l'application dans ses propres Réglages (pas celle d'Android 13).

Erreurs du lint sans rapport avec la version (aussi présentes dans l'application principale) : `ContextCastToActivity`
(FriendsViews.kt), `StateFlowValueCalledInComposition` (VoiceScreen.kt), `MissingPermission` (NetRadio.kt, supprimé).

## 5. Performances

Sur un téléphone d'Android 8 / 9 : spectre HF, waterfall, égaliseur et effets **éteints par défaut** (rallumables) ;
le son et le PTT passent avant tout.

## 6. Lots

- **Lot 0 — FAIT (étape 365)** : dépôt monté, sous-module, `minSdk 26`, compilation de l'APK, relevé du § 4.
- **Lot 1** : suppressions du § 4, défauts du § 5, lint sans erreur `NewApi`, tests verts (`gradlew test`).
- **Lot 2** : émulateurs Android 8.1 et 9 (connexion à la station factice, écoute, émission, STOP, battement perdu,
  connexion coupée, application tuée pendant l'émission), puis un vrai téléphone Android 8 ou 9 (charge fictive,
  10 émissions, 30 min d'écoute écran éteint, casque Bluetooth).
- **Lot 3** : publication (APK sur les Releases de Lite, puis Google Play, seconde fiche) et guide de l'opérateur.

## 7. Questions encore ouvertes

1. Avertissement à la première connexion : « téléphone sans mises à jour de sécurité, le mot de passe de l'opérateur
   y est enregistré » (proposé) ?
2. Téléphone réel pour le lot 2 ?

## 8. Risques

- Téléphones sans correctifs de sécurité depuis environ 2021 : un compte opérateur par appareil (règle existante)
  permet de révoquer celui-là seul (menu 4.3).
- Une bibliothèque (stream-webrtc, Compose, media3, ZXing) peut relever son minimum : Lite fige alors sa version.
- Remarque pour l'application principale : avec Android 11 exigé par Google, Android Auto ne marche plus sur les
  téléphones Android 10 qu'elle accepte encore.
