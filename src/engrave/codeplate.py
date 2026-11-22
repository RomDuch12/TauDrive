"""Plaque codée : code et texte ajustés à leurs cadres.

Reproduit la façon de faire des plaques de production. Le DXF de
référence `DataMatrix.dxf` en montre les deux moitiés :

* une plaque **type**, où deux cadres réservent la place — l'un pour le
  symbole, l'autre pour le texte lisible — et où chacun remplit le sien.
  Le symbole y est un DataMatrix ECC200 rectangulaire 8 × 18 dans une
  fenêtre de 15 × 7 mm, le texte « B000174 » dans une fenêtre de
  8,07 × 1,54 mm ;
* la même plaque avec **les cadres vides**, qui donne l'encombrement à ne
  pas dépasser.

C'est ce raisonnement qui est appliqué ici : on part des fenêtres
disponibles, et le contenu s'y ajuste. L'inverse — choisir une taille de
module ou de police puis espérer que ça rentre — est ce qui produit les
marquages qui débordent.

**Aucune fenêtre modale.** La plaque est posée d'un geste, avec les cotes
de la sélection ou celles de la dernière fois, et tout se règle ensuite
dans la colonne *Propriétés* : symbologie, donnée, fenêtre, position,
remplissage, et la recette appliquée. Un dialogue de plus obligerait à
tout décider avant de rien voir.
"""
from __future__ import annotations

from . import geometry as G, textvec
from .model import Code, Rect, Recipe, Shape, Text

#: Cotes de départ, relevées sur la plaque de production
#: (`DataMatrix.dxf`, symbole 15 × 7 mm dans un cadre de 16 × 8 mm).
DEFAULT_CODE_WINDOW = (15.0, 7.0)
DEFAULT_TEXT_WINDOW = (8.071, 1.538)

#: Marge du cadre englobant, en mm. La plaque de production porte un cadre
#: de 16 × 8 mm autour d'un symbole de 15 × 7 : un demi-millimètre.
DEFAULT_FRAME_MARGIN = 0.5

#: Symbologies posées **avec leur cadre englobant**, et donc gravées en
#: négatif : le fond est creusé, les modules restent en relief.
#:
#: C'est le rendu de la plaque de production — un DataMatrix ne se lit
#: bien sur un métal clair qu'en négatif, le contraste venant du fond
#: dépoli et non de traits creusés dans le brut. Un QR, un Code 39 ou un
#: EAN-13 se posent nus : ils vivent sur des étiquettes, où le fond est
#: déjà clair et où creuser toute la surface serait du temps machine
#: dépensé pour rien.
FRAMED_KINDS = ('datamatrix',)


def default_frame(kind: str) -> str:
    """Cadre que porte une plaque de cette symbologie : 'rect' ou 'none'."""
    return 'rect' if kind in FRAMED_KINDS else 'none'

#: Position du centre du texte lisible **par rapport au centre du code**.
#:
#: Relevée sur la plaque de production, où le cadre du texte est centré en
#: (34,9285 ; 26,272) et celui du code en (50 ; 30). Ce n'est pas une
#: disposition à réinventer : c'est celle des pièces déjà en service, et
#: le texte doit tomber au même endroit d'une plaque à l'autre.
DEFAULT_TEXT_OFFSET = (-15.07, -3.73)


def frame_of(shape: Shape | None) -> tuple[float, float, float, float] | None:
    """Fenêtre offerte par une forme : (x, y, largeur, hauteur).

    Un rectangle donne ses cotes ; toute autre forme portant un cadre
    rectangulaire imposé donne les cotes de ce cadre.
    """
    if isinstance(shape, Rect):
        return shape.x, shape.y, shape.width, shape.height
    if shape is not None and shape.frame == 'rect' and shape.frame_w > 0:
        return shape.x, shape.y, shape.frame_w, shape.frame_h or shape.frame_w
    return None


