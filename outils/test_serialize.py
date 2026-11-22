"""Validation de la sérialisation des documents : aller-retour et format futur.

Reprend la partie de l'ancien `test_spool.py` qui porte sur du code
vivant. Le spouleur réseau qu'il testait aussi a été retiré le
27 août 2026 (EX-90 et EX-91) ; son code est archivé dans
`retire-serveur-260827.zip`.

Usage : python test_serialize.py
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from engrave import serialize                                    # noqa: E402
from engrave.model import Document, PRESET_RECIPES, Rect, Text    # noqa: E402
from engrave.toolpath import build_passes, total_length_mm        # noqa: E402


def check(label, got, want) -> bool:
    ok = got == want
    print(f'  [{"OK " if ok else "KO "}] {label}')
    if not ok:
        print(f'         obtenu : {got!r}\n         attendu: {want!r}')
    return ok


def sample_document(name='essai') -> Document:
    d = Document(name=name)
    d.add(Rect(x=1, y=2, width=20, height=10, recipe=PRESET_RECIPES[1]))
    d.add(Text(x=0, y=15, text='TAU', size_mm=6, rotation_deg=15,
               recipe=dataclasses.replace(PRESET_RECIPES[0], hatch_mm=0.4)))
    return d


def main() -> int:
    r = []

    print('sérialisation :')
    doc = sample_document()
    clone = serialize.loads(serialize.dumps(doc))
    r.append(check('nom conservé', clone.name, doc.name))
    r.append(check('formes conservées', len(clone.shapes), 2))
    r.append(check('géométrie conservée',
                   (clone.shapes[0].width, clone.shapes[0].x),
                   (doc.shapes[0].width, doc.shapes[0].x)))
    r.append(check('rotation conservée', clone.shapes[1].rotation_deg, 15))
    r.append(check('recette conservée', clone.shapes[1].recipe.hatch_mm, 0.4))
    r.append(check('trajectoires identiques',
                   round(total_length_mm(build_passes(clone)), 6),
                   round(total_length_mm(build_passes(doc)), 6)))
    # Un document écrit par une version plus récente est refusé, plutôt que
    # relu de travers : seul ce test le vérifie.
    try:
        serialize.document_from_dict({'format': 99, 'shapes': []})
        r.append(check('format futur refusé', 'accepté', 'ValueError'))
    except ValueError:
        r.append(check('format futur refusé', True, True))

    total, ok = len(r), sum(r)
    print(f'\n{ok}/{total} contrôles passés')
    return 0 if ok == total else 1


if __name__ == '__main__':
    raise SystemExit(main())
