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
