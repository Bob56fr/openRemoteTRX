# trx-remote : pilotage à distance d'un TRX radioamateur

Système bidirectionnel (écoute + émission) pour piloter un TRX depuis un smartphone Android et Android Auto.
Côté station : PC Debian ou Windows (Raspberry Pi prévu, jamais essayé), Python 3.11+. Côté client : page web servie par la station (aujourd'hui), application Android en Kotlin (plus tard).

Langue de travail : français. Réponses concises, avis honnêtes : signale tout problème technique ou de sécurité plutôt que d'approuver par défaut. Ne remets pas en cause les décisions ci-dessous sauf problème réel.

## Travail en parallèle (plusieurs conversations)

Plusieurs conversations font évoluer ce dépôt en parallèle (designer, modules, qualification…). Pour ne plus rien écraser :
- Toujours partir du DERNIER état du dépôt fourni par l'utilisateur, jamais d'une copie plus ancienne.
- L'historique détaillé des étapes est dans `docs/historique.md` : chaque livraison y AJOUTE son entrée (numérotée) et met à jour ici « État actuel », « Essais réels à faire », « En attente » et « Pièges » en quelques lignes.
- Numéro d'étape et version = le plus grand numéro présent dans `docs/historique.md` et `pyproject.toml` + 1 (vérifier avant de livrer).
- Ne jamais supprimer une entrée de `docs/historique.md`, ni une ligne de `pyproject.toml` (paquets, données, commandes) écrite par une autre livraison : AJOUTER à côté.
- Une conversation à la fois dans ce dossier ; commit (et push) à la fin de chaque étape.
- Un zip ne contient que les fichiers réellement modifiés ; si un fichier commun (CLAUDE.md, pyproject.toml, `__init__.py`) a changé depuis la copie de travail, fusionner à la main.

## Règles de sécurité d'émission (priorité absolue)

- **PTT en toggle uniquement**, jamais en maintien appuyé. Aucune exception.
- L'état RX/TX appartient au **serveur** (source de vérité). Les clients envoient « toggle » et affichent l'état renvoyé, jamais un état supposé.
- Sécurités côté Pi, indépendantes des apps : TOT (défaut 90 s, plafond 120 s, bip 10 s avant coupure) ; heartbeat client ~500 ms pendant le TX, retour RX si absent 2 s ; retour RX immédiat si la connexion tombe ; verrou mono-client pour l'émission.
- Toujours RX au démarrage et à la reconnexion.
- EXCEPTION DÉCIDÉE PAR L'UTILISATEUR (2026-10-27, étape 32) : bips de fin émis par la station, désactivés par défaut. Roger bip quand le PROPRIÉTAIRE relâche lui-même ; bip de liaison perdue (trois tons descendants) quand le terminal ne répond plus pendant SON émission (battement perdu, connexion fermée). Seulement depuis TX confirmé, jamais une nouvelle prise, 0,6 s de son et 1,2 s d'attente au plus, micro du client fermé avant ; aucune autre coupure ne bipe, et toute coupure pendant un bip l'interrompt net (`docs/bips.md`).
- OPÉRATEUR SUR PLACE (décision de l'utilisateur, 2026-10-27, étape 34) : « station partagée » par défaut (`[supervisor] allow_local_tx = true`) : une émission faite au micro du poste n'est coupée que par le TOT absolu (`tot_abs_s`, 135 s, réglable sur la station). Une action sur le poste (émission locale, fréquence ou mode changés sans commande de la station) bloque le PTT À DISTANCE pendant l'émission locale puis 2 minutes ; un client peut « reprendre la main » plus tôt, JAMAIS pendant une émission locale. La station ne coupe jamais l'opérateur local pour ce motif. Dans tous les modes, l'échelle de reprise (relances, reset USB, mode sûr) n'est lancée que si une émission RÉSISTE à « T 0 ».
- La passerelle contrôle aussi la **porte audio d'émission**, pas seulement la ligne PTT.
- **Fail-safe** : en cas de doute, ne pas émettre. Liste de bandes vide = réception seule. Le superviseur et les outils ne peuvent que couper, jamais déclencher une émission.
- Tout code qui peut activer le PTT doit avoir des tests de panne (coupure heartbeat, TOT, déconnexion, gel de la passerelle).
- Les tests utilisent le **modèle factice Hamlib (numéro 1)**, jamais un vrai poste, sauf validation finale explicite.

## Architecture

**Station (PC Debian, PC Windows ou Pi : mêmes sources)**
- `rigctld` (Hamlib) écoute **uniquement** en 127.0.0.1:4532 : il n'a aucune authentification, ne jamais l'exposer.
- Passerelle Python : parle à rigctld, expose une API filtrée (fréquence, mode, filtres, PTT, S-mètre) et l'audio.
- Audio duplex : WebRTC (aiortc côté Pi, libwebrtc côté Android), Opus, DataChannel pour CAT/PTT sur la même connexion. Mumble écarté.
- Réseau : AUCUN VPN imposé. Chaque utilisateur choisit (VPN de son choix, ou port exposé + TLS) ; authentification par identifiant + mot de passe haché (voir `docs/acces-distant.md`).
- **Superviseur autonome** (`station/supervisor/`) : seconde couche de sécurité indépendante. Interroge rigctld directement ; force RX (`T 0`) et tue la passerelle si TX > TOT absolu, TX sans client, ou passerelle muette. Surveille aussi rigctld, USB, Tailscale, température/throttling, mémoire, disque ; détecte les anomalies (fréquence hors bandes, changements non commandés, PTT incohérent). Alertes ntfy. Escalade : redémarrer la passerelle, puis rigctld, puis reset USB, puis reboot du Pi limité (ex. 3/heure), au-delà de quoi mode sûr (RX, accès coupé). Minimal, quasi sans dépendance, unit systemd avec `WatchdogSec` + `Restart=always`, plus watchdog matériel du Pi.
- **Tableau de bord texte** (`station/monitor/`, commande `trx-monitor`, Textual/Rich) : simple lecteur d'un « bus d'état » local en lecture seule (JSON publié par passerelle et superviseur). Une seule action : touche « STOP TX » (force RX). Affiche radio, connexion, services, matériel, audio, journal.

**Client Android (Kotlin)**
- `RigService` (foreground) unique : possède la connexion et l'état. L'écran smartphone (Compose) et la MediaSession Android Auto sont deux vues qui s'y abonnent (StateFlow).
- Android Auto : `MediaBrowserService` + `MediaSession` (pas Car App Library). Minimal : lecteur du flux RX, Mute/Volume, présélections (custom actions), commande vocale (`onPlayFromSearch`), PTT toggle avec état explicite (« ÉMISSION EN COURS »), bip à l'activation et à la coupure. Fréquence/mode/préset et indicateur S en texte dans le titre/sous-titre. Aucun graphique, waterfall ni saisie de texte.
- Smartphone : interface complète (S-mètre, fréquence, modes, filtres, PTT toggle bien visible, compte à rebours du TOT, bouton STOP). Prévoir un mode « conduite » qui limite l'interface : un PTT tactile en roulant pose problème légal et anti-distraction. En roulant : toggle sur écran voiture, voix, bouton Bluetooth HID ou touches média du volant (`onMediaButtonEvent`).
- Diffusion : refus Play Store probable en catégorie voiture ; usage perso via sideload et mode développeur Android Auto. Vérifier le cadre réglementaire de la licence.

## Indépendance vis-à-vis du modèle de TRX

Tout poste supporté par Hamlib (~300 modèles). Aucun code spécifique à un modèle.
- `trx-setup` : détecte ports série (`/dev/serial/by-id`) et cartes audio (ALSA, noms stables), cherche le modèle dans `rigctl -l`, teste la liaison **en lecture seule**, choisit la méthode PTT (CAT, RTS, DTR, GPIO, aucune). CAT et audio sont **deux périphériques indépendants** (interfaces externes type Digirig/SignaLink).
- La passerelle interroge Hamlib (`dump_caps`) et publie un **descripteur de capacités** (modes, filtres, S-mètre, méthode PTT) ; l'app construit son interface à partir de lui. Calibration S-mètre par table.
- Source de vérité unique : `station.toml` sur le Pi, versionné, validé côté serveur.

**Réglages en deux niveaux**
- Modifiables depuis le smartphone : présélections, noms de canaux, gains audio, calibration S-mètre, mode/filtre par défaut, TOT (sous le plafond).
- **Pi uniquement** : modèle, port, débit, méthode PTT, bandes autorisées, plafond TOT, réglages du superviseur, clés d'authentification.
- Changement touchant rigctld depuis le smartphone : « appliquer avec confirmation » (retour automatique à l'ancienne config si le client ne confirme pas sous ~30 s).

## Arborescence

```
openRemoteTRX/
├── CLAUDE.md, README.md, README.fr.md, LICENSE, pyproject.toml
├── trxstation/                   # tout le code de la station (voir « État actuel »)
├── tests/                        # pytest ; tests/js/ : tests Node de la page
├── docs/                         # documentation (français) ; historique.md = historique des étapes ; site/ = GitHub Pages
├── .github/workflows/            # pages.yml : publication de docs/site sur GitHub Pages
├── debian/                       # install.sh, releases.sh, LISEZMOI.txt, règles, lanceur TRX Console
├── systemd/                      # rigctld, trx-gateway, trx-supervisor, trx-update-check, trx-remote.target
├── scripts/                      # build_debian_zip.py, build_themes.py, gen_update_key.py
└── config/                       # station.example.toml
```

## Bibliothèques

- Python : stdlib d'abord ; aiortc, aiohttp, sounddevice ou pyalsaaudio, pydantic, Textual/Rich, pytest. Hamlib 4.5+.
- Kotlin : stream-webrtc-android, Compose + Material 3, media3-session / androidx.media, Coroutines/Flow, kotlinx.serialization, Hilt.

## Stratégie : d'abord le côté Pi, sans Android

La passerelle est le composant critique : validée seule avant tout Kotlin. Outils de test : `tools/fake_client.py` (joue le smartphone via aiortc), `tools/audio_loopback.py` (latence aller-retour), tests pytest des scénarios de panne, test du superviseur (`kill -STOP` de la passerelle pendant un TX). Le protocole (messages CAT/PTT, descripteur de capacités, format du bus d'état) est figé et documenté côté Pi avant l'étape Android.

## État actuel (version 0.54.0, étape 55)

L'historique COMPLET des étapes (décisions, formats relevés, défauts trouvés, essais) est dans `docs/historique.md` : le lire avant de toucher à un sujet ancien. Ici, l'essentiel.

- **Station** (Python, `trxstation/`) : configuration validée (`config.py`, `station.toml`), assistant `trx-setup`, passerelle (`gateway/` : CAT par rigctld, sécurité PTT `safety/ptt.py` + opérateur sur place `safety/local.py`, audio WebRTC/aiortc, API et page web `api/`, mémoires, bips de fin, rapports de problème `bugreports.py`), superviseur indépendant (`supervisor/`, mode géré Windows ou systemd), tableau de bord `trx-monitor`, modules (`modules/` : bus 127.0.0.1, module cluster DX `cluster/`), spectre HF et préréglages FIL1/2/3 par le second port CI-V Icom (`spectrum/`), mises en page (`layout/`), qualification de poste (`qualif/`, `trx-qualif`), mise à jour signée (`update/`), TRX Console (`console.py`, 16 menus dont 13 = zip déposé, 14 = station.toml validée, 15 = menu expert/tests, 16 = seuils de température, 17 = indicateur GNOME, 18 = profils de poste, 19 = appairage d'un téléphone (empreinte du certificat et QR code) ; touche `h` = aide d'un menu (`h 19`) ; en-tête : version et identifiant de station `station_id.py` ; réponses en casse libre `answers.py`), diagnostic et rapport.
- **Page web** (`gateway/api/static/`) : `client.js` (logique, testée sous Node), `ui.js` (affichage), `waterfall.js`, `hfscope.js`, `spots.js`, `layout.js`, `theme.js` ; index.html, client.css (couleurs en variables, thèmes générés par `scripts/build_themes.py`).
- **Indicateur GNOME** (barre du haut, lecture seule) : `debian/gnome-extension/` (logique `status.js` testée sous Node), installé par install.sh, activé par le menu 17. Windows : à faire (icône près de l'horloge).
- **Paquet Windows** : `scripts/build_windows_zip.py` -> `dist/trx-remote-windows-X.Y.Z.zip` (`windows/` : installer.cmd, installer.ps1 en UTF-8 avec BOM, notice-windows.html) ; versions dans `%LOCALAPPDATA%\Programs\TRX distant`, configuration `C:\ProgramData\trx-remote` (ACL), tâche planifiée à l'ouverture de session (pythonw, `--log-dir`), arrêt par `trx-supervisor --stop`, pare-feu réseaux privés, raccourcis du menu Démarrer. `-Essai -Destination` : essai sans rien toucher au système.
- **Installation Debian** : `debian/install.sh` + `releases.sh` (versions côte à côte, retour arrière), paquet `scripts/build_debian_zip.py` (`--sans-signature` pour les essais ; contient LICENSE et tests/ pour le menu expert).
- **Validé sur le vrai matériel** (IC-7300MK2) : CAT, PTT, audio, page web (PC et téléphone en Wi-Fi), spectre HF par le port B, pannes (passerelle gelée, superviseur arrêté, client perdu) sous Windows ; installation et marche sous Debian 13 (minix-bzh).
- **Pas encore essayé** : voir « Essais réels à faire ».
- **Licence** : AGPL-3.0-or-later, `LICENSE`, en-têtes SPDX (voir Conventions). README.md (anglais) et README.fr.md.

## Essais réels à faire (sur charge fictive)

Application Android sur le Samsung S25 (connexion, écoute, écran éteint, refus hors bande, QR code et compte S25 : validés le 2026-10-28 ; restent : écoute 30 min écran éteint en Wi-Fi et 4G, appel entrant pendant l'émission => STOP, bips d'émission et ALC, 10 émissions sur charge fictive) ; QR code du menu 19 sur minix-bzh après installation de 0.53.0 ; Essai Debian complet (`docs/essai-debian.md` dès l'étape 3) ; indicateur GNOME (menu 17, après reconnexion) ; installation Windows complète (tâche, pare-feu, raccourcis : seul le mode -Essai a été essayé) ; opérateur sur place (micro du poste, « Reprendre la main ») ; bips de fin (ALC en USB-D, STOP pendant un bip) ; TRX Console menu 4 « réception seule » (largeurs de filtre acceptées, spectre depuis un menu du poste) ; ATT / Notch / fenêtres NR-NB ; FIL1/2/3 par le port B (format CI-V 26 00 à confirmer) ; état des flux du Cluster DX dans la page ; menu expert (pytest sur Debian : 20 tests ne tournent que sous Linux) ; accès distant en 4G/5G ; Raspberry Pi (jamais essayé).

## En attente (décisions ou travaux à venir)

- Signature des mises à jour : clé jamais générée (`scripts/gen_update_key.py`, `update/pubkey.py` vide => mise à jour par Internet refusée) ; `pip --require-hashes` à faire.
- Température du poste : seuils 40/50 °C (`safety/thermal.py`, coupure à distance au 2e) ; l'IC-7300MK2 n'expose PAS TEMP_METER sous Hamlib => sans effet sur ce poste, capteur externe à étudier.
- Collecte des journaux (rf-diy / Azure) : identifiant de station prêt (`station-id`), cahier des charges `docs/collecte-azure-cahier-des-charges.md`, service à construire dans un AUTRE dépôt.
- Signalement des problèmes : étape 2 (réception sur le site WordPress de l'utilisateur) ; formulaire de qualification « [À COMPLÉTER] ».
- Rapport à Hamlib : `docs/hamlib-rapports.md` à envoyer par l'utilisateur.
- Application Android (`com.rfdiy.openremotetrx`, Android 10+) : cahier des charges `docs/android-cahier-des-charges.md` ; lot A0 fait (étape 50 : `docs/protocole.md`, exemples `tests/protocol/`, `hello.features`, empreinte du certificat) ; lot A1 fait (étapes 51-53, application 0.2.0 : `:protocol`, `:logic` avec RigSession et ses tests de panne, `:core` RigService/WebRTC/empreinte, `:app` écrans et lecture du QR code d'appairage (ZXing) ; essayé dans l'émulateur et sur le Samsung S25 avec minix-bzh)  ; interface du téléphone (étapes 54-57, application 0.5.0 : fréquence, bandes, modes, S-mètre en barre, squelch, boutons du poste, niveaux NR/NB, Po/SWR/ALC, mémoires éditables, spectre HF (étape 58), waterfall audio (étape 59, application 0.7.0), police compacte, écran allumé pendant la connexion ; PTT et STOP toujours visibles en bas) ; prochain : lot A2 (Android Auto, toutes voitures, PTT au volant = Lecture/Pause désactivé par défaut). Installer sur le téléphone : `adb install -r app\build\outputs\apk\debug\app-debug.apk` (Bloqueur automatique Samsung désactivé). Construire : `cd android ; gradlew.bat test assembleDebug` avec JAVA_HOME = jbr d'Android Studio. Matrice `docs/parite-web-android.md`.
- VFO A / B, split et clarifieur (RIT / XIT) : oubliés depuis le début (demande du 2026-10-29), station + page + application ; SÉCURITÉ : en split, la fréquence d'émission est celle de l'autre VFO (XIT la décale aussi) => la vérification des bandes d'émission doit porter sur elle, et un split illisible = émission refusée.
- Commande vocale « QSY 27 555 » en réception, avec confirmation sur le téléphone (demande du 2026-10-29) : à étudier (bouton micro de l'application ou écoute permanente) ; ne change que la fréquence, jamais en émission.
- Application Android (étapes 9 à 11 du plan d'origine), designer lot 3, qualification Q2 à Q6, plafonds CPU/mémoire des modules, superviseur (mémoire, disque, watchdog matériel du Pi), règle PipeWire.

## Pièges et leçons (à relire avant de coder)

- **Hamlib** : tout format de réponse ou de capacité doit venir d'un VRAI rigctld (réponses parfois sans libellé ; `dump_caps` incohérent : IC-7300MK2 « Attenuator: 20dB » mais « ATT(0..12) » => une liste déclarée prime sur la plage). `async=1` sous Windows (Hamlib 4.7.2) : réponses décalées, fréquence fausse renvoyée comme un succès => REJETÉ, spectre par le second port CI-V. rigctld relit parfois le PTT dans son cache.
- **Hamlib et filtres Icom** : `set_mode` avec une largeur RÉÉCRIT la largeur du préréglage FIL choisi ; préréglages par le port B (26 00).
- **IC-7300MK2** : modes données (PKTUSB…) seuls modulés par l'USB (`tx_modes`) ; port B (spectre) = `…-if02` sous Linux (pas if01), COM7 sous Windows, adresse B6h ; réglages USB SEND / USB Keying : un port B mal réglé peut mettre en émission ; le spectre se FIGE pendant l'émission (pause, pas une panne).
- **Fils et asyncio** : un fil qui produit (port série) ne doit jamais empiler un `call_soon_threadsafe` par donnée : un seul envoi en attente (le dernier), sinon un petit PC noie la boucle (tests bloqués sur Debian, étape 44). Diagnostic d'un blocage : `py-spy dump --pid`.
- **Sécurité** : la passerelle ne doit JAMAIS quitter sur une erreur d'API ou de port (le superviseur la relancerait en boucle jusqu'au mode sûr) ; une émission qui revient après « T 0 » est une nouvelle émission (opérateur), pas une panne ; NR/NB sont à la fois FONCTION et NIVEAU (clés distinctes `f:`/`l:`).
- **Son sous Linux** : PortAudio ne liste PAS une carte occupée (station, PipeWire) ; le noyau (`arecord -l`) la voit toujours. Sur minix-bzh la carte du poste est la sortie par défaut du bureau.
- **Debian** : superviseur en root => modules sous `run_as` ; fichiers lus par le compte de bureau en 0644 (état passerelle, mode sûr, cluster) ; poste éteint = `rig_absent` (jamais de mode sûr) ; renvoyer un zip ne suffit pas, il faut installer (menu 13) ; le mode sûr mémorisé survit aux corrections (menu 9) ; `station.toml` existante garde ses valeurs (un nouveau défaut ne s'y applique pas).
- **Windows sans fenêtre** (pythonw) : un processus enfant ne reçoit PAS CTRL_BREAK (pas de console commune) et finit tué ; d'où « T 0 » par le superviseur dans `stop_all`. rigctld lancé avec CREATE_NO_WINDOW. Le Python d'un venv relance l'interpréteur de base : règles de pare-feu sur `sys._base_executable`.
- **Windows / outils de Claude** : PowerShell 5.1 relit en ANSI (`Get-Content | Set-Content` abîme les accents et ajoute un BOM : modifier en Python ou avec l'outil d'édition) et retire les guillemets intérieurs passés à `ssh` (envoyer un script à `bash` par l'entrée standard) ; pytest exige `--basetemp` dans le dossier temporaire de la conversation ; durées courtes avec `time.perf_counter()` ; `os.replace` réessayé (`status.replace_atomic`) ; remplacer `subprocess.Popen` globalement casse asyncio ; un message `hello` n'implique pas encore de `state` (attendre dans les tests).
- **Android (Gradle)** : Android Studio fournit Java 25 => Gradle 9.6+ (exigé par AGP 9.5) et Kotlin 2.2+ ; AGP 9 intègre Kotlin (pas de plugin kotlin-android) ; nom de test entre accents graves sans « : » (refusé par la JVM). Essai de bout en bout : passerelle en 127.0.0.1:8443, TLS auto-signé (hôtes 127.0.0.1 et 10.0.2.2), faux rigctld ; l'émulateur voit le PC en 10.0.2.2 ; `adb shell input text` tronque les textes longs, et sous Git Bash il faut MSYS_NO_PATHCONV=1.
- **Page web** : l'attribut `hidden` est battu par un `display:` de classe (`[hidden]{display:none !important}`) ; clic fantôme Android après un appui ; le faux DOM des tests JS n'a ni id ni parent ; un vrai Chromium (Playwright) avec une fausse station trouve ce que les tests simulés ne voient pas ; le canal de données d'aiortc limite un message à 64 ko.

## Environnement de l'utilisateur

- Développement : PC Windows 11, dépôt `C:\dev\openRemoteTRX`, GitHub `Bob56fr/openRemoteTRX` (public), branche `main`.
- Station Debian 13 « minix-bzh » : `ssh bob@192.168.1.19` (clé SSH ; le nom minix-bzh n'est pas connu du SSH), Bureau `~/Desktop`, sudo avec mot de passe (installation par l'utilisateur, `ssh -t` ou TRX Console menu 13), Hamlib 5.0.0~git compilé dans /usr/local/bin.
- Poste : Icom IC-7300MK2, Hamlib 3094 ; Windows COM8 (CAT) / COM7 (port B) ; Linux by-id `…_13003336-if00` / `-if02`.

## Conventions

- LICENCE : AGPL-3.0-or-later (fichier LICENSE du dépôt). TOUT nouveau fichier de code commence par l'en-tête (après `#!` ou `<!doctype html>`) : Python, shell, PowerShell `# SPDX-License-Identifier: AGPL-3.0-or-later` puis `# Copyright (C) 2026 RF-DIY.COM` ; JavaScript et Kotlin en `//` ; CSS en `/* */` ; HTML en `<!-- -->`. Pas d'en-tête dans JSON, TOML, Markdown, units systemd ni images.
- Python : annotations de types, `from __future__ import annotations`, asyncio pour la passerelle, pas de dépendance inutile (surtout dans le superviseur).
- Valider toute entrée externe (config, messages réseau). Toute incohérence de sécurité est une erreur bloquante, pas un avertissement.
- Messages utilisateur et commentaires en français.
- PROFILS DE POSTE (`profiles.py`) : toute livraison qui ajoute, renomme ou retire une clé de [rig], [audio] ou [spectrum] monte `PROFILE_FORMAT`, ajoute `PROFILE_FIELDS[nouveau]` et écrit `MIGRATIONS[ancien]` (ou None si impossible : le profil sera refusé avec le conseil de refaire la configuration). Le test `test_profile_format_matches_the_current_configuration_fields` l'impose.
- MODE D'EMPLOI DE LA CONSOLE (page publique, thème sombre, iframe du site rf-diy.com) : toute livraison qui touche TRX Console (menus, comportement, messages importants) met à jour `docs/console/contenu.toml` puis relance `python scripts/build_console_doc.py` APRÈS le changement de version (le test `test_console_doc` échoue sinon). Ces textes servent AUSSI à l'aide de la touche `h` de la console (`trxstation/console_help.json`, fabriqué par le même script) : un NOUVEAU MENU doit avoir sa section `[menus.<méthode>]` (role, quand, modifie, admin), sinon la fabrication et les tests échouent. Publié par `.github/workflows/pages.yml` (https://bob56fr.github.io/openRemoteTRX/console/, une copie par version) ; bloc WordPress `docs/wordpress/console-iframe.html`. Contenu public : exemples génériques, jamais d'IP, de nom de machine ni de clé.
- Avant d'écrire du code qui touche au PTT : relire la section « Règles de sécurité d'émission ».
- PROTOCOLE CLIENT : toute commande, tout champ ou message ajouté ou changé met à jour `docs/protocole.md`, les exemples `tests/protocol/` (les tests l'imposent), `hello.features` si la fonction est facultative, et `docs/parite-web-android.md`.
