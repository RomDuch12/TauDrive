"""Sérialisation des documents / Document serialization.

Format JSON stable, versionné, utilisé pour l'enregistrement local comme
pour l'échange d'un document entre deux postes.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import math
from typing import Any

from .model import (CODE_KINDS, ILLISIBLE, LONGUEUR_MAX_MM, Circle, Code,
                    Document, Path, Rect, Recipe, Shape, Text, _conformes,
                    _new_id, note_repair, recipe_from_dict, value_like)

FORMAT_VERSION = 1

_SHAPE_TYPES: dict[str, type[Shape]] = {'rect': Rect, 'text': Text,
                                        'path': Path, 'circle': Circle,
                                        'code': Code}


def _shape_kind(shape: Shape) -> str:
    for name, cls in _SHAPE_TYPES.items():
        if type(shape) is cls:
            return name
    raise TypeError(f'forme non sérialisable : {type(shape).__name__}')


def shape_to_dict(shape: Shape) -> dict[str, Any]:
    """Une forme, sous la même forme que dans un fichier.

    Sert aussi de presse-papiers : coller relit ce dictionnaire, donc rien
    ne peut se perdre entre copier et coller qui ne se perdrait pas déjà
    entre enregistrer et rouvrir.

    Les polylignes d'un tracé sont recopiées, mais pas leurs points :
    `dataclasses.asdict` refaisait chaque couple, un à un — 0,4 s pour un
    DXF de 400 000 points, à chaque état d'historique et à chaque
    instantané de session, et 26 Mo par état. Un couple est immuable : le
    partager ne change rien au contenu, et un état n'en pèse plus que 3.
    """
    trace = shape.polylines if isinstance(shape, Path) else None
    if trace:
        sans = copy.copy(shape)
        sans.polylines = []
        champs = dataclasses.asdict(sans)
        champs['polylines'] = [list(map(tuple, p)) for p in trace]
    else:
        champs = dataclasses.asdict(shape)
    return {
        # discriminant nommé `type` et non `kind` : un code 2D a son propre
        # champ `kind` — la symbologie — qui écrasait celui-ci
        'type': _shape_kind(shape),
        **{k: v for k, v in champs.items() if k != 'recipe'},
        'recipe': dataclasses.asdict(shape.recipe),
    }


def shape_from_dict(raw: dict[str, Any], *, new_id: bool = False,
                    report: list | None = None, where: str = '') -> Shape:
    """Relit une forme. `new_id` en fait une copie indépendante.

    Une valeur qui ne convient pas à son champ est remplacée par le défaut
    et notée dans `report` — voir `model.value_like`. Une forme dont le
    type est inconnu, ou qui n'est pas un dictionnaire, fait refuser le
    document : la laisser de côté graverait une pièce incomplète.
    """
    if not isinstance(raw, dict):
        raise ValueError(f'{where}forme illisible')
    # `kind` en repli : c'est le nom qu'employaient les documents écrits
    # avant l'arrivée des codes 2D
    kind = raw.get('type') or raw.get('kind')
    cls = _SHAPE_TYPES.get(kind) if isinstance(kind, str) else None
    if cls is None:
        raise ValueError(f'{where}forme inconnue : {kind!r}')
    if cls is Code and raw.get('kind', 'datamatrix') not in CODE_KINDS:
        # une symbologie inconnue — écrite par une version plus récente —
        # ne se dessinerait pas : le code disparaîtrait de la pièce sans
        # rien dire. Comme une forme inconnue, elle fait refuser.
        raise ValueError(f'{where}code inconnu : {raw.get("kind")!r:.40}')
    kwargs = _conformes(cls, raw, report, where,
                        exclus=('recipe', 'type', 'polylines', 'id'))
    ident = raw.get('id')
    if isinstance(ident, str) and ident:
        kwargs['id'] = ident
    # `recipe_from_dict` et non `Recipe(**…)` : la recette porte des
    # valeurs composées — le traitement — que seul lui sait reconstruire.
    # Bâtie directement, elle recevait un dictionnaire là où un objet
    # était attendu, et le traitement se perdait au premier rechargement.
    # absente, la process prend ses défauts — un document très ancien ;
    # présente mais illisible, elle les prend aussi, et cela se dit
    kwargs['recipe'] = recipe_from_dict(raw.get('recipe', {}), report,
                                        f'{where}process, ')
    if cls is Path:
        # JSON ne connaît pas le tuple : sans cette normalisation, les
        # points relus sont des listes, et tout ce qui les emploie comme
        # clé — le cache de géométrie en particulier — échoue.
        kwargs['polylines'] = _polylines(raw.get('polylines', []), report,
                                         where)
    shape = cls(**kwargs)
    if cls is Text and 'cap_measured' not in raw:
        # écrit avant la mesure de la capitale : il garde sa taille
        shape.cap_measured = False
    if cls is Text and 'anchored' not in raw:
        _anchor_old_text(shape)
    if new_id:
        shape.id = _new_id()
    return shape


def _polylines(brut, report: list | None, where: str) -> list:
    """Les polylignes d'un tracé, points illisibles écartés — et notés."""
    if not isinstance(brut, list):
        note_repair(report, f'{where}polylignes illisibles, retirées')
        return []
    sortie, ecartes = [], 0
    borne = LONGUEUR_MAX_MM
    for poly in brut:
        if not isinstance(poly, list):
            ecartes += 1
            continue
        points = []
        garde = points.append
        for point in poly:
            # Le cas courant d'abord : deux flottants dans la borne. Un
            # NaN échoue à toute comparaison, un infini à la borne : le
            # test est celui d'en dessous, trois fois plus vite — 0,7 s
            # pour relire un DXF de 400 000 points, à chaque ouverture et
            # à chaque « annuler ».
            if (type(point) is list or type(point) is tuple) \
                    and len(point) == 2:
                x, y = point
                if (type(x) is float and type(y) is float
                        and -borne <= x <= borne and -borne <= y <= borne):
                    garde((x, y))
                    continue
            # au-delà de dix mètres, un point ne se hachure plus en temps
            # fini — voir `model.LONGUEUR_MAX_MM`
            if (isinstance(point, (list, tuple)) and len(point) == 2
                    and all(isinstance(c, (int, float))
                            and not isinstance(c, bool) and math.isfinite(c)
                            and abs(c) <= LONGUEUR_MAX_MM
                            for c in point)):
                garde((float(point[0]), float(point[1])))
            else:
                ecartes += 1
        if points:
            sortie.append(points)
        else:
            ecartes += 1                    # un tracé vide se dit aussi
    if ecartes:
        note_repair(report, f'{where}{ecartes} point(s) ou tracé(s) '
                            f'illisible(s) écarté(s)')
    return sortie


