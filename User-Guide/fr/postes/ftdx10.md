# Fiche du poste : Yaesu FTDX10

> **Préparé, pas encore validé sur un vrai poste.** Réglages tirés du *CAT Operation Reference Manual* du FTDX10
> (Yaesu, édition 2308-F), de la notice du pilote USB (2205-E) et des capacités de Hamlib. Le premier opérateur
> qui fait les essais de la [partie 3](../03-integrer-et-essayer-le-trx.md) valide cette fiche : merci de
> rapporter le résultat.

## Identité pour la station

| | |
|---|---|
| Numéro Hamlib | **1042** (« FTDX10 ») |
| Liaison | USB, port « **Enhanced COM Port** », **38400** bauds |
| PTT | par **CAT** (la station envoie la commande d'émission par le port USB) |
| Carte son | « USB Audio CODEC » (réception et émission) |
| Lu par la station | fréquence, mode, filtres, S-mètre, puissance, ALC, TOS, tension, VFO A / B, split, clarifieur |
| Pas disponible | spectre HF du poste (Yaesu n'envoie pas les données de l'écran par CAT : seul le spectre audio est affiché) ; température du poste (le seuil de température de la station est sans effet) |

## Pilote USB (Windows)

1. **Câble USB débranché.** Télécharge le pilote « CP210x Universal Windows Driver » (lien sur le site de Yaesu, ou
   directement chez Silicon Labs) et décompresse-le.
2. Clic droit sur le fichier **`silabser.inf`** > (Windows 11 : « Afficher plus d'options ») > **Installer**.
3. Branche le câble USB, allume le poste : Windows termine l'installation (redémarrage parfois demandé). Le pilote
   de la carte son est celui de Windows, rien à faire.
4. Gestionnaire de périphériques > Ports (COM et LPT) : deux lignes « Silicon Labs Dual CP210x USB to UART Bridge » :
   **Enhanced COM Port (COMx)** pour la station, Standard COM Port (COMy) inutilisé. Un « ! » ou une croix sur une
   ligne : désinstalle puis réinstalle le pilote.

Sous Debian : aucun pilote. Les noms stables des ports sont dans `/dev/serial/by-id/` (`…CP2105…-if00-port0` =
Enhanced, `…-if01-port0` = Standard) ; l'assistant propose d'office le bon.

## Menus à régler

Chemins tels qu'ils apparaissent dans le menu de réglages du poste (voir le manuel d'utilisation du FTDX10 pour
l'ouvrir). Les réglages « MODE » se font **pour chaque mode** que tu veux utiliser en phonie.

### Liaison CAT : OPERATION SETTING > GENERAL

| Menu | Valeur | Pourquoi |
|---|---|---|
| CAT RATE | **38400 bps** | même débit que dans la station (proposé par l'assistant) |
| CAT TIME OUT TIMER | **1000 msec** | valeur proposée par l'assistant |
| CAT RTS | **ENABLE** | Hamlib utilise le contrôle de flux RTS/CTS sur ce poste |
| TX TIME OUT TIMER | **3** (minutes) | seconde sécurité du poste lui-même, au-delà du temps maximal de la station (90 s) |

(`232C RATE` et `232C TIME OUT TIMER` concernent la prise RS-232C : sans effet par l'USB.)

### Voix par l'USB : RADIO SETTING > MODE SSB, MODE AM, MODE FM, MODE PSK/DATA

| Menu (dans chaque mode) | Valeur | Pourquoi |
|---|---|---|
| SSB / AM / FM / DATA **MOD SOURCE** | **REAR** | la modulation vient de l'arrière du poste, pas du micro de façade |
| **REAR SELECT** | **USB** | l'arrière = l'USB (et non la prise DATA) |
| **RPTT SELECT** | **DAKY** | le PTT « arrière » reste sur la prise DATA, où rien n'est branché ; **jamais RTS ni DTR** |
| RPORT GAIN | à ajuster (partie 3) | niveau de la voix qui arrive par l'USB : à régler avec l'ALC |
| SSB / AM / FM / DATA OUT LEVEL | valeur d'usine au départ | niveau du son reçu envoyé vers l'USB : à monter si le son reçu est faible |

Sans « MOD SOURCE = REAR » en BLU, l'assistant limite l'émission aux modes données (DATA-U, DATA-L) : la page ne
pourra pas émettre en USB / LSB.

> **Sécurité : RPTT SELECT et PC KEYING.** Yaesu prévient que, quand le PTT passe par les lignes du port USB, *« le
> poste peut passer en émission au démarrage de l'ordinateur »*. La station n'utilise pas ces lignes : laisse
> **RPTT SELECT = DAKY** dans chaque mode et **CW SETTING > MODE CW > PC KEYING = OFF**.

### Autres réglages conseillés

| Menu | Valeur | Pourquoi |
|---|---|---|
| Touche **VOX** de la façade | **éteinte** | avec la voix par l'USB, un son parasite du PC pourrait faire émettre le poste |
| OPERATION SETTING > TX GENERAL > HF MAX POWER (et 50M, 70M, AM) | la puissance que tu t'autorises | plafond du poste lui-même, que la station ne peut pas dépasser |
| OPERATION SETTING > TX GENERAL > EMERGENCY FREQ TX | **DISABLE** | pas d'émission sur la fréquence d'urgence |

## Correspondance des modes

| Page web / Hamlib | Écran du FTDX10 |
|---|---|
| USB / LSB | USB / LSB |
| PKTUSB / PKTLSB | DATA-U / DATA-L |
| FM / PKTFM | FM / DATA-FM |
| AM | AM |
| CW / CWR | CW-U / CW-L |

## Points à vérifier lors des essais (validation de cette fiche)

À noter dans le rapport de la [partie 3](../03-integrer-et-essayer-le-trx.md) :

1. Le diagnostic (menu 2.1) trouve le poste ; fréquence et mode suivent quand tu tournes le VFO.
2. Voyant **VFO A / VFO B** de la page quand tu appuies sur A/B du poste.
3. Émission sur charge fictive : la page voit puissance, **ALC** et TOS ; le niveau ALC à pleine voix (le seuil
   d'alerte de l'ALC n'a pas encore été relevé sur un Yaesu).
4. Split activé sur le poste : la page l'affiche, l'émission part sur la bonne fréquence.
5. Émission au micro du poste : la page affiche « opérateur sur place » et bloque le PTT à distance.
6. Aucun passage en émission au démarrage du PC ni au branchement du câble.
