"""Import de dessins vectoriels / Vector drawing import.

Le DXF n'est pas le seul format qui arrive à l'atelier. Un client envoie
un logo en `.ai`, un bureau d'études un `.pdf`, un graphiste un `.eps`.
Les rouvrir dans un autre logiciel pour les réexporter en DXF fait perdre
du temps et, surtout, de la précision : chaque conversion approxime les
courbes une fois de plus.

**Ce que ce module lit nativement.**

| Format | Ce que c'est réellement | Lecture |
|---|---|---|
| `.pdf` | PDF | flux de contenu |
| `.ai` v9 et au-delà (2000→) | **un PDF**, avec un flux privé en plus | flux de contenu |
| `.ai` v8 et avant | **un EPS** PostScript | opérateurs Illustrator |
| `.eps`, `.ps` | PostScript encapsulé | opérateurs Illustrator |
| `.svg` | XML | primitives et chemins, voir `svgread` |

Un `.ai` moderne **est** un fichier PDF : Illustrator y range son format
propre dans un flux privé que les autres logiciels ignorent, et écrit la
même illustration en PDF pour que tout le monde puisse la lire. C'est
cette part-là qu'on lit, et elle est complète.

**Le CDR, lui, ne se lit pas.** Voir `CDR_NOTE` : format propriétaire,
sans documentation, dont aucun lecteur libre complet n'existe. Un
convertisseur externe est employé s'il est installé.

**On ne cherche pas à tout interpréter.** Un PDF ou un PostScript complet
est un langage de programmation ; l'interpréter entièrement serait un
travail sans fin et sans objet ici. On suit les opérateurs de **tracé** —
déplacements, droites, courbes de Bézier, transformations, pile d'états —
et l'on ignore les aplats : couleurs, dégradés, images.

**Le texte non vectorisé, lui, est rendu.** Un PDF (donc un `.ai`
moderne) place son texte avec `BT…ET`, `Tf`, `Tm`/`Td`, `Tj`/`TJ` — ces
opérateurs sont suivis, et chaque chaîne devient des contours via
`textvec`. La police n'est pas résolue précisément (le nom déclaré dans
`/BaseFont` est associé au document entier, pas à chaque ressource `Tf`
prise séparément) : c'est une approximation assumée, documentée dans
`fontmap`, plutôt qu'un texte qui disparaît sans un mot.
"""
from __future__ import annotations

import math
import pathlib
import re
import struct
import subprocess

from . import geometry as G
from .dxfimport import ImportReport
from .model import Path as PathShape, Recipe, default_recipe

#: Tolérance d'aplatissement des courbes de Bézier, en mm.
#: La même que l'import DXF : deux formats, une seule finesse.
TOLERANCE_MM = 0.02

#: Points PostScript vers millimètres. 72 points par pouce.
PT_TO_MM = 25.4 / 72.0

#: Extensions reconnues, et ce qu'on en fait.
SUFFIXES = ('.pdf', '.ai', '.eps', '.ps', '.svg', '.cdr')

#: Segments au-delà desquels on arrête de lire.
#:
#: Une carte vectorisée peut porter des millions de segments : on préfère
#: rendre ce qui a été lu, avec un avertissement, plutôt que de faire
#: attendre l'atelier dix minutes pour un dessin qu'il ne gravera pas.
MAX_SEGMENTS = 2_000_000


class VectorError(RuntimeError):
    """Fichier illisible, ou sans géométrie exploitable."""


class Cancelled(VectorError):
    """La lecture a été interrompue à la demande."""


#: Jetons lus entre deux consultations du signal d\'arrêt.
#:
#: Assez rares pour ne rien coûter, assez fréquentes pour qu\'un clic
#: sur *Annuler* soit pris en moins d\'un dixième de seconde sur un
#: fichier de dix mégaoctets.
POLL_EVERY = 20_000


CDR_NOTE = """Le format CorelDRAW (.cdr) est propriétaire et non documenté.
Aucun lecteur libre n'en couvre toutes les versions, et TauDrive n'en
embarque pas.

Deux voies :

* **Exporter depuis CorelDRAW** en PDF, EPS, AI ou DXF — TauDrive lit les
  quatre nativement, et sans perte de précision ;
* **Installer un convertisseur**, que TauDrive emploiera alors
  automatiquement :

    Inkscape 1.0 ou plus récent
    https://inkscape.org/release/

    LibreOffice 6.0 ou plus récent
    https://www.libreoffice.org/download/download-libreoffice/

Les deux emploient le même lecteur, `libcdr`. Inkscape est préféré : le
chemin est plus court et le PDF plus fidèle."""


# --------------------------------------------------------------------------
# Reconnaissance
# --------------------------------------------------------------------------

def sniff(path: str | pathlib.Path) -> str:
    """Ce que le fichier est **réellement**, et non ce que dit son nom.

    Un `.ai` peut être un PDF ou un EPS selon la version qui l'a écrit, et
    un `.eps` peut porter un en-tête binaire DOS avant son PostScript. Se
    fier au suffixe conduirait à refuser des fichiers parfaitement
    lisibles.
    """
    try:
        with open(path, 'rb') as f:
            tete = f.read(2048)
    except OSError as exc:
        raise VectorError(f'fichier illisible : {exc}') from None

    if tete.startswith(b'%PDF'):
        return 'pdf'
    if tete.startswith(b'\xc5\xd0\xd3\xc6'):
        # en-tête binaire DOS EPS : la section PostScript suit
        return 'eps'
    if tete.startswith(b'%!PS') or tete.startswith(b'%!'):
        return 'eps'
    if b'<svg' in tete[:1024].lower() or (
            tete.lstrip()[:5] == b'<?xml' and b'svg' in tete[:1024].lower()):
        return 'svg'
    if tete.startswith(b'RIFF') and b'CDR' in tete[:24].upper():
        return 'cdr'
    if tete.startswith(b'CDR') or tete[:4] == b'\xd0\xcf\x11\xe0':
        # CDR ancien, ou conteneur OLE : dans les deux cas, hors de portée
        return 'cdr'
    suffixe = pathlib.Path(path).suffix.lower()
    if suffixe == '.svg':
        return 'svg'
    if suffixe in ('.pdf', '.ai'):
        return 'pdf'
    if suffixe in ('.eps', '.ps'):
        return 'eps'
    if suffixe == '.cdr':
        return 'cdr'
    return 'inconnu'


