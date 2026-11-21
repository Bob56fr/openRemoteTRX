# Démarrage rapide

Pour les impatients : ton poste dans le navigateur en un quart d'heure. Le reste du guide explique chaque étape en
détail ; reviens-y au premier problème.

## Il te faut

- un poste connu de Hamlib, relié au PC : un câble USB pour la plupart des postes récents (commande et son), sinon une
  interface type Digirig ou SignaLink ;
- un PC sous **Debian 12 ou 13** ou **Windows 10 / 11** 64 bits, allumé en permanence près du poste, relié à la box ;
- une **charge fictive** pour la première émission ;
- un téléphone ou un PC avec un navigateur récent.

## 0. D'abord, le TOT du poste (2 min)

> **Sécurité.** Le **TOT** (*Time Out Timer*) est la minuterie qui coupe l'émission au bout d'un temps maximal.
> Règle celui du poste **avant tout le reste**.

**Pourquoi ?** À distance, tu ne vois pas ton poste. Si le PC de la station se fige, si le câble USB se débranche ou
si un programme plante pendant une émission, plus personne ne peut repasser le poste en réception : il continuerait
d'émettre une porteuse, gênerait la fréquence, chaufferait, et tu en resterais responsable.

**À quoi il sert.** La station a son propre TOT (90 s par défaut) et un superviseur qui la surveille. Le TOT du poste
est la **dernière barrière** : il est dans le poste lui-même, il coupe même quand le PC, le câble ou la station sont en
panne.

**Comment.** Dans le menu du poste, cherche « Time-Out Timer » (« Time-Out Timer (CI-V) » chez Icom) ou « TX TIME OUT TIMER » et choisis **3 minutes** :
plus long que le TOT de la station, il ne coupe jamais une émission normale.

- Icom IC-7300 / IC-7300MK2 : MENU > SET > Function > Time-Out Timer (CI-V).
- Yaesu FTDX10 : OPERATION SETTING > GENERAL > TX TIME OUT TIMER.
- Autre poste : son manuel, rubrique « Time-Out Timer » ou « TOT ».

Sur l'IC-7300MK2, la station relit ce réglage à chaque connexion et te prévient s'il est sur OFF.

## 1. Installer (5 min)

Télécharge le paquet de la dernière version : https://github.com/Bob56fr/openRemoteTRX/releases

**Debian** : extrais `trx-remote-debian-X.Y.Z.zip`, ouvre un terminal dans le dossier obtenu, puis

```
sudo bash install.sh
```

Déconnecte-toi puis reconnecte-toi à la fin.

**Windows** :

1. Installe d'abord **Hamlib 64 bits** (`hamlib-w64-X.Y.Z.exe`) : https://github.com/Hamlib/Hamlib/releases
2. Clic droit sur `trx-remote-windows-X.Y.Z.zip` > Propriétés > **Débloquer**, puis Extraire tout et double-clic sur
   **`installer.cmd`**.
3. Réseau de la maison en profil **Privé**, **veille désactivée**.

## 2. Configurer (5 min)

Ouvre **openRemoteTRX Console** (Debian : menu des applications ou `trx-console` ; Windows : menu Démarrer > **openRemoteTRX**),
puis le **menu 2.1** (l'assistant). Le poste n'est que lu : aucune émission. Ce qui compte :

| Question | Réponse |
|---|---|
| Modèle | tape le nom du poste (ex. `ic-7300`, `ftdx10`), choisis dans la liste |
| Port et débit | le port du poste ; le débit réglé dans le menu CAT du poste |
| PTT | **CAT** si l'assistant le propose |
| Cartes son | celle du poste, en réception et en émission |
| Bandes autorisées | les bandes de **ta licence**, rien d'autre. Liste vide = réception seule |
| Durée maximale d'une émission (TOT de la station) | **90** secondes (proposé, 120 au plus) |
| Accès réseau | « Réseau local ou VPN, en HTTPS » (proposé) |
| Compte | un identifiant ; Entrée sur le mot de passe en génère un fort : **note-le** |

Pour le reste, Entrée garde la valeur proposée.

## 3. Démarrer et vérifier (2 min)

1. **Menu 1.1** : la station démarre, poste en réception.
2. **Menu 6.1** (diagnostic) : corrige chaque ligne en **échec** avant d'aller plus loin ; la ligne dit quoi faire.

## 4. Se connecter (1 min)

1. Sur le téléphone ou un PC de la maison : `https://<adresse-de-la-station>:8443` (adresse affichée en tête de TRX
   Console).
2. Avertissement du certificat : « Avancé » puis « Continuer ». C'est normal (certificat fait par ta station) ; pour
   ne plus le voir : menu 4.4.
3. Connecte-toi avec le compte de l'assistant. Pas de son : touche le bouton du son, le navigateur l'avait bloqué.

Réserve l'adresse du PC dans ta box (réservation DHCP) : si elle change, le certificat ne vaut plus.

## 5. Avant la première émission : trois essais (3 min)

> **Sécurité.** Charge fictive branchée, puissance réduite, une bande de ta licence. Le **PTT est une bascule** : un
> appui pour émettre, un appui pour revenir en réception. Après chaque essai, regarde l'**écran du poste**, pas
> seulement la page.

| Essai | Attendu |
|---|---|
| Pendant une émission, bouton **STOP** | réception immédiate |
| Pendant une émission, ferme l'onglet (ou coupe le Wi-Fi du téléphone) | réception en 2 s environ |
| Fréquence hors de tes bandes, puis PTT | émission **refusée**, message dans la page |

Un seul essai raté : **n'émets pas**, arrête la station (menu 1.2) et lis la partie 8. Les neuf essais complets sont
à la partie 3.5 : fais-les avant d'émettre sur antenne.

## Et ensuite

- **Application Android** : menu 4.1, QR code à scanner (application en test sur invitation, partie 0).
- **Depuis l'extérieur** (4G, autre réseau) : VPN ou port ouvert, partie 5.
- **Alertes sur le téléphone** : menu 3.5, avec une alerte d'essai.
- **Un souci** : menu 6.1, puis le rapport du menu 6.3 à joindre à une demande d'aide (partie 8).
- **Tous les menus de la console** : https://rf-diy.com/trx-console-mode-demploi/
