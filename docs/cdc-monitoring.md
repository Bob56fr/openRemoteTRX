# openRemoteTRX — Cahier des charges : module Monitoring inter-stations

Nov 11, 2026 · @Kriss

## 1. Objet et périmètre

Le module **trx-monitor-link** permet à une station openRemoteTRX d'envoyer périodiquement, à d'autres stations qu'elle a choisies, son état de fonctionnement, ses métriques, ses événements et des logs détaillés de debug. Une même station peut émettre et recevoir. Le but est le monitoring et l'aide au debug entre opérateurs, sans jamais donner la main sur la station distante.

Vocabulaire :

- **Station** : une installation openRemoteTRX (superviseur, passerelle, rigctld, modules).
- **Émetteur** : station qui envoie ses informations.
- **Receveur** : station qui reçoit, stocke, affiche et alerte.
- **Liaison** : relation appairée et orientée émetteur → receveur. Deux stations qui s'échangent mutuellement leurs informations ont deux liaisons indépendantes.
- **Profil d'envoi** : ensemble des catégories, niveaux et fréquences choisis par l'émetteur pour une liaison donnée.

Hors périmètre : toute commande à distance du TRX, l'audio, la vidéo, les spectres. Le module ne transporte que de la télémétrie et des logs.

## 2. Exigences non fonctionnelles

Le TRX reste toujours prioritaire : une panne, une surcharge ou une attaque sur le module ne doit jamais dégrader la passerelle, le CAT ni la sécurité PTT.

- **Isolation** : processus séparé (`trx-monlink`), lancé par le superviseur (systemd sous Linux, mode géré sous Windows), priorité basse (`nice 10` / `BELOW_NORMAL`). Son arrêt n'affecte aucune autre fonction.
- **Budget réseau** : débit sortant plafonné par liaison et global (défaut 32 kbit/s global, 8 kbit/s par liaison). Pendant une session audio cliente, le débit est réduit à 25 % du plafond ; les logs différés sont envoyés après.
- **Ressources** : mémoire < 80 Mo, CPU moyen < 3 % d'un cœur sur Raspberry Pi 4.
- **Sécurité** : aucun paquet non authentifié ne reçoit de réponse ; toute donnée chiffrée et authentifiée ; cryptographie uniquement via libsodium (PyNaCl), aucun algorithme maison.
- **Plateformes** : Debian, Raspberry Pi OS, Windows, comme le reste de la station.
- **Consentement** : rien n'est envoyé sans une liaison appairée et un profil d'envoi explicitement validé par l'émetteur.
- **Configuration** : section `[monitor_link]` dans `station.toml` ; clés et liaisons dans un fichier séparé `monitor_peers.toml` (droits 600), jamais écrasé par une mise à jour.

## 3. Identité de station et appairage

Chaque station possède une identité unique et durable, mutualisée avec la future fonction de présence entre amis.

- **GUID de station** (UUID v4) généré à la première installation.
- **Paire de clés Ed25519** (signature) dont on dérive la clé X25519 (chiffrement), générée localement ; la clé privée ne quitte jamais la station.
- **Pseudo** libre et indicatif optionnel, affichés aux receveurs.
- **Empreinte** : 6 chiffres dérivés du hachage BLAKE2b des deux clés publiques de la liaison, identique des deux côtés.

L'appairage est toujours initié par le receveur, qui invite :

1. Le receveur crée une invitation dans la console : code à usage unique (10 caractères, base32), valable 15 min, affichable en QR code. L'invitation contient son GUID, sa clé publique, ses points de contact (relais de signalisation ou IP:port UDP) et un secret aléatoire de 128 bits.
2. Il transmet le code à l'émetteur par un canal externe (mail, message, téléphone).
3. L'émetteur saisit le code dans sa console. Sa station envoie une demande d'appairage chiffrée avec la clé publique du receveur et authentifiée par le secret de l'invitation.
4. Les deux consoles affichent la même empreinte à 6 chiffres. Les deux opérateurs la comparent de vive voix ou par message, puis confirment chacun de leur côté.
5. L'émetteur choisit le profil d'envoi (section 5) ; rien n'est envoyé avant cette validation.
6. Les clés publiques sont enregistrées dans `monitor_peers.toml` ; l'invitation est détruite.

