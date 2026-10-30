# Application Android sur Google Play (test interne)

Étape 89. Diffusion aux bêta-testeurs par le canal **Test interne** de la Play Console (100 testeurs au plus, pas de
revue complète, disponible en quelques minutes). La production demandera plus tard un test fermé (12 testeurs,
14 jours) avec un compte personnel récent.

## Deux constructions

| Type | Commande (dans `android/`) | Fichier | Usage |
|---|---|---|---|
| `debug` | `gradlew.bat assembleDebug` | `app/build/outputs/apk/debug/app-debug.apk` | essais par `adb install` (inchangé) |
| `release` | `gradlew.bat assembleRelease` | `app/build/outputs/apk/release/app-release.apk` | diffusion hors Play Store (APK signé par la clé d'envoi si elle existe) |
| `play` | `gradlew.bat bundlePlay` | `app/build/outputs/bundle/play/app-play.aab` | **envoi à la Play Console** |

`play` = `release` **sans le scrambler** (`BuildConfig.SCRAMBLER = false` : la rubrique de l'onglet « Égaliseur »
n'existe pas, rien ne peut l'activer). Raison : codage interdit en bandes radioamateur (UIT RR art. 25,
`docs/scrambler.md`) ; l'éditeur nommé sur le Store ne le propose pas. Android Auto reste présent (essai par les
testeurs sans « Sources inconnues ») ; si la revue de Google le refuse, le retirer du type `play` par un manifeste
`app/src/play/AndroidManifest.xml` (`tools:node="remove"` sur `RigAutoService` et la méta-donnée `gms.car`).

`bundlePlay` refuse de construire sans clé d'envoi (« Clé d'envoi absente »).

## Clé d'envoi (une seule fois, HORS DU DÉPÔT)

