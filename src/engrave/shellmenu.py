"""Menu contextuel Windows : « Convertir avec TauDrive ▸ … ».

Ajoute au clic droit de l'explorateur, sur les dessins vectoriels, un
sous-menu qui convertit sans ouvrir l'application. La conversion elle-même
est celle de `convert` — c'est le même lecteur et le même écrivain que le
menu *Fichier ▸ Exporter*.

**Rien n'est écrit hors de `HKEY_CURRENT_USER`.** L'inscription ne demande
donc aucun droit d'administrateur, ne touche pas les autres comptes de la
machine, et se retire aussi facilement qu'elle s'est posée. C'est aussi
pourquoi elle survit à une mise à jour de TauDrive : seul le chemin de
l'exécutable est mémorisé, et `verifier()` le contrôle.

Windows 11 range les entrées de ce type sous **« Afficher plus
d'options »** (ou Maj+F10) : c'est le menu classique. Les entrées du menu
court demandent un paquet signé, ce qui n'a pas de sens pour un outil
d'atelier.
"""
from __future__ import annotations

import pathlib
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton,
                               QVBoxLayout)

from .convert import SOURCES, TARGETS
from .avale import avale

#: Racine des associations, sous le compte de l'utilisateur.
CLASSES = r'Software\Classes'

#: Nom du verbe, et préfixe des clés de sous-menu.
VERBE = 'TauDrive.Convertir'

#: Libellé du sous-menu.
TITRE = 'Convertir avec TauDrive'

#: Extensions où poser le verbe.
EXTENSIONS = SOURCES


def disponible() -> bool:
    """Vrai si le registre Windows est accessible."""
    return sys.platform == 'win32'


#: Scripts qui savent traiter `--convert`, du plus complet au plus réduit.
LANCEURS = ('TauDrive.py', 'TauConvert.py')


def executable() -> tuple[str, list[str]]:
    """Le programme à lancer, et ses arguments fixes.

    Empaqueté, c'est l'exécutable en cours — `TauDrive.exe` ou
    `TauConvert.exe` selon la version installée. Chacun s'inscrit
    donc lui-même, ce qui est la seule réponse juste : c'est celui qu'on
    a sous la main qui sera là au moment du clic droit.

    En développement, c'est l'interpréteur suivi du script réellement
    lancé — et `pythonw.exe` de préférence, pour qu'une console noire ne
    clignote pas à chaque conversion.
    """
    if getattr(sys, 'frozen', False):
        return sys.executable, []

    racine = pathlib.Path(__file__).resolve().parents[2]
    lance = pathlib.Path(getattr(sys.modules.get('__main__'), '__file__', '')
                         or '').resolve()
    script = (lance if lance.name in LANCEURS and lance.is_file()
              else racine / LANCEURS[0])
    interprete = pathlib.Path(sys.executable)
    muet = interprete.with_name('pythonw.exe')
    if muet.is_file():
        interprete = muet
    return str(interprete), [str(script)]


def ligne_de_commande(kind: str) -> str:
    """La commande inscrite au registre pour une cible donnée."""
    programme, avant = executable()
    morceaux = [f'"{programme}"'] + [f'"{a}"' for a in avant]
    morceaux += ['--convert', '"%1"', '--to', kind]
    return ' '.join(morceaux)


def _cle_sous_menu(suffixe: str) -> str:
    """La clé qui porte le sous-menu d'une extension source.

    Une clé par extension, pour que le sous-menu ne propose jamais de
    convertir un DXF en DXF : une entrée qui ne fait rien d'utile use la
    confiance qu'on accorde au menu entier.
    """
    return f'{VERBE}.{suffixe.lstrip(".")}'


def cibles_pour(suffixe: str) -> list[tuple[str, str]]:
    """Les formats de sortie proposés pour une extension source."""
    source = suffixe.lstrip('.').lower()
    return [(k, libelle) for k, libelle in TARGETS if k != source]


# --------------------------------------------------------------------------
# Poser et retirer
# --------------------------------------------------------------------------

