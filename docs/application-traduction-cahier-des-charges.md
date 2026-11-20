# Application Android et page web en quatre langues (FR, EN, DE, ES) — cahier des charges v2

Demande de l'utilisateur du 2026-11-20 : proposer l'application Android en français, anglais, allemand et espagnol,
comme TRX Console (étapes 169 à 241). v2 du même jour : décisions de l'utilisateur (§ 8) ; la PAGE WEB de la
station et le CATALOGUE D'ERREURS entrent dans le projet. Ce document PRÉPARE le travail : aucun code n'est écrit.

## 1. État des lieux (relevé du 2026-11-20, station 0.233.0, application 0.72.0)

### 1.1 Application Android

- Aucun texte dans des ressources Android : `res/values/` ne contient que `ic_launcher_colors.xml`. Tous les textes
  sont des chaînes françaises écrites en dur dans le code Kotlin.
- Volume (chaînes de texte humain hors tests) : environ **1 470 chaînes, 1 390 différentes, 8 800 mots**, dans
  **77 fichiers** : `:logic` 771, `:app` 593, `:core` 105, `:protocol` 5. Les plus chargés : `logic/Texts.kt`
  (refus et coupures, ~100), `app/VoiceScreen.kt` (54), `logic/RigSession.kt` (53), `logic/Help.kt` (aides par
  appui long, 30), `app/NetViews.kt`, `logic/NetUi.kt`, `app/SelcallPanel.kt`, `app/ClusterAndBeeps.kt`,
  `app/MonitoringScreen.kt`, `logic/Diffusion.kt`, `core/RigService.kt`.
- `:logic` est un module JVM pur (testé sans Android) : les `strings.xml` d'Android n'y sont PAS accessibles, or
  c'est là que vit la moitié des textes (refus, messages d'état, aides, Android Auto).
- Commandes vocales d'Android Auto (`logic/Voice.kt`) : mots français (« fréquence », « mémoire », « bande »,
  « qsy »), anglais partiels (« meters », « megahertz »).
- Formats : virgule décimale écrite en dur à certains endroits (`RigDialogs.kt`), `SimpleDateFormat(…, Locale.FRANCE)`
  (`NetViews.kt`), ailleurs `Locale.ROOT`.
- Textes partagés hors de l'application : invitation des amis, page des auditeurs de la diffusion, rapport du
  monitoring, image de la mesure de TOS, rapport de problème (`Intent.ACTION_SEND` dans 6 écrans).
- Fiche Google Play : en français seulement (`docs/android-play-store.md`, `docs/play-store/`).

### 1.2 Page web de la station (`trxstation/gateway/api/static/`)

- Français seulement, textes en dur. Volume : environ **1 530 chaînes différentes, 9 000 mots, 18 fichiers** :
  `client.js` (~480), `ui.js` (~480), `index.html` (~400), puis `sdr.js`, `diffusion.js`, `voice.js`, `friends.js`,
  `monitoring.js`, `swr.js`, `hfscope.js`, `scrambler.js`, `layout.js`…
- Beaucoup de textes sont COMMUNS avec l'application : refus (`REASONS` ↔ `Texts.REFUSALS`), coupures
  (`CUT_REASONS` ↔ `Texts.CUTS`), aides, états. `TextsTest` compare déjà les codes des deux côtés.
- Liste fermée des fichiers servis (`WEB_FILES` de `gateway/api/server.py`) et CSP stricte : tout nouveau fichier
  (catalogue de textes) doit y être ajouté.

### 1.3 Station

- Textes envoyés aux clients, en français : champ `detail` des refus, `breizh_event.detail`, `rig_notice.detail`,
  `freedv_event` (`detail`), refus 403 / 503 de `/offer` (`message`), refus du SDR, de la présence, du monitoring…
  Une dizaine de fichiers de `gateway/` produisent un `detail`. Le code stable (`reason`, `event`, `ort`) est
  presque toujours présent à côté.
- Infrastructure déjà en place : TRX Console et ses outils (`trxstation/i18n/<domaine>.<langue>.json`, mêmes clés
  imposées par les tests, langue choisie par compte) ; alertes ntfy (`[supervisor] notify_lang`).
- Catalogue d'erreurs : **457 codes ORT** (`catalog.yaml`) et **5 codes AND** (`AND-catalog.yaml`) en français et
  anglais seulement ; pages publiques https://bob56fr.github.io/openRemoteTRX/erreurs/ (FR et EN).

## 2. Objectifs

1. Toute l'application (téléphone, tablette, mode conduite, Android Auto, notifications), toute la page web et
   tous les textes que la station envoie aux clients, dans les 4 langues.
