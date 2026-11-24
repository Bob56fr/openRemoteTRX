# 2. Installer la station

L'installation ne commande jamais le poste : il peut rester allumé et branché. Choisis ton système dans les onglets
ci-dessous ; le choix vaut pour toute la page. À la fin, **openRemoteTRX Console** s'ouvre et propose l'assistant de
configuration : c'est la partie 3.

<!-- onglets -->
#### Debian

**Debian 12 ou 13, avec bureau.**

1. Télécharge `trx-remote-debian-X.Y.Z.zip` (partie 0) dans **Téléchargements**, clic droit > « Extraire ici ».
2. Dans le dossier obtenu : clic droit dans une zone vide > « Ouvrir dans un terminal », puis :

   ```
   sudo bash install.sh
   ```

   Ton mot de passe de session est demandé (rien ne s'affiche pendant la frappe : c'est normal). Le script installe
   Hamlib, Python, les modules, le compte de service et les services de la station.
3. À la fin, **déconnecte-toi puis reconnecte-toi** (les droits de ton compte changent).
4. Ouvre **openRemoteTRX Console** depuis le menu des applications (ou tape `trx-console` dans un terminal).

**Hamlib et les postes récents.** Debian 13 fournit Hamlib 4.6, qui ignore les postes récents (IC-7300MK2…) :
`install.sh` installe tout seul la version 4.7 des **backports officiels** de Debian. Sous Debian 12, si ton poste
manque dans `rigctl -l`, l'installation te le dit : lance alors `sudo bash compiler-hamlib.sh` dans le même dossier
(compilation de la dernière Hamlib, 10 à 30 minutes).

**Sans bureau (serveur)**, tout se fait par SSH : copie le zip, puis

```
unzip -q trx-remote-debian-*.zip && cd trx-remote-debian-*/ && sudo bash install.sh
```

ferme la connexion SSH, reconnecte-toi et tape `trx-console`.

#### Raspberry Pi

**Raspberry Pi 4 ou 5, Raspberry Pi OS 64 bits.** Le Pi utilise le **même paquet** que Debian.

> **Le Pi en station.** Déjà en service chez un bêta-testeur, mais sa charge n'est pas encore mesurée avec tout en
> marche (récepteur SDR, FreeDV, plusieurs visiteurs) : commence par les fonctions de base. Un Pi 3 ou plus ancien
> est trop lent pour le son en direct.

**Le matériel.**