def frames_of(shapes: list[Shape]) -> tuple[tuple | None, tuple | None]:
    """Répartit les fenêtres d'une sélection : (code, texte).

    La plus grande accueille le symbole, la plus petite le texte — c'est
    la disposition du DXF de production, et la seule qui ait un sens : un
    code demande bien plus de surface qu'une ligne de caractères.
    """
    found = [f for f in (frame_of(s) for s in shapes) if f]
    if not found:
        return None, None
    found.sort(key=lambda f: f[2] * f[3], reverse=True)
    return found[0], (found[1] if len(found) > 1 else None)


def is_plate(shapes: list[Shape]) -> bool:
    """Vrai si cette sélection est **une plaque codée** : un code, son texte.

    Sert à décider ce que montre la colonne *Propriétés*. Une plaque est
    un groupe, mais un groupe dont on vient toujours régler un membre
    précis : la donnée sur le symbole, la police sur le texte. Lui
    présenter le formulaire de lot obligerait à un clic de plus avant
    chaque frappe.

    La reconnaissance passe par le lien `follows`, et non par le groupe :
    c'est lui qui dit que ce texte est *le* texte de ce code, et il
    survit au dégroupage.
    """
    codes = [s for s in shapes if isinstance(s, Code)]
    if len(codes) != 1 or len(shapes) < 2:
        return False
    code = codes[0]
    return all(s is code
               or (isinstance(s, Text) and s.follows == code.id)
               for s in shapes)


def fit_text(content: str, width: float, height: float, *,
             font_path: str = '', stretch_to_fill: bool = False) -> Text:
    """Texte réglé pour tenir dans une fenêtre, sans la dépasser.

    La hauteur de capitale part de la hauteur de la fenêtre ; si le texte
    est alors trop large, elle est réduite dans la même proportion — ou,
    si on le demande, c'est l'étirement horizontal qui absorbe l'écart.

    Le calcul passe par la géométrie réellement vectorisée, pas par la
    largeur d'avance de la police : ce sont les contours gravés qui
    doivent tenir dans le cadre, et eux seuls.
    """
    shape = Text(text=content, size_mm=max(0.1, height), font_path=font_path,
                 align='center', valign='middle', stretch=1.0)
    lines = content.count('\n') + 1
    if lines > 1:
        shape.size_mm = max(0.1, height / (lines * shape.line_spacing))

    contours = textvec.layout(shape.text, shape.size_mm, shape.font_path,
                              shape.align, shape.valign, shape.line_spacing,
                              measured=shape.cap_measured)
    box = G.bounds(contours) if contours else None
    if box is None:
        return shape

    ink_w, ink_h = box[2] - box[0], box[3] - box[1]
    if ink_h > 0 and ink_h > height:
        shape.size_mm *= height / ink_h
        ink_w *= height / ink_h
    if ink_w > width > 0:
        if stretch_to_fill:
            shape.stretch = width / ink_w
        else:
            shape.size_mm *= width / ink_w
    return shape


