"""Import DXF / DXF import.

S'appuie sur **ezdxf** pour lire le fichier, puis aplatit toutes les
entités géométriques en polylignes millimétriques.

Choix de conception :

* **un tracé par calque.** Dans un DXF de production, les calques séparent
  presque toujours ce qui doit être marqué de ce qui doit être découpé.
  Importer calque par calque permet d'affecter une recette différente à
  chacun sans avoir à redécouper la géométrie à la main.
* **les blocs sont éclatés** (`virtual_entities`), y compris imbriqués :
  ce qui est visible dans le DXF est ce qui est gravé.
* **le texte est rendu en contours**, via `textvec` et la police
  déclarée par le style DXF — ou une substitution choisie par
  l'utilisateur si elle n'est pas sur ce poste (voir `fontmap`). La
  forme des lettres peut donc différer de ce que le concepteur voyait ;
  le contenu et la position, non.
"""
from __future__ import annotations

import math
import pathlib
import re

# `ezdxf` n'est chargé qu'à la première lecture d'un DXF : son
# importation coûtait 1,2 s — numpy compris — à **chaque** démarrage de
# TauDrive, la moitié du chargement de l'application, pour un import de
# dessin qui n'arrive pas toujours.
from .geometry import Polyline, bounds
from .model import Path, Recipe, default_recipe
from .avale import avale

#: Facteur de conversion vers le millimètre, par code $INSUNITS.
INSUNITS_TO_MM = {
    0: 1.0,        # sans unité : on suppose des millimètres
    1: 25.4,       # pouces
    2: 304.8,      # pieds
    3: 1609344.0,  # miles
    4: 1.0,        # millimètres
    5: 10.0,       # centimètres
    6: 1000.0,     # mètres
    7: 1e6,        # kilomètres
    # 8 et 9 étaient pris pour des microns et des mils, à 0,0254 et
    # 0,001 : un dessin en mils arrivait 25 fois trop petit, un en
    # micropouces 1 000 fois trop grand. Codes d'AutoCAD, relus sur
    # `ezdxf.units`.
    8: 2.54e-5,    # micropouces
    9: 0.0254,     # mils, millièmes de pouce
    10: 914.4,     # yards
    11: 1e-7,      # ångströms
    12: 1e-6,      # nanomètres
    13: 1e-3,      # microns
    14: 100.0,     # décimètres
    15: 1e4,       # décamètres
    16: 1e5,       # hectomètres
    # au-delà — gigamètres, unités astronomiques, années-lumière,
    # parsecs —, aucun dessin à graver : des millimètres, comme sans unité
}

#: Marque d'empilement d'AutoCAD dans un MTEXT — voir `_mtext_plain`.
BARRE_EMPILEE = '\\S'

#: Le séparateur d'un empilement, et les espaces qui l'entourent.
_RE_EMPILE = re.compile(r'\s*[\^#]\s*')

#: Entités dont on sait extraire un tracé.
GEOMETRIC = ('LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'ELLIPSE',
             'SPLINE', 'HELIX', 'SOLID', 'TRACE', 'HATCH')

#: Entités qui ne portent pas leur géométrie mais renvoient à un bloc.
#: Éclatées comme un INSERT — voir `_iter_entities`.
#:
#: L'ACAD_TABLE est le tableau d'un cartouche : il se développe en ses
#: filets et ses textes de cellule. L'OLE2FRAME n'y est **pas** — c'est
#: un objet incorporé (une image, un tableur), sans géométrie à en
#: tirer ; `ezdxf` ne lui offre d'ailleurs pas `virtual_entities`.
EXPLODED = ('INSERT', 'DIMENSION', 'LEADER', 'MULTILEADER', 'ACAD_TABLE')

#: Points de définition d'une cotation : ils marquent les origines de
#: mesure et ne se gravent **jamais**. AutoCAD ne les trace pas non plus
#: — ils vivent sur un calque `Defpoints` qui n'est pas imprimé. Les
#: compter comme « non géré » ferait un compte rendu bavard et faux.
SILENT = ('POINT', 'VIEWPORT', 'ATTDEF')

#: Entités volontairement ignorées, comptées pour le rapport.
#:
#: Il n'en reste qu'une. TEXT et MTEXT sont rendus en contours ; les
#: cotations, lignes de repère et blocs sont éclatés. L'ATTRIB reste
#: dehors parce qu'il double presque toujours le TEXT visible qui
#: l'accompagne — le graver marquerait la pièce deux fois.
IGNORED_TEXT = ('ATTRIB',)


class DxfError(RuntimeError):
    """Fichier illisible ou sans géométrie exploitable."""


