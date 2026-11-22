"""Exporte le dépôt public de TauDrive à partir du dépôt de travail.

    python outils/exporter_public.py DOSSIER_PUBLIC --interdits FICHIER [--message "…"]

Comme pour VectorDrive :

- copie les fichiers suivis par git, sauf les documents de travail privés
  (`PRIVES` : spécification de travail, notes d'analyse des protocoles et
  des fichiers de la machine, outils d'extraction, données relevées chez
  les fournisseurs, fichiers de clients, essais d'atelier) ;
- publie `README.public.md` sous le nom `README.md` (`PUBLIES_SOUS`) : le
  README du dépôt de travail, qui suit l'avancement et pointe vers les
  documents privés, ne sort pas ;
- refuse l'export si un fichier publié est un fichier de production
  (programme machine, dessin), contient un des mots du fichier
  `--interdits` (un par ligne : clients, matricule, chemins du poste… ;
  le fichier lui-même reste privé, dans le dépôt du plugin de l'atelier),
  ou si un document publié renvoie par un lien vers un fichier qui ne
  l'est pas ;
- dans DOSSIER_PUBLIC : dépôt git neuf au premier export, puis un commit
  par export — l'historique du dépôt de travail n'est jamais publié.

Les fichiers sont pris **dans l'arbre de travail** : ceux qui y diffèrent
du dernier commit sont nommés avant l'export.

Rien n'est poussé vers un serveur : c'est à l'auteur de le faire.
"""
from __future__ import annotations

import argparse
import fnmatch
import pathlib
import posixpath
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: documents de travail qui ne sortent pas (motifs fnmatch, chemins relatifs)
PRIVES = [
    '.claude/*',
    # README de travail : avancement, captures, documents privés
    # (le public reçoit README.public.md, voir PUBLIES_SOUS)
    'README.md',
    # spécification de travail : décisions, essais et fichiers d'atelier
    'reference/specification.md',
    # journal de développement tenu à l'atelier, et son montage en service
    'reference/export-iso.md',
    'reference/montage-3dm.md',
    # protocole de la carte CNC : relevé pour l'étude, l'application ne
    # s'en sert pas (TauDrive écrit des fichiers que ClTerm exécute)
    'src/cl90135/*',
    # notes d'analyse des protocoles et des fichiers de la machine
    'reference/protocole-*',
    'reference/format-cmd.md',
    'reference/dictionnaire-parametres.md',
    'reference/magasin-outils.md',
    'reference/limites-machine.md',
    'reference/parametres-laser.md',
    'reference/analyse-capture-*',
    'reference/trace-nommee-*',
    'reference/procedure-capture.md',
    # outils d'extraction et d'analyse, et essais sur le corpus capturé
    'outils/pe_strings.py',
    'outils/extract_frames.py',
    'outils/analyse_payload.py',
    'outils/extraire_*.py',
    'outils/audit_recommandations.py',
    'outils/test_cmdfile.py',
    'outils/test_frame.py',
    # données relevées chez les fournisseurs (hors licence, voir LICENSE)
    'extrait/*',
    # versions figées, essais d'atelier
    '260901 TauDrive/*',
    'Test Coupon/*',
    'retire-serveur-*.zip',
    # dessins, plans et rendus : ceux du dépôt sont des fichiers de clients,
    # et TauDrive libre n'en livre aucun
    '*.dxf',
    '*.dwg',
    '*.eps',
    '*.ai',
    '*.pdf',
    '*.jpg',
]
#: fichiers publiés sous un autre nom (nom dans le dépôt de travail → nom publié)
PUBLIES_SOUS = {'README.public.md': 'README.md'}
AUTEUR = 'RomDuch <romduch@gmail.com>'
#: programmes machine et parcours (jamais publiés : ce sont des fichiers de production)
PROGRAMMES = re.compile(r'\.(iso|cljob|cmd|nc|cnc|tap|ngc|plt|hpgl|\d{3})$', re.I)
#: dessins (jamais publiés : TauDrive libre n'en livre aucun)
DESSINS = re.compile(r'\.(dxf|dwg|taudrive|eps|ai|svg|pdf)$', re.I)
_VERSION = re.compile(r"__version__ = '(\d+\.\d+\.\d+)'")
#: lien Markdown : [texte](cible) — la cible jusqu'à l'ancre ou au titre
_LIEN = re.compile(r'\]\(\s*<?([^)\s#>]+)')


def published_name(f: str) -> str:
    """Nom sous lequel un fichier du dépôt de travail est publié."""
    return PUBLIES_SOUS.get(f, f)


def publishable() -> list[str]:
    files = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT,
                           capture_output=True, check=True).stdout
    noms = [f.decode('utf-8') for f in files.split(b'\0') if f]
    return [f for f in noms if not any(fnmatch.fnmatch(f, p) for p in PRIVES)
            and (ROOT / f).is_file()]


