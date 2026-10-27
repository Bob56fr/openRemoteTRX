# Module Cluster DX (étape 28)

Référence : Claude Doc « Cahier des charges — Module Cluster DX ».
Le module récupère les spots des clusters DX et du RBN ; plus tard il les
affichera en marqueurs sur le spectre HF, avec QSY sur appui.

## Lot 1 — essai autonome (fait)

Paquet `trxstation/cluster/`, bibliothèque standard seulement. Il ne touche
NI au poste, NI à rigctld, NI à la station : on peut l'essayer station en
marche ou arrêtée.

    python -m trxstation.cluster --indicatif F4XXX
    python -m trxstation.cluster --indicatif F4XXX --rbn --continent EU --modes SSB FREEDV --duree 7200
    python -m trxstation.cluster --serveurs
    python -m trxstation.cluster --verifier-serveurs

Sans `--source` ni `--connu`, il se connecte à `on0dxk` puis, en secours,
`db0sue`. `--source HÔTE:PORT` (répétable) donne vos propres serveurs dans
l'ordre de priorité ; `--mot-de-passe` demande (saisie masquée) celui de la
première source.

Chaque ligne affichée : heure, `+` nouveau spot (`~` mise à jour avec
`--tout`), `DX`/`RBN`, fréquence kHz, indicatif, mode (`*` = déduit du plan de
bande), spotteur, pays/continent, nombre de spotteurs, commentaire. Une ligne
d'état par minute ; un bilan à la fin (durée écoulée ou Ctrl+C) dit si chaque
coupure a été rattrapée.

### Critère d'acceptation du lot 1

    python -m trxstation.cluster --indicatif <VOTRE INDICATIF> --duree 7200

doit finir par « RÉSULTAT : aucune coupure non rattrapée ». L'analyse des
lignes valides est vérifiée par `tests/test_cluster.py` (jeu de lignes
DXSpider, AR-Cluster, CC Cluster, RBN CW et FT8).

## Comportement

| Point | Règle |
| --- | --- |
| Envois au serveur | indicatif, et mot de passe s'il est demandé ET fourni ; rien d'autre (pas de commande, pas de filtre serveur, pas de spot) |
| Indicatif | obligatoire, forme vérifiée ; vide = refus de démarrer |
| Mot de passe | refusé s'il contient un caractère de contrôle (pas d'injection de commande) |
| Négociations telnet | retirées du flux, aucune réponse |
| Lignes reçues | 512 octets au plus (au-delà : jetée), contrôle et direction retirés |
| Ligne « DX de » illisible | comptée « mal formée », le flux continue |
| Modes suivis | CW, SSB, AM, FM, FreeDV (`FREEDV`, lu « FreeDV » ou « FDV ») ; décision du 2026-10-27 |
| Modes numériques | FT8, FT4, RTTY et autres TOUJOURS écartés (compteur `filtered_digital`), même sans filtre ; ne peuvent pas être choisis |
| Mode | lu dans le spot, sinon déduit du plan IARU R1 ; un spot sans mode dans une fenêtre FT8/FT4 ou un segment numérique est écarté ; 11 m : BLU supposée |
| Pays, continent, zone CQ | cty.dat (AD1C), mis à jour chaque semaine dans `<state_dir>/cluster/cty.dat` ; vérifié AVANT de remplacer l'ancien ; absent = pays inconnus, filtre de continent INOPÉRANT (signalé) |
| Doublons | même indicatif à ±1 kHz : heure et fréquence mises à jour, spotteurs comptés ; vu par un humain = couleur « cluster » |
| Âge | mesuré à la réception, pas sur l'heure HHMMZ du spot |
| Durée de vie | 15 min cluster, 10 min RBN (`--duree-vie`, `--duree-vie-rbn`) |
| Cache | 2 000 spots au plus, les plus anciens partent |
| Filtres | bande (dont `11m`), mode (CW SSB AM FM FREEDV), continent du SPOTTEUR, liste noire (spotté ou spotteur, `XX*` = préfixe) |
| Reconnexion | 10 s, 30 s, 1 min, 2 min, puis 5 min ; remise à zéro après une connexion qui a reçu un spot ou tenu 60 s |
| Bascule | clusters : une seule connexion à la fois ; 3 échecs = source suivante ; RBN : une connexion par source, indépendante |
| Connexion morte | aucune donnée depuis 5 min = reconnexion |
| Indicatif ou mot de passe refusé | source « en échec », PLUS jamais réessayée avant redémarrage (éviter le bannissement) |

