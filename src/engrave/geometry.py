"""Géométrie : contours, transformations, hachurage.

Une *polyligne* est une liste de points `(x, y)`. Un *contour* est une
polyligne fermée (le dernier point rejoint le premier implicitement).
"""
from __future__ import annotations

import bisect
import math

Point = tuple[float, float]
Polyline = list[Point]


# --- transformations -------------------------------------------------------

def rotate(points: Polyline, angle_deg: float,
           cx: float = 0.0, cy: float = 0.0) -> Polyline:
    if not angle_deg:
        return list(points)
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    return [((x - cx) * ca - (y - cy) * sa + cx,
             (x - cx) * sa + (y - cy) * ca + cy) for x, y in points]


def translate(points: Polyline, dx: float, dy: float) -> Polyline:
    return [(x + dx, y + dy) for x, y in points]


def scale(points: Polyline, factor: float) -> Polyline:
    return [(x * factor, y * factor) for x, y in points]


def scale_xy(points: Polyline, fx: float, fy: float) -> Polyline:
    """Mise à l'échelle indépendante sur chaque axe."""
    return [(x * fx, y * fy) for x, y in points]


def bounds(polylines: list[Polyline]) -> tuple[float, float, float, float] | None:
    xs = [x for p in polylines for x, _ in p]
    ys = [y for p in polylines for _, y in p]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


# --- primitives ------------------------------------------------------------

def rect_contour(width: float, height: float,
                 cx: float = 0.0, cy: float = 0.0) -> Polyline:
    """Rectangle centré sur (cx, cy), sens trigonométrique, fermé."""
    hw, hh = width / 2, height / 2
    return [(cx - hw, cy - hh), (cx + hw, cy - hh), (cx + hw, cy + hh),
            (cx - hw, cy + hh), (cx - hw, cy - hh)]


def circle_contour(radius: float, cx: float = 0.0, cy: float = 0.0,
                   tolerance: float = 0.02) -> Polyline:
    """Cercle discrétisé, fermé.

    Le nombre de segments découle de la tolérance de corde voulue : un
    petit cercle n'a pas besoin d'autant de points qu'un grand.

    Ce nombre est arrondi à un **multiple de quatre** pour que les quatre
    points cardinaux tombent exactement sur le contour : sans cela, un
    cercle de ⌀20 mesurait 19,988 mm sur un axe et 20 sur l'autre — un
    écart invisible à l'écran mais bien réel sur la pièce.
    """
    if radius <= 0:
        return []
    ratio = max(1e-9, min(1.0, tolerance / radius))
    steps = max(12, min(720, int(math.ceil(math.pi / math.acos(1 - ratio)))))
    steps += (-steps) % 4
    pts = [(cx + radius * math.cos(2 * math.pi * i / steps),
            cy + radius * math.sin(2 * math.pi * i / steps))
           for i in range(steps)]
    pts.append(pts[0])
    return pts


def flatten_cubic(p0: Point, p1: Point, p2: Point, p3: Point,
                  tolerance: float = 0.01) -> Polyline:
    """Discrétise une Bézier cubique, hors point de départ.

    Le nombre de segments est déduit d'une borne grossière de la courbure.
    """
    d = (abs(p0[0] - 2 * p1[0] + p2[0]) + abs(p0[1] - 2 * p1[1] + p2[1])
         + abs(p1[0] - 2 * p2[0] + p3[0]) + abs(p1[1] - 2 * p2[1] + p3[1]))
    if not math.isfinite(d):
        # un point illisible — NaN, infini — dans un fichier abîmé : la
        # courbe se réduit à sa corde, que l'import écarte ensuite (voir
        # `dxfimport.assainir`) ; compter ses segments faisait planter
        return [p3]
    # borné avant d'être arrondi : une courbe démesurée mais finie donnait
    # une racine infinie, que `int` refuse
    n = max(2, int(min(64.0, math.sqrt(d / max(tolerance, 1e-6)) * 2)))
    out: Polyline = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((
            u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
            u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
        ))
    return out


# --- hachurage -------------------------------------------------------------

