"""Ordonnancement des trajectoires / Toolpath ordering.

Le temps d'un travail se répartit entre la gravure elle-même, qui est
incompressible, et les **déplacements à vide** entre polylignes, qui ne le
sont pas. Sur un texte hachuré, ces déplacements dominent largement.

Deux leviers, appliqués dans cet ordre :

1. **Plus proche voisin** — on part de l'origine et on enchaîne à chaque
   fois la polyligne dont une extrémité est la plus proche du point
   courant, quitte à la parcourir à l'envers.
2. **2-opt borné** — on tente d'inverser des sous-séquences tant que cela
   raccourcit le parcours, dans une limite d'évaluations fixée — et non
   de temps : le même document sort toujours dans le même ordre.

Les polylignes fermées sont laissées intactes : rien n'oblige à démarrer un
contour à un sommet donné, mais changer ce point de départ déplace la
marque d'amorçage, ce qui est visible sur la pièce.
"""
from __future__ import annotations

import math
import operator

from .geometry import Polyline

Point = tuple[float, float]

#: Évaluations de 2-opt accordées par seconde de budget.
#:
#: Le 2-opt s'arrêtait à une **échéance d'horloge** : selon la charge du
#: poste, l'affinage allait plus ou moins loin, et le même document,
#: exporté deux fois, ne sortait pas toujours dans le même ordre. Le
#: parcours rejoué, la vérification et l'export, calculés chacun de leur
#: côté, pouvaient différer de quelques permutations. Le budget se compte
#: désormais en évaluations : même document, même ordre, même fichier,
#: sur tout poste et à toute charge. Six cent mille par seconde, c'est ce
#: que faisait l'ancien calcul sur le poste de développement ; le nouveau,
#: plus rapide, y tient en six dixièmes de seconde.
EVALUATIONS_PAR_S = 600_000

#: Portées successives du 2-opt, en positions : d'abord des inversions
#: courtes, sur tout le parcours, puis sans limite avec ce qui reste du
#: budget. Sans fenêtre, un passage complet coûte n² évaluations : sur un
#: texte hachuré de 1 830 rangées, le budget s'épuisait dans les premières
#: centaines de positions, et le reste du parcours n'était jamais revu.
FENETRES = (32, None)

#: Au-delà de ce nombre d'extrémités, une case de la grille du plus proche
#: voisin passe dans un arbre — voir `_Arbre`. Une répartition régulière
#: n'en met qu'une ou deux par case : le cas courant n'en voit jamais.
CASE_LOURDE = 64

#: Points distincts au plus par feuille de `_Arbre`.
FEUILLE = 32

#: Rabais sur la distance d'un curseur à une boîte de `_Arbre`, avant de
#: l'écarter. `math.hypot` peut se tromper d'une unité sur le dernier
#: chiffre, soit 2⁻⁵² en relatif : sans marge, un point situé pile à la
#: distance du meilleur candidat pourrait être écarté, et l'égalité
#: tranchée autrement que par le balayage de la case. 2⁻⁴⁰ couvre l'écart
#: de loin, et ne fait examiner que quelques boîtes de plus.
_RABAIS = 1.0 - 2.0 ** -40


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def is_closed(poly: Polyline, tol: float = 1e-9) -> bool:
    return len(poly) > 2 and _dist(poly[0], poly[-1]) <= tol


def travel_distance(polylines: list[Polyline],
                    start: Point = (0.0, 0.0)) -> float:
    """Distance parcourue à vide, laser éteint.

    Un point isolé ne compte pas : l'export ne le grave pas, la tête n'y
    va donc pas — comme pour `nearest_neighbour` et le modèle de durée.
    Compté, il ajoutait un aller et retour qui n'existe pas."""
    total = 0.0
    cursor = start
    for poly in polylines:
        if len(poly) < 2:
            continue
        total += _dist(cursor, poly[0])
        cursor = poly[-1]
    return total