Type de cluster (DXSpider, AR-Cluster, CC Cluster, RBN) : reconnu dans la
bannière, affiché, pas encore utilisé (les filtres côté serveur viendront
avec le lot 2, s'ils sont utiles).

## Serveurs proposés

Vérifiés le 2026-10-27 (connexion et bannière, rien envoyé) :

| Nom | Adresse | Logiciel |
| --- | --- | --- |
| on0dxk | on0dxk.dyndns.org:8000 | CC Cluster, Belgique |
| db0sue | db0sue.de:8000 | DXSpider, Allemagne |
| dxspider-uk | dxspider.co.uk:7300 | DXSpider, Royaume-Uni |
| hamserve | dxc.hamserve.uk:7300 | DXSpider, Royaume-Uni |
| w3lpl | dxc.w3lpl.net:7373 | DXSpider, États-Unis |
| ve7cc | dxc.ve7cc.net:23 | CC Cluster, Canada (FT8 et skimmers : SET/FT8, SET/SKIMMER) |
| nc7j | dxc.nc7j.com:7373 | AR-Cluster, États-Unis |
| rbn-cw | telnet.reversebeacon.net:7000 | RBN CW (le RTTY du même flux est écarté) |
| clusterdx | https://clusterdx.org/spots.php | Cluster DX des cibistes, 11 m (page web) |

Le RBN FT8 (port 7001) n'est plus proposé : modes numériques hors périmètre.
À revérifier à chaque livraison : `python -m trxstation.cluster --verifier-serveurs`.

## Cluster DX des cibistes (clusterdx.org)

    python -m trxstation.cluster --indicatif F4XXX --cb    # radioamateurs + cibistes
    python -m trxstation.cluster --connu clusterdx         # cibistes seuls (aucun indicatif demandé)

Le site n'a ni telnet ni API : la station lit la page publique `spots.php`,
un tableau des 100 derniers spots (n°, horodatage, spotteur, fréquence en
kHz, indicatif, commentaire), SANS mode ni pays. Relevé le 2026-10-27 :

- horodatage à l'heure de Paris (converti en UTC par la règle européenne
  d'heure d'été ; l'âge est calculé avec l'heure donnée par le serveur) ;
- spots plus vieux que la durée de vie : ignorés dès le premier relevé ;
- mode supposé BLU (marqué `*`) sauf s'il est écrit dans le commentaire ; un
  commentaire « FT8 » écarte le spot ;
- indicatifs cibistes (« 14LG56 », « 1AT/H688 ») : pas de pays (cty.dat ne
  les connaît pas), filtre de continent sans effet sur eux ;
- couleur de marqueur propre (`cb`).

Bonne conduite : une requête par minute au plus (la page du site se rafraîchit
elle-même toutes les 60 s), réponse limitée à 1 Mo, agent identifié
« TRX-Remote », jamais de connexion au compte. La page n'est pas une API
documentée : si elle change, la source passe « en échec » avec un message
« format », sans jamais produire de faux spot. Il serait correct de prévenir
l'administrateur du site de cet usage.

## Faux cluster

    python -m trxstation.devtools.fake_cluster --port 7300
    python -m trxstation.cluster --indicatif F4XXX --source 127.0.0.1:7300

