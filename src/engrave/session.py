"""Mémoire de session / Session memory.

Ce que TauDrive retient d'un lancement à l'autre :

* les **documents récents**, et ceux qui étaient ouverts à la fermeture —
  la session est rouverte telle qu'on l'a laissée ;
* les **dossiers d'export**, plusieurs, avec celui utilisé en dernier en
  tête : un atelier n'exporte pas tout au même endroit ;
* la géométrie de la fenêtre et la disposition des panneaux.

Tout passe par `QSettings`, donc par la base de registre sous Windows :
aucun fichier de configuration à gérer, et un poste réinstallé repart
proprement.
"""
from __future__ import annotations

import concurrent.futures
import pathlib
import uuid

from PySide6.QtCore import QSettings

ORG_NAME = 'Cielle'
APP_NAME = 'TauDrive'

#: Nombre maximum d'entrées conservées dans chaque liste.
MAX_RECENT = 12


#: Bac isolé, quand l'autotest tourne — `None` en usage normal.
#:
#: L'autotest exerce la vraie fenêtre : il ouvre des onglets, en ferme,
#: enregistre la session. Tout cela partait **dans les réglages du
#: poste**, l'identité Qt changée n'y faisant rien puisque `settings`
#: emploie un nom fixe. Trois dégâts, constatés :
#:
#: * l'index des onglets fermés de l'opérateur était **vidé** à chaque
#:   passage (`forget_closed`) — les fichiers restaient, la liste pour
#:   les retrouver non ;
#: * les onglets d'essai s'archivaient parmi les vrais ;
#: * l'instantané de session grossissait d'un passage à l'autre — chaque
#:   autotest rouvrait les onglets du précédent, en ajoutait, et
#:   enregistrait le tout : 1 307 documents et 801 Mo, et neuf minutes
#:   au lieu de deux.
#:
#: Isolé, tout part dans un dossier temporaire : réglages, instantané,
#: archive. Le poste n'est pas touché, et chaque passage repart de zéro.
_BAC: pathlib.Path | None = None


def isolate(dossier) -> pathlib.Path:
    """Range réglages, session et archive dans `dossier`. Pour l'autotest."""
    global _BAC
    _BAC = pathlib.Path(dossier)
    _BAC.mkdir(parents=True, exist_ok=True)
    return _BAC


def isolated() -> bool:
    return _BAC is not None


def settings() -> QSettings:
    if _BAC is not None:
        return QSettings(str(_BAC / 'reglages.ini'), QSettings.IniFormat)
    return QSettings(ORG_NAME, APP_NAME)


# --- accessibilité des chemins ---------------------------------------------
#
# Interroger un chemin réseau injoignable **bloque** : Windows attend
# l'expiration du délai SMB, une vingtaine de secondes, et l'appelant avec
# lui. Fait dans le constructeur de la fenêtre — ce qui était le cas — cela
# empêchait purement et simplement l'application de démarrer dès que le
# poste était débranché du réseau.
#
# Toute question posée au système de fichiers passe donc désormais par ici :
# la sonde tourne dans un fil de discussion à part, avec un délai court, et
# son résultat est mémorisé **pour un temps**.
#
# Pour un temps, et non pour la session : un réseau qui tarde une fois
# n'est pas un réseau absent. Le résultat était retenu jusqu'à la
# fermeture, si bien qu'un partage lent au démarrage restait déclaré
# injoignable tout l'après-midi, et refusait l'export alors qu'on y
# écrivait parfaitement depuis l'explorateur. Un constat **négatif**
# expire donc vite, un constat positif tient plus longtemps — c'est
# l'asymétrie du cas réel : le partage revient, il ne s'en va presque
# jamais en cours de travail.

#: Délai laissé à un chemin pour répondre, en secondes.
PROBE_TIMEOUT = 0.6

#: Durée de validité d'un constat, en secondes. Un refus se reteste vite.
CACHE_OK_S = 30.0
CACHE_KO_S = 3.0

#: Chemin -> (joignable, instant du constat).
_REACHABLE: dict[str, tuple[bool, float]] = {}
_PROBES: concurrent.futures.ThreadPoolExecutor | None = None


def _pool() -> concurrent.futures.ThreadPoolExecutor:
    global _PROBES
    if _PROBES is None:
        _PROBES = concurrent.futures.ThreadPoolExecutor(
            max_workers=8, thread_name_prefix='acces-chemin')
    return _PROBES


