# Présence de groupe — protocole station ↔ relais (v1)

Contrat entre le module de présence de la station (`trxstation/presence/`, ce dépôt) et le relais (PHP 8.2 +
`sodium`, **autre dépôt**). Cahier des charges : `docs/presence-cahier-des-charges.md`. Vecteurs communs, à reprendre
tels quels dans le dépôt du relais : `tests/protocol/presence_vectors.json` (refabriqués par
`python -m trxstation.presence.vectors`, jamais à la main).

Le relais est une boîte aux lettres : il **authentifie les stations, range des blocs chiffrés et les redistribue**.
Il ne déchiffre rien, ne connaît ni fréquences, ni modes, ni textes, ni statuts, et ne garde aucune adresse IP en base.
Les pages web et l'application ne lui parlent jamais : seules les stations le font.

## 1. Encodages

| Élément | Forme |
|---|---|
| Binaire dans du JSON | base64url **sans** `=`, forme canonique (refuser toute autre écriture) |
| Identifiant de station | `hex(SHA-256("orx-presence id v1\0" ‖ ed_pub)[0:16])`, 32 caractères `[0-9a-f]` |
| Identifiant de groupe | 32 caractères `[0-9a-f]`, tiré au hasard par l'administrateur |
| Heures | secondes Unix entières |
| JSON signé | compact, clés triées, ASCII seul ; **les octets signés sont transmis tels quels** : on vérifie sur les octets reçus, on ne refabrique jamais un JSON pour vérifier |
| Pseudo | 1 à 16 caractères : lettres sans accent, chiffres, espace, `.` `/` `_` `-` ; commence et finit par autre chose qu'une espace ; espaces multiples réduites à une (vecteurs `pseudo`) |

En PHP : `sodium_bin2base64($b, SODIUM_BASE64_VARIANT_URLSAFE_NO_PADDING)`, `sodium_crypto_sign_verify_detached`,
`hash('sha256', …, true)`.

## 2. Clés de la station

Ed25519 (signer) et X25519 (recevoir une clé de groupe), créées par la station, privées restées sur la station. Le
relais ne connaît que les clés publiques et l'identifiant qui en dérive : il **refuse** un identifiant qui n'est pas
l'empreinte de la clé Ed25519 présentée.

## 3. Requêtes

Toutes en `POST`, corps JSON (16 ko au plus), réponse JSON. En-têtes :

| En-tête | Contenu |
|---|---|
| `X-Orx-Station` | identifiant de la station |
| `X-Orx-Signature` | signature Ed25519 (base64url) de `"orx-relay v1\n" ‖ "POST" ‖ "\n" ‖ chemin ‖ "\n" ‖ corps` |

