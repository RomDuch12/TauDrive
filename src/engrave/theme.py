"""Thèmes de TauDrive / TauDrive colour themes.

Une palette décrit **toute** l'application : panneaux, champs, et aussi le
plan de travail. Changer de thème repeint donc la grille, le champ de
marquage et les tracés en même temps que l'interface — sinon le canvas
resterait sombre au milieu d'un thème clair.

**Dix-neuf thèmes**, onze sombres et huit clairs. Le nombre n'est pas
gratuit : un atelier n'a pas le même éclairage qu'un bureau, un écran
n'a pas le même rendu qu'un autre, et l'opérateur qui passe la journée
devant est seul juge de ce qu'il supporte.

Chacun est vérifié au calcul, pas à l'œil : le contraste WCAG du texte
sur son panneau dépasse **7:1** partout, le texte atténué **5:1**, et le
tracé sur son canvas **12:1**. Un thème joli mais illisible ferait rater
une cote.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette


@dataclass(frozen=True)
class Palette:
    """Un thème complet."""
    key: str
    label: str
    dark: bool

    ink: str            # fond le plus profond
    panel: str          # fond des panneaux
    panel_hi: str       # champs, en-têtes
    border: str
    border_hi: str
    text: str
    text_dim: str
    accent: str
    accent_deep: str
    ok: str
    warn: str
    alarm: str

    # --- plan de travail ---
    canvas: str         # fond du canvas
    grid: str           # quadrillage
    field: str          # limite du champ de marquage
    axis: str           # axes
    path: str           # trajectoires
    selected: str       # trajectoire sélectionnée


THEMES: tuple[Palette, ...] = (
    Palette(
        key='ardoise', label='Ardoise (sombre)', dark=True,
        ink='#161a20', panel='#1e232b', panel_hi='#262c36',
        border='#333a46', border_hi='#455063',
        text='#dfe5ee', text_dim='#8a94a6',
        accent='#5ac8fa', accent_deep='#1d5e8c',
        ok='#7bc47f', warn='#d8b25a', alarm='#f08080',
        canvas='#1c2026', grid='#343a44', field='#464e5a',
        axis='#6e7887', path='#e2e8f0', selected='#60c8ff',
    ),
    Palette(
        key='atelier', label='Atelier (clair)', dark=False,
        ink='#eef1f5', panel='#f6f8fa', panel_hi='#ffffff',
        border='#ccd3dd', border_hi='#aab4c2',
        text='#1e232b', text_dim='#5d6875',
        accent='#0a6ebd', accent_deep='#0a6ebd',
        ok='#1d7a3a', warn='#8a5f00', alarm='#b3261e',
        canvas='#fbfcfd', grid='#dde3ea', field='#9aa5b3',
        axis='#7c8797', path='#2b323c', selected='#0a6ebd',
    ),
    Palette(
        key='ambre', label='Ambre (atelier sombre)', dark=True,
        ink='#17140f', panel='#201c15', panel_hi='#2a251c',
        border='#3d3527', border_hi='#544937',
        text='#efe6d6', text_dim='#a1937c',
        accent='#f0a830', accent_deep='#8a5a10',
        ok='#9bbf6a', warn='#e0c15a', alarm='#e07a5f',
        canvas='#1b1710', grid='#3a3226', field='#564a37',
        axis='#7d6f57', path='#f2e9d8', selected='#ffbe4d',
    ),
    Palette(
        key='contraste', label='Contraste élevé', dark=True,
        ink='#000000', panel='#0d0d0d', panel_hi='#1a1a1a',
        border='#4d4d4d', border_hi='#808080',
        text='#ffffff', text_dim='#c0c0c0',
        accent='#00e5ff', accent_deep='#006b7a',
        ok='#3cff7a', warn='#ffd400', alarm='#ff4d4d',
        canvas='#000000', grid='#333333', field='#808080',
        axis='#b0b0b0', path='#ffffff', selected='#00e5ff',
    ),

    # ---------------------------------------------------------------------
    # Sombres
    # ---------------------------------------------------------------------
    Palette(
        key='nuit', label='Nuit (sombre)', dark=True,
        ink='#0d1220', panel='#141b2d', panel_hi='#1c2439',
        border='#2a3450', border_hi='#3b4a6f',
        text='#dde4f2', text_dim='#8b96b0',
        accent='#7aa2f7', accent_deep='#2c4a8f',
        ok='#7fd08a', warn='#e0bb63', alarm='#f28b82',
        canvas='#101627', grid='#293351', field='#42527d',
        axis='#6978a3', path='#e4eaf6', selected='#9ab8ff',
    ),
    Palette(
        key='graphite', label='Graphite (sombre)', dark=True,
        ink='#141414', panel='#1c1c1c', panel_hi='#252525',
        border='#383838', border_hi='#4f4f4f',
        text='#e3e3e3', text_dim='#949494',
        accent='#9e9e9e', accent_deep='#5a5a5a',
        ok='#8bc48f', warn='#d4b45c', alarm='#e88a80',
        canvas='#181818', grid='#333333', field='#4c4c4c',
        axis='#6f6f6f', path='#ededed', selected='#c8c8c8',
    ),
    Palette(
        key='foret', label='Forêt (sombre)', dark=True,
        ink='#101710', panel='#172018', panel_hi='#1e2a20',
        border='#2c3b2f', border_hi='#3e5342',
        text='#dde7dd', text_dim='#8aa08d',
        accent='#6fcf7f', accent_deep='#2a6b39',
        ok='#8fd89a', warn='#d8c162', alarm='#ec8b7f',
        canvas='#121a13', grid='#2a3a2d', field='#41573f',
        axis='#6b8570', path='#e6efe6', selected='#8ce69c',
    ),
    Palette(
        key='prune', label='Prune (sombre)', dark=True,
        ink='#16111d', panel='#1e1728', panel_hi='#281f34',
        border='#3a2f4b', border_hi='#503f66',
        text='#e6dff0', text_dim='#9c8fb2',
        accent='#c08cf0', accent_deep='#5f3a90',
        ok='#8fd0a0', warn='#dcbb66', alarm='#f08a9c',
        canvas='#191323', grid='#332a44', field='#4d3f66',
        axis='#7d6c96', path='#ece4f5', selected='#d3a6ff',
    ),
    Palette(
        key='cuivre', label='Cuivre (sombre)', dark=True,
        ink='#191210', panel='#221917', panel_hi='#2d211d',
        border='#43302a', border_hi='#5d443b',
        text='#efe0d8', text_dim='#a89184',
        accent='#e08a54', accent_deep='#8a4a22',
        ok='#a8c47c', warn='#e0bb63', alarm='#ec8570',
        canvas='#1c1512', grid='#3a2c26', field='#5a4238',
        axis='#8a6f60', path='#f3e7df', selected='#ffa666',
    ),
    Palette(
        key='acier', label='Acier (sombre)', dark=True,
        ink='#111619', panel='#182025', panel_hi='#1f2a30',
        border='#2e3c44', border_hi='#41535e',
        text='#dce6ec', text_dim='#8a9aa6',
        accent='#5fb8d4', accent_deep='#1f5c76',
        ok='#7cc98f', warn='#d6b95e', alarm='#ea8a80',
        canvas='#141b1f', grid='#2b3841', field='#43555f',
        axis='#6e8390', path='#e6eef3', selected='#7fd4f0',
    ),
    Palette(
        key='carbone', label='Carbone (sombre)', dark=True,
        ink='#0a0c0d', panel='#111416', panel_hi='#181c1f',
        border='#282e32', border_hi='#3a4348',
        text='#dfe4e7', text_dim='#828c92',
        accent='#00c2a8', accent_deep='#00655a',
        ok='#5fcf94', warn='#d1b356', alarm='#e87f77',
        canvas='#0d1012', grid='#232a2e', field='#3a4449',
        axis='#5f6d74', path='#e8edf0', selected='#2ae0c4',
    ),
    Palette(
        key='calque', label='Bleu de calque (sombre)', dark=True,
        ink='#0b1f36', panel='#0f2a47', panel_hi='#143458',
        border='#1e4a78', border_hi='#2c6396',
        text='#dbe9f7', text_dim='#8aa9c8',
        accent='#ffffff', accent_deep='#2c6396',
        ok='#8fd6a8', warn='#e6c96a', alarm='#f4938c',
        canvas='#0d2540', grid='#1a4470', field='#3d7ab5',
        axis='#5f92c4', path='#ffffff', selected='#ffd76a',
    ),

    # ---------------------------------------------------------------------
    # Clairs
    # ---------------------------------------------------------------------
    Palette(
        key='papier', label='Papier (clair)', dark=False,
        ink='#f2efe9', panel='#faf8f4', panel_hi='#ffffff',
        border='#d8d2c7', border_hi='#b8b0a2',
        text='#25211c', text_dim='#655e52',
        accent='#8a5a10', accent_deep='#8a5a10',
        ok='#1d7a3a', warn='#8a6100', alarm='#b3261e',
        canvas='#fdfcf9', grid='#e4ded2', field='#a49a89',
        axis='#8a8172', path='#2e2a24', selected='#8a5a10',
    ),
    Palette(
        key='lin', label='Lin (clair)', dark=False,
        ink='#efe9e0', panel='#f8f3ec', panel_hi='#fffcf7',
        border='#d5cbbc', border_hi='#b5a894',
        text='#2a241c', text_dim='#6b6154',
        accent='#a05a2c', accent_deep='#a05a2c',
        ok='#2b7a45', warn='#8a6300', alarm='#b02a20',
        canvas='#fcf9f4', grid='#e2d9cb', field='#a5987f',
        axis='#8b8271', path='#332d24', selected='#a05a2c',
    ),
    Palette(
        key='craie', label='Craie (clair)', dark=False,
        ink='#eceff2', panel='#f5f7f9', panel_hi='#ffffff',
        border='#ccd2d9', border_hi='#a9b2bd',
        text='#1f242a', text_dim='#5b646e',
        accent='#3a5a7a', accent_deep='#3a5a7a',
        ok='#1d7a3a', warn='#8a6300', alarm='#b3261e',
        canvas='#fbfcfd', grid='#dde2e8', field='#98a3af',
        axis='#7b8590', path='#282e35', selected='#3a5a7a',
    ),
    Palette(
        key='azur', label='Azur (clair)', dark=False,
        ink='#e6eef6', panel='#f2f7fb', panel_hi='#ffffff',
        border='#c3d4e3', border_hi='#9db4c9',
        text='#152531', text_dim='#4f6373',
        accent='#0a6ebd', accent_deep='#0a6ebd',
        ok='#0f7a45', warn='#8a6300', alarm='#b3261e',
        canvas='#fafdff', grid='#d6e4ef', field='#8fa8bd',
        axis='#6e8798', path='#1d2c38', selected='#0a6ebd',
    ),
    Palette(
        key='menthe', label='Menthe (clair)', dark=False,
        ink='#e7f1ea', panel='#f2f9f4', panel_hi='#ffffff',
        border='#c6d9cc', border_hi='#a2bcab',
        text='#16261c', text_dim='#4e6456',
        accent='#0f7a45', accent_deep='#0f7a45',
        ok='#0f7a45', warn='#8a6300', alarm='#b3261e',
        canvas='#fafdfb', grid='#d8e7dd', field='#94ad9d',
        axis='#728a7b', path='#1c2d22', selected='#0f7a45',
    ),
    Palette(
        key='sable', label='Sable (clair)', dark=False,
        ink='#f0ead9', panel='#f8f4e8', panel_hi='#fffdf6',
        border='#d9cfb4', border_hi='#b9ab8a',
        text='#2b2718', text_dim='#69614a',
        accent='#8a5f00', accent_deep='#8a5f00',
        ok='#2b7a45', warn='#8a5f00', alarm='#b02a20',
        canvas='#fdfbf3', grid='#e6dcc3', field='#a89a78',
        axis='#8b8060', path='#34301f', selected='#8a5f00',
    ),
    Palette(
        key='contraste-clair', label='Contraste élevé (clair)', dark=False,
        ink='#ffffff', panel='#ffffff', panel_hi='#f0f0f0',
        border='#000000', border_hi='#404040',
        text='#000000', text_dim='#303030',
        accent='#0000cc', accent_deep='#0000cc',
        ok='#006600', warn='#7a4d00', alarm='#cc0000',
        canvas='#ffffff', grid='#c0c0c0', field='#000000',
        axis='#404040', path='#000000', selected='#0000cc',
    ),
)

_BY_KEY = {p.key: p for p in THEMES}
DEFAULT = THEMES[0].key

_current: Palette = THEMES[0]


def current() -> Palette:
    return _current


def get(key: str) -> Palette:
    return _BY_KEY.get(key, THEMES[0])


def names() -> list[tuple[str, str]]:
    """(clé, libellé) de chaque thème, pour l'interface."""
    return [(p.key, p.label) for p in THEMES]


