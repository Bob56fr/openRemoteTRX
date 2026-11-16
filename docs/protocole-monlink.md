# Monitoring inter-stations — protocole, mode R (v1)

Contrat entre le module « monlink » de la station (`trxstation/monlink/`, ce dépôt) et le relais (PHP 8.2 + `sodium`,
dépôt privé `openRemoteTRX-relay`, **mêmes hébergement et garde-fous que la présence**). Cahier des charges :
`docs/cdc-monitoring.md` § 17. Vecteurs communs, à reprendre tels quels dans le dépôt du relais :
`tests/protocol/monlink_vectors.json` (refabriqués par `python -m trxstation.monlink.vectors`, jamais à la main).

Le relais est une boîte aux lettres : il **authentifie les stations, range des enveloppes chiffrées et les rend à leur
destinataire**. Il ne déchiffre rien. Il voit : deux identifiants, un type de message, un numéro de séquence, des
tailles et des heures. Il ne garde aucune adresse IP en base.

Rôles : le **receveur** aide (il invite, il reçoit la télémétrie, il peut DEMANDER) ; l'**émetteur** est la station
surveillée (elle envoie ce que son opérateur a accepté, elle seule décide). Aucun message ne commande quoi que ce soit.

## 1. Encodages

Ceux de la présence (`docs/protocole-presence.md` § 1) : base64url sans `=` canonique, JSON compact à clés triées en
ASCII, octets signés transmis tels quels, secondes Unix, pseudo de 1 à 16 caractères.

| Élément | Forme |
|---|---|
| Identifiant de station | `hex(SHA-256("orx-monlink id v1\0" ‖ ed_pub)[0:16])`, 32 caractères `[0-9a-f]` (domaine **différent** de la présence : deux identifiants sans lien) |
| Code d'invitation | 10 caractères base32 de Crockford (`0-9 A-Z` sans `I L O U`), affiché `ABCDE-FGHJK` ; à la saisie : casse libre, espaces et tirets ignorés, `O` = `0`, `I` et `L` = `1` |
| Adresse d'invitation | 32 caractères `[0-9a-f]` (§ 2) |

## 2. Code, invitation, appairage (stations seulement ; le relais ne fait que ranger)

1. scrypt(code, sel `"orx-monlink invite v1"`, N = 2^15, r = 8, p = 1, 48 octets) : octets 0-15 = **adresse**
   (hexadécimal), 16-47 = **clé du code** (jamais envoyée).
2. Le receveur dépose `{"a": adresse, "box": base64url(nonce ‖ XChaCha20-Poly1305(clé du code, nonce, JSON,
   aad = "orx-monlink invite v1\0" ‖ adresse)), "e": expiration}` ; JSON = `{"v":1,"id","ed","x","pseudo","e"}`.
3. L'émetteur reprend la boîte par l'adresse tirée du code tapé, la déchiffre, vérifie `id` = empreinte de `ed`.
4. Demande d'appairage `{"a","from","to","box","s"}` : `box` = sceau de la présence (X25519 éphémère, HKDF-SHA256,
   XChaCha20-Poly1305) pour la clé `x` du receveur, aad = `"orx-monlink pair v1\0" ‖ a ‖ "\0" ‖ to ‖ "\0" ‖ from`,
   contenu `{"v":1,"id","ed","x","pseudo","t","proof"}`, `proof` = HMAC-SHA256(clé du code, `"orx-monlink pair v1\0"
   ‖ a ‖ to ‖ from ‖ ed ‖ x`) ; `s` = signature Ed25519 de l'émetteur sur aad ‖ box.
5. Empreinte : BLAKE2b-64(`"orx-monlink fp v1\0"` ‖ min(ed) ‖ max(ed)) mod 10^6, affichée `123 456` des deux côtés,
   **comparée de vive voix** : c'est elle qui protège contre un intermédiaire, relais compris.
6. Clé de liaison : X25519(clés statiques) puis HKDF-SHA256(sel = les deux identifiants triés et accolés, info
   `"orx-monlink link v1"`), 32 octets, la même des deux côtés.

Motifs de refus côté station : `malformed`, `decrypt`, `signature`, `unknown_invite`, `expired`, `proof`, `self`.

## 3. Requêtes au relais

Comme la présence (§ 3 de `docs/protocole-presence.md`) : `POST`, en-têtes `X-Orx-Station` et `X-Orx-Signature`
(Ed25519 de `"orx-relay v1\n" ‖ "POST\n" ‖ chemin ‖ "\n" ‖ corps`), champs `t` (±600 s) et `n` (strictement
croissant), même ordre des contrôles, mêmes codes d'erreur. Différences :
- chemins `/v1/mon/<route>` ; route inconnue = 404 `unknown_route` ;
- l'identifiant vérifié est celui du monitoring (§ 1) ; la table des stations du monitoring est **distincte** de
  celle de la présence ;
- corps de 72 ko au plus (`too_large`) ;
- motifs propres au monitoring : `404 unknown_invite`, `403 not_linked`, `403 not_allowed`, `403 direction`.

