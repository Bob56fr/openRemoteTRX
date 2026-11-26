# Laboratoire CW : manipulation Morse à l'écran tactile (cahier des charges v3)

Branche d'essai `exp/cw` (dossier `C:\dev\openRemoteTRX-cw`). Version d'essai `X.Y.Z.devN+cw`, aucun numéro d'étape.
Rédigé le 2026-11-26 d'après le cahier v1 de l'utilisateur et les décisions prises le même jour (§ 2).
v3 (même jour) : CW seulement dans l'application Android, jamais dans la page web (décision 5) ; règle d'envoi du
client corrigée d'après le banc du lot CW-0 (§ 5.1) ; résultats du banc (§ 14).
Journal de la branche : `docs/exp-cw/journal.md`.

## 1. But et nature de la branche

Permettre la manipulation CW depuis l'écran tactile, avec un timing propre malgré la gigue du réseau (4G, VPN).
C'est une PREUVE DE CONCEPT : on code le minimum pour savoir si l'idée tient sur l'air, puis on décide
(§ 11). Abandon = branche supprimée, aucune trace dans `main` sauf un résumé du journal dans `docs/boite-a-idees.md`.
Adoption = fusion dans `main` en UNE étape, avec l'exception de sécurité inscrite dans CLAUDE.md (§ 3).

Hors du POC (après adoption seulement) : mode B, mode D, full break-in, télémétrie partagée.
Jamais : manipulation CW depuis la page web (décision 5), Android Auto, mode conduite.

## 2. Décisions (2026-11-26)

1. **Exception à la règle « PTT en toggle uniquement »**, limitée à la manipulation CW armée (§ 3).
2. **PTT tenu pendant l'armement** en mode A (variante V1, défaut) ; le semi break-in par prises successives
   (variante V2) est mesuré dans le POC, pas imposé.
3. **Canal `cw` sans retransmission** avec redondance, et sécurité par **bail** (§ 5), à la place du battement
   à 20 ms sur un canal fiable.
4. **Ordre** : moteur et banc de simulation, mode A dans la passerelle, page web, essai réel, puis mode C.
   Mode B : note de faisabilité seulement. Mode D : abandonné (intérêt faible, dissimulation des pertes d'aiortc
   non maîtrisable).
5. **Écran tactile Android seulement** (tablette ou smartphone, décision de l'utilisateur du 2026-11-26) : la page
   web ne manipule JAMAIS en CW (ni bouton « Armer CW », ni canal `cw`). Client du POC = application Android.

## 3. Exception de sécurité (texte à inscrire dans CLAUDE.md À L'ADOPTION)

> MANIPULATION CW (décision de l'utilisateur, 2026-11-26, branche `exp/cw`) : « Armer CW » est une prise d'émission
> NORMALE du client (mêmes refus que toggle, verrou mono-client, battements 500 ms / 2 s, TOT, opérateur sur place,
> bandes vérifiées sur la fréquence PORTEUSE réelle). Pendant l'armement, seule la manipulation suit le doigt :
> la porte audio ne laisse passer que la tonalité CW recréée par la station, jamais le micro ; appui continu
> limité à `max_keydown_ms` (2 s, plafond 5 s) ; bail du rejeu dépassé, désarmement, coupure de connexion,
> STOP ou toute coupure existante = tonalité coupée net puis « T 0 ». Désactivé par défaut (`[cw] enabled = false`).
> Seulement depuis l'écran tactile de l'application Android ; jamais depuis la page web, Android Auto ni le mode
> conduite.

Tant que la branche n'est pas adoptée, cette exception ne vaut QUE dans la branche, essais sur charge fictive.

## 4. Mode A (seul mode codé dans le POC, puis C)

- La station recrée une sinusoïde (défaut 700 Hz, 300 à 1 200 Hz) aux fronts en cosinus surélevé (5 ms, 3 à 8 ms)
  et l'injecte dans la sortie audio d'émission déjà utilisée par la passerelle. Émission J2A.
- **Rendu à l'échantillon près DANS le flux de sortie** (position en échantillons depuis l'ancre), jamais par
  minuterie asyncio : précision indépendante de la résolution des minuteries (16 ms sous Windows). Mode A donc
  permis sous Windows et Linux.
- Micro et tonalité exclusifs : armer CW ferme la porte du micro (`gateway/audio/gate.py`) ; le limiteur final reste.
- **Mode du poste exigé** : `[cw] data_mode` (ex. PKTUSB) doit être un mode de `tx_modes` et le mode courant ;
  sinon refus `cw_mode` avec le mode attendu. La station ne change JAMAIS le mode elle-même.
- **Fréquence porteuse** = fréquence affichée + tonalité en USB (- en LSB). Affichée au client. Les bandes sont
  vérifiées sur la porteuse ET sur la fréquence affichée (les deux dans `[[bands]]`, sinon refus `out_of_band`).
  Option « caler la porteuse » : QSY de la station de -f_tonalité AVANT l'armement seulement (commande
  attendue par `LocalPresence.expect`, refusée pendant l'émission comme tout QSY).
- Aide affichée : niveau USB MOD bas, ALC à zéro, compresseur coupé, moniteur d'émission du poste coupé.

## 5. Transport, rejeu et bail

### 5.1 Canal

- Canal de données `cw` ouvert par le client (`ordered: false`, `maxRetransmits: 0`), comme `spectrum` ; annoncé
  par `hello.features` (`cw`). Commandes d'état (armer, désarmer, réglages) sur le canal `control` existant.
- Chaque paquet porte la FENÊTRE des fronts récents (les fronts des 500 dernières ms de la séquence, au plus 32),
  plus le bail courant. La station élimine les doublons par `id` : une perte isolée ne coûte rien, aucun blocage
  en tête de file.
- Paquet à chaque front et toutes les 20 ms PENDANT TOUTE LA SÉQUENCE (clé fermée ou ouverte), puis toutes les
  200 ms en silence armé. (v2 : 20 ms seulement clé fermée ; le banc CW-0 a montré qu'un front d'ouverture perdu
  n'était alors répété qu'au front suivant, 60 à 420 ms plus tard à 20 mots/min : élément allongé ou coupure de
  bail. Débit : 50 paquets de ~100 octets par seconde, négligeable.)
- Le client ne garantit l'état de la clé que jusqu'à « maintenant » : `lease` = heure d'envoi du paquet (sert aussi
  à mesurer la gigue).

