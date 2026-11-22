"""Propriétés d'un lot de formes / Group properties.

Sélectionner une seule forme montre ses propriétés ; en sélectionner
plusieurs — ou cliquer un groupe — n'en montrait aucune, alors que c'est
précisément à ce moment qu'on veut agir d'un bloc : recentrer un
ensemble, l'ajuster à sa fenêtre, passer les vingt-cinq cases d'un coupon
sur la même process.

Ce panneau prend donc la place de l'inspecteur dès que la sélection
dépasse une forme. Il montre du **lot** :

* son centre et son encombrement, modifiables — le lot se déplace et se
  met à l'échelle d'un bloc, proportions conservées si on le demande ;
* sa **rotation**, appliquée à chaque membre ;
* la **process commune**, si toutes les formes en portent une seule ; et
  de quoi l'imposer à toutes, ce qui est l'intérêt principal du panneau ;
* la **longueur gravée** et la **durée estimée** du lot seul, mesurées
  exactement comme à l'export ;
* le **cadre commun** — marge, décalage, épaisseur de trait — parce que
  régler un négatif forme par forme sur douze pièces identiques est un
  travail de copiste ;
* de quoi le **disposer** : aligner, répartir, centrer dans le champ —
  voir `disposition`.

**Une valeur mêlée ne s'écrit pas.** Un champ dont les formes ne
partagent pas la valeur reste vide et n'est pas appliqué : afficher la
valeur de la première et la répandre au premier survol de molette
détruirait le travail sans que rien ne l'annonce.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from . import disposition, recipes, resize, theme
from .model import Document, Recipe, Shape
from .widgets import Spin
from . import theme

#: Ce qu'affiche un champ dont les formes ne partagent pas la valeur.
MIXED = '—'

#: Sentinelles : la valeur « absente » de chaque champ, choisie juste
#: sous son domaine utile pour ne jamais entrer en conflit avec un
#: réglage légitime — une marge nulle reste une marge nulle.
MIXED_ANGLE = -361.0
MIXED_MM = -1.0
MIXED_OFFSET = -21.0

#: Au-delà, la mesure du lot n'est plus refaite à chaque sélection : sur
#: un coupon de plusieurs centaines de cases, construire les trajectoires
#: prend plus longtemps que le clic ne le supporte.
MEASURE_LIMIT = 240


def common(shapes: list[Shape], champ: str):
    """Valeur partagée par toutes les formes, ou `None` si elles diffèrent."""
    valeurs = {getattr(s, champ, None) for s in shapes}
    return valeurs.pop() if len(valeurs) == 1 else None


def common_recipe(shapes: list[Shape]) -> Recipe | None:
    """Process partagée, reconnue à son nom **et** à ses réglages.

    Deux formes qui portent « Laiton » avec deux puissances différentes ne
    partagent pas une process : dire le contraire ferait croire que
    modifier l'une modifie l'autre.
    """
    if not shapes:
        return None
    premiere = shapes[0].recipe
    repere = _signature(premiere)
    return premiere if all(_signature(s.recipe) == repere
                           for s in shapes) else None


def _signature(recipe: Recipe) -> tuple:
    return (recipe.name, recipe.tool_number, recipe.power_percent,
            recipe.frequency_khz, recipe.pulse_width_ns, recipe.speed_mm_min,
            recipe.passes, recipe.hatch_mm)


def measure(shapes: list[Shape], document: Document) -> tuple[float, float]:
    """Longueur gravée et durée estimée du lot seul, en mm et en secondes.

    Les trajectoires sont construites comme à l'export, sur un document
    de circonstance qui ne contient que le lot : la mesure porte donc bien
    sur ce qui est sélectionné, et non sur la plaque entière.
    """
    from .toolpath import build_passes, total_duration_s, total_length_mm
    vivantes = [s for s in shapes if s.visible]
    if not vivantes or len(vivantes) > MEASURE_LIMIT:
        return 0.0, 0.0
    part = Document(shapes=list(vivantes), field_w=document.field_w,
                    field_h=document.field_h, name=document.name)
    try:
        passes = build_passes(part)
    except Exception:
        return 0.0, 0.0
    return total_length_mm(passes), total_duration_s(passes)


class LotPanel(QWidget):
    """Propriétés d'une sélection multiple ou d'un groupe."""

    #: Une propriété du lot a changé : les formes sont déjà modifiées.
    changed = Signal()
    #: Le lot demande à être dégroupé / regroupé.
    grouped = Signal()
    ungrouped = Signal()
    #: On veut voir les propriétés de la forme principale, pas celles du lot.
    primary_asked = Signal()
    #: Un mot pour la barre d'état, après un geste de disposition.
    note = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._shapes: list[Shape] = []
        self._document = Document()
        self._recipes: list[Recipe] = []
        self._primary: Shape | None = None
        self._guard = False
        self._w0 = self._h0 = 0.0

        dehors = QVBoxLayout(self)
        dehors.setAlignment(Qt.AlignTop)
        dehors.setContentsMargins(0, 0, 0, 0)

        self.w_title = QLabel('')
        self.w_title.setWordWrap(True)
        dehors.addWidget(self.w_title)

        dehors.addWidget(self._placement())
        dehors.addWidget(self._arrange())
        dehors.addWidget(self._process())
        dehors.addWidget(self._frame())
        dehors.addWidget(self._measures())

        # Un groupe ne doit pas emprisonner ses membres : un code posé
        # dans son cadre est un groupe de deux, et c'est bien la donnée du
        # code qu'on vient taper. Ce bouton ouvre la forme principale sans
        # défaire la sélection.
        self.w_primary = QPushButton('')
        self.w_primary.setToolTip(
            'Ouvre les propriétés de la forme cliquée, sans quitter le '
            'lot : la sélection ne change pas.')
        self.w_primary.clicked.connect(self.primary_asked.emit)
        dehors.addWidget(self.w_primary)

        rangee = QHBoxLayout()
        self.w_group = QPushButton('Grouper')
        self.w_group.setToolTip(
            'Réunit les formes : elles se sélectionnent et se déplacent '
            'ensuite d\'un bloc.')
        self.w_group.clicked.connect(self.grouped.emit)
        self.w_ungroup = QPushButton('Dégrouper')
        self.w_ungroup.clicked.connect(self.ungrouped.emit)
        rangee.addWidget(self.w_group)
        rangee.addWidget(self.w_ungroup)
        dehors.addLayout(rangee)

    # -- construction ------------------------------------------------------

    def _placement(self) -> QGroupBox:
        boite = QGroupBox('Placement du lot')
        f = QFormLayout(boite)
        theme.tidy_form(f)
        self.w_cx = Spin(0, -5000, 5000, 1, 3, ' mm')
        self.w_cy = Spin(0, -5000, 5000, 1, 3, ' mm')
        self.w_dx = Spin(0, 0.001, 5000, 1, 3, ' mm')
        self.w_dy = Spin(0, 0.001, 5000, 1, 3, ' mm')
        # Le minimum de ces champs est **une sentinelle**, hors du domaine
        # utile : c'est ce que Qt affiche à la place du nombre quand la
        # valeur manque. Un lot dont les formes ne partagent pas l'angle
        # montre ainsi « — » plutôt que l'angle de la première.
        self.w_rot = Spin(0, MIXED_ANGLE, 360, 1, 2, ' °')
        self.w_keep = QCheckBox('Conserver les proportions')
        self.w_keep.setChecked(True)
        self.w_keep.setToolTip(
            'Une cote entrée entraîne l\'autre. Décochée, le lot '
            's\'étire dans un seul axe.')
        for nom, widget in (('Centre X', self.w_cx), ('Centre Y', self.w_cy)):
            widget.valueChanged.connect(self._moved)
            f.addRow(nom, widget)
        f.addRow('', self.w_keep)
        self.w_dx.valueChanged.connect(lambda *_: self._sized('x'))
        self.w_dy.valueChanged.connect(lambda *_: self._sized('y'))
        f.addRow('Dim. X', self.w_dx)
        f.addRow('Dim. Y', self.w_dy)
        self.w_rot.valueChanged.connect(self._rotated)
        self.w_rot.setToolTip(
            'Rotation appliquée à chaque forme du lot, autour de son '
            'propre centre. Vide si les formes ne partagent pas le même '
            'angle.')
        f.addRow('Rotation', self.w_rot)
        return boite

    def _arrange(self) -> QGroupBox:
        boite = QGroupBox('Disposer')
        grille = QGridLayout(boite)
        grille.setContentsMargins(6, 6, 6, 6)
        grille.setSpacing(4)
        libelles = {
            'gauche': ('⇤ Gauche', 'Aligne le bord gauche de chaque bloc '
                       'sur celui de l\'ensemble.'),
            'centre': ('↔ Centre', 'Aligne les blocs sur l\'axe vertical '
                       'de l\'ensemble.'),
            'droite': ('Droite ⇥', 'Aligne le bord droit de chaque bloc '
                       'sur celui de l\'ensemble.'),
            'haut': ('⤒ Haut', 'Aligne le bord haut de chaque bloc sur '
                     'celui de l\'ensemble.'),
            'milieu': ('↕ Milieu', 'Aligne les blocs sur l\'axe '
                       'horizontal de l\'ensemble.'),
            'bas': ('Bas ⤓', 'Aligne le bord bas de chaque bloc sur celui '
                    'de l\'ensemble.'),
        }
        self.w_align: dict[str, QPushButton] = {}
        for rang, (mode, _axe, _cote) in enumerate(disposition.ALIGNEMENTS):
            texte, aide = libelles[mode]
            bouton = QPushButton(texte)
            bouton.setToolTip(aide + ' Un groupe bouge d\'un bloc.')
            bouton.clicked.connect(lambda _=False, m=mode: self._align(m))
            grille.addWidget(bouton, rang // 3, rang % 3)
            self.w_align[mode] = bouton
        self.w_spread_x = QPushButton('Répartir ↔')
        self.w_spread_x.setToolTip(
            'Égalise les espaces entre les blocs, de gauche à droite ; '
            'les deux extrêmes ne bougent pas. Trois blocs au moins.')
        self.w_spread_x.clicked.connect(lambda: self._spread('x'))
        self.w_spread_y = QPushButton('Répartir ↕')
        self.w_spread_y.setToolTip(
            'Égalise les espaces entre les blocs, de bas en haut ; les '
            'deux extrêmes ne bougent pas. Trois blocs au moins.')
        self.w_spread_y.clicked.connect(lambda: self._spread('y'))
        self.w_center = QPushButton('Au centre')
        self.w_center.setToolTip(
            'Centre le lot entier dans le champ de marquage, sans changer '
            'la place des formes entre elles.')
        self.w_center.clicked.connect(self._center)
        grille.addWidget(self.w_spread_x, 2, 0)
        grille.addWidget(self.w_spread_y, 2, 1)
        grille.addWidget(self.w_center, 2, 2)
        return boite

    def _process(self) -> QGroupBox:
        boite = QGroupBox('Process du lot')
        f = QFormLayout(boite)
        theme.tidy_form(f)
        self.w_recipe = QComboBox()
        self.w_recipe.setToolTip(
            'Applique une process à **toutes** les formes du lot.\n'
            '« — » signifie que le lot en porte plusieurs : c\'est le cas '
            'voulu\nd\'un coupon d\'essai, où chaque case a la sienne.')
        f.addRow('Process', self.w_recipe)
        self.w_apply = QPushButton('Appliquer à tout le lot')
        self.w_apply.clicked.connect(self._apply_recipe)
        f.addRow('', self.w_apply)
        self.w_recipe_note = QLabel('')
        self.w_recipe_note.setWordWrap(True)
        self.w_recipe_note.setStyleSheet(theme.css('text_dim', 11))
        f.addRow('', self.w_recipe_note)
        return boite

    def _frame(self) -> QGroupBox:
        boite = QGroupBox('Cadre commun')
        f = QFormLayout(boite)
        theme.tidy_form(f)
        self.w_frame = QComboBox()
        self.w_frame.addItem(MIXED, None)
        for libelle, code in (('aucun', 'none'), ('rectangle', 'rect'),
                              ('cercle', 'circle')):
            self.w_frame.addItem(libelle, code)
        self.w_frame.currentIndexChanged.connect(
            lambda *_: self._set_all('frame', self.w_frame.currentData()))
        f.addRow('Cadre', self.w_frame)
        self.w_margin = Spin(0, MIXED_MM, 200, 0.5, 3, ' mm')
        self.w_offset = Spin(0, MIXED_OFFSET, 20, 0.05, 3, ' mm')
        self.w_line = Spin(0, MIXED_MM, 50, 0.05, 3, ' mm')
        self.w_margin.valueChanged.connect(
            lambda v: self._set_all('frame_margin_mm', v))
        self.w_offset.valueChanged.connect(
            lambda v: self._set_all('frame_offset_mm', v))
        self.w_line.valueChanged.connect(
            lambda v: self._set_all('line_width_mm', v))
        self.w_offset.setToolTip(
            'Épaissit ou amincit le tracé. Sous un cadre, compense la '
            'largeur du faisceau sur un négatif ; seul, grossit ou '
            'affine le dessin lui-même.')
        f.addRow('Marge', self.w_margin)
        f.addRow('Décalage', self.w_offset)
        f.addRow('Épaisseur trait', self.w_line)
        return boite

    def _measures(self) -> QGroupBox:
        boite = QGroupBox('Le lot en chiffres')
        f = QFormLayout(boite)
        theme.tidy_form(f)
        self.w_count = QLabel('')
        self.w_length = QLabel('')
        self.w_time = QLabel('')
        f.addRow('Formes', self.w_count)
        f.addRow('Longueur gravée', self.w_length)
        f.addRow('Durée estimée', self.w_time)
        return boite

    # -- remplissage -------------------------------------------------------

    def set_recipes(self, recipes: list[Recipe]) -> None:
        """Process proposées dans la liste déroulante."""
        self._recipes = list(recipes)

    def set_lot(self, shapes: list[Shape], document: Document,
                primary: Shape | None = None) -> None:
        """Montre ce lot. Une liste de moins de deux formes vide le panneau."""
        self._shapes = list(shapes)
        self._document = document
        self._primary = primary if primary in self._shapes else (
            self._shapes[0] if self._shapes else None)
        if len(self._shapes) < 2:
            return
        self._guard = True
        try:
            self._fill()
        finally:
            self._guard = False

    def _fill(self) -> None:
        formes = self._shapes
        groupes = {s.group for s in formes if s.group}
        if len(groupes) == 1 and all(s.group for s in formes):
            titre = f'<b>Groupe de {len(formes)} formes</b>'
        else:
            titre = f'<b>{len(formes)} formes sélectionnées</b>'
        caches = sum(1 for s in formes if not s.visible)
        if caches:
            titre += f'<br><span style="color:{theme.hex_of('text_dim')}">{caches} masquée(s)' \
                     f' — non gravée(s)</span>'
        self.w_title.setText(titre)
        self.w_group.setEnabled(len(groupes) != 1 or not all(
            s.group for s in formes))
        self.w_ungroup.setEnabled(bool(groupes))
        if self._primary is not None:
            self.w_primary.setText(
                f'Propriétés de « {self._primary.display_name()} »')
            self.w_primary.setEnabled(True)
        else:
            self.w_primary.setText('Propriétés d\'une forme')
            self.w_primary.setEnabled(False)

        cx, cy = resize.selection_center(formes)
        self._w0, self._h0 = resize.selection_size(formes)
        self.w_cx.setValue(cx)
        self.w_cy.setValue(cy)
        self.w_dx.setValue(max(self._w0, 0.001))
        self.w_dy.setValue(max(self._h0, 0.001))

        angle = common(formes, 'rotation_deg')
        self.w_rot.setSpecialValueText('' if angle is not None else MIXED)
        self.w_rot.setValue(angle if angle is not None else self.w_rot.minimum())

        self._fill_recipes()
        self._fill_frame()
        self._fill_measures()

    def _fill_recipes(self) -> None:
        partagee = common_recipe(self._shapes)
        self.w_recipe.blockSignals(True)
        connues = list(self._recipes)
        if partagee is not None and not any(
                _signature(r) == _signature(partagee) for r in connues):
            connues.insert(0, partagee)
        # rangée comme la page des process : racine, puis dossiers
        recipes.fill_combo(
            self.w_recipe, connues,
            texte=lambda r: f'T{r.tool_number} · {r.name}',
            first=(MIXED + '  (process mêlées)', None))
        rang = -1
        if partagee is not None:
            rang = recipes.combo_index(
                self.w_recipe, partagee,
                same=lambda a, b: _signature(a) == _signature(b))
        self.w_recipe.setCurrentIndex(max(rang, 0))
        self.w_recipe.blockSignals(False)

        outils = sorted({s.recipe.tool_number for s in self._shapes})
        if partagee is not None:
            self.w_recipe_note.setText(
                f'Tout le lot grave en T{partagee.tool_number}.')
        else:
            self.w_recipe_note.setText(
                f'{len(outils)} outils dans ce lot : '
                + ', '.join(f'T{t}' for t in outils[:8])
                + ('…' if len(outils) > 8 else '')
                + '. Appliquer une process les remplacerait tous.')

    def _fill_frame(self) -> None:
        cadre = common(self._shapes, 'frame')
        self.w_frame.blockSignals(True)
        index = self.w_frame.findData(cadre)
        self.w_frame.setCurrentIndex(index if index >= 0 else 0)
        self.w_frame.blockSignals(False)
        for widget, champ in ((self.w_margin, 'frame_margin_mm'),
                              (self.w_offset, 'frame_offset_mm'),
                              (self.w_line, 'line_width_mm')):
            valeur = common(self._shapes, champ)
            widget.blockSignals(True)
            widget.setSpecialValueText('' if valeur is not None else MIXED)
            widget.setValue(valeur if valeur is not None
                            else widget.minimum())
            widget.blockSignals(False)

    def _fill_measures(self) -> None:
        from .preflight import duration_text
        self.w_count.setText(f'{len(self._shapes)}')
        longueur, duree = measure(self._shapes, self._document)
        if longueur <= 0 and len(self._shapes) > MEASURE_LIMIT:
            self.w_length.setText('lot trop grand pour être mesuré ici')
            self.w_time.setText('—')
            return
        self.w_length.setText(f'{longueur:,.1f} mm'.replace(',', ' '))
        self.w_time.setText(duration_text(duree))

    def follow_move(self) -> None:
        """Recale le centre du lot après un geste au plan de travail.

        Même défaut que l'inspecteur : déplacer le lot à la souris ne
        passait pas par ici, et le premier réglage de *Centre Y* ramenait
        *Centre X* là d'où on venait. Rien n'est émis.
        """
        if len(self._shapes) < 2 or self._guard:
            return
        cx, cy = resize.selection_center(self._shapes)
        self._guard = True
        try:
            if abs(self.w_cx.value() - cx) > 1e-9:
                self.w_cx.setValue(cx)
            if abs(self.w_cy.value() - cy) > 1e-9:
                self.w_cy.setValue(cy)
        finally:
            self._guard = False

    # -- gestes ------------------------------------------------------------

    def _moved(self, *_) -> None:
        if self._guard or len(self._shapes) < 2:
            return
        resize.move_selection_center(self._shapes, self.w_cx.value(),
                                     self.w_cy.value())
        self.changed.emit()

    def _sized(self, axe: str) -> None:
        if self._guard or len(self._shapes) < 2:
            return
        if self._w0 <= 0 or self._h0 <= 0:
            return
        fx = max(self.w_dx.value(), 1e-6) / self._w0
        fy = max(self.w_dy.value(), 1e-6) / self._h0
        if self.w_keep.isChecked():
            fx = fy = fx if axe == 'x' else fy
        resize.scale_selection(self._shapes, fx, fy)
        # le lot vient de changer de taille : ce qui suit se mesure sur les
        # nouvelles cotes, sans quoi un second réglage repartirait des
        # anciennes et doublerait le facteur
        self._guard = True
        try:
            self._w0, self._h0 = resize.selection_size(self._shapes)
            self.w_dx.setValue(max(self._w0, 0.001))
            self.w_dy.setValue(max(self._h0, 0.001))
            cx, cy = resize.selection_center(self._shapes)
            self.w_cx.setValue(cx)
            self.w_cy.setValue(cy)
        finally:
            self._guard = False
        self.changed.emit()

    def _rotated(self, valeur: float) -> None:
        if self._guard or len(self._shapes) < 2:
            return
        if self.w_rot.specialValueText() and valeur == self.w_rot.minimum():
            return                      # champ mêlé, laissé tel quel
        for forme in self._shapes:
            forme.rotation_deg = float(valeur)
        self.changed.emit()

    def _align(self, mode: str) -> None:
        if len(self._shapes) < 2:
            return
        n = disposition.aligner(self._shapes, mode)
        ou = {'gauche': 'à gauche', 'centre': 'au centre',
              'droite': 'à droite', 'haut': 'en haut',
              'milieu': 'au milieu', 'bas': 'en bas'}[mode]
        self._arranged(n, f'alignés {ou}')

    def _spread(self, axe: str) -> None:
        if len(self._shapes) < 2:
            return
        if len(disposition.blocs(self._shapes)) < 3:
            self.note.emit('Répartir : il faut au moins trois blocs — un '
                           'groupe compte pour un')
            return
        n = disposition.repartir(self._shapes, axe)
        self._arranged(n, 'répartis ' + ('de gauche à droite' if axe == 'x'
                                          else 'de bas en haut'))

    def _center(self) -> None:
        if len(self._shapes) < 2:
            return
        bouge = disposition.centrer(self._shapes)
        self._arranged(int(bouge), 'centrés dans le champ', lot=True)

    def _arranged(self, n: int, quoi: str, lot: bool = False) -> None:
        """Après un geste de disposition : redessiner, et le dire."""
        if not n:
            self.note.emit('Déjà en place : rien n\'a bougé')
            return
        self.follow_move()
        self.changed.emit()
        self.note.emit(f'Lot {quoi}' if lot
                       else f'{n} bloc(s) {quoi}')

    def _set_all(self, champ: str, valeur) -> None:
        """Impose une valeur à toutes les formes du lot."""
        if self._guard or valeur is None or len(self._shapes) < 2:
            return
        widget = self.sender()
        if (hasattr(widget, 'specialValueText') and widget.specialValueText()
                and valeur == widget.minimum()):
            return                      # champ mêlé, non touché
        for forme in self._shapes:
            setattr(forme, champ, valeur)
        if hasattr(widget, 'setSpecialValueText'):
            widget.setSpecialValueText('')
        self.changed.emit()

    def _apply_recipe(self) -> None:
        """Pose la process choisie sur toutes les formes du lot."""
        recette = self.w_recipe.currentData()
        if recette is None or len(self._shapes) < 2:
            return
        for forme in self._shapes:
            forme.recipe = recette
        self._guard = True
        try:
            self._fill_recipes()
            self._fill_measures()
        finally:
            self._guard = False
        self.changed.emit()
