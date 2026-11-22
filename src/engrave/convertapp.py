"""La fenêtre de TauConvert / conversion-only window.

Une seule fenêtre, sans menu ni barre d'outils : un mode d'emploi, deux
boutons, une ligne d'état. C'est délibérément tout.

Le poste qui reçoit cette version n'a pas de laser. Lui présenter un plan
de travail ou des process l'inviterait à chercher une
machine qu'il n'a pas — et poserait la question de savoir pourquoi un
poste de bureau porte une commande de gravure. La réponse est qu'il n'en
porte pas.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from . import shellmenu, theme
from .convert import SOURCES, TARGETS


def tutoriel_html() -> str:
    """Le mode d'emploi, en trois temps : poser, s'en servir, retirer."""
    entrees = ', '.join(s.lstrip('.').upper() for s in SOURCES)
    sorties = ', '.join(libelle for _, libelle in TARGETS)
    return f'''
<p><b>1 — Posez le menu.</b> Le bouton <i>Installer</i> ajoute au clic
droit de l'explorateur, sur les fichiers <b>{entrees}</b>, un sous-menu
« Convertir avec TauDrive ».</p>

<p><b>2 — Servez-vous-en.</b> Clic droit sur un dessin, puis le format
voulu : <b>{sorties}</b>. Le fichier converti est écrit
<b>à côté de l'original</b>, qui n'est jamais modifié. Un fichier du même
nom n'est jamais écrasé : la conversion prend un nom numéroté.</p>

<p style="color:{theme.current().warn}"><b>Sous Windows 11</b>, l'entrée
est sous <i>Afficher plus d'options</i> — ou <b>Maj+F10</b> au clavier.
Ce n'est pas un défaut d'installation : le menu court de Windows 11
n'accepte que les paquets signés.</p>

<p><b>3 — Retirez-le quand vous voulez.</b> Le bouton <i>Retirer</i>
efface tout ce qui a été posé, sans laisser une clé. L'inscription vit
sous votre seul compte Windows : aucun droit d'administrateur n'est
demandé, et les autres comptes du poste ne sont pas touchés.</p>

<p>Vous pouvez aussi convertir sans passer par le menu :</p>
<pre>TauConvert.exe --convert dessin.ai --to dxf</pre>
'''


class ConvertWindow(QWidget):
    """Mode d'emploi, pose, retrait, état. Rien de plus."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('TauDrive — convertisseur')
        self.setMinimumWidth(560)

        dehors = QVBoxLayout(self)
        dehors.setContentsMargins(18, 16, 18, 16)
        dehors.setSpacing(12)

        titre = QLabel('<h2 style="margin:0">Convertir des dessins '
                       'vectoriels</h2>')
        titre.setTextFormat(Qt.RichText)
        dehors.addWidget(titre)

        sous_titre = QLabel(
            'Version réduite de TauDrive : la conversion seule, sans '
            'gravure ni machine.')
        sous_titre.setWordWrap(True)
        dehors.addWidget(sous_titre)

        trait = QFrame()
        trait.setFrameShape(QFrame.HLine)
        dehors.addWidget(trait)

        self._tutoriel = QLabel(tutoriel_html())
        self._tutoriel.setTextFormat(Qt.RichText)
        self._tutoriel.setWordWrap(True)
        self._tutoriel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dehors.addWidget(self._tutoriel)

        self._etat = QLabel('')
        self._etat.setTextFormat(Qt.RichText)
        self._etat.setWordWrap(True)
        dehors.addWidget(self._etat)

        boutons = QHBoxLayout()
        self.bouton_poser = QPushButton('Installer')
        self.bouton_poser.clicked.connect(self._installer)
        self.bouton_oter = QPushButton('Retirer')
        self.bouton_oter.clicked.connect(self._retirer)
        fermer = QPushButton('Fermer')
        fermer.clicked.connect(self.close)
        boutons.addWidget(self.bouton_poser)
        boutons.addWidget(self.bouton_oter)
        boutons.addStretch(1)
        boutons.addWidget(fermer)
        dehors.addLayout(boutons)
        dehors.addStretch(1)

        self._rafraichir()

    def tutoriel_texte(self) -> str:
        """Le mode d'emploi en texte nu — sert au contrôle automatique."""
        return self._tutoriel.text()

    # -- état ----------------------------------------------------------

    def _rafraichir(self) -> None:
        pose, message = shellmenu.verifier()
        palette = theme.current()
        couleur = palette.ok if pose else palette.warn
        self._etat.setText(
            f'<p style="color:{couleur}"><b>{message}</b></p>'.replace(
                chr(10), '<br>'))
        self.bouton_poser.setEnabled(shellmenu.disponible())
        self.bouton_oter.setEnabled(shellmenu.disponible() and pose)

    def _installer(self) -> None:
        try:
            combien = shellmenu.installer()
        except OSError as exc:
            QMessageBox.warning(self, 'Menu contextuel', str(exc))
            return
        self._rafraichir()
        QMessageBox.information(
            self, 'Menu contextuel',
            f'Menu posé sur {combien} type(s) de fichier.'
            f'{chr(10)}{chr(10)}Sous Windows 11, ouvrez le clic droit puis '
            f'« Afficher plus d\'options ».')

    def _retirer(self) -> None:
        shellmenu.retirer()
        self._rafraichir()
