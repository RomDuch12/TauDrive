"""Vectorisation de texte / Text outlining.

Convertit une chaîne en contours fermés, à partir d'une police TrueType
lue avec fontTools. Le texte gravé est donc du **contour réel de la
police**, remplissable par hachurage (voir `geometry.hatch`).
"""
from __future__ import annotations

import functools
import logging
import os
import pathlib

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

# Certaines polices système ont des tables légèrement malformées ; fontTools
# les lit quand même mais émet un avertissement par fichier. Sans intérêt ici.
logging.getLogger('fontTools').setLevel(logging.ERROR)
# Le décodeur de la table `name` signale **en erreur** un décalage qu'il
# corrige lui-même — une police de ce poste le déclenche, et la police se
# lit parfaitement. Depuis que la liste se relit quand les dossiers
# changent, ce faux message revenait à chaque relecture.
logging.getLogger('fontTools.ttLib.tables._n_a_m_e').setLevel(
    logging.CRITICAL)

from .geometry import (Polyline, bounds, contours_touch, flatten_cubic,
                       nonzero_contours)
from .avale import avale

WINDOWS_FONTS = pathlib.Path('C:/Windows/Fonts')

#: Polices essayées par défaut, dans l'ordre.
DEFAULT_FONT_CANDIDATES = ('arial.ttf', 'segoeui.ttf', 'calibri.ttf',
                           'consola.ttf', 'DejaVuSans.ttf')

#: Extensions lues. `.ttc` et `.otc` sont des **collections** : un
#: fichier, plusieurs polices — voir `faces`.
FONT_SUFFIXES = ('.ttf', '.otf', '.ttc', '.otc')

#: Séparateur du rang de face dans un chemin de police.
#:
#: Une collection contient plusieurs polices dans un seul fichier :
#: `msgothic.ttc` en porte trois. La première s'adresse par le chemin
#: nu, **exactement comme avant** — les documents déjà enregistrés ne
#: changent pas d'un octet, et une version antérieure de TauDrive les
#: relit. Les suivantes prennent un rang : `msgothic.ttc#2`. Un document
#: qui emploie une de ces faces-là ne se relira pas sur une version
#: antérieure, mais aucune ne pouvait les choisir : le cas ne peut pas
#: venir du passé.
SPEC_SEP = '#'


def spec_of(path, index: int = 0) -> str:
    """Désignation d'une face : le chemin, suivi du rang s'il n'est pas 0."""
    return f'{path}{SPEC_SEP}{index}' if index else str(path)


def split_spec(spec: str) -> tuple[str, int]:
    """`(chemin, rang)` d'une désignation de police."""
    texte = str(spec or '')
    if SPEC_SEP in texte:
        chemin, _, rang = texte.rpartition(SPEC_SEP)
        if rang.isdigit():
            return chemin, int(rang)
    return texte, 0


def font_dirs() -> tuple[pathlib.Path, ...]:
    """Les dossiers où Windows range les polices, ceux qui existent.

    Pas seulement `C:/Windows/Fonts` : une police installée **pour soi
    seul** — ce que fait une installation sans droits d'administrateur,
    et c'est le cas courant sur un poste d'atelier verrouillé — atterrit
    dans le profil de l'utilisateur. Elle n'était alors visible nulle
    part dans TauDrive, alors que tous les autres programmes la
    proposaient.
    """
    dossiers = [WINDOWS_FONTS]
    local = os.environ.get('LOCALAPPDATA', '')
    if local:
        dossiers.append(pathlib.Path(local) / 'Microsoft' / 'Windows'
                        / 'Fonts')
    return tuple(d for d in dossiers if d.is_dir())


