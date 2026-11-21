# Migration du relais (présence et monitoring) vers le VPS

Cahier des charges v1 (étape 339, 2026-11-21). Aucun code. Préalable à l'ouverture du service au public.

## 1. Objet

Le relais de la présence de groupe et du monitoring entre stations (dépôt privé `openRemoteTRX-relay`) tourne depuis
le 2026-11-11 sur l'hébergement **mutualisé OVH** du site WordPress, dans un sous-dossier
(`https://rf-diy.com/orx-relay/public`), avec ses tables dans la base MySQL de WordPress. C'était suffisant pour la
preuve de concept, pas pour un service ouvert au public. Ce cahier décrit son déménagement vers le VPS
(`openRemoteTRX-vps`, qui sert déjà la diffusion en direct) **sans perdre un groupe, une liste de membres ni une
liaison de monitoring, et sans demander quoi que ce soit aux opérateurs**.

### 1.1 Ce qui déménage

| Élément | Aujourd'hui | Après |
|---|---|---|
| Code du relais (`public/`, `src/`) | FTP dans `/www/orx-relay/` | Déployé par `openRemoteTRX-vps` (PHP-FPM derrière Caddy) |
| Tables `orx_*` (présence) et `orx_mon_*` (monitoring) | MySQL de WordPress | Base propre au relais sur le VPS (§ 4.3) |
| `config.php` (`secret`, base) | FTP | `/etc/orx-vps/relais.php`, fabriqué au premier déploiement |
| `var/rate/` (limites de débit, 2 h de vie) | Hébergement | Recréé vide : rien à copier |

### 1.2 Ce qui reste sur le WordPress

Le site lui-même, les iframes des pages publiques (GitHub Pages), le plugin de l'analyseur des rapports (outil
statique, aucune donnée d'utilisateur). Le plugin back-office `orx-presence-admin` lit les tables du relais
directement : il ne fonctionnera plus et sera **retiré** (§ 9, D6) ; son rôle passe à l'application
d'administration (cahier à venir).

### 1.3 Hors du périmètre

API d'administration et statistiques sur 365 jours (cahier de l'application d'administration, décisions du
2026-11-21) : ce cahier prépare seulement ce dont elles auront besoin (tâches planifiées, base à nous).

## 2. Pourquoi déménager

| Constat sur le mutualisé | Conséquence |
|---|---|
| Pas de CRON | Purges faites « au passage » des requêtes (stations inactives 12 mois, messages de 7 jours) ; aucune sauvegarde ni statistique planifiée possible |
| Route IPv6 de rf-diy.com qui perd ~40 % des connexions (piège de l'étape 208) | Coupures hors de notre portée ; contournées côté station, pas corrigées |
| Base partagée avec WordPress | Une mise à jour ou une extension WordPress peut toucher le relais ; sauvegarde mêlée au site |
| Journaux d'accès tenus par OVH | Durée de conservation des adresses IP non maîtrisée (promesse « aucune IP » du § 13 de la présence) |
| Limites PHP et quotas imposés | Rythme constant de 90 s par station : la charge croît avec chaque station, sans marge connue |

Le VPS (Debian 13, 2 cœurs, 3,8 Go, IPv4 et IPv6 vérifiées 20/20 le 2026-11-17) est déjà durci (SSH par clé,
nftables, fail2ban, mises à jour automatiques) et déployé de façon reproductible (`bash deployer.sh`).

## 3. Contraintes relevées dans le code (2026-11-21)

1. **`relay_url` est écrite dans chaque `station.toml`** (`config.py`, écriture de `[presence]` et
   `[monitor_link]`) : un nouveau défaut ne s'applique pas aux stations existantes (piège Debian « station.toml
   existante garde ses valeurs »).
2. **Les requêtes signent le chemin complet** (`"orx-relay v1\n" || "POST\n" || chemin || "\n" || corps`,
   `wire.base_prefix`) : un relais qui ne sert pas le même chemin refuse la signature (`bad_signature`). Une
   redirection HTTP ne sauve rien (un client POST ne la suit pas, et le chemin changerait).
3. **Les invitations portent l'adresse du relais** et `Engine.join` refuse une invitation « pour un autre relais »
   (`other_relay`) : toute invitation envoyée avant la bascule serait refusée par une station déjà basculée.
4. Les groupes, listes signées, clés scellées, états chiffrés et **derniers compteurs anti-rejeu** sont en base :
   copiés tels quels, les stations ne voient aucune différence ; perdus, tous les groupes sont à recréer.
