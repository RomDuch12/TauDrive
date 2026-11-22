"""Bibliothèque de recettes et mode expert / Recipe library and expert mode.

Une **recette** est un jeu de paramètres laser complet : c'est
l'équivalent d'un *utensile* Cielle, et c'est elle qui décide du numéro
d'outil `T<n>` émis dans l'ISO.

Deux paramètres — **fréquence** et **durée d'impulsion** — ne sont
modifiables qu'en mode expert. Ce ne sont pas des réglages de confort :
mal choisis sur une source MOPA, ils dégradent la gravure et, à forte
énergie par impulsion, la source elle-même. Le mode expert est déverrouillé
par un code, retenu pour la durée de la session seulement.

La bibliothèque locale vit dans le dossier de configuration de
l'utilisateur. Elle vit sur le poste, et se porte sur un autre par les
boutons *Exporter…* / *Importer…* du gestionnaire — un fichier
`.process.json`, voir `echange` — ou, avec tout le reste, par
*Paramètres ▸ Exporter les réglages*.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QFrame, QScrollArea,
                               QFormLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import theme, wobble
from .model import (RECIPE_LIBRARY, SPEED_FROM_DISPLAY,
                    SPEED_TO_DISPLAY, SPEED_UNIT, Recipe, default_recipe,
                    factory_recipes, recipe_from_dict, recipe_to_dict,
                    set_recipe_library)
from .widgets import Combo, IntSpin, Spin

#: Code de déverrouillage du mode expert.
EXPERT_CODE = '1664'

_expert = False


def expert() -> bool:
    """Vrai si le mode expert est déverrouillé pour cette session."""
    return _expert


def unlock(parent=None) -> bool:
    """Demande le code et déverrouille le mode expert. Rend l'état obtenu.

    Le code n'est jamais mémorisé sur le disque : le mode expert se
    redemande à chaque lancement, ce qui est le comportement voulu sur un
    poste d'atelier partagé.
    """
    global _expert
    if _expert:
        return True
    code, ok = QInputDialog.getText(
        parent, 'Mode expert',
        'Fréquence et durée d\'impulsion agissent directement sur la\n'
        'source MOPA. Code d\'accès :', QLineEdit.Password)
    if not ok:
        return False
    if code.strip() != EXPERT_CODE:
        QMessageBox.warning(parent, 'Mode expert', 'Code incorrect.')
        return False
    _expert = True
    return True


def lock() -> None:
    global _expert
    _expert = False


# --------------------------------------------------------------------------
# Persistance locale
# --------------------------------------------------------------------------

#: Nom du fichier de bibliothèque, et les noms qu\'il a portés.
#:
#: **Le nom du fichier ne suit pas l\'habillage de l\'interface.**
#: Quand « recette » est devenue « process » à l\'écran, ce fichier a
#: suivi par mégarde : les postes qui avaient une bibliothèque ne la
#: trouvaient plus, et repartaient sur les process d\'usine — sans que
#: rien ne l\'annonce, puisqu\'une bibliothèque absente est un cas
#: normal au premier lancement.
#:
#: Le nom canonique est donc figé, et les anciens sont **relus** : une
#: bibliothèque écrite sous n\'importe lequel est retrouvée, puis
#: réécrite sous le nom canonique.
LIBRARY_NAME = 'recettes.json'
LEGACY_NAMES = ('recipes.json', 'process.json')


def library_dir() -> pathlib.Path:
    """Dossier des réglages du poste.

    Dépend de l\'identité Qt de l\'application — organisation et
    nom — posée dans `app.main`. Sans elle, Qt retombe sur le nom de
    l\'exécutable, et la bibliothèque atterrirait ailleurs selon
    qu\'on lance le source ou le figé.
    """
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(
        QStandardPaths.AppConfigLocation) or str(pathlib.Path.home())
    return pathlib.Path(base)


def library_path() -> pathlib.Path:
    """Fichier de la bibliothèque locale, **ancien nom compris**.

    Rend le fichier canonique s\'il existe ; sinon le premier ancien
    nom trouvé, pour qu\'une bibliothèque écrite par une version
    précédente ne soit jamais perdue ; sinon le canonique, qui sera créé.
    """
    dossier = library_dir()
    canonique = dossier / LIBRARY_NAME
    if canonique.exists():
        return canonique
    for ancien in LEGACY_NAMES:
        candidat = dossier / ancien
        if candidat.exists():
            return candidat
    return canonique


def load_local() -> list[Recipe]:
    """Bibliothèque locale, ou les préréglages d'usine si elle est absente."""
    path = library_path()
    if not path.exists():
        return list(factory_recipes())
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        raw = data.get('recipes', data) if isinstance(data, dict) else data
        recipes = [recipe_from_dict(r) for r in raw if isinstance(r, dict)]
    except (OSError, ValueError, TypeError):
        return list(factory_recipes())
    return recipes or list(factory_recipes())


def save_local(recipes: list[Recipe]) -> None:
    """Range la bibliothèque, **toujours sous le nom canonique**.

    Écrite par un fichier temporaire puis renommée : une coupure de
    courant au milieu de l\'écriture laisserait sinon une bibliothèque
    tronquée, et l\'atelier repartirait aux process d\'usine.

    Une bibliothèque trouvée sous un ancien nom est ainsi **migrée** au
    premier enregistrement : l\'ancien fichier est laissé en place,
    inutile mais inoffensif, plutôt qu\'effacé — on ne supprime pas
    les données de quelqu\'un pour faire propre.
    """
    dossier = library_dir()
    dossier.mkdir(parents=True, exist_ok=True)
    path = dossier / LIBRARY_NAME
    payload = {'recipes': [recipe_to_dict(r) for r in recipes]}
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding='utf-8')
    tmp.replace(path)


def install_local() -> None:
    """Charge la bibliothèque locale dans le modèle, au démarrage."""
    set_recipe_library(load_local())


