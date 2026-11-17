# Diffusion en direct du TRX vers des internautes : cahier des charges (v4, décisions du 2026-11-17 sur les bandes, la console et le vocabulaire)

Demande de l'utilisateur (2026-11-17) : un petit service de diffusion « lowcost, lowtech », comme un podcast en direct
(pas de différé), pour faire entendre le son du TRX à quelques internautes (moins de 5 au départ) qui n'ont AUCUN compte
sur la station (ni opérateurs, ni visiteurs). Les auditeurs ne joignent JAMAIS la station : ils passent par un serveur
tiers, un petit VPS.

## 1. Décisions de l'utilisateur (2026-11-17)

1. **Responsabilité** : des milliers de SDR en ligne permettent déjà d'écouter n'importe quelle fréquence ; activer la
   rediffusion de son TRX est de la **responsabilité de l'opérateur**. Elle affiche un avertissement clair au premier
   lancement et le journalise. REMPLACÉ en partie par le § 11 (décisions du 2026-11-17) : ce qui est diffusé hors des
   bandes autorisées, c'est l'opérateur qui le décide (`[diffusion] outside_bands`).
2. **Voix émise par l'opérateur** : diffusée seulement si l'opérateur le demande EXPRESSÉMENT ; **désactivée par
   défaut**. Sans l'option, l'émission = silence pour les auditeurs.
3. **Durée** : 24 h/24 possible mais **pas par défaut** ; **1 h par défaut** ; l'opérateur choisit une durée en heures
   ou « sans limite ».
4. **Source** : le son du **TRX seulement** (pas le SDR, pas FreeDV décodé).
5. **Accès** : public ou privé, choisi par l'opérateur AVANT de lancer la diffusion ; **privé par défaut**.
6. **Métadonnées** : l'opérateur choisit dans une liste ce qu'il diffuse ; **par défaut son pseudo seul**.
7. **Mise en marche** : fermée par défaut ; un **indicateur explicite, visible tout le temps**, signale qu'une
   diffusion est active.
8. **Serveur** : un **petit VPS** (Icecast). Son code et sa configuration vont dans un **dépôt privé à part**
   (`openRemoteTRX-vps`) ; dans ce dépôt public restent le module de la station et le protocole (§ 9), pour qu'un autre
   utilisateur puisse monter son propre serveur. Aucun serveur imposé : adresse dans station.toml, rien par défaut.
9. Réponses au § 11 de la v1 (2026-11-17) :
   - **pas de reprise** après un redémarrage du PC (ou Pi) qui fait tourner trx-gateway ;
   - lancement par **tous les opérateurs**, **jamais les visiteurs** ;
   - mot de passe des auditeurs **fixe** jusqu'à ce que l'opérateur le change : c'est lui qui envoie les invitations
     aux auditeurs, de son côté (la station ne les envoie pas) ;
   - HTTPS par Caddy : accepté, à vérifier au lot D5 (vérifié : voir § 11, la SOURCE ne passe pas par Caddy).
