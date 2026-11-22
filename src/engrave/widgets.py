"""Champs de saisie / Input fields.

Un poste de gravure se règle au clavier, pas à la souris. Les compteurs
de Qt vont dans l'autre sens : ils poussent aux flèches, collent l'unité
au chiffre, imposent un nombre de décimales fixe et changent de valeur
au moindre coup de molette.

Les champs d'ici corrigent l'ensemble :

* **aucune flèche.** La souris ne modifie plus rien, molette comprise. On
  tape la valeur, on la corrige aux flèches du clavier. Une cote changée
  par mégarde ne se voit pas : elle part à la gravure ;
* **l'unité est en dehors du champ**, en gris à sa droite. Elle ne se
  sélectionne pas, ne s'efface pas, ne gêne pas la saisie ;
* **le nombre de décimales s'ajuste à la valeur.** `15` s'affiche `15`,
  `0,004673` s'affiche `0,004673`. Un affichage à trois décimales fixes
  montrait `0,005` pour une profondeur de passe — la valeur juste, mais
  fausse à l'œil ;
* **double-clic ou prise de focus sélectionne tout** : ce qu'on tape
  remplace la valeur entière ;
* **la virgule du pavé numérique vaut le point.**
"""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QAbstractSpinBox, QComboBox, QDoubleSpinBox,
                               QHBoxLayout, QLabel, QPlainTextEdit,
                               QSizePolicy, QSpinBox, QWidget)

from . import theme

#: Décimales gardées en interne. L'affichage n'en montre que ce qu'il
#: faut, mais la valeur, elle, ne doit rien perdre : un pas de passe de
#: 4,673 µm s'écrit 0,004673 mm.
PRECISION = 6
SHOWN = 3

#: Décimales **montrées** par défaut.
#:
#: Trois suffisent : le micron est déjà trente fois plus fin que le spot
#: de la machine. Une cote posée à la souris sortait « -26,111537 mm »,
#: six décimales de bruit qui chassent du champ le chiffre qu'on lit.
#:
#: Un champ peut en demander plus — le pas de profondeur en réclame six,
#: et l'arrondir à 0,005 mm serait un contresens. La **valeur**, elle,
#: garde toujours sa précision entière : seul l'affichage est abrégé.


class _NoWheelMixin:
    """Ni molette, ni flèches : la souris ne change aucune valeur."""

    def _wire(self) -> None:
        self.setKeyboardTracking(False)   # ne pas appliquer les états partiels
        self.setFocusPolicy(Qt.StrongFocus)
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        # ce que valait le champ en y entrant : c'est ce qu'Échap rend
        self._a_l_entree = self.value()
        # différé : Qt repositionne le curseur après cet événement
        QTimer.singleShot(0, self.selectAll)

    def mouseDoubleClickEvent(self, event) -> None:
        self.selectAll()
        event.accept()

    def wheelEvent(self, event) -> None:
        event.ignore()

    def keyPressEvent(self, event) -> None:
        """Entrée valide et le dit ; Échap rend la valeur d'entrée.

        Un champ qu'on atteint au clavier doit se quitter au clavier :
        Entrée applique **et** prévient (`validated`), pour que l'appelant
        rende le focus là d'où l'on venait — le plan de travail, la forme
        qu'on réglait. Échap n'est pris que s'il y a quelque chose à
        défaire : sinon il remonte, et ferme le dialogue comme d'habitude.
        """
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            super().keyPressEvent(event)        # interprète le texte tapé
            self.interpretText()
            self.validated.emit()
            event.accept()
            return
        if key == Qt.Key_Escape and self.text() != self.textFromValue(
                getattr(self, '_a_l_entree', self.value())):
            self.setValue(getattr(self, '_a_l_entree', self.value()))
            self.selectAll()
            self.escaped.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _Decimal(_NoWheelMixin, QDoubleSpinBox):
    """Compteur décimal nu, sans unité ni flèches.

    Montre au plus `shown` décimales, zéros de queue retirés, tout en
    gardant la valeur entière : « 5 » plutôt que « 5,000000 », et
    « -26,112 » plutôt que « -26,111537 ».
    """

    validated = Signal()
    escaped = Signal()

    #: Décimales montrées. Réglé par `Spin`, champ par champ.
    shown = SHOWN

    def textFromValue(self, value: float) -> str:
        """Autant de décimales que la valeur en demande, pas une de plus.

        Bornées à `shown`, et non aux décimales internes : celles-ci vont
        jusqu'à six pour ne rien perdre de la valeur, mais une cote posée
        à la souris sortait alors « -26,111537 mm » — six décimales de
        bruit qui chassent du champ le chiffre qu'on lit.
        """
        separator = self.locale().decimalPoint()
        text = f'{value:.{max(0, min(int(self.shown), self.decimals()))}f}'
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        if text in ('', '-', '-0'):
            text = '0'
        return text.replace('.', separator)

    def valueFromText(self, text: str) -> float:
        return super().valueFromText(self._normalise(text))

    def validate(self, text: str, position: int):
        return super().validate(self._normalise(text), position)

    def _normalise(self, text: str) -> str:
        separator = self.locale().decimalPoint()
        return text.replace(',', separator).replace('.', separator)


