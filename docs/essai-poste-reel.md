# Essai sur un vrai poste (Windows, Linux ou Raspberry Pi)

Objectif : vérifier, **par étapes de risque croissant**, que le logiciel pilote réellement ton poste :
liaison CAT, son reçu, accord, PTT, son émis, et surtout **coupure de l'émission en cas de panne**.
L'outil `trx-hwtest` déroule ces étapes et demande une confirmation explicite (`EMETTRE`) avant toute émission.

## 1. Règles de sécurité (non négociables)

1. **Charge fictive** de 50 Ω (puissance suffisante) à la place de l'antenne. Pas d'antenne pour cet essai.
2. **Puissance minimale** sur le poste (5 W ou moins).
3. **VOX désactivé.**
4. **Temporisation d'émission INTERNE du poste (TOT) réglée à 1–3 minutes.** C'est le dernier filet : si le PC,
   le logiciel ou le câble USB lâche pendant une émission, le poste coupe seul.
5. **Reste à côté du poste**, main près de l'interrupteur d'alimentation.
6. **Aucun autre logiciel** qui utilise le poste (WSJT-X, fldigi, HRD, N1MM...) : il prendrait le port COM ou la carte son.
7. Ta licence t'autorise à émettre sur la fréquence utilisée.

Arrêt d'urgence : `Ctrl+C` dans le terminal (l'émission est coupée), sinon coupe l'alimentation du poste.

## 2. Réglages à vérifier dans le menu du poste (les noms varient selon le modèle : voir le manuel)

- **TOT / Time-Out Timer** : 1 à 3 min (voir règle 4).
- **VOX** : OFF.
- **Source de modulation en émission** : l'entrée **USB** (Icom : « DATA MOD » / « MOD input » ; Yaesu : « DATA IN SELECT »...).
- **Niveau d'entrée USB en émission** (Icom « USB MOD Level ») : au **minimum** pour commencer.
- **Niveau de sortie USB en réception** (Icom « USB AF Output Level ») : moyen.
- **CAT** : débit (noter la valeur : `trx-setup` la demande), « CI-V Transceive » OFF (Icom). Si le PTT passe par RTS/DTR, prévoir la
  charge fictive dès le démarrage de `rigctld` : l'ouverture du port peut provoquer une brève émission.

## 3. Préparer Windows

- **Pilote USB** du poste installé (souvent Silicon Labs CP210x). Gestionnaire de périphériques > *Ports (COM et LPT)* :
  noter le numéro COM (certains postes en exposent deux ; le port CAT est en général le premier / « Enhanced »).
- **Hamlib** : télécharger `hamlib-w64-4.x.zip` (hamlib.github.io), le décompresser (ex. `C:\hamlib-w64-4.5.5`).
  `trx-setup` demandera ce dossier s'il ne trouve pas `rigctl.exe`.
- **Son** (Paramètres > Système > Son) :
  - la carte son du poste (« USB Audio CODEC ») n'est **ni la sortie ni l'entrée par défaut** ;
  - Paramètres > Personnalisation > Thèmes > Sons : schéma **« Aucun son »** (sinon une notification Windows pourrait partir en émission) ;
  - propriétés de la carte son > Avancé : format **48000 Hz, 16 bits** ; désactiver les améliorations audio ;
  - Paramètres > Confidentialité > Microphone : **autoriser les applications de bureau** (sinon la capture renvoie du silence).
- **Veille / hibernation** désactivées pendant l'essai.

## 4. Configurer

```
python -m pip install -e ".[dev,monitor,audio]"
trx-setup -o station.toml
```
`trx-setup` détecte les ports COM et les cartes son, te laisse choisir le modèle de poste (recherche par nom), teste la liaison CAT
**en lecture seule**, et propose des bandes d'émission **à vérifier selon ta licence** (sans bande, l'émission est impossible).
Vérifie que `station.toml` contient : le bon `model`, le `port` (COMx), la bonne `speed`, `capture_device` / `playback_device`
(noms de la carte son du poste), et tes `[[bands]]`.

## 5. Lancer l'essai