def reachable(path: str, timeout: float = PROBE_TIMEOUT,
              fresh: bool = False) -> bool:
    """Vrai si le chemin **existe** et répond dans le délai imparti.

    Un chemin qui ne répond pas n'est **pas** effacé de l'historique : il
    est seulement porté absent, et pour quelques secondes seulement. Le
    partage reviendra, et l'entrée avec lui.

    `fresh` refait la sonde sans regarder ce qui a été constaté : c'est
    ce que fait un bouton « Réessayer ».

    Attention : un dossier d'export qui n'existe **pas encore** est
    parfaitement utilisable — il sera créé. Pour cette question-là, c'est
    `writable` qu'il faut, pas celle-ci.
    """
    import time
    path = str(path or '')
    if not path:
        return False
    known = _REACHABLE.get(path)
    if known is not None and not fresh:
        answer, quand = known
        if time.monotonic() - quand < (CACHE_OK_S if answer else CACHE_KO_S):
            return answer
    try:
        answer = bool(_pool().submit(
            lambda: pathlib.Path(path).exists()).result(timeout))
    except Exception:
        # délai dépassé, chemin refusé, lecteur absent : injoignable
        answer = False
    _REACHABLE[path] = (answer, time.monotonic())
    return answer


def writable(path: str, timeout: float = PROBE_TIMEOUT,
             fresh: bool = False) -> bool:
    """Vrai si l'on peut **écrire** là — le dossier existe, ou son parent.

    Un dossier d'export n'a aucune raison d'exister avant le premier
    export : `D:/Gravures/2026` est créé à la volée, sous-dossiers
    compris. Le refuser parce qu'il n'existe pas encore était un faux
    barrage — et c'est ce qui se produisait, alors qu'on écrivait dans
    ce même sous-dossier sans la moindre difficulté depuis l'explorateur.

    On remonte donc jusqu'au premier ancêtre qui répond : s'il est là,
    le reste se crée. La remontée est bornée — un chemin réseau mort
    répondrait autant de fois qu'il a de niveaux.
    """
    path = str(path or '').strip()
    if not path:
        return False
    if reachable(path, timeout, fresh):
        return True
    depart = pathlib.Path(path)
    vus = 0
    parent = depart.parent
    while parent != depart and vus < 4:
        if reachable(str(parent), timeout, fresh):
            return True
        depart, parent, vus = parent, parent.parent, vus + 1
    return False


# --- barre d'outils --------------------------------------------------------

def toolbar_labels() -> bool:
    """Vrai si les libellés paraissent sous les icônes de la barre."""
    return str(settings().value('window/toolbar_labels', 'false')).lower() \
        in ('true', '1', 'yes')


def set_toolbar_labels(on: bool) -> None:
    settings().setValue('window/toolbar_labels', bool(on))


# --- hauteur des champs de saisie ------------------------------------------

#: Hauteur par défaut d'un champ de saisie étirable, en pixels. Six
#: lignes : un texte de plaque en tient une, une mention légale douze, et
#: c'est la seconde qu'on relit mal dans un champ trop court.
FIELD_HEIGHT = 150


def field_height(cle: str, defaut: int = FIELD_HEIGHT) -> int:
    """Hauteur retenue pour ce champ, en pixels."""
    try:
        return max(40, min(int(settings().value(f'champs/{cle}', defaut)),
                           900))
    except (TypeError, ValueError):
        return defaut


def remember_field_height(cle: str, hauteur: int) -> None:
    if cle:
        settings().setValue(f'champs/{cle}', int(hauteur))


def forget_reachability() -> None:
    """Oublie ce qui a été constaté : à appeler après un retour du réseau."""
    _REACHABLE.clear()


def sort_by_reach(paths: list[str]) -> tuple[list[str], list[str]]:
    """Sépare les chemins joignables de ceux qui ne répondent pas."""
    joignables, absents = [], []
    for path in paths:
        (joignables if reachable(path) else absents).append(path)
    return joignables, absents


def _list(key: str) -> list[str]:
    raw = settings().value(key) or []
    if isinstance(raw, str):           # QSettings réduit une liste d'un seul
        raw = [raw]                    # élément à une chaîne
    return [str(x) for x in raw if str(x)]


def _push(key: str, value: str) -> list[str]:
    """Place `value` en tête de la liste, sans doublon, et l'écrit.

    Aucune entrée n'est écartée parce qu'elle ne répond pas : un partage
    hors ligne reviendra, et l'historique doit l'attendre.
    """
    value = str(value)
    kept = [v for v in _list(key) if v != value]
    kept.insert(0, value)
    settings().setValue(key, kept[:MAX_RECENT])
    return kept[:MAX_RECENT]


# --- documents -------------------------------------------------------------

def recent_documents() -> list[str]:
    """Documents récents, joignables ou non — l'historique est conservé."""
    return _list('recent/documents')