class Cancelled(RuntimeError):
    """L'opérateur a interrompu la lecture en cours.

    Distinct de `DxfError` : rien n'a échoué, on a simplement arrêté. Le
    dire par une exception plutôt que par un retour vide évite d'avoir à
    tester le résultat à chaque étage — et évite surtout d'annoncer
    « fichier illisible » à qui vient de presser *Annuler*.
    """


#: Libellés des unités, pour l'interface.
UNIT_CHOICES = (('millimètre', 1.0), ('centimètre', 10.0),
                ('mètre', 1000.0), ('pouce', 25.4))


class ImportReport:
    """Ce qui a été lu, et ce qui ne l'a pas été."""

    def __init__(self) -> None:
        self.units_mm: float = 1.0
        self.declared_units_mm: float = 1.0
        self.units_overridden: bool = False
        self.layers: dict[str, int] = {}
        self.skipped_text: int = 0
        self.skipped_other: dict[str, int] = {}
        #: Entités **gérées** mais sans longueur — une polyligne d'un seul
        #: sommet, un arc de rayon nul. Elles étaient comptées « non
        #: gérées », ce qui laissait croire qu'un type entier manquait ;
        #: ce sont des points isolés, qui n'ont rien à graver.
        self.skipped_empty: dict[str, int] = {}
        #: Remarques sur la lecture — une cote suspecte, une convention
        #: d'origine qui ne se voit pas dans la géométrie.
        self.notes: list[str] = []
        #: Texte rendu avec une police de substitution plutôt que la
        #: police déclarée : {nom déclaré: nombre d'entités}.
        self.font_substitutions: dict[str, int] = {}
        self.polylines: int = 0
        self.extent: tuple[float, float, float, float] | None = None

    def size_mm(self) -> tuple[float, float]:
        if not self.extent:
            return (0.0, 0.0)
        x1, y1, x2, y2 = self.extent
        return (x2 - x1, y2 - y1)

    def fits(self, field_w: float, field_h: float) -> bool:
        w, h = self.size_mm()
        return w <= field_w and h <= field_h

    def unit_warning(self, field_w: float, field_h: float) -> str:
        """Message si la taille obtenue est manifestement invraisemblable.

        L'en-tête `$INSUNITS` d'un DXF est souvent faux : un fichier tracé
        en millimètres peut se déclarer en mètres. Plutôt que de deviner en
        silence, on signale l'incohérence et on laisse choisir.
        """
        w, h = self.size_mm()
        if self.fits(field_w, field_h):
            return ''
        ratio = max(w / field_w if field_w else 0, h / field_h if field_h else 0)
        message = (f'La géométrie mesure {w:.1f} × {h:.1f} mm, soit '
                   f'{ratio:.0f} fois le champ de marquage '
                   f'({field_w:g} × {field_h:g} mm).')
        for label, factor in UNIT_CHOICES:
            if factor >= self.units_mm:
                continue
            alt_w, alt_h = w * factor / self.units_mm, h * factor / self.units_mm
            if alt_w <= field_w and alt_h <= field_h:
                message += (f'\n\nEn lisant le fichier en {label}s, elle ferait '
                            f'{alt_w:.1f} × {alt_h:.1f} mm — ce qui tiendrait '
                            f'dans le champ.')
                break
        return message

    def summary(self) -> str:
        parts = [f'{self.polylines} polyligne(s)',
                 f'{len(self.layers)} calque(s)']
        if self.extent:
            x1, y1, x2, y2 = self.extent
            parts.append(f'{x2 - x1:.1f} × {y2 - y1:.1f} mm')
        if self.skipped_text:
            parts.append(f'{self.skipped_text} texte(s) ignoré(s)')
        if self.skipped_other:
            total = sum(self.skipped_other.values())
            kinds = ', '.join(sorted(self.skipped_other))
            parts.append(f'{total} entité(s) non gérée(s) : {kinds}')
        if self.skipped_empty:
            vides = sum(self.skipped_empty.values())
            parts.append(f'{vides} tracé(s) sans longueur écarté(s) — '
                         f'points isolés, rien à graver')
        if self.font_substitutions:
            total_sub = sum(self.font_substitutions.values())
            noms = ', '.join(sorted(self.font_substitutions))
            parts.append(f'{total_sub} texte(s) avec une police de '
                         f'substitution ({noms})')
        parts.extend(self.notes)
        return ' · '.join(parts)