# --------------------------------------------------------------------------
# Gestionnaire
# --------------------------------------------------------------------------

def unique_name(base: str, existants) -> str:
    """Nom libre dérivé de `base` : « Laiton », « Laiton 2 », « Laiton 3 »…

    Enregistrer une recette personnalisée **crée une entrée**, elle
    n'écrase pas celle dont on est parti. On affine une recette en
    partant d'une autre ; perdre l'ancienne parce qu'on a gardé son nom
    serait perdre le point de comparaison au moment précis où il sert.
    """
    pris = {r.name for r in existants}
    racine = (base or 'process').strip() or 'process'
    if racine not in pris:
        return racine
    # « Laiton 2 » plutôt que « Laiton (copie) » : le rang se relit, et
    # deux affinages successifs se suivent dans la liste
    import re as _re
    nu = _re.sub(r'\s+\d+$', '', racine)
    for rang in range(2, 1000):
        essai = f'{nu} {rang}'
        if essai not in pris:
            return essai
    return f'{nu} {len(pris) + 1}'


def grouped(library) -> list[tuple[str, list]]:
    """Les process par dossier, **dans l'ordre du gestionnaire** : la racine
    d'abord, puis les dossiers par ordre alphabétique, et dans chacun
    l'ordre de la bibliothèque. C'est l'ordre que l'œil a appris dans la
    page des process ; toute liste où l'on en choisit une le reprend.
    """
    par_dossier: dict[str, list] = {}
    for r in library:
        par_dossier.setdefault((r.folder or '').strip(), []).append(r)
    ordre = sorted(par_dossier, key=lambda d: (d != '', d.lower()))
    return [(d, par_dossier[d]) for d in ordre]


def fill_combo(combo, library, *, texte=None, first=None) -> None:
    """Remplit une liste déroulante **comme le gestionnaire range**.

    Les process de la racine viennent en tête ; chaque dossier suit,
    en gras et non sélectionnable, ses process en retrait dessous. La
    liste plate d'avant, préfixée du dossier (« Laiton / Laiton fin »),
    n'avait ni le même ordre ni la même forme que la page des process :
    on cherchait deux fois la même chose de deux façons.

    `first` — un `(libellé, valeur)` posé avant tout : « (personnalisée) »,
    « — (process mêlées) ». `texte(r)` — ce qu'affiche une process.

    Les valeurs se relisent par `itemData(i)` ; les en-têtes rendent
    `None`, comme l'entrée `first` peut le faire : c'est à l'appelant de
    ne jamais prendre un en-tête pour un choix.
    """
    from PySide6.QtGui import QStandardItem, QStandardItemModel
    texte = texte or (lambda r: r.name)
    model = QStandardItemModel(combo)
    if first is not None:
        libelle, valeur = first
        item = QStandardItem(libelle)
        item.setData(valeur, Qt.UserRole)
        model.appendRow(item)
    for dossier, membres in grouped(library):
        if dossier:
            tete = QStandardItem(f'{dossier}  ({len(membres)})')
            tete.setSelectable(False)
            tete.setEnabled(False)
            police = tete.font()
            police.setBold(True)
            tete.setFont(police)
            tete.setData(None, Qt.UserRole)
            model.appendRow(tete)
        for r in membres:
            item = QStandardItem(('    ' if dossier else '') + texte(r))
            item.setData(r, Qt.UserRole)
            item.setToolTip(_summary(r))
            model.appendRow(item)
    combo.setModel(model)


def combo_index(combo, recipe, *, same=None) -> int:
    """Rang de `recipe` dans une liste remplie par `fill_combo`, -1 sinon.

    `same(a, b)` dit si deux process sont la même ; par défaut, égalité
    de tous les champs. Les en-têtes et l'entrée `first` sont ignorés.
    """
    same = same or (lambda a, b: a == b)
    for i in range(combo.count()):
        donnee = combo.itemData(i)
        if donnee is not None and same(donnee, recipe):
            return i
    return -1


def label(recipe: Recipe) -> str:
    """Nom d'une process **précédé de son dossier**, partout où on la choisit.

    Le gestionnaire montrait le rangement, les listes de sélection non :
    « Laiton » y paraissait deux fois, une par dossier, sans rien pour les
    départager. Or c'est le dossier qui porte le sens — la matière, le
    client, la campagne d'essais. Il vient donc devant le nom dans toutes
    les listes où l'on désigne une process, et pas seulement là où on la
    range.
    """
    return f'{recipe.folder} / {recipe.name}' if recipe.folder else recipe.name


#: L'infobulle du style de remplissage, la même aux deux endroits.
FILL_STYLE_TIP = (
    'Hachures : la forme est balayée en rangées.\n'
    'Anneaux : des boucles parallèles au contour, de plus en plus '
    'rentrées.\nPas de demi-tour au bout des rangées — sur cette '
    'machine, chacun freine le miroir\ncomme un allumage : le '
    'DataMatrix dessiné de l’atelier passe de 8,4 s à 2,3 s\n'
    '(estimé, 100 m/min). Avec « Enchaîner », les anneaux se relient '
    'en spirale.\nL’aspect change : à valider sur coupon. Angle, '
    'rotation et croisement ne s’y appliquent pas.')


