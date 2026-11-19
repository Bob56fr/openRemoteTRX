<!-- Fabriqué par scripts/build_station_toml_doc.py : ne pas modifier à la main (explications : docs/station-toml/contenu.toml). -->

# Réglages de la station : station.toml

TRX distant version 0.219.0. Page du site : https://bob56fr.github.io/openRemoteTRX/station-toml/

`station.toml` est le fichier de configuration de la station : le poste, les cartes son, le réseau, les sécurités d'émission, les comptes, les fonctions facultatives. Il est écrit par l'assistant de TRX Console et se modifie ensuite par TRX Console (menu 8.1, et les menus spécialisés cités pour chaque section). La station le **vérifie** à chaque démarrage : une valeur incohérente est refusée avec un message précis, jamais ignorée en silence.

**Débutant** : seuls les réglages courant vous concernent ; l'assistant les règle pour vous. Les réglages expert ont des valeurs par défaut sûres : n'y touchez qu'en connaissance de cause. Emplacement du fichier : `/etc/trx-remote/station.toml` (Debian, Raspberry Pi), `C:\ProgramData\trx-remote\station.toml` (Windows).

## Le poste [rig]

Le transceiver piloté par Hamlib : modèle, liaison CAT, commande du PTT, modes et puissance.

Se modifie : Assistant (menu 2.1), profils de poste (menu 2.3), ou menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `model` | courant | `0` | Numéro du modèle du poste dans Hamlib (liste : `rigctl -l`). 1 = poste factice, pour essayer sans matériel. Exemple : IC-7300MK2 : 3094 (Hamlib 4.7). |
| `port` | courant | `""` | Port série de la liaison CAT. Sous Linux, préférez le nom stable `/dev/serial/by-id/…` (il ne change pas d'un redémarrage à l'autre). Exemple : Windows : `COM8` ; Linux : `/dev/serial/by-id/usb-Silicon_Labs_…-if00-port0`. |
| `speed` | courant | `vide` | Débit série de la liaison CAT. Vide : le débit par défaut de Hamlib pour ce modèle. Doit être identique au réglage du poste. Exemple : 19200, 115200. |
| `ptt_type` | courant | `"RIG"` | Comment la station passe le poste en émission : `RIG` (commande CAT), `RTS` ou `DTR` (ligne d'un port série), `GPIO` / `GPION` (broche du Raspberry Pi), `NONE` (aucune : réception seule). **Sécurité** : La station relit l'état du PTT après chaque commande ; avec `NONE`, aucune émission n'est possible. |
| `ptt_port` | expert | `""` | Port de la commande PTT quand elle n'est pas sur le port CAT (RTS ou DTR d'un autre port). Vide : le port CAT. |
| `extra_conf` | expert | `[]` | Options supplémentaires passées à rigctld (`-C nom=valeur`), pour un poste qui en a besoin. **Sécurité** : Interdits ici : les options du spectre (`async`, `multicast_…`, réglées par [spectrum]) et `cache_timeout`. La station lance toujours rigctld avec `cache_timeout=0` (depuis 0.134.0) : avec un cache, rigctld renvoie après une coupure la valeur commandée au lieu de l'état réel du poste, et un poste resté en émission paraîtrait coupé. Exemple : ["civaddr=0x94"] |
| `tx_modes` | courant | `[]` | Modes dans lesquels l'émission est permise ; vide = tous. Sur les Icom, l'audio de la carte son USB n'est émis qu'en modes données (USB-D, LSB-D, FM-D…) : dans un autre mode, le poste modulerait avec son propre micro. **Sécurité** : Une demande d'émission dans un mode absent de la liste est refusée. La mesure de TOS utilise le premier mode FM permis ici (FM, PKTFM ou FM-D). Exemple : Icom : ["PKTUSB", "PKTLSB", "FM-D", "AM-D"]. |
| `max_power_w` | courant | `0` | Puissance maximale du poste en watts. 0 : inconnue, la page et l'application affichent des pourcentages au lieu de watts. Exemple : 100 pour un poste de 100 W. |
| `tuner` | courant | `false` | Le coupleur d'antenne intégré du poste est utilisé. À chaque connexion d'un opérateur, la station lit alors les réglages d'accord automatique du poste par le second port CI-V (IC-7300MK2 : [TUNER] Switch = Auto, PTT Start = ON) et prévient s'ils sont faux ou impossibles à vérifier. Elle ne les change jamais. **Sécurité** : À distance, sans accord automatique à la prise d'émission, une nouvelle fréquence peut émettre sur un TOS élevé. Hors des bandes radioamateur, l'accord au PTT n'est pas garanti par le poste. Exemple : true si l'antenne passe par le coupleur du poste ; false (défaut) sinon. (depuis 0.210.0) |

## Le son [audio]

Les deux sens audio entre la station et le poste (interface son type Digirig, SignaLink, ou carte USB du poste).

Se modifie : Assistant (menu 2.1), profils de poste (menu 2.3), ou menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `capture_device` | courant | `""` | Carte son qui reçoit l'audio du poste (le son entendu à distance). Vide : la carte par défaut du système. Exemple : Linux : `plughw:CARD=CODEC,DEV=0` ; Windows : `Microphone (USB Audio CODEC)`. |
| `playback_device` | courant | `""` | Carte son qui envoie l'audio vers le poste (votre voix en émission). Vide : la carte par défaut du système. |
| `sample_rate` | expert | `48000` | Fréquence d'échantillonnage. Seule la valeur 48 000 est gérée (codec Opus). Valeurs : 48000 uniquement. |
| `rx_gain_db` | courant | `0.0` | Gain appliqué au son reçu, en dB (négatif = moins fort). |
| `tx_gain_db` | courant | `0.0` | Gain appliqué au son envoyé au poste, en dB. **Sécurité** : Un excès sature l'émetteur : réglez-le sur charge fictive en surveillant l'ALC. |

## Réseau [network]

Comment la page web et l'application joignent la station. Voir aussi le guide d'accès distant (VPN ou port exposé avec HTTPS).

Se modifie : Assistant (menu 2.1), appairage d'un téléphone (menu 4.1), ou menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `rigctld_host` | expert | `"127.0.0.1"` | Adresse d'écoute de rigctld, le service Hamlib qui parle au poste. **Sécurité** : rigctld n'a AUCUNE authentification : il doit écouter en local seulement (127.0.0.1). La station refuse toute autre valeur. |
| `rigctld_port` | expert | `4532` | Port local de rigctld. |
| `gateway_bind` | courant | `"127.0.0.1"` | Adresse d'écoute de la station pour la page et l'application. `127.0.0.1` : cette machine seulement ; l'adresse de la machine sur votre VPN ; ou `0.0.0.0` : toutes ses adresses. **Sécurité** : Hors de la machine, HTTPS est exigé (`tls_cert`, `tls_key`), sauf `allow_insecure_http` dans un VPN. |
| `gateway_port` | courant | `8443` | Port de la station pour la page web et l'application. |
| `web_client` | expert | `true` | Sert la page web de contrôle sur le même port que l'application. false : application seulement. |
| `tls_cert` | courant | `""` | Certificat HTTPS de la station (fichier PEM). L'assistant en génère un ; son empreinte sert à l'appairage du téléphone (menu 4.1). |
| `tls_key` | courant | `""` | Clé privée du certificat HTTPS. **Sécurité** : Fichier secret : il ne doit être lisible que par la station. |
| `allow_insecure_http` | expert | `false` | Autorise l'écoute hors de la machine SANS HTTPS. À n'accepter que dans un VPN qui chiffre déjà tout. **Sécurité** : Sur Internet sans VPN, mots de passe et audio passeraient en clair : laissez false. |
| `trusted_proxies` | expert | `["127.0.0.1", "::1"]` | Adresses (ou plages) des relais de confiance devant la station, dont l'en-tête X-Forwarded-For est cru pour connaître l'adresse réelle du client. |
| `ice_servers` | expert | `["stun:stun.l.google.com:19302"]` | Serveurs STUN/TURN pour établir l'audio (WebRTC) à travers Internet. [] : réseau local ou VPN seulement. |

