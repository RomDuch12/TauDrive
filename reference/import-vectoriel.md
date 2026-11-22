# Import vectoriel — PDF, Illustrator, EPS, SVG, CorelDRAW

Le DXF n'est pas le seul format qui arrive à l'atelier. Un client envoie
un logo en `.ai`, un bureau d'études un `.pdf`, un graphiste un `.eps`
ou un `.svg` sorti d'Inkscape.
Les rouvrir dans un autre logiciel pour les réexporter en DXF fait perdre
du temps et, surtout, de la **précision** : chaque conversion approxime
les courbes une fois de plus.

---

## 1. Ce qui est lu, et comment

| Format | Ce que c'est réellement | Lecture | Statut |
|---|---|---|---|
| `.dxf` | DXF | `ezdxf` | complet |
| `.pdf` | PDF | flux de contenu | **complet** |
| `.ai` v9 et au-delà (2000 →) | **un PDF** | flux de contenu | **complet** |
| `.ai` v8 et avant | **un EPS** | opérateurs Illustrator | **complet** |
| `.eps`, `.ps` | PostScript encapsulé | opérateurs Illustrator | **complet** |
| `.svg` | XML | lecteur propre (`svgread`) | **complet** |
| `.cdr` | CorelDRAW | convertisseur externe | **conditionnel** |

### Pourquoi le `.ai` ne pose pas de problème

Un `.ai` moderne **est un fichier PDF**. Depuis Illustrator 9 (2000),
Adobe range son format propre dans un flux privé que les autres logiciels
ignorent, et écrit **la même illustration en PDF** pour que tout le monde
puisse la lire. C'est cette part-là que TauDrive lit, et elle est
complète : c'est exactement ce qu'affiche n'importe quel lecteur PDF.

Avant la version 9, un `.ai` est un EPS PostScript — lu par l'autre voie.

Le format est reconnu **au contenu, pas au suffixe** : un `.ai` peut être
l'un ou l'autre selon la version qui l'a écrit, et se fier au nom
conduirait à refuser des fichiers parfaitement lisibles.

---

## 2. Ce qu'on interprète, et ce qu'on ignore

Un PDF ou un PostScript complet est un **langage de programmation**.
L'interpréter entièrement serait un travail sans fin et sans objet ici :
on suit les opérateurs de **tracé**, et l'on ignore le reste.

| Suivi | Ignoré |
|---|---|
| déplacements, droites, courbes de Bézier | couleurs, dégradés |
| transformations (`cm`, `ct`, `scale`, `translate`) | images matricielles |
| pile d'états (`q`/`Q`, `gsave`/`grestore`) | transparence, modes de fusion |
| rectangles (`re`) | |
| **texte** (`BT`…`ET`, `Tf`, `Tm`/`Td`, `Tj`/`TJ`) | — voir §12 |

Une gravure n'a que faire d'un aplat : c'est le **tracé** qu'elle suit.
Le texte, seul cas à cheval sur les deux colonnes, a sa propre section.

### Les chemins de découpe sont écartés

Illustrator pose systématiquement un chemin de découpe au format de la
page. Le suivre donnerait un cadre parasite autour de chaque dessin
importé. Les opérateurs `W`, `W*`, `clp` et `eclp` bornent donc ce qui
suit sans jamais entrer dans la géométrie.

### Les deux vocabulaires Illustrator

Illustrator écrit son EPS avec un vocabulaire abrégé, défini dans le
prologue. Deux générations coexistent, et un atelier reçoit des fichiers
de vingt ans d'âge aussi bien que de l'année dernière :

| | déplacement | droite | courbe | fermeture | peinture |
|---|---|---|---|---|---|
| **AI 8 et avant** | `m` | `l` `L` | `c` `C` `v` `V` `y` `Y` | *implicite* | `f` `F` `s` `S` `b` `B` `n` `N` |
| **AI 9 et au-delà** | `mo` | `li` | `cv` | `cp` | `f` `ef` `@` `S` |

Les deux sont acceptées.

La lecture commence **après le prologue** — repéré par `%%EndPageSetup`,
`%%EndSetup` ou `%%EndProlog`. Celui-ci définit des centaines de
procédures, et les interpréter demanderait un interpréteur PostScript
complet pour un résultat déjà connu. Les blocs `{...}` rencontrés ensuite
sont sautés : ce sont des procédures, jamais du tracé.

