"""Réglages au niveau du travail / Job-level settings.

Nom du travail, quantité et numérotation de série. Ces réglages ne
dépendent d'aucune forme : ils décrivent le lot à produire.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFormLayout, QLabel, QLineEdit, QVBoxLayout,
                               QWidget)

from . import theme, variables
from .widgets import IntSpin
from .model import Document


class JobPanel(QWidget):
    """Nom, quantité, série."""

    changed = Signal()

    def __init__(self, document: Document) -> None:
        super().__init__()
        self.document = document
        self._guard = False

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        form = QFormLayout()
        theme.tidy_form(form)

        self.w_name = QLineEdit(document.name)
        self.w_name.textChanged.connect(self._apply)

        self.w_copies = IntSpin(document.copies, 1, 9999)
        self.w_copies.setToolTip(
            'Nombre de pièces. Au-delà de 1, un jeu complet de fichiers est '
            'produit par pièce,\navec les champs variables réévalués.')
        self.w_copies.valueChanged.connect(self._apply)

        self.w_start = IntSpin(document.serial_start, 0, 99_999_999)
        self.w_start.valueChanged.connect(self._apply)

        self.w_step = IntSpin(document.serial_step, -9999, 9999)
        self.w_step.valueChanged.connect(self._apply)

        form.addRow('Travail', self.w_name)
        form.addRow('Quantité', self.w_copies)
        form.addRow('Premier n°', self.w_start)
        form.addRow('Pas', self.w_step)
        layout.addLayout(form)

        self.w_preview = QLabel('')
        self.w_preview.setWordWrap(True)
        self.w_preview.setStyleSheet(theme.css('text_dim', 11))
        layout.addWidget(self.w_preview)

        help_text = QLabel(
            'Champs utilisables dans les textes :\n'
            + '\n'.join(f'   {{{k}}} — {v}' for k, v in
                        variables.KNOWN_FIELDS.items())
            + '\n   {n:04} pour compléter par des zéros')
        help_text.setStyleSheet(theme.css('text_dim', 11))
        layout.addWidget(help_text)

        self.refresh()

    def set_document(self, document: Document) -> None:
        self.document = document
        self._guard = True
        self.w_name.setText(document.name)
        self.w_copies.setValue(document.copies)
        self.w_start.setValue(document.serial_start)
        self.w_step.setValue(document.serial_step)
        self._guard = False
        self.refresh()

    def _apply(self, *_) -> None:
        if self._guard:
            return
        self.document.name = self.w_name.text().strip() or 'gravure'
        self.document.copies = self.w_copies.value()
        self.document.serial_start = self.w_start.value()
        self.document.serial_step = self.w_step.value()
        self.refresh()
        self.changed.emit()

    def refresh(self) -> None:
        doc = self.document
        enabled = doc.copies > 1
        self.w_start.setEnabled(True)
        self.w_step.setEnabled(enabled)
        if enabled:
            first, last = doc.serial_for(0), doc.serial_for(doc.copies - 1)
            self.w_preview.setText(
                f'{doc.copies} pièces · n° {first} → {last} · '
                f'{doc.copies} jeux de fichiers')
        else:
            self.w_preview.setText(f'1 pièce · n° {doc.serial_for(0)}')