def hatch(contours: list[Polyline], step: float,
          angle_deg: float = 0.0) -> list[Polyline]:
    """Remplit `contours` de segments parallèles espacés de `step`.

    Règle pair-impair : un point est intérieur si le nombre d'intersections
    à sa gauche est impair — ce qui gère naturellement les contres-formes
    (le trou du « O », l'intérieur du « A »).

    Les segments sont produits en balayage alterné (zigzag) pour limiter
    les déplacements à vide.

    Chaque rangée n'examine que les arêtes de sa tranche (`EdgeSlices`,
    mêmes intersections, même tri, donc les mêmes segments au bit près).
    Balayer toutes les arêtes à chaque rangée coûtait 20 s sur un logo de
    1 907 tracés au dixième ; le remplissage enchaîné, qui rangeait déjà
    ses arêtes ainsi, le faisait en une.
    """
    if step <= 0 or not contours:
        return []

    # on travaille dans un repère où les hachures sont horizontales
    work = [rotate(c, -angle_deg) for c in contours]
    b = bounds(work)
    if b is None:
        return []
    x1, y1, x2, y2 = b
    # borne basse inclusive, borne haute exclusive : un sommet partagé
    # n'est compté qu'une fois — voir `intervals_at`
    tranches = EdgeSlices(work, step)

    segments: list[Polyline] = []
    n = int((y2 - y1) / step) + 1
    for i in range(n + 1):
        y = y1 + i * step
        if y > y2:
            break
        row = [[(xa, y), (xb, y)] for xa, xb in tranches.intervals(y)]
        if i % 2:
            row.reverse()
            row = [list(reversed(seg)) for seg in row]
        segments.extend(row)

    return [rotate(s, angle_deg) for s in segments]


# --- remplissage enchaîné -------------------------------------------------
#
# **Ce qui coûte sur cette machine, c'est d'allumer, pas de graver.**
# Chaque segment de hachure est une polyligne à part : le faisceau saute,
# s'allume, grave quelques centièmes, s'éteint. Et chaque allumage paie
# les rampes du SkyWrite — le miroir accélère avant le trait et freine
# après — dont la durée croît **avec la vitesse** : 1,1 ms par allumage à
# 50 m/min, 4,4 ms à 200. Mesuré à l'atelier sur un DataMatrix hachuré au
# vingtième, 2 666 allumages : 7 s à 50 m/min, 8 s à 100, 15 s à 200.
# Plus on demandait vite, plus c'était long.
#
# Le remède est de graver **d'un seul trait** les rangées successives
# d'une même île : au bout d'une rangée, au lieu de s'éteindre, le
# faisceau longe le bord sur un pas et repart en sens inverse. Le lien
# court sur la frontière de la zone à remplir — il ne grave rien qui ne
# soit déjà dans la zone. Sur le DataMatrix mesuré : 2 623 allumages
# deviennent 499, pour 12 % de longueur gravée en plus.


