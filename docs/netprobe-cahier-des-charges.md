# Sonde de qualité réseau — cahier des charges

Version 3 (2026-11-09, étape 135) : réponses de l'utilisateur aux questions de la v2 intégrées (§ 15) : EF12 et la
position retirés, « Liaison faible » en Android Auto, seuils réglés d'après les mesures (§ 9.6).

Version 2 (2026-11-09, étape 134). Elle reprend le cahier de l'utilisateur du 2026-11-09 (« Sonde de qualité réseau
openRemoteTRX », exigences EF1 à EF11 ; EF12 retirée en v3) et ajoute :
- ce que le code existant change à ce cahier (§ 3) ;
- l'affichage discret et le détail sur les trois interfaces (§ 9) ;
- la vue des 30 derniers jours, l'effacement et l'export pour l'équipe de développement (§ 10) ;
- la détection d'un profil VPN partagé par deux appareils (§ 8), décision de l'utilisateur du 2026-11-09 après la
  cause trouvée des coupures (PC et S25 sur le même profil WireGuard).

Les réponses de l'utilisateur aux questions de la v2 sont au § 15.

## 1. Objet

Mesurer en continu le lien entre le client (page web, application Android) et la station, et dire après chaque
coupure quel tronçon a lâché :

| N° | Tronçon | Mesuré par |
|---|---|---|
| 1 | Radio du téléphone (4G/5G/Wi-Fi) | application Android (EF11) |
| 2 | Internet jusqu'à l'adresse publique de la box | déduit (§ 7) |
| 3 | Tunnel VPN (quel qu'il soit) | déduit (§ 7) ; profil partagé (§ 8) |
| 4 | Réseau local de la box jusqu'à la station | sondes de la station (§ 5) |
| 5 | Application (passerelle, WebRTC, client) | battement et `/health` (§ 4) |

La sonde ne fait que **mesurer et afficher**. Elle n'agit jamais sur le PTT, la porte audio, le CAT ni le TOT. Les
coupures d'émission restent celles des règles de sécurité : battement d'émission, perte de connexion, TOT.

## 2. Décisions

1. Le cahier de l'utilisateur est la base (EF1 à EF11, `[netprobe]`, tests, essais ; EF12 retirée en v3).
2. 2026-11-09 : indicateur discret sur la page, dans l'application et dans trx-monitor. L'opérateur ouvre le détail
   par un bouton ou un accordéon selon l'interface.
3. 2026-11-09 : une vue des 30 derniers jours, un bouton « Tout effacer » et un export à transmettre à l'équipe de
   développement.
4. 2026-11-09 : la détection d'un profil VPN partagé est intégrée à ce cahier, pas livrée à part.
5. Rien n'est propre à WireGuard ni à la Freebox : chaque utilisateur choisit son VPN (CLAUDE.md).
6. 2026-11-09 (v3) : **EF12 retirée** (conseil sur l'opérateur, données de l'ARCEP) : trop de ressources. Partent
   avec elle : clés `operator_advice`, `arcep_refresh_days`, `advice_min_outages`, mesure de la seconde SIM, relevé
   des cellules des AUTRES opérateurs (elles ne servaient qu'à EF12).
7. 2026-11-09 (v3) : **position retirée** (`FusedLocationProviderClient`, situer les coupures sur la route) : ni
   dans la version Google Play ni dans la version installée à la main. Aucune position n'est relevée, journalisée
   ni exportée.
8. 2026-11-09 (v3) : Android Auto et mode conduite affichent « Liaison faible » quand le lien est mauvais (§ 9.3).
9. 2026-11-09 (v3) : pas de seuils figés au jugé. La station enregistre de quoi les essayer après coup et propose
   des valeurs d'après l'usage réel et le réseau de l'opérateur (§ 9.6).

## 3. Ce que le code existant change au cahier de l'utilisateur

- **Il n'y a qu'un seul chemin WebRTC.** Le « canal de contrôle » EST un DataChannel WebRTC (`control`,
  `docs/protocole.md` § 3). Le contrôle (SCTP) et l'audio (RTP) passent par la même connexion ICE, dans le même flux
  UDP. Doubler le battement sur un « second » DataChannel (EF1) ne distinguerait rien. Le **second chemin
  indépendant** sera donc `GET /health` en HTTPS, c'est-à-dire en TCP, hors WebRTC, sans état ni authentification,
  déjà existant (§ 4.3).
- **Nom des messages.** `heartbeat` est déjà pris : c'est le battement d'émission, sans réponse, envoyé seulement
  pendant une émission. La sonde utilise `net_ping` / `net_pong` (§ 4.1) et la fonction `netprobe` de
  `hello.features`.
- **getStats existe déjà** dans la page (`ui.js`, `collectStats` : gigue, pertes, RTT de la paire ICE, pour le
  diagnostic du son). La sonde réutilise cette lecture au lieu d'en écrire une seconde.
- **Adresse du client.** `client_source` (`gateway/api/auth.py`) donne déjà l'adresse d'origine, y compris derrière
  un relais (`X-Forwarded-For` des relais déclarés). La détection du profil partagé (§ 8) s'appuie dessus.
- **Sondes de la station.** Elles tournent dans un **module** (`trxstation/modules/`, comme le Cluster DX) : un
  processus à part, relancé seul s'il plante, qui ne peut rien casser dans la passerelle (exigence de
  non-régression).
- **Alertes.** C'est le superviseur qui les envoie, avec son `notify_url` existant, en lisant le champ `net` du
  fichier d'état (bus d'état). Il ne parle pas à la sonde et n'ajoute aucune dépendance.
