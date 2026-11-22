# -*- mode: python ; coding: utf-8 -*-
"""Recette d'empaquetage de TauConvert / conversion-only spec.

    pyinstaller TauConvert.spec        (depuis atelier/)

Produit `dist/TauConvert/TauConvert.exe` — le convertisseur
seul : pose et retrait du menu contextuel, conversion, mode d'emploi.

**Recette séparée, et non une cible de plus dans `TauDrive.spec`.** Les
deux exécutables de `TauDrive.spec` partagent leurs dépendances par
`MERGE`, ce qui est exactement ce qu'on ne veut pas ici : le
convertisseur doit pouvoir se copier **seul** sur un poste de bureau.
S'il partageait un dossier avec l'application de gravure, il faudrait
livrer les deux.

**Ce qui est délibérément dehors** — et l'autotest le vérifie :

    engrave.app      l'application de gravure et son plan de travail
    jpt, cl90135     les protocoles machine
    serial           le port série
    shapely          la géométrie du couteau

Un poste de bureau n'a aucune raison de porter une commande de laser.
"""

import pathlib

import PySide6
from PyInstaller.utils.hooks import collect_submodules

ROOT = pathlib.Path(SPECPATH).resolve()           # noqa: F821
SRC = ROOT / 'src'

# --- source dépouillée ------------------------------------------------------
#
# On empaquette une copie **sans docstrings** : 36 % du source, et de loin
# ce qu'un décompilateur aurait de plus utile. Le programme se comporte à
# l'identique — l'autotest passe sur les deux copies, 355/355.
#
# Ce n'est pas une protection : le bytecode reste décompilable, les noms
# et la structure restent lisibles. Cela élève le coût d'entrée, sans
# fermer aucune porte. Voir `outils/depouiller.py`.
#
# Poser `TAUDRIVE_SOURCE=brut` dans l'environnement empaquette le source
# tel quel — utile pour déboguer un exécutable figé.
import os as _os
if _os.environ.get('TAUDRIVE_SOURCE', '').lower() != 'brut':
    import importlib.util as _ilu_d
    _spd = _ilu_d.spec_from_file_location(
        'depouiller', str(ROOT / 'outils' / 'depouiller.py'))
    _dep = _ilu_d.module_from_spec(_spd)
    _spd.loader.exec_module(_dep)
    _compte = _dep.construire()
    print(f'[TauDrive] source dépouillée : '
          f'{_compte["octets_avant"] - _compte["octets_apres"]:,} caractères '
          f'retirés de {_compte["fichiers"]} fichiers')
    for _e in _compte['echecs']:
        print('[TauDrive] non dépouillé :', _e)
    SRC = ROOT / 'build' / 'src-depouille'

# --- ce qui doit être embarqué --------------------------------------------

datas = [(str(ROOT / 'ressources' / name), 'ressources')
         for name in ('taudrive.ico', 'taudrive.png')
         if (ROOT / 'ressources' / name).is_file()]

_qm = pathlib.Path(PySide6.__file__).parent / 'translations' / 'qtbase_fr.qm'
if _qm.is_file():
    datas.append((str(_qm), 'PySide6/translations'))

# Les quinze modules qu'une conversion charge réellement, relevés à
# l'exécution — et non tout `engrave`, dont l'essentiel ne sert qu'à
# graver. `collect_submodules` tirerait `app`, et avec lui la moitié de
# ce que cette version doit précisément ne pas embarquer.
hiddenimports = [
    'engrave.avale', 'engrave.barcode', 'engrave.convert',
    'engrave.convertapp',
    'engrave.dxfimport', 'engrave.fontmap', 'engrave.geometry',
    'engrave.model', 'engrave.ordering', 'engrave.session',
    'engrave.shellmenu', 'engrave.svgread', 'engrave.textvec',
    'engrave.theme', 'engrave.toolpath', 'engrave.variables',
    'engrave.vecexport', 'engrave.vecimport', 'engrave.wobble',
    # importés tardivement : PyInstaller ne les voit pas à l'analyse
    'ezdxf', 'ezdxf.path',
    'pypdf',
    'fontTools.pens.basePen', 'fontTools.ttLib',
]

excludes = [
    # ce que cette version ne doit pas porter
    'engrave.app', 'engrave.knife',
    'jpt', 'cl90135', 'serial', 'shapely',

    'PyQt5', 'PyQt6', 'PySide2', 'qtpy',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick', 'PySide6.QtWebChannel',
    'PySide6.QtWebSockets',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets',
    'PySide6.QtQml', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
    'PySide6.QtPositioning', 'PySide6.QtLocation', 'PySide6.QtSensors',
    'PySide6.QtSerialBus', 'PySide6.QtSerialPort',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtTest',
    'PySide6.QtSql', 'PySide6.QtSpatialAudio', 'PySide6.QtTextToSpeech',
    'PySide6.QtNetwork',
    # `numpy` reste : les routines compilées d'`ezdxf` en dépendent.
    'tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython', 'pytest',
]

# Propriétés Windows du fichier : nom, éditeur, contact.
# Ne signe rien — voir `reference/signature-windows.md` —
# mais donne à l'utilisateur de quoi savoir ce qu'il ouvre.
import importlib.util as _ilu
_sp = _ilu.spec_from_file_location(
    'version_info', str(ROOT / 'version_info.py'))
_vi = _ilu.module_from_spec(_sp)
_sp.loader.exec_module(_vi)
version_file = _vi.ecrire(ROOT, 'TauConvert', 'TauConvert — conversion de dessins vectoriels')

ICON = ROOT / 'ressources' / 'taudrive.ico'
icon_file = str(ICON) if ICON.is_file() else None

# --- aucune donnée d'atelier ------------------------------------------------
#
# `engrave.model` est embarqué pour ses classes (Document, formes). Le cœur
# est libre : ses process sont neutres, celles d'un atelier viennent de son
# plugin, que TauConvert ne charge pas. Plus rien à neutraliser — mais la
# construction s'arrête si une donnée d'atelier reparaissait dans le code.
import re as _re
_code = _re.sub(r'#.*', '', (SRC / 'engrave' / 'model.py').read_text(encoding='utf-8'))
for _interdit in ('JPT 30W', 'dbpunte', 'ReportIncisione', 'Laiton —', 'Acier trempé'):
    if _interdit in _code:
        raise SystemExit(f'[TauConvert] donnée d\'atelier dans le code : {_interdit}')

a = Analysis(                                     # noqa: F821
    [str(ROOT / 'TauConvert.py')],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)                                 # noqa: F821

exe = EXE(                                        # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TauConvert',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
    version=version_file,
)

coll = COLLECT(                                   # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TauConvert',
)
