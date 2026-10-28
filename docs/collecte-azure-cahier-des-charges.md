# Cahier des charges : service de collecte des rapports (rf-diy, Azure)

Version 1 du 2026-10-28. Document de départ du futur dépôt du service, à y copier tel quel (`docs/cahier-des-charges.md`).
Le côté station (TRX distant, dépôt `openRemoteTRX`) n'est décrit ici que pour ce qu'il doit envoyer.

## 1. Contexte

TRX distant (openRemoteTRX) pilote un poste radioamateur à distance. Aujourd'hui, un utilisateur qui rencontre un
problème produit :

- un **rapport de la page** (« Signaler un problème ») : texte assemblé par la page, relu par l'utilisateur avant envoi,
  rangé sur la station dans `<state_dir>/reports/` ;
- un **rapport de dépannage** (TRX Console, menu 8) : zip sur le Bureau (diagnostic, journaux, configuration sans
  mot de passe, `station-id.txt`).

Il les transmet ensuite à la main (e-mail, partage). Le service décrit ici reçoit ces rapports directement, pour
rf-diy.com, sur le tenant Azure du projet.

Chaque station a un identifiant unique et stable : `station-id`, un UUID version 4 créé une fois par la passerelle
(étape 41, voir `trxstation/station_id.py`).

## 2. Objectifs

1. Recevoir les rapports envoyés **volontairement** par les stations, sans compte ni mot de passe pour l'utilisateur.
2. Les ranger de façon consultable par le mainteneur (par station, version, date).
3. Coût quasi nul au volume attendu (quelques dizaines à quelques centaines de rapports par mois), plafonné par une alerte de budget.
4. Résister aux abus : spam, gros fichiers, rafales, faux identifiants.
5. Respecter le RGPD : minimisation, durée de conservation limitée, suppression sur demande.
6. Rester ouvert à d'autres services plus tard (statistiques de versions, liste des postes qualifiés, annonces de mise à jour) sous le même identifiant de station.

Hors périmètre de la version 1 : interface web publique, comptes utilisateurs, réponse automatique à l'utilisateur,
analyse automatique des journaux.

## 3. Principes non négociables

- **Rien ne part sans action de l'utilisateur.** La station n'envoie jamais rien d'elle-même : ni au démarrage, ni en
  tâche de fond, ni « télémétrie ». Chaque envoi est montré puis confirmé.
- **Aucun secret dans les rapports.** La station retire déjà mots de passe, empreintes, clés et jetons ntfy ; le
  service vérifie quand même et refuse un rapport qui en contient visiblement (motifs `password_hash`, `scrypt$`,
  `BEGIN PRIVATE KEY`...).
- **L'identifiant de station n'est pas une preuve d'identité.** N'importe qui peut en inventer un ; il sert à regrouper,
  jamais à autoriser quoi que ce soit d'important.
- **Le service ne peut rien commander à une station.** Aucune réponse du service ne déclenche d'action sur la radio.
- Logiciel libre : même licence que le projet (AGPL-3.0-or-later), en-têtes SPDX comme dans openRemoteTRX.

## 4. Acteurs

| Acteur | Rôle |
|---|---|
| Station TRX distant | Envoie un rapport quand l'utilisateur le décide (TRX Console ou page) |
| Utilisateur radioamateur | Relit et confirme l'envoi ; peut demander la suppression de ses rapports |
| Mainteneur rf-diy | Consulte les rapports, les supprime, suit les coûts |
| Azure | Héberge le service (Functions, Storage) |

## 5. Exigences fonctionnelles

### F1. Enregistrement d'une station (premier envoi)

- `POST /api/v1/stations` avec `{"station_id": "<uuid4>", "version": "0.44.0"}`.
- Le service crée (ou retrouve) la station et renvoie un **jeton d'envoi** aléatoire (32 octets, base64url), une seule fois.
- La station le garde dans `<state_dir>/collecte.token` (0600, propriétaire : compte de la station).
- Pourquoi : limiter les abus par station et empêcher qu'un tiers envoie des rapports au nom d'un `station_id` déjà
  enregistré. Ce n'est pas une authentification forte.
