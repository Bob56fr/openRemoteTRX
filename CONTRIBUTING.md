# Contribuer à openRemoteTRX

*English version below.*

Merci de votre intérêt ! Les échanges se font en **français, anglais, allemand ou espagnol**.

## Signaler un problème ou proposer une idée

- Ouvrez un ticket (*Issues > New issue*) avec le formulaire de votre langue : « Signaler un bug » ou « Proposer une amélioration ».
- Un ticket est **public** : jamais de mot de passe, de clé, d'adresse IP publique ni de nom de domaine personnel. Le rapport de dépannage de TRX Console (menu 2.3) n'en contient pas.
- Les codes d'erreur `ORT-NNNN` sont expliqués sur la [page des codes d'erreur](https://bob56fr.github.io/openRemoteTRX/erreurs/).

## Proposer du code

1. Ouvrez d'abord un ticket pour en discuter : certaines décisions du projet sont arrêtées.
2. **Sécurité d'émission avant tout** : PTT en bascule uniquement (jamais en maintien), état RX/TX tenu par la station, réception au démarrage, en cas de doute ne pas émettre. Tout code qui peut activer le PTT arrive avec ses tests de panne (battement perdu, TOT, déconnexion, passerelle gelée).
3. Les tests utilisent le modèle factice de Hamlib (numéro 1), jamais un vrai poste : `pytest` (lance aussi les tests de la page web sous Node).
4. Aucun code propre à un modèle de poste : tout passe par Hamlib.
5. Chaque nouveau fichier de code commence par l'en-tête de licence :
   ```
   # SPDX-License-Identifier: AGPL-3.0-or-later
   # Copyright (C) 2026 RF-DIY.COM
   ```
6. En proposant une contribution, vous acceptez qu'elle soit publiée sous la licence [AGPL-3.0-or-later](LICENSE).

## Réglementation

Chaque opérateur reste responsable de ses émissions, selon sa licence et la réglementation de son pays.

---

# Contributing to openRemoteTRX

Thank you for your interest! Discussions take place in **French, English, German or Spanish**.

## Reporting a problem or suggesting an idea

- Open an issue (*Issues > New issue*) with the form in your language: "Report a bug" or "Suggest an improvement".
- Issues are **public**: never post passwords, keys, public IP addresses or personal domain names. The TRX Console troubleshooting report (menu 2.3) contains none of these.
- `ORT-NNNN` error codes are explained on the [error codes page](https://bob56fr.github.io/openRemoteTRX/erreurs/).

## Contributing code

1. Open an issue first to discuss it: some project decisions are settled.
2. **Transmit safety first**: toggle-only PTT (never push-and-hold), the RX/TX state is owned by the station, receive at startup, when in doubt do not transmit. Any code that can key the PTT comes with its failure tests (lost heartbeat, TOT, disconnection, frozen gateway).
3. Tests use the Hamlib dummy model (number 1), never a real radio: `pytest` (also runs the web page tests under Node).
4. No radio-specific code: everything goes through Hamlib.
5. Every new code file starts with the licence header shown above.
6. By submitting a contribution, you agree that it is published under the [AGPL-3.0-or-later](LICENSE) licence.

## Regulations

Every operator remains responsible for their transmissions, according to their licence and their country's regulations.