def postscript_section(raw: bytes) -> bytes:
    """La partie PostScript d'un EPS, en-tête binaire DOS retiré.

    Un EPS écrit sous Windows commence souvent par un en-tête de 30 octets
    qui donne la position du PostScript, celle d'un aperçu WMF et celle
    d'un aperçu TIFF. Le lire tel quel donnerait des octets binaires en
    guise d'opérateurs.
    """
    if raw[:4] == b'\xc5\xd0\xd3\xc6':
        debut, longueur = struct.unpack('<II', raw[4:12])
        if 0 < debut < len(raw):
            return raw[debut:debut + longueur] if longueur else raw[debut:]
    return raw


# --------------------------------------------------------------------------
# Matrices
# --------------------------------------------------------------------------
#
# Une matrice PostScript / PDF s'écrit [a b c d e f] et transforme
# (x, y) en (a·x + c·y + e, b·x + d·y + f). La composition se fait dans
# cet ordre : appliquer M puis N revient à la matrice M × N.

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m, n):
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D,
            c * A + d * C, c * B + d * D,
            e * A + f * C + E, e * B + f * D + F)


def mat_apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def mat_scale(m) -> float:
    """Facteur d'échelle moyen de la matrice, pour l'aplatissement."""
    a, b, c, d, _, _ = m
    return max(1e-9, (math.hypot(a, b) + math.hypot(c, d)) / 2.0)


# --------------------------------------------------------------------------
# Constructeur de tracés
# --------------------------------------------------------------------------

class PathBuilder:
    """Accumule les tracés d'un flux, dans le repère final en millimètres.

    Le même pour le PDF et le PostScript : les deux langages ont les mêmes
    primitives de tracé, aux noms près. Ne diffère que la façon de les
    lire.
    """

    def __init__(self, tolerance_mm: float = TOLERANCE_MM) -> None:
        self.tolerance = tolerance_mm
        self.polylines: list[G.Polyline] = []
        self.current: G.Polyline = []
        self.start: tuple[float, float] | None = None
        self.point: tuple[float, float] | None = None
        self.ctm = IDENTITY
        self.stack: list[tuple] = []
        self.segments = 0
        self.truncated = False
        #: Images matricielles rencontrées. Ce ne sont pas des tracés, et
        #: un dessin qui n'est *que* cela doit se refuser en le disant :
        #: « aucun tracé » n'apprend rien, « c'est une photo » dit quoi
        #: faire.
        self.images = 0
        #: Chaînes de texte rencontrées, vectorisées ou non.
        self.textes = 0
        #: Nombre de chaînes rendues sans leur vraie police (voir
        #: `fontmap`) — pour le compte rendu, pas pour la géométrie.
        self.font_substitutions: dict[str, int] = {}

    # -- état ---------------------------------------------------------------

    def save(self) -> None:
        self.stack.append(self.ctm)

    def restore(self) -> None:
        if self.stack:
            self.ctm = self.stack.pop()

    def concat(self, m) -> None:
        self.ctm = mat_mul(m, self.ctm)

    def place(self, x: float, y: float) -> tuple[float, float]:
        """Un point du flux, amené en millimètres dans le repère final."""
        px, py = mat_apply(self.ctm, x, y)
        return (px * PT_TO_MM, py * PT_TO_MM)

    # -- tracé --------------------------------------------------------------

    def moveto(self, x: float, y: float) -> None:
        self.flush()
        self.point = self.place(x, y)
        self.start = self.point
        self.current = [self.point]

    def lineto(self, x: float, y: float) -> None:
        if self.point is None:
            return self.moveto(x, y)
        self.point = self.place(x, y)
        self.current.append(self.point)
        self.segments += 1

    def curveto(self, x1, y1, x2, y2, x3, y3) -> None:
        """Bézier cubique, aplatie à la tolérance voulue.

        La tolérance est exprimée en millimètres **sur la pièce** : elle
        est donc divisée par l'échelle de la matrice courante, sans quoi
        un dessin réduit de moitié serait aplati deux fois plus grossier
        qu'un autre.
        """
        if self.point is None:
            return self.moveto(x3, y3)
        p0 = self.point
        p1, p2, p3 = (self.place(x1, y1), self.place(x2, y2),
                      self.place(x3, y3))
        pts = G.flatten_cubic(p0, p1, p2, p3, self.tolerance)
        self.current.extend(pts[1:])
        self.segments += max(0, len(pts) - 1)
        self.point = p3

    def closepath(self) -> None:
        if self.start and self.point and self.point != self.start:
            self.current.append(self.start)
            self.segments += 1
        self.point = self.start

    def flush(self) -> None:
        """Range la polyligne en cours, si elle porte au moins un segment."""
        if len(self.current) >= 2:
            self.polylines.append(self.current)
        self.current = []

    def endpath(self) -> None:
        """Fin de tracé — peint ou non, la géométrie est la même.

        Un contour de découpe non peint sert autant qu'un contour peint :
        c'est le tracé qu'on grave, pas la couleur.
        """
        self.flush()
        self.point = self.start = None
        if self.segments > MAX_SEGMENTS:
            self.truncated = True

    def full(self) -> bool:
        return self.segments > MAX_SEGMENTS

    # -- texte ----------------------------------------------------------

    def draw_text(self, texte: str, tm, taille: float, nom_police: str,
                  ask=None, tc: float = 0.0, tw: float = 0.0,
                  tz: float = 100.0, ts: float = 0.0) -> float:
        """Rend une chaîne PDF/PostScript en contours, à la position et à
        l'échelle du texte courant (`tm`, composé avec le CTM courant).
        **Rend l'avance**, en unités de texte : de combien le point
        d'écriture doit avancer pour la chaîne suivante.

        Chaque contour est placé point par point avec la même conversion
        que le tracé — même échelle, même origine — pour qu'un texte et
        une géométrie du même flux tombent exactement d'aplomb.

        `tc`, `tw` : espacement des caractères et des mots (`Tc`, `Tw`) ;
        `tz` : échelle horizontale en pour cent (`Tz`) ; `ts` : élévation
        (`Ts`). Ignorés, ils resserraient tout texte crénelé ou justifié.
        """
        texte = (texte or '').strip('\x00')
        if not texte or taille <= 0:
            return 0.0
        from . import fontmap, textvec
        police, exact = fontmap.resolve(nom_police or 'sans-serif', ask=ask)
        # `Tf` donne un cadratin ; `outline` attend une hauteur de
        # capitale. Sans la conversion, le texte sortait 40 % trop grand.
        capitale = taille * textvec.em_ratio(police)
        echelle = (tz or 100.0) / 100.0
        avance = (textvec.advance_width(texte, capitale, police)
                  + tc * len(texte) + tw * texte.count(' ')) * echelle
        if not texte.strip():
            return avance                   # des espaces : rien à graver
        if not exact:
            cle = nom_police or '(non déclarée)'
            self.font_substitutions[cle] = self.font_substitutions.get(cle, 0) + 1
        contours = textvec.outline(texte, capitale, police,
                                   tolerance_mm=max(self.tolerance, 1e-3))
        if not contours:
            return avance
        if tc or tw:
            # l'espacement se répartit lettre par lettre : on redessine
            # chaque caractère à sa place plutôt que d'étirer le mot
            contours = []
            x = 0.0
            for ch in texte:
                if ch.strip():
                    contours.extend(
                        [[(px + x, py) for px, py in poly] for poly in
                         textvec.outline(ch, capitale, police,
                                         tolerance_mm=max(self.tolerance,
                                                          1e-3))])
                x += (textvec.advance_width(ch, capitale, police) + tc
                      + (tw if ch == ' ' else 0.0))
        local = (echelle, 0.0, 0.0, 1.0, 0.0, ts)
        combine = mat_mul(mat_mul(local, tm), self.ctm)
        for poly in contours:
            place = [(px * PT_TO_MM, py * PT_TO_MM)
                     for px, py in (mat_apply(combine, x, y) for x, y in poly)]
            if len(place) >= 2:
                self.polylines.append(place)
            if self.segments + len(place) > MAX_SEGMENTS:
                self.truncated = True
                return avance
            self.segments += len(place)
        return avance


