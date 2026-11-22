"""Préréglages de code / Code presets.

Une plaque de production ne se règle qu'une fois : symbologie, forme,
fenêtre, zone de silence, remplissage, cadre, épaisseur de trait, et la
fenêtre du texte qui l'accompagne. Le même réglage resservira pour toutes
les pièces de la série, et pour la série suivante.

Un préréglage retient **tout le formulaire** — sauf la position, qui
appartient à la plaque et non au réglage. Les préréglages vivent dans le
dossier de configuration de l'utilisateur, à côté des recettes, et se
portent sur un autre poste par les boutons *Exporter…* / *Importer…*
du gestionnaire — un fichier `.codes.json`, voir `echange`.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout)

from .model import (ILLISIBLE, Code, ecrire_symbologie, lire_symbologie,
                    note_repair, value_like)
from . import theme

#: Champs du formulaire retenus par un préréglage. La position (`x`, `y`),
#: l'identité (`id`, `name`, `group`) et la recette en sont exclues : la
#: première appartient à la plaque, la seconde à la forme, la troisième à
#: la bibliothèque de recettes.
FIELDS = (
    'kind', 'data', 'module_mm', 'level', 'quiet_modules', 'dm_shape',
    'checksum', 'bar_height_mm', 'fit_w_mm', 'fit_h_mm', 'fill_step_mm',
    'frame', 'frame_margin_mm', 'frame_w', 'frame_h',
    'line_width_mm', 'line_step_mm', 'rotation_deg',
)

#: Préréglages d'usine, repris de la plaque de production.
FACTORY: tuple[dict, ...] = (
    {
        'name': 'Plaque 15 × 7 — DataMatrix',
        'kind': 'datamatrix', 'data': 'B{n:06}', 'dm_shape': 'auto',
        'quiet_modules': 0, 'fit_w_mm': 15.0, 'fit_h_mm': 7.0,
        'text_w_mm': 8.071, 'text_h_mm': 1.538, 'with_text': True,
        'text_dx_mm': -15.07, 'text_dy_mm': -3.73,
    },
    {
        # cadre de 16 x 8 mm autour d'un symbole de 15 x 7 : la cote exacte
        # de la plaque de production
        'name': 'Plaque 15 × 7 — négatif encadré',
        'kind': 'datamatrix', 'data': 'B{n:06}', 'dm_shape': 'auto',
        'quiet_modules': 0, 'fit_w_mm': 15.0, 'fit_h_mm': 7.0,
        'frame': 'rect', 'frame_margin_mm': 0.5,
        'text_w_mm': 8.071, 'text_h_mm': 1.538, 'with_text': True,
        'text_dx_mm': -15.07, 'text_dy_mm': -3.73,
    },
    {
        'name': 'QR 12 × 12',
        'kind': 'qr', 'data': '{job} {n:04}', 'level': 'M',
        'quiet_modules': 4, 'fit_w_mm': 12.0, 'fit_h_mm': 12.0,
        'text_w_mm': 10.0, 'text_h_mm': 2.0, 'with_text': False,
        'text_dx_mm': 0.0, 'text_dy_mm': -8.5,
    },
)

_LIBRARY: list[dict] = []


def library() -> list[dict]:
    """Préréglages en vigueur, chargés à la première demande."""
    if not _LIBRARY:
        _LIBRARY.extend(load())
    return _LIBRARY


def set_library(presets: list[dict]) -> None:
    _LIBRARY[:] = [p for p in presets if p.get('name')] or list(FACTORY)


def library_path() -> pathlib.Path:
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(
        QStandardPaths.AppConfigLocation) or str(pathlib.Path.home())
    return pathlib.Path(base) / 'codes.json'


def load() -> list[dict]:
    path = library_path()
    if not path.exists():
        return [dict(p) for p in FACTORY]
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        raw = data.get('presets', data) if isinstance(data, dict) else data
        out = [p for p in raw if isinstance(p, dict) and p.get('name')]
    except (OSError, ValueError, TypeError):
        return [dict(p) for p in FACTORY]
    return out or [dict(p) for p in FACTORY]


def save(presets: list[dict]) -> None:
    path = library_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'presets': presets}, indent=2,
                              ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


# --------------------------------------------------------------------------

def from_code(name: str, code: Code, *, text_w_mm: float = 0.0,
              text_h_mm: float = 0.0, with_text: bool = True,
              text_dx_mm: float = 0.0, text_dy_mm: float = 0.0) -> dict:
    """Préréglage retenant tout le formulaire d'un code.

    La fenêtre du texte est retenue **en position relative** au centre du
    code : c'est ce qui permet de reposer la même plaque ailleurs sans
    refaire l'implantation.
    """
    values = dataclasses.asdict(code)
    preset = {'name': name}
    preset.update({field: values[field] for field in FIELDS})
    # un préréglage se porte sur d'autres postes, d'autres versions
    ecrire_symbologie(preset, code.kind)
    preset['text_w_mm'] = float(text_w_mm)
    preset['text_h_mm'] = float(text_h_mm)
    preset['text_dx_mm'] = float(text_dx_mm)
    preset['text_dy_mm'] = float(text_dy_mm)
    preset['with_text'] = bool(with_text)
    return preset


def text_frame_of(preset: dict, cx: float, cy: float):
    """Fenêtre du texte d'un préréglage, placée autour d'un code."""
    if not preset.get('with_text'):
        return None
    return (cx + float(preset.get('text_dx_mm', 0.0)),
            cy + float(preset.get('text_dy_mm', 0.0)),
            float(preset.get('text_w_mm', 8.071)),
            float(preset.get('text_h_mm', 1.538)))


def apply_to(code: Code, preset: dict) -> None:
    """Applique un préréglage à un code, **sans toucher à sa position**.

    Un préréglage décrit un réglage, pas un emplacement : l'appliquer à un
    code déjà posé ne doit pas le faire sauter ailleurs sur la plaque.

    Chaque valeur est lue comme dans un document (`model.value_like`). Un
    préréglage importé d'un autre poste, écrit par une version plus
    récente ou retouché à la main portait sinon tel quel dans la plaque
    une symbologie inconnue — le document ne se rouvrait plus, instantané
    de séance compris — ou un module illisible, qui faisait tomber le
    calcul des trajectoires. Une valeur qui ne convient pas est laissée
    de côté, et dite : le code garde la sienne.
    """
    defaut = Code()
    nom = preset.get('name', '?')
    for field in FIELDS:
        if field == 'kind':
            if 'kind' not in preset and 'kind_recent' not in preset:
                continue
            valeur = preset.get('kind_recent', preset.get('kind'))
            lue = lire_symbologie(preset, ILLISIBLE)
        elif field not in preset:
            continue
        else:
            valeur = preset[field]
            lue = value_like(field, getattr(defaut, field), valeur)
        if lue is ILLISIBLE:
            note_repair(None, f'préréglage « {nom!s:.40} » : '
                              f'{field} = {valeur!r:.40} laissé de côté')
            continue
        setattr(code, field, lue)


def describe(preset: dict) -> str:
    """Résumé d'une ligne, pour l'infobulle de la liste.

    Il se construit avec l'inspecteur de chaque code : une valeur
    retouchée à la main — `"fit_w_mm": "15"`, une liste à la place d'une
    symbologie — le faisait tomber, et plus aucun code n'était réglable
    tant que le préréglage restait en bibliothèque. Seules des valeurs
    lisibles sont mises en forme (`model.value_like`)."""
    def mesure(champ: str) -> float:
        lue = value_like(champ, 0.0, preset.get(champ, 0.0))
        return 0.0 if lue is ILLISIBLE else lue

    brute = preset.get('kind_recent', preset.get('kind'))
    kind = {'datamatrix': 'DataMatrix', 'qr': 'QR',
            'code39': 'Code 39', 'ean13': 'EAN-13',
            'code128': 'Code 128'}.get(
        lire_symbologie(preset),
        f'{brute:.20}' if isinstance(brute, str) else '?')
    bits = [kind, f"« {preset.get('data', '')!s:.60} »"]
    largeur, hauteur = mesure('fit_w_mm'), mesure('fit_h_mm')
    if largeur and hauteur:
        bits.append(f'fenêtre {largeur:g} × {hauteur:g} mm')
    if preset.get('frame', 'none') != 'none':
        bits.append('négatif encadré')
    if preset.get('with_text'):
        bits.append(f"texte {mesure('text_w_mm'):g} × "
                    f"{mesure('text_h_mm'):g} mm")
    return ' · '.join(bits)


class CodePresetManager(QDialog):
    """Renommer, dupliquer, réordonner et supprimer les préréglages."""

    def __init__(self, parent=None, current: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Préréglages de code')
        self.setMinimumSize(560, 380)
        self.presets: list[dict] = [dict(p) for p in library()]
        self.current = current

        layout = QVBoxLayout(self)
        intro = QLabel(
            'Un préréglage retient tout le formulaire — symbologie, donnée, '
            'fenêtre, silence, remplissage, cadre, texte — sauf la position, '
            'qui appartient à la plaque.')
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.css())
        layout.addWidget(intro)

        self.w_list = QListWidget()
        self.w_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.w_list, 1)

        row = QHBoxLayout()
        actions = [('Renommer', self._rename), ('Dupliquer', self._copy),
                   ('Monter', lambda: self._move(-1)),
                   ('Descendre', lambda: self._move(1)),
                   ('Supprimer', self._remove), ('Usine', self._factory)]
        if current is not None:
            actions.insert(0, ('Enregistrer le réglage courant', self._capture))
        for label, slot in actions:
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        # d'un poste à l'autre : un fichier `.codes.json`, montré avant
        # d'entrer — voir `echange`
        row2 = QHBoxLayout()
        for label, slot, tip in (
                ('Importer…', self._import,
                 'Reprend des préréglages d\'un fichier .codes.json écrit '
                 'sur un autre poste.'),
                ('Exporter…', self._export,
                 'Écrit tous les préréglages dans un fichier .codes.json, '
                 'à relire sur un autre poste.')):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row2.addWidget(button)
        row2.addStretch(1)
        layout.addLayout(row2)

        buttons = QDialogButtonBox(QDialogButtonBox.Save
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self, select: int = -1) -> None:
        self.w_list.clear()
        for preset in self.presets:
            item = QListWidgetItem(preset['name'])
            item.setToolTip(describe(preset))
            self.w_list.addItem(item)
        if select >= 0 and self.presets:
            self.w_list.setCurrentRow(min(select, len(self.presets) - 1))

    def _row(self) -> int:
        return self.w_list.currentRow()

    def _capture(self) -> None:
        name, ok = QInputDialog.getText(
            self, 'Enregistrer le réglage', 'Nom du préréglage :',
            text=self.current.get('name', 'Nouveau réglage'))
        name = name.strip()
        if not ok or not name:
            return
        preset = dict(self.current)
        preset['name'] = name
        existing = next((i for i, p in enumerate(self.presets)
                         if p['name'] == name), None)
        if existing is None:
            self.presets.append(preset)
            self._refresh(len(self.presets) - 1)
        else:
            self.presets[existing] = preset
            self._refresh(existing)

    def _rename(self) -> None:
        row = self._row()
        if not (0 <= row < len(self.presets)):
            return
        name, ok = QInputDialog.getText(self, 'Renommer', 'Nom :',
                                        text=self.presets[row]['name'])
        name = name.strip()
        if ok and name:
            self.presets[row]['name'] = name
            self._refresh(row)

    def _copy(self) -> None:
        row = self._row()
        if not (0 <= row < len(self.presets)):
            return
        clone = dict(self.presets[row])
        clone['name'] = f"{clone['name']} (copie)"
        self.presets.insert(row + 1, clone)
        self._refresh(row + 1)

    def _move(self, direction: int) -> None:
        row = self._row()
        target = row + direction
        if not (0 <= row < len(self.presets)
                and 0 <= target < len(self.presets)):
            return
        self.presets[row], self.presets[target] = \
            self.presets[target], self.presets[row]
        self._refresh(target)

    def _remove(self) -> None:
        row = self._row()
        if not (0 <= row < len(self.presets)):
            return
        if len(self.presets) == 1:
            QMessageBox.information(
                self, 'Préréglages',
                'La bibliothèque doit garder au moins un préréglage.')
            return
        del self.presets[row]
        self._refresh(max(0, row - 1))

    def _factory(self) -> None:
        if QMessageBox.question(
                self, 'Préréglages d\'usine',
                'Remplacer toute la bibliothèque par les préréglages '
                'd\'usine ?') != QMessageBox.StandardButton.Yes:
            return
        self.presets = [dict(p) for p in FACTORY]
        self._refresh(0)

    def _export(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from . import echange, session
        depart = pathlib.Path(session.start_folder('reglages'))
        chemin, _ = QFileDialog.getSaveFileName(
            self, 'Exporter les préréglages de code',
            str(depart / f'codes {echange.poste()}'
                + echange.SUFFIX_CODES),
            echange.FILTRE_CODES)
        if not chemin:
            return
        try:
            cible = echange.ecrire_codes(chemin, self.presets)
        except echange.EchangeError as exc:
            QMessageBox.warning(self, 'Exporter les préréglages', str(exc))
            return
        session.remember_file('reglages', str(cible))
        QMessageBox.information(
            self, 'Exporter les préréglages',
            f'{len(self.presets)} préréglage(s) écrit(s) dans\n{cible}')

    def _import(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from . import echange, session
        chemin, _ = QFileDialog.getOpenFileName(
            self, 'Importer des préréglages de code',
            session.start_folder('reglages'), echange.FILTRE_CODES)
        if not chemin:
            return
        try:
            venus, entete = echange.lire_codes(chemin)
        except echange.EchangeError as exc:
            QMessageBox.warning(self, 'Importer des préréglages', str(exc))
            return
        if not venus:
            QMessageBox.information(
                self, 'Importer des préréglages',
                'Ce fichier ne contient aucun préréglage.')
            return
        session.remember_file('reglages', chemin)
        choix = echange.ChoixImport(
            self, 'Importer des préréglages de code', entete, venus,
            lambda p: p['name'], {p['name'] for p in self.presets})
        if choix.exec() != QDialog.DialogCode.Accepted:
            return
        retenus = choix.retenues()
        if not retenus:
            return
        self.presets = echange.fusionner(self.presets, retenus,
                                         lambda p: p['name'])
        self._refresh(len(self.presets) - 1)

    def _save(self) -> None:
        names = [p['name'] for p in self.presets]
        doubles = {n for n in names if names.count(n) > 1}
        if doubles:
            QMessageBox.warning(
                self, 'Préréglages',
                'Deux préréglages portent le même nom : '
                + ', '.join(sorted(doubles)))
            return
        save(self.presets)
        set_library(self.presets)
        self.accept()
