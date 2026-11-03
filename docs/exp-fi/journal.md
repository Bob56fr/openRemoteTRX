# Branche d'essai `exp/st-fi` : vrai binaural par la FI 12 kHz

Branche ABANDONNABLE (règles : CLAUDE.md, « Branches d'essai »). Ni numéro d'étape ni version : journal ici seulement.
Point de départ : `main` à l'étape 116 (station 0.96.0, ST V1 de la page).

## But

Donner au module ST de vraies voies I/Q (les deux bandes latérales autour du battement nul, à la manière des
récepteurs binauraux de KK7B) au lieu d'un mono transformé : une station au-dessus et une au-dessous du battement nul
se placent de part et d'autre de la tête ; c'est là qu'un gain réel en CW et en pile-up est possible.

## Mesures à faire AVANT tout code de production (dans cet ordre)

1. IC-7300MK2, menu « USB AF/IF Output » sur IF : largeur de la FI 12 kHz relevée par la carte son ; les filtres
   (FIL, largeur, PBT), NR, NB, notch du poste agissent-ils sur la FI ? (si non : la moitié des commandes de
   l'interface n'agit plus sur l'écoute => à refaire en logiciel ou abandon). AF et FI ensemble : impossible ?
2. Charge d'un démodulateur Python + numpy (BLU, CW, AM, FM, AGC, squelch) sur minix-bzh et sur un Pi 4.
3. Opus stéréo (aiortc -> Chrome, -> stream-webrtc) : le déphasage I/Q tient-il, à quel débit minimal ?
4. Android : sortie stéréo réelle (même question que la V1 de l'application).

## Conception provisoire

- Station : démodulation OBLIGATOIRE (l'audio mono sert à tout le reste : enregistrement, SELCALL, waterfall audio,
  visiteurs, Android Auto) + I/Q en bande de base, calculés une fois pour tous les clients.
- Bascule AF / FI : capacité facultative du descripteur (modèle par modèle, Hamlib ne sait pas la faire) ; CI-V par le
  port B ou réglage manuel ; retour en AF garanti à l'arrêt.
- Flux : mono par défaut ; stéréo I/Q seulement pour un client qui active ST et que la station l'annonce
  (`hello.features`). Visiteurs et Android Auto en mono.
- Client : le module ST de la V1 accepte M/S ; l'I/Q y entre comme un moteur de plus.

## Journal

- 2026-11-03 : branche créée depuis `main` (étape 116).
