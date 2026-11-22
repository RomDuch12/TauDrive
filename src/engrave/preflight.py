"""Vérification avant envoi / Pre-flight check.

Le dernier moment où une erreur coûte encore zéro : après, elle coûte une
plaque, ou une pièce client. Le contrôle rassemble ce qu'on vérifierait
soi-même à la main, mais qu'on ne vérifie pas quand on est pressé — et
c'est précisément quand on est pressé qu'on se trompe.

Le récapitulatif ne bloque rien : il **montre**, et signale ce qui mérite
un regard. La décision reste à l'opérateur, qui voit la matière et la
pièce. Un contrôle qui refuse d'exporter finit contourné.

Réglable dans *Paramètres ▸ Vérifier avant l'export*.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel,
                               QTextBrowser, QVBoxLayout)

from . import session
from .model import Document
from .toolpath import (MAX_PASSAGES, MAX_RANGEES, build_passes,
                       total_duration_s, total_length_mm, total_travel_mm,
                       unfilled_shapes, unthickened_shapes)

#: Niveaux d'alerte, du plus grave au plus anodin.
BLOQUANT, ATTENTION, INFO = 'bloquant', 'attention', 'info'

_RANG = {BLOQUANT: 0, ATTENTION: 1, INFO: 2}

#: Nombre de travaux dans un CLJOB dont on sache qu'il a gravé.
#: Les fichiers de la machine en portent un ou deux ; le plus
#: long export réussi côté TauDrive en comptait dix-huit.
VERIFIED_JOBS = 18


@dataclass
class Report:
    """Ce que le travail contient et ce qui mérite un regard."""
    shapes: int = 0
    hidden: int = 0
    passes: int = 0
    length_mm: float = 0.0
    travel_mm: float = 0.0
    duration_s: float = 0.0
    #: (numéro d'outil, nom, nombre de passes machine) par recette employée
    recipes: list[tuple[int, str, int]] = field(default_factory=list)
    out_of_field: bool = False
    #: Dossier du travail : il n'existe pas encore au moment du contrôle.
    destination: str = ''
    #: Dossier qui l'accueillera, lui déjà écrit : c'est sa disponibilité
    #: qu'on interroge, pas celle du sous-dossier à créer.
    destination_root: str = ''
    machine_path: str = ''
    #: (niveau, texte) — triées, le plus grave d'abord
    notes: list[tuple[str, str]] = field(default_factory=list)

    def blocking(self) -> list[str]:
        return [t for lvl, t in self.notes if lvl == BLOQUANT]

    def warnings(self) -> list[str]:
        return [t for lvl, t in self.notes if lvl == ATTENTION]


def duration_text(seconds: float) -> str:
    """Durée lisible : on annonce des minutes, pas 372,4 s."""
    seconds = max(0.0, seconds)
    if seconds < 1:
        # « 0 s » se lit comme une panne d'estimation, pas comme un travail
        # très court
        return 'moins d\'une seconde'
    if seconds < 60:
        return f'{seconds:.0f} s'
    minutes, reste = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f'{minutes} min {reste:02d} s'
    heures, minutes = divmod(minutes, 60)
    return f'{heures} h {minutes:02d} min'


def inspect(document: Document, *, destination: str = '',
            destination_root: str = '', machine_path: str = '',
            optimize: bool = False,
            group_by_recipe: bool = False) -> Report:
    """Récapitulatif du travail tel qu'il partirait à la machine.

    Les trajectoires sont construites **exactement** comme à l'export :
    même ordonnancement, même regroupement — et même budget, mêmes champs
    variables, ceux de la première pièce (`iso.reglages_premiere_piece`).
    La vérification se donnait 0,3 s d'ordonnancement quand l'export en
    prend une : elle ne mesurait pas tout à fait ce qui part. Un contrôle
    qui mesurerait autre chose que ce qui part ne servirait à rien.
    """
    import datetime as dt

    from .iso import reglages_premiere_piece
    # un seul instant, comme l'export — voir `iso.contexte_piece`
    now = dt.datetime.now()
    reglages = reglages_premiere_piece(document, now)
    report = Report(destination=destination, machine_path=machine_path,
                    destination_root=destination_root)
    report.shapes = len(document.shapes)
    report.hidden = sum(1 for s in document.shapes if not s.visible)

    from .toolpath import dense_wobble, formes_trop_denses
    with dense_wobble() as denses:
        passes = build_passes(document, optimize=optimize,
                              group_by_recipe=group_by_recipe, **reglages)
    if document.copies > 1 and not denses:
        # Toutes les pièces, comme l'export avant d'écrire : un numéro ou
        # une date peut rendre trop dense ce que la première laissait
        # passer — la huitième d'une série de douze, sans que la dernière
        # le soit. La vérification ne regardait que la première et la
        # dernière, et disait oui à ce que l'export refusait. Seules les
        # formes qui oscillent se recalculent, et l'export les relit.
        from .iso import contexte_piece
        for index in range(1, int(document.copies)):
            denses.update(formes_trop_denses(
                document, contexte_piece(document, index, now)))
            if denses:
                break
    # les mêmes tracés se mesurent pour la durée du travail, celle de
    # chaque process et le conseil de vitesse : une seule fois
    memo: dict = {}
    report.passes = len(passes)
    report.length_mm = total_length_mm(passes)
    report.travel_mm = total_travel_mm(passes)
    report.duration_s = total_duration_s(passes, memo=memo)
    report.out_of_field = document.out_of_field()

    vues: dict[str, tuple[int, str, int]] = {}
    for p in passes:
        vues.setdefault(p.recipe.name,
                        (p.recipe.tool_number, p.recipe.name,
                         p.recipe.passes))
    report.recipes = sorted(vues.values())

    _notes(document, report, passes)
    _note_codes(document, report, reglages['context'], now)
    if denses:
        from .toolpath import _millions, _virgule
        from .wobble import MAX_POINTS
        points, pas, nom = next(iter(denses.values()))
        autres = (f' (et {len(denses) - 1} autre(s) forme(s))'
                  if len(denses) > 1 else '')
        report.notes.append((
            BLOQUANT,
            f'Oscillation trop dense pour {nom}{autres} : '
            f'{_millions(points)} millions de points, au plus '
            f'{MAX_POINTS / 1e6:g}. Le plan de travail la montre sans '
            f'oscillation et l\'export est refusé. Élargissez le pas '
            f'd\'oscillation ({_virgule(pas)} mm ici) : chaque tour en '
            f'compte seize.'))
    else:
        # bloqué, le travail se mesure sur le trait sans oscillation : un
        # conseil de cadence chiffré sur lui serait faux
        _notes_cadence(document, report, passes, optimize, group_by_recipe,
                       memo, reglages)
    report.notes.sort(key=lambda n: _RANG.get(n[0], 9))
    return report


def _note_codes(document: Document, report: Report, contexte: dict,
                now) -> None:
    """Un code inencodable, à la première pièce ou à une autre : bloquant,
    l'export le refuse — voir `toolpath.codes_inencodables`. Seuls les
    codes à champ variable se relisent d'une pièce à l'autre."""
    from .iso import contexte_piece
    from .toolpath import codes_inencodables
    refus, piece = codes_inencodables(document, contexte), 1
    for index in range(1, int(document.copies)):
        if refus:
            break
        refus = codes_inencodables(document,
                                   contexte_piece(document, index, now),
                                   variables_seuls=True)
        piece = index + 1
    if not refus:
        return
    nom, raison = refus[0]
    autres = (f' (et {len(refus) - 1} autre(s))' if len(refus) > 1 else '')
    ou = f' à la pièce {piece}' if document.copies > 1 else ''
    report.notes.append((
        BLOQUANT,
        f'Code inencodable{ou} : {nom}{autres} — {raison}. Il ne serait '
        f'pas gravé, et l\'export est refusé.'))


#: Gain à partir duquel la vérification propose une autre cadence : il
#: faut au moins une seconde **et** un cinquième de la durée.
CONSEIL_GAIN_S = 1.0
CONSEIL_GAIN_PART = 0.2

#: Allumages au-delà desquels on mesure l'effet d'« Enchaîner les tracés ».
CONSEIL_ALLUMAGES = 300


def best_speed(polylines: list, speed_mm_min: float,
               memo: dict | None = None) -> tuple[float, float]:
    """La vitesse la plus rapide **pour ce dessin**, et sa durée.

    Sur cette machine, la durée n'est pas décroissante avec la vitesse :
    chaque allumage paie des rampes proportionnelles à la vitesse — voir
    `toolpath.polylines_duration_s`. Un dessin fait de centaines de petits
    traits a donc une vitesse optimale, souvent bien sous le plafond. On
    la cherche de 5 en 5 m/min, entre 20 et 200. `memo` : voir
    `toolpath.duration_profile`.
    """
    from .toolpath import duration_profile, profile_duration_s
    profil = duration_profile(polylines, memo=memo)
    meilleure = (speed_mm_min, profile_duration_s(profil, speed_mm_min))
    for v in range(20000, 200001, 5000):
        d = profile_duration_s(profil, float(v))
        if d < meilleure[1] - 1e-9:
            meilleure = (float(v), d)
    return meilleure


def _notes_cadence(document: Document, report: Report, passes: list,
                   optimize: bool, group_by_recipe: bool,
                   memo: dict | None = None,
                   reglages: dict | None = None) -> None:
    """Ce qui ferait gagner du temps, chiffré — **sans rien changer**.

    Deux leviers, mesurés sur le travail lui-même :

    * la **vitesse** : sur un dessin fait de petits traits, 200 m/min est
      plus lent que 50 — constaté à l'atelier, 15 s contre 7 ;
    * **enchaîner les tracés** : moins d'allumages, donc moins de rampes.

    Changer la vitesse change l'énergie déposée par millimètre : la note
    le rappelle, et rien n'est appliqué d'office.
    """
    from . import geometry as G
    from .toolpath import polylines_duration_s
    add = report.notes.append
    par_recette: dict = {}
    for p in passes:
        par_recette.setdefault(p.recipe.name, []).append(p)
    for nom, groupe in par_recette.items():
        recette = groupe[0].recipe
        polys = [pl for p in groupe for pl in p.polylines]
        allumages = G.laser_ons(polys)
        actuelle = polylines_duration_s(polys, recette.speed_mm_min,
                                        memo=memo)
        v, d = best_speed(polys, recette.speed_mm_min, memo)
        gain = actuelle - d
        if gain >= CONSEIL_GAIN_S and gain >= CONSEIL_GAIN_PART * actuelle:
            from .toolpath import SPEED_MAX_MM_MIN
            demandee = f'{recette.speed_mm_min / 1000:g} m/min'
            if recette.speed_mm_min > SPEED_MAX_MM_MIN:
                # la machine écrête : 500 m/min gravent à 200
                demandee += f' (gravés à {SPEED_MAX_MM_MIN / 1000:g})'
            add((INFO,
                 f'Process « {nom} » : {duration_text(actuelle)} à '
                 f'{demandee}, '
                 f'{duration_text(d)} à {v / 1000:g} m/min. Sur cette '
                 f'machine chaque allumage paie des rampes d\'autant plus '
                 f'longues que la vitesse est haute ({allumages} allumages '
                 f'ici). Changer la vitesse change l\'énergie déposée : à '
                 f'valider sur coupon.'))
        if (not getattr(recette, 'link_paths', False)
                and allumages >= CONSEIL_ALLUMAGES):
            _conseil_enchainer(document, nom, recette, allumages, actuelle,
                               optimize, group_by_recipe, add, reglages)
        if (recette.hatch_mm > 0
                and getattr(recette, 'fill_style', 'hatch') != 'rings'):
            _conseil_anneaux(document, nom, recette, actuelle,
                             optimize, group_by_recipe, add, reglages)


#: Sommets de contour au-delà desquels la vérification ne chiffre pas
#: les anneaux : environ 0,4 ms par sommet. Une plaque, un logo, le
#: DataMatrix dessiné de l'atelier (2 695 sommets, 1 s) passent ; un
#: texte de cent cinquante lettres en négatif (6 590, 3 s) ne fait pas
#: attendre la vérification.
ANNEAUX_SOMMETS_MAX = 4000


def _conseil_anneaux(document, nom, recette, actuelle,
                     optimize, group_by_recipe, add,
                     reglages: dict | None = None) -> None:
    """Mesure ce que donnerait le remplissage en anneaux, enchaînés —
    construit avec les réglages de l'export, pour se comparer à lui."""
    import dataclasses
    from . import rings
    from .model import Code
    from .toolpath import build_passes, polylines_duration_s, trial_cache
    if not rings.available():
        return
    # Un code se remplit lui-même et ignore le style : seules les autres
    # formes changent. Sans quoi un document de DataMatrix seuls se voyait
    # promettre un gain qui venait tout entier de l'enchaînement.
    concernees = [s for s in document.shapes
                  if s.recipe.name == nom and not isinstance(s, Code)]
    if not concernees:
        return
    # le calcul des anneaux se paie à la taille du dessin : au-delà, la
    # vérification avant gravure ne doit pas faire attendre l'opérateur
    from .toolpath import shape_contours
    sommets = sum(len(c) for s in concernees for c in shape_contours(s))
    if sommets > ANNEAUX_SOMMETS_MAX:
        return
    essai = dataclasses.replace(recette, fill_style='rings', link_paths=True)
    copie = dataclasses.replace(document, shapes=[
        dataclasses.replace(s, recipe=essai)
        if (s.recipe.name == nom and not isinstance(s, Code)) else s
        for s in document.shapes])
    try:
        with trial_cache():
            passes = build_passes(copie, optimize=optimize,
                                  group_by_recipe=group_by_recipe,
                                  **(reglages or {}))
    except Exception as exc:                            # noqa: BLE001
        from .avale import avale
        avale('vérification : essai des anneaux impossible', exc)
        return
    polys = [pl for p in passes if p.recipe.name == nom
             for pl in p.polylines]
    duree = polylines_duration_s(polys, recette.speed_mm_min)
    gain = actuelle - duree
    if gain < CONSEIL_GAIN_S or gain < CONSEIL_GAIN_PART * actuelle:
        return
    add((INFO,
         f'Process « {nom} » : un remplissage en anneaux, qui suit le '
         f'contour au lieu de le balayer, ferait passer '
         f'{duration_text(actuelle)} à {duration_text(duree)} — plus de '
         f'demi-tours au bout des rangées. Se choisit dans la process '
         f'(Style : Anneaux, avec « Enchaîner ») ; l\'aspect change, à '
         f'valider sur coupon.'))


