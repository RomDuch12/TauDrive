"""Icônes vectorielles de TauDrive / TauDrive vector icons.

Dessinées au `QPainter` plutôt que chargées depuis des fichiers : elles
suivent la couleur du thème, restent nettes à toute résolution et
n'ajoutent aucune ressource externe à embarquer.

    icon('rectangle')            couleur du thème courant
    icon('supprimer', ALARM)     couleur imposée
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

#: Taille de dessin. Les icônes sont redimensionnées par Qt si besoin.
SIZE = 22


def _pen(color: QColor, width: float = 1.8) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _rectangle(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRect(QRectF(4, 6, 14, 10))


def _texte(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 2.0))
    p.drawLine(5, 6, 17, 6)          # barre du T
    p.drawLine(11, 6, 11, 17)        # hampe
    p.setPen(_pen(c, 1.4))
    p.drawLine(8, 17, 14, 17)        # empattement


def _dxf(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(4, 16))
    path.lineTo(8, 8)
    path.lineTo(12, 13)
    path.lineTo(18, 5)
    p.drawPath(path)
    p.setPen(_pen(c, 1.3))
    p.drawLine(4, 19, 18, 19)


def _dupliquer(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.drawRect(QRectF(4, 4, 10, 10))
    p.setPen(_pen(c))
    p.drawRect(QRectF(8, 8, 10, 10))


def _supprimer(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawLine(5, 7, 17, 7)                  # couvercle
    p.drawLine(9, 4, 13, 4)                  # poignée
    path = QPainterPath(QPointF(6, 7))
    path.lineTo(7, 18)
    path.lineTo(15, 18)
    path.lineTo(16, 7)
    p.drawPath(path)
    p.setPen(_pen(c, 1.2))
    p.drawLine(9, 10, 9, 15)
    p.drawLine(13, 10, 13, 15)


def _ajuster(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    for x0, y0, x1, y1, x2, y2 in (
            (4, 8, 4, 4, 8, 4), (18, 8, 18, 4, 14, 4),
            (4, 14, 4, 18, 8, 18), (18, 14, 18, 18, 14, 18)):
        p.drawLine(x0, y0, x1, y1)
        p.drawLine(x1, y1, x2, y2)
    p.setPen(_pen(c, 1.2))
    p.drawRect(QRectF(8, 8, 6, 6))


def _exporter(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawLine(11, 4, 11, 13)
    path = QPainterPath(QPointF(7, 9))       # pointe de flèche
    path.lineTo(11, 13)
    path.lineTo(15, 9)
    p.drawPath(path)
    p.drawLine(4, 17, 18, 17)
    p.drawLine(4, 13, 4, 17)
    p.drawLine(18, 13, 18, 17)


def _envoyer(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(4, 11))
    path.lineTo(18, 4)
    path.lineTo(12, 18)
    path.lineTo(10, 12)
    path.closeSubpath()
    p.drawPath(path)


def _lancer(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(7, 4))
    path.lineTo(18, 11)
    path.lineTo(7, 18)
    path.closeSubpath()
    p.drawPath(path)


def _theme(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QPointF(11, 11), 7, 7)
    p.setBrush(c)
    path = QPainterPath()
    path.moveTo(11, 4)
    path.arcTo(QRectF(4, 4, 14, 14), 90, -180)
    path.closeSubpath()
    p.drawPath(path)


def _cercle(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QPointF(11, 11), 7, 7)


def _grouper(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.drawRect(QRectF(4, 4, 7, 7))
    p.drawRect(QRectF(11, 11, 7, 7))
    p.setPen(_pen(c, 1.1))                   # cadre englobant, en pointillé
    pen = p.pen()
    pen.setStyle(Qt.DotLine)
    p.setPen(pen)
    p.drawRect(QRectF(2, 2, 18, 18))


def _degrouper(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.drawRect(QRectF(3, 3, 7, 7))
    p.drawRect(QRectF(12, 12, 7, 7))
    p.setPen(_pen(c, 1.2))                   # les deux s'écartent
    p.drawLine(13, 4, 18, 4)
    p.drawLine(4, 18, 9, 18)


def _redimensionner(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.3))
    p.drawRect(QRectF(3, 3, 9, 9))
    p.setPen(_pen(c))
    p.drawRect(QRectF(8, 8, 11, 11))
    path = QPainterPath(QPointF(13, 18))     # flèche diagonale
    path.lineTo(18, 13)
    p.drawPath(path)
    p.drawLine(18, 13, 18, 16)
    p.drawLine(15, 13, 18, 13)


def _nouveau(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(6, 3))       # feuille au coin plié
    path.lineTo(13, 3)
    path.lineTo(17, 7)
    path.lineTo(17, 19)
    path.lineTo(6, 19)
    path.closeSubpath()
    p.drawPath(path)
    p.setPen(_pen(c, 1.2))
    p.drawLine(13, 3, 13, 7)
    p.drawLine(13, 7, 17, 7)


def _ouvrir(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(3, 17))      # chemise ouverte
    path.lineTo(3, 6)
    path.lineTo(9, 6)
    path.lineTo(11, 9)
    path.lineTo(18, 9)
    p.drawPath(path)
    p.drawLine(3, 17, 19, 17)
    p.drawLine(18, 9, 19, 17)


def _enregistrer(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRect(QRectF(4, 4, 14, 14))         # disquette
    p.setPen(_pen(c, 1.2))
    p.drawRect(QRectF(7, 4, 8, 5))           # volet
    p.drawRect(QRectF(7, 12, 8, 6))          # étiquette


def _recettes(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    for y in (6, 11, 16):                    # curseurs de réglage
        p.drawLine(4, y, 18, y)
    p.setBrush(c)
    for x, y in ((8, 6), (14, 11), (10, 16)):
        p.drawEllipse(QPointF(x, y), 2.2, 2.2)
    p.setBrush(Qt.NoBrush)


def _code(p: QPainter, c: QColor) -> None:
    p.setBrush(c)
    p.setPen(Qt.NoPen)
    for x, y in ((3, 3), (3, 6), (6, 3),          # coin de repérage
                 (12, 3), (15, 3), (18, 3), (18, 6),
                 (3, 12), (3, 15), (3, 18), (6, 18),
                 (9, 9), (12, 12), (15, 9), (9, 15), (18, 15), (12, 18)):
        p.drawRect(QRectF(x - 1, y - 1, 2.6, 2.6))
    p.setBrush(Qt.NoBrush)


def _montage3(p: QPainter, c: QColor) -> None:
    """Trois DataMatrix empilés : le montage à trois postes.

    Chacun tient sur une grille de 5 × 3 cases — le L de repérage plein à
    gauche et en bas, le bord alterné en haut et à droite, une case
    dedans. C'est le minimum pour qu'un DataMatrix se reconnaisse ; en
    dessous, ce n'est plus qu'une tache grise.

    Le pas vaut **2 pixels entiers** : à 1,5 le motif tombait entre deux
    pixels, et les trois symboles ne se ressemblaient plus une fois
    tramés.
    """
    CASES = ((0, 0), (0, 1), (0, 2),              # montant du L
             (1, 2), (2, 2), (3, 2), (4, 2),      # base du L
             (1, 0), (3, 0),                      # bord alterné, en haut
             (4, 1),                              # bord alterné, à droite
             (2, 1))                              # la donnée, en réduction
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    for haut in (2, 9, 16):
        for i, j in CASES:
            p.drawRect(QRectF(5 + i * 2, haut + j * 2, 1.4, 1.4))
    p.setBrush(Qt.NoBrush)


def _gabarits(p: QPainter, c: QColor) -> None:
    """Un montage et ses trois postes : le gestionnaire de montages.

    Le plateau en trait, trois symboles pleins à gauche, la référence en
    clair en face de chacun — de quoi le distinguer du bouton qui pose,
    où les symboles sont seuls.
    """
    p.setPen(_pen(c, 1.3))
    p.drawRect(QRectF(2.5, 2.5, 17.0, 17.0))
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    for haut in (5.0, 9.5, 14.0):
        p.drawRect(QRectF(5.0, haut, 3.4, 3.0))
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, 1.2))
    for haut in (6.5, 11.0, 15.5):
        p.drawLine(QPointF(10.5, haut), QPointF(17.0, haut))


def _bibliotheque(p: QPainter, c: QColor) -> None:
    """Trois dessins rangés debout, comme des planches sur une étagère."""
    p.setPen(_pen(c, 1.4))
    for x, haut in ((4.0, 4.0), (9.0, 3.0), (14.0, 5.0)):
        p.drawRect(QRectF(x, haut, 3.6, 18.0 - haut))
    p.setPen(_pen(c, 1.6))
    p.drawLine(QPointF(2.5, 19.2), QPointF(19.5, 19.2))


def _enregistrer_recette(p: QPainter, c: QColor) -> None:
    """Disquette avec une goutte : enregistrer la process courante."""
    p.setPen(_pen(c, 1.5))
    p.drawRect(QRectF(3.5, 4.5, 12.0, 13.0))
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(6.0, 4.5, 7.0, 4.5))
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, 1.2))
    p.drawRect(QRectF(6.0, 11.5, 7.0, 6.0))
    path = QPainterPath(QPointF(18.0, 5.0))
    path.cubicTo(21.0, 9.0, 21.0, 11.5, 18.0, 11.5)
    path.cubicTo(15.0, 11.5, 15.0, 9.0, 18.0, 5.0)
    p.drawPath(path)


def _traiter(p: QPainter, c: QColor) -> None:
    """Un dessin et sa copie encadrée : l'original passe, la copie reste."""
    pale = QColor(c)
    pale.setAlphaF(0.45)
    p.setPen(_pen(pale, 1.3))
    p.drawEllipse(QRectF(2.5, 6.5, 8.0, 8.0))
    p.setPen(_pen(c, 1.5))
    p.drawRect(QRectF(11.0, 4.0, 9.5, 14.0))
    p.setPen(_pen(c, 1.3))
    p.drawEllipse(QRectF(13.0, 7.5, 5.5, 6.0))


