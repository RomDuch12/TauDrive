"""Cintrer un texte en arc / Text on an arc.

Une bague, un médaillon, le pourtour d'une plaque ronde, un logo de club :
le texte suit un cercle. On le posait lettre par lettre, chacune tournée
à la main — et la quatrième penchait d'un degré de trop.

Le texte est **cintré** sur un cercle de rayon donné, mesuré sur sa
**ligne de base** :

* **au-dessus du centre**, il se lit de l'extérieur, de gauche à droite
  par le haut — le pied des lettres sur le cercle, leur tête vers
  l'extérieur ;
* **au-dessous du centre**, il se lit droit lui aussi, de gauche à droite
  par le bas — le pied sur le cercle, la tête vers le centre.

La longueur d'arc de la ligne de base est **celle du texte droit** : une
lettre ne s'étire ni ne se tasse sur le cercle, elle s'y couche. Les
lettres hautes s'évasent un peu au-dessus, se resserrent au-dessous,
comme sur toute bague gravée.

Le résultat est un **tracé** : il se grave partout, version antérieure
comprise, et ne se retape plus — comme un texte converti. Le cintrage se
défait comme tout autre geste. L'origine du tracé est **le centre du
cercle** : le tourner fait glisser le texte sur son cercle, et le centre
se pose au milieu d'une pièce ronde d'une seule saisie de position.

Le texte cintré garde la place qu'il avait : le milieu de sa ligne de
base reste où il était, le centre du cercle se met dessous (ou dessus).
"""
from __future__ import annotations

import dataclasses
import math

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QVBoxLayout)

from . import theme
from .model import Path, Shape, Text
from .toolpath import own_contours
from .widgets import Spin

#: Côtés du cercle : clé -> libellé.
COTES = {'haut': 'Au-dessus du centre — se lit par le haut',
         'bas': 'Au-dessous du centre — se lit par le bas'}

#: Écart toléré entre l'arc vrai et ses cordes, en mm. Bien sous le spot.
TOLERANCE_MM = 0.005

#: Part du tour au-delà de laquelle on refuse : les deux bouts du texte se
#: toucheraient, et le dernier caractère mordrait sur le premier.
TOUR_MAX = 0.97


def cintrable(shape: Shape) -> bool:
    """Vrai pour un texte qui dessine quelque chose."""
    return isinstance(shape, Text) and bool(shape.text.strip())


def _base(shape: Text, context: dict | None):
    """Contours posés sur la ligne de base de la première ligne, et le
    décalage vertical qui les ramène au texte tel qu'il est posé."""
    sur_base = dataclasses.replace(shape, valign='baseline')
    contours = own_contours(sur_base, context)
    poses = own_contours(shape, context)
    if not contours or not poses:
        return [], 0.0
    # même texte, même alignement : seul l'ancrage vertical diffère, et il
    # décale tout le bloc d'un même cran
    return contours, poses[0][0][1] - contours[0][0][1]


def mesure(shape: Text, context: dict | None = None):
    """(largeur, plus haut, plus bas) du texte sur sa ligne de base, en mm
    — None s'il ne dessine rien."""
    contours, _dy = _base(shape, context)
    if not contours:
        return None
    xs = [x for c in contours for x, _ in c]
    ys = [y for c in contours for _, y in c]
    return max(xs) - min(xs), max(ys), min(ys)


def rayon_naturel(shape: Text, context: dict | None = None) -> float:
    """Un rayon qui couche le texte sur un tiers de tour, au demi-mm."""
    m = mesure(shape, context)
    if m is None:
        return 20.0
    largeur, haut, bas = m
    r = largeur / (2 * math.pi / 3)
    return max(round(r * 2) / 2, 1.0, haut + 0.5, -bas + 0.5)


def probleme(shape: Text, rayon: float, cote: str,
             context: dict | None = None) -> str:
    """Pourquoi ce cintrage ne se fait pas — chaîne vide s'il se fait."""
    if cote not in COTES:
        return f'côté inconnu : {cote!r}'
    if not rayon > 0:
        return 'le rayon doit être positif'
    m = mesure(shape, context)
    if m is None:
        return 'ce texte ne dessine rien'
    largeur, haut, bas = m
    if largeur / rayon > TOUR_MAX * 2 * math.pi:
        return (f'le texte fait {largeur:.1f} mm : sur un rayon de '
                f'{rayon:g} mm, ses deux bouts se toucheraient — rayon '
                f'minimal {largeur / (TOUR_MAX * 2 * math.pi):.1f} mm')
    # la partie du texte tournée vers le centre doit rester en deçà
    vers_centre = haut if cote == 'bas' else -bas
    if vers_centre >= rayon:
        return (f'le texte dépasse le centre du cercle de '
                f'{vers_centre - rayon + 0.001:.1f} mm — rayon minimal '
                f'{vers_centre:.1f} mm')
    return ''


