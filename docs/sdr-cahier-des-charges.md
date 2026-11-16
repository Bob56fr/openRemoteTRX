# openRemoteTRX — Cahier des charges du module SDR (v3)

- v1 : 2026-11-07, rédigée par l'utilisateur.
- v2 : 2026-11-15 (étape 183), relecture commentée avec l'utilisateur : décisions marquées
  **[D 2026-11-15]**, relevé de minix-bzh (§ 2.4), découpage des lots revu (§ 15).
- Essai S0 FAIT sur minix-bzh le 2026-11-15 (étape 184) et S0 bis en C (étape 185) : résultats et décisions au § 16.
- v3 : 2026-11-16 (étape 196), demandes de l'utilisateur : clés **RTL-SDR** (§ 2.4.1), menu **5.4 « Récepteur
  SDR »** de TRX Console avec recherche sur tous les ports USB et hubs (§ 2.4.2), autorité de certification de la
  station (étape 195, hors SDR), lot « confort » (§ 15).
- Lot S1a FAIT (étape 188, station 0.140.0) : `trxstation/sdr/` (sdr-core en C, module « sdr », `trx-sdr`),
  commande `sdr`, rubrique « SDR » de la page ; protocole : `docs/protocole.md` § 18.

## 1. Objet et périmètre

Le module SDR ajoute à openRemoteTRX un récepteur SDR utilisé en parallèle du TRX : second
waterfall, démodulation, décodage numérique, scan de banques et réception auto-adaptative. Le SDR
est en réception seule ; il n'émet jamais.

Principes directeurs :

- **Le TRX reste prioritaire.** Une surcharge ou une panne du module SDR ne doit jamais dégrader
  le pilotage du TRX, son audio ni le PTT. C'est la PASSERELLE qui en juge (§ 2.3).
- **Indépendance matérielle.** Le module ne dépend d'aucun modèle de SDR ; chaque modèle est décrit
  par une fiche (§ 3). Matériel de référence : SDRplay RSP2pro.
- **Plusieurs SDR sur une même machine** : chaque SDR est désigné par son NUMÉRO DE SÉRIE, jamais
  par son port ni par son rang (§ 2.4).
- **Tout automatisme est visible, expliqué et réversible** (§ 12).
- **Le traitement lourd reste sur la station.** Les clients ne reçoivent que des lignes de
  waterfall compressées, de l'audio et du texte décodé, jamais d'IQ brut.
