"""Publie une version zippée de TauDrive et de TauConvert.

    python outils/publier.py --monter           # 1.268.0 → 1.269.0, rien d'autre
    python outils/publier.py                    # empaquette, vérifie, zippe
    python outils/publier.py --sans-build       # zippe les dossiers déjà construits
    python outils/publier.py --sans-autotest    # empaquette et zippe sans vérifier
    python outils/publier.py --remplacer        # republie une version déjà sortie
    python outils/publier.py --plugin DOSSIER --edition ATELIER
                                                # et l'édition de l'atelier

**Le numéro, comme VectorDrive.** La version est `__version__` dans
`src/engrave/__init__.py` — `1.268.0` —, et le chiffre du milieu monte
de 1 à chaque publication : `--monter` le fait, dans le commit du cycle.
La fenêtre *À propos* et les propriétés Windows des exécutables
(`version_info.py`) lisent le même numéro. Jusqu'à 1.0.267, il était
tiré du dernier EX de la spécification.

1. refuse une version déjà publiée — son archive existe — sauf
   `--remplacer`, et une version que `NOUVEAUTES.md` ne décrit pas ;
2. empaquette avec PyInstaller : TauDrive dans `dist-neuf/` — le
   `dist/TauDrive/` d'un poste peut être en train de tourner, et Windows
   refuserait de l'écraser —, TauConvert dans `dist-convert/` ;
3. lance l'autotest de chaque exécutable figé : une archive ne sort que
   d'une version qui passe tous ses contrôles ;
4. fabrique `dist/portable/TauDrive-x.y.z-portable.zip` et
   `TauConvert-x.y.z-portable.zip` : le dossier de l'application,
   `NOUVEAUTES.md`, un `VERSION.txt` qui dit la version, le commit et la
   date, la licence (`LICENSE`, `LICENSE-MIT`, `LICENSE-APACHE`,
   `NOTICE`, `THIRD_PARTY_NOTICES.md`) et le dossier `licences` : les
   textes du dépôt, plus ceux que la distribution Python installée livre
   avec chaque composant embarqué ;
5. ne garde que les trois dernières versions de chacun.

**Les éditions.** `TauDrive` est le cœur libre, sans aucune donnée
d'atelier. `--plugin DOSSIER --edition NOM` fabrique en plus l'édition
d'un atelier : le TauDrive construit, recopié dans `dist-NOM/`, avec le
paquet du plugin posé dans `plugins/` à côté de l'exécutable. Son autotest
doit trouver le plugin et passer ses contrôles (grappe `plugins`) ; elle
sort dans `TauDrive-NOM-x.y.z-portable.zip`, dont le dossier reste
`TauDrive` — le poste garde son chemin.

Les archives restent hors git — `dist/` est ignoré : une application de
200 Mo par version ferait enfler le dépôt sans rien y apporter qu'un
commit ne permette de reconstruire.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PORTABLE = ROOT / 'dist' / 'portable'
PAQUET = ROOT / 'src' / 'engrave' / '__init__.py'
NOUVEAUTES = ROOT / 'NOUVEAUTES.md'
_MOTIF = re.compile(r"__version__ = '(\d+)\.(\d+)\.(\d+)'")

#: la licence de TauDrive, à la racine de chaque archive
LICENCE = ('LICENSE', 'LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE',
           'THIRD_PARTY_NOTICES.md')

#: composants embarqués dont la distribution installée livre la licence :
#: elle est recopiée dans `licences/`. PySide6 (LGPL-3.0) et pySerial n'en
#: livrent pas de texte utilisable — le dépôt porte les leurs, dans
#: `licences/`. Voir THIRD_PARTY_NOTICES.md.
TIERS = ('ezdxf', 'fonttools', 'shapely', 'numpy', 'pypdf', 'pillow',
         'cryptography', 'lxml', 'markupsafe', 'psutil',
         'charset_normalizer', 'brotli', 'cffi', 'pyinstaller')

#: versions gardées de chaque archive
GARDER = 3

#: application → (recette, dossier de construction)
PRODUITS = {
    'TauDrive': ('TauDrive.spec', 'dist-neuf'),
    'TauConvert': ('TauConvert.spec', 'dist-convert'),
}


def version() -> str:
    """`__version__` du paquet `engrave` : `1.268.0`."""
    m = _MOTIF.search(PAQUET.read_text(encoding='utf-8'))
    if not m:
        raise SystemExit(f'pas de __version__ = \'x.y.z\' dans {PAQUET}')
    return '.'.join(m.groups())


def monter() -> str:
    """Monte le chiffre du milieu et remet le dernier à zéro, comme
    VectorDrive : 1.268.0 → 1.269.0. Rien d'autre n'est touché."""
    brut = PAQUET.read_bytes().decode('utf-8')
    m = _MOTIF.search(brut)
    if not m:
        raise SystemExit(f'pas de __version__ = \'x.y.z\' dans {PAQUET}')
    neuve = f'{m.group(1)}.{int(m.group(2)) + 1}.0'
    PAQUET.write_bytes((brut[:m.start()] + f"__version__ = '{neuve}'"
                        + brut[m.end():]).encode('utf-8'))
    return neuve


def decrite(v: str) -> bool:
    """`NOUVEAUTES.md` a-t-il une entrée `### v<version>` ?"""
    return NOUVEAUTES.is_file() and re.search(
        rf'^### v{re.escape(v)}\b', NOUVEAUTES.read_text(encoding='utf-8'),
        re.M) is not None


def commit() -> str:
    """Le commit courant, suivi de `+modifs` si l'arbre n'est pas propre."""
    def git(*args: str) -> str:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    court = git('rev-parse', '--short', 'HEAD')
    # seuls les fichiers suivis comptent : `dist/` et `build/` sont ignorés
    sale = git('status', '--porcelain', '--untracked-files=no')
    return court + ('+modifs' if sale else '')


def construire(nom: str) -> pathlib.Path:
    recette, sortie = PRODUITS[nom]
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean',
                    '--noconfirm', '--distpath', sortie, recette],
                   cwd=ROOT, check=True)
    return ROOT / sortie / nom


def verifier(nom: str, dossier: pathlib.Path, plugin: str = '') -> str:
    """L'autotest de l'exécutable figé ; lève s'il échoue.

    Il se lance depuis la racine du dépôt, comme à la main : quelques
    contrôles relisent les sources (`src/engrave/app.py`…) que
    l'exécutable n'emporte pas. `TAUDRIVE_PLUGINS` est écarté : seul
    compte ce que l'archive porte. Une édition (`plugin`) doit trouver son
    plugin à côté de l'exécutable."""
    env = dict(os.environ, PYTHONIOENCODING='utf-8',
               QT_QPA_PLATFORM='offscreen',
               QT_QPA_FONTDIR='C:/Windows/Fonts')
    env.pop('TAUDRIVE_PLUGINS', None)
    exe = dossier / f'{nom.split("-")[0]}.exe'
    fait = subprocess.run([str(exe), '--autotest'],
                          cwd=ROOT, capture_output=True, env=env,
                          timeout=3600)
    sortie = fait.stdout.decode('utf-8', errors='replace')
    bilan = re.findall(r'(\d+)/(\d+) contrôles passés', sortie)
    ligne = next((l for l in sortie.splitlines()
                  if 'ceux posés se chargent sans erreur' in l), '')
    if plugin and ('[OK' not in ligne or 'aucun plugin posé' in ligne):
        raise SystemExit(f'{nom} : l\'autotest n\'a pas chargé le plugin '
                         f'{plugin}')
    if fait.returncode != 0 or not bilan or bilan[-1][0] != bilan[-1][1]:
        echecs = [ligne for ligne in sortie.splitlines() if '[KO' in ligne]
        raise SystemExit(f'{nom} : autotest en échec (code '
                         f'{fait.returncode}) — {bilan[-1] if bilan else "?"}'
                         + ''.join(f'\n  {e}' for e in echecs[:20]))
    return f'{bilan[-1][0]}/{bilan[-1][1]}'


