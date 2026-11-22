"""Application de gravure — interface PySide6.

Plan de travail en millimètres, repère machine (X droite, Y **haut**,
origine au centre du champ de marquage 110 × 110 mm de la TAU SMART).

Ce qui est affiché est la trajectoire réellement calculée — contour et
hachurage compris. Ce n'est pas une prévisualisation approchée.

Lancement :  python -m engrave.app        (depuis src)
             python TauDrive.py
"""
from __future__ import annotations

import dataclasses
import datetime
import html
import json
import pathlib
import sys
import time
from array import array

from PySide6.QtCore import (QEvent, QLibraryInfo, QPoint, QPointF, QRectF,
                            QSize, Qt, QTimer, QTranslator, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QPainter,
                           QPainterPath, QPainterPathStroker, QPen,
                           QPixmapCache, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox,
                               QToolButton, QWidgetAction,
                               QApplication, QCheckBox, QComboBox, QDialog,
                               QDockWidget,
                               QFileDialog, QFormLayout, QGraphicsItem,
                               QGraphicsPathItem, QGraphicsScene, QGraphicsView,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QInputDialog, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget,
                               QStatusBar, QTabWidget,
                               QVBoxLayout, QWidget)

from . import aimant, icons, iso, journal, preflight, recipes, resize
from . import serialize, session
from . import textvec, theme
from . import barcode, codeplate, codepresets, coupon, drawings
from . import cintrage
from . import conversion
from . import folders
from . import repetition
# le couteau place ses contours avec : sans cet import, il s'arrêtait
# sur une erreur dès qu'une sélection lui était donnée
from . import geometry as G
from . import knife
from . import toolpath
from . import montage
from . import montagepanel
from . import settingsio
from . import shellmenu
from . import splitting
from . import disposition
from . import vecexport
from . import dxfimport
from . import wobble
from . import datestamp, treatment
from . import variables
from .history import History
from .codeplate import build_plate, frames_of
from .widgets import Combo, GrowingText, IntSpin, Spin, TextBox
from .dxfdialog import DxfImportDialog
from . import helpbar
from .closedtabs import ClosedTabs, keywords as _keywords
from .lot import LotPanel
from . import librarypanel
from .librarypanel import DrawingLibrary
from .toolstore import ToolStorePanel
from .jobpanel import JobPanel
from .model import (FIELD_H_MM, FIELD_W_MM, RECIPE_LIBRARY,
                    SPEED_FROM_DISPLAY, SPEED_TO_DISPLAY, SPEED_UNIT,
                    Circle, Code, Document, Path, Rect, Recipe, Shape, Text,
                    preset_recipes, unreported_repairs)
from . import plugins
from .toolpath import (build_passes, code_size, geometry_key, group_zones,
                       local_polylines, total_duration_s, total_length_mm,
                       total_travel_mm)
from .avale import avale
from . import theme
from . import __version__

APP_NAME = session.APP_NAME
ORG_NAME = session.ORG_NAME

#: Version affichée dans le menu « ? » : celle du paquet
#: (`engrave/__init__.py`), qui nomme aussi les archives et les propriétés
#: Windows de l'exécutable.
VERSION = __version__
#: Machine visée. Le plugin d'un atelier peut nommer la sienne
#: (`plugins.Api.set_machine`) : c'est elle que dit *À propos*.
MACHINE = 'Cielle TAU 10×10 SMART'


def machine_label() -> str:
    """La machine de l'atelier si un plugin la nomme, le modèle sinon."""
    return plugins.REGISTRY.machine or MACHINE
#: À qui s'adresser. Seul contact affiché par l'application.
CONTACT = 'romduch@gmail.com'

#: Extension des documents TauDrive.
DOC_SUFFIX = '.taudrive'
DOC_FILTER = 'Documents TauDrive (*.taudrive);;Tous (*)'


