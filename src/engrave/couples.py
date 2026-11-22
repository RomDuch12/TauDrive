"""Couples fréquence / impulsion / F-T pulse couples.

Sur une source **MOPA**, la durée d'impulsion et la fréquence ne sont pas
deux réglages libres : chaque forme d'onde a sa fréquence de répétition
maximale, et l'énergie par impulsion s'effondre au-delà. Les régler
séparément dans un coupon d'essai produit donc des cases qui ne veulent
rien dire — une impulsion de 2 ns à 50 kHz ne marque rien, une de 250 ns
à 1000 kHz est hors d'atteinte.

Ce qui se fait varier utilement, c'est le **couple** : *1300-2*, *375-9*,
*250-13* — la fréquence en kHz, puis la durée en ns. Un axe de coupon
peut donc porter un couple entier, et chaque case reçoit les deux
réglages d'un bloc.

**Deux tables.**

* La **table constructeur** : les treize formes d'onde de la source,
  chacune avec sa fréquence de répétition maximale. Lecture seule, et
  seule disponible en mode normal — un opérateur ne doit pas pouvoir
  inventer un couple que la source refusera.
* Les **couples d'atelier**, réservés au mode expert, avec un
  gestionnaire complet. C'est là qu'on range ce qu'on a mesuré sur pièce,
  **sous le nom du travail qu'il sert** — *Client A fin* — car c'est
  ainsi qu'on le cherche, bien avant de se souvenir que c'est du 200-60.
  Ce sont des données d'atelier : le plugin de l'atelier les apporte
  (`plugins.Api.add_couples`), le cœur libre n'en a aucun.

Un troisième jeu se **récolte** : les couples réellement portés par les
72 outils du magasin de la machine. Ceux-là ne sont pas supposés, ils
ont gravé.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout)

from . import session
from .widgets import IntSpin
from . import theme

#: Clé de rangement des couples du poste.
STORE = 'couples/custom'

#: Bornes admises, reprises de `reference/limites-machine.md`.
F_MIN_KHZ, F_MAX_KHZ = 1, 4000
T_MIN_NS, T_MAX_NS = 1, 2000


@dataclass(frozen=True)
class Couple:
    """Une fréquence et la durée d'impulsion qui va avec."""
    frequency_khz: float
    pulse_width_ns: int
    #: D'où il vient : 'constructeur', 'atelier', 'poste' ou 'magasin'.
    origin: str = 'poste'
    #: Le travail qu'il sert, quand il en sert un — « Client A fin ».
    #: C'est sous ce nom-là qu'un opérateur le cherche, bien avant de se
    #: souvenir que c'est du 200-60.
    name: str = ''

    def key(self) -> str:
        """L'écriture d'atelier : « 1300-2 »."""
        return f'{self.frequency_khz:g}-{self.pulse_width_ns:g}'

    def label(self) -> str:
        titre = f'{self.key()}   ({self.frequency_khz:g} kHz · '
        titre += f'{self.pulse_width_ns:g} ns)'
        return f'{titre}   —   {self.name}' if self.name else titre

    def duty_percent(self) -> float:
        """Rapport cyclique τ × f, en %. Au-delà de 5 %, on est suspect."""
        return self.pulse_width_ns * 1e-9 * self.frequency_khz * 1e3 * 100.0

    def values(self) -> dict:
        """Ce qu'il pose dans une process."""
        return {'frequency_khz': float(self.frequency_khz),
                'pulse_width_ns': int(self.pulse_width_ns)}