### L'en-tête binaire DOS

Un EPS écrit sous Windows commence souvent par 30 octets qui donnent la
position du PostScript, celle d'un aperçu WMF et celle d'un aperçu TIFF :

```
C5 D0 D3 C6 | offset PS (4o) | longueur PS (4o) | offset WMF | ... 
```

Le lire tel quel donnerait des octets binaires en guise d'opérateurs. Le
lecteur suit l'en-tête et se place sur la section PostScript.

---

## 3. Précision

Le contrôle porte sur un PDF **écrit à la main**, de géométrie connue au
micron — et non produit par une bibliothèque, sans quoi le contrôle
porterait sur l'accord de deux bibliothèques entre elles.

```
demandé :  226,7717 × 113,3858 pt
attendu :   80,0000 ×  40,0000 mm      (× 25,4/72)
obtenu  :   80,0000 ×  40,0000 mm
```

Sur un PDF produit par Inkscape à partir d'un SVG coté :

| Élément | Attendu | Lu |
|---|---|---|
| rectangle | 80 × 40 mm | 79,999 × 39,999 |
| cercle Ø 30 | 30 × 30 mm | 30,001 × 30,000 |
| arc de Bézier | 60 mm | 60,001 |

Les courbes sont aplaties à **0,02 mm**, la même tolérance que l'import
DXF : deux formats, une seule finesse. La tolérance est exprimée sur la
pièce, et divisée par l'échelle de la matrice courante — sans quoi un
dessin réduit de moitié serait aplati deux fois plus grossièrement.

### Sur un fichier de production

Un plan de production en EPS, Adobe Illustrator CS5, 5,2 Mo, avec
en-tête binaire DOS :

```
9 914 tracés · 98 818 points · 0,6 s
emprise 296,6 × 419,9 mm     (A3 : 297 × 420)
```

Textes vectorisés, logo, tableau, cotes : tout est lu.

---

## 4. Le CorelDRAW

**Le `.cdr` ne se lit pas nativement, et cela ne changera pas.** Le format
est propriétaire, non documenté, et change à chaque version majeure depuis
1989. Aucun lecteur libre n'en couvre toutes les versions ; le meilleur
effort, `libcdr`, s'arrête aux versions récentes et reste incomplet.

Écrire un lecteur CDR dans TauDrive reviendrait à rétro-concevoir un
format vivant, sans jamais pouvoir garantir qu'un fichier client donné
sera lu. **Deux voies pratiques, toutes deux fiables :**

### a. Exporter depuis CorelDRAW

CorelDRAW exporte nativement en **PDF, EPS, AI et DXF** — les quatre
formats que TauDrive lit, sans perte de précision. C'est la voie la plus
sûre : le dessin passe par le moteur de Corel lui-même.

### b. Laisser TauDrive convertir

Si **Inkscape** ou **LibreOffice** est installé, TauDrive s'en sert
automatiquement : le `.cdr` est converti en PDF dans un dossier
temporaire, lu, puis le temporaire est effacé.

| Convertisseur | Version minimale | Où l'obtenir |
|---|---|---|
| **Inkscape** | **1.0** | <https://inkscape.org/release/> |
| **LibreOffice** | **6.0** | <https://www.libreoffice.org/download/download-libreoffice/> |

Les deux emploient le même lecteur, `libcdr`. Inkscape est préféré : le
chemin est plus court et le PDF plus fidèle. Le convertisseur est cherché
aux emplacements d'installation habituels, puis dans le `PATH`.

### D'où viennent ces bornes

**Inkscape 1.0** est une contrainte de *TauDrive*, pas d'Inkscape : c'est
la version qui a introduit `--export-type` / `--export-filename`. Les
versions 0.9x employaient `--export-pdf`, que TauDrive sait encore appeler
— il interroge `--version` et adapte ses options — mais qui n'est plus
distribué. La lecture du CDR elle-même remonte à Inkscape **0.91** (2015),
quand `libcdr` y est entré.

**LibreOffice 6.0** est une borne de confort : `--headless --convert-to`
est stable bien avant, et `libcdr` lit le CDR depuis LibreOffice **4.0**
(2013). 6.0 est simplement le plus ancien millésime encore raisonnable à
installer aujourd'hui.

