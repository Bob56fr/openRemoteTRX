# TRX distant (openRemoteTRX)

*[English version](README.md)*

Piloter un émetteur-récepteur radioamateur à distance, depuis le navigateur d'un smartphone, d'une tablette ou d'un PC : **écoute et émission**, avec des sécurités d'émission placées sur la station elle-même.

> **Statut : en développement actif.** Validé avec un **Icom IC-7300MK2** sur PC Windows et sur Debian 13. D'autres postes devraient fonctionner (voir plus bas) mais n'ont pas été essayés. Utilisez-le d'abord sur **charge fictive**, à puissance réduite.

## Ce que ça fait

- **Page de contrôle web** servie par la station, en HTTPS : fréquence (glisser les chiffres, clavier, bandes, pas), modes, filtres, NR / NB / Notch / ATT / préampli / AGC / compresseur / puissance, squelch, S-mètre, mesures Po / ROS / ALC, mémoires partagées.
- **Audio dans les deux sens** par WebRTC (Opus), avec le micro du téléphone ou du PC.
- **PTT en bascule uniquement** (jamais en maintien), avec une case « Émission autorisée » à cocher d'abord.
- **Waterfall de l'audio reçu** dans la page, et **spectre HF du poste** (Icom, par le second port CI-V) en plein écran ou intégré sur grand écran, avec accord au doigt.
- **Spots du Cluster DX** (clusters radioamateurs, Reverse Beacon Network, page CB) affichés sur le spectre HF, avec l'état de chaque flux.
- **TRX Console** sur la station : assistant de configuration, diagnostic, tableau de bord, essai guidé du poste, mise à jour, modification de la configuration, seuils de température du poste, rapport de dépannage, tests automatiques.
- Thèmes de couleurs, mises en page, sons de la liaison, bips de fin d'émission (désactivés par défaut), « Signaler un problème ».

## Sécurités d'émission

La station, et non l'application, décide de l'émission. Les sécurités tournent sur la station, même si le téléphone se fige ou perd le réseau :

- durée maximale d'émission (90 s par défaut, plafond 120 s), avec avertissement ;
- signal de vie du client pendant l'émission : sans lui pendant 2 s, retour en réception ;
- retour en réception immédiat si la connexion tombe ; toujours en réception au démarrage ;
- un seul opérateur émet à la fois ; le micro distant n'atteint le poste que pendant sa propre émission confirmée ;
- l'état réel du poste est relu en permanence ; changer la fréquence ou le mode est refusé pendant l'émission ;
- un **superviseur indépendant** relit le poste lui-même et coupe l'émission si la passerelle se fige, ou au-delà d'une durée absolue ; en dernier recours, **mode sûr** (réception seule) ;
- la personne **devant le poste** garde la priorité : si elle utilise le micro ou les boutons du poste, l'émission à distance est bloquée pendant quelques minutes ;
- en cas de doute, la station n'émet pas.

Le détail est dans `CLAUDE.md` (« Règles de sécurité d'émission ») et `docs/`.

## Ce qu'il faut

- Un **poste reconnu par [Hamlib](https://github.com/Hamlib/Hamlib)** (environ 300 modèles), avec liaison CAT et audio par USB (poste à interface USB intégrée, ou interface externe de type Digirig ou SignaLink).
- Une **station** : PC sous **Debian 12 ou 13** avec bureau (installation guidée), ou **PC Windows 10/11**. Hamlib 4.5 ou plus récent, Python 3.11 ou plus récent.
- **Raspberry Pi** : prévu dès l'origine, mais **jamais essayé**. Si vous voulez le tenter de votre côté, vos retours sont bienvenus.

## Installation

### Debian (recommandé)

1. Récupérez le paquet `trx-remote-debian-X.Y.Z.zip` et décompressez-le.
2. Dans le dossier : `sudo bash install.sh` (dépendances, compte de service, services systemd).
3. Ouvrez **TRX Console** (menu des applications ou `trx-console`) et lancez l'**assistant de configuration** (menu 2) : poste, ports, cartes son, accès réseau, comptes.
4. Faites l'**essai guidé** (menu 4) sur charge fictive.
5. Sur le téléphone, ouvrez `https://<adresse-de-la-station>:8443`.

Les versions suivantes s'installent depuis TRX Console (menu 10 par Internet, menu 13 depuis un fichier zip).

### Windows

Installation manuelle pour l'instant : Hamlib pour Windows, Python 3.11 ou plus récent, puis dans le dossier du projet `pip install -e ".[station]"`, `trx-setup` pour la configuration et `trx-supervisor` pour lancer la station. Voir `docs/essai-poste-reel.md`.

## Accès depuis l'extérieur

Le projet n'impose **aucun VPN** : vous choisissez le vôtre (WireGuard, Tailscale…), ou vous exposez le port avec TLS. Les mots de passe sont stockés sous forme d'empreinte, les essais répétés sont freinés, et l'accès réseau sans chiffrement est refusé. **Limite connue** : l'audio WebRTC utilise de l'UDP ; derrière certaines box ou certains réseaux mobiles (NAT strict), il peut ne pas passer sans VPN ou relais TURN. Voir `docs/acces-distant.md`.

## Ce qui reste à faire ou à valider

- Application **Android** (service au premier plan, Android Auto, boutons Bluetooth et du volant) : la page web s'arrête d'émettre dès qu'elle est masquée.
- Accès distant réel en 4G/5G, essais Raspberry Pi, signature des mises à jour publiées.
- La documentation détaillée (`docs/`) est en français.

## Réglementation

Vous restez responsable du respect de votre licence et de la réglementation de votre pays, **y compris pour le trafic à distance**. Certains boutons de bande (85, 45, 11 m) servent à **l'écoute** : ce ne sont pas des bandes radioamateur.

## Signaler un problème, contribuer

- Depuis la page : section **« Signaler un problème »** (rapport relu avant envoi), puis TRX Console, menu 8 (rapport de dépannage, sans mot de passe).
- Sur GitHub : onglet *Issues*.

## Licence

[GNU Affero General Public License v3.0 ou ultérieure](LICENSE) (`AGPL-3.0-or-later`). Copyright (C) 2026 RF-DIY.COM.

Si vous modifiez ce logiciel et le mettez à disposition d'autres personnes par le réseau, vous devez leur proposer le code source de votre version.
