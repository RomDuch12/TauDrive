"""Remplissage en anneaux : des boucles parallèles au contour.

Le hachurage balaie la forme en rangées. Enchaînées en zigzag, elles ne
coûtent plus d'allumage — mais chaque **demi-tour** au bout d'une
rangée reste un virage plus fermé que les 89° du SkyWrite, dès que le
bord n'est pas exactement perpendiculaire aux rangées : le trait
s'arrête, le miroir freine, repart. Sur le DataMatrix dessiné de
l'atelier (`TROP LONG`), le zigzag fait tomber les allumages de 2 623 à
503, mais ajoute 2 088 de ces demi-tours : 12,4 s estimées à 200 m/min
au lieu de 13,8.

Les **anneaux** suivent le contour, de plus en plus rentrés, à un pas
de distance l'un de l'autre. Pas de demi-tour : un anneau tourne avec
la forme, et ses seuls virages serrés sont ceux du dessin lui-même —
une pointe de « V », un angle aigu. Sur le même DataMatrix : 178
allumages, 111 virages, 1,7 s estimées à 100 m/min au lieu de 8,4.
Reliés entre eux par un pont court et en biais, ils font une spirale :
un allumage par île de remplissage, ou presque.

**Où ils passent.** Le contour est toujours gravé ; le premier anneau
est donc à un pas du bord, le suivant à deux, et ainsi de suite. Au
cœur d'un trait, ce qui reste entre le dernier anneau et l'axe peut
dépasser un demi-pas : un anneau d'appoint s'y ajoute, comme dans une
pointe, un empattement fin ou un col étroit que les anneaux n'atteignent
pas. Aucun point de la forme ne reste à plus d'un demi-pas d'un trait —
la règle du hachurage.

**Rien hors du dessin.** Un anneau est intérieur par construction ; un
pont n'est posé que s'il est entier dans la zone, et s'il n'ajoute
aucun virage serré.

Le calcul passe par GEOS (`shapely`), comme le couteau. Sans lui,
`fill` rend `None` et l'appelant revient au hachurage.
"""
from __future__ import annotations

import math

from . import geometry as G

#: Arcs d'un quart de tour découpés en autant de segments. Quatre
#: donnent 22,5° de virage par sommet : bien loin du SkyWrite.
_QUAD_SEGS = 4

#: Distance au trait le plus proche, en pas, au-delà de laquelle un
#: anneau d'appoint s'impose.
TOLERANCE = 0.6


def available() -> bool:
    """Vrai si le moteur géométrique est là."""
    try:
        import shapely                                    # noqa: F401
    except ImportError:
        return False
    return True


def fill(contours: list[G.Polyline], step: float, inset: float = 0.0,
         link: bool = False) -> list[G.Polyline] | None:
    """Les anneaux qui remplissent `contours` (règle pair-impair).

    `step` : distance entre deux anneaux, en mm — le pas de hachurage.
    `inset` : retrait du remplissage, ajouté à chaque anneau.
    `link` : relier les anneaux en spirales (moins d'allumages).
    `None` si `shapely` manque.
    """
    if step <= 0 or not contours:
        return []
    try:
        from shapely.geometry import Polygon
        from shapely.validation import make_valid
    except ImportError:
        return None
    polygones = []
    for c in contours:
        if len(c) < 3:
            continue
        if c[0] != c[-1]:
            # le hachurage referme de lui-même un contour ouvert : un
            # triangle de trois points qui sert de trou doit rester un trou
            c = list(c) + [c[0]]
        if len(c) < 4:
            continue
        p = make_valid(Polygon(c))
        if not p.is_empty and p.area > 1e-12:
            polygones.append(p)
    zone = _pair_impair(polygones)
    if zone is None or zone.is_empty:
        return []
    sortie: list[G.Polyline] = []
    for partie in _parts(zone):
        boucles = _anneaux(partie, step, max(0.0, inset))
        if link:
            sortie.extend(_spirales(boucles, partie, step))
        else:
            sortie.extend(b for _niveau, b in boucles)
    return sortie


def _pair_impair(polygones: list):
    """Union pair-impair : un contour dans un contour fait un trou.

    Par moitiés, pour rester en n log n sur un texte de mille contours.
    """
    if not polygones:
        return None
    if len(polygones) == 1:
        return polygones[0]
    m = len(polygones) // 2
    a, b = _pair_impair(polygones[:m]), _pair_impair(polygones[m:])
    return a.symmetric_difference(b)


