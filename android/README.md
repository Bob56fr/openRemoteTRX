# Application Android openRemoteTRX

Client Android de la station TRX distant. Cahier des charges : [`docs/android-cahier-des-charges.md`](../docs/android-cahier-des-charges.md) ; protocole : [`docs/protocole.md`](../docs/protocole.md).

- Identifiant du paquet : `com.rfdiy.openremotetrx` (ne jamais le changer). Android 10 (API 29) minimum.
- Les règles de sécurité d'émission (PTT en toggle, état de la station seul affiché, battements, RX à la reconnexion, STOP partout) sont celles de `CLAUDE.md` : l'application ne retire et ne remplace aucune sécurité de la station.

## Modules

| Module | Contenu | Android ? |
|---|---|---|
| `:protocol` | messages et commandes, décodage tolérant, constantes | non (Kotlin/JVM) |
| `:logic` | affichage de l'émission, battements, surveillance de la liaison, reconnexion, armement, textes | non (Kotlin/JVM) |
| `:core`, `:app` | service au premier plan, WebRTC, écrans (lot A1) | à venir |

Les tests de `:protocol` lisent les exemples partagés `../tests/protocol/` (les mêmes que pytest et la page) ; ceux de `:logic` comparent les textes avec `client.js`.

## Construire et tester

Prérequis : Android Studio (il fournit le JDK, le SDK et l'émulateur). En ligne de commande, `JAVA_HOME` désigne son JDK :
`C:\Program Files\Android\Android Studio\jbr` (Windows). Gradle 9.1 est téléchargé par le lanceur au premier usage.

```
cd android
gradlew.bat test          # Windows
./gradlew test            # Linux
```