def hidden_layers(doc) -> dict[str, str]:
    """Les calques que le logiciel de CAO ne dessine pas, et pourquoi.

    Trois cas, et ils ne disent pas la même chose :

    * **éteint** (`off`) — masqué à l'écran, volontairement ;
    * **gelé** (`frozen`) — masqué et exclu des calculs. C'est là que
      vivent les couches de travail d'AutoCAD, dont
      `*ADSK_ASSOC_ENTITY_BACKUPS`, qui **double** la géométrie
      associative ; la graver marquerait deux fois le même trait ;
    * **non tracé** (`plot = 0`) — visible à l'écran mais jamais
      imprimé. C'est le cas de `Defpoints`, où AutoCAD range les points
      de définition des cotations.

    Dans les trois cas, ce qui s'y trouve n'apparaît pas sur le plan que
    le concepteur a validé. Ce module promet que « ce qui est visible
    dans le DXF est ce qui est gravé » : sans ce relevé, la promesse
    était fausse.
    """
    caches: dict[str, str] = {}
    try:
        calques = list(doc.layers)
    except Exception:                                  # noqa: BLE001
        return caches
    for calque in calques:
        nom = getattr(calque.dxf, 'name', '')
        if not nom:
            continue
        try:
            if not calque.is_on():
                caches[nom] = 'éteint'
            elif calque.is_frozen():
                caches[nom] = 'gelé'
            elif int(calque.dxf.get('plot', 1)) == 0:
                caches[nom] = 'non tracé'
        except Exception as exc:                       # noqa: BLE001
            avale('calque : état illisible', exc)
            continue
    return caches


def _flatten(entity, tolerance: float) -> list[Polyline] | None:
    """Polylignes d'une entité, dans ses coordonnées d'origine.

    `None` si ezdxf n'a pas su la lire — une SPLINE aux points de
    contrôle trop peu nombreux pour son degré. À ne pas confondre avec
    une liste vide : l'entité est lue, mais n'a aucune longueur. La
    première est un dessin perdu, que le bilan doit montrer ; la
    seconde, un point isolé sans conséquence.
    """
    from ezdxf import path as ezpath
    out: list[Polyline] = []
    try:
        p = ezpath.make_path(entity)
        sommets = p.control_vertices()
        # une cote démesurée ou infinie — un fichier abîmé — se
        # discrétiserait en milliards de points, et la lecture ne
        # finirait pas : l'entité est tenue pour illisible, et le bilan
        # le montre
        if any(_demesure(v.x) or _demesure(v.y) for v in sommets):
            return None
        # une **courbe** au point NaN — cercle, arc, ellipse, spline — ne
        # se discrétise pas : ezdxf tourne sans fin sans rendre la main,
        # et ni la barre de progression ni Annuler n'y peuvent rien. Une
        # suite de segments passe : `assainir` la coupera au point NaN
        if p.has_curves and not all(math.isfinite(v.x) and math.isfinite(v.y)
                                    for v in sommets):
            return None
        for sub in p.sub_paths() or [p]:
            points = [(v.x, v.y) for v in sub.flattening(tolerance)]
            if len(points) >= 2:
                out.append(points)
    except (ValueError, TypeError, AttributeError):
        return None
    return out


def _dxf_font_name(doc, style_name: str) -> str:
    """Le nom de police porté par un style DXF, ou le style lui-même.

    Un style AutoCAD référence un fichier — `.shx` la plupart du temps,
    une police vectorielle propre à AutoCAD, ou `.ttf` quand le dessin
    vient d'un logiciel qui a laissé Windows fournir les polices. Un
    `.shx` n'est jamais installé sur ce poste : `fontmap` s'en remettra
    au nom du style, puis à la substitution.
    """
    try:
        style = doc.styles.get(style_name)
    except Exception:
        style = None
    fichier = getattr(getattr(style, 'dxf', None), 'font', '') if style else ''
    if fichier and fichier.lower().endswith(('.ttf', '.ttc', '.otf')):
        return pathlib.Path(fichier).stem
    return style_name or 'Standard'


def _mtext_plain(entity) -> str:
    """Le texte d'un MTEXT, empilements de tolérance compris.

    AutoCAD empile une tolérance avec `\\S+0,06^+0,02;` : le premier
    terme au-dessus du second, en demi-hauteur. Aplati, cela sort
    `+0,06^+0,02` — le `^` est un **code de contrôle**, et il ne veut
    rien dire pour qui lit le plan.

    On le rend en `+0,06/+0,02`, la forme en ligne conventionnelle d'une
    tolérance sur un dessin technique. Empiler vraiment demanderait deux
    demi-lignes et un calcul de position ; sur quatre occurrences d'un
    plan, la barre oblique dit la même chose et se lit.

    Le remplacement ne s'applique **que** si le fichier portait un
    empilement : sans cela, un accent circonflexe tapé à la main dans un
    texte deviendrait une barre oblique.
    """
    try:
        plat = entity.plain_text()
    except Exception:                                  # noqa: BLE001
        return getattr(entity, 'text', '') or ''
    brut = getattr(entity, 'text', '') or ''
    if BARRE_EMPILEE in brut:
        plat = _RE_EMPILE.sub('/', plat)
    return plat