def licences_tiers() -> list[tuple[pathlib.Path, str]]:
    """Les textes de licence à joindre : `(fichier, nom dans licences/)`.

    Ceux du dépôt (`licences/*.txt`), la licence de Python et de ce qu'il
    embarque, puis, pour chaque composant de `TIERS`, les fichiers de
    licence de sa distribution installée. S'arrête si l'un manque : une
    archive ne sort pas sans les licences de ce qu'elle contient."""
    import importlib.metadata as md
    textes = [(f, f.name) for f in sorted((ROOT / 'licences').glob('*.txt'))]
    python = pathlib.Path(sys.base_prefix) / 'LICENSE.txt'
    if not python.is_file():
        raise SystemExit(f'licence de Python introuvable : {python}')
    textes.append((python, 'Python-LICENSE.txt'))
    for nom in TIERS:
        try:
            dist = md.distribution(nom)
        except md.PackageNotFoundError:
            raise SystemExit(f'{nom} n\'est pas installé : sa licence '
                             f'manque') from None
        fichiers = [f for f in dist.files or ()
                    if '.dist-info' in str(f)
                    and re.search(r'LICEN[CS]E|COPYING', f.name, re.I)]
        if not fichiers:
            raise SystemExit(f'{nom} : aucun fichier de licence dans sa '
                             f'distribution')
        for f in fichiers:
            textes.append((pathlib.Path(dist.locate_file(f)),
                           f'{dist.metadata["Name"]}-{f.name}'))
    return textes


