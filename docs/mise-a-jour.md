# Mise à jour depuis Internet (paquets signés Ed25519)

La station cherche une nouvelle version sur GitHub (dépôt `Bob56fr/openRemoteTRX`, API publique, sans
jeton) au démarrage puis toutes les 24 h. TRX Console l'annonce ; rien n'est installé sans confirmation.
Chaque paquet est **signé** par l'auteur : la station refuse tout paquet dont la signature n'est pas
valide. La version précédente est gardée et un retour en arrière est possible sans Internet.

Debian seulement (installation par `install.sh`). La 0.22 et les versions plus anciennes n'ont pas cet
outil : le passage à la 0.23.0 se fait une fois à la main (`sudo bash install.sh` avec le nouveau zip).

## Côté auteur : la clé de signature (une seule fois)

```
pip install -e ".[dev]"                 # cryptography
python scripts/gen_update_key.py
```

- Une phrase de passe est demandée (12 caractères au minimum) : elle chiffre la clé privée.
- La clé **privée** est écrite dans `%USERPROFILE%\.trx-remote\update-signing-key.pem` (Windows) ou
  `~/.trx-remote/update-signing-key.pem`, jamais dans le dépôt (refusé), jamais écrasée.
  Autre emplacement : variable `TRX_SIGNING_KEY` ou `--output`.
- La clé **publique** est ajoutée à `trxstation/update/pubkey.py` : à committer.
- **Sauvegarde la clé privée hors ligne** (clé USB rangée) avec sa phrase de passe. Perdue : il faut une
  nouvelle clé, et chaque station doit être réinstallée une fois à la main pour connaître la nouvelle clé
  publique. Volée : publie au plus vite une version dont `pubkey.py` ne contient plus l'ancienne clé.
- Changer de clé sans couper la chaîne : créer la nouvelle, publier une version qui contient LES DEUX clés
  publiques, signer les versions suivantes avec la nouvelle, puis retirer l'ancienne.
- `python scripts/gen_update_key.py --afficher` réaffiche la clé publique.

## Côté auteur : publier une version

1. Mettre la version dans `pyproject.toml` ET `trxstation/__init__.py` (ex. `0.24.0`).
2. Committer et pousser (la clé publique doit être dans `pubkey.py` du commit publié).
3. `python scripts/build_debian_zip.py` (phrase de passe demandée) produit dans `dist/` :
   `trx-remote-debian-0.24.0.zip` et `trx-remote-debian-0.24.0.zip.sig`. La signature est revérifiée
   aussitôt, comme le fera la station. Sans clé ou avec une clé absente de `pubkey.py` : erreur, pas de
   `.sig`. Pour un essai local seulement : `--sans-signature`.
4. Sur GitHub, créer une Release :
   - étiquette **`v` + la version exacte** de `pyproject.toml` : `v0.24.0` ;
   - joindre **les deux fichiers**, sans les renommer ;
   - notes de version : texte libre, affiché dans TRX Console (4 000 caractères au plus) ; écrire ce qui
     change POUR L'UTILISATEUR (une ligne par changement, « - … »), la console les montre sur demande avant
     d'installer, avec celles de toutes les versions sautées ;
   - pré-version : version de la forme `0.24.0rc1` (pas `0.24.0-rc1`) ET case « pre-release » cochée.
     Les stations l'ignorent sauf `[update] allow_prerelease = true`.

Une Release sans `.sig`, avec un autre nom de fichier ou une autre étiquette n'est jamais proposée.

## Côté station

```toml
[update]
enabled = true            # false : aucune requête vers GitHub
allow_prerelease = false  # true : propose aussi les pré-versions
```

- Recherche : timer `trx-update-check.timer` (compte `trx`, jamais root, sans droit particulier),
  2 minutes après le démarrage de la station puis toutes les 24 h. Résultat :
  `/var/lib/trx-remote/update/latest.json`. Hors ligne : la dernière version connue est gardée.
- TRX Console : cadre « NOUVELLE VERSION X DISPONIBLE » en haut du menu (noir sur jaune dans un
  terminal), menu 10 marqué « <== NOUVELLE VERSION X ». **Menu 10** : résumé, « Voir la nature des
  changements » (notes de chaque version publiée depuis celle installée, la plus récente d'abord, 12
  versions et 16 000 caractères au plus, par pages de 20 lignes ; une Release sans paquet signé compte
  aussi), puis confirmation en tapant le numéro de version ; à jour : nouvelle recherche immédiate
  proposée. **Menu 11** : retour à la version précédente. Le diagnostic (menu 1)
  a une section « Mise à jour ».
- Installation (`python -m trxstation.update.apply ... install --version X`, en root par TRX Console) :
  1. refus si le poste émet ou si on ne peut pas prouver qu'il n'émet pas (fichier d'état de la
     passerelle vivant ET relecture du PTT par rigctld) : arrêter la station (menu 6) lève le doute ;
  2. GitHub réinterrogé (latest.json, écrit par le compte trx, ne sert qu'à l'affichage) ;
  3. téléchargement, taille exacte, **signature vérifiée par le code déjà installé** ;
  4. contenu contrôlé (aucun chemin `..` ou absolu, aucun lien, version identique) ;
  5. nouvelle vérification de l'émission, arrêt de la station, `install.sh` du paquet vérifié.
  Code de sortie : 0 fait, 1 échec (version active inchangée), 3 refus émission, 4 refus paquet.
- Disposition : `/opt/trx-remote/releases/<version>/` (paquet + venv), liens `current`, `previous`,
  `venv -> current/venv`. Une seule version précédente est gardée.
- Conservés : `/etc/trx-remote/station.toml`, `/etc/trx-remote/tls/`, l'état de la station. Avant chaque
  changement de version : copie `station.toml.avant-<version>` (mêmes droits).
- Retour arrière (menu 11, ou `sudo bash /opt/trx-remote/previous/install.sh --reactiver`) : sans
  Internet. Si l'ancienne version refuse la configuration actuelle, la copie d'avant la mise à jour est
  remise et l'autre gardée dans `station.toml.version-<version>`.
- Échec en cours d'installation : la version incomplète est retirée et la station repart sur la
  version active. Compte-rendu : `/var/log/trx-remote-install.log`.

## Limites connues

- La signature couvre le code de TRX distant, pas les modules Python téléchargés par pip (aiortc, aiohttp…,
  versions minimales non épinglées) : même risque que l'installation manuelle. À faire : liste de versions
  épinglées avec empreintes (`--require-hashes`).
- Les notes de version ne sont pas signées : elles sont nettoyées (aucun caractère de contrôle) et ne
  servent qu'à l'affichage.
- Le temps de veille du PC ne compte pas dans les 24 h (minuterie monotone de systemd).
- NON VALIDÉ sur un vrai Debian : disposition `releases/`, migration depuis la 0.22, `--reactiver`,
  timer systemd, téléchargement réel depuis une Release.
