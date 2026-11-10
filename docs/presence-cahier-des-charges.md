# Présence de groupe — cahier des charges

Version 2 (2026-11-10, étape 154). Elle reprend le cahier de l'utilisateur du 2026-11-09 (« Présence de groupe
remoteTRX ») et ajoute :
- l'avis donné le 2026-11-10 (sécurité, confidentialité, contradictions) et ses corrections (§ 3) ;
- les décisions de l'utilisateur du 2026-11-10 (§ 2) ;
- des valeurs proposées pour les points laissés « à définir » (§ 14) ;
- l'adaptation au code existant (module, bus des modules, `[[bands]]`) et un découpage en lots (§ 15).

Les questions encore ouvertes sont au § 16.

## 1. Objet

Un groupe d'amis équipés d'openRemoteTRX voit qui est actif sur sa station et, si chacun le veut bien, sur quelle
fréquence et dans quel mode. Pas de plateforme SaaS : un relais léger sur rf-diy.com transporte des états chiffrés
qu'il ne peut pas lire.

Objectifs (inchangés) : présence et statut par groupe ; partage choisi groupe par groupe ; QSY en un clic vers un ami
qui partage sa fréquence ; serveur anonyme (pseudos et identifiants de station seulement) ; aucun compte WordPress.

La présence ne fait que **montrer** et, sur demande de l'opérateur, **changer la fréquence et le mode en réception**.
Elle n'agit jamais sur le PTT, la porte audio ni le TOT.

| Inclus | Exclu |
|---|---|
| Présence et statut des membres, par groupe | Notifications, sons, fenêtres surgissantes |
| Partage : fréquence + mode, « On Air », ou texte libre | Page web publique des présences |
| Groupes avec administrateur et co-administrateurs | Compte WordPress pour les utilisateurs |
| QSY en un clic, en réception seulement | Émission déclenchée à distance |
| Statistiques agrégées pour l'administrateur | Historique détaillé sur le serveur |
| Clients : page web, application Android (téléphone et tablette) | **Android Auto** (décision du 2026-11-10) |
| | Service de push tiers (ntfy, Firebase) |

## 2. Décisions de l'utilisateur

1. 2026-11-09 : cahier d'origine (contexte, statuts, niveaux de partage, couleurs, statistiques, relais sans CRON).
2. 2026-11-10 : **pas d'Android Auto** pour cette fonction.
3. 2026-11-10 : **le relais démarre sur l'hébergement WordPress OVH** de rf-diy.com ; passage sur un VPS si le
   service suscite de l'intérêt, sans changement côté stations (§ 10).
4. 2026-11-10 : une fenêtre « toujours au premier plan » n'existe pas pour une page web ordinaire ; à la place,
   **l'opérateur peut afficher lui-même un bloc « Amis »** qui prend la place d'autres informations de la page ou de
   l'application (§ 9).

## 3. Corrections apportées au cahier d'origine

| N° | Problème relevé | Correction |
|---|---|---|
| C1 | Tous les membres partagent la même clé de groupe : n'importe lequel peut fabriquer l'état d'un autre (faux « F4XYZ sur 27.555 FM » qui attire un QSY) ; le relais peut rejouer un vieil état | Chaque état est **signé par la clé privée de la station** qui l'émet, avec un compteur croissant ; la passerelle qui le reçoit vérifie signature, compteur et appartenance au groupe (§ 5.3) |
| C2 | Le relais distribue les clés publiques : il peut glisser la sienne dans la liste des membres et recevoir la nouvelle clé de groupe à la rotation | **Liste des membres signée par un administrateur** (§ 5.2) ; l'empreinte de la clé de l'administrateur est dans l'invitation ; une clé publique connue ne change jamais |
| C3 | Rien ne dit comment le relais sait qu'une station peut rejoindre un groupe ; une invitation qui fuit donne un accès définitif | Invitation avec **jeton à usage unique et date d'expiration** ; l'adhésion n'est effective qu'une fois signée par un administrateur (§ 6.2) |
| C4 | Rythme d'interrogation de 60 s en activité et 2 à 5 min au repos : le relais lit l'activité dans les horaires des requêtes | **Rythme constant** quel que soit le statut ; **états complétés à une taille fixe** (§ 10.3) |
| C5 | Hors ligne après 5 min alors qu'une station au repos peut interroger toutes les 5 min : fausses mises hors ligne | Intervalle 90 s, hors ligne après 4 min (> 2,5 intervalles) |
| C6 | Le QSY applique une donnée venue d'Internet | Le **client** déclenche le QSY par les commandes existantes, après confirmation ; refusé pendant toute émission (station ou micro du poste) ; le module n'a **aucun droit** sur le poste (§ 8) |
| C7 | « Passerelle Pi », « pilotage WireGuard » | Station sur PC Debian, PC Windows ou Pi ; aucun VPN imposé |
| C8 | Texte libre « alphanumérique » mais exemple « Test antenne » avec une espace | Jeu de caractères précisé (§ 7.2) |
| C9 | « Absent depuis 3 j » plus une plage « Au shack » récurrente, entre gens qui connaissent l'adresse les uns des autres | Option « ne pas montrer la durée d'absence » (§ 7.3) |
| C10 | Les statistiques de l'administrateur ne se calculent que quand sa station tourne | Dit à l'adhésion ; les trous sont montrés comme tels (§ 11) |