def _registry_fonts() -> tuple[pathlib.Path, ...]:
    """Les polices déclarées dans la base de registre.

    C'est **elle** qui fait autorité pour Windows, et non le contenu
    d'un dossier : une police peut être déclarée ailleurs que dans les
    deux dossiers connus. On la lit donc aussi, en lecture seule.
    """
    try:
        import winreg
    except ImportError:
        return ()
    chemin = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'
    trouves: list[pathlib.Path] = []
    for ruche in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            cle = winreg.OpenKey(ruche, chemin)
        except OSError:
            continue
        try:
            for i in range(winreg.QueryInfoKey(cle)[1]):
                try:
                    _, valeur, _ = winreg.EnumValue(cle, i)
                except OSError:
                    continue
                fichier = pathlib.Path(str(valeur))
                if not fichier.is_absolute():
                    fichier = WINDOWS_FONTS / fichier
                if fichier.suffix.lower() in FONT_SUFFIXES:
                    trouves.append(fichier)
        finally:
            winreg.CloseKey(cle)
    return tuple(trouves)


def extra_fonts() -> tuple[pathlib.Path, ...]:
    """Les fichiers de police désignés à la main par l'atelier.

    Une police **reçue avec un dessin** et pas installée — Windows
    n'offre alors que son bouton *Installer*, qui demande des droits —
    se désigne par son fichier. Elle entre dans la liste comme les
    autres, et y reste.
    """
    try:
        from . import session
        brut = session.settings().value('polices/fichiers') or []
    except Exception as exc:                            # noqa: BLE001
        avale('polices : liste du poste illisible', exc)
        return ()
    if isinstance(brut, str):
        brut = [brut]
    return tuple(pathlib.Path(str(x)) for x in brut if str(x))


def faces(path) -> list[tuple[str, str]]:
    """Les polices d'un fichier : `(nom, désignation)`, une par face.

    Un `.ttc` en porte plusieurs — `msgothic.ttc` contient *MS Gothic*,
    *MS UI Gothic* et *MS PGothic*. Seule la première était lue, et les
    autres n'existaient nulle part dans TauDrive.
    """
    chemin = pathlib.Path(path)
    if chemin.suffix.lower() not in ('.ttc', '.otc'):
        return [(_family_name(chemin), str(chemin))]
    try:
        from fontTools.ttLib import TTCollection
        collection = TTCollection(str(chemin), lazy=True)
    except Exception as exc:                            # noqa: BLE001
        avale(f'police : collection {chemin.name} illisible', exc)
        return [(_family_name(chemin), str(chemin))]
    sorties = []
    try:
        for rang, police in enumerate(collection.fonts):
            nom = _name_of(police) or f'{chemin.stem} {rang + 1}'
            sorties.append((nom, spec_of(chemin, rang)))
    finally:
        try:
            collection.close()
        except Exception as exc:                        # noqa: BLE001
            avale('police : collection non refermée', exc)
    return sorties or [(_family_name(chemin), str(chemin))]


class FontNotFound(FileNotFoundError):
    """Aucune police utilisable n'a été trouvée."""


#: Police par défaut, une fois trouvée : chaque texte la demande, et la
#: chercher interrogeait le disque deux fois par texte — le tiers du
#: temps de mise en page d'un numéro de série. `refresh_fonts` l'oublie.
_DEFAUT: list[str] = []


def default_font_path() -> str:
    if _DEFAUT:
        return _DEFAUT[0]
    for name in DEFAULT_FONT_CANDIDATES:
        p = WINDOWS_FONTS / name
        if p.exists():
            _DEFAUT[:] = [str(p)]
            return _DEFAUT[0]
    raise FontNotFound(
        'aucune police par défaut trouvée dans C:/Windows/Fonts ; '
        'indiquez un fichier .ttf explicitement')


def _name_of(font) -> str:
    """Nom lu dans la table `name` d'une police déjà ouverte."""
    best = ''
    try:
        enregistrements = font['name'].names
    except Exception as exc:                            # noqa: BLE001
        avale('police : table de noms absente', exc)
        return ''
    for record in enregistrements:
        # 4 = nom complet, 1 = famille ; on préfère l'anglais
        if record.nameID in (4, 1):
            try:
                value = record.toUnicode().strip()
            except Exception as exc:
                avale('police : nom illisible', exc)
                continue
            if value and (not best or record.nameID == 4):
                best = value
                if record.nameID == 4:
                    break
    return best


