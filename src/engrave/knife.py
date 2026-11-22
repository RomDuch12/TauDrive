"""Couteau : donner une épaisseur à un tracé / Stroke to outline.

Un tracé de dessin n'a pas d'épaisseur : c'est une ligne, et la machine
la suit d'un passage de faisceau large de trois centièmes. Un **couteau**,
lui, a une largeur — la lame fait deux dixièmes, la saignée aussi.

Le couteau transforme donc une **ligne** en son **contour** : le bord de
la bande que la ligne balaierait si elle avait cette largeur. Ce qui sort
est un ou plusieurs **contours fermés, sans aucune auto-intersection**.

C'est la différence avec `toolpath.thicken`, et elle est entière :

| | `thicken` | `knife.outline` |
|---|---|---|
| rend | des **passages parallèles** | un **contour fermé** |
| sert à | graver un trait large | décrire le bord d'une bande |
| aux angles fermés | les passages se croisent | le contour se referme proprement |
| ensuite | ça part à la gravure | ça se hachure, se décale, s'exporte |

Un contour fermé se remplit, se décale d'un offset, s'exporte en DXF pour
une découpe. Un faisceau de passages parallèles ne fait rien de tout cela.

**Ce que « sans intersection » exige.** Décaler une ligne de part et
d'autre puis refermer les bouts donne, dès qu'il y a un angle un peu
fermé, une boucle qui repart en arrière et croise le reste. Sur une ligne
qui se croise elle-même — un « 8 », une signature — c'est pire : la bande
se recouvre, et le contour naïf a autant d'intersections que de
croisements. Il faut donc **unir** la bande à elle-même, ce qui est une
opération booléenne sur polygones, pas un décalage.

C'est ce que fait GEOS, par `shapely` : `LineString.buffer()` rend le
polygone exact de la bande, trous compris. Vérifié sur les cas durs — un
angle de 5°, un tracé en huit, une spirale dont les tours se recouvrent —
tous rendus valides et simples.

**Sans `shapely`, le couteau refuse.** Un contour approché ferait une
lame fausse, et une lame fausse coupe au mauvais endroit. Mieux vaut ne
rien rendre que rendre de travers.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog,
                               QDialogButtonBox, QFormLayout,
                               QLabel, QVBoxLayout)

from . import geometry as G
from .widgets import Combo, Spin
from . import theme

#: Bouts de la bande, aux extrémités d'un tracé ouvert.
CAPS = (
    ('round', 'arrondi', 'demi-cercle — le bout d\'une lame ronde'),
    ('flat', 'net', 'la bande s\'arrête sur le dernier point'),
    ('square', 'carré', 'la bande dépasse d\'une demi-largeur'),
)

#: Raccords aux angles du tracé.
JOINS = (
    ('round', 'arrondi', 'le plus sûr : jamais de pointe'),
    ('miter', 'onglet', 'l\'angle est prolongé jusqu\'à sa pointe'),
    ('bevel', 'chanfrein', 'la pointe est coupée droit'),
)

#: Segments par quart de cercle dans les arrondis.
#:
#: Seize donne, sur une lame de 0,2 mm, un écart à l'arc inférieur au
#: micron — trente fois plus fin que le spot. Monter plus haut ne fait
#: qu'allonger le fichier ISO.
RESOLUTION = 16

#: Limite d'onglet : au-delà, la pointe est chanfreinée.
#:
#: Sans limite, un angle de deux degrés produirait une pointe de trente
#: fois la largeur de la lame — une aiguille que rien ne peut couper.
MITER_LIMIT = 4.0

#: Largeur minimale acceptée, en mm. En deçà, on est sous le spot et le
#: contour ne veut plus rien dire.
MIN_WIDTH = 0.005


class KnifeError(RuntimeError):
    """Le couteau n'a pas pu rendre de contour."""


MISSING_NOTE = """La fonction couteau demande la bibliothèque « shapely »,
qui n'est pas installée.

Elle calcule l'union exacte de la bande, ce qu'un simple décalage ne sait
pas faire : sur un angle fermé ou un tracé qui se croise, le contour se
recouvrirait lui-même.

TauDrive préfère ne rien rendre plutôt qu'une lame fausse."""


def available() -> bool:
    """Vrai si le moteur géométrique est là."""
    try:
        import shapely                                    # noqa: F401
    except ImportError:
        return False
    return True


def label(key: str, table) -> str:
    for cle, nom, _ in table:
        if cle == key:
            return nom
    return key


