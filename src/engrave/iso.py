"""Export au dialecte ISO Cielle + CLJOB / Cielle ISO + CLJOB export.

Reproduit le format observé dans `cl_iso/EASY_LASER_*.ISO` et
`EASY_LASER2.CLJOB` d'une TAU 10×10 SMART :

    (INGOMBROFOGLIO:x1, y1, x2, y2)
    T62 (nom,STELO: 6.000, BASE: 0.030, ROT: 0)
    S10000
    G108 P100.000 I80000.00        <- puissance % et fréquence en Hz
    G00X..Y..                      <- déplacement à vide
    G00Z0.000000                   <- pose (laser actif)
    F80000                         <- vitesse
    G01X..Y..                      <- gravure
    G00Z-0.001000                  <- lève

Les fichiers produits sont exécutés par ClTerm, le logiciel de commande
de la machine, avec ses propres sécurités : TauDrive ne pilote pas la
carte.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
from array import array
from itertools import chain

from . import variables
from .model import Document
from .toolpath import Pass, _millions, _refus_dense, _virgule, build_passes

#: Alphabet des noms de fichiers et de dossiers : celui de la machine.
#:
#: Les siens s'appellent `EASY_LASER_Z0001_2.ISO` — **ni espace, ni point
#: avant l'extension**, sur les sept fichiers livrés. Les nôtres qui ont
#: gravé s'appelaient `gravure_Z0001.ISO` : même alphabet, par hasard.
#:
#: Un coupon nommé « Coupon Balayage  Pz0.1 » produisait au contraire
#: `Coupon Balayage  Pz0.1_Z0001.ISO` — deux espaces consécutifs et un
#: point au milieu. Un analyseur qui coupe l'extension au **premier**
#: point y cherche « Coupon Balayage  Pz0 », ne le trouve pas, et ne dit
#: rien.
_SAFE = re.compile(r'[^A-Za-z0-9_-]+')


def sanitize(name: str, fallback: str = 'gravure') -> str:
    """Nom de fichier sûr, dans l'alphabet strict de la machine.

    **En ASCII**, comme tout ce qui part à la machine : le nom se retrouve
    dans le chemin que le CLJOB donne à ClTerm, et un accent y serait le
    même pari que dans un commentaire ISO. Espaces et points deviennent
    des soulignés — le seul point d'un nom de fichier doit être celui de
    son extension.
    """
    cleaned = _SAFE.sub('_', ascii_only(name)).strip('_-')
    while '__' in cleaned:
        cleaned = cleaned.replace('__', '_')
    return cleaned[:60] or fallback


def render_template(template: str, document: Document,
                    when: dt.datetime | None = None) -> str:
    """Développe les champs d'un modèle de chemin.

    Champs acceptés : `{job}`, `{date}` (aammjj), `{time}` (hhmmss) et
    `{year}`. Un champ inconnu est laissé tel quel plutôt que de faire
    échouer l'export : un modèle mal tapé doit se voir dans le chemin
    produit, pas sous forme d'exception au moment d'exporter.
    """
    moment = when or dt.datetime.now()
    values = {
        'job': sanitize(document.name),
        'date': moment.strftime('%y%m%d'),
        'time': moment.strftime('%H%M%S'),
        'year': moment.strftime('%Y'),
    }
    out = template
    for key, value in values.items():
        out = out.replace('{' + key + '}', value)
    return out


def unique_folder(base: pathlib.Path, name: str, limit: int = 999) -> str:
    """Nom libre dans `base` : `name`, puis `name-02`, `name-03`…

    Le rang est ajouté **au dossier**, pas aux fichiers : les noms des ISO
    et du CLJOB restent ceux du travail, et le CLJOB continue de désigner
    ses propres fichiers dans son propre dossier.
    """
    if not (base / name).exists():
        return name
    for rank in range(2, limit + 1):
        candidate = f'{name}-{rank:02d}'
        if not (base / candidate).exists():
            return candidate
    return f'{name}-{limit}'


def replace_tail(path: str, name: str) -> str:
    """Remplace le dernier segment d'un chemin par `name`.

    Sert à faire suivre au chemin machine le nom de dossier réellement
    retenu : après une numérotation automatique, le CLJOB doit désigner
    `…-02`, pas le dossier d'origine.
    """
    trimmed = path.rstrip('\\/')
    cut = max(trimmed.rfind('\\'), trimmed.rfind('/'))
    return (trimmed[:cut + 1] + name) if cut >= 0 else name


def job_folder_name(document: Document,
                    when: dt.datetime | None = None,
                    template: str = '') -> str:
    """Nom du dossier d'un travail.

    C'est le **dernier segment du chemin machine** : les deux ne peuvent
    pas diverger, et le CLJOB désigne donc toujours le dossier où les
    fichiers viennent d'être écrits — vu depuis la machine.
    """
    if template:
        rendered = render_template(template, document, when).rstrip('\\/')
        tail = re.split(r'[\\/]', rendered)[-1]
        if tail:
            return sanitize(tail)
    stamp = (when or dt.datetime.now()).strftime('%Y%m%d-%H%M%S')
    return f'{sanitize(document.name)}_{stamp}'

#: Cotes Z du dialecte : poser / lever l'outil.
Z_DOWN = 0.0
Z_UP = -0.001

#: Régime broche émis par IncicamWIN, conservé tel quel.
SPINDLE = 10000


def _fmt(value: float) -> str:
    return f'{value:.6f}'


#: Substitutions vers l'ASCII pur.
#:
#: Les fichiers produits par la machine — sept `.ISO` et leur `.CLJOB` —
#: ne contiennent **pas un seul octet au-dessus de 127**. On s'aligne
#: exactement dessus : ce que ClTerm n'a jamais eu à lire, il n'a
#: peut-être jamais appris à le lire.
_TRANSLIT = str.maketrans({
    '—': '-', '–': '-', '‘': "'", '’': "'",
    '“': '"', '”': '"', '…': '...', ' ': ' ',
    '×': 'x', '→': '->', '≤': '<=', '≥': '>=',
    '·': '-', '•': '-', '°': 'deg', '±': '+-', 'µ': 'u',
    '€': 'EUR', '«': '"', '»': '"', 'Ø': 'D', 'ø': 'd',
    'à': 'a', 'â': 'a', 'ä': 'a', 'á': 'a', 'å': 'a', 'ã': 'a',
    'ç': 'c', 'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
    'î': 'i', 'ï': 'i', 'í': 'i', 'ì': 'i',
    'ô': 'o', 'ö': 'o', 'ó': 'o', 'ò': 'o', 'õ': 'o',
    'ù': 'u', 'û': 'u', 'ü': 'u', 'ú': 'u',
    'ÿ': 'y', 'ý': 'y', 'ñ': 'n', 'œ': 'oe', 'æ': 'ae', 'ß': 'ss',
    'À': 'A', 'Â': 'A', 'Ä': 'A', 'Á': 'A', 'Å': 'A', 'Ã': 'A',
    'Ç': 'C', 'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
    'Î': 'I', 'Ï': 'I', 'Í': 'I', 'Ì': 'I',
    'Ô': 'O', 'Ö': 'O', 'Ó': 'O', 'Ò': 'O', 'Õ': 'O',
    'Ù': 'U', 'Û': 'U', 'Ü': 'U', 'Ú': 'U',
    'Ÿ': 'Y', 'Ý': 'Y', 'Ñ': 'N', 'Œ': 'OE', 'Æ': 'AE',
})


def ascii_only(text: str) -> str:
    """Translittère vers l'ASCII ; ce qui résiste devient `?`.

    Aucun fichier produit par la machine ne porte d'octet au-dessus de
    127 : ni les `.ISO`, ni le `.CLJOB`. Une recette nommée
    « Laiton — gravure · 20 % » y écrivait pourtant un `·` (0xB7), et le
    nom du travail un `é` — sans que rien ne garantisse que ClTerm sache
    les lire. Ils sont désormais translittérés.
    """
    return (text or '').translate(_TRANSLIT).encode(
        'ascii', 'replace').decode('ascii')


#: Tout ce que la machine écrit dans un `.ISO`, et rien de plus.
#:
#: Relevé sur les sept fichiers livrés : lettres, chiffres, espace, et
#: `( ) , - . : = _`. Aucun autre caractère, sur 22 Mo de G-code.
#:
#: La règle n'est pas cosmétique. Un coupon nommé « 100% / 40000mm/min »
#: introduisait deux caractères que la machine n'émet jamais : le `%` et
#: le `/`. Or **`/` est le caractère de saut de bloc du dialecte ISO** et
#: `%` en est, ailleurs, le délimiteur de programme. Un analyseur qui les
#: traite avant d'ouvrir le commentaire saute la ligne, ou le fichier.
_HORS_ALPHABET = re.compile(r'[^A-Za-z0-9 ,\-.:=_]')

#: Substitutions propres aux **commentaires**, jamais aux chemins.
#:
#: Le `/` et l'antislash séparent les dossiers : les translittérer partout
#: transformait `C:\TauDrive\...` en `C:-TauDrive-...` et le CLJOB ne
#: désignait plus rien. Ces remplacements n'ont de sens que dans du texte
#: libre.
_TRANSLIT_COMMENT = str.maketrans({
    '%': ' pc', '/': '-', '\\': '-', '|': '-', '&': ' et ',
})


def comment(text: str, limit: int = 120) -> str:
    """Rend un texte utilisable dans un commentaire ISO.

    Quatre contraintes, toutes capables de gâcher un fichier :

    * les **parenthèses** délimitent les commentaires du dialecte ; une
      parenthèse fermante venue d'un nom d'outil terminerait le
      commentaire par anticipation et la suite serait lue comme du
      G-code ;
    * le fichier est **en ASCII pur**, comme ceux de la machine ;
    * seul l'**alphabet que la machine emploie** est admis : ce qu'elle
      n'écrit jamais, rien ne garantit qu'elle sache le lire ;
    * la **coupe se fait sur une frontière de mot**. Tronquer au
      caractère près produisait des commentaires comme
      « Profondeur 0.02mm - Vit,STELO: 6.000 » : impossible de savoir si
      « Vit » est un mot coupé ou un nom d'outil.
    """
    text = ascii_only(text).translate(_TRANSLIT_COMMENT)
    text = _HORS_ALPHABET.sub('-', text)
    text = ' '.join(text.split())
    while '--' in text:
        text = text.replace('--', '-')
    if len(text) <= limit:
        return text
    coupe = text[:limit]
    espace = coupe.rfind(' ')
    # on ne remonte pas au-delà de la moitié : mieux vaut couper net que
    # de ne garder qu'un mot isolé là où il y avait une phrase
    return (coupe[:espace] if espace >= limit // 2 else coupe).rstrip(' -,;')


def render_iso(pass_: Pass, *, header_comment: str = '') -> str:
    """Un fichier ISO pour une passe."""
    lines: list[str] = []
    ajoute = lines.append

    xs = [x for poly in pass_.polylines for x, _ in poly]
    ys = [y for poly in pass_.polylines for _, y in poly]
    if xs:
        lines.append(f'(INGOMBROFOGLIO:{min(xs):.3f}, {min(ys):.3f}, '
                     f'{max(xs):.3f}, {max(ys):.3f})')
    lines.append('(Programma generatore: TauDrive)')
    if header_comment:
        lines.append(f'({comment(header_comment)})')

    r = pass_.recipe
    tool = (f'T{r.tool_number} ({comment(r.name, 40)},'
            f'STELO: 6.000, BASE: 0.030, ROT: 0)')
    lines.append(tool)
    lines.append(f'S{SPINDLE}')
    lines.append(f'G108 P{r.power_percent:.3f} I{r.frequency_khz * 1000:.2f}')
    lines.append(tool)

    # Cote de gravure de cette passe. `Z` n'est pas ici la position de
    # l'axe physique — celui-ci se commande à part — mais l'état de
    # l'outil : 0 posé, Z_UP levé, et plus négatif à mesure que les
    # passes s'enfoncent. C'est la convention des fichiers de la machine.
    z_down = Z_DOWN + min(0.0, pass_.z_mm)

    first = True
    pose, leve = f'G00Z{_fmt(z_down)}', f'G00Z{_fmt(Z_UP)}'
    for poly in pass_.polylines:
        if len(poly) < 2:
            continue
        x0, y0 = poly[0]
        ajoute(f'G00X{_fmt(x0)}Y{_fmt(y0)}')
        ajoute(pose)
        if first:
            ajoute(f'F{_vitesse(r.speed_mm_min)}')
            first = False
        # Une ligne par point : deux millions et demi sur un texte
        # oscillé. Le format y est écrit en ligne, sans l'appel à `_fmt`
        # deux fois par point : `%.6f` et `{:.6f}` passent par la même
        # conversion, le texte est le même, octet pour octet.
        lines.extend(['G01X%.6fY%.6f' % (x, y) for x, y in poly[1:]])
        ajoute(leve)

    return '\n'.join(lines) + '\n'


def _vitesse(v: float) -> str:
    """Le nombre du mot F : `{:g}`, comme toujours, tant qu'il est exact
    et sans exposant ; en clair sinon.

    `{:g}` n'a que six chiffres : 1 234 567 mm/min s'écrivait
    `F1.23457e+06`, une notation que le dialecte ISO ne connaît pas, et
    une vitesse arrondie."""
    texte = f'{v:g}'
    if 'e' in texte or float(texte) != v:
        texte = f'{v:.6f}'.rstrip('0').rstrip('.') or '0'
    return texte


def escape(texte: str) -> str:
    """`&`, `<` et `>` en entités XML — ce que fait
    `xml.sax.saxutils.escape`, à l'identique. L'importer chargeait
    `urllib.request` et `http.client` : 0,14 s à chaque démarrage, pour
    trois remplacements."""
    return (texte.replace('&', '&amp;').replace('>', '&gt;')
            .replace('<', '&lt;'))


def render_cljob(document: Document, iso_paths: list[str],
                 passes: list[Pass]) -> str:
    """Le CLJOB XML qui enchaîne les fichiers ISO.

    Le jeu de balises et leur ordre reproduisent **exactement** le fichier
    de référence de la machine (`EASY_LASER2.CLJOB`). ClTerm ne tolère pas
    l'omission : quatre balises d'en-tête et deux balises par bloc de
    travail manquaient, et le travail refusait de se charger alors que les
    fichiers ISO, eux, passaient sans problème.

    `INGOMBRO_TARGA` décrit la **plaque**, pas le dessin : c'est le support
    posé sur la machine. `CENTROLAVORO` place le travail dans le repère
    machine.
    """
    hw, hh = document.plate_w / 2, document.plate_h / 2

    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<LISTA_LAVORI>',
           '<TAG_JOB>2</TAG_JOB>', '<VERSIONEJOB>16</VERSIONEJOB>',
           '<ROTAZIONE>0.000000</ROTAZIONE>',
           '<NUMERO_LENTE_LASER>-1</NUMERO_LENTE_LASER>',
           f'<INGOMBRO_TARGA_X1>{_fmt(-hw)}</INGOMBRO_TARGA_X1>',
           f'<INGOMBRO_TARGA_X2>{_fmt(hw)}</INGOMBRO_TARGA_X2>',
           f'<INGOMBRO_TARGA_Y1>{_fmt(-hh)}</INGOMBRO_TARGA_Y1>',
           f'<INGOMBRO_TARGA_Y2>{_fmt(hh)}</INGOMBRO_TARGA_Y2>',
           '<RIFERIMENTOLAVOROX>0.000000</RIFERIMENTOLAVOROX>',
           '<RIFERIMENTOLAVOROY>0.000000</RIFERIMENTOLAVOROY>',
           '<RIFERIMENTOLAVOROZ>0.000000</RIFERIMENTOLAVOROZ>',
           '<USOMORSA>-1</USOMORSA>',
           '<QUOTARIFERIMENTOSUPERFICIE>0.000000</QUOTARIFERIMENTOSUPERFICIE>',
           '<INCLINAZIONE_MORSA>0.000000</INCLINAZIONE_MORSA>',
           '<NOME_ORIGINE></NOME_ORIGINE>',
           '<QUOTARIFERIMENTOSUPERFICIE_DRITTA>0.000000'
           '</QUOTARIFERIMENTOSUPERFICIE_DRITTA>',
           '<SPESSOREMATERIALE>0.000000</SPESSOREMATERIALE>',
           '<DESTINAZIONE_INCISIONE>-1</DESTINAZIONE_INCISIONE>',
           '<NUMERO_ZONE_TARGA_GRANDE>-1</NUMERO_ZONE_TARGA_GRANDE>',
           '<LUNGHEZZA_ZONA_TARGA_GRANDE>0.000000</LUNGHEZZA_ZONA_TARGA_GRANDE>',
           '<OFFSET_ZONA_TARGA_GRANDE>0.000000</OFFSET_ZONA_TARGA_GRANDE>',
           '<NUMEROCROCINI>0</NUMEROCROCINI>',
           '<TIPOPEZZO>-1</TIPOPEZZO>',
           f'<NOMEJOB>{escape(comment(document.name, 60))}</NOMEJOB>',
           f'<NUMERO_LAVORI>{len(iso_paths)}</NUMERO_LAVORI>']

    for path, p in zip(iso_paths, passes):
        out += ['<DESCRIZIONE_LAVORI>',
                f'<NOME>{escape(ascii_only(path))}</NOME>',
                f'<UTENSILE>{p.recipe.tool_number}</UTENSILE>',
                f'<LISTA_UTENSILI>{p.recipe.tool_number}</LISTA_UTENSILI>',
                '<MODECENTRO>0</MODECENTRO>',
                f'<CENTROLAVOROX>{_fmt(document.work_center_x)}</CENTROLAVOROX>',
                f'<CENTROLAVOROY>{_fmt(document.work_center_y)}</CENTROLAVOROY>',
                '<CENTROLAVOROZ>0.000000</CENTROLAVOROZ>',
                '<INCLINAZIONENX>0.000000</INCLINAZIONENX>',
                '<ROTAZIONENX>0.000000</ROTAZIONENX>',
                '<ROTAZIONEXY>0.000000</ROTAZIONEXY>',
                '<TGRANDELASER>1</TGRANDELASER>',
                '<FLAGLAVORO>0</FLAGLAVORO>',
                '<PROFSUMORSADRITTA>0.000000</PROFSUMORSADRITTA>',
                '<NOME_ENTITA_PREZIOSA></NOME_ENTITA_PREZIOSA>',
                '<ROTAZIONE_ENTITA_PREZIOSA>0.000000'
                '</ROTAZIONE_ENTITA_PREZIOSA>',
                f'<DESCRIZIONE_ENTITA>{escape(comment(p.source_name, 60))}</DESCRIZIONE_ENTITA>',
                '</DESCRIZIONE_LAVORI>']

    out.append('</LISTA_LAVORI>')
    return '\n'.join(out) + '\n'


def machine_path(out_dir: pathlib.Path | str,
                 machine_iso_dir: str | None) -> str:
    """Chemin **tel que la machine le verra**, sans barre oblique finale.

    `machine_iso_dir` vide ou absent : c'est le dossier d'écriture
    lui-même. C'est le cas normal quand on exporte sur un partage réseau
    que la machine sait lire — il n'y a alors **rien à recopier**, ClTerm
    ouvre les fichiers là où ils ont été écrits.

    On ne le renseigne que lorsque la machine voit ce dossier sous un
    autre nom : un lecteur mappé `Z:\\` là où le poste client emploie un
    chemin UNC `\\\\serveur\\gravure`, typiquement.
    """
    base = (machine_iso_dir or str(pathlib.Path(out_dir).resolve()))
    return base.rstrip('\\/')


#: Budget d'ordonnancement d'un export, en secondes de calcul — partagé
#: entre les pièces d'une série, compté en évaluations : voir
#: `ordering.EVALUATIONS_PAR_S`.
BUDGET_S = 1.0


def reglages_premiere_piece(document: Document,
                            now: dt.datetime | None = None) -> dict:
    """Ce que l'export donne à la construction de la première pièce : sa
    part du budget d'ordonnancement et ses champs variables.

    La vérification et le parcours rejoué s'en servent pour construire
    **exactement** ce qui part : l'ordonnancement ne dépend plus de
    l'horloge, deux constructions aux mêmes réglages rendent les mêmes
    passes.
    """
    pieces = max(1, int(document.copies))
    return {'time_budget_s': BUDGET_S / pieces,
            'context': contexte_piece(document, 0, now)}


def contexte_piece(document: Document, index: int,
                   now: dt.datetime | None = None) -> dict:
    """Les champs variables de la pièce `index` (0 pour la première),
    tels que l'export les donne.

    `now` : l'instant du travail. Un export le prend **une fois** et le
    donne à chaque pièce, relevé préalable compris : sinon une heure à la
    seconde, `{heure:%H:%M:%S}`, était vérifiée à 02:35:52 et écrite à
    02:35:54 — on vérifiait ce qui ne partait pas."""
    return variables.make_context(
        serial=document.serial_for(index), index=index + 1,
        total=max(1, int(document.copies)), job=sanitize(document.name),
        now=now)


def _verifie_pieces(document: Document,
                    now: dt.datetime | None = None) -> None:
    """Refuse, **avant toute écriture**, une série dont une pièce aurait
    une oscillation abandonnée — voir `toolpath.formes_trop_denses` — ou
    un code inencodable — voir `toolpath.codes_inencodables`. Le numéro
    qui ne tient plus dans un EAN-13 à la deuxième pièce laissait la
    première écrite, puis refusait la suite pour « document vide »."""
    from .toolpath import _refus_code, codes_inencodables, formes_trop_denses
    copies = max(1, int(document.copies))
    for index in range(copies):
        contexte = contexte_piece(document, index, now)
        denses = formes_trop_denses(document, contexte)
        if denses:
            raise _refus_dense(denses)
        refus = codes_inencodables(document, contexte,
                                   variables_seuls=index > 0)
        if refus:
            raise _refus_code(refus, index + 1 if copies > 1 else None)


def _passes_a_graver(document: Document, **options) -> list[Pass]:
    """Les passes du travail, **refusées** si une oscillation a dû être
    abandonnée.

    Le plan de travail montre alors le trait sans oscillation, pour ne
    pas se figer ; le graver ainsi serait faux — un trait fin à la place
    de la bande demandée. La vérification le bloque, mais elle peut être
    coupée, et l'export en morceaux ne passe pas par elle : c'est donc ici
    que le refus se tient. Voir `toolpath.dense_wobble`.
    """
    from .toolpath import _refus_code, codes_inencodables, dense_wobble
    with dense_wobble() as denses:
        passes = build_passes(document, **options)
    if denses:
        raise _refus_dense(denses)
    # un code inencodable est omis des passes : graver le reste sans lui
    # ne serait pas le travail demandé
    refus = codes_inencodables(document, options.get('context'))
    if refus:
        raise _refus_code(refus)
    return passes


def _empreinte(p: Pass) -> tuple:
    """De quoi reconnaître une passe : ses cotes à plat, la longueur de
    chacun de ses tracés, et ce que `render_iso` lit d'autre.

    Seize octets par point, quand la passe en retient une centaine sous
    forme de couples : garder la passe entière d'une pièce à l'autre
    alourdissait de 20 % le pic de mémoire d'une série. Les cotes se
    comparent comme les couples — `-0,0` égale `0,0`."""
    return (array('d', chain.from_iterable(chain.from_iterable(p.polylines))),
            array('q', map(len, p.polylines)),
            p.recipe, p.z_mm, p.source_name)


def _iso_de(p: Pass, rang, rendus: dict | None) -> str:
    """Le texte ISO de la passe `p`, au `rang` donné dans sa pièce.

    Dans une série, `rendus` garde celui de la pièce précédente au même
    rang, avec son empreinte : une passe qui n'a pas changé — un logo,
    une mention fixe — le reprend au lieu de le réécrire, ligne à ligne.
    Comparer les tracés coûte vingt fois moins que les mettre en texte.
    """
    if rendus is None:
        return render_iso(p, header_comment=p.source_name)
    empreinte = _empreinte(p)
    avant = rendus.get(rang)
    if avant is not None and avant[0] == empreinte:
        return avant[1]
    texte = render_iso(p, header_comment=p.source_name)
    rendus[rang] = (empreinte, texte)
    return texte


def export_piece(document: Document, out_dir: pathlib.Path, stem: str, *,
                 machine_iso_dir: str | None, optimize: bool,
                 group_by_recipe: bool, time_budget_s: float,
                 context: dict | None = None,
                 rendus: dict | None = None) -> list[pathlib.Path]:
    """Écrit les fichiers d'**une** pièce. Retourne les chemins créés.

    `rendus` : les ISO de la pièce précédente d'une série — voir
    `_iso_de`."""
    passes = _passes_a_graver(document, optimize=optimize,
                              group_by_recipe=group_by_recipe,
                              time_budget_s=time_budget_s, context=context)
    if not passes:
        raise ValueError('document vide : aucune trajectoire à exporter')

    written: list[pathlib.Path] = []
    machine_paths: list[str] = []
    base = machine_path(out_dir, machine_iso_dir)

    for i, p in enumerate(passes, 1):
        name = f'{stem}_Z{i:04d}.ISO'
        path = out_dir / name
        # `ascii` et non `latin1` : l'encodeur lève plutôt que d'écrire en
        # silence un octet que la machine n'émet jamais. Une régression se
        # verrait ici, pas trois semaines plus tard devant ClTerm.
        path.write_text(_iso_de(p, i, rendus), encoding='ascii')
        written.append(path)
        machine_paths.append(f'{base}\\{name}')

    job = out_dir / f'{stem}.CLJOB'
    job.write_text(render_cljob(document, machine_paths, passes),
                   encoding='utf-8')
    written.append(job)
    return written


def _ecrire_passes(document: Document, passes: list, out_dir: pathlib.Path,
                   stem: str, base: str, rendus: dict | None = None,
                   rang=None) -> list[pathlib.Path]:
    """Les `.ISO` d'une liste de passes et leur CLJOB, dans `out_dir`.

    `rendus` et `rang` : les ISO du même morceau dans la pièce précédente
    d'une série — voir `_iso_de`."""
    written: list[pathlib.Path] = []
    machine_paths: list[str] = []
    for i, p in enumerate(passes, 1):
        name = f'{stem}_Z{i:04d}.ISO'
        path = out_dir / name
        path.write_text(_iso_de(p, (rang, i), rendus), encoding='ascii')
        written.append(path)
        machine_paths.append(f'{base}\\{name}')
    job = out_dir / f'{stem}.CLJOB'
    job.write_text(render_cljob(document, machine_paths, passes),
                   encoding='utf-8')
    written.append(job)
    return written


