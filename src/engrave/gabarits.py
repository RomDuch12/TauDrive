"""Gabarits de montage / fixture templates.

Un montage machine porte plusieurs pièces à la fois, chacune recevant son
DataMatrix et sa référence en clair. **Ses cotes sont celles de la
mécanique** : elles ne se négocient pas, elles se reproduisent.

C'est précisément pourquoi elles ne doivent pas vivre dans le code. Le
jour où l'entraxe change — un montage refait, une pièce plus large — ce
doit être une valeur à corriger, pas un exécutable à reconstruire. Et le
jour où un deuxième montage arrive, ce doit être une entrée à ajouter,
pas un module à écrire.

Les gabarits vivent dans `montages.json`, à côté des process, et se
partagent par *Paramètres ▸ Exporter les réglages*.

**Positions et entraxe.** Un montage régulier se décrit par son entraxe
et son centre — c'est ainsi qu'on le lit sur un plan :

    "postes": ["HAUT", "MILIEU", "BAS"],
    "entraxe_mm": 23.0,
    "centre_y_mm": 0.2

Les trois ordonnées s'en déduisent : +23,2 / +0,2 / −22,8. Un montage
**irrégulier** donne ses positions une à une, et l'entraxe est alors
ignoré :

    "positions_y_mm": [23.2, 0.2, -22.8]

Les deux formes cohabitent : la première dit l'intention, la seconde
couvre ce qui n'a pas d'intention régulière.

**Ce qui peut s'ajouter**, et qu'une version antérieure ignore sans
dommage :

    "positions_x_mm": [0.0, 0.4, 0.0],
    "donnees": ["B000181", "", "B000190"]

Le premier donne l'abscisse de chaque poste quand elles diffèrent —
`x_mm` reste écrit, au milieu, pour la version d'avant. Le second est
le **formulaire proposé à la pose** : la référence que chaque poste
porte en arrivant ; vide, c'est `donnee`.

**Un montage posé se relit en gabarit** — voir `depuis_formes` : ce
qu'on a retouché sur le plan (cadre, marge, taille, positions, place du
texte) s'enregistre dans le gabarit et revient à la pose suivante.
"""
from __future__ import annotations

import copy
import json
import math
import pathlib
import shutil

#: Nom du fichier, à côté de `recettes.json`.
FICHIER = 'montages.json'

#: Le gabarit livré : le montage à trois DataMatrix en service, relevé
#: sur `Datamatrix.taudrive`. Sert de valeur de repli si le fichier
#: manque, et de modèle à qui veut en écrire un second.
LIVRE = {
    'nom': 'Montage 3 DataMatrix',
    'postes': ['HAUT', 'MILIEU', 'BAS'],
    'entraxe_mm': 23.0,
    'centre_y_mm': 0.2,
    'x_mm': 0.0,
    'donnee': 'B000181',
    'code': {
        'kind': 'datamatrix',
        'largeur_mm': 15.0,
        'hauteur_mm': 7.0,
        'module_mm': 0.5,
        'cadre': 'rect',
        'marge_cadre_mm': 0.5,
        'forme': 'auto',
    },
    'texte': {
        'largeur_mm': 6.2,
        'hauteur_mm': 1.2,
        'dx_mm': -14.0,
        'dy_mm': -3.9,
    },
}


#: Cadres admis autour d'un symbole de montage.
CADRES = ('rect', 'circle', 'none')

#: Copie du fichier **tel qu'il était avant la première écriture de la
#: séance**, à côté de lui. Les cotes d'un montage sont celles de la
#: mécanique : une retouche malheureuse au bout de la flèche, ou un
#: montage supprimé au gestionnaire, doit pouvoir se défaire en
#: recopiant un fichier.
AVANT = 'montages.avant.json'

#: Vrai une fois la copie de la séance faite — ou qu'il n'y avait rien
#: à copier. Les écritures suivantes ne la remplacent pas : elle garde
#: l'état d'ouverture, pas celui d'il y a une retouche.
_copie_faite = False


#: Copie d'un fichier illisible, faite avant qu'un import ne le remplace.
ILLISIBLE = 'montages.illisible.json'


class GabaritError(ValueError):
    """Un gabarit ne tient pas debout."""


