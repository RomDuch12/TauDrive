"""Oscillation du faisceau / Beam wobbling.

Superposer une oscillation au déplacement principal élargit le trait en
un seul passage : un spot de 0,03 mm trace une bande de 0,2 mm, avec une
densité d'énergie homogène d'un bord à l'autre. Deux usages :

* **marquage noir** sur alu ou inox — un trait large et régulier là où
  des passes parallèles laissent des stries ;
* **découpe fine** — une saignée un peu plus large que le faisceau, pour
  que le métal fondu ne se resolidifie pas derrière le passage.

La machine n'a pas d'oscillation native : elle se fait donc dans la
géométrie, avant l'export. C'est une transformation de trajectoire, au
même titre que le hachurage.

**La phase suit la longueur parcourue, pas le paramètre du segment.**
C'est le piège de la formule qu'on trouve partout — `θ = t × f` avec `t`
de 0 à 1 le long du segment. Sur un DXF dont les segments vont de 0,1 mm
à 20 mm, la même formule donne une oscillation deux cents fois plus
serrée sur l'un que sur l'autre. La phase est donc pilotée par l'abscisse
curviligne cumulée, et **continue d'un segment au suivant**.

**Ce n'est pas gratuit.** L'oscillation multiplie la longueur gravée, et
surtout elle demande au scanner une cadence de `v / pas`. À 80 m/min avec
un pas de 0,1 mm, cela fait 13 kHz — dix fois au-delà de ce qu'un galvo
sait suivre. `scanner_hz()` et `check()` disent la note à payer avant
qu'on la découvre sur la pièce.
"""
from __future__ import annotations

import math

from . import geometry as G

#: Formes d'oscillation offertes.
#:
#: * `cercle` — le tracé s'enroule en ressort ; la plus employée, elle
#:   couvre la largeur de façon homogène ;
#: * `huit` — deux boucles opposées par tour, l'énergie se concentre sur
#:   les bords : utile quand on veut fondre les rives d'une saignée ;
#: * `transverse` — un simple va-et-vient perpendiculaire, sans
#:   composante longitudinale : le plus court en trajet, mais l'énergie
#:   se concentre aux points de rebroussement.
SHAPES = (
    ('none', 'aucune', 'trajectoire directe'),
    ('circle', 'cercle', 'ressort — largeur couverte régulièrement'),
    ('eight', 'huit', 'deux boucles par tour — énergie sur les bords'),
    ('transverse', 'transverse', 'va-et-vient perpendiculaire'),
)

#: Points calculés par tour d'oscillation.
#:
#: Seize suffisent : à 0,1 mm de pas, cela fait un point tous les 6 µm,
#: cinq fois plus fin que le spot. Au-delà, on multiplie les lignes de
#: l'ISO sans rien gagner sur la pièce.
STEPS_PER_TURN = 16

#: Cadence que le scanner suit sans faiblir, en Hz.
#:
#: Un galvo de marquage tient quelques centaines de hertz à pleine
#: amplitude, un peu plus sur de très petits débattements. Au-delà,
#: l'oscillation s'arrondit puis s'efface : la commande part, le miroir
#: ne suit pas, et la bande n'est pas plus large qu'un trait simple.
SCANNER_SAFE_HZ = 500.0
SCANNER_MAX_HZ = 1000.0

#: Points qu'une oscillation peut produire pour une forme, au plus.
#:
#: Seize points par tour : au pas de 0,1 mm, cent soixante au millimètre.
#: Un pas tapé 0,001 au lieu de 0,1 en fait seize mille : le contour d'un
#: texte de 25 mm comptait des millions de points, TauDrive se figeait de
#: longues minutes et finissait à court de mémoire. Trois millions, c'est
#: 37 m de trait au pas de 0,2 mm — une vingtaine de minutes de gravure à
#: la cadence que le scanner suit — et quelque 300 Mo en mémoire.
#: Au-delà, la trajectoire reste sans oscillation, la vérification le
#: bloque et l'export le refuse — voir `toolpath.dense_wobble`.
MAX_POINTS = 3_000_000


def scanner_hz(speed_mm_min: float, pitch_mm: float) -> float:
    """Cadence demandée au scanner : une oscillation par pas parcouru."""
    if pitch_mm <= 0 or speed_mm_min <= 0:
        return 0.0
    return (speed_mm_min / 60.0) / pitch_mm


def max_speed_mm_min(pitch_mm: float, limit_hz: float = SCANNER_SAFE_HZ
                     ) -> float:
    """Vitesse au-delà de laquelle le scanner ne suit plus l'oscillation."""
    return max(0.0, pitch_mm * limit_hz * 60.0)


