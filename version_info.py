# -*- coding: utf-8 -*-
"""Propriétés Windows des exécutables / Windows version resource.

Ce que Windows lit dans *Propriétés ▸ Détails* d'un `.exe`, et ce que
l'explorateur, le Gestionnaire des tâches et SmartScreen affichent.

**Pourquoi c'est utile.** Un exécutable sans ces champs est anonyme : le
Gestionnaire des tâches n'affiche qu'un nom de fichier, et SmartScreen
n'a rien à montrer sinon « éditeur inconnu ». Les remplir ne signe pas
le programme — cela reste un fichier non signé, voir `reference/
signature-windows.md` — mais cela donne à l'utilisateur de quoi savoir
ce qu'il ouvre et à qui écrire.

C'est aussi là que la paternité s'inscrit **discrètement** : dans les
propriétés du fichier, pas dans une bannière au démarrage.

Le fichier est lu par PyInstaller (`version=` dans les `EXE`). Il n'est
jamais importé par l'application.
"""

AUTEUR = 'romduch@gmail.com'
CONTACT = 'romduch@gmail.com'
PRODUIT = 'TauDrive'
# lue dans le code (`src/engrave/__init__.py`), comme l'application et les archives
import pathlib as _pl, re as _re  # noqa: E401,E402
VERSION = tuple(int(n) for n in _re.search(
    r"__version__ = '(\d+)\.(\d+)\.(\d+)'",
    (_pl.Path(__file__).parent / 'src' / 'engrave' / '__init__.py').read_text(
        encoding='utf-8')).groups()) + (0,)
ANNEE = 2026


def _texte(nom_fichier: str, description: str) -> str:
    """Le bloc `VSVersionInfo` d'un exécutable, en texte PyInstaller."""
    v = ', '.join(str(n) for n in VERSION)
    lisible = '.'.join(str(n) for n in VERSION[:3])
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v}), prodvers=({v}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040C04B0', [
        StringStruct('CompanyName', '{AUTEUR}'),
        StringStruct('FileDescription', '{description}'),
        StringStruct('FileVersion', '{lisible}'),
        StringStruct('InternalName', '{nom_fichier}'),
        StringStruct('LegalCopyright',
                     '© {ANNEE} {AUTEUR}'),
        StringStruct('OriginalFilename', '{nom_fichier}.exe'),
        StringStruct('ProductName', '{PRODUIT}'),
        StringStruct('ProductVersion', '{lisible}'),
      ])]),
    VarFileInfo([VarStruct('Translation', [1036, 1200])])
  ]
)
"""


def ecrire(dossier, nom_fichier: str, description: str):
    """Écrit le fichier de ressource et rend son chemin.

    `1036` est l'identifiant de langue du français, `1200` la page de
    codes Unicode : les accents des champs passent tels quels.
    """
    import pathlib
    cible = pathlib.Path(dossier) / f'version_{nom_fichier}.txt'
    cible.write_text(_texte(nom_fichier, description), encoding='utf-8')
    return str(cible)