2. Catalogue d'erreurs ORT / AND et ses pages publiques en allemand et en espagnol.
3. Fiche Google Play dans les 4 langues.
4. Aucune régression de sécurité : les textes d'émission (« ÉMISSION EN COURS », STOP, refus, coupures, TOT,
   avertissements réglementaires) ont le MÊME sens dans chaque langue, relus un par un.
5. Ajouter une langue plus tard = ajouter des fichiers, comme pour la console.
6. Aucune perte pour un utilisateur français : le français reste la langue de référence et le repli.

## 3. Choix techniques

### 3.1 Catalogues de textes en JSON, un tronc commun

Trois familles de fichiers, même forme que la console (`trxstation/i18n/`), mêmes clés dans chaque langue :

| Fichier | Contenu | Utilisé par |
|---|---|---|
| `trxstation/i18n/client.<langue>.json` | TRONC COMMUN : refus, coupures, motifs de perte, `detail` de la station, états, aides des fonctions du poste | station (pour `detail`), page, application |
| `trxstation/i18n/page.<langue>.json` | textes propres à la page | page |
| `android/logic/src/main/resources/i18n/app.<langue>.json` | textes propres à l'application | application |

- Le tronc commun est traduit UNE fois et garde la page et l'application d'accord (ce que fait `TextsTest`
  aujourd'hui pour les codes). L'application en embarque une COPIE à la compilation (tâche Gradle, `inputs.dir`
  déclaré : piège Gradle), pour fonctionner avec une station plus ancienne.
- Application : objet `Tr` de `:logic` (`Tr.t("refus.out_of_band")`, variables nommées `{freq}`), utilisable par
  les trois modules et dans les tests JVM. Pluriels par clés `_one` / `_other` (deux formes dans les 4 langues).
  Les rares textes que le SYSTÈME lit dans les ressources (nom de l'application, canal de notification,
  `locales_config.xml`) passent par `res/values-xx/strings.xml`.
- Page : petit module `i18n.js` qui charge le catalogue servi par la station (nouvelles routes dans `WEB_FILES`) ;
  textes de `index.html` marqués par un attribut (`data-t="…"`), remplis au chargement (pas de HTML construit par
  chaîne : CSP et piège `createElement`).

Alternative écartée pour l'application : tout en `strings.xml` avec un `Context` injecté dans `:logic` (casse les
tests JVM purs, gros remaniement de RigSession).

### 3.2 Choix de la langue

- Application : langue du téléphone si c'est fr / en / de / es, sinon ANGLAIS (décision 1) ; réglage
  Réglages > Langue qui l'emporte (langues par application d'Android 13+, `LocaleManager`, `locales_config.xml` ;
  préférence interne en Android 10 à 12, minSdk 29).
- Page : langue du navigateur (`navigator.languages`) si elle est l'une des 4, sinon anglais ; sélecteur dans la
  page, choix gardé par le navigateur (`localStorage` dans un try/catch). À voir à l'étape : reprendre la langue du
  compte opérateur (préférence de la console) quand elle existe.
- Changement de langue sans couper la connexion ; jamais pendant une émission (appliqué au retour en RX).

### 3.3 Textes envoyés par la station : dans la langue du client (décision 2)

- Le client annonce sa langue dans `POST /offer` (nouveau champ facultatif `lang` : `fr`, `en`, `de`, `es`) ; la
  station la valide (liste fermée, sinon `fr`) et la garde pour la session ; `hello` la renvoie (`lang`) et
  `hello.features` annonce `i18n`.
- Tout `detail` / `message` envoyé à ce client est fabriqué dans sa langue à partir du tronc commun
  (`client.<langue>.json`) ; `reason`, `event`, `ort` restent inchangés (codes stables).
- Messages diffusés à plusieurs clients (`breizh_event`, `freedv_event`, `rig_notice`, messages des modules par
  `client_message`) : fabriqués par client, pas une seule fois. Les modules (bus 127.0.0.1) envoient un code et ses
  variables, la PASSERELLE fabrique le texte (règle à imposer par un test).
- Station plus ancienne (pas de `i18n` dans `hello.features`) : l'application et la page traduisent par le code
  qu'elles connaissent, et ne montrent le `detail` français qu'en repli (code inconnu), précédé du code.
- Mise à jour : `docs/protocole.md`, exemples `tests/protocol/`, contrat Android (`:protocol`),
  `docs/parite-web-android.md` (règle « PROTOCOLE CLIENT » de CLAUDE.md).

### 3.4 Ce qui ne se traduit pas