def modified(files: list[str]) -> list[str]:
    """Fichiers publiés qui diffèrent du dernier commit."""
    sortie = subprocess.run(['git', 'diff', '--name-only', '-z', 'HEAD'],
                            cwd=ROOT, capture_output=True, check=True).stdout
    changes = {f.decode('utf-8') for f in sortie.split(b'\0') if f}
    return [f for f in files if f in changes]


def production_files(files: list[str]) -> list[str]:
    """Programmes machine, parcours et dessins parmi les fichiers publiés."""
    return [f for f in files if PROGRAMMES.search(f) or DESSINS.search(f)]


def _text(path: pathlib.Path) -> str | None:
    """Contenu d'un fichier texte (quelle que soit son extension), None s'il est binaire."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b'\0' in data[:8192]:
        return None
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('latin-1')


def broken_links(files: list[str]) -> list[str]:
    """Liens des documents publiés vers un fichier qui ne l'est pas : une
    note privée nommée, et un lien mort pour le lecteur."""
    publies = {published_name(f) for f in files}
    hits = []
    for f in files:
        nom = published_name(f)
        if not nom.endswith('.md'):
            continue
        text = _text(ROOT / f) or ''
        for m in _LIEN.finditer(text):
            cible = m.group(1)
            if re.match(r'[a-z][a-z0-9+.-]*:', cible, re.I):   # http:, mailto:…
                continue
            chemin = posixpath.normpath(
                posixpath.join(posixpath.dirname(nom), cible))
            if chemin not in publies and not any(
                    p.startswith(chemin.rstrip('/') + '/') for p in publies):
                line = text.count('\n', 0, m.start()) + 1
                hits.append(f'{f}:{line} : lien vers un fichier non publié ({cible})')
    return hits


def scan(files: list[str], words: list[str]) -> list[str]:
    """Fichiers (nom ou contenu) où paraît un mot interdit, fichiers de
    production (programmes, parcours, dessins) qui n'ont rien à publier,
    et liens vers des fichiers non publiés."""
    pats = [re.compile(re.escape(w), re.I) for w in words if w.strip()]
    hits = [f'{f} : fichier de production (programme, parcours ou dessin)'
            for f in production_files(files)]
    hits += broken_links(files)
    for f in files:
        for p in pats:
            if p.search(f):
                hits.append(f'{f} : nom ({p.pattern})')
        text = _text(ROOT / f)
        if text is None:
            continue
        for p in pats:
            for m in p.finditer(text):
                line = text.count('\n', 0, m.start()) + 1
                hits.append(f'{f}:{line} : {p.pattern}')
    return hits


def export(dest: pathlib.Path, words: list[str], message: str) -> int:
    files = publishable()
    hits = scan(files, words)
    if hits:
        print('Export refusé — données privées dans des fichiers publiés :')
        print('\n'.join('  ' + h for h in hits[:200]))
        return 1
    for f in modified(files):
        print(f'  pris dans l\'arbre de travail, modifié depuis le commit : {f}')
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.rglob('*'):                       # repartir propre (sauf .git)
        if '.git' in old.relative_to(dest).parts or not old.is_file():
            continue
        old.unlink()
    for f in files:
        out = dest / published_name(f)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, out)

    def git(*a):
        return subprocess.run(['git', *a], cwd=dest, check=True,
                              capture_output=True, text=True, encoding='utf-8')
    if not (dest / '.git').exists():
        git('init', '-q', '-b', 'main')
    git('add', '-A')
    if not git('status', '--porcelain').stdout.strip():
        print('rien de neuf à publier')
        return 0
    name, mail = AUTEUR[:-1].split(' <')
    git('-c', f'user.name={name}', '-c', f'user.email={mail}', 'commit', '-q',
        '-m', message)
    print(f'{len(files)} fichiers exportés dans {dest} ; dernier commit : '
          + git('log', '--oneline', '-1').stdout.strip())
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('dest')
    ap.add_argument('--interdits', required=True,
                    help='fichier privé des mots interdits (un par ligne)')
    ap.add_argument('--message', default='')
    args = ap.parse_args(argv)
    words = [w.strip() for w in pathlib.Path(args.interdits)
             .read_text(encoding='utf-8').splitlines()
             if w.strip() and not w.startswith('#')]
    if not words:
        raise SystemExit('aucun mot interdit : export refusé par prudence')
    m = _VERSION.search((ROOT / 'src' / 'engrave' / '__init__.py')
                        .read_text(encoding='utf-8'))
    version = m.group(1) if m else '?'
    msg = args.message or (f'TauDrive {version}\n\n'
                           'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')
    return export(pathlib.Path(args.dest), words, msg)


if __name__ == '__main__':
    sys.exit(main())
