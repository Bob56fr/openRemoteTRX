# Inventaire des erreurs existantes (lot M1, partie 1)

Partie 1 faite le 2026-11-11 sur le code de la station 0.122.0 ; décisions de l'utilisateur appliquées à l'étape 168 (station 0.126.0 : origines recalées sur ce code). SANS changer son comportement. Référence : `trxstation/errors/catalog.yaml` (cahier des charges du monitoring inter-stations `docs/cdc-monitoring.md`, § 7). Les messages du code seront remplacés par les codes dans la 2e partie du lot M1. Pages publiques (une par code, français et anglais) : https://bob56fr.github.io/openRemoteTRX/erreurs/ (`scripts/build_errors_doc.py`, étape 172).

## Chiffres

- 388 codes ORT, dont 6 abandonnés (`deprecated`) et 12 écrits d'après le cahier (ORT-6501 à 6508, ORT-7001 à 7030) ; 5 codes AND (application Android, `AND-catalog.yaml`) ;
- 444 situations relevées dans le code, regroupées quand la cause est la même (68 doublons fusionnés, liste plus bas) ;
- 1427 origines `fichier:ligne` (toutes vérifiées : le fichier existe et la ligne aussi) ;
- 165 questions relevées pendant l'inventaire, toutes tranchées (décisions ci-dessous, détail en fin de page).

Périmètre : `raise` métier, `except` qui journalise, alerte, refuse ou bascule, `log.error/warning/critical`, alertes ntfy du superviseur et de la passerelle, refus renvoyés aux clients (codes machine du protocole), messages de l'assistant `trx-setup`, de TRX Console et des scripts d'installation (`debian/install.sh`, `releases.sh`, `compiler-hamlib.sh`, `windows/installer.ps1`), échecs CAT / Hamlib, audio, réseau, PTT, scénarios de panne du superviseur. Écartés (comptés en fin de page) : erreurs de programmation, `except` silencieux d'un cas normal, annulations asyncio, outils de développement. Le code de la page web (JS) et de l'application Android (Kotlin) n'est PAS inventorié : seuls les codes machine qu'ils reçoivent le sont.

## Choix de la première partie (acceptés)

1. **Emplacement** : `trxstation/errors/` (catalog.yaml, modules.yaml, codes.py, catalog.json, emit.py), installé avec la station.
2. **PyYAML** dans l'extra `dev` seulement : la station lit `catalog.json`, fabriqué par `scripts/build_errors.py`.
3. **`depuis_version`** : 0.123.0 pour la première série, la version d'arrivée pour les suivantes (0.126.0).
4. **Plage 6500** : ORT-6501 à 6508 génériques (cahier), bus des modules 6511-6528, Breizh Audio Box 6531-6541, FreeDV 6561-6567.
5. **Sous-blocs** :
   - 1500 : mises à jour ;
   - 2300 : spectre HF ;
   - 2600 : essais trx-hwtest ;
   - 2700 : qualification ;
   - 4100 : accès ;
   - 4300 : visiteurs ;
   - 4500 : sonde réseau ;
   - 5100 : refus de prise d'émission ;
   - 5500 : TOS ;
   - 5800 : réglages de sécurité ;
   - 5900 : essais de panne ;
   - 9100 : profils et secrets ;
   - 9200 : mises en page ;
   - 9300 : installation ;
   - 9500 : outils des journaux Android ;
   - 9700 : outils.
6. **ORT-7001 à 7030** : `prevu: true` (monitor inter-stations à venir).
7. **Comportement décrit** : celui du code actuel.

## Décisions de l'utilisateur (2026-11-11) et suites données (station 0.126.0, étape 168)

1. **Spectre et micro du poste** : une émission venue du poste n'est plus coupée.
   - `spectrum/service.py` regarde, port B refermé, qui tient l'émission :
     - le port B (le PTT retombe) : coupure et spectre désactivé, comme avant ;
     - le poste (le PTT reste actif, donc le micro du poste) : AUCUNE coupure, nouvel essai plus tard (ORT-5004, passé en « info ») ; c'est la règle « opérateur sur place » de la passerelle qui s'applique ;
     - le PTT devient illisible : c'est un doute, donc coupure (`ptt_unknown`).
   - Tests : `test_spectrum_service.py`.
2. **TOT** : passerelle 90 s = ORT-5001, TOT absolu 135 s du superviseur = ORT-5024.
3. **ORT-5010** reste critique.
4. **Priorités ntfy** : 5 pour ORT-5020, 5024, 5025, 5026 et 5027 ; 4 pour le mode sûr (ORT-8008). Elles s'appliqueront quand les alertes passeront par le catalogue (partie 2b).
5. **ORT-5003** : pas d'alerte ntfy.
6. **ORT-8002** reste la boucle d'arrêts d'un module (plus de 5 en 300 s), seule boucle comptée aujourd'hui. Les relances de la passerelle restent bornées par l'échelle du superviseur (relances, rigctld, reset USB, reboots limités, puis mode sûr).
7. **Seuils** (`config.py`, `station.example.toml`) :
   - disque 70 % (`[supervisor] disk_alert_pct`) ;
   - processeur 70 °C (`temp_alert_c`) ;
   - pertes réseau 5 % (`[netprobe] loss_alert_pct`) ;
   - surcharge des visiteurs 70 °C (`[access] overload_temp_c`, retour sous 60 °C).

   Une station.toml DÉJÀ écrite garde ses anciennes valeurs : à corriger à la main (menu 14). Le bargraph de la page et de l'application (`hostinfo.LIMITS`) n'est pas changé : ce sont des seuils d'affichage.