> **Ce qui est vérifié et ce qui ne l'est pas.** Inkscape 1.3 a été
> constaté sur ce poste, `libcdr-0.1.dll` compris, et le mécanisme de
> sous-processus a été validé sur une conversion réussie. La lecture d'un
> **vrai fichier `.cdr`** de bout en bout reste à confirmer : aucun n'était
> disponible pour l'essai. Les autres bornes viennent de l'historique
> documenté de ces outils.

TauDrive lit la version installée et l'affiche dans *l'aide ▸ Formats de
fichier*, avec son verdict — « convient » ou « trop ancien pour cette
commande ».

Sans convertisseur, l'import **refuse explicitement** et dit quoi faire —
il ne se contente pas d'échouer :

> Le format CorelDRAW (.cdr) est propriétaire et non documenté. Aucun
> lecteur libre n'en couvre toutes les versions, et TauDrive n'en embarque
> pas.
>
> Deux voies : exporter depuis CorelDRAW en PDF, EPS, AI ou DXF —
> TauDrive lit les quatre nativement, et sans perte de précision ; ou
> installer Inkscape, que TauDrive emploiera alors automatiquement.

---

## 5. Différences avec l'import DXF

| | DXF | PDF / AI / EPS |
|---|---|---|
| **calques** | un `Path` par calque, cochables | une seule forme |
| **unité** | réglable — l'en-tête `$INSUNITS` ment souvent | fixe, le point (1/72") |
| **pages** | — | la **première** seulement |

Ni le PDF ni le PostScript ne portent de notion de calque exploitable :
Illustrator range les siens dans son flux privé, que l'on ne lit pas. Le
choix des calques disparaît donc du dialogue pour ces formats, et le
choix d'unité aussi — un PDF porte la sienne, et la faire régler
n'ouvrirait que la porte à l'erreur.

Une seule page est lue : un dessin de gravure tient sur une page, et un
catalogue de trente pages posé d'un coup sur le plan de travail ne
rendrait service à personne.

---

## 6. Garde-fou

La lecture s'arrête à **2 millions de segments**. Une carte vectorisée
peut en porter davantage : on préfère rendre ce qui a été lu, avec un
avertissement au compte rendu, plutôt que de faire attendre l'atelier dix
minutes pour un dessin qu'il ne gravera pas.

---

## 7. Où l'import est offert

* **barre d'outils** — *Importer un dessin…* (Ctrl+I) ;
* **bibliothèque de dessins** — *Ajouter…* accepte les mêmes formats ;
* **coupon d'essai** — *Motif des cases ▸ Depuis un fichier…*

Partout, le même filtre et le même lecteur.

---

## 8. Le dessin importé arrive d'un bloc

Un fichier importé devient **une seule forme** portant des dizaines ou des
milliers de polylignes. Tant qu'elle reste d'un bloc, l'œil, la
duplication, l'offset et le F2 agissent sur elle entière.

C'est gênant surtout dans un cas, et il est fréquent : le fichier arrive
**avec un cadre** — bordure de plan, contour de page dessiné, gabarit de
découpe. Sous la règle pair-impair du hachurage, ce cadre englobe tout le
reste et **inverse le remplissage** : ce qui devait être gravé ne l'est
plus, et l'inverse.

Deux gestes, au clic droit sur la forme dans la liste :

| Geste | Ce qu'il fait |
|---|---|
| **Détacher le cadre extérieur** | les polylignes qui englobent tout le reste partent dans leur propre forme, **masquée d'emblée**. Un clic sur son œil la rend si elle servait |
| **Séparer les N tracés…** | une forme par polyligne : chacune reçoit son œil, sa duplication, son offset et son F2 |

Aucun des deux ne modifie la géométrie : ils la **répartissent**. Ce qui
part à la machine est identique, à la visibilité près. Les morceaux
gardent tous les réglages de la forme d'origine — process, cadre, offset,
épaisseur, oscillation — et sont groupés, donc déplaçables d'un bloc.

### Le critère du cadre

Une polyligne est tenue pour un cadre si sa boîte couvre **98 %** de
l'emprise totale, dans les deux axes. Pas 100 % : un cadre dessiné au
trait déborde légèrement, et un cadre tracé sur la bordure du dessin le
couvre à quelques microns près. Une forme dont *toutes* les polylignes
couvriraient l'emprise ne rend rien — ce ne serait pas un cadre, mais un
dessin fait de contours superposés.

