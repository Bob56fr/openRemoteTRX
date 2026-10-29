# openRemoteTRX — Cahier des charges : fonction SELCALL (squelch numérique BLU)

Version 1.1 — fourni par l'utilisateur le 2026-10-29. Remarques de relecture et décisions : § 15 (à la fin).

## 1. Contexte et objectif

openRemoteTRX permet de piloter à distance un TRX radioamateur. Le côté station tourne sur PC Windows, Linux Debian ou Raspberry Pi, et comprend le superviseur, la passerelle (CAT via rigctld, audio WebRTC/aiortc) et trx-monitor. Le côté client est la console web, puis l'app Android.

La fonction SELCALL ajoute un **squelch numérique par appel sélectif de groupe** utilisable en BLU. L'utilisateur arme la fonction avec un code numérique. La station n'envoie alors plus l'audio de réception au client tant qu'elle n'a pas reçu ce code. Dès réception du code, l'audio s'ouvre et reste ouvert jusqu'à ce que l'utilisateur réarme lui-même la fonction.

Contraintes radio déterminantes :
- en BLU, un défaut d'accord décale toutes les fréquences audio de la même valeur. Le système doit tolérer **±300 Hz** de décalage, pour les vieux TRX ;
- le signal est reçu dans le bruit de fond HF, avec QSB et voix éventuelle.

## 2. Périmètre

**Dans le périmètre**
- Protocole de signalisation SELCALL, générateur et décodeur.
- Tout le traitement côté station, jamais sur le smartphone.
- Squelch numérique avec ouverture verrouillée.
- Filtrage des tonalités SELCALL dans l'audio reçu (muet, atténué ou carillon).
- Option d'envoi automatique du SELCALL en fin d'émission, à la place du roger bip.
- Bouton « Envoyer SELCALL » manuel : appel du groupe sans parler, trame émise 3 fois.
- Affichage de l'état SELCALL sur Android Auto (lecture seule).
- Configuration, historique des codes, API client, interface console, affichage trx-monitor, notification ntfy.
- Tests automatisés sur signaux synthétiques.

**Hors périmètre**
- Appel personnel ou individuel : le SELCALL est **un appel de groupe**.
- Compatibilité avec les selcalls existants (CCIR 493, ZVEI, DTMF…), inutilisables avec ±300 Hz de décalage.

**Règle fondamentale** : le code émis est **le même** que le code sur lequel la station est armée. Envoyer ce code en fin d'émission permet d'ouvrir le squelch des autres stations du groupe qui auraient manqué l'appel initial.

## 3. Protocole de signalisation

Tous les paramètres ci-dessous sont des constantes nommées, regroupées dans un seul module. Les valeurs indiquées sont les valeurs par défaut.

| Élément | Valeur |
|---|---|
| Fréquence nominale du pilote `F0` | 1000 Hz |
| Durée du pilote | 1000 ms |
| Durée d'un symbole (chiffre, R, contrôle) | 300 ms |
| Fréquence du chiffre `d` (0–9) | `F0 + 200 + 100 × d`, soit 1200 à 2100 Hz |
| Symbole de répétition `R` | `F0 + 1200`, soit 2200 Hz |
| Longueur du code | 3 à 8 chiffres |
| Chiffre de contrôle | somme des chiffres du code, modulo 10 |
| Rampes début/fin de chaque ton | 5 ms (cosinus), pour éviter les clics |
| Niveau d'émission | −6 dBFS, réglable (doit rester sous le seuil d'ALC) |

**Construction de la trame** : pilote, puis chiffres du code, puis chiffre de contrôle. Les symboles sont contigus et à phase continue, sans silence entre eux.

**Règle de répétition** : un symbole identique au symbole précédent est remplacé par `R`. Elle s'applique aussi au chiffre de contrôle.
Exemple : code `4477`, contrôle `2`, donne pilote `4 R 7 R 2`.

**Durée totale** : 1,0 s + (N + 1) × 0,3 s. Cela donne 2,2 s pour 3 chiffres, 2,5 s pour 4 chiffres et 3,7 s pour 8 chiffres.

**Plage utile** : avec ±300 Hz, la trame occupe 700 à 2500 Hz. Elle reste ainsi dans un filtre BLU standard de 2,4 kHz.

La trame fonctionne en USB comme en LSB, puisque le contenu audio est identique. Elle n'est pas limitée aux modes BLU.

## 4. Décodeur

