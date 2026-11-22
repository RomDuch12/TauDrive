"""Magasin d'outils de la machine / Machine tool magazine.

**Lecture seule.** Réponse courte aux deux questions posées :

* **lire `dbpunte.mag` : oui.** Sept champs sont décodés — nom, vitesse,
  puissance, fréquence, résolution, diamètre de spot, durée d'impulsion —
  sur les cent emplacements du magasin. La méthode et les preuves sont
  dans [`magasin-outils.md`](../../reference/magasin-outils.md).

* **l'écrire : non, et ce n'est pas une timidité.** Un enregistrement fait
  **12 411 octets, dont 12 400 ne sont pas décodés** : corrections, tables
  de calibration, paramètres de découpe. Écrire les sept champs connus
  reviendrait à rendre un fichier dont on ne saurait pas garantir le
  reste. Le magasin vit en outre dans les dossiers du constructeur, que
  TauDrive ne modifie jamais (EX-01) — et une machine dont le magasin est
  corrompu ne grave plus rien, sur aucun travail.

  Ce qu'on peut faire à la place, et qui suffit : **charger un outil dans
  une recette**. Les valeurs viennent de la machine, la recette vit chez
  TauDrive, et le magasin n'est pas touché.

**Disponible en mode simple.** Le magasin ne fait que lire, et choisir un
outil de la machine est plus sûr que d'ajuster à la main une fréquence
qu'on ne voit pas : on prend un jeu de valeurs cohérent, tel que la
machine le porte, plutôt que d'en composer un.
"""
from __future__ import annotations

import json
import pathlib
import struct
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from . import session
from .model import Recipe, default_recipe
from . import theme

#: Structure d'un enregistrement, telle qu'établie par balayage
#: différentiel — voir `outils/extraire_outils.py`.
HEADER = 120
STRIDE = 12411
OFF_NAME = 40
OFF_SPEED = 1275        # f32, mm/min
OFF_POWER = 1371        # f32, %
OFF_FREQ = 1387         # i32, Hz
OFF_RES = 1403          # i32, points/mm
OFF_SPOT = 1419         # f32, mm
OFF_PULSE = 12091       # i32, ns
SLOTS = 100

#: Bornes de vraisemblance : un emplacement vide ou un séparateur de
#: présentation ne doit pas se retrouver proposé comme recette.
PLAUSIBLE = {
    'speed_mm_min': (1.0, 1_000_000.0),
    'power_percent': (0.0, 100.0),
    'frequency_hz': (1, 5_000_000),
    'pulse_width_ns': (1, 65_535),
}

#: Réglage du chemin du magasin, pour un poste dont l'installation diffère.
FOLDER_KEY = 'machine/dbpunte'


@dataclass(frozen=True)
class Tool:
    """Un emplacement du magasin."""
    number: int
    name: str
    speed_mm_min: float
    power_percent: float
    frequency_hz: int
    resolution_px_mm: int
    spot_mm: float
    pulse_width_ns: int

    def plausible(self) -> bool:
        for champ, (bas, haut) in PLAUSIBLE.items():
            valeur = getattr(self, champ)
            if not (bas <= valeur <= haut):
                return False
        return True

    def separator(self) -> bool:
        """Les magasins Cielle portent des séparateurs de présentation."""
        nu = self.name.strip('_- ')
        return not nu or self.name.startswith('__')

    def label(self) -> str:
        return (f'T{self.number}  {self.name}   '
                f'[{self.power_percent:g} %, {self.frequency_hz / 1000:g} kHz, '
                f'{self.speed_mm_min / 1000:g} m/min, '
                f'{self.pulse_width_ns} ns]')

    def to_recipe(self, base: Recipe | None = None) -> Recipe:
        """Recette portant les valeurs de cet outil.

        Le **pas de hachurage** reprend le diamètre de spot : c'est le pas
        naturel, celui en dessous duquel on repasse sur la matière déjà
        enlevée. Ce qui n'est pas dans le magasin — nombre de passes et
        profondeur — est laissé tel quel : ces deux-là appartiennent au
        travail, pas à l'outil.
        """
        import dataclasses as _dc
        depart = base or default_recipe()
        return _dc.replace(
            depart,
            name=self.name.strip() or f'Outil T{self.number}',
            tool_number=self.number,
            power_percent=round(self.power_percent, 3),
            frequency_khz=round(self.frequency_hz / 1000.0, 3),
            pulse_width_ns=int(self.pulse_width_ns),
            speed_mm_min=round(self.speed_mm_min, 3),
            hatch_mm=round(self.spot_mm, 4) if self.spot_mm > 0
            else depart.hatch_mm,
            comment=f'Chargé du magasin machine, emplacement T{self.number} '
                    f'(spot {self.spot_mm:g} mm, '
                    f'{self.resolution_px_mm} pts/mm).')