### Le garde-fou de la séparation

Un plan de production de l'atelier porte **9 914 tracés**. Les séparer tous
donnerait autant de lignes dans la liste des formes, autant de widgets, et
une fenêtre qui ne répond plus. Au-delà de **400**, TauDrive demande
confirmation et propose de séparer les 400 premiers en laissant le reste
réuni — sans rien perdre du dessin.

---

## 9. Parcourir une bibliothèque lourde

Un plan d'atelier pèse dix mégaoctets et porte dix mille tracés. Le lire
prend une seconde ; le **garder en mémoire**, douze mégaoctets. La réserve
d'aperçus n'ayant pas de plafond, trente dessins parcourus tenaient
**362 Mo** de géométrie dont l'application n'affichait qu'une vignette de
trois cents pixels. C'est ce qui la faisait ramer, puis tomber.

Trois remèdes, qui se complètent :

| Remède | Effet |
|---|---|
| **esquisse** (`sketch.py`) | un DXF est parcouru au fil de ses codes de groupe : 0,3 s au lieu de 7 |
| **réserve bornée** | cent esquisses au plus en mémoire ; la géométrie exacte n'est **jamais** retenue |
| **vignettes sur disque** (`thumbs.py`) | un dessin déjà vu s'affiche instantanément, même après un redémarrage |

Mesuré sur six copies de ce plan de production, parcourues deux fois :

```
avant :  362 Mo retenus     (extrapolé de 12 Mo par dessin)
après :    6 Mo retenus  ·  125 ko de vignettes sur le disque
```

### La clé d'une vignette

Chemin, **taille** et **date de modification**. Un dessin remplacé sur le
partage produit une clé différente : sa vieille vignette est ignorée, et
personne ne se retrouve devant une image périmée. Une image périmée est
pire que pas d'image — on croit reconnaître, et l'on pose le mauvais
dessin.

Quatre cents vignettes sont gardées, les plus anciennes partant d'abord.
Écrire une vignette n'échoue jamais bruyamment : un disque plein ou un
dossier en lecture seule ne doit pas empêcher d'ouvrir un dessin.

### La lecture s'abandonne

Le dessin entier ne se charge que sur *Visualiser*. La lecture consulte un
signal d'arrêt tous les **20 000 jetons** — assez rare pour ne rien
coûter, assez fréquent pour qu'un clic sur *Annuler* soit pris en moins
d'un dixième de seconde sur un fichier de dix mégaoctets. Mesuré : 0,26 s
pour abandonner la lecture de ce plan de production.

`ezdxf` lit d'un bloc et n'offre pas de prise à ce signal ; un DXF se lit
en une seconde ou deux, et l'attente reste supportable.

---

## 10. Le SVG

Le SVG est lu **sans convertisseur externe** : c'est du XML, et le lire
nous-mêmes évite de dépendre d'Inkscape pour un format que tout le monde
produit.

### Les unités

Un SVG déclare sa taille deux fois, et les deux comptent :

```svg
<svg width="100mm" height="60mm" viewBox="0 0 100 60">
```

Le `viewBox` donne un repère abstrait, `width` lui donne une taille
réelle. Ici, 100 unités valent 100 mm : l'échelle est de 1. Si le fichier
disait `width="200mm"` pour le même `viewBox`, chaque unité vaudrait
2 mm, et un rectangle de 80 unités sortirait à 160 mm.

Toutes les unités CSS sont converties : `mm`, `cm`, `Q`, `in`, `pt`,
`pc`, `px`. Un nombre nu vaut des pixels, à **96 par pouce** — la
définition CSS moderne, celle qu'emploient Inkscape 1.x et les
navigateurs. Un fichier sans aucune unité est lu tel quel, une unité
valant un millimètre, et le compte rendu le dit.

> **Le piège des vieux fichiers.** Inkscape a compté 90 pixels par pouce
> jusqu'à la version 0.92 (2017). Un dessin plus ancien, dont les tailles
> sont exprimées en pixels nus, sort **6,25 % trop petit** : un carré de
> 100 mm en fait 93,75. Le rétablir demande de le grossir de 6,67 % —
> les deux pourcentages diffèrent parce qu'ils ne portent pas sur la même
> mesure, l'un sur le dessin voulu, l'autre sur celui qu'on a.
>
> C'est assez peu pour passer inaperçu à l'écran, et bien assez pour
> mettre une pièce au rebut. **TauDrive le détecte** — il lit l'attribut
> `inkscape:version` — et l'écrit en jaune dans le dialogue d'import,
> sans corriger d'office. Le remède propre est d'ouvrir le fichier dans
> un Inkscape récent et de le réenregistrer : il inscrira alors des
> unités explicites, et la question ne se posera plus.

