"""Construction des trajectoires / Toolpath construction.

Transforme un `Document` en une suite de passes, chacune portant une
recette laser et des polylignes exprimées en millimètres machine.
"""
from __future__ import annotations

import contextlib
import itertools
import math
import threading
from array import array
from collections import deque
from dataclasses import dataclass, field, replace

from . import geometry as G
from . import barcode, ordering, textvec, variables, wobble
from .model import (Circle, Code, Document, Path, Rect, Recipe, Shape,
                    Text)

#: Vitesse de déplacement à vide de la tête galvo, en mm/min.
#: 7 m/s d'après le manuel TAU SMART. **N'entre plus dans la durée** :
#: les sauts de cette machine reprennent la vitesse de gravure, il n'y a
#: pas de vitesse de saut distincte — voir `reference/limites-machine.md`.
RAPID_MM_MIN = 420000.0

# --- dynamique réelle de la machine ----------------------------------------
#
# La durée était estimée comme longueur / vitesse : 0,2 s pour un travail
# qui en prenait 15. Ce qui manquait, c'est que sur cette machine
# **chaque allumage coûte** : le SkyWrite fait accélérer le miroir avant
# le trait et freiner après, et cette rampe dure d'autant plus que la
# vitesse est haute. D'où le paradoxe constaté à l'atelier sur un
# DataMatrix hachuré de 2 666 allumages : 7 s à 50 m/min, 8 s à 100,
# 15 s à 200 — plus on demandait vite, plus c'était long.
#
# Le modèle ci-dessous, par allumage : un saut à profil trapézoïdal, une
# attente fixe, le trait à vitesse constante, deux rampes `v / a` ; et
# deux rampes encore à chaque virage plus serré que l'angle du SkyWrite.
# Ses deux constantes ont été **ajustées sur ces trois mesures** : il les
# rend à 6,9 · 8,8 · 14,3 s. L'accélération trouvée, 1 500 m/s², est de
# l'ordre du paramètre machine (`P_06_01_08_05` = 3000, unité non écrite).

#: Vitesse maximale des axes optiques : `P_06_01_02_04` = 200 m/min.
#: Au-delà, la consigne est écrêtée : 500 m/min gravent à 200.
SPEED_MAX_MM_MIN = 200000.0

#: Accélération effective du miroir, en mm/s². Ajustée sur l'atelier.
ACCEL_MM_S2 = 1.5e6

#: Attente fixe par allumage, en secondes. Ajustée sur l'atelier.
LASER_ON_WAIT_S = 0.0002

#: Angle intérieur sous lequel un virage déclenche le SkyWrite, en degrés
#: (`P_06_01_08_08` = 89°) : le trait s'arrête, repart.
SKYWRITE_ANGLE_DEG = 89.0
_COS_SKYWRITE = math.cos(math.radians(180.0 - SKYWRITE_ANGLE_DEG))


def move_time_s(length_mm: float, v_mm_s: float,
                accel: float = ACCEL_MM_S2) -> float:
    """Durée d'un déplacement parti et arrivé à l'arrêt, profil trapézoïdal."""
    if length_mm <= 0 or v_mm_s <= 0:
        return 0.0
    if length_mm < v_mm_s * v_mm_s / accel:
        return 2.0 * math.sqrt(length_mm / accel)       # jamais à pleine vitesse
    return length_mm / v_mm_s + v_mm_s / accel


def _mesure(poly: G.Polyline) -> tuple[float, int]:
    """Longueur d'une polyligne et ses virages serrés, en un seul passage.

    Chaque segment n'est mesuré qu'une fois : la longueur et le virage le
    partagent. Les deux se comptaient chacun de leur côté, et chaque
    segment deux fois pour les virages — sur un tracé oscillé de trois
    millions de points, la moitié du temps de la vérification.
    """
    hypot = math.hypot
    normes: list[float] = []
    garde = normes.append
    virages = 0
    ax, ay = poly[0]
    ux = uy = nu = 0.0
    premier = True
    for bx, by in poly[1:]:
        wx, wy = bx - ax, by - ay
        nw = hypot(wx, wy)
        garde(nw)
        if (not premier and nu >= 1e-9 and nw >= 1e-9
                and (ux * wx + uy * wy) / (nu * nw) < _COS_SKYWRITE):
            virages += 1
        premier = False
        ux, uy, nu = wx, wy, nw
        ax, ay = bx, by
    # `sum` d'une liste, comme avant d'une suite : même addition compensée
    return sum(normes), virages


def sharp_corners(poly: G.Polyline) -> int:
    """Virages plus serrés que l'angle du SkyWrite dans une polyligne."""
    if len(poly) < 3:
        return 0
    return _mesure(poly)[1]


def duration_profile(polylines: list[G.Polyline],
                     start: tuple[float, float] = (0.0, 0.0),
                     memo: dict | None = None) -> tuple:
    """Ce qui fait la durée d'une suite de polylignes, mesuré une fois :
    les sauts, la longueur gravée, les allumages et les virages serrés.

    `profile_duration_s` en tire la durée à n'importe quelle vitesse. Le
    conseil de vitesse en essaie trente-sept : reparcourir chaque fois
    tous les tracés coûtait deux secondes à la vérification d'un texte.

    `memo` garde la mesure de chaque polyligne d'un appel à l'autre : la
    vérification mesure les mêmes tracés pour la durée du travail, pour
    celle de chaque process et pour le conseil de vitesse. Seuls les sauts
    dépendent de l'ordre ; la longueur et les virages sont à la polyligne.
    La polyligne est gardée avec sa mesure : tant que le mémo vit, son
    identifiant ne peut pas resservir à une autre.
    """
    sauts: list[float] = []
    longueur = 0.0
    allumages = virages = 0
    x, y = start
    for poly in polylines:
        if len(poly) < 2:
            continue
        sauts.append(math.hypot(poly[0][0] - x, poly[0][1] - y))
        vu = memo.get(id(poly)) if memo is not None else None
        if vu is not None and vu[0] is poly:
            mesure = vu[1]
        else:
            mesure = _mesure(poly)
            if memo is not None:
                memo[id(poly)] = (poly, mesure)
        longueur += mesure[0]
        allumages += 1
        virages += mesure[1]
        x, y = poly[-1]
    return sauts, longueur, allumages, virages


def profile_duration_s(profil: tuple, speed_mm_min: float) -> float:
    """La durée d'un `duration_profile` à une vitesse donnée."""
    if speed_mm_min <= 0:
        return 0.0
    sauts, longueur, allumages, virages = profil
    v = min(speed_mm_min, SPEED_MAX_MM_MIN) / 60.0
    rampe = 2.0 * v / ACCEL_MM_S2
    return (sum(move_time_s(s, v) for s in sauts)
            + allumages * LASER_ON_WAIT_S + longueur / v
            + rampe * (allumages + virages))


def polylines_duration_s(polylines: list[G.Polyline], speed_mm_min: float,
                         start: tuple[float, float] = (0.0, 0.0),
                         memo: dict | None = None) -> float:
    """Durée de gravure d'une suite de polylignes à une vitesse donnée.

    Voir l'en-tête de cette section pour le modèle et sa provenance, et
    `duration_profile` pour `memo`.
    """
    if speed_mm_min <= 0:
        return 0.0
    return profile_duration_s(duration_profile(polylines, start, memo),
                              speed_mm_min)


@dataclass
class Pass:
    """Un ensemble de trajectoires partageant la même process."""
    recipe: Recipe
    polylines: list[G.Polyline] = field(default_factory=list)
    source_id: str = ''
    source_name: str = ''
    #: Rang de la passe dans sa recette, 0 pour la première.
    index: int = 0
    #: Cote Z de gravure, en mm, négative vers le bas. C'est la
    #: profondeur de cette passe — voir `Recipe.depth_of`.
    z_mm: float = 0.0

    def length_mm(self) -> float:
        """Longueur gravée, laser actif."""
        total = 0.0
        for poly in self.polylines:
            for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
                total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        return total

    def travel_mm(self, start: tuple[float, float] = (0.0, 0.0)) -> float:
        """Longueur parcourue à vide, depuis `start`.

        Prise isolément, une passe est supposée commencer à l'origine.
        Pour un travail complet, utiliser `total_travel_mm`, qui enchaîne
        les passes sans repasser par l'origine.
        """
        return ordering.travel_distance(self.polylines, start)

    def end_point(self, start: tuple[float, float] = (0.0, 0.0)):
        """Position de la tête à la fin de la passe — au bout du dernier
        trait : un point isolé n'est pas gravé, la tête n'y va pas."""
        for poly in reversed(self.polylines):
            if len(poly) >= 2:
                return poly[-1]
        return start

    def duration_s(self, start: tuple[float, float] = (0.0, 0.0),
                   memo: dict | None = None) -> float:
        """Durée estimée, allumages et SkyWrite compris.

        Ce n'est plus une borne basse : le modèle est ajusté sur des
        mesures de l'atelier — voir `polylines_duration_s`.
        """
        return polylines_duration_s(self.polylines, self.recipe.speed_mm_min,
                                    start, memo)


def shape_contours(shape: Shape, context: dict | None = None,
                   retournes: frozenset = frozenset()) -> list[G.Polyline]:
    """Contours d'une forme, dans son repère local (avant placement).

    `context` fournit les valeurs des champs variables d'un texte ; à
    défaut, un contexte de prévisualisation est utilisé (première pièce).
    `retournes` : contours que son groupe rend creux ou pleins, pour le
    décalage — voir `GroupZone`.
    """
    contours = own_contours(shape, context)
    # Le cadre se mesure sur le dessin **d'origine** : sa marge part du
    # tracé qu'on voit, pas de sa version décalée.
    frame = shape_frame(shape, contours)
    # L'offset vaut **avec ou sans cadre**. Sous un cadre, il compense la
    # largeur du faisceau qui amincit tout relief laissé en négatif ; seul,
    # il grossit ou amincit le tracé lui-même — ce qu'on veut aussi bien
    # sur un logo à graver plein que sur un texte à affiner.
    decale = offset_contours(contours, getattr(shape, 'frame_offset_mm', 0.0),
                             retournes)
    return ([frame] + decale) if frame else decale


def own_contours(shape: Shape,
                 context: dict | None = None) -> list[G.Polyline]:
    """Contours propres d'une forme, **cadre exclu**."""
    if isinstance(shape, Rect):
        return [G.rect_contour(shape.width, shape.height)]
    if isinstance(shape, Circle):
        # discrétisé sur le plus grand des deux rayons puis aplati : une
        # ellipse discrétisée sur le petit axe montrerait ses facettes
        radius = max(shape.width, shape.height) / 2
        if radius <= 0:
            return []
        base = G.circle_contour(radius)
        return [G.scale_xy(base, shape.width / (2 * radius),
                           shape.height / (2 * radius))]
    if isinstance(shape, Path):
        return [list(poly) for poly in shape.polylines]
    if not isinstance(shape, (Code, Text)):
        return []
    # Un texte et un code se dessinent cher, et trois fois par rechargement
    # : pour le remplissage de leur groupe, pour leurs trajectoires, pour
    # leur emprise. On les dessine une fois — voir `_PROPRES`. Chaque
    # appelant reçoit ses propres listes : rien de ce qu'il en fait ne
    # remonte dans la mémoire.
    cle = drawing_key(shape, context)
    # sous le verrou du cache : l'esquisse de la bibliothèque dessine dans
    # un fil de fond, et une éviction croisée levait `KeyError`
    with _VERROU:
        connus = _PROPRES.get(cle)
    if connus is not None:
        return [list(c) for c in connus]
    if isinstance(shape, Code):
        contours = code_contours(shape, context)
    else:
        contours = textvec.layout(cle[1], shape.size_mm, shape.font_path,
                                  shape.align, shape.valign,
                                  shape.line_spacing,
                                  measured=getattr(shape, 'cap_measured',
                                                   True))
        if abs(shape.stretch - 1.0) > 1e-9:
            contours = [G.scale_xy(c, shape.stretch, 1.0) for c in contours]
    figes = tuple(tuple(c) for c in contours)
    poids = sum(len(c) for c in figes)
    with _VERROU:
        if cle not in _PROPRES:
            # les plus anciens s'en vont d'abord : un dict garde l'ordre
            while (_PROPRES
                   and _PROPRES_POINTS[0] + poids > _PROPRES_MAX_POINTS):
                parti = _PROPRES.pop(next(iter(_PROPRES)))
                _PROPRES_POINTS[0] -= sum(len(c) for c in parti)
            _PROPRES[cle] = figes
            _PROPRES_POINTS[0] += poids
    return [list(c) for c in figes]


#: Contours propres des textes et des codes déjà dessinés : clé du dessin
#: (`drawing_key`) -> contours figés. Ils ne dépendent ni de la position,
#: ni de la rotation, ni de la process : la clé ne retient que le dessin.
_PROPRES: dict[tuple, tuple] = {}
_PROPRES_POINTS = [0]
#: Plafond, en points mémorisés.
_PROPRES_MAX_POINTS = 1_000_000


def drawing_key(shape: Shape, context: dict | None = None) -> tuple | None:
    """Ce dont dépend le dessin d'un texte ou d'un code — None sinon.

    Le contenu y entre **une fois les champs variables remplacés** : deux
    numéros de série différents sont deux dessins. Pour un texte, la
    génération des polices aussi — voir `textvec.font_generation`.
    """
    if isinstance(shape, Text):
        text = variables.expand(shape.text,
                                context if context is not None
                                else variables.make_context())
        return ('text', text, shape.size_mm, shape.font_path, shape.align,
                shape.valign, shape.line_spacing, shape.stretch,
                getattr(shape, 'cap_measured', True),
                textvec.font_generation())
    if isinstance(shape, Code):
        data = variables.expand(shape.data,
                                context if context is not None
                                else variables.make_context())
        return ('code', shape.kind, data, shape.module_mm, shape.level,
                shape.quiet_modules, shape.dm_shape, shape.checksum,
                shape.bar_height_mm, shape.fit_w_mm, shape.fit_h_mm,
                shape.fill_step_mm)
    return None


def code_contours(shape: Code,
                  context: dict | None = None) -> list[G.Polyline]:
    """Frontière des modules sombres d'un code, centrée sur l'origine.

    Seules les **arêtes réellement frontalières** sont tracées : le bord
    d'un module sombre n'est émis que s'il donne sur un module clair ou
    sur l'extérieur du symbole.

    Découper le symbole en rectangles par bande, comme on le faisait,
    traçait aussi les arêtes **internes** — celles que deux modules
    sombres superposés partagent. En gravure directe c'était seulement du
    trajet perdu ; en négatif, c'était une ligne gravée au beau milieu
    d'une zone qui devait rester intacte, coupant en deux ce qui devait
    rester d'un seul tenant.

    Une donnée impossible à encoder ne lève pas : elle rend une liste
    vide. L'inspecteur affiche alors la raison — c'est plus utile qu'une
    application qui tombe pendant qu'on tape.
    """
    matrix = code_matrix(shape, context)
    if not matrix:
        return []

    mx, my = code_modules(shape, matrix)
    rows, cols = len(matrix), len(matrix[0])
    half_w, half_h = cols * mx / 2, rows * my / 2

    def dark(y: int, x: int) -> bool:
        return 0 <= y < rows and 0 <= x < cols and matrix[y][x]

    #: Arêtes horizontales, fusionnées par tronçons contigus : une bande
    #: de dix modules donne un segment, pas dix.
    out: list[G.Polyline] = []
    for y in range(rows + 1):
        run_start = None
        for x in range(cols + 1):
            border = x < cols and dark(y - 1, x) != dark(y, x)
            if border and run_start is None:
                run_start = x
            elif not border and run_start is not None:
                yy = half_h - y * my
                out.append([(-half_w + run_start * mx, yy),
                            (-half_w + x * mx, yy)])
                run_start = None

    for x in range(cols + 1):
        run_start = None
        for y in range(rows + 1):
            border = y < rows and dark(y, x - 1) != dark(y, x)
            if border and run_start is None:
                run_start = y
            elif not border and run_start is not None:
                xx = -half_w + x * mx
                out.append([(xx, half_h - run_start * my),
                            (xx, half_h - y * my)])
                run_start = None
    return out


def code_extent(shape: Code, context: dict | None = None):
    """Encombrement du **symbole entier**, zone de silence comprise.

    C'est l'encombrement qui compte pour poser un cadre : les bords de
    l'encre dépendent du hasard des modules sombres — le coin haut-droit
    d'un DataMatrix peut être clair — et un cadre calé dessus n'aurait pas
    la même marge des quatre côtés.
    """
    matrix = code_matrix(shape, context)
    if not matrix:
        return None
    mx, my = code_modules(shape, matrix)
    half_w, half_h = len(matrix[0]) * mx / 2, len(matrix) * my / 2
    return -half_w, -half_h, half_w, half_h


def code_fill(shape: Code, context: dict | None = None) -> list[G.Polyline]:
    """Remplissage d'un code, en balayage alterné.

    Un code n'est **lisible que plein**. Le remplissage est produit ici,
    module par module, plutôt que confié au hachurage de la recette : une
    recette de marquage à hachurage nul donnerait sinon un code
    parfaitement dessiné et parfaitement illisible.

    Deux gravures sont possibles, et c'est le **cadre** qui tranche :

    * sans cadre, ce sont les modules sombres qui sont creusés — le code
      apparaît en creux sur la matière brute ;
    * **avec un cadre**, c'est l'inverse : le fond du cadre est creusé et
      les modules sombres restent en relief. C'est la gravure en négatif,
      celle qui donne le meilleur contraste sur un métal clair, et c'est
      la raison d'être du cadre englobant.

    Dans les deux cas le balayage se fait bande par bande en alternant le
    sens : le trajet à vide reste minime sans qu'aucun ordonnancement
    n'ait à intervenir.
    """
    matrix = code_matrix(shape, context)
    if not matrix:
        return []
    mx, my = code_modules(shape, matrix)
    step = _pas_du_code(shape, mx, my)
    if _traits_du_code(matrix, my, step) > MAX_RANGEES:
        return []                       # voir `code_fill_too_large`

    rows, cols = len(matrix), len(matrix[0])
    half_w, half_h = cols * mx / 2, rows * my / 2

    if shape.frame in ('rect', 'circle'):
        return _code_fill_negative(shape, matrix, mx, my, step)

    out: list[G.Polyline] = []
    for y, start, length in barcode.runs(matrix):
        x1 = -half_w + start * mx
        x2 = x1 + length * mx
        top = half_h - y * my
        bottom = top - my
        # au moins deux passages par module, sinon le trait laisse une
        # arête claire au milieu du carré
        count = max(2, int(round(my / step)))
        flip = False
        for i in range(count):
            yy = bottom + my * (i + 0.5) / count
            out.append([(x2, yy), (x1, yy)] if flip else [(x1, yy), (x2, yy)])
            flip = not flip
    if getattr(shape.recipe, 'link_paths', False):
        # Un module sombre est dans la zone ; le reste n'y est pas. Les
        # liens restent donc sur les arêtes des modules : une rangée de
        # modules contigus se grave d'un trait, un module isolé aussi.
        def sombre(x: float, y: float) -> bool:
            col = math.floor((x + half_w) / mx)
            rang = math.floor((half_h - y) / my)
            return (0 <= rang < rows and 0 <= col < cols
                    and bool(matrix[rang][col]))
        return G.link_horizontal(out, sombre, max_link=mx * 1.01,
                                 critical=_grid_heights(half_h, my))
    return out


