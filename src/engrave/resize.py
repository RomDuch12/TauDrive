"""Redimensionnement des formes / Shape resizing.

Touche **F2** dans l'interface. Fonctionne sur n'importe quelle forme —
rectangle, cercle, texte, tracé DXF — et sur une sélection multiple ou un
groupe, qui est alors mis à l'échelle d'un bloc autour de son centre.

Une réserve, énoncée aussi dans le dialogue : sur une forme **tournée**,
une mise à l'échelle **non uniforme** s'applique dans les axes propres de
la forme, pas dans ceux de l'écran. C'est le seul choix qui garde un
rectangle rectangle ; l'autre convention en ferait un parallélogramme,
que le modèle ne sait pas représenter. Une mise à l'échelle uniforme,
elle, est exacte quelle que soit la rotation.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QLabel, QVBoxLayout)

from . import geometry as G
from .model import Circle, Code, Path, Rect, Shape, Text
from .widgets import Spin
from .toolpath import renew_path_token, shape_contours, shape_extent
from . import theme


def local_size(shape: Shape) -> tuple[float, float]:
    """Encombrement propre d'une forme, rotation exclue, en mm.

    Cadre compris : c'est lui qui donne l'encombrement réel dès qu'il est
    posé, et c'est la cote que l'utilisateur lit sur la pièce.
    """
    if isinstance(shape, (Rect, Circle)) and shape.frame == 'none':
        return abs(shape.width), abs(shape.height)
    contours = shape_contours(shape)
    b = G.bounds(contours) if contours else None
    if b is None:
        return 0.0, 0.0
    return b[2] - b[0], b[3] - b[1]


def selection_size(shapes: list[Shape]) -> tuple[float, float]:
    """Encombrement d'une sélection, rotation et placement compris."""
    if len(shapes) == 1:
        return local_size(shapes[0])
    boxes = [b for b in (shape_extent(s) for s in shapes) if b]
    if not boxes:
        return 0.0, 0.0
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[2] for b in boxes)
    y2 = max(b[3] for b in boxes)
    return x2 - x1, y2 - y1


def selection_center(shapes: list[Shape]) -> tuple[float, float]:
    boxes = [b for b in (shape_extent(s) for s in shapes) if b]
    if not boxes:
        return 0.0, 0.0
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[2] for b in boxes)
    y2 = max(b[3] for b in boxes)
    return (x1 + x2) / 2, (y1 + y2) / 2


def scale_shape(shape: Shape, fx: float, fy: float,
                origin: tuple[float, float] | None = None) -> None:
    """Met une forme à l'échelle, sur place.

    `origin` est le point fixe de la transformation, en coordonnées
    machine. À défaut, la forme est mise à l'échelle autour de son propre
    centre et ne bouge pas.
    """
    fx = float(fx)
    fy = float(fy)
    if fx == 0 or fy == 0:
        raise ValueError('facteur nul')

    if origin is not None:
        ox, oy = origin
        shape.x = ox + (shape.x - ox) * fx
        shape.y = oy + (shape.y - oy) * fy

    if isinstance(shape, Code):
        # Un code posé dans une fenêtre suit cette fenêtre, chaque axe
        # indépendamment : c'est elle qui commande sa taille, et elle est
        # rectangulaire par nature.
        if shape.fit_w_mm > 0 or shape.fit_h_mm > 0:
            shape.fit_w_mm *= fx
            shape.fit_h_mm *= fy
        else:
            # sans fenêtre, les modules doivent rester carrés pour rester
            # lisibles : une demande non uniforme retient la moyenne des
            # deux facteurs plutôt que de produire un symbole illisible
            shape.module_mm *= (fx * fy) ** 0.5
        shape.bar_height_mm *= fy
        shape.fill_step_mm *= (fx * fy) ** 0.5
    elif isinstance(shape, (Rect, Circle)):
        shape.width *= fx
        shape.height *= fy
    elif isinstance(shape, Path):
        shape.polylines = [G.scale_xy(poly, fx, fy)
                           for poly in shape.polylines]
        # ses trajectoires mémorisées ne valent plus, même si les bouts de
        # son premier tracé n'ont pas bougé — un contour parti de l'origine
        renew_path_token(shape)
    elif isinstance(shape, Text):
        # la hauteur de capitale porte l'échelle verticale ; l'écart entre
        # les deux axes est reporté sur l'étirement horizontal
        shape.size_mm *= fy
        shape.stretch *= fx / fy

    # le cadre est une propriété de toute forme : il suit l'échelle où
    # qu'il soit posé, faute de quoi une pièce réduite garderait sa marge
    # d'origine et le négatif ne serait plus à la bonne cote
    shape.frame_margin_mm *= fy
    shape.frame_w *= fx
    shape.frame_h *= fy
    shape.line_width_mm *= (abs(fx) + abs(fy)) / 2