def _luminance(couleur: str) -> float:
    c = [int(couleur[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
         for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contraste(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def resource_dir() -> pathlib.Path:
    """Dossier des ressources, en développement comme en version figée.

    PyInstaller déballe les données dans un dossier temporaire dont le
    chemin est publié via `sys._MEIPASS` ; le calcul relatif au fichier
    source ne vaut plus rien une fois l'application empaquetée.
    """
    base = getattr(sys, '_MEIPASS', None)
    if base:
        return pathlib.Path(base) / 'ressources'
    return pathlib.Path(__file__).resolve().parents[2] / 'ressources'


def settings():
    """Réglages persistants de l'application (choix du thème…)."""
    from PySide6.QtCore import QSettings
    return QSettings(ORG_NAME, APP_NAME)



def app_icon():
    """Icône de l'application, ou None si les ressources sont absentes."""
    from PySide6.QtGui import QIcon
    path = resource_dir() / 'taudrive.ico'
    return QIcon(str(path)) if path.exists() else None


_FONT_MODEL = None


#: Valeur portée par l'entrée « Ajouter un fichier de police… ».
FONT_PICK = '\x00ajouter'

#: La liste dont le modèle a été tiré. `available_fonts` rend **le même
#: objet** tant que rien n'a bougé : comparer l'identité est exact, là où
#: comparer le nombre manquait une police remplacée par une autre.
_FONT_SOURCE: tuple | None = None


def font_model():
    """Modèle des polices du poste, refait quand la liste a changé.

    Construit une seule fois **tant que rien ne bouge** : une police
    installée pendant que TauDrive tourne n'apparaissait jamais, pas
    même en rouvrant le formulaire. `textvec.available_fonts` surveille
    les dossiers ; il reste à refaire le modèle quand le compte change.
    """
    global _FONT_MODEL, _FONT_SOURCE
    from PySide6.QtGui import QStandardItem, QStandardItemModel
    polices = textvec.available_fonts()
    if _FONT_MODEL is None or polices is not _FONT_SOURCE:
        model = QStandardItemModel()
        first = QStandardItem('(par défaut)')
        first.setData('', Qt.UserRole)
        model.appendRow(first)
        for name, path in polices:
            item = QStandardItem(name)
            item.setData(path, Qt.UserRole)
            model.appendRow(item)
        # Dernière entrée : une police **reçue et non installée** se
        # désigne par son fichier. Windows n'offre alors que son bouton
        # « Installer », qui demande des droits qu'un poste d'atelier
        # verrouillé n'a pas.
        pick = QStandardItem('Ajouter un fichier de police…')
        pick.setData(FONT_PICK, Qt.UserRole)
        model.appendRow(pick)
        _FONT_MODEL, _FONT_SOURCE = model, polices
    return _FONT_MODEL


def forget_font_model() -> None:
    """Oblige le prochain formulaire à refaire la liste des polices."""
    global _FONT_MODEL, _FONT_SOURCE
    _FONT_MODEL, _FONT_SOURCE = None, None


def in_scroll(widget: QWidget, min_width: int = 240) -> QScrollArea:
    """Rend un panneau défilable.

    Sans cela, la hauteur minimale d'un panneau riche — l'inspecteur d'un
    texte en compte largement plus de 800 px — devient la hauteur minimale
    de la fenêtre, qui ne tient alors plus sur un écran 1080p.
    """
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setMinimumWidth(min_width)
    return area


MM = 1.0


# --------------------------------------------------------------------------
# Scène
# --------------------------------------------------------------------------

class ShapeItem(QGraphicsPathItem):
    """Représente une forme par ses trajectoires réelles.

    L'attribut porte volontairement le nom `entity` et non `shape` :
    `QGraphicsItem.shape()` est une méthode que Qt appelle pour la
    détection de clic, et un attribut du même nom la masquerait — la
    sélection à la souris cesserait de fonctionner.
    """

    #: Éléments au-delà desquels la zone de clic devient la boîte
    #: englobante.
    #:
    #: `QGraphicsPathItem.shape()` rend le **contour épaissi** du tracé, et
    #: Qt l'appelle à chaque mouvement de souris — survol, sélection au
    #: lasso, début de glissement. Sur un plan importé de 98 584 éléments,
    #: ce calcul coûte 34 ms : bouger la souris au-dessus du dessin plafonne
    #: alors à 29 images par seconde, et le déplacer devient impraticable.
    #:
    #: Au-delà du seuil, la boîte suffit — et vaut mieux. On ne clique pas
    #: *entre deux traits* d'un plan pour ne pas le sélectionner ; on clique
    #: le plan. En dessous, le contour exact reste utile : cliquer dans le
    #: creux d'un « O » ne doit pas prendre la lettre.
    HIT_TEST_MAX = 4000

    #: Largeur de la zone de clic d'un tracé, en millimètres — un demi
    #: de part et d'autre du trait.
    #:
    #: Un trait n'a pas d'épaisseur dans le modèle, et le faisceau en
    #: grave trois centièmes : viser cela à la souris est impossible.
    GRAB_MM = 2.0

    #: Éléments de tracé au-delà desquels la forme se peint **une fois**,
    #: dans une image à la résolution de l'écran, que la vue déplace
    #: ensuite sans la repeindre — voir `rebuild`.
    CACHE_FROM = 50_000

    #: Ce que Qt garde d'images d'items, en Ko, dès qu'une forme lourde
    #: est là. Sa limite d'origine, 10 Mo, ne tient pas l'image d'un grand
    #: écran : refaite à chaque fois, elle coûterait plus qu'un dessin
    #: direct. 64 Mo tiennent un plein écran 4K.
    PIXMAPS_KO = 64 * 1024

    def __init__(self, entity: Shape, on_moved, zone_of=None) -> None:
        super().__init__()
        self.entity = entity
        self._on_moved = on_moved
        #: Rend la part du groupe dans le remplissage de la forme — voir
        #: `toolpath.group_zones` ; et celle qui a servi au dernier tracé.
        self._zone_of = zone_of
        self.zone = None
        self._hit = None
        self.setFlags(QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setPen(QPen(QColor(theme.current().path), 0))
        #: Instant du dernier appui, et si le seuil de maintien est franchi.
        self._presse_t = 0.0
        self._traine = False
        #: Point de la scène où le geste a commencé, et ce qu'il emporte.
        self._ancre = None
        self._geste: _Geste | None = None
        self.rebuild()

    def restyle(self) -> None:
        p = theme.current()
        self.setPen(QPen(QColor(p.selected if self.isSelected() else p.path), 0))

    def rebuild(self) -> None:
        path = QPainterPath()
        self.zone = self._zone_of(self.entity) if self._zone_of else None
        for poly in local_polylines(self.entity, zone=self.zone, brut=True):
            if type(poly) is array:
                # une grosse entrée, telle qu'elle est rangée — x et y
                # alternés : la déplier d'abord doublait le temps de chaque
                # reconstruction, voir `toolpath._COMPACT_POINTS`
                if len(poly) < 4:
                    continue
                it = iter(poly)
                path.moveTo(next(it), next(it))
                for x, y in zip(it, it):
                    path.lineTo(x, y)
                continue
            if len(poly) < 2:
                continue
            path.moveTo(poly[0][0], poly[0][1])
            for x, y in poly[1:]:
                path.lineTo(x, y)
        self.setPath(path)
        # Une forme lourde — un texte oscillé, un million de points — se
        # repeignait entière à chaque image : 210 ms par pas de
        # défilement, cinq images par seconde, et autant pour la faire
        # glisser. Peinte une fois dans une image à la résolution de
        # l'écran — nette à 125 % comme à 100 % —, elle ne se repeint plus
        # qu'au zoom, à la sélection ou quand elle change : 1 ms par pas.
        # Le zoom coûte en échange un tiers de plus, l'image à remplir :
        # une forme légère se peint donc toujours directement.
        lourd = path.elementCount() > self.CACHE_FROM
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache if lourd
                          else QGraphicsItem.NoCache)
        if lourd and QPixmapCache.cacheLimit() < self.PIXMAPS_KO:
            QPixmapCache.setCacheLimit(self.PIXMAPS_KO)
        self._hit = None
        self.setPos(self.entity.x, self.entity.y)

    def shape(self):
        '''Zone de clic, calculée une fois et retenue.

        Qt appelle `shape()` à chaque mouvement de souris. La rendre à
        chaque fois revenait à épaissir cent mille segments soixante fois
        par seconde — voir `HIT_TEST_MAX`.

        **Un texte et un code se prennent par leur pavé entier.** La zone
        rendue par Qt est le contour des traits : cliquer « sur » un texte
        entre deux lettres, ou un DataMatrix entre deux modules, ne
        touchait rien — la sélection se vidait, et le clic suivant
        semblait aléatoire. Pour ces deux-là, le rectangle englobant est
        la bonne réponse : ce sont des pavés compacts, sans intérieur où
        l'on viserait autre chose.

        Les autres formes gardent leur contour, **élargi d'un millimètre
        de part et d'autre** (`GRAB_MM`, qui est la largeur totale) : un
        trait de trois centièmes ne se vise pas à la souris, et remplir
        l'intérieur d'un cadre lui ferait voler les clics destinés à ce
        qu'il entoure.
        '''
        if self._hit is None:
            if (isinstance(self.entity, (Text, Code))
                    or self.path().elementCount() > self.HIT_TEST_MAX):
                grossier = QPainterPath()
                grossier.addRect(self.boundingRect())
                self._hit = grossier
            else:
                # Le contour **seul**, sans l'unir au tracé : uni, un
                # cadre fermé devenait plein et volait les clics de tout
                # ce qu'il entoure.
                epais = QPainterPathStroker()
                epais.setWidth(self.GRAB_MM)
                self._hit = epais.createStroke(self.path())
        return self._hit

    # -- déplacement : il faut tenir le bouton -----------------------------
    #
    # Un clic simple ne doit **rien** déplacer. Sur un écran d'atelier, la
    # main qui vise n'est pas immobile : désigner une forme la décalait de
    # quelques centièmes sans que personne ne le voie, et la pièce partait
    # avec un repère hors cote. Le déplacement à la souris demande donc de
    # **tenir le bouton** — voir `DRAG_HOLD_MS`. Les flèches du clavier,
    # elles, restent le geste précis : un pas connu, annoncé dans la barre.

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._presse_t = time.monotonic()
            self._traine = False
            self._ancre = event.scenePos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if not self._traine:
            if (time.monotonic() - self._presse_t) * 1000.0 < DRAG_HOLD_MS:
                event.accept()          # trop tôt : on ne bouge pas
                return
            # Le seuil vient d'être franchi : on repart de la position
            # **courante**, sinon la forme sauterait du parcours déjà fait.
            self._traine = True
            self._ancre = event.scenePos()
            self.setCursor(Qt.ClosedHandCursor)
            self._geste = self._commencer_geste()
        # Le déplacement se compte depuis le début du geste, et non d'un
        # mouvement au suivant : l'aimant corrige la position, et sa
        # correction ne s'accumule pas d'un mouvement à l'autre.
        brut = event.scenePos() - self._ancre
        dx, dy = brut.x(), brut.y()
        geste = self._geste
        vue = self._vue()
        gx = gy = None
        if (geste.aimant and vue is not None
                and not (event.modifiers() & Qt.AltModifier)):
            portee = aimant.PORTEE_PX / max(abs(vue.transform().m11()), 1e-9)
            dx, gx = aimant.accroche(geste.prises_x, geste.cibles_x, dx,
                                     portee)
            dy, gy = aimant.accroche(geste.prises_y, geste.cibles_y, dy,
                                     portee)
        # Qt déplaçait lui-même toutes les formes sélectionnées ; c'est
        # maintenant à nous de le faire, sans quoi un groupe se déchirerait.
        for item, x0, y0 in geste.departs:
            item.setPos(x0 + dx, y0 + dy)
        if vue is not None:
            vue.montrer_guides(gx, gy)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._traine:
            self._traine = False
            self.unsetCursor()
            vue = self._vue()
            if vue is not None:
                vue.montrer_guides(None, None)
        super().mouseReleaseEvent(event)

    def _vue(self):
        """Le plan de travail qui montre la forme, s'il y en a un."""
        scene = self.scene()
        vues = scene.views() if scene is not None else []
        return vues[0] if vues and isinstance(vues[0], Canvas) else None

    def _commencer_geste(self) -> '_Geste':
        """Ce qu'emporte le geste, d'où chaque forme part, et — l'aimant
        actif — les prises de l'ensemble et ce à quoi elles peuvent
        s'accrocher. Mesuré une fois par geste : trois cents plaques ne
        se remesurent pas à chaque mouvement de souris."""
        bouges = [i for i in self.scene().selectedItems()
                  if isinstance(i, ShapeItem)] or [self]
        vue = self._vue()
        geste = _Geste([(i, i.pos().x(), i.pos().y()) for i in bouges],
                       vue is not None and session.aimant())
        emprises = [i.sceneBoundingRect() for i in bouges
                    if not i.path().isEmpty()]
        if geste.aimant and emprises:
            geste.prises_x = aimant.traits(min(r.left() for r in emprises),
                                           max(r.right() for r in emprises))
            geste.prises_y = aimant.traits(min(r.top() for r in emprises),
                                           max(r.bottom() for r in emprises))
            geste.cibles_x, geste.cibles_y = vue.cibles_aimant(
                {i.entity.id for i in bouges})
        return geste

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.entity.x = self.pos().x()
            self.entity.y = self.pos().y()
            self._on_moved()
        elif change == QGraphicsItem.ItemSelectedChange:
            p = theme.current()
            self.setPen(QPen(QColor(p.selected if value else p.path), 0))
        return super().itemChange(change, value)


@dataclasses.dataclass
class _Geste:
    """Un déplacement à la souris en cours — voir `ShapeItem`."""
    departs: list                         # (forme, x, y) au début du geste
    aimant: bool
    prises_x: tuple = ()
    prises_y: tuple = ()
    cibles_x: list = dataclasses.field(default_factory=list)
    cibles_y: list = dataclasses.field(default_factory=list)


#: Pas de déplacement au clavier, en millimètres, à l'ouverture. Il se
#: tape ensuite dans son champ — Ctrl+flèche y mène.
NUDGE_DEFAULT = 1.0

#: Délai avant de reposer le focus dans un champ qui vient de l'avoir
#: perdu, en millisecondes. Le temps que la séquence de souris s'éteigne.
RECLAIM_FOCUS_MS = 150

#: Durée de maintien du bouton avant qu'une forme ne suive la souris, en
#: millisecondes.
#:
#: Un clic plus court ne déplace **rien** : il désigne, et c'est tout.
#: Désigner une forme la décalait de quelques centièmes — la main qui
#: vise n'est pas immobile — et la pièce partait avec un repère hors
#: cote, sans que rien ne l'annonce. Six cents millisecondes se tiennent
#: sans y penser quand on veut vraiment traîner une forme, et ne
#: s'atteignent jamais par accident.
DRAG_HOLD_MS = 600

#: Côté et retrait du bouton d'ajustement, posé en surcouche du plan de
#: travail. Assez grand pour être visé à bout de bras sur un écran
#: d'atelier, assez discret pour ne pas manger le dessin.
FIT_BUTTON = 32
FIT_MARGIN = 12

#: Largeur du champ « Pas clavier », en pixels.
#:
#: Un nombre à trois chiffres et son unité, rien de plus. Laissé
#: extensible, il prenait la moitié de la barre d'outils.
STEP_FIELD_W = 108


class Canvas(QGraphicsView):
    """Plan de travail. Y vers le haut, unités millimètre."""

    selection_changed = Signal()
    geometry_changed = Signal()
    step_changed = Signal(float)
    #: Ctrl+flèche : on veut **taper** le pas, dans son champ.
    step_focus_requested = Signal()
    #: Double-clic sur un texte ou un code : on veut en taper le contenu.
    edit_requested = Signal(str)

    def __init__(self, document: Document | None,
                 monter: bool = True) -> None:
        super().__init__()
        self.document = document
        self.nudge_step = NUDGE_DEFAULT
        self.setFocusPolicy(Qt.StrongFocus)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor(theme.current().canvas)))
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        # Y vers le haut
        self.setTransform(QTransform().scale(4, -4))
        self._items: dict[str, ShapeItem] = {}
        #: Parts des groupes dans les remplissages, pour tout le plan ;
        #: None tant qu'elles sont à recalculer.
        self._zones: dict | None = None
        self._expanding = False
        #: Forme réellement désignée, par opposition à celles que le groupe
        #: a entraînées avec elle. C'est elle que montre l'inspecteur.
        self._primary: str = ''
        #: Lignes de repère de l'aimant, posées au premier besoin.
        self._guides: tuple | None = None
        #: Faux tant que le décor et les formes ne sont pas posés — un
        #: onglet restauré attend d'être montré, voir `monter`.
        self.monte = monter
        self._decor = []
        if monter:
            self._draw_field()
        self._scene.selectionChanged.connect(self._selection_touched)
        self._build_fit_button()
        if monter:
            self.reload()

    def monter(self) -> bool:
        """Pose le décor et les formes d'un onglet qui attendait. Vrai
        s'il restait à le faire.

        Les formes sont posées signaux coupés : les poser n'est pas une
        modification, et `geometry_changed` marquerait d'une étoile un
        document qu'on vient seulement de regarder.
        """
        if self.monte:
            return False
        self.monte = True
        self._draw_field()
        coupe = self.blockSignals(True)
        try:
            self.reload()
        finally:
            self.blockSignals(coupe)
        QTimer.singleShot(0, self.fit)
        return True

    # -- bouton d'ajustement ------------------------------------------------
    #
    # *Ajuster* est un geste de **vue**, pas un outil : il ne pose rien sur
    # la plaque. Il se fait donc là où l'on regarde — dans le coin du plan
    # de travail — et non à l'autre bout de la barre d'outils.
    #
    # En surcouche, et non dans une marge : le plan de travail garde toute
    # sa surface, et le bouton se tient dans le coin le moins occupé d'un
    # dessin centré.

    def _build_fit_button(self) -> None:
        self.w_fit = QToolButton(self)
        self.w_fit.setIcon(icons.icon('ajuster'))
        self.w_fit.setIconSize(QSize(20, 20))
        self.w_fit.setFixedSize(FIT_BUTTON, FIT_BUTTON)
        self.w_fit.setCursor(Qt.ArrowCursor)
        self.w_fit.setToolTip('Ajuster la vue au dessin   ·   Ctrl+0')
        self.w_fit.clicked.connect(self.fit)
        self.style_fit_button()
        self._place_fit_button()

    def style_fit_button(self) -> None:
        """Assez de fond pour se détacher, assez peu pour ne pas gêner."""
        if not hasattr(self, 'w_fit'):
            return
        palette = theme.current()
        self.w_fit.setIcon(icons.icon('ajuster', palette.text_dim))
        self.w_fit.setStyleSheet(
            f'QToolButton {{ background: {palette.panel};'
            f' border: 1px solid {palette.text_dim}; border-radius: 5px; }}'
            f'QToolButton:hover {{ border-color: {palette.text}; }}')

    def _place_fit_button(self) -> None:
        if not hasattr(self, 'w_fit'):
            return
        # la barre de défilement, quand elle paraît, ne doit pas passer
        # par-dessus le bouton
        marge = FIT_MARGIN
        barre = self.verticalScrollBar()
        if barre is not None and barre.isVisible():
            marge += barre.width()
        bas = self.horizontalScrollBar()
        sous = FIT_MARGIN + (bas.height() if bas is not None
                             and bas.isVisible() else 0)
        self.w_fit.move(self.viewport().width() + self.frameWidth() - marge
                        - FIT_BUTTON,
                        self.viewport().height() + self.frameWidth() - sous
                        - FIT_BUTTON)
        self.w_fit.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_fit_button()

    # -- décor -------------------------------------------------------------

    def _draw_field(self) -> None:
        p = theme.current()
        self._decor = []
        hw, hh = self.document.field_w / 2, self.document.field_h / 2
        grid = QPen(QColor(p.grid), 0)
        for x in range(int(-hw), int(hw) + 1, 10):
            self._decor.append(self._scene.addLine(x, -hh, x, hh, grid))
        for y in range(int(-hh), int(hh) + 1, 10):
            self._decor.append(self._scene.addLine(-hw, y, hw, y, grid))
        pen = QPen(QColor(p.field), 0)
        pen.setStyle(Qt.DashLine)
        self._decor.append(self._scene.addRect(
            QRectF(-hw, -hh, self.document.field_w, self.document.field_h), pen))
        axis = QPen(QColor(p.axis), 0)
        self._decor.append(self._scene.addLine(-hw, 0, hw, 0, axis))
        self._decor.append(self._scene.addLine(0, -hh, 0, hh, axis))
        self._scene.setSceneRect(-hw * 1.2, -hh * 1.2,
                                 self.document.field_w * 1.2,
                                 self.document.field_h * 1.2)

    def restyle(self) -> None:
        """Repeint le plan de travail après un changement de thème."""
        p = theme.current()
        self.setBackgroundBrush(QBrush(QColor(p.canvas)))
        for item in self._decor:
            self._scene.removeItem(item)
        if not self.monte:
            # le décor sera posé au montage, aux couleurs du moment : le
            # poser maintenant relirait un document qui attend
            self.style_fit_button()
            return
        self._draw_field()
        for item in self._items.values():
            item.restyle()
        self.style_fit_button()

    # -- synchronisation ---------------------------------------------------

    def reload(self) -> None:
        for item in self._items.values():
            self._scene.removeItem(item)
        self._items.clear()
        self._zones = None
        for shape in self.document.shapes:
            if not shape.visible:
                continue           # masquée : rien à dessiner
            item = ShapeItem(shape, self.geometry_changed.emit,
                             self.zone_of)
            self._scene.addItem(item)
            self._items[shape.id] = item
        self.geometry_changed.emit()

    def zone_of(self, shape: Shape):
        """La part de son groupe dans le remplissage de `shape`, ou None.

        Calculée une fois pour tout le plan : chaque membre d'un groupe a
        besoin des autres, et les demander membre par membre refaisait le
        tour du groupe autant de fois qu'il a de membres.
        """
        if self._zones is None:
            self._zones = group_zones(self.document.shapes)
        return self._zones.get(shape.id)

    def refresh(self, shape_id: str) -> None:
        self.refresh_many([shape_id])

    def refresh_many(self, shape_ids) -> None:
        """Redessine ces formes, puis les autres membres de leurs groupes
        dont le remplissage a changé.

        Un membre qui change peut changer le remplissage des autres : il
        est un trou dans l'un, une île dans un autre. Les zones de groupe
        ne sont recalculées qu'une fois pour toutes les formes : forme par
        forme, régler la process d'un logo séparé de quatre cents morceaux
        refaisait quatre cents fois le tour du document.
        """
        self._zones = None
        faites, groupes = set(), set()
        for shape_id in shape_ids:
            item = self._items.get(shape_id)
            if item is None or shape_id in faites:
                continue
            item.rebuild()
            faites.add(shape_id)
            if item.entity.group:
                groupes.add(item.entity.group)
        if groupes:
            self._resync(i for sid, i in self._items.items()
                         if sid not in faites and i.entity.group in groupes)
        self.geometry_changed.emit()

    def resync(self, shape_ids) -> None:
        """Redessine celles de ces formes dont le remplissage de groupe a
        changé — après avoir groupé ou dégroupé, par exemple."""
        self._zones = None
        self._resync(self._items[i] for i in shape_ids if i in self._items)
        self.geometry_changed.emit()

    def _resync(self, items) -> None:
        for item in items:
            if self.zone_of(item.entity) != item.zone:
                item.rebuild()

    def _selection_touched(self) -> None:
        """Étend la sélection aux groupes, puis prévient la fenêtre.

        Cliquer un membre sélectionne tout le groupe. L'extension modifie
        la sélection, donc réémet le signal : le garde-fou évite que
        chaque clic ne déclenche une cascade.
        """
        if self._expanding:
            return
        picked = [i.entity.id for i in self._scene.selectedItems()
                  if isinstance(i, ShapeItem)]
        if len(picked) == 1 or self._primary not in picked:
            self._primary = picked[0] if picked else ''
        wanted = set(self.document.expand_selection(picked))
        if wanted != set(picked):
            self._expanding = True
            try:
                for sid, item in self._items.items():
                    item.setSelected(sid in wanted)
            finally:
                self._expanding = False
        self.selection_changed.emit()

    def selected_ids(self) -> list[str]:
        """Identifiants de toutes les formes sélectionnées."""
        return [i.entity.id for i in self._scene.selectedItems()
                if isinstance(i, ShapeItem)]

    def selected_shapes(self) -> list[Shape]:
        return [i.entity for i in self._scene.selectedItems()
                if isinstance(i, ShapeItem)]

    def select_many(self, shape_ids) -> None:
        """Sélectionne exactement ces formes, en une seule notification.

        Chaque `setSelected` émet `selectionChanged`, qui étend la
        sélection aux groupes puis fait recalculer la barre d'état : sur
        une sélection de plusieurs centaines de formes, la note à payer
        est quadratique. Le garde-fou suspend l'extension le temps de la
        boucle, et un seul signal part à la fin.
        """
        wanted = set(shape_ids)
        if wanted == set(self.selected_ids()):
            return
        self._expanding = True
        try:
            for sid, item in self._items.items():
                item.setSelected(sid in wanted)
        finally:
            self._expanding = False
        self.selection_changed.emit()

    def selected_id(self) -> str | None:
        """Identifiant si — et seulement si — une seule forme est sélectionnée."""
        ids = self.selected_ids()
        return ids[0] if len(ids) == 1 else None

    def primary_id(self) -> str | None:
        """Forme à présenter dans l'inspecteur.

        Sélectionner un membre d'un groupe sélectionne tout le groupe ;
        n'afficher alors aucune propriété rendrait le groupe inutilisable,
        puisqu'il faudrait le défaire pour régler quoi que ce soit. On
        montre donc la forme réellement désignée, celle sur laquelle on a
        cliqué, les autres suivant pour le déplacement et l'échelle.
        """
        ids = self.selected_ids()
        if len(ids) == 1:
            return ids[0]
        if self._primary in ids:
            return self._primary
        return None

    def select(self, shape_id: str) -> None:
        self._primary = shape_id
        for sid, item in self._items.items():
            item.setSelected(sid == shape_id)

    # -- aimant ------------------------------------------------------------

    def cibles_aimant(self, exclus: set[str]) -> tuple[list, list]:
        """Ce à quoi peut s'accrocher ce qu'on traîne — voir `aimant` :
        les bords et le milieu des autres formes, les axes, les bords du
        champ. Triées, en x puis en y."""
        hw, hh = self.document.field_w / 2, self.document.field_h / 2
        xs, ys = [-hw, 0.0, hw], [-hh, 0.0, hh]
        for sid, item in self._items.items():
            if sid in exclus or item.path().isEmpty():
                continue
            r = item.sceneBoundingRect()
            xs.extend(aimant.traits(r.left(), r.right()))
            ys.extend(aimant.traits(r.top(), r.bottom()))
        return sorted(xs), sorted(ys)

    def montrer_guides(self, x: float | None, y: float | None) -> None:
        """Les lignes de repère de l'aimant : une verticale en `x`, une
        horizontale en `y` ; None efface la sienne."""
        if self._guides is None:
            if x is None and y is None:
                return
            self._guides = (self._scene.addLine(0, 0, 0, 0),
                            self._scene.addLine(0, 0, 0, 0))
            for ligne in self._guides:
                ligne.setZValue(1e6)
        stylo = QPen(QColor(theme.current().accent), 0)
        stylo.setStyle(Qt.DashLine)
        r = self._scene.sceneRect()
        verticale, horizontale = self._guides
        verticale.setVisible(x is not None)
        horizontale.setVisible(y is not None)
        if x is not None:
            verticale.setPen(stylo)
            verticale.setLine(x, r.top(), x, r.bottom())
        if y is not None:
            horizontale.setPen(stylo)
            horizontale.setLine(r.left(), y, r.right(), y)

    def fit(self) -> None:
        if not self.monte:
            return          # `monter` ajustera la vue, une fois le plan posé
        hw, hh = self.document.field_w / 2, self.document.field_h / 2
        self.fitInView(QRectF(-hw, -hh, self.document.field_w,
                              self.document.field_h), Qt.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    # -- clavier -----------------------------------------------------------

    def set_step(self, value: float) -> None:
        self.nudge_step = max(0.001, float(value))
        self.step_changed.emit(self.nudge_step)

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-clic sur un texte ou un code : on veut le retaper.

        Le premier clic a déjà sélectionné la forme et ouvert son
        formulaire ; le second dit ce qu'on vient y faire. Le champ du
        contenu prend alors le focus, texte sélectionné, et ce qu'on
        tape le remplace — sans traverser la fenêtre à la souris.
        """
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, ShapeItem) and isinstance(item.entity,
                                                      (Text, Code)):
            self.edit_requested.emit(item.entity.id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        """Flèches : déplacer la sélection. Ctrl+flèche : régler le pas.

        Ctrl+↑/↓ faisait défiler une échelle de pas préétablie. Elle ne
        contenait jamais celui qu'il fallait — 0,35 mm pour rattraper un
        entraxe, 2,3 pour un pas de perçage. N'importe quelle flèche
        avec Ctrl envoie donc au **champ du pas**, où l'on tape le nombre
        décimal qu'on veut ; Entrée y applique la valeur et rend le
        focus au plan de travail, la sélection intacte, prête à bouger
        du nouveau pas. Le pas retenu vaut pour toute la session.
        """
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.ControlModifier)

        if ctrl and key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left,
                            Qt.Key_Right):
            self.step_focus_requested.emit()
            event.accept()
            return

        deltas = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
                  Qt.Key_Up: (0, 1), Qt.Key_Down: (0, -1)}
        if key in deltas and not ctrl:
            items = [i for i in self._scene.selectedItems()
                     if isinstance(i, ShapeItem)]
            if items:
                dx, dy = deltas[key]
                step = self.nudge_step * (10 if event.modifiers() & Qt.ShiftModifier
                                          else 1)
                for item in items:
                    item.setPos(item.pos().x() + dx * step,
                                item.pos().y() + dy * step)
                event.accept()
                return
        super().keyPressEvent(event)


# --------------------------------------------------------------------------
# Panneau de propriétés
# --------------------------------------------------------------------------

class ShapeRow(QWidget):
    """Une ligne de la liste des formes : nom, outil, et trois boutons.

    Les gestes qu'on répète le plus sur une plaque — masquer un élément le
    temps d'un essai, dupliquer une plaquette, retirer un repère — se font
    ici d'un clic, sur la ligne concernée. Les chercher dans la barre
    d'outils obligeait à sélectionner d'abord, viser ensuite.
    """

    toggled = Signal(str)          # id de la forme dont l'œil a changé
    duplicated = Signal(str)
    removed = Signal(str)

    def __init__(self, shape: Shape, label: str) -> None:
        super().__init__()
        self.shape_id = shape.id
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 1, 2, 1)
        row.setSpacing(2)

        self.w_label = QLabel(label)
        self.w_label.setTextInteractionFlags(Qt.NoTextInteraction)
        row.addWidget(self.w_label, 1)

        self.w_eye = self._button(
            'oeil', 'Masquer — la forme ne sera ni affichée ni gravée',
            lambda: self.toggled.emit(self.shape_id))
        self.w_copy = self._button(
            'dupliquer', 'Dupliquer cette forme',
            lambda: self.duplicated.emit(self.shape_id))
        self.w_del = self._button(
            'supprimer', 'Supprimer cette forme',
            lambda: self.removed.emit(self.shape_id),
            tint=theme.current().alarm)
        for button in (self.w_eye, self.w_copy, self.w_del):
            row.addWidget(button)
        self.set_visible_state(shape.visible)

    def _button(self, glyph: str, tip: str, slot, tint=None) -> QToolButton:
        button = QToolButton()
        button.setIcon(icons.icon(glyph, tint))
        button.setIconSize(QSize(15, 15))
        button.setFixedSize(21, 21)
        button.setAutoRaise(True)
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.clicked.connect(slot)
        return button

    def set_label(self, label: str) -> None:
        if self.w_label.text() != label:
            self.w_label.setText(label)

    def set_visible_state(self, visible: bool) -> None:
        """Œil ouvert ou fermé, et le nom grisé quand la forme est masquée."""
        palette = theme.current()
        self.w_eye.setIcon(icons.icon('oeil' if visible else 'oeil_ferme',
                                      None if visible else palette.text_dim))
        self.w_eye.setToolTip(
            'Masquer — la forme ne sera ni affichée ni gravée' if visible
            else 'Afficher — la forme repartira à la gravure')
        self.w_label.setStyleSheet(
            '' if visible else f'color:{palette.text_dim}; font-style:italic;')


class RecipeEditor(QWidget):
    """Recette laser de la forme sélectionnée.

    Séparée de l'inspecteur et placée **sous la liste des formes** : la
    recette est ce qu'on vérifie avant de lancer, et elle se lit alors dans
    la même colonne que la forme qu'elle concerne. La colonne des
    propriétés reste pour la géométrie.
    """

    changed = Signal(str)          # id de la forme modifiée
    #: Les formes d'un lot ont reçu la même process : leurs identifiants.
    changed_many = Signal(list)
    saved = Signal(str)            # nom de la recette rangée en bibliothèque

    def __init__(self) -> None:
        super().__init__()
        self._shape: Shape | None = None
        #: Les formes sélectionnées **avec** celle qu'on montre. Quand
        #: elles partagent une seule process, tout réglage fait ici
        #: s'applique à chacune — voir `_spread`.
        self._lot: list[Shape] = []
        self._guard = False
        self._expert = False
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignTop)
        self._empty = QLabel('Aucune forme sélectionnée.')
        self._empty.setStyleSheet(theme.css())
        self._layout.addWidget(self._empty)
        self._body: QWidget | None = None

    # -- lot ---------------------------------------------------------------
    #
    # Sélectionner six formes et régler la puissance ne réglait que la
    # forme cliquée : il fallait recommencer cinq fois, ou passer par le
    # panneau du lot — qui n'existe pas pour un montage ni pour une plaque
    # codée. Le formulaire commun règle donc **toutes** les formes
    # sélectionnées, à une réserve près : quand elles portent déjà des
    # process différentes, c'est presque toujours voulu — un coupon
    # d'essai, où chaque case a la sienne — et un tour de molette ne doit
    # pas les effacer toutes. Le formulaire ne règle alors que la forme
    # cliquée, le dit, et propose d'étendre d'un geste explicite.

    def _spread(self) -> bool:
        """Vrai si ce qu'on règle ici s'applique à tout le lot."""
        if len(self._lot) < 2:
            return False
        from .lot import common_recipe
        return common_recipe(self._lot) is not None

    def _targets(self) -> list:
        """Les formes que le prochain réglage modifie."""
        if self._spread():
            return list(self._lot)
        return [self._shape] if self._shape is not None else []

    def _extend_to_lot(self) -> None:
        """Pose la process de la forme cliquée sur tout le lot."""
        if self._shape is None or len(self._lot) < 2:
            return
        for forme in self._lot:
            forme.recipe = self._shape.recipe
        ids = [f.id for f in self._lot]
        self.refresh()
        self.changed_many.emit(ids)

    def _lot_banner(self, box) -> None:
        """Dit sur quoi porte le formulaire, quand c'est plus d'une forme."""
        if len(self._lot) < 2:
            return
        n = len(self._lot)
        if self._spread():
            note = QLabel(f'{theme.span("ok")}Règle les <b>{n} formes</b> '
                          'sélectionnées.</span>')
            note.setWordWrap(True)
            box.addWidget(note)
            return
        process = len({(f.recipe.name, f.recipe.tool_number,
                        f.recipe.power_percent, f.recipe.speed_mm_min)
                       for f in self._lot})
        nom = self._shape.display_name() if self._shape else 'la forme'
        note = QLabel(
            f'{theme.span("warn")}{n} formes, {process} process '
            f'différentes — seule « {nom} » est réglée ici.</span>')
        note.setWordWrap(True)
        note.setToolTip(
            'Un lot aux process différentes est presque toujours voulu — '
            'un coupon d\'essai, par exemple. Le formulaire ne touche '
            'donc que la forme cliquée, sauf demande explicite.')
        box.addWidget(note)
        etendre = QPushButton(f'Étendre à toutes les formes ({n})')
        etendre.setToolTip(
            f'Pose la process de « {nom} » sur les {n} formes '
            'sélectionnées. Leurs process actuelles sont remplacées.')
        etendre.clicked.connect(self._extend_to_lot)
        box.addWidget(etendre)

    # -- fabriques ---------------------------------------------------------

    def _spin(self, value, lo, hi, step=1.0, decimals=3, suffix='') -> Spin:
        w = Spin(value, lo, hi, step=step, decimals=decimals, suffix=suffix)
        w.valueChanged.connect(self._emit)
        return w

    def _int(self, value, lo, hi, suffix='') -> IntSpin:
        w = IntSpin(value, lo, hi, suffix=suffix)
        w.valueChanged.connect(self._emit)
        return w

    def _emit(self, *_) -> None:
        if self._guard or self._shape is None:
            return
        self._apply()
        if self._spread():
            self.changed_many.emit([f.id for f in self._lot])
        else:
            self.changed.emit(self._shape.id)

    def _wobble_note(self, *_) -> None:
        """Ce que l'oscillation coûte, dit avant qu'on l'apprenne sur pièce.

        Deux chiffres suffisent à décider : la **cadence demandée au
        scanner**, qui dit si le miroir suivra, et le **facteur de
        longueur**, qui dit ce que la durée devient.
        """
        if not hasattr(self, 'w_wob_info'):
            return
        forme = self.w_wob.currentData() or 'none'
        amplitude = self.w_wamp.value()
        pas = self.w_wpitch.value()
        if forme == 'none' or amplitude <= 0 or pas <= 0:
            self.w_wob_info.setText('')
            return
        vitesse = self.w_speed.value() * SPEED_FROM_DISPLAY
        cadence = wobble.scanner_hz(vitesse, pas)
        facteur = wobble.length_factor(amplitude, pas, forme)
        palette = theme.current()
        if cadence > wobble.SCANNER_MAX_HZ:
            couleur, verdict = palette.alarm, 'le scanner ne suivra pas'
        elif cadence > wobble.SCANNER_SAFE_HZ:
            couleur, verdict = palette.warn, 'amplitude réelle réduite'
        else:
            couleur, verdict = palette.ok, 'tenable'
        tenable = wobble.max_speed_mm_min(pas) * SPEED_TO_DISPLAY
        self.w_wob_info.setText(
            f'<span style="color:{couleur}">bande '
            f'{amplitude * 2:.3g} mm · scanner {cadence:.0f} Hz — '
            f'{verdict}</span><br>'
            f'longueur gravée x{facteur:.1f} · tenable jusqu\'à '
            f'{tenable:.1f} {SPEED_UNIT}')

    def _save_recipe(self) -> None:
        """Range la recette de la forme dans la bibliothèque, sous son nom.

        Une recette au point ne vaut que si on la retrouve. Elle se réglait
        sur la forme, dans la colonne 1 — puis il fallait rouvrir le
        gestionnaire et la ressaisir pour la garder. Ce bouton fait le
        trajet.

        Un nom déjà pris est **mis à jour** plutôt que dupliqué : c'est ce
        qu'on veut quand on affine une recette existante, et le
        gestionnaire refuse de toute façon deux recettes de même nom.
        """
        if self._shape is None:
            return
        recette = self._shape.recipe
        nom = (recette.name or '').strip()
        if not nom or nom.lower() in ('personnalisé', 'personnalise'):
            nom, ok = QInputDialog.getText(
                self, 'Enregistrer la process',
                'Sous quel nom ranger cette process ?', text=nom)
            if not ok or not nom.strip():
                return
            recette = dataclasses.replace(recette, name=nom.strip())
            self._shape.recipe = recette
            self.changed.emit(self._shape.id)

        library = list(RECIPE_LIBRARY)
        # **Créer, jamais écraser.** On affine une recette en partant d'une
        # autre : perdre l'ancienne parce qu'on a gardé son nom, ce serait
        # perdre le point de comparaison au moment précis où il sert. Le
        # nom reçoit donc un rang si besoin — « Laiton 2 », « Laiton 3 ».
        neuf = recipes.unique_name(recette.name, library)
        if neuf != recette.name:
            recette = dataclasses.replace(recette, name=neuf)
            self._shape.recipe = recette
        library.append(recette)
        recipes.set_recipe_library(library)
        recipes.save_local(library)
        self.saved.emit(recette.name)

    # -- mode expert -------------------------------------------------------

    def set_expert(self, enabled: bool) -> None:
        """Mode expert : réglages fins de fréquence et de largeur d'impulsion."""
        self._expert = enabled
        shape = self._shape
        if shape is not None:
            self._shape = None          # force la reconstruction
            QTimer.singleShot(0, lambda: self.set_shape(shape))

    def _tune_expert_widgets(self) -> None:
        """Ajuste la **finesse** des réglages, jamais leur étendue.

        Puissance, fréquence et durée d'impulsion restent **visibles** dans
        les deux modes, sur toute la plage admise par la source :
        restreindre les bornes en mode simple faisait écraser en silence une
        valeur réglée en mode expert dès qu'on en sortait. Ce qui change en
        mode simple, c'est que fréquence et impulsion sont en lecture seule
        — on voit avec quoi on grave sans pouvoir le dérégler par mégarde.
        """
        self.w_freq.setRange(1.0, 1300.0)
        self.w_pulse.setRange(1, 65535)
        self.w_power.setRange(0.0, 100.0)
        for w in (self.w_freq, self.w_pulse):
            w.setReadOnly(not self._expert)
            # Aucune infobulle : elle nommerait le mode expert, donc son
            # existence, à qui n'a pas à le connaître. Le champ grisé dit
            # déjà qu'il ne se règle pas ici.
            w.setToolTip('')
        if self._expert:
            self.w_freq.setDecimals(2)
            self.w_freq.setSingleStep(0.1)
            self.w_pulse.setSingleStep(1)
            self.w_power.setDecimals(2)
            self.w_power.setSingleStep(0.5)
        else:
            self.w_freq.setDecimals(0)
            self.w_freq.setSingleStep(5.0)
            self.w_pulse.setSingleStep(10)
            self.w_power.setDecimals(1)
            self.w_power.setSingleStep(5.0)

    # -- construction ------------------------------------------------------

    def set_shape(self, shape: Shape | None, lot=()) -> None:
        """Montre la process de `shape`, réglée pour tout `lot` s'il
        partage la sienne — voir `_spread`."""
        lot = [f for f in lot if f is not None]
        if shape is self._shape and [f.id for f in lot] == [
                f.id for f in self._lot]:
            return
        self._shape = shape
        self._lot = lot if shape is not None else []
        self._rebuild(shape)

    def refresh(self) -> None:
        """Reconstruit sur place — après un changement de bibliothèque."""
        shape, self._shape = self._shape, None
        self.set_shape(shape, self._lot)

    def _rebuild(self, shape: Shape | None) -> None:
        if self._body is not None:
            self._layout.removeWidget(self._body)
            # masqué **avant** d'être détaché, comme le fait
            # l'inspecteur : posé dans la disposition, il attend encore
            # l'affichage que Qt programme au tour suivant ; reconstruit
            # deux fois d'ici là, il paraissait en fenêtre à part
            # jusqu'à sa destruction
            self._body.hide()
            self._body.setParent(None)
            self._body.deleteLater()
            self._body = None
        self._empty.setVisible(shape is None)
        if shape is None:
            return

        self._guard = True
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(0, 0, 0, 0)
        self._lot_banner(box)

        r = shape.recipe
        # Sans titre : le bandeau du panneau porte déjà « Recette
        # laser ». L'écrire deux fois vole une ligne à un panneau
        # qui en manque.
        g_rec = QGroupBox('')
        f = QFormLayout(g_rec)
        theme.tidy_form(f)
        self.w_preset = Combo()
        self.w_preset.setMaxVisibleItems(24)
        # Rangée **comme la page des process** — racine, puis dossiers en
        # tête, process en retrait — et non en liste plate préfixée du
        # dossier : l'œil a appris un ordre dans le gestionnaire, il
        # doit le retrouver ici.
        recipes.fill_combo(self.w_preset, RECIPE_LIBRARY,
                           first=('(personnalisée)', None))
        # La liste affichait « (personnalisée) » même quand la recette venait
        # d'être choisie dans la bibliothèque : on ne voyait donc jamais son
        # propre choix. Elle se positionne sur la recette en vigueur, et ne
        # retombe sur « personnalisée » qu'après une modification qui
        # l'écarte réellement de la bibliothèque.
        self.w_preset.setCurrentIndex(self._preset_index(r))
        self.w_preset.currentIndexChanged.connect(self._preset_chosen)
        self.w_tool = self._int(r.tool_number, 0, 999)
        self.w_power = self._spin(r.power_percent, 0, 100, 5, 1, ' %')
        self.w_freq = self._spin(r.frequency_khz, 1, 1300, 10, 1, ' kHz')
        self.w_pulse = self._int(r.pulse_width_ns, 1, 65535, ' ns')
        # saisie en m/min, modèle en mm/min : la machine se lit en
        # m/min, l'ISO s'écrit en mm/min, et le facteur reste ici
        self.w_speed = self._spin(
            r.speed_mm_min * SPEED_TO_DISPLAY, 0.001, 500, 1, 3,
            ' ' + SPEED_UNIT)
        self.w_passes = self._int(r.passes, 1, 999)
        self.w_passes.setToolTip('Nb_passe du magasin d\'outils.')
        # six décimales, et non trois : le pas relevé sur la machine vaut
        # 4,673 µm, et l'afficher « 0,005 mm » serait un contresens
        self.w_depth = self._spin(r.depth_step_mm, 0, 5, 0.001, 6, ' mm')
        self.w_depth.setToolTip(
            'Zpasse : descente entre deux passes.\n'
            'Sans effet sur une process à un seul passage.')
        self.w_hatch = self._spin(r.hatch_mm, 0, 5, 0.01, 3, ' mm')
        self.w_hatch.setToolTip('Pas de hachurage. 0 = contour seul.')
        self.w_hangle = self._spin(r.hatch_angle_deg, -180, 180, 15, 1, ' °')
        f.addRow('Préréglage', self.w_preset)
        f.addRow('Outil', self.w_tool)
        f.addRow('Puissance', self.w_power)
        f.addRow('Fréquence', self.w_freq)
        f.addRow('Impulsion', self.w_pulse)
        f.addRow('Vitesse', self.w_speed)
        f.addRow('Nb passes', self.w_passes)
        f.addRow('Profondeur / passe', self.w_depth)
        f.addRow('Pas hachurage', self.w_hatch)
        f.addRow('Angle hach.', self.w_hangle)
        box.addWidget(g_rec)

        # --- stratégie de remplissage ---
        #
        # Trois réglages qui ne changent rien au laser et tout au résultat.
        # Ils vivent dans leur propre cadre : le premier porte ce que la
        # machine reçoit, celui-ci ce que la géométrie fait.
        g_fill = QGroupBox('Remplissage')
        ff = QFormLayout(g_fill)
        theme.tidy_form(ff)
        self.w_hstep = self._spin(r.hatch_angle_step_deg, 0, 180, 15, 1, ' °')
        self.w_hstep.setToolTip(
            'Angle ajouté au hachurage à chaque passe.\n'
            '0 : toutes les passes dans le même sens — les creux du '
            'premier passage\nguident le second et le fond sort strié. '
            '45 ou 90 croisent les trajectoires\net donnent un fond plat.')
        self.w_hcross = QCheckBox('Croisé (+90° dans la même passe)')
        self.w_hcross.setChecked(bool(r.hatch_cross))
        self.w_hcross.setToolTip(
            'Deux nappes perpendiculaires au même Z : surface homogène en '
            'un seul passage,\npour deux fois le trajet. À distinguer de '
            'la rotation par passe, qui creuse.')
        self.w_hcross.toggled.connect(self._emit)
        self.w_link = QCheckBox('Enchaîner les tracés (moins d’allumages)')
        self.w_link.setChecked(bool(getattr(r, 'link_paths', False)))
        self.w_link.setToolTip(
            'Moins d’allumages du laser : les rangées d’une même île se '
            'gravent d’un trait,\nles fragments de contour qui se '
            'touchent sont joints, un code se remplit d’un tenant.\n'
            'Sur cette machine, c’est l’allumage qui coûte, pas la '
            'gravure : un DataMatrix\nhachuré passe de 2 666 à 503 '
            'allumages. Rien n’est gravé hors du dessin.')
        self.w_link.toggled.connect(self._emit)
        self.w_fill = Combo()
        self.w_fill.addItem('Hachures — rangées parallèles', 'hatch')
        self.w_fill.addItem('Anneaux — suivent le contour', 'rings')
        self.w_fill.setCurrentIndex(max(0, self.w_fill.findData(
            getattr(r, 'fill_style', 'hatch'))))
        self.w_fill.setToolTip(recipes.FILL_STYLE_TIP)
        self.w_fill.currentIndexChanged.connect(self._fill_style_shown)
        self.w_fill.currentIndexChanged.connect(self._emit)
        self.w_hinset = self._spin(r.hatch_inset_mm, 0, 2, 0.005, 3, ' mm')
        self.w_hinset.setToolTip(
            'Retrait du remplissage par rapport au contour.\n'
            'Le faisceau a une largeur et déborde d\'un demi-spot : '
            'rentrer de 0,015 mm\nmet le bord de la zone gravée '
            'exactement sur le contour.')
        ff.addRow('Style', self.w_fill)
        ff.addRow('Rotation / passe', self.w_hstep)
        ff.addRow('', self.w_hcross)
        ff.addRow('', self.w_link)
        ff.addRow('Retrait', self.w_hinset)
        box.addWidget(g_fill)
        self._fill_style_shown()

        # --- oscillation du faisceau ---
        g_wob = QGroupBox('Oscillation du faisceau')
        fw = QFormLayout(g_wob)
        theme.tidy_form(fw)
        self.w_wob = Combo()
        for cle, nom, note in wobble.SHAPES:
            self.w_wob.addItem(f'{nom} — {note}' if note else nom, cle)
        index_w = self.w_wob.findData(r.wobble)
        self.w_wob.setCurrentIndex(max(0, index_w))
        self.w_wob.currentIndexChanged.connect(self._emit)
        self.w_wob.setToolTip(
            'Superpose une oscillation au déplacement : le trait '
            's\'élargit en un seul passage.\n'
            'La machine ne l\'offre pas — elle est faite dans la '
            'géométrie, avant l\'export.')
        self.w_wamp = self._spin(r.wobble_amp_mm, 0, 5, 0.01, 3, ' mm')
        self.w_wamp.setToolTip(
            'Amplitude. La bande gravée fait **deux fois** cela.')
        self.w_wpitch = self._spin(r.wobble_pitch_mm, 0, 10, 0.05, 3, ' mm')
        self.w_wpitch.setToolTip(
            'Avance par tour d\'oscillation.\n'
            'C\'est aussi ce qui fixe la cadence demandée au scanner : '
            'vitesse / pas.')
        fw.addRow('Forme', self.w_wob)
        fw.addRow('Amplitude', self.w_wamp)
        fw.addRow('Pas oscillation', self.w_wpitch)
        self.w_wob_info = QLabel('')
        self.w_wob_info.setWordWrap(True)
        self.w_wob_info.setStyleSheet('font-size:11px;')
        fw.addRow('', self.w_wob_info)
        for widget in (self.w_wob, self.w_wamp, self.w_wpitch, self.w_speed):
            widget.valueChanged.connect(self._wobble_note) if hasattr(
                widget, 'valueChanged') else None
        self.w_wob.currentIndexChanged.connect(self._wobble_note)
        box.addWidget(g_wob)

        self.w_depth_info = QLabel('')
        self.w_depth_info.setWordWrap(True)
        self.w_depth_info.setStyleSheet(theme.css('text_dim', 11))
        f.addRow('', self.w_depth_info)

        # Le commentaire : sur quelle matière, avec quel résultat, quand.
        # Une recette validée sur chute vaut par ce qu'on en sait, pas par
        # ses chiffres.
        self.w_comment = GrowingText(r.comment)
        self.w_comment.setPlaceholderText(
            'Matière, résultat, date du coupon…')
        self.w_comment.setToolTip(
            'Notes libres, enregistrées avec la process.\n'
            'Jamais envoyées à la machine.')
        self.w_comment.textChanged.connect(self._emit)
        f.addRow('Commentaire', self.w_comment)

        self.w_save_recipe = QPushButton('  Enregistrer la process')
        self.w_save_recipe.setIcon(icons.icon('enregistrer_process'))
        self.w_save_recipe.setToolTip(
            'Range cette process dans la bibliothèque, sous son nom.\n'
            'Un nom déjà pris est mis à jour ; sinon la process est '
            'ajoutée.')
        self.w_save_recipe.clicked.connect(self._save_recipe)
        f.addRow('', self.w_save_recipe)

        self._tune_expert_widgets()
        self.w_freq.setValue(r.frequency_khz)
        self.w_pulse.setValue(r.pulse_width_ns)
        self.w_power.setValue(r.power_percent)

        self._body = body
        self._layout.addWidget(body)
        self._guard = False
        self._describe_depth(r)
        self._wobble_note()

    # -- préréglages -------------------------------------------------------

    def _preset_index(self, recipe: Recipe) -> int:
        """Rang de la process dans la liste, 0 (« personnalisée ») sinon.

        La comparaison porte sur **tous** les champs : deux recettes de
        même nom mais de puissance différente ne sont pas la même, et
        afficher le nom de la bibliothèque laisserait croire le contraire.
        Cherché dans la liste elle-même, et non par rang dans la
        bibliothèque : les en-têtes de dossier décalent les rangs.
        """
        return max(0, recipes.combo_index(self.w_preset, recipe))

    def _sync_preset(self, recipe: Recipe) -> None:
        """Recale la liste après une modification manuelle."""
        index = self._preset_index(recipe)
        if self.w_preset.currentIndex() != index:
            self.w_preset.blockSignals(True)
            self.w_preset.setCurrentIndex(index)
            self.w_preset.blockSignals(False)

    def _preset_chosen(self, index: int) -> None:
        """Applique une recette de la bibliothèque, traitement compris.

        Une recette peut porter un **traitement** — cadre, marge, offset,
        épaisseur. Il est appliqué au dessin **avant** la gravure, en même
        temps que les paramètres laser : les deux vont ensemble, et la
        recette qui décrit comment graver décrit aussi sur quoi.

        Le traitement est figé dans la recette, pas emprunté à un modèle :
        supprimer le modèle plus tard ne casse rien.
        """
        preset = self.w_preset.itemData(index)
        if preset is None or self._shape is None:
            return
        cibles = self._targets()
        for forme in cibles:
            forme.recipe = preset
        if preset.treatment is not None:
            treatment.apply_treatment(cibles, preset.treatment)
        shape_id = self._shape.id
        self.refresh()
        if len(cibles) > 1:
            self.changed_many.emit([f.id for f in cibles])
        else:
            self.changed.emit(shape_id)

    def _describe_depth(self, recipe: Recipe) -> None:
        """Cotes obtenues : un pas de quelques microns ne se lit pas de tête."""
        step = recipe.depth_step()
        if recipe.passes <= 1:
            self.w_depth_info.setText('Un seul passage.')
        elif step <= 0:
            self.w_depth_info.setText(
                f'{recipe.passes} passes, toutes en surface.')
        else:
            cotes = ' · '.join(f'{recipe.depth_of(i):.4f}'
                               for i in range(min(recipe.passes, 4)))
            suite = ' …' if recipe.passes > 4 else ''
            self.w_depth_info.setText(
                f'{recipe.passes} passes de {step * 1000:g} µm — '
                f'Z {cotes}{suite}')

    def _fill_style_shown(self, *_) -> None:
        """Angle, rotation et croisement n'ont pas de sens en anneaux."""
        rangees = self.w_fill.currentData() != 'rings'
        for w in (self.w_hangle, self.w_hstep, self.w_hcross):
            w.setEnabled(rangees)

    # -- application -------------------------------------------------------

    def _apply(self) -> None:
        s = self._shape
        if s is None:
            return
        cibles = self._targets()
        s.recipe = dataclasses.replace(
            s.recipe,
            tool_number=self.w_tool.value(),
            power_percent=self.w_power.value(),
            frequency_khz=self.w_freq.value(),
            pulse_width_ns=self.w_pulse.value(),
            speed_mm_min=self.w_speed.value() * SPEED_FROM_DISPLAY,
            passes=self.w_passes.value(),
            depth_step_mm=self.w_depth.value(),
            comment=self.w_comment.text(),
            hatch_mm=self.w_hatch.value(),
            hatch_angle_deg=self.w_hangle.value(),
            hatch_angle_step_deg=self.w_hstep.value(),
            hatch_cross=self.w_hcross.isChecked(),
            link_paths=self.w_link.isChecked(),
            fill_style=self.w_fill.currentData() or 'hatch',
            hatch_inset_mm=self.w_hinset.value(),
            wobble=self.w_wob.currentData() or 'none',
            wobble_amp_mm=self.w_wamp.value(),
            wobble_pitch_mm=self.w_wpitch.value(),
        )
        # la même process, le même objet : c'est ce que `_propagate_recipe`
        # attend pour reconnaître un groupe qui ne porte qu'une seule
        for forme in cibles:
            forme.recipe = s.recipe
        self._sync_preset(s.recipe)
        self._describe_depth(s.recipe)


class Inspector(QWidget):
    """Édition de la forme sélectionnée et de sa process."""

    changed = Signal(str)          # id de la forme modifiée
    #: On veut revenir aux propriétés du lot entier.
    lot_asked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._shape: Shape | None = None
        self._siblings = 0
        self._guard = False
        self._building = False
        self._expert = False
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignTop)
        self._empty = QLabel('Aucune forme sélectionnée.')
        self._empty.setStyleSheet(theme.css())
        self._layout.addWidget(self._empty)
        self._body: QWidget | None = None

    def _spin(self, value, lo, hi, step=1.0, decimals=3, suffix='') -> Spin:
        w = Spin(value, lo, hi, step=step, decimals=decimals, suffix=suffix)
        w.valueChanged.connect(self._emit)
        return w

    def _int(self, value, lo, hi, suffix='') -> IntSpin:
        w = IntSpin(value, lo, hi, suffix=suffix)
        w.valueChanged.connect(self._emit)
        return w

    def _refresh_dims(self) -> None:
        '''Remesure l'encombrement de la forme et l'affiche.

        La mesure porte sur la **géométrie réelle** — contours vectorisés,
        cadre englobant compris — et non sur les cotes nominales : un
        texte de 5 mm de haut n'occupe pas 5 mm, et un code de 15 mm en
        fait 16 avec sa marge.
        '''
        if self._shape is None or not hasattr(self, 'w_dimx'):
            return
        from .toolpath import shape_extent
        try:
            boite = shape_extent(self._shape)
        except Exception as exc:                       # noqa: BLE001
            from .avale import avale
            avale('encombrement : mesure impossible', exc)
            boite = None
        if not boite:
            self.w_dimx.setText('—')
            self.w_dimy.setText('—')
            return
        self.w_dimx.setText(f'<b>{boite[2] - boite[0]:.3f}</b> mm')
        self.w_dimy.setText(f'<b>{boite[3] - boite[1]:.3f}</b> mm')
        for w in (self.w_dimx, self.w_dimy):
            w.setTextFormat(Qt.RichText)

    def _emit(self, *_) -> None:
        if self._guard or self._shape is None:
            return
        self._apply()
        self._refresh_dims()
        self.changed.emit(self._shape.id)

    def follow_move(self) -> None:
        """Recale X, Y et rotation sur la forme, après un geste au plan.

        Déplacer une forme à la souris ou aux flèches ne passe pas par
        ce panneau : ses champs gardaient l'ancienne position. Le premier
        réglage qui suivait — retaper le texte, par exemple — réécrivait
        alors cette position dans la forme, qui **sautait à l'endroit
        d'où on l'avait déplacée**. Les champs suivent donc chaque geste,
        sans rien émettre.
        """
        s = self._shape
        if s is None or self._body is None or self._building:
            return
        self._guard = True
        try:
            for widget, valeur in ((self.w_x, s.x), (self.w_y, s.y),
                                   (self.w_rot, s.rotation_deg)):
                if abs(widget.value() - valeur) > 1e-9:
                    widget.setValue(valeur)
        finally:
            self._guard = False

    def _font_chosen(self, index: int) -> None:
        """Une police choisie — ou un fichier à désigner."""
        if self.w_font.currentData() != FONT_PICK:
            self._font_index = index
            self._emit()
            return
        from PySide6.QtWidgets import QFileDialog
        chemin, _ = QFileDialog.getOpenFileName(
            self, 'Fichier de police', session.start_folder('polices'),
            'Polices (*.ttf *.otf *.ttc *.otc);;Tous (*)')
        self.w_font.blockSignals(True)
        self.w_font.setCurrentIndex(self._font_index)
        self.w_font.blockSignals(False)
        if not chemin:
            return
        session.remember_file('polices', chemin)
        try:
            spec = textvec.add_font_file(chemin)
        except textvec.FontNotFound as exc:
            QMessageBox.warning(self, 'Fichier de police', str(exc))
            return
        forget_font_model()
        shape = self._shape
        self._shape = None
        if shape is not None:
            shape.font_path = spec
            QTimer.singleShot(0, lambda: self.set_shape(shape))
            self.changed.emit(shape.id)

    def refresh_fonts(self) -> None:
        """Refait le formulaire pour qu'il prenne la liste des polices."""
        shape, self._shape = self._shape, None
        if shape is not None:
            self.set_shape(shape, self._siblings)

    def text_field(self):
        """Le champ de contenu de la forme montrée, ou `None`."""
        if self._shape is None or self._body is None:
            return None
        if isinstance(self._shape, Text):
            return getattr(self, 'w_text', None)
        if isinstance(self._shape, Code):
            return getattr(self, 'w_data', None)
        return None

    def focus_text(self) -> bool:
        """Donne le focus au contenu — texte ou donnée d'un code.

        Tout sélectionné : ce qu'on tape remplace. Rend faux si la forme
        n'a pas de contenu à taper.
        """
        champ = self.text_field()
        if champ is None:
            return False
        champ.setFocus(Qt.MouseFocusReason)
        champ.selectAll()
        return True

    def set_shape(self, shape: Shape | None, siblings: int = 0) -> None:
        """Reconstruit le panneau pour la forme donnée.

        `siblings` est le nombre de formes sélectionnées **avec** elle. Au
        delà d'une, un bouton ramène au formulaire du lot : montrer la
        forme désignée ne doit pas faire perdre l'ensemble auquel elle
        appartient.

        L'ancien panneau est retiré de la disposition **puis** confié à
        `deleteLater()` : le détruire immédiatement pendant que Qt traite
        encore un événement de l'un de ses enfants — le changement de
        préréglage, par exemple — fait tomber l'application.
        """
        if (shape is not None and shape is self._shape
                and self._body is not None and siblings == self._siblings):
            return                      # déjà affiché : rien à refaire
        self._siblings = siblings

        if self._building:
            # une reconstruction est déjà en cours ; la relancer maintenant
            # détruirait les widgets que le code appelant manipule encore
            QTimer.singleShot(0, lambda: self.set_shape(shape))
            return
        self._building = True
        try:
            self._rebuild(shape)
        finally:
            self._building = False

    def _rebuild(self, shape: Shape | None) -> None:
        self._shape = shape
        if self._body is not None:
            old, self._body = self._body, None
            self._layout.removeWidget(old)
            old.hide()
            old.setParent(None)
            old.deleteLater()
        self._empty.setVisible(shape is None)
        if shape is None:
            return

        self._guard = True
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(0, 0, 0, 0)

        # Symétrique du bouton « Voir la forme cliquée » du lot : une
        # plaque codée ouvre le formulaire de l'entité désignée, et ce
        # bouton rend l'ensemble — centre, cotes, process commune.
        if self._siblings > 1:
            retour = QPushButton(f'◂ Voir le lot ({self._siblings} formes)')
            retour.setToolTip(
                'Revient aux propriétés de toute la sélection. Elle ne '
                'change pas : seul le formulaire change.')
            retour.clicked.connect(self.lot_asked.emit)
            box.addWidget(retour)

        # --- encombrement, en tout premier ---
        #
        # C'est la première question qu'on se pose devant une forme :
        # « est-ce que ça rentre ? ». Elle était enterrée sous le
        # placement et la géométrie, et pour un tracé importé elle
        # n'apparaissait nulle part — un DXF n'a ni largeur ni hauteur
        # réglable, seulement des points.
        #
        # Lecture seule : l'encombrement se **constate**, il ne se règle
        # pas. Ce qui le change, ce sont les cotes en dessous, ou F2.
        g_dim = QGroupBox('Encombrement')
        fd = QFormLayout(g_dim)
        theme.tidy_form(fd)
        self.w_dimx = QLabel('—')
        self.w_dimy = QLabel('—')
        for w in (self.w_dimx, self.w_dimy):
            w.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fd.addRow('Dim X', self.w_dimx)
        fd.addRow('Dim Y', self.w_dimy)
        box.addWidget(g_dim)
        self._refresh_dims()

        # --- placement ---
        g_pos = QGroupBox('Placement')
        f = QFormLayout(g_pos)
        theme.tidy_form(f)
        self.w_x = self._spin(shape.x, -500, 500, 0.5, 3, ' mm')
        self.w_y = self._spin(shape.y, -500, 500, 0.5, 3, ' mm')
        self.w_rot = self._spin(shape.rotation_deg, -360, 360, 1, 2, ' °')
        f.addRow('X', self.w_x)
        f.addRow('Y', self.w_y)
        f.addRow('Rotation', self.w_rot)
        box.addWidget(g_pos)

        # --- géométrie ---
        g_geo = QGroupBox('Géométrie')
        f = QFormLayout(g_geo)
        theme.tidy_form(f)
        if isinstance(shape, Rect):
            self.w_w = self._spin(shape.width, 0.1, 500, 1, 3, ' mm')
            self.w_h = self._spin(shape.height, 0.1, 500, 1, 3, ' mm')
            f.addRow('Largeur', self.w_w)
            f.addRow('Hauteur', self.w_h)
        elif isinstance(shape, Circle):
            self.w_w = self._spin(shape.width, 0.1, 500, 1, 3, ' mm')
            self.w_h = self._spin(shape.height, 0.1, 500, 1, 3, ' mm')
            f.addRow('⌀ X', self.w_w)
            f.addRow('⌀ Y', self.w_h)
        elif isinstance(shape, Code):
            self.w_codepreset = Combo()
            self.w_codepreset.addItem('(réglage courant)', None)
            for preset in codepresets.library():
                self.w_codepreset.addItem(preset['name'], preset)
                self.w_codepreset.setItemData(
                    self.w_codepreset.count() - 1,
                    codepresets.describe(preset), Qt.ToolTipRole)
            self.w_codepreset.currentIndexChanged.connect(self._preset_code)
            self.w_codepresets = QPushButton('Préréglages…')
            self.w_codepresets.setToolTip(
                'Enregistrer ce réglage, renommer, dupliquer, supprimer.')
            self.w_codepresets.clicked.connect(self._manage_code_presets)
            f.addRow('Préréglage', self.w_codepreset)
            f.addRow('', self.w_codepresets)

            self.w_kind = Combo()
            for value, label in barcode.KINDS:
                self.w_kind.addItem(label, value)
            self.w_kind.setCurrentIndex(max(self.w_kind.findData(shape.kind), 0))
            self.w_kind.currentIndexChanged.connect(self._emit)
            self.w_data = QPlainTextEdit(shape.data)
            self.w_data.setPlaceholderText(
                'Donnée encodée. Champs : {n} {n:04} {date} {job}…')
            self.w_data.setFixedHeight(56)
            self.w_data.setTabChangesFocus(True)
            self.w_data.textChanged.connect(self._emit)
            self.w_dmshape = Combo()
            for value, label in barcode.DM_SHAPES:
                self.w_dmshape.addItem(label, value)
            self.w_dmshape.setCurrentIndex(
                max(self.w_dmshape.findData(shape.dm_shape), 0))
            self.w_dmshape.setToolTip(
                'DataMatrix seulement. Un symbole rectangulaire occupe '
                'moins de hauteur\nà donnée égale : c\'est ce qu\'on emploie '
                'sur une plaque étroite.')
            self.w_dmshape.currentIndexChanged.connect(self._emit)
            self.w_level = Combo()
            for value, label in barcode.QR_LEVELS:
                self.w_level.addItem(label, value)
            self.w_level.setCurrentIndex(
                max(self.w_level.findData(shape.level), 0))
            self.w_level.setToolTip('Correction d\'erreur, QR seulement.')
            self.w_level.currentIndexChanged.connect(self._emit)
            self.w_checksum = QCheckBox('Clé de contrôle')
            self.w_checksum.setChecked(shape.checksum)
            self.w_checksum.setToolTip(
                'Code 39 seulement. La symbologie est déjà auto-vérifiante ;\n'
                'la clé modulo 43 ne sert qu\'aux donneurs d\'ordre qui '
                'l\'exigent.')
            self.w_checksum.toggled.connect(self._emit)
            self.w_module = self._spin(shape.module_mm, 0.02, 10, 0.05, 3,
                                       ' mm')
            self.w_module.setToolTip(
                'Côté d\'un module. Ignoré si une fenêtre est imposée.')
            self.w_bar = self._spin(shape.bar_height_mm, 0.5, 200, 1, 2, ' mm')
            self.w_bar.setToolTip('Hauteur des barres, codes linéaires.')
            self.w_quiet = self._int(shape.quiet_modules, 0, 16, ' modules')
            self.w_quiet.setToolTip(
                'Zone de silence. La norme demande 4 modules pour un QR,\n'
                '1 pour un DataMatrix, 10 pour un Code 39.')
            f.addRow('Symbologie', self.w_kind)
            f.addRow('Donnée', self.w_data)
            f.addRow('Forme', self.w_dmshape)
            f.addRow('Correction', self.w_level)
            f.addRow('', self.w_checksum)
            f.addRow('Module', self.w_module)
            f.addRow('Haut. barres', self.w_bar)
            f.addRow('Silence', self.w_quiet)

            self.w_fitw = self._spin(shape.fit_w_mm, 0, 500, 1, 3, ' mm')
            self.w_fith = self._spin(shape.fit_h_mm, 0, 500, 1, 3, ' mm')
            for w in (self.w_fitw, self.w_fith):
                w.setToolTip(
                    'Fenêtre imposée. Renseignées toutes deux, le symbole\n'
                    'est étiré pour la remplir exactement — c\'est ainsi que\n'
                    'sont faites les plaques de production. 0 = taille libre.')
            self.w_fill = self._spin(shape.fill_step_mm, 0, 2, 0.01, 3, ' mm')
            self.w_fill.setToolTip(
                'Pas de remplissage des modules. 0 = automatique.\n'
                'Un code se grave plein : un module creux ne se lit pas.')
            f.addRow('Fenêtre X', self.w_fitw)
            f.addRow('Fenêtre Y', self.w_fith)
            f.addRow('Remplissage', self.w_fill)
            self.w_code_info = QLabel('')
            self.w_code_info.setWordWrap(True)
            self.w_code_info.setStyleSheet(theme.css('text_dim', 11))
            f.addRow('', self.w_code_info)
        elif isinstance(shape, Path):
            info = QLabel(f'{len(shape.polylines)} polyligne(s)\n'
                          f'calque « {shape.layer} »\n'
                          f'source : {shape.source}')
            info.setWordWrap(True)
            info.setStyleSheet(theme.css())
            f.addRow('Tracé importé', info)
        elif isinstance(shape, Text):
            self.w_text = TextBox(shape.text, cle='texte',
                                  hauteur=session.field_height('texte'))
            self.w_text.setPlaceholderText(
                'Une ligne par ligne.\nChamps : {n} {n:04} {i} {total} '
                '{date} {heure} {job}')
            self.w_text.setToolTip(
                'Le bord inférieur s\'attrape à la souris : le champ '
                's\'agrandit, et la hauteur est retenue.')
            self.w_text.setTabChangesFocus(True)
            self.w_text.resized.connect(session.remember_field_height)
            self.w_text.textChanged.connect(self._emit)
            self.w_size = self._spin(shape.size_mm, 0.5, 200, 0.5, 2, ' mm')
            # Bornes larges et trois décimales : l'interligne sert aussi à
            # **espacer des lignes qui ne se touchent pas** — deux repères
            # gravés à 30 mm l'un de l'autre au même corps — et à les
            # resserrer sous la hauteur d'une capitale. Le plafond de 5 et
            # le pas de 0,1 y suffisaient rarement.
            self.w_spacing = self._spin(shape.line_spacing, 0.05, 50.0,
                                        0.05, 3, ' ×')
            self.w_spacing.setToolTip(
                'Distance entre deux lignes, en multiples de la hauteur.\n'
                '1,4 est l\'interligne courant · 1 colle les lignes · '
                'au-delà de 5, les lignes s\'écartent franchement.')
            self.w_align = Combo()
            for value, label in (('left', 'gauche'), ('center', 'centré'),
                                 ('right', 'droite')):
                self.w_align.addItem(label, value)
            self.w_align.setCurrentIndex(max(self.w_align.findData(shape.align), 0))
            self.w_align.currentIndexChanged.connect(self._emit)
            self.w_valign = Combo()
            for value, label in (('top', 'haut'), ('middle', 'milieu'),
                                 ('baseline', 'ligne de base'),
                                 ('bottom', 'bas')):
                self.w_valign.addItem(label, value)
            self.w_valign.setCurrentIndex(
                max(self.w_valign.findData(shape.valign), 0))
            self.w_valign.currentIndexChanged.connect(self._emit)
            self.w_font = Combo()
            self.w_font.setMaxVisibleItems(24)
            self.w_font.setToolTip(
                'Polices du poste, collections comprises.\n'
                'La dernière entrée prend un fichier .ttf, .otf ou .ttc '
                'qui n\'est pas installé.')
            # modèle partagé : reconstruire 467 entrées à chaque changement
            # de sélection coûterait plus cher que tout le reste du panneau
            self.w_font.setModel(font_model())
            idx = self.w_font.findData(shape.font_path)
            if idx < 0 and shape.font_path:
                # La police du document n'est pas (ou plus) sur ce poste :
                # on la montre telle quelle plutôt que de retomber en
                # silence sur « par défaut », ce qui changerait le dessin
                # sans le dire. Dans un modèle **à ce formulaire** : le
                # modèle partagé la proposerait ensuite à chaque texte.
                from PySide6.QtGui import QStandardItem, QStandardItemModel
                propre = QStandardItemModel(self.w_font)
                manquante = QStandardItem(
                    f'{pathlib.Path(textvec.split_spec(shape.font_path)[0]).name}'
                    ' — absente de ce poste')
                manquante.setData(shape.font_path, Qt.UserRole)
                propre.appendRow(manquante)
                partage = font_model()
                for rang in range(partage.rowCount()):
                    propre.appendRow(partage.item(rang).clone())
                self.w_font.setModel(propre)
                idx = 0
            self.w_font.setCurrentIndex(max(idx, 0))
            self._font_index = max(idx, 0)
            self.w_font.currentIndexChanged.connect(self._font_chosen)
            self.w_stretch = self._spin(shape.stretch, 0.05, 20.0, 0.05, 3, ' ×')
            self.w_stretch.setToolTip(
                'Étirement horizontal. 1 = proportions d\'origine de la '
                'police.\nRéglé aussi par F2 quand on modifie une seule '
                'des deux largeurs.')
            f.addRow('Texte', self.w_text)
            f.addRow('Hauteur', self.w_size)
            f.addRow('Étirement', self.w_stretch)
            f.addRow('Interligne', self.w_spacing)
            f.addRow('Police', self.w_font)
            f.addRow('Align. H', self.w_align)
            f.addRow('Align. V', self.w_valign)
        box.addWidget(g_geo)

        # --- cadre (gravure en négatif) ---
        #
        # Propriété de toute forme, texte comme tracé DXF : creuser autour
        # d'un logo importé est le même problème que creuser autour de
        # lettres, et la règle pair-impair du hachurage s'en charge seule.
        g_frame = QGroupBox('Cadre — gravure en négatif')
        f = QFormLayout(g_frame)
        theme.tidy_form(f)
        self.w_frame = Combo()
        for value, label in (('none', 'aucun'), ('rect', 'rectangle'),
                             ('circle', 'cercle')):
            self.w_frame.addItem(label, value)
        self.w_frame.setCurrentIndex(
            max(self.w_frame.findData(shape.frame), 0))
        self.w_frame.setToolTip(
            'Avec un hachurage, la matière est enlevée entre le cadre\n'
            'et le dessin : celui-ci ressort en relief.')
        self.w_frame.currentIndexChanged.connect(self._emit)
        self.w_fmargin = self._spin(shape.frame_margin_mm, 0, 100,
                                    0.5, 2, ' mm')
        self.w_fw = self._spin(shape.frame_w, 0, 500, 1, 2, ' mm')
        self.w_fw.setToolTip('0 = ajusté au dessin. Pour un cercle : diamètre.')
        self.w_fh = self._spin(shape.frame_h, 0, 500, 1, 2, ' mm')
        self.w_fh.setToolTip('0 = ajusté au dessin. Ignoré pour un cercle.')
        self.w_foffset = self._spin(shape.frame_offset_mm, -20, 20,
                                    0.01, 3, ' mm')
        self.w_foffset.setToolTip(
            'Décale le contour du dessin.\n'
            'Positif : la matière épaissit — les pleins grossissent,\n'
            'les contre-formes se referment. Compense la largeur du\n'
            'faisceau, qui amincit tout relief laissé par une gravure\n'
            'en négatif. Négatif : le tracé s\'amincit.\n'
            'Agit avec ou sans cadre.')
        f.addRow('Cadre', self.w_frame)
        f.addRow('Marge', self.w_fmargin)
        f.addRow('Offset du dessin', self.w_foffset)
        f.addRow('Larg. cadre', self.w_fw)
        f.addRow('Haut. cadre', self.w_fh)
        self.w_fields = QLabel('')
        self.w_fields.setWordWrap(True)
        self.w_fields.setStyleSheet(theme.css('text_dim', 11))
        f.addRow('', self.w_fields)
        box.addWidget(g_frame)

        # --- épaisseur du trait ---
        g_line = QGroupBox('Épaisseur du trait')
        f = QFormLayout(g_line)
        theme.tidy_form(f)
        self.w_lwidth = self._spin(shape.line_width_mm, 0, 20, 0.05, 3, ' mm')
        self.w_lwidth.setToolTip(
            'Élargit le trait par passages parallèles.\n'
            '0 = un seul passage sur le tracé.')
        self.w_lstep = self._spin(shape.line_step_mm, 0, 2, 0.01, 3, ' mm')
        self.w_lstep.setToolTip(
            'Écart entre deux passages. 0 reprend le pas de hachurage\n'
            'de la process, ou 0,05 mm à défaut.')
        # De quel côté du contour vont les passages : des lignes de cote
        # parallèles au contour de référence, toutes dedans ou toutes
        # dehors. Un tracé ouvert reste élargi des deux côtés.
        self.w_lside = Combo()
        for cle, libelle in (('both', 'des deux côtés'),
                             ('inside', 'intérieur seulement'),
                             ('outside', 'extérieur seulement')):
            self.w_lside.addItem(libelle, cle)
        self.w_lside.setCurrentIndex(
            max(0, self.w_lside.findData(getattr(shape, 'line_side',
                                                 'both'))))
        self.w_lside.setToolTip(
            'Où poser les passages parallèles d’un contour fermé.\n'
            'D’un seul côté, toute l’épaisseur y passe : une bordure qui ne '
            'déborde pas de la pièce,\nou un liseré qui ne mord pas le '
            'dessin. Un tracé ouvert reste élargi des deux côtés.')
        self.w_lside.currentIndexChanged.connect(self._emit)
        if isinstance(shape, Code):
            # les arêtes de modules d'un code n'ont ni dedans ni dehors
            self.w_lside.setEnabled(False)
            self.w_lside.setToolTip('Un code s’élargit toujours des deux '
                                    'côtés : ses modules n’ont pas de '
                                    'contour à eux.')
        f.addRow('Épaisseur', self.w_lwidth)
        f.addRow('Côté', self.w_lside)
        f.addRow('Écart', self.w_lstep)
        box.addWidget(g_line)

        self._body = body
        self._layout.addWidget(body)
        self._guard = False

    def _document_shapes(self) -> list[Shape]:
        """Formes du document courant, pour retrouver un texte lié.

        L'inspecteur ne connaît qu'une forme ; la fenêtre principale lui
        fournit le document au moment où elle l'affiche.
        """
        return list(getattr(self, '_shapes_source', lambda: [])() or [])

    def _preset_code(self, index: int) -> None:
        """Applique un préréglage au code affiché, sans le déplacer."""
        preset = self.w_codepreset.itemData(index)
        shape = self._shape
        if preset is None or not isinstance(shape, Code):
            return
        codepresets.apply_to(shape, preset)
        shape_id = shape.id
        # la reconstruction détruit la liste d'où vient ce signal : on la
        # diffère jusqu'à la fin du traitement en cours
        self._shape = None
        QTimer.singleShot(0, lambda: self.set_shape(shape))
        self.changed.emit(shape_id)

    def _manage_code_presets(self) -> None:
        shape = self._shape
        current = None
        if isinstance(shape, Code):
            # la fenêtre du texte est reprise du texte réellement lié, s'il
            # existe : c'est l'implantation en vigueur qu'on enregistre, pas
            # une proportion inventée
            from .codeplate import DEFAULT_TEXT_OFFSET, DEFAULT_TEXT_WINDOW
            from .toolpath import shape_extent
            dx, dy = DEFAULT_TEXT_OFFSET
            tw, th = DEFAULT_TEXT_WINDOW
            linked = next((t for t in self._document_shapes()
                           if isinstance(t, Text) and t.follows == shape.id),
                          None)
            if linked is not None:
                box = shape_extent(linked)
                dx, dy = linked.x - shape.x, linked.y - shape.y
                if box is not None:
                    tw, th = box[2] - box[0], box[3] - box[1]
            current = codepresets.from_code(
                shape.display_name(), shape, text_w_mm=tw, text_h_mm=th,
                text_dx_mm=dx, text_dy_mm=dy)
        dialog = codepresets.CodePresetManager(self, current)
        if dialog.exec() == QDialog.DialogCode.Accepted and shape is not None:
            self._shape = None
            QTimer.singleShot(0, lambda: self.set_shape(shape))

    def _describe_code(self, s: Code) -> None:
        """Taille obtenue, ou la raison pour laquelle le code est refusé."""
        try:
            barcode.encode(s.kind,
                           variables.expand(s.data, variables.make_context()),
                           level=s.level, shape=s.dm_shape,
                           checksum=s.checksum,
                           quiet_modules=s.quiet_modules)
        except barcode.CodeError as exc:
            self.w_code_info.setText(f'⚠ {exc}')
            self.w_code_info.setStyleSheet(theme.css('alarm', 11))
            return
        rows, cols, w, h = code_size(s)
        grid = f'{cols} modules' if rows == 1 else f'{rows} × {cols} modules'
        note = ' · étiré dans sa fenêtre' if s.fit_w_mm > 0 else ''
        self.w_code_info.setText(
            f'{grid} · {w:.2f} × {h:.2f} mm '
            f'(zone de silence comprise){note}')
        self.w_code_info.setStyleSheet(theme.css('text_dim', 11))

    def _explain(self, s: Shape, framed: bool) -> None:
        """Message d'aide sous le cadre : avertissements d'abord.

        Le pas de hachurage se lit sur la recette : elle vit désormais
        dans son propre panneau, en colonne 1.
        """
        unknown = variables.unknown_fields(s.text) if isinstance(s, Text) else []
        if unknown:
            text = '⚠ champ(s) non reconnu(s) : ' + ', '.join(unknown)
            colour = '#d8b25a'
        elif framed and s.recipe.hatch_mm <= 0:
            around = 'des lettres' if isinstance(s, Text) else 'du dessin'
            text = ('cadre sans hachurage : seuls les contours seront gravés. '
                    f'Réglez « Hachure » pour creuser autour {around}.')
            colour = '#d8b25a'
        elif isinstance(s, Text) and variables.has_fields(s.text):
            text = ('champs variables actifs — '
                    'l\'aperçu montre la première pièce')
            colour = '#7bc47f'
        else:
            text = ''
            colour = '#8a94a6'
        self.w_fields.setText(text)
        self.w_fields.setStyleSheet(f'color:{colour}; font-size:11px;')

    def _apply(self) -> None:
        s = self._shape
        if s is None:
            return
        s.x = self.w_x.value()
        s.y = self.w_y.value()
        s.rotation_deg = self.w_rot.value()
        if isinstance(s, (Rect, Circle)):
            s.width = self.w_w.value()
            s.height = self.w_h.value()
        elif isinstance(s, Code):
            s.kind = self.w_kind.currentData() or 'datamatrix'
            s.data = self.w_data.toPlainText()
            s.module_mm = self.w_module.value()
            s.level = self.w_level.currentData() or 'M'
            s.quiet_modules = self.w_quiet.value()
            s.dm_shape = self.w_dmshape.currentData() or 'square'
            s.checksum = self.w_checksum.isChecked()
            s.bar_height_mm = self.w_bar.value()
            s.fit_w_mm = self.w_fitw.value()
            s.fit_h_mm = self.w_fith.value()
            s.fill_step_mm = self.w_fill.value()
            # les cotes données sont retenues : la plaque suivante repart
            # du même cadre, au même endroit, dans la même symbologie
            from . import session as _session
            _session.remember_code(
                frame=(s.x, s.y, s.fit_w_mm, s.fit_h_mm)
                if s.fit_w_mm > 0 and s.fit_h_mm > 0 else None,
                data=s.data, kind=s.kind, dm_shape=s.dm_shape)

            # chaque symbologie n'expose que ce qui la concerne
            linear = barcode.is_linear(s.kind)
            self.w_level.setEnabled(s.kind == 'qr')
            self.w_dmshape.setEnabled(s.kind == 'datamatrix')
            self.w_checksum.setEnabled(s.kind == 'code39')
            self.w_bar.setEnabled(linear)
            self.w_module.setEnabled(s.fit_w_mm <= 0)
            self.w_fith.setEnabled(not linear or s.fit_h_mm > 0)
            self._describe_code(s)
        elif isinstance(s, Text):
            s.text = self.w_text.toPlainText()
            s.size_mm = self.w_size.value()
            s.stretch = self.w_stretch.value()
            s.line_spacing = self.w_spacing.value()
            s.align = self.w_align.currentData() or 'center'
            s.valign = self.w_valign.currentData() or 'middle'
            s.font_path = self.w_font.currentData() or ''

        s.frame = self.w_frame.currentData() or 'none'
        s.frame_margin_mm = self.w_fmargin.value()
        s.frame_offset_mm = self.w_foffset.value()
        s.frame_w = self.w_fw.value()
        s.frame_h = self.w_fh.value()

        s.line_width_mm = self.w_lwidth.value()
        s.line_step_mm = self.w_lstep.value()
        s.line_side = self.w_lside.currentData() or 'both'
        self.w_lstep.setEnabled(s.line_width_mm > 0)
        self.w_lside.setEnabled(s.line_width_mm > 0)

        framed = s.frame != 'none'
        self.w_fmargin.setEnabled(framed)
        self.w_fw.setEnabled(framed)
        self.w_fh.setEnabled(framed and s.frame == 'rect')
        self._explain(s, framed)



# --------------------------------------------------------------------------
# Panneau source laser
# --------------------------------------------------------------------------

class LaserPanel(QWidget):
    """Surveillance de la source JPT.

    **Aucune commande d'émission n'est exposée ici** : allumer le laser
    reste du ressort du contrôleur machine. Ce panneau lit l'état et
    propose la coupure.
    """

    def __init__(self) -> None:
        super().__init__()
        self._client = None
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignTop)

        row = QHBoxLayout()
        self.w_port = Combo()
        self.w_port.setEditable(True)
        self.w_port.addItem('Simulation')
        for p in self._ports():
            self.w_port.addItem(p)
        self.w_connect = QPushButton('Connecter')
        self.w_connect.clicked.connect(self._toggle)
        row.addWidget(self.w_port, 1)
        row.addWidget(self.w_connect)
        v.addLayout(row)

        self.w_state = QLabel('Déconnecté')
        self.w_state.setStyleSheet(theme.css())
        self.w_state.setWordWrap(True)
        v.addWidget(self.w_state)

        self.w_stop = QPushButton('COUPER ÉMISSION')
        self.w_stop.setStyleSheet(
            'background:#8b1c1c; color:white; font-weight:bold; padding:8px;')
        self.w_stop.clicked.connect(self._shutdown)
        self.w_stop.setEnabled(False)
        v.addWidget(self.w_stop)

        note = QLabel('Aucune commande d\'émission n\'est exposée : '
                      'l\'allumage reste du ressort du contrôleur machine.')
        note.setWordWrap(True)
        note.setStyleSheet(theme.css('text_dim', 11))
        v.addWidget(note)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    @staticmethod
    def _ports() -> list[str]:
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports()]
        except Exception:
            return []

    def _toggle(self) -> None:
        if self._client is not None:
            self._disconnect()
            return
        from jpt.client import JptClient, SerialTransport, SimulatedSource
        target = self.w_port.currentText()
        try:
            transport = (SimulatedSource() if target == 'Simulation'
                         else SerialTransport(target))
            self._client = JptClient(transport)
        except Exception as exc:
            QMessageBox.warning(self, 'Connexion', f'Échec : {exc}')
            return
        self._client.read_serial_number()
        self.w_connect.setText('Déconnecter')
        self.w_stop.setEnabled(True)
        self._timer.start(500)

    def _disconnect(self) -> None:
        self._timer.stop()
        try:
            self._client.close()
        except Exception as exc:
            avale('source laser : fermeture', exc)
            pass
        self._client = None
        self.w_connect.setText('Connecter')
        self.w_stop.setEnabled(False)
        self.w_state.setText('Déconnecté')

    def _poll(self) -> None:
        if self._client is None:
            return
        self._client.poll()
        s = self._client.state
        leds = s.get('leds') or {}
        alarms = s.get('alarm_active') or []
        lines = [
            f"série     : {s.get('serial_number', '—')}",
            f"puissance : {s.get('power_percent', '—')} %",
            f"fréquence : {s.get('frequency', '—')}",
            f"impulsion : {s.get('pulse_width', '—')} ns",
            f"LED       : {', '.join(k for k, v in leds.items() if v) or '—'}",
            f"alarmes   : {', '.join(alarms) if alarms else 'aucune'}",
        ]
        self.w_state.setText('\n'.join(lines))
        self.w_state.setStyleSheet(
            theme.css('alarm') if alarms else theme.css())

    def _shutdown(self) -> None:
        if self._client is not None:
            self._client.shutdown_emission()

    def closeEvent(self, event) -> None:
        if self._client is not None:
            self._disconnect()
        super().closeEvent(event)