def angle_deg(shape: Text, rayon: float,
              context: dict | None = None) -> float:
    """L'angle qu'occupe la ligne de base sur le cercle, en degrés."""
    m = mesure(shape, context)
    if m is None or not rayon > 0:
        return 0.0
    return math.degrees(m[0] / rayon)


def _densifie(contour, rayon_max: float, rayon: float):
    """Recoupe les segments trop longs en angle : cintré, un segment droit
    deviendrait une corde, et la barre d'un T un trait tiré droit."""
    pas = 2 * math.acos(max(-1.0, 1 - TOLERANCE_MM / rayon_max))
    pas_x = max(pas * rayon, 1e-6)
    sortie = [contour[0]]
    for (ax, ay), (bx, by) in zip(contour, contour[1:]):
        n = int(math.ceil(abs(bx - ax) / pas_x))
        for k in range(1, n):
            t = k / n
            sortie.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        sortie.append((bx, by))
    return sortie


def cintrer(shape: Text, rayon: float, cote: str = 'haut',
            context: dict | None = None) -> Path:
    """Le tracé du texte cintré — voir l'en-tête du module.

    Lève `ValueError` si le cintrage ne se fait pas : la raison est celle
    de `probleme`. Tous les réglages communs — process, cadre, décalage,
    épaisseur, groupe — sont repris tels quels.
    """
    raison = probleme(shape, rayon, cote, context)
    if raison:
        raise ValueError(raison)
    contours, dy = _base(shape, context)
    xs = [x for c in contours for x, _ in c]
    cx = (min(xs) + max(xs)) / 2
    loin = max(abs(y) for c in contours for _, y in c)
    polylignes = []
    for c in contours:
        poly = []
        for x, y in _densifie(c, rayon + loin, rayon):
            if cote == 'haut':
                phi = math.pi / 2 - (x - cx) / rayon
                r = rayon + y
            else:
                phi = -math.pi / 2 + (x - cx) / rayon
                r = rayon - y
            poly.append((r * math.cos(phi), r * math.sin(phi)))
        polylignes.append(poly)
    # le centre du cercle, dans le repère du texte tel qu'il est posé
    centre_x, centre_y = cx, dy + (-rayon if cote == 'haut' else rayon)
    a = math.radians(shape.rotation_deg)
    ca, sa = math.cos(a), math.sin(a)
    communs = {f.name: getattr(shape, f.name)
               for f in dataclasses.fields(Shape)}
    communs['name'] = shape.display_name()
    communs['x'] = shape.x + centre_x * ca - centre_y * sa
    communs['y'] = shape.y + centre_x * sa + centre_y * ca
    return Path(polylines=polylignes, **communs)


class CintrageDialog(QDialog):
    """Rayon et côté — et ce que donnera l'arc, avant de rien changer."""

    def __init__(self, parent, shape: Text):
        super().__init__(parent)
        self.setWindowTitle('Cintrer en arc')
        self._shape = shape
        dehors = QVBoxLayout(self)
        f = QFormLayout()
        theme.tidy_form(f)
        self.w_rayon = Spin(rayon_naturel(shape), 0.5, 5000.0, 0.5, 3,
                            ' mm')
        self.w_rayon.setToolTip('Rayon du cercle, mesuré sur la ligne de '
                                'base du texte.')
        self.w_cote = QComboBox()
        for cle, libelle in COTES.items():
            self.w_cote.addItem(libelle, cle)
        f.addRow('Rayon', self.w_rayon)
        f.addRow('Côté', self.w_cote)
        dehors.addLayout(f)
        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        dehors.addWidget(self.w_note)
        aide = QLabel('Le texte devient un tracé : il ne se retape plus. '
                      'Son origine est le centre du cercle — le tourner le '
                      'fait glisser sur le cercle.')
        aide.setWordWrap(True)
        aide.setStyleSheet(theme.css('text_dim', 11))
        dehors.addWidget(aide)
        self.w_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.w_buttons.accepted.connect(self.accept)
        self.w_buttons.rejected.connect(self.reject)
        dehors.addWidget(self.w_buttons)
        self.w_rayon.valueChanged.connect(lambda *_: self._refresh())
        self.w_cote.currentIndexChanged.connect(lambda *_: self._refresh())
        self._refresh()

    def values(self) -> tuple[float, str]:
        """(rayon, côté)."""
        return float(self.w_rayon.value()), str(self.w_cote.currentData())

    def _refresh(self) -> None:
        rayon, cote = self.values()
        raison = probleme(self._shape, rayon, cote)
        ok = self.w_buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(not raison)
        if raison:
            self.w_note.setText(f'<b>Impossible</b> : {raison}.')
            return
        m = mesure(self._shape)
        self.w_note.setText(
            f'Arc de <b>{angle_deg(self._shape, rayon):.0f}°</b> pour '
            f'{m[0]:.1f} mm de texte — cercle de {2 * rayon:g} mm de '
            f'diamètre.')
