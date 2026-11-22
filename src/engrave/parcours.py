"""Rejouer le parcours / Path replay.

Avant d'exporter, on voulait savoir **dans quel ordre** la machine
gravera : une plaque après l'autre, ou tous les codes puis tous les
textes ? le contour avant le remplissage ? Le plan de travail montre le
dessin, pas le parcours, et l'ordre de la liste n'est plus celui de la
gravure dès que l'ordonnancement s'en mêle.

*Affichage ▸ Rejouer le parcours* rejoue le travail **tel que l'export
l'écrira** — mêmes passes, même ordonnancement, même regroupement par
process, première pièce pour les champs variables — au rythme du modèle
de durée (`toolpath.polylines_duration_s`), accéléré à volonté :

* le dessin entier en grisé, ce qui est déjà gravé en couleur, la tête
  en rouge ;
* les sauts à vide en pointillés, qu'on peut masquer ;
* l'allumage en cours, sa process, ce qui est gravé et parcouru à vide,
  le temps écoulé sur le temps total ;
* lecture, pause, allumage précédent ou suivant, et la réglette pour
  aller où l'on veut.

**Rien n'est émis** : c'est une image, calculée ici, sans rien demander
à la machine.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from . import theme
from . import toolpath as T


@dataclass
class Etape:
    """Un allumage : le saut qui y mène, puis le trait."""
    poly: list
    depart: tuple[float, float]      # où était la tête avant le saut
    debut_s: float                   # début du saut
    allume_s: float                  # fin du saut, début du trait
    fin_s: float
    longueur_mm: float
    saut_mm: float
    passe: int
    process: str


def etapes(passes: list, start: tuple[float, float] = (0.0, 0.0),
           minimum_s: float = 0.0) -> list[Etape]:
    """Les allumages du travail, dans l'ordre, sur la ligne du temps.

    La durée de chacun est celle du modèle — saut, attente d'allumage,
    trait, rampes du SkyWrite —, si bien que la dernière fin tombe sur
    `toolpath.total_duration_s`. `minimum_s` donne une durée à une
    process à vitesse nulle, que le modèle compte pour rien et qu'on ne
    pourrait autrement pas parcourir.
    """
    sortie: list[Etape] = []
    t = 0.0
    curseur = start
    for rang, p in enumerate(passes):
        # comme `total_duration_s`, le curseur passe d'une passe à l'autre
        x, y = curseur
        curseur = p.end_point(curseur)
        vitesse = p.recipe.speed_mm_min
        v = min(vitesse, T.SPEED_MAX_MM_MIN) / 60.0
        for poly in p.polylines:
            if len(poly) < 2:
                continue
            duree = max(T.polylines_duration_s([poly], vitesse, (x, y)),
                        minimum_s)
            saut = math.hypot(poly[0][0] - x, poly[0][1] - y)
            vol = min(duree, T.move_time_s(saut, v)) if v > 0 else 0.0
            longueur = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                           for a, b in zip(poly, poly[1:]))
            sortie.append(Etape(poly, (x, y), t, t + vol, t + duree,
                                longueur, saut, rang, p.recipe.name))
            t += duree
            x, y = poly[-1]
    return sortie


def _troncon(poly: list, distance: float) -> list:
    """Le début de `poly`, sur `distance` mm."""
    sortie = [poly[0]]
    reste = distance
    for a, b in zip(poly, poly[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d >= reste:
            f = reste / d if d > 0 else 0.0
            sortie.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
            return sortie
        sortie.append(b)
        reste -= d
    return sortie


@dataclass
class Etat:
    """Où en est le travail à un instant donné."""
    faits: int                       # allumages achevés
    tete: tuple[float, float]
    partiel: list                    # trait en cours, déjà gravé
    en_vol: bool                     # la tête saute, laser éteint
    grave_mm: float
    vide_mm: float
    process: str


class Parcours:
    """Les étapes, et de quoi dire l'état à tout instant."""

    def __init__(self, passes: list, start: tuple[float, float] = (0.0, 0.0),
                 minimum_s: float = 0.0) -> None:
        self.start = start
        self.etapes = etapes(passes, start, minimum_s)
        self.fins = [e.fin_s for e in self.etapes]
        self.duree_s = self.fins[-1] if self.fins else 0.0
        self._graves = [0.0]
        self._vides = [0.0]
        for e in self.etapes:
            self._graves.append(self._graves[-1] + e.longueur_mm)
            self._vides.append(self._vides[-1] + e.saut_mm)
        self.grave_total_mm = self._graves[-1]
        self.vide_total_mm = self._vides[-1]

    def etat(self, t: float) -> Etat:
        k = bisect.bisect_right(self.fins, t)
        if k >= len(self.etapes):
            fin = self.etapes[-1].poly[-1] if self.etapes else self.start
            return Etat(len(self.etapes), fin, [], False,
                        self.grave_total_mm, self.vide_total_mm,
                        self.etapes[-1].process if self.etapes else '')
        e = self.etapes[k]
        if t < e.allume_s:
            f = ((t - e.debut_s) / (e.allume_s - e.debut_s)
                 if e.allume_s > e.debut_s else 1.0)
            f = min(1.0, max(0.0, f))
            tete = (e.depart[0] + f * (e.poly[0][0] - e.depart[0]),
                    e.depart[1] + f * (e.poly[0][1] - e.depart[1]))
            return Etat(k, tete, [], True, self._graves[k],
                        self._vides[k] + f * e.saut_mm, e.process)
        f = ((t - e.allume_s) / (e.fin_s - e.allume_s)
             if e.fin_s > e.allume_s else 1.0)
        partiel = _troncon(e.poly, min(1.0, max(0.0, f)) * e.longueur_mm)
        return Etat(k, partiel[-1], partiel, False,
                    self._graves[k] + f * e.longueur_mm, self._vides[k + 1],
                    e.process)

    def debut_de(self, k: int) -> float:
        """L'instant où commence l'allumage `k` — son saut compris."""
        if not self.etapes:
            return 0.0
        k = min(max(k, 0), len(self.etapes) - 1)
        return self.etapes[k].debut_s