def _date(p: QPainter, c: QColor) -> None:
    """Calendrier : la date du jour, posée automatiquement."""
    p.setPen(_pen(c, 1.5))
    p.drawRect(QRectF(3.5, 5.5, 15.0, 13.0))
    p.drawLine(QPointF(3.5, 9.5), QPointF(18.5, 9.5))
    p.setPen(_pen(c, 1.8))
    p.drawLine(QPointF(7.5, 3.0), QPointF(7.5, 7.0))
    p.drawLine(QPointF(14.5, 3.0), QPointF(14.5, 7.0))
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    for x, y in ((6.5, 12.0), (10.5, 12.0), (14.5, 12.0), (6.5, 15.5),
                 (10.5, 15.5)):
        p.drawRect(QRectF(x - 1.0, y - 1.0, 2.2, 2.2))
    p.setBrush(Qt.NoBrush)


def _lancer_export(p: QPainter, c: QColor) -> None:
    """Triangle plein, gros : le geste qui envoie le travail."""
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    triangle = QPainterPath(QPointF(5.0, 3.0))
    triangle.lineTo(19.5, 11.0)
    triangle.lineTo(5.0, 19.0)
    triangle.closeSubpath()
    p.drawPath(triangle)
    p.setBrush(Qt.NoBrush)


