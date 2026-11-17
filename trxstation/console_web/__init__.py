# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console dans le navigateur (`trx-console --web`, docs/console-web-cahier-des-charges.md).

Programme À PART de la passerelle (qui ne doit jamais pouvoir écrire station.toml), lancé par l'opérateur sous son
compte, à l'écoute sur 127.0.0.1 seulement, ouvert par un jeton à usage unique. La page montre l'état de la station,
les thèmes et l'aide de chaque menu ; les menus se déroulent dans UN terminal intégré (xterm.js) où tourne la console
texte elle-même, pour toute la session (sudo ne redemande pas le mot de passe à chaque menu).
"""