def horloge(secondes: float) -> str:
    """« 1:05,3 » — assez fin pour suivre un allumage, assez court pour
    se lire en passant."""
    # arrondi d'abord : 59,96 s s'affichait « 0:60,0 »
    secondes = round(max(0.0, secondes), 1)
    minutes, reste = divmod(secondes, 60.0)
    if minutes >= 60:
        heures, minutes = divmod(int(minutes), 60)
        return f'{heures} h {minutes:02d}:{reste:04.1f}'.replace('.', ',')
    return f'{int(minutes)}:{reste:04.1f}'.replace('.', ',')


class VueParcours(QWidget):
    """Le dessin, ce qui est gravé, et la tête.

    Deux images tenues à jour plutôt qu'un dessin complet à chaque
    image : le grisé, refait seulement quand la vue change de taille, et
    ce qui est gravé, **prolongé** d'un allumage à l'autre — trois cents
    plaques hachurées font des dizaines de milliers de traits.
    """

    def __init__(self, parcours: Parcours,
                 champ: tuple[float, float] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.parcours = parcours
        self.champ = champ
        self.sauts = True
        self.setMinimumSize(420, 320)
        self._t = 0.0
        self._etat = parcours.etat(0.0)
        self._fond: QPixmap | None = None
        self._grave: QPixmap | None = None
        self._dans_grave = 0                 # allumages déjà dans `_grave`
        pts = [pt for e in parcours.etapes for pt in e.poly]
        pts.append(parcours.start)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self._boite = (min(xs), min(ys), max(xs), max(ys))

    # -- repère -----------------------------------------------------------

    def _repere(self):
        x1, y1, x2, y2 = self._boite
        w, h = max(x2 - x1, 1e-6), max(y2 - y1, 1e-6)
        marge = 16
        k = min((self.width() - 2 * marge) / w,
                (self.height() - 2 * marge) / h)
        ox = (self.width() - k * w) / 2 - k * x1
        oy = (self.height() + k * h) / 2 + k * y1
        return k, ox, oy

    def _point(self, p) -> QPointF:
        k, ox, oy = self._repere()
        return QPointF(ox + k * p[0], oy - k * p[1])

    def _chemin(self, polys) -> QPainterPath:
        k, ox, oy = self._repere()
        chemin = QPainterPath()
        for poly in polys:
            chemin.moveTo(ox + k * poly[0][0], oy - k * poly[0][1])
            for x, y in poly[1:]:
                chemin.lineTo(ox + k * x, oy - k * y)
        return chemin

    # -- images -----------------------------------------------------------

    def _image(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        # arrondi par excès : tronquée, l'image laissait à 125 % une
        # bande non peinte à droite et en bas
        image = QPixmap(math.ceil(self.width() * ratio),
                        math.ceil(self.height() * ratio))
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.transparent)
        return image

    def _peindre_fond(self) -> None:
        p = theme.current()
        self._fond = self._image()
        self._fond.fill(QColor(p.canvas))
        peintre = QPainter(self._fond)
        peintre.setRenderHint(QPainter.Antialiasing)
        if self.champ:
            w, h = self.champ
            a, b = self._point((-w / 2, h / 2)), self._point((w / 2, -h / 2))
            peintre.setPen(QPen(QColor(p.field), 1, Qt.DashLine))
            peintre.drawRect(QRectF(a, b))
        # l'origine, d'où part le premier saut
        o = self._point(self.parcours.start)
        peintre.setPen(QPen(QColor(p.text_dim), 1))
        peintre.drawLine(o + QPointF(-5, 0), o + QPointF(5, 0))
        peintre.drawLine(o + QPointF(0, -5), o + QPointF(0, 5))
        gris = QColor(p.path)
        gris.setAlpha(70)
        peintre.setPen(QPen(gris, 1))
        peintre.drawPath(self._chemin(e.poly for e in self.parcours.etapes))
        peintre.end()

    def _prolonger_grave(self, jusqua: int) -> None:
        """Porte dans l'image du gravé les allumages achevés jusqu'à
        `jusqua` — ou la refait, si l'on est revenu en arrière."""
        if self._grave is None or jusqua < self._dans_grave:
            self._grave = self._image()
            self._dans_grave = 0
        if jusqua == self._dans_grave:
            return
        p = theme.current()
        lot = self.parcours.etapes[self._dans_grave:jusqua]
        peintre = QPainter(self._grave)
        peintre.setRenderHint(QPainter.Antialiasing)
        if self.sauts:
            saut = QColor(p.text_dim)
            saut.setAlpha(140)
            peintre.setPen(QPen(saut, 1, Qt.DotLine))
            peintre.drawPath(self._chemin([e.depart, e.poly[0]] for e in lot
                                          if e.saut_mm > 0))
        peintre.setPen(QPen(QColor(p.accent), 1.5))
        peintre.drawPath(self._chemin(e.poly for e in lot))
        peintre.end()
        self._dans_grave = jusqua

    # -- état ---------------------------------------------------------------

    def set_temps(self, t: float) -> Etat:
        self._t = t
        self._etat = self.parcours.etat(t)
        self.update()
        return self._etat

    def set_sauts(self, montrer: bool) -> None:
        self.sauts = montrer
        self._grave = None
        self.update()

    def resizeEvent(self, event) -> None:
        self._fond = self._grave = None
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        # la fenêtre a changé d'écran, et d'échelle : sans changer de
        # taille, les images gardaient l'ancienne et devenaient floues
        if (self._fond is not None
                and self._fond.devicePixelRatio() != self.devicePixelRatioF()):
            self._fond = self._grave = None
        if self._fond is None:
            self._peindre_fond()
        self._prolonger_grave(self._etat.faits)
        p = theme.current()
        peintre = QPainter(self)
        peintre.drawPixmap(0, 0, self._fond)
        peintre.drawPixmap(0, 0, self._grave)
        peintre.setRenderHint(QPainter.Antialiasing)
        etat = self._etat
        if etat.en_vol and self.sauts and etat.faits < len(
                self.parcours.etapes):
            depart = self.parcours.etapes[etat.faits].depart
            peintre.setPen(QPen(QColor(p.warn), 1, Qt.DashLine))
            peintre.drawLine(self._point(depart), self._point(etat.tete))
        if len(etat.partiel) >= 2:
            peintre.setPen(QPen(QColor(p.accent), 2.5))
            peintre.drawPath(self._chemin([etat.partiel]))
        peintre.setPen(Qt.NoPen)
        peintre.setBrush(QColor(p.alarm))
        peintre.drawEllipse(self._point(etat.tete), 4.0, 4.0)
        peintre.end()


#: Facteurs d'accélération proposés.
VITESSES = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000)

