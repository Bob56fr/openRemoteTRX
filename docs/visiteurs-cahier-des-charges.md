# openRemoteTRX — Cahier des charges : comptes visiteurs en réception seule

Version 3 — 2026-10-29. Réécrit d'après la demande de l'utilisateur et le code de la station 0.70.0 (la version 1, écrite sans le code, demandait une seconde table de comptes, un transport WebSocket et un diffuseur séparé : écartés, voir § 12). v3 : pseudos, accès lié à la présence de l'opérateur (§ 3 bis), décisions de l'utilisateur (§ 13).

## 1. Objet

Un **visiteur** écoute la station et voit toute l'interface, en lecture seule. Il ne peut agir que sur son propre affichage (spectres, volume). Plusieurs visiteurs peuvent être connectés en même temps, dans une limite réglée dans TRX Console.

Usages : démonstration en radio-club, formation, écoute partagée d'un QSO ou d'un réseau.

**Dans le périmètre** : rôle `listener` sur les comptes existants ; contrôle des droits par la station ; audio de réception et voix de l'opérateur pendant ses émissions ; spectre HF et spectre audio ; nombre et liste des visiteurs (page web, application, console, trx-monitor) ; menu « Visiteurs » de la console.

**Hors périmètre** : rôle intermédiaire (opérateur restreint), écoute anonyme ou publique, Android Auto (aucun changement).

**Règle fondamentale** : un visiteur ne peut RIEN changer à la station, au poste ni à ce que voient ou entendent les autres. La désactivation des boutons dans la page n'est qu'un confort : la protection est faite par la passerelle (§ 4).

## 2. Ce qui existe déjà (à réutiliser, pas à refaire)

| Besoin | Existant |
|---|---|
| Comptes | `[[clients]]` (`id`, `password_hash` scrypt), `ClientAuth` dans `config.py`, création par trx-setup |
| Authentification et freinage | `gateway/api/auth.py` : 5 échecs / min par origine, 30 / 15 min par compte, aucun hachage calculé quand verrouillé, durée égale si le compte n'existe pas |
| Connexions multiples | `PeerManager` (`webrtc.py`) : une connexion WebRTC par client, `max_peers` = 4, une reconnexion du même compte remplace l'ancienne |
| Point d'entrée des commandes | `ControlSession.on_message` (`session.py`) juste après `parse_command` ; liste `COMMANDS` dans `protocol.py` |
| Audio de réception partagé | `RxHub` : une capture, une file par abonné (`RxTrack`) |
| Spectre HF partagé | `SpectrumFanout` (`max_fps`) : une lecture du port B, redistribuée à chaque client qui affiche la vue HF |
| Verrou d'émission | `PttController` : `connect_client` / `disconnect_client`, seul le propriétaire bat, seule sa déconnexion coupe |
| Superviseur | « TX sans client » : vrai si le PROPRIÉTAIRE n'est plus dans `status.clients` (`supervisor/core.py`) |

Aujourd'hui, plusieurs opérateurs peuvent déjà être connectés en même temps ; seule l'émission est réservée à un seul (verrou). Ce lot ne change pas cette règle.

## 3. Comptes et configuration

On ajoute des champs à `[[clients]]` ; aucune nouvelle table.

```toml
[access]
max_listeners = 5                  # visiteurs connectés en même temps ; 0 = fonction désactivée (défaut)
max_operators = 4                  # connexions opérateur (ancien max_peers) : toujours disponibles, jamais prises par un visiteur
listeners_need_operator = true     # true : visiteurs admis SEULEMENT si un opérateur est connecté à distance (§ 3 bis)
operator_grace_s = 60              # attente après la perte du dernier opérateur avant de déconnecter les visiteurs (0 à 600)
listeners_outside_bands = false    # true : les visiteurs entendent aussi la réception hors [[bands]] (§ 9)

[[clients]]
id = "f4abc-pc"
password_hash = "scrypt$..."
pseudo = "Kriss F4ABC"
# role absent = "operator" (configurations existantes)

[[clients]]
id = "f4abc-tel"                   # même personne, autre appareil : même pseudo
password_hash = "scrypt$..."
pseudo = "Kriss F4ABC"

[[clients]]
id = "club1"
password_hash = "scrypt$..."
role = "listener"
pseudo = "Radio-club F6KXX"
enabled = true                     # facultatif, défaut true
expires = "2026-12-31"             # facultatif, fin de journée en heure locale de la station
```

