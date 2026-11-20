# TOT du poste : rappel à la connexion et essai de qualification

Cahier des charges v2 (étape 322, 2026-11-20 ; relevés du lot TP0 au § 11, étape 324). Aucun code.

## 1. Objet

Le TOT interne du poste (Icom « Time-Out Timer », Yaesu « TX TIME OUT TIMER », Kenwood équivalent) est la
DERNIÈRE barrière quand tout le reste a lâché : passerelle figée, superviseur arrêté, PC planté, câble CAT
coupé pendant une émission. La station le recommande dans le guide et les fiches de poste, mais rien ne
prévient l'opérateur qui l'a mis sur OFF.

But : prévenir l'opérateur, juste après la connexion, quand le TOT de SON poste est sur OFF, et seulement
quand on a pu le lire À COUP SÛR.

## 2. Décisions de l'utilisateur (2026-11-20)

1. **Message seulement.** Aucune écriture sur le poste dans ce cahier. Le bouton « activer le TOT à 3 min
   pour moi » est reporté (§ 9), poste par poste, une fois l'écriture prouvée par la qualification.
2. **Lecture « à coup sûr » ou rien** (§ 4). Valeur incertaine = « inconnu » = aucun message dans la page
   ni l'application.
3. **Une fois par jour, par compte opérateur et par station**, retenu par la STATION (la page et
   l'application ne redemandent pas chacune de leur côté). Jamais aux visiteurs.
4. **L'émission n'est PAS bloquée** par un TOT du poste sur OFF : le TOT de la station et le superviseur
   restent la sécurité ; le message est un rappel.
5. **Android Auto et mode conduite** : aucune fenêtre en roulant ; le message attend l'écran du téléphone
   (mode conduite quitté ou prochaine ouverture de l'application) ; le PTT de la voiture reste possible.
6. **TOT illisible** (poste non qualifié pour cette lecture, ou lecture qui échoue) : rien à la connexion ;
   l'opérateur est prévenu à la CONFIGURATION du poste (assistant, menu 2.5, guide) qu'il doit régler le TOT
   de son poste sérieusement (§ 6).
7. **Essai de qualification** du TOT du poste, selon les capacités du poste (§ 7) : il relève les valeurs
   que le poste sait donner et vérifie que le poste coupe bien de lui-même.
8. **Conflit avec l'opérateur présent** (étape 206 : émission locale tolérée jusqu'à `local_tx_max_s`,
   300 s) : sans écriture, l'opérateur choisit lui-même la valeur de son poste ; la question reviendra avec
   le bouton d'écriture (§ 9), qui sera une option de TRX Console pour les postes qui savent le faire.

## 3. Constat Hamlib (2026-11-20)

- Aucun paramètre commun pour le TOT d'émission (`RIG_PARM_*` de `rig.h` : APO, BEEP, TIME, BACKLIGHT,
  AFIF… mais pas de TOT).
- Le seul « TOT » du code Yaesu (`newcat.c`, `ftdx10.h`) est le CAT TIME OUT TIMER (délai de la liaison),
  pas la minuterie d'émission ; ticket ouvert Hamlib #1236 « Yaesu TOT value restore » (2023) sur ce sujet.
- Demande à Hamlib : brouillon en anglais donné à l'utilisateur (paramètre `TXTOT`, entier en secondes,
  0 = arrêt, valeurs permises dans les capacités) ; ticket GitHub à ouvrir par l'utilisateur.
- Conséquence : lecture par COMMANDE BRUTE passée par rigctld (`w` / `send_cmd`), au format pris dans une
  TABLE DE DONNÉES par modèle (pas de code par modèle) ; second port CI-V possible chez Icom en repli. Le jour
  où Hamlib aura un paramètre, la station le préfère et garde la commande brute pour les anciennes versions.

## 4. Lecture « à coup sûr »

Une valeur n'est retenue que si TOUT est vrai :

1. Le modèle Hamlib a une entrée dans la table de la station (`trxstation/rigtot.toml`, données : commande de
   lecture, motif de la réponse, correspondance code -> minutes, valeur « arrêt »), marquée validée par une
   qualification réussie (§ 7). La fiche publique `docs/postes/donnees/<poste>.toml` porte le même état ; un
   test vérifie la cohérence des deux.
2. Le poste vient de répondre à une autre lecture (fréquence) juste avant.
3. La réponse correspond EXACTEMENT au motif attendu et à une valeur de la table.
4. Deux lectures successives donnent la même valeur.

Sinon : « inconnu ». Une réponse vide, un délai dépassé, un refus (RPRT), un « ?; » Yaesu ou un 0 renvoyé
par Hamlib faute de réponse ne valent JAMAIS « arrêt » (piège de l'étape 287 : chez Yaesu, Hamlib répond 0
quand le poste est muet).

