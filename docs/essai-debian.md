# Essai d'installation sur un PC Debian 13 (version 0.30.0)

But : valider sur une vraie machine ce qui n'a été que simulé (vrai systemd, vrai `pip`, PipeWire, lanceur
du bureau), puis faire tourner la station complète avec l'IC-7300MK2, spectre HF compris.
Note chaque écart (copie d'écran ou texte) : c'est le résultat de l'essai.

## 0. À préparer sur le PC Windows

- `dist/trx-remote-debian-0.30.0.zip` (paquet d'essai **non signé** : `python scripts/build_debian_zip.py --sans-signature`).
- La `station.toml` de la station Windows (comptes, mots de passe, alertes et bandes seront repris).
- Une clé USB pour les deux fichiers. Le poste peut rester débranché pour les étapes 1 à 3.

## 1. Installation

1. Sur le PC Debian, décompresser le zip dans Téléchargements (clic droit, « Extraire ici »).
2. Copier `station.toml` **à côté de `install.sh`** dans le dossier obtenu.
3. Clic droit dans le dossier, « Ouvrir dans un terminal », puis : `sudo bash install.sh`

| Attendu | À noter si différent |
| --- | --- |
| L'installation va jusqu'au bout sans erreur rouge | dernière ligne affichée + `/var/log/trx-remote-install.log` |
| Message d'import : comptes repris, port COM8 et cartes son « à choisir », spectre désactivé (second port COM7 inconnu ici) | notes affichées |
| Durée raisonnable de `pip` (aiortc, aiohttp…) : quelques minutes | durée, erreur de compilation éventuelle |

4. **Se déconnecter puis se reconnecter** (appartenance aux groupes `dialout`, `audio`, `trx`).
5. Relancer `sudo bash install.sh` une seconde fois : il doit réparer/mettre à jour sans rien écraser.

## 2. TRX Console et diagnostic

1. Menu des applications : « TRX Console ». Une fenêtre de terminal doit s'ouvrir avec le menu.
2. Menu « Diagnostic ».

| Attendu | À noter |
| --- | --- |
| Le lanceur ouvre bien un terminal (point non validé sous GNOME : `Terminal=true`) | ce qui se passe sinon |
| Diagnostic : Python, modules (aiortc, aiohttp, sounddevice), Hamlib (version de Debian 13), groupes OK | toute ligne en échec |
| « Configuration » : signale le port CAT et les cartes son à choisir (normal à ce stade) | |

## 3. Brancher le poste et configurer

1. Brancher l'IC-7300MK2 (USB), l'allumer.
2. Repérer ses ports : `ls -l /dev/serial/by-id/`
   L'IC-7300MK2 en montre **deux**. Relevé sur un vrai Debian 13 : `…-if00` = port A (CI-V, CAT) et
   `…-if02` = port B (spectre). L'assistant le contrôle de toute façon.
3. TRX Console, menu « Assistant de configuration » : choisir le port A, les cartes son du poste
   (noms `plughw:CARD=CODEC…`), accepter les modes données, garder comptes et bandes.
   À la question du spectre HF : **oui**, choisir le port B, vérifier USB SEND / USB Keying, taper OUI.

| Attendu | À noter |
| --- | --- |
| Test de liaison : fréquence, mode, PTT 0 | message d'erreur |
| Spectre : « OK : spectre disponible sur … (adresse CI-V B6h) » | sinon le message « PROBLÈME DE CONFIGURATION » complet |
| Si les deux ports sont inversés : l'assistant refuse le port A comme second port, ou ne trouve pas le poste : choisir l'autre | |

Variante en ligne de commande, station arrêtée :
`sudo systemctl stop trx-remote.target` puis
`sudo trx-setup --output /etc/trx-remote/station.toml --spectre /dev/serial/by-id/…-if02`

## 4. Station en marche

1. TRX Console : « Démarrer la station », puis « Diagnostic » et `trx-monitor`.

| Attendu | À noter |
| --- | --- |
| `systemctl status trx-remote.target` : rigctld, trx-gateway, trx-supervisor actifs | unité en échec + `journalctl -u <unité> -n 50` |
| `trx-monitor` : radio vivante, « Spectre HF » en vert | |
| Diagnostic : section « Spectre HF » OK | |
| **PipeWire** : le son du poste arrive bien à la passerelle (compteur « Trames » qui avance dans `trx-monitor`) — point connu à risque : PipeWire peut accaparer la carte son du poste | si les trames restent à 0 : `pactl list short sources` |

2. Page web depuis le téléphone (Wi-Fi) : adresse `https://<IP du PC Debian>:8443`, certificat auto-signé
   accepté. Connexion, son reçu, vue HF (deux appuis sur la zone des graphiques), boutons du poste, VFO.
3. Émission sur **charge fictive**, puissance minimale : PTT, STOP, puis couper le Wi-Fi du téléphone
   pendant l'émission : le poste doit repasser en réception.

## 5. Pannes et cas connus à observer

| Essai | Attendu | Point connu |
| --- | --- | --- |
| `sudo systemctl kill -s SIGSTOP trx-gateway` pendant une émission sur charge fictive | le superviseur coupe l'émission et relance la passerelle | puis `sudo systemctl kill -s SIGCONT trx-gateway` si besoin |
| Débrancher l'USB du poste en réception | retour au fonctionnement au rebranchement | |
| **Éteindre le poste** plusieurs minutes, puis le rallumer | alerte « rig_absent », aucune relance, jamais de mode sûr ; au retour du poste, rigctld est relancé et la station repart | corrigé en 0.30.0 après le premier essai réel |
| Redémarrer le PC | la station redémarre seule, en réception | |

## 6. Qualification du poste sur ce PC (facultatif ici)

Station arrêtée (`sudo systemctl stop trx-remote.target`), dans un dossier personnel :
`trx-qualif --config /etc/trx-remote/station.toml --plan` puis `trx-qualif --config /etc/trx-remote/station.toml`.
Voir `docs/qualification.md` et la procédure de l'essai de qualification.

## 7. Retour au PC Windows

Rien à faire : la station Windows n'a pas été modifiée. Ne pas faire tourner les deux stations en même
temps sur le même poste (un seul maître par port série).
