"""Bibliothèque de dessins / Drawing library.

Un atelier regrave les mêmes motifs : un logo, une silhouette, un cartouche.
Les retrouver chaque fois dans l'arborescence, redécider des unités et de
l'échelle, c'est du temps perdu et une occasion de se tromper.

La bibliothèque range ces dessins à un endroit connu et les pose d'un
double-clic, prêts à être placés et redimensionnés.

**Deux étagères.**

* Les dessins **livrés** avec TauDrive, dans ses ressources. En lecture
  seule : une mise à jour de l'application les remplace, et ce qu'on y
  aurait ajouté disparaîtrait.
* Les dessins **du poste**, dans un dossier réglable. Pointé sur un
  partage réseau, c'est la bibliothèque de l'atelier — chacun y ajoute, et
  tout le monde en profite. C'est le même principe que la bibliothèque de
  process.

**Tous les formats vectoriels que TauDrive lit** y entrent : `.dxf`,
`.pdf`, `.ai`, `.eps`, `.ps`, et `.cdr` si un convertisseur est installé.
Ils apportent leur géométrie et reçoivent la process courante.

Le `.taudrive` fait exception : il apporte en plus les **process** de ses
formes. Ranger une plaque au point comme élément de bibliothèque conserve
donc les paramètres laser avec lesquels elle a été validée.
"""
from __future__ import annotations

import pathlib
import shutil
from dataclasses import dataclass

from . import session

#: Extensions acceptées, et ce que chacune apporte.
#:
#: Un `.taudrive` apporte ses **process** en plus de sa géométrie ; tous
#: les autres n'apportent que le dessin, et reçoivent la process courante.
SUFFIXES = ('.dxf', '.pdf', '.ai', '.eps', '.ps', '.svg', '.cdr',
            '.taudrive')

#: Clé du dossier réglable, dans les dossiers par défaut.
FOLDER_KIND = 'bibliotheque'

#: Où la bibliothèque du poste se range quand rien n'est réglé.
def default_user_dir() -> pathlib.Path:
    return pathlib.Path.home() / 'TauDrive' / 'Bibliotheque'


@dataclass(frozen=True)
class Entry:
    """Un dessin de la bibliothèque, avec le rayon qui le range."""
    name: str
    path: pathlib.Path
    delivered: bool
    #: Sous-dossier relatif à l'étagère, en style POSIX. Vide à la racine.
    folder: str = ''

    def suffix(self) -> str:
        return self.path.suffix.lower()

    def editable(self) -> bool:
        """Un dessin livré ne se renomme ni ne s'efface."""
        return not self.delivered

    def key(self) -> str:
        """Identité d'un dessin : son rayon **et** son nom.

        Deux « logo » peuvent coexister dans deux rayons différents ; le
        nom seul ne suffit donc plus à désigner un dessin.
        """
        return f'{self.folder}/{self.name}' if self.folder else self.name

    def label(self) -> str:
        marque = 'livré' if self.delivered else 'poste'
        return f'{self.name}   ({marque}, {self.suffix().lstrip(".")})'


def delivered_dir() -> pathlib.Path:
    """Dossier des dessins livrés : celui du plugin de l'atelier s'il en
    donne un, `ressources/bibliotheque` sinon — vide dans la distribution
    libre, qui ne livre aucun dessin."""
    from .plugins import REGISTRY
    if REGISTRY.drawings_dir is not None:
        return REGISTRY.drawings_dir
    from .app import resource_dir
    return resource_dir() / 'bibliotheque'


def user_dir() -> pathlib.Path:
    """Dossier des dessins du poste, réglable dans les dossiers par défaut."""
    reglage = session.default_folder(FOLDER_KIND)
    return pathlib.Path(reglage) if reglage.strip() else default_user_dir()


def set_user_dir(path: str) -> None:
    session.set_default_folder(FOLDER_KIND, path)


#: Profondeur maximale de descente sous une étagère. Une bibliothèque
#: pointée par mégarde sur la racine d'un disque ne doit pas mettre une
#: minute à s'ouvrir.
MAX_DEPTH = 4