#: Nom du fichier de consignes posé à la racine d'un export en morceaux.
CONSIGNES = 'CONSIGNES.txt'


def export_morceaux(document: Document, out_dir: str | pathlib.Path,
                    morceaux: list, *, marge_mm: float = 0.0,
                    marques: bool = False,
                    machine_iso_dir: str | None = None,
                    optimize: bool = True, group_by_recipe: bool = False,
                    time_budget_s: float = BUDGET_S) -> list[pathlib.Path]:
    """Écrit un travail plus grand que le champ, **un job par morceau**.

    Les passes sont construites une fois, comme à l'export ordinaire,
    puis coupées au bord de chaque morceau et recentrées — voir
    `engrave.morceaux`. Chaque morceau a son sous-dossier
    `<travail>_m01`, `_m02`… avec ses `.ISO` et son CLJOB ; les
    consignes de déplacement de la pièce sont écrites à la racine, dans
    `CONSIGNES.txt`, et rappelées en tête de chaque `.ISO`.

    Plusieurs pièces (`copies`) : un sous-dossier par pièce, et les
    morceaux dedans. Les consignes sont les mêmes pour chaque pièce.
    """
    from . import morceaux as _morceaux
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = sanitize(document.name)
    copies = max(1, int(document.copies))
    if not morceaux:
        raise ValueError('aucun morceau à exporter')
    now = dt.datetime.now()
    # refusé avant d'écrire les consignes : un refus ne laisse rien
    _verifie_pieces(document, now)
    texte = _morceaux.consignes(document, morceaux, stem, marge_mm, marques)
    written: list[pathlib.Path] = [out_dir / CONSIGNES]
    written[0].write_text(texte, encoding='utf-8')
    rendus: dict = {}

    def piece(dossier: pathlib.Path, piece_stem: str, machine_dir,
              context: dict) -> list[pathlib.Path]:
        passes = _passes_a_graver(
            document, optimize=optimize, group_by_recipe=group_by_recipe,
            time_budget_s=time_budget_s / max(1, copies), context=context)
        if not passes:
            raise ValueError('document vide : aucune trajectoire à exporter')
        sortie: list[pathlib.Path] = []
        n = len(morceaux)
        for m in morceaux:
            part = _morceaux.passes_du_morceau(passes, m)
            if marques:
                traits = _morceaux.marques_de_raccord(m)
                if traits:
                    part.append(Pass(recipe=passes[0].recipe,
                                     polylines=traits,
                                     source_name='traits de raccord'))
            if not part:
                continue                # un morceau vide : rien à graver
            morceau_stem = m.dossier(piece_stem)
            morceau_dir = dossier / morceau_stem
            morceau_dir.mkdir(parents=True, exist_ok=True)
            # sans « + » : le commentaire ISO ne l'admet pas et le
            # changerait en tiret, ce qui inverserait le sens
            entete = (f'morceau {m.rang}/{n} - deplacer piece '
                      f'X{m.dx:.1f} Y{m.dy:.1f}')
            part = [_avec_entete(p, entete) for p in part]
            base = machine_path(
                morceau_dir,
                f'{machine_dir.rstrip(chr(92) + "/")}\\{morceau_stem}'
                if machine_dir else None)
            sortie += _ecrire_passes(document, part, morceau_dir,
                                     morceau_stem, base, rendus, m.rang)
        return sortie

    if copies == 1:
        return written + piece(out_dir, stem, machine_iso_dir,
                               contexte_piece(document, 0, now))

    for index in range(copies):
        piece_stem = f'{stem}_p{index + 1:04d}'
        piece_dir = out_dir / piece_stem
        piece_dir.mkdir(parents=True, exist_ok=True)
        context = contexte_piece(document, index, now)
        written += piece(
            piece_dir, piece_stem,
            f'{machine_iso_dir.rstrip(chr(92) + "/")}\\{piece_stem}'
            if machine_iso_dir else None, context)
    return written