def nearest_neighbour(polylines: list[Polyline],
                      start: Point = (0.0, 0.0)) -> list[Polyline]:
    """Enchaînement au plus proche voisin, avec inversion autorisée.

    Les extrémités candidates sont rangées dans une **grille régulière** et
    la recherche progresse par anneaux autour du curseur. Le balayage naïf
    est quadratique : sur un texte hachuré finement, où l'on compte des
    milliers de segments, il coûtait à lui seul plusieurs centaines de
    millisecondes à chaque rafraîchissement.

    Chaque anneau ne parcourt que **son pourtour**, dans l'ordre où le
    balayage du carré entier le rencontrait — les égalités de distance se
    tranchent donc de la même façon, et l'ordre rendu est le même. Et une
    extrémité consommée **quitte sa case** : en fin de parcours, quand il
    ne reste que quelques polylignes éparses, chaque recherche refaisait
    le tour du carré entier et de tout ce qui avait déjà servi — 18 s sur
    trois cents plaques, autant sur un hibou séparé.

    Une case **trop chargée** reçoit son propre arbre — voir `_Arbre`. La
    maille suit l'emprise : qu'une seule entité égarée au loin la fixe, et
    tout le reste tombe dans une poignée de cases, que chaque recherche
    parcourait en entier. Vingt mille traits dans 20 mm se triaient en
    0,4 s ; avec un trait de plus posé à 5 m, en 104 s — en une seconde
    avec l'arbre.
    """
    items = [p for p in polylines if len(p) >= 2]
    return [list(reversed(items[i])) if r else items[i]
            for i, r in _plus_proche_voisin(items, start)]


def _plus_proche_voisin(items: list[Polyline],
                        start: Point) -> list[tuple[int, bool]]:
    """Le cœur de `nearest_neighbour`, sur des polylignes d'au moins deux
    points : l'ordre de parcours, en (rang, parcourue à l'envers)."""
    if not items:
        return []
    if len(items) == 1:
        return [(0, False)]

    # points d'entrée : la tête, plus la queue si la polyligne est ouverte
    entries: list[tuple[float, float, int, bool]] = []
    for i, poly in enumerate(items):
        entries.append((poly[0][0], poly[0][1], i, False))
        if not is_closed(poly):
            entries.append((poly[-1][0], poly[-1][1], i, True))

    xs = [e[0] for e in entries]
    ys = [e[1] for e in entries]
    min_x, min_y = min(xs), min(ys)
    span = max(max(xs) - min_x, max(ys) - min_y)

    # Maille dimensionnée sur le **côté** de l'emprise, pas sur son aire :
    # une géométrie plate — points alignés, ou tous confondus — annule
    # l'aire et produirait une maille microscopique, donc une grille de
    # dizaines de milliers de rangées à parcourir.
    if span <= 1e-12:
        cell = 1.0
    else:
        cell = span / max(1, int(math.sqrt(len(entries))))

    grid: dict[tuple[int, int], list[int]] = {}
    cases: list[tuple[int, int]] = []        # la case de chaque entrée
    for k, (x, y, _i, _rev) in enumerate(entries):
        key = (int((x - min_x) / cell), int((y - min_y) / cell))
        grid.setdefault(key, []).append(k)
        cases.append(key)
    # les entrées de chaque polyligne, pour les retirer d'un coup
    par_poly: list[list[int]] = [[] for _ in items]
    for k, (_x, _y, i, _rev) in enumerate(entries):
        par_poly[i].append(k)

    # Borne d'arrêt : au-delà, l'anneau déborde de toute façon la grille.
    # Sans elle, un anneau qui ne contient que des extrémités déjà
    # consommées fait croître le rayon indéfiniment — la recherche ne
    # s'arrête jamais.
    cols = max(gx for gx, _ in grid) - min(gx for gx, _ in grid) + 1
    rows = max(gy for _, gy in grid) - min(gy for _, gy in grid) + 1
    max_ring = max(cols, rows) + 2

    # Les cases trop chargées passent dans un arbre chacune. La grille, ses
    # anneaux et leur ordre ne changent pas : l'arbre rend seulement, pour
    # sa case, ce qu'aurait trouvé le balayage de sa liste. Le gagnant et
    # les égalités restent donc ceux d'avant, et l'ISO le même à l'octet.
    lourdes: dict[tuple[int, int], _Arbre] = {}
    for key in [c for c, ks in grid.items() if len(ks) > CASE_LOURDE]:
        lourdes[key] = _Arbre(entries, grid.pop(key))

    used = [False] * len(items)
    ordered: list[tuple[int, bool]] = []
    cursor = start

    for _ in range(len(items)):
        cx = int((cursor[0] - min_x) / cell)
        cy = int((cursor[1] - min_y) / cell)
        best_k = -1
        best_d = math.inf

        for ring in range(max_ring + 1):
            # un anneau ne peut plus rien apporter dès qu'il est plus loin
            # que le meilleur candidat déjà trouvé
            if best_k >= 0 and (ring - 1) * cell > best_d:
                break
            for gx in range(cx - ring, cx + ring + 1):
                # le pourtour seul : colonnes de bord entières, ailleurs
                # la case du bas et celle du haut — dans l'ordre du carré
                if ring and cx - ring < gx < cx + ring:
                    colonne = (cy - ring, cy + ring)
                else:
                    colonne = range(cy - ring, cy + ring + 1)
                for gy in colonne:
                    case = grid.get((gx, gy))
                    if case is not None:
                        for k in case:
                            x, y, i, _rev = entries[k]
                            d = math.hypot(cursor[0] - x, cursor[1] - y)
                            if d < best_d:
                                best_d, best_k = d, k
                    elif lourdes:
                        arbre = lourdes.get((gx, gy))
                        if arbre is not None:
                            d, k = arbre.plus_proche(cursor[0], cursor[1],
                                                     best_d)
                            if k >= 0:
                                best_d, best_k = d, k

        if best_k < 0:
            # le curseur est très loin de la grille : on prend le premier
            # élément restant plutôt que d'élargir davantage
            for i, poly in enumerate(items):
                if not used[i]:
                    used[i] = True
                    _retirer(grid, lourdes, cases, par_poly[i])
                    ordered.append((i, False))
                    cursor = poly[-1]
                    break
            continue

        _x, _y, index, reverse = entries[best_k]
        used[index] = True
        _retirer(grid, lourdes, cases, par_poly[index])
        ordered.append((index, reverse))
        cursor = items[index][0] if reverse else items[index][-1]

    return ordered