def _family_name(path: pathlib.Path) -> str:
    """Nom de famille lu dans la table `name`, sinon le nom de fichier."""
    try:
        font = TTFont(str(path), fontNumber=0, lazy=True)
        best = _name_of(font)
        font.close()
        return best or path.stem
    except Exception:
        return path.stem


_FONTS: tuple[tuple[str, str], ...] = ()
_FONTS_SIG: tuple | None = None
_FONTS_AT: float = 0.0

#: Délai avant de revérifier l'empreinte des dossiers, en secondes.
#:
#: La vérification coûte trois millisecondes — rien, sauf qu'un import
#: DXF appelle `available_fonts` **une fois par texte** : cinq mille
#: cotations paieraient quinze secondes pour surveiller un dossier qui
#: n'a pas bougé. Deux secondes suffisent à voir une police installée
#: pendant que TauDrive tourne, et rendent la boucle d'import gratuite.
RECHECK_S = 2.0


def _signature() -> tuple:
    """Empreinte bon marché de l'état des polices du poste.

    Date de modification et nombre d'entrées de chaque dossier, plus la
    liste désignée à la main. Soixante microsecondes, contre deux
    dixièmes de seconde pour relire tous les fichiers : la liste peut
    donc se vérifier à chaque ouverture d'un formulaire.
    """
    marques = []
    for dossier in font_dirs():
        try:
            marques.append((str(dossier), dossier.stat().st_mtime_ns,
                            sum(1 for _ in dossier.iterdir())))
        except OSError as exc:
            avale(f'polices : {dossier} illisible', exc)
    return tuple(marques) + (tuple(str(f) for f in extra_fonts()),)


def available_fonts(fresh: bool = False) -> tuple[tuple[str, str], ...]:
    """Toutes les polices du poste : `(nom, désignation)`.

    Parcourt les dossiers de polices **et la base de registre**, ouvre
    chaque face des collections, lit le vrai nom dans la table `name`,
    dédoublonne et trie alphabétiquement.

    Le résultat est retenu, mais **plus pour toujours** : une police
    installée pendant que TauDrive tourne n'apparaissait jamais, même en
    rouvrant le formulaire — il fallait relancer le programme, ce que
    personne ne devine. L'empreinte des dossiers est donc vérifiée à
    chaque appel (voir `_signature`), et la liste refaite si elle a
    changé.
    """
    global _FONTS, _FONTS_SIG, _FONTS_AT
    import time
    if not fresh and _FONTS and time.monotonic() - _FONTS_AT < RECHECK_S:
        return _FONTS
    signature = _signature()
    if not fresh and _FONTS_SIG == signature and _FONTS:
        _FONTS_AT = time.monotonic()
        return _FONTS

    fichiers: dict[str, pathlib.Path] = {}

    def retenir(chemin: pathlib.Path) -> None:
        if chemin.suffix.lower() not in FONT_SUFFIXES:
            return
        try:
            if not chemin.is_file():
                return
        except OSError:
            return
        fichiers.setdefault(str(chemin).lower(), chemin)

    for dossier in font_dirs():
        try:
            for chemin in dossier.iterdir():
                retenir(chemin)
        except OSError as exc:
            avale(f'polices : {dossier} non parcouru', exc)
    for chemin in _registry_fonts():
        retenir(chemin)
    for chemin in extra_fonts():
        retenir(chemin)

    seen: dict[str, str] = {}
    for chemin in fichiers.values():
        for nom, designation in faces(chemin):
            # à nom égal, on garde le premier rencontré
            seen.setdefault(nom, designation)
    _FONTS = tuple(sorted(seen.items(), key=lambda kv: kv[0].lower()))
    _FONTS_SIG = signature
    _FONTS_AT = time.monotonic()
    return _FONTS