### 5.2 Messages (forme de `docs/protocole.md`, clé `type`)

Client -> station, canal `control` :
```json
{"type":"cw_arm","mode":"A","wpm":20,"tone_hz":700,"delay_ms":300}
{"type":"cw_disarm"}
```
Client -> station, canal `cw` :
```json
{"type":"cw","seq":3,"edges":[[41,1,1532],[42,0,1592]],"lease":1610}
```
`edges` = `[id, état 1/0, ts]`, `ts` en ms depuis le début de la séquence, horloge monotone du téléphone, heure du
TOUCHER (keyer compris, il tourne sur le client) ; `lease` = jusqu'où (ts) le client garantit l'état de la clé.

Station -> client :
```json
{"type":"cw_state","state":"armed|playing|idle|fault","seq":3,"buffer_ms":280,"late":0,"carrier_hz":7030700}
{"type":"cw_fault","seq":3,"reason":"lease_expired"}
{"type":"cw_stats","seq":3,"jitter_p95_ms":64,"late":0,"lease_cuts":0,"max_timing_err_ms":0.1}
```

### 5.3 Ordonnanceur

- Ancre = heure d'arrivée du premier paquet de la séquence + `delay_ms` ; un front se joue à `ancre + ts`.
- `delay_ms` : fixe (150 à 500 ms) ou adaptatif ENTRE séquences (p95 de la gigue mesurée + 50 ms, bornes de
  `station.toml`), jamais au milieu d'une séquence.
- Front de FERMETURE de la clé (début de tonalité) en retard : ré-ancrage (la suite est décalée), compté `late`.
  Front d'ouverture (fin de tonalité) en retard : joué tout de suite, compté `late` (allongement borné par le bail).
- **Bail** : la tonalité ne joue que tant que le rejeu n'a pas dépassé `lease + lease_grace_ms` (défaut 60 ms).
  Bail dépassé = fermeture immédiate avec front adouci, séquence abandonnée, `cw_fault lease_expired`.
  Cette règle remplace « battement 150 ms », « cw_up en retard » et « late_abort » du v1.
- Délai de coupure garanti, en temps de rejeu : ≤ `lease_grace_ms` + 20 ms après le dernier instant couvert
  par un bail. En temps réel après une perte de lien, la coupure arrive au plus `delay_ms + lease_grace_ms` plus tard
  (le critère « 200 ms après la perte du lien » du v1 était impossible avec un rejeu de 300 ms).
- Fin de séquence : silence > `seq_gap_ms` (défaut 1 500 ms) ; la suivante est ré-ancrée.

### 5.4 PTT (variantes mesurées)

- **V1 (défaut)** : PTT pris par `cw_arm` (chemin normal du PttController, `reserve` comme la mesure de TOS) et
  tenu jusqu'au désarmement. Désarmement automatique après `idle_disarm_s` (défaut 8 s) sans manipulation,
  pour rendre l'écoute. Simple et sans rafales de « T 1 ».
- **V2 (essai)** : PTT relâché après `hang_ms` (600 ms) de silence, repris au front suivant par le chemin normal
  (refus compris) ; le délai de prise s'ajoute au ré-ancrage. L'anti-rebond `rekey_cooldown_s` (1 s) n'est PAS
  baissé pour la CW : une reprise dans la seconde attend. On mesure si V2 reste utilisable.

