"""Morceaux : graver plus grand que le champ / Tiling an oversize job.

Le champ de marquage fait 110 × 110 mm, et c'est la lentille qui le
fixe : la tête ne se déplace pas, le faisceau balaie ce carré et rien
d'autre. Un dessin plus grand se grave donc **en plusieurs morceaux** :
on grave ce qui tient, on déplace la pièce d'une cote connue, on grave
la suite. La machine n'ayant pas d'axe X/Y motorisé, ce déplacement est
celui de l'**opérateur** — à la butée, au réglet, au vernier de l'étau.
D'où des consignes en clair, morceau par morceau, en millimètres et en
sens, écrites dans le dossier d'export à côté des jobs.

Trois choses sont fixées ici.

**La découpe.** Une grille de morceaux égaux, chacun au plus de la
taille **utile** du champ : le champ moins une marge de sécurité de
chaque côté, parce que le bord de champ est l'endroit où l'optique est
la moins fidèle, et qu'un raccord y serait visible. Des morceaux égaux
plutôt que des morceaux pleins suivis d'une lamelle : quatre bandes de
50 mm se posent mieux que trois de 106 et une de 82.

**Le découpage des trajectoires.** Les passes du travail sont
construites une fois, exactement comme à l'export ordinaire, puis
chaque segment est coupé au bord des morceaux (Liang–Barsky) et
recentré sur l'origine du morceau. Un trait qui traverse une frontière
donne deux traits, un dans chaque morceau. **Rien n'est gravé deux
fois** : un trait posé exactement sur une frontière appartient à un
seul morceau.

**Les consignes.** Un ordre de gravure en serpentin — rangée par
rangée, en alternant le sens, ce qui fait le moins de déplacements — et
pour chaque morceau le déplacement de la pièce depuis le précédent,
dans le repère du plan de travail. Le premier morceau dit où placer la
pièce ; les suivants disent de combien la pousser.

Ce que cela ne fait pas : aligner les morceaux à la place de
l'opérateur. Un raccord juste dépend du déplacement réel de la pièce,
et un écart de deux dixièmes se lit sur un trait continu. Les consignes
le disent, et proposent une **marque de raccord** : un petit trait gravé
de part et d'autre de chaque frontière, à comparer après coup.
"""
from __future__ import annotations

import dataclasses
import datetime
import math
from dataclasses import dataclass

from . import geometry as G
from .model import Document

#: Marge de sécurité proposée, retirée de chaque bord du champ.
MARGE_DEFAUT = 2.0

#: Tolérance de recouvrement sur une frontière, en mm.
EPS = 1e-6


@dataclass
class Morceau:
    """Un morceau de la grille, dans les coordonnées du dessin."""
    rang: int                       # ordre de gravure, à partir de 1
    colonne: int                    # à partir de 1, de gauche à droite
    rangee: int                     # à partir de 1, de haut en bas
    x1: float
    y1: float
    x2: float
    y2: float
    #: Déplacement de la **pièce** depuis le morceau précédent, en mm.
    #: Nul pour le premier.
    dx: float = 0.0
    dy: float = 0.0
    #: Un voisin existe de ce côté. La frontière de droite et celle du
    #: haut appartiennent au voisin ; les traits de raccord, eux, se
    #: gravent des quatre côtés où il y a quelqu'un.
    voisin_droite: bool = False
    voisin_haut: bool = False
    voisin_gauche: bool = False
    voisin_bas: bool = False

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def largeur(self) -> float:
        return self.x2 - self.x1

    @property
    def hauteur(self) -> float:
        return self.y2 - self.y1

    def dossier(self, stem: str) -> str:
        return f'{stem}_m{self.rang:02d}'


# --------------------------------------------------------------------------
# Découpe
# --------------------------------------------------------------------------

def utile(field_w: float, field_h: float, marge_mm: float) -> tuple[float, float]:
    """Taille utile du champ, marge retirée de chaque côté."""
    m = max(0.0, float(marge_mm))
    return max(1.0, field_w - 2 * m), max(1.0, field_h - 2 * m)


