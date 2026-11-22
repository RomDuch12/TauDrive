"""Champs variables et sérialisation / Variable fields and serialization.

Un texte peut contenir des champs entre accolades, remplacés au moment du
calcul des trajectoires :

    {n}          numéro de série courant             ->  7
    {n:04}       numéro sur 4 chiffres               ->  0007
    {i}          index de la pièce dans le lot, 1..N ->  3
    {total}      nombre de pièces du lot             ->  50
    {date}       date du jour, AAAA-MM-JJ
    {heure}      heure, HH:MM
    {job}        nom du travail

`{{` et `}}` produisent une accolade littérale.

Un champ inconnu est **laissé tel quel** plutôt que de faire échouer le
calcul : mieux vaut voir `{client}` gravé à l'écran et le corriger que
perdre le document.
"""
from __future__ import annotations

import datetime as dt
import re

FIELD = re.compile(r'\{\{|\}\}|\{([a-zA-Z_]+)(?::([^}]*))?\}')

#: Champs reconnus, pour l'aide en ligne.
KNOWN_FIELDS = {
    'n': 'numéro de série',
    'i': 'index dans le lot (1…N)',
    'total': 'nombre de pièces du lot',
    'date': 'date du jour',
    'heure': 'heure',
    'job': 'nom du travail',
}


def make_context(*, serial: int = 1, index: int = 1, total: int = 1,
                 job: str = '', now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now()
    return {
        'n': serial,
        'i': index,
        'total': total,
        'date': now.strftime('%Y-%m-%d'),
        'heure': now.strftime('%H:%M'),
        'job': job,
        # L'instant lui-même : `{date:%y%m%d}` a besoin du datetime, pas de
        # la chaîne déjà mise en forme. Un `_` en tête : ce n'est pas un
        # champ qu'on écrit dans un texte.
        '_now': now,
    }


def expand(text: str, context: dict) -> str:
    """Remplace les champs de `text` par leurs valeurs."""
    if '{' not in text:
        return text

    def replace(match: re.Match) -> str:
        token = match.group(0)
        if token == '{{':
            return '{'
        if token == '}}':
            return '}'
        name, spec = match.group(1), match.group(2)
        if name not in context:
            return token                       # champ inconnu : intact
        value = context[name]
        if spec:
            # Un motif de date — reconnaissable à son `%` — s'applique à
            # l'instant, pas à la chaîne déjà mise en forme. C'est ce qui
            # permet d'écrire `{date:%y%m%d}` et d'obtenir « 260820 ».
            moment = context.get('_now')
            if '%' in spec and moment is not None and name in ('date',
                                                               'heure'):
                try:
                    return moment.strftime(spec)
                except (ValueError, TypeError):
                    return str(value)
            # OverflowError : `{n:c}` hors de l'Unicode — un numéro de
            # série négatif ou au-delà de 1 114 111 —, `{n:.3f}` d'un
            # entier trop grand pour un décimal. La vérification passait
            # (première pièce) et l'export tombait sur la deuxième.
            try:
                return format(value, spec)
            except (ValueError, TypeError, OverflowError):
                return str(value)
        return str(value)

    return FIELD.sub(replace, text)


def has_fields(text: str) -> bool:
    """Vrai si le texte contient au moins un champ reconnu."""
    return any(m.group(1) in context_names() for m in FIELD.finditer(text))


def context_names() -> frozenset[str]:
    return frozenset(KNOWN_FIELDS)


def unknown_fields(text: str) -> list[str]:
    """Champs présents mais non reconnus, pour avertir l'utilisateur."""
    known = context_names()
    return sorted({m.group(1) for m in FIELD.finditer(text)
                   if m.group(1) and m.group(1) not in known})
