"""Import et export des réglages / Settings import and export.

Ce que l'atelier accumule ne vit **pas** dans le dossier du programme.
Les process, les couples, les dossiers, les préréglages de code : tout est
ailleurs — dans la base de registre de l'utilisateur et dans son dossier
de réglages. C'est ce qui fait qu'une **mise à jour ne perd rien** : on
remplace `TauDrive`, et l'atelier retrouve son travail.

Mais cela ne suffit pas dans trois cas, et ce sont ceux qui arrivent :

* le poste de production change de **compte Windows**, ou de machine ;
* on veut porter les process d'un poste sur un autre ;
* on veut **une sauvegarde**, parce qu'un disque finit toujours par
  tomber.

D'où ce module. Il range tout dans **un fichier** — un ZIP nommé
`.taudrive-reglages` — qu'on relit ailleurs en choisissant ce qu'on
reprend.

**Rien n'est importé sans qu'on le demande.** L'archive est d'abord
*inspectée* : on voit ce qu'elle contient, on coche, et alors seulement
on remplace. Un import qui écraserait la bibliothèque du poste sans
prévenir serait exactement la perte qu'on cherche à éviter.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import zipfile

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QLabel, QLineEdit, QTextBrowser,
                               QVBoxLayout)

from . import recipes, session
from . import theme

#: Extension du fichier d'échange.
SUFFIX = '.taudrive-reglages'

#: Filtre de sélecteur de fichiers.
FILE_FILTER = f'Réglages TauDrive (*{SUFFIX});;Archive ZIP (*.zip);;Tous (*)'

#: Version du format. Une archive plus récente est refusée plutôt que mal
#: lue : mieux vaut dire « je ne sais pas » que reconstruire de travers.
FORMAT = 1

#: Noms des membres de l'archive.
M_META = 'reglages.json'
M_RECIPES = 'recettes.json'
M_GABARITS = 'montages.json'
#: Préréglages de code. Ils vivaient dans leur propre fichier, à côté
#: des process, et l'archive les oubliait : un poste repris d'une
#: sauvegarde retrouvait ses process et perdait ses plaques.
M_CODES = 'codes.json'
M_DRAWINGS = 'bibliotheque/'

#: Clés de registre **jamais** reprises telles quelles.
#:
#: La géométrie de fenêtre appartient à l'écran qui l'a vue : la rejouer
#: sur un poste à un seul moniteur place la fenêtre hors champ, sans
#: aucun moyen de la récupérer. Les documents récents et la session
#: ouverte désignent des fichiers qui n'existent pas sur l'autre poste.
VOLATILE = ('window/geometry', 'window/state', 'session/open',
            'session/closed', 'recent/documents')

#: Clés qui portent des **chemins absolus**.
#:
#: Elles se reprennent, mais elles méritent d'être annoncées : un dossier
#: d'export qui pointe sur le partage d'un autre atelier ne se voit pas,
#: il se découvre au premier export.
PATHS = ('folders/', 'recent/exports', 'recent/folders/', 'exports/')


class SettingsError(RuntimeError):
    """Archive illisible, ou d'une version qu'on ne sait pas relire."""


def _is_path_key(cle: str) -> bool:
    return any(cle.startswith(p) for p in PATHS)


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def collect(include_volatile: bool = False) -> dict:
    """Les réglages du poste, prêts à être rangés.

    Les clés volatiles — géométrie de fenêtre, documents récents — sont
    laissées de côté par défaut : elles ne veulent rien dire ailleurs.
    """
    s = session.settings()
    valeurs: dict = {}
    for cle in s.allKeys():
        if not include_volatile and cle in VOLATILE:
            continue
        brut = s.value(cle)
        if isinstance(brut, (bytes, bytearray)):
            continue                    # géométries binaires : sans objet
        try:
            json.dumps(brut)
        except (TypeError, ValueError):
            brut = str(brut)
        valeurs[cle] = brut
    return valeurs


def export(path: str | pathlib.Path, *, with_drawings: bool = False,
           include_volatile: bool = False, note: str = '') -> dict:
    """Écrit l'archive. Rend un compte rendu de ce qui y est entré."""
    cible = pathlib.Path(path)
    if not cible.suffix:
        cible = cible.with_suffix(SUFFIX)

    reglages = collect(include_volatile)
    process = recipes.load_local()
    from . import codepresets
    codes = codepresets.load()
    compte = {'reglages': len(reglages), 'process': len(process),
              'codes': len(codes), 'dessins': 0, 'octets': 0,
              'chemin': str(cible)}

    meta = {
        'format': FORMAT,
        'ecrit': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'poste': _hostname(),
        'note': str(note or ''),
        'reglages': reglages,
    }
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(cible, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(M_META, json.dumps(meta, indent=2,
                                          ensure_ascii=False))
            z.writestr(M_RECIPES, json.dumps(
                {'recipes': [recipes.recipe_to_dict(r) for r in process]},
                indent=2, ensure_ascii=False))
            # Les gabarits de montage suivent les process : ce sont des
            # cotes d'atelier, et un poste qui reçoit les uns sans les
            # autres poserait ses montages de travers.
            from . import gabarits
            z.writestr(M_GABARITS, json.dumps(
                {'montages': gabarits.charger()},
                indent=2, ensure_ascii=False))
            z.writestr(M_CODES, json.dumps(
                {'presets': codes}, indent=2, ensure_ascii=False))
            if with_drawings:
                compte['dessins'] = _add_drawings(z)
    except OSError as exc:
        raise SettingsError(f'écriture impossible : {exc}') from None
    compte['octets'] = cible.stat().st_size
    return compte


def _add_drawings(z: zipfile.ZipFile) -> int:
    """Range la bibliothèque de dessins du poste. Rend le nombre de fichiers.

    Les dessins **livrés** avec TauDrive n'y entrent pas : ils arrivent
    avec le programme, et les embarquer doublerait l'archive pour rien.
    """
    from . import drawings
    racine = drawings.user_dir()
    combien = 0
    for entry in drawings.entries():
        if entry.delivered:
            continue
        try:
            relatif = entry.path.relative_to(racine)
        except ValueError:
            continue
        try:
            z.write(entry.path, M_DRAWINGS + relatif.as_posix())
            combien += 1
        except OSError:
            continue
    return combien


def _hostname() -> str:
    import socket
    try:
        return socket.gethostname()
    except OSError:
        return ''


# --------------------------------------------------------------------------
# Inspection, puis import
# --------------------------------------------------------------------------

def inspect(path: str | pathlib.Path) -> dict:
    """Ce que l'archive contient, **sans rien changer**.

    C'est l'étape qui manque à la plupart des imports : on voit d'abord,
    on décide ensuite.
    """
    try:
        with zipfile.ZipFile(path) as z:
            noms = z.namelist()
            if M_META not in noms:
                raise SettingsError(
                    'ce fichier n\'est pas une archive de réglages '
                    'TauDrive.')
            meta = json.loads(z.read(M_META).decode('utf-8'))
            process = []
            if M_RECIPES in noms:
                brut = json.loads(z.read(M_RECIPES).decode('utf-8'))
                process = brut.get('recipes', []) or []
            codes = []
            if M_CODES in noms:
                brut = json.loads(z.read(M_CODES).decode('utf-8'))
                codes = [c for c in brut.get('presets', []) or []
                         if isinstance(c, dict) and c.get('name')]
            dessins = [n for n in noms
                       if n.startswith(M_DRAWINGS) and not n.endswith('/')]
    except SettingsError:
        raise
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise SettingsError(f'archive illisible : {exc}') from None

    version = int(meta.get('format', 0) or 0)
    if version > FORMAT:
        raise SettingsError(
            f'archive écrite par une version plus récente de TauDrive '
            f'(format {version}, connu jusqu\'à {FORMAT}).')

    reglages = meta.get('reglages', {}) or {}
    return {
        'format': version,
        'ecrit': meta.get('ecrit', ''),
        'poste': meta.get('poste', ''),
        'note': meta.get('note', ''),
        'reglages': reglages,
        'nb_reglages': len(reglages),
        'nb_process': len(process),
        'noms_process': [r.get('name', '?') for r in process],
        'nb_codes': len(codes),
        'noms_codes': [c.get('name', '?') for c in codes],
        'nb_dessins': len(dessins),
        'chemins': sorted(c for c in reglages if _is_path_key(c)),
    }


#: Comment reprendre les process d'une archive.
#:
#: * `replace` — celles de l'archive **remplacent** celles du poste de
#:   même nom, les autres s'ajoutent. C'est ce qu'on attend d'un import :
#:   on reprend le poste de production, ses valeurs comptent ;
#: * `add` — seules les process **nouvelles** entrent, le poste garde
#:   les siennes ;
#: * `all` — la bibliothèque du poste est **remplacée** par celle de
#:   l'archive.
PROCESS_MODES = (
    ('replace', 'reprendre : remplacent celles de même nom, les autres '
                's\'ajoutent'),
    ('add', 'ajouter seulement les nouvelles, garder celles du poste'),
    ('all', 'remplacer toute la bibliothèque par celle de l\'archive'),
)


def apply(path: str | pathlib.Path, *, settings: bool = True,
          process: bool = True, drawings_too: bool = False,
          paths: bool = False, merge_process: bool | None = None,
          process_mode: str = 'replace') -> dict:
    """Reprend ce qui est demandé. Rend le compte rendu de ce qui a bougé.

    `process_mode` dit comment les process entrent — voir
    `PROCESS_MODES`. `merge_process` est l'ancien réglage : `True` vaut
    `add`, `False` vaut `all`.

    `paths` reprend les dossiers absolus, qui ne veulent souvent rien dire
    sur un autre poste : laissé à `False`, on garde ceux du poste.

    Ce qui est écrit est aussi **installé en mémoire** : la liste des
    process de la colonne 1 et le gestionnaire doivent voir l'import
    tout de suite. Écrire le fichier seul laissait l'ancienne
    bibliothèque à l'écran, et un *Enregistrer* qui suivait la remettait
    par-dessus l'import.
    """
    if merge_process is not None:
        process_mode = 'add' if merge_process else 'all'
    if process_mode not in {m for m, _ in PROCESS_MODES}:
        raise ValueError(f'mode inconnu : {process_mode!r}')
    vu = inspect(path)
    compte = {'reglages': 0, 'process': 0, 'codes': 0, 'dessins': 0,
              'ignores': [], 'remplacees': 0}

    if settings:
        s = session.settings()
        for cle, valeur in (vu['reglages'] or {}).items():
            if cle in VOLATILE:
                continue
            if _is_path_key(cle) and not paths:
                compte['ignores'].append(cle)
                continue
            s.setValue(cle, valeur)
            compte['reglages'] += 1
        s.sync()

    if process and vu['nb_process']:
        with zipfile.ZipFile(path) as z:
            brut = json.loads(z.read(M_RECIPES).decode('utf-8'))
        venues = [recipes.recipe_from_dict(r)
                  for r in brut.get('recipes', []) if isinstance(r, dict)]
        connues = recipes.load_local()
        noms = {r.name for r in connues}
        if process_mode == 'add':
            neuves = [r for r in venues if r.name not in noms]
            resultat = connues + neuves
            compte['process'] = len(neuves)
        elif process_mode == 'all':
            resultat = venues
            compte['process'] = len(venues)
        else:
            from . import echange
            resultat = echange.fusionner(connues, venues, lambda r: r.name)
            compte['process'] = len(venues)
            compte['remplacees'] = sum(1 for r in venues if r.name in noms)
        if resultat:
            recipes.save_local(resultat)
            recipes.set_recipe_library(resultat)

    if process:
        # Les gabarits arrivent avec les process, et **remplacent** ceux
        # du poste : ce sont les cotes d'une mécanique, pas une
        # préférence à fusionner. Deux montages du même nom aux cotes
        # différentes seraient le pire des deux mondes.
        try:
            with zipfile.ZipFile(path) as z:
                if M_GABARITS in z.namelist():
                    brut = json.loads(z.read(M_GABARITS).decode('utf-8'))
                    from . import gabarits
                    venus = [g for g in brut.get('montages', [])
                             if isinstance(g, dict)]
                    if venus:
                        # remplacer sciemment : un fichier du poste devenu
                        # illisible est mis de côté, pas un obstacle
                        gabarits.enregistrer(venus, remplace_illisible=True)
                        compte['gabarits'] = len(venus)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            from .avale import avale
            avale('réglages : gabarits non repris', exc)

    if process and vu.get('nb_codes'):
        # les préréglages de code suivent les process, avec la même
        # règle de fusion : ce sont des réglages de plaque, pas des cotes
        # de mécanique
        try:
            with zipfile.ZipFile(path) as z:
                brut = json.loads(z.read(M_CODES).decode('utf-8'))
            from . import codepresets, echange
            venus = [c for c in brut.get('presets', [])
                     if isinstance(c, dict) and c.get('name')]
            connus = codepresets.load()
            noms = {c['name'] for c in connus}
            if process_mode == 'add':
                neufs = [c for c in venus if c['name'] not in noms]
                resultat = echange.fusionner(connus, neufs,
                                             lambda c: c['name'])
                compte['codes'] = len(neufs)
            elif process_mode == 'all':
                resultat = venus
                compte['codes'] = len(venus)
            else:
                resultat = echange.fusionner(connus, venus,
                                             lambda c: c['name'])
                compte['codes'] = len(venus)
            if resultat:
                codepresets.save(resultat)
                codepresets.set_library(resultat)
        except (OSError, ValueError, KeyError) as exc:
            from .avale import avale
            avale('réglages : préréglages de code non repris', exc)

    if drawings_too and vu['nb_dessins']:
        compte['dessins'] = _extract_drawings(path)
    return compte


def _extract_drawings(path: str | pathlib.Path) -> int:
    """Pose les dessins de l'archive dans la bibliothèque du poste.

    Un dessin de même nom **n'est pas écrasé** : il reçoit un rang, comme
    à l'ajout ordinaire. Reprendre une archive ne doit pas effacer ce que
    le poste avait déjà.
    """
    from . import drawings
    racine = drawings.user_dir()
    racine.mkdir(parents=True, exist_ok=True)
    combien = 0
    with zipfile.ZipFile(path) as z:
        for nom in z.namelist():
            if not nom.startswith(M_DRAWINGS) or nom.endswith('/'):
                continue
            relatif = drawings.clean_folder(
                str(pathlib.PurePosixPath(nom[len(M_DRAWINGS):]).parent))
            feuille = pathlib.PurePosixPath(nom).name
            dossier = racine / relatif if relatif else racine
            try:
                dossier.mkdir(parents=True, exist_ok=True)
                cible = drawings._free_name(dossier / feuille)
                cible.write_bytes(z.read(nom))
                combien += 1
            except OSError:
                continue
    return combien


# --------------------------------------------------------------------------
# Ce qui vit où — pour l'aide et pour la mise à jour
# --------------------------------------------------------------------------

def locations() -> list[tuple[str, str, bool]]:
    """Où l'état du poste est rangé. `(quoi, où, dans le programme ?)`.

    Aucun de ces emplacements n'est **dans** le dossier du programme :
    c'est ce qui fait qu'une mise à jour ne perd rien.
    """
    from . import drawings, thumbs
    return [
        ('Bibliothèque de process', str(recipes.library_path()), False),
        ('Réglages du poste', session.settings().fileName(), False),
        ('Dessins du poste', str(drawings.user_dir()), False),
        ('Vignettes', str(thumbs.cache_dir()), False),
        ('Onglets fermés', str(session.archive_dir()), False),
        ('Programme', 'dossier TauDrive copié sur le poste', True),
    ]


# --------------------------------------------------------------------------
# Dialogues
# --------------------------------------------------------------------------

def _escape(texte: str) -> str:
    return (str(texte).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


class ExportDialog(QDialog):
    """Ce qu\'on emporte, et ce qu\'on laisse."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Exporter les réglages')
        self.setMinimumWidth(500)

        dehors = QVBoxLayout(self)
        dehors.addWidget(QLabel(
            'Range dans <b>un fichier</b> la bibliothèque de process et '
            'les réglages du poste.<br>'
            f'{theme.span()}À reprendre sur un autre poste, '
            'un autre compte Windows, ou après un disque tombé.</span>'))

        self.w_note = QLineEdit()
        self.w_note.setPlaceholderText(
            'note libre — « poste production, avant mise à jour »')
        dehors.addWidget(self.w_note)

        self.w_drawings = QCheckBox(
            'Emporter aussi les dessins du poste')
        self.w_drawings.setToolTip(
            'Les dessins livrés avec TauDrive ne sont pas emportés : ils '
            'arrivent avec le programme.\n'
            'Une bibliothèque d\'atelier peut peser plusieurs dizaines '
            'de mégaoctets.')
        dehors.addWidget(self.w_drawings)

        self.w_volatile = QCheckBox(
            'Emporter aussi la disposition des fenêtres et les récents')
        self.w_volatile.setToolTip(
            'Rarement utile : une géométrie de fenêtre appartient à '
            'l\'écran qui l\'a vue,\net les documents récents '
            'désignent des fichiers qui n\'existent pas ailleurs.')
        dehors.addWidget(self.w_volatile)

        self.w_note_bas = QLabel('')
        self.w_note_bas.setWordWrap(True)
        self.w_note_bas.setStyleSheet(theme.css())
        dehors.addWidget(self.w_note_bas)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText(
            'Choisir le fichier…')
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        dehors.addWidget(boutons)
        self._describe()

    def _describe(self) -> None:
        try:
            combien = len(recipes.load_local())
            reglages = len(collect(self.w_volatile.isChecked()))
        except Exception:
            return
        from . import codepresets
        self.w_note_bas.setText(
            f'{combien} process · {len(codepresets.load())} préréglages '
            f'de code · {reglages} réglages du poste')

    def choice(self) -> dict:
        return {'with_drawings': self.w_drawings.isChecked(),
                'include_volatile': self.w_volatile.isChecked(),
                'note': self.w_note.text().strip()}


class ImportDialog(QDialog):
    """**On voit d\'abord, on décide ensuite.**

    Un import qui écraserait la bibliothèque du poste sans prévenir
    serait exactement la perte qu\'on cherche à éviter. L\'archive
    est donc inspectée et montrée avant qu\'une seule valeur ne bouge.
    """

    def __init__(self, parent, path) -> None:
        super().__init__(parent)
        self.setWindowTitle('Importer des réglages')
        self.setMinimumSize(560, 480)
        self.path = path
        self.vu = inspect(path)

        dehors = QVBoxLayout(self)
        dehors.addWidget(QLabel(
            f'<b>{_escape(pathlib.Path(path).name)}</b>'))

        vue = QTextBrowser()
        vue.setHtml(self._resume())
        dehors.addWidget(vue, 1)

        self.w_process = QCheckBox(
            f'Reprendre les {self.vu["nb_process"]} process'
            + (f' et {self.vu["nb_codes"]} préréglages de code'
               if self.vu.get('nb_codes') else ''))
        self.w_process.setChecked(bool(self.vu['nb_process']
                                       or self.vu.get('nb_codes')))
        # Trois façons d'entrer, et non une case « sans écraser » : on
        # importe le plus souvent pour **reprendre** le poste de
        # production, et ses valeurs doivent l'emporter sur celles de
        # même nom. Garder les siennes reste possible, mais se choisit.
        from .widgets import Combo
        self.w_mode = Combo()
        for cle, libelle in PROCESS_MODES:
            self.w_mode.addItem(libelle, cle)
        self.w_mode.setToolTip(
            'Comment les process de l\'archive entrent dans la '
            'bibliothèque du poste.\nLes noms déjà pris sont signalés '
            'ci-dessus.')
        self.w_settings = QCheckBox(
            f'Reprendre les {self.vu["nb_reglages"]} réglages du poste')
        self.w_settings.setChecked(True)
        self.w_paths = QCheckBox(
            'Reprendre aussi les dossiers (export, dessins, DXF)')
        self.w_paths.setToolTip(
            'Ces chemins sont absolus : ils ne veulent souvent rien dire '
            'sur un autre poste.')
        self.w_drawings = QCheckBox(
            f'Reprendre les {self.vu["nb_dessins"]} dessins')
        self.w_drawings.setEnabled(bool(self.vu['nb_dessins']))
        for case in (self.w_process, self.w_mode, self.w_settings,
                     self.w_paths, self.w_drawings):
            dehors.addWidget(case)
        self.w_process.toggled.connect(self.w_mode.setEnabled)
        self.w_mode.setEnabled(self.w_process.isChecked())

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText(
            'Reprendre')
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        dehors.addWidget(boutons)

    def _resume(self) -> str:
        v = self.vu
        lignes = ['<style>td{padding:2px 12px 2px 0}</style><table>',
                  f'<tr><td>Écrite le</td><td><b>{_escape(v["ecrit"])}'
                  f'</b></td></tr>',
                  f'<tr><td>Poste</td><td><b>{_escape(v["poste"])}</b>'
                  f'</td></tr>']
        if v['note']:
            lignes.append(f'<tr><td>Note</td><td>{_escape(v["note"])}'
                          f'</td></tr>')
        lignes.append('</table>')
        if v['noms_process']:
            # les noms déjà pris sur le poste : ce que « reprendre »
            # remplacerait, à voir avant de choisir le mode
            try:
                pris = {r.name for r in recipes.load_local()}
            except Exception:
                pris = set()
            communs = sum(1 for n in v['noms_process'] if n in pris)
            lignes.append(f'<p><b>{v["nb_process"]} process</b>'
                          + (f' — {communs} de même nom que sur ce poste'
                             if communs else ' — aucune de même nom que '
                             'sur ce poste') + '</p><ul>')
            for nom in v['noms_process'][:40]:
                note = (f' {theme.span("warn")}— même nom sur ce poste'
                        '</span>' if nom in pris else '')
                lignes.append(f'<li>{_escape(nom)}{note}</li>')
            if v['nb_process'] > 40:
                lignes.append(f'<li>… et {v["nb_process"] - 40} autres</li>')
            lignes.append('</ul>')
        if v.get('noms_codes'):
            lignes.append(f'<p><b>{v["nb_codes"]} préréglages de code'
                          '</b></p><ul>')
            for nom in v['noms_codes'][:20]:
                lignes.append(f'<li>{_escape(nom)}</li>')
            lignes.append('</ul>')
        if v['chemins']:
            lignes.append('<p><b>Dossiers du poste d\'origine</b> — '
                          'repris seulement si on le demande</p><ul>')
            for cle in v['chemins']:
                valeur = v['reglages'].get(cle, '')
                lignes.append(f'<li>{_escape(cle)} : '
                              f'{_escape(str(valeur)[:90])}</li>')
            lignes.append('</ul>')
        if v['nb_dessins']:
            lignes.append(f'<p><b>{v["nb_dessins"]} dessins</b> de la '
                          f'bibliothèque du poste</p>')
        return chr(10).join(lignes)

    def choice(self) -> dict:
        return {'settings': self.w_settings.isChecked(),
                'process': self.w_process.isChecked(),
                'process_mode': self.w_mode.currentData() or 'replace',
                'paths': self.w_paths.isChecked(),
                'drawings_too': self.w_drawings.isChecked()}
