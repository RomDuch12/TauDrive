"""Traitement d'un dessin / Drawing treatment.

Préparer un dessin à la gravure en négatif demande toujours la même
séquence : poser un cadre, choisir sa marge, compenser la largeur du
faisceau par un offset de contour, et parfois épaissir le trait. Quatre
réglages dispersés dans la colonne des propriétés, à refaire dessin après
dessin.

Le traitement les réunit en un geste — et surtout, il **garde l'original**.

Ce qu'il fait, dans cet ordre :

1. il **copie** la sélection, la copie restant exactement où elle est ;
2. il **masque l'original** (œil fermé), **sans le déplacer** : il demeure
   à sa place dans le document, consultable et regravable d'un clic, mais
   ne part pas à la machine ;
3. il applique cadre, marge, offset et épaisseur **sur la copie**.

Garder l'original coûte quelques kilo-octets et évite de refaire un
dessin quand le traitement s'avère trop fort. Le masquer évite qu'il parte
à la gravure par distraction — ce que le contrôle avant export rappelle de
toute façon. **Le laisser en place** évite d'avoir à le replacer si l'on
change d'avis : une plaque est composée à la cote.
"""
from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QPushButton, QVBoxLayout)

from . import geometry as G
from . import session
from .model import Shape, Treatment
from .toolpath import shape_extent
from .widgets import Combo, Spin, fit_to_screen
from . import theme

#: Écart laissé entre l'original écarté et la copie traitée, en mm.
GAP_MM = 6.0

#: Cadres proposés, dans l'ordre du menu.
FRAMES = (('none', 'aucun'), ('rect', 'rectangle'), ('circle', 'cercle'))

#: Clé de rangement des modèles.
STORE = 'treatments/library'

#: Modèles livrés. Point de départ, pas vérité : les cotes dépendent de
#: la matière et du faisceau, et se règlent sur chute.
FACTORY: tuple[Treatment, ...] = (
    Treatment('Relief simple', 'rect', 1.0, 0.0, 0.0, 0.05),
    Treatment('Relief compensé 0,015', 'rect', 1.0, 0.015, 0.03, 0.05),
    Treatment('Relief épais 0,1', 'rect', 1.5, 0.1, 0.2, 0.05),
    Treatment('Médaillon rond', 'circle', 2.0, 0.015, 0.0, 0.05),
)


def templates() -> list[Treatment]:
    """Modèles rangés sur le poste, complétés par ceux d'usine."""
    brut = session.settings().value(STORE)
    if not isinstance(brut, list):
        return list(FACTORY)
    out: list[Treatment] = []
    for entree in brut:
        if not isinstance(entree, dict):
            continue
        champs = {f.name for f in dataclasses.fields(Treatment)}
        try:
            out.append(Treatment(**{k: v for k, v in entree.items()
                                    if k in champs}))
        except (TypeError, ValueError):
            continue
    return out or list(FACTORY)


def save_templates(modeles: list[Treatment]) -> None:
    session.settings().setValue(
        STORE, [dataclasses.asdict(m) for m in modeles])


def store_template(modele: Treatment) -> list[Treatment]:
    """Range un modèle, en remplaçant celui de même nom s'il existe."""
    liste = templates()
    rang = next((i for i, m in enumerate(liste) if m.name == modele.name), -1)
    if rang >= 0:
        liste[rang] = modele
    else:
        liste.append(modele)
    save_templates(liste)
    return liste


def drop_template(nom: str) -> list[Treatment]:
    """Retire un modèle. **Aucune process n'en pâtit** : celles qui s'en
    servaient en portent une copie figée, pas un renvoi."""
    liste = [m for m in templates() if m.name != nom]
    save_templates(liste)
    return liste


def separate(originals: list[Shape], gap: float = GAP_MM) -> float:
    """Masque les originaux, **sans les déplacer**. Rend 0.

    Ils étaient d'abord écartés sur le côté, pour se voir en vis-à-vis de
    la copie traitée. Mauvaise idée à l'usage : une plaque est composée à
    la cote, et pousser l'original ailleurs oblige à le replacer si l'on
    veut finalement le graver. Masqué sur place, il attend son tour sans
    rien déranger — un clic sur son œil le rend, exactement là où il
    était.
    """
    for shape in originals:
        shape.visible = False
    return 0.0