def remember_document(path: str) -> None:
    _push('recent/documents', path)


def forget_documents() -> None:
    settings().remove('recent/documents')


def open_documents() -> list[str]:
    """Documents ouverts lors de la dernière fermeture."""
    return _list('session/open')


def remember_open(paths: list[str]) -> None:
    settings().setValue('session/open', [p for p in paths if p])


# --- dossiers d'export -----------------------------------------------------

def export_folders() -> list[str]:
    """Dossiers d'export mémorisés, joignables ou non."""
    return _list('recent/exports')


def remember_export(folder: str) -> None:
    _push('recent/exports', folder)


def last_export() -> str:
    folders = export_folders()
    return folders[0] if folders else str(pathlib.Path.home())


def machine_view(folder: str) -> str:
    """Chemin sous lequel la **machine** voit ce dossier d'export.

    Vide dans le cas normal : la machine lit le partage par le même chemin
    que le poste client, et le CLJOB peut désigner les fichiers là où ils
    sont. On ne renseigne ceci que si le poste machine emploie un lecteur
    mappé là où le client emploie un chemin UNC.

    Mémorisé **par dossier** : un atelier peut exporter vers deux partages
    dont un seul est mappé.
    """
    mapping = settings().value('exports/machine_view') or {}
    if not isinstance(mapping, dict):
        return ''
    return str(mapping.get(folder, '') or '')


def set_machine_view(folder: str, machine_path: str) -> None:
    mapping = settings().value('exports/machine_view') or {}
    if not isinstance(mapping, dict):
        mapping = {}
    if machine_path.strip():
        mapping[folder] = machine_path.strip()
    else:
        mapping.pop(folder, None)
    settings().setValue('exports/machine_view', mapping)


# --- fenêtre ---------------------------------------------------------------

def save_window(window) -> None:
    s = settings()
    s.setValue('window/geometry', window.saveGeometry())
    s.setValue('window/state', window.saveState())


def restore_window(window) -> None:
    """Restaure la fenêtre, en refusant une géométrie devenue inutilisable.

    Un poste peut avoir changé d'écran depuis la dernière fois : restaurer
    telle quelle une fenêtre placée sur un second moniteur absent la rend
    invisible, sans aucun moyen de la récupérer.
    """
    s = settings()
    geometry = s.value('window/geometry')
    if geometry is not None:
        window.restoreGeometry(geometry)
        if not _on_screen(window):
            window.resize(1280, 820)
            window.move(60, 40)
    state = s.value('window/state')
    if state is not None:
        window.restoreState(state)


def _on_screen(window) -> bool:
    from PySide6.QtGui import QGuiApplication
    frame = window.frameGeometry()
    return any(screen.availableGeometry().intersects(frame)
               for screen in QGuiApplication.screens())


# --- dossiers par défaut ---------------------------------------------------
#
# Un atelier range ses fichiers toujours au même endroit. Redemander le
# chemin à chaque ouverture ou à chaque import est une perte de temps, et
# une source d'erreur quand un opérateur enregistre au mauvais endroit.

#: Emplacements paramétrables, avec leur libellé et leur usage.
FOLDER_KINDS = (
    ('documents', 'Documents TauDrive',
     'Ouverture et enregistrement des documents .taudrive'),
    ('export', 'Export ISO / CLJOB',
     'Destination proposée à l\'export — un partage réseau convient'),
    ('dxf', 'Import DXF', 'Dossier proposé à l\'import de dessins'),
    ('bibliotheque', 'Bibliothèque de dessins',
     'Dessins du poste, ajoutables et effaçables — pointé sur un partage '
     'réseau, c\'est la bibliothèque de l\'atelier'),
    ('archive', 'Archive des onglets fermés',
     'Onglets fermés, rangés par semaine (26s34). Rien n\' est jamais '
     'effacé automatiquement'),
)


def default_folder(kind: str) -> str:
    """Dossier par défaut pour cet usage, ou une chaîne vide."""
    value = settings().value(f'folders/{kind}') or ''
    return str(value)


def set_default_folder(kind: str, path: str) -> None:
    settings().setValue(f'folders/{kind}', path.strip())