#: Génération des polices : avance à chaque relecture. Les contours
#: mémorisés ailleurs la retiennent dans leur clé — voir
#: `toolpath.drawing_key` : une police remise à son chemin après coup
#: redessine ses textes, au lieu de garder ceux de la police de repli.
_GENERATION = [0]


def font_generation() -> int:
    """Génération des polices — voir `_GENERATION`."""
    return _GENERATION[0]


def refresh_fonts() -> tuple[tuple[str, str], ...]:
    """Relit les polices du poste, cache vidé. Rend la nouvelle liste."""
    global _FONTS_SIG
    _FONTS_SIG = None
    _GENERATION[0] += 1
    _load.cache_clear()
    measured_cap.cache_clear()
    _GLYPHES.clear()
    _GLYPHES_POINTS[0] = 0
    _DEFAUT.clear()
    return available_fonts(fresh=True)


def add_font_file(path) -> str:
    """Ajoute un fichier de police à ceux du poste. Rend sa désignation.

    Pour une police **reçue et non installée** : on la désigne, elle
    entre dans la liste et y reste. Lève `FontNotFound` si le fichier ne
    se lit pas comme une police — mieux vaut le dire tout de suite que
    de laisser une entrée morte dans la liste.
    """
    chemin = pathlib.Path(path)
    if chemin.suffix.lower() not in FONT_SUFFIXES:
        raise FontNotFound(
            f'{chemin.name} : extension inconnue — attendu '
            + ', '.join(FONT_SUFFIXES))
    try:
        trouvees = faces(chemin)
        TTFont(str(chemin), fontNumber=0, lazy=True).close()
    except Exception as exc:                            # noqa: BLE001
        raise FontNotFound(f'{chemin.name} ne se lit pas comme une '
                           f'police : {exc}') from None
    from . import session
    reglages = session.settings()
    connus = [str(f) for f in extra_fonts()]
    if str(chemin) not in connus:
        connus.append(str(chemin))
        reglages.setValue('polices/fichiers', connus)
    refresh_fonts()
    return trouvees[0][1] if trouvees else str(chemin)


class _ContourPen(BasePen):
    """Collecte les contours d'un glyphe sous forme de polylignes."""

    def __init__(self, glyph_set, tolerance: float) -> None:
        super().__init__(glyph_set)
        self.contours: list[Polyline] = []
        self._current: Polyline = []
        self._tolerance = tolerance

    def _moveTo(self, pt):
        self._flush()
        self._current = [pt]

    def _lineTo(self, pt):
        self._current.append(pt)

    def _curveToOne(self, p1, p2, p3):
        if not self._current:
            self._current = [p1]
        self._current.extend(
            flatten_cubic(self._current[-1], p1, p2, p3, self._tolerance))

    def _closePath(self):
        if self._current and self._current[0] != self._current[-1]:
            self._current.append(self._current[0])
        self._flush()

    def _endPath(self):
        self._flush()

    def _flush(self):
        if len(self._current) > 2:
            self.contours.append(self._current)
        self._current = []


def _cmap_of(font) -> dict:
    """Table de caractères utilisable, **table symbole comprise**.

    `getBestCmap` rend `None` pour une police qui n'a qu'une table
    symbole `(3, 0)` : Symbol, Wingdings, Webdings, Marlett, et surtout
    **AIGDT**, la police de symboles de tolérancement qu'emploient les
    DXF d'AutoCAD. Treize polices de ce poste tombaient ainsi sur une
    exception au premier caractère.

    Ces tables rangent leurs glyphes dans la zone privée : « A » s'y lit
    à `0xF041`. `_glyph_for` essaie les deux.
    """
    try:
        best = font.getBestCmap()
    except Exception as exc:                            # noqa: BLE001
        avale('police : table de caractères illisible', exc)
        best = None
    if best:
        return best
    try:
        tables = font['cmap'].tables
    except Exception as exc:                            # noqa: BLE001
        avale('police : aucune table de caractères', exc)
        return {}
    for voulue in ((3, 0), (1, 0), (0, 3)):
        for table in tables:
            if (table.platformID, table.platEncID) == voulue:
                return dict(table.cmap)
    return dict(tables[0].cmap) if tables else {}