### Le sens des ordonnées

Le SVG compte ses ordonnées **vers le bas** ; l'atelier, comme le DXF et
le PostScript, les compte vers le haut. Le dessin est donc retourné à la
lecture, et retourné de nouveau à l'écriture. Oublier l'un des deux sort
le dessin en miroir — et un aller-retour ne le verrait pas, puisque les
deux erreurs s'annulent. C'est pourquoi l'autotest contrôle **le fichier
écrit**, et non seulement le résultat d'un aller-retour.

### Ce qui est lu

Toutes les primitives géométriques : `path`, `rect` (coins arrondis
compris), `circle`, `ellipse`, `line`, `polyline`, `polygon`. Toute la
grammaire des chemins : `M m L l H h V v C c S s Q q T t A a Z z`, y
compris les formes courtes où les coordonnées s'enchaînent sans répéter
la lettre.

Les transformations sont composées à chaque niveau de groupe :
`matrix`, `translate`, `scale`, `rotate` (avec centre), `skewX`,
`skewY`.

### Ce qui est ignoré, et signalé

| Élément | Pourquoi | Ce qu'il faut faire |
|---|---|---|
| `<text>` | une police n'est pas une géométrie | *Chemin ▸ Objet en chemin* dans Inkscape |
| `<image>` | une image matricielle n'a pas de tracé | vectoriser, ou passer par le module texte |
| `<use>` | référence à un motif défini ailleurs | *Édition ▸ Cloner ▸ Délier* |

Rien de tout cela ne disparaît en silence : le compte rendu d'import les
énumère. Un texte avalé sans un mot laisserait croire le dessin complet.

### La finesse des courbes

Arcs, cercles et coins arrondis sont découpés en cordes. Le nombre de
cordes n'est **pas fixe** : il se déduit de la tolérance.

L'écart entre une corde et son arc — la *flèche* — vaut `r(1 − cos(θ/2))`.
On inverse la relation pour trouver l'angle admissible, puis on divise le
balayage. À 0,02 mm de tolérance :

| Rayon | Cordes sur un tour |
|---|---|
| 2 mm | 23 |
| 15 mm | 61 |
| 100 mm | 158 |

Un compte fixe raterait toujours d'un côté : trop grossier sur les grands
rayons, mille points inutiles sur les petits.

Le polygone obtenu est **inscrit** : ses sommets sont sur le cercle, ses
cordes en dedans. Un cercle de 30 mm mesure donc 29,98 mm sur sa boîte
englobante, l'écart valant exactement une flèche. C'est le comportement
de tous les imports de TauDrive, et il est du bon côté : une pièce
gravée légèrement en dedans se rattrape, une pièce gravée en dehors non.

---

## 11. Convertir par le clic droit de Windows

*Paramètres ▸ Menu contextuel Windows…* ajoute au clic droit de
l'explorateur, sur les fichiers DXF, PDF, AI, EPS, PS, SVG et CDR, un
sous-menu **« Convertir avec TauDrive »** vers DXF, Illustrator, SVG,
PostScript ou PDF.

C'est le **même lecteur et le même écrivain** que *Fichier ▸ Exporter* :
une conversion faite depuis l'explorateur rend exactement le fichier
qu'aurait rendu l'application ouverte.

### Ce que ça écrit, et où

| | |
|---|---|
| Le fichier converti | **à côté de l'original**, jamais à sa place |
| L'original | jamais modifié |
| Un fichier du même nom existe déjà | la conversion prend un nom numéroté : `dessin (2).dxf` |
| L'inscription au registre | `HKEY_CURRENT_USER` **uniquement** |

Rien n'est écrasé sans confirmation, parce qu'il n'y a **pas eu de
confirmation** : personne n'a vu de sélecteur de fichiers. Un
`dessin (2).dxf` se remarque et se supprime ; un dessin écrasé ne se
récupère pas.

