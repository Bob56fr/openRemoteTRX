# Égaliseur paramétrique et effets de voix (tâche future)

État : **application faite (0.22.0, étape 80)** : onglet « Égaliseur » et bouton EQ (appui long = onglet), calcul `logic/VoiceEq.kt` + `logic/VoiceDsp.kt` (réverbération algorithmique de type Freeverb), branché dans WebRTC par `ExternalAudioProcessingFactory` (après l'annulation d'écho, avant Opus ; relevé sur le S25 : 48 kHz, blocs de 480, échantillons « FloatS16 » ±32 768), réglages et préréglages identiques à la page (`tests/protocol/voice_presets.json`). WebRTC n'ouvre le micro QU'EN ÉMISSION : enregistrement et relecture par le micro du téléphone directement (réception seulement, toute prise les arrête) ; écoute de contrôle en direct non faite dans l'application. **Page web faite (station 0.57.0, étape 69)** : `voice.js`, tests `tests/js/voice_test.js`, vecteurs partagés `tests/protocol/voice_vectors.json` ; application : à faire (lot A3, calcul dans `:logic` avec les mêmes vecteurs). Choix faits à la réalisation : compresseur non fait (facultatif) ; dosage des effets jusqu'à 100 % avec avertissement ; réverbération par réponses impulsionnelles GÉNÉRÉES (rien à télécharger) ; limiteur = compresseur 20:1 à -6 dBFS puis écrêtage doux à -3 dBFS ; enregistrement de 30 s au plus. Décisions de l'utilisateur du 2026-10-28. Concerne la **page web ET l'application Android**.

## 1. Objet

Personnaliser la voix de l'opérateur avant son envoi à la station (puis au poste) : égaliseur 10 bandes, chorus, réverbération. Le traitement se fait **dans le client** (page ou application), juste avant l'encodage Opus. La station n'en sait rien : pas de changement de protocole, pas de réglage dans `station.toml`.

Pourquoi c'est utile : la station fait moduler le poste par l'USB en **mode DATA** (USB-D, LSB-D, AM-D, FM-D ; `tx_modes` de l'IC-7300MK2). Dans ces modes, le poste ne touche pas à l'audio et son égaliseur d'émission est inactif. L'égaliseur du client est donc le seul réglage de timbre possible à distance.

## 2. Chaîne de traitement (ordre imposé)

micro → suppression de bruit et annulation d'écho du navigateur ou de WebRTC (contrôle automatique de gain **désactivé**, comme aujourd'hui dans `client.js`) → filtres coupe-bas et coupe-haut → égaliseur 10 bandes → compresseur (proposé, facultatif) → chorus → réverbération → **limiteur (toujours actif, même effets éteints)** → piste envoyée à la station.

- Le limiteur évite qu'un relevé de l'égaliseur ou des effets fasse monter l'ALC et déborder l'émission. Le plafond de crête est à fixer (environ -3 dBFS), à vérifier à l'ALC sur charge fictive.
- **Bypass** (bouton éteint) : seul le limiteur reste actif ; le reste de la chaîne laisse passer le son tel quel.
- Une erreur ou un manque de calcul dans la chaîne fait passer en bypass, jamais en silence ni en son abîmé. L'erreur est signalée dans le journal.

## 3. Égaliseur