5. L'application Android et la page ne connaissent PAS l'adresse du relais (seul le module de la station lui parle).
6. Le relais applique des limites **par adresse IP** (`ip_per_minute`, `register_per_hour`, `take_per_minute`) :
   tout relais de transition qui ferait passer les anciennes stations par une seule adresse doit transmettre la
   vraie, de façon authentifiée (§ 5.3).

## 4. Cible

### 4.1 Adresse

- Nom dédié **`relay.rf-diy.com`** (A et AAAA vers le VPS), distinct de `server-23.rf-diy.com` (diffusion) : le
  jour où le relais ou la diffusion part sur une autre machine, seul le DNS change.
- **Même chemin qu'aujourd'hui** : `https://relay.rf-diy.com/orx-relay/public` (`base_path` = `/orx-relay/public`).
  C'est ce qui permet au relais de transition (§ 5.3) de faire suivre une requête signée sans la casser. Le
  chemin est un peu long, mais il ne se voit que dans `station.toml`.

### 4.2 Logiciels (paquets Debian seulement, comme le reste du VPS)

- PHP 8.4 en PHP-FPM (`php-fpm`, `php-sqlite3` ou `php-mysql`, sodium vérifié au déploiement), compte à part,
  `open_basedir` sur le dossier du relais, aucune fonction d'exécution.
- Caddy : un bloc `relay.rf-diy.com` à part, `php_fastcgi` sur `public/` seulement, corps limité à 72 ko (limite
  du monitoring), 404 pour tout le reste ; en-têtes de sécurité comme la diffusion.
- Code : le dépôt `openRemoteTRX-relay` reste la source ; `deployer.sh` de `openRemoteTRX-vps` le copie depuis le
  dossier voisin **à un commit donné** (noté dans le déploiement), jamais une copie modifiée sur le serveur.

### 4.3 Base

Recommandation : **SQLite en mode WAL**, fichier dans `/var/lib/orx-relay/`, déjà pris en charge par le relais
(tests). Raisons : aucun service de plus sur une petite machine, sauvegarde = un fichier (`.backup`), charge
attendue modeste (§ 8). À faire dans le relais : `busy_timeout` et `journal_mode=WAL` à l'ouverture, et un essai
de charge à plusieurs processus PHP-FPM.

Variante : MariaDB, qui reprend un `mysqldump` tel quel mais ajoute un service (~100 Mo de mémoire) et ses mises à
jour. Choix de l'utilisateur (D2).

La copie MySQL -> SQLite se fait par un script du relais (`tools/copier_base.php`) : lecture table par table par
PDO, écriture dans une transaction, puis contrôle **nombre de lignes et empreinte SHA-256 du contenu trié de
chaque table** des deux côtés. Toute différence = bascule abandonnée (§ 5.2).

### 4.4 Tâches planifiées (timers systemd)

- Purge : stations sans requête depuis 12 mois, messages du monitoring non relevés de plus de 7 jours, demandes
  d'adhésion de plus de 7 jours (aujourd'hui faites « au passage » : gardées aussi).
- Sauvegarde quotidienne (§ 6).
- Plus tard : compteurs des statistiques (cahier de l'application d'administration).

### 4.5 Journaux et adresses IP

- Journal d'accès de Caddy du relais : adresses **masquées** (`ip_mask` : /16 en IPv4, /32 en IPv6), 7 jours, puis
  effacé. Il sert au diagnostic, jamais à suivre une station.
- Aucune IP en base (inchangé) ; limites de débit dans `var/rate/` sous un nom HMAC qui change chaque jour
  (inchangé).

## 5. Bascule sans coupure visible

### 5.1 Station (une version, avant la bascule)

- Nouveau défaut `relay_url` = `https://relay.rf-diy.com/orx-relay/public` (`[presence]` et `[monitor_link]`).
- **Ancienne adresse reconnue** : à la lecture de `station.toml`, `https://rf-diy.com/orx-relay/public` (exactement
  l'ancien défaut) est remplacée par la nouvelle, en mémoire, et réécrite dans le fichier par la prochaine
  écriture de la console (menus 5.3, 6.5, 8.1) ou par l'installation d'une mise à jour. Une adresse **choisie par
  l'opérateur** (autre relais) n'est jamais touchée.
- **Invitations** : `Engine.join` accepte une invitation portant l'ancienne OU la nouvelle adresse (liste fermée
  `RELAY_ALIASES`) ; les nouvelles invitations portent la nouvelle.