def necessaire(document: Document, marge_mm: float = 0.0) -> bool:
    """Vrai si le dessin déborde du champ utile."""
    b = document.bounds()
    if b is None:
        return False
    uw, uh = utile(document.field_w, document.field_h, marge_mm)
    return (b[2] - b[0]) > uw + EPS or (b[3] - b[1]) > uh + EPS


#: Au-delà de ce nombre de morceaux, il n'y a plus de plan : mille
#: morceaux, ce sont mille déplacements de la pièce à la main, et un
#: dessin de 3 m de côté dans le champ de 110 mm. Seul un document abîmé
#: y arrive — un champ de 0,01 mm, une emprise de vingt mètres —, et le
#: plan, qui créait alors des millions de morceaux, épuisait la mémoire.
MAX_MORCEAUX = 1000


def compte(bornes, field_w: float, field_h: float,
           marge_mm: float = MARGE_DEFAUT) -> tuple[int, int]:
    """(colonnes, rangées) de la grille qui couvre `bornes`, sans la
    construire — (0, 0) pour un dessin vide."""
    if bornes is None:
        return 0, 0
    x1, y1, x2, y2 = bornes
    uw, uh = utile(field_w, field_h, marge_mm)
    return (max(1, math.ceil((x2 - x1 - EPS) / uw)),
            max(1, math.ceil((y2 - y1 - EPS) / uh)))


def plan(bornes, field_w: float, field_h: float,
         marge_mm: float = MARGE_DEFAUT) -> list[Morceau]:
    """La grille de morceaux qui couvre `bornes`, en ordre de gravure.

    Une seule case, centrée sur l'origine du dessin, si tout tient : le
    travail part alors tel quel, sans déplacement. Aucune au-delà de
    `MAX_MORCEAUX` : le dialogue le dit, et n'exporte rien.
    """
    if bornes is None:
        return []
    x1, y1, x2, y2 = bornes
    largeur, hauteur = x2 - x1, y2 - y1
    nx, ny = compte(bornes, field_w, field_h, marge_mm)
    if nx * ny > MAX_MORCEAUX:
        return []
    if nx == 1 and ny == 1:
        hw, hh = field_w / 2, field_h / 2
        return [Morceau(1, 1, 1, -hw, -hh, hw, hh)]

    tw, th = largeur / nx, hauteur / ny
    morceaux: list[Morceau] = []
    rang = 0
    # rangées du haut vers le bas, en serpentin : la rangée 1 va de
    # gauche à droite, la 2 revient, et ainsi de suite
    for j in range(ny):
        haut = y2 - j * th
        bas = haut - th
        colonnes = range(nx) if j % 2 == 0 else range(nx - 1, -1, -1)
        for i in colonnes:
            rang += 1
            morceaux.append(Morceau(
                rang, i + 1, j + 1,
                x1 + i * tw, bas, x1 + (i + 1) * tw, haut,
                voisin_droite=i < nx - 1, voisin_haut=j > 0,
                voisin_gauche=i > 0, voisin_bas=j < ny - 1))
    # le déplacement de la pièce est l'opposé de celui du morceau : pour
    # graver plus à droite dans le dessin, la pièce va vers la gauche
    for precedent, suivant in zip(morceaux, morceaux[1:]):
        suivant.dx = _net(-(suivant.cx - precedent.cx))
        suivant.dy = _net(-(suivant.cy - precedent.cy))
    return morceaux


def _net(v: float) -> float:
    """`-0.0` s'écrirait « -0,0 » dans les consignes."""
    return 0.0 if abs(v) < 1e-9 else v


def dimensions(morceaux: list[Morceau]) -> tuple[int, int]:
    """(colonnes, rangées) de la grille."""
    if not morceaux:
        return 0, 0
    return (max(m.colonne for m in morceaux),
            max(m.rangee for m in morceaux))


# --------------------------------------------------------------------------
# Découpage des trajectoires
# --------------------------------------------------------------------------

