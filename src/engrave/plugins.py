"""Plugins : ce qui est propre à un atelier vit hors du cœur.

TauDrive, le cœur, est libre et ne porte **aucune donnée d'atelier** :
ni process relevées sur une machine, ni magasin d'outils, ni dessins
livrés, ni couples mesurés sur pièce, ni matricule. Un atelier les
apporte par un plugin, comme pour VectorDrive.

Un plugin est un paquet Python qui expose `PLUGIN` (métadonnées : 'nom',
'version', 'api', 'licence', 'description') et `register(api)` ; `api`
est une `Api`, la seule porte d'entrée vers le cœur. Ce qu'il apporte est
rangé dans `REGISTRY`, que le cœur consulte :

* process : préréglages et process par matière (`model.factory_recipes`),
  valeurs par défaut d'une process (`model.default_recipe`) ;
* semence du premier lancement (`semence.dossier`) ;
* gabarit de montage livré, celui du montage en service (`gabarits.livre`) ;
* magasin d'outils extrait de la machine (`toolstore.bundled_path`) ;
* couples fréquence-impulsion d'atelier, nommés (`couples.workshop`) ;
* dessins livrés (`drawings.delivered_dir`) ;
* nom de la machine (*À propos*), lignes de *À propos* ;
* contrôles de l'autotest (grappe `plugins`).

Les couples constructeur de la source JPT (`couples.FACTORY`) sont des
limites de la source, pas des données d'atelier : ils restent au cœur.

Recherche (`load`) : dossier `plugins/` à côté de l'exécutable (ou du
dépôt, en développement), puis `%LOCALAPPDATA%/TauDrive/plugins`, puis
`TAUDRIVE_PLUGINS` (chemins séparés par `;`). `TAUDRIVE_NO_PLUGINS=1`
désactive tout. Un plugin en erreur est noté (`PluginInfo.error`, dit
dans *À propos*) et n'empêche jamais le démarrage.

`load` est appelé au démarrage de l'application (`app.main`) et de la
conversion en ligne de commande, **avant** la semence et la bibliothèque
de process. L'autotest des grappes du cœur ne le fait pas : il éprouve le
cœur libre seul, quels que soient les plugins posés à côté.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import sys
import traceback
from dataclasses import dataclass, field
from typing import Callable

#: version de l'API ; un plugin qui en demande une autre n'est pas chargé
API_VERSION = 1
ENV_PATHS = 'TAUDRIVE_PLUGINS'
ENV_OFF = 'TAUDRIVE_NO_PLUGINS'


@dataclass
class PluginInfo:
    module: str
    name: str = ''
    version: str = ''
    licence: str = ''
    description: str = ''
    path: str = ''
    error: str = ''

    @property
    def ok(self) -> bool:
        return not self.error

    def label(self) -> str:
        """« Atelier 1.0.0 (propriétaire) », ou l'erreur."""
        nom = f'{self.name or self.module} {self.version}'.strip()
        if self.error:
            return f'{nom} : non chargé — {self.error}'
        return nom + (f' ({self.licence})' if self.licence else '')


@dataclass
class Registry:
    """Contributions des plugins chargés."""
    plugins: list = field(default_factory=list)              # PluginInfo
    recipes: list = field(default_factory=list)              # préréglages (Recipe)
    material_recipes: list = field(default_factory=list)     # process par matière (Recipe)
    recipe_defaults: dict = field(default_factory=dict)      # champ → valeur
    seed_dir: pathlib.Path | None = None
    tool_store: pathlib.Path | None = None
    couples: list = field(default_factory=list)              # couples.Couple
    drawings_dir: pathlib.Path | None = None
    montage: dict | None = None                              # gabarit livré
    machine: str = ''
    about: list = field(default_factory=list)
    autotests: list = field(default_factory=list)            # (nom, fonction(check))


REGISTRY = Registry()
_loaded = False


