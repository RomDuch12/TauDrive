"""Esquisse d'un dessin vectoriel / Lightweight drawing outline.

**Un aperçu ne doit pas coûter un import.** Ouvrir un DXF d'atelier avec
`ezdxf` prend plusieurs secondes : le document entier est reconstruit,
chaque arc aplati à 0,02 mm, chaque bloc éclaté. Sur les dessins livrés
cela va de 1 à 7 secondes *par clic de liste* — et parcourir une
bibliothèque de quelques dizaines de mégaoctets lançait autant de
chargements complets qu'on pressait de fois la flèche du bas.

L'esquisse répond à une question bien plus modeste : **à quoi ce dessin
ressemble-t-il ?** Quelques centaines de pixels n'en demandent pas plus.
Elle traverse donc le fichier une seule fois, en lisant les codes de
groupe au fil de l'eau, et retient les sommets :

* les arcs et les bulges deviennent des cordes — invisible à l'échelle
  d'une vignette ;
* les splines passent par leurs points de contrôle ;
* les blocs sont résolus, leur insertion placée, tournée et mise à
  l'échelle : un plan de production n'est souvent qu'une pile d'`INSERT`,
  et les ignorer donnerait un aperçu vide.

Ce qu'elle rend n'est **pas** de la géométrie à graver : c'est une image.
Le dessin exact reste l'affaire de `dxfimport`, appelé à la demande par
le bouton *Visualiser*, puis par l'insertion.

Les autres formats vectoriels n'ont pas d'équivalent bon marché : ils
passent par leur lecteur habituel, et seulement en deçà d'une taille
raisonnable — au-delà, l'aperçu attend qu'on le demande.
"""
from __future__ import annotations

import math
import pathlib
from dataclasses import dataclass, field

from .geometry import Polyline, bounds
from .model import LONGUEUR_MAX_MM
# le facteur vers le millimètre par code `$INSUNITS` : la table de l'import
# elle-même — une copie en avait gardé les erreurs (EX-256)
from .dxfimport import INSUNITS_TO_MM

#: Au-delà, on ne tente même pas l'esquisse : la taille est annoncée, et
#: c'est *Visualiser* qui décidera d'y consacrer du temps.
MAX_BYTES = 96 * 1024 * 1024

#: Garde-fou sur le nombre de lignes lues. Un DXF qui les dépasse rend une
#: esquisse **partielle**, et le dit.
MAX_LINES = 6_000_000

#: Côtés d'un cercle complet dans l'esquisse. Sur un aperçu de trois cents
#: pixels, un cercle de vingt-quatre côtés et un cercle parfait allument
#: les mêmes pixels.
CIRCLE_SIDES = 24


@dataclass
class Outline:
    """Ce qu'une esquisse rend : des tracés, une emprise, et sa franchise.

    `exact` dit si tout le fichier a été lu. `note` porte ce qu'il faut
    afficher quand il n'y a rien à montrer — un aperçu vide sans
    explication laisse croire que le dessin l'est aussi.
    """
    polys: list[Polyline] = field(default_factory=list)
    bounds: tuple[float, float, float, float] | None = None
    exact: bool = True
    note: str = ''

    def points(self) -> int:
        return sum(len(p) for p in self.polys)

    def __bool__(self) -> bool:
        return bool(self.polys)


# --------------------------------------------------------------------------
# DXF : lecture au fil des codes de groupe
# --------------------------------------------------------------------------

#: Entités dont l'esquisse sait tirer des sommets.
_DRAWN = {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'ELLIPSE',
          'SPLINE', 'HELIX'}

#: Marque interne : un nom de bloc ne peut pas contenir d'octet nul.
_EN_ATTENTE = '\x00bloc-sans-nom'


class _Entity:
    """Les codes d'une entité, empilés jusqu'à ce qu'elle se referme."""

    __slots__ = ('kind', 'x', 'y', 'x2', 'y2', 'nums', 'flags', 'name')

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.x: list[float] = []
        self.y: list[float] = []
        self.x2: list[float] = []
        self.y2: list[float] = []
        self.nums: dict[int, float] = {}
        self.flags = 0
        self.name = ''


def _pairs(lignes: list[str]):
    """Couples (code, valeur) d'un DXF ASCII, lignes vides sautées."""
    i, n = 0, len(lignes) - 1
    while i < n:
        code = lignes[i].strip()
        if code:
            yield code, lignes[i + 1]
            i += 2
        else:
            i += 1


def _num(valeur: str) -> float | None:
    try:
        return float(valeur)
    except ValueError:
        return None


