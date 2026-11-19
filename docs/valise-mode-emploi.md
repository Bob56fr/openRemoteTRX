# Valise de qualification : mode d'emploi

Pour qualifier un poste (TRX) sur place, avec la page de la valise dans le navigateur du PC. La valise mesure et
note ; c'est l'opérateur qui branche, qui tape les mots de sécurité et qui fait les gestes au poste. À la fin, un
rapport zip est donné à Claude (ou à l'équipe), qui rédige la fiche du poste.

Détails techniques : [qualification.md](qualification.md) ; cahier des charges :
[qualification-gui-cahier-des-charges.md](qualification-gui-cahier-des-charges.md).

## 1. Ce qu'il faut

- Le poste, son câble USB (CAT et carte son), sa notice.
- Une **charge fictive** qui tient la puissance minimale du poste, et l'**antenne** habituelle (réception).
- Un PC Windows ou Debian avec TRX Remote (installé, ou le code du dépôt avec `pip install -e .`).
- Facultatif : le téléphone avec l'application (essais 3 et 4), un appareil photo (menus du poste).

## 2. Préparer un dossier de qualification (une fois par poste)

La valise travaille dans **son propre dossier**, avec **sa propre station.toml** : elle ne touche jamais à la
station installée sur le PC.

1. Créer un dossier, par exemple `qualif-ic7300` (Windows : `C:\qualif-ic7300`).
2. Y fabriquer la configuration avec l'assistant :
   ```
   trx-setup --output qualif-ic7300/station.toml
   ```
   - modèle du poste, port CAT, débit, PTT par la CAT ;
   - carte son du poste (entrée ET sortie) ;
   - Icom avec second port : port du spectre (port B) et adresse CI-V ;
   - bandes : celles que l'opérateur a le droit d'utiliser (la valise signale les bandes de qualification qui
     manquent) ;
   - un compte opérateur, par exemple `valise`.
3. Dans `station.toml` (section `[supervisor]`), mettre `state_dir` **dans le dossier** (ex.
   `state_dir = "C:\\qualif-ic7300\\state"`) : les journaux de la valise ne se mêlent pas à ceux de la station.
4. Conseillé : `tot_s = 20` dans `[safety]` (l'essai A5 du TOT dure alors 20 s au lieu de 90).
5. Écrire le mot de passe du compte opérateur dans `valise.pw`, **à côté de station.toml** (une seule ligne).
   La valise le lit pour ses essais automatiques : rien à taper. Ce fichier ne quitte jamais le PC : il n'est
   jamais mis dans le rapport.

## 3. Avant chaque séance

- **Arrêter la station installée sur le PC**, s'il y en a une (elle prendrait les mêmes ports et le même poste) :
  TRX Console, menu 1.2.
- Poste allumé, câble USB branché, poste en **réception**, split **OFF**.
- Icom : réglages USB SEND / USB Keying du second port sur OFF (un port B mal réglé peut mettre en émission).
- Windows : son du poste à **100** dans les paramètres de son (entrée et sortie), « améliorations audio »
  désactivées. Un volume réduit donne une émission sans puissance.
- Photos des menus du poste : dans `photos/avant` du dossier de la session (puis `photos/apres` à la fin).

## 4. Lancer la valise

Depuis le dossier de qualification :

```
trx-qualif --config station.toml --output valise --terrain --page
```

- `--output valise` : les sessions et les rapports vont dans `valise/`.
- `--page` : la page de la valise s'ouvre toute seule dans le navigateur (adresse `http://127.0.0.1:<port>/?t=…`
  affichée dans le terminal, à usage unique). Le terminal ne montre plus que le journal : le laisser ouvert.
- Reprendre une session plus tard (après « Quitter (session gardée) ») :
  ```
  trx-qualif --config station.toml --output valise --terrain --page --session valise/terrain-<modèle>-<date>
  ```
  **Sans `--session`, c'est une NOUVELLE session** : les essais faits dans l'ancienne ne comptent pas dans le
  nouveau rapport.
- Sans navigateur : même commande sans `--page` (menu au clavier dans le terminal).
- Depuis TRX Console : menu 8.3, choix 6.

Adresses utiles :

| Page | Adresse |
|---|---|
| Valise | celle affichée dans le terminal (s'ouvre seule) |
| Page de la station (essais à la main) | `http://127.0.0.1:8443/` (lien dans la fiche de chaque essai) |
| Codes d'erreur ORT | https://bob56fr.github.io/openRemoteTRX/erreurs/ |

## 5. La page

- **En haut** : poste, état de la station du PC, branchement (antenne / charge fictive), PTT relu, gros bouton
  **STOP** (coupe l'émission tout de suite, « T 0 », puis arrête l'essai en cours).
- **À gauche** : les essais par thème, avec un point de couleur (vert validé, orange partiel, rouge échec, bleu en
  cours, gris à faire, cercle vide = le poste ne l'a pas). ▶ lance un essai, ↻ le refait. Un essai **grisé** attend
  l'autre état de la station (« Démarrez d'abord la station » / « Arrêtez d'abord la station ») ; « Tout lancer »
  et « Lancer le thème » font ces préalables eux-mêmes.
- **À droite** : la question en cours (gros boutons), les mesures (fréquence, Po, TOS, ALC, S-mètre), les
  dernières lignes, la progression, les boutons de la station, « Fabriquer le rapport pour Claude », « Quitter ».
- **Fenêtre orange** : un mot de sécurité à taper au clavier (voir § 7).

## 6. Le déroulé

Le plus simple : **« Tout lancer »**, qui suit l'ordre ci-dessous, fait arrêter ou démarrer la station quand il le
faut et ne demande que ce qu'un humain doit faire. Par thème :

1. **Liaison et relevés** (sans émission, station arrêtée) : carte son du poste (en premier), relevé du poste
   AVANT (lecture seule), exploration, qualification sans émission (facultative si la complète est faite).
2. **Réception** (sur ANTENNE, aucune émission) : réception sur la fréquence où est le poste, spectre HF, filtres
   FIL1/2/3 (Icom). Pas de signal (bande fermée) : donner une autre fréquence que l'antenne permet (7 ou 3,5 MHz).
3. **Émission (qualification)** (sur CHARGE FICTIVE) : la qualification complète. Elle demande EMETTRE avant chaque
   émission, et des gestes au poste (mettre le split à la touche SPLIT, l'enlever pendant l'émission, etc.).
4. **Essais automatiques A1 à A8** (charge fictive, station en marche) : STOP, battements arrêtés, connexion
   fermée, fréquence hors bande, TOT, STOP TX du tableau de bord, station arrêtée pendant une émission, démarrage.
   La valise les joue seule avec le compte de `valise.pw` ; EMETTRE est demandé avant chacun.
5. **Essais à la main** : la fiche de chaque essai dit quoi faire. Seul le **6** (émission au micro du poste) est
   demandé par « Tout lancer » ; 1, 2, 5, 7, 8 et 9 sont faits par la valise (A1 à A8) ; 3 et 4 (téléphone) et 10
   (redémarrage du PC) sont facultatifs.
6. **Relevé APRÈS et différences** : la liste « À REMETTRE À LA MAIN » montre ce qui a changé sur le poste depuis le
   relevé AVANT ; le remettre (et repasser en mode et filtre habituels).
7. **Fabriquer le rapport pour Claude** : `valise/terrain-<modèle>-<date>.zip` ; « Ouvrir le dossier » montre le
   fichier. Vérifier les photos (indicatif, plaque du poste) avant de le donner.

Verdict proposé dans le rapport : `validation_en_cours` (tout est bon), `incomplet` (essais manquants, listés),
`refuse` (un essai en échec). « Validé » reste une décision de l'équipe.

## 7. Règles de sécurité

- **CHARGE** (charge fictive branchée), **ANTENNE** (antenne branchée), **EMETTRE** (accord pour une émission) se
  tapent **au clavier**, par l'opérateur, à chaque fois. Le collage est refusé ; Entrée seule = refus. Ni la valise,
  ni Claude, ni aucun programme ne peut les donner.
- Émission seulement sur la charge fictive (sauf demande explicite de la valise sur le mot ANTENNE).
- Puissance minimale.
- Au moindre doute : **STOP** dans la page, ou la touche TRANSMIT du poste.
- La valise ne change jamais la fréquence d'elle-même (sauf l'essai A4, qui la remet aussitôt).

## 8. Pièges connus

- **Page de la station ouverte avec le même compte** que `valise.pw` (laissée ouverte après un essai à la main) :
  les deux connexions se chassent et les essais automatiques échouent (« connexion fermée par la station… »).
  **Fermer l'onglet de la page de la station avant les essais automatiques.**
- **Juste après l'essai 6** (micro du poste), la station bloque le PTT à distance 2 minutes (« opérateur sur
  place ») : la valise reprend la main toute seule, mais jamais pendant une émission au micro.
- **Mauvais mot de passe** : la valise le vérifie tout de suite et le redemande ; « Annuler » = essais automatiques
  passés, le reste continue.
- **Nom de la carte son sous Windows** (« 2- USB Audio Device ») : il change si le câble passe sur une autre prise
  USB. Refaire la carte son (premier essai) et corriger station.toml.
- **Icom : modulation par l'USB seulement en mode données** (PKTUSB / PKTLSB) ; en USB, une émission de la valise
  peut sortir sans puissance.
- **Split** : la valise ne l'écrit jamais (sur l'IC-7300MK2, Hamlib échangerait les VFO) ; c'est l'opérateur qui le
  met et l'enlève à la touche SPLIT. Vérifier qu'il est OFF à la fin (relevé APRÈS).
- **Spectre HF « aucune donnée »** juste après un arrêt de la station : relancer l'essai une fois.
- **Station du PC qui ne démarre pas** : regarder `logs/` dans le dossier de qualification ; un autre programme tient
  peut-être le port du poste (logiciel du fabricant, autre station).
- **Onglet de la valise fermé par erreur** : rouvrir `http://127.0.0.1:<port>/` dans le même navigateur, ou relancer
  avec `--session`.
- **Nouvelle session par erreur** (lancée sans `--session`) : reprendre l'ancienne, ou refaire les essais manquants
  dans la nouvelle.
