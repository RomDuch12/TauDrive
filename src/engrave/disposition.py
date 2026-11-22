"""Aligner et répartir une sélection / Arranging a selection.

Poser six plaques en ligne, centrer un texte sous un logo, espacer
régulièrement les cases d'un montage : sans ces gestes, on tapait des
coordonnées une à une dans l'inspecteur, calculette à côté.

**Ce qui bouge, ce sont des blocs.** Un groupe pris dans la sélection se
déplace d'un seul tenant : aligner ses membres un à un le démembrerait —
un code quitterait son texte, un logo séparé ses trous. Une forme seule
est un bloc à elle seule. Une sélection faite d'**un seul groupe** n'a
qu'un bloc, et rien à aligner : ce sont alors ses membres qu'on dispose,
puisque c'est la seule lecture qui ait un sens — régler un texte sous le
code de sa plaque.

**La référence est l'emprise commune**, rotation et cadre compris — la
même que celle qu'affiche le panneau du lot. Aligner à gauche pose le
bord gauche de chaque bloc sur le bord gauche de l'ensemble ; répartir
laisse les deux blocs extrêmes en place et égalise les espaces entre
les autres.
"""
from __future__ import annotations

from .model import Shape
from .resize import move_selection_center
from .toolpath import shape_extent

#: Les six alignements, dans l'ordre des boutons : (libellé, axe, côté).
#: Le côté vaut 0 pour le bord bas ou gauche, 0,5 pour l'axe, 1 pour le
#: bord haut ou droit.
ALIGNEMENTS = (
    ('gauche', 'x', 0.0), ('centre', 'x', 0.5), ('droite', 'x', 1.0),
    ('haut', 'y', 1.0), ('milieu', 'y', 0.5), ('bas', 'y', 0.0),
)

#: En deçà, un bloc est tenu pour déjà en place.
JEU_MM = 1e-9


def blocs(shapes: list[Shape]) -> list[list[Shape]]:
    """Les blocs qui bougent d'un seul tenant, dans l'ordre de la sélection.

    Un groupe forme un bloc, une forme seule aussi. Une sélection d'un seul
    groupe rend ses membres un par un — voir l'en-tête du module.
    """
    par_groupe: dict[str, list[Shape]] = {}
    sortie: list[list[Shape]] = []
    for s in shapes:
        if not s.group:
            sortie.append([s])
        elif s.group in par_groupe:
            par_groupe[s.group].append(s)
        else:
            par_groupe[s.group] = [s]
            sortie.append(par_groupe[s.group])
    if len(sortie) == 1 and len(sortie[0]) > 1:
        return [[s] for s in sortie[0]]
    return sortie


def _emprise(bloc: list[Shape]):
    boites = [b for b in (shape_extent(s) for s in bloc) if b]
    if not boites:
        return None
    return (min(b[0] for b in boites), min(b[1] for b in boites),
            max(b[2] for b in boites), max(b[3] for b in boites))


def _deplacer(bloc: list[Shape], dx: float, dy: float) -> bool:
    if abs(dx) <= JEU_MM and abs(dy) <= JEU_MM:
        return False
    for s in bloc:
        s.x += dx
        s.y += dy
    return True


def _mesures(shapes: list[Shape]) -> list[tuple[list[Shape], tuple]]:
    return [(b, e) for b in blocs(shapes)
            if (e := _emprise(b)) is not None]


def aligner(shapes: list[Shape], mode: str) -> int:
    """Aligne les blocs sur un bord ou un axe de leur emprise commune.

    `mode` : l'un des libellés d'`ALIGNEMENTS`. Rend le nombre de blocs
    déplacés — zéro s'il y en a moins de deux, ou s'ils sont déjà en place.
    """
    regle = next((r for r in ALIGNEMENTS if r[0] == mode), None)
    if regle is None:
        raise ValueError(f'alignement inconnu : {mode!r}')
    _nom, axe, cote = regle
    mesures = _mesures(shapes)
    if len(mesures) < 2:
        return 0
    i0, i1 = (0, 2) if axe == 'x' else (1, 3)
    bas = min(e[i0] for _b, e in mesures)
    haut = max(e[i1] for _b, e in mesures)
    cible = bas + (haut - bas) * cote
    bouges = 0
    for bloc, e in mesures:
        actuel = e[i0] + (e[i1] - e[i0]) * cote
        d = cible - actuel
        bouges += _deplacer(bloc, d if axe == 'x' else 0.0,
                            d if axe == 'y' else 0.0)
    return bouges


def repartir(shapes: list[Shape], axe: str) -> int:
    """Égalise les espaces entre blocs le long de `axe` ('x' ou 'y').

    Les deux blocs extrêmes ne bougent pas ; il en faut trois au moins.
    Les blocs sont pris dans l'ordre de leur bord gauche — ou bas —, de
    sorte qu'aucun ne saute par-dessus un autre. Des blocs plus larges,
    ensemble, que l'intervalle qui les porte se chevauchent également :
    l'espace devient négatif, mais reste égal. Rend le nombre de blocs
    déplacés.
    """
    if axe not in ('x', 'y'):
        raise ValueError(f'axe inconnu : {axe!r}')
    i0, i1 = (0, 2) if axe == 'x' else (1, 3)
    mesures = sorted(_mesures(shapes), key=lambda m: (m[1][i0], m[1][i1]))
    if len(mesures) < 3:
        return 0
    debut = mesures[0][1][i0]
    # le dernier par son bord gauche reste où il est : c'est lui qui
    # borne la répartition, même si un bloc plus large dépasse plus loin
    fin = mesures[-1][1][i1]
    tailles = sum(e[i1] - e[i0] for _b, e in mesures)
    espace = (fin - debut - tailles) / (len(mesures) - 1)
    bouges = 0
    position = debut
    for rang, (bloc, e) in enumerate(mesures):
        if 0 < rang < len(mesures) - 1:
            d = position - e[i0]
            bouges += _deplacer(bloc, d if axe == 'x' else 0.0,
                                d if axe == 'y' else 0.0)
        position += (e[i1] - e[i0]) + espace
    return bouges


def centrer(shapes: list[Shape], cx: float = 0.0, cy: float = 0.0) -> bool:
    """Centre la sélection entière sur (cx, cy) — le centre du champ par
    défaut. Les positions relatives ne changent pas."""
    mesures = _mesures(shapes)
    if not mesures:
        return False
    x0 = min(e[0] for _b, e in mesures)
    y0 = min(e[1] for _b, e in mesures)
    x1 = max(e[2] for _b, e in mesures)
    y1 = max(e[3] for _b, e in mesures)
    dx, dy = cx - (x0 + x1) / 2, cy - (y0 + y1) / 2
    if abs(dx) <= JEU_MM and abs(dy) <= JEU_MM:
        return False
    move_selection_center(shapes, cx, cy)
    return True
