# Journal de la branche exp/cw (laboratoire CW)

- 2026-11-26 : branche créée depuis `main` 7cfdade3 (dossier `C:\dev\openRemoteTRX-cw`). Cahier v1 de l'utilisateur
  relu ; décisions prises (exception PTT limitée à la CW armée, PTT tenu pendant l'armement, canal sans
  retransmission + bail, ordre des lots, mode D abandonné). Cahier v2 : `cahier-des-charges.md`. Aucun code.
  Prochain : lot CW-0 (ordonnanceur, bail, tonalité, banc de simulation), dans une conversation ouverte dans ce dossier.
- 2026-11-26 : LOT CW-0 FAIT (calculs purs, aucun effet sur la station ; version inchangée, la version d'essai
  `X.Y.Z.devN+cw` viendra avec le lot CW-1 qui touche la passerelle). `trxstation/cw/` : `protocol` (paquets du
  canal `cw` validés), `tone` (tonalité à l'échantillon près, cosinus surélevé), `player` (ancre, ré-ancrage, bail,
  appui trop long, fin de séquence, STOP), `jitter` (rejeu adaptatif entre séquences), `sim` (manipulateur PARIS,
  client, réseau : gigue, pertes, coupures, gels 4G), `analysis` (fronts dans le son, clics, largeur) ; banc
  `python -m trxstation.devtools.cw_bench` ; 107 tests `tests/test_cw_*.py`. Résultats : cahier § 14.
  Constats : (1) le client doit envoyer toutes les 20 ms pendant toute la séquence, pas seulement clé fermée (front
  d'ouverture perdu = élément allongé) : cahier § 5.1 corrigé ; (2) une gigue uniforme ne coûte rien grâce à la
  fenêtre, le vrai risque est le GEL de liaison (rafale) : rejeu 300 ms tient des gels jusqu'à ~300 ms ; (3) la
  démodulation par moyenne glissante décalait les fronts de 3 à 5 échantillons : signal analytique (FFT) à la place.
  Interprétation notée au § 5.3 : « front d'ouverture en retard » du v2 = front de FERMETURE de la clé (début de
  tonalité) -> ré-ancrage ; fin de tonalité en retard = jouée tout de suite.
  DÉCISION DE L'UTILISATEUR (même jour) : la CW se fera SEULEMENT sur l'écran tactile Android (tablette, smartphone),
  jamais dans la page web : cahier v3 (§ 2 décision 5, § 7 = application, CW-2 = application).
  Suite complète (tour radio) : 3044 réussis, 3 échecs SANS LIEN avec la CW : ce dossier a été extrait avec
  `core.autocrlf = true` (réglage système de Git), fichiers en CRLF alors que les tests attendent du LF
  (`test_i18n_hwtest::test_catalog_files_are_written_like_the_others`, deux tests de `test_user_guide.py`) ;
  à corriger par une nouvelle extraction en LF du dossier (`git -c core.autocrlf=false checkout-index -f -a`).
  Prochain : lot CW-1 (mode A dans la passerelle, poste factice Hamlib n° 1).