- **Journal.** Il va dans `state_dir/netprobe/`, pas dans un chemin relatif `logs/netprobe` (le dossier courant
  change entre Debian, Windows et le mode géré). La clé `log_dir` du cahier est retirée.
- **Volume du journal.** Une ligne par battement ferait environ 17 Mo par jour et par client : trop pour 30 jours
  sur la carte SD d'un Pi. Le journal garde donc des **résumés toutes les 10 s**, plus les événements, et les
  statistiques sur 30 jours viennent de **résumés horaires** (§ 6).
- **Diagnostic après coup.** Pendant une coupure, le client ne peut rien envoyer. Le diagnostic (EF7) se fait **à la
  reconnexion**, quand le client remet ses 10 dernières minutes (EF6). Une coupure encore en cours s'affiche
  « tronçon : à préciser à la reconnexion », sauf si les sondes de la station suffisent à conclure.
- **Livraison.** Pas de `git add .` : seuls les fichiers de la livraison sont commités (d'autres conversations
  travaillent dans le dépôt). Le dépôt compte environ 1 250 tests Python, pas 233. Une étape numérotée par lot.

## 4. Mesures du lien client ↔ station

### 4.1 Battement réseau dans les deux sens (EF1)

- Le client envoie chaque seconde `{"cmd":"net_ping","seq":N,"t":T}` (`T` = horloge MONOTONE du client, en ms).
  La station répond aussitôt `{"type":"net_pong","seq":N,"t":T,"tr":R}` (`R` = son horloge monotone, en ms).
- La station envoie chaque seconde `{"type":"net_ping","seq":N,"t":T}`. Le client répond aussitôt
  `{"cmd":"net_pong","seq":N,"t":T,"tr":R}`. Ce message ne reçoit aucun `result`, comme `heartbeat`.
- Chaque côté mesure le temps aller-retour avec **sa propre horloge** (`maintenant − t` à la réception du `net_pong`).
  Les horloges des deux côtés ne sont jamais comparées entre elles pour une mesure.
- Moins de 120 octets par message. 2 messages de plus par seconde et par client, sous la limite de 30 par seconde.
- `net_ping` et `net_pong` sont admis pour un VISITEUR (liste blanche, `docs/visiteurs-cahier-des-charges.md`) : il
  voit la qualité de SON lien, et rien d'autre (§ 9).
- Ce battement ne remplace PAS le battement d'émission, qui garde ses règles (400 ms, coupure à 2 s).

### 4.2 Statistiques WebRTC (EF5)

Le client lit `getStats()` toutes les 2 s :
- RTP audio entrant (pertes, gigue, paquets) et sortant ;
- paire ICE nommée (RTT, octets) ;
- `iceConnectionState` et `connectionState`, avec chaque changement horodaté ;
- `navigator.connection.type` quand le navigateur le donne.

La station lit aussi les statistiques d'aiortc (comptes RTP, rapports RTCP du client) si elles sont fiables. C'est à
vérifier au lot 2 : on ne retient que ce qu'un vrai aiortc fournit.

### 4.3 Chemin HTTPS hors WebRTC

Le client interroge `GET /health` toutes les 5 s (délai 3 s, aucune nouvelle route, aucun port nouveau). Il garde le
résultat : réussite, durée ou échec. Interprétation :
- `/health` répond mais le battement est perdu : le problème est dans WebRTC ou la passerelle (tronçon 5) ;
- les deux sont perdus : le problème est dans le réseau ou le tunnel (tronçons 1 à 3).

### 4.4 Indicateurs (EF2)

Sur des fenêtres glissantes de 10 s et 60 s, des deux côtés :
- perte en % (numéros manquants sur les numéros attendus) ;
- temps aller-retour : moyenne, p95, maximum ;
- gigue : formule de la RFC 3550 (J += (|D| − J) / 16) appliquée aux allers-retours successifs, dans l'ordre des
  numéros : elle ne dépend que de l'horloge de l'émetteur (lot 1) ;
- nombre de numéros reçus hors séquence.

Un battement sans écho depuis moins de 5 s est EN ATTENTE (ni reçu ni perdu) ; un `net_pong` qui arrive après 5 s
compte comme perdu ET est noté « tardif ». Aller-retour p95 : rang le plus proche. Les calculs sont communs à trois
codes : Python (station), `client.js` (page) et Kotlin (`:logic`). Ils sont figés par des vecteurs partagés
`tests/protocol/netprobe_vectors.json` (séquences connues et résultats attendus), comme pour la mesure de TOS.

### 4.5 Coupures (EF3)

- Une coupure commence après `outage_missed_beats` battements perdus d'affilée (3 par défaut) et finit au premier
  `net_pong` reçu.
- Elle est enregistrée avec son début, sa fin, sa durée, le côté qui l'a vue le premier, les chemins tombés
  (battement, `/health`, ICE) et le diagnostic (§ 7).
