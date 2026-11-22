"""Dialogue d'import DXF / DXF import dialog.

Trois décisions y sont prises, parce qu'aucune ne peut être devinée de
façon fiable :

* **l'unité** — l'en-tête `$INSUNITS` est souvent faux ;
* **les calques à importer** — un DXF de production mélange géométrie
  utile, cotation et repères ;
* **la mise à l'échelle** — si la pièce dépasse le champ de marquage.
"""
from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QLabel,
                               QListWidget, QListWidgetItem, QVBoxLayout)

from . import dxfimport
from .geometry import bounds
from .model import Document, Path, Recipe, hors_borne
from .widgets import Combo
from . import theme


class DxfImportDialog(QDialog):
    """Relit le fichier à chaque changement d'unité pour montrer le résultat."""

    def __init__(self, parent, file_path: str, document: Document,
                 recipe: Recipe) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            'Importer un DXF' if dxfimport.is_dxf(file_path)
            else 'Importer un dessin vectoriel')
        self.setMinimumWidth(460)
        self.file_path = file_path
        self.document = document
        self.recipe = recipe
        self.shapes: list[Path] = []
        self.report: dxfimport.ImportReport | None = None
        self._guard = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'<b>{pathlib.Path(file_path).name}</b>'))

        form = QFormLayout()
        self.w_units = Combo()
        # Le millimètre est proposé d'emblée : l'en-tête `$INSUNITS` des DXF
        # de production est trop souvent faux — celui d'un fichier d'essai
        # se déclare en mètres pour un dessin tracé en millimètres.
        for label, factor in dxfimport.UNIT_CHOICES:
            self.w_units.addItem(label, factor)
        self.w_units.addItem('déclarée dans le fichier', None)
        self.w_units.setCurrentIndex(0)          # millimètre
        self.w_units.currentIndexChanged.connect(self._reload)
        # Le PDF et le PostScript portent leur unité — le point, 1/72 de
        # pouce — et n'ont donc rien à faire régler. Seul le DXF, dont
        # l'en-tête ment si souvent, garde le choix.
        self._units_row = QLabel('Unité')
        if dxfimport.is_dxf(file_path):
            form.addRow(self._units_row, self.w_units)
        else:
            # signaux coupés **avant** le choix : sinon `_reload` part
            # aussitôt, alors que le reste du formulaire n'existe pas
            self.w_units.blockSignals(True)
            self.w_units.setCurrentIndex(self.w_units.count() - 1)
            self.w_units.blockSignals(False)

        self.w_center = QCheckBox('Centrer en 0,0')
        self.w_center.setChecked(True)
        self.w_center.setToolTip(
            'Recentre l\'ensemble sur l\'origine du plan de travail.\n'
            'Décoché, les coordonnées du DXF sont conservées telles quelles.')
        self.w_center.toggled.connect(self._reload)
        form.addRow('', self.w_center)

        self.w_fit = QCheckBox('Réduire pour tenir dans le champ')
        self.w_fit.toggled.connect(self._update_summary)
        form.addRow('', self.w_fit)
        layout.addLayout(form)

        layout.addWidget(QLabel('Calques à importer :'))
        self.w_layers = QListWidget()
        self.w_layers.setMaximumHeight(140)
        self.w_layers.itemChanged.connect(self._update_summary)
        layout.addWidget(self.w_layers)

        self.w_summary = QLabel('')
        self.w_summary.setWordWrap(True)
        layout.addWidget(self.w_summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.Ok)

        self._reload()

    # -- lecture -----------------------------------------------------------

    def _reload(self) -> None:
        """Relit le fichier, avec une barre au-delà d'une seconde.

        Ce dialogue relit **à chaque changement** d'unité ou de centrage :
        c'est voulu, la géométrie en dépend. Mais un plan de cinq
        mégaoctets prend alors une seconde à chaque case cochée, et sans
        rien à l'écran cela ressemble à un blocage.
        """
        units = self.w_units.currentData()
        from . import fontmap
        from .longtask import barre
        try:
            with barre(self, 'Lecture du dessin…') as progres:
                self.shapes, self.report = dxfimport.any_to_shapes(
                    self.file_path, recipe=self.recipe, units_mm=units,
                    center=self.w_center.isChecked(),
                    ask=fontmap.ask_via(self), progress=progres)
        except dxfimport.Cancelled:
            # renoncer n'est pas une erreur : on garde ce qu'on avait, et
            # le bouton reste ce qu'il était
            return
        except dxfimport.DxfError as exc:
            self.shapes, self.report = [], None
            self.w_summary.setText(
                f'{theme.span('alarm')}{exc}</span>')
            self._ok.setEnabled(False)
            return

        self._guard = True
        self.w_layers.clear()
        for shape in self.shapes:
            item = QListWidgetItem(
                f'{shape.layer}  —  {len(shape.polylines)} polyligne(s)')
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, shape.layer)
            self.w_layers.addItem(item)
        self._guard = False

        # proposer d'emblée la réduction si ça ne tient pas
        self.w_fit.setChecked(
            not self.report.fits(self.document.field_w, self.document.field_h))
        # le résumé a le dernier mot sur le bouton : il le refuse à un
        # dessin qui passerait les dix mètres
        self._ok.setEnabled(True)
        self._update_summary()

    def _selected_layers(self) -> set[str]:
        return {self.w_layers.item(i).data(Qt.UserRole)
                for i in range(self.w_layers.count())
                if self.w_layers.item(i).checkState() == Qt.Checked}

    def _scale_factor(self) -> float:
        """Réduction à appliquer pour tenir dans le champ, 1.0 sinon."""
        if not self.w_fit.isChecked():
            return 1.0
        chosen = self.selected_shapes(scaled=False)
        b = bounds([p for s in chosen for p in s.polylines])
        if not b:
            return 1.0
        w, h = b[2] - b[0], b[3] - b[1]
        if w <= 0 or h <= 0:
            return 1.0
        factor = min(self.document.field_w / w, self.document.field_h / h)
        return min(1.0, factor)

    def _update_summary(self) -> None:
        if self._guard or self.report is None:
            return
        chosen = self.selected_shapes(scaled=False)
        if not chosen:
            self.w_summary.setText(
                f'{theme.span()}Aucun calque sélectionné.</span>')
            self._ok.setEnabled(False)
            return
        self._ok.setEnabled(True)

        factor = self._scale_factor()
        b = bounds([p for s in chosen for p in s.polylines])
        w, h = (b[2] - b[0]) * factor, (b[3] - b[1]) * factor
        count = sum(len(s.polylines) for s in chosen)

        lines = [f'{count} polyligne(s) · <b>{w:.1f} × {h:.1f} mm</b>']
        if factor < 1.0:
            lines.append(f'réduction à {factor * 100:.1f} %')
        if self.report.skipped_text:
            lines.append(f'{self.report.skipped_text} texte(s) vide(s) ou '
                         'sans glyphe exploitable')
        if getattr(self.report, 'font_substitutions', None):
            noms = ', '.join(sorted(self.report.font_substitutions))
            lines.append(f'texte rendu avec une police de substitution : '
                         f'{noms}')
        if self.report.skipped_other:
            lines.append('non géré : '
                         + ', '.join(sorted(self.report.skipped_other)))
        vides = getattr(self.report, 'skipped_empty', None)
        if vides:
            lines.append(f'{sum(vides.values())} tracé(s) sans longueur '
                         'écarté(s) — points isolés, rien à graver')

        # L'indice sur l'unité est d'autant plus utile que la réduction est
        # forte : une pièce ramenée à 0,1 % trahit presque toujours un
        # `$INSUNITS` erroné, pas un dessin réellement géant.
        for remarque in getattr(self.report, 'notes', ()):
            lines.append(f'{theme.span('warn')}{remarque}</span>')

        if self.w_units.currentData() is None:
            warning = self.report.unit_warning(self.document.field_w,
                                               self.document.field_h)
            if warning:
                lines.append(f'{theme.span('warn')}{warning}</span>')

        # Au-delà de dix mètres de l'origine, un point ne survit ni à
        # l'enregistrement ni à « annuler » : la relecture l'écarte. Le
        # dessin entrait, puis disparaissait au premier « refaire ».
        if hors_borne(tuple(c * factor for c in b)):
            remede = ('« Centrer en 0,0 »' if not self.w_center.isChecked()
                      else '« Réduire pour tenir dans le champ »')
            lines.append(f'{theme.span('alarm')}À plus de dix mètres de '
                         f'l\'origine, ce dessin ne pourrait être ni '
                         f'enregistré ni annulé : cocher {remede}.</span>')
            self._ok.setEnabled(False)
        self.w_summary.setText('<br>'.join(lines))

    # -- résultat ----------------------------------------------------------

    def _recentrage(self, chosen: list[Path]) -> tuple[float, float]:
        """Ce qui centre les calques retenus, « Centrer » coché.

        L'import centre le dessin **entier** : un calque retenu seul, loin
        des autres, restait loin de l'origine. Au-delà de dix mètres, le
        dialogue le refusait, en conseillant une case déjà cochée."""
        if not self.w_center.isChecked():
            return 0.0, 0.0
        b = bounds([p for s in chosen for p in s.polylines])
        if not b:
            return 0.0, 0.0
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        # tous les calques retenus : déjà centrés, à l'arrondi près
        if abs(cx) < 1e-6 and abs(cy) < 1e-6:
            return 0.0, 0.0
        return -cx, -cy

    def selected_shapes(self, scaled: bool = True) -> list[Path]:
        keep = self._selected_layers()
        chosen = [s for s in self.shapes if s.layer in keep]
        dx, dy = self._recentrage(chosen)
        factor = min(1.0, self._scale_factor()) if scaled else 1.0
        if factor >= 1.0 and not (dx or dy):
            return chosen
        out = []
        for s in chosen:
            if dx or dy:
                polys = [[((x + dx) * factor, (y + dy) * factor)
                          for x, y in poly] for poly in s.polylines]
            else:
                polys = [[(x * factor, y * factor) for x, y in poly]
                         for poly in s.polylines]
            copy = Path(x=s.x, y=s.y, rotation_deg=s.rotation_deg,
                        recipe=s.recipe, source=s.source, layer=s.layer,
                        polylines=polys)
            out.append(copy)
        return out