Écrire sous `HKEY_CURRENT_USER` a trois conséquences utiles : aucun droit
d'administrateur n'est demandé, les autres comptes du poste ne sont pas
touchés, et le retrait est aussi simple que la pose.

### Sous Windows 11

Windows 11 range ce type d'entrée dans le **menu classique**, sous
« Afficher plus d'options » — ou directement avec **Maj+F10** au clavier.
Le menu court, lui, n'accepte que les entrées venant d'un paquet signé,
ce qui n'a pas de sens pour un outil d'atelier.

Ce n'est donc pas un défaut d'installation : le sous-menu est bien là,
un cran plus loin.

### Ce qui ne s'affiche jamais

Le sous-menu d'un `.dxf` ne propose pas « en DXF ». Une entrée qui ne
fait rien d'utile use la confiance qu'on accorde au menu entier.

### Après une mise à jour

La commande inscrite désigne l'emplacement de `TauDrive.exe`. Tant que le
programme reste au même endroit, une mise à jour ne casse rien.

S'il est déplacé ou réinstallé ailleurs, le clic droit échoue en silence.
Le dialogue le détecte et le dit : *« Installé, mais il désigne un autre
emplacement de TauDrive »*. Un clic sur **Installer** réinscrit le bon
chemin.

### En ligne de commande

Le menu contextuel ne fait qu'appeler ceci :

```
TauDrive.exe --convert dessin.ai --to dxf
TauDrive.exe --convert a.svg b.cdr c.eps --to dxf --dossier D:/sortie
```

Aucune fenêtre n'est ouverte. Un fichier fautif au milieu d'une sélection
n'arrête pas les autres : sur une sélection de trente dessins,
s'interrompre au premier fichier abîmé obligerait à tout recommencer. Le
code de sortie vaut 1 si au moins une conversion a échoué.

---

## 12. Le texte non vectorisé

Longtemps, un TEXT DXF, un `<text>` SVG ou une chaîne `Tj` d'un PDF
disparaissaient de l'import : ni la police AutoCAD, ni celle du poste
client n'étaient forcément les nôtres, et rendre autre chose que ce que
le concepteur voyait semblait pire que ne rien rendre.

**Ce n'est plus le cas.** Un texte absent de la pièce gravée n'est pas
une prudence, c'est un défaut : le contenu et la position comptent bien
plus que la forme exacte des lettres. Le texte est donc rendu en
contours réels — remplissables au hachurage, comme n'importe quelle
forme — dans tous les formats qui le portent :

| Format | Ce qui est suivi | Alignement |
|---|---|---|
| DXF | `TEXT`, `MTEXT` | halign (TEXT), 9 points d'ancrage (MTEXT) |
| SVG | `<text>`, `<tspan>` imbriqués | `text-anchor` |
| PDF / AI moderne | `BT…ET`, `Tf`, `Tm`/`Td`/`TD`/`T*`, `Tj`/`TJ`/`'`/`"` | matrice de texte |

Le rendu vient du même moteur que l'outil **Texte** de TauDrive
(`textvec`) : un vrai contour de police, lu avec fontTools, pas un
succédané.

### Ce qui reste approximatif, et pourquoi

* **MTEXT n'habille pas.** Un bloc trop large pour sa largeur nominale
  ne se coupe pas automatiquement en lignes ; seuls les retours `\P`
  explicites du fichier séparent les lignes. Reproduire l'habillage
  d'AutoCAD demanderait son moteur de mise en page.
* **Le PDF ne résout pas la police par ressource.** Savoir précisément
  quelle police porte quel `Tf` demanderait de suivre les dictionnaires
  `/Resources /Font`, objet par objet. TauDrive prend à la place le nom
  `/BaseFont` le plus fréquent du document entier — exact quand un seul
  document n'emploie qu'une police, ce qui est le cas courant ; une
  approximation documentée sinon.
* **Le PostScript ancien (AI8 et avant) n'est pas suivi.** Son texte se
  pose par `show`, un mécanisme distinct de `Tf`/`Tj`. En pratique, les
  fichiers de cette génération arrivent déjà avec leur texte vectorisé.

Ce qui ne peut vraiment pas être rendu — une chaîne vide, une police
sans le moindre glyphe pour ces caractères — reste compté et signalé
dans le compte rendu d'import, plutôt que de disparaître sans un mot.

### La police manquante

