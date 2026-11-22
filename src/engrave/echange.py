"""Échange de préréglages entre postes / Preset exchange.

Deux bibliothèques se règlent sur un poste et servent sur l'autre : les
**process** — puissance, vitesse, passes, remplissage — et les
**préréglages de code** — symbologie, fenêtre, cadre, texte. L'archive
complète de *Paramètres ▸ Exporter les réglages* les emporte avec tout
le reste ; c'est la sauvegarde. Mais porter trois process de laiton sur
le poste de production n'a pas besoin d'une sauvegarde : il faut **un
fichier par bibliothèque**, lisible, qu'on pose sur une clé et qu'on
relit en face.

C'est ce que fait ce module. Le fichier est le JSON de la bibliothèque
elle-même — le même que `recettes.json` ou `codes.json` sur le poste —
avec la date et le nom du poste qui l'a écrit. Il se relit donc à la
main en cas de doute, et un fichier écrit par une version antérieure
reste lisible.

**Rien n'entre sans qu'on l'ait vu.** À l'import, chaque entrée est
présentée, cochée, avec ce qu'elle remplacerait sur le poste. Une
process de même nom **remplace** la vôtre si vous la laissez cochée : on
importe pour reprendre le réglage de l'autre poste, pas pour garder le
sien ; mais on le voit avant, et on décoche.
"""
from __future__ import annotations

import datetime
import json
import pathlib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QListWidget, QListWidgetItem, QVBoxLayout)

from . import theme

#: Extensions. Un suffixe composé, pour que le sélecteur de fichiers ne
#: propose pas n'importe quel `.json`.
SUFFIX_PROCESS = '.process.json'
SUFFIX_CODES = '.codes.json'
FILTRE_PROCESS = ('Process TauDrive (*.process.json);;JSON (*.json);;'
                  'Tous (*)')
FILTRE_CODES = ('Préréglages de code TauDrive (*.codes.json);;'
                'JSON (*.json);;Tous (*)')


class EchangeError(RuntimeError):
    """Fichier illisible, ou qui ne contient pas ce qu'on attendait."""


def poste() -> str:
    """Nom du poste, pour signer le fichier — vide si Windows ne le dit pas."""
    import socket
    try:
        return socket.gethostname()
    except OSError:
        return ''


def _entete() -> dict:
    return {'ecrit': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'poste': poste(), 'programme': 'TauDrive'}


def _ecrire(path, contenu: dict, suffixe: str) -> pathlib.Path:
    cible = pathlib.Path(path)
    if not str(cible).lower().endswith(suffixe):
        cible = cible.with_name(cible.name + suffixe) if not cible.suffix \
            else cible.with_suffix('').with_name(cible.stem + suffixe)
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(json.dumps(contenu, indent=2, ensure_ascii=False),
                         encoding='utf-8')
    except OSError as exc:
        raise EchangeError(f'écriture impossible : {exc}') from None
    return cible


def _lire(path, cle: str, quoi: str) -> tuple[list[dict], dict]:
    """Les entrées sous `cle`, et l'en-tête. Refuse ce qui n'est pas ça."""
    try:
        brut = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except OSError as exc:
        raise EchangeError(f'lecture impossible : {exc}') from None
    except ValueError as exc:
        raise EchangeError(f'ce fichier n\'est pas du JSON : {exc}') from None
    if isinstance(brut, list):
        entrees, entete = brut, {}
    elif isinstance(brut, dict) and cle in brut:
        entrees, entete = brut.get(cle) or [], brut
    else:
        autre = {'recipes': 'des process', 'presets': 'des préréglages '
                 'de code'}
        trouve = next((autre[k] for k in autre if isinstance(brut, dict)
                       and k in brut), None)
        if trouve:
            raise EchangeError(
                f'ce fichier contient {trouve}, pas {quoi}.')
        raise EchangeError(f'ce fichier ne contient pas {quoi}.')
    return [e for e in entrees if isinstance(e, dict)], entete


# --------------------------------------------------------------------------
# Process
# --------------------------------------------------------------------------