def _conseil_enchainer(document, nom, recette, allumages, actuelle,
                       optimize, group_by_recipe, add,
                       reglages: dict | None = None) -> None:
    """Mesure ce que donnerait « Enchaîner les tracés » sur cette process —
    construit avec les réglages de l'export, pour se comparer à lui."""
    import dataclasses
    from . import geometry as G
    from .toolpath import build_passes, polylines_duration_s, trial_cache
    essai = dataclasses.replace(recette, link_paths=True)
    copie = dataclasses.replace(document, shapes=[
        dataclasses.replace(s, recipe=essai)
        if s.recipe.name == nom else s for s in document.shapes])
    try:
        with trial_cache():
            passes = build_passes(copie, optimize=optimize,
                                  group_by_recipe=group_by_recipe,
                                  **(reglages or {}))
    except Exception as exc:                            # noqa: BLE001
        from .avale import avale
        avale('vérification : essai d\'enchaînement impossible', exc)
        return
    polys = [pl for p in passes if p.recipe.name == nom
             for pl in p.polylines]
    apres = G.laser_ons(polys)
    duree = polylines_duration_s(polys, recette.speed_mm_min)
    gain = actuelle - duree
    # c'est le temps gagné qui compte, pas les allumages : un texte en
    # négatif perdait 80 % de ses allumages pour 43 s → 42 s, ses
    # demi-tours de zigzag coûtant autant — conseil sans objet
    if (apres >= allumages * 0.8 or gain < CONSEIL_GAIN_S
            or gain < CONSEIL_GAIN_PART * actuelle):
        return
    add((INFO,
         f'Process « {nom} » : « Enchaîner les tracés » ferait passer '
         f'{allumages} allumages à {apres}, et {duration_text(actuelle)} à '
         f'{duration_text(duree)}. Se coche dans la process.'))