# --------------------------------------------------------------------------
# PostScript / EPS / Illustrator
# --------------------------------------------------------------------------
#
# Illustrator écrit son EPS avec un vocabulaire abrégé, défini dans le
# prologue. Deux générations coexistent :
#
#   AI 8 et avant   m  l  c  v  y      f F s S b B n N    *u *U
#   AI 9 et au-delà mo li cv           f ef @ S           gsave/grestore
#
# Les deux sont acceptées : un atelier reçoit des fichiers de vingt ans
# d'âge aussi bien que de l'année dernière.

#: Opérateurs de tracé, et le nombre d'arguments qu'ils consomment.
_PS_PATH = {
    'm': 2, 'mo': 2, 'moveto': 2,
    'l': 2, 'L': 2, 'li': 2, 'lineto': 2,
    'c': 6, 'C': 6, 'cv': 6, 'curveto': 6,
    'v': 4, 'V': 4, 'y': 4, 'Y': 4,
}

#: Opérateurs qui posent une **image matricielle**. Ce ne sont pas des
#: tracés : on les compte pour pouvoir le dire, plutôt que de rendre
#: « aucun tracé exploitable » sans expliquer pourquoi.
_PS_IMAGE = {'image', 'colorimage', 'imagemask'}

#: Opérateurs qui terminent un tracé — peint ou non.
_PS_END = {'f', 'F', 'ef', 'eof', 's', 'S', 'b', 'B', 'n', 'N', '@',
           'fill', 'stroke', 'eofill', 'closepath_stroke', 'sf', 'ef*'}

#: Ce qui commence l'illustration. Tout ce qui précède est le prologue :
#: des centaines de procédures qu'il serait vain d'interpréter.
_PS_BODY = ('%%EndPageSetup', '%%EndSetup', '%%EndProlog')

_PS_TOKEN = re.compile(
    rb'%[^\r\n]*|\((?:[^()\\]|\\.)*\)|<[^>]*>|[\[\]{}]|[^\s\[\]{}()<>%]+')


