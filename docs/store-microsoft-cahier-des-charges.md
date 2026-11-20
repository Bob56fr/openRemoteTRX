# Station « TRX distant » sur le Microsoft Store : cahier des charges

Version 1 (2026-11-20, étape 317). Demande de l'utilisateur : « Déploiement du package d'installation sur le Store
Microsoft ; j'ai un compte particulier ». Produit choisi : la STATION Windows complète (pas l'Autotest). Aucun code
dans cette version : décisions à prendre (§ 9), puis lots (§ 10).

Les points marqués **[à vérifier]** viennent de la documentation de Microsoft telle que connue au moment de
l'écriture ; ils se vérifient par l'essai S0 (§ 10) avant tout code, jamais par supposition.

## 1. Point de départ : le zip Windows actuel

`scripts/build_windows_zip.py` -> `dist/trx-remote-windows-X.Y.Z.zip`, `windows/installer.ps1` :

| Ce que fait l'installation | Comment aujourd'hui |
|---|---|
| Python | celui DÉJÀ installé sur le PC (3.11+), venv créé par l'installation, `pip install --require-hashes -r requirements.lock` |
| Hamlib (rigctld) | installé à part par l'opérateur, cherché par l'installation |
| Décodeurs FreeDV | dossier `freedv/` du zip |
| Programmes | `%LOCALAPPDATA%\Programs\TRX distant\versions\<v>` (versions côte à côte, retour arrière) |
| Configuration | `C:\ProgramData\trx-remote` (droits restreints par icacls : compte, administrateurs, système) |
| Pare-feu | règles par programme (python / pythonw de base) et port 8443, réseaux PRIVÉS seulement |
| Démarrage | tâche planifiée à l'ouverture de session (pythonw, superviseur, relance 3 fois) |
| Menu Démarrer | UN raccourci « TRX distant » (TRX Console), inscription dans Paramètres > Applications |
| Commandes | relais `.cmd` dans `…\TRX distant\bin`, ajoutés au PATH de l'utilisateur |
| Mises à jour | mécanisme SIGNÉ de la station (`trxstation/update/`, menus 7.1 à 7.3, retour arrière 7.2) |

## 2. Ce qu'impose le Store (compte particulier)

- **Compte** : l'inscription d'un développeur particulier est gratuite (depuis 2024) avec vérification d'identité
  **[à vérifier : conditions du moment dans Partner Center]**. Un nom d'application se RÉSERVE (unique dans tout le
  Store) ; le nom d'éditeur affiché est celui du compte.
