"""Coupon d'essai / Parameter test coupon.

La façon normale de valider une recette sur une matière : graver la même
géométrie plusieurs fois, en ne changeant qu'un paramètre à la fois, et
lire le résultat à l'œil sur la chute.

Le coupon produit une **grille** : un paramètre varie en X, un autre en Y,
et chaque case porte ses valeurs gravées à côté d'elle. Sans ces
étiquettes, une chute retrouvée trois semaines plus tard ne dit plus rien.

C'est ce qui transforme une recette « point de départ » en valeurs
mesurées chez soi. Les recettes matière livrées avec TauDrive sont
précisément dans ce cas : leurs paramètres laser viennent du magasin de la
machine, mais les profondeurs et le cuir demandent une chute.
"""
from __future__ import annotations

import dataclasses
import pathlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from . import recipes, session
from .model import (FIELD_H_MM, FIELD_W_MM, SPEED_TO_DISPLAY,
                    SPEED_FROM_DISPLAY, SPEED_UNIT, Path, Rect,
                    Recipe, Shape, Text)
from .widgets import Combo, IntSpin, Spin, fit_to_screen
from . import theme

#: Paramètres qu'un coupon sait faire varier.
#:
#: `passes` et `depth_total_mm` servent aux essais de profondeur ;
#: `power_percent` et `speed_mm_min` aux essais de rendu.
#: Le quatrième terme convertit l'unité **du modèle** vers celle qu'on
#: affiche et qu'on grave. Seule la vitesse en a besoin : le modèle et
#: l'ISO la portent en mm/min, l'atelier la lit en m/min.
AXES: tuple[tuple[str, str, str, float], ...] = (
    ('power_percent', 'Puissance', '%', 1.0),
    ('speed_mm_min', 'Vitesse', SPEED_UNIT, SPEED_TO_DISPLAY),
    ('frequency_khz', 'Fréquence', 'kHz', 1.0),
    ('pulse_width_ns', 'Impulsion', 'ns', 1.0),
    ('couple', 'Couple F-T', '', 1.0),
    ('hatch_mm', 'Hachure', 'mm', 1.0),
    ('passes', 'Nb passes', '', 1.0),
    ('depth_total_mm', 'Profondeur', 'mm', 1.0),
    ('', '(aucun)', '', 1.0),
)

#: Champs entiers : une puissance peut valoir 62,5 %, pas un nombre de
#: passes.
_INTEGERS = {'passes', 'pulse_width_ns'}

#: Axes réservés au mode expert. Même règle que dans l'éditeur de
#: recette : fréquence et durée d'impulsion ne se déplacent pas par
#: mégarde.
#:
#: L'axe **couple** n'en fait pas partie : c'est justement la façon sûre
#: de faire varier ces deux réglages en mode normal, puisqu'il ne propose
#: alors que des paires de la table constructeur.
_EXPERT_AXES = {'frequency_khz', 'pulse_width_ns'}

#: L'axe qui ne porte pas un nombre mais une **paire** de réglages.
COUPLE_AXIS = 'couple'

#: Pas d'arrondi des valeurs d'essai, par paramètre.
#:
#: Un coupon doit produire des valeurs qu'on puisse **recopier dans une
#: recette**. Une répartition brute donnait des vitesses comme
#: « 93333,3333 mm/min » : illisible sur la pièce, et personne ne la
#: ressaisira. Chaque axe est donc ramené à un pas de son ordre de
#: grandeur.
_ROUNDING = {
    'power_percent': 0.5,
    'speed_mm_min': 500.0,
    'frequency_khz': 1.0,
    'hatch_mm': 0.005,
    'depth_total_mm': 0.01,
}


def axis_label(field: str) -> str:
    for key, label, _, _ in AXES:
        if key == field:
            return label
    return field


def axis_unit(field: str) -> str:
    for key, _, unit, _ in AXES:
        if key == field:
            return unit
    return ''


def axis_scale(field: str) -> float:
    """Facteur modèle → affichage. 1 partout sauf sur la vitesse."""
    for key, _, _, scale in AXES:
        if key == field:
            return scale
    return 1.0


def couple_steps(chosen, count: int = 0) -> list:
    """Les couples retenus pour un axe, dans l'ordre des impulsions.

    Un axe de couples ne se répartit pas entre deux bornes : on choisit
    des paires dans une table, et l'ordre qui parle est celui des durées
    d'impulsion croissantes.
    """
    from . import couples as _c
    retenus = []
    vus = set()
    for element in chosen or ():
        couple = (element if isinstance(element, _c.Couple)
                  else _c.parse(str(element)))
        if couple is not None and couple.key() not in vus:
            vus.add(couple.key())
            retenus.append(couple)
    retenus.sort(key=lambda c: c.pulse_width_ns)
    return retenus[:count] if count else retenus


def steps(start: float, stop: float, count: int, field: str) -> list:
    """Valeurs réparties de `start` à `stop`, bornes comprises."""
    count = max(1, int(count))
    if count == 1:
        values = [start]
    else:
        span = (stop - start) / (count - 1)
        values = [start + span * i for i in range(count)]
    if field in _INTEGERS:
        # sans arrondi, deux cases voisines porteraient le même nombre de
        # passes tout en s'annonçant différentes
        return sorted({max(1, int(round(v))) for v in values})
    pas = _ROUNDING.get(field)
    if pas:
        arrondies = sorted({round(round(v / pas) * pas, 6) for v in values})
        if arrondies:
            return arrondies
    return [round(v, 6) for v in values]


