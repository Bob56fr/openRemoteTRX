# Protocole client <-> station (version 1)

Référence pour tout client de la passerelle : la page web (`gateway/api/static/client.js`) et l'application Android (`android/`, à venir). Source de vérité : le code de la station (`trxstation/gateway/api/protocol.py`, `session.py`, `server.py`, `webrtc.py`) ; ce document le décrit, les exemples partagés de [`tests/protocol/`](../tests/protocol/) le prouvent (`tests/test_protocol_contract.py`).

## 1. Principes (à respecter par tout client)

- **La station décide, le client affiche.** L'état RX/TX montré est TOUJOURS `state.ptt.state` reçu de la station, jamais un état supposé après un appui.
- **PTT en toggle uniquement** : un appui = une commande `toggle`. Aucun maintien appuyé.
- **Battements** pendant toute émission (§ 5). Sans eux, la station coupe d'elle-même.
- **Toujours RX après une reconnexion** : le client ne reprend jamais une émission tout seul.
- **Rien n'est vérifié par le client seul** : toute règle (bandes, modes d'émission, TOT, opérateur sur place, température) est appliquée par la station ; un client peut prévenir, jamais autoriser.
- **Tolérance** : un client ignore un champ, un type de message ou une fonction qu'il ne connaît pas.

## 2. Connexion

