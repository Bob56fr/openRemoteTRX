# Enregistrement HIFI depuis la page : cahier des charges (v2, décisions du 2026-11-17 prises)

Demande de l'utilisateur (2026-11-17) : la station tourne souvent dans un coin, sans écran ni clavier. Il faut pouvoir
lancer **depuis la page web seulement** un enregistrement de **longue durée, sans compression**, pour travailler sur
les améliorations audio (réduction de bruit, égaliseur…). Fichier WAV déposé dans le dossier « Téléchargements » du
navigateur, nom prérempli et modifiable.

## 1. Décisions de l'utilisateur (2026-11-17)

- Page web seulement (l'application Android n'est pas concernée : exception à noter dans `docs/parite-web-android.md`).
- Débit au choix : 16, 32 ou 48 kHz, sans compression.
- Panneau qui reste affiché dans la page : démarrer, pause, arrêter.
- Nom prérempli, par exemple `7.000.00 - USB - 2026-11-05 13h25-02sec.wav`, modifiable avant le téléchargement.
- **Voix de l'opérateur** enregistrée aussi quand il émet : interrupteur oui / non choisi AVANT de démarrer, **figé**
  une fois l'enregistrement lancé. La perte due à Opus sur cette voix est acceptée.
- Conservation : Raspberry Pi = téléchargé puis effacé de la station ; PC Debian et Windows = téléchargé mais gardé
  sur la station, effacé au bout de **7 jours**.
- Réponses au § 13 de la v1 (2026-11-17) :
  - fichiers coupés en **parties de 10 minutes** ;
  - Raspberry Pi : effacement **1 h après le premier téléchargement complet** ;
  - repères et plafond de téléchargement : sans avis, donc choix du cahier (§ 5 et § 9) ;
  - **son du SDR** enregistrable : la **source se choisit dans le panneau** qui propose l'enregistrement et le
    téléchargement (§ 3.3, § 6).

## 2. Principe (bloquant)

Le son reçu par la page est codé en **Opus** (avec perte) : un enregistrement fait dans le navigateur ne serait qu'un
Opus décodé, inutilisable pour ce but. Donc :

- **la STATION enregistre** le son du poste en PCM, avant tout codage et tout traitement ;
- **la page n'est qu'une télécommande** (démarrer, pause, reprise, arrêt, nom) et récupère le fichier terminé ;
- le fichier passe par une **route HTTP authentifiée** de la passerelle (jamais par le canal de données, limité à
  64 ko par message) ;
- l'enregistrement **ne dépend pas de la page** : onglet fermé, téléphone en veille ou 4G perdue ne l'arrêtent pas ;
  en rouvrant la page, le panneau le retrouve (état publié dans `state`).

## 3. Ce qui est enregistré

### 3.1 Voie « réception » (toujours)

- Le son tel que la carte son du poste le donne : PCM 16 bits, 48 kHz (format de travail de la station,
  `gateway/audio/pcm.py`).
- Prise **avant tout traitement de la station** : avant le gain de réception (`RxHub.gain_db`), avant le traitement
  SELCALL (retard, squelch, filtrage des tonalités) et avant FreeDV (`RxHub.publish`). La valeur du gain est notée dans
  les métadonnées (§ 5).
- FreeDV en service : on enregistre le **signal du poste** (modem), pas la voix décodée.
- Rien de ce que fait le client (égaliseur, effets, spatialisation ST, débrouillage, volume) n'entre dans le fichier.
- Pendant une émission : la voie garde ce que donne la carte (moniteur du poste ou silence), **sans pause automatique**.
  Ainsi le temps reste continu, ce qui compte pour l'analyse, et les émissions sont repérées (§ 5).

### 3.2 Voie « voix émise » (si l'interrupteur est sur oui)

- Ce qui part **réellement vers la carte son du poste** : après la porte audio, la route (directe ou Breizh), le
  limiteur final. Les bips de fin et la trame SELCALL sont compris, puisqu'ils partent sur l'air.
