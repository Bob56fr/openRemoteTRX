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
| Essai du poste refusé : « ORT-9313 … la station est en marche » | l'essai a besoin du poste pour lui seul | arrêter la station (menu 1.2, ou raccourci Windows 4), refaire l'essai, redémarrer la station |
| Un outil s'arrête avec « ORT-9312 … erreur inattendue » | défaut du logiciel dans un cas non prévu (nouveau poste, carte son…) | le message indique le fichier de détail (dossier `plantages`) : le joindre à la demande d'aide (partie 8.3) |

## 8.3 Demander de l'aide

1. Menu **2.3** : crée un rapport de dépannage (zip sur le Bureau) **sans aucun mot de passe**. Sous Windows :
   le dossier des journaux (raccourci 7) et le résultat du diagnostic. Les traces des outils arrêtés sur une erreur
   (code ORT-9312) sont dans le dossier `plantages` du dossier d'état de la station, et le rapport les joint.
2. Depuis la page web : section « Signaler un problème » (texte relu avant l'envoi).
3. Ouvre un ticket sur https://github.com/Bob56fr/openRemoteTRX/issues avec le formulaire **en français**
   (« Signaler un bug »), décris ce que tu faisais, ce que tu attendais, ce qui s'est passé, et joins le rapport.
4. **Être aidé à distance** (monitoring entre stations, menu **5.5**, à activer d'abord : partie 9) : la personne qui
   t'aide crée un code de 10 caractères et te le dicte ; tape-le au choix 4, puis comparez de vive voix les **6
   chiffres** affichés des deux côtés. Différents : réponds « non », la liaison est effacée. Choisis ensuite ce que tu
   envoies (« Diagnostic » conseillé ; fréquence et mode seulement si tu veux). Elle voit alors l'état de ta station
   et ses codes d'erreur, **masqués** (ni mot de passe, ni adresse, ni numéro de série), et peut te **demander** le mode
   assistance (nouvelles toutes les 30 secondes, pour une durée limitée) : c'est toi qui acceptes (choix 7). Elle ne
   peut **rien commander** sur ta station. Tu arrêtes tout quand tu veux (choix 9). Elle peut aussi te
   demander ton **rapport de dépannage** (celui du point 1, entièrement masqué) ; tu peux aussi l'envoyer
   toi-même (choix 10). De son côté, elle reçoit une alerte sur son téléphone si ta station ne donne plus
   de nouvelles. **Loin de ta station**, tout se fait aussi dans la page web, rubrique « Monitoring » : bouton
   « Être aidé : j'ai un code », comparaison des 6 chiffres, choix de ce qui part, réponse aux demandes, fin.