Abréviations radio et noms du poste : PTT, TX, RX, SQL, NB, NR, ATT, P.AMP, AGC, FIL1/2/3, RIT, XIT, ΔTX, split,
QSY, S-mètre (S9+20), Po, ALC, VFO, modes Hamlib (USB, LSB, CW, FM, PKTUSB…), FreeDV, SELCALL, Cluster DX, codes
ORT / AND, numéros de menus de TRX Console (« menu 2.8 »), indicatifs, noms des mémoires de l'opérateur.
« TOS » devient « SWR » en EN / DE / ES ; « BLU » devient « SSB » (EN, DE) et « BLU » (ES). Glossaire commun avec
la console (§ 6).

### 3.5 Formats

Fréquences : format radio inchangé dans toutes les langues (`7.074.00`). Nombres décimaux affichés (TOS, dB,
kHz) : séparateur de la langue (virgule FR / DE / ES, point EN) par une seule fonction (`Format.kt`, et son
équivalent de la page). Dates et heures : format de la langue (fin de `Locale.FRANCE` en dur).

## 4. Points délicats

1. **Sécurité d'émission** : liste fermée des textes de sécurité (préfixes de clé `tx.`, `stop.`, `refus.`,
   `coupure.`, `power.`, `tot.`) relus par l'utilisateur dans chaque langue avant livraison ; test qui interdit une
   traduction vide ou identique au français pour ces clés (sauf abréviations du § 3.4).
2. **Place à l'écran** : l'allemand est ~30 % plus long. Boutons compacts, puces, barre du bas en deux lignes,
   sous-titre d'Android Auto (tronqué par la voiture), tablette, en-tête et rail de la page. Prévoir des libellés
   COURTS distincts (`…_court`) et un essai avec une pseudo-langue allongée (§ 7).
3. **Android Auto et voix** : la grammaire de `Voice.kt` devient une table par langue (« frequency / Frequenz /
   frecuencia », « memory / Speicher / memoria », « band / Band / banda ») ; la langue de la recherche vocale est
   celle de l'Assistant, pas celle de l'application : accepter les mots des 4 langues quelle que soit la langue
   choisie (aucun mot ne fait émettre : la voix ne change que fréquence, bande, mémoire).
4. **Textes réglementaires** : avertissements du scrambler, de la rediffusion, de la diffusion en direct : traduire
   fidèlement le français, sans adapter le droit du pays (relecture par l'utilisateur).
5. **Parité page / application** : `TextsTest` compare aujourd'hui les codes de `client.js` et de `Texts.kt` ; il
   devient « les deux lisent le même tronc commun ». L'exemple français du test reste en français.
6. **Textes partagés** (invitation, page des auditeurs, rapports, image du TOS) : dans la langue de l'expéditeur ;
   l'image du TOS garde « www.rf-diy.com ».
7. **Travail en parallèle** : les lots d'extraction modifient presque tous les fichiers de `android/` (T2, T3) puis
   de `gateway/api/static/` (T4). Pendant chacun, AUCUNE autre conversation ne doit modifier ces dossiers (sinon
   conflits sur tous les écrans). À annoncer sur le tableau de pilotage avant de commencer.
8. **Catalogue d'erreurs** : ajout de `de` et `es` à côté de `en` dans `catalog.yaml` / `AND-catalog.yaml` (mêmes
   variables, imposé par le test du catalogue), `build_errors.py` puis `build_errors_doc.py` (pages publiques
   `erreurs/de/`, `erreurs/es/`) ; alertes ntfy : `notify_lang` accepte alors `de` et `es`.
9. **Tests Node de la page** : le faux DOM des tests ne connaît pas les attributs ; les tests qui vérifient un texte
   français le lisent désormais dans le catalogue français.

## 5. Lots

