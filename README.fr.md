# openRemoteTRX

*[English version](README.md)*

Piloter un émetteur-récepteur radioamateur à distance, depuis le navigateur d'un smartphone, d'une tablette ou d'un PC, ou depuis l'application Android : **écoute et émission**, avec des sécurités d'émission placées sur la station elle-même.

*Dernière mise à jour de cette page : 25 novembre 2026 (code du dépôt : station 0.288.0, application Android 0.93.0).*

> **Statut : en développement actif.** Validé avec un **Icom IC-7300MK2** sur PC Windows et sur Debian 13. **Yaesu FTDX10** qualifié sur charge fictive (validation en cours). D'autres postes devraient fonctionner (voir plus bas) ; l'état de chaque poste essayé est publié sur la [page des postes](https://bob56fr.github.io/openRemoteTRX/postes/). Utilisez-le d'abord sur **charge fictive**, à puissance réduite.

<table>
  <tr>
    <td align="center"><a href="images/readme/openRemoteTRX%20Android%20App%20-%20Stations%20TAB.jpg"><img src="images/readme/openRemoteTRX%20Android%20App%20-%20Stations%20TAB.jpg" width="180" alt="Onglet Station : fréquence, S-mètre, émission"></a><br><sub>Station : fréquence, S-mètre, émission</sub></td>
    <td align="center"><a href="images/readme/openRemoteTRX%20Android%20App%20-%20Stations%20TAB%20Bottom%20.jpg"><img src="images/readme/openRemoteTRX%20Android%20App%20-%20Stations%20TAB%20Bottom%20.jpg" width="180" alt="Onglet Station : bandes, modes, réglages du poste"></a><br><sub>Bandes, modes, réglages du poste</sub></td>
    <td align="center"><a href="images/readme/openRemoteTRX%20Android%20App%20-%20Audio%20TAB.jpg"><img src="images/readme/openRemoteTRX%20Android%20App%20-%20Audio%20TAB.jpg" width="180" alt="Onglet Audio : égaliseur de la voix"></a><br><sub>Audio : égaliseur de la voix</sub></td>
    <td align="center"><a href="images/readme/openRemoteTRX%20Android%20App%20-%20SWR%20Campaign%20TAB.jpg"><img src="images/readme/openRemoteTRX%20Android%20App%20-%20SWR%20Campaign%20TAB.jpg" width="180" alt="Mesure de TOS sur une bande"></a><br><sub>Mesure de TOS sur une bande</sub></td>
  </tr>
</table>

<sub>Captures de l'application en anglais.</sub>

## Ce que ça fait

- **Page de contrôle web** servie par la station, en HTTPS : fréquence (glisser les chiffres, clavier, bandes, pas), modes, filtres (préréglages FIL et largeurs), NR / NB / Notch / ATT / préampli / AGC / compresseur / puissance, squelch lu sur le poste, S-mètre, mesures Po / ROS / ALC, mémoires partagées.
- **Application Android** (Android 10 et plus) : mêmes fonctions, **Android Auto** (lecteur, mémoires au volant, état d'émission explicite), mode conduite, bouton du casque Bluetooth. Une version **Lite** pour Android 8 et 9 est en essai dans un [dépôt séparé](https://github.com/Bob56fr/openRemoteTRX-lite).
- **Audio dans les deux sens** par WebRTC (Opus), avec le micro du téléphone ou du PC ; égaliseur et effets de voix, limiteur final sur la station.
- **PTT en bascule uniquement** (jamais en maintien), avec une case « Émission autorisée » à cocher d'abord, et un **STOP** toujours visible.
- **Waterfall de l'audio reçu**, **spectre HF du poste** (Icom, par le second port CI-V) avec accord au doigt, et **spots du Cluster DX** (clusters radioamateurs, Reverse Beacon Network, page CB) sur le spectre.
- **Récepteur SDR** en plus du poste (SDRplay RSP, RTL-SDR) : waterfall, zoom, écoute séparée, oreille gauche / droite.
- **FreeDV RADE** en réception (voix numérique décodée par la station) et liste des stations FreeDV actives.
- **Mesure de TOS** sur une bande, graphique et image à partager.
- **Comptes visiteurs** en réception seule, et **diffusion en direct** vers un serveur d'écoute (désactivés par défaut).
- **Allumage et extinction du poste à distance** (désactivés par défaut).
- **Présence de groupe « Amis »** (désactivée par défaut) : qui est en QSO, en réception, au shack ; QSY vers un ami après confirmation. Le relais ne transporte que des états chiffrés qu'il ne peut pas lire ; la fonction n'a aucun droit sur le poste.
- **Monitoring entre stations** : une station amie peut aider à dépanner (codes d'erreur, rapport masqué), à la demande de l'opérateur.
- **openRemoteTRX Console** sur la station, en terminal ou **dans le navigateur** (port 8444, comptes administrateurs) : assistant de configuration, diagnostic, tableau de bord, essai guidé du poste, mise à jour, modification de la configuration, rapport de dépannage, tests automatiques. Tableau de bord des signes vitaux en lecture seule (port 8450).
- **Page, application et console en quatre langues** : français, anglais, allemand, espagnol.
- **Catalogue public des codes d'erreur** ([codes ORT](https://bob56fr.github.io/openRemoteTRX/erreurs/)) et alertes sur le téléphone par ntfy.
- **openRemoteTRX-Autotest** : préqualification d'un poste depuis Chrome, sans rien installer ([page](https://bob56fr.github.io/openRemoteTRX/autotest/)).

## Sécurités d'émission

La station, et non l'application, décide de l'émission. Les sécurités tournent sur la station, même si le téléphone se fige ou perd le réseau :

- durée maximale d'émission (90 s par défaut, plafond 120 s), avec avertissement ;
- signal de vie du client pendant l'émission : sans lui pendant 2 s, retour en réception ;
- retour en réception immédiat si la connexion tombe ; toujours en réception au démarrage ;
- un seul opérateur émet à la fois ; le micro distant n'atteint le poste que pendant sa propre émission confirmée ;
- l'état réel du poste est relu en permanence ; la bande est vérifiée sur la fréquence d'émission réelle (split, ΔTX, second récepteur) ; changer la fréquence ou le mode est refusé pendant l'émission ;
- un **superviseur indépendant** relit le poste lui-même et coupe l'émission si la passerelle se fige, ou au-delà d'une durée absolue ; en dernier recours, **mise en sécurité** de la station (réception seule, en attente d'une intervention) ;
- la personne **devant le poste** garde la priorité : si elle émet au micro du poste ou change de fréquence ou de mode, l'émission à distance est bloquée pendant quelques minutes ;
- en cas de doute, la station n'émet pas.

Le détail est dans `CLAUDE.md` (« Règles de sécurité d'émission ») et `docs/`.

## Ce qu'il faut

- Un **poste reconnu par [Hamlib](https://github.com/Hamlib/Hamlib)** (environ 300 modèles), avec liaison CAT et audio par USB (poste à interface USB intégrée, ou interface externe de type Digirig ou SignaLink).
- Une **station** : PC sous **Debian 12 ou 13** (installation guidée), ou **PC Windows 10/11**. Hamlib 4.5 ou plus récent, Python 3.11 ou plus récent.
- **Raspberry Pi 4** : installation préparée (sans bureau, tout par SSH), premiers retours d'un bêta-testeur ; pas encore validé. Pi 3 déconseillé.

## Installation

**Première station ?** Suivez le **guide de l'opérateur**, pas à pas, avec un récapitulatif à cocher, en français, anglais, allemand et espagnol : [User-Guide/](User-Guide/README.md) (page web : https://bob56fr.github.io/openRemoteTRX/guide/). Pressé ? [Démarrage rapide](User-Guide/fr/demarrage-rapide.md), en un quart d'heure. Ce qui suit en est le résumé.

Les paquets signés sont publiés dans les [Releases](https://github.com/Bob56fr/openRemoteTRX/releases).

### Debian (recommandé)

1. Récupérez le paquet `trx-remote-debian-X.Y.Z.zip` et décompressez-le.
2. Dans le dossier : `sudo bash install.sh` (dépendances, compte de service, services systemd).
3. Ouvrez **openRemoteTRX Console** (menu des applications ou `trx-console`) et lancez l'**assistant de configuration** (menu 2.1) : poste, ports, cartes son, accès réseau, comptes.
4. Faites l'**essai guidé** (menu 2.2) sur charge fictive.
5. Sur le téléphone, ouvrez `https://<adresse-de-la-station>:8443`.

Les versions suivantes s'installent depuis openRemoteTRX Console (menu 7.1 par Internet, signature vérifiée ; menu 7.3 depuis un fichier zip).

### Windows

1. Installez **Hamlib 64 bits** (`hamlib-w64-X.Y.Z.exe`, [versions de Hamlib](https://github.com/Hamlib/Hamlib/releases)).
2. Récupérez le paquet `trx-remote-windows-X.Y.Z.zip`, débloquez-le (Propriétés), extrayez-le, double-cliquez sur **`installer.cmd`**. Python est installé s'il manque (avec votre accord).
3. Menu Démarrer > **openRemoteTRX** : un seul raccourci, qui ouvre openRemoteTRX Console (configuration, diagnostic, démarrage et arrêt de la station, tableau de bord, essai du poste, journaux). Désinstallation : Paramètres > Applications.

La station démarre à l'ouverture de session, sans fenêtre. Notice complète : `windows/notice-windows.html` (jointe au paquet). Une version **Microsoft Store** est en préparation.

## Accès depuis l'extérieur

Le projet n'impose **aucun VPN** : vous choisissez le vôtre (WireGuard, Tailscale…), ou vous exposez le port avec TLS. Les mots de passe sont stockés sous forme d'empreinte, les essais répétés sont freinés, et l'accès réseau sans chiffrement est refusé ; la station peut installer sa propre autorité de certification sur vos appareils. Une sonde de qualité réseau explique les coupures (téléphone, réseau mobile, réseau local). **Limite connue** : l'audio WebRTC utilise de l'UDP ; derrière certaines box ou certains réseaux mobiles (NAT strict), il peut ne pas passer sans VPN ou relais TURN. Voir `docs/acces-distant.md`.

## Ce qui reste à faire ou à valider

- Application **Android** : en test sur invitation (Google Play) ; essais réels en voiture (Android Auto) à poursuivre. La page web, elle, s'arrête d'émettre dès qu'elle est masquée.
- Accès distant réel en 4G/5G, validation sur Raspberry Pi, validation complète du FTDX10 (split à distance) et des FTDX101.
- Relecture des traductions allemande et espagnole par des locuteurs natifs.
- La documentation détaillée (`docs/`) est en français.

## Réglementation

Vous restez responsable du respect de votre licence et de la réglementation de votre pays, **y compris pour le trafic à distance**. Certains boutons de bande (85, 45, 11 m) servent à **l'écoute** : ce ne sont pas des bandes radioamateur.

## Signaler un problème, contribuer

- Depuis la page : section **« Signaler un problème »** (rapport relu avant envoi), puis openRemoteTRX Console, menu 6.3 (rapport de dépannage, sans mot de passe ni numéro de série).
- Sur GitHub : onglet *Issues*, avec le formulaire de votre langue (français, anglais, allemand, espagnol).
- Contribuer : voir [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[GNU Affero General Public License v3.0 ou ultérieure](LICENSE) (`AGPL-3.0-or-later`). Copyright (C) 2026 RF-DIY.COM.

Si vous modifiez ce logiciel et le mettez à disposition d'autres personnes par le réseau, vous devez leur proposer le code source de votre version.