class Api:
    """Ce qu'un plugin peut faire. Toutes les méthodes sont sans effet sur
    les fichiers : elles déclarent des contributions."""

    version = API_VERSION

    def __init__(self, registry: Registry, info: PluginInfo):
        self._r = registry
        self.info = info

    # --- process -----------------------------------------------------------
    def add_recipes(self, recipes, *, material: bool = False) -> None:
        """Process de la bibliothèque d'usine : préréglages, ou process par
        matière (`material`). `Recipe` ou dictionnaires (`recipe_to_dict`).
        Les préréglages d'un plugin **remplacent** ceux, neutres, du cœur."""
        from .model import Recipe, recipe_from_dict
        out = [r if isinstance(r, Recipe) else recipe_from_dict(dict(r))
               for r in recipes]
        (self._r.material_recipes if material else self._r.recipes).extend(out)

    def set_recipe_defaults(self, **values) -> None:
        """Valeurs d'une process neuve, et des champs absents d'un fichier
        (`model.default_recipe`). Un champ inconnu est refusé."""
        import dataclasses
        from .model import Recipe
        connus = {f.name for f in dataclasses.fields(Recipe)}
        inconnus = set(values) - connus
        if inconnus:
            raise ValueError('champs de process inconnus : '
                             + ', '.join(sorted(inconnus)))
        self._r.recipe_defaults.update(values)

    # --- données livrées -----------------------------------------------------
    def set_seed_dir(self, path) -> None:
        """Dossier de la semence (recettes.json, montages.json,
        reglages.json), posée au premier lancement — voir `semence`."""
        self._r.seed_dir = pathlib.Path(path)

    def set_tool_store(self, path) -> None:
        """Magasin d'outils extrait de la machine (outils.json), lu quand le
        `dbpunte.mag` de la machine ne répond pas."""
        self._r.tool_store = pathlib.Path(path)

    def add_couples(self, couples) -> None:
        """Couples d'atelier : `couples.Couple`, ou (fréquence kHz,
        impulsion ns, nom). Réservés au mode expert."""
        from .couples import Couple
        for c in couples:
            if not isinstance(c, Couple):
                f, p, nom = (tuple(c) + ('',))[:3]
                c = Couple(float(f), int(p), 'atelier', str(nom))
            self._r.couples.append(c)

    def set_drawings_dir(self, path) -> None:
        """Dossier des dessins livrés (bibliothèque de dessins)."""
        self._r.drawings_dir = pathlib.Path(path)

    def set_montage(self, gabarit: dict) -> None:
        """Gabarit de montage livré : celui du montage en service à
        l'atelier. Il remplace l'exemple du cœur partout où le cœur s'en
        sert — repli sans `montages.json`, valeurs d'un gabarit écrit à
        la main, référence proposée à la pose."""
        import copy
        if not isinstance(gabarit, dict) or not gabarit.get('nom'):
            raise ValueError('un gabarit de montage est un objet avec un nom')
        self._r.montage = copy.deepcopy(gabarit)

    # --- présentation et contrôles ------------------------------------------
    def set_machine(self, label: str) -> None:
        """Nom de la machine de l'atelier, dit dans *À propos*."""
        self._r.machine = str(label)

    def add_about(self, line: str) -> None:
        self._r.about.append(str(line))

    def add_autotest(self, name: str, fn: Callable) -> None:
        """Contrôle de l'autotest (grappe `plugins`) : `fn(check)`, où
        `check(libellé, réussi, détail='')` note un résultat."""
        self._r.autotests.append((f'{self.info.name} : {name}', fn))


def app_dir() -> pathlib.Path:
    """Dossier de l'exécutable (version figée) ou racine du dépôt."""
    if getattr(sys, 'frozen', False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parents[2]


def user_dir() -> pathlib.Path:
    """`%LOCALAPPDATA%/TauDrive/plugins` : les plugins du poste."""
    base = os.environ.get('LOCALAPPDATA') or str(
        pathlib.Path.home() / 'AppData' / 'Local')
    return pathlib.Path(base) / 'TauDrive' / 'plugins'


def search_dirs() -> list[pathlib.Path]:
    out = [app_dir() / 'plugins', user_dir()]
    for p in (os.environ.get(ENV_PATHS) or '').split(os.pathsep):
        if p.strip():
            out.append(pathlib.Path(p.strip()))
    return out


def _candidates(d: pathlib.Path) -> list[tuple[pathlib.Path, str]]:
    """(dossier à mettre dans sys.path, nom du module) des plugins d'un
    dossier : `d` lui-même s'il est un paquet, sinon ses sous-paquets."""
    try:
        if not d.is_dir():
            return []
        if (d / '__init__.py').is_file():
            return [(d.parent, d.name)]
        return [(d, c.name) for c in sorted(d.iterdir())
                if c.is_dir() and (c / '__init__.py').is_file()]
    except OSError:                                 # partage injoignable
        return []


def load(dirs: list | None = None, *, force: bool = False) -> list[PluginInfo]:
    """Charge les plugins (une fois). Rend la liste des plugins vus."""
    global _loaded
    if _loaded and not force:
        return REGISTRY.plugins
    _loaded = True
    if os.environ.get(ENV_OFF) == '1':
        return REGISTRY.plugins
    seen = {p.module for p in REGISTRY.plugins}
    for d in (dirs if dirs is not None else search_dirs()):
        for root, name in _candidates(pathlib.Path(d)):
            if name in seen:
                continue
            seen.add(name)
            REGISTRY.plugins.append(load_module(name, root))
    _apply()
    return REGISTRY.plugins


def load_module(name: str, root=None) -> PluginInfo:
    info = PluginInfo(module=name, path=str(root or ''))
    try:
        if root is not None and str(root) not in sys.path:
            sys.path.insert(0, str(root))
        mod = importlib.import_module(name)
        meta = getattr(mod, 'PLUGIN', {}) or {}
        info.name = str(meta.get('nom') or meta.get('name') or name)
        info.version = str(meta.get('version', ''))
        info.licence = str(meta.get('licence') or meta.get('license') or '')
        info.description = str(meta.get('description', ''))
        need = int(meta.get('api', API_VERSION))
        if need != API_VERSION:
            info.error = (f"API {need} demandée, TauDrive fournit "
                          f"l'API {API_VERSION}")
            return info
        reg = getattr(mod, 'register', None)
        if not callable(reg):
            info.error = 'pas de fonction register(api)'
            return info
        reg(Api(REGISTRY, info))
    except Exception as ex:                         # un plugin ne casse jamais le démarrage
        info.error = f'{type(ex).__name__} : {ex}'
        info.description = info.description or traceback.format_exc(limit=3)
    return info


def _apply() -> None:
    """La bibliothèque d'usine change avec les plugins : celle proposée
    avant tout chargement du poste la suit."""
    from . import model
    model.set_recipe_library([])


def about_lines() -> list[str]:
    """Ce que *À propos* dit des plugins."""
    out = [('Plugin ' + p.label()) for p in REGISTRY.plugins]
    return out + list(REGISTRY.about)


def reset() -> None:
    """Oublie les plugins chargés (autotest, tests)."""
    global _loaded
    REGISTRY.__init__()
    _loaded = False
    _apply()
