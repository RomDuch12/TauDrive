"""Export vectoriel / Vector export — DXF, EPS, AI, SVG, PDF.

L'export ISO+CLJOB va à la machine. Celui-ci va **aux autres** : le bureau
d'études qui veut le plan coté, le client qui veut vérifier son logo, le
graphiste qui reprendra le dessin. Cinq formats, choisis parce qu'ils
s'ouvrent partout :

| Format | Qui l'ouvre |
|---|---|
| `.dxf` | AutoCAD, SolidWorks, Inkscape, LibreCAD, CorelDRAW… |
| `.eps` | Illustrator, CorelDRAW, Inkscape, toute imprimante PostScript |
| `.ai` | Illustrator — **c'est un EPS**, voir plus bas |
| `.svg` | Inkscape, un navigateur, tout logiciel récent |
| `.pdf` | n'importe quoi — Acrobat, un navigateur, une imprimante |

**Deux contenus au choix.**

* le **dessin** — les contours tels qu'on les a posés. C'est ce qu'on
  envoie à quelqu'un qui va reprendre le dessin ;
* les **trajectoires** — tout ce qui part à la machine, hachurage,
  épaississement et oscillation compris. C'est ce qu'on envoie à
  quelqu'un qui veut voir *exactement* ce qui sera gravé.

Le second est souvent cent fois plus lourd que le premier : un carré
hachuré au pas de 0,05 mm porte des centaines de segments là où le dessin
en porte quatre.

**Le `.ai` produit est un EPS.** Illustrator lit sans broncher un `.ai`
au format EPS — c'est ce qu'était le format jusqu'à sa version 8, et il
n'a jamais cessé de le reconnaître. Écrire un vrai `.ai` moderne
demanderait de produire un PDF **et** le flux privé d'Adobe, dont le
format n'est pas documenté. L'EPS donne le même dessin, ouvrable, et sans
rien inventer.
"""
from __future__ import annotations

import datetime
import pathlib

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QVBoxLayout)

from . import geometry as G
from .model import Document
from . import theme

#: Formats offerts, avec leur libellé et leur filtre.
FORMATS = (
    ('dxf', 'DXF', 'Dessin DXF (*.dxf)'),
    ('eps', 'EPS', 'PostScript encapsulé (*.eps)'),
    ('ai', 'Illustrator', 'Illustrator, au format EPS (*.ai)'),
    ('svg', 'SVG', 'Image vectorielle SVG (*.svg)'),
    ('pdf', 'PDF', 'Document PDF (*.pdf)'),
)

#: Millimètres vers points PostScript.
MM_TO_PT = 72.0 / 25.4

#: Filtre commun aux sélecteurs de fichiers.
FILE_FILTER = ';;'.join(f for _, _, f in FORMATS) + ';;Tous (*)'


class ExportError(RuntimeError):
    """L'export n'a pas pu se faire."""


def suffix_format(path) -> str:
    """Le format déduit du suffixe, `dxf` à défaut."""
    suffixe = pathlib.Path(path).suffix.lower().lstrip('.')
    return suffixe if suffixe in {k for k, _, _ in FORMATS} else 'dxf'


# --------------------------------------------------------------------------
# Ce qu'on exporte
# --------------------------------------------------------------------------

def drawing_layers(document: Document, *, visible_only: bool = True
                   ) -> list[tuple[str, list[G.Polyline]]]:
    """Les **contours** du document, un calque par forme.

    Le dessin tel qu'on l'a posé : ni hachurage, ni épaississement, ni
    oscillation. C'est ce qu'on envoie à qui va reprendre le dessin.
    """
    from .toolpath import shape_contours
    couches = []
    for shape in document.shapes:
        if visible_only and not shape.visible:
            continue
        contours = shape_contours(shape)
        if not contours:
            continue
        places = [G.translate(G.rotate(c, shape.rotation_deg),
                              shape.x, shape.y) for c in contours]
        couches.append((_layer_name(shape), places))
    return couches


