# Mesure de TOS (courbe de SWR de l'antenne) — cahier des charges

Version 2 (2026-11-02, étape 103) : réponses de l'utilisateur aux questions de la v1 intégrées (§ 13). Demandé le
2026-11-02 ; décisions de l'utilisateur reprises de la conversation du même jour (§ 2).

## 1. Objet

Tracer la courbe de TOS (SWR) de l'antenne sur une plage de fréquences : la station émet une courte porteuse sur
chaque point, lit le TOS mesuré par le poste, puis passe au point suivant. Le résultat s'affiche sous forme de barres
verticales et peut être exporté en image légendée pour être partagé.

C'est une **émission automatique** : elle suit toutes les règles de sécurité d'émission (CLAUDE.md), sans exception.

## 2. Décisions de l'utilisateur (2026-11-02)

1. La mesure est une **prise d'émission normale du client**, comme l'appel SELCALL manuel (`selcall_send`) : mêmes
   refus que `toggle` (armement, verrou mono-client, opérateur sur place, poste chaud, bande, mode), battements du
   client, TOT, toute coupure arrête la mesure. Tests de panne obligatoires.
2. C'est la **passerelle** qui fait la mesure. Le client (page, application) la lance, l'annule et affiche le résultat.
   TRX Console ne la lance jamais (un outil ne peut que couper) ; elle peut afficher la dernière mesure.
3. **Bandes** : mêmes règles qu'une émission normale. Avec `[safety] enforce_bands = true` (défaut), la mesure n'émet
   que dans les `[[bands]]` de `station.toml` ; pour mesurer en CB (26-28 MHz), sur le 45 m (6 620-6 700 kHz et
   3 410-3 490 kHz) ou sur les bandes marines HF, l'opérateur les ajoute lui-même à `[[bands]]`. Avec
   `enforce_bands = false` (contrôle laissé au poste), AUCUNE bande n'est exigée : l'opérateur peut travailler sur un
   montage particulier sans émission sur l'air (transpondeur, conversion SHF…) ; c'est sa responsabilité (décision du
   2026-11-02). Dans tous les cas, une fenêtre l'avertit quand la plage sort des bandes radioamateur.
4. **Plage par défaut** : la bande où se trouve le poste (table interne : bandes radioamateur, CB, 45 m, marine HF de
   l'appendice 17 de l'UIT). Sinon, l'opérateur choisit une fréquence centrale (par défaut celle du poste) et une
   largeur ; la page affiche alors le calcul de FreqBasse et FreqHaute.
5. **Pas arrondi à une valeur lisible** : 5, 10, 25, 50, 75, 100, 150, 200, 250, 500 kHz… (§ 5).
6. **Mode FM**, sans coupleur : le coupleur est coupé pendant la mesure et remis s'il était en service.
7. **Puissance** : 15 % de la puissance du poste par défaut, réglable par l'opérateur jusqu'à 50 % (certains TOS-mètres
   mesurent mal à très faible puissance).
8. **Choix de l'opérateur mémorisés** (puissance, nombre de points, écoute avant émission) dans un fichier d'état
   `state_dir/swr.json`, PAS dans `station.toml` : la passerelle ne doit jamais pouvoir écrire dans le fichier qui
   contient les bandes autorisées.
9. **Pas d'écoute avant émission** : le S-mètre n'est pas pris en compte (S9 de QRM courant sur 80 m) ; option retirée.
10. **Remise en état** (fréquence, mode, puissance, coupleur, filtre) à la fin, à l'annulation et à toute coupure ;
    l'état remis est RELU sur le poste et montré dans une fenêtre en fin de mesure ET quand l'opérateur quitte la page
    de la mesure, pour qu'il corrige à la main si besoin.
11. **Graphique** en barres verticales, en rouge quand le TOS dépasse 2 ; lignes horizontales à 1,2 1,3 1,4 1,5 1,8
    et 2 ; échelle non linéaire autorisée ; axe vertical plafonné à 5. **Export en image** avec le nom donné par
    l'opérateur en légende.

## 3. Réglages

