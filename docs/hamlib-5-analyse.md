# Hamlib 5.0.0~git : lecture du code pour l'IC-7300 / IC-7300MK2, l'IC-705 et le FTDX10

Analyse du 2026-11-26, LECTURE DU CODE SEULEMENT (aucun essai). Version lue : SHA `fa0ed6d6a` (rigctld de
minix-bzh, « Hamlib 5.0.0~git 2026-10-19 »), comparée au tag `4.7.2` (PC Windows) et à `master` du 2026-11-19.
Chaque point dit « lu » (code ou manuel) ou « mesuré » (nos essais) ; un point « lu » reste à confirmer par l'essai
indiqué. Les points marqués ✔ ont été relus dans les sources après les analyses.

Manuels : `C:\dev\postes-docs\icom-ic705\IC-705_ENG_CI-V_1_20200721.pdf`, `C:\dev\postes-docs\yaesu-ftdx10\FTDX10_CAT_OM_ENG_2308-F (1).pdf`.

## 1. À corriger dans openRemoteTRX (par ordre d'importance)

| # | Constat | Poste | Effet | Correction proposée |
|---|---|---|---|---|
| S1 | ✔ Décalage relais (DUP+/-, « Auto Repeater » `1A 05 00 49` sur l'IC-705) jamais lu par la station ; Hamlib déclare `get_rptr_shift` / `get_rptr_offs` (`ic7300.c:1785`) | IC-705, IC-7100, IC-9700, tout poste VHF/UHF | bande vérifiée sur la fréquence de RÉCEPTION, émission décalée possible HORS BANDE (145,600 + 0,6 = 146,200 MHz) | comme le split et le ΔTX : relire avant d'émettre, refuser si illisible, couper si ça change ; tests de panne |
| S2 | ✔ rigctld refuse toute commande, `T 0` compris (RPRT -20), tant qu'il croit le poste éteint (`tests/rigctl_parse.c:2100`) | tous | poste rallumé à la main après une extinction par la station : premier `T 0` refusé | sur RPRT -20 : `\get_powerstat` puis `T 0` de nouveau ; un -20 n'est jamais une preuve de réception |
| F1 | ✔ `newcat_get_dcd` = toujours -11, `dcd_type = RIG_DCD_NONE` (`ftdx10.c:145`) | FTDX10 (Yaesu newcat) | squelch réel de l'étape 396 abandonné au premier tour | lecture brute `w BY;` (P1 = 1 squelch ouvert), champ de fiche, comme `FT;` |
| F2 | ✔ `M <mode> 0` : 0 devient la largeur « normale » (2400 Hz) et le filtre de toit est réécrit (`newcat.c:1875`) | FTDX10 | réglages de l'opérateur changés par toute remise de mode | remettre un mode avec `-1` (« ne pas changer ») sur ce poste : règle de fiche, pas de `if model` |
| F3 | Paliers SH de Hamlib pour le FTDX10 = table du FTDX101 (2200 / 2300 / 2400) contre 2250 / 2400 / 2450 au manuel (lu, PDF mal extrait) | FTDX10 | `M USB 2400` donnerait 2450, `m` relirait 2400 | largeur lue par `w SH0;` et notre table ; essai C2 avant toute décision |
| I1 | `TUNER` déclaré, l'IC-705 n'a pas de coupleur interne (AH-705 externe, illisible) | IC-705 | `tuner_delay_s` sans objet | fiche `3085.toml` à reprendre (copie de 3094 aujourd'hui : pas de second port, coupleur externe, 10 W / 5 W sur piles) |
| I2 | DATA OFF MOD = MIC,USB par défaut : le son USB module aussi USB / LSB / AM / FM simples | IC-705 | différent de l'IC-7300 | avis comme ORT-5040, menus `01 18` / `01 19` |
| I3 | Menus du TOT différents par modèle : MK2 `00 32`, IC-705 `00 43` | IC-705 | TOT de l'IC-705 non lu | ajouter l'IC-705 à `rigtot.py` (même table de valeurs, à vérifier sur le poste) |

À GARDER absolument : `-C cache_timeout=0` (voir H1), lecture de `s` avant `i` (déjà fait :
`gateway/safety/ptt.py:656`), jamais d'écriture `S`, abandon de `COMP` sur le FTDX10, lecture brute des menus `1A 05`,
refus de `async=1`, relecture après `\set_powerstat 1`.

## 2. À signaler à Hamlib

Sécurité, tous postes (à envoyer en premier, un message chacun) :
- H1 ✔ `rig_set_ptt` écrit le PTT demandé dans le cache même quand la commande a échoué (`src/rig.c`, `rig_set_cache_ptt`
  hors du test du code de retour ; master idem) : un `T 0` raté suivi d'un `t` peut répondre 0 sans lire le poste.
- H2 ✔ `rig_get_split_freq` rend 0 d'après l'état du split en mémoire, sans lire le poste (`src/rig.c:4999`) : un split
  mis à la face avant n'est vu qu'après un `s`.
- H3 `rig_set_split_vfo` rend OK sans rien faire si le PTT en mémoire est actif (`src/rig.c:5797`).
- H4 ✔ rigctld refuse `T 0` quand il croit le poste éteint : laisser passer la coupure du PTT.

Icom IC-7300 / MK2 / IC-705 :
- `S 1 VFOB` force le VFO A (`07 00`) avant `0F 01` quand le VFO courant est inconnu (`icom.c:6740`) : la réception change.
- ✔ `icom_set_mode` ignore le résultat de l'écriture de largeur (`icom.c:2646`) ; au premier refus de `1A 03`, les
  largeurs sont coupées pour toute la session (`icom.c:2128`).
- Plages fausses (`level_gran_icom.h:18-21`) : NB 0..10 écrit 0..1 (tracé sur MK2 ET IC-705), ATT liste {20} / plage
  0..12, PREAMP liste {1,2} (numéros) / plage 0..20, NOTCHF_RAW sans plage ; RFPOWER_METER_WATTS 0..100 et VD_METER 0..1
  pour l'IC-705.
- ✔ `icom_mW2power` suppose un poste de 100 W (`icom.c:9192`) : 5 W donnent 0,05 sur l'IC-705.
- IC-705 : `USB_AF` a sa commande (`01 10`) mais n'est pas dans les niveaux déclarés ; `ANN` déclaré en lecture, écrit
  seulement ; `get_powerstat` absent = « allumé » sans aucune lecture (fa0) ; `TUNER` déclaré sans coupleur interne.
- IP+ (`RIG_FUNC_AIP`) absent de l'IC-7300.
- Demandes déjà rédigées : paramètre TOT (avec MK2 `00 32` et IC-705 `00 43`), DATA MOD, FIL1/2/3 sans réécriture.
- KEYERTYPE (plantage de rigctld) : corrigé par 7e78154e en 5.0, PAS en 4.7.2 : demander un report en 4.7.x.

Yaesu FTDX10 :
- COMP : lecture `PR;` refusée par `?;`, écriture `PR1;` / `PR0;` qui sont des lectures sur ce poste (`newcat.c:6362`,
  6677) ; `?;` retenté 3 × 600 ms (nos 2,45 s) ; même cause probable pour NR / ANF lents en AM / FM.
- `get_dcd` par `BY;` à implémenter (`BY` déjà valide pour le FTDX10, `newcat.c:497`).
- ✔ allumage : boucle de 8 tours, test d'échec `i == 9` jamais vrai (`newcat.c:3804`).
- table de largeurs propre au FTDX10 ; filtre de toit 300 Hz marqué non optionnel ; `U TUNER 2` lance un accord (émission).
- un seul échec de `ST;` coupe la lecture du split pour toute la vie de rigctld (`newcat.c:8517`) ; cache `IF;` de 500 ms
  qui ne suit pas `cache_timeout` (RIT / XIT).
- plages : émission 200 W (fiche reprise du FTDX101), STRENGTH, VD_METER, BKINDL ; `BAND_SELECT` et `get_ts` déclarés
  sans lecture.

## 3. Versions

- 4.7.2 -> fa0ed6d6a : KEYERTYPE corrigé, cache commun sous un seul verrou (26b1ac26), tables de largeurs Yaesu
  réécrites, IC-7300MK2 ajouté et renuméroté ; rien pour l'IC-705.
- fa0ed6d6a -> master : correction de l'async au démarrage (b5118f0d, essayée sur IC-7760 seulement), `get_vfo` des Icom
  à `07 D2` (pas l'IC-7300), nouveau fichier `ic705.c` et pilote réseau IC-705 (grosse refonte jeune), fermeture des
  connexions de rigctld (a3170569) qui pourrait expliquer nos `ConnectionResetError` (hypothèse).
- Conseil : garder fa0ed6d6a en production ; essayer master sur tour radio (poste factice, plusieurs connexions) avant
  de recompiler minix-bzh.

## 4. Essais sans émission pour confirmer (station arrêtée, `-vvvvv`, chaque réglage remis)

IC-7300MK2 (minix-bzh, `rigctl -m 3094 … -C cache_timeout=0`) :
1. `p KEYERTYPE` (jamais en 4.7.2) ; 2. 50 × `l ATT` ; 3. `\get_dcd` squelch fermé / ouvert ; 4. `\get_cache` = 0 sur le
rigctld de la station ; 5. `i` seul après SPLIT mis à la main, puis `s` puis `i` ; 6. `f currVFO f otherVFO` (25 00 /
25 01, poste immobile) ; 7. FIL1/2/3 à la main puis `m` ; 8. `\get_powerstat` allumé / éteint / débranché.

IC-705 (`rigctl -m 3085 -r COMx -s 115200`) :
1. NB, ATT, AGC (en USB, pas en D-STAR) ; 2. `\get_dcd` ; 3. `u TUNER` avec et sans AH-705 ; 4. `\get_powerstat` éteint ;
5. `\get_rptr_shift` / `\get_rptr_offs` en FM 145,500 MHz avec DUP+ à la main ; 6. `\mW2power 5000 14074000 USB` ;
7. lecture brute du TOT `1A 05 00 43` et de DATA MOD `01 19`.

FTDX10 (`rigctl -m 1042 -r COMx -s 38400`) :
1. `-u | findstr PTT` ; 2. palier SH : 2.25k / 2.40k / 2.45k à la face avant puis `w SH0;`, puis `M USB 2400` et
`w SH0;` ; 3. `M USB -1` = seulement `MD02;` ; 4. poste éteint : `\get_powerstat` chronométré, puis `t` et `T 0`
(RPRT -20 attendu) ; 5. `\get_dcd` (-11) et `w BY;` squelch fermé / ouvert ; 6. `w PR0;` ; 7. `u NR` / `u ANF` en USB
puis en FM ; 8. `w EX030116;` (TOT) et menus MOD SOURCE `EX010113` / `EX010114` / `EX010415` / `EX010416`.
