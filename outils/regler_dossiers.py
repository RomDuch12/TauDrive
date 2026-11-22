"""Règle les dossiers par défaut sans passer par l'interface.

Utile pour préparer un poste, ou pour rétablir un réglage après une
réinstallation. Sans argument, affiche les réglages en vigueur.

    python outils/regler_dossiers.py
    python outils/regler_dossiers.py export "\\\\DESKTOP-J2DHKP4\\TauDrive"
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def main(argv: list[str]) -> int:
    from PySide6.QtWidgets import QApplication
    QApplication([])
    from engrave import session

    known = {kind: label for kind, label, _ in session.FOLDER_KINDS}
    if len(argv) >= 2:
        kind, path = argv[0], argv[1]
        if kind not in known:
            print(f'usage inconnu : {kind!r}. Attendu : '
                  + ', '.join(known))
            return 1
        session.set_default_folder(kind, path)

    print('Dossiers par défaut :')
    width = max(len(label) for label in known.values())
    for kind, label, _ in session.FOLDER_KINDS:
        value = session.default_folder(kind)
        if not value:
            state = '(aucun — dernier emplacement employé)'
        elif pathlib.Path(value).is_dir():
            state = value
        else:
            # un partage hors ligne reste un réglage valable : on le signale
            # sans le présenter comme une erreur
            state = f'{value}   [non joignable depuis ce poste]'
        print(f'  {label.ljust(width)}  {state}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
