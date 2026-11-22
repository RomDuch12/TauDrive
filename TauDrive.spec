# -*- mode: python ; coding: utf-8 -*-
"""Recette d'empaquetage TauDrive / TauDrive PyInstaller spec.

Produit l'application de gravure :

    TauDrive.exe          application de gravure (fenêtrée)

    pyinstaller TauDrive.spec              (depuis la racine du dépôt)
    pyinstaller --clean --noconfirm TauDrive.spec

Le résultat est dans `dist/TauDrive/`. Copier ce dossier entier sur les
postes : aucun Python n'y est nécessaire.

La version réduite au convertisseur a sa propre recette,
`TauConvert.spec`.

**Aucun code source n'est distribué.** Les modules sont compilés et rangés
dans l'archive interne de l'exécutable : le dossier `dist/` ne contient
pas un seul `.py`. `optimize=1` retire en outre les assertions du
bytecode embarqué.

Pas `optimize=2` : ce niveau supprime aussi les docstrings, et **numpy en
a besoin à l'import** — `add_docstring` refuse `None` et l'application ne
démarre plus. Le gain aurait été mince ; le défaut, total.

Ce que cela protège, et ce que cela ne protège pas : l'exécutable ne
laisse **rien de lisible** — ni source, ni commentaire, ni docstring — et
le déployer ne donne aucun accès au dépôt. Un bytecode reste toutefois
décompilable par qui s'en donne la peine : c'est une barrière de
distribution, pas un secret industriel. Si le code devait être réellement
protégé, il faudrait le sortir de l'exécutable — service distant ou
composant natif signé — et cela se déciderait avec le client.
"""

import pathlib

import PySide6
from PyInstaller.utils.hooks import collect_submodules

# `SPECPATH` est fourni par PyInstaller : le dossier de ce fichier.
ROOT = pathlib.Path(SPECPATH).resolve()          # noqa: F821
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

# Seules l'icône et le logo servent à l'exécution ; les aperçus produits
# par `outils/generer_logo.py` n'ont rien à faire dans la distribution.
datas = [(str(ROOT / 'ressources' / name), 'ressources')
         for name in ('taudrive.ico', 'taudrive.png', 'taudrive_marque.png')
         if (ROOT / 'ressources' / name).is_file()]

# **Aucune donnée d'atelier.** TauDrive est libre : ni dessins livrés, ni
# semence du premier lancement, ni magasin d'outils extrait d'une
# machine. L'édition d'un atelier les reçoit de son plugin, que
# `outils/publier.py --plugin … --edition …` pose dans `plugins/`, à côté
# de l'exécutable. Voir `engrave.plugins`.

# Traduction française de Qt. Sans elle, les boutons standards des
# dialogues répondent « OK » et « Cancel » dans une application par
# ailleurs entièrement en français.
_qm = pathlib.Path(PySide6.__file__).parent / 'translations' / 'qtbase_fr.qm'
if _qm.is_file():
    datas.append((str(_qm), 'PySide6/translations'))

hiddenimports = [
    # nos propres paquets : PyInstaller ne les découvre pas tous par
    # analyse statique, plusieurs sont importés tardivement
    *collect_submodules('engrave'),
    *collect_submodules('cl90135'),
    *collect_submodules('jpt'),
    # importés à la demande dans le code
    'serial',
    'serial.tools.list_ports',
    'ezdxf',
    'ezdxf.path',
    # lecture PDF — donc aussi Illustrator moderne, qui est un PDF.
    # Importé tardivement dans `vecimport`, PyInstaller ne le voit pas.
    'pypdf',
    # géométrie exacte du couteau : union de polygones par GEOS. Importée
    # tardivement dans `knife`, et sa DLL doit suivre.
    'shapely',
    'shapely.geometry',
    'shapely.ops',
    'fontTools.pens.basePen',
    'fontTools.ttLib',
]

# --- ce qu'il est inutile d'embarquer -------------------------------------
#
# PySide6 tire par défaut des modules très lourds — moteur web, 3D,
# multimédia — dont TauDrive ne se sert pas. Les exclure divise la taille
# du dossier distribué.

excludes = [
    # Autres liaisons Qt. `ezdxf` sait dialoguer avec plusieurs d'entre
    # elles et les tire à l'analyse ; PyInstaller refuse d'en embarquer
    # deux et interrompt la construction. TauDrive n'utilise que PySide6.
    'PyQt5', 'PyQt6', 'PySide2', 'qtpy',

    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick', 'PySide6.QtWebChannel', 'PySide6.QtWebSockets',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets',
    'PySide6.QtQml', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
    'PySide6.QtPositioning', 'PySide6.QtLocation', 'PySide6.QtSensors',
    'PySide6.QtSerialBus', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtTest',
    'PySide6.QtSql', 'PySide6.QtSpatialAudio', 'PySide6.QtTextToSpeech',
    # boîtes à outils parfois tirées par les dépendances, inutiles ici
    #
    # `numpy` n'est **pas** dans cette liste : les routines accélérées de
    # `ezdxf` sont compilées contre lui et l'import échoue sans, ce qui
    # empêche l'application de démarrer.
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
version_file = _vi.ecrire(ROOT, 'TauDrive', 'TauDrive — pilotage laser TAU 10x10 SMART')

ICON = ROOT / 'ressources' / 'taudrive.ico'
icon_file = str(ICON) if ICON.is_file() else None


# --- analyse ---------------------------------------------------------------

gui = Analysis(                                   # noqa: F821
    [str(ROOT / 'TauDrive.py')],
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

gui_pyz = PYZ(gui.pure)                           # noqa: F821


# --- exécutable -----------------------------------------------------------

gui_exe = EXE(                                    # noqa: F821
    gui_pyz,
    gui.scripts,
    [],
    exclude_binaries=True,
    name='TauDrive',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # application fenêtrée : pas de console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
    version=version_file,
)

coll = COLLECT(                                   # noqa: F821
    gui_exe,
    gui.binaries,
    gui.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TauDrive',
)