- Tests : réécriture du seul ancien défaut, adresse personnelle gardée, invitation ancienne acceptée, invitation
  d'un relais inconnu toujours refusée, notice de station.toml (`relay_url`, `depuis`).
- **Ordre imposé** : cette version ne sort qu'APRÈS la bascule (§ 5.2, lot M3). Avant, la nouvelle adresse ne
  sert rien, et une station qui l'utiliserait écrirait dans une base que la copie écraserait. Grâce au relais de
  transition (§ 5.3), les stations qui ne se mettent pas à jour continuent de fonctionner.

### 5.2 Jour de la bascule (fenêtre annoncée, ~15 min)

1. Relais OVH mis **en pause** (`pause` = 600 dans `config.php`) : les stations reçoivent la pause et réessaient
   plus tard, sans erreur ni alerte ; aucune écriture pendant la copie.
2. Copie de la base (§ 4.3) vers le VPS, contrôle des comptes et empreintes.
3. Essais de bout en bout contre le VPS (`tests/e2e_station.py`, `e2e_monlink.py` avec des stations jetables,
   effacées ensuite) et relecture d'un groupe réel par minix-bzh (pointée à la main sur la nouvelle adresse).
4. Le code du relais OVH est remplacé par le **relais de transition** (§ 5.3), pause levée.
5. Contrôle : minix-bzh (ancienne adresse) et une station sur la nouvelle voient le même groupe et les mêmes états.

Retour arrière : jusqu'à la fin du point 4, remettre l'ancien code et lever la pause (rien n'a été écrit sur le
VPS). Après : copie inverse VPS -> OVH par le même script, même contrôle.

### 5.3 Relais de transition sur OVH

Un seul fichier PHP à la place de `public/index.php`, sans base :
- fait suivre **tel quel** chaque requête `POST /orx-relay/public/v1/…` (corps et en-têtes `X-Orx-*` octet pour
  octet) à `https://relay.rf-diy.com` **sur le même chemin** : la signature reste valable ; renvoie la réponse et
  son code tels quels ; délai 10 s, réponse `{"error":"upstream"}` (503) sinon (la station réessaie comme pour
  une panne du relais) ;
- ajoute l'adresse réelle de la station dans `X-Orx-Client-IP` et un en-tête `X-Orx-Forward` = HMAC(secret de
  transition, date | adresse | empreinte du corps) : le VPS ne prend cette adresse **que** si le HMAC est bon,
  sinon il prend l'adresse vue ; le secret n'est connu que des deux serveurs ;
- `GET /orx-relay/public/i…` (page d'une invitation) : redirection 301 vers la même page sur le VPS ;
- compte les requêtes par jour (un nombre, aucune adresse) pour savoir quand plus personne ne passe par là.

Faisabilité à prouver AVANT tout (lot M0) : appel HTTPS sortant depuis le mutualisé (curl de PHP ; les mises à
jour de WordPress montrent que c'est permis), en IPv4 forcé, délai ajouté mesuré.

### 5.4 Fin de la transition

- Durée : **6 mois**, ou plus tôt si le compteur reste à zéro 30 jours de suite (D5).
- Puis le relais de transition répond 410 avec `{"error":"moved","relay":"https://relay.rf-diy.com/orx-relay/public"}` ;
  une station à jour sait déjà lire `moved` (ajouté au lot M3 : message ORT dans le journal et le menu 5.3,
  « mettre à jour la station ») ; une station plus ancienne journalise une erreur du relais, comme aujourd'hui.
- Tables `orx_*` effacées de la base WordPress après une dernière sauvegarde gardée 30 jours.

## 6. Sauvegardes

- Quotidienne : `sqlite3 .backup` (ou `mysqldump`), compressée, **chiffrée par une clé publique** (`age`, paquet
  Debian) : le VPS ne peut pas relire ses propres sauvegardes ; clé privée chez l'utilisateur seulement.
- Hors du VPS : récupérées chaque jour par une machine de l'utilisateur (tirage par SSH, compte de sauvegarde
  limité à ce dossier) ou envoyées vers un stockage objet (D4). 30 sauvegardes quotidiennes et 12 mensuelles.
- Le contenu est déjà illisible pour le relais (états chiffrés, clés scellées), mais contient des identifiants et
  pseudos de stations : données personnelles, d'où le chiffrement.
- **Essai de restauration** écrit et fait au lot M1 (VPS de secours ou machine locale), puis tous les 6 mois.
- Reconstruction complète d'un VPS : `deployer.sh` sur une machine neuve + dernière sauvegarde + DNS : procédure
  écrite dans le README du dépôt VPS, durée mesurée.

## 7. Surveillance

- Alertes **ntfy** du VPS vers le sujet de l'utilisateur (même outil que les stations) : relais qui ne répond plus
  (contrôle local toutes les minutes : `POST /v1/sync` sans signature = 401 attendu), disque > 80 %, mémoire,
  sauvegarde manquée, certificat non renouvelé, service PHP-FPM ou Caddy arrêté ; battement quotidien sans
  sonnerie.
- Contrôle depuis l'extérieur (une station de l'utilisateur, ou un service gratuit de surveillance) : le VPS ne
  peut pas signaler sa propre panne totale.
