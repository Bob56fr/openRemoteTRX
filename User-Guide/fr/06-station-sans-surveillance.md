# 6. Une station sans surveillance

Une station pilotée à distance fonctionne la plupart du temps sans personne à côté. Cette partie prépare ce cas.

## 6.1 Les alertes sur ton téléphone (ntfy)

Le superviseur de la station peut t'envoyer des notifications : émission coupée par sécurité, panne, mise en sécurité,
mémoire ou disque presque plein, coupure de la liaison, et un message « Station en service » sans sonnerie toutes
les heures (s'il n'arrive plus, la station ou sa connexion est en panne).

1. Installe l'application **ntfy** sur le téléphone.
2. Choisis un **nom de sujet long et impossible à deviner** (par exemple 20 lettres et chiffres au hasard) :
   sur le serveur public ntfy.sh, quiconque connaît le nom lit les messages.
3. Abonne-toi à ce sujet dans l'application ntfy.
4. Sur la station, menu **3.5** « Alertes sur le téléphone » : choix 1, colle l'adresse
   `https://ntfy.sh/<ton-sujet>`, enregistre, accepte le redémarrage. L'écran ne montre jamais l'adresse en entier.
5. Vérifie : choix 4, « Envoyer une alerte d'essai » ; le téléphone doit sonner tout de suite (code ORT-8025).
   Ensuite, le message « Station en service » arrive toutes les heures (choix 3 pour changer ce rythme).

Chaque alerte porte un code « ORT-NNNN » avec un lien vers son explication (partie 8).

## 6.2 La mise en sécurité

Après des pannes répétées que les relances n'ont pas réglées, le superviseur **met la station en sécurité** : poste
en réception, accès coupé, alerte envoyée. La mise en sécurité **survit aux redémarrages** : il faut trouver la cause
(menus 6.1 et 6.2), puis le lever par le menu **1.4**.

## 6.3 Après une coupure de courant

| Élément | À régler |
|---|---|
| PC | dans le BIOS / UEFI : « Restore on AC power loss » = **Power On** (le nom varie selon la carte mère) |
| Station Debian | rien : elle démarre avec le PC, sans ouvrir de session |
| Station Windows | elle démarre à l'**ouverture de session** : sans connexion automatique de ta session, elle reste arrêtée |
| Poste | la plupart des postes ne se rallument **pas** seuls. La station sait l'allumer par la CAT (menu **2.8**, hors service par défaut, avec un essai éteindre / rallumer) : ta connexion depuis la page ou l'application le rallume |
| Box | se rallume seule ; vérifie que le VPN aussi |

Un **onduleur** pour le PC, la box et l'alimentation du poste évite la plupart de ces cas.

## 6.4 Protections du matériel

- **Foudre** : une station isolée de toute présence humaine est exposée. Parafoudre sur le câble d'antenne, et
  antenne mise à la terre ou déconnectée en cas d'orage prévu.
- **Puissance** : le plafond du poste (HF MAX POWER, partie 1) reste la dernière barrière.
- **Minuteur du poste** (TX TIME OUT TIMER) : réglé à 3 min, il coupe même si tout le reste a lâché.
- **Température** : le superviseur surveille le processeur du PC et alerte au-delà de 70 °C. Celle du poste n'est
  pas lisible par la station sur les postes essayés (IC-7300MK2, FTDX10) : ventilation correcte autour du poste.
- **Opérateur sur place** : si quelqu'un utilise le poste sur place, l'émission à distance est bloquée pendant
  son émission puis 2 minutes ; la station ne le coupe jamais pour ce motif. Une émission au micro est coupée par
  le TOT absolu (135 s), sauf si l'opérateur a touché le poste (volume, fréquence, mode, sortie du mode DATA…) dans
  les 2 minutes avant de parler ou pendant qu'il parle : la station le sait présent et le laisse parler jusqu'à
  5 minutes (`local_tx_max_s`), avec une simple alerte entre les deux. Le minuteur du poste, s'il est réglé plus
  court, coupe avant. Ces réglages sont au menu **3.4** « Opérateur sur place » : gardez « station partagée » ;
  sinon, un micro tenu enfoncé mène à la mise en sécurité.
