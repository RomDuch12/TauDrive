"""Dossiers par défaut / Default folders.

Un atelier range ses fichiers toujours au même endroit. Redemander le
chemin à chaque ouverture, à chaque import ou à chaque export fait perdre
du temps et finit par produire une plaque exportée au mauvais endroit.

Ce dialogue fixe un emplacement par usage. Ce que ce réglage vaut dépend
de l'usage, et la nuance compte :

* pour les usages de **navigation** — ouvrir, enregistrer, importer,
  exporter — c'est un **point de départ**. Une fois qu'on est allé
  quelque part, le sélecteur y revient : c'est la seule chose qu'on
  attende de lui. Le réglage sert au premier usage, et chaque fois que le
  dernier emplacement ne répond plus ;
* pour les usages de **politique** — dossier d'export machine,
  bibliothèque, archives — le réglage **l'emporte** toujours. Ce
  sont des décisions d'atelier, et elles n'ont pas à suivre les allées et
  venues de quelqu'un qui a exporté un DXF sur son bureau.

Laissé vide, un usage part du dernier emplacement employé, puis du
dossier personnel.
"""
from __future__ import annotations

import pathlib

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from . import session
from .widgets import Combo
from . import theme


class FolderSettings(QDialog):
    """Un champ par usage, avec son bouton de sélection."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Dossiers par défaut')
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        intro = QLabel(
            'Pour ouvrir, enregistrer, importer et exporter, ces dossiers '
            'sont un <b>point de départ</b> :<br>le sélecteur revient '
            'ensuite là où l\'on est allé.<br>'
            'Pour l\'export machine, la bibliothèque et les archives, '
            'le réglage l\'emporte toujours.')
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.css())
        layout.addWidget(intro)

        form = QFormLayout()
        self.fields: dict[str, Combo] = {}
        for kind, label, tip in session.FOLDER_KINDS:
            # liste modifiable garnie des chemins récents : sur un poste
            # d'atelier, le bon dossier a presque toujours déjà servi
            edit = Combo()
            edit.setEditable(True)
            edit.addItem('')
            for folder in session.recent_folders(kind):
                edit.addItem(folder)
            edit.setCurrentText(session.default_folder(kind))
            edit.lineEdit().setPlaceholderText(
                '(aucun — dernier emplacement employé)')
            edit.setToolTip(tip)
            button = QPushButton('…')
            button.setFixedWidth(30)
            button.clicked.connect(
                lambda _=False, k=kind: self._browse(k))
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(edit, 1)
            row.addWidget(button)
            holder = QWidget()
            holder.setLayout(row)
            form.addRow(label, holder)
            self.fields[kind] = edit
        layout.addLayout(form)

        # --- chemin vu par la machine ---
        machine = QFormLayout()
        self.w_template = Combo()
        self.w_template.setEditable(True)
        for candidate in (session.MACHINE_TEMPLATE,
                          r'C:\inciwin\cl_iso\{job}',
                          r'C:\TauDrive\{year}\{date} {job}'):
            self.w_template.addItem(candidate)
        self.w_template.setCurrentText(session.machine_template())
        self.w_template.setToolTip(
            'Chemin sous lequel le poste machine voit le dossier d\'export.\n'
            'C\'est ce chemin qui figure dans le CLJOB — le seul valable à '
            'l\'exécution.')
        machine.addRow('Chemin vu par la machine', self.w_template)
        fields = ' · '.join(f'{key} {label}'
                            for key, label in session.TEMPLATE_FIELDS)
        hint = QLabel(fields)
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.css('text_dim', 11))
        machine.addRow('', hint)
        self.w_preview = QLabel('')
        self.w_preview.setWordWrap(True)
        self.w_preview.setStyleSheet(theme.css('text_dim', 11))
        machine.addRow('', self.w_preview)
        layout.addLayout(machine)
        self.w_template.currentTextChanged.connect(self._preview)
        self._preview()

        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        layout.addWidget(self.w_note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _preview(self) -> None:
        """Montre le chemin obtenu : un modèle ne se relit pas de tête."""
        from . import iso
        from .model import Document
        rendered = iso.render_template(self.w_template.currentText(),
                                       Document(name='plaque essai'))
        self.w_preview.setText(f'Donnerait : <b>{rendered}</b>')

    def _browse(self, kind: str) -> None:
        current = self.fields[kind].currentText().strip()
        folder = QFileDialog.getExistingDirectory(
            self, 'Choisir un dossier',
            current or session.start_folder(kind))
        if folder:
            self.fields[kind].setCurrentText(folder)

    def _save(self) -> None:
        """Prévient si un chemin n'est pas joignable, sans l'interdire.

        Un dossier par défaut mort ne se voit qu'au moment d'exporter —
        c'est-à-dire au pire moment — d'où l'avertissement. Mais un
        **partage réseau** peut être légitimement hors ligne quand on
        règle l'application : refuser sa saisie obligerait à revenir plus
        tard, ce qui est exactement ce qu'on cherche à éviter. On demande
        donc confirmation au lieu de bloquer.
        """
        # `writable` et non `reachable` : un dossier d'export ou d'archive
        # qui n'existe pas encore sera créé au premier usage. Le signaler
        # comme injoignable posait une question sans objet — voir EX-195.
        missing = [f'{label} — {self.fields[kind].currentText().strip()}'
                   for kind, label, _ in session.FOLDER_KINDS
                   if self.fields[kind].currentText().strip()
                   and not session.writable(
                       self.fields[kind].currentText().strip())]
        if missing:
            answer = QMessageBox.question(
                self, 'Dossiers par défaut',
                'Ces dossiers ne sont pas joignables depuis ce poste :\n\n'
                + '\n'.join(missing)
                + '\n\nC\'est normal pour un partage réseau hors ligne, ou '
                  'monté ailleurs.\nEnregistrer quand même ?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer != QMessageBox.Yes:
                self.w_note.setText(
                    'Corrigez le chemin, ou videz le champ pour revenir au '
                    'dernier emplacement employé.')
                self.w_note.setStyleSheet(theme.css('warn'))
                return
        for kind, _, _ in session.FOLDER_KINDS:
            session.set_default_folder(kind, self.fields[kind].currentText())
        session.set_machine_template(self.w_template.currentText())
        self.accept()