def _scan(folder: pathlib.Path, delivered: bool) -> list[Entry]:
    """Contenu d'une étagère, **rayons compris**, trié, sans jamais lever.

    Un dossier injoignable — partage réseau débranché — rend une liste
    vide : la bibliothèque du poste s'efface, celle des dessins livrés
    reste. L'application ne doit pas dépendre du réseau pour s'ouvrir.
    """
    if not session.reachable(str(folder)):
        return []
    trouves: list[Entry] = []
    for fichier in _walk(folder, MAX_DEPTH):
        rangement = fichier.parent.relative_to(folder).as_posix()
        trouves.append(Entry(fichier.stem, fichier, delivered,
                             '' if rangement == '.' else rangement))
    return sorted(trouves, key=lambda e: (e.folder.lower(), e.name.lower()))


def _walk(folder: pathlib.Path, depth: int):
    """Les dessins de `folder`, puis ceux de ses rayons."""
    try:
        contenu = sorted(folder.iterdir(), key=lambda f: f.name.lower())
    except OSError:
        return
    for f in contenu:
        try:
            if f.is_file() and f.suffix.lower() in SUFFIXES:
                yield f
            elif f.is_dir() and depth > 0 and not f.name.startswith('.'):
                yield from _walk(f, depth - 1)
        except OSError:
            continue


def entries(folder: str = '') -> list[Entry]:
    """Toute la bibliothèque : les dessins livrés, puis ceux du poste.

    `folder` restreint au **rayon** demandé, sous-rayons exclus : c'est ce
    qu'on attend d'un dossier qu'on vient d'ouvrir.
    """
    tout = _scan(delivered_dir(), True) + _scan(user_dir(), False)
    if not folder:
        return tout
    return [e for e in tout if e.folder == folder]


def find(name: str) -> Entry | None:
    """Un dessin par son nom, ou par « rayon/nom » s'il y a ambiguïté."""
    cherche = (name or '').strip().lower()
    for entry in entries():
        if entry.key().lower() == cherche:
            return entry
    for entry in entries():
        if entry.name.lower() == cherche:
            return entry
    return None


# --- rayons ----------------------------------------------------------------
#
# Une bibliothèque d'atelier grossit vite : logos clients, cartouches,
# gabarits, pièces d'essai. Une liste à plat de deux cents entrées ne se
# lit plus.
#
# Les rayons sont de **vrais sous-dossiers** sur le disque, et non un
# classement propre à TauDrive : on peut les ranger depuis l'explorateur,
# et un partage réseau garde le même sens pour tout le monde.


def folders() -> list[str]:
    """Rayons de la bibliothèque, **y compris ceux qui sont vides**.

    Un rayon créé puis laissé vide doit rester visible : sinon on le crée,
    il disparaît, et l'on croit que la création a échoué.
    """
    vus: set[str] = {e.folder for e in entries() if e.folder}
    for etagere in (delivered_dir(), user_dir()):
        if not session.reachable(str(etagere)):
            continue
        for sous in _subdirs(etagere, MAX_DEPTH):
            vus.add(sous.relative_to(etagere).as_posix())
    return sorted(vus, key=str.lower)


def _subdirs(folder: pathlib.Path, depth: int):
    try:
        contenu = sorted(folder.iterdir(), key=lambda f: f.name.lower())
    except OSError:
        return
    for f in contenu:
        try:
            if f.is_dir() and not f.name.startswith('.'):
                yield f
                if depth > 1:
                    yield from _subdirs(f, depth - 1)
        except OSError:
            continue


def make_folder(folder: str) -> str:
    """Crée un rayon dans la bibliothèque du poste. Rend son chemin relatif."""
    propre = clean_folder(folder)
    if not propre:
        raise ValueError('nom de rayon vide')
    (user_dir() / propre).mkdir(parents=True, exist_ok=True)
    return propre


def drop_folder(folder: str) -> None:
    """Efface un rayon **vide** de la bibliothèque du poste.

    Un rayon qui contient encore des dessins n'est pas effacé : perdre
    trente dessins sur un clic serait sans recours.
    """
    propre = clean_folder(folder)
    if not propre:
        return
    cible = user_dir() / propre
    if any(True for _ in _walk(cible, MAX_DEPTH)):
        raise ValueError('le rayon contient encore des dessins')
    try:
        cible.rmdir()
    except OSError as exc:
        raise ValueError(f'rayon non effacé : {exc}') from None