class _Integer(_NoWheelMixin, QSpinBox):
    """Compteur entier nu."""

    validated = Signal()
    escaped = Signal()


class _Field(QWidget):
    """Compteur et son unité, côte à côte.

    L'unité est un libellé distinct : elle reste lisible sans faire partie
    du texte saisi. Le composant expose l'interface d'un compteur, si bien
    que le reste de l'application ne voit pas la différence.
    """

    valueChanged = Signal(float)
    #: Entrée dans le champ : la valeur est appliquée, on peut rendre
    #: le focus. Échap : la valeur d'entrée est rétablie, même chose.
    validated = Signal()
    escaped = Signal()

    def __init__(self, spin, unit: str = '', parent=None) -> None:
        super().__init__(parent)
        self._spin = spin
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        row.addWidget(spin, 1)
        # Le parent est donné à la construction, et non laissé à
        # `addWidget`. Une étiquette sans parent qu'on rend visible devient
        # une **fenêtre** : Qt lui crée un vrai window handle, Windows
        # refuse ses 34 px de large et journalise
        # « QWindowsWindow::setGeometry: Unable to set geometry 34x16 ».
        # Des dizaines de fenêtres de 120×16 étaient ainsi créées et
        # détruites à chaque ouverture de panneau.
        self._unit = QLabel(unit, self)
        self._unit.setStyleSheet(theme.css())
        self._unit.setVisible(bool(unit))
        self._unit.setMinimumWidth(34 if unit else 0)
        self._unit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        row.addWidget(self._unit)
        spin.valueChanged.connect(self.valueChanged.emit)
        spin.validated.connect(self.validated.emit)
        spin.escaped.connect(self.escaped.emit)
        self.setFocusProxy(spin)

    # -- interface d'un compteur ------------------------------------------

    def value(self):
        return self._spin.value()

    def setValue(self, value) -> None:
        self._spin.setValue(value)

    def setRange(self, lo, hi) -> None:
        self._spin.setRange(lo, hi)

    def setDecimals(self, n: int) -> None:
        if hasattr(self._spin, 'setDecimals'):
            self._spin.setDecimals(n)

    def setSingleStep(self, step) -> None:
        self._spin.setSingleStep(step)

    def setReadOnly(self, on: bool) -> None:
        self._spin.setReadOnly(on)

    def setButtonSymbols(self, *_ ) -> None:
        """Sans effet : ces champs n'ont jamais de flèches."""

    # -- valeur absente ----------------------------------------------------
    #
    # Un champ qui vaut son minimum peut porter un texte à la place du
    # nombre. C'est ainsi qu'un formulaire de lot montre « — » sur une
    # cote que les formes ne partagent pas, au lieu d'afficher celle de la
    # première et de la répandre au premier tour de molette.

    def setSpecialValueText(self, text: str) -> None:
        self._spin.setSpecialValueText(text)

    def specialValueText(self) -> str:
        return self._spin.specialValueText()

    def minimum(self):
        return self._spin.minimum()

    def maximum(self):
        return self._spin.maximum()

    def setUnit(self, unit: str) -> None:
        self._unit.setText(unit)
        self._unit.setVisible(bool(unit))

    def setToolTip(self, text: str) -> None:
        super().setToolTip(text)
        self._spin.setToolTip(text)

    def setEnabled(self, on: bool) -> None:
        super().setEnabled(on)
        self._spin.setEnabled(on)

    def blockSignals(self, on: bool) -> bool:
        self._spin.blockSignals(on)
        return super().blockSignals(on)

    def selectAll(self) -> None:
        self._spin.selectAll()

    @property
    def spin(self):
        """Le compteur nu, pour les cas qui ont besoin du widget réel."""
        return self._spin