def build_plate(recipe: Recipe, *,
                frame: tuple[float, float, float, float] | None = None,
                text_frame: tuple[float, float, float, float] | None = None,
                data: str = 'B{n:06}', label: str = '',
                kind: str = 'datamatrix', dm_shape: str = 'auto',
                quiet_modules: int = 0, with_text: bool = True,
                stretch_text: bool = False, code_frame: str = 'auto',
                frame_margin_mm: float = DEFAULT_FRAME_MARGIN
                ) -> list[Shape]:
    """Le code — et son texte — ajustés à leurs fenêtres.

    Rend les formes dans l'ordre : symbole, puis texte. L'appelant les
    groupe : elles vont ensemble sur la pièce, et le groupe les fait
    déplacer, redimensionner et changer de recette d'un bloc.

    `code_frame` vaut `'auto'` — le cadre englobant selon la symbologie,
    voir `FRAMED_KINDS` — ou impose `'rect'`, `'circle'` ou `'none'`.

    **Le cadre entoure le symbole seul.** Le texte lisible reste nu : il
    se grave en plein, et l'enfermer à son tour creuserait un second
    rectangle autour de sept caractères — de la surface dépensée pour
    rien, et une plaque qui ne ressemblerait plus à celles en service.
    """
    x, y, w, h = frame or (0.0, 0.0, *DEFAULT_CODE_WINDOW)
    porte_cadre = (default_frame(kind) if code_frame == 'auto'
                   else code_frame)
    code = Code(x=x, y=y, recipe=recipe, kind=kind, data=data,
                dm_shape=dm_shape, quiet_modules=quiet_modules,
                fit_w_mm=w, fit_h_mm=h,
                frame=porte_cadre, frame_margin_mm=frame_margin_mm)

    from .toolpath import code_matrix
    if not code_matrix(code):
        return []
    out: list[Shape] = [code]

    if with_text:
        dx, dy = DEFAULT_TEXT_OFFSET
        tx, ty, tw, th = text_frame or (x + dx, y + dy, *DEFAULT_TEXT_WINDOW)
        text = fit_text(label or data, tw, th, stretch_to_fill=stretch_text)
        text.x, text.y = tx, ty
        text.recipe = recipe
        # nu, quel que soit le cadre du symbole : la marge de 0,5 mm
        # appartient au code, pas à la ligne de caractères
        text.frame = 'none'
        # le texte reproduit la donnée du symbole et la suivra : les deux
        # ne peuvent pas diverger, sous peine de marquer une pièce dont le
        # code et le numéro en clair se contredisent
        text.follows = code.id
        out.append(text)
    return out


def propagate_data(shapes, code: Code) -> list[Text]:
    """Met les textes qui suivent `code` d'accord avec sa donnée.

    Rend les textes effectivement modifiés. C'est **le seul endroit** qui
    tient la promesse de `follows` : un texte lisible qui contredirait son
    symbole est pire que pas de texte du tout, la pièce partant avec deux
    numéros différents — l'un lisible à l'œil, l'autre au lecteur.

    `shapes` accepte un document ou une simple liste : la règle ne dépend
    pas de l'endroit où les formes sont rangées.
    """
    liste = getattr(shapes, 'shapes', shapes)
    touches = []
    for forme in liste:
        if (isinstance(forme, Text) and forme.follows == code.id
                and forme.text != code.data):
            forme.text = code.data
            touches.append(forme)
    return touches


# --------------------------------------------------------------------------
# La prochaine plaque, réglée d'avance
# --------------------------------------------------------------------------