#: Table constructeur de la source JPT MOPA 30 W de la TAU 10×10 SMART.
#:
#: Les **treize formes d'onde** de la source, avec la fréquence de
#: répétition maximale de chacune. Relevée sur la machine : aucun fichier
#: livré ne la porte — la table est dans le firmware, et la GUI JPT
#: l'interroge en RS-232 au démarrage (cf. `limites-machine.md` §2).
#:
#: La lecture est franche : plus l'impulsion est longue, plus la
#: fréquence plafonne bas. De 2 ns à 1300 kHz — impulsions très courtes,
#: cadence très haute, marquage superficiel — jusqu'à 500 ns à 37 kHz,
#: où chaque impulsion porte toute son énergie et creuse.
#:
#: Les quatre dernières partagent 37 kHz : au-delà de 200 ns, c'est
#: l'énergie par impulsion qui commande, et la source ne suit plus en
#: cadence.
FACTORY: tuple[Couple, ...] = (
    Couple(1300, 2, 'constructeur'),
    Couple(375, 9, 'constructeur'),
    Couple(250, 13, 'constructeur'),
    Couple(170, 20, 'constructeur'),
    Couple(135, 30, 'constructeur'),
    Couple(110, 45, 'constructeur'),
    Couple(100, 60, 'constructeur'),
    Couple(90, 80, 'constructeur'),
    Couple(80, 100, 'constructeur'),
    Couple(37, 200, 'constructeur'),
    Couple(37, 250, 'constructeur'),
    Couple(37, 350, 'constructeur'),
    Couple(37, 500, 'constructeur'),
)


#: Couples mesurés à l'atelier, nommés d'après le travail qu'ils servent.
#:
#: Ils ne sont pas dans la table constructeur : ce sont des points de
#: fonctionnement trouvés sur pièce, et gardés parce qu'ils marchent. Deux
#: travaux peuvent partager le même couple — *Client A fin* et *Client B*
#: gravant tous deux en 200-60 — auquel cas c'est **un** couple qui porte
#: les deux noms : un coupon n'a rien à gagner à graver deux fois la même
#: case.
#:
#: Réservés au mode expert, comme les couples du poste : ce sont des
#: valeurs d'atelier, pas des limites de la source. **Aucun au cœur
#: libre** : le plugin de l'atelier les apporte — voir `workshop_raw`.
WORKSHOP: tuple[Couple, ...] = ()


def workshop_raw() -> list[Couple]:
    """Les couples d'atelier tels que déclarés : le cœur, puis les plugins."""
    from .plugins import REGISTRY
    return list(WORKSHOP) + list(REGISTRY.couples)


def workshop() -> list[Couple]:
    """Les couples d'atelier, un par valeur, noms réunis."""
    return _merge(workshop_raw())


def _merge(couples) -> list[Couple]:
    """Réunit les doublons de valeur en gardant tous leurs noms."""
    vus: dict[str, Couple] = {}
    for couple in couples:
        connu = vus.get(couple.key())
        if connu is None:
            vus[couple.key()] = couple
        elif couple.name and couple.name not in connu.name:
            vus[couple.key()] = dataclasses.replace(
                connu, name=f'{connu.name} · {couple.name}'
                if connu.name else couple.name)
    return sorted(vus.values(), key=lambda c: c.pulse_width_ns)


def factory() -> list[Couple]:
    """La table constructeur, triée de la plus courte impulsion à la plus
    longue."""
    return sorted(FACTORY, key=lambda c: c.pulse_width_ns)


def custom() -> list[Couple]:
    """Les couples du poste, tels qu'ils ont été rangés."""
    brut = session.settings().value(STORE) or []
    if not isinstance(brut, list):
        return []
    out = []
    for entree in brut:
        try:
            out.append(Couple(float(entree['f']), int(entree['t']), 'poste',
                              str(entree.get('n', '') or '')))
        except (TypeError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda c: c.pulse_width_ns)


def save_custom(couples: list[Couple]) -> None:
    session.settings().setValue(
        STORE, [{'f': c.frequency_khz, 't': c.pulse_width_ns, 'n': c.name}
                for c in couples])