Mise en œuvre de référence du relais : `src/MonApi.php` du dépôt du relais (tests `tests/MonApiTest.php`, qui
rejouent les requêtes des vecteurs octet pour octet, et `tests/e2e_monlink.py`, code de la station contre le vrai
relais).

## 4. Points d'entrée

| Route | Qui | Corps (en plus de `t`, `n`) | Effet / réponse |
|---|---|---|---|
| `register` | toute station | `ed`, `x`, `pow` (preuve de travail de la présence § 5, sur l'identifiant du monitoring) | crée la station (`403 pow` avec `bits` si la preuve manque) ; `409 exists` si elle l'est déjà : la station le prend pour un succès ; `400 malformed` si l'identifiant n'est pas celui du monitoring |
| `invite/put` | receveur | `a`, `box` (2 ko au plus), `e` (≤ maintenant + 900) | range l'invitation ; 3 en cours au plus par station (`quota`) ; `409 exists` si l'adresse est prise |
| `invite/take` | émetteur | `a` | rend `{box, e}` et l'**efface** (usage unique) ; note qui l'a prise (15 min) ; `404 unknown_invite` si absente, expirée, déjà lue ou si c'est la sienne ; 10 lectures par minute et par adresse IP (`429 rate`) |
| `pair` | émetteur | `req` (demande du § 2.4) | exige `req.from` = la station, `req.a` prise par elle depuis moins de 15 min, `req.to` = l'auteur de l'invitation (sinon `404 unknown_invite`) ; range la demande dans la boîte du receveur (type `pair`) et note les rôles de la liaison (receveur = qui a invité) ; une demande par invitation ; 20 liaisons au plus par station (`403 quota`) |
| `allow` | chacun | `peer` | autorise `peer` à déposer chez soi (le receveur après confirmation de l'empreinte, l'émetteur après le choix du profil) ; `403 not_linked` sans appairage ; deux fois = sans effet |
| `revoke` | chacun | `peer` | fin de liaison IMMÉDIATE dans les deux sens : liaison, autorisations et messages non relevés entre eux effacés ; reprendre = nouvel appairage |
| `put` | chacun | `msg` (enveloppe du § 5), `assist` (facultatif, vrai ou faux) | exige `msg.f` = la station ; `403 not_linked` sans liaison, `403 direction` si le type n'est pas permis dans ce sens, `403 not_allowed` si le destinataire n'a pas (ou plus) autorisé l'expéditeur ; quotas (§ 6) |
| `get` | chacun | `after` (dernier identifiant reçu, 0 au départ) | `{msgs: [{id, from, k, msg}], more}` : 512 ko et 200 messages au plus par réponse, dans l'ordre de dépôt ; `k` = `pair` pour une demande d'appairage (alors `msg` = la demande du § 2.4) |
| `ack` | chacun | `upto` | efface les messages de sa boîte jusqu'à `upto` |

## 5. Enveloppe d'une liaison établie

`{"f": émetteur du message, "to": destinataire, "k": type, "q": séquence, "b": base64url(nonce ‖ chiffré)}` ;
chiffré = XChaCha20-Poly1305(clé de liaison, nonce, zlib(JSON compact du contenu), aad = `"orx-monlink msg v1\0" ‖ f
‖ "\0" ‖ to ‖ "\0" ‖ k ‖ "\0" ‖ q` sur 8 octets gros-boutistes). 64 ko au plus (JSON de l'enveloppe), contenu
décompressé 1 Mo au plus (refus `too_large`), `q` de 1 à 2^53 − 1 par sens, fenêtre anti-rejeu de 2 048.

| Sens | Types |
|---|---|
| de l'émetteur (station surveillée) | `cf` confirmation et profil, `hb` battement, `st` état, `ev` événements, `lg` journaux, `sn` fragment d'instantané, `an` réponse à une demande, `end` fin |
| du receveur (station qui aide) | `rq` demande (assistance, instantané), `end` fin |

Instantané : fragments `sn` `{"id", "i", "n", "h", "d"}` de 32 ko bruts, 64 au plus (2 Mo), `h` = SHA-256 du tout.

## 6. Garde-fous du relais

Ceux de la présence (§ 7 de son protocole : PHP autonome sans WordPress, limite de débit par fichiers, IP jamais en
base, purge occasionnelle sans CRON, `503 pause`), plus : 2 Mo déposés par jour et par liaison, 10 Mo les jours où
l'émetteur a marqué un dépôt `"assist": true` (le relais ne peut pas le vérifier : c'est un plafond, pas un droit) ;
boîte de 5 Mo au plus par station ; message non relevé effacé après 7 jours ; invitation effacée à l'expiration.
Au-delà : `403 quota` ; l'émetteur garde sa file locale (24 h, 5 Mo, événements critiques jamais jetés).

## 7. Versions

`v1` dans les chemins et dans tous les domaines (`orx-monlink … v1`). Un changement incompatible = `v2` à côté.
