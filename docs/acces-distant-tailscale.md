# Accès distant : Tailscale + page web de contrôle

La passerelle sert une **page web de contrôle** (le client de référence) sur son port local. Tailscale la publie en HTTPS **uniquement
sur ton réseau privé** (ton « tailnet ») : rien n'est exposé à Internet. La même page te sert à tester le vrai trajet réseau
(Wi-Fi, 4G, latence, changement de réseau) avant d'écrire l'application Android.

## 1. Principe

```
téléphone ──(Tailscale / WireGuard, chiffré)──► PC : tailscale serve (HTTPS 443) ──► passerelle 127.0.0.1:8443
                                    └── audio WebRTC (UDP) directement vers le PC
```
- `gateway_bind` reste **127.0.0.1** (réglage par défaut) : la passerelle n'écoute jamais sur le réseau elle-même.
- **N'utilise jamais `tailscale funnel`** : il exposerait la page à Internet.

## 2. Installation

1. Installe **Tailscale** sur le PC et sur le téléphone, avec le **même compte**.
2. Console d'administration Tailscale (login.tailscale.com) > **DNS** : active **MagicDNS** et **HTTPS Certificates**
   (c'est ce qui permet au navigateur du téléphone d'autoriser le micro).
3. Démarre la station : `trx-supervisor --config station.toml` (mode géré sous Windows).
4. Publie la passerelle sur le tailnet, dans un terminal du PC :
   ```
   tailscale serve --bg 8443
   tailscale serve status
   ```
   (la syntaxe varie selon la version : `tailscale serve --help`). `tailscale serve status` affiche l'adresse, de la forme
   `https://<nom-du-pc>.<ton-tailnet>.ts.net/`. Pour retirer la publication : `tailscale serve reset`.
5. **Pare-feu Windows** : au premier lancement de la passerelle, Windows demande d'autoriser **python.exe**. Accepte
   (réseaux privés ; coche aussi « publics » si l'interface Tailscale est classée ainsi). Sans cela, la page s'ouvre mais l'audio
   (UDP) ne s'établit pas.

## 3. Utilisation sur le téléphone

1. Ouvre l'adresse `https://<nom-du-pc>.<ton-tailnet>.ts.net/` dans Chrome (ou Firefox).
2. Saisis l'**identifiant** et le **jeton** du client (section `[[clients]]` de `station.toml`). « Mémoriser sur cet appareil » les garde
   dans le navigateur de ce téléphone uniquement.
3. Laisse « Utiliser le micro » coché (le navigateur demande l'autorisation) puis **Se connecter**.
4. Tu dois voir : « Connecté », la fréquence et le mode du poste, le S-mètre, et **entendre le son reçu** (si le navigateur bloque la
   lecture, touche l'écran). La ligne du bas affiche le temps de réponse des commandes, la gigue et les pertes.
5. Essaie dans l'ordre : changer le mode, accorder une fréquence **en réception**, puis (charge fictive, puissance minimale, TOT interne du
   poste réglé) cocher **« Émission autorisée »** et appuyer sur **ÉMETTRE** ; rappuyer pour couper ; **STOP** coupe toujours.

### Sécurités de la page
- **Émission autorisée** : à cocher avant chaque émission ; se décoche seule dès que l'émission s'arrête (évite l'appui accidentel
  dans une poche).
- **Micro fermé** (silence envoyé) sauf pendant l'émission confirmée dont tu es le propriétaire.
- **Écran verrouillé, onglet en arrière-plan, page quittée pendant l'émission : STOP automatique.** Le navigateur ralentit alors ses
  minuteries, donc le signal de vie ne serait plus fiable ; la station coupe de toute façon au bout de ~2 s sans signal de vie.
- Un client qui perd sa connexion pendant l'émission : la station coupe seule (aucune action requise).

## 4. Quoi mesurer (4G contre Wi-Fi)

- **Commande** (ligne du bas) : durée aller-retour d'un ordre ; viser moins de 150 ms en 4G.
- **Gigue / pertes** : une gigue > 40 ms ou des pertes > 2 % rendent l'audio haché.
- `tailscale status` sur le PC : « direct » est préférable à « relay » (relais Tailscale, plus de latence).
- Passe du Wi-Fi à la 4G pendant la réception : la connexion peut tomber ; reconnecte-toi (l'émission, elle, est coupée par la station).

## 5. Dépannage

| Symptôme | Cause probable |
|---|---|
| La page ne s'ouvre pas | PC éteint ou Tailscale arrêté (PC ou téléphone) ; `tailscale serve status` vide ; mauvaise adresse |
| Avertissement « page en HTTP » | tu as ouvert l'adresse `http://` ou l'IP : utilise l'adresse `https://…ts.net` |
| « Micro indisponible » | page non HTTPS, ou HTTPS Certificates non activé dans la console Tailscale |
| « Micro refusé » | autorisation du micro refusée au navigateur : Paramètres du site > Micro |
| « Identifiant ou jeton refusé » | faute de frappe, ou 5 essais ratés : attendre une minute |
| Connecté mais pas de son | pare-feu Windows (python.exe), lecture bloquée (touche l'écran), « Couper le son » coché |
| « connexion failed » après quelques secondes | UDP bloqué (pare-feu, réseau d'entreprise) ; essaie une autre connexion |
| L'émission se coupe quand l'écran s'éteint | comportement voulu (voir « Sécurités de la page ») |

## 6. Sécurité

- Le **jeton** protège la commande de l'émetteur : ne le partage pas, régénère-le s'il a été affiché ou copié ailleurs.
- Limite qui peut joindre le PC dans les **ACL Tailscale** (au minimum : seulement tes appareils).
- `web_client = false` dans `[network]` de `station.toml` désactive la page (l'API WebRTC reste).
- La page est servie sous une **politique de sécurité stricte** (aucun script ni style en ligne, aucune ressource externe).
- Les essais de jeton ratés sont freinés **par origine** (l'adresse Tailscale du client), pas globalement.
