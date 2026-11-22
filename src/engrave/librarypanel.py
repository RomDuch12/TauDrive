"""Panneau de la bibliothèque de dessins / Drawing library panel.

**Un panneau, pas une fenêtre.** Choisir un dessin demande de le voir
grand : une vignette de 280 px ne distingue pas deux révisions d'un même
logo, et les fichiers d'atelier s'appellent `piece_rev3_final.dxf`. Le
panneau prend donc les mêmes colonnes que le gestionnaire de process —
l'**aperçu en colonne 2**, à la place du plan de travail, et
l'**arborescence rayon ▸ dessin en colonne 3**.

**Parcourir ne coûte pas lire.** Une bibliothèque livrée pèse quelques
dizaines de mégaoctets, et un seul de ses dessins peut porter dix mille
polylignes. Lire un tel fichier en entier demande plusieurs secondes ; le
faire à chaque clic de liste — et dix fois de suite si l'on descend aux
flèches — saturait la machine, et le panneau paraissait planté.

Le parcours ne lit donc plus les dessins : il les **esquisse**. Un seul
passage sur le fichier, les sommets retenus, les arcs en cordes — de quoi
reconnaître un dessin sur trois cents pixels, pour un dixième à un
vingtième du prix. Voir `sketch.py`.

**Le dessin entier se demande.** Le bouton *Visualiser* le charge en
pleine définition, avec une barre d'avancement et un bouton *Annuler* qui
rend la main tout de suite. Ce qui a été chargé sert ensuite à l'insertion
sans être relu.

Trois précautions tiennent le panneau vivant, quelle que soit la taille de
la bibliothèque :

* **un seul fil d'esquisse**, qui abandonne les demandes dépassées —
  descendre la liste aux flèches n'en lançait pas dix ;
* **un cache borné**, qui ne retient que des tracés déjà allégés : garder
  la pleine définition de tout ce qu'on a survolé faisait grossir
  l'application jusqu'à l'étouffement ;
* **un chemin de peinture mémorisé**, reconstruit seulement quand le
  dessin change — et non à chaque redimensionnement de la fenêtre.
"""
from __future__ import annotations

import pathlib
import threading
import time

from PySide6.QtCore import QEventLoop, QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QMessageBox,
                               QProgressDialog, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import drawings, icons, session, sketch, theme, thumbs
from . import theme

#: Points au-delà desquels l'aperçu décime le tracé.
#:
#: Quatre mille segments suffisent à reconnaître un dessin sur un aperçu
#: de quelques centaines de pixels ; au-delà, on peint des détails plus
#: fins que le pixel, et on les paie.
BQ_POINTS = 4000

#: Dessins gardés en réserve. Au-delà, le plus ancien survolé est oublié.
#:
#: La réserve était sans limite : parcourir la bibliothèque entière y
#: entassait la pleine définition de chaque dessin — quelques centaines de
#: mégaoctets pour vingt fichiers, et l'application tombait. Elle ne
#: retient plus que des esquisses allégées, et pas plus de trente.
CACHE_ENTRIES = 30