Exigences :

1. Mot de passe en scrypt comme aujourd'hui (`passwords.py`) ; pas d'argon2 ni de bcrypt (dépendance inutile).
2. `role` absent = `operator`. Toute AUTRE valeur que `operator` ou `listener` est une erreur bloquante de validation (une faute de frappe ne doit jamais donner un compte opérateur).
3. **Pseudo** : nom montré aux autres connectés, à la place de l'identifiant (l'identifiant est la moitié d'un couple de connexion : il n'est JAMAIS envoyé à un autre client, quel que soit son rôle, sauf à l'opérateur dans la liste détaillée, § 7.2). Texte simple, 1 à 32 caractères, sans caractère de contrôle, échappé à l'affichage. Plusieurs comptes peuvent porter le même pseudo (une personne, plusieurs appareils), y compris un compte opérateur et un compte visiteur. Les pseudos sont choisis par l'administrateur de la station, jamais par le client. Pseudo absent : « Opérateur » ou « Visiteur » suivi d'un numéro de connexion, JAMAIS l'identifiant.
4. Compte `enabled = false` ou expiré : refusé avec un motif explicite (`account_disabled`, `account_expired`), APRÈS vérification du mot de passe (pas d'indice pour qui ne le connaît pas).
5. `max_listeners` atteint : nouvelle connexion visiteur refusée (`listeners_full`, « Nombre maximal de visiteurs atteint ») ; elle n'éjecte jamais un visiteur connecté. Les quotas opérateurs et visiteurs sont SÉPARÉS : cinq visiteurs n'empêchent jamais un opérateur d'entrer.
6. Une reconnexion du même compte remplace l'ancienne connexion (comportement actuel).
7. Freinage des essais : celui d'`auth.py`, sans changement. PAS de verrouillage d'un compte après 5 échecs : les identifiants sont des indicatifs, publics, n'importe qui pourrait bloquer un compte.
8. `[access]` et `[[clients]]` ne sont PAS des clés de profil de poste (`profiles.py` inchangé).

## 3 bis. Visiteurs admis seulement en présence de l'opérateur

`listeners_need_operator` (commutateur, défaut `true`) :

- **`true`** : un visiteur n'est admis que si AU MOINS une session `operator` est connectée à distance (toute connexion à la page ou à l'application, y compris depuis le PC de la station ; l'opérateur qui parle au micro du poste sans session n'est PAS « connecté »). Sinon refus `operator_absent` : « L'opérateur n'est pas connecté à la station : l'écoute des visiteurs n'est possible qu'en sa présence. »
- **`false`** : les visiteurs se connectent quand ils veulent, avec ou sans opérateur.

Perte de l'opérateur (commutateur à `true`) :

1. Quand la DERNIÈRE session opérateur se ferme, un délai de `operator_grace_s` (défaut 60 s, 0 à 600) commence. Les visiteurs connectés continuent d'écouter ; un bandeau leur indique « Opérateur momentanément déconnecté — fin de l'écoute dans 45 s ».
2. Si un opérateur (n'importe quel compte opérateur) se reconnecte avant la fin : délai annulé, bandeau retiré, rien n'est coupé.
3. Sinon, à la fin du délai : tous les visiteurs sont déconnectés avec le motif `operator_absent` et le même message.
4. Pendant le délai, une NOUVELLE connexion visiteur est refusée (`operator_absent`) ; un visiteur déjà connecté qui se reconnecte (même compte) est accepté.
5. Le délai part de la fermeture constatée par la station : une coupure Internet brutale n'est vue qu'à l'échec de la connexion WebRTC (jusqu'à ~30 s avec aiortc). L'attente réelle peut donc aller jusqu'à environ 90 s ; c'est accepté.
6. Le délai ne touche JAMAIS l'émission : la perte de l'opérateur propriétaire coupe l'émission tout de suite, comme aujourd'hui.
7. Passage du commutateur de `false` à `true` (rechargement de `station.toml`) sans opérateur connecté : le délai démarre comme ci-dessus.

## 4. Contrôle des droits par la station (exigence de sécurité principale)