def _text_polylines(entity, kind: str, tolerance: float, doc,
                    ask, report) -> list[Polyline]:
    """Contours d'un TEXT ou MTEXT, dans les unités du dessin.

    Rendu par `textvec`, avec la police déclarée par le style — ou une
    substitution si elle n'est pas sur ce poste (voir `fontmap`). La
    position suit l'ancrage DXF (alignement horizontal pour TEXT, les
    neuf points d'ancrage pour MTEXT) ; l'habillage automatique d'un
    MTEXT trop large n'est **pas** reproduit, faute d'un moteur de mise
    en page complet — le texte sort sur une seule ligne par retour
    explicite du fichier.
    """
    from . import fontmap, textvec
    import math

    if kind == 'TEXT':
        texte = entity.dxf.get('text', '')
        if not texte.strip():
            return []
        hauteur = entity.dxf.get('height', 0.0) or 0.0
        if hauteur <= 0:
            return []
        style_name = entity.dxf.get('style', 'Standard')
        rotation = entity.dxf.get('rotation', 0.0) or 0.0
        insert = entity.dxf.get('insert', (0.0, 0.0))
        lignes = [texte]
        halign = int(entity.dxf.get('halign', 0) or 0)
        valign = int(entity.dxf.get('valign', 0) or 0)
        col = 'right' if halign == 2 else ('center' if halign in (1, 4) else 'left')
        # Le point d'insertion d'un TEXT ordinaire est **sur sa ligne de
        # base**. Le lecteur y calait le haut des lettres : tout texte
        # tombait d'une hauteur trop bas, sous la cote qu'il annonce.
        # `valign` : 0 ligne de base, 1 bas, 2 milieu, 3 haut ; « Middle »
        # (`halign` 4) centre aussi en hauteur.
        row = {1: 'bottom', 2: 'middle', 3: 'top'}.get(valign, 'baseline')
        if halign == 4:
            row = 'middle'
        # Dès que l'alignement n'est pas gauche / ligne de base, c'est le
        # second point, `align_point`, qui sert de référence — sauf pour
        # « Aligned » et « Fit », qui se rangent entre les deux points.
        if ((halign or valign) and halign not in (3, 5)
                and entity.dxf.hasattr('align_point')):
            insert = entity.dxf.align_point
        pas = hauteur * 1.667
    else:                                              # MTEXT
        texte = _mtext_plain(entity)
        lignes = [l for l in texte.split('\n')]
        if not any(l.strip() for l in lignes):
            return []
        hauteur = entity.dxf.get('char_height', 0.0) or 0.0
        if hauteur <= 0:
            return []
        style_name = entity.dxf.get('style', 'Standard')
        rotation = entity.dxf.get('rotation', 0.0) or 0.0
        insert = entity.dxf.get('insert', (0.0, 0.0))
        point = int(entity.dxf.get('attachment_point', 1) or 1)
        col = 'left' if point in (1, 4, 7) else ('right' if point in (3, 6, 9) else 'center')
        row = 'top' if point <= 3 else ('bottom' if point >= 7 else 'middle')
        facteur = entity.dxf.get('line_spacing_factor', 1.0) or 1.0
        pas = hauteur * 1.667 * facteur

    nom_police = _dxf_font_name(doc, style_name)
    police, exact = fontmap.resolve(nom_police, ask=ask)
    if not exact:
        report.font_substitutions[nom_police] = (
            report.font_substitutions.get(nom_police, 0) + 1)

    # Facteur de largeur et inclinaison d'un TEXT. Un texte condensé
    # (largeur 0,8 est courant en cotation) sortait 25 % trop large, et un
    # texte penché, droit. Ils se lisent **sur l'entité**, 1 et 0 quand
    # elle ne les porte pas : c'est la règle du format. Le style n'en
    # donne que la valeur proposée à la création, que le logiciel de
    # dessin recopie alors dans l'entité. Un MTEXT les porte en codes de
    # mise en forme, ignorés.
    facteur_x, penche = 1.0, 0.0
    if kind == 'TEXT':
        facteur_x = float(entity.dxf.get('width', 1.0) or 1.0)
        penche = float(entity.dxf.get('oblique', 0.0) or 0.0)
    facteur_x = facteur_x if facteur_x > 0 else 1.0
    cisaille = math.tan(math.radians(penche)) if penche else 0.0

    # chaque ligne, posée dans son propre repère puis calée sur le bloc
    largeurs = [textvec.advance_width(l, hauteur, police) * facteur_x
                for l in lignes]
    largeur_bloc = max(largeurs) if largeurs else 0.0
    contours: list[Polyline] = []
    for index, (ligne, largeur) in enumerate(zip(lignes, largeurs)):
        if not ligne.strip():
            continue
        c = textvec.outline(ligne, hauteur, police, tolerance_mm=tolerance)
        if col == 'center':
            dx = (largeur_bloc - largeur) / 2
        elif col == 'right':
            dx = largeur_bloc - largeur
        else:
            dx = 0.0
        dy = -index * pas
        contours.extend([[(x * facteur_x + y * cisaille + dx, y + dy)
                          for x, y in poly] for poly in c])
    if not contours:
        return []

    # décalage du bloc entier pour que le point d'ancrage tombe sur
    # l'origine, avant rotation et translation vers `insert`
    if col == 'center':
        shift_x = -largeur_bloc / 2
    elif col == 'right':
        shift_x = -largeur_bloc
    else:
        shift_x = 0.0
    haut = hauteur                          # approx. hauteur de capitale
    bas = -pas * (len(lignes) - 1) - hauteur * 0.25
    if row == 'baseline':
        shift_y = 0.0
    elif row == 'top':
        shift_y = -haut
    elif row == 'bottom':
        shift_y = -bas
    elif kind == 'TEXT':
        shift_y = -haut / 2                 # milieu des capitales
    else:
        shift_y = -(haut + bas) / 2

    rad = math.radians(rotation)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    ix, iy = float(insert[0]), float(insert[1])
    placed: list[Polyline] = []
    for poly in contours:
        nouveau = []
        for x, y in poly:
            x, y = x + shift_x, y + shift_y
            x, y = x * cos_r - y * sin_r, x * sin_r + y * cos_r
            nouveau.append((x + ix, y + iy))
        placed.append(nouveau)
    return placed


