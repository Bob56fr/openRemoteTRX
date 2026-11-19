# Valise de qualification : mode d'emploi

Pour qualifier un poste (TRX) sur place, avec la page de la valise dans le navigateur du PC. La valise mesure et
note ; c'est l'opérateur qui branche, qui tape les mots de sécurité et qui fait les gestes au poste. À la fin, un
rapport zip est donné à Claude (ou à l'équipe), qui rédige la fiche du poste.

Détails techniques : [qualification.md](qualification.md) ; cahier des charges :
[qualification-gui-cahier-des-charges.md](qualification-gui-cahier-des-charges.md).

Dans cette notice, le poste pris en exemple est un IC-7300 et le dossier de qualification s'appelle
`qualif-ic7300` : changer ce nom pour un autre poste. Chaque commande est à taper dans un **terminal**, **dans le
dossier indiqué** juste au-dessus du cadre.

> **Ouvrir un terminal**
> - **Windows** : touche Windows, taper `PowerShell`, Entrée.
> - **Debian** : menu des applications, « Terminal » (ou Ctrl + Alt + T) ; en SSH, la session SSH elle-même.

## 1. Ce qu'il faut

- Le poste, son câble USB (CAT et carte son), sa notice.
- Une **charge fictive** qui tient la puissance minimale du poste, et l'**antenne** habituelle (réception).
- Un PC Windows ou Debian avec TRX Remote installé (les commandes `trx-setup` et `trx-qualif` répondent dans un
  terminal). Vérifier :

  Dans n'importe quel dossier :
  ```
  trx-qualif --help
  ```
  Réponse attendue : `usage: trx-qualif …`. Sinon, avec le code du dépôt (développeur) :

  Dans le dossier du dépôt (ex. `C:\dev\openRemoteTRX`) :
  ```
  pip install -e .
  ```
- Facultatif : le téléphone avec l'application (essais 3 et 4), un appareil photo (menus du poste).

## 2. Préparer le dossier de qualification (une fois par poste)

La valise travaille dans **son propre dossier**, avec **sa propre station.toml** : elle ne touche jamais à la
station installée sur le PC.

> **Debian : limite actuelle.** Sous Debian, les boutons « Démarrer / Arrêter la station du PC » de la valise
> pilotent la station **installée** (systemd), avec SA configuration `/etc/trx-remote/station.toml`. Sous Debian,
> on qualifie donc avec la station installée, en sautant 2.2 à 2.4 :
> - poste, son, bandes et TOT réglés par TRX Console (menus 2.1, 3.2, 3.3) ; compte opérateur par le menu 4.3 ;
> - valise lancée avec `--config /etc/trx-remote/station.toml` (voir 4.1) ; le mot de passe du compte est demandé
>   au premier essai automatique (pas de `valise.pw`).
>
> Sous Windows, tout ce qui suit s'applique tel quel.

### 2.1 Créer le dossier et y entrer

**Windows** (PowerShell), dans n'importe quel dossier :
```powershell
mkdir C:\qualif-ic7300
cd C:\qualif-ic7300
```

**Debian**, dans n'importe quel dossier :
```bash
mkdir -p ~/qualif-ic7300
cd ~/qualif-ic7300
```

Toutes les commandes suivantes se tapent **dans ce dossier** (`C:\qualif-ic7300` ou `~/qualif-ic7300`).

### 2.2 Fabriquer la configuration de la valise

Dans le dossier de qualification :
```
trx-setup --output station.toml
```

L'assistant pose ses questions ; répondre :
- modèle du poste, port CAT, débit, PTT par la CAT ;
- carte son du poste (entrée ET sortie) ;
- Icom avec second port : port du spectre (port B) et adresse CI-V ;
- bandes : celles que l'opérateur a le droit d'utiliser (la valise signale les bandes de qualification qui
  manquent) ;
- un compte opérateur, par exemple `valise`, **avec un mot de passe que l'on note** (il servira en 2.4).

À la fin, s'il propose « Démarrer la station maintenant », répondre **n** : c'est la valise qui la démarrera.

### 2.3 Deux réglages à changer à la main

Ouvrir le fichier, dans le dossier de qualification :

**Windows** :
```powershell
notepad station.toml
```

**Debian** :
```bash
nano station.toml
```

Changer (ou ajouter) ces deux lignes, chacune dans SA section :

```toml
[supervisor]
state_dir = "C:\\qualif-ic7300\\state"     # Windows (barres doublées)
# state_dir = "/home/MOI/qualif-ic7300/state"   # Debian (MOI = votre compte)

[safety]
tot_s = 20                                  # l'essai du TOT dure 20 s au lieu de 90
```

`state_dir` dans le dossier : les journaux de la valise ne se mêlent pas à ceux de la station installée.
Enregistrer et fermer (Bloc-notes : Ctrl + S ; nano : Ctrl + O, Entrée, Ctrl + X).

### 2.4 Le mot de passe du compte, pour les essais automatiques

Les essais automatiques se connectent à la station comme un téléphone, avec le compte créé en 2.2. Son mot de
passe est lu dans `valise.pw`, **à côté de station.toml** : rien à taper pendant les essais.

**Windows**, dans le dossier de qualification :
```powershell
notepad valise.pw
```
Écrire le mot de passe sur une seule ligne, enregistrer, fermer.

**Debian**, dans le dossier de qualification (remplacer `LE_MOT_DE_PASSE`) :
```bash
printf '%s' 'LE_MOT_DE_PASSE' > valise.pw
chmod 600 valise.pw
```

Ce fichier ne quitte jamais le PC : il n'est jamais mis dans le rapport. Ne pas l'envoyer, ne pas le photographier.

Le dossier contient alors :
```
qualif-ic7300/
├── station.toml     configuration de la valise
└── valise.pw        mot de passe du compte (privé)
```

## 3. Avant chaque séance

### 3.1 Arrêter la station installée sur le PC

S'il y en a une, elle prendrait les mêmes ports et le même poste (sous Debian, c'est elle que la valise
redémarrera quand il le faudra). Par TRX Console (menu 1.2), ou :