#: Durée visée d'une lecture entière au facteur proposé d'office.
LECTURE_S = 20.0


class ParcoursDialog(QDialog):
    """Lecture du parcours — voir l'en-tête du module."""

    PAS = 10000                       # crans de la réglette

    def __init__(self, parent, passes: list,
                 champ: tuple[float, float] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Rejouer le parcours')
        self.parcours = Parcours(passes, minimum_s=1e-4)
        self.t = 0.0
        self.vue = VueParcours(self.parcours, champ, self)

        self.w_regle = QSlider(Qt.Horizontal)
        self.w_regle.setRange(0, self.PAS)
        self.w_regle.valueChanged.connect(self._regle_bougee)
        self.w_prec = QPushButton('◀ Précédent')
        self.w_prec.clicked.connect(lambda: self._sauter(-1))
        self.w_lire = QPushButton('▶ Lecture')
        self.w_lire.clicked.connect(self._basculer)
        self.w_suiv = QPushButton('Suivant ▶')
        self.w_suiv.clicked.connect(lambda: self._sauter(+1))
        self.w_vitesse = QComboBox()
        for v in VITESSES:
            self.w_vitesse.addItem('temps réel' if v == 1 else f'× {v}', v)
        propose = next((i for i, v in enumerate(VITESSES)
                        if self.parcours.duree_s / v <= LECTURE_S),
                       len(VITESSES) - 1)
        self.w_vitesse.setCurrentIndex(propose)
        self.w_vitesse.setToolTip('Accélération de la lecture ; le temps '
                                  'affiché reste celui de la machine')
        self.w_sauts = QCheckBox('Sauts à vide')
        self.w_sauts.setChecked(True)
        self.w_sauts.toggled.connect(self.vue.set_sauts)
        self.w_info = QLabel()
        self.w_info.setStyleSheet(theme.css('text_dim'))

        # Espace et les flèches sont au dialogue : laissés aux enfants, la
        # réglette prenait les flèches au dix-millième, Espace repressait
        # le dernier bouton cliqué et Entrée « Précédent ». La souris
        # garde tout ; le clavier n'a qu'un destinataire.
        for w in (self.w_prec, self.w_lire, self.w_suiv, self.w_regle,
                  self.w_vitesse, self.w_sauts):
            w.setFocusPolicy(Qt.NoFocus)
        for w in (self.w_prec, self.w_lire, self.w_suiv):
            w.setAutoDefault(False)
        self.setFocusPolicy(Qt.StrongFocus)

        boutons = QHBoxLayout()
        for w in (self.w_prec, self.w_lire, self.w_suiv):
            boutons.addWidget(w)
        boutons.addStretch(1)
        boutons.addWidget(self.w_sauts)
        boutons.addWidget(self.w_vitesse)
        mise = QVBoxLayout(self)
        mise.addWidget(self.vue, 1)
        mise.addWidget(self.w_regle)
        mise.addLayout(boutons)
        mise.addWidget(self.w_info)

        self._horloge = QElapsedTimer()
        self._minuteur = QTimer(self)
        self._minuteur.setInterval(30)
        self._minuteur.timeout.connect(self._avancer)
        self.resize(900, 680)
        self._montrer()

    # -- lecture ------------------------------------------------------------

    def _basculer(self) -> None:
        if self._minuteur.isActive():
            self._minuteur.stop()
        else:
            if self.t >= self.parcours.duree_s:
                self.t = 0.0
            self._horloge.start()
            self._minuteur.start()
        self._montrer()

    def _avancer(self, dt_s: float | None = None) -> None:
        """Un pas de lecture : `dt_s` de temps réel, ou ce qui s'est
        écoulé depuis le pas précédent."""
        if dt_s is None:
            dt_s = self._horloge.restart() / 1000.0
        self.t = min(self.parcours.duree_s,
                     self.t + dt_s * self.w_vitesse.currentData())
        if self.t >= self.parcours.duree_s:
            self._minuteur.stop()
        self._montrer()

    def _sauter(self, sens: int) -> None:
        """Au début de l'allumage suivant ou précédent."""
        n = len(self.parcours.etapes)
        k = self.parcours.etat(self.t).faits
        if sens < 0:
            if k >= n or self.t <= self.parcours.debut_de(k) + 1e-12:
                k -= 1
            self.t = self.parcours.debut_de(max(k, 0))
        elif k + 1 >= n:
            self.t = self.parcours.duree_s
        else:
            self.t = self.parcours.debut_de(k + 1)
        self._montrer()

    def _regle_bougee(self, valeur: int) -> None:
        if self.w_regle.signalsBlocked():
            return
        self.t = self.parcours.duree_s * valeur / self.PAS
        self._montrer()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self._basculer()
        elif event.key() == Qt.Key_Left:
            self._sauter(-1)
        elif event.key() == Qt.Key_Right:
            self._sauter(+1)
        else:
            super().keyPressEvent(event)

    def _montrer(self) -> None:
        etat = self.vue.set_temps(self.t)
        total = self.parcours.duree_s
        self.w_regle.blockSignals(True)
        self.w_regle.setValue(int(round(self.PAS * self.t / total))
                              if total > 0 else 0)
        self.w_regle.blockSignals(False)
        self.w_lire.setText('⏸ Pause' if self._minuteur.isActive()
                            else '▶ Lecture')
        n = len(self.parcours.etapes)
        en_cours = min(etat.faits + 1, n)
        self.w_info.setText(
            f'Allumage {en_cours} / {n} · process « {etat.process} » · '
            f'gravé {etat.grave_mm:.0f} / '
            f'{self.parcours.grave_total_mm:.0f} mm · à vide '
            f'{etat.vide_mm:.0f} mm · {horloge(self.t)} / {horloge(total)}'
            + (' · saut' if etat.en_vol else ''))

    def done(self, code: int) -> None:
        self._minuteur.stop()
        super().done(code)
