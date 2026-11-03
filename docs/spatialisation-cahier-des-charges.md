# Spatialisation stéréo de l'audio reçu (« ST ») : cahier des charges v2

v1 : document de l'utilisateur du 2026-11-03. v2 (même jour) : corrections après relecture, décisions de l'utilisateur :
exception au gel de la page et de l'application après la mesure de TOS, V1 sur `main`, étude « FI 12 kHz » sur une
branche à part (`exp/st-fi`, abandonnable).

## 1. But

Transformer l'audio reçu mono en stéréo pour l'écoute au casque : confort d'écoute, séparation perçue, effet
immédiatement audible. Objectif réaliste : **confort et préférence d'écoute**, pas un gain mesurable en signal faible
(voir § 8).

## 2. Périmètre

- Traitement **côté client seulement** (page, application). Le flux réseau reste mono, la station n'est pas touchée,
  ni le protocole, ni `hello.features`. Chaque auditeur règle son effet, visiteurs compris.
- Jamais sur le micro ni sur l'émission.
- Android Auto : toujours mono (bypass).
- iOS : hors périmètre (aucune application).

Chaîne de la page : flux reçu → débrouillage du scrambler (s'il est en service) → **spatialisation** → limiteur
stéréo (toujours actif quand ST est en service) → élément audio (volume, sourdine, sortie inchangés).

## 3. Moteurs (V1)

Tous les moteurs produisent un couple **milieu / côté** (M, S) de même puissance que le signal ; la sortie est
`G = g·(M + w·S)`, `D = g·(M − w·S)`, `g = 1/√(1 + w²)` (sonie égale au mono à ±1 dB).

| Moteur | M | S | Somme G + D |
| --- | --- | --- | --- |
| Décorrélation | signal | signal passé dans 6 filtres passe-tout de Schroeder (retards 1 à 7 ms, graine fixe) | égale au signal (parfaite) |
| Binaural | (A + B)/√2 | (A − B)/√2 | plate, −3 dB à w = 1 |

Binaural : A et B = paire de filtres passe-tout à 90° (structure de Niemitalo, 4 cellules du 2e ordre par voie,
déphasage 90° ± 1° de 20 Hz à 20 kHz, amplitude plate, latence quasi nulle). Le FIR de Hilbert de la v1 est écarté :
amplitude qui chute en bas de bande, latence, retard à compenser. La « fréquence centrale binaurale » de la v1 est
supprimée (sans objet avec un déphasage constant).

Étage commun :
- **Intensité** w : 0 à 150 %.
- **Présence voix** p : 0 à 100 %, retire du côté S la part 300 à 2 700 Hz (S ← S − p·passe-bande(S)) : la voix reste
  au centre, le souffle hors de la bande garde sa largeur.
- **Équilibre** : −100 à +100.
- Paramètres lissés (20 ms), changement de moteur ou de préréglage et bypass A/B en fondu de 50 ms.
- Limiteur stéréo lié, plafond −1 dBFS, non désactivable.

## 4. Préréglages (V1, lecture seule)

| Clé | Nom | Moteur | Intensité | Présence |
| --- | --- | --- | --- | --- |
| `mono` | Mono | aucun (bypass) | — | — |
| `comfort` | Confort | Décorrélation | 70 % | 40 % |
| `dx` | DX BLU | Binaural | 80 % | 25 % |
| `cw` | CW binaural | Binaural | 100 % | 0 % |

« Confort » au premier usage. Un curseur bougé = « Nom (modifié) ». Valeurs communes à la page et à l'application :
`tests/protocol/spatial_presets.json` (fabriqué par `spatial.js`, relu par les tests des deux côtés).

## 5. Interface

- Bouton **ST** dans la ligne des boutons du client (près de EQ / SEL, pas près de NR / NB qui sont des fonctions du
  poste) : appui = marche / arrêt ; « ST ON » allumé ; grisé si la sortie est déclarée mono.
- Rubrique « Spatialisation (stéréo) » : préréglages, trois curseurs, A/B (maintenu : mono, relâché : effet),
  « Sortie mono », indicateur de corrélation G/D (1 = mono, 0 = décorrélé).
- Premier usage : message unique « Mettez un casque pour profiter de l'effet ».
- Réglages enregistrés sur l'appareil (page : stockage du navigateur ; application : préférences).

## 6. Sortie mono et Bluetooth

- **Page** : un navigateur ne sait pas si la sortie est mono, un casque en mode appel ou un haut-parleur unique ⇒
  case « Sortie mono » manuelle (bypass forcé, ST grisé).
- **Application** : détection par `AudioDeviceInfo` (SCO, haut-parleur intégré mono ⇒ bypass ; A2DP, filaire, USB ⇒
  disponible). Le S25 a deux haut-parleurs : pas de bypass forcé sur le haut-parleur.
- **Bluetooth** : on GARDE le fonctionnement de l'étape 96 (réception en A2DP, mode appel pendant l'émission
  seulement), seul moyen d'avoir le bouton PTT du casque. Le mode « HFP permanent » de la v1 est écarté (il casse ce
  bouton et met la réception en mono 8/16 kHz). Pendant l'émission, la réception n'est pas écoutée : la spatialisation
  n'y perd rien.

