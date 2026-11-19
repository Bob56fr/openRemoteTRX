# Qualification d'un poste : `trx-qualif` (lot Q1)

Référence : Claude Doc « Cahier des charges — Programme de qualification TRX ». Ce lot fournit le
moteur en ligne de commande ; le wizard (page web locale) vient au lot Q2, le rapport signé et
chiffré au lot Q3.

## Avant de commencer

Mêmes précautions que `trx-hwtest` (voir `docs/essai-poste-reel.md`) : charge fictive, puissance
minimale, TOT interne du poste réglé, VOX coupé, opérateur près du poste, bande autorisée.
La station (passerelle, superviseur) doit être **arrêtée** : `trx-qualif` lance son propre rigctld.

## Commandes

```
trx-qualif --plan                    # cahier de test du modèle de station.toml (ne touche pas au poste)
trx-qualif                           # qualification complète guidée
trx-qualif --cycles 2000 --tot 8     # endurance plus longue, TOT des essais d'émission
trx-qualif --catalogue DOSSIER       # vérifie toutes les fiches d'un catalogue
trx-qualif --plan --modele 1042      # cahier et incohérences de dump_caps d'un modèle, SANS station.toml ni poste
trx-qualif --explorer                # exploration d'un poste jamais essayé, SANS émission (expert, voir plus bas)
trx-qualif --explorer --lecture-seule  # la même chose sans rien changer sur le poste
trx-qualif --sans-emission           # qualification sans la phase 3 (verdict « incomplet »)
trx-qualif --filtres                 # essaie AUSSI les largeurs de filtre (voir « Filtres » : réécrit les FIL d'un Icom)
```

Depuis TRX Console : menu 8.3 « Qualification d'un poste » (choix 1 à 5 = les commandes ci-dessus ; rapports dans
le dossier d'état de la station, `qualifications/`).

