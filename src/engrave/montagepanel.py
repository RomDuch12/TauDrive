"""Gestionnaire de montages / Fixture manager.

Deux portes sur les mêmes gabarits — voir `gabarits` :

* **la flèche du bouton Montage** — `ProchainMontage`. Le montage que
  pose le bouton, réglé d'avance : cadre, marge, taille, positions,
  place du texte. Chaque champ s'enregistre aussitôt, comme la
  prochaine plaque au bout de la flèche du bouton Code ;
* **le gestionnaire**, à côté de la bibliothèque — `MontageManager`.
  Tous les montages du poste : créés, dupliqués, rangés, supprimés,
  importés, édités jusqu'au dernier champ, avec leur aperçu. Il prend
  la place du plan de travail, comme la bibliothèque, et enregistre sur
  demande, comme le gestionnaire de process : on y fait des essais, on
  y supprime, et rien ne doit partir sur le disque avant qu'on le dise.

**Un montage posé se reprend.** Retouché sur le plan — déplacé, cadre
changé, texte agrandi —, il se relit en gabarit (`gabarits.depuis_formes`)
depuis le formulaire de la pose, la flèche ou le gestionnaire.

Les deux portes écrivent le même fichier. Le gestionnaire ne quitte donc
pas les lieux avec des modifications en suspens : il demande de les
enregistrer ou de les abandonner, et la flèche reste verrouillée tant
qu'il en a.
"""
from __future__ import annotations

import copy
import json
import pathlib

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QMessageBox,
                               QPushButton, QScrollArea, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import gabarits, montage, theme
from .widgets import Combo


def _nombre(texte: str) -> float:
    """Un nombre tapé à la française ou non : « 23,2 » vaut « 23.2 »."""
    return float(str(texte).strip().replace(',', '.').replace(' ', ''))


def _ecrit(v: float) -> str:
    """Une cote à trois décimales au plus, virgule décimale."""
    return f'{float(v):.3f}'.rstrip('0').rstrip('.').replace('.', ',')


# --------------------------------------------------------------------------
# Au bout de la flèche
# --------------------------------------------------------------------------

class ProchainMontage(QWidget):
    """Le montage que pose le bouton, réglé d'avance.

    Posé en tête du menu de la flèche du bouton Montage. On y choisit le
    montage que posera le bouton — le choisir le met en tête de liste —
    et l'on y règle ses cotes sans le poser pour le retoucher ensuite.
    Chaque champ s'enregistre aussitôt dans le gabarit : il n'y a rien à
    valider, et rien à perdre en refermant le menu. La copie
    `montages.avant.json` garde l'état d'avant la première retouche de
    la séance.
    """

    #: L'opérateur demande à reprendre le montage sélectionné au plan.
    capture_asked = Signal()
    #: Le fichier des gabarits vient d'être écrit.
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._guard = False
        self._nom = ''
        dehors = QVBoxLayout(self)
        dehors.setContentsMargins(10, 6, 10, 6)
        titre = QLabel('<b>Prochain montage</b>')
        titre.setTextFormat(Qt.RichText)
        dehors.addWidget(titre)
        form = QFormLayout()
        theme.tidy_form(form)
        self.w_choix = Combo()
        self.w_choix.setToolTip(
            'Le montage que pose le bouton. En choisir un autre le met en '
            'tête de liste.')
        self.w_choix.currentIndexChanged.connect(self._choisi)
        form.addRow('Montage', self.w_choix)
        dehors.addLayout(form)
        self.w_reglages = montage.ReglagesMontage()
        self.w_reglages.changed.connect(self._enregistre)
        dehors.addWidget(self.w_reglages)
        self.w_reprendre = QPushButton('Reprendre le montage sélectionné')
        self.w_reprendre.setToolTip(
            'Inscrit dans ce gabarit le montage sélectionné au plan, tel '
            'qu\'il est posé :\ncadre, marge, taille, positions, place du '
            'texte.')
        self.w_reprendre.clicked.connect(self.capture_asked.emit)
        dehors.addWidget(self.w_reprendre)
        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        dehors.addWidget(self.w_note)
        self.load()

    def load(self) -> None:
        """Relit les gabarits ; montre celui que pose le bouton."""
        liste = gabarits.charger()
        self._guard = True
        try:
            self.w_choix.clear()
            for g in liste:
                self.w_choix.addItem(g['nom'])
            self.w_choix.setCurrentIndex(0)
        finally:
            self._guard = False
        self._nom = liste[0]['nom']
        self.w_reglages.set_gabarit(liste[0])
        self._dit(f'Chaque champ s\'enregistre dans « {self._nom} ». '
                  f'Le formulaire de la pose fait de même pour un montage '
                  f'retouché.')

    def set_locked(self, pourquoi: str = '') -> None:
        """Verrouille le formulaire, en disant pourquoi — ou le rouvre."""
        libre = not pourquoi
        for w in (self.w_choix, self.w_reglages, self.w_reprendre):
            w.setEnabled(libre)
        if pourquoi:
            self._dit(pourquoi, alerte=True)

    def _dit(self, texte: str, alerte: bool = False) -> None:
        self.w_note.setText(texte)
        self.w_note.setStyleSheet(
            f'color:{theme.current().warn};' if alerte
            else theme.css('text_dim', theme.PETIT_PT))

    def _choisi(self, index: int) -> None:
        if self._guard or index < 0:
            return
        try:
            gabarits.mettre_en_tete(self.w_choix.itemText(index))
        except (gabarits.GabaritError, OSError) as exc:
            self._dit(f'Non enregistré : {exc}', alerte=True)
            return
        self.load()
        self.changed.emit()

    def _enregistre(self) -> None:
        try:
            gabarits.remplacer(self.w_reglages.gabarit(), self._nom)
        except (gabarits.GabaritError, OSError) as exc:
            self._dit(f'Non enregistré : {exc}', alerte=True)
            return
        self.changed.emit()