def _format(value: float, field: str) -> str:
    """Valeur telle qu'elle sera **gravée** : dans l'unité d'affichage.

    Une vitesse gravée « 40000 » sur une case de 8 mm est illisible et ne
    dit rien à qui lit la machine en m/min. On grave « 40 ».
    """
    if field == COUPLE_AXIS:
        return value.key() if hasattr(value, 'key') else str(value)
    if field in _INTEGERS:
        return f'{int(value)}'
    text = f'{value * axis_scale(field):.6f}'.rstrip('0').rstrip('.')
    return text or '0'


def build(recipe: Recipe, *,
          x_field: str = 'power_percent', x_from: float = 20.0,
          x_to: float = 100.0, x_count: int = 5,
          y_field: str = 'speed_mm_min', y_from: float = 40000.0,
          y_to: float = 200000.0, y_count: int = 4,
          x_couples=None, y_couples=None, motif=None,
          cell_mm: float = 8.0, gap_mm: float = 3.0,
          label_mm: float = 1.8, hatched: bool = True,
          labels_hatched: bool = False, show_title: bool = True,
          show_x_labels: bool = True, show_y_labels: bool = True,
          fixed: dict | None = None) -> list[Shape]:
    """Grille d'essai : une case par couple de valeurs, étiquetée.

    Rend les formes prêtes à être ajoutées au document et groupées. La
    grille est centrée sur l'origine, marges d'étiquettes comprises, de
    sorte qu'elle tienne d'emblée dans le champ.

    `fixed` **impose** les paramètres qui ne varient pas — ceux qui ne
    sont sur aucun des deux axes. Sans lui, un essai en puissance se
    faisait à la vitesse de la recette de départ, qu'il fallait modifier
    ailleurs avant de venir ici. Les axes l'emportent : un paramètre qui
    varie ne peut pas être fixé en même temps.
    """
    if fixed:
        impose = {k: v for k, v in fixed.items()
                  if k and k not in (x_field, y_field)}
        if 'depth_total_mm' in impose:
            impose['depth_mode'] = 'total'
        if impose:
            recipe = dataclasses.replace(recipe, **impose)

    x_values = _axis_values(x_field, x_from, x_to, x_count, x_couples)
    y_values = _axis_values(y_field, y_from, y_to, y_count, y_couples)

    pas = cell_mm + gap_mm
    largeur = len(x_values) * pas - gap_mm
    hauteur = len(y_values) * pas - gap_mm
    # la marge se cale sur la plus longue étiquette : une vitesse à six
    # chiffres a besoin de plus de place qu'une puissance à deux
    plus_long = max((len(_format(v, y_field)) for v in y_values
                     if v is not None), default=2)
    marge = max(label_mm * 0.62 * plus_long + 2.0, 8.0)
    x0 = -(largeur + marge) / 2 + marge
    y0 = (hauteur + marge) / 2 - marge

    out: list[Shape] = []
    for iy, y_value in enumerate(y_values):
        cy = y0 - iy * pas - cell_mm / 2
        for ix, x_value in enumerate(x_values):
            cx = x0 + ix * pas + cell_mm / 2
            variante = dict()
            if x_field and x_value is not None:
                variante[x_field] = x_value
            if y_field and y_value is not None:
                variante[y_field] = y_value
            essai = _apply(recipe, variante, hatched)
            nom = _case_name(variante, x_field, y_field)
            if motif:
                out.append(_motif_cell(motif, cx, cy, cell_mm, essai, nom))
            else:
                out.append(Rect(x=cx, y=cy, width=cell_mm, height=cell_mm,
                                recipe=essai, name=nom))

        if show_y_labels and y_field and y_value is not None:
            out.append(Text(
                x=x0 - marge / 2, y=cy, size_mm=label_mm, align='center',
                text=_format(y_value, y_field),
                recipe=_marker(recipe, labels_hatched),
                name=f'étiquette {axis_label(y_field)}'))

    for ix, x_value in enumerate(x_values):
        if not show_x_labels or not x_field or x_value is None:
            continue
        out.append(Text(
            x=x0 + ix * pas + cell_mm / 2, y=y0 + marge / 2,
            size_mm=label_mm, align='center',
            text=_format(x_value, x_field),
            recipe=_marker(recipe, labels_hatched),
            name=f'étiquette {axis_label(x_field)}'))

    # en-tête : de quoi retrouver ce que le coupon voulait dire
    if show_title:
        titre = f'{recipe.name} · X {axis_label(x_field)} {axis_unit(x_field)}'
        if y_field:
            titre += f' · Y {axis_label(y_field)} {axis_unit(y_field)}'
        out.append(Text(x=0.0, y=y0 + marge + label_mm, size_mm=label_mm,
                        align='center', text=titre,
                        recipe=_marker(recipe, labels_hatched),
                        name='titre du coupon'))
    return out


