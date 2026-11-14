# 5. Utiliser la station à distance (hors du réseau local)

La station ne gère pas le réseau : elle écoute sur une adresse et un port, et protège l'accès par identifiant et
mot de passe. C'est toi qui choisis comment ton téléphone la joint depuis l'extérieur. Le guide technique complet :
https://github.com/Bob56fr/openRemoteTRX/blob/main/docs/acces-distant.md

## 5.1 Choisir : VPN ou port ouvert

| | A. VPN (recommandé) | B. Port ouvert sur la box |
|---|---|---|
| Principe | un VPN relie le téléphone au réseau de la station | la box redirige un port d'Internet vers la station |
| Exemples | WireGuard (souvent intégré à la box), Tailscale, OpenVPN | box + nom de domaine + certificat reconnu |
| Visible depuis Internet | rien | la page de connexion |
| Son (WebRTC, UDP) | passe simplement | passe souvent, **pas toujours** (box stricte, partage d'adresse de l'opérateur) |

Choisis le VPN si tu hésites : rien n'est exposé, et le son passe.

## 5.2 Option A : VPN

1. Installe le VPN de ton choix : serveur sur la box ou sur le PC de la station, client sur le téléphone.
   Pour Tailscale, un guide dédié : https://github.com/Bob56fr/openRemoteTRX/blob/main/docs/acces-distant-tailscale.md
2. **Un profil VPN par appareil**, jamais partagé. Deux appareils sur le même profil se volent la liaison : coupures
   toutes les 15 à 30 secondes.
3. Si le VPN arrive **sur ton réseau local** (VPN de la box) : rien à changer à la station, utilise la même adresse
   qu'à la maison. Si le VPN donne au PC de la station **une adresse à part** (Tailscale, WireGuard sur le PC) :
   relance l'assistant (menu 3.1, accès réseau) pour que le certificat couvre aussi cette adresse, puis refais
   l'appairage de l'application (menu 4.1).
4. Sur le téléphone, en 4G, VPN actif : ouvre la même page `https://<adresse-de-la-station>:8443`.

Sous Android, un seul VPN peut être actif à la fois. Avec **Android Auto**, ne fais passer par le tunnel que le
réseau de la station (pas tout le trafic), sinon la voiture refuse la liaison : réglages détaillés dans le guide
technique, section « Android Auto et VPN ».

## 5.3 Option B : port ouvert sur la box

À réserver à qui connaît sa box et les certificats.

1. **Vérifie que c'est possible** : compare l'adresse « WAN » de ta box à celle que donne un site « quelle est mon
   adresse IP ». Si elles diffèrent, ton opérateur partage ton adresse (CGNAT) : aucun port ne peut être ouvert,
   prends un VPN.
2. Un **nom de domaine** qui pointe vers ta box (DNS dynamique si l'adresse change).
3. Un **certificat reconnu** : le plus simple est un proxy HTTPS (Caddy) sur le PC de la station, qui obtient et
   renouvelle seul un certificat Let's Encrypt ; la station reste alors en écoute locale. Exemple et réglages dans
   le guide technique, section « Option B ».
4. Redirige sur la box le port 443 (TCP) vers le PC de la station.

> **Sécurité.** Avec un port ouvert, le **mot de passe est ta seule barrière** : long et unique pour chaque compte.
> La station freine les essais (5 échecs par minute et par origine, 30 par quart d'heure et par compte), mais un mot
> de passe volé permet d'émettre dans tes bandes autorisées. Les sécurités d'émission restent actives dans tous les
> cas, et le minuteur d'émission du poste (partie 1) aussi.

## 5.4 Essais depuis l'extérieur

Téléphone **en 4G** (Wi-Fi coupé), charge fictive sur le poste :

1. La page s'ouvre (option B : cadenas sans avertissement).
2. Un mauvais mot de passe est refusé.
3. Le bon mot de passe connecte : fréquence, S-mètre, **son reçu**.
4. Émission sur charge fictive : PTT, puis **STOP** ; puis émission et passage en mode avion : retour en réception.
5. Si la page s'ouvre mais que le son ne s'établit pas : c'est l'UDP qui ne passe pas (option B) : passe au VPN.

En cas de coupures répétées, le menu 2.4 (qualité du réseau) dit quel tronçon lâche : téléphone, réseau mobile,
tunnel, box ou station.
