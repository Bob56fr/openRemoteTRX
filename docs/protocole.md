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
| Offre WebRTC | `POST /offer {"client_id", "password", "sdp", "type"}` | `{"sdp", "type"}` ; `400 bad_request`, `401 unauthorized` (même réponse quelle que soit la cause), `503 busy` (4 clients au plus, station sans `[access]`), `500 server_error` ; mot de passe JUSTE mais accès refusé (station 0.71.0+, § 13) : `403` ou `503` avec `{"error": motif, "message": texte à afficher}` |

- HTTPS obligatoire hors de la boucle locale (`docs/acces-distant.md`). Certificat auto-signé : le client l'**épingle** par son empreinte SHA-256, affichée par `trx-setup --empreinte` et TRX Console menu 4.1 (format `AB:CD:…`, 32 octets). Jamais de « faire confiance à tout ».
- Freinage des mots de passe faux : par origine (5/min) et par compte (30/15 min).
- Une offre acceptée qui ne se connecte pas en 20 s est abandonnée.
- Rôle du compte (`operator` ou `listener` = visiteur en réception seule) : décidé par la station (`[[clients]] role`), annoncé dans `hello.role` (§ 13).

## 3. Transport WebRTC

- **Audio** : une piste dans chaque sens, Opus 48 kHz mono. Le client envoie toujours sa piste micro ; la station n'en fait passer le son au poste que pour le propriétaire de l'émission, porte ouverte (`state.audio.gate_open`). Traitement du micro : pas de contrôle automatique de gain ; annulation d'écho et réduction de bruit selon le profil choisi par l'utilisateur (pièce calme, pièce bruyante, micro-casque avec ou sans réduction de bruit, personnalisé). La station garde 60 ms de réserve avant de jouer le son d'émission vers le poste (gigue du réseau) ; `state.audio.tx_underruns` compte les trous restants (réseau en retard), `tx_overruns` le son jeté car arrivé trop tard (depuis 0.58.0).
- **Canal `control`** (ouvert par le client, ordonné, fiable) : JSON, un objet par message, dans les deux sens.
- **Canal `spectrum`** (facultatif, ouvert par le client, `ordered: false`, `maxRetransmits: 0`) : balayages du spectre HF en binaire (§ 8).
- Limites : 2 048 octets par commande (sauf `layout_save` et `bug_report`, reconnus à leur début `{"cmd":"layout_save"` / `{"cmd":"bug_report"` : le client doit écrire `cmd` EN PREMIER), 64 ko au plus par message (aiortc), 30 messages/s par client (`error rate_limited` au-delà).

## 4. Versions et fonctions annoncées

- `PROTOCOL_VERSION` = 1, annoncée par `GET /config` et `hello.protocol`.
- **Ajout** (commande, champ, type de message, code, fonction) : la version NE change PAS ; les clients ignorent ce qu'ils ne connaissent pas.
- **Retrait ou changement de sens** : version + 1 ; la station accepte encore l'ancienne pendant au moins une version de l'application. Un client qui ne connaît pas la version annoncée le dit à l'utilisateur et reste en réception.
- **`hello.features`** : liste des fonctions offertes par CETTE station. Un client montre une fonction parce qu'elle y figure, jamais d'après un numéro de version.
  - toujours : `ptt`, `frequency`, `mode`, `squelch`, `functions`, `levels`, `local_release` ;
  - selon la station : `memories`, `layouts`, `spectrum` (second port CI-V actif), `beeps`, `bug_report`, `selcall` (`[selcall] enabled`, depuis 0.61.0), `selcall_send` (appel manuel et trame de fin, depuis 0.63.0 ; un client n'offre « Envoyer SELCALL » que si la station l'annonce), `selcall_calibrate` (niveau de la trame et réglage automatique, depuis 0.64.0), `presence` (rôles, pseudos et `state.presence`, depuis 0.71.0 : § 13), `host` (santé de la machine `state.host` et synthèse `host_info`, depuis 0.83.0 ; jamais annoncé à un visiteur), `voice_profiles` (profils d'égaliseur de l'opérateur rangés sur la station, depuis 0.86.0 ; jamais annoncé à un visiteur), `swr` (mesure de TOS, depuis 0.90.0, `[swr] enabled` ; jamais annoncé à un visiteur), `replay` (rediffusion d'un enregistrement, depuis 0.91.0 : `hello.replay`), `breizh` (Breizh Audio Box dans la chaîne d'émission, depuis 0.100.0, `[breizh] enabled` ; jamais annoncé à un visiteur : § 14).
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

