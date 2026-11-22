"""Montage à DataMatrix / DataMatrix fixture.

Un montage machine porte plusieurs pièces à la fois, et chaque pièce
reçoit son propre DataMatrix accompagné de sa référence en clair.

**Les cotes ne sont pas ici.** Elles vivent dans un gabarit — voir
`gabarits` — parce que ce sont celles de la mécanique : le jour où
l'entraxe change, ce doit être une valeur à corriger, pas un exécutable
à reconstruire.

Ce module ne fait qu'une chose, et c'est la seule qui relève du
programme : **chaque texte suit son propre code**. Dans le fichier de
production d'origine, les trois textes pointaient tous vers le symbole
du MILIEU (`follows`), si bien que changer la référence du HAUT ne
mettait à jour aucun texte, et changer celle du MILIEU en réécrivait
trois. Une pièce serait partie avec un code et un numéro lisible qui se
contredisent — exactement ce que `follows` doit empêcher.

Le lien est posé sous-ensemble par sous-ensemble, et l'autotest le
vérifie : autant de codes que de textes, et autant de liens distincts.

**Un montage posé se retouche d'un bloc** — `appliquer` le remet aux
cotes d'un gabarit sans toucher aux références —, et ses retouches
s'enregistrent dans le gabarit depuis le formulaire même de la pose.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit,
                               QPushButton, QToolButton, QVBoxLayout,
                               QWidget)

from .codeplate import fit_text
from .model import (Code, Recipe, Shape, Text, ecrire_symbologie,
                    lire_symbologie)

@dataclass(frozen=True)
class Poste:
    """Un sous-ensemble du montage : un nom, une ordonnée."""

    cle: str
    libelle: str
    y_mm: float


def postes_de(gab: dict) -> tuple:
    """Les postes d'un gabarit, du haut vers le bas.

    L'ordre est celui où on les lit sur la machine, et donc celui des
    champs du formulaire.
    """
    from . import gabarits
    ys = gabarits.positions(gab)
    return tuple(
        Poste(gabarits.cle_poste(libelle), str(libelle), y)
        for libelle, y in zip(gab['postes'], ys))


def defaut() -> dict:
    """Le premier gabarit du poste — celui que pose le bouton."""
    from . import gabarits
    return gabarits.charger()[0]


#: Donnée proposée quand rien n'est saisi.
DEFAULT_DATA = 'B000181'


def build(recipe: Recipe, donnees=None, *, gabarit: dict | None = None,
          x_mm: float | None = None, dm_shape: str = '') -> list[Shape]:
    """Les formes du montage : un symbole et un texte par poste.

    `donnees` donne une référence par poste — une chaîne unique les
    applique toutes. À défaut, chaque poste reçoit celle que le gabarit
    lui propose (`gabarits.proposees`). Rend les formes dans l'ordre des
    postes, symbole puis texte pour chacun, de sorte que l'appelant
    puisse grouper des paires consécutives.
    """
    from . import gabarits
    from .toolpath import code_matrix

    gab = gabarit or defaut()
    postes = postes_de(gab)
    c, t = gab['code'], gab['texte']
    # `x_mm` déplace le montage entier : chaque poste garde son écart
    decale = (0.0 if x_mm is None
              else float(x_mm) - float(gab.get('x_mm', 0.0)))
    abscisses = [x + decale for x in gabarits.positions_x(gab)]
    forme = dm_shape or c.get('forme', 'auto')
    proposees = gabarits.proposees(gab)

    if donnees is None:
        donnees = {}
    elif isinstance(donnees, str):
        donnees = {p.cle: donnees for p in postes}

    out: list[Shape] = []
    for poste, x, propose in zip(postes, abscisses, proposees):
        valeur = str(donnees.get(poste.cle) or propose)
        code = Code(x=x, y=poste.y_mm, recipe=recipe,
                    kind=lire_symbologie(c, 'datamatrix'), data=valeur,
                    dm_shape=forme, quiet_modules=0,
                    module_mm=float(c['module_mm']),
                    fit_w_mm=float(c['largeur_mm']),
                    fit_h_mm=float(c['hauteur_mm']),
                    frame=c.get('cadre', 'rect'),
                    frame_margin_mm=float(c.get('marge_cadre_mm', 0.5)))
        # le poste est un **rôle** : il ne se déduit pas de la donnée et
        # ne change pas avec elle — voir `Shape.role`
        code.role = poste.libelle
        if not code_matrix(code):
            return []

        texte = fit_text(valeur, float(t['largeur_mm']),
                         float(t['hauteur_mm']))
        texte.x = x + float(t.get('dx_mm', 0.0))
        texte.y = poste.y_mm + float(t.get('dy_mm', 0.0))
        texte.recipe = recipe
        texte.frame = 'none'
        # chacun suit **son** symbole, et non celui du milieu : c'est tout
        # l'objet de ce module
        texte.follows = code.id
        texte.role = poste.libelle
        out.extend((code, texte))
    return out


def appliquer(shapes, gab: dict) -> list[Shape]:
    """Remet un montage posé aux cotes d'un gabarit. Rend les formes
    touchées — aucune si le nombre de postes ne s'accorde pas.

    Position de chaque poste, cadre, marge, taille et module du symbole,
    place et taille du texte : tout ce que `build` aurait posé, **sauf les
    références**, qui restent celles qu'on a saisies. La taille du texte
    est celle qu'il aurait eue à la pose, avec la référence proposée —
    pas recalculée sur la référence saisie, que la pose ne connaissait
    pas.

    Les postes se reconnaissent à leur rôle ; à défaut, à leur hauteur :
    le plus haut des codes va au plus haut des postes, quel que soit
    l'ordre dans lequel le gabarit les liste.

    Un montage **tourné** n'est pas touché : les positions du gabarit
    sont droites, et le remettre à ses cotes le détournerait à moitié.
    """
    from . import gabarits

    paires = pairs(list(shapes))
    postes = postes_de(gab)
    if not paires or len(paires) != len(postes):
        return []
    if any((c.rotation_deg or 0) % 360 or (t.rotation_deg or 0) % 360
           for c, t in paires):
        return []
    places = list(zip(postes, gabarits.positions_x(gab),
                      gabarits.proposees(gab)))
    par_role = {gabarits.cle_poste(c.role or ''): (c, t) for c, t in paires}
    if (len(par_role) == len(paires)
            and set(par_role) == {p.cle for p in postes}):
        couples = [(par_role[place[0].cle], place) for place in places]
    else:
        couples = list(zip(sorted(paires, key=lambda p: -p[0].y),
                           sorted(places, key=lambda q: -q[0].y_mm)))
    c, t = gab['code'], gab['texte']
    touches: list[Shape] = []
    for (code, texte), (poste, x, propose) in couples:
        code.x, code.y = x, poste.y_mm
        code.kind = lire_symbologie(c, code.kind)
        code.fit_w_mm = float(c['largeur_mm'])
        code.fit_h_mm = float(c['hauteur_mm'])
        code.module_mm = float(c['module_mm'])
        code.frame = c.get('cadre', 'rect')
        code.frame_margin_mm = float(c.get('marge_cadre_mm', 0.5))
        code.dm_shape = c.get('forme', 'auto')
        code.role = poste.libelle
        texte.size_mm = fit_text(propose, float(t['largeur_mm']),
                                 float(t['hauteur_mm'])).size_mm
        texte.x = x + float(t.get('dx_mm', 0.0))
        texte.y = poste.y_mm + float(t.get('dy_mm', 0.0))
        texte.role = poste.libelle
        touches.extend((code, texte))
    return touches


def pairs(shapes: list[Shape]) -> list[tuple[Code, Text]]:
    """Les paires (symbole, texte) d'une liste, appariées par `follows`."""
    codes = [s for s in shapes if isinstance(s, Code)]
    out = []
    for code in codes:
        texte = next((s for s in shapes
                      if isinstance(s, Text) and s.follows == code.id), None)
        if texte is not None:
            out.append((code, texte))
    return out


