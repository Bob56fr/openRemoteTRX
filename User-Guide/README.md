# User Guide / Guide de l'opérateur

Documentation **opérationnelle** d'openRemoteTRX : installer une station, y intégrer son poste, l'essayer, puis
l'utiliser sur le réseau local et à distance. (La documentation technique et les cahiers des charges sont dans
[`docs/`](../docs/).)

| Langue | Guide | Page web |
|---|---|---|
| Français | [fr/README.md](fr/README.md) | https://bob56fr.github.io/openRemoteTRX/guide/ |
| English | [en/README.md](en/README.md) | https://bob56fr.github.io/openRemoteTRX/guide/en/ |
| Deutsch | [de/README.md](de/README.md) | https://bob56fr.github.io/openRemoteTRX/guide/de/ |
| Español | [es/README.md](es/README.md) | https://bob56fr.github.io/openRemoteTRX/guide/es/ |

Le guide français est la **référence** : toute modification s'y fait d'abord, puis dans les trois traductions (mêmes
noms de fichiers dans chaque dossier, mêmes blocs d'onglets, d'accordéons et d'encadrés « Sécurité » : les tests le
vérifient). Traductions allemande et espagnole à faire relire par quelqu'un dont c'est la langue.

## Onglets par système et accordéons

Ce qui diffère selon le système se range dans des onglets ; sur GitHub, ils se lisent l'un sous l'autre :

```
<!-- onglets -->
#### Debian

texte pour Debian

#### Raspberry Pi

texte pour le Raspberry Pi

#### Windows

texte pour Windows
<!-- /onglets -->
```

Les noms d'onglets sont toujours « Debian », « Raspberry Pi », « Windows », dans toutes les langues : un choix fait
dans un bloc vaut pour toute la page. Un détail facultatif se replie dans un accordéon (fermé à l'écran, ouvert à
l'impression) :

```
<details>
<summary>Titre</summary>

contenu

</details>
```

## Captures d'écran

Les captures sont faites **une fois, en anglais**, et servent à toutes les langues du guide ; seule leur légende est
traduite. Elles se placent dans `User-Guide/captures/` (nom en minuscules, chiffres et tirets, `.png` ou `.jpg`,
600 ko au plus : largeur 1000 à 1400 px) et s'insèrent seules sur leur ligne, avec la légende entre crochets :

```
![Légende de la capture](../captures/nom.png)
```

Elles sont publiées une seule fois à côté des pages, s'ouvrent en grand au toucher et passent dans le PDF. Contenu
public : masquer adresse IP, nom de machine, empreinte du certificat et identifiants avant de les ajouter. Les
schémas (`images/*.svg`) restent propres à chaque langue : ils contiennent du texte.
