"""Mémoire de session : robustesse hors réseau.

Le poste d'atelier est parfois débranché, ou le partage éteint. Deux
exigences en découlent, et ce sont elles qu'on vérifie ici :

* **l'application démarre quand même**, sans attendre l'expiration du
  délai SMB — une vingtaine de secondes par chemin, dans le constructeur
  de la fenêtre, suffisait à la rendre inutilisable ;
* **l'historique est conservé**. Un chemin qui ne répond pas n'est pas
  effacé : le partage reviendra, et l'entrée doit l'attendre.

Usage : python test_session.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

#: Partage volontairement inexistant : aucun poste ne porte ce nom.
ABSENT = r'\\POSTE-QUI-N-EXISTE-PAS-999\partage'


def check(label, got, want) -> bool:
    ok = got == want
    print(f'  [{"OK " if ok else "KO "}] {label}')
    if not ok:
        print(f'         obtenu : {got!r}\n         attendu: {want!r}')
    return ok


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings
    QApplication([])

    # Bac à sable : on ne touche pas aux réglages du poste. Rediriger le
    # format ne suffit pas — il faut **changer d'organisation**, sans quoi
    # une écriture retombe dans la base de registre de l'utilisateur et
    # emporte ses vrais chemins avec elle.
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                      tempfile.mkdtemp())
    QSettings.setDefaultFormat(QSettings.IniFormat)

    from engrave import session
    session.ORG_NAME = 'Cielle-essai'
    session.APP_NAME = 'TauDrive-essai'
    session.settings().clear()
    session.forget_reachability()
    r = []

    print('sonde d\'accès :')
    local = str(ROOT)
    start = time.perf_counter()
    r.append(check('un chemin local répond', session.reachable(local), True))
    r.append(check('un partage absent ne répond pas',
                   session.reachable(ABSENT), False))
    elapsed = time.perf_counter() - start
    r.append(check(f'les deux sondes tiennent dans le délai '
                   f'({elapsed:.2f} s)', elapsed < 5.0, True))

    start = time.perf_counter()
    for _ in range(200):
        session.reachable(ABSENT)
    r.append(check('le résultat est mémorisé, pas resondé',
                   (time.perf_counter() - start) < 0.05, True))

    session.forget_reachability()
    r.append(check('on peut redemander après un retour du réseau',
                   session.reachable(local), True))

    print('\nl\'historique survit à une coupure :')
    doc = ABSENT + r'\plaque.taudrive'
    session.remember_document(doc)
    session.remember_export(ABSENT)
    session.remember_folder('dxf', ABSENT)
    session.set_default_folder('export', ABSENT)

    r.append(check('document injoignable conservé',
                   session.recent_documents(), [doc]))
    r.append(check('dossier d\'export injoignable conservé',
                   session.export_folders(), [ABSENT]))
    r.append(check('dossier récent injoignable conservé',
                   ABSENT in session.recent_folders('dxf'), True))
    r.append(check('dossier par défaut injoignable conservé',
                   session.default_folder('export'), ABSENT))

    # ajouter une entrée vivante ne doit pas chasser la morte
    vivant = str(ROOT)
    session.remember_export(vivant)
    r.append(check('la nouvelle entrée passe devant, l\'ancienne reste',
                   session.export_folders(), [vivant, ABSENT]))

    joignables, absents = session.sort_by_reach(session.export_folders())
    r.append(check('les joignables sont distingués', joignables, [vivant]))
    r.append(check('les absents aussi', absents, [ABSENT]))

    print('\nchoix du point de départ d\'un sélecteur :')
    r.append(check('un défaut injoignable est écarté',
                   session.start_folder('export') != ABSENT, True))
    session.set_default_folder('export', vivant)
    r.append(check('un défaut joignable est retenu',
                   session.start_folder('export'), vivant))

    print('\ndémarrage avec tout injoignable :')
    session.settings().clear()
    session.forget_reachability()
    session.clear_snapshot()
    session.set_default_folder('export', ABSENT)
    session.settings().setValue('recent/exports', [ABSENT])
    session.settings().setValue('recent/documents', [doc])
    session.settings().setValue('session/open', [doc])

    from engrave import recipes, theme
    from engrave.app import MainWindow
    theme.apply(QApplication.instance())
    recipes.install_local()

    start = time.perf_counter()
    window = MainWindow()
    window.show()
    delay = time.perf_counter() - start
    r.append(check(f'la fenêtre se construit ({delay:.2f} s)',
                   delay < 8.0 and window.isVisible(), True))
    r.append(check('un onglet vierge remplace le document absent',
                   window.tabs.count(), 1))
    r.append(check('le dossier absent reste proposé',
                   ABSENT in [window.w_export_dir.itemText(i)
                              for i in range(window.w_export_dir.count())],
                   True))
    window._fill_recent()
    r.append(check('le document absent reste dans les récents',
                   session.recent_documents(), [doc]))

    print('\nvérification avant export :')
    r.append(check('active par défaut', session.preflight(), True))
    session.set_preflight(False)
    r.append(check('se coupe et se retient', session.preflight(), False))
    session.set_preflight(True)
    r.append(check('se rétablit', session.preflight(), True))

    total, ok = len(r), sum(r)
    print(f'\n{ok}/{total} contrôles passés')
    return 0 if ok == total else 1


if __name__ == '__main__':
    raise SystemExit(main())