def _pas_du_code(shape: Code, mx: float, my: float) -> float:
    """Pas du remplissage d'un code : le sien, sinon celui de la recette,
    sinon le quart d'un module — borné au module et au micron.

    Un pas négatif ou nul est absent. Lu d'un fichier, `-1` passait pour
    un pas, que la borne ramenait au micron : un code 39 « A » de 780
    traits en faisait 90 000, quand une hachure à `-1` ne remplit pas un
    rectangle."""
    step = next((p for p in (shape.fill_step_mm, shape.recipe.hatch_mm)
                 if p > 0), min(mx, my) / 4)
    return max(1e-3, min(step, my))


def _traits_du_code(matrix, my: float, step: float) -> int:
    """Traits du remplissage d'un code, comptés sans le tracer.

    Chaque rangée de modules est balayée `max(2, my / step)` fois, coupée
    à chaque plage sombre — ou entre elles, en négatif : le compte des
    plages plus celui des rangées borne les deux gravures."""
    return ((len(barcode.runs(matrix)) + len(matrix))
            * max(2, int(round(my / step))))


def code_fill_too_large(shape: Code, context: dict | None = None) -> bool:
    """Vrai si le remplissage du code compterait plus de `MAX_RANGEES`
    traits : il est alors omis, comme celui d'une forme trop grande.

    Un module de 5 mm au pas d'un micron — ou d'un pas de recette fin,
    0,01 mm, sur des modules de 500 mm — passait des millions de traits
    au calcul, et la mémoire n'y suffisait pas."""
    matrix = code_matrix(shape, context)
    if not matrix:
        return False
    mx, my = code_modules(shape, matrix)
    return _traits_du_code(matrix, my, _pas_du_code(shape, mx, my)) \
        > MAX_RANGEES


def code_refus(shape: Code, context: dict | None = None) -> str | None:
    """La raison pour laquelle la donnée de ce code est inencodable — le
    message de `barcode.CodeError` —, ou `None` s'il s'encode."""
    refus: list[str] = []
    if code_matrix(shape, context, refus):
        return None
    return refus[0] if refus else 'donnée inencodable'


def codes_inencodables(document: Document, context: dict | None = None, *,
                       variables_seuls: bool = False
                       ) -> list[tuple[str, str]]:
    """Les codes visibles que la donnée rend inencodables, pour ces champs
    variables : (nom, raison).

    `code_matrix` les rend vides, et le calcul des passes les omet : un
    EAN-13 de cinq chiffres disparaissait de l'ISO sans un mot, seul ou en
    série, quand l'inspecteur seul le disait. `variables_seuls` ne relit
    que les codes à champ variable — les autres ne changent pas d'une
    pièce à l'autre."""
    sortie = []
    for s in document.shapes:
        if not (s.visible and isinstance(s, Code)):
            continue
        if variables_seuls and not variables.has_fields(s.data):
            continue
        raison = code_refus(s, context)
        if raison is not None:
            sortie.append((s.display_name(), raison))
    return sortie


def _refus_code(refus: list[tuple[str, str]],
                piece: int | None = None) -> ValueError:
    """L'erreur qui refuse un export dont un code est inencodable —
    `refus` est un relevé de `codes_inencodables`, `piece` le numéro de
    la pièce dans une série."""
    nom, raison = refus[0]
    autres = (f' (et {len(refus) - 1} autre(s))' if len(refus) > 1 else '')
    ou = f', pièce {piece}' if piece else ''
    return ValueError(f'code inencodable{ou} — {nom}{autres} : {raison}. '
                      f'Il manquerait à la gravure.')


def _code_fill_negative(shape: Code, matrix, mx: float, my: float,
                        step: float) -> list[G.Polyline]:
    """Creuse le fond du cadre en épargnant les modules sombres.

    Le calcul est fait ligne à ligne plutôt que par la règle pair-impair
    générique : sur un symbole, les modules se touchent par leurs arêtes
    par centaines, et un balayage global y multiplierait les intersections
    coïncidentes — celles que le pair-impair traite le moins bien. Ici les
    intervalles sombres d'une ligne sont connus exactement, et le
    complément s'en déduit sans ambiguïté.
    """
    frame = shape_frame(shape, code_contours(shape))
    box = G.bounds([frame]) if frame else None
    if box is None:
        return []
    fx1, fy1, fx2, fy2 = box

    rows, cols = len(matrix), len(matrix[0])
    half_w, half_h = cols * mx / 2, rows * my / 2
    circle = shape.frame == 'circle'
    cx, cy = (fx1 + fx2) / 2, (fy1 + fy2) / 2
    rx, ry = (fx2 - fx1) / 2, (fy2 - fy1) / 2

    out: list[G.Polyline] = []
    count = max(1, int((fy2 - fy1) / step))
    flip = False
    for i in range(count + 1):
        yy = fy1 + (fy2 - fy1) * (i + 0.5) / (count + 1)
        if yy >= fy2:
            break

        # bornes de la ligne dans le cadre
        if circle:
            if ry <= 0:
                continue
            t = 1.0 - ((yy - cy) / ry) ** 2
            if t <= 0:
                continue
            half = rx * t ** 0.5
            left, right = cx - half, cx + half
        else:
            left, right = fx1, fx2

        # Intervalles sombres de la ligne de modules traversée.
        #
        # `floor` et non `int` : au-dessus du symbole, dans la bande de
        # marge, l'écart est négatif et `int` tronque vers zéro — il rendait
        # la ligne 0. La marge haute épargnait donc les modules de la
        # première ligne, qui se retrouvaient **reproduits à l'extérieur du
        # symbole**, dans le cadre. Sur un DataMatrix, cette première ligne
        # est l'horloge : le motif alterné apparaissait en double.
        dark: list[tuple[float, float]] = []
        row = math.floor((half_h - yy) / my) if my > 0 else -1
        if 0 <= row < rows:
            x = 0
            line = matrix[row]
            while x < cols:
                if not line[x]:
                    x += 1
                    continue
                start = x
                while x < cols and line[x]:
                    x += 1
                dark.append((-half_w + start * mx, -half_w + x * mx))

        # complément : ce qui reste du cadre une fois les modules retirés
        cursor = left
        spans = []
        for a, b in dark:
            a, b = max(a, left), min(b, right)
            if b <= cursor:
                continue
            if a > cursor:
                spans.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < right:
            spans.append((cursor, right))

        for a, b in spans:
            if b - a <= 1e-9:
                continue
            out.append([(b, yy), (a, yy)] if flip else [(a, yy), (b, yy)])
            flip = not flip
    if getattr(shape.recipe, 'link_paths', False):
        # en négatif, la zone est le fond du cadre **moins** les modules
        def fond(x: float, y: float) -> bool:
            if circle:
                if rx <= 0 or ry <= 0 or (
                        ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 > 1.0):
                    return False
            elif not (fx1 <= x <= fx2 and fy1 <= y <= fy2):
                return False
            rang = math.floor((half_h - y) / my) if my > 0 else -1
            col = math.floor((x + half_w) / mx) if mx > 0 else -1
            return not (0 <= rang < rows and 0 <= col < cols
                        and matrix[rang][col])
        bords = [] if circle else [fy1, fy2]
        return G.link_horizontal(out, fond, max_link=max(mx, my) * 1.01,
                                 critical=_grid_heights(half_h, my, bords))
    return out


def _grid_heights(half_h: float, my: float, extra=()):
    """Les hauteurs des arêtes de modules — et du cadre — entre deux
    rangées : c'est là qu'un lien de remplissage pourrait rogner l'angle
    d'un module. Voir `geometry.link_rows`."""
    def critical(y0: float, y1: float, _xa: float, _xb: float):
        out = [y for y in extra if y0 < y < y1]
        if my > 0:
            k = math.ceil((half_h - y1) / my)
            while half_h - k * my > y0:
                y = half_h - k * my
                if y < y1:
                    out.append(y)
                k += 1
        return out
    return critical


def code_matrix(shape: Code, context: dict | None = None,
                refus: list | None = None):
    """Matrice d'un code, ou une liste vide si la donnée est inencodable —
    la raison s'ajoute alors à `refus`, s'il est donné.

    En mode « au plus juste » et dans une fenêtre imposée, la forme du
    symbole est choisie sur celle de la fenêtre : à capacité égale, un
    8 × 18 dans un cadre de 15 × 7 mm donne des modules presque carrés là
    où un 12 × 12 les étirerait de moitié. C'est ce que fait la plaque de
    production, et c'est le seul critère qui compte une fois la donnée
    encodable — les lecteurs supportent mal les modules déformés.
    """
    text = variables.expand(shape.data,
                            context if context is not None
                            else variables.make_context())

    def build(dm_shape: str):
        try:
            return barcode.encode(shape.kind, text, level=shape.level,
                                  shape=dm_shape, checksum=shape.checksum,
                                  quiet_modules=shape.quiet_modules)
        except barcode.CodeError as exc:
            if refus is not None:
                refus.append(str(exc))
            return []

    if (shape.kind == 'datamatrix' and shape.dm_shape == 'auto'
            and shape.fit_w_mm > 0 and shape.fit_h_mm > 0):
        target = shape.fit_w_mm / shape.fit_h_mm
        best, best_score = [], None
        for candidate in ('square', 'rect'):
            matrix = build(candidate)
            if not matrix:
                continue
            mx = shape.fit_w_mm / len(matrix[0])
            my = shape.fit_h_mm / len(matrix)
            distortion = max(mx, my) / min(mx, my)
            # à distorsion égale, le symbole le plus petit l'emporte
            score = (round(distortion, 6), len(matrix) * len(matrix[0]))
            if best_score is None or score < best_score:
                best, best_score = matrix, score
        del target
        return best

    return build(shape.dm_shape)


def code_modules(shape: Code, matrix) -> tuple[float, float]:
    """Taille d'un module, en mm, sur chaque axe.

    Une fenêtre imposée (`fit_w_mm`, `fit_h_mm`) l'emporte sur
    `module_mm` : le symbole est étiré pour la remplir exactement. Les
    modules cessent alors d'être carrés, ce que la norme admet et que les
    plaques de production emploient couramment — le DXF de référence porte
    un 8 × 18 dans une fenêtre de 15 × 7 mm.

    Sur un code linéaire, la hauteur n'est pas une affaire d'encodage :
    c'est la hauteur des barres, réglée à part.
    """
    rows, cols = len(matrix), len(matrix[0])
    mx = (shape.fit_w_mm / cols) if shape.fit_w_mm > 0 \
        else max(1e-6, shape.module_mm)
    if barcode.is_linear(shape.kind):
        my = shape.fit_h_mm if shape.fit_h_mm > 0 \
            else max(1e-6, shape.bar_height_mm)
    else:
        my = (shape.fit_h_mm / rows) if shape.fit_h_mm > 0 \
            else max(1e-6, shape.module_mm)
    return mx, my


def code_size(shape: Code, context: dict | None = None):
    """Encombrement d'un code : (lignes, colonnes, largeur mm, hauteur mm)."""
    matrix = code_matrix(shape, context)
    if not matrix:
        return 0, 0, 0.0, 0.0
    mx, my = code_modules(shape, matrix)
    rows, cols = len(matrix), len(matrix[0])
    return rows, cols, cols * mx, rows * my


# --------------------------------------------------------------------------
# Normalisation des passages
# --------------------------------------------------------------------------
#
# Épaissir un trait pose des passages parallèles. Dès que deux tracés
# d'origine sont plus proches que l'épaisseur demandée — deux contours
# voisins, une arête partagée entre deux entités d'un DXF, un angle très
# fermé — leurs passages se recouvrent, et la matière reçoit deux fois
# l'énergie prévue. Sur un cas mesuré — deux rectangles distants de
# 0,12 mm épaissis à 0,4 mm — **85 % de la longueur gravée passait deux
# fois**. C'est ce qui brûle.
#
# Le remède ne demande pas de calcul de polygones : le trajet voulu est un
# réseau au pas `step`, et tout ce qui roule à moins de ce pas d'un
# passage déjà retenu est du recouvrement. On le retire.

#: Fraction du pas en deçà de laquelle deux passages se recouvrent.
#: 0,9 laisse vivre le réseau voulu — dont les passages sont à exactement
#: un pas — et n'écarte que ce qui est plus serré.
OVERLAP_RATIO = 0.9

#: Plafond d'échantillons. Au-delà, la normalisation est abandonnée
#: plutôt que de faire attendre l'interface : mieux vaut un trajet
#: perfectible qu'une application figée.
NORMALISE_MAX_SAMPLES = 4_000_000


