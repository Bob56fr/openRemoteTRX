# Parité page web / application Android

Une ligne par fonction visible. Toute livraison qui ajoute ou modifie une fonction met sa ligne à jour (règle : `docs/protocole.md` § 11, `docs/android-cahier-des-charges.md` § 8).
État : **fait**, **à faire (lot)**, **absent volontairement** (avec la raison). Mot de `hello.features` entre parenthèses quand la station peut ne pas l'offrir.

| Fonction | Station | Page web | Application | Remarque |
|---|---|---|---|---|
| Connexion, mot de passe, reconnexion automatique | fait | fait | à faire (A1) | |
| Certificat épinglé par empreinte | fait (menu 19, `--empreinte`) | absent volontairement | à faire (A1) | la page dépend du navigateur |
| Écoute, volume, sourdine | fait | fait | à faire (A1) | |
| Écoute écran éteint | fait | impossible (navigateur) | à faire (A1) | raison d'être de l'application |
| PTT toggle, STOP, battements, TOT | fait | fait | à faire (A1) | |
| Sons de liaison (perdue, rétablie, abandon) | — | fait | à faire (A1) | |
| Notification permanente avec STOP | — | absent (navigateur) | à faire (A1) | |
| Appel entrant pendant l'émission => STOP | — | absent (navigateur) | à faire (A1) | |
| Opérateur sur place, « Reprendre la main » | fait | fait | à faire (A3) | champs dans `state.ptt` depuis 0.52.0 |
| Alerte de température | fait | fait | à faire (A3) | |
| Fréquence, bandes, clavier | fait | fait | à faire (A3) | cas d'essai à partager (saisie, bandes) |
| Modes, filtres | fait | fait | à faire (A3) | |
| S-mètre, Po, SWR, ALC | fait | fait | à faire (A3) | |
| Fonctions et niveaux du poste (NR NB P.AMP AGC COMP TUNER ATT…) | fait | fait | à faire (A3) | |
| Mémoires partagées (`memories`) | fait | fait | à faire (A2 lecture, A3 édition) | présélections d'Android Auto |
| Bips de fin (`beeps`) | fait | fait | à faire (A3) | |
| Rapport de problème (`bug_report`) | fait | fait | à faire (A3) | |
| Android Auto, commande vocale, touches du volant | — | absent volontairement | à faire (A2) | |
| Mode conduite | — | absent | à faire (A3) | |
| Waterfall audio | — | fait | plus tard (A4) | |
| Spectre HF (`spectrum`) | fait | fait | plus tard (A4) | |
| Spots du cluster DX | fait | fait | plus tard (A4) | |
| Mises en page du designer (`layouts`) | fait | fait | plus tard (A4), peut-être jamais | |
| Thèmes de couleurs | — | fait | plus tard (A4) | |
