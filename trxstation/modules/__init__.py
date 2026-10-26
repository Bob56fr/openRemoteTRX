"""Socle de l'architecture en modules de la station TRX distant (lot 1a).

Ce paquet ne dépend que de la bibliothèque standard Python (3.11+).
Il fournit :
- tokens    : jetons de session signés délivrés par la passerelle ;
- manifest  : lecture et validation des manifestes de modules ;
- protocol  : format des messages de l'API interne ;
- bus       : serveur de l'API interne, côté cœur (passerelle) ;
- client    : bibliothèque côté module ;
- launcher  : lancement et surveillance des modules, côté superviseur ;
- keys      : clé des modules (créée par la passerelle) et secrets dérivés ;
- registry  : modules choisis dans [modules] run ;
- gateway_bridge, supervisor_glue : branchement dans la passerelle et le superviseur.
"""

API_VERSION = "1.0"
DEFAULT_BUS_HOST = "127.0.0.1"
DEFAULT_BUS_PORT = 47810

__all__ = ["API_VERSION", "DEFAULT_BUS_HOST", "DEFAULT_BUS_PORT"]
