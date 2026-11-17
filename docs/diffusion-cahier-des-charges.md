# Diffusion en direct du TRX vers des internautes : cahier des charges (v1)

Demande de l'utilisateur (2026-11-17) : un petit service de diffusion « lowcost, lowtech », comme un podcast en direct
(pas de différé), pour faire entendre le son du TRX à quelques internautes (moins de 5 au départ) qui n'ont AUCUN compte
sur la station (ni opérateurs, ni visiteurs). Les auditeurs ne joignent JAMAIS la station : ils passent par un serveur
tiers, un petit VPS.

## 1. Décisions de l'utilisateur (2026-11-17)

1. **Responsabilité** : des milliers de SDR en ligne permettent déjà d'écouter n'importe quelle fréquence ; activer la
   rediffusion de son TRX est de la **responsabilité de l'opérateur**. La station ne filtre pas les bandes ; elle
   affiche un avertissement clair à l'activation et le journalise.
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
- Une diffusion **ne reprend pas seule** après un redémarrage de la station ou un mode sûr (proposition, § 10).

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
  Lot D1 : un identifiant et un mot de passe d'auditeur par station, changeables, générables. Comptes nominatifs :
  plus tard si utile.
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
- Lancement et arrêt : opérateurs seulement (jamais les visiteurs), depuis la page, l'application ou TRX Console ;
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
- **D1** Station : module « diffusion », `[diffusion]` de station.toml, `diffusion.key`, son par UDP local, encodage
  PyAV, envoi, reconnexion, durée, état publié, codes ORT ; faux Icecast `devtools/fake_icecast.py` ; tests (aucun
  droit sur le poste, voix émise seulement avec l'option, arrêt en fin de durée, reconnexion, surcharge).
- **D2** Commandes client et page (panneau de lancement, indicateur), `docs/protocole.md`, `hello.features`.
- **D3** TRX Console (menu, interrupteur 5.5), trx-monitor, ntfy, indicateurs GNOME / Windows, guide de l'opérateur.
- **D4** Application Android : indicateur, lancement, arrêt (parité).
- **D5** VPS, dépôt privé `openRemoteTRX-vps` : Debian 13, Caddy (TLS), Icecast (réserve 4 ko, plafond), service des
  métadonnées, page publique des auditeurs (lecteur + métadonnées), sauvegardes.

## 11. Questions ouvertes (réponses attendues avant D1)

1. Reprise après un redémarrage de la station : jamais (proposé) ou reprise de la diffusion en cours ?
2. Lancement par TOUT opérateur, ou par les comptes administrateurs seulement ?
3. Mot de passe des auditeurs : fixe jusqu'à ce que l'opérateur le change (proposé), ou nouveau à chaque diffusion ?
4. TLS jusqu'à Icecast (source et auditeurs en HTTPS par Caddy) : à vérifier au lot D5 (un `PUT` en flux continu à
   travers le mandataire).