def _qt_form():
    """Le formulaire, construit à la demande : le reste du module n'a pas
    besoin de Qt, et l'autotest mesure les plaques sans lui."""
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel,
                                   QPushButton, QVBoxLayout, QWidget)
    from . import session, theme
    from .widgets import Combo, Spin

    class PlateDefaultsForm(QWidget):
        """Cadre, taille, position et texte de **la prochaine plaque**.

        Posé en tête du menu de la flèche du bouton Code : on y règle une
        fois ce que vaudront les plaques suivantes, sans en poser une pour
        la retoucher ensuite. Chaque champ s'enregistre aussitôt — il n'y
        a rien à valider, et rien à perdre en refermant le menu.

        Les plaques déjà posées n'y sont pas touchées. Ce qu'on retouche
        sur l'une d'elles, en revanche — cadre, taille, position, texte —
        vient s'inscrire ici : la suivante reprend la dernière retouche.
        """

        #: Un réglage a changé : les valeurs sont déjà enregistrées.
        changed = Signal()
        #: L'opérateur demande à reprendre la plaque sélectionnée.
        capture_asked = Signal()

        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self._guard = False
            dehors = QVBoxLayout(self)
            dehors.setContentsMargins(10, 6, 10, 6)
            titre = QLabel('<b>Prochaine plaque</b>')
            titre.setTextFormat(Qt.RichText)
            dehors.addWidget(titre)
            form = QFormLayout()
            theme.tidy_form(form)
            self.w_cadre = Combo()
            for cle, libelle in (('auto', 'selon le code'),
                                 ('rect', 'rectangle'),
                                 ('circle', 'cercle'),
                                 ('none', 'aucun')):
                self.w_cadre.addItem(libelle, cle)
            self.w_cadre.setToolTip(
                'Cadre englobant gravé en négatif autour du symbole.\n'
                '« selon le code » : rectangle pour un DataMatrix, rien pour '
                'les autres.')
            self.w_marge = Spin(0.5, 0.0, 20.0, 0.1, 3, ' mm')
            self.w_marge.setToolTip('Jour entre le symbole et son cadre.')
            self.w_l = Spin(15.0, 0.5, 200.0, 0.5, 3, ' mm')
            self.w_h = Spin(7.0, 0.5, 200.0, 0.5, 3, ' mm')
            self.w_x = Spin(0.0, -500.0, 500.0, 0.5, 3, ' mm')
            self.w_y = Spin(0.0, -500.0, 500.0, 0.5, 3, ' mm')
            self.w_tdx = Spin(-15.07, -200.0, 200.0, 0.5, 3, ' mm')
            self.w_tdy = Spin(-3.73, -200.0, 200.0, 0.5, 3, ' mm')
            self.w_tdx.setToolTip('Écart du centre du texte au centre du '
                                  'code, horizontalement.')
            self.w_tdy.setToolTip('Écart du centre du texte au centre du '
                                  'code, verticalement.')

            def paire(a, b):
                rangee = QWidget()
                boite = QHBoxLayout(rangee)
                boite.setContentsMargins(0, 0, 0, 0)
                boite.setSpacing(4)
                boite.addWidget(a)
                boite.addWidget(QLabel('×' if a is self.w_l else '/'))
                boite.addWidget(b)
                return rangee

            form.addRow('Cadre', self.w_cadre)
            form.addRow('Marge', self.w_marge)
            form.addRow('Taille L × H', paire(self.w_l, self.w_h))
            form.addRow('Centre X / Y', paire(self.w_x, self.w_y))
            form.addRow('Texte dX / dY', paire(self.w_tdx, self.w_tdy))
            dehors.addLayout(form)
            self.w_reprendre = QPushButton('Reprendre la plaque sélectionnée')
            self.w_reprendre.setToolTip(
                'Inscrit ici le cadre, la taille, la position et le texte '
                'de la plaque sélectionnée.')
            self.w_reprendre.clicked.connect(self.capture_asked.emit)
            dehors.addWidget(self.w_reprendre)
            note = QLabel('Valeurs reprises par la prochaine plaque posée. '
                          'Retoucher une plaque les met à jour.')
            note.setWordWrap(True)
            note.setStyleSheet(theme.css('text_dim', theme.PETIT_PT))
            dehors.addWidget(note)
            self.w_cadre.currentIndexChanged.connect(self._enregistre)
            for champ in (self.w_marge, self.w_l, self.w_h, self.w_x,
                          self.w_y, self.w_tdx, self.w_tdy):
                champ.valueChanged.connect(self._enregistre)
            self.load()

        def load(self) -> None:
            """Relit les réglages retenus."""
            d = session.code_defaults()
            self._guard = True
            try:
                self.w_cadre.setCurrentIndex(
                    max(0, self.w_cadre.findData(d['code_frame'])))
                self.w_marge.setValue(d['frame_margin'])
                x, y, w, h = d['frame']
                self.w_x.setValue(x)
                self.w_y.setValue(y)
                self.w_l.setValue(w)
                self.w_h.setValue(h)
                self.w_tdx.setValue(d['text_offset'][0])
                self.w_tdy.setValue(d['text_offset'][1])
            finally:
                self._guard = False

        def _enregistre(self, *_) -> None:
            if self._guard:
                return
            d = session.code_defaults()
            _dx, _dy, tw, th = d['text_offset']
            session.remember_code(
                frame=(self.w_x.value(), self.w_y.value(),
                       self.w_l.value(), self.w_h.value()),
                code_frame=self.w_cadre.currentData() or 'auto',
                frame_margin=self.w_marge.value(),
                text_offset=(self.w_tdx.value(), self.w_tdy.value(), tw, th))
            self.changed.emit()

    return PlateDefaultsForm


