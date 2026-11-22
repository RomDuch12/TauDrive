"""Journal des exports / Export journal.

Un même travail est rarement exporté une seule fois. On corrige une
puissance, on ajoute une passe, on relance — et trois plaques plus tard,
personne ne sait plus **laquelle a été gravée avec quoi**.

Le journal répond à cette question. À chaque export d'un travail déjà
exporté, il écrit dans le dossier de destination, à côté des dossiers
horodatés :

    <travail>-journal.txt

Une entrée par export : l'horodatage, le dossier produit, les recettes
employées avec leurs paramètres, et surtout **ce qui a changé depuis
l'export précédent**. C'est ce dernier point qui compte : relire deux
listes de vingt paramètres pour trouver la puissance qui a bougé, personne
ne le fait.

Le fichier est en texte simple, **ASCII**, comme tout ce qui va sur le
partage machine : il se lit depuis n'importe quel poste, sans TauDrive.
"""
from __future__ import annotations

import datetime as dt
import pathlib

from .iso import ascii_only, sanitize
from .model import SPEED_TO_DISPLAY, SPEED_UNIT, Document

#: Nom du fichier, dérivé du travail.
SUFFIX = '-journal.txt'

#: Paramètres suivis, avec leur libellé et leur mise en forme.
TRACKED: tuple[tuple[str, str, str], ...] = (
    ('tool_number', 'outil', 'T{}'),
    ('power_percent', 'puissance', '{:g} %'),
    ('frequency_khz', 'frequence', '{:g} kHz'),
    ('pulse_width_ns', 'impulsion', '{:g} ns'),
    ('speed_mm_min', 'vitesse', '{}'),
    ('passes', 'passes', '{:g}'),
    ('hatch_mm', 'hachure', '{:g} mm'),
    ('hatch_angle_deg', 'angle hachure', '{:g} deg'),
    ('depth_mode', 'mode profondeur', '{}'),
    ('depth_step_mm', 'profondeur/passe', '{:g} mm'),
    ('depth_total_mm', 'profondeur totale', '{:g} mm'),
)


def path_for(base: str | pathlib.Path, job: str) -> pathlib.Path:
    """Fichier de journal d'un travail, dans le dossier d'export."""
    return pathlib.Path(base) / f'{sanitize(job)}{SUFFIX}'


def _format(field: str, value, gabarit: str) -> str:
    if field == 'speed_mm_min':
        try:
            return f'{float(value) * SPEED_TO_DISPLAY:g} {SPEED_UNIT}'
        except (TypeError, ValueError):
            return str(value)
    try:
        return gabarit.format(value)
    except (TypeError, ValueError):
        return str(value)


def snapshot(document: Document, *, optimize: bool = False,
             group_by_recipe: bool = False) -> dict:
    """État des paramètres d'un travail, comparable d'un export à l'autre.

    Les recettes sont indexées **par nom** : c'est ce que l'opérateur lit,
    et deux recettes de même nom aux paramètres différents n'ont pas de
    sens — le gestionnaire les refuse déjà.
    """
    recettes: dict[str, dict] = {}
    for shape in document.shapes:
        if not shape.visible:
            continue
        r = shape.recipe
        recettes.setdefault(r.name, {champ: getattr(r, champ, None)
                                     for champ, _, _ in TRACKED})
    return {
        'formes': len(document.shapes),
        'masquees': sum(1 for s in document.shapes if not s.visible),
        'optimiser': bool(optimize),
        'grouper': bool(group_by_recipe),
        'recipes': recettes,
    }


def differences(avant: dict, apres: dict) -> list[str]:
    """Ce qui a changé entre deux états, en clair."""
    if not avant:
        return []
    out: list[str] = []
    for cle, libelle in (('formes', 'formes'), ('masquees', 'masquees'),
                         ('optimiser', 'optimiser le parcours'),
                         ('grouper', 'grouper par process')):
        if avant.get(cle) != apres.get(cle):
            out.append(f'{libelle} : {avant.get(cle)} -> {apres.get(cle)}')

    anciennes = avant.get('recipes', avant.get('process', {}))
    nouvelles = apres.get('recipes', apres.get('process', {}))
    for nom in sorted(set(nouvelles) - set(anciennes)):
        out.append(f'process ajoutee : {nom}')
    for nom in sorted(set(anciennes) - set(nouvelles)):
        out.append(f'process retiree : {nom}')
    for nom in sorted(set(anciennes) & set(nouvelles)):
        a, b = anciennes[nom], nouvelles[nom]
        for champ, libelle, gabarit in TRACKED:
            if a.get(champ) != b.get(champ):
                out.append(f'{nom} - {libelle} : '
                           f'{_format(champ, a.get(champ), gabarit)} -> '
                           f'{_format(champ, b.get(champ), gabarit)}')
    return out


def render(etat: dict, ecarts: list[str], *, rang: int, dossier: str,
           fichiers: int, when: dt.datetime | None = None) -> str:
    """Une entrée de journal, prête à être ajoutée."""
    moment = (when or dt.datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
    lignes = [
        '=' * 72,
        f'Export n{rang}   {moment}',
        f'  dossier  : {dossier}',
        f'  fichiers : {fichiers}',
        f'  formes   : {etat["formes"]}'
        + (f' dont {etat["masquees"]} masquee(s)' if etat['masquees'] else ''),
        f'  parcours : ' + ('optimise' if etat['optimiser'] else 'ordre de creation')
        + (', groupe par process' if etat['grouper'] else ''),
        '  process :',
    ]
    for nom, valeurs in sorted(etat.get('recipes', {}).items()):
        detail = ', '.join(
            f'{libelle} {_format(champ, valeurs.get(champ), gabarit)}'
            for champ, libelle, gabarit in TRACKED
            if valeurs.get(champ) is not None)
        lignes.append(f'    - {nom} : {detail}')
    if ecarts:
        lignes.append('  MODIFICATIONS depuis l\'export precedent :')
        lignes.extend(f'    * {e}' for e in ecarts)
    elif rang > 1:
        lignes.append('  aucun parametre modifie depuis l\'export precedent')
    return ascii_only('\n'.join(lignes)) + '\n'


def append(base: str | pathlib.Path, job: str, entry: str) -> pathlib.Path:
    """Ajoute une entrée au journal du travail. Ne lève jamais.

    Un journal qui ferait échouer un export serait pire que pas de
    journal : les fichiers sont déjà écrits quand on en arrive ici.
    """
    cible = path_for(base, job)
    try:
        with cible.open('a', encoding='ascii', errors='replace') as f:
            f.write(entry)
    except OSError:
        pass
    return cible
