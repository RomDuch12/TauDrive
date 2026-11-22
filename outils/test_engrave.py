"""Validation de la chaîne géométrie -> trajectoires -> ISO/CLJOB.

Aucune machine ni interface requise.

Usage : python test_engrave.py
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from engrave import geometry as G                       # noqa: E402
from engrave import iso, serialize, textvec, variables   # noqa: E402
from engrave.model import (Circle, Document, PRESET_RECIPES, Path,   # noqa: E402
                           Rect, Recipe, Text, recipe_from_dict,
                           recipe_to_dict)
from engrave.toolpath import (build_passes, build_shape_pass,   # noqa: E402
                              geometry_key, shape_contours)

#: Process d'essai aux valeurs explicites : les contrôles de l'export (T7,
#: F50000) ne dépendent pas des préréglages, neutres au cœur libre. Les
#: valeurs d'un atelier s'éprouvent dans les essais de son plugin.
ESSAI = Recipe('Essai', 100.0, 80.0, 100, 50000.0, tool_number=7)


def check(label, got, want) -> bool:
    ok = got == want
    print(f'  [{"OK " if ok else "KO "}] {label}')
    if not ok:
        print(f'         obtenu : {got!r}\n         attendu: {want!r}')
    return ok


def dataclasses_replace_hatch(recipe: Recipe, hatch: float) -> Recipe:
    import dataclasses
    return dataclasses.replace(recipe, hatch_mm=hatch)


def dataclasses_replace_name(recipe: Recipe, name: str) -> Recipe:
    import dataclasses
    return dataclasses.replace(recipe, name=name)


def approx(label, got, want, tol=1e-6) -> bool:
    ok = abs(got - want) <= tol
    print(f'  [{"OK " if ok else "KO "}] {label}')
    if not ok:
        print(f'         obtenu : {got!r}\n         attendu: {want!r} ± {tol}')
    return ok


def main() -> int:
    r = []

    print('géométrie :')
    rect = G.rect_contour(20, 10)
    r.append(check('rectangle fermé', rect[0], rect[-1]))
    r.append(check('emprise du rectangle', G.bounds([rect]), (-10.0, -5.0, 10.0, 5.0)))
    rot = G.rotate(rect, 90)
    b = G.bounds([rot])
    r.append(approx('rotation 90° : largeur devient hauteur', b[3] - b[1], 20.0, 1e-9))

    print('\nhachurage (règle pair-impair) :')
    # anneau carré : extérieur 20x20, trou 10x10 -> une ligne médiane
    # traverse deux fois de la matière, 5 mm de chaque côté
    outer = G.rect_contour(20, 20)
    inner = G.rect_contour(10, 10)
    segs = G.hatch([outer, inner], step=1.0)
    mid = [s for s in segs if abs(s[0][1]) < 1e-9]
    r.append(check('le trou central est respecté', len(mid), 2))
    total = sum(abs(s[1][0] - s[0][0]) for s in mid)
    r.append(approx('longueur gravée sur la médiane', total, 10.0, 1e-6))
    r.append(check('hachurage désactivé si pas nul', G.hatch([outer], 0), []))

    print('\nvectorisation de texte :')
    try:
        contours = textvec.layout('AO', 8.0, '', 'center')
        r.append(check('contours produits', len(contours) >= 3, True))
        tb = G.bounds(contours)
        r.append(approx('hauteur de capitale ≈ 8 mm', tb[3] - tb[1], 8.0, 0.6))
        # Le centrage se fait sur la **largeur d'avance**, pas sur l'encre :
        # c'est le centrage typographique, celui qui aligne correctement
        # plusieurs lignes entre elles. L'encre peut donc être légèrement
        # décalée, de la différence des approches latérales.
        width = textvec.advance_width('AO', 8.0)
        r.append(approx('centré sur la largeur d\'avance', tb[0], -width / 2, 0.35))
        r.append(approx('encre proche du centre', (tb[0] + tb[2]) / 2, 0.0, 0.35))
    except textvec.FontNotFound as exc:
        print(f'  [--] police indisponible, test sauté ({exc})')

    print('\ntrajectoires :')
    doc = Document(name='essai')
    doc.add(Rect(x=0, y=0, width=20, height=10, recipe=ESSAI))
    doc.add(Text(x=0, y=20, text='AB', size_mm=5, recipe=PRESET_RECIPES[0]))
    passes = build_passes(doc)
    r.append(check('une passe par forme', len(passes), 2))
    r.append(check('recette conservée', passes[0].recipe.tool_number, 7))
    r.append(approx('périmètre du rectangle', passes[0].length_mm(), 60.0, 1e-6))

    doc2 = Document()
    doc2.add(Rect(width=10, height=10, recipe=Recipe(passes=3)))
    r.append(check('3 passages -> 3 passes', len(build_passes(doc2)), 3))

    print('\nordonnancement des trajectoires :')
    from engrave import ordering                                  # noqa: E402
    from engrave.toolpath import total_travel_mm                  # noqa: E402

    # quatre segments volontairement dans le pire ordre possible
    segs = [[(0, 0), (10, 0)], [(0, 3), (10, 3)],
            [(10, 1), (0, 1)], [(10, 2), (0, 2)]]
    scrambled = [segs[0], segs[1], segs[2], segs[3]]
    opt = ordering.optimize(scrambled, time_budget_s=0.2)
    r.append(check('aucune polyligne perdue', len(opt), 4))
    r.append(check('trajet à vide réduit',
                   ordering.travel_distance(opt)
                   < ordering.travel_distance(scrambled), True))
    r.append(check('polylignes fermées non inversées',
                   ordering.is_closed(G.rect_contour(4, 4)), True))

    hatched = Document()
    hatched.add(Text(x=0, y=0, text='ABC', size_mm=10,
                     recipe=dataclasses_replace_hatch(PRESET_RECIPES[1], 0.3)))
    raw = build_passes(hatched)
    tidy = build_passes(hatched, optimize=True, time_budget_s=0.4)
    r.append(check('même nombre de polylignes après ordonnancement',
                   sum(len(p.polylines) for p in tidy),
                   sum(len(p.polylines) for p in raw)))
    r.append(check('gain réel sur du texte hachuré',
                   total_travel_mm(tidy) < total_travel_mm(raw) * 0.5, True))

    grouped = Document()
    for i in range(6):
        grouped.add(Rect(x=-20 + 8 * i, y=(-1) ** i * 10, width=5, height=5,
                         recipe=PRESET_RECIPES[1]))
    g_raw = build_passes(grouped)
    g_opt = build_passes(grouped, optimize=True, group_by_recipe=True,
                         time_budget_s=0.3)
    r.append(check('6 formes de même recette -> 1 passe', len(g_opt), 1))
    r.append(check('trajet inter-formes réduit',
                   total_travel_mm(g_opt) < total_travel_mm(g_raw), True))
    r.append(check('longueur gravée inchangée',
                   round(sum(p.length_mm() for p in g_opt), 6),
                   round(sum(p.length_mm() for p in g_raw), 6)))

    print('\nordonnancement : cas dégénérés :')
    # Une géométrie plate annule l'aire de l'emprise. Dimensionner la
    # grille de recherche dessus produisait une maille microscopique, donc
    # des dizaines de milliers de rangées — et une boucle sans fin.
    cases = {
        'liste vide': [],
        'une seule polyligne': [[(0, 0), (1, 1)]],
        'toutes au même point': [[(5, 5), (5, 5.1)] for _ in range(50)],
        'alignées en X': [[(i, 0), (i + 0.5, 0)] for i in range(200)],
        'alignées en Y': [[(0, i), (0, i + 0.5)] for i in range(200)],
        'deux amas éloignés': ([[(0, 0), (1, 0)]] * 40
                               + [[(900, 900), (901, 900)]] * 40),
        'contours fermés seuls': [G.rect_contour(2, 2) for _ in range(30)],
    }
    for label, polys in cases.items():
        start = time.perf_counter()
        result = ordering.nearest_neighbour(polys)
        elapsed = time.perf_counter() - start
        r.append(check(f'{label} — aucune perte', len(result), len(polys)))
        r.append(check(f'{label} — termine vite', elapsed < 2.0, True))

    print('\nchamp de marquage :')
    doc3 = Document()
    doc3.add(Rect(x=0, y=0, width=50, height=50))
    r.append(check('dans le champ', doc3.out_of_field(), False))
    doc3.add(Rect(x=60, y=0, width=50, height=50))
    r.append(check('hors champ détecté', doc3.out_of_field(), True))

    print('\nexport ISO / CLJOB :')
    with tempfile.TemporaryDirectory() as tmp:
        files = iso.export(doc, tmp)
        r.append(check('2 ISO + 1 CLJOB', len(files), 3))
        text = files[0].read_text(encoding='latin1')
        r.append(check('en-tête d\'emprise', text.startswith('(INGOMBROFOGLIO:'), True))
        r.append(check('outil émis', 'T7 (' in text, True))
        r.append(check('G108 puissance/fréquence en Hz',
                       'G108 P100.000 I80000.00' in text, True))
        r.append(check('vitesse F', '\nF50000\n' in text, True))
        r.append(check('pose outil', 'G00Z0.000000' in text, True))
        r.append(check('lève outil', 'G00Z-0.001000' in text, True))
        r.append(check('nombre de G01 (rectangle fermé)', text.count('G01X'), 4))

        job = files[-1].read_text(encoding='utf-8')
        r.append(check('CLJOB : 2 travaux',
                       '<NUMERO_LAVORI>2</NUMERO_LAVORI>' in job, True))
        # par défaut, le CLJOB désigne les ISO là où ils viennent d'être
        # écrits : exporter sur un partage réseau suffit, il n'y a rien à
        # recopier dans C:\inciwin\cl_iso
        r.append(check('CLJOB : ISO désignés dans le dossier d\'écriture',
                       str(pathlib.Path(tmp).resolve() / 'essai_Z0001.ISO')
                       in job, True))
        r.append(check('CLJOB : aucun chemin cl_iso imposé',
                       r'C:\inciwin\cl_iso' in job, False))
        r.append(check('CLJOB : outil', '<UTENSILE>7</UTENSILE>' in job, True))

    print('\ntexte multiligne et alignements :')
    block = textvec.layout('AAA\nBBB\nCCC', 10, '', 'center', 'middle', 1.4)
    single = textvec.layout('AAA', 10, '', 'center', 'middle', 1.4)
    bb, sb = G.bounds(block), G.bounds(single)
    r.append(check('3 lignes plus hautes qu\'une', bb[3] - bb[1] > sb[3] - sb[1], True))
    r.append(approx('bloc centré verticalement', (bb[1] + bb[3]) / 2, 0.0, 1e-6))
    top = G.bounds(textvec.layout('AAA\nBBB', 10, '', 'center', 'top'))
    r.append(approx('valign top : sommet à zéro', top[3], 0.0, 1e-6))
    wide = textvec.layout('W\nWWWWW', 10, '', 'left', 'top')
    first = [p for p in wide if max(y for _, y in p) > max(
        y for q in wide for _, y in q) - 9]
    fb = G.bounds(first)
    r.append(approx('align left : ligne courte à gauche du bloc',
                    fb[0], G.bounds(wide)[0], 1e-6))
    tight = G.bounds(textvec.layout('A\nB', 10, '', 'center', 'middle', 1.0))
    loose = G.bounds(textvec.layout('A\nB', 10, '', 'center', 'middle', 2.0))
    r.append(check('interligne pris en compte',
                   loose[3] - loose[1] > tight[3] - tight[1], True))

    print('\nchamps variables :')
    ctx = variables.make_context(serial=7, index=2, total=50, job='essai')
    r.append(check('numéro simple', variables.expand('n{n}', ctx), 'n7'))
    r.append(check('numéro complété', variables.expand('{n:04}', ctx), '0007'))
    r.append(check('index et total', variables.expand('{i}/{total}', ctx), '2/50'))
    r.append(check('accolade littérale', variables.expand('{{n}}', ctx), '{n}'))
    r.append(check('champ inconnu conservé',
                   variables.expand('{client}', ctx), '{client}'))
    r.append(check('champ inconnu signalé',
                   variables.unknown_fields('{client} {n}'), ['client']))

    print('\nsérialisation d\'un lot :')
    lot = Document(name='lot', copies=3, serial_start=100, serial_step=5)
    lot.add(Text(text='REF {n:04}', size_mm=5, recipe=PRESET_RECIPES[1]))
    r.append(check('numéros du lot',
                   [lot.serial_for(i) for i in range(3)], [100, 105, 110]))
    with tempfile.TemporaryDirectory() as tmp:
        files = iso.export(lot, tmp, time_budget_s=0.2)
        jobs = sorted(p.name for p in pathlib.Path(tmp).rglob('*.CLJOB'))
        r.append(check('un jeu par pièce', len(jobs), 3))
        texts = [pathlib.Path(tmp, f'lot_p{i:04d}', f'lot_p{i:04d}_Z0001.ISO')
                 .read_text(encoding='latin1') for i in (1, 3)]
        r.append(check('géométries différentes entre pièces',
                       texts[0] != texts[1], True))

    print('\ncommentaires ISO (encodage et parenthèses) :')
    r.append(check('parenthèses neutralisées',
                   iso.comment('Marqueur (repérage)'), 'Marqueur -reperage-'))
    r.append(check('tiret cadratin translittéré',
                   iso.comment('a — b'), 'a - b'))
    r.append(check('encodable en latin-1',
                   iso.comment('flèche → ×').encode('latin1', 'strict').decode('latin1'),
                   iso.comment('flèche → ×')))
    tricky = Document(name='piege')
    tricky.add(Rect(width=10, height=10, recipe=dataclasses_replace_name(
        PRESET_RECIPES[1], 'Laiton (3D) — ×2')))
    with tempfile.TemporaryDirectory() as tmp:
        files = iso.export(tricky, tmp, time_budget_s=0.1)
        text = files[0].read_text(encoding='latin1')
        r.append(check('aucune parenthèse déséquilibrée',
                       [l for l in text.splitlines()
                        if l.count('(') != l.count(')')], []))

    print('\ncadre de texte (gravure en positif) :')
    from engrave.toolpath import text_frame                       # noqa: E402
    plain = Text(text='TAU', size_mm=10,
                 recipe=dataclasses_replace_hatch(PRESET_RECIPES[1], 0.3))
    boxed = Text(text='TAU', size_mm=10, frame='rect', frame_margin_mm=3,
                 recipe=dataclasses_replace_hatch(PRESET_RECIPES[1], 0.3))
    round_ = Text(text='TAU', size_mm=10, frame='circle', frame_margin_mm=3,
                  recipe=dataclasses_replace_hatch(PRESET_RECIPES[1], 0.3))
    r.append(check('sans cadre, aucun contour ajouté',
                   len(shape_contours(boxed)) - len(shape_contours(plain)), 1))
    r.append(check('le cadre est le premier contour',
                   shape_contours(boxed)[0] == text_frame(
                       boxed, shape_contours(plain)), True))
    lp, lb, lc = (build_shape_pass(s).length_mm()
                  for s in (plain, boxed, round_))
    r.append(check('le cadre fait graver bien davantage', lb > lp * 3, True))
    r.append(check('le cercle englobe plus que le rectangle', lc > lb, True))

    fb = G.bounds(shape_contours(boxed))
    tb = G.bounds(shape_contours(plain))
    r.append(approx('marge respectée en largeur',
                    (fb[2] - fb[0]) - (tb[2] - tb[0]), 6.0, 1e-6))

    forced = Text(text='TAU', size_mm=10, frame='rect', frame_w=60, frame_h=20,
                  recipe=dataclasses_replace_hatch(PRESET_RECIPES[1], 0.3))
    fb = G.bounds([shape_contours(forced)[0]])
    r.append(approx('dimensions imposées : largeur', fb[2] - fb[0], 60.0, 1e-6))
    r.append(approx('dimensions imposées : hauteur', fb[3] - fb[1], 20.0, 1e-6))

    # une ligne de hachurage à mi-hauteur doit traverser cadre -> T -> A -> U
    # -> cadre, donc plusieurs segments : la matière part autour des lettres
    mid = [s for s in G.hatch(shape_contours(boxed), 0.3)
           if abs(s[0][1]) < 0.16]
    r.append(check('hachurage entre cadre et lettres', len(mid) >= 4, True))
    r.append(check('cadre sans hachurage : contours seuls',
                   len(build_shape_pass(
                       Text(text='TAU', size_mm=10, frame='rect')).polylines),
                   len(shape_contours(Text(text='TAU', size_mm=10,
                                           frame='rect')))))

    print('\ncercle :')
    circle = G.circle_contour(10)
    r.append(check('fermé', circle[0], circle[-1]))
    cb = G.bounds([circle])
    r.append(approx('diamètre', cb[2] - cb[0], 20.0, 0.05))
    r.append(check('plus de points pour un grand rayon',
                   len(G.circle_contour(100)) > len(G.circle_contour(2)), True))
    r.append(check('rayon nul refusé', G.circle_contour(0), []))

    print('\nformes importées :')
    imported = Document()
    imported.add(Path(polylines=[[(0, 0), (5, 0), (5, 5), (0, 0)]],
                      layer='CUT', source='x.dxf',
                      recipe=PRESET_RECIPES[1]))
    p_imported = build_passes(imported)
    r.append(check('une passe', len(p_imported), 1))
    r.append(approx('périmètre', p_imported[0].length_mm(), 5 + 5 + 50 ** 0.5, 1e-9))
    r.append(check('sérialisation aller-retour',
                   len(serialize.loads(serialize.dumps(imported)).shapes), 1))

    print('\nCLJOB : conformité au fichier de référence de la machine :')
    # ClTerm charge les fichiers ISO sans broncher mais refusait le CLJOB :
    # quatre balises d'en-tête et deux balises par bloc de travail
    # manquaient. Son analyseur est séquentiel, une omission décale tout.
    import re
    reference = (ROOT / 'captures' / '260817' / 'Sniff' / 'cl_iso'
                 / 'EASY_LASER2.CLJOB')
    if reference.is_file():
        ref = reference.read_text(encoding='utf-8', errors='replace')
        with tempfile.TemporaryDirectory() as tmp:
            mine = iso.export(doc, tmp)[-1].read_text(encoding='utf-8')

        def blocks(text):
            tags = [m.group(1) for m in re.finditer(r'<([A-Z_0-9]+)>', text)]
            marks = [i for i, t in enumerate(tags) if t == 'DESCRIZIONE_LAVORI']
            body = tags[marks[0] + 1:marks[1]] if len(marks) > 1 \
                else tags[marks[0] + 1:]
            return tags[:marks[0]], body

        ref_head, ref_body = blocks(ref)
        my_head, my_body = blocks(mine)
        r.append(check('en-tête : mêmes balises, même ordre', my_head, ref_head))
        r.append(check('bloc travail : mêmes balises, même ordre',
                       my_body, ref_body))

        def value(text, key):
            found = re.search(f'<{key}>([^<]*)<', text)
            return found.group(1) if found else None
        r.append(check('TAG_JOB', value(mine, 'TAG_JOB'), '2'))
        r.append(check('TGRANDELASER', value(mine, 'TGRANDELASER'), '1'))
        r.append(check('emprise plaque et non dessin',
                       value(mine, 'INGOMBRO_TARGA_X2'), '50.000000'))
    else:
        print('  [--] fichier de référence absent, test sauté')

    print('\nrelecture d\'un document enregistré :')
    from engrave.toolpath import geometry_key, local_polylines
    saved = Document(name='relu')
    saved.add(Path(polylines=[[(0, 0), (10, 0), (10, 4), (0, 0)]],
                   frame='rect', frame_margin_mm=1))
    saved.add(Rect(width=8, height=4))
    saved.add(Text(text='AB', size_mm=5, stretch=1.5))
    saved.group([s.id for s in saved.shapes[:2]])
    reread = serialize.loads(serialize.dumps(saved))

    # JSON ne connaît pas le tuple : sans normalisation à la relecture, les
    # points reviennent en listes et la clé du cache de géométrie devient
    # non hachable — l'application refusait alors de démarrer, la session
    # rouvrant les documents précédents dès la construction de la fenêtre.
    point = reread.shapes[0].polylines[0][0]
    r.append(check('points relus en tuples', isinstance(point, tuple), True))
    try:
        hash(geometry_key(reread.shapes[0]))
        r.append(check('clé de cache hachable', True, True))
    except TypeError as exc:
        r.append(check('clé de cache hachable', str(exc), True))
    r.append(check('trajectoires calculables après relecture',
                   len(local_polylines(reread.shapes[0])) >= 2, True))
    r.append(check('cadre conservé', reread.shapes[0].frame, 'rect'))
    r.append(check('groupe conservé',
                   reread.shapes[0].group == reread.shapes[1].group != '',
                   True))
    r.append(check('étirement conservé', reread.shapes[2].stretch, 1.5))

    print('\nexport sur dossier réseau :')
    doc = Document(name='reseau', shapes=[Rect(width=10, height=5,
                                               recipe=PRESET_RECIPES[1])])
    with tempfile.TemporaryDirectory() as tmp:
        job = iso.export(doc, tmp)[-1].read_text(encoding='utf-8')
        r.append(check('sans chemin imposé : le dossier réel',
                       str(pathlib.Path(tmp).resolve()) in job, True))

        # le poste machine voit le même partage sous un lecteur mappé
        job = iso.export(doc, tmp,
                         machine_iso_dir=r'Z:\gravure')[-1].read_text(
                             encoding='utf-8')
        r.append(check('chemin imposé : lecteur mappé',
                       r'Z:\gravure\reseau_Z0001.ISO' in job, True))
        r.append(check('barre oblique finale absorbée',
                       r'Z:\gravure\reseau_Z0001.ISO' in
                       iso.export(doc, tmp, machine_iso_dir='Z:\\gravure\\'
                                  )[-1].read_text(encoding='utf-8'), True))

        # une série range chaque pièce dans son sous-dossier : le chemin
        # machine doit suivre, sinon la deuxième pièce désigne les fichiers
        # de la première
        lot = Document(name='lot', copies=2,
                       shapes=[Rect(width=10, height=5,
                                    recipe=PRESET_RECIPES[1])])
        produced = iso.export(lot, tmp, machine_iso_dir=r'Z:\gravure',
                              time_budget_s=0.1)
        jobs = [p for p in produced if p.suffix == '.CLJOB']
        r.append(check('série : un CLJOB par pièce', len(jobs), 2))
        r.append(check('série : chaque pièce a son sous-dossier',
                       r'Z:\gravure\lot_p0002\lot_p0002_Z0001.ISO'
                       in jobs[1].read_text(encoding='utf-8'), True))

        produced = iso.export(lot, tmp, time_budget_s=0.1)
        jobs = [p for p in produced if p.suffix == '.CLJOB']
        r.append(check('série sans chemin imposé : dossier réel de la pièce',
                       str(pathlib.Path(tmp).resolve() / 'lot_p0002'
                           / 'lot_p0002_Z0001.ISO')
                       in jobs[1].read_text(encoding='utf-8'), True))

    print('\ncadre sur un tracé importé (négatif d\'un logo DXF) :')
    from engrave.toolpath import shape_frame
    logo = [[(-8, -4), (8, -4), (8, 4), (-8, 4), (-8, -4)],
            [(-3, -1), (3, -1), (3, 1), (-3, 1), (-3, -1)]]   # avec contre-forme
    plain = Path(polylines=[list(p) for p in logo])
    r.append(check('sans cadre : contours inchangés',
                   len(shape_contours(plain)), 2))

    boxed = Path(polylines=[list(p) for p in logo], frame='rect',
                 frame_margin_mm=2)
    contours = shape_contours(boxed)
    r.append(check('avec cadre : un contour de plus', len(contours), 3))
    r.append(check('le cadre est le premier contour',
                   contours[0], shape_frame(boxed, [list(p) for p in logo])))
    b = G.bounds([contours[0]])
    r.append(check('marge respectée en largeur',
                   (round(b[2] - b[0], 3), round(b[3] - b[1], 3)),
                   (20.0, 12.0)))

    round_ = Path(polylines=[list(p) for p in logo], frame='circle',
                  frame_margin_mm=2)
    b_round = G.bounds([shape_contours(round_)[0]])
    r.append(check('le cercle englobe plus que le rectangle',
                   (b_round[2] - b_round[0]) > (b[2] - b[0]), True))

    forced = Path(polylines=[list(p) for p in logo], frame='rect',
                  frame_w=40, frame_h=30)
    b_forced = G.bounds([shape_contours(forced)[0]])
    r.append(check('dimensions imposées',
                   (round(b_forced[2] - b_forced[0], 3),
                    round(b_forced[3] - b_forced[1], 3)), (40.0, 30.0)))

    hatched = Path(polylines=[list(p) for p in logo], frame='rect',
                   frame_margin_mm=2,
                   recipe=dataclasses_replace_hatch(PRESET_RECIPES[1], 0.4))
    creusé = build_shape_pass(hatched).length_mm()
    nu = build_shape_pass(
        Path(polylines=[list(p) for p in logo],
             recipe=dataclasses_replace_hatch(PRESET_RECIPES[1],
                                              0.4))).length_mm()
    r.append(check('le hachurage se place entre cadre et dessin',
                   creusé > nu, True))

    # la contre-forme doit rester épargnée : la règle pair-impair fait que
    # le trou intérieur du logo n'est pas rempli
    inside = [(x, y) for poly in build_shape_pass(hatched).polylines
              for x, y in poly if abs(x) < 2.5 and abs(y) < 0.5]
    r.append(check('contre-forme épargnée', inside, []))

    print('\ncadre et redimensionnement :')
    from engrave import resize as _resize
    framed = Path(polylines=[list(p) for p in logo], frame='rect',
                  frame_margin_mm=2)
    w0, h0 = _resize.local_size(framed)
    r.append(check('taille lue = celle du cadre', (w0, h0), (20.0, 12.0)))
    _resize.scale_shape(framed, 2.0, 2.0)
    w1, h1 = _resize.local_size(framed)
    r.append(check('cadre mis à l\'échelle avec le dessin',
                   (round(w1, 3), round(h1, 3)), (40.0, 24.0)))
    r.append(check('marge mise à l\'échelle', framed.frame_margin_mm, 4.0))

    print('\ncercles et ellipses :')
    circle = Circle(width=10, height=10)
    b = G.bounds(shape_contours(circle))
    r.append(check('cercle : emprise', (round(b[2] - b[0], 3),
                                        round(b[3] - b[1], 3)), (10.0, 10.0)))
    ellipse = Circle(width=20, height=6)
    b = G.bounds(shape_contours(ellipse))
    r.append(check('ellipse : emprise', (round(b[2] - b[0], 3),
                                         round(b[3] - b[1], 3)), (20.0, 6.0)))
    r.append(check('ellipse : nom', ellipse.default_name(), 'ellipse 20×6'))
    r.append(check('cercle : nom', Circle().default_name(), 'cercle ⌀20'))
    r.append(check('cercle : une passe',
                   len(build_passes(Document(shapes=[Circle(width=8,
                                                            height=8)]))), 1))

    print('\nredimensionnement (F2) :')
    from engrave import resize
    _resize = resize
    rect = Rect(width=20, height=10, x=5, y=0)
    resize.scale_shape(rect, 2.0, 3.0)
    r.append(check('rectangle mis à l\'échelle',
                   (rect.width, rect.height), (40.0, 30.0)))
    r.append(check('rectangle seul : ne bouge pas', (rect.x, rect.y), (5.0, 0.0)))

    reference = Text(text='AB', size_mm=10.0)
    w0, h0 = resize.local_size(reference)
    text = Text(text='AB', size_mm=10.0)
    resize.scale_shape(text, 2.0, 1.0)
    r.append(check('texte : hauteur de capitale inchangée', text.size_mm, 10.0))
    r.append(check('texte : étirement horizontal', text.stretch, 2.0))
    w1, h1 = resize.local_size(text)
    r.append(check('texte : largeur doublée', round(w1 / w0, 3), 2.0))
    r.append(check('texte : hauteur conservée', round(h1 - h0, 6), 0.0))

    path = Path(polylines=[[(0, 0), (10, 0), (10, 4)]])
    resize.scale_shape(path, 0.5, 0.5)
    r.append(check('tracé DXF mis à l\'échelle',
                   path.polylines[0][1], (5.0, 0.0)))

    left = Rect(width=10, height=10, x=-10, y=0)
    right = Rect(width=10, height=10, x=10, y=0)
    resize.scale_selection([left, right], 2.0, 2.0)
    r.append(check('sélection : écartée autour du centre commun',
                   (left.x, right.x), (-20.0, 20.0)))
    r.append(check('sélection : emprise doublée',
                   resize.selection_size([left, right])[0], 60.0))

    print('\ngroupes :')
    doc = Document(shapes=[Rect(), Rect(), Rect()])
    ids = [s.id for s in doc.shapes]
    key = doc.group(ids[:2])
    r.append(check('groupe créé', bool(key), True))
    r.append(check('sélection étendue au groupe',
                   sorted(doc.expand_selection([ids[0]])), sorted(ids[:2])))
    r.append(check('forme isolée non étendue',
                   doc.expand_selection([ids[2]]), [ids[2]]))
    doc.group([ids[1], ids[2]])          # absorbe le groupe existant
    r.append(check('groupes fusionnés',
                   sorted(doc.expand_selection([ids[2]])), sorted(ids)))
    r.append(check('dégroupage', doc.ungroup([ids[0]]), 3))
    r.append(check('plus aucun groupe',
                   [s.group for s in doc.shapes], ['', '', '']))
    r.append(check('grouper une seule forme refusé', doc.group([ids[0]]), None))

    print('\ndossier d\'export horodaté :')
    import datetime as _dt
    r.append(check(
        'nom de dossier assaini et horodaté',
        iso.job_folder_name(Document(name='Plaque n°2 / essai'),
                            _dt.datetime(2026, 8, 17, 14, 30, 5)),
        'Plaque_ndeg2_essai_20260817-143005'))

    print('\nbibliothèque de recettes :')
    import json as _json
    from engrave.model import recipe_from_dict, recipe_to_dict
    source = PRESET_RECIPES[1]
    round_trip = recipe_from_dict(_json.loads(_json.dumps(
        recipe_to_dict(source))))
    r.append(check('recette : aller-retour JSON', round_trip, source))
    r.append(check('champs inconnus ignorés',
                   recipe_from_dict({'name': 'x', 'inconnu': 1}).name, 'x'))

    print('\ncodes 2D dans un document :')
    from engrave.model import Code
    from engrave.toolpath import code_size
    code = Code(kind='datamatrix', data='TAU-1234-56', module_mm=0.5,
                quiet_modules=1, recipe=PRESET_RECIPES[1])
    rows, cols, w_mm, h_mm = code_size(code)
    r.append(check('DataMatrix : symbole carré', rows == cols > 0 and
                   abs(w_mm - h_mm) < 1e-9, True))
    r.append(check('taille = modules × pas',
                   round(w_mm, 6), round(cols * 0.5, 6)))
    r.append(check('une passe par code',
                   len(build_passes(Document(shapes=[code]))), 1))

    qr = Code(kind='qr', data='https://exemple.fr/p/1', module_mm=0.4,
              level='Q', quiet_modules=4, recipe=PRESET_RECIPES[1])
    r.append(check('QR : symbole plus grand qu\'un DataMatrix équivalent',
                   code_size(qr)[0] > rows, True))
    r.append(check('donnée impossible : aucun contour, pas d\'exception',
                   shape_contours(Code(kind='qr', data='Z' * 500)), []))

    # les champs variables valent aussi pour un code : c'est ce qui permet
    # de sérialiser une plaque par pièce
    from engrave import variables as _var
    numbered = Code(kind='datamatrix', data='PN-{n:05}', module_mm=0.5)
    a = code_size(numbered, _var.make_context(serial=1))
    b = code_size(numbered, _var.make_context(serial=2))
    r.append(check('champs variables encodés',
                   shape_contours(numbered, _var.make_context(serial=1))
                   != shape_contours(numbered, _var.make_context(serial=2)),
                   True))
    r.append(check('même taille d\'un numéro à l\'autre', a[0], b[0]))

    print('\ncode ajusté à une fenêtre (plaque de production) :')
    # Le DXF de production place un DataMatrix rectangulaire dans une
    # fenêtre de 15 x 7 mm ; c'est le cadre qui commande, pas le pas de
    # module. On vérifie que la géométrie produite tombe exactement dessus.
    fitted = Code(kind='datamatrix', dm_shape='rect', data='B000174',
                  quiet_modules=0, fit_w_mm=15.0, fit_h_mm=7.0,
                  recipe=PRESET_RECIPES[1])
    rows, cols, w_mm, h_mm = code_size(fitted)
    r.append(check('symbole 8 x 18', (rows, cols), (8, 18)))
    r.append(check('remplit la fenêtre au micron',
                   (round(w_mm, 6), round(h_mm, 6)), (15.0, 7.0)))
    b = G.bounds(shape_contours(fitted))
    r.append(check('emprise centrée sur l\'origine locale',
                   (round(b[0], 6), round(b[1], 6),
                    round(b[2], 6), round(b[3], 6)),
                   (-7.5, -3.5, 7.5, 3.5)))
    r.append(check('modules non carrés, comme sur la plaque',
                   round(w_mm / cols, 4) != round(h_mm / rows, 4), True))

    # sans fenêtre, c'est le pas de module qui commande
    free = Code(kind='datamatrix', dm_shape='rect', data='B000174',
                quiet_modules=0, module_mm=0.5)
    _, _, fw, fh = code_size(free)
    r.append(check('sans fenêtre : modules carrés',
                   (round(fw, 6), round(fh, 6)), (9.0, 4.0)))

    print('\ncodes linéaires dans un document :')
    bars = Code(kind='code39', data='TAU-42', module_mm=0.25,
                bar_height_mm=8.0, quiet_modules=10,
                recipe=PRESET_RECIPES[1])
    rows, cols, w_mm, h_mm = code_size(bars)
    r.append(check('une seule ligne de modules', rows, 1))
    r.append(check('hauteur = hauteur de barres', h_mm, 8.0))
    r.append(check('largeur = modules × pas', round(w_mm, 6),
                   round(cols * 0.25, 6)))
    r.append(check('une passe', len(build_passes(Document(shapes=[bars]))), 1))

    ean = Code(kind='ean13', data='978020137962', module_mm=0.33,
               bar_height_mm=10.0, quiet_modules=9)
    r.append(check('EAN-13 : 95 modules + 2 x 9 de silence',
                   code_size(ean)[1], 113))

    print('\ndossiers par défaut :')
    from engrave import session as _session
    # plus de dossier de spouleur : retiré avec le serveur le 27 août
    # 2026 (EX-90, EX-91 — voir retire-serveur-260827.zip)
    r.append(check('cinq usages paramétrables',
                   [k for k, _, _ in _session.FOLDER_KINDS],
                   ['documents', 'export', 'dxf', 'bibliotheque',
                    'archive']))

    print('\népaisseur de trait :')
    from engrave.toolpath import thicken, clear_cache
    line = [[(0.0, 0.0), (10.0, 0.0)]]
    r.append(check('épaisseur nulle : rien n\'est ajouté',
                   len(thicken(line, 0, 0.1)), 1))
    fat = thicken(line, 0.4, 0.1)
    r.append(check('0,4 mm au pas de 0,1 : 4 passages de plus',
                   len(fat), 5))
    ys = sorted({round(y, 6) for poly in fat for _, y in poly})
    r.append(check('passages répartis de part et d\'autre',
                   ys, [-0.2, -0.1, 0.0, 0.1, 0.2]))

    closed = [G.rect_contour(10, 6)]
    grown = thicken(closed, 0.4, 0.2)
    r.append(check('un contour fermé le reste',
                   all(poly[0] == poly[-1] for poly in grown), True))
    outer = G.bounds([grown[1]])
    inner = G.bounds([grown[2]])
    r.append(check('un passage vers l\'extérieur, l\'autre vers l\'intérieur',
                   (outer[2] - outer[0]) > 10 > (inner[2] - inner[0]), True))

    clear_cache()
    plain = Rect(width=10, height=6, recipe=PRESET_RECIPES[1])
    fat_rect = Rect(width=10, height=6, line_width_mm=0.4, line_step_mm=0.1,
                    recipe=PRESET_RECIPES[1])
    r.append(check('le trait épaissi grave davantage',
                   build_shape_pass(fat_rect).length_mm()
                   > build_shape_pass(plain).length_mm() * 4, True))
    r.append(check('l\'épaisseur entre dans la clé de cache',
                   geometry_key(plain) != geometry_key(fat_rect), True))

    print('\nun code se grave plein :')
    from engrave.toolpath import code_fill, clear_cache
    solid = Code(kind='datamatrix', dm_shape='rect', data='B000174',
                 quiet_modules=0, fit_w_mm=15.0, fit_h_mm=7.0,
                 recipe=PRESET_RECIPES[1])          # recette sans hachurage
    r.append(check('la recette ne hachure pas', solid.recipe.hatch_mm, 0.0))
    engraved = build_shape_pass(solid)
    r.append(check('le code est tout de même rempli',
                   engraved.length_mm() > 300, True))
    outline_only = sum(
        len(poly) for poly in shape_contours(solid))
    r.append(check('remplissage produit en plus des contours',
                   len(engraved.polylines) > outline_only / 5, True))

    # deux passages au minimum par module, même avec un pas absurde :
    # un seul trait laisserait une arête claire au milieu du carré
    absurd = Code(kind='datamatrix', data='AB', module_mm=1.0,
                  quiet_modules=0, fill_step_mm=10.0)
    from engrave import barcode as _bc
    from engrave.toolpath import code_matrix
    runs = len(_bc.runs(code_matrix(absurd)))
    r.append(check('deux passages par bande, même avec un pas grossier',
                   len(code_fill(absurd)), runs * 2))

    coarse = Code(kind='datamatrix', data='AB', module_mm=1.0,
                  quiet_modules=0, fill_step_mm=0.5)
    dense = Code(kind='datamatrix', data='AB', module_mm=1.0,
                 quiet_modules=0, fill_step_mm=0.1)
    r.append(check('un pas plus fin grave davantage',
                   len(code_fill(dense)) > len(code_fill(coarse)), True))
    r.append(check('le pas entre dans la clé de cache',
                   geometry_key(coarse) != geometry_key(dense), True))

    print('\nplaque codée : code et texte dans leurs cadres :')
    from engrave.codeplate import (build_plate, fit_text,   # noqa: E501
                                   frame_of, frames_of)

    # cotes relevées sur `DataMatrix.dxf` : deux cadres, le grand pour le
    # symbole, le petit pour le numéro en clair
    code_window = Rect(width=15.0, height=7.0, x=50.0, y=50.0)
    text_window = Rect(width=8.071, height=1.538, x=34.93, y=46.29)
    first, second = frames_of([text_window, code_window])
    r.append(check('la plus grande fenêtre revient au symbole',
                   (round(first[2], 3), round(first[3], 3)), (15.0, 7.0)))
    r.append(check('la plus petite revient au texte',
                   (round(second[2], 3), round(second[3], 3)),
                   (8.071, 1.538)))
    r.append(check('un rectangle donne ses cotes',
                   frame_of(code_window), (50.0, 50.0, 15.0, 7.0)))
    r.append(check('une forme sans cadre n\'en donne pas',
                   frame_of(Text(text='AB')), None))

    label = fit_text('B000174', 8.071, 1.538)
    box = G.bounds(shape_contours(label))
    r.append(check('le texte tient en largeur',
                   box[2] - box[0] <= 8.071 + 1e-6, True))
    r.append(check('le texte tient en hauteur',
                   box[3] - box[1] <= 1.538 + 1e-6, True))
    r.append(check('la police garde ses proportions', label.stretch, 1.0))

    stretched = fit_text('B000174', 8.071, 1.538, stretch_to_fill=True)
    box = G.bounds(shape_contours(stretched))
    r.append(check('étiré : remplit la largeur',
                   round(box[2] - box[0], 3), 8.071))
    r.append(check('étiré : tient encore en hauteur',
                   box[3] - box[1] <= 1.538 + 1e-6, True))

    narrow = fit_text('TEXTE BEAUCOUP TROP LONG', 8.0, 1.5)
    box = G.bounds(shape_contours(narrow))
    r.append(check('un texte trop long est réduit, jamais débordé',
                   box[2] - box[0] <= 8.0 + 1e-6
                   and box[3] - box[1] <= 1.5 + 1e-6, True))

    print('\ncode encadré : la gravure passe en négatif :')
    from engrave.toolpath import code_fill, code_matrix, clear_cache
    from engrave import barcode as _bc
    reglage = dict(kind='datamatrix', dm_shape='auto', data='B000174',
                   quiet_modules=0, fit_w_mm=15.0, fit_h_mm=7.0,
                   fill_step_mm=0.25, recipe=PRESET_RECIPES[1])
    positif = Code(**reglage)
    negatif = Code(**reglage, frame='rect', frame_margin_mm=1.0)

    lines_pos = code_fill(positif)
    lines_neg = code_fill(negatif)
    r.append(check('sans cadre : du remplissage', len(lines_pos) > 0, True))
    r.append(check('avec cadre : du remplissage aussi',
                   len(lines_neg) > 0, True))
    r.append(check('le négatif creuse davantage — le fond est plus grand '
                   'que les modules',
                   build_shape_pass(negatif).length_mm()
                   > build_shape_pass(positif).length_mm(), True))

    # au cœur d'un module sombre, le positif grave et le négatif épargne
    matrix = code_matrix(positif)
    rows, cols = len(matrix), len(matrix[0])
    mx, my = 15.0 / cols, 7.0 / rows

    def covered(lines, x, y, tol=1e-6):
        """Vrai si un trait de remplissage passe au point donné."""
        for (x1, y1), (x2, y2) in lines:
            if abs(y1 - y) <= my / 2 and min(x1, x2) - tol <= x <= max(x1, x2) + tol:
                return True
        return False

    dark = next((y, x) for y in range(rows) for x in range(cols) if matrix[y][x])
    light = next((y, x) for y in range(rows) for x in range(cols)
                 if not matrix[y][x])
    for label, (gy, gx), expect_pos, expect_neg in (
            ('module sombre', dark, True, False),
            ('module clair', light, False, True)):
        px = -15.0 / 2 + (gx + 0.5) * mx
        py = 7.0 / 2 - (gy + 0.5) * my
        r.append(check(f'{label} : gravé en positif',
                       covered(lines_pos, px, py), expect_pos))
        r.append(check(f'{label} : gravé en négatif',
                       covered(lines_neg, px, py), expect_neg))

    rond = Code(**reglage, frame='circle', frame_margin_mm=1.0)
    b_rect = G.bounds(shape_contours(negatif))
    b_rond = G.bounds(shape_contours(rond))
    r.append(check('un cadre rond englobe davantage',
                   (b_rond[2] - b_rond[0]) > (b_rect[2] - b_rect[0]), True))
    r.append(check('le remplissage rond reste dans son cercle',
                   all(abs(x) <= (b_rond[2] - b_rond[0]) / 2 + 1e-6
                       for poly in code_fill(rond) for x, _ in poly), True))
    clear_cache()

    print('\ncotes de la plaque de production :')
    from engrave.codeplate import (DEFAULT_CODE_WINDOW, DEFAULT_FRAME_MARGIN,
                                   DEFAULT_TEXT_OFFSET, DEFAULT_TEXT_WINDOW)
    from engrave.toolpath import code_contours, code_extent, shape_frame

    # Relevé sur `DataMatrix.dxf` : cadre du texte centré en (34,9285 ;
    # 26,272), cadre du code en (50 ; 30) — soit un écart de
    # (-15,0715 ; -3,728), arrondi aux cotes du bureau d'études.
    r.append(check('écart du texte au code', DEFAULT_TEXT_OFFSET,
                   (-15.07, -3.73)))
    r.append(check('fenêtre du texte', DEFAULT_TEXT_WINDOW, (8.071, 1.538)))
    r.append(check('fenêtre du code', DEFAULT_CODE_WINDOW, (15.0, 7.0)))
    r.append(check('marge du cadre', DEFAULT_FRAME_MARGIN, 0.5))

    plaque = build_plate(PRESET_RECIPES[1], data='B000174')
    r.append(check('un symbole et son texte',
                   [type(s).__name__ for s in plaque], ['Code', 'Text']))
    symbole, legende = plaque
    r.append(check('symbole à l\'origine', (symbole.x, symbole.y), (0.0, 0.0)))
    r.append(check('texte à -15,07 / -3,73',
                   (round(legende.x, 4), round(legende.y, 4)),
                   (-15.07, -3.73)))
    r.append(check('le texte reprend la donnée', legende.text, 'B000174'))

    # posé ailleurs, l'écart est conservé
    decale = build_plate(PRESET_RECIPES[1], frame=(40.0, -12.0, 15.0, 7.0),
                         data='B000174')
    r.append(check('écart conservé où qu\'on pose la plaque',
                   (round(decale[1].x - decale[0].x, 4),
                    round(decale[1].y - decale[0].y, 4)),
                   (-15.07, -3.73)))

    # le cadre de production fait 16 x 8 autour d'un symbole de 15 x 7
    symbole.frame = 'rect'
    symbole.frame_margin_mm = DEFAULT_FRAME_MARGIN
    cadre = G.bounds([shape_frame(symbole, code_contours(symbole))])
    r.append(check('cadre de 16 × 8 mm',
                   (round(cadre[2] - cadre[0], 4),
                    round(cadre[3] - cadre[1], 4)), (16.0, 8.0)))
    emprise = code_extent(symbole)
    r.append(check('symbole de 15 × 7 mm',
                   (round(emprise[2] - emprise[0], 4),
                    round(emprise[3] - emprise[1], 4)), (15.0, 7.0)))

    print('\npréréglage : implantation relative :')
    from engrave import codepresets
    prod = next(p for p in codepresets.FACTORY if 'négatif' in p['name'])
    r.append(check('marge du préréglage de production',
                   prod['frame_margin_mm'], 0.5))
    r.append(check('écart du texte mémorisé',
                   (prod['text_dx_mm'], prod['text_dy_mm']), (-15.07, -3.73)))
    fenetre = codepresets.text_frame_of(prod, 40.0, -12.0)
    r.append(check('fenêtre replacée autour d\'un code déporté',
                   (round(fenetre[0], 4), round(fenetre[1], 4)),
                   (24.93, -15.73)))
    r.append(check('sans texte : aucune fenêtre',
                   codepresets.text_frame_of({'with_text': False}, 0, 0), None))

    print('\nEX-31 — cadre centré, même marge des quatre côtés :')
    from engrave.toolpath import (code_contours, code_extent, code_fill,
                                  shape_frame, clear_cache)
    encadre = Code(kind='datamatrix', dm_shape='auto', data='B000174',
                   quiet_modules=0, fit_w_mm=15.0, fit_h_mm=7.0,
                   frame='rect', frame_margin_mm=1.0,
                   recipe=PRESET_RECIPES[1])
    symbole = code_extent(encadre)
    cadre = G.bounds([shape_frame(encadre, code_contours(encadre))])
    marges = (round(symbole[0] - cadre[0], 6), round(cadre[2] - symbole[2], 6),
              round(symbole[1] - cadre[1], 6), round(cadre[3] - symbole[3], 6))
    r.append(check('marges gauche, droite, bas, haut', marges,
                   (1.0, 1.0, 1.0, 1.0)))
    r.append(check('cadre centré sur le symbole',
                   (round((cadre[0] + cadre[2]) / 2, 9),
                    round((cadre[1] + cadre[3]) / 2, 9)), (0.0, 0.0)))
    # l'emprise du symbole est celle de la matrice entière, pas de l'encre
    r.append(check('emprise = matrice entière',
                   (round(symbole[2] - symbole[0], 6),
                    round(symbole[3] - symbole[1], 6)), (15.0, 7.0)))

    print('\nEX-32 — négatif : aucune ligne entre deux zones épargnées :')
    from engrave.toolpath import code_matrix
    matrix = code_matrix(encadre)
    rows, cols = len(matrix), len(matrix[0])
    mx, my = 15.0 / cols, 7.0 / rows
    segments = code_contours(encadre)

    # une arête interne serait un segment posé entre deux modules de même
    # couleur ; on les cherche tous, il ne doit en rester aucun
    internes = 0
    for poly in segments:
        (ax, ay), (bx, by) = poly[0], poly[-1]
        if abs(ay - by) < 1e-9:                     # arête horizontale
            y = ay
            ligne = round((7.0 / 2 - y) / my)
            milieu = (ax + bx) / 2
            colonne = int((milieu + 15.0 / 2) / mx)
            haut = matrix[ligne - 1][colonne] if 0 < ligne <= rows else False
            bas = matrix[ligne][colonne] if 0 <= ligne < rows else False
            if haut == bas:
                internes += 1
        else:                                       # arête verticale
            x = ax
            colonne = round((x + 15.0 / 2) / mx)
            milieu = (ay + by) / 2
            ligne = int((7.0 / 2 - milieu) / my)
            gauche = matrix[ligne][colonne - 1] if 0 < colonne <= cols else False
            droite = matrix[ligne][colonne] if 0 <= colonne < cols else False
            if gauche == droite:
                internes += 1
    r.append(check('aucune arête interne tracée', internes, 0))

    # et le remplissage négatif épargne bien les modules sombres
    lignes = code_fill(encadre)
    sombre = next((y, x) for y in range(rows) for x in range(cols)
                  if matrix[y][x])

    def traverse(y_mm, x_mm):
        for (x1, y1), (x2, y2) in lignes:
            if abs(y1 - y_mm) <= my / 3 and min(x1, x2) <= x_mm <= max(x1, x2):
                return True
        return False

    px = -15.0 / 2 + (sombre[1] + 0.5) * mx
    py = 7.0 / 2 - (sombre[0] + 0.5) * my
    r.append(check('un module sombre reste intact en négatif',
                   traverse(py, px), False))
    clear_cache()

    print('\nnégatif : rien du symbole ne déborde du cadre :')
    from engrave.toolpath import code_fill, code_matrix, code_modules
    encadre2 = Code(kind='datamatrix', dm_shape='auto', data='B000174',
                    quiet_modules=0, fit_w_mm=15.0, fit_h_mm=7.0,
                    frame='rect', frame_margin_mm=0.5, fill_step_mm=0.1,
                    recipe=PRESET_RECIPES[1])
    mat = code_matrix(encadre2)
    mx2, my2 = code_modules(encadre2, mat)
    demi_h = len(mat) * my2 / 2
    largeur_cadre = len(mat[0]) * mx2 + 2 * 0.5

    # Les bandes de balayage situées au-dessus ou au-dessous du symbole sont
    # entièrement dans la marge : elles doivent être gravées d'un seul trait
    # sur toute la largeur du cadre. Une troncature vers zéro sur l'indice
    # de ligne y reproduisait les modules de la première ligne — l'horloge
    # d'un DataMatrix — **à l'extérieur du symbole**.
    bandes: dict[float, list[float]] = {}
    for (x1, y1), (x2, y2) in code_fill(encadre2):
        if abs(y1) > demi_h:
            bandes.setdefault(round(y1, 6), []).append(abs(x2 - x1))
    r.append(check('des bandes de marge existent', len(bandes) > 0, True))
    r.append(check('un seul trait par bande de marge',
                   sorted({len(v) for v in bandes.values()}), [1]))
    r.append(check('chaque trait couvre toute la largeur du cadre',
                   sorted({round(sum(v), 6) for v in bandes.values()}),
                   [round(largeur_cadre, 6)]))
    r.append(check('marges haute et basse traitées pareil',
                   (any(y > demi_h for y in bandes),
                    any(y < -demi_h for y in bandes)), (True, True)))

    print('\nNb_passe et Zpasse, champs du magasin d\'outils :')
    r.append(check('Zpasse toujours renseigné',
                   Recipe().depth_step_mm, 0.004673))
    r.append(check('un seul passage : aucune descente',
                   Recipe(passes=1).depth_of(0), -0.0))
    trois = Recipe(passes=3)
    r.append(check('trois passes, cotes de la machine',
                   [round(trois.depth_of(i), 6) for i in range(3)],
                   [-0.0, -0.004673, -0.009346]))
    r.append(check('les deux champs survivent au JSON',
                   (recipe_from_dict(recipe_to_dict(trois)).passes,
                    recipe_from_dict(recipe_to_dict(trois)).depth_step_mm),
                   (3, 0.004673)))
    r.append(check('le libellé annonce passes et profondeur',
                   '3 passes de 4.673 µm' in trois.label(), True))

    print('\nEX-54 — les passes descendent en profondeur :')
    import dataclasses as _dc
    profonde = _dc.replace(PRESET_RECIPES[1], passes=3,
                           depth_mode='step', depth_step_mm=0.004673)
    r.append(check('cotes Z des trois passes',
                   [round(profonde.depth_of(i), 6) for i in range(3)],
                   [-0.0, -0.004673, -0.009346]))
    totale = _dc.replace(PRESET_RECIPES[1], passes=3,
                         depth_mode='total', depth_total_mm=0.015)
    r.append(check('profondeur totale répartie',
                   [round(totale.depth_of(i), 6) for i in range(3)],
                   [-0.0, -0.0075, -0.015]))
    r.append(check('un seul passage : aucune descente',
                   _dc.replace(totale, passes=1).depth_step(), 0.0))

    doc = Document(shapes=[Rect(width=6, height=3, recipe=profonde)])
    passes = build_passes(doc)
    r.append(check('trois passes produites', len(passes), 3))
    r.append(check('chacune à sa cote',
                   [round(p.z_mm, 6) for p in passes],
                   [-0.0, -0.004673, -0.009346]))
    import re as _re
    zs = [sorted(set(_re.findall(r'G00Z(-?[0-9.]+)', iso.render_iso(p))))
          for p in passes]
    r.append(check('ISO : la deuxième passe grave plus bas',
                   '-0.004673' in zs[1], True))
    r.append(check('ISO : le relevé reste à -0.001',
                   all('-0.001000' in z for z in zs), True))

    print('\nEX-63 — chemin vu par la machine, sur modèle :')
    import datetime as _dt
    quand = _dt.datetime(2026, 8, 18, 14, 30, 5)
    plaque = Document(name='plaque essai')
    r.append(check('modèle développé',
                   iso.render_template(r'C:\TauDrive\{date} {job}', plaque,
                                       quand),
                   r'C:\TauDrive\260818 plaque_essai'))
    r.append(check('dossier = dernier segment du chemin machine',
                   iso.job_folder_name(plaque, quand,
                                       r'C:\TauDrive\{date} {job}'),
                   '260818_plaque_essai'))
    r.append(check('champ inconnu laissé tel quel',
                   iso.render_template('X{inconnu}', plaque, quand),
                   'X{inconnu}'))
    r.append(check('sans modèle : horodatage complet',
                   iso.job_folder_name(plaque, quand),
                   'plaque_essai_20260818-143005'))

    print('\npréréglages de code :')
    from engrave import codepresets
    r.append(check('préréglages d\'usine', len(codepresets.FACTORY) >= 3, True))
    sample = Code(kind='qr', data='X{n}', level='H', quiet_modules=4,
                  fit_w_mm=12.0, fit_h_mm=12.0, frame='rect',
                  frame_margin_mm=0.8, fill_step_mm=0.07,
                  line_width_mm=0.2, x=25.0, y=-3.0)
    preset = codepresets.from_code('essai', sample, text_w_mm=9.0,
                                   text_h_mm=1.8)
    r.append(check('tout le formulaire est retenu',
                   sorted(set(codepresets.FIELDS) - set(preset)), []))
    r.append(check('la fenêtre du texte aussi',
                   (preset['text_w_mm'], preset['text_h_mm']), (9.0, 1.8)))
    r.append(check('la position n\'en fait pas partie',
                   'x' in preset or 'y' in preset, False))

    target = Code(x=-40.0, y=7.0)
    codepresets.apply_to(target, preset)
    r.append(check('appliqué : le réglage suit',
                   (target.kind, target.level, target.frame,
                    target.fit_w_mm, round(target.fill_step_mm, 3)),
                   ('qr', 'H', 'rect', 12.0, 0.07)))
    r.append(check('appliqué : la position ne bouge pas',
                   (target.x, target.y), (-40.0, 7.0)))
    r.append(check('résumé lisible',
                   'QR' in codepresets.describe(preset)
                   and 'négatif' in codepresets.describe(preset), True))

    print('\nforme choisie sur la fenêtre (mode « au plus juste ») :')
    # Dans un cadre de 15 x 7 mm, seul le 8 x 18 rend les modules presque
    # carrés — c'est ce que porte la plaque de production. Le mode
    # automatique doit le retrouver seul.
    for w_mm, h_mm, expected in ((15.0, 7.0, (8, 18)), (10.0, 10.0, (12, 12)),
                                 (30.0, 6.0, (8, 18)), (8.0, 8.0, (12, 12))):
        auto = Code(kind='datamatrix', dm_shape='auto', data='B000174',
                    quiet_modules=0, fit_w_mm=w_mm, fit_h_mm=h_mm)
        rows, cols, _, _ = code_size(auto)
        r.append(check(f'fenêtre {w_mm:g} × {h_mm:g} → {expected[0]} × '
                       f'{expected[1]}', (rows, cols), expected))

    production = Code(kind='datamatrix', dm_shape='auto', data='B000174',
                      quiet_modules=0, fit_w_mm=15.0, fit_h_mm=7.0)
    rows, cols, w_mm, h_mm = code_size(production)
    r.append(check('module identique à celui du DXF de production',
                   (round(w_mm / cols, 4), round(h_mm / rows, 4)),
                   (0.8333, 0.875)))

    print('\nplaque posée d\'un geste :')
    from engrave.codeplate import build_plate
    made = build_plate(PRESET_RECIPES[1], frame=(0.0, 2.0, 15.0, 7.0),
                       text_frame=(-15.0, -2.0, 8.071, 1.538),
                       data='B000174')
    r.append(check('un symbole et un texte',
                   [type(s).__name__ for s in made], ['Code', 'Text']))
    r.append(check('le symbole est placé sur son cadre',
                   (made[0].x, made[0].y), (0.0, 2.0)))
    r.append(check('le texte est placé sur le sien',
                   (made[1].x, made[1].y), (-15.0, -2.0)))
    r.append(check('le texte reprend la donnée', made[1].text, 'B000174'))
    r.append(check('sans cadre fourni, une fenêtre de repli est employée',
                   len(build_plate(PRESET_RECIPES[1])), 2))
    r.append(check('donnée inencodable : aucune forme, pas d\'exception',
                   build_plate(PRESET_RECIPES[1], data='Z' * 500), []))
    r.append(check('texte facultatif',
                   len(build_plate(PRESET_RECIPES[1], with_text=False)), 1))

    print('\nmise à l\'échelle d\'un code :')
    windowed = Code(kind='datamatrix', dm_shape='rect', data='B000174',
                    quiet_modules=0, fit_w_mm=15.0, fit_h_mm=7.0)
    _resize.scale_shape(windowed, 2.0, 2.0)
    r.append(check('la fenêtre suit l\'échelle',
                   (round(windowed.fit_w_mm, 6), round(windowed.fit_h_mm, 6)),
                   (30.0, 14.0)))
    _resize.scale_shape(windowed, 0.5, 1.0)
    r.append(check('chaque axe indépendamment',
                   (round(windowed.fit_w_mm, 6), round(windowed.fit_h_mm, 6)),
                   (15.0, 14.0)))
    plain_code = Code(kind='datamatrix', data='ESSAI', module_mm=0.5)
    _resize.scale_shape(plain_code, 2.0, 2.0)
    r.append(check('sans fenêtre : le pas de module suit',
                   round(plain_code.module_mm, 6), 1.0))
    clear_cache()

    print('\nformes masquées : ni affichées, ni gravées :')
    doc = Document(shapes=[Rect(recipe=PRESET_RECIPES[1]),
                           Rect(x=30, recipe=PRESET_RECIPES[1])])
    r.append(check('les deux gravent', len(build_passes(doc)), 2))
    doc.shapes[1].visible = False
    r.append(check('une masquée : une passe de moins',
                   len(build_passes(doc)), 1))
    r.append(check('groupée par recette aussi',
                   len(build_passes(doc, group_by_recipe=True)), 1))

    # une forme masquée hors champ ne doit pas déclencher l'alerte : elle
    # ne part pas à la gravure
    loin = Document(shapes=[Rect(x=200, width=50, height=50, visible=False)])
    r.append(check('masquée hors champ : aucune alerte',
                   loin.out_of_field(), False))
    loin.shapes[0].visible = True
    r.append(check('rendue visible : alerte', loin.out_of_field(), True))
    r.append(check('la visibilité survit au JSON',
                   [s.visible for s in
                    serialize.loads(serialize.dumps(doc)).shapes],
                   [True, False]))

    print('\nexports répétés depuis le même onglet :')
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        noms = []
        for _ in range(4):
            nom = iso.unique_folder(base, '260818 plaque')
            (base / nom).mkdir()
            noms.append(nom)
        r.append(check('numérotation automatique', noms,
                       ['260818 plaque', '260818 plaque-02',
                        '260818 plaque-03', '260818 plaque-04']))
        r.append(check('un nom libre reste tel quel',
                       iso.unique_folder(base, 'autre travail'),
                       'autre travail'))

    r.append(check('le chemin machine suit le nom retenu',
                   iso.replace_tail(r'C:\TauDrive\260818 plaque',
                                    '260818 plaque-02'),
                   r'C:\TauDrive\260818 plaque-02'))
    r.append(check('chemin sans dossier parent',
                   iso.replace_tail('plaque', 'plaque-02'), 'plaque-02'))
    r.append(check('barre oblique finale absorbée',
                   iso.replace_tail('C:/travaux/plaque/', 'plaque-02'),
                   'C:/travaux/plaque-02'))

    print('\ncœur libre : aucune donnée d\'atelier :')
    from engrave import couples, model, plugins
    plugins.reset()
    r.append(check('aucune process par matière au cœur',
                   (model.MATERIAL_RECIPES, model.material_recipes()), ((), ())))
    r.append(check('bibliothèque d\'usine = préréglages neutres',
                   model.factory_recipes(), PRESET_RECIPES))
    usine = {c.key() for c in couples.factory()}
    r.append(check('préréglages sur des couples constructeur, outil 1',
                   [(f'{x.frequency_khz:g}-{x.pulse_width_ns:g}' in usine,
                     x.tool_number) for x in PRESET_RECIPES],
                   [(True, 1)] * len(PRESET_RECIPES)))
    r.append(check('process neuve neutre',
                   (model.default_recipe().name, model.default_recipe().tool_number,
                    model.default_recipe().speed_mm_min), ('Process', 1, 40000.0)))
    r.append(check('aucun couple d\'atelier au cœur', couples.workshop(), []))
    r.append(check('couples constructeur gardés (13 formes d\'onde)',
                   len(couples.factory()), 13))
    from engrave import gabarits
    r.append(check('gabarit livré : l\'exemple du cœur',
                   (gabarits.livre()['donnee'], gabarits.livre()['entraxe_mm']),
                   ('B000001', 23.0)))

    print('\nplugins :')
    with tempfile.TemporaryDirectory() as tmp:
        paquet = pathlib.Path(tmp) / 'atelier_essai'
        paquet.mkdir()
        (paquet / '__init__.py').write_text(
            "PLUGIN = {'nom': 'Essai', 'version': '0.1', 'api': 1,\n"
            "          'licence': 'essai'}\n"
            "def register(api):\n"
            "    from engrave.model import Recipe\n"
            "    api.add_recipes([Recipe('Atelier', 50.0, 80.0, 100, 70000.0,\n"
            "                            tool_number=7)])\n"
            "    api.add_recipes([{'name': 'Matière', 'tool_number': 8}],\n"
            "                    material=True)\n"
            "    api.set_recipe_defaults(name='Défaut atelier', tool_number=9)\n"
            "    api.add_couples([(200, 60, 'Client A'), (200, 60, 'Client B')])\n"
            "    api.set_machine('Machine d\\'essai')\n"
            "    api.set_montage({'nom': 'Montage atelier', 'entraxe_mm': 12.5,\n"
            "                     'donnee': 'ZZ-1'})\n"
            "    api.add_about('ligne d\\'essai')\n",
            encoding='utf-8')
        casse = pathlib.Path(tmp) / 'atelier_casse'
        casse.mkdir()
        (casse / '__init__.py').write_text('raise RuntimeError("cassé")\n',
                                           encoding='utf-8')
        vus = plugins.load([tmp], force=True)
        r.append(check('deux plugins vus, un chargé, un en erreur',
                       sorted((p.module, p.ok) for p in vus),
                       [('atelier_casse', False), ('atelier_essai', True)]))
        r.append(check('préréglages du plugin à la place du cœur',
                       [x.name for x in model.preset_recipes()], ['Atelier']))
        r.append(check('process par matière du plugin',
                       [(x.name, x.tool_number) for x in model.material_recipes()],
                       [('Matière', 8)]))
        r.append(check('bibliothèque proposée = usine du plugin',
                       [x.name for x in model.RECIPE_LIBRARY], ['Atelier', 'Matière']))
        r.append(check('valeurs par défaut du plugin',
                       (model.default_recipe().name, model.default_recipe().tool_number,
                        model.default_recipe().speed_mm_min),
                       ('Défaut atelier', 9, 40000.0)))
        r.append(check('forme neuve : process par défaut du plugin',
                       Rect(width=1, height=1).recipe.tool_number, 9))
        r.append(check('champ absent d\'un fichier : valeur du plugin',
                       recipe_from_dict({'name': 'vieux'}).tool_number, 9))
        r.append(check('couples d\'atelier du plugin, noms réunis',
                       [(c.key(), c.name) for c in couples.workshop()],
                       [('200-60', 'Client A · Client B')]))
        r.append(check('machine et À propos',
                       (plugins.REGISTRY.machine, plugins.about_lines()[-1]),
                       ("Machine d'essai", "ligne d'essai")))
        from engrave import gabarits
        r.append(check('gabarit livré par le plugin, partout',
                       (gabarits.livre()['nom'],
                        gabarits.proposees({'postes': ['A', 'B']}),
                        gabarits.verifier({'nom': 'X'})['entraxe_mm']),
                       ('Montage atelier', ['ZZ-1', 'ZZ-1'], 12.5)))
        try:
            plugins.Api(plugins.REGISTRY, plugins.PluginInfo('x')) \
                .set_montage({'entraxe_mm': 1.0})
            sans_nom = False
        except ValueError:
            sans_nom = True
        r.append(check('gabarit sans nom refusé', sans_nom, True))
        r.append(check('À propos dit le plugin en erreur',
                       any('non chargé' in x and 'cassé' in x
                           for x in plugins.about_lines()), True))
        try:
            plugins.Api(plugins.REGISTRY, plugins.PluginInfo('x')) \
                .set_recipe_defaults(inconnu=1)
            refuse = False
        except ValueError:
            refuse = True
        r.append(check('champ de process inconnu refusé', refuse, True))
        if tmp in sys.path:
            sys.path.remove(tmp)
    plugins.reset()
    sys.modules.pop('atelier_essai', None)
    sys.modules.pop('atelier_casse', None)
    r.append(check('oubli des plugins : retour au cœur',
                   (model.factory_recipes(), model.default_recipe().tool_number,
                    list(model.RECIPE_LIBRARY)),
                   (PRESET_RECIPES, 1, list(PRESET_RECIPES))))

    print('\npositionner le centre (F2) :')
    from engrave.resize import move_selection_center, selection_center
    a = Rect(width=10, height=5, x=3.0, y=-2.0)
    b = Rect(width=6, height=4, x=13.0, y=6.0)
    avant = (a.x - b.x, a.y - b.y)
    move_selection_center([a, b], 0.0, 0.0)
    r.append(check('le centre de l\'emprise tombe sur la cote demandée',
                   tuple(round(v, 9) for v in selection_center([a, b])),
                   (0.0, 0.0)))
    r.append(check('les positions relatives ne bougent pas',
                   (round(a.x - b.x, 9), round(a.y - b.y, 9)),
                   (round(avant[0], 9), round(avant[1], 9))))

    seule = Rect(width=8, height=4, x=12.0, y=-7.0)
    move_selection_center([seule], -3.5, 1.25)
    r.append(check('une forme seule se place sur son centre',
                   (round(seule.x, 6), round(seule.y, 6)), (-3.5, 1.25)))
    move_selection_center([seule], -3.5, 1.25)
    r.append(check('demander la position courante ne fait rien',
                   (round(seule.x, 6), round(seule.y, 6)), (-3.5, 1.25)))
    r.append(check('sélection vide : sans effet',
                   move_selection_center([], 5, 5), None))

    # mise à l'échelle puis placement : l'ordre compte, le centre doit
    # tomber juste malgré le changement de taille
    grand = Rect(width=10, height=5, x=20.0, y=20.0)
    _resize.scale_selection([grand], 3.0, 3.0)
    move_selection_center([grand], 0.0, 0.0)
    r.append(check('échelle puis placement : taille et centre',
                   (tuple(round(v, 6) for v in _resize.selection_size([grand])),
                    (round(grand.x, 6), round(grand.y, 6))),
                   ((30.0, 15.0), (0.0, 0.0))))

    print('\ngroupes : recette et étiquettes :')
    doc = Document(shapes=[Rect(recipe=PRESET_RECIPES[0]),
                           Rect(recipe=PRESET_RECIPES[1]),
                           Rect(recipe=PRESET_RECIPES[3])])
    ids = [s.id for s in doc.shapes]
    doc.group(ids[:2])
    r.append(check('membres du groupe', len(doc.group_members(ids[0])), 2))
    r.append(check('forme isolée : elle-même',
                   len(doc.group_members(ids[2])), 1))

    print('\nemprise mémorisée :')
    from engrave.toolpath import shape_extent
    clear_cache()
    moved = Text(text='ABC', size_mm=6, x=0, y=0)
    first = shape_extent(moved)
    moved.x, moved.y = 12.0, -3.0
    second = shape_extent(moved)
    r.append(check('déplacer translate l\'emprise, sans la recalculer',
                   (round(second[0] - first[0], 6),
                    round(second[1] - first[1], 6)), (12.0, -3.0)))
    moved.size_mm = 12.0
    r.append(check('changer la taille invalide bien l\'emprise',
                   round(shape_extent(moved)[2] - shape_extent(moved)[0], 3)
                   > round(second[2] - second[0], 3), True))

    print('\népaisseur de trait : décalage exact, sans recouvrement :')
    from engrave.toolpath import (dedupe, normalise, thicken,
                                  _offset_polyline)
    carre = G.rect_contour(20, 10)
    decale = _offset_polyline(carre, 0.05)
    r.append(approx('le côté s\'écarte de la valeur demandée',
                    abs(decale[0][1] - carre[0][1]), 0.05, 1e-9))
    r.append(approx('la pointe d\'onglet s\'écarte de offset/cos(45°)',
                    ((decale[0][0] - carre[0][0]) ** 2
                     + (decale[0][1] - carre[0][1]) ** 2) ** 0.5,
                    0.05 * 2 ** 0.5, 1e-9))
    droite = _offset_polyline([(0.0, 0.0), (10.0, 0.0)], 0.05)
    r.append(approx('sur une ligne droite, le décalage vaut offset',
                    abs(droite[0][1]), 0.05, 1e-9))

    r.append(check('doublon exact retiré',
                   len(dedupe([carre, list(carre)])), 1))
    r.append(check('doublon inversé retiré',
                   len(dedupe([carre, list(reversed(carre))])), 1))
    r.append(check('deux tracés distincts sont gardés',
                   len(dedupe([carre, G.rect_contour(20, 10, 0, 0.12)])), 2))

    def double_mm(polys, seuil):
        """Longueur qui repasse à moins de `seuil` d'un **autre** tracé."""
        pts = []
        for i, p in enumerate(polys):
            for (x1, y1), (x2, y2) in zip(p, p[1:]):
                lg = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                n = max(1, int(lg / (seuil / 3)))
                for k in range(n):
                    t = k / n
                    pts.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t,
                                i, lg / n))
        cases = {}
        for j, (x, y, _, _) in enumerate(pts):
            cases.setdefault((int(x // seuil), int(y // seuil)), []).append(j)
        double = 0.0
        for j, (x, y, i, dl) in enumerate(pts):
            cx, cy = int(x // seuil), int(y // seuil)
            voisins = [k for a in (-1, 0, 1) for b in (-1, 0, 1)
                       for k in cases.get((cx + a, cy + b), ())]
            if any(k != j and pts[k][2] != i
                   and (pts[k][0] - x) ** 2 + (pts[k][1] - y) ** 2
                   < seuil * seuil for k in voisins):
                double += dl
        return double, sum(dl for *_, dl in pts)

    seul = thicken([carre], 0.4, 0.05)
    d1, t1 = double_mm(seul, 0.045)
    r.append(check('contour isolé épaissi : aucun recouvrement',
                   round(d1, 3), 0.0))

    proches = thicken([carre, G.rect_contour(20, 10, 0, 0.12)], 0.4, 0.05)
    d2, t2 = double_mm(proches, 0.045)
    r.append(check('deux contours proches : recouvrement sous 10 %',
                   d2 / t2 < 0.10, True))

    r.append(check('la normalisation ne touche pas aux tracés voulus',
                   normalise([carre], [], 0.05), []))

    print('\ncoupon d\'essai :')
    from engrave import coupon
    r.append(check('valeurs arrondies : recopiables dans une recette',
                   coupon.steps(40000, 200000, 4, 'speed_mm_min'),
                   [40000.0, 93500.0, 146500.0, 200000.0]))
    r.append(check('bornes comprises',
                   coupon.steps(20, 100, 5, 'power_percent'),
                   [20.0, 40.0, 60.0, 80.0, 100.0]))
    r.append(check('passes : entières et sans doublon',
                   coupon.steps(1, 3, 5, 'passes'), [1, 2, 3]))
    r.append(check('une seule valeur : pas de division par zéro',
                   coupon.steps(7, 99, 1, 'power_percent'), [7.0]))

    grille = coupon.build(PRESET_RECIPES[1], x_count=3, y_count=2)
    cases = [s for s in grille if isinstance(s, Rect)]
    r.append(check('une case par couple de valeurs', len(cases), 6))
    r.append(check('une recette distincte par case',
                   len({s.recipe.name for s in cases}), 6))
    r.append(check('étiquettes : X, Y et titre',
                   len([s for s in grille if isinstance(s, Text)]), 3 + 2 + 1))
    r.append(check('étiquettes gravées sans creuser',
                   all(s.recipe.hatch_mm == 0 and s.recipe.passes == 1
                       for s in grille if isinstance(s, Text)), True))
    b = coupon.extent(grille)
    r.append(check('grille centrée sur l\'origine',
                   (abs(b[0] + b[2]) < 12, abs(b[1] + b[3]) < 12),
                   (True, True)))
    r.append(check('axe neutre : une seule colonne',
                   len([s for s in coupon.build(PRESET_RECIPES[1],
                                                x_field='', y_count=3)
                        if isinstance(s, Rect)]), 3))
    impose = coupon.build(PRESET_RECIPES[1], x_field='power_percent',
                          x_count=3, y_field='',
                          fixed={'speed_mm_min': 12345.0,
                                 'power_percent': 7.0})
    boites = [s for s in impose if isinstance(s, Rect)]
    r.append(check('paramètre fixe appliqué à toutes les cases',
                   {s.recipe.speed_mm_min for s in boites}, {12345.0}))
    r.append(check('un axe l\'emporte sur le même paramètre fixé',
                   len({s.recipe.power_percent for s in boites}) > 1, True))

    profond = coupon.build(PRESET_RECIPES[1], x_field='depth_total_mm',
                           x_from=0.05, x_to=0.15, x_count=3, y_field='')
    r.append(check('essai de profondeur : mode « total » imposé',
                   {s.recipe.depth_mode for s in profond
                    if isinstance(s, Rect)}, {'total'}))

    print('\nASCII pur, comme les fichiers de la machine :')
    r.append(check('point médian et tirets translittérés',
                   iso.ascii_only('Laiton — gravure · 20 %'),
                   'Laiton - gravure - 20 %'))
    r.append(check('accents translittérés',
                   iso.ascii_only('Épaisseur crème à 5 µm'),
                   'Epaisseur creme a 5 um'))
    r.append(check('rien au-dessus de 127',
                   max(ord(c) for c in
                       iso.ascii_only('Coupon é·—×°±µØœ')) < 128, True))
    r.append(check('parenthèses neutralisées dans un commentaire',
                   iso.comment('outil (spécial) fin'), 'outil -special- fin'))
    r.append(check('le / et le % quittent l\'ISO',
                   iso.comment('case 100% / 40000mm/min'),
                   'case 100 pc - 40000mm-min'))
    r.append(check('alphabet limité à celui de la machine',
                   set(iso.comment('a/b|c&d[e]f#g@h')) <=
                   set('abcdefghijklmnopqrstuvwxyz0123456789 ,-.:=_'), True))
    r.append(check('la coupe tombe sur une frontière de mot',
                   iso.comment('Balayage Pz0.1 - Profondeur 0.02mm '
                               '· Vitesse 40000mm/min', 40),
                   'Balayage Pz0.1 - Profondeur 0.02mm'))
    r.append(check('un mot unique trop long est coupé net',
                   iso.comment('A' * 60, 40), 'A' * 40))
    r.append(check('nom de dossier sans accent',
                   iso.sanitize('Coupon é · gravé'), 'Coupon_e_-_grave'))

    with tempfile.TemporaryDirectory() as tmp:
        doc = Document(name='Coupon é gravé')
        doc.add(Rect(width=10, height=10,
                     recipe=dataclasses_replace_name(
                         PRESET_RECIPES[1], 'Laiton — gravure · 20 %')))
        written = iso.export(doc, tmp)
        octets = b''.join(pathlib.Path(f).read_bytes() for f in written)
        r.append(check('aucun octet > 127 dans les fichiers produits',
                       max(octets) < 128, True))

    print('\nvérification avant export :')
    from engrave import preflight
    doc = Document(name='Contrôle')
    doc.add(Rect(width=20, height=10, recipe=PRESET_RECIPES[1]))
    cachee = Rect(x=8, width=5, height=5, recipe=PRESET_RECIPES[1])
    cachee.visible = False
    doc.add(cachee)
    rapport = preflight.inspect(doc)
    r.append(check('formes comptées, masquées comprises',
                   (rapport.shapes, rapport.hidden), (2, 1)))
    r.append(check('les masquées ne produisent pas de passe',
                   rapport.passes, 1))
    r.append(check('longueur mesurée sur le contour',
                   round(rapport.length_mm, 3), 60.0))
    r.append(check('masquées signalées',
                   any('masquée' in w for w in rapport.warnings()), True))

    import dataclasses
    doublon = Document()
    doublon.add(Rect(width=10, height=10, recipe=PRESET_RECIPES[1]))
    # même outil, puissance différente : l'ISO n'emporte que le numéro
    doublon.add(Circle(width=10, height=10,
                       recipe=dataclasses.replace(PRESET_RECIPES[1],
                                                  name='Copie modifiée',
                                                  power_percent=40.0)))
    outil = f'T{PRESET_RECIPES[1].tool_number}'
    r.append(check('même outil, deux jeux de paramètres : signalé',
                   any(outil in w for w in preflight.inspect(doublon)
                       .warnings()), True))

    dehors = Document()
    dehors.add(Rect(x=300, width=20, height=10, recipe=PRESET_RECIPES[1]))
    r.append(check('hors champ : bloquant',
                   len(preflight.inspect(dehors).blocking()), 1))
    r.append(check('document vide : bloquant',
                   len(preflight.inspect(Document()).blocking()), 1))
    r.append(check('durées lisibles',
                   [preflight.duration_text(v) for v in (0.4, 45, 90, 3725)],
                   ['moins d\'une seconde', '45 s', '1 min 30 s',
                    '1 h 02 min']))

    print('\nannuler / refaire :')
    from engrave.history import History
    doc = Document()
    pile = History(doc)
    for _ in range(3):
        doc.add(Rect(width=5, height=5, recipe=PRESET_RECIPES[1]))
        pile.record(doc)
    r.append(check('trois coups annulables', pile.depth(), (3, 0)))
    r.append(check('un état inchangé n\'est pas retenu',
                   pile.record(doc), False))
    revenu = pile.undo()
    r.append(check('annuler restitue l\'état précédent',
                   (len(revenu.shapes), pile.depth()), (2, (2, 1))))
    r.append(check('refaire revient en avant',
                   len(pile.redo().shapes), 3))
    pile.undo()
    doc2 = Document()
    doc2.add(Rect(width=9, height=9, recipe=PRESET_RECIPES[1]))
    pile.record(doc2)
    r.append(check('une action neuve coupe la branche refaisable',
                   pile.depth(), (3, 0)))

    print('\ndocument vide :')
    try:
        iso.export(Document(), tempfile.gettempdir())
        r.append(check('export refusé', 'accepté', 'ValueError'))
    except ValueError:
        r.append(check('export refusé', True, True))

    total, ok = len(r), sum(r)
    print(f'\n{ok}/{total} contrôles passés')
    return 0 if ok == total else 1


if __name__ == '__main__':
    raise SystemExit(main())