def _clip(p, q, x1: float, y1: float, x2: float, y2: float):
    """Le segment [p, q] coupé au rectangle, ou `None` s'il est dehors.

    Liang–Barsky : quatre tests paramétriques, sans intersection
    explicite. Les bords sont **compris**.
    """
    (px, py), (qx, qy) = p, q
    dx, dy = qx - px, qy - py
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, px - x1), (dx, x2 - px), (-dy, py - y1),
                   (dy, y2 - py)):
        if pk == 0.0:
            if qk < 0.0:
                return None
            continue
        t = qk / pk
        if pk < 0.0:
            if t > t1:
                return None
            if t > t0:
                t0 = t
        else:
            if t < t0:
                return None
            if t < t1:
                t1 = t
    if t0 > t1:
        return None
    return ((px + t0 * dx, py + t0 * dy), (px + t1 * dx, py + t1 * dy))


def _sur_frontiere(a, b, m: Morceau) -> bool:
    """Vrai si le segment est posé sur une frontière qui appartient au
    voisin : à droite ou en haut."""
    if m.voisin_droite and abs(a[0] - m.x2) < EPS and abs(b[0] - m.x2) < EPS:
        return True
    if m.voisin_haut and abs(a[1] - m.y2) < EPS and abs(b[1] - m.y2) < EPS:
        return True
    return False


def couper_polyligne(poly: G.Polyline, m: Morceau) -> list[G.Polyline]:
    """Les tronçons d'une polyligne qui tombent dans le morceau.

    Un tronçon se prolonge tant que les segments coupés se suivent ;
    dès qu'un segment sort et qu'un autre rentre, c'est un tronçon neuf.
    """
    tronçons: list[G.Polyline] = []
    courant: G.Polyline = []
    for a, b in zip(poly, poly[1:]):
        coupe = _clip(a, b, m.x1, m.y1, m.x2, m.y2)
        if coupe is None:
            if len(courant) >= 2:
                tronçons.append(courant)
            courant = []
            continue
        ca, cb = coupe
        if math.hypot(cb[0] - ca[0], cb[1] - ca[1]) < EPS:
            continue
        if _sur_frontiere(ca, cb, m):
            if len(courant) >= 2:
                tronçons.append(courant)
            courant = []
            continue
        if courant and math.hypot(courant[-1][0] - ca[0],
                                  courant[-1][1] - ca[1]) < EPS:
            courant.append(cb)
        else:
            if len(courant) >= 2:
                tronçons.append(courant)
            courant = [ca, cb]
    if len(courant) >= 2:
        tronçons.append(courant)
    return tronçons


def passes_du_morceau(passes: list, m: Morceau) -> list:
    """Les passes du travail réduites au morceau, recentrées sur son
    centre. Une passe qui n'y a rien à graver disparaît."""
    out = []
    cx, cy = m.cx, m.cy
    for p in passes:
        polys: list[G.Polyline] = []
        for poly in p.polylines:
            for tronçon in couper_polyligne(poly, m):
                polys.append([(x - cx, y - cy) for x, y in tronçon])
        if polys:
            out.append(dataclasses.replace(p, polylines=polys))
    return out


def marques_de_raccord(m: Morceau, longueur_mm: float = 2.0) -> list[G.Polyline]:
    """Traits de contrôle au milieu de chaque frontière partagée, **dans**
    le morceau, recentrés sur son centre.

    Chaque voisin grave le sien de l'autre côté : les deux doivent se
    prolonger en un trait continu de deux fois `longueur_mm`. S'ils sont
    décalés, la pièce n'a pas été déplacée juste — et de combien se
    mesure au réglet.
    """
    marques: list[G.Polyline] = []
    cx, cy = m.cx, m.cy
    L = longueur_mm
    if m.voisin_droite:
        marques.append([(m.x2 - L - cx, 0.0), (m.x2 - cx, 0.0)])
    if m.voisin_gauche:
        marques.append([(m.x1 - cx, 0.0), (m.x1 + L - cx, 0.0)])
    if m.voisin_haut:
        marques.append([(0.0, m.y2 - L - cy), (0.0, m.y2 - cy)])
    if m.voisin_bas:
        marques.append([(0.0, m.y1 - cy), (0.0, m.y1 + L - cy)])
    return marques