- Un `station_id` déjà enregistré ne reçoit pas de nouveau jeton par cette route. Perte du jeton (réinstallation) :
  la station régénère un `station_id` (suppression du fichier `station-id`) ; l'ancien expire avec ses rapports.
- Limites : 5 enregistrements par adresse IP et par jour.

### F2. Envoi d'un rapport

- `POST /api/v1/reports`, en-têtes `Authorization: Bearer <jeton>` et `X-Station-Id: <uuid4>`.
- Corps `multipart/form-data` :
  - `meta` (JSON, obligatoire) : `kind` (`page` | `troubleshooting`), `version`, `os` (`debian`, `windows`, `raspberry`),
    `rig_model` (numéro Hamlib, facultatif), `created_at` (ISO 8601), `consent` (`true`, obligatoire) ;
  - `file` : texte UTF-8 (`kind = page`, 256 Kio au plus) ou zip (`kind = troubleshooting`, 5 Mio au plus).
- Contrôles : taille, type réel (signature zip, UTF-8 valide), zip sans chemin absolu ni `..`, au plus 200 entrées,
  décompressé au plus 50 Mio (bombe de compression), motifs de secrets (refus `422 secret_detected`).
- Réponse `201` avec `{"report_id": "R-AAAAMMJJ-xxxxxx"}` : la station l'affiche, l'utilisateur peut le citer.
- Limites : 10 rapports par station et par jour, 30 par adresse IP et par jour ; au-delà `429` avec `Retry-After`.

### F3. Suppression à la demande (RGPD)

- `DELETE /api/v1/stations/{station_id}` avec le jeton : supprime la station et tous ses rapports, réponse `204`.
- TRX Console proposera ce choix (menu « Données envoyées à rf-diy »).
- Demande par e-mail sans jeton : le mainteneur supprime à la main (procédure décrite dans le dépôt).

### F4. Consultation (mainteneur)

- Version 1 : Azure Storage Explorer ou le portail, avec l'index en table (voir 7.2). Pas de page publique.
- Version 2 (plus tard) : petite page d'administration protégée par Entra ID (compte du tenant), liste et filtres
  (version, poste, date), téléchargement, suppression.

### F5. Notification du mainteneur

- Un message par nouveau rapport (ntfy ou e-mail), avec `report_id`, version, type, taille ; jamais le contenu.
- Regroupement si plus de 10 en une heure.

### F6. Conservation

- Rapports supprimés automatiquement **après 90 jours** (règle de cycle de vie du stockage).
- Station sans rapport depuis 12 mois : supprimée (tâche planifiée hebdomadaire).

## 6. Exigences non fonctionnelles

