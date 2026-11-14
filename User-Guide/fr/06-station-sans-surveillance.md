# 6. Une station sans surveillance

Une station pilotée à distance fonctionne la plupart du temps sans personne à côté. Cette partie prépare ce cas.

## 6.1 Les alertes sur ton téléphone (ntfy)

Le superviseur de la station peut t'envoyer des notifications : émission coupée par sécurité, panne, mode sûr,
mémoire ou disque presque plein, coupure de la liaison, et un message « Station en service » sans sonnerie toutes
les heures (s'il n'arrive plus, la station ou sa connexion est en panne).

1. Installe l'application **ntfy** sur le téléphone.
2. Choisis un **nom de sujet long et impossible à deviner** (par exemple 20 lettres et chiffres au hasard) :
   sur le serveur public ntfy.sh, quiconque connaît le nom lit les messages.
3. Abonne-toi à ce sujet dans l'application ntfy.
4. Sur la station, menu **3.2**, section `[supervisor]` : `notify_url = "https://ntfy.sh/<ton-sujet>"`. Redémarre
   la station (menu 1.1).
5. Vérifie : le message « Station en service » arrive dans l'heure.

Chaque alerte porte un code « ORT-NNNN » avec un lien vers son explication (partie 8).

## 6.2 Le mode sûr

Après des pannes répétées que les relances n'ont pas réglées, le superviseur met la station en **mode sûr** : poste
en réception, accès coupé, alerte envoyée. Le mode sûr **survit aux redémarrages** : il faut trouver la cause
(menus 2.1 et 1.4), puis le lever par le menu **1.5**.

## 6.3 Après une coupure de courant

| Élément | À régler |
|---|---|
| PC | dans le BIOS / UEFI : « Restore on AC power loss » = **Power On** (le nom varie selon la carte mère) |
| Station Debian | rien : elle démarre avec le PC, sans ouvrir de session |
| Station Windows | elle démarre à l'**ouverture de session** : sans connexion automatique de ta session, elle reste arrêtée |
| Poste | le FTDX10 ne se rallume **pas** seul ; la station ne sait pas (encore) l'allumer à distance |
| Box | se rallume seule ; vérifie que le VPN aussi |

Un **onduleur** pour le PC, la box et l'alimentation du poste évite la plupart de ces cas.

## 6.4 Protections du matériel

- **Foudre** : une station isolée de toute présence humaine est exposée. Parafoudre sur le câble d'antenne, et
  antenne mise à la terre ou déconnectée en cas d'orage prévu.
- **Puissance** : le plafond du poste (HF MAX POWER, partie 1) reste la dernière barrière.
- **Minuteur du poste** (TX TIME OUT TIMER) : réglé à 3 min, il coupe même si tout le reste a lâché.
- **Température** : le superviseur surveille le processeur du PC et alerte au-delà de 70 °C. Celle du FTDX10 n'est
  pas lisible par la station : ventilation correcte autour du poste.
- **Opérateur sur place** : si quelqu'un utilise le poste sur place, l'émission à distance est bloquée pendant
  son émission puis 2 minutes ; la station ne le coupe jamais pour ce motif.