def from_magazine() -> list[Couple]:
    """Les couples réellement portés par les outils de la machine.

    Ceux-là ne sont pas supposés : ils sont dans `dbpunte.mag`, et ils ont
    gravé. Le magasin est lu, jamais écrit.
    """
    from . import toolstore
    vus: set[tuple[float, int]] = set()
    for outil in toolstore.tools():
        if outil.separator() or not outil.frequency_hz or not outil.pulse_width_ns:
            continue
        vus.add((round(outil.frequency_hz / 1000.0, 3),
                 int(outil.pulse_width_ns)))
    return sorted((Couple(f, t, 'magasin') for f, t in vus),
                  key=lambda c: (c.pulse_width_ns, c.frequency_khz))


def available(expert: bool = False) -> list[Couple]:
    """Couples proposés : la table seule en mode normal, tout en expert.

    Le mode normal ne montre que la table constructeur — c'est la règle
    posée pour les réglages qu'un opérateur ne doit pas pouvoir inventer,
    la même que pour la fréquence et l'impulsion prises séparément.
    """
    if not expert:
        return factory()
    connus = list(factory())
    vus = {c.key() for c in connus}
    for couple in _merge(workshop_raw() + custom()):
        if couple.key() not in vus:
            vus.add(couple.key())
            connus.append(couple)
    return connus


def parse(texte: str) -> Couple | None:
    """Lit « 1300-2 », « 1300/2 » ou « 1300 2 ». Rend None si c'est illisible."""
    morceaux = str(texte or '').replace('/', '-').replace(' ', '-').split('-')
    morceaux = [m for m in morceaux if m]
    if len(morceaux) != 2:
        return None
    try:
        return Couple(float(morceaux[0].replace(',', '.')),
                      int(float(morceaux[1].replace(',', '.'))))
    except ValueError:
        return None