| Sujet | Exigence |
|---|---|
| Coût | Cible < 2 € par mois ; alerte de budget à 5 € et 10 € sur le groupe de ressources |
| Disponibilité | Pas d'engagement ; la station réessaie plus tard et garde le rapport localement |
| Délai | Réponse en moins de 10 s (démarrage à froid compris) ; la station attend 30 s au plus |
| Région | France Central (données dans l'UE) |
| Transport | HTTPS uniquement, TLS 1.2 minimum ; la station vérifie le certificat (aucune exception) |
| Journalisation | Application Insights avec échantillonnage et plafond quotidien (100 Mo) ; jamais le contenu des rapports ni le jeton |
| Versionnement | Préfixe `/api/v1` ; un changement incompatible = `/api/v2`, l'ancienne gardée 12 mois |
| Langue | Messages d'erreur en codes stables (`too_large`, `rate_limited`...), traduits côté station |

## 7. Architecture proposée

### 7.1 Composants Azure

| Ressource | Choix | Pourquoi |
|---|---|---|
| Calcul | **Azure Functions, plan Flex Consumption**, Python 3.11 | Payé à l'usage, quota gratuit mensuel, même langage que la station. Le plan Consumption Linux historique est en fin de vie : ne pas partir dessus. |
| Stockage | **Storage Account** (LRS, niveau Hot) : conteneur Blob `reports`, tables `stations` et `reports` | Quelques centimes par Go ; Table Storage suffit comme index |
| Identité | **Identité managée** de la Function vers le Storage (rôles Storage Blob Data Contributor, Storage Table Data Contributor) | Aucune chaîne de connexion à garder secrète |
| Supervision | Application Insights (échantillonnage, plafond quotidien) | Erreurs et temps de réponse |
| Budget | Budget du groupe de ressources + alertes e-mail | Plafond psychologique : Azure ne coupe pas tout seul |
| Domaine (option) | `collecte.rf-diy.com` (CNAME vers la Function, certificat géré) | Adresse stable si l'hébergement change |

À **ne pas** prendre : Front Door, API Management, Cosmos DB, Key Vault (rien à y mettre en v1), App Service dédié :
trop chers ou inutiles pour ce volume.

Vérifier la grille tarifaire et les quotas gratuits du plan Flex Consumption au moment du démarrage : ils évoluent.

### 7.2 Données

Table `stations` : `PartitionKey = "station"`, `RowKey = station_id`, `token_hash` (SHA-256 du jeton, jamais le jeton),
`first_seen`, `last_seen`, `last_version`, `reports_count`.

Table `reports` : `PartitionKey = station_id`, `RowKey = report_id`, `kind`, `version`, `os`, `rig_model`, `size`,
`received_at`, `blob_path`.

Blob : `reports/<station_id>/<report_id>.txt|.zip`, métadonnées minimales.

Limites de débit : compteurs en table `ratelimits` (`PartitionKey = "ip:<ip>"` ou `"st:<id>"`, `RowKey = AAAAMMJJ`),
supprimés après 2 jours. L'adresse IP n'est conservée que là, hachée avec un sel tournant chaque jour.

### 7.3 Sécurité

- Jeton comparé en temps constant à son empreinte.
- Taille vérifiée avant lecture complète (en-tête `Content-Length`, puis lecture bornée).
- Aucun contenu de rapport exécuté, décompressé sur disque ou affiché dans une page sans échappement.
- Stockage sans accès public (`allowBlobPublicAccess = false`), accès par identité managée uniquement.
- CORS fermé : seules les stations (pas les navigateurs) appellent le service.
- Dépendances Python figées avec empreintes (`pip --require-hashes`), Dependabot activé.

## 8. Côté station (dépôt openRemoteTRX, étape à venir)

- Module `trxstation/collecte.py` (stdlib seulement : `urllib.request`, `ssl`) : enregistrement, envoi, suppression.
- `[collecte] url = "https://collecte.rf-diy.com/api/v1"` dans station.toml ; vide = fonction désactivée.
- TRX Console, menu 8 : après création du zip, « Envoyer ce rapport à rf-diy.com ? (oui/non) », avec rappel de ce qu'il contient.
- Page : « Signaler un problème » > « Envoyer à rf-diy.com » relayé par la station (la page ne parle jamais directement au service).
- En cas d'échec : le rapport reste sur la station, message clair, aucune nouvelle tentative automatique.
- Tests : faux service local (aiohttp) qui reproduit les codes d'erreur du contrat.

## 9. Critères d'acceptation (version 1)

1. Une station neuve s'enregistre puis envoie un rapport `page` et un zip `troubleshooting` : `201`, fichiers et index présents.
2. Rapport trop gros : `413` ; zip piégé (chemin `..`, bombe) : `422` ; mot de passe visible : `422 secret_detected`.
3. Onzième rapport du jour : `429` avec `Retry-After`.
4. Mauvais jeton, ou jeton d'une autre station : `401`, rien d'écrit.
5. `DELETE` de la station : plus aucune trace dans les tables ni dans le Blob.
6. Rapport de 91 jours : supprimé par la règle de cycle de vie.
7. Aucun contenu de rapport ni jeton dans Application Insights.
8. Coût du premier mois réel affiché dans le portail, sous la cible.
9. Infrastructure recréée de zéro par le script Bicep dans un groupe de ressources vide.

## 10. Démarrer le nouveau projet

### 10.1 Décisions à prendre d'abord

- Nom du dépôt : par exemple `Bob56fr/rfdiy-collecte` (public, AGPL) ; le garder distinct d'openRemoteTRX.
- Nom de domaine : `collecte.rf-diy.com` ou adresse Azure par défaut pour commencer.
- Abonnement Azure du tenant à utiliser et personne qui reçoit les alertes de budget.

### 10.2 Poste de développement (Windows 11)

1. Python 3.11, Git, VS Code (extensions Azure Functions et Bicep).
2. Azure CLI (`winget install Microsoft.AzureCLI`), puis `az login`.
3. Azure Functions Core Tools v4 (`winget install Microsoft.Azure.FunctionsCoreTools`).
4. Azurite, l'émulateur local du stockage (`npm install -g azurite`).

### 10.3 Dépôt

1. Créer le dépôt GitHub vide, le cloner dans `C:\dev\rfdiy-collecte`.
2. Y copier ce document (`docs/cahier-des-charges.md`), `LICENSE` (AGPL) et un `CLAUDE.md` court : langue française,
   principes du chapitre 3, contrat d'API du chapitre 5, conventions SPDX.
3. Arborescence :
   ```
   rfdiy-collecte/
   ├── function_app.py          # routes HTTP (modèle Python v2)
   ├── collecte/                # validation, stockage, limites de débit
   ├── tests/                   # pytest (Azurite pour le stockage)
   ├── infra/main.bicep         # toute l'infrastructure
   ├── .github/workflows/       # tests + déploiement
   └── docs/
   ```
4. `func init --python` puis une première route `GET /api/v1/health` ; essai local avec `func start` et Azurite.

### 10.4 Azure

1. Groupe de ressources `rg-rfdiy-collecte-frc` en France Central.
2. Budget sur ce groupe (5 € et 10 €) **avant** tout déploiement.
3. `infra/main.bicep` : Storage Account, tables et conteneur, règle de cycle de vie 90 jours, Function App Flex
   Consumption avec identité managée et rôles, Application Insights avec plafond quotidien.
4. Déploiement : `az deployment group create -g rg-rfdiy-collecte-frc -f infra/main.bicep`.

### 10.5 Déploiement continu

1. Inscription d'application Entra ID avec **identité fédérée GitHub (OIDC)** : aucun secret Azure stocké dans GitHub.
2. Workflow : tests à chaque push, déploiement de la Function sur `main` après réussite.

### 10.6 Ordre de développement conseillé

1. `health`, puis `POST /stations` et `POST /reports` (texte seulement), avec leurs tests.
2. Zips, contrôles anti-bombe et anti-secret.
3. Limites de débit, `DELETE`, notification du mainteneur.
4. Domaine personnalisé, essais de charge légers, revue de sécurité.
5. Ensuite seulement : l'étape côté station dans openRemoteTRX (chapitre 8), qui s'appuie sur le contrat figé.

## 11. Questions ouvertes

- Faut-il accepter des rapports d'une station non enregistrée (sans jeton), plus strictement limités ?
- Le mainteneur veut-il une réponse possible à l'utilisateur (adresse e-mail facultative, consentement séparé) ?
- Statistiques anonymes de versions (combien de stations en 0.44.0) : utiles, mais seulement avec un accord explicite
  et séparé de l'envoi de rapports.
