"""Aide contextuelle en barre d'état / Contextual help bar.

Une infobulle flottante a trois défauts sur un poste d'atelier : elle
**recouvre** ce qu'on regardait, elle arrive **après un délai** — le temps
qu'on ait déjà cliqué — et elle **disparaît** dès qu'on bouge d'un pixel.
Sur un écran tactile, elle ne paraît même pas.

L'aide part donc dans un **emplacement dédié de la barre d'état** : elle
s'affiche dès le survol, ne cache rien, et reste lisible le temps qu'on la
lise. Les infobulles flottantes sont supprimées — pas doublées : deux
endroits pour la même information, c'est un de trop.

Le texte d'aide reste écrit là où il l'était, dans `setToolTip()`. Rien à
changer dans les panneaux : le routeur les intercepte au vol. C'est ce qui
rend la reprise possible sur les quelque trois cents infobulles déjà
posées.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QMenu

#: Balises et marques de mise en forme à retirer d'une infobulle.
_TAGS = re.compile(r'<[^>]+>')
_BOLD = re.compile(r'\*\*(.+?)\*\*')

#: Ce qui sépare deux lignes d'une infobulle ramenée sur une seule.
JOIN = '   ·   '

#: Largeur minimale de l'emplacement, en pixels. En dessous, une aide de
#: deux lignes est tronquée avant d'avoir rien dit.
MIN_WIDTH = 320

#: Part de la barre d'état revenant à l'aide.
#:
#: Bornée, et non extensible : laissée libre de s'étendre, l'aide chassait
#: de la barre les mesures du travail — formes, passes, longueur gravée,
#: durée — qui, elles, doivent rester lisibles en permanence.
SHARE = 0.42


def plain(text: str) -> str:
    """Une infobulle ramenée à une ligne lisible.

    Les infobulles sont écrites pour une bulle : plusieurs lignes, parfois
    du gras, parfois du HTML. La barre d'état n'a qu'une ligne — le texte
    est donc mis à plat, sans rien perdre de ce qu'il dit.
    """
    brut = str(text or '')
    brut = brut.replace('<br>', '\n').replace('<br/>', '\n')
    brut = brut.replace('<br />', '\n').replace('</p>', '\n')
    brut = _TAGS.sub('', brut)
    brut = _BOLD.sub(r'\1', brut)
    brut = (brut.replace('&nbsp;', ' ').replace('&amp;', '&')
            .replace('&lt;', '<').replace('&gt;', '>'))
    lignes = [' '.join(l.split()) for l in brut.splitlines()]
    return JOIN.join(l for l in lignes if l)


class HelpLabel(QLabel):
    """L'emplacement d'aide : une ligne, tronquée proprement si besoin.

    Un `QLabel` ordinaire déborde ou force la fenêtre à s'élargir. Celui-ci
    garde le texte entier et n'en peint que ce qui tient, avec une ellipse
    en fin — la barre d'état ne doit jamais commander la largeur de la
    fenêtre.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._full = ''
        self.setMinimumWidth(MIN_WIDTH)
        self.setTextFormat(Qt.PlainText)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def set_help(self, text: str) -> None:
        self._full = plain(text)
        self.setText(self._full)
        self.update()

    def help_text(self) -> str:
        """Le texte entier, avant troncature."""
        return self._full

    def minimumSizeHint(self):
        # sans cela, le texte entier devient la largeur minimale du label,
        # donc celle de la fenêtre
        taille = super().minimumSizeHint()
        taille.setWidth(MIN_WIDTH)
        return taille

    def sizeHint(self):
        """Une part bornée de la barre, jamais toute la barre."""
        taille = super().sizeHint()
        taille.setWidth(self.share_width())
        return taille

    def share_width(self) -> int:
        parent = self.parentWidget()
        large = parent.width() if parent is not None else 0
        return max(MIN_WIDTH, int(large * SHARE))

    def paintEvent(self, event) -> None:
        if not self._full:
            super().paintEvent(event)
            return
        metrique = QFontMetrics(self.font())
        coupe = metrique.elidedText(self._full, Qt.ElideRight,
                                    max(self.width() - 4, 40))
        if coupe != self.text():
            # `setText` seul relancerait un paintEvent : on ne l'appelle
            # que lorsque la troncature change vraiment
            super().setText(coupe)
        super().paintEvent(event)