## 7. Application Android (FAIT, étape 117, application 0.42.0 : piste ci-dessous retenue et essayée sur le S25)

Le crochet actuel de la réception (`setRenderPreProcessing`) ne traite qu'une voie : il ne peut pas produire de
stéréo. Piste retenue, à prouver d'abord sur le S25 : `AudioTrack.addSink` (stream-webrtc 1.3.10) reçoit le son
décodé ; quand ST est en service, le son de WebRTC est coupé (volume 0 de la piste reçue) et l'application joue elle-
même un `AudioTrack` stéréo (mêmes attributs que WebRTC). Le débrouillage du scrambler et l'enregistrement pour la
rediffusion devront suivre le même chemin, ou ST être refusé pendant le débrouillage.

## 8. Ce que la V1 n'apporte pas

À partir d'un audio mono démodulé, tout traitement agit de la même façon sur le signal et sur le bruit : pas de
démasquage binaural réel. Le vrai binaural demande les voies I/Q avec les deux bandes latérales (récepteurs de KK7B),
donc la sortie FI 12 kHz du poste et une démodulation par la station : étude sur la branche `exp/st-fi`
(`docs/exp-fi/journal.md`), sans engagement.

## 9. V2 (après essais de la V1)

Haas, peigne complémentaire (« Wahoo démo »), panneau avancé (bande traitée, retard, gain croisé, pas du peigne,
nombre de passe-tout, graine, égaliseur de sortie, plafond du limiteur), préréglages personnels (enregistrés sur la
station par compte, comme les profils de l'égaliseur ; localement pour les visiteurs), export / import JSON,
association préréglage ↔ mode du poste, extrait de démonstration, widget du designer.

## 10. Recette V1

Automatique (`tests/js/spatial_test.js`, puis tests Kotlin) :
- [ ] Binaural : déphasage 90° ± 2° entre G et D (w = 1) de 300 à 3 000 Hz, amplitudes égales à ±0,5 dB.
- [ ] Décorrélation : G + D = 2 × signal (à l'arrondi près), quelle que soit l'intensité.
- [ ] Sonie : écart ≤ 1 dB entre bypass et chaque préréglage (bruit blanc filtré 300 à 3 000 Hz).
- [ ] Aucun saut d'échantillon > seuil sur 100 changements de préréglage enchaînés (sinus 1 kHz).
- [ ] Aucun NaN ni infini, entrées extrêmes comprises ; limiteur : jamais au-dessus du plafond.
- [ ] Mêmes préréglages et mêmes échantillons de référence sur la page et l'application (`spatial_presets.json`).

Sur l'appareil :
- [ ] Casque filaire puis Bluetooth A2DP : effet audible, A/B sans clic, latence non perçue.
- [ ] Émission puis retour en réception avec le casque Bluetooth : PTT du casque inchangé (étape 96).
- [ ] Débrouillage du scrambler + ST ensemble.
- [ ] Visiteur : ST disponible, rien envoyé à la station.
- [ ] Écoute comparée A/B en BLU, CW, signal faible (préférence notée).
