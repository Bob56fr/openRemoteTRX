# Mettre en service une station openRemoteTRX : guide de l'opérateur

Ce guide t'accompagne, dans l'ordre, du déballage à la première liaison depuis l'extérieur. Il est écrit pour le
**Yaesu FTDX10** ; les parties communes valent pour tous les postes, ce qui est propre au FTDX10 est dans
[la fiche du poste](postes/ftdx10.md).

> **FTDX10 : préparé, pas encore validé sur un vrai poste.** Les réglages viennent du manuel CAT de Yaesu et des
> capacités de Hamlib. Les essais de la partie 3 servent de validation : fais-les tous, sur charge fictive, et
> rapporte le résultat (partie 8, « Demander de l'aide »).

## Le parcours

| Partie | Ce que tu fais | Durée indicative |
|---|---|---|
| [0. Avant de commencer](00-avant-de-commencer.md) | matériel, réglementation, choix Debian ou Windows | 15 min de lecture |
| [1. Préparer le poste](01-preparer-le-poste.md) | câblage, pilote USB, menus du FTDX10 | 30 min |
| [2. Installer la station](02-installer-la-station.md) | logiciel sur le PC | 20 min |
| [3. Intégrer le TRX et l'essayer](03-integrer-et-essayer-le-trx.md) | assistant, essais en réception puis en émission, essais de sécurité | 1 h 30 |
| [4. Utiliser sur le réseau local](04-utilisation-sur-le-lan.md) | page web, téléphone, application Android | 30 min |
| [5. Utiliser à distance](05-utilisation-a-distance.md) | VPN ou port exposé, essai en 4G | 1 h |
| [6. Station sans surveillance](06-station-sans-surveillance.md) | alertes, redémarrage après coupure, protections | 30 min |
| [7. Exploitation au quotidien](07-exploitation-au-quotidien.md) | démarrer, surveiller, mettre à jour, sauvegarder | à lire |
| [8. Dépannage](08-depannage.md) | codes d'erreur, problèmes fréquents, demander de l'aide | au besoin |
| [9. Fonctions facultatives](09-fonctions-facultatives.md) | visiteurs, Cluster DX, FreeDV, SELCALL, TOS… | au choix |
| [10. Récapitulatif à cocher](10-recapitulatif.md) | savoir où tu en es | |

Fiche du poste : [Yaesu FTDX10](postes/ftdx10.md).

## Comment lire ce guide

- Les **menus de TRX Console** sont notés par leur numéro : « menu 3.1 » = thème 3, menu 1. Sous Windows, les mêmes
  actions sont dans le menu Démarrer > **TRX distant** (la partie 2 donne la correspondance).
- Une case **« Sécurité »** signale un point qui touche à l'émission : ne la saute pas.
- Ce guide existe aussi en page web, avec un récapitulatif que l'on coche en ligne :
  https://bob56fr.github.io/openRemoteTRX/guide/