def _axis_values(field: str, depart: float, fin: float, nombre: int,
                 couples=None) -> list:
    """Les valeurs d'un axe, couples compris. `[None]` si l'axe est vide."""
    if not field:
        return [None]
    if field == COUPLE_AXIS:
        return couple_steps(couples) or [None]
    return steps(depart, fin, nombre, field)


def _apply(recipe: Recipe, variante: dict, hatched: bool) -> Recipe:
    """Process d'une case, avec son nom lisible dans la liste des formes.

    « Remplir les cases » **remplit** : coché sur une recette sans
    hachurage, il en pose un. Il ne faisait jusqu'ici que retirer celui
    qui existait déjà, si bien que cocher la case ne changeait rien sur la
    moitié des recettes — et qu'un coupon de rendu de surface sortait en
    contours.
    """
    values = dict(variante)
    couple = values.pop(COUPLE_AXIS, None)
    if couple is not None:
        # un couple pose **les deux** réglages d'un bloc : c'est tout son
        # objet, les régler séparément produirait des cases impossibles
        values.update(couple.values())
    if 'depth_total_mm' in values:
        values['depth_mode'] = 'total'
    if hatched:
        if recipe.hatch_mm <= 0 and 'hatch_mm' not in values:
            values['hatch_mm'] = HATCH_DEFAULT_MM
    else:
        values['hatch_mm'] = 0.0
    detail = ' · '.join(f'{axis_label(k)} {_format(v, k)}{axis_unit(k)}'
                        for k, v in variante.items())
    values['name'] = f'{recipe.name} — {detail}' if detail else recipe.name
    return dataclasses.replace(recipe, **values)


#: Pas de hachure posé quand on veut du plein et que la recette n'en a
#: aucun. 0,05 mm est le pas des recettes matière livrées.
HATCH_DEFAULT_MM = 0.05
LABEL_HATCH_MM = HATCH_DEFAULT_MM


def _marker(recipe: Recipe, hatched: bool = False) -> Recipe:
    """Recette des étiquettes : elles doivent se lire, pas creuser.

    Elles gardent l'outil de la process d'essai — changer d'outil au
    milieu d'un coupon ferait perdre du temps en changements inutiles —
    mais à puissance réduite et en une seule passe.

    Hachurées ou filaires **indépendamment des cases**. Sur un métal clair,
    un texte filaire de 1,8 mm disparaît à la lecture ; sur un cuir sombre,
    le hachurer le brûle. Les deux réglages n'ont pas la même bonne réponse
    au même moment, et lier l'un à l'autre obligerait à choisir entre une
    grille lisible et des étiquettes lisibles.
    """
    return dataclasses.replace(
        recipe, name=f'{recipe.name} — étiquettes',
        power_percent=min(recipe.power_percent, 25.0),
        hatch_mm=LABEL_HATCH_MM if hatched else 0.0,
        passes=1, depth_mode='step', depth_step_mm=0.0,
        depth_total_mm=0.0)


def _case_name(variante: dict, x_field: str, y_field: str) -> str:
    if not variante:
        return 'case'
    return 'case ' + ' / '.join(
        f'{_format(v, k)}{axis_unit(k)}' for k, v in variante.items())


#: Bornes de repli quand la recette ne renseigne pas le paramètre — cas de
#: la profondeur, laissée à zéro tant qu'on grave sans creuser.
_FALLBACK = {
    'depth_total_mm': (0.02, 0.2),
    'hatch_mm': (0.01, 0.08),
    'frequency_khz': (20.0, 200.0),
    'pulse_width_ns': (2.0, 200.0),
    'speed_mm_min': (20000.0, 200000.0),
}


# ---------------------------------------------------------------------------
# Motif des cases
# ---------------------------------------------------------------------------
#
# Une case carrée pleine juge un rendu de surface, et rien d'autre. Or
# ce qu'on veut souvent savoir, c'est comment **le dessin réel** sort : un
# logo se bouche, un texte de 1,2 mm devient illisible, une contre-forme
# se referme. Aucun carré ne le montre.
#
# Une case peut donc porter n'importe quel dessin — un DXF, ou la
# sélection en cours, transformée en coupon d'un clic droit. Le motif est
# ramené à des polylignes, centré et normalisé : c'est exactement ce qui
# part à la gravure, donc ce qu'on lit sur la chute est ce qu'on aura sur
# la pièce.

#: Fraction de la case qu'un motif occupe. Le reste tient lieu de marge,
#: faute de quoi deux motifs voisins se touchent et l'on ne sait plus
#: lequel appartient à quelle case.
MOTIF_FILL = 0.9


def motif_from_shapes(shapes: list[Shape]) -> list:
    """Polylignes d'une sélection, centrées sur l'origine.

    Passe par `shape_polylines` — le même chemin qu'à l'export — de sorte
    que le coupon grave le dessin, et non une approximation de plus.
    """
    from . import geometry as G
    from .toolpath import group_zones, shape_polylines
    # un logo groupé garde ses trous : le pair-impair vaut entre membres
    zones = group_zones(shapes)
    polys = [list(p) for shape in shapes if shape.visible
             for p in shape_polylines(shape, zone=zones.get(shape.id))
             if len(p) >= 2]
    b = G.bounds(polys) if polys else None
    if b is None:
        return []
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return [G.translate(poly, -cx, -cy) for poly in polys]


