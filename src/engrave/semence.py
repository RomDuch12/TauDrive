"""Ce que la distribution apporte au premier lancement / shipped seed.

Un poste neuf ne doit pas démarrer vide. Les process de l'atelier, les
gabarits de montage et les modèles de traitement sont le fruit de mois
d'essais : les redemander à chaque installation reviendrait à les perdre.

**La semence ne remplace jamais.** Elle ne s'applique qu'à ce qui
n'existe pas encore sur le poste. Un opérateur qui a réglé sa
bibliothèque garde exactement ce qu'il a réglé — mettre à jour TauDrive
ne doit pas lui reprendre son travail.

    recettes.json    les process de production
    montages.json    les gabarits de montage
    reglages.json    modèles de traitement, préréglages

**Le cœur libre n'en livre aucune** : ce sont des données d'atelier. Le
plugin de l'atelier en donne le dossier (`plugins.Api.set_seed_dir`) ;
sans lui, `ressources/semence`, absent de la distribution libre.

Ces fichiers sont **relevés sur le poste de production**, par
*Paramètres ▸ Exporter les réglages*, puis rangés dans le plugin. Les chemins
propres à ce poste — dossiers récents, emplacement de la bibliothèque —
en sont volontairement absents : ils ne veulent rien dire ailleurs.

`exports/preflight` non plus. Le poste de production l'a désactivé, et
c'est son droit ; le livrer désactivé le retirerait à tous les postes
neufs, qui ne l'auraient jamais choisi.
"""
from __future__ import annotations

import json
import pathlib

from .avale import avale

#: Dossier de la semence, dans les ressources livrées.
DOSSIER = 'semence'

#: Ce qu'on sème, et où.
MEMBRES = ('recettes.json', 'montages.json', 'reglages.json')


def dossier() -> pathlib.Path:
    """Dossier de la semence : celui du plugin de l'atelier s'il en donne un."""
    from .plugins import REGISTRY
    if REGISTRY.seed_dir is not None:
        return REGISTRY.seed_dir
    from .app import resource_dir
    return resource_dir() / DOSSIER


def _lire(nom: str):
    chemin = dossier() / nom
    try:
        return json.loads(chemin.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        if chemin.exists():
            avale(f'semence : {nom} illisible', exc)
        return None


def semer(reglages_store=None) -> dict:
    """Pose ce qui manque. Rend le compte de ce qui a été posé.

    Appelé au démarrage. Ne lève jamais : un poste dont la semence est
    absente ou abîmée doit démarrer quand même, simplement vide.

    `reglages_store` reçoit un `QSettings` de remplacement. Sans lui, on
    écrit dans celui de l'atelier — et `session.settings()` porte des
    noms **constants**, indépendants de l'identité Qt du processus : un
    autotest qui appellerait `semer()` sans ce paramètre écrirait donc
    dans les réglages réels du poste.
    """
    from . import gabarits, recipes, session

    compte = {'process': 0, 'gabarits': 0, 'reglages': 0}

    # --- les process ---------------------------------------------------
    #
    # `library_path()` rend le fichier canonique **ou** un ancien nom
    # trouvé : on interroge son existence, pas un nom figé, sinon on
    # sèmerait par-dessus une bibliothèque rangée sous son ancien nom.
    try:
        deja = recipes.library_path().exists()
    except Exception as exc:                           # noqa: BLE001
        avale('semence : bibliothèque introuvable', exc)
        deja = True
    if not deja:
        brut = _lire('recettes.json')
        venues = [recipes.recipe_from_dict(r)
                  for r in (brut or {}).get('recipes', [])
                  if isinstance(r, dict)]
        if venues:
            try:
                recipes.save_local(venues)
                compte['process'] = len(venues)
            except OSError as exc:
                avale('semence : process non posées', exc)

    # --- les gabarits de montage ---------------------------------------
    if not gabarits.chemin().exists():
        brut = _lire('montages.json')
        venus = [g for g in (brut or {}).get('montages', [])
                 if isinstance(g, dict)]
        if venus:
            try:
                gabarits.enregistrer(venus)
                compte['gabarits'] = len(venus)
            except (OSError, ValueError) as exc:
                avale('semence : gabarits non posés', exc)

    # --- les réglages qui sont des cotes d'atelier ----------------------
    #
    # Un par un, et **seulement s'il manque** : un réglage déjà posé
    # appartient à qui l'a posé.
    brut = _lire('reglages.json')
    reglages = (brut or {}).get('reglages', {})
    if reglages:
        s = reglages_store if reglages_store is not None else session.settings()
        for cle, valeur in reglages.items():
            if s.value(cle) is None:
                s.setValue(cle, valeur)
                compte['reglages'] += 1
        s.sync()

    return compte


def resume() -> str:
    """Ce que la semence contient, pour l'aide et l'autotest."""
    bouts = []
    for nom in MEMBRES:
        brut = _lire(nom)
        if not isinstance(brut, dict):
            continue
        for cle in ('recipes', 'montages', 'reglages'):
            if cle in brut:
                bouts.append(f'{len(brut[cle])} {cle}')
    return ' · '.join(bouts) or 'aucune semence livrée'
