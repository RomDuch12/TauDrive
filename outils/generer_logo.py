"""Génère le logo et l'icône de TauDrive.

Le logo est un **tau grec majuscule (Τ)** dont la barre verticale se
prolonge en faisceau laser convergent vers un point de focalisation — la
lettre et l'outil dans le même trait.

Produit :
    ressources/taudrive.ico   icône multi-résolutions (16 à 256 px)
    ressources/taudrive.png   logo 512 px, fond transparent
    ressources/taudrive_sombre.png  variante sur fond sombre

Usage : python generer_logo.py
"""
from __future__ import annotations

import pathlib
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'ressources'

AMBER = QColor(255, 176, 32)
AMBER_HOT = QColor(255, 226, 150)
CYAN = QColor(90, 200, 250)
INK = QColor(22, 26, 32)
PLATE = QColor(38, 44, 54)


def draw(size: int, with_plate: bool = True) -> QImage:
    """Dessine le logo dans une image carrée de `size` pixels."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    u = size / 100.0                      # unité : 1 % du côté

    # --- plaque de fond, coins arrondis ---
    if with_plate:
        plate = QRectF(4 * u, 4 * u, 92 * u, 92 * u)
        grad = QLinearGradient(plate.topLeft(), plate.bottomRight())
        grad.setColorAt(0.0, PLATE)
        grad.setColorAt(1.0, INK)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(70, 80, 95), max(1.0, 1.2 * u)))
        p.drawRoundedRect(plate, 18 * u, 18 * u)

    # --- faisceau : cône descendant depuis la hampe du tau ---
    beam = QPainterPath()
    beam.moveTo(43 * u, 58 * u)
    beam.lineTo(57 * u, 58 * u)
    beam.lineTo(51.6 * u, 84 * u)
    beam.lineTo(48.4 * u, 84 * u)
    beam.closeSubpath()
    bg = QLinearGradient(QPointF(50 * u, 58 * u), QPointF(50 * u, 84 * u))
    bg.setColorAt(0.0, QColor(CYAN.red(), CYAN.green(), CYAN.blue(), 190))
    bg.setColorAt(1.0, QColor(CYAN.red(), CYAN.green(), CYAN.blue(), 25))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(bg))
    p.drawPath(beam)

    # --- point de focalisation ---
    focus = QRadialGradient(QPointF(50 * u, 84.5 * u), 9 * u)
    focus.setColorAt(0.0, AMBER_HOT)
    focus.setColorAt(0.35, QColor(AMBER.red(), AMBER.green(), AMBER.blue(), 200))
    focus.setColorAt(1.0, QColor(AMBER.red(), AMBER.green(), AMBER.blue(), 0))
    p.setBrush(QBrush(focus))
    p.drawEllipse(QPointF(50 * u, 84.5 * u), 9 * u, 9 * u)

    # --- le tau : barre horizontale + hampe ---
    tau = QPainterPath()
    tau.addRect(QRectF(22 * u, 20 * u, 56 * u, 11 * u))     # barre
    tau.addRect(QRectF(44.5 * u, 31 * u, 11 * u, 30 * u))   # hampe
    tg = QLinearGradient(QPointF(0, 20 * u), QPointF(0, 61 * u))
    tg.setColorAt(0.0, QColor(245, 249, 255))
    tg.setColorAt(1.0, QColor(196, 214, 236))
    p.setBrush(QBrush(tg))
    p.drawPath(tau)

    # --- empattements, pour asseoir la lettre ---
    p.setBrush(QBrush(QColor(245, 249, 255)))
    p.drawRect(QRectF(22 * u, 31 * u, 5 * u, 5 * u))
    p.drawRect(QRectF(73 * u, 31 * u, 5 * u, 5 * u))

    p.end()
    return img


def main() -> int:
    QGuiApplication(sys.argv[:1])
    OUT.mkdir(parents=True, exist_ok=True)

    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = [draw(s) for s in sizes]

    # Qt n'écrit qu'une seule résolution dans un .ico : on passe par Pillow,
    # qui construit le conteneur multi-résolutions attendu par Windows.
    ico = OUT / 'taudrive.ico'
    tmp = OUT / '_ico_source.png'
    images[-1].save(str(tmp), 'PNG')
    try:
        from PIL import Image
        with Image.open(tmp) as src:
            src.save(ico, format='ICO', sizes=[(s, s) for s in sizes])
        ok = True
    except ImportError:
        ok = images[-1].save(str(ico), 'ICO')
        print('   (Pillow absent : icône à une seule résolution)')
    finally:
        tmp.unlink(missing_ok=True)
    print(f'{ico.name:<24} {"écrit" if ok else "ÉCHEC"}')

    png = OUT / 'taudrive.png'
    print(f'{png.name:<24} {"écrit" if draw(512).save(str(png), "PNG") else "ÉCHEC"}')

    flat = OUT / 'taudrive_marque.png'
    print(f'{flat.name:<24} '
          f'{"écrit" if draw(512, with_plate=False).save(str(flat), "PNG") else "ÉCHEC"}')

    for s, img in zip(sizes, images):
        img.save(str(OUT / f'apercu_{s}.png'), 'PNG')
    print(f'aperçus : {", ".join(str(s) for s in sizes)} px')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