Le corps contient toujours `t` (heure de la station) et `n` (compteur strictement croissant par station :
millisecondes Unix, ou le précédent + 1). Le relais refuse si : corps trop grand (`too_large`), signature fausse
(`bad_signature`), `t` à plus de 600 s de son heure (`clock`, la réponse donne `now` pour que la station prévienne
l'opérateur), `n` ≤ dernier `n` accepté (`replay`). **Ordre des contrôles** (rejeter tôt, avant toute base) : taille,
limite de débit (adresse IP en mémoire de courte durée, jamais écrite en base ; puis identifiant), forme des
en-têtes, lecture de la clé de la station (une seule requête en base), signature, horloge, compteur.

Réponse d'erreur : code HTTP + `{"error": motif, "message": texte, "now": heure}`.

| Code | Motifs |
|---|---|
| 400 | `malformed`, `too_large` |
| 401 | `bad_signature`, `unknown_station`, `clock`, `replay` |
| 403 | `pow`, `not_admin`, `not_member`, `quota` |
| 404 | `unknown_group` |
| 409 | `exists`, `stale_roster` |
| 429 | `rate` (avec `retry_in` en secondes) |
| 503 | `pause` (avec `retry_in`) : relais surchargé ou en maintenance ; la station réessaie sans alerter |

## 4. Points d'entrée

### 4.1 `/v1/register`

`{"ed", "x", "pseudo", "pow", "version", "t", "n"}`. Le relais vérifie : `X-Orx-Station` = empreinte de `ed`,
signature avec `ed`, pseudo, preuve de travail `pow` (§ 5) pour sa difficulté courante, identifiant non déjà connu
(`exists`), quota d'enregistrements par adresse IP. Réponse `{"ok": true, "now", "bits"}`. Sans `pow` valable :
403 `pow` avec `bits` demandé.

### 4.2 `/v1/profile`

`{"pseudo", "version", "t", "n"}` : nouveau pseudo et version du module.

### 4.3 `/v1/unregister`

`{"t", "n"}` : la station et tout ce qui la concerne sont effacés (états, adhésions en attente, clés remises ; elle
reste dans les listes signées jusqu'à ce qu'un administrateur en publie une nouvelle, mais ses états ne sont plus
distribués).

### 4.4 `/v1/group/create`

`{"g", "roster", "t", "n"}` : `roster` = 1re liste signée (§ 6), `by` = la station qui envoie, seule administratrice.
Refus : `exists`, `quota` (5 groupes créés par station).

### 4.5 `/v1/group/join`

La demande d'adhésion de `trxstation/presence/invite.py` : `{"g", "i", "id", "ed", "x", "pseudo", "proof", "t", "n"}`,
`id` = la station qui envoie. Rangée **en attente** pour les administrateurs du groupe ; une seule demande en attente
par station et par groupe. Le relais ne peut pas vérifier `proof` (il n'a pas la clé du groupe) : la station de
l'administrateur le fait. Refus : `unknown_group`, `quota` (20 groupes par station, 50 membres et demandes par groupe).

### 4.6 `/v1/group/roster`

`{"g", "roster", "keys": [clés remises], "reject": [identifiants], "t", "n"}` : nouvelle liste signée par un
administrateur ou co-administrateur de la liste courante (le relais **vérifie les mêmes règles que les stations**
quand il le peut : version + 1, chaînage, signataire et signature ; `stale_roster` si la version n'est pas la suivante).
Les demandes en attente des nouveaux membres, et celles de `reject`, sont retirées. `keys` remplace les clés remises
de chaque membre nommé (`for`). Un membre retiré de la liste ne reçoit plus rien.

### 4.7 `/v1/group/leave` et `/v1/group/delete`

`leave` `{"g", "t", "n"}` : la station quitte le groupe (plus d'états reçus ni distribués ; signalé aux
administrateurs, qui publient une liste sans elle et une nouvelle clé). `delete` `{"g", "t", "n"}` : réservé à un
administrateur de la liste courante ; tout le groupe est effacé.

### 4.8 `/v1/sync` (la requête périodique)

```json
{"states": [{"g": "…", "kv": 3, "blob": "…"}],
 "known": {"<groupe>": 7},
 "since": 1794000000,
 "t": 1794000005, "n": 1794000005123}
```

- `states` : un bloc de 256 octets (342 caractères base64url) par groupe de la station ; le relais remplace le
  précédent et note l'heure de réception. Refus du seul bloc (pas de la requête) si la station n'est pas membre ou si
  la taille n'est pas exacte.
- `known` : version de liste connue par groupe ; `since` : le `now` de la réponse précédente (0 au départ).

Réponse :

```json
{"now": 1794000006, "next_in": 90,
 "groups": [{"g": "…",
             "roster": {"p": "…", "by": "…", "s": "…"},
             "key": {"g": "…", "kv": 3, "for": "…", "box": "…", "by": "…", "s": "…"},
             "members": [{"id": "…", "pseudo": "F4ABC", "age": 42, "kv": 3, "blob": "…"},
                         {"id": "…", "pseudo": "F5XYZ", "age": 4000}],
             "pending": [{"g": "…", "i": "…", "id": "…", "ed": "…", "x": "…", "pseudo": "…", "proof": "…"}],
             "left": ["…"],
             "admin": [{"id": "…", "joined": 1793000000, "version": "0.117.0", "flag": "errors"}]}]}
```

- `roster` seulement si la version du relais dépasse `known` ; `key` seulement si la clé remise à cette station a
  changé.
- `members` : TOUS les autres membres avec `age` = secondes depuis leur dernier `/v1/sync` (hors ligne au-delà de
  240 s, calculé par la station qui lit) ; `blob` et `kv` seulement si le bloc a été reçu après `since`.
- `pending`, `left`, `admin` : seulement pour les administrateurs et co-administrateurs. `admin` = ce que le relais
  sait (date d'adhésion, version du module, `flag` : `errors` pour des refus répétés, `rate` pour un débit anormal) ;
  aucun historique d'activité.
- `next_in` : délai avant la prochaine requête, **le même pour toutes les stations** (90 s par défaut) ; le relais
  l'allonge s'il est chargé. Une station qui revient avant la moitié de `next_in` reçoit 429 `rate`.

## 5. Preuve de travail

Valide si `SHA-256("orx-presence pow v1\0" ‖ identifiant ‖ "\0" ‖ décimal(pow))` commence par au moins `bits` bits
nuls (`pow` entier de 0 à 2^53 − 1). Difficulté choisie par le relais (20 par défaut, quelques secondes sur un Pi 4) ;
la vérifier coûte un seul calcul. Vecteurs : `pow`.

## 6. Liste des membres, clés remises, états

Formats exacts dans les en-têtes de `roster.py`, `invite.py` et `state.py`, et dans les vecteurs `roster`,
`key_box`, `state`. Ce que le relais peut en faire :

| Objet | Le relais lit | Le relais vérifie |
|---|---|---|
| Liste signée `{"p","by","s"}` | `p` (JSON en clair : groupe, version, membres, rôles, clés publiques) | signature de `by` sur `"orx-presence roster v1\0" ‖ p`, `by` administrateur ou co-administrateur de la version précédente, version + 1, `prev` = SHA-256 de la version précédente |
| Clé remise | `g`, `kv`, `for`, `by` | rien d'autre (scellée pour `for`) |
| État | sa taille (256 octets) | rien (chiffré) |
| Demande d'adhésion | `g`, `id`, `ed`, `x`, `pseudo` | `id` = empreinte de `ed`, pseudo |

Les stations, elles, vérifient tout de nouveau et ne font jamais confiance au relais : liste signée par un
administrateur connu, clés d'un membre figées, clé de groupe remise signée par un administrateur de la liste signée,
état signé par la station dont il porte l'identifiant, compteur croissant.

## 7. Garde-fous du relais (hébergement mutualisé OVH, sans CRON)

- Script PHP autonome sur un sous-domaine, sans charger WordPress ; le back-office est un plugin WordPress qui lit
  les mêmes tables (pseudo, identifiant, dates, groupes ; rien d'autre).
- Limite de débit par fichiers (pas d'APCu ni de Redis supposés) ; adresse IP seulement en mémoire de courte durée.
- Expiration calculée à la lecture ; purge occasionnelle lors d'une écriture : stations sans requête depuis 12 mois,
  demandes d'adhésion de plus de 7 jours.
- Quotas : 5 groupes créés et 20 rejoints par station, 50 membres par groupe, 16 ko par requête.
- `next_in` et 503 `pause` : frein général sans toucher aux stations.

## 8. Versions

`v1` dans les chemins et les domaines de signature. Un changement incompatible = `v2` à côté de `v1` pendant la
transition ; les vecteurs portent la version.
