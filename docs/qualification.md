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
```

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
- Filtres Icom : Hamlib choisit FIL1/2/3 et le poste relit la largeur qui y est RÉGLÉE. Une largeur différente
  de Hamlib est acceptée si chaque demande sélectionne bien un filtre distinct ; sinon c'est un échec.
- Si un ancien `station.toml` contient `tx_modes = ["PKTUSB", "PKTLSB", "PKTFM", "PKTAM"]`, l'émission en FM-D
  et AM-D est refusée avec Hamlib 4.7 : `trx-setup --tx-modes PKTUSB PKTLSB FM-D AM-D`.
- Le spectre (scope) n'est pas encore qualifié.