| Étape | Requête | Réponse |
|---|---|---|
| Paramètres | `GET /config` | `{"protocol": 1, "ice_servers": [...], "rig_audio": [...]}` (`rig_audio` : noms des cartes son du poste, à ne pas choisir comme micro ou sortie) |
| Vie | `GET /health` | `{"ok": true}` (n'expose aucun état) |
| Offre WebRTC | `POST /offer {"client_id", "password", "sdp", "type"}` | `{"sdp", "type"}` ; `400 bad_request`, `401 unauthorized` (même réponse quelle que soit la cause), `503 busy` (4 clients au plus), `500 server_error` |

- HTTPS obligatoire hors de la boucle locale (`docs/acces-distant.md`). Certificat auto-signé : le client l'**épingle** par son empreinte SHA-256, affichée par `trx-setup --empreinte` et TRX Console menu 19 (format `AB:CD:…`, 32 octets). Jamais de « faire confiance à tout ».
- Freinage des mots de passe faux : par origine (5/min) et par compte (30/15 min).
- Une offre acceptée qui ne se connecte pas en 20 s est abandonnée.

## 3. Transport WebRTC

- **Audio** : une piste dans chaque sens, Opus 48 kHz mono. Le client envoie toujours sa piste micro ; la station n'en fait passer le son au poste que pour le propriétaire de l'émission, porte ouverte (`state.audio.gate_open`). Traitement du micro : pas de contrôle automatique de gain ; annulation d'écho et réduction de bruit selon le réglage de l'utilisateur.
- **Canal `control`** (ouvert par le client, ordonné, fiable) : JSON, un objet par message, dans les deux sens.
- **Canal `spectrum`** (facultatif, ouvert par le client, `ordered: false`, `maxRetransmits: 0`) : balayages du spectre HF en binaire (§ 8).
- Limites : 2 048 octets par commande (sauf `layout_save` et `bug_report`, reconnus à leur début `{"cmd":"layout_save"` / `{"cmd":"bug_report"` : le client doit écrire `cmd` EN PREMIER), 64 ko au plus par message (aiortc), 30 messages/s par client (`error rate_limited` au-delà).

## 4. Versions et fonctions annoncées

- `PROTOCOL_VERSION` = 1, annoncée par `GET /config` et `hello.protocol`.
- **Ajout** (commande, champ, type de message, code, fonction) : la version NE change PAS ; les clients ignorent ce qu'ils ne connaissent pas.
- **Retrait ou changement de sens** : version + 1 ; la station accepte encore l'ancienne pendant au moins une version de l'application. Un client qui ne connaît pas la version annoncée le dit à l'utilisateur et reste en réception.
- **`hello.features`** : liste des fonctions offertes par CETTE station. Un client montre une fonction parce qu'elle y figure, jamais d'après un numéro de version.
  - toujours : `ptt`, `frequency`, `mode`, `squelch`, `functions`, `levels`, `local_release` ;
  - selon la station : `memories`, `layouts`, `spectrum` (second port CI-V actif), `beeps`, `bug_report`.
- `hello.version` : version du logiciel de la station (affichage seulement).

## 5. Émission : états, battements, coupures

`state.ptt.state` : `RX`, `KEYING` (prise en cours), `TX`, `UNKEYING` (coupure en cours). **KEYING, TX et UNKEYING s'affichent comme une émission.** `owner` = compte qui émet (`null` sinon).

- `toggle` : en RX, demande la prise d'émission (refus possibles § 7) ; dans tout autre état, coupe. Par son propriétaire : fin normale (avec le bip de fin si réglé) ; par un autre client : coupure immédiate.
- `stop` : coupure immédiate, jamais refusée, idempotente, par n'importe quel client.
- **Battements** : `{"cmd":"heartbeat"}` toutes les **400 ms**, dès l'envoi de `toggle` et tant que le client est propriétaire d'une émission. La station attend un battement toutes les 500 ms (`[safety] heartbeat_interval_ms`) et coupe après 2 s sans battement (`heartbeat_timeout_ms`). Aucune réponse n'est envoyée aux battements. Ils partent du composant qui possède la connexion (service Android), jamais d'un écran.
- **TOT** : `tot_remaining_s` (secondes restantes, `null` hors émission), `tot_warning` vrai 10 s avant la coupure.
- **Dernière coupure** `last_cut_reason` : `toggle`, `stop`, `tot`, `heartbeat`, `client_disconnected`, `cat_down`, `rig_silent`, `rig_overheat`, `frequency_changed`, `mode_changed`, `split_changed` (split mis ou ôté sur le poste pendant l'émission), `xit_changed` (ΔTX changé pendant l'émission), `rig_reported_rx`, `ptt_write_failed`, `rig_did_not_key`, `spectrum_port_keyed`, `startup`, `shutdown`.
- **`fault`** : `unkey_failed` = la station n'a pas pu confirmer le retour en réception ; émission refusée jusqu'à intervention sur la station. À afficher en alerte.
- **Opérateur sur place** : `local_remaining_s` (secondes pendant lesquelles le PTT à distance reste refusé, `null` = libre), `local_reason` (`tx`, `frequency`, `mode`), `local_tx` (émission au micro du poste EN COURS). `local_release` (« Reprendre la main ») n'est proposé que si `local_remaining_s` n'est pas `null` ET `local_tx` est faux.
- **Température** : `temp_alert` (`""`, `warn`, `hot` = émission refusée et coupée), `temp_c` (`null` si le poste ne la donne pas).

## 6. Commandes (client -> station)

Forme : `{"cmd": "<nom>", "id": <entier facultatif>, ...}`. `id` est le **numéro de la requête**, repris dans `result` ; l'identifiant d'une mémoire s'appelle `memory_id`. Toutes les commandes sauf `heartbeat` reçoivent un `result`.

| Commande | Paramètres | Effet, `result` en cas de succès |
|---|---|---|
| `toggle` | — | prise ou coupure (§ 5) ; `ptt` (instantané, § 9) |
| `stop` | — | coupure ; `ptt` |
| `heartbeat` | — | battement (aucune réponse) |
| `get_state` | — | `state` (même contenu que le message `state`) |
| `local_release` | — | reprendre la main (opérateur sur place) ; `ptt` |
| `set_frequency` | `hz` entier 1 à 10^10 | refusé hors RX confirmé (`tx_active`) |
| `set_mode` | `mode` (`[A-Za-z0-9-]{1,16}`), `passband` entier 0 à 20 000 (0 = largeur par défaut) | refusé hors RX confirmé |
| `set_squelch` | `value` nombre 0 à 1 | squelch du poste |
| `set_function` | `name` parmi `NR NB AIP COMP TUNER ANF MN RIT XIT`, `on` booléen | refusé pendant l'émission ; `XIT` = ΔTX (décale la fréquence d'ÉMISSION) |
| `set_offset` | `name` `RIT` ou `XIT`, `hz` entier (±99 999, resserré au « Max RIT/XIT » du poste : ±9 999 sur l'IC-7300MK2) | décalage du clarifieur ; refusé pendant l'émission ; sur l'IC-7300 le RIT et le ΔTX partagent le même décalage |
| `set_level` | `name`, `value` : `RFPOWER` parmi 0.05 0.1 0.25 0.5 0.8 1 ; `AGC` 0-6, `PREAMP` 0-30, `ATT` 0-60 (entiers) ; `NR` 0-1, `NB` 0-10 (nombres) | refusé pendant l'émission ; le squelch passe par `set_squelch` |
| `memory_save` | `name` (1 à 40 caractères imprimables), `hz`, `mode`, `favorite` booléen, `memory_id` facultatif (`[a-z0-9]{1,16}`, remplace) | `memory` ; message `memories` diffusé à TOUS les clients |
| `memory_delete` | `memory_id` | `ok` faux + `unknown_memory` si absente |
| `memory_recall` | `memory_id` | mode puis fréquence ; `memory` |
| `layout_get` | — | `profile`, `source`, `warnings` (mise en page de CE compte) |
| `layout_save` | `profile` objet (`docs/mises-en-page.md`) | `warnings` ; `layout_invalid` + `errors` si refusé |
| `layout_reset` | — | profil par défaut ; comme `layout_get` |
| `spectrum_set` | `name` parmi `mode`, `span`, `ref`, `speed`, `filter` ; `value` : texte (mode, speed), entier (span 1 à 10^6, filter 1 à 3), dB (ref, ±100) | `settings` relus ; refusé hors réception |
| `spectrum_watch` | `on` booléen | balayages envoyés à CE client seulement vue HF ouverte (`true` à l'ouverture, `false` à la fermeture) ; `on` |
| `beeps_set` | parmi `roger_enabled`, `link_lost_enabled` (booléens), `roger_tone` (`600` `800` `1000` `1500` `2000` `2500` `duo`), `roger_pattern` (1 à 3) | `settings` ; message `beeps` diffusé à tous |
| `bug_report` | `text` non vide, 30 000 caractères au plus, relu par l'utilisateur, sans mot de passe | `name` du fichier rangé sur la station |

## 7. Réponses et erreurs

- `{"type":"result","id":N,"ok":true, ...}` : succès, champs selon la commande.
- `{"type":"result","id":N,"ok":false,"reason":"…","detail":"…"}` : refus. `detail` est un texte pour l'humain, `reason` un code stable :
  - émission : `not_idle`, `unknown_client`, `fault_latched`, `starting`, `tx_disabled` (aucune bande autorisée), `cat_down`, `cat_error`, `local_active`, `local_tx`, `rig_hot`, `cooldown`, `ptt_unreadable`, `cancelled`, `rig_already_tx`, `mode_not_allowed`, `out_of_band` (vérifié sur la fréquence d'ÉMISSION : en split celle de l'autre VFO, décalée du ΔTX s'il est en service), `split_unreadable`, `xit_unreadable` (split ou ΔTX déclarés par le poste mais illisibles : en cas de doute, pas d'émission), `ptt_write_failed`, `rig_did_not_key` ;
  - réglages : `tx_active` (pas en RX confirmé), `invalid`, `rig_error`, `cat_down` ;
  - fonctions absentes ou en panne : `memories_unavailable`, `unknown_memory`, `storage_error`, `layouts_unavailable`, `layout_invalid`, `layout_storage_error`, `spectrum_unavailable`, `beeps_unavailable`, `beeps_storage_error`, `reports_unavailable` (et les motifs de refus d'un rapport).
- `{"type":"error","code":"…","detail":"…"}` : message illisible, sans `id` : `too_large`, `bad_json`, `bad_message`, `unknown_command`, `invalid_params`, `rate_limited`.

## 8. Messages (station -> client)

| Type | Quand | Contenu |
|---|---|---|
| `hello` | une fois, à l'ouverture du canal | `protocol`, `client_id`, `version`, `capabilities` (descripteur du poste : modes, filtres par mode, fonctions et niveaux lisibles, préamplis, atténuateurs, plages ; construit l'interface), `tx_modes` (modes où l'émission est permise, vide = tous), `max_power_w` (0 = inconnue : puissance en %), `memories`, `layouts` (booléen), `spectrum` (`{source, level_max, max_fps}` ou `null`), `beeps` (réglages ou `null`), `features` |
| `state` | aussitôt après `hello`, puis toutes les 250 ms s'il a changé, au moins chaque seconde | `ptt` (§ 5), `rig` (`connected`, `frequency_hz`, `mode`, `passband_hz`, `strength_db`, `functions` (dont `RIT`, `XIT`), `levels`, `split` (booléen, `null` = inconnu), `tx_frequency_hz` (fréquence d'émission en split, sinon `null`), `offsets` (`RIT`, `XIT` : décalages en Hz)) ; le VFO actif (A, B, mémoire) n'est PAS publié : l'IC-7300MK2 ne le donne pas (`get_vfo` : RPRT -11), `audio` (niveaux et compteurs, diagnostic), `clients` (comptes connectés), `spectrum` (`state` : `waiting`, `starting`, `ok`, `error` ; `code`, `message`, `settings`) |
| `result`, `error` | réponse à une commande | § 7 |
| `memories` | une mémoire change (n'importe quel client) | `items` : `{id, name, hz, mode, favorite}` |
| `beeps` | réglage des bips changé | `settings` |
| `module` | message d'un module (cluster DX…) | `module`, `data` (format propre au module : `docs/cluster-dx.md`) ; spots (`kind` « spots » : bande du poste ; « recent » : 30 derniers toutes bandes, depuis 0.56.0) seulement vue HF ouverte |

Les champs `functions` et `levels` de `state.rig` sont des tables ouvertes (selon le poste) ; ne compter que sur ce qu'annonce `hello.capabilities`.

**Balayages du spectre** (canal `spectrum`, binaire, petit-boutiste) : en-tête de 16 octets `version(1) mode flags réservé | numéro uint32 | bord gauche Hz uint32 | bord droit Hz uint32`, puis un octet par point de 0 à `level_max`. Un numéro plus ancien que le dernier reçu est jeté (compteur remis à zéro à chaque connexion : la station peut avoir redémarré). Détail : `trxstation/spectrum/frame.py` ; exemples partagés : [`tests/protocol/spectrum.json`](../tests/protocol/spectrum.json) (pytest `test_spectrum_frames_match_the_shared_examples`, Kotlin `SpectrumTest`).

## 9. Instantané `ptt` des réponses

`result.ptt` (réponse à `toggle`, `stop`, `local_release`) contient les champs de `state.ptt` plus `event` (dernier évènement : `tot_warning`, `fault`, `fault_cleared`, `local_active`, `local_released`, `temp_alert`… ; indicatif). Le client affiche ensuite le `state` suivant : c'est lui qui fait foi.

## 10. Reconnexion (comportement attendu d'un client)

Premier essai après 400 ms, puis 1,5 s, 3 s, 4,5 s au plus entre deux essais, pendant une fenêtre réglable (300 s au plus) ; un canal qui ne s'ouvre pas en 6 s est abandonné pour réessayer. Identifiants refusés (`401`) : arrêt immédiat. Après reconnexion : réception, l'utilisateur doit réarmer. Sons de la page : `lost` (perte), `restored` (rétablie, en réception), `failed` (abandon).

## 11. Modifier le protocole (règle des livraisons)

Toute livraison qui ajoute ou change une commande, un champ ou un message :
1. met à jour `protocol.py` / `session.py` ET ce document ;
2. ajoute ou corrige les exemples de `tests/protocol/` (le test échoue sinon) ;
3. ajoute un mot à `hello.features` si c'est une fonction qu'une station peut ne pas offrir ;
4. note dans la matrice de parité page / application ce qui reste à faire de chaque côté (`docs/android-cahier-des-charges.md` § 8).

## 12. QR code d'appairage

Affiché par TRX Console (menu 19) et `trx-setup --empreinte` ; lu par l'application (« Scanner le QR code de la station »). Il évite de taper l'empreinte. Il ne contient **JAMAIS de mot de passe** (la station ne les connaît pas en clair).

```
openremotetrx://pair?v=1&n=<nom>&u=<adresse>&id=<identifiant>&fp=<empreinte>
```

| Paramètre | Contenu |
|---|---|
| `v` | version du format : `1` (obligatoire ; une autre valeur est refusée) |
| `n` | nom proposé pour la station (nom de la machine) ; facultatif (défaut : l'hôte) |
| `u` | adresse `https://hôte:port` (obligatoire, HTTPS seulement) |
| `id` | identifiant du compte (`[A-Za-z0-9_-]`, 32 au plus) ; absent = à saisir dans l'application |
| `fp` | empreinte SHA-256 du certificat, 64 chiffres hexadécimaux sans séparateur ; absente = certificat reconnu (proxy) |

Valeurs encodées en pourcentage (UTF-8). Un paramètre inconnu est ignoré ; un mot de passe éventuel n'est jamais lu. Le QR est dessiné en caractères pour un terminal sombre (modules clairs = blocs pleins) ; l'application lit aussi les QR inversés. Exemples partagés : [`tests/protocol/pairing.json`](../tests/protocol/pairing.json) (pytest `tests/test_pairing_qr.py`, Kotlin `PairingTest`).