def toolpath_layers(document: Document, *, visible_only: bool = True
                    ) -> list[tuple[str, list[G.Polyline]]]:
    """Les **trajectoires** du document, un calque par forme.

    Tout ce qui part à la machine. Un carré hachuré au pas de 0,05 mm
    porte ici des centaines de segments là où le dessin en porte quatre :
    l'export est d'autant plus lourd, et c'est voulu.

    Une oscillation trop dense pour être calculée est **refusée**, comme
    à l'export ISO : écrire le trait sans elle ne serait pas ce qui sera
    gravé — voir `toolpath.dense_wobble`.
    """
    from .toolpath import (_refus_code, _refus_dense, codes_inencodables,
                           dense_wobble, group_zones, shape_polylines)
    # un groupe se remplit comme un seul dessin — voir `group_zones`
    zones = group_zones(document.shapes)
    couches = []
    with dense_wobble() as denses:
        for shape in document.shapes:
            if visible_only and not shape.visible:
                continue
            polys = shape_polylines(shape, zone=zones.get(shape.id))
            if polys:
                couches.append((_layer_name(shape), polys))
    if denses:
        raise ExportError(str(_refus_dense(denses)))
    # un code inencodable est omis, comme à l'export ISO qui le refuse
    refus = codes_inencodables(document)
    if refus:
        raise ExportError(str(_refus_code(refus)))
    return couches


def _layer_name(shape) -> str:
    """Nom de calque sûr : le DXF n'accepte pas tout.

    Les caractères interdits par la norme — `<>/\\":;?*|=` et
    l'apostrophe — sont remplacés, et le nom est borné à 31 caractères
    comme le veut la table des calques.
    """
    brut = shape.display_name() or 'forme'
    interdits = '<>/\\":;?*|=\'`'
    propre = ''.join('_' if c in interdits else c for c in brut)
    return ' '.join(propre.split())[:31] or 'forme'


# --------------------------------------------------------------------------
# DXF
# --------------------------------------------------------------------------

def write_dxf(couches, path, *, closed_tolerance: float = 1e-6) -> int:
    """Écrit les couches en DXF R2000. Rend le nombre de polylignes.

    Une `LWPOLYLINE` par polyligne, un calque par forme. R2000 plutôt que
    le dernier millésime : c'est la version que tout lit encore, y compris
    les logiciels d'atelier qui ont quinze ans.

    Les sommets sont posés **d'un bloc** dans l'entité, et non confiés à
    `add_lwpolyline` : ezdxf (1.4) les y ajoute un à un en recopiant tout
    le tableau à chaque ajout. Le coût était quadratique — 33 s pour une
    spirale de 60 000 points, que le SVG écrit en 0,2 s.
    """
    try:
        import ezdxf
    except ImportError:
        raise ExportError('export DXF indisponible : le module « ezdxf » '
                          'manque') from None
    doc = ezdxf.new('R2000', setup=True)
    doc.header['$INSUNITS'] = 4          # millimètre
    espace = doc.modelspace()

    total = 0
    for nom, polys in couches:
        if nom not in doc.layers:
            doc.layers.add(nom)
        for poly in polys:
            if len(poly) < 2:
                continue
            ferme = (abs(poly[0][0] - poly[-1][0]) < closed_tolerance
                     and abs(poly[0][1] - poly[-1][1]) < closed_tolerance)
            points = poly[:-1] if ferme else poly
            # le tableau qu'ezdxf aurait bâti point par point : x, y, puis
            # largeurs de début et de fin et renflement, nuls. Le fichier
            # écrit est le même, octet pour octet
            sommets = [(float(x), float(y), 0.0, 0.0, 0.0) for x, y in points]
            ligne = espace.add_lwpolyline((), dxfattribs={'layer': nom},
                                          close=ferme)
            try:
                ligne.lwpoints.set(sommets)
            except (AttributeError, ValueError):
                # un ezdxf qui n'aurait plus ce tableau : point par point
                ligne.set_points([(x, y) for x, y, *_ in sommets])
            total += 1
    try:
        doc.saveas(str(path))
    except Exception as exc:
        raise ExportError(f'écriture DXF impossible : {exc}') from None
    return total


# --------------------------------------------------------------------------
# EPS et AI
# --------------------------------------------------------------------------