- 2026-11-26 : maquette de l'onglet CW de l'application (https://claude.ai/artifact/NSXTCo2XT6RbHpxLVBt2pt) :
  smartphone 2 palettes / 1 palette, tablette en paysage ; retour de l'utilisateur : STOP et « Quitter » tout en
  haut, plus de barre d'onglets en bas sur le smartphone, tablette validée (cahier § 7).
- 2026-11-26 : LOT CW-1 FAIT (V1 seulement : PTT tenu pendant l'armement ; V2 « hang » refusée par config.py).
  `trxstation/gateway/cw.py` (`CwKeyer`) : `cw_arm` = `key_without_audio` (prise normale, micro fermé) après
  vérification du mode (`[cw] data_mode`, jamais changé par la station) et de la porteuse + fréquence affichée dans
  les bandes, contrôle APRÈS la prise que le PttController a relu la même chose (`tx_reading`, ajouté à ptt.py avec
  `read_transmit_plan`, lecture seule) ; rendu au rythme réel, 60 ms d'avance au plus, à l'échantillon près
  (`trxstation/cw/player.py`) ; écouteur synchrone du PttController : toute coupure (STOP, TOT, battement,
  déconnexion) jette le tampon AVANT « T 0 » ; fins propres à la CW (désarmement, bail, appui trop long,
  inactivité 8 s, rendu en retard > 0,25 s) = fermeture adoucie puis `force_rx`. Canal de données `cw` dans
  webrtc.py (opérateurs seulement), commandes `cw_arm` / `cw_disarm` (protocol.py, commands.json, protocole.md
  § 22), `toggle` du propriétaire armé = désarmer, `cw_arm` refusé pendant une mesure de TOS, fonction `cw` de
  `hello.features`, `[cw]` dans config.py (textes `cw.*` des 4 catalogues `checks`), refus `cw_*` et coupures
  `cw_*` dans les 4 catalogues `client`, mesures par séquence dans `<state_dir>/cw/sequences.jsonl` (ni son, ni
  texte). 20 tests de panne `tests/test_cw_gateway.py` (poste factice) : passés 3 fois de suite.
  Décisions d'exécution : aucun code ORT nouveau dans la branche (journal en `log.info`, les coupures passent
  par ORT-5031 de `force_rx`) : codes à créer à l'adoption ; VERSION INCHANGÉE (0.289.0) pendant le POC : changer la
  version fabriquerait des copies publiques des modes d'emploi par version (console, station.toml) sous un nom
  d'essai ; `[cw]` absente de la notice de station.toml et de `render_toml` (cahier § 10 : à l'adoption).
  Suite complète (tour radio) : 3069 réussis, 3 échecs déjà connus des fins de ligne CRLF de ce dossier (voir
  plus haut), aucun lié à la CW.
  À FAIRE en tête du lot CW-2 : `cw_arm` / `cw_disarm` dans `android/protocol` (Command, NAMES), sinon le test de
  contrat Android (commands.json) échoue ; superviseur et trx-monitor ne voient rien de propre à la CW (émission
  normale d'un client) : suffisant pour le POC.
  Prochain : lot CW-2 (onglet CW de l'application, d'après la maquette).
- 2026-11-26 : LOT CW-2 FAIT EN CODE (application ; essais dans l'émulateur et sur un vrai appareil PAS faits).
  `:protocol` : `Command.CwArm` / `CwDisarm`, message `CwMessage` (cw_state, cw_fault, cw_stats), fonction `cw`.
  `:logic` `Cw.kt` (Kotlin pur, Lite compris) : `CwKeyer` (pioche, iambique A / B, simple levier, poids, inversion ;
  fronts CALCULÉS à la milliseconde, pas mesurés au rappel), `CwPacketizer` (règle du § 5.1 : mêmes paquets que le banc
  Python, vecteurs partagés `tests/protocol/cw_vectors.json` fabriqués par `scripts/build_cw_vectors.py`, rejoués d'un
  coup ET en temps réel par pas de 5 ms), `CwDecoder` (sa propre manipulation), `CwClient` ; `RigSession` :
  `cwArm` (battements dès la demande), `cwDisarm`, `cwPress`, `cwPoll`, micro JAMAIS ouvert tant que la CW est armée
  ou demandée, fin de l'armement venue de la station (`cw_state idle`) ou de la liaison perdue ; `SessionLink.sendCw`
  (défaut : rien, Lite inchangé). `:core` : canal WebRTC `cw` (non ordonné, sans renvoi), rappel de 5 ms pendant
  l'armement (`RigService`), retour local `CwSidetone` (AudioTrack faible latence, fronts de 5 ms), instant du toucher
  pris à l'événement (horloge `elapsedRealtime`). `:app` `CwTab.kt` d'après la maquette : onglet « CW » (seulement si
  annoncé), smartphone plein écran sans barre d'onglets (STOP et Quitter en haut, synthèse, réglages, sélecteur 1 / 2
  palettes, palettes multitouches avec vibration), tablette (rail sur le côté) ; quitter l'onglet, le mode conduite ou
  une ROTATION de l'écran (activité recréée) DÉSARMENT. Textes `cw.*` en 4 langues (« TOT {time} » dans identical.json).
  Station : correctif du rejeu (`player.py`) : une nouvelle séquence du client arrivée pendant le silence de fin de la
  précédente la termine normalement (avant : `seq_overlap` et désarmement à chaque nouvelle séquence en vrai) ; banc
  WebRTC réel `tests/test_webrtc.py::test_cw_channel_end_to_end` (aiortc, canal `cw`) : passé 2 fois.
  Décisions d'exécution : « Armer CW » n'exige PAS « Émission autorisée » (le bouton est lui-même l'action délibérée ;
  à revoir si l'utilisateur le veut) ; réglages gardés sur le téléphone (`ui` : `cw_*`). Pas faits : rejet de la paume,
  affichage de la latence du retour local (`CwSidetone.latencyMs` mesurée, pas montrée), essai dans l'émulateur contre
  une fausse station, vrai téléphone et tablette.
  Tests : Android sur tour radio (dossier à part `C:\dev\openRemoteTRX-cw-and`) 265 réussis, 0 échec, APK de
  débogage dans `dist\openRemoteTRX-cw-debug.apk` (hors dépôt) ; suite Python 3070 réussis, 3 échecs connus CRLF.
  Prochain : essai émulateur + fausse station, puis CW-3 (IC-7300MK2 sur charge fictive).
- 2026-11-26 : ESSAI DANS L'ÉMULATEUR contre une station factice, sur tour radio (Android 17, Medium_Phone_API_37.0,
  sans fenêtre ; scripts dans `docs/exp-cw/emulateur/`) : vraie passerelle de la branche, faux rigctld mis en PKTUSB
  sur 7,030 MHz AVANT la passerelle, `[cw] enabled = true`, ports à part 18443 / 14532 / 47910, son émis enregistré
  dans un WAV et mesuré par `analyse.py` (`trxstation/cw/analysis.py`). RÉSULTATS : connexion (8 ms), onglet CW
  présent, armement = émission (« TX · CW ARMED », TOT), manipulation par l'écran tactile (`input swipe`) reçue par le
  canal `cw` : iambique B à 20 wpm = points 60,000 ms, traits 180,000 ms, espaces 60,000 ms dans le son de la station
  (aucun clic : plus grand saut = celui d'une sinusoïde pure ; -33 dB hors de ±150 Hz), gigue p95 18 ms, 0 paquet en
  retard ; clé droite (1 palette) : appuis de 700 / 250 ms rendus 710 / 264 ms (durée réelle d'`adb swipe`) ; palette
  tenue 3 s sans coupure (battements maintenus) ; 8 s sans manipuler = `cw_idle` ; STOP = réception en 0,12 s ; Close =
  désarmé en 0,48 s (`cw_disarm`) et retour à l'onglet Station ; application tuée = réception en 2,06 s (battements) ;
  réseau coupé = réception en 2,1 s (battements). DÉFAUTS TROUVÉS ET CORRIGÉS : rangée STOP / Close sous la barre
  d'état (l'écran CW n'avait pas les marges de la fenêtre : `modifier` de RigScreen) ; fréquence « 7 030 700 Hz MHz
  porteuse » (`cw.carrier`) ; un message de fin INSÉRÉ décalait « Armer CW » et les palettes (un toucher tombait à
  côté) : place réservée d'une ligne ; « CW désarmée : CW désarmée faute de manipulation » (cause propre à la CW dite
  une fois : `cw.ended_own`, test). Deux lignes de `config.py` et `protocol.py` recollées par un script de remplacement
  (sans effet) remises en forme. Tests : Android 266 / 0 ; Python 3070 réussis, 3 échecs CRLF connus et
  `test_qualif_autodrills::test_the_out_of_band_drill_is_refused_and_the_frequency_restored` sensible à la charge (passe
  seul, 14 / 14). Pièges : clavier de l'émulateur qui double des caractères (saisir par morceaux de 12 et vérifier),
  touche Retour = sortie de l'application quand aucun clavier n'est ouvert, un WAV en cours d'écriture paraît vide dans
  `dir` (le copier pour le lire). Non essayé dans l'émulateur : deux palettes pressées ensemble (multitouche), retour
  local (émulateur sans son), tablette, rotation.
  Prochain : vrai téléphone (S25) et tablette, puis CW-3 (IC-7300MK2 sur charge fictive).
- 2026-11-26 : « ÉMISSION AUTORISÉE » EXIGÉE POUR ARMER LA CW (décision de l'utilisateur, à la place du choix
  d'exécution du lot CW-2). `RigSession.cwArm` refuse sans elle (`cw.arm_first`, 4 langues, aucun `cw_arm` envoyé) ;
  la retirer pendant l'armement désarme (`setArmed(false)` -> `cwDisarm`) ; interrupteur « Émission autorisée » dans
  l'onglet CW au-dessus du sélecteur (smartphone et tablette), ARM CW terne tant qu'elle est coupée. Tests Android
  268 / 0 (2 nouveaux). Émulateur : ARM CW sans elle = refus expliqué, station en RX ; avec = TX ; retirée = RX en
  0,23 s (`cw_disarm`). Piège : le Python d'un venv relance l'interpréteur de base (deux processus par programme) :
  `stop-station.ps1` tue l'arbre (`taskkill /T`), sinon l'ancienne passerelle garde le port 18443.
- 2026-11-26 : SUITE DU LOT CW-2 ET VARIANTE V2 (« hang ») CODÉE, préalables du lot CW-3.
  IAMBIQUE À DEUX PALETTES PRESSÉES ENSEMBLE essayé dans l'émulateur (`squeeze.ps1` : événements multitouches par la
  console de l'émulateur `adb emu event send`, l'image Google refusant `sendevent` sans root) : son de la station
  « · – · – · » (alternance puis élément opposé au relâché, mode B), points 60,000 ms, traits 180,000 ms.
  LATENCE DU RETOUR LOCAL affichée (« Retour local N ms », tampon de l'AudioTrack) avec les mesures du rejeu (tablette).
  REJET DE LA PAUME pas fait : Compose ne donne pas la taille du contact et le seuil se règle sur un vrai écran
  (essai S25 / tablette). V2 (`[cw] ptt_variant = "hang"`, `hang_ms` 600, 200 à 3000) : après `hang_ms` de silence la
  passerelle relâche le PTT (`force_rx("cw_hang")`), la CW reste armée et RIEN n'est écrit vers le poste ;
  l'ordonnanceur avance en silence sans jouer aucun front (`CwPlayer.hold`) ; au front de fermeture suivant, reprise
  par le MÊME chemin que l'armement (`CwKeyer._take` : mode, porteuse, bandes, `key_without_audio` et tous ses refus,
  anti-rebond `cooldown` attendu au plus 3 s, jamais baissé), le point en attente sort ENTIER, retardé (`resume`,
  compté `hang_reanchors`, pas `late`) ; refus = `cw_fault retake_refused` puis désarmée (`cw_retake_refused`) ; toute
  coupure venue d'ailleurs pendant la pause (STOP, autre client : `epoch` du PttController au-delà de celui du relâché)
  désarme POUR DE BON. Application : `cw_state hang` = badge vert « RX · CW EN PAUSE », pas de bip de prise / fin
  tant que la CW est armée, son reçu atténué de 20 dB pendant l'armement (cahier § 6 ; RtcLink et SpatialHub).
  Textes `coupure.cw_hang`, `coupure.cw_retake_refused`, `cw.badge_hang`, `cw.st_sidetone` en 4 langues ;
  `docs/protocole.md` § 22. Tests : 4 tests de panne V2 avec le poste factice (relâché puis repris, STOP pendant la
  pause, poste changé pendant la pause, anti-rebond attendu), test de l'ordonnanceur, test Android de la pause ;
  Android 269 / 0 ; Python 3076 réussis, 3 échecs CRLF connus. Émulateur en V2 (`v2.ps1`, station factice
  `--variante hang`) : PTT relâché ~1 s après chaque point (rejeu 300 + 600), CW armée, point suivant = émission en
  moins de 80 ms, les deux points de 60,000 ms, son écrit seulement pendant les émissions. Remarques : en V2 le TOT
  compte par reprise ; un QSY redevient possible pendant la pause (la reprise revérifie mode, porteuse et bandes) ;
  l'armement V2 émet ~600 ms sans son avant la première pause (aucune puissance en mode données sans audio).
  Prochain : vrai téléphone (S25) et tablette (rejet de la paume à régler), puis CW-3 sur l'IC-7300MK2, V1 puis V2.

- 2026-11-28 : fusion de `main` (15 commits ; conflits d'ajouts seulement ; la CW hérite de la vérification du décalage
  relais par `key_without_audio`). S25 contre la station factice V2 ouverte au réseau local : onglet CW refait
  (fréquence seule sur sa ligne, palettes ~600 px), badge vert « RX · CW EN PAUSE » vu, quatre pauses / reprises
  (`cw_hang`), points 60,000 ms et trait 180,000 ms entiers après chaque reprise, -34 dB hors de ±150 Hz, STOP pendant
  la pause = CW désarmée « bouton STOP ». Détails à reprendre : texte « (votre manipulation décodée) » coupé, « + » de
  la vitesse collé au chiffre. Restent : rejet de la paume, tablette, CW-3 sur l'IC-7300MK2.
- 2026-11-28 (suite) : zone de décodage défilable vérifiée sur le S25 (36 lettres : ligne ramenée sur la dernière,
  retour au début au doigt), texte d'attente sur une ligne, − / + de la vitesse lisibles.
- 2026-11-28 (suite) : banc du décodeur de sa manipulation (`CwDecoderBenchTest`, 18 poignets simulés, rapport et
  retex dans `banc-decodeur.md`) : lecture parfaite d'un poignet propre ; limites = seuils fixes de la vitesse réglée,
  espaces, prosignes absents. Pas de décodage de la réception (hors du cahier).
- 2026-11-28 (suite) : essai à la main et à la paume RÉUSSI sur le S25 (utilisateur) ; tablette plus tard. Onglet
  CW RETIRÉ (décision de l'utilisateur) : la page CW s'ouvre en touchant le mode CW ou CWR, sans changer le mode du
  poste ; bouton « CW » ajouté aux modes quand la station propose la CW et que le poste ne l'annonce pas (station
  factice sans Hamlib) ; vérifié sur le S25 (page ouverte, poste resté en PKTUSB, « Quitter » = onglet Station).
- 2026-11-28 (suite) : CW-3 sur l'IC-7300MK2 (minix-bzh, station de la branche lancée par son superviseur en mode
  géré dans `~/cw-essai`, station installée arrêtée ; charge fictive, 10 % de puissance, 7,030 MHz, S25 en Wi-Fi).
  Premier armement REFUSÉ `cw_mode` (poste en USB : la station ne change jamais le mode) ; passage du poste en CW
  puis PKTUSB = « poste utilisé sur place », main reprise (ORT-5007). V1 : armée 13:44:26, PTT tenu 47 s, puissance
  ~0,11 à chaque élément et 0 entre eux, TOS 1,0, désarmée seule `cw_idle`, signes NETS au second récepteur ; ALC
  souvent 0,9 à 1,0 (USB MOD Level fort pour une tonalité pure, sans claquement entendu). V2 : cinq pauses / reprises
  `cw_hang` en 14 s, désarmée `cw_idle`, aucune autre coupure. 4G non faite (essai court voulu). À faire : bouton
  « Passer en PKTUSB » dans la page CW (commande de mode de l'opérateur, jamais automatique), choix de la variante
  par défaut.
- 2026-11-28 (suite) : décisions de l'utilisateur après CW-3 : V2 PAR DÉFAUT (`[cw] ptt_variant = "hang"` ; banc
  des tests resté en V1 sauf mention) et bouton « PASSER EN PKTUSB » : `hello.cw = {mode, variant}` (null sans
  `[cw] enabled` et pour un visiteur), la page CW remplace « Armer CW » par ce bouton tant que le poste relu n'est pas
  dans le mode exigé ; un toucher = `set_mode` ORDINAIRE de l'opérateur (la station ne change toujours jamais le mode
  d'elle-même, ce n'est pas une action « sur place »). Python 3142 réussis (4 échecs CRLF connus), Android 275 / 0.
  À voir sur le S25 contre l'IC-7300MK2 : poste en USB = bouton « PASSER EN PKTUSB », toucher = « ARMER CW ».