def _text(data: bytes, base: int) -> str:
    fin = data.find(b'\0', base)
    brut = data[base:fin if fin >= 0 else base + 64]
    return brut.decode('latin-1', 'replace').strip()


def read_mag(path: str | pathlib.Path) -> list[Tool]:
    """Décode un `dbpunte.mag`. Lecture seule, sans jamais lever."""
    try:
        data = pathlib.Path(path).read_bytes()
    except OSError:
        return []
    out: list[Tool] = []
    for index in range(SLOTS):
        base = HEADER + index * STRIDE
        if base + STRIDE > len(data):
            break
        try:
            out.append(Tool(
                number=index + 1,
                name=_text(data, base + OFF_NAME),
                speed_mm_min=struct.unpack_from('<f', data, base + OFF_SPEED)[0],
                power_percent=struct.unpack_from('<f', data, base + OFF_POWER)[0],
                frequency_hz=struct.unpack_from('<i', data, base + OFF_FREQ)[0],
                resolution_px_mm=struct.unpack_from('<i', data, base + OFF_RES)[0],
                spot_mm=struct.unpack_from('<f', data, base + OFF_SPOT)[0],
                pulse_width_ns=struct.unpack_from('<i', data, base + OFF_PULSE)[0],
            ))
        except struct.error:
            break
    return out


def _from_json(path: pathlib.Path) -> list[Tool]:
    """Magasin extrait, embarqué avec l'application."""
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    out = []
    for brut in data.get('tools', []):
        try:
            out.append(Tool(
                number=int(brut.get('tool_number') or 0),
                name=str(brut.get('name') or ''),
                speed_mm_min=float(brut.get('speed_mm_min') or 0.0),
                power_percent=float(brut.get('power_percent') or 0.0),
                frequency_hz=int(brut.get('frequency_hz') or 0),
                resolution_px_mm=int(brut.get('resolution_px_mm') or 0),
                spot_mm=float(brut.get('spot_mm') or 0.0),
                pulse_width_ns=int(brut.get('pulse_width_ns') or 0),
            ))
        except (TypeError, ValueError):
            continue
    return out


def mag_path() -> str:
    """Chemin réglé du `dbpunte.mag`, ou une chaîne vide."""
    return str(session.settings().value(FOLDER_KEY) or '')


def set_mag_path(path: str) -> None:
    session.settings().setValue(FOLDER_KEY, (path or '').strip())


def bundled_path() -> pathlib.Path:
    """Magasin extrait de la machine, apporté par le plugin de l'atelier.

    Le cœur libre n'en livre aucun : sans plugin, ce chemin n'existe pas,
    et seul le `dbpunte.mag` réglé est lu.
    """
    from .plugins import REGISTRY
    if REGISTRY.tool_store is not None:
        return REGISTRY.tool_store
    from .app import resource_dir
    return resource_dir() / 'extrait' / 'outils.json'


def source() -> tuple[str, str]:
    """(chemin employé, nature). Le fichier machine prime sur l'extrait."""
    regle = mag_path()
    if regle and session.reachable(regle):
        return regle, 'machine'
    embarque = bundled_path()
    if session.reachable(str(embarque)):
        return str(embarque), 'extrait'
    return '', 'absent'


