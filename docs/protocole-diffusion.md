# Protocole de diffusion : station ↔ serveur (v1)

Contrat entre le module « diffusion » de la station (lot D1, `trxstation/diffusion/`) et le serveur de diffusion
(Icecast + service des métadonnées). Cahier : [diffusion-cahier-des-charges.md](diffusion-cahier-des-charges.md).
Vecteurs : `tests/protocol/diffusion_vectors.json` (fabriqués par `python -m trxstation.diffusion.vectors`), à
reproduire octet pour octet par toute autre mise en œuvre, station ou serveur.

Le serveur de référence (Debian 13, Caddy, Icecast 2.4, service `orx-meta`) est dans un dépôt privé ; quiconque
monte son propre serveur suit ce document : un Icecast quelconque suffit pour le son (§ 2), le service des
métadonnées (§ 3 et § 4) est à écrire.

Principe (cahier § 3) : connexions SORTANTES de la station seulement ; tout ce que renvoie le serveur est une donnée
non fiable (affichée, jamais exécutée).

## 1. Réglages de la station

- `station.toml`, `[diffusion]` : serveur, port des sources (8443 sur le serveur de référence), nom de la station
  (montages et page), codec (`opus` par défaut, `mp3`).
- `diffusion.key` (0600, jamais dans station.toml, jamais affiché en entier) : mot de passe source, clé des
  métadonnées (64 caractères hexadécimaux), identifiant et mot de passe des auditeurs. Les deux premiers sont donnés
  par l'administrateur du serveur.
- Nom de la station : 2 à 32 caractères `a-z 0-9 -`.

## 2. Son : protocole source d'Icecast

- Connexion TLS à `serveur:port des sources`, c'est-à-dire à Icecast lui-même, PAS à un mandataire HTTP.
- Requête (vecteur `source`) :
  ```
  PUT /<station>-<acces> HTTP/1.1
  Host: <serveur>:<port>
  Authorization: Basic base64("source:" + mot de passe source)
  Content-Type: audio/ogg            (audio/mpeg en MP3)
  Ice-Public: 0
  Ice-Name: <pseudo>
  User-Agent: openRemoteTRX
  ```
  `<acces>` = `prive` (défaut) ou `public`, choisi avant le lancement, figé pendant la diffusion.
- **Ni `Transfer-Encoding: chunked`, ni `Content-Length`** : après la ligne vide, le flux brut, sans fin, comme
  libshout. Icecast 2.4 (celui de Debian) ne comprend pas le chunked : les en-têtes des morceaux corrompent les pages
  Ogg et l'auditeur ne reçoit rien (essai du 2026-11-17). Pour la même raison, la source ne passe pas par un
  mandataire HTTP (Caddy, nginx), qui transmettrait en chunked un corps de longueur inconnue ou le perdrait.
- Icecast répond `HTTP/1.0 200 OK` puis ne dit plus rien. La réponse se lit sur la prise elle-même : un client HTTP
  qui « lit la réponse » ferme souvent sa connexion, et l'envoi suivant en ouvrirait une autre, sans requête.
- Refus : `401` (mot de passe source), `403` (montage occupé : une autre source y est déjà), coupure.
- **Fin : fermer la connexion SANS « close_notify » TLS** (fin TCP nette). Icecast 2.4.4, quand il fait lui-même le
  TLS, tourne en boucle à 100 % d'un cœur sur un close_notify et garde le montage occupé pour toujours : toute
  reconnexion reçoit alors 403 (essai du 2026-11-17, avec le client asyncio de la station). Côté serveur, le TLS du
  port des sources se confie à un terminateur TCP (stunnel sur le serveur de référence, qui transmet en clair à
  Icecast en 127.0.0.1) plutôt qu'au TLS d'Icecast ; la connexion s'établit aussi bien plus vite (0,4 s au lieu de
  3 s).
- Opus : Ogg, pages de 100 ms, 32 kb/s mono, 48 kHz (MP3 : 64 kb/s). Mesuré sur le serveur de référence : 0,14 à
  0,19 s entre l'envoi d'un échantillon et sa réception par un auditeur connecté ; un nouvel auditeur reçoit environ
  1 s de réserve (`burst-size` 4 ko) ; un navigateur met quelques secondes à démarrer la lecture.
- Coupure : nouvel essai après 2, 4, 8, 16, 32 puis 60 s (vecteur `reconnexion_s`). Icecast coupe une source muette
  depuis 10 s : la station envoie du son en continu (silence compris).

## 3. Requêtes signées de la station (HTTPS 443)

- `POST https://<serveur>/api/v1/<station>/<action>`, `Content-Type: application/json`, corps ≤ 4 ko.
- `X-Orx-Signature` = HMAC-SHA256(clé des métadonnées, `"POST" + "\n" + chemin + "\n" + corps`), en hexadécimal
  minuscule ; `chemin` = `/api/v1/<station>/<action>`, sans hôte ni paramètre ; `corps` = les octets EXACTS envoyés
  (la station envoie du JSON compact UTF-8, sans échappement des accents). La signature couvre le chemin : un corps
  signé pour `meta` ne vaut rien pour `auditeur`.