#: Au-delà, une sélection de plaques codées n'est plus un montage mais
#: une planche : tout sélectionner sur trois cents plaques bâtissait un
#: formulaire de trois cents champs — une demi-seconde à chaque clic, et
#: personne pour les remplir à la main. Le lot, lui, mesure l'ensemble et
#: lui pose une process commune. Un montage posé depuis son gabarit n'est
#: pas concerné : son nombre de postes est celui du gabarit.
MAX_POSTES = 64


def is_montage(shapes: list[Shape]) -> bool:
    """Vrai si cette sélection est un montage à DataMatrix.

    Autant de textes que de codes, et **autant de liens distincts** :
    c'est le dernier point qui compte. Un montage dont deux textes
    suivraient le même code n'en est pas un — c'est le défaut qu'on a
    trouvé en production, et le reconnaître comme un montage valide
    reviendrait à le bénir.

    Le nombre de postes vient du gabarit — un montage à quatre postes est
    un montage —, dans la limite de `MAX_POSTES`.
    """
    codes = [s for s in shapes if isinstance(s, Code)]
    textes = [s for s in shapes if isinstance(s, Text)]
    if len(codes) < 2 or len(codes) != len(textes):
        return False
    if len(codes) > MAX_POSTES:
        return False
    suivis = {t.follows for t in textes}
    return len(suivis) == len(codes) and suivis == {c.id for c in codes}


# --------------------------------------------------------------------------
# Les réglages d'un montage
# --------------------------------------------------------------------------

#: Écart en deçà duquel un champ de position n'a pas bougé : la moitié
#: du millième que montrent les champs.
SEUIL_MM = 5e-4