#: Décalage de la zone privée des tables symbole.
SYMBOL_BASE = 0xF000


def _glyph_for(cmap: dict, ch: str):
    """Le glyphe d'un caractère, zone privée des polices symbole comprise."""
    code = ord(ch)
    nom = cmap.get(code)
    if nom is None:
        nom = cmap.get(SYMBOL_BASE + code)
    return nom


#: Polices demandées que ce poste n'a pas : désignation -> raison.
#:
#: Un document porte le **chemin** de sa police. Ouvert sur un autre
#: poste, ce chemin peut ne mener nulle part : le document ne s'ouvrait
#: alors pas du tout, l'exception remontant jusqu'au dessin du plan de
#: travail. Il s'ouvre désormais avec la police par défaut — mais cela
#: **change ce qui sera gravé**, et c'est donc dit : ici, dans le
#: journal des incidents, dans la liste des polices du formulaire, et
#: dans la vérification avant export.
MISSING: dict[str, str] = {}


def missing_fonts() -> dict[str, str]:
    """Les polices demandées et absentes, depuis le lancement."""
    return dict(MISSING)


@functools.lru_cache(maxsize=8)
def _load(font_path: str) -> tuple[TTFont, int, dict]:
    chemin, rang = split_spec(font_path)
    try:
        font = TTFont(chemin, fontNumber=rang, lazy=True)
    except Exception as exc:                            # noqa: BLE001
        defaut = default_font_path()
        if str(font_path) == defaut:
            raise FontNotFound(
                f'police par défaut illisible : {exc}') from None
        MISSING[str(font_path)] = str(exc)
        avale(f'police absente, remplacée par celle par défaut : '
              f'{font_path}', exc)
        return _load(defaut)
    upem = font['head'].unitsPerEm
    return font, upem, _cmap_of(font)


#: Capitales plates, dans l'ordre où l'on mesure la hauteur de capitale.
#: « H » d'abord : c'est la lettre que la norme OpenType désigne pour
#: cela — ni accent, ni panse qui déborde, ni pointe qui dépasse.
CAP_LETTERS = 'HIEXTZ'


@functools.lru_cache(maxsize=256)
def measured_cap(font_path: str) -> float:
    """Hauteur de capitale **mesurée** sur le dessin, en unités de police.

    Rend 0 si la police n'a aucune des capitales de `CAP_LETTERS` — une
    police de symboles, typiquement.
    """
    from fontTools.pens.boundsPen import BoundsPen
    font, _upem, cmap = _load(font_path)
    try:
        glyphes = font.getGlyphSet()
    except Exception as exc:                            # noqa: BLE001
        avale('police : glyphes illisibles', exc)
        return 0.0
    for lettre in CAP_LETTERS:
        nom = cmap.get(ord(lettre))
        if not nom or nom not in glyphes:
            continue
        stylo = BoundsPen(glyphes)
        try:
            glyphes[nom].draw(stylo)
        except Exception as exc:                        # noqa: BLE001
            avale(f'police : « {lettre} » illisible', exc)
            continue
        if stylo.bounds and stylo.bounds[3] > 0:
            return float(stylo.bounds[3])
    return 0.0


