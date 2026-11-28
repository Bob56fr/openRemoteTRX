# Écran partagé de TRX Console : protocole (étape 403)

Un opérateur en difficulté (installation, réglage) montre sa **console texte** à un aidant, en **lecture seule**, par
le relais de rf-diy.com. Rien ne remonte de l'aidant vers la station : ni touche, ni commande. Code de la station :
`trxstation/screenshare/` ; code du relais : `src/ScreenApi.php` du dépôt privé `openRemoteTRX-relay` (routes
`/v1/screen/*`, même relais que la présence et le monitoring, `relay_url` de `[monitor_link]`, sinon
`https://relay.rf-diy.com`). La station fait foi.

Décisions de l'utilisateur (2026-11-26) : lecture seule ; pas de question de confidentialité entre opérateurs (tout ce
qui s'affiche est vu, mots de passe générés compris) ; partage depuis Debian / Raspberry Pi d'abord ; console web
laissée de côté (menu refusé, message) ; relais du VPS.

## 1. Déroulé

1. L'opérateur aidé ouvre le menu **6.7** (choix 1) ou tape `trx-console --partage`. La console tire un code de
   10 caractères, ouvre la session sur le relais, montre le code, puis se relance dans un pseudo-terminal
   (variable `TRX_SCREEN_SHARED=1` : ligne jaune dans l'en-tête, pas de partage imbriqué).
2. Il dicte le code à l'aidant (téléphone). L'aidant ouvre le menu 6.7 (choix 2) ou `trx-console --voir CODE`
   (Linux et Windows).
3. Tout ce que la console écrit est envoyé, chiffré, environ 3 fois par seconde ; l'aidant le voit dans son terminal.
4. **Ctrl+]** chez l'opérateur arrête le partage (la console continue) ; quitter la console arrête tout ; le relais
   refuse toute écriture 2 h après l'ouverture. Chez l'aidant : **Ctrl+]** ou Ctrl+C quitte, **Ctrl+R** redemande un
   écran complet.
5. Le titre de la fenêtre dit à l'opérateur si quelqu'un regarde (lecture depuis moins de 10 s), et à l'aidant si sa
   fenêtre est trop petite.

## 2. Code et clés

Code : 10 caractères de l'alphabet de Crockford (50 bits), mêmes règles que le code du monitoring
(`monlink.invite` : casse libre, espaces et tirets ignorés, O = 0, I et L = 1, affiché `ABCDE-FGHJK`).

`scrypt(code, sel "orx-screen v1", N = 2^15, r = 8, p = 1, 80 octets)` :

| octets | rôle |
|---|---|
| 0-15 | **adresse** de la session (32 caractères hexadécimaux), seule chose que le relais voit |
| 16-47 | **clé** des images (XChaCha20-Poly1305), jamais envoyée |
| 48-79 | **jeton d'écriture** ; le relais n'en garde que `SHA-256` (hexadécimal) ; seul l'opérateur l'envoie |

Retrouver le code depuis l'adresse demande 2^50 calculs scrypt. Le code ne sert qu'à une session.

## 3. Images

Clair = `zlib( genre (1 octet) ‖ colonnes (2, gros-boutiste) ‖ lignes (2) ‖ octets du terminal )`, 32 ko d'octets du
terminal au plus. Genre 1 = **suite** (octets à ajouter) ; genre 2 = **écran complet** (l'aidant repart de là).

Boîte = base64url sans remplissage de `nonce (24) ‖ XChaCha20-Poly1305(clé, nonce, clair, données associées)`,
données associées = `"orx-screen frame v1\0" ‖ adresse (ASCII) ‖ numéro d'image (8 octets, gros-boutiste)` : le relais
ne peut ni lire, ni changer l'ordre, ni rejouer une image. 64 ko au plus.

Écran complet : la station garde les octets écrits depuis le dernier effacement complet (`ESC[2J`, `ESC c`, entrée
dans l'écran secondaire), 64 ko au plus, et l'état de l'écran secondaire (`ESC[?1049h`). Elle l'envoie au départ,
après une coupure du relais, et quand l'aidant le demande ; elle fait alors aussi redessiner la console (taille du
pseudo-terminal changée d'une ligne puis remise : l'écran plein Textual se redessine en entier).

L'aidant n'applique rien avant un écran complet, et attend le suivant dès qu'il voit un trou dans les numéros.

## 4. Relais : routes `POST /v1/screen/<route>`

Corps JSON, 72 ko au plus, **non signé** (pas de station inscrite). Réponse JSON ; refus `{"error", "message", "now"}`.

| route | champs | effet et réponse |
|---|---|---|
| `open` | `a` (adresse), `h` (empreinte du jeton) | crée la session (2 h) : `{expires, resumed: false}` ; même `a` et même `h` : `{resumed: true}` ; autre `h` : `409 exists` ; session finie : `410 ended` ; 10 ouvertures par heure et par adresse IP (`429 rate`) ; 200 sessions ouvertes au plus (`503 busy`) |
| `put` | `a`, `w` (jeton, base64url de 32 octets), `s` (numéro > précédent), `d` (boîte) | range l'image ; `{watching, refresh, expires}` (`refresh` : l'aidant demande un écran complet, rendu une fois) ; `403 forbidden` (jeton), `404 unknown_session`, `410 ended`, `409 sequence` (`last`), `413 too_large`, `403 quota` (100 Mo par session) |
| `get` | `a`, `after` (dernier `id` reçu, 0 au départ), `refresh` (facultatif) | `{frames: [{id, s, d}], more, ended: false, expires, last_put}` (512 ko et 200 images au plus) ; session finie : `{frames: [], ended: true, reason: "closed" \| "expired"}` ; `404 unknown_session` |
| `close` | `a`, `w` | fin du partage, images effacées |

Garde-fous : 300 requêtes par minute et par adresse IP ; images gardées 10 min et 4 Mo par session (les plus
anciennes effacées) ; sessions effacées un jour après leur fin (purge quotidienne du VPS et purge au passage) ;
aucune adresse IP en base.

## 5. Limites connues

- Partager : Linux seulement (pseudo-terminal) ; Windows plus tard (pywinpty, comme la console web).
- La fenêtre de l'aidant doit être au moins aussi grande que celle de l'opérateur (titre de la fenêtre).
- Environ 1 s de retard (relevé toutes les 0,7 s, envoi toutes les 0,3 s) ; pas de flux continu (PHP-FPM).
- Le contenu affiché n'est pas filtré (décision : pas de confidentialité entre opérateurs).

Codes : ORT-7060 (relais injoignable ou en refus), ORT-7061 (aucun partage avec ce code).