def _retirer(grid: dict, lourdes: dict, cases: list,
             entrees: list[int]) -> None:
    """Retire de la grille les entrées d'une polyligne consommée."""
    for k in entrees:
        case = grid.get(cases[k])
        if case is not None:
            case.remove(k)
            if not case:
                del grid[cases[k]]
        else:
            arbre = lourdes.get(cases[k])
            if arbre is not None and arbre.retirer(k):
                del lourdes[cases[k]]


class _Arbre:
    """Arbre 2-d des extrémités d'une case trop chargée de la grille.

    Il rend, pour un curseur, exactement ce que rendait le balayage de la
    liste de la case : l'extrémité restante la plus proche et, à distance
    égale, la première de la liste — le plus petit rang. Les distances
    sont calculées par la même expression ; une boîte n'est écartée que si
    tous ses points sont **strictement** plus loin que le meilleur
    candidat, une égalité est donc toujours examinée.

    Les extrémités confondues ne font qu'un point, qui garde ses rangs
    dans l'ordre : des rayons partant tous du même centre se seraient
    départagés un à un, à chaque recherche.
    """
    __slots__ = ('rangs', 'tete', 'vivants', 'morts', 'point_de',
                 'feuille_de', 'boite', 'droite', 'parent', 'compte',
                 'contenu')

    def __init__(self, entries: list, ks: list[int]) -> None:
        # les points distincts, chacun avec ses rangs dans l'ordre de la case
        points: dict[tuple, list[int]] = {}
        for k in ks:
            e = entries[k]
            points.setdefault((e[0], e[1]), []).append(k)
        self.rangs = list(points.values())
        self.tete = [0] * len(self.rangs)
        self.vivants = [len(r) for r in self.rangs]
        self.morts: set[int] = set()
        self.point_de = {k: s for s, r in enumerate(self.rangs) for k in r}
        self.feuille_de = [0] * len(self.rangs)

        # Chaque nœud coupe ses points en deux moitiés, le long du plus long
        # côté de sa boîte : la profondeur ne dépend que du nombre de
        # points, pas de leur répartition — celle-là même qui a mis la case
        # en défaut. Numérotation en profondeur : le fils gauche d'un nœud
        # le suit immédiatement, seul le droit est noté.
        X, Y = operator.itemgetter(0), operator.itemgetter(1)
        tous = [(x, y, s) for s, (x, y) in enumerate(points)]
        self.boite: list[tuple] = []          # (x0, x1, y0, y1)
        self.droite: list[int] = []           # -1 pour une feuille
        self.parent: list[int] = []
        self.compte: list[int] = []           # points encore vivants
        self.contenu: list = []               # points d'une feuille
        pile = [(tous, (min(map(X, tous)), max(map(X, tous)),
                        min(map(Y, tous)), max(map(Y, tous))), -1)]
        while pile:
            pts, boite, pere = pile.pop()
            nd = len(self.boite)
            self.boite.append(boite)
            self.droite.append(-1)
            self.parent.append(pere)
            self.compte.append(len(pts))
            if pere >= 0 and nd != pere + 1:
                self.droite[pere] = nd
            if len(pts) <= FEUILLE:
                self.contenu.append(pts)
                for p in pts:
                    self.feuille_de[p[2]] = nd
                continue
            self.contenu.append(None)
            x0, x1, y0, y1 = boite
            h = len(pts) // 2
            if x1 - x0 >= y1 - y0:
                pts.sort(key=X)
                g, d = pts[:h], pts[h:]
                bg = (g[0][0], g[-1][0], min(map(Y, g)), max(map(Y, g)))
                bd = (d[0][0], d[-1][0], min(map(Y, d)), max(map(Y, d)))
            else:
                pts.sort(key=Y)
                g, d = pts[:h], pts[h:]
                bg = (min(map(X, g)), max(map(X, g)), g[0][1], g[-1][1])
                bd = (min(map(X, d)), max(map(X, d)), d[0][1], d[-1][1])
            pile.append((d, bd, nd))
            pile.append((g, bg, nd))

    def retirer(self, k: int) -> bool:
        """Retire une extrémité consommée ; vrai si l'arbre est vide."""
        s = self.point_de[k]
        self.vivants[s] -= 1
        if self.vivants[s]:
            # le point reste : sa tête passe au premier rang encore vivant
            self.morts.add(k)
            rangs, t = self.rangs[s], self.tete[s]
            while rangs[t] in self.morts:
                t += 1
            self.tete[s] = t
            return False
        # le point s'éteint : il quitte sa feuille, et ses boîtes le
        # décomptent jusqu'à la racine
        nd = self.feuille_de[s]
        pts = self.contenu[nd]
        for j, p in enumerate(pts):
            if p[2] == s:
                del pts[j]
                break
        while nd >= 0:
            self.compte[nd] -= 1
            nd = self.parent[nd]
        return not self.compte[0]

    def plus_proche(self, cx: float, cy: float,
                    best_d: float) -> tuple[float, int]:
        """L'extrémité restante la plus proche de (cx, cy), en (distance,
        rang), si elle est **strictement** plus proche que `best_d` — ce
        qu'a trouvé la grille avant cette case ; sinon `(best_d, -1)`."""
        best_k = -1
        if not self.compte[0]:
            return best_d, best_k
        hypot, rabais = math.hypot, _RABAIS
        rangs, tete = self.rangs, self.tete
        boite, droite, compte, contenu = (self.boite, self.droite,
                                          self.compte, self.contenu)
        pile = [(0.0, 0)]
        while pile:
            borne, nd = pile.pop()
            if borne > best_d:
                continue
            pts = contenu[nd]
            if pts is not None:
                for x, y, s in pts:
                    d = hypot(cx - x, cy - y)
                    if d <= best_d:
                        k = rangs[s][tete[s]]
                        if d < best_d or k < best_k:
                            best_d, best_k = d, k
                continue
            # Distance du curseur à la boîte de chaque fils, minorée de
            # `_RABAIS` ; le plus proche est empilé en dernier, il sort le
            # premier.
            g, dr = nd + 1, droite[nd]
            bg = bd = None
            if compte[g]:
                x0, x1, y0, y1 = boite[g]
                bg = hypot(x0 - cx if cx < x0 else
                           (cx - x1 if cx > x1 else 0.0),
                           y0 - cy if cy < y0 else
                           (cy - y1 if cy > y1 else 0.0)) * rabais
                if bg > best_d:
                    bg = None
            if compte[dr]:
                x0, x1, y0, y1 = boite[dr]
                bd = hypot(x0 - cx if cx < x0 else
                           (cx - x1 if cx > x1 else 0.0),
                           y0 - cy if cy < y0 else
                           (cy - y1 if cy > y1 else 0.0)) * rabais
                if bd > best_d:
                    bd = None
            if bg is None:
                if bd is not None:
                    pile.append((bd, dr))
            elif bd is None:
                pile.append((bg, g))
            elif bg <= bd:
                pile.append((bd, dr))
                pile.append((bg, g))
            else:
                pile.append((bg, g))
                pile.append((bd, dr))
        return best_d, best_k


