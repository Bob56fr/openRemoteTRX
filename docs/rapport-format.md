# Format du rapport de dépannage

Le rapport de dépannage est fabriqué par `trxstation/report.py` : menu 6.3 d'openRemoteTRX Console, ou envoyé masqué
par le monitoring entre stations (menu 6.5). Il est lu par des personnes et par l'**analyseur des rapports**
(https://rf-diy.com/analyseur-de-fichier-de-log-depannage-openremotetrx/, dépôt à part `openRemoteTRX-analyseur`), qui
ouvre le zip dans le navigateur de l'opérateur.

**Ce format est figé.** Une évolution AJOUTE un fichier ou un champ et l'écrit ici ; elle ne renomme ni ne supprime rien.
Un changement incompatible augmente `format` dans `rapport.json`. L'analyseur lit aussi les rapports des stations pas
encore mises à jour : tout fichier peut manquer.

## Nom du fichier

`trx-remote-rapport-AAAAMMJJ-HHMM.zip`, heure locale de la station, sur le Bureau du compte qui le fabrique.

## Fichiers du zip

| Fichier | Depuis | Contenu |
|---|---|---|
| `rapport.json` | 0.266.0 | Premier fichier du zip : description du rapport (ci-dessous). |
| `diagnostic.txt` | avant 0.266.0 | Résultat du diagnostic (menu 6.1), texte dans la langue de l'outil. Depuis 0.279.0, rubrique matériel : lignes « Ports USB » (une par bus qui porte le poste, une carte son ou un SDR : vitesse, périphériques avec leur rôle, débit estimé et charge en %, puis chaque constat avec sa marche à suivre ; nom du produit seulement, jamais de numéro de série). |
| `station.toml` | avant 0.266.0 | Configuration, secrets masqués (`"***"`), adresse ntfy réduite à son serveur. |
| `systeme.txt` | avant 0.266.0 | Sorties de commandes : `uname -a`, `/etc/os-release`, `systemctl get-default`. |
| `materiel.txt` | avant 0.266.0 | Sorties de commandes : ports série `/dev/serial/by-id/`, `lsusb`, cartes son (`arecord -l`, `aplay -l`) ; depuis 0.266.0 : modèle du Pi (`cat /proc/device-tree/model`) et sous-tension (`vcgencmd get_throttled`, valeur brute `throttled=0x…`). |
| `noyau.txt` | 0.266.0 | Sorties de commandes : `journalctl -k -b --no-pager -n 400` (démarrage en cours), `journalctl -k -b -1 --no-pager -n 200` (démarrage précédent, si le journal est persistant) ; `dmesg --ctime` à la suite si aucune n'a réussi. |
| `hamlib.txt` | avant 0.266.0 | Sortie de `rigctld --version`. |
| `python.txt` | avant 0.266.0 | Sortie de `pip freeze` de l'environnement de la station. |
| `services.txt` | avant 0.266.0 | Sortie de `systemctl status` des services de la station. |
| `journal.txt` | avant 0.266.0 | Sortie de `journalctl --no-pager -n 400 --unit=…` des services, **heure locale sans fuseau** (voir `rapport.json`). |
| `cluster-etat.json` | avant 0.266.0 | État du module Cluster DX (`{}` s'il est absent). |
| `station-id.txt` | avant 0.266.0 | Identifiant aléatoire de la station (GUID), ou « inconnu ». |
| `journaux/journal-passerelle.jsonl`, `journaux/journal-superviseur.jsonl` | 0.132.0 | Journaux structurés (une ligne JSON par événement, voir ci-dessous) ; fichier courant seulement. |
| `rapports-page/page-AAAAMMJJ-HHMMSS-<compte>.txt` | avant 0.266.0 | Les 10 derniers « Signaler un problème » envoyés par la page, relus par l'opérateur avant l'envoi. |
| `plantages/*.txt` | 0.153.0 | Traces des outils arrêtés sur une erreur inattendue (code ORT-9312), 10 au plus. |
| `installation.log` | avant 0.266.0 | Journal de la dernière installation (Debian). |
| `reseau.txt` | 0.268.0 | Sorties de commandes : `ip -br link`, `iw dev`, `cat /proc/net/wireless` (signal en dBm), puis pour chaque interface Wi-Fi `iw dev <wlan> link` (signal, débit) et `iw dev <wlan> get power_save` (mise en veille du Wi-Fi) ; dernière ligne : `# historique de la sonde réseau : …` (joint, absent avec la raison, ou illisible avec l'erreur). |
| `chauffe/chauffe.jsonl` | 0.274.0 | Historique de chauffe du superviseur (Linux), dernières 24 h (8 640 lignes au plus), une ligne JSON par relevé toutes les 10 s (voir ci-dessous). Absent hors Linux ou si le superviseur n'a jamais tourné en 0.274.0. |
| `reseau/donnees.json` | 0.268.0 | Historique ANONYME de la sonde réseau sur 30 jours : le `donnees.json` de l'export de la sonde (`trxstation/netprobe/export.py`, `format` 1 : réglages, statistiques, coupures, heures, dernières 24 h ; appareils renommés `appareil-N`, aucune adresse). Absent si la sonde n'a jamais tourné. |

## Sorties de commandes

Chaque commande d'un fichier `.txt` de sorties est écrite ainsi, commandes séparées par une ligne vide :

```
$ <commande et ses arguments>  (code <n>)
<sortie standard et sortie d'erreur>
```

- Deux espaces avant `(code n)`. `code 0` : réussite ; tout autre code : échec, la sortie dit pourquoi. Un échec n'est
  jamais caché ni remplacé par un fichier vide.
- **Droits refusés** (journal ou noyau illisible pour ce compte, depuis 0.266.0) : la même commande est relancée par
  `sudo -n` (jamais de mot de passe demandé) et ajoutée à la suite, `$ sudo -n <commande>  (code n)`. Le premier
  essai reste écrit. `sudo: a password is required` veut dire : pas de droit sudo sans mot de passe.

## `rapport.json`

```json
{
 "format": 1,
 "station": "0.266.0",
 "cree_utc": "2026-11-22T09:41:07Z",
 "fuseau": "Europe/Paris",
 "decalage_min": 60
}
```

- `format` : version de ce document (entier). Les champs s'ajoutent sans changer `format`.
- `station` : version d'openRemoteTRX qui a fabriqué le rapport.
- `cree_utc` : heure de fabrication, ISO 8601 en UTC.
- `fuseau` : fuseau horaire de la station (`timedatectl`, sinon `/etc/timezone`) ; `null` s'il est inconnu (Windows).
- `decalage_min` : décalage de l'heure locale avec l'UTC au moment du rapport, en minutes (60 = UTC+1). Sert à lire
  `journal.txt`, qui est en heure locale sans fuseau.

## Journaux structurés (`journaux/*.jsonl`)

Une ligne JSON par événement :

| Champ | Toujours | Contenu |
|---|---|---|
| `ts` | oui | Heure UTC, ISO 8601 aux millisecondes. |
| `processus` | oui | `passerelle` ou `superviseur`. |
| `niveau` | oui | `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `source` | oui | Nom du module Python qui écrit. |
| `message` | oui | Texte en français. |
| `code` | événement codé | Code `ORT-NNNN` du catalogue d'erreurs (https://bob56fr.github.io/openRemoteTRX/erreurs/). |
| `gravite`, `titre`, `contexte`, `module`, `connu` | événement codé | Gravité et titre du catalogue, variables de l'événement, module concerné. |
| `exception` | parfois | Trace Python d'une erreur. |

## Historique de chauffe (`chauffe/chauffe.jsonl`)

Écrit par le superviseur (`trxstation/heatlog.py`) dans `<state_dir>/chauffe.jsonl` (tourné à 4 Mo, deux anciens
fichiers gardés). Une ligne toutes les 10 s, et une tout de suite quand la température passe le seuil `temp_alert_c` :

| Champ | Toujours | Contenu |
|---|---|---|
| `ts` | oui | Heure UTC, ISO 8601 à la seconde. |
| `temp_c`, `capteur` | oui | Température du processeur (celle de l'alerte ORT-1010) et son capteur ; `null` si illisible. |
| `charge_1min` | oui | Charge moyenne sur 1 minute (`/proc/loadavg`). |
| `mhz_max` | oui | Fréquence la plus haute des cœurs en MHz (`null` si inconnue). |
| `cpu_pct` | oui | Processeur occupé depuis le relevé précédent, en % de la machine entière. |
| `top` | oui | `[[nom, %, n], …]` : programmes qui ont le plus occupé le processeur depuis le relevé précédent, regroupés par nom ; % d'UN cœur comme `top` (200 = deux cœurs), `n` = nombre de processus. 3 programmes, 8 au-dessus du seuil. Nom seul, jamais la ligne de commande ni le compte : `python:<module ou script>` pour un interpréteur, `noyau (kworker)` pour les fils du noyau. |
| `chaud` | au-dessus du seuil | `true`. |
| `capteurs` | au-dessus du seuil | Tous les capteurs hwmon : `{"coretemp Core 5": 84.0, "nvme Composite": 41.9, …}`. |
| `plus_chaud` | au-dessus du seuil | `[capteur, °C]` le plus chaud du processeur. |
| `coeurs_pct` | au-dessus du seuil | Occupation de chaque cœur logique en %, dans l'ordre de `/proc/stat`. |

## Masquage

Le rapport ne contient aucun mot de passe, jeton ni clé (`secrets.toml` n'y est jamais).

**Depuis 0.270.0, dans TOUS les fichiers du zip** (`station.toml`, `journal.txt`, journaux JSON, `diagnostic.txt`…) :
les numéros de série de la station sont relevés (noms `/dev/serial/by-id`, `SN=` de `port_usb`, `serial` du SDR,
`SerialNumber:` du noyau ; valeur entière et son dernier morceau, ex. `IC-7300MK2 13003336` et `13003336`) puis remplacés
par `***` partout ; le NOM DU MODÈLE reste (`Icom Inc. IC-7300MK2`). Avant 0.270.0, ces numéros restaient en clair hors
de `materiel.txt` et `noyau.txt`. Formes reconnues (0.266.0) :

- numéros de série masqués en gardant la forme de la ligne : `SerialNumber: ***`, `usb-Icom_Inc._IC-7300MK2_IC-7300MK2_***-if00` ;
- adresses MAC remplacées par `**:**:**:**:**:**`.

Depuis 0.268.0, dans `reseau.txt` en plus : nom du réseau Wi-Fi (`ssid ***`, `SSID: ***`), BSSID (comme une MAC) et
adresses IP **publiques** (IPv4 et IPv6, remplacées par `adresse-publique`) ; les adresses privées et locales restent.

## Ce que le rapport ne contient pas (encore)

- Historique de la mémoire et du disque (la station ne garde que la mesure du moment). Processeur et température :
  `chauffe/chauffe.jsonl` depuis 0.274.0 (Linux).

Envoyé par le monitoring entre stations, le rapport est en plus masqué par `trxstation/monlink/redact.py` (nom de la
machine, adresses, comptes).