#: Usages de sélecteur de fichiers, chacun avec sa mémoire.
#:
#: **Un usage, un dossier.** Exporter un DXF, enregistrer un document et
#: sauvegarder les réglages ne se font pas au même endroit : les faire
#: partager une seule mémoire ramenait le sélecteur là où l\'on était
#: allé pour tout autre chose.
#:
#: Les usages *de politique* — dossier d\'export machine,
#: bibliothèque, archives — sont réglés une fois dans
#: *Paramètres ▸ Dossiers* et n\'ont pas à suivre les allées et
#: venues : voir `POLICY_KINDS`.
BROWSE_KINDS = (
    ('documents', 'Ouvrir un document'),
    ('enregistrer', 'Enregistrer un document'),
    ('dxf', 'Importer un dessin'),
    ('export_vectoriel', 'Exporter le dessin (DXF, EPS, AI)'),
    ('reglages', 'Import et export des réglages'),
)

#: Usages dont le **réglage explicite l\'emporte** sur le dernier
#: emplacement employé : ce sont des décisions d\'atelier, pas des
#: habitudes de navigation.
POLICY_KINDS = ('export', 'bibliotheque', 'archive')


def last_folder(kind: str) -> str:
    """Dernier dossier employé pour cet usage, ou une chaîne vide."""
    recents = _list(f'recent/folders/{kind}')
    return recents[0] if recents else ''


def start_folder(kind: str, fallback: str = '') -> str:
    """Dossier où ouvrir un sélecteur de fichiers.

    **Le dernier emplacement employé l\'emporte**, pour tout ce qui
    relève de la navigation : ouvrir, enregistrer, importer, exporter. On
    revient là où l\'on était, ce qui est la seule chose qu\'on
    attend d\'un sélecteur de fichiers.

    Le réglage de *Paramètres ▸ Dossiers* sert alors de **point de
    départ** — il vaut au premier usage, et chaque fois que le dernier
    emplacement ne répond plus. Pour les usages de politique
    (`POLICY_KINDS`) l\'ordre s\'inverse : le réglage l\'emporte,
    car c\'est une décision d\'atelier et non une habitude.

    Un dossier qui ne répond pas — partage débranché — est sauté sans
    être oublié : il reviendra avec le réseau.
    """
    regle = default_folder(kind)
    dernier = last_folder(kind)

    ordre = ((regle, dernier) if kind in POLICY_KINDS
             else (dernier, regle))
    for candidat in ordre:
        if candidat and reachable(candidat):
            return candidat
    if fallback and reachable(fallback):
        return fallback
    return str(pathlib.Path.home())


def remember_file(kind: str, path: str) -> None:
    """Retient le dossier **du fichier** qu\'on vient de désigner.

    Le raccourci qui manquait : chaque sélecteur rendait un chemin de
    fichier, et chaque appelant en tirait le dossier à la main — quand il
    y pensait. La moitié ne le faisait pas.
    """
    if not path:
        return
    dossier = pathlib.Path(path)
    remember_folder(kind, str(dossier if dossier.is_dir()
                              else dossier.parent))


# --- sauvegarde silencieuse ------------------------------------------------
#
# L'application n'a pas à demander « voulez-vous enregistrer ? » à chaque
# fermeture. Ce qui est ouvert est réécrit en continu dans un instantané
# de session, et rouvert tel quel au lancement suivant — y compris les
# documents qui n'ont pas encore de fichier. Un enregistrement explicite
# reste nécessaire pour produire un `.taudrive` partageable, mais plus
# pour ne rien perdre.

def session_file() -> pathlib.Path:
    if _BAC is not None:
        return _BAC / 'session.json'
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(
        QStandardPaths.AppDataLocation) or str(pathlib.Path.home())
    return pathlib.Path(base) / 'session.json'


def save_snapshot(entries: list[dict]) -> None:
    """Écrit l'instantané de session. Silencieux, y compris en cas d'échec.

    Une écriture par fichier temporaire puis remplacement : une coupure
    pendant l'écriture laisse l'instantané précédent intact plutôt qu'un
    fichier tronqué, qui coûterait tout le travail en cours.
    """
    path = session_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(snapshot_text(entries), encoding='utf-8')
        tmp.replace(path)
    except OSError:
        pass


#: Texte JSON des formes déjà écrites, par identifiant : la forme telle
#: qu'écrite, son texte, et celui de ses polylignes — voir `snapshot_text`.
_FRAGMENTS: dict[str, tuple] = {}

#: Valeur provisoire, remplacée dans le texte par un fragment déjà écrit.
_TROU = f'\x00{uuid.uuid4().hex}\x00'


