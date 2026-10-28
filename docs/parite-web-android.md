# Parité page web / application Android

Une ligne par fonction visible. Toute livraison qui ajoute ou modifie une fonction met sa ligne à jour (règle : `docs/protocole.md` § 11, `docs/android-cahier-des-charges.md` § 8).
État : **fait**, **à faire (lot)**, **absent volontairement** (avec la raison). Mot de `hello.features` entre parenthèses quand la station peut ne pas l'offrir.

| Fonction | Station | Page web | Application | Remarque |
|---|---|---|---|---|
| Connexion, mot de passe, reconnexion automatique | fait | fait | fait (A1, 0.1.0) | plusieurs stations ; mot de passe mémorisé chiffré (Keystore) au choix ; HTTPS seulement |
| Certificat épinglé par empreinte | fait (menu 19, `--empreinte`) | absent volontairement | fait (A1) | la page dépend du navigateur ; QR code d'appairage : fait (station 0.53.0, menu 19 ; application 0.2.0) |
| Écoute, volume, sourdine | fait | fait | fait (A1) | volume = touches « média » du téléphone |
| Écoute écran éteint | fait | impossible (navigateur) | fait (A1), 30 min à confirmer sur le téléphone | raison d'être de l'application |
| PTT toggle, STOP, battements, TOT | fait | fait | fait (A1) | « Émission autorisée » comme la case de la page |
| Sons de liaison (perdue, rétablie, abandon) | — | fait | fait (A1) | mêmes notes, vibrations ; réglage du volume : plus tard |
| Notification permanente avec STOP | — | absent (navigateur) | fait (A1) | |
| Appel entrant pendant l'émission => STOP | — | absent (navigateur) | fait (A1), à essayer sur le téléphone | perte du focus audio |
| Opérateur sur place, « Reprendre la main » | fait | fait | fait (A1) | champs dans `state.ptt` depuis 0.52.0 |
| Alerte de température | fait | fait | fait (A1, bandeau) | |
| Fréquence, bandes, clavier | fait | fait | fait (0.3.0) : saisie au clavier, crans −/+ et pas, 14 bandes avec mémoire de bande | mêmes règles (tests : bandes et pas comparés à client.js) ; glisser par chiffre : plus tard |
| Modes, filtres | fait | fait | modes fait (0.3.0, modes d'émission rappelés ; ordre USB-D, LSB-D, AM-D, FM-D, CW puis les autres depuis 0.3.1) ; filtres à faire (A3) | bande => mode données si `tx_modes` l'exige ; ordre des modes de la page : à aligner si l'utilisateur le veut |
| S-mètre, Po, SWR, ALC | fait | fait | S-mètre en barre et en texte (0.3.0) ; Po, SWR, ALC à faire (A3) | |
| Fonctions et niveaux du poste (NR NB P.AMP AGC COMP TUNER ATT…) | fait | fait | à faire (A3) | |
| Mémoires partagées (`memories`) | fait | fait | liste et rappel faits (0.3.0) ; édition à faire (A3) | présélections d'Android Auto (A2) |
| Bips de fin (`beeps`) | fait | fait | à faire (A3) | |
| Rapport de problème (`bug_report`) | fait | fait | à faire (A3) | |
| Android Auto, commande vocale, touches du volant | — | absent volontairement | à faire (A2) | |
| Mode conduite | — | absent | à faire (A3) | |
| Waterfall audio | — | fait | plus tard (A4) | |
| Spectre HF (`spectrum`) | fait | fait | plus tard (A4) | |
| Spots du cluster DX | fait | fait | plus tard (A4) | |
| Mises en page du designer (`layouts`) | fait | fait | plus tard (A4), peut-être jamais | |
| Thèmes de couleurs | — | fait | plus tard (A4) | |