def read_postscript(raw: bytes, tolerance_mm: float = TOLERANCE_MM,
                    progress=None, ask=None) -> PathBuilder:
    """Tracés d'un EPS Illustrator, en millimètres.

    La lecture commence **après le prologue** : celui-ci définit les
    procédures abrégées, et les interpréter demanderait un interpréteur
    PostScript complet pour un résultat déjà connu.

    Les blocs `{...}` rencontrés dans le corps sont sautés : ce sont des
    procédures, jamais du tracé.

    `ask` n'est pas encore employé ici : le texte du **PostScript
    ancien** (AI8 et avant) se pose par `show`, dont le glyphe suit une
    police PostScript nommée par `findfont` — un mécanisme distinct de
    `Tf`/`Tj` du PDF, non suivi. En pratique, les fichiers de cette
    génération arrivent déjà avec leur texte vectorisé ; c'est le PDF
    (donc l'AI9 et au-delà) qui porte le cas courant.
    """
    ps = postscript_section(raw)
    debut = 0
    for marque in _PS_BODY:
        trouve = ps.find(marque.encode('latin-1'))
        if trouve >= 0:
            debut = max(debut, trouve + len(marque))
    corps = ps[debut:]

    b = PathBuilder(tolerance_mm)
    pile: list[float] = []
    tableau: list[float] | None = None
    profondeur = 0
    lus = 0
    total = max(1, len(corps))

    for m in _PS_TOKEN.finditer(corps):
        lus += 1
        if progress is not None and lus % POLL_EVERY == 0:
            if not progress(m.start() / total):
                raise Cancelled('lecture interrompue')
        jeton = m.group()
        if jeton[:1] == b'%':
            continue
        if jeton == b'{':
            profondeur += 1
            continue
        if jeton == b'}':
            profondeur = max(0, profondeur - 1)
            continue
        if profondeur:
            continue
        if jeton == b'[':
            tableau = []
            continue
        if jeton == b']':
            pile = list(tableau or [])
            tableau = None
            continue
        if jeton[:1] in b'(<':
            continue

        texte = jeton.decode('latin-1')
        nombre = _number(texte)
        if nombre is not None:
            (tableau if tableau is not None else pile).append(nombre)
            if len(pile) > 64:
                del pile[:-64]
            continue

        _ps_operator(b, texte, pile)
        if b.full():
            b.truncated = True
            break

    b.endpath()
    return b


#: Échappements PDF reconnus dans une chaîne littérale `(...)`.
_PDF_STRING_ESCAPES = {'n': '\n', 'r': '\r', 't': '\t', 'b': '\b',
                       'f': '\f', '(': '(', ')': ')', '\\': '\\'}


def _pdf_string(jeton: bytes) -> str:
    """Décode une chaîne littérale PDF `(...)`, échappements compris.

    Une parenthèse non échappée dans le texte casserait le jeton bien
    avant d'arriver ici — le tokenizer ne gère qu'un niveau
    d'imbrication — donc seuls les échappements standards (`\\n`, `\\)`,
    l'octal `\\ddd`) sont décodés ; le reste passe tel quel.
    """
    interieur = jeton[1:-1]
    out: list[str] = []
    i = 0
    while i < len(interieur):
        c = interieur[i]
        if c == 0x5C and i + 1 < len(interieur):        # antislash
            suivant = chr(interieur[i + 1])
            if suivant in _PDF_STRING_ESCAPES:
                out.append(_PDF_STRING_ESCAPES[suivant])
                i += 2
                continue
            if suivant.isdigit():
                octal = interieur[i + 1:i + 4]
                fin = 1
                while fin < len(octal) and chr(octal[fin - 1]).isdigit() \
                        and fin < 3:
                    fin += 1
                chiffres = bytes(b for b in octal[:fin]
                                 if 48 <= b <= 55)
                try:
                    out.append(chr(int(bytes(chiffres), 8) & 0xFF))
                except ValueError:
                    pass
                i += 1 + max(1, len(chiffres))
                continue
            if suivant in '\r\n':                       # ligne repliée
                i += 2
                continue
            out.append(suivant)
            i += 2
            continue
        out.append(chr(c))
        i += 1
    try:
        return bytes(ord(c) for c in out).decode('cp1252', errors='replace')
    except ValueError:
        return ''.join(out)


def _number(texte: str) -> float | None:
    try:
        return float(texte)
    except ValueError:
        return None


def _ps_operator(b: PathBuilder, op: str, pile: list[float]) -> None:
    """Applique un opérateur PostScript, et vide la pile d'opérandes."""
    besoin = _PS_PATH.get(op)
    if besoin is not None:
        if len(pile) >= besoin:
            args = pile[-besoin:]
            _ps_path(b, op, args)
        pile.clear()
        return

    if op in _PS_IMAGE:
        b.images += 1
        pile.clear()
        return
    if op in _PS_END:
        b.endpath()
    elif op in ('gsave', 'q', 'save'):
        b.save()
    elif op in ('grestore', 'Q', 'restore'):
        b.restore()
    elif op in ('ct', 'concat', 'cm', 'setmatrix'):
        if len(pile) >= 6:
            b.concat(tuple(pile[-6:]))
    elif op == 'scale':
        if len(pile) >= 2:
            b.concat((pile[-2], 0.0, 0.0, pile[-1], 0.0, 0.0))
    elif op == 'translate':
        if len(pile) >= 2:
            b.concat((1.0, 0.0, 0.0, 1.0, pile[-2], pile[-1]))
    elif op in ('np', 'newpath'):
        b.endpath()
    elif op in ('cp', 'closepath', 'h'):
        b.closepath()
        return
    elif op in ('clp', 'eclp', 'clip', 'eoclip', 'W', 'W*'):
        # Un chemin de découpe borne ce qui suit ; il n'est pas gravé.
        # Le suivre serait au mieux inutile, au pire un cadre parasite
        # autour de chaque dessin — Illustrator en pose systématiquement.
        b.current = []
        b.point = b.start = None
    pile.clear()


def _ps_path(b: PathBuilder, op: str, args: list[float]) -> None:
    if op in ('m', 'mo', 'moveto'):
        b.moveto(args[0], args[1])
    elif op in ('l', 'L', 'li', 'lineto'):
        b.lineto(args[0], args[1])
    elif op in ('c', 'C', 'cv', 'curveto'):
        b.curveto(*args[:6])
    elif op in ('v', 'V'):
        # premier point de contrôle = point courant
        if b.point is not None:
            x0, y0 = _unplace(b, b.point)
            b.curveto(x0, y0, args[0], args[1], args[2], args[3])
    elif op in ('y', 'Y'):
        # second point de contrôle = point d'arrivée
        b.curveto(args[0], args[1], args[2], args[3], args[2], args[3])