class _Lattice:
    """Occupation du plan par les passages déjà retenus.

    Un passage retenu est échantillonné au tiers du pas — voir `occupy` —,
    et un point « roule sur un passage » s'il passe à moins de
    `threshold` de l'un de ces échantillons. Ce test est celui de
    toujours ; seul change ce qui est rangé.

    Ce ne sont plus les échantillons un à un, mais les **segments** qui
    les portent, avec le nombre de points que l'échantillonnage y pose :
    un côté de 20 mm au pas de 0,05 mm, c'est un segment ici, et douze
    cents points auparavant — 400 Mo et 25 s pour épaissir un rectangle
    de 25 mm, au plafond de quatre millions. Les échantillons d'un
    segment se recalculent à la demande, par la même formule, et seuls
    ceux qui peuvent tomber à portée.

    Surtout, un segment à rogner se juge **d'un bloc** : `proches` relève
    les segments retenus qui passent à portée de tout son long. Aucun — le
    cas de presque tous : deux passages voisins sont à un pas l'un de
    l'autre, au-delà du seuil — et aucun de ses points n'est occupé, sans
    en éprouver un seul.
    """

    __slots__ = ('spacing', 'threshold', 'sample', 'cell', 'cases', 'count',
                 'attente', 'boite', 'rangs', 'tableau', 'remplis')

    def __init__(self, spacing: float) -> None:
        self.spacing = spacing
        self.threshold = spacing * OVERLAP_RATIO
        # échantillonner au tiers du pas borne l'erreur du test — qui
        # mesure une distance à des points, non à des segments — au
        # sixième du pas
        self.sample = spacing / 3.0
        # des cases de deux pas : un passage en traverse peu, et chacune
        # en porte peu — deux passages voisins sont à un pas
        self.cell = 2.0 * spacing
        #: tous les rangés, dans l'ordre : `(x1, y1, x2, y2, n, longueur,
        #: numéro)`, où `numéro` est sa place ici ; une case porte des
        #: numéros
        self.rangs: list[tuple] = []
        self.cases: dict[tuple[int, int], list[int]] = {}
        #: leurs bouts en numpy, `remplis` premières lignes : construit à
        #: la première recherche dense — voir `_proches_en_bloc`
        self.tableau = None
        self.remplis = 0
        self.count = 0
        # Rangés pas encore placés dans les cases : ils le sont à la
        # recherche suivante. Un long passage retenu couvre des centaines
        # de milliers de cases au pas fin ; celui qui fait atteindre le
        # plafond ne sera jamais cherché, et n'a pas à les remplir.
        self.attente: list[tuple] = []
        #: boîte de tout ce qui est rangé : une recherche s'y rogne
        self.boite: list[float] | None = None

    def _cles(self, ax: float, ay: float, bx: float, by: float,
              marge: float):
        """Les cases que touche le segment [a, b] élargi de `marge` : la
        boîte s'il est droit ou court, sinon celles de ses morceaux d'au
        plus une case — comme `_SegmentGrid._ranger`."""
        c = self.cell
        x0, x1 = (ax, bx) if ax <= bx else (bx, ax)
        y0, y1 = (ay, by) if ay <= by else (by, ay)
        i0, i1 = int((x0 - marge) // c), int((x1 + marge) // c)
        j0, j1 = int((y0 - marge) // c), int((y1 + marge) // c)
        if min(i1 - i0, j1 - j0) <= 2:
            return list(itertools.product(range(i0, i1 + 1),
                                          range(j0, j1 + 1)))
        n = max(i1 - i0, j1 - j0)
        dx, dy = bx - ax, by - ay
        cles = set()
        xa, ya = ax, ay
        for k in range(1, n + 1):
            xb, yb = (bx, by) if k == n else (ax + dx * k / n,
                                              ay + dy * k / n)
            cles.update(itertools.product(
                range(int((min(xa, xb) - marge) // c),
                      int((max(xa, xb) + marge) // c) + 1),
                range(int((min(ya, yb) - marge) // c),
                      int((max(ya, yb) + marge) // c) + 1)))
            xa, ya = xb, yb
        return cles

    def _ranger(self, xa: float, ya: float, xb: float, yb: float, n: int,
                longueur: float) -> None:
        rang = (xa, ya, xb, yb, n, longueur, len(self.rangs))
        self.rangs.append(rang)
        self.attente.append(rang)
        x0, x1 = (xa, xb) if xa <= xb else (xb, xa)
        y0, y1 = (ya, yb) if ya <= yb else (yb, ya)
        boite = self.boite
        if boite is None:
            self.boite = [x0, y0, x1, y1]
        else:
            if x0 < boite[0]:
                boite[0] = x0
            if y0 < boite[1]:
                boite[1] = y0
            if x1 > boite[2]:
                boite[2] = x1
            if y1 > boite[3]:
                boite[3] = y1

    def _placer(self) -> None:
        cases = self.cases
        for rang in self.attente:
            for cle in self._cles(rang[0], rang[1], rang[2], rang[3], 0.0):
                cases.setdefault(cle, []).append(rang[6])
        self.attente.clear()

    def occupy(self, polyline: G.Polyline) -> None:
        """Range un passage retenu, échantillonné au tiers du pas.

        Sur chaque segment, `n = max(1, int(longueur / sample))` points,
        aux fractions `k / n` pour `k` de 0 à `n - 1`, puis le dernier
        sommet ; une polyligne de moins de deux points compte pour ses
        points. Chaque segment est rangé avec son `n`, chaque point seul
        avec `n = 0`, et `count` compte les points comme s'ils l'étaient
        un à un : le plafond tombe au même endroit."""
        if len(polyline) < 2:
            for x, y in polyline:
                self._ranger(x, y, x, y, 0, 0.0)
                self.count += 1
            return
        pas = self.sample
        for (x1, y1), (x2, y2) in zip(polyline, polyline[1:]):
            longueur = math.hypot(x2 - x1, y2 - y1)
            n = max(1, int(longueur / pas))
            self._ranger(x1, y1, x2, y2, n, longueur)
            self.count += n
        x, y = polyline[-1]
        self._ranger(x, y, x, y, 0, 0.0)
        self.count += 1

    def _marge(self, ax: float, ay: float, bx: float, by: float) -> float:
        """Le seuil, plus de quoi couvrir l'arrondi des échantillons."""
        return self.threshold + 1e-9 * (1e3 + abs(ax) + abs(ay)
                                        + abs(bx) + abs(by))

    def proches(self, ax: float, ay: float, bx: float, by: float,
                parmi: list[tuple] | None = None) -> list[tuple]:
        """Les segments et points rangés qui passent à portée du segment
        [a, b] — tous, ou ceux de `parmi` : à moins du seuil, plus une
        marge qui couvre l'arrondi des échantillons. Au moindre doute, le
        segment est relevé, et ses points seront éprouvés un à un.

        Plus de `_EN_BLOC` rangés à éprouver, et ils le sont d'un bloc —
        voir `_proches_en_bloc`."""
        marge = self._marge(ax, ay, bx, by)
        if parmi is not None:
            return [rang for rang in parmi
                    if _ecart_rang(ax, ay, bx, by, rang) < marge]
        if self.boite is None:
            return []
        # Seul ce qui passe près de la boîte de l'occupé peut approcher
        # quelque chose : les cases se cherchent sur ce morceau-là. Rogné
        # à deux marges, l'arrondi du rognage est couvert.
        x0, y0, x1, y1 = self.boite
        rogne = _rogne(ax, ay, bx, by, x0 - 2 * marge, y0 - 2 * marge,
                       x1 + 2 * marge, y1 + 2 * marge)
        if rogne is None:
            return []
        if self.attente:
            self._placer()
        cases = self.cases
        numeros: list[int] = []
        for cle in self._cles(*rogne, marge):
            case = cases.get(cle)
            if case is not None:
                numeros += case
        # un rangé est dans chacune des cases qu'il traverse
        uniques = dict.fromkeys(numeros)
        rangs = self.rangs
        if len(uniques) <= _EN_BLOC:
            return [rangs[i] for i in uniques
                    if _ecart_rang(ax, ay, bx, by, rangs[i]) < marge]
        import numpy as np
        numeros = np.fromiter(uniques, dtype=np.intp, count=len(uniques))
        garde = _proches_en_bloc(ax, ay, bx, by, self._bouts(numeros), marge)
        return [rangs[i] for i in numeros[garde].tolist()]

    def troncons(self, ax: float, ay: float, bx: float, by: float, n: int,
                 proches: list[tuple]) -> list[list[tuple]]:
        """`proches(xa, ya, xb, yb, proches)` pour chacun des tronçons de
        `_TRONCON` points dont `_trim` parcourt le segment [a, b] de `n`
        rangs — leurs bouts calculés comme il le fait —, tous d'un bloc."""
        import numpy as np
        bornes = []
        for debut in range(0, n + 1, _TRONCON):
            fin = min(debut + _TRONCON, n + 1)
            ta, tb = debut / n, (fin - 1) / n
            xa, ya = ax + (bx - ax) * ta, ay + (by - ay) * ta
            xb, yb = ax + (bx - ax) * tb, ay + (by - ay) * tb
            bornes.append((xa, ya, xb, yb, self._marge(xa, ya, xb, yb)))
        bornes = np.array(bornes)[:, :, None]
        bouts = self._bouts(np.array([rang[6] for rang in proches],
                                     dtype=np.intp))
        sortie = []
        # au plus deux cent mille paires à la fois
        par = max(1, 200_000 // len(proches))
        for k in range(0, len(bornes), par):
            b = bornes[k:k + par]
            for ligne in _proches_en_bloc(b[:, 0], b[:, 1], b[:, 2], b[:, 3],
                                          bouts, b[:, 4]):
                sortie.append([proches[j]
                               for j in np.flatnonzero(ligne).tolist()])
        return sortie

    def _bouts(self, numeros):
        """Les bouts `x1, y1, x2, y2` des rangés de ces numéros, en numpy.
        Le tableau se prolonge des derniers rangés ; sa taille double
        quand il est plein."""
        import numpy as np
        n, debut = len(self.rangs), self.remplis
        if debut < n:
            if self.tableau is None or len(self.tableau) < n:
                neuf = np.empty((max(n, 2 * debut, 1024), 4))
                if debut:
                    neuf[:debut] = self.tableau[:debut]
                self.tableau = neuf
            self.tableau[debut:n] = [rang[:4] for rang in self.rangs[debut:n]]
            self.remplis = n
        return self.tableau[numeros]

    def occupe(self, x: float, y: float, proches: list[tuple],
               loin: float) -> bool:
        """Vrai si l'un des échantillons de `proches` passe à moins du
        seuil de (x, y) — le calcul d'avant, mot pour mot, sur les seuls
        échantillons qui peuvent y être.

        Sur un segment, ce sont ceux dont l'abscisse est à portée de
        celle de (x, y), un rang de plus de part et d'autre : un rang vaut
        au moins un tiers de pas, l'arrondi n'en est qu'une infime part.
        Un segment dont la droite passe à plus de `loin` — la marge de
        `proches` — est écarté d'emblée. Le rangé touché passe en tête de
        `proches` : le point suivant, voisin, le touche presque toujours.
        """
        seuil = self.threshold * self.threshold
        portee = self.threshold
        for i, (x1, y1, x2, y2, n, longueur, _) in enumerate(proches):
            if n == 0:
                if (x1 - x) ** 2 + (y1 - y) ** 2 < seuil:
                    if i:
                        proches[0], proches[i] = proches[i], proches[0]
                    return True
                continue
            dx, dy = x2 - x1, y2 - y1
            if abs((x - x1) * dy - (y - y1) * dx) > loin * longueur:
                continue
            if n == 1:
                premier = dernier = 0
            else:
                abscisse = ((x - x1) * dx + (y - y1) * dy) / longueur
                rang = longueur / n
                premier = max(0, int((abscisse - portee) / rang) - 1)
                dernier = min(n - 1, int((abscisse + portee) / rang) + 1)
            for k in range(premier, dernier + 1):
                t = k / n
                if ((x1 + dx * t) - x) ** 2 + ((y1 + dy * t) - y) ** 2 \
                        < seuil:
                    if i:
                        proches[0], proches[i] = proches[i], proches[0]
                    return True
        return False

    def couvre(self, ax: float, ay: float, bx: float, by: float,
               proches: list[tuple]) -> bool:
        """Vrai si l'un des segments de `proches` porte, à portée de
        **chaque** point du segment [a, b], l'un de ses échantillons.

        Ses échantillons sont à un rang `h` l'un de l'autre : un point qui
        se projette entre le premier et le dernier, à `d` de sa droite,
        en a un à moins de `√(d² + h²/4)`. `d` et la projection varient
        en ligne droite le long de [a, b] : les vérifier à ses deux bouts
        suffit. La marge d'arrondi est retranchée partout — au moindre
        doute, la réponse est non, et les points seront éprouvés un à un.
        """
        tol = self._marge(ax, ay, bx, by) - self.threshold
        portee = self.threshold - tol
        for x1, y1, x2, y2, n, longueur, _ in proches:
            if n < 2:
                continue
            dx, dy = x2 - x1, y2 - y1
            h = longueur / n
            reste = portee * portee - h * h / 4
            if reste <= 0.0:
                continue
            dernier = (n - 1) * h - tol
            for px, py in ((ax, ay), (bx, by)):
                abscisse = ((px - x1) * dx + (py - y1) * dy) / longueur
                d = ((px - x1) * dy - (py - y1) * dx) / longueur
                if not (tol <= abscisse <= dernier and d * d < reste):
                    break
            else:
                return True
        return False

    def full(self) -> bool:
        return self.count > NORMALISE_MAX_SAMPLES


def _rogne(ax: float, ay: float, bx: float, by: float, x0: float,
           y0: float, x1: float, y1: float) -> tuple | None:
    """Le morceau du segment [a, b] dans la boîte, ou None s'il n'y entre
    pas — Liang et Barsky."""
    t0, t1 = 0.0, 1.0
    dx, dy = bx - ax, by - ay
    for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0),
                 (dy, y1 - ay)):
        if p == 0.0:
            if q < 0.0:
                return None
            continue
        t = q / p
        if p < 0.0:
            if t > t1:
                return None
            if t > t0:
                t0 = t
        else:
            if t < t0:
                return None
            if t < t1:
                t1 = t
    return ax + dx * t0, ay + dy * t0, ax + dx * t1, ay + dy * t1


#: Au-delà de ce nombre de rangés à éprouver, `_Lattice.proches` les
#: juge d'un bloc, par numpy, et `_trim` les tronçons d'un segment tous
#: ensemble. Un dessin dense — les barres d'un code serrées à quelques
#: microns, puis épaissies d'un demi-millimètre — en met des centaines à
#: portée de chaque segment : les éprouver un à un prenait les trois
#: quarts du temps.
_EN_BLOC = 64


def _proches_en_bloc(ax, ay, bx, by, bouts, marge):
    """Les rangés à moins de `marge` du segment [a, b], en masque — les
    bouts `x1, y1, x2, y2` d'un rangé par ligne de `bouts` : `_ecart_rang`
    sur tous à la fois. `a`, `b` et `marge` sont des nombres, ou des
    colonnes numpy, un segment par ligne : le masque a alors une ligne par
    segment.

    Les mêmes opérations, dans le même ordre ; seule la racine manque, et
    l'on compare des carrés. Le seuil est élargi d'un milliardième pour
    couvrir l'écart d'arrondi qui en résulte, quelques unités du dernier
    chiffre : tout rangé que le calcul un à un retient l'est aussi. Un
    point rangé (n = 0) est jugé comme un segment nul : à la distance de
    `_ecart_rang`, ou moins.

    Un rangé de plus, au milliardième près, ne change rien : `occupe` et
    `couvre` éprouvent ses échantillons à moins du seuil, que la marge
    dépasse d'un micron au moins."""
    import numpy as np
    minimum, maximum, where = np.minimum, np.maximum, np.where
    cx, cy, ex, ey = bouts[:, 0], bouts[:, 1], bouts[:, 2], bouts[:, 3]
    ux, uy = bx - ax, by - ay
    vx, vy = ex - cx, ey - cy
    # un segment nul donne `k = 0`, la distance à son bout — comme
    # `_point_segment`
    long_u = ux * ux + uy * uy
    plein_u = long_u > 1e-18
    long_u = where(plein_u, long_u, 1.0)
    long_v = vx * vx + vy * vy
    plein_v = long_v > 1e-18
    long_v = where(plein_v, long_v, 1.0)

    def au_segment(px, py):
        # carré de `_point_segment(px, py, a, b)`
        k = where(plein_u, minimum(maximum(
            ((px - ax) * ux + (py - ay) * uy) / long_u, 0.0), 1.0), 0.0)
        dx, dy = px - (ax + ux * k), py - (ay + uy * k)
        return dx * dx + dy * dy

    def aux_rangs(px, py):
        # carré de `_point_segment(px, py, c, e)`
        k = where(plein_v, minimum(maximum(
            ((px - cx) * vx + (py - cy) * vy) / long_v, 0.0), 1.0), 0.0)
        dx, dy = px - (cx + vx * k), py - (cy + vy * k)
        return dx * dx + dy * dy

    d = minimum(minimum(au_segment(cx, cy), au_segment(ex, ey)),
                minimum(aux_rangs(ax, ay), aux_rangs(bx, by)))
    # se croisent-ils ? la distance est nulle
    d[((ux * (cy - ay) - uy * (cx - ax)) * (ux * (ey - ay) - uy * (ex - ax))
       < 0.0)
      & ((vx * (ay - cy) - vy * (ax - cx)) * (vx * (by - cy) - vy * (bx - cx))
         < 0.0)] = 0.0
    seuil = marge * (1.0 + 1e-9)
    return d < seuil * seuil


def _ecart_rang(ax: float, ay: float, bx: float, by: float,
                rang: tuple) -> float:
    """Distance du segment [a, b] à un segment — ou un point — rangé dans
    un `_Lattice`."""
    cx, cy, ex, ey, n = rang[:5]
    if n == 0:
        return _point_segment(cx, cy, (ax, ay), (bx, by))
    ux, uy = bx - ax, by - ay
    vx, vy = ex - cx, ey - cy
    # se croisent-ils ? la distance est nulle
    if ((ux * (cy - ay) - uy * (cx - ax))
            * (ux * (ey - ay) - uy * (ex - ax)) < 0.0
            and (vx * (ay - cy) - vy * (ax - cx))
            * (vx * (by - cy) - vy * (bx - cx)) < 0.0):
        return 0.0
    return min(_point_segment(cx, cy, (ax, ay), (bx, by)),
               _point_segment(ex, ey, (ax, ay), (bx, by)),
               _point_segment(ax, ay, (cx, cy), (ex, ey)),
               _point_segment(bx, by, (cx, cy), (ex, ey)))


#: Points d'un tronçon, quand `_trim` parcourt un long segment.
_TRONCON = 48


def _trim(polyline: G.Polyline, lattice: '_Lattice') -> list[G.Polyline]:
    """Ne garde d'une polyligne que ce qui ne roule pas sur un passage.

    Les morceaux retenus gardent les sommets d'origine : on ne rend pas
    une polyligne échantillonnée au tiers de pas, qui pèserait cent fois
    plus lourd dans l'ISO pour la même trajectoire.

    Un segment qu'aucun passage retenu n'approche — `_Lattice.proches` —
    n'est pas parcouru : tous ses points seraient libres, et seuls le
    premier et le dernier comptent ci-dessous.
    """
    if len(polyline) < 2:
        return []
    morceaux: list[G.Polyline] = []
    courant: G.Polyline = []
    pas = lattice.sample

    for (x1, y1), (x2, y2) in zip(polyline, polyline[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(length / pas))
        proches = lattice.proches(x1, y1, x2, y2)
        if not proches:
            # les points de rang 0 et n, au calcul près — `k / n` vaut
            # alors 0.0 et 1.0 : le premier ouvre un morceau s'il n'y en a
            # pas, le dernier, sommet d'origine, le prolonge
            if not courant:
                courant = [(x1 + (x2 - x1) * 0.0, y1 + (y2 - y1) * 0.0)]
            courant.append((x1 + (x2 - x1) * 1.0, y1 + (y2 - y1) * 1.0))
            continue
        loin = lattice._marge(x1, y1, x2, y2)
        # Par tronçons de points consécutifs, chacun avec les seuls rangés
        # à sa portée — ceux de tout le segment passaient à chaque point.
        # Nombreux, ils se trient pour tous les tronçons d'un bloc.
        troncons = (lattice.troncons(x1, y1, x2, y2, n, proches)
                    if n >= _TRONCON and len(proches) > _EN_BLOC else None)
        # Un tronçon couvert d'un bout à l'autre est occupé en entier :
        # seul son premier point compte, il clôt le morceau en cours.
        debut = 0
        while debut <= n:
            fin = min(debut + _TRONCON, n + 1)
            ta, tb = debut / n, (fin - 1) / n
            xa, ya = x1 + (x2 - x1) * ta, y1 + (y2 - y1) * ta
            xb, yb = x1 + (x2 - x1) * tb, y1 + (y2 - y1) * tb
            locaux = (proches if fin - debut == n + 1 or len(proches) <= 2
                      else troncons[debut // _TRONCON] if troncons
                      else lattice.proches(xa, ya, xb, yb, proches))
            if locaux and lattice.couvre(xa, ya, xb, yb, locaux):
                if courant:
                    if len(courant) > 1 or courant[0] != (xa, ya):
                        courant.append((xa, ya))
                    if len(courant) > 1:
                        morceaux.append(courant)
                    courant = []
                debut = fin
                continue
            for k in range(debut, fin):
                t = k / n
                x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                libre = not (locaux and lattice.occupe(x, y, locaux, loin))
                if libre:
                    if not courant:
                        courant = [(x, y)]
                    elif k == n:
                        # sommet d'origine : on le garde tel quel
                        courant.append((x, y))
                elif courant:
                    if len(courant) > 1 or courant[0] != (x, y):
                        courant.append((x, y))
                    if len(courant) > 1:
                        morceaux.append(courant)
                    courant = []
            debut = fin
    if len(courant) > 1:
        morceaux.append(courant)
    return [m for m in morceaux if _length(m) > pas]


def _length(polyline: G.Polyline) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(polyline, polyline[1:]))


def dedupe(polylines: list[G.Polyline],
           tolerance: float = 1e-6) -> list[G.Polyline]:
    """Retire les tracés **rigoureusement identiques**, sens inverse compris.

    Un DXF d'atelier en contient souvent : deux entités qui partagent une
    arête, un calque recopié, un contour retracé par-dessus l'ancien.
    Gravés tels quels, ils reçoivent deux fois l'énergie prévue — sans rien
    ajouter au dessin, puisqu'ils sont au même endroit.

    Seuls les doublons **exacts** partent. Deux tracés distants ne
    serait-ce que d'un centième restent : ils portent peut-être une
    intention, et supprimer un trait que quelqu'un a demandé se voit sur la
    pièce.
    """
    quantum = max(tolerance, 1e-9)

    def cle(poly):
        return tuple((round(x / quantum), round(y / quantum))
                     for x, y in poly)

    vus: set = set()
    out: list[G.Polyline] = []
    for poly in polylines:
        if len(poly) < 2:
            out.append(poly)
            continue
        direct = cle(poly)
        inverse = tuple(reversed(direct))
        if direct in vus or inverse in vus:
            continue
        vus.add(direct)
        out.append(poly)
    return out


def normalise(base: list[G.Polyline], added: list[G.Polyline],
              spacing: float) -> list[G.Polyline]:
    """Retire des passages ajoutés ce qui recouvre `base` ou eux-mêmes.

    `base` est **intouchable** : ce sont les tracés voulus par
    l'utilisateur. Deux contours qu'il a dessinés à 0,02 mm l'un de
    l'autre brûleront peut-être, mais les effacer serait pire — on ne
    supprime pas un trait que quelqu'un a demandé.

    Seuls les passages **ajoutés par l'épaississement** sont rabotés, et
    c'est bien d'eux que vient le recouvrement.
    """
    if spacing <= 0 or not added:
        return list(added)
    lattice = _Lattice(spacing)
    for poly in base:
        lattice.occupy(poly)
        if lattice.full():
            return list(added)
    gardes: list[G.Polyline] = []
    for poly in added:
        if lattice.full():
            gardes.append(poly)
            continue
        for morceau in _trim(poly, lattice):
            gardes.append(morceau)
            lattice.occupy(morceau)
    return gardes


#: Au-delà de ce nombre de passages, un trait n'est plus épaissi. Deux
#: mille passages, c'est un trait de 20 mm — le plus large que propose
#: l'inspecteur — au pas d'un centième, ou de 2 mm au pas d'un micron :
#: une bande que le remplissage creuse bien plus vite. Un pas tapé trop
#: fin y mène, ou un fichier abîmé : une épaisseur de 1 000 mm au pas courant de 0,05 mm
#: demandait vingt mille passages d'un cercle de 1,4 m, que le rognage à
#: la matière ne finissait pas.
MAX_PASSAGES = 2000


def thicken_too_large(width: float, step: float) -> bool:
    """Vrai si épaissir de `width` au pas `step` dépasse `MAX_PASSAGES`.
    Des deux côtés, chacun reçoit la moitié de l'épaisseur ; d'un seul,
    toute : il y a `width / step` passages dans les deux cas."""
    return width > 0 and step > 0 and width / step > MAX_PASSAGES


def line_step(shape: Shape) -> float:
    """L'écart entre deux passages d'épaississement : celui du trait, à
    défaut le pas de hachurage de la recette, à défaut 0,05 mm."""
    return shape.line_step_mm or shape.recipe.hatch_mm or 0.05


def thicken(polylines: list[G.Polyline], width: float,
            step: float, side: str = 'both') -> list[G.Polyline]:
    """Élargit des tracés par passages parallèles, sans recouvrement.

    Chaque segment est décalé le long de sa normale, de part et d'autre du
    tracé d'origine. C'est un épaississement **par passages**, pas un
    véritable décalage de polygone : sur un angle très fermé, les passages
    extérieurs se croisent au lieu de se raccorder proprement. Pour un
    trait gravé de quelques dixièmes de millimètre, l'écart est sans
    conséquence — et le calcul reste instantané, ce qu'un décalage exact
    ne serait pas.

    Les passages ainsi posés sont ensuite **normalisés** : tout ce qui
    roule à moins d'un pas d'un passage déjà retenu est retiré. Sans cela,
    deux tracés plus proches que l'épaisseur demandée voyaient leurs
    passages se superposer, et la matière recevait deux fois l'énergie
    prévue — ce qui la brûle. Voir `normalise`.

    Au-delà de `MAX_PASSAGES`, le tracé est rendu tel quel : la
    vérification signale la forme — voir `unthickened_shapes`.
    """
    if width <= 0 or step <= 0 or thicken_too_large(width, step):
        return list(polylines)
    # d'un seul côté, toute l'épaisseur y passe ; des deux, la moitié.
    # Le jeu d'un milliardième rattrape l'arrondi binaire : 0,3 / 0,05 / 2
    # vaut 2,9999999999999996 en flottant, et `int` en faisait **deux**
    # passages par côté au lieu de trois — un trait de 0,3 mm sortait à
    # 0,2. Les valeurs touchées dépendaient du hasard décimal.
    count_deux = int(width / step / 2 + 1e-9)
    count_un = int(width / step + 1e-9)
    if max(count_deux, count_un if side in ('inside', 'outside') else 0) <= 0:
        return list(polylines)

    # les doublons exacts brûleraient deux fois sans rien apporter, et
    # chacun poserait en plus son propre jeu de passages parallèles
    polylines = dedupe(polylines)

    def ferme(poly: G.Polyline) -> bool:
        # au micron, comme `G.chain_open` qui les a joints : un contour de
        # fragments DXF ne se referme qu'à l'arrondi du logiciel de dessin
        return len(poly) > 3 and math.hypot(poly[0][0] - poly[-1][0],
                                            poly[0][1] - poly[-1][1]) <= 1e-3

    # d'un seul côté, les fragments qui se touchent sont d'abord joints
    # pour décaler : quatre LINE d'un DXF font un rectangle, qui a un
    # dedans, quand chacune seule n'en a pas. Les tracés gravés, eux,
    # restent tels quels.
    sources = polylines
    if side in ('inside', 'outside'):
        # un contour presque fermé est refermé exactement : le décalage
        # ne raccorde en onglet que des bouts rigoureusement confondus,
        # et laissait sinon dépasser une pointe au sommet de départ
        sources = [p[:-1] + [p[0]] if ferme(p) and p[0] != p[-1] else p
                   for p in G.chain_open(polylines)]
    trous = (_holes([p for p in sources if ferme(p)])
             if side in ('inside', 'outside') else set())

    def signes(poly: G.Polyline) -> tuple[tuple[int, ...], int]:
        """Les côtés où décaler ce tracé, et combien de passages.

        Un décalage positif part à droite du sens de parcours : pour un
        contour trigonométrique, c'est l'extérieur. Le sens d'un DXF
        n'étant garanti en rien, on le lit sur l'aire signée plutôt que
        de le supposer. Le côté se compte **par rapport à la matière** :
        le bord d'un trou a son « dehors » dans le trou.

        Un tracé ouvert — un segment de remplissage, une ligne isolée —
        n'a ni dedans ni dehors : il s'élargit des deux côtés, de la
        moitié chacun. Toute l'épaisseur de chaque côté l'aurait rendu
        deux fois trop large, et débordé de la pièce.
        """
        if side not in ('inside', 'outside') or not ferme(poly):
            return (1, -1), count_deux
        aire = _signed_area(poly)
        if abs(aire) < 1e-12:
            return (1, -1), count_deux
        dehors = 1 if aire > 0 else -1
        if id(poly) in trous:
            dehors = -dehors
        return ((dehors,) if side == 'outside' else (-dehors,)), count_un

    ajoutes: list[G.Polyline] = []
    # les passages d'un seul côté, à part : ils seront rognés à la matière
    d_un_cote: list[G.Polyline] = []
    for poly in sources:
        cotes, count = signes(poly)
        for i in range(1, count + 1):
            offset = i * step
            for sign in cotes:
                shifted = _offset_polyline(poly, sign * offset)
                if shifted:
                    (d_un_cote if len(cotes) == 1 else ajoutes).append(shifted)
    if d_un_cote:
        ajoutes += _clip_side(d_un_cote, [p for p in sources if ferme(p)],
                              side)
    return list(polylines) + normalise(polylines, ajoutes, step)


def _clip_side(passages: list[G.Polyline], contours: list[G.Polyline],
               side: str) -> list[G.Polyline]:
    """Rogne des passages d'un seul côté à la matière, ou hors d'elle.

    Les passages sont des décalages de chaque contour pris seul : dans un
    trait plus étroit que l'épaisseur demandée, ceux d'un bord
    traversent jusqu'à l'autre et ressortent — « dedans » débordait
    alors de la pièce, sur les jambages fins d'une lettre. Rognés à la
    matière (règle pair-impair), ils tiennent la promesse. Sans
    `shapely`, rendus tels quels.
    """
    try:
        from shapely.geometry import LineString, Polygon
        from shapely.prepared import prep
        from shapely.validation import make_valid
        from .rings import _pair_impair
    except ImportError:
        return passages
    matiere = _pair_impair([make_valid(Polygon(c)) for c in contours
                            if len(c) >= 4])
    if matiere is None or matiere.is_empty:
        return passages
    # un micron de jeu : un passage qui longe le bord reste entier
    garde = (matiere.buffer(1e-6) if side == 'inside'
             else matiere.buffer(-1e-6))
    vite = prep(garde)
    sortie: list[G.Polyline] = []
    for p in passages:
        if len(p) < 2:
            continue
        ligne = LineString(p)
        if side == 'inside':
            if vite.covers(ligne):
                sortie.append(p)
                continue
            reste = ligne.intersection(garde)
        else:
            if not vite.intersects(ligne):
                sortie.append(p)
                continue
            reste = ligne.difference(garde)
        morceaux = (getattr(reste, 'geoms', None) or [reste])
        for m in morceaux:
            if m.geom_type == 'LineString' and m.length > 1e-6:
                sortie.append([(float(x), float(y)) for x, y in m.coords])
    return sortie


def _temoins(c: G.Polyline) -> list[tuple[float, float]]:
    """Jusqu'à sept points pris au milieu des côtés d'un contour — voir
    `_holes` pour la raison."""
    n = len(c) - 1
    pas = max(1, n // 7)
    return [((c[k][0] + c[k + 1][0]) / 2, (c[k][1] + c[k + 1][1]) / 2)
            for k in range(0, n, pas)][:7]


def _holes(contours: list[G.Polyline]) -> set[int]:
    """Les contours fermés qui sont des trous : contenus par un nombre
    impair d'autres. Rend leurs `id`.

    Être contenu, c'est d'abord avoir sa boîte dans celle de l'autre ;
    puis la **majorité** de quelques points pris au milieu des côtés doit
    être dedans. Un seul sommet ne suffit pas : deux carrés qui se
    touchent par un coin font tomber ce sommet sur le bord du voisin, et
    le lancer de rayon le dit dedans — le carré passait pour un trou, et
    « dedans » gravait dehors.
    """
    boites = []
    for c in contours:
        xs = [x for x, _ in c]
        ys = [y for _, y in c]
        boites.append((min(xs), min(ys), max(xs), max(ys)))

    trous: set[int] = set()
    jeu = 1e-9
    for i, c in enumerate(contours):
        ax0, ay0, ax1, ay1 = boites[i]
        points = _temoins(c)
        n = 0
        for j, d in enumerate(contours):
            if i == j:
                continue
            bx0, by0, bx1, by1 = boites[j]
            if not (bx0 - jeu <= ax0 and ax1 <= bx1 + jeu
                    and by0 - jeu <= ay0 and ay1 <= by1 + jeu):
                continue
            if 2 * sum(1 for p in points if _inside(p, d)) > len(points):
                n += 1
        if n % 2:
            trous.add(id(c))
    return trous


#: Allongement maximal d'un raccord d'onglet. Sur un angle très fermé, la
#: pointe d'onglet part à l'infini ; on la rabat.
MITER_LIMIT = 4.0


def _offset_polyline(poly: G.Polyline, offset: float) -> G.Polyline:
    """Décale une polyligne d'exactement `offset`, raccords en onglet.

    Deux erreurs se cachaient ici, et toutes deux faussaient la cote.

    **Les normales d'arête n'étaient pas normalisées** avant d'être
    moyennées : leur longueur valait celle de l'arête, si bien qu'à un coin
    joignant une arête de 20 mm et une de 10 mm, la longue écrasait la
    courte et le sommet partait de travers.

    **Le déplacement du sommet valait `offset`**, alors qu'un raccord
    d'onglet demande `offset / cos(θ/2)` — à 90°, la pointe doit s'écarter
    de `offset·√2`. Un trait demandé à 0,05 mm sortait à 0,0447 : 11 % de
    moins, sur toute la longueur.

    La formule exacte, avec `n1` et `n2` unitaires :

        d = offset · (n1 + n2) / (1 + n1·n2)

    Elle donne `offset·√2` à 90°, `offset` sur une ligne droite, et diverge
    sur un angle fermé — où `MITER_LIMIT` la rabat.
    """
    if len(poly) < 2:
        return []
    closed = poly[0] == poly[-1] and len(poly) > 2
    points = poly[:-1] if closed else poly
    n = len(points)
    out = []
    for i, (x, y) in enumerate(points):
        normals = []
        if i > 0 or closed:
            ax, ay = points[i - 1]
            normals.append(_unit(y - ay, ax - x))
        if i < n - 1 or closed:
            bx, by = points[(i + 1) % n]
            normals.append(_unit(by - y, x - bx))
        normals = [v for v in normals if v is not None]
        if not normals:
            out.append((x, y))
            continue
        if len(normals) == 1:
            nx, ny = normals[0]
            out.append((x + nx * offset, y + ny * offset))
            continue
        (ax_, ay_), (bx_, by_) = normals
        cos = ax_ * bx_ + ay_ * by_
        denom = 1.0 + cos
        if denom <= 1.0 / MITER_LIMIT:
            # angle trop fermé : on rabat sur la direction moyenne
            mx, my = _unit(ax_ + bx_, ay_ + by_) or (ax_, ay_)
            out.append((x + mx * offset * MITER_LIMIT,
                        y + my * offset * MITER_LIMIT))
            continue
        out.append((x + (ax_ + bx_) / denom * offset,
                    y + (ay_ + by_) / denom * offset))
    if closed:
        out.append(out[0])
    return out


def _unit(x: float, y: float):
    length = math.hypot(x, y)
    return (x / length, y / length) if length > 1e-12 else None


def _signed_area(poly: G.Polyline) -> float:
    points = poly[:-1] if poly[0] == poly[-1] and len(poly) > 2 else poly
    total = 0.0
    for i, (x, y) in enumerate(points):
        nx, ny = points[(i + 1) % len(points)]
        total += x * ny - nx * y
    return total / 2


def _inside(point: tuple[float, float], poly: G.Polyline) -> bool:
    """Lancer de rayon horizontal : nombre de croisements impair = dedans."""
    x, y = point
    dedans = False
    points = poly[:-1] if poly[0] == poly[-1] and len(poly) > 2 else poly
    for i, (ax, ay) in enumerate(points):
        bx, by = points[(i - 1) % len(points)]
        if (ay > y) != (by > y):
            coupe = ax + (y - ay) / (by - ay) * (bx - ax)
            if coupe > x:
                dedans = not dedans
    return dedans


#: Tolérance du contrôle de décalage : un point du contour décalé doit
#: rester à `distance` de la source, à ce facteur près.
OFFSET_TOLERANCE = 0.92


#: Au plus ce nombre de cases traversées, tous segments confondus : au
#: delà, les cases s'élargissent — voir `_SegmentGrid`.
_GRILLE_MAX_CASES = 2_000_000


class _SegmentGrid:
    """Segments d'origine, rangés par case, pour un test de distance rapide.

    Un segment est rangé dans les cases qu'il **traverse**. Il l'était dans
    toutes celles de sa boîte : pour un segment en biais, c'est le carré
    de sa longueur en cases. Un triangle de 40 mm hachuré avec le retrait
    d'un demi-spot (0,015 mm) prenait 13 s, et à 80 mm le calcul ne
    finissait plus — 28 millions de cases par côté.

    Les cases mesurent au moins le décalage, et davantage si le dessin
    est long devant lui (`_GRILLE_MAX_CASES`). Ni l'un ni l'autre ne
    change une réponse de `proche`, qui éprouve les cases voisines à la
    mesure du seuil : une case plus large ne coûte que des segments de
    plus à éprouver.
    """

    __slots__ = ('cell', '_cases', 'segments', '_contours', '_arbre',
                 '_plein')

    def __init__(self, contours: list[G.Polyline], cell: float) -> None:
        longueur = sum(_length(poly) for poly in contours)
        self.cell = max(cell, 1e-6, longueur / _GRILLE_MAX_CASES)
        # Les segments, avec leurs termes précalculés, ceux de
        # `_point_segment` : un même segment est éprouvé des milliers de
        # fois. Les cases ne se remplissent qu'à la première question : un
        # contour décalé dont aucun segment n'a de voisin (`juge`) n'en
        # pose aucune, et un côté de 94 mm décalé d'un dixième de micron
        # en couvrait un million.
        self._contours = contours
        self.segments: list[tuple] = []
        for poly in contours:
            for (ax, ay), (bx, by) in zip(poly, poly[1:]):
                dx, dy = bx - ax, by - ay
                self.segments.append((ax, ay, dx, dy, dx * dx + dy * dy))
        self._cases: dict[tuple[int, int], list] | None = None
        self._arbre = None
        #: segments de la case la plus pleine — compté à la demande
        self._plein: int | None = None

    @property
    def cases(self) -> dict[tuple[int, int], list]:
        if self._cases is None:
            self._cases = {}
            segments = iter(self.segments)
            for poly in self._contours:
                for a, b in zip(poly, poly[1:]):
                    self._ranger(a, b, next(segments))
        return self._cases

    def _ranger(self, a, b, segment: tuple) -> None:
        (ax, ay), (bx, by) = a, b
        dx, dy = segment[2], segment[3]
        c = self.cell
        cases = self._cases
        x0, x1 = (ax, bx) if ax <= bx else (bx, ax)
        y0, y1 = (ay, by) if ay <= by else (by, ay)
        i0, i1, j0, j1 = int(x0 // c), int(x1 // c), int(y0 // c), int(y1 // c)
        nx, ny = i1 - i0 + 1, j1 - j0 + 1
        if nx * ny <= 2 * max(nx, ny) + 2:
            # droit ou court — le cas de presque tous : la boîte, guère
            # plus que ce qu'il traverse
            for cx in range(i0, i1 + 1):
                for cy in range(j0, j1 + 1):
                    cases.setdefault((cx, cy), []).append(segment)
            return
        # En biais : par morceaux d'au plus une case de côté, la boîte de
        # chacun — deux cases sur deux au plus. Leur réunion couvre tout ce
        # que le segment traverse, extrémités exactes comprises.
        n = max(nx, ny)
        vues = set()
        x0, y0 = ax, ay
        for k in range(1, n + 1):
            x1, y1 = (bx, by) if k == n else (ax + dx * k / n,
                                              ay + dy * k / n)
            for cx in range(int(min(x0, x1) // c), int(max(x0, x1) // c) + 1):
                for cy in range(int(min(y0, y1) // c),
                                int(max(y0, y1) // c) + 1):
                    vues.add((cx, cy))
            x0, y0 = x1, y1
        for cle in vues:
            cases.setdefault(cle, []).append(segment)

    @staticmethod
    def _ecart(x: float, y: float, segment: tuple) -> float:
        """`_point_segment`, sur un segment rangé — même calcul."""
        ax, ay, dx, dy, carre = segment
        if carre <= 1e-18:
            return math.hypot(x - ax, y - ay)
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / carre))
        return math.hypot(x - (ax + dx * t), y - (ay + dy * t))

    def proche(self, x: float, y: float, seuil: float) -> bool:
        """Vrai si un segment passe à moins de `seuil` du point.

        Même réponse que `distance(x, y, p) < seuil` pour tout plafond
        `p > seuil`, mais sans chercher le plus proche : le premier qui
        passe assez près suffit. Avec un seuil sous la taille d'une case,
        les huit cases voisines suffisent aussi.
        """
        cx, cy = int(x // self.cell), int(y // self.cell)
        rayon = max(1, int(seuil / self.cell) + 1)
        hypot = math.hypot
        cases = self.cases
        for a in range(-rayon, rayon + 1):
            for b in range(-rayon, rayon + 1):
                # `_ecart` déroulé : l'appel coûtait autant que le calcul
                for ax, ay, dx, dy, carre in cases.get((cx + a, cy + b), ()):
                    if carre <= 1e-18:
                        d = hypot(x - ax, y - ay)
                    else:
                        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy)
                                         / carre))
                        d = hypot(x - (ax + dx * t), y - (ay + dy * t))
                    if d < seuil:
                        return True
        return False

    def touche(self, x: float, y: float, seuil: float) -> tuple | None:
        """`proche`, qui dit lequel : le premier segment trouvé à moins de
        `seuil` du point, ou None. Le même calcul, recopié : `proche` est
        appelé des centaines de milliers de fois, et passer par celle-ci
        le ralentissait d'un sixième."""
        cx, cy = int(x // self.cell), int(y // self.cell)
        rayon = max(1, int(seuil / self.cell) + 1)
        hypot = math.hypot
        cases = self.cases
        for a in range(-rayon, rayon + 1):
            for b in range(-rayon, rayon + 1):
                # `_ecart` déroulé : l'appel coûtait autant que le calcul
                for segment in cases.get((cx + a, cy + b), ()):
                    ax, ay, dx, dy, carre = segment
                    if carre <= 1e-18:
                        d = hypot(x - ax, y - ay)
                    else:
                        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy)
                                         / carre))
                        d = hypot(x - (ax + dx * t), y - (ay + dy * t))
                    if d < seuil:
                        return segment
        return None

    def juge(self, decale: G.Polyline, pas: float,
             seuil: float) -> dict[int, list[bool]] | None:
        """`proche` de chaque point que `prune_offset` éprouve sur
        `decale`, segment par segment — `None` quand ce ne serait pas plus
        rapide, ou sans shapely : chaque point est alors éprouvé par
        `proche`.

        Seuls figurent les segments qui ont un voisin : les autres n'ont
        que de bons points. Un arbre de boîtes (`STRtree`) les trouve d'un
        coup ; sans lui, un côté de 94 mm décalé d'un dixième de micron
        faisait éprouver trois millions de points.

        Les cases mesurent au moins le décalage : sur un dessin dense —
        huit mille points dans 2 mm, décalés de 3 —, tout tenait en
        quelques cases, et chaque point éprouvait tous les segments. Là,
        l'arbre donne d'un coup le plus proche voisin. Il ne fait que
        trier : un point dont le voisin est franchement en deçà du seuil
        est proche — le calcul de `proche` le confirme sur ce voisin —, un
        point sans voisin à portée ne l'est pas ; un point dans la marge
        d'arrondi du seuil, s'il s'en trouve, est éprouvé par `proche`.

        Ailleurs, l'arbre ne paierait pas : sur un dessin ordinaire,
        presque tous les segments décalés ont un voisin à portée — 94 % sur
        le papillon décalé d'un dixième —, et ses requêtes ne feraient que
        s'ajouter au calcul de `proche`. Le bâtir coûte en outre autant que
        `_DENSE_ARBRE` segments éprouvés par segment de la source : un
        contour de deux mille points sur un papillon de cent mille segments
        ne l'amortirait pas, même dense par endroits.
        """
        segments = self.segments
        if not segments or len(decale) < 2:
            return {}
        points = len(decale) + _length(decale) / pas
        if points <= _LONGS * len(decale):
            fixe = 0 if self._arbre is not None else len(segments)
            if self._densite(decale, seuil) <= _DENSE_ARBRE * (1 + fixe
                                                               / points):
                return None
        try:
            import numpy as np
            import shapely
        except ImportError:
            return None

        def traits(bouts):
            # un segment nul est un point : GEOS ne mesure rien d'une
            # ligne de longueur nulle, et ne la rendrait jamais voisine
            lignes = shapely.linestrings(bouts)
            nuls = (bouts[:, 0] == bouts[:, 1]).all(axis=1)
            if nuls.any():
                lignes[nuls] = shapely.points(bouts[nuls, 0])
            return lignes

        if self._arbre is None:
            # les segments dans l'ordre de `segments` : tous les sommets
            # d'un coup, chacun suivi du suivant, sauf le dernier d'un tracé
            contours = [poly for poly in self._contours if poly]
            sommets = np.array([xy for poly in contours for xy in poly],
                               dtype=float).reshape(-1, 2)
            derniers = np.cumsum([len(poly) for poly in contours]) - 1
            debuts = np.setdiff1d(np.arange(len(sommets)), derniers)
            self._arbre = shapely.STRtree(traits(np.stack(
                [sommets[debuts], sommets[debuts + 1]], axis=1)))
        arbre = self._arbre
        sommets = np.array(decale, dtype=float)
        # la portée, et l'arrondi du calcul de GEOS
        marge = seuil + 1e-9 * (1e3 + 4 * (float(np.abs(sommets).max())
                                           + seuil))
        avec = np.unique(arbre.query_nearest(
            traits(np.stack([sommets[:-1], sommets[1:]], axis=1)),
            max_distance=marge, all_matches=False)[0]).tolist()
        if not avec:
            return {}

        # Les points de ces segments, calculés comme `prune_offset` les
        # calcule — un à un, pour l'être au bit près. Le segment trouvé
        # proche d'un point l'est souvent du suivant : il est éprouvé
        # d'abord. Puis, là où le dessin est clair, le calcul de `proche` ;
        # là où il est dense — plus de `_DENSE` segments autour de la case
        # —, quelques-uns de la case, et s'aucun n'est proche, l'arbre, qui
        # ne cherche pas en vain parmi tous.
        cases = self.cases
        c = self.cell
        rayon = max(1, int(seuil / c) + 1)
        # aucune case assez pleine pour qu'un voisinage soit dense : rien
        # à compter
        if self._plein is None:
            self._plein = max(map(len, cases.values()), default=0)
        clair = self._plein * (2 * rayon + 1) ** 2 <= _DENSE
        autour: dict[tuple[int, int], int] = {}
        jugements: dict[int, list[bool]] = {}
        xs: list[float] = []
        ys: list[float] = []
        renvois: list[tuple[list[bool], int]] = []
        for rang in avec:
            (x1, y1), (x2, y2) = decale[rang], decale[rang + 1]
            n = max(1, int(math.hypot(x2 - x1, y2 - y1) / pas))
            jugement = jugements[rang] = [False] * (n + 1)
            dernier = None
            for k in range(n + 1):
                t = k / n
                x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                if dernier is not None and _proche_parmi(x, y, seuil,
                                                         (dernier,)):
                    jugement[k] = True
                    continue
                if clair:
                    dernier = self.touche(x, y, seuil)
                else:
                    cx, cy = int(x // c), int(y // c)
                    compte = autour.get((cx, cy))
                    if compte is None:
                        compte = autour[cx, cy] = sum(
                            len(cases.get((cx + a, cy + b), ()))
                            for a in range(-rayon, rayon + 1)
                            for b in range(-rayon, rayon + 1))
                    if compte <= _DENSE:
                        dernier = self.touche(x, y, seuil)
                    else:
                        dernier = _proche_parmi(x, y, seuil, itertools.islice(
                            cases.get((cx, cy), ()), _DENSE // 4))
                        if dernier is None:
                            xs.append(x)
                            ys.append(y)
                            renvois.append((jugement, k))
                            continue
                jugement[k] = dernier is not None
        if xs:
            paires, ecarts = arbre.query_nearest(
                shapely.points(np.array(xs), np.array(ys)),
                max_distance=marge, return_distance=True, all_matches=False)
            franc = 2 * seuil - marge          # le seuil, moins la marge
            for i, j, ecart in zip(paires[0].tolist(), paires[1].tolist(),
                                   ecarts.tolist()):
                jugement, k = renvois[i]
                jugement[k] = (
                    ecart < franc and _proche_parmi(
                        xs[i], ys[i], seuil, (segments[j],)) is not None
                    or self.proche(xs[i], ys[i], seuil))
        return jugements

    def _densite(self, decale: G.Polyline, seuil: float) -> int:
        """Combien de segments `proche` éprouverait, au plus, pour l'un des
        sommets de `decale` : la médiane de soixante-quatre d'entre eux au
        plus, pris de loin en loin."""
        cases = self.cases
        c = self.cell
        rayon = max(1, int(seuil / c) + 1)
        comptes = sorted(
            sum(len(cases.get((int(x // c) + a, int(y // c) + b), ()))
                for a in range(-rayon, rayon + 1)
                for b in range(-rayon, rayon + 1))
            for x, y in decale[::max(1, len(decale) // 64)])
        return comptes[len(comptes) // 2]

    def distance(self, x: float, y: float, plafond: float) -> float:
        """Distance au segment le plus proche, bornée à `plafond`."""
        cx, cy = int(x // self.cell), int(y // self.cell)
        rayon = max(1, int(plafond / self.cell) + 1)
        best = plafond
        cases = self.cases
        for a in range(-rayon, rayon + 1):
            for b in range(-rayon, rayon + 1):
                for segment in cases.get((cx + a, cy + b), ()):
                    d = self._ecart(x, y, segment)
                    if d < best:
                        best = d
        return best


def _point_segment(px: float, py: float, a, b) -> float:
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    carre = dx * dx + dy * dy
    if carre <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / carre))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def prune_offset(source: list[G.Polyline], decale: G.Polyline,
                 distance: float,
                 grille: '_SegmentGrid | None' = None) -> list[G.Polyline]:
    """Retire d'un contour décalé les **boucles** qu'il s'est faites.

    Décaler un contour de `d` fait se croiser ses côtés dès qu'un angle
    rentrant est plus serré que `d` : la courbe repart en arrière et
    referme une petite boucle. Gravée, cette boucle marque **à
    l'intérieur de l'angle** — sur un chiffre, dans le creux du « 2 » ou
    du « 6 » — là où précisément on ne voulait rien marquer.

    Le critère est géométrique et sans ambiguïté : un point légitime du
    décalage se tient à `d` de la source. Un point de boucle, lui, est
    passé du mauvais côté et se retrouve **plus près** — d'un autre
    morceau du contour, celui qu'il a franchi. On coupe donc tout ce qui
    s'approche à moins de `d` (à la tolérance près), et l'on recoud ce qui
    reste.

    `grille` : les segments de `source` déjà rangés — voir
    `_grille_source`. Un appelant qui élague plusieurs contours de la même
    source la range une fois : la reconstruire pour chacun coûtait 560 s
    sur un papillon de 910 tracés.
    """
    if not decale or len(decale) < 2 or not distance:
        return [decale] if decale else []
    voulu = abs(distance)
    seuil = voulu * OFFSET_TOLERANCE
    pas = max(voulu / 3.0, 1e-4)
    if grille is None:
        grille = _grille_source(source, distance)

    # Jugés d'un coup (`_SegmentGrid.juge`) dès qu'il y a de quoi : un
    # segment sans voisin n'a que de bons points — seuls ceux de rang 0, 1
    # et n comptent ci-dessous.
    jugements = (grille.juge(decale, pas, seuil)
                 if len(decale) + _length(decale) / pas > _JUGER_DES
                 else None)
    morceaux: list[G.Polyline] = []
    courant: G.Polyline = []
    for rang, ((x1, y1), (x2, y2)) in enumerate(zip(decale, decale[1:])):
        longueur = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(longueur / pas))
        jugement = None if jugements is None else jugements.get(rang, ())
        rangs = (0, 1, n) if jugement == () and n > 2 else range(n + 1)
        for k in rangs:
            t = k / n
            x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
            bon = (not grille.proche(x, y, seuil) if jugement is None
                   else not (jugement and jugement[k]))
            if bon:
                if not courant or k == n:
                    courant.append((x, y))
                elif len(courant) == 1:
                    courant.append((x, y))
            elif courant:
                if len(courant) > 1:
                    morceaux.append(courant)
                courant = []
    if len(courant) > 1:
        morceaux.append(courant)

    # Rien n'a été coupé : le contour est rendu tel quel, fermeture
    # comprise. Le recoudre par morceaux le rouvrirait pour rien.
    if len(morceaux) == 1 and len(morceaux[0]) >= len(decale) - 1:
        return [decale]
    return restitch([m for m in morceaux if _length(m) > pas], voulu)


#: Au-delà de ce nombre de points à éprouver, un contour décalé est jugé
#: d'un coup (`_SegmentGrid.juge`) : en deçà, charger shapely et bâtir
#: l'arbre coûterait plus que les points éprouvés un à un.
_JUGER_DES = 2000

#: Au-delà de ce nombre de segments dans les cases qu'éprouve `proche`, le
#: dessin est dense : `_SegmentGrid.juge` cherche le voisin dans l'arbre.
_DENSE = 256

#: Au-delà de ce nombre moyen de points à éprouver par segment, les
#: segments d'un contour décalé sont longs : `_SegmentGrid.juge` dispense
#: de les parcourir ceux qui n'ont pas de voisin.
_LONGS = 8

#: Segments éprouvés par `proche` que coûte, à peu près, un point cherché
#: dans l'arbre — ou un segment de la source rangé dans l'arbre à bâtir.
#: En deçà, `_SegmentGrid.juge` laisse les points d'un contour à `proche`.
_DENSE_ARBRE = 50


def _proche_parmi(x: float, y: float, seuil: float,
                  segments: tuple | itertools.islice) -> tuple | None:
    """`_SegmentGrid.touche`, sur ces seuls segments — même calcul."""
    hypot = math.hypot
    for segment in segments:
        ax, ay, dx, dy, carre = segment
        if carre <= 1e-18:
            d = hypot(x - ax, y - ay)
        else:
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / carre))
            d = hypot(x - (ax + dx * t), y - (ay + dy * t))
        if d < seuil:
            return segment
    return None


def _grille_source(source: list[G.Polyline],
                   distance: float) -> _SegmentGrid:
    """Les segments de `source` rangés pour `prune_offset`."""
    voulu = abs(distance)
    return _SegmentGrid(source, max(voulu, max(voulu / 3.0, 1e-4)))


#: Écart maximal recousu, en multiples de l'offset.
#:
#: Une boucle retirée dans un angle rentrant laisse un écart de l'ordre de
#: l'offset — au plus deux fois la limite d'onglet. Au-delà, ce n'est plus
#: une boucle : le contour s'est **vraiment** séparé en deux, une nervure
#: ayant fondu sous l'érosion, et les deux morceaux sont deux contours.
STITCH_MAX = 6.0


def restitch(morceaux: list[G.Polyline], voulu: float) -> list[G.Polyline]:
    """Recoud des morceaux d'un contour coupé en contours **fermés**.

    C'est la moitié indispensable de l'élagage. Rendre des morceaux
    ouverts paraît sans conséquence — gravés, ils tracent le bon
    contour — mais le **hachurage** les referme lui-même par une corde
    droite d'un bout à l'autre. Cette corde traverse l'intérieur du
    dessin : elle marque un trait en travers du creux d'un « 0 », et
    fausse la règle pair-impair, donc le remplissage entier.

    Les morceaux arrivent dans l'ordre du parcours. Deux morceaux
    consécutifs séparés d'un écart de l'ordre de l'offset encadrent une
    boucle retirée : la corde qui les joint est, à un tiers d'offset
    près, l'intersection exacte que le décalage aurait produite. On les
    coud. Un écart plus large sépare deux régions devenues distinctes :
    chacune se referme sur elle-même.
    """
    if not morceaux:
        return []
    saut = max(voulu * STITCH_MAX, 1e-6)
    pieces = [list(m) for m in morceaux]

    # La couture d'origine du contour tombe au milieu d'un morceau dès que
    # le point de départ était bon : la fin du dernier et le début du
    # premier sont alors le même endroit, et ce sont deux bouts d'un seul.
    if len(pieces) > 1 and _gap(pieces[-1][-1], pieces[0][0]) <= saut:
        pieces[0] = pieces.pop() + pieces[0]

    out: list[G.Polyline] = []
    courant: G.Polyline = []
    for morceau in pieces:
        if not courant:
            courant = morceau
        elif _gap(courant[-1], morceau[0]) <= saut:
            courant.extend(morceau)
        else:
            out.append(courant)
            courant = morceau
    if courant:
        out.append(courant)
    return [_closed(c) for c in out if len(c) >= 3]


def _gap(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _closed(poly: G.Polyline) -> G.Polyline:
    """Le contour, refermé sur son premier point s'il ne l'est pas déjà."""
    if _gap(poly[0], poly[-1]) > 1e-9:
        return list(poly) + [poly[0]]
    return list(poly)


def offset_contours(contours: list[G.Polyline], distance: float,
                    retournes: frozenset = frozenset()) -> list[G.Polyline]:
    """Dilate ou érode des contours fermés de `distance` mm, symétriquement.

    Un offset positif **épaissit la matière** : les pleins grossissent et
    les contre-formes — le trou du « O », l'intérieur d'un motif fermé —
    se referment d'autant. C'est le comportement d'une compensation de
    trait : le faisceau a une largeur, et le relief laissé par une gravure
    en négatif sort plus fin que le dessin.

    Le sens de décalage ne se déduit pas du sens de parcours, qui n'a rien
    de garanti dans un DXF : on décale des deux côtés et l'on retient
    celui qui va dans le bon sens, en comparant les aires. Le creux se
    reconnaît à la règle **pair-impair**, la même que celle qui remplit la
    forme — ce qui garantit que l'offset et le remplissage voient la même
    matière. `retournes` donne les rangs des contours que le **groupe**
    retourne : un morceau seul dans sa forme, mais englobé par un autre
    membre, est un creux du dessin entier — voir `group_zones`.

    Un détail qui a son importance : une nervure plus fine que deux fois
    l'offset **disparaît**, et son contour retourné est écarté plutôt que
    tracé à l'envers. C'est physiquement juste — la matière n'y survit pas
    — et cela vaut mieux qu'un tracé qui se croise.
    """
    if not distance or not contours:
        return list(contours)
    fermes = [c for c in contours if len(c) >= 4]
    # Les boîtes d'abord : un point hors de la boîte d'un contour n'y est
    # pas, et le lancer de rayon le dirait aussi — même réponse, sans
    # parcourir les milliers de points de chacun des autres contours.
    boites = [G.bounds([c]) for c in fermes]
    grille = None
    out: list[G.Polyline] = []
    for rang, poly in enumerate(contours):
        if len(poly) < 4 or abs(_signed_area(poly)) < 1e-12:
            out.append(poly)
            continue
        px, py = poly[0]
        creux = (sum(1 for autre, (x0, y0, x1, y1) in zip(fermes, boites)
                     if autre is not poly and x0 <= px <= x1
                     and y0 <= py <= y1 and _inside(poly[0], autre)) % 2
                 == 1) != (rang in retournes)
        # solide + dilatation, ou creux + érosion : l'aire doit croître
        veut_plus_grand = (distance > 0) != creux
        depart = abs(_signed_area(poly))
        candidats = [_offset_polyline(poly, abs(distance)),
                     _offset_polyline(poly, -abs(distance))]
        aires = [abs(_signed_area(c)) if len(c) >= 4 else -1.0
                 for c in candidats]
        i = (0 if aires[0] > aires[1] else 1) if veut_plus_grand else \
            (0 if aires[0] < aires[1] else 1)
        retenu, aire = candidats[i], aires[i]
        if aire < 0:
            continue
        # la forme s'est retournée sur elle-même : le détail a disparu
        if not veut_plus_grand and aire >= depart:
            continue
        # Les boucles nées des angles rentrants sont retirées : gravées,
        # elles marquent à l'intérieur de l'angle — dans le creux d'un
        # « 2 » ou d'un « 6 » — là où l'on ne voulait rien marquer.
        if grille is None:
            # rangée une fois pour tous les contours : c'est la même source
            grille = _grille_source(contours, distance)
        out.extend(prune_offset(contours, retenu, distance, grille))
    return out


def shape_frame(shape: Shape, contours: list[G.Polyline]) -> G.Polyline:
    """Contour du cadre d'une forme, ou liste vide s'il n'y en a pas.

    Placé **avant** le dessin dans la liste des contours : le hachurage
    applique la règle pair-impair, donc la matière est enlevée entre le
    cadre et le dessin — celui-ci ressort en relief.

    Vaut pour toute forme, texte comme tracé DXF : creuser autour d'un
    logo importé est exactement le même problème que creuser autour de
    lettres, et la règle pair-impair traite les contre-formes seule.
    """
    if shape.frame not in ('rect', 'circle') or not contours:
        return []
    # Un code donne son encombrement complet, pas celui de son encre : le
    # coin haut-droit d'un DataMatrix peut être clair, et un cadre calé
    # sur l'encre n'aurait pas la même marge des quatre côtés.
    b = code_extent(shape) if isinstance(shape, Code) else G.bounds(contours)
    if b is None:
        return []
    x1, y1, x2, y2 = b
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    margin = max(0.0, shape.frame_margin_mm)

    if shape.frame == 'circle':
        if shape.frame_w > 0:
            radius = shape.frame_w / 2
        else:
            radius = math.hypot(x2 - x1, y2 - y1) / 2 + margin
        return G.circle_contour(radius, cx, cy)

    width = shape.frame_w if shape.frame_w > 0 else (x2 - x1) + 2 * margin
    height = shape.frame_h if shape.frame_h > 0 else (y2 - y1) + 2 * margin
    return G.rect_contour(width, height, cx, cy)


#: Ancien nom, conservé : le cadre n'était d'abord qu'une affaire de texte.
text_frame = shape_frame


def place(polylines: list[G.Polyline], shape: Shape) -> list[G.Polyline]:
    """Applique rotation puis translation d'une forme."""
    out = []
    for poly in polylines:
        p = G.rotate(poly, shape.rotation_deg)
        out.append(G.translate(p, shape.x, shape.y))
    return out


# --------------------------------------------------------------------------
# Cache de géométrie
# --------------------------------------------------------------------------
#
# Le hachurage d'un texte peut coûter plusieurs dizaines de millisecondes.
# Recalculé à chaque déplacement à la souris, il rend l'interface poissive.
#
# La géométrie est donc mémorisée **hors position** : rotation appliquée,
# translation non. Déplacer une forme ne recalcule alors plus rien, il ne
# reste qu'une translation. La clé retient tout ce qui change le tracé —
# et rien d'autre.

#: Sentinelle : une emprise mémorisée peut légitimement valoir None.
_MISSING = object()

_CACHE: dict[tuple, list[G.Polyline]] = {}
_CACHE_ORDER: deque[tuple] = deque()
_CACHE_POINTS: dict[tuple, int] = {}
#: Somme de `_CACHE_POINTS`, tenue à jour : la resommer à chaque entrée
#: coûtait autant que d'entrées déjà retenues — quadratique sur un hibou
#: séparé en cinq mille morceaux.
_CACHE_TOTAL = [0]

#: Le fil de l'esquisse de bibliothèque lit et range dans le même cache
#: que le plan de travail et l'export. Lire une entrée avec sa marque
#: d'oscillation abandonnée, ranger une entrée et évincer se font sous ce
#: verrou ; le calcul, lui, se fait hors verrou. Sans lui, une éviction
#: glissée entre la lecture d'une entrée et celle de sa marque rendait le
#: trait sans oscillation **sans le signaler** — l'export passait —, et
#: deux fils rangeant la même entrée la comptaient deux fois.
_VERROU = threading.RLock()

#: Le cache est borné par le **nombre de points retenus**, pas par le
#: nombre d'entrées. Un plafond en nombre d'entrées se comporte très mal
#: aux deux extrêmes : 128 entrées de texte hachuré, c'est déjà beaucoup
#: de mémoire, tandis qu'un document de 300 petites plaques dépassait ce
#: plafond et recalculait tout à chaque rafraîchissement — la sélection
#: complète d'un tel document prenait une seconde et demie.
_CACHE_MAX_POINTS = 3_000_000

#: Points au-delà desquels une entrée est rangée **compacte**.
#:
#: Un point en couple de flottants coûte 113 octets ; dans un tableau de
#: flottants, 16. Le plafond se comptait en couples : un texte oscillé de
#: deux millions et demi de points y tenait à peine, et un document dont
#: la géométrie le dépassait **ne gardait plus rien** — chaque forme
#: évinçait celle dont on aurait besoin ensuite, et tout se recalculait à
#: chaque construction, oscillation comprise : trois secondes et demie
#: pour un rectangle oscillé et son texte. Rangée compacte, une grosse
#: entrée ne compte plus que pour un septième de ses points
#: (`_COMPACT_POIDS`) : le même plafond en tient sept fois plus, pour la
#: même mémoire. La relire coûte de la recréer en couples — 0,4 s pour
#: deux millions et demi de points, quand les recalculer en prenait
#: trois ; une petite entrée, relue sans frais, reste donc en couples.
_COMPACT_POINTS = 100_000
_COMPACT_POIDS = 7


class _Compact(tuple):
    """Une entrée compacte : un tableau `array('d')` par polyligne, les
    coordonnées à plat, x et y alternés. Les flottants y sont rangés tels
    quels : relue, la géométrie est identique au bit."""

    __slots__ = ()


def _compacte(polylines: list[G.Polyline]) -> _Compact:
    chaine = itertools.chain.from_iterable
    return _Compact(array('d', chaine(p)) for p in polylines)


def _deplie(entree: _Compact) -> list[G.Polyline]:
    sortie = []
    for tableau in entree:
        it = iter(tableau)
        sortie.append(list(zip(it, it)))
    return sortie


#: Entrées dont l'oscillation a été abandonnée, et les points qu'elle
#: aurait produits — voir `dense_wobble`.
_DENSES: dict[tuple, int] = {}

#: Relevé en cours des oscillations abandonnées, propre à chaque fil :
#: l'esquisse de la bibliothèque calcule dans le sien.
_RELEVE = threading.local()


@contextlib.contextmanager
def dense_wobble():
    """Relève les formes dont l'oscillation a été abandonnée dans le bloc.

    Rend un dictionnaire `forme → (points, pas, nom)`, rempli au fil des
    constructions : par le calcul qui abandonne, comme par la lecture du
    cache d'une entrée abandonnée plus tôt. Au-delà de
    `wobble.MAX_POINTS`, la trajectoire reste sans oscillation : le plan
    de travail montre ainsi le dessin sans se figer, mais graver ce trait
    fin à la place de la bande demandée serait faux — la vérification le
    bloque, et l'export le refuse.

    Un relevé ouvert dans un autre ne lui cache rien : ce qu'il a relevé
    remonte au relevé englobant à la sortie.
    """
    avant = getattr(_RELEVE, 'courant', None)
    _RELEVE.courant = releve = {}
    try:
        yield releve
    finally:
        _RELEVE.courant = avant
        if avant is not None:
            for cle, valeur in releve.items():
                avant.setdefault(cle, valeur)


def _signale_dense(shape: Shape, points: int) -> None:
    releve = getattr(_RELEVE, 'courant', None)
    if releve is not None:
        # par forme et non par nom : deux textes « TAU » sont deux formes
        releve.setdefault(shape.id or id(shape),
                          (points, shape.recipe.wobble_pitch_mm,
                           shape.display_name()))


def _oscille(recipe) -> bool:
    """L'oscillation est-elle active ? Une amplitude ou un pas nul la
    coupe aussi sûrement que « aucune »."""
    return (recipe.wobble != 'none' and recipe.wobble_amp_mm > 0
            and recipe.wobble_pitch_mm > 0)


def _couches(recipe) -> int:
    """Géométries distinctes qu'une forme calcule pour l'export : une par
    passe quand le hachurage tourne — sauf en anneaux, que l'angle ne
    change pas —, une seule sinon."""
    if (recipe.hatch_angle_step_deg and recipe.hatch_mm > 0
            and getattr(recipe, 'fill_style', 'hatch') != 'rings'):
        return max(1, int(recipe.passes or 1))
    return 1


#: Calculs d'essai en cours — voir `trial_cache`.
_ESSAI = [0]


@contextlib.contextmanager
def trial_cache():
    """Ce qui se calcule dedans ne prend au cache que la place libre.

    La vérification essaie d'autres réglages — « Enchaîner », anneaux —
    pour chiffrer ce qu'ils feraient gagner. Rangés comme les autres, ces
    essais chassaient du cache la géométrie du document lui-même : sur un
    texte oscillé de deux millions et demi de points, l'export qui suit
    la vérification recalculait tout, deux secondes de plus. Un essai est
    désormais rangé **en tête de file**, là où l'on évince d'abord : il
    n'occupe que la place libre, et cède la sienne au premier calcul réel.
    """
    _ESSAI[0] += 1
    try:
        yield
    finally:
        _ESSAI[0] -= 1


def clear_cache() -> None:
    """Vide le cache de géométrie."""
    with _VERROU:
        _vide_caches()


def _vide_caches() -> None:
    _CACHE.clear()
    _CACHE_ORDER.clear()
    _CACHE_POINTS.clear()
    _DENSES.clear()
    _EXTENTS.clear()
    _EXTENT_ORDER.clear()
    _GROUPES.clear()
    _GROUPES_ORDRE.clear()
    _GROUPES_POINTS.clear()
    _PROPRES.clear()
    _PROPRES_POINTS[0] = 0
    _CACHE_TOTAL[0] = 0
    _ORDRES.clear()
    _ORDRES_RANGS[0] = 0


def cache_size() -> tuple[int, int]:
    """(entrées, points) actuellement retenus — une entrée compacte compte
    pour un septième de ses points, voir `_COMPACT_POINTS`."""
    return len(_CACHE), _CACHE_TOTAL[0]


def geometry_key(shape: Shape, context: dict | None = None,
                 pass_index: int = 0) -> tuple | None:
    """Clé de cache, ou None si la forme n'est pas mémorisable.

    Le **rang de passe** entre dans la clé : dès qu'une recette fait
    tourner son hachurage d'une passe à l'autre, la géométrie n'est plus
    la même, et deux passes du même dessin ne peuvent plus partager une
    entrée de cache.
    """
    r = shape.recipe
    # le cadre appartient désormais à toute forme : il entre dans la partie
    # commune de la clé, sinon un DXF encadré resterait affiché sans cadre
    common = (shape.rotation_deg, r.hatch_mm, r.hatch_angle_deg,
              r.hatch_angle_step_deg, r.hatch_cross, r.hatch_inset_mm,
              getattr(r, 'link_paths', False),
              getattr(r, 'fill_style', 'hatch'),
              r.wobble, r.wobble_amp_mm, r.wobble_pitch_mm,
              # Le plafond d'oscillation vaut pour toutes les passes de la
              # forme (`_couches`) : leur nombre décide si elle oscille ou
              # si elle est relevée trop dense. Hors clé, une entrée prise
              # à huit passes resservait à quatre, refus compris.
              _couches(r) if _oscille(r) else 1,
              # en anneaux, l'angle ne change rien : une seule entrée
              pass_index if (r.hatch_angle_step_deg and getattr(
                  r, 'fill_style', 'hatch') != 'rings') else 0,
              shape.frame,
              shape.frame_margin_mm, shape.frame_offset_mm,
              shape.frame_w, shape.frame_h,
              shape.line_width_mm, shape.line_step_mm,
              getattr(shape, 'line_side', 'both'))
    if isinstance(shape, Rect):
        return ('rect', shape.width, shape.height) + common
    if isinstance(shape, Circle):
        return ('circle', shape.width, shape.height) + common
    if isinstance(shape, (Text, Code)):
        return drawing_key(shape, context) + common
    if isinstance(shape, Path):
        # les polylignes d'un tracé importé changent au redimensionnement :
        # la clé retient donc aussi les extrémités du premier tracé, seul
        # invariant bon marché qui bouge quand la mise à l'échelle bouge
        # les extrémités sont converties en tuples : un document relu depuis
        # le JSON rend ses points sous forme de listes, qui ne peuvent pas
        # entrer dans une clé de dictionnaire
        first = shape.polylines[0] if shape.polylines else ()
        marker = (tuple(first[0]), tuple(first[-1])) if first else ()
        return ('path', path_token(shape), len(shape.polylines),
                marker) + common
    return None


#: Numéros des tracés, jamais rendus — voir `path_token`.
_JETONS = itertools.count(1)


def path_token(shape: Shape) -> int:
    """Numéro propre à ce tracé dans la clé de cache, **jamais réemployé**.

    La clé retenait `id(shape)` : un numéro que Python **redonne** à un
    objet neuf dès que l'ancien est libéré. Une copie, un collage, une
    case de grille venaient parfois s'asseoir à l'adresse d'un tracé
    disparu — et gravaient ses trajectoires à lui : une flèche retournée
    puis répétée sortait à l'endroit dans une case. Le numéro est rangé
    sur l'objet avec son adresse ; un objet recopié tel quel (`copy`,
    `deepcopy`) n'a plus la même adresse et reçoit le sien.
    """
    jeton = shape.__dict__.get('_jeton')
    if jeton is None or jeton[1] != id(shape):
        jeton = (next(_JETONS), id(shape))
        shape.__dict__['_jeton'] = jeton
    return jeton[0]


def renew_path_token(shape: Shape) -> None:
    """Oublie le numéro d'un tracé dont les polylignes changent sur place
    : ses trajectoires mémorisées ne valent plus."""
    shape.__dict__.pop('_jeton', None)


# --------------------------------------------------------------------------
# Remplissage d'un groupe : le pair-impair entre ses membres
# --------------------------------------------------------------------------
#
# Un logo DXF arrive d'un bloc, et la règle pair-impair le remplit juste :
# le contour extérieur est gravé, celui qu'il englobe ne l'est pas, le
# suivant l'est de nouveau. **Séparé**, ce même logo devenait une forme
# par contour, chacune remplie pour elle seule : le trou du « O », devenu
# une forme, se remplissait aussi, et le logo sortait en aplat — dégroupé,
# retouché puis regroupé, il le restait. Séparer promettait pourtant de ne
# rien changer à ce qui part à la machine.
#
# Le groupe est désormais l'unité du pair-impair. Chaque contour compte
# combien d'autres l'englobent, contours des autres membres compris :
# pair, il est gravé ; impair, c'est un trou. Chaque anneau ainsi
# délimité se remplit avec la recette du contour qui le borde à
# l'extérieur, si bien qu'un groupe dont les membres partagent une recette
# se remplit comme la forme d'origine.
#
# Ne comptent que les membres **visibles et remplis**. Un cadre gravé au
# seul trait n'ouvre pas de trou dans ce qu'il entoure : c'est le cas
# courant d'un calque de découpe autour d'un logo, qui doit continuer de
# graver le logo plein. Un code 2D se remplit lui-même, module par module,
# et reste à part. Deux contours qui se croisent sans que l'un englobe
# l'autre se remplissent chacun en entier, comme avant : la règle porte
# sur les contours **englobés**.

#: Groupes déjà analysés, sous une clé qui ne retient que leur état
#: **relatif** : déplacer un groupe entier ne refait pas le calcul.
#:
#: Borné par le **nombre de points retenus**, comme le cache des
#: trajectoires : une entrée porte les trous que chaque membre reçoit des
#: autres, et celle d'un logo séparé pèse plusieurs mégaoctets. Retoucher
#: un membre au clavier en crée une par cran.
_GROUPES: dict[tuple, list] = {}
_GROUPES_ORDRE: list[tuple] = []
_GROUPES_POINTS: dict[tuple, int] = {}
_GROUPES_MAX_POINTS = 2_000_000
_GROUPES_MAX = 512


def _participe(shape: Shape) -> bool:
    """Vrai si les contours de la forme comptent dans l'alternance de son
    groupe : visible, remplie, et pas un code."""
    return (shape.visible and not isinstance(shape, Code)
            and shape.recipe.hatch_mm > 0)


@dataclass(frozen=True)
class GroupZone:
    """Ce que son groupe change au remplissage d'une forme.

    `exclus` : rangs de ses contours qui sont des trous d'un **autre**
    membre — ils ne bordent plus son remplissage, mais celui de l'autre.
    `ajouts` : contours d'autres membres qu'elle englobe directement,
    ramenés dans son repère local — ce sont des trous de son remplissage.
    `retournes` : rangs de ses contours propres que le groupe fait passer
    de plein à creux, ou l'inverse. Seul le décalage (`frame_offset_mm`)
    s'en sert : il doit refermer un trou, et non le grossir comme s'il
    était un plein — voir `offset_contours`.
    `nombre` : combien de contours la forme avait au calcul. S'il a changé
    — un texte à l'heure passé à la minute suivante —, la zone ne
    s'applique plus : mieux vaut un remplissage seul qu'un trou mal placé.

    Les contours restent gravés chacun par sa forme, avec sa recette.
    """
    exclus: frozenset
    ajouts: tuple
    retournes: frozenset
    nombre: int

    def __post_init__(self) -> None:
        # la clé de cache se calcule une fois : hacher les trous à chaque
        # consultation coûtait près d'une milliseconde par forme
        object.__setattr__(self, '_cle', (
            tuple(sorted(self.exclus)), tuple(sorted(self.retournes)),
            self.nombre, len(self.ajouts), hash(self.ajouts)))

    def contours(self, propres: list[G.Polyline]) -> list[G.Polyline]:
        """La zone à remplir, à partir des contours propres de la forme."""
        if len(propres) != self.nombre:
            return list(propres)
        return ([c for k, c in enumerate(propres) if k not in self.exclus]
                + [list(c) for c in self.ajouts])

    def signature(self) -> tuple:
        return ('groupe',) + self._cle


def group_zones(shapes, context: dict | None = None, *,
                ensemble: bool = False) -> dict[str, GroupZone]:
    """Pour chaque forme dont le groupe change le remplissage, ce
    changement ; rien pour les autres.

    `shapes` est le document entier ou une sélection : seuls les membres
    présents comptent, et les formes masquées n'y prennent aucune part.
    `ensemble` les tient toutes pour un seul groupe, comme les groupera la
    pose — l'aperçu d'un dessin de bibliothèque doit montrer ce qu'on
    posera.
    """
    par_groupe: dict[str, list[Shape]] = {}
    for s in shapes:
        if (s.group or ensemble) and _participe(s):
            par_groupe.setdefault('' if ensemble else s.group,
                                  []).append(s)
    zones: dict[str, GroupZone] = {}
    for parts in par_groupe.values():
        if len(parts) < 2:
            continue
        for s, zone in zip(parts, _zones_du_groupe(parts, context)):
            if zone is not None:
                zones[s.id] = zone
    return zones


def _zones_du_groupe(parts: list[Shape], context: dict | None) -> list:
    """Une `GroupZone`, ou None, par membre — dans l'ordre de `parts`.

    Les positions sont prises **par rapport au premier membre**, arrondies
    au nanomètre : un groupe qu'on déplace garde sa clé, et ses zones.
    """
    ref = parts[0]
    decalages = [(round(m.x - ref.x, 9), round(m.y - ref.y, 9))
                 for m in parts]
    cles = [geometry_key(m, context) for m in parts]
    cle = (None if any(c is None for c in cles)
           else tuple(zip(cles, decalages)))
    if cle is not None:
        with _VERROU:
            connu = _GROUPES.get(cle)
        if connu is not None:
            return connu
    zones = _analyse_groupe(parts, decalages, context)
    if cle is not None:
        poids = len(zones) + sum(
            len(c) for z in zones if z is not None for c in z.ajouts)
        # sous le verrou, comme `_PROPRES` : le fil de la bibliothèque
        # remplit aussi des groupes, et une somme parcourue pendant qu'un
        # autre fil insère lève `RuntimeError`
        with _VERROU:
            if cle not in _GROUPES:
                _GROUPES[cle] = zones
                _GROUPES_ORDRE.append(cle)
                _GROUPES_POINTS[cle] = poids
            total = sum(_GROUPES_POINTS.values())
            while (len(_GROUPES_ORDRE) > 1
                   and (total > _GROUPES_MAX_POINTS
                        or len(_GROUPES_ORDRE) > _GROUPES_MAX)):
                vieux = _GROUPES_ORDRE.pop(0)
                _GROUPES.pop(vieux, None)
                total -= _GROUPES_POINTS.pop(vieux, 0)
    return zones


def _analyse_groupe(parts: list[Shape], decalages: list,
                    context: dict | None) -> list:
    nuls = [None] * len(parts)
    # les boîtes d'abord : des membres qui ne se recouvrent pas ne peuvent
    # rien s'englober, et c'est le cas de presque tous les groupes — un
    # code et son texte, les cases d'un coupon
    boites = []
    for m, (dx, dy) in zip(parts, decalages):
        b = shape_extent(m, context)
        boites.append(None if b is None else
                      (b[0] - m.x + dx, b[1] - m.y + dy,
                       b[2] - m.x + dx, b[3] - m.y + dy))
    if not _recouvrement(boites):
        return nuls

    def place(c: G.Polyline, p: int) -> G.Polyline:
        dx, dy = decalages[p]
        return G.translate(G.rotate(c, parts[p].rotation_deg), dx, dy)

    # Un décalage grossit les pleins et referme les creux : il doit savoir
    # quels contours le groupe rend creux. Le dessin d'origine en décide,
    # avant tout décalage et sans cadre — comme pour une forme seule, dont
    # le cadre n'entre pas dans ce compte. Sans cela, le trou d'un logo
    # séparé, plein à lui seul, grossissait au lieu de se refermer.
    #
    # Tous les membres comptent, décalés ou non — le contre-poinçon d'un
    # logo séparé, décalé seul, reste le trou de la lettre qui l'entoure —
    # **sauf le cadre sorti d'un dessin encadré** (`detached_frame`) : il
    # n'entrait pas dans le compte de la forme d'origine, il n'entre pas
    # dans celui du groupe. Compté, il faisait du dessin entier un trou,
    # qui s'amincissait au lieu de s'épaissir.
    retournes: list[frozenset] = [frozenset()] * len(parts)
    if any(getattr(m, 'frame_offset_mm', 0.0) for m in parts):
        rangs0: list[tuple[int, int]] = []
        places0: list[G.Polyline] = []
        for q, m in enumerate(parts):
            if getattr(m, 'detached_frame', False):
                continue
            for k, c in enumerate(own_contours(m, context)):
                rangs0.append((q, k))
                places0.append(place(c, q))
        englobants = _englobants(places0)
        inverses: list[set] = [set() for _ in parts]
        for i, (q, k) in enumerate(rangs0):
            if not getattr(parts[q], 'frame_offset_mm', 0.0):
                continue
            etrangers = sum(1 for j in englobants[i] if rangs0[j][0] != q)
            if etrangers % 2:
                inverses[q].add(k)
        retournes = [frozenset(r) for r in inverses]

    rangs: list[tuple[int, int]] = []       # (membre, rang du contour)
    places: list[G.Polyline] = []
    nombres: list[int] = []
    for q, m in enumerate(parts):
        propres = shape_contours(m, context, retournes[q])
        nombres.append(len(propres))
        for k, c in enumerate(propres):
            rangs.append((q, k))
            places.append(place(c, q))
    niveaux = _emboitement(places)

    exclus: list[set] = [set() for _ in parts]
    ajouts: list[list] = [[] for _ in parts]
    for i, (profondeur, parent) in enumerate(niveaux):
        if parent < 0 or profondeur % 2 == 0:
            continue
        q, k = rangs[i]
        hote = rangs[parent][0]
        if hote == q:
            # un trou dans un contour de la même forme : son propre
            # pair-impair s'en charge, comme avant
            continue
        # un trou dans un autre membre : il borde le remplissage de ce
        # membre-là, et plus le sien
        exclus[q].add(k)
        ajouts[hote].append(i)

    zones = []
    for q, m in enumerate(parts):
        if not exclus[q] and not ajouts[q] and not retournes[q]:
            zones.append(None)
            continue
        dx, dy = decalages[q]
        locaux = tuple(
            tuple(G.rotate(G.translate(places[i], -dx, -dy),
                           -m.rotation_deg))
            for i in ajouts[q])
        zones.append(GroupZone(frozenset(exclus[q]), locaux, retournes[q],
                               nombres[q]))
    return zones


def _recouvrement(boites) -> bool:
    """Vrai si deux des boîtes se recouvrent."""
    vues = sorted((b for b in boites if b is not None), key=lambda b: b[0])
    for i, a in enumerate(vues):
        for b in vues[i + 1:]:
            if b[0] > a[2]:
                break
            if b[1] <= a[3] and a[1] <= b[3]:
                return True
    return False


def _emboitement(contours: list[G.Polyline]) -> list[tuple[int, int]]:
    """(profondeur, parent) de chaque contour ; parent -1 s'il n'en a pas.

    La profondeur est le nombre de contours qui l'englobent — voir
    `_englobants` —, le parent le plus profond d'entre eux.
    """
    dans = _englobants(contours)
    boites = [G.bounds([c]) if c else None for c in contours]

    def aire(j: int) -> float:
        b = boites[j]
        return (b[2] - b[0]) * (b[3] - b[1])

    return [(len(d), max(d, key=lambda j: (len(dans[j]), -aire(j)),
                         default=-1))
            for d in dans]


def _englobants(contours: list[G.Polyline]) -> list[set]:
    """Pour chaque contour, les rangs de ceux qui l'englobent.

    Être englobé se juge comme dans `_holes` : la boîte d'abord, puis la
    majorité des témoins pris au milieu des côtés. Un contour de moins de
    trois points, ou plat, n'englobe rien et n'est englobé par rien.

    **Deux contours confondus** — le même tracé sur deux calques, un
    morceau recopié sur place — ont leurs témoins sur le bord l'un de
    l'autre, où le lancer de rayon répond au hasard : selon la finesse
    du tracé, la zone était gravée deux fois ou pas du tout. Ils sont
    reconnus à leurs boîtes égales et à leurs témoins posés sur le bord
    de l'autre ; le premier dans l'ordre est alors l'extérieur, et le
    second un trou — ce que fait le pair-impair d'une forme seule, qui
    les annule.

    Une grille range les boîtes : un contour ne cherche ses englobants que
    parmi ceux qui couvrent la case de son centre. Sans elle, les quelques
    centaines de contours d'un logo séparé se comparaient tous deux à deux
    à chaque calcul. Et chaque englobant range ses arêtes par tranche
    horizontale : le contour extérieur d'un logo porte des milliers de
    points, et le lancer de rayon les parcourait tous pour chacun des
    témoins de chacune de ses îles — 33 s sur un hibou de 1 907 tracés.
    """
    n = len(contours)
    boites: list = [None] * n
    for i, c in enumerate(contours):
        if len(c) < 3:
            continue
        xs = [x for x, _ in c]
        ys = [y for _, y in c]
        b = (min(xs), min(ys), max(xs), max(ys))
        if (b[2] - b[0] > 1e-9 and b[3] - b[1] > 1e-9
                and len({(x, y) for x, y in c}) >= 3):
            boites[i] = b
    valides = [i for i in range(n) if boites[i] is not None]
    dans: list[set] = [set() for _ in range(n)]
    if len(valides) < 2:
        return dans

    x0 = min(boites[i][0] for i in valides)
    y0 = min(boites[i][1] for i in valides)
    x1 = max(boites[i][2] for i in valides)
    y1 = max(boites[i][3] for i in valides)
    cote = max(1, min(64, int(math.sqrt(len(valides)))))
    lx = (x1 - x0) / cote or 1.0
    ly = (y1 - y0) / cote or 1.0

    def case(x: float, y: float) -> tuple[int, int]:
        return (min(cote - 1, max(0, int((x - x0) / lx))),
                min(cote - 1, max(0, int((y - y0) / ly))))

    grille: dict[tuple[int, int], list[int]] = {}
    for i in valides:
        bx0, by0, bx1, by1 = boites[i]
        (ix0, iy0), (ix1, iy1) = case(bx0, by0), case(bx1, by1)
        for gx in range(ix0, ix1 + 1):
            for gy in range(iy0, iy1 + 1):
                grille.setdefault((gx, gy), []).append(i)

    tranches: dict[int, tuple] = {}

    def rangee(j: int, y: float) -> list:
        if j not in tranches:
            tranches[j] = _tranches(contours[j], boites[j])
        haut, base, rangees = tranches[j]
        return rangees.get(int((y - base) / haut), ())

    def dedans(t: tuple[float, float], j: int) -> bool:
        """`_inside(t, contours[j])`, sur les seules arêtes de la tranche."""
        x, y = t
        dans_ = False
        for ax, ay, bx, by in rangee(j, y):
            if ((ay > y) != (by > y)
                    and ax + (y - ay) / (by - ay) * (bx - ax) > x):
                dans_ = not dans_
        return dans_

    def sur_le_bord(temoins: list, j: int) -> bool:
        """Vrai si la plupart des témoins tombent sur le bord de `j`."""
        sur = sum(1 for x, y in temoins
                  if any(_point_segment(x, y, (ax, ay), (bx, by)) <= 1e-6
                         for ax, ay, bx, by in rangee(j, y)))
        return 2 * sur > len(temoins)

    jeu = 1e-9
    for i in valides:
        ax0, ay0, ax1, ay1 = boites[i]
        temoins = None
        for j in grille.get(case((ax0 + ax1) / 2, (ay0 + ay1) / 2), ()):
            if j == i:
                continue
            bx0, by0, bx1, by1 = boites[j]
            if not (bx0 - jeu <= ax0 and ax1 <= bx1 + jeu
                    and by0 - jeu <= ay0 and ay1 <= by1 + jeu):
                continue
            if temoins is None:
                temoins = _temoins(contours[i])
            if (max(abs(ax0 - bx0), abs(ay0 - by0), abs(ax1 - bx1),
                    abs(ay1 - by1)) <= 1e-6 and sur_le_bord(temoins, j)):
                # confondus : le premier dans l'ordre est l'extérieur
                if j < i:
                    dans[i].add(j)
                continue
            if 2 * sum(1 for t in temoins if dedans(t, j)) > len(temoins):
                dans[i].add(j)
    # deux contours presque confondus peuvent encore s'englober l'un
    # l'autre : là aussi, le premier dans l'ordre est tenu pour l'extérieur
    for i in valides:
        dans[i] = {j for j in dans[i] if not (i in dans[j] and j > i)}
    return dans


def _tranches(c: G.Polyline, boite: tuple) -> tuple:
    """Les arêtes d'un contour rangées par tranche horizontale :
    `(hauteur, base, {rang: [(ax, ay, bx, by), …]})`.

    Mêmes arêtes que `_inside`, fermeture comprise ; une arête est rangée
    dans toutes les tranches que couvre son étendue verticale.
    """
    points = c[:-1] if c[0] == c[-1] and len(c) > 2 else c
    base = boite[1]
    haut = (boite[3] - base) / max(1, int(math.sqrt(len(points)))) or 1.0
    rangees: dict[int, list] = {}
    for i, (ax, ay) in enumerate(points):
        bx, by = points[i - 1]
        for k in range(int((min(ay, by) - base) / haut),
                       int((max(ay, by) - base) / haut) + 1):
            rangees.setdefault(k, []).append((ax, ay, bx, by))
    return haut, base, rangees


#: Au-delà de ce nombre de rangées, un remplissage n'est plus une gravure.
#: Cinq cent mille rangées, c'est la diagonale d'un champ de 300 mm au
#: millième de millimètre, ou 25 m au pas courant de 0,05 mm — et des
#: dizaines d'heures de marquage. Seul un fichier abîmé ou importé dans la
#: mauvaise unité y arrive : un PDF tronqué rendait une emprise de 331 km,
#: dont le hachurage tournait sans fin et bloquait la lecture.
MAX_RANGEES = 500_000


def fill_too_large(bounds, step: float) -> bool:
    """Vrai si remplir l'emprise `bounds` au pas `step` dépasse
    `MAX_RANGEES`, quel que soit l'angle : la diagonale sur le pas."""
    if bounds is None or step <= 0:
        return False
    x1, y1, x2, y2 = bounds
    return math.hypot(x2 - x1, y2 - y1) / step > MAX_RANGEES


def unfilled_shapes(document: Document) -> list[Shape]:
    """Les formes visibles dont le remplissage est omis — voir
    `MAX_RANGEES`. Un code fait son propre remplissage, à son échelle :
    ce sont ses traits qui se comptent — voir `code_fill_too_large`."""
    return [s for s in document.shapes
            if s.visible and (
                code_fill_too_large(s) if isinstance(s, Code)
                else s.recipe.hatch_mm > 0
                and fill_too_large(shape_extent(s), s.recipe.hatch_mm))]


def unthickened_shapes(document: Document) -> list[Shape]:
    """Les formes visibles dont l'épaississement est omis — voir
    `MAX_PASSAGES`."""
    return [s for s in document.shapes
            if s.visible and thicken_too_large(s.line_width_mm, line_step(s))]


def fill_contours(shape: Shape, contours: list[G.Polyline],
                  pass_index: int = 0) -> list[G.Polyline]:
    """Le remplissage d'une forme, retrait, croisement et rotation compris.

    Trois réglages viennent s'ajouter au pas et à l'angle :

    * **retrait** — le remplissage s'arrête sur la frontière, mais le
      faisceau a une largeur et déborde d'un demi-spot. Rentrer la nappe
      de 0,015 mm met le bord de la zone gravée sur le contour ;
    * **croisement** — une seconde nappe à +90° dans la même passe, pour
      une surface homogène en un seul passage ;
    * **rotation par passe** — sans elle, les creux du premier passage
      guident le second et le fond sort strié.
    """
    r = shape.recipe
    if r.hatch_mm <= 0 or not contours:
        return []
    if fill_too_large(G.bounds(contours), r.hatch_mm):
        # démesuré : le contour seul, que le contrôle avant export signale
        return []
    if getattr(r, 'fill_style', 'hatch') == 'rings':
        # anneaux parallèles au contour : le retrait se fait par GEOS, plus
        # sûr que `offset_contours` sur un dessin tourmenté
        from . import rings
        anneaux = rings.fill(contours, r.hatch_mm, r.hatch_inset_mm,
                             link=getattr(r, 'link_paths', False))
        if anneaux is not None:
            return anneaux
        # sans shapely (TauConvert) : le hachurage, plutôt que rien
    zone = contours
    if r.hatch_inset_mm > 0:
        rentre = offset_contours(contours, -abs(r.hatch_inset_mm))
        # une forme plus fine que deux fois le retrait disparaîtrait
        # entièrement : mieux vaut un remplissage qui déborde d'un
        # demi-spot qu'une case vide sur la pièce
        zone = rentre or contours
    angle = r.hatch_angle_deg + pass_index * r.hatch_angle_step_deg
    # rangées enchaînées : un allumage par île plutôt qu'un par segment
    remplir = G.hatch_linked if getattr(r, 'link_paths', False) \
        else G.hatch
    nappes = remplir(zone, r.hatch_mm, angle)
    if r.hatch_cross:
        nappes = nappes + remplir(zone, r.hatch_mm, angle + 90.0)
    return nappes


def _local_cached(shape: Shape, context: dict | None,
                  pass_index: int = 0,
                  zone: GroupZone | None = None,
                  brut: bool = False) -> list[G.Polyline]:
    """Trajectoires locales d'une forme, mémorisées.

    `brut` rend une entrée compacte telle quelle, sans la déplier : à qui
    la translate de toute façon, la déplier d'abord ferait deux passages
    — voir `_COMPACT_POINTS`.
    """
    key = geometry_key(shape, context, pass_index)
    if key is not None and zone is not None:
        # le remplissage dépend alors des autres membres du groupe : leur
        # part entre dans la clé — voir `group_zones`
        key = key + zone.signature()
    if key is not None:
        with _VERROU:
            hit = _CACHE.get(key)
            dense = _DENSES.get(key) if hit is not None else None
        if hit is not None:
            if dense is not None:
                _signale_dense(shape, dense)
            if type(hit) is _Compact and not brut:
                return _deplie(hit)
            return hit

    contours = shape_contours(shape, context,
                              zone.retournes if zone is not None
                              else frozenset())
    if not contours:
        return []
    polylines = _outline_of(shape, contours)
    nb_contour = len(polylines)
    if isinstance(shape, Code):
        # un code se remplit lui-même : le hachurage générique, à balayage
        # global, traverserait des centaines de rectangles et coûterait
        # cent fois plus cher pour un résultat identique
        polylines += code_fill(shape, context)
    else:
        polylines += fill_contours(
            shape, contours if zone is None else zone.contours(contours),
            pass_index)
    if shape.line_width_mm > 0:
        step = line_step(shape)
        # un code n'a pas de contour à lui : ses arêtes de modules, jointes,
        # se croisent aux coins de deux modules en diagonale, et n'ont ni
        # dedans ni dehors. Elles s'élargissent des deux côtés.
        cote = ('both' if isinstance(shape, Code)
                else getattr(shape, 'line_side', 'both'))
        if cote in ('inside', 'outside'):
            # d'un seul côté, seul le contour s'épaissit : le remplissage
            # occupe déjà le dedans, et élargies, ses rangées du bord
            # déborderaient de la pièce d'une demi-épaisseur
            polylines = (thicken(polylines[:nb_contour], shape.line_width_mm,
                                 step, cote) + polylines[nb_contour:])
        else:
            # l'épaississement suit le hachurage : il élargit aussi les
            # segments de remplissage, ce qui permet de creuser large avec
            # un pas de hachurage grossier — bien moins de trajet à vide
            polylines = thicken(polylines, shape.line_width_mm, step)
    # L'oscillation vient **en dernier** : elle s'applique à la
    # trajectoire finale, contour et remplissage compris, car c'est le
    # trait gravé qu'elle élargit — pas la forme qu'on a dessinée.
    r = shape.recipe
    dense = 0
    if _oscille(r):
        # compté avant d'être calculé : un pas tapé cent fois trop fin
        # figeait TauDrive — voir `wobble.MAX_POINTS`. Le plafond vaut
        # pour la forme entière : quand le hachurage tourne, chaque passe
        # a sa géométrie, et chacune compte.
        points = wobble.point_count(polylines, r.wobble_pitch_mm) \
            * _couches(r)
        if points > wobble.MAX_POINTS:
            dense = points
            _signale_dense(shape, points)
        else:
            polylines = wobble.apply(polylines, r.wobble_amp_mm,
                                     r.wobble_pitch_mm, r.wobble)
    # sans rotation, les polylignes sont déjà neuves — contours copiés,
    # remplissage tout juste calculé : les recopier une à une ne servait
    # qu'à doubler le temps passé sur un code à mille rangées
    result = ([G.rotate(p, shape.rotation_deg) for p in polylines]
              if shape.rotation_deg else polylines)

    if key is not None:
        points = sum(len(poly) for poly in result)
        if points >= _COMPACT_POINTS:
            # une grosse entrée, rangée compacte — voir `_COMPACT_POINTS`
            entree = _compacte(result)
            points = points // _COMPACT_POIDS + 1
        else:
            entree = result
        with _VERROU:
            # un autre fil a pu la ranger pendant le calcul : la ranger une
            # seconde fois la compterait deux fois
            if key not in _CACHE:
                _CACHE[key] = entree
                if dense:
                    _DENSES[key] = dense
                if _ESSAI[0]:
                    # le premier évincé : il ne chasse personne — voir
                    # `trial_cache`
                    _CACHE_ORDER.appendleft(key)
                else:
                    _CACHE_ORDER.append(key)
                _CACHE_POINTS[key] = points
                _CACHE_TOTAL[0] += points
                while (_CACHE_TOTAL[0] > _CACHE_MAX_POINTS
                       and len(_CACHE_ORDER) > 1):
                    oldest = _CACHE_ORDER.popleft()
                    _CACHE.pop(oldest, None)
                    _DENSES.pop(oldest, None)
                    _CACHE_TOTAL[0] -= _CACHE_POINTS.pop(oldest, 0)
    return result


#: Nappes dessinées au plus, quand les passes tournent.
#:
#: Un remplissage à cent passes couvrirait la forme d'un aplat noir,
#: illisible et cent fois plus lourd à peindre. Au-delà, les
#: premières nappes suffisent à montrer **que** les angles tournent, et
#: dans quel sens.
NAPPES_MONTREES = 6


def pass_angles(recipe) -> list[float]:
    '''Les angles de hachurage réellement gravés, en degrés.

    Un seul si la recette ne fait pas tourner les passes — c'est le cas
    courant. Autant que de passes sinon, et l'écran doit les montrer :
    trois nappes à 60° ne ressemblent pas du tout à une seule.
    '''
    n = max(1, int(getattr(recipe, 'passes', 1) or 1))
    pas = float(getattr(recipe, 'hatch_angle_step_deg', 0.0) or 0.0)
    base = float(getattr(recipe, 'hatch_angle_deg', 0.0) or 0.0)
    if n <= 1 or pas == 0.0 or not getattr(recipe, 'hatch_mm', 0.0):
        return [base]
    # deux passes séparées de 180° tracent les mêmes droites : compter
    # les angles **distincts modulo 180**, et non les passes
    vus, angles = set(), []
    for i in range(n):
        a = (base + i * pas) % 180.0
        cle = round(a, 3)
        if cle not in vus:
            vus.add(cle)
            angles.append(base + i * pas)
    return angles


def local_polylines(shape: Shape, context: dict | None = None,
                    zone: GroupZone | None = None,
                    brut: bool = False) -> list[G.Polyline]:
    '''Trajectoires d'une forme, rotation appliquée mais **non translatées**.

    Employé par l'affichage, où la position est portée par l'item.

    **Toutes les nappes sont rendues**, pas seulement la première. Une
    recette qui tourne son hachurage de 60° à chaque passe grave trois
    directions ; n'en montrer qu'une donnait un écran qui ne ressemblait
    pas à la pièce, et rendait les process de texture indiscernables les
    unes des autres.

    Les contours ne sont pris qu'une fois : ce sont les mêmes à chaque
    passe, et les superposer n'aurait fait qu'alourdir le tracé.

    `zone` est la part du groupe dans le remplissage — voir
    `group_zones`.

    `brut` laisse une grosse entrée telle qu'elle est rangée : des
    tableaux `array('d')`, x et y alternés, au lieu de couples. Qui la
    parcourt une fois — l'affichage — s'épargne de la déplier : 0,7 s à
    chaque reconstruction d'un texte oscillé de deux millions de points.
    '''
    angles = pass_angles(shape.recipe)
    if len(angles) <= 1:
        return _local_cached(shape, context, 0, zone, brut=brut)

    out = list(_local_cached(shape, context, 0, zone, brut=brut))
    for i in range(1, min(len(angles), NAPPES_MONTREES)):
        # seul le remplissage change d'une passe à l'autre : on retire
        # les contours, identiques, que `_local_cached` remet en tête
        suite = _local_cached(shape, context, i, zone, brut=brut)
        out.extend(suite[_nb_contours(shape, context, zone):])
    return out


def _outline_of(shape: Shape, contours: list[G.Polyline]) -> list[G.Polyline]:
    """Les contours tels qu'ils seront gravés : fragments joints si la
    process le demande — voir `Recipe.link_paths`."""
    if getattr(shape.recipe, 'link_paths', False):
        # les doublons exacts d'abord : une LINE recopiée, avalée par une
        # chaîne, échappait ensuite à `dedupe` et se gravait deux fois
        return G.chain_open(dedupe(contours))
    return list(contours)


def _nb_contours(shape: Shape, context: dict | None,
                 zone: GroupZone | None = None) -> int:
    """Combien de polylignes de `_local_cached` sont des contours.

    Elles viennent toujours en tête, avant le remplissage — voir le corps
    de `_local_cached`. Les compter évite de les redessiner une fois par
    nappe.

    L'épaississement et l'oscillation faussent ce compte : ils
    transforment chaque polyligne en plusieurs. Dans ce cas on renonce et
    l'on garde tout, quitte à superposer les contours — c'est un défaut
    d'affichage, pas de gravure.
    """
    if shape.line_width_mm > 0:
        return 0
    if _oscille(shape.recipe):
        return 0
    return len(_outline_of(shape, shape_contours(
        shape, context, zone.retournes if zone is not None
        else frozenset())))


def shape_polylines(shape: Shape, context: dict | None = None,
                    pass_index: int = 0,
                    zone: GroupZone | None = None) -> list[G.Polyline]:
    """Contours placés d'une forme, hachurage compris.

    `zone` est la part de son groupe dans son remplissage : sans elle, la
    forme est remplie pour elle seule — voir `group_zones`.
    """
    local = _local_cached(shape, context, pass_index, zone, brut=True)
    if not local:
        return []
    dx, dy = shape.x, shape.y
    if type(local) is _Compact:
        # translatée depuis les tableaux, sans les déplier d'abord : un
        # passage au lieu de deux, et les mêmes additions qu'en couples
        sortie = []
        for tableau in local:
            it = iter(tableau)
            sortie.append([(x + dx, y + dy) for x, y in zip(it, it)])
        return sortie
    return [G.translate(p, dx, dy) for p in local]


#: Emprises locales mémorisées, sous la même clé que les trajectoires.
_EXTENTS: dict[tuple, tuple | None] = {}
_EXTENT_ORDER: list[tuple] = []
_EXTENT_MAX = 4096


def shape_extent(shape: Shape, context: dict | None = None):
    """Emprise d'une forme, **sans passer par le hachurage**.

    Le hachurage est contenu dans les contours par construction : inutile
    de le calculer pour connaître l'encombrement.

    L'emprise **locale** est mémorisée, comme les trajectoires : elle ne
    dépend pas de la position. Sans cela, le contrôle de dépassement du
    champ revectorisait tous les textes du document à chaque
    rafraîchissement de la barre d'état — sur trois cents plaques, une
    demi-seconde à chaque clic.
    """
    key = geometry_key(shape, context)
    local = _EXTENTS.get(key, _MISSING) if key is not None else _MISSING
    if local is _MISSING:
        contours = shape_contours(shape, context)
        if contours:
            rotated = [G.rotate(c, shape.rotation_deg) for c in contours]
            local = G.bounds(rotated)
        else:
            local = None
        if key is not None:
            with _VERROU:
                if key not in _EXTENTS:
                    _EXTENTS[key] = local
                    _EXTENT_ORDER.append(key)
                while len(_EXTENT_ORDER) > _EXTENT_MAX:
                    _EXTENTS.pop(_EXTENT_ORDER.pop(0), None)
    if local is None:
        return None
    return (local[0] + shape.x, local[1] + shape.y,
            local[2] + shape.x, local[3] + shape.y)


#: Ordres de parcours mémorisés — voir `_ordonne` —, au plus
#: `_ORDRES_MAX` formes et `_ORDRES_MAX_RANGS` tracés en tout : 32 Mo.
#: Assez pour mille plaques ; au-delà, les plus anciens s'en vont.
_ORDRES: dict[tuple, array] = {}
_ORDRES_MAX = 4096
_ORDRES_MAX_RANGS = 4_000_000
_ORDRES_RANGS = [0]


def _ordonne(shape: Shape, placed: list[G.Polyline], context: dict | None,
             pass_index: int, zone: GroupZone | None,
             start: tuple[float, float],
             time_budget_s: float) -> list[G.Polyline]:
    """`ordering.optimize` sur les trajectoires placées d'une forme,
    **mémorisé**.

    Une série refait les passes de chaque pièce : un logo hachuré, une
    mention fixe étaient réordonnés autant de fois qu'il y a de pièces —
    sur cinquante plaques, la moitié du temps de l'export. L'ordre ne
    dépend plus de l'horloge : une forme qui ne change pas d'une pièce à
    l'autre — même géométrie, même place, même point de départ, même
    budget — reçoit le même. Il est gardé sous forme de rangs, quelques
    octets par tracé, et resservi. Une forme à champ variable a une
    géométrie par pièce, donc une clé par pièce.

    Le plan de travail en profite aussi : une retouche qui laisse la
    géométrie en place — une puissance, une vitesse — ne fait plus
    réordonner tout le document.
    """
    key = geometry_key(shape, context, pass_index)
    if key is None or not placed:
        return ordering.optimize(placed, start=start,
                                 time_budget_s=time_budget_s)
    if zone is not None:
        key = key + zone.signature()
    # de quoi reconnaître les tracés eux-mêmes, en plus de la clé : leur
    # nombre, leurs points, et les extrémités du premier et du dernier
    key = (key, shape.x, shape.y, tuple(start), time_budget_s, len(placed),
           sum(map(len, placed)), tuple(map(tuple, placed[0][:1])),
           tuple(map(tuple, placed[-1][-1:])))
    code = _ORDRES.get(key)
    if code is None:
        code = array('q', [i * 2 + r for i, r in ordering.ordre_optimal(
            placed, start, time_budget_s)])
        _ORDRES[key] = code
        _ORDRES_RANGS[0] += len(code)
        while len(_ORDRES) > 1 and (len(_ORDRES) > _ORDRES_MAX or
                                    _ORDRES_RANGS[0] > _ORDRES_MAX_RANGS):
            _ORDRES_RANGS[0] -= len(_ORDRES.pop(next(iter(_ORDRES))))
    return ordering.applique_ordre(placed,
                                   [(v >> 1, v & 1) for v in code])


def build_shape_pass(shape: Shape, *, optimize: bool = False,
                     time_budget_s: float = 0.3,
                     start: tuple[float, float] = (0.0, 0.0),
                     context: dict | None = None,
                     zone: GroupZone | None = None) -> Pass | None:
    """Passe correspondant à une forme, contour + hachurage éventuel.

    `optimize` réordonne les trajectoires pour réduire les déplacements à
    vide (voir `ordering`). `start` est la position réelle de la tête à
    l'entrée de la passe : l'ignorer conduirait à optimiser chaque passe
    comme si la tête revenait à l'origine, ce qui peut dégrader le trajet
    global au lieu de l'améliorer.
    """
    placed = shape_polylines(shape, context, zone=zone)
    if not placed:
        return None
    if optimize:
        placed = _ordonne(shape, placed, context, 0, zone, start,
                          time_budget_s)

    return Pass(recipe=shape.recipe,
                polylines=placed,
                source_id=shape.id,
                source_name=shape.display_name())


def build_passes(document: Document, *, optimize: bool = False,
                 group_by_recipe: bool = False,
                 time_budget_s: float = 0.3,
                 context: dict | None = None) -> list[Pass]:
    """Toutes les passes du document.

    * `optimize` réordonne les trajectoires pour réduire les déplacements
      à vide.
    * `group_by_recipe` fusionne d'abord les formes partageant la même
      recette. Cela évite les changements d'outil inutiles et permet à
      l'ordonnancement d'agir **entre** les formes et non seulement à
      l'intérieur de chacune. En contrepartie, l'ordre de gravure n'est
      plus celui de création : toutes les formes d'une recette sont
      gravées avant de passer à la suivante.

    Une recette demandant plusieurs passages produit autant de passes.

    `time_budget_s` est un budget **total** partagé entre les passes, pas
    un budget par passe : sans cela le temps de calcul serait proportionnel
    au nombre de formes, ce qui devient vite intenable sur une série.
    """
    # une forme masquée n'est ni affichée ni gravée : elle est écartée
    # une fois pour toutes, avant tout calcul
    shapes = [s for s in document.shapes if s.visible]
    # le remplissage d'un groupe alterne d'un membre à l'autre
    zones = group_zones(shapes, context)

    base: list[Pass] = []
    cursor = (0.0, 0.0)
    shape_count = max(1, sum(1 for s in shapes
                             if not isinstance(s, Text) or s.text.strip()))
    per_pass = time_budget_s / shape_count

    # passe groupée -> ses membres, pour refaire ses passes tournantes
    groupees: dict[int, list[Shape]] = {}
    if group_by_recipe:
        groups: dict[Recipe, Pass] = {}
        order: list[Recipe] = []
        membres: dict[Recipe, list[Shape]] = {}
        for shape in shapes:
            placed = shape_polylines(shape, context,
                                     zone=zones.get(shape.id))
            if not placed:
                continue
            membres.setdefault(shape.recipe, []).append(shape)
            existing = groups.get(shape.recipe)
            if existing is None:
                groups[shape.recipe] = Pass(
                    recipe=shape.recipe, polylines=list(placed),
                    source_id=shape.id, source_name=shape.display_name())
                order.append(shape.recipe)
            else:
                existing.polylines.extend(placed)
                existing.source_id = ''
                existing.source_name = f'{existing.recipe.name} (groupé)'
        for recipe in order:
            p = groups[recipe]
            if optimize:
                p.polylines = ordering.optimize(
                    p.polylines, start=cursor, time_budget_s=per_pass)
            cursor = p.end_point(cursor)
            base.append(p)
            if len(membres[recipe]) > 1:
                groupees[id(p)] = membres[recipe]
    else:
        for shape in shapes:
            p = build_shape_pass(shape, optimize=optimize,
                                 time_budget_s=per_pass, start=cursor,
                                 context=context,
                                 zone=zones.get(shape.id))
            if p is not None:
                cursor = p.end_point(cursor)
                base.append(p)

    # Une recette à plusieurs passages produit autant de passes, chacune
    # gravée un cran plus bas que la précédente : c'est ce que font les
    # fichiers de la machine, où un travail à trois passes descend de
    # Z0 à Z-0.004673 puis Z-0.009347.
    passes: list[Pass] = []
    for p in base:
        tourne = p.recipe.hatch_angle_step_deg and p.recipe.hatch_mm > 0
        for i in range(max(1, p.recipe.passes)):
            # la tête part d'où la passe précédente l'a laissée — elle
            # partait de la fin de la dernière passe de base, à l'autre
            # bout du document
            debut = passes[-1].end_point(cursor) if passes else cursor
            if tourne and i and p.source_id:
                # Le hachurage tourne d'une passe à l'autre : la géométrie
                # n'est plus la même, il faut la reconstruire. Réservé au
                # cas où la recette le demande — sinon on paierait autant
                # de calculs que de passes pour un résultat identique.
                forme = next((s for s in shapes if s.id == p.source_id), None)
                if forme is not None:
                    tracés = shape_polylines(
                        forme, context, i, zone=zones.get(forme.id))
                    if optimize:
                        tracés = _ordonne(forme, tracés, context, i,
                                          zones.get(forme.id), debut,
                                          per_pass)
                    passes.append(replace(p, index=i, polylines=tracés,
                                          z_mm=p.recipe.depth_of(i)))
                    continue
            if tourne and i and id(p) in groupees and _couches(p.recipe) > 1:
                # Groupées par process, plusieurs formes n'ont plus de
                # `source_id` : chaque passe regravait l'angle de la
                # première. Leurs passes se refont membre à membre.
                tracés = [t for forme in groupees[id(p)]
                          for t in shape_polylines(
                              forme, context, i, zone=zones.get(forme.id))]
                if optimize:
                    tracés = ordering.optimize(tracés, start=debut,
                                               time_budget_s=per_pass)
                passes.append(replace(p, index=i, polylines=tracés,
                                      z_mm=p.recipe.depth_of(i)))
                continue
            passes.append(p if i == 0 and p.recipe.depth_step() <= 0
                          else replace(p, index=i,
                                       z_mm=p.recipe.depth_of(i)))
    return passes


def _virgule(valeur: float, decimales: int | None = None) -> str:
    """Un nombre à la française, pour un message."""
    texte = f'{valeur:g}' if decimales is None else f'{valeur:.{decimales}f}'
    return texte.replace('.', ',')


def _millions(points: int) -> str:
    """Des points en millions, arrondis **au-dessus** : un compte à peine
    plus grand que le plafond ne doit pas s'écrire comme lui — « 3,0
    millions, au plus 3 »."""
    return _virgule(math.ceil(points / 1e5) / 10, 1)


def _refus_dense(denses: dict) -> ValueError:
    """L'erreur qui refuse un export dont une oscillation est abandonnée
    — `denses` est un relevé de `dense_wobble`.

    Elle vit ici et non dans `iso` : l'export vectoriel la lève aussi, et
    TauConvert, qui n'écrit pas d'ISO, n'a pas à embarquer l'écrivain des
    fichiers machine pour un message."""
    points, pas, nom = next(iter(denses.values()))
    return ValueError(
        f'oscillation trop dense pour {nom} : {_millions(points)} '
        f'millions de points, au plus {wobble.MAX_POINTS / 1e6:g} — élargir '
        f'le pas d\'oscillation ({_virgule(pas)} mm)')


def formes_trop_denses(document: Document,
                       context: dict | None = None) -> dict:
    """Les formes dont l'oscillation serait abandonnée, pour ces champs
    variables — relevé de `dense_wobble`, sans placer ni ordonner.

    Une série construit ses pièces l'une après l'autre : un numéro qui ne
    devenait trop dense qu'à la vingtième faisait refuser l'export après
    dix-neuf pièces écrites. L'export relève donc chaque pièce **avant**
    d'écrire quoi que ce soit. Ce qui est en cache se relit sans frais ;
    le reste est calculé, et l'export le relira. Seules les formes qui
    oscillent sont relevées : les autres ne peuvent pas être trop denses,
    et un document sans oscillation ne coûte rien.
    """
    shapes = [s for s in document.shapes if s.visible]
    oscillent = [s for s in shapes if _oscille(s.recipe)]
    if not oscillent:
        return {}
    zones = group_zones(shapes, context)
    with dense_wobble() as denses:
        for shape in oscillent:
            for i in range(_couches(shape.recipe)):
                _local_cached(shape, context, i, zones.get(shape.id),
                              brut=True)
    return denses


def total_travel_mm(passes: list[Pass],
                    start: tuple[float, float] = (0.0, 0.0)) -> float:
    """Trajet à vide du travail entier.

    La tête ne revient pas à l'origine entre deux passes : le curseur est
    propagé d'une passe à la suivante.

    Une passe déjà mesurée depuis le même point n'est pas remesurée — voir
    `_PARTAGEES`.
    """
    total = 0.0
    cursor = start
    vus: dict[tuple, float] = {}
    for p in passes:
        cle = (id(p.polylines), cursor[0], cursor[1])
        trajet = vus.get(cle)
        if trajet is None:
            trajet = vus[cle] = p.travel_mm(cursor)
        total += trajet
        cursor = p.end_point(cursor)
    return total


#: **Les passes d'une recette partagent leur liste de tracés.** Vingt
#: passes de profondeur gravent vingt fois les mêmes 42 883 traits : les
#: totaux du travail les mesuraient vingt fois — quatre secondes pour
#: afficher le résumé d'un onglet de rainures. Chaque total ne mesure
#: plus qu'une fois une liste donnée (depuis un point donné pour les
#: sauts), et reprend la mesure pour les passes suivantes.
#:
#: Le résultat est le même **au bit près** : la même valeur, ajoutée dans
#: le même ordre. Le partage ne vaut que le temps d'un appel, pendant
#: lequel aucune liste ne change — les passes le tiennent en vie, son
#: identifiant ne peut pas resservir.
_PARTAGEES = True


def total_length_mm(passes: list[Pass]) -> float:
    vus: dict[int, float] = {}
    longueurs = []
    for p in passes:
        longueur = vus.get(id(p.polylines))
        if longueur is None:
            longueur = vus[id(p.polylines)] = p.length_mm()
        longueurs.append(longueur)
    # `sum` de la suite des longueurs, comme avant : même addition compensée
    return sum(longueurs)


def total_duration_s(passes: list[Pass],
                     start: tuple[float, float] = (0.0, 0.0),
                     memo: dict | None = None) -> float:
    """Durée estimée du travail entier, curseur propagé entre passes.

    `memo` : voir `duration_profile`. Une passe de même liste, de même
    vitesse et partie du même point n'est pas remesurée — voir
    `_PARTAGEES` ; la clé reprend tout ce dont `Pass.duration_s` dépend."""
    total = 0.0
    cursor = start
    vus: dict[tuple, float] = {}
    # La première passe part de l'origine, les suivantes du bout de la
    # précédente : deux départs, mais les mêmes traits, qu'un mémo le
    # temps de l'appel ne mesure qu'une fois. Seulement pour les listes
    # partagées : sur une passe unique, tenir le mémo coûte un cinquième
    # du calcul sans rien épargner.
    partagees: set[int] = set()
    local: dict = {}
    if memo is None:
        vues: set[int] = set()
        for p in passes:
            (partagees if id(p.polylines) in vues else vues).add(
                id(p.polylines))
    for p in passes:
        cle = (id(p.polylines), p.recipe.speed_mm_min, cursor[0], cursor[1])
        duree = vus.get(cle)
        if duree is None:
            garde = (memo if memo is not None
                     else local if id(p.polylines) in partagees else None)
            duree = vus[cle] = p.duration_s(cursor, garde)
        total += duree
        cursor = p.end_point(cursor)
    return total