def motif_from_file(path, units_mm: float | None = None) -> list:
    """Polylignes d'un fichier vectoriel, centrées.

    DXF, PDF, Illustrator, EPS — et CorelDRAW si un convertisseur est
    installé. Rend une liste vide si le fichier est illisible : un coupon
    sans motif reste un coupon, on ne l'interrompt pas pour cela.
    """
    from . import dxfimport
    try:
        shapes, _ = dxfimport.any_to_shapes(path, units_mm=units_mm)
    except Exception:
        return []
    return motif_from_shapes(list(shapes))


#: Ancien nom, gardé le temps que plus rien ne l'appelle.
motif_from_dxf = motif_from_file


def motif_size(motif: list) -> tuple[float, float]:
    """Encombrement d'un motif, en mm. (0, 0) s'il est vide."""
    from . import geometry as G
    b = G.bounds(motif) if motif else None
    if b is None:
        return 0.0, 0.0
    return b[2] - b[0], b[3] - b[1]


def _motif_cell(motif: list, cx: float, cy: float, cell_mm: float,
                recipe: Recipe, name: str) -> Shape:
    """Une case portant le motif, ajusté à la case et posé en son centre.

    Le facteur est **le même dans les deux axes** : un logo étiré ne dit
    plus rien du logo qu'on gravera.
    """
    from . import geometry as G
    largeur, hauteur = motif_size(motif)
    voulu = cell_mm * MOTIF_FILL
    facteur = min(voulu / largeur if largeur > 0 else 1.0,
                  voulu / hauteur if hauteur > 0 else 1.0)
    return Path(x=cx, y=cy, recipe=recipe, name=name,
                polylines=[G.scale(poly, facteur) for poly in motif])


def extent(shapes: list[Shape]):
    """Emprise réelle des formes d'un coupon, ou None."""
    from . import geometry as G
    from .toolpath import shape_polylines
    polys = [p for shape in shapes for p in shape_polylines(shape)]
    return G.bounds(polys) if polys else None

# ---------------------------------------------------------------------------
# Dialogue
# ---------------------------------------------------------------------------

#: Paramètres qu'on peut **imposer** à toutes les cases, avec leurs bornes.
#:
#: Ce sont les mêmes que les axes, vus de l'autre côté : ce qui ne varie
#: pas doit tout de même pouvoir se régler. Sans cela, un essai en
#: puissance se faisait à la vitesse de la recette de départ, qu'il fallait
#: aller modifier ailleurs avant de revenir ici.
FIXED: tuple[tuple[str, float, float, int, bool], ...] = (
    # champ, mini, maxi, décimales, réservé au mode expert
    ('power_percent', 0.0, 100.0, 1, False),
    ('speed_mm_min', 1.0, 200000.0, 0, False),
    ('hatch_mm', 0.0, 5.0, 3, False),
    ('passes', 1, 50, 0, False),
    ('depth_total_mm', 0.0, 5.0, 3, False),
    ('frequency_khz', 1.0, 1300.0, 1, True),
    ('pulse_width_ns', 1, 65535, 0, True),
)