def outline(polylines: list[G.Polyline], width: float, *,
            cap: str = 'round', join: str = 'round',
            miter_limit: float = MITER_LIMIT,
            resolution: int = RESOLUTION) -> list[G.Polyline]:
    """Contours fermés de la bande balayée par ces tracés.

    Tous les tracés sont **unis** en une seule opération : deux traits qui
    se recoupent — la barre et le montant d'un « T » — donnent un seul
    contour, et non deux qui se chevauchent.

    Rend les contours extérieurs **et les trous**, tous fermés. La règle
    pair-impair du hachurage s'y retrouve seule : un anneau se remplit
    entre ses deux bords, et pas au milieu.

    Un tracé fermé donne un **anneau** : la bande straddle la ligne, donc
    un bord dehors et un bord dedans. C'est ce qu'on attend d'un couteau
    posé sur un contour.
    """
    if not available():
        raise KnifeError(MISSING_NOTE)
    if width < MIN_WIDTH:
        raise KnifeError(
            f'largeur de {width:g} mm : en deçà de {MIN_WIDTH:g} mm on est '
            f'sous le diamètre du faisceau, et le contour ne veut plus '
            f'rien dire.')

    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import unary_union

    lignes = [LineString([(float(x), float(y)) for x, y in poly])
              for poly in polylines if len(poly) >= 2]
    if not lignes:
        raise KnifeError('aucun tracé à épaissir.')

    source = (lignes[0] if len(lignes) == 1
              else unary_union(MultiLineString(lignes)))
    bande = source.buffer(width / 2.0, cap_style=cap, join_style=join,
                          mitre_limit=miter_limit,
                          quad_segs=max(1, int(resolution)))
    if bande.is_empty:
        raise KnifeError('la bande calculée est vide.')
    return _contours(bande)


def _contours(geom) -> list[G.Polyline]:
    """Les anneaux d'un polygone shapely, en polylignes fermées."""
    out: list[G.Polyline] = []
    morceaux = (list(geom.geoms) if geom.geom_type.startswith('Multi')
                or geom.geom_type == 'GeometryCollection' else [geom])
    for part in morceaux:
        if part.geom_type != 'Polygon' or part.is_empty:
            continue
        for anneau in [part.exterior, *part.interiors]:
            points = [(float(x), float(y)) for x, y in anneau.coords]
            if len(points) >= 4:
                out.append(_closed(points))
    return out


def _closed(poly: G.Polyline) -> G.Polyline:
    if abs(poly[0][0] - poly[-1][0]) > 1e-12 \
            or abs(poly[0][1] - poly[-1][1]) > 1e-12:
        return list(poly) + [poly[0]]
    return list(poly)


def check(contours: list[G.Polyline]) -> list[str]:
    """Ce qui cloche dans un résultat de couteau. Vide s'il est propre.

    Le contrôle n'est pas décoratif : c'est la promesse de la fonction —
    **des contours fermés, sans intersection** — et elle se vérifie
    plutôt qu'elle ne s'affirme.
    """
    soucis: list[str] = []
    if not contours:
        return ['aucun contour']
    try:
        from shapely.geometry import LinearRing
    except ImportError:
        return []
    for rang, poly in enumerate(contours):
        if len(poly) < 4:
            soucis.append(f'contour {rang} : moins de trois sommets')
            continue
        if (abs(poly[0][0] - poly[-1][0]) > 1e-9
                or abs(poly[0][1] - poly[-1][1]) > 1e-9):
            soucis.append(f'contour {rang} : ouvert')
        try:
            anneau = LinearRing([(x, y) for x, y in poly])
        except Exception as exc:
            soucis.append(f'contour {rang} : illisible ({exc})')
            continue
        if not anneau.is_simple:
            soucis.append(f'contour {rang} : il se croise lui-même')
    return soucis


def area_mm2(contours: list[G.Polyline]) -> float:
    """Surface de la bande, trous déduits.

    Utile pour dire ce que la lame va enlever avant de la lancer : une
    bande de 0,2 mm sur un tracé d'un mètre, c'est 200 mm² à graver.
    """
    total = 0.0
    for poly in contours:
        aire = 0.0
        for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
            aire += x1 * y2 - x2 * y1
        total += abs(aire) / 2.0
    # les trous ont été comptés positivement : la bande vaut l'extérieur
    # moins l'intérieur, donc la somme alternée des surfaces triées
    aires = sorted((abs(sum(x1 * y2 - x2 * y1
                            for (x1, y1), (x2, y2) in zip(p, p[1:]))) / 2.0)
                   for p in contours)
    if len(aires) >= 2:
        return max(0.0, aires[-1] - sum(aires[:-1]))
    return total


def length_mm(polylines: list[G.Polyline]) -> float:
    """Longueur cumulée des tracés d'origine."""
    import math
    return sum(math.dist(a, b)
               for poly in polylines for a, b in zip(poly, poly[1:]))


# --------------------------------------------------------------------------
# Dialogue
# --------------------------------------------------------------------------

#: Largeur proposée au premier usage, en mm.
#: Deux dixièmes : la saignée d\'une lame fine, et six fois le spot.
DEFAULT_WIDTH = 0.2