def tools(plausible_only: bool = True) -> list[Tool]:
    """Le magasin, lu du fichier machine s'il répond, de l'extrait sinon."""
    chemin, nature = source()
    if not chemin:
        return []
    lus = read_mag(chemin) if nature == 'machine' \
        else _from_json(pathlib.Path(chemin))
    if not plausible_only:
        return lus
    return [t for t in lus if t.plausible() and not t.separator()]


def writable() -> tuple[bool, str]:
    """Toujours non, avec la raison — elle mérite d'être lue."""
    return False, (
        'Le magasin est lu, jamais écrit. Un enregistrement fait 12 411 '
        'octets dont 12 400 ne sont pas décodés — corrections, tables de '
        'calibration, paramètres de découpe. En réécrire sept champs '
        'rendrait un fichier dont le reste ne serait plus garanti, et une '
        'machine au magasin corrompu ne grave plus rien, sur aucun '
        'travail.\n\n'
        'Charger un outil dans une process donne le même résultat sans '
        'toucher à la machine.')


class ToolStorePanel(QWidget):
    """Choisir un outil du magasin pour en charger les valeurs.

    **Disponible en mode simple.** Le panneau ne fait que lire, et charger
    un outil de la machine donne un jeu de valeurs cohérent — plus sûr que
    d'ajuster une fréquence à la main. L'écran indique en permanence d'où
    viennent les valeurs affichées.
    """

    chosen = Signal(object)        # outil choisi

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Magasin d\'outils de la machine')
        self.setMinimumWidth(300)
        self.picked: Tool | None = None

        dehors = QVBoxLayout(self)
        chemin, nature = source()
        origine = {'machine': 'lu directement sur la machine',
                   'extrait': 'extrait embarqué avec TauDrive',
                   'absent': 'introuvable'}[nature]
        self.w_source = QLabel(f'<b>Magasin</b> — {origine}<br>'
                               f'<span style="color:{theme.hex_of('text_dim')}">{chemin}</span>')
        self.w_source.setWordWrap(True)
        dehors.addWidget(self.w_source)

        self.w_list = QListWidget()
        for outil in tools():
            item = QListWidgetItem(outil.label())
            item.setData(Qt.UserRole, outil)
            item.setToolTip(
                f'Résolution {outil.resolution_px_mm} pts/mm · '
                f'spot {outil.spot_mm:g} mm')
            self.w_list.addItem(item)
        self.w_list.itemDoubleClicked.connect(lambda *_: self._take())
        dehors.addWidget(self.w_list, 1)

        note = QLabel(
            'Charger un outil reprend puissance, fréquence, impulsion, '
            'vitesse et pas de hachurage.<br><b>Nombre de passes et '
            'profondeur ne sont pas dans le magasin</b> : ils appartiennent '
            'au travail, pas a l\'outil, et restent tels quels.')
        note.setWordWrap(True)
        note.setStyleSheet(theme.css())
        dehors.addWidget(note)

        barre = QHBoxLayout()
        self.w_load = QPushButton('Charger dans la process')
        self.w_load.setToolTip(
            'Reprend puissance, fréquence, impulsion, vitesse et pas '
            'de hachurage\n'
            'dans la process sélectionnée du gestionnaire.')
        self.w_load.clicked.connect(self._take)
        barre.addWidget(self.w_load, 1)
        dehors.addLayout(barre)
        if self.w_list.count():
            self.w_list.setCurrentRow(0)

    def _take(self) -> None:
        item = self.w_list.currentItem()
        if item is None:
            return
        self.picked = item.data(Qt.UserRole)
        self.chosen.emit(self.picked)

    def reload(self) -> None:
        """Relit le magasin : utile après un retour du réseau."""
        session.forget_reachability()
        garde = self.w_list.currentRow()
        self.w_list.clear()
        for outil in tools():
            item = QListWidgetItem(outil.label())
            item.setData(Qt.UserRole, outil)
            self.w_list.addItem(item)
        self.w_list.setCurrentRow(min(max(0, garde),
                                      self.w_list.count() - 1))