## 6. Écoute pendant la manipulation

- Tonalité locale de l'application au toucher (sortie à faible latence : AAudio / Oboe, enveloppe programmée,
  but < 30 ms du toucher au son) ; latence mesurée affichée. L'audio reçu n'est jamais le retour de manipulation.
- V1 : réception muette pendant l'armement (PTT tenu). V2 : atténuation du son reçu (-20 dB, réglable jusqu'au
  silence) jusqu'à « rejeu + latence réseau mesurée + tampon » après la fin de la séquence.

## 7. Application Android (seul client du POC, décision 5)

- ONGLET « CW » DÉDIÉ (demande de l'utilisateur du 2026-11-26 ; maquette
  https://claude.ai/artifact/NSXTCo2XT6RbHpxLVBt2pt, smartphone 2 palettes / 1 palette, tablette en paysage) :
  EN HAUT une synthèse du poste (fréquence porteuse et affichée, mode, état RX / TX, PWR, Po, ALC, TOS, S-mètre en
  réception, TOT restant) ; au milieu les commandes habituelles de la CW (vitesse, poids, tonalité, retour local,
  manipulateur, inversion point / trait, caler la porteuse, texte décodé de sa propre manipulation, état du rejeu) ;
  EN BAS le manipulateur tactile avec, juste au-dessus, le SÉLECTEUR « 1 palette » (pioche) / « 2 palettes »
  (iambique A, B, simple levier) et « Armer CW » ; STOP toujours visible ; le PTT de l'application est remplacé
  par « Armer CW » dans cet onglet. Onglet présent seulement si `hello.features` contient `cw`.
- Bouton « Armer CW » (prise d'émission, affiche l'état renvoyé), zones tactiles inactives tant que non armé.
- Interfaces : pioche, iambique A, iambique B, simple levier ; vitesse 5 à 40 mots/min, poids ; inversion
  point / trait ; zones tactiles seulement (multitouche pour l'iambique).
- Rejet de la paume (contact trop large ou hors zone), vibration au toucher.
- Affichage : fréquence porteuse, état du tampon, gigue, `late`, coupures de bail, caractères décodés de sa propre
  manipulation (aide et diagnostic).
- STOP existant toujours visible et toujours actif. Écran CW fermé et désarmé en mode conduite et en Android Auto.
- Keyer et paquets dans `:logic` (sans appel Android : `:logic` est aussi compilé par openRemoteTRX Lite) ; vecteurs
  communs avec le banc Python (même manipulateur, mêmes paquets).
- Textes en quatre langues dès le POC (`app.<langue>.json`, règle du dépôt).
- La page web n'a RIEN de CW (ni affichage, ni canal) ; sa liste de commandes ne change pas.

## 8. Mode C (après l'essai réel du mode A)

- Texte et macros (`{MYCALL}`, `{CALL}`, `{RST}`) vers le keyer du poste (`\send_morse`, vitesse par KEYSPD,
  `\stop_morse` au STOP puis « T 0 »).
- PRÉALABLE : le poste passe en émission de lui-même (break-in) : le PttController doit le RÉSERVER comme sa
  propre émission, sinon superviseur et `local.py` y voient une émission locale (PTT à distance bloqué 2 min)
  ou un TX sans client. À essayer d'abord sur l'IC-7300MK2 en CW, sur charge fictive.

## 9. Mode B : note de faisabilité seulement

Piste : ligne DTR du **second port** (`-if02`, déjà ouvert par la passerelle pour le spectre), si le menu
« USB Keying (CW) » de l'IC-7300MK2 accepte ce port. Hamlib n'a pas de commande de manipulation. Même préalable
que le mode C (émission non commandée par « T 1 »). Précision à mesurer sous Linux et Windows. Rien de codé.

## 10. Configuration `[cw]` (branche seulement)

```toml
[cw]
enabled = false            # désactivé par défaut
modes = ["A"]              # A, puis C
data_mode = "PKTUSB"       # mode du poste exigé pour le mode A
tone_hz = 700
edge_ms = 5
delay_ms = 300             # ou "adaptive"
delay_min_ms = 150
delay_max_ms = 500
lease_grace_ms = 60
max_keydown_ms = 2000      # plafond 5000
seq_gap_ms = 1500
ptt_variant = "hold"       # "hold" (V1) ou "hang" (V2)
idle_disarm_s = 8
hang_ms = 600
```
Validée par `config.py` (bornes, `data_mode` dans `tx_modes`). Notice de station.toml et sections existantes
conservées à l'adoption seulement.

## 11. Lots du POC et décision

| Lot | Contenu | Matériel |
|---|---|---|
| CW-0 | FAIT (2026-11-26, § 14) : ordonnanceur + bail + générateur de tonalité en calculs purs ; banc pytest (gigue 0 à 200 ms, pertes 0 à 10 %, réordonnancement, coupures), analyse du son produit (durées, fronts, clics) | aucun |
| CW-1 | Mode A dans la passerelle (`cw_arm` / `cw_disarm`, canal `cw`, porte audio, PttController), tests de panne (bail, connexion, gel de la passerelle, superviseur, STOP, TOT, QSY refusé, hors bande sur la porteuse) ; client d'essai Python (`devtools`) qui rejoue le banc par WebRTC | poste factice Hamlib n° 1 |
| CW-2 | Application Android (§ 7), essai dans l'émulateur puis sur une vraie tablette et le S25 contre une fausse station | aucun |
| CW-3 | Essai réel IC-7300MK2 sur charge fictive : porteuse mesurée, fronts écoutés sur un second récepteur, Wi-Fi puis 4G, V1 puis V2 | IC-7300MK2 |
| CW-4 | Premiers QSO réels (Wi-Fi, 4G), notes de ressenti dans le journal | antenne |
| CW-5 | Mode C (si CW-3 et CW-4 le justifient) | IC-7300MK2 |

**Critères pour ADOPTER** (tous) :
- banc : écart de timing rejoué ≤ 2 ms au p95 avec rejeu 300 ms et gigue jusqu'à 150 ms, aucun élément tronqué
  hors coupure de bail ;
- coupure : ≤ `lease_grace_ms` + 20 ms en temps de rejeu ; tous les tests de panne verts, suite complète verte ;
- essai réel : manipulation lisible par un correspondant (ou un décodeur) à 20 mots/min en Wi-Fi ET en 4G ;
- ressenti de l'utilisateur jugé utilisable sur au moins une interface.

**ABANDON** si l'un de ces points échoue après correction raisonnable, ou si la latence de la tonalité locale
de l'application rend la manipulation inconfortable sans remède.

## 12. Mesures (POC)

Par séquence et par session, dans `<state_dir>/cw/` (JSON) : mode, interface, vitesse, rejeu, gigue (moyenne, p95,
max), `late`, coupures de bail, écart de timing, type de réseau annoncé par le client. Aucun son, aucun texte saisi.
Pas d'envoi : joint au rapport 6.3 à l'adoption. Questionnaire de fin de session : dans le journal pendant le POC.

## 13. Points ouverts

- Réglementation : J2A dans les sous-bandes CW selon la licence française (à vérifier par l'utilisateur ;
  rappel dans l'aide).
- V1 ou V2 par défaut : tranché après CW-3.
- Mode C : comportement réel de `\stop_morse` et du PTT relu pendant le keyer de l'IC-7300MK2.
- Tonalité locale Android : latence réelle du toucher au son sur la tablette et le S25 (AAudio / Oboe, ou
  `AudioTrack` en mode faible latence), à mesurer au lot CW-2.

## 14. Résultats du banc CW-0 (2026-11-26)

Code : `trxstation/cw/` (protocol, tone, player, jitter, sim, analysis), banc `python -m trxstation.devtools.cw_bench`,
tests `tests/test_cw_*.py` (107). Son analysé par le signal analytique (fronts retrouvés à 0,04 échantillon près).
- Critère « ≤ 2 ms au p95, rejeu 300 ms, gigue ≤ 150 ms » : TENU avec marge (écart mesuré < 0,01 ms, de la seule
  quantification à l'échantillon), pertes jusqu'à 20 %, 5 à 40 mots/min ; aucun élément tronqué.
- Gigue UNIFORME : rattrapée par la redondance de la fenêtre même au-delà du rejeu (400 ms de gigue avec 300 ms de
  rejeu : rien de perdu), car un seul des ~25 paquets qui portent un front doit arriver à temps.
- Cas difficile = GELS de liaison façon 4G (paquets retenus puis livrés en rafale), 20 gels par minute : rejeu
  300 ms = rien de perdu jusqu'à 300 ms de gel, coupures de bail propres au-delà ; rejeu 500 ms = jusqu'à 400 ms.
  À mesurer en vrai au lot CW-3 (durée des gels de la 4G de l'utilisateur) avant de régler `delay_ms`.
- Coupure de bail : tonalité arrêtée à `lease_grace_ms` exactement en temps de rejeu, son nul 5 ms plus tard
  (critère ≤ grace + 20 ms tenu) ; jamais de tonalité qui revient après la coupure (rafale retardée ignorée).
- Fronts : cosinus surélevé de 5 ms, 10 -> 90 % en 3,0 ms, aucun saut plus grand que celui de la sinusoïde, énergie
  hors de ± 250 Hz à -51 dB (manipulation brutale : > -40 dB, le test sait voir les clics).
