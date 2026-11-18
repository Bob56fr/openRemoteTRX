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
     poste est un silence) ;
   - carte son du poste (*Paramètres > Système > Son*, sortie « Haut-parleurs » du poste) : **volume à 100**,
     **améliorations audio désactivées**, format 16 bits 48000 Hz ; le niveau d'émission se dose sur le poste (Icom :
     USB MOD Level). Un volume réduit (38 vu sur un PC) donne une émission sans puissance. Son nom (« 2- USB Audio
     Device »…) change si le câble du poste passe sur une autre prise USB : refaire alors le menu 2.6.

La notice complète (`notice-windows.html`) est dans le paquet.

### TRX Console sous Windows

L'installation crée **un seul raccourci** : menu Démarrer > **TRX distant**. Il ouvre TRX Console, avec les mêmes
menus numérotés que sous Debian : ce guide s'applique tel quel (1.1 démarrer, 2.1 configuration, 6.1 diagnostic…).
Différences :

- **Mises à jour** (menus 7.1 à 7.3) : sous Windows, extrais le nouveau zip et lance son `installer.cmd` ; la
  configuration est gardée. Retour en arrière : relance `installer.cmd` de l'ancienne version.
- **Indicateur près de l'horloge** : menu 8.4 (le lancer, ou le lancer à chaque ouverture de session).
- **Désinstaller** : Paramètres > Applications > **TRX distant** > Désinstaller (la configuration est gardée sauf si
  tu demandes de l'effacer).
- La configuration est dans `C:\ProgramData\trx-remote\station.toml` ; les commandes (`trx-console`, `trx-setup`,
  `trx-monitor`…) se lancent aussi dans un terminal ouvert **après** l'installation.
