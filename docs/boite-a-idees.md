# Boîte à idées

Projets annexes envisagés, **hors de la liste des tâches du projet principal** (ni « En attente » de CLAUDE.md, ni plan des étapes). Une idée n'en sort que sur décision explicite de l'utilisateur.

---

## Allumer le poste à distance (2026-11-14)

**SORTIE de la boîte à idées le 2026-11-19** (demande de l'utilisateur, étape 286) : cahier `docs/alimentation-poste-cahier-des-charges.md` ; FTDX10 éteint et rallumé par la CAT avec succès le même jour.

**Idée** : après une coupure de courant, une station distante reste muette tant que personne n'appuie sur ON/OFF. Le FTDX10 s'allume par CAT **par l'USB seulement** (`PS1;` envoyé deux fois à 1-2 s d'écart, manuel CAT 2308-F ; impossible par la prise RS-232C) ; Hamlib expose `set_powerstat`. À étudier : commande « allumer le poste » réservée à l'opérateur, jamais automatique, aucune émission (le poste démarre en réception), refus si le modèle ne le déclare pas ; vérifier qu'un poste éteint garde l'USB alimenté.

## Transcription et traduction de l'écoute (2026-10-28)

**Idée** : se caler sur une fréquence où l'on parle anglais, allemand ou autre, et obtenir une transcription écrite à l'écran, voire une traduction (texte ou audio).

**Faisabilité étudiée (rien de codé)** : faisable en local, sans service en ligne. Limite principale : la qualité du son BLU HF, pas le logiciel.

- **Transcription** : Whisper (`faster-whisper` ou `whisper.cpp`, MIT), détection automatique de la langue. Sur la **station** (son de réception avant Opus), sous forme de **module** (`modules/`), facultatif, désactivé par défaut, annoncé dans `hello.features`. Texte par segments, 2 à 5 s après chaque passage.
  - PC récent : modèles `small`/`medium` en temps réel ; mini-PC (minix-bzh) : `small` au mieux, à mesurer ; Raspberry Pi : `tiny`/`base`, médiocre en HF.
- **Limites** : bande étroite, bruit, QSB, décalage d'accord ; hallucinations de Whisper sur le bruit (détecteur de voix obligatoire, rien quand le squelch est fermé) ; indicatifs, alphabet phonétique et codes Q mal reconnus (amorce de vocabulaire). À présenter comme une aide, avec un indice de confiance.
- **Traduction écrite** : `translate` de Whisper ne va que vers l'anglais. Il faut une seconde étape : Argos Translate (local, MIT) recommandé ; Opus-MT possible ; NLLB : licence des poids non commerciale, à vérifier. Un service en ligne (DeepL…) ne serait qu'une option.
- **Traduction audio** : synthèse locale (Piper, MIT), 4 à 10 s de retard, réception baissée pendant la voix. Seule façon d'en profiter sous Android Auto (pas de texte en voiture) : plutôt pour l'application, en dernier.
- **Sécurité d'émission** : réception seule. Jamais de contact avec le PTT ni la porte audio d'émission ; jamais de voix synthétique émise vers l'autre station. Exige les plafonds CPU/mémoire des modules (Whisper peut saturer un petit PC).
- **Coûts annexes** : modèles de 150 Mo à 1,5 Go, téléchargés à part (pas dans les zip) ; nouveau message de protocole (`docs/protocole.md`, `tests/protocol/`, `hello.features`, parité web/Android).

**Démarche si l'idée est retenue** :
1. Mesurer d'abord : enregistrer des passages réels sur l'IC-7300 (anglais, allemand, signaux forts et faibles) et les passer hors ligne dans `faster-whisper` `small`/`medium` sur minix-bzh et le PC Windows. Arrêter là si c'est inexploitable.
2. Module de transcription et texte défilant dans la page.
3. Traduction écrite (Argos).
4. Traduction audio, avec l'application Android et Android Auto.

## Vrai binaural par la FI 12 kHz (2026-11-03)

**Branche d'essai `exp/st-fi` ABANDONNÉE le 2026-11-20** (décision de l'utilisateur) : aucune mesure faite, aucun code ; journal de la branche repris ci-dessous tel quel. La ST livrée (étapes 116-117, `spatial.js`, `Spatial.kt`) n'en dépend pas.

Branche ABANDONNABLE (règles : CLAUDE.md, « Branches d'essai »). Ni numéro d'étape ni version : journal ici seulement.
Point de départ : `main` à l'étape 116 (station 0.96.0, ST V1 de la page).

### But

Donner au module ST de vraies voies I/Q (les deux bandes latérales autour du battement nul, à la manière des
récepteurs binauraux de KK7B) au lieu d'un mono transformé : une station au-dessus et une au-dessous du battement nul
se placent de part et d'autre de la tête ; c'est là qu'un gain réel en CW et en pile-up est possible.

### Mesures à faire AVANT tout code de production (dans cet ordre)

1. IC-7300MK2, menu « USB AF/IF Output » sur IF : largeur de la FI 12 kHz relevée par la carte son ; les filtres
   (FIL, largeur, PBT), NR, NB, notch du poste agissent-ils sur la FI ? (si non : la moitié des commandes de
   l'interface n'agit plus sur l'écoute => à refaire en logiciel ou abandon). AF et FI ensemble : impossible ?
2. Charge d'un démodulateur Python + numpy (BLU, CW, AM, FM, AGC, squelch) sur minix-bzh et sur un Pi 4.
3. Opus stéréo (aiortc -> Chrome, -> stream-webrtc) : le déphasage I/Q tient-il, à quel débit minimal ?
4. Android : sortie stéréo réelle (même question que la V1 de l'application).

### Conception provisoire

- Station : démodulation OBLIGATOIRE (l'audio mono sert à tout le reste : enregistrement, SELCALL, waterfall audio,
  visiteurs, Android Auto) + I/Q en bande de base, calculés une fois pour tous les clients.
- Bascule AF / FI : capacité facultative du descripteur (modèle par modèle, Hamlib ne sait pas la faire) ; CI-V par le
  port B ou réglage manuel ; retour en AF garanti à l'arrêt.
- Flux : mono par défaut ; stéréo I/Q seulement pour un client qui active ST et que la station l'annonce
  (`hello.features`). Visiteurs et Android Auto en mono.
- Client : le module ST de la V1 accepte M/S ; l'I/Q y entre comme un moteur de plus.

### Journal

- 2026-11-03 : branche créée depuis `main` (étape 116).
- 2026-11-20 : branche abandonnée et supprimée, journal gardé ici.