def _summary(recipe: Recipe, court: bool = False) -> str:
    '''Nom, outil, passes, profondeur, remplissage et oscillation.

    La liste n'affichait que le nom, et tout le reste se cachait dans une
    infobulle. Deux process ne différant que par leur profondeur étaient
    alors indiscernables — or c'est exactement ce qui distingue une
    gravure d'un évidement. Le remplissage et l'oscillation les
    rejoignent : ce sont eux qui font la différence entre un contour et
    une surface pleine, et entre un trait fin et une bande.

    `court` omet le dossier — sous une branche qui le porte déjà, le
    répéter donnerait « Laiton / Laiton fin » sur deux niveaux.
    '''
    detail = f'T{recipe.tool_number}'
    if recipe.passes > 1:
        pas = recipe.depth_step()
        detail += (f' · {recipe.passes} passes'
                   + (f' de {pas * 1000:g} µm' if pas > 0 else ' en surface'))
    if recipe.hatch_mm > 0:
        detail += f' · rempli {recipe.hatch_mm:g}'
        if getattr(recipe, 'fill_style', 'hatch') == 'rings':
            detail += ' en anneaux'
        elif recipe.hatch_cross:
            detail += '✕'
    if getattr(recipe, 'link_paths', False):
        detail += ' · enchaîné'
    if recipe.wobble != 'none' and recipe.wobble_amp_mm > 0:
        detail += f' · osc {recipe.wobble_amp_mm:g}'
    if recipe.treatment is not None:
        detail += ' · traité'
    nom = recipe.name if court else label(recipe)
    return f'{nom}   [{detail}]'