Un rigctld qui répond déjà est REFUSÉ (c'est presque toujours celui de la station) : arrêter la station, ou
`--no-spawn` pour utiliser ce rigctld en connaissance de cause.

Sans `--config`, `trx-qualif` prend `station.toml` à l'emplacement standard, sinon celui du dossier
courant (cas d'un poste de développement Windows).

Si la commande n'est pas trouvée après la mise à jour : `pip install -e ".[dev]"` (déclare la
nouvelle commande), ou `python -m trxstation.qualif.main`.

## Déroulé

1. Confirmation des précautions, version du firmware lue sur le poste.
2. **Phase 1, sans émission** : fréquence relue sur chaque bande (avec un décalage de 123 Hz pour
   mesurer la résolution), tous les modes déclarés, filtres, lectures et écritures générées depuis
   Hamlib, endurance (1000 lectures) et temps de réponse. L'état du poste est relevé avant et
   **rétabli après**. La puissance n'est jamais montée au-dessus de la valeur de départ si un palier
   inférieur existe ; une puissance hors des paliers de TRX Remote n'est pas touchée.
   Le tuner n'est **jamais** activé automatiquement (il peut lancer un accord).
3. Audio reçu (enregistré dans `rx.wav`).
4. **Phase 2, guidée** : l'opérateur confirme l'afficheur et l'écoute. Réponses déclaratives,
   jamais suffisantes seules.
5. **Phase 3, émission** : étapes de `trx-hwtest` (PTT, audio TX, pannes), chacune après avoir
   tapé `EMETTRE`, plus la **perte de la liaison CAT pendant l'émission** : un relais placé entre
   l'application et rigctld coupe la liaison 1,5 s ; la passerelle doit ramener le poste en
   réception dès son retour.
6. Facultatif : reprise après débranchement du câble USB (en réception).

## Verdict

Recalculé à partir des résultats bruts :

| Socle | Verdict | Brouillon de fiche |
| --- | --- | --- |
| un test en échec | `refuse` | statut `refuse` |
| un test non fait ou ignoré | `incomplet` | statut `refuse` (jamais utilisable) |
| tout réussi | `validation_en_cours` | statut `validation_en_cours` |

Une erreur d'installation (rigctld injoignable, carte son introuvable, bandes mal réglées) donne
`incomplet`, jamais `refuse`. Seul un état PTT illisible refuse le poste dès la liaison CAT.
Le statut `valide` (ou `restreint`) reste une décision de l'éditeur.

## Valise de qualification v0 (`--terrain`, étape 252)

Mode d'emploi pour le qualifieur (préparation, commandes, adresses, pièges) : [valise-mode-emploi.md](valise-mode-emploi.md).

Qualification SUR PLACE par un membre de l'équipe (cahier : `docs/qualification-terrain-cahier-des-charges.md`).
La v0 n'ajoute AUCUN chemin d'émission : les émissions des essais sont faites par la station (page, application,
micro du poste) ; l'outil n'envoie à rigctld que la lecture `t` (liste fermée `OBSERVER_COMMANDS`, 127.0.0.1 seulement).

```
trx-qualif --terrain --output DOSSIER            # nouvelle session dans DOSSIER/terrain-<modèle>-<date>
trx-qualif --terrain --output DOSSIER --session DOSSIER/terrain-…   # reprendre une session
```

Depuis TRX Console : menu 8.3, choix 6 (étape 253 ; la station n'est pas arrêtée par la console, la valise s'en charge).

Bus et page (étapes 279-280, valise graphique, `docs/qualification-gui-cahier-des-charges.md`) : tout passe par le
bus `qualif/bus.py` (historique `evenements.jsonl` dans le dossier de la session). `trx-qualif --terrain --page`
ouvre la valise dans le navigateur de CE PC (127.0.0.1, adresse à usage unique) : menu en boutons, fenêtre
d'intervention pour CHARGE / ANTENNE / EMETTRE (tapés au clavier, collage refusé, bip), STOP toujours visible
(« T 0 » puis essai interrompu, retour au menu) ; le terminal n'affiche plus que le journal. Étape 281 : tuiles
par thème, « Tout lancer », « Relancer les échecs », mesures en direct (`qualif/tiles.py`) ; touches directes
« 5.N » et « 8.N » (un essai), « tout », « echecs », « theme:<id> » acceptées aussi au terminal.

Menu (étape 253) : 1 relevé du poste AVANT, 2 exploration, 3 qualification avec émission, 4 sans émission (station
ARRÊTÉE pour 2 à 4 : refusés sinon, les outils lancent leur rigctld), 5 essais de sécurité chronométrés (station EN
MARCHE), 6 relevé APRÈS et différences, 7 rapport zip, a / d arrêter / démarrer la station du PC (comme les menus 1.2
et 1.1), q quitter.

Carte son du poste (choix 9, étape 258, À FAIRE EN PREMIER, station ARRÊTÉE, aucune émission) : carte choisie (un
nom VIDE donne un silence sans erreur), réception ouverte 2 s (niveau, silence numérique = accès au micro refusé,
carte tenue ailleurs ou mauvaise carte), sortie ouverte avec 0,3 s de SILENCE écrit (rien n'est émis) ; sous Windows :
nom numéroté « 2- … » qui change avec la prise USB, rappel volume 100 / améliorations désactivées (vu sur
l'IC-7300MK2 : volume à 38 = émission sans puissance). Résultat dans le rapport (`carte_son`).

Relevés (1 et 6) : LECTURE SEULE (`ReadOnlyRig` : `f m t s j z u l p` seulement, toute autre commande refusée avant
l'envoi), station ARRÊTÉE, par un rigctld lancé pour l'occasion (étape 255 : une lecture qui le fait tomber est notée,
rigctld relancé, la suite lue, et cette lecture n'est plus jamais faite ; vu : `p KEYERTYPE` sur l'IC-7300MK2 avec
Hamlib 4.7.2) ; fréquence, mode,
split, RIT, XIT, fonctions, niveaux SANS les mesures (S-mètre, ALC…), paramètres ; `reglages/releve-avant.json`,
`releve-apres.json`, `differences.json` = « À REMETTRE À LA MAIN » ; rapport : `remise_en_etat` (« NON vérifiée »
si un relevé manque). Photos des menus du poste : dossiers `photos/avant` et `photos/apres` de la session (copiées à
la main), comptées et listées dans le rapport.

Essais (partie 3.5 du guide, plus le démarrage) : l'observateur relit le PTT toutes les 200 ms. Pour STOP, perte de
liaison et arrêt de la station, le qualifieur tape Entrée AU MOMENT de l'action (repère) : délai = retour en réception
relu - repère, borne = règle + 1 s de réaction humaine. TOT : durée de l'émission relue, ± 2 s. Hors bande et
démarrage : aucune émission vue. Opérateur sur place : émission locale vue, refus du PTT distant déclaré. Chaque essai
demande ensuite si ce qui a été vu est conforme ; une déclaration ne rattrape JAMAIS une mesure en échec. Le résultat
de chaque essai et les lignes des journaux JSON de la station sur la fenêtre (masquées) vont dans `essais/<id>.json`.

Rapport : `<session>.zip` dans DOSSIER (`qualification.json` format 1, `rapport.html`, `LISEZMOI-CLAUDE.md`,
`empreintes.sha256`, dossiers `explore-*`, `qualif-*`, `essais/`). Verdict PROPOSÉ : `refuse` (un essai ou Q1 en
échec), `incomplet`, `validation_en_cours` ; `valide` reste une décision de l'équipe.

Essais AUTOMATIQUES (choix 8, étape 254, `qualif/autodrills.py`) : un client automatique (le faux client WebRTC
des tests, micro MUET, certificat de la passerelle ÉPINGLÉ par son empreinte) se connecte à la station avec un compte
opérateur (demandé une fois, mot de passe masqué) et joue A1 STOP (≤ 0,5 s), A2 battements arrêtés (≤ 3 s), A3
connexion fermée (≤ 3 s), A4 fréquence juste hors d'une bande (émission refusée, fréquence remise), A5 TOT (± 2 s). Étape 282 : A6 STOP TX du tableau de bord appuyé par la valise (« T 0 », même code que le
bouton, < 1 s), A7 station ARRÊTÉE par la valise pendant l'émission (poste relu ensuite par un rigctld de la valise,
« T 0 » s'il émet encore, station redémarrée), A8 démarrage de la station par la valise (PTT relu pendant 40 s,
aucune émission demandée). Un essai automatique réussi remplace l'essai à la main équivalent dans le verdict
(`COVERED_BY` : 1 STOP, 2 TOT, 5 hors bande, 7 STOP TX, 8 station arrêtée, 9 démarrage) ; « Tout lancer » ne
demande plus à l'humain que les essais 3 (Wi-Fi du téléphone), 4 (écran verrouillé) et 6 (micro du poste).
Il ne parle qu'à la PASSERELLE : aucune commande au poste, toutes les sécurités de la station s'appliquent. Chaque
essai exige le mot EMETTRE (ou celui de la langue) tapé par l'opérateur ; poste pas en réception au départ = essai non
joué ; en fin d'essai, quoi qu'il arrive : « stop », connexion fermée, réception relue sur le poste, sinon échec et
alerte « COUPE LE POSTE ». Un essai automatique en échec REFUSE le poste ; ils restent facultatifs pour le verdict
(les essais à la main éprouvent la vraie page et la vraie application). Tests : `tests/test_qualif_autodrills.py`
(station complète en un processus, pannes de l'outil comprises).

Pas encore : configuration de session isolée de celle du PC, mesures ALC, jumeau rejouable.

## Valise : parties antenne / charge, bon mode, lot T3 (étape 263)

Règles de l'utilisateur (2026-11-18) appliquées :
- **Parties** : `r` = réception sur ANTENNE (aucune émission ; sur la FRÉQUENCE DU POSTE, décision du 2026-11-19 :
  l'antenne de l'opérateur est inconnue, cibiste ou radioamateur ; l'opérateur peut donner une autre fréquence, remise
  ensuite ; son et S-mètre mesurés ; verdict ok / faible < -65 dBFS / saturé > -6 dBFS / silence) ; `c` = passage sur
  la CHARGE FICTIVE, confirmé en tapant `CHARGE`. Les choix qui émettent (3, 5, 8) sont REFUSÉS tant que la charge
  n'est pas confirmée, et de nouveau après chaque passage par `r`. Déroulé conseillé affiché : 9, 1, r, 2, s, c, 3, d,
  8, 5, a, 6, 7.
- **Bon mode** : les écritures de la qualification se font en USB si le poste est en CW / FM (mode d'origine remis à
  la fin) ; un réglage refusé est réessayé dans le mode où il existe (`MODE_FOR` : compresseur en USB / LSB / AM,
  réglages CW en CW), le résultat dit « essayé en … ».
- **Montée du niveau d'émission** (valise) : paliers -40, -30, -24, -18, -12, -6 dBFS, arrêt dès qu'une puissance est
  mesurée ET que l'ALC atteint 0,5 ; niveau d'envoi conseillé dans le résultat (`trx-hwtest`, `alc_stop`).
- **Spectre** (`s`, sans émission) : Icom = relevé de 8 s par `devtools/civ_scope` (lecture seule) sur le second port
  s'il est réglé, sinon sur le port CAT (faisabilité) ; autre marque = « non proposé par la CAT ».

Étape 264 : bandes de qualification = toutes les bandes radioamateur (R1) + 85 m, 45 m et 11 m (`qualification_bands`,
d'après la table de la mesure de TOS ; la valise signale celles qui manquent à station.toml) ; essais du COUPLEUR
(mis en marche puis remis, PTT relu pendant l'accord) et du VOX (4 s en marche sans aucun son : aucune émission
attendue ; remis à l'arrêt quoi qu'il arrive ; commande brute de l'outil, la station refusant toute écriture du VOX)
dans la phase d'émission, chacun après EMETTRE.

Étape 269 : essai du SPLIT (`stage_split`, après le coupleur), sur charge fictive après EMETTRE. C'est L'OPÉRATEUR qui règle l'autre VFO et met le split à la touche SPLIT : l'essai n'écrit ni le split ni aucune fréquence (sur l'IC-7300MK2, « S 1 VFOB » de Hamlib 4.7.2 échange les VFO et la fréquence de réception change). Relus : split, fréquence d'émission, fréquence de réception. Fréquence d'émission hors bande : refus attendu (`out_of_band`), aucune émission ; illisible : refus `split_unreadable` (sûr, split inutilisable à distance) ; dans la bande : émission 1 (PTT, puissance, fréquences), puis émission 2 pendant laquelle l'opérateur éteint le split : la station doit couper (`split_changed`, relecture toutes les secondes). Pour relire le split, toujours un rigctld OUVERT : un `rigctl` d'une seule commande renvoie 0 pour la fréquence d'émission.

Étape 266 : choix `f` de la valise = préréglages FIL1 / FIL2 / FIL3 choisis et relus par le SECOND PORT CI-V (26 00,
comme la page et l'application), filtre d'origine remis, largeurs jamais écrites ; Icom avec second port seulement.

## Comparer deux qualifications du même poste (`--comparer`, étape 260)

```
trx-qualif --comparer A B [--output DOSSIER]    # A, B : zips de la valise ou dossiers de session terrain-…
```

Lecture seule (aucun poste, aucune station.toml). Compare : contexte (modèle Hamlib, versions, réglages), verdicts,
tests de la qualification Q1 (résultat ; coupures des pannes à ± 0,5 s ; temps de réponse CAT), essais de sécurité
(résultat ; délai depuis le repère à ± 1 s, mesures du client automatique à ± 0,5 s), constats de l'exploration,
relevés de DÉPART (un poste pas dans le même état au départ = écart « point de départ »), remise en état, niveau reçu
de la carte son (± 6 dB). Chaque écart : gravité (important, à vérifier, pour information) et cause probable (poste,
environnement, opérateur, outil). Documents : `comparaison-<date>/ecarts.md` et `ecarts.json` (format 1). Usage prévu :
qualification du même poste par deux personnes sur le même PC (IC-705, décision du 2026-11-18), ou du même poste
après une nouvelle version de Hamlib.

## Exploration d'un poste jamais essayé (`--explorer`, étape 175)

Pour un expert, AVANT la qualification : aller le plus loin possible sans émettre et trouver où Hamlib et le poste
divergent. Aucune commande de PTT n'est envoyée ; le mode n'est jamais changé.

1. PTT relu 10 fois : poste pas en réception (ou PTT illisible) = arrêt immédiat, sans rien écrire.
2. Indicateurs « Can get … » de dump_caps comparés aux réponses réelles (commandes de lecture seulement).
3. Lecture de TOUTES les fonctions, niveaux et paramètres déclarés, deux fois : refus, instabilité, valeur hors de
   la plage déclarée. Les fonctions d'action (SEND_MORSE, SEND_VOICE_MEM) ne sont pas lues.
4. Couverture : bords des plages de réception, puis une fréquence hors couverture (doit être refusée ; acceptée sans
   être appliquée = constat).
5. Niveau inexistant : refus attendu, et la réponse suivante doit rester juste (flux synchronisé).
6. Écritures avec relecture et remise à la valeur d'origine, LISTE FERMÉE de réglages de réception
   (`EXPLORE_WRITE_FUNCS`, `EXPLORE_WRITE_LEVELS` : CTCSS, APF, PBT, pitch et vitesse CW…). Jamais VOX, tuner, envoi
   de morse ou de mémoire vocale, break-in, MICGAIN, RFPOWER, volume AF, spectre, verrouillage. Le PTT est relu avant
   chaque écriture. Les réglages déjà exploités par TRX Remote sont essayés par la qualification, pas ici.
7. Rafale de lectures mêlées (fréquence, mode, PTT, S-mètre) : réponses décalées, et temps de réponse par commande.
8. Reconnexions à rigctld ; fréquence d'origine remise, mode relu.

Constats (`coherence.py`), par gravité (bloquant, à vérifier, pour information) et par source supposée (hamlib,
poste, trx). Une partie sort de dump_caps SEUL (`--plan`) : préamplis / atténuateurs dont la liste ne suit pas la
plage, plage AGC vide, « PTT type: None » avec « Can set PTT: Y », modes données absents des plages d'émission,
réglages non relisibles, backend non « Stable ».

Dossier `qualifications/explore-<modèle>-<date>/` : `exploration.json`, `constats.txt`, `fiche-poste.md` (brouillon
pour `docs/postes/`, jamais validé en émission), `rapport-hamlib.md` (brouillon EN ANGLAIS des écarts imputables à
Hamlib, à vérifier sur Hamlib master avant envoi), `dump_caps.txt`, `cat_trace.log`, `journal.txt`. Ni indicatif, ni
adresse, ni port série.

### Résultat sur l'IC-7300MK2 (minix-bzh, Hamlib 5.0.0~git, 2026-11-13)

Couverture 30 kHz – 74,8 MHz confirmée, hors couverture refusée (RPRT -9), aucune réponse décalée sur 300 lectures,
état remis. Constats : fréquence, mode et PTT servis par le CACHE de rigctld (0,25 ms : le PTT relu peut être celui
du cache) ; ANN refusé alors que déclaré ; AGC_TIME et BKINDL refusés dans le mode du moment (RPRT -9) ; COMP arrondi
par le poste (pas réel plus grossier que le pas déclaré 0,01) ; STRENGTH et VD_METER lus hors de leur plage déclarée ;
« PTT type » = None avec Hamlib 4.7.2 mais « Rig capable » avec 5.0.

## Rapport

Dossier `qualifications/qualif-<modèle>-<date>/` :

- `results.json` : tous les tests (identifiant, catégorie, résultat, détail, mesures), profil
  Hamlib, plan, verdict ;
- `fiche.toml` : brouillon de fiche TRX ;
- `cat_trace.log` : trace CAT horodatée (future base du rejeu en non-régression) ;
- `dump_caps.txt`, `plan.txt`, `journal.txt`, `rx.wav`.

## Fiche TRX

```toml
[rig]
nom = "IC-7300MK2"
fabricant = "Icom"
hamlib_model = 3094
firmware = ["1.10"]
hamlib_min = "4.6.2"
hamlib_teste = "4.6.2"
statut = "validation_en_cours"   # valide | restreint | validation_en_cours | refuse
fiche_version = 1
backend_hamlib = "Stable"

[fonctions]          # true = proposé par l'application
freq = true
ptt = true
nr = false

[avertissements]     # affichés à l'utilisateur
nr = "en échec à la qualification : …"

[mesures]
latence_cat_ms = 45.0

[validation]
installations = 0
heures_cumulees = 0
rapports_qualif = 1
```

Règle bloquante : un statut utilisable exige `freq`, `mode`, `ptt` et `audio_rx` à `true`.
`ptt` n'est vrai que si les cycles PTT ET le retour en réception sur perte CAT ont réussi.

## Essai de la procédure sur l'IC-7300MK2 (premier passage complet)

But : dérouler la qualification de bout en bout sur un poste connu, pour juger la procédure elle-même
(clarté des questions, durée, verdict, fiche produite) avant de la proposer à d'autres utilisateurs.

1. Préparer : charge fictive, puissance au minimum, TOT interne du poste réglé, VOX coupé, mode
   données (USB-D), station arrêtée (TRX Console, ou arrêt du superviseur sous Windows).
2. `trx-qualif --plan` : lire le cahier de test produit pour ce modèle. Noter tout test qui paraît
   inutile, absent ou mal nommé.
3. `trx-qualif` : suivre le déroulé, chronométrer chaque phase, taper `EMETTRE` seulement poste prêt.
4. Me renvoyer le dossier `qualifications/qualif-…/` complet (zippé), avec :
   - la durée totale et celle de chaque phase ;
   - les questions ou messages peu clairs (copie du texte) ;
   - le verdict obtenu et ce que tu en penses (le poste fonctionne : un `refuse` serait un défaut
     de la procédure à corriger) ;
   - tout ce que le poste a fait d'inattendu (réglage non rétabli à la fin, puissance changée…).

Le spectre HF (second port) n'est pas couvert par la qualification à ce jour.

## Filtres et préréglages FIL (Icom)

Sur un Icom, `set_mode` avec une largeur (> 3 Hz) ÉCRIT cette largeur dans le préréglage FIL1/2/3 choisi par
Hamlib (`icom_set_dsp_flt`, rigs/icom/icom.c). Depuis l'étape 175 :
- le test des filtres n'est fait qu'avec `--filtres` (sinon « ignoré », avec la raison) ;
- le mode d'origine est remis avec la largeur 0 (largeur par défaut du backend, comme la passerelle ; une largeur de
  0 à 3 sort de Hamlib AVANT l'écriture du filtre) : les préréglages restent intacts, mais le filtre SÉLECTIONNÉ peut
  changer. Le bilan liste alors « À REMETTRE À LA MAIN » (re-sélectionner FIL1 / FIL3 dans les modes concernés) ;
- `trx-hwtest`, étape « Largeurs de filtre » : avertissement et réponse « non » par défaut.

Temps de réponse CAT : avec rigctld 5, la fréquence vient du cache (0,2 ms) ; la mesure prend alors le S-mètre,
toujours demandé au poste. NR / NB : la fonction est mise en marche le temps d'essayer son niveau (l'IC-7300MK2
refuse le niveau NB quand NB est arrêté).

## Écarts connus avec le cahier des charges

- La reprise après débranchement USB est un test **fixe** et non du socle : sous Windows, rigctld
  ne retrouve pas toujours le port COM, ce qui relève de l'installation (le superviseur relance
  rigctld en service normal) et non du poste.
- AGC : si Hamlib ne publie pas les valeurs d'AGC du poste, on vérifie seulement que l'écriture
  de la valeur actuelle est acceptée.
- Format de `dump_caps` VÉRIFIÉ sur l'IC-7300MK2 avec Hamlib 4.7.2 (`tests/data/dump_caps_ic7300mk2_hamlib472.txt`) :
  backend Beta, modes données FM-D et AM-D (et non PKTFM, PKTAM), pas d'IP+ (AIP), AGC `0=OFF 2=FAST 5=MEDIUM 3=SLOW`,
  préamplis publiés « 1dB 2dB » (valeurs 1 et 2, alors que la plage du niveau annonce 0..20/10 : on suit la liste).
- AGC : l'essai d'écriture évite OFF tant qu'une autre valeur active existe.
- Filtres Icom (seulement avec `--filtres`) : Hamlib choisit FIL1/2/3 et le poste relit la largeur qui y est
  RÉGLÉE. Une largeur différente de Hamlib est acceptée si chaque demande sélectionne bien un filtre distinct ; sinon
  c'est un échec. ATTENTION : la largeur demandée est écrite dans le préréglage (voir « Filtres et préréglages FIL »).
- Si un ancien `station.toml` contient `tx_modes = ["PKTUSB", "PKTLSB", "PKTFM", "PKTAM"]`, l'émission en FM-D
  et AM-D est refusée avec Hamlib 4.7 : `trx-setup --tx-modes PKTUSB PKTLSB FM-D AM-D`.
- Le spectre (scope) n'est pas encore qualifié.