1. Dans PowerShell (le dossier peut être ailleurs, mais **jamais** dans le dépôt, qui est public) :
   ```
   mkdir $env:USERPROFILE\cles-android
   & "C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe" -genkeypair -v -keystore $env:USERPROFILE\cles-android\upload.jks -alias upload -keyalg RSA -keysize 4096 -validity 10000
   ```
   keytool demande un mot de passe et un nom : mettre « RF-DIY » (le nom n'est pas affiché sur le Store, mais il est
   lisible dans le certificat de la clé d'envoi).
2. Créer `android/keystore.properties` (ignoré par Git) :
   ```
   storeFile=C:/Users/<vous>/cles-android/upload.jks
   storePassword=...
   keyAlias=upload
   keyPassword=...
   ```
   `storeFile` absolu, ou relatif au dossier de ce fichier. Autre emplacement : `gradlew.bat bundlePlay -PkeystoreProperties=chemin`.
3. Sauvegarder `upload.jks` et les mots de passe hors du PC (gestionnaire de mots de passe). Avec **Play App Signing**
   (proposé par défaut, à accepter), Google garde la clé finale : une clé d'envoi perdue se remplace par le support.

## Chaque envoi

1. Monter `versionCode` (toujours +1, Google refuse un numéro déjà envoyé) et `versionName` dans
   `android/app/build.gradle.kts`.
2. `cd android ; gradlew.bat test bundlePlay`
3. Play Console > l'application > Tester et publier > Tests > **Test interne** > Créer une version > déposer
   `app-play.aab` ; notes de version (ci-dessous) ; Enregistrer > Vérifier > Déployer.
4. Onglet **Testeurs** : cocher la liste de testeurs ; copier le **lien d'inscription** et l'envoyer. Chaque testeur
   ouvre le lien avec le compte Google de la liste, accepte, puis installe depuis le Play Store.

Installation qui échoue ou application qui se ferme : la Play Console ne donne AUCUN journal par utilisateur ; le
testeur suit `https://bob56fr.github.io/openRemoteTRX/android/journaux.html` (`docs/site/android/journaux.html`,
iframe WordPress `docs/wordpress/android-journaux-iframe.html`) et renvoie le journal par e-mail (jamais en public).

Un testeur qui a déjà la version `debug` (même identifiant, autre signature) doit la **désinstaller** d'abord.
Décision de l'utilisateur (2026-10-30) : le Samsung S25 GARDE la version `debug` (développement par `adb`) ; la
version du Play Store s'essaie sur un AUTRE téléphone.

## Fiche et déclarations (Play Console, une seule fois)

- **Créer l'application** : nom « openRemoteTRX », langue par défaut français, Application, Gratuite.
- **Statut de commerçant (UE)** : non-commerçant (application gratuite, sans revenus).
- **Coordonnées** : adresse e-mail dédiée (publique), pas d'adresse ni de téléphone.
- **Règles de confidentialité** : `https://bob56fr.github.io/openRemoteTRX/android/confidentialite.html`
  (`docs/site/android/confidentialite.html`, publiée par GitHub Pages au push).
- **Accès à l'application** : « Tout ou partie de l'application est soumise à des restrictions » ; instructions :
  « L'application pilote la station radioamateur de l'utilisateur (logiciel libre openRemoteTRX installé sur son PC).
  Sans station, seul l'écran de connexion est visible. Sources : https://github.com/Bob56fr/openRemoteTRX. »
  (Une station de démonstration en réception seule, compte visiteur, peut être ajoutée plus tard.)
- **Annonces** : non. **Classification du contenu** : questionnaire, catégorie « Utilitaire / productivité », réponses
  « non » partout (pas de contenu entre utilisateurs publié : la voix va à la station de l'utilisateur).
- **Public cible** : 18 ans et plus.
- **Sécurité des données** : aucune donnée collectée ni partagée au sens de Google (tout reste sur le téléphone ou va à
  la station de l'utilisateur, que l'éditeur ne voit pas) ; données chiffrées en transit : oui ; suppression : en
  désinstallant.
- **Services de premier plan** (Règles > Contenu de l'application > Autorisations des services de premier plan) :
  - `microphone` : « Émission radioamateur à distance : la voix de l'utilisateur est envoyée à sa station pendant une
    émission qu'il a demandée, écran éteint ou application en arrière-plan (casque, Android Auto). »
  - `mediaPlayback` : « Écoute en continu du récepteur de la station de l'utilisateur, écran éteint ou dans la
    voiture. »
  - Vidéo demandée : écran de connexion, écoute écran éteint (notification), émission par le bouton PTT.
- **Catégorie** : Outils (ou Communication). **Tags** : radioamateur.
- **Images** : `docs/play-store/icone-512.png`, `docs/play-store/banniere-1024x500.png` ; captures du téléphone
  (au moins 2, format portrait), prises sur le S25 : onglet Station, Spectre, Mémoires.

### Textes de la fiche

Description courte (80 caractères au plus) :

> Écoutez et pilotez votre station radioamateur à distance (station openRemoteTRX).

Description complète :

> openRemoteTRX pilote VOTRE station radioamateur depuis le téléphone : écoute du récepteur, émission en
> alternat, fréquence, mode, filtres, S-mètre, spectre HF, mémoires, Cluster DX.
>
> Il faut une station openRemoteTRX : le logiciel libre (AGPL-3.0) installé sur le PC relié au poste (Windows,
> Debian ; tout poste reconnu par Hamlib). https://github.com/Bob56fr/openRemoteTRX
>
> Sécurité d'émission assurée par la station : PTT en alternat seulement, coupure au bout du temps maximal
> (TOT), retour en réception si le téléphone ne répond plus, une seule personne émet à la fois.
>
> Mode conduite et Android Auto : écoute, mémoires, commande vocale ; l'émission en roulant obéit aux règles de
> votre pays.
>
> Réservé aux radioamateurs titulaires d'une licence : vous êtes responsable de vos émissions.
>
> Aucune publicité, aucun compte, aucun traceur : l'application ne parle qu'à votre station.

Notes de version (exemple) : « Première version de test. Merci de signaler tout problème. »

## À savoir

- `targetSdk 36` : conforme aux exigences de Google pour 2026.
- Pas de minification (`isMinifyEnabled = false`) : la Console avertit (« fichier de désobscurcissement »), sans effet.
- AGPL : le lien vers les sources est dans la description.
- Le scrambler reste dans `debug` et `release` (diffusion hors Play Store), voir `docs/scrambler.md`.
