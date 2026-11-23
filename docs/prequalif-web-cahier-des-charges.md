# Préqualification d'un poste depuis le navigateur : cahier des charges (v4, 2026-11-19)

Demande de l'utilisateur (2026-11-19) : un radioamateur ou un cibiste branche son TRX en USB sur son PC, ouvre une page
dans Chrome et sait en quelques minutes si son poste pourra être piloté par openRemoteTRX. Deux modes :

- **Mode A, navigateur seul** : la page parle au poste par l'API Web Serial de Chrome, SANS Hamlib, grâce aux
  protocoles CAT publiés par les constructeurs (pilotes écrits par Claude d'après leur documentation).
- **Mode B, avec Hamlib** : un petit programme installé sur le PC (Windows ou Linux) lance Hamlib et sert la MÊME page ;
  essai plus sérieux, entièrement automatique (la valise de qualification reste l'outil complet).

V2 le même jour (réponses de l'utilisateur) : rapport ENVOYÉ en un bouton, sans formulaire, avec des données dont la
vraisemblance se vérifie (§ 9) ; mode B ULTRA SIMPLE, petite passerelle « page web <-> Hamlib » proposée sur le
Microsoft Store (§ 8.1) ; français et anglais ; pas d'Android.
V3 le même jour (réponses de l'utilisateur) : programme « openRemoteTRX-Autotest » compilé en EXE (§ 8.1) ; courriel
facultatif derrière un interrupteur sur ARRÊT (§ 9.1) ; test ANONYME annoncé dès l'accueil, rien n'est envoyé sans le
bouton de la fin (§ 4, § 9.2) ; préqualifications NON montrées sur le site public pour l'instant ; autres langues plus
tard.
V4 le même jour (réponses de l'utilisateur, TOUTES les questions tranchées) : essais d'émission à 10 % de la puissance
maximale DU POSTE (§ 5.1) ; changement de fréquence permis (§ 6.5, R8) ; durées acceptées avec un écran qui dit ce qui
se passe et une barre de progression (§ 4.1).

Aucun code à ce stade. Étape 293 (station inchangée, 0.226.0).

## 1. Décisions de l'utilisateur (2026-11-19)

1. **Public** : radioamateurs (ils ont passé l'examen et connaissent leur station) et cibistes, qui en savent autant.
   Pas seulement les qualifieurs du projet.
2. **Émission permise dans les deux modes**, sur CHARGE FICTIVE, l'opérateur DEVANT son poste. Une seule autorisation au
   départ, après un écran qui annonce ce qui va se passer. L'opérateur sait couper son poste à la main : un plantage de
   la page n'est pas un danger. Pas de superviseur, pas de mots à taper à chaque essai.
3. **Pas de sécurités superflues** : les logiciels courants (WSJT-X, fldigi…) émettent par la CAT sans en faire autant.
   On garde seulement le minimum du § 5, qui ne gêne pas l'opérateur.
4. **Marque choisie par des boutons** au départ ; la détection automatique confirme ou précise le modèle.
5. **Le mode B est intéressant parce qu'il est automatique** : la valise (`trx-qualif --terrain --page`) est complexe à
   manipuler ; ici tout s'enchaîne seul après l'autorisation unique.
6. **Xiegu** : traité comme un dialecte du CI-V d'Icom (§ 6.1).
7. **Le rapport est important** : envoi le plus simple possible, sans formulaire complexe, et données vérifiables
   (§ 9).
8. **Mode B ultra simple**, le moins de manipulations possible ; Windows d'abord, passerelle proposée sur le
   Microsoft Store (§ 8.1).
9. **Langues** : français et anglais.
10. **Pas d'Android.**
11. **Nom du programme** : « openRemoteTRX-Autotest » (commande Linux `trx-autotest`) ; compilé en EXE, pas un Python
    à installer (§ 8.1).
12. **Courriel facultatif** pour être recontacté : interrupteur sur ARRÊT par défaut, le champ n'apparaît que sur
    MARCHE (§ 9.1).
13. **Anonymat annoncé dès l'accueil** : le test est anonyme, rien ne part vers rf-diy.com pendant le test ; seul le
    bouton « Envoyer le rapport » de la fin envoie quelque chose, et seulement si l'opérateur le veut.
14. **Préqualifications non publiées** sur le site public pour l'instant (gestion future dans une base de données).
15. **Autres langues plus tard.**
16. **Puissance des essais** : 10 % de la puissance maximale DU POSTE (pas 10 W), puis puissance d'origine remise
    (§ 5.1).
17. **Changement de fréquence permis** pendant le test (§ 6.5, essai R8), fréquence d'origine remise à la fin.
18. **Durées** : 10 s au plus par émission, environ 5 émissions, à condition que l'écran dise à chaque instant ce qui
    se passe, avec une barre de progression pour rassurer l'opérateur (§ 4.1).

EXCEPTION aux règles de sécurité d'émission de CLAUDE.md : elles visent la STATION pilotée À DISTANCE. La
préqualification est un outil LOCAL, l'opérateur présent devant le poste sur charge fictive ; elle ne passe ni par la
passerelle ni par le superviseur et n'en garde que le § 5.

## 2. Ce que la page doit dire à la fin

Un rapport clair, en vert / orange / rouge :

- le poste répond-il par l'USB (port, vitesse, adresse CI-V ou identifiant) ;
- quel modèle et, si lisible, quelle version du firmware ;
- **Hamlib le reconnaît-il, et depuis quelle version** (ex. « IC-7300MK2 : Hamlib 4.7 ou plus ; Debian 13 n'a que la
  4.6 ») ;
- lecture de la fréquence, du mode, du S-mètre, de l'état du PTT, temps de réponse ;
- carte son du poste trouvée (entrée et sortie), niveau du bruit de réception ;
- émission : passage en émission et retour par la CAT (ou par RTS / DTR), puissance et TOS lus, tonalité envoyée par
  la carte son en mode données (Po et ALC qui montent) ;
- ce qui manque ou ce qui coince, en clair, avec ce qu'il faut faire (câble, réglage du menu du poste, vitesse…) ;
- mode A : « sans Hamlib, la station peut encore avoir des surprises : passez au mode B pour en savoir plus ».

## 3. Contraintes techniques (à vérifier au lot PQ1)

- **Web Serial** : Chrome et Edge sur PC (Windows, Linux, macOS). Firefox et Safari : non (la page le dit et propose
  Chrome). Page en HTTPS ou sur 127.0.0.1. Le port est choisi par l'opérateur dans la fenêtre de Chrome ; Chrome se
  souvient de l'autorisation. Un port déjà ouvert (station, rigctld, logiciel du constructeur, WSJT-X) est REFUSÉ : la
  page le dit en clair. Les lignes RTS / DTR se commandent (`setSignals`) : PTT par RTS / DTR des interfaces type
  Digirig possible.
- **WebUSB n'est PAS utilisé** : sous Windows le pilote série tient déjà le périphérique.
- **Carte son du poste** : `getUserMedia` (entrée) et `setSinkId` (sortie) ; les noms des cartes ne sont lisibles
  qu'après l'autorisation du micro. Le nom de la carte change selon le poste (C-Media « USB Audio Device » pour
  l'IC-7300MK2, « USB AUDIO CODEC » pour le FTDX10) : la page propose la carte la plus probable, l'opérateur confirme.
  Traitements de Chrome coupés (`echoCancellation`, `noiseSuppression`, `autoGainControl` à false).
- **Page dans une iframe** (site rf-diy.com) : Web Serial exige `allow="serial"` sur l'iframe ; sinon, lien vers la
  page publiée.
- **Android** : hors du projet (décision du 2026-11-19).
- **Mode B** : une page publique (GitHub Pages) qui parlerait à un programme sur 127.0.0.1 déclenche maintenant une
  demande d'accès au réseau local de Chrome, incompréhensible pour l'opérateur. Le programme local SERT donc lui-même
  la page (comme la valise).

## 4. Déroulé (identique dans les deux modes)

1. **Accueil** : ce que fait la page, ce qu'il faut (câble USB, charge fictive, Chrome), ce qui va se passer (les
   émissions : combien, combien de temps, à quelle puissance), langue. En évidence : « Le test est anonyme. Rien
   n'est envoyé pendant le test, ni à rf-diy.com ni ailleurs. À la fin, vous pourrez envoyer le rapport au projet si
   vous le voulez. » Pendant le test la page ne contacte AUCUN serveur (vérifiable dans les outils de Chrome).
2. **Marque** : boutons (Icom, Yaesu, Kenwood, Elecraft, Xiegu, Autre). « Autre » = mode A impossible, mode B proposé.
   Modèle proposé ensuite en boutons (liste de la marque), « Je ne sais pas » permis.
3. **Branchement** : choix du port dans la fenêtre de Chrome (mode A) ou liste des ports (mode B).
4. **Détection** : vitesses courantes essayées, identification du modèle (§ 6) ; écart avec le modèle choisi = question.
5. **Relevé de l'état d'origine** : fréquence, mode, puissance réglée, et ce que le protocole permet de relire.
6. **Essais en réception** (aucune émission).
7. **Autorisation unique d'émettre** : la fréquence et la puissance qui seront utilisées sont affichées ;
   case « Mon poste est sur charge fictive » + bouton « J'autorise les émissions d'essai ». Refus = rapport sans
   émission.
8. **Essais en émission**, enchaînés automatiquement.
9. **Remise de l'état d'origine**, relue et montrée.
10. **Rapport** (§ 9).

### 4.1 Écran pendant les essais

- Barre de progression GÉNÉRALE (étape N sur M, temps restant estimé) toujours visible.
- Ligne « en ce moment » en clair : « Lecture du S-mètre… », « Changement de fréquence (+1 kHz)… », « Puissance mise
  à 10 % (10 W)… ».
- Avant chaque émission : ce qui va être émis (porteuse, tonalité), fréquence, puissance, durée.
- PENDANT une émission : bandeau rouge « ÉMISSION EN COURS » avec le compte à rebours de l'essai (barre qui se vide),
  bouton STOP agrandi, et PANNEAU D'ÉMISSION « pro » (demande de l'utilisateur, v4) à la manière de l'afficheur d'un
  poste :
  - fréquence en grands chiffres (MHz.kHz.Hz) et mode ;
  - puissance de sortie (Po) : barre graduée de 0 à la puissance maximale du poste, valeur en W, repère des 10 %
    attendus ;
  - TOS (SWR) : échelle non linéaire 1 / 1,5 / 2 / 3 / ∞, vert jusqu'à 1,5, orange jusqu'à 2, rouge au-delà (alerte
    seule, comme la règle de la station) ;
  - ALC : barre avec la zone « correcte » du constructeur quand elle est connue ;
  - pour chaque barre : valeur en chiffres et crête maintenue (1 s) ; lue environ 5 fois par seconde ;
  - mesure que le poste ne donne pas = barre grisée « non disponible », jamais une valeur inventée ;
  - valeurs gardées dans la trace du rapport (§ 9.2 : elles servent aussi à vérifier sa vraisemblance) ;
  - maquette : https://claude.ai/artifact/P6YoyvkAhzhafUhqRmjPLQ (privée).
- Après chaque essai : coche verte, croix rouge ou « non disponible », avec une phrase.
- Liste des étapes à venir visible (l'opérateur sait ce qui l'attend).

## 5. Sécurités gardées (le minimum)

- Aucune émission avant l'autorisation du § 4.7.
- **Durée maximale de chaque essai d'émission** fixée par l'essai (10 s au plus), retour en réception par la page.
- **Retour en réception** à toute erreur de la page, onglet caché (`visibilitychange`), fermeture (`pagehide`), port
  perdu ; puis PTT relu.
- **STOP** : gros bouton toujours visible et touche Échap (= retour en réception, fin des essais).
- La page n'écrit au poste que dans une **liste fermée** de commandes par modèle (jamais un réglage de menu, jamais un
  essai au hasard d'une commande non documentée).
- Après tout cela, l'opérateur reste maître : son interrupteur et son micro.

### 5.1 Puissance des essais

- Puissance d'origine relevée au § 4.5, puis réglée à 10 % de la puissance maximale DU POSTE (table du modèle :
  100 W => 10 W, IC-705 10 W => 1 W ; Hamlib `RFPOWER` 0,10 en mode B ; Icom `14 0A` à l'échelle 0-255).
- Poste dont la puissance minimale dépasse 10 % : sa puissance minimale, affichée comme telle.
- Puissance réglée RELUE avant la première émission ; illisible ou refusée = l'autorisation montre « puissance non
  réglable par la CAT : réglez-la à la main sur 10 % » et attend l'accord de l'opérateur.
- Puissance d'origine remise à la fin, relue et montrée (aussi après STOP ou une erreur).
- E2 vérifie que la puissance lue pendant l'émission est cohérente avec ces 10 %.

## 6. Mode A : pilotes par famille de protocoles

Un pilote par FAMILLE, une table par MODÈLE (données JSON de la page : famille, adresse ou identifiant, vitesses,
commandes permises, modes données, mesures disponibles, source documentaire, état « vérifié sur un vrai poste » ou non).
Documents des constructeurs HORS du dépôt (`C:\dev\postes-docs\`) ; seules les commandes utilisées sont écrites dans le
code. La documentation peut se tromper : chaque modèle reste « non vérifié » tant qu'un vrai poste n'est pas passé.

### 6.1 Icom CI-V (et Xiegu)

- Trames `FE FE <poste> <contrôleur> … FD`, écho du bus à ignorer, réponses NG (`FA`).
- Identification : `19 00` (adresse du poste), sinon adresses par défaut des modèles de la marque choisie.
- Lectures : fréquence `03`, mode `04`, S-mètre `15 02`, PTT `1C 00`, Po `15 11`, TOS `15 12`, ALC `15 13`,
  puissance réglée `14 0A`, mode données `1A 06` (selon le modèle) ; spectre (essai R10) : affichage `27 10` et sortie
  `27 11` lus, mis en marche, trames `27 00` écoutées, puis remis comme ils étaient (la page n'envoie jamais de `27 00`).
- Écritures (liste fermée) : PTT `1C 00`, fréquence `05` (essai R8), mode et mode données pour la tonalité, puissance
  `14 0A` pour l'essai, puis remise.
- **Xiegu** (G90, G106, X6100, X6200, X5105) : dialecte partiel du CI-V. Une commande non gérée peut rester SANS
  réponse (pas de NG) : silence = « non supporté », délai court, jamais « câble en panne ». `19 00` peut ne pas répondre :
  adresses connues des modèles. Firmware (officiel ou communautaire) relevé et noté : un résultat ne vaut que pour lui.
  Documentation maigre : sources de Hamlib et relevés sur un vrai poste en complément.

### 6.2 Kenwood, Elecraft, Yaesu « nouveau » (ASCII terminé par `;`)

- Identification `ID;` (numéro du modèle) ; `FA;`, `MD;`, `SM0;`, `TX;` / `RX;` (Yaesu : `TX1;` / `TX0;`), mètres
  `RM…;`, puissance `PC;`, `IF;` selon la marque. Réponse `?;` = refusée.
- Variantes par marque et par modèle dans la table ; Elecraft proche de Kenwood.
- Poste lent (piège du FTDX10) : délais par commande, une lecture facultative trop lente est abandonnée, jamais la
  liaison.

### 6.3 Yaesu ancien (trames de 5 octets : FT-817 / 857 / 897…)

- Protocole pauvre (peu de lectures, pas d'accusé de réception) ; lot plus tardif.

### 6.4 Autres marques

- Mode A non prévu : mode B.

### 6.5 Essais du mode A

| Code | Essai | Émission |
|---|---|---|
| R1 | Port ouvert, vitesse trouvée | non |
| R2 | Modèle identifié (et firmware si lisible) | non |
| R3 | Fréquence et mode lus, cohérents d'une lecture à l'autre | non |
| R4 | S-mètre lu, il bouge (antenne) ou reste bas (charge) | non |
| R5 | Temps de réponse (médiane, pire cas) | non |
| R6 | PTT lu = réception | non |
| R7 | Carte son du poste : entrée trouvée, niveau du bruit de réception | non |
| R8 | Écriture de la fréquence (+1 kHz dans la même bande) et du mode, relues, puis remises | non |
| R9 | Fonctions du poste (ATT, P.AMP, NB, NR, RIT, split, VFO…) : lues, changées, relues, remises | non |
| R10 | Spectre (waterfall) : balayages complets reçus en 3 s, nombre de points, fréquence du poste dans le balayage, niveaux dans l'échelle, affichage et sortie remis ; Icom en mode A seulement (étape 367, Autotest 0.8.0), « non disponible » ailleurs ; trames adressées à un autre contrôleur comptées, jamais reprises | non |
| E1 | Émission par la CAT puis retour, PTT relu, temps mesurés | oui |
| E2 | Puissance (Po) lue pendant l'émission, non nulle | oui |
| E3 | TOS lu (charge fictive : bas) | oui |
| E4 | Tonalité 1 kHz par la carte son en mode données : Po et ALC montent | oui |
| E5 | Émission par RTS ou DTR (si l'opérateur utilise une interface de ce type) | oui |
| E6 | Retour en réception par STOP de la page, PTT relu | oui |

Un essai que le modèle ne permet pas est « non disponible », jamais un échec.

## 7. Liste des modèles de Hamlib embarquée

- Fabriquée par un script du dépôt d'après les sources de Hamlib (versions publiées) : numéro de modèle, nom, état
  dans Hamlib, PREMIÈRE version qui le connaît, versions des distributions courantes (Debian stable, backports,
  Raspberry Pi OS) et Windows.
- Sert au rapport du mode A et prépare le mode B (numéro de modèle à lancer).

## 8. Mode B : avec Hamlib, automatique

- Commande `trx-autotest` (même code Python que `trx-qualif` : exploration en lecture, liste fermée d'écritures,
  constats de cohérence, étapes de `trx-hwtest`) : lance SON rigctld sur un port libre (jamais celui de la station,
  refus si la station tourne), sert la page sur 127.0.0.1 avec un jeton, ouvre le navigateur.
- MÊME page que le mode A : une couche « transport » choisit le pilote (Web Serial en mode A, API locale en mode B).
- Ajouts du mode B : tout ce que Hamlib déclare (`dump_caps`) essayé en lecture, plages déclarées vérifiées, lectures
  qui font tomber rigctld retenues (piège de l'étape 255), temps de réponse par commande, essai des filtres et du
  second port seulement si l'opérateur le demande.
- Comparaison A / B quand les deux ont tourné : ce que dit la documentation contre ce que fait Hamlib = matière pour un
  rapport à Hamlib (`docs/hamlib-rapports.md`).
- Installation : § 8.1.
- La valise reste l'outil de QUALIFICATION (pannes, superviseur, station complète) ; le rapport du mode B peut la
  préremplir.

### 8.1 openRemoteTRX-Autotest : passerelle ultra simple, Microsoft Store

- Un seul programme « openRemoteTRX-Autotest » : installé depuis le Microsoft Store, lancé depuis le menu
  Démarrer ; il ouvre lui-même Chrome / Edge sur sa page (127.0.0.1, jeton), une icône près de l'horloge, fermer la page
  ou l'icône = arrêt. Aucune question d'installation, aucun réglage, aucun pare-feu (écoute sur 127.0.0.1 seulement).
- Contenu : un EXE natif + rigctld.exe et les DLL de Hamlib pour Windows (version épinglée, empreinte vérifiée à la
  fabrication) ; ni la station, ni le superviseur, ni la passerelle. Rien à installer à côté (pas de Python).
- EXE (décision v3) : le code reste écrit en Python, PARTAGÉ avec `trx-qualif` (une seule implémentation des essais),
  et il est COMPILÉ en C puis en EXE par Nuitka. Écartés : PyInstaller (un Python caché dans une archive, démarrage
  lent, souvent pris pour un virus) et une réécriture en Go ou Rust (deux codes des essais à tenir d'accord).
- Hamlib par rigctld.exe, processus à part, et non par la DLL chargée dans l'EXE : un défaut de Hamlib qui fait planter
  (lecture `KEYERTYPE`, étape 255) ne tue que rigctld, l'EXE le relance et retient la lecture fautive.
- Paquet MSIX : le Store le signe lui-même (pas de certificat de signature de code à acheter, pas d'avertissement
  SmartScreen), mises à jour par le Store ; accès aux ports série = application « pleine confiance » (`runFullTrust`).
- Licences : Hamlib (LGPL / GPL) livré avec l'offre des sources ; notre code AGPL ; mentions dans la fenêtre « À
  propos ».
- À vérifier au lot PQ5 : compte développeur Microsoft (conditions et coût pour un particulier), délai et règles de
  certification (faux positifs des antivirus à surveiller même avec Nuitka), taille du paquet, compilation Nuitka de
  aiohttp et des autres modules utilisés.
- Aussi publié en zip sur les Releases GitHub (même programme) et par `winget` plus tard ; Linux : commande
  `trx-autotest` du paquet de la station (pas de Store).

## 9. Rapport

- Page imprimable + fichier JSON téléchargeable (format proche de `docs/postes/donnees/*.toml` : `[poste]`,
  `[[essais]]`), niveau « préqualification navigateur (sans Hamlib) » ou « préqualification Hamlib ».
- Anonyme : ni adresse, ni nom de machine, ni numéro de série (les noms de ports et de cartes son sont nettoyés).
- Ne modifie PAS les fiches publiques des postes (seules les qualifications y entrent) ; usage : § 11, question 8.

### 9.1 Envoi en un bouton (proposition de la v2)

- Bouton « Envoyer le rapport au projet » à la fin ; avant l'envoi, la page MONTRE ce qui part (résumé lisible + « voir
  le détail »). Champs FACULTATIFS : indicatif, commentaire libre. Aucun compte exigé.
- Interrupteur « Je veux que le projet puisse me recontacter » sur ARRÊT par défaut : sur MARCHE, un champ « Adresse
  de courriel » apparaît (format vérifié, rien de plus) ; repassé sur ARRÊT, le champ est vidé et rien ne part. Texte à
  côté : l'adresse ne sert qu'à vous répondre au sujet de ce rapport, n'est jamais publiée ni transmise, effacée sur
  simple demande (avec le numéro du rapport). Rangée À PART du rapport sur le serveur (le rapport reste anonyme pour
  qui l'étudie).
- Envoi en HTTPS vers un petit service du projet sur le VPS de diffusion (dépôt privé `openRemoteTRX-vps`, même Caddy) :
  reçu, stocké, numéro de rapport rendu à l'opérateur (à citer s'il écrit au projet). Limite de débit par adresse.
- Écartés : ticket GitHub prérempli (compte GitHub exigé, rapport trop long pour une adresse), courriel (logiciel de
  messagerie, taille), dépôt de fichier sur un site.
- Le bouton « Télécharger le rapport » reste (pour le garder, ou l'envoyer plus tard).

### 9.2 Rapports truqués

On ne peut PAS prouver qu'un rapport est vrai : le code de la page est public, tout secret qu'elle contiendrait aussi
(une signature par la page ne prouve rien ; le programme du Store non plus). Le but : rendre un faux COÛTEUX et SANS
EFFET.

1. **Trace brute jointe** : chaque octet envoyé et reçu par le port série (mode A) ou chaque commande et réponse de
   rigctld (mode B), horodaté, avec les mesures du son. Le SERVICE recalcule lui-même les résultats depuis la trace
   avec le même code de pilote : les conclusions écrites par la page ne sont jamais crues.
2. **Rapport rejoué** : la v2 proposait un jeton demandé au serveur AU DÉBUT des essais ; RETIRÉ en v3 (la page ne
   contacte aucun serveur pendant le test, § 4). À la place : empreinte de la trace gardée par le service, un rapport
   déjà reçu (même trace) est refusé ; horodatages de la trace comparés à l'heure de réception.
3. **Cohérence physique** vérifiée par le service : identité du poste (`19 00`, `ID;`) cohérente avec le modèle choisi,
   format exact des trames du modèle, écho CI-V, temps de réponse plausibles et non réguliers, S-mètre qui varie,
   puissance lue en émission compatible avec la puissance réglée, PTT relu après chaque retour, ALC et Po qui montent
   avec la tonalité. Inventer une trace cohérente demande de connaître le protocole aussi bien que le pilote.
4. **Poids** : un rapport seul = « signalé par un utilisateur », jamais un changement de fiche ; plusieurs rapports
   CONCORDANTS et indépendants (indicatifs, firmwares, dates différents) font monter la confiance ; un rapport
   discordant est relu par le mainteneur ; la QUALIFICATION (valise) reste seule à valider un poste.
5. **Indicatif facultatif** vérifiable plus tard (annuaire, réponse à un courriel) pour les rapports qui feraient
   changer une fiche.
6. **Anonymat** : aucune adresse IP gardée avec le rapport (seulement pour la limite de débit, effacée après 24 h),
   noms de ports et de cartes nettoyés, numéro de série du poste jamais envoyé.

## 10. Où vit le code

- Sources de la page dans le dépôt (`prequalif/` ou `docs/site/prequalif/`, à fixer au lot PQ1), en-têtes SPDX, tests
  Node des pilotes (trames, analyses de réponses) avec de vraies trames relevées sur les postes du projet.
- Mode A publié sur GitHub Pages (`https://bob56fr.github.io/openRemoteTRX/prequalif/`), bloc WordPress avec
  `allow="serial"` à essayer.
- Mode B dans `trxstation/` (paquet Python), page servie depuis les mêmes fichiers.

## 11. Questions ouvertes

TOUTES TRANCHÉES (v4).

1. ~~Puissance~~ : 10 % de la puissance maximale du poste (§ 5.1).
2. ~~Fréquence~~ : changement permis (R8), fréquence d'origine remise.
3. ~~Durées~~ : 10 s au plus, environ 5 émissions, écran et barre de progression (§ 4.1).
4. ~~Rapport~~ : TRANCHÉ (un bouton, courriel facultatif derrière un interrupteur, § 9.1).
5. ~~Mode B~~ : TRANCHÉ (openRemoteTRX-Autotest, EXE, Microsoft Store, § 8.1).
6. ~~Langues~~ : TRANCHÉ (français et anglais).
7. ~~Android~~ : TRANCHÉ (non).
8. ~~Rapports reçus sur le site public~~ : TRANCHÉ (non pour l'instant ; base de données plus tard). Question d'origine : la page publique des postes
   (https://bob56fr.github.io/openRemoteTRX/postes/) ne montre aujourd'hui que les postes QUALIFIÉS par le projet.
   Montrer aussi ce que disent les rapports reçus (« IC-7300 : 4 rapports d'utilisateurs, tous OK » ; « Xiegu G90 :
   1 rapport, PTT par la CAT en échec »), dans une partie à part et après relecture ? Ou garder les rapports pour le
   projet seulement ?

## 12. Lots

| Lot | Contenu | Poste d'essai |
|---|---|---|
| PQ0 | Ce cahier, questions tranchées | — |
| PQ1 (FAIT, étape 294, Autotest 0.1.0 ; essai réel à faire) | Page mode A : accueil, marque, port, CI-V Icom, essais R1 à R7, autorisation, E1 à E4 et E6, remise, rapport | IC-7300MK2, IC-705 |
| PQ2 | Famille ASCII : Yaesu nouveau, Kenwood, Elecraft ; E5 (RTS / DTR) | FTDX10 |
| PQ3 | Xiegu (dialecte CI-V) et Yaesu ancien, marqués « non vérifié » sans poste | bêta-testeur |
| PQ4 | Liste des modèles de Hamlib embarquée (§ 7) | — |
| PQ5 (partie 1 FAITE, étape 337, Autotest 0.7.0 : `python -m trxstation.autotest`, page servie, `hamlib.js` ; restent l'exploration de tout `dump_caps`, la comparaison A / B, la commande `trx-autotest` et l'EXE) | Mode B : `trx-autotest`, page servie, transport « API locale », comparaison A / B | IC-7300MK2, FTDX10 |
| PQ6 (FAIT en partie, étape 296, Autotest 0.6.0 : anglais, GitHub Pages, lien WordPress ; reste le guide) | Publication (GitHub Pages, lien plutôt qu'iframe : Web Serial), langues, guide de l'opérateur | — |

### 12.1 Lot PQ5, partie 1 (étape 337, Autotest 0.7.0)

- Programme local `python -m trxstation.autotest` (`trxstation/autotest/` : `main.py`, `server.py`, `rig.py`) :
  refuse de démarrer si la station tourne ; sert la page de `autotest/web/` sur 127.0.0.1 (port 8767 par défaut) avec
  un jeton à usage unique échangé contre un cookie ; Host et Origin vérifiés ; fichiers en liste fermée ; la CSP de
  index.html est ouverte à la SEULE API de même origine (`connect-src 'self'`) et la balise
  `<meta name="autotest-mode" content="hamlib">` annonce le mode B à la page. La page publiée (mode A) reste fermée.
- rigctld PROPRE à l'Autotest, sur un port libre, `cache_timeout=0`, lancé à « Se connecter au poste » (modèle choisi
  dans la liste de `rigctl -l`, port série, vitesse) ; capacités lues par `rigctl -m N -u` ; relancé s'il tombe
  (commande fautive retenue).
- LISTE FERMÉE des commandes rigctld (`rig.check_command`) : lectures f, m, t, s, j, niveaux et fonctions nommés ;
  écritures F, M <mode> 0 (largeur TOUJOURS 0), T 0 / 1, L (RFPOWER, ATT, PREAMP, NR, NB, COMP, bornés), U (NB, NB2,
  NR, ANF, COMP, MN, APF, RIT), G XCHG. JAMAIS : VOX, coupleur (un accord = une émission sur certains postes), split
  (piège de l'IC-7300MK2), XIT, alimentation, commandes brutes, menus.
- GARDE DU PROGRAMME, indépendante de la page : après un « T 1 », « T 0 » par une connexion à part si l'émission dure
  plus de 12 s, si la page ne fait plus aucune requête pendant 3 s, à la déconnexion et à l'arrêt du programme ; la
  page garde ses coupures (10 s, STOP, Échap, onglet caché, fermeture : « T 0 » envoyé aussi au programme).
- Page : choix « Tous les postes (Hamlib) » en tête des marques en mode B ; écran « Poste piloté par Hamlib »
  (modèle, port, vitesse) ; pilote `hamlib.js` à la même interface que les pilotes du mode A (runner.js inchangé
  hormis R1 / R2) ; fonctions de R9 tirées des capacités déclarées ; rapport : `outil.mode` = B, bloc `poste.hamlib`
  (nom, version, statut du backend).

## 13. Limites assumées

- Le mode A valide la documentation du constructeur, PAS Hamlib : il ne prévoit pas les défauts de Hamlib déjà
  rencontrés (lecture qui fait tomber rigctld, split qui échange les VFO, plage déclarée fausse, cache).
- Un modèle jamais branché sur un vrai poste reste « non vérifié » dans la table.
- Chrome et Edge seulement pour le mode A.

## Annexe : pilote USB Icom et Web Serial (essai du 2026-11-19)

Avec le pilote USB Icom 1.70 (IC-7300MK2, IC-705, IC-905, identifiant USB 0C26), tout Chrome se fige dès qu'une lecture attend sur un port vide. Icom l'a corrigé dans le pilote 1.80 (Windows 11). La page l'exige pour ces postes sous Windows ; Windows 10 (pas de pilote 1.80 annoncé) : mode B. Diagnostic : `autotest/web/diag.html`.
