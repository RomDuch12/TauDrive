"""Répéter une sélection en grille / Step-and-repeat.

Vingt étiquettes sur une plaque, un montage à huit postes posé à la main,
une série de porte-clés : on dupliquait, on déplaçait, on recommençait —
et une copie décalée d'un millimètre partait à la gravure.

La sélection est recopiée en **colonnes et rangées**, à un pas donné :
l'original reste en haut à gauche, les copies suivent rangée par rangée,
de gauche à droite — l'ordre de la liste, donc l'ordre de gravure, est
celui de la lecture. Chaque case est une copie **entière** de la
sélection :

* une plaque groupée — code et texte — donne une plaque groupée par case,
  chacune son groupe : déplacer une case ne déplace pas les autres ;
* le texte d'une plaque suit le code **de sa case**, comme à la
  duplication : retaper une case ne change pas le numéro des autres ;
* une forme qui n'était pas groupée ne l'est pas plus en copie — voir
  `Document.regroup_copies`.

**En cercle**, la sélection se recopie autour d'un centre — les
graduations d'un cadran, les rayons d'une rosace, des perçages sur une
bride : `repeter_en_cercle`. Sur un tour entier, les copies se
répartissent régulièrement, la dernière ne retombe pas sur l'original ;
sur un arc, la première et la dernière en marquent les bouts. Les copies
**tournent avec le cercle** — une graduation reste dirigée vers le
centre — ou gardent leur angle — un chiffre reste droit.

**Les champs variables valent la même chose dans toutes les cases** :
`{n}`, `{date}` sont évalués pièce par pièce, et une grille est **une**
pièce. Pour numéroter, c'est le lot qu'il faut — un jeu de fichiers par
pièce, `Document.copies`.
"""
from __future__ import annotations

import math

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QVBoxLayout)

from . import serialize, theme
from .model import Document, Shape
from .toolpath import shape_contours, shape_extent
from .widgets import IntSpin, Spin

#: Bornes du formulaire : au-delà, la liste des formes devient illisible.
MAX_CASES = 400

#: Jour entre deux cases quand le pas se déduit de la taille, en mm.
JOUR_MM = 2.0


def emprise(shapes: list[Shape]):
    boites = [b for b in (shape_extent(s) for s in shapes) if b]
    if not boites:
        return None
    return (min(b[0] for b in boites), min(b[1] for b in boites),
            max(b[2] for b in boites), max(b[3] for b in boites))


def pas_naturel(shapes: list[Shape], jour: float = JOUR_MM):
    """Le pas qui pose les cases côte à côte, à `jour` mm l'une de l'autre."""
    e = emprise(shapes)
    if e is None:
        return 10.0, 10.0
    return (e[2] - e[0]) + jour, (e[3] - e[1]) + jour


def emprise_grille(shapes: list[Shape], colonnes: int, rangees: int,
                   pas_x: float, pas_y: float):
    """L'emprise de la grille entière, ou None — pour la vérifier contre
    le champ avant de rien créer."""
    e = emprise(shapes)
    if e is None:
        return None
    return (e[0], e[1] - (rangees - 1) * pas_y,
            e[2] + (colonnes - 1) * pas_x, e[3])


def repeter(document: Document, shapes: list[Shape], colonnes: int,
            rangees: int, pas_x: float, pas_y: float) -> list[Shape]:
    """Ajoute au document les copies de `shapes` en grille. Rend les
    copies, case par case, rangée par rangée.

    Les rangées descendent : la deuxième est à `pas_y` **sous** la
    première. L'original occupe la première case et ne bouge pas.
    """
    if colonnes < 1 or rangees < 1:
        raise ValueError('au moins une colonne et une rangée')
    if colonnes * rangees > MAX_CASES:
        raise ValueError(f'au plus {MAX_CASES} cases')
    ordonnees = _dans_l_ordre(document, shapes)
    sortie: list[Shape] = []
    for r in range(rangees):
        for c in range(colonnes):
            if r == 0 and c == 0:
                continue

            def placer(copie, forme, c=c, r=r):
                copie.x = forme.x + c * pas_x
                copie.y = forme.y - r * pas_y
            sortie += _case(document, ordonnees, placer)
    return sortie


def _dans_l_ordre(document: Document, shapes: list[Shape]) -> list[Shape]:
    """La sélection dans l'ordre du document, et non celui des clics : une
    plaque garde son code avant son texte, puisque c'est l'ordre de
    gravure."""
    voulus = {s.id for s in shapes}
    return [s for s in document.shapes if s.id in voulus]