class _WatchedStream:
    """Un flux texte qui compte ce qu'il a lu et se laisse interrompre.

    `ezdxf.readfile` est un appel d'un seul tenant : sur un dessin de cinq
    mégaoctets il occupe trois secondes pendant lesquelles rien ne bouge et
    *Annuler* reste sans effet. Or `ezdxf.read` accepte un flux, et n'en
    demande guère plus qu'un `readline`.

    Ce flux-là compte donc les caractères rendus et le dit, tous les
    256 ko. Le rapport peut lever `Cancelled` : la lecture s'arrête alors
    au beau milieu de l'analyse, ce qui est bien le but.
    """

    #: Un rapport tous les 256 ko : assez fin pour que la barre avance,
    #: assez rare pour ne rien coûter sur des millions de lignes.
    PAS = 256 * 1024

    def __init__(self, fp, taille: int, rapport) -> None:
        self._fp = fp
        self._taille = max(1, taille)
        self._rapport = rapport
        self._lus = 0
        self._prochain = self.PAS

    def readline(self, *args):
        ligne = self._fp.readline(*args)
        self._lus += len(ligne)
        if self._lus >= self._prochain:
            self._prochain = self._lus + self.PAS
            self._rapport(min(1.0, self._lus / self._taille))
        return ligne

    def __iter__(self):
        return self

    def __next__(self):
        ligne = self.readline()
        if not ligne:
            raise StopIteration
        return ligne

    def __getattr__(self, nom):
        return getattr(self._fp, nom)


def _open_document(path, rapport):
    """Ouvre un DXF en rendant des comptes, et en pouvant s'interrompre.

    Retombe sur `ezdxf.readfile` — muet mais sûr — pour un DXF binaire, ou
    si cette version d'ezdxf ne présente pas les fonctions employées ici.
    Le compte rendu est un agrément ; la lecture, non.
    """
    import ezdxf
    chemin = str(path)
    try:
        from ezdxf.filemanagement import dxf_file_info
        from ezdxf.lldxf.validator import is_binary_dxf_file, is_dxf_file
    except ImportError:                     # pragma: no cover - vieux ezdxf
        return ezdxf.readfile(chemin)
    if is_binary_dxf_file(chemin) or not is_dxf_file(chemin):
        return ezdxf.readfile(chemin)
    info = dxf_file_info(chemin)
    taille = pathlib.Path(chemin).stat().st_size
    with open(chemin, mode='rt', encoding=info.encoding,
              errors='surrogateescape') as fp:
        doc = ezdxf.read(_WatchedStream(fp, taille, rapport))
    doc.filename = chemin
    return doc