def check(speed_mm_min: float, pitch_mm: float, amplitude_mm: float,
          shape: str = 'circle') -> list[tuple[str, str]]:
    """Ce qui mérite un regard avant de lancer une oscillation.

    Rend une liste `(niveau, texte)` où le niveau vaut `'bloquant'`,
    `'attention'` ou `'info'` — les mêmes que la vérification avant
    export.
    """
    notes: list[tuple[str, str]] = []
    if shape == 'none' or amplitude_mm <= 0 or pitch_mm <= 0:
        return notes

    cadence = scanner_hz(speed_mm_min, pitch_mm)
    if cadence > SCANNER_MAX_HZ:
        notes.append((
            'bloquant',
            f'Oscillation à {cadence:.0f} Hz : le scanner n\'en tient pas '
            f'plus de {SCANNER_MAX_HZ:.0f}. Le miroir ne suivra pas, et la '
            f'bande ne sera pas plus large qu\'un trait simple. Descendez '
            f'à {max_speed_mm_min(pitch_mm) * 0.001:.1f} m/min, ou '
            f'élargissez le pas.'))
    elif cadence > SCANNER_SAFE_HZ:
        notes.append((
            'attention',
            f'Oscillation à {cadence:.0f} Hz : au-delà de '
            f'{SCANNER_SAFE_HZ:.0f} Hz, l\'amplitude réelle commence à '
            f'être plus faible que demandée. À vérifier sur chute.'))

    if pitch_mm > amplitude_mm * 4:
        notes.append((
            'attention',
            f'Pas de {pitch_mm:g} mm pour une amplitude de '
            f'{amplitude_mm:g} mm : les tours sont trop espacés, la bande '
            f'sortira festonnée au lieu d\'être pleine.'))

    facteur = length_factor(amplitude_mm, pitch_mm, shape)
    if facteur > 8:
        notes.append((
            'info',
            f'La longueur gravée est multipliée par {facteur:.0f} : la '
            f'durée et la taille du fichier ISO suivent.'))
    return notes


#: Longueur d'un tour d'oscillation, en multiples de l'amplitude.
#:
#: **Mesurées, non déduites.** La valeur analytique du cercle — 2πa,
#: soit 6,28 — surestime : une partie du mouvement circulaire se confond
#: avec l'avance, et le tracé discrétisé coupe les arcs. Ces constantes
#: viennent de la mesure du tracé réellement produit, sur trois couples
#: (amplitude, pas), et tiennent à 9 % près.
TURN_LENGTH = {'circle': 5.5, 'eight': 8.9, 'transverse': 4.3}


def length_factor(amplitude_mm: float, pitch_mm: float,
                  shape: str = 'circle') -> float:
    """De combien l'oscillation multiplie la longueur d'un trait.

    Le tracé avance de `p` par tour tout en parcourant `k·a` en travers :
    la longueur d'un tour est l'hypoténuse des deux, et le facteur en est
    le rapport à `p`. Jamais moins de 1.
    """
    if shape == 'none' or amplitude_mm <= 0 or pitch_mm <= 0:
        return 1.0
    tour = TURN_LENGTH.get(shape, 0.0) * amplitude_mm
    return max(1.0, math.hypot(tour, pitch_mm) / pitch_mm)


def _offset(shape: str, phase: float, amplitude: float
            ) -> tuple[float, float]:
    """Écart au tracé, en repère local `(tangente, normale)`."""
    if shape == 'circle':
        return amplitude * math.sin(phase), amplitude * math.cos(phase)
    if shape == 'eight':
        # Lissajous 1:2 — deux boucles par tour, croisées au centre
        return amplitude * math.sin(2 * phase), amplitude * math.cos(phase)
    if shape == 'transverse':
        return 0.0, amplitude * math.cos(phase)
    return 0.0, 0.0


