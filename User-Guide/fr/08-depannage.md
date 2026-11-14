# 8. Dépannage

## 8.1 Le premier réflexe

1. **Diagnostic** (menu 2.1) : il dit ce qui ne va pas et quoi faire.
2. **Journal** (menu 1.4) : les messages commencent par un code « ORT-NNNN ».
3. Chaque code a sa page d'explication (cause, que faire) : https://bob56fr.github.io/openRemoteTRX/erreurs/
   (champ de recherche : tape le code).

## 8.2 Problèmes fréquents

| Symptôme | Cause probable | À faire |
|---|---|---|
| Le diagnostic ne trouve pas le poste | poste éteint, port **Standard** choisi, CAT RATE différent de 38400, pilote absent (Windows) | allumer ; reprendre l'assistant avec le port **Enhanced** ; régler CAT RATE (fiche du poste) |
| Pas de son reçu | carte son du poste prise par le bureau ; micro interdit aux applications (Windows) ; OUT LEVEL trop bas | partie 1.4 ; partie 2.2 ; fiche du poste |
| L'émission part mais rien n'est modulé | MOD SOURCE = MIC ou REAR SELECT = DATA dans ce mode | fiche du poste, « Voix par l'USB » |
| Seuls les modes DATA peuvent émettre | l'assistant a noté que la voix ne passe pas par l'USB | régler MOD SOURCE, puis relancer l'assistant et répondre « oui » |
| ALC au maximum, son saturé | RPORT GAIN trop haut | partie 3.4 |
| Le poste passe en émission au démarrage du PC | RPTT SELECT sur RTS ou DTR, ou PC KEYING actif | **débrancher l'USB**, régler RPTT SELECT = DAKY et PC KEYING = OFF |
| « Micro indisponible » dans la page | page ouverte en HTTP | ouvrir l'adresse en **https://** |
| Page injoignable depuis le téléphone | station arrêtée ; adresse changée ; réseau en profil Public (Windows) | menu 1.1 ; partie 4.1 ; partie 2.2 |
| Connecté mais pas de son à distance | l'UDP ne passe pas (port ouvert sur la box) | VPN (partie 5) |
| Coupures toutes les 15 à 30 s | deux appareils sur le même profil VPN | un profil par appareil |
| Émission coupée toute seule | durée maximale atteinte, téléphone qui ne répond plus, fréquence hors bandes, opérateur sur place | normal : la raison est affichée dans la page et le journal |
| Plus rien ne répond, alerte « mode sûr » | pannes répétées | partie 6.2 |

## 8.3 Demander de l'aide

1. Menu **2.3** : crée un rapport de dépannage (zip sur le Bureau) **sans aucun mot de passe**. Sous Windows :
   le dossier des journaux (raccourci 7) et le résultat du diagnostic.
2. Depuis la page web : section « Signaler un problème » (texte relu avant l'envoi).
3. Ouvre un ticket sur https://github.com/Bob56fr/openRemoteTRX/issues avec le formulaire **en français**
   (« Signaler un bug »), décris ce que tu faisais, ce que tu attendais, ce qui s'est passé, et joins le rapport.