8. **ORT-2104** (délai CAT) : pas de changement. Une lecture qui n'aboutit pas est aujourd'hui refermée et réessayée en silence. Le cahier imaginait un compteur sur 5 min avec alerte et relance de rigctld, ce que le code ne fait pas. Les deux causes (délai dépassé, connexion fermée par rigctld) seront distinguées quand le code émettra ses événements.
9. **ORT-2001** : la fusion est acceptée.
10. **Passerelle sans carte son** : pas de changement pour l'instant. Pour ne plus quitter, la passerelle devrait tourner sans son et REFUSER l'émission, avec un nouveau refus dans le protocole, la page et l'application. Ce chantier est à décider à part.
11. **Xruns (ORT-3010)** : `gateway/audio/xruns.py` relève les décrochages et les trames perdues de la capture toutes les 30 s. Au-delà de 50 en 5 min, il émet ORT-3010 au journal, une fois par 30 min, sans ntfy. Tests : `test_audio_xruns.py`.
12. **Tailscale** : aucun code. Aucun VPN n'est imposé (accès distant au choix de l'utilisateur) ; la mention de CLAUDE.md est corrigée.
13. **Breizh arrêté** : `breizh/link.py` émet ORT-6501 au journal une fois, après 60 s sans aucune réponse aux HELLO, sans ntfy ni message aux clients. Test : `test_breizh_route.py`.
14. **Pas d'alerte ntfy** pour FreeDV, le cluster, le relais de présence et le SELCALL en réception (FreeDV n'est pas mûr).
15. **Battement des modules internes** : pas encore ; ORT-6504 reste pour les modules extérieurs (Breizh, FreeDV).
16. **Fichier de clés de présence abîmé** : le module ne plante plus et n'écrase jamais les clés. Il émet ORT-6920, publie le problème (ligne « Présence » de trx-monitor) et attend. En passant, un défaut a été corrigé : `await a if c else b` n'attendait pas `b`, et sans bus le module rendait la main tout de suite. Test : `test_presence_module.py`.
17. **Installation** : deux codes, ORT-9308 (modules Python impossibles) et ORT-9311 (EMPREINTE différente, critique). Les scripts d'installation devront distinguer les deux messages de pip (partie 2b).
18. **Présence** : deux codes, ORT-6908 et 6909 (refus ordinaires) et ORT-6923 (signature invalide, attaque possible).
19. **CAT `invalid`** : deux codes, ORT-2012 (fonction non gérée) et ORT-2013 (valeur hors plage). Le code machine `invalid` du protocole reste le même ; l'événement les distinguera (partie 2b).
20. **Refus d'émission dus au poste** : gardés en 5100.
21. **Application Android** : préfixe AND (`AND-catalog.yaml`, registre `modules.yaml`). AND-1001 à 1005 remplacent ORT-9504 à 9508 (`deprecated`). Les erreurs de l'OUTIL trx-journal-android (ORT-9501 à 9503) restent ORT.
22. **Mémoires, réglages, mises en page** : rangement gardé (1000 et 9200).
23. **Affichages** : fusionnés avec le code de la panne affichée ; la console affichera le code d'origine (partie 2b).
24. **Gravités selon l'outil** : gardées. Un système non pris en charge bloque l'installation (ORT-1011) ; le disque insuffisant à l'installation (ORT-1012) reste distinct du disque plein en service (ORT-1001).
25. **Clé de signature des versions** (ORT-1511) : gardée, utile au mainteneur.
26. **Décodeurs FreeDV** : restent en ORT-65xx.
27. **Erreurs inattendues** : une par domaine.
   - Nouveaux codes : ORT-4018 (session d'un client), ORT-4509 (sonde réseau, `netprobe_error`), ORT-5028 (bips de fin), ORT-6541 (Breizh), ORT-6567 (FreeDV).
   - Rattachements : `friends_error` à ORT-6922, la surveillance des accès à ORT-8018.
   - ORT-8019 est `deprecated`.

## Tableau code → origines

Gravité et action automatique : comportement ACTUEL du code. `codes machine` : codes déjà émis (refus, raisons de coupure, types d'alerte).


### 1000–1999 : Système

| Code | Gravité | Titre | ntfy | Action | Codes machine | Origines |
| --- | --- | --- | --- | --- | --- | --- |
| ORT-1001 | avert. | Disque presque plein | oui (3) | aucune | `disk_high` | `trxstation/supervisor/core.py:292-294` |
| ORT-1002 | avert. | Mémoire de la station presque pleine | oui (3) | aucune | `memory_high` | `trxstation/supervisor/core.py:290-291` |
| ORT-1003 | avert. | Raspberry Pi ralenti | oui (3) | aucune | `pi_throttled` | `trxstation/supervisor/core.py:295-296`, `trxstation/hostinfo.py:39`, `trxstation/hostinfo.py:140` |
| ORT-1004 | avert. | Identifiant de station indisponible | non | aucune |  | `trxstation/gateway/main.py:261-260` |
| ORT-1005 | erreur | Fichier d'état de la passerelle non écrit | non | nouvel_essai |  | `trxstation/gateway/status/publisher.py:89`, `trxstation/gateway/status/publisher.py:91`, `trxstation/status.py:87` |
| ORT-1006 | avert. | Machine de la station chargée | non | aucune | `warn`, `bad` | `trxstation/hostinfo.py:35`, `trxstation/hostinfo.py:163-177`, `trxstation/hostinfo.py:370` |
| ORT-1007 | avert. | État de la mesure de TOS non enregistré ou illisible | non | aucune |  | `trxstation/swr/store.py:79`, `trxstation/swr/store.py:93` |
| ORT-1008 | erreur | Réglage non enregistré sur la station | non | refus | `storage_error`, `layout_storage_error`, `beeps_storage_error`, `breizh_storage_error`, `voice_profiles_storage_error`, `report_storage_error`, `freedv_storage_error` | `trxstation/gateway/api/session.py:344`, `trxstation/gateway/api/session.py:380`, `trxstation/gateway/api/session.py:660`, `trxstation/gateway/api/session.py:325`, `trxstation/gateway/api/session.py:723`, `trxstation/gateway/voice_profiles.py:121`, `trxstation/gateway/bugreports.py:70`, `trxstation/freedv/service.py:123`, `trxstation/gateway/api/access.py:90`, `trxstation/gateway/memories.py:116`, `trxstation/gateway/api/session.py:344`, `trxstation/gateway/api/session.py:351`, `trxstation/layout/store.py:88`, `trxstation/layout/store.py:101`, `trxstation/layout/store.py:121`, `trxstation/gateway/api/session.py:380` |
| ORT-1009 | avert. | Journal de la station non écrit | non | aucune |  | `trxstation/breizh/store.py:116`, `trxstation/netprobe/store.py:62`, `trxstation/netprobe/store.py:156`, `trxstation/netprobe/store.py:190`, `trxstation/netprobe/store.py:205`, `trxstation/netprobe/store.py:217` |
| ORT-1010 | avert. | Température du processeur élevée | oui (3) | aucune | `cpu_hot` | `trxstation/supervisor/core.py:262-264`, `trxstation/cpu_temp.py:85`, `trxstation/diagnostics.py:186`, `trxstation/monitor/model.py:219` |
| ORT-1011 | erreur | Système d'exploitation non pris en charge | non | refus |  | `debian/install.sh:289`, `debian/install.sh:287`, `trxstation/diagnostics.py:169`, `trxstation/diagnostics.py:171`, `windows/installer.ps1:231`, `windows/installer.ps1:233` |
| ORT-1012 | erreur | Espace disque insuffisant | non | refus |  | `trxstation/diagnostics.py:178`, `debian/install.sh:315`, `windows/installer.ps1:269` |
| ORT-1013 | info | Température du processeur illisible | non | aucune |  | `debian/install.sh:495` |
| ORT-1014 | avert. | Matériel en dessous du minimum conseillé | non | aucune |  | `debian/install.sh:300`, `debian/install.sh:303`, `debian/install.sh:312` |
| ORT-1015 | avert. | Alimentation du Raspberry Pi trop faible | non | aucune |  | `debian/install.sh:306` |
| ORT-1020 | erreur | Horloge de la station refusée par le relais | non | nouvel_essai | `clock` | `trxstation/presence/engine.py:396` |
| ORT-1501 | avert. | Recherche de mise à jour impossible | non | nouvel_essai |  | `trxstation/update/check.py:245`, `trxstation/update/check.py:253`, `trxstation/update/check.py:254`, `trxstation/update/check.py:257`, `trxstation/update/check.py:259`, `trxstation/update/check.py:177`, `trxstation/update/check.py:180`, `trxstation/update/check.py:329`, `trxstation/update/check.py:367`, `trxstation/diagnostics.py:597`, `trxstation/console.py:442`, `trxstation/console.py:452`, `trxstation/update/apply.py:229` |
| ORT-1502 | avert. | Dernière recherche de mise à jour trop ancienne | non | aucune |  | `trxstation/diagnostics.py:601`, `trxstation/update/check.py:364` |
| ORT-1503 | info | Nouvelle version disponible | non | aucune |  | `trxstation/update/check.py:369`, `trxstation/diagnostics.py:605`, `trxstation/tray/status.py:205` |
| ORT-1504 | avert. | Aucune clé de signature connue | non | refus |  | `trxstation/diagnostics.py:582`, `trxstation/update/signing.py:132` |
| ORT-1505 | erreur | Mise à jour refusée : émission en cours ou état inconnu | non | refus | `EXIT_TX` | `trxstation/update/apply.py:78`, `trxstation/update/apply.py:81`, `trxstation/update/apply.py:83`, `trxstation/update/apply.py:85`, `trxstation/update/apply.py:87`, `trxstation/update/apply.py:216`, `trxstation/update/apply.py:364`, `trxstation/console.py:1735` |
| ORT-1506 | CRITIQUE | Signature du paquet refusée | non | refus | `EXIT_REFUSED` | `trxstation/update/apply.py:248`, `trxstation/update/apply.py:284`, `trxstation/update/signing.py:64`, `trxstation/update/signing.py:66`, `trxstation/update/signing.py:76`, `trxstation/update/signing.py:78`, `trxstation/update/signing.py:80`, `trxstation/update/signing.py:98`, `trxstation/update/signing.py:103`, `trxstation/update/signing.py:108`, `trxstation/update/signing.py:113`, `trxstation/update/signing.py:117`, `trxstation/update/signing.py:119`, `trxstation/update/signing.py:136`, `trxstation/update/signing.py:145`, `trxstation/update/signing.py:147`, `trxstation/update/signing.py:149`, `trxstation/update/signing.py:153`, `trxstation/update/signing.py:155` |
| ORT-1507 | CRITIQUE | Contenu du paquet refusé | non | refus | `EXIT_REFUSED` | `trxstation/update/apply.py:98`, `trxstation/update/apply.py:106`, `trxstation/update/apply.py:109`, `trxstation/update/apply.py:111`, `trxstation/update/apply.py:114`, `trxstation/update/apply.py:116`, `trxstation/update/apply.py:120`, `trxstation/update/apply.py:124`, `trxstation/update/apply.py:126`, `trxstation/update/apply.py:366` |
| ORT-1508 | erreur | Téléchargement de la mise à jour impossible | non | refus | `EXIT_REFUSED` | `trxstation/update/apply.py:305`, `trxstation/update/apply.py:242`, `trxstation/update/apply.py:233` |
| ORT-1509 | avert. | Paquet déposé refusé ou à confirmer | non | refus | `EXIT_REFUSED` | `trxstation/update/apply.py:266`, `trxstation/update/apply.py:268`, `trxstation/update/apply.py:270`, `trxstation/update/apply.py:289`, `trxstation/update/apply.py:287`, `trxstation/console.py:532`, `trxstation/console.py:547`, `trxstation/console.py:556` |
| ORT-1510 | erreur | Installation de la nouvelle version échouée | non | refus | `EXIT_FAILED` | `trxstation/update/apply.py:255`, `trxstation/update/apply.py:295`, `trxstation/update/apply.py:221`, `trxstation/update/apply.py:320`, `trxstation/update/apply.py:325`, `trxstation/console.py:517`, `trxstation/console.py:1738`, `trxstation/update/apply.py:347` |
| ORT-1511 | erreur | Clé de signature des versions inutilisable (développement) | non | refus |  | `trxstation/update/keyfile.py:49`, `trxstation/update/keyfile.py:58`, `trxstation/update/keyfile.py:78`, `trxstation/update/keyfile.py:82`, `trxstation/update/keyfile.py:84`, `trxstation/update/keyfile.py:93` |

### 2000–2999 : CAT, Hamlib, rigctld, port série

| Code | Gravité | Titre | ntfy | Action | Codes machine | Origines |
| --- | --- | --- | --- | --- | --- | --- |
| ORT-2001 | CRITIQUE | Port série du poste introuvable | non | aucune | `usb_missing` | `trxstation/diagnostics.py:302`, `trxstation/diagnostics.py:290`, `trxstation/supervisor/core.py:253-255`, `trxstation/supervisor/core.py:255` |
| ORT-2002 | erreur | rigctld ne démarre pas | non | refus |  | `trxstation/devtools/hwtest.py:839`, `trxstation/qualif/main.py:93`, `trxstation/setup_wizard.py:123`, `trxstation/setup_wizard.py:128`, `trxstation/setup_wizard.py:132`, `trxstation/setup_wizard.py:442` |
| ORT-2003 | erreur | Hamlib introuvable (rigctld ou rigctl) | non | refus |  | `trxstation/hamlib.py:47`, `trxstation/run_rigctld.py:34`, `trxstation/gateway/cat/capabilities.py:177`, `trxstation/devtools/hwtest.py:832`, `trxstation/qualif/main.py:86`, `trxstation/hamlib.py:47`, `trxstation/supervisor/main.py:135-137`, `trxstation/setup_wizard.py:64`, `trxstation/setup_wizard.py:75`, `trxstation/setup_wizard.py:115`, `trxstation/setup_wizard.py:82`, `trxstation/diagnostics.py:209`, `windows/installer.ps1:250`, `windows/installer.ps1:259`, `windows/installer.ps1:263` |
| ORT-2004 | info | rigctld non lancé (outil en --no-spawn) | non | refus |  | `trxstation/devtools/hwtest.py:823`, `trxstation/qualif/main.py:80` |
| ORT-2005 | erreur | rigctld injoignable | oui (3) | nouvel_essai | `rigctld_down` | `trxstation/gateway/cat/client.py:82`, `trxstation/gateway/cat/client.py:98`, `trxstation/gateway/cat/link.py:124`, `trxstation/devtools/hwtest.py:223`, `trxstation/qualif/trace.py:78`, `trxstation/supervisor/core.py:246`, `trxstation/supervisor/core.py:245-246`, `trxstation/supervisor/rigctl.py:57`, `trxstation/supervisor/rigctl.py:63`, `trxstation/supervisor/rigctl.py:68`, `trxstation/monitor/model.py:189`, `trxstation/monitor/model.py:191`, `trxstation/tray/status.py:171` |
| ORT-2006 | avert. | Connexion fermée par rigctld | non | nouvel_essai |  | `trxstation/gateway/cat/client.py:108`, `trxstation/gateway/cat/client.py:128`, `trxstation/gateway/cat/link.py:124` |
| ORT-2007 | erreur | Réponse de rigctld désynchronisée | non | nouvel_essai |  | `trxstation/gateway/cat/client.py:114`, `trxstation/gateway/cat/client.py:127` |
| ORT-2008 | avert. | Réponse du poste illisible | non | aucune |  | `trxstation/gateway/cat/client.py:141`, `trxstation/gateway/cat/client.py:151`, `trxstation/gateway/cat/client.py:160`, `trxstation/gateway/cat/client.py:196`, `trxstation/gateway/cat/client.py:211`, `trxstation/gateway/cat/link.py:171` |
| ORT-2009 | info | Lecture facultative abandonnée pour ce poste | non | aucune |  | `trxstation/gateway/cat/link.py:245`, `trxstation/gateway/cat/link.py:160`, `trxstation/gateway/cat/link.py:155` |
| ORT-2010 | erreur | Le poste ne répond pas (rigctld répond) | non | aucune |  | `trxstation/gateway/cat/link.py:171`, `trxstation/gateway/cat/link.py:158`, `trxstation/devtools/hwtest.py:225` |
| ORT-2011 | avert. | Commande refusée par le poste (RPRT) | non | refus | `rig_error` | `trxstation/gateway/cat/client.py:61`, `trxstation/gateway/cat/client.py:116`, `trxstation/gateway/api/session.py:744`, `trxstation/modules/gateway_bridge.py:147`, `trxstation/qualif/runner.py:62` |
| ORT-2012 | info | Mode ou fonction non géré par ce poste | non | refus | `invalid` | `trxstation/gateway/cat/link.py:280`, `trxstation/gateway/cat/link.py:332`, `trxstation/gateway/api/session.py:742` |
| ORT-2013 | info | Valeur hors de la plage du poste | non | refus | `invalid` | `trxstation/gateway/cat/link.py:308`, `trxstation/gateway/cat/link.py:321`, `trxstation/gateway/cat/client.py:295`, `trxstation/gateway/api/session.py:742` |
| ORT-2014 | avert. | Capacités du poste indisponibles (dump_caps) | non | repli_jeu_minimal |  | `trxstation/gateway/cat/capabilities.py:182`, `trxstation/gateway/cat/capabilities.py:184`, `trxstation/gateway/main.py:70`, `trxstation/devtools/hwtest.py:180`, `trxstation/qualif/main.py:158`, `trxstation/gateway/main.py:70` |
| ORT-2015 | avert. | Poste éteint ou débranché | oui (3) | aucune | `rig_absent` | `trxstation/supervisor/core.py:258`, `trxstation/ports.py:57`, `trxstation/supervisor/core.py:257-260` |
| ORT-2016 | avert. | Port du poste du profil absent | non | aucune |  | `trxstation/console.py:740` |
| ORT-2017 | erreur | Le poste répond mal au test de liaison | non | refus |  | `trxstation/setup_wizard.py:150` |
| ORT-2018 | erreur | Modèle du poste inconnu de ce Hamlib | non | aucune |  | `trxstation/diagnostics.py:295` |
| ORT-2019 | avert. | Service système qui perturbe le port série | non | aucune |  | `trxstation/diagnostics.py:315`, `trxstation/diagnostics.py:320`, `debian/install.sh:472`, `debian/install.sh:481` |
| ORT-2020 | avert. | Tension d'alimentation du poste basse | non | aucune |  | `trxstation/tray/status.py:190` |
| ORT-2021 | erreur | Compilation de Hamlib impossible | non | refus |  | `debian/compiler-hamlib.sh:48`, `debian/compiler-hamlib.sh:50`, `debian/compiler-hamlib.sh:60`, `debian/compiler-hamlib.sh:61`, `debian/compiler-hamlib.sh:62`, `debian/compiler-hamlib.sh:67` |
| ORT-2022 | avert. | Un autre rigctld passe avant celui compilé | non | aucune |  | `debian/compiler-hamlib.sh:70` |
| ORT-2104 | erreur | Délai de réponse CAT dépassé | non | nouvel_essai |  | `trxstation/gateway/cat/client.py:106`, `trxstation/gateway/cat/client.py:132`, `trxstation/gateway/cat/link.py:124` |
| ORT-2200 | avert. | Version de Hamlib plus ancienne que la version qualifiée | non | aucune |  | `trxstation/qualif/sheet.py:222`, `trxstation/diagnostics.py:216`, `trxstation/diagnostics.py:218`, `debian/install.sh:368`, `debian/install.sh:364`, `debian/install.sh:361` |
| ORT-2301 | avert. | Second port du poste impossible à ouvrir (spectre HF) | non | repli_mode_normal | `open_failed` | `trxstation/spectrum/probe.py:37`, `trxstation/spectrum/service.py:384`, `trxstation/spectrum/service.py:139`, `trxstation/devtools/hwtest.py:443` |
| ORT-2302 | avert. | Aucune réponse CI-V sur le second port | non | repli_mode_normal | `no_answer` | `trxstation/spectrum/probe.py:39`, `trxstation/spectrum/probe.py:167`, `trxstation/spectrum/probe.py:175`, `trxstation/spectrum/service.py:451` |
| ORT-2303 | avert. | Adresse CI-V du poste changée (second port) | non | repli_mode_normal | `wrong_address` | `trxstation/spectrum/probe.py:41`, `trxstation/spectrum/probe.py:166` |
| ORT-2304 | avert. | Le poste ne fournit pas le spectre par le CI-V | non | repli_mode_normal | `no_scope` | `trxstation/spectrum/probe.py:43`, `trxstation/spectrum/probe.py:170`, `trxstation/spectrum/service.py:408`, `trxstation/devtools/hwtest.py:454` |
| ORT-2305 | erreur | Le second port n'est pas celui du même poste | non | repli_mode_normal | `other_rig` | `trxstation/spectrum/probe.py:44`, `trxstation/spectrum/probe.py:181` |
| ORT-2306 | avert. | État d'émission illisible après l'ouverture du second port | non | repli_mode_normal | `ptt_unknown` | `trxstation/spectrum/probe.py:47`, `trxstation/spectrum/service.py:330` |
| ORT-2307 | avert. | Plus aucune donnée du spectre HF | non | repli_mode_normal | `silent` | `trxstation/spectrum/probe.py:50`, `trxstation/spectrum/service.py:440`, `trxstation/devtools/hwtest.py:480` |
| ORT-2308 | avert. | Second port du poste perdu | non | repli_mode_normal | `port_lost` | `trxstation/spectrum/probe.py:52`, `trxstation/spectrum/service.py:412` |
| ORT-2309 | erreur | Erreur interne du spectre HF | non | repli_mode_normal | `internal` | `trxstation/spectrum/probe.py:54`, `trxstation/spectrum/service.py:350`, `trxstation/spectrum/service.py:107` |
| ORT-2310 | info | Réglage du spectre ou du filtre FIL refusé | non | refus | `spectrum_refused` | `trxstation/spectrum/service.py:52`, `trxstation/spectrum/service.py:177`, `trxstation/spectrum/service.py:179`, `trxstation/spectrum/service.py:186`, `trxstation/spectrum/service.py:190`, `trxstation/spectrum/service.py:258`, `trxstation/spectrum/service.py:289`, `trxstation/gateway/api/session.py:648`, `trxstation/gateway/api/session.py:673` |
| ORT-2311 | erreur | Réglage du spectre HF incompatible avec le poste | non | refus |  | `trxstation/config.py:634`, `trxstation/config.py:642`, `trxstation/config.py:644`, `trxstation/config.py:870`, `trxstation/setup_wizard.py:176` |
| ORT-2312 | erreur | Vérification du second port CI-V impossible | non | refus |  | `trxstation/setup_wizard.py:180`, `trxstation/setup_wizard.py:200`, `trxstation/setup_wizard.py:204`, `trxstation/setup_wizard.py:206`, `trxstation/setup_wizard.py:217`, `trxstation/setup_wizard.py:223`, `trxstation/setup_wizard.py:264`, `trxstation/setup_wizard.py:873` |
| ORT-2313 | erreur | Spectre HF en panne (affichage) | non | aucune |  | `trxstation/diagnostics.py:458`, `trxstation/monitor/model.py:245`, `trxstation/tray/status.py:196` |
| ORT-2601 | erreur | Essai : fréquence non suivie par le poste | non | aucune | `freq_rw` | `trxstation/qualif/runner.py:245`, `trxstation/devtools/hwtest.py:371`, `trxstation/devtools/hwtest.py:372`, `trxstation/devtools/hwtest.py:516`, `trxstation/devtools/hwtest.py:519` |
| ORT-2602 | erreur | Essai : mode non suivi par le poste | non | aucune | `mode_rw` | `trxstation/qualif/runner.py:256`, `trxstation/qualif/runner.py:263`, `trxstation/qualif/runner.py:265`, `trxstation/devtools/hwtest.py:543`, `trxstation/devtools/hwtest.py:548`, `trxstation/devtools/hwtest.py:563` |
| ORT-2603 | avert. | Essai : largeurs de filtre non suivies | non | aucune | `filters` | `trxstation/qualif/runner.py:301`, `trxstation/devtools/hwtest.py:389`, `trxstation/devtools/hwtest.py:404`, `trxstation/devtools/hwtest.py:417` |
| ORT-2604 | avert. | Essai : fonction ou niveau du poste en échec | non | aucune |  | `trxstation/qualif/runner.py:310`, `trxstation/qualif/runner.py:328`, `trxstation/qualif/runner.py:335`, `trxstation/qualif/runner.py:342`, `trxstation/qualif/runner.py:349`, `trxstation/qualif/runner.py:387`, `trxstation/qualif/runner.py:394`, `trxstation/qualif/runner.py:145` |
| ORT-2605 | erreur | Essai : endurance de la liaison CAT en échec | non | aucune | `cat_endurance` | `trxstation/qualif/runner.py:416`, `trxstation/qualif/runner.py:430` |
| ORT-2606 | avert. | Essai : pas de reprise après débranchement USB | non | aucune | `usb_replug` | `trxstation/qualif/runner.py:510`, `trxstation/qualif/runner.py:515` |
| ORT-2607 | avert. | Essai : état d'origine du poste non rétabli | non | aucune |  | `trxstation/qualif/runner.py:186`, `trxstation/devtools/hwtest.py:410`, `trxstation/devtools/hwtest.py:578`, `trxstation/devtools/hwtest.py:353` |
| ORT-2608 | erreur | Essai : coupure faite sur le poste non vue par la station | non | aucune |  | `trxstation/devtools/hwtest.py:746`, `trxstation/devtools/hwtest.py:748` |
| ORT-2701 | avert. | Qualification : socle en échec, poste refusé | non | aucune |  | `trxstation/qualif/results.py:63`, `trxstation/qualif/main.py:70`, `trxstation/qualif/results.py:149` |
| ORT-2702 | info | Qualification incomplète | non | aucune |  | `trxstation/qualif/results.py:65`, `trxstation/qualif/runner.py:99`, `trxstation/qualif/runner.py:546`, `trxstation/devtools/hwtest.py:765`, `trxstation/qualif/main.py:116` |
| ORT-2703 | info | Qualification : afficheur ou son non confirmés par l'opérateur | non | aucune |  | `trxstation/qualif/runner.py:442`, `trxstation/qualif/runner.py:457`, `trxstation/qualif/runner.py:462` |
| ORT-2704 | info | Poste ou firmware non qualifié | non | aucune |  | `trxstation/qualif/sheet.py:214`, `trxstation/qualif/sheet.py:220`, `trxstation/qualif/sheet.py:224` |

### 3000–3999 : Audio

| Code | Gravité | Titre | ntfy | Action | Codes machine | Origines |
| --- | --- | --- | --- | --- | --- | --- |
| ORT-3001 | CRITIQUE | Périphérique audio du poste absent | non | arreter_passerelle |  | `trxstation/audio_devices.py:130`, `trxstation/gateway/audio/devices.py:212`, `trxstation/gateway/audio/devices.py:272`, `trxstation/gateway/main.py:321`, `trxstation/gateway/main.py:72`, `trxstation/gateway/main.py:321-321`, `trxstation/diagnostics.py:347`, `trxstation/diagnostics.py:330` |
| ORT-3002 | avert. | Essai : son reçu absent, muet ou saturé | non | aucune | `audio_rx` | `trxstation/devtools/hwtest.py:261`, `trxstation/devtools/hwtest.py:265`, `trxstation/devtools/hwtest.py:267`, `trxstation/devtools/hwtest.py:186` |
| ORT-3003 | erreur | Essai : audio d'émission non transmis ou ROS élevé | non | retour_rx | `audio_tx` | `trxstation/devtools/hwtest.py:641`, `trxstation/devtools/hwtest.py:643` |
| ORT-3004 | CRITIQUE | Ouverture du périphérique audio impossible | non | arreter_passerelle |  | `trxstation/gateway/audio/devices.py:235`, `trxstation/gateway/audio/devices.py:285`, `trxstation/gateway/main.py:321` |
| ORT-3005 | avert. | Son d'émission en retard ou haché | non | aucune |  | `trxstation/gateway/audio/ring.py:40`, `trxstation/gateway/audio/ring.py:29`, `trxstation/gateway/audio/pipeline.py:62`, `trxstation/netprobe/probe.py:51` |
| ORT-3006 | info | Client trop lent pour le son reçu | non | aucune |  | `trxstation/gateway/audio/hub.py:63`, `trxstation/gateway/audio/pipeline.py:57` |
| ORT-3007 | erreur | Traitement du son reçu en erreur | non | repli_son_brut |  | `trxstation/gateway/audio/hub.py:58` |
| ORT-3008 | erreur | Vidage du tampon d'émission impossible à la coupure | non | aucune |  | `trxstation/gateway/audio/beeps.py:294` |
| ORT-3009 | avert. | Cartes son de la station non choisies | non | aucune |  | `trxstation/config.py:865`, `trxstation/migrate.py:5` |
| ORT-3010 | avert. | Sous-débits audio fréquents (xruns) | non | aucune |  | `trxstation/gateway/audio/devices.py:224`, `trxstation/gateway/audio/devices.py:219`, `trxstation/gateway/audio/xruns.py:55` |
| ORT-3011 | avert. | Carte son du poste occupée par le son du bureau | non | aucune |  | `trxstation/diagnostics.py:352`, `trxstation/diagnostics.py:366`, `trxstation/diagnostics.py:370` |

### 4000–4999 : Réseau, accès, clients

| Code | Gravité | Titre | ntfy | Action | Codes machine | Origines |
| --- | --- | --- | --- | --- | --- | --- |
| ORT-4001 | avert. | Pertes réseau d'un client élevées | oui (3) | aucune |  | `trxstation/netprobe/probe.py:416`, `trxstation/netprobe/probe.py:182` |
| ORT-4002 | avert. | Demande de déconnexion d'un visiteur ignorée | non | aucune |  | `trxstation/gateway/access_watch.py:86`, `trxstation/gateway/access_watch.py:91`, `trxstation/gateway/access_watch.py:96`, `trxstation/gateway/access_watch.py:99`, `trxstation/gateway/access_watch.py:124` |
| ORT-4003 | info | Demande de connexion mal formée | non | refus | `bad_request` | `trxstation/gateway/api/server.py:52`, `trxstation/gateway/api/server.py:54`, `trxstation/gateway/api/server.py:58` |
| ORT-4004 | avert. | Connexion refusée : identifiant ou mot de passe | non | refus | `unauthorized` | `trxstation/gateway/api/server.py:65`, `trxstation/gateway/api/server.py:66`, `trxstation/gateway/api/auth.py:105`, `trxstation/gateway/api/auth.py:113` |
| ORT-4005 | avert. | Station occupée : trop de connexions | non | refus | `busy`, `operators_full` | `trxstation/gateway/api/webrtc.py:170`, `trxstation/gateway/api/server.py:76`, `trxstation/gateway/api/access.py:184`, `trxstation/gateway/api/server.py:73` |
| ORT-4006 | erreur | Erreur de la station pendant la connexion | non | refus | `server_error` | `trxstation/gateway/api/server.py:78`, `trxstation/gateway/api/server.py:79`, `trxstation/gateway/api/webrtc.py:177` |
| ORT-4007 | avert. | Compte désactivé ou expiré | non | refus | `account_disabled`, `account_expired` | `trxstation/gateway/api/access.py:149`, `trxstation/gateway/api/access.py:151`, `trxstation/gateway/api/access.py:166`, `trxstation/gateway/api/access.py:205`, `trxstation/gateway/api/webrtc.py:286` |
| ORT-4008 | info | Compte modifié : reconnexion demandée | non | refus | `account_changed` | `trxstation/gateway/api/access.py:147`, `trxstation/gateway/api/access.py:153`, `trxstation/gateway/api/session.py:508` |
| ORT-4009 | avert. | Connexion WebRTC jamais établie | non | refus |  | `trxstation/gateway/api/webrtc.py:278` |
| ORT-4010 | info | Message du client illisible | non | refus | `too_large`, `bad_json`, `bad_message` | `trxstation/gateway/api/protocol.py:130`, `trxstation/gateway/api/protocol.py:134`, `trxstation/gateway/api/protocol.py:136`, `trxstation/gateway/api/session.py:582` |
| ORT-4011 | info | Commande inconnue de la station | non | refus | `unknown_command` | `trxstation/gateway/api/protocol.py:139`, `trxstation/gateway/api/session.py:582` |
| ORT-4012 | info | Paramètres de commande refusés | non | refus | `invalid_params`, `invalid`, `voice_profile_refused`, `layout_invalid` | `trxstation/gateway/api/protocol.py:114`, `trxstation/netprobe/report.py:41`, `trxstation/gateway/api/session.py:742`, `trxstation/gateway/api/session.py:496`, `trxstation/gateway/api/session.py:726`, `trxstation/gateway/voice_profiles.py:96`, `trxstation/gateway/api/session.py:377` |
| ORT-4013 | avert. | Client trop bavard : messages ignorés | non | refus | `rate_limited` | `trxstation/gateway/api/session.py:574` |
| ORT-4014 | info | Fonction absente de cette station | non | refus | `*_unavailable` | `trxstation/gateway/api/session.py:269`, `trxstation/gateway/api/session.py:295`, `trxstation/gateway/api/session.py:312`, `trxstation/gateway/api/session.py:336`, `trxstation/gateway/api/session.py:367`, `trxstation/gateway/api/session.py:390`, `trxstation/gateway/api/session.py:466`, `trxstation/gateway/api/session.py:532`, `trxstation/gateway/api/session.py:619`, `trxstation/gateway/api/session.py:648`, `trxstation/gateway/api/session.py:655`, `trxstation/gateway/api/session.py:690`, `trxstation/gateway/api/session.py:713` |
| ORT-4015 | info | Élément demandé inconnu | non | refus | `unknown_memory`, `unknown_listener` | `trxstation/gateway/api/session.py:353`, `trxstation/gateway/api/session.py:357`, `trxstation/gateway/api/session.py:687`, `trxstation/gateway/api/session.py:357`, `trxstation/gateway/api/session.py:353`, `trxstation/gateway/memories.py:88` |
| ORT-4016 | info | Rapport de problème refusé | non | refus | `report_empty`, `report_too_soon` | `trxstation/gateway/bugreports.py:51`, `trxstation/gateway/bugreports.py:55`, `trxstation/gateway/api/session.py:624` |
| ORT-4017 | info | Demande de TRX Console ignorée | non | refus |  | `trxstation/netprobe/probe.py:226`, `trxstation/netprobe/probe.py:231`, `trxstation/gateway/access_watch.py:86`, `trxstation/gateway/access_watch.py:91`, `trxstation/gateway/access_watch.py:96`, `trxstation/gateway/access_watch.py:99`, `trxstation/gateway/access_watch.py:124`, `trxstation/presence/service.py:163`, `trxstation/presence/service.py:175`, `trxstation/presence/service.py:178` |
| ORT-4018 | erreur | Erreur inattendue : session d'un client | non | aucune |  | `trxstation/gateway/api/session.py:148`, `trxstation/gateway/api/session.py:600`, `trxstation/gateway/api/session.py:682` |
| ORT-4101 | erreur | Certificat TLS inutilisable : API non démarrée | non | repli_reception_seule |  | `trxstation/gateway/main.py:253`, `trxstation/gateway/api/tls.py:22`, `trxstation/gateway/api/tls.py:36`, `trxstation/gateway/main.py:252-252`, `trxstation/setup_wizard.py:802`, `trxstation/diagnostics.py:554`, `trxstation/console.py:628` |
| ORT-4102 | erreur | Port de la passerelle impossible à ouvrir | non | repli_reception_seule |  | `trxstation/gateway/main.py:290`, `trxstation/gateway/api/server.py:109`, `trxstation/gateway/main.py:289-290`, `trxstation/gateway/main.py:215` |
| ORT-4103 | erreur | Compte d'accès mal défini | non | refus |  | `trxstation/config.py:509`, `trxstation/config.py:511`, `trxstation/config.py:514`, `trxstation/config.py:516`, `trxstation/config.py:518`, `trxstation/config.py:659`, `trxstation/config.py:662`, `trxstation/config.py:664`, `trxstation/setup_wizard.py:686`, `trxstation/setup_wizard.py:688`, `trxstation/setup_wizard.py:718`, `trxstation/console.py:1049` |
| ORT-4104 | avert. | Compte avec un jeton en clair | non | aucune |  | `trxstation/config.py:873` |
| ORT-4105 | avert. | Mot de passe trop faible refusé | non | refus |  | `trxstation/passwords.py:62`, `trxstation/passwords.py:64`, `trxstation/passwords.py:66`, `trxstation/passwords.py:68`, `trxstation/setup_wizard.py:691`, `trxstation/console.py:1010` |
| ORT-4106 | avert. | Certificat HTTPS impossible : accès limité à ce PC | non | repli_acces_local |  | `trxstation/setup_wizard.py:545` |
| ORT-4107 | avert. | Aucune adresse réseau sur ce PC | non | aucune |  | `trxstation/diagnostics.py:537` |
| ORT-4108 | avert. | Port de la station fermé ou bloqué | non | aucune |  | `trxstation/diagnostics.py:561`, `trxstation/diagnostics.py:566`, `windows/installer.ps1:359` |
| ORT-4301 | info | Écoute des visiteurs coupée sur la station | non | refus | `listeners_off` | `trxstation/gateway/api/access.py:172`, `trxstation/gateway/api/access.py:217`, `trxstation/gateway/api/session.py:692` |
| ORT-4302 | info | Écoute des visiteurs fermée par l'opérateur | non | refus | `listeners_closed` | `trxstation/gateway/api/access.py:174`, `trxstation/gateway/api/access.py:219`, `trxstation/gateway/api/access.py:75` |
| ORT-4303 | info | Nombre maximal de visiteurs atteint | non | refus | `listeners_full` | `trxstation/gateway/api/access.py:178` |
| ORT-4304 | info | Opérateur absent : écoute des visiteurs impossible | non | refus | `operator_absent` | `trxstation/gateway/api/access.py:182`, `trxstation/gateway/api/access.py:215` |
| ORT-4305 | info | Visiteur déconnecté par l'opérateur | non | refus | `kicked` | `trxstation/gateway/api/webrtc.py:297`, `trxstation/gateway/api/session.py:686`, `trxstation/gateway/access_watch.py:122` |
| ORT-4306 | info | Commande refusée à un visiteur | non | refus | `forbidden` | `trxstation/gateway/api/session.py:518`, `trxstation/gateway/api/session.py:519` |
| ORT-4307 | avert. | Visiteur déconnecté : trop de commandes refusées | oui (3) | refus | `too_many_forbidden` | `trxstation/gateway/api/session.py:521`, `trxstation/gateway/api/session.py:523`, `trxstation/gateway/api/session.py:527` |
| ORT-4308 | erreur | Station surchargée : visiteurs déconnectés | oui (3) | arreter_ecoute_visiteurs | `station_overload` | `trxstation/gateway/api/overload.py:91`, `trxstation/gateway/api/overload.py:46`, `trxstation/gateway/access_watch.py:113`, `trxstation/gateway/access_watch.py:116`, `trxstation/gateway/access_watch.py:118`, `trxstation/gateway/api/access.py:176`, `trxstation/gateway/access_watch.py:111-118`, `trxstation/gateway/api/overload.py:141` |
| ORT-4309 | avert. | Écoute des visiteurs verrouillée après des surcharges répétées | non | arreter_ecoute_visiteurs | `station_overload (locked)` | `trxstation/gateway/api/overload.py:111`, `trxstation/gateway/api/overload.py:89` |
| ORT-4310 | info | Réouverture de l'écoute des visiteurs refusée | non | refus | `still_overloaded` | `trxstation/gateway/api/overload.py:129`, `trxstation/gateway/api/session.py:734`, `trxstation/gateway/access_watch.py:109`, `trxstation/gateway/access_watch.py:109` |
| ORT-4501 | avert. | Coupure réseau d'un client | oui (3) | aucune | `net_event outage` | `trxstation/netprobe/probe.py:160`, `trxstation/netprobe/probe.py:163`, `trxstation/netprobe/probe.py:291` |
| ORT-4502 | avert. | Aller-retour réseau élevé | non | aucune |  | `trxstation/netprobe/calc.py:144` |
| ORT-4503 | avert. | Profil VPN probablement partagé | oui (3) | aucune | `net_event vpn_shared` | `trxstation/netprobe/vpn.py:87`, `trxstation/netprobe/vpn.py:92`, `trxstation/netprobe/probe.py:157` |
| ORT-4504 | info | Horloge du client décalée | non | aucune |  | `trxstation/netprobe/probe.py:365` |
| ORT-4505 | avert. | Sonde de la station vers la box ou Internet abandonnée | non | repli_tcp |  | `trxstation/netprobe/station_probes.py:176`, `trxstation/netprobe/station_probes.py:67`, `trxstation/netprobe/station_probes.py:192` |
| ORT-4506 | info | Historique de la sonde réseau effacé | non | aucune |  | `trxstation/netprobe/probe.py:280` |
| ORT-4507 | info | trx-netreport : aucune mesure | non | aucune |  | `trxstation/netprobe/netreport.py:38`, `trxstation/netprobe/netreport.py:42` |
| ORT-4508 | erreur | Export ou effacement de l'historique réseau impossible | non | refus |  | `trxstation/console.py:1415`, `trxstation/console.py:1445` |
| ORT-4509 | erreur | Erreur inattendue : sonde de qualité réseau | non | aucune | `netprobe_error` | `trxstation/gateway/api/session.py:190`, `trxstation/gateway/api/session.py:223`, `trxstation/gateway/api/session.py:245`, `trxstation/gateway/api/session.py:501`, `trxstation/netprobe/probe.py:180`, `trxstation/netprobe/probe.py:194`, `trxstation/netprobe/probe.py:202`, `trxstation/netprobe/probe.py:210`, `trxstation/netprobe/vpn.py:94`, `trxstation/netprobe/station_probes.py:197` |

### 5000–5999 : PTT et sécurité d'émission

| Code | Gravité | Titre | ntfy | Action | Codes machine | Origines |
| --- | --- | --- | --- | --- | --- | --- |
| ORT-5001 | avert. | Durée maximale d'émission (TOT) atteinte | non | retour_rx | `tot` | `trxstation/gateway/safety/ptt.py:625-626`, `trxstation/gateway/safety/ptt.py:96` |
| ORT-5002 | erreur | Retour forcé en réception : terminal perdu | non | retour_rx | `heartbeat`, `client_disconnected` | `trxstation/gateway/safety/ptt.py:628-629`, `trxstation/gateway/safety/ptt.py:261` |
| ORT-5003 | CRITIQUE | L'ouverture du second port met le poste en émission | non | retour_rx | `spectrum_port_keyed` | `trxstation/spectrum/probe.py:45`, `trxstation/spectrum/service.py:326`, `trxstation/spectrum/service.py:319`, `trxstation/devtools/hwtest.py:450`, `trxstation/devtools/hwtest.py:451`, `trxstation/spectrum/service.py:319`, `trxstation/setup_wizard.py:195` |
| ORT-5004 | info | Émission pendant l'ouverture du second port (autre cause) | non | nouvel_essai | `ptt_busy` | `trxstation/spectrum/probe.py:48`, `trxstation/spectrum/service.py:393`, `trxstation/spectrum/service.py:393` |
| ORT-5005 | info | Poste utilisé sur place : PTT à distance bloqué | non | refus | `local_active` | `trxstation/gateway/safety/ptt.py:477`, `trxstation/gateway/safety/ptt.py:601`, `trxstation/gateway/safety/local.py:46` |
| ORT-5006 | info | Reprise de la main impossible : le poste émet sur place | non | refus | `local_tx` | `trxstation/gateway/safety/ptt.py:424` |
| ORT-5007 | info | Main reprise à distance | non | aucune | `local_released` | `trxstation/gateway/safety/ptt.py:425` |
| ORT-5008 | erreur | Poste trop chaud : émission à distance coupée | oui (3) | retour_rx | `rig_overheat`, `rig_hot` | `trxstation/gateway/safety/ptt.py:479`, `trxstation/gateway/safety/ptt.py:615`, `trxstation/gateway/safety/ptt.py:605`, `trxstation/gateway/safety/thermal.py:45`, `trxstation/supervisor/core.py:272` |
| ORT-5009 | avert. | Poste chaud | oui (3) | aucune | `rig_warm` | `trxstation/gateway/safety/thermal.py:50`, `trxstation/supervisor/core.py:272` |
| ORT-5010 | CRITIQUE | PTT actif sans session cliente | oui (3) | retour_rx | `ptt_mismatch` | `trxstation/supervisor/core.py:235-236` |
| ORT-5011 | info | Prise d'émission annulée par une coupure | non | refus | `cancelled` | `trxstation/gateway/safety/ptt.py:512`, `trxstation/gateway/safety/ptt.py:534`, `trxstation/gateway/safety/ptt.py:541` |
| ORT-5012 | erreur | L'ordre d'émission a échoué | non | retour_rx | `ptt_write_failed` | `trxstation/gateway/safety/ptt.py:531`, `trxstation/gateway/safety/ptt.py:532` |
| ORT-5013 | erreur | Le poste n'est pas passé en émission | non | retour_rx | `rig_did_not_key` | `trxstation/gateway/safety/ptt.py:543`, `trxstation/gateway/safety/ptt.py:544`, `trxstation/gateway/safety/ptt.py:543`, `trxstation/gateway/safety/ptt.py:544` |
| ORT-5014 | info | Fin d'émission proche (TOT) | non | aucune | `tot_warning` | `trxstation/gateway/safety/ptt.py:631-633` |
| ORT-5015 | info | Émission coupée par STOP | non | retour_rx | `stop` | `trxstation/gateway/api/session.py:613` |
| ORT-5016 | info | Émission coupée par un autre client | non | retour_rx | `toggle` | `trxstation/gateway/safety/ptt.py:278` |
| ORT-5017 | avert. | Réglage modifié sur le poste pendant l'émission | non | retour_rx | `frequency_changed`, `mode_changed`, `split_changed`, `xit_changed` | `trxstation/gateway/safety/ptt.py:654`, `trxstation/gateway/safety/ptt.py:661`, `trxstation/gateway/safety/ptt.py:668`, `trxstation/gateway/safety/ptt.py:643`, `trxstation/gateway/safety/ptt.py:654`, `trxstation/gateway/safety/ptt.py:668`, `trxstation/gateway/safety/ptt.py:661` |
| ORT-5018 | avert. | Le poste est repassé seul en réception | non | retour_rx | `rig_reported_rx` | `trxstation/gateway/safety/ptt.py:674`, `trxstation/gateway/safety/ptt.py:674` |
| ORT-5019 | erreur | Liaison avec le poste perdue pendant l'émission | non | retour_rx | `cat_down`, `rig_silent` | `trxstation/gateway/safety/ptt.py:611`, `trxstation/gateway/safety/ptt.py:613`, `trxstation/gateway/safety/ptt.py:617`, `trxstation/gateway/safety/ptt.py:611`, `trxstation/gateway/safety/ptt.py:613` |
| ORT-5020 | CRITIQUE | Retour en réception impossible | oui (5) | redemarrer_passerelle | `unkey_failed`, `gateway_cannot_unkey` | `trxstation/gateway/safety/ptt.py:700`, `trxstation/gateway/safety/ptt.py:706`, `trxstation/gateway/safety/ptt.py:710-711`, `trxstation/supervisor/core.py:223`, `trxstation/monitor/model.py:194`, `trxstation/tray/status.py:177` |
| ORT-5021 | avert. | Bip de fin d'émission impossible | non | retour_rx |  | `trxstation/gateway/safety/ptt.py:365`, `trxstation/gateway/safety/ptt.py:381`, `trxstation/gateway/safety/ptt.py:385`, `trxstation/gateway/safety/ptt.py:396`, `trxstation/gateway/safety/ptt.py:308` |
| ORT-5022 | info | Bip de fin interrompu par une coupure | non | retour_rx |  | `trxstation/gateway/safety/ptt.py:388`, `trxstation/gateway/safety/ptt.py:287` |
| ORT-5023 | info | Émission coupée par l'arrêt de la station | non | retour_rx | `shutdown` | `trxstation/gateway/safety/ptt.py:235`, `trxstation/gateway/main.py:129` |
| ORT-5024 | CRITIQUE | TOT absolu dépassé : coupure par le superviseur | oui (5) | retour_rx | `tot_absolu` | `trxstation/supervisor/core.py:214-214`, `trxstation/supervisor/core.py:186`, `trxstation/supervisor/core.py:426` |
| ORT-5025 | CRITIQUE | Passerelle muette pendant une émission | oui (5) | redemarrer_passerelle | `gateway_silent_tx` | `trxstation/supervisor/core.py:218-218`, `trxstation/supervisor/core.py:186` |
| ORT-5026 | CRITIQUE | rigctld injoignable pendant une émission | oui (5) | redemarrer_rigctld | `rigctld_down_during_tx` | `trxstation/supervisor/core.py:242-244`, `trxstation/supervisor/core.py:184-186`, `trxstation/supervisor/core.py:244` |
| ORT-5027 | CRITIQUE | « T 0 » du superviseur non confirmé | non | nouvel_essai |  | `trxstation/supervisor/core.py:313-314`, `trxstation/supervisor/rigctl.py:88`, `trxstation/supervisor/backends.py:248`, `trxstation/supervisor/backends.py:252` |
| ORT-5028 | erreur | Erreur inattendue : bips de fin d'émission | non | aucune |  | `trxstation/gateway/audio/beeps.py:172` |
| ORT-5101 | erreur | Émission refusée : défaut verrouillé | non | refus | `fault_latched` | `trxstation/gateway/safety/ptt.py:462` |
| ORT-5102 | info | Émission refusée : station en démarrage | non | refus | `starting` | `trxstation/gateway/safety/ptt.py:464` |
| ORT-5103 | info | Émission refusée : coupure ou émission en cours | non | refus | `not_idle` | `trxstation/gateway/safety/ptt.py:466`, `trxstation/gateway/safety/ptt.py:245` |
| ORT-5104 | avert. | Émission refusée : client non reconnu | non | refus | `unknown_client` | `trxstation/gateway/safety/ptt.py:468`, `trxstation/gateway/safety/ptt.py:422` |
| ORT-5105 | info | Émission refusée : mesure de TOS en cours | non | refus | `swr_busy` | `trxstation/gateway/safety/ptt.py:470`, `trxstation/swr/runner.py:96`, `trxstation/swr/runner.py:109`, `trxstation/gateway/api/session.py:590` |
| ORT-5106 | avert. | Émission refusée : aucune bande autorisée | non | refus | `tx_disabled` | `trxstation/gateway/safety/ptt.py:472`, `trxstation/config.py:859`, `trxstation/setup_wizard.py:499` |
| ORT-5107 | avert. | Émission refusée : hors des bandes autorisées | non | refus | `out_of_band` | `trxstation/gateway/safety/ptt.py:520` |
| ORT-5108 | erreur | Émission refusée : split illisible | non | refus | `split_unreadable` | `trxstation/gateway/safety/ptt.py:567`, `trxstation/gateway/safety/ptt.py:572`, `trxstation/gateway/safety/ptt.py:575`, `trxstation/gateway/safety/ptt.py:567`, `trxstation/gateway/safety/ptt.py:572`, `trxstation/gateway/safety/ptt.py:575` |
| ORT-5109 | erreur | Émission refusée : ΔTX (XIT) illisible | non | refus | `xit_unreadable` | `trxstation/gateway/safety/ptt.py:587`, `trxstation/gateway/safety/ptt.py:590`, `trxstation/gateway/safety/ptt.py:587`, `trxstation/gateway/safety/ptt.py:590` |
| ORT-5110 | erreur | Émission refusée : liaison avec le poste perdue | non | refus | `cat_down` | `trxstation/gateway/safety/ptt.py:474`, `trxstation/gateway/api/session.py:746`, `trxstation/gateway/safety/ptt.py:474`, `trxstation/gateway/api/session.py:746`, `trxstation/modules/gateway_bridge.py:149` |
| ORT-5111 | erreur | Émission refusée : le poste répond mal | non | refus | `cat_error` | `trxstation/gateway/safety/ptt.py:491`, `trxstation/gateway/safety/ptt.py:499`, `trxstation/gateway/safety/ptt.py:507`, `trxstation/gateway/safety/ptt.py:577`, `trxstation/gateway/safety/ptt.py:592`, `trxstation/gateway/safety/ptt.py:491`, `trxstation/gateway/safety/ptt.py:499`, `trxstation/gateway/safety/ptt.py:507`, `trxstation/gateway/safety/ptt.py:577`, `trxstation/gateway/safety/ptt.py:592` |
| ORT-5112 | erreur | Émission refusée : état du PTT illisible | non | refus | `ptt_unreadable` | `trxstation/gateway/safety/ptt.py:496`, `trxstation/gateway/safety/ptt.py:496`, `trxstation/devtools/hwtest.py:239` |
| ORT-5113 | avert. | Émission refusée : le poste émet déjà | non | refus | `rig_already_tx` | `trxstation/gateway/safety/ptt.py:514`, `trxstation/gateway/safety/ptt.py:514`, `trxstation/devtools/hwtest.py:237` |
| ORT-5114 | avert. | Émission refusée dans ce mode | non | refus | `mode_not_allowed` | `trxstation/gateway/safety/ptt.py:516`, `trxstation/gateway/safety/ptt.py:516`, `trxstation/devtools/hwtest.py:533`, `trxstation/devtools/hwtest.py:538` |
| ORT-5115 | info | Émission refusée : trop rapprochée | non | refus | `cooldown` | `trxstation/gateway/safety/ptt.py:481` |
| ORT-5116 | info | Réglage refusé pendant l'émission | non | refus | `tx_active` | `trxstation/gateway/safety/ptt.py:456`, `trxstation/swr/runner.py:107`, `trxstation/gateway/safety/ptt.py:456`, `trxstation/spectrum/service.py:181`, `trxstation/spectrum/service.py:210`, `trxstation/spectrum/service.py:278` |
| ORT-5501 | info | Mesure de TOS non disponible | non | refus | `swr_unavailable` | `trxstation/swr/runner.py:98` |
| ORT-5502 | info | Plage de mesure de TOS invalide | non | refus | `swr_bad_range`, `swr_too_many_points` | `trxstation/swr/plan.py:76`, `trxstation/swr/plan.py:90`, `trxstation/swr/plan.py:92`, `trxstation/swr/plan.py:101`, `trxstation/swr/plan.py:105`, `trxstation/swr/runner.py:101-102` |
| ORT-5503 | avert. | Mesure de TOS : aucun point dans les bandes | non | refus | `swr_out_of_band` | `trxstation/swr/runner.py:77-78` |
| ORT-5504 | avert. | Mesure de TOS : aucun mode FM permis | non | refus | `swr_no_fm_mode` | `trxstation/swr/runner.py:104` |
| ORT-5505 | erreur | Mesure de TOS arrêtée : poste illisible | non | retour_rx | `swr_unreadable` | `trxstation/swr/runner.py:160`, `trxstation/swr/runner.py:167`, `trxstation/swr/runner.py:243` |
| ORT-5506 | info | Mesure de TOS interrompue par une coupure | non | retour_rx | `cut`, `swr_cancel` | `trxstation/swr/runner.py:125`, `trxstation/swr/runner.py:138`, `trxstation/swr/runner.py:119`, `trxstation/swr/runner.py:314-316` |
| ORT-5507 | avert. | Mesure de TOS arrêtée : émission refusée | non | retour_rx |  | `trxstation/swr/runner.py:142`, `trxstation/swr/runner.py:276-277` |
| ORT-5508 | erreur | Mesure de TOS en erreur | non | retour_rx | `swr_failed` | `trxstation/swr/runner.py:282-283` |
| ORT-5509 | avert. | Lecture du TOS instable sur ce poste | non | aucune | `swr_unstable` | `trxstation/swr/runner.py:213`, `trxstation/swr/runner.py:251` |
| ORT-5510 | avert. | Point de mesure à puissance réduite | non | aucune | `reduced` | `trxstation/swr/runner.py:271-272` |
| ORT-5511 | info | Point de mesure sans lecture du TOS | non | aucune | `unread` | `trxstation/swr/runner.py:265-266` |
| ORT-5512 | avert. | Remise en état du poste incomplète après la mesure | non | aucune |  | `trxstation/swr/runner.py:301-302`, `trxstation/swr/runner.py:327`, `trxstation/swr/runner.py:336-343` |
| ORT-5801 | avert. | PTT par RTS ou DTR : risque d'émission brève | non | aucune |  | `trxstation/config.py:880`, `trxstation/diagnostics.py:248` |
| ORT-5802 | avert. | Contrôle des bandes désactivé | non | aucune |  | `trxstation/config.py:861` |
| ORT-5803 | avert. | Chargement d'un profil refusé pendant l'émission | non | refus |  | `trxstation/console.py:723`, `trxstation/console.py:778` |
| ORT-5804 | avert. | PTT actif pendant le test : retour en réception forcé | non | retour_rx |  | `trxstation/setup_wizard.py:154`, `trxstation/setup_wizard.py:439` |
| ORT-5805 | CRITIQUE | STOP TX de trx-monitor sans confirmation | non | retour_rx |  | `trxstation/monitor/actions.py:18` |
| ORT-5806 | erreur | Mise en page sans commande de sécurité | non | refus | `layout_invalid` | `trxstation/layout/validate.py:132`, `trxstation/layout/validate.py:134`, `trxstation/layout/validate.py:304`, `trxstation/layout/validate.py:306` |
| ORT-5901 | erreur | Essai : état PTT relu incohérent | non | retour_rx | `ptt_cycle` | `trxstation/devtools/hwtest.py:614`, `trxstation/devtools/hwtest.py:602`, `trxstation/devtools/hwtest.py:632`, `trxstation/devtools/hwtest.py:677`, `trxstation/devtools/hwtest.py:730` |
| ORT-5902 | CRITIQUE | Essai de panne : l'émission n'a pas été coupée | non | retour_rx |  | `trxstation/devtools/hwtest.py:688`, `trxstation/devtools/hwtest.py:741`, `trxstation/devtools/hwtest.py:690`, `trxstation/devtools/hwtest.py:204` |

### 6000–6999 : Modules

| Code | Gravité | Titre | ntfy | Action | Codes machine | Origines |
| --- | --- | --- | --- | --- | --- | --- |
| ORT-6401 | erreur | Cluster DX activé mais incomplet | non | refus |  | `trxstation/config.py:425`, `trxstation/config.py:427`, `trxstation/config.py:430`, `trxstation/diagnostics.py:477` |
| ORT-6402 | avert. | Serveur de spots injoignable | non | nouvel_essai | `unreachable` | `trxstation/cluster/telnet.py:165`, `trxstation/cluster/telnet.py:193`, `trxstation/cluster/feed.py:194`, `trxstation/cluster/service.py:333`, `trxstation/cluster/tester.py:70` |
| ORT-6403 | info | Connexion au cluster fermée par le serveur | non | nouvel_essai | `closed` | `trxstation/cluster/telnet.py:30`, `trxstation/cluster/telnet.py:202` |
| ORT-6404 | avert. | Connexion au cluster muette | non | nouvel_essai | `idle` | `trxstation/cluster/telnet.py:210` |
| ORT-6405 | erreur | Indicatif refusé par le cluster | non | refus | `callsign_refused` | `trxstation/cluster/telnet.py:217`, `trxstation/cluster/telnet.py:199`, `trxstation/cluster/feed.py:158`, `trxstation/cluster/tester.py:92` |
| ORT-6406 | erreur | Mot de passe refusé par le cluster | non | refus | `password_refused` | `trxstation/cluster/telnet.py:218`, `trxstation/cluster/feed.py:158` |
| ORT-6407 | erreur | Le cluster demande un mot de passe | non | refus | `password_required` | `trxstation/cluster/telnet.py:236`, `trxstation/cluster/service.py:76` |
| ORT-6408 | avert. | Bascule vers un autre cluster | non | repli_source_suivante | `failed` | `trxstation/cluster/feed.py:168` |
| ORT-6409 | avert. | Aucune source du Cluster DX connectée | non | aucune | `red` | `trxstation/cluster/service.py:47`, `trxstation/cluster/service.py:263`, `trxstation/cluster/service.py:281`, `trxstation/diagnostics.py:501`, `trxstation/diagnostics.py:506`, `trxstation/diagnostics.py:515`, `trxstation/diagnostics.py:521`, `trxstation/diagnostics.py:528` |
| ORT-6410 | avert. | Page des spots CB illisible | non | nouvel_essai | `format` | `trxstation/cluster/clusterdx.py:106`, `trxstation/cluster/clusterdx.py:115`, `trxstation/cluster/clusterdx.py:150`, `trxstation/cluster/feed.py:194`, `trxstation/cluster/tester.py:68` |
| ORT-6411 | avert. | Table des pays (cty.dat) absente ou illisible | non | aucune |  | `trxstation/cluster/cty.py:163`, `trxstation/cluster/cty.py:165`, `trxstation/cluster/cty.py:127`, `trxstation/cluster/cli.py:146` |
| ORT-6412 | info | Mise à jour de cty.dat impossible | non | nouvel_essai |  | `trxstation/cluster/service.py:290`, `trxstation/cluster/cty.py:183`, `trxstation/cluster/cty.py:186`, `trxstation/cluster/cli.py:143` |
| ORT-6413 | info | Indicatif refusé par le réglage du Cluster DX | non | refus |  | `trxstation/cluster/text.py:74`, `trxstation/cluster/text.py:76`, `trxstation/cluster/text.py:85`, `trxstation/cluster/setup.py:178`, `trxstation/cluster/cli.py:228` |
| ORT-6501 | erreur | Module extérieur déclaré mais absent ou non démarré | non | aucune | `freedv_missing`, `state.freedv.cause`, `module_absent` | `trxstation/breizh/link.py:314`, `trxstation/breizh/link.py:287`, `trxstation/freedv/service.py:119`, `trxstation/gateway/main.py:185`, `trxstation/gateway/api/session.py:303`, `trxstation/gateway/main.py:183-183`, `trxstation/freedv/rx_engine.py:282`, `trxstation/modules/registry.py:39`, `trxstation/modules/launcher.py:191`, `trxstation/modules/supervisor_glue.py:69`, `trxstation/supervisor/main.py:143`, `trxstation/supervisor/main.py:153`, `trxstation/modules/bus.py:171`, `trxstation/modules/bus.py:389`, `trxstation/modules/gateway_bridge.py:157`, `trxstation/gateway/api/session.py:538`, `trxstation/breizh/link.py:282` |
| ORT-6502 | erreur | Version du module incompatible | non | refus | `breizh_event refused (proto)`, `api` | `trxstation/breizh/link.py:128`, `trxstation/breizh/protocol.py:249`, `trxstation/breizh/protocol.py:265`, `trxstation/breizh/protocol.py:126`, `trxstation/modules/launcher.py:118`, `trxstation/modules/bus.py:262`, `trxstation/modules/supervisor_glue.py:51` |
| ORT-6503 | erreur | Échec de la négociation avec le module | non | refus | `breizh_event refused (format`, `latency)`, `auth` | `trxstation/breizh/link.py:128`, `trxstation/breizh/protocol.py:251`, `trxstation/breizh/protocol.py:271`, `trxstation/modules/bus.py:236`, `trxstation/modules/bus.py:247`, `trxstation/modules/bus.py:251`, `trxstation/modules/bus.py:258`, `trxstation/modules/client.py:92`, `trxstation/cluster/service.py:345`, `trxstation/presence/service.py:250`, `trxstation/modules/demo_module.py:70` |
| ORT-6504 | avert. | Le module ne répond plus (battement perdu) | non | repli_direct | `breizh_event lost`, `state.freedv.cause` | `trxstation/breizh/link.py:290`, `trxstation/breizh/store.py:112`, `trxstation/freedv/rx_engine.py:422`, `trxstation/freedv/rx_engine.py:354`, `trxstation/freedv/rx_engine.py:358` |
| ORT-6505 | avert. | Catalogue du module invalide ou non traduit | non | aucune |  | *prévu, pas encore dans le code* |
| ORT-6506 | avert. | Code reçu absent du catalogue du module | non | aucune |  | *prévu, pas encore dans le code* |
| ORT-6507 | erreur | Le module perturbe la station (CPU, latence audio) | non | arreter_module |  | `trxstation/modules/bus.py:282` |
| ORT-6508 | avert. | Préfixe non enregistré | non | aucune |  | *prévu, pas encore dans le code* |
| ORT-6511 | avert. | Manifeste de module invalide | non | refus |  | `trxstation/modules/manifest.py:85`, `trxstation/modules/manifest.py:108`, `trxstation/modules/manifest.py:126`, `trxstation/modules/manifest.py:153`, `trxstation/modules/manifest.py:176`, `trxstation/modules/registry.py:31`, `trxstation/modules/supervisor_glue.py:39`, `trxstation/modules/gateway_bridge.py:67` |
| ORT-6512 | info | Module désactivé par son manifeste | non | refus |  | `trxstation/modules/registry.py:41` |
| ORT-6513 | avert. | Aucun module utilisable | non | aucune |  | `trxstation/modules/gateway_bridge.py:69`, `trxstation/modules/supervisor_glue.py:41` |
| ORT-6514 | erreur | Bus des modules indisponible | non | aucune |  | `trxstation/modules/gateway_bridge.py:79`, `trxstation/modules/bus.py:96` |
| ORT-6515 | erreur | Clé des modules invalide | non | aucune |  | `trxstation/modules/keys.py:48`, `trxstation/modules/keys.py:72`, `trxstation/modules/launcher.py:143` |
| ORT-6516 | erreur | Compte d'exécution des modules inutilisable | oui (3) | refus |  | `trxstation/modules/launcher.py:155`, `trxstation/modules/launcher.py:164` |
| ORT-6517 | avert. | Arrêt inattendu d'un module | oui (3) | nouvel_essai |  | `trxstation/modules/launcher.py:284` |
| ORT-6518 | avert. | Message illisible d'un module | non | aucune |  | `trxstation/modules/bus.py:295`, `trxstation/modules/protocol.py:37`, `trxstation/modules/protocol.py:45`, `trxstation/modules/protocol.py:47` |
| ORT-6519 | avert. | Station injoignable depuis un module | non | nouvel_essai |  | `trxstation/modules/client.py:134`, `trxstation/modules/client.py:207`, `trxstation/modules/client.py:88` |
| ORT-6520 | info | Commande de module refusée pendant l'émission | non | refus | `ptt_active` | `trxstation/modules/bus.py:341`, `trxstation/modules/bus.py:342` |
| ORT-6521 | avert. | Action d'un module non autorisée | non | refus | `forbidden` | `trxstation/modules/bus.py:339`, `trxstation/modules/bus.py:358`, `trxstation/modules/bus.py:367`, `trxstation/modules/bus.py:173` |
| ORT-6522 | info | Commande non disponible | non | refus | `unavailable` | `trxstation/modules/bus.py:344`, `trxstation/modules/bus.py:374`, `trxstation/modules/client.py:196`, `trxstation/modules/gateway_bridge.py:132` |
| ORT-6523 | info | Trop de messages d'un module | non | refus | `rate_limited` | `trxstation/modules/bus.py:360` |
| ORT-6524 | avert. | Délai de réponse dépassé entre la station et un module | non | refus | `timeout` | `trxstation/modules/bus.py:182`, `trxstation/modules/bus.py:353` |
| ORT-6525 | avert. | Changement de fréquence demandé par un module refusé | non | refus | `invalid` | `trxstation/modules/gateway_bridge.py:135`, `trxstation/modules/gateway_bridge.py:137`, `trxstation/modules/gateway_bridge.py:143`, `trxstation/modules/gateway_bridge.py:147`, `trxstation/modules/gateway_bridge.py:149` |
| ORT-6526 | avert. | Jeton de session refusé | non | refus | `token_expired` | `trxstation/modules/bus.py:371`, `trxstation/modules/tokens.py:75`, `trxstation/modules/tokens.py:78`, `trxstation/modules/tokens.py:87`, `trxstation/modules/tokens.py:90` |
| ORT-6527 | erreur | Erreur inattendue dans le bus des modules | non | aucune | `internal` | `trxstation/modules/bus.py:223`, `trxstation/modules/bus.py:316`, `trxstation/modules/bus.py:376`, `trxstation/modules/client.py:176`, `trxstation/modules/client.py:190`, `trxstation/modules/client.py:202`, `trxstation/modules/client.py:216`, `trxstation/modules/supervisor_glue.py:86`, `trxstation/modules/gateway_bridge.py:99`, `trxstation/modules/gateway_bridge.py:204`, `trxstation/modules/gateway_bridge.py:217`, `trxstation/modules/launcher.py:305` |
| ORT-6528 | avert. | Fichier d'un module non écrit | non | aucune |  | `trxstation/cluster/service.py:181`, `trxstation/cluster/service.py:259`, `trxstation/presence/service.py:267`, `trxstation/presence/store.py:88`, `trxstation/presence/service.py:168`, `trxstation/presence/service.py:191` |
| ORT-6531 | erreur | Clé d'appairage de Breizh Audio Box inutilisable | non | repli_direct |  | `trxstation/breizh/keyfile.py:30`, `trxstation/breizh/keyfile.py:32`, `trxstation/breizh/keyfile.py:34`, `trxstation/breizh/keyfile.py:38`, `trxstation/breizh/keyfile.py:62`, `trxstation/gateway/main.py:205`, `trxstation/gateway/main.py:204-204`, `trxstation/console.py:1500`, `trxstation/console.py:1565`, `trxstation/console.py:1606` |
| ORT-6532 | info | Breizh Audio Box a quitté le mode OpenRemoteTRX | non | repli_direct | `breizh_event lost` | `trxstation/breizh/link.py:227` |
| ORT-6533 | avert. | Repli pendant l'émission : fin en direct | non | repli_direct | `breizh_event fallback` | `trxstation/gateway/audio/route.py:133`, `trxstation/gateway/audio/route.py:75`, `trxstation/breizh/link.py:119` |
| ORT-6534 | info | Blocs de son revenus trop tard de Breizh Audio Box | non | aucune | `state.breizh.late` | `trxstation/gateway/audio/route.py:128`, `trxstation/gateway/audio/route.py:164` |
| ORT-6535 | erreur | Mode OpenRemoteTRX non activé dans Breizh Audio Box | non | repli_direct | `breizh_event refused (mode_off)` | `trxstation/breizh/link.py:128` |
| ORT-6536 | avert. | Breizh Audio Box sert déjà une autre station | non | repli_direct | `breizh_event refused (busy)` | `trxstation/breizh/link.py:128` |
| ORT-6537 | erreur | Breizh Audio Box n'a pas coupé son CAT | non | repli_direct | `breizh_event refused (cat_on)` | `trxstation/breizh/link.py:128`, `trxstation/breizh/protocol.py:268` |
| ORT-6538 | erreur | Réponse de Breizh Audio Box mal formée | non | repli_direct | `breizh_event refused (nonce`, `json`, `code)` | `trxstation/breizh/link.py:128`, `trxstation/breizh/protocol.py:217`, `trxstation/breizh/protocol.py:204`, `trxstation/breizh/protocol.py:282` |
| ORT-6539 | avert. | Paquets de Breizh Audio Box refusés | non | aucune | `breizh_event bad_packets` | `trxstation/breizh/link.py:270`, `trxstation/breizh/link.py:185`, `trxstation/breizh/protocol.py:143` |
| ORT-6540 | info | Breizh Audio Box joint ou repris | non | aucune | `breizh_event connected`, `back`, `reactivated` | `trxstation/breizh/link.py:252`, `trxstation/breizh/link.py:260`, `trxstation/breizh/link.py:256`, `trxstation/breizh/link.py:301`, `trxstation/breizh/link.py:97` |
| ORT-6541 | erreur | Erreur inattendue : liaison avec Breizh Audio Box | non | aucune |  | `trxstation/breizh/link.py:319`, `trxstation/breizh/store.py:121` |
| ORT-6561 | avert. | Décodeur FreeDV arrêté | non | nouvel_essai | `state.freedv.cause` | `trxstation/freedv/rx_engine.py:414`, `trxstation/freedv/rx_engine.py:266` |
| ORT-6562 | avert. | Sortie d'un décodeur FreeDV illisible | non | nouvel_essai | `state.freedv.cause` | `trxstation/freedv/rx_engine.py:381`, `trxstation/freedv/rx_engine.py:400` |
| ORT-6563 | erreur | FreeDV abandonné après ses relances | non | repli_son_du_poste | `freedv_event fault` | `trxstation/freedv/service.py:155`, `trxstation/freedv/service.py:156`, `trxstation/freedv/rx_engine.py:263` |
| ORT-6564 | erreur | Mode FreeDV en erreur dans la chaîne audio | non | repli_son_du_poste |  | `trxstation/gateway/audio/hub.py:51` |
| ORT-6565 | avert. | Décodeur FreeDV trop lent : son jeté | non | aucune | `trx-monitor freedv.drops` | `trxstation/freedv/rx_engine.py:326` |
| ORT-6566 | info | Mode FreeDV non changé pendant l'émission | non | refus | `freedv_tx` | `trxstation/gateway/api/session.py:298` |
| ORT-6567 | erreur | Erreur inattendue : mode FreeDV | non | aucune |  | `trxstation/freedv/service.py:104` |
| ORT-6801 | info | Essai SELCALL : RIT refusé ou illisible | non | aucune |  | `trxstation/devtools/hwtest.py:301`, `trxstation/devtools/hwtest.py:321`, `trxstation/devtools/hwtest.py:354` |
| ORT-6802 | info | Trame SELCALL de fin omise : TOT trop proche | non | aucune |  | `trxstation/gateway/safety/ptt.py:306` |
| ORT-6803 | avert. | Appel SELCALL refusé : plus long que le TOT | non | refus | `selcall_too_long` | `trxstation/gateway/safety/ptt.py:316` |
| ORT-6804 | erreur | Appel SELCALL interrompu | non | retour_rx | `selcall_timeout`, `selcall_failed` | `trxstation/gateway/safety/ptt.py:334-335`, `trxstation/gateway/safety/ptt.py:340-341` |
| ORT-6805 | info | Appel SELCALL reçu | oui (3) | aucune |  | `trxstation/selcall/receiver.py:205`, `trxstation/selcall/receiver.py:227`, `trxstation/gateway/main.py:108` |
| ORT-6806 | info | Trame SELCALL rejetée | non | aucune |  | `trxstation/selcall/receiver.py:347`, `trxstation/selcall/decoder.py:242` |
| ORT-6807 | avert. | État SELCALL illisible | non | aucune |  | `trxstation/selcall/receiver.py:99` |
| ORT-6808 | avert. | État SELCALL non enregistré | non | aucune |  | `trxstation/selcall/receiver.py:136` |
| ORT-6809 | info | SELCALL non disponible | non | refus | `selcall_unavailable` | `trxstation/gateway/api/session.py:390`, `trxstation/gateway/api/session.py:417`, `trxstation/gateway/api/session.py:447` |
| ORT-6810 | info | Appel SELCALL impossible : aucun code armé | non | refus | `selcall_not_armed` | `trxstation/gateway/api/session.py:394` |
| ORT-6811 | info | Code SELCALL invalide | non | refus | `invalid_params` | `trxstation/selcall/protocol.py:32`, `trxstation/gateway/api/protocol.py:231` |
| ORT-6812 | avert. | Réglage automatique SELCALL : ALC illisible | non | aucune |  | `trxstation/selcall/calibrate.py:35`, `trxstation/gateway/api/session.py:434` |
| ORT-6813 | avert. | Réglage automatique SELCALL : ALC dès le plus bas niveau | non | aucune |  | `trxstation/selcall/calibrate.py:41` |
| ORT-6814 | erreur | Erreur inattendue du SELCALL | non | aucune |  | `trxstation/selcall/receiver.py:116`, `trxstation/selcall/receiver.py:163`, `trxstation/selcall/receiver.py:172`, `trxstation/selcall/receiver.py:354` |
| ORT-6901 | avert. | Module « presence » injoignable depuis la console | non | refus |  | `trxstation/console.py:1236`, `trxstation/console.py:1241`, `trxstation/console.py:1253`, `trxstation/console.py:1262`, `trxstation/monitor/model.py:211`, `trxstation/monitor/model.py:213` |
| ORT-6902 | avert. | Présence de groupe : pseudo absent | non | aucune | `pseudo_missing` | `trxstation/presence/engine.py:346`, `trxstation/monitor/model.py:211` |
| ORT-6903 | avert. | Relais de présence injoignable | non | nouvel_essai | `relay_unreachable` | `trxstation/presence/engine.py:353`, `trxstation/presence/engine.py:354`, `trxstation/presence/engine.py:312`, `trxstation/presence/relay.py:53`, `trxstation/presence/relay.py:55`, `trxstation/presence/relay.py:59`, `trxstation/presence/relay.py:61` |
| ORT-6904 | erreur | Enregistrement refusé par le relais de présence | non | nouvel_essai | `register_{motif}` | `trxstation/presence/engine.py:327`, `trxstation/presence/engine.py:337`, `trxstation/presence/engine.py:338` |
| ORT-6905 | info | Relais de présence en pause ou chargé | non | nouvel_essai | `relay_paused` | `trxstation/presence/engine.py:396` |
| ORT-6906 | avert. | Requête refusée par le relais de présence | non | nouvel_essai | `relay_error_{motif}` | `trxstation/presence/engine.py:394`, `trxstation/presence/engine.py:397`, `trxstation/presence/engine.py:398`, `trxstation/presence/engine.py:418` |
| ORT-6907 | avert. | Action refusée par le relais de présence | non | refus | `http_{code}` | `trxstation/presence/engine.py:317`, `trxstation/presence/engine.py:542`, `trxstation/presence/engine.py:550` |
| ORT-6908 | avert. | Liste des membres d'un groupe refusée | non | refus |  | `trxstation/presence/engine.py:438`, `trxstation/presence/roster.py:144`, `trxstation/presence/roster.py:139`, `trxstation/presence/roster.py:156`, `trxstation/presence/roster.py:182`, `trxstation/presence/roster.py:185`, `trxstation/presence/roster.py:192`, `trxstation/presence/roster.py:95` |
| ORT-6909 | avert. | Clé de groupe reçue refusée | non | refus |  | `trxstation/presence/engine.py:460`, `trxstation/presence/invite.py:173`, `trxstation/presence/invite.py:176`, `trxstation/presence/invite.py:179`, `trxstation/presence/invite.py:183` |
| ORT-6910 | info | État d'un membre refusé | non | refus |  | `trxstation/presence/engine.py:500`, `trxstation/presence/state.py:102`, `trxstation/presence/state.py:108`, `trxstation/presence/state.py:116` |
| ORT-6911 | info | Station retirée d'un groupe | non | aucune |  | `trxstation/presence/engine.py:422`, `trxstation/presence/engine.py:448` |
| ORT-6912 | info | Demande d'adhésion refusée automatiquement | non | refus |  | `trxstation/presence/engine.py:530`, `trxstation/presence/invite.py:136`, `trxstation/presence/invite.py:138`, `trxstation/presence/invite.py:142` |
| ORT-6913 | info | Invitation refusée | non | refus | `invitation_expired` | `trxstation/presence/engine.py:224`, `trxstation/presence/engine.py:226`, `trxstation/presence/engine.py:228`, `trxstation/presence/invite.py:87`, `trxstation/presence/invite.py:89`, `trxstation/presence/invite.py:91` |
| ORT-6914 | info | Trop de groupes | non | refus | `quota` | `trxstation/presence/engine.py:193`, `trxstation/presence/engine.py:230` |
| ORT-6915 | info | Station pas encore enregistrée auprès du relais | non | refus | `not_registered` | `trxstation/presence/engine.py:184` |
| ORT-6916 | info | Action réservée à un administrateur du groupe | non | refus | `not_admin` | `trxstation/presence/engine.py:210`, `trxstation/presence/engine.py:253`, `trxstation/presence/engine.py:263`, `trxstation/presence/engine.py:267`, `trxstation/presence/engine.py:277`, `trxstation/presence/engine.py:605` |
| ORT-6917 | info | Groupe ou membre inconnu | non | refus | `unknown_group` | `trxstation/presence/engine.py:176`, `trxstation/presence/actions.py:63`, `trxstation/presence/engine.py:265`, `trxstation/presence/engine.py:279` |
| ORT-6918 | info | Saisie refusée (présence de groupe) | non | refus | `pseudo` | `trxstation/presence/engine.py:122`, `trxstation/presence/engine.py:132`, `trxstation/presence/engine.py:140`, `trxstation/presence/engine.py:148`, `trxstation/presence/engine.py:190`, `trxstation/presence/engine.py:289`, `trxstation/presence/engine.py:298`, `trxstation/presence/actions.py:24`, `trxstation/presence/actions.py:98`, `trxstation/presence/actions.py:146` |
| ORT-6919 | info | Présence de groupe non disponible | non | refus | `friends_unavailable` | `trxstation/gateway/api/session.py:532`, `trxstation/gateway/api/session.py:542` |
| ORT-6920 | erreur | Fichier de clés de la présence illisible | non | nouvel_essai |  | `trxstation/presence/identity.py:73`, `trxstation/presence/identity.py:75`, `trxstation/presence/service.py:56`, `trxstation/presence/service.py:207` |
| ORT-6921 | erreur | Données de la présence illisibles | non | aucune |  | `trxstation/presence/store.py:56`, `trxstation/presence/engine.py:166` |
| ORT-6922 | erreur | Erreur inattendue de la présence de groupe | non | nouvel_essai | `internal` | `trxstation/presence/service.py:240`, `trxstation/presence/service.py:241`, `trxstation/presence/service.py:185`, `trxstation/presence/service.py:229`, `trxstation/gateway/api/session.py:541` |
| ORT-6923 | erreur | Signature invalide reçue (attaque possible) | non | refus |  | `trxstation/presence/engine.py:438`, `trxstation/presence/roster.py:144`, `trxstation/presence/roster.py:139`, `trxstation/presence/roster.py:156`, `trxstation/presence/roster.py:182`, `trxstation/presence/roster.py:185`, `trxstation/presence/roster.py:192`, `trxstation/presence/roster.py:95`, `trxstation/presence/engine.py:460`, `trxstation/presence/invite.py:173`, `trxstation/presence/invite.py:176`, `trxstation/presence/invite.py:179`, `trxstation/presence/invite.py:183` |

### 7000–7999 : Monitor inter-stations

| Code | Gravité | Titre | ntfy | Action | Codes machine | Origines |
| --- | --- | --- | --- | --- | --- | --- |
| ORT-7001 | info | Liaison monitor établie | non | aucune |  | *prévu, pas encore dans le code* |
| ORT-7010 | avert. | Échec ICE, bascule en port UDP | non | repli_udp |  | *prévu, pas encore dans le code* |
| ORT-7020 | avert. | File d'envoi saturée | non | aucune |  | *prévu, pas encore dans le code* |
| ORT-7030 | erreur | Clé distante changée, liaison suspendue | oui (4) | suspendre_liaison |  | *prévu, pas encore dans le code* |

### 8000–8999 : Superviseur et processus

| Code | Gravité | Titre | ntfy | Action | Codes machine | Origines |
| --- | --- | --- | --- | --- | --- | --- |
| ORT-8001 | erreur | Redémarrage d'un processus par le superviseur | oui (3) | redemarrer_passerelle | `restart_gateway`, `restart_rigctld` | `trxstation/supervisor/core.py:338-339`, `trxstation/supervisor/core.py:340-344`, `trxstation/supervisor/backends.py:233` |
| ORT-8002 | erreur | Module désactivé après des arrêts répétés | oui (3) | arreter_module |  | `trxstation/modules/launcher.py:277` |
| ORT-8003 | erreur | Passerelle muette | oui (3) | redemarrer_passerelle | `gateway_silent` | `trxstation/supervisor/core.py:250-251`, `trxstation/status.py:125`, `trxstation/diagnostics.py:431`, `trxstation/diagnostics.py:434`, `trxstation/monitor/model.py:181`, `trxstation/monitor/model.py:184`, `trxstation/monitor/model.py:113`, `trxstation/tray/status.py:139` |
| ORT-8004 | erreur | Réinitialisation USB du poste | oui (3) | reset_usb | `reset_usb` | `trxstation/supervisor/core.py:345-346`, `trxstation/supervisor/backends.py:85-87` |
| ORT-8005 | erreur | Réinitialisation USB impossible | non | redemarrer_rigctld |  | `trxstation/supervisor/usb.py:30`, `trxstation/supervisor/usb.py:39`, `trxstation/supervisor/backends.py:282` |
| ORT-8006 | CRITIQUE | Redémarrage de la machine par le superviseur | oui (3) | redemarrer_systeme | `reboot` | `trxstation/supervisor/core.py:348`, `trxstation/supervisor/core.py:364-365`, `trxstation/supervisor/backends.py:89-90` |
| ORT-8007 | CRITIQUE | Redémarrage refusé : historique non inscriptible | non | arreter_passerelle |  | `trxstation/supervisor/core.py:358-363` |
| ORT-8008 | CRITIQUE | Mode sûr : station en réception, accès coupé | oui (4) | mode_sur | `safe_mode` | `trxstation/supervisor/core.py:353-354`, `trxstation/supervisor/core.py:368`, `trxstation/supervisor/core.py:376`, `trxstation/supervisor/core.py:386`, `trxstation/supervisor/state.py:45`, `trxstation/supervisor/backends.py:215`, `trxstation/diagnostics.py:427`, `trxstation/monitor/model.py:196`, `trxstation/tray/status.py:130`, `trxstation/console.py:424` |
| ORT-8009 | erreur | Mode sûr non enregistré | non | mode_sur |  | `trxstation/supervisor/core.py:371-372` |
| ORT-8010 | erreur | Action du superviseur en échec | non | aucune |  | `trxstation/supervisor/core.py:316`, `trxstation/supervisor/backends.py:64`, `trxstation/supervisor/backends.py:66`, `trxstation/supervisor/backends.py:274`, `trxstation/supervisor/backends.py:191` |
| ORT-8011 | info | Station rétablie | oui (3) | aucune |  | `trxstation/supervisor/core.py:429-430` |
| ORT-8012 | info | Station en service | oui (1) | aucune |  | `trxstation/supervisor/core.py:400-418`, `trxstation/supervisor/notify.py:50` |
| ORT-8013 | avert. | Alerte ntfy non envoyée | non | aucune |  | `trxstation/supervisor/notify.py:52`, `trxstation/supervisor/core.py:398` |
| ORT-8014 | CRITIQUE | Boucle de supervision en erreur | non | arreter_superviseur |  | `trxstation/supervisor/main.py:75`, `trxstation/supervisor/main.py:76-77` |
| ORT-8015 | erreur | Superviseur déjà en cours d'exécution | non | refus |  | `trxstation/supervisor/main.py:113-115`, `trxstation/procutil.py:37` |
| ORT-8016 | erreur | La station ne s'arrête pas | non | aucune |  | `trxstation/supervisor/main.py:59` |
| ORT-8017 | erreur | Superviseur disparu : passerelle arrêtée | non | arreter_passerelle |  | `trxstation/gateway/main.py:57` |
| ORT-8018 | erreur | Surveillance des accès en erreur | non | nouvel_essai |  | `trxstation/gateway/access_watch.py:133`, `trxstation/gateway/access_watch.py:133` |
| ORT-8019 | erreur | Erreur inattendue d'un composant (la station continue) | non | aucune | `netprobe_error`, `friends_error` | *abandonné → ORT-4018, ORT-4509, ORT-5028, ORT-6541, ORT-6567, ORT-6922, ORT-8018 (une erreur inattendue par domaine)* |
| ORT-8020 | avert. | Aucune adresse d'alerte (ntfy) | non | aucune |  | `trxstation/config.py:878` |
| ORT-8021 | erreur | Service de la station en échec ou arrêté | non | aucune |  | `trxstation/diagnostics.py:415`, `trxstation/diagnostics.py:417`, `trxstation/diagnostics.py:419`, `trxstation/console.py:406`, `trxstation/console.py:409`, `debian/install.sh:168` |

### 9000–9999 : Configuration et installation

| Code | Gravité | Titre | ntfy | Action | Codes machine | Origines |
| --- | --- | --- | --- | --- | --- | --- |
| ORT-9001 | erreur | station.toml invalide | non | refus |  | `trxstation/config.py:955`, `trxstation/config.py:947`, `trxstation/gateway/main.py:307`, `trxstation/supervisor/main.py:97`, `trxstation/monitor/main.py:25`, `trxstation/update/apply.py:352`, `trxstation/update/check.py:354`, `trxstation/setup_wizard.py:736`, `trxstation/setup_wizard.py:841`, `trxstation/setup_wizard.py:758`, `trxstation/diagnostics.py:233`, `trxstation/console.py:688`, `trxstation/tray/main.py:177`, `trxstation/run_rigctld.py:25`, `trxstation/devtools/hwtest.py:870`, `trxstation/devtools/hwtest.py:873`, `trxstation/qualif/main.py:142`, `trxstation/qualif/main.py:147`, `trxstation/supervisor/main.py:96-98`, `trxstation/gateway/main.py:306-306`, `trxstation/cluster/service.py:355`, `trxstation/presence/service.py:277`, `trxstation/cluster/setup.py:499`, `trxstation/cluster/setup.py:502` |
| ORT-9002 | erreur | Réglage inconnu dans station.toml | non | refus |  | `trxstation/config.py:881`, `trxstation/config.py:914`, `trxstation/config.py:896` |
| ORT-9003 | erreur | Structure de station.toml invalide | non | refus |  | `trxstation/config.py:940` |
| ORT-9004 | erreur | Version du format de station.toml non prise en charge | non | refus |  | `trxstation/config.py:484` |
| ORT-9005 | erreur | Réglage oui/non mal écrit | non | refus |  | `trxstation/config.py:382`, `trxstation/config.py:419`, `trxstation/config.py:552`, `trxstation/config.py:601`, `trxstation/config.py:606`, `trxstation/config.py:624`, `trxstation/config.py:666`, `trxstation/config.py:687`, `trxstation/config.py:694`, `trxstation/config.py:721`, `trxstation/config.py:761`, `trxstation/config.py:792`, `trxstation/config.py:808` |
| ORT-9006 | erreur | Valeur de réglage hors limites | non | refus |  | `trxstation/config.py:492`, `trxstation/config.py:499`, `trxstation/config.py:502`, `trxstation/config.py:505`, `trxstation/config.py:542`, `trxstation/config.py:560`, `trxstation/config.py:562`, `trxstation/config.py:565`, `trxstation/config.py:568`, `trxstation/config.py:572`, `trxstation/config.py:574`, `trxstation/config.py:578`, `trxstation/config.py:591`, `trxstation/config.py:395`, `trxstation/config.py:413`, `trxstation/config.py:421`, `trxstation/config.py:612`, `trxstation/config.py:616`, `trxstation/config.py:626`, `trxstation/config.py:628`, `trxstation/config.py:640`, `trxstation/config.py:684`, `trxstation/config.py:698`, `trxstation/config.py:701`, `trxstation/config.py:723`, `trxstation/config.py:731`, `trxstation/config.py:735`, `trxstation/config.py:773`, `trxstation/config.py:779`, `trxstation/config.py:782` |
| ORT-9007 | erreur | Valeur de réglage mal formée | non | refus |  | `trxstation/config.py:495`, `trxstation/config.py:532`, `trxstation/config.py:535`, `trxstation/config.py:576`, `trxstation/config.py:580`, `trxstation/config.py:582`, `trxstation/config.py:587`, `trxstation/config.py:589`, `trxstation/config.py:595`, `trxstation/config.py:386`, `trxstation/config.py:389`, `trxstation/config.py:391`, `trxstation/config.py:400`, `trxstation/config.py:402`, `trxstation/config.py:405`, `trxstation/config.py:408`, `trxstation/config.py:411`, `trxstation/config.py:415`, `trxstation/config.py:417`, `trxstation/config.py:614`, `trxstation/config.py:630`, `trxstation/config.py:638`, `trxstation/config.py:668`, `trxstation/config.py:673`, `trxstation/config.py:743`, `trxstation/config.py:745`, `trxstation/config.py:768`, `trxstation/config.py:796`, `trxstation/config.py:807` |
| ORT-9008 | erreur | Seuils de réglage dans le mauvais ordre | non | refus |  | `trxstation/config.py:554`, `trxstation/config.py:739`, `trxstation/config.py:741`, `trxstation/config.py:776`, `trxstation/console.py:1662` |
| ORT-9009 | erreur | Réglages de sécurité d'émission incohérents | non | refus |  | `trxstation/config.py:546`, `trxstation/config.py:548`, `trxstation/config.py:550`, `trxstation/config.py:558` |
| ORT-9010 | CRITIQUE | rigctld exposé hors de la machine | non | refus |  | `trxstation/config.py:539` |
| ORT-9011 | CRITIQUE | Réglage réservé interdit dans extra_conf | non | refus |  | `trxstation/config.py:621` |
| ORT-9012 | erreur | Modèle ou port du poste manquant | non | refus |  | `trxstation/config.py:488`, `trxstation/config.py:490` |
| ORT-9013 | erreur | Méthode PTT inconnue | non | refus |  | `trxstation/config.py:497` |
| ORT-9014 | erreur | Bande d'émission mal définie | non | refus |  | `trxstation/config.py:649` |
| ORT-9015 | erreur | Deux services sur le même port | non | refus |  | `trxstation/config.py:593`, `trxstation/config.py:785`, `trxstation/config.py:636`, `trxstation/setup_wizard.py:178` |
| ORT-9016 | CRITIQUE | Module réglé pour tourner en root | non | refus |  | `trxstation/config.py:597` |
| ORT-9017 | erreur | Adresse de liaison refusée (non privée ou non chiffrée) | non | refus |  | `trxstation/config.py:763`, `trxstation/config.py:766`, `trxstation/config.py:794` |
| ORT-9018 | avert. | Modification de station.toml refusée | non | refus |  | `trxstation/console.py:604`, `trxstation/console.py:1118` |
| ORT-9019 | erreur | Enregistrement de station.toml impossible | non | refus |  | `trxstation/console.py:795`, `trxstation/console.py:800`, `trxstation/console.py:805` |
| ORT-9020 | avert. | station.toml illisible pour ce compte | non | refus |  | `trxstation/console.py:581`, `trxstation/console.py:732`, `trxstation/console.py:866`, `trxstation/console.py:1466`, `trxstation/console.py:1641`, `trxstation/console.py:628`, `trxstation/diagnostics.py:236` |
| ORT-9021 | avert. | Droits de station.toml incorrects | non | aucune |  | `trxstation/diagnostics.py:242`, `trxstation/diagnostics.py:245` |
| ORT-9022 | info | Station pas encore configurée | non | aucune |  | `trxstation/diagnostics.py:228`, `trxstation/console.py:401`, `trxstation/console.py:1747`, `debian/install.sh:171`, `debian/install.sh:505`, `windows/installer.ps1:428` |
| ORT-9023 | info | Aucun éditeur de texte | non | refus |  | `trxstation/console.py:585` |
| ORT-9101 | erreur | Profil de poste illisible ou abîmé | non | refus |  | `trxstation/profiles.py:105`, `trxstation/profiles.py:107`, `trxstation/profiles.py:111`, `trxstation/console.py:720`, `trxstation/console.py:729` |
| ORT-9102 | erreur | Profil de poste d'une autre version | non | refus |  | `trxstation/profiles.py:120`, `trxstation/profiles.py:126`, `trxstation/profiles.py:132` |
| ORT-9103 | erreur | Profil de poste refusé par la validation | non | refus |  | `trxstation/profiles.py:144`, `trxstation/profiles.py:151` |
| ORT-9104 | info | Nom de profil refusé | non | refus |  | `trxstation/console.py:695`, `trxstation/console.py:765` |
| ORT-9105 | erreur | secrets.toml illisible ou mal formé | non | refus |  | `trxstation/secretstore.py:56`, `trxstation/secretstore.py:60`, `trxstation/secretstore.py:63`, `trxstation/secretstore.py:67`, `trxstation/secretstore.py:110`, `trxstation/cluster/service.py:198`, `trxstation/diagnostics.py:485`, `trxstation/cluster/service.py:193`, `trxstation/cluster/service.py:195`, `trxstation/cluster/service.py:198`, `trxstation/cluster/setup.py:507`, `trxstation/cluster/setup.py:242` |
| ORT-9106 | avert. | Mot de passe de source refusé | non | refus |  | `trxstation/secretstore.py:42`, `trxstation/secretstore.py:44` |
| ORT-9107 | avert. | secrets.toml lisible par d'autres comptes | non | repli_correction_droits |  | `trxstation/secretstore.py:81`, `trxstation/cluster/service.py:192`, `trxstation/diagnostics.py:490` |
| ORT-9108 | avert. | Identifiant de station invalide | non | aucune |  | `trxstation/station_id.py:47`, `trxstation/station_id.py:70`, `trxstation/gateway/main.py:262` |
| ORT-9201 | avert. | Mise en page refusée | non | refus | `layout_invalid` | `trxstation/layout/store.py:76`, `trxstation/gateway/api/session.py:377`, `trxstation/layout/validate.py:66-199`, `trxstation/layout/validate.py:251-308` |
| ORT-9202 | avert. | Thème refusé (contraste ou couleur d'émission) | non | refus | `layout_invalid` | `trxstation/layout/theme.py:106`, `trxstation/layout/theme.py:115`, `trxstation/layout/palette.py:100`, `trxstation/layout/palette.py:103`, `trxstation/layout/validate.py:228`, `trxstation/layout/validate.py:238`, `trxstation/layout/validate.py:244` |
| ORT-9203 | avert. | Mise en page d'un format plus récent | non | refus | `layout_invalid` | `trxstation/layout/validate.py:266` |
| ORT-9204 | avert. | Mise en page enregistrée abîmée : profil d'usine servi | non | repli_profil_usine |  | `trxstation/layout/store.py:66` |
| ORT-9205 | info | Widget lié à une fonction absente du poste | non | aucune |  | `trxstation/layout/validate.py:110` |
| ORT-9301 | erreur | Python absent ou trop ancien | non | refus |  | `trxstation/diagnostics.py:173`, `debian/install.sh:343`, `windows/installer.ps1:238`, `windows/installer.ps1:244` |
| ORT-9302 | erreur | Modules Python manquants | non | refus |  | `trxstation/diagnostics.py:204`, `trxstation/diagnostics.py:445`, `debian/install.sh:428`, `debian/install.sh:253`, `windows/installer.ps1:309`, `trxstation/monitor/main.py:34`, `trxstation/tray/main.py:185`, `trxstation/update/signing.py:141` |
| ORT-9303 | avert. | Compte absent d'un groupe nécessaire | non | aucune |  | `trxstation/diagnostics.py:284`, `trxstation/diagnostics.py:287`, `debian/install.sh:322` |
| ORT-9304 | erreur | Paquet d'installation incomplet | non | refus |  | `debian/install.sh:47`, `debian/install.sh:282`, `debian/install.sh:284`, `debian/install.sh:246` |
| ORT-9305 | erreur | Droits administrateur nécessaires | non | refus |  | `debian/install.sh:94`, `debian/compiler-hamlib.sh:31` |
| ORT-9306 | erreur | Pas d'accès Internet pendant l'installation | non | refus |  | `debian/install.sh:318` |
| ORT-9307 | erreur | Installation des paquets Debian impossible | non | refus |  | `debian/install.sh:339`, `debian/install.sh:340`, `debian/compiler-hamlib.sh:40`, `debian/compiler-hamlib.sh:42` |
| ORT-9308 | erreur | Installation des modules Python impossible | non | refus |  | `debian/install.sh:422`, `debian/install.sh:419`, `windows/installer.ps1:298`, `windows/installer.ps1:303`, `windows/installer.ps1:305` |
| ORT-9309 | erreur | Installation de TRX distant ou activation de la version impossible | non | refus |  | `debian/install.sh:426`, `debian/install.sh:431`, `debian/install.sh:255`, `debian/install.sh:248`, `debian/install.sh:245`, `debian/install.sh:64`, `windows/installer.ps1:307` |
| ORT-9310 | avert. | Configuration refusée par la version installée | non | repli_config_precedente |  | `debian/install.sh:264`, `debian/install.sh:264` |
| ORT-9311 | CRITIQUE | Empreinte d'un module Python différente : installation arrêtée | non | arreter_installation |  | `debian/install.sh:422`, `debian/install.sh:419`, `windows/installer.ps1:298`, `windows/installer.ps1:303`, `windows/installer.ps1:305` |
| ORT-9501 | erreur | Journal Android illisible | non | refus |  | `trxstation/devtools/androidlog.py:596`, `trxstation/devtools/androidlog.py:362`, `trxstation/devtools/androidlog.py:620`, `trxstation/devtools/androidlog.py:589` |
| ORT-9502 | avert. | Téléphone : copie ou lecture du journal impossible | non | refus |  | `trxstation/devtools/androidlog.py:650`, `trxstation/devtools/androidlog.py:546`, `trxstation/devtools/androidlog.py:554` |
| ORT-9503 | avert. | Rapport HTML du journal Android non écrit | non | aucune |  | `trxstation/devtools/androidlog.py:604` |
| ORT-9504 | erreur | Application Android : plantage | non | aucune | `plantage` | *abandonné → AND-1001 (catalogue de l'application Android, AND-catalog.yaml)* |
| ORT-9505 | erreur | Application Android bloquée (ANR) | non | aucune | `blocage` | *abandonné → AND-1002 (catalogue de l'application Android, AND-catalog.yaml)* |
| ORT-9506 | avert. | Application Android : installation en échec | non | aucune | `installation` | *abandonné → AND-1003 (catalogue de l'application Android, AND-catalog.yaml)* |
| ORT-9507 | avert. | Application Android arrêtée par Android | non | aucune | `arret` | *abandonné → AND-1004 (catalogue de l'application Android, AND-catalog.yaml)* |
| ORT-9508 | info | Erreurs écrites par l'application Android | non | aucune | `erreur` | *abandonné → AND-1005 (catalogue de l'application Android, AND-catalog.yaml)* |
| ORT-9701 | erreur | Module pyserial absent (spectre HF) | non | repli_mode_normal | `no_pyserial` | `trxstation/spectrum/probe.py:53`, `trxstation/spectrum/service.py:382`, `trxstation/devtools/hwtest.py:441` |
| ORT-9702 | avert. | Fichier des mémoires illisible | non | repli_liste_vide |  | `trxstation/gateway/memories.py:149` |
| ORT-9703 | info | Mémoires indisponibles sur cette station | non | refus | `memories_unavailable` | `trxstation/gateway/api/session.py:336` |
| ORT-9704 | avert. | Fiche de qualification invalide | non | refus |  | `trxstation/qualif/main.py:67`, `trxstation/qualif/sheet.py:124`, `trxstation/qualif/sheet.py:154`, `trxstation/qualif/sheet.py:156`, `trxstation/qualif/sheet.py:114`, `trxstation/qualif/sheet.py:234` |
| ORT-9705 | info | Paramètre d'outil hors bornes | non | refus |  | `trxstation/devtools/hwtest.py:877`, `trxstation/devtools/hwtest.py:880`, `trxstation/devtools/hwtest.py:886`, `trxstation/devtools/hwtest.py:131`, `trxstation/qualif/main.py:150`, `trxstation/qualif/main.py:153`, `trxstation/qualif/main.py:167` |
| ORT-9706 | avert. | station.toml modifié mais invalide : comptes inchangés | non | nouvel_essai |  | `trxstation/gateway/access_watch.py:61`, `trxstation/gateway/access_watch.py:64` |
| ORT-9707 | CRITIQUE | Bibliothèque audio absente (sounddevice / PortAudio) | non | arreter_passerelle |  | `trxstation/gateway/audio/devices.py:186`, `trxstation/gateway/main.py:321` |
| ORT-9708 | erreur | Source ou sortie audio d'essai invalide | non | arreter_passerelle |  | `trxstation/gateway/audio/devices.py:100`, `trxstation/gateway/audio/devices.py:102`, `trxstation/gateway/audio/devices.py:107`, `trxstation/gateway/audio/devices.py:148`, `trxstation/gateway/audio/devices.py:314` |
| ORT-9709 | erreur | Modules WebRTC absents : API non démarrée | non | repli_reception_seule |  | `trxstation/gateway/main.py:246`, `trxstation/gateway/main.py:245-245` |
| ORT-9710 | avert. | Aucun compte client : pas d'API | non | repli_reception_seule |  | `trxstation/gateway/main.py:234`, `trxstation/gateway/main.py:234`, `trxstation/config.py:876`, `trxstation/gateway/main.py:234` |
| ORT-9711 | erreur | Exposition de l'API jugée dangereuse : API non démarrée | non | repli_reception_seule |  | `trxstation/gateway/main.py:238`, `trxstation/gateway/main.py:236-237`, `trxstation/config.py:850`, `trxstation/config.py:527`, `trxstation/gateway/main.py:238`, `trxstation/diagnostics.py:544` |
| ORT-9712 | avert. | Fichier de réglages de la station illisible | non | repli_valeurs_par_defaut |  | `trxstation/gateway/audio/beeps.py:145`, `trxstation/gateway/voice_profiles.py:155`, `trxstation/breizh/store.py:73`, `trxstation/netprobe/store.py:119` |
| ORT-9713 | erreur | Rapport de diagnostic impossible | non | refus |  | `trxstation/console.py:419` |
| ORT-9714 | erreur | Commande introuvable | non | refus |  | `trxstation/console.py:156`, `trxstation/console.py:201`, `windows/installer.ps1:183` |
| ORT-9715 | info | Option de commande inconnue ou invalide | non | refus |  | `debian/install.sh:88`, `debian/compiler-hamlib.sh:29`, `trxstation/setup_wizard.py:809`, `trxstation/setup_wizard.py:863` |
| ORT-9716 | erreur | Import de la configuration d'un autre PC impossible | non | refus |  | `trxstation/migrate.py:135`, `debian/install.sh:452`, `debian/install.sh:454`, `debian/install.sh:450` |
| ORT-9717 | info | Indicateur de bureau indisponible | non | aucune |  | `trxstation/console.py:344`, `trxstation/console.py:347`, `trxstation/console.py:351`, `trxstation/console.py:363`, `trxstation/tray/main.py:157` |
| ORT-9718 | info | Tests de la station indisponibles | non | refus |  | `trxstation/console.py:1689`, `trxstation/console.py:1698` |

### Application Android (préfixe AND)

Relevés par trx-journal-android dans les journaux des bêta-testeurs ; ORT-9504 à 9508 abandonnés à leur profit.

| Code | Remplace | Titre | Origines |
| --- | --- | --- | --- |
| AND-1001 | ORT-9504 | Application Android : plantage | `trxstation/devtools/androidlog.py:299`, `trxstation/devtools/androidlog.py:311`, `trxstation/devtools/androidlog.py:322`, `trxstation/devtools/androidlog.py:134` |
| AND-1002 | ORT-9505 | Application Android bloquée (ANR) | `trxstation/devtools/androidlog.py:259` |
| AND-1003 | ORT-9506 | Application Android : installation en échec | `trxstation/devtools/androidlog.py:279` |
| AND-1004 | ORT-9507 | Application Android arrêtée par Android | `trxstation/devtools/androidlog.py:271` |
| AND-1005 | ORT-9508 | Erreurs écrites par l'application Android | `trxstation/devtools/androidlog.py:284` |

## Doublons regroupés (même cause = même code)

| Code | Entrée gardée | Situations fusionnées |
| --- | --- | --- |
| ORT-1008 | Réglage non enregistré sur la station | Mémoires non enregistrées *(CAT)* ; Mise en page impossible à enregistrer *(configuration)* |
| ORT-1010 | Température du processeur élevée | Température du processeur élevée *(configuration)* |
| ORT-2001 | Port série du poste introuvable | Port série du poste introuvable *(PTT)* ; Port série du poste disparu pendant une émission *(CAT)* |
| ORT-2002 | rigctld ne démarre pas | rigctld ne démarre pas (test de liaison) *(configuration)* |
| ORT-2003 | Hamlib introuvable (rigctld ou rigctl) | rigctld introuvable *(PTT)* ; Hamlib (rigctl / rigctld) introuvable *(configuration)* |
| ORT-2005 | rigctld injoignable | rigctld injoignable *(PTT)* ; Liaison avec le poste perdue (affichage) *(configuration)* |
| ORT-2014 | Capacités du poste indisponibles (dump_caps) | Capacités du poste indisponibles *(PTT)* |
| ORT-2015 | Poste éteint ou débranché | Poste éteint ou débranché *(PTT)* |
| ORT-2200 | Version de Hamlib plus ancienne que la version qualifiée | Version de Hamlib trop ancienne *(configuration)* |
| ORT-3001 | Périphérique audio du poste absent | Périphérique audio du poste absent *(PTT)* ; Carte son du poste absente *(configuration)* |
| ORT-4015 | Élément demandé inconnu | Mémoire inconnue *(CAT)* |
| ORT-4017 | Demande de TRX Console ignorée | Demande de TRX Console ignorée *(modules internes)* |
| ORT-4101 | Certificat TLS inutilisable : API non démarrée | Certificat TLS inutilisable *(PTT)* ; Certificat HTTPS absent ou illisible *(configuration)* |
| ORT-4102 | Port de la passerelle impossible à ouvrir | Écoute réseau impossible *(PTT)* |
| ORT-4308 | Station surchargée : visiteurs déconnectés | Station surchargée : visiteurs déconnectés *(PTT)* |
| ORT-4310 | Réouverture de l'écoute des visiteurs refusée | Réouverture de l'écoute des visiteurs demandée *(PTT)* |
| ORT-5003 | L'ouverture du second port met le poste en émission | Le port du spectre a mis le poste en émission *(PTT)* ; Le poste passe en émission à l'ouverture du second port *(configuration)* |
| ORT-5013 | Le poste n'est pas passé en émission | Le poste n'est pas passé en émission *(CAT)* |
| ORT-5017 | Réglage modifié sur le poste pendant l'émission | Émission coupée : fréquence d'émission changée sur le poste *(CAT)* ; Émission coupée : mode changé sur le poste *(CAT)* |
| ORT-5018 | Le poste est repassé seul en réception | Le poste est repassé en réception de lui-même *(CAT)* |
| ORT-5019 | Liaison avec le poste perdue pendant l'émission | Émission coupée : liaison CAT perdue *(CAT)* ; Émission coupée : poste muet *(CAT)* |
| ORT-5020 | Retour en réception impossible | Défaut PTT : retour en réception impossible (affichage) *(configuration)* |
| ORT-5026 | rigctld injoignable pendant une émission | rigctld injoignable pendant une émission *(CAT)* |
| ORT-5106 | Émission refusée : aucune bande autorisée | Aucune bande autorisée : réception seule *(configuration)* |
| ORT-5108 | Émission refusée : split illisible | Split illisible : émission refusée *(CAT)* |
| ORT-5109 | Émission refusée : ΔTX (XIT) illisible | ΔTX (XIT) illisible : émission refusée *(CAT)* |
| ORT-5110 | Émission refusée : liaison avec le poste perdue | Commande ou émission refusée : liaison avec le poste perdue *(CAT)* |
| ORT-5111 | Émission refusée : le poste répond mal | Émission refusée : le poste ne répond pas correctement *(CAT)* |
| ORT-5112 | Émission refusée : état du PTT illisible | État du PTT illisible : émission refusée *(CAT)* |
| ORT-5113 | Émission refusée : le poste émet déjà | Le poste est déjà en émission *(CAT)* |
| ORT-5114 | Émission refusée dans ce mode | Émission refusée dans ce mode *(CAT)* |
| ORT-5116 | Réglage refusé pendant l'émission | Réglage du poste refusé pendant l'émission *(CAT)* |
| ORT-6409 | Aucune source du Cluster DX connectée | Module Cluster DX sans état récent ou source en échec *(configuration)* |
| ORT-6501 | Module extérieur déclaré mais absent ou non démarré | Breizh Audio Box ne répond pas *(audio)* ; Décodeur FreeDV introuvable *(audio)* ; Lancement d'un décodeur FreeDV impossible *(audio)* ; Module demandé introuvable *(modules internes)* ; Lancement du module impossible *(modules internes)* ; Module absent *(modules internes)* |
| ORT-6502 | Version du module incompatible | Version de protocole de Breizh Audio Box incompatible *(audio)* ; Version d'API du module incompatible *(modules internes)* |
| ORT-6503 | Échec de la négociation avec le module | Négociation avec Breizh Audio Box refusée (format, latence) *(audio)* ; Connexion d'un module refusée par la station *(modules internes)* |
| ORT-6504 | Le module ne répond plus (battement perdu) | Breizh Audio Box ne répond plus *(audio)* ; Décodeur FreeDV gelé *(audio)* |
| ORT-6507 | Le module perturbe la station (CPU, latence audio) | Module trop lent à lire : déconnecté *(modules internes)* |
| ORT-6531 | Clé d'appairage de Breizh Audio Box inutilisable | Breizh Audio Box non utilisé : clé illisible *(PTT)* ; Clé d'appairage Breizh absente ou illisible *(configuration)* |
| ORT-8003 | Passerelle muette | Passerelle muette (état figé ou absent) *(configuration)* |
| ORT-8008 | Mode sûr : station en réception, accès coupé | Mode sûr actif *(configuration)* |
| ORT-9001 | station.toml invalide | station.toml invalide ou introuvable (outil) *(CAT)* ; station.toml invalide *(PTT)* ; Configuration illisible pour un module *(modules internes)* |
| ORT-9105 | secrets.toml illisible ou mal formé | Fichier des mots de passe (secrets.toml) à corriger *(modules internes)* |
| ORT-9709 | Modules WebRTC absents : API non démarrée | API WebRTC indisponible : modules manquants *(PTT)* |
| ORT-9710 | Aucun compte client : pas d'API | Aucun compte autorisé : réception seule *(PTT)* ; Aucun compte d'accès : pas d'accès distant *(configuration)* |
| ORT-9711 | Exposition de l'API jugée dangereuse : API non démarrée | API non démarrée : exposition sans chiffrement *(PTT)* ; Page de la station exposée sans chiffrement : accès refusé *(configuration)* |

## Questions relevées pendant l'inventaire (détail, par code)

Questions de la partie 1, tranchées par l'utilisateur le 2026-11-11 (décisions plus haut) ; gardées comme trace.

- **ORT-1001** (Disque presque plein) : Le cahier écrit > 85 % ; le code alerte à disk_alert_pct = 90 % (config.py:248) ; le bargraph passe orange à 85 % (hostinfo.py:35). Une alerte par heure au plus.
- **ORT-1002** (Mémoire de la station presque pleine) : Seuil par défaut 90 % (config.py:247) ; CLAUDE.md note qu'il est peut-être trop bas sous Windows. Une alerte par heure au plus.
- **ORT-1005** (Fichier d'état de la passerelle non écrit) : Conséquence : le superviseur voit « gateway_silent » et relance la passerelle (voire « gateway_silent_tx » en émission) alors que la passerelle va bien.
- **ORT-1006** (Machine de la station chargée) : Affichage seul dans la page et l'application (opérateurs), sans journal ni alerte ; seuils différents de ceux du superviseur (mémoire 90 %, disque 90 %, processeur 80 °C). Harmoniser ?
- **ORT-1008** (Réglage non enregistré sur la station) : Plage 1000 (disque) ou 9000 (installation, droits) ? Un seul code avec {fonction}, ou un par fonction (codes protocole distincts) ?
- **ORT-1008** (Réglage non enregistré sur la station) : Aucun journal côté station (seulement le refus au client) : à journaliser ? Plage 1000 (disque) ou 9000 ?
- **ORT-1009** (Journal de la station non écrit) : Gravité différente aujourd'hui (log.error pour Breizh, warning pour la sonde) : harmoniser en avertissement ?
- **ORT-1010** (Température du processeur élevée) : Le cahier écrit > 75 °C ; le superviseur alerte à temp_alert_c = 80 °C (config.py:246) ; le bargraph de la page passe orange à 75 °C et rouge à 85 °C (hostinfo.py:35). Sous Windows, aucune mesure : jamais d'alerte.
- **ORT-1010** (Température du processeur élevée) : Seuils différents : cahier 75 °C, diagnostic 80 °C, trx-monitor 70 °C (orange) / 80 °C (rouge), superviseur temp_alert_c. Quel seuil unique retenir ?
- **ORT-1011** (Système d'exploitation non pris en charge) : L'installateur refuse (erreur) là où le diagnostic ne fait qu'avertir : une seule gravité ou deux entrées ?
- **ORT-1012** (Espace disque insuffisant) : Le cahier (ORT-1001) vise une alerte du superviseur à 85 % ; ici, seuils absolus (1 Go / 0,3 Go au diagnostic, MIN_FREE_MB à l'installation Debian, 2 Go sous Windows). Fusionner avec ORT-1001 ou garder une entrée « installation » ?
- **ORT-1020** (Horloge de la station refusée par le relais) : Cause identique à ORT-1020 (horloge désynchronisée) vue par la présence : un seul code 1020, ou 69xx en plus ?
- **ORT-1511** (Clé de signature des versions inutilisable (développement)) : Erreur d'outil de développement (scripts/gen_update_key.py, fabrication des paquets), jamais vue par un radioamateur : la garder dans le catalogue ?
- **ORT-2001** (Port série du poste introuvable) : Sans émission connue, ce cas devient « rig_absent » (alerte seule, entrée sup-poste-absent). « usb_missing » n'agit (reset USB) que si la dernière émission connue était en cours.
- **ORT-2001** (Port série du poste introuvable) : Superviseur hors de mon périmètre. usb_missing n'est gardé que pendant une émission (sinon remplacé par rig_absent) ; priorité ntfy par défaut (3) pour un cas critique.
- **ORT-2002** (rigctld ne démarre pas) : Seuls trx-hwtest et trx-qualif constatent aujourd'hui ce cas ; la passerelle et le superviseur ne voient qu'un rigctld injoignable (entrée cat-rigctld-injoignable). Rattacher ORT-2002 aussi à l'échec de démarrage du service rigctld par le superviseur (hors de mon périmètre) ?
- **ORT-2003** (Hamlib introuvable (rigctld ou rigctl)) : trx-rigctld s'arrête (code 3) : sous systemd, Restart=always relance en boucle. Faut-il une gravité critique quand c'est le service rigctld qui échoue (station sans CAT) et erreur seulement pour les outils ?
- **ORT-2003** (Hamlib introuvable (rigctld ou rigctl)) : Le cahier a ORT-2002 « rigctld ne démarre pas » ; ce cas (Hamlib absent) relève plutôt de l'installation (9000). À trancher.
- **ORT-2005** (rigctld injoignable) : Côté passerelle : nouvel essai seul (avertissement dans le journal) ; côté superviseur après rigctld_fail_s : alerte ntfy et relance de rigctld. Une seule entrée avec action « redemarrer_rigctld » (comportement du superviseur), ou deux codes (constat passerelle / décision superviseur) ? Le superviseur est hors de mon périmètre.
- **ORT-2005** (rigctld injoignable) : Le cahier dit « rigctld ne démarre pas » ; le code ne voit que « injoignable depuis rigctld_fail_s = 5 s » (après 30 s de grâce au démarrage), qu'il soit jamais démarré ou tombé ensuite. Une seule entrée suffit-elle ?
- **ORT-2005** (rigctld injoignable) : Affichage d'un état publié par la passerelle (perte CAT) : à rattacher au code CAT de l'inventaire de la passerelle.
- **ORT-2008** (Réponse du poste illisible) : Une réponse illisible pour la fréquence ou le mode met l'état du poste à « inconnu » (même effet qu'un poste muet) ; faut-il la fusionner avec cat-poste-muet ?
- **ORT-2010** (Le poste ne répond pas (rigctld répond)) : Aucune alerte ni journal côté passerelle hors émission (seulement last_error dans l'état publié) ; le superviseur voit-il ce cas ? À alerter après un délai ?
- **ORT-2012** (Mode ou fonction non géré par ce poste) : Le code protocole « invalid » sert aussi aux valeurs hors plage et à toute ValueError (texte de la page : « Valeur refusée par le poste. ») : créer des codes machine distincts (not_supported, out_of_range) ?
- **ORT-2014** (Capacités du poste indisponibles (dump_caps)) : Un format dump_caps non reconnu (capabilities.py:146, complete=False) bascule aussi en jeu minimal sans aucun message : à journaliser sous ce code ?
- **ORT-2015** (Poste éteint ou débranché) : Constaté par le superviseur (hors de mon périmètre). Le cahier met ORT-2001 « Port série introuvable » en critique ; le code le traite en alerte seule hors émission (rig_absent) et en escalade reset USB pendant une émission (usb_missing). Garder deux codes (ORT-2001 = usb_missing pendant l'émission) ?
- **ORT-2016** (Port du poste du profil absent) : Même cause que ORT-2001 (port série introuvable) mais simple avertissement au chargement d'un profil : fusionner ?
- **ORT-2017** (Le poste répond mal au test de liaison) : Proche de ORT-2104 (délai CAT) mais ici le poste répond par une erreur Hamlib : garder une entrée séparée ?
- **ORT-2020** (Tension d'alimentation du poste basse) : Seuil de 12 V propre à l'indicateur (Windows et GNOME) : aucune alerte ntfy ni affichage équivalent ailleurs. Faut-il un seuil réglable ?
- **ORT-2104** (Délai de réponse CAT dépassé) : Le cahier prévoit « {n} fois sur 5 min », ntfy et redemarrer_rigctld ; le code actuel ne compte pas les délais, ne les distingue pas d'une connexion fermée dans le journal (même message « liaison rigctld perdue ») et n'alerte pas : il referme et réessaie (3 s par commande). À compter et à distinguer ?
- **ORT-2200** (Version de Hamlib plus ancienne que la version qualifiée) : Seule origine : Catalog.lookup, non appelé en service. diagnostics.py:216 (hors périmètre) signale aussi « version de Hamlib illisible : le spectre exige Hamlib 4.6 ou plus ». Gravité du cahier (avertissement) conservée.
- **ORT-2309** (Erreur interne du spectre HF) : Le fil s'arrête définitivement après une erreur interne (pas de nouvel essai) : voulu ?
- **ORT-2310** (Réglage du spectre ou du filtre FIL refusé) : Cinq codes machine (bad_setting, spectrum_unavailable, spectrum_busy, spectrum_timeout, spectrum_refused) pour une même famille de refus bénins : un seul code ORT avec {raison}, ou un code par motif ?
- **ORT-2312** (Vérification du second port CI-V impossible) : Les textes détaillés viennent de CheckFailed (trxstation/spectrum/), hors de ce périmètre : à fusionner avec l'inventaire du spectre.
- **ORT-2313** (Spectre HF en panne (affichage)) : État publié par la passerelle (inventaire spectre) : ici seulement affiché.
- **ORT-2704** (Poste ou firmware non qualifié) : Catalog.lookup n'est appelé par aucun code en service aujourd'hui (seulement les tests) : entrée prévue pour plus tard ?
- **ORT-3001** (Périphérique audio du poste absent) : La passerelle QUITTE (code 5) alors que la règle du projet est de ne jamais quitter (le superviseur la relance en boucle, backends.py:233, jusqu'à l'escalade). Faut-il garder l'arrêt franc ou passer en « réception seule sans audio » ? Le code ORT doit-il être émis par la passerelle (avant de quitter) ou par le superviseur qui voit le code 5 ?
- **ORT-3001** (Périphérique audio du poste absent) : La passerelle sort (code 5) : le superviseur la relance en boucle et le constate comme « gateway_silent » (pas d'alerte propre à l'audio). Faut-il que la passerelle reste en vie sans audio, comme pour l'API ?
- **ORT-3002** (Essai : son reçu absent, muet ou saturé) : Hors de la plage CAT : à rapprocher de l'inventaire audio (3000).
- **ORT-3003** (Essai : audio d'émission non transmis ou ROS élevé) : ROS élevé (5000 ?) et audio non transmis (3000) mélangés dans le même essai : séparer ?
- **ORT-3004** (Ouverture du périphérique audio impossible) : Même question que audio-peripherique-introuvable (arrêt code 5, relances en boucle).
- **ORT-3005** (Son d'émission en retard ou haché) : Aucun journal ni alerte aujourd'hui : seulement des compteurs dans l'état et un repère de la sonde réseau. Seuil d'émission du code à fixer.
- **ORT-3007** (Traitement du son reçu en erreur) : Journalisé une seule fois puis plus jamais (_processor_failed) et jamais réarmé : faut-il une alerte ntfy, le SELCALL armé ne protégeant plus l'écoute ?
- **ORT-3010** (Sous-débits audio fréquents (xruns)) : Ces compteurs ne sont publiés NULLE PART aujourd'hui (AudioPipeline.stats(), pipeline.py:53, ne contient ni xruns ni overruns de la capture) et rien n'alerte : faut-il les publier et à partir de quel seuil (par minute) émettre ORT-3010 ?
- **ORT-4001** (Pertes réseau d'un client élevées) : Le cahier dit « > 5 % », le code alerte à [netprobe] loss_alert_pct = 10 % (palier rouge, réglable par type de réseau) : quel seuil retenir pour ORT-4001 ?
- **ORT-4004** (Connexion refusée : identifiant ou mot de passe) : Le verrouillage (freinage) n'est pas distingué dans le journal et n'alerte pas : faut-il un code séparé « essais freinés depuis {source} » avec alerte ntfy (port exposé attaqué) ?
- **ORT-4012** (Paramètres de commande refusés) : Regroupé volontairement (même préconisation) ; faut-il un code à part pour voice_profile_refused et layout_invalid, que l'opérateur peut corriger lui-même ?
- **ORT-4013** (Client trop bavard : messages ignorés) : Aucun journal côté station : faut-il journaliser (une fois par minute) un client qui dépasse la limite ?
- **ORT-4015** (Élément demandé inconnu) : Plage : 4000 (refus au client) ou 2000 (mémoires du poste) ? Le plafond « 200 mémoires au maximum » (memories.py:91) part en reason « invalid » : entrée à part ?
- **ORT-4101** (Certificat TLS inutilisable : API non démarrée) : Origine dans gateway/main.py (hors de mon périmètre strict) : vérifier qu'un autre agent ne l'a pas aussi catalogué (doublon à fusionner).
- **ORT-4102** (Port de la passerelle impossible à ouvrir) : Origine dans gateway/main.py : doublon possible avec l'agent processus / configuration.
- **ORT-4308** (Station surchargée : visiteurs déconnectés) : Le seuil de température (85 °C) diffère de ORT-1010 (75 °C, processeur) du cahier : deux codes distincts (protection des visiteurs vs alerte système) ou un seul ? Les dépassements (température, CPU, retard, mémoire) doivent-ils être des codes séparés ou une variable {depassement} ?
- **ORT-4308** (Station surchargée : visiteurs déconnectés) : Seuils dans overload.py (hors périmètre) : à dédoublonner avec l'inventaire réseau / visiteurs.
- **ORT-4501** (Coupure réseau d'un client) : Alerte ntfy seulement si la coupure dure au moins [netprobe] alert_outage_s (10 s), au plus une toutes les alert_cooldown_s (300 s). Un code par diagnostic (8 tronçons, préconisations différentes) ou un seul code avec {troncon} ?
- **ORT-4502** (Aller-retour réseau élevé) : Seulement affiché (indicateur rouge / orange) : aucun journal ni alerte. Faut-il un code pour un état seulement affiché ?
- **ORT-4503** (Profil VPN probablement partagé) : Trois variantes (same_time, alternate, pattern) avec des textes différents (vpn.py:115-122) : une entrée avec variantes de message ou trois codes ?
- **ORT-4504** (Horloge du client décalée) : Journal de la sonde seulement. Proche de ORT-1020 (horloge de la STATION) : même code ou code réseau à part ?
- **ORT-5001** (Durée maximale d'émission (TOT) atteinte) : Le cahier écrit « Timeout d'émission 3 min » et gravité critique ; le code a un TOT de 90 s par défaut (config.py:214, tot_s), plafond 120 s (tot_ceiling_s, config.py:215), et un TOT ABSOLU du superviseur de 135 s (tot_abs_s, config.py:232) qui est une autre entrée (sup-tot-absolu). Aucune valeur ne vaut 3 min. Le TOT de la passerelle est une coupure de sécurité normale, sans alerte ntfy : faut-il le garder en « avertissement » ou suivre le cahier (critique) ? À quel des deux TOT ORT-5001 doit-il correspondre ?
- **ORT-5002** (Retour forcé en réception : terminal perdu) : Deux codes machine (battement perdu, connexion fermée) pour une même cause : une seule entrée ORT-5002 avec {cause}, ou deux codes ? Le bip de liaison perdue (désactivé par défaut) précède la coupure (au plus 1,2 s).
- **ORT-5003** (L'ouverture du second port met le poste en émission) : Aucune alerte ntfy aujourd'hui (journal log.error seulement) pour une émission non commandée : en ajouter une ? Codes internes : ptt_on_open (spectre), spectrum_port_keyed (raison de coupure).
- **ORT-5003** (L'ouverture du second port met le poste en émission) : Hors de mon périmètre strict (spectrum/), cité parce que c'est une raison de retour en réception : à dédoublonner avec l'inventaire du spectre.
- **ORT-5004** (Émission pendant l'ouverture du second port (autre cause)) : La station coupe une émission qui n'est pas de son fait (micro du poste) alors que la règle « opérateur sur place » dit de ne jamais couper l'opérateur local : à confirmer par l'utilisateur.
- **ORT-5008** (Poste trop chaud : émission à distance coupée) : Sans effet sur l'IC-7300MK2 (TEMP_METER absent sous Hamlib). Seuils par défaut 40 / 50 °C (config.py:220-221).
- **ORT-5010** (PTT actif sans session cliente) : Avec le réglage par défaut allow_local_tx = true (« station partagée », config.py:250), ce cas n'est JAMAIS signalé ni coupé (seul le TOT absolu agit) : un PTT actif sans session cliente est alors traité comme une émission locale. Est-ce bien l'ORT-5010 du cahier ? Faut-il une alerte (sans coupure) en mode station partagée ?
- **ORT-5013** (Le poste n'est pas passé en émission) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5016** (Émission coupée par un autre client) : Le même code « toggle » sert aussi quand le PROPRIÉTAIRE relâche lui-même (ptt.py:276, fin normale) : le distinguer ?
- **ORT-5017** (Réglage modifié sur le poste pendant l'émission) : Quatre codes machine pour une même cause (réglage du poste changé) : une entrée avec {reglage} ou quatre codes ?
- **ORT-5017** (Réglage modifié sur le poste pendant l'émission) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ? Trois codes machine (frequency_changed, split_changed, xit_changed) regroupés ici avec {quoi}.
- **ORT-5017** (Réglage modifié sur le poste pendant l'émission) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5018** (Le poste est repassé seul en réception) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5019** (Liaison avec le poste perdue pendant l'émission) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ? Même code machine cat_down que le refus : deux codes ORT distincts proposés.
- **ORT-5019** (Liaison avec le poste perdue pendant l'émission) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5020** (Retour en réception impossible) : Le cahier ne la liste pas ; c'est pourtant la panne d'émission la plus grave. Priorité ntfy : le code n'envoie aucune priorité (3) ; faut-il 5 (urgent) ?
- **ORT-5020** (Retour en réception impossible) : Le défaut est levé par la passerelle (inventaire PTT 5000) : ici seulement affiché. Fusionner.
- **ORT-5024** (TOT absolu dépassé : coupure par le superviseur) : TOT absolu = 135 s par défaut (config.py:232), plus proche des « 3 min » du cahier que le TOT de 90 s : ORT-5001 devrait-il être celui-ci ? Action : « T 0 » à chaque passage ; échelle de reprise (redémarrage passerelle…) seulement si l'émission venait de la passerelle ou résiste 5 s de plus.
- **ORT-5026** (rigctld injoignable pendant une émission) : Constaté par le superviseur (hors de mon périmètre), cité pour la plage CAT ; priorité ntfy aujourd'hui par défaut (3) alors que le cas est critique : monter à 5 ?
- **ORT-5027** (« T 0 » du superviseur non confirmé) : Seulement journalisé, aucune alerte ntfy propre (le problème qui a causé le « T 0 » est alerté par ailleurs). Faut-il une alerte dédiée ?
- **ORT-5101** (Émission refusée : défaut verrouillé) : Aucun moyen d'effacer le défaut n'est exposé aujourd'hui en dehors de clear_fault() (ptt.py:242) : quelle commande ou quel menu de TRX Console l'opérateur doit-il utiliser ? (redémarrer la passerelle l'efface de fait).
- **ORT-5108** (Émission refusée : split illisible) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5109** (Émission refusée : ΔTX (XIT) illisible) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5110** (Émission refusée : liaison avec le poste perdue) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5111** (Émission refusée : le poste répond mal) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5112** (Émission refusée : état du PTT illisible) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5113** (Émission refusée : le poste émet déjà) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5114** (Émission refusée dans ce mode) : Chevauchement avec le périmètre PTT (5000) : refus d'émission dont la cause est la liaison CAT ou le poste ; garder dans la plage 5000 ou rattacher à 2000 ?
- **ORT-5116** (Réglage refusé pendant l'émission) : Chevauche le périmètre PTT (safety/ptt.py) : à fusionner avec l'inventaire PTT.
- **ORT-5507** (Mesure de TOS arrêtée : émission refusée) : Le code renvoyé est celui du refus PTT (local_active, out_of_band...) : faut-il un code ORT propre à la mesure, avec le code PTT en contexte ?
- **ORT-5901** (Essai : état PTT relu incohérent) : « prise d'émission refusée » reprend le motif Refused de la station (déjà catalogué ailleurs) : garder une entrée d'essai distincte ?
- **ORT-6401** (Cluster DX activé mais incomplet) : Doublon possible avec l'inventaire du module Cluster DX (plage 6400) : garder ici la seule validation de station.toml ?
- **ORT-6408** (Bascule vers un autre cluster) : Aucun message n'est journalisé à la bascule elle-même (seul l'état FAILED apparaît) : faut-il un message explicite ?
- **ORT-6409** (Aucune source du Cluster DX connectée) : Une entrée (rouge) ou deux (rouge = aucune source, orange = en partie / pas de spot depuis 15 min) ? Aucune alerte ntfy aujourd'hui.
- **ORT-6409** (Aucune source du Cluster DX connectée) : Relève surtout de l'inventaire du module Cluster DX : garder ici seulement l'origine « diagnostic ».
- **ORT-6501** (Module extérieur déclaré mais absent ou non démarré) : Quand Breizh est simplement arrêté, la station reste en « connecting » SANS journal ni événement (seule une erreur de socket est journalisée) : faut-il émettre ORT-6501 après N HELLO sans réponse ?
- **ORT-6501** (Module extérieur déclaré mais absent ou non démarré) : À dédoublonner avec l'inventaire FreeDV.
- **ORT-6501** (Module extérieur déclaré mais absent ou non démarré) : Rapproché d'ORT-6501 (module déclaré mais absent), prévu pour les modules extérieurs : même code pour un module interne ?
- **ORT-6501** (Module extérieur déclaré mais absent ou non démarré) : Plage 6500 proposée pour les erreurs du bus des modules INTERNES, alors que le cahier réserve ORT-6501 à 6508 aux modules extérieurs : garder 6501-6508 pour les deux (même constat par la station), ou ouvrir une sous-plage à part (ex. 6520-6599 pour le bus interne, ou 6100) ?
- **ORT-6501** (Module extérieur déclaré mais absent ou non démarré) : À dédoublonner avec l'inventaire des modules.
- **ORT-6501** (Module extérieur déclaré mais absent ou non démarré) : Plage 6500 proposée pour les erreurs du bus des modules INTERNES, alors que le cahier réserve ORT-6501 à 6508 aux modules extérieurs : garder 6501-6508 pour les deux (même constat par la station), ou ouvrir une sous-plage à part (ex. 6520-6599 pour le bus interne, ou 6100) ?
- **ORT-6502** (Version du module incompatible) : Plage 6500 proposée pour les erreurs du bus des modules INTERNES, alors que le cahier réserve ORT-6501 à 6508 aux modules extérieurs : garder 6501-6508 pour les deux (même constat par la station), ou ouvrir une sous-plage à part (ex. 6520-6599 pour le bus interne, ou 6100) ?
- **ORT-6503** (Échec de la négociation avec le module) : Plage 6500 proposée pour les erreurs du bus des modules INTERNES, alors que le cahier réserve ORT-6501 à 6508 aux modules extérieurs : garder 6501-6508 pour les deux (même constat par la station), ou ouvrir une sous-plage à part (ex. 6520-6599 pour le bus interne, ou 6100) ? Codes du bus : hello, auth (et api, entrée à part).
- **ORT-6507** (Le module perturbe la station (CPU, latence audio)) : Rapproché d'ORT-6507 (module qui perturbe la station). Les messages jetés quand la file d'un module est pleine (bus.py:198, compteur dropped) ne sont que comptés : à cataloguer ?
- **ORT-6511** (Manifeste de module invalide) : Plage 6500 proposée pour les erreurs du bus des modules INTERNES, alors que le cahier réserve ORT-6501 à 6508 aux modules extérieurs : garder 6501-6508 pour les deux (même constat par la station), ou ouvrir une sous-plage à part (ex. 6520-6599 pour le bus interne, ou 6100) ? Les ManifestError de manifest.py:85-153 (13 raise) sont regroupés ici.
- **ORT-6515** (Clé des modules invalide) : Côté superviseur, une clé absente ou illisible n'est PAS signalée (launcher._spawn attend en silence, module « en attente ») : faut-il une alerte après un délai ?
- **ORT-6517** (Arrêt inattendu d'un module) : Proche d'ORT-8001 (redémarrage d'un processus par le superviseur) : code 8001 avec {processus} = module, ou code propre en 65xx ?
- **ORT-6519** (Station injoignable depuis un module) : Aucun délai de battement n'est appliqué aux modules internes (bus.py ne fait qu'afficher heartbeat_age_s) : ORT-6504 (battement perdu) n'a pas d'équivalent interne aujourd'hui. À ajouter ?
- **ORT-6520** (Commande de module refusée pendant l'émission) : Refus lié à la sécurité d'émission : plage 5000 (PTT) ou 6500 (bus des modules) ?
- **ORT-6522** (Commande non disponible) : Codes machine distincts aujourd'hui : unavailable, unknown_op, unknown_command (une entrée ou trois ?).
- **ORT-6525** (Changement de fréquence demandé par un module refusé) : Les raisons du refus (Refused.reason, rig_error, cat_down) sont celles de la passerelle : l'entrée doit-elle renvoyer au code CAT / PTT d'origine plutôt qu'à un code de module ?
- **ORT-6526** (Jeton de session refusé) : Codes : token_malformed, token_signature, token_expired, token_revoked ; une signature fausse mérite-t-elle une entrée à part (gravité plus haute, sécurité) ?
- **ORT-6528** (Fichier d'un module non écrit) : Cause « disque plein » : renvoyer plutôt à ORT-1001 (plage système) ?
- **ORT-6531** (Clé d'appairage de Breizh Audio Box inutilisable) : Plage 6500 (liaison) ou 9000 (configuration) ? key_problem() est présenté comme « problème BLOQUANT » de configuration alors que la passerelle continue sans Breizh.
- **ORT-6531** (Clé d'appairage de Breizh Audio Box inutilisable) : Rapprochement avec ORT-6503 (« échec de la négociation ») approximatif ; à dédoublonner avec l'inventaire Breizh.
- **ORT-6531** (Clé d'appairage de Breizh Audio Box inutilisable) : Doublon possible avec l'inventaire Breizh (6500) côté passerelle.
- **ORT-6533** (Repli pendant l'émission : fin en direct) : Le repli ne coupe JAMAIS l'émission (règle du cahier Breizh) : à garder en avertissement. Code distinct de ORT-6504 (Breizh perdu hors émission) : à confirmer.
- **ORT-6534** (Blocs de son revenus trop tard de Breizh Audio Box) : Compteur seulement (state.breizh.late), aucun journal : faut-il un code et un seuil ?
- **ORT-6535** (Mode OpenRemoteTRX non activé dans Breizh Audio Box) : Rattacher à ORT-6501 (module non démarré) ou garder un code propre ?
- **ORT-6538** (Réponse de Breizh Audio Box mal formée) : Défaut interne de Breizh : code ORT (la station le constate) ou code BZA du module ?
- **ORT-6539** (Paquets de Breizh Audio Box refusés) : Un tag refusé en nombre = clé différente OU tentative d'injection : code séparé pour « clé différente » (préconisation précise) ?
- **ORT-6540** (Breizh Audio Box joint ou repris) : Événement normal, pas une erreur : utile au monitor inter-stations (ORT-65xx info) ou à exclure du catalogue ?
- **ORT-6561** (Décodeur FreeDV arrêté) : Plantage interne du décodeur : relèverait plutôt du préfixe FDV ; la station ne voit que le code de sortie (ORT-6504 ?).
- **ORT-6562** (Sortie d'un décodeur FreeDV illisible) : Format de sortie du décodeur : ORT-6503 (interface) ou ORT-6502 (version incompatible) ?
- **ORT-6563** (FreeDV abandonné après ses relances) : Aucune alerte ntfy aujourd'hui (seulement les clients connectés) : en faut-il une ? Équivalent de ORT-8002 (boucle de redémarrages) pour un processus enfant de la passerelle.
- **ORT-6564** (Mode FreeDV en erreur dans la chaîne audio) : Journalisé une seule fois (_freedv_failed) et l'état publié reste « écoute » : les clients ne le voient pas.
- **ORT-6565** (Décodeur FreeDV trop lent : son jeté) : Compteur seulement (trx-monitor) ; rapprocher de ORT-6507 (le module perturbe la station) ?
- **ORT-6801** (Essai SELCALL : RIT refusé ou illisible) : Le résultat « SELCALL : RIEN décodé » (hwtest.py:354) relève plutôt de l'inventaire SELCALL (6800).
- **ORT-6803** (Appel SELCALL refusé : plus long que le TOT) : À dédoublonner avec l'inventaire SELCALL (même code).
- **ORT-6805** (Appel SELCALL reçu) : Événement normal (pas une erreur) mais alerte ntfy par défaut ([selcall] notify_on_call = true) : le catalogue d'erreurs doit-il aussi porter les événements d'information de ce type ? Le code SELCALL n'est jamais dans l'alerte (décision 2026-11-09) : garder {code} hors du message.
- **ORT-6809** (SELCALL non disponible) : Origines dans gateway/api/session.py (périmètre passerelle) : à dédoublonner avec l'agent de la passerelle.
- **ORT-6810** (Appel SELCALL impossible : aucun code armé) : Origine dans gateway/api/session.py : à dédoublonner avec l'agent de la passerelle.
- **ORT-6811** (Code SELCALL invalide) : Le refus client porte le code générique invalid_params (protocole) : faut-il un code machine propre au SELCALL ?
- **ORT-6903** (Relais de présence injoignable) : relay.py:22 précise « sans alerte » : confirmer qu'aucune alerte ntfy n'est voulue, même après une longue coupure ?
- **ORT-6908** (Liste des membres d'un groupe refusée) : Motifs regroupés (signature, signer, chain, key_changed, rotation_missing, no_admin, admin_rights, version, group, malformed) : une signature fausse (attaque possible) mérite-t-elle une entrée à part, plus grave ?
- **ORT-6913** (Invitation refusée) : Codes : invitation_malformed, invitation_relay_mismatch, invitation_expired, other_relay, already : une entrée ou plusieurs ?
- **ORT-6918** (Saisie refusée (présence de groupe)) : Codes machine : pseudo, text, shack, name, share, args, unknown_action (une entrée regroupée, comme pour la validation de configuration).
- **ORT-6919** (Présence de groupe non disponible) : Origines dans gateway/api/session.py : à dédoublonner avec l'agent de la passerelle ; friends_error = erreur inattendue (entrée à part ?).
- **ORT-6920** (Fichier de clés de la présence illisible) : Aujourd'hui l'exception n'est pas rattrapée : le module s'arrête, le superviseur le relance puis le désactive (module-boucle-arrets). Faut-il un message clair au démarrage ?
- **ORT-8001** (Redémarrage d'un processus par le superviseur) : action_auto vaut redemarrer_passerelle (niveau 0) ou redemarrer_rigctld (niveau 1) selon le niveau : deux codes distincts ? En mode géré, la relance d'un processus qui s'est arrêté seul (backends.py:233) n'envoie aucune alerte ntfy.
- **ORT-8002** (Module désactivé après des arrêts répétés) : Proche d'ORT-8002 (boucle de redémarrages, > 3 en 10 min) ; le code actuel : plus de 5 arrêts en 300 s (RestartPolicy). Code 8002 ou 65xx ? Seuils à aligner ?
- **ORT-8003** (Passerelle muette) : Doublon probable avec l'entrée « passerelle muette » du superviseur (8000) : un seul code, affiché par trx-monitor et l'indicateur.
- **ORT-8005** (Réinitialisation USB impossible) : Sous Windows, rien n'est fait (pas même la relance de rigctld) ; sous Linux (systemd), rigctld est relancé même si la réinitialisation a échoué.
- **ORT-8006** (Redémarrage de la machine par le superviseur) : Pas d'alerte ntfy propre au redémarrage : seule « Reprise : reboot » part (core.py:339), avant le redémarrage. Sur un PC de bureau max_reboots_per_hour = 0 : ce niveau devient directement le mode sûr.
- **ORT-8007** (Redémarrage refusé : historique non inscriptible) : Passerelle arrêtée sans alerte ntfy dédiée (seule « Reprise : reboot » est partie juste avant).
- **ORT-8008** (Mode sûr : station en réception, accès coupé) : Le cahier dit « Boucle de redémarrages (> 3 en 10 min), processus arrêté » ; le code compte les redémarrages de la MACHINE par heure (max_reboots_per_hour = 3, config.py:234) et passe en mode sûr global ; aucune limite de relances de processus en 10 min n'existe (la passerelle peut être relancée indéfiniment tous les recovery_wait_s = 20 s, mais l'échelle monte d'un niveau à chaque fois).
- **ORT-8008** (Mode sûr : station en réception, accès coupé) : Affichage seulement dans ce périmètre ; le déclenchement (et l'alerte ntfy) relève de l'inventaire du superviseur : fusionner sous le même code.
- **ORT-8013** (Alerte ntfy non envoyée) : Une notify_url absente ou non http(s) désactive les alertes sans aucun message (notify.py:40-41). À signaler à l'installation ?
- **ORT-8014** (Boucle de supervision en erreur) : En mode géré (Windows, tâche planifiée), personne ne relance le superviseur après cette sortie : la passerelle s'arrête alors aussi (--parent-pid). À confirmer.
- **ORT-8019** (Erreur inattendue d'un composant (la station continue)) : Regroupement de tous les log.exception « garde-fou » : faut-il un code générique par plage (3xxx audio, 4xxx réseau, 65xx modules) plutôt qu'un seul 8xxx ?
- **ORT-9001** (station.toml invalide) : La passerelle et le superviseur quittent avec le code 2 (pas d'alerte ntfy possible : l'URL est dans le fichier refusé). Faut-il un message distinct pour « TOML illisible » (syntaxe) et « réglage refusé » (validation) ?
- **ORT-9001** (station.toml invalide) : Mêmes problèmes de validation que ORT-9001 (inventaire configuration) : simple origine supplémentaire de ORT-9001 ?
- **ORT-9001** (station.toml invalide) : Les règles de validation elles-mêmes sont dans config.py (hors de ce périmètre). La passerelle qui sort en code 2 en mode géré est relancée chaque seconde par le superviseur (backends.py:233).
- **ORT-9001** (station.toml invalide) : Même cause que ORT-9001 (station.toml invalide) vue depuis un module : fusionner avec l'entrée de l'agent configuration ?
- **ORT-9009** (Réglages de sécurité d'émission incohérents) : Le cahier (ORT-5001) parle d'un « timeout d'émission 3 min » ; le code a tot_s = 90 s (plafond 120 s) et tot_abs_s = 135 s. Quel texte garder dans le catalogue ?
- **ORT-9105** (secrets.toml illisible ou mal formé) : secrets.toml sert à toute la station (secretstore) : plage 9000 plutôt que 6400 ?
- **ORT-9308** (Installation des modules Python impossible) : Un seul message mêle panne réseau et empreinte différente (sécurité) : faut-il les séparer (le code pip ne permet pas de distinguer aujourd'hui) ?
- **ORT-9501** (Journal Android illisible) : Plage à choisir pour l'application Android et ses outils (aucune plage dédiée dans le cahier) : 9000 provisoire, ou préfixe à part (ex. ORA) ?
- **ORT-9502** (Téléphone : copie ou lecture du journal impossible) : Plage à choisir pour l'application Android et ses outils (aucune plage dédiée dans le cahier) : 9000 provisoire, ou préfixe à part (ex. ORA) ?
- **ORT-9503** (Rapport HTML du journal Android non écrit) : Plage à choisir pour l'application Android et ses outils (aucune plage dédiée dans le cahier) : 9000 provisoire, ou préfixe à part (ex. ORA) ?
- **ORT-9504** (Application Android : plantage) : Plage à choisir pour l'application Android et ses outils (aucune plage dédiée dans le cahier) : 9000 provisoire, ou préfixe à part (ex. ORA) ? Plantage Java et plantage natif regroupés : séparer (préconisations proches) ?
- **ORT-9505** (Application Android bloquée (ANR)) : Plage à choisir pour l'application Android et ses outils (aucune plage dédiée dans le cahier) : 9000 provisoire, ou préfixe à part (ex. ORA) ?
- **ORT-9506** (Application Android : installation en échec) : Plage à choisir pour l'application Android et ses outils (aucune plage dédiée dans le cahier) : 9000 provisoire, ou préfixe à part (ex. ORA) ?
- **ORT-9507** (Application Android arrêtée par Android) : Plage à choisir pour l'application Android et ses outils (aucune plage dédiée dans le cahier) : 9000 provisoire, ou préfixe à part (ex. ORA) ?
- **ORT-9508** (Erreurs écrites par l'application Android) : Plage à choisir pour l'application Android et ses outils (aucune plage dédiée dans le cahier) : 9000 provisoire, ou préfixe à part (ex. ORA) ?
- **ORT-9709** (Modules WebRTC absents : API non démarrée) : Origine dans gateway/main.py : doublon possible avec l'agent installation.
- **ORT-9710** (Aucun compte client : pas d'API) : Origine dans gateway/main.py : doublon possible avec l'agent configuration.
- **ORT-9711** (Exposition de l'API jugée dangereuse : API non démarrée) : Les textes exacts viennent de config.exposure_problem (périmètre configuration) : une entrée par règle ou une seule entrée avec {probleme} ?

## Situations écartées du catalogue

| Domaine | Catégorie | Nombre |
| --- | --- | --- |
| CAT, Hamlib, spectre, essais | erreurs de programmation (arguments invalides entre fonctions, liste fermée CI-V) | 30 |
| CAT, Hamlib, spectre, essais | assertions | 1 |
| CAT, Hamlib, spectre, essais | except silencieux d'un cas normal (port déjà perdu, boucle fermée, fichier absent, fin de flux, lecture facultative) | 34 |
| CAT, Hamlib, spectre, essais | annulation par l'utilisateur (Ctrl+C, essai annulé, étape ignorée ou non confirmée) | 22 |
| CAT, Hamlib, spectre, essais | écouteurs défaillants journalisés (log.exception d'un rappel interne) | 2 |
| PTT, superviseur, système | erreurs de programmation (arguments invalides, assertions) | 7 |
| PTT, superviseur, système | except internes qui journalisent un défaut de programmation sans effet pour l'utilisateur | 8 |
| PTT, superviseur, système | except qui avalent un cas normal (fichier absent, capteur absent, Windows, fin de flux) | 21 |
| PTT, superviseur, système | raisons de fin d'émission normales (pas des erreurs) | 6 |
| PTT, superviseur, système | re-raise / annulation asyncio | 5 |
| audio, réseau, API, Breizh, FreeDV | erreurs de programmation (arguments invalides entre fonctions) | 17 |
| audio, réseau, API, Breizh, FreeDV | NotImplementedError / assertions | 3 |
| audio, réseau, API, Breizh, FreeDV | paquets Breizh invalides levés puis comptés (agrégés dans breizh-paquets-refuses) | 14 |
| audio, réseau, API, Breizh, FreeDV | except qui avalent un cas normal (fichier absent, fin de flux, annulation, fermeture simultanée) | 26 |
| audio, réseau, API, Breizh, FreeDV | re-raise après nettoyage (sans message) | 6 |
| audio, réseau, API, Breizh, FreeDV | validations de paramètres client déjà couvertes par protocole-parametres-invalides (une entrée pour toutes) | 48 |
| audio, réseau, API, Breizh, FreeDV | journaux d'information normaux (démarrage, mode choisi, réglage fait) | 14 |
| audio, réseau, API, Breizh, FreeDV | refus liés à l'émission (PTT, TOS, SELCALL : autre agent) | 9 |
| configuration, installation, console, mises à jour | erreurs de programmation (arguments invalides entre fonctions) | 3 |
| configuration, installation, console, mises à jour | except qui avalent un cas normal (fichier absent attendu, lecture d'état ratée sans conséquence, en-tête de la console) | 24 |
| configuration, installation, console, mises à jour | version publiée suspecte écartée sans message (release_from_github / Release.problem renvoient None) | 1 |
| configuration, installation, console, mises à jour | re-raise après nettoyage (fichier temporaire) | 3 |
| configuration, installation, console, mises à jour | annulations et saisies de l'utilisateur (Annulé, Abandon, Interrompu, choix invalide, menu inexistant) | 20 |
| configuration, installation, console, mises à jour | informations sans erreur (aucun profil, aucun compte, aucune mesure, écoute des visiteurs fermée) | 10 |
| modules internes, cluster, SELCALL, présence | erreurs de programmation (arguments invalides entre fonctions, ValueError internes) | 24 |
| modules internes, cluster, SELCALL, présence | validation de données reçues remontée sous un code d'une entrée déjà cataloguée (Malformed, ValueError de parse) | 30 |
| modules internes, cluster, SELCALL, présence | except qui avalent un cas normal (fichier absent attendu, fin de flux, annulation asyncio, message facultatif perdu) | 26 |
| modules internes, cluster, SELCALL, présence | outil de développement (devtools : listener_load, station_load, presence_buddy, breizh_probe, fake_*, cat_raw, civ_dual, civ_scope, client_cli, hamlib_scope, latency, loopback, sample_caps ; démo des modules ; outil en ligne de commande trxstation.cluster) | 160 |
| modules internes, cluster, SELCALL, présence | messages d'information normaux (log.info : connexion, lancement, armement…) | 25 |