def _case(document: Document, ordonnees: list[Shape], placer) -> list[Shape]:
    """Ajoute une copie entière de la sélection, que `placer(copie,
    forme)` met à sa place. Rend les copies."""
    liens: dict[str, str] = {}
    paires = []
    sortie: list[Shape] = []
    for forme in ordonnees:
        copie = serialize.shape_from_dict(
            serialize.shape_to_dict(forme), new_id=True)
        placer(copie, forme)
        groupe, copie.group = copie.group, ''
        liens[forme.id] = copie.id
        paires.append((copie, groupe))
        sortie.append(document.add(copie))
    # le texte d'une plaque suit le code de sa case
    for copie, _g in paires:
        suivi = getattr(copie, 'follows', '')
        if suivi and suivi in liens:
            copie.follows = liens[suivi]
    document.regroup_copies(paires)
    return sortie


def angles_cercle(nombre: int, angle_deg: float = 360.0) -> list[float]:
    """Les angles des `nombre` cases, l'original à 0°, dans le sens
    trigonométrique.

    Un tour entier se partage en `nombre` pas égaux : la dernière case
    ne retombe pas sur la première. Un arc place la première et la
    dernière à ses bouts.
    """
    if nombre < 1:
        return []
    if abs(abs(angle_deg) - 360.0) < 1e-9 or nombre == 1:
        pas = angle_deg / nombre
    else:
        pas = angle_deg / (nombre - 1)
    return [k * pas for k in range(nombre)]


def _tourne(x: float, y: float, cx: float, cy: float, angle_deg: float):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    return (cx + (x - cx) * ca - (y - cy) * sa,
            cy + (x - cx) * sa + (y - cy) * ca)


def repeter_en_cercle(document: Document, shapes: list[Shape], nombre: int,
                      cx: float = 0.0, cy: float = 0.0,
                      angle_deg: float = 360.0,
                      orienter: bool = True) -> list[Shape]:
    """Ajoute au document les copies de `shapes` autour de (cx, cy). Rend
    les copies, case par case, dans le sens de rotation.

    `angle_deg` positif tourne dans le sens trigonométrique, négatif dans
    celui des aiguilles d'une montre. `orienter` fait tourner chaque copie
    avec le cercle ; sinon elle garde l'angle de l'original. L'original
    occupe la première case et ne bouge pas.
    """
    if nombre < 2:
        raise ValueError('au moins deux cases')
    if nombre > MAX_CASES:
        raise ValueError(f'au plus {MAX_CASES} cases')
    if not 0 < abs(angle_deg) <= 360.0:
        raise ValueError('angle entre 0 et 360°')
    ordonnees = _dans_l_ordre(document, shapes)
    sortie: list[Shape] = []
    for angle in angles_cercle(nombre, angle_deg)[1:]:

        def placer(copie, forme, angle=angle):
            copie.x, copie.y = _tourne(forme.x, forme.y, cx, cy, angle)
            if orienter:
                copie.rotation_deg = (forme.rotation_deg + angle) % 360.0
        sortie += _case(document, ordonnees, placer)
    return sortie