STORE = 'knife/defaults'


def defaults() -> dict:
    from . import session
    brut = session.settings().value(STORE) or {}
    if not isinstance(brut, dict):
        brut = {}
    return {'width': float(brut.get('width', DEFAULT_WIDTH) or DEFAULT_WIDTH),
            'cap': str(brut.get('cap', 'round') or 'round'),
            'join': str(brut.get('join', 'round') or 'round'),
            'keep': str(brut.get('keep', '1')) not in ('0', 'false', 'False')}


def remember(**valeurs) -> None:
    from . import session
    courant = defaults()
    courant.update(valeurs)
    session.settings().setValue(STORE, courant)


class KnifeDialog(QDialog):
    """Largeur de lame, bouts, raccords — et ce que cela va donner.

    Le compte rendu est calculé **à chaque changement** : longueur du
    tracé, surface de la bande, nombre de contours, et le verdict du
    contrôle. On sait donc ce qu\'on obtient avant de le poser, et non
    après.
    """

    def __init__(self, parent, polylines: list) -> None:
        super().__init__(parent)
        self.setWindowTitle('Couteau')
        self.setMinimumWidth(460)
        self._polys = polylines
        self._resultat: list = []
        reglages = defaults()

        dehors = QVBoxLayout(self)
        dehors.addWidget(QLabel(
            'Donne une <b>épaisseur</b> au tracé et en rend le '
            '<b>contour fermé</b>.<br>'
            f'{theme.span()}Un contour se hachure, se décale '
            'et s\'exporte ; un trait épaissi par passages, non.</span>'))

        form = QFormLayout()
        self.w_width = Spin(reglages['width'], MIN_WIDTH, 50.0, 0.05, 3,
                            ' mm')
        self.w_width.setToolTip(
            'Largeur de la bande. Le tracé en est le milieu : elle déborde '
            'de moitié de chaque côté.')
        self.w_width.valueChanged.connect(self._recompute)
        form.addRow('Largeur de lame', self.w_width)

        self.w_cap = Combo()
        for cle, nom, note in CAPS:
            self.w_cap.addItem(f'{nom} — {note}', cle)
        self.w_cap.setCurrentIndex(max(0, self.w_cap.findData(
            reglages['cap'])))
        self.w_cap.currentIndexChanged.connect(self._recompute)
        self.w_cap.setToolTip(
            'Ce que devient le bout d\'un tracé ouvert. Sans effet sur '
            'un contour fermé, qui n\'a pas de bout.')
        form.addRow('Bouts', self.w_cap)

        self.w_join = Combo()
        for cle, nom, note in JOINS:
            self.w_join.addItem(f'{nom} — {note}', cle)
        self.w_join.setCurrentIndex(max(0, self.w_join.findData(
            reglages['join'])))
        self.w_join.currentIndexChanged.connect(self._recompute)
        form.addRow('Raccords', self.w_join)
        dehors.addLayout(form)

        self.w_keep = QCheckBox('Garder le tracé d\'origine, masqué')
        self.w_keep.setChecked(reglages['keep'])
        self.w_keep.setToolTip(
            'Le tracé nu reste dans le document, œil fermé : on y revient '
            'si la largeur ne convient pas.')
        dehors.addWidget(self.w_keep)

        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        dehors.addWidget(self.w_note)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        self._ok = boutons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText('Poser le contour')
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        dehors.addWidget(boutons)
        self._recompute()

    def _recompute(self, *_) -> None:
        from . import theme
        palette = theme.current()
        try:
            self._resultat = outline(
                self._polys, self.w_width.value(),
                cap=self.w_cap.currentData() or 'round',
                join=self.w_join.currentData() or 'round')
        except KnifeError as exc:
            self._resultat = []
            self.w_note.setText(
                f'<span style="color:{palette.alarm}">{exc}</span>')
            self._ok.setEnabled(False)
            return
        soucis = check(self._resultat)
        self._ok.setEnabled(not soucis)
        longueur = length_mm(self._polys)
        aire = area_mm2(self._resultat)
        if soucis:
            self.w_note.setText(
                f'<span style="color:{palette.alarm}">'
                + '<br>'.join(soucis) + '</span>')
            return
        self.w_note.setText(
            f'{len(self._resultat)} contour(s) fermé(s), sans intersection'
            f'<br>{theme.span()}tracé {longueur:.1f} mm · '
            f'bande {aire:.1f} mm² · '
            f'{sum(len(p) for p in self._resultat)} sommets</span>')

    def contours(self) -> list:
        return self._resultat

    def keep_original(self) -> bool:
        return self.w_keep.isChecked()

    def accept(self) -> None:
        remember(width=self.w_width.value(),
                 cap=self.w_cap.currentData() or 'round',
                 join=self.w_join.currentData() or 'round',
                 keep=self.w_keep.isChecked())
        super().accept()