- Une déconnexion complète du client est une coupure qui se termine à la reconnexion du MÊME appareil (§ 8.1). Une
  coupure sans reconnexion dans les 30 min est close « sans retour ».

### 4.6 Remise des 10 dernières minutes (EF6)

- Le client garde en mémoire 10 min de résumés de 10 s : battement, getStats, `/health`, mesures radio de
  l'application.
- À la reconnexion, il les envoie par `{"cmd":"net_backlog", ...}`. Comme `layout_save` et `bug_report`, ce message
  est reconnu à son début et peut atteindre 60 ko (`cmd` écrit en premier). Au-delà, il est envoyé en plusieurs
  morceaux.
- La station refuse tout ce qui dépasse 15 min ou date d'avant la coupure précédente.

### 4.7 Écart d'horloge

La station estime l'écart entre l'horloge MURALE du client (champ `w`, ajouté au `net_ping` du client toutes les
60 s) et la sienne, comme NTP : milieu de l'aller-retour. Au-delà de 1 s, le journal le note et le backlog est recalé
sur l'heure de la station.

## 5. Sondes de la station (EF4)

- Décision technique du lot 2b (étape 138) : les sondes tournent DANS la passerelle (`netprobe/station_probes.py`),
  en tâche asyncio sans rien de bloquant (ICMP de Windows dans un fil), toute erreur gardée chez elles ; un module ne
  démarrerait que si `[modules]` est en service, donc pas par défaut. Ping sans privilège vérifié sur Debian 13
  (`ping_group_range` = 0 2147483647) et sous Windows (IcmpSendEcho). Passerelle par défaut : `/proc/net/route` ;
  Windows : table des routes, en sautant une route par défaut sans passerelle (VPN point à point).
- Deux cibles chaque seconde :
  - `lan_target` : `"auto"` = passerelle par défaut de la machine (Linux : `/proc/net/route` ; Windows :
    `GetBestRoute2` ou `route print`) ;
  - `internet_target` : `"1.1.1.1"` par défaut.
- Méthode, dans l'ordre :
  - ICMP sans privilège (Linux : socket `SOCK_DGRAM`/`IPPROTO_ICMP`, permise par `net.ipv4.ping_group_range` sur
    Debian 13 ; Windows : `IcmpSendEcho` par ctypes) ;
  - sinon connexion TCP, **toutes les 5 s seulement** (port 80 de la box, 443 de la cible Internet).

  La méthode retenue est affichée.
- Mêmes indicateurs qu'au § 4.4, sur les mêmes fenêtres.
- Une sonde ne peut rien faire d'autre qu'envoyer ces paquets. Le module n'a pas de droit sur le bus d'émission.

## 6. Journal et statistiques (EF6, EF10)

Tout est dans `state_dir/netprobe/` (lisible par le compte de la station, 0644 comme les autres fichiers d'état ;
jamais dans `station.toml`) :

| Fichier | Contenu | Durée |
|---|---|---|
| `AAAA-MM-JJ.jsonl` | résumés de 10 s par client et par sonde, changements d'état, mesures radio | `log_retention_days` (7) |
| `coupures.jsonl` | une ligne par coupure, avec son diagnostic | `stats_retention_days` (30) |
| `heures.jsonl` | résumé horaire par appareil : coupures, durée cumulée, perte, aller-retour p95, gigue, type de réseau | `stats_retention_days` (30) |
| `vpn.json` | appareils vus par adresse (§ 8), avertissements ignorés | 30 jours |

- Chaque ligne a un horodatage UTC en ms, une source (`client`, `passerelle`, `sonde`, `radio`), un type
  (`mesure`, `coupure`, `etat`) et ses valeurs.
- Volume estimé par client connecté en continu : environ 2 Mo par jour pour les résumés de 10 s, environ 15 ko par
  jour pour les heures. 30 jours de statistiques font moins de 1 Mo.
- Rotation à minuit UTC, nettoyage au démarrage du module puis chaque jour.
- **Un appareil** = l'identifiant `device` du § 8.1, jamais une adresse IP.

## 7. Diagnostic automatique (EF7)

À la fin d'une coupure (ou à la remise du backlog), la station applique la PREMIÈRE règle qui convient :

| N° | Constat | Tronçon probable |
|---|---|---|
| 1 | La passerelle a redémarré ou s'est figée pendant la coupure (journal du superviseur) | 5, application ou station |
| 2 | La sonde vers la box tombe aussi | 4, réseau local ou machine de la station |
| 3 | Seule la sonde Internet tombe (la box répond) | 2, connexion Internet de la box |
| 4 | Le battement tombe mais `/health` répond | 5, WebRTC ou passerelle |
| 5 | Application Android : signal sous `rsrp_alert_dbm` / `sinr_alert_db`, changement de cellule ou bascule Wi-Fi ↔ mobile dans les 10 s d'avant | 1, radio du téléphone |
| 6 | Motif régulier (§ 8.3) avec une radio correcte | 3, profil VPN probablement partagé |
| 7 | Tous les chemins du client tombent, les sondes de la station restent bonnes | 1 à 3, téléphone, réseau mobile ou tunnel |
| 8 | Données insuffisantes (pas de backlog) | indéterminé |