1. Le rôle est lu dans `[[clients]]` à l'authentification et attaché à la session ; le client ne peut pas le choisir ni le changer.
2. **Liste blanche**, au seul point d'entrée `on_message`, avant toute exécution. Pour un `listener`, sont acceptées seulement deux commandes, qui ne touchent NI le poste NI la station :
   - `get_state` (relecture de l'état) ;
   - `spectrum_watch` (n'agit que sur l'envoi des balayages à CE client).
   Tout le reste est refusé avec `{"type":"result","ok":false,"reason":"forbidden"}`, y compris toute commande ajoutée plus tard. La liste des connectés est poussée dans `state` (§ 7) : aucune commande à demander.
3. Sont donc refusées toutes les autres, sans exception (décision de l'utilisateur : un visiteur n'agit en RIEN sur le poste) : `toggle`, `stop`, `heartbeat` (ignoré sans réponse, comme aujourd'hui pour un non-propriétaire), `local_release`, `set_*`, `spectrum_set`, `memory_*`, `layout_*`, `bug_report`, `beeps_set`, `selcall_*`. La mise en page affichée au visiteur est jointe à son `hello` (§ 6.6).
4. Une session `listener` n'appelle JAMAIS `ctrl.connect_client` ni `disconnect_client` : elle ne peut pas devenir propriétaire, et sa connexion ou sa perte n'a aucun effet sur l'émission.
5. Piste micro d'un visiteur : la station n'en négocie pas (connexion en réception seule) ; si le client en envoie une quand même, elle est consommée et jetée, jamais passée à la porte d'émission.
6. Données envoyées à un visiteur : `hello` et `state` habituels plus `role`, SANS ce qui ne le concerne pas : identifiants des comptes (remplacés par les pseudos), adresses IP, propriétaire du PTT sous forme d'identifiant (remplacé par son pseudo), réglages des bips et du SELCALL au-delà de l'état affiché. Aucun secret ne part aujourd'hui dans `hello` ; un test le vérifie pour un visiteur. Règle valable AUSSI entre opérateurs : un client ne reçoit jamais l'identifiant d'un autre compte, sauf dans la liste détaillée de l'opérateur (§ 7.2).
7. Journal : chaque refus est noté (compte, origine, commande), au plus une ligne par seconde et par session. Au-delà de 20 refus en une minute, la session est fermée (`too_many_forbidden`) et une alerte ntfy part (client modifié ou attaque : la page ne les envoie jamais).
8. Statut publié : `status.clients` ne contient QUE les opérateurs (un visiteur n'est jamais enregistré auprès du PttController) ; les connexions des deux rôles sont dans `status.presence`, pour que le superviseur et trx-monitor ne les confondent jamais. (Le champ `audio.listeners` existant, abonnés du `RxHub` tous rôles confondus, est gardé tel quel : le renommer casserait les clients.)

## 5. Audio des visiteurs

Transport : **WebRTC, comme l'opérateur**, connexion en réception seule (pas de micro). Même page, même application, même latence (bien sous 2 s). Le coût d'aiortc par connexion (un encodage Opus et un chiffrement par client) est MESURÉ au lot 2 avec 5 visiteurs ; un diffuseur Opus partagé n'est étudié que si la mesure le demande (§ 12).

Source entendue par les visiteurs :

| État | Source |
|---|---|
| Réception | Son du poste tel qu'il part vers les opérateurs (gain RX, squelch SELCALL et atténuation de ses tonalités compris) |
| Émission d'un client | Voix du propriétaire telle qu'elle part vers le poste (sortie de la porte d'émission), bips de fin et trame SELCALL compris |
| Émission locale (micro du poste) | Ce que la carte son du poste renvoie en émission (souvent du silence) : la station n'a pas cette voix |
| Aucun opérateur connecté | Son du poste : un visiteur peut écouter une station sans opérateur |

Exigences :

1. Mélangeur des visiteurs dans la passerelle : en émission, il prend les trames de la porte d'émission à la place de celles du `RxHub` ; fondu de 20 ms à chaque bascule (pas de clic).
2. L'opérateur ne reçoit JAMAIS ce mélange : ses connexions restent branchées sur le `RxHub` seul (il ne s'entend pas lui-même).
3. Isolement : file bornée par visiteur, la trame en trop est jetée (jamais d'attente) ; ni la porte d'émission ni le `RxHub` ne peuvent être ralentis par un visiteur. Test : un visiteur qui ne lit plus rien ne change ni l'audio de l'opérateur ni le retour en réception.
4. Visiteur durablement en retard (file pleine plus de 10 s) : déconnecté avec le motif `listener_too_slow`.
5. Hors bandes (§ 9) : silence à la place du son du poste.

## 6. Interface du visiteur (page web, puis application)

Même interface que l'opérateur (même mise en page, même thème) ; le client règle tout d'après `hello.role`.

1. Désactivées (grisées, `disabled`) : toutes les commandes du poste et de la station (fréquence, molette, bandes, modes, filtres, NR, NB, ATT, P.AMP, squelch, split, RIT, ΔTX, mémoires, PTT, SELCALL, réglages du spectre HF : span, référence, vitesse). Le PTT par le bouton du casque, les touches du volant ou un bouton HID est ignoré.
2. Masqués : Réglages de la station, bips, rapports de problème, égaliseur, SCRAMBLER (bouton, voyant, réglages : rien n'apparaît), enregistrement de profils de mise en page. Conséquence acceptée : pendant un QSO brouillé, le visiteur entend le signal brouillé (illisible), et en émission la voix de l'opérateur telle qu'elle part vers le poste, donc brouillée elle aussi (le brouillage est fait par le client de l'opérateur ; la station ne le connaît pas).
3. Actifs : volume et sourdine de l'appareil, zoom, palette, contraste et hauteur des deux spectres (réglages locaux, jamais envoyés).
4. Clic sur le waterfall ou sur un spot du Cluster DX : sans effet (pas d'accord). Les spots s'affichent s'ils existent.
5. Un appui sur un élément désactivé n'envoie RIEN (test).
6. Mise en page : celle par défaut de la station, jointe au `hello` du visiteur ; aucun enregistrement.
7. État en direct comme pour l'opérateur : fréquence, mode, S-mètre, Po/SWR/ALC, voyants ; l'afficheur passe en « ÉMISSION » quand l'opérateur émet.
8. Bandeau discret : « Visiteur — réception seule ».
9. Spectre audio : calculé par le client sur ce qu'il entend (en émission, la voix de l'opérateur).
10. Spectre HF : reçu comme l'opérateur, cadence plafonnée pour les visiteurs (`[access] listener_spectrum_fps`, défaut 5) ; réglages du poste choisis par l'opérateur.

## 7. Nombre et liste des visiteurs

1. Opérateurs et visiteurs : pictogramme casque et nombre (« 🎧 3 ») près de l'état de connexion, dès un visiteur, absent à zéro. Mis à jour sous 2 s (champ `presence` de `state`).
2. Opérateur : appui = liste des connectés (pseudo, rôle, durée de connexion ; en plus pour lui : identifiant du compte et origine IP) avec « Déconnecter » par visiteur et confirmation (commande `listener_kick`, opérateurs seulement).
3. Visiteur : appui = même liste réduite à pseudo, rôle et durée, opérateurs compris (décision de l'utilisateur). Ni identifiant ni IP.
4. Le nombre compte les CONNEXIONS visiteurs ; un pseudo connecté par deux comptes apparaît une fois avec « ×2 ».
5. Fonction annoncée dans `hello.features` (`presence`) : une page ou une application récente n'affiche rien face à une station ancienne.
6. Arrivée d'un visiteur : rien par défaut ; bip discret chez l'opérateur, en option du client.

## 8. TRX Console et trx-monitor

TRX Console, nouveau menu 20 « Visiteurs » (administrateur) :

- `max_listeners` (0 à 20), commutateur `listeners_need_operator` (ON/OFF), `operator_grace_s`, `listeners_outside_bands`, cadence du spectre des visiteurs ;
- comptes visiteurs : créer (mot de passe saisi deux fois ou tiré au hasard et affiché une fois), pseudo, nouveau mot de passe, activer / désactiver, expiration, supprimer ;
- pseudo des comptes opérateurs (affiché aux visiteurs) ;
- liste des visiteurs connectés et « Déconnecter ».

Prise en compte sans redémarrer : la passerelle relit `[[clients]]` et `[access]` quand `station.toml` change (date de modification, au plus une fois par seconde) et ne garde la nouvelle liste que si TOUT le fichier est valide (sinon l'ancienne reste et l'erreur est journalisée). Un compte désactivé, expiré, supprimé ou dont le mot de passe a changé est déconnecté aussitôt. Un changement du rôle d'un compte connecté le déconnecte (il se reconnecte avec le nouveau rôle).

« Déconnecter » depuis la console : NOUVEAU canal (il n'en existe aucun aujourd'hui de la console vers la passerelle ; trx-monitor parle à rigctld). Demande écrite par la console dans un fichier du dossier d'état (identifiant du compte, heure), lue par la passerelle avec le rechargement de `station.toml`, effacée une fois traitée, ignorée au-delà de 10 s. Ce canal ne peut que DÉCONNECTER un visiteur ; aucune nouvelle porte réseau.

trx-monitor : zone « Connexions » en LECTURE SEULE (rôle, nom, IP, durée, état OK / lent), en-tête « Visiteurs : 3 / 5 », refus de connexion dans le journal. Pas d'action « Déconnecter » : trx-monitor garde sa seule action STOP TX.

## 9. Hors bandes et cadre réglementaire

1. UN SEUL réglage, dans `station.toml` : `[access] listeners_outside_bands` (aucune table de bandes à part, aucun autre paramètre). `false` (défaut) : quand la fréquence de RÉCEPTION est hors des `[[bands]]` de la station, le son du poste est remplacé par du silence pour les visiteurs, avec le message « Hors bandes amateur — écoute des visiteurs suspendue ». La voix de l'opérateur en émission reste diffusée (il n'émet que dans une bande autorisée).
`true` : les visiteurs entendent la réception partout, sous la responsabilité de l'opérateur.
2. On réutilise `[[bands]]` (bandes d'émission autorisées) : plus strict qu'une table IARU complète, donc sûr, et sans nouvelle table à maintenir. Liste vide = silence permanent pour les visiteurs (la station n'émet pas non plus).
3. L'affichage (fréquence, spectre HF) reste visible.
4. Documentation : texte sur la responsabilité de l'opérateur qui retransmet ce qu'il reçoit (pas un avis juridique), dans `docs/acces-distant.md`.

## 10. Charge et priorité de l'opérateur

1. Les visiteurs ne dégradent jamais l'opérateur : files bornées qui jettent (§ 5.3), cadence du spectre plafonnée (§ 6.10).
2. Au lot 2, mesure sur minix-bzh (et Windows) avec 1 opérateur + 5 visiteurs : charge du processeur, retards audio (`tx_underruns`, `rx_dropped`), retards de la boucle asyncio. Les valeurs par défaut de `max_listeners` et de la cadence en découlent.
3. Le superviseur n'a RIEN de nouveau à lancer : les visiteurs sont servis par la passerelle. Une panne liée aux visiteurs ne doit jamais faire quitter la passerelle (règle existante).

## 11. Tests et critères d'acceptation

Tests automatiques (modèle factice Hamlib, faux rigctld) :

- [ ] Test paramétré sur TOUTE la liste `COMMANDS` : chaque commande hors liste blanche envoyée par un `listener` est refusée (`forbidden`) et le poste n'est pas sollicité (aucune commande au faux rigctld).
- [ ] Une commande ajoutée à `COMMANDS` sans être classée fait échouer un test (classement obligatoire opérateur / visiteur).
- [ ] Visiteur connecté puis perdu pendant une émission de l'opérateur : aucun effet sur l'émission ; il n'est jamais dans `ctrl._clients` ni `status.clients`.
- [ ] `role` inconnu dans `station.toml` : validation en erreur.
- [ ] `max_listeners` : la connexion n+1 est refusée, les n premières restent ; les opérateurs entrent toujours.
- [ ] Compte désactivé, expiré, supprimé, mot de passe changé : refus à la connexion, déconnexion si connecté ; `station.toml` invalide : ancienne liste gardée.
- [ ] Bascule de source réception → émission → réception (PTT simulé), fondu sans saut ; l'opérateur ne reçoit jamais sa voix.
- [ ] Visiteur qui ne lit plus : audio de l'opérateur et retour en réception inchangés ; déconnexion `listener_too_slow`.
- [ ] Hors `[[bands]]` : silence pour les visiteurs ; voix de l'opérateur diffusée en émission.
- [ ] `hello` et `state` d'un visiteur (et d'un second opérateur) : aucun secret, aucun identifiant de compte, aucune IP ; pseudos seulement ; compte sans pseudo affiché « Visiteur n ».
- [ ] `listeners_need_operator = true` : visiteur refusé sans opérateur (`operator_absent`) ; admis avec ; opérateur perdu puis revenu avant `operator_grace_s` : aucun visiteur coupé ; non revenu : tous déconnectés à l'échéance (horloge simulée) ; nouvelle connexion refusée pendant le délai ; perte de l'opérateur en émission : coupure immédiate, inchangée.
- [ ] `listeners_need_operator = false` : visiteur admis sans opérateur.
- [ ] Scrambler : aucun élément visible en rôle visiteur (test JS).
- [ ] 21 refus en une minute : session fermée, alerte.
- [ ] Tests JS : en rôle visiteur, aucun clic n'envoie de commande ; pictogramme et nombre.
- [ ] Scénarios de panne existants (gel de la passerelle, superviseur arrêté, client perdu) rejoués avec deux visiteurs connectés.

Essai réel (IC-7300MK2, minix-bzh, charge fictive) :

- [ ] 1 opérateur + 5 visiteurs (navigateurs et téléphones) pendant 30 min avec émissions : aucune dégradation pour l'opérateur ; mesure du processeur.
- [ ] Latence des visiteurs en réception et en émission.
- [ ] Nombre et liste à jour sous 2 s ; « Déconnecter » depuis la page de l'opérateur et la console.

## 12. Choix écartés de la version 1 (et pourquoi)

| Version 1 | Retenu | Raison |
|---|---|---|
| Table `[[users]]` / `login` | champs ajoutés à `[[clients]]` | les comptes existent déjà |
| argon2 ou bcrypt | scrypt | déjà en place, stdlib |
| Verrouillage du compte après 5 échecs | freinage actuel d'`auth.py` | identifiants publics : blocage de comptes par un tiers |
| Flux Opus unique par WebSocket, WebCodecs + WASM, MediaCodec | WebRTC en réception seule | aucun nouveau transport ni décodeur ; à revoir SEULEMENT si la mesure du lot 2 le montre |
| Diffuseur dans un processus séparé lancé par le superviseur | files bornées dans la passerelle | sortir l'audio du processus = nouvelle IPC et nouvelles pannes ; le superviseur reste minimal |
| Paliers de délestage CPU (85 %, 50 ms) | files qui jettent + mesure | inutile pour quelques visiteurs ; à ajouter si la mesure le demande |
| Table des bandes IARU par région | `[[bands]]` de la station | plus strict, déjà validé |
| « Déconnecter » dans trx-monitor | console et page de l'opérateur | trx-monitor reste en lecture seule |
| Verrouillage de session à 12 h | rien | la session vit avec la connexion ; un compte désactivé ou expiré est coupé aussitôt |

## 13. Décisions de l'utilisateur (2026-10-29)

1. **Aucune action d'un visiteur sur le poste**, STOP compris : rien ne part de la page d'un visiteur vers le poste, et la station refuse tout sauf `get_state` et `spectrum_watch` (§ 4).
2. **Scrambler invisible** pour les visiteurs (§ 6.2).
3. **SELCALL masqué** aux visiteurs (décision du 2026-10-30) : ni code armé, ni historique, ni état ; le squelch s'applique à leur son comme à celui de l'opérateur.
4. **Les visiteurs voient les pseudos** des autres visiteurs et des opérateurs ; jamais les identifiants ni les IP (§ 7).
5. **Pseudo** distinct de l'identifiant de connexion, partageable entre plusieurs comptes (§ 3).
6. **Commutateur `listeners_need_operator`** et attente de 60 s par défaut (§ 3 bis).
7. **Hors bandes** : un seul paramètre dans `station.toml` (§ 9).

Restent à confirmer après la mesure du lot 2 : `max_listeners = 0` à l'installation (fonction désactivée), cadence du spectre 5 balayages/s, défaut du commutateur à `true`.

## 14 bis. Réalisation

- **Lot 1 FAIT** (étape 84, station 0.71.0) : `config.py` (`ClientAuth.role/pseudo/enabled/expires`, `[access]`), `gateway/api/access.py` (rôles, quotas, présence, attente, pseudos, liste blanche), `session.py` (liste blanche, `bye`, `state.presence`), `webrtc.py` (admission, micro des visiteurs jeté, silence hors bandes), `gateway/access_watch.py` (relecture de `station.toml`, demande de déconnexion de la console), TRX Console menu 20, page : refus 403 / 503 et `bye` affichés. Le SILENCE HORS BANDES (§ 9), prévu au lot 2, est fait dès le lot 1.
- Reportés au lot 3 (avec la page) : commande `listener_kick` (« Déconnecter » depuis la page de l'opérateur), mise en page de la station jointe au `hello` d'un visiteur (§ 6.6), zone « Connexions » de trx-monitor (les données sont déjà dans le fichier d'état, `presence`).
- **Lot 2 FAIT** (même étape 84) : `gateway/audio/listeners.py` (copie de ce qui part vers le poste, mélange et fondu par visiteur), `[access] listener_spectrum_fps` (5 par défaut), outil de mesure `python -m trxstation.devtools.listener_load`. « Visiteur trop lent » (§ 5.4) : sans objet en WebRTC (aiortc envoie sans contre-pression ; les files bornées garantissent qu'aucun visiteur ne retarde le poste). Première mesure (PC Windows de développement) : 5,5 % d'un cœur par visiteur, pire retard de la boucle 26 ms avec 5 visiteurs ; à refaire sur minix-bzh pour fixer `max_listeners` et décider du flux Opus partagé (§ 12).

- **Lot 3 FAIT** (étape 86, station 0.73.0) : page en mode visiteur (tout grisé et inerte sauf affichage des spectres, volume et thème ; réglages de la station masqués ; client.js n'envoie rien d'autre que `get_state` et `spectrum_watch`), 🎧 N et liste, « Déconnecter » (`listener_kick`) et « Rouvrir l'écoute » (`listeners_reopen`) pour l'opérateur, zone de trx-monitor en lecture seule. Un visiteur garde la mise en page d'usine (§ 6.6 simplifié).
- **Protection contre la surcharge** (décision de l'utilisateur du 2026-10-30, `gateway/api/overload.py`) : 85 °C au processeur, 90 % de charge, 100 ms de retard de la passerelle ou moins de 10 % de mémoire libre pendant 10 s => visiteurs déconnectés avec la cause précise, arrivants refusés ; réouverture automatique après 5 minutes nettement en dessous (75 °C, 70 %, 50 ms, 15 %) ; après 3 coupures en une heure, réouverture à la main seulement (page de l'opérateur, TRX Console menu 20), acceptée seulement au vert. Seuils : `[access] overload_*`. Remplace les paliers du § 12.

- **Commutateur de l'opérateur et lot 4 FAITS** (étape 88, station 0.74.0, application 0.26.0) : « Écoute des visiteurs » en fin de rubrique Connexion (page) et dans les Réglages (application), mémorisé sur la station, FERMÉ par défaut ; fermer déconnecte les visiteurs présents. Un visiteur n'entre donc que si station.toml le permet (`max_listeners` > 0) ET si l'opérateur a ouvert l'écoute. Application : mode visiteur (tout inerte, rien n'est envoyé hors relecture de l'état et du spectre), 🎧 N, liste, « Déconnecter », « Rouvrir l'écoute ».

## 14. Découpage en lots

1. **Comptes et droits** : champs de `[[clients]]` (`role`, `pseudo`, `enabled`, `expires`), `[access]`, validation, quotas séparés, liste blanche dans `on_message`, présence de l'opérateur et délai, pseudos à la place des identifiants dans `state`, rechargement de `station.toml`, menu 20 de la console (`docs/console/contenu.toml`), tests de refus. `docs/protocole.md`, `tests/protocol/` (`role`, `presence`, `forbidden`, `operator_absent`, `listener_kick`), `hello.features`, `docs/parite-web-android.md`.
2. **Audio et spectre des visiteurs** : connexion en réception seule, mélangeur réception/émission, files bornées, silence hors bandes, cadence du spectre, mesure de charge.
3. **Page web** : rôle visiteur (désactivé / masqué / actif), pictogramme, liste, « Déconnecter » ; zone « Connexions » de trx-monitor.
4. **Application Android** : même comportement ; Android Auto inchangé.

Chaque lot est livré, testé et validé avant le suivant.