class RecipeManager(QWidget):
    """Création, modification, duplication et suppression des recettes.

    **Un panneau, pas une fenêtre.** Régler une recette demande de voir le
    dessin sur lequel elle s'applique ; une fenêtre modale le cache et
    oblige à la refermer pour vérifier. Le panneau vit en colonne 2, à
    côté du plan de travail.

    L'enregistrement devient donc explicite : le bouton *Enregistrer*
    range la bibliothèque, *Rétablir* la relit. Sans fenêtre à fermer, il
    n'y a plus de moment où l'on validerait sans le savoir.
    """

    saved = Signal(int)            # nombre de recettes rangées
    done = Signal()                # l'opérateur a fini de régler

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Gestionnaire de process')
        self.setMinimumWidth(340)
        self.recipes: list[Recipe] = list(RECIPE_LIBRARY) or list(factory_recipes())
        self._current = -1
        self._guard = False

        outer = QVBoxLayout(self)
        split = QHBoxLayout()
        outer.addLayout(split, 1)

        # --- colonne gauche : la liste ---
        left = QVBoxLayout()
        # Un arbre plutôt qu'une liste : les process se rangent par
        # dossier — la matière, le client, la campagne d'essais — et une
        # bibliothèque qui en compte trente sur un seul niveau ne se lit
        # plus. Les dossiers se replient ; l'état de chacun est retenu
        # d'un rechargement à l'autre, sinon régler une process
        # rouvrirait tout à chaque frappe.
        self.w_list = QTreeWidget()
        self.w_list.setHeaderHidden(True)
        self.w_list.setIndentation(14)
        self.w_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.w_list.currentItemChanged.connect(self._item_changed)
        left.addWidget(self.w_list, 1)
        #: Dossiers repliés, par nom. Vide = tout est déplié.
        self._replies: set = set()
        self.w_list.itemCollapsed.connect(self._fold_changed)
        self.w_list.itemExpanded.connect(self._fold_changed)
        # Deux boutons par ligne : en panneau ancré, quatre de front
        # se tronquaient en « Nouvell », « uplique », « enomm ».
        for paire in ((('Nouvelle', self._new), ('Dupliquer', self._copy)),
                      (('Renommer', self._rename),
                       ('Supprimer', self._remove))):
            row = QHBoxLayout()
            for label, slot in paire:
                b = QPushButton(label)
                b.clicked.connect(slot)
                row.addWidget(b)
            left.addLayout(row)
        row2 = QHBoxLayout()
        for label, slot, tip in (
                ('Monter', lambda: self._move(-1), 'Ordre de la liste'),
                ('Descendre', lambda: self._move(1), 'Ordre de la liste'),
                ('Usine', self._factory,
                 'Rétablit les process d\'usine : relevés machine et '
                 'matières')):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row2.addWidget(b)
        left.addLayout(row2)
        # D'un poste à l'autre : un fichier par bibliothèque, qu'on pose
        # sur une clé. L'archive complète des réglages reste la
        # sauvegarde ; ceci est le geste courant.
        row3 = QHBoxLayout()
        for label, slot, tip in (
                ('Importer…', self._import,
                 'Reprend des process d\'un fichier .process.json écrit '
                 'sur un autre poste.\nChaque entrée est montrée et '
                 'cochée avant d\'entrer.'),
                ('Exporter…', self._export,
                 'Écrit toute la bibliothèque dans un fichier '
                 '.process.json, à relire sur un autre poste.')):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row3.addWidget(b)
        left.addLayout(row3)
        holder = QWidget()
        holder.setLayout(left)
        holder.setMaximumWidth(300)
        split.addWidget(holder)

        # --- colonne droite : l'éditeur ---
        self.editor = QWidget()
        ed = QVBoxLayout(self.editor)
        ed.setContentsMargins(0, 0, 0, 0)

        g_id = QGroupBox('Identité')
        f = QFormLayout(g_id)
        theme.tidy_form(f)
        self.w_name = QLineEdit()
        self.w_name.textChanged.connect(self._edited)
        self.w_folder = QLineEdit()
        self.w_folder.setPlaceholderText('Laiton, Essais, Client X…')
        self.w_folder.setToolTip(
            'Dossier de rangement. Vide = à la racine.\n'
            'Une bibliothèque d\'atelier finit à cinquante entrées ; sans '
            'rangement,\non ne retrouve plus la process laiton parmi les '
            'essais.')
        self.w_folder.textChanged.connect(self._edited)
        self.w_tool = self._int(0, 999, 'Numéro d\'outil `T<n>` émis dans '
                                        'l\'ISO. Doit exister dans le magasin '
                                        'dbpunte.mag de la machine.')
        f.addRow('Nom', self.w_name)
        f.addRow('Dossier', self.w_folder)
        f.addRow('Outil', self.w_tool)
        ed.addWidget(g_id)

        g_laser = QGroupBox('Laser')
        f = QFormLayout(g_laser)
        theme.tidy_form(f)
        self.w_power = self._float(0, 100, ' %', 1)
        # saisie en m/min, modèle en mm/min
        self.w_speed = self._float(0.001, 500, ' ' + SPEED_UNIT,
                                   3, step=1.0)
        self.w_passes = self._int(1, 999, 'Nb_passe du magasin d\'outils : '
                                         'nombre de passages de la process')
        f.addRow('Puissance', self.w_power)
        f.addRow('Vitesse', self.w_speed)
        f.addRow('Nb passes', self.w_passes)
        ed.addWidget(g_laser)

        self.g_expert = QGroupBox('Impulsion — mode expert')
        f = QFormLayout(self.g_expert)
        theme.tidy_form(f)
        self.w_freq = self._float(1, 1300, ' kHz', 2, step=1.0)
        self.w_pulse = self._int(1, 65535, 'Durée d\'impulsion, en '
                                           'nanosecondes (source MOPA)')
        f.addRow('Fréquence', self.w_freq)
        f.addRow('Impulsion', self.w_pulse)
        self.w_lock = QLabel('')
        self.w_lock.setWordWrap(True)
        f.addRow('', self.w_lock)
        ed.addWidget(self.g_expert)

        g_depth = QGroupBox('Profondeur')
        f = QFormLayout(g_depth)
        theme.tidy_form(f)
        self.w_depth_mode = Combo()
        for value, label in (('step', 'pas imposé entre deux passes'),
                             ('total', 'profondeur finale visée')):
            self.w_depth_mode.addItem(label, value)
        self.w_depth_mode.setToolTip(
            'Une process à plusieurs passages grave chaque passage un cran\n'
            'plus bas. La machine emploie 4,673 µm par passe.')
        self.w_depth_mode.currentIndexChanged.connect(self._edited)
        self.w_depth_step = self._float(0, 5, ' mm', 4, step=0.001)
        self.w_depth_step.setToolTip(
            'Zpasse du magasin d\'outils : descente entre deux passes.\n'
            'La machine emploie 0,004673 mm sur le travail relevé.')
        self.w_depth_total = self._float(0, 20, ' mm', 3, step=0.01)
        f.addRow('Réglage', self.w_depth_mode)
        f.addRow('Profondeur / passe', self.w_depth_step)
        f.addRow('Profondeur totale', self.w_depth_total)
        self.w_depth_info = QLabel('')
        self.w_depth_info.setWordWrap(True)
        self.w_depth_info.setStyleSheet(theme.css('text_dim', 11))
        f.addRow('', self.w_depth_info)
        ed.addWidget(g_depth)

        g_treat = QGroupBox('Traitement du dessin')
        ft = QFormLayout(g_treat)
        theme.tidy_form(ft)
        self.w_treatment = Combo()
        self.w_treatment.setToolTip(
            'Cadre, marge, offset et épaisseur appliqués au dessin '
            'avant la gravure.\n'
            'Les valeurs sont figées dans la process : supprimer le '
            'modèle ne casse rien.')
        self.w_treatment.currentIndexChanged.connect(self._treatment_chosen)
        self.w_treat_info = QLabel('')
        self.w_treat_info.setWordWrap(True)
        self.w_treat_info.setStyleSheet(theme.css('text_dim', 11))
        ft.addRow('Modèle', self.w_treatment)
        ft.addRow('', self.w_treat_info)
        ed.addWidget(g_treat)

        # --- remplissage ---
        #
        # Les cinq réglages du remplissage, et non deux. Le pas et l'angle
        # y étaient seuls, si bien qu'une process enregistrée depuis ce
        # panneau repartait avec un croisement et un retrait aux valeurs
        # par défaut — alors que la colonne 1 les offrait sur la forme.
        # Deux formulaires pour le même objet ne peuvent pas montrer deux
        # choses différentes.
        g_hatch = QGroupBox('Remplissage')
        f = QFormLayout(g_hatch)
        theme.tidy_form(f)
        self.w_hatch = self._float(0, 5, ' mm', 3, step=0.01)
        self.w_hatch.setToolTip('Pas de remplissage. 0 = contour seul.')
        self.w_hangle = self._float(-180, 180, ' °', 1, step=15)
        self.w_hangle.setToolTip('Orientation des nappes.')
        self.w_hstep = self._float(0, 180, ' °', 1, step=15)
        self.w_hstep.setToolTip(
            'Angle ajouté au hachurage à chaque passe.\n'
            '0 : toutes les passes dans le même sens — les creux du '
            'premier passage\nguident le second et le fond sort strié. '
            '45 ou 90 croisent les trajectoires\net donnent un fond plat.')
        self.w_hcross = QCheckBox('Croisé (+90° dans la même passe)')
        self.w_hcross.setToolTip(
            'Deux nappes perpendiculaires au même Z : surface homogène en '
            'un seul passage,\npour deux fois le trajet. À distinguer de '
            'la rotation par passe, qui creuse.')
        self.w_hcross.toggled.connect(self._edited)
        self.w_link = QCheckBox('Enchaîner les tracés (moins d’allumages)')
        self.w_link.setToolTip(
            'Moins d’allumages du laser : les rangées d’une même île se '
            'gravent d’un trait,\nles fragments de contour qui se '
            'touchent sont joints, un code se remplit d’un tenant.\n'
            'Sur cette machine, c’est l’allumage qui coûte, pas la '
            'gravure : un DataMatrix\nhachuré passe de 2 666 à 503 '
            'allumages. Rien n’est gravé hors du dessin.')
        self.w_link.toggled.connect(self._edited)
        self.w_fill = Combo()
        self.w_fill.addItem('Hachures — rangées parallèles', 'hatch')
        self.w_fill.addItem('Anneaux — suivent le contour', 'rings')
        self.w_fill.setToolTip(FILL_STYLE_TIP)
        self.w_fill.currentIndexChanged.connect(self._fill_style_shown)
        self.w_fill.currentIndexChanged.connect(self._edited)
        self.w_hinset = self._float(0, 2, ' mm', 3, step=0.005)
        self.w_hinset.setToolTip(
            'Retrait du remplissage par rapport au contour.\n'
            'Le faisceau a une largeur et déborde d\'un demi-spot : '
            'rentrer de 0,015 mm\nmet le bord de la zone gravée '
            'exactement sur le contour.')
        f.addRow('Pas hachurage', self.w_hatch)
        f.addRow('Style', self.w_fill)
        f.addRow('Angle', self.w_hangle)
        f.addRow('Rotation / passe', self.w_hstep)
        f.addRow('', self.w_hcross)
        f.addRow('', self.w_link)
        f.addRow('Retrait', self.w_hinset)
        ed.addWidget(g_hatch)

        # --- oscillation du faisceau ---
        #
        # La machine ne l'offre pas : elle est faite dans la géométrie,
        # avant l'export. Une process qui la porte doit donc la porter
        # **enregistrée**, sans quoi elle se perd au premier rechargement.
        g_wob = QGroupBox('Oscillation du faisceau')
        fw = QFormLayout(g_wob)
        theme.tidy_form(fw)
        self.w_wob = Combo()
        for cle, nom, note in wobble.SHAPES:
            self.w_wob.addItem(f'{nom} — {note}' if note else nom, cle)
        self.w_wob.currentIndexChanged.connect(self._edited)
        self.w_wob.setToolTip(
            'Superpose une oscillation au déplacement : le trait '
            's\'élargit en un seul passage.')
        self.w_wamp = self._float(0, 5, ' mm', 3, step=0.01)
        self.w_wamp.setToolTip(
            'Amplitude. La bande gravée fait **deux fois** cela.')
        self.w_wpitch = self._float(0, 10, ' mm', 3, step=0.05)
        self.w_wpitch.setToolTip(
            'Avance par tour d\'oscillation.\n'
            'C\'est aussi ce qui fixe la cadence demandée au scanner : '
            'vitesse / pas.')
        self.w_wob_info = QLabel('')
        self.w_wob_info.setWordWrap(True)
        fw.addRow('Forme', self.w_wob)
        fw.addRow('Amplitude', self.w_wamp)
        fw.addRow('Pas oscillation', self.w_wpitch)
        fw.addRow('', self.w_wob_info)
        ed.addWidget(g_wob)
        ed.addStretch(1)
        # L'éditeur défile seul : la barre de boutons doit rester au bas du
        # panneau, atteignable quelle que soit la hauteur disponible. Une
        # zone défilante autour du tout aurait fait passer « Terminé » sous
        # la ligne de flottaison.
        defile = QScrollArea()
        defile.setWidgetResizable(True)
        defile.setFrameShape(QFrame.NoFrame)
        defile.setWidget(self.editor)
        split.addWidget(defile, 1)

        barre = QHBoxLayout()
        self.w_save = QPushButton('Enregistrer')
        self.w_save.setToolTip('Range la bibliothèque sur le poste et la '
                               'rend disponible aux formes.')
        self.w_save.clicked.connect(self._save)
        self.w_revert = QPushButton('Rétablir')
        self.w_revert.setToolTip('Relit la bibliothèque enregistrée et '
                                 'abandonne les modifications en cours.')
        self.w_revert.clicked.connect(self.reload)
        self.w_expert_button = QPushButton('Déverrouiller le mode expert')
        self.w_expert_button.clicked.connect(self._unlock)
        # « Terminé » rend les colonnes au dessin. Il est distinct
        # d'« Enregistrer » : on range une recette sans forcément avoir
        # fini de régler les autres.
        self.w_done = QPushButton('Terminé')
        self.w_done.setDefault(True)
        self.w_done.setToolTip('Revient au plan de travail. Les process '
                               'enregistrées sont conservées.')
        self.w_done.clicked.connect(self.done.emit)
        # Le guide des paramètres, à portée du réglage : c'est ici qu'on
        # se demande quelle durée d'impulsion la source tient, et non
        # dans un menu à l'autre bout de la fenêtre.
        self.w_guide = QPushButton('?')
        self.w_guide.setFixedWidth(34)
        self.w_guide.setToolTip(
            'Guide des paramètres : ce que chaque réglage fait au métal, '
            'les treize formes d\'onde de la source, et ce que valent les '
            'recommandations qui circulent.')
        self.w_guide.clicked.connect(self._open_guide)
        barre.addWidget(self.w_guide)
        barre.addWidget(self.w_save)
        barre.addWidget(self.w_revert)
        barre.addStretch(1)
        barre.addWidget(self.w_expert_button)
        barre.addWidget(self.w_done)
        outer.addLayout(barre)

        self._refresh_list()
        self._apply_expert()
        if self.recipes:
            self._select_rang(0)

    # -- fabriques de widgets ---------------------------------------------

    def _float(self, lo, hi, suffix, decimals, step=1.0):
        w = Spin(lo, lo, hi, step=step, decimals=decimals, suffix=suffix)
        w.valueChanged.connect(self._edited)
        return w

    def _int(self, lo, hi, tip=''):
        w = IntSpin(lo, lo, hi)
        if tip:
            w.setToolTip(tip)
        w.valueChanged.connect(self._edited)
        return w

    # -- mode expert -------------------------------------------------------

    def _unlock(self) -> None:
        if unlock(self):
            self._apply_expert()

    def _apply_expert(self) -> None:
        on = expert()
        for w in (self.w_freq, self.w_pulse):
            w.setEnabled(on)
        self.w_expert_button.setVisible(not on)
        if on:
            self.w_lock.setText('Mode expert actif pour cette session.')
            self.w_lock.setStyleSheet(theme.css('ok', 11))
        else:
            self.w_lock.setText(
                'Verrouillé. Ces deux valeurs agissent directement sur la '
                'source : un code est demandé pour les modifier.')
            self.w_lock.setStyleSheet(theme.css('text_dim', 11))

    # -- liste -------------------------------------------------------------

    def _refresh_list(self, select: int = -1) -> None:
        """Range les process par dossier, dans un arbre repliable.

        L'ordre des dossiers est alphabétique, mais **la racine passe en
        tête** : une process sans dossier est le cas courant, et
        l'enterrer sous les rangements la rendrait plus difficile à
        trouver que celles qu'on a pris la peine de classer.
        """
        self._guard = True
        self.w_list.clear()
        self._noeuds = {}

        par_dossier: dict[str, list[int]] = {}
        for i, r in enumerate(self.recipes):
            par_dossier.setdefault(r.folder.strip(), []).append(i)

        ordre = sorted(par_dossier, key=lambda d: (d != '', d.lower()))
        choisi = None
        for dossier in ordre:
            rangs = par_dossier[dossier]
            if dossier:
                parent = QTreeWidgetItem(self.w_list,
                                         [f'{dossier}  ({len(rangs)})'])
                parent.setData(0, Qt.UserRole, None)
                parent.setToolTip(0, f'{len(rangs)} process dans « {dossier} »')
                police = parent.font(0)
                police.setBold(True)
                parent.setFont(0, police)
                self._noeuds[dossier] = parent
            else:
                parent = None
            for rang in rangs:
                r = self.recipes[rang]
                # sous un dossier, le nom suffit : le répéter en entier
                # ferait « Laiton / Laiton fin » sur deux niveaux
                titre = _summary(r, court=bool(dossier))
                item = (QTreeWidgetItem(parent, [titre]) if parent is not None
                        else QTreeWidgetItem(self.w_list, [titre]))
                item.setData(0, Qt.UserRole, rang)
                item.setToolTip(0, r.label())
                if rang == select:
                    choisi = item
            if parent is not None:
                parent.setExpanded(dossier not in self._replies)

        self._guard = False
        if choisi is not None:
            self.w_list.setCurrentItem(choisi)
        elif select >= 0:
            self._select_rang(min(select, len(self.recipes) - 1))

    def labels(self) -> list[str]:
        '''Le texte de chaque process listée, dossiers exclus.

        La liste est un arbre : compter ses entrées de premier niveau
        compterait les dossiers. Cette méthode existe pour que personne
        n'ait à savoir comment l'arbre est bâti.
        '''
        return [i.text(0) for i in self._tous_items()]

    def select_row(self, rang: int) -> None:
        '''Désigne la process de rang `rang`.'''
        self._select_rang(rang)

    def folders(self) -> list[str]:
        '''Les dossiers montrés, dans leur ordre.'''
        return [self.w_list.topLevelItem(i).text(0)
                       .rsplit(chr(32) * 2 + chr(40), 1)[0]
                for i in range(self.w_list.topLevelItemCount())
                if self.w_list.topLevelItem(i)
                       .data(0, Qt.UserRole) is None]

    def _select_rang(self, rang: int) -> None:
        """Pose la sélection sur la process de rang donné."""
        for item in self._tous_items():
            if item.data(0, Qt.UserRole) == rang:
                self.w_list.setCurrentItem(item)
                return

    def _tous_items(self):
        """Toutes les entrées de process, dossiers exclus."""
        out = []
        for i in range(self.w_list.topLevelItemCount()):
            haut = self.w_list.topLevelItem(i)
            if haut.data(0, Qt.UserRole) is not None:
                out.append(haut)
            for j in range(haut.childCount()):
                out.append(haut.child(j))
        return out

    def _fold_changed(self, item) -> None:
        """Retient qu'un dossier a été replié, ou rouvert."""
        if self._guard or item.data(0, Qt.UserRole) is not None:
            return
        nom = item.text(0).rsplit('  (', 1)[0]
        if item.isExpanded():
            self._replies.discard(nom)
        else:
            self._replies.add(nom)

    def _item_changed(self, item, _precedent=None) -> None:
        """Un clic sur un dossier ne change pas de process."""
        if item is None:
            return
        rang = item.data(0, Qt.UserRole)
        if rang is None:
            return
        self._row_changed(int(rang))

    def _row_changed(self, row: int) -> None:
        if self._guard:
            return
        self._current = row
        self.editor.setEnabled(0 <= row < len(self.recipes))
        if not (0 <= row < len(self.recipes)):
            return
        r = self.recipes[row]
        self._guard = True
        self.w_name.setText(r.name)
        self.w_folder.setText(r.folder)
        self._fill_treatments(r.treatment)
        self.w_tool.setValue(r.tool_number)
        self.w_power.setValue(r.power_percent)
        self.w_speed.setValue(r.speed_mm_min * SPEED_TO_DISPLAY)
        self.w_passes.setValue(r.passes)
        self.w_freq.setValue(r.frequency_khz)
        self.w_pulse.setValue(r.pulse_width_ns)
        self.w_hatch.setValue(r.hatch_mm)
        self.w_hstep.setValue(r.hatch_angle_step_deg)
        self.w_hcross.setChecked(bool(r.hatch_cross))
        self.w_link.setChecked(bool(getattr(r, 'link_paths', False)))
        self.w_fill.setCurrentIndex(max(0, self.w_fill.findData(
            getattr(r, 'fill_style', 'hatch'))))
        self._fill_style_shown()
        self.w_hinset.setValue(r.hatch_inset_mm)
        self.w_wob.setCurrentIndex(max(0, self.w_wob.findData(r.wobble)))
        self.w_wamp.setValue(r.wobble_amp_mm)
        self.w_wpitch.setValue(r.wobble_pitch_mm)
        self.w_hangle.setValue(r.hatch_angle_deg)
        self.w_depth_mode.setCurrentIndex(
            max(self.w_depth_mode.findData(r.depth_mode), 0))
        self.w_depth_step.setValue(r.depth_step_mm)
        self.w_depth_total.setValue(r.depth_total_mm)
        self._guard = False
        self._describe_depth(r)

    def _fill_style_shown(self, *_) -> None:
        """Angle, rotation et croisement n'ont pas de sens en anneaux."""
        rangees = self.w_fill.currentData() != 'rings'
        for w in (self.w_hangle, self.w_hstep, self.w_hcross):
            w.setEnabled(rangees)

    def _edited(self, *_) -> None:
        """Reporte l'édition dans la recette courante.

        `Recipe` est immuable : on remplace l'entrée de la liste plutôt que
        de muter, ce qui garantit aussi que le cache de trajectoires — qui
        prend la recette pour clé — voit bien le changement.
        """
        if self._guard or not (0 <= self._current < len(self.recipes)):
            return
        self.recipes[self._current] = dataclasses.replace(
            self.recipes[self._current],
            name=self.w_name.text().strip() or 'sans nom',
            folder=self.w_folder.text().strip(),
            tool_number=self.w_tool.value(),
            power_percent=self.w_power.value(),
            speed_mm_min=self.w_speed.value() * SPEED_FROM_DISPLAY,
            passes=self.w_passes.value(),
            frequency_khz=self.w_freq.value(),
            pulse_width_ns=self.w_pulse.value(),
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
            depth_mode=self.w_depth_mode.currentData() or 'step',
            depth_step_mm=self.w_depth_step.value(),
            depth_total_mm=self.w_depth_total.value(),
            treatment=self.w_treatment.currentData(),
        )
        self._describe_depth(self.recipes[self._current])
        self._decrire_oscillation()
        r = self.recipes[self._current]
        item = self.w_list.currentItem()
        if item is not None and item.data(0, Qt.UserRole) == self._current:
            # changer de dossier change de branche : il faut reconstruire,
            # sinon la process reste affichée sous son ancien rangement
            parent = item.parent()
            actuel = (parent.text(0).rsplit('  (', 1)[0] if parent else '')
            if actuel != r.folder.strip():
                self._refresh_list(select=self._current)
                return
            item.setText(0, _summary(r, court=bool(r.folder.strip())))
            item.setToolTip(0, r.label())

    def _decrire_oscillation(self) -> None:
        """Dit ce que l'oscillation demande au scanner, et si c'est tenable.

        La bande n'est pas plus large qu'un trait simple quand le miroir
        ne suit pas — et rien ne l'annonce sur la pièce.
        """
        if not (0 <= self._current < len(self.recipes)):
            return
        r = self.recipes[self._current]
        if r.wobble == 'none' or r.wobble_pitch_mm <= 0:
            self.w_wob_info.setText('')
            return
        cadence = wobble.scanner_hz(r.speed_mm_min, r.wobble_pitch_mm)
        palette = theme.current()
        if cadence > wobble.SCANNER_MAX_HZ:
            couleur = palette.alarm
            verdict = 'au-delà de ce que le scanner suit'
        elif cadence > wobble.SCANNER_SAFE_HZ:
            couleur, verdict = palette.warn, 'à la limite du scanner'
        else:
            couleur, verdict = palette.ok, 'tenable'
        self.w_wob_info.setTextFormat(Qt.RichText)
        self.w_wob_info.setText(
            f'<span style="color:{couleur}">{cadence:.0f} Hz demandés — '
            f'{verdict}.</span>')

    def _fill_treatments(self, courant=None) -> None:
        """Liste les modèles, en gardant visible celui qui a disparu.

        Un traitement figé dans une recette dont le modèle a été retiré de
        la bibliothèque doit rester **visible et sélectionné** : sinon la
        recette semblerait avoir perdu son traitement alors qu'elle le
        porte toujours.
        """
        from .treatment import templates
        self.w_treatment.blockSignals(True)
        self.w_treatment.clear()
        self.w_treatment.addItem('(aucun)', None)
        noms = []
        for modele in templates():
            self.w_treatment.addItem(modele.name, modele)
            noms.append(modele.name)
        if courant is not None and courant.name not in noms:
            libelle = (f'{courant.name} (modèle retiré)' if courant.name
                       else 'réglages figés')
            self.w_treatment.addItem(libelle, courant)
        rang = 0
        if courant is not None:
            rang = next((i for i in range(self.w_treatment.count())
                         if self.w_treatment.itemData(i) == courant), 0)
            if rang == 0:
                rang = next((i for i in range(self.w_treatment.count())
                             if getattr(self.w_treatment.itemData(i), 'name',
                                        None) == courant.name), 0)
        self.w_treatment.setCurrentIndex(rang)
        self.w_treatment.blockSignals(False)
        self.w_treat_info.setText(courant.describe() if courant else
                                  'Le dessin est gravé tel quel.')

    def _treatment_chosen(self) -> None:
        if self._guard or not (0 <= self._current < len(self.recipes)):
            return
        modele = self.w_treatment.currentData()
        self.recipes[self._current] = dataclasses.replace(
            self.recipes[self._current], treatment=modele)
        self.w_treat_info.setText(modele.describe() if modele else
                                  'Le dessin est gravé tel quel.')

    def reload(self) -> None:
        """Relit la bibliothèque **enregistrée**, en abandonnant l'édition.

        Le fichier, et non la copie en mémoire : c'est lui que
        *Importer des réglages* vient d'écrire. Relire la mémoire
        montrait la bibliothèque d'avant l'import — et un *Enregistrer*
        qui suivait la réécrivait par-dessus, effaçant l'import.
        """
        self.recipes = load_local()
        set_recipe_library(self.recipes)
        self._refresh_list(min(self._current, len(self.recipes) - 1))
        if self.recipes:
            self._row_changed(max(0, min(self._current,
                                         len(self.recipes) - 1)))

    def load_tool(self, outil) -> None:
        """Charge un outil du magasin dans la recette courante.

        Le **nom de la recette est conservé** : c'est celui que l'atelier
        emploie, et l'écraser par celui du magasin ferait perdre le fil.
        """
        if outil is None or not (0 <= self._current < len(self.recipes)):
            return
        ancienne = self.recipes[self._current]
        self.recipes[self._current] = dataclasses.replace(
            outil.to_recipe(ancienne), name=ancienne.name)
        self._refresh_list(self._current)
        self._row_changed(self._current)

    def _rename(self) -> None:
        """Amène au champ *Nom* et l'y sélectionne.

        Renommer se faisait déjà en tapant dans ce champ — encore
        fallait-il savoir qu'il était éditable. Un bouton le dit.
        """
        if not (0 <= self._current < len(self.recipes)):
            return
        self.w_name.setFocus(Qt.OtherFocusReason)
        self.w_name.selectAll()

    def _describe_depth(self, recipe: Recipe) -> None:
        """Montre les cotes obtenues : un pas ne se lit pas de tête."""
        total = recipe.depth_mode == 'total'
        self.w_depth_step.setEnabled(not total)
        self.w_depth_total.setEnabled(total)
        step = recipe.depth_step()
        if step <= 0 or recipe.passes <= 1:
            self.w_depth_info.setText(
                'Toutes les passes en surface.' if recipe.passes > 1
                else 'Un seul passage : la profondeur ne s\'applique pas.')
            return
        cotes = ' · '.join(f'{recipe.depth_of(i):.4f}'
                           for i in range(min(recipe.passes, 4)))
        suite = ' …' if recipe.passes > 4 else ''
        self.w_depth_info.setText(
            f'{recipe.passes} passes, pas de {step * 1000:g} µm — '
            f'Z {cotes}{suite}')

    def _new(self) -> None:
        self.recipes.append(default_recipe(name='Nouvelle process'))
        self._refresh_list(len(self.recipes) - 1)

    def _copy(self) -> None:
        if not (0 <= self._current < len(self.recipes)):
            return
        src = self.recipes[self._current]
        self.recipes.insert(self._current + 1,
                            dataclasses.replace(src, name=f'{src.name} (copie)'))
        self._refresh_list(self._current + 1)

    def _remove(self) -> None:
        if not (0 <= self._current < len(self.recipes)):
            return
        if len(self.recipes) == 1:
            QMessageBox.information(
                self, 'Process',
                'La bibliothèque doit garder au moins une process.')
            return
        name = self.recipes[self._current].name
        if QMessageBox.question(
                self, 'Supprimer', f'Supprimer « {name} » ?') != \
                QMessageBox.StandardButton.Yes:
            return
        row = self._current
        del self.recipes[row]
        self._refresh_list(max(0, row - 1))

    def _move(self, direction: int) -> None:
        row = self._current
        target = row + direction
        if not (0 <= row < len(self.recipes) and 0 <= target < len(self.recipes)):
            return
        self.recipes[row], self.recipes[target] = \
            self.recipes[target], self.recipes[row]
        self._refresh_list(target)

    def _factory(self) -> None:
        usine = list(factory_recipes())
        if QMessageBox.question(
                self, 'Process d\'usine',
                f'Remplacer toute la bibliothèque par les {len(usine)} '
                'process d\'usine ?') != QMessageBox.StandardButton.Yes:
            return
        self.recipes = usine
        self._refresh_list(0)

    def _open_guide(self) -> None:
        """Ouvre le guide des paramètres laser."""
        from .guide import Guide
        Guide(self).exec()

    # -- échange entre postes ---------------------------------------------

    def _export(self) -> None:
        """Toute la bibliothèque **telle qu'affichée**, non enregistrée
        comprise : on exporte ce qu'on voit."""
        from PySide6.QtWidgets import QFileDialog
        from . import echange, session
        depart = pathlib.Path(session.start_folder('reglages'))
        chemin, _ = QFileDialog.getSaveFileName(
            self, 'Exporter les process',
            str(depart / f'process {echange.poste()}'
                + echange.SUFFIX_PROCESS),
            echange.FILTRE_PROCESS)
        if not chemin:
            return
        try:
            cible = echange.ecrire_process(chemin, self.recipes)
        except echange.EchangeError as exc:
            QMessageBox.warning(self, 'Exporter les process', str(exc))
            return
        session.remember_file('reglages', str(cible))
        QMessageBox.information(
            self, 'Exporter les process',
            f'{len(self.recipes)} process écrites dans\n{cible}')

    def _import(self) -> None:
        """Reprend des process d'un fichier, après les avoir montrées."""
        from PySide6.QtWidgets import QFileDialog
        from . import echange, session
        chemin, _ = QFileDialog.getOpenFileName(
            self, 'Importer des process',
            session.start_folder('reglages'), echange.FILTRE_PROCESS)
        if not chemin:
            return
        try:
            venues, entete = echange.lire_process(chemin)
        except echange.EchangeError as exc:
            QMessageBox.warning(self, 'Importer des process', str(exc))
            return
        if not venues:
            QMessageBox.information(self, 'Importer des process',
                                    'Ce fichier ne contient aucune process.')
            return
        session.remember_file('reglages', chemin)
        choix = echange.ChoixImport(
            self, 'Importer des process', entete, venues,
            lambda r: r.name, {r.name for r in self.recipes})
        if choix.exec() != QDialog.DialogCode.Accepted:
            return
        retenues = choix.retenues()
        if not retenues:
            return
        self.recipes = echange.fusionner(self.recipes, retenues,
                                         lambda r: r.name)
        # les dossiers venus d'ailleurs s'ouvrent : on veut voir ce qui
        # vient d'arriver
        self._replies -= {r.folder for r in retenues
                          if getattr(r, 'folder', '')}
        self._refresh_list(len(self.recipes) - 1)
        self._save()

    def _save(self) -> None:
        names = [r.name for r in self.recipes]
        doubles = {n for n in names if names.count(n) > 1}
        if doubles:
            QMessageBox.warning(
                self, 'Process',
                'Deux process portent le même nom : '
                + ', '.join(sorted(doubles))
                + '.\nLa liste déroulante ne permettrait plus de les '
                  'distinguer.')
            return
        save_local(self.recipes)
        set_recipe_library(self.recipes)
        self.saved.emit(len(self.recipes))
