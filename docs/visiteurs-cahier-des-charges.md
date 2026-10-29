# openRemoteTRX — Cahier des charges : comptes visiteurs en réception seule

Version 2 — 2026-10-29. Réécrit d'après la demande de l'utilisateur et le code de la station 0.70.0 (la version 1, écrite sans le code, demandait une seconde table de comptes, un transport WebSocket et un diffuseur séparé : écartés, voir § 12). Décisions encore à prendre : § 13.

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
max_listeners = 5        # visiteurs connectés en même temps ; 0 = fonction désactivée (défaut)
max_operators = 4        # connexions opérateur (ancien max_peers) : toujours disponibles, jamais prises par un visiteur

[[clients]]
id = "f4abc"
password_hash = "scrypt$..."
# role absent = "operator" (configurations existantes)

[[clients]]
id = "club1"
password_hash = "scrypt$..."
role = "listener"
display_name = "Radio-club F6KXX"   # facultatif, 40 caractères au plus
enabled = true                      # facultatif, défaut true
expires = "2026-12-31"              # facultatif, fin de journée en heure locale de la station
```

Exigences :

1. Mot de passe en scrypt comme aujourd'hui (`passwords.py`) ; pas d'argon2 ni de bcrypt (dépendance inutile).
2. `role` absent = `operator`. Toute AUTRE valeur que `operator` ou `listener` est une erreur bloquante de validation (une faute de frappe ne doit jamais donner un compte opérateur).
3. `display_name` : texte simple, validé (longueur, pas de caractère de contrôle), échappé à l'affichage.
4. Compte `enabled = false` ou expiré : refusé avec un motif explicite (`account_disabled`, `account_expired`), APRÈS vérification du mot de passe (pas d'indice pour qui ne le connaît pas).
5. `max_listeners` atteint : nouvelle connexion visiteur refusée (`listeners_full`, « Nombre maximal de visiteurs atteint ») ; elle n'éjecte jamais un visiteur connecté. Les quotas opérateurs et visiteurs sont SÉPARÉS : cinq visiteurs n'empêchent jamais un opérateur d'entrer.
6. Une reconnexion du même compte remplace l'ancienne connexion (comportement actuel).
7. Freinage des essais : celui d'`auth.py`, sans changement. PAS de verrouillage d'un compte après 5 échecs : les identifiants sont des indicatifs, publics, n'importe qui pourrait bloquer un compte.
8. `[access]` et `[[clients]]` ne sont PAS des clés de profil de poste (`profiles.py` inchangé).

## 4. Contrôle des droits par la station (exigence de sécurité principale)

1. Le rôle est lu dans `[[clients]]` à l'authentification et attaché à la session ; le client ne peut pas le choisir ni le changer.
2. **Liste blanche**, au seul point d'entrée `on_message`, avant toute exécution. Pour un `listener`, sont acceptées seulement :
   - `get_state` ;
   - `spectrum_watch` (n'agit que sur l'envoi des balayages à CE client) ;
   - `listeners_list` (nouvelle, § 7).
   Tout le reste est refusé avec `{"type":"result","ok":false,"reason":"forbidden"}`, y compris toute commande ajoutée plus tard.
3. Sont donc refusées, entre autres : `toggle`, `stop` (voir § 13), `heartbeat` (ignoré sans réponse, comme aujourd'hui pour un non-propriétaire), `local_release`, `set_*`, `spectrum_set`, `memory_*`, `layout_save` / `layout_reset` (écrivent sur la station), `layout_get` (autorisé seulement si le profil lu est celui de l'opérateur, voir § 6.6), `bug_report`, `beeps_set`, `selcall_*`.
4. Une session `listener` n'appelle JAMAIS `ctrl.connect_client` ni `disconnect_client` : elle ne peut pas devenir propriétaire, et sa connexion ou sa perte n'a aucun effet sur l'émission.
5. Piste micro d'un visiteur : la station n'en négocie pas (connexion en réception seule) ; si le client en envoie une quand même, elle est consommée et jetée, jamais passée à la porte d'émission.
6. Données envoyées à un visiteur : `hello` et `state` habituels plus `role`, SANS ce qui ne le concerne pas : liste nominative des connectés (remplacée par les nombres), détails des rapports, réglages des bips et du SELCALL au-delà de l'état affiché. Aucun secret ne part aujourd'hui dans `hello` ; un test le vérifie pour un visiteur.
7. Journal : chaque refus est noté (compte, origine, commande), au plus une ligne par seconde et par session. Au-delà de 20 refus en une minute, la session est fermée (`too_many_forbidden`) et une alerte ntfy part (client modifié ou attaque : la page ne les envoie jamais).
8. Statut publié (`status.clients`) : les visiteurs sont dans un champ SÉPARÉ (`listeners`), pour que le superviseur et trx-monitor ne les confondent jamais avec un opérateur. Attention : le champ `listeners` actuel de `AudioPipeline.stats()` (abonnés du `RxHub`) est renommé `rx_subscribers` pour éviter la confusion.

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
2. Masqués : Réglages de la station, bips, rapports de problème, égaliseur et scrambler d'émission, enregistrement de profils de mise en page.
3. Actifs : volume et sourdine de l'appareil, zoom, palette, contraste et hauteur des deux spectres (réglages locaux, jamais envoyés).
4. Clic sur le waterfall ou sur un spot du Cluster DX : sans effet (pas d'accord). Les spots s'affichent s'ils existent.
5. Un appui sur un élément désactivé n'envoie RIEN (test).
6. Mise en page : celle de l'opérateur par défaut de la station (`layout_get` du profil par défaut) ; aucun enregistrement.
7. État en direct comme pour l'opérateur : fréquence, mode, S-mètre, Po/SWR/ALC, voyants ; l'afficheur passe en « ÉMISSION » quand l'opérateur émet.
8. Bandeau discret : « Visiteur — réception seule ».
9. Spectre audio : calculé par le client sur ce qu'il entend (en émission, la voix de l'opérateur).
10. Spectre HF : reçu comme l'opérateur, cadence plafonnée pour les visiteurs (`[access] listener_spectrum_fps`, défaut 5) ; réglages du poste choisis par l'opérateur.

## 7. Nombre et liste des visiteurs

1. Opérateurs et visiteurs : pictogramme casque et nombre (« 🎧 3 ») près de l'état de connexion, dès un visiteur, absent à zéro. Mis à jour sous 2 s (champ `listeners` de `state`).
2. Opérateur : appui = liste des visiteurs (nom affiché ou identifiant, origine IP, durée de connexion) avec « Déconnecter » et confirmation (commande `listener_kick`, opérateurs seulement).
3. Visiteur : nombre seulement (voir § 13).
4. Nouvelle commande `listeners_list` ; fonction annoncée dans `hello.features` (`listeners`) : une page ou une application récente n'affiche rien face à une station ancienne.
5. Arrivée d'un visiteur : rien par défaut ; bip discret chez l'opérateur, en option du client.

## 8. TRX Console et trx-monitor

TRX Console, nouveau menu 20 « Visiteurs » (administrateur) :

- `max_listeners` (0 à 20) et cadence du spectre des visiteurs ;
- comptes visiteurs : créer (mot de passe saisi deux fois ou tiré au hasard et affiché une fois), nom affiché, nouveau mot de passe, activer / désactiver, expiration, supprimer ;
- liste des visiteurs connectés et « Déconnecter ».

Prise en compte sans redémarrer : la passerelle relit `[[clients]]` et `[access]` quand `station.toml` change (date de modification, au plus une fois par seconde) et ne garde la nouvelle liste que si TOUT le fichier est valide (sinon l'ancienne reste et l'erreur est journalisée). Un compte désactivé, expiré, supprimé ou dont le mot de passe a changé est déconnecté aussitôt. Un changement du rôle d'un compte connecté le déconnecte (il se reconnecte avec le nouveau rôle).

« Déconnecter » depuis la console : NOUVEAU canal (il n'en existe aucun aujourd'hui de la console vers la passerelle ; trx-monitor parle à rigctld). Demande écrite par la console dans un fichier du dossier d'état (identifiant du compte, heure), lue par la passerelle avec le rechargement de `station.toml`, effacée une fois traitée, ignorée au-delà de 10 s. Ce canal ne peut que DÉCONNECTER un visiteur ; aucune nouvelle porte réseau.

trx-monitor : zone « Connexions » en LECTURE SEULE (rôle, nom, IP, durée, état OK / lent), en-tête « Visiteurs : 3 / 5 », refus de connexion dans le journal. Pas d'action « Déconnecter » : trx-monitor garde sa seule action STOP TX.

## 9. Hors bandes et cadre réglementaire

1. `[access] listeners_outside_bands = false` (défaut) : quand la fréquence de RÉCEPTION est hors des `[[bands]]` de la station, le son du poste est remplacé par du silence pour les visiteurs, avec le message « Hors bandes amateur — écoute des visiteurs suspendue ». La voix de l'opérateur en émission reste diffusée (il n'émet que dans une bande autorisée).
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
- [ ] `hello` et `state` d'un visiteur : aucun secret, aucune liste nominative.
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

## 13. Décisions de l'utilisateur à prendre (avant le lot 1)

1. **STOP par un visiteur** : recommandé : REFUSÉ (en démonstration, un visiteur ne doit pas pouvoir couper l'opérateur ; la station a ses propres sécurités). L'autre choix se défend par la règle « couper est toujours permis ».
2. **Scrambler** : le débrouillage est fait par le client. Recommandé : un visiteur n'a ni débrouilleur ni brouilleur ; pendant un QSO brouillé, il entend le signal brouillé (illisible), et en émission la voix de l'opérateur telle qu'elle part, donc brouillée elle aussi. Pas de diffusion « en clair » aux visiteurs.
3. **Liste nominative pour les visiteurs** : recommandé : nombre seulement.
4. **Valeurs par défaut** : `max_listeners = 0` (désactivé à l'installation), cadence du spectre 5 balayages/s, à confirmer après la mesure.

## 14. Découpage en lots

1. **Comptes et droits** : champs de `[[clients]]`, `[access]`, validation, quotas séparés, liste blanche dans `on_message`, rechargement de `station.toml`, menu 20 de la console (`docs/console/contenu.toml`), tests de refus. `docs/protocole.md`, `tests/protocol/` (`role`, `forbidden`, `listeners_list`, `listener_kick`), `hello.features`, `docs/parite-web-android.md`.
2. **Audio et spectre des visiteurs** : connexion en réception seule, mélangeur réception/émission, files bornées, silence hors bandes, cadence du spectre, mesure de charge.
3. **Page web** : rôle visiteur (désactivé / masqué / actif), pictogramme, liste, « Déconnecter » ; zone « Connexions » de trx-monitor.
4. **Application Android** : même comportement ; Android Auto inchangé.

Chaque lot est livré, testé et validé avant le suivant.
