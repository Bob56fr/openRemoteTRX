# Breizh Audio Box dans la chaîne d'émission : cahier des charges v1

- v0 du 2026-11-04 : demande et décisions de l'utilisateur (§ 1 à 3, inchangés).
- v1 du 2026-11-04 : protocole UDP + HMAC, réglages, protocole client, tests de panne, lots (§ 4 à 13). **VALIDÉE
  par l'utilisateur le 2026-11-04** (les 8 points du § 13 acceptés) : le protocole du § 5 est FIGÉ.

EXCEPTION de l'utilisateur au gel de la page et de l'application (2026-11-04).

## 1. Demande

Le son du micro du client (page, application) passe par Breizh Audio Box (traitement de la voix) avant d'aller au
poste. Les deux logiciels tournent sur le MÊME RÉSEAU LOCAL, pas forcément sur le même PC. Si Breizh disparaît,
remoteTRX annule le routage et repasse en mode autonome.

## 2. Principe retenu

```
client (micro) → Opus → passerelle : décodage → [Breizh par le réseau local] → volume retour → limiteur final → porte audio d'émission → poste
```

- Son brut 48 kHz mono par UDP, blocs de 256 échantillons numérotés (~1,5 Mbit/s). Breizh renvoie UN bloc par bloc
  reçu, sans carte son de son côté (pas de dérive d'horloge entre les deux PC). Latence ajoutée visée : 10 à 20 ms.
  (v1 : 480 échantillons proposés à la place de 256, voir § 4.2.)
- Côté openRemoteTRX : client du protocole dans la passerelle ; un FAUX BREIZH (renvoi tel quel ou gain) pour les
  tests. Côté Breizh : serveur du protocole (son lot V2), conversation à part dans son dépôt.
- Le protocole réseau est figé et documenté ICI avant le codage des deux côtés.

## 3. Décisions de l'utilisateur (2026-11-04)

1. **Sécurité du flux** : appairage par clé partagée, chaque bloc authentifié (HMAC), un seul hôte Breizh autorisé
   (déclaré dans `station.toml`), seule la réponse à un bloc réellement envoyé est acceptée. Le micro circule en clair
   sur le réseau local : à dire dans la notice.
2. **Breizh ne touche jamais au PTT ni à la porte d'émission** : la porte audio d'émission est APRÈS le retour de
   Breizh ; limiteur final de la station toujours actif. Côté Breizh : onglet « OpenRemoteTRX » dans les réglages
   (paramètres d'appairage, activation du mode) ; ce mode activé COUPE le CAT de Breizh et GRISE son onglet CAT
   (Breizh ne peut alors plus faire passer le poste en émission).
3. **Roger bip** : reste à remoteTRX (exception des bips de fin, `docs/bips.md`).
4. **Breizh disparu (plus de retour pendant ~100 ms)** : option A, repli IMMÉDIAT en direct à gain réduit, opérateur
   prévenu, mode autonome conservé. Pas de réactivation automatique hâtive : attente suffisamment longue, OU
   réactivation demandée par l'utilisateur depuis la page et l'application. Un JOURNAL de connexion / reconnexion
   dans l'onglet dédié (page, application).
5. **Effets du client coupés** quand Breizh est actif (annoncé par `hello`) : égaliseur, chorus, réverbération en
   bypass ; le limiteur du client reste.
6. **Scrambler d'émission et Breizh EXCLUSIFS** (le scrambler brouille dans le client, avant Breizh).
7. **Volume retour** : réglage borné (−20 à +6 dB) appliqué à la station après Breizh, réglable depuis la page et
   l'application.
8. **Exception au gel** de la page et de l'application : accordée.

---

## 4. Chaîne audio côté station (v1)

### 4.1 Ce qui existe aujourd'hui (constaté dans le code, 0.98.0)

- `webrtc.receive_tx_audio` : Opus décodé, rééchantillonné en s16 mono 48 kHz, recoupé en trames de **20 ms (960
  échantillons)** par `FrameAssembler`, puis `TxAudioGate.push(client_id, pcm)`.
- `TxAudioGate` : jette tout si fermée ou si le client n'est pas le propriétaire ; gain `[audio] tx_gain_db` ; écrit
  dans `TapSink` (poste + copie pour les visiteurs). Le `PttController` ferme la porte AVANT « PTT off » (flush).
- `SoundDeviceSink` : tampon de 60 ms contre la gigue, 200 ms au plus (au-delà le plus ancien est jeté).
- **Il n'y a PAS de limiteur à la station** aujourd'hui : seul le client limite (`voice.js`, `VoiceDsp`). Le « limiteur
  final toujours actif » de la décision 2 est donc à CRÉER (lot 2).

### 4.2 Chaîne v1

```
trame 20 ms du propriétaire
  │  porte d'ENTRÉE : porte ouverte ET client propriétaire ? sinon jetée (rien ne part vers Breizh hors émission)
  ▼
route de l'émission (fixée à la prise) ──── direct ───────────────────────────────┐
  │ breizh                                                                         │
  ▼                                                                                │
découpe en 2 blocs de 480 → UDP vers Breizh → retour du bloc n (HMAC, attendu)     │
  │   bloc n absent après block_timeout_ms → bloc n « sec » à fallback_gain_db     │
  │   aucun retour valable pendant lost_ms → REPLI : route = direct jusqu'à la fin  │
  ▼                                                                                │
volume retour (return_gain_db, −20 à +6 dB)                                        │
  ▼                                                                                ▼
limiteur final de la station (crête −1 dBFS, TOUJOURS, les deux routes) ◄──────────┘
  ▼
porte audio d'émission (TxAudioGate, inchangée : ouverte + propriétaire + même « époque ») → poste + visiteurs
```

- **Taille de bloc : 480 échantillons (10 ms)** (v0 : 256 ; décision du § 13). Raisons : la passerelle reçoit le son par
  trames de 20 ms déjà complètes, découper plus fin n'ôte AUCUNE latence ; 960 n'est pas un multiple de 256 (blocs à
  cheval sur deux trames, reste à garder) ; 480 × 2 octets = 960 octets tient dans un paquet sans fragmentation
  (MTU 1 500) ; 100 paquets/s par sens au lieu de 188. Débit : ~0,8 Mbit/s par sens.
- **Époque de la porte** : la porte prend un numéro à chaque ouverture / fermeture. Un bloc revenu de Breizh porte
  l'époque de son départ ; une époque périmée = bloc jeté. Ainsi **aucun son revenu de Breizh après une coupure**
  (stop, TOT, battements, déconnexion, superviseur) n'atteint le poste. Conséquence acceptée : à la fin normale, les
  10 à 30 derniers ms de voix encore chez Breizh sont perdus.
- **Route fixée à la prise d'émission** : `breizh` si la liaison est prête (§ 5.6), sinon `direct`. Pendant une
  émission, seul le passage breizh → direct (repli) est possible, jamais l'inverse (pas de saut de son en cours de
  phrase).
- **Bloc en retard** (`block_timeout_ms`, défaut 40 ms) : le bloc d'origine part « sec » à `fallback_gain_db` à sa
  place, l'ordre est gardé ; s'il arrive ensuite, il est jeté (compté `late`). Le repli entier n'a lieu qu'après
  `lost_ms` (décision 4 : 100 ms) sans AUCUN retour valable.
- **Bips de fin, SELCALL, TOS, rediffusion** : ne passent PAS par Breizh (inchangé : `TailPlayer` écrit directement
  dans le puits). Les visiteurs entendent le son traité (copie prise après la porte, comme aujourd'hui).
- **Ce que Breizh ne peut pas faire, par construction** : aucune commande du protocole ne touche au PTT, au CAT, à la
  porte ni au TOT ; un paquet de Breizh ne peut que fournir le contenu d'un bloc DEMANDÉ. Le module `breizh/` n'importe
  ni `safety/` ni le CAT (vérifié par un test, § 9).

## 5. Protocole UDP station ⇄ Breizh (version 1, FIGÉ après validation)

### 5.1 Rôles et transport

- **Station = client** (envoie le son, prend l'initiative), **Breizh = serveur** : écoute UDP sur `port` (défaut
  **47100**) de l'adresse déclarée dans `[breizh] host`.
- La station envoie depuis UN socket ; elle n'accepte que les paquets venant exactement de `host:port`. Breizh
  n'accepte que l'adresse de station déclarée dans son onglet et répond à l'adresse source du paquet.
- Pare-feu : à ouvrir côté PC Breizh (UDP entrant `port`) ; côté station rien (UDP sortant, retour suivi).
- Ordre des octets : réseau (gros-boutiste). Son : PCM s16 **petit-boutiste** (comme un WAV), mono, 48 000 Hz.

### 5.2 En-tête commun (28 octets) et étiquette

| Décalage | Taille | Champ | Contenu |
|---|---|---|---|
| 0 | 4 | `magic` | `ORTB` (ASCII) |
| 4 | 1 | `version` | 1 |
| 5 | 1 | `type` | § 5.3 |
| 6 | 2 | `flags` | bit 0 `START` (premier bloc d'une émission : remettre à zéro l'état du traitement), bit 1 `GAP` (blocs manquants avant celui-ci), autres = 0 |
| 8 | 8 | `session` | numéro de session tiré au hasard par la station (§ 5.4) |
| 16 | 4 | `seq` | compteur de paquets de l'ÉMETTEUR, strictement croissant dans la session, par sens |
| 20 | 4 | `ref` | AUDIO / AUDIO_RET : numéro de bloc ; PONG : `seq` du PING ; sinon 0 |
| 24 | 2 | `len` | taille de la charge utile |
| 26 | 2 | `reserved` | 0 |
| 28 | `len` | charge utile | § 5.3 |
| 28+`len` | 16 | `tag` | HMAC-SHA256(clé, octets 0 à 28+`len`−1), 16 premiers octets |

Clé de `tag` : **clé d'appairage** pour HELLO, HELLO_ACK et ERROR ; **clé de session** (§ 5.4) pour tous les autres.
Un paquet trop court, de `magic`/`version` inconnus, de `len` incohérente ou d'étiquette fausse est **jeté sans
réponse** (pas d'oracle, pas d'amplification), compté, signalé au journal une fois par minute au plus.

### 5.3 Messages

| Type | Nom | Sens | Charge utile |
|---|---|---|---|
| 1 | HELLO | S → B | JSON UTF-8 : `{"proto":1,"rate":48000,"block":480,"format":"s16le","station":"0.99.0","nonce":"<16 octets base64>"}` |
| 2 | HELLO_ACK | B → S | JSON : `{"proto":1,"nonce":"<16 octets base64>","breizh":"<version>","cat_off":true,"latency_ms":<traitement annoncé>}` |
| 3 | AUDIO | S → B | 480 échantillons s16le (960 octets) |
| 4 | AUDIO_RET | B → S | 480 échantillons s16le, `ref` = numéro du bloc traité |
| 5 | PING | S → B | vide |
| 6 | PONG | B → S | vide, `ref` = `seq` du PING |
| 7 | BYE | S ⇄ B | JSON : `{"reason":"<code>"}` (`mode_off`, `shutdown`, `disabled`) |
| 8 | ERROR | B → S | JSON : `{"code":"<code>"}` : `proto` (version), `format` (taux, bloc), `mode_off` (mode OpenRemoteTRX non activé), `busy` (une autre station) |

Champs JSON inconnus : ignorés (ajout possible sans changer `proto`). Changement de sens : `proto` + 1, la station
refuse la liaison (journal « version de Breizh incompatible »).

### 5.4 Appairage, session, rejeu

- **Clé d'appairage** : 32 octets aléatoires, montrés en base64url (43 caractères) par TRX Console, saisis (ou collés)
  dans l'onglet « OpenRemoteTRX » de Breizh avec l'adresse et le port de la station.
- **Ouverture** : la station tire `session` (64 bits) et `nonce_s` (16 octets), envoie HELLO toutes les 2 s jusqu'à un
  HELLO_ACK valable (même `session`, étiquette juste, `cat_off` vrai, `proto` 1, `latency_ms` ≤ 50).
- **Clé de session** = HMAC-SHA256(clé d'appairage, `"ORTB1 session"` ‖ `session` (8 octets) ‖ `nonce_s` ‖ `nonce_b`).
  Un paquet d'une ancienne session ne passe donc jamais.
- **HELLO répété** (précision du 2026-11-04, lot 2, sans changement de format) : la station renvoie le MÊME HELLO (même
  `session`, même `nonce_s`) toutes les 2 s tant qu'elle n'a pas de réponse. Breizh répond à un HELLO de la session
  qu'il sert déjà par le MÊME HELLO_ACK (même `nonce_b`, idéalement les mêmes octets), sans changer sa clé de session ;
  un nouveau `session` = une nouvelle session. La station ignore un HELLO_ACK de sa session une fois celle-ci ouverte.
- **Rejeu** : chaque côté jette un paquet dont `seq` n'est pas STRICTEMENT supérieur au dernier accepté (un paquet
  désordonné est perdu : acceptable sur un réseau local). La station n'accepte un AUDIO_RET que si `ref` est un bloc
  ENVOYÉ, pas encore répondu, pas expiré ; chaque bloc n'est accepté qu'UNE fois.
- **HELLO_ACK sans `cat_off: true`** : liaison REFUSÉE (journal « Breizh n'a pas coupé son CAT »). C'est une
  déclaration de Breizh, pas une preuve : la vraie garantie reste que Breizh n'a aucun moyen d'agir sur le PTT de la
  station.
- **Ce que le protocole ne protège pas** (à écrire dans la notice) : le son du micro circule EN CLAIR sur le réseau
  local (décision 1) ; un appareil du réseau local peut empêcher la liaison (paquets en masse, HELLO rejoué) : la
  conséquence est au pire un repli en direct, jamais une émission.

### 5.5 Flux audio

- AUDIO seulement pendant une émission routée vers Breizh, porte ouverte, client propriétaire. `ref` = numéro de bloc
  croissant de la session ; `START` sur le premier bloc de chaque émission ; `GAP` si des blocs ont manqué.
- Breizh répond à CHAQUE AUDIO par UN AUDIO_RET de même `ref` et même taille, sans attendre d'autres blocs (pas de
  tampon interne plus long que sa `latency_ms` annoncée), et n'envoie JAMAIS d'AUDIO_RET spontané. Un bloc qu'il ne
  peut pas traiter : il le renvoie tel quel (jamais du silence inventé).

### 5.6 Battement et états de la liaison

- Hors émission : PING toutes les 1 s ; liaison perdue après 3 s sans PONG.
- En émission routée : les AUDIO_RET valent battement ; liaison perdue après `lost_ms` (100 ms) sans retour valable.
- États publiés (`state.breizh.state`) :

| État | Sens | Route de la prochaine émission |
|---|---|---|
| `off` | `[breizh] enabled = false` | direct |
| `connecting` | HELLO en cours, jamais joint depuis le démarrage | direct |
| `ready` | session ouverte, PONG reçus | breizh |
| `active` | émission en cours par Breizh | (breizh) |
| `fallback` | Breizh perdu ; repli en direct à gain réduit ; cherche à revenir | direct |
| `refused` | clé, version, format ou CAT refusés : rien ne se retente seul avant 60 s | direct |

- **Réactivation** (décision 4) : depuis `fallback`, nouvelle session dès que Breizh répond, mais l'état reste
  `fallback` jusqu'à `reactivate_after_s` (défaut **60 s**) de PONG sans faute, OU jusqu'à la commande
  `breizh_reactivate`. Jamais pendant une émission : la réactivation prend effet à la prochaine prise.

## 6. Réglages

### 6.1 `station.toml`, section `[breizh]` (station seulement)

| Clé | Défaut | Bornes | Rôle |
|---|---|---|---|
| `enabled` | `false` | | fonction disponible |
| `host` | `""` | adresse IP **privée** (RFC 1918, fd00::/8, lien local, 127.0.0.1) | PC de Breizh ; une adresse publique est REFUSÉE (micro en clair) ; un nom d'hôte est refusé (pas de DNS dans le chemin du son) |
| `port` | `47100` | 1024-65535 | port UDP de Breizh |
| `key_file` | `""` = `breizh.key` à côté de station.toml | | fichier de la clé d'appairage (base64url, 32 octets) ; 0600 sous Linux, ACL sous Windows ; refusé si lisible par tous |
| `block_timeout_ms` | 40 | 15-100 | délai d'un bloc avant son remplacement « sec » |
| `lost_ms` | 100 | 50-500, > `block_timeout_ms` | sans retour valable : repli en direct |
| `fallback_gain_db` | −6 | −20 à 0 | gain du son direct en repli (décision 4 « gain réduit ») |
| `reactivate_after_s` | 60 | 0 (jamais seul) ou 30-3600 | stabilité exigée avant le retour automatique |

- La clé n'est PAS dans station.toml (fichier versionné, recopié dans les rapports et profils) : fichier à part
  (§ 13). `enabled` sans `host` ou sans clé lisible = erreur de configuration bloquante.
- `[breizh]` n'est ni `[rig]` ni `[audio]` ni `[spectrum]` : pas de changement de `PROFILE_FORMAT`.
- Notice de station.toml (`docs/station-toml/contenu.toml`) : à écrire au lot 1.

### 6.2 Réglages de l'opérateur (`state_dir/breizh.json`, pas station.toml)

- `return_gain_db` (défaut 0, bornes fixes −20 à +6 dB, pas de 0,5) : volume retour (décision 7).
- `bypass` (défaut `false`) : « Direct » choisi par l'opérateur (§ 13 point 8) ; gardé après un redémarrage.
- Journal : `state_dir/breizh-log.jsonl`, 200 dernières lignes.

## 7. Protocole client (à reporter dans `docs/protocole.md`, `tests/protocol/`, `docs/parite-web-android.md`)

- **`hello.features`** : `breizh` si `[breizh] enabled` ; jamais annoncé à un visiteur.
- **`state.breizh`** (opérateurs seulement, absent sinon) :
  `{"state":"ready","route":"breizh","bypass":false,"return_gain_db":0.0,"rtt_ms":3,"late":0,"lost":0,"peer":"Breizh 2.1.0","reactivate_in_s":null}`
  - `route` : route de l'émission EN COURS, sinon de la prochaine (`direct` si `bypass`, quel que soit `state`). **Les clients coupent égaliseur, chorus et
    réverbération (limiteur gardé) quand `route` = `breizh` au moment d'ouvrir le micro**, et ne changent rien
    pendant l'émission. Scrambler d'émission : impossible à activer quand `route` = `breizh` (message clair) ; activé
    avant, il est désactivé à l'arrivée de Breizh avec le même message (décision 6).
  - `late` / `lost` : blocs remplacés et replis de l'émission en cours (ou de la dernière).
  - `reactivate_in_s` : secondes avant la réactivation automatique (`null` hors `fallback`).
- **Commandes** :
  - `{"cmd":"breizh_set","return_gain_db":-3.5}` ou `{"cmd":"breizh_set","bypass":true}` (les deux champs sont
    facultatifs, au moins un) → `result` avec les réglages retenus ; refus `bad_value` hors bornes. `bypass` prend
    effet à la prochaine émission (jamais pendant), la liaison avec Breizh reste ouverte (PING) ; journal
    `bypass` / `unbypass` avec le compte.
  - `{"cmd":"breizh_reactivate"}` → `result` `{"pending": true}` (prendra effet à la prochaine émission ou dès que
    Breizh répond) ; refus `breizh_unavailable` si `off`.
  - `{"cmd":"breizh_log"}` → `result` `{"entries":[{"t":"2026-11-04T10:12:03Z","event":"fallback","detail":"…"}]}`
    (50 dernières).
  - Visiteur : les trois refusés par la liste blanche (`not_allowed`, inchangé).
- **Message** `{"type":"breizh_event","event":"fallback","detail":"Breizh ne répond plus : émission en direct, gain −6 dB"}`
  à tous les opérateurs. Événements : `connected`, `lost`, `fallback`, `back` (Breizh répond de nouveau),
  `reactivated` (`auto` ou compte), `bypass` / `unbypass` (compte), `refused` (`key`, `proto`, `format`, `cat_on`, `mode_off`, `busy`),
  `bad_packets` (nombre, une fois par minute au plus). `fallback` pendant une émission = alerte visible et bip court
  du client (pas de la station).
- **Client ancien** (qui ignore `breizh`) : il garde ses effets et peut brouiller ; la station ne peut pas le savoir.
  Accepté : la notice le dit.

## 8. Affichage

- Page et application : rubrique / onglet « Breizh Audio Box » (si `breizh` annoncé) : état en clair, liaison
  (`peer`, `rtt_ms`), volume retour (−20 à +6 dB), commutateur « Direct » (ignore Breizh ; « à la prochaine
  émission » s'il est changé pendant une émission), bouton « Réactiver Breizh » (en `fallback`), journal (50 lignes).
  Sur l'écran principal : petit voyant « BZH » vert (`ready` / `active`), orange (`fallback`), gris (autre, ou « Direct » choisi) ; toucher =
  la rubrique. Égaliseur : bandeau « Traitement par Breizh Audio Box » quand ses effets sont coupés.
- trx-monitor : ligne « Breizh » (état, route, rtt, late, lost) ; fichier d'état : champ `breizh`.
- TRX Console : menu 22 « Breizh Audio Box » : créer / remplacer la clé (affichée une fois, à recopier dans Breizh),
  adresse et port, essai de LIAISON (HELLO + 5 PING, sans aucun son), dernières lignes du journal. Aide `h 22`, mode
  d'emploi de la console.
- Superviseur : rien (Breizh ne peut pas émettre ; la passerelle reste la seule à ouvrir la porte). Pas d'alerte ntfy
  en V1.

## 9. Tests (faux Breizh : `trxstation/devtools/fake_breizh.py`)

Modes du faux Breizh : `echo`, `gain` (dB), `slow` (délai fixe), `jitter`, `freeze` (cesse de répondre), `drop`
(perd 1 bloc sur N), `forge` (étiquettes fausses), `replay` (renvoie d'anciens AUDIO_RET), `spontaneous` (AUDIO_RET
non demandés), `cat_on`, `proto2`.

**Tests de panne (passerelle, modèle factice Hamlib 1)**

1. Breizh absent au démarrage : `connecting`, l'émission part aussitôt en direct, aucun retard de prise.
2. Breizh gelé pendant une émission : repli en ≤ `lost_ms` + 20 ms, son direct à `fallback_gain_db`, `breizh_event`
   envoyé, **PTT, TOT et battements inchangés**, émission non coupée.
3. Breizh trop lent (délai > `block_timeout_ms`) : blocs remplacés, ordre gardé, aucun bloc deux fois, retours tardifs
   jetés ; délai > `lost_ms` : repli.
4. Paquets falsifiés (étiquette, session, adresse source, `len`, type inconnu, paquet tronqué) : jamais écrits,
   comptés ; 10 000 paquets/s faux ne bloquent pas la boucle (trames du micro toujours servies).
5. Paquets rejoués (même session et session précédente) : jetés.
6. AUDIO_RET d'un bloc jamais envoyé ou déjà répondu : jeté.
7. **Coupure pendant que des blocs sont chez Breizh** (stop, TOT, battement perdu, déconnexion, `rig_did_not_key`) :
   AUCUN octet n'atteint le puits après la fermeture de la porte (époque) ; puits vidé.
8. AUDIO_RET reçus hors émission (`spontaneous`) : rien n'atteint le puits.
9. Breizh revenu après repli : pas de retour pendant l'émission ; retour après `reactivate_after_s` de PONG sans
   faute ; `breizh_reactivate` avance le retour ; `reactivate_after_s = 0` : seulement à la main.
10. `cat_off` faux, `proto` 2, format refusé, mauvaise clé : `refused`, journal, émissions en direct.
11. Erreurs de socket (hôte injoignable, ICMP « port fermé », réseau coupé, `host` invalide au rechargement) : la
    passerelle NE QUITTE PAS (piège « Sécurité »), état `fallback` ou `connecting`.
12. Breizh perdu ET client déconnecté à la même seconde : retour RX normal, aucune exception.
13. Roger bip et trame SELCALL en route `breizh` : joués tels quels, non retardés, pas envoyés à Breizh.
14. Limiteur final : signal à +6 dB de retour et blocs à pleine échelle : crête ≤ −1 dBFS au puits, les deux routes.
15. Structure : `trxstation/breizh/` n'importe ni `gateway.safety` ni le CAT ; aucun AUDIO envoyé porte fermée ou par
    un non-propriétaire ; visiteur : `breizh_*` refusées, `state.breizh` absent.
16. « Direct » : `bypass` vrai = route `direct` à la prochaine prise, aucun AUDIO envoyé, gain normal (pas de gain
    de repli), PING maintenus ; changé pendant une émission : la route en cours ne change pas.
17. Configuration : adresse publique, nom d'hôte, clé absente / courte / lisible par tous, `lost_ms` ≤
    `block_timeout_ms` : erreur bloquante.

**Interopérabilité** : `tests/protocol/breizh_vectors.json` (clé, nonces, paquets complets attendus, étiquettes) :
relu par les tests de la station ET à reprendre tel quel dans le dépôt de Breizh. `trxstation/devtools/breizh_probe.py`
(fausse station : HELLO, PING, son de test 1 kHz, mesure de latence et de pertes) pour la conversation de Breizh.

**Essais réels** (après le lot V2 de Breizh) : même PC, puis deux PC en filaire, puis Wi-Fi (repli attendu plus
fréquent : à mesurer), Breizh fermé pendant une émission sur charge fictive, ALC avec et sans Breizh.

## 10. Charge

~100 paquets/s par sens, HMAC-SHA256 sur 1 ko : négligeable. Limiteur et gain en numpy (déjà utilisé par le SELCALL),
pas en Python échantillon par échantillon. À mesurer sur le Raspberry Pi 4 (`devtools/station_load.py`).

## 11. Ce qui n'est PAS fait en V1

- Chiffrement du son (décision 1 : clair sur le réseau local) ; liaison par Internet (adresse publique refusée).
- Plusieurs Breizh, ou un Breizh pour plusieurs stations (`busy`).
- Réception par Breizh (seulement l'émission).
- Contrôle par la station que Breizh a vraiment coupé son CAT (déclaration seulement).

## 12. Découpage en lots

| Lot | Contenu | Livré |
|---|---|---|
| 1 | `trxstation/breizh/protocol.py` (paquets, HMAC, session, rejeu), `[breizh]` dans `config.py` + validation + fichier de clé, vecteurs `tests/protocol/breizh_vectors.json`, faux Breizh, `breizh_probe.py`, notice station.toml | station, sans effet sur l'émission |
| 2 | `breizh/link.py` (session, PING, états, journal), route dans la chaîne d'émission (porte d'entrée, époque, blocs remplacés, repli, réactivation), limiteur final, volume retour, `state.breizh`, `breizh_set` / `breizh_reactivate` / `breizh_log`, `breizh_event`, `hello.features`, `docs/protocole.md`, exemples, commutateur « Direct », tests de panne 1-17, trx-monitor | station : utilisable avec le faux Breizh |
| 3 | Page : rubrique Breizh, voyant BZH, « Direct », effets coupés, scrambler exclusif, journal (tests Node, `TextsTest` à relancer) | page |
| 4 | Application : écran Breizh, voyant, « Direct », `VoiceHub` en bypass, scrambler exclusif, parité | application |
| 5 | TRX Console menu 22 (clé, essai de liaison, journal), mode d'emploi, notice (son en clair, pare-feu du PC Breizh) | station |

Le lot V2 de Breizh (serveur du protocole, onglet « OpenRemoteTRX », CAT coupé) peut commencer dès le lot 1 livré
(vecteurs + `breizh_probe.py`).

## 12 bis. Réalisation

- Lot 1 FAIT (étape 120, station 0.99.0) : `trxstation/breizh/protocol.py`, `keyfile.py`, `vectors.py` ;
  `[breizh]` dans `config.py` ; `tests/protocol/breizh_vectors.json` ; `devtools/fake_breizh.py`,
  `devtools/breizh_probe.py` ; notice de station.toml. Pour la conversation de Breizh : ce document (§ 5), les vecteurs,
  et `python -m trxstation.devtools.breizh_probe --host <PC de Breizh> --key <clé>` comme fausse station.
  Session (64 bits) en HEXADÉCIMAL dans les vecteurs : un nombre JSON perdrait des chiffres en JavaScript.

- Lot 2 FAIT (étape 121, station 0.100.0) : `breizh/link.py` (session, PING, états, réactivation), `breizh/store.py`
  (volume retour, « Direct », journal), `gateway/audio/route.py` (porte d'entrée, blocs dans l'ordre, remplacement,
  repli), `gateway/audio/limiter.py` (limiteur final, les deux routes), époque de la porte (`gate.py`), `state.breizh`,
  `breizh_set` / `breizh_reactivate` / `breizh_log`, `breizh_event`, fichier d'état et trx-monitor ; tests de panne
  `tests/test_breizh_route.py`. Choix faits en codant : un retour AUTHENTIQUE arrivé après son remplacement compte comme
  signe de vie (Breizh lent n'est pas Breizh perdu : pas de repli, blocs secs) ; clé illisible au démarrage = station
  SANS Breizh (journal d'erreur), jamais d'arrêt de la passerelle.

- Lot 3 FAIT (étape 122, station 0.101.0) : page web (voyant BZH, rubrique, volume retour, « Direct », réactivation,
  journal, égaliseur et effets coupés par `VoiceChain.setExternal` quand la route est Breizh, scrambler d'émission exclu,
  bip court de la page au repli pendant SON émission). Textes communs dans `client.js` (`BREIZH_STATES`, `breizhView`)
  pour l'application.

## 13. Décisions de l'utilisateur sur la v1 (2026-11-04 : les 8 points acceptés)

1. Blocs de **480 échantillons** (10 ms) au lieu de 256.
2. **Limiteur final de la station** (crête −1 dBFS) sur les DEUX routes, donc aussi sans Breizh.
3. Clé d'appairage dans un **fichier à part** (`breizh.key`), pas dans station.toml.
4. **Adresse privée exigée** pour `host`.
5. **Réactivation automatique après 60 s** de stabilité, jamais pendant une émission ; `breizh_reactivate` prend
   effet à la prochaine émission.
6. **Gain de repli −6 dB** par défaut.
7. **Port 47100** (à reprendre tel quel dans Breizh).
8. **Commutateur « Direct »** dans la page et l'application (`breizh_set` `{"bypass": true}`, § 6.2, 7, 8, test 16).