def _iter_entities(container, depth: int = 0):
    """Parcourt les entités en éclatant les blocs, jusqu'à 8 niveaux.

    Une **cotation est un bloc**, elle aussi. Un DIMENSION ne porte pas
    sa géométrie : il renvoie à un bloc anonyme (`*D7`) qui contient le
    dessin réel — lignes d'attache, ligne de cote, flèches, et le texte
    de la mesure. Il en va de même d'un LEADER et d'un MULTILEADER.

    Les éclater ici plutôt que les traiter à part sert deux choses : le
    texte de cote passe par le rendu de texte comme n'importe quel MTEXT,
    et `<>` y est déjà remplacé par la mesure, `%%C` par le Ø. Les écrire
    à la main aurait demandé de refaire ce calcul, et de le refaire faux.
    """
    for entity in container:
        kind = entity.dxftype()
        if kind in EXPLODED and depth < 8:
            try:
                yield from _iter_entities(entity.virtual_entities(), depth + 1)
            except Exception:
                pass                       # bloc non résoluble : ignoré
            continue
        yield entity


def read(path: str | pathlib.Path, *, tolerance_mm: float = 0.02,
         units_mm: float | None = None, progress=None, ask=None
         ) -> tuple[dict[str, list[Polyline]], ImportReport]:
    """Lit un DXF. Retourne ({calque: polylignes}, rapport).

    Les coordonnées sont converties en millimètres selon `$INSUNITS`, sauf
    si `units_mm` impose un facteur — l'en-tête des DXF étant fréquemment
    faux, cette échappatoire est nécessaire.

    `progress(fraction, texte)` est appelé au fil de la lecture ; s'il rend
    `False`, `Cancelled` est levée. Un dessin de dix mégaoctets demande
    plusieurs secondes : sans reddition de comptes, l'application paraît
    plantée, et sans sortie, elle l'est.

    `ask(nom, candidats)` — voir `fontmap.resolve` — est appelé si un
    TEXT ou MTEXT déclare une police absente du poste. Sans `ask`, la
    substitution retombe silencieusement sur un alias connu ou la police
    par défaut.

    Les deux moitiés du travail — l'analyse du fichier puis
    l'aplatissement des entités — pèsent à peu près autant, et toutes deux
    rendent des comptes : la première à travers le flux surveillé, la
    seconde entité par entité.
    """
    def avance(part: float, texte: str) -> None:
        if progress is not None and progress(part, texte) is False:
            raise Cancelled(texte)

    import ezdxf
    avance(0.0, 'ouverture du fichier…')
    try:
        doc = _open_document(
            path, lambda part: avance(0.4 * part, 'lecture du fichier…'))
    except (OSError, ezdxf.DXFError) as exc:
        raise DxfError(f'lecture impossible : {exc}') from exc
    except Cancelled:
        raise
    except Exception as exc:                           # noqa: BLE001
        # un fichier tronqué fait trébucher ezdxf lui-même — un
        # `StopIteration` au milieu de l'en-tête : c'est un refus, dit
        raise DxfError(f'fichier illisible, sans doute abîmé '
                       f'({type(exc).__name__})') from exc
    avance(0.4, 'analyse des entités…')

    report = ImportReport()
    code = doc.header.get('$INSUNITS', 4)
    report.declared_units_mm = INSUNITS_TO_MM.get(code, 1.0)
    if units_mm is None:
        report.units_mm = report.declared_units_mm
    else:
        report.units_mm = units_mm
        report.units_overridden = (units_mm != report.declared_units_mm)
    scale = report.units_mm

    # la tolérance d'aplatissement est exprimée en mm : on la ramène
    # aux unités du fichier avant de la passer à ezdxf
    tolerance = max(tolerance_mm / scale, 1e-6)

    from . import fontmap
    ask_une_fois = fontmap.cached_ask(ask) if ask is not None else None

    # ce que la CAO ne dessine pas : relevé une fois, consulté à chaque
    # entité — voir `hidden_layers`
    caches = hidden_layers(doc)
    sautes: dict[str, int] = {}

    layers: dict[str, list[Polyline]] = {}
    # Dénominateur pris sur l'espace objet, sans éclater les blocs :
    # les compter d'abord coûterait le prix de l'import une seconde fois.
    # Un dessin fait d'INSERT dépassera donc les 100 % — la fraction est
    # bornée, la barre continue d'avancer, et personne n'y perd.
    attendu = max(1, len(doc.modelspace()))
    for rang, entity in enumerate(_iter_entities(doc.modelspace())):
        if rang % 64 == 0:
            avance(0.4 + 0.55 * min(1.0, rang / attendu),
                   f'{rang} entités lues')
        kind = entity.dxftype()
        # un calque que la CAO ne dessine pas ne se grave pas non plus :
        # le contrôle vient avant tout le reste, texte compris
        calque_ent = getattr(entity.dxf, 'layer', '0') or '0'
        if calque_ent in caches:
            sautes[calque_ent] = sautes.get(calque_ent, 0) + 1
            continue
        if kind in ('TEXT', 'MTEXT'):
            polylines = _text_polylines(entity, kind, tolerance, doc,
                                        ask_une_fois, report)
            if not polylines:
                report.skipped_text += 1
                continue
            layer = getattr(entity.dxf, 'layer', '0') or '0'
            scaled = [[(x * scale, y * scale) for x, y in poly]
                      for poly in polylines]
            layers.setdefault(layer, []).extend(scaled)
            continue
        if kind in SILENT:
            continue
        if kind in IGNORED_TEXT:
            report.skipped_text += 1
            continue
        if kind not in GEOMETRIC:
            report.skipped_other[kind] = report.skipped_other.get(kind, 0) + 1
            continue
        polylines = _flatten(entity, tolerance)
        if polylines is None:
            # illisible : un dessin perdu, montré comme tel
            report.skipped_other[kind] = report.skipped_other.get(kind, 0) + 1
            continue
        if not polylines:
            report.skipped_empty[kind] = report.skipped_empty.get(kind, 0) + 1
            continue
        layer = getattr(entity.dxf, 'layer', '0') or '0'
        scaled = [[(x * scale, y * scale) for x, y in poly]
                  for poly in polylines]
        layers.setdefault(layer, []).extend(scaled)

    # avant les comptes du bilan, pour qu'ils soient justes ; et avant le
    # refus d'un fichier vide, qu'un fichier tout entier abîmé devient
    lus = bool(layers)
    layers = assainir_calques(layers, report)
    if not layers:
        raise DxfError(ILLISIBLE if lus else
                       'aucune géométrie exploitable dans ce fichier')

    for nom, combien in sorted(sautes.items()):
        report.notes.append(f'calque « {nom} » {caches[nom]} : '
                            f'{combien} entité(s) non importée(s)')
    avance(0.95, 'mesure de l\'emprise…')
    report.layers = {name: len(polys) for name, polys in layers.items()}
    report.polylines = sum(report.layers.values())
    report.extent = bounds([p for polys in layers.values() for p in polys])
    avance(1.0, 'terminé')
    return layers, report