## 4. Architecture

```
 client (page, application) ──(lien existant)──► passerelle ──bus 127.0.0.1──► module « presence » ──HTTPS──► relais
                                                     ▲                               │                     (api.rf-diy.com)
                                                     └───── messages « module » ─────┘
```

- **Un module de la station** (`trxstation/presence/`, déclaré dans `modules/builtin/presence/manifest.toml`), comme
  le Cluster DX, et non du code dans la passerelle : Internet, le relais et la cryptographie ne doivent jamais pouvoir
  faire tomber le composant critique, et la passerelle ne quitte jamais sur une erreur réseau.
- Le module lit l'état de la station sur le bus des modules (`freq_mode`, `ptt`, `trx_state`, activité des clients),
  **jamais par une seconde connexion à rigctld**.
- Manifeste : `commands = []` (ni PTT, ni QSY), connexions sortantes seulement, quotas CPU et mémoire bornés,
  niveaux de dégradation « pause » et « arrêt ».
- Les clients ne parlent **jamais** au relais ; ils lisent les présences auprès de leur passerelle, par les messages
  de module déjà relayés (`type: "module"`), et envoient leurs réglages au module par le même lien.
- Désactivé par défaut (`[presence] enabled = false`).

## 5. Identité et cryptographie

### 5.1 Identité des stations

1. À l'activation, le module crée une paire de clés **Ed25519** (signature). L'identifiant de station est
   l'**empreinte de la clé publique** (SHA-256 tronqué, encodé en base32) : plus de GUID séparé, aucun doublon
   possible. Il est **distinct** de l'identifiant de `station_id.py` (collecte des journaux) pour ne pas relier les
   deux services.
2. Une seconde paire **X25519** (chiffrement) sert à recevoir les clés de groupe. Les deux clés privées restent dans
   un fichier à côté de `station.toml` (`presence.key`, droits restreints, comme `breizh.key`), jamais transmises.
3. Enregistrement auprès du relais : identifiant, pseudo, deux clés publiques, **preuve de travail** (hashcash
   SHA-256, quelques secondes sur un Pi 4, difficulté choisie par le relais).
4. Chaque requête est signée et porte un horodatage (tolérance ±10 min) et un **compteur croissant** par station : le
   relais refuse un compteur déjà vu (rejeu).
5. Le pseudo (indicatif ou surnom) est modifiable par l'opérateur.

### 5.2 Liste des membres signée

Chaque groupe a une **liste des membres** versionnée : pour chaque membre, son identifiant, ses clés publiques, son
rôle (administrateur, co-administrateur, membre). Elle est **signée par un administrateur ou co-administrateur**
d'après la liste précédente. Une passerelle n'accepte une nouvelle version que si elle est signée par un
administrateur de la version qu'elle connaît. Le relais la stocke et la transmet sans pouvoir la modifier.

### 5.3 États

- Un état **par groupe** (le niveau de partage diffère d'un groupe à l'autre).
- Contenu : version, compteur, horodatage, statut, depuis quand, dernière émission, et selon le niveau : fréquence +
  mode, ou « On Air », ou texte.
