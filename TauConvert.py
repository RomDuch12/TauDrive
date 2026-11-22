"""TauConvert — le convertisseur seul / conversion-only build.

Une version **réduite** de TauDrive, pour les postes qui n'ont pas à
graver : un bureau d'études, un poste de préparation, l'ordinateur de
quelqu'un qui reçoit des dessins clients et doit les rendre en DXF.

Elle ne fait que trois choses :

* **poser** le sous-menu « Convertir avec TauDrive » au clic droit de
  l'explorateur, ou le **retirer** ;
* **convertir** les fichiers que ce menu lui envoie ;
* **expliquer** en quelques lignes comment s'en servir.

Rien d'autre. Pas de plan de travail, pas de process, pas de machine,
pas de bibliothèque. Un poste de bureau n'a aucune
raison de porter une commande de laser, et lui en donner une est un
risque qu'on ne prend pas.

    TauConvert.exe                    la fenêtre
    TauConvert.exe --convert a.ai --to dxf
    TauConvert.exe --autotest

Le format converti et sa précision sont **exactement** ceux de TauDrive :
c'est le même lecteur et le même écrivain, au même module près.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / 'src'))


def main() -> int:
    if '--autotest' in sys.argv:
        return autotest()

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName('Cielle')
    # **La même identité que TauDrive**, volontairement : les deux
    # partagent la mémoire des dossiers et les substitutions de police.
    # Un poste qui a les deux ne doit pas répondre deux fois à la même
    # question.
    app.setApplicationName('TauDrive')

    if '--convert' in sys.argv:
        from engrave.convert import run
        return run()

    from engrave import theme
    theme.apply(app)
    from engrave.convertapp import ConvertWindow
    fenetre = ConvertWindow()
    fenetre.show()
    return app.exec()


def autotest() -> int:
    """Vérifie que la version réduite est complète — et bien réduite."""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName('Cielle')
    app.setApplicationName('TauConvert-autotest')

    controles = []

    def check(libelle, ok, detail=''):
        controles.append((libelle, bool(ok), detail))

    import shutil
    import tempfile
    from engrave import convert, shellmenu
    from engrave.convertapp import ConvertWindow

    bac = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-conv-'))
    source = bac / 'cote.svg'
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        'height="60mm" viewBox="0 0 100 60">'
        '<rect x="10" y="10" width="80" height="40" fill="none"/>'
        '</svg>', encoding='utf-8')

    ecrits = {}
    for kind, _ in convert.TARGETS:
        cible = convert.convert(source, kind, dossier=bac / 'sortie')
        ecrits[kind] = cible.stat().st_size
    check('conversion : tous les formats de sortie sont produits',
          len(ecrits) == len(convert.TARGETS)
          and all(t > 0 for t in ecrits.values()),
          ' · '.join(f'{k} {t}o' for k, t in ecrits.items()))

    from engrave import vecimport, geometry
    relu, _ = vecimport.read(str(bac / 'sortie' / 'cote.svg'))
    boite = geometry.bounds(relu)
    check('conversion : la cote traverse la conversion intacte',
          abs((boite[2] - boite[0]) - 80.0) < 0.01
          and abs((boite[3] - boite[1]) - 40.0) < 0.01,
          f'{boite[2] - boite[0]:.3f} × {boite[3] - boite[1]:.3f} mm '
          f'pour 80 × 40')

    fenetre = ConvertWindow()
    check('fenêtre : construite, avec ses deux boutons',
          fenetre.windowTitle()
          and fenetre.bouton_poser is not None
          and fenetre.bouton_oter is not None,
          fenetre.windowTitle())

    # ce qui doit **rester dehors** : c'est la raison d'être de cette
    # version, et un import de trop la ferait taire sans qu'on le voie
    interdits = [m for m in ('engrave.app', 'jpt', 'cl90135', 'serial')
                 if m in sys.modules]
    check('réduite : ni application de gravure, ni machine',
          not interdits,
          'chargés à tort : ' + ', '.join(interdits) if interdits
          else 'aucune commande de laser sur un poste de bureau')

    # Refuser une oscillation trop dense tirait l'écrivain des fichiers
    # machine (`engrave.iso`) dans la version réduite, pour un message :
    # le refus vit désormais à côté du relevé, dans `toolpath`.
    from engrave import vecexport, wobble
    from engrave.model import Document, Recipe, Rect
    plafond = wobble.MAX_POINTS
    wobble.MAX_POINTS = 10
    refus = ''
    try:
        dense = Document(name='dense')
        dense.add(Rect(width=5, height=3, recipe=Recipe(
            name='osc', hatch_mm=0, wobble='circle', wobble_amp_mm=0.05,
            wobble_pitch_mm=0.05)))
        vecexport.export(dense, bac / 'dense.svg', toolpaths=True)
    except vecexport.ExportError as exc:
        refus = str(exc)
    finally:
        wobble.MAX_POINTS = plafond
    machine = [m for m in ('engrave.iso', 'engrave.morceaux')
               if m in sys.modules]
    check('réduite : une oscillation refusée sans l' + chr(39)
          + 'écrivain des fichiers machine',
          'trop dense' in refus and not machine,
          ('chargés à tort : ' + ', '.join(machine)) if machine
          else refus[:60])

    check('menu contextuel : pose et retrait offerts',
          hasattr(shellmenu, 'installer') and hasattr(shellmenu, 'retirer')
          and len(shellmenu.EXTENSIONS) >= 6,
          f'{len(shellmenu.EXTENSIONS)} extensions · '
          f'{len(convert.TARGETS)} formats de sortie')

    programme, avant = shellmenu.executable()
    inscrite = shellmenu.ligne_de_commande('dxf')
    check('menu contextuel : la version réduite s' + chr(39) + 'inscrit '
          'elle-même',
          'TauConvert' in inscrite and '--convert' in inscrite,
          'sinon le clic droit appellerait un TauDrive absent du poste')

    check('tutoriel : présent et non vide',
          len(fenetre.tutoriel_texte()) > 200,
          f'{len(fenetre.tutoriel_texte())} caractères')

    shutil.rmtree(bac, ignore_errors=True)

    largeur = max(len(l) for l, _, _ in controles)
    rates = 0
    for libelle, ok, detail in controles:
        rates += not ok
        print(f'  [{"OK " if ok else "KO "}] {libelle.ljust(largeur)}  '
              f'{detail}')
    print(f'\n{len(controles) - rates}/{len(controles)} contrôles passés')
    return 1 if rates else 0


if __name__ == '__main__':
    raise SystemExit(main())
