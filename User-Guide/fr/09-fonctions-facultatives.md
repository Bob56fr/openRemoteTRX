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
| **Récepteur SDR** (SDRplay) | second waterfall et écoute (AM, FM, BLU, CW) d'un SDR en réception seule, à côté du TRX ; son du SDR coupé pendant toute émission ; balance TRX / SDR et, au casque, une source par oreille ; zoom du waterfall (« Zoom − / + » autour de la fréquence écoutée, ◄ ► pour déplacer la fenêtre) ; la station ralentit ou suspend le SDR toute seule si elle est trop chargée ; SDR choisi et réglé au menu 5.4 de TRX Console (recherche sur tous les ports USB et hubs) ; « QSY du TRX » vers une fréquence lue sur le SDR | installer d'abord l'API SDRplay du fabricant, puis la station ; `trx-sdr --list` donne le numéro de série ; `[sdr]` et « sdr » dans `[modules] run` (menu 3.2) |

> **Récepteur SDR : protège son entrée.** Le SDR ne supporte pas la puissance de ton TRX. Antenne séparée, ou
> commutateur et séquenceur qui mettent l'entrée du SDR à la masse avant toute émission : c'est à toi de le prévoir,
> selon ton matériel. La station ne peut pas le faire à ta place (une émission au micro du poste n'est vue qu'après
> coup). Le SDR se désigne par son **numéro de série** : sur une machine qui en a plusieurs, ne mets jamais celui
> d'un SDR utilisé par une autre application. Branche-le sur son propre port USB, jamais sur le hub du poste.

> **Sécurité.** Retransmettre à des tiers ce que la station reçoit (visiteurs) engage ta responsabilité, surtout
> hors des bandes radioamateur ; par défaut, les visiteurs n'entendent que du silence hors de tes bandes.

Avec le FTDX10, deux fonctions de la page restent indisponibles : le **spectre HF du poste** (seul le spectre audio
s'affiche) et les **préréglages de filtre FIL1/2/3** (propres aux Icom).
