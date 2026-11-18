# Qualification sur place d'un poste : la « valise de qualification » — cahier des charges v1

Demande de l'utilisateur (2026-11-18) : un membre de l'équipe (le **qualifieur**) se rend chez un opérateur qui n'a
pas de matériel informatique, pour qualifier un poste jamais essayé avec SON PC à lui. Il faut un outil plus
complet que `trx-qualif` (lot Q1, `docs/qualification.md`) qui produise, en une visite, tout ce qu'il faut pour
qu'une conversation Claude ajoute le poste à la liste des postes validés.

Aucun code n'est écrit par ce cahier. Étape 248, station inchangée (0.191.0).

## 1. Décisions

| # | Sujet | Décision | Par |
| --- | --- | --- | --- |
| 1 | Système du PC du qualifieur | Windows ET Debian (mêmes sources ; aucune difficulté propre à l'un, voir § 9) | utilisateur, 2026-11-18 |
| 2 | Rapports bruts | gardés sur le PC du qualifieur, jamais dans un dépôt ; seules les fiches qui en sortent vont dans le dépôt public | utilisateur, 2026-11-18 |
| 3 | Authenticité du rapport | PAS de signature : le qualifieur remet lui-même le zip dans une conversation Claude. Une liste d'empreintes SHA-256 suffit (zip incomplet ou abîmé, fichier retouché à la main par erreur) | cahier (l'utilisateur laisse le choix) |
| 4 | Redémarrage complet du PC pendant la qualification | essai facultatif ; remplacé par défaut par le redémarrage de la station complète, superviseur compris | utilisateur, 2026-11-18 |
| 5 | Lieu de l'outil | `trx-qualif --terrain`, menu 8.3 de TRX Console (console texte, écran plein ET console web en formulaires) ; pas d'application à part | cahier |
| 6 | Qui appuie sur EMETTRE | l'OPÉRATEUR du poste (titulaire de la station), jamais le qualifieur seul ; chaque essai qui émet est confirmé à part | cahier |
| 7 | Liste des postes validés | nouveau fichier `docs/postes/README.md` (tableau) + fiches `docs/postes/<poste>.md` + catalogue `trxstation/qualif/catalogue/<poste>.toml` (format de `sheet.py`) + ligne du README | cahier, à confirmer |

Remarque sur la décision 3 : la signature du lot Q3 visait des rapports envoyés par des inconnus (site WordPress).
Ici le qualifieur est un membre de l'équipe qui parle à Claude : la confiance vient de la conversation, pas du
fichier. Les empreintes protègent seulement contre un transfert raté. Si un jour des rapports arrivent d'ailleurs, le
lot Q3 s'ajoutera sans rien changer au format (champ `signature` réservé dans `qualification.json`).

## 2. But et périmètre

But : en UNE visite d'environ 2 heures, sans réseau Internet obligatoire, obtenir :
- la preuve que les règles de sécurité d'émission tiennent avec ce poste, MESURÉE et horodatée (pas déclarée) ;
- tout ce que Hamlib et le poste font réellement (exploration, qualification Q1) ;
- les réglages qui marchent (port, débit, méthode PTT, carte son, niveaux, modes de données) ;
- un rapport unique, lisible par un humain ET par Claude, d'où sortent sans travail de recherche : la fiche du poste,
  la fiche du guide de l'opérateur, la fiche du catalogue, les aides de `trx-setup`, le brouillon du rapport à
  Hamlib, et un faux poste rejouable pour les tests ;
- le poste de l'opérateur rendu dans l'état où il était.

Hors périmètre : la qualification par l'utilisateur lui-même (lots Q2 à Q4, inchangés), l'application Android
(essayée à part avec le téléphone du qualifieur, § 5.4), l'antenne et l'installation de l'opérateur.

## 3. Rôles et matériel

- **Qualifieur** : membre de l'équipe, son PC (Windows 10/11 ou Debian 12/13), son téléphone avec l'application.
- **Opérateur** : titulaire de la station, présent pendant TOUTE la séance, seul à confirmer chaque émission.
- **Kit** (liste imprimée par `--terrain --preparer`, § 4) : charge fictive (puissance du poste au minimum), câble
  USB du poste ou interface son externe, câbles audio de l'interface si besoin, rallonge / hub USB alimenté, clé
  avec le kit hors ligne.

## 4. Avant de partir : `trx-qualif --terrain --preparer --modele N`

