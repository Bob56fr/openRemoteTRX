# Valise de qualification graphique : cahier des charges (v2)

Demande de l'utilisateur (2026-11-19) : effectuer et suivre les essais de qualification dans une interface graphique
« effet wahou », pas dans un terminal. Elle doit servir à un **qualifieur seul** (mode manuel) et à **Claude** quand il
mène lui-même les essais et a besoin d'une intervention humaine (mode piloté). Maquette cliquable :
https://claude.ai/artifact/XurAobkbMe1FDpGCwhXvbj (privée, valeurs réelles de l'IC-7300MK2 du 2026-11-19).

## 1. Principes

- **Même moteur** que `trx-qualif --terrain` (`trxstation/qualif/terrain.py`, `runner.py`, `autodrills.py`) : la page
  n'invente aucun essai ; elle remplace le terminal (questions, réponses, affichage), le code des essais ne change pas.
- **Page servie par la valise elle-même** (aiohttp, comme la console web) sur 127.0.0.1, jeton à usage unique dans
  l'adresse puis cookie, Host / Origin vérifiés, une seule session ; Windows et Debian.
- **Une session = un poste** (dossier `terrain-<modèle>-<date>-…` existant) : reprise après fermeture de la page.

## 2. Écran (voir la maquette)

- **Bandeau d'état toujours visible** : poste, Hamlib, système ; voyants CAT, second port, branchement (antenne /
  charge fictive), PTT relu (« ÉMISSION » rouge clignotant), qui pilote (qualifieur / Claude) ; **STOP** toujours visible.
- **Mesures en direct** : puissance, TOS, ALC, S-mètre, fréquence et mode lus pendant l'essai en cours.
- **Note sur 5 en direct** (même calcul que la page des postes, `rating` de `scripts/build_rigs_doc.py`) et
  progression ; « Fabriquer le rapport » (zip actuel) et « Brouillon de fiche publique » (`docs/postes/donnees/*.toml`).
- **Thèmes en tuiles** (liaison et relevés, réception, sécurité d'émission, émission, coupleur et TOS, absent du poste) :
  chaque tuile dit où elle se fait (antenne, charge fictive, sans émission), chaque essai a un état coloré (à faire,
  en cours, validé, partiel, échec, absent du poste), sa mesure, et un bouton lancer / relancer. Pas de défilement sans
  fin : le journal est replié en bas.
- Boutons « Tout lancer », « Relancer les échecs », « Remettre à zéro ».

## 3. Demande d'intervention humaine (règle de sécurité)

Fenêtre qui passe **devant tout** (rien ne continue sans réponse), en trois parties : **pourquoi** (ex. « le poste va
émettre ; seul un humain près du poste peut l'autoriser »), **ce qu'il faut faire** (ex. « branchez la charge
fictive »), **le mot à taper** ou « C'est fait » pour un geste sans risque (parler au micro, touche SPLIT) ; « Passer cet
essai » toujours offert ; signal sonore.

- Texte montré au qualifieur (formulation de l'utilisateur, 2026-11-19) : « Les mots CHARGE, ANTENNE et EMETTRE devront
  être tapés au clavier par vous-même, afin d'être certain que vous êtes d'accord avec l'essai qui va être fait et que
  votre TRX est bien disponible comme demandé. »
- Ces mots ne viennent QUE de la fenêtre, tapés au clavier par un humain : ni Claude ni l'API ne peuvent les fournir
  (la route de pilotage les refuse ; test imposé). C'est plus sûr que le déroulé actuel, où Claude recopiait dans ses
  scripts le mot dit dans la conversation.
- **Deux bips** (décision de l'utilisateur) : un bip bien audible à l'ouverture de la fenêtre d'intervention ; un petit
  bip différent, discret, quand Claude passe d'un essai à l'autre sans réclamer d'intervention.
- EMETTRE une fois par **thème** qui émet (comme aujourd'hui une fois par essai dans le terminal) ; CHARGE / ANTENNE à
  chaque changement de branchement demandé par un thème.
- STOP coupe tout de suite (même chemin que l'essai en cours : `force_rx`), arrête l'enchaînement et le dit.

## 4. Mode piloté par Claude

- Claude parle à la valise par une **API locale** (127.0.0.1, même jeton) : lister les essais et leurs états, lancer un
  essai / un thème / tout, lire les mesures et le journal, poser une question à l'humain (texte libre, oui / non,
  « c'est fait »), arrêter. Une commande `trx-qualif --pilote …` l'enveloppe pour la conversation.
- Quand un essai a besoin d'un humain, l'API renvoie « en attente de l'opérateur » ; la page affiche la fenêtre de la
  § 3 avec « Claude a besoin de vous » ; la réponse humaine débloque l'essai.
- Claude ne change jamais la fréquence de lui-même (règle du 2026-11-19) ; il peut DEMANDER à l'opérateur de la changer.

## 5. Ce qui ne change pas

Règles de la qualification (CLAUDE.md, « Qualifier un poste ») : réception sur antenne, émissions sur charge fictive,
mode par réglage, aucune écriture hors liste fermée, poste remis comme au départ, rapport zip avec empreintes.

## 6. Lots

- **G0** : maquette et ce cahier : VALIDÉS par l'utilisateur le 2026-11-19.
- **G1** : moteur d'événements de la valise : `ask` / `out` de `terrain.py` remplacés par un bus (question, réponse,
  ligne de journal, état d'essai, mesure) ; le terminal devient un client de ce bus (aucun changement visible).
- **G2** : page en mode manuel (tuiles, fenêtre d'intervention, STOP, mesures, journal), français et anglais.
- **G3** : API de pilotage et `trx-qualif --pilote` ; refus des mots de sécurité par l'API (test).
- **G4** : note en direct, brouillon de fiche publique, rapport depuis la page.

## 7. Décisions de l'utilisateur (2026-11-19)

1. Type d'interface VALIDÉ (maquette v3).
2. Page ouverte **seulement sur le PC de la valise** (127.0.0.1), pas de tablette.
3. Langues : **français et anglais** d'abord.
4. Son : bip avec la fenêtre d'intervention, petit bip différent à chaque essai enchaîné par Claude ; pas d'alerte ntfy.
