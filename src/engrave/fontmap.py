"""Faire correspondre le nom d'une police déclarée à un fichier installé.

Un DXF, un SVG ou un PDF déclare une police par son **nom** (`Arial`,
`Helvetica`, un style AutoCAD) — jamais le fichier lui-même. Ce module fait
le pont vers ce que le poste a réellement : `textvec.available_fonts()`.

Quand rien ne correspond, on **ne devine pas en silence**. Le texte est
un contenu du dessin, pas un détail : rendre `Verdana` en trébuchant sur
la première police venue produirait un résultat que personne n'a choisi.
La substitution est donc **mémorisée par nom de police**, une fois
décidée — en interface via `SubstituteDialog`, en ligne de commande ou en
autotest via la police par défaut, sans jamais bloquer un import.
"""
from __future__ import annotations

from . import textvec

#: Correspondances usuelles, des noms de familles PDF/DXF/SVG génériques
#: vers une police Windows presque toujours installée. N'évite pas la
#: substitution explicite ; réduit seulement le nombre de fois où elle
#: est demandée pour un nom aussi courant qu'« Arial ».
COMMON_ALIASES = {
    'arial': 'Arial', 'helvetica': 'Arial', 'arialmt': 'Arial',
    'times new roman': 'Times New Roman', 'times': 'Times New Roman',
    'timesnewromanpsmt': 'Times New Roman',
    'courier new': 'Courier New', 'courier': 'Courier New',
    'couriernewpsmt': 'Courier New',
    'calibri': 'Calibri', 'segoe ui': 'Segoe UI', 'verdana': 'Verdana',
    'tahoma': 'Tahoma', 'georgia': 'Georgia',
}


def _settings():
    from . import session
    return session.settings()


def _key(nom: str) -> str:
    return f'polices/substitution/{nom.strip().lower()}'


def remembered(nom: str) -> str:
    """Le chemin déjà choisi pour ce nom de police, ou vide."""
    if not nom:
        return ''
    return str(_settings().value(_key(nom)) or '')


def remember(nom: str, chemin: str) -> None:
    """Mémorise un choix — un seul dialogue par nom de police, pour toujours."""
    if nom:
        _settings().setValue(_key(nom), chemin)


def forget(nom: str) -> None:
    if nom:
        _settings().remove(_key(nom))


def _by_family(nom: str) -> str:
    """Cherche `nom` parmi les polices installées, tolérant sur la casse
    et les suffixes de graisse (`Arial Bold`, `Arial,Bold`…)."""
    cible = nom.strip().lower().replace(',', ' ')
    for famille, chemin in textvec.available_fonts():
        f = famille.strip().lower()
        if f == cible or cible.startswith(f) or f.startswith(cible):
            return chemin
    return ''


def cached_ask(ask):
    """Enveloppe `ask` pour qu'un même nom ne soit demandé qu'une fois
    par lecture — décliner (rendre None) compte aussi, sans quoi chaque
    occurrence du même texte redemanderait."""
    vu: dict = {}

    def enveloppe(nom, candidats):
        if nom not in vu:
            vu[nom] = ask(nom, candidats)
        return vu[nom]
    return enveloppe


def resolve(nom: str, *, ask=None) -> tuple[str, bool]:
    """Le chemin d'une police pour le nom déclaré. Rend `(chemin, exact)`.

    `exact` est faux quand on a dû se rabattre sur une substitution ou la
    police par défaut — utile pour compter, dans le compte rendu d'import,
    combien de texte n'a pas eu son vrai visage.

    `ask(nom, candidats) -> chemin | None`, si fourni, est appelé une
    seule fois par nom absent : c'est le point d'entrée du dialogue
    utilisateur. Sans `ask` — ligne de commande, autotest — on retombe
    silencieusement sur un alias connu, puis la police par défaut.
    """
    nom = (nom or '').strip()
    if not nom:
        return (textvec.default_font_path(), False)

    souvenir = remembered(nom)
    if souvenir:
        return (souvenir, True)

    trouve = _by_family(nom)
    if trouve:
        return (trouve, True)

    alias = COMMON_ALIASES.get(nom.lower())
    if alias:
        trouve = _by_family(alias)
        if trouve:
            return (trouve, True)

    if ask is not None:
        candidats = textvec.available_fonts()
        choix = ask(nom, candidats)
        if choix:
            remember(nom, choix)
            return (choix, True)

    return (textvec.default_font_path(), False)


# --------------------------------------------------------------------------
# Le dialogue
# --------------------------------------------------------------------------

class SubstituteDialog:
    """Choisit une police installée à la place d'une police absente.

    Une classe fine, pas un `QDialog` sous-classé : elle sert d'un bloc,
    par `ask_via(parent)`, et n'a pas besoin d'exister au-delà.
    """

    def __init__(self, parent, nom: str, candidats) -> None:
        from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                                       QLabel, QVBoxLayout)
        self._QDialog = QDialog
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle('Police manquante')
        self.dialog.setMinimumWidth(420)

        dehors = QVBoxLayout(self.dialog)
        dehors.addWidget(_riche(
            f'<p>Le dessin utilise la police <b>{nom}</b>, absente de ce '
            f'poste.</p>'
            f'<p>Le texte sera rendu avec la police choisie ci-dessous — '
            f'la forme des lettres change, pas le contenu ni la '
            f'position. Ce choix est <b>mémorisé pour « {nom} »</b> : il ne '
            f'sera plus demandé.</p>'))

        self.combo = QComboBox()
        for famille, chemin in candidats:
            self.combo.addItem(famille, chemin)
        if self.combo.count() == 0:
            dehors.addWidget(QLabel(
                'Aucune police installée : le texte sera vide.'))
        dehors.addWidget(self.combo)

        boutons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        boutons.accepted.connect(self.dialog.accept)
        boutons.rejected.connect(self.dialog.reject)
        dehors.addWidget(boutons)

    def choice(self) -> str:
        """Le chemin choisi, ou vide si annulé."""
        if self.combo.count() == 0:
            return ''
        if self.dialog.exec() != self._QDialog.DialogCode.Accepted:
            return ''
        return str(self.combo.currentData())


def _riche(html: str):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    label = QLabel(html)
    label.setTextFormat(Qt.RichText)
    label.setWordWrap(True)
    return label


def ask_via(parent):
    """Un `ask` prêt pour `resolve()`, qui pose `SubstituteDialog`."""
    def ask(nom, candidats):
        return SubstituteDialog(parent, nom, candidats).choice() or None
    return ask