### 4.1 Traitement
- L'audio de réception est rééchantillonné à 8 kHz mono pour le décodage.
- Analyse spectrale glissante : fenêtre de Hann de 128 ms (1024 points), pas de 32 ms.
- Plancher de bruit par trame : médiane des bins de 300 à 2800 Hz.

### 4.2 Détection du pilote
- Recherche d'un pic entre `F0 − 350` et `F0 + 350` Hz.
- Le pilote est validé si :
  - le pic dépasse le plancher d'au moins **12 dB** (paramètre) ;
  - sur au moins **80 %** des trames d'une durée de **800 ms** ;
  - avec une fréquence stable à **±5 Hz** autour de sa médiane. Ce critère rejette la voix et les sifflements glissants.
- Le décalage est calculé par **Δ = fréquence mesurée − F0**, avec une précision visée de ±2 Hz (interpolation parabolique du pic).

### 4.3 Décodage des symboles
- Le découpage en cases de 300 ms est synchronisé sur la fin du pilote : fin de stabilité du pic et apparition d'un ton de la grille.
- Pour chaque case, on mesure l'énergie aux 11 fréquences attendues (chiffres 0–9 et R), corrigées de Δ, avec une tolérance de ±40 Hz.
- On procède à un vote majoritaire sur les trames centrales de la case, en excluant les transitions.
- Le symbole est rejeté si l'écart entre le meilleur et le second candidat est inférieur à **6 dB**, ou si le meilleur est sous le seuil de présence.
- La fin de trame est atteinte quand aucun ton de la grille n'est présent pendant 100 ms. La longueur du code est donc déduite et non imposée.

### 4.4 Validation
- Les `R` sont remplacés par le symbole précédent.
- La trame est acceptée si le contrôle est correct et si le nombre de chiffres est compris entre 3 et 8.
- Le squelch ne s'ouvre que si le code décodé est égal au code armé.
- Toute trame valide (bon ou mauvais code) est journalisée avec le code, Δ, le SNR et l'horodatage.
- Toute trame décodée, valide ou non, est soumise au filtrage (§6).

### 4.5 Objectifs de performance (valeurs initiales, à ajuster après essais)
- **Détection** ≥ 95 % à un SNR de +6 dB dans 2,4 kHz, pour tout décalage dans ±300 Hz.
- **Fausse ouverture** : aucune sur 24 h simulées de bruit, de voix et de sifflements.
- **Dérive tolérée** pendant la trame : ±10 Hz.
- **Charge CPU** du décodeur < 10 % d'un cœur sur Raspberry Pi 4.
- Dépendances : numpy autorisé. Éviter scipy sauf s'il est déjà présent dans le projet.

## 5. Machine d'états du squelch

États :
- **DÉSACTIVÉ** : fonctionnement actuel, audio transmis normalement.
- **VEILLE** : armé, audio de réception non transmis au client, décodeur actif.
- **OUVERT** : appel reçu, audio transmis, décodeur toujours actif pour le filtrage.

| De | Événement | Vers | Actions |
|---|---|---|---|
| DÉSACTIVÉ | Utilisateur active avec un code | VEILLE | Code ajouté en tête de l'historique |
| VEILLE | Trame valide avec le bon code | OUVERT | Événement client, notification ntfy (option), log |
| VEILLE | Trame d'un autre code ou invalide | VEILLE | Log seulement |
| OUVERT | Utilisateur réarme | VEILLE | Audio coupé |
| OUVERT | Nouvelle trame valide | OUVERT | Filtrée, sans autre effet (pas de réouverture) |
| VEILLE ou OUVERT | Utilisateur désactive | DÉSACTIVÉ | — |

Règles :
- **Aucune temporisation** : l'état OUVERT est verrouillé jusqu'à une action de l'utilisateur.
- **En VEILLE, la piste audio WebRTC reste établie** et transmet du silence, pour éviter une renégociation.
- **La déconnexion du client ne change pas l'état.**
- **Au redémarrage de la station**, l'état VEILLE ou OUVERT est restauré en VEILLE avec le même code (sûr par défaut).
- **Pendant l'émission locale**, le décodeur est suspendu.

## 6. Filtrage des tonalités dans l'audio reçu

Actif tant que la fonction SELCALL est activée (VEILLE ou OUVERT), et réglable par option.