def _anchor_old_text(shape: Text) -> None:
    """Un texte d'avant l'ancrage garde sa place à l'écran.

    Jusqu'en septembre 2026, un bloc de texte était **toujours centré**
    sur son origine, et l'alignement ne jouait qu'entre les lignes d'un
    bloc. Depuis, un texte aligné à gauche a son origine au bord gauche
    — c'est ce qui lui permet de pousser vers la droite quand on le
    rallonge. Relu tel quel, un texte ancien aligné à gauche aurait
    donc sauté d'une demi-largeur : on décale son origine d'autant, dans
    le sens de sa rotation, et rien ne bouge à l'écran.

    Un document écrit par une version antérieure se reconnaît à
    l'absence du champ `anchored` — et non à un numéro de format, pour
    que les fichiers écrits ici restent lisibles par l'ancienne version.
    """
    import math
    from . import textvec, variables
    shape.anchored = True
    if shape.align not in ('left', 'right'):
        return
    try:
        texte = variables.expand(shape.text, variables.make_context())
        decalage = textvec.anchor_shift(texte, shape.size_mm,
                                        shape.font_path, shape.align,
                                        measured=shape.cap_measured)
    except Exception as exc:                          # noqa: BLE001
        from .avale import avale
        avale('relecture : ancrage d\'un texte ancien', exc)
        return
    decalage *= shape.stretch
    if not decalage:
        return
    angle = math.radians(shape.rotation_deg)
    shape.x += decalage * math.cos(angle)
    shape.y += decalage * math.sin(angle)