- **Protection matérielle à la charge de l'opérateur [D 2026-11-15].** La protection de l'entrée
  du SDR contre la puissance émise par le TRX (antenne séparée, séquenceur, commutateur qui met
  l'entrée à la masse au repos, parafoudre) relève de l'opérateur, technicien de sa station. Elle
  est décrite dans une partie du guide de l'opérateur (`User-Guide/`) et rappelée par l'assistant,
  qui la fait cocher. La documentation dit franchement ce que la station NE garantit PAS :
  une émission faite au micro du poste n'est vue qu'après coup (interrogation de rigctld), donc
  aucune mesure logicielle (LNA minimal, relais piloté) ne protège l'entrée à temps.

## 2. Architecture côté station

### 2.1 Un module du bus existant [D 2026-11-15]

La v1 prévoyait un moteur autonome avec sa propre API REST / WebSocket et sa propre console web.
Retenu à la place : un **module de la station** sur le bus existant (`docs/modules.md` :
127.0.0.1, secret dérivé de `modules.key`, manifeste, lancé par le superviseur à priorité basse
sous `run_as`, relancé, désactivé après 5 arrêts en 5 min). Raisons : pas de seconde surface
d'authentification, pas de second serveur web à sécuriser, mêmes règles que le Cluster DX, la
présence et FreeDV.

- Accès distant UNIQUEMENT par la passerelle (authentification habituelle, opérateurs / visiteurs).
- Pas de console web propre au moteur. Un mode « SDR seul » (écouteurs sans TRX) se fera plus tard
  par la même station avec une liste de bandes vide (réception seule), pas par un second serveur.
- OpenAPI / AsyncAPI, négociation de versions et widgets décrits par le moteur : REPORTÉS au jour où
  un moteur tiers existera. Le contrat est `docs/protocole.md` (nouvelles commandes, `hello.features`
  avec `sdr`), comme pour toute fonction facultative.
- Sans `sdr` dans `[modules] run`, ou module arrêté : la station se comporte exactement comme
  aujourd'hui, rien de SDR n'apparaît dans les clients.

| Processus (enfants du module) | Rôle | Priorité |
| --- | --- | --- |
| `sdr-core` | Acquisition IQ, FFT, canaliseur, démodulation, gain automatique | Basse, bridable |
| `sdr-decoders` | Décodeurs numériques (un sous-processus par décodeur actif) | Plus basse |
| `sdr-learner` | Mesures, base d'apprentissage, propositions | La plus basse |

### 2.2 Données entre le module et la passerelle

- Commandes, état, lignes de waterfall, texte décodé : messages du bus (`client_message`,
  `scope: "operators"` quand il le faut ; commandes clients par `call` avec le droit
  `client_commands`). Une ligne de waterfall reste sous la limite de 64 ko du canal de données.
- Audio : PCM 48 kHz du module vers la passerelle par une liaison locale (127.0.0.1, authentifiée
  comme le bus) ; la passerelle en fait la SECONDE piste WebRTC (§ 13.3). L'encodage Opus de cette
  piste coûte du CPU à la passerelle : mesuré en S0, et c'est la première chose que la passerelle
  coupe en cas de surcharge (§ 2.3).
- **Droits sur le TRX** : le module n'écrit JAMAIS au poste. « Envoyer cette fréquence au TRX » est
  une commande du CLIENT relayée par la passerelle (opérateur seulement, refusée pendant
  l'émission, contrôle des bandes, `PttController`), ou la commande `qsy` du bus déjà existante.
  Les réglages du TRX dont l'apprentissage a besoin (§ 10) sont lus sur le bus d'état publié par la
  passerelle, JAMAIS par une seconde connexion à rigctld.

### 2.3 Charge : la passerelle décide [D 2026-11-15]

- Le module **surveille sa propre consommation** (CPU, mémoire de chaque processus), la publie
  (page, application, trx-monitor) et se bride seul au-delà de plafonds réglables.
- La **passerelle juge sa propre qualité de service** (retard de la boucle asyncio, xruns de la
  carte son du poste ORT-3010, charge, température ; même logique que `gateway/api/overload.py`
  pour les visiteurs) et envoie au module des consignes graduées par le bus : `brider` (niveau
  1 à 4), `suspendre`, `reprendre`. Ordre du bridage : décodeurs, `sdr-learner` (collecte passive et
  traitement fantôme compris), canaux parallèles, cadence du waterfall, fréquence
  d'échantillonnage. Sa propre première mesure : couper la piste audio SDR des clients.
- **Hystérésis** : reprise d'un cran seulement après N minutes au vert (comme les visiteurs : 5 min),
  sinon le système oscille.
- **Fait (étape 192, station 0.144.0)** : niveaux 0 à 5 (`trxstation/sdr/load.py` : 1 son du SDR coupé, 2 waterfall
  à mi-cadence, 3 waterfall à 1 ligne/s, 4 échantillonnage à 2 MHz, 5 suspendu ; les crans « décodeurs »,
  « sdr-learner » et « canaux parallèles » s'insèreront avant le waterfall quand ces lots existeront) ; seuils de la
  passerelle un cran sous ceux des visiteurs ; décrochages de la carte son du poste pris en compte ; plafonds du
  module `[sdr] max_cpu_pct` / `max_mem_mb` (le module ne se suspend jamais lui-même).
- Seule la passerelle peut envoyer ces consignes au module (bus authentifié).
- **Superviseur = dernier recours** : il arrête les processus du module si la passerelle est muette
  ou si le module n'obéit pas ; il reste minimal (pas de logique SDR).
- Priorité système : nice / classe de priorité basse (déjà fait par le lanceur des modules) ;
  plafonds cgroups / Job Objects : lot 2 des modules, toujours en attente (`docs/modules.md`).

### 2.4 Plusieurs SDR sur une machine [D 2026-11-15]

Relevé du 2026-11-15 sur minix-bzh : DEUX RSP2pro (USB 1df7:3010).

| N° de série | Usage |
| --- | --- |
| 170502EC10 | projet AIS RSSI (service `ais-rssi`, `AIS-catcher -d 170502EC10`), NE PAS TOUCHER |
| 170502E910 | openRemoteTRX |

Règles :

- `[sdr] serial` est OBLIGATOIRE dès que la machine voit plus d'un SDR (assistant et validation de
  station.toml le refusent sinon). Jamais « le premier trouvé », jamais le port USB (le RSP a changé
  trois fois de port pendant le relevé, son numéro est resté le même).
- Numéro de série absent au démarrage : le module ne démarre pas (code ORT-60xx, alerte ntfy), sans
  JAMAIS se replier sur un autre appareil.
- Le numéro se lit par l'API du fabricant (SDRplay : `GetDevices`, `SerNo`), PAS par sysfs / udev :
  le RSP s'énumère d'abord sans numéro (`SerialNumber=0`), le numéro n'apparaît dans sysfs que plus
  tard.
- L'assistant liste les SDR présents avec leur numéro, signale ceux déjà ouverts par une autre
  application et ne propose pas de les prendre.
- Aucun outil du projet (qualification, essai, diagnostic, trx-hwtest) n'ouvre un SDR dont le numéro
  n'est pas celui de `station.toml`.
- **`sdrplay.service` est COMMUN aux projets** : la station ne le redémarre JAMAIS (cela couperait
  l'AIS). Échelle de reprise du SDR = relancer le module, rien d'autre ; une panne du service est
  signalée (ORT-60xx) et laissée à l'opérateur. Le « reset USB » du superviseur ne vise que le poste.

#### 2.4.1 Clés RTL-SDR [D 2026-11-16]

- Second pilote de sdr-core : bibliothèque librtlsdr (osmocom ; licence à vérifier avant le lot : GPL 2 « ou
  ultérieure » attendue, compatible AGPL), installée par install.sh. Clé de l'utilisateur : **RTL-SDR Blog V4**
  (HF par son convertisseur intégré : vérifier que la version de librtlsdr de Debian 13 la prend en charge, sinon
  la branche du fabricant compilée comme Hamlib).
- **Numéros de série** : beaucoup de clés sortent d'usine avec le MÊME numéro (« 00000001 ») ; deux clés au même
  numéro ne peuvent pas être désignées : la station les REFUSE. Le menu 5.4 proposera d'en réécrire un
  (`rtl_eeprom`, écriture dans la mémoire de la clé : confirmation, une clé à la fois, jamais une clé prise).
- Pilote TV du noyau (`dvb_usb_rtl28xxu`) : il prend la clé au branchement ; install.sh l'écarte (liste noire).
- Limites : 8 bits, environ 2,4 MHz de large au plus (largeurs proposées selon le type de SDR).
- Windows : pilote WinUSB (Zadig) à poser à la main, documenté.

#### 2.4.2 Recherche des SDR et menu 5.4 [D 2026-11-16] (FAIT, étape 196)

- `trx-sdr --list` et TRX Console menu 5.4 : TOUS les ports USB, hubs compris (sysfs), SANS ouvrir aucun SDR ;
  type et modèle (identifiant USB, chaînes du fabricant), numéro de série, emplacement (« bus 3, port 6 -> hub,
  port 2 »), état : libre / pris par un programme (nom du programme avec les droits d'administration) / pris par le
  pilote TV du noyau / SDR DE CETTE STATION ; avertissements : numéro en double, SDR sur le même hub que le poste.
- SDRplay : le service du fabricant tient tous les RSP ouverts ; seuls ceux que son API PROPOSE sont libres.
- Menu 5.4 : choix du SDR par numéro de série (refus d'un SDR pris ou au numéro en double), largeur, antenne,
  plafonds, mise en service (« sdr » ajouté à `[modules] run`) ; redémarrage proposé.
- ais-rssi ouvre l'API SDRplay quelques secondes toutes les 5 minutes (relances d'AIS-catcher à
  21:12:40 et 21:17:40 le 2026-11-15) : la cohabitation de deux programmes sur l'API est vérifiée
  en S0.

### 2.5 USB

Relevé du 2026-11-15 : sur ce mini-PC (Alder Lake-N), les fils USB 2 de TOUS les ports aboutissent
au contrôleur 00:14.0 ; l'autre contrôleur (Thunderbolt, 00:0d.0) ne reçoit que la partie USB 3 des
ports. Le RSP2pro étant USB 2, il partage toujours le contrôleur de l'IC-7300. Avec xHCI chaque port
racine est son propre lien à 480 Mbit/s : pas de partage de bande tant que chaque appareil a SON
port racine (relevé : IC-7300 en 3-2 derrière son hub interne, RSP AIS en 3-3, RSP openRemoteTRX en
3-5). Règle du guide : JAMAIS un SDR sur le même hub que le poste ni sur le hub du clavier. S0 mesure
quand même les xruns de l'IC-7300 avec le SDR à pleine cadence.

### 2.6 Licences et installation [D 2026-11-15]

- Le code de la station est sous AGPL-3.0-or-later : les bibliothèques GPLv3 / AGPLv3 / LGPL /
  MIT / BSD conviennent ; GPLv2-only à exclure (incompatible).
- **API SDRplay** : propriétaire, non redistribuable. Installée À LA MAIN par l'utilisateur
  (`sdrplay.service`), jamais livrée dans les zips. Le module la charge par SoapySDR + SoapySDRPlay3
  (MIT) ; SoapySDR (Boost) : installé par install.sh / le paquet Windows ou à la main, à décider en
  S0. D'autres SDR (RTL-SDR, Airspy…) s'ajoutent par fiche, sans code spécifique dans le cœur.
- Décodeurs appelés comme programmes externes séparés de préférence (comme FreeDV).
- Plateformes : Debian et Windows d'abord, Raspberry Pi ensuite (moins de canaux parallèles).

### 2.7 Configuration

`station.toml`, section `[sdr]` (driver, `serial`, plafonds, bandes enregistrables §10) ; banques,
profils, base d'apprentissage dans `state_dir/sdr/`, gardés par les mises à jour et sauvegardés.
Toute clé ajoutée suit les conventions (notice station.toml, profils de poste si une clé de [rig] /
[audio] / [spectrum] change).

## 3. Fiche SDR

Chaque modèle de SDR est décrit par une fiche qui déclare ses capacités ; l'interface masque ce que
le SDR ne sait pas faire, comme pour les fiches TRX.

| Rubrique | Contenu | Exemple RSP2pro (à confirmer sur l'API) |
| --- | --- | --- |
| Couverture | Plage de fréquences | 1 kHz à 2 GHz |
| Entrées antenne | Liste, nom, plage utile, impédance | A, B (50 Ω), Hi-Z (fil long, < 30 MHz) |
| Bandes passantes FI | Valeurs disponibles | 200 kHz à 8 MHz |
| Modes FI | Zero-IF, low-IF | Les deux |
| Gain | États LNA par plage, gain FI, AGC matériel | États LNA, IFGR 20–59 dB, AGC FI |
| Filtres | Présélection automatique, notchs broadcast | Notch PO/AM, notch FM |
| Bias-T | Présence, entrée concernée | Oui |
| Signal de surcharge | Disponible ou non | Oui (événement CAN) |
| Résolution | Bits effectifs selon fréquence d'échantillonnage | 12 à 14 bits |
| Cohérence multi-récepteurs | Oui / non | Non |
| Identification | Comment lire le numéro de série | API SDRplay `SerNo` |
| Stabilisation | Durée après changement d'antenne ou de gain | à mesurer |

Comme pour les postes, tout format et toute capacité viennent du VRAI matériel (API interrogée sur
le RSP2pro), jamais de la documentation seule. Fiche validée par un outil de qualification dérivé de
`trx-qualif` (chaque entrée, chaque filtre, chaque état de gain), qui n'ouvre que le SDR de
`[sdr] serial`.

## 4. Waterfall SDR

Calculé sur la station, envoyé au client en lignes compressées ; il s'ajoute au waterfall TRX.

- Spectre + waterfall avec zoom, déplacement, moyennage, peak hold, palette et plage dynamique
  réglables (réutiliser `waterfall.js` / `hfscope.js` et leurs équivalents Android).
- Clic ou appui pour accorder le démodulateur SDR ; « envoyer cette fréquence au TRX » (§ 2.2).
- Marqueurs : spots du Cluster DX, fréquences de la banque active (exclues en grisé), canaux actifs
  en écoute parallèle.
- Indicateurs : plancher de bruit, surcharge, antenne et profil de gain actifs, alerte
  atmosphérique (§ 11).
- Débit adapté au lien : points, cadence et compression selon le terminal et la sonde réseau
  (`netprobe/`).
- Le waterfall continue pendant le PTT (§ 13).

## 5. Démodulation et modes numériques

Démodulation et décodage sur la station ; les décodeurs renvoient du texte.

**Modes audio** : AM (enveloppe et synchrone avec choix de bande latérale), NBFM, WFM, USB, LSB, CW.
Réutiliser autant que possible le démodulateur I/Q étudié sur la branche `exp/st-fi`.

| Priorité | Modes | Remarque |
| --- | --- | --- |
| 1 | FT8, FT4 | Décodage par période, liste des stations, marqueurs |
| 2 | CW (texte) | Vitesse affichée |
| 3 | RTTY, PSK31/63 | Texte défilant |
| 4 | APRS | Positions et messages |
| 5 | SSTV | Images reçues, galerie |
| 6 | FreeDV | Réutiliser `trxstation/freedv/` (décodeurs déjà compilés) |
| Exclu | DMR, D-Star, C4FM | Codec AMBE : risque juridique |

Chaque décodeur est un sous-processus activable séparément, arrêté en premier en cas de surcharge.

## 6. Banques de mémoires et scan

Scan sur une banque, modes audio AM, NBFM et BLU seulement.

**Paramètres d'une banque** : nom, entrée antenne, profil de gain (auto ou figé), filtres
matériels ; vitesse (canaux/s), seuil de détection **en dB au-dessus du plancher de bruit**, mode
d'arrêt (maintien tant que le signal est présent, ou durée fixe), temporisation de fin de signal,
délai de reprise.

**Paramètres d'une mémoire** : fréquence, mode, filtre, nom, tag « exclue du scan », priorité.

**Comportement** :

- Après un changement d'antenne ou de gain, attente de stabilisation (fiche SDR) avant mesure.
- Banque entière dans la bande passante du SDR : proposition de passer en écoute parallèle (§ 7).
- Banque répartie sur des bandes à antennes différentes : permise, ralentissement signalé.
- Seuils et vitesses : propositions de l'apprentissage (§ 10), toujours soumises à l'opérateur.

## 7. Écoute parallèle spatialisée

Quand toute une banque tient dans la bande passante du SDR, toutes ses fréquences sont démodulées
simultanément par un canaliseur et placées dans l'espace stéréo.

- Canaliseur polyphase ou par FFT, un démodulateur par mémoire non exclue ; squelch par canal
  calculé sur la station, seuls les canaux ouverts sont mixés.
- Placement par fréquence (bas à gauche, haut à droite) ou ordre libre ; panoramique simple jusqu'à
  3 sources, binaural (HRTF) au-delà ; nombre maximal de voix ; canal prioritaire avec atténuation
  des autres.
- Le canal actif clignote dans la liste et sur le waterfall.
- Piste SDR en stéréo Opus (48 à 64 kbit/s) dans ce mode seulement ; repli mono annoncé.
- Nombre de canaux plafonné selon la plateforme et bridable (§ 2.3).

## 8. Gain RF et FI

Trois niveaux, reprise manuelle possible à tout moment.

1. **Profil par bande** chargé à chaque changement de bande, affiné par l'apprentissage.
2. **Boucle automatique** : LNA monté jusqu'à ce que le plancher augmente d'environ 3 dB ; FI par AGC
   matériel avec consigne en dBFS ; surcharge du CAN = recul immédiat d'un cran ; hystérésis ;
   aucun changement de LNA pendant la réception d'une station (seulement au changement de bande,
   sur surcharge ou en silence).
3. **Manuel** : valeurs verrouillées par l'opérateur, bouton « Auto ».

Bouton « Optimiser » : teste les états de LNA sur la fréquence courante, retient le meilleur S/B.
En écoute parallèle, gain commun : profil par banque.

## 9. Mode fréquence unique

Configuration du SDR et de la chaîne DSP pour la meilleure réception d'une seule fréquence.

**Matériel** : bande FI la plus étroite, échantillonnage réduit et décimation ; low-IF plutôt que
zero-IF ; notchs broadcast quand la fréquence en est éloignée ; entrée antenne selon la bande ;
bias-T coupé sauf préampli déclaré.

| Mode | Filtre | Traitements | AGC |
| --- | --- | --- | --- |
| BLU | 1,8 à 2,7 kHz réglable | PBT/IF shift, notch auto, passe-bande 300–2700 Hz | Lent |
| CW | 250 à 500 Hz | APF, décodage optionnel | Rapide |
| AM | 6 à 9 kHz | Détection synchrone, choix de bande latérale | Moyen |
| NBFM | 12,5 kHz | Désaccentuation, coupe-bas 300 Hz (CTCSS) | — |

| Bandes | Adaptations de départ |
| --- | --- |
| 160, 80, 40 m, 45 m, 85 m | LNA bas, noise blanker, AGC plus lent |
| 20 à 15 m | Profil intermédiaire selon le plancher mesuré |
| 11 m, 10 m | Plus de gain, noise blanker (allumages), réducteur de bruit |
| VHF/UHF | LNA élevé, squelch « absence de voix » |

Réduction de bruit : soustraction spectrale ou réseau neuronal (type RNNoise) sur la station.
Table de profils bande × mode modifiable ; chaque automatisme affiché et désactivable.

## 10. Apprentissage et auto-adaptation

`sdr-learner` mesure hors usage (campagnes) et pendant l'usage (collecte passive), accumule des
statistiques sur des semaines et en tire des PROPOSITIONS.

**Déclenchement et arrêt** : actif quand aucun client n'est connecté depuis un délai réglable, ou
forcé par l'opérateur ; jamais pendant une émission ; plages horaires autorisées. Arrêt en moins
d'une seconde à la connexion d'un client (sauf mode forcé), à la demande du SDR ou de la passerelle.
Option : un second SDR dédié à l'apprentissage (désigné lui aussi par son numéro de série).

**Collecte passive pendant l'utilisation** : JAMAIS de changement de fréquence, d'antenne, de gain ou
de filtre décidé par l'apprentissage. Mesures sur la chaîne active (SNR, plancher, déclenchements
NB/NR, AGC, décodages) et sur le reste de la capture (plancher, raies, occupation). Préférences
implicites : corrections manuelles de l'opérateur sur le SDR, et sur le TRX lues sur le bus d'état
(§ 2.2), enregistrées avec leur contexte. Traitement fantôme d'un profil candidat sur le même IQ.
Premiers suspendus en cas de surcharge.

**Bandes [D 2026-11-15]** :

| Usage | Bandes permises par défaut |
| --- | --- |
| Mesures sans audio (bruit, occupation, raies) | toutes les bandes de la v1 : amateur, marine, radiodiffusion, 11 m, 45 m, 85 m, bandes ajoutées |
| Enregistrement audio / IQ (extraits des rapports) | amateur, CB (11 m), radiodiffusion, et les bandes ajoutées par l'opérateur À SA RESPONSABILITÉ (avertissement) |
| Exclus des enregistrements par défaut | bandes marines et toute bande de correspondance privée (secret des correspondances) |

**Mesures** (par bande, entrée, état de gain, heure, jour, saison) : plancher de bruit, SNR selon le
LNA, comparaison des entrées, surcharges et porteuses fortes, raies parasites stables, bruit
impulsionnel, occupation, balises et décodages de référence (NCDXF, nombre de décodages FT8).

**Méthode** : statistiques explicables (médianes, percentiles, tendances), seuil minimal de données
avant toute proposition (ex. 7 jours et N mesures par créneau), mesures d'un épisode atmosphérique
ou d'une émission exclues, stockage SQLite local, agrégation progressive, conservation réglable.

**Niveau d'autonomie** : 0 observation ; **1 proposition (défaut)** ; 2 application avec rapport.

**Surveillance de l'installation** : dérive brutale du plancher ou des balises sur une antenne =
alerte (code ORT-60xx), en lien avec la mesure de TOS.

**Modes** (un seul à la fois, affiché partout) :

| Mode | Le SDR sert à | Entrée | Sortie |
| --- | --- | --- | --- |
| Écoute | Écoute, scan, écoute parallèle (collecte passive possible) | Choix de l'opérateur ; défaut quand un client est connecté | Auto-amélioration ou arrêt |
| Auto-amélioration | Campagnes ; inutilisable pour l'écoute | Auto quand plus aucun client (si activé), ou forcé par l'opérateur | « Quitter » ; connexion d'un client si non forcé |
| Arrêt | Rien | Désactivation, ou suspension par la passerelle / le superviseur | Réactivation |

Arbitrage : openRemoteTRX prioritaire (§ 2.3) ; en auto-amélioration forcée, le TRX reste
utilisable et le PTT suspend aussi la campagne ; retour automatique après le départ du dernier
client (délai réglable) ; campagne interrompue reprise au point d'arrêt, mesures incomplètes
marquées et non utilisées.

## 11. Bruits atmosphériques en HF

Détection de quatre situations, comportement temporaire, retour automatique au profil normal.

| Situation | Signature | Comportement temporaire |
| --- | --- | --- |
| Orage lointain | Craquements impulsionnels faibles, bandes basses, le soir | NB renforcé, AGC à maintien plus long, indication |
| Orage proche | Impulsions large bande simultanées, amplitude et cadence croissantes | LNA réduit, NB maximal, **alerte sécurité** (déconnecter / mettre les antennes à la masse), pause de l'apprentissage |
| Pluie sur l'antenne | Souffle crépitant quasi continu, bandes hautes, antennes filaires | NR renforcé, autre entrée proposée |
| Propagation exceptionnelle | Nombreux signaux forts, plancher en hausse, surcharges | LNA réduit, notchs, FI étroite, notification |

Distinction QRM local / atmosphérique ; indice de confiance ; correction de l'opérateur ; source
externe de foudre optionnelle (Blitzortung : conditions d'utilisation à vérifier) ; relais de
protection optionnel piloté par la station, en COMPLÉMENT de la protection matérielle (§ 1),
au repos sur « entrée à la masse » ; chaque épisode journalisé et exclu de la référence.

## 12. Rapports, refus et retour en arrière

Toute adaptation automatique est enregistrée, expliquée et réversible.

| Classe | Exemples | Traitement |
| --- | --- | --- |
| Temps réel | Boucle de gain, NB quelques secondes | Synthèse quotidienne |
| Temporaire | Orage, pluie, propagation | Rapport court ; retour automatique signalé |
| Majeur | Profil bande × mode, antenne par défaut, notchs, seuil de scan, LNA par défaut | Rapport détaillé + notification ; accepté / refusé selon le niveau d'autonomie |

**Rapport majeur** : date, déclencheur, portée, valeurs avant / après, justification chiffrée, gain
attendu, confiance, quantité de données, boutons Accepter / Refuser / Annuler.

**Exemples audio** : extraits IQ de 10 à 30 s démodulés avec l'ancien et le nouveau profil ;
situations variées ; changements matériels non rejouables : alternance rapide signalée « non
simultanée » ; sonie égalisée ; Opus, IQ gardés peu de temps, quota disque ; extraits seulement
sur les bandes enregistrables (§ 10), jamais envoyés à l'extérieur ni accessibles aux visiteurs.

**Lecteur d'écoute comparative** : bascule A ↔ B à la même position sans coupure, spectre de
l'extrait, panneau d'information, navigation, boucle, test à l'aveugle X / Y optionnel, boutons
dans le lecteur ; page, tablette, téléphone.

**Retour en arrière** : chaque changement majeur = nouvelle version du profil (au moins 20
gardées) ; annulation du dernier, des k derniers ou retour à une date ; état de référence
restaurable en une action ; un changement refusé n'est plus reproposé pendant une durée réglable ;
toute annulation journalisée.

**Diffusion** : liste des rapports dans la page et l'application, ntfy pour les changements majeurs
et les alertes de sécurité (TOUJOURS par un code du catalogue, plage ORT-6000), synthèse
hebdomadaire exportable, consultation depuis TRX Console et trx-monitor.

## 13. PTT, protection et audio

### 13.1 PTT

- Audio SDR coupé en fondu court (~50 ms) au début de toute émission (client, local, SELCALL, TOS) ;
  scan et écoute parallèle en pause, temporisations figées. La coupure est faite par la PASSERELLE
  sur sa piste (pas d'attente du module) ; le module est prévenu par le bus.
- Waterfall maintenu, fréquence d'émission grisée.
- Reprise après le relâchement et un délai réglable (ex. 500 ms).
- Mesures prises pendant l'émission exclues de l'apprentissage.

### 13.2 Protection de l'entrée

À la charge de l'opérateur (§ 1). Options logicielles en complément seulement : LNA minimal pendant
le PTT, relais externe commun avec la protection orage.

### 13.3 Audio TRX + SDR [D 2026-11-15]

- **Deux pistes WebRTC** : TRX (inchangée) et SDR (ajoutée seulement quand le client écoute le SDR ;
  l'opérateur accepte le débit en plus). Piste SDR en mono Opus (~32 kbit/s) par défaut, stéréo
  seulement en écoute parallèle (§ 7).
- **Côté client** :
  - en mono : volume par source et balance TRX / SDR ;
  - en stéréo : option « TRX à gauche, SDR à droite » (ou l'inverse) ;
  - la séparation gauche / droite et la spatialisation « ST » (`spatial.js`, `SpatialHub`) sont
    EXCLUSIVES, comme ST et le débrouillage du scrambler ;
  - Android : la stéréo passe par le chemin `AudioTrackSink` / `SpatialHub` (étape 117) ; Android
    Auto en mono : volume par source seulement.
- **Squelch** :
  - SDR : calculé sur la station (un par canal en écoute parallèle) ; l'état ouvert / fermé est
    envoyé au client pour l'affichage ;
  - TRX, pour l'option « priorité TRX » (SDR atténué quand le TRX reçoit quelque chose) : état du
    squelch lu sur le poste quand il le déclare (`get_dcd`), sinon détection d'activité sur l'audio
    du TRX par la station ; l'atténuation se fait chez le client sur l'état reçu.
- **Pendant l'émission** : SDR coupé pour tous (opérateur et visiteurs).
- **Visiteurs** : UN mixage fait par la station, commun à tous les visiteurs, réglé par l'opérateur
  (SDR oui / non, balance, priorité TRX) ; pas de mixage par visiteur (CPU). Accès au SDR des
  visiteurs activable dans la console, fermé par défaut ; seulement sur les bandes enregistrables
  (§ 10) ; pas de SDR quand l'écoute des visiteurs est fermée.

## 14. Interface utilisateur

Designer d'interface existant enrichi de widgets SDR, variantes téléphone / tablette / ordinateur.

**Widgets** : waterfall SDR, scanner, éditeur de banques, mixeur, décodage texte, indicateur
atmosphérique, rapports, lecteur A/B, tableau de bord d'apprentissage.

| Terminal | Disposition |
| --- | --- |
| Téléphone Android | Un waterfall à la fois (balayage TRX ↔ SDR) ; scanner compact ; rapports en notification puis liste |
| Tablette Android | Deux waterfalls superposés, panneau latéral |
| Page web ordinateur | Vue complète ; édition des banques et profils ; tableau de bord d'apprentissage |
| Android Auto | État seulement : scan actif, canal en cours, alerte atmosphérique |
| TRX Console / trx-monitor | État du module, charge, historique des changements |

Le faux stimulus du designer anime les nouveaux widgets. Interface de suivi de l'auto-amélioration
(en ce moment, raisonnement, plan, journal de décisions, propositions, commandes) dans la page et
l'application ; raisonnement généré à partir des statistiques réelles, aucune explication inventée.

**Application** : UNE seule application ; module SDR DANS l'APK (pas de Play Feature Delivery :
inutilisable pour les versions installées hors Google Play), visible seulement si `hello.features`
annonce `sdr`. Pas de client iOS aujourd'hui. Variante « SDR seul » plus tard (product flavor).

## 15. Phasage et validation

Le journal des changements et le retour en arrière arrivent avant tout automatisme majeur.

| Lot | Contenu | Validation |
| --- | --- | --- |
| **S0** | Essai HORS DÉPÔT sur minix-bzh : SoapySDR + SoapySDRPlay3, ouverture du RSP 170502E910 par son numéro sans toucher à 170502EC10, cohabitation avec AIS-catcher sur l'API, charge CPU (FFT, démodulation, encodage Opus d'une seconde piste) à 2 / 6 / 8 MHz, xruns de l'IC-7300 à pleine cadence, lecture de la fiche RSP2pro réelle ; puis Windows | Chiffres relevés ; AIS RSSI intact ; aucun xrun de l'IC-7300 ; décision Python / numpy ou outil externe (csdr, liquid-dsp) |
| S1a | Module `sdr` (manifeste, `[sdr]`, choix par numéro de série, fiche), acquisition, waterfall SDR dans la page | Waterfall SDR sur la page ; module absent = station inchangée ; mauvais numéro = refus |
| S1b | Démodulation audio, seconde piste, coupure au PTT, consignes de charge de la passerelle, mixage client et visiteurs | Audio SDR sur la page ; coupure à chaque type d'émission (tests de panne) ; aucune dégradation du TRX à charge maximale |
| S1c | Application Android (téléphone, tablette), trx-monitor, TRX Console | Waterfall et audio SDR sur les trois terminaux |
| S3 | Banques et scan (gain manuel ou profil figé) | Arrêt fiable au seuil, aucune fréquence exclue ouverte, reprise conforme |
| S2 | Journal, rapports, versions, retour en arrière ; extraits IQ, lecteur A/B ; profils bande × mode ; gain automatique ; mode fréquence unique | 5 changements annulés = état exact ; aucune surcharge CAN non corrigée en 40 m et 11 m |
| S4 | Écoute parallèle spatialisée | Banque 2 m en stéréo sur PC ; plafond respecté sur Pi |
| S5 | Détection atmosphérique | Validée sur enregistrements IQ ; retour automatique |
| S6 | Apprentissage | Arrêt < 1 s à la connexion ; collecte passive sans modification ; propositions chiffrées + A/B après 7 jours |
| S7 | Décodeurs (FT8 / FT4 d'abord) | Comparables à WSJT-X sur le même signal |

S3 (scan à gain manuel) passe avant S2 : il n'introduit aucun automatisme majeur.

**Prérequis** : vérifier les licences (§ 2.6) ; bibliothèque d'enregistrements IQ de référence
(orage, pluie, propagation, QRM local, 40 m et 11 m chargés) pour des tests pytest sans matériel ;
partie du guide de l'opérateur sur la protection de l'entrée (§ 1).

**Questions ouvertes**

- S0 : le projet AIS RSSI peut-il être arrêté quelques minutes pendant les essais, ou doit-il tourner
  sans interruption ?
- SoapySDR : installé par install.sh / le paquet Windows, ou à la main comme l'API SDRplay ?
- Délai d'inactivité et plages horaires par défaut de l'apprentissage (S6).
- Relais de protection : matériel cible (relais USB, GPIO du Pi) (S5).

## 16. Résultats de l'essai S0 (minix-bzh, 2026-11-15, étape 184)

Matériel : Intel i3-N300 (8 cœurs E), 16 Go, Debian 13, API SDRplay 3.15, RSP2pro 170502E910 sur
le port 3-5 ; projet AIS RSSI EN MARCHE pendant tout l'essai (pas besoin de l'arrêter) ; station
openRemoteTRX en marche, capture de la carte son de l'IC-7300 active (`RUNNING`).
Outils hors dépôt dans `~/sdr-s0/` de minix-bzh : `sdrplay_iq` (C, lié à l'API : liste les SDR,
ouvre UN numéro de série, IQ int16 sur la sortie standard), `run_rate.sh`, `bench_dsp.py` (numpy du
venv de la station).

| Mesure | Résultat |
| --- | --- |
| Liste des SDR par l'API | SEUL le RSP libre est listé ; celui de l'AIS (ouvert) n'apparaît pas |
| Ouverture par numéro de série | OK ; numéro absent = rien n'est ouvert (code 3) |
| Cohabitation avec AIS-catcher | OK ; ses relances toutes les ~5 min 07 s sont son propre cycle (journal), sans lien avec l'essai |
| Flux 2 / 6 / 8 MHz, sortie jetée | 0 trou d'échantillons ; aucune erreur USB du noyau |
| CPU du service SDRplay (commun) | 10 % d'un cœur avec l'AIS seul ; + 9 % à 2 MHz, + 18 % à 6 MHz, + 24 % à 8 MHz |
| CPU de l'outil C | ~3 % à 2 MHz |
| xruns de l'IC-7300 | aucun ORT-3010 (seuil : 50 en 5 min) ; compteur fin NON publié par la passerelle |
| numpy, 2 MHz, waterfall (moyenne de TOUTES les FFT) + 1 canal | 51 % d'un cœur |
| numpy, 2 MHz, + 16 canaux | 64 % d'un cœur |
| numpy, 8 MHz | 116 à 151 % d'un cœur : NE SUIT PAS (échantillons perdus) |
| Opus d'une seconde piste (PyAV) | 1 à 2 % d'un cœur par client |

Décisions et conséquences :

- **Liste des SDR** : l'API ne voit pas un SDR déjà ouvert. L'assistant croise donc la liste de l'API
  avec les appareils USB du fabricant (sysfs, VID 1df7) pour afficher « présent mais pris par une
  autre application » ; le numéro de série reste lu par l'API.
- **Accès au SDR par un petit programme C** (comme `sdrplay_iq`), processus enfant du module, lié
  dynamiquement à l'API du fabricant, IQ par un tube : pas de SoapySDR pour le RSP (Debian ne fournit
  pas son module SDRplay, l'API étant propriétaire), pas de structures C recopiées en Python.
  Compilé par install.sh comme les décodeurs FreeDV (sans intervention de l'opérateur, qui n'installe
  que l'API SDRplay) ; Windows : compilé à la fabrication du zip. SoapySDR reste prévu pour les autres
  SDR (Debian fournit les modules RTL-SDR, Airspy…).
- **Licence** : ce programme AGPL est lié à une bibliothèque propriétaire ; en tant que titulaire des
  droits, RF-DIY.COM ajoute une EXCEPTION DE LIAISON explicite dans son en-tête (ACCEPTÉE par
  l'utilisateur le 2026-11-15).
- **Cadence** : 2 MHz par défaut sur minix-bzh (et moins sur un Pi). Au-delà : waterfall calculé sur
  une partie des FFT (1 sur 4), traitement réparti sur plusieurs processus, ou canaliseur en C
  (liquid-dsp, MIT) ; à décider en S1a sur mesure. numpy n'utilise qu'un cœur pour une FFT.
- **Seconde piste audio** : coût négligeable, rien à changer.
- **xruns** : S1b publie le compteur de décrochages de la carte son du poste (état de la passerelle)
  pour mesurer finement l'effet du SDR.
- **Windows** : S0 à refaire sur un PC Windows avec un RSP (pas encore fait).

### 16.1 S0 bis : la même chaîne en C avec liquid-dsp (étape 185)

liquid-dsp 1.7.0 (MIT, paquets Debian `libliquid1` / `libliquid-dev`, qui utilisent FFTW en simple
précision et `libfec0`) extraits sans sudo dans `~/sdr-s0/root/` ; programme d'essai
`bench_liquid.c` (`-O2 -march=x86-64-v3`, un seul fil), sur le vrai flux du RSP, AIS en marche.
Les pourcentages sont rapportés à la durée du signal : au-delà de 100 %, le programme ne suit pas
(trous dans le flux).

| Cadence, canaux | numpy (§ 16) | C, un mélangeur + rééchantillonneur par canal | C, canaliseur par FFT |
| --- | --- | --- | --- |
| 2 MHz, 1 canal | 51 % | **23 %** | — |
| 2 MHz, 16 canaux | 64 % | 139 % (ne suit pas) | **41 %** |
| 6 MHz, 1 canal | — | 47 % | — |
| 8 MHz, 1 canal | 116 % (ne suit pas) | **47 à 51 %** | 89 % |
| 8 MHz, 16 canaux | 151 % (ne suit pas) | 441 % (ne suit pas) | 100 % (limite) |
| 8 MHz, 64 canaux | — | — | 132 % (ne suit pas) |

Le waterfall seul pèse peu (une FFT sur 4 ou toutes : 47 % contre 51 % à 8 MHz, 1 canal).

Conclusions :

- Le C gagne environ un facteur 2 sur numpy, PAS 3 à 5 : le travail est dominé par les FFT, que numpy
  faisait déjà en C. Le vrai levier est ailleurs : l'algorithme et les cœurs (l'i3-N300 a 8 cœurs E
  assez lents ; les essais n'en utilisaient qu'un).
- Algorithme selon l'usage :
  - fréquence unique (§ 9) : décimation et FI étroite DANS le RSP, presque gratuites pour la station ;
  - 1 à 4 canaux : mélangeur + rééchantillonneur par canal ;
  - écoute parallèle (§ 7) : canaliseur par FFT ou polyphase (`firpfbch` de liquid-dsp), à régler en
    S4 (bloc plus petit que les 2^19 de l'essai, plans FFTW mesurés, un fil par groupe de canaux).
- Cadence : 2 MHz couvre une bande HF entière (10 m compris) et la bande 2 m ; c'est le défaut.
  8 MHz est réservé au waterfall large avec 1 à 4 canaux.
- Charge totale estimée sur minix-bzh à 2 MHz et 16 canaux : service SDRplay ~19 % + cœur ~41 %, soit
  environ 0,6 cœur sur 8.
- **Décision proposée** : `sdr-core` en C avec liquid-dsp (paquet Debian, installé par install.sh ;
  Windows : compilé à la fabrication du zip), plusieurs fils ; le module, le scan, les rapports et
  l'apprentissage restent en Python.