- Les stations journalisent déjà un relais injoignable : rien à ajouter côté station.

## 8. Capacité

- Rythme constant de 90 s par station, états de taille fixe : 1 000 stations ≈ 11 requêtes/s, quelques Mo de base.
  PHP-FPM sur 2 cœurs : quelques centaines de requêtes/s. La marge est large, mais elle se **mesure** au lot M1
  (outil de charge : N stations simulées contre le VPS, temps de réponse et processeur relevés, Icecast en marche).
- Monitoring : 5 Mo par boîte au plus, 20 liaisons par station : quelques centaines de Mo au pire, 40 Go de disque.
- La diffusion (bande passante d'Icecast) et le relais partagent la machine : si la diffusion grossit, elle part
  sur un second VPS (nom `server-23` déjà distinct) ; rien à décider maintenant.

## 9. RGPD

- Mettre à jour la politique de confidentialité de rf-diy.com : nouvel hébergement (OVH, centre de données du VPS),
  durées (journaux 7 jours, IP masquées ; sauvegardes 30 jours / 12 mois ; stations inactives 12 mois).
- Le VPS actuel est **au Canada** (décision d'adéquation de l'Union européenne pour le Canada). C'est admis, mais
  pour un service ouvert à des opérateurs européens, un VPS en France (OVH Roubaix / Gravelines) est le plus simple
  à expliquer (D3).
- Aucune donnée nouvelle collectée par la migration.

## 10. Lots

| Lot | Contenu | Dépôt(s) |
|---|---|---|
| M0 | Faisabilité : appel sortant depuis OVH (relais de transition minimal), DNS `relay.rf-diy.com`, choix D1 à D4 | relay, vps |
| M1 | VPS prêt : PHP-FPM, bloc Caddy, base vide, timers, sauvegardes chiffrées et restauration essayée, alertes ntfy, essai de charge ; relais : WAL / `busy_timeout`, `X-Orx-Forward`, script de copie | vps, relay |
| M2 | Bascule (§ 5.2) avec le relais de transition ; minix-bzh vérifiée sur l'ancienne et la nouvelle adresse | relay, vps |
| M3 | Version de la station : nouveau défaut, ancienne adresse reconnue, invitations anciennes acceptées, lecture de `moved` ; notice station.toml, guide, historique | openRemoteTRX (étape normale) |
| M4 | Fin de transition (§ 5.4), retrait du plugin back-office, tables effacées de WordPress | relay, WordPress |

Ouverture au public : après M3 publiée et **deux semaines sans incident** sur le VPS.

## 11. Décisions à prendre

| N° | Question | Recommandation |
|---|---|---|
| D1 | Nom du relais | `relay.rf-diy.com`, chemin `/orx-relay/public` gardé |
| D2 | Base | SQLite WAL (MariaDB si l'utilisateur préfère reprendre un `mysqldump` tel quel) |
| D3 | Emplacement | Garder le VPS du Canada pour M0 à M2 ; avant l'ouverture au public, décider d'un VPS en France ou non |
| D4 | Destination des sauvegardes | Tirage quotidien par une machine de l'utilisateur, chiffrées `age` |
| D5 | Durée du relais de transition | 6 mois, ou 30 jours sans aucune requête |
| D6 | Plugin back-office `orx-presence-admin` | Retiré à M4, remplacé par l'application d'administration |
| D7 | Fenêtre de bascule | Annoncée aux bêta-testeurs, ~15 min, un soir de semaine |