def document_to_dict(document: Document) -> dict[str, Any]:
    return {
        'format': FORMAT_VERSION,
        'name': document.name,
        'field_w': document.field_w,
        'field_h': document.field_h,
        'work_center_x': document.work_center_x,
        'work_center_y': document.work_center_y,
        'plate_w': document.plate_w,
        'plate_h': document.plate_h,
        'copies': document.copies,
        'serial_start': document.serial_start,
        'serial_step': document.serial_step,
        'coupon': dict(document.coupon),
        # La process du moment, pour que rouvrir le travail la retrouve.
        # Une version antérieure ignore la clé : elle ne lit que les
        # champs qu'elle connaît.
        'last_recipe': (dataclasses.asdict(document.last_recipe)
                        if document.last_recipe is not None else None),
        'shapes': [shape_to_dict(s) for s in document.shapes],
    }


def document_from_dict(data: dict[str, Any],
                       report: list | None = None) -> Document:
    """Relit un document. `report` reçoit, s'il est donné, chaque valeur
    illisible remplacée par son défaut — voir `model.value_like` ;
    l'appelant les montre avant qu'on grave."""
    if not isinstance(data, dict):
        raise ValueError('document illisible')
    version = data.get('format', 1)
    if isinstance(version, bool) or not isinstance(version, (int, float)):
        # un format illisible n'empêche pas de lire : relu comme le premier
        note_repair(report, f'document : format = {version!r:.40}')
    elif version > FORMAT_VERSION:
        raise ValueError(
            f'document au format {version}, cette version en gère {FORMAT_VERSION}')

    def nombre(cle: str, defaut, entier: bool = False):
        if cle not in data:
            return defaut
        v = value_like(cle, defaut, data[cle])
        if v is ILLISIBLE:
            note_repair(report, f'document : {cle} = {data[cle]!r:.40}')
            return defaut
        return int(v) if entier else float(v)

    nom = data.get('name', 'gravure')
    document = Document(
        name=nom if isinstance(nom, str) else 'gravure',
        field_w=nombre('field_w', 110.0),
        field_h=nombre('field_h', 110.0),
        work_center_x=nombre('work_center_x', 50.0),
        work_center_y=nombre('work_center_y', 50.0),
        plate_w=nombre('plate_w', 100.0),
        plate_h=nombre('plate_h', 100.0),
        copies=max(1, nombre('copies', 1, entier=True)),
        serial_start=nombre('serial_start', 1, entier=True),
        serial_step=nombre('serial_step', 1, entier=True),
    )
    reglages = data.get('coupon')
    if isinstance(reglages, dict):
        document.coupon = dict(reglages)
    derniere = data.get('last_recipe')
    if isinstance(derniere, dict):
        document.last_recipe = recipe_from_dict(derniere, report,
                                                'dernière process, ')

    formes = data.get('shapes', [])
    if not isinstance(formes, list):
        raise ValueError('liste des formes illisible')
    for rang, raw in enumerate(formes):
        document.shapes.append(shape_from_dict(
            raw, report=report, where=f'forme {rang + 1} : '))

    return document


def dumps(document: Document, *, indent: int | None = 1) -> str:
    return json.dumps(document_to_dict(document), ensure_ascii=False,
                      indent=indent)


def loads(text: str, report: list | None = None) -> Document:
    return document_from_dict(json.loads(text), report)
