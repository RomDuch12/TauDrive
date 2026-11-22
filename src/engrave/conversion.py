"""Convertir en tracé, retourner en miroir / Paths and mirroring.

**Convertir en tracé** fige une forme en polylignes : un texte, un
rectangle, une ellipse deviennent un tracé, comme un DXF importé. On y
gagne tout ce qu'un tracé sait faire — séparer ses contours, les
retourner, les déformer au F2 dans un seul axe sans toucher à la police —
et l'on y perd ce qui faisait la forme : un texte converti ne se retape
plus, un champ variable est figé à sa valeur du moment. Ce qui part à la
machine est identique : mêmes contours, mêmes réglages — cadre, décalage,
épaisseur, process.

**Retourner** une sélection la renverse autour de son centre, de gauche à
droite ou de haut en bas — pour graver au dos d'un verre, ou poser deux
pièces en vis-à-vis. Un rectangle ou une ellipse sont symétriques : seuls
leur place et leur angle changent. Un tracé se retourne point par point.
Un texte doit d'abord être converti ; un **code 2D ne se retourne pas** :
retourné, il ne se lit plus de face, et une pièce marquée d'un code que
le lecteur refuse est perdue.
"""
from __future__ import annotations

import dataclasses

from .model import Circle, Code, Path, Rect, Shape, Text
from .resize import selection_center
from .toolpath import own_contours

#: Formes qu'on sait figer en tracé.
CONVERTIBLES = (Text, Rect, Circle)


def convertible(shape: Shape) -> bool:
    return isinstance(shape, CONVERTIBLES)


def en_trace(shape: Shape, context: dict | None = None) -> Path:
    """Le tracé qui grave exactement ce que grave `shape`.

    Les contours sont pris dans le repère local, **avant** rotation : le
    tracé garde l'angle de la forme, que le F2 et l'inspecteur continuent
    de régler. Tous les réglages communs — cadre, décalage, épaisseur,
    process, groupe, visibilité — sont repris tels quels, par le modèle
    lui-même : un champ ajouté plus tard suivra sans qu'on y pense.
    """
    communs = {f.name: getattr(shape, f.name)
               for f in dataclasses.fields(Shape)}
    communs['name'] = shape.display_name()
    return Path(polylines=[list(c) for c in own_contours(shape, context)],
                **communs)


def retournable(shapes: list[Shape]) -> bool:
    """Vrai si la sélection peut se retourner telle quelle : ni texte à
    convertir d'abord, ni code."""
    return not any(isinstance(s, (Text, Code)) for s in shapes)


def retourner(shapes: list[Shape], axe: str) -> list[Shape]:
    """Retourne les formes autour du centre de leur emprise commune.

    `axe` : 'h' renverse de gauche à droite, 'v' de haut en bas. Les
    textes et les codes doivent avoir été écartés — voir `retournable`.
    Rend les formes dans le même ordre ; **un tracé revient sous un objet
    neuf**, que l'appelant remet à sa place dans le document.

    Pour une forme tournée de θ, retourner revient à garder sa géométrie
    locale retournée et à prendre l'angle −θ : la symétrie et la rotation
    ne commutent qu'au prix de ce changement de signe.

    Pourquoi un objet neuf : les trajectoires d'un tracé sont mémorisées
    sous une clé qui retient l'objet et les extrémités de son premier
    contour (`toolpath.geometry_key`). Un « D » dont le premier contour
    part et revient sur l'axe garde ces extrémités une fois retourné : le
    même objet aurait gardé ses anciennes trajectoires, et gravé le « D »
    à l'endroit.
    """
    if axe not in ('h', 'v'):
        raise ValueError(f'axe inconnu : {axe!r}')
    if not retournable(shapes):
        raise ValueError('un texte ou un code ne se retourne pas tel quel')
    if not shapes:
        return []
    cx, cy = selection_center(shapes)
    sortie: list[Shape] = []
    for s in shapes:
        x, y = (2 * cx - s.x, s.y) if axe == 'h' else (s.x, 2 * cy - s.y)
        angle = -s.rotation_deg % 360.0 if s.rotation_deg else 0.0
        if isinstance(s, Path):
            if axe == 'h':
                polys = [[(-px, py) for px, py in p] for p in s.polylines]
            else:
                polys = [[(px, -py) for px, py in p] for p in s.polylines]
            sortie.append(dataclasses.replace(s, x=x, y=y,
                                              rotation_deg=angle,
                                              polylines=polys))
        else:
            s.x, s.y, s.rotation_deg = x, y, angle
            sortie.append(s)
    return sortie
