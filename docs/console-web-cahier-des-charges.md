# TRX Console dans le navigateur : cahier des charges (v1, à valider)

Demande de l'utilisateur (2026-11-17) : après la console texte et l'écran plein (étapes 219 à 227), une **belle page
web avec « effet wahou »**, même si le menu texte suffit. Lot 0 et arborescence : carte des réglages
(https://claude.ai/artifact/X6WmL9HUCrbcqbWyoNcGZi). Maquette visuelle de cette page : voir la conversation (artefact
« Console web de la station »).

## 1. Ce que la page doit offrir

- **Accueil vivant** : état de la station (en marche, arrêtée, émission, mode sûr), poste (fréquence, mode, tension),
  version, alerte de nouvelle version ; relu toutes les quelques secondes (fichier d'état, comme trx-monitor).
- **Les 8 thèmes en cartes**, avec pictogramme, couleur et nombre de menus ; un clic déplie le thème ; recherche
  instantanée (« ntfy », « TOT », « visiteur ») sur les libellés ET les aides.
- **L'aide de chaque menu** au survol et à la sélection (mêmes textes que la touche `h`, 4 langues).
- **Ouvrir un menu** : il se déroule dans un **terminal intégré** à la page (voir § 3), puis l'accueil se relit.
- Même arborescence et mêmes numéros que la console (`MENU_THEMES`), changement de langue (menu 0).
- Thème sombre « shack » et thème clair ; animation d'apparition sobre ; utilisable sur tablette.

## 2. Sécurité (bloquant)

- **Programme à part**, jamais la passerelle : la passerelle ne doit pas pouvoir écrire `station.toml` (règle du
  projet). Commande `trx-console --web` (aiohttp, déjà une dépendance), lancée par l'opérateur sous SON compte, comme
  la console.
- **127.0.0.1 seulement**, port choisi au hasard ; **jeton à usage unique** dans l'adresse ouverte automatiquement dans
  le navigateur (`webbrowser`), échangé contre un cookie de session (HttpOnly, SameSite=Strict) ; Host et Origin
  vérifiés (pas de rebinding DNS, pas de requête d'un autre site) ; arrêt quand on ferme le terminal qui l'a lancée,
  ou après 30 min sans page ouverte.
- Depuis un autre PC : **tunnel SSH** (`ssh -L 8765:127.0.0.1:<port> station`), jamais un port ouvert.
- Le mot de passe sudo se tape dans le terminal intégré : il va au pseudo-terminal, jamais stocké ni journalisé.
- Aucune action d'émission : la console web ne fait que ce que fait TRX Console (qui ne peut que couper).

## 3. Les menus : terminal intégré

Les menus sont des conversations (questions, mot de passe sudo, éditeur, outils interactifs comme l'essai du poste).
Les refaire en formulaires web demanderait de réécrire chaque menu. Choix proposé : la page ouvre un **terminal
intégré** (xterm.js, MIT, livré avec la station : aucun accès Internet) relié à un **pseudo-terminal** où tourne
`trx-console --texte --menu X.Y` (nouvelle option : un seul menu puis sortie). Tout marche donc comme dans un
terminal : sudo, nano, essai du poste, tableau de bord.

- **Un seul terminal pour toute la session**, où les menus se déroulent l'un après l'autre (pas un terminal neuf par
  menu). Raison : sudo retient le mot de passe PAR TERMINAL (15 minutes sous Debian, délai relancé à chaque usage) ;
  un terminal par menu ferait redemander le mot de passe à chaque menu. Comme dans la console texte : un mot de passe
  au premier menu d'administration, puis plus rien tant qu'on s'en sert. Pas de règle sudoers sans mot de passe
  (`NOPASSWD`) : tout programme lancé sous le compte de l'opérateur pourrait alors écrire dans /etc.
- Debian / Pi : pseudo-terminal de la bibliothèque standard (`pty`).
- Windows : ConPTY par `pywinpty` (MIT, nouvelle dépendance, Windows seulement), ou en attendant ouverture du menu dans
  une nouvelle fenêtre de console.

## 4. Découpage proposé

| Lot | Contenu |
|---|---|
| W1 | `trx-console --menu X.Y` ; serveur local (127.0.0.1, jeton, cookie, Origin) ; page : accueil vivant, cartes des thèmes, recherche, aide, thèmes sombre et clair ; menus dans le terminal intégré sous Debian |
| W2 | Windows (pywinpty ou nouvelle fenêtre), raccourci « TRX distant » qui propose écran plein ou page |
| W3 | Écrans web natifs pour les menus les plus utilisés (comptes 4.3, alertes 3.5, fonctions 5.5), formulaires validés |

## 5. Décisions de l'utilisateur (2026-11-17)

1. Programme à part, 127.0.0.1, jeton, tunnel SSH : **oui**.
2. Menus dans un terminal intégré : **oui, pour le moment** (formulaires du lot W3 selon l'usage).
3. Windows : **pywinpty**, même écran que sous Debian (« sinon on se perd quand on donne des conseils à quelqu'un
   par téléphone »). Lot W2 fusionné dans W1.
4. Rendu : maquette retouchée (5 colonnes, bulle d'aide au survol, panneau du bas sur téléphone) puis validée.

## 5 quater. Menus en formulaires (lot W3a, étape 235)

Demande de l'utilisateur (2026-11-17) : une page « sans le terminal », quitte à ne représenter que ce qui se passe
dans la console. Décision : la station joue LE MÊME code de menu dans un processus enfant (`console_web/worker.py`),
« dire » et « demander » remplacés par des messages JSON ; la page les dessine (`static/flow.js`). Nature d'une
question : `Console.hint` (oui/non, nombre et bornes, mot de passe, mot de confirmation, pause) sinon lignes
« 1) … » avant l'invite et « x = … » de l'invite ; réponse libre toujours offerte. Commandes lancées par un menu :
sortie au fil de l'eau, ligne de réponse pour un outil qui pose une question. sudo : mot de passe demandé dans la
page une fois par session (mémoire du serveur, oublié à la fermeture), vérifié par `sudo -S -k true`, passé par
l'entrée standard à chaque commande (`sudo -S -k`, jamais le cache : il ne peut pas tomber dans l'entrée de la
commande). Restent au terminal : tableau de bord 1.3 (plein écran) et éditeur 8.1. Suite : W3b (assistant 2.1 et ses
parties en vrais formulaires : questions de `setup_wizard` annoncées par une marque), W3c (tableau de bord natif dans
la page, éditeur de station.toml).

W3b FAIT (étape 237, station 0.181.0) : un outil lancé par un menu (trx-setup et ses parties, réglage du Cluster DX)
annonce chaque question par une ligne `trxstation/formhint.py` (`\x1eTRXFORM {json}` : nature, invite, choix, bornes,
valeur actuelle, mot à taper, texte exact de l'invite qui suit) quand `TRX_CONSOLE_FORMS=1` (posé par le worker,
redonné à travers sudo par `env`) ; au terminal, rien ne change. Le worker (`ToolStream`) remplace la ligne par un
formulaire `tool: true`, retire l'invite répétée de la sortie et renvoie la réponse sur l'entrée de l'outil ; la page
inscrit la réponse dans la sortie, sous sa question. Champs acceptés : liste fermée, choix limités à 200.

W3c FAIT (étape 238, station 0.182.0) : plus aucun menu réservé au terminal (`TERMINAL_MENUS` vide). TABLEAU DE BORD
(1.3) dessiné par la page : `/api/dashboard` (lecture seule, ne prolonge pas la session) renvoie les panneaux et le
journal de trx-monitor (`monitor/model.py` : `build_panels`, `EventLog`), la page (`static/dash.js`) les redessine
toutes les 0,7 s ; STOP TX = `/api/stop_tx` (session + même origine) = `monitor/actions.stop_tx` (« T 0 » direct à
rigctld, ne peut que couper). STATION.TOML (8.1) : le worker remplace nano par la page (`WEB_EDITOR`) : le texte part
dans un champ, revient modifié (512 ko au plus) ou annulé, remplace la COPIE de travail ; la console vérifie,
montre les différences et enregistre par sudo exactement comme avec nano (fins de ligne d'origine gardées).

## 5 ter. TRX Console sur le réseau (étape 233)

Décisions de l'utilisateur (2026-11-17), le raccourci des étapes 230-231 étant « beaucoup trop compliqué en pratique » : une page HTTPS servie en permanence sur le réseau local ou le VPN (port 8444, certificat de la station), connexion avec un compte OPÉRATEUR marqué `admin = true` (choix 1), session fermée après 30 min sans action ; le mot de passe sudo reste demandé dans le terminal, une fois par session (choix 2) ; raccourci retiré (choix 3), menu 4.6 repris. Garde-fous : adresses privées seulement, 5 échecs = 15 min de blocage par adresse, alerte ntfy à chaque connexion (ORT-4022) et à chaque blocage (ORT-4023), une seule session (une nouvelle connexion ferme l'ancienne et son terminal), 8 h au plus. Service : `trx-console-web@<compte>` (Debian, jamais root, groupe trx), enfant du superviseur sous Windows ; relancé 30 s après une installation (elle peut tourner dans son propre terminal).

## 5 bis. Raccourci « Console de la station » (étapes 230-231, ABANDONNÉ à l'étape 233)

Demande de l'utilisateur (2026-11-17) : le tunnel SSH à la main n'est pas ergonomique pour un non-informaticien.
Décision : la page de pilotage offre aux OPÉRATEURS un lanceur Windows (`console-station.cmd`, modèle servi par la
station et rempli par la page : adresse par laquelle le PC joint la station, compte et ports de `[remote_console]`,
aucun secret). Il lance `ssh -tt -L port:/tmp/trx-console-<aléa>.sock compte@station trx-console --web --raccourci
<socket>` (une console par ouverture, socket Unix privé, aucun port de la station), lit la ligne
`TRX-CONSOLE-URL` et ouvre l'adresse dans le navigateur du PC ; au premier lancement il se range dans
`%LOCALAPPDATA%\OpenRemoteTRX`, pose un raccourci sur le Bureau et propose une clé SSH ed25519 (privée sur le PC,
publique ajoutée à `authorized_keys` de la station avec le mot de passe SSH une dernière fois). Le mot de passe sudo
reste demandé dans la console. Menu 4.6 ; station Debian ou Pi seulement (serveur SSH).

## 6. Questions d'origine

1. Programme à part `trx-console --web`, 127.0.0.1 + jeton, tunnel SSH pour un autre PC : d'accord ?
2. Menus dans un terminal intégré (xterm.js livré avec la station) plutôt que des formulaires : d'accord ?
3. Windows : nouvelle dépendance `pywinpty`, ou menus ouverts dans une fenêtre de console à part ?
4. Le rendu de la maquette convient-il ?
