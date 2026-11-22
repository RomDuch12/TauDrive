"""Séparer les tracés d'un dessin importé / Splitting imported paths.

Un DXF, un PDF ou un Illustrator arrive comme **une seule forme** portant
des dizaines ou des milliers de polylignes. Tant qu'elle reste d'un bloc,
on ne peut ni en masquer une, ni en décaler une, ni en redimensionner une
seule : l'œil, la duplication, l'offset et le F2 agissent sur la forme
entière.

C'est gênant surtout dans un cas, et il est fréquent : le fichier arrive
**avec un cadre** — bordure de plan d'assemblage, contour de page dessiné,
gabarit de découpe. Sous la règle pair-impair du hachurage, ce cadre
englobe tout le reste et **inverse le remplissage** : ce qui devait être
gravé ne l'est plus, et l'inverse.

Deux gestes, du plus chirurgical au plus large :

* **détacher le cadre** — les polylignes qui englobent tout le reste
  partent dans leur propre forme. Un clic sur leur œil, et le
  remplissage redevient juste. C'est presque toujours ce qu'il faut ;
* **séparer les tracés** — une forme par polyligne. Le contrôle complet,
  au prix d'une liste qui peut devenir longue.

Aucun des deux ne modifie la géométrie : ils la **répartissent**. Ce qui
part à la machine est identique, à la visibilité près.

C'est le **groupe** qui tient cette promesse pour le remplissage. Les
morceaux sortent groupés, et le pair-impair vaut entre les membres d'un
groupe comme entre les polylignes d'une forme : le trou du « O », devenu
une forme à lui, reste un trou. Dégroupés, les morceaux se remplissent
chacun pour soi ; regroupés, ils retrouvent l'alternance — voir
`toolpath.group_zones`.
"""
from __future__ import annotations

import dataclasses

from . import geometry as G
from .model import Circle, Path, Rect, Shape, Text

#: Au-delà, séparer produit une liste que personne ne lira.
#:
#: Un plan de production de l'atelier en porte 9 914 : autant de lignes dans la
#: liste des formes, autant de widgets, et une fenêtre qui ne répond plus.
#: L'appelant doit demander confirmation au-delà de ce seuil.
BUSY_COUNT = 400

#: Fraction de l'emprise totale qu'une polyligne doit couvrir pour être
#: tenue pour un cadre.
#:
#: 0,98 et non 1 : un cadre dessiné au trait déborde légèrement du reste,
#: et un cadre tracé exactement sur la bordure du dessin le couvre à
#: quelques microns près. Trop bas, on détacherait un contour légitime.
FRAME_COVER = 0.98


def polyline_count(shape: Shape) -> int:
    return len(getattr(shape, 'polylines', ()) or ())


def splittable(shape: Shape) -> bool:
    """Vrai si la forme porte plus d'une polyligne à séparer."""
    return isinstance(shape, Path) and polyline_count(shape) > 1


def frame_indices(polylines: list[G.Polyline]) -> list[int]:
    """Rangs des polylignes qui **englobent tout le reste**.

    Le critère est l'emprise, et non l'appartenance point par point : un
    cadre est un rectangle qui couvre le dessin entier, et cela se voit à
    sa boîte. Chercher mieux — un vrai test d'inclusion — coûterait cher
    sans rien changer au résultat sur les fichiers réels.

    Une forme dont **toutes** les polylignes couvriraient l'emprise ne
    rend rien : ce ne serait pas un cadre, mais un dessin fait de
    contours superposés.
    """
    if len(polylines) < 2:
        return []
    total = G.bounds(polylines)
    if total is None:
        return []
    x1, y1, x2, y2 = total
    large, haut = max(x2 - x1, 1e-9), max(y2 - y1, 1e-9)

    trouves = []
    for rang, poly in enumerate(polylines):
        b = G.bounds([poly])
        if b is None:
            continue
        if ((b[2] - b[0]) >= large * FRAME_COVER
                and (b[3] - b[1]) >= haut * FRAME_COVER):
            trouves.append(rang)
    return [] if len(trouves) == len(polylines) else trouves


def detach_frame(shape: Path) -> list[Path] | None:
    """Sépare le cadre du dessin. Rend `[cadre, reste]`, ou `None`.

    Le cadre vient **en tête** : c'est lui qu'on va masquer, et il doit
    tomber sous la main dans la liste des formes.
    """
    rangs = set(frame_indices(shape.polylines))
    if not rangs or len(rangs) >= len(shape.polylines):
        return None
    cadre = [p for i, p in enumerate(shape.polylines) if i in rangs]
    reste = [p for i, p in enumerate(shape.polylines) if i not in rangs]
    nom = shape.display_name()
    return [
        _derive(shape, cadre, f'{nom} — cadre'),
        _derive(shape, reste, nom),
    ]


