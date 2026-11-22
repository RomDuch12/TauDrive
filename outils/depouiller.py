"""Copie dépouillée des sources, pour l'empaquetage / stripped source copy.

**Ce que ce script fait, et ce qu'il ne fait pas.**

Il retire les **docstrings** d'une copie du code, et rien d'autre. Le
programme empaqueté se comporte exactement pareil ; ce qu'un décompilateur
récupérerait perd en revanche les 184 ko de prose qui expliquent chaque
décision — soit 17 % du source, et de loin ce qu'il y a de plus utile à
qui voudrait comprendre le programme sans l'avoir écrit.

Les commentaires, eux, ne sont **jamais** dans le bytecode : Python les
jette à la compilation. Il n'y a donc rien à faire pour eux.

**Ce n'est pas une protection.** Le bytecode reste décompilable, les noms
de fonctions et la structure restent lisibles, et la logique se suit. Cela
élève le coût d'entrée, ça ne ferme aucune porte. La seule protection
réelle serait de sortir le code de l'exécutable — service distant ou
composant natif signé — et cela se décide autrement qu'ici.

Pourquoi pas `optimize=2`, qui retire les docstrings tout seul : ce niveau
les retire **partout**, y compris dans numpy, dont l'import échoue alors —
`add_docstring` refuse `None`. Le dépouillement doit donc ne toucher que
nos modules, et c'est ce que fait ce script.

    python outils/depouiller.py            écrit build/src-depouille/
"""
from __future__ import annotations

import ast
import pathlib
import shutil
import sys

RACINE = pathlib.Path(__file__).resolve().parents[1]
SOURCE = RACINE / 'src'
SORTIE = RACINE / 'build' / 'src-depouille'


class _Depouilleur(ast.NodeTransformer):
    """Retire les docstrings, laisse tout le reste intact."""

    def _sans_doc(self, noeud):
        self.generic_visit(noeud)
        corps = noeud.body
        if (corps and isinstance(corps[0], ast.Expr)
                and isinstance(corps[0].value, ast.Constant)
                and isinstance(corps[0].value.value, str)):
            corps = corps[1:]
            # un corps vide n'est pas du Python valide
            if not corps:
                corps = [ast.Pass()]
            noeud.body = corps
        return noeud

    visit_Module = _sans_doc
    visit_ClassDef = _sans_doc
    visit_FunctionDef = _sans_doc
    visit_AsyncFunctionDef = _sans_doc


def depouiller(texte: str) -> str:
    """Le même code, sans ses docstrings."""
    arbre = _Depouilleur().visit(ast.parse(texte))
    ast.fix_missing_locations(arbre)
    return ast.unparse(arbre)


def construire(source: pathlib.Path = SOURCE,
               sortie: pathlib.Path = SORTIE) -> dict:
    """Écrit la copie dépouillée. Rend le compte de ce qui a été retiré."""
    if sortie.exists():
        shutil.rmtree(sortie)
    sortie.mkdir(parents=True)

    compte = {'fichiers': 0, 'octets_avant': 0, 'octets_apres': 0,
              'echecs': []}
    for chemin in sorted(source.rglob('*.py')):
        if '__pycache__' in chemin.parts:
            continue
        relatif = chemin.relative_to(source)
        cible = sortie / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        brut = chemin.read_text(encoding='utf-8')
        try:
            nu = depouiller(brut)
            # ceinture et bretelles : ce qu'on écrit doit compiler
            compile(nu, str(cible), 'exec')
        except (SyntaxError, ValueError, RecursionError) as exc:
            # un module qu'on ne sait pas réécrire part **tel quel** :
            # mieux vaut livrer sa prose que livrer un programme cassé
            compte['echecs'].append(f'{relatif} : {exc}')
            nu = brut
        cible.write_text(nu, encoding='utf-8')
        compte['fichiers'] += 1
        compte['octets_avant'] += len(brut)
        compte['octets_apres'] += len(nu)
    return compte


if __name__ == '__main__':
    c = construire()
    gagne = c['octets_avant'] - c['octets_apres']
    print(f'{c["fichiers"]} fichiers · '
          f'{c["octets_avant"]:,} -> {c["octets_apres"]:,} caractères '
          f'({gagne:,} retirés, {gagne * 100 // max(1, c["octets_avant"])} %)')
    for e in c['echecs']:
        print('  non dépouillé :', e)
    print('->', SORTIE)
    sys.exit(0)