# --- rétro-compatibilité : quelques modules lisent ces constantes ----------
ACCENT = THEMES[0].accent
OK = THEMES[0].ok
WARN = THEMES[0].warn
ALARM = THEMES[0].alarm
TEXT_DIM = THEMES[0].text_dim


def tidy_form(form) -> None:
    """Règle un QFormLayout pour tenir dans un panneau étroit.

    Les champs s'étirent, et une ligne trop longue passe le champ sous son
    libellé plutôt que de déborder hors du panneau.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFormLayout
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(6)


def qt_palette(p: Palette) -> QPalette:
    q = QPalette()
    q.setColor(QPalette.Window, QColor(p.panel))
    q.setColor(QPalette.WindowText, QColor(p.text))
    q.setColor(QPalette.Base, QColor(p.panel_hi))
    q.setColor(QPalette.AlternateBase, QColor(p.panel))
    q.setColor(QPalette.Text, QColor(p.text))
    q.setColor(QPalette.Button, QColor(p.panel_hi))
    q.setColor(QPalette.ButtonText, QColor(p.text))
    q.setColor(QPalette.Highlight, QColor(p.accent_deep))
    q.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    q.setColor(QPalette.ToolTipBase, QColor(p.panel_hi))
    q.setColor(QPalette.ToolTipText, QColor(p.text))
    q.setColor(QPalette.Disabled, QPalette.Text, QColor(p.text_dim))
    q.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p.text_dim))
    q.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p.text_dim))
    return q


def stylesheet(p: Palette) -> str:
    return f"""
