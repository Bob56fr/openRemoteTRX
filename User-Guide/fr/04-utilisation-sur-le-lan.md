# 4. Utiliser la station sur le réseau local

Le réseau local, c'est le Wi-Fi ou le câble de la maison : le téléphone et la station sont derrière la même box.

## 4.1 Une adresse fixe pour la station

Dans ta box, **réserve une adresse IP** au PC de la station (réservation DHCP). Le certificat créé par l'assistant
porte l'adresse du PC : si elle change, le navigateur et l'application ne le reconnaîtront plus. Après un
changement d'adresse, relance l'assistant (menu 3.1) pour refaire le certificat.

L'adresse à utiliser est affichée en tête de TRX Console et par le diagnostic.

## 4.2 La page web

1. Sur le téléphone ou un PC : `https://<adresse-de-la-station>:8443`
2. Le navigateur signale un **certificat non reconnu** : c'est attendu (certificat créé par ta station, pas par une
   autorité). « Avancé » puis « Continuer ». Cela ne se fait qu'une fois par appareil.
3. Connecte-toi avec le compte créé par l'assistant.

Ce que tu dois voir : fréquence et mode qui suivent le poste, S-mètre, son reçu (touche le bouton du son si le
navigateur l'a bloqué).

Pour **émettre**, la page a besoin du **micro** : le navigateur le demande à la première émission. Il ne le
propose qu'en HTTPS, d'où le certificat.

> **Sécurité.** Le PTT est une **bascule** : un appui pour émettre, un appui pour revenir en réception. L'état
> affiché est celui que la station confirme, jamais une supposition. **STOP** coupe à tout moment. Une page masquée
> (autre onglet, écran verrouillé) arrête l'émission.

## 4.3 Plusieurs utilisateurs

Chaque personne a **son compte**. Pour en ajouter un, relance l'assistant (menu 3.1) : il reprend tous tes
réglages (réponds « oui » à « Les garder » pour les comptes existants) et te laisse ajouter des identifiants ; à la
question du mot de passe, Entrée = un mot de passe fort est généré. Une seule personne peut émettre à la fois. Pour des auditeurs sans aucune commande, préfère les **visiteurs** (partie 9).

## 4.4 L'application Android

L'application (« openRemoteTRX », Android 10 ou plus récent) apporte ce que la page ne peut pas faire : émission
qui continue écran éteint, bouton d'un casque, Android Auto, mode conduite.

1. Installe l'application (test sur invitation, partie 0).
2. Sur la station, menu **4.1** : TRX Console affiche l'adresse, les comptes, l'empreinte du certificat et un
   **QR code** (sans mot de passe).
3. Dans l'application : « **Scanner le QR code de la station** ». L'adresse, l'identifiant et l'empreinte se
   remplissent ; saisis le mot de passe.
4. Connecte-toi : même vérification que pour la page (fréquence, son reçu), puis un essai d'émission sur charge
   fictive avec STOP.

L'empreinte du certificat protège la liaison : l'application refuse une station dont le certificat a changé.
Après un nouveau certificat (changement d'adresse), refais l'appairage.

> **Sécurité.** En voiture, le PTT tactile du téléphone est masqué (mode conduite) : utilise Android Auto, la
> commande vocale ou les touches du volant, et respecte le code de la route.
