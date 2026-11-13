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

Depuis TRX Console : menu 2.7 « Qualification d'un poste » (choix 1 à 5 = les commandes ci-dessus ; rapports dans
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