def _coupon(p: QPainter, c: QColor) -> None:
    """Grille d'essai : des cases de plus en plus remplies."""
    p.setPen(_pen(c, 1.2))
    for i, x in enumerate((3.5, 9.0, 14.5)):
        for j, y in enumerate((3.5, 9.0, 14.5)):
            case = QRectF(x, y, 4.0, 4.0)
            niveau = (i + j) / 4.0
            if niveau > 0:
                couleur = QColor(c)
                couleur.setAlphaF(min(1.0, 0.25 + niveau * 0.75))
                p.fillRect(case, couleur)
            p.drawRect(case)


def _verifier(p: QPainter, c: QColor) -> None:
    """Contrôle avant envoi : une liste, cochée."""
    p.setPen(_pen(c, 1.5))
    p.drawRect(QRectF(3.5, 3.5, 11.0, 15.0))
    p.setPen(_pen(c, 1.2))
    for y in (7.0, 10.0, 13.0):
        p.drawLine(QPointF(6.0, y), QPointF(12.0, y))
    pen = _pen(c, 2.4)
    p.setPen(pen)
    p.drawLine(QPointF(12.0, 14.5), QPointF(15.5, 18.0))
    p.drawLine(QPointF(15.5, 18.0), QPointF(20.0, 9.5))