- Le diagnostic dit toujours sur quoi il s'appuie (« sondes station bonnes, /health perdu, signal −98 dBm »).
- Ce n'est jamais une certitude : le texte affiché dit « probable ».

## 8. Profil VPN partagé par deux appareils

Cause réelle des coupures du 2026-11-09 : le PC et le S25 étaient sur le même profil WireGuard. Le serveur VPN ne
garde qu'une adresse d'origine par profil, et chaque appareil la vole à l'autre à chaque paquet. Seul le serveur VPN
le voit directement. Il est hors de portée de la station (box, VPN de l'utilisateur), et lire son API (Freebox OS)
serait propre à un VPN : c'est écarté. La station repère donc les **effets**, de trois façons.

### 8.1 Identifiant d'appareil

- Chaque client tire au hasard, une fois, un identifiant de 128 bits :
  - page : `localStorage` (repli : un identifiant de session, alors la règle 8.3 seule s'applique) ;
  - application : ses préférences.
- Il est envoyé dans `POST /offer` (`"device"`, facultatif ; une station plus ancienne l'ignore).
- Il ne contient rien de personnel, n'est jamais montré à un autre client et n'apparaît dans l'export que remplacé
  par un repère (§ 10.3).
- La station l'accompagne du type de client (`page` ou `android`) et du système déclaré, pour les messages.

### 8.2 Même adresse, deux appareils (D1 en même temps, D2 en alternance)

- **D1** : deux connexions OUVERTES EN MÊME TEMPS, d'identifiants `device` différents, arrivent de la MÊME adresse
  privée (10/8, 172.16/12, 192.168/16, 100.64/10, fc00::/7).
- **D2** : la même adresse privée sert à deux `device` différents en moins de 10 min (fermeture de l'un, ouverture
  de l'autre).
- Adresses jamais prises en compte : 127.0.0.1 et ::1 (client sur la station), adresses publiques (plusieurs
  appareils derrière une même box distante, cas légitime).
- Effet : avertissement (jamais un refus) sur la page, dans l'application (opérateurs seulement) et dans
  trx-monitor, plus une alerte ntfy, au plus une par adresse et par 24 h :
  > « Deux appareils (Windows, page / Android, application) arrivent par la même adresse 192.168.27.2. S'ils passent
  > par un VPN, ils partagent probablement le même profil : c'est une cause connue de coupures toutes les 15 à 30 s.
  > Créez un profil par appareil. »
- Faux positif connu : la page ouverte dans Chrome ET l'application sur le MÊME téléphone (deux identifiants, une
  adresse). Le message propose « Ignorer pour cette adresse », gardé dans `vpn.json`, effacé par « Tout effacer ».
- Limite : un appareil qui est dans le VPN sans jamais se connecter à la station (le PC de l'incident) n'est pas vu
  par D1 ni D2. Seul le § 8.3 peut alors l'attraper.

### 8.3 Motif régulier des coupures (D3)

- Signature d'un profil partagé : au moins 4 coupures en 10 min, intervalles réguliers (coefficient de variation
  inférieur à 25 %, période de 10 à 150 s), durées voisines.
- Pour une application Android, il faut aussi une radio correcte (pas de règle 5 du § 7).
- Diagnostic : « profil VPN probablement partagé par un autre appareil (coupures toutes les ~28 s, signal bon) ». Les
  mêmes conseils que D1 et D2 s'affichent.
- `vpn_shared_warn = true` (défaut) active D1, D2 et D3. Avec `false`, seul le diagnostic du § 7 reste.

### 8.4 Documentation

- `docs/acces-distant.md` : « un profil VPN par appareil, jamais partagé » (fait dans cette étape).
- Aide du menu 19 de TRX Console (appairage d'un téléphone) : même phrase (lot 4).

## 9. Affichage : indicateur discret et détail

### 9.1 Niveau de l'indicateur

C'est le plus mauvais de (seuils EN SERVICE pour le type de réseau du client : choisis par l'opérateur, sinon ceux de
`station.toml`, § 9.6) :
- perte sur 60 s : vert < `loss_warn_pct` ≤ orange < `loss_alert_pct` ≤ rouge ;
- aller-retour p95 sur 60 s : mêmes paliers avec `rtt_warn_ms` / `rtt_alert_ms` ;
- coupure en cours : rouge ; coupure dans les 2 dernières minutes : au moins orange ;
- application Android : signal sous `rsrp_warn_dbm` / `sinr_warn_db` = orange, sous les seuils d'alerte = rouge.

Il est gris tant qu'il n'y a pas 10 s de mesures. Chaque niveau a aussi une FORME (barres pleines ou barrées), pour
ne pas reposer sur la seule couleur.

### 9.2 Page web

- **Indicateur** dans l'en-tête fixe : trois petites barres colorées (comme un niveau de réseau), sans texte.
- **Détail** : un toucher ouvre un **accordéon** sous l'en-tête :
  - perte 10 s / 60 s, aller-retour moyen et p95, gigue ;
  - état ICE, `/health`, type de réseau du navigateur ;
  - dernière coupure (durée, il y a combien de temps, tronçon probable) ;
  - avertissement de profil partagé s'il y en a un ;
  - lien « Statistiques 30 jours ».

  Fermé par défaut. L'état ouvert ou fermé est retenu dans le navigateur.

### 9.3 Application Android

- **Indicateur** dans la barre du haut : pastille avec le type de réseau (`4G`, `5G`, `Wi-Fi`) et trois barres
  colorées.
- **Détail** : un toucher ouvre un **panneau en bas d'écran** avec le même contenu que la page, plus la radio
  (RSRP/RSRQ/SINR ou RSSI Wi-Fi, niveau 0-4, cellule changée il y a…) et le lien vers l'écran plein écran des
  statistiques (§ 10).
- **Mode conduite et Android Auto** : pas d'indicateur permanent. Quand le niveau est ROUGE (coupure en cours ou
  seuils d'alerte), « Liaison faible » s'affiche :
  - en Android Auto : en tête du sous-titre, avant le S-mètre ;
  - en mode conduite : une ligne de texte sous la fréquence.

  Il disparaît après 10 s revenues au vert ou à l'orange, sans bip ni annonce vocale. Le titre (fréquence et mode)
  ne change pas.

### 9.4 trx-monitor

- Une ligne « Réseau » dans la vue principale : niveau par client connecté et état des deux sondes.
- La touche `n` ouvre le panneau « Réseau » complet (EF8) :
  - par tronçon : perte, aller-retour, gigue, dernière coupure ;
  - les sondes et leur méthode (ICMP ou TCP) ;
  - les 10 dernières coupures avec leur diagnostic ;
  - les avertissements de profil partagé.
- Actualisé chaque seconde. Lecture seule.

### 9.5 Visiteurs

Un visiteur voit l'indicateur et le détail de SON lien (calculés de son côté et par ses `net_pong`). Il ne voit
jamais les sondes de la station, les autres clients, les statistiques de 30 jours, l'export, les avertissements de
profil partagé ni « Tout effacer ».

### 9.6 Seuils réglés d'après les mesures

Personne ne sait d'avance quel aller-retour ou quelle perte gênent vraiment l'écoute et l'émission avec un réseau
mobile donné. Les seuils de l'indicateur n'ont AUCUN effet sur la sécurité ni sur la liaison : seulement sur la
couleur et les alertes. On peut donc les essayer sans risque, en trois temps.

1. **Mesurer ce qui s'entend.** En plus de la perte et de l'aller-retour, chaque résumé de 10 s garde ce qui dégrade
   le son pour de vrai :
   - côté client : `concealmentEvents` et `concealedSamples` de getStats (trous masqués par le décodeur), vidages de
     la réserve de gigue ;
   - côté station : `tx_underruns` et `tx_overruns` (son d'émission en retard ou jeté).

   Un résumé est « son dégradé » s'il y a eu au moins un trou audible (seuil d'environ 1 % d'échantillons masqués,
   affiné aux essais).
2. **Garder un histogramme par type de réseau.** Chaque résumé horaire (`heures.jsonl`) range les fenêtres de 10 s
   dans des cases :
   - aller-retour p95 : 0-50, 50-100, 100-150, 150-200, 250, 300, 400, 600, 800, 1 000, + ms ;
   - perte : moins de 0,5 (≈ 0), 0,5-1, 1-2, 2-5, 5-10, 10-20, + % (lot 1 : des cases demi-ouvertes comme
     l'aller-retour, pour que le bas d'une case soit un seuil utilisable).

   Chaque case compte les fenêtres, et parmi elles celles « son dégradé ». Types de réseau : réseau local, Wi-Fi,
   4G, 5G, inconnu (page sans `navigator.connection`). Environ 200 octets par heure et par type : négligeable.
3. **Essayer et proposer.** La vue des statistiques (§ 10.1) a une rubrique « Seuils » (opérateur) :
   - pour chaque type de réseau, deux curseurs (orange, rouge) pour l'aller-retour et pour la perte ;
   - en les déplaçant, la page recalcule sur les 30 jours enregistrés, SANS rien changer sur la station : « orange
     X % du temps, rouge Y % ; le son a été dégradé dans Z % des fenêtres rouges et W % des fenêtres vertes » ;
   - une valeur PROPOSÉE par type de réseau, dès 7 jours et 2 000 fenêtres de ce type :
     - orange = début des cases où le son est dégradé dans plus de 5 % des fenêtres ;
     - rouge = au-delà de 25 % ;
     - jamais en dessous du p75 habituel de ce réseau, pour qu'un réseau bon mais lent ne reste pas orange en
       permanence.

   Appliquer : la passerelle ne peut pas écrire `station.toml`. Les seuils choisis par l'opérateur sont rangés dans
   `state_dir/netprobe/seuils.json`, comme les choix de la mesure de TOS. Ils PRIMENT sur ceux de `station.toml`,
   qui restent les valeurs de départ. « Revenir aux valeurs de station.toml » les efface. « Tout effacer » efface
   l'historique, PAS les seuils choisis.

**Valeurs de départ** (`station.toml`, en attendant les mesures) : aller-retour 250 / 600 ms, perte 2 / 10 %, les
mêmes pour tous les réseaux. Les essais réels (§ 14) comparent 4G, 5G et Wi-Fi sur au moins 7 jours avant de changer
ces défauts dans le code.

## 10. Statistiques des 30 derniers jours, effacement, export

### 10.1 Vue « Qualité du réseau »

Page : rubrique en fin de Réglages. Application : écran plein écran ouvert depuis les Réglages et depuis le panneau du
§ 9.3. Opérateurs seulement. Choix de la période : 24 h, 7 jours, 30 jours ; choix de l'appareil : tous ou un
appareil.

Contenu :
1. **Synthèse** : nombre de coupures, durée cumulée, plus longue coupure, disponibilité en % du temps connecté,
   perte et aller-retour p95 médians.
2. **Coupures par jour** : barres, couleur par tronçon probable.
3. **Heures les plus touchées** : grille jour × heure, intensité = coupures (EF10).
4. **Répartition par tronçon** : barres horizontales, en %.
5. **Tendance** : aller-retour p95 et perte par jour (lignes).
6. **Par réseau** (application) : coupures et qualité en 4G, 5G et Wi-Fi.
7. **Liste des dernières coupures** : date, durée, tronçon, ce qui l'appuie.
8. **Seuils** : histogrammes par type de réseau, curseurs d'essai, valeurs proposées, « Appliquer » (§ 9.6).

Les données viennent de `heures.jsonl` et `coupures.jsonl` par la commande `net_stats` (§ 11), au plus 60 ko par
réponse ; la liste des coupures est paginée. Rien n'est recalculé sur le client.

### 10.2 Tout effacer

- Bouton « Tout effacer » (opérateur), confirmation en deux temps : « Effacer l'historique réseau des 30 derniers
  jours ? » puis le bouton rouge.
- Commande `net_clear`. La station efface `state_dir/netprobe/` (journal, coupures, heures, appareils vus,
  avertissements ignorés). Le client vide ses 10 min en mémoire. Les mesures reprennent aussitôt.
- Le journal de la station garde une ligne « historique réseau effacé par <compte> à <heure> ».
- TRX Console offre la même chose (menu 23, § 12).

### 10.3 Export pour l'équipe de développement

- Bouton « Exporter » (page : téléchargement ; application : partage par les applications du téléphone ou
  enregistrement dans Documents/OpenRemoteTRX) et `trx-netreport --export FICHIER` sur la station.
- Un fichier `openremotetrx-reseau-AAAAMMJJ.zip` contient :
  - `rapport.html` : la vue du § 10.1 en page autonome, lisible hors ligne ;
  - `donnees.json` : coupures, heures et résumés de 10 s des 7 derniers jours, versions de la station et des clients,
    méthode des sondes, réglages `[netprobe]`.
- **Anonyme par défaut** (même principe que `trx-journal-android`) :
  - adresses IP remplacées par des repères (`privée-A`, `publique-B`) ;
  - identifiants d'appareils remplacés par `appareil-1`, `-2` ;
  - pas de nom de compte ni d'identifiant de cellule (aucune position n'existe : § 2.7) ;
  - l'identifiant de station est gardé (`station-id`, déjà prévu pour la collecte).
- Une case, décochée par défaut : « joindre les identifiants de cellules » (s'ils existent, § 13).
- Les histogrammes et les seuils choisis (§ 9.6) sont toujours joints : ils aident l'équipe à choisir les défauts.
- Le fichier est fabriqué par la station. Le client le reçoit en morceaux de 48 ko (`net_export`), au plus 2 Mo.
- Envoi : par l'utilisateur (courriel, forum). Plus tard, pièce jointe du rapport de problème quand sa réception
  (étape 2 du signalement) existera.

## 11. Protocole (ajouts, version inchangée)

| Message | Sens | Rôle | Qui |
|---|---|---|---|
| `net_ping` | les deux | battement réseau, `seq`, `t`, `w` facultatif | tous |
| `net_pong` | les deux | écho, `seq`, `t`, `tr` ; aucune réponse | tous |
| `net_report` | client → station | résumé de 10 s (getStats, `/health`, réseau, radio) | tous (visiteur : non journalisé) |
| `net_backlog` | client → station | 10 dernières minutes après une coupure, 60 ko au plus | opérateurs |
| `net_stats` | client → station | statistiques (période, appareil, page), histogrammes compris | opérateurs |
| `net_thresholds` | client → station | appliquer les seuils choisis par type de réseau, ou revenir à ceux de station.toml | opérateurs |
| `net_clear` | client → station | tout effacer | opérateurs |
| `net_export` | client → station | export par morceaux (`part`) | opérateurs |
| `state.net` | station → client | niveau, indicateurs 10 s / 60 s, sondes (opérateurs), dernière coupure, avertissement | tous (réduit pour un visiteur) |
| `net_event` | station → client | coupure close et diagnostic, avertissement de profil partagé | opérateurs |
| `POST /offer` `device` | client → station | identifiant d'appareil (§ 8.1) | tous |

- Fonction `netprobe` dans `hello.features` (si `[netprobe] enabled`).
- Mises à jour : `docs/protocole.md`, exemples `tests/protocol/`, `docs/parite-web-android.md`.

## 12. Station : réglages, superviseur, console, rapport

### 12.1 `[netprobe]` de `station.toml`

| Clé | Défaut | Rôle |
|---|---|---|
| `enabled` | `true` | Active la sonde |
| `heartbeat_interval_s` | `1` | Période du battement réseau (0,5 à 10) |
| `outage_missed_beats` | `3` | Battements perdus pour déclarer une coupure (2 à 20) |
| `lan_target` | `"auto"` | Box à sonder (`auto` = passerelle par défaut) |
| `internet_target` | `"1.1.1.1"` | Cible Internet ; `""` = pas de sonde Internet |
| `loss_warn_pct` / `loss_alert_pct` | `2` / `10` | Paliers de départ de la perte sur 60 s (§ 9.6) |
| `rtt_warn_ms` / `rtt_alert_ms` | `250` / `600` | Paliers de départ de l'aller-retour p95 (cahier de l'utilisateur : 150 / 400 ; § 9.6) |
| `alert_outage_s` | `10` | Coupure qui déclenche une alerte ntfy ; `0` = aucune |
| `alert_cooldown_s` | `300` | Délai minimal entre deux alertes |
| `log_retention_days` | `7` | Résumés de 10 s |
| `stats_retention_days` | `30` | Coupures et résumés horaires (7 à 90) |
| `vpn_shared_warn` | `true` | Détection du profil partagé (§ 8) |
| `rsrp_warn_dbm` / `rsrp_alert_dbm` | `-105` / `-115` | Paliers du signal 4G/5G |
| `sinr_warn_db` / `sinr_alert_db` | `3` / `0` | Paliers du rapport signal/bruit |

- Défauts sans rien toucher. Une `station.toml` existante sans `[netprobe]` prend les défauts. Rien n'est réécrit
  dans les autres sections (`notify_url` intact : un test l'impose).
- Notice publique `docs/station-toml/contenu.toml` mise à jour (convention du dépôt).

### 12.2 Alertes (EF9)

Décision technique du lot 2a (étape 137) : les alertes partent de la PASSERELLE, par le même `notify_url` que celles des
visiteurs, et non du superviseur : c'est elle qui sait quand une coupure est close et diagnostiquée. Le superviseur
n'est pas modifié (une passerelle arrêtée est déjà signalée par lui).

- La passerelle envoie l'alerte ntfy :
  - coupure close plus longue que `alert_outage_s` ;
  - perte sur 60 s au-dessus de `loss_alert_pct` ;
  - profil partagé (§ 8).
- Message : durée, tronçon probable, appareil (type et système, jamais l'identifiant).
- Au plus une alerte par `alert_cooldown_s`, toutes causes confondues ; le profil partagé a son propre délai de 24 h.
- La perte sur 60 s n'alerte pas pendant une coupure ni dans la minute qui suit (déjà alertée comme coupure), et
  une seule fois jusqu'au retour sous le palier orange.
- Une sonde muette n'est pas une panne de la station (pas de reprise, pas de mode sûr). Le module des sondes est
  relancé comme tout module.

### 12.3 TRX Console et `trx-netreport`

- Menu 23 « Qualité du réseau » :
  - synthèse 24 h et 30 jours ;
  - dernières coupures ;
  - avertissements de profil partagé ;
  - seuils en service par type de réseau et valeurs proposées (§ 9.6, lecture seule : on applique depuis la page ou
    l'application) ;
  - export (chemin proposé sur le Bureau) ;
  - « Tout effacer » (confirmation en tapant `EFFACER`) ;
  - aide `h 23`.
- `trx-netreport [--jours N] [--export FICHIER]` : résumé lisible (EF10). Ajouté à `[project.scripts]`, à la liste
  `COMMANDS` d'`install.sh` et au mode d'emploi de la console.

## 13. Application Android : radio (EF11)

Reprise d'EF11, SANS la position, la seconde SIM ni les cellules des autres opérateurs (§ 2.6 et 2.7) :
- **Relevé de base, sans autorisation de localisation**, dans TOUTES les versions, Google Play comprise :
  - type de réseau (LTE, 5G NSA, 5G SA) ;
  - RSRP / RSRQ / RSSNR (4G), SS-RSRP / SS-RSRQ / SS-SINR (5G), niveau 0-4 ;
  - bascule Wi-Fi ↔ mobile, changement d'adresse, réseau validé, débits estimés ;
  - RSSI, bande et débit du Wi-Fi.

  `READ_PHONE_STATE` seulement si la version d'Android l'exige pour ces écouteurs (à vérifier au lot 6, API par API).
- **Changement de cellule** (handover, identifiant de cellule, timing advance de la cellule SERVANTE) :
  - Android ne le donne qu'avec `ACCESS_FINE_LOCATION` ;
  - écran éteint, il exige en plus le type `location` du service de premier plan, que Google Play fait justifier.

  Décision de l'utilisateur (2026-11-09) :
  - version installée à la main seulement, option désactivée par défaut, autorisation demandée à l'activation ;
  - aucune position n'est lue : l'autorisation ne sert qu'à l'identifiant de la cellule ;
  - version Google Play : sans cette option, comme pour le scrambler.

  Sans elle, la règle 5 du § 7 s'appuie sur le signal faible et les bascules de réseau seulement.
- **Écran éteint** : le service de premier plan existant (`microphone|mediaPlayback`) garde le relevé de base tant
  qu'une session est ouverte.
- Champs absents envoyés à `null`, absence gérée partout. Jamais de balayage réseau.
- **Calculs** dans `:logic` (tests sur la JVM). L'accès aux API Android reste dans `:core`.

## 14. Découpage en lots (une étape par lot, chaque lot validé avant le suivant)

| Lot | Contenu | Où |
|---|---|---|
| 1 | Calculs (§ 4.4, 4.5, 7, 8.3), vecteurs partagés, protocole (§ 11) dans `protocole.md` et `tests/protocol/` | Python, client.js, Kotlin `:logic` |
| 2a | FAIT (étape 137, station 0.106.0) : passerelle (`net_ping`/`net_pong`, `state.net`, `device`, D1/D2/D3, journal, heures, coupures, diagnostic sans les sondes, `net_*`, `[netprobe]`, alertes ntfy) ; partie protocole de la page (battements, résumés de 10 s, remise après une coupure, sans affichage) ; classes des commandes de l'application | passerelle, page, application |
| 2b | FAIT (étape 138, station 0.107.0) : sondes de la station (box, Internet : ICMP sinon TCP) dans la passerelle, faits `lan_probe_down` / `internet_probe_down` du diagnostic, `state.net.probes`. L'export (`net_export`, zip anonyme) passe au lot 4 avec `trx-netreport`, qui fabrique le même rapport | passerelle |
| 3 | FAIT (étape 139, station 0.108.0) : page : `/health` toutes les 5 s (aussi pendant une reconnexion), trous du son reçu (getStats), indicateur, accordéon, vue 30 jours, seuils (curseurs, proposition), effacement. Export : lot 4 | page |
| 4 | FAIT (étape 140, station 0.109.0) : trx-monitor (panneau « Réseau », touche `n`, événements), TRX Console menu 23, `trx-netreport`, export anonyme (`net_export`, bouton de la page, `--export`, menu 23). Aide du menu 19 : « un profil VPN par appareil » est dans le mode d'emploi du menu 23 et `docs/acces-distant.md` | station, page |
| 5 | FAIT (étape 141, application 0.53.0) : pastille de la barre du haut, détail, écran « Qualité du réseau » 30 jours (seuils, proposition, effacement), export partagé, « Liaison faible » en Android Auto et en mode conduite ; type de réseau du téléphone = Wi-Fi / mobile / réseau local (4G / 5G : lot 6) | Android |
| 6 | FAIT (étape 142, application 0.54.0) : relevé de base SANS autorisation (type de réseau Wi-Fi / 4G / 5G / réseau local, RSRP / RSSNR ou SS-RSRP / SS-SINR, niveau 0 à 4, bascule de réseau, réseau sous-jacent d'un VPN) toutes les 2 s ; changement de cellule en option, autorisation de localisation déclarée dans les manifestes `debug` / `release` seulement (vérifié : absente du manifeste fusionné `play`), APPLICATION OUVERTE seulement (écran éteint, Android refuse la localisation sans service de type `location`, non ajouté) ; trx-monitor : radio du téléphone | Android, station |

Les seuils et histogrammes (§ 9.6) sont livrés avec les lots 2 (station), 3 (page) et 5 (application).

**Tests** (au fil des lots) :
- les tests automatiques du cahier de l'utilisateur ;
- vecteurs partagés vérifiés par les trois codes ;
- faux transport qui perd, retarde ou désordonne ;
- D1, D2 et D3 avec leurs faux positifs (même adresse publique, 127.0.0.1, « Ignorer pour cette adresse ») ;
- liste blanche des visiteurs ;
- `net_backlog` trop gros ou trop ancien refusé ;
- un flot de `net_ping` invalides ne change RIEN à l'état PTT, au battement d'émission ni au TOT (test de
  non-régression de la sécurité) ;
- plantage du module des sondes sans effet sur la passerelle.

**Essais réels** : ceux du cahier de l'utilisateur, plus un essai D1 (PC et téléphone sur le même profil WireGuard,
les deux connectés à la station : avertissement attendu) et un essai D3 (PC dans le VPN sans ouvrir la page, téléphone
connecté : « profil probablement partagé » attendu). Pour les seuils (§ 9.6) : au moins 7 jours d'usage normal en
4G, en 5G et en Wi-Fi, puis comparaison des valeurs proposées avec le ressenti de l'opérateur. Les défauts du code
ne changent qu'après ces essais.

## 15. Réponses de l'utilisateur aux questions de la v2 (2026-11-09)

1. EF12 (conseil sur l'opérateur, données de l'ARCEP) : **retirée**, trop de ressources (§ 2.6).
2. Position : **retirée** partout (§ 2.7). Le changement de cellule, qui exige l'autorisation de localisation sans
   lire de position, existe hors Google Play seulement (§ 13) : confirmé par l'utilisateur.
3. Android Auto et mode conduite : **« Liaison faible »** quand le lien est rouge (§ 9.3).
4. Seuils : pas d'avis a priori ; ils sont **réglés d'après les mesures** (§ 9.6). Valeurs de départ
   250 / 600 ms et 2 / 10 %, revues après 7 jours d'essais en 4G, 5G et Wi-Fi.