def to_shapes(path: str | pathlib.Path, *, recipe: Recipe | None = None,
              tolerance_mm: float = 0.02, center: bool = True,
              units_mm: float | None = None, progress=None, ask=None
              ) -> tuple[list[Path], ImportReport]:
    """Lit un DXF et en fait des formes `Path`, une par calque.

    `center=True` recentre l'ensemble sur l'origine du plan de travail, en
    conservant les positions relatives des calques entre eux.
    """
    layers, report = read(path, tolerance_mm=tolerance_mm,
                          units_mm=units_mm, progress=progress, ask=ask)
    recipe = recipe or default_recipe()
    source = pathlib.Path(path).name

    dx = dy = 0.0
    if center and report.extent:
        x1, y1, x2, y2 = report.extent
        dx, dy = -(x1 + x2) / 2, -(y1 + y2) / 2

    shapes: list[Path] = []
    for layer, polylines in sorted(layers.items()):
        shapes.append(Path(
            polylines=[[(x + dx, y + dy) for x, y in poly]
                       for poly in polylines],
            recipe=recipe, source=source, layer=layer))
    return shapes, report


#: Au-delà, une coordonnée n'est plus une cote : mille kilomètres. Les
#: plans de géomètre, très loin de leur origine, restent bien en deçà.
COTE_ABSURDE_MM = 1e9

#: Refus d'un fichier dont `assainir` n'a rien laissé. Sans lui, l'import
#: rendait une forme sans tracé, et le dialogue tombait en la mesurant.
ILLISIBLE = ('aucun point lisible : toutes les cotes de ce fichier sont '
            'non numériques, infinies ou démesurées. Il est sans doute '
            'abîmé — le réexporter depuis le logiciel qui l\'a produit')


def _cote(x, y) -> bool:
    return (math.isfinite(x) and math.isfinite(y)
            and abs(x) <= COTE_ABSURDE_MM and abs(y) <= COTE_ABSURDE_MM)


def _demesure(v: float) -> bool:
    """Infinie, ou au-delà de `COTE_ABSURDE_MM` ; NaN ne l'est pas."""
    return abs(v) > COTE_ABSURDE_MM


