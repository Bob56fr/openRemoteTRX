# 3. Intégrer le TRX et l'essayer

> **Sécurité.** Pendant toute cette partie : **charge fictive** sur la prise d'antenne, **puissance réduite**
> (10 W par exemple), personne à proximité de l'antenne débranchée.

## 3.1 L'assistant de configuration (menu 3.1)

Le poste n'est interrogé qu'**en lecture** : aucune émission pendant l'assistant. Rien n'est enregistré si tu
abandonnes en cours de route. Réponses pour le FTDX10 :

| Question | Réponse |
|---|---|
| Modèle du poste | **1042** (Yaesu FTDX10). L'assistant affiche alors la liste des menus du poste à vérifier (partie 1) |
| Port série du CAT | le port **Enhanced** (Debian : proposé d'office ; Windows : le COM noté à la partie 1) |
| Débit | **38400** (identique à CAT RATE du poste) |
| Méthode de PTT | **CAT** (proposée) |
| La voix part-elle par l'USB ? | **oui**, si MOD SOURCE = REAR et REAR SELECT = USB sont réglés ; sinon l'émission sera limitée aux modes données |
| Cartes son (réception, émission) | « USB Audio CODEC » pour les deux |
| Spectre HF par un second port | **aucun** (le FTDX10 n'envoie pas son spectre) |
| Bandes autorisées à l'émission | les bandes de **ta licence**, seulement. Liste vide = réception seule |
| Accès réseau | « **Réseau local ou VPN, en HTTPS avec un certificat généré ici** » (recommandé) |
| Comptes | un identifiant (lettres, chiffres, `_`, `-`) et un **mot de passe long** (Entrée = un mot de passe fort est généré : note-le) ; Entrée sur un identifiant vide pour terminer |
| Puissance maximale du poste | **100** (watts) |
| Durée maximale d'une émission (TOT) | **90** secondes (valeur par défaut, plafond 120) |
| Rediffusion d'enregistrements | **non** (réponse par défaut) |

L'assistant affiche à la fin l'adresse à ouvrir (`https://<adresse-de-la-station>:8443`) et l'**empreinte du
certificat** (utile pour l'application Android, partie 4).

## 3.2 Le diagnostic (menu 2.1)

Il passe tout en revue sans rien modifier : chaque ligne est **OK**, à **surveiller** ou en **échec**, avec la
marche à suivre. Corrige chaque échec avant d'aller plus loin (menu 3.2 pour un réglage, ou relance l'assistant).

Échecs fréquents à ce stade : mauvais port (Standard au lieu d'Enhanced), CAT RATE du poste différent de 38400,
carte son du poste prise par le bureau (partie 1.4).

## 3.3 L'essai guidé du poste (menu 2.2)

La station est arrêtée pendant l'essai.

1. **Choix 1, réception seule** : liaison CAT, son reçu, changement de fréquence et de mode, largeurs de filtre.
   Écoute que le son reçu est propre et à un niveau correct (sinon : OUT LEVEL du mode, fiche du poste).
2. **Choix 2, réception puis émission** : charge fictive, puissance réduite. Chaque passage en émission demande de
   taper `EMETTRE`.

Copie le **résumé final** affiché à l'écran : il sert au rapport de validation.

## 3.4 Démarrer la station et régler la modulation

1. Menu **1.1** : la station démarre (le poste est toujours remis en réception au démarrage). Refais un diagnostic
   (menu 2.1) quelques secondes plus tard.
2. Ouvre la page `https://<adresse-de-la-station>:8443` depuis un téléphone ou un PC du réseau (détails et
   avertissement du certificat : partie 4), connecte-toi.
3. Bande autorisée, mode USB ou LSB, charge fictive : appuie sur le **PTT** (bascule : un appui pour émettre, un
   appui pour revenir en réception), parle normalement quelques secondes, appuie de nouveau.
4. Regarde l'**ALC** dans la page : il doit bouger sur les pointes de voix sans rester au maximum. Ajuste
   **RPORT GAIN** sur le poste (menu du mode utilisé) jusqu'à obtenir ce résultat.

## 3.5 Les essais de sécurité

Fais-les **tous**, sur charge fictive, avant toute émission sur antenne. Chacun doit se terminer par le retour du
poste en réception (vérifie sur l'écran du poste, pas seulement dans la page).

| # | Essai | Résultat attendu |
|---|---|---|
| 1 | Pendant une émission, bouton **STOP** de la page | retour en réception immédiat |
| 2 | Émettre sans rien toucher | compte à rebours et bip 10 s avant la fin, retour en réception au bout de **90 s** |
| 3 | Pendant une émission, couper le Wi-Fi du téléphone (ou fermer l'onglet) | retour en réception en **2 s** environ |
| 4 | Pendant une émission depuis le téléphone, verrouiller l'écran | retour en réception |
| 5 | Régler une fréquence hors de tes bandes autorisées, appuyer sur PTT | émission **refusée**, message dans la page |
| 6 | Émettre **au micro du poste** (sans la station) | la page affiche l'opérateur sur place et bloque le PTT à distance pendant l'émission puis 2 minutes |
| 7 | Pendant une émission, touche **STOP TX** du tableau de bord (menu 1.3) | retour en réception |
| 8 | Pendant une émission, arrêter la station (menu 1.2) | retour en réception |
| 9 | Redémarrer le PC, poste allumé | le poste ne passe **jamais** en émission pendant le démarrage |

Un essai qui ne donne pas le résultat attendu : **n'utilise pas la station en émission**, arrête-la (menu 1.2) et
demande de l'aide (partie 8) avec le rapport du menu 2.3.

## 3.6 Pour aller plus loin (facultatif)

- **Qualification du poste** (menu 2.7, `trx-qualif`) : pour un expert qui veut tout vérifier de ce que Hamlib
  déclare pour le FTDX10. Commence par le choix 2 (exploration sans émission) ; le rapport produit est précieux pour
  valider la fiche du poste.
- **Profil de poste** (menu 3.3) : enregistre la configuration sous un nom (« FTDX10 maison ») pour la recharger plus
  tard si tu changes de poste.

## 3.7 Rapporter la validation

Le FTDX10 n'ayant jamais été essayé avec la station, ton résultat compte : ouvre un ticket « Signaler un bug » en
français (même si tout va bien, titre « FTDX10 : essais de mise en service ») avec le résumé de l'essai guidé, le
résultat des 9 essais de sécurité et les points de la [fiche du poste](postes/ftdx10.md), section « Points à
vérifier ».