def snapshot_text(entries: list[dict]) -> str:
    """Le texte de l'instantané : `json.dumps({'documents': entries})`,
    caractère pour caractère — mais **sans réécrire** ce qui n'a pas
    changé depuis le précédent.

    L'instantané se réécrit 2,5 s après chaque retouche, tous onglets
    compris : avec un DXF de 400 000 points ouvert, chaque retouche
    figeait la fenêtre près d'une seconde, le temps de remettre en texte
    un dessin qui n'avait pas bougé. Une forme inchangée reprend son
    texte ; une forme déplacée ou réglée, celui de ses polylignes.
    """
    import json
    neufs: dict[str, tuple] = {}

    def texte(valeur) -> str:
        return json.dumps(valeur, ensure_ascii=False)
    trou = texte(_TROU)

    def forme(f) -> str:
        cle = f.get('id') if isinstance(f, dict) else None
        if not isinstance(cle, str):
            return texte(f)
        ancien = _FRAGMENTS.get(cle)
        if ancien is not None and ancien[0] == f:
            neufs[cle] = ancien
            return ancien[1]
        trace = f.get('polylines')
        if isinstance(trace, list) and trace:
            if ancien is not None and ancien[2] is not None \
                    and ancien[2][0] == trace:
                memo = ancien[2]
            else:
                memo = (trace, texte(trace))
            ecrit = texte({**f, 'polylines': _TROU}).replace(trou, memo[1], 1)
        else:
            memo, ecrit = None, texte(f)
        neufs[cle] = (f, ecrit, memo)
        return ecrit

    def document(d) -> str:
        formes = d.get('shapes') if isinstance(d, dict) else None
        if not isinstance(formes, list):
            return texte(d)
        return texte({**d, 'shapes': _TROU}).replace(
            trou, '[' + ', '.join(forme(f) for f in formes) + ']', 1)

    def entree(e) -> str:
        if not isinstance(e, dict) or 'document' not in e:
            return texte(e)
        return texte({**e, 'document': _TROU}).replace(
            trou, document(e['document']), 1)

    sortie = ('{"documents": [' + ', '.join(entree(e) for e in entries)
              + ']}')
    _FRAGMENTS.clear()
    _FRAGMENTS.update(neufs)
    return sortie


def load_snapshot() -> list[dict]:
    """Instantané de la dernière session, ou une liste vide."""
    import json
    path = session_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    entries = data.get('documents') if isinstance(data, dict) else None
    return [e for e in entries or [] if isinstance(e, dict)]


def clear_snapshot() -> None:
    try:
        session_file().unlink(missing_ok=True)
    except OSError:
        pass


# --- dernière plaque codée -------------------------------------------------
#
# Les cotes d'une plaque ne changent pas d'une pièce à l'autre : c'est le
# même cadre, le même emplacement, la même symbologie. Les redemander à
# chaque pose serait une corvée — et une occasion de se tromper.

#: Cotes de départ, reprises de la plaque de production.
_CODE_FALLBACK = {
    'frame': (0.0, 0.0, 15.0, 7.0),
    # centre du texte à -15,07 / -3,73 du centre du code : la disposition
    # des plaques déjà en service
    'text_frame': (-15.07, -3.73, 8.071, 1.538),
    'data': 'B{n:06}',
    'kind': 'datamatrix',
    'dm_shape': 'auto',
    # cadre englobant : 'auto' le décide selon la symbologie, sinon
    # 'rect', 'circle' ou 'none' — le dernier choix de l'atelier
    'code_frame': 'auto',
    'frame_margin': 0.5,
    # le texte, **relativement au centre du code** : centre et fenêtre.
    # Absent des réglages d'avant ; il s'en déduit alors — voir
    # `code_defaults` — pour que la première plaque tombe au même endroit.
    'text_offset': (-15.07, -3.73, 8.071, 1.538),
}

#: Cadres admis pour une plaque.
CODE_FRAMES = ('auto', 'rect', 'circle', 'none')