def _parts(geom) -> list:
    """Les polygones d'une géométrie shapely, quelle qu'elle soit."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == 'Polygon':
        return [geom]
    out = []
    for g in getattr(geom, 'geoms', []):
        out.extend(_parts(g))
    return out


def _loops(geom) -> list[G.Polyline]:
    """Les bords d'une géométrie, la matière toujours à gauche.

    Extérieur dans le sens trigonométrique, trous dans l'autre : deux
    anneaux voisins courent alors dans le même sens, ce qui permet de
    passer de l'un à l'autre sans demi-tour.
    """
    from shapely.geometry.polygon import orient
    out: list[G.Polyline] = []
    for p in _parts(geom):
        p = orient(p, 1.0)
        for anneau in [p.exterior, *p.interiors]:
            pts = [(float(x), float(y)) for x, y in anneau.coords]
            if len(pts) >= 4:
                out.append(pts)
    return out


def _anneaux(partie, step: float,
             inset: float) -> list[tuple[float, G.Polyline]]:
    """Les anneaux d'une île, du bord vers le cœur, avec leur niveau."""
    def rentre(d: float):
        return partie.buffer(-d, join_style='round', quad_segs=_QUAD_SEGS)

    # en deçà, un reste n'est qu'un éclat d'angle droit, déjà sous le
    # faisceau du contour ou de l'anneau voisin
    aire_min = step * step / 4
    boucles: list[tuple[float, G.Polyline]] = []
    k = 1
    courant = rentre(inset + step)
    # le demi-pas avant le premier anneau : un trait plus fin que deux
    # pas, une pointe, que le premier anneau n'atteint pas
    moitie = rentre(inset + TOLERANCE * step)
    while True:
        if courant.is_empty and moitie.is_empty:
            break
        # ce que le demi-pas contient et que l'anneau suivant, regonflé
        # d'un demi-pas, ne couvre pas : un cœur de trait, une pointe
        couvert = courant.buffer(TOLERANCE * step, join_style='round',
                                 quad_segs=_QUAD_SEGS) \
            if not courant.is_empty else None
        reste = moitie if couvert is None else moitie.difference(couvert)
        for morceau in _parts(reste):
            if morceau.area >= aire_min:
                boucles.extend((k - 0.5, b) for b in _loops(morceau))
        if courant.is_empty:
            break
        boucles.extend((float(k), b) for b in _loops(courant))
        k += 1
        if k > 100000:                       # garde-fou : jamais atteint
            break
        moitie = rentre(inset + (k - 1 + TOLERANCE) * step)
        courant = rentre(inset + k * step)
    return boucles


def _spirales(boucles: list[tuple[float, G.Polyline]], partie,
              step: float) -> list[G.Polyline]:
    """Relie chaque anneau à un anneau plus rentré, en spirale.

    Arrivé au bout d'un anneau — c'est-à-dire revenu à son départ —,
    le trait passe sur l'anneau suivant par un pont court, en biais vers
    l'avant : aucun virage serré, rien hors de la zone. L'anneau suivant
    repart du point d'arrivée du pont.
    """
    from shapely import STRtree
    from shapely.geometry import LineString, Point, box
    zone = partie.buffer(1e-6)
    niveaux = sorted({n for n, _b in boucles})
    par_niveau: dict[float, list[G.Polyline]] = {}
    for n, b in boucles:
        par_niveau.setdefault(n, []).append(b)
    lignes = {id(b): LineString(b) for _n, b in boucles}
    # un index par niveau : chercher l'anneau suivant parmi tous ceux du
    # niveau rendait le calcul quadratique — 60 s pour un texte de cent
    # cinquante lettres en négatif, dont chaque trou fait un anneau
    arbres = {n: STRtree([lignes[id(b)] for b in par_niveau[n]])
              for n in niveaux}
    pris: set[int] = set()
    sortie: list[G.Polyline] = []
    for n in niveaux:
        for b in par_niveau[n]:
            if id(b) in pris:
                continue
            pris.add(id(b))
            chemin = list(b)
            niveau = n
            while True:
                fin = chemin[-1]
                meilleur = None
                # l'anneau suivant, ou un anneau d'appoint à mi-chemin
                fenetre = box(fin[0] - 3 * step, fin[1] - 3 * step,
                              fin[0] + 3 * step, fin[1] + 3 * step)
                for prochain in (niveau + 0.5, niveau + 1.0):
                    arbre = arbres.get(prochain)
                    if arbre is None:
                        continue
                    for k in arbre.query(fenetre):
                        c = par_niveau[prochain][int(k)]
                        if id(c) in pris:
                            continue
                        ligne = lignes[id(c)]
                        s = (ligne.project(Point(fin)) + step) % ligne.length
                        q = ligne.interpolate(s)
                        d = math.hypot(q.x - fin[0], q.y - fin[1])
                        if d <= 3 * step and (meilleur is None
                                              or d < meilleur[0]):
                            meilleur = (d, c, s, (q.x, q.y), prochain)
                if meilleur is None:
                    break
                _d, c, s, q, prochain = meilleur
                tour = _depuis(c, s, q)
                essai = chemin[-2:] + tour[:2]
                if _virages(essai) or not zone.covers(LineString([fin, q])):
                    break
                pris.add(id(c))
                chemin.extend(tour)
                niveau = prochain
            sortie.append(chemin)
    return sortie


def _depuis(boucle: G.Polyline, s: float,
            q: tuple[float, float]) -> G.Polyline:
    """La boucle fermée, parcourue depuis l'abscisse curviligne `s`."""
    sommets = boucle[:-1]
    cumul = 0.0
    i = 0
    for i in range(len(sommets)):
        a, b = boucle[i], boucle[i + 1]
        lg = math.hypot(b[0] - a[0], b[1] - a[1])
        if cumul + lg >= s:
            break
        cumul += lg
    return [q] + sommets[i + 1:] + sommets[:i + 1] + [q]


def _virages(poly: G.Polyline) -> int:
    """Virages plus fermés que le SkyWrite : ceux de `toolpath`."""
    from .toolpath import sharp_corners
    return sharp_corners(poly)