Un dessin déclare sa police par son **nom** — jamais le fichier. Quand
ce nom n'est pas sur le poste, TauDrive :

1. cherche une police installée du même nom (tolérant sur la casse et
   les suffixes de graisse) ;
2. sinon, essaie un alias connu (`Helvetica` → Arial, `Times` → Times
   New Roman…) ;
3. sinon, **demande** — une boîte de dialogue propose les polices
   installées, et le choix est **mémorisé pour ce nom, définitivement** :
   il ne sera plus jamais redemandé, sur ce poste ;
4. en ligne de commande ou en fond (bibliothèque, coupon), retombe
   silencieusement sur une police par défaut plutôt que de bloquer.

Ce sont des **caractères accentués et internationaux** que ce mécanisme
sert le plus souvent : un dessin français plein d'apostrophes, d'accents
ou de guillemets français employait fréquemment une police que le poste
de gravure n'a pas — le texte disparaissait entièrement. Il est rendu
maintenant, avec la police la plus proche disponible.

Le choix se retire depuis `fontmap.forget(nom)` si une police installée
plus tard doit reprendre la main ; il n'y a pas encore de bouton dédié
dans l'interface pour cela — un remplacement d'installation reste rare.

---

## 13. TauConvert : la version réduite

`TauConvert.exe` est TauDrive **amputé de tout ce qui grave**. Il
s'adresse aux postes qui n'ont pas de machine : un bureau d'études, un
poste de préparation, l'ordinateur de quelqu'un qui reçoit des dessins
clients et doit les rendre en DXF.

### Ce qu'il fait

Trois choses, et rien d'autre :

1. **poser** le sous-menu « Convertir avec TauDrive » au clic droit, ou
   le **retirer** ;
2. **convertir** les fichiers que ce menu lui envoie ;
3. **expliquer** en quelques lignes comment s'en servir.

Une seule fenêtre, sans menu ni barre d'outils : un mode d'emploi, deux
boutons, une ligne d'état.

### Ce qu'il ne porte pas — et pourquoi

| Absent | |
|---|---|
| `engrave.app` | le plan de travail et toute l'application de gravure |
| `jpt`, `cl90135` | les protocoles machine |
| `serial` | le port série |
| `shapely` | la géométrie du couteau |

**Un poste de bureau n'a aucune raison de porter une commande de
laser**, et lui en donner une est un risque qu'on ne prend pas. Ce n'est
pas une question de taille de fichier : l'autotest de cette version
vérifie explicitement que ces modules sont absents, et échoue si l'un
d'eux revient par une dépendance oubliée.

Le dossier pèse 175 Mo au lieu de 220 — c'est un effet secondaire, pas
l'objet.

### La conversion est la même

Exactement la même : le même lecteur et le même écrivain, au même module
près. Un DXF produit par `TauConvert.exe` est identique, à l'octet,
à celui qu'aurait produit `TauDrive.exe`.

### Quand les deux cohabitent

Les deux exécutables se partagent **volontairement** la même clé de
registre : sinon un poste qui aurait les deux offrirait deux sous-menus
identiques au clic droit, et personne ne saurait lequel choisir.

Chacun s'inscrit lui-même. Le dernier qui clique sur *Installer*
l'emporte, et l'état de l'autre le dit en **nommant** l'exécutable
inscrit :

> Installé, mais le clic droit appelle `TauConvert.exe`.
> Cliquez sur Installer pour qu'il appelle celui-ci à la place.

### Empaquetage

```bash
cd atelier && pyinstaller --clean --noconfirm TauConvert.spec
dist/TauConvert/TauConvert.exe --autotest
```

Recette séparée, et non une cible de plus dans `TauDrive.spec` : les
deux exécutables de cette dernière partagent leurs dépendances par
`MERGE`, ce qui est précisément ce qu'on ne veut pas — le convertisseur
doit pouvoir se copier **seul** sur un poste.

---

## 14. Les cotations d'un DXF

Une cotation ne porte pas sa géométrie. Un `DIMENSION` renvoie à un
**bloc anonyme** (`*D7`) qui contient le dessin réel : lignes d'attache,
ligne de cote, flèches, et le texte de la mesure.

C'est pourquoi elles étaient perdues : la liste des entités ignorées les
écartait avant qu'on ait regardé ce qu'elles contenaient.