def code_defaults() -> dict:
    """Réglages de la dernière plaque posée, complétés par les valeurs
    d'usine. Les clés absentes ou corrompues sont remplacées une à une."""
    import math
    from .model import LONGUEUR_MAX_MM
    stored = settings().value('code/defaults') or {}
    if not isinstance(stored, dict):
        stored = {}

    # Une cote infinie, NaN ou démesurée — réglages abîmés, archive
    # retouchée — passait telle quelle à la plaque posée : une marge de
    # 10⁶ mm figeait le calcul des trajectoires, une infinie le faisait
    # tomber. Comme dans un document : finie, bornée à `LONGUEUR_MAX_MM`.
    def cote(v) -> bool:
        return math.isfinite(v) and abs(v) <= LONGUEUR_MAX_MM

    out = dict(_CODE_FALLBACK)
    for key, fallback in _CODE_FALLBACK.items():
        value = stored.get(key)
        if isinstance(fallback, tuple):
            try:
                numbers = tuple(float(v) for v in value)
            except (TypeError, ValueError, OverflowError):
                continue
            if len(numbers) == len(fallback) and all(map(cote, numbers)):
                out[key] = numbers
        elif isinstance(fallback, float):
            try:
                number = max(0.0, float(value))
            except (TypeError, ValueError, OverflowError):
                continue
            if cote(number):
                out[key] = number
        elif isinstance(value, str) and value:
            out[key] = value
    if out['code_frame'] not in CODE_FRAMES:
        out['code_frame'] = 'auto'
    # Une symbologie ou une forme inconnue — réglages abîmés, ou écrits par
    # une version plus récente — se posait telle quelle sur la plaque
    # suivante, et le document ne se rouvrait plus.
    from .model import CHOIX, lire_symbologie
    out['kind'] = lire_symbologie(stored, _CODE_FALLBACK['kind'])
    if out['dm_shape'] not in CHOIX['dm_shape']:
        out['dm_shape'] = _CODE_FALLBACK['dm_shape']
    if 'text_offset' not in stored:
        # Réglages écrits avant : le texte était retenu en position
        # **absolue**. On en tire l'écart au code, de sorte que la
        # prochaine plaque, posée au cadre retenu, ait son texte
        # exactement là où l'ancienne version l'aurait mis.
        fx, fy = out['frame'][0], out['frame'][1]
        tx, ty, tw, th = out['text_frame']
        out['text_offset'] = (tx - fx, ty - fy, tw, th)
    return out


def remember_code(frame=None, text_frame=None, data: str = '',
                  kind: str = '', dm_shape: str = '', code_frame: str = '',
                  frame_margin: float | None = None,
                  text_offset=None) -> None:
    """Retient ce qui vient d'être posé, champ par champ."""
    current = code_defaults()
    if code_frame in CODE_FRAMES:
        current['code_frame'] = code_frame
    if frame_margin is not None:
        current['frame_margin'] = max(0.0, float(frame_margin))
    if text_offset:
        current['text_offset'] = tuple(float(v) for v in text_offset)
    if frame:
        current['frame'] = tuple(float(v) for v in frame)
    if text_frame:
        current['text_frame'] = tuple(float(v) for v in text_frame)
    if data:
        current['data'] = data
    if kind:
        current['kind'] = kind
    if dm_shape:
        current['dm_shape'] = dm_shape
    ecrit = {k: (list(v) if isinstance(v, tuple) else v)
             for k, v in current.items()}
    # Une autre version installée sur ce poste relit ces réglages : une
    # symbologie qu'elle ignore va à part, `kind` garde la dernière
    # qu'elle connaît — voir `model.ecrire_symbologie`.
    from .model import ecrire_symbologie
    avant = settings().value('code/defaults')
    ancien = avant.get('kind') if isinstance(avant, dict) else None
    if isinstance(ancien, str):
        ecrit['kind'] = ancien
    else:
        ecrit.pop('kind', None)
    ecrire_symbologie(ecrit, current['kind'])
    settings().setValue('code/defaults', ecrit)


# --- chemins récents, tous usages ------------------------------------------

def remember_folder(kind: str, folder: str) -> None:
    """Retient un dossier employé pour cet usage."""
    if folder:
        _push(f'recent/folders/{kind}', folder)


def recent_folders(kind: str) -> list[str]:
    """Dossiers récemment employés pour cet usage, joignables ou non."""
    seen = _list(f'recent/folders/{kind}')
    if kind == 'export':
        # les dossiers d'export ont leur propre liste, tenue à jour par
        # l'export lui-même : les deux se complètent
        for folder in export_folders():
            if folder not in seen:
                seen.append(folder)
    chosen = default_folder(kind)
    if chosen and chosen not in seen:
        seen.insert(0, chosen)
    return seen[:MAX_RECENT]


# --- chemin vu par la machine ----------------------------------------------
#
# Le poste machine et les postes clients désignent le même dossier par des
# chemins différents : `C:\TauDrive` sur la machine, `\poste\TauDrive`
# depuis le réseau. Le CLJOB doit porter **le chemin de la machine**, seul
# valable à l'exécution.

#: Modèle par défaut du chemin vu par la machine.
MACHINE_TEMPLATE = r'C:\TauDrive\{date} {job}'

#: Champs acceptés dans le modèle, avec leur description.
TEMPLATE_FIELDS = (
    ('{job}', 'nom de l\'onglet, assaini'),
    ('{date}', 'date du jour, aammjj'),
    ('{time}', 'heure, hhmmss'),
    ('{year}', 'année sur quatre chiffres'),
)


def machine_template() -> str:
    value = settings().value('exports/machine_template')
    return str(value) if value else MACHINE_TEMPLATE


