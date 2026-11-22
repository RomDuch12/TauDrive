"""Date automatique / Automatic date stamp.

Un bouton pour poser la date du jour, et une flèche pour dire comment.

La date est posée comme **champ variable** `{date}`, pas comme texte figé :
elle est réévaluée à chaque export. Une plaque préparée le lundi et gravée
le mercredi porte la date du mercredi — ce qui est presque toujours ce
qu'on veut, et jamais ce qu'un texte tapé à la main donnerait.

Le format par défaut est `aammjj`, celui des dossiers de la machine.
"""
from __future__ import annotations

import datetime as dt

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QLabel, QVBoxLayout)

from . import session, textvec
from .model import Text
from .widgets import Combo, Spin, fit_to_screen
from .avale import avale
from . import theme

#: Formats proposés, avec le motif `strftime` et un exemple.
FORMATS: tuple[tuple[str, str, str], ...] = (
    ('aammjj', '%y%m%d', 'compact, celui des dossiers machine'),
    ('jj/mm/aa', '%d/%m/%y', 'lecture courante'),
    ('jj/mm/aaaa', '%d/%m/%Y', 'année complète'),
    ('aaaa-mm-jj', '%Y-%m-%d', 'tri alphabétique = tri chronologique'),
    ('jj.mm.aa', '%d.%m.%y', 'sans barre oblique'),
    ('mm/aaaa', '%m/%Y', 'mois et année'),
    ('aaaa', '%Y', 'année seule'),
    ('jj/mm/aa hh:mm', '%d/%m/%y %H:%M', 'date et heure'),
)

#: Façons d'ajuster la taille du texte.
FITS: tuple[tuple[str, str], ...] = (
    ('height', 'hauteur imposée (proportionnel)'),
    ('width', 'largeur imposée (proportionnel)'),
    ('box', 'dans une boîte X × Y'),
)

#: Clé de rangement des réglages.
STORE = 'datestamp'

_FALLBACK = {
    'format': '%y%m%d',
    'font': '',
    'fit': 'height',
    'size_mm': 5.0,
    'width_mm': 30.0,
}


def defaults() -> dict:
    brut = session.settings().value(STORE)
    out = dict(_FALLBACK)
    if isinstance(brut, dict):
        for cle, repli in _FALLBACK.items():
            valeur = brut.get(cle)
            if valeur is None:
                continue
            try:
                out[cle] = float(valeur) if isinstance(repli, float) \
                    else str(valeur)
            except (TypeError, ValueError):
                continue
    return out


def remember(**valeurs) -> None:
    courant = defaults()
    courant.update({k: v for k, v in valeurs.items() if k in _FALLBACK})
    session.settings().setValue(STORE, courant)


def sample(motif: str, when: dt.datetime | None = None) -> str:
    """Ce que le format donnera aujourd'hui."""
    try:
        return (when or dt.datetime.now()).strftime(motif)
    except ValueError:
        return '?'


def build(reglages: dict | None = None, recipe=None) -> Text:
    """Le texte de date, prêt à être ajouté au document.

    La taille est **calculée sur le rendu réel** quand une largeur est
    imposée : la date du jour ne fait pas la même largeur qu'une autre —
    `01/01/26` est plus étroite que `28/12/26` — et poser une taille
    nominale donnerait une plaque à refaire un jour sur deux.
    """
    r = dict(_FALLBACK)
    r.update(reglages or defaults())
    forme = Text(text='{date:' + str(r['format']) + '}',
                 size_mm=float(r['size_mm']),
                 font_path=str(r['font'] or ''),
                 name='date automatique')
    if recipe is not None:
        forme.recipe = recipe
    if r['fit'] in ('width', 'box'):
        forme.size_mm = _fit_size(sample(str(r['format'])), forme,
                                  float(r['width_mm']),
                                  float(r['size_mm'])
                                  if r['fit'] == 'box' else None)
    return forme


