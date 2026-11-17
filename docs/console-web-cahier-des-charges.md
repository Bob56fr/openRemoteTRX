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

## 6. Questions d'origine

1. Programme à part `trx-console --web`, 127.0.0.1 + jeton, tunnel SSH pour un autre PC : d'accord ?
2. Menus dans un terminal intégré (xterm.js livré avec la station) plutôt que des formulaires : d'accord ?
3. Windows : nouvelle dépendance `pywinpty`, ou menus ouverts dans une fenêtre de console à part ?
4. Le rendu de la maquette convient-il ?