class ReglagesMontage(QWidget):
    """Cadre, marge, taille, positions et texte d'un montage.

    **Un formulaire pour trois usages** : la flèche du bouton Montage y
    règle le prochain montage, le formulaire de la pose y retouche celui
    qu'on vient de poser, le gestionnaire y édite un gabarit. Trois
    copies du même formulaire finiraient par ne plus montrer les mêmes
    champs.

    Il tient un gabarit entier et n'en change que ce qu'il montre. Les
    positions se lisent comme sur un plan : un **entraxe** et un
    **centre**. Un montage aux positions une à une montre l'entraxe
    moyen ; le changer les rend régulières, déplacer le centre les
    décale toutes.

    `complet` ajoute la symbologie, la forme du DataMatrix et le module :
    ce qu'on règle une fois au gestionnaire, pas à chaque pose.
    """

    #: Un réglage a changé : `gabarit()` le porte déjà.
    changed = Signal()

    def __init__(self, parent=None, *, complet: bool = False) -> None:
        super().__init__(parent)
        from . import theme
        from .widgets import Combo, Spin
        self._gab: dict = {}
        self._montre: dict = {}
        self._guard = False

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        theme.tidy_form(form)

        def paire(a, b, signe):
            rangee = QWidget()
            boite = QHBoxLayout(rangee)
            boite.setContentsMargins(0, 0, 0, 0)
            boite.setSpacing(4)
            boite.addWidget(a)
            boite.addWidget(QLabel(signe))
            boite.addWidget(b)
            return rangee

        self.w_kind = self.w_forme = self.w_module = None
        if complet:
            from . import barcode
            self.w_kind = Combo()
            for cle, libelle in barcode.KINDS:
                self.w_kind.addItem(libelle, cle)
            self.w_forme = Combo()
            for cle, libelle in (('auto', 'selon la donnée'),
                                 ('square', 'carré'),
                                 ('rect', 'rectangulaire')):
                self.w_forme.addItem(libelle, cle)
            self.w_forme.setToolTip('Forme du DataMatrix. « selon la '
                                    'donnée » prend la plus compacte.')
            self.w_module = Spin(0.5, 0.01, 10.0, 0.05, 3, ' mm')
            self.w_module.setToolTip(
                'Côté d\'un module. Le symbole est ensuite étiré à sa '
                'fenêtre L × H.')
            form.addRow('Symbologie', self.w_kind)
            form.addRow('Forme', self.w_forme)
        self.w_cadre = Combo()
        for cle, libelle in (('rect', 'rectangle'), ('circle', 'cercle'),
                             ('none', 'aucun')):
            self.w_cadre.addItem(libelle, cle)
        self.w_cadre.setToolTip('Cadre englobant gravé en négatif autour '
                                'de chaque symbole.')
        self.w_marge = Spin(0.5, 0.0, 20.0, 0.1, 3, ' mm')
        self.w_marge.setToolTip('Jour entre le symbole et son cadre.')
        self.w_cl = Spin(15.0, 0.5, 200.0, 0.5, 3, ' mm')
        self.w_ch = Spin(7.0, 0.5, 200.0, 0.5, 3, ' mm')
        for w in (self.w_cl, self.w_ch):
            w.setToolTip('Fenêtre du symbole, cadre non compris : il est '
                         'étiré pour la remplir.')
        self.w_entraxe = Spin(23.0, 0.0, 500.0, 0.5, 3, ' mm')
        self.w_entraxe.setToolTip('Écart vertical entre deux postes '
                                  'voisins.')
        self.w_irregulier = QLabel(
            'Positions une à une : changer l\'entraxe les rend régulières, '
            'déplacer le centre les décale toutes.')
        self.w_irregulier.setWordWrap(True)
        self.w_irregulier.setStyleSheet(theme.css('text_dim',
                                                  theme.PETIT_PT))
        self.w_cx = Spin(0.0, -500.0, 500.0, 0.5, 3, ' mm')
        self.w_cy = Spin(0.0, -500.0, 500.0, 0.5, 3, ' mm')
        self.w_cx.setToolTip('Centre du montage dans le champ, '
                             'horizontalement.')
        self.w_cy.setToolTip('Centre du montage dans le champ, '
                             'verticalement : entre le poste du haut et '
                             'celui du bas.')
        self.w_tl = Spin(6.2, 0.1, 200.0, 0.1, 3, ' mm')
        self.w_th = Spin(1.2, 0.1, 200.0, 0.1, 3, ' mm')
        for w in (self.w_tl, self.w_th):
            w.setToolTip('Fenêtre du texte en clair : la référence proposée '
                         'y est ajustée à la pose.')
        self.w_tdx = Spin(-14.0, -200.0, 200.0, 0.5, 3, ' mm')
        self.w_tdy = Spin(-3.9, -200.0, 200.0, 0.5, 3, ' mm')
        for w in (self.w_tdx, self.w_tdy):
            w.setToolTip('Écart du centre du texte au centre de son '
                         'symbole.')

        form.addRow('Cadre', self.w_cadre)
        form.addRow('Marge', self.w_marge)
        form.addRow('Symbole L × H', paire(self.w_cl, self.w_ch, '×'))
        if self.w_module is not None:
            form.addRow('Module', self.w_module)
        form.addRow('Entraxe', self.w_entraxe)
        form.addRow('', self.w_irregulier)
        form.addRow('Centre X / Y', paire(self.w_cx, self.w_cy, '/'))
        form.addRow('Texte L × H', paire(self.w_tl, self.w_th, '×'))
        form.addRow('Texte dX / dY', paire(self.w_tdx, self.w_tdy, '/'))
        self.w_irregulier.hide()

        for combo in (self.w_cadre, self.w_kind, self.w_forme):
            if combo is not None:
                combo.currentIndexChanged.connect(self._edite)
        for champ in (self.w_marge, self.w_cl, self.w_ch, self.w_module,
                      self.w_entraxe, self.w_cx, self.w_cy, self.w_tl,
                      self.w_th, self.w_tdx, self.w_tdy):
            if champ is not None:
                champ.valueChanged.connect(self._edite)

    # -- lecture ---------------------------------------------------------

    def set_gabarit(self, gab: dict) -> None:
        """Montre ce gabarit. N'émet rien."""
        from . import gabarits
        self._gab = copy.deepcopy(gab)
        c, t = self._gab['code'], self._gab['texte']
        try:
            ys = gabarits.positions(self._gab)
            xs = gabarits.positions_x(self._gab)
        except (gabarits.GabaritError, TypeError, ValueError):
            ys, xs = [], []
        irregulier = bool(self._gab.get('positions_y_mm'))
        if irregulier and len(ys) > 1:
            entraxe = (ys[0] - ys[-1]) / (len(ys) - 1)
        else:
            entraxe = float(self._gab.get('entraxe_mm', 0.0))
        cy = ((max(ys) + min(ys)) / 2 if ys
              else float(self._gab.get('centre_y_mm', 0.0)))
        cx = ((max(xs) + min(xs)) / 2 if xs
              else float(self._gab.get('x_mm', 0.0)))
        self._guard = True
        try:
            def choisit(combo, cle, repli):
                i = combo.findData(cle)
                combo.setCurrentIndex(i if i >= 0
                                      else max(0, combo.findData(repli)))
            choisit(self.w_cadre, c.get('cadre', 'rect'), 'rect')
            if self.w_kind is not None:
                choisit(self.w_kind, lire_symbologie(c, 'datamatrix'),
                        'datamatrix')
                choisit(self.w_forme, c.get('forme', 'auto'), 'auto')
                self.w_forme.setEnabled(self.w_kind.currentData()
                                        == 'datamatrix')
                self.w_module.setValue(float(c.get('module_mm', 0.5)))
            self.w_marge.setValue(float(c.get('marge_cadre_mm', 0.5)))
            self.w_marge.setEnabled(c.get('cadre', 'rect') != 'none')
            self.w_cl.setValue(float(c.get('largeur_mm', 15.0)))
            self.w_ch.setValue(float(c.get('hauteur_mm', 7.0)))
            self.w_entraxe.setValue(entraxe)
            self.w_entraxe.setEnabled(len(ys) > 1)
            self.w_cx.setValue(cx)
            self.w_cy.setValue(cy)
            self.w_tl.setValue(float(t.get('largeur_mm', 6.2)))
            self.w_th.setValue(float(t.get('hauteur_mm', 1.2)))
            self.w_tdx.setValue(float(t.get('dx_mm', 0.0)))
            self.w_tdy.setValue(float(t.get('dy_mm', 0.0)))
            self.w_irregulier.setVisible(irregulier)
        finally:
            self._guard = False
        # ce que montrent les champs, tel qu'ils le montrent : c'est à
        # cela qu'on compare pour savoir lequel a bougé
        self._montre = {'entraxe': self.w_entraxe.value(),
                        'cx': self.w_cx.value(), 'cy': self.w_cy.value()}

    def gabarit(self) -> dict:
        """Le gabarit montré, retouches comprises."""
        return copy.deepcopy(self._gab)

    # -- édition ---------------------------------------------------------

    def _edite(self, *_) -> None:
        if self._guard or not self._gab:
            return
        g = self._gab
        c, t = g['code'], g['texte']
        c['cadre'] = self.w_cadre.currentData() or 'rect'
        c['marge_cadre_mm'] = self.w_marge.value()
        c['largeur_mm'] = self.w_cl.value()
        c['hauteur_mm'] = self.w_ch.value()
        if self.w_kind is not None:
            # un montage se porte d'un poste à l'autre, d'une version à
            # l'autre — voir `model.ecrire_symbologie`. Réécrite à chaque
            # retouche, d'une largeur même, la symbologie effaçait celle
            # qu'une version plus récente y avait rangée.
            choisie = self.w_kind.currentData() or 'datamatrix'
            if choisie != lire_symbologie(c, 'datamatrix'):
                ecrire_symbologie(c, choisie)
            c['forme'] = self.w_forme.currentData() or 'auto'
            c['module_mm'] = self.w_module.value()
        t['largeur_mm'] = self.w_tl.value()
        t['hauteur_mm'] = self.w_th.value()
        t['dx_mm'] = self.w_tdx.value()
        t['dy_mm'] = self.w_tdy.value()

        m = self._montre
        entraxe, cx, cy = (self.w_entraxe.value(), self.w_cx.value(),
                           self.w_cy.value())
        # Entrée dans un champ sans rien taper relit les trois décimales
        # affichées : un entraxe moyen de 22,6667 deviendrait 22,667, et
        # les positions une à une seraient rendues régulières sans qu'on
        # ait rien demandé. Bouger, c'est changer de plus d'un demi-pas
        # d'affichage.
        if abs(entraxe - m['entraxe']) > SEUIL_MM:
            # les postes répartis régulièrement le sont dans l'ordre de la
            # liste, le premier en haut : rangés d'abord, chacun reste à
            # sa place relative, sa référence avec lui
            from .gabarits import GabaritError, trier_postes
            try:
                trier_postes(g)
            except GabaritError:
                pass
            g.pop('positions_y_mm', None)
            g['entraxe_mm'] = entraxe
            g['centre_y_mm'] = cy
        elif abs(cy - m['cy']) > SEUIL_MM:
            if g.get('positions_y_mm'):
                g['positions_y_mm'] = [float(y) + cy - m['cy']
                                       for y in g['positions_y_mm']]
            else:
                g['centre_y_mm'] = cy
        if abs(cx - m['cx']) > SEUIL_MM:
            d = cx - m['cx']
            if g.get('positions_x_mm'):
                g['positions_x_mm'] = [float(x) + d
                                       for x in g['positions_x_mm']]
            g['x_mm'] = float(g.get('x_mm', 0.0)) + d
        # relu : l'entraxe d'un montage devenu régulier, la marge grisée
        # d'un symbole sans cadre
        self.set_gabarit(g)
        self.changed.emit()


