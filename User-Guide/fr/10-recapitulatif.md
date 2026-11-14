# 10. Récapitulatif : où en es-tu ?

Coche au fur et à mesure. Sur la page web du guide, les cases se cochent en ligne et restent cochées dans ton
navigateur ; sur GitHub, imprime cette page ou recopie la liste.

## 0. Avant de commencer

- [ ] Conditions du trafic à distance vérifiées pour ma licence
- [ ] Charge fictive disponible pour les essais
- [ ] Système choisi (Debian recommandé, ou Windows) et paquet téléchargé

## 1. Préparer le poste

- [ ] Pilote CP210x installé avant de brancher le câble (Windows)
- [ ] Port « Enhanced COM Port » repéré
- [ ] CAT RATE 38400, CAT TIME OUT TIMER 1000 msec, CAT RTS ENABLE
- [ ] MOD SOURCE = REAR et REAR SELECT = USB dans chaque mode utilisé
- [ ] RPTT SELECT = DAKY dans chaque mode, PC KEYING = OFF
- [ ] VOX éteint, TX TIME OUT TIMER 3 min, HF MAX POWER réglé
- [ ] Carte son du poste retirée du son par défaut du PC

## 2. Installer la station

- [ ] Logiciel installé (install.sh ou installer.cmd)
- [ ] Session rouverte (Debian) ; profil réseau Privé et veille désactivée (Windows)

## 3. Intégrer le TRX et l'essayer

- [ ] Assistant terminé (modèle 1042, port Enhanced, PTT par CAT, bandes de ma licence)
- [ ] Diagnostic sans échec
- [ ] Essai guidé en réception seule réussi
- [ ] Essai guidé avec émission réussi sur charge fictive
- [ ] Station démarrée, page ouverte, modulation réglée avec l'ALC (RPORT GAIN)
- [ ] Essai 1 : STOP coupe l'émission
- [ ] Essai 2 : coupure au bout de 90 s, avertissement 10 s avant
- [ ] Essai 3 : liaison coupée pendant l'émission, retour en réception
- [ ] Essai 4 : écran verrouillé pendant l'émission, retour en réception
- [ ] Essai 5 : émission refusée hors de mes bandes
- [ ] Essai 6 : émission au micro du poste, PTT à distance bloqué
- [ ] Essai 7 : STOP TX du tableau de bord
- [ ] Essai 8 : arrêt de la station pendant l'émission
- [ ] Essai 9 : aucun passage en émission au démarrage du PC
- [ ] Résultat des essais rapporté (ticket « FTDX10 : essais de mise en service »)

## 4. Utiliser sur le réseau local

- [ ] Adresse IP réservée au PC de la station dans la box
- [ ] Page web ouverte en https, certificat accepté, micro autorisé
- [ ] Un compte par utilisateur, mots de passe longs
- [ ] Application Android appairée par le QR code (menu 4.1), essai d'émission et STOP

## 5. Utiliser à distance

- [ ] Choix fait : VPN (recommandé) ou port ouvert
- [ ] Un profil VPN par appareil
- [ ] Depuis la 4G : page, son reçu, émission sur charge fictive, STOP
- [ ] Depuis la 4G : mode avion pendant l'émission, retour en réception

## 6. Station sans surveillance

- [ ] Alertes ntfy reçues (sujet long et secret), message « Station en service » vu
- [ ] PC réglé pour se rallumer après une coupure de courant
- [ ] Onduleur, parafoudre, ventilation du poste
- [ ] Je sais lever le mode sûr (menu 1.5) après avoir trouvé la cause

## 7. Exploitation au quotidien

- [ ] Je sais démarrer, arrêter et surveiller la station
- [ ] Je sais mettre à jour et revenir à la version précédente
- [ ] Configuration et certificat sauvegardés ailleurs
- [ ] Profil du poste enregistré (menu 3.3)

## Station en service

- [ ] Première émission sur antenne, dans mes bandes, avec identification