10. Protocole (2026-11-17, « go » de l'utilisateur sur le brouillon) : métadonnées renvoyées au moins toutes les 30 s
    pendant une diffusion (nombre d'auditeurs) ; mots de passe des auditeurs en lettres et chiffres seulement (à
    dicter) ; identifiants des auditeurs renvoyés à chaque lancement privé (serveur sans sauvegarde) ; anti-rejeu par
    `ts_ms` strictement croissant, sans nonce. Contrat : `docs/protocole-diffusion.md`.

## 2. POC (fait le 2026-11-17, hors dépôt, « tests concluants » de l'utilisateur)

Station factice sur le PC de développement, Icecast 2.5.0 (Windows) sur le PC « tour radio », réseau local. Encodage
par **PyAV** (déjà installé avec aiortc : aucune dépendance nouvelle, pas de ffmpeg), envoi par le protocole source
d'Icecast (`PUT` + `Expect: 100-continue`, puis flux brut, comme libshout).

| Mesure | Résultat |
|---|---|
| Opus 32 kb/s mono (Ogg) | 1,2 % d'un cœur |
| MP3 64 kb/s | 2,2 % d'un cœur |
| Retard, réglages par défaut (réserve d'Icecast 16 ko, pages Ogg de 1 s) | 5,0 s |
| Retard, pages Ogg de 100 ms et réserve de 4 ko | **≈ 1 s** (2 s au pire) |
| Montage privé (identifiant) | refus 401 sans identifiant ou mauvais mot de passe, montage caché de l'état public |
| Lecteurs | Chrome (S25) et VLC : son et identifiant demandé, validés par l'utilisateur |

Leçons : le retard tient surtout à la réserve d'Icecast (`burst-size`) ; une source sur un montage occupé est refusée
(« Mountpoint in use ») ; un arrêt du serveur coupe la source (`ConnectionResetError`) : il faut se reconnecter seul ;
le titre ICY (`/admin/metadata`) ne marche qu'en MP3 et ne porte qu'une ligne ; sous Git Bash, un argument `/montage`
est changé en chemin Windows (`MSYS_NO_PATHCONV=1`).

### 2.1 Serveur de référence (lot D5, fait le 2026-11-17)

VPS OVH (Debian 13, paquets Debian seulement : correctifs automatiques), dépôt privé `openRemoteTRX-vps` (déploiement
idempotent) : Caddy (HTTPS Let's Encrypt, 443) pour les auditeurs, Icecast 2.4.4 (réserve 4 ko, 5 auditeurs par
montage, aucune page d'état publique), service des métadonnées `orx-meta` (bibliothèque standard), page des
auditeurs `/ecoute/<station>` (FR / EN, connexion par cookie pour le montage privé, lecteurs type VLC par
identifiant). Essais par Internet : 0,14 à 0,19 s entre l'envoi et la réception (auditeur connecté), privé / public,
mauvais mot de passe source refusé, montage occupé = 403, changement du mot de passe des auditeurs sans couper ceux
qui écoutent (18 vérifications).

## 3. Principe et sécurité (bloquant)

- Module du bus **« diffusion » SANS AUCUN DROIT sur le poste** (comme `presence` et `monlink`) : il ne lit que le son
  et l'état publié ; il ne peut ni changer de fréquence ni émettre. Une panne de la diffusion n'a aucun effet sur la
  réception, l'émission ou les sécurités.
- La passerelle lui envoie le son du TRX en PCM sur une prise **UDP 127.0.0.1** (comme le son du SDR, dans l'autre
  sens), le **même son que celui des visiteurs** ; pendant une émission, la voix de l'opérateur seulement si l'option
  du § 1.2 est cochée, sinon silence.
- **Connexion SORTANTE seulement**, de la station vers le VPS : aucun port ouvert, aucun canal de retour. Tout ce que
  renvoie le VPS (état, nombre d'auditeurs) est une donnée non fiable, jamais une commande.
- Secrets (mot de passe source, mot de passe des auditeurs) dans un fichier à part, `diffusion.key` (0600), jamais
  dans station.toml, jamais affichés en entier.
- La charge est jugée par la passerelle comme pour les visiteurs (`gateway/api/overload.py`) : en surcharge, la
  diffusion s'arrête avec la cause.
- Une diffusion **ne reprend jamais seule** après un redémarrage du PC ou du Pi de la station (décision § 1.9), ni
  après un mode sûr. Proposition du cahier, faute d'avis : une relance de la passerelle par le superviseur (panne)
  arrête aussi la diffusion, avec sa cause (fail-safe : la diffusion ne survit pas à ce qui l'a autorisée).

## 4. Son

- **Opus 32 kb/s mono en Ogg, pages de 100 ms** par défaut ; **MP3 64 kb/s** en option (iPhone ancien, applications
  de radio, titre ICY).
- 48 kHz en entrée ; aucun traitement de la page (égaliseur, ST) ; le niveau suit le son des visiteurs.
- Reconnexion seule après une coupure : 2, 4, 8… 60 s ; aiohttp (bascule IPv4 / IPv6, piège de l'étape 208).

## 5. Durée et arrêt

- Durée choisie au lancement : 1 h par défaut, de 1 à 24 h, ou « sans limite » (24 h/24).
- Arrêt : fin de la durée, opérateur (page, application, TRX Console), arrêt de la station, mode sûr, surcharge,
  fonction mise hors service. Chaque arrêt donne sa cause (code ORT).

## 6. Accès

- Choisi AVANT le lancement, figé pendant la diffusion : **privé** (défaut) ou **public**.
- Privé : identifiant + mot de passe d'auditeur demandés par le lecteur (authentification du montage d'Icecast).
  Un identifiant et un mot de passe d'auditeur par station, **fixes** jusqu'à ce que l'opérateur les change (« En
  générer un » proposé) ; l'opérateur les transmet lui-même à ses auditeurs (la station montre l'adresse d'écoute et
  l'identifiant à copier, le mot de passe sur demande). Comptes nominatifs : plus tard si utile.
- Public : adresse simple à partager ; jamais inscrit dans un annuaire (`Ice-Public: 0`).
- Plafond d'auditeurs réglé sur le VPS (5 pour commencer).

## 7. Métadonnées

Liste au choix de l'opérateur, **pseudo seul par défaut** : pseudo, indicatif, fréquence, mode, bande, état
réception / émission, S-mètre, message libre court. **Jamais** : adresse IP, nom de machine, locator précis, numéro de
série. Envoyées par la station au VPS à chaque changement (au plus une fois par seconde) en JSON signé (§ 9), lues par
la page des auditeurs ; en MP3, elles forment aussi le titre ICY.

## 8. Indicateur et commandes

- **Indicateur toujours visible** dès qu'une diffusion est active : page (en-tête, pastille rouge « DIFFUSION » + nombre
  d'auditeurs + temps restant), application Android (bandeau), Android Auto (sous-titre), TRX Console (en-tête),
  trx-monitor, indicateur GNOME et Windows. Alerte ntfy au début et à la fin.
- Lancement et arrêt : TOUS les opérateurs (jamais les visiteurs, commande hors de leur liste blanche), depuis la
  page, l'application ou TRX Console ; tout opérateur peut arrêter la diffusion lancée par un autre ;
  avertissement du § 1.1 à confirmer au premier lancement.
- Fonction **hors service par défaut** : interrupteur du menu 5.5 ; réglages (serveur, codec, mots de passe) dans un
  nouveau menu en FIN du thème 5 (4 langues).

## 9. Protocole public (ce dépôt)

`docs/protocole-diffusion.md` : protocole source d'Icecast utilisé (montage, en-têtes), et métadonnées : JSON signé
HMAC-SHA256 par la clé de la station (`POST /meta/<montage>`), champs, cadence, vecteurs de test
`tests/protocol/diffusion_vectors.json`. Un serveur Icecast quelconque suffit pour le son ; seul le service des
métadonnées est à écrire par celui qui monte son propre VPS.

## 10. Lots

- **D0** POC : fait (§ 2).
- **D1** Station, en deux étapes :
  - **D1a** (fait, étape 242) : protocole public `docs/protocole-diffusion.md`, calculs purs
    `trxstation/diffusion/protocol.py` (signature, corps, métadonnées permises, requête source brute, durée, mot de
    passe généré), vecteurs `tests/protocol/diffusion_vectors.json` (mêmes octets que le serveur).
  - **D1b** (fait, étape 244) : module « diffusion », `[diffusion]` de station.toml, `diffusion.key`, son par UDP local, encodage
    PyAV, envoi en flux brut TLS, reconnexion, durée, état publié, codes ORT ; faux Icecast
    `devtools/fake_icecast.py` ; tests (aucun droit sur le poste, voix émise seulement avec l'option, arrêt en fin de
    durée, reconnexion, surcharge).
- **D2** (fait, étape 245) Commandes client et page (panneau de lancement, indicateur), `docs/protocole.md` § 20,
  `hello.features`, `state.diffusion` (opérateurs), réglage `outside_bands` (§ 12.1).
- **D3** (fait en grande partie, étape 246) TRX Console : interrupteur 5.5 et menu **5.6** (état, lancer avec
  avertissement au premier lancement, arrêter, identifiants des auditeurs voir / générer, réglages `[diffusion]` dont
  hors bandes, secrets du serveur dans `diffusion.key` écrit par la console elle-même en 0600 au compte du service,
  jamais par une demande au module) ; alertes ntfy de la PASSERELLE au début (ORT-6101) et à la fin (ORT-6102, avec la
  cause) ; guide de l'opérateur (partie 9). RESTE de la proposition du § 12.3 (à valider) : lien et QR code des
  canaux, « Dernières diffusions », essai de liaison avec le serveur, qualité et durée par défaut réglables ;
  indicateurs GNOME / Windows. La ligne « Diffusion » du tableau de bord et de trx-monitor : conversation de la
  console web (§ 12.5).
- **D4** Application Android : indicateur, lancement, arrêt (parité).
- **D5** VPS, dépôt privé `openRemoteTRX-vps` : FAIT le 2026-11-17 (§ 2.1) ; reste l'essai avec la vraie station
  (D1b) et la page sur iPhone (anciens Safari et Opus : option MP3).

## 11. Questions de la v1 : toutes tranchées (§ 1.9)

Vérifié au lot D5 (2026-11-17) : un `PUT` en flux continu NE PASSE PAS à travers Caddy. Icecast 2.4.4 (celui de
Debian) ne comprend pas l'envoi « chunked » (les en-têtes des morceaux corrompent les pages Ogg : l'auditeur ne reçoit
rien), et Caddy transmet toujours ainsi un corps de longueur inconnue (sans longueur ni chunked, le corps est perdu).
Décision : la station envoie en FLUX BRUT, comme libshout, en TLS DIRECTEMENT à Icecast sur un port à part (8443 sur
le serveur de référence, certificat de Caddy recopié chaque jour) ; les auditeurs restent derrière Caddy (443). Ce
choix marche avec n'importe quel Icecast (§ 9). Icecast 2.5 (dépôt Xiph) écarté : rien pour Debian 13, et hors des
correctifs automatiques.

Trouvé au lot D1b (2026-11-17) : Icecast 2.4.4, quand il fait lui-même le TLS, tourne en boucle à 100 % d'un cœur et
garde le montage occupé pour toujours quand une source ferme PROPREMENT sa session TLS (close_notify, ce que fait
asyncio). Corrigé des deux côtés : sur le serveur de référence, stunnel tient le TLS du port des sources et transmet
en clair à Icecast (fin TCP normale) ; la station ferme sans close_notify (compatibilité avec un Icecast nu).

## 12. Décisions de l'utilisateur du 2026-11-17 : bandes, TRX Console, vocabulaire (v4)

1. **Ce qui est diffusé, c'est l'opérateur qui le décide** : il est juridiquement responsable de sa station, le
   logiciel ne choisit pas à sa place. La décision « pas de filtre de bandes » (§ 1.1) est remplacée par un
   interrupteur des réglages de la diffusion, « Diffuser aussi hors des bandes autorisées » (`[diffusion]
   outside_bands`) :
   - non : SILENCE pour les auditeurs quand la réception sort des `[[bands]]` de station.toml, SANS arrêter la
     diffusion ; le son revient dès que le poste rentre dans une bande autorisée ; fréquence inconnue : silence (comme
     `listener_muted` des visiteurs) ;
   - oui : tout est diffusé, quelle que soit la fréquence ;
   - même principe que `[access] listeners_outside_bands` des visiteurs (défaut false), réglages INDÉPENDANTS ;
   - valeur par défaut : pas encore tranchée par l'utilisateur ; `false` proposé et appliqué (étape 245), comme
     pour les visiteurs.
2. **Rangement dans TRX Console** : le thème 4 « Accès et comptes » regroupe ceux qui se CONNECTENT à la station ;
   le thème 5 « Fonctions » regroupe ce que la station ENVOIE vers l'extérieur : la diffusion y va. Interrupteur du
   service dans le menu 5.5 ; menu de la diffusion en **5.6** (ajouté en fin de thème), dans les quatre langues
   (lot D3).
3. **Arborescence proposée du 5.6 « Diffusion en direct »** (proposition, pas encore validée en détail) :
   - État : en cours ou non, canal, auditeurs privé / public, temps restant, qui l'a lancée, serveur joignable.
   - Lancer ou arrêter : canal, durée (1 h par défaut), avertissement au premier lancement ; tout opérateur peut
     arrêter.
   - Canal privé : identifiant et mot de passe des auditeurs (« En générer un »), lien et QR code ; changer le mot
     de passe ne coupe pas ceux qui écoutent déjà.
   - Canal public : lien et QR code.
   - Ce qui est diffusé : l'interrupteur hors bandes (point 1), la voix émise (non par défaut), les informations
     montrées, la qualité, la durée par défaut.
   - Serveur : adresse, identifiant de la station, clé (fichier à part, jamais affichée), essai de liaison.
   - Dernières diffusions : début, durée, nombre maximal d'auditeurs.
4. **Vocabulaire commun** : « visiteurs » = UNIQUEMENT les comptes de la station (page, application, menu 4.2) ;
   « auditeurs » = UNIQUEMENT la diffusion. Dans le tableau de bord, l'ancien « Auditeurs » s'appelle déjà
   « Écoutes du poste » (étape 243). Le nombre d'auditeurs par canal vient de la réponse `auditeurs` du protocole
   (`docs/protocole-diffusion.md` § 3.1), avec au plus 30 s de retard ; il est seulement affiché.
5. **Partage du travail** : la conversation de la console web reprend elle-même le titre du menu 4.2 et la ligne
   « Diffusion » du tableau de bord ; les deux conversations se préviennent avant de livrer (numéros d'étape).
