# TauDrive — application de gravure et export ISO

TauDrive, application PySide6 : plan de travail, rectangles, textes vectorisés,
process laser, export vers un couple `ISO` + `CLJOB` exécutable par
ClTerm.

```bash
python TauDrive.py
```

Validation : `python outils/test_engrave.py` (286/286)
et `python outils/test_barcode.py` (76/76)

---

## 1. Où se branche cette application

```
   TauDrive    ──►  Document  ──►  Trajectoires  ──┬──►  ISO + CLJOB  ──►  ClTerm  ──►  machine
   (canvas)         (formes)      (ordonnancées)   │      ✅ fonctionne aujourd'hui
                                                   │
                                                   └──►  pilote CL90135 natif
                                                          ⛔ bloqué : protocole de
                                                             mouvement non capturé
```

Le protocole de mouvement de la carte n'étant pas encore connu (voir
[procedure-capture.md](procedure-capture.md)), **l'application ne pilote pas
la machine directement**. Elle produit des fichiers que ClTerm sait
exécuter — c'est la seule voie qui grave réellement aujourd'hui.

Tout ce qui est en amont de la flèche — modèle, géométrie, hachurage,
vectorisation de texte, process — est **commun aux deux sorties**. Ce
travail ne sera pas à refaire quand le pilote natif arrivera : il n'y aura
qu'un second générateur à brancher à la place de `engrave.iso`.

---

## 2. Repère et unités

Millimètres. **X vers la droite, Y vers le haut**, origine au centre du
champ de marquage 110 × 110 mm de la TAU SMART. C'est le repère machine,
donc ce qui est à l'écran est à l'échelle et à la place réelles.

Le dépassement du champ est signalé en permanence dans la barre d'état et
redemandé à l'export.

---

## 3. Formes

| Forme | Paramètres |
|---|---|
| **Rectangle** | largeur, hauteur, position, rotation |
| **Cercle / ellipse** | diamètre X, diamètre Y, position, rotation |
| **Texte** | chaîne, hauteur de capitale, étirement, police TrueType, alignement, position, rotation |
| **Tracé** | polylignes importées d'un DXF, par calque |
| **Code** | DataMatrix, QR Code, Code 39, EAN-13 — voir §22 et §26 |

Toute forme porte en outre un **cadre** (§14) et une **épaisseur de
trait** (§23).

Le cercle est discrétisé sur une tolérance de corde, avec un nombre de
segments **multiple de quatre** : les quatre points cardinaux tombent
ainsi exactement sur le contour. Sans cette contrainte, un cercle de ⌀20
mesurait 19,988 mm sur un axe — invisible à l'écran, bien réel sur la
pièce.

Le texte est vectorisé par **fontTools** à partir du contour réel de la
police (`C:\Windows\Fonts` par défaut), pas d'une approximation. Les
contre-formes — le trou du « O », l'intérieur du « A » — sont correctement
exclues du remplissage par la règle pair-impair.

---

## 4. Process laser

Une process est l'équivalent d'un *utensile* Cielle :

| Champ | Unité | Remarque |
|---|---|---|
| `power_percent` | % | |
| `frequency_khz` | kHz | converti en Hz dans le `G108` |
| `pulse_width_ns` | ns | |
| `speed_mm_min` | mm/min | devient le mot `F` |
| `passes` | — | nombre de passages |
| `hatch_mm` | mm | pas de hachurage ; **0 = contour seul** |
| `hatch_angle_deg` | ° | |
| `tool_number` | — | mot `T` — **voir l'avertissement ci-dessous** |

Les préréglages fournis sont repris de `ReportIncisione.txt` de la machine :
`Marqueur` (outil 3), `JPT 30W laiton` (62), `Dégrossissage` (65),
`Satinage` (66).

Le hachurage est produit en balayage alterné (zigzag) pour limiter les
déplacements à vide.

> ### ⚠ Le numéro d'outil
> Les fichiers ISO observés portent **à la fois** un `T<n>` et un
> `G108 P.. I..`. Lequel l'emporte quand les deux se contredisent —
> paramètres du magasin `dbpunte.mag` ou valeurs du `G108` — **n'a pas été
> vérifié**.
>
> Tant que ce point n'est pas tranché, considérez que **c'est le numéro
> d'outil qui commande** et renseignez-le avec un outil réellement présent
> dans le magasin de la machine, dont les paramètres correspondent à ce que
> vous voulez. Les valeurs de la process servent alors à l'estimation de
> durée et à l'aperçu.

---

## 5. Format produit

Un fichier `.ISO` par passe, plus un `.CLJOB` qui les enchaîne.

```
(INGOMBROFOGLIO:-10.000, -5.000, 10.000, 5.000)
(Programma generatore: atelier-cielle)
(rectangle 20×10)
T62 (JPT 30W laiton,STELO: 6.000, BASE: 0.030, ROT: 0)
S10000
G108 P100.000 I80000.00
T62 (...)
G00X-10.000000Y-5.000000     déplacement à vide
G00Z0.000000                 pose (laser actif)
F80000                       vitesse
G01X10.000000Y-5.000000      gravure
...
G00Z-0.001000                lève
```

Conventions reprises telles quelles du dialecte observé :
`Z 0.000000` pose, `Z -0.001000` lève, `G108 P<%> I<Hz>`, `S10000`.

### Où le CLJOB va chercher les ISO

**Par défaut, le CLJOB désigne les `.ISO` à l'endroit exact où ils
viennent d'être écrits.** Exporter sur un partage réseau que la machine
sait lire suffit donc : ClTerm ouvre le CLJOB sur le partage et y trouve
ses fichiers. **Il n'y a rien à recopier dans `C:\inciwin\cl_iso`.**

Le champ *Vu par la machine*, dans la barre d'outils, ne sert qu'au cas
où le poste machine voit ce même dossier **sous un autre nom** — un
lecteur mappé `Z:\gravure` là où le poste client emploie
`\\serveur\gravure`. Laissé vide, c'est le chemin réel qui est inscrit.
Ce réglage est mémorisé **par dossier d'export** : un atelier peut viser
deux partages dont un seul est mappé.

En série, chaque pièce a son sous-dossier et le chemin machine suit —
sinon la deuxième pièce désignerait les fichiers de la première.

En interface de programmation, c'est l'argument `machine_iso_dir` de
`engrave.iso.export()` : `None` (défaut) = le dossier d'écriture.

---

## 6. Panneau source laser

Se connecte à la source JPT — port série réel ou **simulation** — et
affiche numéro de série, puissance, fréquence, largeur d'impulsion, LED et
alarmes.

**Aucune commande d'émission n'y est exposée**, délibérément : allumer un
laser de classe 4 reste du ressort du contrôleur machine, qui porte la
chaîne d'interlocks. Seule la coupure est offerte.

---

## 7. Points ouverts

1. Le conflit `T<n>` / `G108` (§4).
2. Le facteur d'échelle de la fréquence côté source série, inféré mais non
   mesuré — sans effet sur l'export ISO, qui reste en hertz comme les
   fichiers d'origine.
3. La conversion d'un texte étiré (`stretch`) reste un étirement
   géométrique, pas une graisse optique : très au-delà de 2×, les pleins
   et les déliés s'écartent de ce que dessinerait une police condensée.

---

## 8. Ordonnancement des trajectoires

Deux cases dans la barre d'outils :

| Case | Effet |
|---|---|
| **Optimiser le parcours** | plus proche voisin avec inversion de polyligne, puis 2-opt borné en temps |
| **Grouper par process** | fusionne les formes de même process avant d'ordonnancer — l'optimisation agit alors **entre** les formes, et le nombre de changements d'outil chute |

Gains mesurés (trajet à vide) :

| Cas | Brut | Ordonné | + groupé |
|---|---:|---:|---:|
| texte hachuré 0,25 mm | 3 365 mm | **323 mm** | 323 mm |
| 12 rectangles alignés | 495 mm | 495 mm | **243 mm** |
| 25 rectangles dispersés | 1 375 mm | 1 375 mm | **414 mm** |
| 8 formes, 2 process alternées | 478 mm | 358 mm | **194 mm** |

Le point délicat, corrigé : chaque passe doit être optimisée **depuis la
position réelle de la tête** à son entrée, pas depuis l'origine. Sans cela
l'optimisation peut dégrader le trajet global au lieu de l'améliorer. Les
tests vérifient qu'aucun cas ne régresse.

Le groupement change l'ordre de gravure — toutes les formes d'une process
passent avant la suivante. C'est presque toujours souhaitable, mais ce
n'est plus l'ordre de création.

---

## 9. Ergonomie

| Geste | Effet |
|---|---|
| **Flèches** | déplacent **toute la sélection** du pas courant (1 mm par défaut) |
| **Ctrl + ↑ / ↓** | change le pas — 0,01 · 0,05 · 0,1 · 0,25 · 0,5 · 1 · 2 · 5 · 10 · 25 mm. Le pas retenu vaut pour toute la session |
| **Maj + flèche** | déplace de dix fois le pas |
| champ *Pas clavier* | saisie directe d'une valeur quelconque |
| **Mode expert** | déverrouille les réglages fins : fréquence au 0,1 kHz sur 1–1300 kHz, impulsion au 1 ns sur 1–65535 ns, puissance au 0,5 % |

`Dupliquer` et `Supprimer` agissent également sur toute la sélection ; la
barre d'état indique le nombre de formes sélectionnées.

La liste des polices énumère **toutes** les polices installées (466 sur le
poste de développement), avec le vrai nom de famille lu dans la table
`name` de chaque fichier, `.ttf`, `.otf` et `.ttc` compris. Le résultat est
mis en cache au premier appel.

---

## 10. Texte multiligne et alignements

Le texte accepte les retours à la ligne. Trois réglages :

| Réglage | Valeurs |
|---|---|
| **Alignement horizontal** | `gauche` · `centré` · `droite` — appliqué **ligne par ligne** dans la largeur du bloc |
| **Alignement vertical** | `haut` · `milieu` · `ligne de base` · `bas` — position du bloc par rapport au point (x, y) |
| **Interligne** | multiple de la hauteur de capitale, 1,4 par défaut |

Les lignes vides comptent : elles occupent leur interligne.

Le centrage horizontal se fait sur la **largeur d'avance** de la ligne, pas
sur son encre. C'est le centrage typographique : il aligne correctement des
lignes entre elles, au prix d'un léger décalage de l'encre égal à la
différence des approches latérales — quelques dixièmes de millimètre.

---

## 11. Champs variables et séries

Un texte peut contenir des champs remplacés au calcul :

| Champ | Valeur |
|---|---|
| `{n}` · `{n:04}` | numéro de série, éventuellement complété par des zéros |
| `{i}` · `{total}` | index de la pièce dans le lot, nombre de pièces |
| `{date}` · `{heure}` | horodatage |
| `{job}` | nom du travail |
| `{{` · `}}` | accolade littérale |

Un champ **inconnu est laissé tel quel** plutôt que de faire échouer le
calcul, et signalé dans le panneau des propriétés : mieux vaut voir
`{client}` à l'écran et le corriger que perdre le document.

Le panneau **Lot et série** porte la quantité, le premier numéro et le pas.
Au-delà d'une pièce, l'export produit **un jeu complet de fichiers par
pièce**, rangé dans `<travail>_p0001`, `_p0002`… avec les champs réévalués.

> Le budget d'optimisation est **total**, réparti entre les pièces et les
> formes. Sans cela le temps de calcul serait proportionnel à la taille de
> la série. Mesuré : 1 pièce 0,4 s · 10 pièces 0,9 s · 50 pièces 3,2 s.

---

## 12. Import DXF

`Ctrl+I`. Lecture par **ezdxf**, aplatissement en polylignes millimétriques.

* **Centrage en 0,0** proposé par défaut, décochable pour conserver les
  coordonnées d'origine du DXF.
* **Un tracé par calque** — dans un DXF de production les calques séparent
  presque toujours marquage et découpe ; chacun peut donc recevoir sa
  propre process. Le dialogue permet de n'en importer qu'une partie.
* **Les blocs sont éclatés**, imbrications comprises.
* **Le texte DXF n'est pas importé.** Un TEXT ou MTEXT renvoie à une police
  AutoCAD absente ; le rendre donnerait autre chose que ce que le
  concepteur a vu. Ces entités sont comptées et signalées, à recréer comme
  texte TauDrive.

> ### ⚠ L'en-tête `$INSUNITS` est souvent faux
> Un fichier d'essai fourni se **déclare en mètres** alors que ses
> coordonnées sont en millimètres : lu tel quel, il mesure 156 639 mm au
> lieu de 156,6. Le dialogue affiche la taille obtenue, signale
> l'incohérence quand elle dépasse le champ, et laisse forcer l'unité.
> **Vérifiez toujours la taille annoncée avant de valider.**

---

## 13. Bibliothèque de process partagée

Les process vivent sur le poste, et s'échangent par un fichier de réglages :
tous les autres récupèrent. C'est ce qui évite que chaque poste ait sa
propre idée des paramètres du laiton.

`outils/extraire_outils.py` reconstitue **72 process réelles** depuis le
magasin `dbpunte.mag` de la machine — voir
[magasin-outils.md](magasin-outils.md). Le fichier `extrait/outils.json`
qu'il produit est directement publiable depuis le panneau *Réseau*.

---

## 14. Gravure en négatif — cadre à creuser

**Toute forme** peut porter un **cadre**, rectangle ou cercle : texte,
tracé importé d'un DXF, rectangle, cercle. Associé à un hachurage, la
matière est enlevée **entre le cadre et le dessin** : celui-ci ressort en
relief.

| Réglage | Effet |
|---|---|
| **Cadre** | `aucun` · `rectangle` · `cercle` |
| **Marge cadre** | distance entre le dessin et le cadre |
| **Largeur / hauteur imposées** | `0` = ajusté au dessin. Pour un cercle, la largeur vaut le diamètre |

Aucun calcul booléen n'est nécessaire : le cadre est simplement placé en
tête de la liste des contours, et la **règle pair-impair** du hachurage
creuse l'anneau entre le cadre et le dessin — contre-formes comprises. Le
trou du « O » d'un texte reste plein, et l'intérieur d'un contour DXF
aussi : creuser autour d'un logo importé est exactement le même problème
que creuser autour de lettres, et c'est pourquoi le cadre appartient à la
forme de base et non au seul texte.

Sans hachurage, seuls les contours sont tracés ; l'interface le signale.

Le cadre suit le redimensionnement F2 : marge et cotes imposées sont
mises à l'échelle avec le dessin, faute de quoi une pièce réduite
garderait sa marge d'origine et le négatif ne serait plus à la cote.

Ordres de grandeur mesurés sur « TAU » en 10 mm, hachure 0,3 mm :

| | longueur gravée |
|---|---:|
| texte seul | 81 mm |
| texte hachuré | 180 mm |
| + cadre rectangle | 724 mm |
| + cadre cercle | 1 198 mm |

---

## 15. Habillage et disposition

`engrave/theme.py` porte la palette et la feuille de style : les panneaux
latéraux prolongent le plan de travail au lieu de trancher avec lui. Les
couleurs d'état sont celles déjà employées ailleurs — accent `#5ac8fa`,
avertissement `#d8b25a`, alarme `#f08080`, succès `#7bc47f`.

Deux problèmes de disposition résolus, tous deux capables de rendre
l'application inutilisable sur un écran ordinaire :

**La fenêtre ne tenait pas à l'écran.** Les propriétés d'un texte comptent
une vingtaine de champs ; leur hauteur naturelle — 838 px — devenait la
hauteur minimale de la fenêtre, qui réclamait alors 1116 px sur un bureau
qui n'en offre que 1009. Chaque panneau est désormais dans une zone
défilable : le minimum est retombé à **624 × 192**.

**Le panneau utile était écrasé par le panneau de surveillance.** Empilés,
`Propriétés` et `Source laser` se partageaient la colonne à parts égales :
la vingtaine de champs se retrouvait dans 174 px pendant que six lignes de
laser en occupaient autant. Les proportions sont fixées au premier
affichage — trois quarts pour les propriétés, un quart pour le laser.

Les formulaires passent le champ sous son libellé quand la place manque
plutôt que de déborder, et les libellés longs ont été raccourcis, le détail
étant repoussé dans les infobulles.

---

## 16. Thèmes, icônes, performances

### Thèmes

Quatre palettes, dans le sélecteur en bout de barre d'outils : **Ardoise**
(sombre), **Atelier** (clair), **Ambre** (sombre chaud), **Contraste élevé**.
Le choix est mémorisé d'une session à l'autre.

Une palette décrit **toute** l'application, plan de travail compris :
changer de thème repeint la grille, le champ de marquage et les tracés en
même temps que les panneaux. Les icônes se redessinent à la nouvelle
couleur.

### Icônes

`engrave/icons.py` dessine les icônes au `QPainter` plutôt que de charger
des fichiers : elles suivent la couleur du thème, restent nettes à toute
résolution et n'ajoutent aucune ressource à embarquer. La corbeille est
teintée en couleur d'alarme, seul geste destructeur de la barre.

### Performances

Le déplacement d'une forme à la souris coûtait **771 ms**. Trois causes,
toutes corrigées :

| Cause | Correctif | Effet |
|---|---|---|
| chaque mouvement relançait un ordonnancement complet (2-opt) | barre d'état temporisée, 2-opt réservé à l'export | — |
| `bounds()` reconstruisait toutes les passes, hachurage compris | emprise calculée sur les seuls contours, que le hachurage ne dépasse jamais | 26,6 → 3,9 ms |
| le hachurage était recalculé à chaque pixel | géométrie mémorisée **hors position** : déplacer ne fait plus qu'une translation | 9,1 → 0,8 ms |

Résultat : **2,55 ms par mouvement**, barre d'état à 8 ms.

Deux défauts découverts en optimisant, et corrigés :

* **`nearest_neighbour` était quadratique.** Remplacé par une recherche sur
  grille régulière : 5 000 polylignes en 109 ms. La première version
  bouclait sans fin sur une géométrie plate — points alignés ou confondus —
  parce que la maille était dimensionnée sur l'*aire* de l'emprise, qui
  vaut alors zéro. Elle l'est maintenant sur le côté. Sept cas dégénérés
  sont couverts par les tests.
* **L'inspecteur pouvait se reconstruire pendant qu'il se construisait**,
  détruisant les widgets manipulés par le code appelant. Réentrance
  bloquée, destruction différée, et pas de reconstruction pour une forme
  déjà affichée.