class HelpRouter(QObject):
    """Détourne les infobulles vers l'emplacement d'aide.

    Posé sur l'application entière : tout ce qui porte un `toolTip`
    l'annonce en barre d'état au survol, et **aucune bulle ne flotte**.

    Le survol est pris sur `Enter` plutôt que sur l'événement `ToolTip` de
    Qt : celui-ci n'arrive qu'après le délai d'infobulle, une seconde
    entière, soit bien après qu'on ait cliqué.
    """

    def __init__(self, label: HelpLabel, parent=None) -> None:
        super().__init__(parent)
        self.label = label
        self._source: QObject | None = None

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()

        if kind == QEvent.ToolTip:
            # la bulle flottante est supprimée, son texte est déjà en
            # barre d'état
            texte = self._tooltip_of(obj)
            if texte:
                self._show(obj, texte)
            return True

        if kind == QEvent.Enter:
            texte = self._tooltip_of(obj)
            if texte:
                self._show(obj, texte)
        elif kind == QEvent.MouseMove and isinstance(obj, QMenu):
            # Dans un menu, c'est l'**action** survolée qui porte l'aide,
            # et non le menu. Prise au mouvement plutôt qu'à l'événement
            # `ToolTip` : celui-ci n'arrive qu'après une seconde, soit
            # après qu'on ait choisi.
            self._show_action(obj, obj.activeAction())
        elif kind in (QEvent.Leave, QEvent.Hide):
            if obj is self._source:
                self._clear()
        elif kind == QEvent.ActionChanged and obj is self._source:
            # un bouton dont l'action change d'infobulle — bascule
            # ouvrir/fermer — doit annoncer la nouvelle
            texte = self._tooltip_of(obj)
            if texte:
                self._show(obj, texte)

        return False

    # -- interne -----------------------------------------------------------

    @staticmethod
    def _tooltip_of(obj) -> str:
        chercher = getattr(obj, 'toolTip', None)
        if chercher is None:
            return ''
        try:
            return str(chercher() or '')
        except TypeError:
            return ''

    def _show_action(self, menu, action) -> None:
        """Aide d'une action de menu, si elle en porte une de son cru.

        Qt fait de l'intitulé l'infobulle par défaut : répéter
        « Enregistrer » sous un bouton *Enregistrer* n'apprend rien, et
        chasserait de l'écran une aide utile.
        """
        if action is None:
            self._clear()
            return
        texte = str(action.toolTip() or '')
        intitule = str(action.text() or '').replace('&', '')
        if not texte or plain(texte) == intitule:
            self._clear()
            return
        self._show(menu, texte)

    def refresh(self, source) -> None:
        """Réaffiche l'aide de `source` si c'est bien elle qu'on survole.

        Un bouton qui bascule — ouvrir puis fermer — change d'infobulle
        sous le curseur : sans cela, la barre garderait l'ancienne
        jusqu'au prochain survol.
        """
        if source is not self._source:
            return
        texte = self._tooltip_of(source)
        if texte:
            self.label.set_help(texte)

    def _show(self, source, texte: str) -> None:
        self._source = source
        self.label.set_help(texte)

    def _clear(self) -> None:
        self._source = None
        self.label.set_help('')


def install(app, label: HelpLabel) -> HelpRouter:
    """Pose le routeur sur l'application et rend l'objet à conserver.

    L'objet **doit** être gardé en vie par l'appelant : un filtre
    d'événements ramassé par le collecteur cesse silencieusement d'agir,
    et l'aide disparaîtrait sans que rien ne l'explique.
    """
    routeur = HelpRouter(label, app)
    app.installEventFilter(routeur)
    return routeur