## Sécurités d'émission [safety]

Les règles que la station applique à TOUTE émission demandée à distance, indépendamment de la page et de l'application.

Se modifie : Menu 8.1 ; seuils de température : menu 3.1 ; rediffusion : assistant (menu 2.1). (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `tot_s` | courant | `90` | Temps maximal d'une émission (TOT) en secondes : au-delà, la station repasse en réception, avec un bip d'avertissement avant. Valeurs : Au-dessus de 0 et au plus `tot_ceiling_s`. **Sécurité** : Limite aussi la durée d'un enregistrement rediffusé (TOT moins 5 s). |
| `tot_ceiling_s` | courant | `120` | Plafond du TOT : la valeur de `tot_s` ne peut pas le dépasser. **Sécurité** : Le superviseur coupe de son côté au-delà de `[supervisor] tot_abs_s`, qui doit rester plus grand. |
| `enforce_bands` | courant | `true` | true : la station refuse d'émettre hors des `[[bands]]`. false : c'est le poste qui l'interdit (par exemple le « TX limit » des Icom) ; la responsabilité vous revient. **Sécurité** : Avec true et une liste de bandes vide, aucune émission n'est possible (réception seule). |
| `warn_before_s` | expert | `10` | Secondes avant la fin du TOT où l'avertissement est donné. Valeurs : Entre 0 et `tot_s`. |
| `heartbeat_interval_ms` | expert | `500` | Cadence attendue des battements du téléphone ou de la page pendant une émission (preuve que le client est toujours là). |
| `heartbeat_timeout_ms` | expert | `2000` | Sans battement depuis ce délai, la station repasse en réception (client perdu, réseau coupé). **Sécurité** : Ne l'augmentez pas sans raison : c'est ce qui coupe une émission dont le client a disparu. |
| `rig_temp_warn_c` | courant | `40` | Température du poste (si Hamlib la donne) à partir de laquelle un avertissement est affiché et envoyé. Valeurs : Entre 20 et 90 °C, plus petit que `rig_temp_cut_c`. |
| `rig_temp_cut_c` | courant | `50` | Au-delà, l'émission à distance est coupée et refusée jusqu'au retour sous `rig_temp_warn_c`. |
| `allow_replay` | courant | `false` | Autorise la rediffusion d'un enregistrement de l'audio reçu (page et application) : enregistrer un correspondant puis le renvoyer en émission. Demandé par l'assistant à l'ajout du poste ; refusé par défaut. **Sécurité** : Rediffuser l'émission d'une station à des tiers est en général INTERDIT au service amateur : n'activez qu'en connaissance de cause, sous votre responsabilité. (depuis 0.91.0) |
| `swr_alert` | courant | `2.0` | TOS au-dessus duquel la station prévient l'opérateur qui émet (bandeau rouge et bip dans la page), si le TOS lu reste au-dessus plus d'une seconde ; une alerte par émission. 0 : arrêt. Valeurs : 0, ou de 1,2 à 10. **Sécurité** : Alerte SEULEMENT : la station ne coupe jamais l'émission pour un TOS élevé (le poste réduit déjà sa puissance de lui-même). Exemple : 2.0 (défaut). (depuis 0.212.0) |

## Bandes autorisées [[bands]]

Une entrée par bande où l'émission est permise. **Liste vide = réception seule.** Les bandes proposées par l'assistant (IARU Région 1) sont un point de départ : vérifiez-les pour votre licence et votre pays.

Se modifie : Assistant (menu 2.1) ou menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `name` | courant | `obligatoire` | Nom de la bande, affiché dans les messages. Exemple : "40m" |
| `low_mhz` | courant | `obligatoire` | Limite basse de la bande, en MHz. Exemple : 7.000 |
| `high_mhz` | courant | `obligatoire` | Limite haute de la bande, en MHz. Exemple : 7.200 |

## Comptes [[clients]]

Une entrée par compte qui peut se connecter : opérateurs (contrôle complet) et visiteurs (écoute seule).

Se modifie : Assistant (menu 2.1), visiteurs (menu 4.2), commande `trx-setup --add-client`. (relu sans redémarrer).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `id` | courant | `""` | Identifiant de connexion du compte, saisi dans la page ou l'application. Exemple : "telephone", "voiture" |
| `token` | expert | `""` | Ancien secret en clair (anciennes versions). Toujours accepté, mais à remplacer par un mot de passe (`password_hash`). **Sécurité** : Un secret en clair dans le fichier est lisible par qui lit le fichier : remplacez-le. |
| `password_hash` | courant | `""` | Empreinte du mot de passe (scrypt) ; jamais le mot de passe lui-même. Écrite par l'assistant, le menu 4.2 ou `trx-setup --set-password`. |
| `role` | courant | `"operator"` | `operator` : contrôle complet ; `listener` : visiteur en écoute seule, aucune commande vers le poste. |
| `pseudo` | courant | `""` | Nom montré aux autres connectés à la place de l'identifiant (plusieurs comptes peuvent porter le même). |
| `enabled` | courant | `true` | false : connexion refusée, et une connexion en cours est fermée. |
| `expires` | courant | `""` | Date de fin du compte (AAAA-MM-JJ, heure de la station) ; vide : jamais. |
| `admin` | courant | `false` | true : ce compte opérateur peut aussi ouvrir TRX Console sur le réseau (`[remote_console]`, menu 4.6). Les autres opérateurs pilotent le poste mais n'administrent pas la station. Valeurs : Opérateurs seulement (jamais un visiteur). **Sécurité** : Le mot de passe d'un compte administrateur ouvre la configuration de la station : à ne pas prêter. (depuis 0.178.0) |

## Visiteurs en réception seule [access]

Des comptes qui écoutent la station et voient l'écran de l'opérateur, sans aucune commande vers le poste.

Se modifie : Menu 4.2. (relu sans redémarrer).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `max_listeners` | courant | `0` | Nombre de visiteurs connectés en même temps ; 0 : écoute des visiteurs fermée sur la station. Sinon, l'opérateur ouvre ou ferme l'écoute depuis sa page ou l'application. Valeurs : 0 à 20. |
| `max_operators` | expert | `4` | Nombre de connexions opérateur en même temps (quota à part : un visiteur ne prend jamais la place d'un opérateur). Valeurs : 1 à 8. |
| `listeners_need_operator` | courant | `true` | true : visiteurs admis seulement si un opérateur est connecté à distance. |
| `operator_grace_s` | expert | `60` | Après la perte du dernier opérateur, attente avant de déconnecter les visiteurs. Valeurs : 0 à 600 s. |
| `listeners_outside_bands` | courant | `false` | false : silence pour les visiteurs quand la réception sort des bandes de la station. |
| `listener_spectrum_fps` | expert | `5` | Cadence maximale du spectre HF envoyé aux visiteurs (images par seconde) ; l'opérateur garde la sienne. Valeurs : 1 à 20. |
| `overload_temp_c` | expert | `70` | Protection de la station : température du processeur au-delà de laquelle (pendant 10 s) les visiteurs sont déconnectés. Valeurs : 50 à 105 °C. |
| `overload_cpu_pct` | expert | `90` | Même protection : charge du processeur (tous cœurs) en %. Valeurs : 50 à 100 %. |
| `overload_lag_ms` | expert | `100` | Même protection : retard de la boucle de la station, en millisecondes. Valeurs : 20 à 2000 ms. |
| `overload_mem_pct` | expert | `10` | Même protection : mémoire libre minimale, en %. Valeurs : 1 à 50 %. |

## Mesure de TOS [swr]

La courbe de TOS de l'antenne, lancée depuis la page ou l'application : une courte porteuse FM par point. Dernière mesure : menu 5.4.

Se modifie : Menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `true` | false : la mesure de TOS n'est pas proposée. (depuis 0.90.0) |
| `max_power_pct` | courant | `50` | Plafond de puissance de la mesure, en % de la puissance du poste. L'opérateur choisit la puissance (15 % par défaut) sous ce plafond. Valeurs : 5 à 50 %. **Sécurité** : Jamais au-dessus de 50 % : quelques watts suffisent pour mesurer. (depuis 0.90.0) |
| `max_points` | expert | `50` | Nombre maximal de points d'une mesure. Valeurs : 2 à 200. (depuis 0.90.0) |
| `point_tx_max_s` | expert | `2.0` | Durée maximale de l'émission d'un point. Le temps réel est étalonné au premier usage pour chaque modèle de poste, sans dépasser cette valeur. Valeurs : 0,5 à 3 s. (depuis 0.90.0) |

## Breizh Audio Box dans l'émission [breizh]

Le son du micro passe par Breizh Audio Box (traitement de la voix) sur un autre PC du réseau local avant d'aller au poste. Si Breizh ne répond plus, la station repasse seule en direct. Le son du micro circule EN CLAIR sur le réseau local : seulement sur un réseau de confiance.

Se modifie : Menu 8.1 ; la clé d'appairage se crée avec TRX Console (fichier `breizh.key` à côté de station.toml). (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | true : le son du micro de l'opérateur passe par Breizh Audio Box pendant l'émission, quand Breizh répond. **Sécurité** : Breizh ne peut jamais déclencher ni prolonger une émission : la station garde le PTT, la porte audio d'émission et son limiteur. (depuis 0.99.0) |
| `host` | courant | `""` | Adresse IP du PC où tourne Breizh Audio Box (127.0.0.1 si c'est le même PC). Valeurs : Adresse IP privée seulement (RFC 1918 : 10/8, 172.16/12, 192.168/16 ; lien local 169.254/16 ; locale 127/8 ; IPv6 fd00::/8, fe80::/10). Ni nom d'hôte ni adresse publique. **Sécurité** : Le son du micro n'est pas chiffré : une adresse publique est refusée. (depuis 0.99.0) |
| `port` | expert | `47100` | Port UDP sur lequel Breizh attend la station (le même que dans l'onglet « OpenRemoteTRX » de Breizh). Valeurs : 1024 à 65535. (depuis 0.99.0) |
| `key_file` | expert | `""` | Fichier de la clé d'appairage partagée avec Breizh. Vide : `breizh.key` à côté de station.toml. La clé n'est jamais écrite dans station.toml. **Sécurité** : Fichier refusé s'il est lisible par tous les comptes. (depuis 0.99.0) |
| `block_timeout_ms` | expert | `40` | Délai au-delà duquel un bloc de son (10 ms) qui n'est pas revenu de Breizh part sans traitement, à gain réduit. Valeurs : 15 à 100 ms. (depuis 0.99.0) |
| `lost_ms` | expert | `100` | Sans aucun retour de Breizh pendant ce délai, l'émission continue en direct jusqu'à sa fin (repli). Valeurs : 50 à 500 ms, plus grand que block_timeout_ms. (depuis 0.99.0) |
| `fallback_gain_db` | expert | `-6.0` | Gain du son direct pendant un repli (Breizh perdu), pour ne pas surmoduler un son prévu pour être traité. Valeurs : -20 à 0 dB. (depuis 0.99.0) |
| `reactivate_after_s` | expert | `60` | Après un repli, durée pendant laquelle Breizh doit répondre sans faute avant d'être repris automatiquement (jamais pendant une émission). 0 : seulement quand l'opérateur le demande. Valeurs : 0, ou 30 à 3600 s. (depuis 0.99.0) |

## Sonde de qualité réseau [netprobe]

La station mesure en continu la liaison avec chaque téléphone ou navigateur connecté (pertes, temps aller-retour, gigue, coupures) et dit après une coupure quel tronçon a probablement lâché. Un petit indicateur l'affiche ; les statistiques des 30 derniers jours, l'effacement et l'export sont dans la page et l'application. La sonde ne fait que mesurer : elle n'agit jamais sur l'émission.

Se modifie : Menu 8.1. Les seuils de l'indicateur choisis dans la page ou l'application (statistiques, rubrique « Seuils ») sont rangés à part et priment sur ceux d'ici. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `true` | true : la station mesure la qualité de la liaison avec chaque client (battement réseau d'une seconde dans les deux sens, quelques dizaines d'octets). **Sécurité** : La sonde ne fait que mesurer et afficher : elle ne coupe ni ne déclenche jamais une émission. (depuis 0.106.0) |
| `heartbeat_interval_s` | expert | `1.0` | Période du battement réseau entre la station et chaque client. Valeurs : 0,5 à 10 s. (depuis 0.106.0) |
| `outage_missed_beats` | expert | `3` | Nombre de battements sans écho qui font déclarer une coupure. Valeurs : 2 à 20. (depuis 0.106.0) |
| `lan_target` | expert | `"auto"` | Box (passerelle du réseau local) que la station sonde pour savoir si une coupure vient de son propre réseau. auto : la passerelle par défaut de la machine. (depuis 0.106.0) |
| `internet_target` | expert | `"1.1.1.1"` | Adresse sur Internet que la station sonde pour savoir si une coupure vient de la connexion de la box. Vide : aucune sonde Internet. (depuis 0.106.0) |
| `loss_warn_pct` | expert | `2.0` | Perte de battements sur 60 s à partir de laquelle l'indicateur passe à l'orange (valeur de départ). Valeurs : 0,1 à 100 %, plus petit que loss_alert_pct. (depuis 0.106.0) |
| `loss_alert_pct` | expert | `5.0` | Perte de battements sur 60 s à partir de laquelle l'indicateur passe au rouge (valeur de départ). Valeurs : 0,1 à 100 %. (depuis 0.106.0) |
| `rtt_warn_ms` | expert | `250` | Temps aller-retour (p95 sur 60 s) à partir duquel l'indicateur passe à l'orange. Valeur de départ : la rubrique « Seuils » des statistiques propose des valeurs d'après vos mesures. Valeurs : 20 à 5 000 ms, plus petit que rtt_alert_ms. (depuis 0.106.0) |
| `rtt_alert_ms` | expert | `600` | Temps aller-retour (p95 sur 60 s) à partir duquel l'indicateur passe au rouge (valeur de départ). Valeurs : 20 à 5 000 ms. (depuis 0.106.0) |
| `alert_outage_s` | courant | `10` | Une coupure plus longue envoie une alerte par l'adresse de notification de [supervisor] (notify_url). 0 : aucune alerte de coupure. Valeurs : 0 à 3 600 s. (depuis 0.106.0) |
| `alert_cooldown_s` | expert | `300` | Délai minimal entre deux alertes de la sonde (coupure, perte). Valeurs : 30 à 86 400 s. (depuis 0.106.0) |
| `log_retention_days` | expert | `7` | Durée de conservation des mesures détaillées (résumés de 10 s). Valeurs : 1 à 30 jours. (depuis 0.106.0) |
| `stats_retention_days` | expert | `30` | Durée de conservation des coupures et des statistiques horaires (vue des 30 derniers jours). Valeurs : 7 à 90 jours. (depuis 0.106.0) |
| `vpn_shared_warn` | courant | `true` | true : avertit quand deux appareils semblent partager le même profil VPN (même adresse privée, ou coupures très régulières), cause connue de coupures toutes les 15 à 30 s. (depuis 0.106.0) |
| `rsrp_warn_dbm` | expert | `-105` | Signal 4G/5G mesuré par l'application (RSRP) sous lequel l'indicateur passe à l'orange. Valeurs : -140 à -40 dBm, au-dessus de rsrp_alert_dbm. (depuis 0.106.0) |
| `rsrp_alert_dbm` | expert | `-115` | Signal 4G/5G (RSRP) sous lequel l'indicateur passe au rouge. Valeurs : -140 à -40 dBm. (depuis 0.106.0) |
| `sinr_warn_db` | expert | `3` | Rapport signal/bruit 4G/5G mesuré par l'application sous lequel l'indicateur passe à l'orange. Valeurs : -20 à 30 dB, au-dessus de sinr_alert_db. (depuis 0.106.0) |
| `sinr_alert_db` | expert | `0` | Rapport signal/bruit 4G/5G sous lequel l'indicateur passe au rouge. Valeurs : -20 à 30 dB. (depuis 0.106.0) |

## Présence de groupe [presence]

Un groupe d'amis équipés d'openRemoteTRX voit qui est actif sur sa station et, si chacun le veut, sur quelle fréquence et dans quel mode. Un relais sur Internet transporte des états CHIFFRÉS qu'il ne peut pas lire. Le module « presence » n'a aucun droit sur le poste : il ne peut ni émettre ni changer de fréquence ; un QSY vers un ami se fait seulement par un appui de l'opérateur, en réception.

Se modifie : Menu 8.1, et ajouter « presence » à `[modules] run`. Les groupes, le pseudo et ce qui est partagé se règlent dans la page, l'application ou TRX Console (rangés à part, pas dans station.toml). (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | true : la station s'enregistre auprès du relais et échange la présence avec les groupes dont elle est membre (« presence » doit aussi figurer dans `[modules] run`). **Sécurité** : La présence ne fait que montrer : aucune donnée reçue du relais ne peut commander le poste. (depuis 0.117.0) |
| `relay_url` | expert | `"https://rf-diy.com/orx-relay/public"` | Adresse du relais de présence. Valeurs : https:// obligatoire ; http:// seulement vers 127.0.0.1 ou localhost (essais avec un relais sur la même machine). Exemple : Relais par défaut : `https://rf-diy.com/orx-relay/public` ; essai local : `http://127.0.0.1:8099`. (depuis 0.117.0) |
| `key_file` | expert | `""` | Fichier des clés de la station pour la présence (signature et réception des clés de groupe). Vide : `presence.key` dans le dossier d'état, créé par le module au premier démarrage. Relatif : à côté de station.toml. **Sécurité** : Ce fichier identifie la station auprès du relais et des groupes : ne jamais le copier sur une autre station. (depuis 0.117.0) |

## Monitoring inter-stations [monitor_link]

Pour AIDER un opérateur en difficulté, ou ÊTRE AIDÉ, sans VPN ni port ouvert : la station de l'opérateur aidé envoie, par le même relais que la présence et chiffré de bout en bout, ce que SON opérateur a accepté (battement, santé de la machine, état du poste sans fréquence ni mode par défaut, codes d'erreur), toujours masqué (mots de passe, adresses, numéros de série). La station qui aide ne peut que lire et DEMANDER : aucune commande vers la station aidée n'existe. Le module « monlink » n'a aucun droit sur le poste.

Se modifie : Menu 8.1, et ajouter « monlink » à `[modules] run`. Pseudo, invitations, liaisons et profils d'envoi se règlent dans TRX Console (rangés à part, pas dans station.toml). (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | true : la station s'enregistre auprès du relais du monitoring, relève les messages de ses liaisons et envoie ce que chaque profil permet (« monlink » doit aussi figurer dans `[modules] run`). Sans liaison confirmée, rien ne part. **Sécurité** : Le monitoring ne fait que lire et montrer : aucun message reçu ne peut commander le poste ni la station. (depuis 0.159.0) |
| `relay_url` | expert | `"https://rf-diy.com/orx-relay/public"` | Adresse du relais du monitoring (le même que celui de la présence). Valeurs : https:// obligatoire ; http:// seulement vers 127.0.0.1 ou localhost (essais avec un relais sur la même machine). Exemple : Relais par défaut : `https://rf-diy.com/orx-relay/public` ; essai local : `http://127.0.0.1:8099`. (depuis 0.159.0) |
| `key_file` | expert | `""` | Fichier des clés de la station pour le monitoring (signature, chiffrement des liaisons). Vide : `monlink.key` dans le dossier d'état (sous-dossier `monlink`), créé par le module au premier démarrage. Relatif : à côté de station.toml. Différent des clés de la présence : les deux services ne peuvent pas être reliés. **Sécurité** : Ce fichier identifie la station auprès de ses partenaires de monitoring : ne jamais le copier sur une autre station. (depuis 0.159.0) |

## Diffusion en direct [diffusion]

Faire entendre le son du TRX à quelques internautes qui n'ont AUCUN compte sur la station, comme un podcast en direct : la station envoie le son à un serveur de diffusion (Icecast), et les auditeurs l'écoutent sur la page de ce serveur ou dans VLC. Ils ne joignent jamais la station. Fermée par défaut, privée par défaut (identifiant et mot de passe d'auditeur), 1 heure par défaut ; la voix émise par l'opérateur n'est diffusée que s'il le demande. Le module « diffusion » n'a aucun droit sur le poste. Aucun serveur n'est imposé : celui que donne l'administrateur du serveur, avec le mot de passe source et la clé des métadonnées (fichier à part, jamais dans station.toml).

Se modifie : Menu 8.1, et ajouter « diffusion » à `[modules] run`. Protocole : `docs/protocole-diffusion.md` du dépôt. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | true : le module « diffusion » accepte qu'un opérateur lance une diffusion. Aucune diffusion ne démarre seule, ni au démarrage, ni après une relance de la passerelle ou un mode sûr. **Sécurité** : Activer la rediffusion de son TRX est de la responsabilité de l'opérateur (la station ne filtre pas les bandes). (depuis 0.188.0) |
| `server` | courant | `""` | Nom du serveur de diffusion, donné par son administrateur. Vide : aucune diffusion possible (aucun serveur imposé). Exemple : server = "diffusion.example.org" (depuis 0.188.0) |
| `station` | courant | `""` | Nom de la station sur ce serveur (2 à 32 caractères a-z, 0-9 et -), donné par son administrateur : il forme l'adresse de la page des auditeurs (`https://<serveur>/ecoute/<station>`) et des flux. Exemple : station = "f4xyz" (depuis 0.188.0) |
| `source_port` | expert | `8443` | Port TLS où la station envoie le son, directement au serveur Icecast (pas le port 443 : un mandataire HTTP ne sait pas relayer une source). Valeurs : 1 à 65535 (depuis 0.188.0) |
| `api_port` | expert | `443` | Port HTTPS des métadonnées (pseudo, fréquence…) et du nombre d'auditeurs. Valeurs : 1 à 65535 (depuis 0.188.0) |
| `codec` | courant | `"opus"` | `opus` (32 kb/s, le plus léger, par défaut) ou `mp3` (64 kb/s : anciens iPhone, applications de radio). (depuis 0.188.0) |
| `audio_port` | expert | `47822` | Port UDP par lequel la passerelle donne le son au module, en 127.0.0.1 seulement (paquets signés d'un jeton). À changer seulement si un autre programme le prend. Valeurs : 1024 à 65535, différent de [modules] bus_port et de [sdr] audio_port (depuis 0.188.0) |
| `key_file` | expert | `""` | Fichier des secrets de la diffusion (mot de passe source, clé des métadonnées, identifiant et mot de passe des auditeurs). Vide : `diffusion.key` dans le dossier d'état (sous-dossier `diffusion`). Relatif : à côté de station.toml. **Sécurité** : Droits 0600 exigés sous Linux : un fichier lisible par d'autres comptes est refusé. Ne jamais le joindre à un message. (depuis 0.188.0) |
| `tls` | expert | `true` | true : connexions chiffrées et certificat du serveur vérifié. false seulement vers 127.0.0.1 (faux serveur d'essai, `python -m trxstation.devtools.fake_icecast`). **Sécurité** : Refusé vers tout autre serveur : le mot de passe source passerait en clair. (depuis 0.188.0) |
| `outside_bands` | courant | `false` | false (défaut) : silence pour les auditeurs quand la réception sort des bandes autorisées (`[[bands]]`) ou que la fréquence est inconnue, sans arrêter la diffusion : le son revient dès que le poste rentre dans une bande. true : tout est diffusé, quelle que soit la fréquence. Indépendant de `[access] listeners_outside_bands` (visiteurs). **Sécurité** : Ce qui est diffusé est de la responsabilité de l'opérateur (décision de l'utilisateur du 2026-11-17). (depuis 0.189.0) |

## TRX Console sur le réseau [remote_console]

TRX Console dans le navigateur, depuis n'importe quel PC, tablette ou téléphone du réseau local ou du VPN, sans SSH : `https://<station>:8444/`. On s'y connecte avec un compte **opérateur marqué administrateur** (`admin = true` dans `[[clients]]`) ; la session se ferme après 30 minutes sans action. La console tourne sous un compte Linux ordinaire, jamais root : le mot de passe sudo reste demandé dans le terminal, une fois par session. Jamais joignable depuis Internet (adresses publiques refusées).

Se modifie : Menu 4.6 de TRX Console. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | true : la station sert TRX Console en HTTPS sur le réseau (service `trx-console-web@compte` sous Debian, processus du superviseur sous Windows). **Sécurité** : Un compte administrateur vaut presque un accès SSH à la station : mot de passe solide, réseau local ou VPN seulement. 5 échecs bloquent l'adresse 15 minutes ; chaque connexion envoie une alerte ntfy. (depuis 0.178.0) |
| `account` | courant | `""` | Compte Linux sous lequel tourne la console (celui de l'opérateur qui administre : il doit pouvoir utiliser sudo et faire partie du groupe `trx`). Vide sous Windows. Valeurs : Nom de compte Linux : minuscules, chiffres, _ . - (32 caractères au plus). Jamais root. Exemple : `account = "pi"` (depuis 0.178.0) |
| `port` | expert | `8444` | Port HTTPS de la console. L'adresse d'écoute est celle de la page de pilotage (`[network] gateway_bind`), avec le même certificat. Valeurs : 1024 à 65535, différent du port de la page de pilotage et de rigctld. (depuis 0.178.0) |
| `idle_min` | expert | `30` | Durée sans action (menu ouvert, touche tapée) après laquelle la session se ferme : il faut se reconnecter. Valeurs : 5 à 240 minutes. (depuis 0.178.0) |

## FreeDV en réception [freedv]

La station décode elle-même la voix numérique FreeDV (RADE V1) avec deux programmes de l'équipe FreeDV, lancés seulement quand l'opérateur choisit le mode FreeDV dans la page : tous les connectés, visiteurs compris, entendent alors la voix décodée à la place du son du poste, avec la synchro, le SNR et les indicatifs reçus. Réception seulement : rien n'est émis, et le poste n'est pas touché.

Se modifie : Menu 8.1 ; le mode FreeDV se choisit dans la page (rubrique « FreeDV »), il n'est pas gardé au redémarrage. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | true : FreeDV est proposé dans la page (rubrique et voyant « FDV ») ; les décodeurs ne tournent que pendant le mode FreeDV choisi par l'opérateur. **Sécurité** : Réception seulement : le mode FreeDV ne change ni la fréquence ni le mode du poste, et se refuse pendant une émission. Une panne des décodeurs n'arrête jamais la station : après 5 relances en 10 minutes, le son du poste revient. (depuis 0.122.0) |
| `ka9q_path` | expert | `"freedv-ka9q"` | Programme qui décode la voix et l'indicatif (freedv-ka9q, de freedv-integrations). Un nom seul est cherché dans le PATH, puis parmi les décodeurs livrés avec la station (paquet Windows). Debian et Raspberry Pi : `sudo bash compiler-freedv.sh` (dossier du paquet) les compile et les met dans le PATH ; rien à régler ensuite. Valeurs : Chemin d'un fichier, ou nom seul ; jamais vide. Introuvable : le mode FreeDV est refusé avec le nom du programme manquant. Exemple : `freedv-ka9q` (défaut, Debian et Windows), ou le chemin complet d'un programme compilé à part. (depuis 0.122.0) |
| `radae_rx_path` | expert | `"radae_rx"` | Programme qui donne la synchro, le SNR et le décalage de fréquence (radae_rx, de rade_c). Un nom seul est cherché dans le PATH, puis parmi les décodeurs livrés avec la station (paquet Windows), comme freedv-ka9q. Valeurs : Chemin d'un fichier, ou nom seul ; jamais vide. Exemple : `radae_rx` (depuis 0.122.0) |
| `locator` | courant | `""` | Locator Maidenhead de la station. Sert à la liste « Activité FreeDV » (module `freedv_activity` de `[modules] run`) : distance de chaque station et note de chance de réception. Il n'est envoyé nulle part : FreeDV Reporter est lu en simple observateur. Valeurs : 4 ou 6 caractères (JN18 ou JN18du), ou vide (liste sans distance, note moins juste). Exemple : `JN18du` (depuis 0.125.0) |

## Récepteur SDR [sdr]

Un récepteur SDR en parallèle du TRX, en réception seule : son waterfall s'affiche dans la page (rubrique « SDR »). Le SDR est désigné par son numéro de série. Il faut installer à la main l'API du fabricant AVANT la station, qui compile alors le programme sdr-core, et ajouter « sdr » à `[modules] run`.

Se modifie : Menu 8.1 ; le centre, le gain et la cadence se règlent ensuite depuis la page. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | true : la rubrique « SDR » (waterfall d'un récepteur SDR en parallèle du TRX) est proposée aux opérateurs. Il faut aussi « sdr » dans `[modules] run` et le numéro de série du SDR dans `serial`. **Sécurité** : Réception seulement : le module SDR n'a aucun droit sur le poste ; « QSY du TRX » passe par la commande habituelle de fréquence, refusée pendant une émission. Une panne du SDR n'arrête jamais la station. La protection de l'entrée du SDR contre la puissance émise par le TRX (antenne séparée, séquenceur) est à la charge de l'opérateur. (depuis 0.140.0) |
| `driver` | expert | `"sdrplay"` | Type de SDR. `sdrplay` : RSP de SDRplay, dont l'API s'installe à la main (logiciel du fabricant) AVANT l'installation de la station. `rtlsdr` (station 0.149.0+) : clé RTL-SDR (dont la RTL-SDR Blog V4), pilote installé par la station elle-même ; le pilote TV du noyau est écarté. Se choisit au menu 2.4 de TRX Console avec le SDR. Valeurs : `sdrplay` ou `rtlsdr`. (depuis 0.140.0) |
| `serial` | courant | `""` | Numéro de série du SDR de cette station. Le SDR est toujours désigné par ce numéro, jamais par son port USB : sur une machine qui a plusieurs SDR, chacun sert la bonne application. `trx-sdr --list` montre les SDR libres et ceux déjà pris par une autre application. Valeurs : Lettres et chiffres, 4 à 32 ; obligatoire quand `enabled = true`. Numéro absent au démarrage : le module attend (nouvel essai toutes les 30 s) et n'ouvre jamais un autre SDR. **Sécurité** : Ne jamais mettre le numéro d'un SDR utilisé par une autre application de la machine. Exemple : `1234567ABC` (depuis 0.140.0) |
| `core_path` | expert | `""` | Programme sdr-core (cœur natif du module SDR). Vide : celui que l'installation a compilé (à côté de la station), sinon le PATH. Valeurs : Chemin d'un fichier, ou vide. (depuis 0.140.0) |
| `sample_rate_hz` | courant | `2000000` | Largeur couverte par le waterfall du SDR (fréquence d'échantillonnage). 2 MHz couvre une bande HF entière ou la bande 2 m et charge peu la machine ; 6 et 8 MHz demandent beaucoup plus de calcul. Valeurs : SDRplay : 2000000, 6000000 ou 8000000 ; clé RTL-SDR : 1024000, 2048000 ou 2400000 (Hz). Exemple : `2000000` (depuis 0.140.0) |
| `center_hz` | courant | `7100000` | Fréquence centrale du SDR au premier démarrage. La dernière choisie depuis la page est ensuite reprise (rangée sur la station, pas dans ce fichier). Valeurs : 1 000 à 2 000 000 000 Hz. Exemple : `7100000` (depuis 0.140.0) |
| `antenna` | courant | `"A"` | Entrée d'antenne du SDR (RSP2 : A ou B ; sans effet sur une clé RTL-SDR, qui n'en a qu'une). Valeurs : A ou B. (depuis 0.140.0) |
| `lna_state` | expert | `2` | État du préamplificateur (LNA) au premier démarrage : 0 = gain maximal. Se règle ensuite depuis la page, où il est présenté à l'endroit (curseur « Gain RF » : 8 = gain maximal). Valeurs : 0 à 8. (depuis 0.140.0) |
| `gain_reduction_db` | expert | `50` | Réduction de gain de la FI au premier démarrage, utilisée quand l'AGC de la FI est coupé (`agc = false`). Se règle ensuite depuis la page ; à augmenter en cas de surcharge signalée. Valeurs : 20 à 59 dB. (depuis 0.140.0) |
| `agc` | courant | `true` | AGC matériel de la FI : le SDR règle lui-même la réduction de gain FI pour garder le signal au bon niveau ; la page n'offre alors que le curseur « Gain RF ». false : la réduction de gain se règle à la main (curseur « Gain FI »). Se change ensuite depuis la page. Valeurs : true ou false. (depuis 0.141.0) |
| `audio_port` | expert | `47821` | Port UDP par lequel le module SDR envoie le son démodulé à la passerelle. Il n'écoute qu'en 127.0.0.1 (jamais sur le réseau) et n'accepte que les paquets portant le jeton du module. Valeurs : 1024 à 65535, différent de `[modules] bus_port`. Port déjà pris : waterfall seul (code ORT-6003). Exemple : `47821` (depuis 0.142.0) |
| `fft_size` | expert | `4096` | Nombre de points de la FFT du waterfall : plus il est grand, plus le détail est fin. Valeurs : Puissance de 2 de 512 à 16 384. (depuis 0.140.0) |
| `bins` | expert | `1024` | Nombre de cases d'une ligne envoyée aux clients (chaque case garde le maximum des points qu'elle couvre). Moins de cases = moins de données mobiles. Valeurs : Puissance de 2 de 128 à fft_size. (depuis 0.140.0) |
| `lines_per_s` | expert | `8` | Lignes de waterfall par seconde au premier démarrage ; se règle ensuite depuis la page. Valeurs : 1 à 15. (depuis 0.140.0) |
| `max_cpu_pct` | expert | `150` | Plafond de processeur du module SDR (sdr-core et module ensemble), en pourcentage d'UN cœur. Au-delà pendant 10 s, le module se bride lui-même par crans (waterfall ralenti, puis à 1 ligne/s, puis échantillonnage à 2 MHz) ; un cran est rendu après 5 minutes nettement sous le plafond. La passerelle bride aussi le module quand ELLE souffre, indépendamment de ce réglage. Valeurs : 20 à 800 (150 = un cœur et demi). Exemple : `150` (depuis 0.144.0) |
| `max_mem_mb` | expert | `400` | Plafond de mémoire du module SDR (sdr-core et module ensemble), en Mo. Au-delà pendant 10 s, le module se bride lui-même comme pour `max_cpu_pct`. Valeurs : 50 à 4000. Exemple : `400` (depuis 0.144.0) |

## Spectre HF du poste [spectrum]

Le spectre et le waterfall HF du poste dans la page et l'application, par un second port du poste (Icom) ou par Hamlib.

Se modifie : Assistant (menu 2.1), profils de poste (menu 2.3), ou menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | Spectre et waterfall HF du poste dans la page et l'application. false : pas de spectre HF (un seul port vers le poste). |
| `source` | courant | `"rigctld"` | `civ_port` : second port série du poste réglé en CI-V (Icom, recommandé) ; `rigctld` : flux de Hamlib 4.6+ (déconseillé sous Windows). |
| `data_port` | expert | `4572` | Source rigctld : port UDP local de la diffusion du spectre. |
| `max_fps` | expert | `10` | Cadence maximale du spectre envoyé aux clients (images par seconde). |
| `port` | courant | `""` | Source civ_port : second port série du poste. **Sécurité** : Jamais le port CAT ni le port PTT. Sur l'IC-7300, régler « USB SEND » et « USB Keying » sur OFF pour ce port : sinon il pourrait mettre le poste en émission. Exemple : Windows : `COM7` ; Linux : `/dev/serial/by-id/…-if02-port0`. |
| `civ_address` | courant | `""` | Source civ_port : adresse CI-V du poste, en hexadécimal (revérifiée à chaque ouverture). Exemple : IC-7300MK2 : B6. |
| `baud` | courant | `115200` | Source civ_port : débit du second port (identique au réglage du poste). Valeurs : 9600, 19200, 38400, 57600 ou 115200. |

## SELCALL [selcall]

Squelch numérique par appel de groupe : le son reçu reste coupé jusqu'à l'appel de votre code.

Se modifie : Menu 8.1 ; le code et les options se règlent depuis la page ou l'application. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | Fonction SELCALL disponible sur cette station. |
| `send_on_tx_end` | courant | `false` | Trame SELCALL émise en fin d'émission, à la place du roger bip (seulement si le temps d'émission restant la contient). |
| `manual_repeat` | expert | `3` | Appel manuel : nombre d'émissions de la trame. Valeurs : 1 à 5. |
| `manual_gap_ms` | expert | `500` | Appel manuel : silence entre deux trames, en millisecondes. |
| `filter_mode` | expert | `"attenuate"` | Ce que deviennent les tonalités SELCALL dans le son reçu : `mute` (coupées), `attenuate` (atténuées), `chime` (remplacées par un carillon). |
| `attenuation_db` | expert | `20` | Mode attenuate : atténuation des tonalités, en dB. |
| `audio_delay_ms` | expert | `500` | Retard du son reçu pour que les tonalités soient filtrées avant d'être entendues. Valeurs : 250 à 1000 ms. |
| `tx_level_dbfs` | expert | `-6.0` | Niveau de la trame émise, sous le seuil de l'ALC (réglable automatiquement depuis la page ou l'application). |
| `notify_on_call` | courant | `true` | Alerte ntfy (URL `notify_url` du superviseur), envoyée par la passerelle quand un appel ouvre le squelch, une par minute au plus. Le code SELCALL n'y figure jamais (une rubrique ntfy publique se devine). |
| `history_size` | expert | `10` | Nombre de derniers codes gardés. |

## Cluster DX [cluster]

Les spots des clusters DX, du RBN et des cibistes, affichés sur le spectre et en liste.

Se modifie : Menu 8.1 ; mots de passe des sources : fichier `secrets.toml` (jamais ici). (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `false` | Module Cluster DX (spots des clusters, du RBN et des cibistes). |
| `call` | courant | `""` | VOTRE indicatif radioamateur, seul envoyé aux clusters et au RBN. Vide : le module refuse de démarrer. |
| `cb_call` | expert | `""` | Votre indicatif de cibiste (sources CB) ; aujourd'hui envoyé nulle part. |
| `modes` | courant | `[]` | Modes suivis (CW, SSB, AM, FM, FREEDV) ; vide : tous. Jamais les modes numériques. |
| `bands` | courant | `[]` | Bandes suivies ; vide : toutes. |
| `continents` | expert | `[]` | Continent du SPOTTEUR (celui qui annonce) ; vide : tous. |
| `blacklist` | expert | `[]` | Indicatifs ignorés ; `XX*` désigne un préfixe. |
| `ttl_min` | expert | `15.0` | Durée de vie des spots des clusters et des cibistes, en minutes. |
| `rbn_ttl_min` | expert | `10.0` | Durée de vie des spots du RBN, en minutes. |
| `cty_update` | expert | `true` | Mise à jour hebdomadaire de la liste des pays des indicatifs (cty.dat). |
| `source` | expert | `[]` | Les sources de spots : voir la section suivante. |

## Sources du Cluster DX [[cluster.source]]

Une entrée par source de spots (cluster telnet, RBN, site web).

Se modifie : Menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `name` | expert | `obligatoire` | Nom de la source, affiché dans l'état des flux. |
| `type` | expert | `"telnet"` | `telnet` (cluster DX), `rbn` (Reverse Beacon Network), `web` (site, cibistes). |
| `host` | expert | `""` | telnet, rbn : nom du serveur. |
| `port` | expert | `0` | telnet, rbn : port du serveur. |
| `url` | expert | `""` | web : adresse de la page (https seulement). |
| `call` | expert | `""` | Indicatif propre à cette source ; vide : `[cluster] call`. |
| `secret` | expert | `""` | NOM d'un mot de passe rangé dans `secrets.toml` (jamais le mot de passe lui-même) ; vide : aucun. |
| `priority` | expert | `1` | Clusters telnet : 1 = principal, puis secours dans l'ordre. |
| `enabled` | expert | `true` | false : source ignorée. |

## Superviseur [supervisor]

La seconde couche de sécurité, indépendante de la passerelle : elle surveille l'émission, rigctld et la machine, coupe l'émission en cas de doute et relance ce qui ne répond plus.

Se modifie : Menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `tot_abs_s` | courant | `135` | TOT absolu du superviseur : au-delà, il coupe l'émission lui-même, même si la passerelle ne le fait pas. Coupe aussi une émission faite au micro du poste. **Sécurité** : Doit rester strictement plus grand que `[safety] tot_ceiling_s`. |
| `poll_interval_s` | expert | `1.0` | Cadence de surveillance au repos (plus rapide pendant une émission). |
| `max_reboots_per_hour` | expert | `3` | Redémarrages de la machine permis par heure ; au-delà, mode sûr (réception, accès coupé). |
| `notify_url` | courant | `""` | Adresse de notification ntfy pour les alertes de la station (facultatif). Chaque alerte porte un code stable (par exemple « ORT-5024 TOT absolu dépassé »), la priorité ntfy de ce code, ce qu'il faut faire et le lien vers la page du code (liste des codes d’erreur) ; un code sans alerte par défaut est seulement inscrit au journal. **Sécurité** : Choisissez un sujet difficile à deviner : quiconque le connaît lit vos alertes. Exemple : `https://ntfy.sh/mon-sujet-secret` |
| `notify_lang` | courant | `"fr"` | Langue des alertes ntfy envoyées au téléphone : titre, message et marche à suivre du catalogue d'erreurs. Le journal de la station reste en français ; une valeur mesurée (détail) reste telle que la station l'écrit. Valeurs : `fr` (défaut) ou `en` : les langues du catalogue d'erreurs. Exemple : `en` (depuis 0.165.0) |
| `status_path` | expert | `/run/trx-remote/gateway-status.json` (Linux) ; `C:\ProgramData\trx-remote\run\gateway-status.json` (Windows). | Fichier d'état écrit par la passerelle et lu par le superviseur, trx-monitor et TRX Console. |
| `state_dir` | expert | `/var/lib/trx-remote` (Linux) ; `C:\ProgramData\trx-remote\state` (Windows). | Dossier d'état de la station : mode sûr, mémoires, profils, mesures de TOS, identifiant de station. |
| `service_mode` | expert | `"auto"` | `auto`, `systemd` (Linux : services du système) ou `managed` (le superviseur lance lui-même les processus, Windows). |
| `instance_lock_port` | expert | `47321` | Port local réservé pour garantir qu'un seul superviseur tourne. |
| `stale_after_s` | expert | `2.0` | Passerelle jugée muette si son fichier d'état ne change plus depuis ce délai. |
| `startup_grace_s` | expert | `30.0` | Délai de grâce au démarrage, le temps que la passerelle et rigctld soient prêts. |
| `mismatch_grace_s` | expert | `1.5` | Tolérance avant de juger une émission « inexpliquée » (poste en émission sans client). |
| `rigctld_fail_s` | expert | `5.0` | rigctld injoignable depuis ce délai : il est redémarré. |
| `recovery_wait_s` | expert | `20.0` | Attente entre deux niveaux de l'échelle de reprise (relances, reset USB, mode sûr). |
| `healthy_reset_s` | expert | `120.0` | Durée sans problème avant de repartir du premier niveau de l'échelle de reprise. |
| `temp_alert_c` | expert | `70.0` | Température de la machine au-delà de laquelle une alerte est envoyée (sans autre action). |
| `mem_alert_pct` | expert | `90` | Mémoire utilisée (en %) au-delà de laquelle une alerte `notify_url` est envoyée, si cela dure 60 s ; une alerte par heure au plus. Aucune autre action (ni redémarrage, ni mode sûr). Valeurs : 0 (aucune alerte) ou 50 à 99. (depuis 0.115.0) |
| `disk_alert_pct` | expert | `70` | Disque utilisé (en %) au-delà duquel une alerte est envoyée, mesuré sur le dossier d'état et sur la racine du système ; 60 s de suite, une alerte par heure au plus. Un disque plein empêche d'écrire l'état et les journaux. Valeurs : 0 (aucune alerte) ou 50 à 99. (depuis 0.115.0) |
| `alive_every_h` | courant | `1.0` | Message « Station en service » envoyé par `notify_url` toutes les N heures (priorité minimale) ; 0 : aucun. |
| `allow_local_tx` | courant | `true` | true (« station partagée ») : une émission faite au micro du poste n'est pas coupée à distance (seul le TOT absolu s'applique), et le PTT à distance est bloqué pendant l'émission locale puis 2 minutes. **Sécurité** : false : toute émission non demandée par la station est coupée. Un micro tenu enfoncé résiste alors à la coupure et mène au mode sûr en une minute environ : gardez true si quelqu'un se sert du poste sur place. |
| `local_tx_max_s` | expert | `300` | Station partagée : durée d'émission au micro du poste tolérée quand un opérateur est PRÉSENT, c'est-à-dire quand une action sur le poste (volume, fréquence, mode, sortie du mode DATA, préampli, NR...) a été vue dans les 2 minutes avant la prise ou pendant l'émission. Passé le TOT absolu, simple alerte ; à cette durée, coupure par le superviseur, puis échelle de reprise et mode sûr si l'émission résiste. Sans preuve de présence, le TOT absolu s'applique. Valeurs : 1 à 600 s ; jamais moins que `tot_abs_s` (le plus grand des deux s'applique). **Sécurité** : Un micro coincé juste après une action sur le poste émet jusqu'à cette durée avant d'être coupé. (depuis 0.157.0) |
| `gateway_unit` | expert | `"trx-gateway.service"` | Linux : nom du service systemd de la passerelle. |
| `rigctld_unit` | expert | `"rigctld.service"` | Linux : nom du service systemd de rigctld. |

## Modules [modules]

Programmes complémentaires lancés à côté de la station (Cluster DX…), reliés par un bus local.

Se modifie : Menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `run` | expert | `[]` | Modules à faire tourner ; vide : aucun (pas de bus). Exemple : ["cluster"] |
| `bus_port` | expert | `47810` | Port de l'API interne des modules, en local seulement. |
| `run_as` | expert | `"trx"` | Linux : compte sous lequel tournent les modules (jamais root). |
| `extra_dir` | expert | `""` | Dossier de modules supplémentaires ; vide : modules fournis seulement. |

## Mises à jour [update]

Recherche des nouvelles versions publiées (rien n'est installé sans votre accord).

Se modifie : Menu 8.1 ; installation : menu 7.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `enabled` | courant | `true` | Cherche une nouvelle version au démarrage puis toutes les 24 h ; la console l'annonce, rien n'est installé sans votre accord. |
| `allow_prerelease` | expert | `false` | true : propose aussi les pré-versions (versions d'essai). |

## Outils [tools]

Où trouver Hamlib quand il n'est pas dans le chemin du système.

Se modifie : Assistant (menu 2.1) ou menu 8.1. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `hamlib_dir` | courant | `""` | Dossier d'installation de Hamlib sous Windows (celui qui contient `bin\rigctld.exe`). Vide : Hamlib doit être dans le PATH. Exemple : `C:\Program Files\hamlib-w64-4.7.2` |

## En-tête du fichier

Deux numéros gérés par la station elle-même.

Se modifie : Rien à faire : écrits par la station. (au redémarrage).

| Clé | Niveau | Par défaut | À quoi il sert |
|---|---|---|---|
| `schema_version` | expert | `1` | Version du format du fichier. La station la met à jour elle-même lors d'une migration. |
| `config_revision` | expert | `1` | Compteur incrémenté à chaque enregistrement par TRX Console : permet de savoir quelle version du fichier est en service. |