def move(entry: Entry, folder: str) -> Entry:
    """Déplace un dessin du poste vers un autre rayon."""
    if entry.delivered:
        raise ValueError('un dessin livré ne se déplace pas')
    propre = clean_folder(folder)
    dossier = user_dir() / propre if propre else user_dir()
    dossier.mkdir(parents=True, exist_ok=True)
    cible = _free_name(dossier / entry.path.name, ignore=entry.path)
    if cible == entry.path:
        return entry
    entry.path.rename(cible)
    return Entry(cible.stem, cible, False, propre)


def clean_folder(folder: str) -> str:
    """Chemin de rayon sûr : ni remontée, ni racine, ni lettre de lecteur."""
    morceaux = []
    for part in str(folder or '').replace(chr(92), '/').split('/'):
        propre = _clean(part)
        if propre and propre not in ('.', '..'):
            morceaux.append(propre)
    return '/'.join(morceaux[:MAX_DEPTH])


# --- gestion ---------------------------------------------------------------

def add(source: str | pathlib.Path, name: str = '',
        folder: str = '') -> Entry:
    """Range une copie de `source` dans la bibliothèque du poste.

    Une **copie**, pas un lien : un dessin de bibliothèque doit survivre
    au ménage du dossier d'où il venait.
    """
    source = pathlib.Path(source)
    if source.suffix.lower() not in SUFFIXES:
        raise ValueError(f'format non géré : {source.suffix or "sans suffixe"}')
    rangement = clean_folder(folder)
    dossier = user_dir() / rangement if rangement else user_dir()
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / f'{_clean(name) or source.stem}{source.suffix.lower()}'
    cible = _free_name(cible)
    shutil.copy2(source, cible)
    return Entry(cible.stem, cible, False, rangement)


def rename(entry: Entry, name: str) -> Entry:
    """Renomme un dessin du poste. Un dessin livré n'est pas modifiable."""
    if entry.delivered:
        raise ValueError('un dessin livré ne se renomme pas')
    propre = _clean(name)
    if not propre:
        raise ValueError('nom vide')
    cible = _free_name(entry.path.with_name(f'{propre}{entry.path.suffix}'),
                       ignore=entry.path)
    entry.path.rename(cible)
    return Entry(cible.stem, cible, False, entry.folder)


def remove(entry: Entry) -> None:
    """Efface un dessin du poste. Un dessin livré n'est pas effaçable."""
    if entry.delivered:
        raise ValueError('un dessin livré ne s\'efface pas')
    entry.path.unlink(missing_ok=True)


def _clean(name: str) -> str:
    """Nom de fichier sûr, sans séparateur ni remontée de chemin."""
    interdits = '\\/:*?"<>|'
    propre = ''.join(' ' if c in interdits else c for c in (name or ''))
    return ' '.join(propre.split()).strip('. ')[:60]


def _free_name(cible: pathlib.Path,
               ignore: pathlib.Path | None = None) -> pathlib.Path:
    """`cible`, ou `cible-02`, `cible-03`… si le nom est déjà pris."""
    if not cible.exists() or (ignore and cible == ignore):
        return cible
    for rang in range(2, 1000):
        essai = cible.with_name(f'{cible.stem}-{rang:02d}{cible.suffix}')
        if not essai.exists():
            return essai
    return cible


# --- chargement ------------------------------------------------------------