def _notes(document: Document, report: Report, passes: list) -> None:
    """Les points qui méritent un regard, du plus grave au plus anodin."""
    add = report.notes.append

    if not report.passes:
        add((BLOQUANT, 'Aucune trajectoire à graver : le travail écrirait '
                       'un fichier vide.'))
    if report.out_of_field:
        add((BLOQUANT,
             f'Une trajectoire sort du champ de marquage '
             f'({document.field_w:g} × {document.field_h:g} mm). '
             f'La machine ne peut pas l\'atteindre — sauf en plusieurs '
             f'morceaux : Fichier ▸ Exporter en morceaux.'))
    demesurees = unfilled_shapes(document)
    if demesurees:
        rangees = f'{MAX_RANGEES:,}'.replace(',', ' ')
        add((ATTENTION,
             f'{len(demesurees)} forme(s) trop grande(s) pour être '
             f'remplie(s) : plus de {rangees} rangées de hachure, ou '
             f'traits pour un code. '
             f'Seul leur contour est tracé. Fichier abîmé, ou importé '
             f'dans la mauvaise unité ?'))
    trop_epais = unthickened_shapes(document)
    if trop_epais:
        passages = f'{MAX_PASSAGES:,}'.replace(',', ' ')
        add((ATTENTION,
             f'{len(trop_epais)} forme(s) au trait trop épais pour son '
             f'pas : plus de {passages} passages. Leur tracé est gravé '
             f'sans épaississement. Épaisseur ou pas à revoir — le '
             f'remplissage creuse une bande large bien plus vite.'))
    if report.hidden:
        add((ATTENTION,
             f'{report.hidden} forme(s) masquée(s) — elles ne seront pas '
             f'gravées. Volontaire ?'))

    _notes_polices(document, add)

    _notes_liens(document, add)

    # Un même numéro d'outil sous deux jeux de paramètres : l'ISO n'emporte
    # que le numéro, la machine appliquera donc son magasin, pas la
    # recette d'ici. C'est le piège classique d'une recette dupliquée puis
    # modifiée sans changer son T.
    par_outil: dict[int, set] = {}
    for p in passes:
        r = p.recipe
        par_outil.setdefault(r.tool_number, set()).add(
            (r.power_percent, r.frequency_khz, r.pulse_width_ns,
             r.speed_mm_min))
    for tool, jeux in sorted(par_outil.items()):
        if len(jeux) > 1:
            add((ATTENTION,
                 f'L\'outil T{tool} est appelé avec {len(jeux)} jeux de '
                 f'paramètres différents. L\'ISO n\'emporte que le numéro : '
                 f'la machine appliquera ce que porte son magasin.'))

    for p in passes:
        if p.recipe.power_percent <= 0:
            add((ATTENTION, f'Process « {p.recipe.name} » à 0 % de '
                            f'puissance : elle ne marquera rien.'))
            break
    for p in passes:
        r = p.recipe
        if r.passes > 1 and r.depth_step() <= 0:
            add((INFO, f'Process « {r.name} » : {r.passes} passes au même '
                       f'Z. Repasser sans descendre creuse peu.'))
            break

    # Chaque passe devient un `.ISO` et une entrée du CLJOB. Les fichiers
    # de la machine n'en portent qu'un ou deux ; le plus long export dont
    # on sache qu'il a gravé en comptait dix-huit. Au-delà, on est en
    # terrain non vérifié — ce qui se dit, plutôt que de se taire.
    if report.passes > VERIFIED_JOBS:
        add((ATTENTION,
             f'{report.passes} travaux dans un seul CLJOB. Le plus long '
             f'export dont on sache qu\'il a gravé en comptait '
             f'{VERIFIED_JOBS} ; au-delà, rien n\'est vérifié. En cas de '
             f'refus silencieux de ClTerm, réduisez le nombre de process '
             f'ou de passes.'))

    # L'oscillation demande au scanner une cadence de v / pas. Elle est
    # muette sur la pièce quand le miroir ne suit pas : la bande n'est
    # pas plus large qu'un trait simple, et rien ne l'annonce.
    from . import wobble as _wob
    vues_wob: set[tuple] = set()
    for p in passes:
        r = p.recipe
        clef = (r.wobble, r.wobble_amp_mm, r.wobble_pitch_mm, r.speed_mm_min)
        if r.wobble == 'none' or clef in vues_wob:
            continue
        vues_wob.add(clef)
        for niveau, texte in _wob.check(r.speed_mm_min, r.wobble_pitch_mm,
                                        r.wobble_amp_mm, r.wobble):
            add((niveau, f'Process « {r.name} » : {texte}'))

    racine = report.destination_root or report.destination
    # `writable` et non `reachable` : un dossier d'export qui n'existe pas
    # encore sera créé, sous-dossiers compris. Ne bloque que si même son
    # parent ne répond pas — là, c'est bien le partage qui manque.
    if racine and not session.writable(racine):
        add((BLOQUANT, f'Le dossier de destination ne répond pas :\n{racine}'))
    if report.duration_s > 3600:
        add((INFO, f'Travail long : {duration_text(report.duration_s)} '
                   f'estimées.'))