def installer() -> int:
    """Inscrit le sous-menu. Rend le nombre d'extensions traitées."""
    if not disponible():
        raise OSError('le menu contextuel n est possible que sous Windows.')
    import winreg

    programme, _ = executable()
    icone = f'{programme},0'
    posees = 0

    for suffixe in EXTENSIONS:
        cibles = cibles_pour(suffixe)
        if not cibles:
            continue
        sous_menu = _cle_sous_menu(suffixe)

        # le sous-menu, une entrée par format de sortie
        for rang, (kind, libelle) in enumerate(cibles, start=1):
            chemin = rf'{CLASSES}\{sous_menu}\shell\{rang:02d}{kind}'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, chemin) as cle:
                winreg.SetValueEx(cle, 'MUIVerb', 0, winreg.REG_SZ,
                                  f'en {libelle}')
                winreg.SetValueEx(cle, 'Icon', 0, winreg.REG_SZ, icone)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                  chemin + r'\command') as cle:
                winreg.SetValueEx(cle, None, 0, winreg.REG_SZ,
                                  ligne_de_commande(kind))

        # le verbe posé sur l'extension, qui renvoie au sous-menu
        chemin = (rf'{CLASSES}\SystemFileAssociations\{suffixe}'
                  rf'\shell\{VERBE}')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, chemin) as cle:
            winreg.SetValueEx(cle, 'MUIVerb', 0, winreg.REG_SZ, TITRE)
            winreg.SetValueEx(cle, 'Icon', 0, winreg.REG_SZ, icone)
            # Windows ajoute lui-même le `\shell` final : une clé qui le
            # porte déjà pointe vers un sous-menu qui n'existe pas, et
            # l'explorateur retombe sur un verbe fantôme — d'où le
            # « Windows ne trouve pas TauDrive » au clic.
            winreg.SetValueEx(cle, 'ExtendedSubCommandsKey', 0, winreg.REG_SZ,
                              sous_menu)
        posees += 1

    _prevenir_explorateur()
    return posees


def retirer() -> int:
    """Retire tout ce qu'`installer` a posé. Rend le nombre d'entrées ôtées."""
    if not disponible():
        return 0
    import winreg

    otees = 0
    for suffixe in EXTENSIONS:
        chemin = (rf'{CLASSES}\SystemFileAssociations\{suffixe}'
                  rf'\shell\{VERBE}')
        if _supprimer_arbre(winreg.HKEY_CURRENT_USER, chemin):
            otees += 1
        _supprimer_arbre(winreg.HKEY_CURRENT_USER,
                         rf'{CLASSES}\{_cle_sous_menu(suffixe)}')
    _prevenir_explorateur()
    return otees


def _supprimer_arbre(racine, chemin: str) -> bool:
    """Supprime une clé et sa descendance. Vrai si quelque chose existait."""
    import winreg
    try:
        cle = winreg.OpenKey(racine, chemin, 0,
                             winreg.KEY_READ | winreg.KEY_WRITE)
    except OSError:
        return False
    with cle:
        while True:
            try:
                enfant = winreg.EnumKey(cle, 0)
            except OSError:
                break
            _supprimer_arbre(racine, f'{chemin}\\{enfant}')
    try:
        winreg.DeleteKey(racine, chemin)
    except OSError:
        return False
    return True


def _prevenir_explorateur() -> None:
    """Dit à l'explorateur que les associations ont changé.

    Sans cela le menu n'apparaît qu'à la session suivante, et on croit
    l'inscription ratée.
    """
    try:
        import ctypes
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST,
                                             None, None)
    except Exception as exc:                           # noqa: BLE001
        avale('registre : explorateur non prévenu', exc)


# --------------------------------------------------------------------------
# État
# --------------------------------------------------------------------------

def installe() -> bool:
    """Vrai si le verbe est posé sur au moins une extension."""
    if not disponible():
        return False
    import winreg
    for suffixe in EXTENSIONS:
        chemin = (rf'{CLASSES}\SystemFileAssociations\{suffixe}'
                  rf'\shell\{VERBE}')
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, chemin))
            return True
        except OSError:
            continue
    return False


def verifier() -> tuple[bool, str]:
    """L'état du menu, et ce qu'il faudrait en faire.

    Le cas qui compte est le troisième : le menu est posé, mais il désigne
    **un autre programme que celui qui pose la question**. Cela arrive à
    chaque fois que TauDrive est déplacé ou réinstallé ailleurs — et
    aussi lorsque TauDrive et TauConvert cohabitent sur un poste,
    puisqu'ils se partagent volontairement la même clé pour ne jamais
    offrir deux sous-menus identiques. Le clic droit échoue alors en
    silence, ou passe par l'autre programme sans qu'on le sache.

    Le message **nomme** l'exécutable inscrit : « il désigne un autre
    emplacement » n'aide personne à savoir lequel.
    """
    if not disponible():
        return False, 'Le menu contextuel n est possible que sous Windows.'
    if not installe():
        return False, 'Non installé.'
    import winreg
    attendu, _ = executable()
    for suffixe in EXTENSIONS:
        cibles = cibles_pour(suffixe)
        if not cibles:
            continue
        chemin = (rf'{CLASSES}\{_cle_sous_menu(suffixe)}\shell'
                  rf'\01{cibles[0][0]}\command')
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chemin) as cle:
                commande = winreg.QueryValueEx(cle, None)[0]
        except OSError:
            continue
        if attendu.lower() not in str(commande).lower():
            inscrit = _programme_inscrit(str(commande))
            return True, (f'Installé, mais le clic droit appelle '
                          f'{inscrit}.\nCliquez sur Installer pour qu'
                          f'il appelle celui-ci à la place.')
        break
    return True, f'Installé pour {len(EXTENSIONS)} type(s) de fichier.'


