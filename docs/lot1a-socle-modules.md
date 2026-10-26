# Lot 1a — Socle de l'architecture en modules

Ce lot ajoute le paquet `trx_modules/` sans modifier aucun fichier existant.
Il ne dépend que de la bibliothèque standard Python (3.11 ou plus).

## Contenu

| Fichier | Rôle |
| --- | --- |
| `trx_modules/tokens.py` | Jetons de session signés (émission, vérification, révocation) |
| `trx_modules/manifest.py` | Lecture et validation des `modules/<nom>/manifest.toml` |
| `trx_modules/protocol.py` | Format des messages de l'API interne (JSON, une ligne par message) |
| `trx_modules/bus.py` | Serveur de l'API interne, côté cœur (sera intégré à la passerelle) |
| `trx_modules/client.py` | Bibliothèque côté module (reconnexion, battements, détection des trous) |
| `trx_modules/launcher.py` | Lancement et relance des modules, côté superviseur ; unités systemd |
| `trx_modules/secrets_store.py` | Secrets par module, générés à l'installation |
| `trx_modules/demo_module.py` | Module factice : pause pendant le PTT |
| `trx_modules/demo.py` | Démonstration autonome, sans TRX |
| `modules/demo/manifest.toml` | Manifeste du module factice |
| `tests/modules/` | Tests (pytest) |

## Essayer la démonstration

Depuis la racine du dépôt :

    python -m trx_modules.demo

Un faux cœur démarre, le module factice est lancé comme un vrai module
(processus séparé, priorité basse), le PTT bascule toutes les 3 secondes et
les messages qui iraient au terminal s'affichent.

## Règles appliquées

- Le cœur n'attend jamais un module : `publish()` ne bloque jamais, chaque
  module a une file bornée, un module trop lent est déconnecté.
- L'API interne n'écoute que sur 127.0.0.1 ; chaque module a son secret.
- Un module n'a que les droits de son manifeste ; la commande `qsy` est
  refusée pendant le PTT ; aucun module ne peut demander le PTT.
- Le secret passe par l'environnement, jamais par la ligne de commande ni
  par l'unité systemd.

## Reste à faire (lot 1b)

- Brancher `BusServer` dans la passerelle : état réel, publication des
  événements PTT, fréquence et mode, relais des messages vers le client,
  jetons de session délivrés au login.
- Brancher `ModuleLauncher` dans le superviseur (mode géré) et installer
  les unités systemd des modules sous Linux.
- Port de l'API interne et emplacement du fichier de secrets dans station.toml.