def _notes_polices(document: Document, add) -> None:
    """Dit si du texte part avec une police qui n'est pas celle demandée.

    Un document écrit ailleurs porte le **chemin** de ses polices. Si ce
    poste ne les a pas, le texte est gravé avec la police par défaut :
    les lettres ne sont plus les mêmes, la largeur non plus. C'est le
    genre de différence qu'on ne voit qu'en comparant deux plaques côte
    à côte, longtemps après.
    """
    from . import textvec
    from .model import Text
    absentes = textvec.missing_fonts()
    if not absentes:
        return
    employees = {s.font_path for s in document.shapes
                 if isinstance(s, Text) and s.font_path}
    concernees = sorted(employees & set(absentes))
    if not concernees:
        return
    import pathlib as _pl
    noms = ', '.join(_pl.Path(textvec.split_spec(c)[0]).name
                     for c in concernees[:4])
    add((ATTENTION,
         f'{len(concernees)} police(s) absente(s) de ce poste : {noms}. '
         f'Le texte sera gravé avec la police par défaut — lettres et '
         f'largeurs différentes de ce que le document demande.'))


def _notes_liens(document: Document, add) -> None:
    """Le texte en clair dit-il bien ce que dit le symbole ?

    Trois défauts, tous rencontrés sur un fichier réel — `Datamatrix.taudrive`
    portait le troisième, et il était en production.

    Une pièce qui part avec un code et un numéro lisible qui se
    contredisent est pire qu'une pièce sans marquage : l'un se lit à
    l'œil, l'autre au lecteur, et rien ne dit lequel fait foi. C'est
    précisément ce que le lien `follows` existe pour empêcher — encore
    faut-il que quelqu'un vérifie qu'il tient.
    """
    from .model import Code, Text

    codes = {s.id: s for s in document.shapes if isinstance(s, Code)}
    textes = [s for s in document.shapes
              if isinstance(s, Text) and s.follows]
    if not codes and not textes:
        return

    # 1. un lien qui ne mène nulle part — le code a été supprimé, le
    #    texte est resté, et il ne suivra plus jamais rien
    orphelins = [t for t in textes if t.follows not in codes]
    if orphelins:
        noms = ', '.join(f'« {t.text} »' for t in orphelins[:3])
        suite = '…' if len(orphelins) > 3 else ''
        add((BLOQUANT,
             f'{len(orphelins)} texte(s) suivent un code qui n\'existe '
             f'plus : {noms}{suite}. Ils ne se mettront plus à jour.'))

    # 2. un lien qui tient, mais que la donnée a déjà pris de vitesse
    divergents = [t for t in textes
                  if t.follows in codes and t.text != codes[t.follows].data]
    if divergents:
        exemple = divergents[0]
        add((BLOQUANT,
             f'{len(divergents)} texte(s) ne disent pas ce que dit leur '
             f'code. Exemple : le texte porte « {exemple.text} », le '
             f'symbole « {codes[exemple.follows].data} ».'))

    # 3. deux textes sur un même code pendant qu'un autre n'en a aucun.
    #    C'est le défaut du montage à trois DataMatrix : les trois textes
    #    suivaient le symbole du milieu. Changer la référence du haut ne
    #    mettait à jour aucun texte ; changer celle du milieu en
    #    réécrivait trois.
    suivis: dict[str, int] = {}
    for t in textes:
        if t.follows in codes:
            suivis[t.follows] = suivis.get(t.follows, 0) + 1
    doubles = [i for i, n in suivis.items() if n > 1]
    sans = [i for i in codes if i not in suivis]
    if doubles and sans:
        add((BLOQUANT,
             f'{len(doubles)} code(s) portent plusieurs textes pendant que '
             f'{len(sans)} n\'en portent aucun. Un texte suit sans doute le '
             f'mauvais symbole : éditer une référence en changerait '
             f'plusieurs, ou aucune.'))