Règles : 5 essais de code erronés invalident l'invitation ; une empreinte non confirmée sous 10 min annule l'appairage ; une invitation sert à une seule liaison ; un changement de clé de l'autre station suspend la liaison et impose un nouvel appairage. Pour un échange mutuel, chaque station invite l'autre.

## 4. Transport UDP

Deux modes de transport, tous deux en UDP, essayés dans cet ordre ; le mode actif est affiché pour chaque liaison.

**Mode A — canal de données WebRTC (prioritaire, aucun port ouvert).** Réutilise aiortc, déjà présent dans le projet. ICE avec STUN (serveur public en V1, joint via le nom stun.rf-diy.com en CNAME pour pouvoir en changer) traverse les NAT des deux box par « hole punching » ; DTLS chiffre le canal, dont l'empreinte de certificat est signée par la clé Ed25519 de la station (protection contre l'interception). La signalisation (échange des offres SDP) passe par le relais HTTPS prévu sur rf-diy.com pour la présence ; le relais ne voit que des messages signés et chiffrés de bout en bout, jamais le contenu. Pas de serveur TURN en V1 : en cas d'échec ICE (NAT symétrique, CGNAT 4G), bascule en mode B.

**Mode B — port UDP silencieux (repli).** Le receveur ouvre un port UDP sur sa box (défaut 51830, configurable). Chaque paquet porte : identifiant de liaison (8 octets), compteur 64 bits, données chiffrées XChaCha20-Poly1305 avec la clé de liaison issue d'un échange X25519. Tout paquet dont l'authentification échoue est ignoré **sans aucune réponse**, comme WireGuard : le port est indiscernable d'un port fermé pour un scanner. Clé de liaison renouvelée toutes les 24 h ou tous les 2³² paquets.

**Fiabilité, dans les deux modes :**

