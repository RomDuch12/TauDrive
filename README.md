# TauDrive — atelier TAU 10×10 SMART

Pilotage laser autonome pour la **TAU 10×10 SMART**
(source JPT MOPA 30 W, tête galvo XY2-100, f-theta 160 mm, champ
110 × 110 mm, carte CNC Cielle **CL90135**).

**Logiciel libre**, sous double licence **MIT ou Apache-2.0**, au choix
([LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE)). Les
données relevées chez les fournisseurs (`extrait/`, `fournisseurs/`) n'en
font pas partie ; les composants tiers gardent leurs licences
([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), dossier `licences/`).

**Cœur libre, données d'atelier en plugin**, comme VectorDrive. TauDrive
ne livre aucune donnée d'atelier : ses préréglages sont cinq exemples
neutres posés sur les couples constructeur de la source, sans semence,
magasin d'outils, dessins livrés ni couples mesurés sur pièce. Un atelier
les apporte par un plugin posé dans `plugins/`, à côté de l'exécutable —
voir [Cœur libre et plugins](#cœur-libre-et-plugins).

> **Les dossiers sources sont en lecture seule.** Rangés dans
> `fournisseurs/`, hors git : rien n'est jamais écrit dans
> `Cielle sur pc controller/`, `Incicam 2025 sp50 .../` ni
> `Tau_Smart_…/`. Tout le travail dérivé vit ici.

---

## Démarrer

```bash
python TauDrive.py                       # TauDrive
python TauDrive.py --autotest            # vérifier l'installation
python TauDrive.py --autotest vectoriel  # une seule grappe
python TauConvert.py                     # convertisseur seul
```

Dépendances : `PySide6`, `fontTools`, `pyserial`, `ezdxf`,
`Pillow` (icône seulement), `PyInstaller` (empaquetage seulement).

**Distribution autonome**, sans Python sur les postes :

```bash
pyinstaller --clean --noconfirm TauDrive.spec
dist/TauDrive/TauDrive.exe --autotest        # 589 contrôles
```

**Versions numérotées comme VectorDrive**, une par publication :

```bash
python outils/publier.py --monter
```

```bash
python outils/publier.py
```

`--monter` fait passer `__version__` (`src/engrave/__init__.py`) de
1.268.0 à 1.269.0 ; la version se décrit dans `NOUVEAUTES.md`, et le
tout se commite. La publication empaquette alors TauDrive et TauConvert,
lance l'autotest de chaque exécutable, et dépose
`dist/portable/TauDrive-x.y.z-portable.zip` et
`TauConvert-x.y.z-portable.zip`. Elle refuse une version déjà publiée ou
que `NOUVEAUTES.md` ne décrit pas. Les trois dernières versions sont
gardées, hors git.

**L'édition d'un atelier** — le même TauDrive, avec le plugin de l'atelier
dans `plugins/` — sort en même temps, dans
`TauDrive-NOM-x.y.z-portable.zip` :

```bash
python outils/publier.py --plugin DOSSIER_DU_PLUGIN --edition NOM
```

---

## Cœur libre et plugins

Un plugin est un paquet Python qui expose `PLUGIN` (nom, version, API,
licence) et `register(api)`. `api` (`src/engrave/plugins.py`) est la
seule porte vers le cœur ; ce qu'il déclare, le cœur le consulte :

| Méthode | Ce qu'elle apporte | Consulté par |
|---|---|---|
| `add_recipes(…)`, `add_recipes(…, material=True)` | préréglages (ils remplacent ceux du cœur), process par matière | `model.factory_recipes()` |
| `set_recipe_defaults(**valeurs)` | process neuve, forme neuve, champ absent d'un fichier | `model.default_recipe()` |
| `set_seed_dir(dossier)` | semence du premier lancement | `semence.dossier()` |
| `set_tool_store(outils.json)` | magasin d'outils extrait de la machine | `toolstore.bundled_path()` |
| `add_couples(…)` | couples d'atelier nommés, mode expert | `couples.workshop()` |
| `set_drawings_dir(dossier)` | dessins livrés | `drawings.delivered_dir()` |
| `set_machine(nom)`, `add_about(ligne)` | *? ▸ À propos* | `app.machine_label()` |
| `add_autotest(nom, fn)` | contrôles de l'autotest, grappe `plugins` | `TauDrive.exe --autotest plugins` |

Les **couples constructeur** de la source (`couples.FACTORY`, treize
formes d'onde) sont des limites de la source, pas des données d'atelier :
ils restent au cœur.

**Où TauDrive cherche** : `plugins/` à côté de l'exécutable (à la racine
du dépôt en développement), `%LOCALAPPDATA%\TauDrive\plugins`, puis les
dossiers de `TAUDRIVE_PLUGINS` (séparés par `;`). `TAUDRIVE_NO_PLUGINS=1`
les écarte tous. Un plugin en erreur n'empêche jamais le démarrage ;
*À propos* le dit. Les grappes du cœur de l'autotest ne chargent aucun
plugin : elles éprouvent le cœur libre seul.

**Dépôt public** : `outils/exporter_public.py DOSSIER --interdits FICHIER`
copie les fichiers suivis, sauf les documents de travail (spécification,
notes d'analyse de la machine, outils d'extraction, données des
fournisseurs, fichiers de clients) ; il refuse tout fichier de production
et tout mot de la liste privée, et publie dans un dépôt git neuf, sans
l'historique de travail.

---

## Arborescence

| Dossier | Contenu |
|---|---|
| `reference/` | documentation reconstituée, en français avec terminologie anglaise |
| `fournisseurs/` | dossiers d'origine Cielle, Incicam et Tau Smart — lecture seule, hors git |
| `extrait/` | données extraites de la machine : dictionnaire des paramètres, magasin d'outils — privées, hors licence |
| `ressources/` | logo et icône |
| `plugins/` | plugins d'atelier posés pour le développement — hors git |
| `captures/` | logs machine datés — *vide tant qu'aucune capture n'a eu lieu* |
| `outils/` | scripts d'extraction, d'analyse et de validation |
| `src/cl90135/` | protocole carte CNC : trame, décodeur `.CMD` |
| `src/jpt/` | protocole et client de la source laser |
| `src/engrave/` | TauDrive : modèle, géométrie, trajectoires, codes 2D, export, interface, thèmes, icônes |
| `TauDrive.spec` | recette d'empaquetage PyInstaller |
| `TauConvert.spec` | version réduite : conversion et menu contextuel seuls |
| `dist/portable/` | versions zippées, hors git — `outils/publier.py` |
| `NOUVEAUTES.md` | ce que chaque version change pour l'opérateur |
| `LICENSE`, `LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE` | double licence MIT ou Apache-2.0, et son étendue |
| `THIRD_PARTY_NOTICES.md`, `licences/` | composants tiers : licence et usage de chacun, textes à joindre |

---

## État d'avancement

| Élément | Statut | Validation |
|---|---|---|
| Couche trame CL90135 (DLE + CRC-16/ARC) | **validée** | 107/107, ré-encodage à l'octet près |
| Format `.CMD` (tampon de trajectoire) | **validé** | 173/173 jusqu'à EOF, 10 623 707 enregistrements |
| Transformation ISO → CMD | **validée** | emprise et centre concordants au millième de mm |
| Protocole série source JPT | **reconstitué** | 14/14 |
| Client série JPT | **fonctionnel** | source simulée intégrée ; 19/19 |
| TauDrive : dessin, trajectoires, export | **fonctionnel** | 589/589 |
| Cercles et ellipses | **fonctionnel** | inclus ci-dessus |
| Redimensionnement F2, groupes | **fonctionnel** | inclus ci-dessus |
| Onglets, session, dossiers d'export horodatés | **fonctionnel** | inclus ci-dessus |
| Cadre en négatif sur toute forme, DXF compris | **fonctionnel** | inclus ci-dessus |
| Codes : DataMatrix carré et rectangulaire, QR, Code 39, EAN-13, Code 128 | **fonctionnel** | 90/90 — dont la reproduction exacte du symbole de production ; 5 930 symboles relus par zxing-cpp |
| Plaque codée : code + texte ajustés à leurs cadres | **fonctionnel** | inclus ci-dessus |
| Onglets nommables, sauvegarde silencieuse de session | **fonctionnel** | 288/288 sur l'interface |
| Process par matière (relevées du magasin d'outils) | **fonctionnel** | inclus ci-dessus |
| Process : remplissage complet, oscillation, rangement par dossier | **fonctionnel** | arbre repliable ; format compatible avec le poste de production |
| Process de **texture** inox / laiton / alu | **livré** | 15 états de surface, couples constructeur ; à valider sur coupon |
| Semence : la distribution apporte les process du poste de prod | **fonctionnel** | 33 process, 1 gabarit ; ne remplace jamais |
| Encombrement **Dim X / Dim Y** en tête des propriétés | **fonctionnel** | géométrie réelle, cadre compris ; vaut pour un tracé importé |
| **F2 fait tourner** — échelle, rotation, placement | **fonctionnel** | groupe autour du centre commun, forme seule sur elle-même |
| F2 : la cote en avant, pourcentages repliés | **fonctionnel** | gras et plus hauts ; repli retenu |
| Nappes tournées **toutes dessinées** (ex. 3 × 60°) | **corrigé** | angles distincts mod 180° ; plafond d'écran à 6, gravure non bornée |
| Contraste vérifié sur **19 thèmes × 4 rôles** | **corrigé** | 52 couleurs en dur retirées ; 3,06 → ≥ 4,5 sur les thèmes clairs |
| Import lourd fluide : zone de clic bornée | **corrigé** | 34 ms → 0,01 ms par mouvement de souris |
| Barre d'avancement au-delà d'une seconde, annulable | **fonctionnel** | seuil sur le temps écoulé, pas sur la taille |
| Bytecode livré **sans docstrings** | **fonctionnel** | 378 ko retirés (36 %) ; autotest identique sur les deux copies |
| Visibilité par forme, exports répétés numérotés | **fonctionnel** | inclus ci-dessus |
| Fonctionnement hors réseau, historique conservé | **fonctionnel** | 21/21 |
| Cadre englobant : gravure du code en négatif | **fonctionnel** | inclus ci-dessus |
| Passes liées à la profondeur (Z décroissant) | **fonctionnel** | inclus ci-dessus |
| Chemin machine sur modèle paramétrable | **fonctionnel** | inclus ci-dessus |
| Préréglages de code (tout le formulaire) | **fonctionnel** | inclus ci-dessus |
| Codes gravés pleins, indépendamment de la process | **fonctionnel** | inclus ci-dessus |
| Dossiers par défaut paramétrables | **fonctionnel** | inclus ci-dessus |
| Épaisseur de trait par passages parallèles, sans recouvrement | **fonctionnel** | 85 % → 6 % de trajet en double |
| Décalage de contour exact (onglet, normales unitaires) | **fonctionnel** | 0,050 mm demandés, 0,050 obtenus |
| Export direct sur partage réseau, sans recopie | **fonctionnel** | inclus ci-dessus |
| Gestionnaire de process + mode expert (code) | **fonctionnel** | inclus ci-dessus |
| Texte multiligne, alignements, cadre en positif | **fonctionnel** | inclus ci-dessus |
| Import DXF (par calque, unités, mise à l'échelle) | **fonctionnel** | testé sur les 2 DXF de production |
| Import **PDF et Illustrator** (.ai v9+, qui est un PDF) | **fonctionnel** | 80,0000 × 40,0000 mm demandés, obtenus |
| Import **EPS / PostScript**, en-tête binaire DOS compris | **fonctionnel** | plan de production 5,2 Mo : 9 914 tracés en 0,6 s |
| Import **CorelDRAW** par convertisseur externe | **conditionnel** | Inkscape ou LibreOffice ; refus explicite sinon |
| Import **SVG**, lecteur propre sans convertisseur | **fonctionnel** | 80,000 × 40,000 mm exacts ; flèche 0,0099 pour 0,02 demandés |
| Texte non vectorisé **rendu en contours** (DXF, SVG, PDF/AI) | **fonctionnel** | TEXT+MTEXT : 37 polylignes, 1849 points ; substitution de police testée |
| **Cotations DXF** : DIMENSION, LEADER, tableau de cartouche | **fonctionnel** | plan de production : 44 cotations perdues → 705 polylignes |
| Calques éteints, gelés ou non tracés **écartés** | **corrigé** | `Defpoints` et les sauvegardes associatives ne se gravent plus |
| **Export DXF, EPS, AI, SVG et PDF** — dessin ou trajectoires | **fonctionnel** | EPS relu à 40,000 × 20,000 mm ; SVG à 0,07 µm près ; PDF écrit/relu identique |
| **Conversion au clic droit** de Windows | **fonctionnel** | 7 formats en entrée, 5 en sortie ; posé et retiré sans résidu |
| **Montage à DataMatrix** — un gabarit, pas du code | **fonctionnel** | positions et entraxe dans `montages.json` ; 4 postes sans recompiler |
| **TauConvert**, version réduite | **fonctionnel** | conversion + menu contextuel seuls ; ni gravure ni machine (175 Mo contre 220) |
| Séparer les tracés d'un import : cadre, ou un par un | **fonctionnel** | œil, duplication, offset et F2 sur chaque tracé |
| Versions et liens des convertisseurs, dans l'aide | **livré** | Inkscape 1.0+, LibreOffice 6.0+ |
| Bibliothèque lourde : esquisse, réserve bornée, vignettes disque | **corrigé** | 362 Mo retenus → 6 Mo ; lecture annulable en 0,26 s |
| Import / export des réglages et de la bibliothèque | **fonctionnel** | un fichier `.taudrive-reglages`, inspecté avant reprise |
| Bibliothèque de process retrouvée après le renommage | **corrigé** | `recettes.json` figé ; anciens noms relus et migrés |
| **Couteau** : un tracé devient un contour fermé épais | **fonctionnel** | 6 cas durs vérifiés simples ; 50×2 mm + π à la cote |
| Un dernier dossier retenu **par usage** : ouvrir, enregistrer, importer, exporter | **corrigé** | `start_folder` ne lisait jamais la mémoire qu'il écrivait |
| Annuler / refaire, par onglet | **fonctionnel** | inclus ci-dessus |
| Vérification avant export (activable dans Paramètres) | **fonctionnel** | inclus ci-dessus |
| Coupon d'essai : grille de paramètres, valeurs gravées | **fonctionnel** | inclus ci-dessus |
| Coupon éditable case par case après génération | **fonctionnel** | inclus ci-dessus |
| Coupon : paramètres fixes, formulaire rééditable | **fonctionnel** | fréquence et impulsion en expert |
| Offset signé du dessin sous un cadre (compensation de trait) | **fonctionnel** | symétrique, contre-formes comprises |
| Bibliothèque de dessins : livrés + poste, **rayons**, gestion complète | **fonctionnel** | MyCar livré ; DXF et .taudrive |
| Journal des exports : paramètres et modifications horodatés | **fonctionnel** | texte ASCII, lisible sans TauDrive |
| Process : commentaire libre et bouton d'enregistrement | **fonctionnel** | zone de texte à hauteur dynamique |
| Traitement d'un dessin : copie traitée, original **masqué sur place** | **fonctionnel** | bouton épaisseur = 2 × offset |
| Magasin d'outils machine : lecture et chargement en process | **décodé** | 73 outils ; panneau colonne 3, mode simple |
| Modèles de traitement, figés dans les process | **fonctionnel** | supprimer le modèle ne casse rien |
| Process et magasin prennent les colonnes 2 et 3 | **fonctionnel** | « Terminé » rend le dessin |
| Liste des formes : renommer, réordonner, menu contextuel | **fonctionnel** | double-clic et clic droit |
| Enregistrer une process crée au lieu d'écraser, dossiers | **fonctionnel** | « Laiton », puis « Laiton 2 » |
| Onglets fermés : tous gardés, archivés par semaine `26s34` | **fonctionnel** | recherche par mot-clé, contenu compris |
| Date automatique : champ variable, 8 formats, ajustement | **fonctionnel** | taille calculée sur le rendu réel |
| Copier/coller superposé, entre onglets | **fonctionnel** | groupe collé neuf et séparé |
| Clic droit sur onglet : dupliquer, renommer, fermer | **fonctionnel** | copie indépendante |
| Barre d'état verte/rouge après export | **fonctionnel** | couleurs du thème, 2 s |
| Vitesses en m/min à la saisie et à l'affichage | **fonctionnel** | modèle et ISO restent en mm/min |
| Sélection multiple ou groupe : **formulaire de lot** en colonne 3 | **fonctionnel** | centre, cotes, rotation, process commune, mesures |
| Process appliquée d'un coup à tout un lot | **fonctionnel** | valeur mêlée jamais écrite |
| Lot : **aligner, répartir, centrer** dans le champ | **fonctionnel** | un groupe bouge d'un bloc |
| **Retourner** (miroir) et **convertir en tracé** | **fonctionnel** | trajectoires identiques ; un code 2D refusé |
| **Répéter en grille** : colonnes, rangées, pas | **fonctionnel** | une plaque groupée par case, champ vérifié |
| Documents abîmés : **valeurs illisibles remplacées et nommées** | **corrigé** | 150 plantages sur 300 → 0 sur 1 300 |
| Dessins importés abîmés : **points illisibles écartés**, remplissage démesuré borné | **corrigé** | 10 plantages ou blocages sur 100 → 0 sur 150 |
| Lettres à **traits superposés** (Bahnschrift, scripts, « ç ») : remplies sans trou | **corrigé** | 35 glyphes sur 62 troués en Bahnschrift → 0 ; 55 polices sur 92 identiques |
| Ordonnancement du parcours | **accéléré** | 11,9 s → 2,5 s sur 300 codes, même ordre |
| Textes et codes : **dessinés une fois** ; planche ≠ montage | **accéléré** | 300 plaques : sélection 1,7 → 0,25 s, contours identiques |
| Relecture indépendante des cycles EX-227 à 232 | **corrigé** | 8 défauts, dont un tracé retourné gravé à l'endroit |
| **Cintrer un texte en arc** : rayon, côté | **fonctionnel** | ligne de base sur le cercle, lisible par le haut ou par le bas |
| **Répéter en cercle** : cases, centre, angle | **fonctionnel** | graduations orientées, plaques groupées par case |
| **Rejouer le parcours** dans l'ordre de l'export | **fonctionnel** | au temps exact du modèle de durée ; 48 300 allumages fluides |
| **Magnétisme** : bords et milieux s'accrochent en déplaçant | **fonctionnel** | formes, axes, champ ; Alt libère ; clavier toujours exact |
| Relecture indépendante des cycles EX-238 à 240 | **corrigé** | 10 défauts, dont un import figé par une courbe NaN ; script ×1,5 à ×3,7 |
| Vérification d'un travail oscillé : ×1,8, sablier, cache préservé | **fonctionnel** | mêmes notes au bit près ; l'export qui suit ne recalcule plus tout |
| Cache de géométrie compact pour les grosses entrées | **fonctionnel** | 282 → 41 Mo sur un texte oscillé ; plus de recalcul en boucle au-delà du plafond |
| Oscillation trop dense : comptée avant calcul, bloquée, refusée | **fonctionnel** | un pas de 0,001 ne fige plus ; forme lourde peinte une fois (210 → 1 ms) |
| Ordonnancement déterministe, vérification aux réglages de l'export | **fonctionnel** | même ordre à toute charge ; 2-opt 2 à 3× plus rapide, trajet à vide plus court |
| Séries : forme inchangée ordonnée et écrite une fois | **accéléré** | 50 plaques 21 s → 5,2 s, fichiers identiques octet pour octet |
| Relecture EX-243 à 245 : cache sous verrou, plafond par forme, série refusée avant écriture | **corrigé** | 4 défauts reproduits puis corrigés, 5 retouches |
| Démarrage : ezdxf et numpy chargés à la demande | **accéléré** | fenêtre affichée en 1,9 s au lieu de 2,9 à 3,7 |
| Historique et session légers sur un gros dessin | **accéléré** | DXF de 400 000 points : 1,7 s → 0,1 s par retouche, 26 → 3 Mo par état |
| Bibliothèque : DXF à sa vraie taille ; relecture trois fois plus rapide | **corrigé** | plan d'essai posé à 157 mm au lieu de 156 m, intact après « refaire » ; annuler 0,15 → 0,07 s |
| Relecture EX-246 à 248 : refus périmé, mémoire de série, pièce du milieu, passes groupées tournantes | **corrigé** | 5 défauts + 3 plus anciens, chacun reproduit puis corrigé |
| Préréglages de code lus comme un document | **corrigé** | symbologie inconnue, module illisible : laissés de côté et dits |
| Code 128 : deux chiffres par caractère, table relue par zxing-cpp | **fonctionnel** | 106/106 valeurs relues ; rangé à part pour les versions antérieures |
| Décalage : un long côté en biais ne fige plus | **corrigé** | triangle de 40 mm : 13,5 → 0,15 s ; mêmes contours au bit près |
| Relecture EX-249 à 254 : montage repassé ailleurs, calque seul, infobulle, cotes, unités DXF | **corrigé** | 6 défauts + 1 plus ancien, chacun reproduit puis corrigé |
| Banc de 600 documents au hasard : code inencodable, `{n:c}`, mot F, process négatif | **corrigé** | 6 défauts, chacun reproduit puis corrigé ; refus avant d'écrire la série |
| Épaissir : passages retenus rangés en segments, non en échantillons | **accéléré** | rectangle épaissi de 25 mm : 31 → 1,1 s ; mêmes tracés au bit près |
| Décalage : côtés sans voisin sautés, dessin dense jugé par un arbre | **accéléré** | rectangle décalé de 0,0001 mm : 18 → 0,0 s ; mêmes contours au bit près |
| Export DXF : sommets posés d'un bloc | **accéléré** | spirale de 60 000 points : 33 → 1,0 s ; même fichier octet pour octet |
| Épaississement plafonné à deux mille passages | **corrigé** | 1 000 mm au pas de 0,05 mm : figé → 0,22 s ; tracé seul, signalé à la vérification |
| Morceaux plafonnés à mille, champ d'au moins 1 mm | **corrigé** | champ de 0,01 mm : des millions de morceaux, la mémoire épuisée → refusé, export grisé |
| Plus proche voisin : une case chargée se trie à l'arbre | **accéléré** | 20 000 traits et un à 5 m : 122 → 0,95 s ; même ordre, même ISO |
| Épaississement dense : les rangés proches se jugent d'un bloc | **accéléré** | 910 barres dans 5 mm épaissies de 0,5 mm : 294 → 82 s ; tracés identiques au bit |
| Un seul dossier de travail, une archive zippée par version | **en place** | `outils/publier.py` → `dist/portable/TauDrive-x.y.z-portable.zip`, autotest de l'exe compris |
| Numéro de version comme VectorDrive : 1.268.0, le milieu +1 par publication | **en place** | `src/engrave/__init__.py` ; *À propos*, propriétés des exe, noms d'archives, `NOUVEAUTES.md` |
| Licence MIT ou Apache-2.0, comme VectorDrive | **en place** | licences des composants jointes à chaque archive ; `extrait/` hors licence |
| Cœur libre sans données d'atelier ; plugins, comme VectorDrive | **en place** | `plugins.py` ; édition d'atelier `publier.py --plugin` ; `exporter_public.py` ; `test_engrave` {TE}/{TE} |
| Démarrage : seul l'onglet de devant s'ouvre, les autres au clic | **accéléré** | 4 onglets dont 220 000 points : 8–10 s → 1,2 s ; résumé de 20 passes sur les mêmes traits 4,4 → 0,3 s, au bit près |
| **Q** grouper, **S** dégrouper, **Ctrl+G** combiner, **Ctrl+Maj+G** décombiner, **Alt+W** centrer, **Ctrl+I** importer | **en place** | barre d'outils et menu *Forme* ; Q et S ne valent que sur le plan de travail et la liste des formes |
| Coupon : cases portant un **DXF ou la sélection** | **fonctionnel** | clic droit ▸ en faire un coupon |
| Coupon : axe **couple F-T** (1300-2, 375-9, 250-13) | **fonctionnel** | table constructeur seule en mode normal |
| Gestionnaire de couples fréquence/impulsion | **fonctionnel** | mode expert ; 46 couples récoltés du magasin |
| Décalage sans boucle dans les angles rentrants | **corrigé** | 9 segments fautifs → 0 sur « 2608 » |
| Barre d'outils : icônes seules, annuler/refaire en tête | **fonctionnel** | export large, vert ou orange selon le thème |
| Aide contextuelle en **barre d'état**, plus d'infobulle flottante | **fonctionnel** | ~300 infobulles routées sans rien réécrire |
| Bouton *Process…* : ouvre **et** referme le gestionnaire | **fonctionnel** | Ctrl+M bascule de même |
| Décalage **recousu** : plus un seul contour ouvert | **corrigé** | 14 contours ouverts sur 19 → 0 |
| Offset du dessin **avec ou sans cadre** | **fonctionnel** | amincir ou grossir un tracé nu |
| Trois décimales affichées, la valeur reste entière | **fonctionnel** | « -26,112 » pour -26,111537 |
| *Ajuster* en surcouche du plan de travail | **fonctionnel** | coin bas-droit, Ctrl+0 conservé |
| Bibliothèque et process bordés à droite de la barre | **fonctionnel** | réserves séparées des outils |
| Table constructeur : les 13 formes d'onde de la source | **relevée** | 1300-2 … 37-500, rapport cyclique 0,26 → 1,85 % |
| Couples d'atelier nommés d'après leur travail | **fonctionnel** | apportés par le plugin de l'atelier, mode expert |
| Bibliothèque en **panneau** : aperçu colonne 2, arbre colonne 3 | **fonctionnel** | même disposition que le gestionnaire de process |
| Aperçu allégé d'abord, pleine définition ensuite | **fonctionnel** | chargement hors du fil qui peint |
| Rayons en arborescence, icône dossier | **fonctionnel** | plus de liste plate ni de menu déroulant |
| **Oscillation du faisceau** (cercle, huit, transverse) | **fonctionnel** | phase sur la longueur parcourue, contours refermés |
| Cadence scanner calculée, export refusé si le miroir ne suit pas | **fonctionnel** | 13 kHz demandés à 80 m/min · pas 0,1 mm |
| Remplissage : rotation par passe, croisé, retrait | **fonctionnel** | 540 → 1040 mm croisé, géométrie par passe |
| Guide des paramètres laser, bouton **?** du gestionnaire | **livré** | 3 pages, nourries des données du programme |
| Audit des recommandations contre la machine | **outil** | 3 tenues sur 7 ; la table s'avère nominale, pas impérative |
| Ctrl+H / Ctrl+F : plein ou filaire, pas mémorisé | **fonctionnel** | inclus ci-dessus |
| Coupon : cinq options activables séparément | **fonctionnel** | texte et cases indépendants |
| Export conforme au modèle machine : alphabet, encodage, noms | **fonctionnel** | comparé aux 7 ISO de la machine |
| Interface entièrement en français, Qt compris | **fonctionnel** | inclus ci-dessus |
| 19 thèmes, contrastes vérifiés au calcul | **fonctionnel** | contraste texte ≥ 7:1 sur les 19 |
| Mode simple : source laser, réseau, lot/série masqués | **fonctionnel** | inclus ci-dessus |
| Menu « ? » : version, machine, contact | **fonctionnel** | inclus ci-dessus |
| Magasin d'outils `dbpunte.mag` | **décodé** | 72 process, 3 outils recoupés, spot confirmé sur 9 |
| Limites machine : vitesse faisceau, plages laser | **établies** | 3 sources concordantes, 10,6 M enregistrements |
| Ordonnancement des trajectoires | **fonctionnel** | jusqu'à 90 % de trajet à vide en moins |
| Dictionnaire des paramètres IT/FR/EN | **livré** | 4 106 paramètres, 86,6 % traduits |
| Empaquetage autonome (PyInstaller) | **fonctionnel** | 288/288 sur l'exécutable figé, aucun code source distribué |
| CLJOB accepté par ClTerm | **réparé** | balises identiques au fichier machine, même ordre |
| Séquence de gravure au niveau des commandes | **relevée** | 1 125 lignes, capture du 17 août |
| **Commandes de mouvement au niveau octet** | **manquant** | *nécessite la session de capture* |

```bash
cd atelier
for t in frame cmdfile jpt jpt_client engrave barcode session; do python outils/test_$t.py; done
```

---

## Documents

**Protocoles machine**
* [`protocole-cl90135.md`](reference/protocole-cl90135.md) — liaison, trame,
  CRC, byte-stuffing, couche message.
* [`format-cmd.md`](reference/format-cmd.md) — en-tête, opcodes, conventions,
  validation croisée ISO → CMD.
* [`protocole-jpt.md`](reference/protocole-jpt.md) — source laser : trame,
  commandes, réponses, champs de bits, unités.

**Cadrage**
* [`specification.md`](reference/specification.md) — **spécification
  fonctionnelle**, 112 exigences numérotées et leur justification.
* [`limites-machine.md`](reference/limites-machine.md) — **ce que la
  machine sait faire** : vitesse maximale du faisceau, plages
  impulsion / fréquence / puissance réellement employées, et la relation
  pas d'impulsion ↔ diamètre de spot qui les lie.

**Application**
* [`couteau.md`](reference/couteau.md) — donner une épaisseur à un
  tracé : contours fermés, sans auto-intersection
* [`mise-a-jour.md`](reference/mise-a-jour.md) — où vivent les réglages,
  comment mettre à jour sans rien perdre, import et export
* [`import-vectoriel.md`](reference/import-vectoriel.md) — PDF,
  Illustrator, EPS, SVG, CorelDRAW : ce qui est lu et comment, la
  conversion par le clic droit de Windows, et la version réduite
  *TauConvert*
* [`montage-3dm.md`](reference/montage-3dm.md) — le montage à trois
  DataMatrix : cotes, liens texte/code, formulaire à trois champs
* [`parametres-laser.md`](reference/parametres-laser.md) — physique des
  réglages, formes d'onde de la source, audit des recommandations,
  remplissage et oscillation
* [`export-iso.md`](reference/export-iso.md) — TauDrive : process, format
  ISO/CLJOB, ordonnancement, ergonomie, texte multiligne, séries, import DXF.
* [`magasin-outils.md`](reference/magasin-outils.md) — structure de
  `dbpunte.mag` et méthode de décodage.

**Données et méthode**
* [`dictionnaire-parametres.md`](reference/dictionnaire-parametres.md) —
  4 106 paramètres IT/FR/EN et ce que vaut chaque traduction.
* [`procedure-capture.md`](reference/procedure-capture.md) — **procédure de
  la session de journalisation** sur le poste de production.
* [`analyse-capture-260817.md`](reference/analyse-capture-260817.md) — ce
  que contient la capture du 17 août, **pourquoi le journal octet n'a pas
  été écrit**, et la séquence de gravure relevée.
* [`trace-nommee-260817.txt`](reference/trace-nommee-260817.txt) — les
  1 125 commandes nommées d'une gravure réelle, en clair.

---

## Ce qui reste bloqué

Les captures existantes ne contiennent **que du trafic de configuration au
démarrage, dans le sens carte → PC**. Aucune commande de mouvement ni de
tir laser n'y figure.

La capture du 17 août 2026 n'a pas levé ce point, et la cause est
identifiée : les deux paramètres de journalisation avaient bien été armés,
mais le fichier `Param_cielle.xml` qui les portait contenait aussi neuf
valeurs `NaN` sur des paramètres de jerk. ClTerm l'a déclaré corrompu au
démarrage et a **restauré la sauvegarde de la veille**, drapeaux éteints
compris. Détail et marche à suivre :
[`analyse-capture-260817.md`](reference/analyse-capture-260817.md).

Ce que cette capture a tout de même apporté : la **séquence complète d'une
gravure au niveau des commandes nommées**. On sait désormais quels ordres
chercher et dans quel ordre ils arrivent — le dépouillement de la
prochaine capture consistera à aligner le journal octet sur cette trace,
horodatage contre horodatage.

Tant que cette capture n'a pas eu lieu, TauDrive **ne pilote pas la machine
directement** : il produit des fichiers `ISO` + `CLJOB` que ClTerm exécute.
Ces fichiers peuvent être écrits **directement sur un partage réseau** que
la machine sait lire — le CLJOB les y désigne, il n'y a rien à recopier
dans `C:\inciwin\cl_iso`.
Toute la chaîne en amont — modèle, géométrie, hachurage, vectorisation,
process et ordonnancement — est commune aux deux sorties et ne
sera pas à refaire.

Marche à suivre : [`procedure-capture.md`](reference/procedure-capture.md).
Réserve importante à vérifier dès la première passe : dans le journal
existant, **68 % des fragments sont tronqués**.
