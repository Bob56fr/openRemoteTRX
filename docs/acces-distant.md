# Accès distant : VPN ou port exposé (au choix de l'utilisateur)

La station **ne gère pas le réseau** : elle écoute sur une adresse et un port, et protège l'accès par **identifiant + mot de passe**.
C'est à toi de décider comment ton téléphone ou ta voiture la joint. Deux familles de solutions :

| | A. VPN (recommandé) | B. Port exposé sur la box |
|---|---|---|
| Principe | un VPN de ton choix relie le téléphone à la station | la box redirige un port d'Internet vers la station |
| Exemples | WireGuard, OpenVPN, Tailscale, ZeroTier, VPN de la box | box + nom de domaine dynamique + HTTPS |
| Exposé à Internet | rien | la page de connexion |
| Audio WebRTC (UDP) | fonctionne simplement | dépend de ta box / de ton opérateur (voir plus bas) |
| Difficulté | moyenne (installer le VPN) | moyenne (box, domaine, certificat) |

Dans les deux cas, la station applique les mêmes protections : mot de passe haché, freinage des essais, bandes autorisées, durée
maximale d'émission, coupure à la perte du client, superviseur.

## 1. Mots de passe

- Créer un client : `trx-setup --add-client phone -o station.toml` (saisie masquée, double saisie ; **Entrée = en générer un fort**).
- Changer un mot de passe : `trx-setup --set-password phone -o station.toml`.
- **Règle** : 12 caractères minimum, au moins 5 caractères différents, ne contient pas l'identifiant. Une **phrase de passe longue**
  est préférable ; un mot de passe généré (≈ 128 bits) est le plus sûr.
- Dans `station.toml`, seule l'**empreinte** (`password_hash`, scrypt) est enregistrée, jamais le mot de passe. Un mot de passe oublié
  se remplace (il ne se retrouve pas).
- Les anciens jetons en clair (`token = "..."`) fonctionnent encore mais déclenchent un avertissement : remplace-les.
- **Si le port est exposé sur Internet, le mot de passe est ta seule barrière : choisis-le long et unique.**

## 2. Réglages `[network]` de `station.toml`

| Réglage | Rôle | Défaut |
|---|---|---|
| `gateway_bind` | adresse d'écoute : `127.0.0.1` (machine seule), l'IP du VPN, ou `0.0.0.0` (toutes) | `127.0.0.1` |
| `gateway_port` | port d'écoute | `8443` |
| `tls_cert`, `tls_key` | HTTPS natif (fichiers PEM) | vides |
| `allow_insecure_http` | autorise l'écoute **hors machine sans TLS** (réservé à un VPN qui chiffre déjà) | `false` |
| `trusted_proxies` | adresses/réseaux dont l'en-tête `X-Forwarded-For` est cru (proxy HTTPS devant) | boucle locale |
| `ice_servers` | serveurs STUN pour l'audio ; `[]` = réseau local ou VPN uniquement | STUN public de Google |
| `web_client` | sert la page web de contrôle | `true` |

**Garde-fou** : si `gateway_bind` n'est pas la boucle locale, sans TLS et sans `allow_insecure_http = true`, la passerelle **refuse de
démarrer son API** (elle reste en réception seule) et l'écrit dans son journal : un mot de passe ne doit jamais circuler en clair.

## 3. Option A : VPN

1. Installe le VPN de ton choix sur la machine de la station **et** sur le téléphone (ils reçoivent chacun une adresse privée).
2. Réglages de la station :
   ```toml
   [network]
   gateway_bind = "10.8.0.1"          # l'adresse de la station DANS le VPN
   allow_insecure_http = true         # le VPN chiffre déjà le trafic
   ice_servers = []                   # pas de STUN public : le VPN suffit
   ```
3. Sur le téléphone, VPN actif : `http://10.8.0.1:8443/`.

**Limite du navigateur** : sans HTTPS, Chrome refuse l'accès au **micro** sur cette page. Tu peux écouter et commander, pas émettre.
Pour émettre depuis le navigateur, ajoute le TLS (section 4, `trx-setup --self-signed`, ou un certificat de ton réseau). L'application
Android, elle, n'a pas cette contrainte.

Sous Android, **un seul VPN** peut être actif à la fois.

### Android Auto et VPN (WireGuard)

**Symptôme** : Android Auto affiche « Erreur de communication 21 - Si vous êtes connecté à un VPN… ».