def from_values(name: str = '', **values) -> Treatment:
    """Modèle à partir des réglages d'un dialogue."""
    champs = {f.name for f in dataclasses.fields(Treatment)}
    return Treatment(name=name,
                     **{k: v for k, v in values.items()
                        if k in champs and k != 'name'})


def apply_treatment(shapes: list[Shape], modele: Treatment | None) -> None:
    """Applique un traitement figé — celui que porte une process."""
    if modele is None:
        return
    apply(shapes, frame=modele.frame, margin_mm=modele.margin_mm,
          offset_mm=modele.offset_mm, line_width_mm=modele.line_width_mm,
          line_step_mm=modele.line_step_mm)


def apply(shapes: list[Shape], *, frame: str = 'rect',
          margin_mm: float = 1.0, offset_mm: float = 0.0,
          line_width_mm: float = 0.0, line_step_mm: float = 0.05) -> None:
    """Pose cadre, marge, offset et épaisseur sur les formes données."""
    for shape in shapes:
        shape.frame = frame
        shape.frame_margin_mm = margin_mm
        shape.frame_offset_mm = offset_mm
        shape.line_width_mm = line_width_mm
        if line_width_mm > 0 and line_step_mm > 0:
            shape.line_step_mm = line_step_mm


class TreatmentDialog(QDialog):
    """Les quatre réglages d'un traitement, et ce qu'ils vont donner."""

    def __init__(self, parent, shapes: list[Shape]) -> None:
        super().__init__(parent)
        self.setWindowTitle('Traitement du dessin')
        self.setMinimumWidth(420)
        self._shapes = shapes

        dehors = QVBoxLayout(self)
        titre = (shapes[0].display_name() if len(shapes) == 1
                 else f'{len(shapes)} formes')
        dehors.addWidget(QLabel(
            f'<b>{titre}</b><br>'
            'L\'original est écarté et masqué ; les réglages ci-dessous '
            'sont appliqués<br>à une copie restée en place.'))

        # Les modèles : un traitement au point se réemploie, il ne se
        # ressaisit pas. Ils vivent sur le poste, pas dans le document.
        ligne = QHBoxLayout()
        self.w_template = Combo()
        self.w_template.setMinimumWidth(180)
        self._fill_templates()
        self.w_template.currentIndexChanged.connect(self._pick_template)
        b_save = QPushButton('Ranger…')
        b_save.setToolTip('Range ces réglages sous un nom, réutilisable '
                          'sur un autre dessin ou dans une process.')
        b_save.clicked.connect(self._store)
        b_drop = QPushButton('Retirer')
        b_drop.setToolTip('Retire le modèle de la liste. Les process qui '
                          's\'en servaient gardent leurs valeurs.')
        b_drop.clicked.connect(self._drop)
        ligne.addWidget(QLabel('Modèle'))
        ligne.addWidget(self.w_template, 1)
        ligne.addWidget(b_save)
        ligne.addWidget(b_drop)
        dehors.addLayout(ligne)

        g = QGroupBox('Gravure en négatif')
        f = QFormLayout(g)
        premiere = shapes[0]
        self.w_frame = Combo()
        for cle, libelle in FRAMES:
            self.w_frame.addItem(libelle, cle)
        self.w_frame.setCurrentIndex(max(self.w_frame.findData('rect'), 0))
        self.w_frame.setToolTip(
            'Avec un cadre, la matière est enlevée entre le cadre et le\n'
            'dessin : celui-ci ressort en relief.')
        self.w_margin = Spin(max(premiere.frame_margin_mm, 1.0), 0, 100,
                             0.5, 2, ' mm')
        self.w_offset = Spin(premiere.frame_offset_mm, -20, 20, 0.01, 3,
                             ' mm')
        self.w_offset.setToolTip(
            'Décale le contour du dessin épargné. Positif : la matière\n'
            'épaissit — compense la largeur du faisceau, qui amincit\n'
            'tout relief laissé par une gravure en négatif.')
        f.addRow('Cadre', self.w_frame)
        f.addRow('Marge', self.w_margin)
        f.addRow('Offset du dessin', self.w_offset)
        dehors.addWidget(g)

        g2 = QGroupBox('Épaisseur du trait')
        f2 = QFormLayout(g2)
        self.w_width = Spin(premiere.line_width_mm, 0, 20, 0.05, 3, ' mm')
        self.w_width.setToolTip(
            'Élargit le tracé par passages parallèles.\n'
            '0 = un seul passage.')
        self.w_step = Spin(max(premiere.line_step_mm, 0.05), 0.005, 5,
                           0.005, 3, ' mm')
        self.w_step.setToolTip('Écart entre deux passages parallèles.')
        self.w_double = QPushButton('Épaisseur = 2 × offset')
        self.w_double.setToolTip(
            'Reprend deux fois l\'offset du dessin : le trait grave\n'
            'exactement la bande dont le contour a été écarté, de part\n'
            'et d\'autre du tracé.')
        self.w_double.clicked.connect(self._double)
        f2.addRow('Épaisseur', self.w_width)
        f2.addRow('Pas des passages', self.w_step)
        f2.addRow('', self.w_double)
        dehors.addWidget(g2)

        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        self.w_note.setStyleSheet(theme.css())
        dehors.addWidget(self.w_note)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText('Traiter')
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        dehors.addWidget(boutons)

        for w in (self.w_margin, self.w_offset, self.w_width, self.w_step):
            w.valueChanged.connect(lambda *_: self._update())
        self.w_frame.currentIndexChanged.connect(lambda *_: self._update())
        self._update()
        fit_to_screen(self)

    def _fill_templates(self, choisi: str = '') -> None:
        garde = choisi or (self.w_template.currentData().name
                           if self.w_template.currentData() else '')
        self.w_template.blockSignals(True)
        self.w_template.clear()
        self.w_template.addItem('(réglages libres)', None)
        for modele in templates():
            self.w_template.addItem(f'{modele.name}   [{modele.describe()}]',
                                    modele)
        rang = next((i for i in range(self.w_template.count())
                     if getattr(self.w_template.itemData(i), 'name', '')
                     == garde), 0)
        self.w_template.setCurrentIndex(rang)
        self.w_template.blockSignals(False)

    def _pick_template(self) -> None:
        modele = self.w_template.currentData()
        if modele is None:
            return
        self.w_frame.setCurrentIndex(
            max(self.w_frame.findData(modele.frame), 0))
        self.w_margin.setValue(modele.margin_mm)
        self.w_offset.setValue(modele.offset_mm)
        self.w_width.setValue(modele.line_width_mm)
        self.w_step.setValue(modele.line_step_mm)
        self._update()

    def _store(self) -> None:
        actuel = self.w_template.currentData()
        nom, ok = QInputDialog.getText(
            self, 'Ranger le modèle', 'Sous quel nom ?',
            text=getattr(actuel, 'name', ''))
        if not ok or not nom.strip():
            return
        store_template(self.template(nom.strip()))
        self._fill_templates(nom.strip())

    def _drop(self) -> None:
        modele = self.w_template.currentData()
        if modele is None:
            return
        drop_template(modele.name)
        self._fill_templates()

    def template(self, nom: str = '') -> Treatment:
        """Les réglages courants, sous forme de modèle figé."""
        return from_values(nom, **self.values())

    def _double(self) -> None:
        """Épaisseur = deux fois l'offset. Un offset nul ne dit rien."""
        offset = abs(self.w_offset.value())
        if offset <= 0:
            self.w_note.setText(
                'Réglez d\'abord un offset : sans lui, il n\'y a pas de '
                'bande à couvrir.')
            return
        self.w_width.setValue(round(offset * 2, 4))

    def values(self) -> dict:
        return {
            'frame': self.w_frame.currentData() or 'none',
            'margin_mm': self.w_margin.value(),
            'offset_mm': self.w_offset.value(),
            'line_width_mm': self.w_width.value(),
            'line_step_mm': self.w_step.value(),
        }

    def _update(self) -> None:
        v = self.values()
        morceaux = []
        if v['frame'] == 'none':
            morceaux.append('sans cadre : le dessin lui-même est gravé')
        else:
            morceaux.append(f'gravure en négatif, marge {v["margin_mm"]:g} mm')
        if v['offset_mm']:
            sens = 'épaissi' if v['offset_mm'] > 0 else 'aminci'
            morceaux.append(f'relief {sens} de {abs(v["offset_mm"]):g} mm')
        if v['line_width_mm']:
            passages = max(1, int(v['line_width_mm'] / v['line_step_mm'] / 2))
            morceaux.append(f'trait de {v["line_width_mm"]:g} mm '
                            f'({passages} passage(s) de chaque côté)')
        self.w_note.setText(' · '.join(morceaux))
