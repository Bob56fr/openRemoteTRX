# Station « TRX distant » sur le Microsoft Store : cahier des charges

Version 3 (2026-11-20, étape 321 : versions de Windows § 12, garde Python et essais S0 bis § 11.1 ; v2 : étape 320 ;
v1 : étape 317). Demande de l'utilisateur : « Déploiement du package
d'installation sur le Store Microsoft ; j'ai un compte particulier ». Produit choisi : la STATION Windows complète (pas
l'Autotest). v2 : décisions de l'utilisateur (§ 9) et résultats de l'essai S0 (§ 11) ; aucun code de la station.

**Résumé de S0** : un MSIX avec Python embarqué fait tourner la station telle quelle ; pare-feu (réseaux privés),
alias, tâche de démarrage et écriture dans ProgramData fonctionnent ; une mise à jour normale est REFUSÉE tant que la
station tourne, mais une mise à jour forcée ou une désinstallation TUE la station et laisse rigctld orphelin, poste EN
ÉMISSION : la GARDE DE FIN (§ 4.1) est OBLIGATOIRE, essayée avec succès dans les trois cas.

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
- **Hamlib À CÔTÉ, pas dans le paquet** (décision 3) : l'opérateur installe Hamlib lui-même, comme aujourd'hui
  (`[tools] hamlib_dir`). Messages qui vont bien, au bon moment : premier lancement de TRX Console et assistant 2.1
  (« Hamlib introuvable : téléchargez … puis indiquez son dossier »), refus de démarrer la station sans rigctld
  (code ORT existant ou nouveau), lien vers la page de Hamlib dans la fiche. Effet de bord UTILE vu en S0 : un
  rigctld hors du paquet SURVIT à la fermeture forcée du paquet, ce qui permet la garde de fin (§ 4.1). La
  certification doit le savoir (notes : « Hamlib requis, gratuit, installé à part »).
- **Décodeurs FreeDV** (`freedv/`), comme le zip.
- Code de la station, `LICENSE`, catalogues `i18n`, pages statiques.

### 3.2 Manifeste (`AppxManifest.xml`)

- Application principale « TRX distant » = TRX Console (terminal), entrée du menu Démarrer.
- **Alias d'exécution** (`uap5:AppExecutionAlias`) : `trx-console`, `trx-setup`, `trx-monitor`, `trx-hwtest`,
  `trx-qualif`, `trx-journal-android`… = la liste `$Commands` d'installer.ps1, tapables dans tout terminal (remplace
  les relais `.cmd` et la modification du PATH). Applications secondaires sans entrée de menu
  (`AppListEntry="none"`). VU EN S0 : un alias de python.exe marche (avec ou sans paramètres du manifeste), mais un
  alias de pythonw.exe AVEC paramètres ne lance rien : la STATION ne se lance jamais par un alias.
- **Démarrage à l'ouverture de session** : `desktop:StartupTask` qui lance le superviseur. L'opérateur peut le
  couper dans Paramètres > Applications > Démarrage : TRX Console doit le DIRE (état du démarrage automatique en
  tête, comme l'état de la station). Menu 1.1 (démarrer) : `explorer.exe shell:AppsFolder\<famille>!Supervisor`,
  exactement comme la tâche de démarrage (essayé en S0). VU EN S0 (§ 11.2) :
  - la tâche de démarrage IGNORE `uap10:Parameters` (pythonw lancé avec `argv = ['']`, qui quitte sans rien dire) :
    l'application « Supervisor » est un LANCEUR SANS PARAMÈTRES, `python\trx-station.exe` (copie de pythonw.exe) +
    un `.pth` de site-packages qui importe un petit module : exécutable `trx-station.exe` ET aucun argument = lancer
    `trxstation.supervisor.main` avec la configuration par défaut ; les sous-processus (passerelle, modules), lancés
    AVEC arguments, ne sont pas touchés. Les lignes « import » d'un `._pth` sont IGNORÉES (seul `import site`
    compte) : passer par un `.pth` ;
  - Windows n'exécute la tâche qu'après un PREMIER lancement de l'application par l'utilisateur (à chaque nouvelle
    installation) : fin de l'installation depuis le Store = TRX Console ouverte une fois (bouton « Lancer » du
    Store), qui démarre la station ; le guide le dit.