def summary_html(report: Report) -> str:
    """Le récapitulatif, prêt à afficher."""
    lignes = [
        '<style>td{padding:2px 10px 2px 0;}</style>',
        '<table>',
        _row('Formes', f'{report.shapes}'
                       + (f' dont {report.hidden} masquée(s)'
                          if report.hidden else '')),
        _row('Passes', f'{report.passes}'),
        _row('Longueur gravée', f'{report.length_mm:,.1f} mm'
             .replace(',', ' ')),
        _row('Déplacements à vide', f'{report.travel_mm:,.1f} mm'
             .replace(',', ' ')),
        _row('Durée estimée', duration_text(report.duration_s)),
        '</table>',
    ]

    if report.recipes:
        lignes.append('<p><b>Process employées</b></p><table>')
        for tool, name, passes in report.recipes:
            detail = f'{passes} passes' if passes > 1 else '1 passe'
            lignes.append(_row(f'T{tool}', f'{name} — {detail}'))
        lignes.append('</table>')

    if report.destination:
        lignes.append('<p><b>Destination</b></p><table>')
        lignes.append(_row('Écriture', report.destination))
        if report.machine_path:
            lignes.append(_row('Vu par la machine', report.machine_path))
        lignes.append('</table>')

    if report.notes:
        lignes.append('<p><b>À vérifier</b></p><ul>')
        for niveau, texte in report.notes:
            marque = {BLOQUANT: '■', ATTENTION: '▲'}.get(niveau, '·')
            lignes.append(f'<li>{marque} {_escape(texte)}</li>')
        lignes.append('</ul>')
    else:
        lignes.append('<p>Rien à signaler.</p>')
    return '\n'.join(lignes)