# --------------------------------------------------------------------------
# L'aperçu
# --------------------------------------------------------------------------

class ApercuMontage(QWidget):
    """Le montage tel qu'il sera posé, avec le nom et l'ordonnée de
    chaque poste.

    La croix marque le centre du champ : un montage se règle par rapport
    à lui, et c'est en le voyant qu'on remarque un centre resté à 30 mm.
    """

    #: Place laissée à droite pour le nom des postes, en pixels.
    ETIQUETTES_PX = 120

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(300, 260)
        self._traits: list = []
        self._postes: list = []
        self._bounds = None
        self._note = 'Aucun montage'

    def montre(self, gab: dict | None, recipe=None, note: str = '') -> None:
        """Construit le montage et le peint. `gab` vide : la note seule."""
        self._traits, self._postes, self._bounds = [], [], None
        self._note = note or 'Aucun montage'
        if gab:
            from .geometry import bounds
            from .model import default_recipe
            from .toolpath import shape_extent, shape_polylines
            erreur = ''
            try:
                formes = montage.build(recipe or default_recipe(), gabarit=gab)
            except (gabarits.GabaritError, KeyError, TypeError,
                    ValueError) as exc:
                formes, erreur = [], str(exc)
            if not formes:
                self._note = erreur or 'Donnée impossible à encoder'
            for forme in formes:
                self._traits.extend(shape_polylines(forme))
            for code, _texte in montage.pairs(formes):
                boite = shape_extent(code)
                if boite is not None:
                    self._postes.append((str(code.role), code.y, boite))
            if self._traits:
                b = bounds(self._traits)
                # le centre du champ reste en vue
                self._bounds = (min(b[0], 0.0), min(b[1], 0.0),
                                max(b[2], 0.0), max(b[3], 0.0))
        self.update()

    def emprise(self):
        """Largeur et hauteur du montage, en mm — None sans montage."""
        if not self._traits:
            return None
        from .geometry import bounds
        b = bounds(self._traits)
        return b[2] - b[0], b[3] - b[1]

    def paintEvent(self, event) -> None:
        palette = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(palette.canvas))
        if self._bounds is None:
            p.setPen(QColor(palette.text_dim))
            p.drawText(QRectF(self.rect()).adjusted(12, 12, -12, -12),
                       Qt.AlignCenter | Qt.TextWordWrap, self._note)
            return
        x1, y1, x2, y2 = self._bounds
        marge = 22
        zone = QRectF(self.rect()).adjusted(marge, marge,
                                            -marge - self.ETIQUETTES_PX,
                                            -marge)
        echelle = min(zone.width() / max(x2 - x1, 1e-6),
                      zone.height() / max(y2 - y1, 1e-6))
        dx = zone.center().x() - (x1 + x2) / 2 * echelle
        dy = zone.center().y() + (y1 + y2) / 2 * echelle

        def ecran(x, y):
            return QPointF(x * echelle + dx, -y * echelle + dy)

        # la croix du centre du champ
        croix = QPen(QColor(palette.text_dim), 1.0, Qt.DashLine)
        croix.setCosmetic(True)
        p.setPen(croix)
        o = ecran(0.0, 0.0)
        p.drawLine(QPointF(o.x() - 9, o.y()), QPointF(o.x() + 9, o.y()))
        p.drawLine(QPointF(o.x(), o.y() - 9), QPointF(o.x(), o.y() + 9))

        chemin = QPainterPath()
        for poly in self._traits:
            if len(poly) < 2:
                continue
            chemin.moveTo(ecran(*poly[0]))
            for pt in poly[1:]:
                chemin.lineTo(ecran(*pt))
        trait = QPen(QColor(palette.path), 1.0)
        trait.setCosmetic(True)
        p.setPen(trait)
        p.drawPath(chemin)

        p.setPen(QColor(palette.text_dim))
        for nom, y, boite in self._postes:
            bout = ecran(boite[2], y)
            p.drawText(QRectF(bout.x() + 8, bout.y() - 9,
                              self.ETIQUETTES_PX, 18),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       f'{nom}  y {_ecrit(y)}')


# --------------------------------------------------------------------------
# Le gestionnaire
# --------------------------------------------------------------------------