def apply_polyline(poly: G.Polyline, amplitude_mm: float, pitch_mm: float,
                   shape: str = 'circle') -> G.Polyline:
    """Une polyligne, oscillation superposée.

    La phase repart de zéro **au début de chaque polyligne** et court
    ensuite sur toute sa longueur, sommets compris : une oscillation qui
    se réinitialiserait à chaque segment ferait un ressaut visible à
    chaque angle du dessin.

    Le premier et le dernier point sont **ramenés sur le tracé** : sans
    cela, un contour fermé ne se refermerait plus, et la règle
    pair-impair du hachurage s'en trouverait faussée.
    """
    if (shape == 'none' or amplitude_mm <= 0 or pitch_mm <= 0
            or len(poly) < 2):
        return list(poly)

    if shape not in ('circle', 'eight', 'transverse'):
        # forme inconnue (fichier d'une version future) : aucun écart
        return _apply_generic(poly, amplitude_mm, pitch_mm, shape)

    # La boucle intérieure tourne une fois par point produit — trois
    # millions pour un texte hachuré fin : `_offset` y est déplié et les
    # fonctions tenues en local. Les opérations, et leur ordre, sont
    # celles de `_apply_generic` : le tracé est identique au bit près.
    pas_calcul = pitch_mm / STEPS_PER_TURN
    sortie: list[tuple[float, float]] = []
    ajoute = sortie.append
    sin, cos, hypot, ceil = math.sin, math.cos, math.hypot, math.ceil
    deux_pi = 2 * math.pi
    a = amplitude_mm
    parcouru = 0.0

    x1, y1 = poly[0]
    for x2, y2 in poly[1:]:
        dx, dy = x2 - x1, y2 - y1
        longueur = hypot(dx, dy)
        if longueur <= 1e-12:
            x1, y1 = x2, y2
            continue
        tx, ty = dx / longueur, dy / longueur
        nx, ny = -ty, tx                      # normale à gauche
        n = max(1, int(ceil(longueur / pas_calcul)))
        for k in range(n):
            phase = deux_pi * (parcouru + longueur * k / n) / pitch_mm
            if shape == 'circle':
                le, ne = a * sin(phase), a * cos(phase)
            elif shape == 'eight':
                le, ne = a * sin(2 * phase), a * cos(phase)
            else:
                le, ne = 0.0, a * cos(phase)
            ajoute((x1 + dx * k / n + tx * le + nx * ne,
                    y1 + dy * k / n + ty * le + ny * ne))
        parcouru += longueur
        x1, y1 = x2, y2

    if not sortie:
        return list(poly)
    # les bouts reviennent sur le tracé : un contour doit rester fermé
    sortie[0] = tuple(poly[0])
    sortie.append(tuple(poly[-1]))
    return sortie


def _apply_generic(poly: G.Polyline, amplitude_mm: float, pitch_mm: float,
                   shape: str) -> G.Polyline:
    """La forme écrite simplement, point par point, par `_offset`.

    C'est la définition dont `apply_polyline` est la version rapide ; elle
    sert aux formes que cette dernière ne connaît pas, et de référence à
    l'autotest.
    """
    pas_calcul = pitch_mm / STEPS_PER_TURN
    sortie: list[tuple[float, float]] = []
    parcouru = 0.0

    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        dx, dy = x2 - x1, y2 - y1
        longueur = math.hypot(dx, dy)
        if longueur <= 1e-12:
            continue
        tx, ty = dx / longueur, dy / longueur
        nx, ny = -ty, tx                      # normale à gauche
        n = max(1, int(math.ceil(longueur / pas_calcul)))
        for k in range(n):
            s = parcouru + longueur * k / n
            phase = 2 * math.pi * s / pitch_mm
            le, ne = _offset(shape, phase, amplitude_mm)
            base_x = x1 + dx * k / n
            base_y = y1 + dy * k / n
            sortie.append((base_x + tx * le + nx * ne,
                           base_y + ty * le + ny * ne))
        parcouru += longueur

    if not sortie:
        return list(poly)
    sortie[0] = tuple(poly[0])
    sortie.append(tuple(poly[-1]))
    return sortie


def point_count(polylines: list[G.Polyline], pitch_mm: float) -> int:
    """Points que produirait `apply`, **comptés sans être calculés**.

    Le compte est exact : chaque segment en donne autant que la boucle de
    `apply_polyline`, plus le dernier point. Il ne coûte qu'un passage sur
    les segments d'origine — seize fois moins de points, au moins, que le
    tracé oscillé. Une longueur infinie ou non numérique compte pour
    démesurée : l'oscillation n'en serait jamais venue à bout.
    """
    if pitch_mm <= 0:
        return sum(len(p) for p in polylines)
    pas_calcul = pitch_mm / STEPS_PER_TURN
    hypot, ceil = math.hypot, math.ceil
    total = 0
    for poly in polylines:
        if len(poly) < 2:
            total += len(poly)
            continue
        n = 0
        x1, y1 = poly[0]
        for x2, y2 in poly[1:]:
            longueur = hypot(x2 - x1, y2 - y1)
            if not longueur <= 1e-12:         # NaN compris
                q = longueur / pas_calcul
                if not q < 1e15:
                    return 10 ** 15
                n += max(1, int(ceil(q)))
            x1, y1 = x2, y2
        total += n + 1 if n else len(poly)
    return total


def apply(polylines: list[G.Polyline], amplitude_mm: float,
          pitch_mm: float, shape: str = 'circle') -> list[G.Polyline]:
    """Toutes les trajectoires, oscillation superposée."""
    if shape == 'none' or amplitude_mm <= 0 or pitch_mm <= 0:
        return polylines
    return [apply_polyline(p, amplitude_mm, pitch_mm, shape)
            for p in polylines]


def label(shape: str) -> str:
    for key, nom, _ in SHAPES:
        if key == shape:
            return nom
    return shape