## Lot 2 — service de la station (fait)

### Régler le Cluster DX

Debian : **TRX Console, menu 12**. Windows ou à la main :

    python -m trxstation.cluster.setup --config station.toml

La première fois, l'éditeur demande QUELS SPOTS recevoir :

1. clusters radioamateurs (spots saisis par des opérateurs) ;
2. RBN (stations CW repérées automatiquement, beaucoup de spots) ;
3. Cluster DX des cibistes (clusterdx.org, 11 m) ;

puis les MODES suivis (SSB, AM, FM, FreeDV, CW ; le numérique est toujours
écarté). Choisir le RBN sans la CW déclenche un avertissement. Pour chaque flux
choisi, une source est proposée dans la liste des serveurs vérifiés, puis
**testée** ; pour les clusters, un secours est proposé (bascule automatique).

Ensuite, le menu permet de revenir sur ces choix (`f`), d'ajouter, modifier ou
supprimer une source, de passer un cluster en premier, d'activer ou de
désactiver une source ou tout le module, de régler filtres et durées de vie.
Rien n'est écrit avant `w` (Enregistrer), et la configuration est validée
avant. Redémarrer ensuite la station (menu 5 ; la console le propose).

- **Test obligatoire** de toute source ajoutée ou modifiée : connexion,
  identification, un spot en 60 s au plus. Compte rendu : OK, serveur
  injoignable, indicatif refusé, mot de passe refusé ou demandé, aucun spot
  reçu, page illisible. Une source en échec n'est gardée que si on le confirme.
- **Mot de passe ou clé** : saisie masquée, écrits SEULEMENT dans
  `secrets.toml` ; affichés `****`. Entrée = garder, `-` = supprimer.

### Fichiers

| Fichier | Contenu | Droits |
| --- | --- | --- |
| `station.toml`, `[cluster]` et `[[cluster.source]]` | indicatif, modes, filtres, sources ; `secret = "nom"` (le NOM du mot de passe) | ceux de station.toml |
| `secrets.toml`, à côté de station.toml | `[secrets]` `"nom" = "mot de passe"` | 0600, compte `trx` |
| `<state_dir>/cluster/status.json` | état par source, compteurs, pastille | 0644, toutes les 5 s |
| `<state_dir>/cluster/cluster.log` | journal, 5 fichiers de 1 Mo | — |
| `<state_dir>/cluster/cty.dat` | pays des indicatifs, mis à jour chaque semaine | — |

`secrets.toml` n'est jamais : dans un rapport de dépannage, dans le paquet
d'installation, dans Git, réécrit par une mise à jour (`install.sh` n'y touche
pas), importé depuis Windows (les mots de passe sont à ressaisir, l'import le
signale). Le module corrige lui-même des droits trop larges au démarrage ; le
diagnostic les signale avec la commande qui corrige. Pas de chiffrement sur
disque (la clé serait sur la même machine).

### Le module

`[modules] run = ["cluster"]` (l'éditeur l'ajoute ou le retire avec
`[cluster] enabled`). Le superviseur le lance comme les autres modules :
processus séparé, priorité basse (nice 15), relance à délai croissant, jamais
en root, chemin de station.toml transmis par `TRX_CONFIG_PATH`. Le manifeste
ne lui donne AUCUN droit sur le poste (ni événement, ni commande) : seulement
des messages vers les pages (« Cluster DX : toutes les sources connectées »,
affichés dans le journal de la page, avec `health`).

Pastille : verte = chaque flux (groupe des clusters, chaque RBN, page CB) a une
connexion et un spot de moins de 15 min ; orange = en partie ; rouge = aucune
connexion.

### Diagnostic et rapport

Section « Cluster DX » du diagnostic : sources actives, présence et droits de
`secrets.toml`, état publié (vieux de plus de 30 s = module arrêté ou bloqué),
état de chaque source avec le dernier motif, âge du dernier spot, cty.dat. Le
rapport contient `cluster-etat.json` (état et compteurs), jamais les secrets.

