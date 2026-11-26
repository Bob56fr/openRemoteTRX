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