### Ce qui est éclaté

| Entité | Ce qu'elle contient |
|---|---|
| `INSERT` | un bloc, imbriqué jusqu'à 8 niveaux |
| `DIMENSION` | lignes d'attache, ligne de cote, flèches, texte de mesure |
| `LEADER` | ligne de repère et sa flèche |
| `MULTILEADER` | ligne de repère, texte, remplissage |
| `ACAD_TABLE` | filets et textes de cellule d'un cartouche |

L'`OLE2FRAME` n'y est **pas** : c'est un objet incorporé — une image, un
tableur — sans géométrie à en tirer. `ezdxf` ne lui offre d'ailleurs pas
`virtual_entities`.

### Pourquoi éclater plutôt que traiter à part

Deux raisons, et la seconde est la vraie.

Le texte de cote passe par le rendu de texte comme n'importe quel MTEXT :
un seul chemin, une seule police, une seule substitution.

Et surtout, **le texte y est déjà résolu**. Le fichier porte :

```
{\fArial|b0|i0|c0|p34;\C256;%%C\Fromans|c0;<> pour goupille cylindrique}
```

Le `<>` est un emplacement pour la mesure, `%%C` le symbole Ø.
`virtual_entities()` rend `Ø6+0,06/+0,02 pour goupille cylindrique` — la
mesure calculée, le symbole résolu. Refaire ce calcul à la main aurait
surtout été le refaire faux.

### Les points de définition

Un `POINT` sur une cotation marque une origine de mesure. Il ne se grave
**jamais** — AutoCAD ne le trace pas davantage, et les range sur un
calque `Defpoints` qui n'est pas imprimé. Les compter comme « non géré »
aurait fait un compte rendu bavard et faux.

### Les tolérances empilées

AutoCAD empile une tolérance avec `\S+0,06^+0,02;` : le premier terme
au-dessus du second, en demi-hauteur. Aplati, cela sort `+0,06^+0,02` —
le `^` est un **code de contrôle**, pas un caractère.

TauDrive rend `+0,06/+0,02`, la forme en ligne conventionnelle d'une
tolérance sur un dessin technique. Empiler vraiment demanderait deux
demi-lignes et un calcul de position ; sur quatre occurrences d'un plan,
la barre oblique dit la même chose et se lit.

Le remplacement ne s'applique **que** si le fichier portait un
empilement : sans cela, un accent circonflexe tapé à la main dans un
commentaire deviendrait une barre oblique.

---

## 15. Les calques que la CAO ne dessine pas

Trois états rendent un calque invisible, et ils ne disent pas la même
chose :

| État | Ce que ça veut dire | Exemple rencontré |
|---|---|---|
| **éteint** (`off`) | masqué à l'écran, volontairement | — |
| **gelé** (`frozen`) | masqué et exclu des calculs | `*ADSK_ASSOC_ENTITY_BACKUPS` |
| **non tracé** (`plot = 0`) | visible à l'écran, jamais imprimé | `Defpoints` |

Dans les trois cas, ce qui s'y trouve n'apparaît pas sur le plan que le
concepteur a validé. TauDrive les écarte, et **dit lesquels** dans le
compte rendu d'import :

```
calque « Defpoints » non tracé : 132 entité(s) non importée(s)
```

Les deux cas rencontrés sur un fichier réel valent d'être nommés.
`Defpoints` porte les points de définition des cotations.
`*ADSK_ASSOC_ENTITY_BACKUPS` porte les sauvegardes de la géométrie
associative d'AutoCAD : elle **double** ce qui est déjà dessiné, et la
graver marquerait deux fois le même trait.

Ce module promettait déjà que « ce qui est visible dans le DXF est ce
qui est gravé ». Sans ce relevé, la promesse était fausse.

---

## 16. Mesuré sur un plan de production

Un plan de production client — un plan A3 double, AutoCAD 2013,
cotations et cartouche complets.

| | Avant | Après |
|---|---|---|
| Polylignes lues | 148 | **2 478** |
| Calque COTATIONS | 44 | **705** |
| Calque CARTOUCHE | 4 | **1 564** |
| Entités écartées comme texte | 48 | **0** |
| Calque `Defpoints` | 2 tracés gravés à tort | **écarté, et dit** |

Ce qui reste dehors : 4 `OLE2FRAME`, qui n'ont pas de géométrie.
