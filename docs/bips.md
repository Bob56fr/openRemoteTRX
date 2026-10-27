# Bips de fin d'émission (étape 32)

Deux bips produits **par la station** et **émis** juste avant le retour en
réception. Les deux sont désactivés par défaut. Ils se règlent depuis la page
(onglet **Audio**), et le réglage vaut pour tous les appareils : il est gardé
par la station dans `<state_dir>/beeps.json`.

## Roger bip

Émis quand **vous relâchez le PTT vous-même** (vous êtes le propriétaire de
l'émission).

- Tonalité : 600, 800, 1000, 1500, 2000, 2500 Hz, ou « deux tons montants »
  (1000 puis 1500 Hz).
- Motif : 1, 2 ou 3 bips (bip de 100 ms, silence de 60 ms entre deux).
- Bouton « Écouter » : joué sur le téléphone seulement, jamais émis.

## Bip de liaison perdue

Émis quand la station coupe parce que **votre terminal ne répond plus** pendant
votre émission (signal de vie absent depuis 2 s, ou connexion fermée). Il
prévient les autres stations que la coupure n'est pas volontaire. Le motif est
fixe : trois tons descendants (1200, 900, 600 Hz ; 0,44 s), distinct de tout
roger bip.

C'est une **exception assumée** à la règle « retour en réception immédiat si la
connexion tombe » (décision de l'utilisateur, 2026-10-27). C'est une émission
automatique, de 0,4 s environ, faite sous la responsabilité du titulaire. La
page demande une confirmation à l'activation.

## Bornes imposées par le code, quels que soient les réglages

| Règle | Valeur |
| --- | --- |
| Durée du son | 0,6 s au plus (`MAX_TAIL_S`), tronquée au-delà |
| Attente avant « PTT off » | 1,2 s au plus (`TAIL_MAX_WAIT_S`) : un bip qui traîne ou plante n'empêche jamais la coupure |
| Niveau | -15 dBFS + gain d'émission (`[audio] tx_gain_db`), plafonné à -10 dBFS |
| Fondus | 5 ms en début et en fin de chaque ton (pas de claquement, donc pas d'éclaboussure de spectre) |
| Micro du client | fermé, et son reste jeté, AVANT le bip |
| Déclenchement | seulement depuis une émission CONFIRMÉE ; jamais une nouvelle prise d'émission |

## Jamais de bip sur ces coupures

TOT, STOP, coupure par un autre client, liaison CAT perdue, poste muet,
fréquence ou mode changés pendant l'émission, poste revenu en réception de
lui-même, défaut, superviseur, arrêt de la station. Dans tous ces cas, la
coupure est immédiate, comme avant.

Si l'une de ces coupures arrive **pendant** un bip (par exemple STOP), le bip
s'arrête net : plus rien n'est écrit et ce qui attendait dans le tampon de la
carte son est jeté. La coupure part aussitôt.

Pendant le bip, l'état affiché est « UNKEYING » (affiché comme une émission),
et l'accord ainsi que les réglages restent refusés.

## Protocole

- `hello.beeps` : réglages (`roger_enabled`, `roger_tone`, `roger_pattern`,
  `link_lost_enabled`), séquences `[Hz, ms]` pour l'écoute (`roger_sequence`,
  `link_lost_sequence`), listes `tones` et `patterns` ; `null` si la station
  n'a pas de bips.
- `beeps_set` avec un ou plusieurs de ces réglages (liste FERMÉE, vérifiée par
  le protocole) ; réponse avec `settings` ; message `{"type": "beeps",
  "settings": …}` diffusé à tous les clients.
- Refus : `beeps_unavailable`, `beeps_storage_error`.

## Fichiers

`trxstation/gateway/audio/beeps.py` (catalogue, synthèse, réglages, lecteur
cadencé), `trxstation/gateway/safety/ptt.py` (`_end_with_tail`, `_stop_tail`),
tests `tests/test_beeps.py` (dont les tests de panne).

## À valider sur le vrai poste (charge fictive)

Vérifier que le bip passe bien à l'émission (mode données USB-D sur l'IC-7300),
à un niveau d'ALC raisonnable. Vérifier aussi que STOP pendant un roger bip de
3 bips coupe immédiatement, et que le bip de liaison perdue part quand le
téléphone passe en mode avion pendant l'émission.