def _unplace(b: PathBuilder, point) -> tuple[float, float]:
    """Ramène un point millimétré dans le repère du flux.

    Nécessaire au seul opérateur `v`, dont le premier point de contrôle
    est le point courant : celui-ci est mémorisé transformé, il faut donc
    le détransformer avant de le repasser à `curveto`.
    """
    a, bb, c, d, e, f = b.ctm
    det = a * d - bb * c
    if abs(det) < 1e-12:
        return (0.0, 0.0)
    x, y = point[0] / PT_TO_MM - e, point[1] / PT_TO_MM - f
    return ((x * d - y * c) / det, (y * a - x * bb) / det)


# --------------------------------------------------------------------------
# PDF — et donc Illustrator moderne
# --------------------------------------------------------------------------

#: Opérateurs PDF de tracé, avec leur nombre d'arguments.
_PDF_PATH = {'m': 2, 'l': 2, 'c': 6, 'v': 4, 'y': 4, 're': 4}

#: Opérateurs qui peignent — et donc terminent — un tracé.
_PDF_PAINT = {'S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'n'}


#: Trouve un nom de police dans un dictionnaire de police PDF, subset
#: éventuel compris (`ABCDEF+Arial-Bold` → `Arial-Bold`).
_PDF_BASEFONT = re.compile(rb'/BaseFont\s*/([A-Za-z0-9+\-,\.]+)')


def _pdf_guess_basefont(raw: bytes) -> str:
    """La police du document, à défaut de mieux.

    Résoudre **exactement** quelle police porte quel `Tf` demanderait de
    suivre les dictionnaires `/Resources /Font`, objet par objet — un
    petit analyseur PDF à lui seul. On se contente ici du nom le plus
    fréquent parmi tous les `/BaseFont` du fichier : la plupart des
    dessins d'atelier n'en emploient qu'une, et c'est alors exact ; sur
    plusieurs, c'est une approximation assumée (voir `fontmap`).
    """
    trouves = _PDF_BASEFONT.findall(raw)
    if not trouves:
        return ''
    noms = []
    for m in trouves:
        nom = m.decode('latin-1', errors='replace')
        if len(nom) > 7 and nom[6] == '+' and nom[:6].isupper():
            nom = nom[7:]                   # préfixe de sous-ensemble
        noms.append(nom.replace('-', ' ').replace(',', ' '))
    from collections import Counter
    return Counter(noms).most_common(1)[0][0]


def read_pdf(path: str | pathlib.Path, tolerance_mm: float = TOLERANCE_MM,
             pages: int = 1, progress=None, ask=None) -> PathBuilder:
    """Tracés d'un PDF — ou d'un `.ai` moderne, qui en est un.

    Seule la **première page** est lue par défaut : un dessin de gravure
    tient sur une page, et un catalogue de trente pages posé d'un coup sur
    le plan de travail ne rendrait service à personne.

    `ask` — voir `fontmap.resolve` — sert au texte non vectorisé dont la
    police n'est pas sur ce poste.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise VectorError(
            'lecture PDF indisponible : le module « pypdf » manque') from None

    try:
        raw = pathlib.Path(path).read_bytes()
        lecteur = PdfReader(str(path))
        feuilles = lecteur.pages[:max(1, pages)]
    except Exception as exc:
        raise VectorError(f'PDF illisible : {exc}') from None
    nom_police = _pdf_guess_basefont(raw)

    b = PathBuilder(tolerance_mm)
    ask_une_fois = None
    if ask is not None:
        from . import fontmap
        ask_une_fois = fontmap.cached_ask(ask)
    for page in feuilles:
        # La boîte de recadrage donne l'origine : un PDF dont la page ne
        # commence pas en (0,0) placerait sinon le dessin de travers.
        try:
            boite = page.mediabox
            b.ctm = (1.0, 0.0, 0.0, 1.0,
                     -float(boite.left), -float(boite.bottom))
        except Exception:
            b.ctm = IDENTITY
        base = b.ctm
        try:
            flux = page.get_contents()
            donnees = flux.get_data() if flux is not None else b''
        except Exception as exc:
            raise VectorError(f'flux PDF illisible : {exc}') from None
        _read_pdf_stream(b, donnees, base, progress, nom_police,
                         ask_une_fois)
        if b.full():
            b.truncated = True
            break
    b.endpath()
    return b


def _read_pdf_stream(b: PathBuilder, donnees: bytes, base, progress=None,
                     nom_police: str = '', ask=None) -> None:
    """Suit les opérateurs de tracé — et de texte — d'un flux PDF."""
    pile: list[float] = []
    lus = 0
    total = max(1, len(donnees))

    # état du texte courant, valide entre BT et ET
    tm = tlm = IDENTITY
    tfs = 0.0
    tl = 0.0
    # espacements et échelle : ils survivent à ET, comme dans le format
    tc = tw = ts = 0.0
    tz = 100.0
    #: l'état du texte fait partie de l'état graphique : `q` le met de
    #: côté, `Q` le rend. Sans quoi un espacement posé dans un bloc
    #: `q … Q` débordait sur tout le texte qui suivait.
    pile_texte: list[tuple] = []
    dernier_texte = ''
    tableau_ouvert = False
    #: éléments d'un tableau `TJ` : chaînes **et** décalages, dans l'ordre
    tableau_texte: list = []

    def ecrire(chaine: str) -> None:
        """Dessine `chaine` au point courant, puis avance le point."""
        nonlocal tm
        avance = b.draw_text(chaine, tm, tfs, nom_police, ask,
                             tc=tc, tw=tw, tz=tz, ts=ts)
        # sans cette avance, deux `Tj` d'un même bloc s'écrivaient l'un
        # sur l'autre, à la même origine
        tm = mat_mul((1.0, 0.0, 0.0, 1.0, avance, 0.0), tm)

    for m in _PS_TOKEN.finditer(donnees):
        lus += 1
        if progress is not None and lus % POLL_EVERY == 0:
            if not progress(m.start() / total):
                raise Cancelled('lecture interrompue')
        jeton = m.group()

        if jeton[:1] == b'(':
            chaine = _pdf_string(jeton)
            if tableau_ouvert:
                tableau_texte.append(chaine)
            else:
                dernier_texte = chaine
            continue
        if jeton[:1] == b'%' or jeton[:1] == b'<' or jeton in (b'{', b'}'):
            continue
        if jeton == b'[':
            tableau_ouvert = True
            tableau_texte = []
            continue
        if jeton == b']':
            tableau_ouvert = False
            continue
        if jeton[:1] == b'/':
            continue

        texte = jeton.decode('latin-1')
        nombre = _number(texte)
        if nombre is not None and tableau_ouvert:
            # un décalage dans un tableau `TJ` : crénage, approche,
            # justification. Il était jeté, et le texte se resserrait.
            tableau_texte.append(nombre)
            continue
        if nombre is not None:
            pile.append(nombre)
            if len(pile) > 64:
                del pile[:-64]
            continue

        besoin = _PDF_PATH.get(texte)
        if besoin is not None:
            if len(pile) >= besoin:
                _pdf_path(b, texte, pile[-besoin:])
            pile.clear()
            continue
        if texte in _PDF_PAINT:
            b.endpath()
        elif texte == 'q':
            b.save()
            pile_texte.append((tc, tw, tz, ts, tl, tfs))
        elif texte == 'Q':
            b.restore()
            if not b.stack:
                b.ctm = base
            if pile_texte:
                tc, tw, tz, ts, tl, tfs = pile_texte.pop()
        elif texte == 'cm' and len(pile) >= 6:
            b.concat(tuple(pile[-6:]))
        elif texte == 'h':
            b.closepath()
            pile.clear()
            continue
        elif texte in ('W', 'W*'):
            # chemin de découpe : borne ce qui suit, n'est pas gravé
            b.current = []
            b.point = b.start = None
        elif texte in ('Do', 'BI', 'EI'):
            # `Do` invoque un objet externe — le plus souvent une image ;
            # `BI` ouvre une image en ligne. On compte une fois par
            # image, pas une par opérateur.
            if texte != 'EI':
                b.images += 1
        elif texte == 'BT':
            tm = tlm = IDENTITY
        elif texte == 'Tf' and pile:
            tfs = pile[-1]
        elif texte == 'Tm' and len(pile) >= 6:
            tm = tlm = tuple(pile[-6:])
        elif texte in ('Td', 'TD') and len(pile) >= 2:
            tx, ty = pile[-2], pile[-1]
            if texte == 'TD':
                tl = -ty
            tlm = mat_mul((1.0, 0.0, 0.0, 1.0, tx, ty), tlm)
            tm = tlm
        elif texte == 'T*':
            tlm = mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -tl), tlm)
            tm = tlm
        elif texte == 'TL' and pile:
            tl = pile[-1]
        elif texte == 'Tc' and pile:
            tc = pile[-1]
        elif texte == 'Tw' and pile:
            tw = pile[-1]
        elif texte == 'Tz' and pile:
            tz = pile[-1]
        elif texte == 'Ts' and pile:
            ts = pile[-1]
        elif texte in ('Tj', "'", '"'):
            if texte == '"' and len(pile) >= 2:
                tw, tc = pile[-2], pile[-1]
            if texte in ("'", '"'):
                tlm = mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -tl), tlm)
                tm = tlm
            if dernier_texte:
                ecrire(dernier_texte)
            dernier_texte = ''
        elif texte == 'TJ':
            for element in tableau_texte:
                if isinstance(element, str):
                    ecrire(element)
                else:
                    # en millièmes de cadratin, et **à rebours** : un
                    # nombre positif rapproche la chaîne suivante
                    tm = mat_mul((1.0, 0.0, 0.0, 1.0,
                                  -element / 1000.0 * tfs * tz / 100.0, 0.0),
                                 tm)
            tableau_texte = []
        pile.clear()
        if b.full():
            return