# --------------------------------------------------------------------------
# Consignes
# --------------------------------------------------------------------------

def _mm(v: float) -> str:
    """`-100,0` : une décimale, virgule française, signe explicite."""
    return f'{v:+.1f}'.replace('.', ',')


def _sens(dx: float, dy: float) -> str:
    bouts = []
    if abs(dx) >= 0.05:
        bouts.append(f'{abs(dx):.1f} mm vers X{"+" if dx > 0 else "−"} '
                     f'({"droite" if dx > 0 else "gauche"})')
    if abs(dy) >= 0.05:
        bouts.append(f'{abs(dy):.1f} mm vers Y{"+" if dy > 0 else "−"} '
                     f'({"haut" if dy > 0 else "bas"})')
    return ' et '.join(bouts).replace('.', ',') if bouts else 'aucun'


def consignes(document: Document, morceaux: list[Morceau], stem: str,
              marge_mm: float, avec_marques: bool = False) -> str:
    """Le texte remis à l'opérateur, écrit dans le dossier d'export."""
    b = document.bounds() or (0.0, 0.0, 0.0, 0.0)
    nx, ny = dimensions(morceaux)
    n = len(morceaux)
    quand = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    def v(x: float) -> str:
        return f'{x:.1f}'.replace('.', ',')

    lignes = [
        f'CONSIGNES OPÉRATEUR — GRAVURE EN {n} MORCEAU{"X" if n > 1 else ""}',
        f'Travail : {document.name}    Écrit le {quand} par TauDrive',
        f'Dessin : {v(b[2] - b[0])} × {v(b[3] - b[1])} mm — champ de '
        f'marquage {document.field_w:g} × {document.field_h:g} mm, marge '
        f'de sécurité {v(marge_mm)} mm de chaque côté',
        f'Découpe : {nx} colonne{"s" if nx > 1 else ""} × {ny} '
        f'rangée{"s" if ny > 1 else ""} — morceaux de '
        f'{v(morceaux[0].largeur)} × {v(morceaux[0].hauteur)} mm',
        '',
        'Repère : X+ vers la droite du plan de travail, Y+ vers le haut, '
        'tels qu\'affichés à l\'écran.',
        'Les déplacements sont ceux de la PIÈCE sur la table, en '
        'millimètres, depuis le morceau précédent.',
        'Entre deux morceaux : même origine machine, même Z, même '
        'position du champ. Seule la pièce bouge.',
    ]
    if avec_marques:
        lignes.append(
            'Chaque morceau grave un trait de raccord de 2 mm au milieu '
            'de chaque frontière : après le dernier morceau, ces traits '
            'doivent se prolonger exactement. Un décalage se lit et se '
            'mesure.')
    lignes.append('')
    for m in morceaux:
        lignes.append(
            f'Morceau {m.rang}/{n}  (rangée {m.rangee}, colonne '
            f'{m.colonne}) — dossier {m.dossier(stem)}')
        if m.rang == 1:
            lignes.append(
                f'  Placer la pièce de sorte que le point X {_mm(m.cx)} / '
                f'Y {_mm(m.cy)} du dessin soit au centre du champ.')
        else:
            lignes.append(f'  Déplacer la pièce de {_sens(m.dx, m.dy)}.')
        lignes.append(
            f'  Couvre le dessin de X {_mm(m.x1)} à {_mm(m.x2)} et de '
            f'Y {_mm(m.y1)} à {_mm(m.y2)}.')
        lignes.append(f'  Lancer {m.dossier(stem)}.CLJOB, attendre la fin.')
        lignes.append('')
    if n > 1:
        tx = sum(m.dx for m in morceaux)
        ty = sum(m.dy for m in morceaux)
        lignes.append(
            f'Contrôle : au dernier morceau, la pièce a été déplacée en tout '
            f'de X {_mm(tx)} / Y {_mm(ty)} par rapport au premier.')
    return '\n'.join(lignes) + '\n'


# --------------------------------------------------------------------------
# Dialogue
# --------------------------------------------------------------------------