def intervals_at(contours: list[Polyline], y: float) -> list[tuple[float, float]]:
    """Les intervalles intérieurs d'une horizontale, règle pair-impair."""
    xs: list[float] = []
    for contour in contours:
        pts = contour if contour[0] == contour[-1] else contour + [contour[0]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if ay == by:
                continue
            lo, hi = (ay, by) if ay < by else (by, ay)
            # borne basse inclusive, borne haute exclusive : un sommet
            # partagé n'est compté qu'une fois
            if not (lo <= y < hi):
                continue
            xs.append(ax + (y - ay) * (bx - ax) / (by - ay))
    xs.sort()
    return [(xs[k], xs[k + 1]) for k in range(0, len(xs) - 1, 2)
            if xs[k + 1] - xs[k] > 1e-9]


class EdgeSlices:
    """Les arêtes de contours, rangées par tranche horizontale.

    `intervals(y)` rend exactement ce que rend `intervals_at(contours,
    y)`, mais n'examine que les arêtes de la tranche de `y`. Le
    remplissage enchaîné éprouve ses liens à des hauteurs quelconques —
    celles des sommets voisins — et balayer à chaque fois toutes les
    arêtes d'un texte coûtait des secondes.
    """

    def __init__(self, contours: list[Polyline], height: float) -> None:
        self.height = height if height > 0 else 1.0
        self.slices: dict[int, list[tuple[float, float, float, float]]] = {}
        for contour in contours:
            pts = contour if contour[0] == contour[-1] \
                else contour + [contour[0]]
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                if ay == by:
                    continue
                lo, hi = (ay, by) if ay < by else (by, ay)
                for k in range(math.floor(lo / self.height),
                               math.floor(hi / self.height) + 1):
                    self.slices.setdefault(k, []).append((ax, ay, bx, by))

    def intervals(self, y: float) -> list[tuple[float, float]]:
        xs: list[float] = []
        for ax, ay, bx, by in self.slices.get(math.floor(y / self.height), ()):
            lo, hi = (ay, by) if ay < by else (by, ay)
            if not (lo <= y < hi):
                continue
            xs.append(ax + (y - ay) * (bx - ax) / (by - ay))
        xs.sort()
        return [(xs[k], xs[k + 1]) for k in range(0, len(xs) - 1, 2)
                if xs[k + 1] - xs[k] > 1e-9]


def _dans(intervalles: list[tuple[float, float]], x: float) -> bool:
    import bisect
    debuts = [a for a, _ in intervalles]
    i = bisect.bisect_right(debuts, x) - 1
    return 0 <= i < len(intervalles) and intervalles[i][0] <= x <= intervalles[i][1]


def link_rows(rows: list[tuple[float, list[tuple[float, float]]]], inside,
              max_link: float, spacing: float = 0.0,
              critical=None) -> list[Polyline]:
    """Enchaîne les intervalles de rangées horizontales successives.

    `rows` : `(y, [(a, b), …])` par `y` croissant, intervalles triés.
    `inside(x, y)` : vrai si le point est dans la zone à remplir.
    `max_link` : écart horizontal maximal entre les deux bouts d'un lien.

    Une chaîne se prolonge d'une rangée à la suivante **seulement si le
    passage est sans ambiguïté** : l'intervalle n'en recouvre qu'un seul
    au rang suivant, et celui-ci n'est recouvert que par lui. À une
    fourche — le haut d'un « A », le trou d'un « O » — les chaînes
    s'arrêtent et d'autres commencent. Le lien, enfin, doit rester dans
    la zone : il est éprouvé en trois points, légèrement rentrés vers
    l'intérieur. Un lien qui sortirait graverait hors du dessin.

    Trois points ne voient pas un coin rentrant qui pointe entre eux :
    le lien en rognait l'angle, d'un dixième de pas. `critical(y0, y1,
    xa, xb)`, s'il est donné, rend les hauteurs des sommets du bord
    proches du lien ; il y est éprouvé aussi, juste au-dessus et juste
    au-dessous. Entre deux de ces hauteurs, le bord et le lien sont deux
    droites : si le lien est dedans aux deux bouts, il l'est partout.
    """
    if not rows:
        return []
    if spacing <= 0:
        ecarts = sorted(b[0] - a[0] for a, b in zip(rows, rows[1:])
                        if b[0] - a[0] > 1e-12)
        spacing = ecarts[len(ecarts) // 2] if ecarts else 0.0
    rentre = min(1e-4, spacing * 0.1) if spacing > 0 else 1e-4

    chaines: list[Polyline] = []
    #: chaînes en cours : (points, intervalle de la rangée précédente,
    #: côté où la chaîne s'achève — 'd' à droite, 'g' à gauche)
    ouvertes: list[tuple[Polyline, tuple[float, float], str]] = []
    y_prec = None
    for rang, (y, ivs) in enumerate(rows):
        if y_prec is not None and spacing > 0 and y - y_prec > 1.5 * spacing:
            ouvertes = []                      # trou entre deux rangées
        succ: dict[int, list[int]] = {}
        pred: dict[int, list[int]] = {}
        for oi, (_ch, (a, b), _c) in enumerate(ouvertes):
            for ji, (c, d) in enumerate(ivs):
                if a <= d and c <= b:
                    succ.setdefault(oi, []).append(ji)
                    pred.setdefault(ji, []).append(oi)
        nouvelles = []
        prises: set[int] = set()
        for oi, (ch, (a, b), cote) in enumerate(ouvertes):
            js = succ.get(oi, [])
            if len(js) != 1 or len(pred.get(js[0], [])) != 1:
                continue
            ji = js[0]
            c, d = ivs[ji]
            if cote == 'd':
                x0, x1, arrivee, suite, sens = b, d, (d, c), 'g', -1.0
            else:
                x0, x1, arrivee, suite, sens = a, c, (c, d), 'd', 1.0
            if abs(x1 - x0) > max_link:
                continue
            valide = True
            for t in (0.25, 0.5, 0.75):
                xt = x0 + t * (x1 - x0) + sens * rentre
                yt = y_prec + t * (y - y_prec)
                if not inside(xt, yt):
                    valide = False
                    break
            if valide and critical is not None:
                eps = (y - y_prec) * 1e-4
                for yv in critical(y_prec, y, min(x0, x1), max(x0, x1)):
                    for yt in (yv - eps, yv + eps):
                        if not y_prec < yt < y:
                            continue
                        t = (yt - y_prec) / (y - y_prec)
                        if not inside(x0 + t * (x1 - x0) + sens * rentre, yt):
                            valide = False
                            break
                    if not valide:
                        break
            if not valide:
                continue
            ch.append((arrivee[0], y))
            ch.append((arrivee[1], y))
            nouvelles.append((ch, (c, d), suite))
            prises.add(ji)
        for ji, (c, d) in enumerate(ivs):
            if ji in prises:
                continue
            # le sens alterne d'une rangée à l'autre, comme le hachurage
            # ordinaire : une chaîne d'un seul segment reste bien ordonnée
            if rang % 2:
                ch, cote = [(d, y), (c, y)], 'g'
            else:
                ch, cote = [(c, y), (d, y)], 'd'
            chaines.append(ch)
            nouvelles.append((ch, (c, d), cote))
        ouvertes = nouvelles
        y_prec = y
    return chaines


def hatch_linked(contours: list[Polyline], step: float,
                 angle_deg: float = 0.0) -> list[Polyline]:
    """Comme `hatch`, mais les rangées d'une même île sont gravées d'un
    seul trait — voir l'en-tête de cette section."""
    if step <= 0 or not contours:
        return []
    work = [rotate(c, -angle_deg) for c in contours]
    b = bounds(work)
    if b is None:
        return []
    _x1, y1, _x2, y2 = b
    tranches = EdgeSlices(work, step)
    rows = []
    n = int((y2 - y1) / step) + 1
    for i in range(n + 1):
        y = y1 + i * step
        if y > y2:
            break
        ivs = tranches.intervals(y)
        if ivs:
            rows.append((y, ivs))
    cache: dict[float, list[tuple[float, float]]] = {}

    def inside(x: float, y: float) -> bool:
        cle = round(y, 9)
        ivs = cache.get(cle)
        if ivs is None:
            ivs = cache[cle] = tranches.intervals(y)
        return _dans(ivs, x)

    # les sommets du bord, par hauteur : là où un lien peut rogner un coin
    sommets = sorted((y, x) for c in work for x, y in c)
    hauteurs = [y for y, _x in sommets]

    def critical(y0: float, y1: float, xa: float, xb: float):
        debut = bisect.bisect_right(hauteurs, y0)
        fin = bisect.bisect_left(hauteurs, y1)
        return [y for y, x in sommets[debut:fin]
                if xa - step <= x <= xb + step]

    chaines = link_rows(rows, inside, max_link=6 * step, spacing=step,
                        critical=critical)
    return [rotate(ch, angle_deg) for ch in chaines]


def link_horizontal(segments: list[Polyline], inside,
                    max_link: float, critical=None) -> list[Polyline]:
    """Enchaîne des segments déjà horizontaux, regroupés par rangée.

    Pour les remplissages produits ailleurs que par `hatch` — un code,
    qui se remplit module par module. Le sens des segments est ignoré :
    il est refait par l'enchaînement.
    """
    par_rangee: dict[float, list[tuple[float, float]]] = {}
    for seg in segments:
        if len(seg) != 2 or abs(seg[0][1] - seg[1][1]) > 1e-9:
            return list(segments)       # pas un remplissage horizontal
        a, b = sorted((seg[0][0], seg[1][0]))
        par_rangee.setdefault(round(seg[0][1], 9), []).append((a, b))
    rows = [(y, sorted(ivs)) for y, ivs in sorted(par_rangee.items())]
    return link_rows(rows, inside, max_link, critical=critical)


def chain_open(polylines: list[Polyline], tol: float = 1e-3) -> list[Polyline]:
    """Joint bout à bout les polylignes **ouvertes** qui se touchent.

    Un DXF arrive souvent en fragments — une LINE, un ARC, une LINE — qui
    dessinent ensemble un seul contour. Gravé tel quel, chaque fragment
    est un allumage : un plan de production en compte 1 150, dont 1 069 se
    touchent par leurs bouts. Joints, ils se gravent d'un trait. Le
    tracé est **le même**, point pour point : seules les coupures du
    faisceau disparaissent.

    Les polylignes fermées ne sont pas touchées. L'ordre est tenu : une
    chaîne prend la place du premier fragment qui la compose. À un
    carrefour de trois fragments ou plus, une seule suite est prise, les
    autres commencent une chaîne à elles. `tol` : écart admis entre deux
    bouts, en mm — un micron par défaut.
    """
    def ferme(p: Polyline) -> bool:
        return math.hypot(p[0][0] - p[-1][0], p[0][1] - p[-1][1]) <= tol

    ouvertes = [i for i, p in enumerate(polylines)
                if len(p) > 1 and not ferme(p)]
    if len(ouvertes) < 2:
        return [list(p) for p in polylines]

    def case(pt):
        return (math.floor(pt[0] / tol), math.floor(pt[1] / tol))

    grille: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for i in ouvertes:
        p = polylines[i]
        for bout, pt in ((0, p[0]), (1, p[-1])):
            grille.setdefault(case(pt), []).append((i, bout))

    pris: set[int] = set()

    def voisin(pt):
        cx, cy = case(pt)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i, bout in grille.get((cx + dx, cy + dy), ()):
                    if i in pris:
                        continue
                    q = polylines[i][0] if bout == 0 else polylines[i][-1]
                    if math.hypot(q[0] - pt[0], q[1] - pt[1]) <= tol:
                        return i, bout
        return None

    chaine_de: dict[int, Polyline] = {}
    for i in ouvertes:
        if i in pris:
            continue
        pris.add(i)
        chaine = list(polylines[i])
        while True:                                  # vers l'avant
            trouve = voisin(chaine[-1])
            if trouve is None:
                break
            j, bout = trouve
            pris.add(j)
            suite = polylines[j] if bout == 0 else polylines[j][::-1]
            chaine.extend(suite[1:])
        while True:                                  # vers l'arrière
            trouve = voisin(chaine[0])
            if trouve is None:
                break
            j, bout = trouve
            pris.add(j)
            avant = polylines[j][::-1] if bout == 0 else polylines[j]
            chaine = list(avant[:-1]) + chaine
        chaine_de[i] = chaine

    sortie: list[Polyline] = []
    for i, p in enumerate(polylines):
        if i in chaine_de:
            sortie.append(chaine_de[i])
        elif i not in pris:
            sortie.append(list(p))
    return sortie


def laser_ons(polylines: list[Polyline]) -> int:
    """Nombre d'allumages : une polyligne d'au moins deux points, un."""
    return sum(1 for p in polylines if len(p) > 1)


# --- règle non nulle --------------------------------------------------------
#
# Une police se remplit selon la règle **non nulle** : un point est dans la
# lettre si les contours qui l'entourent ne s'annulent pas, compte tenu de
# leur sens. TauDrive remplit en **pair-impair**. Les deux règles disent la
# même chose tant que les contours ne se croisent pas — c'est le cas de
# presque toutes les polices. Pas des polices **variables**, dont les traits
# se superposent — le « E » de Bahnschrift est un fût et trois bras posés
# dessus —, ni des polices **de script**, dont les lettres se chevauchent
# pour se lier. Sous la règle pair-impair, chaque recouvrement devenait un
# trou, carré blanc au milieu du plein, et son contour se gravait par-dessus.
#
# `nonzero_contours` rend des contours **équivalents en pair-impair** à ce
# que la règle non nulle remplit : le bord seul de la matière, sans les
# traits intérieurs. Tout ce qui suit — hachurage, anneaux, offset, groupes
# — reste en pair-impair et n'en sait rien.


def _coupes(segs: list[tuple[float, float, float, float]],
            tol: float) -> dict[int, list]:
    """Les points où couper chaque segment : croisements, contacts en T,
    recouvrements. Balayage selon x : seuls les segments dont les boîtes
    se recouvrent sont confrontés. `{rang: [(t, point), …]}`."""
    eps = 1e-9
    # les boîtes une fois pour toutes : c'est le balayage qui coûte, et
    # il interroge chacune à chaque pas
    x_min = [s[0] if s[0] < s[2] else s[2] for s in segs]
    x_max = [s[2] if s[0] < s[2] else s[0] for s in segs]
    y_min = [s[1] if s[1] < s[3] else s[3] for s in segs]
    y_max = [s[3] if s[1] < s[3] else s[1] for s in segs]
    ordre = sorted(range(len(segs)), key=x_min.__getitem__)
    actifs: list[int] = []
    coupes: dict[int, list] = {}
    for k in ordre:
        ax, ay, bx, by = segs[k]
        gauche = x_min[k] - tol
        actifs = [j for j in actifs if x_max[j] >= gauche]
        bas, haut = y_min[k] - tol, y_max[k] + tol
        rx, ry = bx - ax, by - ay
        lr = math.hypot(rx, ry)
        for j in actifs:
            if y_max[j] < bas or y_min[j] > haut:
                continue
            cx, cy, dx, dy = segs[j]
            sx, sy = dx - cx, dy - cy
            ls = math.hypot(sx, sy)
            qx, qy = cx - ax, cy - ay
            den = rx * sy - ry * sx
            if abs(den) <= 1e-12 * lr * ls:
                # parallèles : seul un recouvrement colinéaire compte
                if abs(qx * ry - qy * rx) > tol * lr:
                    continue
                for px, py in ((cx, cy), (dx, dy)):
                    t = ((px - ax) * rx + (py - ay) * ry) / (lr * lr)
                    if eps < t < 1 - eps:
                        coupes.setdefault(k, []).append((t, (px, py)))
                for px, py in ((ax, ay), (bx, by)):
                    u = ((px - cx) * sx + (py - cy) * sy) / (ls * ls)
                    if eps < u < 1 - eps:
                        coupes.setdefault(j, []).append((u, (px, py)))
                continue
            t = (qx * sy - qy * sx) / den
            u = (qx * ry - qy * rx) / den
            if t < -eps or t > 1 + eps or u < -eps or u > 1 + eps:
                continue
            dans_t, dans_u = eps < t < 1 - eps, eps < u < 1 - eps
            if not (dans_t or dans_u):
                continue                    # un sommet partagé
            # le point est calculé une fois, et le même pour les deux
            # segments : c'est ce qui permet de les rechaîner ensuite
            if not dans_t:
                p = (ax, ay) if t <= eps else (bx, by)
            elif not dans_u:
                p = (cx, cy) if u <= eps else (dx, dy)
            else:
                p = (ax + t * rx, ay + t * ry)
            if dans_t:
                coupes.setdefault(k, []).append((t, p))
            if dans_u:
                coupes.setdefault(j, []).append((u, p))
        actifs.append(k)
    return coupes


class _Tranches:
    """Nombre d'enroulement d'un point (Dan Sunday) autour d'une boucle,
    ses arêtes rangées par tranche horizontale pour n'examiner que celles
    de sa hauteur."""

    __slots__ = ('y0', 'h', 'tranches')

    def __init__(self, segs: list[tuple[float, float, float, float]]) -> None:
        ys = [y for s in segs for y in (s[1], s[3])]
        self.y0 = min(ys)
        self.h = max((max(ys) - self.y0) / max(1, int(math.sqrt(len(segs)))),
                     1e-12)
        self.tranches: dict[int, list] = {}
        for s in segs:
            if s[1] == s[3]:
                continue
            lo, hi = (s[1], s[3]) if s[1] < s[3] else (s[3], s[1])
            for k in range(int((lo - self.y0) / self.h),
                           int((hi - self.y0) / self.h) + 1):
                self.tranches.setdefault(k, []).append(s)

    def __call__(self, px: float, py: float) -> int:
        w = 0
        for ax, ay, bx, by in self.tranches.get(
                int((py - self.y0) / self.h), ()):
            gauche = (bx - ax) * (py - ay) - (px - ax) * (by - ay)
            if ay <= py < by:
                if gauche > 0:
                    w += 1
            elif by <= py < ay:
                if gauche < 0:
                    w -= 1
        return w


class _Enroulement:
    """Nombre d'enroulement d'un point, boucle par boucle.

    Une boucle fermée ne compte que pour les points de son emprise : hors
    d'elle, son enroulement est nul. Une grille sur les emprises ne fait
    donc interroger que les boucles qui contiennent le point. Rangées en
    une seule fois par tranche, les arêtes d'une ligne de script — vingt
    lettres liées en une seule matière — étaient toutes examinées à la
    hauteur du point, d'un bout à l'autre de la ligne : 0,7 s pour un mot
    en Segoe Script.
    """

    def __init__(self, segs: list[tuple[float, float, float, float]]) -> None:
        # `_aretes` rend chaque anneau d'un seul tenant : une boucle se
        # referme quand une arête revient à son premier point. Un anneau
        # qui repasse par son départ en fait deux, fermées chacune
        boucles, courante = [], []
        for s in segs:
            courante.append(s)
            if s[2] == courante[0][0] and s[3] == courante[0][1]:
                boucles.append(courante)
                courante = []
        if courante:
            boucles.append(courante)
        self.boucles = []
        for b in boucles:
            xs = [v for s in b for v in (s[0], s[2])]
            ys = [v for s in b for v in (s[1], s[3])]
            self.boucles.append((min(xs), min(ys), max(xs), max(ys),
                                 _Tranches(b)))
        self.x0 = min(b[0] for b in self.boucles)
        self.y0 = min(b[1] for b in self.boucles)
        self.cote = max(1, int(math.sqrt(len(self.boucles))))
        self.lx = max((max(b[2] for b in self.boucles) - self.x0) / self.cote,
                      1e-12)
        self.ly = max((max(b[3] for b in self.boucles) - self.y0) / self.cote,
                      1e-12)
        self.cases: dict[tuple[int, int], list] = {}
        for b in self.boucles:
            for i in range(self._i(b[0]), self._i(b[2]) + 1):
                for j in range(self._j(b[1]), self._j(b[3]) + 1):
                    self.cases.setdefault((i, j), []).append(b)

    def _i(self, x: float) -> int:
        return min(self.cote - 1, max(0, int((x - self.x0) / self.lx)))

    def _j(self, y: float) -> int:
        return min(self.cote - 1, max(0, int((y - self.y0) / self.ly)))

    def __call__(self, px: float, py: float) -> int:
        w = 0
        for x1, y1, x2, y2, tranches in self.cases.get(
                (self._i(px), self._j(py)), ()):
            if x1 <= px <= x2 and y1 <= py <= y2:
                w += tranches(px, py)
        return w


def _anneaux(contours: list[Polyline]) -> list[list[Point]]:
    """Les contours, ouverts — sans le point de fermeture — et sans point
    répété ; un contour de moins de trois points est écarté."""
    anneaux = []
    for c in contours:
        pts = [(float(x), float(y)) for x, y in c]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        pts = [p for i, p in enumerate(pts) if p != pts[i - 1]]
        if len(pts) >= 3:
            anneaux.append(pts)
    return anneaux


def _sommets_partages(anneaux: list[list[Point]]) -> bool:
    """Vrai si deux anneaux ont un sommet en commun.

    Le balayage des croisements ne voit pas ceux qui tombent sur un
    sommet des deux côtés : deux anneaux identiques, ou qui ne se
    croisent qu'en des sommets communs, revenaient tels quels — et la
    règle pair-impair faisait un trou de ce que la règle non nulle
    remplit."""
    vus: dict[Point, int] = {}
    for rang, anneau in enumerate(anneaux):
        for pt in anneau:
            if vus.setdefault(pt, rang) != rang:
                return True
    return False


def _aretes(anneaux: list[list[Point]]) -> list[tuple]:
    return [(a[i][0], a[i][1], a[(i + 1) % len(a)][0], a[(i + 1) % len(a)][1])
            for a in anneaux for i in range(len(a))]


def _grappes(points: list[Point], pas: float) -> dict[Point, Point]:
    """Chaque point vers le représentant de sa grappe : deux points à
    moins de `pas` l'un de l'autre, en x comme en y, en partagent un.

    Un arrondi sur une grille fixe séparait deux points voisins tombés de
    part et d'autre d'une ligne de la grille : un croisement calculé à
    quelques cent-millièmes d'un sommet, et la chaîne ne se refermait
    plus. Le représentant est le premier point de la grappe selon x."""
    uniques = sorted(set(points))
    parent = list(range(len(uniques)))

    def racine(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, (xa, ya) in enumerate(uniques):
        for b in range(a + 1, len(uniques)):
            xb, yb = uniques[b]
            if xb - xa > pas:
                break
            if abs(yb - ya) <= pas:
                ra, rb = racine(a), racine(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    return {pt: uniques[racine(i)] for i, pt in enumerate(uniques)}


def contours_touch(a: list[Polyline], b: list[Polyline]) -> bool:
    """Vrai si un contour de `a` croise un contour de `b`, ou le touche
    ailleurs qu'en un sommet commun. Seules les arêtes de la zone où les
    deux emprises se recouvrent sont confrontées."""
    ba, bb = bounds(a), bounds(b)
    if ba is None or bb is None:
        return False
    x0, y0 = max(ba[0], bb[0]), max(ba[1], bb[1])
    x1, y1 = min(ba[2], bb[2]), min(ba[3], bb[3])
    if x0 > x1 or y0 > y1:
        return False

    def dedans(s) -> bool:
        return not (max(s[0], s[2]) < x0 or min(s[0], s[2]) > x1
                    or max(s[1], s[3]) < y0 or min(s[1], s[3]) > y1)

    sa = [s for s in _aretes(_anneaux(a)) if dedans(s)]
    sb = [s for s in _aretes(_anneaux(b)) if dedans(s)]
    if not sa or not sb:
        return False
    echelle = max(1.0, max(max(abs(s[0]), abs(s[1])) for s in sa + sb))
    return bool(_coupes(sa + sb, 1e-9 * echelle))


def nonzero_contours(contours: list[Polyline]) -> list[Polyline]:
    """Contours équivalents en pair-impair au remplissage **non nul** de
    `contours` — voir l'en-tête de cette section.

    Des contours qui ne se croisent pas reviennent **tels quels**, le
    même objet : la règle pair-impair les remplit déjà comme
    la règle non nulle, à condition qu'un trou tourne à l'envers de ce
    qui l'entoure — ce que garantit une police. Sinon, chaque segment est
    coupé à ses croisements, chaque morceau gardé s'il sépare la matière
    du vide, et les morceaux gardés sont rechaînés en contours fermés, la
    matière **à droite** comme dans une police TrueType. Une chaîne qui
    ne se referme pas — un calcul pris en défaut — rend les contours
    d'origine : jamais pire qu'avant.
    """
    anneaux = _anneaux(contours)
    if not anneaux:
        return contours
    segs = _aretes(anneaux)
    echelle = max(1.0, max(max(abs(s[0]), abs(s[1])) for s in segs))
    tol = 1e-9 * echelle
    coupes = _coupes(segs, tol)
    if not coupes and not _sommets_partages(anneaux):
        return contours

    morceaux = []
    for k, (ax, ay, bx, by) in enumerate(segs):
        jalons = ([(0.0, (ax, ay))] + sorted(coupes.get(k, ()))
                  + [(1.0, (bx, by))])
        for (_t0, p0), (_t1, p1) in zip(jalons, jalons[1:]):
            if p0 != p1:
                morceaux.append((p0, p1))

    enroulement = _Enroulement(segs)
    # de part et d'autre d'un morceau, au plus près : une lame de matière
    # de quelques millièmes d'unité — deux bords presque confondus, que
    # dessinent certaines polices — échappait à un écart plus grand, et sa
    # chaîne ne se refermait plus. Dix fois la tolérance des coupes, bien
    # au-dessus du bruit des calculs.
    delta = 1e-8 * echelle
    pas = 1e-7 * echelle

    gardes = []
    for p0, p1 in morceaux:
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        n = math.hypot(dx, dy)
        if n <= tol:
            continue
        mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
        nx, ny = -dy / n * delta, dx / n * delta
        plein_g = enroulement(mx + nx, my + ny) != 0
        plein_d = enroulement(mx - nx, my - ny) != 0
        if plein_g == plein_d:
            continue                        # trait intérieur, ou dans le vide
        gardes.append((p0, p1) if plein_d else (p1, p0))

    # les extrémités voisines ne font qu'un point, le même pour tous
    rep = _grappes([p for bord in gardes for p in bord], pas)
    bords, vus = [], set()
    for p0, p1 in gardes:
        bord = (rep[p0], rep[p1])
        if bord[0] != bord[1] and bord not in vus:
            vus.add(bord)
            bords.append(bord)

    depart: dict[Point, list[int]] = {}
    for i, (p0, _p1) in enumerate(bords):
        depart.setdefault(p0, []).append(i)
    pris = [False] * len(bords)
    sortie: list[Polyline] = []
    for i0 in range(len(bords)):
        if pris[i0]:
            continue
        origine = bords[i0][0]
        anneau = [origine]
        i = i0
        while True:
            pris[i] = True
            anneau.append(bords[i][1])
            if bords[i][1] == origine:
                break
            suivants = [j for j in depart.get(bords[i][1], ()) if not pris[j]]
            if not suivants:
                return contours             # chaîne rompue : l'original
            i = suivants[0]
        if len(anneau) >= 4:
            sortie.append(anneau)
    return sortie