def _arc(cx: float, cy: float, r: float, a1: float, a2: float) -> Polyline:
    pas = max(2, int(CIRCLE_SIDES * (a2 - a1) / math.tau) + 1)
    return [(cx + r * math.cos(a1 + (a2 - a1) * i / pas),
             cy + r * math.sin(a1 + (a2 - a1) * i / pas))
            for i in range(pas + 1)]


def _emit(ent: _Entity, out: list[Polyline]) -> None:
    """Ajoute à `out` le tracé approché d'une entité refermée."""
    kind = ent.kind
    if kind in ('LWPOLYLINE', 'POLYLINE'):
        points = list(zip(ent.x, ent.y))
        if len(points) >= 2:
            if ent.flags & 1 and points[0] != points[-1]:
                points.append(points[0])    # polyligne fermée
            out.append(points)
        return
    if kind == 'LINE':
        if ent.x and ent.y and ent.x2 and ent.y2:
            out.append([(ent.x[0], ent.y[0]), (ent.x2[0], ent.y2[0])])
        return
    if kind in ('CIRCLE', 'ARC'):
        r = ent.nums.get(40, 0.0)
        if not (ent.x and ent.y) or r <= 0:
            return
        if kind == 'CIRCLE':
            a1, a2 = 0.0, math.tau
        else:
            a1 = math.radians(ent.nums.get(50, 0.0))
            a2 = math.radians(ent.nums.get(51, 360.0))
            if a2 <= a1:
                a2 += math.tau
        out.append(_arc(ent.x[0], ent.y[0], r, a1, a2))
        return
    if kind == 'ELLIPSE':
        if not (ent.x and ent.y and ent.x2 and ent.y2):
            return
        cx, cy = ent.x[0], ent.y[0]
        mx, my = ent.x2[0], ent.y2[0]          # demi-grand axe, relatif
        ratio = ent.nums.get(40, 1.0)
        a1, a2 = ent.nums.get(41, 0.0), ent.nums.get(42, math.tau)
        if a2 <= a1:
            a2 += math.tau
        grand = math.hypot(mx, my)
        angle = math.atan2(my, mx)
        ca, sa = math.cos(angle), math.sin(angle)
        pas = max(2, int(CIRCLE_SIDES * (a2 - a1) / math.tau) + 1)
        trace = []
        for i in range(pas + 1):
            t = a1 + (a2 - a1) * i / pas
            u, v = grand * math.cos(t), grand * ratio * math.sin(t)
            trace.append((cx + u * ca - v * sa, cy + u * sa + v * ca))
        out.append(trace)
        return
    if kind in ('SPLINE', 'HELIX'):
        # les points de contrôle, reliés : la courbe passe dedans, ce qui
        # suffit à reconnaître un dessin sur trois cents pixels
        points = list(zip(ent.x, ent.y))
        if len(points) >= 2:
            out.append(points)


def _place(polys: list[Polyline], dx: float, dy: float,
           sx: float, sy: float, rot_deg: float) -> list[Polyline]:
    """Un bloc posé : échelle, puis rotation, puis translation."""
    if sx == 1.0 and sy == 1.0 and rot_deg == 0.0:
        return [[(x + dx, y + dy) for x, y in poly] for poly in polys]
    a = math.radians(rot_deg)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for poly in polys:
        mis = []
        for x, y in poly:
            u, v = x * sx, y * sy
            mis.append((u * ca - v * sa + dx, u * sa + v * ca + dy))
        out.append(mis)
    return out


#: Couples de codes lus entre deux respirations. Voir `dxf_outline`.
BREATH_EVERY = 40_000


