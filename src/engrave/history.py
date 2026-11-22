"""Annuler et refaire / Undo and redo.

Sur un poste d'atelier, un `Ctrl+Z` manquant se paie en plaques : on
rattrape une fausse manœuvre en refaisant le dessin, ou pire, on ne la
rattrape pas et elle part à la gravure.

L'historique retient des **instantanés du document entier**, sous la même
forme que l'enregistrement. C'est plus simple qu'un journal d'opérations
inverses, et surtout plus sûr : rien ne peut se désynchroniser entre ce
qui a été fait et ce qui est censé le défaire. Un document de gravure pèse
quelques kilo-octets — le coût est sans commune mesure avec le risque. Un
DXF d'atelier peut compter des centaines de milliers de points : les
états en partagent les couples, immuables, au lieu de les recopier —
voir `serialize.shape_to_dict`.

Les instantanés sont **regroupés dans le temps** : un déplacement à la
souris produit des dizaines de modifications, qui doivent se défaire d'un
seul coup et non pixel par pixel.
"""
from __future__ import annotations

from . import serialize
from .model import Document

#: Nombre d'états conservés. Au-delà, les plus anciens sont oubliés.
DEPTH = 60


class History:
    """Pile d'instantanés d'un document, avec un curseur."""

    def __init__(self, document: Document) -> None:
        self._states: list[dict] = [self._snap(document)]
        self._index = 0

    @staticmethod
    def _snap(document: Document) -> dict:
        return serialize.document_to_dict(document)

    # -- enregistrement ----------------------------------------------------

    def record(self, document: Document) -> bool:
        """Retient l'état courant s'il diffère du dernier. Vrai s'il a servi.

        Tout ce qui suit le curseur est abandonné : refaire n'a plus de
        sens dès qu'on repart dans une autre direction.
        """
        state = self._snap(document)
        if state == self._states[self._index]:
            return False
        del self._states[self._index + 1:]
        self._states.append(state)
        if len(self._states) > DEPTH:
            self._states.pop(0)
        self._index = len(self._states) - 1
        return True

    # -- parcours ----------------------------------------------------------

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    def undo(self) -> Document | None:
        if not self.can_undo():
            return None
        self._index -= 1
        return self._document()

    def redo(self) -> Document | None:
        if not self.can_redo():
            return None
        self._index += 1
        return self._document()

    def _document(self) -> Document | None:
        try:
            return serialize.document_from_dict(self._states[self._index])
        except Exception:
            # un état illisible ne doit pas emporter l'application : on le
            # retire et on s'en tient là
            del self._states[self._index]
            self._index = max(0, self._index - 1)
            return None

    def depth(self) -> tuple[int, int]:
        """(coups annulables, coups refaisables) — pour les libellés."""
        return self._index, len(self._states) - 1 - self._index