| Élément | Conseil |
|---|---|
| Le Pi | Pi 4 avec **4 Go** (2 Go au minimum), ou Pi 5 |
| Alimentation | le bloc **officiel** (Pi 4 : USB-C 5,1 V 3 A ; Pi 5 : 5 V 5 A). Un chargeur de téléphone provoque des sous-tensions : le Pi ralentit et l'USB du poste décroche |
| Refroidissement | radiateur avec ventilateur, ou boîtier ventilé : sans lui, le Pi ralentit vers 80 °C |
| Stockage | carte SD 32 Go « High Endurance » classe A2, ou mieux un **SSD en USB 3** (le Pi démarre dessus, et il dure plus longtemps qu'une carte qui écrit jour et nuit) |
| Réseau | câble Ethernet conseillé ; le Wi-Fi marche, avec plus de coupures du son |

**1. Préparer la carte**, sur ton PC, avec **Raspberry Pi Imager** (raspberrypi.com/software) :

1. Appareil : ton modèle de Pi. Système : **Raspberry Pi OS (64-bit)** si un écran restera branché ; sinon
   *Raspberry Pi OS (other)* > **Raspberry Pi OS Lite (64-bit)**, sans bureau, tout se fera depuis ton PC.
2. Personnalisation, **avant** d'écrire la carte : un nom (par exemple `trx-pi`), un compte et son **mot de passe**
   (indispensable pour installer), le fuseau horaire et le clavier, le Wi-Fi seulement sans câble, et **SSH
   activé** (de préférence par clé publique).
3. Écris la carte, mets-la dans le Pi, branche le réseau, le poste, puis l'alimentation. Le premier démarrage prend
   2 à 3 minutes (le Pi redémarre une fois tout seul).
4. Trouve l'adresse du Pi dans la liste des appareils de ta box, et **réserve-la** (réservation DHCP, partie 4.1).

**2. Mettre le système à jour**, dans un terminal du Pi (avec bureau) ou depuis ton PC (sans bureau :
`ssh -l <compte> <adresse-du-pi>`) :

```
sudo apt update && sudo apt full-upgrade -y && sudo reboot
```

**3. Installer la station.**

- **Avec bureau** : exactement comme sous Debian (onglet Debian) : zip téléchargé et extrait, `sudo bash install.sh`
  dans un terminal ouvert dans le dossier, puis déconnexion et reconnexion.
- **Sans bureau**, depuis ton PC (PowerShell sous Windows, terminal sous Linux ou macOS), dans le dossier du zip
  téléchargé :

  ```
  scp -o User=<compte> trx-remote-debian-X.Y.Z.zip <adresse-du-pi>:
  ssh -t -l <compte> <adresse-du-pi>
  ```

  puis, sur le Pi :

  ```
  sudo apt install -y unzip
  unzip -q trx-remote-debian-X.Y.Z.zip && cd trx-remote-debian-X.Y.Z && sudo bash install.sh
  ```

  À la fin, tape `exit` et reconnecte-toi (`ssh -t -l <compte> <adresse-du-pi>`) : les droits de ton compte ont
  changé. Puis `trx-console`.

**Ce que l'installation fait en plus sur un Pi.**

- Elle affiche le modèle et signale un Pi trop ancien, une mémoire trop petite ou une **sous-tension** (alimentation
  trop faible) : corrige avant d'aller plus loin.
- Raspberry Pi OS 13 fournit Hamlib 4.6 : elle installe la 4.7 des backports officiels de Debian (postes récents comme
  l'IC-7300MK2). Sur Raspberry Pi OS 12, si ton poste manque dans `rigctl -l` : `sudo bash compiler-hamlib.sh` (de 10
  à 30 minutes sur un Pi).
- Elle met en marche le **chien de garde matériel** du Pi : si le système se fige plus de 15 secondes, le Pi
  redémarre tout seul, et la station repart en réception.
- Avec bureau, elle ajoute la police des pictogrammes d'openRemoteTRX Console.

**4. Vérifier l'alimentation et la température**, après quelques minutes de marche :

```
vcgencmd get_throttled; vcgencmd measure_temp
```

Attendu : `throttled=0x0` et moins de 70 °C. Toute autre valeur de `throttled` = alimentation trop faible ou
surchauffe : change l'alimentation ou ajoute un ventilateur. Une fois la station en marche, son superviseur
t'enverra une alerte (partie 6) si le Pi est ralenti, si la mémoire ou le disque se remplissent.

<details>
<summary>Travailler sans écran au quotidien</summary>

- **openRemoteTRX Console par SSH** : `ssh -t -l <compte> <adresse-du-pi> trx-console` (le `-t` est indispensable :
  la console pose des questions). Windows Terminal affiche bien les cadres, les couleurs et le QR code du menu 4.1.
- **Plus confortable : la console dans le navigateur.** Une fois, menu **4.6** (partie 7.5) ; ensuite
  `https://<adresse-du-pi>:8444/` depuis le PC, la tablette ou le téléphone, sans SSH.
- **Tableau de bord** : `ssh -t -l <compte> <adresse-du-pi> trx-monitor`, ou le tableau de bord des signes vitaux
  dans le navigateur (partie 7.1).
- **Éteindre le Pi** : `sudo poweroff`, puis attends que le voyant vert s'arrête de clignoter avant de couper
  l'alimentation (une coupure brutale peut abîmer la carte SD).

</details>

#### Windows

**Windows 10 ou 11, 64 bits.**

1. Installe **Hamlib 64 bits** (`hamlib-w64-X.Y.Z.exe`, version **4.7** ou plus récente : les postes récents comme
   l'IC-7300MK2 n'existent pas avant) depuis https://github.com/Hamlib/Hamlib/releases, dans le dossier proposé.
2. Copie `trx-remote-windows-X.Y.Z.zip` sur le PC. Clic droit > Propriétés > coche **Débloquer** > OK.
3. Clic droit > Extraire tout, puis double-clic sur **`installer.cmd`**. Si Windows affiche « Windows a protégé
   votre ordinateur » : Informations complémentaires > Exécuter quand même.
4. Accepte la demande d'administrateur et réponds aux questions (Python est installé s'il manque, avec ton accord).
5. Réglages de Windows indispensables :
   - réseau de la maison en profil **Privé** (le pare-feu n'ouvre la station que sur les réseaux privés) ;
   - **veille et hibernation désactivées** (Paramètres > Système > Alimentation) ;
   - *Paramètres > Confidentialité > Microphone* : accès autorisé aux applications de bureau (sinon le son reçu du
     poste est un silence) ;
   - carte son du poste (*Paramètres > Système > Son*, sortie « Haut-parleurs » du poste) : **volume à 100**,
     **améliorations audio désactivées**, format 16 bits 48000 Hz ; le niveau d'émission se dose sur le poste (Icom :
     USB MOD Level). Un volume réduit (38 vu sur un PC) donne une émission sans puissance. Son nom (« 2- USB Audio
     Device »…) change si le câble du poste passe sur une autre prise USB : refaire alors le menu 2.6.

La notice complète (`notice-windows.html`) est dans le paquet.

**openRemoteTRX Console sous Windows.** L'installation crée **un seul raccourci** : menu Démarrer >
**openRemoteTRX**. Il ouvre openRemoteTRX Console, avec les mêmes menus numérotés que sous Debian : ce guide
s'applique tel quel (1.1 démarrer, 2.1 configuration, 6.1 diagnostic…). Différences :

- **Mises à jour** (menus 7.1 à 7.3) : sous Windows, extrais le nouveau zip et lance son `installer.cmd` ; la
  configuration est gardée. Retour en arrière : relance `installer.cmd` de l'ancienne version.
- **Indicateur près de l'horloge** : menu 8.4 (le lancer, ou le lancer à chaque ouverture de session).
- **Désinstaller** : Paramètres > Applications > **openRemoteTRX** > Désinstaller (la configuration est gardée sauf si
  tu demandes de l'effacer).
- La configuration est dans `C:\ProgramData\trx-remote\station.toml` ; les commandes (`trx-console`, `trx-setup`,
  `trx-monitor`…) se lancent aussi dans un terminal ouvert **après** l'installation.
<!-- /onglets -->