class CouponDialog(QDialog):
    """Réglage d'un coupon : recette de départ, deux axes, paramètres fixes.

    Le dialogue annonce en permanence ce qui va être produit — nombre de
    cases et emprise — parce qu'un coupon trop grand pour le champ ne se
    découvrirait, sinon, qu'au moment de l'export.

    Il se rouvre sur les réglages d'un coupon déjà produit : `settings`
    prime alors sur la mémoire de session. Un coupon n'est pas un dessin
    qu'on retouche à la souris, c'est le résultat d'un formulaire — et ce
    formulaire doit rester accessible.
    """

    def __init__(self, parent, recipe: Recipe,
                 library: list[Recipe] | None = None,
                 settings: dict | None = None,
                 expert: bool = False, motif: list | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Coupon d\'essai — modifier' if settings
                            else 'Coupon d\'essai')
        self.setMinimumWidth(460)
        self._library = list(library or [recipe])
        self._expert = bool(expert)
        # Motif des cases : polylignes centrées, ou rien pour un carré.
        # Rangé avec les réglages, il se régénère à la réouverture sans
        # qu'on ait à retrouver le DXF d'origine.
        self._motif = list(motif or [])
        self._motif_nom = 'sélection' if motif else ''
        if not self._motif and settings and settings.get('motif'):
            self._motif = [list(map(tuple, poly))
                           for poly in settings['motif']]
            self._motif_nom = str(settings.get('source', '')) or 'motif'
        # Un essai se fait rarement en une fois : la deuxième plaque affine
        # la première. On rouvre donc sur les réglages du coupon en cours
        # d'édition s'il y en a un, sur ceux du dernier sinon.
        self._memoire = dict(session.coupon_defaults())
        if settings:
            self._memoire.update({k: v for k, v in settings.items()
                                  if k in self._memoire or k == 'fixed'})
        retenue = self._memoire.get('recipe')
        if retenue:
            recipe = next((p for p in self._library if p.name == retenue),
                          recipe)

        # Le formulaire a grandi — deux axes, sept paramètres fixes, cinq
        # options — au point de dépasser un écran FullHD : les boutons
        # passaient sous la barre des tâches, hors d'atteinte. Le corps
        # défile, le résumé et les boutons restent visibles quoi qu'il
        # arrive.
        dehors = QVBoxLayout(self)
        dehors.setContentsMargins(0, 0, 0, 0)
        corps = QWidget()
        layout = QVBoxLayout(corps)
        defile = QScrollArea()
        defile.setWidgetResizable(True)
        defile.setFrameShape(QFrame.NoFrame)
        defile.setWidget(corps)
        dehors.addWidget(defile, 1)

        layout.addWidget(QLabel(
            'Grave la même case plusieurs fois en ne changeant qu\'un ou '
            'deux paramètres,<br>et grave les valeurs à côté. À lire sur '
            'une chute de la matière visée.'))

        form = QFormLayout()
        self.w_recipe = Combo()
        # rangée comme la page des process : racine, puis dossiers
        recipes.fill_combo(self.w_recipe, self._library)
        index = recipes.combo_index(self.w_recipe, recipe,
                                    same=lambda a, b: a.name == b.name)
        if index < 0:
            index = recipes.combo_index(self.w_recipe, self._library[0]) \
                if self._library else 0
        self.w_recipe.setCurrentIndex(max(index, 0))
        self.w_recipe.currentIndexChanged.connect(self._recipe_changed)
        form.addRow('Process de départ', self.w_recipe)

        motif_ligne = QWidget()
        motif_boite = QVBoxLayout(motif_ligne)
        motif_boite.setContentsMargins(0, 0, 0, 0)
        self.w_motif = QLabel('')
        self.w_motif.setWordWrap(True)
        motif_boite.addWidget(self.w_motif)
        boutons_motif = QWidget()
        rangee_motif = QHBoxLayout(boutons_motif)
        rangee_motif.setContentsMargins(0, 0, 0, 0)
        self.w_motif_dxf = QPushButton('Depuis un fichier…')
        self.w_motif_dxf.setToolTip(
            'Chaque case grave ce dessin au lieu d\'un carré : c\'est le '
            'seul moyen\nde voir comment le motif réel sort sous chaque '
            'jeu de paramètres.')
        self.w_motif_dxf.clicked.connect(self._pick_motif)
        self.w_motif_clear = QPushButton('Revenir au carré')
        self.w_motif_clear.clicked.connect(self._drop_motif)
        rangee_motif.addWidget(self.w_motif_dxf)
        rangee_motif.addWidget(self.w_motif_clear)
        motif_boite.addWidget(boutons_motif)
        form.addRow('Motif des cases', motif_ligne)
        layout.addLayout(form)

        self.w_x = _AxisRow(self, 'Axe X (colonnes)', 'x', self._memoire)
        self.w_y = _AxisRow(self, 'Axe Y (lignes)', 'y', self._memoire)
        layout.addWidget(self.w_x)
        layout.addWidget(self.w_y)

        self.w_fixed = _FixedBox(self, recipe,
                                 self._memoire.get('fixed') or {})
        layout.addWidget(self.w_fixed)

        grid = QFormLayout()
        self.w_cell = Spin(self._memoire['cell_mm'], 1.0, 60.0, 1.0, 2, ' mm')
        self.w_gap = Spin(self._memoire['gap_mm'], 0.0, 40.0, 0.5, 2, ' mm')
        self.w_label = Spin(self._memoire['label_mm'], 0.5, 10.0, 0.1, 2,
                            ' mm')
        self.w_hatch = QCheckBox('Remplir les cases (hachurage)')
        self.w_hatch.setChecked(bool(self._memoire['hatched']))
        self.w_hatch.setToolTip(
            'Décoché, seul le contour est tracé : plus rapide, mais le '
            'rendu de surface\nne se juge que sur une case remplie.')
        self.w_hatch_labels = QCheckBox('Remplir les étiquettes')
        self.w_hatch_labels.setChecked(bool(self._memoire['labels_hatched']))
        self.w_hatch_labels.setToolTip(
            'Indépendant des cases. Sur un métal clair, un texte filaire '
            'de 1,8 mm\ndisparaît à la lecture ; sur un cuir sombre, le '
            'hachurer le brûle.')
        self.w_title = QCheckBox('Graver le titre')
        self.w_title.setChecked(bool(self._memoire['show_title']))
        self.w_title.setToolTip(
            'Ligne d\'en-tête rappelant la process et les deux axes.')
        self.w_xlab = QCheckBox('Graver les étiquettes de colonnes')
        self.w_xlab.setChecked(bool(self._memoire['show_x_labels']))
        self.w_ylab = QCheckBox('Graver les étiquettes de lignes')
        self.w_ylab.setChecked(bool(self._memoire['show_y_labels']))
        for case in (self.w_xlab, self.w_ylab):
            case.setToolTip(
                'Sans elles, la chute ne dit plus quelle case portait '
                'quelle valeur.\nÀ ne couper que si la place manque '
                'vraiment.')
        grid.addRow('Côté d\'une case', self.w_cell)
        grid.addRow('Écart entre cases', self.w_gap)
        grid.addRow('Hauteur des étiquettes', self.w_label)
        grid.addRow('', self.w_hatch)
        grid.addRow('', self.w_hatch_labels)
        grid.addRow('', self.w_title)
        grid.addRow('', self.w_xlab)
        grid.addRow('', self.w_ylab)
        layout.addLayout(grid)

        layout.addStretch(1)
        self.w_note = QLabel()
        self.w_note.setWordWrap(True)
        self.w_note.setContentsMargins(9, 0, 9, 0)
        dehors.addWidget(self.w_note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            'Régénérer' if settings else 'Générer')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.setContentsMargins(9, 0, 9, 9)
        dehors.addWidget(buttons)

        for widget in (self.w_cell, self.w_gap, self.w_label):
            widget.valueChanged.connect(lambda *_: self._update_note())
        self.w_hatch.toggled.connect(lambda *_: self._update_note())
        for case in (self.w_hatch_labels, self.w_title, self.w_xlab,
                     self.w_ylab):
            case.toggled.connect(lambda *_: self._update_note())
        self._show_motif()
        self._recipe_changed()
        fit_to_screen(self, content=corps)

    # -- réactions ---------------------------------------------------------

    def recipe(self) -> Recipe:
        choisie = self.w_recipe.currentData()
        return choisie if choisie is not None else self._library[0]

    def axes(self) -> tuple[str, str]:
        return self.w_x.values()[0], self.w_y.values()[0]

    def _recipe_changed(self) -> None:
        """Les bornes suivent la process : on encadre sa valeur courante."""
        recipe = self.recipe()
        self.w_x.suggest(recipe)
        self.w_y.suggest(recipe)
        self.w_fixed.follow(recipe)
        self._update_note()

    def axis_changed(self) -> None:
        """Un paramètre qui varie ne se fixe plus : son champ se grise."""
        self.w_fixed.refresh_enabled()
        self._update_note()

    def _show_motif(self) -> None:
        if not self._motif:
            self.w_motif.setText(
                'carré plein — juge le rendu de surface')
            self.w_motif_clear.setEnabled(False)
            return
        largeur, hauteur = motif_size(self._motif)
        self.w_motif.setText(
            f'<b>{self._motif_nom}</b> — {len(self._motif)} tracé(s), '
            f'{largeur:.1f} × {hauteur:.1f} mm, ajusté à chaque case')
        self.w_motif_clear.setEnabled(True)

    def _pick_motif(self) -> None:
        from . import dxfimport
        chemin, _ = QFileDialog.getOpenFileName(
            self, 'Motif des cases', session.start_folder('dxf'),
            dxfimport.FILE_FILTER)
        if not chemin:
            return
        motif = motif_from_file(chemin)
        if not motif:
            self.w_motif.setText(
                '<b>Fichier illisible ou vide</b> — la case reste carrée')
            return
        self._motif = motif
        self._motif_nom = pathlib.Path(chemin).stem
        session.remember_file('dxf', chemin)
        self._show_motif()
        self._update_note()

    def _drop_motif(self) -> None:
        self._motif = []
        self._motif_nom = ''
        self._show_motif()
        self._update_note()

    def _update_note(self) -> None:
        shapes = self.shapes()
        cases = sum(1 for s in shapes if not isinstance(s, Text))
        b = extent(shapes)
        if b is None:
            self.w_note.setText('<b>Rien à générer.</b>')
            return
        w, h = b[2] - b[0], b[3] - b[1]
        tient = w <= FIELD_W_MM and h <= FIELD_H_MM
        etat = ('' if tient else
                f'<br><b>Plus grand que le champ {FIELD_W_MM:.0f} × '
                f'{FIELD_H_MM:.0f} mm</b> — réduisez la case, l\'écart ou '
                f'le nombre de valeurs.')
        self.w_note.setText(
            f'{cases} case(s) · emprise {w:.1f} × {h:.1f} mm{etat}')

    # -- résultat ----------------------------------------------------------

    def settings(self) -> dict:
        """Tout ce qui décrit ce coupon, prêt à être conservé et rejoué."""
        x_field, x_from, x_to, x_count = self.w_x.values()
        y_field, y_from, y_to, y_count = self.w_y.values()
        return {
            'recipe': self.recipe().name,
            'x_field': x_field, 'x_from': x_from, 'x_to': x_to,
            'x_count': x_count, 'x_couples': self.w_x.couples_text(),
            'y_field': y_field, 'y_from': y_from, 'y_to': y_to,
            'y_count': y_count, 'y_couples': self.w_y.couples_text(),
            'cell_mm': self.w_cell.value(), 'gap_mm': self.w_gap.value(),
            'label_mm': self.w_label.value(),
            'hatched': self.w_hatch.isChecked(),
            'labels_hatched': self.w_hatch_labels.isChecked(),
            'show_title': self.w_title.isChecked(),
            'show_x_labels': self.w_xlab.isChecked(),
            'show_y_labels': self.w_ylab.isChecked(),
            'fixed': self.w_fixed.values(),
            'source': self._motif_nom,
            'motif': [[list(p) for p in poly] for poly in self._motif],
        }

    def shapes(self) -> list[Shape]:
        """Les formes du coupon tel qu'il est réglé à l'instant."""
        reglages = self.settings()
        reglages.pop('recipe', None)
        reglages['x_couples'] = reglages.pop('x_couples', '').split()
        reglages['y_couples'] = reglages.pop('y_couples', '').split()
        reglages.pop('source', None)
        reglages['motif'] = self._motif
        return build(self.recipe(), **reglages)