def _pdf_path(b: PathBuilder, op: str, args: list[float]) -> None:
    if op == 'm':
        b.moveto(args[0], args[1])
    elif op == 'l':
        b.lineto(args[0], args[1])
    elif op == 'c':
        b.curveto(*args[:6])
    elif op == 'v':
        if b.point is not None:
            x0, y0 = _unplace(b, b.point)
            b.curveto(x0, y0, args[0], args[1], args[2], args[3])
    elif op == 'y':
        b.curveto(args[0], args[1], args[2], args[3], args[2], args[3])
    elif op == 're':
        x, y, w, h = args[:4]
        b.moveto(x, y)
        b.lineto(x + w, y)
        b.lineto(x + w, y + h)
        b.lineto(x, y + h)
        b.closepath()
        b.flush()


# --------------------------------------------------------------------------
# CorelDRAW — par convertisseur externe
# --------------------------------------------------------------------------

#: Convertisseurs cherchés, dans l'ordre de préférence.
#:
#: Inkscape d'abord : il emploie `libcdr`, le lecteur de LibreOffice, et
#: rend un PDF vectoriel fidèle. LibreOffice ensuite, qui emploie le même
#: lecteur par un chemin plus long.
CONVERTERS = (
    (r'C:\Program Files\Inkscape\bin\inkscape.exe', 'inkscape'),
    (r'C:\Program Files\Inkscape\inkscape.exe', 'inkscape'),
    (r'C:\Program Files (x86)\Inkscape\bin\inkscape.exe', 'inkscape'),
    (r'C:\Program Files (x86)\Inkscape\inkscape.exe', 'inkscape'),
    (r'C:\Program Files\LibreOffice\program\soffice.exe', 'soffice'),
)

#: Délai laissé au convertisseur, en secondes.
CONVERT_TIMEOUT = 120

