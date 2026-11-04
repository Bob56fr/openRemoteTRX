# Breizh Audio Box dans la chaîne d'émission : cahier des charges v0 (décisions)

v0 du 2026-11-04 : demande et décisions de l'utilisateur, avant rédaction complète (v1) dans une conversation dédiée.
EXCEPTION de l'utilisateur au gel de la page et de l'application (2026-11-04).

## 1. Demande

Le son du micro du client (page, application) passe par Breizh Audio Box (traitement de la voix) avant d'aller au
poste. Les deux logiciels tournent sur le MÊME RÉSEAU LOCAL, pas forcément sur le même PC. Si Breizh disparaît,
remoteTRX annule le routage et repasse en mode autonome.

## 2. Principe retenu

```
client (micro) → Opus → passerelle : décodage → [Breizh par le réseau local] → volume retour → limiteur final → porte audio d'émission → poste
```

- Son brut 48 kHz mono par UDP, blocs de 256 échantillons numérotés (~1,5 Mbit/s). Breizh renvoie UN bloc par bloc
  reçu, sans carte son de son côté (pas de dérive d'horloge entre les deux PC). Latence ajoutée visée : 10 à 20 ms.
- Côté openRemoteTRX : client du protocole dans la passerelle ; un FAUX BREIZH (renvoi tel quel ou gain) pour les
  tests. Côté Breizh : serveur du protocole (son lot V2), conversation à part dans son dépôt.
- Le protocole réseau est figé et documenté ICI avant le codage des deux côtés.

## 3. Décisions de l'utilisateur (2026-11-04)

1. **Sécurité du flux** : appairage par clé partagée, chaque bloc authentifié (HMAC), un seul hôte Breizh autorisé
   (déclaré dans `station.toml`), seule la réponse à un bloc réellement envoyé est acceptée. Le micro circule en clair
   sur le réseau local : à dire dans la notice.
2. **Breizh ne touche jamais au PTT ni à la porte d'émission** : la porte audio d'émission est APRÈS le retour de
   Breizh ; limiteur final de la station toujours actif. Côté Breizh : onglet « OpenRemoteTRX » dans les réglages
   (paramètres d'appairage, activation du mode) ; ce mode activé COUPE le CAT de Breizh et GRISE son onglet CAT
   (Breizh ne peut alors plus faire passer le poste en émission).
3. **Roger bip** : reste à remoteTRX (exception des bips de fin, `docs/bips.md`).
4. **Breizh disparu (plus de retour pendant ~100 ms)** : option A, repli IMMÉDIAT en direct à gain réduit, opérateur
   prévenu, mode autonome conservé. Pas de réactivation automatique hâtive : attente suffisamment longue, OU
   réactivation demandée par l'utilisateur depuis la page et l'application. Un JOURNAL de connexion / reconnexion
   dans l'onglet dédié (page, application).
5. **Effets du client coupés** quand Breizh est actif (annoncé par `hello`) : égaliseur, chorus, réverbération en
   bypass ; le limiteur du client reste.
6. **Scrambler d'émission et Breizh EXCLUSIFS** (le scrambler brouille dans le client, avant Breizh).
7. **Volume retour** : réglage borné (−20 à +6 dB) appliqué à la station après Breizh, réglable depuis la page et
   l'application.
8. **Exception au gel** de la page et de l'application : accordée.

## 4. À écrire dans la v1

Protocole (messages, appairage, battement, numérotation, HMAC, versions), réglages de `station.toml` (hôte, clé,
délais), commandes et champs du protocole client (`docs/protocole.md`, `hello.features`), tests de panne (Breizh
absent, gelé, trop lent, paquets falsifiés ou rejoués, perte pendant une émission), lots de codage.