def _dialogue():
    """Les classes Qt, importées à la demande : le découpage lui-même
    n'a pas besoin de l'interface, et l'autotest le mesure sans elle."""
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                   QFormLayout, QHBoxLayout, QLabel,
                                   QTextBrowser, QVBoxLayout, QWidget)
    from . import theme
    from .widgets import Spin

    class Apercu(QWidget):
        """La grille des morceaux sur le dessin, numérotée."""

        def __init__(self) -> None:
            super().__init__()
            self.setMinimumSize(320, 220)
            self._bornes = None
            self._morceaux: list[Morceau] = []
            self._champ = (110.0, 110.0)

        def montrer(self, bornes, morceaux, champ) -> None:
            self._bornes, self._morceaux, self._champ = bornes, morceaux, champ
            self.update()

        def paintEvent(self, _event) -> None:
            p = theme.current()
            qp = QPainter(self)
            qp.setRenderHint(QPainter.Antialiasing)
            qp.fillRect(self.rect(), QColor(p.canvas))
            if not self._bornes or not self._morceaux:
                return
            x1, y1, x2, y2 = self._bornes
            marge = 18
            w, h = self.width() - 2 * marge, self.height() - 2 * marge
            echelle = min(w / max(x2 - x1, 1e-6), h / max(y2 - y1, 1e-6))

            def vers(x, y):
                return (marge + (x - x1) * echelle,
                        marge + (y2 - y) * echelle)

            # le dessin
            qp.setPen(QPen(QColor(p.path), 2))
            ax, ay = vers(x1, y2)
            bx, by = vers(x2, y1)
            qp.drawRect(QRectF(ax, ay, bx - ax, by - ay))
            # les morceaux, et leur numéro
            qp.setPen(QPen(QColor(p.selected), 1, Qt.DashLine))
            for m in self._morceaux:
                ax, ay = vers(m.x1, m.y2)
                bx, by = vers(m.x2, m.y1)
                qp.drawRect(QRectF(ax, ay, bx - ax, by - ay))
            qp.setPen(QPen(QColor(p.text)))
            police = qp.font()
            police.setBold(True)
            police.setPointSize(max(10, police.pointSize() + 2))
            qp.setFont(police)
            for m in self._morceaux:
                ax, ay = vers(m.x1, m.y2)
                bx, by = vers(m.x2, m.y1)
                qp.drawText(QRectF(ax, ay, bx - ax, by - ay),
                            Qt.AlignCenter, str(m.rang))

    class MorceauxDialog(QDialog):
        """Combien de morceaux, avec quelle marge, et les consignes."""

        def __init__(self, parent, document: Document, stem: str) -> None:
            super().__init__(parent)
            self.setWindowTitle('Exporter en morceaux')
            self.setMinimumSize(720, 560)
            self.document = document
            self.stem = stem
            self._plan: list[Morceau] = []

            dehors = QVBoxLayout(self)
            b = document.bounds() or (0.0, 0.0, 0.0, 0.0)
            self.w_titre = QLabel('')
            self.w_titre.setWordWrap(True)
            dehors.addWidget(self.w_titre)

            haut = QHBoxLayout()
            self.w_apercu = Apercu()
            haut.addWidget(self.w_apercu, 1)

            reglages = QFormLayout()
            theme.tidy_form(reglages)
            self.w_marge = Spin(MARGE_DEFAUT, 0.0, 20.0, 0.5, 1, ' mm')
            self.w_marge.setToolTip(
                'Retirée de chaque bord du champ. Le bord de champ est '
                'l\'endroit où l\'optique est la moins fidèle : un raccord '
                'y serait visible.\n0 = tout le champ.')
            self.w_marge.valueChanged.connect(self._recalculer)
            reglages.addRow('Marge de sécurité', self.w_marge)
            self.w_marques = QCheckBox('Graver des traits de raccord')
            self.w_marques.setToolTip(
                'Un trait de 2 mm au milieu de chaque frontière, de part '
                'et d\'autre. Après le dernier morceau, ils doivent se '
                'prolonger : sinon la pièce n\'a pas été déplacée juste.\n'
                'À réserver aux pièces où une marque en plus est admise.')
            self.w_marques.toggled.connect(self._recalculer)
            reglages.addRow('', self.w_marques)
            self.w_resume = QLabel('')
            self.w_resume.setWordWrap(True)
            self.w_resume.setStyleSheet(theme.css())
            reglages.addRow('', self.w_resume)
            colonne = QWidget()
            colonne.setLayout(reglages)
            colonne.setMaximumWidth(300)
            haut.addWidget(colonne)
            dehors.addLayout(haut, 2)

            dehors.addWidget(QLabel('<b>Consignes</b> — écrites dans le '
                                    'dossier d\'export, à côté des jobs :'))
            self.w_consignes = QTextBrowser()
            self.w_consignes.setStyleSheet(
                'font-family: Consolas, "Courier New", monospace;')
            dehors.addWidget(self.w_consignes, 3)

            boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                       | QDialogButtonBox.StandardButton.Cancel)
            self.w_ok = boutons.button(QDialogButtonBox.StandardButton.Ok)
            self.w_ok.setText('Exporter les morceaux')
            boutons.accepted.connect(self.accept)
            boutons.rejected.connect(self.reject)
            dehors.addWidget(boutons)
            self._recalculer()

        def _recalculer(self, *_) -> None:
            d = self.document
            b = d.bounds()
            self._plan = plan(b, d.field_w, d.field_h, self.w_marge.value())
            self.w_apercu.montrer(b, self._plan, (d.field_w, d.field_h))
            self.w_ok.setEnabled(bool(self._plan))
            if not b:
                self.w_titre.setText('Le document est vide.')
                return
            if not self._plan:
                nx, ny = compte(b, d.field_w, d.field_h, self.w_marge.value())
                n = f'{nx * ny:,}'.replace(',', ' ')
                plafond = f'{MAX_MORCEAUX:,}'.replace(',', ' ')
                self.w_titre.setText(
                    f'<b>Dessin de {b[2] - b[0]:.1f} × {b[3] - b[1]:.1f} mm</b> '
                    f'pour un champ de {d.field_w:g} × {d.field_h:g} mm — '
                    f'<b>{n} morceaux</b>, au plus {plafond}.')
                self.w_resume.setText(
                    f'{theme.span("alarm")}Trop de morceaux pour un '
                    'travail : des déplacements de la pièce par milliers. '
                    'Vérifiez l\'emprise du dessin — une forme égarée au '
                    'loin, un cadre démesuré.</span>')
                self.w_consignes.setPlainText('')
                return
            nx, ny = dimensions(self._plan)
            n = len(self._plan)
            self.w_titre.setText(
                f'<b>Dessin de {b[2] - b[0]:.1f} × {b[3] - b[1]:.1f} mm</b> '
                f'pour un champ de {d.field_w:g} × {d.field_h:g} mm — '
                f'<b>{n} morceau{"x" if n > 1 else ""}</b>, '
                f'{nx} × {ny}.')
            if n == 1:
                self.w_resume.setText(
                    f'{theme.span("ok")}Tout tient dans le champ utile : '
                    'un seul morceau, sans déplacement.</span>')
            else:
                self.w_resume.setText(
                    f'Morceaux de {self._plan[0].largeur:.1f} × '
                    f'{self._plan[0].hauteur:.1f} mm.<br>'
                    f'{n - 1} déplacement(s) de la pièce entre les '
                    'morceaux.')
            self.w_consignes.setPlainText(
                consignes(d, self._plan, self.stem, self.w_marge.value(),
                          self.w_marques.isChecked()))

        def plan(self) -> list[Morceau]:
            return list(self._plan)

        def marge(self) -> float:
            return float(self.w_marge.value())

        def marques(self) -> bool:
            return self.w_marques.isChecked()

    return MorceauxDialog


def dialogue(parent, document: Document, stem: str):
    """Construit le dialogue. Voir `_dialogue`."""
    return _dialogue()(parent, document, stem)
