# Yaesu FTDX10, FTDX101D, FTDX101MP

État : **NON VALIDÉ sur un vrai poste** (station 0.65.0). Préparé d'après le manuel CAT du FTDX10 et les capacités
Hamlib 4.7.2 / 5.0. Le premier essai réel se fait sur charge fictive, avec `trx-qualif`, avant toute émission sur
l'air.

## Ce que dit Hamlib

| | FTDX10 | FTDX101D | FTDX101MP |
|---|---|---|---|
| Numéro Hamlib | 1042 | 1040 | 1044 |
| État Hamlib | Stable | Stable | Stable |

- Liaison série 4800 à 38400 bauds, 8N2, contrôle de flux matériel RTS/CTS.
- PTT par CAT (commande `TX`).
- Mesures lisibles : ALC, SWR, puissance, COMP, tension, courant. La température n'est pas lisible : le seuil de
  température de la station est sans effet.
- RIT et XIT jusqu'à ±9,999 kHz ; split lisible.
- **VFO actif lisible** (`VFO: VFOA`, `VFOB`, `MEM`) : voyant « VFO A » ou « VFO B » dans la page et l'application.
  L'IC-7300MK2 ne le donne pas.
- FTDX10 : préampli 10 et 20 dB (AMP1, AMP2) ; atténuateur 6, 12 et 18 dB.

## Ports USB

Un seul câble USB donne deux ports série (puce Silicon Labs CP2105) et une carte son (« USB Audio CODEC ») :

| Port | Nom Windows | Nom stable Linux | Usage |
|---|---|---|---|
| Enhanced | « Silicon Labs Dual CP2105 USB to UART Bridge: Enhanced COM Port » | `…CP2105…-if00-port0` | **CAT** |
| Standard | « … Standard COM Port » | `…CP2105…-if01-port0` | PTT/CW par RTS/DTR |

`trx-setup` propose d'office le port Enhanced pour le CAT. Il refuse le port Standard, sauf confirmation explicite.

## Menus du poste (proposés par `trx-setup`)

- **CAT RATE** = 38400 bps, la même valeur que dans `station.toml`.
- **CAT TIME OUT** = 1000 msec.
- **CAT RTS** = ON : Hamlib attend le contrôle de flux RTS/CTS.
- **RPTT SELECT** : ni RTS ni DTR si le PTT passe par CAT. Une ligne RTS ou DTR mal placée peut mettre le poste en
  émission. Un passage en émission inattendu a été signalé pendant des essais CAT d'un FTDX10 sous Hamlib.
- **SSB, AM, FM et DATA MOD SOURCE** = REAR, et **REAR SELECT** = USB : l'audio du client part par l'USB.
  - Sans ces réglages, le poste modulerait avec son propre micro, c'est-à-dire le son de la pièce.
  - `trx-setup` limite alors l'émission aux modes données (PKTUSB, PKTLSB…), comme pour un Icom.
- **USB MOD GAIN / RPORT GAIN** : à régler avec l'ALC. Le réglage automatique SELCALL et le voyant OVERLOAD ALC (seuil
  à 50 %) aident, mais l'échelle de l'ALC Yaesu n'a pas été relevée : seuil à vérifier.
- **TX TIME OUT TIMER** = 3 min : seconde sécurité, indépendante de la station (TOT 90 s par défaut).

## Ce qui ne marche pas avec ces postes

- **Spectre HF** : la commande CAT `SS` ne fait que régler l'affichage du poste. Aucune donnée du scope ne sort par
  CAT, alors que les Icom l'envoient par le second port CI-V. Seul le spectre audio est disponible.
- **Préréglages FIL1/2/3, NB largeur et profondeur** : propres au port CI-V des Icom.
- **FTDX101D/MP** : seul le récepteur principal (MAIN) est piloté. Le split par le SUB est à essayer.

## Essai réel à faire

1. Lancer `trx-setup`, choisir 1042 ou 1040, puis le port Enhanced, et régler les menus ci-dessus.
2. Faire le test de liaison (lecture seule), puis lancer `trx-qualif`.
3. Sur charge fictive :
   - PTT toggle et STOP ;
   - TOT ;
   - client perdu ;
   - superviseur (`T 0`) ;
   - opérateur sur place (émission au micro du poste) ;
   - ALC pendant le réglage automatique SELCALL ;
   - voyant VFO A et VFO B (bouton A/B du poste) ;
   - split.
4. Rapporter les formats relevés dans `docs/historique.md`. Si l'ALC monte trop vite ou pas du tout, ajuster
   `ALC_OVERLOAD`.

Sources :
- [Manuel CAT du FTDX10](https://rigpix.com/yaesu/ftdx10_cat_manual.pdf)
- [FTDX10 et DigiPi](https://groups.google.com/g/digipi/c/MWWNC-LkJZM)
- [SCU-LAN10, kit distant officiel Yaesu](https://www.wimo.com/en/scu-lan10)