**Cause** : un tunnel qui fait passer TOUT le trafic (`AllowedIPs = 0.0.0.0/0, ::/0`) emporte aussi la liaison locale entre le
téléphone et la voiture. Android Auto sans fil passe par un Wi-Fi direct, en général `192.168.49.x`.

Il faut que seul le chemin vers la station passe par le tunnel. Dans l'application WireGuard, modifiez le tunnel (crayon) :

1. **Côté pair (Peer), « IP autorisées »** : ne mettre que l'adresse de la station dans le VPN et, si besoin, son réseau
   local. Exemple : `10.8.0.0/24, 192.168.1.0/24` au lieu de `0.0.0.0/0, ::/0`. Le reste du téléphone, Internet en 4G et la
   voiture compris, sort alors normalement. Le réseau local de la station ne doit pas être `192.168.49.0/24`.
2. **Côté interface, « Applications exclues »** : cochez **Android Auto**. Si l'erreur persiste, cochez aussi **Services
   Google Play**. Ne cochez **pas** openRemoteTRX : elle doit passer par le tunnel.
3. Dans Android, Paramètres > Connexions > Plus de paramètres de connexion > VPN > roue dentée de WireGuard : **« Bloquer
   les connexions sans VPN » désactivé**. Ce réglage bloque Android Auto même avec les deux points ci-dessus.
4. Désactivez puis réactivez le tunnel, débranchez ou rebranchez la voiture, puis vérifiez qu'openRemoteTRX se connecte
   encore à la station.

Avec Android Auto **filaire** (câble USB), l'erreur est en général absente, mais le réglage 1 reste conseillé.

## 4. Option B : port exposé

### Prérequis
- Une **adresse IP publique** : certains opérateurs (4G/5G, fibre partagée) placent leurs clients derrière un partage d'adresse
  (CGNAT) où **aucun port ne peut être ouvert**. Compare l'adresse « WAN » de ta box à celle que montre un site « quelle est mon IP » :
  si elles diffèrent, utilise un VPN.
