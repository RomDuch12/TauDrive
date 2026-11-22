"""Conversion d'un dessin vectoriel d'un format à l'autre, sans fenêtre.

Le même moteur sert à trois entrées : le menu *Fichier ▸ Exporter*, la
ligne de commande, et le clic droit de l'explorateur Windows (voir
`shellmenu`). Il n'y a qu'un lecteur et qu'un écrivain, et c'est
volontaire : une conversion faite depuis l'explorateur doit rendre
exactement le fichier qu'aurait rendu l'application ouverte.

    TauDrive.exe --convert dessin.ai --to dxf
    TauDrive.exe --convert a.svg b.cdr c.eps --to dxf --dossier D:/sortie

Entrées : DXF, PDF, AI, EPS, PS, SVG, CDR.
Sorties : DXF, AI, EPS, SVG.

`.cdr` et les `.ai` récents passent par Inkscape ou LibreOffice ; sans
eux la conversion échoue en le disant, plutôt que de rendre un fichier
vide.
"""
from __future__ import annotations

import pathlib
import sys
from .avale import avale

#: Ce qu'on sait relire.
SOURCES = ('.dxf', '.pdf', '.ai', '.eps', '.ps', '.svg', '.cdr')

#: Ce qu'on sait écrire, avec le libellé du menu contextuel.
TARGETS = (
    ('dxf', 'DXF'),
    ('ai', 'Illustrator'),
    ('svg', 'SVG'),
    ('eps', 'PostScript'),
    ('pdf', 'PDF'),
)


class ConvertError(RuntimeError):
    """La conversion n'a pas abouti."""


def free_path(cible: pathlib.Path) -> pathlib.Path:
    """Un chemin libre voisin de `cible`.

    On n'écrase jamais un fichier existant depuis le clic droit :
    l'utilisateur n'a pas vu de sélecteur de fichiers, donc il n'a rien
    confirmé. Un `dessin (2).dxf` se remarque et se supprime ; un dessin
    écrasé ne se récupère pas.
    """
    if not cible.exists():
        return cible
    for n in range(2, 1000):
        essai = cible.with_name(f'{cible.stem} ({n}){cible.suffix}')
        if not essai.exists():
            return essai
    raise ConvertError(f'trop de fichiers du même nom : {cible.name}')


def convert(source, kind: str = 'dxf', *, dossier=None,
            tolerance_mm: float = 0.02, toolpaths: bool = False) -> pathlib.Path:
    """Convertit `source` vers `kind`. Rend le chemin écrit.

    Le fichier sort à côté de la source, ou dans `dossier` s'il est
    donné.
    """
    from . import dxfimport, vecexport
    from .model import Document

    source = pathlib.Path(source)
    kind = str(kind or 'dxf').lower().lstrip('.')
    if kind not in {k for k, _ in TARGETS}:
        raise ConvertError(f'format de sortie inconnu : {kind}')
    if not source.is_file():
        raise ConvertError(f'introuvable : {source}')
    if source.suffix.lower() not in SOURCES:
        raise ConvertError(f'format d entrée non pris en charge : '
                           f'{source.suffix or "sans suffixe"}')

    try:
        formes, rapport = dxfimport.any_to_shapes(str(source),
                                                  tolerance_mm=tolerance_mm)
    except dxfimport.DxfError as exc:
        # le lecteur a déjà dit pourquoi, et souvent quoi faire : le
        # préfixer une seconde fois donnerait « lecture impossible :
        # lecture impossible : … »
        raise ConvertError(str(exc)) from None
    except Exception as exc:
        raise ConvertError(f'lecture impossible : {exc}') from None
    if not formes:
        raise ConvertError('le fichier ne contient aucun tracé exploitable.')

    document = Document()
    document.name = source.stem
    for forme in formes:
        document.add(forme)

    destination = pathlib.Path(dossier) if dossier else source.parent
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConvertError(f'dossier de sortie inaccessible : {exc}') from None

    cible = free_path(destination / f'{source.stem}.{kind}')
    try:
        vecexport.export(document, cible, kind=kind, toolpaths=toolpaths)
    except Exception as exc:
        raise ConvertError(f'écriture impossible : {exc}') from None
    return cible


def summary(source, cible, rapport=None) -> str:
    """Une ligne de compte rendu, pour la console ou une bulle."""
    source, cible = pathlib.Path(source), pathlib.Path(cible)
    taille = cible.stat().st_size if cible.exists() else 0
    return f'{source.name} -> {cible.name} ({taille // 1024 or 1} ko)'


# --------------------------------------------------------------------------
# Ligne de commande
# --------------------------------------------------------------------------

def run(argv=None) -> int:
    """Traite `--convert`. Rend un code de sortie.

    Une erreur sur un fichier n'arrête pas les autres : quand on
    convertit une sélection de trente dessins, s'interrompre au premier
    fichier abîmé oblige à tout recommencer.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    fichiers: list[str] = []
    kind = 'dxf'
    dossier = None
    silencieux = '--silencieux' in argv or '--quiet' in argv

    i = 0
    lecture = False
    while i < len(argv):
        mot = argv[i]
        if mot == '--convert':
            lecture = True
        elif mot == '--to':
            i += 1
            kind = argv[i] if i < len(argv) else 'dxf'
            lecture = False
        elif mot == '--dossier':
            i += 1
            dossier = argv[i] if i < len(argv) else None
            lecture = False
        elif mot.startswith('--'):
            lecture = False
        elif lecture:
            fichiers.append(mot)
        i += 1

    if not fichiers:
        _dire('Aucun fichier à convertir.', silencieux, True)
        return 2

    ecrits, ratés = [], []
    for chemin in fichiers:
        try:
            cible = convert(chemin, kind, dossier=dossier)
        except ConvertError as exc:
            ratés.append((chemin, str(exc)))
        except Exception as exc:                       # noqa: BLE001
            ratés.append((chemin, f'erreur inattendue : {exc}'))
        else:
            ecrits.append(cible)
            print(summary(chemin, cible))

    if ratés:
        detail = chr(10).join(f'{pathlib.Path(f).name} : {m}'
                              for f, m in ratés)
        _dire(f'{len(ratés)} fichier(s) non converti(s) :{chr(10)}{detail}',
              silencieux, True)
    elif ecrits and not silencieux and len(ecrits) > 1:
        _dire(f'{len(ecrits)} fichier(s) convertis en {kind.upper()}.',
              silencieux, False)
    return 1 if ratés else 0


def _dire(message: str, silencieux: bool, erreur: bool) -> None:
    """Dit quelque chose, à l'écran si possible.

    Lancé depuis l'explorateur, le programme n'a pas de console : un
    message sur `stderr` n'irait nulle part, et l'utilisateur croirait
    que le clic droit n'a rien fait.
    """
    print(message, file=sys.stderr if erreur else sys.stdout)
    if silencieux:
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is None:
            return
        boite = QMessageBox.warning if erreur else QMessageBox.information
        boite(None, 'TauDrive', message)
    except Exception as exc:                           # noqa: BLE001
        avale('conversion : message non montré', exc)