Forme : `{"cmd": "<nom>", "id": <entier facultatif>, ...}`. `id` est le **numéro de la requête**, repris dans `result` ; l'identifiant d'une mémoire s'appelle `memory_id`. Toutes les commandes sauf `heartbeat`, `net_ping`, `net_pong` et `net_report` reçoivent un `result`.

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
| `set_offset` | `name` `RIT` ou `XIT`, `hz` entier (±99 999, resserré au « Max RIT/XIT » du poste : ±9 999 sur l'IC-7300MK2 ; RIT : ±500 Hz au plus depuis 0.81.0, `max_rit_hz` du descripteur) | décalage du clarifieur ; refusé pendant l'émission ; sur l'IC-7300 le RIT et le ΔTX partagent le même décalage |
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
| `selcall_activate` | `code` (texte de 3 à 8 chiffres) | `status` ; arme le squelch SELCALL de la station (VEILLE : plus aucun son reçu jusqu'à l'appel de ce code) ; message `selcall` diffusé à tous |
| `selcall_rearm` | — | `status` ; OUVERT -> VEILLE (même code) |
| `selcall_deactivate` | — | `status` ; son reçu normal |
| `selcall_options` | `filter_mode` (`mute`, `attenuate`, `chime`), `attenuation_db` (6 à 60) `send_on_tx_end` (booléen : trame émise en fin d'émission à la place du roger bip) et/ou `tx_level_dbfs` (niveau de la trame, -30 à -1, arrondi à 0,5 dB) | `status` |
| `selcall_calibrate` | — | `ptt` ; réglage automatique du niveau de la trame d'après l'ALC : ÉMISSION par ce client (mêmes refus que `toggle`), micro fermé, ton de 1 000 Hz par paliers de 2 dB (1,2 s chacun) depuis -30 dBFS ; arrêt dès que l'ALC décolle de son niveau de départ (+10 %) ou dépasse 50 % ; niveau retenu = dernier palier propre - 2 dB, enregistré ; progression dans `status.sending`, résultat dans `status.calibration` ; annuler = `stop` |
| `selcall_send` | — | `ptt` ; appel SELCALL manuel : ÉMISSION par ce client (mêmes refus que `toggle`, plus `selcall_not_armed`, `selcall_too_long`), micro du client fermé, trame du code armé `manual_repeat` fois ; progression dans `status.sending` ; annuler = `stop` ; fin : `last_cut_reason` `selcall_sent` (ou `selcall_timeout`, `selcall_failed`). Le client envoie ses battements comme pour toute émission dont il est propriétaire |
| `listener_kick` | `account` (identifiant d'un compte visiteur) | OPÉRATEUR seulement (station 0.73.0+) : déconnecte ce visiteur (`bye kicked`) ; refus `unknown_listener` s'il n'est pas un visiteur connecté. Il peut se reconnecter : pour l'en empêcher, désactiver son compte (TRX Console menu 4.2) |
| `host_info` | — | OPÉRATEUR seulement (station 0.83.0+, fonction `host`) : synthèse du matériel de la station ; réponse `sections` = `[{title, rows: [[libellé, valeur], ...]}]` déjà rédigées en français (machine, charge en ce moment, station, son), affichées telles quelles ; ni numéro de série, ni adresse IP ou MAC, ni chemin de port série ; n'agit sur rien |
| `voice_profiles` | — | OPÉRATEUR seulement (station 0.86.0+, fonction `voice_profiles`) : profils d'égaliseur et d'effets de voix du COMPTE ; réponse `profiles` = `[{name, settings}]` dans l'ordre d'enregistrement (`settings` : format de `voice.js` / `docs/egaliseur-voix.md`, sans le champ `format`) ; n'agit sur rien |
| `voice_profile_save` | `name` (1 à 32 caractères imprimables), `settings` (objet) | OPÉRATEUR seulement : crée le profil ou remplace celui du même nom (majuscules ignorées) ; 10 profils au plus par compte (refus `voice_profile_refused` avec `detail`) ; la station borne les réglages comme `voice.js validate` ; message compact sous 2 048 octets ; réponse `profiles` |
| `voice_profile_delete` | `name` | OPÉRATEUR seulement : supprime le profil (`voice_profile_refused` s'il n'existe pas) ; réponse `profiles` |
| `swr_plan` | `low_hz`, `high_hz` (entiers), `points` (2 à 200), `power_pct` (1 à 100, plafonné par `[swr] max_power_pct`) | OPÉRATEUR seulement (station 0.90.0+, fonction `swr`) : plan de la mesure de TOS SANS rien émettre (`docs/tos-cahier-des-charges.md`) ; réponse `plan` (`low_hz`, `high_hz`, `step_hz` lisible, `points` [`{hz, status}`, `status` = `pending` ou `out_of_band`], `amateur_only`, `fm_mode`, `power_pct`, `power_w`, `max_power_pct`, `settle_s`, `calibration_needed`, `estimated_s`) et `choices` (derniers choix du compte) ; refus `swr_bad_range`, `swr_too_many_points`, `swr_out_of_band` |
| `swr_start` | comme `swr_plan` | OPÉRATEUR : lance la mesure ; CHAQUE point est une prise d'émission NORMALE de ce client (mêmes refus que `toggle`, battements exigés, TOT, porte audio FERMÉE) ; mode FM permis par `tx_modes` (`FM`, `PKTFM`, `FM-D`), coupleur coupé, puissance demandée ; étalonnage du temps de lecture au premier usage d'un modèle ; toute coupure (STOP de n'importe quel client, TOT, battement, déconnexion...) arrête la mesure, jamais de reprise ; poste remis en état (relu) ; réponse `plan` puis messages `swr` ; pendant la mesure, les réglages du poste sont refusés à tous (`swr_busy`), STOP reste toujours possible ; refus `swr_busy`, `swr_no_fm_mode`, `swr_unavailable`, `tx_active` |
| `swr_cancel` | — | OPÉRATEUR : arrête la mesure (coupure immédiate, puis remise en état) |
| `swr_last` | — | OPÉRATEUR : dernière mesure rangée sur la station (`last`, résultat comme `swr.result`, ou `null`) et `choices` |
| `listeners_open` | `on` (booléen) | OPÉRATEUR seulement (station 0.74.0+) : commutateur « Écoute des visiteurs », mémorisé sur la station, FERMÉ par défaut ; `false` déconnecte les visiteurs présents (`bye listeners_closed`) ; `true` refusé (`listeners_off`) si `[access] max_listeners` vaut 0 ; réponse `open` |
| `listeners_reopen` | — | OPÉRATEUR seulement (station 0.73.0+) : rouvre l'écoute des visiteurs suspendue par une surcharge ; refus `still_overloaded` (avec `detail`) tant que la station n'est pas nettement revenue sous les seuils |
| `bug_report` | `text` non vide, 30 000 caractères au plus, relu par l'utilisateur, sans mot de passe | `name` du fichier rangé sur la station |
| `breizh_set` | `return_gain_db` (−20 à +6, pas de 0,5) et/ou `bypass` (booléen : « Direct ») ; au moins un | OPÉRATEUR seulement (station 0.100.0+, fonction `breizh`, § 14) : volume retour après Breizh et commutateur « Direct », enregistrés sur la station, pris à la PROCHAINE émission (jamais pendant) ; réponse `breizh` (comme `state.breizh`) ; message `breizh_event` `bypass` / `unbypass` ; refus `breizh_unavailable`, `breizh_storage_error` |
| `breizh_reactivate` | — | OPÉRATEUR : reprendre Breizh après un repli, à la prochaine émission ; réponse `pending` (vrai : attend que Breizh réponde) et `breizh` ; refus `breizh_unavailable` |
| `breizh_log` | — | OPÉRATEUR : journal de la liaison, réponse `entries` = 50 derniers `{t, event, detail}` (`t` : heure UTC ISO 8601) |
| `net_ping` | `seq` (0 à 2^31-1), `t` (horloge monotone du client, ms entières), `w` facultatif (heure Unix du client en ms, toutes les 60 s) | sonde réseau (station 0.106.0+, fonction `netprobe`, § 15) : la station répond aussitôt par le message `net_pong` (aucun `result`) ; admis pour un visiteur |
| `net_pong` | `seq`, `t` (repris du `net_ping` de la station), `tr` (horloge monotone du client à la réception, ms) | écho d'un `net_ping` de la station (aucune réponse) ; admis pour un visiteur |
| `net_report` | `report` : résumé de 10 s du client (§ 15) | aucune réponse ; enregistré pour un opérateur, sert seulement au niveau de l'indicateur pour un visiteur |
| `net_backlog` | `reports` : 90 résumés au plus ; message reconnu à son début (`{"cmd":"net_backlog"`, `cmd` en PREMIER), 60 000 octets au plus | OPÉRATEUR : 10 dernières minutes après une reconnexion ; réponse `count` |
| `net_stats` | `days` (1 à 90, défaut 30), `device` facultatif (identifiant d'appareil ou `""` = tous) | OPÉRATEUR : statistiques de la vue « Qualité du réseau » ; réponse `stats` (§ 15) |
| `net_clear` | — | OPÉRATEUR : « Tout effacer » l'historique réseau (pas les seuils choisis) |
| `net_thresholds` | `net_type` (`lan`, `wifi`, `4g`, `5g`, `mobile`, `unknown`) et `rtt_warn`, `rtt_alert` (20 à 5 000 ms), `loss_warn`, `loss_alert` (0,1 à 100 %), orange < rouge ; ou `reset: true` | OPÉRATEUR : seuils de l'indicateur choisis pour ce type de réseau (priment sur `station.toml`) ou retour aux valeurs de départ ; réponse `thresholds` (tous les seuils choisis) |
| `net_vpn_ignore` | `address` (adresse IP) | OPÉRATEUR : ne plus avertir d'un profil VPN partagé pour cette adresse |
| `net_export` | `part` (0 à 99 ; 0 = fabriquer un nouvel export) | OPÉRATEUR (station 0.109.0+) : export ANONYME des 30 derniers jours (zip : `rapport.html`, `donnees.json`), par morceaux ; réponse `name` (nom de fichier), `part`, `parts`, `size` (octets du zip), `data` (36 000 octets au plus, en base64) ; le client demande `part` = 1, 2… jusqu'à `parts` - 1 et assemble |
| `friends` | `action` (une de `view`, `stats`, `pseudo`, `texts`, `shack_for`, `shack_cancel`, `shack_rules`, `create`, `invite`, `join`, `leave`, `delete`, `exclude`, `role`, `share`, `rename`, `qsy_mark`, `qsy_back`), `args` (objet, 1 500 octets au plus, vérifié par le module) | OPÉRATEUR (station 0.118.0+, fonction `friends`, § 16) : présence de groupe, relayée au module « presence » ; réponse `action`, `data` (résultat de l'action) ; refus : `reason` du module ou `friends_unavailable` |
| `freedv_set` | `on` (booléen) | OPÉRATEUR (station 0.122.0+, fonction `freedv`, § 17) : mode FreeDV de la station en RÉCEPTION (voix décodée vers tous les clients, visiteurs compris) ; n'agit JAMAIS sur le poste ; refusé pendant toute émission (`freedv_tx`) ; réponse `freedv` (état comme `state.freedv`) ; refus : `freedv_unavailable`, `freedv_tx`, `freedv_missing` (décodeur introuvable), `freedv_storage_error` |

## 7. Réponses et erreurs

- `{"type":"result","id":N,"ok":true, ...}` : succès, champs selon la commande.
- `{"type":"result","id":N,"ok":false,"reason":"…","detail":"…"}` : refus. `detail` est un texte pour l'humain, `reason` un code stable :
  - émission : `not_idle`, `unknown_client`, `fault_latched`, `starting`, `tx_disabled` (aucune bande autorisée), `cat_down`, `cat_error`, `local_active`, `local_tx`, `rig_hot`, `cooldown`, `ptt_unreadable`, `cancelled`, `rig_already_tx`, `mode_not_allowed`, `out_of_band` (vérifié sur la fréquence d'ÉMISSION : en split celle de l'autre VFO, décalée du ΔTX s'il est en service), `split_unreadable`, `xit_unreadable` (split ou ΔTX déclarés par le poste mais illisibles : en cas de doute, pas d'émission), `ptt_write_failed`, `rig_did_not_key` ;
  - réglages : `tx_active` (pas en RX confirmé), `invalid`, `rig_error`, `cat_down` ;
  - fonctions absentes ou en panne : `memories_unavailable`, `unknown_memory`, `storage_error`, `layouts_unavailable`, `layout_invalid`, `layout_storage_error`, `spectrum_unavailable`, `beeps_unavailable`, `beeps_storage_error`, `selcall_unavailable`, `reports_unavailable` (et les motifs de refus d'un rapport), `freedv_unavailable`, `freedv_missing`, `freedv_storage_error`, `freedv_tx` (§ 17) ;
  - visiteur : `forbidden` (toute commande hors `get_state` et `spectrum_watch`, § 13).
- `{"type":"error","code":"…","detail":"…"}` : message illisible, sans `id` : `too_large`, `bad_json`, `bad_message`, `unknown_command`, `invalid_params`, `rate_limited`.

## 8. Messages (station -> client)

| Type | Quand | Contenu |
|---|---|---|
| `hello` | une fois, à l'ouverture du canal | `protocol`, `client_id`, `role` (`operator` ou `listener`, § 13), `pseudo` (nom montré aux autres connectés, `""` si la station n'a pas de contrôle des rôles), `version`, `capabilities` (descripteur du poste : modes, filtres par mode, fonctions et niveaux lisibles, préamplis, atténuateurs, plages ; construit l'interface), `tx_modes` (modes où l'émission est permise, vide = tous), `max_power_w` (0 = inconnue : puissance en %), `memories`, `layouts` (booléen), `spectrum` (`{source, level_max, max_fps}` ou `null`), `beeps` (réglages ou `null`), `selcall` (état comme le message `selcall`, ou `null`), `freedv` (station 0.122.0+ : état comme `state.freedv`, ou `null` sans `[freedv] enabled`, § 17), `replay` (`{max_s}` : rediffusion d'un enregistrement de l'audio reçu permise, durée maximale = TOT - 5 s ; `null` si la station ne l'a pas accordée (`[safety] allow_replay`, assistant) ou pour un visiteur ; station 0.91.0+), `features` |
| `swr` | au client qui a lancé la mesure de TOS, à chaque étape | `state` (`preparing`, `calibrating`, `measuring`, `restoring`, puis `done`, `cut` ou `failed`), `index` (point qui vient d'être mesuré ou `null`), `total`, `points` (`{hz, status, swr, power_w}` ; `status` : `pending`, `measured`, `out_of_band`, `unread`, `reduced` = puissance réduite par le poste), et à la fin `result` (`points`, `best`, `reason`, `detail` (motif de la coupure), `warning` (`swr_unstable`), `saved` (état d'origine), `restored` (état relu), `differences` (écarts à corriger à la main), `power_pct`, `power_w`, `fm_mode`, `at`) |
| `state` | aussitôt après `hello`, puis toutes les 250 ms s'il a changé, au moins chaque seconde | `ptt` (§ 5), `rig` (`connected`, `frequency_hz`, `mode`, `passband_hz`, `strength_db`, `functions` (dont `RIT`, `XIT`), `levels`, `split` (booléen, `null` = inconnu), `tx_frequency_hz` (fréquence d'émission en split, sinon `null`), `offsets` (`RIT`, `XIT` : décalages en Hz), `vfo` (VFO actif tel que Hamlib le nomme : `VFOA`, `VFOB`, `MEM`, `Main`, `Sub`... ; `null` = non lisible, cas de l'IC-7300MK2 : `get_vfo` RPRT -11 ; station 0.65.0+, affichage seul)), `audio` (niveaux et compteurs, diagnostic ; `listeners` = abonnés au son reçu, TOUS rôles confondus), `clients` (comptes opérateurs connectés ; `[]` pour un visiteur), `spectrum` (`state` : `waiting`, `starting`, `ok`, `error` ; `code`, `message`, `settings`), `presence` (§ 13, `null` sans contrôle des rôles), `host` (station 0.83.0+ : santé de la machine de la station pour le petit bargraph, recalculée toutes les 2 s : `cpu_pct`, `mem_pct` (mémoire utilisée), `disk_pct`, `temp_c` (processeur ; `null` sous Windows), `throttled` (Raspberry Pi : ralenti EN CE MOMENT, `null` ailleurs), `load` (0 à 1 : la mesure la plus proche de son seuil rouge, rouge à 0,9), `level` (`ok`, `warn`, `bad`), `worst` (`cpu`, `mem`, `disk`, `temp`, `power` ou `""`) ; seuils orange / rouge : processeur 75 / 90 %, mémoire 80 / 90 %, disque 85 / 95 %, température 75 / 85 °C ; `null` pour un VISITEUR), `breizh` (station 0.100.0+ avec `[breizh] enabled`, opérateurs seulement, ABSENT sinon : § 14), `net` (station 0.106.0+ avec la fonction `netprobe` : la liaison de CE client, § 15 ; ABSENT sinon), `freedv` (station 0.122.0+ avec `[freedv] enabled`, TOUTES les connexions : § 17 ; ABSENT sinon) |
| `result`, `error` | réponse à une commande | § 7 |
| `memories` | une mémoire change (n'importe quel client) | `items` : `{id, name, hz, mode, favorite}` |
| `beeps` | réglage des bips changé | `settings` |
| `selcall` | état du SELCALL changé (commande d'un client, appel reçu) | `status` : `state` (`disabled`, `standby`, `open`), `code`, `history` (récent en tête), `filter_mode`, `attenuation_db`, `last_call` (`code`, `delta_hz`, `snr_db`, `at` : heure Unix) ou `null`, `send_on_tx_end`, `sending` (appel manuel ou réglage en cours : « 1/3 », « réglage -20 dBFS : ALC 5 % »…, sinon vide), `tx_level_dbfs`, `calibration` (résultat du dernier réglage automatique) ; le passage `standby` -> `open` = appel reçu (bip discret chez le client) |
| `bye` | juste avant que la station ferme la connexion (station 0.71.0+) | `reason` (`listeners_closed` (0.74.0+), `station_overload` (0.73.0+), `operator_absent`, `listeners_off`, `account_disabled`, `account_expired`, `account_changed`, `kicked`, `too_many_forbidden`), `message` (texte à afficher). Le client affiche le message et NE se reconnecte PAS tout seul |
| `breizh_event` | à chaque opérateur, à chaque événement de la liaison avec Breizh (station 0.100.0+, § 14) | `t`, `event`, `detail` (texte français à afficher) ; `event` : `connected`, `lost` (Breizh perdu hors émission), `fallback` (perdu PENDANT une émission : alerte et bip court du client), `back` (Breizh répond de nouveau), `reactivated`, `refused`, `bad_packets`, `bypass`, `unbypass` |
| `net_ping` | chaque seconde (`[netprobe] heartbeat_interval_s`) à chaque client, station 0.106.0+ avec la fonction `netprobe` | `seq`, `t` (horloge monotone de la station, ms) ; le client répond AUSSITÔT par la commande `net_pong` |
| `net_pong` | réponse immédiate à la commande `net_ping` | `seq`, `t` (repris), `tr` (horloge monotone de la station) |
| `net_event` | aux OPÉRATEURS : coupure close et diagnostiquée, profil VPN probablement partagé | `event` : `outage` (`outage` : `start_ms`, `end_ms` (heure Unix de la station), `duration_ms`, `diagnosis`, `basis`, `agent`, `net_type`, `kind` = `in_session` ou `disconnect`) ou `vpn_shared` (`warning` : `address`, `kind` = `same_time`, `alternate` ou `pattern`, `agents`, `since_ms`, `period_ms`) |
| `freedv_event` | à TOUS les clients, visiteurs compris (station 0.122.0+, § 17) | `kind` : `callsign` (`callsign`, `snr_db` (entier ou `null`), `t` : heure Unix), `sequence` (fin d'une séquence de voix : `start`, `duration_s`, `note` de 1 à 5, `detail`, `callsigns`), `fault` (`cause` : décodeurs abandonnés après leurs relances, son du poste remis) |
| `module` | message d'un module (cluster DX…) | `module`, `data` (format propre au module : `docs/cluster-dx.md`) ; spots (`kind` « spots » : bande du poste ; « recent » : 30 derniers toutes bandes, depuis 0.56.0) seulement vue HF ouverte |

Les champs `functions` et `levels` de `state.rig` sont des tables ouvertes (selon le poste) ; ne compter que sur ce qu'annonce `hello.capabilities`.

**Balayages du spectre** (canal `spectrum`, binaire, petit-boutiste) : en-tête de 16 octets `version(1) mode flags réservé | numéro uint32 | bord gauche Hz uint32 | bord droit Hz uint32`, puis un octet par point de 0 à `level_max`. Un numéro plus ancien que le dernier reçu est jeté (compteur remis à zéro à chaque connexion : la station peut avoir redémarré). Détail : `trxstation/spectrum/frame.py` ; exemples partagés : [`tests/protocol/spectrum.json`](../tests/protocol/spectrum.json) (pytest `test_spectrum_frames_match_the_shared_examples`, Kotlin `SpectrumTest`).

## 9. Instantané `ptt` des réponses

`result.ptt` (réponse à `toggle`, `stop`, `local_release`) contient les champs de `state.ptt` plus `event` (dernier évènement : `tot_warning`, `fault`, `fault_cleared`, `local_active`, `local_released`, `temp_alert`… ; indicatif). Le client affiche ensuite le `state` suivant : c'est lui qui fait foi.

## 10. Reconnexion (comportement attendu d'un client)

Premier essai après 400 ms, puis 1,5 s, 3 s, 4,5 s au plus entre deux essais, pendant une fenêtre réglable (300 s au plus) ; un canal qui ne s'ouvre pas en 6 s est abandonné pour réessayer. Identifiants refusés (`401`) ou accès refusé (`403`) : arrêt immédiat ; après un `bye`, aucune reconnexion automatique. Après reconnexion : réception, l'utilisateur doit réarmer. Sons de la page : `lost` (perte), `restored` (rétablie, en réception), `failed` (abandon).

## 11. Modifier le protocole (règle des livraisons)

Toute livraison qui ajoute ou change une commande, un champ ou un message :
1. met à jour `protocol.py` / `session.py` ET ce document ;
2. ajoute ou corrige les exemples de `tests/protocol/` (le test échoue sinon) ;
3. ajoute un mot à `hello.features` si c'est une fonction qu'une station peut ne pas offrir ;
4. note dans la matrice de parité page / application ce qui reste à faire de chaque côté (`docs/android-cahier-des-charges.md` § 8).

## 12. QR code d'appairage

Affiché par TRX Console (menu 4.1) et `trx-setup --empreinte` ; lu par l'application (« Scanner le QR code de la station »). Il évite de taper l'empreinte. Il ne contient **JAMAIS de mot de passe** (la station ne les connaît pas en clair).

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

## 13. Visiteurs en réception seule (station 0.71.0+)

Cahier des charges : [`docs/visiteurs-cahier-des-charges.md`](visiteurs-cahier-des-charges.md). Un compte `[[clients]] role = "listener"` écoute et voit l'état, sans RIEN pouvoir changer.

- **Liste blanche** : un visiteur ne peut envoyer que `get_state` et `spectrum_watch`. Toute autre commande (y compris `stop`, et toute commande ajoutée plus tard) reçoit `result ok:false reason:"forbidden"` ; `heartbeat` est ignoré sans réponse ; un message de plus de 2 048 octets est refusé sans analyse. Au-delà de 20 refus en une minute, la station envoie `bye too_many_forbidden`, ferme la connexion et alerte (ntfy). Le client d'un visiteur ne doit envoyer aucune autre commande.
- Un visiteur n'est **jamais** enregistré auprès de la sécurité d'émission : sa connexion ou sa perte n'a aucun effet sur une émission. Son micro éventuel est lu et jeté (jamais vers le poste).
- **Admission** (après le mot de passe, réponse de `POST /offer`) : `403 account_disabled`, `403 account_expired`, `403 listeners_off` (`[access] max_listeners = 0`), `503 listeners_full`, `403 operator_absent` (`listeners_need_operator = true` et aucun opérateur connecté), `503 operators_full` (opérateurs : quota `max_operators`, jamais pris par un visiteur).
- **Présence de l'opérateur** : avec `listeners_need_operator = true`, la perte du dernier opérateur ouvre une attente de `operator_grace_s` (défaut 60 s, `state.presence.grace_remaining_s`) ; un opérateur revenu à temps annule tout ; sinon `bye operator_absent` à chaque visiteur. Pendant l'attente, seul un visiteur déjà présent peut se reconnecter.
- **Son d'un visiteur** : en réception, le son du poste ; pendant une émission de la station, ce qui part vers le poste (voix du propriétaire après la porte, bips et trame SELCALL de fin), avec un fondu de 20 ms à chaque bascule. Un opérateur ne reçoit jamais sa propre voix. Spectre HF : au plus `[access] listener_spectrum_fps` balayages par seconde (5 par défaut).
- **Hors bandes** : `[access] listeners_outside_bands = false` (défaut) : le son reçu par un visiteur est remplacé par du silence quand la fréquence de réception sort des `[[bands]]` de la station (ou est inconnue).
- **Pseudos** : un client ne reçoit jamais l'identifiant d'un AUTRE compte, sauf un opérateur dans `presence.connections`. Pour un visiteur : `state.ptt.owner` = pseudo du compte qui émet, `state.clients` = `[]`, `hello.beeps` = `null`, SELCALL MASQUÉ (`hello.selcall` = `null`, aucun message `selcall`, ni `selcall`, `selcall_send` ou `selcall_calibrate` dans `hello.features` : le code de groupe ne part jamais vers un visiteur ; le squelch s'applique quand même au son qu'il reçoit). Compte sans pseudo : « Opérateur » ou « Visiteur N ».
- **Surcharge** (station 0.73.0+, `gateway/api/overload.py`) : processeur >= `[access] overload_temp_c` (85 °C), charge >= `overload_cpu_pct` (90 %), retard de la passerelle > `overload_lag_ms` (100 ms) ou mémoire libre < `overload_mem_pct` (10 %) pendant 10 s : chaque visiteur reçoit `bye station_overload` (message précis : la cause et la valeur), les nouvelles connexions sont refusées (`403 station_overload`) ; réouverture automatique après 5 minutes NETTEMENT sous les seuils (température - 10 °C, 70 %, retard / 2, mémoire + 5 points) ; après 3 coupures en une heure, réouverture à la main seulement (`listeners_reopen`, TRX Console menu 4.2). État : `state.presence.suspended` = `null` ou `{reason, message, since_s, locked, reopen_in_s}`.
- **`state.presence`** : `operators`, `listeners` (connexions ouvertes), `max_listeners`, `open` (commutateur de l'opérateur ET `max_listeners` > 0, station 0.74.0+), `suspended` (ci-dessus), `grace_remaining_s` (`null` hors attente), `people` (`{pseudo, role, since_s, count}` : un pseudo connecté par plusieurs comptes apparaît une fois avec `count`) ; pour un opérateur seulement, `connections` (`{id, pseudo, role, source, since_s}`). Exemples : `tests/protocol/messages.json` (`state`, `state_listener`, `bye`, `offer_refused`).

## 14. Breizh Audio Box dans la chaîne d'émission (station 0.100.0+)

Fonction `breizh` (`[breizh] enabled`, opérateurs seulement). Le micro du propriétaire passe par Breizh Audio Box (autre
PC du réseau local) avant la porte d'émission ; la station garde le PTT, la porte, le TOT, le limiteur final et le repli.
Cahier des charges : [`docs/breizh-cahier-des-charges.md`](breizh-cahier-des-charges.md).

- `state.breizh` : `state` (`connecting`, `ready`, `active` = émission en cours par Breizh, `fallback` = repli, `refused`),
  `route` (`breizh` ou `direct` : route de l'émission EN COURS, sinon de la prochaine ; `direct` si `bypass`), `bypass`,
  `return_gain_db`, `rtt_ms` (aller-retour, `null` avant la première mesure), `late` (blocs remplacés par le son
  d'origine dans l'émission en cours ou la dernière), `lost` (replis de cette émission : 0 ou 1), `peer` (version de
  Breizh), `reactivate_in_s` (secondes avant le retour automatique, `null` hors repli ou si la station attend l'opérateur).
- **Le client coupe égaliseur, chorus et réverbération (limiteur gardé) quand `route` vaut `breizh` au moment d'ouvrir le
  micro**, et ne change rien pendant l'émission. Scrambler d'émission impossible quand `route` vaut `breizh` (exclusifs).
- Route fixée à la prise : seul le passage `breizh` -> `direct` (repli, `breizh_event fallback`) arrive pendant une
  émission ; le repli ne coupe JAMAIS l'émission.
- Exemples : `state_breizh`, `breizh_event`, `breizh_log_result` de [`tests/protocol/messages.json`](../tests/protocol/messages.json).

## 15. Sonde de qualité réseau (station 0.106.0+, fonction `netprobe`)

Cahier des charges : [`docs/netprobe-cahier-des-charges.md`](netprobe-cahier-des-charges.md). La sonde MESURE et AFFICHE : aucun de ces messages n'agit sur le poste, l'émission ou le battement d'émission (`heartbeat`, § 5, inchangé). Calculs identiques dans la station (`trxstation/netprobe/calc.py`), la page (`static/netprobe.js`) et l'application (`logic/NetProbe.kt`), figés par [`tests/protocol/netprobe_vectors.json`](../tests/protocol/netprobe_vectors.json). Un client n'envoie ces commandes que si `hello.features` contient `netprobe`.

- **Appareil** : `POST /offer` accepte deux champs facultatifs, `device` (identifiant tiré au hasard UNE fois par le client, 32 caractères hexadécimaux, sans rien de personnel) et `agent` (« page Windows », « android 0.53.0 », 48 caractères au plus). Une station plus ancienne les ignore. Ils servent à relier une reconnexion à la coupure qui l'a précédée et à repérer un profil VPN partagé.
- **Battement réseau** dans les deux sens, toutes les `heartbeat_interval_s` (1 s) : la station envoie `net_ping`, le client répond `net_pong` ; le client envoie `net_ping`, la station répond `net_pong`. `t`, `tr` : horloges MONOTONES en ms entières de l'émetteur et du répondeur ; l'aller-retour se mesure sur l'horloge de l'émetteur seul. `w` (heure Unix du client, toutes les 60 s) : écart d'horloge estimé par la station pour recaler les résumés du client.
- **Indicateurs** (fenêtres de 10 s et 60 s) : un battement sans écho depuis moins de 5 s est en attente ; sans écho depuis 5 s, ou avec un écho arrivé après 5 s (« tardif »), il est perdu. Perte en % au dixième ; aller-retour moyen, p95 (rang le plus proche), max ; gigue = formule de la RFC 3550 sur les allers-retours successifs ; hors séquence = échos arrivés après un écho de numéro plus grand.
- **Coupure** : `outage_missed_beats` (3) battements envoyés depuis le dernier écho, chacun sans réponse depuis au moins un intervalle ; elle commence à l'envoi du premier et finit au premier écho reçu. Une déconnexion suivie d'une reconnexion du MÊME appareil dans les 30 min est aussi une coupure (`kind` `disconnect`). Le diagnostic attend 15 s les résumés du client.
- **`state.net`** : `level` (`gray` moins de 10 s de mesures, `green`, `orange`, `red`), `loss_pct` (60 s), `loss_pct_10`, `rtt_ms` (p95 sur 60 s), `rtt_mean_ms`, `jitter_ms`, `late`, `out_of_order`, `outage` (coupure en cours), `outage_s`, `last_outage` (`ago_s`, `duration_s`, `diagnosis` ou `null` en attente), `net_type` (dernier résumé du client), `thresholds` en service (`rtt_warn`, `rtt_alert`, `loss_warn`, `loss_alert`), et pour un OPÉRATEUR `vpn` (avertissements de profil partagé, comme `net_event.warning`) et `probes` (station 0.107.0+ : sondes de la station, `lan` = box, `internet` ; chacune `address`, `method` (`icmp`, `tcp` ou `null`), `ok` (dernier essai), `loss_pct`, `rtt_ms` sur 60 s ; `{}` si aucune).
- **Résumé du client** (`net_report.report`, éléments de `net_backlog.reports`) : `t` (heure Unix du client en ms, OBLIGATOIRE), `net_type` (`lan`, `wifi`, `4g`, `5g`, `mobile`, `unknown` ou `null`), `loss_pct`, `rtt_mean_ms`, `rtt_p95_ms`, `jitter_ms` (vus par le client), `health_ok` / `health_fail` (réponses et échecs de `GET /health` pendant les 10 s), `degraded` (trou audible dans le son), `concealed_pct` (% d'échantillons masqués par le décodeur), `rsrp_dbm`, `sinr_db`, `signal_level` (0 à 4), `cell_changed`, `net_switched` (bascule Wi-Fi / mobile ou changement d'adresse), `ice` (état ICE). Tout champ absent vaut `null` ou `false` ; un champ inconnu est ignoré ; une valeur hors bornes refuse le message (`invalid_params`).
- **Diagnostic** (`diagnosis`) : `app_station`, `lan`, `box_internet`, `webrtc`, `phone_radio`, `vpn_shared`, `mobile_or_tunnel`, `unknown` ; `basis` = faits qui l'appuient (`backlog`, `health_ok`, `radio_weak`, `cell_changed`, `network_switched`, `regular_pattern`, sondes de la station).
- **`net_stats.stats`** : `days`, `device`, `now_ms`, `devices` (`device`, `agent`, `last_ms`), `summary` (`outages`, `outage_s`, `longest_s`, `connected_s`, `availability_pct`, `loss_pct`), `per_day` (`date` locale, `outages`, `outage_s`, `by_diagnosis`, `hours` = 24 compteurs de coupures, `loss_pct`, `rtt_p95_ms`), `by_diagnosis`, `by_net_type` (`windows`, `outages`, `loss_pct`), `thresholds` par type de réseau (`in_force`, `chosen`, `rtt_hist` et `loss_hist` = `[fenêtres, dont son dégradé]` par case, `days`, `proposed` : `{rtt, loss}` chacun `{warn, alert}` ou `null`), `edges` (`rtt_ms`, `loss_pct` : limites des cases), `outages_list` (50 dernières).
- Sondes de la station (0.107.0+) : une par seconde vers la box (`[netprobe] lan_target`, `auto` = passerelle par défaut) et vers `internet_target`, en ICMP sans privilège, sinon en TCP toutes les 5 s ; faits `lan_probe_down`, `internet_probe_down` du diagnostic. Export anonyme : `net_export` (station 0.109.0+), aussi `trx-netreport --export`.

## 16. Présence de groupe « Amis » (station 0.118.0+, fonction `friends`)

Cahier des charges : [`docs/presence-cahier-des-charges.md`](presence-cahier-des-charges.md). Le module « presence »
échange avec le relais des états CHIFFRÉS ; il n'a AUCUN droit sur le poste. Annoncée dans `hello.features` (`friends`)
seulement pour un OPÉRATEUR, quand `[presence] enabled` et « presence » est dans `[modules] run`. Un visiteur ne reçoit
ni la commande ni les avis.

- **Commande** `{"cmd": "friends", "id": 7, "action": "…", "args": {…}}` ; réponse `{"type": "result", "id": 7,
  "ok": true, "action": "…", "data": {…}}`, ou `ok: false` avec `reason` : `module_absent` (module arrêté), `timeout`,
  `args`, `unknown_group`, `not_admin`, `not_registered`, `relay_unreachable`, `invitation_expired`,
  `invitation_token_used`, `other_relay`, `already`, `quota`, `pseudo`, `text`, `share`, `name`… et `detail` (texte).
- **Actions** (`args`) : `view` (`g` facultatif : un seul groupe) ; `stats` (`g`, administrateurs) ; `pseudo`
  (`pseudo`) ; `texts` (`texts`, 8 textes prédéfinis) ; `shack_for` (`minutes`, 1 à 1 440) ; `shack_cancel` ;
  `shack_rules` (`rules` : `[{"days": [0..6], "start": "HH:MM", "end": "HH:MM"}]`, 7 au plus, `suspended_until`
  facultatif) ; `create` (`name`) -> `g` ; `invite` (`g`, `days` 1 à 30, défaut 7) -> `url` (contient la clé du
  groupe : à ne montrer qu'à l'opérateur) ; `join` (`url`, `name` facultatif) -> `g` ; `leave`, `delete` (`g`) ;
  `exclude` (`g`, `member`) ; `role` (`g`, `member`, `role` a / c / m) ; `share` (`g`, `level` f / o / x, `text`
  si x, `invisible`, `hide_absence`) ; `rename` (`g`, `name`) ; `qsy_mark` -> `back` (fréquence et mode ACTUELS,
  retenus avant un QSY vers un ami) ; `qsy_back` -> `back` (rendu une fois, puis oublié).
- **Vue** (`view`) : `station`, `pseudo`, `registered`, `problem`, `last_sync`, `texts`, `groups` : `g`, `name`,
  `role` (a / c / m), `status` (`member`, `pending`, `removed`), `share`, `members` triés (actifs d'abord) : `id`,
  `pseudo`, `code` (Q En QSO, R En RX, S Au shack, A Absent, O Hors ligne), `age` (s depuis la dernière requête du
  membre), `role` (a / c / m, d'après la liste signée ; station 0.119.0+), `tx_ok` (ajouté par la PASSERELLE quand
  `[safety] enforce_bands` : la fréquence partagée `f` est-elle dans les `[[bands]]` de cette station ? indication
  seulement, l'émission reste jugée à l'instant ; 0.119.0+), et sauf hors ligne : `sd` (début du statut, absent si masqué), `lt` (dernière émission), `su` (fin de la
  plage « Au shack »), `lv` (f / o / x), `f` et `m` (si f), `x` (si x), `updated` (s depuis l'état reçu).
  Vue de plus de 48 ko : `truncated: true`, membres réduits (le client demande chaque groupe avec `g`).
- **Avis** `{"type": "module", "module": "presence", "data": {"kind": "friends_changed", "scope": "operators"}}` :
  la vue a changé ; le client redemande `view` (le message reste petit quel que soit le nombre de membres).
- **Page web** (station 0.119.0+, `friends.js`, rubrique « Amis ») : vue relue à la connexion, sur l'avis et toutes les
  30 s quand la rubrique est là ; affichage au choix (dans les rubriques, en grand, fenêtre détachée Document
  Picture-in-Picture là où elle existe).
- **Application** (0.60.0+, `logic/Friends.kt`, `app/FriendsViews.kt`) : mêmes règles et mêmes textes que la page.
- **QSY vers un ami** (page 0.119.0, application 0.60.0) : confirmation de l'opérateur avec l'âge de l'information ; refusé pendant toute
  émission ; `friends` `qsy_mark`, puis `set_mode` et `set_frequency` habituels ; « Retour » = `qsy_back` puis les
  mêmes commandes. Jamais d'émission.

## 17. FreeDV RADE V1 en réception (station 0.122.0+, fonction `freedv`)

Lot F1 du cahier des charges FreeDV. Fonction annoncée dans `hello.features` (`freedv`) quand `[freedv] enabled = true`.
La station décode elle-même (freedv-ka9q pour la voix et l'indicatif, radae_rx de rade_c pour la synchro et le SNR) ;
les clients ne décodent rien.

- **Mode FreeDV** : `freedv_set {on}` (OPÉRATEURS ; refusé pendant toute émission, de la station ou au micro du poste).
  En mode FreeDV, TOUS les clients, visiteurs compris, entendent la voix décodée à la place du son du poste, et du
  silence hors synchro (la synchro RADE tient lieu de squelch). Le mode n'est pas gardé au redémarrage de la station.
  Il ne change rien au poste (fréquence, mode) : FreeDV se reçoit en BLU supérieure (USB ou PKTUSB).
- **`state.freedv`** (et `hello.freedv`) : `on`, `engine` (`demarrage`, `ecoute`, `relance`, `panne`, `arret`), `sync`
  (`search`, `candidate`, `sync`), `confirmed` (synchro tenue au moins 2 s : n'afficher « voix » que là, les fausses
  synchros du bruit durent environ 1 s), `snr_db` et `foff_hz` (en synchro seulement ; le SNR estimé par RADE est
  2 à 3 dB sous le vrai en évanouissements), `restarts`, `cause` (dernière panne du moteur), `fault` (cause de
  l'abandon : le mode a été quitté tout seul après les relances ; effacée à la prochaine mise en route), `calls` (10
  derniers indicatifs, le plus récent en tête : `callsign`, `snr_db`, `t`), `sequences` (10 dernières séquences de
  voix : `start`, `duration_s`, `note`, `detail`, `callsigns`).
- **Note d'une séquence** (1 à 5) : SNR médian pendant la synchro (5 dès +6 dB, 4 dès +3, 3 dès 0, 2 dès -3), une
  étoile de moins si la synchro tient moins de 80 % du temps (deux sous 50 %) ou se perd plus de 3 fois par minute,
  2 au plus sous 3 s. La station n'enregistre JAMAIS la voix décodée.
- **Pannes** : un décodeur arrêté, gelé ou introuvable est relancé (1, 2, 5, 10 puis 30 s) ; au-delà de 5 relances en
  10 minutes, le mode est quitté (`freedv_event` `fault`, `state.freedv.fault`), jusqu'à une nouvelle demande.
- Exemples : `state_freedv`, `freedv_event`, `freedv_set_result` de [`tests/protocol/messages.json`](../tests/protocol/messages.json).
- **Activité FreeDV** (station 0.125.0+, module `freedv_activity` de `[modules] run`, désactivé par défaut) : la station lit
  FreeDV Reporter (qso.freedv.org) en OBSERVATEUR (rôle « view » : rien n'est envoyé) et publie toutes les 10 s, à TOUS les
  clients (visiteurs compris), un message de module (`type: "module"`, `module: "freedv_activity"`) dont `data` vaut :
  `kind: "freedv_activity"`, `retain: "snapshot"`, `status` (`ok`, `connexion`, `erreur`), `message` (cause lisible de
  l'erreur), `total` (stations connectées au service), `locator` (booléen : `[freedv] locator` réglé, donc distances
  présentes), `t` (heure Unix de l'envoi : au-delà de 60 s sans nouveau message, la liste est périmée), `freqs` (20 au
  plus, la plus prometteuse en tête ; activité HF 1,8 à 29,7 MHz par pas de 500 Hz) : `f` (Hz), `note` (chance de
  réception ici, RADE V1 seulement : émetteur en cours 2, récent 1, × 0,4 au-delà de 3 000 km ou distance inconnue ;
  voisin à moins de 1 500 km qui décode à 3 dB ou plus : +2, +3 sous 800 km), `tx` (8 au plus, ceux qui émettent en
  tête : `c` indicatif, `km` ou `null`, `on` émet en ce moment, `min` minutes depuis la dernière émission (15 au plus) ou
  `null`, `m` mode FreeDV, `RADEV1` ou autre), `rx` (6 au plus, les plus proches en tête : `c`, `km`, `snr` en dB, `m`).
  Le QSY d'un OPÉRATEUR vers une ligne est immédiat et passe par les commandes habituelles : `set_mode` `USB` si le
  poste n'est ni en USB ni en PKTUSB, puis `set_frequency` (refusés pendant l'émission). Exemple : `module_freedv_activity`.