def write_eps(couches, path, *, title: str = 'TauDrive',
              illustrator: bool = False, line_width_pt: float = 0.24) -> int:
    """Écrit les couches en PostScript encapsulé. Rend le nombre de tracés.

    `illustrator=True` ajoute les commentaires que reconnaît Illustrator
    et pose un calque par couche. Le contenu est le même : c'est le même
    PostScript, avec un en-tête plus bavard.

    La boîte englobante est **calculée sur la géométrie**, et le dessin
    ramené à l'origine : un EPS dont le contenu est loin de sa boîte
    s'ouvre vide dans la moitié des logiciels.
    """
    polys = [p for _, couche in couches for p in couche if len(p) >= 2]
    if not polys:
        raise ExportError('rien à exporter : aucun tracé visible.')
    x1, y1, x2, y2 = G.bounds(polys)

    def pt(x, y):
        return ((x - x1) * MM_TO_PT, (y - y1) * MM_TO_PT)

    largeur = (x2 - x1) * MM_TO_PT
    hauteur = (y2 - y1) * MM_TO_PT
    quand = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    out: list[str] = [
        '%!PS-Adobe-3.0 EPSF-3.0',
        f'%%Creator: TauDrive',
        f'%%Title: {_ascii(title)}',
        f'%%CreationDate: {quand}',
        f'%%BoundingBox: 0 0 {int(largeur) + 1} {int(hauteur) + 1}',
        f'%%HiResBoundingBox: 0 0 {largeur:.4f} {hauteur:.4f}',
    ]
    if illustrator:
        out += ['%%AI8_CreatorVersion: 8.0',
                '%%DocumentProcessColors: Black',
                f'%%For: {_ascii(title)}']
    out += ['%%LanguageLevel: 2', '%%EndComments', '%%BeginProlog',
            '/m {moveto} bind def', '/l {lineto} bind def',
            '/S {stroke} bind def', '/h {closepath} bind def',
            '%%EndProlog', '%%BeginSetup', '%%EndSetup',
            f'{line_width_pt:g} setlinewidth', '1 setlinecap',
            '1 setlinejoin', '0 setgray']

    total = 0
    for nom, couche in couches:
        if illustrator:
            out.append(f'%%AI5_BeginLayer: 1 1 1 1 0 0 0 79 128 255 '
                       f'({_ascii(nom)}) 0 0')
        out.append(f'% couche : {_ascii(nom)}')
        for poly in couche:
            if len(poly) < 2:
                continue
            ferme = (abs(poly[0][0] - poly[-1][0]) < 1e-9
                     and abs(poly[0][1] - poly[-1][1]) < 1e-9)
            points = poly[:-1] if ferme else poly
            x, y = pt(*points[0])
            out.append(f'newpath {x:.4f} {y:.4f} m')
            for px, py in points[1:]:
                x, y = pt(px, py)
                out.append(f'{x:.4f} {y:.4f} l')
            out.append('h S' if ferme else 'S')
            total += 1
        if illustrator:
            out.append('%%AI5_EndLayer--')

    out += ['showpage', '%%EOF', '']
    try:
        pathlib.Path(path).write_text('\n'.join(out), encoding='ascii',
                                      errors='replace')
    except OSError as exc:
        raise ExportError(f'écriture impossible : {exc}') from None
    return total


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------

def write_svg(couches, path, *, title: str = 'TauDrive',
              line_width_mm: float = 0.1) -> int:
    """Écrit les couches en SVG. Rend le nombre de tracés.

    Le SVG compte ses ordonnées **vers le bas**, l'atelier vers le haut :
    le dessin est retourné à l'écriture, faute de quoi il ressort en
    miroir chez qui l'ouvre. C'est la seule différence de fond avec les
    autres formats.

    L'unité est le millimètre, déclarée deux fois : `width`/`height` en
    millimètres et un `viewBox` de même mesure. Un lecteur qui ignore les
    unités retrouve alors les bonnes proportions, et celui qui les honore
    retrouve la bonne taille.
    """
    polys = [p for _, couche in couches for p in couche if len(p) >= 2]
    if not polys:
        raise ExportError('rien à exporter : aucun tracé visible.')
    x1, y1, x2, y2 = G.bounds(polys)
    largeur = max(x2 - x1, 1e-6)
    hauteur = max(y2 - y1, 1e-6)
    quand = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<!-- TauDrive · {_xml(title)} · {quand} -->',
        '<svg xmlns="http://www.w3.org/2000/svg"'
        ' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
        ' version="1.1"',
        f'     width="{largeur:.4f}mm" height="{hauteur:.4f}mm"',
        f'     viewBox="0 0 {largeur:.4f} {hauteur:.4f}">',
        f'  <title>{_xml(title)}</title>',
    ]

    total = 0
    for nom, couche in couches:
        tracés = [poly for poly in couche if len(poly) >= 2]
        if not tracés:
            continue
        out.append(f'  <g inkscape:label="{_xml(nom)}" '
                   f'inkscape:groupmode="layer" id="{_slug(nom)}"'
                   f' fill="none" stroke="#000000"'
                   f' stroke-width="{line_width_mm:g}"'
                   f' stroke-linecap="round" stroke-linejoin="round">')
        for poly in tracés:
            fermé = (abs(poly[0][0] - poly[-1][0]) < 1e-9
                     and abs(poly[0][1] - poly[-1][1]) < 1e-9)
            points = poly[:-1] if fermé else poly
            morceaux = []
            for i, (px, py) in enumerate(points):
                x = px - x1
                y = y2 - py          # l'ordonnée se retourne ici
                morceaux.append(f'{"M" if i == 0 else "L"} {x:.4f} {y:.4f}')
            if fermé:
                morceaux.append('Z')
            out.append(f'    <path d="{" ".join(morceaux)}"/>')
            total += 1
        out.append('  </g>')

    out += ['</svg>', '']
    texte = chr(10).join(out)
    try:
        pathlib.Path(path).write_text(texte, encoding='utf-8')
    except OSError as exc:
        raise ExportError(f'écriture impossible : {exc}') from None
    return total


