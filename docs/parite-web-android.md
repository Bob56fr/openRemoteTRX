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
| S-mètre, Po, SWR, ALC | fait | fait | fait (S-mètre 0.3.0 ; Po, SWR, ALC pendant l'émission, COMP, Vd, température : 0.4.0) | SWR >= 2 et ALC >= 90 % en orange |
| Fonctions et niveaux du poste (NR NB P.AMP AGC COMP TUNER ATT…) | fait | fait | boutons faits (0.4.0 : NR, NB, P.AMP, ATT, NOTCH, IP+, AGC, COMP, FIL, TUNER, PWR, mêmes cycles que la page)  ; squelch et niveaux NR/NB faits (0.5.0) | verrouillés pendant l'émission ; une commande à la fin du geste |
| Mémoires partagées (`memories`) | fait | fait | fait (liste et rappel 0.3.0 ; création, modification, favori, suppression en deux temps 0.5.0) | présélections d'Android Auto (A2) |
| Bips de fin (`beeps`) | fait | fait | à faire (A3) | |
| Rapport de problème (`bug_report`) | fait | fait | à faire (A3) | |
| Android Auto, commande vocale, touches du volant | — | absent volontairement | à faire (A2) | |
| Mode conduite | — | absent | à faire (A3) | |
| Waterfall audio | — | fait | fait (0.7.0 : même analyse que la page, FFT 4096 Blackman, lissage 0,35, -85 à -30 dBFS ; VIT, LARG, GAIN, PIC) | calcul sur le téléphone, seulement pendant l'affichage |
| Spectre HF (`spectrum`) | fait | fait | fait (0.6.0 : courbe, waterfall, repère, graduations, toucher = accorder, glisser = VFO, span / mode / vitesse / REF du poste, gain et plage) | trames : exemples partagés `tests/protocol/spectrum.json` ; vue intégrée en paysage (page : dock) : plus tard |
| Spots du cluster DX | fait | fait | plus tard (A4) | |
| Mises en page du designer (`layouts`) | fait | fait | plus tard (A4), peut-être jamais | |
| Thèmes de couleurs | — | fait | plus tard (A4) | |
| VFO A / B, split, clarifieur (RIT / XIT) | à faire (sécurité : en split, la bande d'émission est celle du VFO d'émission) | à faire | à faire | demandé le 2026-10-29 ; protocole à étendre (`docs/protocole.md`) |
| Commande vocale « QSY 27 555 » (confirmation sur le téléphone) | — | absent | à étudier (bouton micro ou écoute permanente) | demandé le 2026-10-29 ; jamais en émission, fréquence seulement |