# --------------------------------------------------------------------------
# Fenêtre principale
# --------------------------------------------------------------------------

class DocumentTab(Canvas):
    """Un onglet : un canevas, son document, et le fichier qui le porte."""

    def __init__(self, document: Document | None, file_path: str = '',
                 brut: dict | None = None) -> None:
        #: Le document tel que l'instantané de séance l'a rendu, **pas
        #: encore relu** : un onglet restauré ne coûte rien tant qu'on ne
        #: le regarde pas — voir `MainWindow._restore_session`.
        self._brut = brut if document is None else None
        #: Contenu illisible, gardé pour l'instantané tant que l'onglet
        #: reste vide — voir `contenu_session`.
        self._illisible: dict | None = None
        self._doc: Document | None = None
        self._history: History | None = None
        #: Appelé avec les valeurs remplacées par leur défaut, au moment
        #: où le document est relu — voir `MainWindow._report_repairs`.
        self.signaler = None
        super().__init__(document, monter=self._brut is None)
        self.file_path = file_path
        self.dirty = False
        self.passes_cache: tuple | None = None
        #: Combien de fois cet onglet a été exporté, et l'état des
        #: paramètres au dernier export : de quoi journaliser ce qui a
        #: changé entre deux plaques.
        self.export_count = 0
        self.export_state: dict = {}

    # -- document relu à la demande ------------------------------------------

    @property
    def document(self) -> Document:
        if self._doc is None and self._brut is not None:
            self._relire()
        return self._doc

    @document.setter
    def document(self, valeur: Document | None) -> None:
        self._doc = valeur
        if valeur is not None:
            self._brut = None

    @property
    def history(self) -> History:
        """Annuler/refaire : un historique par onglet, comme il se doit —
        défaire dans un document ne doit rien changer dans un autre. Il
        part du document tel qu'on le trouve en ouvrant l'onglet."""
        if self._history is None:
            self._history = History(self.document)
        return self._history

    def en_attente(self) -> bool:
        """Vrai tant que le document n'a pas été relu."""
        return self._doc is None and self._brut is not None

    def _relire(self) -> None:
        """Relit le document de l'instantané.

        Les recours sont ceux de la restauration d'avant : le fichier
        enregistré si le contenu mémorisé est illisible, puis un document
        vide au nom du travail — l'onglet est déjà là, il ne peut plus
        disparaître.
        """
        brut, self._brut = self._brut, None
        rapport: list[str] = []
        try:
            self._doc = serialize.document_from_dict(brut, rapport)
        except Exception as exc:
            print(f'TauDrive : instantané illisible — {exc}', file=sys.stderr)
            rapport = []
            if self.file_path and session.reachable(self.file_path):
                try:
                    self._doc = serialize.loads(
                        pathlib.Path(self.file_path).read_text(
                            encoding='utf-8'), rapport)
                except Exception as exc2:
                    print(f'TauDrive : « {self.file_path} » illisible — '
                          f'{exc2}', file=sys.stderr)
            if self._doc is None:
                nom = brut.get('name') if isinstance(brut, dict) else None
                self._doc = Document(name=nom if isinstance(nom, str)
                                     else 'gravure')
                self._illisible = brut
        if rapport and self.signaler is not None:
            self.signaler(list(rapport))

    def contenu_session(self) -> dict:
        """Le document tel qu'il s'écrit dans l'instantané de séance.

        Un onglet jamais ouvert se réécrit **tel qu'il a été lu** : le
        relire pour le réécrire coûterait tout ce que l'attente épargne,
        sans rien y changer. Un contenu illisible se garde de même tant
        que l'onglet reste vide : il ne se perd pas au premier instantané.
        """
        if self._brut is not None:
            return self._brut
        if self._illisible is not None and not self._doc.shapes:
            return self._illisible
        return serialize.document_to_dict(self._doc)

    def title(self) -> str:
        """Nom du travail, et non celui du fichier.

        Prendre le nom du fichier faisait qu'un onglet **déjà enregistré**
        gardait son ancien titre après un renommage : le nouveau nom
        n'apparaissait nulle part. C'est le nom du travail qui commande —
        il sert aussi de nom de dossier à l'export.
        """
        if self.en_attente():
            # le nom que la relecture donnera, sans relire : voir
            # `serialize.document_from_dict`
            nom = self._brut.get('name', 'gravure')
            nom = nom if isinstance(nom, str) else 'gravure'
        else:
            nom = self.document.name
        name = nom or (
            pathlib.Path(self.file_path).stem if self.file_path else '')
        return ('* ' if self.dirty else '') + (name or 'sans titre')