def decimate(polys: list, budget: int = BQ_POINTS) -> list:
    """Version allégée d'un tracé, un point sur `n`.

    Les extrémités de chaque polyligne sont **toujours gardées** : un
    contour qui perdrait son dernier point s'ouvrirait, et un contour
    ouvert se voit tout de suite sur un aperçu.
    """
    total = sum(len(p) for p in polys)
    if total <= budget or not polys:
        return polys
    pas = max(2, total // max(1, budget))
    allege = []
    for poly in polys:
        if len(poly) <= 3:
            allege.append(poly)
            continue
        court = poly[::pas]
        if court[-1] != poly[-1]:
            court = court + [poly[-1]]
        if len(court) >= 2:
            allege.append(court)
    return allege


#: Temps cédé au fil de l'interface à chaque respiration de l'esquisse.
#:
#: Cinq millisecondes, et non zéro ni une : sous Windows, la granularité
#: de l'horloge fait qu'un sommeil plus court rend la main trop vite pour
#: que le fil de l'interface ait le temps de reprendre le verrou de
#: l'interpréteur. Mesuré : à 1 ms la fenêtre reste figée, à 5 ms elle se
#: repeint pendant toute la lecture.
BREATH_S = 0.005


def _respirer() -> None:
    """Cède la main au fil de l'interface, le temps qu'il se repeigne."""
    time.sleep(BREATH_S)


def _stamp(entry) -> str:
    """Identité d'un fichier **et de son état** : chemin, taille, date.

    Un dessin remplacé sur le partage réseau doit ressortir de la réserve
    ré-esquissé, et non tel qu'il était à midi.
    """
    try:
        st = entry.path.stat()
        return f'{entry.path}|{st.st_size}|{int(st.st_mtime)}'
    except OSError:
        return str(entry.path)


# --------------------------------------------------------------------------
# Esquisse en arrière-plan
# --------------------------------------------------------------------------

#: Au-delà, la lecture s\'accompagne d\'une barre plutôt que
#: d\'un sablier. En deçà, la fenêtre s\'ouvrirait et se
#: refermerait dans le même souffle, ce qui inquiète plus que ça ne
#: rassure.
PROGRESS_AFTER_BYTES = 300_000


def load_with_progress(parent, entry, recipe=None):
    """Lit le dessin **entier**, avec barre d\'avancement et abandon.

    Rend `(formes, erreur)` :

    * `(liste, )` — la lecture a abouti ;
    * `(None, )` — on a renoncé en cours de route ;
    * `(None, raison)` — la lecture a échoué, et voici pourquoi.

    Dix mégaoctets de polylignes prennent plusieurs secondes. Une fenêtre
    figée sans explication a toutes les apparences d\'un plantage : la
    barre dit que ça travaille, et le bouton dit qu\'on peut s\'en
    aller.

    La lecture reste dans le **fil de l\'interface** — poser des
    formes dans un document depuis un fil de fond demanderait de tout
    verrouiller — mais `drawings.load` rend la main de loin en loin par
    son rapport d\'avancement, et c\'est là que la fenêtre se
    repeint.
    """
    from .dxfimport import Cancelled, DxfError

    try:
        gros = entry.path.stat().st_size > PROGRESS_AFTER_BYTES
    except OSError:
        gros = False

    barre = None
    if gros:
        barre = QProgressDialog(f'Lecture de « {entry.name} »…', 'Annuler',
                                0, 1000, parent)
        barre.setWindowTitle('Bibliothèque')
        barre.setWindowModality(Qt.WindowModal)
        # sans délai : le fichier est déjà connu pour être gros, et
        # attendre une seconde de plus ne fait que laisser croire au gel
        barre.setMinimumDuration(0)
        barre.setAutoClose(False)
        barre.setAutoReset(False)
        barre.setValue(0)

    def avance(fraction: float, texte: str = '') -> bool:
        if barre is None:
            return True
        barre.setValue(int(max(0.0, min(1.0, fraction)) * 1000))
        if texte:
            barre.setLabelText(f'{entry.name} — {texte}')
        QApplication.processEvents()
        return not barre.wasCanceled()

    try:
        formes = drawings.load(entry, recipe=recipe, progress=avance)
    except Cancelled:
        return (None, '')
    except (DxfError, OSError, ValueError) as exc:
        return (None, str(exc))
    except Exception as exc:                     # lecteur tiers récalcitrant
        return (None, str(exc))
    finally:
        if barre is not None:
            barre.close()
    return (list(formes), '')


class PreviewLoader(QObject):
    """Fait l\'esquisse hors du fil de l\'interface.

    Esquisser un DXF d\'atelier prend un tiers de seconde ; le lire en
    entier, jusqu\'à sept. Ni l\'un ni l\'autre n\'a sa
    place dans le fil qui peint : il fige la fenêtre entière, barre
    d\'état et boutons compris. Le travail part donc dans un fil à
    part, et le résultat revient par un signal — Qt le remet lui-même dans
    le bon fil.

    **Deux réserves, et c\'est là tout le remède.**

    * en **mémoire**, les esquisses : quelques milliers de points chacune,
      on peut en garder cent sans y penser ;
    * sur le **disque**, les mêmes, sous `thumbs` : un dessin déjà vu se
      montre alors instantanément, même après un redémarrage, sans que son
      fichier soit rouvert.

    Ce qui n\'est **jamais** gardé, c\'est la géométrie exacte :
    un plan pèse douze mégaoctets une fois lu, et c\'est en les
    accumulant que l\'application enflait jusqu\'à tomber.

    Chaque demande porte un **jeton** — chemin, taille et date du fichier.
    Un résultat dont le jeton n\'est plus le courant est jeté :
    parcourir la liste aux flèches lance dix esquisses, et seule la
    dernière a un sens.
    """

    ready = Signal(str, object)              # jeton, sketch.Outline

    #: Esquisses gardées en mémoire. Chacune pèse quelques dizaines de
    #: kilo-octets : cent tiennent dans quelques mégaoctets.
    MAX_CACHE = 100

    def __init__(self) -> None:
        super().__init__()
        self._token = ''
        self._stop = False
        self._cache: dict = {}
        self._order: list[str] = []

    # -- réserve -----------------------------------------------------------

    def cached(self, entry):
        """L\'esquisse de cette entrée, mémoire puis disque."""
        jeton = _stamp(entry)
        trouve = self._cache.get(jeton)
        if trouve is not None:
            return trouve
        garde = thumbs.load(entry.path)
        if garde is None:
            return None
        polys, bornes = garde
        if not polys:
            return None
        esquisse = sketch.Outline(polys, bornes, False, '')
        self._keep(jeton, esquisse)
        return esquisse

    def _keep(self, jeton: str, esquisse) -> None:
        self._cache[jeton] = esquisse
        self._order.append(jeton)
        while len(self._order) > self.MAX_CACHE:
            self._cache.pop(self._order.pop(0), None)

    def forget(self) -> None:
        self._cache.clear()
        self._order.clear()

    # -- travail de fond ---------------------------------------------------

    def stop(self) -> None:
        """N\'attend plus rien : le fil en cours sera ignoré."""
        self._stop = True
        self._token = ''

    def current(self) -> str:
        return self._token

    def request(self, entry, recipe=None) -> str:
        """Lance l\'esquisse et rend le jeton de cette demande."""
        self._token = jeton = _stamp(entry)
        self._stop = False
        threading.Thread(target=self._work, args=(jeton, entry, recipe),
                         daemon=True, name='esquisse-bibliotheque').start()
        return jeton

    def _work(self, jeton: str, entry, recipe) -> None:
        def respirer():
            if self._stop or jeton != self._token:
                raise _Abandon()
            _respirer()
        try:
            esquisse = drawings.outline(entry, recipe=recipe,
                                        respirer=respirer)
        except _Abandon:
            return
        except Exception as exc:
            esquisse = sketch.Outline(note=f'Aperçu impossible : {exc}')
        if self._stop or jeton != self._token:
            return
        self._keep(jeton, esquisse)
        if esquisse.polys:
            # rangée sur le disque : le prochain passage sera instantané,
            # même après un redémarrage
            thumbs.store(entry.path, esquisse.polys)
        self.ready.emit(jeton, esquisse)


class _Abandon(Exception):
    """Signal interne : l\'esquisse en cours n\'intéresse plus."""


class Preview(QWidget):
    """Aperçu d'un dessin, ajusté à la place disponible.

    Le chemin de peinture est **mémorisé** : construire un `QPainterPath`
    de plusieurs milliers de segments à chaque `paintEvent` rendait tout
    redimensionnement de fenêtre poissif, alors que le dessin n'avait pas
    bougé.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(360, 300)
        self._polys: list = []
        self._bounds = None
        self._note = 'Aucun aperçu'
        self._chemin: QPainterPath | None = None
        self._taille = None

    def show_drawing(self, polys, bounds, note: str = '') -> None:
        self._polys, self._bounds = polys, bounds
        self._note = note or 'Aucun aperçu'
        self._chemin = None
        self.update()

    def resizeEvent(self, event) -> None:
        self._chemin = None
        super().resizeEvent(event)

    def _build(self) -> QPainterPath:
        x1, y1, x2, y2 = self._bounds
        largeur, hauteur = max(x2 - x1, 1e-6), max(y2 - y1, 1e-6)
        marge = 18
        zone = self.rect().adjusted(marge, marge, -marge, -marge)
        echelle = min(zone.width() / largeur, zone.height() / hauteur)
        dx = zone.center().x() - (x1 + x2) / 2 * echelle
        dy = zone.center().y() + (y1 + y2) / 2 * echelle

        chemin = QPainterPath()
        for poly in self._polys:
            if len(poly) < 2:
                continue
            chemin.moveTo(poly[0][0] * echelle + dx, -poly[0][1] * echelle + dy)
            for x, y in poly[1:]:
                chemin.lineTo(x * echelle + dx, -y * echelle + dy)
        return chemin

    def paintEvent(self, event) -> None:
        palette = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(palette.canvas))
        if not self._polys or self._bounds is None:
            p.setPen(QColor(palette.text_dim))
            p.drawText(QRectF(self.rect()).adjusted(12, 12, -12, -12),
                       Qt.AlignCenter | Qt.TextWordWrap, self._note)
            return

        if self._chemin is None or self._taille != self.size():
            self._chemin = self._build()
            self._taille = self.size()
        pen = QPen(QColor(palette.path), 1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawPath(self._chemin)


class LibraryTree(QTreeWidget):
    """Arborescence **rayon ▸ dessin**, colonne 3.

    Un arbre plutôt qu'une liste et un menu déroulant : une bibliothèque
    d'atelier passe deux cents entrées, et l'on cherche d'abord le rayon —
    le client, le type de pièce — avant le dessin.
    """

    picked = Signal(object)                 # une entrée choisie
    activated_entry = Signal(object)        # double-clic : poser le dessin

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.currentItemChanged.connect(self._current)
        self.itemDoubleClicked.connect(self._activated)

    def fill(self, entries: list) -> None:
        """Range les entrées par rayon, rayons vides compris."""
        garde = self.selected().key() if self.selected() else ''
        self.clear()
        chemise = icons.icon('dossier', theme.current().text_dim)
        branches: dict[str, QTreeWidgetItem] = {}

        def branche(rayon: str) -> QTreeWidgetItem | None:
            if not rayon:
                return None
            if rayon in branches:
                return branches[rayon]
            parent, _, feuille = rayon.rpartition('/')
            noeud = QTreeWidgetItem([feuille])
            noeud.setIcon(0, chemise)
            noeud.setData(0, Qt.UserRole, None)
            dessus = branche(parent)
            (dessus.addChild(noeud) if dessus is not None
             else self.addTopLevelItem(noeud))
            branches[rayon] = noeud
            return noeud

        for rayon in drawings.folders():
            branche(rayon)
        retrouve = None
        for entry in entries:
            feuille = QTreeWidgetItem([entry.name])
            feuille.setData(0, Qt.UserRole, entry)
            feuille.setToolTip(0, str(entry.path))
            dessus = branche(entry.folder)
            (dessus.addChild(feuille) if dessus is not None
             else self.addTopLevelItem(feuille))
            if entry.key() == garde:
                retrouve = feuille
        self.expandAll()
        if retrouve is not None:
            self.setCurrentItem(retrouve)
        elif self.topLevelItemCount():
            self._select_first()

    def _select_first(self) -> None:
        for i in range(self.topLevelItemCount()):
            trouve = self._first_leaf(self.topLevelItem(i))
            if trouve is not None:
                self.setCurrentItem(trouve)
                return

    def _first_leaf(self, noeud) -> QTreeWidgetItem | None:
        if noeud.data(0, Qt.UserRole) is not None:
            return noeud
        for i in range(noeud.childCount()):
            trouve = self._first_leaf(noeud.child(i))
            if trouve is not None:
                return trouve
        return None

    def selected(self):
        item = self.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def current_folder(self) -> str:
        """Rayon de l'entrée choisie, ou du dossier lui-même s'il l'est."""
        item = self.currentItem()
        if item is None:
            return ''
        entree = item.data(0, Qt.UserRole)
        if entree is not None:
            return entree.folder
        morceaux = []
        while item is not None:
            morceaux.insert(0, item.text(0))
            item = item.parent()
        return '/'.join(morceaux)

    def _current(self, *_) -> None:
        self.picked.emit(self.selected())

    def _activated(self, item, _col) -> None:
        entree = item.data(0, Qt.UserRole)
        if entree is not None:
            self.activated_entry.emit(entree)


class DrawingLibrary(QWidget):
    """Bibliothèque de dessins : aperçu en colonne 2, arbre en colonne 3.

    Le bouton *Insérer* est celui qu'on presse quatre-vingt-dix fois sur
    cent ; le reste — ajouter, renommer, effacer, ranger en rayons —
    tient dans une rangée sous l'aperçu.
    """

    chosen_entry = Signal(object)           # poser ce dessin
    done = Signal()                         # revenir au plan de travail

    def __init__(self, parent=None, recipe=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Bibliothèque de dessins')
        self._recipe = recipe
        self.chosen: drawings.Entry | None = None
        self._loader = PreviewLoader()
        self._loader.ready.connect(self._loaded)
        self._pending = ''
        #: Dernier dessin lu en entier : (empreinte, formes). Insérer juste
        #: après avoir visualisé ne doit pas relire le fichier.
        self._full: tuple[str, list] | None = None

        dehors = QVBoxLayout(self)
        titre = QLabel('<b>Bibliothèque de dessins</b>')
        dehors.addWidget(titre)

        self.w_preview = Preview()
        dehors.addWidget(self.w_preview, 1)

        self.w_info = QLabel('')
        self.w_info.setWordWrap(True)
        dehors.addWidget(self.w_info)

        self.w_folder = QLabel('')
        self.w_folder.setWordWrap(True)
        self.w_folder.setStyleSheet(theme.css('text_dim', 11))
        dehors.addWidget(self.w_folder)

        rangee = QHBoxLayout()
        for libelle, slot, astuce in (
                ('Ajouter…', self._add,
                 'Range une copie d\'un fichier DXF ou TauDrive dans la '
                 'bibliothèque du poste'),
                ('Renommer…', self._rename, 'Renomme un dessin du poste'),
                ('Supprimer', self._remove, 'Efface un dessin du poste'),
                ('Nouveau rayon…', self._new_shelf,
                 'Crée un sous-dossier dans la bibliothèque du poste'),
                ('Déplacer…', self._move,
                 'Range le dessin choisi dans un autre rayon'),
                ('Dossier…', self._pick_folder,
                 'Choisit le dossier de la bibliothèque du poste — un '
                 'partage réseau en fait celle de l\'atelier'),
                ('Actualiser', self.reload,
                 'Relit les dossiers : utile après un ajout fait ailleurs')):
            b = QPushButton(libelle)
            b.setToolTip(astuce)
            b.clicked.connect(slot)
            rangee.addWidget(b)
            setattr(self, f'b_{slot.__name__.strip("_")}', b)
        dehors.addLayout(rangee)

        bas = QHBoxLayout()
        # **Visualiser** est le pendant de l'esquisse : ce que le parcours
        # ne montre qu'approché, ce bouton le lit pour de bon — sous barre
        # d'avancement, et abandonnable en cours.
        self.w_view = QPushButton('Visualiser')
        self.w_view.setToolTip(
            'Lit le dessin en entier et le montre en pleine définition.\n'
            'Un dessin lourd prend quelques secondes : la lecture s\'annule '
            'à tout moment.')
        self.w_view.clicked.connect(self._visualise)
        self.w_insert = QPushButton('Insérer dans le dessin')
        self.w_insert.setToolTip(
            'Pose ce dessin sur le plan de travail, groupé, prêt à être '
            'placé.')
        self.w_insert.clicked.connect(self._insert)
        self.w_done = QPushButton('Terminé')
        self.w_done.setToolTip('Revient au plan de travail sans rien poser.')
        self.w_done.clicked.connect(self.done.emit)
        bas.addWidget(self.w_view)
        bas.addWidget(self.w_insert, 1)
        bas.addWidget(self.w_done)
        dehors.addLayout(bas)

        # L'arbre est un panneau à part : il vit en colonne 3 et se pose
        # dans un dock, comme le magasin d'outils.
        self.tree = LibraryTree()
        self.tree.picked.connect(self._selected)
        self.tree.activated_entry.connect(self._insert_entry)

    # -- liste -------------------------------------------------------------

    def set_recipe(self, recipe) -> None:
        self._recipe = recipe

    def reload(self) -> None:
        self.tree.fill(drawings.entries())
        # « Ne répond pas » et « n'existe pas encore » ne se disent pas
        # pareil : le premier annonce un partage hors ligne, le second un
        # dossier qui se créera au premier ajout.
        dossier = drawings.user_dir()
        if session.reachable(str(dossier)):
            etat = ''
        elif session.reachable(str(dossier.parent)):
            etat = '   (créé au premier ajout)'
        else:
            etat = '   (ne répond pas)'
        self.w_folder.setText(f'Bibliothèque du poste : {dossier}{etat}')
        self._selected(self.current())

    def current(self) -> drawings.Entry | None:
        return self.tree.selected()

    def closeEvent(self, event) -> None:
        self._loader.stop()
        super().closeEvent(event)

    def forget_loaded(self) -> None:
        """Oublie le dessin lu en entier. Appelé en quittant le panneau.

        Un dessin de dix mégaoctets pèse autant en mémoire une fois lu.
        Le garder après qu'on a refermé la bibliothèque, c'est le payer
        pour rien pendant tout le reste de la séance — et c'est comme cela
        que l'application enflait jusqu'à ne plus répondre.
        """
        self._full = None

    def _selected(self, entry=None) -> None:
        entry = entry if entry is not None else self.current()
        modifiable = bool(entry and entry.editable())
        self.b_rename.setEnabled(modifiable)
        self.b_remove.setEnabled(modifiable)
        self.b_move.setEnabled(modifiable)
        self.w_insert.setEnabled(entry is not None)
        self.w_view.setEnabled(entry is not None)
        if entry is None:
            self.w_preview.show_drawing([], None)
            self.w_info.setText(
                'Bibliothèque vide. *Ajouter…* y range un DXF ou un '
                'document TauDrive.')
            return

        connu = self._loader.cached(entry)
        if connu is not None:
            self._pending = ''
            self._show(entry, connu)
            return
        # Rien en réserve : l'esquisse part se faire, et l'on annonce
        # l'attente plutôt que de laisser un cadre vide.
        self.w_preview.show_drawing([], None, 'esquisse en cours…')
        self.w_info.setText(f'<b>{entry.name}</b>')
        self._pending = self._loader.request(entry, self._recipe)

    def _loaded(self, jeton: str, esquisse) -> None:
        """Une esquisse est arrivée. Périmée, elle est jetée."""
        if jeton != self._loader.current():
            return                          # une autre entrée a été choisie
        entry = self.current()
        if entry is None or _stamp(entry) != jeton:
            return
        self._show(entry, esquisse)

    def _show(self, entry, esquisse) -> None:
        if not esquisse.polys:
            self.w_preview.show_drawing(
                [], None, esquisse.note or 'Dessin illisible ou vide.')
            self.w_info.setText(f'<b>{entry.name}</b><br>'
                                f'{self._weight(entry)}')
            return
        self._paint(entry, esquisse.polys, esquisse.bounds, hq=False,
                    exact=esquisse.exact)

    def _paint(self, entry, polys, bounds, hq: bool,
               exact: bool = True) -> None:
        """Montre ces tracés. `hq` distingue la pleine définition de
        l'esquisse — la nuance est écrite sous l'aperçu, car une cote
        approchée ne se donne pas pour exacte."""
        if entry is not self.current():
            return
        self.w_preview.show_drawing(polys, bounds)
        if bounds is None:
            self.w_info.setText(f'<b>{entry.name}</b><br>'
                                'Dessin illisible ou vide.')
            return
        detail = ('géométrie seule' if entry.suffix() == '.dxf'
                  else 'géométrie et process')
        rayon = f'{entry.folder} · ' if entry.folder else ''
        environ = '' if hq else '≈ '
        etat = ('pleine définition' if hq else
                'esquisse' if exact else 'esquisse partielle')
        self.w_info.setText(
            f'<b>{entry.name}</b> — {rayon}{detail}<br>'
            f'{environ}{bounds[2] - bounds[0]:.1f} × '
            f'{bounds[3] - bounds[1]:.1f} mm · '
            f'{len(polys)} tracé(s) · {etat} · {self._weight(entry)}')

    @staticmethod
    def _weight(entry) -> str:
        try:
            taille = entry.path.stat().st_size
        except OSError:
            return 'taille inconnue'
        return (f'{taille / 1e6:.1f} Mo' if taille >= 1e6
                else f'{taille / 1e3:.0f} ko')

    # -- actions -----------------------------------------------------------

    def _load_full(self) -> list | None:
        """Le dessin choisi, lu en entier — de la réserve, ou du fichier.

        Rend `None` si l'on a annulé ou si la lecture a échoué ; le message
        d'erreur, lui, a déjà été montré.
        """
        entry = self.current()
        if entry is None:
            return None
        empreinte = _stamp(entry)
        if self._full is not None and self._full[0] == empreinte:
            return self._full[1]
        formes, erreur = load_with_progress(self, entry, self._recipe)
        if erreur:
            QMessageBox.warning(self, 'Bibliothèque',
                                f'« {entry.name} » illisible : {erreur}')
            return None
        if formes is None:
            self.w_info.setText(f'<b>{entry.name}</b> — lecture annulée.')
            return None
        self._full = (empreinte, formes)
        return formes

    def _visualise(self) -> None:
        """Charge le dessin en entier et le montre en pleine définition."""
        entry = self.current()
        formes = self._load_full()
        if not formes or entry is None:
            return
        from . import geometry as G
        from .toolpath import group_zones, shape_polylines
        # posées, elles seront groupées : on les montre ainsi
        zones = group_zones(formes, ensemble=True)
        polys = [p for forme in formes
                 for p in shape_polylines(forme, zone=zones.get(forme.id))]
        if not polys:
            self.w_info.setText(f'<b>{entry.name}</b> — aucun tracé.')
            return
        # Peint allégé, annoncé complet : le comptage porte sur le dessin
        # réel, l'affichage sur ce qu'un écran sait montrer.
        total = len(polys)
        self.w_preview.show_drawing(decimate(polys), G.bounds(polys))
        rayon = f'{entry.folder} · ' if entry.folder else ''
        b = G.bounds(polys)
        self.w_info.setText(
            f'<b>{entry.name}</b> — {rayon}pleine définition<br>'
            f'{b[2] - b[0]:.3f} × {b[3] - b[1]:.3f} mm · '
            f'{total} tracé(s) · {self._weight(entry)}')

    def _insert(self) -> None:
        entry = self.current()
        if entry is not None:
            self._insert_entry(entry)

    def _insert_entry(self, entry) -> None:
        self.chosen = entry
        self.chosen_entry.emit(entry)

    def shapes_for(self, entry):
        """Les formes de cette entrée, **prêtes à poser**.

        Rend `(formes, erreur)`, comme `load_with_progress` : `(None, )`
        si l\'on a renoncé, `(None, raison)` si la lecture a échoué.

        C\'est le panneau qui lit, et non l\'appelant : il est le
        seul à tenir la réserve, et une lecture faite ailleurs ne la
        nourrirait pas. Insérer deux fois le même dessin relisait sinon
        quatre secondes de DXF pour rien.

        Les formes rendues sont **des copies neuves** : celles de la
        réserve ne doivent jamais entrer dans un document, sous peine
        d\'y être modifiées depuis deux endroits.
        """
        deja = self.loaded_shapes(entry)
        if deja is not None:
            return (deja, '')
        formes, erreur = load_with_progress(self, entry, self._recipe)
        if formes is None:
            return (None, erreur)
        self._full = (_stamp(entry), formes)
        return (self.loaded_shapes(entry) or [], '')

    def loaded_shapes(self, entry) -> list | None:
        """Formes déjà lues pour cette entrée, si elles sont encore fraîches.

        Sert à l'insertion : visualiser puis insérer ne doit pas relire
        sept secondes de DXF pour rien.

        Ce sont des **copies neuves**, identifiants compris. Rendre les
        formes de la réserve elle-même les ferait poser deux fois sous le
        même identifiant, et le groupe formé à l'insertion marquerait la
        réserve autant que le document.
        """
        if self._full is None or self._full[0] != _stamp(entry):
            return None
        import copy as _copy

        from .model import _new_id
        neuves = []
        for forme in self._full[1]:
            fraiche = _copy.deepcopy(forme)
            fraiche.id = _new_id()
            fraiche.group = ''
            neuves.append(fraiche)
        return neuves

    def _add(self) -> None:
        chemin, _ = QFileDialog.getOpenFileName(
            self, 'Ajouter à la bibliothèque',
            session.start_folder('dxf'),
            'Dessins (*.dxf *.pdf *.ai *.eps *.ps *.svg *.cdr *.taudrive);;'
            'Dessins DXF (*.dxf);;Illustrator et PDF (*.ai *.pdf);;'
            'PostScript (*.eps *.ps);;SVG (*.svg);;CorelDRAW (*.cdr);;'
            'Documents TauDrive (*.taudrive);;Tous (*)')
        if not chemin:
            return
        try:
            # un ajout atterrit dans le rayon qu'on regarde : c'est là
            # qu'on l'a cherché avant de se résoudre à l'importer
            entry = drawings.add(chemin,
                                 folder=self.tree.current_folder())
        except Exception as exc:
            QMessageBox.warning(self, 'Bibliothèque',
                                f'Ajout impossible : {exc}')
            return
        session.remember_file('dxf', chemin)
        self.reload()
        self._select_key(entry.key())

    def _select_key(self, clef: str) -> None:
        for entree in drawings.entries():
            if entree.key() == clef:
                self.tree.fill(drawings.entries())
                break

    def _rename(self) -> None:
        entry = self.current()
        if entry is None or not entry.editable():
            return
        nom, ok = QInputDialog.getText(self, 'Renommer', 'Nouveau nom :',
                                       text=entry.name)
        if not ok or not nom.strip():
            return
        try:
            drawings.rename(entry, nom)
        except Exception as exc:
            QMessageBox.warning(self, 'Bibliothèque',
                                f'Renommage impossible : {exc}')
        self.reload()

    def _remove(self) -> None:
        entry = self.current()
        if entry is None or not entry.editable():
            return
        if QMessageBox.question(
                self, 'Supprimer',
                f'Effacer « {entry.name} » de la bibliothèque du poste ?\n\n'
                f'{entry.path}') != QMessageBox.StandardButton.Yes:
            return
        try:
            drawings.remove(entry)
        except Exception as exc:
            QMessageBox.warning(self, 'Bibliothèque',
                                f'Suppression impossible : {exc}')
        self.reload()

    def _new_shelf(self) -> None:
        depart = self.tree.current_folder()
        nom, ok = QInputDialog.getText(
            self, 'Nouveau rayon',
            'Nom du rayon (« Clients/Exemple » pour un sous-rayon) :',
            text=(depart + '/' if depart else ''))
        if not ok or not nom.strip():
            return
        try:
            drawings.make_folder(nom)
        except Exception as exc:
            QMessageBox.warning(self, 'Bibliothèque',
                                f'Rayon non créé : {exc}')
            return
        self.reload()

    def _move(self) -> None:
        entry = self.current()
        if entry is None or not entry.editable():
            return
        choix = ['(racine)'] + drawings.folders()
        depart = choix.index(entry.folder) if entry.folder in choix else 0
        rayon, ok = QInputDialog.getItem(
            self, 'Déplacer', f'Ranger « {entry.name} » dans :',
            choix, depart, False)
        if not ok:
            return
        try:
            drawings.move(entry, '' if rayon == '(racine)' else rayon)
        except Exception as exc:
            QMessageBox.warning(self, 'Bibliothèque',
                                f'Déplacement impossible : {exc}')
        self.reload()

    def _pick_folder(self) -> None:
        dossier = QFileDialog.getExistingDirectory(
            self, 'Dossier de la bibliothèque du poste',
            str(drawings.user_dir()))
        if not dossier:
            return
        drawings.set_user_dir(dossier)
        session.forget_reachability()
        self.reload()