- **Deux façons de publier une application de bureau** :
  1. **MSIX** : le Store SIGNE lui-même le paquet (aucun certificat à acheter, pas d'avertissement SmartScreen),
     installe sans droits d'administrateur, met à jour, désinstalle proprement. Contraintes : dossier des programmes
     en LECTURE SEULE (`C:\Program Files\WindowsApps`), tout doit être DANS le paquet, mises à jour par le Store
     SEULEMENT (une application ne se met pas à jour elle-même), capacité restreinte `runFullTrust` à justifier.
  2. **EXE / MSI** « hébergé » : le Store ne fait que pointer vers un installateur téléchargé chez l'éditeur, qui
     DOIT être signé par un certificat de signature de code reconnu (payant ; Azure Trusted Signing pour les
     particuliers seulement dans certains pays **[à vérifier pour la France]**). Mises à jour par l'éditeur permises.
     Pas d'avantage pour l'opérateur par rapport au zip actuel, coût annuel, et Python à installer à part refusé à
     la certification (« l'application doit fonctionner sans dépendance à installer à la main »).
- **Fiche** : description, captures, icônes, règles de confidentialité (URL), questionnaire d'âge (IARC), marchés,
  prix (gratuit), conditions de licence (on peut donner la NÔTRE : AGPL-3.0-or-later, § 7).
- **Certification** : relue par Microsoft (quelques jours) ; une application qui écoute sur le réseau et pilote du
  matériel doit l'expliquer dans les « notes pour la certification » (mode d'emploi pour l'essayer sans poste :
  modèle factice Hamlib n° 1).

## 3. Proposition : MSIX, Python embarqué

### 3.1 Contenu du paquet

- **Python embarqué** (distribution « embeddable » officielle de CPython, même version mineure que les essais) avec
  `site-packages` déjà rempli depuis `requirements.lock` À LA FABRICATION (empreintes vérifiées comme aujourd'hui).
  Pas de Nuitka : la station lance ses services et modules par `python -m …` (superviseur -> passerelle, modules,
  outils de TRX Console) ; Nuitka obligerait à tout réécrire en exécutables séparés pour un gain nul.
- **Hamlib** : `rigctld.exe` et ses DLL d'une version FIGÉE (dernière Release publique, empreinte SHA-256 comme
  `compiler-hamlib.sh`), dans le paquet. L'opérateur n'installe plus rien à part. Hamlib est LGPL / GPL : sources
  et offre écrite citées dans la fiche et dans `LICENSE` du paquet.
- **Décodeurs FreeDV** (`freedv/`), comme le zip.
- Code de la station, `LICENSE`, catalogues `i18n`, pages statiques.

### 3.2 Manifeste (`AppxManifest.xml`)

- Application principale « TRX distant » = TRX Console (terminal), entrée du menu Démarrer.
- **Alias d'exécution** (`uap5:AppExecutionAlias`) : `trx-console`, `trx-setup`, `trx-monitor`, `trx-hwtest`,
  `trx-qualif`, `trx-journal-android`… = la liste `$Commands` d'installer.ps1, tapables dans tout terminal (remplace
  les relais `.cmd` et la modification du PATH). Applications secondaires sans entrée de menu
  (`AppListEntry="none"`) **[à vérifier : paramètres passés à python.exe par l'alias]**.
- **Démarrage à l'ouverture de session** : `desktop:StartupTask` qui lance le superviseur (pythonw). L'opérateur
  peut le couper dans Paramètres > Applications > Démarrage : TRX Console doit le DIRE (état du démarrage
  automatique en tête, comme l'état de la station).
- **Pare-feu** : `desktop2:FirewallRules` (règles posées à l'installation, retirées à la désinstallation) pour le
  python.exe / pythonw.exe du paquet, entrées sur réseaux PRIVÉS seulement, comme aujourd'hui **[à vérifier :
  attribut Profile, besoin d'élévation]**. Règle par programme = tout port (8443 ou `gateway_port` changé, 8444 de
  la console réseau, WebRTC).
- `runFullTrust` (ports série, cartes son, sous-processus, réseau).

### 3.3 Données

Configuration, clés, certificats, état, journaux : HORS du paquet, sinon perdus à chaque désinstallation (et la
virtualisation MSIX de `%APPDATA%` les cacherait aux autres outils). Proposition : MÊME dossier que le zip,
`C:\ProgramData\trx-remote`, droits restreints au compte comme aujourd'hui, créé au premier lancement par la station
elle-même (plus par l'installateur) **[à vérifier : écriture dans ProgramData depuis une application MSIX non
virtualisée]**. Repli si l'essai S0 échoue : `LocalState` du paquet, avec un avertissement clair « désinstaller =
configuration effacée, exportez-la d'abord » et un export par TRX Console.

### 3.4 Version Store dans le code

- Détection : `trxstation/packaging.py` (nouveau) lit l'identité du paquet (`GetCurrentPackageFullName` par
  ctypes) : `is_store()`.
- Mises à jour : menus 7.1, 7.2, 7.3 et vérification `trx-update-check` REMPLACÉS par « Mises à jour : par le
  Microsoft Store » (version installée, lien `ms-windows-store://pdp/?productid=…`). Aucun retour arrière (le Store
  n'en propose pas).
- Chemins : Python, rigctld, freedv cherchés DANS le paquet, jamais dans le PATH du système.
- Le paquet zip et la page de la console continuent d'exister ; Debian / Pi inchangés.

## 4. Sécurité d'émission (priorité absolue)

Le Store met à jour, et l'opérateur désinstalle, PENDANT QUE LA STATION TOURNE. Si Windows FERME les processus de
l'application (superviseur, passerelle, rigctld) pendant une émission par la CAT, plus personne n'envoie « T 0 » :
le poste peut RESTER EN ÉMISSION. C'est le même risque qu'un processus tué à la main aujourd'hui, mais déclenché
sans l'opérateur.

Exigences avant toute publication :
1. Essai S0 : mise à jour d'un paquet local (même identité, version +1) pendant une émission du modèle factice,
   puis sur charge fictive avec l'IC-7300MK2 : savoir si Windows reporte la mise à jour (application en marche) ou
   ferme les processus **[à vérifier]**. Même essai pour la désinstallation.
2. S'il ferme : le paquet n'est PAS publié tant qu'une parade n'est pas trouvée et essayée (pistes : mise à jour
   seulement poste en réception, déclenchée par TRX Console par l'API `StoreContext` ; TOT INTERNE du poste
   recommandé dans le guide ; mise à jour « non obligatoire » dans Partner Center).
3. Toujours RX au démarrage (règle existante) : vérifié après une mise à jour du Store.
4. Tests de panne existants inchangés ; nouveau test : `is_store()` vrai => aucun chemin de mise à jour de la
   station.

## 5. Coexistence avec le zip

Un PC qui a déjà la version zip : deux superviseurs = deux rigctld sur 4532 et deux passerelles sur 8443. La version
Store REFUSE de démarrer la station si la tâche planifiée « TRX distant » existe (code ORT nouveau, message : «
désinstallez d'abord la version zip par Paramètres > Applications ; votre configuration est gardée »), et reprend
`C:\ProgramData\trx-remote` tel quel. Le zip fait l'inverse (refus si le paquet Store est installé).

## 6. Fiche du Store

Réutiliser `docs/play-store/listing/<langue>/` (4 langues) et les règles de confidentialité existantes (URL GitHub
Pages) ; captures de TRX Console et de la page web ; avertissement réglementaire (licence radioamateur ou CB,
responsabilité de l'opérateur) ; notes pour la certification : modèle factice Hamlib n° 1, aucune émission réelle
sans poste.

## 7. Licence

L'auteur (RF-DIY.COM) peut publier son code AGPL où il veut. Les composants de tiers (Hamlib GPL / LGPL, FFmpeg de
PyAV LGPL, FreeDV LGPL) : déclarer NOS conditions de licence (AGPL-3.0-or-later + avis des tiers) au lieu des
conditions standard de Microsoft, et donner le lien des sources de la version exacte (tag GitHub) dans la fiche
**[à vérifier : compatibilité GPL des conditions du Store pour un composant GPL]**.

## 8. Fabrication

`scripts/build_msix.py` (nouveau) : copie propre du commit (`git archive`, comme les Releases), Python embarqué
téléchargé avec empreinte, `pip install --require-hashes --target`, Hamlib et FreeDV, manifeste rempli (identité
`Name` / `Publisher` DONNÉES par Partner Center après réservation du nom, version `X.Y.Z.0`), icônes, `makeappx pack`
(Windows SDK). Pour les essais locaux seulement : `signtool` avec un certificat d'essai auto-signé (jamais envoyé au
Store, qui signe lui-même). Fichier produit dans `dist/`.

## 9. Décisions à prendre par l'utilisateur

1. MSIX (proposé) ou EXE / MSI signé.
2. Python embarqué (proposé) ou Nuitka.
3. Hamlib inclus et figé dans le paquet (proposé).
4. Données dans `C:\ProgramData\trx-remote` (proposé, si S0 le permet) ou dans le paquet.
5. Mises à jour : Store seulement, retour arrière perdu (imposé par le Store) ; mise à jour lancée par TRX Console
   poste en réception, si S0 montre que Windows ferme les processus.
6. Nom réservé : « openRemoteTRX » (comme Google Play, proposé) ou « TRX distant ».
7. Visibilité : PRIVÉE d'abord (liste de comptes de bêta-testeurs), publique après les essais.
8. Marchés et langues de la fiche (4 langues proposées).

## 10. Lots

- **S0 (essai, aucun code livré)** : paquet MSIX fait à la main sur ce PC, installé en local (mode développeur) :
  Python embarqué + station + modèle factice ; vérifier les points [à vérifier] (alias, StartupTask, pare-feu
  privé, ProgramData, mise à jour et désinstallation pendant une émission, § 4) ; relevé dans ce cahier.
- **S1** : `packaging.py`, version Store dans le code (§ 3.4, § 5), tests.
- **S2** : `scripts/build_msix.py`, test de fabrication.
- **S3 (utilisateur)** : compte Partner Center particulier, réservation du nom, identité du paquet reportée dans la
  fabrication.
- **S4** : fiche, captures, notes de certification ; première soumission en visibilité privée.
- **S5** : essais réels (installation depuis le Store sur un PC propre, IC-7300MK2 sur charge fictive, mise à jour
  du Store) puis publication publique ; guide de l'opérateur (partie installation Windows).