Le changement de thème passait 2,1 s à repeindre des panneaux déjà
remplacés mais pas encore détruits ; la file de suppressions différées est
vidée d'abord — **130 ms**.

---

## 17. Empaquetage

`TauDrive.spec` produit une distribution autonome — aucun Python requis sur
les postes.

```bash
cd atelier
pyinstaller --clean --noconfirm TauDrive.spec
```

Résultat dans `dist/TauDrive/` : **deux exécutables** partageant un même
dossier `_internal`.

| Fichier | Rôle |
|---|---|
| `TauDrive.exe` | application de gravure, fenêtrée |

Un seul exécutable. La version réduite au convertisseur a sa propre recette :
voir `TauConvert.spec`. Anciennement, le
poste machine, sans fenêtre, pendant que l'opérateur se sert de TauDrive.
`MERGE` met leurs dépendances en commun, le dossier ne pèse donc pas deux
fois le prix.

### Vérifier une construction

Un démarrage sans plantage ne prouve pas qu'un exécutable est complet :
polices, ressources, import DXF et port série peuvent manquer sans que rien
ne le signale au lancement.

```bash
TauDrive.exe --autotest > rapport.txt
```

Douze contrôles : thèmes, ressources, icônes, polices système, construction
de la fenêtre, calcul des trajectoires, export ISO/CLJOB, `ezdxf`, port
série, client laser. À relancer après chaque construction, et sur
le poste cible avant déploiement.

### Deux pièges rencontrés, tous deux résolus

* **`numpy` ne doit pas être exclu.** Les routines accélérées d'`ezdxf`
  sont compilées contre lui ; sans lui l'application ne démarre pas du
  tout. C'est l'auto-test qui l'a révélé — la construction, elle,
  réussissait sans broncher.
* **Les autres liaisons Qt doivent l'être.** `ezdxf` sait dialoguer avec
  PyQt5 comme avec PySide6 et l'entraîne dans l'analyse ; PyInstaller
  refuse d'embarquer deux liaisons Qt et interrompt la construction.

### Chemins et encodage en version figée

* Les ressources sont déballées dans un dossier temporaire ; `resource_dir()`
  lit `sys._MEIPASS` plutôt qu'un chemin relatif au source, qui n'a plus de
  sens une fois empaqueté.
* La console Windows d'un exécutable figé n'est pas en UTF-8 : les flux
  de sortie sont reconfigurés au démarrage, sans quoi l'autotest et les
  conversions en ligne de commande sortent en caractères illisibles.

### Taille

**≈ 170 Mo**, dont l'essentiel est Qt et `numpy`. Les modules PySide6
inutiles — moteur web, 3D, multimédia, QML — sont exclus. Descendre plus
bas demanderait de renoncer à l'import DXF.

---

## 18. Redimensionnement (F2)

**F2** ouvre le dialogue de redimensionnement sur la sélection, quelle
qu'elle soit : rectangle, cercle, texte, tracé DXF, sélection multiple ou
groupe. Quatre champs tenus d'accord entre eux — largeur X, largeur Y,
% X, % Y — et une case **Respecter les proportions** : le champ modifié
commande, les trois autres suivent.

Ce que « mettre à l'échelle » veut dire selon la forme :

| Forme | Effet |
|---|---|
| Rectangle, cercle | les deux cotes sont multipliées |
| Tracé DXF | chaque point est multiplié |
| Texte | `size_mm` porte l'échelle **verticale**, `stretch` la différence entre les deux axes |
| Sélection multiple | chaque membre est mis à l'échelle **et** écarté du centre commun, d'un bloc |

Deux réserves, énoncées aussi dans le dialogue :

* sur une forme **tournée**, une mise à l'échelle **non uniforme**
  s'applique dans les axes propres de la forme, pas dans ceux de l'écran.
  C'est le seul choix qui garde un rectangle rectangle ; l'autre
  convention en ferait un parallélogramme, que le modèle ne représente
  pas. Une mise à l'échelle uniforme reste exacte quelle que soit la
  rotation ;
* une dimension nulle — texte vide, trait strictement horizontal — ne
  peut pas être mise à l'échelle : le champ correspondant est grisé
  plutôt que de diviser par zéro.

---

## 19. Groupes

**Q** groupe la sélection, **S** la dégroupe. On construit
une sélection multiple au **Ctrl+clic** sur le plan de travail, ou par
rectangle de sélection.

Le groupe n'est **pas** une forme conteneur : chaque membre garde sa
process, son entrée dans la liste et sa place dans l'ordre de gravure. Ce
qu'apporte le groupe, c'est que sélectionner un membre les sélectionne
tous — donc le déplacement aux flèches, le redimensionnement F2, la
duplication et la suppression agissent sur l'ensemble.

Ce choix est délibéré : un conteneur aurait imposé une process unique au
groupe, ce qui interdit le cas le plus courant — un contour au marqueur
et un remplissage hachuré qu'on veut déplacer ensemble sans les graver
pareil.

Quelques conséquences utiles :

* grouper une sélection qui contient déjà des groupes les **absorbe** ;
* dupliquer un groupe crée un **nouveau** groupe, pas un ajout à l'ancien ;
* un DXF multi-calques arrive groupé — ses calques ne se désolidarisent
  pas par mégarde — et se dégroupe d'un S ;
* la liste des formes marque chaque groupe d'une pastille (◆ ◇ ◈ …) pour
  les distinguer d'un coup d'œil.

### Combiner et décombiner

**Ctrl+G** *combine* la sélection : elle devient **un seul tracé**, comme un
DXF importé d'un bloc, avec les réglages et la process de la première
forme de la liste. Ses polylignes se remplissent ensemble en pair-impair,
et le cadre, le décalage et l'épaisseur valent pour le tout. Rien ne bouge
sur la plaque. Les textes sont figés comme par *Convertir en tracé* ; les
codes 2D restent à part.

**Ctrl+Maj+G** *décombine* : chaque tracé ou texte sélectionné se sépare en ses
polylignes, groupées — le trou d'un « O » reste un trou. C'est *Séparer
les tracés* appliqué à toute la sélection.

Q et S — grouper, dégrouper — n'agissent que si le **plan de travail**
ou la **liste des formes** a le focus : dans un champ, la lettre se tape
normalement. Ctrl+G, Ctrl+Maj+G et **Alt+W**, qui centre la sélection
dans le champ, valent partout dans la fenêtre.

---

## 20. Gestionnaire de process et mode expert

**Ctrl+M** ouvre le gestionnaire : créer, dupliquer, renommer, supprimer,
réordonner, et revenir aux cinq process relevées sur la machine. La
bibliothèque est enregistrée dans le dossier de configuration de
l'utilisateur (`process.json`) et rechargée au lancement. Deux process
ne peuvent pas porter le même nom — la liste déroulante ne permettrait
plus de les distinguer.

**Fréquence** et **durée d'impulsion** ne sont modifiables qu'en **mode
expert**, déverrouillé par un code (`1664`). Ailleurs — dans l'inspecteur
d'une forme — elles restent **visibles mais en lecture seule** : on doit
pouvoir constater avec quoi on grave sans pouvoir le dérégler d'un coup
de molette.

La raison n'est pas cosmétique : sur une source MOPA, ces deux valeurs
fixent l'énergie par impulsion. Mal choisies, elles dégradent le rendu et,
à forte énergie, la source. Le déverrouillage n'est **jamais** écrit sur
le disque : il vaut pour la session en cours, ce qui est le bon
comportement sur un poste d'atelier partagé.

---

## 21. Onglets, sessions et dossiers d'export

**Onglets.** Plusieurs documents sont ouverts côte à côte, chacun avec
son plan de travail, son historique de trajectoires et son fichier. Un
astérisque marque les modifications non enregistrées ; fermer un onglet
modifié propose d'enregistrer.

**Session.** À la fermeture, TauDrive retient les documents ouverts, la
géométrie de la fenêtre et la disposition des panneaux, et rouvre le tout
au lancement suivant. La géométrie restaurée est vérifiée : une fenêtre
qui retomberait sur un écran désormais absent est ramenée au centre —
sans ce contrôle, elle serait invisible et irrécupérable.

**Documents récents et dossiers d'export.** Le bouton *Récents* liste les
deux. Les entrées dont le fichier ou le dossier a disparu sont écartées
à la lecture, pas conservées comme des liens morts.

**Un dossier par travail.** L'export crée
`<dossier choisi>/<nom du travail>_AAAAMMJJ-HHMMSS/` et y écrit tous les
fichiers du lot. L'horodatage n'est pas décoratif : réexporter après une
correction écraserait sinon des fichiers déjà copiés sur la machine, sans
moyen de savoir lequel est en train de graver.

**Format de document.** `.taudrive`, JSON versionné — le même que celui
rouvert plus tard. Un document enregistré aujourd'hui reste lisible par
une version ultérieure ; l'inverse est refusé explicitement plutôt que
lu de travers.

---

## 22. Codes 2D — DataMatrix et QR Code

**Ctrl+B** pose un code 2D. Deux symbologies, encodées **en Python pur**,
sans dépendance externe : l'application est distribuée figée sur des
postes d'atelier, et une bibliothèque native de plus serait une
bibliothèque de plus à embarquer.

| Réglage | Effet |
|---|---|
| **Symbologie** | DataMatrix (ECC200) ou QR Code |
| **Donnée** | texte encodé — accepte les champs variables (`{n}`, `{date}`…) |
| **Module** | côté du carré élémentaire, en mm |
| **Correction** | QR seulement : L (7 %), M (15 %), Q (25 %), H (30 %) |
| **Silence** | zone de silence, en modules |

Le **nombre** de modules ne se règle pas : il découle de la donnée et de
la symbologie. C'est le côté du module qui fixe la taille du symbole, et
l'inspecteur affiche en permanence ce qu'on obtient — `21 × 21 modules ·
10,50 × 10,50 mm`, zone de silence comprise.

Ce qui est gravé : les modules sombres voisins d'une même ligne sont
**fusionnés en un seul rectangle**, cinq à dix fois moins de contours pour
un dessin identique. La règle pair-impair du hachurage reste correcte, les
rectangles se touchant sans se recouvrir.

Un code se sérialise comme un texte : `PN-{n:05}` produit un symbole
différent par pièce, de taille constante tant que le nombre de caractères
ne change pas.

Une donnée trop longue ne fait pas tomber l'application : le code
disparaît du plan de travail et l'inspecteur affiche la capacité
dépassée.

### Ce qui est couvert

* **DataMatrix ECC200**, symboles carrés de 10×10 à 52×52 modules, soit
  jusqu'à 204 octets. Encodage ASCII avec compression des paires de
  chiffres.
* **QR Code**, mode octet, versions 1 à 10, soit jusqu'à 271 octets au
  niveau L. Les huit masques sont évalués et le meilleur retenu selon le
  score de pénalité de la norme.

Ces plafonds sont très au-delà de ce qu'on marque sur une plaque ; les
tailles supérieures n'ajouteraient que de la surface perdue.

### Comment on sait que c'est juste

`python outils/test_barcode.py` — 40 contrôles, sur deux niveaux.

**Valeurs publiées.** Polynômes générateurs, chaînes d'information de
format et de version, mots de code d'un exemple normatif : ces nombres
viennent des normes, pas de notre code. Une erreur les fait tomber
immédiatement. C'est ainsi qu'a été trouvé le seul vrai piège de
l'exercice : QR et DataMatrix emploient tous deux Reed-Solomon sur
GF(256), mais **pas le même corps ni la même première racine** — QR réduit
modulo 0x11D en partant de alpha⁰, DataMatrix modulo 0x12D en partant de
alpha¹. Un symbole construit avec la mauvaise convention a la bonne
taille, la bonne allure, et reste illisible.

**Relecture.** Un décodeur écrit dans le test relit chaque QR produit : il
retrouve le masque dans la zone d'information, le retire, reparcourt les
modules, désentrelace les blocs et **vérifie les syndromes Reed-Solomon**
avant de rendre le message. Sept cas passent, du plus court au plus long,
accents compris.

---

## 23. Épaisseur du trait

Un passage unique du laser laisse une rayure, pas un trait. Le réglage
**Épaisseur du trait**, présent sur toute forme, élargit le tracé par
passages parallèles de part et d'autre.

| Réglage | Effet |
|---|---|
| **Épaisseur** | largeur visée, en mm. 0 = un seul passage |
| **Écart** | distance entre deux passages. 0 reprend le pas de hachurage de la process, ou 0,05 mm |

L'épaississement s'applique **après** le hachurage : il élargit aussi les
segments de remplissage, ce qui permet de creuser large avec un pas de
hachurage grossier — donc beaucoup moins de trajet à vide.

C'est un épaississement **par passages**, pas un décalage de polygone
exact : sur un angle très fermé, les passages extérieurs se croisent au
lieu de se raccorder proprement. À l'échelle d'un trait de quelques
dixièmes de millimètre l'écart est sans conséquence, et le calcul reste
instantané — ce qu'un décalage exact ne serait pas.

---

## 24. Ce qui a changé dans l'interface

**Menus.** *Fichier* rassemble Nouveau, Ouvrir, Documents récents,
Enregistrer, Enregistrer sous, Exporter, Fermer l'onglet et Quitter.
*Paramètres* rassemble ce qui se règle une fois par poste — mode expert,
optimisation du parcours, groupement par process, thème, gestionnaire de
process. Ce sont des réglages, pas des outils : ils n'encombrent plus la
barre.

**Mode expert.** Ce n'est plus une case cochable à l'infobulle bavarde,
mais une entrée de menu. Elle commande aussi la **visibilité des panneaux
Réseau et Source laser** : connexion machine, état de la source et file
d'attente n'apparaissent qu'en mode expert. Un opérateur qui compose une
plaque n'en a que faire — et un panneau de trop est un panneau où l'on
clique par erreur.

**Colonnes.** Plus aucun plafond de largeur. Les bornes précédentes — 300
à 460 px — empêchaient d'élargir les propriétés pour lire une liste de
polices ou un chemin d'export entier. Le menu *Affichage* permet de
masquer chaque panneau.

**Liste des formes.** Chaque entrée affiche le **numéro d'outil** de sa
process : c'est lui qui part dans l'ISO, et c'est la première chose qu'on
vérifie avant de lancer une plaque. L'infobulle donne la process complète.

**Process d'un groupe.** Modifier la process d'un membre l'applique à tout
le groupe. Un groupe se grave d'un bloc ; lui laisser deux process
obligerait à sélectionner ses membres un par un pour corriger la
puissance, ce que le groupe est précisément censé éviter. Les géométries
restent propres à chaque membre.

**Champs numériques.** Un double-clic — ou la simple prise de focus —
sélectionne la valeur entière : ce qu'on tape la remplace, séparateur
décimal et décimales compris. La virgule du pavé numérique est acceptée
comme le point. La molette n'agit que sur un champ ayant le focus : faire
défiler un panneau ne modifie plus au passage les cotes survolées.

---

## 25. Performances : ce qui coûtait cher

Le groupage d'une sélection nombreuse était lent, et l'application
poissive sur un document chargé. Le profilage a désigné trois coupables,
tous corrigés.

| Cause | Effet mesuré (300 plaques hachurées) |
|---|---|
| `out_of_field()` revectorisait **tous les textes** à chaque rafraîchissement de la barre d'état | 531 ms → **5 ms** par rafraîchissement |
| Le cache de géométrie plafonnait à 128 entrées : un document de 300 formes le vidait en boucle | plus aucun recalcul ; le cache est désormais borné par le **nombre de points**, pas d'entrées |
| Chaque `setSelected` déclenchait l'extension aux groupes et un recalcul complet | sélection totale : 1 500 ms → **6 ms** |

Le groupage et le dégroupage ne reconstruisent plus la liste ni la
sélection : grouper ne change aucune géométrie, seules les étiquettes
bougent. Sur 300 formes, groupage et dégroupage sont passés de plusieurs
centaines de millisecondes à moins de cent, rafraîchissement compris.

Les mesures affichées dans la barre d'état — longueur gravée, trajet à
vide, durée — sont mémorisées avec les passes : un changement de
sélection, qui ne touche à rien, ne les recalcule plus.

---

## 26. Symbologies disponibles

| Symbologie | Portée | Réglages propres |
|---|---|---|
| **DataMatrix ECC200** | carré 10×10 à 52×52, **rectangulaire** 8×18 à 16×48 | forme : carré, rectangulaire, au plus juste |
| **QR Code** | mode octet, versions 1 à 10 | correction L, M, Q, H |
| **Code 39** | 43 caractères, majuscules et ponctuation | clé de contrôle modulo 43, hauteur de barres |
| **EAN-13** | 12 ou 13 chiffres | hauteur de barres |

Le **DataMatrix rectangulaire** n'est pas une curiosité : c'est ce qu'on
emploie sur une plaque étroite, et c'est ce que porte le DXF de
production. À donnée égale il occupe moins de hauteur qu'un carré.

Le Code 39 est **auto-vérifiant** — trois éléments larges sur neuf par
caractère — ce qui suffit à écarter la plupart des lectures fautives ; la
clé modulo 43 reste proposée pour les donneurs d'ordre qui l'exigent.
L'EAN-13 accepte douze chiffres, dont il calcule la clé, ou treize, dont
il vérifie la clé et refuse la saisie si elle est fausse.

Les codes linéaires n'ont qu'une ligne de modules : leur hauteur est un
réglage de gravure — **Haut. barres** — et non une affaire d'encodage.
Leur zone de silence ne s'applique qu'à gauche et à droite.

---

## 27. Plaque codée : code et texte dans leurs cadres

**Ctrl+B**, et rien d'autre : **aucune fenêtre modale**. La plaque est
posée d'un geste, puis tout se règle dans la colonne *Propriétés* —
symbologie, donnée, fenêtre, position, remplissage, et la process
appliquée. Un dialogue de plus obligerait à tout décider avant de rien
voir.

C'est la façon de faire des plaques de production, telle que la montre le
DXF de référence : **deux cadres** réservent la place — l'un pour le
symbole, l'autre pour le numéro en clair — et chacun remplit le sien.

Sélectionner **un ou deux rectangles** avant d'appuyer sur Ctrl+B en
reprend les cotes : la plus grande fenêtre accueille le symbole, la plus
petite le texte. C'est la disposition du DXF, et la seule qui ait un
sens — un code demande bien plus de surface qu'une ligne de caractères.
Sans sélection, ce sont **les cotes de la dernière plaque posée** qui
servent : le cadre ne change pas d'une pièce à l'autre, le redemander
serait une corvée et une occasion de se tromper.