def edition(source: pathlib.Path, plugin: pathlib.Path,
            nom: str) -> pathlib.Path:
    """`dist-NOM/TauDrive` : le TauDrive construit et le plugin dans
    `plugins/`. Rend le dossier de l'édition."""
    if not (plugin / '__init__.py').is_file():
        raise SystemExit(f'{plugin} n\'est pas un paquet de plugin '
                         f'(pas de __init__.py)')
    dossier = ROOT / f'dist-{nom}' / 'TauDrive'
    if dossier.exists():
        shutil.rmtree(dossier)
    shutil.copytree(source, dossier)
    shutil.copytree(plugin, dossier / 'plugins' / plugin.name,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    return dossier


def zipper(nom: str, dossier: pathlib.Path, v: str, signe: str,
           bilan: str, racine: str = '') -> pathlib.Path:
    """`racine` : le dossier dans l'archive (le nom du produit par défaut)."""
    PORTABLE.mkdir(parents=True, exist_ok=True)
    archive = PORTABLE / f'{nom}-{v}-portable.zip'
    racine = racine or nom
    provisoire = archive.with_suffix('.zip.part')
    texte = (f'{nom} {v}\n'
             f'commit {signe}\n'
             f'construit le {dt.datetime.now():%Y-%m-%d %H:%M}\n'
             f'autotest {bilan}\n')
    with zipfile.ZipFile(provisoire, 'w', zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for f in sorted(dossier.rglob('*')):
            if f.is_file() and '__pycache__' not in f.parts:
                z.write(f, pathlib.Path(racine) / f.relative_to(dossier))
        z.writestr(f'{racine}/VERSION.txt', texte)
        z.write(NOUVEAUTES, f'{racine}/NOUVEAUTES.md')
        for fichier in LICENCE:
            z.write(ROOT / fichier, f'{racine}/{fichier}')
        for source, nom_lic in licences_tiers():
            z.write(source, f'{racine}/licences/{nom_lic}')
    # remplacé d'un coup : une archive à moitié écrite ne porte jamais le
    # nom définitif
    os.replace(provisoire, archive)
    return archive


def elaguer(nom: str) -> list[pathlib.Path]:
    """Retire les archives au-delà des `GARDER` plus récentes versions."""
    def cle(p: pathlib.Path):
        m = re.search(r'-(\d+)\.(\d+)\.(\d+)-portable\.zip$', p.name)
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
    archives = sorted(PORTABLE.glob(f'{nom}-*-portable.zip'), key=cle)
    retirees = archives[:-GARDER] if len(archives) > GARDER else []
    for p in retirees:
        p.unlink()
    return retirees


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--sans-build', action='store_true',
                   help='zipper les dossiers déjà construits')
    p.add_argument('--sans-autotest', action='store_true',
                   help='ne pas lancer l\'autotest des exécutables')
    p.add_argument('--monter', action='store_true',
                   help='monter le numéro (1.268.0 devient 1.269.0) et s\'arrêter')
    p.add_argument('--remplacer', action='store_true',
                   help='republier une version dont l\'archive existe déjà')
    p.add_argument('--plugin', type=pathlib.Path,
                   help='paquet du plugin d\'un atelier, pour son édition')
    p.add_argument('--edition', default='',
                   help='nom de l\'édition : TauDrive-NOM-x.y.z')
    p.add_argument('produits', nargs='*', default=list(PRODUITS),
                   help='TauDrive, TauConvert (les deux par défaut)')
    a = p.parse_args()
    if bool(a.plugin) != bool(a.edition):
        raise SystemExit('--plugin et --edition vont ensemble')
    if a.edition and not re.fullmatch(r'[A-Za-z0-9]+', a.edition):
        raise SystemExit(f'nom d\'édition invalide : {a.edition}')
    if a.edition and 'TauDrive' not in a.produits:
        raise SystemExit('une édition se fait avec TauDrive')
    if a.monter:
        avant = version()
        print(f'version {avant} montée à {monter()} : à décrire dans NOUVEAUTES.md '
              f'et à commiter')
        return
    v, signe = version(), commit()
    print(f'version {v} — commit {signe}')
    for nom in a.produits:
        if nom not in PRODUITS:
            raise SystemExit(f'produit inconnu : {nom}')
    # avant d'empaqueter : un refus ne coûte pas dix minutes de construction
    noms = list(a.produits) + ([f'TauDrive-{a.edition}'] if a.edition else [])
    deja = [PORTABLE / f'{nom}-{v}-portable.zip' for nom in noms]
    deja = [d for d in deja if d.exists()]
    if deja and not a.remplacer:
        raise SystemExit(f'{deja[0].name} existe déjà : une version ne sort '
                         f'qu\'une fois. `python outils/publier.py --monter`, '
                         f'puis décrire et commiter — ou --remplacer.')
    if not decrite(v):
        raise SystemExit(f'NOUVEAUTES.md ne décrit pas la version {v} : '
                         f'ajouter une entrée « ### v{v} — … ».')
    manquants = [f for f in LICENCE if not (ROOT / f).is_file()]
    if manquants:
        raise SystemExit(f'licence absente du dépôt : {", ".join(manquants)}')
    licences_tiers()
    for nom in a.produits:
        dossier = (ROOT / PRODUITS[nom][1] / nom if a.sans_build
                   else construire(nom))
        if not (dossier / f'{nom}.exe').is_file():
            raise SystemExit(f'{nom} : pas d\'exécutable dans {dossier}')
        bilan = 'non lancé' if a.sans_autotest else verifier(nom, dossier)
        archive = zipper(nom, dossier, v, signe, bilan)
        taille = archive.stat().st_size / 1e6
        print(f'{archive.relative_to(ROOT)}  {taille:.0f} Mo  autotest {bilan}')
        for r in elaguer(nom):
            print(f'  retirée : {r.name}')
        if nom == 'TauDrive' and a.edition:
            nom_ed = f'TauDrive-{a.edition}'
            dossier_ed = edition(dossier, a.plugin.resolve(), a.edition)
            bilan_ed = ('non lancé' if a.sans_autotest
                        else verifier(nom_ed, dossier_ed, a.edition))
            archive = zipper(nom_ed, dossier_ed, v, signe, bilan_ed,
                             racine='TauDrive')
            taille = archive.stat().st_size / 1e6
            print(f'{archive.relative_to(ROOT)}  {taille:.0f} Mo  '
                  f'autotest {bilan_ed}')
            for r in elaguer(nom_ed):
                print(f'  retirée : {r.name}')


if __name__ == '__main__':
    main()
