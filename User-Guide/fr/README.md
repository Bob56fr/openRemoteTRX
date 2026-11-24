# Mettre en service une station openRemoteTRX : guide de l'opérateur

Ce guide t'accompagne, dans l'ordre, du déballage à la première liaison depuis l'extérieur. Il vaut pour tout poste
connu de Hamlib ; ce qui est propre à un modèle (pilote USB, menus, ports) est dans sa **fiche de poste** :

- [Icom IC-7300MK2](postes/ic7300mk2.md) : **validé** sur un vrai poste ;
- [Yaesu FTDX10](postes/ftdx10.md) : préparé, **validation en cours**.

Pour un autre poste : son manuel, le tableau « Selon ta marque » du [démarrage rapide](demarrage-rapide.md), et les
essais de la partie 3, qui servent de validation : fais-les tous, sur charge fictive, et rapporte le résultat
(partie 8, « Demander de l'aide »). État de chaque poste essayé : https://bob56fr.github.io/openRemoteTRX/postes/

> **Pressé ?** Le [démarrage rapide](demarrage-rapide.md) mène du poste branché à la page web en un quart d'heure,
> TOT du poste compris. Reviens aux parties ci-dessous au premier problème.

## Le parcours

| Partie | Ce que tu fais | Durée indicative |
|---|---|---|
| [Démarrage rapide](demarrage-rapide.md) | l'essentiel pour les impatients, essais de sécurité compris | 15 min |
| [0. Avant de commencer](00-avant-de-commencer.md) | matériel, réglementation, choix Debian, Raspberry Pi ou Windows | 15 min de lecture |
| [1. Préparer le poste](01-preparer-le-poste.md) | câblage, pilote USB, menus du poste | 30 min |
| [2. Installer la station](02-installer-la-station.md) | logiciel sur le PC ou le Raspberry Pi | 20 min (Pi : 1 h avec la carte SD) |
| [3. Intégrer le TRX et l'essayer](03-integrer-et-essayer-le-trx.md) | assistant, essais en réception puis en émission, essais de sécurité | 1 h 30 |
| [4. Utiliser sur le réseau local](04-utilisation-sur-le-lan.md) | page web, téléphone, application Android | 30 min |
| [5. Utiliser à distance](05-utilisation-a-distance.md) | VPN ou port exposé, essai en 4G | 1 h |
| [6. Station sans surveillance](06-station-sans-surveillance.md) | alertes, redémarrage après coupure, protections | 30 min |
| [7. Exploitation au quotidien](07-exploitation-au-quotidien.md) | démarrer, surveiller, mettre à jour, sauvegarder | à lire |
| [8. Dépannage](08-depannage.md) | codes d'erreur, problèmes fréquents, demander de l'aide | au besoin |
| [9. Fonctions facultatives](09-fonctions-facultatives.md) | visiteurs, Cluster DX, FreeDV, SELCALL, TOS… | au choix |
| [Glossaire](glossaire.md) | les mots du projet : qui est quoi | au besoin |
| [10. Récapitulatif à cocher](10-recapitulatif.md) | savoir où tu en es | |

Fiches de poste : [Icom IC-7300MK2](postes/ic7300mk2.md), [Yaesu FTDX10](postes/ftdx10.md). Schéma des briques de
la station : partie 0, « Comment c'est organisé ».

## Comment lire ce guide

- Les **menus d'openRemoteTRX Console** sont notés par leur numéro : « menu 2.1 » = thème 2 (Poste et matériel), menu 1. Sous Windows, le
  raccourci menu Démarrer > **openRemoteTRX** ouvre la même console (partie 2). La console s'ouvre en **écran plein** :
  thèmes à gauche avec leur pictogramme (flèches et Entrée), aide du menu choisi à droite ; on peut aussi taper le
  numéro dans la console texte (`trx-console --texte`).
- Une case **« Sécurité »** signale un point qui touche à l'émission : ne la saute pas.
- Ce qui change selon le système est rangé dans des **onglets** Debian / Raspberry Pi / Windows : choisis le tien
  une fois, il est retenu pour toute la page. Sur GitHub, les onglets se lisent l'un sous l'autre.
- Ce guide existe aussi en page web, avec un récapitulatif que l'on coche en ligne, et en **PDF** à imprimer
  (lien « Télécharger en PDF » en haut de la page) : https://bob56fr.github.io/openRemoteTRX/guide/