def _xml(texte: str) -> str:
    """Texte utilisable dans un attribut ou un nœud XML."""
    return (str(texte or '').replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _slug(texte: str) -> str:
    """Identifiant XML tiré d'un nom de calque."""
    propre = ''.join(c if (c.isalnum() or c in '-_') else '-'
                     for c in str(texte or 'couche'))
    return ('couche-' + propre.strip('-')) or 'couche'


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def write_pdf(couches, path, *, title: str = 'TauDrive',
             line_width_pt: float = 0.24) -> int:
    """Écrit les couches en PDF. Rend le nombre de tracés.

    Un document minimal, écrit à la main plutôt que par une
    bibliothèque : trois objets et un flux de contenu, l'un des plus
    simples PDF valides qui soit. Le repère est celui du PostScript — Y
    croît vers le haut — donc **pas de retournement** ici, à la
    différence du SVG.
    """
    polys = [p for _, couche in couches for p in couche if len(p) >= 2]
    if not polys:
        raise ExportError('rien à exporter : aucun tracé visible.')
    x1, y1, x2, y2 = G.bounds(polys)

    def pt(x, y):
        return ((x - x1) * MM_TO_PT, (y - y1) * MM_TO_PT)

    largeur = max((x2 - x1) * MM_TO_PT, 1.0)
    hauteur = max((y2 - y1) * MM_TO_PT, 1.0)

    corps: list[str] = [f'{line_width_pt:g} w 1 J 1 j 0 G']
    total = 0
    for nom, couche in couches:
        corps.append(f'% {_ascii(nom)}')
        for poly in couche:
            if len(poly) < 2:
                continue
            ferme = (abs(poly[0][0] - poly[-1][0]) < 1e-9
                     and abs(poly[0][1] - poly[-1][1]) < 1e-9)
            points = poly[:-1] if ferme else poly
            x, y = pt(*points[0])
            corps.append(f'{x:.4f} {y:.4f} m')
            for px, py in points[1:]:
                x, y = pt(px, py)
                corps.append(f'{x:.4f} {y:.4f} l')
            corps.append('h S' if ferme else 'S')
            total += 1
    flux = '\n'.join(corps).encode('latin-1', errors='replace')

    objets = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        (f'<< /Type /Page /Parent 2 0 R '
         f'/MediaBox [0 0 {largeur:.4f} {hauteur:.4f}] '
         f'/Contents 4 0 R /Resources << >> >>').encode('latin-1'),
        (f'<< /Length {len(flux)} >>stream\n'.encode('latin-1') + flux
         + b'\nendstream'),
    ]
    out = bytearray(f'%PDF-1.4\n%titre : {_ascii(title)}\n'.encode('latin-1'))
    places = []
    for i, contenu in enumerate(objets, 1):
        places.append(len(out))
        out += f'{i} 0 obj\n'.encode('latin-1') + contenu
        out += b'\nendobj\n'
    debut_xref = len(out)
    out += f'xref\n0 {len(objets) + 1}\n'.encode('latin-1')
    out += b'0000000000 65535 f \n'
    for place in places:
        out += f'{place:010d} 00000 n \n'.encode('latin-1')
    out += b'trailer\n'
    out += f'<< /Size {len(objets) + 1} /Root 1 0 R >>\n'.encode('latin-1')
    out += f'startxref\n{debut_xref}\n%%EOF\n'.encode('latin-1')

    try:
        pathlib.Path(path).write_bytes(bytes(out))
    except OSError as exc:
        raise ExportError(f'écriture impossible : {exc}') from None
    return total