def _escape_html(texte: str) -> str:
    """Texte utilisable dans un fragment HTML.

    Un message d'erreur porte souvent un chemin, parfois des chevrons :
    les poser tels quels dans du RichText en avalerait la moitié.
    """
    return (str(texte).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


class NoteBar(QStatusBar):
    """Barre d'état qui laisse le temps de lire ce qu'elle dit.

    Le résumé du document — formes, passes, durée — se réécrit 120 ms
    après chaque changement. Il effaçait le message qui venait de dire ce
    qu'on avait fait : « 3 formes groupées », « 4 blocs alignés à gauche »
    s'affichaient le temps d'un éclair. Un message à durée garde désormais
    la barre jusqu'à son terme ; le résumé l'attend — voir
    `MainWindow._status_due`.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fin = 0.0

    def showMessage(self, text: str, timeout: int = 0) -> None:
        self._fin = (time.monotonic() + timeout / 1000.0) if timeout > 0 \
            else 0.0
        super().showMessage(text, timeout)

    def note_ms(self) -> int:
        """Millisecondes restantes au message en cours, 0 s'il n'y en a
        pas — ou si c'est le résumé, qui n'a pas de terme."""
        reste = self._fin - time.monotonic()
        return int(reste * 1000) + 1 if reste > 0 else 0


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setStatusBar(NoteBar(self))
        self.setWindowTitle(f'{APP_NAME} — TAU 10×10 SMART')
        icon = app_icon()
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(1280, 820)
        self.optimize = True
        self.group_recipes = False

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabBarDoubleClicked.connect(self._rename_tab)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setToolTip(
            'Double-cliquez un onglet pour le renommer.\n'
            'Le nom est celui du travail : il sert aussi de nom de dossier '
            'à l\'export.')

        # Bouton « nouvel onglet ». Il vit dans le coin de la barre
        # d'onglets, donc **hors de toute barre d'outils** : la feuille de
        # style du thème ne l'atteignait pas et il restait plat, sans
        # couleur ni survol — invisible sur les thèmes sombres. Il porte
        # maintenant sa propre icône vectorielle et son propre style.
        self.w_add_tab = QToolButton()
        self.w_add_tab.setToolTip('Nouvel onglet  (Ctrl+N)')
        self.w_add_tab.setAutoRaise(False)
        self.w_add_tab.setFixedSize(44, 32)
        self.w_add_tab.setIconSize(QSize(22, 22))
        self.w_add_tab.setCursor(Qt.PointingHandCursor)
        self.w_add_tab.clicked.connect(self._new_document)
        self._style_add_tab()
        # Le bouton suit le dernier onglet, au lieu de rester plaqué au
        # bord droit de la fenêtre — à l'autre bout de l'écran quand deux
        # onglets seulement sont ouverts.
        #
        # Un widget de coin **vide** réserve malgré tout la place : sans
        # lui, des onglets nombreux occuperaient toute la barre et le
        # bouton viendrait se poser dessus.
        self.w_add_tab.setParent(self.tabs)
        self.tabs.tabBar().installEventFilter(self)
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self.tabs.currentChanged.connect(self._place_add_tab)
        # Colonne 2 : le plan de travail, ou le gestionnaire de recettes
        # quand on l'appelle. Une pile plutôt qu'une fenêtre : on règle une
        # recette à la place du dessin, pas par-dessus, et l'on revient
        # d'un bouton.
        self.center = QStackedWidget()
        self.center.addWidget(self.tabs)
        self.setCentralWidget(self.center)

        # sauvegarde silencieuse : ni question à la fermeture, ni geste à
        # faire. L'instantané est réécrit au repos, pas à chaque frappe.
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.setInterval(2500)
        self._session_timer.timeout.connect(self._save_session)

        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(600)
        self._history_timer.timeout.connect(self._record_history)

        # Retour de la barre d'état à sa couleur normale après un export.
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)
        #: Pas de hachure retiré par Ctrl+F, pour que Ctrl+H le rende.
        self._hatch_memo: dict[str, float] = {}
        #: Vrai pendant qu'un état de l'historique est remis en place :
        #: ce qui s'ensuit n'est pas une modification de l'utilisateur.
        self._restoring = False

        # Le rafraîchissement de la barre d'état recalcule les trajectoires :
        # on ne le déclenche qu'une fois l'utilisateur arrêté, sinon chaque
        # pixel de déplacement à la souris paierait le calcul complet.
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(120)
        self._status_timer.timeout.connect(self._status_due)

        self.shape_list = QListWidget()
        self.shape_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.shape_list.itemSelectionChanged.connect(self._list_selected)
        self.shape_list.itemDoubleClicked.connect(self._rename_shape)
        self.shape_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.shape_list.customContextMenuRequested.connect(self._shape_menu)
        # Le gestionnaire de process s'ouvre depuis la **barre d'outils**,
        # bordé à droite avec la bibliothèque : ce sont deux réserves, et
        # non des outils de dessin. La colonne ne porte plus que la liste.
        colonne = QWidget()
        pile = QVBoxLayout(colonne)
        pile.setContentsMargins(0, 0, 0, 0)
        pile.setSpacing(4)
        pile.addWidget(self.shape_list, 1)

        # **L'ordre de la liste est l'ordre de gravure.** Il ne se réglait
        # qu'au clic droit, dans un menu de quinze entrées : personne ne
        # l'y cherchait. Deux flèches sous la liste, là où l'on regarde,
        # et le même geste au clavier.
        rangee_ordre = QHBoxLayout()
        rangee_ordre.setContentsMargins(2, 0, 2, 0)
        rangee_ordre.setSpacing(4)
        self.w_order_up = QToolButton()
        self.w_order_up.setIcon(icons.icon('monter'))
        self.w_order_up.setIconSize(QSize(18, 18))
        self.w_order_up.setToolTip(
            'Monter dans la liste — c\'est l\'ordre de gravure : la forme '
            'sera gravée plus tôt.\nAlt+↑ · fonctionne sur toute la '
            'sélection')
        self.w_order_up.clicked.connect(lambda: self._reorder_selection(-1))
        self.w_order_down = QToolButton()
        self.w_order_down.setIcon(icons.icon('descendre'))
        self.w_order_down.setIconSize(QSize(18, 18))
        self.w_order_down.setToolTip(
            'Descendre dans la liste — la forme sera gravée plus tard.\n'
            'Alt+↓ · fonctionne sur toute la sélection')
        self.w_order_down.clicked.connect(lambda: self._reorder_selection(1))
        rangee_ordre.addWidget(self.w_order_up)
        rangee_ordre.addWidget(self.w_order_down)
        self.w_order_note = QLabel('Ordre de gravure')
        self.w_order_note.setStyleSheet(theme.css('text_dim', 11))
        self.w_order_note.setToolTip(
            'Les formes sont gravées de haut en bas, sauf si « Grouper par '
            'process » est coché à l\'export :\nle regroupement passe alors '
            'devant, pour éviter les changements d\'outil inutiles.')
        rangee_ordre.addWidget(self.w_order_note, 1)
        pile.addLayout(rangee_ordre)
        for raccourci, sens in (('Alt+Up', -1), ('Alt+Down', 1)):
            action = QAction(self)
            action.setShortcut(raccourci)
            action.triggered.connect(
                lambda _=False, d=sens: self._reorder_selection(d))
            self.addAction(action)

        dock_list = QDockWidget('Formes', self)
        dock_list.setObjectName('dock_formes')
        dock_list.setWidget(colonne)
        self.shape_list.setMinimumHeight(80)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock_list)

        # La recette vit en colonne 1, **sous la liste des formes** : c'est
        # ce qu'on vérifie avant de lancer, et cela se lit dans la même
        # colonne que la forme concernée. La colonne des propriétés reste
        # pour la géométrie.
        self.recipe = RecipeEditor()
        self.recipe.changed.connect(self._shape_edited)
        self.recipe.changed_many.connect(self._shapes_edited)
        self.recipe.saved.connect(self._recipe_saved)
        dock_recipe = QDockWidget('Process laser', self)
        dock_recipe.setObjectName('dock_process')
        dock_recipe.setWidget(in_scroll(self.recipe, 240))
        self.addDockWidget(Qt.LeftDockWidgetArea, dock_recipe)

        self.inspector = Inspector()
        self.inspector._shapes_source = lambda: self.document.shapes
        self.inspector.changed.connect(self._shape_edited)

        # Une forme montre ses propriétés ; plusieurs montrent celles du
        # **lot**. Les deux panneaux sont empilés au même endroit : c'est
        # la même question — « qu'est-ce que je manipule ? » — et elle se
        # lit toujours dans la même colonne.
        self.lot = LotPanel()
        self.lot.changed.connect(self._lot_edited)
        self.lot.grouped.connect(self._group)
        self.lot.ungrouped.connect(self._ungroup)
        self.lot.primary_asked.connect(self._show_primary)
        self.lot.note.connect(
            lambda texte: self.statusBar().showMessage(texte, 4000))
        self.inspector.lot_asked.connect(self._show_lot)
        self._insp_stack = QStackedWidget()
        self._insp_stack.addWidget(in_scroll(self.inspector, 340))
        self._insp_stack.addWidget(in_scroll(self.lot, 340))
        # Troisieme feuille : le montage a trois postes. Ses trois champs
        # ne se rangent ni dans le formulaire d'une forme ni dans celui
        # d'un lot — on y saisit trois references, pas une propriete.
        self.montage_form = montage.MontageForm()
        self.montage_form.changed.connect(self._montage_edited)
        self.montage_form.saved.connect(self._montage_saved)
        self._insp_stack.addWidget(in_scroll(self.montage_form, 340))
        dock_insp = QDockWidget('Propriétés', self)
        dock_insp.setObjectName('dock_proprietes')
        dock_insp.setWidget(self._insp_stack)
        self.addDockWidget(Qt.RightDockWidgetArea, dock_insp)

        self.job = JobPanel(Document())
        self.job.changed.connect(self._job_changed)
        dock_job = QDockWidget('Lot et série', self)
        dock_job.setObjectName('dock_lot')
        dock_job.setWidget(in_scroll(self.job, 230))
        self.addDockWidget(Qt.LeftDockWidgetArea, dock_job)

        self.laser = LaserPanel()
        dock_laser = QDockWidget('Source laser', self)
        dock_laser.setObjectName('dock_laser')
        dock_laser.setWidget(in_scroll(self.laser, 250))
        self.addDockWidget(Qt.RightDockWidgetArea, dock_laser)

        # Colonne 2 : le gestionnaire de recettes, à côté du plan de
        # travail. Régler une recette demande de voir le dessin sur lequel
        # elle s'applique — une fenêtre modale le cachait et obligeait à la
        # refermer pour vérifier.
        self.recipes_panel = recipes.RecipeManager(self)
        self.recipes_panel.saved.connect(self._recipes_stored)
        self.recipes_panel.done.connect(self._leave_recipes)
        self.center.addWidget(self.recipes_panel)
        self.splitDockWidget(dock_list, dock_recipe, Qt.Vertical)

        # Colonne 3 : le magasin d'outils, avec les propriétés. Lecture
        # seule, et **disponible en mode simple** : choisir un outil de la
        # machine est plus sûr que d'ajuster une fréquence à la main.
        # Bibliothèque : même disposition que le gestionnaire de process.
        # L'aperçu prend le plan de travail — un dessin se choisit en le
        # voyant grand — et l'arborescence prend les propriétés.
        self.library_panel = DrawingLibrary(self)
        self.library_panel.chosen_entry.connect(self._library_insert)
        self.library_panel.done.connect(self._leave_library)
        self.center.addWidget(self.library_panel)
        dock_biblio = QDockWidget('Dessins', self)
        dock_biblio.setObjectName('dock_bibliotheque')
        dock_biblio.setWidget(self.library_panel.tree)
        self.addDockWidget(Qt.RightDockWidgetArea, dock_biblio)

        # Gestionnaire de montages, à côté de la bibliothèque : il prend
        # le plan de travail **et** les propriétés — liste, éditeur et
        # aperçu tiennent ensemble, et les propriétés d'une forme n'ont
        # rien à dire pendant qu'on règle un gabarit.
        self.montages_panel = montagepanel.MontageManager(self)
        self.montages_panel.done.connect(self._leave_montages)
        self.montages_panel.pose_asked.connect(self._pose_from_manager)
        self.montages_panel.capture_asked.connect(self._capture_into_manager)
        self.montages_panel.saved.connect(self._montages_saved)
        self.center.addWidget(self.montages_panel)
        # les trois réserves partagent la colonne : chaque bouton dit ce
        # qu'il fera, quel que soit le chemin par lequel on est revenu
        self.center.currentChanged.connect(self._label_center_buttons)

        self.tools_panel = ToolStorePanel(self)
        self.tools_panel.chosen.connect(self.recipes_panel.load_tool)
        self.tools_panel.chosen.connect(self._tool_loaded)
        dock_tools = QDockWidget('Magasin d\'outils', self)
        dock_tools.setObjectName('dock_magasin')
        dock_tools.setWidget(in_scroll(self.tools_panel, 320))
        self.addDockWidget(Qt.RightDockWidgetArea, dock_tools)
        self.tabifyDockWidget(dock_insp, dock_tools)
        self.tabifyDockWidget(dock_insp, dock_biblio)
        dock_biblio.hide()
        dock_insp.raise_()
        # Le magasin ne paraît qu'en réglage de recettes : il prend la
        # place des propriétés, il n'a rien à faire là pendant qu'on dessine.
        dock_tools.hide()

        self.tabifyDockWidget(dock_list, dock_job)
        dock_list.raise_()

        # Aucun plafond de largeur : les colonnes se règlent à la souris et
        # gardent la largeur choisie d'une session à l'autre. Les bornes
        # d'origine — 300 à 460 px — empêchaient d'élargir les propriétés
        # pour lire une liste de polices ou un chemin d'export entier.
        self._docks = (dock_list, dock_job, dock_insp, dock_laser,
                       dock_recipe, dock_tools, dock_biblio)
        # Chaque dock porte un nom. Rien ne doit compter des positions
        # dans `_docks` : en retirer un décalait tous les index suivants
        # en silence, et l'on ouvrait le mauvais panneau.
        self._dock_list = dock_list
        self._dock_job = dock_job
        self._dock_insp = dock_insp
        self._dock_laser = dock_laser
        self._dock_recipe = dock_recipe
        self._dock_tools = dock_tools
        self._dock_biblio = dock_biblio
        self._expert_docks = (dock_laser, dock_job)
        for dock in self._docks:
            dock.setMinimumWidth(180)
            dock.setMaximumWidth(16777215)

        self._build_toolbar()
        # Les libellés de la barre sont un réglage de poste : il se relit
        # au lancement, une fois les boutons posés.
        self._apply_toolbar_labels()
        self._restore_session()
        # Après la restauration, et non avant : `restoreState` remet les
        # panneaux tels qu'ils étaient à la fermeture, mode expert compris.
        # Un panneau expert visible en dernier ressortait donc en mode
        # simple au redémarrage suivant.
        self._apply_expert_visibility(recipes.expert())
        self._build_help_bar()
        self.statusBar().showMessage('Prêt')
        self._fitted = False

    # -- onglet courant ----------------------------------------------------
    #
    # `canvas` et `document` restent les noms utilisés partout ailleurs :
    # ce sont désormais des propriétés qui suivent l'onglet actif.

    @property
    def canvas(self) -> DocumentTab:
        tab = self.tabs.currentWidget()
        # un onglet restauré se monte la première fois qu'il devient
        # courant : tout ce qui passe par ici trouve un plan posé
        if tab is not None and not tab.monte:
            tab.monter()
        return tab

    @property
    def document(self) -> Document:
        tab = self.tabs.currentWidget()
        return tab.document if tab is not None else Document()

    def tabs_all(self) -> list[DocumentTab]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def new_tab(self, document: Document | None = None,
                file_path: str = '') -> DocumentTab:
        tab = DocumentTab(document if document is not None else Document(),
                          file_path)
        tab.selection_changed.connect(self._selection_changed)
        tab.geometry_changed.connect(self._geometry_changed)
        tab.step_changed.connect(self._step_changed)
        tab.step_focus_requested.connect(self._focus_step)
        tab.edit_requested.connect(self._edit_requested)
        index = self.tabs.addTab(tab, tab.title())
        QTimer.singleShot(0, self._place_add_tab)
        self.tabs.setCurrentIndex(index)
        QTimer.singleShot(0, tab.fit)
        return tab

    def _waiting_tab(self, brut: dict, file_path: str = '') -> DocumentTab:
        """Ajoute, sans le rendre courant, un onglet qui attend d'être
        montré : son document ne sera relu, et son plan posé, qu'au
        premier clic — voir `_restore_session`."""
        tab = DocumentTab(None, file_path, brut=brut)
        tab.signaler = lambda rapport, t=tab: self._report_repairs(
            t.title(), rapport, quiet=True)
        tab.selection_changed.connect(self._selection_changed)
        tab.geometry_changed.connect(self._geometry_changed)
        tab.step_changed.connect(self._step_changed)
        tab.step_focus_requested.connect(self._focus_step)
        tab.edit_requested.connect(self._edit_requested)
        self.tabs.addTab(tab, tab.title())
        return tab

    def eventFilter(self, watched, event):
        """Replace le bouton d'ajout dès que la barre d'onglets bouge."""
        if (watched is self.tabs.tabBar()
                and event.type() in (QEvent.Resize, QEvent.LayoutRequest,
                                     QEvent.Show)):
            self._place_add_tab()
        return super().eventFilter(watched, event)

    def _place_add_tab(self) -> None:
        """Colle le bouton juste à droite du dernier onglet.

        Quand les onglets remplissent la barre, il se range contre le bord
        droit plutôt que de déborder : mieux vaut un bouton serré qu'un
        bouton hors de vue.
        """
        bar = self.tabs.tabBar()
        if bar.count() == 0:
            return

        # La barre s'arrête avant le bouton : sans cette réserve, des
        # onglets nombreux occuperaient toute la largeur et le bouton
        # viendrait se poser sur le dernier. Qt affiche alors ses flèches
        # de défilement, ce qui est le comportement attendu.
        reserve = self.w_add_tab.width() + 10
        voulu = max(60, self.tabs.width() - reserve)
        if bar.maximumWidth() != voulu:
            bar.setMaximumWidth(voulu)
            QTimer.singleShot(0, self._place_add_tab)
            return

        last = bar.tabRect(bar.count() - 1)
        coin = bar.mapTo(self.tabs, QPoint(min(last.right() + 4, bar.width()),
                                           0))
        limite = self.tabs.width() - self.w_add_tab.width() - 4
        y = coin.y() + max(0, (bar.height() - self.w_add_tab.height()) // 2)
        self.w_add_tab.move(min(coin.x(), max(0, limite)), y)
        self.w_add_tab.raise_()
        self.w_add_tab.show()

    def _style_add_tab(self) -> None:
        """Icône et couleurs du bouton d'ajout, accordées au thème courant."""
        palette = theme.current()
        self.w_add_tab.setIcon(icons.icon('plus', palette.text))
        self.w_add_tab.setStyleSheet(
            f'QToolButton {{ border: 1px solid {palette.border};'
            f' border-radius: 5px; background: {palette.panel};'
            f' margin: 2px 4px; }}'
            f'QToolButton:hover {{ background: {palette.panel_hi};'
            f' border-color: {palette.accent}; }}'
            f'QToolButton:pressed {{ background: {palette.accent_deep}; }}')

    def _retitle(self, tab: DocumentTab) -> None:
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self.tabs.setTabText(index, tab.title())
            self.tabs.setTabToolTip(index, tab.file_path or 'non enregistré')

    def _touch(self) -> None:
        """Marque le document courant comme modifié et programme l'instantané."""
        tab = self.canvas
        if tab is not None and not tab.dirty:
            tab.dirty = True
            self._retitle(tab)
        self._session_timer.start()
        # Restituer un état n'est pas une modification à retenir. Sans
        # cette garde, le rechargement provoqué par un « annuler »
        # reprogrammait un instantané, que le « refaire » suivant posait
        # avant de se déplacer — coupant du même coup la branche qu'il
        # voulait justement parcourir.
        if self._restoring:
            return
        # les instantanés sont regroupés dans le temps : un déplacement à
        # la souris produit des dizaines de modifications, qui doivent se
        # défaire d'un seul coup
        self._history_timer.start()

    def _record_history(self) -> None:
        tab = self.canvas
        if tab is not None and tab.history.record(tab.document):
            self._update_history_actions()

    def _update_history_actions(self) -> None:
        tab = self.canvas
        annulables, refaisables = tab.history.depth() if tab else (0, 0)
        self.w_undo.setEnabled(bool(annulables))
        self.w_redo.setEnabled(bool(refaisables))
        self.w_undo.setToolTip(f'Annuler  (Ctrl+Z) — {annulables} coup(s)'
                               if annulables else 'Rien à annuler')
        self.w_redo.setToolTip(f'Refaire  (Ctrl+Y) — {refaisables} coup(s)'
                               if refaisables else 'Rien à refaire')

    def _undo(self) -> None:
        self._apply_history('undo')

    def _redo(self) -> None:
        self._apply_history('redo')

    def _apply_history(self, sens: str) -> None:
        """Remonte ou redescend d'un cran dans l'historique de l'onglet.

        L'instantané en attente est d'abord posé : sans cela, la dernière
        modification — celle qu'on veut justement défaire — n'aurait pas
        encore été retenue.
        """
        tab = self.canvas
        if tab is None:
            return
        if self._history_timer.isActive():
            self._history_timer.stop()
            tab.history.record(tab.document)
        document = (tab.history.undo() if sens == 'undo'
                    else tab.history.redo())
        if document is None:
            self.statusBar().showMessage(
                'Rien à annuler' if sens == 'undo' else 'Rien à refaire',
                2000)
            return
        document.name = tab.document.name          # le nom d'onglet demeure
        self._restoring = True
        try:
            tab.document = document
            tab.passes_cache = None
            tab.reload()
            self.job.set_document(document)
            self.inspector.set_shape(None)
            self.recipe.set_shape(None)
            self._refresh_list()
            self._update_history_actions()
            self._update_status()
            tab.dirty = True
            self._retitle(tab)
        finally:
            self._restoring = False
        self._history_timer.stop()
        self._session_timer.start()
        annulables, refaisables = tab.history.depth()
        self.statusBar().showMessage(
            ('Annulé' if sens == 'undo' else 'Refait')
            + f' · {annulables} annulable(s), {refaisables} refaisable(s)',
            3000)

    def _rename_tab(self, index: int) -> None:
        """Renomme un onglet — donc le travail qu'il porte.

        Ce n'est pas qu'une étiquette : le nom du travail sert de nom de
        dossier à l'export et de nom de fichier proposé à l'enregistrement.
        """
        tab = self.tabs.widget(index)
        if tab is None:
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, 'Renommer l\'onglet',
                                        'Nom du travail :',
                                        text=tab.document.name)
        name = name.strip()
        if not ok or not name or name == tab.document.name:
            return
        tab.document.name = name
        self._retitle(tab)
        if tab is self.canvas:
            self.job.set_document(tab.document)
        self._touch()

    def _tab_changed(self) -> None:
        tab = self.canvas
        if tab is None:
            self.inspector.set_shape(None)
            self.shape_list.clear()
            return
        self.job.set_document(tab.document)
        self._refresh_list()
        self._selection_changed()
        self._update_history_actions()
        self._update_status()

    def _close_tab(self, index: int) -> None:
        """Ferme un onglet, sans rien demander.

        L'instantané de session est réécrit dans la foulée : un onglet
        fermé par mégarde se retrouve dans le fichier de session tant
        qu'il n'a pas été remplacé, et un onglet enregistré reste sur
        disque de toute façon.
        """
        tab = self.tabs.widget(index)
        if tab is None:
            return
        # L'onglet est conservé **avec son contenu** : un onglet fermé par
        # mégarde se rouvre, et l'on retrouve la plaque d'avant-hier au
        # mot-clé. Un document vide n'a rien à garder.
        if tab.document.shapes:
            try:
                session.remember_closed(
                    tab.document.name,
                    serialize.dumps(tab.document, indent=None),
                    tab.file_path,
                    _keywords(tab.document))
            except Exception as exc:
                avale('onglet fermé : mots-clés', exc)
                pass
        self.tabs.removeTab(index)
        QTimer.singleShot(0, self._place_add_tab)
        tab.deleteLater()
        if self.tabs.count() == 0:
            self.new_tab()
        self._save_session()

    # -- session -----------------------------------------------------------

    def _restore_session(self) -> None:
        """Rouvre la session précédente telle qu'elle était, ou un onglet vierge.

        L'instantané prime sur la liste des fichiers ouverts : il contient
        aussi les documents **jamais enregistrés**, qui seraient sinon
        perdus au premier redémarrage.
        """
        session.restore_window(self)
        # **Seul l'onglet actif est ouvert.** Les autres attendent qu'on
        # les clique : leur document n'est pas relu, leur plan pas posé.
        # Chaque onglet restauré devenait courant à son tour, le temps de
        # calculer trajectoires et durée qu'on remplaçait aussitôt — près
        # de dix secondes au lancement pour quatre onglets, dont deux
        # dessins de 140 000 et 220 000 points.
        #
        # Les signaux des onglets se taisent pendant la restauration : le
        # résumé n'est calculé qu'une fois, pour l'onglet qui reste devant.
        opened = 0
        actif = -1
        self.tabs.blockSignals(True)
        try:
            for entry in session.load_snapshot():
                if self._restore_entry(entry):
                    opened += 1
                    if entry.get('actif'):
                        actif = self.tabs.count() - 1
            if opened == 0:
                for path in session.open_documents():
                    if self._load_into_tab(path, quiet=True):
                        opened += 1
            if opened == 0:
                self.new_tab()
            # l'onglet qui était devant à la fermeture ; à défaut, le
            # dernier, comme avant
            self.tabs.setCurrentIndex(actif if actif >= 0
                                      else self.tabs.count() - 1)
        finally:
            self.tabs.blockSignals(False)
        for tab in self.tabs_all():
            self._retitle(tab)
        QTimer.singleShot(0, self._place_add_tab)
        self._tab_changed()

    def _restore_entry(self, entry: dict) -> bool:
        """Rouvre un document de l'instantané. Faux si rien n'est lisible.

        Le contenu mémorisé prime sur le fichier : c'est lui qui porte les
        modifications non enregistrées. Le fichier ne sert de recours que
        si l'instantané est illisible.
        """
        path = str(entry.get('path') or '')
        raw = entry.get('document')
        if isinstance(raw, dict):
            # relu au premier clic — les recours d'un contenu illisible
            # sont dans `DocumentTab._relire`
            tab = self._waiting_tab(raw, path)
            tab.dirty = bool(entry.get('dirty'))
            return True
        return self._load_into_tab(path, quiet=True) if path else False

    def _save_session(self) -> None:
        """Écrit l'instantané. Appelé souvent, donc silencieux et bon marché."""
        entries = []
        courant = self.tabs.currentWidget()
        for tab in self.tabs_all():
            try:
                entree = {
                    'path': tab.file_path,
                    'dirty': tab.dirty,
                    'document': tab.contenu_session(),
                }
            except Exception:
                continue          # un onglet fâché ne doit pas bloquer les autres
            # l'onglet de devant, rouvert devant au prochain lancement ; une
            # version antérieure ignore la clé et rouvre le dernier
            if tab is courant:
                entree['actif'] = True
            entries.append(entree)
        session.save_snapshot(entries)
        session.remember_open([t.file_path for t in self.tabs_all()
                               if t.file_path])

    def _load_into_tab(self, path: str, quiet: bool = False) -> bool:
        """Ouvre un document dans un nouvel onglet. Faux en cas d'échec.

        La construction de l'onglet est dans le même filet que la lecture :
        un document qui se lit mais dont la géométrie fâche l'affichage
        empêcherait sinon **l'application entière de démarrer**, puisque la
        session rouvre les documents précédents dès la construction de la
        fenêtre.
        """
        if not session.reachable(path):
            message = (f'« {pathlib.Path(path).name} » ne répond pas.\n'
                       'Le partage est peut-être hors ligne — le document '
                       'reste dans la liste des récents.')
            if quiet:
                print(f'TauDrive : {path} injoignable au démarrage',
                      file=sys.stderr)
            else:
                QMessageBox.information(self, 'Ouvrir', message)
            return False
        rapport: list[str] = []
        try:
            document = serialize.loads(
                pathlib.Path(path).read_text(encoding='utf-8'), rapport)
            self.new_tab(document, path)
        except Exception as exc:
            if not quiet:
                QMessageBox.critical(self, 'Ouvrir',
                                     f'Lecture impossible :\n{exc}')
            else:
                print(f'TauDrive : « {path} » ignoré au démarrage — {exc}',
                      file=sys.stderr)
            return False
        if rapport:
            self._report_repairs(pathlib.Path(path).name, rapport, quiet)
        session.remember_document(path)
        return True

    def _report_repairs(self, nom: str, rapport: list, quiet: bool) -> None:
        """Dit quelles valeurs illisibles ont été remplacées par leur
        défaut — voir `model.value_like`.

        Le document s'ouvre, pour ne pas perdre le travail ; mais une
        puissance ou une vitesse remise en silence à sa valeur par défaut
        partirait à la gravure sans que personne ne l'ait choisie. On le
        dit donc avant, valeur par valeur.
        """
        lignes = [f'TauDrive : « {nom} », valeur illisible remplacée par '
                  f'son défaut — {r}' for r in rapport]
        if quiet:
            # au démarrage : sur stderr pour le journal, et **à l'écran**
            # — l'exécutable n'a pas de console, et une puissance remise à
            # 100 % dans l'instantané de séance partait à la gravure sans
            # que personne ne l'ait su
            print('\n'.join(lignes), file=sys.stderr)
            QTimer.singleShot(0, lambda: self._alert_repairs(
                f'Reprise de « {nom} »', list(rapport)))
            return
        montre = '\n'.join(f'• {r}' for r in rapport[:12])
        reste = (f'\n… et {len(rapport) - 12} autre(s)'
                 if len(rapport) > 12 else '')
        QMessageBox.warning(
            self, 'Ouvrir',
            f'« {nom} » portait {len(rapport)} valeur(s) illisible(s), '
            f'remplacée(s) par leur valeur par défaut. Vérifiez ces '
            f'réglages avant de graver :\n\n{montre}{reste}')

    def _alert_repairs(self, titre: str, lignes: list) -> None:
        """Montre **sans bloquer** des valeurs remplacées par leur défaut.

        Non modale : elle surgit au démarrage, après un collage, à la
        relecture de la bibliothèque de process, et ne doit rien arrêter
        — mais elle reste à l'écran tant qu'on ne l'a pas fermée.
        """
        if not lignes:
            return
        montre = '\n'.join(f'• {r}' for r in lignes[:12])
        reste = (f'\n… et {len(lignes) - 12} autre(s)'
                 if len(lignes) > 12 else '')
        boite = QMessageBox(
            QMessageBox.Icon.Warning, titre,
            f'{len(lignes)} valeur(s) illisible(s), remplacée(s) par leur '
            f'valeur par défaut. Vérifiez ces réglages avant de graver :'
            f'\n\n{montre}{reste}',
            QMessageBox.StandardButton.Ok, self)
        boite.setModal(False)
        boite.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        boite.show()
        #: la dernière alerte montrée — l'autotest la lit
        self.last_repair_alert = (titre, list(lignes))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_add_tab()

    def showEvent(self, event) -> None:
        """Ajuste la vue une fois les panneaux réellement disposés."""
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            for tab in self.tabs_all():
                QTimer.singleShot(0, tab.fit)
            QTimer.singleShot(0, self._balance_docks)
            QTimer.singleShot(0, self._tab_changed)

    def _balance_docks(self) -> None:
        """Donne la hauteur au panneau qu'on utilise, pas à celui qu'on surveille.

        Empilés, les panneaux se partagent la colonne à parts égales : les
        propriétés d'un texte, qui comptent une vingtaine de champs, se
        retrouvaient réduites à quelques lignes par un panneau laser qui
        n'en a que six.
        """
        (dock_list, dock_job, dock_insp, dock_laser,
         dock_recipe, dock_tools, dock_biblio) = self._docks
        # hauteur : les propriétés priment sur la surveillance du laser,
        # et la recette a besoin d'autant de place que la liste des formes
        self.resizeDocks([dock_insp, dock_laser], [3, 1], Qt.Vertical)
        self.resizeDocks([dock_list, dock_recipe], [2, 3], Qt.Vertical)
        # largeur : assez pour que les formulaires tiennent sans rognage
        self.resizeDocks([dock_insp], [385], Qt.Horizontal)
        self.resizeDocks([dock_list], [250], Qt.Horizontal)

    # -- barre d'outils ----------------------------------------------------

    #: Libellés abrégés de la barre d'outils, quand ils paraissent.
    #:
    #: Le nom entier reste dans le menu et dans l'infobulle ; sous une
    #: icône de vingt-six pixels, « Exporter le dessin (DXF, EPS, AI)… »
    #: élargirait le bouton à lui seul plus que les six qui le suivent.
    COURTS = {
        'Dégrouper': 'Dégrp.',
        'Redimensionner…': 'Cotes',
        'Importer un dessin…': 'Importer',
        'Exporter le dessin (DXF, EPS, AI)…': 'Export dess.',
        'Traitement dessin': 'Traiter',
        'Bibliothèque…': 'Biblioth.',
        'Montage à DataMatrix': 'Montage',
        'Plaque codée': 'Plaque',
    }

    @classmethod
    def _court(cls, label: str) -> str:
        """Libellé de barre d'outils : court, et sans points de suite."""
        if label in cls.COURTS:
            return cls.COURTS[label]
        nu = label.split(' (')[0].rstrip('… ').strip()
        return nu if len(nu) <= 12 else nu[:11].rstrip() + '.'

    def _act(self, label, slot, shortcut=None, tip='', glyph='', tint=None):
        """Action nommée, avec son icône teintée par le thème."""
        a = QAction(label, self)
        # `iconText` est ce que la barre affiche quand elle montre les
        # libellés ; `text` reste le nom entier, pour le menu.
        a.setIconText(self._court(label))
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(shortcut)
        if tip:
            a.setToolTip(tip)
        if glyph:
            a.setIcon(icons.icon(glyph, tint))
            self._actions.append((a, glyph, tint))
        return a

    def _build_toolbar(self) -> None:
        """Menus, puis deux barres d'outils réduites à ce qui sert souvent.

        Ce qui se règle une fois par poste — mode expert, thème,
        ordonnancement — a quitté la barre d'outils pour le menu
        *Paramètres* : ce sont des réglages, pas des outils.
        """
        self._actions: list[tuple[QAction, str, str | None]] = []
        self._build_menus()

        tb = self.addToolBar('Outils')
        tb.setObjectName('barre_outils')
        tb.setMovable(False)
        # **Icônes seules par défaut.** Vingt libellés de front débordaient
        # de la barre sur un écran d'atelier ; les icônes tiennent, et
        # l'infobulle porte le nom entier avec son raccourci. Qui préfère
        # lire les noms les fait paraître sous les icônes — *Paramètres ▸
        # Libellés sous les icônes* — et ce sont alors des libellés
        # **courts** qui s'affichent, pour que la barre ne double pas de
        # largeur : voir `_court`.
        self._toolbar = tb
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        tb.setIconSize(QSize(26, 26))

        def act(label, slot, shortcut=None, tip='', glyph='', tint=None,
                bar=None):
            a = self._act(label, slot, shortcut, tip, glyph, tint)
            (bar if bar is not None else tb).addAction(a)
            return a

        # Annuler et refaire en tête : ce sont les deux boutons qu'on
        # cherche en premier quand quelque chose vient de mal tourner.
        self.w_undo = act('Annuler', self._undo, 'Ctrl+Z', glyph='annuler')
        self.w_redo = act('Refaire', self._redo, 'Ctrl+Y', glyph='refaire')
        tb.addSeparator()

        # Grouper et dégrouper suivent immédiatement : ils s'emploient sur
        # ce qu'on vient de poser, et non en fin de course avec les gestes
        # d'édition.
        self.w_grouper = act(
            'Grouper', self._group, 'Q',
            'Réunit la sélection : ses formes se sélectionnent et se '
            'déplacent ensuite d\'un bloc, chacune garde sa process   ·   Q',
            glyph='grouper')
        self.w_degrouper = act(
            'Dégrouper', self._ungroup, 'S',
            'Défait le groupe de la sélection : chaque forme redevient '
            'indépendante   ·   S', glyph='degrouper')
        # **Une lettre seule ne vaut que sur le dessin.** Q et S agissent
        # quand le plan de travail ou la liste des formes a le focus ;
        # dans un champ, une liste déroulante, un nom à taper, la lettre
        # reste une lettre.
        for action in (self.w_grouper, self.w_degrouper):
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.tabs.addAction(action)
            self.shape_list.addAction(action)
        tb.addSeparator()

        act('Rectangle', self._add_rect, 'Ctrl+R', glyph='rectangle')
        act('Cercle', self._add_circle, 'Ctrl+L',
            'Cercle ou ellipse', glyph='cercle')
        act('Texte', self._add_text, 'Ctrl+T', glyph='texte')
        # Un bouton qui pose, une flèche qui choisit la symbologie —
        # exactement comme la date. Poser la même plaque que la dernière
        # fois est le geste de série ; changer de symbologie, l'exception
        # qui mérite un menu, pas un aller-retour dans les propriétés.
        self.w_code_button = QToolButton()
        self.w_code_button.setIcon(icons.icon('code'))
        self.w_code_button.setIconSize(QSize(26, 26))
        self.w_code_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.w_code_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.w_code_button.clicked.connect(
            lambda: self._add_code_in_frame())
        self.w_code_menu = QMenu(self.w_code_button)
        # **La prochaine plaque, réglée d'avance** : cadre, taille,
        # position et texte, au bout de la flèche plutôt que dans une
        # fenêtre à part. Chaque champ s'enregistre aussitôt.
        self.w_plate_form = codeplate.plate_defaults_form(self.w_code_menu)
        self.w_plate_form.capture_asked.connect(self._capture_plate)
        plaque = QWidgetAction(self.w_code_menu)
        plaque.setDefaultWidget(self.w_plate_form)
        self.w_code_menu.addAction(plaque)
        self.w_code_menu.addSeparator()
        self.w_code_menu.aboutToShow.connect(self.w_plate_form.load)
        self.w_code_kinds: list[QAction] = []
        groupe = QActionGroup(self.w_code_menu)
        groupe.setExclusive(True)
        for valeur, libelle in barcode.KINDS:
            a = self.w_code_menu.addAction(libelle)
            a.setCheckable(True)
            a.setData(valeur)
            a.setStatusTip(self._code_kind_help(valeur))
            a.triggered.connect(
                lambda _=False, k=valeur: self._add_code_in_frame(k))
            groupe.addAction(a)
            self.w_code_kinds.append(a)
        self.w_code_menu.aboutToShow.connect(self._mark_code_kind)
        self.w_code_button.setMenu(self.w_code_menu)
        tb.addWidget(self.w_code_button)
        # Le raccourci vit sur une action, que la barre n'affiche pas :
        # le bouton est déjà là, en double il prendrait deux places.
        self.w_code_action = self._act(
            'Code…', lambda: self._add_code_in_frame(), 'Ctrl+B',
            'Code et texte ajustés à leurs cadres, comme sur les plaques '
            'de production', glyph='code')
        self.addAction(self.w_code_action)
        self._mark_code_kind()
        # Le montage a trois postes est un geste de production a part
        # entiere, pas une variante du bouton code : il pose six formes
        # d'un coup, a des cotes qui ne se negocient pas.
        # Un bouton qui pose, une flèche qui choisit le gabarit — comme
        # le bouton Code. Poser le même montage que la dernière fois est
        # le geste de série ; en changer, l'exception qui mérite un menu.
        self.w_montage_button = QToolButton()
        self.w_montage_button.setIcon(icons.icon('montage3'))
        self.w_montage_button.setIconSize(QSize(26, 26))
        self.w_montage_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.w_montage_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.w_montage_button.clicked.connect(lambda: self._add_montage())
        self.w_montage_menu = QMenu(self.w_montage_button)
        # **Le prochain montage, réglé d'avance** : cadre, marge, taille,
        # positions, au bout de la flèche — comme la prochaine plaque.
        # Construit une fois : le menu se remplit à chaque ouverture, mais
        # le formulaire n'est que relu.
        self.w_montage_form = montagepanel.ProchainMontage(
            self.w_montage_menu)
        self.w_montage_form.capture_asked.connect(self._capture_montage)
        self.w_montage_form.changed.connect(self._gabarits_changed)
        prochain = QWidgetAction(self.w_montage_menu)
        prochain.setDefaultWidget(self.w_montage_form)
        self.w_montage_menu.addAction(prochain)
        self.w_montage_menu.addSeparator()
        self._montage_actions: list[QAction] = []
        self.w_montage_menu.aboutToShow.connect(self._fill_montage_menu)
        self.w_montage_button.setMenu(self.w_montage_menu)
        self.w_montage_button.setToolTip(
            'Pose le montage à DataMatrix en tête de liste, chaque texte '
            'lié à son code.\nLa flèche le règle, en choisit un autre ou '
            'ouvre le gestionnaire de montages.   Ctrl+Maj+B')
        tb.addWidget(self.w_montage_button)
        self.w_montage_action = self._act(
            'Montage à DataMatrix…', lambda: self._add_montage(),
            'Ctrl+Maj+B',
            'Les DataMatrix du montage et leurs textes, aux cotes du '
            'gabarit — chaque texte lié à son propre code',
            glyph='montage3')
        self.addAction(self.w_montage_action)
        act('Importer un dessin…', self._import_dxf, 'Ctrl+I',
            'DXF, PDF, Illustrator, EPS, SVG — et CorelDRAW si un '
            'convertisseur est installé   ·   Ctrl+I', glyph='import_dessin')
        # Son symétrique : le dessin qui repart vers un fichier. Il était
        # au menu seulement, sans icône, alors qu'il se fait aussi souvent
        # que l'import — un client qui redemande son plan.
        # Sans raccourci : il appartient à l'entrée du menu. Deux actions
        # qui réclament Ctrl+Maj+E le rendent ambigu, et Qt n'en déclenche
        # alors aucune.
        act('Exporter le dessin (DXF, EPS, AI)…', self._export_vector,
            tip='Pour un bureau d\'études, un client, un graphiste — pas '
                'pour la machine.', glyph='export_dessin')
        # Un bouton qui pose, une flèche qui règle. Poser la date est le
        # geste courant ; en changer le format, l'exception.
        self.w_date_button = QToolButton()
        self.w_date_button.setIcon(icons.icon('date'))
        self.w_date_button.setIconSize(QSize(26, 26))
        self.w_date_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.w_date_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.w_date_button.setToolTip(
            'Pose la date du jour comme champ variable : elle est '
            'réévaluée\n'
            'à chaque export. La flèche ouvre format, police et taille.')
        self.w_date_button.clicked.connect(self._add_date)
        menu_date = QMenu(self.w_date_button)
        menu_date.addAction(self._act('Options de la date…',
                                      self._add_date_options))
        for libelle, motif, note in datestamp.FORMATS:
            a = menu_date.addAction(
                f'{libelle}   ({datestamp.sample(motif)})')
            a.setStatusTip(note)
            a.triggered.connect(
                lambda _=False, m=motif: self._add_date(fmt=m))
        self.w_date_button.setMenu(menu_date)
        tb.addWidget(self.w_date_button)

        act('Traitement dessin', self._treat, 'Ctrl+Shift+T',
            glyph='traiter')
        act('Couteau…', self._knife, 'Ctrl+K',
            'Donne une épaisseur au tracé et en rend le contour fermé — '
            'pour hachurer, décaler ou découper', glyph='couteau')
        act('Coupon…', self._add_coupon, 'Ctrl+Shift+C',
            'Grille d\'essai : un paramètre par axe, valeurs gravées '
            'à côté', glyph='coupon')
        tb.addSeparator()
        act('Dupliquer', self._duplicate, 'Ctrl+D', glyph='dupliquer')
        act('Redimensionner…', self._resize_selection, 'F2',
            'Cotes ou pourcentage, proportions au choix',
            glyph='redimensionner')
        act('Supprimer', self._delete, 'Del', glyph='supprimer',
            tint=theme.current().alarm)

        # *Ajuster* a quitté la barre pour le coin du plan de travail :
        # c'est un geste de vue, il se fait là où l'on regarde. Le
        # raccourci reste, sans bouton.
        self.addAction(self._act('Ajuster', lambda: self.canvas.fit(),
                                 'Ctrl+0', glyph='ajuster'))

        tb.addSeparator()
        # Une croix à quatre flèches plutôt que « Pas clavier » : la barre
        # est en icônes, et deux mots de texte au milieu y font une
        # verrue. Ce que le champ règle se lit dans l'aide au survol.
        etiquette_pas = QLabel()
        etiquette_pas.setPixmap(icons.icon('pas').pixmap(20, 20))
        etiquette_pas.setContentsMargins(6, 0, 4, 0)
        etiquette_pas.setToolTip(
            'Pas clavier : de combien les flèches déplacent une forme')
        tb.addWidget(etiquette_pas)
        # Étroit : c'est un nombre à trois chiffres, pas un chemin. Laissé
        # extensible, il occupait la moitié de la barre et repoussait tout
        # le reste hors de l'écran.
        self.w_step = Spin(NUDGE_DEFAULT, 0.001, 100.0, step=0.1,
                           decimals=3, suffix=' mm')
        self.w_step.setFixedWidth(STEP_FIELD_W)
        self.w_step.setToolTip(
            'Déplacement des formes aux flèches.\n'
            'Ctrl+flèche vient taper ici le pas · Entrée rend la main '
            'au plan\nMaj+flèche = ×10')
        self.w_step.valueChanged.connect(self._step_set)
        # Entrée ou Échap rendent le focus là d'où Ctrl+flèche l'a pris :
        # la forme est toujours sélectionnée, la flèche suivante la bouge.
        self.w_step.validated.connect(self._step_validated)
        self.w_step.escaped.connect(self._leave_step)
        tb.addWidget(self.w_step)

        # **Deux boutons bordés à droite.** Bibliothèque et gestionnaire de
        # process ne posent rien sur la plaque : ils ouvrent des réserves.
        # Les tenir à l'écart des outils de dessin évite de les prendre
        # l'un pour l'autre, et le ressort qui les y pousse garde l'écart
        # quelle que soit la largeur de la fenêtre.
        ressort = QWidget()
        ressort.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(ressort)
        self.w_library_action = act(
            'Bibliothèque…', self._library, 'Ctrl+J',
            'Dessins rangés une fois pour toutes : livrés avec TauDrive '
            'ou ajoutés par l\'atelier', glyph='bibliotheque')
        self.w_library_button = tb.widgetForAction(self.w_library_action)
        self.w_montages_action = act(
            'Montages…', self._toggle_montages, 'Ctrl+Shift+J',
            'Gestionnaire de montages : créer, dupliquer, ranger, régler '
            'cadre, taille et positions des postes', glyph='gabarits')
        self.w_montages_button = tb.widgetForAction(self.w_montages_action)
        self.w_recipes_action = act(
            'Process…', self._toggle_recipes, 'Ctrl+M',
            'Gestionnaire de process : créer, renommer, dupliquer, '
            'régler passes et profondeur', glyph='process')
        self.w_recipes_button = tb.widgetForAction(self.w_recipes_action)

        # deuxième rangée : la destination des fichiers
        self.addToolBarBreak()
        tb2 = self.addToolBar('Export')
        tb2.setObjectName('barre_export')
        tb2.setMovable(False)
        tb2.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        tb2.addWidget(QLabel(' Dossier d\'export '))
        self.w_export_dir = Combo()
        self.w_export_dir.setEditable(True)
        self.w_export_dir.setMinimumWidth(260)
        self.w_export_dir.setToolTip(
            'Dossiers d\'export mémorisés — un partage réseau convient.\n'
            'Chaque travail y reçoit son propre sous-dossier horodaté.')
        self._refresh_export_dirs()
        tb2.addWidget(self.w_export_dir)
        b = QPushButton('…')
        b.setFixedWidth(30)
        b.setToolTip('Choisir un dossier')
        b.clicked.connect(self._pick_export_dir)
        tb2.addWidget(b)

        # **Le bouton d'export ne ressemble à aucun autre.** C'est le
        # geste qui envoie le travail à la machine : deux fois plus large,
        # un triangle plein bien visible, et la couleur d'accord du thème.
        # On ne le cherche pas, on le voit.
        self.w_export_button = QToolButton()
        self.w_export_button.setText(' Exporter')
        self.w_export_button.setIcon(icons.icon('lancer_export'))
        self.w_export_button.setIconSize(QSize(24, 24))
        self.w_export_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.w_export_button.setToolTip(
            'Écrit les fichiers ISO + CLJOB exécutables par ClTerm  '
            '(Ctrl+E)')
        self.w_export_button.setMinimumWidth(190)
        self.w_export_button.setMinimumHeight(34)
        self.w_export_button.clicked.connect(self._export)
        tb2.addWidget(self.w_export_button)
        self._paint_export_button()

        # le raccourci vit dans le menu Fichier ; l'action reste pour lui
        act('Exporter…', self._export, 'Ctrl+E',
            'Écrit les fichiers ISO + CLJOB exécutables par ClTerm',
            glyph='exporter', bar=None).setVisible(False)

    def _build_menus(self) -> None:
        bar = self.menuBar()

        # --- Fichier ---
        menu = bar.addMenu('&Fichier')
        menu.addAction(self._act('Nouveau', self._new_document, 'Ctrl+N',
                                 glyph='nouveau'))
        menu.addAction(self._act('Ouvrir…', self._open_document, 'Ctrl+O',
                                 glyph='ouvrir'))
        self._recent_menu = menu.addMenu('Documents récents')
        self._recent_menu.aboutToShow.connect(self._fill_recent)
        menu.addSeparator()
        menu.addAction(self._act('Enregistrer', self._save, 'Ctrl+S',
                                 glyph='enregistrer'))
        menu.addAction(self._act('Enregistrer sous…', self._save_as,
                                 'Ctrl+Shift+S', glyph='enregistrer'))
        menu.addSeparator()
        menu.addAction(self._act('Copier', self._copy, 'Ctrl+C',
                                 'Copie la sélection — collable dans un '
                                 'autre onglet'))
        menu.addAction(self._act('Coller', self._paste, 'Ctrl+V',
                                 'Colle au même endroit, prêt à être '
                                 'déplacé aux flèches ou à la souris'))
        menu.addSeparator()
        menu.addAction(self._act('Exporter…', self._export, 'Ctrl+E',
                                 glyph='exporter'))
        menu.addAction(self._act(
            'Exporter en morceaux…', self._export_morceaux,
            tip='Dessin plus grand que le champ : un job par morceau, et '
                'les consignes de déplacement de la pièce entre deux'))
        menu.addAction(self._act(
            'Exporter le dessin (DXF, EPS, AI)…', self._export_vector,
            'Ctrl+Shift+E',
            'Pour un bureau d\'études, un client, un graphiste — pas '
            'pour la machine.', glyph='export_dessin'))
        menu.addSeparator()
        menu.addAction(self._act('Fermer l\'onglet', self._close_current,
                                 'Ctrl+W'))
        menu.addAction(self._act('Quitter', self.close, 'Ctrl+Q'))

        # --- Forme ---
        menu = bar.addMenu('F&orme')
        menu.addAction(self._act(
            'Retourner gauche ↔ droite', lambda: self._mirror('h'),
            'Ctrl+Shift+H',
            'Renverse la sélection autour de son centre — pour graver au '
            'dos d\'un verre, ou poser deux pièces en vis-à-vis'))
        menu.addAction(self._act(
            'Retourner haut ↕ bas', lambda: self._mirror('v'),
            'Ctrl+Shift+V', 'Renverse la sélection autour de son centre'))
        menu.addSeparator()
        menu.addAction(self._act(
            'Répéter en grille…', self._repeat_grid, 'Ctrl+Shift+R',
            'Recopie la sélection en colonnes et rangées, à un pas donné '
            '— vingt étiquettes sur une plaque'))
        menu.addAction(self._act(
            'Répéter en cercle…', self._repeat_circle, 'Ctrl+Shift+O',
            'Recopie la sélection autour d\'un centre — graduations d\'un '
            'cadran, rayons d\'une rosace, perçages d\'une bride'))
        menu.addSeparator()
        menu.addAction(self._act(
            'Convertir en tracé', self._convert_to_path, 'Ctrl+Shift+P',
            'Fige textes, rectangles et ellipses en polylignes : ils se '
            'séparent et se retournent, mais ne se retapent plus'))
        menu.addAction(self._act(
            'Cintrer un texte en arc…', self._bend_text, 'Ctrl+Shift+A',
            'Couche le texte sur un cercle — bague, médaillon, pourtour '
            'd\'une plaque ronde'))
        menu.addSeparator()
        # Ctrl+G et Ctrl+Maj+G ne se tapent pas : ils valent partout, comme
        # Alt+W. Grouper et dégrouper ont pris Q et S (barre d'outils).
        self.w_combine = self._act(
            'Combiner', self._combine, 'Ctrl+G',
            'Réunit la sélection en un seul tracé, rempli d\'un bloc en '
            'pair-impair — l\'inverse de Décombiner   ·   Ctrl+G')
        self.w_uncombine = self._act(
            'Décombiner', self._uncombine, 'Ctrl+Shift+G',
            'Sépare chaque tracé ou texte sélectionné en ses polylignes, '
            'groupées : le remplissage ne change pas   ·   Ctrl+Maj+G')
        menu.addAction(self.w_combine)
        menu.addAction(self.w_uncombine)
        self.w_center_sel = self._act(
            'Centrer dans le champ', self._center_selection, 'Alt+W',
            'Centre la sélection dans le champ de marquage, sans changer la '
            'place des formes entre elles   ·   Alt+W')
        menu.addAction(self.w_center_sel)

        # --- Paramètres ---
        menu = bar.addMenu('&Paramètres')
        self.w_expert = QAction('Mode expert', self, checkable=True)
        self.w_expert.toggled.connect(self._toggle_expert)
        menu.addAction(self.w_expert)
        menu.addSeparator()

        self.w_optimize = QAction('Optimiser le parcours', self,
                                  checkable=True)
        self.w_optimize.setChecked(self.optimize)
        self.w_optimize.setStatusTip(
            'Réordonne les trajectoires pour réduire les déplacements à vide')
        self.w_optimize.toggled.connect(self._toggle_optimize)
        menu.addAction(self.w_optimize)

        self.w_group = QAction('Grouper par process', self, checkable=True)
        self.w_group.setChecked(self.group_recipes)
        self.w_group.setStatusTip(
            'Fusionne les formes de même process : moins de changements '
            'd\'outil, et l\'ordre de gravure n\'est plus celui de création')
        self.w_group.toggled.connect(self._toggle_group)
        menu.addAction(self.w_group)

        self.w_preflight = QAction('Vérifier avant l\'export', self,
                                   checkable=True)
        self.w_preflight.setChecked(session.preflight())
        self.w_preflight.setStatusTip(
            'Récapitulatif au moment d\'exporter : formes masquées, '
            'process et outils appelés, durée estimée, dépassement de champ')
        self.w_preflight.toggled.connect(self._toggle_preflight)
        menu.addAction(self.w_preflight)
        self.w_tb_labels = QAction('Libellés sous les icônes', self,
                                   checkable=True)
        self.w_tb_labels.setChecked(session.toolbar_labels())
        self.w_tb_labels.setToolTip(
            'Fait paraître le nom de chaque bouton sous son icône, en '
            'abrégé.\nLe nom entier reste dans l\'infobulle.')
        self.w_tb_labels.toggled.connect(self._toggle_toolbar_labels)
        menu.addAction(self.w_tb_labels)
        menu.addAction(self._act(
            'Relire les polices du poste', self._refresh_fonts,
            tip='À faire après avoir installé une police pendant que '
                'TauDrive tourne — la liste se met d\'ordinaire à jour '
                'toute seule en deux secondes'))
        menu.addSeparator()

        themes = menu.addMenu('Thème')
        self._theme_actions = []
        # Dix-neuf thèmes dans une seule liste se parcourent mal : sombres
        # et clairs sont séparés, dans cet ordre, car c'est le premier tri
        # que fait l'œil devant un écran d'atelier.
        precedent = None
        for palette in theme.THEMES:
            if precedent is not None and palette.dark != precedent:
                themes.addSeparator()
            precedent = palette.dark
            a = QAction(palette.label, self, checkable=True)
            a.setChecked(palette.key == theme.current().key)
            a.triggered.connect(
                lambda _=False, k=palette.key: self._change_theme(k))
            themes.addAction(a)
            self._theme_actions.append((a, palette.key))
        menu.addSeparator()
        menu.addAction(self._act('Process…', self._toggle_recipes, 'Ctrl+M',
                                 glyph='process'))
        menu.addAction(self._act('Dossiers par défaut…', self._edit_folders,
                                 glyph='ouvrir'))
        menu.addAction(self._act(
            'Menu contextuel Windows…', self._edit_shell_menu,
            tip='Convertir un dessin (AI, DXF, SVG, CDR…) depuis le '
                'clic droit de Windows, sans ouvrir TauDrive'))
        menu.addSeparator()
        menu.addAction(self._act(
            'Exporter les réglages…', self._export_settings,
            tip='Range process et réglages dans un fichier — sauvegarde, '
                'ou passage sur un autre poste'))
        menu.addAction(self._act(
            'Importer des réglages…', self._import_settings,
            tip='Reprend une archive de réglages, après avoir montré ce '
                'qu\'elle contient'))
        menu.addAction(self._act(
            'Où sont rangés mes réglages ?', self._where_settings,
            tip='Rien de tout cela n\'est dans le dossier du '
                'programme : une mise à jour ne perd rien'))

        naming = menu.addMenu('Exports répétés')
        naming.setToolTip('Que faire quand un travail est exporté deux fois')
        self._naming_actions = []
        for key, label, tip in session.EXPORT_NAMING:
            a = QAction(label, self, checkable=True)
            a.setChecked(key == session.export_naming())
            a.setStatusTip(tip)
            a.setToolTip(tip)
            a.triggered.connect(lambda _=False, k=key: self._set_naming(k))
            naming.addAction(a)
            self._naming_actions.append((a, key))

        # --- Affichage ---
        menu = bar.addMenu('&Affichage')
        menu.addAction(self._act(
            'Rejouer le parcours…', self._rejouer_parcours,
            'Ctrl+Shift+L',
            tip='Le travail tel que l\'export l\'écrira : dans quel ordre, '
                'combien de sauts, et combien de temps'))
        self.act_aimant = self._act(
            'Magnétisme', self._basculer_aimant, 'Ctrl+Shift+M',
            tip='Ce qu\'on déplace à la souris s\'accroche aux bords et '
                'au milieu des autres formes, aux axes et au champ — Alt '
                'tenu pour déplacer librement')
        self.act_aimant.setCheckable(True)
        self.act_aimant.setChecked(session.aimant())
        menu.addAction(self.act_aimant)
        menu.addSeparator()
        for dock in self._docks:
            menu.addAction(dock.toggleViewAction())

        # --- ? ---
        menu = bar.addMenu('&?')
        menu.addAction(self._act(
            'Ce qui a été rattrapé…', self._show_avale,
            tip='Les erreurs que TauDrive a rattrapées sans arrêter le '
                'travail — une vignette, une police, une clé de registre'))
        menu.addSeparator()
        menu.addAction(self._act('À propos de TauDrive', self._about))
        a = menu.addAction(f'Écrire à {CONTACT}')
        a.setStatusTip('Copie l\'adresse dans le presse-papiers')
        a.triggered.connect(self._copy_contact)

    def _basculer_aimant(self, actif: bool) -> None:
        """Retient le choix — voir `aimant`."""
        session.set_aimant(actif)
        self.statusBar().showMessage(
            'Magnétisme actif : bords et milieux s\'accrochent — Alt pour '
            'déplacer librement' if actif else
            'Magnétisme coupé : la souris déplace librement', 4000)

    def _rejouer_parcours(self) -> None:
        """Rejoue le travail dans l'ordre de l'export — voir `parcours`.

        Les passes sont refaites comme l'export les fait : même budget
        d'ordonnancement — partagé entre les pièces d'une série —, champs
        variables de la première pièce (`iso.reglages_premiere_piece`).
        Celles du plan de travail, faites avec un budget plus court,
        peuvent différer. L'ordonnancement ne dépend plus de l'horloge :
        le parcours rejoué est celui de l'export, permutation pour
        permutation.
        """
        from .parcours import ParcoursDialog
        dialogue = erreur = None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            passes = build_passes(self.document, optimize=self.optimize,
                                  group_by_recipe=self.group_recipes,
                                  **iso.reglages_premiere_piece(self.document))
            # la ligne du temps de trois cents plaques hachurées : une
            # demi-seconde, sous le même sablier
            if any(len(poly) >= 2 for p in passes for poly in p.polylines):
                dialogue = ParcoursDialog(
                    self, passes,
                    (self.document.field_w, self.document.field_h))
        except Exception as exc:                    # noqa: BLE001
            erreur = exc
        finally:
            QApplication.restoreOverrideCursor()
        if erreur is not None:
            # le menu ne rend rien à personne : sans ce message, une
            # erreur s'y perdait sans un mot
            QMessageBox.warning(self, 'Rejouer le parcours',
                                f'Le parcours n\'a pas pu être calculé :\n'
                                f'{erreur}')
            return
        if dialogue is None:
            self.statusBar().showMessage('Rien à graver : aucun parcours à '
                                         'rejouer', 4000)
            return
        dialogue.exec()
        dialogue.deleteLater()

    def _show_avale(self) -> None:
        """Montre ce que l'application a rattrapé sans le dire.

        Un filet large est souvent le bon choix — écrire une vignette ne
        doit jamais empêcher d'ouvrir un dessin. Ce qui ne va pas, c'est
        le silence : on cherche une heure pourquoi rien ne s'affiche,
        alors que la réponse était là, attrapée et jetée.
        """
        from . import avale as journal
        boite = QMessageBox(self)
        boite.setWindowTitle('Ce qui a été rattrapé')
        boite.setTextFormat(Qt.RichText)
        if not journal.count():
            boite.setText(
                '<p><b>Rien n\'a été rattrapé.</b></p>'
                '<p>Cette liste retient les erreurs que TauDrive absorbe '
                'pour ne pas interrompre le travail : une vignette qui ne '
                's\'écrit pas, une police malformée, une clé de registre '
                'refusée. Elle est vide, et c\'est bon signe.</p>')
            boite.exec()
            return
        lignes = ['<p><b>' + journal.summary() + '</b></p>',
                  '<p>Rien de tout cela n\'a interrompu le travail.</p>',
                  '<style>td{padding:2px 12px 2px 0;vertical-align:top}'
                  '</style><table>']
        for quand, contexte, genre, message, _ in journal.entries()[:40]:
            lignes.append(
                f'<tr><td>{quand:%H:%M:%S}</td>'
                f'<td><b>{_escape_html(contexte)}</b></td>'
                f'<td>{_escape_html(genre)}: '
                f'{_escape_html(message)}</td></tr>')
        lignes.append('</table>')
        if journal.count() > 40:
            lignes.append(f'<p>… et {journal.count() - 40} de plus.</p>')
        boite.setText(chr(10).join(lignes))
        boite.exec()

    def _about(self) -> None:
        """Qui a fait quoi, pour quelle machine, et à qui écrire."""
        box = QMessageBox(self)
        box.setWindowTitle('À propos de TauDrive')
        box.setTextFormat(Qt.RichText)
        icon = app_icon()
        if icon is not None and not icon.isNull():
            box.setIconPixmap(icon.pixmap(64, 64))
        box.setText(
            f'<b>{APP_NAME} {VERSION}</b><br>'
            f'Pilotage de gravure laser<br><br>'
            f'{machine_label()}<br>'
            f'Source JPT MOPA · carte CNC Cielle CL90135<br>'
            f'Champ {FIELD_W_MM:g} × {FIELD_H_MM:g} mm')
        box.setInformativeText(
            f'Contact : <a href="mailto:{CONTACT}">{CONTACT}</a><br><br>'
            'TauDrive prépare et exporte les travaux. <b>Il ne commande '
            'aucune émission laser</b> : le tir reste au contrôleur de la '
            'machine, qui porte la chaîne de sécurité.<br><br>'
            'Logiciel libre, sous licence MIT ou Apache-2.0, au choix. '
            'Composants tiers et leurs licences : THIRD_PARTY_NOTICES.md '
            'et dossier « licences », à côté de TauDrive.exe.'
            + ''.join(f'<br>{html.escape(ligne)}'
                      for ligne in plugins.about_lines()))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _copy_contact(self) -> None:
        QApplication.clipboard().setText(CONTACT)
        self.statusBar().showMessage(f'{CONTACT} copié dans le '
                                     f'presse-papiers', 4000)

    def _fill_recent(self) -> None:
        """Documents récents, les injoignables signalés mais conservés."""
        menu = self._recent_menu
        menu.clear()
        documents = session.recent_documents()
        for path in documents:
            here = session.reachable(path)
            label = pathlib.Path(path).name + ('' if here else '   (hors ligne)')
            a = menu.addAction(label)
            a.setToolTip(
                path if here
                else f'{path}\n\nNe répond pas — partage hors ligne.')
            a.setEnabled(here)
            a.triggered.connect(lambda _=False, p=path: self._open_recent(p))
        if not documents:
            menu.addAction('(aucun)').setEnabled(False)
            return
        menu.addSeparator()
        menu.addAction('Vider la liste').triggered.connect(
            session.forget_documents)

    def _close_current(self) -> None:
        index = self.tabs.currentIndex()
        if index >= 0:
            self._close_tab(index)

    def _open_recent(self, path: str) -> None:
        for tab in self.tabs_all():
            if tab.file_path == path:
                self.tabs.setCurrentWidget(tab)
                return
        self._load_into_tab(path)

    # -- documents ---------------------------------------------------------

    def _new_document(self) -> None:
        self.new_tab()
        self._tab_changed()

    def _open_document(self) -> None:
        recent = session.recent_documents()
        path, _ = QFileDialog.getOpenFileName(
            self, 'Ouvrir un document',
            session.start_folder('documents',
                                 str(pathlib.Path(recent[0]).parent)
                                 if recent else ''),
            DOC_FILTER)
        if path:
            session.remember_file('documents', path)
            self._open_recent(path)

    def _save(self) -> bool:
        return self._save_tab(self.canvas)

    def _save_as(self) -> bool:
        return self._save_tab(self.canvas, ask=True)

    def _save_tab(self, tab: DocumentTab, ask: bool = False) -> bool:
        if tab is None:
            return False
        path = tab.file_path
        if ask or not path:
            # « Enregistrer » a sa propre mémoire : on ouvre depuis
            # un dossier de travail et l'on enregistre souvent ailleurs.
            # Les faire partager une mémoire ramenait le sélecteur au
            # mauvais endroit une fois sur deux.
            recent = session.recent_documents()
            folder = session.start_folder(
                'enregistrer',
                str(pathlib.Path(recent[0]).parent) if recent else '')
            suggestion = str(pathlib.Path(folder)
                             / (tab.document.name + DOC_SUFFIX))
            path, _ = QFileDialog.getSaveFileName(
                self, 'Enregistrer le document', suggestion, DOC_FILTER)
            if not path:
                return False
            if not pathlib.Path(path).suffix:
                path += DOC_SUFFIX
        try:
            pathlib.Path(path).write_text(serialize.dumps(tab.document),
                                          encoding='utf-8')
        except OSError as exc:
            QMessageBox.critical(self, 'Enregistrer', f'Échec :\n{exc}')
            return False
        session.remember_file('enregistrer', path)
        tab.file_path = path
        tab.dirty = False
        self._retitle(tab)
        session.remember_document(path)
        self.statusBar().showMessage(f'Enregistré : {path}', 4000)
        return True

    # -- réglages ----------------------------------------------------------

    def _change_theme(self, key: str) -> None:
        """Applique un thème à chaud, plan de travail et icônes compris.

        Les panneaux remplacés attendent leur destruction différée ; une
        feuille de style s'applique aussi à eux. En vidant d'abord la file,
        le changement de thème passe de deux secondes à un dixième.
        """
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        theme.apply(QApplication.instance(), key)
        for action, k in self._theme_actions:
            action.setChecked(k == key)
        self._paint_export_button()
        self._paint_help_bar()
        for tab in self.tabs_all():
            tab.restyle()
        for action, glyph, tint in self._actions:
            colour = theme.current().alarm if tint else None
            action.setIcon(icons.icon(glyph, colour))
        self._style_add_tab()
        self._update_status()
        session.settings().setValue('theme', key)

    def _toggle_optimize(self, enabled: bool) -> None:
        self.optimize = enabled
        self._invalidate()

    def _toggle_group(self, enabled: bool) -> None:
        self.group_recipes = enabled
        self._invalidate()

    def _recipe_saved(self, nom: str) -> None:
        """Une process vient d'être rangée : les listes doivent la voir."""
        self.inspector.set_shape(None)
        self._selection_changed()
        self._flash_status(
            f'Process « {nom} » rangée dans la bibliothèque '
            f'({len(RECIPE_LIBRARY)} process)', True, 3.0)

    def _refresh_fonts(self) -> None:
        """Relit les polices du poste et refait les listes."""
        avant = len(textvec.available_fonts())
        apres = len(textvec.refresh_fonts())
        forget_font_model()
        self.inspector.refresh_fonts()
        ecart = apres - avant
        self._flash_status(
            f'{apres} polices lues'
            + (f' — {ecart:+d} depuis la dernière fois' if ecart else
               ' — aucun changement'), True, 4.0)

    def _toggle_toolbar_labels(self, enabled: bool) -> None:
        """Montre ou cache les libellés de la barre d'outils."""
        session.set_toolbar_labels(enabled)
        self._apply_toolbar_labels()

    def _apply_toolbar_labels(self) -> None:
        barre = getattr(self, '_toolbar', None)
        if barre is None:
            return
        barre.setToolButtonStyle(Qt.ToolButtonTextUnderIcon
                                 if session.toolbar_labels()
                                 else Qt.ToolButtonIconOnly)
        # Les boutons posés à la main — date, code, montage — ne sont pas
        # des actions de la barre : ils se règlent un par un.
        for bouton, libelle in (
                (getattr(self, 'w_date_button', None), 'Date'),
                (getattr(self, 'w_code_button', None), 'Plaque'),
                (getattr(self, 'w_montage_button', None), 'Montage')):
            if bouton is None:
                continue
            bouton.setText(libelle)
            bouton.setToolButtonStyle(Qt.ToolButtonTextUnderIcon
                                      if session.toolbar_labels()
                                      else Qt.ToolButtonIconOnly)

    def _toggle_preflight(self, enabled: bool) -> None:
        session.set_preflight(enabled)
        self.statusBar().showMessage(
            'Vérification avant export activée' if enabled
            else 'Vérification avant export désactivée — '
                 'réactivable dans Paramètres', 4000)

    def _toggle_expert(self, enabled: bool) -> None:
        """Le mode expert se déverrouille par code, jamais par simple clic."""
        if enabled and not recipes.expert():
            if not recipes.unlock(self):
                self.w_expert.blockSignals(True)
                self.w_expert.setChecked(False)
                self.w_expert.blockSignals(False)
                return
        if not enabled:
            recipes.lock()
        active = enabled and recipes.expert()
        self.recipe.set_expert(active)
        self._apply_expert_visibility(active)

    def _apply_expert_visibility(self, expert: bool) -> None:
        """Source laser, réseau et lot/série : réservés au mode expert.

        Un opérateur qui compose une plaque n'a que faire de l'état de la
        source ni de la numérotation de série — et
        un panneau de trop est un panneau où l'on clique par erreur. Ces
        trois-là n'apparaissent qu'une fois le mode expert déverrouillé.

        Leur entrée du menu *Affichage* disparaît avec eux : la laisser
        reviendrait à offrir le panneau d'un clic tout en prétendant
        l'avoir masqué.
        """
        for dock in self._expert_docks:
            dock.setVisible(expert)
            dock.toggleViewAction().setVisible(expert)

    def _build_help_bar(self) -> None:
        """Pose l'emplacement d'aide à droite de la barre d'état.

        À droite, et non dans la zone de message : celle-ci porte les
        mesures du travail, réécrites en continu, et l'aide y serait
        effacée au premier mouvement de souris.
        """
        self.w_help = helpbar.HelpLabel()
        self.w_help.setObjectName('aide')
        # sans facteur d'étirement : l'aide prend sa part et pas plus,
        # les mesures du travail gardent le reste
        self.statusBar().addPermanentWidget(self.w_help, 0)
        self._paint_help_bar()
        # le routeur doit survivre : un filtre d'événements ramassé par le
        # collecteur cesse d'agir en silence
        self._help_router = helpbar.install(QApplication.instance(),
                                            self.w_help)

    def _paint_help_bar(self) -> None:
        """L'aide se lit atténuée : c'est un renseignement, pas une alerte."""
        if not hasattr(self, 'w_help'):
            return
        palette = theme.current()
        # `font-weight` est repris explicitement : la barre entière passe en
        # gras quand une trajectoire sort du champ, et l'aide n'a pas à
        # crier avec elle
        self.w_help.setStyleSheet(
            f'color:{palette.text_dim}; padding-left:10px;'
            f'font-weight:normal;'
            f'border-left:1px solid {palette.text_dim};')

    def _toggle_recipes(self) -> None:
        """Le bouton *Process…* ouvre **et** referme le gestionnaire.

        Un bouton qui n'ouvre que dans un sens oblige à retrouver
        *Terminé* à l'autre bout de la colonne. Celui d'où l'on vient est
        celui qu'on cherche pour revenir.
        """
        if self.center.currentIndex() == 1:
            self._leave_recipes()
        else:
            self._manage_recipes()

    def _label_recipes_button(self) -> None:
        """Le bouton dit ce qu'il fera, pas où l'on est."""
        ouvert = self.center.currentIndex() == 1
        # C'est l'**action** qu'on renomme : le bouton de barre en tient
        # son intitulé, et le renommer directement serait effacé au
        # prochain rafraîchissement de l'action.
        self.w_recipes_action.setText('Fermer les process'
                                      if ouvert else 'Process…')
        self.w_recipes_action.setToolTip(
            'Referme le gestionnaire et rend le plan de travail'
            if ouvert else
            'Gestionnaire de process : créer, renommer, dupliquer, '
            'régler passes et profondeur')
        # le curseur est encore sur le bouton : l'aide doit suivre
        routeur = getattr(self, '_help_router', None)
        if routeur is not None and self.w_recipes_button is not None:
            routeur.refresh(self.w_recipes_button)

    def _manage_recipes(self) -> None:
        """Passe en réglage de recettes : colonnes 2 et 3 lui sont prêtées.

        Le gestionnaire prend la place du plan de travail, et le magasin
        d'outils celle des propriétés. On ne règle pas une recette
        par-dessus le dessin mais **à sa place**, et l'on revient d'un
        bouton — *Enregistrer* ne quitte pas les lieux.
        """
        if self.center.currentIndex() == 2:
            self._leave_library()
        if not self._leave_montages():
            return
        self.recipes_panel.reload()
        self.center.setCurrentIndex(1)
        self._dock_insp.hide()
        self._dock_tools.show()
        self._dock_tools.raise_()
        self._label_recipes_button()
        self.statusBar().showMessage(
            'Réglage des process — « Fermer les process » ou « Terminé » '
            'pour revenir au dessin', 8000)

    def _leave_recipes(self) -> None:
        """Rend les colonnes 2 et 3 au dessin et à ses propriétés."""
        self.center.setCurrentIndex(0)
        self._dock_tools.hide()
        self._dock_insp.show()
        self._dock_insp.raise_()
        self._label_recipes_button()
        self._selection_changed()

    def _recipes_stored(self, combien: int) -> None:
        """La bibliothèque vient d'être rangée : les listes doivent la voir."""
        self.inspector.set_shape(None)
        self.recipe.set_shape(None)
        self._selection_changed()
        self._flash_status(f'{combien} process(s) en bibliothèque', True, 3.0)

    def _tool_loaded(self, outil) -> None:
        if outil is None:
            return
        self.statusBar().showMessage(
            f'T{outil.number} « {outil.name} » chargé dans la process — '
            f'Enregistrer pour le garder', 6000)

    def _invalidate(self) -> None:
        for tab in self.tabs_all():
            tab.passes_cache = None
        self._update_status()

    def _job_changed(self) -> None:
        """Les champs variables changent la géométrie : tout est à refaire."""
        self.canvas.reload()
        self._refresh_list()
        self._retitle(self.canvas)
        self._touch()

    def _step_set(self, value: float) -> None:
        for tab in self.tabs_all():
            tab.nudge_step = max(0.001, float(value))

    def _step_changed(self, value: float) -> None:
        self.w_step.blockSignals(True)
        self.w_step.setValue(value)
        self.w_step.blockSignals(False)
        self._step_set(value)
        self.statusBar().showMessage(f'Pas de déplacement : {value:g} mm', 2000)

    def _focus_step(self) -> None:
        """Ctrl+flèche : le champ du pas prend la main, tout sélectionné."""
        self.w_step.setFocus(Qt.ShortcutFocusReason)
        self.w_step.selectAll()
        self.statusBar().showMessage(
            'Tapez le pas en mm — Entrée l\'applique et rend la main au '
            'plan de travail', 4000)

    def _step_validated(self) -> None:
        """Entrée dans le champ du pas : appliqué, retour au plan."""
        self._step_set(self.w_step.value())
        self.statusBar().showMessage(
            f'Pas de déplacement : {self.w_step.value():g} mm', 2000)
        self._leave_step()

    def _leave_step(self) -> None:
        if self.canvas is not None:
            self.canvas.setFocus(Qt.OtherFocusReason)

    def _geometry_changed(self) -> None:
        # les formulaires suivent le geste : sinon leur premier réglage
        # replacerait la forme là d'où on vient de la déplacer
        self.inspector.follow_move()
        self.lot.follow_move()
        self._remember_plate()
        self._touch()
        self._status_timer.start()

    # -- formes ------------------------------------------------------------

    def _add(self, shape: Shape) -> None:
        self.document.add(shape)
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select(shape.id)
        self._touch()

    def _add_rect(self) -> None:
        self._add(Rect(width=20, height=10, recipe=self._default_recipe()))

    def _add_circle(self) -> None:
        self._add(Circle(width=20, height=20, recipe=self._default_recipe()))

    @staticmethod
    def _code_kind_help(kind: str) -> str:
        """Ce que chaque symbologie sait faire, en une ligne d'aide."""
        return {
            'datamatrix':
                'Le plus dense, et le seul qui se relise entamé. Posé avec '
                'son cadre englobant, gravé en négatif : le rendu des '
                'plaques de production.',
            'qr':
                'Lu par tous les téléphones, quatre niveaux de correction. '
                'Posé nu, gravé en creux.',
            'code39':
                'Linéaire, alphanumérique, sans longueur imposée. Posé nu.',
            'ean13':
                'Linéaire, treize chiffres exactement, clé comprise. Posé nu.',
            'code128':
                'Linéaire, tout l\'ASCII, et deux chiffres par caractère : '
                'un numéro en moitié moins de place qu\'en Code 39. Clé '
                'toujours comprise. Posé nu.',
        }.get(kind, '')

    def _mark_code_kind(self) -> None:
        """Coche la symbologie que le bouton posera, et le dit en infobulle."""
        courant = session.code_defaults()['kind']
        for a in getattr(self, 'w_code_kinds', []):
            a.setChecked(a.data() == courant)
        libelle = dict(barcode.KINDS).get(courant, courant)
        cadre = (f'avec cadre englobant à '
                 f'{codeplate.DEFAULT_FRAME_MARGIN:g} mm, en négatif'
                 if codeplate.default_frame(courant) == 'rect' else 'nu')
        self.w_code_button.setToolTip(
            f'Pose un {libelle} et son texte, ajustés à leurs cadres '
            f'({cadre}).\n'
            f'La flèche change de symbologie.   Ctrl+B')

    def _fill_montage_menu(self) -> None:
        """La flèche : le prochain montage en tête, puis les gabarits du
        poste, puis le gestionnaire."""
        from . import gabarits
        menu = self.w_montage_menu
        for a in self._montage_actions:
            menu.removeAction(a)
            a.deleteLater()
        self._montage_actions = []
        self.w_montage_form.load()
        # le gestionnaire écrit le même fichier : tant qu'il garde des
        # modifications, la flèche n'y touche pas
        self.w_montage_form.set_locked(
            'Le gestionnaire de montages a des modifications non '
            'enregistrées : enregistrez-les ou abandonnez-les d\'abord.'
            if self.montages_panel.dirty() else '')

        def ajoute(action: QAction) -> QAction:
            menu.addAction(action)
            self._montage_actions.append(action)
            return action

        for gab in gabarits.charger():
            a = ajoute(QAction(f'Poser « {gab["nom"]} »', menu))
            a.setStatusTip(
                f'{len(gab["postes"])} poste(s) · entraxe '
                f'{gab.get("entraxe_mm", 0):g} mm')
            # par son nom, relu au clic : le formulaire au-dessus vient
            # peut-être de changer ses cotes
            a.triggered.connect(
                lambda _=False, n=gab['nom']: self._add_montage_named(n))
        separe = QAction(menu)
        separe.setSeparator(True)
        ajoute(separe)
        a = ajoute(QAction('Gestionnaire de montages…', menu))
        a.triggered.connect(self._manage_montages)
        a = ajoute(QAction('Où sont les gabarits ?…', menu))
        a.triggered.connect(self._where_gabarits)

    def _add_montage_named(self, nom: str) -> None:
        """Pose le gabarit qui porte ce nom, tel qu'il est maintenant."""
        from . import gabarits
        # le gestionnaire d'abord : s'il enregistre en se refermant, c'est
        # ce qu'il vient d'écrire qui se pose, pas ce que le menu a lu
        if not self._leave_montages():
            return
        gab = next((g for g in gabarits.charger() if g['nom'] == nom), None)
        if gab is None:
            self.statusBar().showMessage(f'« {nom} » n\'existe plus', 4000)
            return
        self._add_montage(gab)

    def _gabarits_changed(self) -> None:
        """Le fichier des gabarits vient d'être écrit : les autres portes
        le relisent — le formulaire de la pose son gabarit d'origine, le
        gestionnaire sa liste s'il n'a rien en suspens."""
        self.montage_form.rafraichir_gabarits()
        self.montages_panel.relire_si_propre()

    def _montage_of_selection(self) -> list:
        """Les formes du montage sélectionné au plan — vide sinon."""
        lot = self.canvas.selected_shapes() if self.canvas else []
        return lot if montage.is_montage(lot) else []

    def _capture_montage(self) -> None:
        """La flèche reprend le montage sélectionné : le bouton le posera
        ainsi."""
        from . import gabarits
        formes = self._montage_of_selection()
        if not formes:
            self.statusBar().showMessage(
                'Sélectionnez un montage posé — ses codes et leurs textes — '
                'pour le reprendre', 5000)
            return
        tete = gabarits.charger()[0]
        try:
            gab = gabarits.depuis_formes(formes, tete)
            gab['nom'] = tete['nom']
            gabarits.remplacer(gab, tete['nom'])
        except (gabarits.GabaritError, OSError) as exc:
            QMessageBox.warning(self, 'Montage', f'Rien de repris : {exc}')
            return
        self.w_montage_form.load()
        self._gabarits_changed()
        self.statusBar().showMessage(
            f'« {tete["nom"]} » reprend le montage sélectionné : cadre, '
            f'taille, positions et texte', 6000)

    def _montage_saved(self, nom: str) -> None:
        """Le formulaire de la pose vient d'écrire un gabarit."""
        self.montages_panel.relire_si_propre()
        self.statusBar().showMessage(
            f'Gabarit « {nom} » enregistré — la flèche du bouton Montage '
            f'le montre, la pose suivante le reprend', 6000)

    # -- gestionnaire de montages -----------------------------------------

    def _toggle_montages(self) -> None:
        """*Montages…* ouvre **et** referme le gestionnaire."""
        if self.center.currentIndex() == 3:
            self._leave_montages()
        else:
            self._manage_montages()

    def _manage_montages(self) -> None:
        """Le gestionnaire prend le plan de travail et les propriétés."""
        if self.center.currentIndex() == 3:
            return
        if self.center.currentIndex() == 2:
            self._leave_library()
        elif self.center.currentIndex() == 1:
            self._leave_recipes()
        self.montages_panel.set_recipe(self._default_recipe())
        self.montages_panel.reload()
        self.center.setCurrentIndex(3)
        self._dock_insp.hide()
        self.statusBar().showMessage(
            'Gestionnaire de montages — « Enregistrer » écrit les gabarits, '
            '« Terminé » revient au plan de travail', 8000)

    def _leave_montages(self) -> bool:
        """Rend le plan de travail. Faux si l'opérateur a préféré rester
        pour ne pas perdre ses modifications."""
        if self.center.currentIndex() != 3:
            return True
        if not self.montages_panel.peut_quitter():
            return False
        self.center.setCurrentIndex(0)
        self._dock_insp.show()
        self._dock_insp.raise_()
        self._selection_changed()
        return True

    def _label_montages_button(self) -> None:
        ouvert = self.center.currentIndex() == 3
        self.w_montages_action.setText('Fermer les montages'
                                       if ouvert else 'Montages…')
        self.w_montages_action.setToolTip(
            'Referme le gestionnaire et rend le plan de travail'
            if ouvert else
            'Gestionnaire de montages : créer, dupliquer, ranger, régler '
            'cadre, taille et positions des postes')
        routeur = getattr(self, '_help_router', None)
        bouton = getattr(self, 'w_montages_button', None)
        if routeur is not None and bouton is not None:
            routeur.refresh(bouton)

    def _label_center_buttons(self, *_) -> None:
        """Les trois boutons de réserve disent ce qu'ils feront."""
        for libelle in ('_label_library_button', '_label_recipes_button',
                        '_label_montages_button'):
            if hasattr(self, 'w_montages_action'):
                getattr(self, libelle)()

    def _pose_from_manager(self, gab: dict) -> None:
        """Le gestionnaire a tranché ses modifications : on pose."""
        self._leave_montages()
        if self.center.currentIndex() == 0:
            self._add_montage(gab)

    def _capture_into_manager(self) -> None:
        formes = self._montage_of_selection()
        if not formes:
            self.montages_panel.dit(
                'Aucun montage sélectionné au plan : sélectionnez ses codes '
                'et leurs textes, puis revenez ici.', alerte=True)
            return
        self.montages_panel.reprendre(formes)

    def _montages_saved(self, combien: int) -> None:
        self.montage_form.rafraichir_gabarits()
        self._flash_status(f'{combien} montage(s) enregistré(s)', True, 3.0)

    def _add_montage(self, gabarit=None) -> None:
        """Pose un montage à DataMatrix, aux cotes de son gabarit.

        Deux formes par poste — un symbole, un texte — groupées **deux à
        deux** : chaque poste se déplace d'un bloc, mais les postes
        restent indépendants, parce qu'ils portent des pièces
        différentes.

        Aucune fenêtre modale : les cotes sont celles de la mécanique, il
        n'y a rien à demander. Les références se saisissent ensuite dans
        le formulaire, qui s'ouvre tout seul.
        """
        from . import gabarits
        # gestionnaire ouvert : le montage se poserait derrière lui, sur
        # un plan caché, et le formulaire de la pose reviendrait à côté
        if not self._leave_montages():
            return
        gab = gabarit or gabarits.charger()[0]
        formes = montage.build(self._default_recipe(), gabarit=gab)
        if not formes:
            QMessageBox.warning(self, 'Montage',
                                'Donnée impossible à encoder.')
            return
        for forme in formes:
            self.document.add(forme)
        for i in range(0, len(formes), 2):
            self.document.group([formes[i].id, formes[i + 1].id])
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many([f.id for f in formes])
        self._touch()
        self._show_montage(formes, gab)
        # on pose un montage pour y taper trois références : la première
        # prend la main tout de suite
        QTimer.singleShot(0, self.montage_form.focus_first)
        self.statusBar().showMessage(
            f'{gab["nom"]} posé — saisissez les références dans le '
            f'formulaire', 6000)

    def _where_gabarits(self) -> None:
        """Dit où vit le fichier de gabarits, et ce qu'on y règle."""
        from . import gabarits
        chemin = gabarits.ecrire_livre_si_absent() or gabarits.chemin()
        boite = QMessageBox(self)
        boite.setWindowTitle('Gabarits de montage')
        boite.setTextFormat(Qt.RichText)
        boite.setText(
            f'<p>Les cotes des montages vivent dans :</p>'
            f'<p><code>{_escape_html(str(chemin))}</code></p>'
            f'<p>Positions, entraxe, taille du symbole et place du texte '
            f'y sont des <b>valeurs</b> : le jour où l\'entraxe change, '
            f'c\'est une ligne à corriger, pas un programme à '
            f'reconstruire.</p>'
            f'<p>Ajouter une entrée y ajoute un montage, sans rien '
            f'installer. Le fichier part avec '
            f'<i>Paramètres ▸ Exporter les réglages</i>.</p>'
            f'<p>Le <b>gestionnaire de montages</b> — bouton '
            f'<i>Montages…</i>, à côté de la bibliothèque — les édite '
            f'sans ouvrir le fichier. À la première écriture de chaque '
            f'séance, l\'état d\'avant est gardé à côté, sous le nom '
            f'<code>{gabarits.AVANT}</code>.</p>')
        boite.exec()

    def _show_montage(self, formes, gabarit=None) -> None:
        """Ouvre le formulaire du montage sur ces formes."""
        if self.montage_form.set_montage(formes, self.document, gabarit):
            self._insp_stack.setCurrentIndex(2)
            self._show_properties()

    def _montage_edited(self) -> None:
        """Une reference a change : propager au texte, redessiner.

        La propagation passe par `_propagate_data`, le meme chemin que
        l'edition d'un code isole : c'est lui qui tient la promesse du
        lien `follows`, et il n'y a aucune raison d'en ecrire un second.
        """
        codes = {code.id for code in self.montage_form.codes()}
        for code in self.montage_form.codes():
            # les noms sont deja remis d'accord par le formulaire, qui
            # seul sait quel poste porte quel code
            self._propagate_data(code.id)
        # Redessiner les formes du montage **en place**, et non tout le
        # plan : `reload` retire chaque forme de la scène, la sélection
        # fond une forme après l'autre, et le formulaire se rechargeait
        # au passage sur un montage partiel — deux postes sur trois, sans
        # plus savoir de quel gabarit ils venaient.
        self.canvas.refresh_many(
            [forme.id for forme in self.document.shapes
             if forme.id in codes or (isinstance(forme, Text)
                                      and forme.follows in codes)])
        self._refresh_list()
        self._touch()

    def _add_code_in_frame(self, kind: str = '') -> None:
        """Pose une plaque codée : le symbole et son texte, groupés.

        Aucune fenêtre modale. Si un ou deux rectangles sont sélectionnés,
        leurs cotes servent de fenêtres — la plus grande pour le symbole,
        la plus petite pour le texte, comme sur le DXF de production.
        Sinon on reprend les cotes de la dernière plaque posée.

        `kind` impose la symbologie — c'est ce que la flèche du bouton
        choisit. Sans elle, on reprend celle de la dernière plaque : poser
        vingt plaques identiques est le geste courant, et redésigner la
        symbologie à chaque fois serait vingt clics pour rien.

        Le reste se règle dans la colonne *Propriétés* : donnée, fenêtre,
        position, remplissage et recette. Décider de tout avant d'avoir
        rien vu n'aide personne.
        """
        selected = self.canvas.selected_shapes() if self.canvas else []
        frame, text_frame = frames_of(selected)
        remembered = session.code_defaults()
        kind = kind if isinstance(kind, str) and kind else remembered['kind']
        if frame is None:
            frame = tuple(remembered['frame'])
        if text_frame is None:
            # le texte suit le code : il est retenu **par rapport à lui**
            dx, dy, tw, th = remembered['text_offset']
            text_frame = (frame[0] + dx, frame[1] + dy, tw, th)

        shapes = build_plate(self._default_recipe(), frame=frame,
                             text_frame=text_frame,
                             data=remembered['data'],
                             kind=kind,
                             dm_shape=remembered['dm_shape'],
                             code_frame=remembered['code_frame'],
                             frame_margin_mm=remembered['frame_margin'])
        if not shapes:
            QMessageBox.warning(self, 'Code', 'Donnée impossible à encoder.')
            return

        for shape in shapes:
            self.document.add(shape)
        # symbole et texte forment un tout : on les groupe, ce qui les fait
        # déplacer, redimensionner et changer de recette d'un bloc
        if len(shapes) > 1:
            self.document.group([s.id for s in shapes])
        self.canvas.reload()
        self._refresh_list()
        # la sélection se pose sur le symbole : c'est son panneau qu'on
        # veut voir s'ouvrir dans les propriétés
        self.canvas.select(shapes[0].id)
        session.remember_code(
            frame=frame, text_frame=text_frame, kind=kind,
            text_offset=(text_frame[0] - frame[0], text_frame[1] - frame[1],
                         text_frame[2], text_frame[3]))
        self._touch()
        libelle = dict(barcode.KINDS).get(kind, kind)
        encadre = (' — cadre englobant à '
                   f'{codeplate.DEFAULT_FRAME_MARGIN:g} mm, gravé en négatif'
                   if shapes[0].frame != 'none' else '')
        self.statusBar().showMessage(
            f'{libelle} posé{encadre} — réglez donnée et process dans '
            f'les propriétés', 8000)

    def _plate_of_selection(self):
        """`(code, texte)` de la plaque sélectionnée, ou `(None, None)`.

        **Une** plaque : un montage en porte trois, et le déplacer ne dit
        rien de ce que doit être la prochaine plaque seule — retenir la
        position de son premier code poserait la suivante par-dessus.
        """
        lot = self.canvas.selected_shapes() if self.canvas else []
        codes = [s for s in lot if isinstance(s, Code)]
        if len(codes) > 1:
            return None, None
        if not codes:
            sid = self.canvas.primary_id() if self.canvas else None
            forme = self.document.get(sid) if sid else None
            if isinstance(forme, Text) and forme.follows:
                code = self.document.get(forme.follows)
                if isinstance(code, Code):
                    return code, forme
            return None, None
        code = codes[0]
        texte = next((s for s in self.document.shapes
                      if isinstance(s, Text) and s.follows == code.id), None)
        return code, texte

    def _capture_plate(self) -> None:
        """Inscrit la plaque sélectionnée comme modèle de la suivante."""
        code, texte = self._plate_of_selection()
        if code is None:
            self.statusBar().showMessage(
                'Sélectionnez une plaque codée pour la reprendre', 3000)
            return
        session.remember_code(**codeplate.plate_settings(
            code, texte, session.code_defaults()['code_frame']))
        self.w_plate_form.load()
        self.statusBar().showMessage(
            'La prochaine plaque reprendra celle-ci : cadre, taille, '
            'position et texte', 4000)

    def _remember_plate(self) -> None:
        """Une plaque retouchée apprend à la suivante, sans rien demander.

        Appelé à chaque modification de la forme désignée : déplacement au
        plan de travail compris, qui ne passe pas par le formulaire.
        """
        code, texte = self._plate_of_selection()
        if code is None:
            return
        try:
            session.remember_code(**codeplate.plate_settings(
                code, texte, session.code_defaults()['code_frame']))
        except Exception as exc:                        # noqa: BLE001
            from .avale import avale
            avale('plaque : réglages non retenus', exc)

    def _coupon_from_selection(self) -> None:
        """Fait un coupon d'essai du dessin sélectionné.

        Un carré plein juge un rendu de surface, et rien d'autre. Ce qu'on
        veut souvent savoir, c'est comment **le dessin réel** sort : un
        logo se bouche, un texte de 1,2 mm devient illisible. Le coupon
        grave alors le dessin dans chaque case.
        """
        formes = self.canvas.selected_shapes() if self.canvas else []
        if not formes:
            self.statusBar().showMessage(
                'Coupon : sélectionnez d\'abord une ou plusieurs formes',
                4000)
            return
        motif = coupon.motif_from_shapes(formes)
        if not motif:
            QMessageBox.warning(
                self, 'Coupon',
                'Cette sélection ne donne aucun tracé à graver.')
            return
        self._add_coupon(motif=motif)

    def _add_coupon(self, motif: list | None = None) -> None:
        """Pose une grille d'essai, groupée, dans un onglet à elle.

        Un coupon n'a rien à faire au milieu d'un travail de production :
        il occupe tout le champ, porte vingt recettes différentes et se
        jette après lecture. Il part donc dans son propre onglet, prêt à
        être exporté seul.
        """
        library = list(RECIPE_LIBRARY) or list(preset_recipes())
        # Un onglet qui porte déjà un coupon se **rouvre** sur son propre
        # formulaire : un coupon n'est pas un dessin qu'on retouche à la
        # souris, c'est le résultat de réglages, et ces réglages doivent
        # rester accessibles.
        courant = self.canvas
        reglages = dict(courant.document.coupon) if courant else {}
        depart = self._default_recipe()
        if reglages.get('recipe'):
            depart = next((p for p in library
                           if p.name == reglages['recipe']), depart)
        dialog = coupon.CouponDialog(self, depart, library,
                                     settings=reglages or None,
                                     expert=recipes.expert(),
                                     motif=motif or None)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        shapes = dialog.shapes()
        if not shapes:
            QMessageBox.warning(self, 'Coupon', 'Aucune case à générer.')
            return

        # les réglages sont retenus deux fois : dans la session, pour le
        # prochain coupon ; dans le document, pour rouvrir celui-ci
        neufs = dialog.settings()
        session.remember_coupon(**{k: v for k, v in neufs.items()
                                   if k != 'fixed'})

        if reglages:
            tab = courant
            tab.document.shapes.clear()
            self.canvas.reload()
        else:
            tab = self.new_tab()
            tab.document.name = f'Coupon {dialog.recipe().name}'
        tab.document.coupon = neufs
        for shape in shapes:
            tab.document.add(shape)
        tab.document.group([s.id for s in shapes])
        tab.passes_cache = None
        tab.reload()
        self._tab_changed()
        self._retitle(tab)
        tab.fit()
        self._touch()
        cases = sum(1 for s in shapes if not isinstance(s, Text))
        self.statusBar().showMessage(
            f'Coupon {"régénéré" if reglages else "posé"} : {cases} cases, '
            f'{cases} process distinctes — cliquez une case pour lire et '
            f'modifier sa process, ou Coupon… pour rouvrir le formulaire',
            8000)

    def _export_vector(self) -> None:
        """Exporte le dessin vers un format d\'échange.

        Rien à voir avec l\'export machine : celui-ci va **aux
        autres** — le bureau d\'études qui veut le plan, le client qui
        veut vérifier son logo. On lui demande donc ce qu\'il veut
        voir : le dessin tel qu\'on l\'a posé, ou tout ce qui
        partira à la gravure.
        """
        if not any(f.visible for f in self.document.shapes):
            QMessageBox.information(self, 'Exporter le dessin',
                                    'Aucune forme visible à exporter.')
            return
        choix = vecexport.VectorExportDialog(self, self.document)
        if choix.exec() != QDialog.DialogCode.Accepted:
            return
        genre, trajectoires = choix.choice()
        depart = pathlib.Path(session.start_folder('export_vectoriel'))
        propose = depart / f'{iso.sanitize(self.document.name)}.{genre}'
        chemin, _ = QFileDialog.getSaveFileName(
            self, 'Exporter le dessin', str(propose),
            next(f for k, _, f in vecexport.FORMATS if k == genre))
        if not chemin:
            return
        if not pathlib.Path(chemin).suffix:
            chemin += f'.{genre}'
        try:
            combien = vecexport.export(self.document, chemin, kind=genre,
                                       toolpaths=trajectoires)
        except Exception as exc:
            QMessageBox.warning(self, 'Exporter le dessin',
                                f'Export impossible : {exc}')
            return
        session.remember_file('export_vectoriel', chemin)
        self._flash_status(
            f'{combien} tracé(s) écrits dans '
            f'{pathlib.Path(chemin).name}', True, 3.0)

    def _export_settings(self) -> None:
        """Range process et réglages dans un fichier."""
        choix = settingsio.ExportDialog(self)
        if choix.exec() != QDialog.DialogCode.Accepted:
            return
        depart = pathlib.Path(session.start_folder('reglages'))
        propose = depart / f'TauDrive {datetime.date.today():%Y-%m-%d}'
        chemin, _ = QFileDialog.getSaveFileName(
            self, 'Exporter les réglages',
            str(propose.with_suffix(settingsio.SUFFIX)),
            settingsio.FILE_FILTER)
        if not chemin:
            return
        try:
            compte = settingsio.export(chemin, **choix.choice())
        except Exception as exc:
            QMessageBox.warning(self, 'Exporter les réglages',
                                f'Export impossible : {exc}')
            return
        session.remember_file('reglages', chemin)
        detail = (f'{compte["process"]} process, '
                  f'{compte["reglages"]} réglages')
        if compte['dessins']:
            detail += f', {compte["dessins"]} dessins'
        self._flash_status(f'Réglages exportés — {detail}', True, 4.0)

    def _import_settings(self) -> None:
        """Reprend une archive, **après avoir montré ce qu\'elle
        contient**."""
        chemin, _ = QFileDialog.getOpenFileName(
            self, 'Importer des réglages',
            session.start_folder('reglages'),
            settingsio.FILE_FILTER.replace(
                ';;Tous (*)',
                ';;Bibliothèque seule — recettes.json, codes.json, '
                'montages.json (*.json);;Tous (*)'))
        if not chemin:
            return
        session.remember_file('reglages', chemin)
        # Un `recettes.json` copié tel quel depuis l'autre poste — le
        # geste le plus simple, et le premier qu'on tente — n'est pas une
        # archive : il est reconnu et repris comme une bibliothèque.
        import zipfile
        if not zipfile.is_zipfile(chemin):
            self._import_library_file(chemin)
            return
        try:
            fenetre = settingsio.ImportDialog(self, chemin)
        except Exception as exc:
            QMessageBox.warning(self, 'Importer des réglages', str(exc))
            return
        if fenetre.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            compte = settingsio.apply(chemin, **fenetre.choice())
        except Exception as exc:
            QMessageBox.warning(self, 'Importer des réglages',
                                f'Import impossible : {exc}')
            return
        self._library_changed()
        if compte.get('gabarits'):
            self._gabarits_changed()
        detail = (f'{compte["process"]} process'
                  + (f' dont {compte["remplacees"]} remplacée(s)'
                     if compte.get('remplacees') else '')
                  + f', {compte["reglages"]} réglages')
        if compte.get('codes'):
            detail += f', {compte["codes"]} préréglages de code'
        if compte['dessins']:
            detail += f', {compte["dessins"]} dessins'
        if compte['ignores']:
            detail += f' · {len(compte["ignores"])} dossier(s) laissés'
        self._flash_status(f'Réglages repris — {detail}', True, 5.0)

    def _library_changed(self) -> None:
        """La bibliothèque a changé sur le disque : tout ce qui la montre
        la relit — gestionnaire, colonne 1, panneau du lot."""
        self.recipes_panel.reload()
        self.recipe.refresh()
        self._selection_changed()

    def _import_library_file(self, chemin: str) -> None:
        """Reprend un fichier de bibliothèque nu : process, préréglages de
        code ou montages, reconnus à leur contenu, montrés avant d'entrer."""
        from . import echange
        genre = echange.genre(chemin)
        nom = pathlib.Path(chemin).name
        if genre == 'process':
            try:
                venues, entete = echange.lire_process(chemin)
            except echange.EchangeError as exc:
                QMessageBox.warning(self, 'Importer des process', str(exc))
                return
            connues = recipes.load_local()
            choix = echange.ChoixImport(
                self, f'Importer des process — {nom}', entete, venues,
                lambda r: r.name, {r.name for r in connues})
            if choix.exec() != QDialog.DialogCode.Accepted:
                return
            retenues = choix.retenues()
            if not retenues:
                return
            resultat = echange.fusionner(connues, retenues, lambda r: r.name)
            recipes.save_local(resultat)
            recipes.set_recipe_library(resultat)
            self._library_changed()
            self._flash_status(
                f'{len(retenues)} process reprises de {nom} — '
                f'{len(resultat)} en bibliothèque', True, 5.0)
        elif genre == 'codes':
            try:
                venus, entete = echange.lire_codes(chemin)
            except echange.EchangeError as exc:
                QMessageBox.warning(self, 'Importer des préréglages',
                                    str(exc))
                return
            connus = codepresets.load()
            choix = echange.ChoixImport(
                self, f'Importer des préréglages de code — {nom}', entete,
                venus, lambda p: p['name'], {p['name'] for p in connus})
            if choix.exec() != QDialog.DialogCode.Accepted:
                return
            retenus = choix.retenues()
            if not retenus:
                return
            resultat = echange.fusionner(connus, retenus,
                                         lambda p: p['name'])
            codepresets.save(resultat)
            codepresets.set_library(resultat)
            self._flash_status(
                f'{len(retenus)} préréglage(s) de code repris de {nom}',
                True, 5.0)
        elif genre == 'montages':
            from . import gabarits
            try:
                brut = json.loads(pathlib.Path(chemin).read_text(
                    encoding='utf-8'))
                venus = [g for g in brut.get('montages', [])
                         if isinstance(g, dict)]
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, 'Importer des montages', str(exc))
                return
            if not venus:
                QMessageBox.information(self, 'Importer des montages',
                                        'Ce fichier ne décrit aucun montage.')
                return
            noms = ', '.join(str(g.get('nom', '?')) for g in venus)
            if QMessageBox.question(
                    self, 'Importer des montages',
                    f'Remplacer les gabarits de montage du poste par ceux '
                    f'de {nom} ?\n\n{noms}\n\nCe sont des cotes de '
                    'mécanique : elles ne se fusionnent pas.') != \
                    QMessageBox.StandardButton.Yes:
                return
            try:
                gabarits.enregistrer(venus, remplace_illisible=True)
            except (gabarits.GabaritError, OSError) as exc:
                QMessageBox.warning(self, 'Importer des montages',
                                    f'Rien n\'est repris : {exc}')
                return
            self._gabarits_changed()
            self._flash_status(f'{len(venus)} montage(s) repris de {nom}',
                               True, 5.0)
        else:
            QMessageBox.warning(
                self, 'Importer des réglages',
                f'{nom} n\'est ni une archive de réglages TauDrive, ni un '
                'fichier de bibliothèque (process, préréglages de code, '
                'montages).')

    def _where_settings(self) -> None:
        """Dit où vit l\'état du poste, et pourquoi la mise à jour ne
        le perd pas."""
        lignes = [
            '<p>Rien de ce que l\'atelier accumule n\'est rangé '
            '<b>dans</b> le dossier du programme.</p>',
            '<style>td{padding:2px 14px 2px 0}</style><table>']
        for quoi, ou, dedans in settingsio.locations():
            couleur = theme.current().warn if dedans else theme.current().ok
            lignes.append(
                f'<tr><td>{quoi}</td>'
                f'<td style="color:{couleur}">{ou}</td></tr>')
        lignes.append('</table>')
        lignes.append(
            '<p><b>Mettre à jour ne perd donc rien</b> : on remplace le '
            'dossier <i>TauDrive</i>, et process, dossiers et dessins sont '
            'retrouvés au lancement suivant.</p>'
            '<p>Ce qui les sépare du programme, c\'est le <b>compte '
            'Windows</b> : un poste qui change de session ne les voit plus. '
            'C\'est le cas où <i>Exporter les réglages</i> sert.</p>')
        boite = QMessageBox(self)
        boite.setWindowTitle('Où sont rangés mes réglages ?')
        boite.setTextFormat(Qt.RichText)
        boite.setText(chr(10).join(lignes))
        boite.exec()

    def _set_naming(self, mode: str) -> None:
        session.set_export_naming(mode)
        for action, key in self._naming_actions:
            action.setChecked(key == mode)
        libelle = next(l for k, l, _ in session.EXPORT_NAMING if k == mode)
        self.statusBar().showMessage(f'Exports répétés : {libelle.lower()}',
                                     4000)

    def _edit_shell_menu(self) -> None:
        """Pose ou retire le « Convertir avec TauDrive » du clic droit."""
        shellmenu.ShellMenuDialog(self).exec()

    def _edit_folders(self) -> None:
        dialog = folders.FolderSettings(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_export_dirs()
            default = session.default_folder('export')
            if default and not self.w_export_dir.currentText().strip():
                self.w_export_dir.setCurrentText(default)
            self.statusBar().showMessage('Dossiers par défaut enregistrés',
                                         4000)

    def _add_text(self) -> None:
        try:
            textvec.default_font_path()
        except textvec.FontNotFound as exc:
            QMessageBox.warning(self, 'Police', str(exc))
            return
        self._add(Text(text='TEXTE', size_mm=6, recipe=self._default_recipe()))
        # On pose un texte pour le taper : le champ prend la main tout de
        # suite, « TEXTE » sélectionné, et ce qu'on tape le remplace.
        QTimer.singleShot(0, self._focus_text_field)

    def _focus_text_field(self, insiste: bool = False) -> None:
        """Le contenu de la forme montrée prend le focus, s'il en a un.

        `insiste` repose le focus une fraction de seconde plus tard.
        Après un double-clic, la **fin** de la séquence de souris — le
        relâchement, qui arrive après notre tour d'événements — rendait
        la main au plan de travail : le curseur clignotait dans le champ,
        et ce qu'on tapait n'y entrait pas. On le repose donc une fois la
        séquence éteinte, et seulement si elle l'a vraiment reprise.
        """
        if self._insp_stack.currentIndex() != 0:
            return
        if self.inspector.focus_text():
            self._dock_insp.show()
        if insiste:
            QTimer.singleShot(RECLAIM_FOCUS_MS, self._reclaim_text_focus)

    def _reclaim_text_focus(self) -> None:
        """Repose le focus dans le champ s'il l'a perdu entre-temps."""
        if self._insp_stack.currentIndex() != 0:
            return
        champ = self.inspector.text_field()
        if champ is None or champ.hasFocus():
            return
        courant = self.focusWidget()
        # On ne reprend la main que si elle est repartie au plan de
        # travail : si l'opérateur a lui-même cliqué ailleurs entre-temps,
        # ce serait lui voler son champ.
        if courant is None or isinstance(courant, Canvas):
            self.inspector.focus_text()

    def _edit_requested(self, shape_id: str) -> None:
        """Double-clic sur un texte ou un code au plan : on vient le taper.

        Le formulaire est déjà ouvert par le premier clic — celui de la
        forme, du lot ou du montage selon la sélection. Il reste à
        mettre le focus dans **le bon champ** : le texte de la forme, la
        donnée du code, ou la référence du poste s'il s'agit d'un
        montage.
        """
        shape = self.document.get(shape_id)
        if shape is None:
            return
        page = self._insp_stack.currentIndex()
        if page == 2:
            if self.montage_form.focus_for(shape_id):
                self._dock_insp.show()
                return
        if page == 1 or self.inspector._shape is not shape:
            self.inspector.set_shape(shape)
            self._insp_stack.setCurrentIndex(0)
        QTimer.singleShot(0, lambda: self._focus_text_field(insiste=True))

    def _default_recipe(self) -> Recipe:
        """Process à poser sur une forme neuve, **celle du dernier emploi**.

        La première entrée de la bibliothèque n'a aucune raison d'être
        celle du travail en cours : dans un travail d'acier satiné, tout
        est satiné. La process employée en dernier est donc retenue
        **par onglet** — deux travaux ouverts côte à côte ne gravent pas
        la même matière — et suit le document quand on l'enregistre.
        """
        derniere = getattr(self.document, 'last_recipe', None)
        if derniere is not None:
            return derniere
        if RECIPE_LIBRARY:
            return RECIPE_LIBRARY[0]
        prereglages = preset_recipes()
        return prereglages[min(1, len(prereglages) - 1)]

    def _remember_recipe(self, recipe) -> None:
        """Retient la process de cet onglet, pour la forme suivante."""
        if recipe is None or self.canvas is None:
            return
        if self.document.last_recipe != recipe:
            self.document.last_recipe = recipe

    def _import_dxf(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, 'Importer un dessin', session.start_folder('dxf'),
            dxfimport.FILE_FILTER)
        if not file_path:
            return
        session.remember_file('dxf', file_path)
        dialog = DxfImportDialog(self, file_path, self.document,
                                 self._default_recipe())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        shapes = dialog.selected_shapes()
        if not shapes:
            return
        for shape in shapes:
            self.document.add(shape)
        # un DXF arrive en plusieurs calques : ils forment naturellement un
        # groupe, qu'on peut défaire d'un S si besoin
        if len(shapes) > 1:
            self.document.group([s.id for s in shapes])
        self._leave_library()
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select(shapes[0].id)
        self.canvas.fit()
        self._touch()

    def _add_date(self, checked: bool = False, fmt: str = '') -> None:
        """Pose la date du jour, au format retenu.

        Champ variable, pas texte figé : une plaque préparée lundi et
        gravée mercredi porte la date du mercredi. C'est presque toujours
        ce qu'on veut, et jamais ce qu'un texte tapé à la main donnerait.
        """
        reglages = datestamp.defaults()
        if fmt:
            reglages['format'] = fmt
            datestamp.remember(format=fmt)
        try:
            textvec.default_font_path()
        except textvec.FontNotFound as exc:
            QMessageBox.warning(self, 'Police', str(exc))
            return
        forme = datestamp.build(reglages, self._default_recipe())
        self._add(forme)
        self.statusBar().showMessage(
            f'Date posée : « {datestamp.sample(reglages["format"])} » '
            f'aujourd\'hui, recalculée à chaque export', 6000)

    def _add_date_options(self) -> None:
        dialog = datestamp.DateOptions(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        valeurs = dialog.values()
        datestamp.remember(**valeurs)
        forme = datestamp.build(valeurs, self._default_recipe())
        self._add(forme)
        self.statusBar().showMessage(
            f'Date posée : « {datestamp.sample(valeurs["format"])} » '
            f'aujourd\'hui, hauteur {forme.size_mm:g} mm', 6000)

    def _treat(self) -> None:
        """Prépare un dessin à la gravure en négatif, original conservé.

        Copie la sélection, écarte et masque l'original, puis applique
        cadre, marge, offset et épaisseur **sur la copie**. L'original
        reste consultable dans le document — et regravable d'un clic sur
        son œil — sans partir à la machine.
        """
        originaux = self.canvas.selected_shapes() if self.canvas else []
        if not originaux:
            self.statusBar().showMessage(
                'Sélectionnez le dessin à traiter', 3000)
            return
        dialog = treatment.TreatmentDialog(self, originaux)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        copies, paires = [], []
        for forme in originaux:
            try:
                copie = serialize.shape_from_dict(
                    serialize.shape_to_dict(forme), new_id=True)
            except Exception as exc:
                avale('copie de forme : entrée illisible', exc)
                continue
            copie.group = ''
            copies.append(self.document.add(copie))
            paires.append((copie, forme.group))
        if not copies:
            QMessageBox.warning(self, 'Traitement', 'Copie impossible.')
            return
        # les groupes de l'original, sous des noms neufs — voir
        # `Document.regroup_copies`
        self.document.regroup_copies(paires)

        treatment.apply(copies, **dialog.values())
        treatment.separate(originaux)

        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many([c.id for c in copies])
        self._touch()
        self.statusBar().showMessage(
            f'Traité : {len(copies)} copie(s) — l\'original reste à sa '
            f'place, masqué. Rouvrez son œil pour le graver', 8000)

    def _library(self) -> None:
        """Ouvre — ou referme — la bibliothèque de dessins.

        Elle prend les colonnes 2 et 3, comme le gestionnaire de process :
        l'aperçu à la place du plan de travail, l'arborescence à la place
        des propriétés. Un dessin se choisit en le voyant grand.
        """
        if self.center.currentIndex() == 2:
            self._leave_library()
            return
        if not self._leave_montages():
            return
        # depuis les process : le magasin d'outils leur appartient, il ne
        # reste pas ouvert à côté de la bibliothèque
        if self.center.currentIndex() == 1:
            self._leave_recipes()
        self.library_panel.set_recipe(self._default_recipe())
        self.library_panel.reload()
        self.center.setCurrentIndex(2)
        self._dock_insp.hide()
        self._dock_biblio.show()
        self._dock_biblio.raise_()
        self._label_library_button()
        self.statusBar().showMessage(
            'Bibliothèque de dessins — « Insérer » pose le dessin, '
            '« Terminé » revient au plan de travail', 8000)

    def _leave_library(self) -> None:
        """Rend les colonnes 2 et 3 au dessin et à ses propriétés."""
        # appelé aussi après un import, quelle que soit la réserve
        # ouverte : le gestionnaire de montages a son mot à dire
        if self.center.currentIndex() == 3:
            self._leave_montages()
            return
        # Le dessin lu en entier a fini son office : le garder pèserait le
        # poids du fichier pour tout le reste de la séance.
        self.library_panel.forget_loaded()
        self.center.setCurrentIndex(0)
        self._dock_biblio.hide()
        self._dock_insp.show()
        self._dock_insp.raise_()
        self._label_library_button()
        self._selection_changed()

    def _label_library_button(self) -> None:
        ouverte = self.center.currentIndex() == 2
        self.w_library_action.setText('Fermer la bibliothèque'
                                      if ouverte else 'Bibliothèque…')
        self.w_library_action.setToolTip(
            'Referme la bibliothèque et rend le plan de travail'
            if ouverte else
            'Dessins rangés une fois pour toutes : livrés avec TauDrive '
            'ou ajoutés par l\'atelier')
        routeur = getattr(self, '_help_router', None)
        bouton = getattr(self, 'w_library_button', None)
        if routeur is not None and bouton is not None:
            routeur.refresh(bouton)

    def _library_insert(self, entry) -> None:
        """Pose sur le plan de travail le dessin choisi dans l'arbre.

        Un `.dxf` arrive avec la process courante ; un `.taudrive` arrive
        avec **les siennes** — c'est l'intérêt d'y ranger une plaque déjà
        validée sur chute.

        La lecture passe par la même barre d'avancement que *Visualiser*,
        et s'annule de même : dix mégaoctets de polylignes prennent
        plusieurs secondes, et une fenêtre figée sans explication a toutes
        les apparences d'un plantage. Un dessin déjà visualisé n'est pas
        relu.
        """
        self.library_panel.set_recipe(self._default_recipe())
        shapes, erreur = self.library_panel.shapes_for(entry)
        if erreur:
            QMessageBox.warning(self, 'Bibliothèque',
                                f'« {entry.name} » illisible : {erreur}')
            return
        if shapes is None:
            self.statusBar().showMessage(
                f'« {entry.name} » — lecture annulée', 4000)
            return
        if not shapes:
            QMessageBox.information(self, 'Bibliothèque',
                                    f'« {entry.name} » ne contient aucun '
                                    f'tracé.')
            return
        for shape in shapes:
            self.document.add(shape)
        # un dessin de bibliothèque est un tout : il se déplace et se
        # redimensionne d'un bloc, comme un DXF importé
        if len(shapes) > 1:
            self.document.group([s.id for s in shapes])
        self._leave_library()
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select(shapes[0].id)
        self._touch()
        self.statusBar().showMessage(
            f'« {entry.name} » posé — F2 pour le mettre à la cote', 6000)

    def _duplicate(self) -> None:
        """Duplique la sélection **à côté**, pas par-dessus.

        La copie se posait cinq millimètres plus loin. Sur une plaquette
        de quinze millimètres cela se voyait ; sur un dessin importé de
        deux cents, les deux exemplaires se superposaient à l'écran et
        l'on croyait que rien ne s'était passé — puis on gravait deux
        fois le même tracé au même endroit.

        La copie est donc décalée de **la largeur de la sélection**, plus
        deux millimètres de jour : elle est toujours visiblement à côté,
        quelle que soit la taille. Si la place manque à droite, elle va
        dessous ; si le champ est plein, on retombe sur le petit décalage
        — mieux vaut une copie à déplacer qu'un refus.
        """
        ids = self.canvas.selected_ids()
        if not ids:
            return
        # L'ordre du document, et non celui de la sélection : une plaque
        # codée doit garder son symbole avant son texte, puisque c'est
        # l'ordre de gravure.
        voulus = set(ids)
        ordonnes = [s.id for s in self.document.shapes if s.id in voulus]
        dx, dy = self._duplicate_offset(ordonnes)
        copies, liens = [], {}
        for shape_id in ordonnes:
            copie = self.document.duplicate(shape_id, dx, dy)
            if copie is not None:
                copies.append(copie)
                liens[shape_id] = copie.id
        # **Le texte d'une plaque suit le code de la copie**, pas celui de
        # l'original. Sans cela, retaper la donnée de l'original changeait
        # aussi le texte lisible de la copie, et deux plaques partaient
        # avec des numéros qui se contredisent.
        for copie in copies:
            suivi = getattr(copie, 'follows', '')
            if suivi and suivi in liens:
                copie.follows = liens[suivi]
        # une copie de groupe est un nouveau groupe, pas un ajout à
        # l'ancien ; une forme qui n'était pas groupée ne l'est pas plus en
        # copie — voir `Document.regroup_copies`
        self.document.regroup_copies([(c, c.group) for c in copies])
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many([c.id for c in copies])
        self._touch()
        self.statusBar().showMessage(
            f'{len(copies)} copie(s) posée(s) à {dx:+g} / {dy:+g} mm', 3000)

    #: Jour laissé entre une forme et sa copie, en millimètres.
    DUPLICATE_GAP_MM = 2.0

    def _duplicate_offset(self, ids: list[str]) -> tuple[float, float]:
        """De combien poser la copie : à droite, sinon dessous."""
        from .toolpath import shape_extent
        boites = []
        for shape_id in ids:
            forme = self.document.get(shape_id)
            if forme is None:
                continue
            try:
                boite = shape_extent(forme)
            except Exception as exc:                   # noqa: BLE001
                from .avale import avale
                avale('duplication : encombrement non mesuré', exc)
                boite = None
            if boite:
                boites.append(boite)
        if not boites:
            return 5.0, -5.0
        x1 = min(b[0] for b in boites)
        y1 = min(b[1] for b in boites)
        x2 = max(b[2] for b in boites)
        y2 = max(b[3] for b in boites)
        jour = self.DUPLICATE_GAP_MM
        largeur, hauteur = (x2 - x1) + jour, (y2 - y1) + jour
        hw, hh = self.document.field_w / 2, self.document.field_h / 2
        if x2 + largeur <= hw:
            return largeur, 0.0
        if y1 - hauteur >= -hh:
            return 0.0, -hauteur
        return 5.0, -5.0

    def _paint_export_button(self) -> None:
        """Couleur d'accord du thème : vert s'il en a un, orange sinon.

        La couleur vient du **thème**, jamais d'une constante : les
        dix-neuf palettes n'ont pas le même vert, et un vert sombre sur un
        fond clair ne se verrait pas. Quand `ok` manque de contraste sur le
        panneau, c'est `warn` — l'orange — qui prend le relais.
        """
        bouton = getattr(self, 'w_export_button', None)
        if bouton is None:
            return
        palette = theme.current()
        fond = palette.ok if _contraste(palette.ok, palette.panel) >= 2.6             else palette.warn
        encre = palette.ink if palette.dark else '#ffffff'
        bouton.setStyleSheet(
            f'QToolButton {{ background: {fond}; color: {encre};'
            f' border: 1px solid {fond}; border-radius: 5px;'
            f' padding: 4px 14px; font-weight: 600; }}'
            f'QToolButton:hover {{ border-color: {palette.text}; }}'
            f'QToolButton:pressed {{ background: {palette.accent_deep}; }}')
        bouton.setIcon(icons.icon('lancer_export', encre))

    def _flash_status(self, message: str, ok: bool,
                      seconds: float = 2.0) -> None:
        """Colore la barre d'état deux secondes : vert réussi, rouge échoué.

        Les couleurs viennent du **thème** — `ok` et `alarm` — et non de
        constantes : un thème clair et un thème à contraste élevé n'ont pas
        le même vert, et un vert sombre sur fond clair ne se verrait pas.

        Deux secondes, puis retour à la normale. Une barre qui resterait
        verte finirait par ne plus rien dire.
        """
        palette = theme.current()
        fond = palette.ok if ok else palette.alarm
        encre = palette.ink if palette.dark else '#ffffff'
        self.statusBar().setStyleSheet(
            f'QStatusBar {{ background: {fond}; color: {encre}; }}'
            f'QStatusBar::item {{ border: 0; }}')
        # l'aide s'efface le temps de l'éclat : un texte atténué sur fond
        # vert ne se lit pas, et la bande doit rester nette
        if hasattr(self, 'w_help'):
            self.w_help.setVisible(False)
        self.statusBar().showMessage(message, int(seconds * 1000))
        self._flash_timer.start(int(seconds * 1000))

    def _clear_flash(self) -> None:
        self.statusBar().setStyleSheet('')
        if hasattr(self, 'w_help'):
            self.w_help.setVisible(True)

    def _reopen_tab(self) -> None:
        """Rouvre un onglet fermé, choisi par mot-clé."""
        dialog = ClosedTabs(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.chosen:
            return
        entree = dialog.chosen
        contenu = session.read_closed(entree)
        if not contenu:
            QMessageBox.warning(
                self, 'Onglets fermés',
                'L' + chr(39) + 'archive de cet onglet est introuvable :'
                + chr(10) + str(entree.get('file', '')))
            return
        try:
            document = serialize.loads(contenu)
        except Exception as exc:
            QMessageBox.warning(self, 'Onglets fermés',
                                f'Contenu illisible : {exc}')
            return
        tab = self.new_tab(document, entree.get('path', ''))
        tab.dirty = True
        self._tab_changed()
        self._retitle(tab)
        tab.fit()
        self._touch()
        self.statusBar().showMessage(
            f'« {document.name} » rouvert', 5000)

    def _rename_shape(self, item) -> None:
        """Double-clic sur une forme : la renommer.

        Le nom d'une forme n'est pas celui du travail — celui-là se règle
        sur l'onglet et sert de nom de dossier à l'export. C'est
        l'étiquette qu'on lit dans la liste et qui part en commentaire dans
        l'ISO, de quoi retrouver une forme parmi trente.
        """
        shape = self.document.get(item.data(Qt.UserRole)) if item else None
        if shape is None:
            return
        # Le champ part **vide** tant que personne n'a renommé, et non
        # rempli du nom dérivé : le pré-remplir figerait le nom au
        # premier « OK » machinal, et la forme cesserait de suivre
        # sa donnée sans que personne ne l'ait demandé.
        invite = ('Nom, vide pour le laisser suivre le contenu\n'
                  f'(actuellement : {shape.display_name()})')
        nom, ok = QInputDialog.getText(
            self, 'Renommer la forme', invite, text=shape.name)
        if not ok:
            return
        # Vider le champ **rend le nom au calcul** : c'est la seule façon
        # de défaire un renommage, et elle doit rester simple.
        shape.name = nom.strip()
        self._relabel_list()
        self._touch()

    def _shape_menu(self, point) -> None:
        """Clic droit sur une forme : ce qu'on fait à une forme entière."""
        item = self.shape_list.itemAt(point)
        if item is None:
            return
        shape_id = item.data(Qt.UserRole)
        shape = self.document.get(shape_id)
        if shape is None:
            return
        # Un clic droit **dans** une sélection multiple la conserve : la
        # défaire obligerait à tout ré-désigner avant d'agir sur le lot.
        if shape_id not in (self.canvas.selected_ids() if self.canvas
                            else []):
            self.canvas.select(shape_id)
        menu = QMenu(self)
        a_voir = menu.addAction('Masquer' if shape.visible else 'Afficher')
        a_ren = menu.addAction('Renommer…')
        menu.addSeparator()
        a_dup = menu.addAction('Dupliquer')
        a_sup = menu.addAction('Supprimer')
        menu.addSeparator()
        a_haut = menu.addAction('Monter')
        a_bas = menu.addAction('Descendre')
        # Un dessin importé arrive d'un bloc : tant qu'il l'est, on ne peut
        # ni masquer une de ses polylignes, ni en décaler une seule.
        a_cadre = a_separer = None
        if splitting.splittable(shape):
            menu.addSeparator()
            nb_tracés = splitting.polyline_count(shape)
            if splitting.frame_indices(shape.polylines):
                a_cadre = menu.addAction('Détacher le cadre extérieur')
                a_cadre.setToolTip(
                    'Sort dans sa propre forme le tracé qui englobe tout le '
                    'reste. Sous la règle pair-impair du hachurage, un tel '
                    'cadre inverse le remplissage : le masquer suffit à le '
                    'remettre d\'aplomb.')
            a_separer = menu.addAction(
                f'Séparer les {nb_tracés} tracés…')
            a_separer.setToolTip(
                'Une forme par polyligne : chacune reçoit son œil, sa '
                'duplication, son offset et son F2.')

        menu.addSeparator()
        a_miroir_h = menu.addAction('Retourner gauche ↔ droite')
        a_miroir_v = menu.addAction('Retourner haut ↕ bas')
        a_trace = None
        if conversion.convertible(shape):
            a_trace = menu.addAction('Convertir en tracé')
            a_trace.setToolTip(
                'Fige la forme en polylignes : elle se sépare et se '
                'retourne, mais ne se retape plus.')
        a_arc = None
        if cintrage.cintrable(shape):
            a_arc = menu.addAction('Cintrer en arc…')
            a_arc.setToolTip(
                'Couche le texte sur un cercle ; il devient un tracé.')
        menu.addSeparator()
        a_couteau = menu.addAction('Couteau…')
        a_couteau.setToolTip(
            'Donne une épaisseur au tracé et en rend le contour fermé.')
        combien = len(self.canvas.selected_shapes()) if self.canvas else 1
        a_coupon = menu.addAction(
            'En faire un coupon d\'essai…' if combien < 2 else
            f'Faire un coupon d\'essai de ces {combien} formes…')
        a_coupon.setToolTip(
            'Grave ce dessin dans chaque case du coupon, au lieu d\'un '
            'carré plein.')
        choisi = menu.exec(self.shape_list.mapToGlobal(point))
        if choisi is a_voir:
            self._toggle_visible(shape_id)
        elif choisi is a_ren:
            self._rename_shape(item)
        elif choisi is a_dup:
            self._duplicate_one(shape_id)
        elif choisi is a_sup:
            self._remove_one(shape_id)
        elif choisi in (a_haut, a_bas):
            self._reorder(shape_id, -1 if choisi is a_haut else 1)
        elif choisi is a_coupon:
            self._coupon_from_selection()
        elif a_cadre is not None and choisi is a_cadre:
            self._detach_frame(shape_id)
        elif a_separer is not None and choisi is a_separer:
            self._explode(shape_id)
        elif choisi is a_couteau:
            self._knife()
        elif choisi in (a_miroir_h, a_miroir_v):
            self._mirror('h' if choisi is a_miroir_h else 'v')
        elif a_trace is not None and choisi is a_trace:
            self._convert_to_path()
        elif a_arc is not None and choisi is a_arc:
            self._bend_text()

    def _substitute(self, neuves: list, message: str) -> None:
        """Remet des formes transformées à la place de celles qui portent
        leur identifiant, puis redessine — même ordre, même sélection."""
        par_id = {s.id: s for s in neuves}
        self.document.shapes = [par_id.get(s.id, s)
                                for s in self.document.shapes]
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many(list(par_id))
        self._touch()
        self.statusBar().showMessage(message, 5000)

    def _repeat_grid(self) -> None:
        """Recopie la sélection en grille — voir `repetition`."""
        formes = self.canvas.selected_shapes() if self.canvas else []
        if not formes:
            self.statusBar().showMessage(
                'Répéter : sélectionnez d\'abord ce qu\'il faut recopier',
                3000)
            return
        fenetre = repetition.RepetitionDialog(self, formes, self.document)
        if fenetre.exec() != QDialog.DialogCode.Accepted:
            return
        colonnes, rangees, pas_x, pas_y = fenetre.values()
        copies = repetition.repeter(self.document, formes, colonnes,
                                    rangees, pas_x, pas_y)
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many([s.id for s in formes]
                                + [c.id for c in copies])
        self._touch()
        self.statusBar().showMessage(
            f'Grille {colonnes} × {rangees} : {len(copies)} forme(s) '
            f'ajoutée(s)', 5000)

    def _repeat_circle(self) -> None:
        """Recopie la sélection autour d'un centre — voir `repetition`."""
        formes = self.canvas.selected_shapes() if self.canvas else []
        if not formes:
            self.statusBar().showMessage(
                'Répéter en cercle : sélectionnez d\'abord ce qu\'il faut '
                'recopier', 3000)
            return
        fenetre = repetition.CercleDialog(self, formes, self.document)
        if fenetre.exec() != QDialog.DialogCode.Accepted:
            return
        nombre, cx, cy, angle, orienter = fenetre.values()
        try:
            copies = repetition.repeter_en_cercle(
                self.document, formes, nombre, cx, cy, angle, orienter)
        except ValueError as exc:
            QMessageBox.warning(self, 'Répéter en cercle', str(exc))
            return
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many([s.id for s in formes]
                                + [c.id for c in copies])
        self._touch()
        self.statusBar().showMessage(
            f'Cercle de {nombre} cases sur {angle:g}° : {len(copies)} '
            f'forme(s) ajoutée(s)', 5000)

    def _convert_to_path(self) -> None:
        """Fige en tracés les textes, rectangles et ellipses sélectionnés —
        voir `conversion`."""
        formes = [s for s in (self.canvas.selected_shapes()
                              if self.canvas else [])
                  if conversion.convertible(s)]
        if not formes:
            self.statusBar().showMessage(
                'Convertir en tracé : sélectionnez un texte, un rectangle '
                'ou une ellipse', 4000)
            return
        if not self._accept_frozen_fields(formes, 'Convertir en tracé'):
            return
        neuves = [conversion.en_trace(s) for s in formes]
        self._substitute(neuves, f'{len(neuves)} forme(s) converties en '
                                 f'tracé — elles ne se retapent plus')

    def _bend_text(self) -> None:
        """Cintre le texte sélectionné sur un cercle — voir `cintrage`."""
        textes = [s for s in (self.canvas.selected_shapes()
                              if self.canvas else [])
                  if cintrage.cintrable(s)]
        if len(textes) != 1:
            self.statusBar().showMessage(
                'Cintrer en arc : sélectionnez un texte, et un seul', 4000)
            return
        texte = textes[0]
        fenetre = cintrage.CintrageDialog(self, texte)
        if fenetre.exec() != QDialog.DialogCode.Accepted:
            return
        if not self._accept_frozen_fields([texte], 'Cintrer en arc'):
            return
        rayon, cote = fenetre.values()
        try:
            arc = cintrage.cintrer(texte, rayon, cote)
        except ValueError as exc:
            QMessageBox.warning(self, 'Cintrer en arc', str(exc))
            return
        self._substitute([arc], f'« {arc.display_name()} » cintré sur un '
                                f'rayon de {rayon:g} mm — il ne se retape '
                                f'plus')

    def _accept_frozen_fields(self, formes: list, titre: str) -> bool:
        """Vrai si aucun texte ne perd de champ variable, ou si l'on
        accepte de les figer."""
        figes = [s for s in formes if isinstance(s, Text)
                 and variables.has_fields(s.text)]
        # un texte qui suit un code — la référence en clair d'une plaque —
        # ne suivrait plus : retaper le code laisserait l'ancien numéro
        # gravé à côté, et le code et son texte se contrediraient
        suiveurs = [s for s in formes if isinstance(s, Text)
                    and getattr(s, 'follows', '')]
        if not figes and not suiveurs:
            return True
        raisons = []
        if figes:
            raisons.append(
                f'{len(figes)} texte(s) portent des champs variables — '
                f'date, numéro de série. Convertis en tracé, ils garderont '
                f'leur valeur d\'aujourd\'hui sur toutes les pièces.')
        if suiveurs:
            raisons.append(
                f'{len(suiveurs)} texte(s) suivent un code. Convertis en '
                f'tracé, ils ne le suivront plus : retaper le code laissera '
                f'l\'ancien texte gravé à côté.')
        reponse = QMessageBox.question(
            self, titre, '\n\n'.join(raisons) + '\n\nContinuer ?',
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel)
        return reponse == QMessageBox.StandardButton.Yes

    def _mirror(self, axe: str) -> None:
        """Retourne la sélection autour de son centre — voir `conversion`."""
        formes = self.canvas.selected_shapes() if self.canvas else []
        if not formes:
            self.statusBar().showMessage(
                'Retourner : sélectionnez d\'abord une ou plusieurs formes',
                3000)
            return
        if any(isinstance(s, Code) for s in formes):
            QMessageBox.information(
                self, 'Retourner',
                'Un code 2D ne se retourne pas : retourné, il ne se lit '
                'plus de face, et une pièce marquée d\'un code que le '
                'lecteur refuse est perdue.\n\nRetirez le code de la '
                'sélection — dégroupez une plaque au besoin.')
            return
        textes = [s for s in formes if isinstance(s, Text)]
        if textes:
            reponse = QMessageBox.question(
                self, 'Retourner',
                f'{len(textes)} texte(s) seront d\'abord convertis en '
                f'tracé : retournés, ils ne se retaperont plus.\n\n'
                f'Continuer ?',
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel)
            if reponse != QMessageBox.StandardButton.Yes:
                return
            if not self._accept_frozen_fields(textes, 'Retourner'):
                return
            formes = [conversion.en_trace(s) if isinstance(s, Text) else s
                      for s in formes]
        neuves = conversion.retourner(formes, axe)
        sens = 'de gauche à droite' if axe == 'h' else 'de haut en bas'
        self._substitute(neuves, f'{len(neuves)} forme(s) retournée(s) '
                                 f'{sens}')

    def _replace_shape(self, shape_id: str, neuves: list) -> None:
        """Remplace une forme par plusieurs, **à sa place dans l'ordre**.

        L'ordre de la liste est l'ordre de gravure : renvoyer les morceaux
        en fin de liste changerait le travail sans que personne ne l'ait
        demandé.
        """
        formes = self.document.shapes
        rang = next((i for i, s in enumerate(formes) if s.id == shape_id), -1)
        if rang < 0:
            return
        groupe = formes[rang].group
        self.document.shapes = formes[:rang] + list(neuves) + formes[rang + 1:]
        if groupe:
            # Un membre séparé reste dans **son** groupe : les morceaux du
            # reste d'un logo de plus de quatre cents tracés, rangés dans
            # un groupe à eux, perdaient l'alternance avec le reste du
            # logo — leurs trous se remplissaient de nouveau.
            for s in neuves:
                s.group = groupe
        elif len(neuves) > 1:
            self.document.group([s.id for s in neuves])
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many([s.id for s in neuves])
        self._touch()

    def _detach_frame(self, shape_id: str) -> None:
        """Sort le cadre englobant dans sa propre forme, et le masque.

        Masqué d'emblée : c'est ce qu'on veut neuf fois sur dix — un cadre
        de plan qui inverse le hachurage n'a rien à faire sur la pièce. Un
        clic sur son œil le rend s'il servait.
        """
        forme = self.document.get(shape_id)
        morceaux = splitting.detach_frame(forme) if forme is not None else None
        if not morceaux:
            self.statusBar().showMessage(
                'Aucun tracé n\'englobe les autres dans cette forme', 4000)
            return
        morceaux[0].visible = False
        self._replace_shape(shape_id, morceaux)
        self.statusBar().showMessage(
            f'Cadre détaché et masqué — {len(morceaux[0].polylines)} '
            f'tracé(s). Son œil le rend si besoin.', 8000)

    def _explode(self, shape_id: str) -> None:
        """Une forme par polyligne, après avertissement si la liste enfle."""
        forme = self.document.get(shape_id)
        if forme is None or not splitting.splittable(forme):
            return
        combien = splitting.polyline_count(forme)
        limite = 0
        if combien > splitting.BUSY_COUNT:
            reponse = QMessageBox.question(
                self, 'Séparer les tracés',
                f'Ce dessin porte {combien} tracés.\n\n'
                f'Les séparer tous rendrait la liste des formes '
                f'inutilisable.\n\n'
                f'Séparer les {splitting.BUSY_COUNT} premiers et laisser le '
                f'reste réuni ?',
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel)
            if reponse != QMessageBox.StandardButton.Yes:
                return
            limite = splitting.BUSY_COUNT
        morceaux = splitting.explode(forme, limit=limite)
        if len(morceaux) < 2:
            return
        self._replace_shape(shape_id, morceaux)
        self.statusBar().showMessage(
            f'{len(morceaux)} formes — chacune a son œil, sa duplication, '
            f'son offset et son F2', 8000)

    def _combine(self) -> None:
        """Q : réunit la sélection en un seul tracé — voir
        `splitting.combine`. Il prend la place de la première forme dans
        l'ordre de gravure."""
        formes = self.canvas.selected_shapes() if self.canvas else []
        rang = {s.id: i for i, s in enumerate(self.document.shapes)}
        retenues = sorted((s for s in formes if splitting.combinable(s)),
                          key=lambda s: rang.get(s.id, len(rang)))
        if len(retenues) < 2:
            self.statusBar().showMessage(
                'Combiner : sélectionnez au moins deux formes — tracés, '
                'textes, rectangles ou ellipses', 4000)
            return
        if not self._accept_frozen_fields(retenues, 'Combiner'):
            return
        combine = splitting.combine(retenues)
        if combine is None:
            self.statusBar().showMessage(
                'Combiner : ces formes ne donnent aucun tracé', 4000)
            return
        ids = {s.id for s in retenues}
        premier = min(rang[i] for i in ids)
        avant = [s for s in self.document.shapes[:premier]]
        apres = [s for s in self.document.shapes[premier:]
                 if s.id not in ids]
        self.document.shapes = avant + [combine] + apres
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many([combine.id])
        self._touch()
        notes = [f'{len(retenues)} formes combinées en un tracé de '
                 f'{len(combine.polylines)} polyligne(s)']
        if any(s.recipe != retenues[0].recipe for s in retenues):
            notes.append(f'process de « {retenues[0].display_name()} » '
                         f'pour le tout')
        laissees = len(formes) - len(retenues)
        if laissees:
            notes.append(f'{laissees} code(s) laissé(s) à part')
        self.statusBar().showMessage(' — '.join(notes), 8000)

    def _uncombine(self) -> None:
        """S : sépare chaque tracé ou texte sélectionné en ses polylignes.

        C'est *Séparer les tracés* sur toute la sélection, textes
        compris : les morceaux sortent groupés — ou restent dans le groupe
        de la forme —, et le pair-impair du groupe garde le remplissage tel
        qu'il était (voir `toolpath.group_zones`).
        """
        formes = self.canvas.selected_shapes() if self.canvas else []
        rang = {s.id: i for i, s in enumerate(self.document.shapes)}
        cibles = sorted((s for s in formes if splitting.uncombinable(s)),
                        key=lambda s: rang.get(s.id, len(rang)))
        if not cibles:
            self.statusBar().showMessage(
                'Décombiner : sélectionnez un tracé de plusieurs polylignes, '
                'ou un texte', 4000)
            return
        textes = [s for s in cibles if isinstance(s, Text)]
        if textes and not self._accept_frozen_fields(textes, 'Décombiner'):
            return
        traces = [conversion.en_trace(s) if isinstance(s, Text) else s
                  for s in cibles]
        limite = 0
        lourds = [t for t in traces
                  if splitting.polyline_count(t) > splitting.BUSY_COUNT]
        if lourds:
            combien = max(splitting.polyline_count(t) for t in lourds)
            reponse = QMessageBox.question(
                self, 'Décombiner',
                f'Un dessin de la sélection porte {combien} tracés.\n\n'
                f'Les séparer tous rendrait la liste des formes '
                f'inutilisable.\n\n'
                f'Séparer les {splitting.BUSY_COUNT} premiers de chacun et '
                f'laisser le reste réuni ?',
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel)
            if reponse != QMessageBox.StandardButton.Yes:
                return
            limite = splitting.BUSY_COUNT
        par_id: dict[str, list] = {}
        for source, trace in zip(cibles, traces):
            morceaux = splitting.explode(trace, limit=limite)
            if len(morceaux) < 2:
                continue
            # mêmes règles que `_replace_shape` : un membre séparé reste
            # dans son groupe, des morceaux libres forment le leur
            if source.group:
                for m in morceaux:
                    m.group = source.group
            par_id[source.id] = morceaux
        if not par_id:
            self.statusBar().showMessage(
                'Décombiner : rien à séparer dans cette sélection', 4000)
            return
        neuves = []
        resultat = []
        for s in self.document.shapes:
            morceaux = par_id.get(s.id)
            if morceaux is None:
                resultat.append(s)
            else:
                resultat.extend(morceaux)
                neuves.extend(morceaux)
        self.document.shapes = resultat
        for source_id, morceaux in par_id.items():
            if not morceaux[0].group:
                self.document.group([m.id for m in morceaux])
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many([s.id for s in neuves])
        self._touch()
        self.statusBar().showMessage(
            f'{len(par_id)} forme(s) décombinée(s) en {len(neuves)} '
            f'tracés, groupés : le remplissage ne change pas', 8000)

    def _center_selection(self) -> None:
        """Alt+W : centre la sélection dans le champ — le bouton *Au
        centre* du lot (`disposition.centrer`), pour une forme comme pour
        plusieurs."""
        formes = self.canvas.selected_shapes() if self.canvas else []
        if not formes:
            self.statusBar().showMessage(
                'Centrer : sélectionnez d\'abord une ou plusieurs formes',
                3000)
            return
        if not disposition.centrer(formes):
            self.statusBar().showMessage(
                'Déjà au centre du champ : rien n\'a bougé', 3000)
            return
        self.inspector.follow_move()
        self.lot.follow_move()
        ids = self.canvas.selected_ids()
        self.canvas.reload()
        self._relabel_list()
        self.canvas.select_many(ids)
        self._touch()
        self.statusBar().showMessage('Sélection centrée dans le champ', 3000)

    def _knife(self) -> None:
        """Donne une épaisseur à la sélection et en pose le contour fermé.

        Le tracé nu reste dans le document, œil fermé : on y revient si la
        largeur ne convient pas. C\'est la même prudence que le
        traitement du dessin — on ne remplace pas un tracé par un autre
        sans laisser de quoi revenir.
        """
        formes = self.canvas.selected_shapes() if self.canvas else []
        if not formes:
            self.statusBar().showMessage(
                'Couteau : sélectionnez d\'abord un ou plusieurs tracés',
                4000)
            return
        # Les contours de chaque forme, **placés** : le couteau travaille
        # dans le repère du plan de travail, car deux formes qui se
        # touchent doivent donner un seul contour uni.
        tracés = [G.translate(G.rotate(contour, forme.rotation_deg),
                              forme.x, forme.y)
                  for forme in formes
                  for contour in toolpath.shape_contours(forme)]
        if not tracés:
            QMessageBox.information(
                self, 'Couteau',
                'Cette sélection ne donne aucun tracé à épaissir.')
            return
        if not knife.available():
            QMessageBox.warning(self, 'Couteau', knife.MISSING_NOTE)
            return

        fenetre = knife.KnifeDialog(self, tracés)
        if fenetre.exec() != QDialog.DialogCode.Accepted:
            return
        contours = fenetre.contours()
        if not contours:
            return

        # le contour est posé centré comme toute forme importée : sa
        # géométrie est absolue, on la ramène dans le repère local
        b = G.bounds(contours)
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        # le rôle, pas le nom : « couteau 2 mm » est stable, alors que le
        # nom de la source peut changer après coup — le figer ici le
        # rendrait faux sans que rien ne le dise
        lame = Path(polylines=[G.translate(c, -cx, -cy) for c in contours],
                    x=cx, y=cy, recipe=formes[0].recipe,
                    role=f'couteau {fenetre.w_width.value():g} mm')
        if fenetre.keep_original():
            for forme in formes:
                forme.visible = False
        else:
            for forme in formes:
                self.document.remove(forme.id)
        self.document.add(lame)
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select(lame.id)
        self._touch()
        self._flash_status(
            f'Couteau : {len(contours)} contour(s) fermé(s), '
            f'{knife.area_mm2(contours):.1f} mm² de bande', True, 4.0)

    def _reorder(self, shape_id: str, delta: int) -> None:
        """Monte ou descend une forme dans la liste.

        L'ordre de la liste est **l'ordre de gravure** tant que le
        regroupement par recette est coupé : monter une forme, c'est la
        graver plus tôt.
        """
        if not self.document.move_shape(shape_id, delta):
            self.statusBar().showMessage('Déjà en bout de liste', 2000)
            return
        self._refresh_list()
        self.canvas.select(shape_id)
        self._touch()

    def _reorder_selection(self, delta: int) -> None:
        """Déplace **toute la sélection** d'un rang, son ordre conservé.

        Le bloc bute plutôt qu'il ne se tasse : monter alors que la
        première forme touche déjà le haut ne doit pas rapprocher les
        autres d'elle — on perdrait l'ordre interne d'une sélection sans
        l'avoir demandé.
        """
        if self.canvas is None:
            return
        ids = set(self.canvas.selected_ids())
        if not ids:
            self.statusBar().showMessage(
                'Sélectionnez une forme à déplacer dans l\'ordre', 3000)
            return
        formes = self.document.shapes
        rangs = [i for i, s in enumerate(formes) if s.id in ids]
        if not rangs:
            return
        if (delta < 0 and rangs[0] == 0) or (
                delta > 0 and rangs[-1] == len(formes) - 1):
            self.statusBar().showMessage('Déjà en bout de liste', 2000)
            return
        # Les identifiants sont relevés **avant** de bouger : la liste est
        # modifiée en place, les rangs ne valent plus rien dès le premier
        # déplacement. En montant, on commence par celle du haut.
        cibles = [formes[i].id for i in rangs]
        for shape_id in (cibles if delta < 0 else reversed(cibles)):
            self.document.move_shape(shape_id, delta)
        self._refresh_list()
        self.canvas.select_many(list(ids))
        self._touch()
        premier = min(i for i, s in enumerate(self.document.shapes)
                      if s.id in ids)
        self.statusBar().showMessage(
            f'{len(ids)} forme(s) — gravée(s) en position {premier + 1} '
            f'sur {len(self.document.shapes)}', 3000)

    def _tab_menu(self, point) -> None:
        """Clic droit sur un onglet : ce qu'on fait à un onglet entier."""
        index = self.tabs.tabBar().tabAt(point)
        if index < 0:
            return
        menu = QMenu(self)
        a_dup = menu.addAction('Dupliquer l\'onglet')
        a_ren = menu.addAction('Renommer…')
        menu.addSeparator()
        a_close = menu.addAction('Fermer')
        choisi = menu.exec(self.tabs.tabBar().mapToGlobal(point))
        if choisi is a_dup:
            self._duplicate_tab(index)
        elif choisi is a_ren:
            self._rename_tab(index)
        elif choisi is a_close:
            self._close_tab(index)

    def _duplicate_tab(self, index: int = -1) -> None:
        """Ouvre une copie indépendante d'un onglet.

        Copie, et non second onglet sur le même document : on duplique
        pour essayer une variante sans risquer l'original. Les deux
        doivent donc pouvoir diverger, jusqu'aux identifiants de formes.
        """
        if index < 0:
            index = self.tabs.currentIndex()
        source = self.tabs.widget(index)
        if source is None:
            return
        try:
            brut = serialize.document_to_dict(source.document)
            copie = serialize.document_from_dict({**brut, 'shapes': []})
            # identifiants neufs : deux onglets ne doivent pas se partager
            # une forme sans le savoir. L'appartenance à un groupe passe
            # par un nom, pas par un identifiant : elle survit.
            for forme in brut.get('shapes', []):
                copie.shapes.append(
                    serialize.shape_from_dict(dict(forme), new_id=True))
        except Exception as exc:
            QMessageBox.warning(self, 'Dupliquer l\'onglet',
                                f'Copie impossible : {exc}')
            return
        copie.name = f'{source.document.name} (copie)'
        tab = self.new_tab(copie)
        tab.dirty = True
        self._tab_changed()
        self._retitle(tab)
        tab.fit()
        self._touch()
        self.statusBar().showMessage(
            f'Onglet dupliqué : {copie.name}', 5000)

    #: Pas de hachure posé par Ctrl+H quand la forme n'en avait aucun.
    HATCH_DEFAULT_MM = 0.05

    def _set_hatched(self) -> None:
        self._switch_fill(True)

    def _set_outline(self) -> None:
        self._switch_fill(False)

    def _switch_fill(self, hatched: bool) -> None:
        """Ctrl+H / Ctrl+F : la sélection passe en plein ou en filaire.

        Le pas retiré est **mémorisé** : repasser en plein rend sa valeur
        d'origine, et non un pas d'usine. Sans cela, un aller-retour
        Ctrl+F puis Ctrl+H remplacerait en silence un hachurage réglé à
        0,02 mm par le pas par défaut — une différence qui ne se voit pas
        à l'écran et se paie sur la pièce.
        """
        shapes = self.canvas.selected_shapes() if self.canvas else []
        if not shapes:
            self.statusBar().showMessage('Sélectionnez une ou plusieurs '
                                         'formes', 3000)
            return
        touchees = 0
        for shape in shapes:
            actuel = shape.recipe.hatch_mm
            if hatched:
                if actuel > 0:
                    continue
                pas = self._hatch_memo.get(shape.id) or self.HATCH_DEFAULT_MM
            else:
                if actuel <= 0:
                    continue
                self._hatch_memo[shape.id] = actuel
                pas = 0.0
            shape.recipe = dataclasses.replace(shape.recipe, hatch_mm=pas)
            touchees += 1
        if not touchees:
            self.statusBar().showMessage(
                'Déjà ' + ('hachurée(s)' if hatched else 'filaire(s)'), 3000)
            return
        # `reload` reconstruit la scène et perd la sélection : sans la
        # remettre, un Ctrl+F suivi d'un Ctrl+H ne trouvait plus rien à
        # remplir, et l'aller-retour restait sans effet.
        garde = [s.id for s in shapes]
        self.canvas.reload()
        self.canvas.select_many(garde)
        self._relabel_list()
        self._selection_changed()
        self._touch()
        self.statusBar().showMessage(
            f'{touchees} forme(s) en ' + ('hachuré' if hatched
                                          else 'filaire'), 4000)

    # -- presse-papiers ----------------------------------------------------
    #
    # Le presse-papiers est **de l'application**, pas du système : les
    # formes s'y rangent sous leur forme sérialisée, la même que celle du
    # fichier. Passer par le presse-papiers de Windows exposerait les
    # documents à tout ce qui traîne dedans, sans rien apporter — personne
    # ne colle une gravure dans un tableur.

    def _copy(self) -> None:
        shapes = self.canvas.selected_shapes() if self.canvas else []
        if not shapes:
            self.statusBar().showMessage('Rien à copier', 2000)
            return
        self._clipboard = [serialize.shape_to_dict(s) for s in shapes]
        self.statusBar().showMessage(
            f'{len(shapes)} forme(s) copiée(s) — Ctrl+V pour coller ici ou '
            f'dans un autre onglet', 5000)

    def _paste(self) -> None:
        """Colle la copie **superposée**, prête à être déplacée.

        Superposée et non décalée : on colle pour comparer, pour recaler à
        la cote, ou pour reprendre une forme d'un autre onglet à sa place
        exacte. Un décalage automatique obligerait à corriger deux
        coordonnées à chaque collage.
        """
        if not getattr(self, '_clipboard', None) or self.canvas is None:
            self.statusBar().showMessage('Le presse-papiers est vide', 2000)
            return
        colles, paires = [], []
        for data in self._clipboard:
            try:
                forme = serialize.shape_from_dict(dict(data), new_id=True)
            except Exception as exc:
                avale('collage : forme illisible', exc)
                continue
            # L'appartenance au groupe d'origine est effacée **avant**
            # l'ajout : conservée, elle faisait que regrouper les formes
            # collées ramassait aussi les originales, qui portaient le même
            # nom de groupe. On collait deux formes, on en regroupait
            # quatre.
            groupe, forme.group = forme.group, ''
            colles.append(self.document.add(forme))
            paires.append((forme, groupe))
        if not colles:
            self.statusBar().showMessage('Collage impossible', 3000)
            return
        # la copie d'un groupe est un groupe neuf, pas un ajout à l'ancien ;
        # une forme copiée seule reste seule — voir
        # `Document.regroup_copies`
        self.document.regroup_copies(paires)
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many([c.id for c in colles])
        self._touch()
        self.statusBar().showMessage(
            f'{len(colles)} forme(s) collée(s) au même endroit — flèches ou '
            f'souris pour les écarter', 6000)

    def _delete(self) -> None:
        ids = self.canvas.selected_ids()
        if not ids:
            return
        for shape_id in ids:
            self.document.remove(shape_id)
        self.canvas.reload()
        self._refresh_list()
        self.inspector.set_shape(None)
        self._touch()

    def _resize_selection(self) -> None:
        shapes = self.canvas.selected_shapes()
        if not shapes:
            self.statusBar().showMessage(
                'F2 : sélectionnez d\'abord une ou plusieurs formes', 3000)
            return
        dialog = resize.ResizeDialog(self, shapes)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.apply()
        ids = [s.id for s in shapes]
        self.canvas.reload()
        self._refresh_list()
        self.canvas.select_many(ids)
        self._touch()

    def _group(self) -> None:
        ids = self.canvas.selected_ids()
        if len(ids) < 2:
            self.statusBar().showMessage(
                'Grouper : sélectionnez au moins deux formes '
                '(Ctrl+clic pour en ajouter)', 4000)
            return
        cle = self.document.group(ids)
        # Grouper ne déplace rien, et la sélection est déjà exactement
        # celle qu'on vient de grouper : ni reconstruction du plan, ni
        # re-sélection. Mais le remplissage peut changer — le groupe est
        # l'unité du pair-impair, voir `toolpath.group_zones` : seules les
        # formes dont il change sont redessinées.
        self.canvas.resync([s.id for s in self.document.shapes
                            if cle and s.group == cle])
        self._relabel_list()
        self.statusBar().showMessage(f'{len(ids)} formes groupées', 3000)
        self._touch()

    def _ungroup(self) -> None:
        ids = self.canvas.selected_ids()
        # les membres d'abord : dégroupés, plus rien ne les désigne
        groupes = {s.group for s in self.document.shapes
                   if s.id in set(ids) and s.group}
        membres = [s.id for s in self.document.shapes if s.group in groupes]
        freed = self.document.ungroup(ids)
        if not freed:
            self.statusBar().showMessage('Aucun groupe dans la sélection', 3000)
            return
        # chacun se remplit de nouveau pour lui seul
        self.canvas.resync(membres)
        self._relabel_list()
        self.statusBar().showMessage(f'{freed} formes dégroupées', 3000)
        self._touch()

    # -- synchronisation ---------------------------------------------------

    def _labels(self) -> list[str]:
        """Étiquettes de la liste : pastille de groupe, nom, outil.

        Le numéro d'outil reste visible en permanence : c'est lui qui part
        dans l'ISO, et c'est la première chose qu'on vérifie avant de
        lancer une plaque.
        """
        marks: dict[str, str] = {}
        for shape in self.document.shapes:
            if shape.group and shape.group not in marks:
                marks[shape.group] = '◆◇◈○●□■△▲'[len(marks) % 9]
        out = []
        for shape in self.document.shapes:
            mark = f'{marks[shape.group]} ' if shape.group else ''
            # Un nom tapé à la main ne suit plus le contenu : il est figé,
            # et c'est voulu. Encore faut-il le voir — sinon on lit une
            # référence périmée en croyant lire la bonne.
            fige = ' ✎' if shape.renamed() else ''
            out.append(f'{mark}{shape.display_name()}{fige}  ·  '
                       f'T{shape.recipe.tool_number}')
        return out

    def _refresh_list(self) -> None:
        self.shape_list.blockSignals(True)
        self.shape_list.clear()
        self._rows: dict[str, ShapeRow] = {}
        for shape, label in zip(self.document.shapes, self._labels()):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, shape.id)
            item.setToolTip(shape.recipe.label())
            row = ShapeRow(shape, label)
            row.toggled.connect(self._toggle_visible)
            row.duplicated.connect(self._duplicate_one)
            row.removed.connect(self._remove_one)
            item.setSizeHint(row.sizeHint())
            self.shape_list.addItem(item)
            self.shape_list.setItemWidget(item, row)
            self._rows[shape.id] = row
        self.shape_list.blockSignals(False)

    def _relabel_list(self) -> None:
        """Réécrit les étiquettes sans toucher aux entrées ni à la sélection.

        Vider puis reconstruire la liste efface la sélection, ce qui
        déclenche un rafraîchissement de l'inspecteur et un recalcul des
        trajectoires — tout cela pour un changement d'étiquette.
        """
        labels = self._labels()
        if self.shape_list.count() != len(labels):
            self._refresh_list()
            return
        for i, (shape, label) in enumerate(zip(self.document.shapes, labels)):
            item = self.shape_list.item(i)
            item.setToolTip(shape.recipe.label())
            row = self._rows.get(shape.id)
            if row is not None:
                row.set_label(label)
                row.set_visible_state(shape.visible)

    # -- actions de ligne --------------------------------------------------

    def _toggle_visible(self, shape_id: str) -> None:
        """Masque ou réaffiche une forme, et tout son groupe avec elle.

        Un groupe qui se graverait à moitié n'aurait pas de sens : le
        symbole partirait sans son texte lisible.
        """
        shape = self.document.get(shape_id)
        if shape is None:
            return
        etat = not shape.visible
        for membre in self.document.group_members(shape_id):
            membre.visible = etat
        self.canvas.reload()
        self._relabel_list()
        self._touch()
        caches = sum(1 for s in self.document.shapes if not s.visible)
        self.statusBar().showMessage(
            f'{shape.display_name()} : {"masquée" if not etat else "affichée"}'
            + (f' · {caches} forme(s) masquée(s) dans ce document'
               if caches else ''), 5000)

    def _duplicate_one(self, shape_id: str) -> None:
        self.canvas.select(shape_id)
        self._duplicate()

    def _remove_one(self, shape_id: str) -> None:
        self.canvas.select(shape_id)
        self._delete()

    def _list_selected(self) -> None:
        """Sélectionne sur le plan de travail et **ouvre les propriétés**.

        Cliquer une forme dans la liste sans voir ses réglages n'a pas
        d'intérêt : le panneau des propriétés peut être masqué derrière
        un autre, on le met au premier plan.
        """
        items = self.shape_list.selectedItems()
        ids = [i.data(Qt.UserRole) for i in items]
        if not ids:
            return
        # la première désignée commande l'inspecteur, même si un groupe
        # entraîne les autres avec elle
        self.canvas._primary = ids[0]
        self.canvas.select_many(self.document.expand_selection(ids))
        # `select_many` se tait quand l'ensemble ne change pas : recliquer
        # la ligne d'un groupe qu'on avait ouvert doit tout de même
        # ramener le formulaire du lot.
        self._selection_changed()
        self._show_properties()

    def _show_properties(self) -> None:
        # `self._dock_insp` plutôt que `self._docks[3]` : retirer un dock
        # de la liste décalait l'index en silence, et l'on ouvrait le
        # mauvais panneau.
        dock = self._dock_insp
        if not dock.isVisible():
            dock.show()
        dock.raise_()

    def _selection_changed(self) -> None:
        sid = self.canvas.primary_id() if self.canvas else None
        shape = self.document.get(sid) if sid else None
        lot = self.canvas.selected_shapes() if self.canvas else []
        # Le montage passe avant le lot : selectionner ses six formes,
        # c'est venir saisir trois references, pas mesurer un ensemble.
        # Le bouton « Voir le lot » reste la pour qui veut le mesurer.
        if montage.is_montage(lot):
            self.montage_form.set_montage(lot, self.document)
            self._insp_stack.setCurrentIndex(2)
            self.recipe.set_shape(shape, lot)
            self._status_timer.start()
            return
        if len(lot) > 1 and not (shape is not None
                                 and codeplate.is_plate(lot)):
            # Le lot passe devant : mesurer un ensemble et lui poser une
            # process commune est ce qu'on vient y chercher. La process de
            # la forme principale reste éditable en colonne 1.
            self.lot.set_recipes(self._known_recipes())
            self.lot.set_lot(lot, self.document, shape)
            self._insp_stack.setCurrentIndex(1)
        else:
            # **Une plaque codée fait exception.** Le symbole et son texte
            # forment un groupe, mais on ne les règle jamais ensemble : on
            # tape la donnée sur l'un, la police sur l'autre. Le
            # formulaire suit donc l'entité désignée, et le bouton « Voir
            # le lot » rend l'ensemble à qui veut le mesurer.
            self.inspector.set_shape(shape, len(lot))
            self._insp_stack.setCurrentIndex(0)
        self.recipe.set_shape(shape, lot)
        # même temporisation que les déplacements : un clic sur le plan de
        # travail ne doit pas attendre le recalcul de la barre d'état
        self._status_timer.start()

    def _show_lot(self) -> None:
        """Ramène le formulaire du lot, sans toucher à la sélection.

        Réciproque de « Voir la forme cliquée » : une plaque codée ouvre
        l'entité désignée, et l'on doit pouvoir revenir à l'ensemble pour
        le centrer, le coter ou lui poser une process commune.
        """
        lot = self.canvas.selected_shapes() if self.canvas else []
        if len(lot) < 2:
            return
        sid = self.canvas.primary_id()
        self.lot.set_recipes(self._known_recipes())
        self.lot.set_lot(lot, self.document,
                         self.document.get(sid) if sid else None)
        self._insp_stack.setCurrentIndex(1)

    def _show_primary(self) -> None:
        """Montre les propriétés de la forme cliquée, lot ou pas.

        La sélection n'est pas touchée : on revient au lot en recliquant
        sa ligne dans la liste.
        """
        sid = self.canvas.primary_id() if self.canvas else None
        shape = self.document.get(sid) if sid else None
        if shape is None:
            return
        self.inspector.set_shape(shape)
        self._insp_stack.setCurrentIndex(0)
        self.statusBar().showMessage(
            f'{shape.display_name()} — recliquez la ligne pour revenir '
            f'au lot', 6000)

    def _known_recipes(self) -> list:
        """Process proposées au lot : la bibliothèque, puis celles du plan.

        Une process réglée sur une forme sans avoir été rangée en
        bibliothèque doit rester applicable au reste du lot : c'est le
        geste normal — on met une forme au point, puis on l'étend.
        """
        connues = list(recipes.load_local())
        vues = {(r.name, r.tool_number) for r in connues}
        for forme in self.document.shapes:
            clef = (forme.recipe.name, forme.recipe.tool_number)
            if clef not in vues:
                vues.add(clef)
                connues.append(forme.recipe)
        return connues

    def _lot_edited(self) -> None:
        """Le lot a changé : redessiner, sans perdre la sélection.

        Recharger le plan de travail vide la sélection, ce qui refermerait
        le panneau du lot à chaque tour de molette. Elle est donc rétablie
        telle quelle, et le panneau n'est pas reconstruit — les champs
        qu'on manipule doivent garder le focus.
        """
        ids = self.canvas.selected_ids()
        self.canvas.reload()
        self._relabel_list()
        self.canvas.select_many(ids)
        self._touch()

    def _shape_edited(self, shape_id: str) -> None:
        # propager d'abord, redessiner ensuite et en une fois : le
        # remplissage d'un groupe dépend de tous ses membres
        self.canvas.refresh_many([shape_id]
                                 + self._propagate_data(shape_id)
                                 + self._propagate_recipe(shape_id))
        self._relabel_list()
        self._remember_plate()
        forme = self.document.get(shape_id)
        if forme is not None:
            self._remember_recipe(forme.recipe)
        self._touch()

    def _shapes_edited(self, shape_ids: list) -> None:          # noqa: D401
        """Un lot a reçu la même process : redessiner chacune, une fois.

        Passer par `_shape_edited` forme par forme relabelliserait la
        liste et daterait le document autant de fois qu'il y a de
        formes — sur un lot de trois cents, c'est ce qui rend le panneau
        poisseux.
        """
        self.canvas.refresh_many(shape_ids)
        self._relabel_list()
        if shape_ids:
            forme = self.document.get(shape_ids[0])
            if forme is not None:
                self._remember_recipe(forme.recipe)
        self._touch()

    def _propagate_data(self, shape_id: str) -> list:
        """Met à jour les textes qui reproduisent la donnée d'un code.

        Un texte lisible qui contredirait son symbole est pire que pas de
        texte du tout : la pièce partirait avec deux numéros différents,
        l'un lisible à l'œil, l'autre au lecteur.

        Rend les formes touchées, que l'appelant redessine.
        """
        code = self.document.get(shape_id)
        if not isinstance(code, Code):
            return []
        return [shape.id
                for shape in codeplate.propagate_data(self.document, code)]

    def _propagate_recipe(self, shape_id: str) -> list:
        """Étend la recette éditée aux autres membres du groupe.

        Un groupe se grave d'un bloc : lui laisser deux recettes obligerait
        à sélectionner ses membres un par un pour corriger la puissance,
        ce qui est précisément ce que le groupe évite. Les géométries
        restent propres à chaque membre.

        **Sauf si le groupe porte délibérément plusieurs recettes.** Un
        coupon d'essai est exactement cela : vingt-cinq cases groupées pour
        se déplacer d'un bloc, mais dont chacune a sa process — c'est tout
        son objet. Y propager la première recette éditée effacerait l'essai
        en un clic.

        La règle se lit sur l'état du groupe, sans rien mémoriser : on
        propage tant que **les autres membres partagent une seule et même
        recette**. Une plaque codée — symbole et texte, même recette —
        continue donc de se régler d'un geste ; un coupon garde ses cases.

        Rend les formes touchées, que l'appelant redessine en une fois :
        une à une, chaque état intermédiaire du groupe se recalculait.
        """
        edited = self.document.get(shape_id)
        if edited is None or not edited.group:
            return []
        autres = [s for s in self.document.group_members(shape_id)
                  if s.id != shape_id]
        if len({s.recipe for s in autres}) > 1:
            return []
        touchees = []
        for shape in autres:
            if shape.recipe != edited.recipe:
                shape.recipe = edited.recipe
                touchees.append(shape.id)
        return touchees

    def _document_signature(self) -> tuple:
        """Empreinte de ce qui influe sur les trajectoires.

        Permet de ne pas refaire le calcul quand rien n'a bougé — un simple
        changement de sélection déclenche aussi un rafraîchissement.
        """
        # un seul contexte de champs variables pour tout le document : le
        # construire par forme coûtait plus cher que l'empreinte elle-même
        context = variables.make_context()
        return (self.optimize, self.group_recipes, self.document.copies,
                self.document.serial_start, self.document.serial_step,
                # le groupe et la visibilité changent les remplissages :
                # un groupe alterne le pair-impair entre ses membres
                tuple((geometry_key(s, context), round(s.x, 6),
                       round(s.y, 6), s.recipe, s.group, s.visible)
                      for s in self.document.shapes))

    def _current_passes(self, *, time_budget_s: float = 0.0):
        """Passes courantes, mémorisées tant que le document ne change pas.

        Le 2-opt n'est pas appliqué ici : le plus proche voisin capte
        l'essentiel du gain, et l'export s'accorde ensuite une seconde
        entière pour affiner.
        """
        tab = self.canvas
        if tab is None:
            return []
        signature = self._document_signature()
        if tab.passes_cache is not None and tab.passes_cache[0] == signature:
            return tab.passes_cache[1]
        passes = build_passes(self.document, optimize=self.optimize,
                              group_by_recipe=self.group_recipes,
                              time_budget_s=time_budget_s)
        tab.passes_cache = (signature, passes, None)
        return passes

    def _current_metrics(self) -> tuple[float, float, float]:
        """Longueur gravée, trajet à vide et durée, mémorisés.

        Ces trois mesures parcourent toutes les trajectoires — sur un
        document de 300 plaques hachurées, quatre cents millisecondes à
        chaque fois. Elles ne dépendent que des passes : les mémoriser
        avec elles rend gratuit tout rafraîchissement qui ne change rien,
        et un simple changement de sélection en déclenche un.
        """
        passes = self._current_passes()
        tab = self.canvas
        if tab is not None and tab.passes_cache is not None:
            cached = tab.passes_cache[2]
            if cached is not None:
                return cached
        metrics = (total_length_mm(passes), total_travel_mm(passes),
                   total_duration_s(passes))
        if tab is not None and tab.passes_cache is not None:
            tab.passes_cache = (tab.passes_cache[0], passes, metrics)
        return metrics

    def _status_due(self) -> None:
        """Le résumé est dû : il attend qu'un message en cours ait fini —
        voir `NoteBar`. Appelé directement, `_update_status` écrit tout de
        suite."""
        bar = self.statusBar()
        reste = bar.note_ms() if isinstance(bar, NoteBar) else 0
        if reste:
            QTimer.singleShot(reste + 20, self._status_due)
            return
        self._update_status()

    def _update_status(self) -> None:
        # Les lectures sans compte rendu — bibliothèque de process, collage,
        # dessin inséré, import de réglages — notent leurs remplacements à
        # part : on les dit ici, au premier résumé qui suit.
        non_dits = unreported_repairs()
        if non_dits:
            self._alert_repairs('Valeurs illisibles', non_dits)
        if self.canvas is None:
            return
        passes = self._current_passes()
        length, travel, duration = self._current_metrics()
        out = self.document.out_of_field()

        # Les allumages, à côté de la durée : sur cette machine c'est eux
        # qui la font, bien plus que la longueur gravée — voir
        # `Recipe.link_paths`. Les voir baisser quand on coche
        # « Enchaîner les tracés » dit tout de suite ce que la case vaut.
        # une liste de tracés partagée par plusieurs passes se compte une
        # fois — voir `toolpath._PARTAGEES`
        comptes: dict[int, int] = {}
        allumages = 0
        for p in passes:
            n = comptes.get(id(p.polylines))
            if n is None:
                n = comptes[id(p.polylines)] = sum(
                    1 for poly in p.polylines if len(poly) > 1)
            allumages += n
        msg = (f'{len(self.document.shapes)} forme(s) · {len(passes)} passe(s) · '
               f'gravé {length:.1f} mm · à vide {travel:.1f} mm · '
               f'{allumages} allumage(s) · '
               f'~{duration:.1f} s · pas {self.canvas.nudge_step:g} mm')
        selected = len(self.canvas.selected_ids())
        if selected > 1:
            msg += f' · {selected} formes sélectionnées'
        caches = sum(1 for s in self.document.shapes if not s.visible)
        if caches:
            msg += f' · {caches} masquée(s), non gravée(s)'
        if out:
            msg += '   ⚠ TRAJECTOIRE HORS CHAMP'
            # portée à la barre elle-même : sans le sélecteur, la règle
            # descend sur l'emplacement d'aide et le passe en gras rouge
            self.statusBar().setStyleSheet(
                f'QStatusBar {{ color:{theme.ALARM}; font-weight:bold; }}')
        else:
            self.statusBar().setStyleSheet('')
        self.statusBar().showMessage(msg)

    # -- export ------------------------------------------------------------

    def _name_export(self, base: pathlib.Path, wanted: str) -> str | None:
        """Nom du dossier d'export, selon le réglage de nommage.

        Un même travail s'exporte souvent plusieurs fois — une correction,
        un essai, une seconde matière — et le modèle de chemin donne
        chaque fois le même nom. Sans distinction, le second export
        écrasait le premier, y compris des fichiers déjà copiés sur la
        machine. Rend `None` si l'opérateur renonce.
        """
        libre = not (base / wanted).exists()
        mode = session.export_naming()
        if libre or mode == 'overwrite':
            return wanted
        if mode == 'auto':
            return iso.unique_folder(base, wanted)

        from PySide6.QtWidgets import QInputDialog
        propose = iso.unique_folder(base, wanted)
        nom, ok = QInputDialog.getText(
            self, 'Nom de l\'export',
            f'« {wanted} » existe déjà dans :\n{base}\n\n'
            'Nom du dossier de cet export :', text=propose)
        nom = iso.sanitize(nom.strip()) if nom.strip() else ''
        if not ok or not nom:
            return None
        return nom

    def _refresh_export_dirs(self) -> None:
        current = self.w_export_dir.currentText()
        self.w_export_dir.blockSignals(True)
        self.w_export_dir.clear()
        # le dossier par défaut vient en tête, même s'il n'a jamais servi
        for folder in session.recent_folders('export'):
            self.w_export_dir.addItem(folder)
        if current:
            self.w_export_dir.setCurrentText(current)
        self.w_export_dir.blockSignals(False)

    def _use_export_dir(self, folder: str) -> None:
        self.w_export_dir.setCurrentText(folder)
        session.remember_export(folder)
        self._refresh_export_dirs()

    def _pick_export_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, 'Dossier d\'export', self.w_export_dir.currentText()
            or session.last_export())
        if folder:
            self._use_export_dir(folder)

    def _confirm_export_dir(self, base: str) -> bool:
        """Vrai si l'on peut exporter là. Sinon, propose de réessayer.

        Deux corrections tiennent dans cette méthode, et toutes deux
        venaient du même endroit :

        * un dossier qui n'existe **pas encore** était refusé, alors que
          l'export le crée — c'est `writable` qui répond à la bonne
          question, et non `reachable` ;
        * le refus était **définitif pour la session** : le partage
          revenu, le message revenait quand même, jusqu'à ce qu'on
          relance le programme. *Réessayer* refait la sonde pour de bon
          (`fresh`), après avoir oublié ce qui avait été constaté.
        """
        if not base:
            self._pick_export_dir()
            return bool(self.w_export_dir.currentText().strip())
        if session.writable(base):
            return True
        while True:
            boite = QMessageBox(self)
            boite.setIcon(QMessageBox.Warning)
            boite.setWindowTitle('Export')
            boite.setText(f'Le dossier d\'export ne répond pas :\n{base}')
            boite.setInformativeText(
                'Partage hors ligne, ou poste débranché du réseau. Le '
                'chemin reste mémorisé.\n\n'
                'S\'il est revenu depuis, « Réessayer » le reteste.')
            reessayer = boite.addButton('Réessayer',
                                        QMessageBox.AcceptRole)
            autre = boite.addButton('Choisir un autre dossier…',
                                    QMessageBox.ActionRole)
            boite.addButton(QMessageBox.Cancel)
            boite.setDefaultButton(reessayer)
            boite.exec()
            clique = boite.clickedButton()
            if clique is reessayer:
                session.forget_reachability()
                if session.writable(base, fresh=True):
                    self._flash_status(f'{base} répond de nouveau', True, 3.0)
                    return True
                continue
            if clique is autre:
                self._pick_export_dir()
                base = self.w_export_dir.currentText().strip()
                if base and session.writable(base, fresh=True):
                    return True
                if not base:
                    return False
                continue
            return False

    def _export(self) -> None:
        if not self.document.shapes:
            QMessageBox.information(self, 'Export', 'Le document est vide.')
            return
        # Le dépassement de champ est signalé ici quand la vérification
        # complète est coupée ; sinon c'est elle qui le porte, avec le
        # reste, plutôt que de poser deux questions à la suite. Dans les
        # deux cas, la réponse utile n'est pas « quand même » : c'est la
        # découpe en morceaux.
        if not session.preflight() and self.document.out_of_field():
            boite = QMessageBox(self)
            boite.setIcon(QMessageBox.Warning)
            boite.setWindowTitle('Hors champ')
            boite.setText(
                'Une trajectoire sort du champ de marquage '
                f'({self.document.field_w:g} × {self.document.field_h:g} '
                'mm).')
            boite.setInformativeText(
                'La machine ne peut pas l\'atteindre. Le dessin peut être '
                'gravé en plusieurs morceaux, la pièce déplacée entre '
                'deux.')
            decouper = boite.addButton('Découper en morceaux…',
                                       QMessageBox.AcceptRole)
            forcer = boite.addButton('Exporter quand même',
                                     QMessageBox.DestructiveRole)
            boite.addButton(QMessageBox.Cancel)
            boite.setDefaultButton(decouper)
            boite.exec()
            if boite.clickedButton() is decouper:
                self._export_morceaux()
                return
            if boite.clickedButton() is not forcer:
                return

        destination = self._export_destination()
        if destination is None:
            return
        base, folder, machine_dir, job_name = destination

        # Dernier moment où une erreur ne coûte encore rien : le
        # récapitulatif porte la destination réellement retenue, y compris
        # la numérotation qui vient d'être décidée.
        if session.preflight():
            # quelques secondes sur un texte oscillé, autant que les
            # essais qui chiffrent les conseils : sans sablier, la fenêtre
            # semblait figée, et Windows finissait par la dire « ne
            # répond pas »
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                report = preflight.inspect(
                    self.document, destination=str(folder),
                    destination_root=base,
                    machine_path=iso.machine_path(folder, machine_dir),
                    optimize=self.optimize,
                    group_by_recipe=self.group_recipes)
            finally:
                QApplication.restoreOverrideCursor()
            dialog = preflight.PreflightDialog(self, report)
            accepte = dialog.exec() == QDialog.DialogCode.Accepted
            if dialog.skip_next_time():
                session.set_preflight(False)
                self.w_preflight.blockSignals(True)
                self.w_preflight.setChecked(False)
                self.w_preflight.blockSignals(False)
            if not accepte:
                return

        erreur = None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            files = iso.export(self.document, str(folder),
                               machine_iso_dir=machine_dir,
                               optimize=self.optimize,
                               group_by_recipe=self.group_recipes)
        except Exception as exc:
            erreur = exc
        finally:
            QApplication.restoreOverrideCursor()
        if erreur is not None:
            self._flash_status(f'Export échoué : {erreur}', False)
            QMessageBox.critical(self, 'Export', f'Échec : {erreur}')
            return
        session.remember_export(base)
        self._refresh_export_dirs()

        # Journal : ce qui a été exporté, quand, et ce qui a changé depuis
        # la fois précédente. Un travail est rarement exporté une seule
        # fois, et trois plaques plus tard personne ne sait plus laquelle a
        # été gravée avec quoi.
        etat = journal.snapshot(self.document, optimize=self.optimize,
                                group_by_recipe=self.group_recipes)
        tab = self.canvas
        rang = getattr(tab, 'export_count', 0) + 1
        tab.export_count = rang
        ecarts = journal.differences(getattr(tab, 'export_state', None) or {},
                                     etat)
        tab.export_state = etat
        carnet = journal.append(base, self.document.name,
                                journal.render(etat, ecarts, rang=rang,
                                               dossier=job_name,
                                               fichiers=len(files)))
        seen = iso.machine_path(folder, machine_dir)
        # Pas de fenêtre à refermer : un export réussi n'a rien à
        # annoncer qui vaille un clic. Le compte rendu va dans la barre
        # d'état, et le détail dans son infobulle pour qui veut vérifier
        # le chemin vu par la machine.
        self._flash_status(
            f'Exporté : {len(files)} fichier(s) → {folder}', True)
        self.statusBar().setToolTip(
            f'{len(files)} fichier(s) écrit(s) dans :\n{folder}\n\n'
            f'Le CLJOB désigne les .ISO à cet emplacement :\n{seen}\n\n'
            'Ouvrez le CLJOB depuis ClTerm.\n'
            'Le modèle de ce chemin se règle dans '
            'Paramètres ▸ Dossiers par défaut.')

    def _export_destination(self):
        """Dossier d'export, dossier du travail, chemin machine et nom —
        ou `None` si l'opérateur renonce. Commun aux deux exports."""
        base = (self.w_export_dir.currentText().strip()
                or session.default_folder('export') or session.last_export())
        if not self._confirm_export_dir(base):
            return None
        base = self.w_export_dir.currentText().strip() or base

        # un dossier par travail : les fichiers d'un lot ne se mélangent pas
        # à ceux du précédent, et on sait toujours ce qu'on a envoyé
        # Le dossier d'export et le chemin machine viennent du **même
        # modèle** : le CLJOB désigne donc toujours le dossier où les
        # fichiers viennent d'être écrits, vu depuis la machine.
        template = session.machine_template()
        job_name = iso.job_folder_name(self.document, template=template)
        job_name = self._name_export(pathlib.Path(base), job_name)
        if job_name is None:
            return None
        # Le chemin machine reprend le nom réellement retenu : les deux ne
        # peuvent pas diverger, même après une numérotation automatique.
        machine_dir = iso.replace_tail(
            iso.render_template(template, self.document), job_name)
        folder = pathlib.Path(base) / job_name
        return base, folder, machine_dir, job_name

    def _export_morceaux(self) -> None:
        """Un dessin plus grand que le champ : un job par morceau.

        Le dialogue montre la grille, laisse régler la marge, et écrit
        les consignes de déplacement de la pièce dans le dossier
        d'export. Il ne passe pas par la vérification ordinaire : elle
        déclarerait le travail hors champ, ce qui est précisément ce
        qu'on est en train de traiter.
        """
        if not self.document.shapes:
            QMessageBox.information(self, 'Export', 'Le document est vide.')
            return
        from . import morceaux
        stem = iso.sanitize(self.document.name)
        dialog = morceaux.dialogue(self, self.document, stem)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        plan = dialog.plan()
        if not plan:
            return
        destination = self._export_destination()
        if destination is None:
            return
        base, folder, machine_dir, job_name = destination
        try:
            folder.mkdir(parents=True, exist_ok=True)
            files = iso.export_morceaux(
                self.document, str(folder), plan, marge_mm=dialog.marge(),
                marques=dialog.marques(), machine_iso_dir=machine_dir,
                optimize=self.optimize, group_by_recipe=self.group_recipes)
        except Exception as exc:
            self._flash_status(f'Export échoué : {exc}', False)
            QMessageBox.critical(self, 'Exporter en morceaux',
                                 f'Échec : {exc}')
            return
        session.remember_export(base)
        self._refresh_export_dirs()
        etat = journal.snapshot(self.document, optimize=self.optimize,
                                group_by_recipe=self.group_recipes)
        tab = self.canvas
        rang = getattr(tab, 'export_count', 0) + 1
        tab.export_count = rang
        ecarts = journal.differences(getattr(tab, 'export_state', None) or {},
                                     etat)
        tab.export_state = etat
        journal.append(base, self.document.name,
                       journal.render(etat, ecarts, rang=rang,
                                      dossier=job_name, fichiers=len(files))
                       + f'  en {len(plan)} morceaux\n')
        n = len(plan)
        self._flash_status(
            f'Exporté en {n} morceau{"x" if n > 1 else ""} : {len(files)} '
            f'fichier(s) → {folder}', True, 6.0)
        QMessageBox.information(
            self, 'Exporter en morceaux',
            f'{n} job{"s" if n > 1 else ""} écrit{"s" if n > 1 else ""} '
            f'dans\n{folder}\n\nLes consignes de déplacement de la pièce '
            f'sont dans {iso.CONSIGNES}, à la racine de ce dossier. '
            'Imprimez-les ou ouvrez-les à côté de ClTerm : chaque morceau '
            'dit de combien pousser la pièce avant de le lancer.')

    def closeEvent(self, event) -> None:
        # Rendre le plan de travail **avant** d'enregistrer la
        # disposition : fermée gestionnaire ouvert, la fenêtre se
        # rouvrait sans propriétés, un panneau de réserve à leur place.
        if not self._leave_montages():
            event.ignore()
            return
        if self.center.currentIndex() == 2:
            self._leave_library()
        elif self.center.currentIndex() == 1:
            self._leave_recipes()
        self._save_session()
        session.save_window(self)
        self.laser.closeEvent(event)
        super().closeEvent(event)


def install_french(app: QApplication) -> bool:
    """Traduit les libellés que Qt fournit lui-même.

    Sans cela, l'application est en français mais ses boutons standards
    répondent « OK » et « Cancel », et les menus contextuels de saisie
    parlent anglais. La traduction est livrée avec Qt ; son absence n'est
    pas une raison de ne pas démarrer.
    """
    translator = QTranslator(app)
    # Le second chemin sert à la version figée : PyInstaller range les
    # traductions à côté de PySide6, où `QLibraryInfo` ne regarde pas
    # toujours.
    candidats = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
                 str(pathlib.Path(getattr(sys, '_MEIPASS', '.'))
                     / 'PySide6' / 'translations')]
    if not any(translator.load('qtbase_fr', c) for c in candidats):
        return False
    # la référence est retenue sur l'application : un traducteur ramassé
    # par le collecteur cesse d'agir sans rien signaler
    app._fr = translator
    return app.installTranslator(translator)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    install_french(app)
    theme.apply(app, settings().value('theme', theme.DEFAULT))
    # Les plugins d'abord : ce sont eux qui apportent les données de
    # l'atelier — semence, process d'usine, magasin, dessins. Un plugin en
    # erreur n'empêche pas le démarrage (*À propos* le dit).
    plugins.load()
    # Ce que la distribution apporte à un poste neuf, **avant** de charger
    # la bibliothèque : process de l'atelier, gabarits, modèles de
    # traitement. Rien n'est jamais écrasé — voir `semence`.
    from . import semence
    semence.semer()
    recipes.install_local()
    icon = app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
