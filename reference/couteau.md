# Couteau — donner une épaisseur à un tracé

Un tracé de dessin n'a pas d'épaisseur : c'est une ligne, et la machine la
suit d'un passage de faisceau large de trois centièmes. Un **couteau**, lui,
a une largeur — la lame fait deux dixièmes, la saignée aussi.

Le couteau transforme donc une **ligne** en son **contour** : le bord de la
bande que la ligne balaierait si elle avait cette largeur. Ce qui sort est un
ou plusieurs **contours fermés, sans aucune auto-intersection**.

*Barre d'outils ▸ Couteau…* (**Ctrl+K**), ou clic droit sur la forme.

---

## 1. Pourquoi ce n'est pas l'épaisseur de trait

TauDrive avait déjà de quoi élargir un trait — `line_width_mm`, qui pose des
**passages parallèles**. Ce n'est pas la même chose, et la différence est
entière :

| | épaisseur de trait | couteau |
|---|---|---|
| rend | des passages parallèles | un **contour fermé** |
| sert à | graver un trait large | décrire le **bord** d'une bande |
| aux angles fermés | les passages se croisent | le contour se referme proprement |
| ensuite | ça part à la gravure, et c'est tout | ça se hachure, se décale d'un offset, s'exporte en DXF pour une découpe |

Un contour fermé est une **forme**. Un faisceau de passages parallèles est un
**parcours**. On ne peut ni remplir, ni décaler, ni découper un parcours.

---

## 2. Ce que « sans intersection » exige

C'est toute la difficulté, et elle est sous-estimée.

Décaler une ligne de part et d'autre puis refermer les bouts paraît suffire.
Ça ne l'est pas :

* dès qu'un **angle est un peu fermé**, le décalage extérieur repart en
  arrière et croise le reste — la boucle qu'on connaît déjà de
  `prune_offset` ;
* sur une ligne **qui se croise elle-même** — un « 8 », une signature, un
  paraphe — la bande se recouvre, et le contour naïf a autant
  d'intersections que le tracé a de croisements ;
* sur une **spirale serrée**, les tours voisins se touchent et doivent
  fusionner en une seule forme.

Il faut donc **unir la bande à elle-même**. C'est une opération booléenne sur
polygones, pas un décalage — et les deux ne se ressemblent que de loin.

TauDrive emploie **GEOS**, par `shapely` : `LineString.buffer()` rend le
polygone exact de la bande, trous compris.

### Vérifié, pas supposé

| Cas | Contours | Verdict |
|---|---|---|
| trait droit | 1 | propre |
| angle de 5° | 1 | propre |
| tracé en huit | 3 (1 extérieur + 2 trous) | propre |
| contour fermé → anneau | 2 | propre |
| deux traits en T | **1** — les deux unis | propre |
| spirale à tours jointifs | 1 | propre |

Et la géométrie tombe juste, pas seulement propre :

```
trait de 50 mm, lame de 2 mm, bouts arrondis
  emprise attendue   52,00 × 2,00 mm      obtenue  52,00 × 2,00
  aire attendue      50×2 + π×1²  = 103,14 mm²   obtenue  103,14
```

Avec des **bouts nets**, l'emprise retombe à 50,00 mm : la bande s'arrête sur
le dernier point.

### Le contrôle fait partie de la fonction

`knife.check()` vérifie chaque contour rendu : fermé, et **simple** au sens
de GEOS — il ne se croise pas lui-même. C'est la promesse de la fonction, et
elle se vérifie plutôt qu'elle ne s'affirme. Le dialogue refuse de poser un
résultat qui ne passe pas.

Le contrôle attrape bien un contour fautif : un nœud papillon
`(0,0)→(10,10)→(10,0)→(0,10)→(0,0)` est signalé « il se croise lui-même ».

---

## 3. Les réglages

| Réglage | Ce qu'il fait |
|---|---|
| **Largeur de lame** | largeur de la bande. Le tracé en est le **milieu** : elle déborde de moitié de chaque côté |
| **Bouts** | arrondi (demi-cercle), net (s'arrête sur le point), carré (dépasse d'une demi-largeur). Sans effet sur un contour fermé, qui n'a pas de bout |
| **Raccords** | arrondi (le plus sûr, jamais de pointe), onglet (prolongé jusqu'à la pointe), chanfrein (pointe coupée droit) |
| **Garder l'origine masquée** | le tracé nu reste dans le document, œil fermé : on y revient si la largeur ne convient pas |

La **limite d'onglet** vaut 4. Sans elle, un angle de deux degrés produirait
une pointe de trente fois la largeur de la lame — une aiguille que rien ne
peut couper.

Les arrondis sont discrétisés en **16 segments par quart de cercle** : sur
une lame de 0,2 mm, l'écart à l'arc est inférieur au micron, trente fois plus
fin que le spot.

La largeur minimale est **0,005 mm**. En deçà on est sous le diamètre du
faisceau, et le contour ne veut plus rien dire — la fonction refuse plutôt
que de rendre une lame qui n'existe pas.

---

## 4. Deux tracés qui se touchent n'en font qu'un

Tous les tracés de la sélection sont **unis en une seule opération**. La
barre et le montant d'un « T » donnent un contour, pas deux qui se
chevauchent.

C'est pourquoi le couteau travaille dans le repère du **plan de travail** et
non dans celui de chaque forme : deux formes qui se touchent doivent fusionner.

---

## 5. Un contour fermé donne un anneau

La bande straddle la ligne : un bord dehors, un bord dedans. Le couteau posé
sur un rectangle de 40 × 20 avec une lame de 2 mm rend donc **deux** contours
— extérieur 923 mm², trou 684 mm² — et la bande vaut la différence, 239 mm².

La règle pair-impair du hachurage s'y retrouve seule : l'anneau se remplit
entre ses deux bords, et pas au milieu.

---

## 6. Ce que le couteau demande

`shapely`, qui embarque GEOS. **Sans lui, la fonction refuse** et le dit :

> La fonction couteau demande la bibliothèque « shapely », qui n'est pas
> installée. Elle calcule l'union exacte de la bande, ce qu'un simple
> décalage ne sait pas faire : sur un angle fermé ou un tracé qui se croise,
> le contour se recouvrirait lui-même.
>
> TauDrive préfère ne rien rendre plutôt qu'une lame fausse.

Un repli approché aurait été facile à écrire. Il aurait aussi produit des
lames fausses sur exactement les cas où l'on a besoin du couteau — et une
lame fausse coupe au mauvais endroit.

---

## 7. À quoi cela sert, ensuite

Le contour posé est une forme comme une autre. On peut donc :

* le **hachurer** — la bande se grave pleine, et non par passages ;
* lui appliquer un **offset** — pour compenser la largeur du faisceau sur la
  découpe ;
* l'**exporter en DXF** vers une découpeuse ou un bureau d'études ;
* le **séparer** en ses contours si l'on veut traiter le trou à part.

C'est ce que l'épaisseur de trait ne permettait pas.