- **10 bandes entre 100 et 5 000 Hz** (certains postes émettent jusqu'à 5 kHz). Fréquences par défaut, réparties en logarithmique : 100, 160, 250, 370, 570, 880, 1 350, 2 100, 3 250, 5 000 Hz.
- « Paramétrique » : chaque bande a un gain (±12 dB), une fréquence (réglable autour de sa valeur par défaut) et une largeur Q. Les bandes 1 et 10 peuvent devenir des filtres en plateau.
- Filtres coupe-bas et coupe-haut réglables, pour adapter la bande passante à celle du poste.
- Calcul : filtres biquad standard (formules du « Audio EQ Cookbook »). Page : `BiquadFilterNode` de WebAudio. Application : même calcul en Kotlin pur, dans `:logic`. Des **vecteurs d'essai partagés** (coefficients attendus pour quelques réglages, en JSON) prouvent que la page et l'application calculent la même chose.

## 4. Chorus et réverbération

- **Chorus** : plusieurs types (par exemple classique, ensemble à 3 voix, doublage), avec un dosage (% d'injection), une vitesse et une profondeur.
- **Réverbération** : plusieurs types (par exemple pièce, salle, plaque, ressort), avec un dosage (% d'injection) et une durée. Page : `ConvolverNode` avec des réponses générées ou embarquées (attention à la taille). Application : réverbération algorithmique de type Freeverb.
- Effets désactivés par défaut, avec un avertissement : en BLU, ils réduisent la compréhension.
- **Au retour en réception, la traîne de réverbération et le chorus sont coupés net**, comme le micro du client aujourd'hui. Ainsi, rien ne prolonge une émission.
- À décider : plafond du dosage (aucun, ou par exemple 50 %).

## 5. S'écouter sans émettre (les deux solutions)

1. **Écoute de contrôle au casque** : la sortie de la chaîne est renvoyée en direct dans le casque du téléphone ou du PC.
   - Un avertissement demande un casque : sur haut-parleur, le son repart dans le micro (effet Larsen).
   - Un casque Bluetooth ajoute environ 150 à 250 ms de retard : c'est gênant, d'où la seconde solution.
2. **Enregistrement puis relecture** : quelques secondes enregistrées (30 s au plus), puis relues avec les réglages en cours. Les réglages peuvent changer pendant la relecture, la prise reste la même.

Sécurité : l'écoute de contrôle et la relecture ne sont **jamais** envoyées à la station. Elles sont désactivées pendant une émission, et toute émission qui commence les arrête. Des tests le prouvent.

## 6. Interface

- **Page web** : un accordéon « Égaliseur paramétrique », ainsi qu'un **bouton marche/arrêt d'accès direct** visible sans ouvrir l'accordéon (près du PTT ou du réglage micro). Le bouton montre clairement l'état (allumé, éteint).
- **Application** : un onglet « Égaliseur paramétrique » et le même bouton marche/arrêt d'accès direct sur l'écran principal.
- Pas d'écran de réglage en **mode conduite** ni dans Android Auto. On pourra y ajouter plus tard le seul bouton marche/arrêt si c'est jugé utile.
- **Préréglages nommés** (par exemple « DX », « Ragchew », « Neutre ») et réglages enregistrés par client : page en `localStorage`, application en DataStore.
- Export et import dans un **format JSON commun** à la page et à l'application, pour retrouver la même voix sur les deux.

## 7. Essais

- Page : tests Node de la logique (validation des réglages, construction de la chaîne sur un faux `AudioContext`), puis un vrai Chromium (Playwright).
- Application : tests JVM du calcul dans `:logic`, avec les vecteurs partagés.
- Sécurité : la relecture et l'écoute de contrôle ne vont jamais dans la piste d'émission ; elles s'arrêtent au passage en émission ; la traîne s'arrête au retour en réception ; le bypass s'active en cas d'erreur.
- Sur le vrai poste, sur charge fictive : ALC et largeur du signal émis avec l'égaliseur au maximum et les effets à 100 %, en USB-D. À vérifier aussi : le COMP du poste agit-il en mode DATA ?

## 8. Quand l'intégrer

- **Page web** : pas besoin de la station ni de l'application. C'est le « banc d'essai » prévu au § 8.5 du cahier des charges Android. Possible dès que l'étape Android en cours (lot A1) est livrée et commitée, pour ne pas travailler à deux sur le dépôt.
- **Application** : il faut d'abord la piste micro WebRTC de `:core` (lot A1). Les calculs (biquads, vecteurs partagés) peuvent arriver dans `:logic` dès la fin de A1 ; l'écran et le bouton avec le **lot A3** (interface smartphone complète).
- Ligne à tenir à jour dans `docs/parite-web-android.md`.