def em_ratio(font_path: str = '') -> float:
    """Hauteur de capitale rapportée au cadratin (« em ») de la police.

    TauDrive mesure un texte par sa **hauteur de capitale** ; un SVG
    (`font-size`) ou un PDF (`Tf`) le mesurent par son **cadratin**, la
    boîte entière du corps, accents et jambages compris. Un « H » en Arial
    corps 10 fait 7,16 de haut, pas 10. Prendre l'un pour l'autre rendait
    tout texte importé d'un SVG ou d'un PDF **40 % trop grand**.

    Multiplier une taille de cadratin par ce rapport donne la taille que
    `outline` attend. Hauteur déclarée d'abord, mesurée sinon — voir
    `measured_cap` ; 0,7 en dernier recours, la valeur typique.
    """
    font_path = font_path or default_font_path()
    font, upem, _cmap = _load(font_path)
    try:
        cap = font['OS/2'].sCapHeight or 0
    except (KeyError, AttributeError):
        cap = 0
    if cap <= 0:
        cap = measured_cap(font_path)
    if cap <= 0 or upem <= 0:
        return 0.7
    return cap / upem


def _scale_for(font, upem: float, size_mm: float,
               cap_mesuree: float = 0.0) -> float:
    """Facteur d'échelle calant la hauteur de capitale sur `size_mm`.

    La hauteur de capitale **déclarée** par la police (`sCapHeight`)
    passe en premier : c'est la valeur du dessinateur. Mais elle n'existe
    que depuis la version 2 de la table `OS/2`, et **284 polices sur 489**
    de ce poste ne l'ont pas — Century Gothic parmi elles. On se rabattait
    alors sur la hauteur au-dessus de la ligne de base (`hhea.ascent`),
    qui compte accents et jambages : un texte demandé à 10 mm sortait à
    7,14 mm en Century Gothic, et 254 polices s'écartaient de plus d'un
    demi-millimètre sur dix.

    `cap_mesuree`, si elle est donnée, remplace ce repli par la hauteur
    réellement mesurée sur le « H » — voir `measured_cap`. Elle n'est pas
    donnée pour les textes des documents écrits avant la correction :
    ceux-là gardent leur taille d'origine, voir `Text.cap_measured`.
    """
    try:
        cap = font['OS/2'].sCapHeight or 0
    except (KeyError, AttributeError):
        cap = 0
    if cap <= 0 and cap_mesuree > 0:
        cap = cap_mesuree
    if cap <= 0:
        cap = getattr(font['hhea'], 'ascent', upem * 0.7)
    return size_mm / cap


#: Contours des glyphes déjà dessinés, **en unités de police** :
#: (police, glyphe, tolérance) -> contours.
#:
#: Trois cents plaques numérotées redessinaient trois cents fois les dix
#: mêmes chiffres : 4 200 glyphes tracés à la courbe près pour une
#: sélection, plus d'une seconde. Un glyphe ne dépend que de sa police,
#: de son nom et de la tolérance d'aplatissement — celle-ci suit la
#: taille, d'où une entrée par taille employée. La mise à l'échelle et
#: l'avance se font à la sortie, par **les mêmes opérations** qu'avant :
#: les contours rendus sont identiques au bit près.
_GLYPHES: dict[tuple, tuple] = {}
_GLYPHES_POINTS = [0]
#: Plafond, en points mémorisés : quelques dizaines de mégaoctets.
_GLYPHES_MAX_POINTS = 400_000


def _glyph_contours(font_path: str, glyph_set, name: str,
                    tol_units: float) -> tuple:
    """Contours d'un glyphe en unités de police, mémorisés — voir
    `_GLYPHES`. Une erreur de dessin remonte, et rien n'est retenu."""
    cle = (font_path, name, tol_units)
    contours = _GLYPHES.get(cle)
    if contours is None:
        pen = _ContourPen(glyph_set, tol_units)
        glyph_set[name].draw(pen)
        # une police se remplit en non nul : les traits superposés d'une
        # police variable ne doivent pas se graver en trous — voir
        # `geometry.nonzero_contours`. Payé une fois par glyphe.
        contours = tuple(tuple(c) for c in nonzero_contours(pen.contours))
        poids = sum(len(c) for c in contours)
        # les plus anciens s'en vont d'abord : un dict garde l'ordre
        while _GLYPHES and _GLYPHES_POINTS[0] + poids > _GLYPHES_MAX_POINTS:
            parti = _GLYPHES.pop(next(iter(_GLYPHES)))
            _GLYPHES_POINTS[0] -= sum(len(c) for c in parti)
        _GLYPHES[cle] = contours
        _GLYPHES_POINTS[0] += poids
    return contours