def assainir(polylines: list, report: ImportReport) -> list:
    """Écarte les points qui ne sont pas des cotes — NaN, infini, ou au-delà
    de `COTE_ABSURDE_MM` — en coupant le tracé là où ils étaient.

    Un fichier abîmé — un PostScript tronqué, un SVG au nombre illisible —
    rendait de tels points, qui passaient jusqu'au hachurage : il tombait
    à la première rangée, et l'emprise faite de NaN décentrait tout le
    dessin. L'écart est noté dans le compte rendu, l'emprise recalculée.
    Un fichier sain repart **tel quel**, sans rien recopier.
    """
    if all(_cote(x, y) for poly in polylines for x, y in poly):
        return polylines
    sortie, ecartes = [], 0
    for poly in polylines:
        morceau = []
        for x, y in poly:
            if _cote(x, y):
                morceau.append((x, y))
                continue
            ecartes += 1
            if len(morceau) >= 2:
                sortie.append(morceau)
            morceau = []
        if len(morceau) >= 2:
            sortie.append(morceau)
    report.notes.append(
        f'{ecartes} point(s) illisible(s) écarté(s) — valeur non '
        f'numérique, infinie ou démesurée : le fichier est sans doute '
        f'abîmé')
    report.extent = bounds(sortie) if sortie else None
    return sortie


def assainir_calques(layers: dict, report: ImportReport) -> dict:
    """`assainir`, calque par calque ; l'emprise est celle de l'ensemble."""
    if all(_cote(x, y) for polys in layers.values()
           for poly in polys for x, y in poly):
        return layers
    notes = len(report.notes)
    sains = {nom: assainir(polys, report) for nom, polys in layers.items()}
    # une note pour tout le fichier, pas une par calque
    ecartes = sum(int(n.split(' ', 1)[0]) for n in report.notes[notes:])
    del report.notes[notes:]
    report.notes.append(
        f'{ecartes} point(s) illisible(s) écarté(s) — valeur non '
        f'numérique, infinie ou démesurée : le fichier est sans doute '
        f'abîmé')
    sains = {nom: polys for nom, polys in sains.items() if polys}
    tous = [poly for polys in sains.values() for poly in polys]
    report.extent = bounds(tous) if tous else None
    return sains


# --- import de tout format vectoriel ---------------------------------------
#
# Le DXF n'est plus le seul format lu. PDF, AI, EPS et CDR passent par
# `vecimport`, dont la signature est la même : l'interface n'a donc pas à
# savoir lequel elle manipule.

#: Tous les formats vectoriels acceptés à l'import.
ALL_SUFFIXES = ('.dxf', '.pdf', '.ai', '.eps', '.ps', '.svg', '.cdr')

#: Filtre de sélecteur de fichiers, commun à tous les points d'entrée.
FILE_FILTER = (
    'Dessins vectoriels (*.dxf *.pdf *.ai *.eps *.ps *.svg *.cdr);;'
    'Dessins DXF (*.dxf);;'
    'Illustrator et PDF (*.ai *.pdf);;'
    'PostScript (*.eps *.ps);;'
    'SVG (*.svg);;'
    'CorelDRAW (*.cdr);;'
    'Tous (*)')


def is_dxf(path) -> bool:
    return pathlib.Path(path).suffix.lower() == '.dxf'


def any_to_shapes(path, *, recipe=None, tolerance_mm: float = 0.02,
                  center: bool = True, units_mm: float | None = None,
                  progress=None, ask=None):
    """Lit n'importe quel format vectoriel accepté.

    Rend `(formes, compte rendu)`, exactement comme `to_shapes`. Les
    erreurs sortent toutes en `DxfError` : l'appelant n'a qu'un type à
    connaître.

    `ask` — voir `fontmap.resolve` — sert au texte rencontré dans le
    fichier dont la police n'est pas sur ce poste.

    `progress` traverse jusqu'au lecteur : le PostScript et le PDF
    consultent le signal tous les `vecimport.POLL_EVERY` jetons, le DXF
    toutes les 64 entités. Un abandon sort en `Cancelled`, jamais en
    `DxfError` — renoncer n'est pas échouer.
    """
    if is_dxf(path):
        return to_shapes(path, recipe=recipe, tolerance_mm=tolerance_mm,
                         center=center, units_mm=units_mm, progress=progress,
                         ask=ask)
    if progress is not None and progress(0.0, 'lecture du fichier…') is False:
        raise Cancelled('lecture du fichier')
    from . import vecimport
    try:
        sortie = vecimport.to_shapes(path, recipe=recipe,
                                     tolerance_mm=tolerance_mm,
                                     center=center, units_mm=units_mm,
                                     ask=ask, progress=progress)
    except vecimport.Cancelled:
        # renoncer n'est pas échouer : le dire avec le type que
        # l'appelant attend, sinon « lecture interrompue » s'affiche en
        # rouge comme un fichier illisible
        raise Cancelled('lecture du fichier') from None
    except vecimport.VectorError as exc:
        raise DxfError(str(exc)) from None
    if progress is not None:
        progress(1.0, 'terminé')
    return sortie