def two_opt(polylines: list[Polyline], start: Point = (0.0, 0.0),
            time_budget_s: float = 0.5) -> list[Polyline]:
    """Amélioration 2-opt, bornée en évaluations — voir `EVALUATIONS_PAR_S`.

    Inverse une sous-séquence quand cela raccourcit le parcours à vide.
    L'inversion retourne aussi le sens de parcours de chaque polyligne.

    Le sens est tenu **à part**, polyligne par polyligne, et les points ne
    sont retournés qu'à la fin : inverser une sous-séquence recopiait
    chaque point de chacune, des milliers par rangée sur un tracé oscillé.
    Après une inversion, la recherche reprend où elle en était au lieu de
    repartir du début — ce qui rendait le tout cubique.
    """
    if len(polylines) < 4:
        return list(polylines)
    ordre, retournee = _deux_opt([p[0] for p in polylines],
                                 [p[-1] for p in polylines],
                                 start, time_budget_s)
    return [list(reversed(polylines[k])) if r else polylines[k]
            for k, r in zip(ordre, retournee)]


def _deux_opt(debuts: list[Point], fins: list[Point], start: Point,
              time_budget_s: float) -> tuple[list[int], list[bool]]:
    """Le cœur de `two_opt`, sur les seules extrémités : la nouvelle
    position de chaque polyligne et son sens. `debuts` et `fins` sont
    modifiés en place."""
    n = len(debuts)
    budget = max(0, int(time_budget_s * EVALUATIONS_PAR_S))
    ordre = list(range(n))
    retournee = [False] * n
    hypot = math.hypot
    faites = 0
    for fenetre in FENETRES:
        ameliore = True
        while ameliore and faites < budget:
            ameliore = False
            for i in range(n - 1):
                if faites >= budget:
                    break
                ax, ay = fins[i - 1] if i > 0 else start
                bx, by = debuts[i]
                bout = n if fenetre is None else min(n, i + 1 + fenetre)
                j = i + 1
                while j < bout and faites < budget:
                    faites += 1
                    cx, cy = fins[j]
                    avant = hypot(ax - bx, ay - by)
                    apres = hypot(ax - cx, ay - cy)
                    if j + 1 < n:
                        dx, dy = debuts[j + 1]
                        avant += hypot(cx - dx, cy - dy)
                        apres += hypot(bx - dx, by - dy)
                    if apres < avant - 1e-12:
                        ordre[i:j + 1] = ordre[i:j + 1][::-1]
                        retournee[i:j + 1] = [not r for r in
                                              retournee[i:j + 1][::-1]]
                        tetes, queues = debuts[i:j + 1], fins[i:j + 1]
                        debuts[i:j + 1] = queues[::-1]
                        fins[i:j + 1] = tetes[::-1]
                        bx, by = debuts[i]
                        ameliore = True
                    j += 1
    return ordre, retournee


