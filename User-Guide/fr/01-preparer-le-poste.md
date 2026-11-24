# 1. Préparer le poste

Station **éteinte**, rien de branché : c'est le moment de régler le poste. Le détail des menus de ton poste est
dans sa fiche ([Icom IC-7300MK2](postes/ic7300mk2.md), [Yaesu FTDX10](postes/ftdx10.md)) ; pour un autre poste,
son manuel et le tableau « Selon ta marque » du [démarrage rapide](demarrage-rapide.md). Cette partie dit dans quel
ordre faire les choses.

## 1.1 Installer le pilote USB (Windows seulement)

Sous Windows, le pilote USB du poste (celui de son fabricant : « Icom USB Driver », Silicon Labs CP210x chez
Yaesu…) s'installe **avant** de brancher le câble USB ; sinon Windows peut installer un mauvais pilote. Le nom, la
version minimale et la marche à suivre sont dans la fiche du poste, « Pilote USB », sinon sur le site du fabricant.

Sous Debian et sur un Raspberry Pi, rien à installer : le noyau reconnaît le poste tout seul.

## 1.2 Brancher

1. Antenne débranchée, **charge fictive** sur la prise d'antenne utilisée.
2. Câble USB entre le poste et le PC.
3. Allume le poste (appui long sur ON/OFF).

Le PC voit alors un ou deux **ports série** et une **carte son**. La fiche du poste dit lequel sert à la commande
(IC-7300MK2 : le premier, le second sert au spectre HF ; FTDX10 : l'« Enhanced COM Port », le « Standard » ne sert
pas).

<!-- onglets -->
#### Debian

Rien à noter : l'assistant reconnaît lui-même le bon port. Pour le voir : `ls -l /dev/serial/by-id/` dans un
terminal (un nom stable par port, qui ne change pas d'une prise USB à l'autre).

#### Raspberry Pi

Comme sous Debian. Branche le câble du poste **directement** sur un port USB du Pi (les ports bleus USB 3 vont aussi) ;
un hub, seulement s'il a sa propre alimentation : le Pi ne fournit pas assez de courant à plusieurs appareils.

#### Windows

Gestionnaire de périphériques > Ports (COM et LPT) : note le numéro COM du port de commande.
<!-- /onglets -->

## 1.3 Régler les menus du poste

Règle les menus listés dans la fiche de ton poste, section « Menus à régler » (sinon, son manuel). Ils sont
indispensables :

- **débit du CAT** identique à celui de la station (choisi dans l'assistant) ;
- **voix par l'USB** : sinon le poste module avec son propre micro, c'est-à-dire le bruit de la pièce. Sur un Icom
  (IC-7300MK2) : MENU > SET > Connectors > MOD Input > **DATA MOD = USB** (la station n'émet qu'en mode données) ;
  le poste n'accepte la prise USB que dans DATA MOD **ou** DATA OFF MOD. Avec le second port réglé, la station le
  vérifie à chaque connexion et te prévient s'il n'est pas sur USB ;
- **aucune ligne RTS/DTR** pour le PTT ni la CW : sinon le poste peut passer en émission au démarrage du PC ;
- **VOX éteint** : un VOX en marche fait émettre le poste sur un bruit de la pièce, sans aucune commande. La station le vérifie à chaque connexion d'un opérateur et le **coupe** s'il est en marche (message dans le journal de la page, code ORT-5034). Sur certains postes il reste en marche dans un mode alors qu'il est coupé dans un autre (vu sur l'IC-7300MK2 : coupé en mode données, encore en marche en phonie) ;
- **coupleur d'antenne intégré** (si l'antenne passe par lui) : l'accord doit partir tout seul à la prise d'émission
  sur une nouvelle fréquence. Sur l'IC-7300MK2 : MENU > SET > Function > Tuner, **[TUNER] Switch = Auto** (état du
  coupleur mémorisé par bande) et **PTT Start = ON**. Réponds « oui » à la question du coupleur de l'assistant : la
  station vérifiera ces réglages à chaque connexion et te préviendra s'ils sont faux (elle ne les change jamais). Hors
  des bandes radioamateur, le poste ne garantit pas l'accord au PTT. Pendant une émission, si le TOS dépasse 2
  plus d'une seconde, la page affiche un bandeau rouge et bipe (elle ne coupe pas) ;
- **minuterie d'émission du poste** (TX TIME OUT TIMER) : une seconde sécurité, indépendante de la station.
  Règle-la (3 min conseillé) : si la station, le réseau ou le PC tombent pendant une émission, c'est elle qui coupe.
  Pour un poste dont la lecture est qualifiée (IC-7300MK2), la station la lit à chaque connexion et te prévient si
  elle est sur OFF ; pour les autres, elle ne peut pas la vérifier.

> **Sécurité.** Une sécurité en plus ne coûte rien : règle aussi une **puissance maximale** raisonnable dans le
> poste (HF MAX POWER). La station ne peut pas la dépasser, quoi qu'il arrive.

## 1.4 Son du PC

La carte son du poste ne doit **jamais** être le son par défaut du PC, sinon les sons du bureau partent vers le
poste (et le bureau occupe la carte) :

<!-- onglets -->
#### Debian

*Paramètres > Son* : en sortie les haut-parleurs du PC, en entrée son micro.

#### Raspberry Pi

Sans bureau (Raspberry Pi OS Lite) : rien à faire, aucun programme ne prend la carte du poste. Avec bureau : comme
sous Debian, dans les réglages du son de la barre du haut. La carte son du Pi lui-même (« Headphones », « HDMI ») ne
sert pas à la station.

#### Windows

*Paramètres > Système > Son* : en sortie les haut-parleurs du PC, en entrée son micro ; dans « Plus de paramètres de
son », la carte du poste n'est ni « Périphérique par défaut » ni « Périphérique de communication par défaut » ;
schéma de sons « Aucun son ». Le détail est dans la notice Windows jointe au paquet.
<!-- /onglets -->