| Où | Clé | Défaut | Rôle |
|---|---|---|---|
| `station.toml`, `[swr]` (station seulement) | `enabled` | `true` | `false` = mesure absente (fonction non annoncée) |
| | `max_power_pct` | `50` | plafond de puissance, en % de la puissance du poste ; jamais au-dessus de 50 |
| | `max_points` | `50` | nombre maximal de points d'une mesure |
| | `point_tx_max_s` | `2.0` | durée d'émission maximale d'un point (plafond de l'étalonnage, § 6 bis) |
| `state_dir/swr.json` (derniers choix, par compte) | `power_pct` | `15` | puissance demandée (5 % au moins : minimum de l'IC-7300) |
| | `points` | `11` | nombre de points souhaité |
| | `last` | — | dernière mesure (résultat complet, pour l'afficher à nouveau et dans TRX Console) |
| `state_dir/swr.json` (par modèle Hamlib) | `settle_s` | — | temps de lecture fiable du TOS mesuré au premier usage (§ 6 bis) |

Puissance du poste : `[rig] max_power_w` (déjà dans `station.toml`), sinon la « High power » de la plage d'émission
de Hamlib (`dump_caps`, « TX ranges » : 100 W pour l'IC-7300MK2). Inconnue des deux : la mesure travaille en % sans
afficher de watts. Réglage : niveau Hamlib `RFPOWER` (0 à 1 ; 0,05 au moins sur l'IC-7300MK2), donc 15 % = 0,15.

## 4. Choix du mode FM

- Mode utilisé : le premier mode FM que le poste annonce (`capabilities.modes`) ET que `tx_modes` permet, dans
  l'ordre `FM`, `PKTFM`, `FM-D`. Sur l'IC-7300MK2 avec `tx_modes` Icom : `FM-D`. En mode données FM sans audio, le
  poste émet sa porteuse pleine : la porte audio d'émission reste FERMÉE pendant toute la mesure (rien du micro).
- Aucun mode FM permis : mesure refusée (`swr_no_fm_mode`) avec le conseil d'ajouter `FM-D` à `tx_modes`.
- Pourquoi pas la BLU : sans audio, aucune puissance de sortie, TOS illisible.

## 5. Plage, pas et points

Entrées : bande (par défaut celle du poste), ou fréquence centrale F (par défaut celle du poste) et largeur L ; nombre de
points souhaité N (2 à `max_points`).

1. Plage : bande choisie = ses limites ; sinon FreqBasse = F - L/2, FreqHaute = F + L/2. La page affiche le calcul
   (« 14 175 kHz ± 175 kHz = 14 000 à 14 350 kHz »).
2. Pas brut = L / (N - 1). Pas retenu = la valeur de la liste 1, 2, 5, 10, 25, 50, 75, 100, 150, 200, 250, 500,
   1 000 kHz la plus proche du pas brut (en dessous de 5 kHz : 1 et 2 kHz pour les bandes étroites comme le 60 m).
3. Points = de FreqBasse arrondie au pas supérieur jusqu'à FreqHaute, au pas retenu ; le nombre réel de points est
   affiché (exemple de l'utilisateur : 1 000 kHz en 10 tests -> pas brut 111 kHz -> pas 100 kHz -> 11 points).
4. Un point hors des `[[bands]]` de la station : sauté et marqué « hors bande » (barre grise). Plage entièrement hors
   bande : mesure refusée.
5. Au-delà de `max_points` : refus avec le nombre de points calculé.

Table interne des bandes (pour la plage par défaut et l'avertissement, JAMAIS pour autoriser une émission) : bandes
radioamateur IARU Région 1 (comme `DEFAULT_BANDS_R1`), CB 26 000-28 000 kHz, 45 m 6 620-6 700 et 3 410-3 490 kHz,
marine HF (appendice 17 de l'UIT, sous-bandes 4, 6, 8, 12, 16, 18/19, 22, 25/26 MHz).

## 6. Déroulé côté station

1. **Contrôles avant tout changement** (refus immédiat, rien n'est touché) : client opérateur, armé, seul propriétaire
   possible du PTT, poste en RX confirmé, pas d'opérateur sur place, poste pas trop chaud, mode FM disponible, plage
   et points valides, au moins un point dans les bandes.
2. **Mémorisation** de l'état du poste, RELU : fréquence, mode et largeur, puissance (`RFPOWER`), coupleur (fonction
   `TUNER`), split et décalages RIT/ΔTX.
3. **Préparation** : coupleur arrêté (s'il est lisible et en service), mode FM, puissance demandée (bornée au plafond).
   Chaque réglage est relu ; un réglage qui ne se relit pas comme demandé = annulation et remise en état.
4. **Pour chaque point** :
   - QSY sur le point (fréquence relue) ; point hors bande (si `enforce_bands`) = sauté ;
   - prise d'émission NORMALE (`_key` du PttController : mêmes vérifications que `toggle`, porte audio fermée) ;
   - émission pendant le temps de lecture fiable du poste (`settle_s`, § 6 bis) ; lectures du `SWR` et de la
     puissance (`RFPOWER_METER`) sur la seconde moitié ; valeur retenue = médiane des lectures ;
   - retour en RX (`T 0`) confirmé avant le point suivant ;
   - progression envoyée au client (point, fréquence, TOS, puissance).
5. **Fin** (normale, annulée ou coupée) : RX confirmé d'abord, puis remise en état dans l'ordre puissance, mode et
   largeur, fréquence, coupleur, décalages ; chaque valeur est relue ; les écarts sont listés.
6. **Résultat** : points (fréquence, TOS ou « hors bande » / « non lu »), meilleur point (TOS minimal),
   plage où TOS < 1,5 et < 2, puissance utilisée, mode utilisé, heure, état remis et écarts. Rangé dans `swr.json`
   (`last`) et envoyé au client.

## 6 bis. Étalonnage du temps de lecture, au premier usage (par modèle de poste)

Le temps nécessaire pour un TOS fiable dépend du poste (probablement 0,5 s ou moins sur l'IC-7300). Au premier usage de
la mesure avec un modèle de poste (numéro Hamlib absent de `swr.json`), la station le mesure :

1. Une seule prise d'émission sur la fréquence du poste (dans les mêmes conditions qu'un point : FM, puissance choisie,
   coupleur arrêté, porte audio fermée, toutes les règles du § 7), au plus `point_tx_max_s` (2 s).
2. Lecture du `SWR` aussi vite que rigctld répond (environ toutes les 50 à 100 ms) ; « stable » = 3 lectures de suite à
   ±0,05 l'une de l'autre et puissance de sortie lue non nulle.
3. `settle_s` = instant de la première lecture stable + 0,2 s de marge, borné entre 0,3 s et `point_tx_max_s` ;
   jamais stable : `point_tx_max_s` et un avertissement (« lecture du TOS instable sur ce poste »).
4. Rangé dans `swr.json` pour ce modèle ; « Refaire l'étalonnage » dans les réglages de la mesure. L'étalonnage est
   affiché à l'opérateur (« Étalonnage : 0,6 s par point sur ce poste ») et compté dans la durée annoncée de la mesure.

## 7. Sécurité (règles d'émission, priorité absolue)

- Chaque point est une prise d'émission du client qui a lancé la mesure : battements de ce client (~500 ms) exigés
  pendant TOUTE la mesure, battement perdu 2 s = coupure, connexion fermée = coupure immédiate ; TOT de la station
  appliqué à chaque point ; le superviseur garde son TOT absolu et peut tout couper.
- Toute coupure (STOP de n'importe quel client, TOT, battement, déconnexion, opérateur sur place, poste chaud,
  changement de fréquence ou de mode non commandé, refus d'une prise) ARRÊTE la mesure : pas de point suivant ; la
  remise en état est tentée en RX seulement.
- Annuler (`swr_cancel` ou `stop`) : RX immédiat puis remise en état.
- Jamais d'émission au démarrage ni à la reconnexion : une mesure interrompue n'est JAMAIS reprise.
- Porte audio d'émission fermée de bout en bout : rien du micro ne part, même en FM.
- TOS élevé : la mesure CONTINUE (une courbe peut avoir une forme surprenante ; les postes se protègent eux-mêmes et
  15 W ne présentent pas de risque, décision du 2026-11-02) ; un point au-dessus de 5 est marqué « > 5 » ; si le poste
  réduit sa puissance par protection (puissance lue nettement sous la puissance demandée), le point est marqué
  « puissance réduite par le poste ».
- Puissance jamais au-dessus du plafond (`max_power_pct`, 50 % au plus) ; réglée AVANT la première prise, relue.
- Un seul client mesure à la fois ; une mesure en cours bloque `toggle`, SELCALL et les réglages des autres clients
  (refus « mesure de TOS en cours »).
- Tests de panne (faux rigctld, modèle factice) : battement perdu en plein point, déconnexion, STOP d'un autre client,
  TOT, passerelle gelée (superviseur), poste qui ne se relit pas, poste utilisé sur place pendant la mesure, coupure
  pendant l'étalonnage, remise en état après chacune de ces coupures, jamais de reprise après reconnexion.

## 8. Protocole (à ajouter à `docs/protocole.md`)

- Fonction `swr` dans `hello.features` (station avec `[swr] enabled`, opérateurs seulement).
- `swr_plan` : `{band?}` ou `{center_hz, width_hz}`, `points` -> réponse `plan` (FreqBasse, FreqHaute, pas, points
  avec « hors bande », avertissement hors radioamateur, puissance en % et en W, mode FM retenu). N'émet rien.
- `swr_start` : mêmes paramètres + `power_pct` -> réponse immédiate (acceptée ou refus), puis messages ; étalonnage
  d'abord si le modèle n'en a pas (§ 6 bis).
- `swr_calibrate` : refaire l'étalonnage du temps de lecture (une prise d'émission, mêmes règles).
- `swr_cancel` : RX immédiat et remise en état.
- `swr_last` : dernière mesure rangée (pour la réafficher).
- Message `swr` diffusé au client qui mesure : `state` (`preparing`, `calibrating`, `measuring`, `restoring`, `done`,
  `cancelled`, `cut`), `index`, `total`, point courant, points déjà mesurés, et à la fin `result` (§ 6.6) avec l'état remis.
- Motifs de refus nouveaux (texte français dans la page et l'application) : `swr_busy`, `swr_no_fm_mode`,
  `swr_out_of_band`, `swr_too_many_points`, `swr_power_unknown` (si nécessaire), `swr_unreadable`, `swr_unstable` (avertissement de l'étalonnage).

## 9. Affichage (page et application)

- Page de mesure : bande proposée (celle du poste), ou centre + largeur avec le calcul FreqBasse / FreqHaute affiché ;
  nombre de points (pas retenu et nombre réel affichés) ; puissance en % et en W ; durée estimée (étalonnage) ; bouton
  « Lancer la mesure » (désactivé si non armé) ; bouton « Annuler » toujours visible pendant la mesure, avec STOP.
- Fenêtre d'avertissement avant le lancement quand la plage sort des bandes radioamateur (« Vous allez émettre hors
  des bandes radioamateur : responsabilité de l'opérateur »).
- Pendant la mesure : barre de progression, barres qui apparaissent une à une, « ÉMISSION » bien visible.
- Graphique : barres verticales, vertes jusqu'à 1,5, orange de 1,5 à 2, ROUGES au-dessus de 2 ; grises pour « hors
  bande » ; axe vertical non linéaire (1 à 2 étiré, 2 à 5 resserré), plafonné à 5 (au-delà : barre
  pleine marquée « > 5 ») ; lignes horizontales à 1,2 1,3 1,4 1,5 1,8 et 2 ; fréquences en abscisse ; meilleur point
  mis en avant ; barres grises pour « hors bande », hachurées pour « puissance réduite par le poste ».
- Export image (PNG) ANONYME (décision du 2026-11-02) : nom de la mesure demandé à l'opérateur, en légende sous le
  graphique, avec la date, la puissance et le mode ; PAS d'indicatif ni de nom de station ; en pied, le petit logo et
  le lien « www.rf-diy.com ». Logo : l'icône de l'application (`docs/play-store/icone-512.png`) en attendant un logo
  du site fourni par l'utilisateur. Partage par le menu du téléphone (application) ou téléchargement (page).
- Fenêtre « État du poste remis » à la fin ET en quittant la page de la mesure : fréquence, mode, puissance, coupleur,
  décalages, avec les écarts en rouge (« coupleur : non remis, à rallumer à la main »).

## 10. Supervision et outils

- TRX Console : un menu « Dernière mesure de TOS » (lecture seule, depuis `swr.json`) ; jamais de lancement.
- trx-monitor : « Mesure de TOS en cours » dans l'état de la passerelle ; STOP TX l'arrête comme toute émission.
- Bus d'état : `swr` (état, point, total) publié par la passerelle.

## 11. Découpage proposé

1. Calculs purs (plage, pas, points, table des bandes, échelle du graphique) + tests, côté station, page et application.
2. Moteur de mesure et étalonnage dans la passerelle + tests de panne (faux rigctld) + protocole.
3. Page de mesure (web) + export image.
4. Application (écran, partage de l'image).
5. TRX Console (dernière mesure), trx-monitor, mode d'emploi.

## 12. Ce qui n'est PAS fait

- Aucune mesure sans client connecté (pas de mesure planifiée, pas de lancement par la console).
- Aucune reprise automatique d'une mesure interrompue.
- Pas de mesure en BLU ni en CW.

## 13. Réponses de l'utilisateur (2026-11-02)

1. `enforce_bands = false` : aucune bande exigée (projet sans émission sur l'air possible), responsabilité de l'opérateur.
2. TOS élevé : on ne s'arrête pas ; les postes sont protégés, sans risque à 15 W.
3. Durée d'un point : mesurée pour chaque poste au premier usage (§ 6 bis) ; probablement 0,5 s ou moins.
4. Pas d'écoute avant émission (S9 de QRM courant sur 80 m) : option retirée.
5. Image anonyme : pas d'indicatif ; petit logo et lien www.rf-diy.com.

Reste à fournir par l'utilisateur (facultatif) : un logo du site rf-diy.com pour le pied de l'image.