def explode(shape: Path, limit: int = 0) -> list[Path]:
    """Une forme par polyligne, dans l'ordre du dessin.

    `limit` borne le nombre de formes produites ; 0 ne borne rien. La
    borne n'écarte rien : les polylignes au-delà restent réunies dans une
    dernière forme, faute de quoi séparer perdrait du dessin.

    **Un dessin encadré** — gravé en négatif — donne son cadre à part, en
    tête, et des morceaux sans cadre. Chaque morceau gardait le sien,
    mesuré sur lui seul : autant de rectangles que de tracés, au lieu du
    seul cadre autour du dessin. Groupé avec les morceaux, ce cadre les
    creuse comme il creusait le dessin entier — voir
    `toolpath.group_zones`.
    """
    polys = [p for p in shape.polylines if len(p) >= 2]
    if len(polys) < 2:
        return [shape]
    nom = shape.display_name()
    if limit and len(polys) > limit:
        seules, groupe = polys[:limit], polys[limit:]
    else:
        seules, groupe = polys, []
    out = [_derive(shape, [poly], f'{nom} — tracé {i + 1}')
           for i, poly in enumerate(seules)]
    if groupe:
        out.append(_derive(shape, groupe,
                           f'{nom} — {len(groupe)} tracés restants'))
    if getattr(shape, 'frame', 'none') == 'none':
        return out
    from .toolpath import own_contours, shape_frame
    contour = shape_frame(shape, own_contours(shape))
    for morceau in out:
        morceau.frame = 'none'
    if not contour:
        return out
    # le cadre n'est pas décalé : l'offset vaut pour le dessin, comme dans
    # `toolpath.shape_contours`
    cadre = _derive(shape, [contour], f'{nom} — cadre')
    cadre.frame, cadre.frame_offset_mm = 'none', 0.0
    # marqué : il n'entre pas dans le compte du décalage de son groupe,
    # comme il n'entrait pas dans celui du dessin — voir `group_zones`
    cadre.detached_frame = True
    return [cadre] + out


#: Formes qu'on sait combiner : tout ce qui se fige en tracé. Un code 2D
#: reste à part — il se remplit module par module, et pris dans le
#: pair-impair d'un dessin, il ne se lirait plus.
COMBINABLES = (Path, Rect, Circle, Text)


def combinable(shape: Shape) -> bool:
    return isinstance(shape, COMBINABLES)


def combine(shapes: list[Shape], context: dict | None = None) -> Path | None:
    """Réunit des formes en **un seul tracé** — l'inverse de séparer.

    Toutes les polylignes passent dans une même forme, comme un DXF
    importé d'un bloc : elles se remplissent ensemble, en pair-impair — le
    rond posé dans un carré y devient un trou —, et le cadre, le décalage,
    l'épaisseur s'appliquent au dessin entier. Le tracé prend les réglages
    de la **première** forme dans l'ordre de gravure, sa process comprise.

    La géométrie est prise **placée** — rotation et position de chaque
    forme — puis recentrée sur son emprise : rien ne bouge sur la plaque.
    Les textes et les formes simples sont figés comme par *Convertir en
    tracé* ; leur cadre n'est pas repris, c'est celui de la première forme
    qui entoure le tout.

    Les codes et les formes masquées restent à part. Rend `None` s'il
    reste moins de deux formes à réunir.
    """
    retenues = [s for s in shapes if combinable(s) and s.visible]
    if len(retenues) < 2:
        return None
    from .toolpath import own_contours, place
    monde = [p for s in retenues for p in place(own_contours(s, context), s)
             if p]
    boite = G.bounds(monde)
    if boite is None:
        return None
    cx, cy = (boite[0] + boite[2]) / 2, (boite[1] + boite[3]) / 2
    tete = retenues[0]
    communs = {f.name: getattr(tete, f.name)
               for f in dataclasses.fields(Shape)}
    groupes = {s.group for s in retenues}
    communs.update(
        id=Path().id, x=cx, y=cy, rotation_deg=0.0,
        # un tracé qui réunit les membres d'un même groupe y reste, avec
        # ce qui n'a pas été combiné — un code laissé à part, par exemple
        group=groupes.pop() if len(groupes) == 1 else '',
        role='', detached_frame=False)
    return Path(polylines=[G.translate(p, -cx, -cy) for p in monde],
                **communs)


def uncombinable(shape: Shape, context: dict | None = None) -> bool:
    """Vrai si *Décombiner* a quelque chose à séparer : un tracé de
    plusieurs polylignes, ou un texte de plusieurs contours."""
    if splittable(shape):
        return True
    if not isinstance(shape, Text):
        return False
    from .toolpath import own_contours
    return len(own_contours(shape, context)) > 1


def _derive(shape: Path, polylines: list[G.Polyline], name: str) -> Path:
    """Une forme reprenant tous les réglages de `shape`, sauf sa géométrie.

    Passe par `dataclasses.replace` : les champs ajoutés au modèle depuis
    — cadre, offset, épaisseur, oscillation — suivent d'eux-mêmes. Les
    énumérer à la main, c'était s'assurer d'en oublier au prochain ajout.
    """
    neuve = dataclasses.replace(shape, polylines=[list(p) for p in polylines],
                                name=name, group='')
    neuve.id = Path().id            # une identité propre, jamais partagée
    return neuve