Quand : à la connexion d'un OPÉRATEUR, poste en réception, hors émission locale, au plus une fois par
connexion ; jamais pendant une émission, jamais pour un visiteur. La commande brute est dans une liste fermée
(une lecture par modèle, aucune écriture), jamais fournie par un client.

## 5. Message à la connexion (page et application)

Condition : TOT lu « arrêt » à coup sûr, et ce compte ne l'a pas déjà vu aujourd'hui sur cette station.

Contenu (texte de sécurité, 4 langues, relu par l'utilisateur) :

- Titre : « Le TOT de votre poste est désactivé ».
- Texte : le TOT du poste est la dernière sécurité si la station, le réseau ou le PC tombent pendant une
  émission ; sans lui le poste peut rester en émission jusqu'à une intervention sur place ; régler
  « Time-Out Timer » / « TX TIME OUT TIMER » dans le menu du poste (3 min conseillé).
- Deux boutons :
  - « J'ai compris, je continue » : message noté vu pour la journée (`rig_tot_ack`) ;
  - « Quitter » : déconnexion (page : retour à l'écran de connexion ; application : déconnexion).

La journée est la date locale de la station. Un TOT réglé ensuite (relu à une prochaine connexion) efface
l'avertissement. Le message s'affiche après les éventuelles fenêtres d'allumage du poste (P2 / P3).

## 6. TOT inconnu : prévenir à la configuration

- `trx-setup` (assistant complet et partie 2.5 « poste et liaison CAT ») : après le test de liaison, si le
  modèle n'a pas de lecture validée, une étape d'information : « Réglez le TOT (minuterie d'émission) de
  votre poste : c'est la dernière sécurité en cas de panne de la station » avec le nom du menu quand
  `rig_hints.py` le connaît ; si la lecture est validée, la valeur lue est montrée (et l'avertissement si
  arrêt).
- Guide de l'opérateur : la règle déjà écrite (partie 1, récapitulatif) devient une case à cocher en tête.
- trx-monitor et tableau de bord 1.3 : ligne « TOT du poste : 3 min / ARRÊT / inconnu ».

## 7. Essai de qualification « TOT du poste »

Dans la valise (`trx-qualif --terrain`) et le plan de qualification, seulement si le poste DÉCLARE un TOT
(fiche ou question à l'opérateur). Station ARRÊTÉE par la valise (le TOT de la station couperait avant :
120 s au plus contre 3 min au minimum chez Icom), rigctld de la valise, poste sur CHARGE FICTIVE (mot
CHARGE), puissance au minimum.

Partie A, valeurs lisibles (sans émission) :

1. Lecture de la valeur actuelle (format candidat de la table).
2. L'opérateur parcourt lui-même les valeurs du menu du poste (OFF, 3, 5, 10…) ; à chaque valeur, la valise
   lit et demande « Le poste affiche-t-il … ? » : on mémorise la liste des valeurs que le poste sait donner
   et la correspondance code -> minutes, confirmées par l'opérateur.
3. Poste éteint ou câble CAT retiré : la lecture doit donner « inconnu », jamais « arrêt ».

Partie B, coupure par le poste (avec émission, mot EMETTRE) :

1. L'opérateur règle la PLUS PETITE valeur du poste (Icom 3 min, FTDX10 1 min).
2. Émission en USB ou LSB SANS AUDIO (porte du son fermée, opérateur silencieux) : pas de puissance de sortie
   en BLU sans modulation ; l'opérateur garde un œil sur le poste.
3. La valise lit le PTT et la puissance chaque seconde, chronomètre, et a sa propre limite : valeur du TOT +
   30 s, puis « T 0 » relu (essai en échec si le poste n'a pas coupé).
4. Relevé : durée réelle avant la coupure, bip ou alerte du poste, PTT lu par la CAT APRÈS la coupure par le
   poste (s'il reste à 1, la station croirait le poste encore en émission : constat à traiter), le poste
   reprend-il une émission tant que la commande PTT reste active ? « T 0 » puis « T 1 » relance-t-il ?
5. L'opérateur remet sa valeur (3 min conseillé) ; la valise relit.

Résultat dans le rapport et la fiche : `tot_poste = { lecture = "validee" | "non", valeurs = [...],
coupure = "verifiee" | "non", duree_s, ptt_apres }`. Un essai à la main existe pour un poste sans lecture
(partie B seule, valeur donnée par l'opérateur).

Station : une coupure faite par le poste pendant une émission à distance (station figée puis revenue, ou
émission locale) doit être reconnue (PTT retombé sans commande) et décrite comme « coupure par le poste »,
jamais comptée comme une panne ni déclencher l'échelle de reprise : vérifié par un test de panne avec le
modèle factice.

## 8. Protocole (esquisse, figée au lot TP1)

- `hello.features` : `rig_tot`.
- `state.rig.tot` : `{ "state": "on" | "off" | "unknown", "minutes": 3 }` (opérateurs seulement).
- Message `rig_tot_warning` envoyé une fois à la connexion quand le § 5 s'applique.
- Commande `rig_tot_ack` (opérateurs) : vu pour la journée ; `state_dir/rig_tot_ack.json` (compte -> date).
- `docs/protocole.md`, `tests/protocol/`, `docs/parite-web-android.md`.

## 9. Plus tard : écriture « activer pour moi »

Reportée (décision 1). Quand elle viendra : option de TRX Console (thème 3), hors service par défaut,
seulement pour un modèle dont l'ÉCRITURE est validée par la qualification ; une seule valeur (3 min, ou la plus
petite du poste au-dessus) ; écriture puis relecture avant tout « OK » ; refusée pendant toute émission ;
conflit avec `local_tx_max_s` (300 s) à expliquer dans la console.

## 10. Lots

| Lot | Contenu |
|---|---|
| TP0 | Relevé des formats sur l'IC-7300MK2 (CI-V `1A 05` par `w` de rigctld, puis second port) et le FTDX10 (`EX`) : OFF, une valeur, poste muet ; parties A et B du § 7 à la main |
| TP1 | Station : table `rigtot.toml`, lecture à la connexion, `state.rig.tot`, `rig_tot_warning`, `rig_tot_ack`, coupure par le poste reconnue (test de panne), trx-setup / 2.5, trx-monitor, codes ORT, fiches des postes |
| TP2 | Page : fenêtre, textes 4 langues |
| TP3 | Application : fenêtre, attente hors conduite, textes 4 langues |
| TP4 | Valise : essai « TOT du poste » (§ 7), rapport, fiches |

Textes de sécurité en 4 langues : relus par l'utilisateur avant livraison.

## 11. Lot TP0 : relevés (2026-11-20)

### 11.1 Icom IC-7300MK2 (PC Windows, COM8, adresse CI-V B6h, Hamlib 4.7.2) : RÉUSSI

- Commande (manuel CI-V, « SET > Function ») : `1A 05 00 32`, données 00 = OFF, 01 = 3 min, 02 = 5 min,
  03 = 10 min, 04 = 20 min, 05 = 30 min. Le manuel précise : **valable seulement pour une émission lancée par
  une commande CI-V ou la touche TRANSMIT** (donc pas pour le PTT du micro ni, à vérifier, pour un PTT par
  les lignes RTS / DTR « USB SEND » : la station ne doit annoncer le TOT du poste comme une sécurité que si
  sa méthode PTT est CAT).
- Lecture directe (port série) : trame `FE FE B6 E0 1A 05 00 32 FD`, écho puis réponse
  `FE FE E0 B6 1A 05 00 32 xx FD` en 50 à 65 ms.
- Lecture par rigctld (chemin de la station) : `W \0xFE\0xFE\0xB6\0xE0\0x1A\0x05\0x00\0x32\0xFD 19`
  (19 octets = écho de 9 + réponse de 10) ; rigctld rend les octets sous la forme `\0xFE\0xFE…` ; avec
  `0xFD` comme fin de réponse, rigctld s'arrête sur l'ÉCHO (réponse vide) : lire un nombre d'octets et
  chercher la trame adressée au contrôleur (E0 <- B6), jamais prendre la première. `\send_raw` : RPRT -5.
  Le nombre 19 suppose l'écho CI-V en marche (réglage du poste) : TP1 doit gérer l'écho absent (10 octets).
- Partie A : OFF puis 3, 5, 10, 20, 30, 3 min choisis au menu par l'opérateur, chaque valeur lue juste en
  moins de 6 s, aucun écart avec l'afficheur ; poste ÉTEINT : délai dépassé = « inconnu », jamais OFF ;
  rallumé : 3 min relu.
- Partie B (charge fictive, USB sans audio, puissance mesurée 0, émission par `T 1` de rigctld) : le poste
  coupe SEUL à **180,0 s** (TOT 3 min), PTT lu par Hamlib (`t`) ET état TX CI-V (`1C 00`) retombés à 0 dans la
  même seconde ; aucune reprise seule pendant 15 s ; une nouvelle prise `T 1` est acceptée normalement.
  Conséquence pour la station : la coupure par le poste se VOIT par la lecture du PTT (pas de PTT figé à 1).
- Le poste de l'utilisateur était sur OFF au départ ; laissé sur 3 min.

### 11.2 Yaesu FTDX10 : À FAIRE (poste absent)

- D'après le manuel CAT (2308-F, table 2) : menu 03 OPERATION SETTING / 01 GENERAL / 16 TX TIME OUT TIMER,
  P4 = 00 (OFF) à 30 (min), 2 chiffres : lecture `EX030116;`, réponse attendue `EX030116xx;`.
- À vérifier : réponse par la commande brute de rigctld (`w EX030116;`), poste muet (« ?; » ou rien), et
  partie B avec la valeur 1 min.
