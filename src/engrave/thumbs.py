"""Vignettes de bibliothèque / Library thumbnails.

Parcourir une bibliothèque ne doit pas coûter le prix de ses dessins. Un
plan d'atelier pèse dix mégaoctets et porte dix mille tracés : le lire
prend une seconde, et le **garder en mémoire** douze mégaoctets. Trente
dessins parcourus, et l'application tenait 360 Mo de géométrie dont elle
n'affichait qu'un aperçu de trois cents pixels.

C'est ce qui la faisait ramer puis tomber.

La vignette casse ce lien. Elle est **décimée** — quinze cents points au
plus, assez pour reconnaître un dessin sur trois cents pixels — et rangée
**sur le disque**, à côté des réglages du poste. Un dessin déjà vu
s'affiche donc instantanément, sans rien lire de son fichier et sans
retenir un octet de sa géométrie.

Le dessin entier ne se charge que si on le **demande**, avec une barre de
progression et de quoi renoncer.

La clé tient compte de la **date et de la taille** du fichier : un dessin
modifié produit une clé différente, sa vieille vignette est ignorée, et
personne ne se retrouve devant une image périmée.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from . import geometry as G, session

#: Points au plus dans une vignette.
#:
#: Quinze cents suffisent : sur un aperçu de 300 px, cela fait un point
#: tous les cinq pixels de contour. Au-delà, on garde des détails plus
#: fins que le pixel — et on les paie en mémoire comme en disque.
MAX_POINTS = 1500

#: Vignettes gardées sur le disque. Au-delà, les plus anciennes partent.
MAX_FILES = 400


def cache_dir() -> pathlib.Path:
    """Où les vignettes se rangent, à côté des réglages du poste."""
    return pathlib.Path.home() / 'TauDrive' / 'vignettes'


#: Version des vignettes, dans leur clé : changée quand ce qu'elles
#: retiennent se calcule autrement. 2 : un DXF à sa vraie taille (EX-251)
#: — une vignette d'avant annonçait encore 150 m pour un dessin de 150 mm.
FORMAT = 2


def key_for(path: str | pathlib.Path) -> str:
    """Clé d'un fichier : son chemin, sa date et sa taille.

    La date et la taille en font partie pour que la vignette d'un dessin
    **modifié** ne soit jamais reprise. Une image périmée est pire que pas
    d'image : on croit reconnaître, et l'on pose le mauvais dessin. La
    version (`FORMAT`) écarte de même celles d'un calcul abandonné.
    """
    p = pathlib.Path(path)
    try:
        etat = p.stat()
        marque = (f'{FORMAT}|{p.resolve()}|{int(etat.st_mtime)}|'
                  f'{etat.st_size}')
    except OSError:
        marque = str(p)
    return hashlib.sha1(marque.encode('utf-8')).hexdigest()[:20]


def decimate(polys: list, budget: int = MAX_POINTS) -> list:
    """Version allégée d'un tracé, un point sur `n`.

    Les extrémités de chaque polyligne sont **toujours gardées** : un
    contour qui perdrait son dernier point s'ouvrirait, et un contour
    ouvert se voit tout de suite sur un aperçu.
    """
    total = sum(len(p) for p in polys)
    if total <= budget or not polys:
        return [list(p) for p in polys]
    pas = max(2, total // max(1, budget))
    allege = []
    for poly in polys:
        if len(poly) <= 3:
            allege.append(list(poly))
            continue
        court = list(poly[::pas])
        if court[-1] != poly[-1]:
            court.append(poly[-1])
        if len(court) >= 2:
            allege.append(court)
    return allege


def load(path: str | pathlib.Path) -> tuple[list, tuple | None] | None:
    """La vignette d'un fichier, ou `None` si elle n'est pas en réserve."""
    fichier = cache_dir() / f'{key_for(path)}.json'
    try:
        brut = json.loads(fichier.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    polys = [[(float(x), float(y)) for x, y in poly]
             for poly in brut.get('p', [])]
    emprise = brut.get('b')
    return (polys, tuple(emprise) if emprise else None)


def store(path: str | pathlib.Path, polys: list) -> None:
    """Range la vignette d'un fichier. Silencieux en cas d'échec.

    Un disque plein ou un dossier en lecture seule ne doit pas empêcher
    d'ouvrir un dessin : la vignette est un confort, pas une dépendance.
    """
    allege = decimate(polys)
    emprise = G.bounds(polys) if polys else None
    dossier = cache_dir()
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f'{key_for(path)}.json').write_text(
            json.dumps({'p': [[[round(x, 3), round(y, 3)] for x, y in poly]
                              for poly in allege],
                        'b': list(emprise) if emprise else None,
                        'n': len(polys)},
                       separators=(',', ':')),
            encoding='utf-8')
    except OSError:
        return
    prune()


def prune(limit: int = MAX_FILES) -> int:
    """Retire les vignettes les plus anciennes. Rend le nombre effacé."""
    dossier = cache_dir()
    try:
        fichiers = sorted(dossier.glob('*.json'),
                          key=lambda f: f.stat().st_mtime)
    except OSError:
        return 0
    efface = 0
    for vieux in fichiers[:max(0, len(fichiers) - limit)]:
        try:
            vieux.unlink()
            efface += 1
        except OSError:
            continue
    return efface


def forget() -> int:
    """Vide la réserve entière. Rend le nombre de vignettes effacées."""
    return prune(0)


def size_on_disk() -> int:
    """Octets occupés par la réserve."""
    try:
        return sum(f.stat().st_size for f in cache_dir().glob('*.json'))
    except OSError:
        return 0


def describe(path: str | pathlib.Path) -> dict:
    """Ce qu'on sait d'un fichier **sans le lire** : taille, date, format.

    C'est ce qu'on montre pendant qu'on parcourt : instantané, et déjà
    utile. Le dessin lui-même attend qu'on le demande.
    """
    import datetime
    p = pathlib.Path(path)
    try:
        etat = p.stat()
        octets, quand = etat.st_size, etat.st_mtime
    except OSError:
        octets, quand = 0, 0
    return {
        'nom': p.stem,
        'octets': octets,
        'taille': human_size(octets),
        'quand': (datetime.datetime.fromtimestamp(quand).strftime(
            '%d/%m/%Y') if quand else ''),
        'format': p.suffix.lstrip('.').lower() or 'sans suffixe',
        'lourd': octets > HEAVY_BYTES,
    }


#: Au-delà, un dessin est annoncé comme lourd avant qu'on l'ouvre.
HEAVY_BYTES = 2_000_000


def human_size(octets: int) -> str:
    if octets >= 1_000_000:
        return f'{octets / 1_000_000:.1f} Mo'
    if octets >= 1000:
        return f'{octets / 1000:.0f} ko'
    return f'{octets} o'