def outline(text: str, size_mm: float, font_path: str = '',
            tolerance_mm: float = 0.02,
            measured: bool = True) -> list[Polyline]:
    """Contours d'**une ligne**, posée sur la ligne de base, début en x = 0.

    Le placement — alignement, interligne — relève de `layout`.
    `measured` : hauteur de capitale mesurée quand la police ne la
    déclare pas — voir `_scale_for`.
    """
    # une taille nulle ou négative — un document abîmé — ne dessine rien,
    # au lieu d'arrêter le calcul sur une division par zéro
    if not text or not size_mm > 0:
        return []
    font_path = font_path or default_font_path()
    font, upem, cmap = _load(font_path)
    scale = _scale_for(font, upem, size_mm,
                       measured_cap(font_path) if measured else 0.0)

    glyph_set = font.getGlyphSet()
    hmtx = font['hmtx']
    tol_units = max(tolerance_mm / scale, 1e-3)

    glyphes: list[list[Polyline]] = []
    pen_x = 0.0
    for ch in text:
        name = _glyph_for(cmap, ch)
        if name is None or name not in glyph_set:
            pen_x += upem * 0.3           # caractère absent : espace
            continue
        glyphes.append([[((x + pen_x) * scale, y * scale) for x, y in c]
                        for c in _glyph_contours(font_path, glyph_set, name,
                                                 tol_units)])
        pen_x += hmtx[name][0]
    return _lier(glyphes)


