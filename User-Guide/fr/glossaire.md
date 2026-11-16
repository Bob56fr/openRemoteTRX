# Glossaire

Les mots du guide, rangés par thème. Le schéma des briques est dans la
[partie 0](00-avant-de-commencer.md#comment-cest-organisé).

## Le matériel

| Terme | Ce que c'est |
|---|---|
| **Poste**, **TRX** | l'émetteur-récepteur radio (ici le Yaesu FTDX10) |
| **PC de la station** | l'ordinateur posé à côté du poste, allumé en permanence, qui fait tourner la station |
| **Station** | l'ensemble poste + PC + logiciel openRemoteTRX ; « démarrer la station » = démarrer ses services |
| **CAT** | *Computer Aided Transceiver* : la commande du poste par l'ordinateur (fréquence, mode, émission…) |
| **Enhanced COM Port** / **Standard COM Port** | les deux ports série que le FTDX10 crée sur le PC par son câble USB : le premier sert au CAT, le second (lignes RTS/DTR) n'est pas utilisé par la station |
| **USB Audio CODEC** | la carte son intégrée au poste, vue par le PC : son reçu vers le PC, voix vers le poste |
| **Charge fictive** | résistance de 50 Ω qui remplace l'antenne : le poste émet sans rayonner. Obligatoire pour tous les essais |
| **ALC** | indicateur du poste qui montre si la modulation est trop forte ; sert à régler le niveau de la voix |
| **TOS** (SWR) | taux d'ondes stationnaires : adaptation de l'antenne. La station sait le mesurer sur une bande |
| **VFO A / VFO B** | les deux fréquences de travail du poste ; la page montre lequel est actif |
| **Split** | réception sur une fréquence, émission sur une autre |

## Le logiciel de la station

| Terme | Ce que c'est |
|---|---|
| **openRemoteTRX** | le nom du projet ; l'application Android porte ce nom, la station s'appelle aussi « TRX distant » |
| **Hamlib** | la bibliothèque libre qui sait parler à environ 300 modèles de postes ; chaque modèle a un **numéro** (FTDX10 = 1042) |
| **rigctld** | le programme de Hamlib qui garde la liaison avec le poste ; il n'écoute que sur le PC lui-même, jamais sur le réseau |
| **Passerelle** (`trx-gateway`) | le cœur de la station : sert la page web, vérifie les comptes, transporte le son et **décide de l'émission** |
| **Superviseur** (`trx-supervisor`) | le gardien indépendant : surveille la passerelle, rigctld et le PC ; il peut **seulement couper** une émission, relancer un service ou mettre la station en mode sûr ; envoie les alertes |
| **TRX Console** (`trx-console`) | le tableau de commande de la station dans un terminal : installer, configurer, démarrer, essayer, mettre à jour, dépanner (menus numérotés « 3.1 », « 2.2 »…) |
| **Assistant de configuration** (`trx-setup`) | les questions qui créent la configuration (menu 3.1) ; il n'interroge le poste qu'en lecture |
| **Tableau de bord** (`trx-monitor`) | l'état en direct dans un terminal (menu 1.3) ; une seule action : STOP TX |
| **Indicateur** | le voyant de la station dans la barre du haut (Debian) ou près de l'horloge (Windows) ; lecture seule |
| **Essai guidé** (`trx-hwtest`) | l'essai pas à pas du vrai poste (menu 2.2) |
| **Qualification** (`trx-qualif`) | l'exploration complète de ce que Hamlib déclare pour un poste (menu 2.7), pour experts |
| **`station.toml`** | le fichier de configuration de la station : poste, ports, comptes, bandes autorisées, sécurités |
| **Profil de poste** | une configuration de poste enregistrée sous un nom, pour changer de poste (menu 3.3) |
| **Module** | une fonction facultative qui tourne à côté de la passerelle (Cluster DX, présence de groupe…) |
| **Mise à jour signée** | les paquets Debian sont signés : la mise à jour par Internet (menu 6.1) refuse un paquet dont la signature ne correspond pas ; un zip non signé (menu 6.3) demande une confirmation |

## Côté utilisateur

| Terme | Ce que c'est |
|---|---|
| **Page web** | l'interface de la station dans un navigateur, à l'adresse `https://<adresse-de-la-station>:8443` |
| **Application Android** | l'application openRemoteTRX : la même chose que la page, plus l'émission écran éteint, le casque, la voiture |
| **Android Auto** | l'affichage de l'application sur l'écran de la voiture : écoute, mémoires, PTT, sans graphique |
| **Mode conduite** | l'écran réduit de l'application en voiture : pas de PTT tactile |
| **Compte opérateur** | identifiant + mot de passe qui permettent de commander le poste et d'émettre ; **un par appareil** (`PC`, `S25`…), gérés au menu 4.3 |
| **Visiteur** | compte en réception seule : écoute et voit l'écran, aucune commande |
| **Appairage** | l'ajout de la station dans l'application, par le **QR code** du menu 4.1 |

## La sécurité d'émission

| Terme | Ce que c'est |
|---|---|
| **PTT** | *Push To Talk* : le passage en émission |
| **PTT en bascule** | un appui pour émettre, un appui pour revenir en réception (jamais « tant qu'on appuie ») |
| **STOP** | retour immédiat en réception, toujours disponible |
| **TOT** | *Time Out Timer* : durée maximale d'une émission (90 s par défaut, 120 s au plus), avec un bip 10 s avant la coupure |
| **TOT absolu** | durée au-delà de laquelle le superviseur coupe toute émission, même celle faite au micro du poste (135 s ; 5 minutes si l'opérateur a touché le poste juste avant ou pendant) |
| **Battement** | le signe de vie que le téléphone envoie deux fois par seconde pendant l'émission ; s'il manque 2 s, retour en réception |
| **Bandes autorisées** | les plages de fréquences où la station accepte d'émettre ; liste vide = réception seule |
| **Opérateur sur place** | quelqu'un qui utilise le poste devant lui : l'émission à distance est bloquée pendant son émission puis 2 minutes |
| **Porte audio d'émission** | le passage du son vers le poste, ouvert par la passerelle seulement pendant une émission autorisée |
| **Mode sûr** | l'état où le superviseur met la station après des pannes répétées : réception, accès coupé ; se lève par le menu 1.5 |
| **Minuterie du poste** (TX TIME OUT TIMER) | la coupure propre au FTDX10, indépendante de la station : la dernière barrière |

## Le réseau

| Terme | Ce que c'est |
|---|---|
| **Réseau local** (LAN) | le réseau de la maison, derrière la box |
| **Port 8443** | le port où la passerelle reçoit la page et l'application |
| **HTTPS**, **certificat** | le chiffrement de la liaison ; la station crée son propre certificat (« auto-signé ») : le navigateur avertit la première fois |
| **Empreinte du certificat** | le résumé du certificat que l'application retient pour refuser une fausse station |
| **WebRTC** | la technique qui transporte le son en direct, par **UDP** |
| **VPN** | un tunnel chiffré qui met le téléphone « dans » le réseau de la maison, de n'importe où (WireGuard, Tailscale…) |
| **Profil VPN** | les clés d'un appareil dans le VPN : un profil par appareil, jamais partagé |
| **Port ouvert** | la box qui laisse entrer depuis Internet vers la station ; demande un vrai certificat et un mot de passe fort |
| **CGNAT** | adresse partagée par l'opérateur entre plusieurs clients : aucun port ne peut être ouvert, il faut un VPN |
| **ntfy** | le service de notifications qui porte les alertes de la station sur ton téléphone |
| **Code ORT** | le numéro d'un message de la station (« ORT-5031 ») ; chaque code a sa page d'explication |