def plate_defaults_form(parent=None):
    """Le formulaire « Prochaine plaque ». Voir `_qt_form`."""
    return _qt_form()(parent)


def plate_settings(code, texte=None, retenu: str = 'auto') -> dict:
    """Ce qu'une plaque posée apprend à la suivante : cadre, taille,
    position et place du texte. Rend des arguments de
    `session.remember_code`.

    Le cadre reste « selon le code » tant qu'il est celui que le code
    aurait eu de lui-même : retenir « rect » parce qu'un DataMatrix en
    porte un ferait encadrer — et graver en négatif — le QR suivant.

    `retenu` est le cadre déjà retenu : s'il donne ce cadre-là à ce code,
    il est gardé — un « rectangle » choisi pour toutes les plaques ne
    redevient pas « selon le code » parce qu'on a retouché un DataMatrix.

    Une plaque tournée n'apprend pas la place de son texte : l'écart
    mesuré serait tourné, et la plaque suivante, droite, le poserait de
    travers.
    """
    attendu = default_frame(code.kind) if retenu == 'auto' else retenu
    cadre = retenu if code.frame == attendu else code.frame
    reglages = {'code_frame': cadre,
                'frame_margin': code.frame_margin_mm}
    if code.fit_w_mm > 0 and code.fit_h_mm > 0:
        reglages['frame'] = (code.x, code.y, code.fit_w_mm, code.fit_h_mm)
    if texte is not None and not (code.rotation_deg or texte.rotation_deg):
        fenetre = text_window(texte)
        if fenetre:
            reglages['text_offset'] = (texte.x - code.x, texte.y - code.y,
                                       *fenetre)
    return reglages


def text_window(texte) -> tuple[float, float] | None:
    """La fenêtre qui, rendue à `fit_text`, redonne ce texte à sa taille.

    Ce n'est **pas** l'encre du texte posé. Elle porte le numéro
    substitué (« B000001 »), plus étroit que le gabarit (« B{n:06} »)
    que `fit_text` mesure : retenue telle quelle, chaque retouche
    rétrécissait le texte de la plaque suivante d'un cinquième — 1,17,
    0,91, 0,71 mm… La fenêtre est donc l'encre du **gabarit** à la
    taille du texte, mesurée comme `fit_text` mesure — police par
    défaut, centré, sans étirement —, et rehaussée à la hauteur de
    capitale quand l'encre est plus basse : `fit_text` part de la hauteur
    de la fenêtre.
    """
    if not texte.text or texte.size_mm <= 0:
        return None
    modele = Text(text=texte.text, size_mm=texte.size_mm, align='center',
                  valign='middle', stretch=1.0)
    contours = textvec.layout(modele.text, modele.size_mm, modele.font_path,
                              modele.align, modele.valign,
                              modele.line_spacing,
                              measured=modele.cap_measured)
    box = G.bounds(contours) if contours else None
    if box is None:
        return None
    lignes = modele.text.count('\n') + 1
    depart = modele.size_mm * (lignes * modele.line_spacing
                               if lignes > 1 else 1.0)
    # un millionième de plus en largeur, pour que l'arrondi ne fasse
    # pas réduire `fit_text` ; la hauteur, elle, est rendue exacte
    return ((box[2] - box[0]) * (1 + 1e-6), max(depart, box[3] - box[1]))
