# Migration du relais et du VPS (France) avant l'ouverture au public

Cahier des charges v2 (étape 340, 2026-11-21 ; v1 à l'étape 339). Aucun code. Préalable à l'ouverture du service au
public.

## 1. Objet

Deux déménagements, faits ensemble tant que le service n'a que **deux utilisateurs** (l'utilisateur et un
bêta-testeur) :

1. Le **relais** de la présence de groupe et du monitoring entre stations (dépôt privé `openRemoteTRX-relay`) quitte
   l'hébergement **mutualisé OVH** du site WordPress (`https://rf-diy.com/orx-relay/public`, tables dans la base
   MySQL de WordPress) pour un VPS.
2. Le **VPS** de la diffusion en direct (`openRemoteTRX-vps`, aujourd'hui au Canada) est **remplacé par un VPS en
   France**, qui portera la diffusion ET le relais.

### 1.1 Décisions de l'utilisateur (2026-11-21)

1. **Pas de transition pour des utilisateurs existants** : les deux stations sont reconfigurées à la main
   (`station.toml` par le menu 8.1, groupe recréé, monitoring ré-appairé). Le relais repart d'une **base vide** ;
   ni copie de base, ni relais de transition, ni compatibilité avec l'ancienne adresse.
2. **VPS en France** (OVH, centre de données français) : données des opérateurs européens hébergées dans l'Union
   européenne, faible latence ; fait MAINTENANT, tant qu'un déménagement ne coûte rien.
3. Sauvegardes : la sauvegarde automatique du VPS proposée par OVH est la base (§ 6).

### 1.2 Ce qui reste sur le WordPress

Le site, les iframes des pages publiques (GitHub Pages), le plugin de l'analyseur des rapports (aucune donnée
d'utilisateur). Le plugin back-office `orx-presence-admin`, qui lisait les tables du relais, est **retiré** ; son
rôle passe à l'application d'administration (cahier à venir, décisions du 2026-11-21 : pseudos seulement pour les
groupes de la station du propriétaire, chiffres pour le reste, statistiques sur 365 jours).

## 2. Pourquoi

| Constat | Conséquence |
|---|---|
| Mutualisé sans CRON | Purges faites « au passage » des requêtes ; aucune sauvegarde ni statistique planifiée |
| Route IPv6 de rf-diy.com qui perd ~40 % des connexions (piège de l'étape 208) | Coupures hors de notre portée |
| Base partagée avec WordPress | Une extension WordPress peut toucher le relais ; sauvegarde mêlée au site |
| Journaux d'accès tenus par OVH | Conservation des adresses IP non maîtrisée (promesse « aucune IP » de la présence, § 13) |
| VPS au Canada | Données d'opérateurs européens hors de l'Union (admis par décision d'adéquation, mais plus simple en France) ; ~90 ms de plus pour la diffusion |
| Après l'ouverture au public, chaque changement d'adresse touche toutes les stations | D'où un NOM DÉDIÉ par service (§ 3) : les déménagements suivants ne seront qu'un changement de DNS |

## 3. Noms

| Service | Nom | Remarque |
|---|---|---|
| Relais | **`relay.rf-diy.com`**, à la racine (`base_path` vide) | Nouveau défaut de `[presence] relay_url` et `[monitor_link] relay_url` : `https://relay.rf-diy.com` |
| Diffusion | `server-23.rf-diy.com` **gardé** | Pointé sur le nouveau VPS : `[diffusion] server` des stations inchangé |

Les deux noms pointent sur la même machine ; un service qui grossit (diffusion : bande passante d'Icecast) part sur
une autre machine par un simple changement de DNS.

## 4. Nouveau VPS (lot V1)

- Commande par l'utilisateur : VPS OVH en **France** (Gravelines, Roubaix ou Strasbourg), Debian 13, au moins le
  gabarit actuel (2 cœurs, 4 Go, 40 Go), **option de sauvegarde automatique** souscrite (§ 6).
- **Tout par `deployer.sh`** : le durcissement fait à la main le 2026-11-17 sur le VPS du Canada (SSH par clé
  seulement, root interdit, `AllowUsers`, nftables, fail2ban, mises à jour automatiques, nom de la machine) est
  vérifié dans `deploy.sh` et ajouté s'il manque. Critère : une machine NEUVE devient un serveur complet par
  `bash deployer.sh debian@<adresse>` et la seule pose de la clé SSH. La migration sert d'essai de reconstruction
  (durée relevée dans le README du dépôt VPS).
- **Diffusion** : secrets de `/etc/orx-vps` (mots de passe source, `META_KEY`, identifiants des auditeurs,
  `auditeurs.json`, secret des cookies) copiés de l'ancien VPS vers le nouveau par l'utilisateur (scp, jamais dans un
  dépôt) : `diffusion.key` des stations reste valable. Puis DNS de `server-23.rf-diy.com` (A et AAAA) vers le
  nouveau VPS, TTL abaissé la veille ; Caddy obtient son certificat, stunnel le recopie.
- Essais : `tools/essai_meta.py` (18 vérifications), `tools/essai_flux.py`, une diffusion réelle depuis minix-bzh
  écoutée sur la page des auditeurs.
- L'ancien VPS du Canada reste allumé jusqu'à la fin du lot V4, puis est **résilié** par l'utilisateur.

## 5. Relais sur le VPS (lot V2)

### 5.1 Logiciels (paquets Debian seulement)

- PHP 8.4 en PHP-FPM (`php-fpm`, `php-sqlite3` ; sodium vérifié au déploiement), compte à part, `open_basedir`
  limité au dossier du relais, fonctions d'exécution interdites.
- Caddy : bloc `relay.rf-diy.com` à part, `php_fastcgi` sur `public/` seulement, corps limité à 72 ko (limite du
  monitoring), 404 pour tout le reste, mêmes en-têtes de sécurité que la diffusion.
- Code : `deployer.sh` copie le relais depuis le dossier voisin `openRemoteTRX-relay` **à un commit donné** (noté
  dans le déploiement) ; jamais une copie modifiée sur le serveur. `config.php` fabriqué au premier déploiement
  dans `/etc/orx-vps/relais.php` (secret tiré au hasard), jamais dans un dépôt.

### 5.2 Base

**SQLite en mode WAL** (`/var/lib/orx-relay/relais.sqlite`), déjà pris en charge par le relais (tests) : aucun
service de plus, sauvegarde = un fichier. À ajouter au relais : `journal_mode=WAL` et `busy_timeout` à l'ouverture.
MariaDB seulement si l'essai de charge (§ 7) montrait des attentes d'écriture.

### 5.3 Tâches planifiées (timers systemd)

- Purges : stations sans requête depuis 12 mois, messages du monitoring non relevés de plus de 7 jours, demandes
  d'adhésion de plus de 7 jours (les purges « au passage » restent).
- Copie cohérente de la base chaque nuit (§ 6).
- Plus tard : compteurs des statistiques (application d'administration).

### 5.4 Journaux et adresses IP

Journal d'accès de Caddy du relais aux adresses **masquées** (`ip_mask` : /16 en IPv4, /32 en IPv6), gardé 7 jours.
Toujours aucune adresse IP en base ; limites de débit dans `var/rate/` sous un nom HMAC qui change chaque jour.

### 5.5 Surveillance

Alertes **ntfy** du VPS vers le sujet de l'utilisateur : relais qui ne répond plus (contrôle local chaque minute :
`POST /v1/sync` sans signature = 401 attendu), disque > 80 %, mémoire, Caddy / PHP-FPM / Icecast / stunnel arrêtés,
certificat non renouvelé, copie de la base manquée ; battement quotidien sans sonnerie. Un contrôle depuis
l'extérieur (une station de l'utilisateur) signale la panne totale du VPS, que celui-ci ne peut pas annoncer.

## 6. Sauvegardes

Question de l'utilisateur : la sauvegarde complète du VPS par OVH suffit-elle ?

**Pour maintenant, oui**, avec un complément qui ne coûte rien :

- La sauvegarde automatique d'OVH (quotidienne, à souscrire sur le NOUVEAU VPS) protège contre la perte du disque
  ou une erreur de manipulation. Les données du relais sont de toute façon recréables en quelques minutes tant que
  le service n'a que deux utilisateurs.
- **Complément** : chaque nuit, `sqlite3 .backup` écrit une copie COHÉRENTE de la base dans `/var/backups/orx-relay/`
  (7 copies gardées). Elle entre dans la sauvegarde d'OVH et permet de restaurer **la base seule**, sans remettre
  tout le VPS à une date antérieure (ce que fait une restauration OVH, diffusion comprise).
- À relever dans l'espace client au lot V1 : lieu de stockage de la sauvegarde OVH (autre centre de données ?),
  durée de conservation, restauration du VPS entier seulement ou fichier par fichier.

**Avant l'ouverture au public**, une sauvegarde hors du VPS devient nécessaire (D4), car celle d'OVH laisse trois
risques : même fournisseur et même compte (compte compromis ou incident majeur d'un centre de données : incendie
de Strasbourg en 2021), restauration du VPS entier seulement, et pas d'essai de restauration de la base. Proposition
pour ce moment-là : copie de nuit chiffrée par clé publique (`age`, paquet Debian ; le VPS ne peut pas relire ses
sauvegardes), récupérée par une machine de l'utilisateur, 30 quotidiennes et 12 mensuelles, essai de restauration
tous les 6 mois. Le contenu est illisible pour le relais (états chiffrés, clés scellées), mais contient des
identifiants et pseudos de stations : données personnelles, d'où le chiffrement.

## 7. Capacité

Rythme constant de 90 s par station, états de taille fixe : 1 000 stations ≈ 11 requêtes/s et quelques Mo de base ;
monitoring : 5 Mo par boîte au plus. La marge est large mais se **mesure** au lot V2 : outil de charge (N stations
simulées, Icecast en marche), temps de réponse, processeur, attentes d'écriture SQLite.

## 8. Station (lot V3, étape normale)

- Nouveau défaut `relay_url` = `https://relay.rf-diy.com` (`[presence]`, `[monitor_link]`), notice de
  station.toml (`depuis`), guide de l'opérateur, README du relais.
- **Monitoring : ré-enregistrement automatique.** Aujourd'hui, face à un relais qui ne connaît pas la station
  (`unknown_station` : relais remis à zéro, station purgée après 12 mois), le module « monlink » se croit toujours
  enregistré et échoue en boucle ; la présence, elle, se ré-enregistre déjà. Même traitement pour le monitoring,
  avec un test.
- Vérifier (et corriger si besoin) le comportement d'une station qui garde un groupe ou une liaison que le relais ne
  connaît pas (`unknown_group`, `unknown_link`) : message clair dans le menu 5.3 / 6.5, la page et l'application,
  et « Quitter » toujours possible.
- Aucune compatibilité avec l'ancienne adresse (décision 1).

## 9. Bascule (lot V4, par les deux utilisateurs)

Sur chaque station, dans cet ordre :
1. Menu 5.3 : quitter (ou supprimer) les groupes ; menu 6.5 : terminer les liaisons de monitoring.
2. Installer la version du lot V3, ou à défaut, menu 8.1 : `relay_url = "https://relay.rf-diy.com"` dans
   `[presence]` ET `[monitor_link]` (une station.toml existante garde l'ancienne valeur même après mise à jour :
   l'édition est nécessaire dans les deux cas), puis redémarrer la station.
3. Recréer le groupe (menu 5.3), inviter l'autre station, ré-appairer le monitoring (menu 6.5, code dicté).
4. Contrôle : chacun voit l'autre dans « Amis » (page, application), le monitoring reçoit les dernières nouvelles.

## 10. Fermeture de l'ancien (lot V5)

- Relais du mutualisé : fichiers `/www/orx-relay/` supprimés par FTP, tables `orx_*` et `orx_mon_*` effacées de la
  base WordPress (phpMyAdmin d'OVH), plugin `orx-presence-admin` désactivé et supprimé.
- VPS du Canada résilié (après la diffusion et le relais vérifiés sur le nouveau).
- Notes à jour : README des dépôts relay et vps, mémoire de Claude (`vps-ovh`), CLAUDE.md.

## 11. RGPD

Politique de confidentialité de rf-diy.com à mettre à jour par l'utilisateur : hébergement OVH en France pour la
présence, le monitoring et la diffusion ; journaux 7 jours aux adresses masquées ; stations inactives effacées
après 12 mois ; sauvegardes (durée de celle d'OVH, plus la copie hors VPS quand elle existera). Aucune donnée
nouvelle collectée.

## 12. Lots et décisions

| Lot | Contenu | Qui |
|---|---|---|
| V1 | Nouveau VPS en France par `deployer.sh` (durcissement compris), diffusion déplacée, DNS `server-23` | Utilisateur (commande, option de sauvegarde, copie des secrets) + Claude (dépôt vps) |
| V2 | Relais sur le VPS : PHP-FPM, Caddy, SQLite WAL, timers, copie de la base, journaux masqués, alertes ntfy, essai de charge, essais de bout en bout ; DNS `relay.rf-diy.com` | Claude (dépôts vps et relay) |
| V3 | Version de la station : nouveau défaut, ré-enregistrement du monitoring, groupes et liaisons inconnus | Claude (étape normale) |
| V4 | Bascule des deux stations (§ 9) | Les deux utilisateurs |
| V5 | Fermeture du mutualisé et du VPS du Canada | Utilisateur |

Ouverture au public : après V5, deux semaines sans incident ET la sauvegarde hors du VPS en place (D4).

| N° | Question | État |
|---|---|---|
| D1 | Nom du relais | `relay.rf-diy.com` à la racine (retenu) |
| D2 | Base | SQLite WAL (retenu sauf résultat contraire de l'essai de charge) |
| D3 | Emplacement | France (décision de l'utilisateur, 2026-11-21) |
| D4 | Sauvegardes | Sauvegarde OVH + copie cohérente de nuit (maintenant) ; copie chiffrée hors du VPS avant l'ouverture au public (à décider à ce moment) |
| D5 | Plugin back-office | Retiré (V5) |
