# 9. Fonctions facultatives

Toutes sont **désactivées** au départ. Active-les une fois la station validée (parties 3 à 5).

| Fonction | À quoi elle sert | Où l'activer |
|---|---|---|
| **Visiteurs** en réception seule | des comptes qui écoutent la station et voient l'écran, sans **aucune** commande (radio-club, démonstration) | menu 4.2, puis le commutateur « Écoute des visiteurs » de la page |
| **Cluster DX** | spots sur le spectre et pastilles sur les boutons de bande | menu 5.1 |
| **FreeDV** RADE V1 (réception) | voix numérique FreeDV décodée par la station | décodeurs à compiler (`sudo bash compiler-freedv.sh` dans le dossier du paquet Debian), puis `[freedv]` (menu 3.2) |
| **SELCALL** | squelch par appel de groupe en BLU | `[selcall] enabled = true` (menu 3.2), puis la rubrique SELCALL de la page |
| **Mesure de TOS** | courbe de TOS de l'antenne sur une bande, en FM, puissance réduite | page web ou application ; la station émet : bandes autorisées seulement |
| **Présence de groupe** | voir quels amis équipés d'openRemoteTRX sont en QSO, et les rejoindre | menu 5.3 |
| **Breizh Audio Box** | traitement de la voix sur un autre PC du réseau local | menu 5.2 |
| **Rediffusion** d'un enregistrement | renvoyer en émission un enregistrement de la réception | accordée à l'assistant ; en général **interdite** au service amateur |

> **Sécurité.** Retransmettre à des tiers ce que la station reçoit (visiteurs) engage ta responsabilité, surtout
> hors des bandes radioamateur ; par défaut, les visiteurs n'entendent que du silence hors de tes bandes.

Avec le FTDX10, deux fonctions de la page restent indisponibles : le **spectre HF du poste** (seul le spectre audio
s'affiche) et les **préréglages de filtre FIL1/2/3** (propres aux Icom).