def optimize(polylines: list[Polyline], start: Point = (0.0, 0.0),
             time_budget_s: float = 0.5) -> list[Polyline]:
    """Ordonnancement complet : plus proche voisin puis 2-opt."""
    return applique_ordre(polylines,
                          ordre_optimal(polylines, start, time_budget_s))


def ordre_optimal(polylines: list[Polyline], start: Point = (0.0, 0.0),
                  time_budget_s: float = 0.5) -> list[tuple[int, bool]]:
    """L'ordre que rend `optimize`, **sans le matérialiser** : pour chaque
    position, le rang de la polyligne dans `polylines`, et si elle est
    parcourue à l'envers.

    Il tient en quelques octets par tracé, se garde donc à peu de frais
    et se rejoue avec `applique_ordre` — voir `toolpath._ordonne`.
    """
    if len(polylines) < 2:
        return [(i, False) for i in range(len(polylines))]
    rangs = [i for i, p in enumerate(polylines) if len(p) >= 2]
    items = [polylines[i] for i in rangs]
    ppv = _plus_proche_voisin(items, start)
    if len(ppv) < 4:
        return [(rangs[i], r) for i, r in ppv]
    debuts = [items[i][-1] if r else items[i][0] for i, r in ppv]
    fins = [items[i][0] if r else items[i][-1] for i, r in ppv]
    ordre, retournee = _deux_opt(debuts, fins, start, time_budget_s)
    return [(rangs[ppv[k][0]], ppv[k][1] != r)
            for k, r in zip(ordre, retournee)]


def applique_ordre(polylines: list[Polyline],
                   ordre: list[tuple[int, bool]]) -> list[Polyline]:
    """Les polylignes dans l'ordre donné par `ordre_optimal`."""
    return [list(reversed(polylines[i])) if r else polylines[i]
            for i, r in ordre]


def report(before: list[Polyline], after: list[Polyline],
           start: Point = (0.0, 0.0)) -> dict[str, float]:
    """Comparaison chiffrée avant / après."""
    d0 = travel_distance(before, start)
    d1 = travel_distance(after, start)
    return {
        'travel_before_mm': d0,
        'travel_after_mm': d1,
        'saved_mm': d0 - d1,
        'saved_percent': 0.0 if d0 <= 0 else (d0 - d1) / d0 * 100,
    }
