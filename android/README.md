# Application Android openRemoteTRX

Client Android de la station TRX distant. Cahier des charges : [`docs/android-cahier-des-charges.md`](../docs/android-cahier-des-charges.md) ; protocole : [`docs/protocole.md`](../docs/protocole.md).

- Identifiant du paquet : `com.rfdiy.openremotetrx` (ne jamais le changer). Android 10 (API 29) minimum.
- Les règles de sécurité d'émission (PTT en toggle, état de la station seul affiché, battements, RX à la reconnexion, STOP partout) sont celles de `CLAUDE.md` : l'application ne retire et ne remplace aucune sécurité de la station.

## Modules

| Module | Contenu | Android ? |
|---|---|---|
| `:protocol` | messages et commandes, décodage tolérant, constantes | non (Kotlin/JVM) |
| `:logic` | affichage de l'émission, battements, surveillance de la liaison, reconnexion, armement, textes | non (Kotlin/JVM) |
| `:core` | `RigService` (seul propriétaire de la connexion), WebRTC, HTTPS épinglé, comptes, sons | oui |
| `:app` | écrans Compose (stations, station connectée) | oui |

Les tests de `:protocol` lisent les exemples partagés `../tests/protocol/` (les mêmes que pytest et la page) ; ceux de `:logic` comparent les textes avec `client.js`.

## Construire et tester

Prérequis : Android Studio (il fournit le JDK, le SDK et l'émulateur). En ligne de commande, `JAVA_HOME` désigne son JDK :
`C:\Program Files\Android\Android Studio\jbr` (Windows). Gradle 9.1 est téléchargé par le lanceur au premier usage.

```
cd android
gradlew.bat test assembleDebug     # Windows ; APK : app/build/outputs/apk/debug/app-debug.apk
./gradlew test assembleDebug       # Linux
```

Google Play (test interne) : `gradlew.bat bundlePlay` -> `app/build/outputs/bundle/play/app-play.aab`, signé par la clé
d'envoi (`keystore.properties`, hors dépôt), sans le scrambler : voir `docs/android-play-store.md`.

Installer sur un téléphone branché en USB (débogage USB activé) : `adb install -r app/build/outputs/apk/debug/app-debug.apk`
(adb : `%LOCALAPPDATA%\Android\Sdk\platform-tools`).