def dxf_outline(path: pathlib.Path, respirer=None) -> Outline:
    """Esquisse d'un DXF ASCII, blocs résolus, en millimètres.

    Un seul passage sur le fichier. Les blocs sont mémorisés au vol et les
    `INSERT` de l'espace objet les reposent — sans récursion : un bloc qui
    en insère un autre rend son contenu direct, ce qui suffit à situer le
    dessin.

    `respirer` est appelé tous les `BREATH_EVERY` couples de codes. Il sert
    à **rendre la main** quand l'esquisse tourne dans un fil de fond : un
    fil Python occupé sans interruption garde le verrou de l'interpréteur,
    et la fenêtre reste figée jusqu'à ce qu'il ait fini. Quelques
    millisecondes cédées de loin en loin suffisent à ce que l'interface se
    repeigne pendant qu'on parcourt la bibliothèque.
    """
    try:
        taille = path.stat().st_size
    except OSError as exc:
        return Outline(note=f'Fichier illisible : {exc}')
    if taille > MAX_BYTES:
        return Outline(note=f'{taille / 1e6:.0f} Mo — trop lourd pour un '
                            f'aperçu automatique.\nBouton « Visualiser ».')
    lignes = path.read_bytes().decode('latin-1', 'replace').split('\n')
    tronque = len(lignes) > MAX_LINES
    if tronque:
        del lignes[MAX_LINES:]

    echelle = 1.0
    section = ''
    attend_section = False
    entete = ''
    bloc = ''
    blocs: dict[str, list[Polyline]] = {}
    modele: list[Polyline] = []
    inserts: list[tuple] = []
    ent: _Entity | None = None

    def ranger(fini: _Entity | None) -> None:
        """Referme une entité dans le bon réservoir."""
        if fini is None:
            return
        if fini.kind == 'INSERT':
            if fini.name and fini.x and fini.y and not bloc:
                inserts.append((fini.name, fini.x[0], fini.y[0],
                                fini.nums.get(41, 1.0),
                                fini.nums.get(42, 1.0),
                                fini.nums.get(50, 0.0)))
            return
        _emit(fini, blocs.setdefault(bloc, []) if bloc else modele)

    souffle = BREATH_EVERY
    for code, valeur in _pairs(lignes):
        if respirer is not None:
            souffle -= 1
            if souffle <= 0:
                souffle = BREATH_EVERY
                respirer()
        if code == '0':
            mot = valeur.strip().upper()
            # **`VERTEX` ne referme pas la polyligne en cours.** Un
            # `POLYLINE` DXF n'est qu'un en-tête : ses sommets suivent en
            # entités séparées, jusqu'à `SEQEND`. Les fermer une à une
            # rendrait autant de tracés d'un seul point.
            if mot == 'VERTEX':
                continue
            ranger(ent)
            ent = None
            if mot == 'SECTION':
                attend_section = True
            elif mot == 'ENDSEC':
                section, bloc = '', ''
            elif mot == 'BLOCK':
                bloc = _EN_ATTENTE
            elif mot == 'ENDBLK':
                bloc = ''
            elif mot == 'INSERT':
                ent = _Entity('INSERT')
            elif mot in _DRAWN:
                ent = _Entity(mot)
            continue

        if attend_section and code == '2':
            section, attend_section = valeur.strip().upper(), False
            continue
        if section == 'HEADER':
            if code == '9':
                entete = valeur.strip().upper()
            elif code == '70' and entete == '$INSUNITS':
                echelle = INSUNITS_TO_MM.get(int(_num(valeur) or 0), 1.0)
                entete = ''
            continue
        if bloc == _EN_ATTENTE and code == '2':
            bloc = valeur.strip()
            blocs.setdefault(bloc, [])
            continue
        if ent is None:
            continue
        if code == '2' and ent.kind == 'INSERT':
            ent.name = valeur.strip()
            continue
        nombre = _num(valeur)
        if nombre is None:
            continue
        if code == '10':
            ent.x.append(nombre)
        elif code == '20':
            ent.y.append(nombre)
        elif code == '11':
            ent.x2.append(nombre)
        elif code == '21':
            ent.y2.append(nombre)
        elif code == '70':
            ent.flags = int(nombre)
        elif code in ('40', '41', '42', '50', '51'):
            # le premier gagne : un LWPOLYLINE répète le code 42 (bulge)
            # à chaque sommet, et ce n'est pas un rayon
            ent.nums.setdefault(int(code), nombre)
    ranger(ent)

    traces = list(modele)
    for nom, dx, dy, sx, sy, rot in inserts:
        contenu = blocs.get(nom)
        if contenu:
            traces.extend(_place(contenu, dx, dy, sx or 1.0, sy or 1.0, rot))
    # Un DXF dont tout vit dans des blocs qu'aucun INSERT lisible ne pose
    # vaut mieux esquissé de travers que pas du tout : on montre alors les
    # blocs à leur place de définition.
    if not traces:
        for contenu in blocs.values():
            traces.extend(contenu)

    # Une unité déclarée qui porterait le dessin au-delà de dix mètres est
    # fausse : la bibliothèque le pose alors en millimètres
    # (`drawings.load`), et l'esquisse annonce la même taille.
    b = bounds(traces) if echelle != 1.0 else None
    if b is not None and (max(b[2] - b[0], b[3] - b[1]) * echelle / 2
                          <= LONGUEUR_MAX_MM):
        traces = [[(x * echelle, y * echelle) for x, y in poly]
                  for poly in traces]
    traces = [p for p in traces if len(p) >= 2]
    if not traces:
        return Outline(note='Aucun tracé reconnu à la volée.\n'
                            'Bouton « Visualiser » pour lire le fichier '
                            'en entier.')
    return Outline(traces, bounds(traces), not tronque,
                   'Esquisse partielle : fichier très long.'
                   if tronque else '')