Sur le PC du qualifieur, avec Internet :
1. Vérifie la version de la station (dernière Release) et de Hamlib (la station refuse un Hamlib trop ancien pour ce
   modèle : cas de l'IC-7300MK2 avant 4.7).
2. **Kit hors ligne** dans `terrain/kit/` : zip de la station, installateur Hamlib (Windows) ou paquets (Debian),
   pilotes USB courants (Silicon Labs CP210x, FTDI, WCH CH340) ; rien ne doit manquer s'il n'y a pas de réseau.
3. Cahier de test du modèle (`--plan --modele N`) et constats tirés de `dump_caps` seul (`coherence.py`).
4. **Feuille de visite** (HTML imprimable) : poste, numéro Hamlib, réglages attendus du poste (source de modulation
   USB, niveaux USB, débit CAT, CI-V transceive, TOT interne, VOX coupé) d'après `rig_hints.py` et la fiche si elle
   existe, sinon « à relever » ; liste du kit ; déroulé et durée estimée.
5. Rien n'est écrit dans la configuration de la station du PC.

## 5. Sur place : le déroulé guidé

Une **session** = un dossier `terrain/<poste>-<AAAA-MM-JJ-HHMM>/` sur le PC du qualifieur. Chaque partie est
enregistrée dès qu'elle finit : une session interrompue (PC fermé, câble arraché) REPREND où elle en était
(`--terrain --reprendre`). Chaque partie a un résultat : réussi, échec, ignoré (avec la raison), non fait.

### 5.1 Ouverture et isolation du PC

- La station installée sur le PC (s'il y en a une) est ARRÊTÉE (Windows : `trx-supervisor --stop` ; Debian :
  `systemctl stop trx-remote.target`, sudo une fois) et SA configuration n'est jamais lue ni écrite.
- La session a sa propre `station.toml`, son dossier d'état, ses journaux, ses certificats, ses comptes (un compte
  opérateur « terrain » à mot de passe généré, pour le téléphone). Tout est dans le dossier de session.
