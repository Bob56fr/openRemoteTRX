# Postes essayés avec openRemoteTRX

Page publique : https://bob56fr.github.io/openRemoteTRX/postes/ (comparaison des postes et fiche de chaque poste,
français / anglais, filtre par thème). Bloc WordPress à coller une fois : `docs/wordpress/postes-iframe.html`.

Postes POTENTIELLEMENT compatibles (pas essayés) : `usb-integre.toml`, postes à USB intégré pour la CAT et le son (un seul câble), d'après la documentation des fabricants ; section « Postes à USB intégré » en fin de la même page.

| Poste | Modèle Hamlib | Statut | Fiche détaillée |
| --- | --- | --- | --- |
| Icom IC-705 | 3085 | validation en cours (qualifié deux fois, même résultat) | `donnees/icom-ic705.toml` |
| Icom IC-7300MK2 | 3094 | validation en cours | `donnees/icom-ic7300mk2.toml` |
| Yaesu FTDX10 | 1042 | validation en cours (réception seulement, jamais essayé en émission) | `donnees/yaesu-ftdx10.toml`, préparation : `yaesu-ftdx10-ftdx101.md` |

PRÉQUALIFICATIONS (étape 374) : rapports de l'openRemoteTRX-Autotest dans `autotest/*.toml`, montrés À PART
(section « Préqualifications en cours (Autotest) ») pour qu'un visiteur voie qu'un poste est en cours d'essai. Ils ne
changent JAMAIS une fiche ni une note. Import : `python scripts/import_autotest.py RAPPORT.json [--source utilisateur]`
(champs publics seulement, empreinte de la trace vérifiée), puis écrire `resume` / `resume_en`, chaque `texte_en`, et
`note` / `note_en` quand un résultat est trompeur ; enfin `python scripts/build_rigs_doc.py`.

## Données

Une fiche par poste dans `donnees/<fabricant>-<modèle>.toml`, source unique des tableaux. Après tout changement :
`python scripts/build_rigs_doc.py` (`tests/test_rigs_doc.py` refuse une page périmée ou une fiche incohérente).

- `[poste]` : `fabricant`, `modele`, `hamlib_model`, `statut` (`valide`, `restreint`, `validation_en_cours`,
  `refuse`), `resume` et `resume_en`.
- `[poste] stabilite` : `ok` (aucun défaut aléatoire pendant les essais) ou `defauts` (avec `stabilite_note` /
  `stabilite_note_en`) ; sans ce champ, pas de note.
- `[[essais]]` : `date`, `station`, `hamlib`, `systeme`, `quoi` / `quoi_en`. Un résultat vaut pour ces versions.
- NOTE SUR 5 ÉTOILES (« fonctionne avec openRemoteTRX », décision de l'utilisateur du 2026-11-19, `rating` de
  `scripts/build_rigs_doc.py`) : validé = 1, partiel = ½, ne fonctionne pas = 0, `non_declare` de cause `hamlib` ou
  `trx_distant` = ½ ; `non_declare` de cause `poste` (choix du constructeur) HORS du calcul ; `non_teste` hors du calcul,
  note « provisoire » ; aucune note tant que la sécurité d'émission n'est pas entièrement validée ni sans `stabilite` ;
  `defauts` = 3 étoiles au plus. Le statut « restreint » reste pour un vrai problème d'usage à distance, jamais pour une
  absence du constructeur.
- `[fonctions]` : TOUTES les fonctions de la liste `FEATURES` de `scripts/build_rigs_doc.py`, chacune avec `etat` =
  `valide`, `partiel`, `echec`, `non_teste` (affiché « non testé (1) ») ou `non_declare` (affiché « non disponible
  (2) ») ; `note` / `note_en` obligatoires pour `partiel` et `echec` ; `cause` obligatoire pour `non_declare` :
  `hamlib` (Hamlib ne la propose pas pour ce modèle), `poste` (la CAT du poste ne la donne pas) ou `trx_distant`
  (pas encore programmée). Les notes (1) et (2) sont en bas de la page publique.
- `[hamlib]` : `non_exploite` (proposé par Hamlib, pas utilisé par openRemoteTRX), `constats` / `constats_en`.

Règles : chaque état vient d'un essai réel (qualification, valise de qualification) ; un poste n'est `valide` ou
`restreint` que si TOUTE la sécurité d'émission est `valide` ; la comparaison ne montre que `valide` et `partiel`, et
jamais un poste `refuse`. Contenu public : ni indicatif, ni adresse, ni nom de machine, ni numéro de série.

Une nouvelle fonction s'ajoute à `FEATURES` (thème, libellés français et anglais) ET à chaque fiche.