# --------------------------------------------------------------------------
# Le dialogue
# --------------------------------------------------------------------------

class ShellMenuDialog(QDialog):
    """Poser ou retirer le menu contextuel, en sachant ce qu'on pose.

    Le dialogue dit trois choses avant d'offrir le bouton : quels
    fichiers gagnent le menu, où l'inscription est écrite, et pourquoi
    Windows 11 la range sous « Afficher plus d'options ». Un utilisateur
    qui clique « Installer » puis ne voit rien au clic droit conclurait
    que c'est cassé.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Menu contextuel Windows')
        self.setMinimumWidth(560)

        dehors = QVBoxLayout(self)
        entrees = ', '.join(s.lstrip('.').upper() for s in EXTENSIONS)
        sorties = ', '.join(libelle for _, libelle in TARGETS)
        dehors.addWidget(_riche(
            f'<p>Ajoute au clic droit de l explorateur, sur les fichiers '
            f'<b>{entrees}</b>, un sous-menu <b>« {TITRE} »</b> qui '
            f'convertit vers <b>{sorties}</b> sans ouvrir TauDrive.</p>'
            f'<p>Le fichier converti est écrit <b>à côté de l original</b>, '
            f'qui n est jamais modifié. Un fichier du même nom n est jamais '
            f'écrasé : la conversion prend alors un nom numéroté.</p>'))

        self._etat = QLabel()
        self._etat.setWordWrap(True)
        dehors.addWidget(self._etat)

        dehors.addWidget(_riche(
            '<p><b>Sous Windows 11</b>, ce type d entrée se trouve sous '
            '<i>Afficher plus d options</i> (ou <b>Maj+F10</b> au clavier), '
            'et non dans le menu court.</p>'
            '<p>L inscription est écrite <b>sous votre compte Windows '
            'seulement</b> : elle ne demande aucun droit d administrateur, '
            'ne touche pas les autres comptes du poste, et se retire d un '
            'clic.</p>'))

        boutons = QHBoxLayout()
        self._poser = QPushButton('Installer')
        self._poser.clicked.connect(self._installer)
        self._oter = QPushButton('Retirer')
        self._oter.clicked.connect(self._retirer)
        fermer = QPushButton('Fermer')
        fermer.clicked.connect(self.accept)
        fermer.setDefault(True)
        boutons.addWidget(self._poser)
        boutons.addWidget(self._oter)
        boutons.addStretch(1)
        boutons.addWidget(fermer)
        dehors.addLayout(boutons)
        self._rafraichir()

    def _rafraichir(self) -> None:
        pose, message = verifier()
        couleur = ''
        try:
            from . import theme
            palette = theme.current()
            couleur = palette.ok if pose else palette.warn
        except Exception as exc:                       # noqa: BLE001
            avale('thème : couleur indisponible', exc)
        style = f' style="color:{couleur}"' if couleur else ''
        self._etat.setTextFormat(Qt.RichText)
        self._etat.setText(f'<p{style}><b>{message}</b></p>'.replace(
            chr(10), '<br>'))
        self._poser.setEnabled(disponible())
        self._oter.setEnabled(disponible() and pose)

    def _installer(self) -> None:
        try:
            combien = installer()
        except OSError as exc:
            QMessageBox.warning(self, 'Menu contextuel', str(exc))
            return
        self._rafraichir()
        QMessageBox.information(
            self, 'Menu contextuel',
            f'Menu posé sur {combien} type(s) de fichier.'
            f'{chr(10)}{chr(10)}Sous Windows 11, ouvrez le clic droit puis '
            f'« Afficher plus d options ».')

    def _retirer(self) -> None:
        retirer()
        self._rafraichir()


def _riche(html: str) -> QLabel:
    """Un paragraphe qui se replie."""
    label = QLabel(html)
    label.setTextFormat(Qt.RichText)
    label.setWordWrap(True)
    return label

def _programme_inscrit(commande: str) -> str:
    """Le nom de l'exécutable que porte une commande du registre.

    La commande est du PowerShell-libre : un chemin entre guillemets,
    puis les arguments. On ne rend que le nom du fichier — c'est ce
    qui distingue TauDrive.exe de TauConvert.exe, et le chemin
    complet n'aurait pas sa place dans une ligne d'état.
    """
    commande = commande.strip()
    if commande.startswith(chr(34)):
        fin = commande.find(chr(34), 1)
        if fin > 1:
            return pathlib.Path(commande[1:fin]).name
    return commande.split(' ')[0] or 'un autre programme'