# --------------------------------------------------------------------------
# Le formulaire
# --------------------------------------------------------------------------

class MontageForm(QWidget):
    """Un champ par sous-ensemble, et un « appliquer à tous ».

    Le montage se charge de trois façons, et le formulaire doit servir
    les trois : des pièces différentes (on tape chaque référence), des
    pièces du même lot (on tape une fois et l'on applique à tous), ou
    une seule pièce remontée pendant que les autres restent en place (on
    ne touche qu'un champ).

    D'où un bouton *Appliquer à tous* plutôt qu'une case « tous
    identiques » : la case imposerait un mode, le bouton rend un service
    et laisse chaque champ libre ensuite.

    Les champs sont **reconstruits à chaque chargement** : le nombre de
    postes vient du gabarit, et rien n'oblige deux montages à en avoir
    autant l'un que l'autre.
    """

    #: Émis quand une donnée a changé, pour que la fenêtre rafraîchisse.
    changed = Signal()
    #: Un gabarit vient d'être écrit — son nom.
    saved = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._codes: dict[str, Code] = {}
        self._postes: tuple = ()
        self._champs: dict[str, QLineEdit] = {}
        self._document = None
        self._formes: list = []
        self._guard = False
        #: Le gabarit que décrit le montage chargé, retouches comprises,
        #: et le nom de celui d'où il vient — vide s'il n'en vient
        #: d'aucun connu.
        self._reglages_gab: dict | None = None
        self._base_nom = ''
        self._ids: tuple = ()
        #: D'où vient chaque montage posé ou enregistré pendant la séance,
        #: par ses codes : retrouver un gabarit à ses seuls postes
        #: confondrait l'original et sa copie, qui portent les mêmes.
        self._origines: dict[frozenset, str] = {}
        #: Les gabarits entre lesquels on n'a pas su choisir.
        self._ambigus: list[str] = []

        self._dehors = QVBoxLayout(self)
        self._dehors.setContentsMargins(8, 8, 8, 8)

        self._titre = QLabel('<b>Montage à DataMatrix</b>')
        self._titre.setTextFormat(Qt.RichText)
        self._dehors.addWidget(self._titre)

        rappel = QLabel(
            'Chaque référence est gravée <b>deux fois</b> sur son poste : '
            'en DataMatrix et en clair. Les deux ne peuvent pas diverger.')
        rappel.setWordWrap(True)
        rappel.setTextFormat(Qt.RichText)
        self._dehors.addWidget(rappel)

        self._form = QFormLayout()
        self._form.setLabelAlignment(Qt.AlignRight)
        self._dehors.addLayout(self._form)

        self._tous = QPushButton('Appliquer à tous')
        self._tous.setToolTip(
            'Reprend la référence du premier poste sur tous les autres.\n'
            'Sert quand les pièces du montage viennent du même lot.')
        self._tous.clicked.connect(self._applique_tous)
        self._dehors.addWidget(self._tous)

        self._etat = QLabel('')
        self._etat.setWordWrap(True)
        self._etat.setTextFormat(Qt.RichText)
        self._dehors.addWidget(self._etat)

        # **Les réglages, au formulaire de la pose.** Cadre, marge,
        # taille, positions et place du texte se retouchent ici pour le
        # montage entier — et non code par code dans les propriétés —,
        # puis s'enregistrent dans le gabarit : la pose suivante les
        # reprend, et la flèche du bouton Montage les montre.
        self.w_plier = QToolButton()
        self.w_plier.setText('Cadre, taille et positions')
        self.w_plier.setCheckable(True)
        self.w_plier.setAutoRaise(True)
        self.w_plier.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.w_plier.toggled.connect(self._plie)
        self._dehors.addWidget(self.w_plier)
        self.w_boite = QWidget()
        boite = QVBoxLayout(self.w_boite)
        boite.setContentsMargins(0, 0, 0, 0)
        self.w_reglages = ReglagesMontage()
        self.w_reglages.changed.connect(self._applique_reglages)
        boite.addWidget(self.w_reglages)
        # le nom du gabarit sur sa ligne : porté par le bouton, il
        # élargissait la colonne des propriétés au-delà de l'écran
        self.w_gabarit = QLabel('')
        self.w_gabarit.setWordWrap(True)
        self.w_gabarit.setTextFormat(Qt.RichText)
        boite.addWidget(self.w_gabarit)
        self.w_avec_refs = QCheckBox('Retenir aussi les références saisies')
        self.w_avec_refs.setToolTip(
            'La pose suivante les proposera dans ce formulaire, poste par '
            'poste.')
        boite.addWidget(self.w_avec_refs)
        rangee = QHBoxLayout()
        self.w_enregistrer = QPushButton('Enregistrer dans le gabarit')
        self.w_enregistrer.setToolTip(
            'Le gabarit reprend ce montage tel qu\'il est posé : cadre, '
            'marge, taille, positions, place du texte.\nLa pose suivante '
            'le posera ainsi.')
        self.w_enregistrer.clicked.connect(
            lambda: self.enregistrer_gabarit())
        self.w_nouveau = QPushButton('Comme nouveau…')
        self.w_nouveau.setToolTip(
            'Range ce montage sous un autre nom, sans toucher au gabarit '
            'd\'origine.\nIl paraît ensuite au bout de la flèche du bouton '
            'Montage.')
        self.w_nouveau.clicked.connect(self._demande_nouveau)
        rangee.addWidget(self.w_enregistrer, 1)
        rangee.addWidget(self.w_nouveau)
        boite.addLayout(rangee)
        self._dehors.addWidget(self.w_boite)
        self._dehors.addStretch(1)
        from .session import settings
        ouvert = str(settings().value('montage/reglages_ouverts',
                                      'true')).lower() in ('true', '1')
        self.w_plier.setChecked(ouvert)
        self._plie(ouvert)

    # -- remplissage ---------------------------------------------------

    def set_montage(self, shapes, document=None, gabarit=None) -> bool:
        """Charge un montage. Faux si ce n'en est pas un.

        L'appariement se fait par **position**, du haut vers le bas, et
        non par le nom : un nom se modifie à la main et ment vite.
        """
        self._document = document
        codes = sorted((s for s in shapes if isinstance(s, Code)),
                       key=lambda s: -s.y)
        if len(codes) < 2:
            self._codes = {}
            return False

        # les postes viennent du gabarit quand on le connaît — chacun
        # apparié au code qui porte son rôle, à défaut à sa hauteur, et
        # non à son rang dans la liste — ; sinon des rôles portés par les
        # codes eux-mêmes, qui les ont gardés
        from .gabarits import cle_poste
        if gabarit is not None:
            postes = postes_de(gabarit)
            par_cle = {p.cle: p for p in postes}
            roles = [cle_poste(c.role or '') for c in codes]
            if (len(postes) == len(codes) == len(set(roles))
                    and set(roles) == set(par_cle)):
                self._postes = tuple(par_cle[r] for r in roles)
            else:
                self._postes = tuple(sorted(postes, key=lambda p: -p.y_mm))
        else:
            self._postes = tuple(
                Poste(cle_poste(c.role or f'poste {i + 1}'),
                      str(c.role or f'poste {i + 1}'), c.y)
                for i, c in enumerate(codes))
        if (len(self._postes) != len(codes)
                or len({p.cle for p in self._postes}) != len(codes)):
            self._postes = tuple(
                Poste(f'poste_{i + 1}', f'Poste {i + 1}', c.y)
                for i, c in enumerate(codes))

        self._rebatir()
        self._guard = True
        self._codes = {p.cle: c for p, c in zip(self._postes, codes)}
        for cle, code in self._codes.items():
            self._champs[cle].setText(code.data)
        self._guard = False
        self._dit_etat(shapes)
        self._formes = list(shapes)

        # le gabarit d'où vient ce montage : donné à la pose, déjà connu
        # s'il s'agit du même montage, retrouvé sinon
        ids = tuple(c.id for c in codes)
        if gabarit is not None:
            base, self._base_nom = gabarit, str(gabarit.get('nom', ''))
            self._origines[frozenset(ids)] = self._base_nom
            self._ambigus = []
        elif ids == self._ids and self._reglages_gab is not None:
            base = self._reglages_gab
        else:
            base = self._retrouve(frozenset(ids), codes)
            self._base_nom = str(base['nom']) if base else ''
            self.w_avec_refs.setChecked(False)
        self._ids = ids
        self._relit_reglages(base)
        return True

    # -- réglages ------------------------------------------------------

    def _retrouve(self, cle: frozenset, codes) -> dict | None:
        """Le gabarit d'où vient un montage qu'on recharge.

        Celui dont on l'a posé ou dans lequel on l'a enregistré pendant
        la séance, s'il existe encore. Sinon celui dont les postes
        portent ces rôles — et, s'il y en a plusieurs, comme un original
        et sa copie, celui que le montage reproduit exactement. Faute de
        mieux, aucun : enregistrer dans le mauvais gabarit écraserait
        l'original avec les cotes de la copie.
        """
        from . import gabarits
        liste = gabarits.charger()
        self._ambigus = []
        nom = self._origines.get(cle)
        if nom:
            connu = next((g for g in liste if g['nom'] == nom), None)
            if connu is not None:
                return connu
        roles = sorted(gabarits.cle_poste(c.role or '') for c in codes)
        candidats = [g for g in liste
                     if sorted(gabarits.cle_poste(q)
                               for q in g['postes']) == roles]
        if len(candidats) <= 1:
            return candidats[0] if candidats else None
        formes = self._paires()
        exacts = []
        for g in candidats:
            try:
                if gabarits.depuis_formes(formes, g) == g:
                    exacts.append(g)
            except (gabarits.GabaritError, TypeError, ValueError):
                continue
        if len(exacts) == 1:
            return exacts[0]
        self._ambigus = [g['nom'] for g in candidats]
        return None

    def rafraichir_gabarits(self) -> None:
        """Le fichier des gabarits a changé ailleurs — gestionnaire,
        flèche, import : le gabarit d'origine est relu, et oublié s'il
        n'existe plus. Le montage posé, lui, ne bouge pas."""
        from . import gabarits
        if not self._codes:
            return
        base = None
        if self._base_nom:
            base = next((g for g in gabarits.charger()
                         if g['nom'] == self._base_nom), None)
        if base is None:
            # supprimé, renommé, ou ambigu jusque-là : recherché comme au
            # chargement — une copie supprimée lève l'ambiguïté, un
            # gabarit renommé se retrouve à ses postes
            base = self._retrouve(frozenset(self._ids), self.codes())
        else:
            self._ambigus = []
        self._base_nom = str(base['nom']) if base else ''
        self._relit_reglages(base)

    def _paires(self) -> list:
        """Les formes du montage chargé, codes et textes."""
        tout = list(getattr(self._document, 'shapes', None)
                    or self._formes)
        ids = {c.id for c in self._codes.values()}
        return [s for c, t in pairs(tout) if c.id in ids for s in (c, t)]

    def _relit_reglages(self, base) -> None:
        """Les réglages montrés suivent le montage tel qu'il est posé —
        déplacé au plan compris."""
        from . import gabarits
        try:
            gab = gabarits.depuis_formes(self._paires(), base)
        except (gabarits.GabaritError, TypeError, ValueError) as exc:
            self._reglages_gab = None
            self.w_boite.setEnabled(False)
            self.w_gabarit.setText(str(exc))
            return
        if self._base_nom:
            gab['nom'] = self._base_nom
        self._reglages_gab = gab
        self.w_boite.setEnabled(True)
        self.w_boite.setToolTip('')
        self.w_reglages.set_gabarit(gab)
        self._nomme_boutons()

    def _nomme_boutons(self) -> None:
        from html import escape
        self.w_enregistrer.setEnabled(bool(self._base_nom))
        if self._base_nom:
            self.w_gabarit.setText(
                f'Gabarit : <b>{escape(self._base_nom)}</b>')
        elif self._ambigus:
            self.w_gabarit.setText(
                'Plusieurs gabarits portent ces postes ('
                + ', '.join(escape(n) for n in self._ambigus)
                + ') : rangez celui-ci comme nouveau, ou reprenez-le au '
                'gestionnaire dans le bon.')
        else:
            self.w_gabarit.setText(
                'Ce montage ne vient d\'aucun gabarit connu : rangez-le '
                'comme nouveau.')

    def _plie(self, ouvert: bool) -> None:
        self.w_plier.setArrowType(Qt.DownArrow if ouvert else Qt.RightArrow)
        self.w_boite.setVisible(ouvert)
        from .session import settings
        settings().setValue('montage/reglages_ouverts', bool(ouvert))

    def _applique_reglages(self) -> None:
        """Un réglage a bougé : le montage posé le suit, références
        intactes."""
        from . import gabarits, theme
        try:
            gab = gabarits.verifier(self.w_reglages.gabarit())
        except gabarits.GabaritError as exc:
            self._etat.setText(f'<span style="color:{theme.current().warn}">'
                               f'{exc}</span>')
            return
        if not appliquer(self._paires(), gab):
            return
        self._reglages_gab = gab
        self.changed.emit()

    def enregistrer_gabarit(self, nom: str = '') -> str:
        """Écrit le montage chargé dans son gabarit — ou, `nom` donné,
        dans un gabarit nouveau. Rend le nom écrit, vide si rien ne l'a
        été."""
        from . import gabarits, theme
        try:
            gab = gabarits.depuis_formes(
                self._paires(), self._reglages_gab,
                references=self.w_avec_refs.isChecked())
            if nom:
                gab['nom'] = gabarits.nom_libre(
                    nom, (g['nom'] for g in gabarits.charger()))
                ancien = ''
            elif self._base_nom:
                gab['nom'] = ancien = self._base_nom
            else:
                return ''
            gabarits.remplacer(gab, ancien)
        except (gabarits.GabaritError, OSError) as exc:
            self._etat.setText(f'<span style="color:{theme.current().warn}">'
                               f'Gabarit non écrit : {exc}</span>')
            return ''
        self._base_nom = gab['nom']
        self._origines[frozenset(self._ids)] = gab['nom']
        self._ambigus = []
        # les réglages montrés sont ceux qu'on vient d'écrire, références
        # proposées comprises : une retouche suivante ne doit pas revenir
        # aux anciennes
        self._reglages_gab = gab
        self.w_reglages.set_gabarit(gab)
        self._nomme_boutons()
        self.saved.emit(gab['nom'])
        return gab['nom']

    def _demande_nouveau(self) -> None:
        from . import gabarits
        propose = gabarits.nom_libre(
            f'{self._base_nom or "Montage"} retouché',
            (g['nom'] for g in gabarits.charger()))
        nom, ok = QInputDialog.getText(self, 'Nouveau montage',
                                       'Nom du montage :', text=propose)
        if ok and nom.strip():
            self.enregistrer_gabarit(nom.strip())

    def _rebatir(self) -> None:
        """Refait les champs pour les postes courants."""
        while self._form.count():
            item = self._form.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._champs = {}
        for poste in self._postes:
            champ = QLineEdit()
            champ.setClearButtonEnabled(True)
            champ.editingFinished.connect(
                lambda p=poste.cle: self._applique(p))
            champ.returnPressed.connect(
                lambda p=poste.cle: self._applique(p))
            self._champs[poste.cle] = champ
            self._form.addRow(f'{poste.libelle} :', champ)
        self._titre.setText(
            f'<b>Montage à {len(self._postes)} DataMatrix</b>')

    def codes(self) -> list:
        """Les symboles chargés, du haut vers le bas."""
        return [self._codes[p.cle] for p in self._postes
                if p.cle in self._codes]

    def focus_for(self, shape_id: str) -> bool:
        """Le champ du poste dont `shape_id` est le code — ou le texte qui
        le suit — prend le focus, référence sélectionnée. Faux sinon."""
        for cle, code in self._codes.items():
            if code.id == shape_id:
                break
        else:
            textes = [s for s in (getattr(self._document, 'shapes', ())
                                  if self._document is not None else ())
                      if s.id == shape_id]
            suit = getattr(textes[0], 'follows', '') if textes else ''
            cle = next((c for c, code in self._codes.items()
                        if code.id == suit), None)
            if cle is None:
                return False
        champ = self._champs.get(cle)
        if champ is None:
            return False
        champ.setFocus(Qt.OtherFocusReason)
        champ.selectAll()
        return True

    def focus_first(self) -> bool:
        """Le premier poste prend le focus — au moment où l'on pose le
        montage, c'est sa référence qu'on vient taper."""
        for poste in self._postes:
            champ = self._champs.get(poste.cle)
            if champ is not None:
                champ.setFocus(Qt.OtherFocusReason)
                champ.selectAll()
                return True
        return False

    def _dit_etat(self, shapes) -> None:
        """Dit si chaque texte suit bien son propre code."""
        from . import theme
        textes = [s for s in shapes if isinstance(s, Text)]
        attendus = {c.id for c in self._codes.values()}
        suivis = {t.follows for t in textes if t.follows}
        palette = theme.current()
        if suivis == attendus and len(suivis) == len(self._codes):
            self._etat.setText(
                f'<span style="color:{palette.ok}">Chaque texte suit son '
                f'propre code.</span>')
        else:
            manque = len(attendus - suivis)
            self._etat.setText(
                f'<span style="color:{palette.warn}"><b>Attention :</b> '
                f'{manque} code(s) sans texte lié. Le texte en clair ne '
                f'suivra pas la référence.</span>')

    # -- édition -------------------------------------------------------

    def _applique(self, cle: str) -> None:
        code = self._codes.get(cle)
        if self._guard or code is None:
            return
        valeur = self._champs[cle].text().strip()
        if not valeur or valeur == code.data:
            return
        code.data = valeur
        self._propage(code)
        self.changed.emit()

    def _propage(self, code) -> None:
        """Met le texte lié d'accord avec la donnée du symbole.

        Passe par `codeplate.propagate_data`, qui tient cette règle pour
        toute l'application : la réécrire ici en ferait une seconde
        version, et deux versions d'une règle finissent par diverger.
        """
        if self._document is None:
            return
        from .codeplate import propagate_data
        propagate_data(self._document, code)

    def _applique_tous(self) -> None:
        """Reprend la référence du premier poste sur tous les autres."""
        if not self._postes:
            return
        valeur = self._champs[self._postes[0].cle].text().strip()
        if not valeur:
            return
        self._guard = True
        for poste in self._postes:
            self._champs[poste.cle].setText(valeur)
        self._guard = False
        change = False
        for poste in self._postes:
            code = self._codes.get(poste.cle)
            if code is not None and code.data != valeur:
                code.data = valeur
                self._propage(code)
                change = True
        if change:
            self.changed.emit()