Le résultat est un **groupe** : symbole et texte vont ensemble sur la
pièce. Cliquer l'un ou l'autre sélectionne le groupe — pour le
déplacement et l'échelle — mais l'inspecteur montre **la forme désignée**,
celle sur laquelle on a cliqué. Sans cela il faudrait défaire le groupe
pour régler quoi que ce soit, ce qui lui ôterait tout intérêt.

### La forme du symbole se choisit sur la fenêtre

En mode **au plus juste**, ce n'est pas la plus petite taille qui gagne
mais celle dont les modules restent les plus carrés dans la fenêtre
donnée. Les lecteurs supportent mal les modules déformés, et à capacité
égale le choix est gratuit.

| Fenêtre | Symbole retenu | Module |
|---|---|---|
| 15 × 7 mm | **8 × 18** | 0,833 × 0,875 mm |
| 10 × 10 mm | 12 × 12 | 0,833 × 0,833 mm |
| 30 × 6 mm | 8 × 18 | 1,667 × 0,750 mm |

La première ligne est exactement ce que porte `DataMatrix.dxf` : posé
dans un cadre de 15 × 7 mm, le symbole retrouve seul la forme et le pas
de module de la plaque de production.

### Le texte

Sa hauteur de capitale part de la hauteur de sa fenêtre ; s'il est alors
trop large, elle est réduite dans la même proportion. Le calcul passe par
la géométrie **réellement vectorisée**, pas par la largeur d'avance de la
police : ce sont les contours gravés qui doivent tenir dans le cadre, et
eux seuls. Un texte trop long est réduit, jamais débordé.

---|---|
| **Forme** | `au plus juste` retient la taille qui gaspille le moins de modules, rectangulaire comprise |
| **Retrait** | marge appliquée au cadre avant ajustement |
| **Silence** | zone de silence, comprise dans la fenêtre |
| **Garder les modules carrés** | centre le symbole sans l'étirer, au lieu de remplir |

Un symbole étiré a des modules non carrés — ce que la norme admet et que
les plaques emploient couramment. Le dialogue affiche le rapport
d'étirement et **avertit au-delà de 1,6** : certains lecteurs s'en
accommodent mal, et une fenêtre moins allongée, ou la forme
rectangulaire, donne un meilleur rapport.

Les mêmes réglages restent accessibles ensuite dans l'inspecteur —
*Fenêtre X* et *Fenêtre Y*. Renseignées toutes deux, elles l'emportent
sur le pas de module.

### Ce que vaut cette reconstitution

Le fichier `DataMatrix.dxf` du partage de production a été analysé
module par module : le symbole qu'il porte est un **ECC200 rectangulaire
8 × 18 encodant « B000174 », dessiné dans une fenêtre de 15 × 7 mm**, soit
des modules de 0,8333 × 0,875 mm.

Cette matrice, reconstituée depuis les contours du DXF par
échantillonnage au centre de chaque module, sert de test de
non-régression : `test_barcode.py` vérifie que notre encodeur la
reproduit **à l'identique, module pour module**. C'est la meilleure
référence dont on dispose — elle ne vient ni de notre code ni d'une norme
relue, mais d'un symbole qui grave et se lit en atelier.

---

## 28. Dossiers par défaut

*Paramètres ▸ Dossiers par défaut* fixe un emplacement par usage :
documents TauDrive, export ISO/CLJOB, import DXF.

Laissé vide, un usage reprend le dernier emplacement employé, puis le
dossier personnel.

Un chemin non joignable est **signalé mais accepté après confirmation**.
Un dossier par défaut mort ne se voit sinon qu'au moment d'exporter,
c'est-à-dire au pire moment — d'où l'avertissement. Mais un partage
réseau peut être légitimement hors ligne quand on règle l'application, et
refuser sa saisie obligerait à revenir plus tard : exactement ce qu'on
cherche à éviter.

Ces réglages se posent aussi sans ouvrir l'interface, ce qui sert à
préparer un poste :

```bash
python outils/regler_dossiers.py export "\\DESKTOP-J2DHKP4\TauDrive"
python outils/regler_dossiers.py
```

Le dossier d'export par défaut vient en tête de la liste déroulante de la
barre d'outils, même s'il n'a encore jamais servi.

---

## 29. La process affichée est celle qui sera gravée

La liste *Préréglage* de l'inspecteur affichait « (personnalisée) » même
lorsqu'une process venait d'être choisie dans la bibliothèque : on ne
voyait jamais son propre choix, et rien ne distinguait une process de
production d'une valeur bricolée.

Elle se positionne désormais sur la process en vigueur, et ne retombe sur
« personnalisée » qu'après une modification qui l'écarte réellement de la
bibliothèque. La comparaison porte sur **tous** les champs : deux process
de même nom mais de puissance différente ne sont pas la même, et afficher
le nom de la bibliothèque laisserait croire le contraire.

La liste des formes porte de son côté le numéro d'outil de chaque forme —
voir §24.

---

## 30. Un code se grave plein

Un code n'est **lisible que plein** : un contour de module laisse un
carré vide que le lecteur ne verra pas.

Le remplissage est donc produit par la forme elle-même, module par
module, et **ne dépend pas du hachurage de la process**. Une process de
marquage à hachurage nul donnerait sinon un code parfaitement dessiné et
parfaitement illisible — l'erreur ne se verrait qu'à la lecture de la
première pièce.

| Réglage | Effet |
|---|---|
| **Remplissage** | pas entre deux passages, en mm. 0 = automatique |

L'automatique retient le pas de hachurage de la process s'il est
renseigné, sinon le quart d'un module. Deux passages par module au
minimum : un seul trait laisserait une arête claire au milieu du carré.

Le balayage se fait bande par bande en alternant le sens, si bien que le
trajet à vide reste minime sans qu'aucun ordonnancement n'ait à
intervenir. Sur le symbole de la plaque de référence — 8 × 18 modules
dans 15 × 7 mm — cela donne 205 trajectoires pour 447 mm gravés.

Le hachurage générique de la process n'est **pas** appliqué en plus : son
balayage global traverserait des centaines de rectangles et coûterait
cent fois plus cher pour un résultat identique.

---

## 31. Mise à l'échelle d'un code

| Cas | Comportement |
|---|---|
| Code posé dans une **fenêtre** | la fenêtre suit l'échelle, **axe par axe** — elle est rectangulaire par nature |
| Code **sans fenêtre** | le pas de module suit, en gardant les modules carrés : une demande non uniforme retient la moyenne des deux facteurs |

Un code sans fenêtre doit garder ses modules carrés pour rester lisible ;
un code posé dans une fenêtre est commandé par elle, et la norme admet
des modules rectangulaires — c'est ce que fait la plaque de production.

---

## 32. Onglets et sauvegarde silencieuse

| Geste | Effet |
|---|---|
| **+** au bout de la barre d'onglets | nouvel onglet |
| **double-clic** sur un onglet | le renomme |
| fermeture d'un onglet ou de l'application | **aucune question** |

Renommer un onglet ne change pas qu'une étiquette : c'est le **nom du
travail**, celui qui sert de nom de dossier à l'export et de nom de
fichier proposé à l'enregistrement.

**Rien n'est jamais perdu, et rien n'est jamais demandé.** Ce qui est
ouvert est réécrit en continu dans un instantané de session — deux
secondes et demie après la dernière modification, pas à chaque frappe — et
rouvert tel quel au lancement suivant, **y compris les documents qui
n'ont pas encore de fichier**. Fermer sans enregistrer ne perd donc rien.

L'enregistrement explicite (`Ctrl+S`) reste nécessaire pour produire un
`.taudrive` partageable ou archivable ; il ne l'est plus pour ne rien
perdre.

L'instantané est écrit par fichier temporaire puis remplacement : une
coupure pendant l'écriture laisse l'instantané précédent intact plutôt
qu'un fichier tronqué, qui coûterait tout le travail en cours. Au
démarrage, il prime sur la liste des fichiers ouverts — c'est lui qui
porte les modifications non enregistrées ; un instantané illisible fait
retomber sur les fichiers, sans empêcher le démarrage.

**Seul l'onglet de devant s'ouvre au lancement.** Les autres portent leur
nom dans la barre, mais leur dessin n'est relu qu'au premier clic : avec
plusieurs dessins lourds, la fenêtre paraît en une à deux secondes au
lieu de dix. Le premier clic sur un gros dessin prend le temps de le
poser ; les suivants sont immédiats.

---

## 33. Cadre englobant : la gravure en négatif

Deux gravures sont possibles pour un code, et c'est le **cadre** qui
tranche :

| Cadre | Ce qui est creusé | Ce qui reste |
|---|---|---|
| aucun | les modules sombres | la matière brute autour |
| **rectangle ou cercle** | le fond du cadre | **les modules, en relief** |

C'est la raison d'être du cadre englobant. Sur un métal clair, creuser le
fond donne le meilleur contraste : le symbole ressort en relief poli sur
un fond dépoli.

Le calcul est fait **ligne à ligne**, en retranchant les intervalles
sombres de chaque bande. Le hachurage générique par règle pair-impair
aurait pu servir, mais sur un symbole les modules se touchent par leurs
arêtes par centaines : un balayage global y multiplierait les
intersections coïncidentes, précisément le cas que le pair-impair traite
le moins bien. Ici les intervalles sombres d'une ligne sont connus
exactement, et le complément s'en déduit sans ambiguïté.

> **Un symbole en négatif se lit à l'envers.** Les lecteurs du commerce
> gèrent presque tous ce mode — *reverse video* — mais il vaut mieux le
> vérifier avec le lecteur du client avant de lancer une série, et le
> mentionner sur la gamme.

Sur le symbole de la plaque de référence, le passage en négatif fait
passer la gravure de 447 à 970 mm : le fond est plus grand que les
modules, la pièce reste plus longtemps sous le faisceau.

---

## 34. Préréglages de code

Une plaque ne se règle qu'une fois : symbologie, forme, fenêtre, zone de
silence, remplissage, cadre, épaisseur de trait, fenêtre du texte. Le
même réglage resservira pour toute la série, et pour la suivante.

Un préréglage retient **tout le formulaire** — dix-huit champs — sauf la
position, qui appartient à la plaque et non au réglage : appliquer un
préréglage à un code déjà posé ne le fait pas sauter ailleurs.

La liste *Préréglage*, en tête du panneau d'un code, applique un réglage
enregistré. Le bouton *Préréglages…* ouvre le gestionnaire : enregistrer
le réglage courant, renommer, dupliquer, réordonner, supprimer, revenir
aux réglages d'usine.

Trois préréglages d'usine, repris de la plaque de production :

| Nom | Contenu |
|---|---|
| Plaque 15 × 7 — DataMatrix | fenêtre 15 × 7 mm, texte 8,07 × 1,54 mm |
| Plaque 15 × 7 — négatif encadré | la même, cadre rectangle, marge 1 mm |
| QR 12 × 12 | QR niveau M, silence 4 modules, sans texte |

La bibliothèque vit dans `codes.json`, à côté des process, dans le
dossier de configuration de l'utilisateur.

---

## 35. Saisie : la molette ne modifie plus rien

**Aucune valeur ne change à la molette** — ni un compteur, ni une liste
déroulante. La molette est réservée au défilement des panneaux.

Une cote changée d'un coup de molette ne se voit pas : elle part à la
gravure. Les valeurs se saisissent au clavier, ou se règlent aux flèches
et aux boutons du champ — trois gestes délibérés, contre un accident.

Rappel des autres facilités de saisie (§24) : un double-clic ou la simple
prise de focus sélectionne la valeur entière, et la virgule du pavé
numérique est acceptée comme le point.

---

## 36. Chemins récents

Partout où l'on désigne un dossier, les chemins déjà employés sont
proposés : le dossier d'export dans la barre d'outils, et chacun des
quatre usages du dialogue *Dossiers par défaut*, devenus des listes
modifiables.

Chaque usage tient sa propre liste — documents, export, DXF —
alimentée à l'ouverture, à l'enregistrement, à l'import et à l'export.
Les entrées dont le dossier a disparu sont écartées à la lecture, et le
dossier par défaut vient toujours en tête.

---

## 37. Ce que le cadre change pour un code

Deux corrections récentes, l'une visible, l'autre invisible mais bien
plus grave.

**Le cadre est centré sur le symbole entier.** Il se calait auparavant
sur l'encre — les modules sombres — dont les bords dépendent du hasard :
le coin haut-droit d'un DataMatrix peut être clair, et la marge n'était
alors pas la même des quatre côtés. Elle se compte désormais depuis
l'encombrement de la matrice complète, zone de silence comprise.

**Les arêtes internes ne sont plus tracées.** Le symbole était découpé en
rectangles par bande, ce qui traçait aussi les arêtes que deux modules
sombres superposés partagent. En gravure directe, c'était du trajet
perdu ; **en négatif, c'était une ligne gravée au milieu d'une zone qui
devait rester intacte**, coupant en deux ce qui devait rester d'un seul
tenant — et abîmant la lecture. Seules les frontières réelles entre zone
gravée et zone épargnée sont maintenant tracées, fusionnées par tronçons
contigus.

---

## 38. Passes et profondeur

Une process à plusieurs passages grave **chaque passage un cran plus
bas**. Le comportement est repris des fichiers de la machine : un travail
à trois passes y descend de `Z0` à `Z-0.004673` puis `Z-0.009346`, en se
relevant à `Z-0.001` entre deux tracés.

Deux façons de le régler, au choix de la process :

| Réglage | Ce qu'on saisit |
|---|---|
| **pas imposé** | la descente entre deux passes — 4,673 µm sur la machine |
| **profondeur totale** | la cote finale visée ; le pas s'en déduit |

Une process qui ne renseigne rien garde le comportement précédent :
toutes les passes en surface. Le gestionnaire affiche les cotes obtenues,
un pas ne se lisant pas de tête.

Dans ce dialecte, `Z` n'est pas la position de l'axe physique — celui-ci
se commande à part — mais l'état de l'outil : `0` posé, `-0.001` levé, et
plus négatif à mesure que les passes s'enfoncent.

---

## 39. Chemin machine : un modèle, plus un champ

Le champ *Vu par la machine* a quitté la barre d'outils. C'est un réglage
de poste, pas une décision de tous les jours : il est devenu un
**modèle**, dans *Paramètres ▸ Dossiers par défaut*.

```
C:\TauDrive\{date} {job}
```

| Champ | Valeur |
|---|---|
| `{job}` | nom de l'onglet, assaini |
| `{date}` | date du jour, `aammjj` |
| `{time}` | heure, `hhmmss` |
| `{year}` | année sur quatre chiffres |

Le dialogue montre en permanence le chemin obtenu — un modèle ne se relit
pas de tête. Un champ mal tapé est laissé tel quel dans le chemin plutôt
que de faire échouer l'export : l'erreur doit se voir, pas exploser au
mauvais moment.

**Le dossier d'export porte le dernier segment du modèle.** Les deux ne
peuvent donc pas diverger : le CLJOB désigne toujours le dossier où les
fichiers viennent d'être écrits, vu depuis la machine. Sur l'installation
en place, `\DESKTOP-J2DHKP4\TauDrive` et `C:\TauDrive` sont le même
dossier — le poste client écrit sur le partage, la machine lit en local.

---

## 40. Les cotes de la plaque de production

Le DXF de référence a été mesuré entité par entité ; ces cotes sont
maintenant celles que TauDrive emploie par défaut, et elles sont
verrouillées par des contrôles.

| | Cote relevée |
|---|---|
| Symbole | **15 × 7 mm**, DataMatrix ECC200 rectangulaire 8 × 18 |
| Module | **0,8333 × 0,875 mm** |
| Cadre englobant | **16 × 8 mm**, soit une marge de **0,5 mm** |
| Fenêtre du texte | **8,071 × 1,538 mm** |
| Centre du texte | **X −15,07 · Y −3,73** par rapport au centre du code |

L'écart du texte est mémorisé **en relatif** : poser la même plaque
ailleurs sur le champ conserve l'implantation, et un préréglage la
transporte d'un travail à l'autre. C'est la disposition des pièces déjà
en service — il n'y a aucune raison de la réinventer à chaque fois.

### Ce que vaut la vérification du symbole

Deux mesures indépendantes, toutes deux contre le DXF de production :

1. **module par module** — les huit lignes de la matrice sont identiques,
   0 différence sur 8 ;
2. **par échantillonnage géométrique** — 5 184 points répartis sur les 144
   modules, testés par la règle pair-impair sur les contours du DXF :
   **aucun écart**. Même emprise, même pas de module.

Un piège s'est présenté en route, et il vaut d'être noté : le DXF décrit
le symbole par **six polylignes**, dont cinq sont des *trous* — des zones
claires enfermées dans une zone sombre. Les remplir toutes en plein, sans
appliquer la règle pair-impair entre elles, donne une image fausse à un
endroit précis. C'est une image de contrôle qui s'est ainsi trompée, pas
le générateur : la vérification par échantillonnage, elle, applique bien
la règle et ne trouve rien.

---

## 41. Le motif qui débordait du cadre

Sur un code encadré, la première ligne de modules — l'**horloge** d'un
DataMatrix — se retrouvait reproduite dans la bande de marge, au-dessus du
symbole. Le cadre portait ainsi un faux motif alterné qui n'appartenait
pas au code.

La cause tient à une ligne. Le remplissage en négatif retranche, de chaque
bande de balayage, les intervalles sombres de la ligne de modules
traversée :

```python
row = int((half_h - yy) / my)      # avant
row = math.floor((half_h - yy) / my)   # après
```

Au-dessus du symbole, `half_h - yy` est **négatif**, et `int()` tronque
vers zéro : il rendait `0`, c'est-à-dire la première ligne du symbole. La
marge haute épargnait donc les modules de cette ligne au lieu d'être
gravée d'un seul tenant. `floor` rend `-1`, hors de la matrice, et la
bande est gravée entière.

La marge basse n'était pas touchée : l'indice y dépasse le nombre de
lignes et le contrôle de bornes l'écartait déjà.

Un contrôle verrouille désormais le comportement des deux côtés : une
bande de marge doit produire **un seul trait, couvrant toute la largeur du
cadre**.

---

## 42. Nb_passe et Zpasse

Le magasin d'outils de la machine porte toujours ces deux champs à côté
des paramètres laser. TauDrive les reprend sous les mêmes noms :