- **Retard de l'audio** : tampon à la station, réglable de 250 à 1000 ms, **500 ms par défaut**. La latence est acceptable en usage distant.
- **Pré-détecteur rapide** : un ton stable (±5 Hz) dans la zone pilote pendant 150 ms déclenche une atténuation en fondu de 20 ms. Celle-ci est appliquée à la position du début du ton dans le tampon, donc avant qu'il ne soit audible.
- **Si le pilote n'est pas confirmé** : retour en fondu de 20 ms.
- **Si une trame est en cours** : l'atténuation est maintenue jusqu'à la fin de trame (§4.3), plus 50 ms.

Trois modes, au choix de l'utilisateur :
- `mute` : silence complet ;
- `attenuate` : atténuation réglable, −20 dB par défaut ;
- `chime` : silence, puis un carillon doux et court (2 notes, environ 300 ms, niveau bas) à la fin de la trame. Il signale qu'un appel ou une fin d'émission a eu lieu.

Exigence de test : après filtrage, l'énergie résiduelle des tons dans l'audio de sortie est inférieure de 30 dB (mode `mute`) à celle de l'entrée.

## 7. Émission du SELCALL

### 7.1 En fin d'émission

Option `send_on_tx_end`, désactivée par défaut, active seulement quand la fonction SELCALL est activée.

- Au relâchement du PTT par l'utilisateur, la station **maintient l'émission**, coupe le micro, injecte la trame dans l'audio TX, puis repasse en réception.
- Tout passe par le module de sécurité PTT existant :
  - la durée de la trame est comptée dans le temps maximal d'émission ;
  - la trame est annulée immédiatement (retour en réception) en cas de perte du client, de défaut de la passerelle, de nouvel appui PTT ou de toute condition de sécurité ;
  - les changements de fréquence et de mode restent refusés jusqu'au retour effectif en réception.
- Le roger bip éventuel n'est pas émis quand le SELCALL le remplace.

### 7.2 Appel manuel « Envoyer SELCALL »

Permet d'appeler le groupe sans parler.

- **Disponibilité** : seulement si la fonction est activée (VEILLE ou OUVERT), puisque le code émis est le code armé. Il faut aussi que l'émission soit autorisée et que le PTT ne soit pas déjà actif.
- **Séquence** : passage en émission, puis la trame **émise 3 fois** (option `manual_repeat`, 1 à 5), séparées par **500 ms de silence** (option `manual_gap_ms`), puis retour en réception. Le PTT reste actif pendant toute la séquence et le micro est coupé.
- **Durée maximale** avec les valeurs par défaut : 3 × 3,7 s + 2 × 0,5 s, soit environ 12 s pour un code de 8 chiffres. Cette durée est comptée dans le temps maximal d'émission.
- **Interruption** : le bouton se transforme en « Annuler » pendant la séquence. L'annulation, comme toute condition de sécurité (perte du client, défaut de la passerelle), ramène immédiatement en réception.
- **État de la station** : un appel manuel ne change pas l'état du squelch local.
- **Côté réception** : la première trame décodée ouvre le squelch, les suivantes sont seulement filtrées (§5 et §6). Le silence de 500 ms garantit la détection de fin de trame (100 ms) et la resynchronisation sur le pilote suivant.

## 8. Configuration

Nouvelle section dans station.toml. Les clés existantes ne doivent pas être modifiées : `notify_url` dans `[supervisor]` est conservé.

```toml
[selcall]
enabled = false            # fonction disponible sur cette station
send_on_tx_end = false
manual_repeat = 3         # nombre d'émissions de la trame (appel manuel)
manual_gap_ms = 500
filter_mode = "attenuate"  # mute | attenuate | chime
attenuation_db = 20
audio_delay_ms = 500
tx_level_dbfs = -6
notify_on_call = true      # via ntfy du superviseur
history_size = 10
# paramètres avancés (détection) : seuils dB, stabilité Hz, etc.
```

**État courant et historique des codes** : fichier d'état séparé côté station (par exemple `state/selcall.json`), et non dans station.toml. Il contient l'état, le code armé et les derniers codes utilisés, le plus récent en tête et sans doublon.

**Validation du code** : uniquement des chiffres, 3 à 8.

## 9. API client

Suivre les conventions de l'API client existante. Les noms ci-dessous sont indicatifs.

- **Commandes** :
  - `selcall.activate(code)` ;
  - `selcall.rearm()` ;
  - `selcall.deactivate()` ;
  - `selcall.send()` et `selcall.cancel_send()` ;
  - `selcall.get_history()` ;
  - `selcall.set_options(...)` pour `filter_mode`, `attenuation_db` et `send_on_tx_end`.