#: Versions minimales, et pourquoi.
#:
#: **Inkscape 1.0** — c'est la version qui a introduit
#: `--export-type` / `--export-filename`. Les versions 0.9x employaient
#: `--export-pdf`, que TauDrive sait encore appeler, mais qui n'est plus
#: distribué. La lecture du CDR elle-même remonte à 0.91, par `libcdr`.
#:
#: **LibreOffice 6.0** — `--headless --convert-to` est stable bien avant,
#: et `libcdr` lit le CDR depuis LibreOffice 4.0 ; 6.0 est simplement le
#: plus ancien millésime encore raisonnable à installer aujourd'hui.
#:
#: Vérifié ici sur **Inkscape 1.3**, qui embarque `libcdr-0.1.dll`. Les
#: autres bornes viennent de l'historique documenté de ces outils, non
#: d'un essai sur ce poste.
MIN_VERSIONS = {
    'inkscape': ('1.0', 'https://inkscape.org/release/'),
    'soffice': ('6.0',
                'https://www.libreoffice.org/download/download-libreoffice/'),
}


def converter() -> tuple[str, str] | None:
    """Le convertisseur installé, ou `None`. Rend `(chemin, genre)`."""
    import shutil
    for chemin, genre in CONVERTERS:
        if pathlib.Path(chemin).exists():
            return (chemin, genre)
    for nom, genre in (('inkscape', 'inkscape'), ('soffice', 'soffice')):
        trouve = shutil.which(nom)
        if trouve:
            return (trouve, genre)
    return None