| Champ | Rôle |
|---|---|
| **Nb passes** | `Nb_passe` — nombre de passages de la process |
| **Profondeur / passe** | `Zpasse` — descente entre deux passes |

`Zpasse` **n'est jamais nul par défaut** : sa valeur d'usine est celle
relevée dans les fichiers ISO de la machine, **4,673 µm**. Une process à
un seul passage n'en subit aucun effet ; une process à trois passages
grave à `Z0`, `Z-0.004673`, `Z-0.009346`, en se relevant à `Z-0.001`
entre les tracés.

Le second mode — *profondeur totale visée* — reste disponible : il calcule
`Zpasse` à partir de la cote finale et du nombre de passes, sans changer
ce qui est écrit dans l'ISO.

---

## 43. Hors réseau : l'application démarre, l'historique reste

Débranché du réseau, TauDrive ne démarrait plus. La cause n'était pas une
erreur mais une **attente** : interroger un chemin réseau injoignable
bloque jusqu'à l'expiration du délai SMB — une vingtaine de secondes — et
la fenêtre en posait huit dans son constructeur. Le dossier d'export par
défaut, les dossiers récents, les documents de la dernière session :
chacun coûtait son délai avant que rien ne s'affiche.

Plus grave, ces mêmes contrôles **effaçaient l'historique**. Les listes
filtraient sur l'existence du chemin, et la réécriture qui suivait
supprimait définitivement ce qui n'avait pas répondu. Une seule
utilisation hors réseau perdait tous les chemins de partage.

### Ce qui a changé

Toute question posée au système de fichiers passe par une sonde bornée :

```python
session.reachable(chemin)      # 0,6 s au plus, résultat mémorisé
```

Elle tourne dans un fil de discussion à part, et rend `False` si le chemin
n'a pas répondu dans le délai. Le résultat est retenu pour la session, si
bien qu'un partage absent n'est sondé qu'une fois.

**Aucune liste ne filtre plus sur l'existence.** Un chemin injoignable
reste dans l'historique, marqué *hors ligne* dans les menus, et redevient
utilisable dès que le partage revient — `session.forget_reachability()`
force une nouvelle sonde.

Mesures, tous chemins injoignables :

| | Avant | Après |
|---|---:|---:|
| Construction de la fenêtre | plusieurs minutes | **0,13 s** |
| Documents récents conservés | 0 | **tous** |
| Dossiers d'export conservés | 0 | **tous** |

Ce que voit l'opérateur : les entrées hors ligne restent listées mais
grisées ; l'export refuse poliment et propose de choisir un autre dossier,
sans rien effacer ; un document de session absent laisse un onglet vierge
au lieu d'empêcher le démarrage.

`outils/test_session.py` verrouille l'ensemble — 18 contrôles, sur un
partage volontairement inexistant.

---

## 44. Le bouton « nouvel onglet »

Il vit dans le coin de la barre d'onglets, donc **hors de toute barre
d'outils** : la feuille de style du thème, qui ne vise que
`QToolBar QToolButton`, ne l'atteignait pas. Il restait plat, sans fond ni
bordure ni survol — pratiquement invisible sur les thèmes sombres.

Il porte maintenant sa propre **icône vectorielle** — une croix épaisse,
teintée par le thème comme les autres — et son propre style : fond de
panneau, bordure, coins arrondis, surbrillance au survol et accentuation
au clic. 44 × 32 px, curseur de main. L'icône se re-teinte à chaque
changement de thème, comme celles de la barre d'outils.

---

## 45. La process passe en colonne 1

La process laser a quitté la colonne des propriétés pour se placer **sous
la liste des formes**, dans la première colonne. C'est ce qu'on vérifie
juste avant de lancer une plaque, et cela se lit désormais dans la même
colonne que la forme concernée : on désigne une forme dans la liste, sa
process est immédiatement au-dessous. La colonne des propriétés reste à
la géométrie.

Le panneau porte aussi les deux champs du magasin d'outils — **Nb passes**
et **Profondeur / passe** — avec les cotes obtenues affichées en clair :

```
3 passes de 4,673 µm — Z -0.0000 · -0.0047 · -0.0093
```

Techniquement, l'inspecteur a été scindé en deux composants indépendants
qui reçoivent la même forme et signalent leurs modifications de la même
façon. Le seul lien restant est l'avertissement « cadre sans hachurage »,
qui lit maintenant le pas sur la process elle-même plutôt que sur un
champ d'interface.

---

## 46. Le bouton « nouvel onglet » suit le dernier onglet

Il était widget de coin : plaqué au bord droit de la fenêtre, à l'autre
bout de l'écran quand deux onglets seulement étaient ouverts. Il est
maintenant **collé à quatre pixels du dernier onglet**, et se replace à
chaque ajout, fermeture, déplacement d'onglet ou redimensionnement.

La barre d'onglets est bornée pour lui laisser sa place : sans cette
réserve, des onglets nombreux occuperaient toute la largeur et le bouton
viendrait se poser sur le dernier. Quand les onglets débordent, Qt
affiche ses flèches de défilement — le comportement attendu — et le
bouton reste au même endroit.

---

## 47. F2 positionne aussi le centre

Redimensionner et placer sont le même geste dans la pratique : on ajuste
une plaque à sa fenêtre, puis on la met où elle doit aller. Le dialogue
**F2** propose donc, sous les cotes, une case *Positionner le centre* et
deux champs X et Y.

Le centre affiché est celui de l'**emprise commune** de la sélection,
rotation comprise — la même référence que les dimensions affichées juste
au-dessus. Les positions relatives des formes entre elles ne changent
pas : le groupe se déplace d'un bloc.

L'ordre des opérations compte, et il est fixé : **mise à l'échelle
d'abord, autour du centre courant ; déplacement ensuite**, jusqu'à la
cote demandée. L'ordre inverse ferait dériver le centre pendant la mise à
l'échelle, et la cote finale serait fausse.

La case décochée, rien ne bouge — le dialogue se comporte exactement
comme avant.

---

## 48. Exports répétés du même travail

Un travail s'exporte souvent plusieurs fois : une correction, un essai,
une seconde matière. Le modèle de chemin donnant chaque fois le même nom
de dossier, le second export **écrasait le premier** — y compris des
fichiers déjà copiés sur la machine, sans moyen de savoir lequel gravait.

*Paramètres ▸ Exports répétés* offre trois conduites :

| Réglage | Effet |
|---|---|
| **Numéroter automatiquement** (défaut) | `260818 plaque`, puis `-02`, `-03`… Aucun écrasement, aucune question |
| **Demander un nom** | un nom est demandé à chaque export, pré-rempli avec le rang suivant |
| **Écraser** | l'ancien export est remplacé — à ne choisir que si rien n'est copié ailleurs |

Le rang porte sur le **dossier**, jamais sur les fichiers : les ISO et le
CLJOB gardent le nom du travail, et le CLJOB continue de désigner ses
propres fichiers dans son propre dossier. Le chemin vu par la machine
suit le nom réellement retenu — après une numérotation, il pointe bien
sur `…-02`.

---

## 49. Liste des formes : trois boutons par ligne

Chaque ligne porte, à droite de son nom et de son numéro d'outil :

| Bouton | Effet |
|---|---|
| **œil** | masque ou réaffiche la forme |
| **dupliquer** | copie la forme |
| **supprimer** | la retire |

Les chercher dans la barre d'outils obligeait à sélectionner d'abord,
viser ensuite. Ici le geste porte sur la ligne qu'on regarde.

### Ce que « masqué » veut dire

**Une forme masquée n'est ni affichée ni gravée.** C'est le seul sens
utile sur une machine : masquer un élément qu'on graverait quand même
reviendrait à marquer une pièce avec quelque chose d'invisible à l'écran.

Pour que ce choix ne se retourne jamais contre l'opérateur, trois
garde-fous : le nom est **grisé et en italique** dans la liste, la barre
d'état affiche en permanence `n masquée(s), non gravée(s)`, et une forme
masquée **ne déclenche plus l'alerte de dépassement du champ** — elle ne
part pas à la gravure, elle n'a pas à alerter.

L'œil agit sur **tout le groupe** : un groupe gravé à moitié n'aurait pas
de sens, le symbole partirait sans son texte lisible.

---

## 50. Refonte des champs de saisie

Un poste de gravure se règle au clavier. Les compteurs de Qt vont dans
l'autre sens : ils poussent aux flèches, collent l'unité au chiffre et
imposent un nombre de décimales fixe.

| | Avant | Après |
|---|---|---|
| Flèches | présentes | **aucune** — clavier seulement |
| Unité | dans le texte saisi | **à l'extérieur**, en gris |
| Décimales | fixes | **ajustées à la valeur** |

Le troisième point n'était pas cosmétique. À trois décimales fixes, une
profondeur de passe de 0,004673 mm s'affichait **0,005** : la valeur
stockée était juste, celle qu'on lisait était fausse. Les champs gardent
six décimales en interne et n'en montrent que ce que la valeur demande —
`15` reste `15`, `0,004673` reste `0,004673`.

L'unité sortie du champ ne se sélectionne plus, ne s'efface plus et ne
gêne plus la saisie. Le reste ne change pas : double-clic ou prise de
focus sélectionne tout, la virgule du pavé numérique vaut le point, la
molette ne modifie jamais rien.

---

## 51. Process par matière

Douze process s'ajoutent aux cinq relevés machine. **Leurs paramètres
laser ne sont pas inventés** : ils viennent du magasin d'outils de la
machine, `dbpunte.mag`, dont les cent outils ont été relevés.

| Process | Outil d'origine |
|---|---|
| Laiton — gravure / satinage | T6 / T7 |
| Aluminium — gravure / satinage | T8 / T9 |
| Acier — gravure | T88 |
| Acier trempé — gravure | T60 (Steel Z160) |
| Inox — gravure | T10 |
| Découpe 0,5 mm, évidement 1 mm | T6 (laiton), T12 (inox découpe) |

### Ce qui demande une validation sur chute

Deux choses ne viennent pas de la machine, et il faut le savoir :

* **le cuir.** Aucun outil du magasin ne le concerne. Une source fibre
  n'est d'ailleurs pas l'outil habituel du cuir — un CO₂ l'est. Les
  valeurs proposées sont volontairement basses, et la process porte
  « (à valider) » dans son nom ;
* **les profondeurs.** Le nombre de passes découle d'un enlèvement
  supposé de 5 µm par passe — ordre de grandeur cohérent avec les
  4,673 µm relevés dans les fichiers de la machine, mais qui dépend de la
  matière, de l'état de surface et de la focalisation.

Une découpe de 0,5 mm demande **cent passes** à une source de 30 W, un
évidement de 1 mm en demande deux cents. C'est long, et l'estimation de
durée affichée dans la barre d'état le dit avant de lancer. Ces process
sont un **point de départ**, à confirmer sur une chute avant toute série.

---

## 52. Distribution sans code source

`dist/TauDrive/` ne contient **pas un seul fichier `.py`**. Les modules
sont compilés et rangés dans l'archive interne de l'exécutable ; ni
source, ni commentaire, ni nom de classe n'y sont lisibles. `optimize=1`
retire en outre les assertions du bytecode.

Pourquoi pas `optimize=2`, qui aurait aussi retiré les docstrings :
**numpy en a besoin à l'import**. Son `add_docstring` refuse `None` et
l'application ne démarrait plus du tout. Le gain aurait été mince, le
défaut total — c'est le genre de réglage qui ne se voit qu'à l'exécution
de l'exécutable figé, jamais en développement.

> **Ce que cela protège, et ce que cela ne protège pas.** Déployer
> l'exécutable ne donne aucun accès au dépôt, et rien de lisible n'y
> traîne. Mais un bytecode reste décompilable par qui s'en donne la
> peine : c'est une barrière de distribution, pas un secret industriel.
> Si le code devait être réellement protégé, il faudrait le sortir de
> l'exécutable — service distant ou composant natif signé — et cela se
> décide avec le client, pas dans une process d'empaquetage.

---

## 53. Annuler et refaire

Ctrl+Z et Ctrl+Y, propres à chaque onglet.

L'historique retient des **instantanés du document entier**, sous la même
forme que l'enregistrement, plutôt qu'un journal d'opérations inverses.
C'est plus simple, et surtout plus sûr : rien ne peut se désynchroniser
entre ce qui a été fait et ce qui est censé le défaire. Un document de
gravure pèse quelques kilo-octets ; le coût est sans commune mesure avec
le risque.

Les instantanés sont **regroupés dans le temps** (600 ms) : un déplacement
à la souris produit des dizaines de modifications, qui doivent se défaire
d'un seul coup et non pixel par pixel. La pile retient 60 états ; une
action neuve abandonne la branche refaisable.

Un piège s'y cachait : le rechargement provoqué par un « annuler » passe
par le même chemin qu'une modification, et reprogrammait donc un
instantané. Le « refaire » suivant le posait avant de se déplacer, ce qui
**coupait la branche qu'il voulait justement parcourir** — annuler puis
refaire ne rendait rien. Une garde marque désormais la restitution pour ce
qu'elle est : remettre un état en place n'est pas le modifier.

---

## 54. Vérification avant export

Le dernier moment où une erreur coûte encore zéro. Au moment d'exporter,
un récapitulatif du travail **tel qu'il partira** :

| Rubrique | Contenu |
|---|---|
| Formes | total, dont masquées |
| Passes | nombre de passes réellement écrites |
| Longueur gravée | laser actif, en mm |
| Déplacements à vide | trajet entre les tracés |
| Durée estimée | curseur propagé d'une passe à la suivante |
| Process employées | par numéro d'outil, avec le nombre de passes |
| Destination | dossier d'écriture **et** chemin vu par la machine |

Les trajectoires y sont construites **exactement comme à l'export** : même
ordonnancement, même regroupement par process. Un contrôle qui mesurerait
autre chose que ce qui part ne servirait à rien.

### Ce qui est signalé

**Bloquant** — dépassement de champ, travail vide, dossier de destination
injoignable.

**Attention** — formes masquées ; un même numéro d'outil appelé avec deux
jeux de paramètres différents ; une process à 0 % de puissance.

Le deuxième cas mérite un mot : **l'ISO n'emporte que le numéro d'outil**,
pas les paramètres. Dupliquer une process, en changer la puissance et
oublier de changer son `T` donne un travail qui grave deux fois la même
chose — la machine applique ce que porte son magasin. Rien dans le dessin
ne le laisse voir.

### Ce qui n'est pas fait

Le contrôle **ne refuse jamais d'exporter**. La décision reste à
l'opérateur, qui voit la matière et la pièce ; un contrôle qui bloque finit
contourné, et un contournement s'apprend une fois pour toutes. Seul le
bouton par défaut change : quand un point bloquant est présent, c'est
« Revenir au dessin » qui a le focus, pour qu'un « Entrée » machinal ne
lance pas un travail hors champ.

Réglable dans *Paramètres ▸ Vérifier avant l'export*, actif par défaut, et
désactivable depuis le dialogue lui-même.

---

## 55. Coupon d'essai

La façon normale de valider une process sur une matière : graver la même
géométrie plusieurs fois, en ne changeant qu'un paramètre à la fois, et
lire le résultat à l'œil sur une chute.

*Coupon…* (Ctrl+Maj+C) produit une **grille** : un paramètre varie en X,
un autre en Y, chaque case porte sa propre process, et les valeurs sont
**gravées à côté**. Sans ces étiquettes, une chute retrouvée trois semaines
plus tard ne dit plus rien.

Paramètres pouvant varier : puissance, vitesse, fréquence, durée
d'impulsion, pas de hachure, nombre de passes, profondeur visée. Un axe
peut être neutralisé pour n'en faire varier qu'un seul.

### Trois détails qui font la différence

**Les valeurs sont arrondies à un pas utilisable** — 500 mm/min sur les
vitesses, 0,5 % sur les puissances, 0,005 mm sur les hachures. Une
répartition brute donnait « 93 333,3333 mm/min » : illisible sur la pièce,
et personne ne la ressaisira dans une process.

**Les bornes proposées encadrent la process choisie.** Offrir 20…100 % de
puissance quand la process en emploie 12 fait perdre le premier coupon :
les valeurs utiles sont autour du point de fonctionnement connu.

**Les étiquettes gardent l'outil de la process d'essai**, mais à puissance
réduite, sans hachurage et en une passe. Elles doivent se lire, pas
creuser — et changer d'outil au milieu d'un coupon coûterait des
changements inutiles.

Le coupon est posé **dans son propre onglet**, groupé : il occupe tout le
champ, porte vingt process différentes et se jette après lecture. Il n'a
rien à faire au milieu d'un travail de production. Son emprise est
annoncée avant génération, et comparée au champ de marquage.

---

## 56. L'interface parle français, Qt compris

Les boutons standards des dialogues, les menus contextuels de saisie et
les messages de fichier viennent de Qt, pas de TauDrive : sans traduction
installée, une application entièrement rédigée en français répond « OK » et
« Cancel ». La traduction livrée avec Qt (`qtbase_fr.qm`) est chargée au
démarrage et embarquée dans la distribution. Son absence n'empêche pas de
démarrer.

---

## 57. Dix-neuf thèmes, vérifiés au calcul

Onze sombres, huit clairs. Le nombre n'est pas gratuit : un atelier n'a
pas l'éclairage d'un bureau, un écran n'a pas le rendu d'un autre, et
l'opérateur qui passe la journée devant est seul juge de ce qu'il
supporte.

**Sombres** — Ardoise, Ambre, Contraste élevé, Nuit, Graphite, Forêt,
Prune, Cuivre, Acier, Carbone, Bleu de calque.

**Clairs** — Atelier, Papier, Lin, Craie, Azur, Menthe, Sable, Contraste
élevé (clair).

Le menu les sépare en deux blocs, sombres puis clairs : c'est le premier
tri que fait l'œil devant un écran d'atelier, avant même de lire les noms.

### Le contraste ne se juge pas à l'œil

Dix-neuf palettes de dix-neuf couleurs, cela fait 361 valeurs. Les
relire une à une sur un écran ne prouve rien : la même couleur passe ou
ne passe pas selon la dalle, l'angle et la lumière de la pièce.

Le contrôle automatique calcule donc le **rapport de contraste WCAG** de
chaque palette et refuse celles qui tombent sous les seuils :