- **Signé** (Ed25519, clé de la station) **puis chiffré** (XChaCha20-Poly1305, clé du groupe), complété à une
  **taille fixe** avant chiffrement.
- La passerelle qui reçoit vérifie : déchiffrement, signature d'un membre de la liste signée, compteur plus grand que
  le dernier vu, horodatage plausible. Sinon l'état est ignoré (et compté dans le journal du module).

### 5.4 Bibliothèques

Station : `cryptography` (déjà utilisée par `update/`, Ed25519, X25519, ChaCha20-Poly1305). Relais : extension
`sodium` de PHP (fournie depuis PHP 7.2 ; présence à vérifier sur l'offre OVH). Les clients (page, application) ne
font **aucune** cryptographie. Vecteurs d'essai communs station / relais : `tests/protocol/presence_vectors.json`.

## 6. Groupes

### 6.1 Création

La passerelle de l'administrateur demande un identifiant de groupe au relais, crée localement la clé symétrique du
groupe et signe la première liste des membres (elle seule, administrateur).

### 6.2 Invitation et adhésion

- **Invitation** : URL `https://api.rf-diy.com/i#…` et QR code (la partie après `#` n'est jamais envoyée au serveur
  par un navigateur) contenant : adresse du relais, identifiant du groupe, clé du groupe, empreinte de la clé de
  l'administrateur, **jeton à usage unique**, date d'expiration (7 jours par défaut). Transmise hors du relais
  (en main propre, messagerie, courriel).
- **Adhésion** : le nouveau membre colle ou scanne l'invitation (page, application, TRX Console). **Écran de
  consentement** : statistiques visibles par l'administrateur (§ 11), ce qui est partagé, rôle du relais. Il choisit
  son niveau de partage pour ce groupe.
- Sa passerelle présente le jeton au relais ; l'adhésion reste **en attente** jusqu'à la prochaine requête d'un
  administrateur, dont la passerelle vérifie le jeton (créé par elle) et signe la nouvelle liste. Le membre voit
  « en attente de validation » d'ici là.
- Un jeton déjà utilisé ou expiré est refusé.

### 6.3 Rôles

Administrateur et co-administrateurs : exclure un membre, consulter les statistiques, nommer ou retirer un
co-administrateur, transférer le rôle, supprimer le groupe, créer des invitations.

### 6.4 Exclusion et rotation de la clé

À chaque exclusion (et à chaque départ volontaire), la passerelle d'un administrateur crée une nouvelle clé de
groupe, signe la nouvelle liste et dépose la clé **chiffrée pour chaque membre restant** avec sa clé X25519 lue dans
la liste signée (jamais une clé fournie par le relais seul). L'exclu garde l'ancienne clé, devenue inutile.

### 6.5 Succession

Si aucun administrateur ne s'est manifesté depuis **90 jours**, le co-administrateur le plus ancien peut se déclarer
administrateur : sa passerelle signe une nouvelle liste ; le relais vérifie le délai d'après ses horodatages. Sans
co-administrateur, le groupe continue sans administration (plus d'adhésion ni d'exclusion).

## 7. Partage

### 7.1 Niveaux (par groupe, modifiables à tout moment)

| Niveau | Transmis avec le statut |
|---|---|
| Fréquence et mode | Fréquence exacte et mode (indissociables : nécessaires au QSY) |
| On Air | Le seul code « On Air » |
| Texte libre | Le texte choisi par l'opérateur (§ 7.2) |

### 7.2 Texte libre

16 caractères au plus : lettres sans accent, chiffres, espace, `-`, `.`, `/` (indicatifs `F4ABC/P`). Filtré par le
module ; textes prédéfinis mémorisés (« Mobile », « Test antenne »). Saisi depuis la page, l'application ou la console.
La modération d'un texte chiffré relève de l'administrateur du groupe.

### 7.3 Invisible et discrétion

- **Invisible** dans un groupe ou dans tous, sans quitter le groupe : les autres le voient « Hors ligne » (la station
  continue d'interroger le relais au même rythme ; limite assumée : un client modifié pourrait voir la différence).
- **Ne pas montrer la durée d'absence** (option par groupe, désactivée par défaut) : « Absent » sans durée.

## 8. QSY en un clic

- Disponible seulement pour un membre au niveau « Fréquence et mode » ; jamais pour « On Air » ni texte.
- Déclenché par le **client** (page, application), après **confirmation** : « Aller sur 14.205 USB ? », avec l'âge de
  l'information (depuis quand le membre y est, dernière émission) ; le client envoie les **commandes existantes**
  (mode puis fréquence, comme le rappel d'une mémoire). Le module n'a aucun droit sur le poste : aucune donnée
  reçue du relais ne peut changer quoi que ce soit sans un appui de l'opérateur.
- **Jamais d'émission.** Refusé pendant toute émission (de la station ou au micro du poste) ; si le statut de
  l'opérateur est « En QSO » sans émission en cours, avertissement renforcé. Le refus pendant l'émission est
  vérifié aussi par la passerelle (à confirmer au lot 3 : ajouter le refus s'il n'existe pas déjà).
- Fréquence et mode validés comme toute commande (bornes, modes du descripteur de capacités) ; un mode inconnu du
  poste = QSY sans changement de mode, avec un avertissement.
- **Retour** : le module mémorise fréquence et mode d'avant le dernier QSY de présence (le client le lui signale) ;
  un bouton « Retour » les rétablit (même chemin, même confirmation).
- **Changement de bande** : « vérifiez l'accord avant d'émettre ».
- **Plan de bande** : une fréquence hors des `[[bands]]` de `station.toml` est signalée (« émission impossible
  ici ») ; la réception reste permise. Pas de nouvelle notion de « classe de licence ».
- Interdit aux visiteurs en réception seule ; ils ne voient pas la présence.

## 9. Affichage

L'affichage est passif : aucun son, aucune notification, aucune fenêtre surgissante.

### 9.1 Statuts et couleurs

| Priorité | Statut | Déclenchement | Fin | Couleur | Marqueur |
|---|---|---|---|---|---|
| 1 | En QSO | Émission (station ou micro du poste) | 10 min après la dernière émission | Rouge plein | Q |
| 2 | En RX | Fréquence ou mode changés, commande d'un client opérateur, client opérateur connecté | 5 min sans interaction | Vert | R |
| 3 | Au shack | Déclaration (« pour 2 h », plage récurrente suspendable) | Fin de la plage | Ambre | S |
| 4 | Absent | Aucun des cas précédents | — | Gris | A |
| 5 | Hors ligne | Pas de requête depuis 4 min (calculé par le relais à la lecture) | Retour | Pastille vide cerclée | — |

L'écoute d'un visiteur ne compte pas comme activité. Au shack : une activité fait passer en RX ou QSO, puis retour à
Au shack si la plage court toujours.

### 9.2 Règles communes

Actifs en haut, absents et hors ligne en bas, grisés. Toucher un membre = détail (fréquence et mode ou texte, durée
dans l'état, dernière émission, bouton QSY). « Mis à jour il y a x s ». Vue par groupe ou par membre (un membre de
plusieurs groupes n'apparaît qu'une fois).

### 9.3 Bloc « Amis » choisi par l'opérateur (décision du 2026-11-10)

L'opérateur **affiche lui-même** un bloc « Amis » qui prend la place d'autres informations ; il le masque quand il
veut. Le choix est mémorisé sur l'appareil.

- **Page web** : bloc « Amis » placé par le système de mise en page existant (`layout.js`) : à la place d'une
  rubrique, dans une colonne, ou en grand (le reste de la page réduit à l'en-tête, la fréquence, le PTT et STOP, qui
  restent toujours visibles). Une ligne par membre : pastille, pseudo, fréquence et mode ou texte ; groupes
  repliables. EN PLUS, là où le navigateur le permet (Chrome, Edge : API Document Picture-in-Picture), un bouton
  « Fenêtre détachée » ouvre une petite fenêtre au premier plan ; ailleurs le bouton n'apparaît pas.
- **Application, téléphone** : bandeau discret de pastilles dans l'onglet Station (toucher = vue complète) ; option
  « Bloc Amis » qui remplace le petit waterfall et les bandes de l'onglet Station par la liste ; vue complète dans
  l'onglet Mémoires et Cluster DX (sous-onglet « Amis »).
- **Application, tablette** : rubrique « Amis » dans le rail (avec Mémoires, Audio, Réglages), et option de la
  mettre à la place du spectre du son.
- **Veille du shack** (application) : plein écran, fond noir, gros caractères, luminosité basse, écran allumé
  pendant la charge ; STOP reste accessible si une émission est en cours.
- PTT et STOP ne sont jamais cachés par le bloc « Amis ».

## 10. Relais

### 10.1 Hébergement (décision du 2026-11-10)

- Démarrage sur l'hébergement **WordPress OVH mutualisé** de rf-diy.com : petit script PHP autonome sur un
  sous-domaine (`api.rf-diy.com`) qui **ne charge pas WordPress** ; un plugin WordPress fournit le back-office (pseudo,
  identifiant, date d'enregistrement, dernière activité, groupes ; rien d'autre).
- Passage sur un VPS si le service prend de l'ampleur : seule l'adresse du relais change (`[presence] relay_url`,
  plus une redirection annoncée par l'ancien relais).
- Risque assumé : un abus peut ralentir le blog. Parades sur ce même hébergement : rejet le plus tôt possible
  (taille, signature de forme, limite de débit) avant toute requête en base ; limite de débit par fichiers (pas
  d'APCu ni de Redis supposés) ; **pas de Cloudflare pour la preuve de concept** (décision du 2026-11-10, à
  reconsidérer en cas d'abus ou au passage sur VPS) ; **frein général** : chaque réponse
  donne l'intervalle suivant (`next_in`), le même pour toutes les stations, que le relais peut allonger en cas de
  charge, et un mode « pause » (le module réessaie plus tard, sans erreur pour l'opérateur).

### 10.2 Requête unique

La passerelle envoie ses états (un par groupe) et reçoit dans la même réponse : états des membres de ses groupes avec
leur âge, listes des membres signées si elles ont changé, clés de groupe chiffrées pour elle, adhésions en attente
(administrateurs), `next_in`. Réponse vide si rien n'a changé depuis le dernier compteur.

### 10.3 Rythme

**Constant** : 90 s (`next_in`), que la station soit active ou non. Hors ligne après 4 min. Ordre de grandeur :
50 stations ≈ 0,6 requête/s (≈ 48 000 par jour).

### 10.4 Données stockées

Par station : identifiant, pseudo, clés publiques, groupes, dernier état chiffré par groupe, horodatage et compteur de
la dernière requête, version du module. Par groupe : listes des membres signées (dernière version), clés chiffrées,
jetons d'invitation utilisés. **Aucune adresse IP en base.** Expiration calculée à la lecture ; purge occasionnelle
lors d'une écriture (pas de CRON).

## 11. Statistiques de l'administrateur

Calculées sur la passerelle de l'administrateur (et des co-administrateurs) à partir des états qu'elle reçoit déjà ;
le relais n'a aucun historique d'activité.

| Statistique | Source | Granularité |
|---|---|---|
| Dernière activité | Passerelle admin | Date |
| Jours actifs sur le mois | Passerelle admin | Nombre |
| Temps approximatif en QSO et en RX | Passerelle admin | Par semaine |
| Date d'adhésion | Relais | Date |
| Version du module | Relais | Dernière connue |
| Erreurs répétées, débit anormal | Relais | Indicateur |

Agrégées seulement. Historique local : 6 mois. Les périodes où la station de l'administrateur était éteinte sont
montrées comme « non observé ». Les membres en sont informés à l'adhésion.

## 12. Sécurité, abus, déni de service

| Menace | Parade |
|---|---|
| Usurpation d'une station auprès du relais | Requêtes signées, horodatées, compteur croissant |
| Usurpation d'un membre auprès des autres membres | États signés par la station (§ 5.3) |
| Relais malveillant ou compromis | Liste des membres signée par un administrateur, empreinte dans l'invitation, clé publique figée (§ 5.2) |
| Invitation qui fuit | Jeton à usage unique, expiration, validation par un administrateur |
| Enregistrements massifs | Preuve de travail, quota par adresse IP (en mémoire de courte durée, jamais en base) |
| Flot de requêtes | Limite par station et par IP avant toute base ; `next_in` et pause |
| Messages volumineux | Taille maximale de requête ; états de taille fixe |
| Lecture par le serveur | États chiffrés avec la clé du groupe, inconnue du serveur |
| Activité lue dans les horaires | Rythme constant, taille fixe |
| Membre exclu | Rotation de la clé |
| Action à distance sur le TRX | Module sans aucun droit sur le poste ; QSY seulement par l'opérateur, confirmé, en réception |
| Relais en panne | Le module se tait et réessaie ; la station, la page et l'application fonctionnent sans lui |

## 13. Confidentialité (RGPD)

Comme le cahier d'origine : le relais ne connaît ni fréquences, ni modes, ni textes, ni statuts ; aucune IP en base
(journaux d'OVH soumis à leur durée de conservation) ; données supprimées à la désinscription (bouton dans la console,
la page et l'application) ; stations inactives purgées après 12 mois ; mention dans la politique de confidentialité
de rf-diy.com ; écran de consentement à l'adhésion.

## 14. Valeurs retenues (points « à définir » du cahier d'origine)

Validées par l'utilisateur le 2026-11-10 (« larges pour la preuve de concept »).

| Point | Valeur |
|---|---|
| Groupes créés par station | 5 |
| Groupes rejoints par station | 20 |
| Membres par groupe | 50 |
| Taille d'un état chiffré | 256 octets (fixe) |
| Taille maximale d'une requête | 16 ko |
| Reprise du rôle d'administrateur | 90 jours |
| Historique sur la passerelle de l'administrateur | 6 mois |
| Purge des stations inactives | 12 mois |
| Signature / chiffrement | Ed25519 ; X25519 + XChaCha20-Poly1305 (sceau pour les clés) ; XChaCha20-Poly1305 pour les états |
| Rythme / hors ligne | 90 s constant / 4 min |
| Invitation | URL avec fragment `#` + QR code, expiration 7 jours, usage unique |
| Preuve de travail | hashcash SHA-256, difficulté fixée par le relais (≈ 5 s sur un Pi 4) |

## 15. Lots proposés

1. **Protocole et calculs** (FAIT, étape 155 : `trxstation/presence/`, `docs/protocole-presence.md`) : `trxstation/presence/` partie pure (statuts et priorités, temporisations, format et
   remplissage des états, signatures, liste signée, invitations, preuve de travail), `presence_vectors.json`,
   `docs/protocole-presence.md` (relais) ; tests.
2. **Relais PHP et plugin WordPress** : dans un **autre dépôt** (comme la collecte Azure), d'après le protocole figé au
   lot 1 et ses vecteurs ; faux relais Python dans `devtools/` pour les essais de la station.
3. **Module de la station** : manifeste, enregistrement, boucle de requêtes, groupes, invitations, rotation,
   statistiques ; `[presence]` dans `station.toml` (notice), réglages des groupes dans `state_dir/presence/` ; messages
   vers les clients (`docs/protocole.md`, `hello.features`) ; TRX Console (menu « Présence de groupe » : pseudo,
   groupes, invitation en QR code, désinscription ; mode d'emploi) ; ligne de trx-monitor ; tests de panne (relais
   muet, réponses fausses, états forgés, rejeu, liste non signée).
4. **Page web** : bloc « Amis », consentement, niveaux de partage, textes, Au shack, invisible, QSY et Retour,
   statistiques de l'administrateur, fenêtre détachée là où elle existe.
5. **Application Android** : bandeau, vue complète, bloc « Amis » (téléphone, tablette), veille du shack, QSY et
   Retour ; `docs/parite-web-android.md`.

Chaque lot est validé par l'utilisateur avant le suivant.

## 16. Questions

Réponses de l'utilisateur du 2026-11-10 :
1. Relais PHP et plugin WordPress : **dans un autre dépôt**, pour plus de sécurité.
2. Hébergement OVH vérifié par l'utilisateur le 2026-11-10 (petit fichier d'essai) : **PHP 8.2.35, extension
   `sodium` présente**, `sodium_crypto_aead_xchacha20poly1305_ietf_encrypt` et `sodium_crypto_sign_detached`
   disponibles. Le relais vise PHP 8.2.
3. **Pas de Cloudflare** pour la preuve de concept.
4. Valeurs du § 14 **validées**.