class _FixedBox(QGroupBox):
    """Les paramètres qui ne varient pas, mais qui se règlent quand même.

    Un champ porté par un axe est grisé et annonce sur quel axe il varie :
    le formulaire dit alors de lui-même pourquoi il ne se règle pas ici.

    **Fréquence et durée d'impulsion n'apparaissent qu'en mode expert.**
    Ce sont les deux réglages qu'un opérateur ne doit pas pouvoir déplacer
    par mégarde, et la règle vaut ici comme dans l'éditeur de recette.
    """

    def __init__(self, dialog: CouponDialog, recipe: Recipe,
                 memoire: dict) -> None:
        super().__init__('Paramètres fixes — appliqués à toutes les cases')
        self._dialog = dialog
        self._rows: dict[str, tuple] = {}
        form = QFormLayout(self)

        for champ, bas, haut, decimales, reserve in FIXED:
            if reserve and not dialog._expert:
                continue
            depart = memoire.get(champ, getattr(recipe, champ, 0.0) or 0.0)
            unit = axis_unit(champ)
            facteur = axis_scale(champ) or 1.0
            if champ in _INTEGERS:
                widget = IntSpin(int(depart), int(bas), int(haut), 1, unit)
            else:
                widget = Spin(float(depart) * facteur, bas * facteur,
                              haut * facteur, 1.0, decimales, unit)
            note = QLabel('')
            note.setStyleSheet(theme.css())
            form.addRow(axis_label(champ), widget)
            form.addRow('', note)
            widget.valueChanged.connect(lambda *_: dialog._update_note())
            self._rows[champ] = (widget, note)
        self.refresh_enabled()

    def follow(self, recipe: Recipe) -> None:
        """Reprend les valeurs de la process choisie, sans écraser un axe."""
        x_field, y_field = self._dialog.axes()
        for champ, (widget, _) in self._rows.items():
            if champ in (x_field, y_field):
                continue
            widget.blockSignals(True)
            widget.setValue((getattr(recipe, champ, 0.0) or 0.0)
                            * (axis_scale(champ) or 1.0))
            widget.blockSignals(False)
        self.refresh_enabled()

    def refresh_enabled(self) -> None:
        x_field, y_field = self._dialog.axes()
        for champ, (widget, note) in self._rows.items():
            axe = ('X' if champ == x_field
                   else 'Y' if champ == y_field else '')
            widget.setEnabled(not axe)
            note.setText(f'varie sur l\'axe {axe}' if axe else '')
            note.setVisible(bool(axe))

    def values(self) -> dict:
        """Les valeurs imposées, hors paramètres portés par un axe."""
        x_field, y_field = self._dialog.axes()
        return {champ: (int(w.value()) if champ in _INTEGERS
                        else w.value() / (axis_scale(champ) or 1.0))
                for champ, (w, _) in self._rows.items()
                if champ not in (x_field, y_field)}