| Paire | Seuil | Pire cas observé |
|---|---:|---:|
| texte sur panneau | 7:1 | 11,8:1 |
| texte atténué sur panneau | 3:1 | 5,2:1 |
| accent sur panneau | 3:1 | 4,8:1 |
| tracé sur canvas | 4,5:1 | 12,6:1 |
| alarme sur panneau | 3:1 | 5,7:1 |

Un thème joli mais illisible ferait rater une cote. Le seuil du texte est
volontairement au niveau AAA (7:1) et non AA (4,5:1) : on lit ces
panneaux toute la journée, debout, sous un éclairage d'atelier.

Une palette repeint **aussi le plan de travail** — canvas, grille, limite
de champ, axes, tracés. Sans cela le canvas resterait sombre au milieu
d'un thème clair.

---

## 58. Ce que le mode simple cache vraiment

Trois panneaux sont réservés au mode expert : **Source laser**, **Réseau**
et **Lot et série**. Un opérateur qui compose une plaque n'a que faire de
l'état de la source ni de la numérotation de
série — et un panneau de trop est un panneau où l'on clique par erreur.

Deux détails qui rendaient le masquage illusoire ont été corrigés.

**L'entrée du menu *Affichage* disparaît avec le panneau.** La laisser
revenait à offrir le panneau d'un clic tout en prétendant l'avoir retiré.

**Le masquage s'applique après la restauration de session.** Il venait
avant : `restoreState` remettait ensuite les panneaux tels qu'ils étaient
à la fermeture, si bien qu'un panneau expert ouvert en dernier ressortait
en mode simple au démarrage suivant. L'ordre compte.

### Aucune infobulle ne nomme le mode expert

Les champs *fréquence* et *durée d'impulsion* restent **visibles** en mode
simple, en lecture seule : on doit pouvoir constater avec quoi on grave
sans pouvoir le dérégler. Ils portaient une infobulle « Lecture seule : le
mode expert est verrouillé » — qui annonçait l'existence du mode à
exactement les gens qui n'ont pas à le connaître. Elle est retirée. Le
champ grisé dit déjà qu'il ne se règle pas ici.

---

## 59. Le menu « ? »

Version, machine visée, contact. Et un rappel qui a sa place là plus que
partout ailleurs : **TauDrive ne commande aucune émission laser**, le tir
reste au contrôleur de la machine qui porte la chaîne de sécurité.

Le contact est aussi proposé en entrée de menu, qui le copie dans le
presse-papiers — sur un poste d'atelier sans client de messagerie
configuré, un `mailto:` ne mène nulle part.

---

## 60. Cent vingt fenêtres invisibles par ouverture de panneau

Le journal se remplissait de :

```
QWindowsWindow::setGeometry: Unable to set geometry 34x16+640+276
on QWidgetWindow/"QLabelClassWindow". Resulting geometry: 120x16
```

La cause tenait à trois lignes dans le composant de saisie. L'étiquette
d'unité — le « mm » posé à droite du champ — était construite **sans
parent**, puis rendue visible, puis seulement ajoutée à la disposition :

```python
self._unit = QLabel(unit)          # sans parent
self._unit.setVisible(bool(unit))  # → devient une FENÊTRE
self._unit.setMinimumWidth(34)     # Windows refuse : minimum 120 px
row.addWidget(self._unit)          # trop tard
```

Un widget sans parent qu'on rend visible est une fenêtre de premier
niveau. Qt lui créait donc un vrai *window handle*, Windows refusait ses
34 px de large et le ramenait à 120, et l'étiquette redevenait un simple
enfant à la ligne suivante — après quoi la fenêtre était détruite.

Le tout était invisible à l'usage : aucun scintillement, aucun ralenti
mesurable. Seulement des dizaines de fenêtres natives créées et détruites
à chaque ouverture d'un panneau de propriétés, et un journal illisible qui
noyait les vrais messages.

Le correctif tient en un argument — `QLabel(unit, self)` — et le contrôle
automatique vérifie désormais qu'une étiquette d'unité n'est jamais une
fenêtre.

> **La leçon générale.** En Qt, `setVisible(True)` sur un widget sans
> parent ne fait pas ce qu'on croit. Donner le parent à la construction
> coûte cinq caractères ; le laisser à `addWidget` ouvre une fenêtre entre
> les deux.

---

## 61. Le coupon exporté que la machine refusait

Le premier coupon réellement exporté — 84 fichiers, 25 cases — a mis au
jour deux défauts de l'export, qu'aucune plaque ordinaire n'avait révélés.

### Des octets que la machine n'écrit jamais

Les fichiers produits par la machine sont **en ASCII pur**. Vérification
faite sur les sept `.ISO` et le `.CLJOB` livrés : **zéro octet au-dessus
de 127**, sans exception.

Les nôtres en étaient pleins. Les 85 fichiers du coupon, sans exception
non plus :

| Fichier | Octets hors ASCII | Origine |
|---|---|---|
| `.ISO` | `0xB7` | le `·` du nom de process, écrit en latin-1 |
| `.CLJOB` | `0xC3 0xA9` | le `é` du nom de travail, écrit en UTF-8 |

Deux encodages différents dans le même travail, et aucun des deux
correspondant à ce que la machine produit. Le nom d'une process
« Laiton — gravure · Puissance 20 % » suffisait à en semer partout.

Tout ce qui part à la machine est désormais **translittéré en ASCII** :
noms de process, nom du travail, commentaires, et jusqu'aux **noms de
dossiers**, qui se retrouvent dans le chemin que le CLJOB donne à ClTerm.
Le fichier ISO est écrit avec l'encodeur `ascii` et non `latin1` : une
régression lève à l'écriture au lieu de se découvrir trois semaines plus
tard devant la machine.

### Un commentaire coupé au milieu d'un mot

```
T62 (Balayage Pz0.1 - Profondeur 0.02mm ? Vit,STELO: 6.000, ...)
```

Le nom de process était tronqué à quarante caractères **au caractère
près**, ce qui laissait « Vit » — début de « Vitesse » — collé au
`,STELO:` qui suit. Impossible, en lisant le fichier, de savoir si c'est
un mot coupé ou un nom d'outil.

La coupe se fait maintenant sur une frontière de mot, sans remonter
au-delà de la moitié de la limite : mieux vaut couper net que de ne garder
qu'un mot isolé là où il y avait une phrase.

> **Ce qui n'était pas en cause.** Le `G108 P… I…` que nous émettons est
> bien un code Cielle : il figure dans `clterm.exe` et dans les propres
> `EASY_LASER_Z0003_2.ISO` et `Z0004` de la machine. Le premier fichier
> auquel je l'avais comparé n'en contenait simplement pas.

---

## 62. Un coupon s'édite après génération

Un coupon est **groupé** : vingt-cinq cases plus leurs étiquettes se
déplacent, se redimensionnent et se masquent d'un bloc. C'est ce qu'on
veut.

Mais la règle du groupe voulait aussi que **la process éditée s'étende à
tous les membres** — pensée pour la plaque codée, dont le symbole et le
texte se règlent ensemble. Appliquée à un coupon, elle effaçait les
vingt-cinq process en un clic : toucher une case pour ajuster sa
puissance ramenait les vingt-quatre autres à la même valeur. Le coupon
perdait son objet au premier réglage.

### La règle corrigée

> On propage la process aux autres membres **tant qu'ils partagent une
> seule et même process**.

Elle se lit sur l'état courant du groupe, sans rien mémoriser :

| Groupe | Process des autres membres | Propagation |
|---|---|---|
| plaque codée : symbole + texte | une seule | **oui** — un geste règle les deux |
| coupon : 25 cases + étiquettes | plusieurs | **non** — chaque case garde la sienne |

Une plaque codée continue donc de se régler d'un geste, et un coupon
s'édite case par case. Aucun réglage, aucune option : la structure du
groupe dit déjà ce qu'il faut faire.

### Ce qui est visible

Chaque case porte son nom dans la liste des formes — `case 0.02mm /
40000mm/min` — et son numéro d'outil. La cliquer ouvre sa process dans la
colonne 1 et ses propriétés en colonne 3. Ce qui a été gravé se relit donc
dans le document, sans avoir à rouvrir le dialogue.

### Et le dialogue rouvre sur les réglages précédents

Un essai se fait rarement en une fois : la deuxième plaque affine la
première. Process de départ, axes, bornes, nombre de valeurs, taille de
case, écart et hachurage sont retenus d'un coupon à l'autre — ressaisir
six champs entre deux essais fait perdre le fil de ce qu'on cherchait.

---

## 63. Le refus silencieux : trois écarts au modèle machine

Symptôme : ClTerm **refuse de simuler et de graver un coupon, sans un
message**, alors que les mêmes formes créées à la main passent.

Aucune erreur à lire, donc rien à corriger d'après un message. La seule
méthode disponible : comparer, caractère par caractère, un export qui
grave et un export qui ne grave pas. Trois écarts en sont sortis — et
tous trois portent sur ce que TauDrive écrivait **au-delà** de ce que la
machine écrit elle-même.

### Écart 1 — des octets hors ASCII

Les sept `.ISO` et le `.CLJOB` de la machine ne portent **pas un seul
octet au-dessus de 127**. Nos 85 fichiers de coupon en portaient tous :
`0xB7` (le `·` d'un nom de process) dans les ISO, `0xC3 0xA9` (le `é` du
nom de travail) dans le CLJOB — soit **deux encodages différents dans le
même travail**, et aucun des deux correspondant à la machine.

### Écart 2 — deux caractères que la machine n'écrit jamais

L'alphabet complet des `.ISO` de la machine, relevé sur 22 Mo de G-code :

```
A-Z  a-z  0-9  espace  ( )  ,  -  .  :  =  _
```

Rien d'autre. Notre coupon y ajoutait `/` — 150 occurrences, venues des
`mm/min` des noms de cases — et aurait ajouté `%` sur un coupon en
puissance.

Ce ne sont pas deux caractères anodins : **`/` est le caractère de saut de
bloc du dialecte ISO**, et `%` en est ailleurs le délimiteur de programme.
Un analyseur qui les rencontre avant d'avoir ouvert le commentaire saute
la ligne — ou le fichier.

Les commentaires sont désormais filtrés sur l'alphabet exact de la
machine. `case 100% / 40000mm/min` s'écrit `case 100 pc - 40000mm-min`.

### Écart 3 — espaces et point dans les noms de fichiers

| Origine | Nom produit |
|---|---|
| machine | `EASY_LASER_Z0001_2.ISO` |
| TauDrive, exports qui ont gravé | `gravure_Z0001.ISO` |
| TauDrive, coupon refusé | `Coupon Balayage  Pz0.1_Z0001.ISO` |

Ni la machine ni nos exports qui fonctionnent n'emploient d'espace, et
aucun ne place de point ailleurs qu'avant l'extension. Le coupon avait les
deux — **deux espaces consécutifs** et un point au milieu, tous deux venus
du nom d'onglet.

Un analyseur qui coupe l'extension au **premier** point cherche un fichier
nommé « Coupon Balayage  Pz0 ». Il ne le trouve pas. Et ne dit rien.

Les noms de fichiers et de dossiers passent maintenant par le même tamis
que la machine : lettres, chiffres, `_` et `-`. Le travail ci-dessus
produit `260819_Coupon_Balayage_Pz0_1/Coupon_Balayage_Pz0_1_Z0001.ISO`.

### Ce qui reste non vérifié

Le coupon refusé comptait **84 travaux** dans un seul CLJOB. Les fichiers
de la machine en portent un ou deux ; le plus long export dont on sache
qu'il a gravé en comptait dix-huit. Au-delà, personne ne sait.

La vérification avant export le signale désormais, sans inventer de
limite : elle dit ce qui a été vu graver, et laisse décider.

> **Le test qui tranche.** Exporter un coupon 2×2 — neuf travaux, sous le
> seuil connu. S'il grave, le nombre de travaux n'était pas en cause et
> les trois écarts ci-dessus suffisaient. S'il refuse encore, c'est
> ailleurs, et il faudra une capture de ClTerm au moment du refus.

### La règle qui en sort

> Tout ce qui part à la machine tient dans ce que la machine écrit
> elle-même. Alphabet, encodage, conventions de nommage : là où l'on
> pourrait faire plus riche, on fait pareil.

Un contrôle automatique compare désormais un coupon exporté à ce modèle :
alphabet, octets, noms de fichiers. C'est lui qui aurait attrapé les trois
écarts avant la machine.

---

## 64. L'export ne pose plus de fenêtre

Un export réussi n'a rien à annoncer qui vaille un clic. Le compte rendu
— nombre de fichiers et dossier d'écriture — passe dans la **barre
d'état**, et le détail (chemin vu par la machine, rappel du réglage du
modèle) dans son infobulle, pour qui veut vérifier.

Les fenêtres modales restent où elles ont leur place : l'échec d'écriture,
et la vérification avant envoi, qui appelle une décision.

---

## 65. Le coupon : fixer ce qui ne varie pas

Un coupon fait varier **un ou deux** paramètres. Les autres venaient de la
process de départ, sans moyen de les toucher : un essai en puissance se
faisait forcément à la vitesse de cette process, qu'il fallait aller
modifier dans la bibliothèque avant de revenir ici. Deux allers-retours
pour une valeur.

Le formulaire porte donc une section **Paramètres fixes — appliqués à
toutes les cases** :

| Paramètre | Mode simple | Mode expert |
|---|:---:|:---:|
| Puissance, Vitesse, Hachure, Nb passes, Profondeur | oui | oui |
| **Fréquence, Durée d'impulsion** | — | **oui** |

Fréquence et durée d'impulsion suivent la règle qui vaut partout ailleurs
dans TauDrive : ce sont les deux réglages qu'un opérateur ne doit pas
pouvoir déplacer par mégarde. Elles disparaissent aussi de la liste des
**axes** en mode simple — on ne propose pas de faire varier ce qu'on
n'autorise pas à régler.

### Un paramètre ne peut pas être fixe et variable

Choisir la puissance en axe X grise le champ *Puissance* des paramètres
fixes, et lui accole la mention « varie sur l'axe X ». Le formulaire dit
alors de lui-même pourquoi ce champ ne se règle pas ici, plutôt que de
laisser l'opérateur saisir une valeur sans effet.

Côté code, la même règle est appliquée à la génération : `build(...,
fixed=…)` écarte silencieusement tout paramètre porté par un axe. Une
interface qui se contredirait avec le générateur produirait des coupons
faux sans rien signaler.

---

## 66. Le formulaire d'un coupon se rouvre

Un coupon n'est pas un dessin qu'on retouche à la souris : c'est le
résultat d'un formulaire. Changer une borne, ajouter une colonne ou
corriger une vitesse fixe revenait à jeter le coupon et à tout ressaisir.

Le document **retient les réglages qui l'ont produit** — `Document.coupon`,
enregistré avec lui. Sur un onglet qui porte un coupon, *Coupon…*
(Ctrl+Maj+C) rouvre donc **ce** formulaire, avec ses axes, ses bornes et
ses paramètres fixes ; le bouton s'appelle *Régénérer* et la grille est
refaite en place, dans le même onglet.

Sur tout autre onglet, la même commande crée un coupon neuf dans un onglet
neuf, préréglé sur le dernier coupon produit. Deux mémoires distinctes,
pour deux besoins qui ne se confondent pas :

| Mémoire | Portée | Sert à |
|---|---|---|
| `Document.coupon` | ce coupon-ci | le rouvrir et le refaire |
| `session.coupon_defaults()` | le poste | préréger le **prochain** coupon |

> **Ce que la régénération écrase.** Elle refait la grille entière : les
> retouches faites case par case après coup sont perdues. C'est le prix
> d'un formulaire qui reprend la main, et c'est le comportement attendu —
> régénérer, c'est demander la grille que le formulaire décrit, pas celle
> qu'on a modifiée depuis.

---

## 67. Offset du dessin sous un cadre

Graver en négatif laisse le dessin **en relief**. Mais le faisceau a une
largeur : il mord sur ce qu'il longe, et le relief sort systématiquement
plus fin que le tracé. Sur un spot de 0,03 mm, un trait dessiné à 0,3 mm
en fait 0,27 sur la pièce.

Le champ **Offset du dessin**, dans les propriétés, décale le contour
épargné avant calcul du négatif :

