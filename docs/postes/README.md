# Postes essayés avec TRX distant

Page publique : https://bob56fr.github.io/openRemoteTRX/postes/ (comparaison des postes et fiche de chaque poste,
français / anglais, filtre par thème). Bloc WordPress à coller une fois : `docs/wordpress/postes-iframe.html`.

| Poste | Modèle Hamlib | Statut | Fiche détaillée |
| --- | --- | --- | --- |
| Icom IC-705 | 3085 | validation en cours (qualifié deux fois, même résultat) | `donnees/icom-ic705.toml` |
| Icom IC-7300MK2 | 3094 | validation en cours | `donnees/icom-ic7300mk2.toml` |
| Yaesu FTDX10 | 1042 | validation en cours (réception seulement, jamais essayé en émission) | `donnees/yaesu-ftdx10.toml`, préparation : `yaesu-ftdx10-ftdx101.md` |

## Données

Une fiche par poste dans `donnees/<fabricant>-<modèle>.toml`, source unique des tableaux. Après tout changement :
`python scripts/build_rigs_doc.py` (`tests/test_rigs_doc.py` refuse une page périmée ou une fiche incohérente).

- `[poste]` : `fabricant`, `modele`, `hamlib_model`, `statut` (`valide`, `restreint`, `validation_en_cours`,
  `refuse`), `resume` et `resume_en`.
- `[[essais]]` : `date`, `station`, `hamlib`, `systeme`, `quoi` / `quoi_en`. Un résultat vaut pour ces versions.
- `[fonctions]` : TOUTES les fonctions de la liste `FEATURES` de `scripts/build_rigs_doc.py`, chacune avec `etat` =
  `valide`, `partiel`, `echec`, `non_teste` (affiché « non testé (1) ») ou `non_declare` (affiché « non disponible
  (2) ») ; `note` / `note_en` obligatoires pour `partiel` et `echec` ; `cause` obligatoire pour `non_declare` :
  `hamlib` (Hamlib ne la propose pas pour ce modèle), `poste` (la CAT du poste ne la donne pas) ou `trx_distant`
  (pas encore programmée). Les notes (1) et (2) sont en bas de la page publique.
- `[hamlib]` : `non_exploite` (proposé par Hamlib, pas utilisé par TRX distant), `constats` / `constats_en`.

Règles : chaque état vient d'un essai réel (qualification, valise de qualification) ; un poste n'est `valide` ou
`restreint` que si TOUTE la sécurité d'émission est `valide` ; la comparaison ne montre que `valide` et `partiel`, et
jamais un poste `refuse`. Contenu public : ni indicatif, ni adresse, ni nom de machine, ni numéro de série.

Une nouvelle fonction s'ajoute à `FEATURES` (thème, libellés français et anglais) ET à chaque fiche.