def _lier(glyphes: list[list[Polyline]]) -> list[Polyline]:
    """Les contours d'une ligne, les lettres qui se chevauchent **fondues**
    en une seule matière.

    Une police de script lie ses lettres en les faisant se recouvrir : sous
    la règle pair-impair, chaque liaison devenait un trou, et le contour de
    chaque lettre se gravait à travers la suivante. Seules les lettres dont
    les emprises se recouvrent sont confrontées, sur la seule zone de
    recouvrement ; une police ordinaire — dont les lettres ne se touchent
    pas — rend ses contours tels quels.
    """
    boites = [bounds(g) for g in glyphes]
    parent = list(range(len(glyphes)))

    def racine(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ordre = sorted((i for i, b in enumerate(boites) if b),
                   key=lambda i: boites[i][0])
    for n, i in enumerate(ordre):
        bi = boites[i]
        for j in ordre[n + 1:]:
            bj = boites[j]
            if bj[0] > bi[2]:
                break
            if bj[1] > bi[3] or bj[3] < bi[1] or racine(i) == racine(j):
                continue
            if contours_touch(glyphes[i], glyphes[j]):
                parent[racine(j)] = racine(i)
    if all(parent[i] == i for i in range(len(parent))):
        return [c for g in glyphes for c in g]
    paquets: dict[int, list[int]] = {}
    for i in range(len(glyphes)):
        paquets.setdefault(racine(i), []).append(i)
    contours: list[Polyline] = []
    for i in range(len(glyphes)):
        membres = paquets.pop(racine(i), None)
        if membres is None:
            continue                      # rendue avec sa première lettre
        if len(membres) == 1:
            contours.extend(glyphes[i])
        else:
            contours.extend(nonzero_contours(
                [c for m in membres for c in glyphes[m]]))
    return contours


def advance_width(text: str, size_mm: float, font_path: str = '',
                  measured: bool = True) -> float:
    """Largeur d'avance d'une ligne, sans la dessiner."""
    if not text:
        return 0.0
    font_path = font_path or default_font_path()
    font, upem, cmap = _load(font_path)
    scale = _scale_for(font, upem, size_mm,
                       measured_cap(font_path) if measured else 0.0)
    hmtx = font['hmtx']
    total = 0.0
    for ch in text:
        name = _glyph_for(cmap, ch)
        total += upem * 0.3 if name is None or name not in hmtx.metrics \
            else hmtx[name][0]
    return total * scale


#: Alignements admis.
HALIGN = ('left', 'center', 'right')
VALIGN = ('top', 'middle', 'baseline', 'bottom')


def layout(text: str, size_mm: float, font_path: str = '',
           align: str = 'center', valign: str = 'middle',
           line_spacing: float = 1.4,
           measured: bool = True) -> list[Polyline]:
    """Contours d'un bloc de texte, éventuellement sur plusieurs lignes.

    * `align` — `left`, `center` ou `right`. C'est à la fois la
      justification des lignes dans le bloc **et l'ancrage du bloc sur
      l'origine** : à gauche, l'origine est le bord gauche du bloc et le
      texte pousse vers la droite ; à droite, l'inverse ; centré, il
      pousse des deux côtés. C'est ce qui fait qu'un texte aligné à
      gauche **garde son bord gauche** quand on le retape plus long — le
      bloc était auparavant toujours centré sur l'origine, et
      l'alignement ne changeait rien à un texte d'une ligne.
    * `valign` — position du bloc par rapport à l'origine :
      `top` (l'origine est le haut du bloc), `middle` (centré),
      `baseline` (ligne de base de la **première** ligne, comme un texte
      simple) ou `bottom`.
    * `line_spacing` — interligne, en multiples de `size_mm`.

    Les lignes vides comptent : elles occupent leur interligne.
    """
    lines = text.split('\n')
    if not any(line.strip() for line in lines):
        return []

    step = size_mm * line_spacing
    widths = [advance_width(line, size_mm, font_path, measured)
              for line in lines]
    block_width = max(widths) if widths else 0.0

    placed: list[Polyline] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        contours = outline(line, size_mm, font_path, measured=measured)
        if not contours:
            continue
        # justification dans le bloc, puis ancrage du bloc : les deux
        # vont ensemble — voir `anchor_shift` pour le second seul
        if align == 'center':
            dx = (block_width - widths[index]) / 2 - block_width / 2
        elif align == 'right':
            dx = -widths[index]
        else:                                    # 'left'
            dx = 0.0
        dy = -index * step
        placed.extend([[(x + dx, y + dy) for x, y in c] for c in contours])

    if not placed:
        return []

    # décalage vertical du bloc selon `valign`
    if valign == 'baseline':
        offset = 0.0
    else:
        ys = [y for c in placed for _, y in c]
        low, high = min(ys), max(ys)
        if valign == 'top':
            offset = -high
        elif valign == 'bottom':
            offset = -low
        else:                                    # 'middle'
            offset = -(low + high) / 2
    if offset:
        placed = [[(x, y + offset) for x, y in c] for c in placed]
    return placed


def anchor_shift(text: str, size_mm: float, font_path: str = '',
                 align: str = 'center', measured: bool = True) -> float:
    """De combien l'ancrage déplace un bloc, par rapport au bloc centré.

    Sert à relire les documents écrits **avant** l'ancrage : ils
    posaient tout bloc centré sur son origine, quel que soit
    l'alignement. Pour qu'un tel texte ne bouge pas à la relecture, son
    origine se décale de cette valeur — négative à gauche, positive à
    droite, nulle au centre. En millimètres, avant étirement.
    """
    if align not in ('left', 'right'):
        return 0.0
    lines = text.split('\n')
    widths = [advance_width(line, size_mm, font_path, measured)
              for line in lines if line.strip()]
    block_width = max(widths) if widths else 0.0
    return -block_width / 2 if align == 'left' else block_width / 2