def cle_poste(libelle) -> str:
    """La clé d'un poste — celle du formulaire : minuscules, sans espace.

    « POSTE 4 » et « Poste 4 » ont la même : deux postes ainsi nommés se
    confondraient.
    """
    return str(libelle).strip().lower().replace(' ', '_')


def chemin() -> pathlib.Path:
    from .recipes import library_dir
    return library_dir() / FICHIER


def positions(gab: dict) -> list[float]:
    """Les ordonnées des postes, du haut vers le bas.

    `positions_y_mm` l'emporte quand il est donné : un montage
    irrégulier n'a pas d'entraxe à déclarer.
    """
    explicites = gab.get('positions_y_mm')
    postes = gab.get('postes') or []
    if explicites:
        if len(explicites) != len(postes):
            raise GabaritError(
                f'{len(postes)} poste(s) mais {len(explicites)} position(s) '
                f'dans « {gab.get("nom", "sans nom")} »')
        return [float(y) for y in explicites]

    entraxe = float(gab.get('entraxe_mm', 0.0))
    centre = float(gab.get('centre_y_mm', 0.0))
    n = len(postes)
    if n == 0:
        raise GabaritError('un gabarit sans poste ne pose rien')
    # le poste du milieu tombe sur `centre` ; pour un nombre pair, le
    # centre est entre les deux du milieu, ce qui est bien ce qu'on veut
    milieu = (n - 1) / 2.0
    return [centre + (milieu - i) * entraxe for i in range(n)]


def positions_x(gab: dict) -> list[float]:
    """Les abscisses des postes, du haut vers le bas.

    Toutes à `x_mm`, sauf si `positions_x_mm` les donne une à une — un
    poste décalé d'un rien sur le montage réel.
    """
    explicites = gab.get('positions_x_mm')
    n = len(gab.get('postes') or [])
    if explicites:
        if len(explicites) != n:
            raise GabaritError(
                f'{n} poste(s) mais {len(explicites)} abscisse(s) '
                f'dans « {gab.get("nom", "sans nom")} »')
        return [float(x) for x in explicites]
    return [float(gab.get('x_mm', 0.0))] * n


def proposees(gab: dict) -> list[str]:
    """La référence que chaque poste porte à la pose.

    `donnees` la donne poste par poste ; une case vide, ou absente,
    reprend `donnee`. C'est ce que montre le formulaire du montage au
    moment où on le pose.
    """
    defaut = str(gab.get('donnee') or LIVRE['donnee'])
    par_poste = gab.get('donnees') or []
    out = []
    for i in range(len(gab.get('postes') or [])):
        valeur = str(par_poste[i]).strip() if i < len(par_poste) else ''
        out.append(valeur or defaut)
    return out


def verifier(gab: dict) -> dict:
    """Rend le gabarit complété de ses valeurs par défaut. Lève si faux.

    On complète plutôt qu'on n'exige : un gabarit écrit à la main ne
    porte que ce qui change du montage livré, et lui réclamer les douze
    autres valeurs le rendrait pénible à écrire — donc faux.

    Toute faute lève `GabaritError` : un `"code": 5` levait une erreur
    de type que les imports ne rattrapaient pas, et l'import des réglages
    s'arrêtait à moitié.
    """
    try:
        return _verifier(gab)
    except GabaritError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        nom = gab.get('nom', 'sans nom') if isinstance(gab, dict) else '?'
        raise GabaritError(f'« {nom} » mal formé : {exc}') from exc


def _verifier(gab: dict) -> dict:
    if not isinstance(gab, dict):
        raise GabaritError('un gabarit doit être un objet')
    plein = copy.deepcopy(LIVRE)
    for cle, valeur in gab.items():
        if isinstance(valeur, dict) and isinstance(plein.get(cle), dict):
            plein[cle].update(valeur)
        else:
            plein[cle] = valeur
    if not plein.get('nom'):
        raise GabaritError('un gabarit doit porter un nom')
    positions(plein)                       # lève si postes et positions
                                           # ne s'accordent pas
    positions_x(plein)
    if not isinstance(plein.get('donnees', []), list):
        raise GabaritError(
            f'« donnees » doit être une liste dans « {plein["nom"]} »')
    for section, cles in (('code', ('largeur_mm', 'hauteur_mm', 'module_mm')),
                          ('texte', ('largeur_mm', 'hauteur_mm'))):
        for cle in cles:
            if float(plein[section][cle]) <= 0:
                raise GabaritError(
                    f'{section}.{cle} doit être positif dans '
                    f'« {plein["nom"]} »')
    return plein


