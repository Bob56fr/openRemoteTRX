# Banc du décodeur CW (réglage 20 mots/min, 40 tirages par ligne)

Message : `CQ CQ DE F4XYZ/P F4XYZ/P K F4XYZ DE DL1ABC GM UR RST 579 5NN QTH LORIENT NAME BOB HW? 73 TU =`

| Scénario | Erreurs / caractère | Mots exacts | Exemple (pire des 10 premiers tirages) |
|---|---:|---:|---|
| Pioche, rythme parfait | 0,0 % | 100 % | `CQ CQ DE F4XYZ/P F4XYZ/P K F4XYZ DE DL1ABC GM UR RST 579 5NN QTH LORIENT NAME BOB HW? 73 TU =` |
| Pioche, irrégularité 10 % | 0,1 % | 100 % | `CQ CQ DE F4XYZ/P F4XYZ/P K F4XYZ DE DL1ABC GM UR RST 579 5NN QTH LORIENT NAME BOB HW? 73 TU =` |
| Pioche, irrégularité 20 % | 9,5 % | 77 % | `? CQ DE F5XCZ/P F4X?Z? K F4XYB DE DL?BC GM UR RST 579 5NN Q6 LW?ENE NIME BOB HW? 73 TU =` |
| Pioche, irrégularité 30 % | 27,0 % | 42 % | `CQ CQ B F4XYZ6F ??Z/P D ?XCZ DE SL1I? GM SR ?T 5?9 5NN?H LGRSK NAME BDB HW? 6 ? TU =` |
| Pioche, traits lourds (4 points), 15 % | 1,8 % | 97 % | `? CQ DE F4XYZ/P F4XYZ? K F4XYZ DE DL1ABC GM UR RST 579 5NN QTH LO?ENT NAME BOB HW? 73 TU =` |
| Pioche, traits courts (2,2 points), 15 % | 27,1 % | 36 % | `CQ CV DE F4XXZ6P H5XYL/P K H4BBZ SE DH?AHF GA UR RST 5?? 5NI ZTH HGRIENE IIIE BUH HW? ?? TS 6` |
| Pioche, lettres serrées (2,2 points), 15 % | 26,6 % | 60 % | `CQ ? DE ?X?P F4?/P K ?Z DE DL1?C GM UR RV 57? 5C ? ??N? BOB HW? 73 TU =` |
| Pioche, espaces larges (5 / 12 points), 15 % | 29,3 % | 39 % | `C Q C Q DE F 4 XY Z /P F 4 X YZ /P K F 4XY Z D E D L1 A B C G M UR RS T 5 7? 5 NN QT H L O RI E N T NAM E B OB H W? 7 3 T U =` |
| Pioche à 16 mots/min (réglage 20), 15 % | 1,2 % | 97 % | `CQ CQ DE F4XYZ/P F4XYZ/P K F4XYZ DE DL1ABC G M UR RST 579 5 NN QTH LORIENT NAME BOB HW? 73 TU =` |
| Pioche à 26 mots/min (réglage 20), 15 % | 37,4 % | 25 % | `CQ ? DEH4V?PH5H?/P K F?Z SE DL2?BGMUS RV 56/5C? ??EKNAME BKBHW? 7? TS =` |
| Pioche qui accélère 18 → 25 mots/min, 15 % | 8,4 % | 76 % | `? CQ DE F4XYZ/P F4X?Z? K F4XYB DE DL1ABC GM UR RST 579 5NN Q6 LW?ENE NIMEBOB HW? 74 TU=` |
| Palettes B, lâcher ±0,3 point | 1,5 % | 97 % | `CQ CQ B F4XYZ/P F4XYZ/P K F4XYZ DE DL1ABC GM UR RST 579 5NN QTH LORSNT NAME BOB HW? 73 TU =` |
| Palettes B, lâcher ±0,5 point | 4,3 % | 89 % | `CQ /Q DE F4XYZ/? F4XYZ/? K ?XYG DE D?ABC GM UR RST 579 5NN QTH LORIENT NAME BOB HW? 73 TU =` |
| Palettes B, lâcher ±0,8 point | 15,1 % | 60 % | `?Q /Q DE F4XYZ/L ?4XYZ/? K ?X?G DI Z?AD? ZM UR RST 579 5NN QTH LOREINT NAME BOB H?? Z? TA =` |
| Palettes A, lâcher ±0,5 point | 4,3 % | 89 % | `CQ /Q DE F4XYZ/? F4XYZ/? K ?XYG DE D?ABC GM UR RST 579 5NN QTH LORIENT NAME BOB HW? 73 TU =` |
| Palettes B, lettres serrées (2,2 points) | 27,5 % | 60 % | `CQ ? B ?X?P F4XYZ/P K F4X? DE ?? ? UR RST 5? 5NN QTH L?EK NJE ?B HW? 73 X =` |
| Palettes B, espaces larges (5 / 12 points) | 26,2 % | 42 % | `C Q C Q DE F 4 X YZ/ P F 4XYZ / P K F4XY Z DE DL 1A B C G M UR R S T 5 7 9 5 N N Q TH L ORIENT N A M E B O B HW ? 73 T U =` |
| Palettes B, espaces très irréguliers (40 %) | 25,4 % | 52 % | `CQ CQ B F4?Z/P F4XYZ/PK ?XYZB D? GM ? RST 5? 5NN ?H L?I EK NAM E?BHW? 73 X =` |

## Retex (2026-11-28)

- Seuils FIXES tirés de la vitesse réglée (trait au-delà de 2 points, lettre close après 2 points de silence, mot après
  5) : aucune adaptation. Un opérateur plus rapide que le réglage s'effondre (26 au lieu de 20 : 37 % d'erreurs), plus
  lent passe (16 : 1 %, quelques espaces en trop).
- Pioche : tolérance ~10-15 % d'irrégularité ; 20 % = 10 % d'erreurs ; traits courts (rapport 2,2) illisibles, traits
  lourds bien lus.
- Les ESPACES sont le point faible des deux modes : lettres serrées = lettres fusionnées en « ? », espaces larges
  (débutant hésitant, Farnsworth) = espaces parasites dans les mots. Le manipulateur iambique calibre les éléments,
  pas les espaces.
- Palettes : le décodeur lit EXACTEMENT ce qui part (sortie du manipulateur) ; les erreurs du lâcher (±0,5 point :
  4 %) sont de vraies erreurs de manipulation, ce qu'on attend d'une aide à la manipulation.
- Caractères absents : AR (+), SK, KN, BT n'est que « = », virgule, tiret, @ ; « ? » sert à la fois au point
  d'interrogation et au code inconnu.
- Non couvert par le banc : les appuis simultanés (squeeze) ; iambique A et B donnent ici les mêmes résultats.