- C'est la voix du client décodée d'Opus : perte acceptée (décision § 1).
- Silence numérique hors émission.
- Voie supplémentaire du fichier (§ 3.3) : avec la source TRX, stéréo gauche = réception, droite = voix émise ;
  interrupteur sur non et une seule source : fichier **mono**.
- Les deux voies sont alignées sur l'horloge de la capture (trames de 20 ms). Pour chaque trame reçue, la station
  écrit la trame émise pendant la même période, ou du silence. Capture et lecture passent par le même codec USB du
  poste, donc pas de dérive entre les deux horloges.

### 3.3 Source : TRX, SDR ou les deux (décision du 2026-11-17)

- Choisie dans le panneau AVANT de démarrer, figée ensuite, comme le débit et la voix émise :
  - **TRX** (défaut) : voie réception du § 3.1 ;
  - **SDR** : le son DÉMODULÉ du SDR tel que la passerelle le reçoit de sdr-core (PCM 16 bits, 48 kHz, trames de
    20 ms, `gateway/audio/sdr_audio.py`). C'est le son d'écoute (après la démodulation et l'AGC de sdr-core), jamais
    les échantillons I/Q (trop volumineux, hors sujet) ;
  - **TRX + SDR** : les deux voies, pour comparer le même signal.
- Choix SDR proposé seulement si le module SDR est en service. Le SDR n'écoute qu'une fréquence à la fois : celle
  écoutée au départ entre dans le nom, ses changements dans les repères.
- Le son du SDR est **coupé pendant toute émission** (règle du module) : la voie garde le silence, avec le repère
  d'émission ; bridage, suspension ou panne du SDR (ORT-6004) = silence et repère, l'enregistrement continue.
- Horloges : le SDR et le codec du poste n'ont pas la même horloge. L'enregistreur cale tout sur la capture du poste
  (source TRX ou TRX + SDR) et compense la dérive du SDR en ajoutant ou retirant un échantillon de temps en temps ;
  toute correction de plus de 20 ms est notée dans les repères. Source SDR seule : calé sur l'arrivée des paquets du
  SDR, trous comblés par du silence.
- **Voies du fichier**, dans cet ordre fixe, seulement celles choisies : TRX, SDR, voix émise (1 à 3 voies ; ordre
  et nom des voies écrits dans les métadonnées et dans le panneau).

### 3.4 Exclus

Voix des autres clients, son des visiteurs, échantillons I/Q du SDR.

## 4. Format et volumes

- **WAV PCM 16 bits** (le codec USB des postes courants est en 16 bits : 24 bits n'apporterait rien).
- Débit choisi avant de démarrer, figé ensuite : 48 kHz (natif), 32 ou 16 kHz. Le rééchantillonnage se fait à la
  station avec un **vrai filtre anti-repliement** (polyphase), jamais une simple décimation. Un test mesure
  l'atténuation au-dessus de la nouvelle fréquence de Nyquist.
- Volumes indicatifs (affichés dans le panneau avant de démarrer) :

| Débit | 1 voie | 2 voies | 3 voies |
|---|---|---|---|
| 48 kHz | 5,8 Mo/min, 346 Mo/h | 691 Mo/h | 1 037 Mo/h |
| 32 kHz | 230 Mo/h | 461 Mo/h | 691 Mo/h |
| 16 kHz | 115 Mo/h | 230 Mo/h | 346 Mo/h |

- Fichier coupé en **parties de 10 minutes** (décision du 2026-11-17 ; `… - partie 02.wav`), sans trou ni
  recouvrement entre deux parties (chaque partie commence à l'échantillon qui suit la fin de la précédente) : environ
  58 Mo par partie en 48 kHz mono, 173 Mo avec 3 voies. Loin de la limite de 4 Go d'un WAV.
- Chaque partie est un WAV complet et lisible seul (en-tête, métadonnées, repères qui la concernent, heure de son
  début). Le nom de chaque partie reprend la fréquence et l'heure de SON début.
- Durée maximale d'un enregistrement : **12 h** par défaut (réglable), puis arrêt automatique.

## 5. Repères et métadonnées

Indispensables pour exploiter un long fichier :

- **Dans le WAV** : bloc `LIST/INFO` (station, version, poste, fréquence et mode au départ, débit, gain de réception,
  voies) et repères `cue` / `adtl`.
- **Fichier de repères Audacity par partie** (`… - partie 02 - reperes.txt`, format « début ⇥ fin ⇥ texte » importé
  par « Importer des étiquettes », temps relatifs à la partie) et **un JSON** pour tout l'enregistrement (temps
  absolu et partie de chaque événement), pour les scripts d'analyse (choix du cahier, l'utilisateur n'ayant pas
  d'avis).
- Événements notés, horodatés en temps du fichier et en heure locale :
  - pause et reprise ;
  - changement de fréquence, de mode, de filtre, de NR / NB / préampli / ATT (comparaison avec l'état du poste
    publié par la passerelle, sans aucune lecture supplémentaire au poste) ; pour le SDR, fréquence écoutée, mode,
    gains, bridage ;
  - début et fin d'émission, avec la cause de la coupure ;
  - trou (trames perdues, § 8) ;
  - FreeDV mis en service ou arrêté.

## 6. Page web

- Une entrée « Enregistrement HIFI » (rubrique ou bouton de l'en-tête), **opérateurs seulement**, visible si
  `hello.features` contient `hifi_rec`.
- **Panneau flottant** non modal, déplaçable, qui reste affiché quand on change de rubrique (option : fenêtre
  détachée comme la rubrique « Amis », Chrome sur PC seulement).
- **Avant de démarrer** :
  - **source** : TRX / SDR / TRX + SDR (SDR grisé si le module n'est pas en service) ;
  - débit (16 / 32 / 48 kHz) ;
  - interrupteur « Voix émise » ;
  - volume estimé par heure et place libre sur la station ;
  - avertissement réglementaire à la première utilisation (§ 9) ;
  - bouton ● Enregistrer.
- **Pendant** :
  - durée, taille, place restante, partie en cours ;
  - niveau de chaque voie (barre et crête, écrêtage signalé) ;
  - état : enregistrement / pause / émission ;
  - boutons ❚❚ Pause / ▶ Reprise et ■ Arrêter ;
  - réglages (source, débit, voix émise) affichés mais grisés ;
  - les parties déjà terminées sont téléchargeables pendant que l'enregistrement continue.
- **Après l'arrêt** :
  - champ du nom prérempli : `<fréquence> - <mode> - <AAAA-MM-JJ> <HH>h<MM>-<SS>sec.wav`. La fréquence est celle
    du début, écrite comme l'afficheur de la page (`14.074.00`), le mode est le nom Hamlib (`USB`, `PKTUSB`), l'heure
    est l'heure locale de la station au début ;
  - bouton « Télécharger » : le fichier arrive dans « Téléchargements ». Chrome sur PC peut proposer « Enregistrer
    sous » selon son réglage ; sur Android, le dossier ne peut pas être imposé ;
  - une ligne par partie de 10 minutes (avec son fichier de repères), plus **« Tout télécharger »** : UN seul fichier
    ZIP **sans compression** (mode « stocké » : les WAV y sont intacts, octet pour octet) qui contient toutes les
    parties, leurs repères et le JSON. Évite les dizaines de téléchargements et la question de Chrome sur les
    téléchargements multiples ; le ZIP se fabrique en flux, sans copie sur le disque de la station.
- **Liste « Enregistrements sur la station »** (PC Debian et Windows) : nom, date, durée, taille, jours restants avant
  effacement, Télécharger, Renommer, Supprimer.
- **Avertissement de durée de téléchargement** : 350 Mo par le VPN en 4G peuvent prendre longtemps. Durée estimée
  d'après le débit mesuré par la sonde réseau quand elle est disponible.
- Le bouton STOP de la page (retour en réception) n'arrête **pas** l'enregistrement.

## 7. Vie de l'enregistrement sur la station

- **Un seul enregistrement à la fois** par station.
- Seul le **compte qui l'a lancé** peut le mettre en pause ou l'arrêter. Les autres opérateurs voient « Enregistrement
  en cours (pseudo) ».
- Dossier : `<state_dir>/enregistrements/`, accessible au seul compte de la station (0600 / 0700).
- **Refus au démarrage** si la place libre est sous `min_free_gb` (2 Go par défaut) ou sous le volume prévu pour la
  durée maximale. Le refus est montré dans le panneau avec un code ORT.
- **Arrêt automatique** :
  - place libre sous 1 Go ;
  - durée maximale atteinte ;
  - passerelle arrêtée ;
  - mode sûr ;
  - poste absent plus de N minutes.

  Chaque arrêt automatique est noté dans les repères.
- **Écriture hors de la boucle asyncio** (fil d'écriture dédié). L'en-tête WAV (tailles) est réécrit toutes les
  10 s : une passerelle tuée laisse un fichier lisible.
- **Au redémarrage**, un enregistrement interrompu est **réparé** (en-tête recalculé, repère « interrompu ») et placé
  dans la liste.
- Charge négligeable (copie de trames et écriture disque). Le bridage de la charge (SDR, visiteurs) ne touche pas
  l'enregistrement.

## 8. Intégrité du son

- L'enregistreur ne doit **jamais perdre une trame en silence**. Si sa file déborde (disque lent), la station
  insère du **silence de même durée** pour garder le temps juste, et note un repère « trou de N ms ».
- Les débordements de la carte son (xruns, ORT-3010) sont aussi notés dans les repères.
- Fin de fichier propre à l'arrêt (dernière trame complète, en-tête final).

## 9. Conservation et téléchargement

- **Raspberry Pi** (détecté par `hostinfo`, réglable) : chaque partie est effacée **1 h après son premier
  téléchargement complet** (décision du 2026-11-17 ; directement ou par « Tout télécharger »). La marge permet de
  recommencer si le navigateur a mal enregistré. Une partie jamais téléchargée est effacée au bout de 7 jours.
- **PC Debian et Windows** : gardé **7 jours** après la fin, puis effacé, téléchargé ou non.
- Route `GET` authentifiée (même compte que la page, opérateurs seulement) :
  - nom envoyé par `Content-Disposition`, filtré par une liste fermée de caractères ;
  - **requêtes partielles** (`Range`) pour reprendre un téléchargement coupé ;
  - lecture en flux depuis le disque ;
  - seulement des fichiers terminés (ou des parties terminées).
- **Débit de téléchargement** (choix du cahier, l'utilisateur n'ayant pas d'avis) : **sans limite par défaut**
  (`download_kbps = 0`), réglable dans station.toml pour une box à montée faible. Garde-fou automatique : pendant
  une émission (client, micro du poste, SELCALL, TOS) le téléchargement est ralenti à 256 kbit/s, pour ne pas gêner
  le son en direct ni le canal de contrôle.
- **Avertissement réglementaire** à la première utilisation : écouter n'est pas toujours enregistrer légalement (bandes
  marine, communications de tiers). Responsabilité de l'opérateur, même principe que la rediffusion.
- **Raspberry Pi, carte SD** : de longues écritures l'usent. Le guide conseille une clé USB ou un SSD (dossier
  réglable).

## 10. Sécurité d'émission

- L'enregistrement **ne fait que lire** : aucune commande au poste, aucun lien avec le PTT, la porte audio ni le TOT.
- Il ne change rien à la chaîne d'émission. La voix émise est copiée APRÈS le limiteur, sans retour possible vers le
  poste.
- Un visiteur ne peut ni lancer, ni voir, ni télécharger un enregistrement (liste blanche de `ControlSession`
  inchangée).
- Tests de panne : disque plein, passerelle tuée pendant l'écriture, page fermée, émission pendant l'enregistrement,
  arrêt sur mode sûr ; preuve qu'aucun chemin de ce code n'atteint le PTT.

## 11. Protocole et réglages (à figer au lot H1)

- Commandes du client :
  - `hifi_rec_start {rate, sources, tx_voice}` (`sources` : `["trx"]`, `["sdr"]` ou `["trx", "sdr"]`) ;
  - `hifi_rec_pause`, `hifi_rec_resume`, `hifi_rec_stop` ;
  - `hifi_rec_list` ;
  - `hifi_rec_rename {id, name}` ;
  - `hifi_rec_delete {id}`.
- Message `hifi_rec` (état) et champ `state.hifi_rec`.
- `hello.features` : `hifi_rec`.
- Routes `GET /api/recordings/<id>/<partie>` (+ `…/<partie>/reperes.txt`, `…/reperes.json`) et
  `GET /api/recordings/<id>/tout.zip` (ZIP stocké, fabriqué en flux).
- Mise à jour de `docs/protocole.md`, des exemples `tests/protocol/` et de `docs/parite-web-android.md` (page
  seulement). Le contrat Android (`Command`, `NAMES`) suit pour que les tests de contrat passent, sans écran.
- `station.toml`, nouvelle section `[hifi_rec]` :

| Réglage | Défaut | Rôle |
|---|---|---|
| `enabled` | `true` | fonction proposée aux opérateurs |
| `dir` | `""` | dossier, vide = `<state_dir>/enregistrements` |
| `max_hours` | 12 | durée maximale |
| `part_minutes` | 10 | durée d'une partie |
| `min_free_gb` | 2 | place minimale pour démarrer |
| `keep_days` | 7 | conservation (PC) |
| `delete_after_download` | auto | `true` sur Raspberry Pi, `false` ailleurs |
| `download_kbps` | 0 | plafond du téléchargement |

  Notice station.toml à compléter.
- **Codes ORT** à créer : enregistrement démarré / arrêté (information), refus faute de place, arrêt automatique, trou,
  fichier réparé, téléchargement terminé.
- **trx-monitor** : une ligne « Enregistrement » (durée, taille, compte). Interrupteur dans le menu 5.5 « Fonctions en
  service » (4 langues).

## 12. Lots

1. **H1, station** : enregistreur (1 à 3 voies, sources TRX / SDR, calage des horloges, rééchantillonnage, parties
   de 10 minutes, repères, réparation), commandes, routes de téléchargement (ZIP stocké compris), conservation, codes
   ORT, `[hifi_rec]`, tests de panne.
2. **H2, page** : panneau flottant, nom, liste, téléchargement, avertissements ; essai dans un vrai Chromium
   (Playwright) contre une fausse station.
3. **H3** : trx-monitor, menu 5.5, notice station.toml, guide de l'opérateur, mode d'emploi de la console.
4. **Essai réel** sur minix-bzh :
   - 2 h d'enregistrement TRX + SDR + voix émise, avec émissions sur charge fictive (SDR coupé, repères) ;
   - « Tout télécharger » ouvert, parties recollées dans Audacity sans clic ni décalage entre elles ;
   - fichier ouvert dans Audacity avec ses repères ;
   - téléchargement en Wi-Fi puis en 4G ;
   - passerelle relancée pendant l'enregistrement ;
   - puis sur un Raspberry Pi (effacement après téléchargement).

## 13. Décisions (2026-11-17)

Toutes prises (voir § 1). Le lot H1 peut commencer quand l'utilisateur le demandera.
