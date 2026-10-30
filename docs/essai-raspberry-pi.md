# Essai sur un Raspberry Pi 4 sans bureau, tout par SSH depuis Windows (version 0.76.0)

But : savoir si un Raspberry Pi 4 suffit pour faire tourner la station (passerelle avec audio WebRTC, rigctld,
superviseur, spectre HF, visiteurs) et l'utiliser au quotidien sans écran, sans clavier ni bureau. Aucun Raspberry
Pi n'a jamais fait tourner la station avant cet essai. Le Pi 3 n'est pas essayé ici (voir la fin).

On part d'une carte SD vierge, avec Raspberry Pi OS **Lite 64 bits** (sans bureau). Tout se fait depuis le PC
Windows, dans un terminal PowerShell (Windows Terminal conseillé : accents, couleurs et QR code s'y affichent bien).
Note chaque écart (texte copié depuis le terminal) : c'est le résultat de l'essai.

## 0. Matériel

| Élément | Conseil |
| --- | --- |
| Raspberry Pi 4 | 2 Go au minimum, 4 Go conseillés |
| Alimentation | bloc officiel USB-C 5,1 V 3 A. Un chargeur de téléphone provoque des sous-tensions : le Pi ralentit, l'USB du poste décroche |
| Refroidissement | radiateur avec ventilateur, ou boîtier ventilé. Sans ça, le Pi 4 ralentit vers 80 °C, et la station déconnecte les visiteurs à 85 °C |
| Stockage | carte SD 32 Go « High Endurance » de classe A2, ou mieux un SSD en USB 3 (le Pi 4 démarre dessus) |
| Réseau | câble Ethernet conseillé pour l'essai (Wi-Fi possible, à noter) |
| Poste | IC-7300MK2 et son câble USB, branché directement sur un port USB du Pi. Hub alimenté si d'autres appareils USB |

## 1. Préparer la carte SD (PC Windows)

1. Une clé SSH existe-t-elle déjà sur le PC ? Dans PowerShell : `Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub`.
   Si le fichier n'existe pas : `ssh-keygen -t ed25519` (Entrée à chaque question).
2. Installer et ouvrir **Raspberry Pi Imager** (raspberrypi.com/software).
3. Appareil : **Raspberry Pi 4**. Système : *Raspberry Pi OS (other)* > **Raspberry Pi OS Lite (64-bit)**.
   Stockage : la carte SD.
4. Personnalisation, à remplir AVANT d'écrire la carte :
   - nom d'hôte : `trx-pi` ;
   - compte : `bob` et un mot de passe, indispensable pour `sudo` ;
   - Wi-Fi seulement si pas de câble (pays FR) ; fuseau `Europe/Paris`, clavier `fr` ;
   - **SSH activé**, « authentification par clé publique seulement », coller le contenu de `id_ed25519.pub`.
5. Écrire la carte, la mettre dans le Pi, brancher le réseau puis l'alimentation. Le premier démarrage prend
   2 à 3 minutes (le Pi redémarre une fois tout seul).

## 2. Première connexion SSH

1. Trouver l'adresse du Pi : liste des appareils de la box (nom `trx-pi`), ou `ping trx-pi.local`. Le nom en
   `.local` ne marche pas toujours, comme pour minix-bzh : dans ce cas, utiliser l'adresse IP. Le mieux est de
   réserver cette adresse dans la box (bail DHCP fixe).
2. `ssh bob@<IP du Pi>`. Répondre `yes` à la question sur l'empreinte (première connexion seulement).
3. Mettre le système à jour, puis redémarrer :

   ```
   sudo apt update && sudo apt full-upgrade -y && sudo reboot
   ```

4. Se reconnecter, puis faire un relevé de départ :

   ```
   cat /proc/device-tree/model; echo; uname -m; . /etc/os-release; echo "$PRETTY_NAME"
   vcgencmd get_throttled; vcgencmd measure_temp; free -m; df -h /
   ```

| Attendu | À noter |
| --- | --- |
| `Raspberry Pi 4 Model B …`, `aarch64`, Debian 12 ou 13 | modèle, mémoire totale, version |
| `throttled=0x0` | toute autre valeur : alimentation ou chaleur (voir § 6) |
| température au repos sous 55 °C | valeur |

## 3. Copier et installer la station

1. Sur le PC Windows, dans `C:\dev\openRemoteTRX` :

   ```
   python scripts/build_debian_zip.py --sans-signature
   scp dist\trx-remote-debian-0.76.0.zip bob@<IP du Pi>:
   ```

   Rien d'autre à copier : on part d'une station vierge, sans reprendre la `station.toml` d'une autre station.
2. Toujours depuis PowerShell sur le PC, sans ouvrir de session sur le Pi :

   ```
   $pi = "bob@<IP du Pi>"
   ssh -t $pi "sudo apt install -y unzip && unzip -oq trx-remote-debian-0.76.0.zip && cd trx-remote-debian-0.76.0 && time sudo bash install.sh"
   ```

   `-t` est indispensable : `sudo` demande le mot de passe et `install.sh` pose ses questions au clavier.
   Ne pas mettre de guillemets À L'INTÉRIEUR de la commande : PowerShell 5.1 les retire avant de la passer à `ssh`.
   `unzip -o` permet de relancer la même ligne après une correction.

| Attendu | À noter |
| --- | --- |
| Étape 1 : modèle du Pi affiché en vert, aucun avertissement d'alimentation ni de mémoire | avertissements |
| `pip` télécharge des modules déjà compilés pour arm64 : quelques minutes | durée totale (`time`). Si `pip` compile (`Building wheel for av`, `aiortc`…), noter quel module et la durée : c'est un défaut à corriger |
| Étape 8 : « pas de bureau : TRX Console se lance par la commande trx-console » | |
| Fin : « Installation terminée » | sinon la dernière ligne et `/var/log/trx-remote-install.log` |

3. Chaque commande `ssh` ouvre une NOUVELLE connexion, donc les nouveaux groupes (`dialout`, `audio`, `trx`)
   s'appliquent d'eux-mêmes. TRX Console, `trx-monitor` et les mesures se lancent de la même façon :

   ```
   ssh -t $pi trx-console
   ssh -t $pi trx-monitor
   ssh -t $pi /opt/trx-remote/venv/bin/python -m trxstation.devtools.station_load --minutes 10
   ```

4. **Hamlib récent pour l'IC-7300MK2.** Raspberry Pi OS (comme Debian) fournit un Hamlib trop ancien : le
   modèle 3094 (IC-7300MK2) n'arrive qu'avec Hamlib 4.7, et `install.sh` le signale par un avertissement. Le
   script `compiler-hamlib.sh` du zip compile Hamlib 4.7.2 dans `/usr/local` (de 10 à 30 minutes ; l'archive
   est vérifiée par son empreinte SHA-256). La station prend alors ce rigctld-là : `/usr/local/bin` passe
   avant `/usr/bin`, comme sur minix-bzh.

   ```
   ssh -t $pi "cd trx-remote-debian-0.76.0 && time sudo bash compiler-hamlib.sh"
   ssh $pi "rigctld --version; rigctl -l | grep -i 7300"
   ```

   Attendu : `Hamlib 4.7.2`, puis deux lignes, `3073 Icom IC-7300` et `3094 Icom IC-7300MK2`. Noter la durée.

## 4. Mesure sans le poste (faux poste Hamlib)

Le poste reste débranché. Cette mesure dit déjà si le processeur suffit pour l'audio WebRTC et les visiteurs.

```
/opt/trx-remote/venv/bin/python -m trxstation.devtools.listener_load --listeners 5 --seconds 30
```

L'outil lance une passerelle complète avec un faux poste, un opérateur et 5 visiteurs factices dans un autre
processus. Il mesure le processeur de la passerelle (en % d'un cœur) avec l'opérateur seul, puis avec les
visiteurs, et le pire retard de sa boucle.

| Mesure | Repère sur le PC de développement | Pi 4 |
| --- | --- | --- |
| opérateur seul (% d'un cœur) | | |
| par visiteur (% d'un cœur) | 5,5 % | |
| pire retard de la boucle | sous 100 ms (au-delà, la protection contre la surcharge déconnecte les visiteurs) | |

Pour essayer davantage, recommencer avec `--listeners 10`.

## 5. Brancher le poste et configurer

1. Brancher l'IC-7300MK2 sur le Pi et l'allumer.
2. `ls -l /dev/serial/by-id/` : deux ports, `…-if00` (CAT) et `…-if02` (spectre).
   `arecord -l` : la carte `USB Audio CODEC` du poste. La carte son du Pi (`bcm2835 Headphones`, `vc4hdmi`) ne
   sert pas.
3. `trx-console`, menu « Assistant de configuration », comme sur minix-bzh (`docs/essai-debian.md` § 3) :
   port A, cartes son du poste, comptes, bandes. Spectre HF : oui, port B (`-if02`).
4. TRX Console : « Démarrer la station », puis « Diagnostic ».

| Attendu | À noter |
| --- | --- |
| TRX Console s'affiche correctement en SSH : cadres, accents, couleurs | défauts d'affichage |
| Diagnostic : Python, modules, Hamlib, groupes, température du processeur (capteur `cpu_thermal`) OK | toute ligne en échec |
| `trx-monitor` dans une 2e fenêtre SSH : radio vivante, spectre HF vert, compteur « Trames » qui avance | |
| Menu 19 : le QR code s'affiche dans le terminal et le téléphone le lit | |

## 6. La station en marche : mesures

Dans une deuxième fenêtre SSH, pendant chaque situation ci-dessous :

```
/opt/trx-remote/venv/bin/python -m trxstation.devtools.station_load --minutes 10 --csv mesure-A.csv
```

L'outil ne fait que lire `/proc` et `/sys`, sans rien envoyer à la station. Une ligne s'affiche toutes les
5 secondes. Le bilan final donne, en moyenne et au pire :

- le processeur de toute la machine ;
- le processeur de chaque service : rigctld, passerelle, superviseur, autres (en % d'UN cœur) ;
- la température et la fréquence du processeur ;
- la mémoire disponible ;
- les Mo écrits par heure sur la carte SD ;
- les drapeaux `vcgencmd get_throttled`.

| Situation | Machine | Passerelle | rigctld | Temp. pire | Mo/heure | throttled |
| --- | --- | --- | --- | --- | --- | --- |
| A. station démarrée, aucun client | | | | | | |
| B. opérateur sur la page web (téléphone en Wi-Fi), spectre HF et waterfall affichés | | | | | | |
| C. B + application Android en même temps (autre compte) ou 2 visiteurs | | | | | | |
| D. émission sur **charge fictive**, puissance minimale, 1 minute | | | | | | |
| E. une nuit, aucun client (`--minutes 480`) : usure de la carte SD | | | | | | |

À juger aussi, à l'oreille et à l'œil :

- le son reçu sur le téléphone : coupures, craquements, retard comparé à minix-bzh ;
- la réactivité de la fréquence et du S-mètre ;
- la fluidité du spectre HF.

Repères :

- passerelle sous 50 % d'un cœur en B ;
- température sous 70 °C ;
- `throttled=0x0` du début à la fin.

`0x50005` veut dire « sous-tension en ce moment et depuis le démarrage » : changer l'alimentation.
`0x20002` veut dire « fréquence bridée », souvent par la chaleur.

## 7. Pannes

Les mêmes essais que sur minix-bzh (`docs/essai-debian.md` § 5), sur **charge fictive** :

| Essai | Attendu |
| --- | --- |
| `sudo systemctl kill -s SIGSTOP trx-gateway` pendant une émission | le superviseur coupe l'émission et relance la passerelle |
| couper le Wi-Fi du téléphone pendant une émission | retour en réception en 2 s au plus |
| débrancher l'USB du poste en réception, puis le rebrancher | la station repart seule |
| éteindre le poste quelques minutes | alerte « rig_absent », jamais de mode sûr ; reprise au rallumage |
| `sudo reboot` | la station redémarre seule, en réception (vérifier par `trx-console` après reconnexion SSH) |
| (facultatif) débrancher brutalement l'alimentation du Pi en réception | le Pi redémarre, la station repart en réception. Ce test peut abîmer la carte SD : à faire en dernier |

## 8. Conclusion à rapporter

- Le Pi 4 suffit-il pour : un opérateur seul ? un opérateur avec le spectre HF ? combien de visiteurs ?
- Durée de l'installation, et modules compilés s'il y en a eu.
- Mo écrits par heure. Au-delà de quelques dizaines de Mo par heure, prévoir le journal en mémoire
  (`Storage=volatile` dans `/etc/systemd/journald.conf`) ou un SSD. Ne pas le faire avant la mesure E.
- Tout défaut d'affichage de TRX Console ou de `trx-monitor` en SSH.

Ne pas faire tourner minix-bzh et le Pi en même temps sur le même poste : un seul maître par port série.

## Et le Raspberry Pi 3 ?

Jamais essayé, et déconseillé : son processeur est 2 à 3 fois plus lent que celui du Pi 4, il n'a qu'1 Go de
mémoire, et ses ports USB 2 partagent le bus de l'Ethernet. `install.sh` affiche un avertissement sur tout
modèle autre que Pi 4, Pi 400 et Pi 5. Si le Pi 4 se révèle juste, inutile d'essayer le Pi 3. S'il est très à
l'aise, on peut tenter le § 4 sur un Pi 3 pour voir.