def _fit_size(rendu: str, forme: Text, largeur_mm: float,
              hauteur_mm: float | None) -> float:
    """Taille qui fait tenir `rendu` dans la largeur — et la hauteur.

    Mesuré sur les contours réellement vectorisés, pas sur une estimation
    de chasse : une police condensée et une police large ne tiennent pas
    la même place au même corps.
    """
    essai = 10.0
    try:
        contours = textvec.layout(rendu, essai, forme.font_path,
                                  forme.align, forme.valign,
                                  forme.line_spacing,
                                  measured=getattr(forme, 'cap_measured',
                                                   True))
    except Exception:
        return forme.size_mm
    if not contours:
        return forme.size_mm
    xs = [x for c in contours for x, _ in c]
    ys = [y for c in contours for _, y in c]
    largeur = max(xs) - min(xs)
    hauteur = max(ys) - min(ys)
    if largeur <= 0 or hauteur <= 0:
        return forme.size_mm
    facteur = largeur_mm / largeur
    if hauteur_mm:
        facteur = min(facteur, hauteur_mm / hauteur)
    return round(essai * facteur, 4)


class DateOptions(QDialog):
    """Format, police et taille de la date automatique."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Date automatique')
        self.setMinimumWidth(420)
        r = defaults()

        dehors = QVBoxLayout(self)
        dehors.addWidget(QLabel(
            'La date est posée comme <b>champ variable</b> : elle est '
            'réévaluée<br>à chaque export. Une plaque préparée lundi et '
            'gravée mercredi<br>porte la date du mercredi.'))

        g = QGroupBox('Format')
        f = QFormLayout(g)
        self.w_format = Combo()
        for libelle, motif, note in FORMATS:
            self.w_format.addItem(f'{libelle}   ({sample(motif)}) — {note}',
                                  motif)
        self.w_format.setCurrentIndex(
            max(self.w_format.findData(r['format']), 0))
        self.w_format.currentIndexChanged.connect(self._update)
        f.addRow('Format', self.w_format)
        dehors.addWidget(g)

        g2 = QGroupBox('Police et taille')
        f2 = QFormLayout(g2)
        self.w_font = Combo()
        self.w_font.addItem('(police par défaut)', '')
        try:
            for nom, chemin in textvec.available_fonts():
                self.w_font.addItem(nom, chemin)
        except Exception as exc:
            avale('police : liste incomplète', exc)
        rang = self.w_font.findData(r['font'])
        self.w_font.setCurrentIndex(max(rang, 0))
        self.w_fit = Combo()
        for cle, libelle in FITS:
            self.w_fit.addItem(libelle, cle)
        self.w_fit.setCurrentIndex(max(self.w_fit.findData(r['fit']), 0))
        self.w_fit.currentIndexChanged.connect(self._update)
        self.w_size = Spin(float(r['size_mm']), 0.2, 200, 0.5, 3, ' mm')
        self.w_width = Spin(float(r['width_mm']), 0.2, 500, 1, 3, ' mm')
        for w in (self.w_size, self.w_width):
            w.valueChanged.connect(lambda *_: self._update())
        f2.addRow('Police', self.w_font)
        f2.addRow('Ajustement', self.w_fit)
        f2.addRow('Hauteur', self.w_size)
        f2.addRow('Largeur', self.w_width)
        dehors.addWidget(g2)

        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        self.w_note.setStyleSheet(theme.css())
        dehors.addWidget(self.w_note)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText('Poser')
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        dehors.addWidget(boutons)
        self._update()
        fit_to_screen(self)

    def values(self) -> dict:
        return {
            'format': self.w_format.currentData() or '%y%m%d',
            'font': self.w_font.currentData() or '',
            'fit': self.w_fit.currentData() or 'height',
            'size_mm': self.w_size.value(),
            'width_mm': self.w_width.value(),
        }

    def _update(self) -> None:
        v = self.values()
        largeur = v['fit'] in ('width', 'box')
        self.w_width.setEnabled(largeur)
        self.w_size.setEnabled(v['fit'] in ('height', 'box'))
        rendu = sample(v['format'])
        cotes = ('hauteur imposée' if v['fit'] == 'height'
                 else 'largeur imposée' if v['fit'] == 'width'
                 else 'dans la boîte')
        self.w_note.setText(f'Aujourd\'hui : <b>{rendu}</b> — {cotes}. '
                            f'La taille sera recalculée à chaque date, '
                            f'pour que la largeur tienne.')