def load(entry: Entry, recipe=None, units_mm: float | None = None,
         progress=None):
    """Formes d'un dessin de bibliothèque, prêtes à être ajoutées.

    Un `.taudrive` rend ses formes **avec leurs process** : c'est tout
    l'intérêt d'y ranger une plaque déjà validée. Un `.dxf` reçoit la
    process passée en argument, comme à l'import.

    `progress(fraction, texte)` suit la lecture et l'interrompt en rendant
    `False` — voir `dxfimport.read`. Un dessin d'atelier pèse dix
    mégaoctets : le lire est une opération qui se surveille et qui
    s'abandonne, pas une opération qu'on subit.
    """
    if entry.suffix() == '.taudrive':
        from . import serialize
        if progress is not None and progress(0.0, 'lecture…') is False:
            from .dxfimport import Cancelled
            raise Cancelled('lecture')
        document = serialize.loads(
            entry.path.read_text(encoding='utf-8'))
        if progress is not None:
            progress(1.0, 'terminé')
        return list(document.shapes)

    from . import dxfimport
    from .geometry import bounds
    from .model import hors_borne

    def emprise(formes):
        return bounds([p for f in formes for p in getattr(f, 'polylines', ())])

    shapes, rapport = dxfimport.any_to_shapes(entry.path, recipe=recipe,
                                              units_mm=units_mm,
                                              progress=progress)
    # L'en-tête d'un DXF ment souvent sur son unité (EX-14) : celui d'un
    # fichier d'essai se dit en mètres, et le dessin arrivait large de
    # 156 m. Au-delà de dix mètres, un point ne survit ni à
    # l'enregistrement ni à « annuler » — la relecture l'écarte : le dessin
    # disparaissait au premier « refaire ». Il est alors relu en
    # millimètres, l'unité que propose l'import ; une unité déclarée
    # vraisemblable reste respectée.
    b = emprise(shapes)
    # déjà lu en millimètres : le relire rendrait la même chose
    if (units_mm is None and dxfimport.is_dxf(entry.path) and hors_borne(b)
            and getattr(rapport, 'units_mm', 1.0) != 1.0):
        shapes, _ = dxfimport.any_to_shapes(entry.path, recipe=recipe,
                                            units_mm=1.0, progress=progress)
        b = emprise(shapes)
    if hors_borne(b):
        raise ValueError(
            f'le dessin mesure {(b[2] - b[0]) / 1000:.0f} × '
            f'{(b[3] - b[1]) / 1000:.0f} m : au-delà de dix mètres, il ne '
            f'pourrait être ni enregistré ni annulé. « Importer un '
            f'dessin… » sait le réduire au champ')
    return list(shapes)


def preview(entry: Entry, recipe=None, progress=None):
    """Contours **exacts** d'un dessin. Vide s'il est illisible.

    C'est la pleine définition : le fichier est lu en entier, hachurage
    des formes compris. Pour parcourir une bibliothèque, voir `outline`,
    qui coûte dix à vingt fois moins cher.
    """
    from . import geometry as G
    from .dxfimport import Cancelled
    from .toolpath import group_zones, shape_polylines
    try:
        shapes = load(entry, recipe=recipe, progress=progress)
    except Cancelled:
        raise
    except Exception:
        return [], None
    # posées, ses formes seront groupées : l'aperçu les remplit de même
    zones = group_zones(shapes, ensemble=True)
    polys = [p for shape in shapes
             for p in shape_polylines(shape, zone=zones.get(shape.id))]
    return polys, (G.bounds(polys) if polys else None)


#: Taille au-delà de laquelle un format sans lecteur d'esquisse n'est plus
#: aperçu tout seul. Ces lecteurs-là — PDF, EPS, Illustrator — sont rapides
#: mais pas gratuits ; passé quelques mégaoctets, mieux vaut demander.
HEAVY_BYTES = 4 * 1024 * 1024


def outline(entry: Entry, recipe=None, respirer=None):
    """**Esquisse** d'un dessin : de quoi le reconnaître, et rien de plus.

    Rend un `sketch.Outline`. C'est ce que le panneau affiche pendant
    qu'on parcourt la bibliothèque — un DXF de cinq mégaoctets s'esquisse
    en un tiers de seconde là où sa lecture exacte en demande sept.

    `respirer` rend la main de loin en loin, pour l'esquisse faite dans un
    fil de fond : voir `sketch.dxf_outline`.

    Les formats sans lecteur d'esquisse retombent sur la lecture exacte,
    et seulement en deçà de `HEAVY_BYTES` : au-delà, on annonce le poids
    et l'on attend *Visualiser*.
    """
    from . import sketch
    if entry.suffix() == '.dxf':
        return sketch.dxf_outline(entry.path, respirer=respirer)
    try:
        taille = entry.path.stat().st_size
    except OSError as exc:
        return sketch.Outline(note=f'Fichier illisible : {exc}')
    if taille > HEAVY_BYTES:
        return sketch.Outline(
            note=f'{taille / 1e6:.1f} Mo — aperçu à la demande.\n'
                 f'Bouton « Visualiser ».')
    polys, bornes = preview(entry, recipe=recipe)
    if not polys:
        return sketch.Outline(note='Dessin illisible ou vide.')
    return sketch.Outline(polys, bornes, True, '')
