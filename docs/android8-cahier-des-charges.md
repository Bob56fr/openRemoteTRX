# Cahier des charges — Application openRemoteTRX sur Android 8 et 9

État : **à décider**, rien n'est codé. Rédigé le 2026-11-22 (étape 364). Complète
[`android-cahier-des-charges.md`](android-cahier-des-charges.md) : sécurité, protocole, essais de panne et parité
s'appliquent sans exception.

## 1. Objet

Proposer l'application aux téléphones sous **Android 8.0, 8.1 et 9** (API 26 à 28), aujourd'hui écartés
(`minSdk = 29`, Android 10). But : ne pas écarter les téléphones anciens ou modestes (objectif d'origine du cahier
Android), par exemple un vieux téléphone gardé au shack ou prêté à un visiteur.

## 2. Principes (décisions proposées)

1. **Une seule application, un seul APK** (`com.rfdiy.openremotetrx`) : `minSdk` passe de 29 à **26**. Pas de
   version « dégradée » à part (double entretien, double publication).
2. **Les fonctions absentes d'Android 8 / 9 sont masquées**, jamais simulées. Ce qui reste marche comme sur Android 10+.
3. **Sécurité d'émission inchangée** : elle est portée par la station (état RX/TX, TOT, battements, retour en
   réception, superviseur). Le PTT reste en toggle, le STOP toujours visible.
4. **Aucun changement de la station ni du protocole.** La station accepte déjà TLS 1.2 (`tls.py`), que donne Android 8 ;
   l'application vérifie le certificat par son empreinte (appairage), sans dépendre des autorités du téléphone.
5. **Pas en dessous d'Android 8** : les canaux de notification et le service au premier plan, tels qu'utilisés,
   commencent là.

## 3. Ce qui change sur Android 8 / 9 (relevé à compléter au lot 0)

| Fonction | Exige | Sur Android 8 / 9 |
|---|---|---|
| Radio du téléphone dans la qualité du réseau (4G / 5G, dBm, cellule) | API 29 (`getCellSignalStrengths`, `CellInfoNr`) | masquée : « détail radio indisponible sur cette version d'Android » ; la sonde réseau elle-même reste |
| Image de la mesure de TOS enregistrée dans Images/OpenRemoteTRX | API 29 (`MediaStore … RELATIVE_PATH`) | partage seulement (Android le propose déjà), ou enregistrement avec l'ancienne autorisation de stockage limitée à Android 9 (à décider, § 6) |
| Export SELCALL dans Téléchargements | API 29 (`MediaStore.Downloads`) | même choix que l'image de TOS |
| Micro du casque Bluetooth | API 31 pour la méthode récente | ancienne méthode SCO, déjà codée (repli existant) |
| Android Auto | application Android Auto de Google | **à vérifier** : Google peut avoir abandonné Android 8 ; sinon pas de voiture sur ces téléphones (mode conduite à l'écran gardé) |
| Langue par application (Réglages d'Android) | API 33 | déjà absente avant Android 13 : Réglages > Langue de l'application suffit |
| Autres appels propres à Android 9 / 10 | inconnus | liste exacte donnée par la vérification d'Android (lint `NewApi`) au lot 0 |

## 4. Performances

Un téléphone de 2017-2018 peut peiner avec WebRTC + Compose + spectre HF + waterfall. Proposé : sur Android 8 / 9
(ou sur tout appareil déclaré « faible » par Android, `isLowRamDevice`), spectre HF et waterfall **éteints par défaut**
(rallumables), égaliseur et effets de voix éteints par défaut. Le son et le PTT passent avant tout.

## 5. Lots

- **Lot 0 — relevé (sans livraison)** : `minSdk = 26` sur une copie de travail, `gradlew lint` (liste exacte des appels
  à adapter), application dans un émulateur Android 8.1 : connexion à la station factice, écoute, émission, STOP,
  coupure de liaison. Résultat : liste chiffrée des adaptations, décision de faire ou non.
- **Lot 1 — adaptations** : tests de version et masquages du § 3, réglages par défaut du § 4, test cliquet (toute
  fonction masquée a son test de version), `gradlew test` vert.
- **Lot 2 — essais** : émulateur Android 8.1 et 9 ajoutés aux essais Android (tests de panne compris : battement
  perdu, connexion coupée, application tuée pendant l'émission), puis **un vrai téléphone Android 8 ou 9** (charge
  fictive, 10 émissions, 30 min d'écoute écran éteint, casque Bluetooth).
- **Lot 3 — publication** : version Google Play (le `minSdk` ne change rien au `targetSdk` exigé par Google), fiche
  mise à jour (« Android 8 ou plus récent »), guide de l'opérateur, `docs/parite-web-android.md`.

## 6. Décisions à prendre par l'utilisateur

1. Plancher : **Android 8.0** (API 26, proposé) ou Android 9 (API 28, moins de cas, moins de téléphones gagnés) ?
2. Image de TOS et export SELCALL sur Android 8 / 9 : partage seulement (proposé, aucune autorisation de plus) ou
   enregistrement avec l'autorisation de stockage ?
3. Avertissement à la première connexion sur Android 8 / 9 : « téléphone sans mises à jour de sécurité, le mot de
   passe de l'opérateur y est enregistré » (proposé) ?
4. Téléphone réel pour le lot 2 : lequel (bêta-testeur, téléphone de l'utilisateur) ?

## 7. Risques

- Téléphones sans correctifs de sécurité depuis environ 2021 : le mot de passe du compte opérateur y est stocké ; un
  compte par appareil (règle existante) permet de le révoquer seul depuis la station (menu 4.3).
- Bibliothèques : stream-webrtc, Compose, media3 et ZXing acceptent aujourd'hui Android 8 ; une future version peut
  relever son minimum et bloquer une mise à jour : à surveiller à chaque montée de version.
- Chaque version d'Android en plus = un émulateur de plus dans chaque série d'essais.