| Offset | Effet |
|---:|---|
| `+0,015 mm` | compense un spot de 0,03 mm : le relief sort à la cote |
| `+0,4 mm` | épaissit franchement — pleins gras, contre-formes refermées |
| `0` | frontière exactement sur le tracé (comportement d'origine) |
| `−0,4 mm` | amincit le relief, ouvre les contre-formes |

Il agit **avec ou sans cadre**. Sous un cadre, c'est la compensation du
faisceau sur un négatif. Seul, c'est le tracé lui-même qu'on grossit ou
qu'on amincit — ce qu'on veut aussi bien pour rattraper un logo trop
maigre que pour affiner un texte qui se bouche. L'épaisseur de trait,
elle, reste un autre réglage : elle élargit le passage, elle ne déplace
pas le contour.

### Symétrique, contre-formes comprises

Un offset positif épaissit la matière **partout** : les pleins grossissent
et les contre-formes — le trou du « O », l'intérieur d'un motif fermé — se
referment d'autant. C'est le comportement d'une compensation de trait, et
non d'un simple grossissement du contour extérieur.

### Trouver le bon côté sans connaître le sens de parcours

Décaler un contour suppose de savoir où est le dedans. Le sens de parcours
d'une polyligne le dirait — sauf qu'il n'a rien de garanti dans un DXF,
où chaque logiciel émetteur fait à sa façon.

On ne s'y fie donc pas : chaque contour est décalé **des deux côtés**, et
l'on retient celui qui va dans le bon sens en comparant les aires. Reste à
savoir si le contour est un plein ou un creux — ce que donne la règle
**pair-impair**, la même qui remplit la forme. Offset et remplissage
voient ainsi exactement la même matière, ce qui n'irait pas de soi avec
deux critères différents.

| Contour | Offset positif | Aire visée |
|---|---|---|
| plein (profondeur paire) | dilate | croît |
| creux (profondeur impaire) | érode | décroît |

### Ce qui disparaît disparaît

Une nervure plus fine que deux fois l'offset ne survit pas : son contour
se retourne sur lui-même. Plutôt que de tracer un polygone croisé — que la
machine graverait comme un nœud — le contour est **écarté**. C'est
physiquement juste : la matière n'y résisterait pas non plus.

---

## 68. Bibliothèque de dessins

Un atelier regrave les mêmes motifs : un logo, une silhouette, un
cartouche. Les retrouver chaque fois dans l'arborescence, redécider des
unités et de l'échelle, c'est du temps perdu et une occasion de se
tromper.

*Bibliothèque…* (Ctrl+J) les range à un endroit connu et les pose d'un
double-clic.

### Deux étagères

| Étagère | Emplacement | Droits |
|---|---|---|
| **livrés** | ressources de TauDrive | lecture seule |
| **du poste** | dossier réglable | ajouter, renommer, effacer |

Les dessins livrés sont en lecture seule pour une raison simple : une mise
à jour de l'application les remplace, et ce qu'on y aurait ajouté
disparaîtrait sans prévenir. Le dossier du poste, lui, se règle dans
*Paramètres ▸ Dossiers par défaut* — **pointé sur un partage réseau, c'est
la bibliothèque de l'atelier**, exactement comme la bibliothèque de
process. Chacun y ajoute, tout le monde en profite.

Un dossier injoignable vide l'étagère du poste sans emporter le reste : la
bibliothèque livrée reste consultable débranché du réseau.

### Deux formats, deux apports

| Format | Ce qu'il apporte |
|---|---|
| `.dxf` | la géométrie seule ; reçoit la process courante |
| `.taudrive` | la géométrie **et les process** de ses formes |

Le second mérite qu'on s'y arrête : ranger comme élément de bibliothèque
une plaque **déjà validée sur chute** conserve les paramètres laser avec
lesquels elle a été validée. Le dessin ne revient pas nu, il revient au
point.

### L'aperçu n'est pas décoratif

Un DXF n'a ni vignette ni nom parlant — les fichiers d'atelier s'appellent
souvent `piece_rev3_final.dxf`. La fenêtre affiche donc le tracé réel,
avec son encombrement en millimètres et son nombre de tracés. Poser le
mauvais dessin, sinon, ne se voit qu'une fois la plaque gravée.

### Ajouter, c'est copier

Un dessin ajouté est **copié** dans la bibliothèque, jamais référencé : il
doit survivre au ménage du dossier d'où il venait. Un nom déjà pris reçoit
un rang — `Voiture client-02` — plutôt que d'écraser en silence.

**MyCar** est livré comme premier élément de la bibliothèque.

---

## 69. Process : ce qui existait, et ce qui manquait

Le nombre de passes et la profondeur étaient **déjà** dans la définition
d'une process — *Nb passes* dans le groupe *Laser*, *Réglage*,
*Profondeur / passe* et *Profondeur totale* dans le groupe *Profondeur*.
Renommer se faisait aussi : le champ *Nom* est éditable et la liste suit
la frappe.

Ce qui manquait n'était donc pas la fonction, c'était de **la voir**.

**La liste n'affichait que le nom.** Les passes et la profondeur se
cachaient dans une infobulle, si bien que deux process ne différant que
par leur profondeur étaient indiscernables — or c'est exactement ce qui
sépare une gravure d'un évidement. Chaque entrée porte désormais son
outil et, s'il y a lieu, ses passes :

```
Dégrossissage   [T65 · 2 passes de 4.673 µm]
Satinage        [T66]
```

**Renommer n'avait aucune affordance.** Un champ de saisie n'annonce pas
qu'on peut s'en servir pour renommer ; un bouton, si. *Renommer* amène au
champ *Nom* et l'y sélectionne. Rien de neuf sous le capot — seulement de
quoi trouver ce qui était déjà là.

**Un bouton *Process…* entre la liste des formes et la process.** C'est
là qu'on se trouve quand on constate qu'aucune process de la bibliothèque
ne convient ; aller la chercher dans un menu cassait le geste.

---

## 70. Copier, coller, dupliquer un onglet

### Ctrl+C / Ctrl+V

La sélection — une forme ou un groupe entier — se copie et se colle
**superposée** : au même endroit, prête à être écartée aux flèches ou à la
souris.

Superposée, et non décalée d'un cran comme le fait *Dupliquer*. Les deux
gestes ne servent pas à la même chose : on duplique pour poser une seconde
pièce à côté, on colle pour comparer, pour recaler à la cote, ou pour
reprendre une forme d'un autre onglet **à sa place exacte**. Un décalage
automatique obligerait alors à corriger deux coordonnées à chaque collage.

Le presse-papiers est **celui de l'application**, pas celui de Windows.
Les formes s'y rangent sous leur forme sérialisée — la même que dans le
fichier — ce qui garantit que rien ne se perd entre copier et coller qui
ne se perdrait pas déjà entre enregistrer et rouvrir. Il traverse les
onglets : copier dans l'un, coller dans l'autre.

> **Un piège trouvé au test.** Les formes collées conservaient le **nom de
> groupe** de leur original. Les regrouper ramassait alors aussi les
> originales : on collait deux formes, on en regroupait quatre. Le groupe
> est désormais effacé avant l'ajout, et le collage forme un groupe neuf,
> séparé.

### Clic droit sur un onglet

*Dupliquer l'onglet*, *Renommer…*, *Fermer*. La duplication produit une
**copie indépendante** : identifiants de formes renouvelés, pour que les
deux onglets puissent diverger sans se marcher dessus. On duplique pour
essayer une variante sans risquer l'original — deux vues du même document
ne rendraient pas ce service.

L'appartenance à un groupe passe par un nom et non par un identifiant :
elle survit au renouvellement.

---

## 71. La barre d'état dit le résultat de l'export

Vert deux secondes si l'export a réussi, rouge s'il a échoué, puis retour
à la normale.

Les couleurs viennent du **thème** — `ok` et `alarm` — et non de
constantes : les dix-neuf thèmes n'ont pas le même vert, et un vert sombre
sur un fond clair ne se verrait pas. L'encre suit : claire sur un thème
sombre, blanche sinon.

Deux secondes, puis effacement. Une barre qui resterait verte finirait par
ne plus rien dire — c'est le changement qui porte l'information, pas la
couleur.

L'échec garde en outre sa fenêtre : la couleur signale, le message
explique, et un échec d'écriture demande à être lu.

---

## 72. Les vitesses se lisent en m/min

La machine annonce ses vitesses en **m/min** — `Vel.=80.000m/min` dans ses
rapports — et ses propres outils s'en nomment :
`-->OT_SGROSSA_130KHz_80m/min`. TauDrive les affichait en mm/min, ce qui
obligeait à diviser de tête chaque fois qu'on comparait une process à ce
que dit la machine.

Elles se **saisissent et s'affichent** désormais en m/min, partout :
éditeur de process, gestionnaire, axes du coupon, valeurs gravées sur les
étiquettes.

### Ce qui ne change pas

Le **modèle** et l'**ISO** restent en mm/min. C'est l'unité du mot `F`, et
la convertir là reviendrait à poser un facteur 1000 sur le chemin de la
machine — exactement l'endroit où une erreur d'unité ne pardonne pas.

La conversion tient dans trois constantes, et n'existe qu'aux bords :

```
saisie  →  × 1000  →  modèle (mm/min)  →  ISO  F80000
affiche ←  × 0,001 ←
```

Un effet secondaire heureux : les étiquettes d'un coupon en vitesse
gravaient « 40000 » sur une case de 8 mm, illisible et inutile. Elles
gravent « 40 ».

---

## 73. Ctrl+H et Ctrl+F : plein ou filaire

**Ctrl+H** remplit les formes sélectionnées, **Ctrl+F** ne leur laisse que
le contour. Sur une sélection entière, groupe compris.

Le pas retiré par Ctrl+F est **mémorisé** : Ctrl+H rend sa valeur
d'origine, et non un pas d'usine. Sans cette mémoire, un aller-retour
remplacerait en silence un hachurage réglé à 0,02 mm par le pas par
défaut — une différence invisible à l'écran, et qui se paie sur la pièce.
Une forme qui n'a jamais eu de hachurage reçoit 0,05 mm, le pas des
process matière livrées.

> **Un piège du même genre.** `reload()` reconstruit la scène et **perd la
> sélection**. Un Ctrl+F suivi d'un Ctrl+H ne trouvait donc plus rien à
> remplir, et l'aller-retour restait sans effet. La sélection est
> maintenant remise après le rechargement.

---

## 74. Les options du coupon s'activent une à une

Cinq interrupteurs, indépendants :

| Option | Ce qu'elle décide |
|---|---|
| Remplir les cases | grille pleine ou filaire |
| **Remplir les étiquettes** | texte plein ou filaire, **indépendamment des cases** |
| Graver le titre | ligne d'en-tête rappelant process et axes |
| Graver les étiquettes de colonnes | valeurs de l'axe X |
| Graver les étiquettes de lignes | valeurs de l'axe Y |

L'indépendance du texte et des cases n'est pas un raffinement. Sur un
métal clair, un texte filaire de 1,8 mm disparaît à la lecture ; sur un
cuir sombre, le hachurer le brûle. Les deux réglages n'ont pas la même
bonne réponse au même moment, et les lier obligeait à choisir entre une
grille lisible et des étiquettes lisibles.

Couper le titre ou les étiquettes sert quand la place manque — mais c'est
à faire en connaissance de cause : **sans étiquettes, une chute retrouvée
trois semaines plus tard ne dit plus quelle case portait quelle valeur.**
L'infobulle le rappelle.

### « Remplir » remplit enfin

*Remplir les cases* ne faisait jusqu'ici que **retirer** le hachurage
existant. Coché sur une process qui n'en avait aucun — la moitié des
process livrées — il ne changeait rien, et un coupon destiné à juger un
rendu de surface sortait en contours. Il pose désormais 0,05 mm quand la
process est nue.

---

## 75. Le trait épaissi brûlait — deux causes, pas une

Signalé : en filaire avec une épaisseur, certaines zones reçoivent
plusieurs passages superposés et brûlent.

Mesuré, sur deux rectangles distants de 0,12 mm épaissis à 0,4 mm :
**85 % de la longueur gravée passait à moins d'un pas d'un autre
passage**. La matière y recevait deux fois l'énergie prévue.

En cherchant, un second défaut est apparu — plus grave, parce qu'il
faussait la cote sans rien signaler.

### Cause 1 — le décalage lui-même était faux

`_offset_polyline` moyennait les normales des deux arêtes d'un sommet
**sans les normaliser**. Leur longueur valait celle de l'arête : à un coin
joignant une arête de 20 mm et une de 10 mm, la longue écrasait la courte
et le sommet partait de travers.

Et le sommet était déplacé de `offset`, alors qu'un raccord d'onglet
demande `offset / cos(θ/2)` — à 90°, la pointe doit s'écarter de
`offset·√2`.

| | Demandé | Obtenu | Écart |
|---|---:|---:|---:|
| écart au côté | 0,050 mm | 0,0447 mm | **−11 %** |
| pointe d'onglet | 0,0707 mm | 0,0447 mm | **−37 %** |

Un trait demandé à 0,4 mm d'épaisseur sortait à 0,36. Sur un contour isolé,
cette seule erreur produisait **33 % de recouvrement** : les passages, mal
dirigés, se rapprochaient là où ils auraient dû rester parallèles.

La formule exacte, avec `n1` et `n2` unitaires :

```
d = offset · (n1 + n2) / (1 + n1·n2)
```

`offset·√2` à 90°, `offset` sur une droite, et une divergence sur un angle
très fermé — que `MITER_LIMIT` rabat à quatre fois l'offset.

### Cause 2 — rien ne surveillait les recouvrements

Deux tracés plus proches que l'épaisseur demandée voient leurs passages
se croiser, quoi qu'on fasse. Deux remèdes, dans cet ordre.

**Les doublons exacts partent.** Un DXF d'atelier en contient souvent :
deux entités qui partagent une arête, un calque recopié, un contour
retracé par-dessus l'ancien. Gravés tels quels ils brûlent double sans
rien ajouter au dessin, puisqu'ils sont au même endroit. Seuls les
doublons **rigoureusement identiques** partent — sens de parcours inversé
compris. Deux tracés distants ne serait-ce que d'un centième restent : ils
portent peut-être une intention, et supprimer un trait que quelqu'un a
demandé se voit sur la pièce.

**Les passages ajoutés sont normalisés.** Le trajet voulu est un réseau au
pas `step` ; tout ce qui roule à moins de 0,9 pas d'un passage déjà retenu
est du recouvrement, et se retire. Le seuil laisse vivre le réseau — dont
les passages sont à exactement un pas — et n'écarte que ce qui est plus
serré.

Une grille au pas `step` fait le tri : un point n'interroge que les neuf
cases autour de lui. Sans elle le test serait quadratique et un dessin
épaissi coûterait des minutes.

> **Ce qui n'est jamais raboté.** Les tracés **voulus par l'utilisateur**.
> Deux contours qu'il a dessinés à 0,02 mm l'un de l'autre brûleront
> peut-être — mais les effacer serait pire. Seuls les passages *ajoutés
> par l'épaississement* sont concernés, et c'est bien d'eux que venait le
> recouvrement.

### Résultat

| Cas, épaisseur 0,4 mm au pas 0,05 | Avant | Après |
|---|---:|---:|
| contour isolé | 33 % | **0 %** |
| deux contours à 0,12 mm | 85 % | **6 %** |
| contours doublés | 100 % | **0 %** |

Les 6 % restants sont les croisements de passages sur les angles, là où
deux bandes voisines se rejoignent : un vrai décalage de polygone les
supprimerait, au prix d'un calcul sans commune mesure. Le contrôle
automatique vérifie que ce reliquat ne dépasse pas 10 %.

---

## 76. La fenêtre du coupon dépassait l'écran

Le formulaire a grandi — deux axes, sept paramètres fixes, cinq options —
jusqu'à demander **1 114 px de haut en mode expert**. Sur un écran FullHD
avec sa barre des tâches, il en reste un millier : *Générer* et *Annuler*
passaient dessous, hors d'atteinte.

Une fenêtre dont on ne peut pas atteindre le bouton de validation est
inutilisable, et rien à l'écran n'explique pourquoi.

Le corps du formulaire **défile** désormais ; le résumé — nombre de cases
et emprise — et les deux boutons restent ancrés en bas, visibles quelle
que soit la hauteur disponible. La fenêtre s'ouvre à la taille de son
contenu, **bornée à ce que l'écran peut montrer**.

Le dimensionnement demande une précaution : une zone défilante n'annonce
que sa taille minimale, si bien qu'une fenêtre bâtie autour d'elle
s'ouvrait repliée sur 449 px alors qu'elle avait la place de tout montrer.
`fit_to_screen` interroge donc le **contenu**, pas la zone.

Le contrôle automatique compare désormais la fenêtre à l'écran réel, dans
les deux modes.

---

## 77. Journal des exports

Un même travail est rarement exporté une seule fois. On corrige une
puissance, on ajoute une passe, on relance — et trois plaques plus tard,
personne ne sait plus **laquelle a été gravée avec quoi**.

À chaque export, TauDrive écrit dans le dossier de destination, à côté des
dossiers horodatés :

```
<travail>-journal.txt
```

Une entrée par export : horodatage, dossier produit, nombre de fichiers,
formes et formes masquées, ordonnancement, et les process employées avec
leurs onze paramètres. Puis, à partir du deuxième :

```
  MODIFICATIONS depuis l'export precedent :
    * formes : 1 -> 2
    * optimiser le parcours : False -> True
    * process ajoutee : Satinage
    * JPT 30W laiton - puissance : 100 % -> 60 %
    * JPT 30W laiton - passes : 1 -> 3
```

C'est cette section qui compte. Relire deux listes de vingt paramètres
pour trouver la puissance qui a bougé, personne ne le fait — et personne
ne devrait avoir à le faire.

Le fichier est en **texte ASCII**, comme tout ce qui va sur le partage
machine : il se lit depuis n'importe quel poste, sans TauDrive. Et il
n'interrompt jamais un export : les fichiers sont déjà écrits quand on en
arrive là, un journal qui échoue se tait.

---

## 78. La process : commentaire et enregistrement

### Un commentaire, parce que les chiffres ne disent pas tout

Une process validée sur chute vaut par **ce qu'on en sait**. « 2 mm de
laiton poli, très bon rendu, coupon du 14/03 » en dit plus que n'importe
quel nom, et c'est précisément ce qui se perd entre deux opérateurs.

Le champ *Commentaire* est une zone de texte qui **prend la hauteur de son
contenu**, d'une ligne à huit — au-delà, l'ascenseur reprend la main
plutôt que de pousser le reste du panneau hors de vue. Une zone fixe de
trois lignes gaspille la place quand elle est vide et la refuse quand elle
est pleine.

Le commentaire part **avec la process**, bibliothèque partagée comprise,
et **jamais dans l'ISO** : la machine n'en a que faire.

### Un bouton pour la ranger

Une process se réglait sur la forme, dans la colonne 1 — puis il fallait
rouvrir le gestionnaire et la ressaisir pour la garder. Le bouton
*Enregistrer la process* fait le trajet.

Un nom déjà pris est **mis à jour** plutôt que dupliqué : c'est ce qu'on
veut quand on affine une process existante, et le gestionnaire refuse de
toute façon deux process de même nom. Une process encore nommée
« personnalisé » se voit demander un nom — sans nom, on ne la retrouvera
pas.

---

## 79. Traitement d'un dessin

Préparer un dessin à la gravure en négatif demande toujours la même
séquence : poser un cadre, choisir sa marge, compenser la largeur du
faisceau par un offset de contour, parfois épaissir le trait. Quatre
réglages dispersés dans la colonne des propriétés, à refaire dessin après
dessin.

*Traiter…* (Ctrl+Maj+T) les réunit, et surtout **garde l'original** :

1. la sélection est **copiée**, la copie restant exactement où elle est ;
2. l'**original est masqué** (œil fermé) — et **ne bouge pas** ;
3. cadre, marge, offset et épaisseur sont appliqués **sur la copie**.

L'original demeure dans le document comme référence, consultable et
regravable d'un clic sur son œil, mais ne part pas à la machine. Garder le
dessin nu coûte quelques kilo-octets et évite de le refaire quand le
traitement s'avère trop fort ; le masquer évite qu'il parte à la gravure
par distraction — ce que le contrôle avant export rappellerait de toute
façon.

**L'original ne se déplace plus.** Il était écarté sur le côté, de sa
propre largeur plus un écart, pour que les deux versions se voient sans se
recouvrir. Mais déplacer le dessin nu déplace le repère au moment même où
l'on compare la copie à ce dont elle vient, et fait sortir du champ un
dessin qui y tenait. Masqué sur place, il ne gêne ni la vue ni la gravure.

### Le bouton « épaisseur = 2 × offset »

Il reprend **deux fois l'offset du dessin**. La raison est géométrique :
l'offset écarte le contour d'une distance donnée, et un trait de deux fois
cette distance grave exactement la bande ainsi gagnée, de part et d'autre
du tracé. Ce que l'offset a pris en largeur, le trait le rend en matière
enlevée.

Sur un offset nul, le bouton ne fait rien et le dit : sans offset, il n'y
a pas de bande à couvrir.

---

## 80. Le magasin d'outils : lecture oui, écriture non

Deux questions posées, deux réponses nettes.

### Lire : oui

Sept champs sont décodés sur les cent emplacements de `dbpunte.mag` — nom,
vitesse, puissance, fréquence, résolution, **diamètre de spot**, durée
d'impulsion. Méthode et preuves dans
[`magasin-outils.md`](magasin-outils.md).

TauDrive lit le fichier de la machine s'il répond, et l'extrait embarqué
sinon — donc y compris sur un poste débranché. Sur les cent emplacements,
73 sont exploitables ; les autres sont des séparateurs de présentation ou
des emplacements vides, écartés par des bornes de vraisemblance.

### Écrire : non, et ce n'est pas une timidité

Un enregistrement fait **12 411 octets, dont 12 400 ne sont pas
décodés** : corrections, tables de calibration, paramètres de découpe. En
réécrire sept rendrait un fichier dont le reste ne serait plus garanti. Le
magasin vit en outre dans les dossiers du constructeur, que TauDrive ne
modifie jamais (EX-01).

Et l'enjeu n'est pas symétrique : une process ratée gâche une plaque, **un
magasin corrompu immobilise la machine** — sur tous les travaux, pas
seulement le sien.

### Ce qu'on fait à la place

**Charger un outil dans une process.** Les valeurs viennent de la machine,
la process vit chez TauDrive, le magasin n'est pas touché. Le bouton
*Magasin d'outils…* du gestionnaire ouvre la liste ; il est **réservé au
mode expert**, comme la fréquence et l'impulsion : le numéro d'outil qu'un
travail appelle est ce que la machine applique réellement.

Trois choix méritent d'être connus :

| | |
|---|---|
| le **nom de la process est conservé** | c'est celui que l'atelier emploie ; l'écraser par celui du magasin ferait perdre le fil |
| le **pas de hachurage reprend le spot** | c'est le pas naturel : hachurer plus fin repasse sur la matière déjà enlevée |
| **passes et profondeur sont laissées** | elles ne sont pas dans le magasin — elles appartiennent au travail, pas à l'outil (voir §42) |

Un bouton *Pourquoi pas d'édition ?* donne la raison dans l'application,
plutôt que de laisser croire à un oubli.

---

## 81. Modèles de traitement, et pourquoi ils sont copiés

Un traitement au point — cadre, marge, offset, épaisseur — se réemploie ;
il ne se ressaisit pas. Le dialogue *Traiter…* propose donc des
**modèles** : quatre livrés, autant qu'on veut ajoutés, rangés sur le
poste.

Une **process peut porter un traitement**. Choisir cette process sur une
forme applique alors les deux d'un coup : les paramètres laser *et* la
mise en négatif du dessin. La process qui dit comment graver dit aussi
sur quoi.

### Les valeurs sont figées, pas empruntées

C'est le point qui compte, et il conditionne tout le reste.

Une process ne **renvoie pas** à un modèle par son nom : elle en porte une
**copie complète**. Supprimer le modèle de la bibliothèque ne casse donc
aucune process — celles qui s'en servaient continuent d'appliquer
exactement ce qu'elles appliquaient.

| Approche | Supprimer le modèle |
|---|---|
| renvoi par nom | la process perd son traitement, ou pire, en prend un autre du même nom |
| **copie figée** | **rien ne change** |

C'est la seule façon d'avoir des modèles qu'on ose ranger : personne ne
fait le ménage dans une bibliothèque s'il faut d'abord vérifier ce qui en
dépend.

Le gestionnaire le montre : une process dont le modèle a été retiré
affiche **« Relief épais 0,1 (modèle retiré) »** et garde ses valeurs.
Sinon elle semblerait avoir perdu son traitement alors qu'elle le porte
toujours.

> **Un défaut trouvé au passage.** La lecture d'un document reconstruisait
> la process à la main plutôt que par `recipe_from_dict`. Le traitement,
> valeur composée, revenait donc sous forme de dictionnaire au lieu d'un
> objet — et se perdait au premier rechargement. La lecture passe
> désormais par la fonction qui sait le reconstruire.

---

## 82. Process et magasin : des panneaux, plus des fenêtres

Régler une process demande de **voir le dessin** sur lequel elle
s'applique. Une fenêtre modale le cachait et obligeait à la refermer pour
vérifier, puis à la rouvrir pour corriger.

Les deux sont devenus des panneaux ancrés :

| Panneau | Place | Voisinage |
|---|---|---|
| **Process** | colonne 2 | à côté du plan de travail |
| **Magasin d'outils** | colonne 3 | avec les propriétés, en onglets |

Le gestionnaire n'a donc plus de bouton *Enregistrer / Annuler* de
fenêtre : *Enregistrer* range la bibliothèque, *Rétablir* la relit. Sans
fenêtre à fermer, il n'y a plus de moment où l'on validerait sans le
savoir.

> **Une subtilité de Qt.** Découper horizontalement un dock **déjà empilé**
> le fait *tabuler* au lieu d'ouvrir une seconde colonne. La colonne 2
> apparaissait donc en onglet derrière *Formes*. La division horizontale
> doit précéder les divisions verticales de la colonne 1.

Les quatre boutons de la liste sont passés sur deux rangées : de front
dans un panneau ancré, ils se tronquaient en « Nouvell », « uplique »,
« enomm ».

---

## 83. Le magasin sert aussi en mode simple

Il était réservé au mode expert ; il ne l'est plus.

La raison du changement tient en une phrase : **le panneau ne fait que
lire**, et choisir un outil de la machine est *plus sûr* que d'ajuster une
fréquence à la main. On prend un jeu de valeurs cohérent, tel que la
machine le porte, plutôt que d'en composer un.

La réserve du mode expert visait les réglages qu'on **déplace sans les
voir** — une fréquence, une durée d'impulsion. Charger un outil nommé
`Laiton` ou `Inox découpe` est le contraire : c'est un choix explicite,
tracé dans le commentaire de la process, et qu'on peut défaire en
rechargeant un autre outil.

Fréquence et durée d'impulsion restent en lecture seule dans l'éditeur :
on ne les compose toujours pas à la main en mode simple, on les reçoit
d'un outil.

---

## 84. Le réglage des process prend la place du dessin

Les panneaux ancrés d'hier montraient les process **à côté** du plan de
travail. C'est mieux qu'une fenêtre modale, mais cela rognait le dessin
et laissait deux colonnes se disputer la largeur.

Le gestionnaire prend désormais la place du plan de travail, et le
magasin d'outils celle des propriétés :

| | Au dessin | En réglage de process |
|---|---|---|
| colonne 1 | formes, puis process laser | inchangée |
| **colonne 2** | plan de travail | **gestionnaire de process** |
| **colonne 3** | propriétés de la forme | **magasin d'outils** |

On règle une process **à la place** du dessin, pas par-dessus. La colonne 1
reste visible : la forme sélectionnée et sa process continuent d'être
sous les yeux pendant qu'on travaille la bibliothèque.

### Deux boutons qui ne font pas la même chose

*Enregistrer* range la bibliothèque et **ne quitte pas les lieux** : on
enregistre une process sans avoir fini de régler les autres.

*Terminé* rend les colonnes 2 et 3 au dessin et à ses propriétés. C'est
le seul bouton qui sort, et il ne perd rien — ce qui a été enregistré
l'est.

Le magasin d'outils n'apparaît qu'en réglage de process : il occupe la
place des propriétés, il n'a rien à faire là pendant qu'on dessine.

### Deux détails de mise en page

Le panneau porte sa **barre de boutons hors de la zone défilante**. Une
zone défilante autour du tout faisait passer *Terminé* sous la ligne de
flottaison — le même défaut que la fenêtre du coupon, au même endroit.

Le bouton **« Pourquoi pas d'édition ? »** a disparu. La raison reste
dite, mais dans la note du panneau plutôt que derrière un bouton : une
explication qu'il faut aller chercher n'est pas lue, et un bouton de plus
dans une barre en compte un de trop.

### « Process laser » n'est plus écrit deux fois

Le bandeau du panneau de colonne 1 porte déjà ce titre ; le cadre qu'il
contenait le répétait. Une ligne rendue à un panneau qui en manque.

---

## 85. Liste des formes : renommer, réordonner

**Double-clic** sur une ligne : renommer la forme. **Clic droit** : la
masquer, la renommer, la dupliquer, la supprimer, la monter, la descendre.

Une précision qui évite une confusion : le nom d'une forme n'est **pas**
celui du travail. Celui-là se règle sur l'onglet et sert de nom de dossier
à l'export ; celui de la forme est l'étiquette qu'on lit dans la liste et
qui part en commentaire dans l'ISO — de quoi retrouver une forme parmi
trente.

Monter et descendre changent l'**ordre de gravure**, tant que le
regroupement par process est coupé. Monter une forme, c'est la graver plus
tôt.

---

## 86. Enregistrer une process **crée**, n'écrase pas

Le bouton d'enregistrement mettait à jour la process de même nom. Il
ajoute désormais une entrée, et donne un rang au nom si besoin :

```
Laiton        70 %        ← reste tel quel
Laiton 2      35 %        ← l'affinage
```

On affine une process en partant d'une autre. Perdre l'ancienne parce
qu'on a gardé son nom, ce serait perdre le point de comparaison au moment
précis où il sert — juste après avoir gravé les deux côte à côte.

Le rang se relit (« Laiton 2 », « Laiton 3 ») et deux affinages successifs
se suivent dans la liste, ce que « Laiton (copie) » ne donnerait pas.

### Des dossiers dans la bibliothèque

Une bibliothèque d'atelier finit à cinquante entrées : sans rangement, on
ne retrouve plus la process laiton parmi les essais. Chaque process porte
un **dossier** libre — `Laiton`, `Essais`, `Client X` — affiché en préfixe
dans la liste. Vide, elle reste à la racine.

---

## 87. Onglets fermés

Fermer un onglet ne demande rien : c'est voulu, et cela vaut mieux qu'une
question à chaque fois. Encore faut-il pouvoir revenir sur celui qu'on a
fermé par mégarde.

**Tous** sont conservés avec leur contenu, sans plafond, et *Fichier ▸
Onglets fermés…* (Ctrl+Maj+W) les rouvre.

Le contenu part sur le **disque**, non dans la base de registre : un
document pèse quelques kilo-octets, mille documents la feraient enfler
pour rien. Les fichiers se rangent par **semaine ISO** :

```
~/TauDrive/Onglets fermes/
    26s33/  Plaque_Renault_20260812-094512.taudrive
    26s34/  Plaque_client_X_20260821-165503.taudrive
```

`26s34` = semaine 34 de 2026. Un atelier se souvient d'une plaque par sa
semaine bien avant de se souvenir de sa date, et la liste se filtre sur
cette semaine-là. Le dossier d'archive se règle comme les autres, dans
*Paramètres ▸ Dossiers*.

La recherche porte sur le **contenu autant que sur le nom** :

```
Mot-clé : B000174
  → Plaque client X   —   26s34   —   2026-08-21 16:55   —   B000174
```

*Vider la liste* n'efface que l'index : **les fichiers archivés restent**
dans leurs dossiers de semaine.

Ce n'est pas un luxe. On se souvient du texte gravé ou de la référence du
client bien plus souvent que du nom qu'on avait donné à l'onglet — surtout
quand ce nom était « gravure ».

---

## 88. Date automatique

Un bouton pour poser, une flèche pour régler.

La date est posée comme **champ variable** `{date:%y%m%d}`, jamais comme
texte figé : elle est réévaluée à chaque export. Une plaque préparée lundi
et gravée mercredi porte la date du **mercredi** — presque toujours ce
qu'on veut, et jamais ce qu'un texte tapé à la main donnerait.

Le menu de la flèche propose les huit formats directement, chacun avec son
rendu du jour, et une entrée *Options* pour la police et la taille.

| Format | Aujourd'hui | Pour quoi faire |
|---|---|---|
| `aammjj` | `260821` | **défaut** — celui des dossiers machine |
| `jj/mm/aa` | `21/08/26` | lecture courante |
| `aaaa-mm-jj` | `2026-08-21` | tri alphabétique = tri chronologique |
| `mm/aaaa`, `aaaa`, `jj.mm.aa`, … | | selon la place |

### Trois façons d'ajuster la taille

**Hauteur imposée** — le corps est fixé, la largeur suit. **Largeur
imposée** — l'inverse. **Dans une boîte X × Y** — la plus petite des deux
contraintes l'emporte.

Les deux dernières calculent la taille **sur le rendu réel**, pas sur une
estimation de chasse. La raison est concrète : `01/01/26` est plus étroite
que `28/12/26`, et une police condensée ne tient pas la place d'une police
large au même corps. Poser une taille nominale donnerait une plaque à
refaire un jour sur deux.

> **Un ajout au moteur de champs.** `{date}` rendait une chaîne déjà mise
> en forme, à laquelle aucun motif ne pouvait s'appliquer. Le contexte
> porte désormais l'instant lui-même, et un format contenant `%` est passé
> à `strftime` plutôt qu'à `format`. `{n:03}` continue de donner `001`.

---

## 89. Propriétés d'un lot

Sélectionner une forme montre ses propriétés. En sélectionner plusieurs —
ou cliquer un groupe — n'en montrait aucune, alors que c'est précisément
là qu'on veut agir d'un bloc.

La colonne 3 montre donc **ce qu'on manipule** : les propriétés d'une
forme seule, un **formulaire de lot** dès que la sélection en dépasse une.

| Groupe | Ce qu'il règle |
|---|---|
| Placement du lot | centre X/Y · dim. X/Y · rotation · conserver les proportions |
| Process du lot | la process commune, et de quoi l'imposer à **toutes** les formes |
| Cadre commun | cadre · marge · décalage · épaisseur de trait |
| Le lot en chiffres | nombre de formes · longueur gravée · durée estimée |

### Une valeur mêlée ne s'écrit pas

Un champ dont les formes ne partagent pas la valeur affiche `—` et n'est
**pas** appliqué :

```
Rotation          —          ← les formes n'ont pas le même angle
Marge          3,000 mm      ← toutes l'ont, elle se règle
```

Montrer la valeur de la première et la répandre au premier tour de molette
détruirait le travail sans que rien ne l'annonce. Techniquement, le
minimum de ces champs est une **sentinelle** hors du domaine utile — Qt y
affiche un texte à la place du nombre — de sorte qu'une marge nulle reste
une marge nulle.

### Les mesures sont celles de l'export

Longueur et durée sont construites par `build_passes` sur un document de
circonstance ne contenant que le lot. Un lot mesuré autrement ne servirait
à rien. Au-delà de 240 formes la mesure est coupée : sur un coupon de
plusieurs centaines de cases, construire les trajectoires prend plus
longtemps que le clic ne le supporte.

### Un groupe n'emprisonne pas ses membres

Un code posé dans son cadre est un groupe de deux, et c'est bien la donnée
du code qu'on vient taper. Un bouton de tête — *Propriétés de « … »* —
ouvre la forme cliquée **sans défaire la sélection** ; recliquer la ligne
dans la liste ramène le lot.

---

## 90. Rayons de la bibliothèque

Une bibliothèque d'atelier passe vite deux cents entrées — logos clients,
cartouches, gabarits, pièces d'essai — et une liste à plat ne se lit plus.

Les rayons sont de **vrais sous-dossiers** sur le disque :

```
Bibliotheque/
    Clients/
        Client A/   capot.dxf
        Client B/   etiquette.taudrive
    Gabarits/       plaque_100x100.dxf
```

Pas un classement propre à TauDrive : on les range depuis l'explorateur,
et un partage réseau garde le même sens pour tout le monde. Quatre niveaux
au plus, pour qu'une bibliothèque pointée par mégarde sur la racine d'un
disque ne mette pas une minute à s'ouvrir.

| Geste | Effet |
|---|---|
| *Rayon* | restreint la liste — sous-rayons exclus |
| *Nouveau rayon…* | crée le sous-dossier, `Clients/Renault` accepté |
| *Déplacer…* | range le dessin choisi dans un autre rayon |
| *Ajouter…* | atterrit dans le rayon qu'on regarde |

Un rayon créé mais **vide reste visible** : sinon on le crée, il
disparaît, et l'on croit que la création a échoué. Un rayon qui contient
encore des dessins **ne s'efface pas** — perdre trente dessins sur un clic
serait sans recours. Un nom de rayon ne peut pas sortir de la
bibliothèque : remontées `..` et lettres de lecteur sont retirées.

---

## 91. Coupons : le motif des cases

Un carré plein juge un rendu de surface, et rien d'autre. Ce qu'on veut
souvent savoir, c'est comment **le dessin réel** sort : un logo se bouche,
un texte de 1,2 mm devient illisible, une contre-forme se referme.

Deux sources :

* un **fichier DXF**, choisi dans le formulaire du coupon ;
* la **sélection en cours** — clic droit sur la liste des formes ▸ *En
  faire un coupon d'essai…*

Le motif passe par `shape_polylines`, **le même chemin que l'export** : ce
qu'on lit sur la chute est ce qu'on aura sur la pièce. Il est centré, puis
ajusté à 90 % de la case, **facteur identique dans les deux axes** — un
logo étiré ne dit plus rien du logo qu'on gravera.

Le motif est rangé avec les réglages du coupon, donc régénérable sans
avoir à retrouver le DXF d'origine.

---

## 92. Coupons : l'axe des couples F-T

Sur une source **MOPA**, la durée d'impulsion et la fréquence ne sont pas
deux réglages libres : chaque forme d'onde a sa fréquence de répétition
maximale, et l'énergie par impulsion s'effondre au-delà.

Les faire varier séparément produit des cases qui ne veulent rien dire —
2 ns à 50 kHz ne marque rien, 250 ns à 1000 kHz est hors d'atteinte. Ce
qui se fait varier utilement, c'est le **couple** :

```
1300-2      1300 kHz · 2 ns
 375-9       375 kHz · 9 ns
 250-13      250 kHz · 13 ns
```

Une case reçoit **les deux réglages d'un bloc**. Quand l'axe porte des
couples, les bornes *De / À / Nombre de valeurs* disparaissent du
formulaire : on coche des paires dans une table, il n'y a rien à répartir.

### Deux tables, et une règle de mode

| Mode | Ce qui est proposé | Gestionnaire |
|---|---|---|
| normal | table constructeur **seule** | non |
| expert | table constructeur **+ couples du poste** | oui, complet |

Un opérateur ne doit pas pouvoir inventer un couple que la source
refusera : c'est la même règle que pour la fréquence et l'impulsion prises
séparément.

Le gestionnaire — mode expert — ajoute, supprime, signale un **rapport
cyclique** τ × f supérieur à 5 %, et sait **récolter les couples du
magasin** : 46 paires distinctes portées par les 72 outils de
`dbpunte.mag`, qui ont l'avantage d'avoir gravé. Le magasin est lu, jamais
écrit.

### Les treize formes d'onde

| f (kHz) | 1300 | 375 | 250 | 170 | 135 | 110 | 100 | 90 | 80 | 37 | 37 | 37 | 37 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **τ (ns)** | 2 | 9 | 13 | 20 | 30 | 45 | 60 | 80 | 100 | 200 | 250 | 350 | 500 |

La lecture est franche : plus l'impulsion est longue, plus la fréquence
plafonne bas. De 2 ns à 1300 kHz — impulsions très courtes, cadence très
haute, marquage superficiel — jusqu'à 500 ns à 37 kHz, où chaque impulsion
porte toute son énergie et creuse. Les quatre dernières partagent 37 kHz :
au-delà de 200 ns, c'est l'énergie par impulsion qui commande, et la
source ne suit plus en cadence.

Le rapport cyclique τ × f monte régulièrement de **0,26 % à 1,85 %**,
sans saut ni valeur aberrante — la table est cohérente d'un bout à
l'autre.

Elle a été **relevée sur la machine**, et non lue dans un fichier : la
table est dans le firmware de la source, que la GUI JPT interroge en
RS-232 au démarrage. Cherchée sans succès dans `JPT_Laser.exe`,
`Config/default.conf`, les 66 journaux `Log/*.xls` et `CLTERM.EXE`
(cf. [`limites-machine.md`](limites-machine.md) §2).

### Les couples d'atelier

Des couples mesurés sur pièce, **nommés d'après le travail qu'ils
servent**. Ce sont des données d'atelier : le cœur libre n'en livre aucun,
le plugin de l'atelier les apporte (`plugins.Api.add_couples`). Par
exemple :

| Couple | Travail |
|---|---|
| `200-20` | Client A surfaces |
| `200-60` | Client A fin · Client B |

Aucun n'est dans la table constructeur : ce sont des points de
fonctionnement trouvés à l'atelier et gardés parce qu'ils marchent. On les
cherche sous le nom du travail, bien avant de se souvenir que c'est du
200-60.

*Client A fin* et *Client B* gravent au même couple : c'est donc **un**
couple qui porte les deux noms. Un coupon n'a rien à gagner à graver deux
fois la même case.

Réservés au mode expert, comme les couples du poste : ce sont des valeurs
d'atelier, pas des limites de la source.

---

## 93. L'aide passe en barre d'état

Une infobulle flottante a trois défauts sur un poste d'atelier :

* elle **recouvre** ce qu'on regardait — souvent le champ voisin ;
* elle arrive **après un délai** d'une seconde, le temps qu'on ait déjà
  cliqué ;
* elle **disparaît** dès qu'on bouge d'un pixel.

Sur un écran tactile, elle ne paraît même pas.

L'aide part donc dans un **emplacement dédié**, à droite de la barre
d'état :

```
7 forme(s) · 7 passe(s) · gravé 1394.5 mm · …    │  Gestionnaire de process : créer, renommer…
└────────── mesures du travail ──────────┘       └────────────── aide du survol ─────────────┘
```

À droite, et non dans la zone de message : celle-ci porte les mesures,
réécrites en continu, et l'aide y serait effacée au premier mouvement de
souris. La part de l'aide est **bornée à 42 %** de la barre — laissée
libre, elle chassait les mesures.

### Rien n'a été réécrit

Le texte reste écrit là où il l'était, dans `setToolTip()`. Un filtre
d'événements posé sur l'application entière l'intercepte au survol
(`Enter`, et non l'événement `ToolTip` de Qt, qui n'arrive qu'après le
délai) et **consomme** l'événement de bulle. C'est ce qui rend la reprise
possible sur les quelque trois cents infobulles existantes.

La mise à plat joint les lignes par ` · `, retire le gras `**…**` et les
balises HTML : la barre n'a qu'une ligne, le texte entier doit y tenir ou
s'y tronquer proprement.

Dans un **menu**, c'est l'action survolée qui porte l'aide. Une action
dont l'infobulle ne fait que répéter son intitulé n'écrit rien.

Deux précautions de style : l'emplacement fixe son propre `font-weight`,
sinon l'alerte *hors champ* — qui passe la barre en gras rouge — le
gagnerait aussi ; et il s'efface le temps d'un **éclat de couleur** après
export, un texte atténué sur fond vert ne se lisant pas.

---

## 94. Le bouton *Process…* bascule

Le gestionnaire prend les colonnes 2 et 3. On y entrait par le bouton
sous la liste des formes, on en sortait par *Terminé*, à l'autre bout de
la colonne.

Le bouton **ouvre et referme** désormais, et son intitulé dit ce qu'il
fera :

| État | Intitulé | Aide |
|---|---|---|
| dessin | *Process…* | Gestionnaire de process : créer, renommer, dupliquer… |
| gestionnaire ouvert | *Fermer les process* | Referme le gestionnaire et rend le plan de travail |

Celui d'où l'on vient est celui qu'on cherche pour revenir. **Ctrl+M** et
*Paramètres ▸ Process…* basculent de la même façon ; *Terminé* reste en
place, il ne gêne personne.

---

## 95. Le décalage doit se **recoudre**

Décaler un contour de `d` fait se croiser ses côtés dès qu'un angle
rentrant est plus serré que `d`. L'élagage retire ces boucles — sans quoi
elles marquent dans le creux d'un « 2 » ou d'un « 6 ». Mais l'élagage ne
suffit pas : il laisse des **morceaux ouverts**.

Rendre des morceaux ouverts paraît sans conséquence. Gravés, ils tracent
le bon contour. C'est le **hachurage** qui les trahit : il les referme
lui-même par une corde droite d'un bout à l'autre, et cette corde traverse
l'intérieur du dessin.

```
« 260821 » vectorisé, offset +0,35 mm

avant :  19 contours, dont 14 OUVERTS   → trait parasite en travers du
                                          creux du « 6 », du « 0 », du « 1 »
après :  10 contours, tous fermés       → aucun
```

Dix contours : exactement ceux de la source — six extérieurs et quatre
contre-formes (le « 6 », le « 0 », les deux du « 8 »).

### La règle de recouture

Les morceaux arrivent dans l'ordre du parcours. Deux morceaux consécutifs
séparés d'un écart **de l'ordre de l'offset** encadrent une boucle
retirée : la corde qui les joint est, à un tiers d'offset près,
l'intersection exacte que le décalage aurait produite. On les coud.

Un écart plus large — au-delà de six fois l'offset — sépare deux régions
devenues distinctes, une nervure ayant fondu sous l'érosion : chacune se
referme alors sur elle-même.

La couture d'origine du contour demande une précaution : si le point de
départ était bon, la fin du dernier morceau et le début du premier sont le
même endroit, et ce sont deux bouts d'un seul. Ils sont réunis avant tout
le reste.

---

## 96. Trois décimales à l'écran

Une cote posée à la souris sortait « -26,111537 mm » : six décimales de
bruit qui chassent du champ le chiffre qu'on lit.

L'affichage montre désormais **au plus trois décimales**, zéros de queue
retirés — « 5 » plutôt que « 5,000000 », « -26,112 » plutôt que
« -26,111537 ». Le micron est déjà trente fois plus fin que le spot de la
machine.

La **valeur** ne change pas : elle garde ses six décimales internes, et
l'ISO continue de les écrire. Seul l'affichage est abrégé.

Un champ peut en demander plus. Le pas de profondeur en réclame six : la
valeur relevée sur la machine vaut 4,673 µm, et l'afficher « 0,005 mm »
serait le contresens que la spécification interdit depuis le début.

---

## 97. La bibliothèque prend deux colonnes

Choisir un dessin demande de le voir grand. Une vignette de 280 px ne
distingue pas deux révisions d'un même logo, et les fichiers d'atelier
s'appellent `piece_rev3_final.dxf`.

La bibliothèque est donc un **panneau**, aux mêmes colonnes que le
gestionnaire de process :

| Colonne | Contenu |
|---|---|
| 2 (plan de travail) | l'aperçu, en grand, et les boutons de gestion |
| 3 (propriétés) | l'arborescence **rayon ▸ dessin**, icône dossier |

Un arbre plutôt qu'une liste et un menu déroulant : on cherche d'abord le
rayon — le client, le type de pièce — avant le dessin. Le mot « Rayon » a
disparu avec le menu ; c'est l'icône de chemise qui dit ce qu'est une
branche.

La note « dessin livré : lecture seule » a disparu aussi : les boutons
*Renommer*, *Supprimer* et *Déplacer* sont grisés sur un dessin livré, ce
qui le dit mieux qu'une phrase sous l'aperçu.

### L'aperçu en deux temps

Un DXF d'atelier porte couramment cent mille segments. Le charger puis le
peindre entier fige le panneau une seconde à chaque clic de liste.

```
clic  →  [allégé]   un point sur n, extrémités gardées   → paraît aussitôt
      →  [entier]   pleine définition                    → substitué sans
                                                            clignotement
```

Les extrémités de chaque polyligne sont **toujours** gardées : un contour
qui perdrait son dernier point s'ouvrirait, et un contour ouvert se voit
tout de suite sur un aperçu.

Le chargement sort du fil qui peint — il figeait la fenêtre entière, barre
d'état et boutons compris. Chaque demande porte un **jeton** : un résultat
dont le jeton n'est plus le courant est jeté, car parcourir la liste aux
flèches lance dix chargements et seul le dernier a un sens. Ce qui a déjà
été chargé est gardé en réserve : revenir sur un dessin est instantané.

---

## 98. Ce que la barre d'outils dit d'elle-même

La barre est en **icônes seules** : l'aide au survol est le seul endroit
où un bouton se nomme. Une explication qui n'en dit pas le nom laisse
l'opérateur deviner l'icône.

Deux boutons étaient dans ce cas, et n'annoncent plus qu'eux-mêmes :

| Bouton | Avant | Maintenant |
|---|---|---|
| grouper | « Réunit la sélection : elle se déplace et se redimensionne d'un bloc » | **Grouper** |
| traitement | « Copie le dessin, écarte et masque l'original, et applique cadre, marge, offset et épaisseur sur la copie » | **Traitement dessin** |

Le champ *Pas clavier* a perdu son étiquette de texte au profit d'une
**croix à quatre flèches** : deux mots au milieu d'une barre d'icônes y
font une verrue, et ce que le champ règle se lit dans l'aide au survol.

---

## 99. Remplissage et oscillation

Deux transformations de trajectoire s'ajoutent au pas et à l'angle de
hachurage. Le détail, la physique et les mesures sont dans
[`parametres-laser.md`](parametres-laser.md) ; voici ce qu'il faut savoir
pour lire le code.

### Le remplissage

| Réglage | Champ de `Recipe` | Effet mesuré (carré 10×10, pas 0,2) |
|---|---|---|
| rotation par passe | `hatch_angle_step_deg` | 3 passes à 60° : 35, 46, 46 tracés |
| croisé | `hatch_cross` | 540 → 1040 mm |
| retrait | `hatch_inset_mm` | 540 → 445 mm |

La rotation par passe **reconstruit la géométrie à chaque passe** — le
rang de passe entre donc dans la clé de cache. Cela ne se produit que si
la recette le réclame : sinon on paierait autant de calculs que de passes
pour un résultat identique.

### L'oscillation

```
θ = 2π × s / pas       s = longueur parcourue depuis le début du tracé
```

et non `θ = t × f` avec `t` de 0 à 1 le long du segment, qui est la
formule qu'on trouve partout et qui donne une densité dépendant de la
longueur du segment. Contrôlé : deux segments de 1 mm et 20 mm reçoivent
41 et 40 points par mm.

Les bouts reviennent **sur le tracé**, sinon un contour fermé ne se
refermerait plus et la règle pair-impair du hachurage serait faussée.

L'oscillation vient **en dernier**, après l'épaississement : c'est le
trait gravé qu'elle élargit, pas la forme qu'on a dessinée.

### Ce que cela coûte

| | |
|---|---|
| longueur gravée | ×1,5 à ×9 selon forme, amplitude et pas |
| cadence scanner | `v / pas` — 13 kHz à 80 m/min avec un pas de 0,1 mm |

La cadence est **la vraie limite**. Un galvo suit 500 Hz sans faiblir,
1000 Hz à la limite ; au-delà le miroir ne suit pas et la bande n'est pas
plus large qu'un trait simple. Sur cette machine, **osciller impose de
ralentir** : une bande de 0,2 mm au pas de 0,4 mm ne tient que jusqu'à
12 m/min.

La vérification avant export refuse un travail qui dépasse la limite.

---

## 100. Le guide des paramètres

Le bouton **?** du gestionnaire de process ouvre trois pages : la physique
des quatre réglages, les formes d'onde de la source avec l'audit des
recommandations, et le coût du remplissage et de l'oscillation.

Le guide est **produit à partir des données du programme** — `couples.py`,
`advice.py`, `wobble.py`. Il ne peut donc pas dériver de ce que le
programme fait. Un guide qui décrirait une autre version serait pire
qu'aucun guide.

L'audit se lance aussi en ligne de commande :

```bash
python outils/audit_recommandations.py 180-30@600
```

`fréquence-impulsion@vitesse`, la vitesse en mm/s comme dans la plupart
des tables qui circulent.

---

## 101. Import vectoriel : PDF, Illustrator, EPS, CorelDRAW

Le détail est dans [`import-vectoriel.md`](import-vectoriel.md) ; voici ce
qu'il faut savoir pour lire le code.

`vecimport.py` porte un lecteur pour deux langages qui ont les mêmes
primitives de tracé aux noms près :

| Langage | Formats | Opérateurs suivis |
|---|---|---|
| PDF | `.pdf`, `.ai` v9+ | `m l c v y re` · `q Q cm` · `S s f F f* B B* b b* n` |
| PostScript | `.eps`, `.ps`, `.ai` v8- | `m mo · l li · c cv · v y` · `gsave grestore ct scale translate` · `f ef @ S b n` |

`PathBuilder` leur est commun : il porte la pile de matrices, aplatit les
Béziers et rend des polylignes **en millimètres**. Ne diffère que la façon
de lire les jetons.

### Trois pièges, et comment ils sont traités

**Le suffixe ment.** Un `.ai` est un PDF ou un EPS selon la version qui
l'a écrit. `sniff()` regarde les premiers octets : `%PDF`, `%!PS`,
`ÅÐÓÆ` (en-tête binaire DOS), `RIFF…CDR`.

**Le prologue n'est pas du tracé.** Un EPS Illustrator définit des
centaines de procédures avant l'illustration. La lecture commence après
`%%EndPageSetup` / `%%EndSetup` / `%%EndProlog`, et les blocs `{...}`
rencontrés ensuite sont sautés.

**Le chemin de découpe n'est pas un dessin.** `W`, `W*`, `clp`, `eclp`
bornent ce qui suit ; les suivre donnerait un cadre parasite au format de
la page autour de chaque import.

### La tolérance suit l'échelle

L'aplatissement des Béziers est demandé à 0,02 mm **sur la pièce**. La
tolérance passée à `flatten_cubic` est donc divisée par l'échelle de la
matrice courante, sans quoi un dessin réduit de moitié serait aplati deux
fois plus grossièrement.

### Le CDR sort du programme

`convert_to_pdf()` appelle Inkscape ou LibreOffice sur un dossier
temporaire, lit le PDF produit, puis efface le temporaire. Sans
convertisseur, `VectorError(CDR_NOTE)` — un refus qui dit quoi faire, et
non un échec muet.

---

## 102. Séparer les tracés d'un import

`splitting.py`. Un import devient **une forme** portant N polylignes ;
tant qu'elle l'est, l'œil, la duplication, l'offset et le F2 agissent sur
elle entière.

| Fonction | Ce qu'elle rend |
|---|---|
| `frame_indices(polys)` | rangs des polylignes dont la boîte couvre 98 % de l'emprise, dans les deux axes |
| `detach_frame(shape)` | `[cadre, reste]` — le cadre **en tête**, car c'est lui qu'on va masquer |
| `explode(shape, limit)` | une forme par polyligne ; au-delà de `limit`, le reste réuni dans une dernière |

`_derive()` passe par `dataclasses.replace` : les champs ajoutés au modèle
depuis — cadre, offset, épaisseur, oscillation — suivent d'eux-mêmes. Les
énumérer à la main, c'était s'assurer d'en oublier au prochain ajout.

Côté application, `_replace_shape()` remet les morceaux **à la place de
l'original dans l'ordre** : cet ordre est l'ordre de gravure, et les
renvoyer en fin de liste changerait le travail sans qu'on l'ait demandé.

---

## 103. Export vectoriel

`vecexport.py`, sans rapport avec l'export machine. Trois formats, deux
contenus.

| | contours | trajectoires |
|---|---|---|
| source | `shape_contours` | `shape_polylines` |
| contient | le dessin posé | hachurage, épaississement, oscillation |
| poids relevé | 5 tracés | 99 tracés, pour le même document |

Le DXF sort en **R2000** — la version que tout lit encore, y compris les
logiciels d'atelier qui ont quinze ans — avec `$INSUNITS = 4` et une
`LWPOLYLINE` par polyligne, un calque par forme.

L'EPS calcule sa boîte **sur la géométrie** et ramène le dessin à
l'origine : un EPS dont le contenu est loin de sa boîte s'ouvre vide dans
la moitié des logiciels. Relu par notre propre lecteur, il rend
40,000 × 20,000 mm pour un rectangle de 40 × 20.

Le `.ai` est le même EPS avec les commentaires `%%AI8_CreatorVersion` et
`%%AI5_BeginLayer`. Illustrator l'ouvre : c'est ce qu'était le format
jusqu'à sa version 8.
