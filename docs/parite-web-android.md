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
| Bips de fin (`beeps`) | fait | fait | fait (0.13.0 : roger, tonalité, motif, liaison perdue avec confirmation, Écouter) | |
| Rapport de problème (`bug_report`) | fait | fait | à faire (A3) | |
| Android Auto, commande vocale, touches du volant | — | absent volontairement | touches du volant et bouton du casque : fait (0.13.0, désactivé par défaut) ; Android Auto et voix : fait (0.21.0, non essayé en voiture) | prendre l'émission : voiture et application seulement ; voix : jamais d'émission |
| Mode conduite | — | absent | à faire (A3) | |
| Waterfall audio | — | fait | fait (0.7.0 : même analyse que la page, FFT 4096 Blackman, lissage 0,35, -85 à -30 dBFS ; VIT, LARG, GAIN, PIC) | calcul sur le téléphone, seulement pendant l'affichage |
| Spectre HF (`spectrum`) | fait | fait | fait (0.6.0 : courbe, waterfall, repère, graduations, toucher = accorder, glisser = VFO, span / mode / vitesse / REF du poste, gain et plage) | trames : exemples partagés `tests/protocol/spectrum.json` ; vue intégrée en paysage (page : dock) : plus tard |
| Spots du cluster DX | fait | fait | fait (0.8.0 : étiquettes sur le spectre en paysage, « +N », fiche, QSY ; 0.10.0 : voyant de santé, SPOTS, LISTE triée, VFO = accord au doigt) | |
| Mises en page du designer (`layouts`) | fait | fait | plus tard (A4), peut-être jamais | |
| Thèmes de couleurs | — | fait | thème par défaut de la page repris (0.12.0) ; choix du thème (Icom, Yaesu, Kenwood) : plus tard | |
| Split, RIT, ΔTX / XIT : lecture, boutons RIT et ΔTX, curseur du décalage | fait (0.55.0 : `split`, `tx_frequency_hz`, `offsets`, `set_offset` ; bande vérifiée sur la fréquence d'ÉMISSION) | fait (boutons, curseur sous le squelch) ; voyants : à faire | fait (0.11.0 : voyants RIT, ΔTX, SPLIT, boutons, curseur) | |
| VFO actif (A, B, mémoire) | non lisible sur l'IC-7300MK2 (`get_vfo` : RPRT -11) ; second port CI-V à étudier | — | — | voyant absent plutôt que deviné |
| Commande vocale « QSY 27 555 » (confirmation sur le téléphone) | — | absent | à étudier (bouton micro ou écoute permanente) | demandé le 2026-10-29 ; jamais en émission, fréquence seulement |
| Bandes préférées (choix et ordre des boutons de bande) | — (réglage de l'appareil) | à faire (étape suivante) | fait (0.8.0 : ✎ au bout des bandes) | demandé le 2026-10-29 ; aucune cochée = toutes |
| Spectre HF en plein écran en tournant le téléphone (paysage), waterfall audio en portrait | — | page : vue HF plein écran / intégrée en paysage large | fait (0.8.0) | STOP et état de l'émission toujours visibles en paysage |
| Zoom à deux doigts sur le spectre HF (span du poste) | fait (spectrum_set) | absent | fait (0.9.0) | passe en mode CENT si besoin |
| NB : largeur et profondeur (en plus de marche/arrêt et niveau) | à faire : Hamlib ne les expose PAS pour l'IC-7300MK2 (dump_caps : NB 0..10 seul, aucun « Extra level ») ; possible par le second port CI-V (comme FIL1/2/3), à confirmer sur le poste | à faire | à faire | demandé le 2026-10-29 |
| Voyants de l'afficheur : ATT ou P.AMP 1 / P.AMP 2 (ou rien), RIT, ΔTX, SPLIT, NOTCH, NB, NR (VFO-A / VFO-B / MEM : non lisible) | — | à faire | fait (0.11.0) | vert = actif, gris = éteint ; précisé par l'utilisateur le 2026-10-29 |
| Bargraphs POWER, SWR, ALC toujours visibles dans l'afficheur | — | fait (graphiques de puissance) | fait (0.10.1) | à zéro en réception |
| Pastilles de spots sur les boutons de bande, rubrique « Cluster DX » (état des flux) | fait (`cluster_status`) | fait | fait (0.12.0) | spots actifs seulement (moins de 15 min) |
| Quitter l'application pendant l'émission => retour en réception (réglage « rester en émission », désactivé par défaut) | — | absent (navigateur : la page en arrière-plan est suspendue, la station coupe faute de battements) | fait (0.12.0) | demandé le 2026-10-29 |
| PTT par le bouton du casque (filaire ou Bluetooth) ou les touches du volant ; micro du casque Bluetooth | — | absent (navigateur) | fait (0.13.0, désactivés par défaut) | demandé le 2026-10-29 ; à essayer avec un vrai casque |
| « Tout afficher » : 30 derniers spots TOUTES BANDES (heure locale, indicatif, fréquence, source ; toucher = QSY) | fait (message `recent`, 0.56.0) | fait (0.56.0) | fait (0.14.0 ; 0.13.0 : bande du poste seulement) | demandé le 2026-10-29 |
| Version du logiciel sur l'écran de connexion | — | en pied de page | fait (0.13.0) | |
| Voyants de l'afficheur (ATT / P.AMP n, RIT, ΔTX, SPLIT, NOTCH, NB, NR) | fait | fait (0.56.0, `indicatorsView`) | fait (0.10.1-0.11.0) | |
| Bandes préférées | — | fait (0.56.0 : cases à cocher, ordre du plan) | fait (0.9.0 : choix et ordre) | |
| Égaliseur paramétrique 10 bandes, chorus, réverbération, limiteur, écoute de contrôle, enregistrement et relecture, bouton EQ direct, préréglages, export / import JSON | — (côté client) | fait (0.57.0, `voice.js`) | fait (0.22.0 : onglet « Égaliseur », bouton EQ ; écoute de contrôle en direct NON faite, enregistrement et relecture seulement) | vecteurs communs `voice_vectors.json`, `voice_presets.json` |
| Profil du micro (pièce calme / bruyante, micro-casque avec ou sans réduction de bruit, personnalisé) | compte les trous (`tx_underruns`) | fait (0.58.0 ; appliqué tout de suite si le navigateur le permet) | fait (0.16.0 ; à la connexion suivante) | coupures en émission, 2026-10-29 |
| Gain du micro, porte de bruit réglable, niveau du micro | — | fait (0.58.0, `voice.js`) | à faire (A3, avec l'égaliseur) | |
| SELCALL : indicateur, armer / réarmer / désactiver, historique, filtrage des tonalités, dernier appel, bip à l'ouverture | fait (0.61.0 : commandes `selcall_*`, message `selcall`) | fait (0.61.0) | fait (0.17.0) | lot 4 du cahier SELCALL |
| SELCALL : fichier de test pour un correspondant | — (fabriqué par le client) | Écouter, Télécharger (0.61.0) | Écouter, Partager, Téléchargements (0.17.0) | demandé le 2026-10-29 |
| SELCALL : appel manuel (« Envoyer SELCALL » / « Annuler (2/3) »), trame en fin d'émission | fait (0.62.0 : `selcall_send`, `send_on_tx_end`) | fait (0.62.0) | fait (0.18.0) | lot 3 du cahier SELCALL |
| SELCALL : niveau de la trame (curseur), réglage automatique d'après l'ALC | fait (0.64.0 : `selcall_calibrate`, `tx_level_dbfs`) | fait (0.64.0) | fait (0.19.0) | demandé le 2026-10-29 |
| Voyant « OVERLOAD ALC » (ALC >= 50 % pendant toute émission) | publie l'ALC pendant l'émission | fait (0.64.0) | fait (0.19.0) | seuil commun ALC_OVERLOAD, à ajuster |
| Voyant du VFO actif (VFO A, VFO B, MEM, MAIN, SUB) quand le poste le dit | publie `rig.vfo` (0.65.0) | fait (0.65.0) | fait (0.20.0) | Yaesu FTDX10/101 ; absent sur l'IC-7300MK2 |