def version_of(binaire: str, genre: str) -> str:
    """Version du convertisseur, ou une chaîne vide s'il ne répond pas."""
    try:
        fait = subprocess.run([binaire, '--version'], capture_output=True,
                              timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    sortie = (fait.stdout or fait.stderr or b'').decode('utf-8', 'replace')
    trouve = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', sortie)
    return trouve.group(0) if trouve else ''


def _too_old(version: str, minimum: str) -> bool:
    """Compare deux versions « 1.3 » / « 1.0 » sans rien supposer d'autre."""
    def morceaux(v):
        return [int(x) for x in re.findall(r'\d+', v)[:3]]
    a, b = morceaux(version), morceaux(minimum)
    if not a:
        return False                    # version illisible : on essaie
    return a + [0, 0, 0] < b + [0, 0, 0]


def converter_status() -> dict:
    """Ce qu'on sait du convertisseur installé, pour l'aide et l'erreur."""
    outil = converter()
    if outil is None:
        return {'trouve': False}
    binaire, genre = outil
    version = version_of(binaire, genre)
    minimum, lien = MIN_VERSIONS.get(genre, ('', ''))
    return {'trouve': True, 'chemin': binaire, 'genre': genre,
            'version': version, 'minimum': minimum, 'lien': lien,
            'trop_vieux': bool(version and _too_old(version, minimum))}


def convert_to_pdf(path: str | pathlib.Path,
                   out_dir: str | pathlib.Path | None = None) -> pathlib.Path:
    """Convertit un fichier en PDF par un outil externe.

    Rend le chemin du PDF produit. Lève `VectorError` si aucun
    convertisseur n'est installé, ou si la conversion échoue.
    """
    outil = converter()
    if outil is None:
        raise VectorError(CDR_NOTE)
    binaire, genre = outil
    source = pathlib.Path(path).resolve()
    dossier = pathlib.Path(out_dir) if out_dir else source.parent
    cible = dossier / (source.stem + '.pdf')

    if genre == 'inkscape':
        # `--export-type` date d\'Inkscape 1.0 ; les 0.9x employaient
        # `--export-pdf`. On appelle encore l\'ancienne forme plutôt
        # que de refuser un poste qui n\'a pas été mis à jour.
        version = version_of(binaire, genre)
        if version and _too_old(version, '1.0'):
            cmd = [binaire, str(source), f'--export-pdf={cible}']
        else:
            cmd = [binaire, str(source), '--export-type=pdf',
                   f'--export-filename={cible}']
    else:
        cmd = [binaire, '--headless', '--convert-to', 'pdf',
               '--outdir', str(dossier), str(source)]
    try:
        fait = subprocess.run(cmd, capture_output=True, timeout=CONVERT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise VectorError(
            f'{pathlib.Path(binaire).name} n\'a pas répondu en '
            f'{CONVERT_TIMEOUT} s.') from None
    except OSError as exc:
        raise VectorError(f'conversion impossible : {exc}') from None

    if not cible.exists():
        detail = (fait.stderr or fait.stdout or b'').decode(
            'utf-8', 'replace').strip()[:300]
        raise VectorError(
            f'{pathlib.Path(binaire).name} n\'a produit aucun PDF.'
            + (f'\n{detail}' if detail else ''))
    return cible


# --------------------------------------------------------------------------
# Entrée commune
# --------------------------------------------------------------------------

def read(path: str | pathlib.Path, *, tolerance_mm: float = TOLERANCE_MM,
         units_mm: float | None = None, progress=None, ask=None
         ) -> tuple[list[G.Polyline], ImportReport]:
    """Tracés d'un fichier vectoriel, en millimètres, avec son compte rendu.

    `units_mm` force une échelle : les PDF et PostScript portent leurs
    unités (le point), et n'en ont normalement pas besoin. Le réglage
    existe pour les dessins mis à l'échelle avant export.

    `ask` — voir `fontmap.resolve` — sert au texte non vectorisé dont la
    police n'est pas sur ce poste.
    """
    genre = sniff(path)
    temporaire = None
    if genre == 'cdr':
        import tempfile
        temporaire = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-cdr-'))
        path = convert_to_pdf(path, temporaire)
        genre = 'pdf'

    try:
        if genre == 'svg':
            from . import svgread
            try:
                polys_svg, rapport_svg = svgread.read(
                    pathlib.Path(path).read_bytes(), tolerance_mm, ask=ask)
            except svgread.SvgError as exc:
                raise VectorError(str(exc)) from None
            b = PathBuilder(tolerance_mm)
            b.polylines = polys_svg
            b.note_svg = rapport_svg
        elif genre == 'pdf':
            b = read_pdf(path, tolerance_mm, progress=progress, ask=ask)
        elif genre == 'eps':
            b = read_postscript(pathlib.Path(path).read_bytes(), tolerance_mm,
                                progress=progress, ask=ask)
        else:
            raise VectorError(
                f'format non reconnu : {pathlib.Path(path).suffix or "sans "
                                        "suffixe"}')
    finally:
        if temporaire is not None:
            import shutil
            shutil.rmtree(temporaire, ignore_errors=True)

    polys = [p for p in b.polylines if len(p) >= 2]
    if units_mm and units_mm != 1.0:
        polys = [G.scale(p, units_mm) for p in polys]

    report = ImportReport()
    report.units_mm = units_mm or 1.0
    report.declared_units_mm = 1.0
    report.units_overridden = bool(units_mm and units_mm != 1.0)
    # un fichier abîmé peut rendre des points NaN ou infinis — voir
    # `dxfimport.assainir` ; avant les comptes, pour qu'ils soient justes
    from .dxfimport import ILLISIBLE, assainir
    lus = bool(polys)
    polys = assainir(polys, report)
    report.polylines = len(polys)
    report.layers = {genre: len(polys)}
    report.extent = G.bounds(polys) if polys else None
    if b.truncated:
        report.skipped_other['segments au-delà de la limite'] = 1
    if getattr(b, 'images', 0):
        report.skipped_other['images matricielles'] = b.images
    for nom, nombre in getattr(b, 'font_substitutions', {}).items():
        report.font_substitutions[nom] = (
            report.font_substitutions.get(nom, 0) + nombre)
    note = getattr(b, 'note_svg', None)
    if note:
        report.declared_units_mm = note.get('echelle_mm', 1.0)
        if note.get('textes'):
            # un texte non vectorisé disparaîtrait en silence, et l\'on
            # croirait le dessin incomplet sans savoir pourquoi
            report.skipped_text = note['textes']
        for cle, nombre in (('images matricielles', note.get('images', 0)),
                            ('références « use »', note.get('usages', 0))):
            if nombre:
                report.skipped_other[cle] = nombre
        for nom, nombre in note.get('police_substituee', {}).items():
            report.font_substitutions[nom] = (
                report.font_substitutions.get(nom, 0) + nombre)
        if note.get('avertissement'):
            report.notes.append(note['avertissement'])
    if not polys:
        raise VectorError(ILLISIBLE if lus else _pourquoi_vide(b, report,
                                                               genre))
    return polys, report


def _pourquoi_vide(b, report, genre: str) -> str:
    '''Pourquoi ce fichier ne donne aucun tracé, et quoi faire.

    « Aucun tracé exploitable » est vrai mais inutile : il ne dit ni ce
    que le fichier contient, ni comment s'en sortir. Un opérateur devant
    ce message rouvre le fichier dans trois logiciels avant de comprendre
    qu'il tenait une photo.
    '''
    images = getattr(b, 'images', 0)
    textes = int(getattr(report, 'skipped_text', 0) or 0)

    if images and not textes:
        return (f'ce fichier ne contient pas de tracé, mais '
                f'{images} image(s) matricielle(s) — une photo ou un '
                f'scan.\n\nUne gravure suit un contour : il faut '
                f'vectoriser l\'image d\'abord (Inkscape ▸ Chemin ▸ '
                f'Vectoriser le bitmap), puis réimporter.')
    if textes and not images:
        return (f'ce fichier ne contient que du texte '
                f'({textes} bloc(s)), et aucune police n\'a pu le '
                f'rendre.\n\nInstallez la police du dessin, ou '
                f'vectorisez le texte dans le logiciel d\'origine.')
    if images and textes:
        return (f'ce fichier ne contient aucun tracé : '
                f'{images} image(s) et {textes} bloc(s) de texte '
                f'seulement.')
    if genre == 'eps':
        return ('aucun tracé lisible dans ce PostScript.\n\nS\'il '
                'vient d\'un logiciel récent, réexportez-le en PDF ou '
                'en AI : le vocabulaire y est mieux défini.')
    return ('ce fichier ne contient aucun tracé exploitable.\n\n'
            'Vérifiez qu\'il n\'est pas vide, et qu\'il a bien été '
            'enregistré comme dessin vectoriel.')


def to_shapes(path: str | pathlib.Path, *, recipe: Recipe | None = None,
              tolerance_mm: float = TOLERANCE_MM, center: bool = True,
              units_mm: float | None = None, progress=None, ask=None
              ) -> tuple[list[PathShape], ImportReport]:
    """Lit un fichier vectoriel et en fait une forme `Path`.

    Même signature que `dxfimport.to_shapes` : les deux imports se
    substituent l'un à l'autre dans l'interface.

    Une seule forme, et non une par calque : ni le PDF ni le PostScript ne
    portent de notion de calque exploitable — Illustrator range les siens
    dans son flux privé, que l'on ne lit pas.
    """
    polys, report = read(path, tolerance_mm=tolerance_mm, units_mm=units_mm,
                         progress=progress, ask=ask)
    dx = dy = 0.0
    if center and report.extent:
        x1, y1, x2, y2 = report.extent
        dx, dy = -(x1 + x2) / 2, -(y1 + y2) / 2
    source = pathlib.Path(path).name
    forme = PathShape(
        polylines=[[(x + dx, y + dy) for x, y in poly] for poly in polys],
        recipe=recipe or default_recipe(), source=source,
        layer=pathlib.Path(path).suffix.lstrip('.').lower() or 'vecteur')
    return [forme], report