class MontageManager(QWidget):
    """Tous les montages du poste : liste, éditeur, aperçu.

    Il prend la place du plan de travail, comme la bibliothèque. La liste
    est l'ordre de la flèche du bouton Montage, et le premier est celui
    que pose le bouton. *Enregistrer* écrit le fichier, *Rétablir* le
    relit ; rien ne part sur le disque avant.
    """

    done = Signal()
    #: Poser ce gabarit sur le plan de travail.
    pose_asked = Signal(dict)
    #: Reprendre le montage sélectionné au plan dans le gabarit courant.
    capture_asked = Signal()
    #: Le fichier vient d'être écrit — nombre de montages.
    saved = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Gestionnaire de montages')
        self._liste: list[dict] = []
        self._index = -1
        self._dirty = False
        self._guard = False
        self._recipe = None
        #: Le fichier tel qu'il était à la dernière lecture : s'il a changé
        #: depuis — flèche, formulaire de la pose, import —, enregistrer ne
        #: l'écrase pas sans le dire.
        self._empreinte: bytes | None = None
        self._minuterie = QTimer(self)
        self._minuterie.setSingleShot(True)
        self._minuterie.setInterval(150)
        self._minuterie.timeout.connect(self._redessine)

        dehors = QVBoxLayout(self)
        tete = QHBoxLayout()
        titre = QLabel('<b>Gestionnaire de montages</b>')
        titre.setTextFormat(Qt.RichText)
        tete.addWidget(titre)
        tete.addStretch(1)
        self.w_etat = QLabel('')
        tete.addWidget(self.w_etat)
        dehors.addLayout(tete)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        dehors.addWidget(split, 1)

        # --- la liste ---
        gauche = QWidget()
        gl = QVBoxLayout(gauche)
        gl.setContentsMargins(0, 0, 0, 0)
        self.w_list = QListWidget()
        self.w_list.setToolTip('L\'ordre de la flèche du bouton Montage. Le '
                               'premier est celui que pose le bouton.')
        self.w_list.currentRowChanged.connect(self._choisi)
        gl.addWidget(self.w_list, 1)
        # deux boutons par ligne : quatre de front se tronquent dans une
        # colonne étroite
        for paire in (
                (('Nouveau', self._nouveau,
                  'Un montage neuf, aux cotes du montage livré'),
                 ('Dupliquer', self._dupliquer,
                  'Une copie du montage choisi, à retoucher sans toucher '
                  'à l\'original')),
                (('Monter', lambda: self._deplace(-1),
                  'Ordre de la flèche du bouton Montage'),
                 ('Descendre', lambda: self._deplace(1),
                  'Ordre de la flèche du bouton Montage')),
                (('Par défaut', self._en_tete,
                  'Le bouton Montage posera celui-ci : il passe en tête'),
                 ('Supprimer', self._supprimer,
                  'Retire le montage choisi — à l\'enregistrement')),
                (('Importer…', self._importer,
                  'Ajoute les montages d\'un fichier montages.json écrit '
                  'sur un autre poste.\nAucun n\'est remplacé : un homonyme '
                  'aux cotes différentes entre sous un autre nom.'),
                 ('Exporter…', self._exporter,
                  'Écrit tous les montages dans un fichier, à relire sur un '
                  'autre poste'))):
            rangee = QHBoxLayout()
            for libelle, slot, astuce in paire:
                b = QPushButton(libelle)
                b.setToolTip(astuce)
                b.clicked.connect(slot)
                rangee.addWidget(b)
                setattr(self, 'b_' + libelle.lower().rstrip('…')
                        .replace(' ', '_').replace('é', 'e'), b)
            gl.addLayout(rangee)
        split.addWidget(gauche)

        # --- l'éditeur ---
        editeur = QWidget()
        ed = QVBoxLayout(editeur)
        ed.setContentsMargins(0, 0, 6, 0)
        g_id = QGroupBox('Identité')
        f = QFormLayout(g_id)
        theme.tidy_form(f)
        self.w_nom = QLineEdit()
        self.w_nom.setToolTip('Le nom paraît au bout de la flèche du bouton '
                              'Montage.')
        self.w_nom.textEdited.connect(self._nom_edite)
        self.w_donnee = QLineEdit()
        self.w_donnee.setToolTip(
            'Référence proposée à la pose, pour chaque poste dont la case '
            '« Référence proposée » est vide.')
        self.w_donnee.textEdited.connect(self._donnee_editee)
        f.addRow('Nom', self.w_nom)
        f.addRow('Référence', self.w_donnee)
        ed.addWidget(g_id)

        g_postes = QGroupBox('Postes, du haut vers le bas')
        vp = QVBoxLayout(g_postes)
        self.w_postes = QTableWidget(0, 4)
        self.w_postes.setHorizontalHeaderLabels(
            ['Poste', 'Y (mm)', 'X (mm)', 'Référence proposée'])
        self.w_postes.verticalHeader().setVisible(False)
        self.w_postes.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.w_postes.setSelectionMode(QAbstractItemView.SingleSelection)
        entete = self.w_postes.horizontalHeader()
        entete.setSectionResizeMode(QHeaderView.ResizeToContents)
        entete.setSectionResizeMode(3, QHeaderView.Stretch)
        self.w_postes.setToolTip(
            'Taper une ordonnée fixe les positions une à une ; l\'entraxe, '
            'plus bas, les rend régulières.\nUne référence proposée vide '
            'reprend celle du montage.')
        self.w_postes.cellChanged.connect(self._cellule)
        vp.addWidget(self.w_postes)
        rangee = QHBoxLayout()
        for libelle, slot, astuce in (
                ('Ajouter', self._ajoute_poste, 'Un poste de plus, en bas'),
                ('Retirer', self._retire_poste, 'Retire le poste choisi'),
                ('Monter', lambda: self._deplace_poste(-1),
                 'Échange le nom et la référence du poste choisi avec ceux '
                 'du poste au-dessus'),
                ('Descendre', lambda: self._deplace_poste(1),
                 'Échange le nom et la référence du poste choisi avec ceux '
                 'du poste au-dessous')):
            b = QPushButton(libelle)
            b.setToolTip(astuce)
            b.clicked.connect(slot)
            rangee.addWidget(b)
            setattr(self, 'b_poste_' + libelle.lower(), b)
        vp.addLayout(rangee)
        self.w_disposition = QLabel('')
        self.w_disposition.setWordWrap(True)
        self.w_disposition.setStyleSheet(theme.css('text_dim',
                                                   theme.PETIT_PT))
        vp.addWidget(self.w_disposition)
        ed.addWidget(g_postes)

        g_reg = QGroupBox('Symbole, cadre, positions et texte')
        vr = QVBoxLayout(g_reg)
        self.w_reglages = montage.ReglagesMontage(complet=True)
        self.w_reglages.changed.connect(self._reglages_edites)
        vr.addWidget(self.w_reglages)
        ed.addWidget(g_reg)
        self.w_erreur = QLabel('')
        self.w_erreur.setWordWrap(True)
        ed.addWidget(self.w_erreur)
        ed.addStretch(1)
        defile = QScrollArea()
        defile.setWidgetResizable(True)
        defile.setWidget(editeur)
        split.addWidget(defile)

        # --- l'aperçu ---
        droite = QWidget()
        dr = QVBoxLayout(droite)
        dr.setContentsMargins(0, 0, 0, 0)
        self.w_apercu = ApercuMontage()
        dr.addWidget(self.w_apercu, 1)
        self.w_info = QLabel('')
        self.w_info.setWordWrap(True)
        self.w_info.setStyleSheet(theme.css('text_dim', theme.PETIT_PT))
        dr.addWidget(self.w_info)
        split.addWidget(droite)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 2)
        split.setSizes([240, 440, 480])

        bas = QHBoxLayout()
        self.w_reprendre = QPushButton('Reprendre le montage sélectionné')
        self.w_reprendre.setToolTip(
            'Inscrit dans le montage choisi celui qui est sélectionné au '
            'plan, tel qu\'il est posé :\ncadre, marge, taille, positions, '
            'place du texte. Dupliquez d\'abord pour garder l\'original.')
        self.w_reprendre.clicked.connect(self.capture_asked.emit)
        self.w_retablir = QPushButton('Rétablir')
        self.w_retablir.setToolTip('Relit les montages enregistrés, en '
                                   'abandonnant les modifications.')
        self.w_retablir.clicked.connect(self._retablir)
        self.w_enregistrer = QPushButton('Enregistrer')
        self.w_enregistrer.setToolTip(
            'Écrit les montages du poste. Le fichier d\'avant la première '
            'écriture de la séance reste à côté : montages.avant.json.')
        self.w_enregistrer.clicked.connect(self.enregistrer)
        self.w_poser = QPushButton('Poser sur le plan')
        self.w_poser.setToolTip('Pose le montage choisi sur le plan de '
                                'travail et y revient.')
        self.w_poser.clicked.connect(self._poser)
        self.w_termine = QPushButton('Terminé')
        self.w_termine.setToolTip('Revient au plan de travail.')
        self.w_termine.clicked.connect(self.done.emit)
        bas.addWidget(self.w_reprendre)
        bas.addStretch(1)
        for b in (self.w_retablir, self.w_enregistrer, self.w_poser,
                  self.w_termine):
            bas.addWidget(b)
        dehors.addLayout(bas)
        self.w_where = QLabel('')
        self.w_where.setWordWrap(True)
        self.w_where.setStyleSheet(theme.css('text_dim', theme.PETIT_PT))
        dehors.addWidget(self.w_where)

    # -- état --------------------------------------------------------------

    def set_recipe(self, recipe) -> None:
        self._recipe = recipe

    def dirty(self) -> bool:
        return self._dirty

    def montages(self) -> list[dict]:
        """La liste en cours d'édition, copiée."""
        return copy.deepcopy(self._liste)

    def courant(self) -> dict | None:
        if 0 <= self._index < len(self._liste):
            return self._liste[self._index]
        return None

    def reload(self, index: int = 0, nom: str = '') -> None:
        """Relit le fichier ; les modifications en suspens sont perdues.

        `nom` reprend ce montage-là où qu'il soit rangé : le fichier a pu
        changer d'ordre — un montage mis en tête au bout de la flèche —,
        et rester au même rang en ferait éditer un autre.
        """
        self._empreinte = self._lit_empreinte()
        self._liste = [copy.deepcopy(g) for g in gabarits.charger()]
        self._dirty = False
        if nom:
            index = next((i for i, g in enumerate(self._liste)
                          if g.get('nom') == nom), index)
        self._remplit_liste(min(max(0, index), len(self._liste) - 1))
        chemin = gabarits.chemin()
        avant = chemin.with_name(gabarits.AVANT)
        self.w_where.setText(
            f'Montages du poste : {chemin}'
            + ('' if chemin.exists() else '   (créé au premier '
               'enregistrement)')
            + (f'\nÉtat d\'avant la séance : {avant.name}'
               if avant.exists() else ''))
        # un fichier illisible, des montages refusés : le dire, plutôt
        # que de laisser croire que la liste est tout le fichier
        etat = gabarits.etat_fichier()
        if etat:
            self.dit(etat, alerte=True)
        self._dit_etat()

    @staticmethod
    def _lit_empreinte() -> bytes | None:
        try:
            return gabarits.chemin().read_bytes()
        except OSError:
            return None

    def relire_si_propre(self) -> None:
        """Le fichier a changé ailleurs : relu, sauf modifications en
        suspens — celles-là, *Enregistrer* les confrontera au fichier."""
        if not self._dirty:
            self.reload(self._index, str((self.courant() or {}).get('nom',
                                                                   '')))

    def dit(self, texte: str, alerte: bool = False) -> None:
        """Un mot sous l'éditeur."""
        self.w_erreur.setText(texte)
        self.w_erreur.setStyleSheet(
            f'color:{theme.current().warn};' if alerte
            else theme.css('text_dim', theme.PETIT_PT))

    def _dit_etat(self) -> None:
        if self._dirty:
            self.w_etat.setText(
                f'<span style="color:{theme.current().warn}">'
                f'Modifications non enregistrées</span>')
        else:
            self.w_etat.setText('')
        erreur = self._erreur_globale()
        self.w_enregistrer.setEnabled(self._dirty and not erreur)
        self.w_retablir.setEnabled(self._dirty)
        nb = len(self._liste)
        self.b_supprimer.setEnabled(nb > 1)
        self.b_monter.setEnabled(self._index > 0)
        self.b_descendre.setEnabled(0 <= self._index < nb - 1)
        self.b_par_defaut.setEnabled(self._index > 0)

    # -- la liste ----------------------------------------------------------

    def _libelle(self, i: int) -> str:
        nom = str(self._liste[i].get('nom', '')) or 'sans nom'
        # « par défaut », comme le bouton qui l'y met : « posé par le
        # bouton » se tronquait dans la colonne
        return nom + ('  — par défaut' if i == 0 else '')

    def _remplit_liste(self, index: int) -> None:
        self._guard = True
        try:
            self.w_list.clear()
            for i in range(len(self._liste)):
                self.w_list.addItem(self._libelle(i))
            self.w_list.setCurrentRow(index)
        finally:
            self._guard = False
        self._choisi(index)

    def _renomme_lignes(self) -> None:
        for i in range(min(self.w_list.count(), len(self._liste))):
            self.w_list.item(i).setText(self._libelle(i))

    def _choisi(self, index: int) -> None:
        if self._guard:
            return
        self._index = index
        self._montre()

    def _montre(self, reglages: bool = True) -> None:
        """Remplit l'éditeur du montage choisi."""
        g = self.courant()
        self._guard = True
        try:
            for w in (self.w_nom, self.w_donnee, self.w_postes,
                      self.w_reglages):
                w.setEnabled(g is not None)
            if g is None:
                self.w_nom.clear()
                self.w_donnee.clear()
                self.w_postes.setRowCount(0)
            else:
                if self.w_nom.text() != g.get('nom', ''):
                    self.w_nom.setText(str(g.get('nom', '')))
                if self.w_donnee.text() != str(g.get('donnee', '')):
                    self.w_donnee.setText(str(g.get('donnee', '')))
                self._remplit_postes(g)
                if reglages:
                    self.w_reglages.set_gabarit(g)
        finally:
            self._guard = False
        self._valide()
        self._dit_etat()
        self._minuterie.start()

    def _remplit_postes(self, g: dict) -> None:
        try:
            ys = gabarits.positions(g)
        except (gabarits.GabaritError, TypeError, ValueError):
            ys = []
        try:
            xs = gabarits.positions_x(g)
        except (gabarits.GabaritError, TypeError, ValueError):
            xs = []
        refs = list(g.get('donnees') or [])
        postes = list(g.get('postes') or [])
        ligne = self.w_postes.currentRow()
        self.w_postes.setRowCount(len(postes))
        for i, nom in enumerate(postes):
            valeurs = (str(nom),
                       _ecrit(ys[i]) if i < len(ys) else '',
                       _ecrit(xs[i]) if i < len(xs) else '',
                       str(refs[i]) if i < len(refs) else '')
            for j, valeur in enumerate(valeurs):
                item = self.w_postes.item(i, j)
                if item is None:
                    item = QTableWidgetItem()
                    self.w_postes.setItem(i, j, item)
                if item.text() != valeur:
                    item.setText(valeur)
                if j in (1, 2):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if 0 <= ligne < len(postes):
            self.w_postes.setCurrentCell(ligne, 0)
        if g.get('positions_y_mm'):
            self.w_disposition.setText(
                'Positions une à une. Changer l\'entraxe, plus bas, les '
                'rend régulières.')
        elif len(postes) > 1:
            self.w_disposition.setText(
                f'Régulier : entraxe {_ecrit(g.get("entraxe_mm", 0))} mm, '
                f'centre {_ecrit(g.get("centre_y_mm", 0))} mm. Taper une '
                f'ordonnée fixe les positions une à une.')
        else:
            self.w_disposition.setText('Un seul poste.')

    # -- édition -----------------------------------------------------------

    def _modifie(self, reglages: bool = True) -> None:
        """Le montage choisi a changé : tout ce qui le montre suit."""
        self._dirty = True
        self._renomme_lignes()
        self._montre(reglages)

    def _nom_edite(self, texte: str) -> None:
        g = self.courant()
        if self._guard or g is None:
            return
        # tel que tapé : rogné ici, l'espace entre deux mots
        # disparaîtrait sous les doigts — il l'est à l'enregistrement
        g['nom'] = texte
        self._modifie()

    def _donnee_editee(self, texte: str) -> None:
        g = self.courant()
        if self._guard or g is None:
            return
        g['donnee'] = texte
        self._modifie()

    def _reglages_edites(self) -> None:
        if self._guard or self.courant() is None:
            return
        self._liste[self._index] = self.w_reglages.gabarit()
        self._modifie(reglages=False)

    def _cellule(self, ligne: int, colonne: int) -> None:
        g = self.courant()
        if self._guard or g is None:
            return
        item = self.w_postes.item(ligne, colonne)
        texte = item.text() if item is not None else ''
        n = len(g['postes'])
        if colonne == 0:
            g['postes'][ligne] = texte.strip() or f'POSTE {ligne + 1}'
        elif colonne in (1, 2):
            try:
                valeur = _nombre(texte)
                if colonne == 1:
                    ys = gabarits.positions(g)
                    ys[ligne] = valeur
                    g['positions_y_mm'] = ys
                    # le formulaire de la pose lit les postes du haut
                    # vers le bas : un poste passé sous son voisin
                    # change de rang, avec son nom et sa référence
                    gabarits.trier_postes(g)
                else:
                    xs = gabarits.positions_x(g)
                    xs[ligne] = valeur
                    if max(xs) - min(xs) < gabarits.JEU_MM:
                        g.pop('positions_x_mm', None)
                        g['x_mm'] = xs[0]
                    else:
                        g['positions_x_mm'] = xs
                        g['x_mm'] = (min(xs) + max(xs)) / 2
            except (ValueError, gabarits.GabaritError):
                self.dit(f'« {texte} » n\'est pas une cote.', alerte=True)
                self._montre()
                return
        else:
            refs = list(g.get('donnees') or [])
            refs += [''] * (n - len(refs))
            refs[ligne] = texte.strip()
            if any(refs):
                g['donnees'] = refs[:n]
            else:
                g.pop('donnees', None)
        self._modifie()

    def _ajoute_poste(self) -> None:
        g = self.courant()
        if g is None:
            return
        try:
            ys = gabarits.positions(g)
            xs = gabarits.positions_x(g)
        except gabarits.GabaritError:
            return
        cles = {gabarits.cle_poste(q) for q in g['postes']}
        nom, k = f'POSTE {len(ys) + 1}', len(ys) + 2
        while gabarits.cle_poste(nom) in cles:
            nom, k = f'POSTE {k}', k + 1
        g['postes'].append(nom)
        # en bas, au pas des autres : les postes en place ne bougent pas
        # — un montage régulier le reste, son centre descend d'un
        # demi-pas
        pas = ((ys[0] - ys[-1]) / (len(ys) - 1) if len(ys) > 1
               else float(g.get('entraxe_mm') or 0.0)) or 10.0
        gabarits.poser_ordonnees(g, ys + [ys[-1] - pas], False)
        if g.get('positions_x_mm'):
            g['positions_x_mm'] = xs + [xs[-1]]
        if g.get('donnees'):
            g['donnees'] = list(g['donnees']) + ['']
        self._modifie()
        self.w_postes.setCurrentCell(len(g['postes']) - 1, 0)

    def _retire_poste(self) -> None:
        g = self.courant()
        ligne = self.w_postes.currentRow()
        # deux postes au moins : un seul ne fait pas un montage, son
        # formulaire ne s'ouvrirait pas
        if g is None or len(g['postes']) <= 2 or not (
                0 <= ligne < len(g['postes'])):
            return
        try:
            ys = gabarits.positions(g)
        except gabarits.GabaritError:
            return
        for cle in ('postes', 'positions_x_mm', 'donnees'):
            valeurs = g.get(cle)
            if valeurs and ligne < len(valeurs):
                valeurs = list(valeurs)
                valeurs.pop(ligne)
                g[cle] = valeurs
        # les autres restent où ils sont : retirer celui du milieu rend
        # les positions une à une
        gabarits.poser_ordonnees(g, ys[:ligne] + ys[ligne + 1:], False)
        self._modifie()

    def _deplace_poste(self, sens: int) -> None:
        """Échange nom et référence proposée avec le voisin : les
        positions, elles, restent celles des places."""
        g = self.courant()
        ligne = self.w_postes.currentRow()
        if g is None:
            return
        autre = ligne + sens
        if not (0 <= ligne < len(g['postes'])
                and 0 <= autre < len(g['postes'])):
            return
        postes = g['postes']
        postes[ligne], postes[autre] = postes[autre], postes[ligne]
        if g.get('donnees'):
            refs = list(g['donnees']) + [''] * len(postes)
            refs[ligne], refs[autre] = refs[autre], refs[ligne]
            g['donnees'] = refs[:len(postes)]
        self._modifie()
        self.w_postes.setCurrentCell(autre, 0)

    # -- montages ----------------------------------------------------------

    def _noms(self) -> list[str]:
        return [str(g.get('nom', '')) for g in self._liste]

    def _insere(self, g: dict, index: int) -> None:
        self._liste.insert(index, g)
        self._dirty = True
        self._remplit_liste(index)

    def _nouveau(self) -> None:
        g = gabarits.verifier({})
        g['nom'] = gabarits.nom_libre('Nouveau montage', self._noms())
        self._insere(g, len(self._liste))
        self.w_nom.setFocus(Qt.OtherFocusReason)
        self.w_nom.selectAll()

    def _dupliquer(self) -> None:
        g = self.courant()
        if g is None:
            return
        copie = copy.deepcopy(g)
        copie['nom'] = gabarits.nom_libre(f'{g.get("nom", "")} (copie)',
                                          self._noms())
        self._insere(copie, self._index + 1)

    def _deplace(self, sens: int) -> None:
        i, j = self._index, self._index + sens
        if not (0 <= i < len(self._liste) and 0 <= j < len(self._liste)):
            return
        self._liste[i], self._liste[j] = self._liste[j], self._liste[i]
        self._dirty = True
        self._remplit_liste(j)

    def _en_tete(self) -> None:
        if self._index <= 0:
            return
        self._liste.insert(0, self._liste.pop(self._index))
        self._dirty = True
        self._remplit_liste(0)

    def _supprimer(self, confirmer: bool = True) -> None:
        g = self.courant()
        if g is None or len(self._liste) < 2:
            return
        if confirmer and QMessageBox.question(
                self, 'Supprimer un montage',
                f'Retirer « {g.get("nom", "")} » ?\n\nIl disparaît du '
                f'fichier à l\'enregistrement. Le fichier d\'avant la '
                f'première écriture de la séance reste à côté, sous le nom '
                f'{gabarits.AVANT}.') != QMessageBox.Yes:
            return
        self._liste.pop(self._index)
        self._dirty = True
        self._remplit_liste(max(0, self._index - 1))

    def _retablir(self) -> None:
        if self._dirty and QMessageBox.question(
                self, 'Rétablir',
                'Abandonner les modifications et relire les montages '
                'enregistrés ?') != QMessageBox.Yes:
            return
        self.reload(self._index)

    # -- validation et aperçu ----------------------------------------------

    def _erreur(self, g: dict) -> str:
        try:
            gabarits.verifier(g)
        except (gabarits.GabaritError, TypeError, KeyError,
                ValueError) as exc:
            return str(exc)
        return ''

    def _erreur_globale(self) -> str:
        """La première raison de ne pas enregistrer — vide s'il n'y en a
        aucune."""
        vus: set = set()
        for g in self._liste:
            nom = str(g.get('nom', '')).strip()
            if not nom:
                return "Un montage n'a pas de nom."
            erreur = self._erreur(g)
            if erreur:
                return f'« {nom or "sans nom"} » : {erreur}'
            if nom in vus:
                return (f'Deux montages s\'appellent « {nom} » : ils '
                        f'seraient indiscernables au bout de la flèche.')
            vus.add(nom)
            cles = [gabarits.cle_poste(q) for q in g['postes']]
            if len(set(cles)) != len(cles):
                return (f'« {nom} » : deux postes portent le même nom — '
                        f'majuscules et espaces ne les distinguent pas.')
            if len(cles) < 2:
                return (f'« {nom} » : un montage porte au moins deux '
                        f'postes.')
        return ''

    def _valide(self) -> None:
        erreur = self._erreur_globale()
        if erreur:
            self.dit(erreur, alerte=True)
        else:
            self.dit('')
        self.w_poser.setEnabled(self.courant() is not None
                                and not self._erreur(self.courant()))

    def _redessine(self) -> None:
        g = self.courant()
        if g is None:
            self.w_apercu.montre(None)
            self.w_info.setText('')
            return
        erreur = self._erreur(g)
        if erreur:
            self.w_apercu.montre(None, note=erreur)
            self.w_info.setText('')
            return
        plein = gabarits.verifier(g)
        self.w_apercu.montre(plein, self._recipe)
        taille = self.w_apercu.emprise()
        n = len(plein['postes'])
        self.w_info.setText(
            f'{n} poste(s)'
            + (f' · encombrement {_ecrit(taille[0])} × {_ecrit(taille[1])} '
               f'mm' if taille else '')
            + ' · la croix marque le centre du champ')

    # -- échanges ----------------------------------------------------------

    def importer_fichier(self, chemin) -> tuple[int, int, list[str]]:
        """Ajoute les montages d'un fichier. Rend `(ajoutés, identiques,
        refusés)` ; un fichier illisible lève `OSError` ou `ValueError`."""
        brut = json.loads(pathlib.Path(chemin).read_text(encoding='utf-8'))
        if isinstance(brut, dict):
            brut = brut.get('montages', [brut])
        if not isinstance(brut, list):
            raise ValueError('ce fichier ne décrit aucun montage')
        valides, refuses = [], []
        for g in brut:
            try:
                valides.append(gabarits.verifier(g))
            except (gabarits.GabaritError, TypeError, KeyError,
                    ValueError) as exc:
                nom = g.get('nom', '?') if isinstance(g, dict) else '?'
                refuses.append(f'{nom} : {exc}')
        liste, ajoutes, identiques = gabarits.fusionner(self._liste, valides)
        if ajoutes:
            index = len(self._liste)
            self._liste = liste
            self._dirty = True
            self._remplit_liste(index)
        return ajoutes, identiques, refuses

    def exporter_fichier(self, chemin) -> int:
        """Écrit les montages affichés. Rend leur nombre."""
        self._propres()
        liste = [gabarits.verifier(g) for g in self._liste]
        pathlib.Path(chemin).write_text(
            json.dumps({'montages': liste}, ensure_ascii=False, indent=2)
            + '\n', encoding='utf-8')
        return len(liste)

    def _importer(self) -> None:
        chemin, _ = QFileDialog.getOpenFileName(
            self, 'Importer des montages', '',
            'Montages (*.json);;Tous (*)')
        if not chemin:
            return
        try:
            ajoutes, identiques, refuses = self.importer_fichier(chemin)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Importer des montages',
                                f'Fichier illisible : {exc}')
            return
        lignes = [f'{ajoutes} montage(s) ajouté(s).']
        if identiques:
            lignes.append(f'{identiques} déjà présent(s) à l\'identique, '
                          f'non repris.')
        if refuses:
            lignes.append('Refusés :\n' + '\n'.join(refuses))
        if ajoutes:
            lignes.append('Rien n\'est écrit avant « Enregistrer ».')
        QMessageBox.information(self, 'Importer des montages',
                                '\n'.join(lignes))

    def _exporter(self) -> None:
        erreur = self._erreur_globale()
        if erreur:
            QMessageBox.warning(self, 'Exporter des montages', erreur)
            return
        chemin, _ = QFileDialog.getSaveFileName(
            self, 'Exporter les montages', 'montages.json',
            'Montages (*.json)')
        if not chemin:
            return
        try:
            n = self.exporter_fichier(chemin)
        except OSError as exc:
            QMessageBox.warning(self, 'Exporter des montages', str(exc))
            return
        self.dit(f'{n} montage(s) écrit(s) dans {chemin}')

    # -- gestes ------------------------------------------------------------

    def _propres(self) -> None:
        """Noms et références rognés, comme ils seront écrits."""
        for g in self._liste:
            g['nom'] = str(g.get('nom', '')).strip()
            if 'donnee' in g:
                g['donnee'] = str(g['donnee']).strip()

    def enregistrer(self) -> bool:
        """Écrit les montages. Faux si l'un d'eux ne tient pas debout."""
        self._propres()
        erreur = self._erreur_globale()
        if erreur:
            self.dit(erreur, alerte=True)
            return False
        if self._lit_empreinte() != self._empreinte and QMessageBox.question(
                self, 'Gestionnaire de montages',
                'Le fichier des montages a changé depuis que le '
                'gestionnaire l\'a lu — flèche du bouton Montage, '
                'formulaire de la pose ou import.\n\nL\'écraser avec la '
                'liste affichée ?') != QMessageBox.Yes:
            self.dit('Rien n\'est écrit : « Rétablir » relit le fichier.',
                     alerte=True)
            return False
        try:
            gabarits.enregistrer(self._liste)
        except (gabarits.GabaritError, OSError) as exc:
            self.dit(f'Non enregistré : {exc}', alerte=True)
            return False
        index = self._index
        self.reload(index, str((self.courant() or {}).get('nom', '')))
        self.dit(f'{len(self._liste)} montage(s) enregistré(s).')
        self.saved.emit(len(self._liste))
        return True

    def reprendre(self, shapes) -> bool:
        """Inscrit un montage posé dans le gabarit choisi, nom gardé."""
        g = self.courant()
        if g is None:
            return False
        try:
            repris = gabarits.depuis_formes(shapes, g)
        except (gabarits.GabaritError, TypeError, ValueError) as exc:
            self.dit(f'Rien de repris : {exc}', alerte=True)
            return False
        repris['nom'] = g.get('nom', repris['nom'])
        self._liste[self._index] = repris
        self._modifie()
        self.dit(f'« {repris["nom"]} » reprend le montage sélectionné. '
                 f'Rien n\'est écrit avant « Enregistrer ».')
        return True

    def _poser(self) -> None:
        self._propres()
        g = self.courant()
        if g is None or self._erreur(g):
            return
        plein = gabarits.verifier(g)
        if self._dirty:
            boite = QMessageBox(self)
            boite.setWindowTitle('Poser un montage')
            boite.setText('Des modifications ne sont pas enregistrées.')
            oui = boite.addButton('Enregistrer et poser',
                                  QMessageBox.AcceptRole)
            sans = boite.addButton('Poser sans enregistrer',
                                   QMessageBox.DestructiveRole)
            boite.addButton('Annuler', QMessageBox.RejectRole)
            boite.setInformativeText(
                'Sans enregistrer, le montage se pose tel qu\'il est '
                'montré, et les modifications sont abandonnées.')
            boite.exec()
            if boite.clickedButton() is oui:
                if not self.enregistrer():
                    return
            elif boite.clickedButton() is sans:
                self.reload(self._index)
            else:
                return
        self.pose_asked.emit(plein)

    def peut_quitter(self) -> bool:
        """Vrai si l'on peut rendre le plan de travail : rien en suspens,
        ou l'opérateur a tranché."""
        if not self._dirty:
            return True
        reponse = QMessageBox.question(
            self, 'Gestionnaire de montages',
            'Enregistrer les modifications des montages ?',
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if reponse == QMessageBox.Save:
            return self.enregistrer()
        if reponse == QMessageBox.Discard:
            self.reload(self._index)
            return True
        return False