- **Raccourcis du navigateur** (demande de l'utilisateur du 2026-11-20) : deux entrées de plus dans le menu
  Démarrer, « Console TRX (navigateur) » et « openRemoteTRX (navigateur) ». Un MSIX ne pose pas de raccourci vers
  une adresse : chacune est une application du paquet (lanceur comme ci-dessus) qui lit station.toml et ouvre le
  navigateur par défaut sur `https://<station>:<gateway_port>/` ou `https://<station>:8444/` (adresse juste même si le
  port ou le certificat changent) ; console réseau désactivée = message qui cite le menu 4.6 au lieu d'une page
  morte. À vérifier en S1 : regroupement des trois entrées sous « openRemoteTRX » dans le menu Démarrer de Windows 11.
- **Pare-feu** : `desktop2:FirewallRules` pour le python.exe / pythonw.exe du paquet, TCP et UDP, `Profile="private"`
  : posées à l'installation SANS droits d'administrateur, retirées à la désinstallation (essayé en S0). Règle par
  programme = tout port (8443 ou `gateway_port` changé, 8444 de la console réseau, WebRTC).
- `runFullTrust` (ports série, cartes son, sous-processus, réseau).

### 3.3 Données

Configuration, clés, certificats, état, journaux : HORS du paquet, sinon perdus à chaque désinstallation (et la
virtualisation MSIX de `%APPDATA%` les cacherait aux autres outils). Proposition : MÊME dossier que le zip,
`C:\ProgramData\trx-remote`, droits restreints au compte comme aujourd'hui, créé au premier lancement par la station
elle-même (plus par l'installateur). RETENU (décision 4, avis de Claude) : S0 montre que l'écriture dans ProgramData
depuis le paquet est RÉELLE (aucune copie virtualisée) et que la configuration SURVIT à la désinstallation ; la
migration depuis le zip est immédiate. Attention : un dossier créé par un administrateur n'est pas modifiable par le
compte (vu en S0) : la station crée le dossier sous le compte de l'opérateur, puis restreint les droits.

### 3.4 Version Store dans le code

- Détection : `trxstation/packaging.py` (nouveau) lit l'identité du paquet (`GetCurrentPackageFullName` par
  ctypes) : `is_store()`.
- Mises à jour : menus 7.1, 7.2, 7.3 et vérification `trx-update-check` REMPLACÉS par « Mises à jour : par le
  Microsoft Store » (version installée, lien `ms-windows-store://pdp/?productid=…`). Aucun retour arrière (le Store
  n'en propose pas).
- Mise à jour proposée par TRX Console (décision 5) : `StoreContext` lit la mise à jour disponible ; l'installation
  n'est lancée que poste en RÉCEPTION et station arrêtée proprement (« T 0 » relu), sinon le message « une nouvelle
  version vous attend sur le Microsoft Store » avec le lien de la fiche.
- Chemins : Python et freedv cherchés DANS le paquet, rigctld par `[tools] hamlib_dir` (Hamlib à côté).
- `sys.executable` vaut le chemin de l'ALIAS quand un programme est lancé par un alias (vu en S0 :
  `…\WindowsApps\trx-s0-python.exe`) : les sous-processus de la station (passerelle, modules, outils) se lancent
  avec le VRAI python.exe / pythonw.exe du paquet (`Path(sys.prefix)`), jamais avec l'alias.
- Le paquet zip et la page de la console continuent d'exister ; Debian / Pi inchangés.

## 4. Sécurité d'émission (priorité absolue)

Le Store met à jour, et l'opérateur désinstalle, PENDANT QUE LA STATION TOURNE. Si Windows FERME les processus de
l'application (superviseur, passerelle, rigctld) pendant une émission par la CAT, plus personne n'envoie « T 0 » :
le poste peut RESTER EN ÉMISSION. C'est le même risque qu'un processus tué à la main aujourd'hui, mais déclenché
sans l'opérateur.

CONSTATÉ EN S0 (§ 11) : une mise à jour normale est refusée tant que la station tourne (aucun effet), une mise à jour
différée attend sa fermeture (aucun effet), mais une mise à jour FORCÉE ou une DÉSINSTALLATION tue net le superviseur
et la passerelle (aucune ligne au journal) ; rigctld (hors du paquet) survit, orphelin, et garde le poste factice EN
ÉMISSION indéfiniment. On ne sait pas laquelle des façons le Store emploie : on suppose la pire.

### 4.1 Garde de fin (obligatoire)

Le superviseur lance, à chaque démarrage, une GARDE qui survit à la fermeture du paquet. Paramètres : numéro du
superviseur, port et numéro de rigctld. Elle attend la mort du superviseur, lit le PTT, envoie « T 0 », relit, puis
arrête rigctld. RETENUE (S0 bis, § 11.1) : **garde en Python, par le pythonw.exe DU PAQUET, lancée HORS DU TRAVAIL de
l'application** (`CREATE_BREAKAWAY_FROM_JOB`) : elle survit à la mise à jour forcée ET à la désinstallation (essayé),
sans PowerShell, donc sans stratégie d'exécution ni heuristique d'antivirus. Repli si Windows refuse le
« breakaway » : `powershell.exe` 5.1 par son chemin COMPLET (`%SystemRoot%\System32\WindowsPowerShell\v1.0\`),
script passé en TEXTE par `-Command` (jamais `-File`, bloqué par une stratégie « AllSigned » imposée, essayé),
jamais `-EncodedCommand`, jamais PowerShell 7 (`pwsh`, absent par défaut). Essais : station tuée net, mise à jour
forcée, désinstallation, avec chacune des deux gardes : PTT 1 lu, « T 0 », PTT 0 relu, moins d'une seconde après la
mort du superviseur. Règles :
- lancée SANS `DETACHED_PROCESS` (powershell quitte aussitôt avec ce drapeau, vu en S0), avec `CREATE_NO_WINDOW` ;
- un arrêt NORMAL de la station la laisse faire (« T 0 » de plus, sans effet) ;
- une garde absente ou morte = station refusée au démarrage (fail-safe), test de panne ;
- au démarrage, le superviseur ADOPTE un rigctld orphelin (déjà le cas, vu en S0) et le remet en réception ;
- [à vérifier en S4] la certification accepte la garde (processus hors du travail de l'application) ;
- la même garde sert aussi au zip Windows (station tuée par le Gestionnaire des tâches) : à proposer.

Exigences avant toute publication :
1. Garde de fin (§ 4.1) codée et ses tests de panne (superviseur tué, garde tuée, rigctld absent).
2. Essai réel sur charge fictive avec l'IC-7300MK2 : désinstallation et mise à jour forcée pendant une émission ;
   poste relu en réception à l'afficheur.
3. Toujours RX au démarrage (règle existante) : vérifié après une mise à jour du Store.
4. Tests de panne existants inchangés ; nouveau test : `is_store()` vrai => aucun chemin de mise à jour de la
   station.
5. S4 (visibilité privée) : vraie mise à jour par le Store pendant une émission sur charge fictive, pour connaître
   le comportement réel du Store.

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

## 9. Décisions de l'utilisateur (2026-11-20)

1. « Le plus fiable des deux » : **MSIX** (signé par le Store, installation et retrait propres, sans droits
   d'administrateur ; vérifié en S0).
2. « Le plus fiable, sans installer Python ni venv » : **Python embarqué** (les deux évitent l'installation ; Python
   embarqué garde le code et les modules essayés tels quels, Nuitka devrait recompiler aiortc / PyAV et réécrire les
   lancements `python -m` ; vérifié en S0 : la station tourne sans changement).
3. **Hamlib à côté**, installé par l'opérateur, avec des messages qui le guident au bon moment (§ 3.1).
4. Avis demandé, retenu : **`C:\ProgramData\trx-remote`** (§ 3.3, vérifié en S0).
5. **Store seulement** ; mise à jour lancée par TRX Console poste en réception, sinon message « nouvelle version sur
   le Microsoft Store » (§ 3.4).
6. Nom réservé : **openRemoteTRX**.
7. Visibilité **privée** d'abord, publique après les essais.
8. Fiche en **français, anglais, allemand, espagnol**.

## 10. Lots

- **S0 TERMINÉ** le 2026-11-20 sur le PC « tour radio » (§ 11, § 11.1, § 11.2), paquet d'essai, certificat et
  données retirés ; restent Windows 10 22H2 dans une machine virtuelle (§ 12) et Smart App Control en marche (PC
  neuf ou machine virtuelle).
- **S1** : `packaging.py`, version Store dans le code (§ 3.4, § 5), GARDE DE FIN (§ 4.1) et ses tests de panne,
  messages Hamlib (§ 3.1), tests.
- **S2** : `scripts/build_msix.py`, test de fabrication. FAIT (étape 335, avec la fin de S1a).
- **S3 (utilisateur)** : compte Partner Center particulier, réservation du nom, identité du paquet reportée dans la
  fabrication. FAIT le 2026-11-20 : `windows/msix/identity.toml` (Name RF-DIY.COM.openRemoteTRX, Publisher
  CN=4DBA8C0D-D395-454A-A7A5-5CB99996408C, PublisherDisplayName RF-DIY.COM ; famille
  RF-DIY.COM.openRemoteTRX_5fxpmskyjpc1g), groupe de testeurs créé.
- **S4** : fiche, captures, notes de certification ; première soumission en visibilité privée.
  PRÉPARÉ (étape 335) : fiche en 4 langues `docs/microsoft-store/listing/<langue>/` (description, fonctions,
  mots-clés, configuration requise), notes de certification en anglais `docs/microsoft-store/notes-certification.txt`
  (justification de runFullTrust, parcours sans poste), règles de confidentialité de la station
  `docs/site/station/confidentialite.html` ; captures (1366 x 768 au moins) à faire par l'utilisateur.
- **S5** : essais réels (installation depuis le Store sur un PC propre, IC-7300MK2 sur charge fictive, mise à jour
  du Store) puis publication publique ; guide de l'opérateur (partie installation Windows).

## 11. Essai S0 (2026-11-20, PC « tour radio », Windows 11)

Paquet d'essai `RFDIY.openRemoteTRX.S0` (0.0.1.0 et 0.0.2.0, 90 Mo) : Python 3.12.10 embarqué, station 0.244.0
installée depuis une copie propre du commit (`git archive`, `pip --require-hashes --target`), manifeste de trois
applications (Console, Supervisor avec StartupTask, Python), pare-feu du manifeste ; makeappx et signtool du paquet
NuGet `Microsoft.Windows.SDK.BuildTools` 10.0.28000 (sans installer le SDK) ; signé par un certificat d'essai
`CN=openRemoteTRX-S0` (approuvé dans `LocalMachine\TrustedPeople` de tour radio). Poste factice (modèle 1), ports à
part (rigctld 4632, page 8543), configuration `C:\ProgramData\trx-remote-s0`, Hamlib 4.7.2 À CÔTÉ du paquet.

| Point | Résultat |
|---|---|
| Installation par SSH (même administrateur) | REFUSÉE (0x80070005) : un MSIX s'installe dans la session de bureau de l'utilisateur (essais : tâche planifiée ponctuelle « Interactive ») |
| Installation dans la session | 8 s, sans droits d'administrateur, `SignatureKind` Developer |
| Pare-feu | 4 règles (python / pythonw, TCP / UDP), entrantes, profil PRIVÉ seulement ; retirées à la désinstallation |
| Alias | les trois présents dans `%LOCALAPPDATA%\Microsoft\WindowsApps` ; alias de python.exe OK ; alias de pythonw.exe avec paramètres : rien ne démarre |
| `sys.executable` | chemin de l'ALIAS si lancé par alias (§ 3.4) ; vrai chemin du paquet si lancé par le menu / `shell:AppsFolder` |
| ProgramData | écriture RÉELLE depuis le paquet (aucune copie virtualisée) ; configuration et état GARDÉS après désinstallation |
| Station | superviseur, rigctld (hors paquet) et passerelle démarrés, état publié, journaux écrits ; aucun changement de code |
| Tâche de démarrage | enregistrée, état 2 (en service) ; à l'ouverture de session : voir § 11.2 |
| Mise à jour sans option, station en marche | REFUSÉE (0x80073D02, ressources utilisées) : station intacte |
| Mise à jour différée | acceptée, appliquée à la fermeture : station intacte |
| Mise à jour FORCÉE | 34 à 42 s ; superviseur et passerelle TUÉS sans journal ; rigctld SURVIT, poste factice resté EN ÉMISSION |
| Désinstallation, station en marche | 33 à 36 s ; même effet : rigctld orphelin, PTT = 1 relu après coup |
| Relance après une fermeture forcée | rigctld orphelin ADOPTÉ, poste remis en réception (PTT 0) |
| Garde de fin (§ 4.1), trois cas | PTT 1 lu, « T 0 », PTT 0 relu, rigctld arrêté, 0,6 s après la mort du superviseur |
| Garde lancée avec `DETACHED_PROCESS` | powershell quitte aussitôt (code 0) : drapeau interdit |

Fichiers gardés pour les prochaines fabrications (hors dépôt, sur tour radio) : `C:\dev\openRemoteTRX-msix\`
(`outils\sdk-buildtools-10.0.28000` = makeappx / signtool, `outils\python-embed\python-3.12.10-embed-amd64.zip`,
`outils\hamlib-w64-4.7.2`, `scripts\build_s0.py`, `s0\` : paquets, certificat d'essai, scripts des essais, garde,
`s0run.ps1` = lancer un script dans la session de bureau). Le certificat d'essai (clé privée) est dans le magasin
« Personnel » du compte du PC de développement ; le vrai paquet est signé par le Store.

### 11.1 Essai S0 bis (2026-11-20, tour radio : Windows 11 Famille 25H2, build 26200, x64)

| Point | Résultat |
|---|---|
| Stratégie « AllSigned » imposée (`HKCU\Software\Policies\…\PowerShell`, compte chris seul, retirée ensuite) | garde `powershell -File` BLOQUÉE (rien ne tourne) ; garde `powershell -Command` (texte) : fonctionne ; garde Python : fonctionne |
| Lancement hors du travail de l'application (`CREATE_BREAKAWAY_FROM_JOB`) depuis le Python du paquet | accepté |
| Garde Python du paquet (hors du travail), mise à jour FORCÉE pendant une émission | survit : PTT 1 lu, « T 0 », PTT 0 relu, rigctld arrêté, ~1 s après la mort du superviseur |
| Garde Python du paquet (hors du travail), DÉSINSTALLATION pendant une émission | survit : même résultat |
| Garde PowerShell 5.1 `-Command` (chemin complet), désinstallation pendant une émission | même résultat (0,6 s) |
| Defender (temps réel, comportement, AMSI en marche) | aucune détection pendant tous les essais (gardes cachées comprises) |
| Smart App Control | ARRÊTÉ sur tour radio (installation ancienne) : non essayé |
| Mode S | absent : non essayé (voir § 12) |

### 11.2 Tâche de démarrage à l'ouverture de session (2026-11-20, trois reconnexions de l'utilisateur)

Traceur : un `sitecustomize.py` du paquet d'essai notait chaque lancement de Python (heure, `sys.argv`).

| Paquet | Ouverture de session | Résultat |
|---|---|---|
| 0.0.2.0, jamais lancé depuis sa réinstallation | 16:34:26 | RIEN lancé en 5 min (tâche pourtant en service) |
| 0.0.2.0, lancé une fois à la main | 16:42:43 | Supervisor lancé à 16:42:51, arrêté dans la même seconde, aucun journal |
| 0.0.3.0 (traceur), lancé une fois | 16:52:58 | pythonw lancé à 16:53:11 avec `argv = ['']` : paramètres du manifeste IGNORÉS |
| 0.0.5.0 (lanceur `trx-station.exe` + `.pth`), lancé une fois | 17:03:47 | station DÉMARRÉE SEULE à 17:03:55 (superviseur, rigctld, passerelle en réception à 17:03:58) |

(La 0.0.4.0, lanceur avec la ligne « import » dans le `._pth`, ne démarrait rien : ligne ignorée.)

## 12. Versions de Windows

| Système | Pris en charge | Pourquoi |
|---|---|---|
| Windows 7, 8, 8.1 | NON | ni MSIX ni Store pour une application de bureau ; Python 3.11+ exigé par la station ne tourne plus sous Windows 7 (dernier : 3.8) ; aucun correctif de sécurité, alors que la station ouvre des ports. Même le zip ne peut pas y tourner. |
| Windows 10 avant 2004 (build 19041) | NON | `uap10:Parameters` du manifeste (paramètres des applications) inexistant ; le Store ne propose pas le paquet (`MinVersion`) |
| Windows 10 22H2, x64 | OUI, avec avertissement | plus de correctifs depuis octobre 2025 (extension grand public finie en octobre 2026) sauf éditions LTSC / entreprise : la page d'installation et TRX Console le signalent sans bloquer ; console noire (conhost) : pictogrammes de TRX Console illisibles, `TRX_CONSOLE_SANS_ICONES=1` (étape 223) ; ESSAI À FAIRE (machine virtuelle) |
| Windows 11, x64 (Famille, Pro) | OUI | essayé (S0, S0 bis) |
| Windows 10 / 11 en mode S | NON, refus expliqué | programmes hors Store (rigctld de Hamlib) et PowerShell interdits : la station le détecte (`HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy`, `SkuPolicyRequired = 1`) et refuse de démarrer avec un message (sortir du mode S : gratuit, sans retour) |
| Windows 11 ARM (Snapdragon) | NON pour l'instant | paquet x64 en émulation : à essayer avant de le promettre ; pilotes USB des postes en ARM64 à vérifier ; Windows 10 ARM n'émule pas le x64 |

Autres règles :
- PowerShell : seul **Windows PowerShell 5.1** est garanti (identique sous Windows 10 et 11) ; PowerShell 7 (`pwsh`)
  s'installe à part : jamais exigé. Tout script lancé par la station : syntaxe 5.1, chemin complet, `-Command`.
- Smart App Control (Windows 11 installé neuf) : peut bloquer un programme non signé ou peu connu (rigctld de Hamlib,
  pythonw du paquet ?) : essai à faire sur un PC neuf ou une machine virtuelle ; s'il bloque, message qui l'explique.
- Stratégies d'entreprise (GPO, AppLocker, WDAC) : la station ne cherche pas à les contourner ; une garde qui ne
  démarre pas = station refusée (fail-safe), message clair.
- Guide de l'opérateur et fiche du Store : « Windows 10 22H2 ou Windows 11, 64 bits (x64) ».