def _plus(p: QPainter, c: QColor) -> None:
    """Croix d'ajout, tracée épaisse : elle se vise à bout de bras."""
    pen = _pen(c, 3.0)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(11, 4, 11, 18)
    p.drawLine(4, 11, 18, 11)


def _oeil(p: QPainter, c: QColor) -> None:
    """Œil ouvert : la forme est gravée."""
    p.setPen(_pen(c, 1.5))
    path = QPainterPath(QPointF(3, 11))
    path.cubicTo(7, 4, 15, 4, 19, 11)
    path.cubicTo(15, 18, 7, 18, 3, 11)
    p.drawPath(path)
    p.setBrush(c)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(11, 11), 2.6, 2.6)
    p.setBrush(Qt.NoBrush)


def _oeil_ferme(p: QPainter, c: QColor) -> None:
    """Œil fermé : la forme n'est ni affichée ni gravée."""
    p.setPen(_pen(c, 1.5))
    path = QPainterPath(QPointF(3, 9))
    path.cubicTo(7, 15, 15, 15, 19, 9)
    p.drawPath(path)
    p.setPen(_pen(c, 1.2))
    p.drawLine(5, 13, 3, 16)
    p.drawLine(11, 15, 11, 18)
    p.drawLine(17, 13, 19, 16)


def _annuler(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.7))
    path = QPainterPath(QPointF(5, 9))
    path.lineTo(9, 5)
    p.drawPath(path)
    path = QPainterPath(QPointF(5, 9))
    path.lineTo(9, 13)
    p.drawPath(path)
    path = QPainterPath(QPointF(5, 9))
    path.lineTo(13, 9)
    path.cubicTo(18, 9, 18, 17, 13, 17)
    p.drawPath(path)


def _refaire(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.7))
    path = QPainterPath(QPointF(17, 9))
    path.lineTo(13, 5)
    p.drawPath(path)
    path = QPainterPath(QPointF(17, 9))
    path.lineTo(13, 13)
    p.drawPath(path)
    path = QPainterPath(QPointF(17, 9))
    path.lineTo(9, 9)
    path.cubicTo(4, 9, 4, 17, 9, 17)
    p.drawPath(path)


def _pas(p: QPainter, c: QColor) -> None:
    """Croix à quatre flèches : le pas dont les flèches déplacent."""
    p.setPen(_pen(c, 1.5))
    p.drawLine(11, 4, 11, 18)
    p.drawLine(4, 11, 18, 11)
    for x, y, dx1, dy1, dx2, dy2 in (
            (11, 4, -3, 3, 3, 3),            # haut
            (11, 18, -3, -3, 3, -3),         # bas
            (4, 11, 3, -3, 3, 3),            # gauche
            (18, 11, -3, -3, -3, 3)):        # droite
        p.drawLine(x, y, x + dx1, y + dy1)
        p.drawLine(x, y, x + dx2, y + dy2)


def _feuille(p: QPainter, c: QColor, x: float = 7.0) -> None:
    """Feuille de dessin : le cadre et deux traits de tracé dedans."""
    p.setPen(_pen(c, 1.3))
    p.drawRect(QRectF(x, 3.5, 11, 15))
    p.setPen(_pen(c, 1.1))
    p.drawLine(QPointF(x + 2.5, 13), QPointF(x + 5, 8.5))
    p.drawLine(QPointF(x + 5, 8.5), QPointF(x + 8.5, 14.5))


def _fleche_h(p: QPainter, c: QColor, x1: float, x2: float, y: float) -> None:
    """Flèche horizontale de `x1` vers `x2`."""
    p.setPen(_pen(c, 2.0))
    p.drawLine(QPointF(x1, y), QPointF(x2, y))
    sens = 1.0 if x2 > x1 else -1.0
    p.drawLine(QPointF(x2, y), QPointF(x2 - 3 * sens, y - 3))
    p.drawLine(QPointF(x2, y), QPointF(x2 - 3 * sens, y + 3))


def _import_dessin(p: QPainter, c: QColor) -> None:
    """Flèche qui entre dans la feuille : un dessin vient du dehors."""
    _feuille(p, c, 9.0)
    _fleche_h(p, c, 1.5, 8.0, 11)


