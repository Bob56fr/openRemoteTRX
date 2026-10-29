# Scrambler de voix (bandes inversées et permutées)

État : **fait (station 0.68.0, application 0.23.0, étape 81)**. Il reste à l'essayer sur l'air entre deux postes.

## Décision

Demande de l'utilisateur, le 2026-10-29. Elle a été maintenue malgré les réserves exprimées : le Règlement des
radiocommunications de l'UIT (art. 25) et la réglementation nationale interdisent, en bandes radioamateur, les
émissions destinées à masquer le sens des messages.

- Utilisable sur toutes les fréquences, sous la responsabilité de l'utilisateur.
- Désactivé par défaut et à chaque démarrage : seuls le mode et le décalage sont gardés.
- Un message clair et une confirmation sont demandés à chaque mise en service.
- Un voyant « SCRAMBLER » (ou « DÉBROUILLAGE ») reste visible près du PTT.
- Ce n'est PAS un chiffrement : tout possesseur d'un scrambler identique entend la voix.

## Principe

Le traitement est fait **dans le client** (page web ou application). La station n'en sait rien et le protocole ne
change pas.

- **Émission** : la voix est brouillée juste avant le limiteur de l'égaliseur. Le limiteur reste en bout de chaîne.
- **Réception** : la voix est débrouillée avant le haut-parleur.
  - Page : AudioWorklet, puis le même élément `<audio>` (volume, sourdine et sortie inchangés).
  - Application : `ExternalAudioProcessingFactory.setRenderPreProcessing` de WebRTC.
- Les tonalités SELCALL et les bips de fin, produits par la station, ne sont pas brouillés.

## Calcul (`scrambler.js`, `logic/Scrambler.kt`, même résultat)

- Transformée de Fourier à court terme de 2 048 points à 48 kHz, demi-recouvrement, fenêtres racine de Hann. Le retard
  est d'environ 43 ms par sens.
- La bande 300-3 000 Hz est découpée en 1 à 5 bandes de même largeur. Leurs limites tombent sur des bins **pairs**,
  avec un bin libre entre deux bandes.
  - Chaque bande est recopiée dans une autre case (permutation), à l'endroit ou retournée (inversion = miroir et
    conjugué).
  - Comme tout déplacement est d'un nombre pair de bins, le résultat ne dépend pas du découpage en trames. L'émetteur
    et le récepteur n'ont donc pas à être synchronisés.
  - Seule reste une rotation de phase constante par bande, inaudible.
- **Décalage fin en réception** (±300 Hz) : une BLU mal accordée décale toutes les fréquences. L'inversion transforme
  ce décalage en décalage opposé, ce qui empêche le débrouillage. Un décaleur de fréquence (transformée de Hilbert,
  127 coefficients) corrige le décalage avant le débrouillage. Le RIT du poste fait le même travail.

## Modes prêts à l'emploi

| Clé | Libellé | Bandes | Permutation | Inversion |
|---|---|---|---|---|
| inv1 | Inversion simple (1 bande) | 1 | 0 | oui |
| inv2 à inv5 | 2 à 5 bandes inversées | 2 à 5 | aucune | toutes |
| mix2 | 2 bandes échangées | 2 | 1 0 | non |
| mix3 | 3 bandes mélangées | 3 | 2 0 1 | 1, 3 |
| mix4 | 4 bandes mélangées | 4 | 1 3 0 2 | 1, 2 |
| mix5a | 5 bandes mélangées A | 5 | 4 2 0 3 1 | toutes |
| mix5b | 5 bandes mélangées B | 5 | 2 4 1 0 3 | 2, 4, 5 |

Les correspondances de bins de chaque mode sont dans `tests/protocol/scrambler_modes.json`, fabriqué par
`scrambler.js`. La page et l'application doivent les retrouver exactement.

## Essais

- **Node** (`tests/js/scrambler_test.js`) et **JVM** (`ScramblerTest`), mêmes cas :
  - limites paires ;
  - fichier commun ;
  - plus rien aux fréquences d'origine une fois brouillé ;
  - plus de 30 dB après débrouillage, pour des décalages dans le temps de 0, 333 et 777 échantillons ;
  - BLU décalée de 40 Hz rétablie par le décalage fin ;
  - réglages jamais réactivés seuls.
- **Chromium réel** (AudioWorklet) : un ton de 1 000 Hz sort à 2 282 Hz une fois brouillé (inv1), puis revient à
  1 000 Hz après débrouillage.
- **Application** :
  - le limiteur reste en bout de chaîne avec le scrambler ;
  - aucun reste de l'émission précédente au début de la suivante.
- **Auto-essai sans émettre** dans l'application : « Relire » joue la prise brouillée. Avec « Débrouiller », la voix
  doit redevenir claire.
- **À faire** : essai sur l'air entre deux postes, en BLU puis en FM, avec plusieurs modes et le décalage fin.