def _lire(p: pathlib.Path) -> list | None:
    """Les entrées brutes du fichier — None s'il n'existe pas.

    Lève `GabaritError` s'il existe mais ne se lit pas. La marque d'ordre
    des octets qu'ajoute le Bloc-notes est admise : un fichier corrigé à
    la main ne doit pas devenir illisible pour autant.
    """
    if not p.exists():
        return None
    try:
        brut = json.loads(p.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise GabaritError(f'« {p.name} » est illisible ({exc})') from exc
    if isinstance(brut, dict):
        brut = brut.get('montages', [brut])
    if not isinstance(brut, list):
        raise GabaritError(f'« {p.name} » ne contient aucune liste de '
                           f'montages')
    return brut


def _tri(brut) -> tuple[list, list, list[str]]:
    """`(valides, entrées refusées telles quelles, raisons des refus)`."""
    valides, refusees, raisons = [], [], []
    for gab in brut or []:
        try:
            valides.append(verifier(gab))
        except (GabaritError, TypeError, KeyError, ValueError,
                AttributeError) as exc:
            nom = gab.get('nom', '?') if isinstance(gab, dict) else '?'
            refusees.append(gab)
            raisons.append(f'{nom} : {exc}')
    return valides, refusees, raisons


def charger() -> list[dict]:
    """Les gabarits du poste. Rend au moins celui qui est livré.

    Un fichier absent, illisible ou vide n'est pas une erreur : c'est un
    poste qui n'a rien personnalisé. Le montage livré doit marcher sans
    que personne n'ait rien écrit.
    """
    try:
        brut = _lire(chemin())
    except GabaritError:
        return [verifier({})]
    out, _refusees, raisons = _tri(brut)
    if raisons:
        # un gabarit fautif ne doit pas emporter les autres, ni le montage
        # livré — mais il ne doit pas non plus disparaître sans un mot
        from .avale import avale
        avale('gabarit refusé', GabaritError('; '.join(raisons)))
    return out or [verifier({})]


def etat_fichier() -> str:
    """Ce que le fichier porte sans qu'on le montre — vide si rien.

    Un fichier illisible, des montages refusés : le gestionnaire le dit,
    plutôt que de laisser croire que le fichier ne contient que ce qu'il
    montre.
    """
    try:
        _valides, _refusees, raisons = _tri(_lire(chemin()))
    except GabaritError as exc:
        return (f'{exc} : seul le montage livré est montré, et rien ne '
                f'sera écrit tant qu\'il n\'aura pas été corrigé.')
    if raisons:
        return (f'{len(raisons)} montage(s) refusé(s), gardé(s) tels quels '
                f'dans le fichier : ' + ' ; '.join(raisons))
    return ''


def enregistrer(gabarits: list[dict], *,
                remplace_illisible: bool = False) -> pathlib.Path:
    """Écrit les gabarits. Rend le chemin écrit.

    **Rien de ce qu'on n'a pas su lire n'est perdu.** Les entrées que
    `verifier` refuse — invisibles au gestionnaire comme à la flèche —
    sont réécrites telles quelles, à la suite : sans cela, la première
    retouche au bout de la flèche effaçait du fichier le montage qu'on y
    avait écrit à la main avec une faute.

    Un fichier **illisible** n'est pas écrasé : l'écriture est refusée.
    Seul un import qui le remplace sciemment passe outre
    (`remplace_illisible`), et il en garde d'abord une copie,
    `ILLISIBLE`.

    La première écriture de la séance garde l'état d'avant dans
    `AVANT` : voir là.
    """
    p = chemin()
    verifies = [verifier(g) for g in gabarits]
    try:
        _valides, gardees, _raisons = _tri(_lire(p))
    except GabaritError as exc:
        if not remplace_illisible:
            raise GabaritError(
                f'{exc} : rien n\'est écrit. Corrigez-le, ou supprimez-le '
                f'pour repartir du montage livré.') from exc
        try:
            shutil.copy2(p, p.with_name(ILLISIBLE))
        except OSError as err:
            raise GabaritError(
                f'{exc}, et sa copie n\'a pu être faite ({err}) : rien '
                f'n\'est écrit.') from err
        gardees = []
    p.parent.mkdir(parents=True, exist_ok=True)
    _garder_avant(p)
    p.write_text(
        json.dumps({'montages': verifies + gardees},
                   ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    return p


def _garder_avant(p: pathlib.Path) -> None:
    """Copie le fichier à côté de lui, une fois par séance."""
    global _copie_faite
    if _copie_faite:
        return
    _copie_faite = True
    if not p.exists():
        return
    try:
        shutil.copy2(p, p.with_name(AVANT))
    except OSError as exc:
        from .avale import avale
        avale('gabarits : copie de sécurité non écrite', exc)


def remplacer(gab: dict, ancien_nom: str = '') -> pathlib.Path:
    """Range un gabarit : à la place de celui qui s'appelait `ancien_nom`
    — son propre nom à défaut —, et à la fin s'il n'y en a pas."""
    plein = verifier(gab)
    liste = charger()
    cle = ancien_nom or plein['nom']
    for i, g in enumerate(liste):
        if g['nom'] == cle:
            liste[i] = plein
            break
    else:
        liste.append(plein)
    return enregistrer(liste)


def mettre_en_tete(nom: str) -> bool:
    """Fait de `nom` le montage que pose le bouton. Faux s'il n'existe pas."""
    liste = charger()
    for i, g in enumerate(liste):
        if g['nom'] == nom:
            if i:
                liste.insert(0, liste.pop(i))
                enregistrer(liste)
            return True
    return False


def nom_libre(voulu: str, pris) -> str:
    """`voulu`, ou `voulu (2)`, `(3)`… s'il est déjà pris."""
    voulu = (voulu or '').strip() or 'Montage'
    pris = set(pris)
    if voulu not in pris:
        return voulu
    k = 2
    while f'{voulu} ({k})' in pris:
        k += 1
    return f'{voulu} ({k})'


def fusionner(liste: list[dict], venus: list[dict]):
    """Ajoute des gabarits à une liste sans en remplacer aucun.

    Rend `(liste, ajoutés, identiques)`. Un gabarit déjà présent à
    l'identique n'entre pas une seconde fois ; un homonyme aux cotes
    différentes entre sous un nom libre — deux montages du même nom
    seraient indiscernables au bout de la flèche.
    """
    out = [verifier(g) for g in liste]
    ajoutes = identiques = 0
    for brut in venus:
        g = verifier(brut)
        if any(g == deja for deja in out):
            identiques += 1
            continue
        g['nom'] = nom_libre(g['nom'], (d['nom'] for d in out))
        out.append(g)
        ajoutes += 1
    return out, ajoutes, identiques


# --------------------------------------------------------------------------
# Un montage posé, relu en gabarit
# --------------------------------------------------------------------------

#: Écart en deçà duquel deux cotes sont les mêmes, en mm. Le micron :
#: trente fois plus fin que le spot, et assez large pour absorber les
#: arrondis d'un déplacement à la souris.
JEU_MM = 1e-3


def _arrondi(v: float) -> float:
    return round(float(v), 4)


def _memes(a, b) -> bool:
    return len(a) == len(b) and all(abs(x - y) < JEU_MM
                                    for x, y in zip(a, b))


def poser_ordonnees(gab: dict, ys: list[float], garder: bool) -> None:
    """Range des ordonnées dans un gabarit, sous la forme la plus parlante.

    Celle du gabarit si elle les donne encore (`garder`) ; un entraxe et
    un centre si elles sont régulièrement espacées du haut vers le bas ;
    une à une sinon.
    """
    if garder:
        try:
            if _memes(positions(gab), ys):
                return
        except GabaritError:
            pass
    gab.pop('positions_y_mm', None)
    n = len(ys)
    if n == 1:
        gab['centre_y_mm'] = _arrondi(ys[0])
        return
    pas = [ys[i] - ys[i + 1] for i in range(n - 1)]
    if min(pas) > 0 and max(pas) - min(pas) < JEU_MM:
        gab['entraxe_mm'] = _arrondi(sum(pas) / len(pas))
        gab['centre_y_mm'] = _arrondi((ys[0] + ys[-1]) / 2)
    else:
        gab['positions_y_mm'] = [_arrondi(y) for y in ys]


def poser_abscisses(gab: dict, xs: list[float]) -> None:
    """Range des abscisses dans un gabarit : communes si elles le sont."""
    try:
        if _memes(positions_x(gab), xs):
            return
    except GabaritError:
        pass
    gab.pop('positions_x_mm', None)
    if max(xs) - min(xs) < JEU_MM:
        gab['x_mm'] = _arrondi(xs[0])
    else:
        gab['positions_x_mm'] = [_arrondi(x) for x in xs]
        # la version d'avant ignore les abscisses une à une : elle pose
        # tout au milieu, ce qui reste le moins faux
        gab['x_mm'] = _arrondi((min(xs) + max(xs)) / 2)


def trier_postes(gab: dict) -> None:
    """Range les postes du haut vers le bas, nom, abscisse et référence
    proposée suivant chacun sa place.

    Le formulaire lit les postes dans cet ordre-là : un gabarit dont le
    poste « A » serait en bas mais listé en tête ferait taper la
    référence de A sur le code du haut.
    """
    ys = positions(gab)
    ordre = sorted(range(len(ys)), key=lambda i: -ys[i])
    if ordre == list(range(len(ys))):
        return
    xs = positions_x(gab)
    gab['postes'] = [gab['postes'][i] for i in ordre]
    if gab.get('donnees'):
        refs = list(gab['donnees']) + [''] * len(ys)
        gab['donnees'] = [refs[i] for i in ordre]
    poser_ordonnees(gab, [ys[i] for i in ordre], False)
    if gab.get('positions_x_mm'):
        gab['positions_x_mm'] = [xs[i] for i in ordre]


def depuis_formes(shapes, base: dict | None = None, *,
                  references: bool = False) -> dict:
    """Le gabarit que décrit un montage posé — retouché ou non.

    Lit sur les formes ce que le plan de travail laisse retoucher : la
    position de chaque poste, le cadre, la marge, la taille et le module
    du symbole, la place et la taille du texte. Le symbole et le texte du
    **poste du haut** font foi pour tous ; les postes sont rangés du haut
    vers le bas, et chacun garde sa référence proposée.

    `base` est le gabarit d'où vient le montage : ce que les formes
    n'ont pas changé y garde **sa forme** — un entraxe reste un entraxe,
    une fenêtre de texte reste celle qu'on avait tapée. Relire un
    montage tel qu'il a été posé rend donc son gabarit à l'identique.

    La fenêtre du texte est gardée tant qu'elle redonne à chaque poste
    la taille de son texte, **avec la référence que la pose lui
    proposera** — pas celle qu'il porte. Sinon elle est recalculée pour
    la taille du texte du haut, assez large pour la plus longue des
    références proposées : retenue sur « A1 », elle ferait rétrécir le
    « B000181 » de la pose suivante — le défaut qu'avaient les plaques
    (EX-224).

    Un montage **tourné** ne se relit pas : ses positions et la place de
    ses textes sont tournées, et le gabarit n'en sait rien.

    `references` retient aussi les références saisies : la pose suivante
    les proposera.
    """
    from .codeplate import fit_text, text_window
    from .model import Text, ecrire_symbologie, lire_symbologie
    from .montage import pairs

    paires = sorted(pairs(list(shapes)), key=lambda p: -p[0].y)
    if not paires:
        raise GabaritError('aucun code suivi de son texte dans la sélection')
    if any((c.rotation_deg or 0) % 360 or (t.rotation_deg or 0) % 360
           for c, t in paires):
        raise GabaritError(
            'montage tourné : ses positions ne se relisent pas en gabarit. '
            'Retouchez-le droit, ou réglez le gabarit au gestionnaire.')
    gab = verifier(copy.deepcopy(base) if base else {})
    n = len(paires)
    anciens = list(gab['postes'])
    memes_postes = len(anciens) == n
    # un code sans rôle prend le nom du poste **à sa hauteur** dans le
    # gabarit, et non à son rang dans la liste, qui peut aller du bas
    # vers le haut
    du_haut = anciens
    if memes_postes:
        try:
            ys_base = positions(gab)
            du_haut = [anciens[i] for i in sorted(range(n),
                                                  key=lambda i: -ys_base[i])]
        except GabaritError:
            pass
    noms: list[str] = []
    vus: set = set()
    for i, (code, _texte) in enumerate(paires):
        nom = (str(code.role or '').strip()
               or (du_haut[i] if memes_postes else f'POSTE {i + 1}'))
        # deux postes de même clé se confondraient dans le formulaire,
        # qui les range en minuscules et sans espace
        racine, k = nom, 2
        while cle_poste(nom) in vus:
            nom, k = f'{racine} {k}', k + 1
        vus.add(cle_poste(nom))
        noms.append(nom)
    # chaque référence proposée suit son poste, même rangé autrement
    refs = list(gab.get('donnees') or [])
    refs += [''] * (len(anciens) - len(refs))
    par_cle = {cle_poste(a): r for a, r in zip(anciens, refs)}
    gab['postes'] = noms
    if [cle_poste(a) for a in anciens] != [cle_poste(nm) for nm in noms]:
        if set(par_cle) == {cle_poste(nm) for nm in noms} and any(refs):
            gab['donnees'] = [par_cle[cle_poste(nm)] for nm in noms]
        else:
            gab.pop('donnees', None)
    poser_ordonnees(gab, [c.y for c, _ in paires], memes_postes)
    poser_abscisses(gab, [c.x for c, _ in paires])

    code0, texte0 = paires[0]
    c = gab['code']
    # le fichier des montages passe d'une version à l'autre : une
    # symbologie récente va à part (`model.ecrire_symbologie`), et une
    # symbologie inchangée n'est pas réécrite
    if code0.kind != lire_symbologie(c):
        ecrire_symbologie(c, code0.kind)
    if code0.fit_w_mm > 0 and code0.fit_h_mm > 0:
        c['largeur_mm'] = _arrondi(code0.fit_w_mm)
        c['hauteur_mm'] = _arrondi(code0.fit_h_mm)
    c['module_mm'] = float(code0.module_mm)
    c['cadre'] = code0.frame if code0.frame in CADRES else 'none'
    c['marge_cadre_mm'] = _arrondi(max(0.0, code0.frame_margin_mm))
    c['forme'] = code0.dm_shape or 'auto'
    if references:
        gab['donnees'] = [str(code.data) for code, _ in paires]

    t = gab['texte']
    t['dx_mm'] = _arrondi(texte0.x - code0.x)
    t['dy_mm'] = _arrondi(texte0.y - code0.y)
    proposees_ = proposees(gab)
    largeur, hauteur = float(t['largeur_mm']), float(t['hauteur_mm'])
    if any(abs(fit_text(propose, largeur, hauteur).size_mm
               - texte.size_mm) >= JEU_MM
           for propose, (_code, texte) in zip(proposees_, paires)):
        fenetres = [text_window(Text(text=propose, size_mm=texte0.size_mm))
                    for propose in proposees_]
        fenetres = [f for f in fenetres if f]
        if fenetres:
            # arrondie vers le haut : un dix-millième de moins ferait
            # réduire le texte d'autant
            t['largeur_mm'] = math.ceil(max(f[0] for f in fenetres)
                                        * 1e4) / 1e4
            t['hauteur_mm'] = _arrondi(max(f[1] for f in fenetres))
    return verifier(gab)


def ecrire_livre_si_absent() -> pathlib.Path | None:
    """Pose le gabarit livré sur le poste, s'il n'y est pas déjà.

    Le fichier n'est **pas** nécessaire au fonctionnement — `charger()`
    retombe sur le gabarit livré. Il est écrit pour être **lu et
    modifié** : personne ne corrige un entraxe dans un fichier dont il
    ignore l'existence.
    """
    p = chemin()
    if p.exists():
        return None
    try:
        return enregistrer([copy.deepcopy(LIVRE)])
    except OSError:
        return None