def move_selection_center(shapes: list[Shape], cx: float, cy: float) -> None:
    """Déplace la sélection pour que son centre tombe en (cx, cy).

    Le centre est celui de l'emprise commune, rotation comprise — la même
    référence que celle qu'affiche le dialogue. Les positions relatives des
    formes entre elles ne changent pas.
    """
    if not shapes:
        return
    ox, oy = selection_center(shapes)
    dx, dy = cx - ox, cy - oy
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return
    for shape in shapes:
        shape.x += dx
        shape.y += dy


def scale_selection(shapes: list[Shape], fx: float, fy: float) -> None:
    """Met une sélection à l'échelle autour de son centre commun."""
    if not shapes:
        return
    origin = selection_center(shapes) if len(shapes) > 1 else None
    for shape in shapes:
        scale_shape(shape, fx, fy, origin)


def rotate_selection(shapes: list[Shape], angle_deg: float) -> None:
    '''Fait tourner une sélection autour du centre de son emprise.

    Deux choses tournent, et il faut les deux :

    * **l'angle propre** de chaque forme (`rotation_deg`), sans quoi un
      texte resterait droit dans une plaque tournée ;
    * **la position** de chaque forme autour du centre commun, sans quoi
      les formes tourneraient sur elles-mêmes en restant en place.

    Une seule forme tourne sur son propre centre : il n'y a pas
    d'ensemble autour duquel la faire pivoter.
    '''
    if not shapes or abs(angle_deg) < 1e-12:
        return
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    cx, cy = selection_center(shapes) if len(shapes) > 1 else (None, None)

    for shape in shapes:
        shape.rotation_deg = (shape.rotation_deg + angle_deg) % 360.0
        if cx is None:
            continue
        dx, dy = shape.x - cx, shape.y - cy
        shape.x = cx + dx * cos_a - dy * sin_a
        shape.y = cy + dx * sin_a + dy * cos_a


#: Clé de la mémoire du repli des pourcentages.
CLE_POURCENT = 'resize/pourcentages'


def _pourcentages_ouverts() -> bool:
    '''Vrai si la section des pourcentages était ouverte la dernière fois.

    Fermée par défaut : la cote est le geste courant. Mais qui s'en sert
    s'en sert souvent, et la replier à chaque ouverture serait une
    brimade.
    '''
    from . import session
    return bool(session.settings().value(CLE_POURCENT, False, type=bool))


def _retenir_pourcentages(ouvert: bool) -> None:
    from . import session
    session.settings().setValue(CLE_POURCENT, bool(ouvert))


