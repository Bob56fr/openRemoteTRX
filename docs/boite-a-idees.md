# Boîte à idées

Projets annexes envisagés, **hors de la liste des tâches du projet principal** (ni « En attente » de CLAUDE.md, ni plan des étapes). Une idée n'en sort que sur décision explicite de l'utilisateur.

---

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