- La station de session écoute sur les ports habituels (celle du PC est arrêtée) ; rigctld toujours en 127.0.0.1.
- À la FIN (ou en abandonnant), la station du PC est relancée telle qu'elle était ; un oubli est rattrapé au
  prochain lancement de TRX Console (« une session terrain n'a pas été refermée »).
- Rien n'est installé chez l'opérateur. Rien ne reste sur le PC à part le dossier de session.

### 5.2 Le poste : détection, relevé de départ, configuration

1. Précautions confirmées une par une (charge fictive, puissance minimale, TOT interne, VOX coupé, opérateur présent,
   aucun autre logiciel sur le poste).
2. **Photos des menus du poste AVANT toute modification** : la session les demande menu par menu (liste de la
   feuille de visite) et les range dans `photos/avant/` (déposées depuis le téléphone par la page de la console, ou
   copiées à la main). Elles servent à rendre le poste (§ 5.6) et à écrire la fiche.
3. **Détection** : ports série (identifiant USB, `rig_hints.py`), cartes son, modèle Hamlib proposé ; débit et
   méthode PTT essayés en LECTURE SEULE (assistant `trx-setup`, parties poste et son, dans la configuration de la
   session).
4. **Relevé de départ** par la CAT : tout ce qui est lisible (fréquence, mode, largeur, VFO, split, RIT/XIT,
   fonctions, niveaux, paramètres), deux fois ; c'est la référence de la remise en état.
5. Réglages du poste demandés à l'opérateur d'après la feuille (source USB, niveaux), avec photo APRÈS.

### 5.3 Ce que fait déjà `trx-qualif` (repris tel quel)

1. Exploration sans émission (`--explorer`, étape 175) : constats, brouillons `fiche-poste.md`,
   `rapport-hamlib.md`.
2. Qualification Q1 phases 1 et 2 (sans émission, puis questions à l'opérateur), audio reçu `rx.wav`.
3. Qualification Q1 phase 3 (émission sur charge fictive, étapes de `trx-hwtest`, perte de la CAT pendant
   l'émission) ; filtres seulement si le qualifieur le choisit (`--filtres`, préréglages FIL d'un Icom réécrits).

### 5.4 Essais de sécurité CHRONOMÉTRÉS (le cœur de la valise)

La station de session tourne pour de vrai (passerelle + superviseur). Un **observateur** de la session relit le
poste par rigctld (connexion à part, `cache_timeout=0`, LECTURE SEULE : il n'envoie jamais rien d'autre que des
lectures) toutes les 100 ms et lit le bus d'état ; chaque essai donne des horodatages et un délai mesuré, comparés à
une borne.

Les essais 1 à 6 sont joués par un **client automatique** (le `devtools/fake_client.py` de l'outil, aiortc :
connexion, battements, PTT toggle, STOP) : reproductibles, mesurés, sans dépendre d'un doigt sur un écran. Le client
automatique est un CLIENT ordinaire : toutes les sécurités de la passerelle s'appliquent à lui. Chaque essai qui
émet est annoncé (durée, puissance) et confirmé par l'opérateur (`EMETTRE`, comme `trx-hwtest`).

| # | Essai | Joué par | Mesuré | Borne |
| --- | --- | --- | --- | --- |
| 1 | STOP pendant une émission | client automatique | commande -> réception relue sur le poste | ≤ 0,5 s |
| 2 | TOT : émission sans rien faire, TOT de la session réduit à 20 s (sous le plafond) | client automatique | bip à TOT - 10 s, coupure, écart | ± 1 s |
| 3 | Battements arrêtés (client figé) | client automatique | dernier battement -> réception | ≤ 2,5 s |
| 4 | Connexion coupée net (prise fermée) | client automatique | coupure -> réception | ≤ 1 s |
| 5 | Fréquence hors des bandes, PTT | client automatique | refus, code ORT, PTT jamais vu en émission | 0 émission |
| 6 | Deux clients : le second demande le PTT pendant l'émission du premier | client automatique | refus (verrou mono-client) | 0 prise |
| 7 | STOP TX du tableau de bord (menu 1.3) | qualifieur | touche -> réception | ≤ 0,5 s |
| 8 | Passerelle gelée pendant une émission (`kill -STOP` / suspension du processus sous Windows) | session | gel -> « T 0 » du superviseur -> réception | ≤ TOT absolu du superviseur réglé pour l'essai |
| 9 | Station arrêtée pendant une émission | session | arrêt -> réception | ≤ 2 s |
| 10 | Opérateur sur place : émission au micro du poste | opérateur | émission locale vue, PTT à distance refusé pendant et 2 min après | refus |
| 11 | Démarrage de la station complète, poste allumé | session | PTT relu toutes les 100 ms du lancement à « prête » | jamais en émission |
| 12 | Téléphone : écran verrouillé, puis Wi-Fi coupé, pendant une émission depuis l'application | qualifieur | réception relue | ≤ 2,5 s |
| 13 | FACULTATIF : redémarrage complet du PC, poste allumé | qualifieur | état relu après le redémarrage + journaux du superviseur | jamais en émission (preuve plus faible : aucune mesure pendant l'arrêt du PC) |

Un échec à l'un de ces essais ARRÊTE les émissions de la session (plus aucune émission proposée), le verdict est
`refuse` et la cause est dans le rapport. Les essais 8 et 11 regardent aussi ce que le poste fait seul (certains
postes repassent en émission à la reconnexion USB : à voir).

L'essai 12 ne vise pas le poste mais la chaîne réelle (application, Wi-Fi) ; il reste utile car un défaut là se
voit chez l'opérateur, pas en laboratoire.

### 5.5 Mesures audio et modulation

- **Réception** : niveau moyen, crête et bruit de fond sur la carte son du poste, en mode données et en BLU ; carte
  muette, saturée ou mal choisie détectée (seuils à fixer au lot T3).
- **Émission sur charge fictive** : tonalité 1 kHz par la passerelle, niveau LOGICIEL croissant par paliers de
  2 s (la session ne touche JAMAIS au MICGAIN, au niveau USB MOD ni à la puissance du poste, liste fermée de
  l'exploration), lecture CAT de l'ALC, de la puissance et du TOS à chaque palier ; résultat : niveau logiciel
  conseillé et réglage du poste à conseiller à l'opérateur ; puissance relue avant (refus si elle n'est pas au
  minimum déclaré par l'opérateur). Durée totale sous le TOT de la session.
- **Spectre HF** par le second port, SEULEMENT si le poste en a un (Icom) : ouverture, données reçues, gel pendant
  l'émission, reprise. Sinon « ignoré : pas de second port ».

### 5.6 Remise en état et fermeture

1. Relevé de fin par la CAT, comparé au relevé de départ : différences listées « À REMETTRE À LA MAIN », avec la
   photo du menu concerné ; la session NE réécrit PAS seule ce qu'elle n'a pas changé elle-même.
2. Confirmation de l'opérateur (« poste rendu »), photos APRÈS facultatives.
3. Fabrication du rapport (§ 6), station du PC relancée (§ 5.1).

## 6. Le rapport : `qualif-terrain-<poste>-<date>.zip`

Écrit dans le dossier de session, sur le PC du qualifieur (décision 2). Contenu :

| Fichier | Rôle |
| --- | --- |
| `rapport.html` | lecture humaine : synthèse, verdict, tableau des essais avec délais, points à vérifier, photos |
| `qualification.json` | format FIGÉ (versionné, `format: 1`), source de tout ce que Claude écrit dans le dépôt (§ 7) |
| `LISEZMOI-CLAUDE.md` | court : ce que contient le zip et la procédure d'intégration du § 7 (pour la conversation qui le reçoit) |
| `empreintes.sha256` | empreinte de chaque fichier du zip (décision 3) |
| `explore/` | dossier de l'exploration (constats, brouillons, `dump_caps.txt`, trace CAT) |
| `qualif/` | dossier Q1 (`results.json`, `fiche.toml`, `cat_trace.log`, `rx.wav`, journal) |
| `essais/` | un fichier par essai du § 5.4 (horodatages de l'observateur, événements de la passerelle et du superviseur) |
| `audio/` | mesures du § 5.5, extraits WAV courts |
| `reglages/` | `station.toml` de la session (secrets retirés), relevés de départ et de fin, différences |
| `photos/` | avant / après |
| `jumeau/` | données du faux poste rejouable (§ 8) |
| `journaux/` | journaux JSON de la passerelle et du superviseur de la session |

`qualification.json` contient au moins : versions (station, Hamlib, firmware du poste, système du PC), poste
(fabricant, modèle, numéro Hamlib, backend), liaison (type de port, identifiant USB, débit, méthode PTT, cache),
audio (carte, niveaux conseillés), modes (lus, émis, modes de données), fonctions (exploitées, refusées, instables),
essais (identifiant, joué par, délai mesuré, borne, résultat), constats (gravité, source supposée), remise en état,
verdict proposé et raisons, champ `signature` réservé (vide).

**Données personnelles** : passées par le masquage du monitoring (`monlink/redact.py`) : ni indicatif, ni nom, ni
adresse IP, ni nom de machine ou de compte, ni numéro de série, ni locator. Les PHOTOS ne peuvent pas être masquées
par l'outil : le qualifieur les regarde avant de remettre le zip (indicatif sur une étiquette, plaque du poste). Le
zip part dans une conversation Claude : il est donc envoyé à un service extérieur, l'opérateur en est prévenu à
l'ouverture de la session.

## 7. Côté dépôt : intégration par Claude

Le qualifieur ouvre une conversation dans le dépôt et y donne le zip. Procédure (aussi dans `LISEZMOI-CLAUDE.md`) :
1. Vérifier `empreintes.sha256` (sinon : demander un nouveau zip).
2. `trx-qualif --integrer ZIP` (outil du dépôt, lot T4) écrit des BROUILLONS : `docs/postes/<poste>.md`,
   `User-Guide/fr/postes/<poste>.md`, `trxstation/qualif/catalogue/<poste>.toml`, ligne de `docs/postes/README.md`,
   aides de `rig_hints.py` (proposées, pas appliquées), `docs/hamlib-rapports.md` (ajout), et le faux poste du § 8
   dans `tests/rigs/<poste>/`.
3. Claude relit, corrige, lance les tests du sujet puis la suite complète, et décide le statut avec l'utilisateur :
   - `valide` : verdict `validation_en_cours` ET tous les essais du § 5.4 réussis (13 facultatif) ET aucun constat
     bloquant ;
   - `restreint` : même chose avec des fonctions retirées (fonction en échec = `false` + avertissement) ;
   - `validation_en_cours` : un essai non fait ou ignoré sans raison acceptable ;
   - `refuse` : un essai de sécurité en échec.
4. Étape normale (historique, version, CLAUDE.md « Postes préparés / validés »).

## 8. Le faux poste rejouable (« jumeau »)

À partir de la trace CAT de la session (`cat_trace.log` : commandes, réponses, délais) : un FakeRigctld paramétré
par poste, qui garde un état (fréquence, mode, PTT, fonctions, niveaux) et rend les réponses, refus et formats
RÉELS relevés (y compris les cas difficiles : réponses sans libellé, refus selon le mode, lectures lentes comme
« u COMP » du FTDX10). Les tests de la station tournent alors aussi contre chaque poste qualifié : une nouvelle
version est vérifiée contre tous les postes déjà vus, sans les avoir. C'est le lot Q5 du programme d'origine.

Limite : un jumeau ne rejoue que ce qui a été vu ; une commande jamais relevée = refus « non relevé » (le test
échoue lisiblement, il ne devine pas).

## 9. Windows et Debian

Mêmes sources, mêmes essais. Différences gérées par l'outil :
- arrêt et relance de la station du PC (tâche planifiée et `trx-supervisor --stop` ; systemd et sudo) ;
- gel de la passerelle (essai 8) : `SIGSTOP` sous Debian, suspension du processus sous Windows
  (`NtSuspendProcess`, déjà nécessaire au même essai sur la station Windows) ;
- accès au port série sous Debian : compte du qualifieur dans `dialout` (vérifié à la préparation, § 4) ;
- pilotes USB : Windows seulement (kit) ; Debian les a.

Aucune n'est plus compliquée que ce que la station fait déjà ; le seul point neuf est la suspension sous Windows.

## 10. Sécurité (relue contre les règles d'émission)

- Toute émission de la session passe par la passerelle de session (client automatique, application) ou par
  `PttController` (étapes de `trx-qualif` / `trx-hwtest`) : verrou, battements, TOT, bandes, retour en réception.
  Aucun chemin d'émission nouveau.
- L'observateur ne fait que LIRE ; le superviseur de session tourne avec ses règles habituelles.
- Chaque émission est confirmée par l'opérateur, annoncée (durée, puissance) ; puissance relue au minimum.
- TOT de session réduit (20 s pour l'essai 2, 30 s ailleurs), sous le plafond.
- Un échec de sécurité arrête toutes les émissions de la session.
- Bandes de la session : celles que l'opérateur déclare avoir le droit d'utiliser (liste vide = réception seule, la
  partie émission est alors « non faite »).
- Tests de panne de l'outil lui-même (client automatique figé, observateur coupé, câble arraché pendant un essai,
  session reprise après une coupure du PC) : exigés au lot T2.

## 11. Lots

| Lot | Contenu | Dépend de |
| --- | --- | --- |
| T1 | session isolée (§ 5.1), préparation et kit (§ 4), détection, relevés de départ / fin, photos, remise en état, reprise | — |
| T2 | observateur, client automatique, essais 1 à 13 chronométrés, tests de panne de l'outil | T1 |
| T3 | mesures audio et ALC, spectre par le second port | T1 |
| T4 | rapport (`rapport.html`, `qualification.json`, empreintes, masquage), `trx-qualif --integrer`, `docs/postes/README.md`, catalogue | T2, T3 |
| T5 | jumeau rejouable et tests de la station contre `tests/rigs/` | T4 |

Chaque lot : console texte et console web (formulaires), quatre langues (domaine `qualif`), menu 8.3, guide de
l'opérateur partie 3.6, mode d'emploi de la console. Essais réels : d'abord l'IC-7300MK2 à la maison (poste connu,
la valise doit le donner `valide` : sinon c'est la valise qui a un défaut), puis le BÊTA-TEST sur un **Icom IC-705**
(décision de l'utilisateur, 2026-11-18), puis le Yaesu FTDX10.

Documentation de l'IC-705 (manuels du fabricant, guide CI-V) : HORS du dépôt public (droits d'Icom), dans
`C:\dev\postes-docs\icom-ic705\` sur le PC de développement ; seule la fiche écrite par l'équipe
(`docs/postes/icom-ic705.md`) entre dans le dépôt. Points propres à l'IC-705 à préparer au § 4 : 10 W au plus
(5 W sur batterie), UN câble USB qui donne DEUX ports série (CI-V et second port) et une carte son, Wi-Fi et
Bluetooth du poste à laisser coupés pendant la séance (une autre commande que la CAT de la session fausserait les
essais « opérateur sur place »), alimentation secteur pendant la séance (batterie qui s'épuise = coupure en plein
essai).

## 12. Questions encore ouvertes

1. Décision 7 (liste des postes validés : `docs/postes/README.md` + catalogue dans `trxstation/qualif/catalogue/`) :
   à confirmer.
2. Bornes du § 5.4 : proposées d'après les règles (2 s de battement, etc.) ; à confirmer au premier essai réel sur
   l'IC-7300MK2.
3. Seuils des mesures audio (§ 5.5) : à fixer au lot T3 d'après l'IC-7300MK2.