def ecrire_process(path, recipes) -> pathlib.Path:
    """Écrit des process dans un fichier d'échange. Rend le chemin."""
    from .model import recipe_to_dict
    contenu = _entete()
    contenu['recipes'] = [recipe_to_dict(r) for r in recipes]
    return _ecrire(path, contenu, SUFFIX_PROCESS)


def lire_process(path) -> tuple[list, dict]:
    """Les process d'un fichier d'échange, et son en-tête."""
    from .model import recipe_from_dict
    entrees, entete = _lire(path, 'recipes', 'des process')
    return [recipe_from_dict(e) for e in entrees], entete


# --------------------------------------------------------------------------
# Préréglages de code
# --------------------------------------------------------------------------

def ecrire_codes(path, presets: list[dict]) -> pathlib.Path:
    contenu = _entete()
    contenu['presets'] = [dict(p) for p in presets if p.get('name')]
    return _ecrire(path, contenu, SUFFIX_CODES)


def lire_codes(path) -> tuple[list[dict], dict]:
    entrees, entete = _lire(path, 'presets', 'des préréglages de code')
    return [e for e in entrees if e.get('name')], entete


def genre(path) -> str:
    """Ce qu'un fichier JSON contient : `process`, `codes`, `montages`,
    ou `''` si ce n'est rien de connu — sans lever."""
    try:
        brut = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    if isinstance(brut, dict):
        if 'recipes' in brut:
            return 'process'
        if 'presets' in brut:
            return 'codes'
        if 'montages' in brut:
            return 'montages'
    return ''


# --------------------------------------------------------------------------
# Fusion
# --------------------------------------------------------------------------

def fusionner(existants: list, venus: list, nom) -> list:
    """`existants` où chaque venu **remplace** l'entrée de même nom, ou
    s'ajoute à la fin. L'ordre du poste est conservé."""
    resultat = list(existants)
    rangs = {nom(e): i for i, e in enumerate(resultat)}
    for venu in venus:
        cle = nom(venu)
        if cle in rangs:
            resultat[rangs[cle]] = venu
        else:
            rangs[cle] = len(resultat)
            resultat.append(venu)
    return resultat


class ChoixImport(QDialog):
    """Ce que le fichier contient, entrée par entrée, à cocher.

    Chaque ligne dit si l'entrée **remplace** une entrée du poste de
    même nom. Tout est coché : on importe pour reprendre ; mais on
    décoche ce qu'on tient à garder.
    """

    def __init__(self, parent, titre: str, entete: dict,
                 entrees: list, nom, deja: set) -> None:
        super().__init__(parent)
        self.setWindowTitle(titre)
        self.setMinimumSize(460, 380)
        self._entrees = entrees
        self._nom = nom

        dehors = QVBoxLayout(self)
        origine = []
        if entete.get('poste'):
            origine.append(f'poste <b>{entete["poste"]}</b>')
        if entete.get('ecrit'):
            origine.append(f'écrit le {entete["ecrit"]}')
        dehors.addWidget(QLabel(
            f'<b>{len(entrees)} entrée(s)</b>'
            + (' — ' + ', '.join(origine) if origine else '')))

        self.w_liste = QListWidget()
        remplace = 0
        for entree in entrees:
            cle = nom(entree)
            item = QListWidgetItem(cle)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            if cle in deja:
                remplace += 1
                item.setText(f'{cle}   — remplace celle du poste')
                item.setForeground(QColor(theme.hex_of('warn')))
            self.w_liste.addItem(item)
        dehors.addWidget(self.w_liste, 1)

        note = QLabel(
            f'{theme.span()}{remplace} remplacerai(en)t une entrée de '
            'même nom sur ce poste ; les autres s\'ajoutent. Décochez ce '
            'que vous voulez garder.</span>' if remplace else
            f'{theme.span()}Aucun nom en commun avec le poste : tout '
            's\'ajoute.</span>')
        note.setWordWrap(True)
        dehors.addWidget(note)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText(
            'Reprendre')
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        dehors.addWidget(boutons)

    def retenues(self) -> list:
        """Les entrées laissées cochées."""
        return [e for i, e in enumerate(self._entrees)
                if self.w_liste.item(i).checkState() == Qt.Checked]