class ResizeDialog(QDialog):
    """Dialogue F2 : cotes visées ou pourcentages, proportions au choix."""

    def __init__(self, parent, shapes: list[Shape]) -> None:
        super().__init__(parent)
        self.setWindowTitle('Redimensionner')
        self.setMinimumWidth(360)
        self.shapes = shapes
        self.w0, self.h0 = selection_size(shapes)
        self.cx0, self.cy0 = selection_center(shapes)
        self._guard = False

        layout = QVBoxLayout(self)
        if len(shapes) == 1:
            title = shapes[0].display_name()
        else:
            title = f'{len(shapes)} formes sélectionnées'
        layout.addWidget(QLabel(f'<b>{title}</b>'))
        layout.addWidget(QLabel(
            f'Dimensions actuelles : {self.w0:.3f} × {self.h0:.3f} mm<br>'
            f'Centre actuel : {self.cx0:.3f} · {self.cy0:.3f} mm'))

        # --- la cote, en évidence ---
        #
        # C'est le geste courant : on tape la cote qu'on veut. Les
        # pourcentages servent une fois sur dix, et occupaient pourtant
        # deux lignes sur quatre, dans la même graisse et au même endroit
        # — rien ne disait par où commencer.
        g_cote = QGroupBox('Dimensions')
        form = QFormLayout(g_cote)
        self.w_keep = QCheckBox('Respecter les proportions')
        self.w_keep.setChecked(True)
        self.w_keep.toggled.connect(self._keep_toggled)

        self.w_x = self._spin(self.w0, ' mm', 0.001, 5000)
        self.w_y = self._spin(self.h0, ' mm', 0.001, 5000)
        for widget in (self.w_x, self.w_y):
            police = widget.font()
            police.setPointSizeF(police.pointSizeF() * 1.25)
            police.setBold(True)
            widget.setFont(police)
            widget.setMinimumHeight(32)
        form.addRow('<b>Dim X</b>', self.w_x)
        form.addRow('<b>Dim Y</b>', self.w_y)
        form.addRow('', self.w_keep)
        layout.addWidget(g_cote)

        # --- les pourcentages, en second ---
        #
        # Repliés : ils restent à un clic, sans se disputer l'attention
        # avec la cote. Ouvrir cette section la retient pour la fois
        # suivante — qui s'en sert s'en sert souvent.
        self.w_pct_box = QGroupBox('Ou en pourcentage')
        self.w_pct_box.setCheckable(True)
        self.w_pct_box.setChecked(_pourcentages_ouverts())
        self.w_pct_box.toggled.connect(_retenir_pourcentages)
        pf = QFormLayout(self.w_pct_box)
        self.p_x = self._spin(100.0, ' %', 0.01, 100000)
        self.p_y = self._spin(100.0, ' %', 0.01, 100000)
        pf.addRow('% X', self.p_x)
        pf.addRow('% Y', self.p_y)
        layout.addWidget(self.w_pct_box)

        # --- position du centre ---
        #
        # Redimensionner et placer sont le même geste dans la pratique :
        # on ajuste une plaque à sa fenêtre, puis on la met où elle doit
        # aller. Les demander dans deux endroits différents oblige à
        # ressortir du dialogue pour finir le travail.
        place = QFormLayout()
        self.w_move = QCheckBox('Positionner le centre')
        self.w_move.setToolTip(
            'Déplace la sélection pour que le centre de son emprise tombe\n'
            'exactement sur les cotes données. Les formes gardent leurs\n'
            'positions relatives.')
        self.w_move.toggled.connect(self._move_toggled)
        place.addRow('', self.w_move)
        self.c_x = Spin(self.cx0, -5000, 5000, 1, 3, ' mm')
        self.c_y = Spin(self.cy0, -5000, 5000, 1, 3, ' mm')
        for widget in (self.c_x, self.c_y):
            widget.setEnabled(False)
            widget.valueChanged.connect(lambda *_: self._update_note())
        place.addRow('Centre X', self.c_x)
        place.addRow('Centre Y', self.c_y)
        layout.addLayout(place)

        # --- rotation ---
        #
        # Troisième geste du même mouvement : mettre à la cote, tourner,
        # placer. Une plaque arrive rarement dans le bon sens, et
        # ressortir du dialogue pour la tourner à la souris fait perdre
        # la cote qu'on vient de régler.
        tourne = QFormLayout()
        self.w_turn = QCheckBox('Faire tourner')
        self.w_turn.setToolTip(
            'Tourne la sélection autour du centre de son emprise.\n'
            'Les formes gardent leurs positions relatives.')
        self.w_turn.toggled.connect(self._turn_toggled)
        tourne.addRow('', self.w_turn)
        self.r_angle = Spin(0.0, -360, 360, 15, 2, ' °')
        self.r_angle.setEnabled(False)
        self.r_angle.valueChanged.connect(lambda *_: self._update_note())
        tourne.addRow('Angle', self.r_angle)
        layout.addLayout(tourne)

        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        self.w_note.setStyleSheet(theme.css('text_dim', 11))
        layout.addWidget(self.w_note)
        self._update_note()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._enabled(self.w0 > 0, self.h0 > 0)

    def _turn_toggled(self, on: bool) -> None:
        self.r_angle.setEnabled(on)
        self._update_note()

    def _spin(self, value, suffix, lo, hi) -> Spin:
        w = Spin(value, lo, hi, decimals=3, suffix=suffix)
        w.valueChanged.connect(self._changed)
        return w

    def _enabled(self, x_ok: bool, y_ok: bool) -> None:
        """Une dimension nulle — un texte vide, un trait horizontal — ne peut
        pas être mise à l'échelle : mieux vaut griser que diviser par zéro."""
        self.w_x.setEnabled(x_ok)
        self.p_x.setEnabled(x_ok)
        self.w_y.setEnabled(y_ok)
        self.p_y.setEnabled(y_ok)

    def _move_toggled(self, on: bool) -> None:
        self.c_x.setEnabled(on)
        self.c_y.setEnabled(on)
        if not on:                       # revenir au centre courant
            self._guard = True
            self.c_x.setValue(self.cx0)
            self.c_y.setValue(self.cy0)
            self._guard = False
        self._update_note()

    def _keep_toggled(self, keep: bool) -> None:
        if keep:
            self._guard = True
            self.w_y.setValue(self.h0 * self.factors()[0])
            self.p_y.setValue(self.p_x.value())
            self._guard = False
        self._update_note()

    def _changed(self) -> None:
        """Tient les quatre champs d'accord entre eux.

        Le champ que l'utilisateur vient de modifier commande, les trois
        autres suivent. Sans ce garde-fou, chaque recalcul déclencherait le
        suivant en boucle.
        """
        if self._guard:
            return
        sender = self.sender()
        self._guard = True
        try:
            if sender is self.w_x:
                fx = self.w_x.value() / self.w0 if self.w0 else 1.0
                self.p_x.setValue(fx * 100)
                if self.w_keep.isChecked():
                    self.p_y.setValue(fx * 100)
                    self.w_y.setValue(self.h0 * fx)
            elif sender is self.p_x:
                fx = self.p_x.value() / 100
                self.w_x.setValue(self.w0 * fx)
                if self.w_keep.isChecked():
                    self.p_y.setValue(self.p_x.value())
                    self.w_y.setValue(self.h0 * fx)
            elif sender is self.w_y:
                fy = self.w_y.value() / self.h0 if self.h0 else 1.0
                self.p_y.setValue(fy * 100)
                if self.w_keep.isChecked():
                    self.p_x.setValue(fy * 100)
                    self.w_x.setValue(self.w0 * fy)
            elif sender is self.p_y:
                fy = self.p_y.value() / 100
                self.w_y.setValue(self.h0 * fy)
                if self.w_keep.isChecked():
                    self.p_x.setValue(self.p_y.value())
                    self.w_x.setValue(self.w0 * fy)
        finally:
            self._guard = False
        self._update_note()

    def _update_note(self) -> None:
        fx, fy = self.factors()
        rotated = any(abs(s.rotation_deg) > 1e-9 for s in self.shapes)
        if rotated and abs(fx - fy) > 1e-9:
            self.w_note.setText(
                '⚠ mise à l\'échelle non uniforme sur une forme tournée : '
                'elle s\'applique dans les axes propres de la forme, pas '
                'dans ceux de l\'écran.')
            self.w_note.setStyleSheet(theme.css('warn', 11))
        elif (any(isinstance(s, Code) and s.fit_w_mm <= 0 for s in self.shapes)
                and abs(fx - fy) > 1e-9):
            self.w_note.setText(
                '⚠ un code sans fenêtre imposée garde ses modules carrés : '
                'la moyenne des deux facteurs lui sera appliquée. Un code '
                'posé dans une fenêtre suit cette fenêtre, axe par axe.')
            self.w_note.setStyleSheet(theme.css('warn', 11))
        elif any(isinstance(s, Text) for s in self.shapes) and abs(fx - fy) > 1e-9:
            self.w_note.setText(
                'Texte étiré : la hauteur des lettres suit Y, leur largeur X.')
            self.w_note.setStyleSheet(theme.css('text_dim', 11))
        else:
            self.w_note.setText('')

    def factors(self) -> tuple[float, float]:
        fx = self.p_x.value() / 100 if self.w_x.isEnabled() else 1.0
        fy = self.p_y.value() / 100 if self.w_y.isEnabled() else 1.0
        return fx, fy

    def apply(self) -> None:
        '''Met à l'échelle, tourne, puis place — dans cet ordre.

        L'ordre n'est pas indifférent :

        * **la mise à l'échelle d'abord**, autour du centre courant. Elle
          agit sur X et Y séparément, ce qui n'a de sens que sur une
          forme encore droite : appliquée après une rotation, un
          étirement en X déformerait la pièce de travers ;
        * **la rotation ensuite**, autour du centre de l'emprise ;
        * **le placement en dernier**, parce que la rotation déplace le
          centre de l'emprise dès que la forme n'est pas symétrique. Le
          faire avant laisserait la pièce à côté de sa cote.
        '''
        fx, fy = self.factors()
        if abs(fx - 1) > 1e-12 or abs(fy - 1) > 1e-12:
            scale_selection(self.shapes, fx, fy)
        if self.w_turn.isChecked() and abs(self.r_angle.value()) > 1e-12:
            rotate_selection(self.shapes, self.r_angle.value())
        if self.w_move.isChecked():
            move_selection_center(self.shapes, self.c_x.value(),
                                  self.c_y.value())