def set_machine_template(template: str) -> None:
    settings().setValue('exports/machine_template',
                        template.strip() or MACHINE_TEMPLATE)


# --- exports répétés depuis le même onglet ---------------------------------
#
# Un même travail s'exporte souvent plusieurs fois : une correction, un
# essai, une seconde matière. Le modèle de chemin donnant le même nom de
# dossier, le second export écrasait le premier — y compris des fichiers
# déjà copiés sur la machine, sans moyen de savoir lequel gravait.

#: Façons de distinguer deux exports du même travail.
EXPORT_NAMING = (
    ('auto', 'Numéroter automatiquement',
     'Le dossier reçoit un rang : « … », « …-02 », « …-03 ». Aucun '
     'écrasement, aucune question.'),
    ('ask', 'Demander un nom à chaque fois',
     'Un nom est demandé à chaque export ; il complète le dossier. Utile '
     'quand chaque export a une raison d\'être différente.'),
    ('overwrite', 'Écraser le dossier existant',
     'L\'ancien export est remplacé. À ne choisir que si les fichiers ne '
     'sont jamais copiés ailleurs.'),
)


def export_naming() -> str:
    value = settings().value('exports/naming')
    known = {k for k, _, _ in EXPORT_NAMING}
    return str(value) if value in known else 'auto'


def set_export_naming(mode: str) -> None:
    settings().setValue('exports/naming', mode)


# --- vérification avant export ---------------------------------------------
#
# Active par défaut : le récapitulatif ne coûte que le temps de le lire, et
# une plaque gâchée coûte davantage. Qui le trouve inutile le coupe ici ou
# depuis la case du dialogue lui-même.

def preflight() -> bool:
    value = settings().value('exports/preflight', True)
    return str(value).lower() not in ('false', '0')


def set_preflight(on: bool) -> None:
    settings().setValue('exports/preflight', bool(on))


def aimant() -> bool:
    """L'aimant du plan de travail — voir `aimant`. Actif d'office."""
    value = settings().value('plan/aimant', True)
    return str(value).lower() not in ('false', '0')


def set_aimant(on: bool) -> None:
    settings().setValue('plan/aimant', bool(on))


# --- réglages du coupon d'essai --------------------------------------------
#
# On rouvre le dialogue sur les réglages du dernier coupon : un essai se
# fait rarement en une fois. La deuxième plaque affine la première, et
# ressaisir six champs entre les deux fait perdre le fil.

_COUPON_FALLBACK = {
    'recipe': '',
    'x_field': 'power_percent', 'x_from': 20.0, 'x_to': 100.0, 'x_count': 5,
    'y_field': 'speed_mm_min', 'y_from': 40000.0, 'y_to': 200000.0,
    'y_count': 4,
    'cell_mm': 8.0, 'gap_mm': 3.0, 'label_mm': 1.8, 'hatched': True,
    'labels_hatched': False, 'show_title': True,
    'show_x_labels': True, 'show_y_labels': True,
    # couples fréquence-impulsion retenus sur chaque axe, en « 1300-2 »
    # séparés par des espaces : une chaîne se relit sans surprise là où
    # une liste se fait aplatir par QSettings quand elle n'a qu'un élément
    'x_couples': '', 'y_couples': '',
    # source de la géométrie des cases : '' = carré, sinon un DXF ou une
    # sélection mise en bibliothèque
    'source': '', 'source_path': '',
}


def coupon_defaults() -> dict:
    """Réglages du dernier coupon, complétés par les valeurs d'usine."""
    stored = settings().value('coupon/defaults') or {}
    if not isinstance(stored, dict):
        stored = {}
    out = dict(_COUPON_FALLBACK)
    for key, fallback in _COUPON_FALLBACK.items():
        value = stored.get(key)
        if value is None:
            continue
        try:
            if isinstance(fallback, bool):
                out[key] = str(value).lower() not in ('false', '0')
            elif isinstance(fallback, int):
                out[key] = int(value)
            elif isinstance(fallback, float):
                out[key] = float(value)
            else:
                out[key] = str(value)
        except (TypeError, ValueError):
            continue
    return out


def remember_coupon(**values) -> None:
    """Retient les réglages d'un coupon, clé par clé."""
    current = coupon_defaults()
    current.update({k: v for k, v in values.items()
                    if k in _COUPON_FALLBACK})
    settings().setValue('coupon/defaults', current)