QMainWindow, QWidget {{ background: {p.panel}; color: {p.text};
    font-size: 12px; }}

QToolBar {{ background: {p.ink}; border: none;
    border-bottom: 1px solid {p.border}; padding: 4px 6px; spacing: 2px; }}
QToolBar QToolButton {{ color: {p.text}; padding: 5px 9px;
    border: 1px solid transparent; border-radius: 4px; }}
QToolBar QToolButton:hover {{ background: {p.panel_hi};
    border-color: {p.border_hi}; }}
QToolBar QToolButton:pressed {{ background: {p.accent_deep}; color: #fff; }}
QToolBar::separator {{ background: {p.border}; width: 1px; margin: 4px 6px; }}

QDockWidget {{ color: {p.text}; }}
QDockWidget::title {{ background: {p.ink}; padding: 7px 10px;
    border-bottom: 1px solid {p.border}; font-weight: bold;
    letter-spacing: 0.4px; }}
QDockWidget > QWidget {{ background: {p.panel}; }}
QScrollArea {{ border: none; background: {p.panel}; }}

QGroupBox {{ border: 1px solid {p.border}; border-radius: 6px;
    margin-top: 14px; padding: 10px 8px 8px 8px; background: {p.ink}; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
    left: 10px; padding: 0 6px; color: {p.accent}; font-weight: bold; }}

QLabel {{ background: transparent; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p.panel_hi}; border: 1px solid {p.border};
    border-radius: 4px; padding: 4px 6px;
    selection-background-color: {p.accent_deep}; }}
/* Le champ qui a le focus se voit de loin : deux pixels d'accent au
   lieu d'un. Un seul pixel ne se distinguait pas du
   cadre ordinaire — sur un écran d'atelier, à bout de bras, on ne savait
   pas où l'on tapait. Le rembourrage perd le pixel que la bordure gagne :
   le champ ne change pas de taille, et rien ne saute dans le formulaire. */
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{ border: 2px solid {p.accent};
    padding: 3px 5px; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled {{ background: {p.panel}; color: {p.text_dim};
    border-color: {p.border}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{ image: none;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {p.text_dim}; margin-right: 6px; }}
QComboBox QAbstractItemView {{ background: {p.panel_hi};
    border: 1px solid {p.border_hi};
    selection-background-color: {p.accent_deep}; outline: none; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::down-button {{ background: {p.panel}; border: none;
    width: 15px; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {p.border_hi}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 3px solid transparent; border-right: 3px solid transparent;
    border-bottom: 4px solid {p.text_dim}; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 3px solid transparent; border-right: 3px solid transparent;
    border-top: 4px solid {p.text_dim}; }}

QPushButton {{ background: {p.panel_hi}; border: 1px solid {p.border_hi};
    border-radius: 4px; padding: 5px 12px; }}
QPushButton:hover {{ background: {p.border}; border-color: {p.accent}; }}
QPushButton:pressed {{ background: {p.accent_deep}; color: #fff; }}
QPushButton:disabled {{ background: {p.panel}; color: {p.text_dim};
    border-color: {p.border}; }}

QCheckBox {{ spacing: 6px; background: transparent; }}
QCheckBox::indicator {{ width: 14px; height: 14px;
    border: 1px solid {p.border_hi}; border-radius: 3px;
    background: {p.panel_hi}; }}
QCheckBox::indicator:checked {{ background: {p.accent};
    border-color: {p.accent}; }}

QListWidget, QTableWidget {{ background: {p.ink};
    border: 1px solid {p.border}; border-radius: 4px; outline: none;
    alternate-background-color: {p.panel}; }}
QListWidget::item, QTableWidget::item {{ padding: 4px 6px; }}
QListWidget::item:selected, QTableWidget::item:selected {{
    background: {p.accent_deep}; color: #ffffff; }}
QListWidget::item:hover, QTableWidget::item:hover {{
    background: {p.panel_hi}; }}
QHeaderView::section {{ background: {p.panel_hi}; color: {p.text_dim};
    border: none; border-right: 1px solid {p.border};
    border-bottom: 1px solid {p.border}; padding: 5px 6px;
    font-weight: bold; }}
QTableCornerButton::section {{ background: {p.panel_hi}; border: none; }}

QTabBar::tab {{ background: {p.panel}; color: {p.text_dim};
    border: 1px solid {p.border}; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
    padding: 5px 12px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {p.ink}; color: {p.accent};
    border-color: {p.border_hi}; }}
QTabBar::tab:hover {{ color: {p.text}; }}

QScrollBar:vertical, QScrollBar:horizontal {{ background: {p.panel};
    border: none; width: 10px; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {p.border_hi}; border-radius: 5px;
    min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {p.accent_deep}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page,
QScrollBar::sub-page {{ background: none; border: none; height: 0; width: 0; }}

QStatusBar {{ background: {p.ink}; border-top: 1px solid {p.border};
    color: {p.text_dim}; }}
QStatusBar::item {{ border: none; }}

QToolTip {{ background: {p.panel_hi}; color: {p.text};
    border: 1px solid {p.border_hi}; padding: 4px 6px; }}
QDialog {{ background: {p.panel}; }}
"""


def apply(app, key: str | None = None) -> Palette:
    """Applique un thème. Retourne la palette retenue."""
    global _current, ACCENT, OK, WARN, ALARM, TEXT_DIM
    palette = get(key) if key else _current
    _current = palette

    ACCENT, OK, WARN = palette.accent, palette.ok, palette.warn
    ALARM, TEXT_DIM = palette.alarm, palette.text_dim

    # `setStyle` remplace l'objet de style et invalide tout le cache de
    # feuille de style : appelé à chaque changement de thème, il rendait
    # l'opération dix fois plus longue. Une fois suffit.
    if app.style() is None or app.style().objectName().lower() != 'fusion':
        app.setStyle('Fusion')
    app.setPalette(qt_palette(palette))
    app.setStyleSheet(stylesheet(palette))

    from . import icons
    icons.clear_cache()
    return palette


#: Taille du texte secondaire, en points.
PETIT_PT = 11


def css(role: str = 'text_dim', taille: int | None = None) -> str:
    """Feuille de style d'un texte, prise dans le thème courant.

    Remplace les couleurs écrites en dur. Elles paraissaient inoffensives
    — un gris moyen se lit à peu près partout — mais elles étaient
    mesurées à **3,06 de contraste sur les huit thèmes clairs**, pour un
    seuil lisible de 4,5. Le texte secondaire y était pâle au point de
    disparaître.

        w.setStyleSheet(theme.css())              gris secondaire
        w.setStyleSheet(theme.css('warn', 11))    avertissement, 11 pt

    Le style est posé à la construction du widget. Un changement de thème
    en cours de session reconstruit les panneaux, ce qui le rejoue.
    """
    palette = current()
    couleur = getattr(palette, role, palette.text_dim)
    if taille is None:
        return f'color:{couleur};'
    return f'color:{couleur}; font-size:{int(taille)}px;'


def hex_of(role: str = 'text_dim') -> str:
    """La couleur d'un rôle, pour un fragment HTML."""
    palette = current()
    return getattr(palette, role, palette.text_dim)

def span(role: str = 'text_dim') -> str:
    """Balise ouvrante d'un fragment coloré, prise dans le thème.

        f'{theme.span("warn")}Attention</span>'

    Rendre la balise entière plutôt que la seule couleur évite d'imbriquer
    des guillemets dans une f-string — ce qui, avant Python 3.12, ne
    compile pas, et se lit mal de toute façon.
    """
    return f'<span style="color:{hex_of(role)}">'
