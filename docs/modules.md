# Modules complémentaires (étape 21)

Les fonctions complémentaires (cluster DX, vidéo, journal…) tournent chacune
dans **son propre processus**. Un module qui plante, sature le processeur ou
fuit en mémoire ne touche ni à l'audio, ni au CAT, ni au PTT.
Référence : Claude Doc « Cahier des charges — Architecture en modules de la
station TRX distant ».

## Activer un module

Dans `station.toml` :

    [modules]
    run = ["demo"]

Puis redémarrer la station. Liste vide (par défaut) : ni bus, ni module, la
station se comporte exactement comme avant.

Modules fournis : `cluster` (Cluster DX, voir `docs/cluster-dx.md` ; se règle
avec TRX Console, menu 12, qui l'ajoute ici) et `demo`, un module factice qui se met
en pause pendant l'émission et l'annonce dans le journal de la page web
(« [demo] Démo en pause pendant l'émission », puis « [demo] Démo reprise »).
Il sert à valider la chaîne complète sans matériel.

## Réglages

| Clé | Défaut | Rôle |
| --- | --- | --- |
| `run` | `[]` | Modules à faire tourner |
| `bus_port` | `47810` | Port de l'API interne, en 127.0.0.1 seulement |
| `run_as` | `"trx"` | Linux : compte des modules quand le superviseur est root |
| `extra_dir` | `""` | Dossier de modules supplémentaires (`<nom>/manifest.toml`) |

## Qui fait quoi

- **Passerelle** : démarre l'API interne (`trxstation/modules/bus.py`) et le
  pont (`gateway_bridge.py`), qui observe le PTT, la fréquence, le mode et
  l'état du poste, et les publie aux modules. Elle crée la clé des modules
  (`<state_dir>/modules.key`, lisible par elle seule).
- **Superviseur** : lance les modules comme processus enfants
  (`supervisor_glue.py`, `launcher.py`), à priorité basse, les relance s'ils
  s'arrêtent (délai croissant), les désactive après 5 arrêts en 5 minutes et
  envoie une alerte ntfy. Il attend que la clé existe avant de les lancer.
- **Page web** : affiche dans son journal les messages texte des modules.

## Règles de sécurité

- Le cœur n'attend jamais un module : publication sans blocage, file bornée
  par module, module trop lent déconnecté.
- Un module ne peut PAS demander le PTT. Seule commande autorisable : `qsy`,
  qui passe par le `PttController` (refusée hors RX confirmé, comme pour le
  client) et que le bus refuse déjà pendant toute émission.
- Un module ne tourne jamais en root. Superviseur root (Debian) : module lancé
  sous `run_as` ; compte absent, vide ou « root » : module non lancé.
- L'API interne n'écoute qu'en 127.0.0.1 ; chaque module s'identifie avec un
  secret dérivé de la clé, transmis par l'environnement (jamais en argument).
- Toute erreur des modules est journalisée et laisse la station tourner.

## Démonstration sans station

    python -m trxstation.modules.demo

Faux cœur + module factice : le PTT bascule toutes les 3 secondes.

## Pas encore fait

- Plafonds CPU et mémoire appliqués par le système (cgroups, Job Objects) et
  échelle de dégradation du superviseur : lot 2.
- Jetons de session délivrés au client (nécessaires au futur module vidéo).
- État des modules dans trx-monitor.
- Unités systemd séparées par module : `generate_systemd_unit` est prêt mais
  non utilisé ; les modules sont aujourd'hui enfants du superviseur partout.
