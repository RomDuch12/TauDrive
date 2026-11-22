"""Barre d'avancement pour ce qui dure / progress for slow work.

**La règle : au-delà d'une seconde, on montre et on laisse partir.**

En dessous, une barre qui apparaît et disparaît aussitôt est plus
gênante qu'utile — elle fait clignoter l'écran pour rien. Au-delà, une
fenêtre figée sans explication a toutes les apparences d'un plantage :
la barre dit que ça travaille, et le bouton dit qu'on peut s'en aller.

Le seuil porte sur le **temps réellement écoulé**, et non sur une taille
de fichier ou un nombre de points. Un même dessin est rapide sur un
poste et lent sur un autre ; deviner à l'avance se trompe dans les deux
sens, alors que la montre ne se trompe jamais.

    from .longtask import barre

    with barre(self, 'Lecture du dessin…') as progres:
        formes = lire(chemin, progress=progres)

`progres(fraction, texte)` rend **False** quand on a demandé l'arrêt.
C'est la convention déjà employée par `dxfimport.read` et
`vecimport.read` : le travail la consulte de loin en loin et lève
`Cancelled`.

**Ce que ce module ne peut pas faire.** Le travail tourne dans le fil de
l'interface — y poser des formes depuis un fil de fond demanderait de
tout verrouiller. Un calcul qui ne rend jamais la main ne peut donc ni
s'afficher ni s'interrompre : c'est à lui d'appeler `progres`. Les
chemins lents de TauDrive le font ; un nouveau doit le faire aussi.
"""
from __future__ import annotations

import contextlib
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog

#: Au-delà de cette durée, la barre paraît. En deçà, rien.
SEUIL_S = 1.0

#: Pas de rafraîchissement. Repeindre à chaque appel coûterait plus cher
#: que le travail lui-même sur une boucle serrée.
RAFRAICHIR_S = 0.05


class Reporter:
    """Ce qu'on passe au travail : un appel, et une réponse.

    Rendre `False` veut dire « on arrête ». Le travail est libre de
    l'ignorer — mais alors le bouton *Annuler* ne servirait à rien, et
    mieux vaudrait ne pas l'offrir.
    """

    def __init__(self, parent, titre: str, seuil_s: float = SEUIL_S) -> None:
        self._parent = parent
        self._titre = titre
        self._seuil = float(seuil_s)
        self._depart = time.monotonic()
        self._dernier = 0.0
        self._dialogue: QProgressDialog | None = None
        self.annule = False

    # -- appel ---------------------------------------------------------

    def __call__(self, fraction: float = 0.0, texte: str = '') -> bool:
        maintenant = time.monotonic()
        ecoule = maintenant - self._depart

        if self._dialogue is None:
            if ecoule < self._seuil:
                return not self.annule
            self._ouvrir()

        if maintenant - self._dernier < RAFRAICHIR_S:
            return not self.annule
        self._dernier = maintenant

        valeur = max(0, min(1000, int(float(fraction or 0.0) * 1000)))
        self._dialogue.setValue(valeur)
        if texte:
            self._dialogue.setLabelText(str(texte))
        QApplication.processEvents()
        if self._dialogue.wasCanceled():
            self.annule = True
        return not self.annule

    def _ouvrir(self) -> None:
        self._dialogue = QProgressDialog(self._titre, 'Annuler', 0, 1000,
                                         self._parent)
        self._dialogue.setWindowTitle('TauDrive')
        self._dialogue.setWindowModality(Qt.WindowModal)
        # déjà ouverte quand on la crée : le délai a été mesuré ici, pas
        # laissé à Qt, qui le compterait à partir de sa propre naissance
        self._dialogue.setMinimumDuration(0)
        self._dialogue.setAutoClose(False)
        self._dialogue.setAutoReset(False)
        self._dialogue.show()
        QApplication.processEvents()

    # -- fin -----------------------------------------------------------

    def duree_s(self) -> float:
        return time.monotonic() - self._depart

    def a_paru(self) -> bool:
        """Vrai si la barre a réellement été montrée."""
        return self._dialogue is not None

    def fermer(self) -> None:
        if self._dialogue is not None:
            self._dialogue.close()
            self._dialogue.deleteLater()
            self._dialogue = None
            QApplication.processEvents()


@contextlib.contextmanager
def barre(parent, titre: str, seuil_s: float = SEUIL_S):
    """Prête un `Reporter` et le referme, quoi qu'il arrive.

    La barre se ferme aussi quand le travail lève : une fenêtre
    d'avancement qui survit à l'erreur qu'elle accompagnait reste sur
    l'écran sans plus rien mesurer.
    """
    reporter = Reporter(parent, titre, seuil_s)
    try:
        yield reporter
    finally:
        reporter.fermer()
