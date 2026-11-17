# 9. Fonctions facultatives

Toutes sont **désactivées** au départ. Active-les une fois la station validée (parties 3 à 5) : le menu **5.5**
« Fonctions en service » les met en service ou les arrête d'un numéro (il lance aussi le module de la fonction) ;
une fonction qui demande d'autres réglages est refusée avec le menu où les faire.

| Fonction | À quoi elle sert | Où l'activer |
|---|---|---|
| **Visiteurs** en réception seule | des comptes qui écoutent la station et voient l'écran, sans **aucune** commande (radio-club, démonstration) | menu 4.2, puis le commutateur « Écoute des visiteurs » de la page |
| **Cluster DX** | spots sur le spectre et pastilles sur les boutons de bande | menu 5.1 |
| **FreeDV** RADE V1 (réception) | voix numérique FreeDV décodée par la station | décodeurs à compiler (`sudo bash compiler-freedv.sh` dans le dossier du paquet Debian), puis menu 5.5 (« FreeDV en réception ») ; le locator de l'activité FreeDV : `[freedv] locator` (menu 8.1) |
| **SELCALL** | squelch par appel de groupe en BLU | menu 5.5, puis la rubrique SELCALL de la page |
| **Mesure de TOS** | courbe de TOS de l'antenne sur une bande, en FM, puissance réduite | page web ou application ; la station émet : bandes autorisées seulement |
| **Présence de groupe** | voir quels amis équipés d'openRemoteTRX sont en QSO, et les rejoindre | menu 5.3 |
| **Monitoring entre stations** | être aidé à distance par quelqu'un de confiance, ou aider un autre opérateur : état de la station et codes d'erreur, masqués et chiffrés, sans VPN ni port ouvert ; aucune commande possible vers la station aidée | menu 5.5 (« Monitoring entre stations »), puis menu 6.5 ou rubrique « Monitoring » de la page (partie 8.3) |
| **Breizh Audio Box** | traitement de la voix sur un autre PC du réseau local | menu 5.2 |
| **Diffusion en direct** | faire entendre le son du poste à quelques **auditeurs** sur Internet, sans compte sur la station : ils écoutent sur la page d'un serveur de diffusion (canal privé avec identifiant et mot de passe, ou public) ; indicateur **DIFFUSION** toujours visible dans la page ; ta voix pendant tes émissions n'est diffusée que si tu le demandes ; hors de tes bandes, silence pour les auditeurs (sauf réglage contraire) ; alerte sur le téléphone au début et à la fin | menu 5.6 (serveur et secrets donnés par l'administrateur du serveur), menu 5.5 (« Diffusion en direct »), puis menu 5.6 ou rubrique « Diffusion en direct » de la page pour lancer et arrêter |
| **Rediffusion** d'un enregistrement | renvoyer en émission un enregistrement de la réception | accordée à l'assistant ; en général **interdite** au service amateur |
| **Récepteur SDR** (SDRplay) | second waterfall et écoute (AM, FM, BLU, CW) d'un SDR en réception seule, à côté du TRX ; son du SDR coupé pendant toute émission ; balance TRX / SDR et, au casque, une source par oreille ; zoom du waterfall (« Zoom − / + » autour de la fréquence écoutée, ◄ ► pour déplacer la fenêtre), palette de couleurs, largeur (au plus celle choisie au menu 2.4) et antenne A / B depuis la page ; spots du Cluster DX sur le waterfall du SDR (toucher un spot : le SDR l'écoute, le TRX ne bouge pas) ; la station ralentit ou suspend le SDR toute seule si elle est trop chargée ; SDR choisi et réglé au menu 2.4 de TRX Console (recherche sur tous les ports USB et hubs) ; « QSY du TRX » vers une fréquence lue sur le SDR | installer d'abord l'API SDRplay du fabricant, puis la station ; `trx-sdr --list` donne le numéro de série ; `[sdr]` et « sdr » dans `[modules] run` (menu 8.1) |

> **Récepteur SDR : protège son entrée.** Le SDR ne supporte pas la puissance de ton TRX. Antenne séparée, ou
> commutateur et séquenceur qui mettent l'entrée du SDR à la masse avant toute émission : c'est à toi de le prévoir,
> selon ton matériel. La station ne peut pas le faire à ta place (une émission au micro du poste n'est vue qu'après
> coup). Le SDR se désigne par son **numéro de série** : sur une machine qui en a plusieurs, ne mets jamais celui
> d'un SDR utilisé par une autre application. Branche-le sur son propre port USB, jamais sur le hub du poste.

> **Sécurité.** Retransmettre à des tiers ce que la station reçoit (visiteurs, auditeurs de la diffusion)
> engage ta responsabilité, surtout hors des bandes radioamateur ; par défaut, visiteurs et auditeurs n'entendent
> que du silence hors de tes bandes (deux réglages indépendants).

Avec le FTDX10, deux fonctions de la page restent indisponibles : le **spectre HF du poste** (seul le spectre audio
s'affiche) et les **préréglages de filtre FIL1/2/3** (propres aux Icom).