- Un **nom de domaine** pointant vers ta box (service de DNS dynamique si l'adresse change).

### Le HTTPS est obligatoire
Deux manières :
1. **Proxy inverse sur la même machine (recommandé)** : par exemple Caddy, qui obtient et renouvelle seul un certificat reconnu
   (Let's Encrypt), avec les ports 80 et 443 redirigés vers la machine :
   ```
   station.mondomaine.org {
       reverse_proxy 127.0.0.1:8443
   }
   ```
   La passerelle reste sur `127.0.0.1` (réglage par défaut) ; le proxy local est reconnu automatiquement pour `X-Forwarded-For`.
2. **TLS natif** : `tls_cert` et `tls_key` pointent vers tes fichiers PEM (par exemple fournis par certbot), `gateway_bind = "0.0.0.0"`,
   et le port `gateway_port` redirigé. Pour un **essai** : `trx-setup --self-signed station.mondomaine.org -o station.toml` génère un
   certificat auto-signé (chiffré, mais le navigateur affichera un avertissement à accepter).

### Redirections sur la box
- TCP 443 (ou le port choisi) vers la machine de la station.
- **Audio** : le son passe par WebRTC, donc en **UDP**, sur des ports choisis au hasard par la station. La traversée de box se fait
  par STUN (`ice_servers`) et **fonctionne souvent** derrière une box ordinaire, mais **pas toujours** (NAT strict, CGNAT). Je ne peux
  pas, pour l'instant, fixer une plage de ports UDP à rediriger. Si la page s'ouvre mais que le son ne s'établit pas : passe à
  l'option A (VPN), ou installe un relais TURN de ton choix et ajoute-le dans `ice_servers` (`turn:...`).

### Ce que la station fait pour te protéger
- Mot de passe haché (scrypt), vérifié hors de la boucle de sécurité de l'émission.
- Freinage : **5 échecs par minute et par origine**, **30 échecs par 15 minutes et par compte** ; aucun calcul quand c'est verrouillé ;
  réponse identique que l'identifiant existe ou non.
- Chaque refus est écrit dans le journal avec l'origine.
- Page servie sous politique de sécurité stricte ; aucun mot de passe mémorisé par la page.
- Toutes les protections d'émission restent actives (bandes, durée maximale, perte du client, superviseur).

### Ce que ces protections ne couvrent pas
- Un **mot de passe volé ou faible** : la personne pourrait émettre dans les bandes autorisées, jusqu'à la durée maximale à chaque fois.
  C'est pourquoi le **TOT interne du poste** et une **charge/antenne conformes** restent indispensables.
- Un attaquant réparti sur de nombreuses adresses peut verrouiller ton **compte** quelques minutes (le freinage par compte protège le
  mot de passe, au prix de cette gêne).
- Les failles des composants que tu ajoutes (box, proxy, système) : garde-les à jour, n'expose que ce port.

### Mesures complémentaires conseillées
Liste blanche d'adresses dans le proxy ou le pare-feu si tu as une adresse fixe côté mobile ; authentification supplémentaire du proxy
(certificat client) ; éteindre ou isoler la station quand tu ne t'en sers pas.

## 4 bis. Micro dans le navigateur quand la page n'est pas en HTTPS reconnu

Le navigateur bloque le micro sur toute page en HTTP (hors `localhost`). C'est une règle du navigateur : aucune case à cocher dans la page ne peut
la lever. Deux manières de donner l'autorisation **au niveau du navigateur** :

1. **HTTPS auto-signé (recommandé pour un essai en réseau local)** :
   ```
   trx-setup --self-signed 192.168.1.20 -o station.toml     (l'adresse du PC ; ajoute un nom si tu en as un)
   ```
   Redémarre la station, puis ouvre `https://192.168.1.20:8443/` sur le téléphone. Le navigateur signale un certificat non reconnu : « Avancé »,
   puis « Continuer ». Le micro est ensuite proposé normalement. Bénéfice supplémentaire : le mot de passe ne circule plus en clair sur le Wi-Fi.
   Réserve au PC une adresse fixe dans ta box (réservation DHCP), sinon le certificat ne correspondra plus à l'adresse.
2. **Réglage de Chrome pour cette adresse** : dans Chrome, ouvre `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, active le
   réglage, ajoute l'origine **exacte** (protocole, adresse et port : `http://192.168.1.20:8443`), puis relance Chrome. Il traitera cette
   seule origine comme sûre. Ce réglage reste propre à ce navigateur ; retire-le après les essais. Le mot de passe voyage alors toujours en clair
   sur le réseau local.

L'application Android n'a pas cette contrainte (elle capte le micro sans passer par le navigateur).

## 5. Mise en service : à vérifier une fois

1. De l'extérieur (4G, VPN actif ou non selon l'option) : la page s'ouvre en HTTPS (cadenas) dans l'option B.
2. Un **mauvais mot de passe** est refusé, et le message est le même pour un identifiant inconnu.
3. Cinq mauvais essais de suite : l'accès est refusé un moment, **même avec le bon mot de passe**, puis revient.
4. Le bon mot de passe connecte : fréquence, mode, S-mètre, son reçu.
5. Charge fictive, puissance minimale : la prise d'émission fonctionne, **STOP** coupe, écran verrouillé pendant l'émission coupe.
6. Journal de la passerelle : les refus apparaissent avec l'origine attendue (pas toujours `127.0.0.1` derrière un proxy : sinon,
   `trusted_proxies` est mal réglé).

## 6. Dépannage

| Symptôme | Cause probable |
|---|---|
| « API NON DÉMARRÉE … SANS chiffrement » dans le journal | `gateway_bind` hors boucle locale sans TLS : ajoute le TLS, un proxy HTTPS, ou `allow_insecure_http = true` (VPN seulement) |
| « certificat TLS inutilisable » | chemins ou droits des fichiers `tls_cert`/`tls_key`, certificat et clé qui ne vont pas ensemble |
| Page ouverte mais « Micro indisponible » | page en HTTP : il faut HTTPS (hors `localhost`) |
| Connecté mais pas de son | UDP bloqué (pare-feu, box, CGNAT) : option A, ou relais TURN ; vérifier `ice_servers` |
| Toutes les origines apparaissent comme `127.0.0.1` | le proxy n'envoie pas `X-Forwarded-For`, ou n'est pas dans `trusted_proxies` |
| Un attaquant verrouille tout le monde | l'origine vue est celle du proxy : régler `trusted_proxies` et l'en-tête du proxy |
| « Identifiant ou mot de passe refusé » alors qu'ils sont justes | verrou après trop d'essais (attendre), ou mot de passe modifié (`--set-password`) |