# --- onglets fermés ---------------------------------------------------------
#
# Fermer un onglet ne demande rien : c'est voulu, et cela vaut mieux qu'une
# question à chaque fois. Encore faut-il pouvoir revenir sur un onglet fermé
# par mégarde, ou retrouver la plaque d'avant-hier dont on ne sait plus le
# nom exact.
#
# **Tout est gardé**, sans plafond, mais sur le disque et non dans la base
# de registre : un document pèse quelques kilo-octets, mille documents la
# feraient enfler pour rien. Les fichiers sont rangés par **semaine** —
# `26s34` pour la semaine 34 de 2026 — parce qu'un atelier se souvient
# d'une plaque par sa semaine bien avant de se souvenir de sa date.

#: Clé de l'index, et dossier d'archivage.
CLOSED_INDEX = 'session/closed'
CLOSED_FOLDER = 'folders/archive'


def archive_dir() -> pathlib.Path:
    """Dossier d'archivage des onglets fermés, réglable."""
    regle = str(settings().value(CLOSED_FOLDER) or '')
    if regle.strip():
        return pathlib.Path(regle)
    if _BAC is not None:
        return _BAC / 'Onglets fermes'
    return pathlib.Path.home() / 'TauDrive' / 'Onglets fermes'


def set_archive_dir(path: str) -> None:
    settings().setValue(CLOSED_FOLDER, (path or '').strip())


def week_folder(when=None) -> str:
    """Dossier de semaine : `26s34` pour la semaine 34 de 2026.

    Semaine **ISO** : celle que les plannings d'atelier emploient, et qui
    ne dépend pas du jour où commence la semaine sur le poste.
    """
    import datetime as _dt
    moment = when or _dt.datetime.now()
    annee, semaine, _ = moment.isocalendar()
    return f'{annee % 100:02d}s{semaine:02d}'


def closed_tabs() -> list[dict]:
    """Onglets fermés, le plus récent en tête. Tous, sans plafond."""
    brut = settings().value(CLOSED_INDEX) or []
    if not isinstance(brut, list):
        return []
    return [e for e in brut if isinstance(e, dict) and e.get('file')]


def remember_closed(name: str, document_json: str, path: str = '',
                    keywords: str = '') -> dict | None:
    """Archive un onglet fermé sur le disque, et l'indexe.

    Le contenu part dans un fichier ; l'index ne retient que de quoi le
    retrouver — nom, chemin d'origine, moment, et les **mots du dessin**
    (textes gravés, noms de formes) sur lesquels portera la recherche.
    """
    import datetime as _dt
    moment = _dt.datetime.now()
    dossier = archive_dir() / week_folder(moment)
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        cible = dossier / f'{_safe(name)}_{moment:%Y%m%d-%H%M%S}.taudrive'
        cible.write_text(document_json, encoding='utf-8')
    except OSError:
        return None
    entree = {
        'name': str(name or 'gravure'),
        'path': str(path or ''),
        'when': moment.strftime('%Y-%m-%d %H:%M'),
        'week': week_folder(moment),
        'file': str(cible),
        'keys': str(keywords or '')[:400],
    }
    liste = closed_tabs()
    liste.insert(0, entree)
    settings().setValue(CLOSED_INDEX, liste)
    return entree


def _safe(name: str) -> str:
    interdits = '\\/:*?"<>|'
    propre = ''.join('_' if c in interdits else c for c in (name or ''))
    return '_'.join(propre.split()).strip('._')[:48] or 'gravure'


def read_closed(entree: dict) -> str:
    """Contenu d'un onglet archivé, ou une chaîne vide s'il a disparu."""
    try:
        return pathlib.Path(entree.get('file', '')).read_text(encoding='utf-8')
    except OSError:
        return ''


def forget_closed() -> None:
    """Vide l'index. **Les fichiers archivés restent** sur le disque."""
    settings().remove(CLOSED_INDEX)


def closed_weeks() -> list[str]:
    """Semaines représentées dans l'archive, la plus récente en tête."""
    vues = []
    for e in closed_tabs():
        semaine = e.get('week', '')
        if semaine and semaine not in vues:
            vues.append(semaine)
    return vues


def search_closed(mot: str, week: str = '') -> list[dict]:
    """Onglets fermés contenant `mot` — nom, chemin, semaine ou contenu.

    Chercher dans le contenu n'est pas un luxe : on se souvient du texte
    gravé ou de la référence du client bien plus souvent que du nom qu'on
    avait donné à l'onglet.
    """
    entrees = closed_tabs()
    if week:
        entrees = [e for e in entrees if e.get('week') == week]
    mot = (mot or '').strip().lower()
    if not mot:
        return entrees
    return [e for e in entrees
            if mot in e.get('name', '').lower()
            or mot in e.get('path', '').lower()
            or mot in e.get('week', '').lower()
            or mot in e.get('keys', '').lower()]