| Type de message | Livraison | Taille | Fréquence par défaut |
| --- | --- | --- | --- |
| Battement de cœur | sans accusé | < 200 octets | 60 s |
| État et métriques | sans accusé, la valeur suivante remplace | < 1 200 octets | 60 s |
| Événements (codes d'erreur) | accusé et retransmission | < 1 200 octets | immédiat |
| Lots de logs | accusé, retransmission, fragments ≤ 1 200 octets | lot ≤ 256 Ko compressé zstd | 5 min |
| Instantané de diagnostic | accusé, retransmission | ≤ 2 Mo compressé | à la demande |

Anti-rejeu : fenêtre glissante de 2 048 compteurs. Retransmission : 3 essais avec délai doublé (2, 4, 8 s), puis mise en file locale. File d'attente côté émetteur : 24 h ou 50 Mo maximum, les logs les plus anciens et de plus faible gravité étant supprimés en premier. Les événements critiques ne sont jamais supprimés de la file.

## 5. Données échangées et granularité

L'émetteur choisit, pour chaque destinataire, chaque catégorie avec son niveau et sa fréquence ; trois profils prédéfinis servent de point de départ et restent modifiables.

| Catégorie | Contenu détaillé | Réglages par destinataire |
| --- | --- | --- |
| Battement de cœur | GUID, version, uptime, horodatage, mode de transport | toujours actif dès la liaison validée |
| Système | CPU par cœur, charge, RAM, swap, disque, température, horloge NTP (écart), OS, version Python | on/off, fréquence 30 s à 15 min |
| Processus | état et redémarrages du superviseur, de la passerelle, de rigctld et de chaque module ; PID, CPU, RAM, threads | on/off, fréquence |
| CAT / Hamlib | version Hamlib, modèle, port, vitesse, latence des commandes (min/moy/max/p95), taux d'erreurs, timeouts, reconnexions | on/off, fréquence |
| TRX | fréquence, mode, filtre, puissance, S-mètre, ALC, SWR, préampli, NB, NR | on/off ; **fréquence et mode masquables séparément** |
| PTT / sécurité | nombre et durée des émissions, déclenchements du timeout 3 min, refus de PTT, retombées en réception sur panne | on/off |
| Audio | périphériques, taux d'échantillonnage, niveaux, sous-débits et sur-débits (xruns), latence, gigue, pertes WebRTC, codec | on/off, fréquence |
| Réseau | sessions clientes (nombre, durée, sans identité), débit, RTT, pertes, résultats de la sonde de qualité réseau | on/off, fréquence |
| Modules | état SDR, vidéo, cluster DX, FreeDV, SELCALL, présence et modules extérieurs déclarés comme Breiz Audio ou FreeDV (selon les modules installés) | on/off par module |
| Événements | codes du catalogue (section 7) avec contexte | gravité minimale : info, avertissement, erreur, critique |
| Logs | lignes de log structurées (JSON) par module | on/off par module ; niveau DEBUG, INFO, WARNING, ERROR ; fréquence des lots |

Profils prédéfinis :

- **Essentiel** : battement de cœur, système, processus, événements ≥ erreur.
- **Diagnostic** : Essentiel + CAT, PTT, audio, réseau, événements ≥ avertissement, logs INFO.
- **Debug complet** : toutes les catégories, logs DEBUG ; expire automatiquement au bout de 72 h (durée réglable 1 h à 14 jours), puis retour au profil précédent.

Chaque message porte le GUID de l'émetteur, un numéro de séquence, un horodatage UTC en millisecondes et la version du schéma de données. Le schéma est décrit en JSON Schema dans le dépôt, encodé en CBOR sur le réseau.

## 6. Masquage obligatoire des données sensibles

Le masquage s'applique dans le processus émetteur, avant chiffrement et mise en file, et ne peut pas être désactivé, quel que soit le profil.

| Donnée | Traitement |
| --- | --- |
| Mots de passe, jetons, clés, secrets (station.toml, cluster DX, ntfy, comptes) | supprimés : `***` |
| Identifiants de connexion des opérateurs et des visiteurs | remplacés par un alias stable par liaison (`user-1`, `visiteur-3`) |
| Adresses IPv4 et IPv6 | réseau privé conservé en classe (`LAN`), IP publique remplacée par un hachage court + pays si connu |
| Adresses MAC, numéros de série matériel | tronqués aux 3 premiers octets |
| URL de notification ntfy et URL avec paramètres | domaine conservé, chemin et paramètres supprimés |
| Chemins de fichiers contenant le nom d'utilisateur | nom d'utilisateur remplacé par `<user>` |
| Fréquence et mode | transmis seulement si l'émetteur l'a autorisé pour ce destinataire |

Mise en œuvre : un filtre unique `redact.py` appliqué à tous les messages et à toutes les lignes de log (règles par champ structuré + expressions régulières de secours sur le texte libre). Chaque règle a son test unitaire. L'émetteur peut prévisualiser dans la console, pour chaque destinataire, un échantillon exact de ce qui part. Les logs doivent être structurés (champs nommés) pour que le masquage soit fiable ; les modules existants seront adaptés dans un lot dédié.

## 7. Catalogue d'erreurs

Le catalogue devient la référence unique de toute la suite : un seul fichier `errors/catalog.yaml` dans le dépôt, utilisé par le superviseur, ntfy, le monitor, la qualification TRX, la remontée Azure et la documentation rf-diy.

Règles :

- Code au format `ORT-NNNN` : stable, jamais réutilisé ni renuméroté ; une erreur abandonnée passe en `deprecated: true`.
- Le code ne lève jamais d'erreur par un texte libre : il utilise une constante générée depuis le YAML (`errors/codes.py`), ce que vérifie un test.
- Chaque événement émis porte le code, la gravité et un dictionnaire de contexte (valeurs mesurées, module, port, etc.).
- Textes en français dans le YAML, champ `en` obligatoire dès la bêta (titre, message, causes et préconisation en anglais ; un test refuse toute entrée sans traduction).
- Une page de documentation par code est générée automatiquement (`docs/errors/ORT-NNNN.md`), publiable sur rf-diy.

Plages :

| Plage | Domaine |
| --- | --- |
| 1000–1999 | Système (OS, disque, CPU, température, horloge, mises à jour) |
| 2000–2999 | CAT / Hamlib / rigctld / port série |
| 3000–3999 | Audio (périphériques, xruns, WebRTC média) |
| 4000–4999 | Réseau (clients, sonde de qualité, VPN, NAT) |
| 5000–5999 | PTT et sécurité d'émission |
| 6000–6999 | Modules (6000 SDR, 6200 vidéo, 6400 cluster DX, 6500 interface des modules extérieurs, 6800 SELCALL, 6900 présence) |
| 7000–7999 | Monitor inter-stations (appairage, transport, quotas) |
| 8000–8999 | Superviseur et processus |
| 9000–9999 | Configuration et installation |

### Modules extérieurs

Les modules extérieurs qui interagissent avec openRemoteTRX (Breiz Audio, FreeDV, futurs modules de tiers) ont leur propre espace de codes, avec un préfixe enregistré à la place de `ORT`. Leurs erreurs suivent le même schéma YAML et passent par les mêmes canaux : superviseur, monitor inter-stations, ntfy, page web.

Règles :

- **Préfixe** de 3 lettres majuscules, unique, déclaré dans le registre `errors/modules.yaml` (préfixe, nom, rôle, mode d'interaction, contact, version minimale d'openRemoteTRX, chemin du catalogue). `ORT` est réservé au cœur.
- **Catalogue fourni par le module** : fichier `<PREFIXE>-catalog.yaml` livré avec lui, même structure que celui du cœur, textes en français et en anglais obligatoires, codes `<PREFIXE>-NNNN` stables et jamais réutilisés. Les plages internes sont libres pour chaque module, mais conseillées : 0xxx démarrage et configuration, 1xxx traitement, 2xxx interface avec la station, 9xxx divers.
- **Remontée des événements** : le module écrit sur le même socket local que les modules internes, avec un champ `module` (son préfixe) et un battement de cœur toutes les 30 s. Le masquage (section 6) s'applique à ses messages comme aux autres.
- **Validation au chargement** : un catalogue invalide ou incomplet n'empêche pas le module de tourner, mais ses événements sont affichés sous le code générique ORT-6505 avec le texte brut.
- **Profils d'envoi** : chaque module extérieur déclaré apparaît comme une ligne à part dans la catégorie Modules et dans les logs par module, activable par destinataire.

Préfixes réservés au départ :

| Préfixe | Module | Rôle vis-à-vis de la station |
| --- | --- | --- |
| ORT | cœur openRemoteTRX | réservé |
| BZA | Breiz Audio | à préciser |
| FDV | FreeDV | encodage et décodage numérique sur la passerelle |

Les problèmes de **liaison** entre la station et un module extérieur restent des codes `ORT`, dans la plage 6500–6599, car c'est la station qui les constate :

| Code | Gravité | Titre | Préconisation résumée |
| --- | --- | --- | --- |
| ORT-6501 | erreur | Module extérieur déclaré mais absent ou non démarré | Vérifier son installation et son lancement |
| ORT-6502 | erreur | Version du module incompatible | Mettre à jour le module ou openRemoteTRX |
| ORT-6503 | erreur | Échec de la négociation avec le module | Vérifier la configuration d'interface (socket, port, périphérique audio) |
| ORT-6504 | avertissement | Le module ne répond plus (battement perdu) | Consulter ses logs ; redémarrage par le superviseur si prévu |
| ORT-6505 | avertissement | Catalogue du module invalide ou non traduit | Signaler à l'auteur du module |
| ORT-6506 | avertissement | Code reçu absent du catalogue du module | Mettre à jour le catalogue du module |
| ORT-6507 | erreur | Le module perturbe la station (CPU, latence audio) | Module isolé ou arrêté ; réduire sa charge |
| ORT-6508 | avertissement | Préfixe non enregistré | Déclarer le module dans le registre |

Structure d'une entrée :

```yaml
ORT-2104:
  gravite: erreur            # info | avertissement | erreur | critique
  titre: Délai de réponse CAT dépassé
  message: "Le TRX n'a pas répondu à {commande} en {delai_ms} ms ({n} fois sur 5 min)."
  causes:
    - Câble USB débranché ou défectueux
    - Vitesse série différente de celle réglée dans le TRX
    - Port COM pris par un autre logiciel
  preconisation: >
    Vérifier le câble USB et la vitesse CI-V du TRX, fermer tout autre logiciel
    de contrôle, puis lancer le diagnostic CAT de l'assistant.
  action_auto: redemarrer_rigctld   # aucune | redemarrer_<processus> | retour_rx | ...
  ntfy_defaut: true
  priorite_ntfy: 4
  doc: https://rf-diy.com/openremotetrx/erreurs/ORT-2104
  depuis_version: 0.9.0
```

Premières entrées à rédiger (liste de départ, à compléter par Claude Code en inventoriant les erreurs existantes du code) :

| Code | Gravité | Titre | Préconisation résumée |
| --- | --- | --- | --- |
| ORT-1001 | avertissement | Disque presque plein (> 85 %) | Purger logs et enregistrements, vérifier la rétention |
| ORT-1010 | avertissement | Température CPU élevée (> 75 °C) | Vérifier ventilation et charge des modules |
| ORT-1020 | erreur | Horloge désynchronisée (> 2 s) | Activer NTP ; l'horodatage des logs est faussé |
| ORT-2001 | critique | Port série du TRX introuvable | Vérifier câble USB, alimentation du TRX, pilote |
| ORT-2002 | erreur | rigctld ne démarre pas | Vérifier modèle Hamlib et port, relancer l'assistant |
| ORT-2104 | erreur | Délai de réponse CAT dépassé | Câble, vitesse CI-V, logiciel concurrent |
| ORT-2200 | avertissement | Version Hamlib obsolète | Mettre à jour via l'assistant |
| ORT-3001 | critique | Périphérique audio du TRX absent | Vérifier USB et carte son du TRX |
| ORT-3010 | avertissement | Sous-débits audio fréquents (xruns) | Réduire la charge, augmenter le tampon |
| ORT-4001 | avertissement | Pertes réseau client > 5 % | Voir sonde de qualité réseau, maillon faible |
| ORT-5001 | critique | Timeout d'émission 3 min déclenché | Vérifier le client, le PTT bloqué ou la liaison |
| ORT-5002 | critique | Retour forcé en réception sur perte client | Vérifier stabilité réseau du client |
| ORT-5010 | critique | PTT actif sans session cliente | Contrôler le TRX immédiatement |
| ORT-7001 | info | Liaison monitor établie | Aucune |
| ORT-7010 | avertissement | Échec ICE, bascule en port UDP | Ouvrir le port UDP côté receveur si besoin |
| ORT-7020 | avertissement | File d'envoi saturée | Réduire le profil ou augmenter le débit |
| ORT-7030 | erreur | Clé distante changée, liaison suspendue | Refaire l'appairage après vérification |
| ORT-8001 | erreur | Redémarrage d'un processus par le superviseur | Consulter les logs du processus concerné |
| ORT-8002 | critique | Boucle de redémarrages (> 3 en 10 min) | Processus arrêté, intervention requise |
| ORT-9001 | erreur | station.toml invalide | Corriger la ligne indiquée ou relancer l'assistant |

## 8. Réception, stockage et quotas

Le receveur stocke tout localement dans une base SQLite dédiée (`monitor_link.db`, mode WAL), une source par émetteur, sans rien renvoyer vers un tiers.

- **Tables** : `sources` (GUID, pseudo, clé, état de liaison), `heartbeats`, `metrics` (série temporelle par nom de métrique), `events` (code, gravité, contexte JSON), `logs` (ligne JSON, module, niveau, recherche plein texte FTS5), `snapshots` (fichiers compressés sur disque, référence en base).
- **Rétention par défaut**, réglable par source : métriques 30 jours (agrégées à 5 min au-delà de 48 h), événements 180 jours, logs 14 jours, instantanés 30 jours.
- **Quotas par source** fixés par le receveur : volume par jour (défaut 50 Mo) et espace disque total (défaut 500 Mo). Au dépassement : événement ORT-7021 côté receveur, rejet des logs DEBUG puis INFO, conservation des événements ; l'émetteur est informé et réduit son envoi.
- **Limitation de débit entrant** : 200 paquets/s par source ; au-delà, paquets ignorés et source signalée.
- **Purge** : quotidienne, plus purge immédiate de toutes les données d'une source sur demande du receveur.

## 9. Alertes ntfy côté receveur

Le receveur définit ses propres règles d'alerte par source, avec la configuration ntfy existante du superviseur (`notify_url`) ou un sujet ntfy dédié au monitoring.

| Type de règle | Exemple | Paramètres |
| --- | --- | --- |
| Absence de nouvelles | aucun battement de cœur depuis 5 min | délai (2 à 120 min) ; **règle activée par défaut** |
| Code d'erreur | ORT-5010 reçu | un code ou une plage (ex. 5000–5999) |
| Gravité | tout événement ≥ critique | gravité minimale |
| Seuil de métrique | température CPU > 80 °C pendant 3 min | métrique, opérateur, seuil, durée |
| Retour à la normale | battement revenu, seuil repassé | activable par règle |

Anti-spam obligatoire :

- **Dédoublonnage** : une même règle pour une même source ne notifie qu'une fois par fenêtre (défaut 30 min), avec le nombre d'occurrences dans le message suivant.
- **Hystérésis** sur les seuils (défaut 5 %).
- **Heures silencieuses** par source ; les événements critiques passent outre si l'option est cochée.
- **Plafond global** : 20 notifications par heure, puis une notification de synthèse.

Contenu de la notification : pseudo de la station, code, titre, message avec valeurs, préconisation résumée, lien vers la page web du rapport ; priorité ntfy reprise du catalogue (`priorite_ntfy`), surchargeable par règle.

## 10. Demande de diagnostic

Le receveur peut demander plus d'informations, mais seul l'émetteur décide : aucune demande ne s'applique sans son accord explicite.

Types de demande :

- **Instantané** : état complet à l'instant T (configuration masquée, versions, processus, 30 dernières minutes de logs DEBUG du tampon circulaire, résultats d'un diagnostic de l'assistant).
- **Élévation temporaire** : passage d'un module ou de tous en DEBUG pour une durée choisie (15 min à 24 h), retour automatique au profil antérieur.

Déroulé : la demande arrive dans la console de l'émetteur et, si ntfy est configuré, en notification ; l'émetteur accepte, refuse ou ignore (expiration au bout de 24 h). Le receveur voit l'état de sa demande. Un tampon circulaire de 30 min de logs DEBUG est conservé en mémoire sur l'émetteur, jamais envoyé sans demande acceptée. Limite : 3 demandes par jour et par liaison.

L'émetteur peut aussi envoyer un instantané de lui-même à un destinataire, sans demande, depuis la console.

## 11. Fin de liaison et révocation

Chaque opérateur peut mettre fin à une liaison à tout moment, en un clic, sans l'accord de l'autre ; l'effet est immédiat.

| Action | Qui | Effet |
| --- | --- | --- |
| Pause | émetteur | envoi suspendu (battement de cœur compris) ; le receveur voit « en pause », pas d'alerte d'absence |
| Pause de réception | receveur | paquets ignorés, alertes désactivées, liaison conservée |
| Arrêt d'émission | émetteur | message signé « fin de liaison », clés de liaison effacées, file vidée |
| Arrêt de réception | receveur | message signé « fin de liaison », clé de l'émetteur supprimée, ses paquets ignorés ensuite |
| Purge | receveur | effacement de toutes les données reçues de la source (proposé à l'arrêt) |

Le message de fin est envoyé 3 fois ; s'il n'arrive pas, la liaison est quand même close localement, et l'autre côté la constate par l'échec d'authentification (ORT-7031). Reprendre une liaison close impose un nouvel appairage complet.

## 12. Menu « Monitoring » de la console

Un nouveau menu de TRX Console regroupe tout le paramétrage, en suivant la même ergonomie que les menus existants.

1. **Mon identité** : GUID, pseudo, indicatif optionnel, empreinte de clé, régénération des clés (avec avertissement : toutes les liaisons seront à refaire).
2. **Mes destinataires** (j'envoie) : liste avec état (active, en pause, échec, mode A/B), dernier envoi, volume du jour ; par destinataire : profil d'envoi détaillé (cases par catégorie et module, niveaux, fréquences), masquage fréquence/mode, prévisualisation de ce qui part, pause, arrêt.
3. **Mes sources** (je reçois) : liste avec état, dernier battement, quotas, rétention ; pause, arrêt, purge.
4. **Inviter une station** : génération du code et du QR, suivi de l'appairage, comparaison d'empreinte.
5. **Rejoindre avec un code** : saisie du code, comparaison d'empreinte, choix du profil d'envoi.
6. **Alertes** : règles par source, sujet ntfy, heures silencieuses, test d'envoi.
7. **Demandes de diagnostic** : reçues (accepter/refuser) et envoyées (état).
8. **Transport** : activation des modes A et B, port UDP, relais de signalisation, plafonds de débit, test de connectivité avec une source.
9. **Catalogue d'erreurs** : consultation et recherche par code ou mot-clé.

Le tableau de bord texte (trx-monitor, Textual) affiche en plus une ligne « Monitoring » : nombre de liaisons actives en émission et en réception, dernière alerte.

## 13. Page web de consultation

La page est servie par la passerelle existante, en HTTPS, derrière le même login que le client web ; elle est en lecture seule et responsive (smartphone, tablette, ordinateur).

- **Vue d'ensemble** : une carte par source (pseudo, état coloré vert/orange/rouge/gris, dernier battement, version, alertes ouvertes), triée par gravité.
- **Page d'une source** : chronologie des événements avec code, titre, préconisation et lien vers la doc ; graphiques des métriques (système, CAT, audio, réseau) sur 1 h, 24 h, 7 jours, 30 jours ; état des processus et modules.
- **Logs** : filtres par module, niveau, période, code, texte (FTS5) ; suivi en direct ; export JSON et texte d'une sélection.
- **Instantanés** : liste, téléchargement, vue structurée.
- **Ma station vue par les autres** : pour chaque destinataire, aperçu de ce qui lui est envoyé (transparence).
- **Catalogue** : page de recherche dans le catalogue d'erreurs.

Graphiques dessinés localement (bibliothèque embarquée, pas de CDN), pour fonctionner sans accès Internet.

## 14. Architecture logicielle et intégration

Le module est un paquet Python séparé, piloté par le superviseur ; les autres processus lui transmettent leurs données par une file locale, sans dépendre de lui.

```text
openremotetrx/
  errors/
    catalog.yaml          # catalogue du cœur (ORT)
    modules.yaml          # registre des préfixes des modules extérieurs
    codes.py              # constantes générées (script tools/gen_errors.py)
    emit.py               # API emit_event(code, **contexte) pour tous les modules
  monlink/
    __main__.py           # processus trx-monlink
    identity.py           # GUID, clés Ed25519/X25519, empreinte
    pairing.py            # invitations, appairage, révocation
    transport_webrtc.py   # mode A (aiortc, ICE/STUN, data channel)
    transport_udp.py      # mode B (port silencieux, XChaCha20-Poly1305, anti-rejeu)
    reliability.py        # fragmentation, accusés, retransmission, file persistante
    collect.py            # collecte métriques, événements, logs locaux
    redact.py             # masquage obligatoire
    profiles.py           # profils d'envoi par destinataire, expiration
    store.py              # SQLite côté receveur, rétention, quotas
    alerts.py             # règles, dédoublonnage, envoi ntfy
    diag.py               # demandes de diagnostic, tampon DEBUG circulaire
    web.py                # routes de la page web (montées dans la passerelle)
  schemas/monlink/*.json  # JSON Schema des messages (encodage CBOR)
```

Intégration avec l'existant :

- **Collecte locale** : les modules écrivent leurs logs JSON structurés et leurs événements dans un socket local (Unix sous Linux, named pipe sous Windows) lu par `trx-monlink` ; si celui-ci est arrêté, les modules ne bloquent pas (écriture non bloquante, perte acceptée).
- **Superviseur** : lance, surveille et redémarre `trx-monlink` ; ses propres alertes ntfy utilisent désormais les codes du catalogue.
- **Passerelle** : monte les routes web du monitor et réutilise son authentification.
- **Relais de signalisation** : point d'entrée HTTPS sur rf-diy.com partagé avec la présence ; messages signés, durée de vie 5 min, limitation de débit par GUID.
- **Dépendances nouvelles** : PyNaCl, cbor2, zstandard (aiortc déjà présent). À ajouter au wizard d'installation et aux paquets Debian/Windows.
- **Mises à jour** : `monitor_peers.toml` et `monitor_link.db` préservés, comme `station.toml`.

## 15. Tests et critères d'acceptation

Le module est accepté quand deux stations réelles, derrière deux box différentes, échangent dans les deux sens pendant 72 h sans perturber le TRX.

Tests automatisés (pytest, à ajouter à la suite existante) :

- Catalogue : YAML valide, codes uniques, tous les champs présents, aucun texte d'erreur libre dans le code.
- Masquage : un test par règle ; un corpus de logs piégés (mots de passe, IP, URL ntfy) ne doit rien laisser passer.
- Cryptographie : paquet altéré, rejoué, d'une clé inconnue → ignoré sans réponse.
- Appairage : code erroné 5 fois, invitation expirée, empreinte non confirmée, changement de clé.
- Fiabilité : pertes simulées de 20 % et réordonnancement → logs complets et dans l'ordre.
- Quotas, rétention, dédoublonnage et heures silencieuses des alertes.
- Révocation : plus aucune donnée acceptée après la fin de liaison, dans les deux sens.
- Isolation : `trx-monlink` tué ou saturé → passerelle et sécurité PTT inchangées (réutiliser les scénarios de panne existants).

Essais réels :

- [ ] Mode A entre deux box grand public (dont sa Freebox)
- [ ] Bascule en mode B et scan nmap du port UDP : aucune réponse
- [ ] Notification ntfy sur absence de battement (coupure secteur de l'émetteur)
- [ ] Demande de diagnostic acceptée puis expirée
- [ ] Session audio en cours : débit réduit, aucune dégradation audible
- [ ] Station Windows ↔ station Debian

## 16. Découpage en lots et livraison

Six lots, chacun livré par Claude Code en paquet zip d'installation `trx-remote-etapeNN-sujet.zip` avec les commandes habituelles (git add, commit « Avant … », Expand-Archive, pytest) ; numéros d'étape à caler sur la numérotation en cours.

| Lot | Contenu | Dépend de |
| --- | --- | --- |
| M1 — catalogue | `catalog.yaml`, générateur, `emit_event`, registre des modules extérieurs et codes ORT-65xx, migration des erreurs existantes et des alertes du superviseur, logs structurés JSON | — |
| M2 — identité et appairage | GUID, clés, invitations, empreinte, `monitor_peers.toml`, menus console 1, 4, 5 | M1 |
| M3 — transport | mode B d'abord (UDP silencieux, fiabilité, file), puis mode A WebRTC et relais de signalisation | M2 |
| M4 — émission | collecte, masquage, profils, prévisualisation, pause/arrêt, menu console 2 | M3 |
| M5 — réception et alertes | SQLite, quotas, rétention, règles ntfy, menus 3 et 6 | M4 |
| M6 — web et diagnostic | page web, demandes de diagnostic, tampon DEBUG, menu 7, essais réels 72 h | M5 |

Décisions prises :

- **Relais de signalisation** : hébergé sur l'OVH mutualisé de rf-diy.com au départ, mutualisé avec la fonction de présence.
- **Serveur STUN** : serveurs publics en V1 ; serveur auto-hébergé plus tard si openRemoteTRX rencontre le succès. Les stations n'utilisent jamais d'adresse STUN en dur mais un nom sous notre domaine (CNAME, ex. `stun.rf-diy.com`, et `signal.rf-diy.com` pour le relais), pour changer de serveur sans mise à jour des stations.
- **Serveur TURN** : reporté ; les stations en 4G/CGNAT utilisent le mode B ou attendront une version ultérieure.
- **Catalogue** : traduit en anglais dès la bêta.
