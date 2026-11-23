# Postes essayés avec openRemoteTRX

Page publique : https://bob56fr.github.io/openRemoteTRX/postes/ (comparaison des postes et fiche de chaque poste,
français / anglais, filtre par thème). Bloc WordPress à coller une fois : `docs/wordpress/postes-iframe.html`.

Postes POTENTIELLEMENT compatibles (pas essayés) : `usb-integre.toml`, postes à USB intégré pour la CAT et le son (un seul câble), d'après la documentation des fabricants ; section « Postes à USB intégré » en fin de la même page.

| Poste | Modèle Hamlib | Verdict (calculé) | Fonctions complémentaires | Fiche détaillée |
| --- | --- | --- | --- | --- |
| Icom IC-7300MK2 | 3094 | ★ GO | 5 complet (24/24) | `donnees/icom-ic7300mk2.toml` |
| Yaesu FTDX10 | 1042 | ★ GO (qualifié avec la valise le 2026-11-19) | 4 très bon (17/23) | `donnees/yaesu-ftdx10.toml`, préparation : `yaesu-ftdx10-ftdx101.md` |
| Icom IC-705 | 3085 | ★ GO avec réserve (son reçu faible sur charge fictive) | 4 très bon (17/22) | `donnees/icom-ic705.toml` |
| Icom IC-7100 | 3070 | préqualification (Autotest) | — | `autotest/icom-ic-7100-20261123-1507.toml` |

Tableau au 2026-11-23 : la page publique le recalcule à chaque fabrication.

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
- DOUBLE NOTATION (décisions de l'utilisateur du 2026-11-23, étape 376 ; remplace la note sur 5 étoiles de l'étape
  277, qui faisait lire un 4,5 comme « insuffisant ») : rien à saisir, tout est calculé (`verdict` et `level` de
  `scripts/build_rigs_doc.py`).
  a) VERDICT « Utilisable à distance » sur la liste FERMÉE `VITAL` : les 8 fonctions de sécurité d'émission, la
  fréquence, le son reçu et la modulation par l'USB, plus un mode modulable par l'USB (le meilleur de `modes_base` et
  `modes_donnees`). GO = toutes validées ; GO avec réserve = aucune en échec, au moins une partielle (ou statut
  `restreint`, ou `stabilite = "defauts"`) ; NO-GO = une en échec ou non disponible (quelle que soit la cause), ou
  statut `refuse` ; pas encore évalué = au moins une non testée. Une étoile devant le GO, nulle part ailleurs. Un
  NO-GO est MONTRÉ, avec sa raison.
  b) NIVEAU des fonctions COMPLÉMENTAIRES (toutes les autres), seulement avec un GO : validé = 1, partiel = ½, ne
  fonctionne pas = 0, `non_declare` de cause `hamlib` ou `trx_distant` = ½ ; cause `poste` et `non_teste` HORS du
  calcul ; niveau 1 « essentiel » (< 50 %), 2 « base », 3 « bon » (≥ 65 %), 4 « très bon » (≥ 80 %), 5 « complet »
  (≥ 95 %) ; `defauts` = niveau 3 au plus. Affiché en bargraph de S-mètre tout en verts (jamais de jaune ni de rouge).
  Le statut « restreint » reste pour un vrai problème d'usage à distance, jamais pour une absence du constructeur.
- Page : résumé en tête en deux colonnes (« Utilisables à distance » | « En cours d'évaluation », NO-GO et
  préqualifications à droite), comparaison ouverte, fiches et liste USB REPLIÉES (un lien les ouvre ; tout s'ouvre à
  l'impression).
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