def _row(label: str, value: str) -> str:
    return f'<tr><td>{_escape(label)}</td><td><b>{_escape(value)}</b></td></tr>'


def _escape(text: str) -> str:
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('\n', '<br>'))


class PreflightDialog(QDialog):
    """Récapitulatif avant export, avec la case pour ne plus le revoir."""

    def __init__(self, parent, report: Report) -> None:
        super().__init__(parent)
        self.setWindowTitle('Vérification avant export')
        self.setMinimumSize(520, 460)
        self.report = report

        layout = QVBoxLayout(self)
        bloquants = report.blocking()
        if bloquants:
            titre = ('<b>Ce travail présente '
                     f'{len(bloquants)} point(s) bloquant(s).</b>')
        elif report.warnings():
            titre = '<b>Vérifiez les points signalés avant d\'envoyer.</b>'
        else:
            titre = '<b>Prêt à exporter.</b>'
        layout.addWidget(QLabel(titre))

        view = QTextBrowser()
        view.setHtml(summary_html(report))
        view.setOpenExternalLinks(False)
        layout.addWidget(view, 1)

        self.w_skip = QCheckBox('Ne plus vérifier avant l\'export')
        self.w_skip.setToolTip(
            'Se rétablit dans Paramètres ▸ Vérifier avant l\'export.')
        layout.addWidget(self.w_skip)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText('Exporter' if not bloquants else 'Exporter quand même')
        ok.setDefault(not bloquants)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            'Revenir au dessin')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if bloquants:
            # rien n'est interdit, mais le bouton sûr est celui qui a le
            # focus : un « Entrée » machinal ne doit pas lancer un travail
            # qui sort du champ
            buttons.button(
                QDialogButtonBox.StandardButton.Cancel).setFocus(
                    Qt.OtherFocusReason)

    def skip_next_time(self) -> bool:
        return self.w_skip.isChecked()