class CoupleManager(QDialog):
    """Gestionnaire des couples du poste. **Mode expert seulement.**

    La table constructeur y figure en lecture seule, pour qu'on voie ce
    qu'on complète ; seuls les couples du poste s'ajoutent, se modifient
    et s'effacent.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Couples fréquence / impulsion')
        self.setMinimumSize(520, 460)
        self._couples = custom()

        dehors = QVBoxLayout(self)
        dehors.addWidget(QLabel(
            'Sur une source MOPA, la durée d\'impulsion et la fréquence '
            'vont par paires.<br>La table constructeur est en lecture '
            'seule ; les couples du poste s\'ajoutent ici.'))

        self.w_list = QListWidget()
        self.w_list.currentItemChanged.connect(lambda *_: self._selected())
        dehors.addWidget(self.w_list, 1)

        saisie = QHBoxLayout()
        saisie.addWidget(QLabel('Fréquence'))
        self.w_f = IntSpin(100, F_MIN_KHZ, F_MAX_KHZ, 10, 'kHz')
        saisie.addWidget(self.w_f)
        saisie.addWidget(QLabel('Impulsion'))
        self.w_t = IntSpin(20, T_MIN_NS, T_MAX_NS, 1, 'ns')
        saisie.addWidget(self.w_t)
        self.w_name = QLineEdit()
        self.w_name.setPlaceholderText('travail servi — « Client A fin »')
        self.w_name.setToolTip(
            'Facultatif, mais c\'est sous ce nom qu\'on retrouve un '
            'couple :\non se souvient du travail bien avant de se '
            'souvenir du 200-60.')
        self.w_name.returnPressed.connect(self._add)
        saisie.addWidget(self.w_name, 1)
        self.w_add = QPushButton('Ajouter')
        self.w_add.clicked.connect(self._add)
        saisie.addWidget(self.w_add)
        dehors.addLayout(saisie)

        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        self.w_note.setStyleSheet(theme.css('text_dim', 11))
        dehors.addWidget(self.w_note)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText(
            'Enregistrer')
        boutons.accepted.connect(self._store)
        boutons.rejected.connect(self.reject)
        self.w_drop = QPushButton('Supprimer')
        self.w_drop.clicked.connect(self._drop)
        boutons.addButton(self.w_drop, QDialogButtonBox.ActionRole)
        self.w_harvest = QPushButton('Reprendre ceux du magasin')
        self.w_harvest.setToolTip(
            'Ajoute les couples réellement portés par les outils de la '
            'machine.\nIls ne sont pas supposés : ils ont gravé.')
        self.w_harvest.clicked.connect(self._harvest)
        boutons.addButton(self.w_harvest, QDialogButtonBox.ActionRole)
        dehors.addWidget(boutons)

        self._refresh()

    # -- affichage ---------------------------------------------------------

    def _refresh(self) -> None:
        garde = self._current().key() if self._current() else ''
        self.w_list.clear()
        # Les deux tables livrées d'abord, en lecture seule, pour qu'on
        # voie ce qu'on complète et qu'on ne redouble pas un couple connu.
        for couple in factory():
            item = QListWidgetItem(f'{couple.label()}   — constructeur')
            item.setData(Qt.UserRole, couple)
            item.setForeground(Qt.gray)
            self.w_list.addItem(item)
        for couple in workshop():
            item = QListWidgetItem(f'{couple.label()}   — atelier')
            item.setData(Qt.UserRole, couple)
            item.setForeground(Qt.gray)
            self.w_list.addItem(item)
        for couple in self._couples:
            item = QListWidgetItem(f'{couple.label()}   — poste')
            item.setData(Qt.UserRole, couple)
            self.w_list.addItem(item)
            if couple.key() == garde:
                self.w_list.setCurrentItem(item)
        self._selected()

    def _current(self) -> Couple | None:
        item = self.w_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _selected(self) -> None:
        couple = self._current()
        propre = bool(couple and couple.origin == 'poste')
        self.w_drop.setEnabled(propre)
        if couple is None:
            self.w_note.setText(f'{len(self._couples)} couple(s) du poste.')
            return
        rapport = couple.duty_percent()
        alerte = ('  —  rapport cyclique élevé, à vérifier sur la source'
                  if rapport > 5.0 else '')
        venue = {'constructeur': 'table de la source, en lecture seule',
                 'atelier': 'mesuré sur pièce, livré avec TauDrive',
                 'magasin': 'porté par un outil de la machine'}.get(
                     couple.origin, 'couple du poste')
        self.w_note.setText(
            f'{couple.key()} · {venue} · rapport cyclique '
            f'{rapport:.2f} %{alerte}')

    # -- gestes ------------------------------------------------------------

    def _add(self) -> None:
        couple = Couple(float(self.w_f.value()), int(self.w_t.value()),
                        'poste', self.w_name.text().strip())
        connus = self._couples + factory() + workshop()
        if any(c.key() == couple.key() for c in connus):
            QMessageBox.information(self, 'Couples',
                                    f'{couple.key()} figure déjà dans la '
                                    f'liste.')
            return
        self.w_name.clear()
        self._couples.append(couple)
        self._couples.sort(key=lambda c: c.pulse_width_ns)
        self._refresh()

    def _drop(self) -> None:
        couple = self._current()
        if couple is None or couple.origin != 'poste':
            return
        self._couples = [c for c in self._couples if c.key() != couple.key()]
        self._refresh()

    def _harvest(self) -> None:
        connus = ({c.key() for c in self._couples}
                  | {c.key() for c in factory()}
                  | {c.key() for c in workshop()})
        ajoutes = 0
        for couple in from_magazine():
            if couple.key() not in connus:
                connus.add(couple.key())
                self._couples.append(Couple(couple.frequency_khz,
                                            couple.pulse_width_ns, 'poste',
                                            'repris du magasin'))
                ajoutes += 1
        self._couples.sort(key=lambda c: c.pulse_width_ns)
        self._refresh()
        self.w_note.setText(f'{ajoutes} couple(s) repris du magasin.')

    def _store(self) -> None:
        save_custom(self._couples)
        self.accept()