```
trx-hwtest --config station.toml
```
(`--tot 8` : durée du TOT pendant l'essai ; `--tx-levels -40 -30 -24` : niveaux de la tonalité, jamais au-dessus de -12 dBFS.)

| Étape | Ce qui se passe | Émission ? | Attendu |
|---|---|---|---|
| 1. CAT | lecture fréquence, mode, PTT, S-mètre | non | fréquence correcte, PTT lisible en réception |
| 2. Audio RX | mesure 5 s, écrit `hwtest_rx.wav` | non | niveau moyen entre -40 et -15 dBFS ; **écoute le WAV** |
| 3. Accord | +1 kHz puis retour | non | fréquence relue sur le poste |
| 4. PTT | 3 cycles de porteuse **sans audio** | oui (confirmation) | voyant TX du poste, prise et coupure < 1 s |
| 5. Audio TX | tonalité 1 kHz à -40, -30, -24 dBFS | oui (confirmation) | ALC à peine visible, ROS < 2 |
| 6. Pannes | perte du heartbeat, TOT, déconnexion | oui (confirmation) | coupure dans les délais annoncés |

En SSB, les étapes 4 et 6 n'émettent pratiquement aucune puissance (pas de modulation) ; elles contrôlent le PTT et sa coupure.
À l'étape 5, monte le niveau **progressivement** : si l'ALC bouge ou si la puissance dépasse ce qui est prévu, réponds `n` à « plus fort ».

## 6. Réglages d'après les résultats

- **RX trop faible / trop fort** : ajuste d'abord le niveau de sortie USB du poste, puis `rx_gain_db` (suggestion affichée).
- **TX** : règle le niveau d'entrée USB du poste pour que l'ALC reste à peine visible au niveau de modulation normal ;
  `tx_gain_db` ne sert qu'à l'ajustement fin (garde-le ≤ +6).

## 7. Si quelque chose échoue

| Symptôme | Causes probables |
|---|---|
| « rigctld ne démarre pas » / CAT injoignable | Hamlib introuvable ; COM occupé par un autre logiciel ; mauvais modèle ou débit ; poste éteint ; câble |
| Fréquence illisible mais rigctld répond | débit CAT différent de celui du poste ; mauvais port COM (essayer l'autre port) |
| Audio RX « silence total » | mauvais périphérique ; autorisation microphone Windows ; sortie USB du poste à zéro |
| Audio RX saturation | niveau de sortie USB trop haut |
| PTT refusé `ptt_unreadable` | ce poste ne permet pas de relire l'état du PTT : **ne continue pas, envoie-moi le résultat** |
| PTT refusé `out_of_band` | fréquence hors des `[[bands]]` : accorde le poste dans une bande autorisée |
| Prise/coupure > 1 s | débit CAT trop bas, ou poste lent à répondre |
| Audio TX « trames non transmises » | périphérique de lecture mal choisi ; porte d'émission fermée |
| ROS > 2 | charge fictive ou câble défaillants : arrêter |
| **« L'ÉMISSION N'A PAS ÉTÉ COUPÉE »** | **COUPE L'ALIMENTATION. N'enchaîne pas. Envoie-moi le bilan complet.** |

## 8. Ce qu'il faut me renvoyer en cas de problème

Le **bilan complet** du terminal, le **modèle exact** du poste, le contenu de `[rig]` et `[audio]` de `station.toml`
(sans les jetons de `[[clients]]`), la version de Windows et la sortie de `rigctl --version`.


## 9. Cas particuliers rencontrés

### Icom IC-7300 / IC-7300MK2 (Hamlib 3073 / 3094)
Noms de menu de l'IC-7300, très proches sur le MK2 : **à vérifier dans ton manuel**.
- **SET > Function > Time-Out Timer (CI-V)** : 3 minutes (le TOT interne qui coupe si le PC lâche).
- **SET > Connectors > CI-V** : *CI-V Transceive* OFF, *CI-V USB Port* : « Unlink from [REMOTE] », *CI-V USB Echo Back* OFF.
- **SET > Connectors > MOD Input** : *DATA MOD* = **USB** ; **USB MOD Level** au minimum pour commencer.
- **SET > Connectors > USB AF Output Level** : moyen.
- **Mode données** : l'audio USB n'est émis qu'en mode **USB-D** (Hamlib : `PKTUSB`). En USB « normal », la modulation vient du micro.
  `trx-hwtest` te propose de basculer en `PKTUSB` avant l'étape audio d'émission, et rétablit le mode ensuite.

### Fréquence hors bandes (ex. 27 MHz)
Si le poste est sur une fréquence hors des `[[bands]]`, l'émission est refusée (`out_of_band`). `trx-hwtest` propose alors
d'accorder le poste au milieu d'une bande autorisée (étape « Fréquence d'essai »). Vérifie que ta licence couvre cette bande.

### Voicemeeter / VB-Cable installés
Dans Voicemeeter, **aucune sortie matérielle (A1…A5) ne doit être réglée sur « Haut-parleurs (USB Audio …) » du poste** :
tout son passant par Voicemeeter partirait en émission pendant le PTT. Idem pour VB-Cable : ne pas l'acheminer vers le poste.
Les périphériques du poste portent souvent un nom générique (« USB Audio Device ») : vérifie lequel est le poste
(débranche/rebranche le câble USB et regarde lequel disparaît de la liste).

### Diagnostic d'un format de réponse inattendu
Les versions de Hamlib répondent parfois autrement (valeurs sans libellé, par exemple). Le logiciel est tolérant, mais si une
lecture échoue, lance `trx-rigctld --config station.toml` dans une fenêtre, puis dans une autre :
```
python -m trxstation.devtools.cat_raw --port 4532 f m t "l STRENGTH" "l ALC"
```
Cet outil est en lecture seule (il ne sait pas accorder ni émettre) et affiche les réponses brutes dans les deux formats :
copie-moi sa sortie.

## 10. Protéger ta configuration
`station.toml` contient les **empreintes des mots de passe** des clients (et, s'il en reste, d'anciens jetons en clair). Il ne doit jamais être publié : ajoute à `.gitignore`
`station.toml`, `station.toml.bak` et `dev.toml` (si tu les as déjà ajoutés à Git : `git rm --cached station.toml station.toml.bak`).
Un mot de passe généré par `trx-setup` est affiché une seule fois à l'écran : note-le, ou change-le avec
`trx-setup --set-password NOM -o station.toml`. Les anciens jetons en clair (`token = ...`) sont à remplacer de la même façon.


## 11. Essai de la page web sur le PC de la station (réception, micro, émission)

Page : `http://127.0.0.1:8443/` dans Chrome, sur le PC qui porte la station (la boucle locale autorise le micro sans HTTPS).

### Avant : les périphériques par défaut de Windows
Paramètres > Système > Son : le **micro par défaut** et la **sortie par défaut** ne doivent **pas** être la carte son du poste
(« USB Audio Device » / « USB Audio CODEC »). Avec Voicemeeter ou VB-Cable installés, vérifie aussi qu'ils ne redirigent rien vers le poste.
La page te protège : elle **refuse** d'utiliser comme micro, ou comme sortie, un périphérique qu'elle reconnaît comme celui du poste
(d'après `capture_device` / `playback_device` de `station.toml`), et l'écrit dans son journal. Choisis alors un autre micro ou une autre
sortie dans les listes de la page ; coche « Ce n'est pas le poste » seulement si l'avertissement est une erreur.

### Le poste doit être en mode données pour recevoir le micro par l'USB
Sur un Icom (IC-7300, IC-7300MK2…), l'audio USB n'est émis qu'en mode **USB-D** (Hamlib : `PKTUSB`) avec *MOD Input > DATA MOD = USB*.
En USB « normal », le poste module avec **son propre micro** : la page ne sert alors à rien en émission. La page affiche un
encadré jaune qui te le rappelle ; choisis `PKTUSB` dans la liste « Mode » puis « Changer ».

### Diagnostic quand « aucun son ne passe »
Ouvre `trx-monitor --config station.toml` à côté de la page, et regarde le panneau **Audio** de la station et la ligne « diagnostic »
sous la page (elle indique les paquets audio reçus/envoyés et les niveaux vus par le navigateur).

| Ce que tu observes | Cause probable |
|---|---|
| **Réception** à -90 dBFS dans le moniteur | la station ne capte rien du poste : mauvais `capture_device`, squelch fermé, niveau de sortie USB du poste à zéro |
| Réception correcte, **Auditeurs = 0** | le son n'est pas établi vers le navigateur (voir la ligne de diagnostic, pare-feu Windows pour python.exe) |
| Réception correcte, Auditeurs = 1, page : « son reçu : N paquets, niveau 0 % » | le poste est silencieux côté radio, ou la sortie de la page est coupée / mal choisie |
| Page : paquets reçus mais **aucun son entendu** | sortie audio du navigateur : volume, « Couper le son », périphérique de sortie (liste de la page) |
| En émission : **Porte micro OUVERTE** mais *Émission* à -90 dBFS | micro du navigateur muet : mauvais micro choisi (nom affiché dans le journal), ou page sans autorisation du micro |
| En émission : *Émission* correcte, « micro passées au poste » qui **augmente**, mais pas de modulation sur le poste | le poste est en USB au lieu de **USB-D (PKTUSB)**, `MOD Input` ≠ USB, ou `USB MOD Level` à zéro |
| « micro passées au poste » qui **n'augmente pas** alors que la porte est ouverte | l'audio du navigateur n'arrive pas à la station (journal de la page, pare-feu) |


## 11 bis. Écran du téléphone qui s'éteint

La page demande au navigateur de **garder l'écran allumé** tant que tu es connecté et que la page est au premier plan (case « Garder l'écran
allumé », HTTPS requis ; Chrome 84 ou plus récent). Limites : le verrou est **relâché par le navigateur dès que la page est masquée**
(autre application, autre onglet, écran verrouillé à la main) et la page coupe alors l'émission par sécurité. Branche le téléphone et baisse la
luminosité pour de longues sessions. Pour travailler **écran éteint, avec une autre application au premier plan ou depuis Android Auto**, il
faut l'application Android (service au premier plan).

## 11 ter. La page de contrôle (afficheur, mémoires, squelch)

**Partie haute, toujours visible** : fréquence (au format des postes : `7.074.00` = 7 074,00 kHz), mode (les modes données s'affichent « USB-D »,
« LSB-D »...), S-mètre, puissance (`Po`), pastilles **NR, NB, P.AMP, IP+**, gros bouton d'émission, STOP, case « Émission autorisée » et
**squelch** (le curseur règle le squelch du poste ; 0 = ouvert). **Partie basse, qui défile** : connexion, mémoires, accord, audio, mesures du poste
(ALC, ROS, compression, tension, température, ATT, AGC), affichage, diagnostic et journal.

- **Indicateurs** : la page n'affiche que ce que le poste fournit via Hamlib. Une pastille absente signifie « non fourni par ce poste ou cette
  version de Hamlib », pas « désactivé ». Hamlib nomme l'IP+ `AIP`. Pour voir ce que ton poste annonce : `rigctl -m <modèle> -u` (lignes
  « Get functions » et « Get level »).
- **Boutons de commande du poste**, juste au-dessus du bouton **PTT** : **NR**, **NB**, **P.AMP**, **IP+**, **AGC**, **COMP** (compresseur de parole),
  **FIL** (filtre de réception) et **TUNER**. Un appui bascule NR, NB, IP+, COMP et TUNER (bleu = en service). **P.AMP** passe d'une valeur à
  la suivante (arrêt, puis les valeurs du poste). **AGC** passe de rapide à moyen à lent. **FIL** passe à la largeur suivante du mode en cours
  (large, normale, étroite : sur un Icom, FIL1, FIL2, FIL3) ; l'étiquette indique la largeur, p. ex. « FIL 2.4k ». Un bouton n'apparaît que si
  Hamlib sait lire et régler la fonction sur ton poste. Si **FIL** manque, envoie-moi les lignes « Bandwidths » de `rigctl -m 3094 -u`.
  **Tous ces boutons sont verrouillés pendant l'émission** (la station les refuse aussi).
- **TUNER** : l'appui met le tuner en ou hors service. Hamlib n'envoie aucun ordre d'accord, mais selon le réglage du poste (accord au PTT) un
  accord peut se déclencher à la prochaine émission, donc avec une porteuse. **Essaie d'abord sur charge fictive.**
- **Repère de squelch** : un trait orange sur le S-mètre indique le niveau du squelch quand il est activé (curseur SQL au-dessus de 0). Le
  repère est **indicatif** : il suppose que le curseur du squelch et le S-mètre partagent la même échelle 0-255.
- **SWR et ALC** : deux graphiques sous la puissance (Po), côte à côte. Ils ne se remplissent **que pendant l'émission** (le poste ne les
  mesure pas en réception) ; échelle du SWR de 1 à 3.
- **Case « Émission autorisée »** : elle **reste cochée** après chaque émission ; tu la décoches toi-même. Elle est décochée à chaque
  connexion ou rechargement de la page. Le micro, lui, ne s'ouvre que pendant une émission confirmée.
- **Mémoires** (partie basse) : « ＋ Mémoriser la fréquence actuelle » enregistre fréquence et mode. Toucher une mémoire la **rappelle**
  (mode, puis fréquence ; refusé pendant l'émission). L'étoile marque un **favori** : les favorites s'affichent en tête, les autres par
  fréquence croissante, avec le mode. Le crayon modifie ; la suppression demande une confirmation. Les mémoires sont enregistrées **sur la
  station** (`memories.json`, dans le dossier d'état), donc **partagées entre tous tes appareils**. 200 au maximum.
- **Affichage** : portrait par défaut ; « Disposition » propose le paysage (deux colonnes : informations et bouton à gauche, le reste à droite).
  « Automatique » passe en paysage seulement si l'écran couché est assez large (640 px et plus). « Taille du texte » : automatique selon l'écran,
  ou petit, moyen, grand. Ces réglages sont mémorisés dans le navigateur.
- **Mesures d'émission** (puissance, ROS, ALC, compression) : lues seulement **pendant l'émission**, à tour de rôle, pour ne pas saturer la
  liaison série du poste.

### Régler la fréquence

- **Chiffre glissable** : pose le doigt sur un chiffre de l'afficheur et glisse vers le haut (plus) ou le bas (moins) ; un cran tous les 22 px,
  avec le poids du chiffre touché (kHz, 10 kHz, centaines de Hz…). L'affichage suit tout de suite et **une seule commande** part à la fin du
  geste. Sur ordinateur, la molette de la souris sur un chiffre fait de même.
- **Un appui court sur la fréquence ouvre un clavier numérique** : « 7074 » ou « 7 074,5 » = kHz ; « 14.205 » = MHz (moins de 1000) ; « 7.074.00 »
  (format du poste) est aussi compris. L'aperçu montre la valeur comprise avant validation.
- **Boutons de bande** (160 à 6 m, section Accord) : ils reviennent à la **dernière fréquence et au dernier mode utilisés sur cette bande**
  (mémorisés dans ton navigateur une fois la fréquence stable 1,5 s ; un point de départ usuel sinon). Le mode est rappelé d'abord, puis la
  fréquence ; avec `tx_modes`, USB devient USB-D et LSB devient LSB-D. Les registres de bande sont propres à chaque appareil.
- **Pas ◀ ▶** (10 Hz à 25 kHz) : un appui = un pas, maintenu = répétition.
- Tout ceci est **refusé pendant l'émission**.

### Puissance d'émission (bouton PWR)

Un appui passe à la puissance supérieure : 5, 10, 25, 50, 80, 100 %, puis retour à 5 %. Avec `max_power_w` (`trx-setup --max-power 100 -o station.toml`)
l'étiquette est en **watts** (« PWR 25W ») ; sans, en pourcentage. Le réglage envoyé est une **fraction de la puissance maximale** du poste : le
nombre de watts affiché suppose une correspondance linéaire, **à vérifier au wattmètre sur charge fictive**. Refusé pendant l'émission.

### Waterfall de l'audio reçu

Un appui, ou un double appui, sur la zone des graphiques Po, SWR et ALC la remplace par le waterfall (le S-mètre reste visible) ; un nouvel appui
sur le waterfall la rétablit. Pendant l'émission, Po, SWR et ALC s'écrivent en superposition. Il analyse **l'audio reçu dans le navigateur**
(0 à 5 kHz, raies de 11,7 Hz), en dégradé gris, bleu puis blanc, avec une grille tous les 500 Hz (graduations en kHz, sans unité) et la courbe du spectre au-dessus.
Boutons : **VIT** (3, 6, 12, 25, 50 lignes par seconde), **LARG** (bande affichée : 5, 3, 2.5, 2, 1 kHz), **GAIN** (sensibilité des couleurs, de -12 à +18 dB),
**PIC** (pics maintenus avec une constante de temps de 0,5 s, 2 s, 5 s, maintien, ou aucun) ; « pic 0.70 » indique la fréquence de la raie la plus forte (en kHz).
Limites : c'est le spectre de l'**audio après compression Opus**, pas du signal radio ; un squelch fermé donne un waterfall noir ; l'analyse ne tourne
que lorsque le waterfall est affiché.

### Journal des pertes de connexion

Chaque perte (ou échec de connexion) est enregistrée dans ton navigateur : raison en français, explication, piste, durée de session, dernier temps de
réponse, état du réseau du téléphone, page visible ou masquée, émission en cours, et les dernières lignes du journal. La dernière raison s'affiche
sous le bouton de connexion ; **Diagnostic et journal** garde les **10 dernières** (menu), avec « Copier le rapport » et « Effacer l'historique ».
Raisons reconnues : canal fermé, liaison échouée (WebRTC ou ICE), **plus de nouvelles de la station depuis 5 s**, canal jamais ouvert en 15 s (UDP bloqué),
station injoignable, identifiants refusés, station occupée. Une déconnexion voulue n'est jamais une perte.

### Reconnexion automatique et image d'accueil

- **Reconnexion automatique** : après une coupure en cours de session (micro-coupure 4G en voiture, par exemple), la page retente seule de se
  connecter pendant **15 s** par défaut (liste « Reconnexion automatique après une coupure » de la section Connexion : désactivée, 15, 30 ou 60 s ;
  réglage mémorisé sur le téléphone). **Le mot de passe n'est pas redemandé** : la page le garde en mémoire vive le temps de la session, jamais dans le
  stockage du navigateur ; il est oublié à une déconnexion voulue, à l'abandon de la reconnexion et au rechargement de la page (F5).
- Pendant la reconnexion, un **grand texte orange clignotant** remplace l'affichage de la fréquence : « RECONNEXION… 12 s », avec le numéro de l'essai
  et la dernière erreur, et un bouton **Annuler**. Si le délai s'écoule, il devient « CONNEXION PERDUE » en rouge fixe et la zone de connexion se rouvre.
  Avec « réduire les animations » activé dans Android, le texte ne clignote pas.
- **Sécurité** : rien n'est réarmé tout seul. La case « Émission autorisée » est décochée à la coupure, le micro reste fermé, et la station coupe de toute
  façon l'émission faute de signal de vie. Il faut recocher la case pour émettre.
- Règles : un premier essai à 0,4 s, puis tous les 1,5 s, 3 s, 4,5 s ; un canal qui ne s'ouvre pas en 6 s est abandonné pour réessayer ; **hors
  ligne, la page attend** le retour du réseau (ou du premier plan) puis retente aussitôt ; **identifiants refusés = arrêt immédiat** (la station bloque
  après 5 échecs) ; une connexion manuelle ou « Annuler » arrête tout. L'historique des pertes garde **une seule entrée** par coupure, avec l'issue :
  « reconnexion automatique réussie après 7 s, 3 essais » ou « abandonnée ».
- **Image d'accueil** : au chargement ou à l'actualisation (F5), le logo reste **2 secondes** puis s'efface en fondu ; un appui la passe. Elle s'efface
  par la feuille de style, même si le JavaScript échoue. Pour la changer, remplace `trxstation/gateway/api/static/splash.webp` (560 px de large environ,
  quelques dizaines de ko : elle est rechargée à chaque ouverture).

## 11 quater. Contrôle des bandes d'émission (`enforce_bands`)

Beaucoup de postes interdisent eux-mêmes d'émettre hors des bandes amateur (réglage **TX limit** des Icom : à vérifier ON dans le menu du poste).
`trx-setup --bands off -o station.toml` supprime le contrôle côté station (`enforce_bands = false`) ; `--bands on` le rétablit. Une fois
désactivé, **seul le poste protège** : la station ne refusera plus une émission hors bande, et le démarrage affiche un avertissement. Garde-le
actif avec un poste qui n'a pas ce réglage.

## 12. Limiter l'émission aux modes où l'audio USB est utilisé (`tx_modes`)

Sur un Icom (IC-7300, IC-7300MK2…), l'audio USB n'est utilisé qu'en **modes données** (USB-D, LSB-D, AM-D, FM-D). Dans un autre mode, le poste
module avec sa **propre** source (micro, ACC ou LAN) : une prise d'émission à distance enverrait alors le bruit de la pièce, ou rien.

Réglage de `station.toml`, section `[rig]` :
```toml
tx_modes = ["PKTUSB", "PKTLSB", "PKTFM", "PKTAM"]   # noms Hamlib ; vide = aucune restriction (autres marques)
```
Sur un fichier existant : `trx-setup --tx-modes PKTUSB PKTLSB PKTFM PKTAM -o station.toml` (`--tx-modes aucun` supprime la restriction ;
à l'installation, `trx-setup` le propose automatiquement pour un Icom).

Effets :
- **Prise d'émission refusée** (`mode_not_allowed`) si le mode relu sur le poste n'est pas dans la liste, ou s'il est illisible.
- **Coupure immédiate** (`mode_changed`) si le mode est changé sur le poste **pendant** l'émission.
- La page web affiche les modes données sous leur nom lisible (« USB-D (données) ») et un message bloquant qui indique le mode à choisir.
- `trx-hwtest` propose de passer dans un mode autorisé avant les étapes d'émission, puis rétablit ton mode.
- Le changement de fréquence ou de mode reste interdit pendant l'émission.

En mode données, certains réglages propres à la voix (largeur d'émission, compresseur, filtres de réception, AGC et réducteur de bruit
mémorisés par mode) peuvent différer : à vérifier une fois dans le manuel du poste.

## 13. Coupure faite sur le poste et spectre HF (`trx-hwtest --coupure-poste`)

Avant d'activer `[spectrum]` (spectre HF du poste, Hamlib `async=1`), il faut prouver que la station voit
toujours une coupure faite **sur le poste lui-même** : avec les données asynchrones, Hamlib pourrait
renvoyer un état d'émission gardé en mémoire au lieu de relire le poste.

Mêmes précautions qu'au début de ce document (charge fictive, puissance minimale, TOT interne du poste),
station arrêtée, puis deux essais :

1. `[spectrum] enabled = false` dans station.toml, puis `trx-hwtest --config station.toml --coupure-poste`.
2. `[spectrum] enabled = true` (et `[rig] speed = 115200`), puis la même commande.

Déroulé : la question est posée AVANT l'émission ; après `EMETTRE` et Entrée, la station prend l'émission et
affiche `>>> COUPE MAINTENANT` : appuie sur la touche TRANSMIT du poste. Résultat attendu dans les deux cas :
« Coupure par le poste (...) : vue en x s » (ton temps de réaction compris, relecture toutes les 1 s).
« PAS VUE : le TOT de l'essai a coupé » avec le spectre activé = la relecture n'est pas fiable avec
`async=1` : laisser `[spectrum] enabled = false`.

**Résultat (IC-7300MK2, Windows, Hamlib 4.7.2)** : `async=1` est rejeté (réponses décalées, `T 0` en
échec). Piste suivante : le second port du poste (section 14).

## 14. Spectre sur le second port du poste (`civ_dual`)

Certains Icom (IC-7300MK2…) exposent deux ports série USB. Si le port B est réglé en **CI-V**, rigctld peut
garder le port A **sans async** (réglages de la station inchangés) pendant qu'on lit le spectre sur le port B.
Cet essai vérifie que c'est vrai, **sans aucune émission**.

**Avant tout**, sur le poste (MENU > SET > Connecteurs) :

- « USB SEND », « USB Keying (CW) » et « USB Keying (RTTY) » : **aucun ne doit utiliser le port B**
  (OFF, ou une ligne du port A). Sinon, ouvrir le port B peut mettre le poste en émission.
- fonction du port B : CI-V ;
- charge fictive ou antenne, puissance au minimum (par précaution).

Station arrêtée, puis :

```
python -m trxstation.devtools.civ_dual --config station.toml --port-b COM7 --duree 30
```

L'outil lance son propre rigctld sur le port A de station.toml (127.0.0.1:4542, sans async, journal
`-vvvv`), relit le PTT, ouvre le port B (RTS et DTR à zéro), relit le PTT, puis lit le spectre sur le port B
en interrogeant rigctld (fréquence et PTT) toutes les 0,5 s. Sur le port B il parle en **E1h** (rigctld
parle en E0h) : toute trame E0h vue sur B prouve que les deux ports partagent le même bus CI-V.

Lecture du bilan (`deux-ports-<date>/resume.txt`) :

| Ligne | Bon | À traiter |
| --- | --- | --- |
| PTT | toujours 0 | « PTT relu ACTIF » : arrêt immédiat, port B fermé, `T 0` (code 4). Revoir USB SEND / USB Keying. |
| Spectre | « spectre reçu sur le port B » | aucun balayage : port B pas en CI-V, mauvais débit, ou sortie du spectre réservée au port A |
| rigctld | toutes les lectures répondues | échecs ou « rigctld ne répond plus » : le flux gêne le port A |
| Bus | 0 ligne « spectre » dans le journal de rigctld | lignes « spectre » : le spectre arrive AUSSI sur le port A. Le journal `-vvvv` ne contient que des noms de fonctions (pas d'octets) : indicatif |
| Fréquence | identique sur A et B | différente : ne pas toucher au poste pendant l'essai, puis relancer |

Si le poste ne répond pas en E1h, l'outil réessaie en E0h et le note : le comptage du bus partagé est
alors moins parlant. Ce relevé ne remplace pas `trx-hwtest --coupure-poste` (section 13), à refaire avec
le port B ouvert avant toute mise en service.

**Résultat (IC-7300MK2, Windows)** : spectre reçu sur le port B (4 balayages/s, 475 points), rigctld
sans échec sur le port A, ports indépendants ; `trx-hwtest --coupure-poste` avec `civ_scope` actif sur le
port B : coupure faite sur le poste vue en 4,2 s. Voie retenue pour la station (section 15).

## 15. Mettre en service le spectre par le second port (`trx-setup --spectre`)

Station arrêtée, mêmes vérifications du menu que la section 14 (USB SEND / USB Keying sur le port A ou OFF,
port B en CI-V) :

```
trx-setup --output station.toml --spectre COM7
```

L'assistant lance un rigctld temporaire sur le port CAT, relit le PTT, ouvre le port B (RTS et DTR à zéro),
relit le PTT, puis vérifie : le poste répond en CI-V (adresse trouvée et enregistrée), il fournit le
spectre, et il affiche la même fréquence que sur le port CAT. Si tout va bien, `[spectrum]` est écrit
(`source = "civ_port"`, `port`, `civ_address`). Sinon : « PROBLÈME DE CONFIGURATION », rien n'est activé.
L'assistant complet (`trx-setup` sans option) pose la même question pour un Icom.
`trx-setup --spectre off` revient au mode normal.

**À chaque démarrage, puis en continu**, la passerelle refait ces vérifications :

- le port B ne s'ouvre qu'en réception confirmée, et le PTT est relu juste après : s'il passe en émission,
  le port est refermé, la coupure est envoyée et le spectre reste désactivé jusqu'au redémarrage ;
- adresse CI-V, spectre et fréquence vérifiés à chaque ouverture ; adresse revérifiée toutes les 30 s ;
- plus de spectre pendant 5 s (affichage éteint sur le poste, réglage changé, câble) = problème.

En cas de problème, la station continue **en mode normal** (un seul port, sans waterfall HF) et prévient :
journal de la passerelle, page web (« Spectre HF : problème de configuration… »), `trx-monitor` (panneau
Audio) et diagnostic de TRX Console (section « Spectre HF »). Elle réessaie seule toutes les 60 s, toujours
en réception confirmée.

**Affichage du spectre HF dans la page** : touche la zone des graphiques de puissance une fois (spectre de
l'audio reçu), puis une seconde fois : le spectre HF du poste s'ouvre en plein écran et le téléphone passe en
paysage (Chrome Android). Le trait orange marque la fréquence du poste ; « GAIN » règle la sensibilité des
couleurs ; « STOP » coupe l'émission ; « Fermer », un appui sur le spectre ou le geste retour referment la
vue. Si le spectre n'est pas disponible (mode normal), cette étape est sautée.
À vérifier à l'écran : les graduations en MHz correspondent aux bords affichés par le poste, en mode
centré comme en mode fixe ; le trait orange est sur la fréquence affichée par le poste.

**Réglages du spectre du poste depuis la page** (ligne « Poste : » de la vue HF) : mode CENT/FIX, largeur
(SPAN, mode centré seulement), niveau de référence (REF − / REF +, par 1 dB) et vitesse. Chaque appui part
vers le poste par le second port, puis le réglage est RELU : le bouton affiche la valeur du poste. Ces
réglages sont refusés pendant l'émission. Un réglage changé directement sur le poste apparaît dans la page
en 30 s au plus. À vérifier : chaque bouton change bien le réglage affiché par le poste, et une largeur
plus étroite affine bien le spectre.
