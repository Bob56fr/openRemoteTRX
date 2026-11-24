# 0. Avant de commencer

## Ce que tu vas obtenir

- Ton poste piloté depuis un **navigateur** (PC, tablette, téléphone) ou l'**application Android** : fréquence,
  mode, filtres, S-mètre, son reçu, et l'**émission en phonie** avec le micro du téléphone ou du PC.
- Une station qui **se protège seule** : elle démarre toujours en réception, coupe l'émission au bout d'une durée
  maximale (90 s par défaut), si le téléphone ne répond plus ou si la liaison tombe, et refuse d'émettre hors des
  bandes que tu as déclarées.
- Un **superviseur** indépendant qui surveille la station et peut t'envoyer des alertes sur ton téléphone.

## Comment c'est organisé

![Les briques d'une station openRemoteTRX](images/briques.svg)

- Tu utilises un **navigateur** ou l'**application Android**. Ils parlent à la **passerelle**, le cœur de la station,
  qui tourne sur le **PC de la station** à côté du poste.
- La passerelle commande le poste par **rigctld** (le programme de Hamlib) et échange le son avec la **carte son du
  poste**. C'est elle qui décide de l'émission et applique les sécurités.
- Le **superviseur** surveille le tout de façon indépendante : il ne peut que couper une émission, relancer un
  service, et t'envoyer des **alertes**.
- **openRemoteTRX Console**, le tableau de bord et l'indicateur sont tes outils sur le PC : ils lisent l'état de la station.
- La configuration tient dans un seul fichier, **`station.toml`**.

Chaque mot est expliqué dans le [glossaire](glossaire.md).

## Le matériel

| Élément | Ce qu'il faut |
|---|---|
| Le poste | un poste connu de Hamlib, son alimentation, une antenne. Les postes déjà essayés ont leur fiche : [Icom IC-7300MK2](postes/ic7300mk2.md) (validé), [Yaesu FTDX10](postes/ftdx10.md) (en cours de validation) |
| La liaison PC - poste | sur la plupart des postes récents, **un câble USB** qui transporte à la fois la commande (CAT) et le son ; sinon une interface externe (Digirig, SignaLink…) |
| Le PC de la station | PC sous **Debian 12 ou 13** avec bureau (recommandé), **Raspberry Pi 4 ou 5** sous Raspberry Pi OS 64 bits, ou PC **Windows 10/11** 64 bits. Il reste allumé en permanence près du poste |
| Le réseau | le PC relié à la box, de préférence **par câble** |
| Pour les essais | une **charge fictive** (50 Ω) qui supporte la puissance d'essai : **obligatoire** pour toute la partie 3 |
| Côté utilisateur | un téléphone Android 10 ou plus récent, ou n'importe quel navigateur récent |

## Debian, Raspberry Pi ou Windows ?

| | Debian (recommandé) | Raspberry Pi | Windows |
|---|---|---|---|
| Matériel | un PC, même ancien (2 cœurs, 4 Go) | Pi 4 (**4 Go** conseillés) ou Pi 5, alimentation officielle, refroidissement, de préférence un SSD | un PC 64 bits |
| Système | Debian 12 ou 13 | Raspberry Pi OS 64 bits (Debian 12 ou 13), avec ou sans bureau | Windows 10 ou 11 |
| Paquet | `trx-remote-debian-X.Y.Z.zip` | le **même** que Debian | `trx-remote-windows-X.Y.Z.zip` |
| Démarrage | au démarrage du PC, sans ouvrir de session | au démarrage du Pi, sans ouvrir de session | à l'**ouverture de ta session** (le PC doit rester avec ta session ouverte, verrouillée si tu veux) |
| Mises à jour | par Internet depuis openRemoteTRX Console, signature vérifiée | comme Debian | à la main, en relançant l'installateur d'une nouvelle version |
| Outils | openRemoteTRX Console (menus 1 à 8) | la même, sur le bureau du Pi ou par SSH depuis un autre PC | openRemoteTRX Console aussi, par l'unique raccourci menu Démarrer > openRemoteTRX (sauf les mises à jour, menus 7.x) |
| État | validé (IC-7300MK2) | en service chez un bêta-testeur ; charge (SDR, FreeDV, plusieurs visiteurs) pas encore mesurée | validé (IC-7300MK2) |

Le Raspberry Pi 3 et les modèles plus anciens sont trop lents pour le son en direct : l'installation le signale.

## Réglementation

> **Sécurité et responsabilité.** Tu restes responsable de chaque émission de ta station, **y compris à distance** :
> respect de ta licence, des bandes et des puissances autorisées, identification. Les conditions du trafic à
> distance dépendent du pays : renseigne-toi auprès de ton administration (en France : l'ANFR) avant de l'utiliser.
> Certains boutons de bande de la page (85, 45, 11 m) ne servent qu'à **l'écoute** : ce ne sont pas des bandes
> radioamateur.

## Où trouver le logiciel

Les paquets d'installation sont sur la page des versions du projet :
https://github.com/Bob56fr/openRemoteTRX/releases

- Debian et Raspberry Pi : `trx-remote-debian-X.Y.Z.zip` (et son fichier de signature `.sig`).
- Windows : `trx-remote-windows-X.Y.Z.zip`.

L'application Android est en **test sur invitation** (Google Play) : demande l'accès en ouvrant un ticket (partie 8).
Sans elle, la page web fait tout depuis le navigateur du téléphone.
