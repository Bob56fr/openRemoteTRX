# openRemoteTRX-Autotest

Préqualification d'un poste depuis le navigateur : cahier des charges `docs/prequalif-web-cahier-des-charges.md`.

- `web/` : la page du mode A (Web Serial, sans Hamlib), en français et en anglais (`?lang=en`). Publiée sur
  https://bob56fr.github.io/openRemoteTRX/autotest/ (copiée par `.github/workflows/pages.yml`) ; bloc WordPress
  `docs/wordpress/autotest-lien.html`. Pilotes : Icom CI-V (`civ.js`), Yaesu FTDX10 (`yaesu.js`), Kenwood TS-890S
  (`kenwood.js`) ; traductions `i18n.js` + `en.js`.
- Tests : `node tests/js/autotest_test.js` (logique, garde d'émission, pannes) et `tests/test_autotest_page.py`.

## Essayer la page sur ce PC

Web Serial exige HTTPS ou `127.0.0.1`. Depuis n'importe quel dossier :

```
python C:\dev\openRemoteTRX\autotest\serve.py
```

(`python -m http.server --directory autotest/web` ne marche que lancé depuis la racine du dépôt : sinon erreur 404.)

puis ouvrir `http://127.0.0.1:8765/` dans Chrome ou Edge. Fermer avant tout logiciel qui tient le port du poste
(station openRemoteTRX, WSJT-X, logiciel du constructeur). Poste sur CHARGE FICTIVE pour les émissions.
