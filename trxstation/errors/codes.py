# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Codes du catalogue d'erreurs : FICHIER FABRIQUÉ par scripts/build_errors.py depuis catalog.yaml.

Ne pas modifier à la main. Un code n'est jamais réutilisé ni renuméroté (cahier du monitoring, § 7).
"""
from __future__ import annotations

ORT_1001 = "ORT-1001"   # avertissement : Disque presque plein
ORT_1002 = "ORT-1002"   # avertissement : Mémoire de la station presque pleine
ORT_1003 = "ORT-1003"   # avertissement : Raspberry Pi ralenti
ORT_1004 = "ORT-1004"   # avertissement : Identifiant de station indisponible
ORT_1005 = "ORT-1005"   # erreur : Fichier d'état de la passerelle non écrit
ORT_1006 = "ORT-1006"   # avertissement : Machine de la station chargée
ORT_1007 = "ORT-1007"   # avertissement : État de la mesure de TOS non enregistré ou illisible
ORT_1008 = "ORT-1008"   # erreur : Réglage non enregistré sur la station
ORT_1009 = "ORT-1009"   # avertissement : Journal de la station non écrit
ORT_1010 = "ORT-1010"   # avertissement : Température du processeur élevée
ORT_1011 = "ORT-1011"   # erreur : Système d'exploitation non pris en charge
ORT_1012 = "ORT-1012"   # erreur : Espace disque insuffisant
ORT_1013 = "ORT-1013"   # info : Température du processeur illisible
ORT_1014 = "ORT-1014"   # avertissement : Matériel en dessous du minimum conseillé
ORT_1015 = "ORT-1015"   # avertissement : Alimentation du Raspberry Pi trop faible
ORT_1020 = "ORT-1020"   # erreur : Horloge de la station refusée par le relais
ORT_1501 = "ORT-1501"   # avertissement : Recherche de mise à jour impossible
ORT_1502 = "ORT-1502"   # avertissement : Dernière recherche de mise à jour trop ancienne
ORT_1503 = "ORT-1503"   # info : Nouvelle version disponible
ORT_1504 = "ORT-1504"   # avertissement : Aucune clé de signature connue
ORT_1505 = "ORT-1505"   # erreur : Mise à jour refusée : émission en cours ou état inconnu
ORT_1506 = "ORT-1506"   # critique : Signature du paquet refusée
ORT_1507 = "ORT-1507"   # critique : Contenu du paquet refusé
ORT_1508 = "ORT-1508"   # erreur : Téléchargement de la mise à jour impossible
ORT_1509 = "ORT-1509"   # avertissement : Paquet déposé refusé ou à confirmer
ORT_1510 = "ORT-1510"   # erreur : Installation de la nouvelle version échouée
ORT_1511 = "ORT-1511"   # erreur : Clé de signature des versions inutilisable (développement)
ORT_2001 = "ORT-2001"   # critique : Port série du poste introuvable
ORT_2002 = "ORT-2002"   # erreur : rigctld ne démarre pas
ORT_2003 = "ORT-2003"   # erreur : Hamlib introuvable (rigctld ou rigctl)
ORT_2004 = "ORT-2004"   # info : rigctld non lancé (outil en --no-spawn)
ORT_2005 = "ORT-2005"   # erreur : rigctld injoignable
ORT_2006 = "ORT-2006"   # avertissement : Connexion fermée par rigctld
ORT_2007 = "ORT-2007"   # erreur : Réponse de rigctld désynchronisée
ORT_2008 = "ORT-2008"   # avertissement : Réponse du poste illisible
ORT_2009 = "ORT-2009"   # info : Lecture facultative abandonnée pour ce poste
ORT_2010 = "ORT-2010"   # erreur : Le poste ne répond pas (rigctld répond)
ORT_2011 = "ORT-2011"   # avertissement : Commande refusée par le poste (RPRT)
ORT_2012 = "ORT-2012"   # info : Mode ou fonction non géré par ce poste
ORT_2013 = "ORT-2013"   # info : Valeur hors de la plage du poste
ORT_2014 = "ORT-2014"   # avertissement : Capacités du poste indisponibles (dump_caps)
ORT_2015 = "ORT-2015"   # avertissement : Poste éteint ou débranché
ORT_2016 = "ORT-2016"   # avertissement : Port du poste du profil absent
ORT_2017 = "ORT-2017"   # erreur : Le poste répond mal au test de liaison
ORT_2018 = "ORT-2018"   # erreur : Modèle du poste inconnu de ce Hamlib
ORT_2019 = "ORT-2019"   # avertissement : Service système qui perturbe le port série
ORT_2020 = "ORT-2020"   # avertissement : Tension d'alimentation du poste basse
ORT_2021 = "ORT-2021"   # erreur : Compilation de Hamlib impossible
ORT_2022 = "ORT-2022"   # avertissement : Un autre rigctld passe avant celui compilé
ORT_2104 = "ORT-2104"   # erreur : Délai de réponse CAT dépassé
ORT_2200 = "ORT-2200"   # avertissement : Version de Hamlib plus ancienne que la version qualifiée
ORT_2301 = "ORT-2301"   # avertissement : Second port du poste impossible à ouvrir (spectre HF)
ORT_2302 = "ORT-2302"   # avertissement : Aucune réponse CI-V sur le second port
ORT_2303 = "ORT-2303"   # avertissement : Adresse CI-V du poste changée (second port)
ORT_2304 = "ORT-2304"   # avertissement : Le poste ne fournit pas le spectre par le CI-V
ORT_2305 = "ORT-2305"   # erreur : Le second port n'est pas celui du même poste
ORT_2306 = "ORT-2306"   # avertissement : État d'émission illisible après l'ouverture du second port
ORT_2307 = "ORT-2307"   # avertissement : Plus aucune donnée du spectre HF
ORT_2308 = "ORT-2308"   # avertissement : Second port du poste perdu
ORT_2309 = "ORT-2309"   # erreur : Erreur interne du spectre HF
ORT_2310 = "ORT-2310"   # info : Réglage du spectre ou du filtre FIL refusé
ORT_2311 = "ORT-2311"   # erreur : Réglage du spectre HF incompatible avec le poste
ORT_2312 = "ORT-2312"   # erreur : Vérification du second port CI-V impossible
ORT_2313 = "ORT-2313"   # erreur : Spectre HF en panne (affichage)
ORT_2601 = "ORT-2601"   # erreur : Essai : fréquence non suivie par le poste
ORT_2602 = "ORT-2602"   # erreur : Essai : mode non suivi par le poste
ORT_2603 = "ORT-2603"   # avertissement : Essai : largeurs de filtre non suivies
ORT_2604 = "ORT-2604"   # avertissement : Essai : fonction ou niveau du poste en échec
ORT_2605 = "ORT-2605"   # erreur : Essai : endurance de la liaison CAT en échec
ORT_2606 = "ORT-2606"   # avertissement : Essai : pas de reprise après débranchement USB
ORT_2607 = "ORT-2607"   # avertissement : Essai : état d'origine du poste non rétabli
ORT_2608 = "ORT-2608"   # erreur : Essai : coupure faite sur le poste non vue par la station
ORT_2701 = "ORT-2701"   # avertissement : Qualification : socle en échec, poste refusé
ORT_2702 = "ORT-2702"   # info : Qualification incomplète
ORT_2703 = "ORT-2703"   # info : Qualification : afficheur ou son non confirmés par l'opérateur
ORT_2704 = "ORT-2704"   # info : Poste ou firmware non qualifié
ORT_3001 = "ORT-3001"   # critique : Périphérique audio du poste absent
ORT_3002 = "ORT-3002"   # avertissement : Essai : son reçu absent, muet ou saturé
ORT_3003 = "ORT-3003"   # erreur : Essai : audio d'émission non transmis ou ROS élevé
ORT_3004 = "ORT-3004"   # critique : Ouverture du périphérique audio impossible
ORT_3005 = "ORT-3005"   # avertissement : Son d'émission en retard ou haché
ORT_3006 = "ORT-3006"   # info : Client trop lent pour le son reçu
ORT_3007 = "ORT-3007"   # erreur : Traitement du son reçu en erreur
ORT_3008 = "ORT-3008"   # erreur : Vidage du tampon d'émission impossible à la coupure
ORT_3009 = "ORT-3009"   # avertissement : Cartes son de la station non choisies
ORT_3010 = "ORT-3010"   # avertissement : Sous-débits audio fréquents (xruns)
ORT_3011 = "ORT-3011"   # avertissement : Carte son du poste occupée par le son du bureau
ORT_4001 = "ORT-4001"   # avertissement : Pertes réseau d'un client élevées
ORT_4002 = "ORT-4002"   # avertissement : Demande de déconnexion d'un visiteur ignorée
ORT_4003 = "ORT-4003"   # info : Demande de connexion mal formée
ORT_4004 = "ORT-4004"   # avertissement : Connexion refusée : identifiant ou mot de passe
ORT_4005 = "ORT-4005"   # avertissement : Station occupée : trop de connexions
ORT_4006 = "ORT-4006"   # erreur : Erreur de la station pendant la connexion
ORT_4007 = "ORT-4007"   # avertissement : Compte désactivé ou expiré
ORT_4008 = "ORT-4008"   # info : Compte modifié : reconnexion demandée
ORT_4009 = "ORT-4009"   # avertissement : Connexion WebRTC jamais établie
ORT_4010 = "ORT-4010"   # info : Message du client illisible
ORT_4011 = "ORT-4011"   # info : Commande inconnue de la station
ORT_4012 = "ORT-4012"   # info : Paramètres de commande refusés
ORT_4013 = "ORT-4013"   # avertissement : Client trop bavard : messages ignorés
ORT_4014 = "ORT-4014"   # info : Fonction absente de cette station
ORT_4015 = "ORT-4015"   # info : Élément demandé inconnu
ORT_4016 = "ORT-4016"   # info : Rapport de problème refusé
ORT_4017 = "ORT-4017"   # info : Demande de TRX Console ignorée
ORT_4018 = "ORT-4018"   # erreur : Erreur inattendue : session d'un client
ORT_4101 = "ORT-4101"   # erreur : Certificat TLS inutilisable : API non démarrée
ORT_4102 = "ORT-4102"   # erreur : Port de la passerelle impossible à ouvrir
ORT_4103 = "ORT-4103"   # erreur : Compte d'accès mal défini
ORT_4104 = "ORT-4104"   # avertissement : Compte avec un jeton en clair
ORT_4105 = "ORT-4105"   # avertissement : Mot de passe trop faible refusé
ORT_4106 = "ORT-4106"   # avertissement : Certificat HTTPS impossible : accès limité à ce PC
ORT_4107 = "ORT-4107"   # avertissement : Aucune adresse réseau sur ce PC
ORT_4108 = "ORT-4108"   # avertissement : Port de la station fermé ou bloqué
ORT_4301 = "ORT-4301"   # info : Écoute des visiteurs coupée sur la station
ORT_4302 = "ORT-4302"   # info : Écoute des visiteurs fermée par l'opérateur
ORT_4303 = "ORT-4303"   # info : Nombre maximal de visiteurs atteint
ORT_4304 = "ORT-4304"   # info : Opérateur absent : écoute des visiteurs impossible
ORT_4305 = "ORT-4305"   # info : Visiteur déconnecté par l'opérateur
ORT_4306 = "ORT-4306"   # info : Commande refusée à un visiteur
ORT_4307 = "ORT-4307"   # avertissement : Visiteur déconnecté : trop de commandes refusées
ORT_4308 = "ORT-4308"   # erreur : Station surchargée : visiteurs déconnectés
ORT_4309 = "ORT-4309"   # avertissement : Écoute des visiteurs verrouillée après des surcharges répétées
ORT_4310 = "ORT-4310"   # info : Réouverture de l'écoute des visiteurs refusée
ORT_4501 = "ORT-4501"   # avertissement : Coupure réseau d'un client
ORT_4502 = "ORT-4502"   # avertissement : Aller-retour réseau élevé
ORT_4503 = "ORT-4503"   # avertissement : Profil VPN probablement partagé
ORT_4504 = "ORT-4504"   # info : Horloge du client décalée
ORT_4505 = "ORT-4505"   # avertissement : Sonde de la station vers la box ou Internet abandonnée
ORT_4506 = "ORT-4506"   # info : Historique de la sonde réseau effacé
ORT_4507 = "ORT-4507"   # info : trx-netreport : aucune mesure
ORT_4508 = "ORT-4508"   # erreur : Export ou effacement de l'historique réseau impossible
ORT_4509 = "ORT-4509"   # erreur : Erreur inattendue : sonde de qualité réseau
ORT_5001 = "ORT-5001"   # avertissement : Durée maximale d'émission (TOT) atteinte
ORT_5002 = "ORT-5002"   # erreur : Retour forcé en réception : terminal perdu
ORT_5003 = "ORT-5003"   # critique : L'ouverture du second port met le poste en émission
ORT_5004 = "ORT-5004"   # info : Émission pendant l'ouverture du second port (autre cause)
ORT_5005 = "ORT-5005"   # info : Poste utilisé sur place : PTT à distance bloqué
ORT_5006 = "ORT-5006"   # info : Reprise de la main impossible : le poste émet sur place
ORT_5007 = "ORT-5007"   # info : Main reprise à distance
ORT_5008 = "ORT-5008"   # erreur : Poste trop chaud : émission à distance coupée
ORT_5009 = "ORT-5009"   # avertissement : Poste chaud
ORT_5010 = "ORT-5010"   # critique : PTT actif sans session cliente
ORT_5011 = "ORT-5011"   # info : Prise d'émission annulée par une coupure
ORT_5012 = "ORT-5012"   # erreur : L'ordre d'émission a échoué
ORT_5013 = "ORT-5013"   # erreur : Le poste n'est pas passé en émission
ORT_5014 = "ORT-5014"   # info : Fin d'émission proche (TOT)
ORT_5015 = "ORT-5015"   # info : Émission coupée par STOP
ORT_5016 = "ORT-5016"   # info : Émission coupée par un autre client
ORT_5017 = "ORT-5017"   # avertissement : Réglage modifié sur le poste pendant l'émission
ORT_5018 = "ORT-5018"   # avertissement : Le poste est repassé seul en réception
ORT_5019 = "ORT-5019"   # erreur : Liaison avec le poste perdue pendant l'émission
ORT_5020 = "ORT-5020"   # critique : Retour en réception impossible
ORT_5021 = "ORT-5021"   # avertissement : Bip de fin d'émission impossible
ORT_5022 = "ORT-5022"   # info : Bip de fin interrompu par une coupure
ORT_5023 = "ORT-5023"   # info : Émission coupée par l'arrêt de la station
ORT_5024 = "ORT-5024"   # critique : TOT absolu dépassé : coupure par le superviseur
ORT_5025 = "ORT-5025"   # critique : Passerelle muette pendant une émission
ORT_5026 = "ORT-5026"   # critique : rigctld injoignable pendant une émission
ORT_5027 = "ORT-5027"   # critique : « T 0 » du superviseur non confirmé
ORT_5028 = "ORT-5028"   # erreur : Erreur inattendue : bips de fin d'émission
ORT_5101 = "ORT-5101"   # erreur : Émission refusée : défaut verrouillé
ORT_5102 = "ORT-5102"   # info : Émission refusée : station en démarrage
ORT_5103 = "ORT-5103"   # info : Émission refusée : coupure ou émission en cours
ORT_5104 = "ORT-5104"   # avertissement : Émission refusée : client non reconnu
ORT_5105 = "ORT-5105"   # info : Émission refusée : mesure de TOS en cours
ORT_5106 = "ORT-5106"   # avertissement : Émission refusée : aucune bande autorisée
ORT_5107 = "ORT-5107"   # avertissement : Émission refusée : hors des bandes autorisées
ORT_5108 = "ORT-5108"   # erreur : Émission refusée : split illisible
ORT_5109 = "ORT-5109"   # erreur : Émission refusée : ΔTX (XIT) illisible
ORT_5110 = "ORT-5110"   # erreur : Émission refusée : liaison avec le poste perdue
ORT_5111 = "ORT-5111"   # erreur : Émission refusée : le poste répond mal
ORT_5112 = "ORT-5112"   # erreur : Émission refusée : état du PTT illisible
ORT_5113 = "ORT-5113"   # avertissement : Émission refusée : le poste émet déjà
ORT_5114 = "ORT-5114"   # avertissement : Émission refusée dans ce mode
ORT_5115 = "ORT-5115"   # info : Émission refusée : trop rapprochée
ORT_5116 = "ORT-5116"   # info : Réglage refusé pendant l'émission
ORT_5501 = "ORT-5501"   # info : Mesure de TOS non disponible
ORT_5502 = "ORT-5502"   # info : Plage de mesure de TOS invalide
ORT_5503 = "ORT-5503"   # avertissement : Mesure de TOS : aucun point dans les bandes
ORT_5504 = "ORT-5504"   # avertissement : Mesure de TOS : aucun mode FM permis
ORT_5505 = "ORT-5505"   # erreur : Mesure de TOS arrêtée : poste illisible
ORT_5506 = "ORT-5506"   # info : Mesure de TOS interrompue par une coupure
ORT_5507 = "ORT-5507"   # avertissement : Mesure de TOS arrêtée : émission refusée
ORT_5508 = "ORT-5508"   # erreur : Mesure de TOS en erreur
ORT_5509 = "ORT-5509"   # avertissement : Lecture du TOS instable sur ce poste
ORT_5510 = "ORT-5510"   # avertissement : Point de mesure à puissance réduite
ORT_5511 = "ORT-5511"   # info : Point de mesure sans lecture du TOS
ORT_5512 = "ORT-5512"   # avertissement : Remise en état du poste incomplète après la mesure
ORT_5801 = "ORT-5801"   # avertissement : PTT par RTS ou DTR : risque d'émission brève
ORT_5802 = "ORT-5802"   # avertissement : Contrôle des bandes désactivé
ORT_5803 = "ORT-5803"   # avertissement : Chargement d'un profil refusé pendant l'émission
ORT_5804 = "ORT-5804"   # avertissement : PTT actif pendant le test : retour en réception forcé
ORT_5805 = "ORT-5805"   # critique : STOP TX de trx-monitor sans confirmation
ORT_5806 = "ORT-5806"   # erreur : Mise en page sans commande de sécurité
ORT_5901 = "ORT-5901"   # erreur : Essai : état PTT relu incohérent
ORT_5902 = "ORT-5902"   # critique : Essai de panne : l'émission n'a pas été coupée
ORT_6401 = "ORT-6401"   # erreur : Cluster DX activé mais incomplet
ORT_6402 = "ORT-6402"   # avertissement : Serveur de spots injoignable
ORT_6403 = "ORT-6403"   # info : Connexion au cluster fermée par le serveur
ORT_6404 = "ORT-6404"   # avertissement : Connexion au cluster muette
ORT_6405 = "ORT-6405"   # erreur : Indicatif refusé par le cluster
ORT_6406 = "ORT-6406"   # erreur : Mot de passe refusé par le cluster
ORT_6407 = "ORT-6407"   # erreur : Le cluster demande un mot de passe
ORT_6408 = "ORT-6408"   # avertissement : Bascule vers un autre cluster
ORT_6409 = "ORT-6409"   # avertissement : Aucune source du Cluster DX connectée
ORT_6410 = "ORT-6410"   # avertissement : Page des spots CB illisible
ORT_6411 = "ORT-6411"   # avertissement : Table des pays (cty.dat) absente ou illisible
ORT_6412 = "ORT-6412"   # info : Mise à jour de cty.dat impossible
ORT_6413 = "ORT-6413"   # info : Indicatif refusé par le réglage du Cluster DX
ORT_6501 = "ORT-6501"   # erreur : Module extérieur déclaré mais absent ou non démarré
ORT_6502 = "ORT-6502"   # erreur : Version du module incompatible
ORT_6503 = "ORT-6503"   # erreur : Échec de la négociation avec le module
ORT_6504 = "ORT-6504"   # avertissement : Le module ne répond plus (battement perdu)
ORT_6505 = "ORT-6505"   # avertissement : Catalogue du module invalide ou non traduit
ORT_6506 = "ORT-6506"   # avertissement : Code reçu absent du catalogue du module
ORT_6507 = "ORT-6507"   # erreur : Le module perturbe la station (CPU, latence audio)
ORT_6508 = "ORT-6508"   # avertissement : Préfixe non enregistré
ORT_6511 = "ORT-6511"   # avertissement : Manifeste de module invalide
ORT_6512 = "ORT-6512"   # info : Module désactivé par son manifeste
ORT_6513 = "ORT-6513"   # avertissement : Aucun module utilisable
ORT_6514 = "ORT-6514"   # erreur : Bus des modules indisponible
ORT_6515 = "ORT-6515"   # erreur : Clé des modules invalide
ORT_6516 = "ORT-6516"   # erreur : Compte d'exécution des modules inutilisable
ORT_6517 = "ORT-6517"   # avertissement : Arrêt inattendu d'un module
ORT_6518 = "ORT-6518"   # avertissement : Message illisible d'un module
ORT_6519 = "ORT-6519"   # avertissement : Station injoignable depuis un module
ORT_6520 = "ORT-6520"   # info : Commande de module refusée pendant l'émission
ORT_6521 = "ORT-6521"   # avertissement : Action d'un module non autorisée
ORT_6522 = "ORT-6522"   # info : Commande non disponible
ORT_6523 = "ORT-6523"   # info : Trop de messages d'un module
ORT_6524 = "ORT-6524"   # avertissement : Délai de réponse dépassé entre la station et un module
ORT_6525 = "ORT-6525"   # avertissement : Changement de fréquence demandé par un module refusé
ORT_6526 = "ORT-6526"   # avertissement : Jeton de session refusé
ORT_6527 = "ORT-6527"   # erreur : Erreur inattendue dans le bus des modules
ORT_6528 = "ORT-6528"   # avertissement : Fichier d'un module non écrit
ORT_6531 = "ORT-6531"   # erreur : Clé d'appairage de Breizh Audio Box inutilisable
ORT_6532 = "ORT-6532"   # info : Breizh Audio Box a quitté le mode OpenRemoteTRX
ORT_6533 = "ORT-6533"   # avertissement : Repli pendant l'émission : fin en direct
ORT_6534 = "ORT-6534"   # info : Blocs de son revenus trop tard de Breizh Audio Box
ORT_6535 = "ORT-6535"   # erreur : Mode OpenRemoteTRX non activé dans Breizh Audio Box
ORT_6536 = "ORT-6536"   # avertissement : Breizh Audio Box sert déjà une autre station
ORT_6537 = "ORT-6537"   # erreur : Breizh Audio Box n'a pas coupé son CAT
ORT_6538 = "ORT-6538"   # erreur : Réponse de Breizh Audio Box mal formée
ORT_6539 = "ORT-6539"   # avertissement : Paquets de Breizh Audio Box refusés
ORT_6540 = "ORT-6540"   # info : Breizh Audio Box joint ou repris
ORT_6541 = "ORT-6541"   # erreur : Erreur inattendue : liaison avec Breizh Audio Box
ORT_6561 = "ORT-6561"   # avertissement : Décodeur FreeDV arrêté
ORT_6562 = "ORT-6562"   # avertissement : Sortie d'un décodeur FreeDV illisible
ORT_6563 = "ORT-6563"   # erreur : FreeDV abandonné après ses relances
ORT_6564 = "ORT-6564"   # erreur : Mode FreeDV en erreur dans la chaîne audio
ORT_6565 = "ORT-6565"   # avertissement : Décodeur FreeDV trop lent : son jeté
ORT_6566 = "ORT-6566"   # info : Mode FreeDV non changé pendant l'émission
ORT_6567 = "ORT-6567"   # erreur : Erreur inattendue : mode FreeDV
ORT_6801 = "ORT-6801"   # info : Essai SELCALL : RIT refusé ou illisible
ORT_6802 = "ORT-6802"   # info : Trame SELCALL de fin omise : TOT trop proche
ORT_6803 = "ORT-6803"   # avertissement : Appel SELCALL refusé : plus long que le TOT
ORT_6804 = "ORT-6804"   # erreur : Appel SELCALL interrompu
ORT_6805 = "ORT-6805"   # info : Appel SELCALL reçu
ORT_6806 = "ORT-6806"   # info : Trame SELCALL rejetée
ORT_6807 = "ORT-6807"   # avertissement : État SELCALL illisible
ORT_6808 = "ORT-6808"   # avertissement : État SELCALL non enregistré
ORT_6809 = "ORT-6809"   # info : SELCALL non disponible
ORT_6810 = "ORT-6810"   # info : Appel SELCALL impossible : aucun code armé
ORT_6811 = "ORT-6811"   # info : Code SELCALL invalide
ORT_6812 = "ORT-6812"   # avertissement : Réglage automatique SELCALL : ALC illisible
ORT_6813 = "ORT-6813"   # avertissement : Réglage automatique SELCALL : ALC dès le plus bas niveau
ORT_6814 = "ORT-6814"   # erreur : Erreur inattendue du SELCALL
ORT_6901 = "ORT-6901"   # avertissement : Module « presence » injoignable depuis la console
ORT_6902 = "ORT-6902"   # avertissement : Présence de groupe : pseudo absent
ORT_6903 = "ORT-6903"   # avertissement : Relais de présence injoignable
ORT_6904 = "ORT-6904"   # erreur : Enregistrement refusé par le relais de présence
ORT_6905 = "ORT-6905"   # info : Relais de présence en pause ou chargé
ORT_6906 = "ORT-6906"   # avertissement : Requête refusée par le relais de présence
ORT_6907 = "ORT-6907"   # avertissement : Action refusée par le relais de présence
ORT_6908 = "ORT-6908"   # avertissement : Liste des membres d'un groupe refusée
ORT_6909 = "ORT-6909"   # avertissement : Clé de groupe reçue refusée
ORT_6910 = "ORT-6910"   # info : État d'un membre refusé
ORT_6911 = "ORT-6911"   # info : Station retirée d'un groupe
ORT_6912 = "ORT-6912"   # info : Demande d'adhésion refusée automatiquement
ORT_6913 = "ORT-6913"   # info : Invitation refusée
ORT_6914 = "ORT-6914"   # info : Trop de groupes
ORT_6915 = "ORT-6915"   # info : Station pas encore enregistrée auprès du relais
ORT_6916 = "ORT-6916"   # info : Action réservée à un administrateur du groupe
ORT_6917 = "ORT-6917"   # info : Groupe ou membre inconnu
ORT_6918 = "ORT-6918"   # info : Saisie refusée (présence de groupe)
ORT_6919 = "ORT-6919"   # info : Présence de groupe non disponible
ORT_6920 = "ORT-6920"   # erreur : Fichier de clés de la présence illisible
ORT_6921 = "ORT-6921"   # erreur : Données de la présence illisibles
ORT_6922 = "ORT-6922"   # erreur : Erreur inattendue de la présence de groupe
ORT_6923 = "ORT-6923"   # erreur : Signature invalide reçue (attaque possible)
ORT_7001 = "ORT-7001"   # info : Liaison monitor établie
ORT_7010 = "ORT-7010"   # avertissement : Échec ICE, bascule en port UDP
ORT_7020 = "ORT-7020"   # avertissement : File d'envoi saturée
ORT_7030 = "ORT-7030"   # erreur : Clé distante changée, liaison suspendue
ORT_8001 = "ORT-8001"   # erreur : Redémarrage d'un processus par le superviseur
ORT_8002 = "ORT-8002"   # erreur : Module désactivé après des arrêts répétés
ORT_8003 = "ORT-8003"   # erreur : Passerelle muette
ORT_8004 = "ORT-8004"   # erreur : Réinitialisation USB du poste
ORT_8005 = "ORT-8005"   # erreur : Réinitialisation USB impossible
ORT_8006 = "ORT-8006"   # critique : Redémarrage de la machine par le superviseur
ORT_8007 = "ORT-8007"   # critique : Redémarrage refusé : historique non inscriptible
ORT_8008 = "ORT-8008"   # critique : Mode sûr : station en réception, accès coupé
ORT_8009 = "ORT-8009"   # erreur : Mode sûr non enregistré
ORT_8010 = "ORT-8010"   # erreur : Action du superviseur en échec
ORT_8011 = "ORT-8011"   # info : Station rétablie
ORT_8012 = "ORT-8012"   # info : Station en service
ORT_8013 = "ORT-8013"   # avertissement : Alerte ntfy non envoyée
ORT_8014 = "ORT-8014"   # critique : Boucle de supervision en erreur
ORT_8015 = "ORT-8015"   # erreur : Superviseur déjà en cours d'exécution
ORT_8016 = "ORT-8016"   # erreur : La station ne s'arrête pas
ORT_8017 = "ORT-8017"   # erreur : Superviseur disparu : passerelle arrêtée
ORT_8018 = "ORT-8018"   # erreur : Surveillance des accès en erreur
ORT_8019 = "ORT-8019"   # erreur : Erreur inattendue d'un composant (la station continue)  [abandonné]
ORT_8020 = "ORT-8020"   # avertissement : Aucune adresse d'alerte (ntfy)
ORT_8021 = "ORT-8021"   # erreur : Service de la station en échec ou arrêté
ORT_9001 = "ORT-9001"   # erreur : station.toml invalide
ORT_9002 = "ORT-9002"   # erreur : Réglage inconnu dans station.toml
ORT_9003 = "ORT-9003"   # erreur : Structure de station.toml invalide
ORT_9004 = "ORT-9004"   # erreur : Version du format de station.toml non prise en charge
ORT_9005 = "ORT-9005"   # erreur : Réglage oui/non mal écrit
ORT_9006 = "ORT-9006"   # erreur : Valeur de réglage hors limites
ORT_9007 = "ORT-9007"   # erreur : Valeur de réglage mal formée
ORT_9008 = "ORT-9008"   # erreur : Seuils de réglage dans le mauvais ordre
ORT_9009 = "ORT-9009"   # erreur : Réglages de sécurité d'émission incohérents
ORT_9010 = "ORT-9010"   # critique : rigctld exposé hors de la machine
ORT_9011 = "ORT-9011"   # critique : Réglage réservé interdit dans extra_conf
ORT_9012 = "ORT-9012"   # erreur : Modèle ou port du poste manquant
ORT_9013 = "ORT-9013"   # erreur : Méthode PTT inconnue
ORT_9014 = "ORT-9014"   # erreur : Bande d'émission mal définie
ORT_9015 = "ORT-9015"   # erreur : Deux services sur le même port
ORT_9016 = "ORT-9016"   # critique : Module réglé pour tourner en root
ORT_9017 = "ORT-9017"   # erreur : Adresse de liaison refusée (non privée ou non chiffrée)
ORT_9018 = "ORT-9018"   # avertissement : Modification de station.toml refusée
ORT_9019 = "ORT-9019"   # erreur : Enregistrement de station.toml impossible
ORT_9020 = "ORT-9020"   # avertissement : station.toml illisible pour ce compte
ORT_9021 = "ORT-9021"   # avertissement : Droits de station.toml incorrects
ORT_9022 = "ORT-9022"   # info : Station pas encore configurée
ORT_9023 = "ORT-9023"   # info : Aucun éditeur de texte
ORT_9101 = "ORT-9101"   # erreur : Profil de poste illisible ou abîmé
ORT_9102 = "ORT-9102"   # erreur : Profil de poste d'une autre version
ORT_9103 = "ORT-9103"   # erreur : Profil de poste refusé par la validation
ORT_9104 = "ORT-9104"   # info : Nom de profil refusé
ORT_9105 = "ORT-9105"   # erreur : secrets.toml illisible ou mal formé
ORT_9106 = "ORT-9106"   # avertissement : Mot de passe de source refusé
ORT_9107 = "ORT-9107"   # avertissement : secrets.toml lisible par d'autres comptes
ORT_9108 = "ORT-9108"   # avertissement : Identifiant de station invalide
ORT_9201 = "ORT-9201"   # avertissement : Mise en page refusée
ORT_9202 = "ORT-9202"   # avertissement : Thème refusé (contraste ou couleur d'émission)
ORT_9203 = "ORT-9203"   # avertissement : Mise en page d'un format plus récent
ORT_9204 = "ORT-9204"   # avertissement : Mise en page enregistrée abîmée : profil d'usine servi
ORT_9205 = "ORT-9205"   # info : Widget lié à une fonction absente du poste
ORT_9301 = "ORT-9301"   # erreur : Python absent ou trop ancien
ORT_9302 = "ORT-9302"   # erreur : Modules Python manquants
ORT_9303 = "ORT-9303"   # avertissement : Compte absent d'un groupe nécessaire
ORT_9304 = "ORT-9304"   # erreur : Paquet d'installation incomplet
ORT_9305 = "ORT-9305"   # erreur : Droits administrateur nécessaires
ORT_9306 = "ORT-9306"   # erreur : Pas d'accès Internet pendant l'installation
ORT_9307 = "ORT-9307"   # erreur : Installation des paquets Debian impossible
ORT_9308 = "ORT-9308"   # erreur : Installation des modules Python impossible
ORT_9309 = "ORT-9309"   # erreur : Installation de TRX distant ou activation de la version impossible
ORT_9310 = "ORT-9310"   # avertissement : Configuration refusée par la version installée
ORT_9311 = "ORT-9311"   # critique : Empreinte d'un module Python différente : installation arrêtée
ORT_9501 = "ORT-9501"   # erreur : Journal Android illisible
ORT_9502 = "ORT-9502"   # avertissement : Téléphone : copie ou lecture du journal impossible
ORT_9503 = "ORT-9503"   # avertissement : Rapport HTML du journal Android non écrit
ORT_9504 = "ORT-9504"   # erreur : Application Android : plantage  [abandonné]
ORT_9505 = "ORT-9505"   # erreur : Application Android bloquée (ANR)  [abandonné]
ORT_9506 = "ORT-9506"   # avertissement : Application Android : installation en échec  [abandonné]
ORT_9507 = "ORT-9507"   # avertissement : Application Android arrêtée par Android  [abandonné]
ORT_9508 = "ORT-9508"   # info : Erreurs écrites par l'application Android  [abandonné]
ORT_9701 = "ORT-9701"   # erreur : Module pyserial absent (spectre HF)
ORT_9702 = "ORT-9702"   # avertissement : Fichier des mémoires illisible
ORT_9703 = "ORT-9703"   # info : Mémoires indisponibles sur cette station
ORT_9704 = "ORT-9704"   # avertissement : Fiche de qualification invalide
ORT_9705 = "ORT-9705"   # info : Paramètre d'outil hors bornes
ORT_9706 = "ORT-9706"   # avertissement : station.toml modifié mais invalide : comptes inchangés
ORT_9707 = "ORT-9707"   # critique : Bibliothèque audio absente (sounddevice / PortAudio)
ORT_9708 = "ORT-9708"   # erreur : Source ou sortie audio d'essai invalide
ORT_9709 = "ORT-9709"   # erreur : Modules WebRTC absents : API non démarrée
ORT_9710 = "ORT-9710"   # avertissement : Aucun compte client : pas d'API
ORT_9711 = "ORT-9711"   # erreur : Exposition de l'API jugée dangereuse : API non démarrée
ORT_9712 = "ORT-9712"   # avertissement : Fichier de réglages de la station illisible
ORT_9713 = "ORT-9713"   # erreur : Rapport de diagnostic impossible
ORT_9714 = "ORT-9714"   # erreur : Commande introuvable
ORT_9715 = "ORT-9715"   # info : Option de commande inconnue ou invalide
ORT_9716 = "ORT-9716"   # erreur : Import de la configuration d'un autre PC impossible
ORT_9717 = "ORT-9717"   # info : Indicateur de bureau indisponible
ORT_9718 = "ORT-9718"   # info : Tests de la station indisponibles
AND_1001 = "AND-1001"   # erreur : Application Android : plantage
AND_1002 = "AND-1002"   # erreur : Application Android bloquée (ANR)
AND_1003 = "AND-1003"   # avertissement : Application Android : installation en échec
AND_1004 = "AND-1004"   # avertissement : Application Android arrêtée par Android
AND_1005 = "AND-1005"   # info : Erreurs écrites par l'application Android

ALL: frozenset[str] = frozenset({
    ORT_1001, ORT_1002, ORT_1003, ORT_1004, ORT_1005, ORT_1006, ORT_1007, ORT_1008,
    ORT_1009, ORT_1010, ORT_1011, ORT_1012, ORT_1013, ORT_1014, ORT_1015, ORT_1020,
    ORT_1501, ORT_1502, ORT_1503, ORT_1504, ORT_1505, ORT_1506, ORT_1507, ORT_1508,
    ORT_1509, ORT_1510, ORT_1511, ORT_2001, ORT_2002, ORT_2003, ORT_2004, ORT_2005,
    ORT_2006, ORT_2007, ORT_2008, ORT_2009, ORT_2010, ORT_2011, ORT_2012, ORT_2013,
    ORT_2014, ORT_2015, ORT_2016, ORT_2017, ORT_2018, ORT_2019, ORT_2020, ORT_2021,
    ORT_2022, ORT_2104, ORT_2200, ORT_2301, ORT_2302, ORT_2303, ORT_2304, ORT_2305,
    ORT_2306, ORT_2307, ORT_2308, ORT_2309, ORT_2310, ORT_2311, ORT_2312, ORT_2313,
    ORT_2601, ORT_2602, ORT_2603, ORT_2604, ORT_2605, ORT_2606, ORT_2607, ORT_2608,
    ORT_2701, ORT_2702, ORT_2703, ORT_2704, ORT_3001, ORT_3002, ORT_3003, ORT_3004,
    ORT_3005, ORT_3006, ORT_3007, ORT_3008, ORT_3009, ORT_3010, ORT_3011, ORT_4001,
    ORT_4002, ORT_4003, ORT_4004, ORT_4005, ORT_4006, ORT_4007, ORT_4008, ORT_4009,
    ORT_4010, ORT_4011, ORT_4012, ORT_4013, ORT_4014, ORT_4015, ORT_4016, ORT_4017,
    ORT_4018, ORT_4101, ORT_4102, ORT_4103, ORT_4104, ORT_4105, ORT_4106, ORT_4107,
    ORT_4108, ORT_4301, ORT_4302, ORT_4303, ORT_4304, ORT_4305, ORT_4306, ORT_4307,
    ORT_4308, ORT_4309, ORT_4310, ORT_4501, ORT_4502, ORT_4503, ORT_4504, ORT_4505,
    ORT_4506, ORT_4507, ORT_4508, ORT_4509, ORT_5001, ORT_5002, ORT_5003, ORT_5004,
    ORT_5005, ORT_5006, ORT_5007, ORT_5008, ORT_5009, ORT_5010, ORT_5011, ORT_5012,
    ORT_5013, ORT_5014, ORT_5015, ORT_5016, ORT_5017, ORT_5018, ORT_5019, ORT_5020,
    ORT_5021, ORT_5022, ORT_5023, ORT_5024, ORT_5025, ORT_5026, ORT_5027, ORT_5028,
    ORT_5101, ORT_5102, ORT_5103, ORT_5104, ORT_5105, ORT_5106, ORT_5107, ORT_5108,
    ORT_5109, ORT_5110, ORT_5111, ORT_5112, ORT_5113, ORT_5114, ORT_5115, ORT_5116,
    ORT_5501, ORT_5502, ORT_5503, ORT_5504, ORT_5505, ORT_5506, ORT_5507, ORT_5508,
    ORT_5509, ORT_5510, ORT_5511, ORT_5512, ORT_5801, ORT_5802, ORT_5803, ORT_5804,
    ORT_5805, ORT_5806, ORT_5901, ORT_5902, ORT_6401, ORT_6402, ORT_6403, ORT_6404,
    ORT_6405, ORT_6406, ORT_6407, ORT_6408, ORT_6409, ORT_6410, ORT_6411, ORT_6412,
    ORT_6413, ORT_6501, ORT_6502, ORT_6503, ORT_6504, ORT_6505, ORT_6506, ORT_6507,
    ORT_6508, ORT_6511, ORT_6512, ORT_6513, ORT_6514, ORT_6515, ORT_6516, ORT_6517,
    ORT_6518, ORT_6519, ORT_6520, ORT_6521, ORT_6522, ORT_6523, ORT_6524, ORT_6525,
    ORT_6526, ORT_6527, ORT_6528, ORT_6531, ORT_6532, ORT_6533, ORT_6534, ORT_6535,
    ORT_6536, ORT_6537, ORT_6538, ORT_6539, ORT_6540, ORT_6541, ORT_6561, ORT_6562,
    ORT_6563, ORT_6564, ORT_6565, ORT_6566, ORT_6567, ORT_6801, ORT_6802, ORT_6803,
    ORT_6804, ORT_6805, ORT_6806, ORT_6807, ORT_6808, ORT_6809, ORT_6810, ORT_6811,
    ORT_6812, ORT_6813, ORT_6814, ORT_6901, ORT_6902, ORT_6903, ORT_6904, ORT_6905,
    ORT_6906, ORT_6907, ORT_6908, ORT_6909, ORT_6910, ORT_6911, ORT_6912, ORT_6913,
    ORT_6914, ORT_6915, ORT_6916, ORT_6917, ORT_6918, ORT_6919, ORT_6920, ORT_6921,
    ORT_6922, ORT_6923, ORT_7001, ORT_7010, ORT_7020, ORT_7030, ORT_8001, ORT_8002,
    ORT_8003, ORT_8004, ORT_8005, ORT_8006, ORT_8007, ORT_8008, ORT_8009, ORT_8010,
    ORT_8011, ORT_8012, ORT_8013, ORT_8014, ORT_8015, ORT_8016, ORT_8017, ORT_8018,
    ORT_8019, ORT_8020, ORT_8021, ORT_9001, ORT_9002, ORT_9003, ORT_9004, ORT_9005,
    ORT_9006, ORT_9007, ORT_9008, ORT_9009, ORT_9010, ORT_9011, ORT_9012, ORT_9013,
    ORT_9014, ORT_9015, ORT_9016, ORT_9017, ORT_9018, ORT_9019, ORT_9020, ORT_9021,
    ORT_9022, ORT_9023, ORT_9101, ORT_9102, ORT_9103, ORT_9104, ORT_9105, ORT_9106,
    ORT_9107, ORT_9108, ORT_9201, ORT_9202, ORT_9203, ORT_9204, ORT_9205, ORT_9301,
    ORT_9302, ORT_9303, ORT_9304, ORT_9305, ORT_9306, ORT_9307, ORT_9308, ORT_9309,
    ORT_9310, ORT_9311, ORT_9501, ORT_9502, ORT_9503, ORT_9504, ORT_9505, ORT_9506,
    ORT_9507, ORT_9508, ORT_9701, ORT_9702, ORT_9703, ORT_9704, ORT_9705, ORT_9706,
    ORT_9707, ORT_9708, ORT_9709, ORT_9710, ORT_9711, ORT_9712, ORT_9713, ORT_9714,
    ORT_9715, ORT_9716, ORT_9717, ORT_9718, AND_1001, AND_1002, AND_1003, AND_1004,
    AND_1005,
})