## Lot 3 — spots sur le spectre HF (fait)

### Dans la page

Vue du spectre HF (3e état de la zone des graphiques) :

- **marqueurs** : un trait vertical par spot de la plage affichée et
  l'indicatif en étiquette ; trait et cadre selon la source (cluster =
  couleur d'accent, RBN = gris, CB = couleur des favoris ; jamais la couleur
  d'émission) ; spot de moins de 2 min en gras ; estompage avec l'âge ;
- **chevauchement** : étiquettes sur 3 rangées, puis regroupées en « +N »
  (un appui sur « +N » liste ces spots) ;
- **appui sur une étiquette** : fiche (indicatif, source, nombre de
  spotteurs, fréquence, mode — « supposé » s'il vient du plan de bande —,
  pays, spotteur, heure UTC, âge, commentaire) et bouton **QSY** ;
- **QSY** : le mode d'abord (adapté au poste : USB -> USB-D si l'émission
  l'exige ; inchangé si le poste ne le connaît pas), puis la fréquence, par
  les commandes HABITUELLES de la page ; bouton verrouillé pendant
  l'émission, et la station refuse de toute façon un changement de fréquence
  hors réception confirmée ;
- **LISTE** : spots de la bande, triés par fréquence ou par âge ;
- **SPOTS** : masque ou montre les marqueurs (mémorisé sur l'appareil) ;
- **pastille** verte, orange ou rouge : état du module (survol : détail) ;
  les messages du module s'affichent aussi dans le journal (« [cluster] … »).

Les boutons SPOTS et LISTE n'apparaissent que si la station a un module
cluster qui parle.

### Ce qui circule (données mobiles)

- Le module reçoit la fréquence du poste (événement `freq_mode`, lecture
  seule ; aucune commande permise) et ne retient que la **bande courante**
  (±500 kHz hors des bandes connues).
- Il envoie un **instantané** (150 spots au plus, environ 25 ko au pire) au
  changement de bande et toutes les 60 s, et entre deux les **changements**
  seulement, regroupés chaque seconde (marqueur à l'écran en moins de 2 s).
- La passerelle ne transmet ces messages qu'aux clients dont la **vue HF est
  ouverte** (la même commande `spectrum_watch` que pour les balayages : page
  masquée ou vue fermée = rien ne part). Elle garde le dernier instantané et
  les changements qui ont suivi, et les **rejoue** au client qui ouvre la vue :
  les spots s'affichent tout de suite.

Format des messages (`{"type": "module", "module": "cluster", "data": …}`) :
`data.kind = "spots"`, `op = "snapshot"` (avec `window` [début, fin] en kHz)
ou `"delta"` (avec `removed`), `scope = "hf_view"`, `retain`, et `spots` en
clés courtes : `id`, `f` (kHz), `dx`, `de`, `m` (mode), `mg` (mode supposé),
`k` (cluster, rbn, cb), `t` (HHMM UTC), `n` (spotteurs), `age` (s), `c`
(commentaire), `co` (pays), `ct` (continent), `q` (mode proposé pour le QSY).

### Pas fait dans ce lot

- **Android Auto** : l'application Android est en attente.
- **Designer** : l'option « marqueurs cluster » du widget waterfall et les faux
  spots de prévisualisation attendent l'éditeur de mises en page (le designer
  n'a encore que le moteur de rendu). Les marqueurs vivent dans la vue HF
  plein écran, qui n'est pas déplacée par les mises en page.
- Accord par appui sur le spectre lui-même (hors spot) : non demandé.

## À venir

- API web de secours pour les clusters radioamateurs (DXSummit) si utile.
- Mode « hors ligne » (question ouverte du cahier des charges) : aujourd'hui
  le cache garde les spots jusqu'à expiration et la pastille passe au rouge.