- **Événements poussés** :
  - `selcall.state` (état, code, options, envoi en cours avec le numéro de répétition) ;
  - `selcall.call_received` (code, Δ Hz, SNR, horodatage).
- **Authentification** : la même que le reste de l'API.

## 10. Interfaces client

### 10.1 Console web (puis app smartphone)

- **Indicateur dans l'en-tête fixe**, à côté du squelch : `SEL 4721` en veille, `SEL OUVERT` en surbrillance. Un appui ouvre le panneau.
- **Panneau SELCALL** :
  - liste des derniers codes et champ de saisie ;
  - boutons Activer, Réarmer et Désactiver ;
  - bouton « Envoyer SELCALL », qui devient « Annuler » pendant l'envoi avec la progression (1/3, 2/3, 3/3) ;
  - options (filtrage, atténuation, envoi en fin d'émission) ;
  - dernier appel reçu (code, Δ, SNR, heure).
- **À l'ouverture** : bip local discret côté client, en plus de la notification ntfy.
- Style cohérent avec l'afficheur actuel inspiré des afficheurs Icom.

### 10.2 Android Auto

- **Affichage seul** de l'état SELCALL : désactivé, veille avec le code, ouvert, envoi en cours.
- **Aucune commande SELCALL** sur l'écran voiture. Toute action d'émission reste sur le téléphone, conformément à la décision sur le PTT.
- **Information minimale**, conforme aux règles Google : pas de Δ ni de SNR.
- À réaliser lors du développement de l'app Android, à partir de l'événement `selcall.state`.

## 11. Supervision

- **trx-monitor** affiche l'état SELCALL, le code armé, le dernier appel reçu (code, Δ, SNR) et le compteur de trames rejetées.
- **Logs** : chaque trame décodée, chaque changement d'état et chaque annulation d'envoi en fin d'émission.

## 12. Tests

**Module générateur** (réutilisé pour l'émission et pour les tests) produisant des WAV synthétiques. Matrice pytest :
- **décalages** de −300 à +300 Hz par pas de 50 Hz, plus ±350 Hz pour vérifier le rejet ou la limite ;
- **SNR** de +20 à 0 dB (bruit blanc filtré à 300–2700 Hz) ;
- **codes de 3 à 8 chiffres**, dont des répétitions (`4477`, `1111`) et un contrôle égal au dernier chiffre ;
- **dérive** linéaire de ±10 Hz sur la trame et QSB simulé ;
- **rejets** : contrôle faux, trame tronquée, mauvais code, voix synthétique, sifflement glissant, porteuse fixe sans chiffres ;
- **deux trames successives**, et une trame pendant l'état OUVERT ;
- **appel manuel** : 3 trames séparées de 500 ms donnant une seule ouverture et 3 filtrages ; ouverture correcte si la 1re trame est perdue (bruit) mais la 2e ou la 3e reçue ; annulation en cours de séquence ;
- **filtrage** : énergie résiduelle des tons (§6), absence de clics, voix non coupée en dehors des trames ;
- **machine d'états** et persistance au redémarrage ;
- **envoi en fin d'émission** avec le faux poste : annulations de sécurité et respect du temps maximal d'émission ;
- **bout en bout** sur le faux poste : trame injectée, audio client silencieux, ouverture, filtrage.

**Essai réel guidé** (étape à ajouter dans trx-hwtest), avec l'IC-7300MK2 :
1. émission de la trame par un second poste ou par un fichier audio ;
2. décalage volontaire par RIT de ±300 Hz ;
3. vérification de l'ouverture et du filtrage.

## 13. Découpage en lots

Chaque lot se termine par tous les tests au vert et un commit.

1. **Protocole** : générateur et décodeur hors ligne (fonctions pures sur tableaux numpy) avec la matrice de tests §12.
2. **Intégration réception** : retard audio, pré-détecteur, filtrage, machine d'états, état persistant.
3. **Émission** : envoi en fin d'émission et appel manuel répété, intégrés à la sécurité PTT.
4. **API et console web** : panneau, indicateur, historique, options.
5. **Supervision** : trx-monitor, logs, ntfy, étape trx-hwtest.
6. **Android Auto** (avec l'app Android) : affichage de l'état.

Exigences transverses : fonctionnement identique sous Windows (mode géré), Debian et Raspberry Pi ; aucune régression sur les tests existants.

## 14. Points ouverts

- Réglage définitif des seuils après essais sur l'air.

## 15. Relecture (Claude, 2026-10-29) : points à trancher avant le lot 3

NIVEAU DE LA TRAME (demande de l'utilisateur, 2026-10-29 : niveau bien trop élevé ; station 0.64.0, application 0.19.0, étape 77) : curseur `tx_level_dbfs` (-30 à -1 dBFS, enregistré dans selcall.json, option `selcall_options`) ; RÉGLAGE AUTOMATIQUE `selcall_calibrate` (`selcall/calibrate.py`) : émission ordinaire du client (mêmes refus que toggle, micro fermé, toute coupure l'interrompt), ton de 1 000 Hz à phase continue par paliers de 2 dB de 1,2 s depuis -30 dBFS, ALC relu à chaque palier ; arrêt dès qu'il décolle de son niveau de départ (+10 %) ou dépasse 50 % ; niveau = dernier palier propre - 2 dB (plafond -3) ; ALC illisible = niveau inchangé ; progression dans `sending`, résultat dans `calibration`. Seuils À AJUSTER après essai sur l'IC-7300MK2. Voyant permanent « OVERLOAD ALC » (page, application) : ALC >= 50 % pendant toute émission, quel que soit l'usage.
AVANCEMENT : lot 3 FAIT (station 0.62.0, application 0.18.0, étape 75) : ÉMISSION. Fin d'émission : sorte « selcall » des sons de fin (`TailPlayer`), choisie à la place du roger bip quand `send_on_tx_end` (option réglable par les clients, `selcall_options`) et le SELCALL est armé ; mêmes règles que les bips (relâché par son propriétaire depuis TX confirmé, micro fermé avant, toute coupure l'interrompt), attente bornée à durée + 0,6 s (plafond absolu 4,5 s), et SEULEMENT si le TOT restant la contient (sinon roger bip). Appel manuel : commande `selcall_send` -> `PttController.send_selcall` : prise d'émission NORMALE (`_key`, mêmes refus que toggle, plus `selcall_not_armed` et `selcall_too_long` si la séquence dépasse le TOT), porte du micro gardée FERMÉE, trame du code armé `manual_repeat` fois séparées de `manual_gap_ms` (silence écrit), progression « 1/3 »... dans `status.sending` (jamais enregistrée), puis RX (`selcall_sent`) ; la séquence est la « tâche de fin » : STOP, nouvel appui, autre client, déconnexion, battement perdu, TOT l'interrompent net ; séquence bloquée = `selcall_timeout`. Clients : « Envoyer SELCALL » (« Émission autorisée » exigée, battements dès la demande) devient « Annuler (2/3) » (= stop) ; case « Envoyer la trame en fin d'émission ». 17 tests de panne (`tests/test_selcall_tx.py`), dont la trame RÉELLEMENT écrite vers le poste décodée 3 fois et aucun son de micro passé.
AVANCEMENT : lot 4 FAIT AVANT le lot 3 (choix de l'utilisateur, pour essayer la réception sur l'air au plus tôt ; station 0.61.0, application 0.17.0, étape 74) : commandes `selcall_activate` / `selcall_rearm` / `selcall_deactivate` / `selcall_options`, `hello.selcall`, message `selcall` diffusé à tous, fonction `selcall` (docs/protocole.md) ; page : indicateur « SEL 4721 » / « SEL OUVERT » à côté du SQL, rubrique SELCALL, bip discret à l'ouverture ; application : indicateur dans l'afficheur, panneau, carillon à l'ouverture. FICHIER DE TEST (demande de l'utilisateur) : fabriqué par la page (`selcall.js`) ou l'application (`SelcallTones`), sans la station : 2 s de silence puis la trame 3 fois séparées de 0,5 s, WAV mono 16 bits 48 kHz ; page : Écouter, Télécharger ; application : Écouter, Partager (WhatsApp, Signal… par le menu de partage d'Android), Téléchargements. Mêmes tons vérifiés par `tests/protocol/selcall_vectors.json` (station, page, application) ; un fichier fabriqué par la page est décodé par la station (3 trames). Conseils d'essai : envoyer comme DOCUMENT (pas en message vocal, recompressé), volume moyen, le correspondant s'identifie.
AVANCEMENT : lot 2 FAIT (station 0.60.0, étape 73) : `[selcall]` dans station.toml (validé, écrit par trx-setup), `selcall/receiver.py` (`SelcallStore` : état et historique dans state_dir/selcall.json, écriture atomique, OUVERT -> VEILLE au redémarrage, fichier illisible = désactivé ; `SelcallReceiver` entre la carte son et les clients : retard réglable, décodage à 8 kHz, pré-détecteur 150 ms, atténuation en fondu de 20 ms posée au DÉBUT du ton, maintenue jusqu'à la fin de trame + 50 ms ; modes mute / attenuate / chime ; VEILLE = silence, piste maintenue ; décodeur suspendu pendant toute émission) ; 13 tests (`tests/test_selcall_receiver.py`), dont résidu des tons < -30 dB en mode mute, voix non coupée hors trame, pas de clic. Commandes des clients : lot 4 (rien n'arme encore la fonction depuis la page). CHOIX : une case sans ton NET de la grille (silence, bruit OU VOIX qui suit la trame) termine la trame ; avant, la voix juste après la trame la faisait rejeter (« symbole illisible »). Retard minimal de 250 ms : le pré-détecteur répond en 300 ms environ (150 ms de ton + fenêtre d'analyse) : à 250 ms, les ~50 premières ms du pilote peuvent s'entendre ; 500 ms par défaut : rien.
AVANCEMENT : lot 1 FAIT (station 0.59.0, étape 72) : `trxstation/selcall/` (`protocol`, `signal`, `decoder`), `tests/test_selcall_protocol.py`. Mesures sur signaux synthétiques : 100 % de détection de -300 à +300 Hz (pas de 50 Hz) jusqu'à 0 dB de SNR dans 2,4 kHz, encore 100 % à -3 dB et 83 % à -6 dB ; Δ à ±2 Hz ; SNR mesuré à ±1,5 dB ; aucune trame valide sur 5 minutes de voix, voyelles tenues, sifflements et porteuses ; environ 1 % d'un cœur de PC. Choix de réalisation : seuil de présence d'un ton de la grille porté à 14 dB au-dessus du plancher (à 10 dB, le plus fort des ~120 bins regardés dépassait souvent le seuil dans le bruit seul et rendait la fin de trame illisible) ; fin de trame = première case de 300 ms sans ton (au lieu de 100 ms : même effet, cases déjà calées) ; pilote verrouillé plus de 2,5 s sans chiffres = porteuse, abandon.

DÉCISIONS DE L'UTILISATEUR (2026-10-29) : point 1 => OUI, l'exception des bips de fin est ÉTENDUE au SELCALL de fin d'émission (trame de 3,7 s au plus, mêmes garde-fous) ; ordre des travaux : égaliseur et effets, puis SELCALL, puis scrambler.

1. **Envoi en fin d'émission (§ 7.1) et exception des bips de fin.** La règle de sécurité décidée à l'étape 32 limite toute émission
   produite par la station après le relâchement à 0,6 s de son et 1,2 s d'attente. Une trame dure 2,2 à 3,7 s : il faut une
   EXTENSION EXPLICITE de cette exception par l'utilisateur (même règles : seulement depuis une émission confirmée relâchée par son
   propriétaire, micro coupé avant, toute coupure l'interrompt net, jamais une nouvelle prise).
2. **Appel manuel (§ 7.2).** C'est une prise d'émission demandée par le client (comme `toggle`) : « Émission autorisée » exigée,
   verrou mono-client, battements du client pendant toute la séquence (sinon retour en RX en 2 s), TOT compté, bande et mode
   d'émission vérifiés comme pour le PTT. Le superviseur n'émet jamais lui-même.
3. **Porte audio d'émission.** La trame doit passer par la porte de la passerelle (comme les bips), jamais par un autre chemin.
4. **Ordre avec le scrambler.** Trame toujours EN CLAIR (jamais brouillée), décodée sur le son reçu AVANT tout débrouillage.
5. **Pendant l'émission (de ce client comme locale)**, décodeur suspendu (le poste ne reçoit rien d'utile).
6. **numpy** : présent (dépendance d'aiortc / PyAV), jamais importé par le code de la station jusqu'ici ; à déclarer dans
   `pyproject.toml` si le décodeur l'utilise. scipy : absent, non utilisé.
7. **Retard de l'audio reçu (§ 6)** : 500 ms s'ajoutent à la latence quand SELCALL est actif ; le S-mètre et le spectre, eux, ne
   sont pas retardés (léger décalage visible).
