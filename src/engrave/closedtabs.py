"""Onglets fermés / Closed tabs.

Fermer un onglet ne demande rien — c'est voulu, et cela vaut mieux qu'une
question à chaque fois. Encore faut-il pouvoir revenir sur celui qu'on a
fermé par mégarde, ou retrouver la plaque d'avant-hier dont on ne sait
plus le nom exact.

**Tout est gardé**, sans plafond : le contenu part dans un fichier, rangé
par semaine — `26s34` pour la semaine 34 de 2026 — parce qu'un atelier se
souvient d'une plaque par sa semaine bien avant de se souvenir de sa date.

La recherche porte sur le contenu autant que sur le nom : on se souvient
du texte gravé ou de la référence du client bien plus souvent que du nom
qu'on avait donné à l'onglet.
"""
from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from . import session
from . import theme

#: Nombre de textes gravés retenus comme mots-clés d'un document.
MAX_KEYWORDS = 40


def keywords(document) -> str:
    """Les mots d'un document sur lesquels portera la recherche.

    Les textes gravés et les noms de formes : ce dont on se souvient. Le
    dessin lui-même n'entre pas dans l'index — il est sur le disque, et
    personne ne cherche une plaque par ses coordonnées.
    """
    mots: list[str] = []
    for forme in getattr(document, 'shapes', []):
        for champ in ('text', 'data', 'name'):
            valeur = str(getattr(forme, champ, '') or '').strip()
            if valeur and len(valeur) < 60 and valeur not in mots:
                mots.append(valeur)
        if len(mots) >= MAX_KEYWORDS:
            break
    return ' · '.join(mots[:MAX_KEYWORDS])


class ClosedTabs(QDialog):
    """Rouvrir un onglet fermé, retrouvé par mot-clé ou par semaine."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Onglets fermés')
        self.setMinimumSize(620, 460)
        self.chosen: dict | None = None

        dehors = QVBoxLayout(self)
        dehors.addWidget(QLabel(
            'Tous les onglets fermés sont gardés, archivés par semaine.<br>'
            'La recherche porte aussi sur ce qu\'ils contenaient — un texte '
            'gravé, une référence.'))

        ligne = QHBoxLayout()
        self.w_search = QLineEdit()
        self.w_search.setPlaceholderText('Mot-clé : nom, texte gravé, '
                                         'référence…')
        self.w_search.setClearButtonEnabled(True)
        self.w_search.textChanged.connect(self._refresh)
        ligne.addWidget(self.w_search, 1)
        ligne.addWidget(QLabel('Semaine'))
        self.w_week = QComboBox()
        self.w_week.setMinimumWidth(110)
        self.w_week.addItem('toutes', '')
        for semaine in session.closed_weeks():
            self.w_week.addItem(semaine, semaine)
        self.w_week.currentIndexChanged.connect(self._refresh)
        ligne.addWidget(self.w_week)
        dehors.addLayout(ligne)

        self.w_list = QListWidget()
        self.w_list.itemDoubleClicked.connect(lambda *_: self._take())
        dehors.addWidget(self.w_list, 1)

        self.w_note = QLabel('')
        self.w_note.setStyleSheet(theme.css())
        self.w_note.setWordWrap(True)
        dehors.addWidget(self.w_note)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText('Rouvrir')
        boutons.accepted.connect(self._take)
        boutons.rejected.connect(self.reject)
        self.w_clear = QPushButton('Vider la liste')
        self.w_clear.setToolTip(
            'Oublie la liste. Les fichiers archivés restent sur le disque, '
            'dans les dossiers de semaine.')
        self.w_clear.clicked.connect(self._clear)
        boutons.addButton(self.w_clear, QDialogButtonBox.ActionRole)
        dehors.addWidget(boutons)

        self._refresh()

    # -- affichage ---------------------------------------------------------

    def _refresh(self) -> None:
        self.w_list.clear()
        entrees = session.search_closed(self.w_search.text(),
                                        self.w_week.currentData() or '')
        for entree in entrees:
            item = QListWidgetItem(self._ligne(entree))
            item.setData(Qt.UserRole, entree)
            fichier = entree.get('file', '')
            if fichier and not pathlib.Path(fichier).exists():
                # l'index le connaît, le disque ne l'a plus : le dire
                # plutôt que de laisser l'opérateur cliquer dans le vide
                item.setText(item.text() + '   (fichier absent)')
                item.setForeground(Qt.gray)
            item.setToolTip(entree.get('path', '') or fichier)
            self.w_list.addItem(item)
        if self.w_list.count():
            self.w_list.setCurrentRow(0)
        total = len(session.closed_tabs())
        if total:
            self.w_note.setText(
                f'{self.w_list.count()} sur {total} onglet(s) fermé(s) · '
                f'archive : {session.archive_dir()}')
        else:
            self.w_note.setText('Aucun onglet fermé pour l\'instant.')

    @staticmethod
    def _ligne(entree: dict) -> str:
        morceaux = [entree.get('name', 'gravure'),
                    entree.get('week', ''),
                    entree.get('when', '')]
        mots = entree.get('keys', '')
        if mots:
            morceaux.append(mots[:70])
        return '   —   '.join(m for m in morceaux if m)

    # -- actions -----------------------------------------------------------

    def _take(self) -> None:
        item = self.w_list.currentItem()
        if item is None:
            return
        self.chosen = item.data(Qt.UserRole)
        self.accept()

    def _clear(self) -> None:
        session.forget_closed()
        self.w_week.blockSignals(True)
        self.w_week.clear()
        self.w_week.addItem('toutes', '')
        self.w_week.blockSignals(False)
        self._refresh()