class _AxisRow(QGroupBox):
    """Un axe : le paramètre qui varie, ses bornes, son nombre de valeurs."""

    def __init__(self, dialog: CouponDialog, title: str, prefixe: str,
                 memoire: dict) -> None:
        super().__init__(title)
        self._dialog = dialog
        self._prefixe = prefixe
        field = str(memoire.get(f'{prefixe}_field', ''))
        form = QFormLayout(self)

        self.w_field = Combo()
        for key, label, unit, _ in AXES:
            if key in _EXPERT_AXES and not dialog._expert:
                continue
            self.w_field.addItem(f'{label} {unit}'.strip(), key)
        index = self.w_field.findData(field)
        self.w_field.setCurrentIndex(max(0, index))
        self.w_field.currentIndexChanged.connect(self._field_changed)
        form.addRow('Paramètre', self.w_field)

        facteur = axis_scale(field) or 1.0
        self.w_from = Spin(float(memoire.get(f'{prefixe}_from', 0.0)) * facteur,
                           -1e6, 1e6, 1.0, 4)
        self.w_to = Spin(float(memoire.get(f'{prefixe}_to', 0.0)) * facteur,
                         -1e6, 1e6, 1.0, 4)
        self.w_count = IntSpin(int(memoire.get(f'{prefixe}_count', 5)), 1, 20)
        self._premier = True
        self._l_from = QLabel('De')
        self._l_to = QLabel('À')
        self._l_count = QLabel('Nombre de valeurs')
        form.addRow(self._l_from, self.w_from)
        form.addRow(self._l_to, self.w_to)
        form.addRow(self._l_count, self.w_count)
        for widget in (self.w_from, self.w_to, self.w_count):
            widget.valueChanged.connect(lambda *_: dialog._update_note())

        # --- couples fréquence / impulsion ---
        #
        # Un axe de couples ne se répartit pas entre deux bornes : on coche
        # les paires voulues dans la table. Les bornes disparaissent alors
        # du formulaire, elles n'auraient plus de sens.
        self.w_couples = QListWidget()
        self.w_couples.setSelectionMode(QListWidget.NoSelection)
        self.w_couples.setMaximumHeight(150)
        self.w_couples.itemChanged.connect(lambda *_: dialog._update_note())
        self._l_couples = QLabel('Couples')
        form.addRow(self._l_couples, self.w_couples)
        self.w_manage = QPushButton('Gérer les couples…')
        self.w_manage.setToolTip(
            'Ajoute au poste les couples relevés sur la source, ou repris '
            'du magasin de la machine.')
        self.w_manage.clicked.connect(self._manage)
        self._l_manage = QLabel('')
        form.addRow(self._l_manage, self.w_manage)
        self._fill_couples(str(memoire.get(f'{prefixe}_couples', '')))

    def values(self) -> tuple[str, float, float, int]:
        """Bornes **en unités du modèle** : la saisie est en m/min, pas
        le reste du programme."""
        champ = self.w_field.currentData() or ''
        facteur = axis_scale(champ) or 1.0
        return (champ, self.w_from.value() / facteur,
                self.w_to.value() / facteur, int(self.w_count.value()))

    # -- couples -----------------------------------------------------------

    def _fill_couples(self, retenus: str = '') -> None:
        """Remplit la table des couples, en cochant ceux déjà choisis."""
        from . import couples as _c
        coches = {m for m in str(retenus or '').split() if m}
        self.w_couples.blockSignals(True)
        self.w_couples.clear()
        for couple in _c.available(self._dialog._expert):
            item = QListWidgetItem(couple.label())
            item.setData(Qt.ItemDataRole.UserRole, couple.key())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if couple.key() in coches
                               else Qt.Unchecked)
            self.w_couples.addItem(item)
        if not coches and self.w_couples.count():
            # rien de retenu : tout cocher vaut mieux qu'un coupon vide
            for i in range(self.w_couples.count()):
                self.w_couples.item(i).setCheckState(Qt.Checked)
        self.w_couples.blockSignals(False)

    def couples(self) -> list[str]:
        """Les couples cochés, en « 1300-2 »."""
        return [self.w_couples.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.w_couples.count())
                if self.w_couples.item(i).checkState() == Qt.Checked]

    def couples_text(self) -> str:
        return ' '.join(self.couples())

    def _manage(self) -> None:
        from .couples import CoupleManager
        garde = self.couples_text()
        fenetre = CoupleManager(self)
        if fenetre.exec() == QDialog.DialogCode.Accepted:
            self._fill_couples(garde)
            self._dialog._update_note()

    def _field_changed(self) -> None:
        self._premier = False
        self.suggest(self._dialog.recipe())
        self._dialog.axis_changed()

    def suggest(self, recipe: Recipe) -> None:
        """Bornes de départ encadrant la valeur de la recette choisie.

        Proposer 20…100 % de puissance quand la recette en emploie 12 fait
        perdre le premier coupon : les bornes utiles sont autour du point
        de fonctionnement connu, pas au milieu de l'échelle.
        """
        field = self.w_field.currentData() or ''
        actif = bool(field)
        couple = field == COUPLE_AXIS
        for widget, etiquette in ((self.w_from, self._l_from),
                                  (self.w_to, self._l_to),
                                  (self.w_count, self._l_count)):
            widget.setEnabled(actif and not couple)
            widget.setVisible(not couple)
            etiquette.setVisible(not couple)
        for widget in (self.w_couples, self.w_manage, self._l_couples,
                       self._l_manage):
            widget.setVisible(couple)
        # Le gestionnaire est **réservé au mode expert** : en mode normal,
        # seule la table constructeur est proposée, et elle ne se modifie
        # pas depuis un poste d'atelier.
        self.w_manage.setEnabled(couple and self._dialog._expert)
        if couple:
            self._fill_couples(self.couples_text())
            return
        if not actif:
            return
        unit = axis_unit(field)
        for widget in (self.w_from, self.w_to):
            widget.setUnit(unit)
        if self._premier:
            # à l'ouverture, les bornes mémorisées priment : l'opérateur
            # vient de les choisir au coupon précédent
            self._premier = False
            return
        courant = float(getattr(recipe, field, 0.0) or 0.0)
        if field in _INTEGERS:
            bas, haut = max(1.0, courant - 2), max(2.0, courant + 2)
        elif field == 'power_percent':
            bas = max(1.0, courant * 0.4)
            haut = min(100.0, max(courant, 20.0) * 1.6)
        elif courant > 0:
            bas, haut = courant * 0.5, courant * 1.5
        else:
            bas, haut = _FALLBACK.get(field, (1.0, 10.0))
        facteur = axis_scale(field) or 1.0
        self.w_from.blockSignals(True)
        self.w_to.blockSignals(True)
        self.w_from.setValue(round(bas * facteur, 4))
        self.w_to.setValue(round(haut * facteur, 4))
        self.w_from.blockSignals(False)
        self.w_to.blockSignals(False)