def _enveloppe(points):
    """Enveloppe convexe d'un semis de points (chaîne monotone)."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cote(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    bas, haut = [], []
    for q in pts:
        while len(bas) >= 2 and cote(bas[-2], bas[-1], q) <= 0:
            bas.pop()
        bas.append(q)
    for q in reversed(pts):
        while len(haut) >= 2 and cote(haut[-2], haut[-1], q) <= 0:
            haut.pop()
        haut.append(q)
    return bas[:-1] + haut[:-1]


def emprise_cercle(shapes: list[Shape], nombre: int, cx: float, cy: float,
                   angle_deg: float, orienter: bool):
    """L'emprise de toutes les cases, ou None — sans rien ajouter au
    document.

    Chaque forme est réduite une fois à l'enveloppe convexe de ses
    contours : tournée, son emprise est celle de l'enveloppe tournée.
    Quatre cents cases d'un dessin de cinq mille tracés se mesurent ainsi
    à chaque frappe dans le dialogue.
    """
    enveloppes = []
    for forme in shapes:
        pts = [q for c in shape_contours(forme) for q in c]
        if pts:
            enveloppes.append((forme, _enveloppe(pts)))
    if not enveloppes:
        return None
    x1 = y1 = math.inf
    x2 = y2 = -math.inf
    for angle in angles_cercle(nombre, angle_deg):
        for forme, env in enveloppes:
            x, y = _tourne(forme.x, forme.y, cx, cy, angle)
            rot = forme.rotation_deg + (angle if orienter else 0.0)
            for px, py in env:
                qx, qy = _tourne(px, py, 0.0, 0.0, rot)
                x1, x2 = min(x1, qx + x), max(x2, qx + x)
                y1, y2 = min(y1, qy + y), max(y2, qy + y)
    return (x1, y1, x2, y2)


class RepetitionDialog(QDialog):
    """Colonnes, rangées, pas — et ce que donnera la grille, avant de
    rien créer : son nombre de cases, ses cotes, et si elle tient dans le
    champ."""

    def __init__(self, parent, shapes: list[Shape], document: Document):
        super().__init__(parent)
        self.setWindowTitle('Répéter en grille')
        self._shapes = list(shapes)
        self._document = document
        self._guard = False

        dehors = QVBoxLayout(self)
        f = QFormLayout()
        theme.tidy_form(f)
        self.w_cols = IntSpin(3, 1, 50)
        self.w_rows = IntSpin(2, 1, 50)
        self.w_auto = QCheckBox('Côte à côte, au jour près')
        self.w_auto.setChecked(True)
        self.w_auto.setToolTip(
            'Le pas suit la taille de la sélection, plus le jour : les '
            'cases se touchent presque, sans se chevaucher.')
        self.w_jour = Spin(JOUR_MM, 0.0, 100.0, 0.5, 3, ' mm')
        px, py = pas_naturel(self._shapes)
        self.w_px = Spin(px, 0.001, 5000.0, 1.0, 3, ' mm')
        self.w_py = Spin(py, 0.001, 5000.0, 1.0, 3, ' mm')
        self.w_px.setToolTip('Entraxe de deux colonnes, bord gauche à '
                             'bord gauche.')
        self.w_py.setToolTip('Entraxe de deux rangées ; les rangées '
                             'descendent.')
        f.addRow('Colonnes', self.w_cols)
        f.addRow('Rangées', self.w_rows)
        f.addRow('', self.w_auto)
        f.addRow('Jour', self.w_jour)
        f.addRow('Pas X', self.w_px)
        f.addRow('Pas Y', self.w_py)
        dehors.addLayout(f)
        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        dehors.addWidget(self.w_note)
        aide = QLabel('Les champs variables — {n}, {date} — valent la même '
                      'chose dans toutes les cases : pour numéroter, '
                      'passez par le lot.')
        aide.setWordWrap(True)
        aide.setStyleSheet(theme.css('text_dim', 11))
        dehors.addWidget(aide)
        self.w_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.w_buttons.accepted.connect(self.accept)
        self.w_buttons.rejected.connect(self.reject)
        dehors.addWidget(self.w_buttons)
        for champ in (self.w_cols, self.w_rows, self.w_jour, self.w_px,
                      self.w_py):
            champ.valueChanged.connect(lambda *_: self._refresh())
        self.w_auto.toggled.connect(lambda *_: self._refresh())
        self._refresh()

    def values(self) -> tuple[int, int, float, float]:
        """(colonnes, rangées, pas X, pas Y)."""
        return (int(self.w_cols.value()), int(self.w_rows.value()),
                float(self.w_px.value()), float(self.w_py.value()))

    def _refresh(self) -> None:
        if self._guard:
            return
        self._guard = True
        try:
            auto = self.w_auto.isChecked()
            self.w_jour.setEnabled(auto)
            self.w_px.setEnabled(not auto)
            self.w_py.setEnabled(not auto)
            if auto:
                px, py = pas_naturel(self._shapes, self.w_jour.value())
                self.w_px.setValue(px)
                self.w_py.setValue(py)
        finally:
            self._guard = False
        cols, rows, px, py = self.values()
        n = cols * rows
        texte = f'<b>{n} case(s)</b>'
        e = emprise_grille(self._shapes, cols, rows, px, py)
        dehors = False
        if e is not None:
            texte += (f' · grille {e[2] - e[0]:.1f} × {e[3] - e[1]:.1f} mm')
            hw = self._document.field_w / 2
            hh = self._document.field_h / 2
            dehors = (e[0] < -hw - 1e-6 or e[2] > hw + 1e-6
                      or e[1] < -hh - 1e-6 or e[3] > hh + 1e-6)
        trop = n > MAX_CASES
        if trop:
            texte += f'<br>Au plus {MAX_CASES} cases.'
        elif dehors:
            texte += ('<br>La grille sort du champ de marquage : '
                      'réduisez-la, ou posez-la ailleurs ensuite.')
        self.w_note.setText(texte)
        self.w_note.setStyleSheet(
            f'color:{theme.ALARM};' if (trop or dehors) else '')
        self.w_buttons.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(not trop and n > 1)


class CercleDialog(QDialog):
    """Nombre, centre, angle couvert — et ce que donnera le cercle, avant
    de rien créer : rayon, pas, et s'il tient dans le champ."""

    def __init__(self, parent, shapes: list[Shape], document: Document):
        super().__init__(parent)
        self.setWindowTitle('Répéter en cercle')
        self._shapes = list(shapes)
        self._document = document
        dehors = QVBoxLayout(self)
        f = QFormLayout()
        theme.tidy_form(f)
        self.w_nombre = IntSpin(12, 2, MAX_CASES)
        self.w_cx = Spin(0.0, -5000.0, 5000.0, 1.0, 3, ' mm')
        self.w_cy = Spin(0.0, -5000.0, 5000.0, 1.0, 3, ' mm')
        self.w_cx.setToolTip('Centre du cercle — par défaut, celui du '
                             'champ de marquage.')
        self.w_angle = Spin(360.0, -360.0, 360.0, 15.0, 3, '°')
        self.w_angle.setToolTip(
            'Angle couvert : 360° pour un tour entier, moins pour un arc. '
            'Négatif, les copies tournent dans le sens des aiguilles '
            'd\'une montre.')
        self.w_orienter = QCheckBox('Les copies tournent avec le cercle')
        self.w_orienter.setChecked(True)
        self.w_orienter.setToolTip(
            'Cochée, une graduation reste dirigée vers le centre ; '
            'décochée, chaque copie garde l\'angle de l\'original — un '
            'chiffre reste droit.')
        f.addRow('Cases', self.w_nombre)
        f.addRow('Centre X', self.w_cx)
        f.addRow('Centre Y', self.w_cy)
        f.addRow('Angle couvert', self.w_angle)
        f.addRow('', self.w_orienter)
        dehors.addLayout(f)
        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        dehors.addWidget(self.w_note)
        self.w_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.w_buttons.accepted.connect(self.accept)
        self.w_buttons.rejected.connect(self.reject)
        dehors.addWidget(self.w_buttons)
        for champ in (self.w_nombre, self.w_cx, self.w_cy, self.w_angle):
            champ.valueChanged.connect(lambda *_: self._refresh())
        self.w_orienter.toggled.connect(lambda *_: self._refresh())
        self._refresh()

    def values(self) -> tuple[int, float, float, float, bool]:
        """(cases, centre X, centre Y, angle, orienter)."""
        return (int(self.w_nombre.value()), float(self.w_cx.value()),
                float(self.w_cy.value()), float(self.w_angle.value()),
                self.w_orienter.isChecked())

    def _refresh(self) -> None:
        n, cx, cy, angle, orienter = self.values()
        e = emprise(self._shapes)
        rayon = (math.hypot((e[0] + e[2]) / 2 - cx, (e[1] + e[3]) / 2 - cy)
                 if e else 0.0)
        nul = abs(angle) < 1e-9
        texte = f'<b>{n} case(s)</b>'
        dehors = False
        if not nul:
            pas = angles_cercle(n, angle)[1] if n > 1 else 0.0
            texte += f' · pas {pas:g}° · rayon {rayon:.1f} mm'
            ec = emprise_cercle(self._shapes, n, cx, cy, angle, orienter)
            if ec is not None:
                hw = self._document.field_w / 2
                hh = self._document.field_h / 2
                dehors = (ec[0] < -hw - 1e-6 or ec[2] > hw + 1e-6
                          or ec[1] < -hh - 1e-6 or ec[3] > hh + 1e-6)
        if nul:
            texte += '<br>Un angle nul ne répète rien.'
        elif rayon < 1e-6:
            texte += ('<br>La sélection est au centre : les copies '
                      'tourneraient sur place.')
        elif dehors:
            texte += ('<br>Le cercle sort du champ de marquage : '
                      'rapprochez la sélection du centre.')
        self.w_note.setText(texte)
        self.w_note.setStyleSheet(
            f'color:{theme.ALARM};' if (nul or dehors) else '')
        self.w_buttons.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(not nul)
