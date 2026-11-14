# 2. Installer la station

L'installation ne commande jamais le poste : il peut rester allumé et branché.

## 2.1 Debian (12 ou 13, avec bureau)

1. Télécharge `trx-remote-debian-X.Y.Z.zip` (partie 0) dans **Téléchargements**, clic droit > « Extraire ici ».
2. Dans le dossier obtenu : clic droit dans une zone vide > « Ouvrir dans un terminal », puis :

   ```
   sudo bash install.sh
   ```

   Ton mot de passe de session est demandé (rien ne s'affiche pendant la frappe : c'est normal). Le script installe
   Hamlib, Python, les modules, le compte de service et les services de la station.
3. À la fin, **déconnecte-toi puis reconnecte-toi** (les droits de ton compte changent).
4. Ouvre **TRX Console** depuis le menu des applications (ou tape `trx-console` dans un terminal). Elle propose
   l'assistant de configuration : c'est la partie 3.

Sans bureau (serveur), tout se fait par SSH : copie le zip, puis

```
unzip -q trx-remote-debian-*.zip && cd trx-remote-debian-*/ && sudo bash install.sh
```

ferme la connexion SSH, reconnecte-toi et tape `trx-console`.

## 2.2 Windows 10 / 11

1. Installe **Hamlib 64 bits** (`hamlib-w64-X.Y.Z.exe`, version 4.6 ou plus récente) depuis
   https://github.com/Hamlib/Hamlib/releases, dans le dossier proposé.
2. Copie `trx-remote-windows-X.Y.Z.zip` sur le PC. Clic droit > Propriétés > coche **Débloquer** > OK.
3. Clic droit > Extraire tout, puis double-clic sur **`installer.cmd`**. Si Windows affiche « Windows a protégé
   votre ordinateur » : Informations complémentaires > Exécuter quand même.
4. Accepte la demande d'administrateur et réponds aux questions (Python est installé s'il manque, avec ton accord).
5. Réglages de Windows indispensables :
   - réseau de la maison en profil **Privé** (le pare-feu n'ouvre la station que sur les réseaux privés) ;
   - **veille et hibernation désactivées** (Paramètres > Système > Alimentation) ;
   - *Paramètres > Confidentialité > Microphone* : accès autorisé aux applications de bureau (sinon le son reçu du
     poste est un silence).

La notice complète (`notice-windows.html`) est dans le paquet.

### Correspondance Windows / TRX Console

Ce guide cite les menus de TRX Console (Debian). Sous Windows :

| TRX Console (Debian) | Windows : menu Démarrer > TRX distant |
|---|---|
| 3.1 Assistant de configuration | 1 - Configuration de la station |
| 2.1 Diagnostic | 2 - Diagnostic |
| 1.1 Démarrer / 1.2 Arrêter | 3 - Démarrer la station / 4 - Arrêter la station |
| 1.3 Tableau de bord | 5 - Tableau de bord |
| 2.2 Essai du poste | 6 - Essai du poste (station arrêtée d'abord) |
| 1.4 Journal | 7 - Journaux de la station |
| 3.2 Modifier station.toml | éditer `C:\ProgramData\trx-remote\station.toml` (Bloc-notes lancé en administrateur), puis arrêter et redémarrer la station |
| 4.1 Appairage d'un téléphone | `trx-setup --empreinte` dans un terminal (adresse, comptes, empreinte du certificat ; pas de QR code) |
| 6.1 Mise à jour | relancer `installer.cmd` d'une nouvelle version |

Les autres menus de TRX Console (profils, visiteurs, Cluster DX…) sont propres à Debian ; sous Windows, leurs
réglages se font dans `station.toml` (notice de chaque réglage : https://bob56fr.github.io/openRemoteTRX/station-toml/).
Les commandes (`trx-setup`, `trx-monitor`, `trx-hwtest`…) se lancent dans un terminal ouvert **après**
l'installation.