**Windows**, dans n'importe quel dossier :
```powershell
trx-supervisor --stop
```

**Debian**, dans n'importe quel dossier :
```bash
sudo systemctl stop trx-remote.target
```

### 3.2 Le poste et le PC

- Poste allumé, câble USB branché, poste en **réception**, split **OFF**.
- Icom : réglages USB SEND / USB Keying du second port sur OFF (un port B mal réglé peut mettre en émission).
- Windows : son du poste à **100** dans les paramètres de son (entrée et sortie), « améliorations audio »
  désactivées. Un volume réduit donne une émission sans puissance.
- Photos des menus du poste : dans `photos/avant` du dossier de la session (puis `photos/apres` à la fin).

## 4. Lancer la valise

### 4.1 Première séance (nouvelle session)

**Windows**, dans le dossier de qualification :
```powershell
trx-qualif --config station.toml --output valise --terrain --page
```

**Debian** (station installée, voir la limite au § 2), dans le dossier de qualification :
```bash
trx-qualif --config /etc/trx-remote/station.toml --output valise --terrain --page
```

- La page de la valise s'ouvre toute seule dans le navigateur.
- Le terminal affiche son adresse (`http://127.0.0.1:<port>/?t=…`, valable UNE fois) puis le journal : **le laisser
  ouvert** pendant toute la séance (le fermer arrête la valise).
- Les sessions et les rapports vont dans le sous-dossier `valise` :
  ```
  qualif-ic7300/
  ├── station.toml
  ├── valise.pw
  ├── state/                                  journaux de la station de la valise
  ├── logs/                                   journaux du superviseur (Windows)
  └── valise/
      ├── terrain-3094-20261119-0116/         la session (photos/avant, photos/apres…)
      └── terrain-3094-20261119-0116.zip      le rapport pour Claude
  ```

### 4.2 Reprendre une session (après « Quitter (session gardée) »)

Dans le dossier de qualification, avec le nom du dossier de la session (voir `valise/`) :
```
trx-qualif --config station.toml --output valise --terrain --page --session valise/terrain-3094-20261119-0116
```

> **Attention** : sans `--session`, c'est une **NOUVELLE** session. Les essais faits dans l'ancienne ne comptent
> pas dans le nouveau rapport.

### 4.3 Autres façons

Sans navigateur (menu au clavier dans le terminal), dans le dossier de qualification :
```
trx-qualif --config station.toml --output valise --terrain
```

Depuis TRX Console : menu 8.3, choix 6.

### 4.4 Adresses utiles

| Page | Adresse | Quand |
|---|---|---|
| Valise | affichée dans le terminal, s'ouvre seule | toute la séance |
| Page de la station | `http://127.0.0.1:8443/` | essais à la main seulement (lien dans la fiche de l'essai) ; **la fermer avant les essais automatiques** |
| Codes d'erreur ORT | https://bob56fr.github.io/openRemoteTRX/erreurs/ | un message « ORT-NNNN » à comprendre |

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
- **Onglet de la valise fermé par erreur** : rouvrir `http://127.0.0.1:<port>/` (port affiché dans le terminal) dans le même navigateur, ou relancer
  avec `--session`.
- **Nouvelle session par erreur** (lancée sans `--session`) : reprendre l'ancienne, ou refaire les essais manquants
  dans la nouvelle.