def _avec_entete(p: Pass, entete: str) -> Pass:
    """La passe avec la consigne du morceau en tête de son commentaire."""
    import dataclasses
    nom = f'{entete} - {p.source_name}' if p.source_name else entete
    return dataclasses.replace(p, source_name=nom)


def export(document: Document, out_dir: str | pathlib.Path, *,
           machine_iso_dir: str | None = None,
           optimize: bool = True, group_by_recipe: bool = False,
           time_budget_s: float = BUDGET_S) -> list[pathlib.Path]:
    """Écrit les fichiers du travail. Retourne les fichiers créés.

    Par défaut, le CLJOB désigne les `.ISO` **à l'endroit où ils viennent
    d'être écrits**. Exporter sur un partage réseau que la machine sait
    lire suffit donc : il n'y a rien à recopier dans `C:\\inciwin\\cl_iso`,
    ClTerm ouvre les fichiers sur le partage.

    `machine_iso_dir` ne sert qu'au cas où la machine voit ce même dossier
    sous un autre nom — un lecteur mappé `Z:\\` face à un chemin UNC côté
    client. C'est alors ce chemin-là qui figure dans le CLJOB.

    Si le document déclare plusieurs pièces (`copies`), **un jeu complet
    est produit par pièce**, avec les champs variables réévalués : chaque
    pièce a son propre numéro de série. Les jeux sont nommés
    `<travail>_p0001`, `_p0002`… et rangés dans un sous-dossier par pièce
    pour rester lisibles côté machine.
    """
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Le nom du travail sert de **nom de fichier** : il passe par le même
    # tamis que les dossiers. Un travail nommé « Coupon Balayage  Pz0.1 »
    # produisait sinon `Coupon Balayage  Pz0.1_Z0001.ISO`, seul fichier de
    # toute la chaîne à porter des espaces et un point avant l'extension.
    stem = sanitize(document.name)
    copies = max(1, int(document.copies))
    # un seul instant pour tout le travail — voir `contexte_piece`
    now = dt.datetime.now()

    if copies == 1:
        context = contexte_piece(document, 0, now)
        return export_piece(document, out_dir, stem,
                            machine_iso_dir=machine_iso_dir,
                            optimize=optimize,
                            group_by_recipe=group_by_recipe,
                            time_budget_s=time_budget_s, context=context)

    # une pièce trop dense est refusée avant la première écrite : un
    # export refusé ne laisse pas une demi-série dans le dossier
    _verifie_pieces(document, now)

    # le budget est réparti entre les pièces : une série de 50 ne doit pas
    # coûter 50 fois le temps d'une pièce seule
    per_piece = time_budget_s / copies

    written: list[pathlib.Path] = []
    rendus: dict = {}
    for index in range(copies):
        piece_stem = f'{stem}_p{index + 1:04d}'
        piece_dir = out_dir / piece_stem
        piece_dir.mkdir(parents=True, exist_ok=True)
        context = contexte_piece(document, index, now)
        # chaque pièce a son sous-dossier ; s'il n'y a pas de chemin
        # machine imposé, `export_piece` prendra le dossier réel de la pièce
        written += export_piece(
            document, piece_dir, piece_stem,
            machine_iso_dir=(f'{machine_iso_dir.rstrip(chr(92) + "/")}'
                             f'\\{piece_stem}' if machine_iso_dir else None),
            optimize=optimize, group_by_recipe=group_by_recipe,
            time_budget_s=per_piece, context=context, rendus=rendus)
    return written