Chaque lot = une étape (numéros de station / d'application suivants), validé par l'utilisateur avant le suivant,
comme pour la console. Rien de visible avant T5 sauf le champ `lang` du protocole.

| Lot | Contenu | Touche | Visible |
|---|---|---|---|
| **T0** (FAIT, étape 305) | Mécanisme et tronc commun : format des catalogues, `client.fr.json` (refus, coupures, motifs, aides), `Tr` de `:logic`, copie Gradle, `i18n.js` de la page, tests (mêmes clés, mêmes variables, JSON valide, clés de sécurité). | station, application, page | Non |
| **T1** | Station : `lang` dans `/offer` et `hello`, `detail` / `message` fabriqués dans la langue du client, modules par code + variables, protocole et exemples. FAIT (étape 306) pour les refus, l'accès, `bye` et `rig_notice` ; restent `power_progress`, `breizh_event`, `freedv_event`, messages des modules. | station | Non (français) |
| **T2** (FAIT, étape 307) | Extraction de `:logic` vers `app.fr.json` / tronc commun ; cliquet « aucune chaîne française dans un fichier converti » (liste `CONVERTED`, comme `test_error_free_text.py`). Réglage de langue. | application (gelée) | Non |
| **T3** (FAIT, étape 308) | Extraction de `:core` (notifications, RigService, RigMedia, Android Auto) et de `:app` (écrans, dialogues). | application (gelée) | Non |
| **T4** (FAIT, étape 309) | Extraction de la page (`client.js`, `ui.js`, `index.html`, puis les autres fichiers) vers `page.fr.json` / tronc commun ; sélecteur de langue. | page (gelée) | Non |
| **T5** | Anglais complet (application, page, station) + essais réels (téléphone, tablette, DHU, PC). | tout | Oui |
| **T6** | Allemand (vouvoiement) et espagnol, glossaire, pseudo-langue longue, ajustements de place. | tout | Oui |
| **T7** | Voix d'Android Auto en 4 langues, textes partagés, formats des dates et nombres. | application, page | Oui |
| **T8** | Catalogue d'erreurs ORT / AND en DE / ES, pages publiques des codes, `notify_lang` de / es. | station, site | Oui |
| **T9** | Fiche Google Play en EN / DE / ES (titre, descriptions, captures d'écran par langue), notes de version. | Store | Store |

Volume : environ 2 900 chaînes à déplacer (application + page ; une partie passe dans le tronc commun) ;
traduction ≈ 15 000 mots après dédoublonnage, plus le catalogue d'erreurs (457 codes), × 2 langues pour DE / ES
(l'anglais du catalogue existe déjà). Ordre conseillé : T0 et T1 tout de suite ; T2-T3 en série rapprochée
(application gelée), T4 (page gelée) ; puis T5 à T9.

## 6. Méthode de traduction

- Traduction faite par Claude à partir du français, avec un GLOSSAIRE `docs/i18n-glossaire.md` (FR / EN / DE / ES)
  repris des fichiers de la console pour les mêmes notions (station, poste, émission, mémoire, opérateur,
  visiteur…), afin que la console, l'application, la page et le guide disent la même chose.
- Ton : français inchangé (tutoiement de l'application et de la page) ; anglais neutre ; ALLEMAND VOUVOYÉ (« Sie »,
  décision 4, comme la console) ; espagnol « tú » (comme la console).
- Relecture DE / ES par un locuteur natif (déjà en attente pour la console) ; textes de sécurité relus par
  l'utilisateur.
- Le PC « tour radio » sert aux contrôles lourds (suite de tests de la station, comparaisons des catalogues) ; la
  compilation Android reste sur le PC de développement.

## 7. Tests et contrôles

- Mêmes clés et mêmes variables `{…}` dans les 4 fichiers de chaque famille ; aucune valeur vide ; JSON valide.
- Cliquets : aucune chaîne littérale de texte humain dans les fichiers convertis (Kotlin, JavaScript, HTML) ;
  aucun `detail` en français écrit en dur dans la station.
- Clés de sécurité : traduction présente et différente du français (sauf abréviations listées).
- Station : un client `lang = "de"` reçoit ses refus en allemand, un autre client en français en même temps ;
  `lang` inconnu = français ; vieux client sans `lang` = français.
- Pseudo-langue (`xx`, textes allongés de 40 % et accentués) disponible en débogage (application) et par paramètre
  (page) pour voir les débordements.
- Essais réels : S25 en EN / DE / ES, tablette, DHU Android Auto (titre / sous-titre), commandes vocales, page sur
  PC et téléphone, langue changée pendant la connexion, émission sur charge fictive dans chaque langue (textes
  d'émission, refus, STOP).
- `gradlew.bat test` complet à chaque lot (piège `TextsTest`) ; suite complète de la station (`scripts/tests.py`).

## 8. Décisions de l'utilisateur (2026-11-20)

1. Langue par défaut hors fr / en / de / es : **anglais**.
2. Textes de la station : **la station les envoie directement dans la langue du client** (§ 3.3).
3. Page web de la station : **traduite aussi**.
4. Allemand : **vouvoiement** (« Sie »).
5. Catalogue d'erreurs ORT / AND en DE / ES : **dans ce projet** (lot T8).
6. Fiche Google Play : **les 4 langues**.
7. Créneau de gel de `android/` (T2-T3) et de la page (T4) : à fixer avec l'utilisateur au moment de ces lots.