- Champs communs : `v` = 1, `station` (identique au chemin), `ts_ms` = heure de la station en millisecondes Unix,
  STRICTEMENT croissant d'une requête à l'autre (même si l'horloge recule). Le serveur refuse `|ts_ms − son heure| >
  120 s` (400) et un `ts_ms` qui n'est pas plus grand que le dernier accepté pour cette station (409, rejeu). Pas de
  nonce : une seule station par clé.
- Réponses JSON ; erreur `{"erreur": "<texte>"}` : 400 (corps), 401 (signature), 404 (station inconnue), 409 (rejeu),
  413 (taille), 429 (cadence).

### 3.1 `meta` : métadonnées

```json
{"v":1,"station":"bob56fr","ts_ms":1800000000000,"acces":"prive","meta":{"pseudo":"BOB-56-FR"}}
```

- `acces` : le montage en cours. Envoi au lancement, à chaque changement (au plus une fois par seconde ; le serveur
  refuse deux envois en moins de 0,5 s) et au moins toutes les 30 s pendant la diffusion (le nombre d'auditeurs
  revient dans la réponse).
- `meta` : SEULS champs permis (champ inconnu = 400), tous facultatifs ; l'opérateur choisit lesquels envoyer
  (cahier § 7 : pseudo seul par défaut). Aucun caractère de contrôle. Jamais d'adresse IP, de nom de machine, de
  locator précis, de numéro de série.

  | Champ | Type | Limite |
  |---|---|---|
  | `pseudo` | texte | 32 caractères |
  | `indicatif` | texte | 16 |
  | `frequence_hz` | entier | 0 à 300 000 000 000 |
  | `mode` | texte | 12 |
  | `bande` | texte | 12 |
  | `tx` | booléen | émission en cours |
  | `s_metre` | texte | 8 (ex. `S9+20`) |
  | `message` | texte | 140 |

- `silence` (facultatif, hors de `meta`, depuis la station 0.191.0) : pourquoi les auditeurs n'entendent rien en ce
  moment, pour le leur dire. TOUJOURS envoyé quand il s'applique (aucune donnée personnelle), absent quand le son
  passe. Valeurs : `hors_bandes` (réception hors des bandes autorisées, `[diffusion] outside_bands = false`),
  `emission` (l'opérateur émet et sa voix n'est pas diffusée), `pas_de_son` (le son du poste n'arrive plus au module
  depuis 2 s). Le serveur refuse (400) une autre valeur ; un serveur plus ancien l'ignore. Exemple signé : vecteur
  « meta publique, silence hors bandes ».

  ```json
  {"v":1,"station":"bob56fr","ts_ms":1800000003000,"acces":"public","meta":{"pseudo":"BOB-56-FR"},"silence":"hors_bandes"}
  ```

- Réponse : `{"ok":true,"auditeurs":{"prive":N,"public":M}}` (`auditeurs` = `null` si Icecast ne répond pas). La
  station la vérifie (entiers de 0 à 10 000, sinon ignorée) et ne fait que l'afficher.

### 3.2 `auditeur` : identifiant et mot de passe du montage privé

```json
{"v":1,"station":"bob56fr","ts_ms":1800000002000,"user":"auditeur","password":"Abcdef123456"}
```

- `user` : 1 à 32 caractères `A-Z a-z 0-9 . _ -` ; `password` : 8 à 64 lettres ou chiffres (à dicter et à taper sur
  un téléphone ; « En générer un » : 12 caractères sans 0, O, 1, l, I).
- Effet immédiat : anciens identifiants et pages connectées refusés ; un auditeur déjà en écoute n'est PAS coupé.
- La station renvoie ses identifiants à chaque lancement d'une diffusion privée : un serveur refait n'a rien à
  sauvegarder.

## 4. Côté auditeurs (rien à faire pour la station)

- Page : `https://<serveur>/ecoute/<station>` (lecteur, métadonnées, connexion pour le montage privé). C'est
  l'adresse que l'opérateur transmet ; la station l'affiche avec l'identifiant (le mot de passe sur demande).
- Lecteurs (VLC, applications de radio) : `https://<serveur>/<station>-prive` (identifiant demandé) ou `-public`.
- Service de la page (serveur de référence) : `GET /api/v1/<station>/etat` → `{"en_direct":false}` ou
  `{"en_direct":true,"acces":…,"montage":…,"meta":{…},"silence":…,"maj":<s>,"auditeurs":N,"places":P}` (`silence` :
  dernière raison reçue de la station, null si le son passe ; `places` : auditeurs au plus par montage) ; montage privé sans connexion :
  401 `{"en_direct":true,"acces":"prive","connexion":true}`. `POST /api/v1/<station>/connexion`
  `{"user","password"}` : cookie de 12 h (HttpOnly, Secure, SameSite=Strict) ; 5 échecs d'une même adresse en 10 min
  = 429.