def _export_dessin(p: QPainter, c: QColor) -> None:
    """Flèche qui sort de la feuille : le dessin part vers un fichier."""
    _feuille(p, c, 2.0)
    _fleche_h(p, c, 14.0, 20.5, 11)


def _monter(p: QPainter, c: QColor) -> None:
    """Chevron vers le haut, sur sa barre : graver plus tôt."""
    p.setPen(_pen(c, 2.0))
    p.drawLine(5, 11, 11, 5)
    p.drawLine(11, 5, 17, 11)
    p.drawLine(11, 5, 11, 18)


def _descendre(p: QPainter, c: QColor) -> None:
    """Chevron vers le bas : graver plus tard."""
    p.setPen(_pen(c, 2.0))
    p.drawLine(5, 12, 11, 18)
    p.drawLine(11, 18, 17, 12)
    p.drawLine(11, 5, 11, 18)


def _dossier(p: QPainter, c: QColor) -> None:
    """Chemise fermée : le rayon d'une bibliothèque."""
    p.setPen(_pen(c, 1.4))
    path = QPainterPath(QPointF(3, 18))
    path.lineTo(3, 6)
    path.lineTo(9, 6)
    path.lineTo(11, 9)
    path.lineTo(19, 9)
    path.lineTo(19, 18)
    path.closeSubpath()
    p.drawPath(path)


def _couteau(p: QPainter, c: QColor) -> None:
    """Une lame, et le trait qu'elle épaissit.

    Deux traits parallèles autour d'un trait fin : c'est exactement ce que
    la fonction fait — une ligne devient le bord d'une bande.
    """
    p.setPen(_pen(c, 1.4))
    p.drawLine(3, 14, 19, 6)             # bord haut de la bande
    p.drawLine(3, 19, 19, 11)            # bord bas
    p.setPen(_pen(c, 0.9))
    p.drawLine(3, 16, 19, 8)             # le tracé, au milieu
    p.setPen(_pen(c, 1.4))
    p.drawLine(19, 6, 19, 11)            # le bout, net


DRAWINGS = {
    'couteau': _couteau,
    'pas': _pas,
    'monter': _monter,
    'descendre': _descendre,
    'import_dessin': _import_dessin,
    'export_dessin': _export_dessin,
    'dossier': _dossier,
    'rectangle': _rectangle,
    'annuler': _annuler,
    'refaire': _refaire,
    'oeil': _oeil,
    'oeil_ferme': _oeil_ferme,
    'plus': _plus,
    'coupon': _coupon,
    'lancer_export': _lancer_export,
    'date': _date,
    'traiter': _traiter,
    'enregistrer_process': _enregistrer_recette,
    'bibliotheque': _bibliotheque,
    'verifier': _verifier,
    'code': _code,
    'montage3': _montage3,
    'gabarits': _gabarits,
    'cercle': _cercle,
    'grouper': _grouper,
    'degrouper': _degrouper,
    'redimensionner': _redimensionner,
    'nouveau': _nouveau,
    'ouvrir': _ouvrir,
    'enregistrer': _enregistrer,
    'process': _recettes,
    'texte': _texte,
    'dxf': _dxf,
    'dupliquer': _dupliquer,
    'supprimer': _supprimer,
    'ajuster': _ajuster,
    'exporter': _exporter,
    'envoyer': _envoyer,
    'lancer': _lancer,
    'theme': _theme,
}

_CACHE: dict[tuple[str, str], QIcon] = {}


def icon(name: str, color: str | QColor | None = None) -> QIcon:
    """Icône `name`, teintée. Mémorisée par (nom, couleur)."""
    if color is None:
        from . import theme
        color = theme.current().text
    key = (name, QColor(color).name())
    hit = _CACHE.get(key)
    if hit is not None:
        return hit

    draw = DRAWINGS.get(name)
    if draw is None:
        return QIcon()

    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(Qt.NoBrush)
    draw(painter, QColor(color))
    painter.end()

    result = QIcon(pixmap)
    _CACHE[key] = result
    return result


def clear_cache() -> None:
    """À appeler lors d'un changement de thème."""
    _CACHE.clear()