class Spin(_Field):
    """Champ décimal : unité à l'extérieur, décimales dynamiques."""

    def __init__(self, value: float = 0.0, lo: float = -1e9, hi: float = 1e9,
                 step: float = 1.0, decimals: int = PRECISION,
                 suffix: str = '', parent=None) -> None:
        spin = _Decimal()
        spin.setRange(lo, hi)
        # les décimales demandées ne bornent que l'affichage ; on garde
        # toujours de quoi représenter la valeur sans la tronquer
        spin.setDecimals(max(decimals, PRECISION))
        spin.shown = max(0, min(int(decimals), PRECISION))
        spin.setSingleStep(step)
        spin.setValue(value)
        spin._wire()
        super().__init__(spin, suffix.strip(), parent)


class IntSpin(_Field):
    """Champ entier : unité à l'extérieur."""

    def __init__(self, value: int = 0, lo: int = 0, hi: int = 999999,
                 step: int = 1, suffix: str = '', parent=None) -> None:
        spin = _Integer()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin._wire()
        super().__init__(spin, suffix.strip(), parent)


class TextBox(QPlainTextEdit):
    """Champ de saisie **étirable à la souris**, hauteur retenue.

    Un texte de plaque tient en une ligne ; un pavé de mentions légales
    en prend douze. La hauteur était figée à 80 pixels, soit quatre
    lignes : au-delà, on éditait par une meurtrière, en faisant défiler
    pour relire ce qu'on venait de taper.

    Le champ s'attrape donc par son **bord inférieur** — six pixels où
    le curseur devient une double flèche — et s'étire. La hauteur
    obtenue est retenue sous `cle`, et vaut pour les champs suivants :
    qui grave des pavés ne veut pas réétirer à chaque forme.

    Pourquoi pas la poignée de Qt : `QSizeGrip` réclame un coin libre,
    et le champ est dans un formulaire, collé à son voisin. Le bord
    entier est une cible plus large qu'un coin de dix pixels, et plus
    facile à viser à bout de bras sur un écran d'atelier.
    """

    #: Épaisseur de la zone d'attrape, en pixels.
    BORD = 8
    #: Bornes de hauteur, en pixels.
    MIN_H = 54
    MAX_H = 900

    #: La hauteur a changé : `(clé, hauteur)`.
    resized = Signal(str, int)

    def __init__(self, text: str = '', parent=None, *, cle: str = '',
                 hauteur: int = 150) -> None:
        super().__init__(text, parent)
        self._cle = cle
        self._tire = False
        self._depart = 0
        self._hauteur0 = 0
        self.setFixedHeight(max(self.MIN_H, min(int(hauteur), self.MAX_H)))
        self.setMouseTracking(True)

    # -- étirement ---------------------------------------------------------

    def _sur_le_bord(self, y: float) -> bool:
        return y >= self.height() - self.BORD

    def mouseMoveEvent(self, event) -> None:
        if self._tire:
            delta = int(event.position().y() - self._depart)
            self.setFixedHeight(max(self.MIN_H,
                                    min(self._hauteur0 + delta, self.MAX_H)))
            event.accept()
            return
        self.viewport().setCursor(
            Qt.SizeVerCursor if self._sur_le_bord(event.position().y())
            else Qt.IBeamCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if (event.button() == Qt.LeftButton
                and self._sur_le_bord(event.position().y())):
            self._tire = True
            self._depart = event.position().y()
            self._hauteur0 = self.height()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._tire:
            self._tire = False
            self.resized.emit(self._cle, self.height())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self.viewport().setCursor(Qt.IBeamCursor)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        """Trois traits au bas du champ : la poignée se voit.

        Sans marque, personne ne devine qu'un bord s'attrape : le champ
        restait à sa taille d'ouverture faute de savoir qu'il s'étirait.
        """
        super().paintEvent(event)
        from PySide6.QtGui import QColor, QPainter, QPen
        from . import theme
        peintre = QPainter(self.viewport())
        couleur = QColor(theme.hex_of('text_dim'))
        couleur.setAlpha(170)
        peintre.setPen(QPen(couleur, 1.2))
        bas = self.viewport().height() - 3
        centre = self.viewport().width() // 2
        for rang in range(3):
            y = bas - rang * 3
            demi = 9 - rang * 3
            peintre.drawLine(centre - demi, y, centre + demi, y)


class Combo(QComboBox):
    """Liste déroulante insensible à la molette.

    Même raison que pour les compteurs : faire défiler la colonne des
    propriétés ne doit pas changer une symbologie ou une recette au
    passage. La liste s'ouvre au clic, se parcourt au clavier.
    """

    def wheelEvent(self, event) -> None:
        event.ignore()


def fit_to_screen(dialog, margin: int = 60, content=None) -> None:
    """Borne une fenêtre à ce que l'écran peut montrer.

    Un formulaire qui grandit finit par déborder : sur un écran FullHD
    avec sa barre des tâches, il reste un millier de pixels, et les
    boutons *Générer* et *Annuler* passaient dessous, hors d'atteinte. Une
    fenêtre dont on ne peut pas atteindre le bouton de validation est
    inutilisable sans qu'on comprenne pourquoi.

    À employer avec une zone défilante : borner la hauteur ne sert à rien
    si le contenu ne peut pas défiler.
    """
    ecran = dialog.screen() or QGuiApplication.primaryScreen()
    if ecran is None:
        return
    place = ecran.availableGeometry()
    voulu = dialog.sizeHint()
    hauteur, largeur = voulu.height(), voulu.width()
    if content is not None:
        # Une zone défilante n'annonce que sa taille minimale : sans
        # regarder le contenu, la fenêtre s'ouvrirait repliée sur 400 px
        # alors qu'elle a la place de tout montrer.
        vu = content.sizeHint()
        hauteur = max(hauteur, vu.height() + 2 * margin)
        largeur = max(largeur, vu.width() + 40)
    dialog.resize(min(largeur, place.width() - margin),
                  min(hauteur, place.height() - margin))


class GrowingText(QPlainTextEdit):
    """Zone de texte qui prend la hauteur de son contenu.

    Une zone fixe de trois lignes gaspille la place quand elle est vide et
    la refuse quand elle est pleine. Celle-ci grandit ligne à ligne, entre
    une et huit : au-delà, l'ascenseur reprend la main plutôt que de
    pousser le reste du panneau hors de vue.
    """

    MIN_LINES = 1
    MAX_LINES = 8

    def __init__(self, text: str = '', parent=None) -> None:
        super().__init__(text, parent)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda *_: self._fit())
        self._fit()

    def _fit(self) -> None:
        metrique = self.fontMetrics().lineSpacing()
        lignes = max(self.MIN_LINES,
                     min(self.MAX_LINES,
                         int(self.document().size().height())))
        marges = self.contentsMargins()
        cadre = int(self.document().documentMargin()) * 2 + 6
        self.setFixedHeight(lignes * metrique + cadre
                            + marges.top() + marges.bottom())

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:
        if value != self.toPlainText():
            self.setPlainText(value or '')
