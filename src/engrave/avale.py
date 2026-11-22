"""Ce que l'application a rattrapé sans le dire / swallowed errors.

Un `except Exception` large est souvent le bon choix : écrire une
vignette ne doit jamais empêcher d'ouvrir un dessin, et une police
malformée ne doit pas fermer la bibliothèque. Le filet est légitime.

**Ce qui ne l'est pas, c'est le silence.** Un filet muet avale aussi les
vraies erreurs, et l'on cherche ensuite pendant une heure pourquoi une
vignette ne s'affiche pas — alors que la réponse était là, attrapée et
jetée.

Ce module ne change rien au comportement : ce qui était rattrapé l'est
toujours, et l'application continue exactement comme avant. Il se
contente de **retenir** ce qui est passé, pour qu'on puisse le lire.

    from .avale import avale
    try:
        vignette.write(...)
    except Exception as exc:
        avale('vignette', exc)

Les entrées se lisent dans *? ▸ Ce qui a été rattrapé*.
"""
from __future__ import annotations

import collections
import datetime
import threading

#: Nombre d'entrées gardées. Au-delà, les plus anciennes partent.
#:
#: Deux cents suffit : ce journal sert à comprendre ce qui vient de se
#: passer, pas à tenir l'historique d'une semaine. Le garder court le
#: rend lisible, et l'empêche de peser sur une session qui dure.
MAX = 200

_journal: collections.deque = collections.deque(maxlen=MAX)
_verrou = threading.Lock()


def avale(contexte: str, exc: BaseException, *, detail: str = '') -> None:
    """Retient une erreur rattrapée. Ne lève jamais.

    `contexte` dit **où** — « vignette », « police », « registre ». C'est
    ce qu'on lit en premier, et c'est ce qui doit permettre de retrouver
    l'endroit sans chercher.
    """
    try:
        entree = (datetime.datetime.now(), str(contexte),
                  type(exc).__name__, str(exc)[:200], str(detail)[:200])
        with _verrou:
            _journal.append(entree)
    except Exception:                                  # noqa: BLE001
        # Un journal qui plante en journalisant serait le comble : on
        # préfère perdre la ligne que l'opération qu'elle accompagne.
        pass


def entries() -> list[tuple]:
    """Les entrées, de la plus récente à la plus ancienne."""
    with _verrou:
        return list(reversed(_journal))


def count() -> int:
    with _verrou:
        return len(_journal)


def clear() -> None:
    with _verrou:
        _journal.clear()


def summary() -> str:
    """Une ligne par contexte, la plus fréquente d'abord."""
    par_contexte: dict[str, int] = {}
    for _, contexte, _, _, _ in entries():
        par_contexte[contexte] = par_contexte.get(contexte, 0) + 1
    if not par_contexte:
        return 'Rien n\'a été rattrapé.'
    return ' · '.join(f'{c} ({n})' for c, n in
                      sorted(par_contexte.items(), key=lambda kv: -kv[1]))


def report_text() -> str:
    """Le journal en texte nu, lisible sans TauDrive."""
    lignes = ['TauDrive — ce qui a été rattrapé sans le dire', '']
    if not _journal:
        lignes.append('(rien)')
    for quand, contexte, genre, message, detail in entries():
        lignes.append(f'{quand:%Y-%m-%d %H:%M:%S}  [{contexte}]  '
                      f'{genre}: {message}')
        if detail:
            lignes.append(f'{" " * 21}{detail}')
    return '\n'.join(lignes) + '\n'