def _ascii(texte: str) -> str:
    """Texte réduit à l'ASCII, parenthèses neutralisées.

    Un commentaire PostScript n'a pas de règle d'échappement : une
    parenthèse déséquilibrée dans un nom de calque suffit à dérouter
    certains lecteurs.
    """
    propre = (str(texte or '').encode('ascii', 'replace')
              .decode('ascii').replace('(', '[').replace(')', ']'))
    return ''.join(c for c in propre if 32 <= ord(c) < 127)


# --------------------------------------------------------------------------
# Entrée commune
# --------------------------------------------------------------------------

def export(document: Document, path, *, kind: str = '',
           toolpaths: bool = False, visible_only: bool = True) -> int:
    """Exporte le document. Rend le nombre de tracés écrits.

    `kind` vaut `dxf`, `eps`, `ai`, `svg` ou `pdf` ; à défaut il est
    déduit du suffixe.
    `toolpaths` choisit les trajectoires plutôt que les contours.
    """
    kind = kind or suffix_format(path)
    couches = (toolpath_layers(document, visible_only=visible_only)
               if toolpaths
               else drawing_layers(document, visible_only=visible_only))
    if not couches:
        raise ExportError('rien à exporter : aucune forme visible.')
    if kind == 'dxf':
        return write_dxf(couches, path)
    if kind in ('eps', 'ai'):
        return write_eps(couches, path, title=document.name or 'TauDrive',
                         illustrator=(kind == 'ai'))
    if kind == 'svg':
        return write_svg(couches, path, title=document.name or 'TauDrive')
    if kind == 'pdf':
        return write_pdf(couches, path, title=document.name or 'TauDrive')
    raise ExportError(f'format inconnu : {kind}')


# --------------------------------------------------------------------------
# Choix de l'export
# --------------------------------------------------------------------------

class VectorExportDialog(QDialog):
    """Format, et contenu : le dessin ou les trajectoires.

    Deux questions, et le poids annoncé pour chacune — un export de
    trajectoires est souvent cent fois plus lourd qu'un export de dessin,
    et l'apprendre après coup n'aide personne.
    """

    def __init__(self, parent, document: Document) -> None:
        super().__init__(parent)
        self.setWindowTitle('Exporter le dessin')
        self.setMinimumWidth(440)
        self._document = document

        dehors = QVBoxLayout(self)
        dehors.addWidget(QLabel(
            'Pour un bureau d\'études, un client, un graphiste.<br>'
            f"{theme.span()}L'export machine — ISO et "
            "CLJOB — reste sur le bouton <b>Exporter</b>.</span>"))

        form = QFormLayout()
        self.w_format = QComboBox()
        for cle, libelle, _ in FORMATS:
            self.w_format.addItem(f'{libelle}   (.{cle})', cle)
        self.w_format.setToolTip(
            'DXF pour la CAO, EPS pour l\'impression et le dessin, '
            'AI pour Illustrator.')
        form.addRow('Format', self.w_format)

        self.w_content = QComboBox()
        self.w_content.addItem('Dessin — les contours posés', False)
        self.w_content.addItem(
            'Trajectoires — tout ce qui part à la machine', True)
        self.w_content.setToolTip(
            'Le dessin s\'ouvre et se reprend ; les trajectoires '
            'montrent exactement ce qui sera gravé, hachurage et '
            'oscillation compris.')
        self.w_content.currentIndexChanged.connect(self._describe)
        form.addRow('Contenu', self.w_content)
        dehors.addLayout(form)

        self.w_note = QLabel('')
        self.w_note.setWordWrap(True)
        self.w_note.setStyleSheet(theme.css())
        dehors.addWidget(self.w_note)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText(
            'Choisir le fichier…')
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        dehors.addWidget(boutons)
        self._describe()

    def _describe(self) -> None:
        """Annonce le nombre de tracés — donc le poids — avant de partir."""
        try:
            couches = (toolpath_layers(self._document)
                       if self.w_content.currentData()
                       else drawing_layers(self._document))
        except Exception:
            self.w_note.setText('')
            return
        traces = sum(len(c) for _, c in couches)
        points = sum(len(p) for _, c in couches for p in c)
        self.w_note.setText(
            f'{len(couches)} calque(s) · {traces} tracé(s) · '
            f'{points} points')

    def choice(self) -> tuple[str, bool]:
        return (self.w_format.currentData() or 'dxf',
                bool(self.w_content.currentData()))
