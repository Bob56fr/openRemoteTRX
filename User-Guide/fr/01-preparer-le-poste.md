# 1. Préparer le poste

Station **éteinte**, rien de branché : c'est le moment de régler le poste. Le détail des menus du FTDX10 est dans
[la fiche du poste](postes/ftdx10.md) ; cette partie dit dans quel ordre faire les choses.

## 1.1 Installer le pilote USB (Windows seulement)

Sous Windows, le pilote **Silicon Labs CP210x** doit être installé **avant** de brancher le câble USB du poste ;
sinon Windows peut installer un mauvais pilote. Voir [la fiche du poste](postes/ftdx10.md), « Pilote USB ».

Sous Debian, rien à installer : le noyau reconnaît le poste tout seul.

## 1.2 Brancher

1. Antenne débranchée, **charge fictive** sur la prise d'antenne utilisée.
2. Câble USB entre l'arrière du FTDX10 et le PC.
3. Allume le poste (appui long sur ON/OFF).

Le PC voit alors **deux ports série** et **une carte son** (« USB Audio CODEC ») :

| Port | Rôle | À utiliser pour |
|---|---|---|
| **Enhanced COM Port** | commande du poste (CAT) | **la station** |
| Standard COM Port | lignes RTS/DTR (PTT, manipulation CW) | rien : la station ne s'en sert pas |

Sous Windows : Gestionnaire de périphériques > Ports (COM et LPT), note le numéro COM de l'« Enhanced COM Port ».
Sous Debian, l'assistant reconnaît lui-même le bon port.

## 1.3 Régler les menus du poste

Règle les menus listés dans [la fiche du poste](postes/ftdx10.md), section « Menus à régler ». Ils sont
indispensables :

- **débit du CAT** identique à celui de la station (38400 bps) ;
- **voix par l'USB** : sinon le poste module avec son propre micro, c'est-à-dire le bruit de la pièce ;
- **aucune ligne RTS/DTR** pour le PTT ni la CW : sinon le poste peut passer en émission au démarrage du PC ;
- **VOX éteint** : un VOX en marche fait émettre le poste sur un bruit de la pièce, sans aucune commande. La station le vérifie à chaque connexion d'un opérateur et le **coupe** s'il est en marche (message dans le journal de la page, code ORT-5034). Sur certains postes il reste en marche dans un mode alors qu'il est coupé dans un autre (vu sur l'IC-7300MK2 : coupé en mode données, encore en marche en phonie) ;
- **coupleur d'antenne intégré** (si l'antenne passe par lui) : l'accord doit partir tout seul à la prise d'émission
  sur une nouvelle fréquence. Sur l'IC-7300MK2 : MENU > SET > Function > Tuner, **[TUNER] Switch = Auto** (état du
  coupleur mémorisé par bande) et **PTT Start = ON**. Réponds « oui » à la question du coupleur de l'assistant : la
  station vérifiera ces réglages à chaque connexion et te préviendra s'ils sont faux (elle ne les change jamais). Hors
  des bandes radioamateur, le poste ne garantit pas l'accord au PTT ;
- **minuterie d'émission du poste** (TX TIME OUT TIMER) : une seconde sécurité, indépendante de la station.

> **Sécurité.** Une sécurité en plus ne coûte rien : règle aussi une **puissance maximale** raisonnable dans le
> poste (HF MAX POWER). La station ne peut pas la dépasser, quoi qu'il arrive.

## 1.4 Son du PC

La carte son du poste ne doit **jamais** être le son par défaut du PC, sinon les sons du bureau partent vers le
poste (et le bureau occupe la carte) :

- Debian : *Paramètres > Son* : en sortie les haut-parleurs du PC, en entrée son micro.
- Windows : *Paramètres > Système > Son* : idem ; dans « Plus de paramètres de son », la carte du poste n'est ni
  « Périphérique par défaut » ni « Périphérique de communication par défaut » ; schéma de sons « Aucun son ». Le
  détail est dans la notice Windows jointe au paquet.
