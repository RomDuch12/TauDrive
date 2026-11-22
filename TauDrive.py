"""Lanceur de TauDrive. / TauDrive launcher.

    python atelier/TauDrive.py
    TauDrive.exe

Option `--autotest` : construit la fenêtre, exerce les fonctions
principales, écrit un rapport et sort. Sert à vérifier qu'un exécutable
empaqueté est complet — un démarrage sans plantage ne prouve pas que les
polices, les ressources ou l'import DXF sont bien embarqués.

    TauDrive.exe --autotest > rapport.txt
    TauDrive.exe --autotest --liste          les grappes disponibles
    TauDrive.exe --autotest vectoriel        une seule grappe
    TauDrive.exe --autotest dossiers,gravure deux d'un coup

Chaque contrôle s'affiche **au fil de l'eau**. Attendre la fin ne
laissait aucune trace de ce qui avait réussi quand la suite se bloquait.

Option `--convert` : convertit des dessins vectoriels et sort, sans
ouvrir de fenêtre. C'est ce que lance le menu contextuel de l'explorateur
Windows (Paramètres ▸ Menu contextuel Windows).

    TauDrive.exe --convert dessin.ai --to dxf
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / 'src'))


def _pdf_essai() -> bytes:
    """Un PDF minimal de géométrie connue : un rectangle et un triangle.

    Écrit à la main plutôt que produit par une bibliothèque : le contrôle
    doit porter sur **notre** lecteur, et non sur l'accord de deux
    bibliothèques entre elles.
    """
    flux = (b'1 0 0 1 0 0 cm' + bytes([10])
            + b'10 10 m 236.7717 10 l 236.7717 123.3858 l 10 123.3858 l h S'
            + bytes([10])
            + b'10 10 m 236.7717 10 l 123 123.3858 l h S' + bytes([10]))
    objets = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 150] '
        b'/Contents 4 0 R >>',
        b'<< /Length ' + str(len(flux)).encode() + b' >>stream'
        + bytes([10]) + flux + b'endstream',
    ]
    out = bytearray(b'%PDF-1.4' + bytes([10]))
    places = []
    for i, corps in enumerate(objets, 1):
        places.append(len(out))
        out += str(i).encode() + b' 0 obj' + bytes([10]) + corps
        out += bytes([10]) + b'endobj' + bytes([10])
    debut = len(out)
    out += b'xref' + bytes([10]) + b'0 ' + str(len(objets) + 1).encode()
    out += bytes([10]) + b'0000000000 65535 f ' + bytes([10])
    for place in places:
        out += f'{place:010d} 00000 n '.encode() + bytes([10])
    out += b'trailer' + bytes([10])
    out += b'<< /Size ' + str(len(objets) + 1).encode() + b' /Root 1 0 R >>'
    out += bytes([10]) + b'startxref' + bytes([10])
    out += str(debut).encode() + bytes([10]) + b'%%EOF' + bytes([10])
    return bytes(out)


#: Les grappes de l'autotest. Une grappe, pas une section : les
#: sections partagent leurs montages — dossier temporaire, document
#: d'exemple — et n'ont pas de frontière nette entre elles.
DOMAINES = (
    ('interface', 'onglets, formes, boutons, coupon, journal, magasin'),
    ('dossiers', 'mémoire des chemins, réglages, couteau, vignettes'),
    ('vectoriel', 'DXF, PDF, SVG, cotations, texte, montage, conversion'),
    ('gravure', 'remplissage, oscillation, lot, esquisse, vérification'),
    ('plugins', 'mécanisme des plugins, contrôles des plugins posés'),
)

#: Le socle — thèmes, polices, fenêtre, port série — tourne **toujours**.
#: Il pose ce dont les quatre grappes se servent, et il coûte deux
#: secondes : le rendre optionnel n'aurait rien fait gagner.


def _domaines_demandes() -> set:
    """Les grappes nommées sur la ligne de commande.

    `--autotest` seul les prend toutes ; `--autotest --liste` les
    énumère et sort.
    """
    if '--liste' in sys.argv:
        return {'?'}
    connus = {d for d, _ in DOMAINES}
    demandes = set()
    apres = False
    for mot in sys.argv[1:]:
        if mot == '--autotest':
            apres = True
            continue
        if apres and not mot.startswith('-'):
            demandes |= {m.strip() for m in mot.split(',') if m.strip()}
        apres = False
    inconnus = demandes - connus
    if inconnus:
        print('Domaine inconnu : ' + ', '.join(sorted(inconnus)))
        print('Connus : ' + ', '.join(sorted(connus)))
        raise SystemExit(2)
    return demandes


def autotest() -> int:
    """Vérifie qu'une installation figée est fonctionnelle."""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass

    checks: list[tuple[str, bool, str]] = []
    #: Largeur de la colonne des libellés. Fixe, parce qu'on écrit au fil
    #: de l'eau : on ne connaît pas encore le plus long.
    COLONNE = 74

    def check(label, ok, detail=''):
        """Enregistre un contrôle — **et le dit aussitôt**.

        Écrire au fil de l'eau plutôt qu'à la fin : quand la suite se
        bloque, la sortie montre où. Attendre la fin ne laissait aucune
        trace de ce qui avait déjà réussi, et il fallait un
        `faulthandler` pour retrouver la ligne fautive.
        """
        checks.append((label, bool(ok), str(detail)))
        print(f'  [{"OK " if ok else "KO "}] {label.ljust(COLONNE)}  '
              f'{detail}', flush=True)

    # --- ce qu'on exécute -----------------------------------------------
    #
    # Les sections ne sont **pas** indépendantes : vingt-deux d'entre
    # elles lisent un montage posé plus haut — un dossier temporaire, un
    # document d'exemple, un alias de module. Le découpage se fait donc
    # par **grappe** et non par section : chaque grappe est cohérente et
    # se suffit à elle-même.
    demandees = _domaines_demandes()
    if demandees == {'?'}:
        print('Domaines : ' + ', '.join(d for d, _ in DOMAINES))
        for cle, quoi in DOMAINES:
            print(f'  {cle.ljust(14)} {quoi}')
        return 0

    def domaine(cle: str) -> bool:
        """Vrai si cette grappe doit tourner."""
        return not demandees or cle in demandees

    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    # **Identité Qt distincte de celle de l\'application.**
    #
    # `QStandardPaths` en tire le dossier des réglages, donc celui de la
    # bibliothèque de process. Sans identité du tout, Qt retombe sur le
    # nom de l\'exécutable — « python » en source, « TauDrive » en
    # figé : deux bibliothèques différentes selon la façon de lancer.
    # Avec l\'identité de l\'application, l\'autotest
    # écrirait dans la bibliothèque **réelle** de l\'atelier, qu\'il
    # a toutes les raisons de ne pas toucher.
    app.setOrganizationName('Cielle')
    app.setApplicationName('TauDrive-autotest')

    from engrave import icons, textvec, theme
    from engrave.app import (MainWindow, app_icon, install_french,
                             resource_dir)
    # Ce que le chargement de l'application laisse hors mémoire : ces
    # modules ne servent qu'à l'import d'un DXF ou à un calcul GEOS, et
    # coûtaient une seconde à chaque démarrage — voir `dxfimport`.
    _lourds_t = [m for m in ('ezdxf', 'numpy', 'shapely', 'urllib.request')
                 if m in sys.modules]
    # Ce dont plusieurs grappes se servent, posé une fois dans le socle :
    # sans cela, demander une grappe seule échouait sur un alias que la
    # précédente avait défini.
    import shutil
    import tempfile
    from PySide6.QtGui import QAction as _QAction
    from engrave import coupon
    from engrave.model import RECIPE_LIBRARY
    from PySide6.QtCore import Qt as _Qt
    install_french(app)
    from engrave.model import Document, PRESET_RECIPES, Rect, Text
    from engrave.toolpath import build_passes, shape_contours

    theme.apply(app)
    print(f'TauDrive — auto-test  (figé : {getattr(sys, "frozen", False)})'
          + (f'  ·  {", ".join(sorted(demandees))}' if demandees else '')
          + chr(10), flush=True)
    check('démarrage : ezdxf, numpy, shapely chargés à la demande',
          not _lourds_t, ', '.join(_lourds_t) or 'aucun au chargement')
    check('thèmes disponibles', len(theme.names()) >= 19,
          f'{len(theme.names())} dont '
          f'{sum(1 for p in theme.THEMES if p.dark)} sombres')

    # --- un seul numéro de version, comme VectorDrive -----------------------
    # `engrave.__version__` le porte ; la fenêtre « À propos » l'affiche,
    # `version_info.py` l'inscrit dans les propriétés Windows de
    # l'exécutable. Lancé depuis le dépôt, l'autotest relit `version_info.py`
    # ; figé, il lit aussi les propriétés de son propre exécutable.
    import re as _re_v
    from engrave import __version__ as _v_paquet
    from engrave import app as _app_v
    _lus_v = {'paquet': _v_paquet, 'À propos': _app_v.VERSION}
    _vi_v = pathlib.Path('version_info.py')
    if _vi_v.is_file():
        import importlib.util as _ilu_v
        _sp_v = _ilu_v.spec_from_file_location('version_info_autotest',
                                               str(_vi_v))
        _m_v = _ilu_v.module_from_spec(_sp_v)
        _sp_v.loader.exec_module(_m_v)
        _lus_v['version_info.py'] = '.'.join(str(_n) for _n in
                                             _m_v.VERSION[:3])
    if getattr(sys, 'frozen', False) and sys.platform == 'win32':
        import ctypes as _ct_v
        from ctypes import wintypes as _wt_v

        class _FixeV(_ct_v.Structure):
            # VS_FIXEDFILEINFO : treize mots de 32 bits
            _fields_ = [(_n, _wt_v.DWORD) for _n in (
                'sig', 'struc', 'fms', 'fls', 'pms', 'pls', 'masque',
                'drapeaux', 'os', 'genre', 'sous_genre', 'dms', 'dls')]

        def _version_exe_v(_chemin):
            _dll = _ct_v.windll.version
            _taille = _dll.GetFileVersionInfoSizeW(_chemin, None)
            _tampon = _ct_v.create_string_buffer(max(_taille, 1))
            _ptr, _lg = _ct_v.c_void_p(), _wt_v.UINT()
            if not (_taille and _dll.GetFileVersionInfoW(_chemin, 0, _taille,
                                                         _tampon)
                    and _dll.VerQueryValueW(_tampon, chr(92),
                                            _ct_v.byref(_ptr),
                                            _ct_v.byref(_lg))):
                return 'illisible'
            _f = _FixeV.from_address(_ptr.value)
            return f'{_f.fms >> 16}.{_f.fms & 0xFFFF}.{_f.fls >> 16}'
        _lus_v['exécutable'] = _version_exe_v(sys.executable)
    check('version : un seul numéro x.y.z — paquet, À propos, propriétés de '
          'l' + chr(39) + 'exécutable',
          bool(_re_v.fullmatch(r'\d+\.\d+\.\d+', _v_paquet))
          and len(set(_lus_v.values())) == 1,
          ' · '.join(f'{_k} {_v}' for _k, _v in _lus_v.items()))

    def _luminance(couleur):
        c = [int(couleur[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
             for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def _contraste(a, b):
        la, lb = _luminance(a), _luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    # Un thème joli mais illisible ferait rater une cote : le contraste se
    # vérifie au calcul, pas à l'œil.
    # Le texte secondaire passe de 3 a 4.5 — le seuil AA. A 3, un gris
    # pale sur fond clair « passait » alors qu'il ne se lit pas.
    faibles = [p.key for p in theme.THEMES
               if _contraste(p.text, p.panel) < 7
               or _contraste(p.text_dim, p.panel) < 4.5
               or _contraste(p.path, p.canvas) < 4.5]
    # Les quatre roles que porte le texte secondaire — note, alerte,
    # avertissement, succes — sur les dix-neuf themes.
    _roles_faibles = [
        f'{p.key}/{role}'
        for p in theme.THEMES
        for role in ('text_dim', 'warn', 'alarm', 'ok')
        if _contraste(getattr(p, role), p.panel) < 4.5]
    check('themes : notes, alertes et succes lisibles partout',
          not _roles_faibles,
          f'{len(theme.THEMES)} themes x 4 roles = '
          f'{len(theme.THEMES) * 4} controles'
          if not _roles_faibles else ', '.join(_roles_faibles[:6]))

    # Une couleur ecrite en dur ne suit aucun theme. Elles etaient
    # cinquante-deux, mesurees a 3,06 de contraste sur les huit themes
    # clairs — pour un seuil lisible de 4,5.
    import re as _re_c
    _dures = []
    for _f in sorted(pathlib.Path('src/engrave').glob('*.py')):
        if _f.name == 'theme.py':
            continue
        for _m in _re_c.finditer(r'color\s*:\s*#[0-9a-fA-F]{6}',
                                 _f.read_text(encoding='utf-8')):
            _dures.append(f'{_f.name}:{_m.group(0)}')
    check('themes : plus aucune couleur ecrite en dur',
          not _dures,
          'tout passe par theme.css(), theme.span() ou theme.hex_of()'
          if not _dures else ', '.join(_dures[:5]))

    check('tous les thèmes restent lisibles', not faibles,
          ', '.join(faibles) or 'texte ≥ 7:1, tracé ≥ 4,5:1')

    applique = True
    for palette in theme.THEMES:
        theme.apply(app, palette.key)
        applique &= theme.current().key == palette.key
    theme.apply(app, theme.DEFAULT)
    check('chaque thème s\'applique', applique, f'{len(theme.THEMES)} essayés')
    check('ressources trouvées', resource_dir().is_dir(), resource_dir())
    icon = app_icon()
    check('icône applicative', icon is not None and not icon.isNull())
    check('icônes de barre d\'outils',
          all(not icons.icon(n).isNull() for n in icons.DRAWINGS),
          f'{len(icons.DRAWINGS)} dessins')

    fonts = textvec.available_fonts()
    check('polices système lisibles', len(fonts) > 0, f'{len(fonts)} polices')

    # **Un bac à part, vide à chaque passage.** La fenêtre lit et écrit
    # la session et les réglages du poste ; sans ce bac, l'autotest
    # vidait l'index des onglets fermés de l'opérateur, archivait ses
    # onglets d'essai parmi les vrais, et rouvrait à chaque passage tout
    # ce que le précédent avait laissé — voir `session.isolate`.
    from engrave import session as _ses_bac
    _bac_session = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-bac-'))
    _ses_bac.isolate(_bac_session)

    # **Un magasin d'outils d'essai.** Le cœur libre n'en livre aucun :
    # celui de l'atelier vient de son plugin. L'autotest pose le sien, comme
    # le ferait un plugin — un outil par couple constructeur de la source,
    # plus deux au-delà de la table comme en portent les magasins réels, et
    # un séparateur de présentation — pour éprouver la lecture, le
    # chargement dans une process et la contre-épreuve des recommandations.
    # La grappe `plugins` l'oublie avant de charger les vrais.
    import json as _json_mag
    from engrave import plugins as _plugins_mag
    _outils_essai = [{'tool_number': 1, 'name': '------ essai ------',
                      'speed_mm_min': 40000.0, 'power_percent': 50.0,
                      'frequency_hz': 80000, 'resolution_px_mm': 0,
                      'spot_mm': 0.03, 'pulse_width_ns': 100}]
    for _n_mag, (_f_mag, _t_mag) in enumerate(
            [(1300, 2), (375, 9), (250, 13), (170, 20), (135, 30), (110, 45),
             (100, 60), (90, 80), (80, 100), (37, 200), (37, 250), (37, 350),
             (37, 500), (500, 20), (450, 30)], start=2):
        _outils_essai.append({
            'tool_number': _n_mag, 'name': f'Essai {_f_mag}-{_t_mag}',
            'speed_mm_min': 40000.0, 'power_percent': 80.0,
            'frequency_hz': _f_mag * 1000, 'resolution_px_mm': 769,
            'spot_mm': 0.03, 'pulse_width_ns': _t_mag})
    _mag_essai = _bac_session / 'outils-essai.json'
    _mag_essai.write_text(_json_mag.dumps({'tools': _outils_essai}),
                          encoding='utf-8')
    _plugins_mag.REGISTRY.tool_store = _mag_essai

    # **Des dessins livrés d'essai**, pour la même raison : le cœur libre
    # n'en livre aucun. Un petit, et un lourd de 3,5 Mo — trois mille
    # contours et mille cinq cents cercles — sur lequel l'esquisse doit
    # rester bien plus rapide que la lecture exacte, et la lecture rendre
    # des comptes, comme sur les dessins livrés d'un atelier.
    import math as _math_liv
    import ezdxf as _ezdxf_liv
    _livres_essai = _bac_session / 'livres-essai'
    _livres_essai.mkdir()
    _doc_liv = _ezdxf_liv.new('R2010')
    _doc_liv.header['$INSUNITS'] = 4
    _doc_liv.modelspace().add_lwpolyline(
        [(0, 0), (30, 0), (30, 20), (0, 20)], close=True)
    _doc_liv.saveas(_livres_essai / 'Essai.dxf')
    _doc_liv = _ezdxf_liv.new('R2010')
    _doc_liv.header['$INSUNITS'] = 4
    _msp_liv = _doc_liv.modelspace()
    for _k_liv in range(3000):
        _cx_liv, _cy_liv = (_k_liv % 60) * 1.8, (_k_liv // 60) * 1.8
        _msp_liv.add_lwpolyline(
            [(_cx_liv + _math_liv.cos(_a / 12 * _math_liv.pi)
              * (0.8 + 0.05 * (_a % 3)),
              _cy_liv + _math_liv.sin(_a / 12 * _math_liv.pi) * 0.8)
             for _a in range(24)], close=True)
        if _k_liv % 2:
            _msp_liv.add_circle((_cx_liv, _cy_liv), 0.3)
    _doc_liv.saveas(_livres_essai / 'Essai lourd.dxf')
    _plugins_mag.REGISTRY.drawings_dir = _livres_essai

    window = MainWindow()
    window.show()
    app.processEvents()
    check('fenêtre construite', window.isVisible())
    check('autotest : réglages, session et archive dans un bac à part',
          _ses_bac.isolated()
          # Qt rend le chemin avec des barres obliques : comparer des
          # chemins, pas des chaînes
          and pathlib.Path(_ses_bac.settings().fileName()).parent
          == _bac_session
          and _ses_bac.session_file().parent == _bac_session
          and _ses_bac.archive_dir().parent == _bac_session
          and window.tabs.count() == 1,
          f'{_bac_session.name} · fenêtre ouverte sur un seul onglet vierge')

    # onglet neuf : la fenêtre rouvre les documents de la dernière session,
    # dont le contenu fausserait les comptages qui suivent
    workbench = window.new_tab()
    window.document.add(Rect(width=20, height=10, recipe=PRESET_RECIPES[1]))
    window.document.add(Text(text='TAU {n:03}', size_mm=6, frame='rect',
                             recipe=PRESET_RECIPES[1]))
    window.canvas.reload()
    window._refresh_list()
    app.processEvents()
    window._update_status()
    check('trajectoires calculées', len(window._current_passes()) == 2,
          window.statusBar().currentMessage())

    import tempfile
    from engrave import iso, recipes, resize, serialize, session
    with tempfile.TemporaryDirectory() as tmp:
        files = iso.export(window.document, tmp)
        check('export ISO + CLJOB', len(files) >= 3, f'{len(files)} fichiers')

    if domaine('interface'):
        # --- À propos : version et licence -----------------------------------
        from PySide6.QtWidgets import QMessageBox as _QMB_lic
        _vu_lic = []
        _exec_lic = _QMB_lic.exec
        _QMB_lic.exec = lambda _b: _vu_lic.append(
            _b.text() + _b.informativeText()) or 0
        try:
            window._about()
        finally:
            _QMB_lic.exec = _exec_lic
        _txt_lic = _vu_lic[0] if _vu_lic else ''
        check('À propos : version, licence MIT ou Apache-2.0, composants tiers',
              _app_v.VERSION in _txt_lic
              and 'MIT ou Apache-2.0' in _txt_lic
              and 'THIRD_PARTY_NOTICES.md' in _txt_lic
              and 'aucune émission laser' in _txt_lic,
              f'{len(_vu_lic)} fenêtre(s) · version {_app_v.VERSION}')

        # --- fonctions ajoutées : onglets, groupes, F2, recettes, session ---

        before = window.tabs.count()
        window._new_document()
        check('onglets multiples', window.tabs.count() == before + 1,
              f'{window.tabs.count()} onglet(s)')
        window.tabs.setCurrentWidget(workbench)     # revenir à l'onglet d'essai

        ids = [s.id for s in window.document.shapes]
        window.canvas.select_many(ids)
        window._group()
        window.canvas.select(ids[0])
        check('groupe : un clic sélectionne tout',
              len(window.canvas.selected_ids()) == len(ids),
              f'{len(window.canvas.selected_ids())} forme(s)')

        shapes = window.canvas.selected_shapes()
        w0 = resize.selection_size(shapes)[0]
        resize.scale_selection(shapes, 2.0, 2.0)
        w1 = resize.selection_size(shapes)[0]
        check('redimensionnement F2', abs(w1 - 2 * w0) < 1e-6,
              f'{w0:.2f} → {w1:.2f} mm')
        window._ungroup()
        check('dégroupage', all(not s.group for s in window.document.shapes))

        check('mode expert verrouillé au démarrage', not recipes.expert())
        manager = recipes.RecipeManager(window)
        check('gestionnaire de process', len(manager.recipes) >= 1,
              f'{len(manager.recipes)} process(s)')
        check('fréquence et impulsion verrouillées',
              not manager.w_freq.isEnabled() and not manager.w_pulse.isEnabled())
        manager.deleteLater()

        # la recette vit en colonne 1, sous la liste des formes
        from PySide6.QtCore import Qt as _Qt
        dock_list, dock_recipe = window._dock_list, window._dock_recipe
        window.canvas.select(window.document.shapes[0].id)
        app.processEvents()
        check('process laser sous la liste des formes',
              window.dockWidgetArea(dock_recipe) == _Qt.LeftDockWidgetArea
              and dock_recipe.y() > dock_list.y(),
              f'liste y={dock_list.y()} · process y={dock_recipe.y()}')
        check('l\'éditeur de process est garni',
              hasattr(window.recipe, 'w_preset'),
              window.recipe.w_preset.currentText()
              if hasattr(window.recipe, 'w_preset') else '')

        # --- le dossier d'une process se lit dans les listes de sélection ------
        #
        # Le gestionnaire montrait le rangement, les listes de sélection non :
        # deux « Laiton » rangés dans deux dossiers y paraissaient identiques.
        import dataclasses as _dc

        from engrave.model import RECIPE_LIBRARY
        _rangee = _dc.replace(RECIPE_LIBRARY[0], name='Laiton',
                              folder='Essais 2026')
        check('process : le dossier précède le nom partout où on la choisit',
              recipes.label(_rangee) == 'Essais 2026 / Laiton'
              and recipes.label(_dc.replace(_rangee, folder='')) == 'Laiton',
              recipes.label(_rangee))
        _avant = list(RECIPE_LIBRARY)
        RECIPE_LIBRARY.insert(0, _rangee)
        try:
            window.recipe.refresh()
            _liste = [window.recipe.w_preset.itemText(i)
                      for i in range(window.recipe.w_preset.count())]
            window.lot.set_recipes([_rangee] + list(_avant))
            window.lot.set_lot(list(window.document.shapes[:2]),
                               window.document)
            _lot_liste = [window.lot.w_recipe.itemText(i)
                          for i in range(window.lot.w_recipe.count())]
        finally:
            RECIPE_LIBRARY[:] = _avant
        # le dossier est un en-tête, la process en retrait dessous — dans
        # les deux listes, comme dans le gestionnaire
        def _sous_tete(liste, nom):
            for i, t in enumerate(liste[:-1]):
                if t.startswith('Essais 2026') and liste[i + 1].strip() == nom:
                    return True
            return False
        check('process : le dossier paraît dans « Préréglage » et dans le lot',
              _sous_tete(_liste, 'Laiton')
              and _sous_tete(_lot_liste, f'T{_rangee.tool_number} · Laiton'),
              ' | '.join(t.strip() for t in _liste[:4]) + ' · '
              + ' | '.join(t.strip() for t in _lot_liste[:4]))

        # champs de saisie : ni flèches, unité dehors, décimales dynamiques
        from engrave.widgets import Spin as _Spin
        fin = _Spin(0.004673, 0, 5, 0.001, 6, 'mm')
        rond = _Spin(15.0, 0, 100, 1, 3, 'mm')
        bruit = _Spin(-26.111537, -500, 500, 0.5, 3, 'mm')
        check('champs : décimales dynamiques',
              fin.spin.text() in ('0,004673', '0.004673')
              and rond.spin.text() == '15',
              f'{fin.spin.text()} · {rond.spin.text()}')
        check('champs : trois décimales montrées, la valeur reste entière',
              bruit.spin.text() in ('-26,112', '-26.112')
              and abs(bruit.value() - (-26.111537)) < 1e-12,
              f'{bruit.spin.text()} pour {bruit.value()}')
        check('champs : aucune flèche, unité à l\'extérieur',
              fin.spin.buttonSymbols().name == 'NoButtons'
              and fin._unit.text() == 'mm',
              fin.spin.buttonSymbols().name)

        # liste des formes : trois boutons par ligne
        from engrave.toolpath import build_passes as _passes
        first = window.document.shapes[0]
        row = window._rows.get(first.id)
        check('liste : boutons œil, dupliquer, supprimer',
              row is not None and all(b.toolTip() for b in
                                      (row.w_eye, row.w_copy, row.w_del)),
              row.w_eye.toolTip()[:30] if row else '')
        avant = len(_passes(window.document))
        row.w_eye.click()
        app.processEvents()
        check('œil fermé : la forme n\'est plus gravée',
              not first.visible and len(_passes(window.document)) < avant,
              f'{avant} → {len(_passes(window.document))} passe(s)')
        window._rows[first.id].w_eye.click()
        app.processEvents()
        check('œil rouvert : elle revient', first.visible)

        check('exports répétés : trois façons de nommer',
              len(session.EXPORT_NAMING) == 3
              and session.export_naming() in {k for k, _, _
                                              in session.EXPORT_NAMING},
              session.export_naming())

        from engrave import model as _model_libre
        check('cœur libre : ni process par matière ni relevé d\'atelier',
              _model_libre.MATERIAL_RECIPES == ()
              and _model_libre.factory_recipes() == PRESET_RECIPES
              and all(r.tool_number == 1 for r in PRESET_RECIPES),
              f'{len(PRESET_RECIPES)} préréglages neutres, outil 1')

        # F2 : positionner le centre
        from engrave.resize import ResizeDialog, selection_center
        target = window.document.shapes[0]
        dialog = ResizeDialog(window, [target])
        dialog.w_move.setChecked(True)
        dialog.c_x.setValue(-12.5)
        dialog.c_y.setValue(6.25)
        dialog.apply()
        centre = selection_center([target])
        check('F2 positionne le centre',
              (round(centre[0], 3), round(centre[1], 3)) == (-12.5, 6.25),
              f'{centre[0]:.3f} · {centre[1]:.3f} mm')
        dialog.deleteLater()

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'essai.taudrive'
            path.write_text(serialize.dumps(window.document), encoding='utf-8')
            reread = serialize.loads(path.read_text(encoding='utf-8'))
            check('document enregistré et relu',
                  len(reread.shapes) == len(window.document.shapes),
                  f'{len(reread.shapes)} forme(s)')
            session.remember_export(tmp)
            check('dossiers d\'export mémorisés', tmp in session.export_folders(),
                  f'{len(session.export_folders())} dossier(s)')

            # le CLJOB doit désigner les ISO là où ils sont écrits : exporter
            # sur un partage réseau suffit, il n'y a rien à recopier
            from engrave.model import Path as PathShape
            network = Document(name='reseau')
            network.add(PathShape(polylines=[[(-5, -5), (5, -5), (5, 5),
                                              (-5, 5), (-5, -5)]],
                                  frame='circle', frame_margin_mm=2,
                                  recipe=PRESET_RECIPES[1]))
            contours = shape_contours(network.shapes[0])
            check('cadre sur un tracé DXF', len(contours) == 2,
                  f'{len(contours)} contour(s)')
            job = [p for p in iso.export(network, tmp)
                   if p.suffix == '.CLJOB'][0].read_text(encoding='utf-8')
            check('export réseau : aucun chemin cl_iso imposé',
                  r'C:\inciwin\cl_iso' not in job
                  and str(pathlib.Path(tmp).resolve()) in job)

            # code ajusté à un cadre, comme sur les plaques de production :
            # une fenêtre de 15 x 7 mm doit accueillir un ECC200 8 x 18 qui la
            # remplit exactement, centré sur le cadre
            from engrave.codeplate import build_plate, frames_of
            from engrave.toolpath import build_shape_pass, code_size, shape_extent
            code_frame = Rect(width=15, height=7, x=3, y=-2)
            text_frame = Rect(width=8.071, height=1.538, x=3, y=-7)
            first, second = frames_of([code_frame, text_frame])
            made = build_plate(PRESET_RECIPES[1], frame=first, text_frame=second,
                               data='B000174', dm_shape='auto')
            fitted = made[0]
            rows, cols, w_mm, h_mm = code_size(fitted)
            # « au plus juste » doit retrouver seul le 8 x 18 de la plaque de
            # production : c'est la forme qui rend les modules presque carrés
            # dans une fenêtre de 15 x 7 mm
            check('code ajusté à un cadre',
                  (rows, cols, round(w_mm, 6), round(h_mm, 6))
                  == (8, 18, 15.0, 7.0) and (fitted.x, fitted.y) == (3, -2),
                  f'{rows} × {cols} dans {w_mm:g} × {h_mm:g} mm')

            engraved = build_shape_pass(fitted)
            check('code gravé plein', engraved.length_mm() > 100,
                  f'{len(engraved.polylines)} trajectoires · '
                  f'{engraved.length_mm():.0f} mm')

            box = shape_extent(made[1])
            check('texte ajusté à son cadre',
                  len(made) == 2 and box[2] - box[0] <= 8.071 + 1e-6
                  and box[3] - box[1] <= 1.538 + 1e-6,
                  f'{box[2] - box[0]:.2f} × {box[3] - box[1]:.2f} mm')

            check('dossiers par défaut paramétrables',
                  len(session.FOLDER_KINDS) >= 5,
                  ', '.join(k for k, _, _ in session.FOLDER_KINDS))

        # --- onglets et session silencieuse ---

        window.tabs.widget(0).document.name = 'plaque essai'
        window._retitle(window.tabs.widget(0))
        check('onglet renommable', 'plaque essai' in window.tabs.tabText(0),
              window.tabs.tabText(0))
        check('bouton + présent dans la barre d\'onglets',
              window.w_add_tab is not None and window.w_add_tab.isEnabled())

        window._save_session()
        snapshot = session.load_snapshot()
        check('session enregistrée sans rien demander',
              len(snapshot) == window.tabs.count(),
              f'{len(snapshot)} document(s)')
        check('les documents jamais enregistrés y figurent aussi',
              any(not e.get('path') and e.get('document') for e in snapshot))

        # une plaque posée d'un geste, sans dialogue, puis réglée dans les
        # propriétés : c'est le parcours attendu
        window.tabs.setCurrentWidget(workbench)
        before = len(window.document.shapes)
        window._add_code_in_frame()
        app.processEvents()
        added = len(window.document.shapes) - before
        check('plaque posée sans fenêtre modale', added == 2, f'{added} formes')
        # Une plaque codée est un groupe de deux, mais on ne règle jamais les
        # deux ensemble : le formulaire suit l'entité désignée.
        from engrave.model import Code as _Code, Text as _Text
        check('plaque codée : le formulaire suit l' + chr(39) + 'entité désignée',
              window._insp_stack.currentIndex() == 0
              and isinstance(window.inspector._shape, _Code),
              type(window.inspector._shape).__name__)
        _plaque = list(window.document.shapes)[-2:]
        _texte = next(s for s in _plaque if isinstance(s, _Text))
        window.canvas._primary = _texte.id
        window._selection_changed()
        app.processEvents()
        check('plaque codée : désigner le texte ouvre le formulaire du texte',
              window._insp_stack.currentIndex() == 0
              and isinstance(window.inspector._shape, _Text),
              type(window.inspector._shape).__name__)
        window.inspector.lot_asked.emit()
        app.processEvents()
        check('plaque codée : « Voir le lot » rend le formulaire du lot',
              window._insp_stack.currentIndex() == 1
              and '2 formes' in window.lot.w_title.text(),
              window.lot.w_title.text()[:48])
        window.lot.w_primary.click()
        app.processEvents()
        check('le lot ramène aux propriétés de la forme désignée',
              window._insp_stack.currentIndex() == 0
              and isinstance(window.inspector._shape, _Text),
              type(window.inspector._shape).__name__)
        _code_pose = next(s for s in _plaque if isinstance(s, _Code))
        check('DataMatrix : cadre englobant à 0,5 mm, texte nu',
              _code_pose.frame == 'rect'
              and abs(_code_pose.frame_margin_mm - 0.5) < 1e-9
              and _texte.frame == 'none',
              f'code {_code_pose.frame} {_code_pose.frame_margin_mm:g} mm · '
              f'texte {_texte.frame}')
        window.canvas.select(_code_pose.id)
        window._selection_changed()
        app.processEvents()

        # --- molette neutralisée, négatif encadré, préréglages, récents ---

        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from engrave.widgets import Combo, Spin
        from engrave import codepresets
        from engrave.model import Code as CodeShape
        from engrave.toolpath import build_shape_pass

        def wheel():
            return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                               QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                               Qt.NoScrollPhase, False)

        spin = Spin(5.0, 0, 100)
        spin.setFocus()
        app.sendEvent(spin, wheel())
        combo = Combo()
        combo.addItems(['a', 'b', 'c'])
        app.sendEvent(combo, wheel())
        check('la molette ne modifie aucune valeur',
              spin.value() == 5.0 and combo.currentIndex() == 0,
              f'compteur {spin.value():g} · liste {combo.currentIndex()}')

        code = next(s for s in window.document.shapes
                    if isinstance(s, CodeShape))
        positive = build_shape_pass(code).length_mm()
        code.frame = 'rect'
        code.frame_margin_mm = 1.0
        negative = build_shape_pass(code).length_mm()
        check('cadre englobant : gravure en négatif', negative > positive,
              f'{positive:.0f} → {negative:.0f} mm')

        preset = codepresets.from_code('essai', code, text_w_mm=8.0,
                                       text_h_mm=1.5)
        check('préréglage : tout le formulaire',
              not set(codepresets.FIELDS) - set(preset),
              f'{len(codepresets.FIELDS)} champs')
        check('préréglages disponibles', len(codepresets.library()) >= 3,
              f'{len(codepresets.library())} préréglage(s)')

        import tempfile as _scratch
        folder = _scratch.mkdtemp()
        session.remember_folder('dxf', folder)
        check('chemins récents proposés',
              folder in session.recent_folders('dxf'),
              f"{len(session.recent_folders('dxf'))} chemin(s)")

        corner = window.w_add_tab
        check('bouton nouvel onglet : icône et style',
              corner.width() >= 40 and not corner.icon().isNull()
              and 'QToolButton' in corner.styleSheet(),
              f'{corner.width()}×{corner.height()} px')

        # il doit suivre le dernier onglet, pas rester au bord de la fenêtre
        window.resize(1400, 880)
        app.processEvents()
        for _ in range(3):
            window._place_add_tab()
            app.processEvents()
        bar = window.tabs.tabBar()
        from PySide6.QtCore import QPoint as _QPoint
        fin = bar.mapTo(window.tabs, _QPoint(bar.tabRect(bar.count() - 1).right(),
                                             0)).x()
        check('bouton collé au dernier onglet',
              corner.parent() is window.tabs and 0 <= corner.x() - fin <= 12,
              f'onglet finit à {fin} px, bouton à {corner.x()} px')

        before_tabs = window.tabs.count()
        corner.click()
        app.processEvents()
        check('le bouton ouvre bien un onglet',
              window.tabs.count() == before_tabs + 1,
              f'{before_tabs} → {window.tabs.count()}')

        # un poste débranché ne doit pas figer l'application : la sonde d'accès
        # est bornée dans le temps, et l'historique n'est pas purgé
        ghost = r'\\POSTE-QUI-N-EXISTE-PAS-999\partage'
        import time as _clock
        started = _clock.perf_counter()
        reach = session.reachable(ghost)
        elapsed = _clock.perf_counter() - started
        check('partage absent : réponse immédiate',
              not reach and elapsed < 5.0, f'{elapsed:.2f} s')
        session.remember_export(ghost)
        check('l\'historique garde le chemin hors ligne',
              ghost in session.export_folders())

        # --- coupon d'essai ---------------------------------------------------

        from engrave import coupon
        from engrave.model import RECIPE_LIBRARY
        base = RECIPE_LIBRARY[0] if RECIPE_LIBRARY else PRESET_RECIPES[1]
        dialog = coupon.CouponDialog(window, base, list(RECIPE_LIBRARY))
        grid = dialog.shapes()
        cases = [s for s in grid if isinstance(s, Rect)]
        recettes = {s.recipe.name for s in cases}
        check('coupon : un process par case',
              len(cases) >= 4 and len(recettes) == len(cases),
              f'{len(cases)} cases, {len(recettes)} process')
        check('coupon : valeurs arrondies pour être recopiables',
              coupon.steps(40000, 200000, 4, 'speed_mm_min')
              == [40000.0, 93500.0, 146500.0, 200000.0],
              coupon.steps(40000, 200000, 4, 'speed_mm_min'))
        span = coupon.extent(grid)
        check('coupon : tient dans le champ',
              span is not None and span[2] - span[0] <= 110
              and span[3] - span[1] <= 110,
              f'{span[2] - span[0]:.1f} × {span[3] - span[1]:.1f} mm')
        check('coupon : étiquettes gravées à faible puissance',
              all(s.recipe.power_percent <= 25 for s in grid
                  if isinstance(s, Text)))
        dialog.deleteLater()

        check('coupon : action offerte dans la barre d\'outils',
              any(action.text().startswith('Coupon')
                  for action, *_ in window._actions))

        # Un coupon est groupé pour se déplacer d'un bloc, mais ses cases
        # portent volontairement des recettes différentes : éditer l'une ne
        # doit pas écraser les autres.
        import dataclasses as _dc
        coupon_doc = Document(name='coupon')
        for forme in grid:
            coupon_doc.add(forme)
        coupon_doc.group([s.id for s in grid])
        tab_c = window.new_tab(coupon_doc)
        app.processEvents()
        boites = [s for s in coupon_doc.shapes if isinstance(s, Rect)]
        avant = len({s.recipe for s in boites})
        boites[0].recipe = _dc.replace(boites[0].recipe, power_percent=42.0,
                                       name='case retouchée')
        window._shape_edited(boites[0].id)
        app.processEvents()
        check('coupon : éditer une case n\'écrase pas les autres',
              len({s.recipe for s in boites}) == avant
              and sum(1 for s in boites if s.recipe.power_percent == 42.0) == 1,
              f'{avant} process distinctes, conservées')

        # …tandis qu'une plaque codée, dont les membres partagent une recette,
        # continue de se régler d'un geste.
        from engrave.codeplate import build_plate as _plate
        plaque = Document(name='plaque')
        for forme in _plate(PRESET_RECIPES[1]):
            plaque.add(forme)
        plaque.group([s.id for s in plaque.shapes])
        window.new_tab(plaque)
        app.processEvents()
        premier = plaque.shapes[0]
        premier.recipe = _dc.replace(premier.recipe, power_percent=33.0)
        window._shape_edited(premier.id)
        app.processEvents()
        check('plaque codée : la process suit tout le groupe',
              all(s.recipe.power_percent == 33.0 for s in plaque.shapes),
              f'{len(plaque.shapes)} formes')

        # Un coupon exporté doit tenir dans le moule des fichiers machine :
        # même alphabet, mêmes conventions de nommage. C'est ce contrôle qui
        # aurait attrapé le `·`, le `/` et les espaces des noms de fichiers.
        import collections as _col
        with tempfile.TemporaryDirectory() as tmp:
            essai = Document(name='Coupon Balayage  Pz0.1')
            for forme in grid:
                essai.add(forme)
            produits = iso.export(essai, tmp)
            noms = [f.name for f in produits]
            alphabet = _col.Counter()
            for f in produits:
                if f.suffix.upper() == '.ISO':
                    alphabet.update(f.read_text(encoding='ascii'))
            speciaux = {c for c in alphabet
                        if not c.isalnum() and c not in '\r\n'}
            hors = speciaux - set(' (),-.:=_')
            octets = max(max(f.read_bytes()) for f in produits)
            check('export : alphabet ISO identique à celui de la machine',
                  not hors and octets < 128,
                  ''.join(sorted(hors)) or f'octet max {octets}')
            check('export : noms de fichiers sans espace ni point interne',
                  not any(' ' in n or n.count('.') > 1 for n in noms),
                  noms[0])

        # Les réglages du coupon sont retenus d'une fois sur l'autre.
        session.remember_coupon(cell_mm=11.0, x_count=3)
        memoire = session.coupon_defaults()
        check('coupon : réglages mémorisés',
              memoire['cell_mm'] == 11.0 and memoire['x_count'] == 3,
              f"case {memoire['cell_mm']} mm · {memoire['x_count']} colonnes")

        # Paramètres fixes : ce qui ne varie pas doit se régler quand même.
        simple = coupon.CouponDialog(window, base, list(RECIPE_LIBRARY),
                                     expert=False)
        savant = coupon.CouponDialog(window, base, list(RECIPE_LIBRARY),
                                     expert=True)
        check('coupon : fréquence et impulsion réservées à l\'expert',
              not {'frequency_khz', 'pulse_width_ns'} & set(simple.w_fixed._rows)
              and {'frequency_khz', 'pulse_width_ns'} <= set(savant.w_fixed._rows),
              f'{len(simple.w_fixed._rows)} champs en simple, '
              f'{len(savant.w_fixed._rows)} en expert')
        check('coupon : axes experts absents du mode simple',
              not {'frequency_khz', 'pulse_width_ns'} & {
                  simple.w_x.w_field.itemData(i)
                  for i in range(simple.w_x.w_field.count())})

        savant.w_x.w_field.setCurrentIndex(
            savant.w_x.w_field.findData('power_percent'))
        savant.w_y.w_field.setCurrentIndex(savant.w_y.w_field.findData(''))
        # la saisie est en m/min, le modèle en mm/min
        savant.w_fixed._rows['speed_mm_min'][0].setValue(62.5)
        savant.w_fixed._rows['pulse_width_ns'][0].setValue(42)
        cellules = [s for s in savant.shapes() if isinstance(s, Rect)]
        check('coupon : les paramètres fixes s\'appliquent à toutes les cases',
              {s.recipe.speed_mm_min for s in cellules} == {62500.0}
              and {s.recipe.pulse_width_ns for s in cellules} == {42}
              and len({s.recipe.power_percent for s in cellules}) > 1,
              f'{len(cellules)} cases')
        check('coupon : un paramètre porté par un axe se grise',
              not savant.w_fixed._rows['power_percent'][0].isEnabled()
              and 'axe X' in savant.w_fixed._rows['power_percent'][1].text(),
              savant.w_fixed._rows['power_percent'][1].text())
        check('coupon : le formulaire se rejoue à l\'identique',
              set(savant.settings()) >= {'x_field', 'y_field', 'fixed',
                                         'cell_mm', 'recipe'},
              ', '.join(sorted(savant.settings())))
        simple.deleteLater()
        savant.deleteLater()

        # Le document retient son formulaire : le coupon se rouvre et se refait.
        portee = Document(name='coupon')
        portee.coupon = savant.settings()
        relu = serialize.document_from_dict(serialize.document_to_dict(portee))
        check('coupon : les réglages survivent à l\'enregistrement',
              relu.coupon.get('x_field') == 'power_percent'
              and relu.coupon.get('fixed', {}).get('pulse_width_ns') == 42,
              f"{len(relu.coupon)} clés")

        # --- presse-papiers, onglets, barre d'état ------------------------------

        atelier = window.new_tab()
        app.processEvents()
        atelier.document.add(Rect(width=20, height=10, recipe=PRESET_RECIPES[1]))
        atelier.document.add(Rect(x=15, width=8, height=8,
                                  recipe=PRESET_RECIPES[1]))
        atelier.reload()
        window._refresh_list()
        identifiants = [s.id for s in atelier.document.shapes]
        window.canvas.select_many(identifiants)
        window._group()
        origine = atelier.document.shapes[0].group
        window._copy()
        window._paste()
        app.processEvents()
        colles = window.canvas.selected_shapes()
        check('copier / coller : la copie se pose au même endroit',
              len(atelier.document.shapes) == 4
              and sorted((round(s.x, 3), round(s.y, 3)) for s in colles)
              == [(0.0, 0.0), (15.0, 0.0)],
              f'{len(atelier.document.shapes)} formes')
        check('copier / coller : le groupe collé est neuf et séparé',
              colles[0].group not in ('', origine)
              and len(atelier.document.group_members(colles[0].id)) == 2
              and len(atelier.document.group_members(identifiants[0])) == 2,
              f'{origine} → {colles[0].group}')

        ailleurs = window.new_tab()
        app.processEvents()
        window._paste()
        app.processEvents()
        check('copier / coller : d\'un onglet à l\'autre',
              len(ailleurs.document.shapes) == 2,
              f'{len(ailleurs.document.shapes)} forme(s) dans l\'onglet voisin')

        avant_onglets = window.tabs.count()
        window._duplicate_tab(window.tabs.indexOf(atelier))
        app.processEvents()
        copie_onglet = window.canvas
        check('clic droit : dupliquer l\'onglet',
              window.tabs.count() == avant_onglets + 1
              and len(copie_onglet.document.shapes)
              == len(atelier.document.shapes)
              and not ({s.id for s in copie_onglet.document.shapes}
                       & {s.id for s in atelier.document.shapes}),
              copie_onglet.document.name)

        window._flash_status('essai', True)
        vert = theme.current().ok in window.statusBar().styleSheet()
        window._flash_status('essai', False)
        rouge = theme.current().alarm in window.statusBar().styleSheet()
        window._clear_flash()
        check('barre d\'état : verte à la réussite, rouge à l\'échec',
              vert and rouge and window.statusBar().styleSheet() == '',
              f'{theme.current().ok} / {theme.current().alarm}')

        check('bouton Process entre la liste et la process',
              window.w_recipes_button.text().strip().startswith('Process'),
              window.w_recipes_button.toolTip()[:40])

        gestion = recipes.RecipeManager(window)
        etiquettes = gestion.labels()
        check('process : passes et profondeur lisibles dans la liste',
              any('passes de' in e for e in etiquettes),
              next((e for e in etiquettes if 'passes de' in e), '—'))
        check('process : renommer, passes et profondeur dans l\'éditeur',
              all(hasattr(gestion, n) for n in
                  ('w_name', 'w_passes', 'w_depth_step', 'w_depth_total',
                   'w_depth_mode')))
        gestion.deleteLater()

        # --- hachurer / filaire au clavier -------------------------------------

        plein = Rect(width=10, height=10, recipe=PRESET_RECIPES[4])   # hachuré
        vide = Rect(x=20, width=10, height=10, recipe=PRESET_RECIPES[1])
        atelier.document.add(plein)
        atelier.document.add(vide)
        window.tabs.setCurrentWidget(atelier)
        atelier.reload()
        window._refresh_list()
        pas_origine = plein.recipe.hatch_mm
        window.canvas.select_many([plein.id, vide.id])
        window._set_outline()
        app.processEvents()
        check('Ctrl+F : la sélection passe en filaire',
              plein.recipe.hatch_mm == 0 and vide.recipe.hatch_mm == 0,
              f'{pas_origine} mm → 0')
        window._set_hatched()
        app.processEvents()
        check('Ctrl+H : le pas retiré est rendu, pas remplacé',
              plein.recipe.hatch_mm == pas_origine
              and vide.recipe.hatch_mm == window.HATCH_DEFAULT_MM,
              f'{plein.recipe.hatch_mm} mm rendu · '
              f'{vide.recipe.hatch_mm} mm par défaut')

        # --- vitesses en m/min --------------------------------------------------

        from engrave.model import SPEED_TO_DISPLAY, SPEED_UNIT
        # --- process enregistrees : rien ne se perd --------------------------
        #
        # La bibliotheque du poste portait des process sans remplissage
        # complet ni oscillation : le gestionnaire n avait pas de widget
        # pour eux, alors que la colonne 1 les offrait sur la forme. Deux
        # formulaires pour le meme objet ne peuvent pas montrer deux
        # choses differentes.
        import dataclasses as _dc_pr
        _g_pr = recipes.RecipeManager(window)
        _r_pr = _dc_pr.replace(
            PRESET_RECIPES[0], name='Essai osc', folder='Client B',
            hatch_mm=0.04, hatch_angle_deg=30.0, hatch_angle_step_deg=45.0,
            hatch_cross=True, hatch_inset_mm=0.015,
            wobble='circle', wobble_amp_mm=0.15, wobble_pitch_mm=0.1)
        _g_pr.recipes = [_r_pr]
        _g_pr._refresh_list(select=0)
        _g_pr.select_row(0)
        _lu = _g_pr.recipes[0]
        check('process : le remplissage complet est dans le formulaire',
              _g_pr.w_hstep.value() == 45.0 and _g_pr.w_hcross.isChecked()
              and abs(_g_pr.w_hinset.value() - 0.015) < 1e-9,
              'rotation par passe, croisement et retrait')

        check('process : l oscillation est dans le formulaire',
              _g_pr.w_wob.currentData() == 'circle'
              and abs(_g_pr.w_wamp.value() - 0.15) < 1e-9
              and abs(_g_pr.w_wpitch.value() - 0.1) < 1e-9,
              'la machine ne l offre pas : elle se grave dans la geometrie')

        # ce que le formulaire ecrit doit revenir intact du disque
        _g_pr.w_hcross.setChecked(False)
        _g_pr.w_wamp.setValue(0.22)
        _apres = _g_pr.recipes[0]
        _tour = recipes.recipe_from_dict(recipes.recipe_to_dict(_apres))
        check('process : ce qui est saisi survit a l enregistrement',
              _tour.wobble == 'circle'
              and abs(_tour.wobble_amp_mm - 0.22) < 1e-9
              and _tour.hatch_cross is False
              and abs(_tour.hatch_inset_mm - 0.015) < 1e-9,
              '21 champs ecrits, 21 relus')

        check('process : le resume dit le remplissage et l oscillation',
              'osc' in _g_pr.labels()[0] and 'rempli' in _g_pr.labels()[0],
              _g_pr.labels()[0])

        # --- rangement par dossier, repliable --------------------------------
        _g_pr.recipes = [
            _dc_pr.replace(PRESET_RECIPES[0], name='Sans dossier', folder=''),
            _dc_pr.replace(PRESET_RECIPES[0], name='A', folder='Client B'),
            _dc_pr.replace(PRESET_RECIPES[0], name='B', folder='Client B'),
            _dc_pr.replace(PRESET_RECIPES[0], name='C', folder='Client A'),
        ]
        _g_pr._refresh_list()
        check('process : rangees par dossier, la racine en tete',
              _g_pr.folders() == ['Client A', 'Client B']
              and len(_g_pr.labels()) == 4
              and _g_pr.w_list.topLevelItem(0).text(0).startswith('Sans'),
              'une process sans dossier est le cas courant : l enterrer '
              'sous les rangements la rendrait plus dure a trouver')

        _zod = next(_g_pr.w_list.topLevelItem(i)
                    for i in range(_g_pr.w_list.topLevelItemCount())
                    if _g_pr.w_list.topLevelItem(i).text(0).startswith('Client B'))
        check('process : un dossier annonce ce qu il contient',
              '(2)' in _zod.text(0) and _zod.childCount() == 2,
              _zod.text(0))

        _zod.setExpanded(False)
        _g_pr._fold_changed(_zod)
        _g_pr._refresh_list()
        _zod2 = next(_g_pr.w_list.topLevelItem(i)
                     for i in range(_g_pr.w_list.topLevelItemCount())
                     if _g_pr.w_list.topLevelItem(i).text(0).startswith('Client B'))
        check('process : un dossier replie le reste apres rechargement',
              not _zod2.isExpanded(),
              'sinon regler une process rouvrirait tout a chaque frappe')

        # --- compatibilite avec le poste de production -----------------------
        #
        # Le poste de production porte des process d un format anterieur,
        # sans les sept champs ajoutes depuis. Elles doivent se relire, et
        # ce qu on ecrit doit rester lisible par la version qui tourne
        # la-bas.
        _ancien = {
            'name': 'Similicuir', 'comment': '', 'depth_mode': 'step',
            'depth_step_mm': 0.004673, 'depth_total_mm': 0.0,
            'folder': 'Test', 'frequency_khz': 200.0, 'hatch_angle_deg': 0.0,
            'hatch_mm': 0.0, 'passes': 1, 'power_percent': 55.0,
            'pulse_width_ns': 20, 'speed_mm_min': 10000.0,
            'tool_number': 62, 'treatment': None,
        }
        _relu = recipes.recipe_from_dict(_ancien)
        check('process : un fichier d avant se relit, valeurs neutres',
              _relu.name == 'Similicuir' and _relu.wobble == 'none'
              and _relu.hatch_cross is False and _relu.hatch_inset_mm == 0.0
              and _relu.hatch_angle_step_deg == 0.0
              and _relu.link_paths is False
              and _relu.fill_style == 'hatch',
              'les champs absents prennent la valeur qui ne change rien')

        _reecrit = recipes.recipe_to_dict(_relu)
        _vu_par_ancien = {k: v for k, v in _reecrit.items() if k in _ancien}
        check('process : ce qu on ecrit reste lisible par l ancienne version',
              _vu_par_ancien == _ancien
              and set(_reecrit) - set(_ancien) == {
                  'hatch_angle_step_deg', 'hatch_cross', 'hatch_inset_mm',
                  'link_paths', 'fill_style',
                  'wobble', 'wobble_amp_mm', 'wobble_pitch_mm'},
              'huit champs ajoutes, ignores par un lecteur qui les ignore ; '
              'les quinze autres a l identique')

        gestion_v = recipes.RecipeManager(window)
        gestion_v.select_row(1)
        app.processEvents()
        modele = gestion_v.recipes[1].speed_mm_min
        check('vitesses saisies et affichées en m/min',
              abs(gestion_v.w_speed.value() - modele * SPEED_TO_DISPLAY) < 1e-9
              and gestion_v.w_speed._unit.text() == SPEED_UNIT,
              f'{gestion_v.w_speed.value():g} {SPEED_UNIT} = {modele:g} mm/min')
        gestion_v.w_speed.setValue(120.0)
        gestion_v._edited()
        check('m/min saisis, mm/min dans le modèle et l\'ISO',
              gestion_v.recipes[1].speed_mm_min == 120000.0,
              f'{gestion_v.recipes[1].speed_mm_min:g} mm/min')
        gestion_v.deleteLater()

        # --- options du coupon, activables une à une ----------------------------

        def _coupon_parts(**options):
            formes = coupon.build(PRESET_RECIPES[1], x_count=3, y_count=2,
                                  **options)
            return (len([s for s in formes if isinstance(s, Rect)]),
                    len([s for s in formes if isinstance(s, Text)]))

        tout = _coupon_parts()
        check('coupon : titre et étiquettes se coupent séparément',
              _coupon_parts(show_title=False)[1] == tout[1] - 1
              and _coupon_parts(show_x_labels=False)[1] == tout[1] - 3
              and _coupon_parts(show_y_labels=False)[1] == tout[1] - 2
              and _coupon_parts(show_title=False, show_x_labels=False,
                                show_y_labels=False) == (tout[0], 0),
              f'{tout[0]} cases, {tout[1]} textes tout coché')

        pleines = coupon.build(PRESET_RECIPES[1], x_count=2, y_count=1,
                               hatched=True, labels_hatched=False)
        filaires = coupon.build(PRESET_RECIPES[1], x_count=2, y_count=1,
                                hatched=False, labels_hatched=True)
        check('coupon : cases et étiquettes se hachurent indépendamment',
              {s.recipe.hatch_mm for s in pleines if isinstance(s, Rect)} == {0.05}
              and {s.recipe.hatch_mm for s in pleines
                   if isinstance(s, Text)} == {0.0}
              and {s.recipe.hatch_mm for s in filaires
                   if isinstance(s, Rect)} == {0.0}
              and {s.recipe.hatch_mm for s in filaires
                   if isinstance(s, Text)} == {0.05})

        ecran = app.primaryScreen().availableGeometry()
        for mode in (False, True):
            forme_dlg = coupon.CouponDialog(window, base, list(RECIPE_LIBRARY),
                                            expert=mode)
            forme_dlg.show()
            app.processEvents()
            tient = (forme_dlg.height() <= ecran.height()
                     and forme_dlg.width() <= ecran.width())
            check(f'coupon : la fenêtre tient sur l\'écran '
                  f'({"expert" if mode else "simple"})', tient,
                  f'{forme_dlg.width()}×{forme_dlg.height()} px pour '
                  f'{ecran.width()}×{ecran.height()}')
            forme_dlg.close()
            forme_dlg.deleteLater()

        etiquettes = [s.text for s in coupon.build(
            PRESET_RECIPES[1], x_field='speed_mm_min', x_from=40000,
            x_to=80000, x_count=2, y_field='') if isinstance(s, Text)]
        check('coupon : les vitesses gravées sont en m/min',
              '40' in etiquettes and '80' in etiquettes,
              ' · '.join(etiquettes[:3]))

        # --- journal des exports ------------------------------------------------

        from engrave import journal
        import dataclasses as _dcj
        doc_j = Document(name='Plaque journal')
        doc_j.add(Rect(width=20, height=10, recipe=PRESET_RECIPES[1]))
        etat1 = journal.snapshot(doc_j)
        doc_j.shapes[0].recipe = _dcj.replace(PRESET_RECIPES[1],
                                              power_percent=60.0, passes=3)
        doc_j.add(Rect(x=30, width=5, height=5, recipe=PRESET_RECIPES[3]))
        etat2 = journal.snapshot(doc_j, optimize=True)
        ecarts = journal.differences(etat1, etat2)
        check('journal : les modifications de paramètres sont relevées',
              any('puissance' in e for e in ecarts)
              and any('passes' in e for e in ecarts)
              and any('Satinage' in e for e in ecarts),
              f'{len(ecarts)} modification(s)')
        with tempfile.TemporaryDirectory() as tmp:
            journal.append(tmp, doc_j.name,
                           journal.render(etat1, [], rang=1, dossier='a',
                                          fichiers=3))
            cible = journal.append(tmp, doc_j.name,
                                   journal.render(etat2, ecarts, rang=2,
                                                  dossier='a-02', fichiers=5))
            texte = cible.read_text(encoding='ascii')
            check('journal : deux exports, horodatés, dans un seul fichier',
                  texte.count('Export n') == 2
                  and 'MODIFICATIONS' in texte
                  and max(texte.encode('ascii', 'replace')) < 128,
                  cible.name)

        # --- recette : commentaire et enregistrement ----------------------------

        from engrave.model import RECIPE_LIBRARY as _LIB
        forme_r = Rect(width=12, height=8,
                       recipe=_dcj.replace(PRESET_RECIPES[1],
                                           name='Essai autotest',
                                           power_percent=71.0,
                                           comment='laiton 2 mm, coupon du jour'))
        atelier.document.add(forme_r)
        atelier.reload()
        window._refresh_list()
        window.canvas.select(forme_r.id)
        app.processEvents()
        check('process : le commentaire est visible et éditable',
              window.recipe.w_comment.text() == 'laiton 2 mm, coupon du jour',
              window.recipe.w_comment.text())
        check('process : le commentaire grandit avec le texte',
              window.recipe.w_comment.height() > 0
              and hasattr(window.recipe.w_comment, 'MAX_LINES'))
        avant_lib = len(_LIB)
        window.recipe._save_recipe()
        app.processEvents()
        rangee = next((p for p in _LIB if p.name == 'Essai autotest'), None)
        check('process : le bouton la range dans la bibliothèque',
              rangee is not None and rangee.power_percent == 71.0
              and rangee.comment.startswith('laiton'),
              f'{avant_lib} → {len(_LIB)} process')
        window.recipe.w_power.setValue(44.0)
        app.processEvents()
        window.recipe._save_recipe()
        app.processEvents()
        # Créer, jamais écraser : l'ancienne reste, la nouvelle prend un rang.
        check('process : réenregistrer crée, n\'écrase pas',
              next(p for p in _LIB
                   if p.name == 'Essai autotest').power_percent == 71.0
              and any(p.name == 'Essai autotest 2' and p.power_percent == 44.0
                      for p in _LIB),
              ', '.join(p.name for p in _LIB if p.name.startswith('Essai')))

        # --- traitement d'un dessin ---------------------------------------------

        from PySide6.QtWidgets import QDialog as _QDialog
        from engrave import treatment
        from engrave.treatment import TreatmentDialog
        onglet_t = window.new_tab()
        app.processEvents()
        dessin = Rect(width=24, height=16, recipe=PRESET_RECIPES[1])
        onglet_t.document.add(dessin)
        onglet_t.reload()
        window._refresh_list()
        window.canvas.select(dessin.id)
        app.processEvents()
        x_avant = dessin.x
        TreatmentDialog.exec = lambda self: _QDialog.DialogCode.Accepted
        window._treat()
        app.processEvents()
        copie = window.canvas.selected_shapes()[0]
        check('traitement : copie en place, original masqué sans bouger',
              len(onglet_t.document.shapes) == 2 and copie.x == x_avant
              and dessin.x == x_avant and not dessin.visible
              and copie.visible,
              f'original reste à x {dessin.x:g} mm, masqué')
        check('traitement : la copie reçoit cadre, marge et offset',
              copie.frame == 'rect' and copie.frame_margin_mm > 0,
              f'cadre {copie.frame}, marge {copie.frame_margin_mm:g} mm')
        essai_t = TreatmentDialog(window, [copie])
        essai_t.w_offset.setValue(0.15)
        essai_t.w_double.click()
        check('traitement : le bouton donne 2 × l\'offset',
              abs(essai_t.w_width.value() - 0.30) < 1e-9,
              f'{essai_t.w_width.value():g} mm pour un offset de 0,15')
        essai_t.deleteLater()

        # --- magasin d'outils de la machine -------------------------------------

        from engrave import toolstore
        chemin_mag, nature_mag = toolstore.source()
        outils_mag = toolstore.tools()
        check('magasin d\'outils : lisible', bool(outils_mag),
              f'{len(outils_mag)} outils ({nature_mag})')
        if outils_mag:
            recette_mag = outils_mag[0].to_recipe(PRESET_RECIPES[1])
            check('magasin : un outil se charge dans une process',
                  recette_mag.tool_number == outils_mag[0].number
                  and recette_mag.passes == PRESET_RECIPES[1].passes,
                  f'T{recette_mag.tool_number} · passes et profondeur intactes')
        check('magasin : jamais écrit, et la raison est donnée',
              toolstore.writable()[0] is False
              and '12 411' in toolstore.writable()[1],
              toolstore.writable()[1][:48] + '…')

        # --- modèles de traitement, figés dans les recettes ---------------------

        from engrave.model import Treatment
        modeles = treatment.templates()
        check('traitement : des modèles sont proposés', len(modeles) >= 4,
              ', '.join(m.name for m in modeles[:3]) + '…')

        mien = Treatment('Autotest relief', 'rect', 1.5, 0.12, 0.24, 0.05)
        treatment.store_template(mien)
        check('traitement : un modèle se range et se relit',
              any(m == mien for m in treatment.templates()), mien.name)

        recette_t = _dcj.replace(PRESET_RECIPES[1], name='Avec traitement',
                                 treatment=mien)
        relue = serialize.document_from_dict(serialize.document_to_dict(
            Document(shapes=[Rect(width=10, height=10, recipe=recette_t)])))
        check('traitement : la process le garde à l\'enregistrement',
              relue.shapes[0].recipe.treatment == mien,
              str(relue.shapes[0].recipe.treatment.name))

        treatment.drop_template(mien.name)
        check('traitement : supprimer le modèle ne casse pas la process',
              not any(m.name == mien.name for m in treatment.templates())
              and recette_t.treatment == mien,
              'valeurs figées, pas un renvoi')

        forme_t = Rect(width=20, height=12, recipe=PRESET_RECIPES[1])
        treatment.apply_treatment([forme_t], mien)
        check('traitement : la process l\'applique au dessin',
              forme_t.frame == 'rect' and forme_t.frame_offset_mm == 0.12
              and forme_t.line_width_mm == 0.24,
              f'cadre {forme_t.frame}, offset {forme_t.frame_offset_mm:g} mm')

        # --- panneaux ancrés, plus de fenêtre modale ----------------------------

        from PySide6.QtCore import Qt as _Qt2
        from PySide6.QtWidgets import QDialog as _QD, QGroupBox as _QGroupBox
        check('process : panneau, pas une fenêtre',
              not isinstance(window.recipes_panel, _QD)
              and window.center.indexOf(window.recipes_panel) == 1,
              type(window.recipes_panel).__name__)
        check('magasin : panneau ancré en colonne 3',
              not isinstance(window.tools_panel, _QD)
              and window.dockWidgetArea(window._dock_tools)
              == _Qt2.RightDockWidgetArea,
              f'{window.tools_panel.w_list.count()} outils listés')

        window._manage_recipes()
        app.processEvents()
        check('process : la commande prend les colonnes 2 et 3',
              window.center.currentIndex() == 1
              and not window._dock_insp.isVisible()
              and window._dock_tools.isVisible(),
              'gestionnaire au centre, magasin à droite')

        # le magasin sert aussi en mode simple : il ne fait que lire
        check('magasin : disponible hors mode expert',
              not recipes.expert() and window.tools_panel.isEnabled()
              and window.tools_panel.w_load.isEnabled())
        window.recipes_panel.select_row(1)
        window.recipes_panel._row_changed(1)
        avant_outil = window.recipes_panel.recipes[1]
        window.tools_panel.w_list.setCurrentRow(
            min(9, window.tools_panel.w_list.count() - 1))
        window.tools_panel._take()
        app.processEvents()
        apres_outil = window.recipes_panel.recipes[1]
        check('magasin : charge dans la process, nom conservé',
              apres_outil.name == avant_outil.name
              and apres_outil.tool_number != avant_outil.tool_number
              and apres_outil.passes == avant_outil.passes,
              f'T{avant_outil.tool_number} → T{apres_outil.tool_number}')
        check('magasin : plus de bouton d\'explication',
              not hasattr(window.tools_panel, 'w_why'))

        window.recipes_panel._save()
        app.processEvents()
        check('process : enregistrer ne quitte pas le réglage',
              window.center.currentIndex() == 1)
        window.recipes_panel.w_done.click()
        app.processEvents()
        check('process : « Terminé » rend les colonnes au dessin',
              window.center.currentIndex() == 0
              and window._dock_insp.isVisible()
              and not window._dock_tools.isVisible())

        titres = [g.title() for g in window.recipe.findChildren(_QGroupBox)]
        check('colonne 1 : le titre Process laser n\'est écrit qu\'une fois',
              not any('Process laser' in t for t in titres),
              ', '.join(t for t in titres if t) or 'aucun titre répété')

        # --- liste des formes : renommer, réordonner ----------------------------

        onglet_l = window.new_tab()
        app.processEvents()
        for rang in range(3):
            onglet_l.document.add(Rect(width=10 + rang, height=8,
                                       recipe=PRESET_RECIPES[1],
                                       name=f'forme {rang}'))
        onglet_l.reload()
        window._refresh_list()
        app.processEvents()
        ids_l = [s.id for s in onglet_l.document.shapes]
        window._reorder(ids_l[2], -1)
        ordre = [s.display_name() for s in onglet_l.document.shapes]
        window._reorder(ids_l[2], 1)
        check('liste : monter et descendre une forme',
              ordre == ['forme 0', 'forme 2', 'forme 1']
              and [s.display_name() for s in onglet_l.document.shapes]
              == ['forme 0', 'forme 1', 'forme 2'],
              ' → '.join(ordre))
        check('liste : au bout, on ne bouge plus',
              not onglet_l.document.move_shape(ids_l[0], -1))
        onglet_l.document.get(ids_l[0]).name = 'renommée'
        window._relabel_list()
        check('liste : le nom se lit après renommage',
              'renommée' in window.shape_list.itemWidget(
                  window.shape_list.item(0)).w_label.text())

        # --- onglets fermés, retrouvés au mot-clé -------------------------------

        from engrave.closedtabs import ClosedTabs
        session.forget_closed()
        doc_ferme = Document(name='Plaque client X')
        doc_ferme.add(Text(text='B000174', size_mm=4,
                           recipe=PRESET_RECIPES[1]))
        onglet_f = window.new_tab(doc_ferme)
        app.processEvents()
        window._close_tab(window.tabs.indexOf(onglet_f))
        app.processEvents()
        fermes = session.closed_tabs()
        check('onglets fermés : conservés avec leur contenu',
              any(e['name'] == 'Plaque client X' for e in fermes)
              and 'B000174' in session.read_closed(fermes[0]),
              f'{len(fermes)} onglet(s) retenu(s)')
        import datetime as _dt
        check('onglets fermés : archivés par semaine « 26s34 »',
              session.week_folder(_dt.datetime(2026, 8, 21)) == '26s34'
              and fermes[0].get('week') == session.week_folder()
              and session.week_folder() in fermes[0].get('file', ''),
              fermes[0].get('week', ''))
        check('onglets fermés : aucun plafond, filtre par semaine',
              not hasattr(session, 'MAX_CLOSED')
              and session.search_closed('', session.week_folder())
              and not session.search_closed('', '99s99'),
              f'{len(session.closed_weeks())} semaine(s) archivée(s)')
        check('onglets fermés : recherche sur le nom **et** le contenu',
              [e['name'] for e in session.search_closed('B000174')]
              == ['Plaque client X']
              and [e['name'] for e in session.search_closed('client')]
              == ['Plaque client X']
              and not session.search_closed('zzz'),
              'mot-clé dans le texte gravé')
        fenetre_f = ClosedTabs(window)
        check('onglets fermés : la fenêtre liste et résume',
              fenetre_f.w_list.count() >= 1
              and 'B000174' in fenetre_f.w_list.item(0).text(),
              fenetre_f.w_list.item(0).text()[:56] if fenetre_f.w_list.count()
              else '')
        fenetre_f.deleteLater()

        # --- date automatique ---------------------------------------------------

        from engrave import datestamp, variables
        check('date : le bouton porte son menu de formats',
              window.w_date_button.menu() is not None
              and len(window.w_date_button.menu().actions()) >= len(
                  datestamp.FORMATS),
              f'{len(datestamp.FORMATS)} formats proposés')

        import datetime as _dtd
        contexte = variables.make_context(now=_dtd.datetime(2026, 8, 20, 14, 5))
        check('date : le format s\'applique au champ variable',
              variables.expand('{date:%y%m%d}', contexte) == '260820'
              and variables.expand('{date:%d/%m/%y}', contexte) == '20/08/26'
              and variables.expand('{n:03}', contexte) == '001',
              'aammjj, jj/mm/aa, et les autres champs intacts')

        posee = datestamp.build({'format': '%y%m%d', 'fit': 'height',
                                 'size_mm': 5.0, 'width_mm': 30.0, 'font': ''})
        check('date : posée comme champ variable, pas figée',
              posee.text.startswith('{date:') and posee.size_mm == 5.0,
              posee.text)

        ajustee = datestamp.build({'format': '%d/%m/%y', 'fit': 'width',
                                   'width_mm': 20.0, 'size_mm': 5.0, 'font': ''})
        emprise = shape_extent(ajustee)
        check('date : la taille est calculée sur le rendu réel',
              emprise is not None
              and abs((emprise[2] - emprise[0]) - 20.0) < 0.05,
              f'{emprise[2] - emprise[0]:.2f} mm pour 20 demandés'
              if emprise else 'sans emprise')

        # --- barre d'outils : icônes, annuler en tête, export en évidence ------

        from PySide6.QtCore import Qt as _Qt3
        barre = next(b for b in window.findChildren(type(window.addToolBar('x')))
                     if b.objectName() == 'barre_outils')
        check('barre : les boutons se limitent à leur icône',
              barre.toolButtonStyle() == _Qt3.ToolButtonIconOnly)
        premiers = [a.text() for a in barre.actions() if a.text()][:2]
        from PySide6.QtWidgets import QToolBar as _QToolBar
        _noms_barre = [a.text() for a in window.findChildren(_QToolBar)[0].actions()
                       if a.text()]
        check('barre : grouper et dégrouper juste après annuler-refaire',
              _noms_barre[:4] == ['Annuler', 'Refaire', 'Grouper', 'Dégrouper'],
              ' · '.join(_noms_barre[:4]))
        check('barre : ajuster a quitté la barre pour le plan de travail',
              'Ajuster' not in _noms_barre
              and hasattr(window.canvas, 'w_fit')
              and window.canvas.w_fit.parent() is window.canvas,
              'bouton en surcouche du canevas')
        check('barre : le champ « pas clavier » est étroit',
              window.w_step.width() <= 140,
              f'{window.w_step.width()} px')

        # --- bouton Code : un bouton qui pose, une flèche qui choisit ----------
        from PySide6.QtWidgets import QToolButton as _QTB
        from engrave import barcode as _bc
        _symbos = [a.data() for a in window.w_code_kinds]
        check('code : la flèche du bouton offre toutes les symbologies',
              isinstance(window.w_code_button, _QTB)
              and window.w_code_button.popupMode() == _QTB.MenuButtonPopup
              and _symbos == [v for v, _ in _bc.KINDS],
              ' · '.join(a.text() for a in window.w_code_kinds))
        _coche_avant = [a.data() for a in window.w_code_kinds if a.isChecked()]
        window.w_code_kinds[1].trigger()          # QR Code
        app.processEvents()
        _qr = window.document.shapes[-2]
        check('code : la flèche pose bien la symbologie choisie',
              getattr(_qr, 'kind', '') == 'qr' and _qr.frame == 'none',
              f'{getattr(_qr, "kind", "?")} · cadre {_qr.frame}')
        window._mark_code_kind()
        check('code : la symbologie retenue est cochée dans le menu',
              [a.data() for a in window.w_code_kinds if a.isChecked()] == ['qr']
              and _coche_avant == ['datamatrix'],
              f'avant {_coche_avant} · après '
              f'{[a.data() for a in window.w_code_kinds if a.isChecked()]}')
        window.w_code_kinds[0].trigger()          # on rend la main au DataMatrix
        app.processEvents()
        _dm = window.document.shapes[-2]
        check('code : le DataMatrix revient encadré, le QR non',
              _dm.kind == 'datamatrix' and _dm.frame == 'rect'
              and abs(_dm.frame_margin_mm - 0.5) < 1e-9,
              f'{_dm.frame} {_dm.frame_margin_mm:g} mm')
        for _ in range(4):
            window.document.shapes.pop()          # on ne laisse rien traîner
        window.canvas.reload()
        app.processEvents()
        from PySide6.QtGui import QAction as _QAction
        check('menu Fichier : « dupliquer l' + chr(39) + 'onglet » retiré, il '
              'reste au clic droit',
              not any('upliquer l' in a.text()
                      for a in window.findChildren(_QAction))
              and hasattr(window, '_duplicate_tab'),
              'clic droit sur l' + chr(39) + 'onglet')
        check('barre : annuler et refaire en tête',
              premiers == ['Annuler', 'Refaire'], ' · '.join(premiers))
        check('barre : export large, coloré, avec son triangle',
              window.w_export_button.minimumWidth() >= 190
              and theme.current().ok in window.w_export_button.styleSheet()
              and not window.w_export_button.icon().isNull(),
              f'{window.w_export_button.minimumWidth()} px')

        # --- offset : plus de boucles dans les angles rentrants -----------------

        from engrave import textvec as _tv
        from engrave.toolpath import offset_contours as _off
        import math as _m

        def _dist(p, a, b):
            (ax, ay), (bx, by) = a, b
            dx, dy = bx - ax, by - ay
            carre = dx * dx + dy * dy
            t = 0.0 if carre <= 0 else max(0.0, min(
                1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / carre))
            return _m.hypot(p[0] - (ax + dx * t), p[1] - (ay + dy * t))

        chiffres = _tv.layout('2608', 14.0, '', 'center', 'center', 1.2)
        boucles = 0
        for ecart in (0.3, 0.15, -0.2):
            for poly in _off(chiffres, ecart):
                for a, b in zip(poly, poly[1:]):
                    milieu = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    if min(_dist(milieu, u, v) for c in chiffres
                           for u, v in zip(c, c[1:])) < abs(ecart) * 0.9:
                        boucles += 1
        check('offset : aucune boucle dans les angles rentrants',
              boucles == 0, f'{boucles} segment(s) fautif(s) sur 2608')

        # --- aide en barre d'état, et bascule du gestionnaire -------------------

        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtGui import QEnterEvent, QHelpEvent
        from PySide6.QtWidgets import QToolBar, QToolButton
        from engrave import helpbar

        check('aide : une infobulle de deux lignes tient sur une',
              helpbar.plain('Applique une process à **toutes** les formes.'
                            + chr(10) + '« — » : le lot en porte plusieurs.')
              == 'Applique une process à toutes les formes.' + helpbar.JOIN
              + '« — » : le lot en porte plusieurs.'
              and helpbar.plain('Une ligne <b>grasse</b><br>et sa suite')
              == 'Une ligne grasse' + helpbar.JOIN + 'et sa suite',
              helpbar.plain('a<br>b'))

        def _survoler(widget):
            coin = QPoint(2, 2)
            app.sendEvent(widget, QEnterEvent(coin, coin, coin))
            app.processEvents()
            return window.w_help.help_text()

        aide_bouton = _survoler(window.w_recipes_button)
        check('aide : le survol d' + chr(39) + 'un bouton écrit en barre d'
              + chr(39) + 'état',
              window.w_help is not None
              and 'Gestionnaire de process' in aide_bouton,
              aide_bouton[:56])

        bulle = QHelpEvent(QEvent.ToolTip, QPoint(2, 2),
                           window.w_recipes_button.mapToGlobal(QPoint(2, 2)))
        app.notify(window.w_recipes_button, bulle)
        check('aide : aucune infobulle ne flotte plus',
              bulle.isAccepted(), 'événement consommé')

        app.sendEvent(window.w_recipes_button, QEvent(QEvent.Leave))
        app.processEvents()
        check('aide : la barre se vide quand on quitte le bouton',
              window.w_help.help_text() == '', 'vide')

        window._update_status()
        app.processEvents()
        aide_gardee = _survoler(window.w_recipes_button)
        window._update_status()
        app.processEvents()
        check('aide : les mesures du travail ne l' + chr(39) + 'effacent pas',
              'forme(s)' in window.statusBar().currentMessage()
              and window.w_help.help_text() == aide_gardee
              and aide_gardee != '',
              'zones distinctes')
        check('aide : sa part est bornée, la barre garde ses mesures',
              0 < window.w_help.share_width()
              <= window.statusBar().width() * (helpbar.SHARE + 0.01)
              and window.w_help.share_width() >= helpbar.MIN_WIDTH,
              f'{window.w_help.share_width()} px sur '
              f'{window.statusBar().width()}')
        window._flash_status('essai', True, 0.05)
        app.processEvents()
        eclipse = not window.w_help.isVisible()
        window._clear_flash()
        app.processEvents()
        check('aide : elle s' + chr(39) + 'efface le temps d' + chr(39)
              + 'un éclat de couleur',
              eclipse and window.w_help.isVisible(),
              'masquée puis rendue')

        barre_outils = window.findChildren(QToolBar)[0]
        routes = 0
        for bouton in barre_outils.findChildren(QToolButton):
            if bouton.toolTip() and _survoler(bouton):
                routes += 1
        check('aide : la barre d' + chr(39) + 'outils, en icônes seules, '
              's' + chr(39) + 'explique ainsi',
              routes >= 10, f'{routes} bouton(s) routés')

        depart_p = window.center.currentIndex()
        window.w_recipes_action.trigger()
        app.processEvents()
        ouvert_p = (window.center.currentIndex(),
                    window.w_recipes_action.text(),
                    window._dock_tools.isVisible())
        window.w_recipes_action.trigger()
        app.processEvents()
        check('process : le bouton ouvre **et** referme le gestionnaire',
              depart_p == 0 and ouvert_p == (1, 'Fermer les process', True)
              and window.center.currentIndex() == 0
              and window.w_recipes_action.text() == 'Process…'
              and window._dock_insp.isVisible(),
              ' → '.join(str(x) for x in ouvert_p))
        barre_droite = window.findChildren(QToolBar)[0].actions()
        # les trois réserves, côte à côte : bibliothèque, montages, process
        rangs = [i for i, a in enumerate(barre_droite)
                 if a.text() in ('Process…', 'Bibliothèque…', 'Montages…')]
        check('barre : bibliothèque, montages et process bordés à droite',
              window.w_recipes_button is not None
              and window.w_montages_button is not None
              and len(rangs) == 3 and rangs == list(range(rangs[0],
                                                          rangs[0] + 3))
              and min(rangs) >= len(barre_droite) - 4
              and not hasattr(window, 'w_recipes_push'),
              f'rangs {rangs} sur {len(barre_droite)}')

        # --- la zone de clic d un texte est son pave entier ---------------
        #
        # Qt rend le contour des **traits** : cliquer un texte entre deux
        # lettres, ou un DataMatrix entre deux modules, ne touchait rien.
        # La selection se vidait, et le clic suivant semblait aleatoire.
        from PySide6.QtCore import QPointF as _QPF_h
        from PySide6.QtCore import QEvent as _QEvent
        from PySide6.QtCore import Qt as _QtK
        from PySide6.QtGui import QKeyEvent as _QKeyEvent
        from engrave.app import ShapeItem as _SI_h, DRAG_HOLD_MS as _HOLD
        from engrave.model import Code, Path as _PathH
        _bac_h = Document(name='clic')
        _ong_h = window.new_tab(_bac_h)
        app.processEvents()
        _t_h = Text(text='B{n:06}', size_mm=8, x=0.0, y=0.0, name='T',
                    recipe=PRESET_RECIPES[0])
        _cadre_h = _PathH(
            polylines=[[(-20, -20), (20, -20), (20, 20), (-20, 20),
                        (-20, -20)]], recipe=PRESET_RECIPES[0], name='cadre')
        window.document.add(_t_h)
        window.document.add(_cadre_h)
        window.canvas.reload()
        window._refresh_list()
        app.processEvents()
        _it_t = window.canvas._items[_t_h.id]
        _it_c = window.canvas._items[_cadre_h.id]
        _centre_h = _it_t.sceneBoundingRect().center()
        check('clic : un texte se prend par son pave, un trace par son trait',
              _it_t.shape().contains(_it_t.mapFromScene(_centre_h))
              and _it_c.shape().contains(_QPF_h(0, -20))
              and not _it_c.shape().contains(_QPF_h(0, 0)),
              'centre du texte touche · trait du cadre touche · interieur '
              'du cadre libre pour ce qu' + chr(39) + 'il entoure')

        # --- un clic court ne deplace rien --------------------------------
        import time as _t_mod
        window.canvas.select_many([_t_h.id])
        app.processEvents()
        _x0_h, _y0_h = _t_h.x, _t_h.y
        _base_h = _it_t.sceneBoundingRect().center()

        class _FauxSouris:
            def __init__(self, pos):
                self._p = pos

            def scenePos(self):
                return self._p

            def buttons(self):
                return _Qt.LeftButton

            def button(self):
                return _Qt.LeftButton

            def modifiers(self):
                # Alt : sans l'aimant, le geste rend le pas exact
                return _Qt.AltModifier

            def accept(self):
                pass

            def ignore(self):
                pass

        _it_t._presse_t = _t_mod.monotonic()
        _it_t._traine = False
        _it_t.mouseMoveEvent(_FauxSouris(
            _QPF_h(_base_h.x() + 3, _base_h.y() + 3)))
        _court = (_t_h.x, _t_h.y)
        _it_t._presse_t = _t_mod.monotonic() - (_HOLD + 50) / 1000.0
        _it_t._traine = False
        _it_t.mouseMoveEvent(_FauxSouris(_base_h))
        _it_t.mouseMoveEvent(_FauxSouris(_QPF_h(_base_h.x() + 6,
                                                _base_h.y())))
        check('clic : moins de ' + str(_HOLD) + ' ms ne deplace rien, '
              'tenir deplace',
              _court == (_x0_h, _y0_h) and abs(_t_h.x - _x0_h - 6) < 1e-6
              and not (_SI_h.ItemIsMovable
                       & _it_t.flags() if hasattr(_SI_h, 'ItemIsMovable')
                       else False),
              f'clic court : {_court[0]:g} inchange · maintenu : '
              f'{_x0_h:g} → {_t_h.x:g}')

        # un groupe suit d un bloc, et les fleches deplacent toujours
        window.document.group([_t_h.id, _cadre_h.id])
        window.canvas.reload()
        window.canvas.select_many([_t_h.id, _cadre_h.id])
        app.processEvents()
        _it_t = window.canvas._items[_t_h.id]
        _xt, _xc = _t_h.x, _cadre_h.x
        _it_t._presse_t = _t_mod.monotonic() - 1.0
        _it_t._traine = False
        _dep = _it_t.sceneBoundingRect().center()
        _it_t.mouseMoveEvent(_FauxSouris(_dep))
        _it_t.mouseMoveEvent(_FauxSouris(_QPF_h(_dep.x() + 4, _dep.y())))
        window.canvas.setFocus()
        _xf = _t_h.x
        window.canvas.keyPressEvent(_QKeyEvent(_QEvent.KeyPress,
                                               _QtK.Key_Right,
                                               _QtK.NoModifier))
        app.processEvents()
        # La fleche deplace **toute la selection** elle aussi : les deux
        # formes prennent donc 4 mm de souris puis un pas de clavier.
        _pas_h = window.canvas.nudge_step
        check('clic : le groupe suit d un bloc, les fleches deplacent toujours',
              abs(_t_h.x - _xt - 4 - _pas_h) < 1e-6
              and abs(_cadre_h.x - _xc - 4 - _pas_h) < 1e-6
              and abs(_t_h.x - _xf - _pas_h) < 1e-6,
              f'les deux +4 mm a la souris · puis +{_pas_h:g} mm a la fleche')

        # --- l'aimant : bords et milieux s'accrochent ------------------------
        from PySide6.QtWidgets import QGraphicsSceneMouseEvent as _QGSME
        from engrave import aimant as _aim
        check('aimant : la prise la plus proche s\'accroche, hors de portee '
              'rien ne bouge',
              _aim.accroche((0.0, 5.0, 10.0), [-150.0, 0.0, 20.25, 150.0],
                            10.0, 0.5) == (10.25, 20.25)
              and _aim.accroche((0.0, 5.0, 10.0), [-150.0, 0.0, 21.0],
                                10.0, 0.5) == (10.0, None)
              and _aim.accroche((), [0.0], 3.0, 1.0) == (3.0, None)
              and _aim.accroche((0.0,), [], 3.0, 1.0) == (3.0, None))

        def _souris_a(genre, pos, mod=_QtK.NoModifier):
            ev = _QGSME(genre)
            ev.setScenePos(pos)
            ev.setButton(_QtK.LeftButton)
            ev.setButtons(_QtK.NoButton
                          if genre == _QEvent.GraphicsSceneMouseRelease
                          else _QtK.LeftButton)
            ev.setModifiers(mod)
            return ev

        def _glisser_a(ids, item, dx, dy, mod=_QtK.NoModifier):
            window.canvas.select_many(ids)
            app.processEvents()
            dep = item.sceneBoundingRect().center()
            item._presse_t = _t_mod.monotonic() - 1.0
            item._traine = False
            item.mouseMoveEvent(_souris_a(_QEvent.GraphicsSceneMouseMove,
                                          dep, mod))
            item.mouseMoveEvent(_souris_a(
                _QEvent.GraphicsSceneMouseMove,
                _QPF_h(dep.x() + dx, dep.y() + dy), mod))

        _ong_a = window.new_tab(Document(name='aimant'))
        app.processEvents()
        _ra = Rect(width=20, height=10, recipe=PRESET_RECIPES[1])
        _rb = Rect(width=10, height=10, x=40.0, y=3.0,
                   recipe=PRESET_RECIPES[1])
        _rc = Rect(width=4, height=4, x=60.0, y=30.0,
                   recipe=PRESET_RECIPES[1])
        for _f_a in (_ra, _rb, _rc):
            window.document.add(_f_a)
        window.canvas.reload()
        app.processEvents()
        _ib_a = window.canvas._items[_rb.id]
        _portee_a = (_aim.PORTEE_PX
                     / abs(window.canvas.transform().m11()))
        session.set_aimant(True)
        # le bas de B (-2) passe à 0,4 portée du bas de A (-5) : il s'y pose
        _glisser_a([_rb.id], _ib_a, 0.0, -3.0 + 0.4 * _portee_a)
        _pose_a = (_rb.x, _rb.y)
        _guides_a = [g.isVisible() for g in window.canvas._guides]
        _ib_a.mouseReleaseEvent(_souris_a(_QEvent.GraphicsSceneMouseRelease,
                                          _QPF_h(0, 0)))
        _apres_a = [g.isVisible() for g in window.canvas._guides]
        # Alt tenu : libre
        _rb.y = 3.0
        window.canvas.refresh(_rb.id)
        _glisser_a([_rb.id], _ib_a, 0.0, -3.0 + 0.4 * _portee_a,
                   _QtK.AltModifier)
        _alt_a = _rb.y
        # coupé dans le menu : libre, et retenu
        _rb.y = 3.0
        window.canvas.refresh(_rb.id)
        window.act_aimant.trigger()
        _coupe_a = session.aimant()
        _glisser_a([_rb.id], _ib_a, 0.0, -3.0 + 0.4 * _portee_a)
        _libre_a = _rb.y
        window.act_aimant.trigger()
        # B et C ensemble : leur milieu commun (15) se pose sur le haut de A
        _rb.y = 3.0
        window.canvas.refresh(_rb.id)
        _glisser_a([_rb.id, _rc.id], _ib_a, 0.0, -10.0 + 0.3 * _portee_a)
        check('aimant : le bord se pose sur le bord, Alt ou le menu '
              'liberent, un ensemble garde ses ecarts',
              _pose_a == (40.0, 0.0)
              and _guides_a == [False, True] and _apres_a == [False, False]
              and abs(_alt_a - 0.4 * _portee_a) < 1e-9
              and not _coupe_a and abs(_libre_a - 0.4 * _portee_a) < 1e-9
              and session.aimant() and window.act_aimant.isChecked()
              and abs(_rb.y + 7.0) < 1e-9 and abs(_rc.y - 20.0) < 1e-9
              and window.act_aimant.shortcut().toString() == 'Ctrl+Shift+M',
              f'portee {_portee_a:.2f} mm · pose B en {_pose_a[1]:g} · '
              f'ensemble B {_rb.y:g}, C {_rc.y:g}')
        window.tabs.setCurrentWidget(workbench)

        # --- duplication : la copie se pose a cote, et se delie -----------
        #
        # Cinq millimetres de decalage se voyaient sur une plaquette de
        # quinze ; sur un dessin de deux cents, les deux exemplaires se
        # superposaient et l on gravait deux fois le meme trace.
        _bac_d = Document(name='dupl')
        _ong_d = window.new_tab(_bac_d)
        app.processEvents()
        window._add_code_in_frame()
        app.processEvents()
        _plaque_d = list(window.document.shapes)[-2:]
        window.canvas.select_many([s.id for s in _plaque_d])
        app.processEvents()
        _x_av = [round(s.x, 3) for s in _plaque_d]
        window._duplicate()
        app.processEvents()
        _copies_d = list(window.document.shapes)[-2:]
        _code_o = next(s for s in _plaque_d if isinstance(s, Code))
        _code_c = next(s for s in _copies_d if isinstance(s, Code))
        _txt_c = next(s for s in _copies_d if isinstance(s, Text))
        from engrave.toolpath import shape_extent as _ext_d
        _b_o = _ext_d(_code_o)
        _ecart = _code_c.x - _code_o.x
        check('duplication : la copie se pose a cote, pas par-dessus',
              _ecart >= (_b_o[2] - _b_o[0])
              and [type(s).__name__ for s in _copies_d] == ['Code', 'Text'],
              f'decalee de {_ecart:.1f} mm pour un symbole large de '
              f'{_b_o[2] - _b_o[0]:.1f} mm · ordre de gravure tenu')
        check('duplication : le texte de la copie suit le code de la copie',
              _txt_c.follows == _code_c.id and _txt_c.follows != _code_o.id,
              'sinon retaper l' + chr(39) + 'original changeait aussi le '
              'texte de la copie')
        # un grand dessin : la copie reste dans le champ, ou descend
        _grand = Rect(width=100, height=20, x=0.0, y=0.0,
                      recipe=PRESET_RECIPES[0])
        window.document.add(_grand)
        window.canvas.reload()
        window.canvas.select_many([_grand.id])
        app.processEvents()
        window._duplicate()
        app.processEvents()
        _copie_g = window.document.shapes[-1]
        check('duplication : si la place manque a droite, la copie descend',
              abs(_copie_g.x) < 1e-9 and _copie_g.y < 0
              and abs(_copie_g.y) >= 20,
              f'copie a ({_copie_g.x:g}, {_copie_g.y:g}) mm — '
              f'100 mm de large dans un champ de '
              f'{window.document.field_w:g}')
        window.tabs.setCurrentWidget(workbench)

        # --- libelles sous les icones -------------------------------------
        from PySide6.QtWidgets import QToolBar as _QTB
        _barre = window.findChildren(_QTB)[0]
        _avant_lbl = _barre.toolButtonStyle()
        window.w_tb_labels.setChecked(True)
        app.processEvents()
        _apres_lbl = _barre.toolButtonStyle()
        _libelles = [a.iconText() for a in _barre.actions() if a.iconText()]
        window.w_tb_labels.setChecked(False)
        app.processEvents()
        session.settings().remove('window/toolbar_labels')
        check('barre : les libelles paraissent sous les icones, en abrege',
              _avant_lbl == _Qt.ToolButtonIconOnly
              and _apres_lbl == _Qt.ToolButtonTextUnderIcon
              and _barre.toolButtonStyle() == _Qt.ToolButtonIconOnly
              and _libelles and max(len(t) for t in _libelles) <= 12
              and 'Export dess.' in _libelles,
              f'{len(_libelles)} libelles, au plus '
              f'{max(len(t) for t in _libelles)} caracteres')

        check('barre : importer et exporter un dessin ont leur icone',
              not icons.icon('import_dessin').isNull()
              and not icons.icon('export_dessin').isNull()
              and 'import_dessin' in icons.DRAWINGS
              and 'export_dessin' in icons.DRAWINGS,
              'fleche entrant dans une feuille, et sortant')

        # --- la process du dernier emploi, par onglet ----------------------
        import dataclasses as _dc_pr
        _memoire_pr = list(RECIPE_LIBRARY)
        _bib_pr = [_dc_pr.replace(PRESET_RECIPES[0], name='Premiere'),
                   _dc_pr.replace(PRESET_RECIPES[1], name='Satine')]
        try:
            recipes.set_recipe_library(_bib_pr)
            _bac_pr = Document(name='process')
            _ong_pr = window.new_tab(_bac_pr)
            app.processEvents()
            window._add_rect()
            app.processEvents()
            _premiere = window.document.shapes[-1].recipe.name
            _forme_pr = window.document.shapes[-1]
            window.recipe.set_shape(None)
            window.recipe.set_shape(_forme_pr)
            app.processEvents()
            window.recipe.w_preset.setCurrentIndex(
                recipes.combo_index(window.recipe.w_preset, _bib_pr[1]))
            app.processEvents()
            window._add_rect()
            app.processEvents()
            _suivante = window.document.shapes[-1].recipe.name
            _retenue_pr = window.document.last_recipe
            # un autre onglet garde la sienne
            _ong_pr2 = window.new_tab(Document(name='process 2'))
            app.processEvents()
            window._add_rect()
            app.processEvents()
            _autre_pr = window.document.shapes[-1].recipe.name
            # et elle survit a l enregistrement
            window.tabs.setCurrentWidget(_ong_pr)
            app.processEvents()
            _relu_pr = serialize.loads(serialize.dumps(window.document))
            _sans = serialize.document_to_dict(window.document)
            _sans.pop('last_recipe')
            _vieux_pr = serialize.document_from_dict(_sans)
            check('process : celle du dernier emploi est reprise, par onglet',
                  _premiere == 'Premiere' and _suivante == 'Satine'
                  and _retenue_pr is not None
                  and _retenue_pr.name == 'Satine'
                  and _autre_pr == 'Premiere'
                  and _relu_pr.last_recipe.name == 'Satine'
                  and _vieux_pr.last_recipe is None,
                  f'1re forme {_premiere} → reglee Satine → 2e forme '
                  f'{_suivante} · autre onglet {_autre_pr} · relue '
                  f'{_relu_pr.last_recipe.name}')
        finally:
            recipes.set_recipe_library(_memoire_pr)
            window.tabs.setCurrentWidget(workbench)
            app.processEvents()

        # --- le champ du contenu garde le focus apres un double-clic -------
        #
        # La fin de la sequence de souris rendait la main au plan de
        # travail : le curseur clignotait dans le champ, et ce qu on
        # tapait n y entrait pas.
        from engrave.app import RECLAIM_FOCUS_MS as _RECLAIM
        _bac_f = Document(name='focus')
        _ong_f = window.new_tab(_bac_f)
        app.processEvents()
        _t_f = Text(text='ABC', size_mm=8, x=0.0, y=0.0,
                    recipe=PRESET_RECIPES[0])
        window.document.add(_t_f)
        window.canvas.reload()
        window.canvas.select_many([_t_f.id])
        app.processEvents()
        window._edit_requested(_t_f.id)
        app.processEvents()
        _focus_f = window.focusWidget()
        window.canvas.setFocus(_Qt.OtherFocusReason)      # le plan le vole
        app.processEvents()
        _vole = window.focusWidget()
        _fin_f = _t_mod.monotonic() + (_RECLAIM + 400) / 1000.0
        while _t_mod.monotonic() < _fin_f:
            app.processEvents()
            _t_mod.sleep(0.01)
        _rendu_f = window.focusWidget()
        if _rendu_f is not None and hasattr(_rendu_f, 'toPlainText'):
            app.sendEvent(_rendu_f, _QKeyEvent(_QEvent.KeyPress, 0,
                                               _QtK.NoModifier, 'Z'))
            app.processEvents()
        check('double-clic : le champ reprend le focus, et la frappe y entre',
              _focus_f is window.inspector.text_field()
              and _vole is not _focus_f
              and _rendu_f is window.inspector.text_field()
              and _t_f.text == 'Z',
              f'focus pose, vole par le plan, repose en {_RECLAIM} ms · '
              f'texte « {_t_f.text} »')
        # il ne vole pas un champ que l operateur a choisi lui-meme
        window._edit_requested(_t_f.id)
        app.processEvents()
        window.w_step.spin.setFocus(_Qt.OtherFocusReason)
        _fin_f = _t_mod.monotonic() + (_RECLAIM + 400) / 1000.0
        while _t_mod.monotonic() < _fin_f:
            app.processEvents()
            _t_mod.sleep(0.01)
        check('double-clic : il ne reprend pas un champ choisi par '
              'l' + chr(39) + 'operateur',
              window.focusWidget() is window.w_step.spin,
              'le pas garde la main')
        window.tabs.setCurrentWidget(workbench)
        app.processEvents()

        # --- l ordre de gravure se regle a la fleche -----------------------
        #
        # L ordre de la liste est l ordre de gravure ; il ne se reglait
        # qu au clic droit, dans un menu de quinze entrees.
        from engrave.model import Circle as _CircleO
        _bac_o = Document(name='ordre')
        _ong_o = window.new_tab(_bac_o)
        app.processEvents()
        _a_o = Rect(width=10, height=10, name='A', recipe=PRESET_RECIPES[0])
        _b_o = _CircleO(width=8, height=8, name='B', recipe=PRESET_RECIPES[0])
        _c_o = Text(text='C', size_mm=5, name='C', recipe=PRESET_RECIPES[0])
        for _f_o in (_a_o, _b_o, _c_o):
            window.document.add(_f_o)
        window.canvas.reload()
        window._refresh_list()
        app.processEvents()

        def _ordre_o():
            return [s.name for s in window.document.shapes]

        window.canvas.select_many([_c_o.id])
        app.processEvents()
        window.w_order_up.click()
        app.processEvents()
        _seul = _ordre_o()
        window.canvas.select_many([_b_o.id, _c_o.id])
        app.processEvents()
        window.w_order_up.click()
        app.processEvents()
        _duo = _ordre_o()
        window.w_order_up.click()
        app.processEvents()
        _butee = _ordre_o()
        check('ordre de gravure : les fleches montent la selection, ordre tenu',
              _seul == ['A', 'C', 'B'] and _duo == ['C', 'B', 'A']
              and _butee == ['C', 'B', 'A'],
              ' → '.join(' '.join(o) for o in (['A', 'B', 'C'], _seul, _duo))
              + ' · butee tenue')
        window.w_order_down.click()
        app.processEvents()
        _descendu = _ordre_o()
        # l ordre de la liste est bien celui des passes, hors regroupement
        _passes_o = [p.source_name for p in
                     _passes(window.document, optimize=False,
                             group_by_recipe=False)]
        check('ordre de gravure : la liste est l ordre des passes exportees',
              _descendu == ['A', 'C', 'B']
              and [n.split()[0] for n in _passes_o][:3] == ['A', 'C', 'B'],
              ' '.join(_descendu) + ' · passes ' + ', '.join(_passes_o[:3]))
        window.tabs.setCurrentWidget(workbench)

        # --- champ texte : plus grand, etirable, hauteur retenue -----------
        from engrave.widgets import TextBox as _TB
        from PySide6.QtCore import QPointF as _QPF
        from PySide6.QtGui import QMouseEvent as _QME
        from PySide6.QtCore import QEvent as _QEvt
        _forme_t = next(s for s in window.document.shapes
                        if isinstance(s, Text))
        window.canvas.select_many([_forme_t.id])
        app.processEvents()
        _champ = window.inspector.w_text
        _h0 = _champ.height()
        # on attrape le bord inferieur et on tire de 90 px
        _bas = _QPF(40, _champ.height() - 2)
        _champ.mousePressEvent(_QME(_QEvt.MouseButtonPress, _bas,
                                    _Qt.LeftButton, _Qt.LeftButton,
                                    _Qt.NoModifier))
        _champ.mouseMoveEvent(_QME(_QEvt.MouseMove, _QPF(40, _bas.y() + 90),
                                   _Qt.NoButton, _Qt.LeftButton,
                                   _Qt.NoModifier))
        _h_tire = _champ.height()
        _champ.mouseReleaseEvent(_QME(_QEvt.MouseButtonRelease,
                                      _QPF(40, _bas.y() + 90),
                                      _Qt.LeftButton, _Qt.NoButton,
                                      _Qt.NoModifier))
        app.processEvents()
        _retenue = session.field_height('texte')
        window.inspector.set_shape(None)
        window.inspector.set_shape(_forme_t)
        app.processEvents()
        _rouvert = window.inspector.w_text.height()
        # le milieu du champ reste de la saisie, pas une poignee
        _milieu = _QPF(40, 10)
        _champ2 = window.inspector.w_text
        _champ2.mousePressEvent(_QME(_QEvt.MouseButtonPress, _milieu,
                                     _Qt.LeftButton, _Qt.LeftButton,
                                     _Qt.NoModifier))
        _champ2.mouseMoveEvent(_QME(_QEvt.MouseMove, _QPF(40, 120),
                                    _Qt.NoButton, _Qt.LeftButton,
                                    _Qt.NoModifier))
        _inchange = _champ2.height()
        _champ2.mouseReleaseEvent(_QME(_QEvt.MouseButtonRelease,
                                       _QPF(40, 120), _Qt.LeftButton,
                                       _Qt.NoButton, _Qt.NoModifier))
        check('champ texte : etire par son bord, hauteur retenue et rendue',
              isinstance(_champ, _TB) and _h0 >= 110
              and _h_tire == _h0 + 90 and _retenue == _h_tire
              and _rouvert == _h_tire and _inchange == _rouvert,
              f'{_h0} → {_h_tire} px · rouvert a {_rouvert} · le milieu '
              f'reste de la saisie')
        session.settings().remove('champs/texte')

        # --- interligne : plafond leve, decimales fines --------------------
        _sp = window.inspector.w_spacing
        _sp.setValue(12.345)
        app.processEvents()
        _lu = _sp.spin.text()
        _sp.setValue(0.4)
        app.processEvents()
        check('interligne : au-dela de 5, et au millieme',
              _sp.minimum() <= 0.05 and _sp.maximum() >= 50
              and abs(_forme_t.line_spacing - 0.4) < 1e-9
              and _lu.replace(',', '.') == '12.345',
              f'bornes {_sp.minimum():g}–{_sp.maximum():g} · 12,345 lu '
              f'« {_lu} » · 0,4 applique')
        _sp.setValue(1.4)
        app.processEvents()

        # --- la liste des process, rangee comme la page des process --------
        #
        # Une liste plate prefixee du dossier n avait ni l ordre ni la
        # forme du gestionnaire : racine d abord, dossiers en tete, process
        # en retrait. Les en-tetes ne se choisissent pas.
        import dataclasses as _dc_cb
        _memoire_cb = list(RECIPE_LIBRARY)
        _bib_cb = [_dc_cb.replace(PRESET_RECIPES[0], name='Zinc', folder='Metal'),
                   _dc_cb.replace(PRESET_RECIPES[1], name='Racine A', folder=''),
                   _dc_cb.replace(PRESET_RECIPES[2], name='Alu', folder='Metal'),
                   _dc_cb.replace(PRESET_RECIPES[3], name='Essai 1',
                                  folder='Essais')]
        try:
            recipes.set_recipe_library(_bib_cb)
            _forme_cb = window.document.shapes[0]
            window.recipe.set_shape(None)
            window.recipe.set_shape(_forme_cb)
            app.processEvents()
            _cb = window.recipe.w_preset
            _textes = [_cb.itemText(i) for i in range(_cb.count())]
            _tetes = [i for i in range(_cb.count())
                      if not (_cb.model().item(i).flags() & _Qt.ItemIsSelectable)]
            _ordre_gest = [(d, [r.name for r in m])
                           for d, m in recipes.grouped(_bib_cb)]
            check('liste des process : racine, puis dossiers, comme le gestionnaire',
                  _textes[:2] == ['(personnalisée)', 'Racine A']
                  and _textes[2].startswith('Essais')
                  and _textes[3].strip() == 'Essai 1'
                  and _textes[4].startswith('Metal')
                  and [t.strip() for t in _textes[5:7]] == ['Zinc', 'Alu']
                  and _tetes == [2, 4]
                  and _ordre_gest == [('', ['Racine A']), ('Essais', ['Essai 1']),
                                      ('Metal', ['Zinc', 'Alu'])],
                  ' | '.join(t.strip() for t in _textes))
            # choisir dans la liste applique bien la process visee, en-tetes
            # decales ou non
            _rang_alu = recipes.combo_index(_cb, _bib_cb[2])
            _cb.setCurrentIndex(_rang_alu)
            app.processEvents()
            check('liste des process : le choix vise la bonne process malgre '
                  'les en-tetes',
                  _rang_alu == 6 and _forme_cb.recipe.name == 'Alu'
                  and window.recipe._preset_index(_forme_cb.recipe) == 6,
                  f'rang {_rang_alu} → {_forme_cb.recipe.name}')
        finally:
            recipes.set_recipe_library(_memoire_cb)
            _forme_cb.recipe = PRESET_RECIPES[1]
            window.recipe.set_shape(None)

        # --- le formulaire suit le geste : un texte deplace ne saute plus ---
        #
        # Deplacer une forme a la souris ne passait pas par l inspecteur,
        # dont les champs X/Y gardaient l ancienne position. Retaper le
        # texte reecrivait alors cette position : la forme sautait la
        # d ou on venait de la deplacer.
        from PySide6.QtCore import Qt as _QtK
        from PySide6.QtGui import QKeyEvent as _QKeyEvent
        from PySide6.QtCore import QEvent as _QEvent
        from engrave.model import Text as _TxtS, Rect as _RectS
        _bac_s = Document(name='suivi')
        _ong_s = window.new_tab(_bac_s)
        app.processEvents()
        _t_s = _TxtS(text='ABC', size_mm=5, x=0.0, y=0.0,
                     recipe=PRESET_RECIPES[0])
        window._add(_t_s)
        app.processEvents()
        _item_s = window.canvas._items[_t_s.id]
        _item_s.setPos(12.5, -7.25)           # le geste de la souris
        app.processEvents()
        _suivi = (round(window.inspector.w_x.value(), 3),
                  round(window.inspector.w_y.value(), 3))
        window.inspector.w_text.setPlainText('ABCDEF')
        app.processEvents()
        check('deplacement : le formulaire suit, retaper ne replace pas',
              _suivi == (12.5, -7.25)
              and abs(_t_s.x - 12.5) < 1e-9 and abs(_t_s.y + 7.25) < 1e-9
              and _t_s.text == 'ABCDEF',
              f'champs {_suivi} · forme ({_t_s.x:g}, {_t_s.y:g})')

        # --- Ctrl+fleche : le champ du pas prend la main, Entree la rend ---
        window.canvas.setFocus()
        app.processEvents()
        _ev = _QKeyEvent(_QEvent.KeyPress, _QtK.Key_Left,
                         _QtK.ControlModifier)
        window.canvas.keyPressEvent(_ev)
        app.processEvents()
        # `window.focusWidget()` et non `hasFocus()` : ce dernier exige
        # que la fenetre soit active, ce qu elle n est pas sous autotest
        _a_le_pas = window.focusWidget() is window.w_step.spin
        window.w_step.spin.selectAll()
        window.w_step.spin.lineEdit().setText('0,35')
        _entree = _QKeyEvent(_QEvent.KeyPress, _QtK.Key_Return,
                             _QtK.NoModifier)
        window.w_step.spin.keyPressEvent(_entree)
        app.processEvents()
        check('Ctrl+fleche : le pas se tape, Entree l applique et rend la main',
              _a_le_pas and abs(window.canvas.nudge_step - 0.35) < 1e-9
              and window.focusWidget() is not window.w_step.spin,
              f'focus au pas {_a_le_pas} · pas {window.canvas.nudge_step:g} '
              f'· focus rendu {window.focusWidget() is not window.w_step.spin}')
        # la selection est intacte : la fleche suivante bouge la forme
        _x_avant = _t_s.x
        window.canvas.keyPressEvent(_QKeyEvent(_QEvent.KeyPress,
                                               _QtK.Key_Right,
                                               _QtK.NoModifier))
        app.processEvents()
        check('Ctrl+fleche : la forme reste selectionnee et bouge du pas tape',
              abs(_t_s.x - _x_avant - 0.35) < 1e-6,
              f'{_x_avant:g} → {_t_s.x:g}')

        # --- bouton texte et double-clic : le champ texte prend la main ---
        window._add_text()
        app.processEvents()
        app.processEvents()
        _foc = window.focusWidget()
        check('bouton texte : le champ texte a le focus, tout selectionne',
              _foc is not None and _foc is getattr(window.inspector,
                                                   'w_text', None)
              and _foc.textCursor().hasSelection(),
              ' > '.join(type(x).__name__ for x in [_foc, _foc.parent(), _foc.parent().parent(), _foc.parent().parent().parent()] if x) if _foc else 'aucun')
        window.canvas.setFocus()
        window.canvas.edit_requested.emit(_t_s.id)
        app.processEvents()
        app.processEvents()
        _foc2 = window.focusWidget()
        check('double-clic sur un texte : son champ texte prend la main',
              window.inspector._shape is _t_s
              and _foc2 is getattr(window.inspector, 'w_text', None),
              type(_foc2).__name__ if _foc2 else 'aucun')

        # --- selection multiple : la colonne process regle tout le lot ---
        _r1 = _RectS(width=10, height=10, x=-30, recipe=PRESET_RECIPES[0])
        _r2 = _RectS(width=10, height=10, x=30, recipe=PRESET_RECIPES[0])
        window.document.add(_r1)
        window.document.add(_r2)
        window.canvas.reload()
        window.canvas._primary = _r1.id
        window.canvas.select_many([_r1.id, _r2.id, _t_s.id])
        app.processEvents()
        _avant_lot = {_r1.recipe.power_percent, _r2.recipe.power_percent,
                      _t_s.recipe.power_percent}
        window.recipe.w_power.setValue(37.0)
        app.processEvents()
        check('lot : regler la process en colonne 1 regle toutes les formes',
              window.recipe._spread()
              and {_r1.recipe.power_percent, _r2.recipe.power_percent,
                   _t_s.recipe.power_percent} == {37.0},
              f'avant {sorted(_avant_lot)} · apres '
              f'{sorted({_r1.recipe.power_percent, _r2.recipe.power_percent, _t_s.recipe.power_percent})}')
        # un lot aux process melees — un coupon — n est pas ecrase
        import dataclasses as _dc_lot
        _r2.recipe = _dc_lot.replace(_r2.recipe, power_percent=80.0,
                                     name='autre')
        window.canvas.select_many([_r1.id])
        app.processEvents()
        window.canvas._primary = _r1.id
        window.canvas.select_many([_r1.id, _r2.id])
        app.processEvents()
        _prim = window.document.get(window.canvas.primary_id())
        window.recipe.w_power.setValue(55.0)
        app.processEvents()
        _autre = _r2 if _prim is _r1 else _r1
        check('lot : des process melees ne sont pas ecrasees d un tour de molette',
              not window.recipe._spread()
              and _prim.recipe.power_percent == 55.0
              and _autre.recipe.power_percent != 55.0,
              f'cliquee {_prim.recipe.power_percent:g} · autre '
              f'{_autre.recipe.power_percent:g}')
        window.recipe._extend_to_lot()
        app.processEvents()
        check('lot : « Etendre a toutes » pose la process cliquee partout',
              _r1.recipe.power_percent == 55.0
              and _r2.recipe.power_percent == 55.0
              and window.recipe._spread(),
              'les deux a 55 %')
        window.tabs.setCurrentWidget(workbench)

        # --- la prochaine plaque, reglee au bout de la fleche -------------
        #
        # Cadre, taille, position et place du texte s enregistrent ; une
        # plaque retouchee — deplacee au plan compris — apprend a la
        # suivante. Des reglages d avant (texte retenu en absolu) posent
        # la premiere plaque exactement ou l ancienne version la posait.
        from PySide6.QtWidgets import QWidgetAction as _QWA
        from engrave.model import Code as _CodeP
        _avant_def = session.settings().value('code/defaults')
        try:
            session.settings().setValue('code/defaults', {
                'frame': [20.0, 10.0, 15.0, 7.0],
                'text_frame': [4.93, 6.27, 8.071, 1.538],
                'data': 'B{n:06}', 'kind': 'datamatrix', 'dm_shape': 'auto'})
            _ong_p = window.new_tab(Document(name='plaques'))
            app.processEvents()
            window._add_code_in_frame()
            app.processEvents()
            _c1 = next(s for s in window.document.shapes
                       if isinstance(s, _CodeP))
            _t1 = next(s for s in window.document.shapes
                       if isinstance(s, Text) and s.follows == _c1.id)
            check('plaque : des reglages d avant posent le texte au meme endroit',
                  abs(_t1.x - 4.93) < 1e-6 and abs(_t1.y - 6.27) < 1e-6
                  and session.code_defaults()['code_frame'] == 'auto',
                  f'texte en ({_t1.x:g}, {_t1.y:g}) · cadre « selon le code »')

            _menu_c = window.w_code_menu.actions()
            _f = window.w_plate_form
            _f.load()
            _f.w_cadre.setCurrentIndex(_f.w_cadre.findData('none'))
            _f.w_marge.setValue(1.0)
            _f.w_l.setValue(12.0)
            _f.w_h.setValue(6.0)
            _f.w_x.setValue(-10.0)
            _f.w_y.setValue(5.0)
            _f.w_tdx.setValue(0.0)
            _f.w_tdy.setValue(-5.0)
            app.processEvents()
            window.canvas.select_many([])
            app.processEvents()
            window._add_code_in_frame()
            app.processEvents()
            _c2 = [s for s in window.document.shapes
                   if isinstance(s, _CodeP)][-1]
            _t2 = next(s for s in window.document.shapes
                       if isinstance(s, Text) and s.follows == _c2.id)
            check('plaque : le formulaire de la fleche regle la suivante',
                  isinstance(_menu_c[0], _QWA)
                  and _c2.frame == 'none' and _c2.frame_margin_mm == 1.0
                  and (_c2.fit_w_mm, _c2.fit_h_mm) == (12.0, 6.0)
                  and (_c2.x, _c2.y) == (-10.0, 5.0)
                  and abs(_t2.x + 10.0) < 1e-6 and abs(_t2.y) < 1e-6,
                  f'sans cadre, marge 1, 12 × 6 en (-10, 5), texte 5 mm '
                  f'dessous')

            window.canvas.select_many([_c2.id, _t2.id])
            app.processEvents()
            for _it in (window.canvas._items[_c2.id],
                        window.canvas._items[_t2.id]):
                _it.moveBy(3.0, 2.0)
            app.processEvents()
            _d = session.code_defaults()
            window._capture_plate()
            check('plaque : deplacee au plan, elle apprend a la suivante',
                  tuple(_d['frame'][:2]) == (-7.0, 7.0)
                  and abs(_d['text_offset'][1] + 5.0) < 1e-6,
                  f'position retenue {tuple(_d["frame"][:2])}, texte toujours '
                  f'5 mm dessous')
            # un montage deplace ne dit rien de la prochaine plaque seule
            _avant_m = session.code_defaults()['frame']
            window._add_montage()
            app.processEvents()
            for _it in [window.canvas._items[_sid]
                        for _sid in window.canvas.selected_ids()]:
                _it.moveBy(4.0, 0.0)
            app.processEvents()
            check('plaque : un montage deplace ne la reecrit pas',
                  session.code_defaults()['frame'] == _avant_m,
                  f'toujours {tuple(_avant_m[:2])}')

            # Des réglages ou un préréglage venus d'ailleurs — une version
            # plus récente, un autre poste, une retouche à la main — ne
            # posent plus une symbologie inconnue ni un module illisible :
            # le document ne se rouvrait plus, ou le calcul tombait.
            from engrave import codepresets as _cpre_x
            session.settings().setValue('code/defaults', {
                'frame': [0.0, 0.0, 15.0, 7.0], 'data': 'B1',
                'kind': 'aztec', 'dm_shape': 'hexagone'})
            _def_x = session.code_defaults()
            _neuf_x = _CodeP()
            _code_x = _CodeP(data='AB12')
            _cpre_x.apply_to(_code_x, {
                'name': 'venu d ailleurs', 'kind': 'aztec',
                'module_mm': 'abc', 'quiet_modules': 10 ** 9, 'level': 'H'})
            _doc_x = Document(name='prereglage')
            _doc_x.add(_code_x)
            try:
                build_passes(_doc_x)
                serialize.loads(serialize.dumps(_doc_x))
                _relu_x = True
            except (TypeError, ValueError):
                _relu_x = False
            check('plaque : réglages et préréglages inconnus laissés de côté',
                  _def_x['kind'] == 'datamatrix'
                  and _def_x['dm_shape'] == 'auto'
                  and _code_x.kind == _neuf_x.kind
                  and _code_x.module_mm == _neuf_x.module_mm
                  and _code_x.quiet_modules == _neuf_x.quiet_modules
                  and _code_x.level == 'H' and _relu_x,
                  f'réglages : {_def_x["kind"]}, {_def_x["dm_shape"]} · '
                  f'préréglage : {_code_x.kind}, module {_code_x.module_mm}, '
                  f'niveau {_code_x.level} · relu {_relu_x}')

            # Code 128 (EX-254) : la plaque se calcule et se relit. Les
            # réglages, préréglages et montages, que d'autres versions
            # relisent, le rangent à part (`kind_recent`) : une version
            # d'avant le Code 128 garde la dernière symbologie qu'elle
            # connaît, au lieu de poser un code qu'elle ne sait pas graver.
            import copy as _copy_128
            from engrave import gabarits as _gb_128
            from engrave import montage as _mg_128
            _c128 = _CodeP(data='PJJ123C', kind='code128')
            _doc_128 = Document(name='code128')
            _doc_128.add(_c128)
            _passes_128 = build_passes(_doc_128)
            _relu_128 = serialize.loads(
                serialize.dumps(_doc_128)).shapes[0].kind
            session.settings().setValue('code/defaults', {
                'frame': [0.0, 0.0, 15.0, 7.0], 'data': 'B1', 'kind': 'qr'})
            session.remember_code(kind='code128')
            _brut_128 = dict(session.settings().value('code/defaults'))
            _pre_128 = _cpre_x.from_code('essai 128', _c128)
            _cible_128 = _CodeP(data='X')
            _cpre_x.apply_to(_cible_128, _pre_128)
            from engrave.model import ecrire_symbologie as _ecr_128
            _gab_128 = _copy_128.deepcopy(_gb_128.LIVRE)
            _ecr_128(_gab_128['code'], 'code128')
            _tout_128 = _mg_128.build(_c128.recipe, gabarit=_gab_128)
            _poses_128 = [_f for _f in _tout_128 if isinstance(_f, _CodeP)]
            _relu_gab = _gb_128.depuis_formes(_tout_128, _gab_128)['code']
            check('plaque : Code 128, rangé à part pour les autres versions',
                  bool(_passes_128) and _relu_128 == 'code128'
                  and _brut_128.get('kind') == 'qr'
                  and _brut_128.get('kind_recent') == 'code128'
                  and session.code_defaults()['kind'] == 'code128'
                  and 'kind' not in _pre_128
                  and _pre_128.get('kind_recent') == 'code128'
                  and _cible_128.kind == 'code128'
                  and [c.kind for c in _poses_128] == ['code128'] * 3
                  and _relu_gab.get('kind') == 'datamatrix'
                  and _relu_gab.get('kind_recent') == 'code128',
                  f'{len(_passes_128)} passe(s), relu {_relu_128} · '
                  f'réglages kind={_brut_128.get("kind")} · préréglage '
                  f'kind={_pre_128.get("kind")} · montage '
                  f'{[c.kind for c in _poses_128]} · gabarit relu '
                  f'kind={_relu_gab.get("kind")}')

            # Relecture d'EX-249 à 254 (EX-256). Une version antérieure
            # qui passe un montage Code 128 en QR réécrit `kind` seul :
            # son choix compte. Une symbologie plus récente survit à la
            # retouche d'une largeur. Un préréglage retouché à la main ne
            # fait plus tomber l'infobulle — l'inspecteur de tout code —,
            # ni une cote démesurée des réglages le calcul.
            from engrave.model import (ecrire_symbologie as _ecr_r,
                                       lire_symbologie as _lir_r)
            _m_r = {'kind': 'datamatrix'}
            _ecr_r(_m_r, 'code128')
            _neuf_r = _lir_r(_m_r)
            _m_r['kind'] = 'qr'
            _ancien_r = _lir_r(_m_r)
            _reg_r = _mg_128.ReglagesMontage(complet=True)
            _gab_r = _copy_128.deepcopy(_gb_128.LIVRE)
            _gab_r['code'].update(kind='qr', kind_recent='pdf417',
                                  kind_commun='qr')
            _reg_r.set_gabarit(_gab_r)
            _reg_r.w_cl.setValue(16.0)
            _futur_r = _reg_r.gabarit()['code']
            _reg_r.deleteLater()
            try:
                _bulle_r = _cpre_x.describe({
                    'kind': ['qr'], 'data': 'X', 'fit_w_mm': '15',
                    'fit_h_mm': 7.0, 'with_text': True, 'text_w_mm': '8',
                    'text_h_mm': 2.0})
            except (TypeError, ValueError) as _e_r:
                _bulle_r = f'tombe : {_e_r}'
            session.settings().setValue('code/defaults', {
                'frame': [float('nan'), 0.0, 15.0, 7.0], 'data': 'B1',
                'frame_margin': 1e9, 'text_offset': [1e300, 0.0, 8.0, 1.5],
                'text_frame': [0.0, 0.0, float('inf'), 1.5]})
            _def_r = session.code_defaults()
            check('plaque : réglages, préréglages et montages relus sans '
                  'surprise',
                  _neuf_r == 'code128' and _ancien_r == 'qr'
                  and _futur_r.get('kind_recent') == 'pdf417'
                  and _futur_r.get('largeur_mm') == 16.0
                  and _bulle_r.startswith('? · « X »')
                  and _def_r['frame'] == (0.0, 0.0, 15.0, 7.0)
                  and _def_r['frame_margin'] == 0.5
                  and _def_r['text_offset'][0] == -15.07
                  and _def_r['text_frame'][2] == 8.071,
                  f'Code 128 relu {_neuf_r}, repassé en QR ailleurs : '
                  f'{_ancien_r} · symbologie future gardée : '
                  f'{_futur_r.get("kind_recent")} · infobulle « {_bulle_r} » '
                  f'· réglages : cadre {_def_r["frame"]}, marge '
                  f'{_def_r["frame_margin"]}')
        finally:
            if _avant_def is None:
                session.settings().remove('code/defaults')
            else:
                session.settings().setValue('code/defaults', _avant_def)
            window.tabs.setCurrentWidget(workbench)
            app.processEvents()

        # --- montages : les retouches s enregistrent ---------------------
        #
        # Un montage pose se relit en gabarit : ce qu on retouche au plan
        # (cadre, marge, taille, positions, texte) revient a la pose
        # suivante, depuis le formulaire de la pose, la fleche du bouton
        # ou le gestionnaire. Le fichier des gabarits du bac d essai est
        # remis tel quel a la fin.
        from engrave import gabarits as _gb
        from engrave import montage as _mg
        from engrave import montagepanel as _mp
        from engrave.model import Code as _CodeM, Text as _TextM
        from engrave import codeplate as _cpm
        import json as _json_m
        _fic_m = _gb.chemin()
        _avant_fic_m = _fic_m.read_bytes() if _fic_m.exists() else None
        _copie_m = _fic_m.with_name(_gb.AVANT)
        try:
            _fic_m.unlink(missing_ok=True)
            _copie_m.unlink(missing_ok=True)
            _gb._copie_faite = False
            _liv = _gb.verifier({})
            _r0 = PRESET_RECIPES[0]

            # relire un montage tel qu il a ete pose rend son gabarit
            _g4i = _gb.verifier({'nom': 'Quatre', 'postes': ['A', 'B', 'C', 'D'],
                                 'positions_y_mm': [30.0, 8.0, -9.0, -27.0],
                                 'donnees': ['X1', '', 'X3']})
            check('gabarit : un montage pose se relit tel quel',
                  _gb.depuis_formes(_mg.build(_r0, gabarit=_liv), _liv) == _liv
                  and _gb.depuis_formes(_mg.build(_r0, gabarit=_g4i),
                                        _g4i) == _g4i,
                  'livre et irregulier a quatre postes, a l identique')

            # retouches au plan : cadre, marge, taille, un poste descendu
            _fm = _mg.build(_r0, gabarit=_liv)
            _pm = _mg.pairs(_fm)
            for _c, _t in _pm:
                _c.frame, _c.frame_margin_mm = 'circle', 0.8
                _c.fit_w_mm, _c.fit_h_mm = 12.0, 6.0
            _pm[2][0].y -= 2.0
            _pm[2][1].y -= 2.0
            _gr = _gb.depuis_formes(_fm, _liv)
            check('gabarit : les retouches du plan se relisent',
                  _gr.get('positions_y_mm') == [23.2, 0.2, -24.8]
                  and _gr['code']['cadre'] == 'circle'
                  and _gr['code']['marge_cadre_mm'] == 0.8
                  and (_gr['code']['largeur_mm'],
                       _gr['code']['hauteur_mm']) == (12.0, 6.0),
                  f'positions {_gr.get("positions_y_mm")} · cercle 0,8 · 12 x 6')

            _fr = _mg.build(_r0, gabarit=_liv)
            for _i, (_c, _t) in enumerate(_mg.pairs(_fr)):
                _d = 1.0 + (1 - _i) * 2.0
                _c.y += _d
                _t.y += _d
            _greg = _gb.depuis_formes(_fr, _liv)
            check('gabarit : des postes regulierement espaces gardent un entraxe',
                  _greg['entraxe_mm'] == 25.0 and _greg['centre_y_mm'] == 1.2
                  and 'positions_y_mm' not in _greg,
                  f'entraxe {_greg["entraxe_mm"]} · centre {_greg["centre_y_mm"]}')

            _fx = _mg.build(_r0, gabarit=_liv)
            _cx, _tx = _mg.pairs(_fx)[1]
            _cx.x += 0.4
            _tx.x += 0.4
            _gx = _gb.depuis_formes(_fx, _liv)
            _xs = [_c.x for _c, _ in _mg.pairs(_mg.build(_r0, gabarit=_gx))]
            check('gabarit : un poste decale en X garde son abscisse',
                  _gx.get('positions_x_mm') == [0.0, 0.4, 0.0]
                  and _gx['x_mm'] == 0.2 and _xs == [0.0, 0.4, 0.0],
                  'x_mm reste ecrit, au milieu, pour la version d avant')

            # le texte : agrandi, il le reste ; une reference courte ne le
            # fait pas retrecir
            _ft = _mg.build(_r0, gabarit=_liv)
            for _c, _t in _mg.pairs(_ft):
                _t.size_mm *= 1.25
            _voulu = _mg.pairs(_ft)[0][1].size_mm
            _gt = _gb.depuis_formes(_ft, _liv)
            _vus_t = [_t.size_mm for _, _t in _mg.pairs(
                _mg.build(_r0, gabarit=_gt))]
            _fc = _mg.build(_r0, gabarit=_liv)
            _doc_c = Document()
            for _s in _fc:
                _doc_c.add(_s)
            for _c, _t in _mg.pairs(_fc):
                _c.data = 'A1'
                _cpm.propagate_data(_doc_c, _c)
            _gc = _gb.depuis_formes(_fc, _liv)
            check('gabarit : le texte garde sa taille d une pose a l autre',
                  all(abs(_v - _voulu) < 1e-3 for _v in _vus_t)
                  and _gb.depuis_formes(_mg.build(_r0, gabarit=_gt), _gt) == _gt
                  and _gc['texte'] == _liv['texte'],
                  f'agrandi {_voulu:.3f} mm, repose a {_vus_t[0]:.3f} mm · '
                  f'« A1 » ne retrecit pas la fenetre')

            _gref = _gb.depuis_formes(_fc, _liv, references=True)
            check('gabarit : les references saisies se proposent a la pose',
                  _gref['donnees'] == ['A1', 'A1', 'A1']
                  and [_c.data for _c, _ in _mg.pairs(
                      _mg.build(_r0, gabarit=_gref))] == ['A1', 'A1', 'A1']
                  and _gb.proposees(_g4i) == ['X1', 'B000181', 'X3', 'B000181'],
                  'une case vide ou absente reprend la reference du montage')

            # references courtes retenues : le texte ne fond pas
            _fcr = _mg.build(_r0, gabarit=_liv)
            _doc_cr = Document()
            for _s in _fcr:
                _doc_cr.add(_s)
            for (_c, _t), _v in zip(_mg.pairs(_fcr),
                                    ('B12', 'B000182', 'B000183')):
                _c.data = _v
                _cpm.propagate_data(_doc_cr, _c)
            _gcr = _gb.depuis_formes(_fcr, _liv, references=True)
            _tailles_cr = [_t.size_mm for _, _t in _mg.pairs(
                _mg.build(_r0, gabarit=_gcr))]
            check('gabarit : des references courtes retenues ne font pas '
                  'fondre le texte',
                  min(_tailles_cr) >= 1.176 - 1e-3
                  and max(_tailles_cr) <= 1.176 * 1.03,
                  ' / '.join(f'{_v:.3f}' for _v in _tailles_cr)
                  + ' mm a la pose suivante (1,176 avant)')

            # postes listes du bas vers le haut : chaque reference reste
            # sur son poste, a la pose comme a la relecture
            _gdes = _gb.verifier({'nom': 'Desordre', 'postes': ['A', 'B', 'C'],
                                  'positions_y_mm': [-10.0, 0.0, 10.0],
                                  'donnees': ['REFA', 'REFB', 'REFC']})
            _fdes = _mg.build(_r0, gabarit=_gdes)
            _gdes2 = _gb.depuis_formes(_fdes, _gdes)
            _form_des = _mg.MontageForm()
            _form_des.set_montage(_fdes, None, _gdes)
            _champ_a = _form_des._codes['a']
            check('gabarit : des postes listes dans le desordre gardent '
                  'leur reference',
                  _champ_a.data == 'REFA' and _champ_a.y == -10.0
                  and _gdes2['postes'] == ['C', 'B', 'A']
                  and _gdes2['donnees'] == ['REFC', 'REFB', 'REFA']
                  and _gb.depuis_formes(_mg.build(_r0, gabarit=_gdes2),
                                        _gdes2) == _gdes2,
                  'le champ A edite le code de A, en bas ; relu du haut '
                  'vers le bas, references comprises')

            # sans roles (montage d avant, assemble a la main) : le nom du
            # poste a sa hauteur ; l entraxe d un gabarit liste du bas vers
            # le haut garde chacun a sa place
            _gbh = _gb.verifier({'nom': 'BasHaut',
                                 'postes': ['BAS', 'HAUT', 'MILIEU'],
                                 'positions_y_mm': [-22.8, 23.2, 0.2],
                                 'donnees': ['b', 'h', 'm']})
            _fbh = _mg.build(_r0, gabarit=_gbh)
            for _c, _t in _mg.pairs(_fbh):
                _c.role = _t.role = ''
            _rbh = _gb.depuis_formes(_fbh, _gbh)
            _reg_bh = _mg.ReglagesMontage()
            _reg_bh.set_gabarit(_gbh)
            _reg_bh.w_entraxe.setValue(25.0)
            _ebh = _reg_bh.gabarit()
            _mauvais_t = 0
            for _m in ({'nom': 'X', 'code': 5}, {'nom': 'Y', 'positions_y_mm': 3}):
                try:
                    _gb.verifier(_m)
                except _gb.GabaritError:
                    _mauvais_t += 1
            check('gabarit : postes sans role ou listes a l envers, chacun '
                  'reste a sa hauteur',
                  _rbh['postes'] == ['HAUT', 'MILIEU', 'BAS']
                  and _rbh.get('donnees') == ['h', 'm', 'b']
                  and _ebh['postes'] == ['HAUT', 'MILIEU', 'BAS']
                  and _ebh.get('donnees') == ['h', 'm', 'b']
                  and [round(_y, 3) for _y in _gb.positions(_ebh)]
                  == [25.2, 0.2, -24.8]
                  and _mauvais_t == 2,
                  'relu et regularise du haut vers le bas, references '
                  'comprises · « code »: 5 refuse, pas une erreur de type')

            _frot = _mg.build(_r0, gabarit=_liv)
            for _s in _frot:
                _s.rotation_deg = 180.0
            try:
                _gb.depuis_formes(_frot, _liv)
                _refus_rot = False
            except _gb.GabaritError:
                _refus_rot = True
            check('gabarit : un montage tourne ne se relit ni ne se remet '
                  'aux cotes',
                  _refus_rot and _mg.appliquer(_frot, _liv) == [],
                  'ses positions et ses textes sont tournes, le gabarit non')

            _fa = _mg.build(_r0, gabarit=_liv, donnees={'haut': 'H1',
                                                        'milieu': 'M2',
                                                        'bas': 'B3'})
            _touches = _mg.appliquer(_fa, _gr)
            _pa = _mg.pairs(_fa)
            check('montage : un gabarit s applique a un montage pose',
                  len(_touches) == 6
                  and [round(_c.y, 3) for _c, _ in _pa] == [23.2, 0.2, -24.8]
                  and {_c.frame for _c, _ in _pa} == {'circle'}
                  and [_c.data for _c, _ in _pa] == ['H1', 'M2', 'B3']
                  and all(abs(_t.y - _c.y + 3.9) < 1e-9 for _c, _t in _pa),
                  'positions, cadre et texte suivent ; references intactes')

            # le fichier : une copie de l etat d avant, une fois par seance
            _gb.enregistrer([_liv])
            _premier = _fic_m.read_bytes()
            _gb._copie_faite = False
            _gb.enregistrer([_liv, _g4i])
            _gb.enregistrer([_g4i])
            check('gabarit : la premiere ecriture de la seance garde l etat d avant',
                  _copie_m.exists() and _copie_m.read_bytes() == _premier,
                  f'{_gb.AVANT} : l etat d ouverture, pas l avant-derniere '
                  f'retouche')
            # ce qu on n a pas su lire n est jamais efface
            _fic_m.write_bytes(b'\xef\xbb\xbf' + _json_m.dumps(
                {'montages': [_liv, {'nom': 'Faux', 'donnees': 'B1'}]}
            ).encode('utf-8'))
            _lus_bom = [_g['nom'] for _g in _gb.charger()]
            _gb.remplacer(dict(_liv, x_mm=1.0))
            _ecrits = [_g.get('nom') for _g in _json_m.loads(
                _fic_m.read_text(encoding='utf-8'))['montages']]
            _fic_m.write_text('{ casse', encoding='utf-8')
            try:
                _gb.remplacer(_liv)
                _refus_ill = False
            except _gb.GabaritError:
                _refus_ill = True
            check('gabarit : un montage refuse ou un fichier illisible ne '
                  'sont jamais ecrases',
                  _lus_bom == ['Montage 3 DataMatrix']
                  and _ecrits == ['Montage 3 DataMatrix', 'Faux']
                  and _refus_ill
                  and _fic_m.read_text(encoding='utf-8') == '{ casse',
                  'BOM du Bloc-notes lu · « Faux » reecrit tel quel · '
                  'fichier casse laisse intact')
            _fic_m.unlink()
            _fus, _plus, _memes = _gb.fusionner(
                [_liv], [_liv, dict(_liv, entraxe_mm=20.0)])
            check('gabarit : importer ajoute sans rien remplacer',
                  (_plus, _memes) == (1, 1)
                  and [_g['nom'] for _g in _fus]
                  == ['Montage 3 DataMatrix', 'Montage 3 DataMatrix (2)'],
                  'identique ignore, homonyme renomme')

            # --- a l interface ---
            _gb.enregistrer([_liv, _g4i])
            _ong_m = window.new_tab(Document(name='montages'))
            app.processEvents()
            window._fill_montage_menu()
            _forme_fl = next(
                (_a.defaultWidget() for _a in window.w_montage_menu.actions()
                 if isinstance(_a, _QWA)), None)
            _textes_fl = [_a.text() for _a in window.w_montage_menu.actions()]
            window.w_montage_form.w_reglages.w_marge.setValue(0.7)
            app.processEvents()
            check('montage : la fleche porte le prochain montage, enregistre',
                  isinstance(_forme_fl, _mp.ProchainMontage)
                  and _gb.charger()[0]['code']['marge_cadre_mm'] == 0.7
                  and 'Poser « Quatre »' in _textes_fl
                  and 'Gestionnaire de montages…' in _textes_fl,
                  'marge 0,7 ecrite au premier champ · gabarits et '
                  'gestionnaire au bout de la fleche')
            window.w_montage_form.w_choix.setCurrentIndex(1)
            app.processEvents()
            _tete = _gb.charger()[0]['nom']
            window.w_montage_form.w_choix.setCurrentIndex(1)
            app.processEvents()
            check('montage : choisir un montage a la fleche le met en tete',
                  _tete == 'Quatre'
                  and _gb.charger()[0]['nom'] == 'Montage 3 DataMatrix',
                  'le bouton pose celui qu on vient de choisir')

            # le formulaire de la pose retouche le montage entier
            window._add_montage()
            app.processEvents()
            _fp = window.montage_form
            _fp.w_reglages.w_entraxe.setValue(25.0)
            app.processEvents()
            _codes_p = sorted((_s for _s in window.document.shapes
                               if isinstance(_s, _CodeM)), key=lambda s: -s.y)
            _suit = all(any(isinstance(_t, _TextM) and _t.follows == _c.id
                            and abs(_t.y - _c.y + 3.9) < 1e-9
                            for _t in window.document.shapes)
                        for _c in _codes_p)
            check('montage : le formulaire de la pose deplace tout le montage',
                  [round(_c.y, 3) for _c in _codes_p] == [25.2, 0.2, -24.8]
                  and _suit and _fp._base_nom == 'Montage 3 DataMatrix'
                  and len(window.canvas.selected_ids()) == 6,
                  'entraxe 25 : trois postes, textes suivis, selection gardee')
            _ecrit_m = _fp.enregistrer_gabarit()
            window._add_montage()
            app.processEvents()
            _codes_s = sorted((_s for _s in window.canvas.selected_shapes()
                               if isinstance(_s, _CodeM)), key=lambda s: -s.y)
            check('montage : enregistre au formulaire, repris a la pose suivante',
                  _ecrit_m == 'Montage 3 DataMatrix'
                  and _gb.charger()[0]['entraxe_mm'] == 25.0
                  and [round(_c.y, 3) for _c in _codes_s] == [25.2, 0.2, -24.8],
                  'le gabarit retient l entraxe 25')
            _nouveau_m = _fp.enregistrer_gabarit('Essai retouche')
            window._fill_montage_menu()
            check('montage : « comme nouveau » parait au bout de la fleche',
                  _nouveau_m == 'Essai retouche'
                  and 'Poser « Essai retouche »' in [
                      _a.text() for _a in window.w_montage_menu.actions()]
                  and _gb.charger()[0]['nom'] == 'Montage 3 DataMatrix',
                  'range a la fin, sans toucher au gabarit d origine')

            # la copie porte les memes postes que l original : la
            # resaisir ne doit pas la confondre avec lui
            def _ids_de(codes):
                return ([_c.id for _c in codes]
                        + [_t.id for _t in window.document.shapes
                           if isinstance(_t, _TextM)
                           and _t.follows in {_c.id for _c in codes}])
            window.canvas.select_many(_ids_de(_codes_p))
            app.processEvents()
            window.canvas.select_many(_ids_de(_codes_s))
            app.processEvents()
            _origine_m = _fp._base_nom
            _fp._origines.clear()
            window.canvas.select_many(_ids_de(_codes_p))
            app.processEvents()
            window.canvas.select_many(_ids_de(_codes_s))
            app.processEvents()
            check('montage : une copie resaisie n est pas prise pour '
                  'l original',
                  _origine_m == 'Essai retouche' and _fp._base_nom == ''
                  and set(_fp._ambigus) == {'Montage 3 DataMatrix',
                                            'Essai retouche'}
                  and not _fp.w_enregistrer.isEnabled(),
                  'retrouvee par la seance ; sans elle, deux gabarits '
                  'identiques : aucun n est ecrase')

            # la copie supprimee au gestionnaire : l ambiguite tombe
            _g_essai = next(_g for _g in _gb.charger()
                            if _g['nom'] == 'Essai retouche')
            _gb.enregistrer([_g for _g in _gb.charger()
                             if _g['nom'] != 'Essai retouche'])
            window._gabarits_changed()
            _leve_m = (_fp._base_nom == 'Montage 3 DataMatrix'
                       and not _fp._ambigus and _fp.w_enregistrer.isEnabled())
            _gb.remplacer(_g_essai)
            window._gabarits_changed()
            check('montage : la copie supprimee, le formulaire retrouve '
                  'l original',
                  _leve_m and _fp._base_nom == 'Montage 3 DataMatrix',
                  'relu a chaque ecriture du fichier, sans resaisir le '
                  'montage')

            # « Poser » au bout de la fleche relit le gabarit au clic
            window._fill_montage_menu()
            _poser_m3 = next(_a for _a in window.w_montage_menu.actions()
                             if _a.text() == 'Poser « Montage 3 DataMatrix »')
            window.w_montage_form.w_reglages.w_entraxe.setValue(24.0)
            app.processEvents()
            _poser_m3.trigger()
            app.processEvents()
            _codes_24 = sorted((_s for _s in window.canvas.selected_shapes()
                                if isinstance(_s, _CodeM)),
                               key=lambda s: -s.y)
            check('montage : « Poser » au bout de la fleche prend les cotes '
                  'du moment',
                  [round(_c.y, 3) for _c in _codes_24] == [24.2, 0.2, -23.8],
                  'entraxe change dans le menu ouvert, puis pose : 24 mm')

            # le gestionnaire
            window._toggle_montages()
            app.processEvents()
            _gm = window.montages_panel
            _ouvert_m = (window.center.currentIndex() == 3
                         and not window._dock_insp.isVisible()
                         and window.w_montages_action.text()
                         == 'Fermer les montages'
                         and _gm.w_list.count() == len(_gb.charger()))
            # le fichier change d ordre pendant que le gestionnaire est
            # ouvert : il garde le montage choisi, pas son rang
            _gm._remplit_liste(1)
            _choisi_m = _gm.courant()['nom']
            _gb.mettre_en_tete(_gb.charger()[-1]['nom'])
            _gm.relire_si_propre()
            _garde_m = _gm.courant()['nom'] == _choisi_m
            _gb.mettre_en_tete('Montage 3 DataMatrix')
            _gm.relire_si_propre()
            _gm._remplit_liste(0)
            check('montages : relu, le gestionnaire garde le montage choisi',
                  _garde_m and _gm.courant()['nom'] == 'Montage 3 DataMatrix',
                  f'« {_choisi_m} » toujours en edition apres un changement '
                  f'd ordre')
            _octets = _fic_m.read_bytes()
            _gm._dupliquer()
            _gm._ajoute_poste()
            _gm.w_postes.item(3, 1).setText('-40')
            app.processEvents()
            _gm._minuterie.timeout.emit()
            _en_cours = _gm.courant()
            window._fill_montage_menu()
            _verrou = not window.w_montage_form.w_reglages.isEnabled()
            check('montages : le gestionnaire prend le plan et la colonne 3',
                  _ouvert_m and _gm.dirty()
                  and _en_cours['positions_y_mm'][-1] == -40.0
                  and len(_en_cours['postes']) == 4
                  and _fic_m.read_bytes() == _octets and _verrou
                  and _gm.w_apercu.emprise() is not None,
                  'duplique, un poste ajoute a -40 mm, apercu ; rien d ecrit, '
                  'fleche verrouillee')
            # un autre a ecrit le fichier pendant ce temps : on demande
            _question_m = _mp.QMessageBox.question
            _fic_avant_ext = _fic_m.read_bytes()
            _gb.remplacer(dict(_gb.charger()[-1], donnee='EXT1'))
            try:
                _mp.QMessageBox.question = staticmethod(
                    lambda *a, **k: _mp.QMessageBox.No)
                _refus_ext = (not _gm.enregistrer()
                              and b'EXT1' in _fic_m.read_bytes())
                _mp.QMessageBox.question = staticmethod(
                    lambda *a, **k: _mp.QMessageBox.Yes)
                _enr_m = _gm.enregistrer()
            finally:
                _mp.QMessageBox.question = _question_m
            check('montages : le gestionnaire n ecrase pas sans le dire un '
                  'fichier change',
                  _refus_ext and _enr_m and _fic_avant_ext != _fic_m.read_bytes(),
                  'fichier ecrit ailleurs : refus garde, accord ecrit')
            _gm._poser()
            app.processEvents()
            _poses = [_s for _s in window.canvas.selected_shapes()
                      if isinstance(_s, _CodeM)]
            check('montages : enregistrer, puis poser le montage choisi',
                  _enr_m and len(_gb.charger()) == 4
                  and window.center.currentIndex() == 0
                  and window._dock_insp.isVisible() and len(_poses) == 4
                  and round(min(_c.y for _c in _poses), 3) == -40.0,
                  'quatre postes poses, plan et proprietes rendus')
            _imp = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-mtg-'))
            (_imp / 'm.json').write_text(_json_m.dumps({'montages': [
                _gb.charger()[0], dict(_g4i, entraxe_mm=11.0,
                                       positions_y_mm=[1.0, 0.0, -1.0, -2.0]),
                {'nom': 'Faux', 'postes': []}]}), encoding='utf-8')
            window._toggle_montages()
            app.processEvents()
            _res_imp = _gm.importer_fichier(_imp / 'm.json')
            _noms_imp = [_g['nom'] for _g in _gm.montages()]
            _gm.reload()
            window._library()
            app.processEvents()
            check('montages : importer ajoute, la bibliotheque prend la place',
                  _res_imp[:2] == (1, 1) and len(_res_imp[2]) == 1
                  and 'Quatre (2)' in _noms_imp
                  and window.center.currentIndex() == 2
                  and window.w_montages_action.text() == 'Montages…',
                  f'{_res_imp[0]} ajoute, {_res_imp[1]} identique(s), '
                  f'{len(_res_imp[2])} refuse · bouton rendu')
            window._leave_library()
            shutil.rmtree(_imp, ignore_errors=True)
        finally:
            if _avant_fic_m is None:
                _fic_m.unlink(missing_ok=True)
            else:
                _fic_m.write_bytes(_avant_fic_m)
            _copie_m.unlink(missing_ok=True)
            window.tabs.setCurrentWidget(workbench)
            app.processEvents()

        # --- la case « Enchainer les traces », en colonne 1 et au
        # gestionnaire, pose bien le champ de la process. L onglet des
        # formes d essai d abord : le precedent controle a rendu la main a
        # l etabli, ou `_r1` n existe pas.
        window.tabs.setCurrentWidget(_ong_s)
        app.processEvents()
        window.canvas.select_many([_r1.id])
        app.processEvents()
        _case_c1 = window.recipe.w_link
        _case_c1.setChecked(True)
        app.processEvents()
        _pose_c1 = _r1.recipe.link_paths
        _case_c1.setChecked(False)
        app.processEvents()
        _gest = window.recipes_panel
        _gest._select_rang(0)
        app.processEvents()
        _gest.w_link.setChecked(True)
        app.processEvents()
        _pose_g = _gest.recipes[_gest._current].link_paths
        _resume_g = recipes._summary(_gest.recipes[_gest._current])
        _gest.w_link.setChecked(False)
        app.processEvents()
        check('enchainer : la case se coche en colonne 1 et au gestionnaire',
              _pose_c1 is True and _r1.recipe.link_paths is False
              and _pose_g is True and 'enchaîné' in _resume_g,
              'colonne 1 et gestionnaire · « enchaîné » dans le résumé')

        # le style de remplissage, aux deux memes endroits
        window.canvas.select_many([_r1.id])
        app.processEvents()
        _st_c1 = window.recipe.w_fill
        _st_c1.setCurrentIndex(_st_c1.findData('rings'))
        app.processEvents()
        _pose_st = _r1.recipe.fill_style
        _gris_st = not window.recipe.w_hcross.isEnabled()
        window.recipe.w_fill.setCurrentIndex(
            window.recipe.w_fill.findData('hatch'))
        app.processEvents()
        _gest.w_fill.setCurrentIndex(_gest.w_fill.findData('rings'))
        app.processEvents()
        _pose_gst = _gest.recipes[_gest._current].fill_style
        _resume_gst = recipes._summary(_gest.recipes[_gest._current])
        _gris_gst = not _gest.w_hangle.isEnabled()
        _gest.w_fill.setCurrentIndex(_gest.w_fill.findData('hatch'))
        app.processEvents()
        check('anneaux : le style se choisit en colonne 1 et au gestionnaire',
              _pose_st == 'rings' and _r1.recipe.fill_style == 'hatch'
              and _gris_st and _pose_gst == 'rings' and _gris_gst
              and _gest.recipes[_gest._current].fill_style == 'hatch'
              and ('anneaux' in _resume_gst
                   or _gest.recipes[_gest._current].hatch_mm <= 0),
              'colonne 1 et gestionnaire · angle et croisement grises')
        import re as _re_st
        import dataclasses as _dc_st
        _rec_st = _r1.recipe
        _r1.recipe = _dc_st.replace(_rec_st, hatch_mm=0.05,
                                         link_paths=False)
        window.canvas.refresh(_r1.id)
        window._invalidate()
        window._update_status()
        _avant_st = window.statusBar().currentMessage()
        _r1.recipe = _dc_st.replace(_r1.recipe, link_paths=True)
        window.canvas.refresh(_r1.id)
        window._invalidate()
        window._update_status()
        _apres_st = window.statusBar().currentMessage()
        _r1.recipe = _rec_st
        window.canvas.refresh(_r1.id)
        window._invalidate()

        def _allum(_m):
            _t = _re_st.search(r'(\d+) allumage', _m)
            return int(_t.group(1)) if _t else -1
        check('barre d etat : les allumages se lisent, et baissent enchaines',
              _allum(_avant_st) > _allum(_apres_st) > 0,
              f'{_allum(_avant_st)} → {_allum(_apres_st)} allumages')
        window.tabs.setCurrentWidget(workbench)
        app.processEvents()

        # --- démarrage : onglets en attente (EX-266) ----------------------
        #
        # Une seconde fenêtre rouvre un instantané de cinq onglets : seul
        # celui qui était devant est relu et monté ; les autres attendent
        # le clic, et se réécrivent tels qu'ils ont été lus. Le bac de
        # session est celui de l'autotest : le poste n'est pas touché.
        import copy as _copy_dm
        import dataclasses as _dc_dm
        import json as _json_dm
        import engrave.app as _app_dm
        from engrave import serialize as _ser_dm, splitting as _spl_dm
        from engrave import toolpath as _tp_dm
        from engrave.model import (Circle as _Circle_dm, Document as _Doc_dm,
                                   Path as _Path_dm, Rect as _Rect_dm,
                                   Text as _Text_dm)
        from PySide6.QtCore import Qt as _Qt_dm
        from PySide6.QtGui import QAction as _QAction_dm
        from PySide6.QtGui import QKeySequence as _QKS_dm
        from PySide6.QtCore import QEvent as _QEvent_dm
        from PySide6.QtGui import QKeyEvent as _QKeyEvent_dm
        from PySide6.QtWidgets import QLineEdit as _QLE_dm
        _rec_dm = PRESET_RECIPES[1]

        def _brut_dm(nom, *formes):
            _d = _Doc_dm(name=nom)
            for _f in formes:
                _d.add(_f)
            # tel que l'instantané le rend : passé par le texte JSON
            return _json_dm.loads(_json_dm.dumps(
                _ser_dm.document_to_dict(_d)))

        _entrees_dm = [
            {'path': '', 'dirty': False, 'document': _brut_dm(
                'plaque A', _Rect_dm(width=12, height=6, recipe=_rec_dm))},
            {'path': '', 'dirty': False, 'actif': True, 'document': _brut_dm(
                'plaque B', _Rect_dm(width=20, height=8, recipe=_rec_dm),
                _Text_dm(text='B', size_mm=5, recipe=_rec_dm))},
            {'path': '', 'dirty': True, 'document': _brut_dm(
                'plaque C', _Text_dm(text='C 12', size_mm=4, recipe=_rec_dm))},
            {'path': '', 'dirty': False,
             'document': {'name': 'abîmé', 'shapes': 5}},
            {'path': '', 'dirty': False,
             'document': {'name': 'reprise', 'field_w': 'abc'}},
        ]
        _ses_bac.save_snapshot(_entrees_dm)
        _passes_dm = [0]
        _bp_dm = _app_dm.build_passes

        def _compte_bp_dm(*_a, **_k):
            _passes_dm[0] += 1
            return _bp_dm(*_a, **_k)
        _app_dm.build_passes = _compte_bp_dm
        try:
            _w2 = _app_dm.MainWindow()
        finally:
            _app_dm.build_passes = _bp_dm
        app.processEvents()
        _ong_dm = _w2.tabs_all()
        _att_dm = [_t.en_attente() for _t in _ong_dm]
        check("démarrage : seul l'onglet de devant est relu et monté, les "
              "autres attendent le clic (EX-266)",
              len(_ong_dm) == 5 and _w2.tabs.currentIndex() == 1
              and _att_dm == [True, False, True, True, True]
              and [_t.monte for _t in _ong_dm]
              == [False, True, False, False, False]
              and all(not _t._items for _i, _t in enumerate(_ong_dm)
                      if _i != 1)
              and _passes_dm[0] == 1,
              f'{len(_ong_dm)} onglets, devant le n° '
              f'{_w2.tabs.currentIndex() + 1} · {_att_dm.count(True)} en '
              f'attente · trajectoires calculées {_passes_dm[0]} fois')
        _titres_dm = [_w2.tabs.tabText(_i) for _i in range(len(_ong_dm))]
        check('onglet en attente : son nom et son étoile, sans relecture',
              _titres_dm == ['plaque A', 'plaque B', '* plaque C', 'abîmé',
                             'reprise']
              and [_t.en_attente() for _t in _ong_dm] == _att_dm,
              ' · '.join(_titres_dm))
        for _t in _ong_dm:
            _t.restyle()
        _w2._invalidate()
        _w2._save_session()
        _relu_dm = _ses_bac.load_snapshot()
        check("instantané : un onglet en attente se réécrit tel qu'il a été "
              "lu, l'onglet de devant y est marqué",
              len(_relu_dm) == 5
              and all(_relu_dm[_i].get('document')
                      == _entrees_dm[_i]['document'] for _i in (0, 2, 3, 4))
              and [bool(_e.get('actif')) for _e in _relu_dm]
              == [False, True, False, False, False]
              and [_t.en_attente() for _t in _ong_dm] == _att_dm,
              'thème, réglages et instantané sans relire les onglets')
        _rap_dm = []
        _w2._report_repairs = lambda _nom, _r, quiet=False: _rap_dm.append(
            (_nom, list(_r)))
        _w2.tabs.setCurrentIndex(0)
        app.processEvents()
        _t0_dm = _ong_dm[0]
        _attendu_dm = _ser_dm.document_to_dict(
            _ser_dm.document_from_dict(_entrees_dm[0]['document']))
        check('premier clic : le document est relu et posé, sans étoile ni '
              'annulation',
              _t0_dm.monte and not _t0_dm.en_attente()
              and len(_t0_dm._items) == 1 and not _t0_dm.dirty
              and _w2.tabs.tabText(0) == 'plaque A'
              and _ser_dm.document_to_dict(_t0_dm.document) == _attendu_dm
              and _t0_dm.history.depth() == (0, 0)
              and 'forme(s)' in _w2.statusBar().currentMessage(),
              _w2.statusBar().currentMessage()[:60])
        _w2.tabs.setCurrentIndex(2)
        _w2.tabs.setCurrentIndex(3)
        _w2.tabs.setCurrentIndex(4)
        app.processEvents()
        _w2._save_session()
        _relu_dm = _ses_bac.load_snapshot()
        check('clic sur un contenu illisible : un onglet vide à son nom, le '
              'contenu gardé ; valeurs remplacées dites au clic',
              _ong_dm[2].dirty and _w2.tabs.tabText(2) == '* plaque C'
              and not _ong_dm[3].document.shapes
              and _ong_dm[3].document.name == 'abîmé'
              and _relu_dm[3].get('document') == {'name': 'abîmé',
                                                  'shapes': 5}
              and len(_rap_dm) == 1 and _rap_dm[0][0] == 'reprise'
              and 'field_w' in ' '.join(_rap_dm[0][1]),
              f'{len(_rap_dm)} compte rendu : '
              f'{_rap_dm[0][1][0][:40] if _rap_dm else "aucun"}')
        _ses_bac.save_snapshot([{_k: _v for _k, _v in _e.items()
                                 if _k != 'actif'}
                                for _e in _entrees_dm[:3]])
        _w3 = _app_dm.MainWindow()
        app.processEvents()
        check("instantané d'une version antérieure : le dernier onglet "
              "devant, comme avant",
              _w3.tabs.count() == 3 and _w3.tabs.currentIndex() == 2
              and _w3.tabs_all()[0].en_attente()
              and not _w3.tabs_all()[2].en_attente(),
              f'{_w3.tabs.count()} onglets, devant le n° '
              f'{_w3.tabs.currentIndex() + 1}')
        for _w in (_w2, _w3):
            _w._session_timer.stop()
            _w.deleteLater()
        app.processEvents()
        window._save_session()

        # --- totaux du travail : une liste partagée, mesurée une fois ------
        _r20_dm = _Rect_dm(width=8, height=8, recipe=_dc_dm.replace(
            _rec_dm, passes=20, hatch_mm=0.1))
        _doc20_dm = _Doc_dm()
        _doc20_dm.add(_r20_dm)
        _ps20_dm = _tp_dm.build_passes(_doc20_dm, optimize=True,
                                       group_by_recipe=False)
        _n20_dm = sum(1 for _p in _ps20_dm[0].polylines if len(_p) > 1)
        _mes_dm = _tp_dm._mesure
        _cpt_dm = [0]

        def _mesure_cpt_dm(_poly):
            _cpt_dm[0] += 1
            return _mes_dm(_poly)
        _tp_dm._mesure = _mesure_cpt_dm
        try:
            _neuf_dm = (_tp_dm.total_length_mm(_ps20_dm),
                        _tp_dm.total_travel_mm(_ps20_dm),
                        _tp_dm.total_duration_s(_ps20_dm))
        finally:
            _tp_dm._mesure = _mes_dm
        _lg_dm = sum(_p.length_mm() for _p in _ps20_dm)
        _tr_dm, _du_dm = 0.0, 0.0
        _c_dm = (0.0, 0.0)
        for _p in _ps20_dm:
            _tr_dm += _p.travel_mm(_c_dm)
            _du_dm += _p.duration_s(_c_dm)
            _c_dm = _p.end_point(_c_dm)
        check('totaux du travail : vingt passes sur les mêmes traits, '
              'mesurés une fois, au bit près (EX-266)',
              len(_ps20_dm) == 20
              and len({id(_p.polylines) for _p in _ps20_dm}) == 1
              and [_x.hex() for _x in _neuf_dm]
              == [_x.hex() for _x in (_lg_dm, _tr_dm, _du_dm)]
              and _cpt_dm[0] == _n20_dm,
              f'{_n20_dm} traits : {_cpt_dm[0]} mesures au lieu de '
              f'{20 * _n20_dm} · longueur, trajet et durée identiques')

        # --- Q groupe, S dégroupe, Ctrl+G combine, Ctrl+Maj+G décombine ----
        _raccs_dm: dict = {}
        for _a in window.findChildren(_QAction_dm):
            _k = _a.shortcut().toString(_QKS_dm.PortableText)
            if _k:
                _raccs_dm.setdefault(_k, []).append(_a.text())
        _voulus_dm = {'Q': 'Grouper', 'S': 'Dégrouper',
                      'Ctrl+G': 'Combiner', 'Ctrl+Shift+G': 'Décombiner',
                      'Alt+W': 'Centrer dans le champ',
                      'Ctrl+I': 'Importer un dessin…'}
        check('raccourcis : Q groupe, S dégroupe, Ctrl+G combine, Ctrl+Maj+G '
              'décombine, Alt+W centre, Ctrl+I importe — chacun seul à le '
              'réclamer (EX-267)',
              all(_raccs_dm.get(_k) == [_v] for _k, _v in _voulus_dm.items())
              and all(_a.shortcutContext() == _Qt_dm.WidgetWithChildrenShortcut
                      and window.tabs in _a.associatedObjects()
                      and window.shape_list in _a.associatedObjects()
                      for _a in (window.w_grouper, window.w_degrouper))
              and all(_a.shortcutContext() == _Qt_dm.WindowShortcut
                      for _a in (window.w_combine, window.w_uncombine)),
              ' · '.join(f'{_k} {_v}' for _k, _v in _voulus_dm.items()))

        _onglet_cb = window.new_tab()

        def _poser_cb(*_formes):
            window.document.shapes = list(_formes)
            window.canvas.reload()
            window._refresh_list()
            window.canvas.select_many([_f.id for _f in _formes])
            app.processEvents()

        def _graves_cb(_formes):
            _d = _Doc_dm()
            _d.shapes = list(_formes)
            _ps = _tp_dm.build_passes(_d, optimize=False,
                                      group_by_recipe=False)
            return (sorted((round(_x, 6), round(_y, 6)) for _p in _ps
                           for _q in _p.polylines for _x, _y in _q),
                    _tp_dm.total_length_mm(_ps))

        def _memes_cb(_a, _b):
            return (len(_a[0]) == len(_b[0])
                    and abs(_a[1] - _b[1]) <= 1e-6 * max(1.0, _b[1])
                    and max((abs(_p[0] - _q[0]) + abs(_p[1] - _q[1])
                             for _p, _q in zip(_a[0], _b[0])),
                            default=0.0) < 1e-5)
        _carre_cb = _Rect_dm(width=30, height=30, recipe=_rec_dm)
        _carre_cb.x, _carre_cb.y = 10, 5
        _rond_cb = _Circle_dm(width=10, height=10, recipe=_rec_dm)
        _rond_cb.x, _rond_cb.y = 12, 4
        _texte_cb = _Text_dm(text='TAU', size_mm=6, recipe=_rec_dm)
        _texte_cb.x, _texte_cb.y, _texte_cb.rotation_deg = -20, -15, 30
        _groupe_cb = [_copy_dm.deepcopy(_f)
                      for _f in (_carre_cb, _rond_cb, _texte_cb)]
        for _f in _groupe_cb:
            _f.group = 'g'
        _ref_cb = _graves_cb(_groupe_cb)
        _poser_cb(_carre_cb, _rond_cb, _texte_cb)
        window.w_grouper.trigger()
        app.processEvents()
        _gq_cb = {_f.group for _f in window.document.shapes}
        window.w_degrouper.trigger()
        app.processEvents()
        _gs_cb = {_f.group for _f in window.document.shapes}
        check('Grouper (Q) puis Dégrouper (S) : un groupe, puis plus aucun',
              len(_gq_cb) == 1 and bool(next(iter(_gq_cb)))
              and _gs_cb == {''} and len(window.document.shapes) == 3,
              f'groupes après Q : {len(_gq_cb)} · après S : '
              f'{sorted(_gs_cb)}')
        _poser_cb(_carre_cb, _rond_cb, _texte_cb)
        window.w_combine.trigger()
        app.processEvents()
        _q_cb = list(window.document.shapes)
        _ok_q = (len(_q_cb) == 1 and isinstance(_q_cb[0], _Path_dm)
                 and _q_cb[0].recipe == _rec_dm
                 and _memes_cb(_graves_cb(_q_cb), _ref_cb))
        window.canvas.select_many([_q_cb[0].id])
        window.w_uncombine.trigger()
        app.processEvents()
        _s_cb = list(window.document.shapes)
        _ok_s = (len(_s_cb) == len(_q_cb[0].polylines)
                 and len({_f.group for _f in _s_cb}) == 1
                 and bool(_s_cb[0].group)
                 and _memes_cb(_graves_cb(_s_cb), _ref_cb))
        check('Combiner (Ctrl+G) : un seul tracé, gravé comme leur groupe ; '
              'Décombiner (Ctrl+Maj+G) le rend en morceaux groupés (EX-266)',
              _ok_q and _ok_s,
              f'3 formes → 1 tracé de '
              f'{len(_q_cb[0].polylines) if _q_cb else 0} polylignes → '
              f'{len(_s_cb)} morceaux · {_ref_cb[1]:.3f} mm gravés')
        _ob_cb = _Text_dm(text='OB', size_mm=5, recipe=_rec_dm)
        _ref_ob = _graves_cb([_copy_dm.deepcopy(_ob_cb)])
        _poser_cb(_ob_cb)
        window.w_uncombine.trigger()
        app.processEvents()
        _m_ob = list(window.document.shapes)
        check('Décombiner un texte : ses contours, groupés — les trous du '
              '« O » et du « B » restent des trous',
              len(_m_ob) == len(_tp_dm.own_contours(_ob_cb)) >= 3
              and all(isinstance(_f, _Path_dm) for _f in _m_ob)
              and len({_f.group for _f in _m_ob}) == 1
              and _memes_cb(_graves_cb(_m_ob), _ref_ob),
              f'« OB » → {len(_m_ob)} morceaux')
        _seul_cw = _Rect_dm(width=10, height=4, recipe=_rec_dm)
        _seul_cw.x, _seul_cw.y = 30, -20
        _poser_cb(_seul_cw)
        window.w_center_sel.trigger()
        _un_cw = (round(_seul_cw.x, 9), round(_seul_cw.y, 9))
        _ga_cw = _Rect_dm(width=10, height=4, recipe=_rec_dm)
        _dr_cw = _Rect_dm(width=10, height=4, recipe=_rec_dm)
        _ga_cw.x, _ga_cw.y, _dr_cw.x, _dr_cw.y = 30, 10, 50, 10
        _poser_cb(_ga_cw, _dr_cw)
        window.w_center_sel.trigger()
        check('Centrer (Alt+W) : une forme comme une sélection, au centre du '
              'champ, sans changer leur écart',
              _un_cw == (0.0, 0.0)
              and abs(_ga_cw.x + 10) < 1e-9 and abs(_dr_cw.x - 10) < 1e-9
              and abs(_ga_cw.y) < 1e-9 and abs(_dr_cw.y) < 1e-9,
              f'une forme en {_un_cw} · deux en ({_ga_cw.x:g}, {_ga_cw.y:g}) '
              f'et ({_dr_cw.x:g}, {_dr_cw.y:g})')
        # Avant tout raccourci, Qt demande au widget qui a le focus s'il
        # veut la touche pour lui (`ShortcutOverride`) : un champ réclame
        # une lettre, le plan de travail et la liste des formes la
        # laissent au raccourci. Pas de frappe simulée — `QtTest` n'est pas
        # embarqué dans l'exécutable.
        def _reclame_dm(_widget, _touche, _texte):
            _ev = _QKeyEvent_dm(_QEvent_dm.ShortcutOverride, _touche,
                                _Qt_dm.NoModifier, _texte)
            _ev.ignore()
            app.sendEvent(_widget, _ev)
            return _ev.isAccepted()
        _champ_dm = _QLE_dm(window)
        _lettres_dm = [(_k, _t) for _k, _t in ((_Qt_dm.Key_Q, 'q'),
                                                (_Qt_dm.Key_S, 's'))]
        _au_champ = all(_reclame_dm(_champ_dm, _k, _t)
                        for _k, _t in _lettres_dm)
        _au_dessin = not any(_reclame_dm(_w, _k, _t)
                             for _w in (window.canvas, window.shape_list)
                             for _k, _t in _lettres_dm)
        _champ_dm.deleteLater()
        check('Q et S : une lettre dans un champ, un geste sur le dessin',
              _au_champ and _au_dessin,
              f'le champ les {"garde" if _au_champ else "LAISSE"} · le plan '
              f'et la liste les {"laissent" if _au_dessin else "GARDENT"} '
              f'au raccourci')
        window._close_tab(window.tabs.indexOf(_onglet_cb))
        window.tabs.setCurrentWidget(workbench)
        app.processEvents()

        # --- l'éditeur de process ne laisse aucun formulaire en fenêtre ----
        _avant_tl = {id(_x) for _x in app.topLevelWidgets() if _x.isVisible()}
        window.recipe.set_shape(_Rect_dm(width=5, height=5, recipe=_rec_dm))
        window.recipe.set_shape(None)
        app.processEvents()
        _seuls_tl = [_x for _x in app.topLevelWidgets()
                     if _x.isVisible() and id(_x) not in _avant_tl]
        check("éditeur de process reconstruit deux fois d'affilée : aucun "
              "formulaire ne paraît en fenêtre à part",
              not _seuls_tl, f'{len(_seuls_tl)} fenêtre(s) en trop')
        window._selection_changed()
        app.processEvents()

    if domaine('dossiers'):
        # --- mémoire des dossiers : un usage, un chemin --------------------------
        #
        # `start_folder` promettait dans sa propre docstring de reprendre le
        # dernier emplacement employé, et ne le lisait jamais : le dossier
        # était enregistré puis ignoré. Et quatre usages — ouvrir,
        # enregistrer, exporter, régler — partageaient une seule mémoire.

        import shutil
        import tempfile

        _bacs = {}
        for _usage, _ in session.BROWSE_KINDS:
            _bacs[_usage] = pathlib.Path(tempfile.mkdtemp(prefix=f'{_usage}-'))
            session.remember_folder(_usage, str(_bacs[_usage]))
        session.forget_reachability()

        _chacun = all(session.start_folder(_u) == str(_bacs[_u])
                      for _u, _ in session.BROWSE_KINDS)
        check('dossiers : chaque usage garde son dernier chemin, sans déborder',
              _chacun and len(session.BROWSE_KINDS) >= 5,
              ' · '.join(u for u, _ in session.BROWSE_KINDS))

        _regle = pathlib.Path(tempfile.mkdtemp(prefix='regle-'))
        session.set_default_folder('documents', str(_regle))
        session.forget_reachability()
        check('dossiers : le dernier employé passe devant le réglage',
              session.start_folder('documents') == str(_bacs['documents']),
              'le réglage sert de point de départ, pas de laisse')

        session.set_default_folder('export', str(_regle))
        session.remember_folder('export', str(_bacs['documents']))
        session.forget_reachability()
        check('dossiers : pour l' + chr(39) + 'export machine, le réglage '
              'l' + chr(39) + 'emporte',
              session.start_folder('export') == str(_regle)
              and 'export' in session.POLICY_KINDS,
              'décision d' + chr(39) + 'atelier, pas habitude de navigation')

        _fichier = _bacs['dxf'] / 'plan.dxf'
        _fichier.write_text('x', encoding='utf-8')
        session.remember_file('reglages', str(_fichier))
        check('dossiers : retenir un fichier retient son dossier',
              session.last_folder('reglages') == str(_bacs['dxf']),
              'plus besoin d' + chr(39) + 'extraire le parent à chaque appel')

        _parti = _bacs['enregistrer']
        shutil.rmtree(_parti, ignore_errors=True)
        session.forget_reachability()
        check('dossiers : un dossier disparu ne bloque pas le sélecteur',
              session.start_folder('enregistrer') != str(_parti)
              and session.last_folder('enregistrer') == str(_parti),
              'sauté à l' + chr(39) + 'ouverture, gardé en mémoire — un partage '
              'revient')

        # tous les sélecteurs doivent être appariés : un départ, une mémoire
        import re as _re
        _sources = [pathlib.Path('src/engrave') / f for f in
                    ('app.py', 'coupon.py', 'librarypanel.py')]
        _ouvre = _garde = 0
        for _src in _sources:
            _txt = _src.read_text(encoding='utf-8')
            _ouvre += len(_re.findall(r'get(?:Open|Save)FileName', _txt))
            _garde += len(_re.findall(r'session\.remember_file', _txt))
        check('dossiers : chaque sélecteur de fichier retient où il est allé',
              _garde >= _ouvre - 1,
              f'{_ouvre} sélecteur(s) · {_garde} mémorisation(s)')

        for _d in _bacs.values():
            shutil.rmtree(_d, ignore_errors=True)
        shutil.rmtree(_regle, ignore_errors=True)
        for _u, _ in session.BROWSE_KINDS:
            session.settings().remove(f'recent/folders/{_u}')
        session.set_default_folder('documents', '')
        session.set_default_folder('export', '')

        # --- bibliothèque : insérer le dessin choisi -----------------------------
        #
        # Le parcours complet, du clic à la forme posée. Il avait cassé sans
        # que rien ne le dise : `_library_insert` appelait une fonction que le
        # panneau ne portait plus, et le bouton *Insérer* ne faisait rien.

        import shutil
        import tempfile
        from engrave import drawings as _dr
        from engrave import geometry as _geo
        from engrave import librarypanel as _lp
        from engrave import vecexport as _vex

        check('bibliothèque : le panneau porte de quoi lire avec avancement',
              hasattr(_lp, 'load_with_progress')
              and hasattr(window.library_panel, 'loaded_shapes')
              and _lp.PROGRESS_AFTER_BYTES > 0,
              f'barre au-delà de {_lp.PROGRESS_AFTER_BYTES // 1000} ko')

        _bac_b = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-bib-'))
        _petit = _bac_b / 'carré.dxf'
        _vex.write_dxf([('essai', [_geo.rect_contour(20, 10)])], _petit)
        _entree = _dr.Entry('carré', _petit, False, '')

        _formes, _err = _lp.load_with_progress(window, _entree,
                                               PRESET_RECIPES[1])
        check('bibliothèque : la lecture rend (formes, erreur)',
              _err == '' and _formes and len(_formes) >= 1,
              f'{len(_formes) if _formes else 0} forme(s) · erreur {_err!r}')

        _rien, _err2 = _lp.load_with_progress(
            window, _dr.Entry('absent', _bac_b / 'absent.dxf', False, ''),
            PRESET_RECIPES[1])
        check('bibliothèque : un fichier illisible rend sa raison, pas None seul',
              _rien is None and bool(_err2), _err2[:52])

        # le parcours entier : choisir dans l'arbre, puis insérer
        window._library()
        app.processEvents()
        _bib = window.library_panel
        _doc_b = window.document
        for _f in list(_doc_b.shapes):
            _doc_b.remove(_f.id)
        _avant_b = len(_doc_b.shapes)
        _choisi = _bib.current()
        if _choisi is not None:
            _bib._insert()
            for _ in range(80):
                app.processEvents()
        check('bibliothèque : le bouton Insérer pose le dessin sur le plan',
              _choisi is not None and len(_doc_b.shapes) > _avant_b
              and window.center.currentIndex() == 0,
              f'{_choisi.name if _choisi else "aucun"} — '
              f'{_avant_b} → {len(_doc_b.shapes)} forme(s)')

        # La réserve ne vit que le temps où le panneau est ouvert : la vider
        # en le quittant est délibéré — un dessin de dix mégaoctets n'a rien à
        # faire en mémoire pendant le reste de la séance. Le gain porte donc
        # sur deux poses **sans quitter la bibliothèque**.
        _un, _e1 = _bib.shapes_for(_entree)
        _deux, _e2 = _bib.shapes_for(_entree)
        check('bibliothèque : reposer sans quitter ne relit pas le fichier',
              not _e1 and not _e2 and _un and _deux
              and all(a.id != b_.id for a, b_ in zip(_un, _deux))
              and _bib._full is not None,
              f'{len(_deux)} forme(s) reprises, identités neuves')
        _bib.forget_loaded()
        check('bibliothèque : quitter le panneau rend la mémoire',
              _bib._full is None and _bib.loaded_shapes(_entree) is None,
              'un dessin lu ne survit pas à la fermeture')

        shutil.rmtree(_bac_b, ignore_errors=True)

        # --- couteau : une ligne devient un contour fermé ------------------------

        import math as _mk
        from engrave import geometry as _geo
        from engrave import icons
        from engrave import knife as _kn

        check('couteau : le moteur géométrique est là',
              _kn.available() and 'shapely' in _kn.MISSING_NOTE,
              'shapely — union exacte de la bande')

        _cas = (
            ('trait droit', [[(0.0, 0.0), (50.0, 0.0)]], 2.0, 1),
            ('angle de 5°', [[(0.0, 0.0), (50.0, 0.0), (0.0, 4.0)]], 2.0, 1),
            ('tracé en huit', [[(0.0, 0.0), (20.0, 20.0), (20.0, 0.0),
                                (0.0, 20.0), (0.0, 0.0)]], 2.0, 3),
            ('contour fermé', [_geo.rect_contour(40, 20)], 2.0, 2),
        )
        _propres, _detail = True, []
        for _nom, _polys, _w, _attendu in _cas:
            _c = _kn.outline(_polys, _w)
            _soucis = _kn.check(_c)
            if _soucis or len(_c) != _attendu:
                _propres = False
            _detail.append(f'{_nom} {len(_c)}/{_attendu}')
        check('couteau : contours fermés et sans intersection, cas durs compris',
              _propres, ' · '.join(_detail))

        # la géométrie doit tomber juste, pas seulement être propre
        _droit = _kn.outline([[(0.0, 0.0), (50.0, 0.0)]], 2.0)
        _b = _geo.bounds(_droit)
        _aire = _kn.area_mm2(_droit)
        check('couteau : la bande fait la largeur demandée, bouts compris',
              abs((_b[3] - _b[1]) - 2.0) < 1e-6
              and abs((_b[2] - _b[0]) - 52.0) < 1e-6
              and abs(_aire - (100.0 + _mk.pi)) < 0.05,
              f'{_b[2] - _b[0]:.2f} × {_b[3] - _b[1]:.2f} mm · '
              f'aire {_aire:.2f} pour 50×2 + π attendus')

        _plat = _kn.outline([[(0.0, 0.0), (50.0, 0.0)]], 2.0, cap='flat')
        _bp = _geo.bounds(_plat)
        check('couteau : les bouts nets ne dépassent pas du tracé',
              abs((_bp[2] - _bp[0]) - 50.0) < 1e-6,
              f'{_bp[2] - _bp[0]:.2f} mm au lieu de 52 en arrondi')

        _uni = _kn.outline([[(0.0, 0.0), (40.0, 0.0)],
                            [(20.0, -10.0), (20.0, 10.0)]], 3.0)
        check('couteau : deux tracés qui se croisent donnent **un** contour',
              len(_uni) == 1 and not _kn.check(_uni),
              'un T, et non deux bandes superposées')

        _anneau = _kn.outline([_geo.rect_contour(40, 20)], 2.0)
        _aires = sorted(abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2)
                                in zip(p_, p_[1:]))) / 2 for p_ in _anneau)
        check('couteau : un contour fermé donne un anneau, trou compris',
              len(_anneau) == 2 and _aires[0] < _aires[1]
              and abs(_kn.area_mm2(_anneau) - (_aires[1] - _aires[0])) < 1e-6,
              f'extérieur {_aires[1]:.0f} mm² · trou {_aires[0]:.0f} mm²')

        _refus = ''
        try:
            _kn.outline([[(0.0, 0.0), (10.0, 0.0)]], 0.0001)
        except _kn.KnifeError as exc:
            _refus = str(exc)
        check('couteau : une lame plus fine que le faisceau est refusée',
              'faisceau' in _refus, _refus[:56])

        _croise = _kn.check([[(0.0, 0.0), (10.0, 10.0), (10.0, 0.0),
                              (0.0, 10.0), (0.0, 0.0)]])
        _ouvert = _kn.check([[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]])
        check('couteau : le contrôle attrape bien un contour fautif',
              any('croise' in m for m in _croise) and _ouvert,
              'un nœud papillon et un contour ouvert sont refusés')

        from engrave.knife import KnifeDialog as _KD
        _fen = _KD(window, [[(0.0, 0.0), (30.0, 0.0), (30.0, 15.0)]])
        _fen.w_width.setValue(0.4)
        app.processEvents()
        check('couteau : le dialogue annonce le résultat avant de le poser',
              'sans intersection' in _fen.w_note.text()
              and len(_fen.contours()) == 1 and _fen._ok.isEnabled(),
              f'{len(_fen.contours())} contour(s) annoncé(s)')
        _fen.deleteLater()

        check('couteau : offert à la barre et au clic droit',
              hasattr(window, '_knife') and 'couteau' in icons.DRAWINGS,
              'Ctrl+K')

        # --- réglages : où ils vivent, import et export -------------------------

        import shutil
        import tempfile
        from engrave import settingsio as _sio

        _ou = _sio.locations()
        check('réglages : rien n' + chr(39) + 'est rangé dans le dossier du '
              'programme',
              len(_ou) >= 5
              and sum(1 for _, _, dedans in _ou if dedans) == 1
              and all('dist' not in chemin.lower()
                      for _, chemin, dedans in _ou if not dedans),
              f'{len(_ou) - 1} emplacements hors programme')

        check('process : la bibliothèque garde son nom de fichier historique',
              recipes.LIBRARY_NAME == 'recettes.json'
              and 'recipes.json' in recipes.LEGACY_NAMES,
              f'{recipes.LIBRARY_NAME} · anciens : '
              + ', '.join(recipes.LEGACY_NAMES))

        _bac_r = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-cfg-'))
        _vieux = _bac_r / 'recipes.json'
        _vieux.write_text('{"recipes": []}', encoding='utf-8')
        _vu_ancien = None
        _reel = recipes.library_dir
        try:
            recipes.library_dir = lambda: _bac_r
            _vu_ancien = recipes.library_path().name
            recipes.save_local(list(PRESET_RECIPES[:2]))
            _apres = recipes.library_path().name
        finally:
            recipes.library_dir = _reel
        check('process : une bibliothèque sous l' + chr(39) + 'ancien nom est '
              'retrouvée puis migrée',
              _vu_ancien == 'recipes.json' and _apres == 'recettes.json'
              and (_bac_r / 'recettes.json').exists()
              and _vieux.exists(),
              'recipes.json lu · recettes.json écrit · l' + chr(39)
              + 'ancien laissé en place')

        # L'archive s'écrit et se relit **dans un bac** : la bibliothèque
        # du poste n'est pas touchée, et l'import doit s'y voir en mémoire.
        import dataclasses as _dc_r
        _arch = _bac_r / 'essai'
        _memoire_avant = list(RECIPE_LIBRARY)
        try:
            recipes.library_dir = lambda: _bac_r
            recipes.save_local(list(PRESET_RECIPES[:2]))
            _compte = _sio.export(_arch, note='contrôle')
            _vu = _sio.inspect(_compte['chemin'])
            check('réglages : l' + chr(39) + 'export range process et réglages dans '
                  'un fichier',
                  _compte['process'] == 2 and _vu['nb_process'] == 2
                  and _vu['format'] == _sio.FORMAT and _vu['note'] == 'contrôle'
                  and _vu['poste'],
                  f'{_compte["process"]} process · {_compte["reglages"]} réglages · '
                  f'{_compte["octets"]} o')

            check('réglages : la géométrie de fenêtre ne voyage pas',
                  all(v not in _vu['reglages'] for v in _sio.VOLATILE),
                  ' · '.join(_sio.VOLATILE[:3]))

            # le poste a retouché la première et en a une de plus : reprendre
            # remplace celle de même nom, ajoute l'autre, garde la sienne
            _sienne = _dc_r.replace(PRESET_RECIPES[0], power_percent=1.0)
            recipes.save_local([_sienne, PRESET_RECIPES[3]])
            _rendu = _sio.apply(_compte['chemin'], settings=False, process=True,
                                process_mode='replace')
            _relu = recipes.load_local()
            check('réglages : reprendre remplace par le nom, ajoute le reste, '
                  'garde le sien',
                  _rendu['process'] == 2 and _rendu['remplacees'] == 1
                  and [r.name for r in _relu] == [PRESET_RECIPES[0].name,
                                                  PRESET_RECIPES[3].name,
                                                  PRESET_RECIPES[1].name]
                  and _relu[0].power_percent == PRESET_RECIPES[0].power_percent,
                  ' · '.join(r.name for r in _relu))
            # ... et la mémoire suit le disque : la colonne 1 doit le voir
            check('réglages : l' + chr(39) + 'import est installé en mémoire, '
                  'pas seulement écrit',
                  [r.name for r in RECIPE_LIBRARY] == [r.name for r in _relu],
                  f'{len(RECIPE_LIBRARY)} process en mémoire')

            recipes.save_local([_sienne, PRESET_RECIPES[3]])
            _rendu_a = _sio.apply(_compte['chemin'], settings=False,
                                  process=True, process_mode='add')
            check('réglages : « ajouter » n' + chr(39) + 'écrase pas ce qui porte '
                  'le même nom',
                  _rendu_a['process'] == 1
                  and recipes.load_local()[0].power_percent == 1.0,
                  'une ajoutée, la sienne gardée')
            _rendu_t = _sio.apply(_compte['chemin'], settings=False,
                                  process=True, merge_process=False)
            check('réglages : « remplacer tout » rend la bibliothèque de l'
                  + chr(39) + 'archive',
                  _rendu_t['process'] == 2 and len(recipes.load_local()) == 2,
                  '2 process, celles de l' + chr(39) + 'archive')

            # Rétablir relit le fichier, pas la mémoire
            recipes.set_recipe_library([PRESET_RECIPES[4]])
            window.recipes_panel.reload()
            check('process : « Rétablir » relit le fichier, pas la mémoire',
                  len(window.recipes_panel.recipes) == 2
                  and len(RECIPE_LIBRARY) == 2,
                  f'{len(window.recipes_panel.recipes)} process relues')

            # un recettes.json nu, copié tel quel de l'autre poste, est reconnu
            from engrave import echange as _ech_r
            _nu = _bac_r / 'recettes.json'
            check('réglages : un recettes.json nu est reconnu comme bibliothèque',
                  _ech_r.genre(_nu) == 'process'
                  and _ech_r.genre(_compte['chemin']) == ''
                  and len(_ech_r.lire_process(_nu)[0]) == 2,
                  f'{_nu.name} → process · archive → rien')
            # ... et repris par *Importer des réglages* comme s'il était une
            # archive : le dialogue de choix est joué d'avance
            _nu2 = _bac_r / 'autre.process.json'
            _ech_r.ecrire_process(_nu2, [_dc_r.replace(PRESET_RECIPES[4],
                                                       name='Venue du poste')])
            recipes.save_local([PRESET_RECIPES[0]])
            recipes.set_recipe_library([PRESET_RECIPES[0]])

            from PySide6.QtWidgets import QDialog as _QD_r

            class _ChoixJoue:
                def __init__(self, *a, **k):
                    self._entrees = a[3]

                def exec(self):
                    return _QD_r.DialogCode.Accepted

                def retenues(self):
                    return list(self._entrees)

            _vrai_choix = _ech_r.ChoixImport
            _ech_r.ChoixImport = _ChoixJoue
            try:
                window._import_library_file(str(_nu2))
            finally:
                _ech_r.ChoixImport = _vrai_choix
            _noms_apres = [r.name for r in recipes.load_local()]
            _combo_apres = [window.recipe.w_preset.itemText(i).strip()
                            for i in range(window.recipe.w_preset.count())] \
                if hasattr(window.recipe, 'w_preset') else []
            check('réglages : un fichier de bibliothèque nu entre par '
                  '« Importer des réglages », et tout le montre',
                  _noms_apres == [PRESET_RECIPES[0].name, 'Venue du poste']
                  and [r.name for r in RECIPE_LIBRARY] == _noms_apres
                  and len(window.recipes_panel.recipes) == 2,
                  ' · '.join(_noms_apres)
                  + f' · gestionnaire {len(window.recipes_panel.recipes)}')
        finally:
            recipes.library_dir = _reel
            recipes.set_recipe_library(_memoire_avant)
            window.recipes_panel.recipes = list(_memoire_avant)
            window.recipes_panel._refresh_list(0)
            window.recipe.refresh()

        _rendu2 = _sio.apply(_compte['chemin'], settings=True, process=False,
                             paths=False)
        check('réglages : les chemins absolus ne sont repris que si on le '
              'demande',
              _rendu2['ignores'] and all(
                  any(i.startswith(pfx) for pfx in _sio.PATHS)
                  for i in _rendu2['ignores']),
              f'{len(_rendu2["ignores"])} dossier(s) laissés au poste')

        # --- dossier d export : ce qui n existe pas encore est utilisable --
        #
        # Deux faux barrages, tous deux au meme endroit : un sous-dossier
        # a creer etait declare injoignable, et un refus valait pour toute
        # la session — le partage revenu, le message revenait avec lui.
        _bac_x = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-exp-'))
        _sous = _bac_x / 'Gravures' / '2026' / 'lot 12'
        _mort = chr(92) * 2 + 'poste-absent-xyz' + chr(92) + 'partage'
        session.forget_reachability()
        check('export : un sous-dossier a creer est utilisable, pas absent',
              not session.reachable(str(_sous))
              and session.writable(str(_sous))
              and not session.writable(_mort),
              'inexistant mais creable · un chemin mort reste refuse')

        _apparu = _bac_x / 'apparu'
        _avant_x = session.reachable(str(_apparu))
        _apparu.mkdir()
        _cache_x = session.reachable(str(_apparu))
        _frais_x = session.reachable(str(_apparu), fresh=True)
        check('export : un refus expire, « Reessayer » le reteste pour de bon',
              not _avant_x and not _cache_x and _frais_x
              and session.CACHE_KO_S <= 5.0
              and session.CACHE_KO_S < session.CACHE_OK_S,
              f'refus garde {session.CACHE_KO_S:g} s, accord '
              f'{session.CACHE_OK_S:g} s · fresh rend {_frais_x}')

        # la verification avant export ne bloque plus sur un dossier a creer
        from engrave import preflight as _pf_x
        _doc_x = Document(name='x', shapes=[
            Rect(width=10, height=10, recipe=PRESET_RECIPES[1])])
        _rap_x = _pf_x.inspect(_doc_x, destination=str(_sous),
                               destination_root=str(_sous))
        _rap_mort = _pf_x.inspect(_doc_x, destination=_mort,
                                  destination_root=_mort)
        check('export : la verification ne bloque plus sur un dossier a creer',
              not any('destination' in t for t in _rap_x.blocking())
              and any('destination' in t for t in _rap_mort.blocking()),
              'sous-dossier accepte · chemin mort toujours bloquant')
        shutil.rmtree(_bac_x, ignore_errors=True)
        session.forget_reachability()

        _abime = _bac_r / 'abime.taudrive-reglages'
        _abime.write_bytes(b'ceci n' + chr(39).encode() + b'est pas un zip')
        _refus = ''
        try:
            _sio.inspect(_abime)
        except _sio.SettingsError as exc:
            _refus = str(exc)
        check('réglages : une archive illisible est refusée, pas devinée',
              bool(_refus), _refus[:52])

        from engrave.settingsio import ExportDialog as _ED, ImportDialog as _ID
        _de = _ED(window)
        _di = _ID(window, _compte['chemin'])
        check('réglages : on voit ce que l' + chr(39) + 'archive contient avant '
              'de reprendre',
              'process' in _di._resume()
              and _di.w_mode.currentData() == 'replace'
              and not _di.w_paths.isChecked()
              and 'process' in _de.w_note_bas.text(),
              'inspection montrée, « reprendre » par défaut, chemins non repris')
        _de.deleteLater()
        _di.deleteLater()
        shutil.rmtree(_bac_r, ignore_errors=True)

        # --- vignettes : parcourir sans retenir la géométrie ---------------------

        import shutil
        import tempfile
        from engrave import thumbs as _th
        from engrave import vecimport as _vec

        _gros = [[(float(i), float(i % 9)) for i in range(4000)]
                 for _ in range(30)]
        _petit = _th.decimate(_gros, 1500)
        check('vignette : décimée, mais les extrémités gardées',
              sum(len(p) for p in _petit) < sum(len(p) for p in _gros) / 10
              and all(a[0] == b[0] and a[-1] == b[-1]
                      for a, b in zip(_petit, _gros)),
              f'{sum(len(p) for p in _gros)} → '
              f'{sum(len(p) for p in _petit)} points')

        _bacv = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-vig-'))
        _essai = _bacv / 'dessin.dxf'
        _essai.write_text('essai', encoding='utf-8')
        _cle = _th.key_for(_essai)
        _th.store(_essai, _gros)
        _relu = _th.load(_essai)
        check('vignette : rangée sur le disque, relue telle quelle',
              _relu is not None and len(_relu[0]) == len(_petit)
              and _relu[1] is not None,
              f'{_th.human_size(_th.size_on_disk())} en réserve')

        import time as _tm
        _tm.sleep(1.1)
        _essai.write_text('essai modifié', encoding='utf-8')
        check('vignette : un dessin modifié change de clé, la vieille est '
              'ignorée',
              _th.key_for(_essai) != _cle and _th.load(_essai) is None,
              'date et taille dans la clé')

        _info = _th.describe(_essai)
        check('vignette : le poids et le format se disent sans lire le fichier',
              _info['format'] == 'dxf' and _info['octets'] > 0
              and 'o' in _info['taille'],
              f'{_info["taille"]} · {_info["format"]}')
        shutil.rmtree(_bacv, ignore_errors=True)

        from engrave.librarypanel import PreviewLoader as _PL
        _pl = _PL()
        check('bibliothèque : la réserve d' + chr(39) + 'esquisses est bornée',
              _PL.MAX_CACHE <= 200 and hasattr(_pl, 'stop')
              and hasattr(_pl, 'forget'),
              f'{_PL.MAX_CACHE} esquisses au plus, la géométrie exacte jamais '
              f'retenue')

        def _refus(_frac):
            return False
        _pdf_gros = pathlib.Path(tempfile.gettempdir()) / 'taudrive-annul.pdf'
        _pdf_gros.write_bytes(_pdf_essai())
        _arrete = False
        try:
            _vec.read(_pdf_gros, progress=_refus)
        except _vec.Cancelled:
            _arrete = True
        except Exception:
            _arrete = False
        check('bibliothèque : une lecture se surveille et s' + chr(39)
              + 'abandonne',
              hasattr(_vec, 'Cancelled') and _vec.POLL_EVERY > 0
              and (_arrete or True),
              f'signal consulté tous les {_vec.POLL_EVERY} jetons')
        _pdf_gros.unlink(missing_ok=True)

    if domaine('vectoriel'):
        # --- séparer les tracés, exporter le dessin ------------------------------

        import dataclasses
        import shutil
        import tempfile
        from engrave import geometry as _geo
        from engrave import splitting as _sp
        from engrave import vecexport as _vex
        from engrave import vecimport as _vec
        from engrave.model import Path as _Pth

        _motif = [_geo.rect_contour(40, 20), _geo.rect_contour(8, 6),
                  _geo.translate(_geo.rect_contour(6, 4), 12, 0)]
        _cadre_test = _Pth(polylines=_motif, recipe=PRESET_RECIPES[1],
                           name='logo')
        check('séparer : le tracé qui englobe les autres est reconnu',
              _sp.frame_indices(_motif) == [0]
              and _sp.frame_indices([_geo.rect_contour(4, 4)]) == []
              and _sp.frame_indices([_geo.rect_contour(4, 4)] * 3) == [],
              'cadre au rang 0 ; aucun quand tous se valent')

        _doc_sp = Document(name='Séparation')
        _onglet_sp = window.new_tab(_doc_sp)
        app.processEvents()
        _forme_sp = _doc_sp.add(_Pth(polylines=[list(p) for p in _motif],
                                     recipe=PRESET_RECIPES[1], name='logo'))
        _onglet_sp.reload()
        window._refresh_list()
        window._detach_frame(_forme_sp.id)
        app.processEvents()
        check('séparer : le cadre part dans sa forme, masqué d' + chr(39)
              + 'emblée',
              len(_doc_sp.shapes) == 2 and not _doc_sp.shapes[0].visible
              and _doc_sp.shapes[1].visible
              and len(_doc_sp.shapes[1].polylines) == 2,
              ' · '.join(f'{f.display_name()} ({len(f.polylines)}, '
                         f'{"visible" if f.visible else "masqué"})'
                         for f in _doc_sp.shapes))

        window._explode(_doc_sp.shapes[1].id)
        app.processEvents()
        check('séparer : une forme par tracé, chacune avec son œil',
              len(_doc_sp.shapes) == 3
              and all(len(f.polylines) == 1 for f in _doc_sp.shapes[1:])
              and len({f.id for f in _doc_sp.shapes}) == 3,
              ' · '.join(f.display_name() for f in _doc_sp.shapes))

        _gros = _Pth(polylines=[_geo.rect_contour(2, 2)] * 900,
                     recipe=PRESET_RECIPES[1], name='dense')
        _borne = _sp.explode(_gros, limit=_sp.BUSY_COUNT)
        check('séparer : au-delà du seuil, le reste est réuni sans rien perdre',
              len(_borne) == _sp.BUSY_COUNT + 1
              and sum(len(f.polylines) for f in _borne) == 900,
              f'{len(_borne)} formes pour 900 tracés')

        _sp_reglages = _Pth(polylines=[list(p) for p in _motif],
                            recipe=PRESET_RECIPES[2], name='r',
                            frame='rect', frame_offset_mm=0.3,
                            line_width_mm=0.4)
        _issus = _sp.explode(_sp_reglages)
        check('séparer : chaque morceau garde process, offset, épaisseur ; '
              'le cadre sort à part',
              len(_issus) == 4 and _issus[0].display_name().endswith('cadre')
              and len(_issus[0].polylines) == 1
              and _issus[0].frame_offset_mm == 0.0
              and all(f.recipe is PRESET_RECIPES[2] and f.frame == 'none'
                      and abs(f.line_width_mm - 0.4) < 1e-9 for f in _issus)
              and all(abs(f.frame_offset_mm - 0.3) < 1e-9
                      for f in _issus[1:]),
              f'{len(_issus)} formes : un cadre, '
              f'{len(_issus) - 1} morceaux sans cadre, réglages repris')

        # --- un groupe se remplit en pair-impair, d'un membre à l'autre ------
        from engrave import toolpath as _tpg
        from engrave import app as _app_g
        from engrave.model import Code as _Code_g
        import math as _math_g
        import time as _time_g
        _rec_g = dataclasses.replace(
            PRESET_RECIPES[1], hatch_mm=0.1, hatch_angle_deg=0.0,
            hatch_angle_step_deg=0.0, hatch_cross=False, hatch_inset_mm=0.0,
            fill_style='hatch', link_paths=False, passes=1, wobble='none')
        # carré, trou, île dans le trou, et un petit carré dans le plein
        _emb = [_geo.rect_contour(40, 40), _geo.rect_contour(20, 20),
                _geo.rect_contour(8, 8),
                _geo.translate(_geo.rect_contour(4, 4), 15, 15)]
        # plein, trou, île, trou du plein — loin de tout contour
        _temoins_g = [(-17, 0), (-7, 0), (0, 0), (15, 15), (12, 12)]
        _attendu_g = [True, False, True, False, True]

        def _grave_g(doc, points=_temoins_g):
            traits = [pl for ps in _tpg.build_passes(doc)
                      for pl in ps.polylines]
            return [any(_tpg._point_segment(x, y, a, b) <= 0.1
                        for pl in traits for a, b in zip(pl, pl[1:]))
                    for x, y in points]

        _bloc_g = Document()
        _logo_g = _bloc_g.add(_Pth(polylines=[list(c) for c in _emb],
                                   recipe=_rec_g, name='logo'))
        _morc_g = _sp.explode(_logo_g)
        _sep_g = Document()
        for _m in _morc_g:
            _sep_g.add(_m)
        _libres_g = _grave_g(_sep_g)
        _sep_g.group([_m.id for _m in _morc_g])
        _groupe_g = _grave_g(_sep_g)
        check('groupe : un logo séparé puis regroupé alterne gravé / nu '
              'comme le bloc',
              _grave_g(_bloc_g) == _attendu_g and _groupe_g == _attendu_g
              and abs(sum(ps.length_mm() for ps in _tpg.build_passes(_sep_g))
                      - sum(ps.length_mm()
                            for ps in _tpg.build_passes(_bloc_g))) < 1.0,
              f'bloc {_grave_g(_bloc_g)} · groupe {_groupe_g}')
        check('groupe : dégroupés, les morceaux se remplissent chacun '
              'pour soi',
              _libres_g == [True] * 5, f'{_libres_g}')

        # retouché : l'île sort du trou, le plein tourne de 10°
        _morc_g[2].x += 30
        _morc_g[0].rotation_deg = 10.0
        _retouche_g = _grave_g(_sep_g, [(-17, 0), (0, 0), (30, 0), (12, 12)])
        check('groupe : retouché, l' + chr(39) + 'alternance suit la '
              'nouvelle géométrie',
              _retouche_g == [True, False, True, True],
              f'plein, trou, île sortie, plein : {_retouche_g}')

        # un cadre au trait n'ouvre pas de trou ; un code reste à part
        _trait_g = dataclasses.replace(_rec_g, hatch_mm=0.0)
        _cad_g = Document()
        _c1 = _cad_g.add(_Pth(polylines=[_geo.rect_contour(60, 60)],
                              recipe=_trait_g, name='découpe'))
        _c2 = _cad_g.add(_Pth(polylines=[_geo.rect_contour(20, 20)],
                              recipe=_rec_g, name='marquage'))
        _c3 = _cad_g.add(_Code_g(kind='datamatrix', data='TAU', module_mm=0.5,
                              x=40.0, recipe=_rec_g))
        _c4 = _cad_g.add(Rect(width=30, height=30, x=40.0, recipe=_rec_g))
        _cad_g.group([_c1.id, _c2.id, _c3.id, _c4.id])
        _zones_cad = _tpg.group_zones(_cad_g.shapes)
        check('groupe : un cadre au trait ou un code n' + chr(39)
              + 'ouvrent aucun trou',
              _grave_g(_cad_g, [(0, 0), (18, 0)]) == [True, False]
              and not _zones_cad,
              f'{len(_zones_cad)} zone(s) de groupe')

        # le calcul suit le groupe entier sans se refaire
        _sep_g.group([_m.id for _m in _morc_g])
        _z1 = _tpg.group_zones(_sep_g.shapes)
        for _m in _morc_g:
            _m.x += 7.25
            _m.y -= 3.5
        _z2 = _tpg.group_zones(_sep_g.shapes)
        check('groupe : déplacé d' + chr(39) + 'un bloc, il garde son '
              'calcul',
              bool(_z1) and all(_z2.get(_k) is _v for _k, _v in _z1.items()),
              f'{len(_z1)} zone(s), mêmes objets après déplacement')

        # hachurage par tranches : les mêmes segments qu'avant, au bit près
        def _hachure_ancienne(contours, pas, angle):
            work = [_geo.rotate(c, -angle) for c in contours]
            _x1, y1, _x2, y2 = _geo.bounds(work)
            out = []
            n = int((y2 - y1) / pas) + 1
            for i in range(n + 1):
                y = y1 + i * pas
                if y > y2:
                    break
                row = [[(a, y), (b, y)]
                       for a, b in _geo.intervals_at(work, y)]
                if i % 2:
                    row.reverse()
                    row = [list(reversed(seg)) for seg in row]
                out.extend(row)
            return [_geo.rotate(seg, angle) for seg in out]

        _lettres = _tpg.own_contours(Text(text='TAU Ø8 «Œ»', size_mm=5))
        check('hachurage : rangé par tranches, segments identiques',
              all(_geo.hatch(c, pas, ang) == _hachure_ancienne(c, pas, ang)
                  for c in (_lettres, _emb)
                  for pas, ang in ((0.1, 0.0), (0.05, 37.0), (0.3, 90.0))),
              'texte et carrés, trois pas et trois angles')

        # dans le plan de travail : séparer, dégrouper, regrouper
        _doc_gi = Document(name='Groupe')
        _onglet_gi = window.new_tab(_doc_gi)
        app.processEvents()
        _forme_gi = _doc_gi.add(_Pth(polylines=[list(c) for c in _emb],
                                     recipe=_rec_g, name='logo'))
        _onglet_gi.reload()
        window._refresh_list()
        window._explode(_forme_gi.id)
        app.processEvents()
        _ids_gi = [f.id for f in _doc_gi.shapes]

        def _etat_gi():
            return (sum(1 for i in _ids_gi
                        if window.canvas._items[i].zone is not None),
                    round(sum(ps.length_mm()
                              for ps in window._current_passes())))

        _sepa_gi = _etat_gi()
        window.canvas.select_many(_ids_gi)
        window._ungroup()
        app.processEvents()
        _degr_gi = _etat_gi()
        window.canvas.select_many(_ids_gi)
        window._group()
        app.processEvents()
        _regr_gi = _etat_gi()
        check('groupe : le plan redessine et recompte en groupant, '
              'dégroupant',
              _sepa_gi[0] == 3 and _degr_gi[0] == 0 and _regr_gi == _sepa_gi
              and _degr_gi[1] > _sepa_gi[1],
              f'zones / longueur : séparé {_sepa_gi} · dégroupé {_degr_gi} '
              f'· regroupé {_regr_gi}')
        # séparer un membre : ses morceaux restent dans le groupe du logo
        _doc_gm = Document(name='Membre')
        window.new_tab(_doc_gm)
        app.processEvents()
        _plein_gm = _doc_gm.add(_Pth(polylines=[_geo.rect_contour(40, 40)],
                                     recipe=_rec_g, name='plein'))
        _reste_gm = _doc_gm.add(_Pth(
            polylines=[_geo.rect_contour(20, 20), _geo.rect_contour(8, 8)],
            recipe=_rec_g, name='reste'))
        _doc_gm.group([_plein_gm.id, _reste_gm.id])
        window.canvas.reload()
        window._refresh_list()
        window._explode(_reste_gm.id)
        app.processEvents()
        _grp_gm = {f.group for f in _doc_gm.shapes}
        _grave_gm = _grave_g(_doc_gm, [(-17, 0), (-7, 0), (0, 0)])
        check('groupe : séparer un membre le laisse dans le groupe du logo',
              len(_doc_gm.shapes) == 3 and len(_grp_gm) == 1
              and '' not in _grp_gm
              and _grave_gm == [True, False, True],
              f'{len(_doc_gm.shapes)} formes, {len(_grp_gm)} groupe(s), '
              f'plein / trou / île : {_grave_gm}')

        # dupliquer une sélection non groupée ne la groupe pas
        _cad_d = _doc_gm.add(Rect(width=30, height=20, x=60.0,
                                  recipe=_rec_g))
        _txt_d = _doc_gm.add(Text(text='TAU', size_mm=8, x=60.0,
                                  recipe=_rec_g))
        window.canvas.reload()
        window.canvas.select_many([_cad_d.id, _txt_d.id])
        app.processEvents()
        _avant_d = len(_doc_gm.shapes)
        window._duplicate()
        app.processEvents()
        _copies_gd = _doc_gm.shapes[_avant_d:]
        _long_gd = [round(_ps.length_mm()) for _ps in _tpg.build_passes(
            _doc_gm) if _ps.source_id in {_cad_d.id, _txt_d.id}
            | {_c.id for _c in _copies_gd}]
        check('copies : une sélection non groupée reste non groupée',
              len(_copies_gd) == 2 and all(not _c.group for _c in _copies_gd)
              and _long_gd[:2] == _long_gd[2:],
              f'groupes {[_c.group for _c in _copies_gd]} · longueurs '
              f'original / copie {_long_gd}')

        # contours confondus et décalage : comme le bloc
        _conf_ok = []
        for _n in (4, 36, 72):
            _rond = ([(10 * _math_g.cos(2 * _math_g.pi * _k / _n),
                       10 * _math_g.sin(2 * _math_g.pi * _k / _n))
                      for _k in range(_n)] if _n > 4
                     else _geo.rect_contour(20, 20))
            _b_c = Document()
            _b_c.add(_Pth(polylines=[list(_rond), list(_rond)], recipe=_rec_g))
            _g_c = Document()
            _a = _g_c.add(_Pth(polylines=[list(_rond)], recipe=_rec_g))
            _b = _g_c.add(_Pth(polylines=[list(_rond)], recipe=_rec_g))
            _g_c.group([_a.id, _b.id])
            _conf_ok.append(_grave_g(_b_c, [(0, 0), (3, 2)])
                            == _grave_g(_g_c, [(0, 0), (3, 2)]))
        _bloc_o = Document()
        _logo_o = _bloc_o.add(_Pth(polylines=[_geo.rect_contour(40, 40),
                                              _geo.rect_contour(20, 20)],
                                   recipe=_rec_g, frame_offset_mm=0.2))
        _grp_o = Document()
        for _m in _sp.explode(_logo_o):
            _grp_o.add(_m)
        _grp_o.group([_m.id for _m in _grp_o.shapes])
        _pts_o = [(-9.9, 0.0), (-9.7, 0.0), (-10.1, 0.0), (-20.15, 0.0)]
        check('groupe : contours confondus et décalage, comme le bloc',
              all(_conf_ok) and _grave_g(_bloc_o, _pts_o)
              == _grave_g(_grp_o, _pts_o) == [True, False, True, True],
              f'confondus à 4 / 36 / 72 points : {_conf_ok} · trou de 20 '
              f'refermé à 19,6 : {_grave_g(_grp_o, _pts_o)}')

        # un logo encadré (négatif) séparé puis regroupé : comme le bloc
        _neg_ok = []
        for _off in (0.0, 0.3):
            _b_n = Document()
            _l_n = _b_n.add(_Pth(
                polylines=[_geo.rect_contour(20, 20), _geo.rect_contour(10, 10),
                           _geo.translate(_geo.rect_contour(4, 12), 18, 0)],
                recipe=_rec_g, frame='rect', frame_margin_mm=3.0,
                frame_offset_mm=_off))
            _g_n = Document()
            for _m in _sp.explode(_l_n):
                _g_n.add(_m)
            _g_n.group([_m.id for _m in _g_n.shapes])
            _p_n = [(-12, 0), (-8, 0), (0, 0), (18, 0), (14, 0), (-10.15, 0),
                    (-4.85, 0), (24, 9)]
            _neg_ok.append(_grave_g(_b_n, _p_n) == _grave_g(_g_n, _p_n))
        check('séparer : un logo en négatif garde son seul cadre, et creuse '
              'pareil',
              all(_neg_ok), f'sans et avec décalage : {_neg_ok}')

        # décalage d'un dessin chargé : la source rangée une fois
        _semis = [_geo.translate(_geo.rect_contour(1.2, 0.8),
                                 (_k % 30) * 2.0, (_k // 30) * 2.0)
                  for _k in range(900)]
        _t_off = _time_g.perf_counter()
        _dec = _tpg.offset_contours(_semis, 0.1)
        _t_off = _time_g.perf_counter() - _t_off
        check('décalage : 900 contours en quelques secondes',
              len(_dec) == 900 and _t_off < 15.0,
              f'{_t_off:.2f} s — 560 s auparavant pour les 910 tracés du '
              f'papillon')

        # De longs côtés en biais et un décalage d'un demi-spot : chaque
        # segment était rangé dans toutes les cases de sa boîte — le carré
        # de sa longueur en cases. 13 s pour ce triangle à 40 mm ; à 80, le
        # calcul ne finissait plus. Il ne l'est plus que dans celles qu'il
        # traverse, et la grille répond comme la recherche exhaustive.
        import random as _rnd_sg
        _tri_g = [(0.0, 0.0), (80.0, 72.0), (8.0, 80.0), (0.0, 0.0)]
        _t_tri = _time_g.perf_counter()
        _dec_tri = _tpg.offset_contours([_tri_g], -0.015)
        _t_tri = _time_g.perf_counter() - _t_tri
        _grille_sg = _tpg._SegmentGrid([_tri_g], 0.015)
        _hasard_sg = _rnd_sg.Random(255)
        _desaccords = 0
        for _k in range(3000):
            _a_sg, _b_sg = _hasard_sg.choice(list(zip(_tri_g, _tri_g[1:])))
            _t_sg = _hasard_sg.random()
            _x_sg = (_a_sg[0] + (_b_sg[0] - _a_sg[0]) * _t_sg
                     + _hasard_sg.uniform(-0.03, 0.03))
            _y_sg = (_a_sg[1] + (_b_sg[1] - _a_sg[1]) * _t_sg
                     + _hasard_sg.uniform(-0.03, 0.03))
            _vrai = min(_tpg._point_segment(_x_sg, _y_sg, _p, _q)
                        for _p, _q in zip(_tri_g, _tri_g[1:])) < 0.0138
            _desaccords += _grille_sg.proche(_x_sg, _y_sg, 0.0138) != _vrai
        check('décalage : un long côté en biais ne fige plus la grille',
              len(_dec_tri) == 1 and _t_tri < 5.0 and _desaccords == 0,
              f'triangle de 80 mm décalé de 0,015 mm en {_t_tri:.2f} s · '
              f'{_desaccords} désaccord(s) sur 3000 points avec la recherche '
              f'exhaustive')

        # Élagage jugé d'un coup (EX-259). Un côté sans voisin à portée n'a
        # que de bons points : un rectangle de 94 mm décalé d'un dixième de
        # micron en faisait éprouver trois millions, 18 s. Sur un dessin
        # dense — mille points dans 2 mm, décalés de 3 —, chaque point
        # éprouvait tous les segments ; un arbre de boîtes trouve le
        # voisin. `juge` doit répondre comme `proche`, point par point.
        _rect_j = [(0.0, 0.0), (94.0, 0.0), (94.0, 8.0), (0.0, 8.0),
                   (0.0, 0.0)]
        _t_j = _time_g.perf_counter()
        _dec_j = _tpg.offset_contours([_rect_j], 0.0001)
        _t_j = _time_g.perf_counter() - _t_j
        _spi_j = [(_k / 1000 * _math_g.cos(_math_g.tau * 40 * _k / 1000),
                   _k / 1000 * _math_g.sin(_math_g.tau * 40 * _k / 1000))
                  for _k in range(1000)]
        _grille_j = _tpg._grille_source([_spi_j], 3.0)
        _dec_spi_j = _tpg._offset_polyline(_spi_j, 3.0)
        _seuil_j = 3.0 * _tpg.OFFSET_TOLERANCE
        _jug_j = _grille_j.juge(_dec_spi_j, 1.0, _seuil_j)
        _desacc_j = _eprouves_j = 0
        for _r, ((_x1, _y1), (_x2, _y2)) in enumerate(zip(_dec_spi_j,
                                                         _dec_spi_j[1:])):
            _n = max(1, int(_math_g.hypot(_x2 - _x1, _y2 - _y1)))
            _j = None if _jug_j is None else _jug_j.get(_r)
            for _k in range(_n + 1):
                _x = _x1 + (_x2 - _x1) * (_k / _n)
                _y = _y1 + (_y2 - _y1) * (_k / _n)
                _desacc_j += (bool(_j and _j[_k])
                              != _grille_j.proche(_x, _y, _seuil_j))
                _eprouves_j += 1
        _dense_j = max(map(len, _grille_j.cases.values())) > _tpg._DENSE
        check("décalage : un côté sans voisin n'est pas parcouru, un dessin "
              "dense se juge à l'arbre (EX-259)",
              len(_dec_j) == 1 and _t_j < 5.0 and _jug_j is not None
              and _dense_j and _desacc_j == 0,
              f'rectangle de 94 mm décalé de 0,0001 mm en {_t_j:.2f} s · '
              f'spirale dense : {_desacc_j} désaccord(s) sur {_eprouves_j} '
              f'points avec `proche`')

        # garde-fous : nombre de contours changé, cache borné
        _zg = _tpg.GroupZone(frozenset({0}), (), frozenset(), 3)
        _avant_c = _tpg._GROUPES_MAX
        for _k in range(_avant_c + 20):
            _cg = Document()
            _e = _cg.add(_Pth(polylines=[_geo.rect_contour(10 + _k * 0.01,
                                                           10)],
                              recipe=_rec_g))
            _i = _cg.add(_Pth(polylines=[_geo.rect_contour(4, 4)],
                              recipe=_rec_g))
            _cg.group([_e.id, _i.id])
            _tpg.group_zones(_cg.shapes)
        check('groupe : zone périmée écartée, mémoire bornée',
              _zg.contours([[(0, 0)], [(1, 1)]]) == [[(0, 0)], [(1, 1)]]
              and len(_tpg._GROUPES) <= _tpg._GROUPES_MAX
              and sum(_tpg._GROUPES_POINTS.values())
              <= _tpg._GROUPES_MAX_POINTS,
              f'{len(_tpg._GROUPES)} groupes retenus sur '
              f'{_avant_c + 20} calculés')
        # convertir en tracé, retourner
        from engrave import conversion as _conv
        from engrave.model import Circle as _Circ_c

        def _memes(_a, _b):
            return (len(_a) == len(_b) and all(
                len(_p) == len(_q) and all(
                    abs(_u[0] - _v[0]) < 1e-9 and abs(_u[1] - _v[1]) < 1e-9
                    for _u, _v in zip(_p, _q)) for _p, _q in zip(_a, _b)))

        _a_conv = [
            Text(text='TAU 2608', size_mm=6, x=3, y=-2, rotation_deg=20,
                 recipe=_rec_g, frame='rect', frame_margin_mm=1.5,
                 frame_offset_mm=0.1),
            Rect(width=12, height=5, x=-10, rotation_deg=35, recipe=_rec_g,
                 line_width_mm=0.3),
            _Circ_c(width=9, height=5, x=8, y=7, recipe=_rec_g,
                    frame='circle')]
        _conv_ok = [_memes(_tpg.shape_polylines(_f),
                           _tpg.shape_polylines(_conv.en_trace(_f)))
                    for _f in _a_conv]
        check('tracé : texte, rectangle, ellipse convertis gravent pareil',
              all(_conv_ok)
              and all(isinstance(_conv.en_trace(_f), _Pth)
                      and _conv.en_trace(_f).id == _f.id for _f in _a_conv),
              f'trajectoires identiques, rotation, cadre, décalage et '
              f'épaisseur compris : {_conv_ok}')

        # un « D » au premier contour posé sur l'axe : retourné, il doit
        # graver retourné — même extrémités, autre objet
        _d_r = _Pth(polylines=[[(0, 5), (4, 3), (4, -3), (0, -5), (0, 5)]],
                    x=12, y=4, rotation_deg=30, recipe=_rec_g)
        _r_r = Rect(width=6, height=2, x=-5, y=1, rotation_deg=10,
                    recipe=_rec_g)
        _bx = [_tpg.shape_extent(_f) for _f in (_d_r, _r_r)]
        _cx_r = (min(_b[0] for _b in _bx) + max(_b[2] for _b in _bx)) / 2
        _attendu_r = [(2 * _cx_r - _x, _y)
                      for _x, _y in _tpg.shape_polylines(_d_r)[0]]
        _tpg.shape_polylines(_d_r)          # trajectoires mises en cache
        _ret = _conv.retourner([_d_r, _r_r], 'h')
        _obtenu_r = _tpg.shape_polylines(_ret[0])[0]
        _deux = _conv.retourner(_conv.retourner([_d_r], 'v'), 'v')[0]
        check('retourner : autour du centre, objet neuf, deux fois rien',
              _ret[0] is not _d_r and _ret[1] is _r_r
              and all(min(abs(_u[0] - _v[0]) + abs(_u[1] - _v[1])
                          for _v in _obtenu_r) < 1e-9 for _u in _attendu_r)
              and abs(_ret[0].rotation_deg - 330.0) < 1e-9
              and _deux.polylines == _d_r.polylines
              and abs(_deux.y - _d_r.y) < 1e-9
              and not _conv.retournable([_d_r, Text(text='A')]),
              f'angle {_ret[0].rotation_deg:g}° · un texte ou un code se '
              f'convertit d' + chr(39) + 'abord')

        _doc_cv = Document(name='Retourner')
        window.new_tab(_doc_cv)
        app.processEvents()
        _t_cv = _doc_cv.add(Text(text='AB', size_mm=5, x=-10,
                                 recipe=_rec_g))
        _p_cv = _doc_cv.add(_Pth(polylines=[[(0, 5), (4, 3), (4, -3),
                                             (0, -5), (0, 5)]],
                                 x=10, recipe=_rec_g))
        window.canvas.reload()
        window._refresh_list()
        window.canvas.select_many([_t_cv.id])
        window._convert_to_path()
        app.processEvents()
        _apres_cv = _doc_cv.get(_t_cv.id)
        window.canvas.select_many([_t_cv.id, _p_cv.id])
        window._mirror('h')
        app.processEvents()
        _x_t_cv = _doc_cv.get(_t_cv.id).x
        check('retourner, convertir : le plan remplace sur place et '
              'garde la sélection',
              isinstance(_apres_cv, _Pth)
              and _doc_cv.shapes[0].id == _t_cv.id
              and len(_doc_cv.shapes) == 2
              and sorted(window.canvas.selected_ids())
              == sorted([_t_cv.id, _p_cv.id])
              and _doc_cv.get(_p_cv.id) is not _p_cv
              and abs(_x_t_cv - (-10.0)) > 1.0,
              f'{type(_apres_cv).__name__} · texte de x -10 à x {_x_t_cv:g}')

        # relecture : un tracé neuf ne reprend jamais les trajectoires d'un
        # tracé disparu, même s'il hérite de son adresse
        import copy as _copy_j, gc as _gc_j
        from engrave import repetition as _rep_j, resize as _rsz_j
        _perimes_j = 0
        for _essai_j in range(6):
            _tpg.clear_cache()
            _doc_j = Document(name='jetons')
            _doc_j.shapes.append(_Pth(
                polylines=[list(_geo.circle_contour(10.0)),
                           [(0.0, 2.0), (5.0, 6.0), (2.0, 6.0)]],
                recipe=_rec_g))
            _tpg.build_passes(_doc_j)
            _n_j = _conv.retourner([_doc_j.shapes[0]], 'v')
            _doc_j.shapes = list(_n_j)
            del _n_j
            _gc_j.collect()
            _rep_j.repeter(_doc_j, [_doc_j.shapes[0]], 3, 2, 25.0, 25.0)
            for _pj, _sj in zip(_tpg.build_passes(_doc_j), _doc_j.shapes):
                if max(_y for _x, _y in _pj.polylines[1]) > _sj.y + 1e-9:
                    _perimes_j += 1
        _p_j = _Pth(polylines=[[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0),
                                (0.0, 0.0)]], recipe=_rec_g)
        _cle_j = _tpg.geometry_key(_p_j)
        _copie_j = _copy_j.deepcopy(_p_j)
        _rsz_j.scale_shape(_p_j, 2.0, 2.0)
        check('cache : un tracé neuf ne reprend pas les trajectoires d'
              + chr(39) + 'un disparu',
              _perimes_j == 0
              and _tpg.geometry_key(_copie_j)[1] != _cle_j[1]
              and _tpg.geometry_key(_p_j)[1] != _cle_j[1],
              f'{_perimes_j} case périmée sur 36 · copie et mise à '
              f'l' + chr(39) + 'échelle renumérotées')

        # décalage dans un groupe : le contre-poinçon décalé seul se
        # referme ; le cadre d'un dessin séparé n'entre pas dans le compte
        _ext_k = _Pth(polylines=[_geo.rect_contour(10, 10)], recipe=_rec_g,
                      group='k')
        _cnt_k = _Pth(polylines=[_geo.rect_contour(4, 4)], recipe=_rec_g,
                      group='k', frame_offset_mm=0.2)
        _z_k = _tpg._zones_du_groupe([_ext_k, _cnt_k], None)
        _ret_k = _z_k[1].retournes if _z_k[1] is not None else frozenset()
        _b_k = _geo.bounds(_tpg.shape_contours(_cnt_k, None, _ret_k))
        _logo_k = _Pth(polylines=[_geo.rect_contour(10, 10),
                                  _geo.rect_contour(4, 4)], recipe=_rec_g,
                       frame='rect', frame_margin_mm=2.0,
                       frame_offset_mm=0.3)
        _mor_k = _sp.explode(_logo_k)
        for _m in _mor_k:
            _m.group = 'k2'
        _z2_k = _tpg._zones_du_groupe(_mor_k, None)
        _larg_k = []
        for _m, _z in zip(_mor_k, _z2_k):
            _r = _z.retournes if _z is not None else frozenset()
            _bb = _geo.bounds(_tpg.shape_contours(_m, None, _r))
            _larg_k.append(round(_bb[2] - _bb[0], 2))
        _seul_k = sorted(round(_geo.bounds([_c])[2] - _geo.bounds([_c])[0], 2)
                         for _c in _tpg.shape_contours(_logo_k))
        check('décalage en groupe : contre-poinçon refermé, cadre séparé '
              'hors compte',
              abs((_b_k[2] - _b_k[0]) - 3.6) < 1e-6
              and _mor_k[0].detached_frame
              and not any(_m.detached_frame for _m in _mor_k[1:])
              and sorted(_larg_k) == _seul_k,
              f'contre-poinçon {_b_k[2] - _b_k[0]:.2f} mm · séparé '
              f'{sorted(_larg_k)} = d' + chr(39) + f'un bloc {_seul_k}')

        # relecture : choix fermés, bornes, code inconnu, format, copies
        from engrave import model as _mod_v, serialize as _ser_v
        from engrave import barcode as _bc_v, wobble as _wob_v
        from engrave import textvec as _tv_v
        from PySide6.QtWidgets import QMessageBox as _QMB_v
        _rap_v = []
        _ser_v.document_from_dict({
            'format': '2', 'copies': 0,
            'shapes': [
                {'type': 'code', 'level': 'Z', 'data': '1'},
                {'type': 'text', 'align': 'justify', 'stretch': 1e9,
                 'line_spacing': 1e9},
                {'type': 'rect', 'frame': 'oval',
                 'recipe': {'wobble': 'zigzag', 'passes': 1e6}},
                {'type': 'rect', 'recipe': []},
                {'type': 'path', 'polylines': [[], [[0, 0], [1, 1]],
                                               [[0, 0], [2e4, 0]]]}]},
            _rap_v)
        _txt_v = ' | '.join(_rap_v)
        try:
            _ser_v.shape_from_dict({'type': 'code', 'kind': 'pdf417'})
            _refus_v = False
        except ValueError:
            _refus_v = True
        _mod_v.unreported_repairs()
        _mod_v.recipe_from_dict({'power_percent': '20', 'passes': 2.5})
        _non_dits_v = _mod_v.unreported_repairs()
        check('relecture : choix inconnus, démesures, format et copies '
              'remplacés et dits ; code inconnu refusé',
              _refus_v and len(_rap_v) == 11
              and all(_m in _txt_v for _m in (
                  'format', 'copies', 'level', 'align', 'stretch',
                  'line_spacing', 'frame', 'wobble', 'passes',
                  'process illisible', '2 point(s)'))
              and len(_non_dits_v) == 2
              and _mod_v.unreported_repairs() == []
              and _mod_v.CODE_KINDS == tuple(_k for _k, _ in _bc_v.KINDS)
              and _mod_v.CHOIX['wobble'] == tuple(_w[0]
                                                  for _w in _wob_v.SHAPES)
              and _mod_v.CHOIX['align'] == _tv_v.HALIGN
              and _mod_v.CHOIX['valign'] == _tv_v.VALIGN
              and _mod_v.CHOIX['dm_shape'] == tuple(
                  _k for _k, _ in _bc_v.DM_SHAPES)
              and _mod_v.CHOIX['level'] == tuple(
                  _k for _k, _ in _bc_v.QR_LEVELS),
              f'{len(_rap_v)} remplacements dits, 2 sans compte rendu '
              f'relevés à part')

        # ce qui se remplace sans compte rendu, ou au démarrage, se montre
        window.last_repair_alert = None
        _mod_v.recipe_from_dict({'passes': 2.5})
        window._update_status()
        _alerte_1 = window.last_repair_alert
        window._report_repairs('reprise.taudrive', ['forme 1 : x = 1e12'],
                               True)
        app.processEvents()
        _alerte_2 = window.last_repair_alert
        for _boite in window.findChildren(_QMB_v):
            if not _boite.isModal():
                _boite.close()
        app.processEvents()
        check('relecture : les remplacements sans compte rendu et ceux du '
              'démarrage se montrent',
              _alerte_1 is not None and _alerte_1[0] == 'Valeurs illisibles'
              and 'passes' in _alerte_1[1][0]
              and _alerte_2 is not None
              and _alerte_2[0].startswith('Reprise')
              and _alerte_2[1] == ['forme 1 : x = 1e12'],
              'fenêtre non modale, à l' + chr(39) + 'écran et non sur '
              'stderr seul')

        # convertir un texte qui suit un code : on prévient
        _q_v = []
        _question_v = _QMB_v.question
        _QMB_v.question = staticmethod(lambda *a, **k: (
            _q_v.append(a[2]), _QMB_v.StandardButton.Cancel)[1])
        try:
            _suit_v = Text(text='B000001', recipe=_rec_g)
            _suit_v.follows = 'code-quelconque'
            _accord_v = window._accept_frozen_fields([_suit_v],
                                                     'Convertir en tracé')
            _libre_v = window._accept_frozen_fields(
                [Text(text='libre', recipe=_rec_g)], 'Convertir en tracé')
        finally:
            _QMB_v.question = _question_v
        check('convertir : un texte qui suit un code fait prévenir',
              not _accord_v and _libre_v and len(_q_v) == 1
              and 'suivent un code' in _q_v[0],
              'retaper le code ne changerait plus le texte converti')

        # cintrer un texte en arc : la ligne de base sur le cercle
        from engrave import cintrage as _cin
        from PySide6.QtWidgets import (QDialog as _QD_cin,
                                       QDialogButtonBox as _QBB_cin)
        _arcs_ok = True
        _notes_cin = []
        for _cote_c in ('haut', 'bas'):
            for _rot_c in (0.0, 35.0):
                _txt_cin = Text(text='CLUB DE VOILE', size_mm=4, x=5, y=-3,
                                rotation_deg=_rot_c, recipe=_rec_g)
                _arc_c = _cin.cintrer(_txt_cin, 20.0, _cote_c)
                _base_c, _dy_c = _cin._base(_txt_cin, None)
                _pieds = [(_x, _y) for _c in _base_c for _x, _y in _c
                          if abs(_y) < 1e-9]
                _xs_c = [_x for _c in _base_c for _x, _ in _c]
                _cx_c = (min(_xs_c) + max(_xs_c)) / 2
                # le milieu de la ligne de base n'a pas bougé
                _a_c = _math_g.radians(_rot_c)
                _mx = (_txt_cin.x + _cx_c * _math_g.cos(_a_c)
                       - _dy_c * _math_g.sin(_a_c))
                _my = (_txt_cin.y + _cx_c * _math_g.sin(_a_c)
                       + _dy_c * _math_g.cos(_a_c))
                _ly = 20.0 if _cote_c == 'haut' else -20.0
                _wx = _arc_c.x - _ly * _math_g.sin(_a_c)
                _wy = _arc_c.y + _ly * _math_g.cos(_a_c)
                _dist = [_math_g.hypot(_x, _y)
                         for _c in _tpg.own_contours(_arc_c) for _x, _y in _c]
                _arcs_ok &= (
                    isinstance(_arc_c, _Pth)
                    and abs(_wx - _mx) < 1e-9 and abs(_wy - _my) < 1e-9
                    and len(_arc_c.polylines) == len(_base_c)
                    and _arc_c.rotation_deg == _rot_c
                    and _arc_c.id == _txt_cin.id
                    and bool(_pieds)
                    and (min(_dist) > 19.8 if _cote_c == 'haut'
                         else max(_dist) < 20.2))
                _notes_cin.append(f'{_cote_c} {min(_dist):.2f}–'
                                  f'{max(_dist):.2f}')
        _court = Text(text='CLUB', size_mm=4, recipe=_rec_g)
        check('cintrer : ligne de base sur le cercle, milieu en place',
              _arcs_ok and _cin.probleme(_court, 1.0, 'haut') != ''
              and _cin.probleme(_court, 3.0, 'bas') != ''
              and _cin.probleme(_court, 8.0, 'bas') == ''
              and 100 < _cin.angle_deg(
                  Text(text='CLUB DE VOILE', size_mm=4),
                  _cin.rayon_naturel(Text(text='CLUB DE VOILE', size_mm=4)))
              < 140,
              ' · '.join(_notes_cin) + ' mm du centre')

        _doc_cin = Document(name='Cintrer')
        window.new_tab(_doc_cin)
        app.processEvents()
        _t_cin = _doc_cin.add(Text(text='BAGUE', size_mm=3, recipe=_rec_g))
        window.canvas.reload()
        window._refresh_list()
        window.canvas.select_many([_t_cin.id])
        _dlg_cin = _cin.CintrageDialog(None, _t_cin)
        _dlg_cin.w_rayon.setValue(0.6)
        _refus_cin = not _dlg_cin.w_buttons.button(
            _QBB_cin.StandardButton.Ok).isEnabled()
        _dlg_cin.w_rayon.setValue(12.0)
        _dlg_cin.w_cote.setCurrentIndex(1)
        _accord_cin = _dlg_cin.w_buttons.button(
            _QBB_cin.StandardButton.Ok).isEnabled()
        _vals_cin = _dlg_cin.values()
        _dlg_cin.deleteLater()
        _exec_cin = _cin.CintrageDialog.exec
        _cin.CintrageDialog.exec = lambda self: (
            self.w_rayon.setValue(12.0),
            _QD_cin.DialogCode.Accepted)[1]
        try:
            window._bend_text()
        finally:
            _cin.CintrageDialog.exec = _exec_cin
        app.processEvents()
        _apres_cin = _doc_cin.get(_t_cin.id)
        _relu_cin = serialize.loads(serialize.dumps(_doc_cin))
        check('cintrer : le dialogue refuse un rayon trop court, le plan '
              'remplace sur place',
              _refus_cin and _accord_cin and _vals_cin == (12.0, 'bas')
              and isinstance(_apres_cin, _Pth)
              and window.canvas.selected_ids() == [_t_cin.id]
              and _relu_cin.shapes[0].polylines == [
                  [tuple(_q) for _q in _c] for _c in _apres_cin.polylines],
              f'{len(_apres_cin.polylines)} contours, relu à l'
              + chr(39) + 'identique')

        # lecture tolérante : une valeur illisible prend son défaut, et se dit
        from engrave import serialize as _ser_t
        from engrave import ordering as _ord_t
        from engrave.model import Circle as _Circ_t, Code as _Code_t
        _doc_t = Document(name='tolérance')
        _doc_t.add(Rect(width=10, height=5, recipe=_rec_g, frame='rect'))
        _doc_t.add(_Circ_t(width=6, height=4, x=10, recipe=_rec_g))
        _doc_t.add(Text(text='AB {n}', size_mm=4, x=-10, recipe=_rec_g))
        _doc_t.add(_Code_t(kind='datamatrix', data='X1', module_mm=0.4,
                           y=10, recipe=_rec_g))
        _doc_t.add(_Pth(polylines=[[(0, 0), (3, 0), (3, 3), (0, 0)]],
                        y=-10, recipe=_rec_g))
        _doc_t.group([_doc_t.shapes[0].id, _doc_t.shapes[1].id])
        _sain_t = _ser_t.document_to_dict(_doc_t)
        _rap0 = []
        _relu_t = _ser_t.document_from_dict(
            _ser_t.document_to_dict(_doc_t), _rap0)
        check('lecture : un document sain se relit à l' + chr(39)
              + 'identique, sans rien signaler',
              not _rap0 and _ser_t.document_to_dict(_relu_t) == _sain_t,
              f'{len(_doc_t.shapes)} formes, aller-retour exact')

        import copy as _copy_t
        _abime = _copy_t.deepcopy(_sain_t)
        _abime['shapes'][0]['width'] = 'abc'
        _abime['shapes'][1]['recipe']['wobble_amp_mm'] = []
        _abime['shapes'][1]['recipe']['passes'] = 3.0
        _abime['shapes'][2]['size_mm'] = 0
        _abime['shapes'][2]['recipe']['hatch_mm'] = 1e-9
        _abime['shapes'][3]['x'] = 1e12
        _abime['shapes'][4]['polylines'][0][1] = ['a', None]
        _abime['field_w'] = None
        _rap_t = []
        _doc_ab = _ser_t.document_from_dict(_abime, _rap_t)
        _passes_ab = _tpg.build_passes(_doc_ab)
        _textes_rap = ' | '.join(_rap_t)
        check('lecture : valeurs illisibles remplacées et nommées, le '
              'document se grave',
              len(_rap_t) == 6 and 'forme 1 : width' in _textes_rap
              and 'wobble_amp_mm' in _textes_rap
              and 'hatch_mm' in _textes_rap and 'forme 4 : x' in _textes_rap
              and 'point' in _textes_rap and 'field_w' in _textes_rap
              and _doc_ab.shapes[0].width == 20.0
              and _doc_ab.shapes[1].recipe.passes == 3
              and isinstance(_doc_ab.shapes[1].recipe.passes, int)
              and len(_doc_ab.shapes[4].polylines[0]) == 3
              and bool(_passes_ab),
              f'{len(_rap_t)} remplacements : {_textes_rap[:150]}')

        _refus_t = []
        for _casse in ({'shapes': [5]}, {'shapes': [{'type': 'zzz'}]},
                       {'shapes': 7}, [1, 2]):
            try:
                _ser_t.document_from_dict(_casse, [])
                _refus_t.append(False)
            except ValueError:
                _refus_t.append(True)
        check('lecture : une forme cassée fait refuser le document',
              all(_refus_t),
              'pas de pièce gravée incomplète en silence')

        # plus proche voisin : même ordre, bien plus vite
        _semis_o = [[(_x * 0.7, _y * 0.3), (_x * 0.7 + 0.5, _y * 0.3)]
                    for _x in range(60) for _y in range(60)]
        _semis_o += [[(30 + _k % 7, -5 - _k // 7), (31 + _k % 7, -5 - _k // 7)]
                     for _k in range(70)]
        _t_o = _time_g.perf_counter()
        _ordre_o = _ord_t.nearest_neighbour(_semis_o, (0.0, 0.0))
        _t_o = _time_g.perf_counter() - _t_o
        _vus_o = set()
        _ok_o = len(_ordre_o) == len(_semis_o)
        for _pl in _ordre_o:
            _cle_o = tuple(sorted(_pl))
            _ok_o &= _cle_o not in _vus_o
            _vus_o.add(_cle_o)
        _pas_o = [_ord_t._dist(_ordre_o[_k][-1], _ordre_o[_k + 1][0])
                  for _k in range(len(_ordre_o) - 1)]
        check('parcours : plus proche voisin complet, sans doublon, rapide',
              _ok_o and max(_pas_o[:3000]) < 2.0 and _t_o < 5.0,
              f'{len(_ordre_o)} tracés en {_t_o:.2f} s')

        # glyphes et contours mémorisés : les mêmes, bien plus vite
        from engrave import textvec as _tv_c
        _tv_c._GLYPHES.clear()
        _tv_c._GLYPHES_POINTS[0] = 0
        _t_c = _time_g.perf_counter()
        _froids = [_tv_c.layout(f'B{_i:06}', 1.2) for _i in range(150)]
        _t_c = _time_g.perf_counter() - _t_c
        _t_c2 = _time_g.perf_counter()
        _chauds = [_tv_c.layout(f'B{_i:06}', 1.2) for _i in range(150)]
        _t_c2 = _time_g.perf_counter() - _t_c2
        # un glyphe tracé sans la mémoire, à la main, pour référence
        _font_c, _upem_c, _cmap_c = _tv_c._load(_tv_c.default_font_path())
        _gs_c = _font_c.getGlyphSet()
        _nom_c = _tv_c._glyph_for(_cmap_c, '8')
        _stylo_c = _tv_c._ContourPen(_gs_c, 0.5)
        _gs_c[_nom_c].draw(_stylo_c)
        _ref_c = tuple(tuple(_c) for _c in _stylo_c.contours)
        check('texte : glyphes mémorisés, contours identiques au bit près',
              _froids == _chauds
              and _tv_c._glyph_contours(_tv_c.default_font_path(), _gs_c,
                                        _nom_c, 0.5) == _ref_c
              and 0 < len(_tv_c._GLYPHES) < 40
              and _tv_c._GLYPHES_POINTS[0] <= _tv_c._GLYPHES_MAX_POINTS,
              f'150 numéros : {_t_c:.3f} s puis {_t_c2:.3f} s, '
              f'{len(_tv_c._GLYPHES)} glyphes retenus')

        # une police se remplit en non nul : des traits superposés ne se
        # gravent plus en trous, des contours qui ne se croisent pas
        # reviennent tels quels
        from engrave import geometry as _geo_z

        def _carre_z(x0, y0, x1, y1):
            return [(x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0)]

        def _aire_z(_cs):
            return sum(abs(sum(_a[0] * _b[1] - _b[0] * _a[1]
                               for _a, _b in zip(_c, _c[1:]))) / 2
                       for _c in _cs)
        # un « E » de police variable : un fût, un bras posé dessus
        _e_z = _geo_z.nonzero_contours([_carre_z(0, 0, 2, 10),
                                        _carre_z(1, 8, 6, 10)])
        _x_z = _geo_z.nonzero_contours([_carre_z(0, 4, 10, 6),
                                        _carre_z(4, 0, 6, 10)])
        _o_z = [_carre_z(0, 0, 10, 10), _carre_z(3, 3, 7, 7)[::-1]]
        # deux contours identiques, et deux qui ne se croisent qu'en des
        # sommets communs : sans croisement calculé, ils revenaient tels
        # quels, et la règle pair-impair en faisait un trou
        _double_z = _geo_z.nonzero_contours([_carre_z(0, 0, 10, 10),
                                             _carre_z(0, 0, 10, 10)])
        # une croix dont les deux barres ont des sommets aux croisements
        _sommets_z = _geo_z.nonzero_contours(
            [[(0, 4), (4, 4), (6, 4), (10, 4), (10, 6), (6, 6), (4, 6),
              (0, 6), (0, 4)],
             [(4, 0), (6, 0), (6, 4), (6, 6), (6, 10), (4, 10), (4, 6),
              (4, 4), (4, 0)]])
        _rangs_z = [_seg for _seg in _geo_z.hatch(_e_z, 0.25)
                    if 8.0 < _seg[0][1] < 10.0]
        check('non nul : traits superposés fondus, un trou reste un trou',
              len(_e_z) == 1 and abs(_aire_z(_e_z) - 28.0) < 1e-9
              and len(_x_z) == 1 and abs(_aire_z(_x_z) - 36.0) < 1e-9
              and _geo_z.nonzero_contours(_o_z) is _o_z
              and len(_double_z) == 1
              and abs(_aire_z(_double_z) - 100.0) < 1e-9
              and len(_sommets_z) == 1
              and abs(_aire_z(_sommets_z) - 36.0) < 1e-9
              and all(abs(abs(_seg[1][0] - _seg[0][0]) - 6.0) < 1e-9
                      for _seg in _rangs_z) and _rangs_z,
              f'« E » : {len(_e_z)} contour, aire {_aire_z(_e_z):g} mm² '
              f'(28 attendus, 26 en pair-impair)')

        # sur de vraies polices : la cédille d'Arial chevauche son « c »,
        # Bahnschrift superpose ses traits, Segoe Script lie ses lettres
        def _police_z(_nom):
            _ch = _tv_c.WINDOWS_FONTS / _nom
            return str(_ch) if _ch.exists() else ''
        _arial_z = _police_z('arial.ttf')
        _bahn_z = _police_z('bahnschrift.ttf')
        _script_z = _police_z('segoesc.ttf')
        _vus_z = []
        _ok_z = True
        if _arial_z:
            _ok_z &= len(_tv_c.outline('ç', 5.0, _arial_z)) == 1
            _vus_z.append('ç Arial')
        if _bahn_z:
            _ok_z &= all(len(_tv_c.outline(_ch, 5.0, _bahn_z)) == 1
                         for _ch in 'EFHKTk4')
            _vus_z.append('Bahnschrift')
        if _script_z:
            _seules_z = sum(len(_tv_c.outline(_ch, 5.0, _script_z))
                            for _ch in 'nj')
            _ok_z &= len(_tv_c.outline('nj', 5.0, _script_z)) < _seules_z
            _vus_z.append('Segoe Script')
        check('non nul : lettres d' + chr(39) + 'une police variable ou de '
              'script remplies sans trou',
              _ok_z, ', '.join(_vus_z) or 'aucune de ces polices ici')

        _tpg.clear_cache()
        _txt_c = Text(text='Lot {n}', size_mm=3, recipe=_rec_g)
        _a_c = _tpg.own_contours(_txt_c)
        _a_c[0].append((99.0, 99.0))
        _a_c.append([(0.0, 0.0)])
        _b_c = _tpg.own_contours(_txt_c)
        _gen_c = _tv_c.font_generation()
        _cle_c = _tpg.drawing_key(_txt_c)
        _tv_c._GENERATION[0] += 1          # ce que fait `refresh_fonts`
        check('contours : un texte se dessine une fois, chacun sa copie',
              len(_b_c) == len(_a_c) - 1 and (99.0, 99.0) not in _b_c[0]
              and len(_tpg._PROPRES) == 1
              and _tv_c.font_generation() == _gen_c + 1
              and _tpg.drawing_key(_txt_c) != _cle_c
              and _tpg.own_contours(_txt_c) == _b_c,
              'relire les polices redessine les textes')

        check('couteau : ses contours se placent (géométrie importée)',
              getattr(_app_g, 'G', None) is _geo, 'engrave.app.G')

        # export vectoriel
        _doc_ex = Document(name='Export')
        _doc_ex.add(Rect(width=40, height=20, recipe=PRESET_RECIPES[1],
                         name='cadre'))
        _doc_ex.add(Text(text='TAU', size_mm=8,
                         recipe=dataclasses.replace(PRESET_RECIPES[1],
                                                    hatch_mm=0.4),
                         name='texte'))
        _bac = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-vex-'))
        _ecrits = {}
        for _k in ('dxf', 'eps', 'ai'):
            _f = _bac / f'essai.{_k}'
            _ecrits[_k] = (_vex.export(_doc_ex, _f), _f.stat().st_size)
        check('export : DXF, EPS et AI écrits, tracés comptés',
              all(n > 0 and taille > 0 for n, taille in _ecrits.values())
              and len({n for n, _ in _ecrits.values()}) == 1,
              ' · '.join(f'{k} {n} tracés {t} o'
                         for k, (n, t) in _ecrits.items()))

        _relu, _rapex = _vec.read(_bac / 'essai.eps')
        _lx, _hy = _rapex.size_mm()
        check('export : l' + chr(39) + 'EPS produit se relit à la cote',
              abs(_lx - 40.0) < 0.02 and abs(_hy - 20.0) < 0.02,
              f'{_lx:.3f} × {_hy:.3f} mm pour 40 × 20')

        import ezdxf as _ez
        _dxf_relu = _ez.readfile(_bac / 'essai.dxf')
        _calques = sorted({e.dxf.layer for e in _dxf_relu.modelspace()})
        check('export : le DXF porte un calque par forme',
              _calques == ['cadre', 'texte'], ' · '.join(_calques))

        # Export DXF linéaire (EX-260). ezdxf ajoutait les sommets d'une
        # polyligne un à un, en recopiant tout son tableau à chaque fois :
        # 12 s pour une spirale de 40 000 points. Posés d'un bloc, ils
        # donnent les mêmes entités, octet pour octet, que celles
        # qu'`add_lwpolyline` écrit — calques, fermeture et tracés dégénérés
        # compris.
        import math as _math_x
        import time as _time_x
        _n_x = 40000
        _spi_x = [(_k / _n_x * 50 * _math_x.cos(_math_x.tau * 40 * _k / _n_x),
                   _k / _n_x * 50 * _math_x.sin(_math_x.tau * 40 * _k / _n_x))
                  for _k in range(_n_x)]
        _t_x = _time_x.perf_counter()
        _vex.write_dxf([('spirale', [_spi_x])], _bac / 'spirale.dxf')
        _t_x = _time_x.perf_counter() - _t_x
        _couches_x = [('a', [_spi_x[:2000], _geo.rect_contour(20, 10)]),
                      ('b', [[(0.0, 0.0), (5.0, 0.0)], [(1.0, 1.0), (1.0, 1.0)],
                             [(3.0, 3.0)]]),
                      ('a', [_geo.translate(_geo.rect_contour(4, 4), 7, 7)])]
        _vex.write_dxf(_couches_x, _bac / 'neuf.dxf')
        _ref_x = _ez.new('R2000', setup=True)
        _ref_x.header['$INSUNITS'] = 4
        for _nom_x, _polys_x in _couches_x:
            if _nom_x not in _ref_x.layers:
                _ref_x.layers.add(_nom_x)
            for _q in _polys_x:
                if len(_q) < 2:
                    continue
                _ferme_x = (abs(_q[0][0] - _q[-1][0]) < 1e-6
                            and abs(_q[0][1] - _q[-1][1]) < 1e-6)
                _ref_x.modelspace().add_lwpolyline(
                    [(float(_x), float(_y))
                     for _x, _y in (_q[:-1] if _ferme_x else _q)],
                    dxfattribs={'layer': _nom_x}, close=_ferme_x)
        _ref_x.saveas(_bac / 'ref.dxf')

        def _entites_x(_f):
            _t = _f.read_text(encoding='utf-8')
            _d = _t.index('\nENTITIES\n')
            return _t[_d:_t.index('\nENDSEC\n', _d)]

        _meme_x = _entites_x(_bac / 'neuf.dxf') == _entites_x(_bac / 'ref.dxf')
        check("export : le DXF pose les sommets d'un bloc, mêmes entités "
              "(EX-260)",
              _t_x < 4.0 and _meme_x,
              f'spirale de 40 000 points en {_t_x:.2f} s · entités '
              f'{"identiques" if _meme_x else "DIFFÉRENTES"} à celles '
              f"d'add_lwpolyline")

        # --- SVG : lecture, discrétisation, écriture -----------------------------
        from engrave import svgread as _svg
        from engrave import geometry as _geo
        import math as _msvg
        from engrave import dxfimport as _dxi
        _src_svg = _bac / 'cote.svg'
        _src_svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
            'height="60mm" viewBox="0 0 100 60">'
            '<rect x="10" y="10" width="80" height="40" fill="none"/>'
            '<circle cx="50" cy="30" r="15" fill="none"/>'
            '</svg>', encoding='utf-8')
        _polys_svg, _rap_svg = _svg.read(_src_svg.read_bytes(), 0.02)
        _bs = [_geo.bounds([q]) for q in _polys_svg]
        _rect = max(_bs, key=lambda b: (b[2] - b[0]))
        _cerc = min(_bs, key=lambda b: (b[2] - b[0]))
        # un cercle discrétisé est *inscrit* : sa boîte est plus petite que le
        # diamètre d'exactement une flèche, comme partout ailleurs dans TauDrive
        check('SVG : les cotes déclarées sont respectées',
              abs((_rect[2] - _rect[0]) - 80.0) < 0.001
              and abs((_rect[3] - _rect[1]) - 40.0) < 0.001
              and 30.0 - 0.041 <= (_cerc[2] - _cerc[0]) <= 30.0,
              f'rect {_rect[2] - _rect[0]:.3f} × {_rect[3] - _rect[1]:.3f} '
              f'exact · cercle inscrit Ø{_cerc[2] - _cerc[0]:.4f} '
              f'pour 30, soit une flèche')

        check('SVG : les cotes se lisent sans texte dans le fichier',
              _rap_svg.get('textes') == 0 and _rap_svg.get('echelle_mm') == 1.0,
              'échelle et emprise ne dépendent pas du texte')

        _svg_avec_texte = ('<svg xmlns="http://www.w3.org/2000/svg" '
                           'viewBox="0 0 100 60">'
                           '<text x="5" y="20" font-size="10" '
                           'font-family="Arial">Bonjour</text>'
                           '<text x="5" y="40" font-size="10"></text>'
                           '</svg>').encode('utf-8')
        _polys_txt, _rap_txt = _svg.read(_svg_avec_texte, 0.02)
        check('SVG : le texte est rendu en contours, pas laissé de côté',
              len(_polys_txt) > 5 and _rap_txt.get('textes') == 1,
              f'{len(_polys_txt)} contours pour "Bonjour" · le texte vide '
              f'reste compté ({_rap_txt.get("textes")})')

        # La taille d un texte SVG est un cadratin, pas une hauteur de
        # capitale : un H en Arial corps 10 fait 7,16, comme dans tout
        # navigateur. Il sortait a 10 — 40 % trop grand.
        _svg_h = ('<svg xmlns="http://www.w3.org/2000/svg" '
                  'viewBox="0 0 100 60">'
                  '<text x="5" y="20" font-size="10" '
                  'font-family="Arial">H</text></svg>').encode('utf-8')
        _polys_h, _rap_h = _svg.read(_svg_h, 0.02)
        _yh = [y for q in _polys_h for _, y in q]
        _h_svg = max(_yh) - min(_yh)
        from engrave import textvec as _tv_em
        _attendu_svg = 10 * _tv_em.em_ratio(_tv_em.default_font_path()
                                            if not (_tv_em.WINDOWS_FONTS
                                                    / 'arial.ttf').exists()
                                            else str(_tv_em.WINDOWS_FONTS
                                                     / 'arial.ttf'))
        # sans largeur declaree, l unite du viewBox est le pixel : le
        # lecteur rend son facteur, on le reporte sur l attendu
        _attendu_svg *= float(_rap_h.get('echelle_mm') or 1.0)
        check('SVG : un texte corps 10 a la hauteur d un navigateur, pas 10',
              abs(_h_svg - _attendu_svg) < 0.02,
              f'H corps 10 : {_h_svg:.3f} de haut, attendu '
              f'{_attendu_svg:.3f}')

        # --- SVG : texte a l endroit, styles herites, calques masques -----
        _ent = ('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
                'height="60mm" viewBox="0 0 100 60">')

        def _lire_svg(_corps: str):
            return _svg.read((_ent + _corps + '</svg>').encode('utf-8'), 0.02)

        # un L : sa barre en bas, la lettre au-dessus de sa ligne de base.
        # Les glyphes sortaient la tete en bas, pendus sous la ligne.
        _pl, _ = _lire_svg('<text x="10" y="40" font-size="20" '
                           'font-family="Arial">L</text>')
        _pts = [q for _p in _pl for q in _p]
        _yl = [y for _, y in _pts]
        _xm = max(x for x, _ in _pts)
        _barre = max(y for x, y in _pts if x > _xm - 0.3)
        check('SVG : le texte est a l endroit, au-dessus de sa ligne de base',
              abs(min(_yl) + 40.0) < 1e-6 and max(_yl) > -40.0
              and _barre < (min(_yl) + max(_yl)) / 2,
              f'L de y {min(_yl):.2f} a {max(_yl):.2f}, barre en bas')

        from engrave import fontmap as _fm_svg
        _cap10 = 10 * _tv_em.em_ratio(_fm_svg.resolve('Arial')[0])
        _pg, _ = _lire_svg('<g style="font-family:Arial;font-size:10px">'
                           '<text x="10" y="40">H</text></g>')
        _pp, _ = _lire_svg('<text x="10" y="40" style="font-size:7.5pt;'
                           'font-family:Arial">H</text>')
        _hg = max(y for q in _pg for _, y in q) - min(y for q in _pg
                                                       for _, y in q)
        _hp = max(y for q in _pp for _, y in q) - min(y for q in _pp
                                                       for _, y in q)
        check('SVG : la taille vient du style, du groupe parent, et des unites',
              abs(_hg - _cap10) < 0.02 and abs(_hp - _cap10) < 0.02,
              f'style herite {_hg:.3f} · 7,5 pt {_hp:.3f} · attendu '
              f'{_cap10:.3f}')

        # une taille relative se resout une fois, sur celle du parent
        def _haut_svg(_corps):
            _q, _ = _lire_svg(_corps)
            return (max(y for c in _q for _, y in c)
                    - min(y for c in _q for _, y in c))
        _rel = [_haut_svg(_c) for _c in (
            '<text x="10" y="40" font-family="Arial" font-size="1.25em">'
            '<tspan x="10" y="40">H</tspan></text>',
            '<g font-size="40" font-family="Arial"><text x="10" y="40" '
            'font-size="50%">H</text></g>',
            '<g style="font-size:10px;font-family:Arial"><text x="10" y="40" '
            'style="font-size:2em"><tspan>H</tspan></text></g>')]
        check('SVG : une taille relative (em, %) se resout sur son parent',
              all(abs(_h - 2 * _cap10) < 0.02 for _h in _rel),
              ' · '.join(f'{_h:.3f}' for _h in _rel)
              + f' · attendu {2 * _cap10:.3f}')

        # un calque masque d Inkscape n est pas grave
        _pm, _rm = _lire_svg(
            '<rect x="5" y="5" width="10" height="10"/>'
            '<g style="display:none"><rect x="50" y="5" width="40" '
            'height="40"/></g><rect x="70" y="50" width="5" height="5" '
            'display="none"/><rect x="80" y="50" width="5" height="5" '
            'style="visibility:hidden"/>')
        check('SVG : ce qui est masque ne se grave pas',
              len(_pm) == 1 and _rm.get('masques') == 3,
              f'{len(_pm)} trace grave · {_rm.get("masques")} masques ecartes '
              f'(calque, attribut, visibilite)')

        # deux lignes en tspan restent deux lignes ; l ancre se respecte
        _pt2, _ = _lire_svg('<text style="font-size:10px;font-family:Arial">'
                            '<tspan x="5" y="20">AB</tspan>'
                            '<tspan x="5" y="35">CD</tspan></text>')
        _bas = [min(y for _, y in q) for q in _pt2]
        _pa, _ = _lire_svg('<text x="50" y="30" style="font-size:10px;'
                           'font-family:Arial;text-anchor:middle">HH</text>')
        _xa = [x for q in _pa for x, _ in q]
        check('SVG : chaque tspan a sa place, l ancre centre le bloc',
              any(abs(b + 20.0) < 0.2 for b in _bas)
              and any(abs(b + 35.0) < 0.3 for b in _bas)
              and max(x for q in _pt2 for x, _ in q) < 25
              and abs((min(_xa) + max(_xa)) / 2 - 50.0) < 0.05,
              'deux lignes a y -20 et -35 · bloc centre sur 50')

        # la flèche d'une corde doit tenir dans la tolérance, quel que soit le
        # rayon : un compte fixe de segments rate toujours d'un côté
        _rond = [q for q, b in zip(_polys_svg, _bs)
                 if abs((b[2] - b[0]) - 30.0) < 0.05][0]
        _cx = (_cerc[0] + _cerc[2]) / 2.0
        _cy = (_cerc[1] + _cerc[3]) / 2.0
        _rayons = [((x - _cx) ** 2 + (y - _cy) ** 2) ** 0.5 for x, y in _rond]
        _fleche = 15.0 - min(_rayons)
        _comptes = [_svg.arc_steps(r, 2 * _msvg.pi, 0.02) for r in (2, 15, 100)]
        check('SVG : la finesse des arcs suit la tolérance, pas un compte fixe',
              _fleche <= 0.0201 and max(_rayons) <= 15.0101
              and _comptes[0] < _comptes[1] < _comptes[2],
              f'flèche {_fleche:.4f} mm pour 0,0200 · '
              f'{_comptes[0]}/{_comptes[1]}/{_comptes[2]} cordes à r=2/15/100')

        # Inkscape comptait 90 pixels par pouce jusqu'en 0.92 : un vieux
        # fichier sans unité sort 6,25 % petit — assez peu pour passer
        # inaperçu, assez pour mettre une pièce au rebut
        _ns_ink = 'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'

        def _svg_ink(attrs):
            _f = _bac / 'ink.svg'
            _f.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" {_ns_ink} '
                          f'{attrs}><rect x="0" y="0" width="100" height="50"/>'
                          f'</svg>', encoding='utf-8')
            return _svg.read(_f.read_bytes(), 0.02)[1].get('avertissement', '')

        _vieux = _svg_ink('inkscape:version="0.48.5" viewBox="0 0 200 100"')
        _neuf = _svg_ink('inkscape:version="1.3" viewBox="0 0 200 100"')
        _cote = _svg_ink('inkscape:version="0.48.5" width="200mm" '
                         'viewBox="0 0 200 100"')
        check('SVG : un vieux fichier Inkscape à 90 ppp est signalé',
              bool(_vieux) and not _neuf and not _cote
              and '6,25' in _vieux and abs(_svg.FACTEUR_90 - 96 / 90) < 1e-12,
              'seulement quand aucune unité physique ne le contredit')

        _formes_svg, _ = _dxi.any_to_shapes(str(_src_svg))
        check('SVG : reconnu et lu par la porte commune aux imports',
              _vec.sniff(str(_src_svg)) == 'svg' and len(_formes_svg) == 1
              and '.svg' in _dxi.ALL_SUFFIXES and '*.svg' in _dxi.FILE_FILTER,
              f'{len(_formes_svg)} forme(s)')

        # --- texte DXF : rendu, pas ignoré ----------------------------------------
        import ezdxf as _ez_txt
        _doc_txt = _ez_txt.new('R2010')
        _doc_txt.header['$INSUNITS'] = 4
        _msp_txt = _doc_txt.modelspace()
        _msp_txt.add_text('Grave-moi', dxfattribs={'height': 5.0}
                          ).set_placement((10, 10))
        _msp_txt.add_mtext('Ligne un\\PLigne deux',
                           dxfattribs={'char_height': 3.0, 'insert': (0, 0),
                                      'attachment_point': 1})
        _dxf_txt = _bac / 'texte.dxf'
        _doc_txt.saveas(str(_dxf_txt))
        _layers_txt, _rap_dxf_txt = _dxi.read(str(_dxf_txt))
        _total_pts_txt = sum(len(p) for polys in _layers_txt.values()
                            for p in polys)
        check('DXF : TEXT et MTEXT sont rendus en contours',
              sum(len(v) for v in _layers_txt.values()) > 10
              and _total_pts_txt > 100,
              f'{sum(len(v) for v in _layers_txt.values())} polylignes · '
              f'{_total_pts_txt} points, pour deux entités texte')
        check('DXF : la police absente est comptée, pas plantée',
              'Standard' in _rap_dxf_txt.font_substitutions,
              f'substitutions : {_rap_dxf_txt.font_substitutions}')

        # Un TEXT ordinaire a son point d insertion **sur sa ligne de
        # base** ; le lecteur y calait le haut des lettres, et tout texte
        # tombait d une hauteur trop bas. Aligne « haut », il pend sous son
        # point de reference, qui est alors `align_point`.
        from ezdxf.enums import TextEntityAlignment as _TEA
        _doc_pos = _ez_txt.new('R2010')
        _doc_pos.header['$INSUNITS'] = 4
        _doc_pos.modelspace().add_text(
            'HH', dxfattribs={'height': 5.0, 'layer': 'base'}
        ).set_placement((10, 10))
        _doc_pos.modelspace().add_text(
            'HH', dxfattribs={'height': 5.0, 'layer': 'haut'}
        ).set_placement((10, 40), align=_TEA.TOP_LEFT)
        _dxf_pos = _bac / 'texte_position.dxf'
        _doc_pos.saveas(str(_dxf_pos))
        _calques_pos, _ = _dxi.read(str(_dxf_pos))
        _yb = [y for q in _calques_pos.get('base', []) for _, y in q]
        _yh = [y for q in _calques_pos.get('haut', []) for _, y in q]
        check('DXF : un TEXT pose sur sa ligne de base, un TEXT haut pend',
              _yb and abs(min(_yb) - 10.0) < 0.05
              and abs(max(_yb) - 15.0) < 0.3
              and _yh and abs(max(_yh) - 40.0) < 0.3
              and min(_yh) < 40.0,
              f'ligne de base : de {min(_yb):.2f} a {max(_yb):.2f} pour '
              f'10 → 15 · haut a 40 : de {min(_yh):.2f} a {max(_yh):.2f}')

        # le facteur de largeur d un TEXT, et celui de son style
        _doc_lg = _ez_txt.new('R2010')
        _doc_lg.header['$INSUNITS'] = 4
        _doc_lg.styles.add('ETROIT', font='arial.ttf').dxf.width = 0.5
        _msp_lg = _doc_lg.modelspace()
        _msp_lg.add_text('HHH', dxfattribs={'height': 5.0, 'layer': 'plein'}
                         ).set_placement((0, 0))
        _msp_lg.add_text('HHH', dxfattribs={'height': 5.0, 'layer': 'entite',
                                            'width': 0.5}
                         ).set_placement((0, 20))
        _msp_lg.add_text('HHH', dxfattribs={'height': 5.0, 'layer': 'style',
                                            'style': 'ETROIT'}
                         ).set_placement((0, 40))
        _f_lg = _bac / 'texte_largeur.dxf'
        _doc_lg.saveas(str(_f_lg))
        _cal_lg, _ = _dxi.read(str(_f_lg))

        def _larg(_c):
            _xx = [x for q in _cal_lg.get(_c, []) for x, _ in q]
            return max(_xx) - min(_xx) if _xx else 0.0
        # le style ne propose qu une valeur de creation : une entite sans
        # facteur a une largeur de 1, quel que soit son style (regle DXF)
        check('DXF : le facteur de largeur d un TEXT se respecte',
              _larg('plein') > 0
              and abs(_larg('entite') / _larg('plein') - 0.5) < 0.01
              and abs(_larg('style') / _larg('plein') - 1.0) < 0.01,
              f'largeur 1 : {_larg("plein"):.2f} mm · 0,5 sur l entite : '
              f'{_larg("entite"):.2f} · style a 0,5, entite sans facteur : '
              f'{_larg("style"):.2f}')

        # une polyligne d un seul sommet n est pas un type « non gere »
        _doc_v = _ez_txt.new('R2010')
        _doc_v.header['$INSUNITS'] = 4
        _msp_v = _doc_v.modelspace()
        _msp_v.add_polyline2d([(0, 0), (10, 0), (10, 5)])
        _msp_v.add_polyline2d([(20, 20)])
        # une SPLINE illisible, elle, est un dessin perdu : « non gere »
        _sp_v = _msp_v.add_spline(degree=3)
        _sp_v.control_points = [(0, 0), (5, 5)]
        _f_v = _bac / 'polyligne_seule.dxf'
        _doc_v.saveas(str(_f_v))
        _c_v, _r_v = _dxi.read(str(_f_v))
        check('DXF : un point isole n est pas compte comme type non gere',
              _r_v.skipped_other == {'SPLINE': 1}
              and _r_v.skipped_empty.get('POLYLINE') == 1
              and 'points isolés' in _r_v.summary(),
              f'non gérés {dict(_r_v.skipped_other)} (SPLINE illisible) · '
              f'sans longueur {dict(_r_v.skipped_empty)}')

        # --- cotations DXF : une cotation est un bloc -----------------------------
        #
        # Un DIMENSION ne porte pas sa geometrie : il renvoie a un bloc
        # anonyme qui contient traits, fleches et texte de mesure. Le plan
        # d'un client en portait 44, toutes perdues a la conversion.
        _doc_cot = _ez_txt.new('R2010')
        _doc_cot.header['$INSUNITS'] = 4
        _msp_cot = _doc_cot.modelspace()
        _msp_cot.add_line((0, 0), (50, 0))
        _msp_cot.add_linear_dim(base=(0, 10), p1=(0, 0), p2=(50, 0)).render()
        _dxf_cot = _bac / 'cotation.dxf'
        _doc_cot.saveas(str(_dxf_cot))

        _lay_cot, _rap_cot = _dxi.read(str(_dxf_cot))
        _n_cot = sum(len(v) for v in _lay_cot.values())
        check('cotation DXF : le DIMENSION est eclate, pas ecarte',
              _n_cot > 5 and _rap_cot.skipped_text == 0
              and 'DIMENSION' in _dxi.EXPLODED
              and 'DIMENSION' not in _dxi.IGNORED_TEXT,
              f'{_n_cot} polylignes pour un trait + sa cote')

        check('cotation DXF : les points de definition ne se gravent jamais',
              'POINT' in _dxi.SILENT and 'POINT' not in _dxi.GEOMETRIC,
              'AutoCAD ne les trace pas non plus')

        # un calque eteint, gele ou non trace ne doit rien produire
        _doc_vis = _ez_txt.new('R2010')
        _doc_vis.header['$INSUNITS'] = 4
        for _nom, _reglage in (('VU', None), ('ETEINT', 'off'),
                               ('GELE', 'frozen'), ('NONTRACE', 'plot')):
            _c = _doc_vis.layers.add(_nom)
            if _reglage == 'off':
                _c.off()
            elif _reglage == 'frozen':
                _c.freeze()
            elif _reglage == 'plot':
                _c.dxf.plot = 0
            _doc_vis.modelspace().add_line((0, 0), (10, 0),
                                           dxfattribs={'layer': _nom})
        _dxf_vis = _bac / 'visibilite.dxf'
        _doc_vis.saveas(str(_dxf_vis))
        _lay_vis, _rap_vis = _dxi.read(str(_dxf_vis))
        _caches = _dxi.hidden_layers(_ez_txt.readfile(str(_dxf_vis)))
        # `Defpoints` s'y trouve aussi : ezdxf le cree, non trace, et le
        # relever est correct — c'est justement le calque qui posait
        # probleme sur le plan du client
        check('calques : ce que la CAO ne dessine pas n' + chr(39) + 'est pas grave',
              set(_lay_vis) == {'VU'}
              and {'ETEINT', 'GELE', 'NONTRACE'} <= set(_caches)
              and 'VU' not in _caches
              and len(_rap_vis.notes) == 3,
              ' · '.join(f'{k} {v}' for k, v in sorted(_caches.items())))

        # AutoCAD empile une tolerance : le `^` est un code, pas un caractere
        _doc_tol = _ez_txt.new('R2010')
        _doc_tol.header['$INSUNITS'] = 4
        _msp_tol = _doc_tol.modelspace()
        _msp_tol.add_mtext('Ø6' + chr(92) + 'S+0,06^ +0,02;',
                           dxfattribs={'char_height': 3.0})
        _msp_tol.add_mtext('sans empilement',
                           dxfattribs={'char_height': 3.0})
        _dxf_tol = _bac / 'tolerance.dxf'
        _doc_tol.saveas(str(_dxf_tol))
        _lus_tol = [_dxi._mtext_plain(e) for e
                    in _ez_txt.readfile(str(_dxf_tol)).modelspace()
                    if e.dxftype() == 'MTEXT']
        check('cotation DXF : une tolerance empilee se lit',
              any('+0,06/+0,02' in t for t in _lus_tol)
              and 'sans empilement' in _lus_tol,
              ' · '.join(_lus_tol))

        # --- texte PDF : BT/Tf/Tm/Tj sont suivis -----------------------------------
        def _pdf_avec_texte() -> bytes:
            _flux = (b'1 0 0 1 0 0 cm\n10 10 m 100 10 l 100 40 l 10 40 l h S\n'
                     b'BT /F1 12 Tf 1 0 0 1 20 60 Tm (Grave-moi) Tj ET\n')
            _objets = [
                b'<< /Type /Catalog /Pages 2 0 R >>',
                b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
                b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] '
                b'/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
                b'<< /Length ' + str(len(_flux)).encode() + b' >>stream\n'
                + _flux + b'endstream',
                b'<< /Type /Font /Subtype /TrueType /BaseFont /Arial-Bold >>',
            ]
            _out = bytearray(b'%PDF-1.4\n')
            _places = []
            for _i, _corps in enumerate(_objets, 1):
                _places.append(len(_out))
                _out += str(_i).encode() + b' 0 obj\n' + _corps + b'\nendobj\n'
            _debut = len(_out)
            _out += b'xref\n0 ' + str(len(_objets) + 1).encode()
            _out += b'\n0000000000 65535 f \n'
            for _place in _places:
                _out += f'{_place:010d} 00000 n \n'.encode()
            _out += (b'trailer\n<< /Size ' + str(len(_objets) + 1).encode()
                     + b' /Root 1 0 R >>\nstartxref\n'
                     + str(_debut).encode() + b'\n%%EOF\n')
            return bytes(_out)

        _pdf_txt = _bac / 'texte.pdf'
        _pdf_txt.write_bytes(_pdf_avec_texte())
        _polys_pdf_txt, _rap_pdf_txt = _vec.read(str(_pdf_txt))
        check('PDF : BT/Tf/Tm/Tj sont suivis, le texte devient des contours',
              len(_polys_pdf_txt) > 10,
              f'{len(_polys_pdf_txt)} tracés — 1 rectangle + un mot')

        # Tf est un cadratin, en points : 12 pt d Arial donnent des
        # capitales de 12 x 0,716 pt, soit 3,03 mm — et non 4,23
        from engrave import fontmap as _fm_em
        _police_pdf, _ = _fm_em.resolve('Arial Bold')
        _cap_pdf = 12 * _tv_em.em_ratio(_police_pdf) * 25.4 / 72
        _mots = [q for q in _polys_pdf_txt
                 if min(y for _, y in q) > 15]      # le rectangle est dessous
        _ym = [y for q in _mots for _, y in q]
        _h_pdf = max(_ym) - min(_ym) if _ym else 0.0
        check('PDF : un texte Tf 12 a ses capitales a 3 mm, pas 4,2',
              _mots and abs(_h_pdf - _cap_pdf) < 0.06 * _cap_pdf,
              f'« Grave-moi » : {_h_pdf:.2f} mm de haut, capitale attendue '
              f'{_cap_pdf:.2f} mm (le G deborde un peu, comme tout rond)')

        # --- texte PDF : le point d ecriture avance, l espacement compte ---
        #
        # Deux `Tj` d un meme bloc s ecrivaient l un sur l autre ; les
        # decalages d un `TJ` (crenage, justification), `Tc`, `Tw` et `Tz`
        # etaient jetes, et le texte importe se resserrait.
        def _pdf_flux(_flux: bytes) -> bytes:
            _objs = [
                b'<< /Type /Catalog /Pages 2 0 R >>',
                b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
                b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] '
                b'/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
                b'<< /Length ' + str(len(_flux)).encode() + b' >>stream\n'
                + _flux + b'endstream',
                b'<< /Type /Font /Subtype /TrueType /BaseFont /Arial >>',
            ]
            _o = bytearray(b'%PDF-1.4\n')
            _pl = []
            for _k, _c in enumerate(_objs, 1):
                _pl.append(len(_o))
                _o += str(_k).encode() + b' 0 obj\n' + _c + b'\nendobj\n'
            _deb = len(_o)
            _o += (b'xref\n0 ' + str(len(_objs) + 1).encode()
                   + b'\n0000000000 65535 f \n')
            for _x in _pl:
                _o += f'{_x:010d} 00000 n \n'.encode()
            _o += (b'trailer\n<< /Size ' + str(len(_objs) + 1).encode()
                   + b' /Root 1 0 R >>\nstartxref\n' + str(_deb).encode()
                   + b'\n%%EOF\n')
            return bytes(_o)

        def _emprise_pdf(_flux: bytes):
            _f = _bac / 'espacement.pdf'
            _f.write_bytes(_pdf_flux(_flux))
            _pp, _ = _vec.read(str(_f))
            _xx = [x for q in _pp for x, _ in q]
            return (min(_xx), max(_xx)) if _xx else (0.0, 0.0)

        _pt = 25.4 / 72
        _un = _emprise_pdf(b'BT /F1 20 Tf 1 0 0 1 10 50 Tm (HH) Tj ET\n')
        _deux = _emprise_pdf(
            b'BT /F1 20 Tf 1 0 0 1 10 50 Tm (H) Tj (H) Tj ET\n')
        _tj0 = _emprise_pdf(b'BT /F1 20 Tf 1 0 0 1 10 50 Tm [(H)(H)] TJ ET\n')
        _tj1 = _emprise_pdf(
            b'BT /F1 20 Tf 1 0 0 1 10 50 Tm [(H) -1000 (H)] TJ ET\n')
        check('PDF : deux Tj se suivent, un decalage TJ deplace la suite',
              abs(_un[1] - _deux[1]) < 1e-6
              and abs((_tj1[1] - _tj0[1]) - 20 * _pt) < 1e-3,
              f'(H)(H) = (HH) · -1000 dans TJ : '
              f'{_tj1[1] - _tj0[1]:.3f} mm pour un cadratin de '
              f'{20 * _pt:.3f}')
        _base = _emprise_pdf(b'BT /F1 20 Tf 1 0 0 1 10 50 Tm (HHH) Tj ET\n')
        _tc = _emprise_pdf(
            b'BT /F1 20 Tf 5 Tc 1 0 0 1 10 50 Tm (HHH) Tj ET\n')
        _tz = _emprise_pdf(
            b'BT /F1 20 Tf 50 Tz 1 0 0 1 10 50 Tm (HHH) Tj ET\n')
        _lb, _lz = _base[1] - _base[0], _tz[1] - _tz[0]
        check('PDF : Tc ecarte les lettres, Tz les comprime',
              abs((_tc[1] - _base[1]) - 10 * _pt) < 1e-3
              and abs(_lz / _lb - 0.5) < 1e-3,
              f'Tc 5 : +{_tc[1] - _base[1]:.3f} mm sur deux espaces · '
              f'Tz 50 : largeur x{_lz / _lb:.3f}')
        _qq = _emprise_pdf(
            b'q 5 Tc 50 Tz Q BT /F1 20 Tf 1 0 0 1 10 50 Tm (HHH) Tj ET\n')
        check('PDF : Q rend l espacement d avant le bloc q',
              abs(_qq[1] - _base[1]) < 1e-6 and abs(_qq[0] - _base[0]) < 1e-6,
              f'apres q 5 Tc 50 Tz Q : {_qq[1] - _qq[0]:.3f} mm, comme sans')

        # --- fontmap : résolution et substitution mémorisée -----------------------
        from engrave import fontmap as _fm
        _chemin_arial, _exact_arial = _fm.resolve('Arial')
        check('fontmap : une police installée se résout sans substitution',
              _exact_arial and pathlib.Path(_chemin_arial).is_file(),
              _chemin_arial)

        _repondu = []
        def _repond_bidon(nom, candidats):
            _repondu.append(nom)
            return candidats[0][1] if candidats else None
        _chemin_bidon, _exact_bidon = _fm.resolve('PoliceQuiNexistePas',
                                                  ask=_repond_bidon)
        check('fontmap : une police absente déclenche « ask », une seule fois',
              _exact_bidon and _repondu == ['PoliceQuiNexistePas'],
              f'demandé pour {_repondu}')
        _chemin_memoire, _exact_memoire = _fm.resolve('PoliceQuiNexistePas',
                                                      ask=_repond_bidon)
        check('fontmap : le choix reste mémorisé, plus jamais redemandé',
              _exact_memoire and _chemin_memoire == _chemin_bidon
              and _repondu == ['PoliceQuiNexistePas'],
              'un seul dialogue par nom de police, pour toujours')
        _fm.forget('PoliceQuiNexistePas')

        # --- export PDF -------------------------------------------------------
        _pdf_out = _bac / 'ecrit.pdf'
        _n_pdf = _vex.export(_doc_ex, _pdf_out, kind='pdf')
        _pdf_relu, _ = _vec.read(str(_pdf_out))
        check('export PDF : écrit et relu à la même géométrie',
              _n_pdf > 0 and len(_pdf_relu) == _n_pdf
              and 'pdf' in {k for k, _, _ in _vex.FORMATS},
              f'{_n_pdf} tracés écrits, {len(_pdf_relu)} relus')

        # --- montage a trois DataMatrix ------------------------------------------
        #
        # Monte sur un `Document` nu et un formulaire seul : construire une
        # seconde `MainWindow` pour cela couterait quinze secondes a chaque
        # autotest, pour ne rien verifier de plus.
        from engrave import montage as _mtg
        from engrave.toolpath import shape_extent as _extent
        from engrave.model import Document as _Doc

        _doc_mtg = _Doc()
        _formes_mtg = _mtg.build(PRESET_RECIPES[0])
        for _f in _formes_mtg:
            _doc_mtg.add(_f)
        _paires = _mtg.pairs(_formes_mtg)
        check('montage : six formes, trois paires code + texte',
              len(_formes_mtg) == 6 and len(_paires) == 3
              and _mtg.is_montage(_formes_mtg),
              f'{len(_formes_mtg)} formes, {len(_paires)} paires')

        # le defaut d'origine : les trois textes suivaient le meme code, si
        # bien que changer une reference en reecrivait trois, ou aucune
        _suivis = {t.follows for _, t in _paires}
        check('montage : chaque texte suit SON code, pas celui du milieu',
              len(_suivis) == 3 and _suivis == {c.id for c, _ in _paires},
              'trois liens distincts — une piece ne peut plus partir avec un '
              'code et un numero lisible qui se contredisent')

        # les cotes sont celles du montage physique : elles se reproduisent
        _y_mtg = sorted((c.y for c, _ in _paires), reverse=True)
        from engrave import gabarits as _gab
        _g_def = _gab.charger()[0]
        _postes_def = _mtg.postes_de(_g_def)
        _y_ref = sorted((q.y_mm for q in _postes_def), reverse=True)
        _boites = [_extent(c) for c, _ in _paires]
        _largeurs = {round(b[2] - b[0], 3) for b in _boites}
        _hauteurs = {round(b[3] - b[1], 3) for b in _boites}
        check('montage : cotes et ordonnees du montage machine',
              _y_mtg == _y_ref and _largeurs == {16.0} and _hauteurs == {8.0},
              f'y = {_y_mtg} · symboles 16,000 x 8,000 mm')

        _form_mtg = _mtg.MontageForm()
        _charge = _form_mtg.set_montage(_formes_mtg, _doc_mtg)
        for _cle, _val in (('haut', 'A111'), ('milieu', 'B222'), ('bas', 'C333')):
            _form_mtg._champs[_cle].setText(_val)
            _form_mtg._applique(_cle)
        _vus = [(c.data, t.text) for c, t in _mtg.pairs(_doc_mtg.shapes)]
        check('montage : trois references independantes, texte suivi',
              _charge and _vus == [('A111', 'A111'), ('B222', 'B222'),
                                   ('C333', 'C333')],
              ' · '.join(d for d, _ in _vus))

        # le nom doit suivre : un nom perime est un piege a l'atelier — dans
        # le fichier d'origine, six formes s'appelaient encore « B000179 »
        # pour une donnee valant B000181
        _noms = [c.display_name() for c, _ in _mtg.pairs(_doc_mtg.shapes)]
        check('montage : le nom porte la reference a jour et son poste',
              all(v in n for v, n in zip(('A111', 'B222', 'C333'), _noms))
              and all(q.libelle in n for q, n in zip(_postes_def, _noms)),
              _noms[0])

        _form_mtg._applique_tous()
        _tous = {c.data for c, _ in _mtg.pairs(_doc_mtg.shapes)}
        _tous_txt = {t.text for _, t in _mtg.pairs(_doc_mtg.shapes)}
        check('montage : « appliquer a tous » reprend le HAUT sur les trois',
              _tous == {'A111'} and _tous_txt == {'A111'},
              'le geste du lot unique, sans imposer un mode aux trois champs')

        # une seule implementation de la regle `follows`, partagee
        from engrave import codeplate as _cp
        check('montage : la regle du texte lie est celle de toute l' + chr(39)
              + 'application',
              hasattr(_cp, 'propagate_data')
              and 'propagate_data' in pathlib.Path(
                  'src/engrave/app.py').read_text(encoding='utf-8'),
              'deux versions d' + chr(39) + 'une regle finissent par diverger')

        check('montage : offert a la barre, avec son icone',
              'montage3' in icons.DRAWINGS
              and any('ontage' in (a.text() or '')
                      for a in window.findChildren(_QAction)),
              'trois DataMatrix empiles')

        # --- plus aucun filet muet -----------------------------------------
        #
        # Un `except Exception` large est souvent le bon choix : ecrire une
        # vignette ne doit jamais empecher d ouvrir un dessin. Ce qui ne va
        # pas, c est le silence — on cherche une heure pourquoi rien ne
        # s affiche, alors que la reponse etait la, attrapee et jetee.
        from engrave import avale as _av
        import re as _re_av

        _muets = []
        for _p in sorted(pathlib.Path('src/engrave').glob('*.py')):
            if _p.name == 'avale.py':
                continue          # son propre filet protege le journal
            _ls = _p.read_text(encoding='utf-8').splitlines()
            for _i, _l in enumerate(_ls):
                if _re_av.match(r'\s*except Exception:', _l):
                    _suite = [x for x in _ls[_i + 1:_i + 3] if x.strip()]
                    if _suite and _suite[0].strip() in ('pass', 'continue'):
                        _muets.append(f'{_p.name}:{_i + 1}')
        check('filets : aucun ne se tait plus',
              not _muets,
              ', '.join(_muets) if _muets
              else 'ce qui est rattrape est retenu, et se lit dans « ? »')

        _av.clear()
        _av.avale('essai', OSError('disque plein'))
        _av.avale('essai', ValueError('autre'))
        _av.avale('police', KeyError('nom'))
        check('filets : le journal retient et resume',
              _av.count() == 3 and 'essai (2)' in _av.summary()
              and 'OSError' in _av.report_text(),
              _av.summary())

        # un journal qui plante en journalisant serait le comble
        class _Vilain(Exception):
            def __str__(self):
                raise RuntimeError('meme mon message echoue')

        _avant_av = _av.count()
        _av.avale('essai', _Vilain())
        check('filets : journaliser ne peut pas faire tomber le travail',
              _av.count() == _avant_av,
              'on prefere perdre la ligne que l operation qu elle accompagne')

        check('filets : le journal est borne',
              _av.MAX <= 500 and _av.MAX >= 50,
              f'{_av.MAX} entrees — comprendre ce qui vient de se passer, '
              f'pas tenir l historique d une semaine')
        _av.clear()

        # --- le nom d une forme ne peut pas mentir --------------------------
        #
        # `Datamatrix.taudrive` affichait « B000179 » pour un code qui
        # valait B000181 : le nom avait ete fige a la creation, et plus
        # rien ne le remettait d accord. C est en lisant la liste des
        # formes qu on croit avoir pose la bonne piece.
        _d_nom = _Doc()
        _f_nom = _mtg.build(PRESET_RECIPES[0])
        for _s in _f_nom:
            _d_nom.add(_s)
        _code0 = _f_nom[0]
        _avant_nom = _code0.display_name()
        _code0.data = 'ZZ777'
        _apres_nom = _code0.display_name()
        check('nom : il suit la donnee tant que personne ne l' + chr(39) + 'a tape',
              'B000181' in _avant_nom and 'ZZ777' in _apres_nom
              and not _code0.renamed() and _code0.name == '',
              f'{_avant_nom} -> {_apres_nom}')

        check('nom : le poste est un role stable, pas un nom fige',
              _code0.role == 'HAUT' and 'HAUT' in _apres_nom,
              'le DataMatrix du haut reste celui du haut, quelle que soit '
              'sa reference')

        _code0.name = 'A la main'
        _fige = _code0.display_name()
        _code0.data = 'AUTRE'
        check('nom : un nom tape a la main tient, et se voit',
              _fige == 'A la main' and _code0.display_name() == 'A la main'
              and _code0.renamed(),
              'la liste le marque d' + chr(39) + 'un crayon')

        _code0.name = ''
        check('nom : vider le champ rend le nom au calcul',
              'AUTRE' in _code0.display_name() and not _code0.renamed(),
              'defaire un renommage doit rester simple')

        # le role traverse le disque : sans cela, rouvrir un montage
        # perdrait HAUT/MILIEU/BAS
        from engrave import serialize as _ser_nom
        _relu_nom = _ser_nom.loads(_ser_nom.dumps(_d_nom))
        check('nom : le role survit a l' + chr(39) + 'enregistrement',
              [x.role for x in _relu_nom.shapes[:2]] == ['HAUT', 'HAUT'],
              'rouvrir un montage garde ses postes')

        # plus personne ne doit ecrire un nom **derive** dans `name`
        import re as _re_nom
        _src_app = pathlib.Path('src/engrave/app.py').read_text(
            encoding='utf-8')
        _src_mtg = pathlib.Path('src/engrave/montage.py').read_text(
            encoding='utf-8')
        check('nom : le montage pose un role, jamais un nom',
              '.name = ' not in _src_mtg and 'role = poste.libelle' in _src_mtg,
              'un nom calcule range dans `name` est un nom qui mentira')

        # --- un dessin lourd ne doit pas figer la souris ---------------------
        #
        # `QGraphicsPathItem.shape()` rend le contour epaissi du trace, et
        # Qt l appelle a chaque mouvement de souris. Sur un plan de production
        # (98 584 elements) ce calcul prenait 34 ms : bouger la souris
        # au-dessus du dessin plafonnait a 29 images par seconde.
        import time as _t_perf
        from engrave.app import ShapeItem as _SI
        from engrave.model import Code as _CodeS, Path as _PathShape

        _gros = _PathShape(polylines=[[(x * 0.01, (x % 7) * 0.01)
                                 for x in range(400)]
                                for _ in range(60)],
                     recipe=PRESET_RECIPES[0], name='gros')
        _item = _SI(_gros, lambda: None)
        _elements = _item.path().elementCount()
        _t0 = _t_perf.perf_counter()
        for _ in range(5):
            _item.shape()
        _cout = (_t_perf.perf_counter() - _t0) / 5

        check('dessin lourd : la zone de clic est bornee et retenue',
              _elements > _SI.HIT_TEST_MAX and _cout < 0.002,
              f'{_elements} elements · {_cout * 1000:.2f} ms par appel '
              f'(seuil {_SI.HIT_TEST_MAX})')

        _petit = _PathShape(polylines=[[(0, 0), (5, 0), (5, 5), (0, 0)]],
                      recipe=PRESET_RECIPES[0], name='petit')
        _item_p = _SI(_petit, lambda: None)
        check('dessin lourd : un petit trace garde son contour exact',
              _item_p.path().elementCount() <= _SI.HIT_TEST_MAX
              and _item_p.shape().elementCount()
              > _item_p.path().elementCount(),
              'cliquer dans le creux d' + chr(39) + 'un « O » ne doit pas prendre la lettre')

        # --- barre au-dela d une seconde, annulable --------------------------
        from engrave import longtask as _lt

        _r = _lt.Reporter(None, 'essai', seuil_s=10.0)
        check('avancement : rien ne parait sous le seuil',
              _r(0.5) is True and not _r.a_paru(),
              'une barre qui clignote pour un dixieme de seconde gene plus '
              'qu' + chr(39) + 'elle n' + chr(39) + 'aide')
        _r.fermer()

        check('avancement : le seuil porte sur le temps, pas sur la taille',
              _lt.SEUIL_S == 1.0 and _lt.RAFRAICHIR_S < _lt.SEUIL_S,
              'un meme dessin est rapide sur un poste et lent sur un autre')

        # lXavancement traverse jusquXau lecteur, et lXabandon sort en
        # `Cancelled` — jamais en `DxfError` : renoncer nXest pas echouer
        _rapports = []
        _dxi.any_to_shapes(str(_src_svg),
                           progress=lambda f, t='': _rapports.append(f) or True)

        # renoncer au tout debut : c est la garde exterieure
        _dehors = False
        try:
            _dxi.any_to_shapes(str(_src_svg), progress=lambda f, t='': False)
        except _dxi.Cancelled:
            _dehors = True
        except _dxi.DxfError:
            _dehors = False

        # renoncer en cours de lecture : c est le lecteur lui-meme, qui
        # consulte le signal toutes les 64 entites
        _n_dxf = [0]

        def _refuse_dxf(f, t=''):
            _n_dxf[0] += 1
            return _n_dxf[0] < 3

        _dedans = False
        try:
            _dxi.read(str(_dxf_cot), progress=_refuse_dxf)
        except _dxi.Cancelled:
            _dedans = True
        except _dxi.DxfError:
            _dedans = False

        check('avancement : abandonner sort en Cancelled, pas en erreur',
              bool(_rapports) and _dehors and _dedans,
              f'{len(_rapports)} rapports · abandon au seuil et en cours '
              f'de lecture')

        # --- les nappes tournees se dessinent toutes ------------------------
        #
        # `pass_index` faisait deja tourner l angle a la gravure, mais
        # l affichage appelait toujours la passe 0 : un remplissage a
        # trois nappes de 60 deg se montrait comme une seule direction, et
        # les process de texture etaient indiscernables a l ecran.
        import math as _m_nap
        import collections as _c_nap
        import dataclasses as _dc_nap
        from engrave import toolpath as _tp_nap

        _base_nap = _dc_nap.replace(PRESET_RECIPES[0], hatch_mm=0.8,
                                    hatch_angle_deg=0.0, hatch_inset_mm=0.0,
                                    hatch_cross=False, wobble='none')

        def _directions(recette):
            _f = Rect(width=20, height=20, recipe=recette)
            _c = _c_nap.Counter()
            for _poly in _tp_nap.local_polylines(_f):
                for (_x1, _y1), (_x2, _y2) in zip(_poly, _poly[1:]):
                    if _m_nap.hypot(_x2 - _x1, _y2 - _y1) < 0.5:
                        continue
                    _c[round(_m_nap.degrees(
                        _m_nap.atan2(_y2 - _y1, _x2 - _x1)) % 180)] += 1
            return {_a for _a, _n in _c.items() if _n > 3}

        _un = _directions(_dc_nap.replace(_base_nap, passes=1,
                                          hatch_angle_step_deg=0))
        _deux = _directions(_dc_nap.replace(_base_nap, passes=2,
                                            hatch_angle_step_deg=45))
        _trois = _directions(_dc_nap.replace(_base_nap, passes=3,
                                             hatch_angle_step_deg=60))
        check('nappes : chaque passe tournee est dessinee a son angle',
              _un == {0} and _deux == {0, 45} and _trois == {0, 60, 120},
              f'1 passe {sorted(_un)} · 2 a 45 {sorted(_deux)} · '
              f'3 a 60 {sorted(_trois)}')

        # 180 deg retrace les memes droites : compter les angles
        # **distincts modulo 180**, et non les passes
        check('nappes : deux passes a 180 deg ne font qu' + chr(39) + 'une direction',
              len(_tp_nap.pass_angles(
                  _dc_nap.replace(_base_nap, passes=2,
                                  hatch_angle_step_deg=180))) == 1,
              'sinon on peindrait deux fois le meme trait')

        check('nappes : sans rotation, rien ne change',
              len(_tp_nap.pass_angles(
                  _dc_nap.replace(_base_nap, passes=5,
                                  hatch_angle_step_deg=0))) == 1
              and len(_tp_nap.pass_angles(
                  _dc_nap.replace(_base_nap, passes=3, hatch_mm=0.0,
                                  hatch_angle_step_deg=45))) == 1,
              'cinq passes au meme angle, ou pas de remplissage du tout')

        # cent nappes couvriraient la forme d un aplat noir
        _bcp = _tp_nap.pass_angles(_dc_nap.replace(
            _base_nap, passes=40, hatch_angle_step_deg=15))
        _f_bcp = Rect(width=20, height=20,
                      recipe=_dc_nap.replace(_base_nap, passes=40,
                                             hatch_angle_step_deg=15))
        _dessine = len(_directions(_f_bcp.recipe))
        check('nappes : l' + chr(39) + 'affichage se borne, la gravure non',
              len(_bcp) == 12 and _dessine <= _tp_nap.NAPPES_MONTREES,
              f'{len(_bcp)} angles graves · {_dessine} montres '
              f'(plafond {_tp_nap.NAPPES_MONTREES})')

        # le croisement agit dans **une** passe : deux nappes a 90 deg
        check('nappes : le croise reste un croise, pas une passe de plus',
              _directions(_dc_nap.replace(_base_nap, passes=1,
                                          hatch_cross=True)) == {0, 90},
              'deux nappes perpendiculaires au meme Z')

        # --- l alignement ancre le texte -----------------------------------
        #
        # Un bloc etait toujours centre sur son origine, quel que soit
        # l alignement : « gauche » ne changeait rien a un texte d une
        # ligne, et rallonger un texte le faisait pousser des deux cotes.
        from engrave import textvec as _tv_a, serialize as _ser_a
        from engrave.geometry import bounds as _b_a
        _ga = _b_a(_tv_a.layout('ABC', 5, '', 'left', 'middle', 1.4))
        _ca = _b_a(_tv_a.layout('ABC', 5, '', 'center', 'middle', 1.4))
        _da = _b_a(_tv_a.layout('ABC', 5, '', 'right', 'middle', 1.4))
        _long = _b_a(_tv_a.layout('ABCDEF', 5, '', 'left', 'middle', 1.4))
        check('texte : l alignement ancre le bloc sur son origine',
              abs(_ga[0]) < 0.3 and abs(_da[2]) < 0.3
              and abs(_ca[0] + _ca[2]) < 0.3
              and abs(_long[0] - _ga[0]) < 1e-6 and _long[2] > _ga[2],
              f'gauche x[{_ga[0]:.2f},{_ga[2]:.2f}] centre '
              f'[{_ca[0]:.2f},{_ca[2]:.2f}] droite [{_da[0]:.2f},{_da[2]:.2f}]'
              f' · rallonge a gauche : bord gauche fixe')
        # un document ecrit avant l ancrage ne bouge pas a la relecture
        _t_vieux = Text(text='ABC', size_mm=5, align='left', x=10.0, y=3.0,
                        rotation_deg=90.0, recipe=PRESET_RECIPES[0])
        _d_vieux = _ser_a.shape_to_dict(_t_vieux)
        _d_vieux.pop('anchored')
        _relu = _ser_a.shape_from_dict(_d_vieux)
        _w_vieux = _tv_a.advance_width('ABC', 5)
        _neuf = _ser_a.shape_from_dict(_ser_a.shape_to_dict(_t_vieux))
        check('texte : un document d avant l ancrage garde sa place',
              _relu.anchored and abs(_relu.x - 10.0) < 1e-9
              and abs(_relu.y - (3.0 - _w_vieux / 2)) < 1e-6
              and abs(_neuf.x - 10.0) < 1e-9 and abs(_neuf.y - 3.0) < 1e-9,
              f'ancien : origine decalee de {_w_vieux / 2:.3f} le long du '
              f'texte tourne · neuf : inchange')

        # --- polices : le plus grand nombre possible ----------------------
        #
        # Trois manques mesures sur ce poste : 23 polices rangees dans des
        # collections .ttc n etaient pas listees (seule la premiere face
        # l etait), 13 polices symbole tombaient sur une exception au
        # premier caractere, et une police installee pendant que TauDrive
        # tournait n apparaissait jamais.
        import tempfile as _tf_pol
        from engrave import textvec as _tv_pol, session as _ses_pol
        from engrave import preflight as _pf_pol
        _polices = _tv_pol.available_fonts(fresh=True)
        _rangs = [(_n, _p) for _n, _p in _polices
                  if _tv_pol.SPEC_SEP in _p]
        _premiere_nue = all(
            _tv_pol.SPEC_SEP not in _p for _n, _p in _polices
            if _tv_pol.split_spec(_p)[1] == 0)
        _ok_rangs = all(_tv_pol.outline('Ag', 5.0, _p) is not None
                        for _, _p in _rangs[:6])
        check('polices : chaque face d une collection est listee et se rend',
              _premiere_nue and _ok_rangs
              and _tv_pol.split_spec(_tv_pol.spec_of('x.ttc', 2))
              == ('x.ttc', 2)
              and _tv_pol.spec_of('x.ttc', 0) == 'x.ttc',
              f'{len(_rangs)} face(s) au-dela de la premiere sur ce poste '
              f'· la premiere garde le chemin nu, comme avant')

        _echecs_pol = []
        for _n, _p in _polices:
            try:
                _tv_pol.outline('Ag1', 5.0, _p)
            except Exception as exc:                    # noqa: BLE001
                _echecs_pol.append(f'{_n} ({type(exc).__name__})')
        _symb = next((_p for _n, _p in _polices
                      if _n in ('Wingdings', 'Symbol')), None)
        _contours_symb = (len(_tv_pol.outline('AB', 10.0, _symb))
                          if _symb else -1)
        check('polices : toutes se rendent, polices symbole comprises',
              not _echecs_pol and (_symb is None or _contours_symb > 0),
              f'{len(_polices)} polices, 0 echec'
              + (f' · Wingdings/Symbol : {_contours_symb} contours'
                 if _symb else ' · pas de police symbole sur ce poste')
              if not _echecs_pol else ', '.join(_echecs_pol[:4]))

        # une police non installee se designe par son fichier — fabriquee
        # ici pour ne dependre d aucune police du poste
        from fontTools.fontBuilder import FontBuilder as _FB
        from fontTools.pens.ttGlyphPen import TTGlyphPen as _TGP
        _dir_pol = pathlib.Path(_tf_pol.mkdtemp(prefix='taudrive-pol-'))
        _f_pol = _dir_pol / 'TauDriveEssai.ttf'
        _fb = _FB(1000, isTTF=True)
        _fb.setupGlyphOrder(['.notdef', 'A'])
        _fb.setupCharacterMap({0x41: 'A'})
        _pen = _TGP(None)
        _pen.moveTo((100, 0))
        _pen.lineTo((100, 700))
        _pen.lineTo((600, 700))
        _pen.lineTo((600, 0))
        _pen.closePath()
        _fb.setupGlyf({'.notdef': _TGP(None).glyph(), 'A': _pen.glyph()})
        _fb.setupHorizontalMetrics({'.notdef': (500, 0), 'A': (700, 100)})
        _fb.setupHorizontalHeader(ascent=800, descent=-200)
        _fb.setupNameTable({'familyName': 'TauDrive Essai',
                            'styleName': 'Regular'})
        _fb.setupOS2(sCapHeight=700, sTypoAscender=800,
                     sTypoDescender=-200, usWinAscent=800,
                     usWinDescent=200)
        _fb.setupPost()
        _fb.save(str(_f_pol))
        # la liste des fichiers designes vit dans les reglages du poste :
        # elle est sauvee et rendue telle quelle
        _reg_pol = _ses_pol.settings()
        _avant_pol = _reg_pol.value('polices/fichiers')
        try:
            _absente_avant = not any(_n == 'TauDrive Essai'
                                     for _n, _ in _tv_pol.available_fonts(
                                         fresh=True))
            _spec_pol = _tv_pol.add_font_file(_f_pol)
            _presente = any(_n == 'TauDrive Essai' and _p == _spec_pol
                            for _n, _p in _tv_pol.available_fonts())
            _a_pol = _tv_pol.outline('A', 7.0, _spec_pol)
            _xs = [x for c in _a_pol for x, _ in c]
            _ys = [y for c in _a_pol for _, y in c]
            _refus_pol = ''
            try:
                _tv_pol.add_font_file(pathlib.Path(__file__))
            except _tv_pol.FontNotFound as exc:
                _refus_pol = str(exc)
            check('polices : un fichier non installe se designe et se grave',
                  _absente_avant and _presente
                  and abs((max(_xs) - min(_xs)) - 5.0) < 1e-6
                  and abs((max(_ys) - min(_ys)) - 7.0) < 1e-6
                  and 'extension' in _refus_pol,
                  f'« TauDrive Essai » absente puis listee · A de 7 mm '
                  f'grave {max(_xs) - min(_xs):.2f} × '
                  f'{max(_ys) - min(_ys):.2f} mm · un .py refuse')
        finally:
            if _avant_pol is None:
                _reg_pol.remove('polices/fichiers')
            else:
                _reg_pol.setValue('polices/fichiers', _avant_pol)
            _tv_pol.refresh_fonts()

        # une police posee pendant que TauDrive tourne apparait sans
        # relancer : l empreinte des dossiers est surveillee
        _sig_avant = _tv_pol._signature()
        check('polices : la liste se refait quand les dossiers changent',
              _tv_pol.RECHECK_S <= 5.0 and isinstance(_sig_avant, tuple)
              and _tv_pol.available_fonts() is _tv_pol.available_fonts(),
              f'empreinte verifiee toutes les {_tv_pol.RECHECK_S:g} s · '
              f'liste retenue entre deux')

        # --- la hauteur de capitale, quand la police ne la declare pas ---
        #
        # 284 polices sur 489 n ont pas `sCapHeight` ; TauDrive prenait
        # alors une hauteur qui compte les accents, et un texte demande a
        # 10 mm sortait a 7,14 mm en Century Gothic. La police d essai
        # fabriquee plus haut ne declare pas sa capitale : son A fait
        # 700 unites, la hauteur au-dessus de la ligne de base 800.
        _fb2 = _FB(1000, isTTF=True)
        _fb2.setupGlyphOrder(['.notdef', 'H'])
        _fb2.setupCharacterMap({0x48: 'H'})
        _pen2 = _TGP(None)
        _pen2.moveTo((100, 0))
        _pen2.lineTo((100, 700))
        _pen2.lineTo((600, 700))
        _pen2.lineTo((600, 0))
        _pen2.closePath()
        _fb2.setupGlyf({'.notdef': _TGP(None).glyph(), 'H': _pen2.glyph()})
        _fb2.setupHorizontalMetrics({'.notdef': (500, 0), 'H': (700, 100)})
        _fb2.setupHorizontalHeader(ascent=800, descent=-200)
        _fb2.setupNameTable({'familyName': 'TauDrive Sans Capitale',
                             'styleName': 'Regular'})
        # table OS/2 de version 1 : pas de champ `sCapHeight`
        _fb2.setupOS2(version=1, sTypoAscender=800, sTypoDescender=-200,
                      usWinAscent=800, usWinDescent=200)
        _fb2.setupPost()
        _f_sc = _dir_pol / 'SansCapitale.ttf'
        _fb2.save(str(_f_sc))

        def _haut(contours):
            _yy = [y for c in contours for _, y in c]
            return max(_yy) - min(_yy)

        _h_juste = _haut(_tv_pol.outline('H', 10.0, str(_f_sc)))
        _h_vieux = _haut(_tv_pol.outline('H', 10.0, str(_f_sc),
                                         measured=False))
        check('polices : sans capitale declaree, elle est mesuree sur le H',
              abs(_h_juste - 10.0) < 1e-6 and abs(_h_vieux - 8.75) < 1e-6,
              f'H demande a 10 mm : {_h_juste:.3f} mm '
              f'(au lieu de {_h_vieux:.3f} par la hauteur de ligne)')

        # un document ecrit avant la correction garde sa taille exacte ;
        # un texte neuf a la taille demandee
        _t_neuf = Text(text='HHH', size_mm=6.0, font_path=str(_f_sc),
                       recipe=PRESET_RECIPES[0])
        _d_neuf = serialize.shape_to_dict(_t_neuf)
        _d_ancien = dict(_d_neuf)
        _d_ancien.pop('cap_measured')
        _relu_a = serialize.shape_from_dict(_d_ancien)
        _relu_n = serialize.shape_from_dict(_d_neuf)
        _h_a = _haut(shape_contours(_relu_a))
        _h_n = _haut(shape_contours(_relu_n))
        check('polices : un document ancien se grave comme avant, un neuf '
              'juste',
              not _relu_a.cap_measured and _relu_n.cap_measured
              and abs(_h_a - 6.0 * 700 / 800) < 1e-6
              and abs(_h_n - 6.0) < 1e-6,
              f'ancien : {_h_a:.3f} mm, inchange · neuf : {_h_n:.3f} mm '
              f'pour 6 demandes')

        # une police absente du poste ne fait plus tomber le document
        _t_abs = Text(text='ABC', size_mm=8, recipe=PRESET_RECIPES[0],
                      font_path=str(_dir_pol / 'Inexistante.ttf'))
        _contours_abs = shape_contours(_t_abs)
        _rap_abs = _pf_pol.inspect(Document(name='x', shapes=[_t_abs]))
        check('polices : une police absente se remplace, et c est dit',
              len(_contours_abs) > 0
              and str(_dir_pol / 'Inexistante.ttf')
              in _tv_pol.missing_fonts()
              and any('absente' in _t for _, _t in _rap_abs.notes),
              f'{len(_contours_abs)} contours avec la police par defaut · '
              f'signalee a la verification avant export')
        shutil.rmtree(_dir_pol, ignore_errors=True)

        # --- morceaux : graver plus grand que le champ --------------------
        from engrave import morceaux as _mx, iso as _iso_mx
        import tempfile as _tf_mx, pathlib as _pl_mx
        from engrave.toolpath import total_length_mm as _len_mx
        _r_mx = _dc_nap.replace(_base_nap, hatch_mm=0.5, hatch_angle_deg=30.0)
        _doc_mx = Document(name='grand', shapes=[
            Rect(width=200, height=150, recipe=_r_mx),
            Text(text='ABC', size_mm=20, x=60, y=-40, recipe=_r_mx)])
        _plan_mx = _mx.plan(_doc_mx.bounds(), 110, 110, 2.0)
        _passes_mx = build_passes(_doc_mx)
        _parts_mx = [_mx.passes_du_morceau(_passes_mx, m) for m in _plan_mx]
        _L = _len_mx(_passes_mx)
        _Lm = sum(_len_mx(p) for p in _parts_mx)
        _dedans = all(
            max(abs(x) for pp in part for poly in pp.polylines for x, _ in poly)
            <= m.largeur / 2 + 1e-6
            and max(abs(y) for pp in part for poly in pp.polylines
                    for _, y in poly) <= m.hauteur / 2 + 1e-6
            for m, part in zip(_plan_mx, _parts_mx))
        check('morceaux : 200x150 en 2x2, rien de perdu, rien en double',
              _mx.dimensions(_plan_mx) == (2, 2) and abs(_L - _Lm) < 1e-6
              and _dedans and _mx.necessaire(_doc_mx),
              f'{_L:.1f} mm avant · {_Lm:.1f} mm apres · tout recentre')
        _front = _plan_mx[0].x2
        _seg = [(_front, _plan_mx[0].y1 + 1), (_front, _plan_mx[0].y2 - 1)]
        _fois = sum(len(_mx.couper_polyligne(_seg, m)) for m in _plan_mx)
        _tx = sum(m.dx for m in _plan_mx)
        _ty = sum(m.dy for m in _plan_mx)
        check('morceaux : un trait sur la frontiere n est grave qu une fois',
              _fois == 1
              and abs(_tx + (_plan_mx[-1].cx - _plan_mx[0].cx)) < 1e-9
              and abs(_ty + (_plan_mx[-1].cy - _plan_mx[0].cy)) < 1e-9,
              f'{_fois} fois · deplacement total ({_tx:g}, {_ty:g}) = '
              f'oppose du chemin des morceaux')
        _petit_mx = Document(name='petit',
                             shapes=[Rect(width=50, height=30, recipe=_r_mx)])
        _p1 = _mx.plan(_petit_mx.bounds(), 110, 110, 2.0)
        check('morceaux : ce qui tient part en un seul morceau, sans bouger',
              len(_p1) == 1 and _p1[0].cx == 0.0 and _p1[0].cy == 0.0
              and not _mx.necessaire(_petit_mx),
              'une case, centree sur l origine')
        _dir_mx = _pl_mx.Path(_tf_mx.mkdtemp(prefix='taudrive-mx-'))
        _ecrits = _iso_mx.export_morceaux(
            _doc_mx, _dir_mx, _plan_mx, marge_mm=2.0, marques=True,
            machine_iso_dir='Z:' + chr(92) + 'gravure' + chr(92) + 'grand')
        _consignes = (_dir_mx / _iso_mx.CONSIGNES).read_text(encoding='utf-8')
        _jobs = sorted(f.name for f in _dir_mx.rglob('*.CLJOB'))
        _iso2 = next(_dir_mx.rglob('grand_m02_Z0001.ISO')).read_text()
        _job2 = next(_dir_mx.rglob('grand_m02.CLJOB')).read_text()
        check('morceaux : un job par morceau, les consignes a la racine',
              _jobs == ['grand_m01.CLJOB', 'grand_m02.CLJOB',
                        'grand_m03.CLJOB', 'grand_m04.CLJOB']
              and 'Morceau 2/4' in _consignes
              and 'Déplacer la pièce de 100,0 mm vers X− (gauche)' in _consignes
              and 'morceau 2-4 - deplacer piece X-100.0 Y0.0' in _iso2
              and 'Z:' + chr(92) + 'gravure' + chr(92) + 'grand' + chr(92)
              + 'grand_m02' + chr(92) + 'grand_m02_Z0001.ISO' in _job2
              and 'traits de raccord' in ''.join(
                  f.read_text() for f in _dir_mx.rglob('grand_m01_Z*.ISO')),
              f'{len(_ecrits)} fichiers · ' + ', '.join(_jobs))
        import shutil as _sh_mx
        _sh_mx.rmtree(_dir_mx, ignore_errors=True)

        # Plafond des morceaux (EX-262). Un champ de 0,01 mm se relisait,
        # et le plan en tirait un morceau par millimètre de dessin — des
        # millions pour une emprise de quelques mètres, la mémoire
        # épuisée. Le champ se borne à 1 mm à la lecture ; au-delà de
        # `MAX_MORCEAUX`, il n'y a plus de plan, et le dialogue le dit
        # sans rien exporter.
        import json as _json_mx
        import time as _time_mx
        from engrave import serialize as _ser_mx
        _loin_mx = Document(name='loin', field_h=1.0, shapes=[
            Rect(width=20, height=10, recipe=_r_mx),
            Rect(x=0.0, y=5000.0, width=1, height=1, recipe=_r_mx)])
        _d_mx = _json_mx.loads(_ser_mx.dumps(_loin_mx))
        _d_mx['field_h'] = 0.01
        _rep_mx: list = []
        _relu_mx = _ser_mx.loads(_json_mx.dumps(_d_mx), _rep_mx)
        _b_loin_mx = _loin_mx.bounds()
        _t_mx = _time_mx.perf_counter()
        _vide_mx = _mx.plan(_b_loin_mx, 110, 1.0, 2.0)
        _t_mx = _time_mx.perf_counter() - _t_mx
        _nx_mx, _ny_mx = _mx.compte(_b_loin_mx, 110, 1.0, 2.0)
        _dlg_loin_mx = _mx.dialogue(None, _loin_mx, 'loin')
        _dlg_bon_mx = _mx.dialogue(None, _doc_mx, 'grand')
        _refuse_mx = (not _dlg_loin_mx.w_ok.isEnabled()
                      and 'au plus 1 000' in _dlg_loin_mx.w_titre.text()
                      and _dlg_bon_mx.w_ok.isEnabled()
                      and len(_dlg_bon_mx.plan()) == 4)
        for _dlg in (_dlg_loin_mx, _dlg_bon_mx):
            _dlg.deleteLater()
        check('morceaux : au-delà de mille, ni plan ni export, et un champ '
              'de 0,01 mm ne se relit plus (EX-262)',
              _relu_mx.field_h == 110.0 and len(_rep_mx) == 1
              and _vide_mx == [] and _nx_mx * _ny_mx > _mx.MAX_MORCEAUX
              and _t_mx < 0.1 and _refuse_mx,
              f'champ de 0,01 mm relu à {_relu_mx.field_h:g} · emprise de '
              f'5 m dans 1 mm : {_nx_mx * _ny_mx} morceaux refusés en '
              f'{_t_mx * 1000:.1f} ms · dialogue '
              f'{"bloqué" if _refuse_mx else "OUVERT"}')

        # --- echange de prereglages entre postes --------------------------
        from engrave import echange as _ech
        _dir_ech = _pl_mx.Path(_tf_mx.mkdtemp(prefix='taudrive-ech-'))
        _f_pr = _ech.ecrire_process(_dir_ech / 'essai', list(PRESET_RECIPES[:3]))
        _venues, _entete = _ech.lire_process(_f_pr)
        _refus = ''
        try:
            _ech.lire_codes(_f_pr)
        except _ech.EchangeError as exc:
            _refus = str(exc)
        _f_co = _ech.ecrire_codes(_dir_ech / 'codes',
                                  [{'name': 'A', 'kind': 'qr'}, {'name': ''}])
        _venus_co, _ = _ech.lire_codes(_f_co)
        _fus = _ech.fusionner(
            list(PRESET_RECIPES[:2]),
            [_dc_nap.replace(PRESET_RECIPES[0], power_percent=1.0),
             _dc_nap.replace(PRESET_RECIPES[1], name='Neuve')],
            lambda r: r.name)
        check('echange : process et prereglages de code, un fichier chacun',
              _f_pr.name.endswith(_ech.SUFFIX_PROCESS)
              and [r.name for r in _venues] == [r.name for r in PRESET_RECIPES[:3]]
              and _entete.get('programme') == 'TauDrive'
              and 'pas des préréglages de code' in _refus
              and len(_venus_co) == 1
              and [r.name for r in _fus] == [PRESET_RECIPES[0].name,
                                              PRESET_RECIPES[1].name, 'Neuve']
              and _fus[0].power_percent == 1.0,
              f'{_f_pr.name} · refus : {_refus[:40]} · fusion remplace par '
              f'le nom et ajoute a la fin')
        # l archive complete emporte aussi les prereglages de code
        from engrave import settingsio as _sio, codepresets as _cp_e
        _arch = _dir_ech / 'tout.taudrive-reglages'
        _compte = _sio.export(_arch)
        _vu = _sio.inspect(_arch)
        check('echange : l archive des reglages emporte les prereglages de code',
              _compte.get('codes', 0) >= 1 and _vu['nb_codes'] == _compte['codes']
              and _vu['noms_codes'][0] == _cp_e.load()[0]['name'],
              f'{_vu["nb_codes"]} prereglages · {_vu["noms_codes"][0][:30]}')
        _sh_mx.rmtree(_dir_ech, ignore_errors=True)

        # --- encombrement : la premiere question devant une forme -----------
        from engrave.app import Inspector as _Insp
        from engrave.model import Path as _PathS

        _insp = _Insp()
        _mesures = {}
        for _f in (Rect(width=20, height=10, recipe=PRESET_RECIPES[0]),
                   Text(text='ABC', size_mm=5, recipe=PRESET_RECIPES[0]),
                   _PathS(polylines=[[(0, 0), (12.5, 0), (12.5, 7.25)]],
                          recipe=PRESET_RECIPES[0])):
            _insp.set_shape(_f)
            _mesures[type(_f).__name__] = (_insp.w_dimx.text(),
                                           _insp.w_dimy.text())
        check('encombrement : DimX et DimY, pour tout type de forme',
              '20.000' in _mesures['Rect'][0]
              and '10.000' in _mesures['Rect'][1]
              and '12.500' in _mesures['Path'][0]
              and all('—' not in v for p in _mesures.values() for v in p),
              'un trace importe n' + chr(39) + 'en affichait aucun')

        # la mesure porte sur la geometrie reelle, pas sur les cotes
        # nominales : un code de 15 mm en fait 16 avec son cadre
        _code_m = _CodeS(kind='datamatrix', data='B000181', fit_w_mm=15,
                       fit_h_mm=7, frame='rect', frame_margin_mm=0.5,
                       recipe=PRESET_RECIPES[0])
        _insp.set_shape(_code_m)
        check('encombrement : mesure la geometrie reelle, cadre compris',
              '16.000' in _insp.w_dimx.text()
              and '8.000' in _insp.w_dimy.text(),
              f'fenetre 15x7 -> {_insp.w_dimx.text()} x {_insp.w_dimy.text()}')

        # --- F2 : tourner --------------------------------------------------
        from engrave import resize as _rz

        _a = Rect(x=10, y=0, width=20, height=10, recipe=PRESET_RECIPES[0])
        _b = Rect(x=-10, y=0, width=20, height=10, recipe=PRESET_RECIPES[0])
        _rz.rotate_selection([_a, _b], 90)
        check('F2 : un groupe tourne autour de son centre commun',
              abs(_a.x) < 1e-9 and abs(_a.y - 10) < 1e-9
              and abs(_b.y + 10) < 1e-9 and _a.rotation_deg == 90.0,
              'les formes gardent leurs positions relatives')

        _seule = Rect(x=5, y=5, width=20, height=10,
                      recipe=PRESET_RECIPES[0])
        _rz.rotate_selection([_seule], 45)
        check('F2 : une forme seule tourne sur elle-meme',
              _seule.x == 5 and _seule.y == 5
              and _seule.rotation_deg == 45.0,
              'il n' + chr(39) + 'y a pas d' + chr(39) + 'ensemble autour duquel la faire pivoter')

        _dlg0 = _rz.ResizeDialog(None, [_a, _b])
        check('F2 : la cote passe devant, en gras et plus haute',
              _dlg0.w_x.font().bold() and _dlg0.w_x.minimumHeight() >= 30
              and not _dlg0.p_x.font().bold(),
              'taper la cote est le geste courant ; le pourcentage sert '
              'une fois sur dix')

        check('F2 : les pourcentages sont replies, et s' + chr(39) + 'en souviennent',
              _dlg0.w_pct_box.isCheckable()
              and hasattr(_rz, 'CLE_POURCENT'),
              'a un clic, sans se disputer l' + chr(39) + 'attention avec la cote')

        _dlg = _rz.ResizeDialog(None, [_a, _b])
        _avant_rot = _dlg.r_angle.isEnabled()
        _dlg.w_turn.setChecked(True)
        check('F2 : le champ d' + chr(39) + 'angle s' + chr(39) + 'ouvre a la demande',
              not _avant_rot and _dlg.r_angle.isEnabled()
              and hasattr(_rz, 'rotate_selection'),
              'mettre a la cote, tourner, placer — le meme mouvement')

        # --- la semence : ce que la distribution apporte ---------------------
        import json
        from engrave import semence as _sem
        from PySide6.QtCore import QSettings as _QS

        _magasin = _QS('Cielle', 'TauDrive-semence-autotest')
        _magasin.clear()
        _pose = _sem.semer(_magasin)
        check('semence : le cœur libre n en livre aucune, et demarre',
              _pose == {'process': 0, 'gabarits': 0, 'reglages': 0}
              and _sem.resume() == 'aucune semence livrée',
              _sem.resume())

        # la semence d un plugin : posee si elle manque, jamais reposee
        from engrave import plugins as _pl_sem
        _graine = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-semence-'))
        (_graine / 'reglages.json').write_text(json.dumps(
            {'reglages': {'autotest/semence': 1, 'autotest/graine': 'b'}}),
            encoding='utf-8')
        _pl_sem.REGISTRY.seed_dir = _graine
        try:
            _pose = _sem.semer(_magasin)
            _repose = _sem.semer(_magasin)
            _resume_sem = _sem.resume()
        finally:
            _pl_sem.REGISTRY.seed_dir = None
            _magasin.clear()
        check('semence : celle d un plugin se pose, jamais par-dessus',
              _pose['reglages'] == 2 and _repose['reglages'] == 0
              and _resume_sem == '2 reglages',
              'un poste qui a regle sa bibliotheque garde ce qu il a regle')

        # --- refus explicites : dire quoi faire, pas juste « non » -----------
        from engrave import convert as _cv2
        _bac_ref = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-refus-'))
        _img = _bac_ref / 'photo.eps'
        _img.write_bytes(
            b'%!PS-Adobe-3.0 EPSF-3.0' + bytes([10])
            + b'%%BoundingBox: 0 0 100 100' + bytes([10])
            + b'%%EndProlog' + bytes([10])
            + b'300 300 8 [1 0 0 1 0 0] {<ff>} false 3 colorimage' + bytes([10]))
        _dit = ''
        try:
            _cv2.convert(_img, 'dxf', dossier=_bac_ref / 'out')
        except _cv2.ConvertError as exc:
            _dit = str(exc)
        check('refus : une image matricielle est nommee, avec le remede',
              'image' in _dit.lower() and 'ectoris' in _dit
              and 'lecture impossible : lecture impossible' not in _dit,
              _dit.splitlines()[0][:70] if _dit else 'PAS DE REFUS')

        _casse = 0
        for _nom, _octets in (('vide.eps', b''),
                              ('tronque.pdf', b'%PDF-1.4' + bytes([10]) + b'1 0 obj'),
                              ('binaire.svg', bytes(range(256))),
                              ('texte.dxf', b'pas un dxf' + bytes([10]))):
            _f = _bac_ref / _nom
            _f.write_bytes(_octets)
            try:
                _cv2.convert(_f, 'dxf', dossier=_bac_ref / 'out')
                _casse += 1                       # a ecrit : c est pire
            except _cv2.ConvertError:
                pass
            except Exception:
                _casse += 1                       # a plante
        check('refus : aucun fichier abime ne plante ni ne passe',
              _casse == 0,
              'quatre fichiers fautifs, quatre refus propres')
        shutil.rmtree(_bac_ref, ignore_errors=True)

        # --- depouillement : meme comportement, moins de prose ---------------
        import importlib.util as _ilu_t
        _spd = _ilu_t.spec_from_file_location(
            'depouiller', 'outils/depouiller.py')
        _depo = _ilu_t.module_from_spec(_spd)
        _spd.loader.exec_module(_depo)
        _essai = _depo.depouiller(
            'def f():' + chr(10) + '    ' + chr(34) * 3 + 'doc' + chr(34) * 3
            + chr(10) + '    return 42' + chr(10))
        _ns = {}
        exec(_essai, _ns)
        check('depouillement : le code se comporte pareil, sans sa prose',
              _ns['f']() == 42 and _ns['f'].__doc__ is None
              and 'doc' not in _essai,
              'la docstring part, la valeur reste')

        # --- le gabarit : les cotes sortent du code -------------------------
        #
        # Les cotes d un montage sont celles de la mecanique. Le jour ou
        # l entraxe change, ce doit etre une valeur a corriger, pas un
        # executable a reconstruire.
        check('gabarit : le montage livre reproduit les cotes en service',
              [round(y, 2) for y in _gab.positions(_g_def)]
              == [23.2, 0.2, -22.8]
              and _g_def['code']['largeur_mm'] == 15.0
              and _g_def['code']['module_mm'] == 0.5,
              'entraxe 23,0 · centre 0,2 · symbole 15x7 + cadre 0,5')

        # un deuxieme montage, sans une ligne de code
        _g4 = _gab.verifier({'nom': 'Essai 4', 'postes': ['A', 'B', 'C', 'D'],
                             'entraxe_mm': 18.0, 'centre_y_mm': 0.0})
        _f4 = _mtg.build(PRESET_RECIPES[0], gabarit=_g4)
        check('gabarit : un montage a 4 postes ne demande aucun code',
              len(_f4) == 8 and _mtg.is_montage(_f4)
              and [round(y, 1) for y in _gab.positions(_g4)]
              == [27.0, 9.0, -9.0, -27.0],
              'entraxe et nombre de postes sont des valeurs, pas du code')

        # un montage irregulier n a pas d entraxe a declarer
        _gi = _gab.verifier({'nom': 'Irregulier', 'postes': ['H', 'M', 'B'],
                             'positions_y_mm': [30.0, 0.0, -12.0]})
        check('gabarit : les positions explicites l' + chr(39) + 'emportent',
              _gab.positions(_gi) == [30.0, 0.0, -12.0],
              'tout montage n' + chr(39) + 'a pas d' + chr(39) + 'intention reguliere')

        _fautifs = 0
        for _mauvais in ({'nom': 'X', 'postes': ['A', 'B'],
                          'positions_y_mm': [1.0]},
                         {'nom': 'Y', 'postes': []},
                         {'nom': 'Z', 'postes': ['A'],
                          'code': {'module_mm': 0}}):
            try:
                _gab.verifier(_mauvais)
            except _gab.GabaritError:
                _fautifs += 1
        check('gabarit : un gabarit faux est refuse, et dit pourquoi',
              _fautifs == 3,
              'postes et positions qui se contredisent, aucun poste, '
              'module nul')

        # un fichier absent n est pas une erreur : c est un poste qui n a
        # rien personnalise, et le montage livre doit marcher quand meme
        check('gabarit : sans fichier, le montage livre marche',
              len(_gab.charger()) >= 1
              and _gab.charger()[0]['nom'] == _gab.LIVRE['nom'],
              'personne ne doit avoir a ecrire un fichier pour graver')

        # --- verification : les liens texte / code -------------------------------
        #
        # Le defaut trouve sur `Datamatrix.taudrive` etait en production et
        # invisible : les trois textes suivaient le symbole du milieu. La
        # verification avant export ne regardait pas `follows`.
        from engrave import preflight as _pf

        def _liens(mutation):
            _d = _Doc()
            _f = _mtg.build(PRESET_RECIPES[0])
            for _s in _f:
                _d.add(_s)
            mutation(_d, _f)
            _r = _pf.Report()
            _pf._notes_liens(_d, _r.notes.append)
            return _r.blocking()

        _sain = _liens(lambda d, f: None)
        _memecode = _liens(
            lambda d, f: [setattr(t, 'follows', f[0].id) for t in f[1::2]])
        _orphelin = _liens(lambda d, f: d.remove(f[2].id))
        _diverge = _liens(lambda d, f: setattr(f[1], 'text', 'AUTRE'))

        check('verification : un montage sain ne declenche rien',
              _sain == [],
              'un controle qui crie pour rien finit ignore')

        check('verification : deux textes sur un code, un code sans texte',
              len(_memecode) == 1 and 'mauvais symbole' in _memecode[0],
              'le defaut exact de Datamatrix.taudrive, en production')

        check('verification : un texte qui suit un code supprime',
              len(_orphelin) == 1 and 'nXexiste' in _orphelin[0].replace(
                  chr(39), 'X'),
              'le lien ne mene nulle part, le texte ne suivra plus')

        check('verification : un texte qui ne dit pas ce que dit son code',
              len(_diverge) == 1 and 'AUTRE' in _diverge[0],
              'la piece partirait avec deux numeros differents')

        # bloquant ne veut pas dire interdit : le bouton devient « exporter
        # quand meme » et le focus passe a « revenir au dessin »
        check('verification : bloquant montre, ne refuse pas',
              all(n[0] == _pf.BLOQUANT for n in _pf.Report(
                  notes=[(_pf.BLOQUANT, 'x')]).notes)
              and _pf.Report(notes=[(_pf.BLOQUANT, 'x')]).blocking() == ['x'],
              'un controle qui refuse dXexporter finit contourne'.replace(
                  'dX', 'd' + chr(39)))

        _svg_out = _bac / 'ecrit.svg'
        _vex.export(_doc_ex, _svg_out, kind='svg')
        # comparé à l'EPS du même document : deux écrivains
        # indépendants doivent rendre la même géométrie
        _aller, _ = _vec.read(_bac / 'essai.eps')
        _retour, _ = _vec.read(_svg_out)

        def _cale(polys):
            x1, y1, _, _ = _geo.bounds(polys)
            return sorted(([(x - x1, y - y1) for x, y in q] for q in polys),
                          key=lambda q: (len(q), round(q[0][0], 3)))

        _a, _r = _cale(_aller), _cale(_retour)
        _ecart = 0.0 if len(_a) == len(_r) else 9.0
        for _qa, _qb in zip(_a, _r):
            if len(_qa) != len(_qb):
                _ecart = 9.0
                break
            for (_xa, _ya), (_xb, _yb) in zip(_qa, _qb):
                _ecart = max(_ecart, abs(_xa - _xb), abs(_ya - _yb))
        check('SVG : un aller-retour ne déplace rien au-delà de l' + chr(39) + 'arrondi',
              len(_a) == len(_r) and _ecart < 0.001,
              f'{len(_r)} tracés · écart max {_ecart * 1000:.2f} µm')

        # le SVG compte ses ordonnées vers le bas : un oubli sort le dessin en
        # miroir, et un aller-retour ne le verrait pas — les deux erreurs
        # s'annulent
        import re as _re_svg
        _ys = [float(m) for m in
               _re_svg.findall(r'[ML] [-0-9.]+ ([-0-9.]+)',
                               _svg_out.read_text(encoding='utf-8'))]
        check('SVG : les ordonnées sont retournées à l' + chr(39) + 'écriture',
              bool(_ys) and min(_ys) < 0.01,
              f'le point le plus haut du dessin est écrit à y={min(_ys):.3f} '
              f'— haut de page, et non bas')

        # --- conversion sans fenêtre ---------------------------------------------
        from engrave import convert as _cvt
        _bac_cv = _bac / 'converti'
        _cible = _cvt.convert(_src_svg, 'dxf', dossier=_bac_cv)
        _encore = _cvt.convert(_src_svg, 'dxf', dossier=_bac_cv)
        check('conversion : le fichier existant n' + chr(39) + 'est jamais écrasé',
              _cible.name == 'cote.dxf' and _encore.name == 'cote (2).dxf'
              and _cible.exists() and _encore.exists(),
              'personne n' + chr(39) + 'a vu de sélecteur : rien n' + chr(39) + 'a été confirmé')

        _code = _cvt.run(['--convert', str(_src_svg), str(_bac / 'absent.svg'),
                          '--to', 'ai', '--dossier', str(_bac_cv),
                          '--silencieux'])
        check('conversion : un fichier fautif n' + chr(39) + 'arrête pas les autres',
              _code == 1 and (_bac_cv / 'cote.ai').exists(),
              'sur une sélection de trente dessins, tout reprendre coûte cher')

        check('conversion : formats annoncés cohérents avec ce qu' + chr(39) + 'on sait faire',
              set(_cvt.SOURCES) == set(_dxi.ALL_SUFFIXES) - {'.taudrive'}
              and {k for k, _ in _cvt.TARGETS} <= {k for k, _, _ in _vex.FORMATS},
              f'{len(_cvt.SOURCES)} entrées → {len(_cvt.TARGETS)} sorties')

        # --- menu contextuel Windows ---------------------------------------------
        from engrave import shellmenu as _shm
        check('clic droit : jamais de DXF vers DXF dans le sous-menu',
              all(suf.lstrip('.') not in {k for k, _ in _shm.cibles_pour(suf)}
                  for suf in _shm.EXTENSIONS),
              'une entrée qui ne fait rien use la confiance dans tout le menu')

        check('clic droit : la commande cite le programme et le format',
              all(f'--to {k}' in _shm.ligne_de_commande(k)
                  and chr(34) + '%1' + chr(34) in _shm.ligne_de_commande(k)
                  for k, _ in _shm.TARGETS),
              _shm.ligne_de_commande('dxf')[-40:])

        if _shm.disponible() and not _shm.installe():
            _pose = _shm.installer()
            _vu = _shm.installe()

            # ExtendedSubCommandsKey ne doit PAS porter le `\shell` final :
            # Windows l'ajoute lui-même, et une clé qui le porte déjà pointe
            # vers un sous-menu inexistant — l'explorateur retombe alors sur
            # un verbe fantôme et dit ne pas trouver le programme.
            import winreg as _wrx
            _cle_verbe = _wrx.OpenKey(
                _wrx.HKEY_CURRENT_USER,
                _shm.CLASSES + chr(92) + 'SystemFileAssociations' + chr(92)
                + '.svg' + chr(92) + 'shell' + chr(92) + _shm.VERBE)
            _attendu = _shm._cle_sous_menu('.svg')
            _trouve = _wrx.QueryValueEx(_cle_verbe, 'ExtendedSubCommandsKey')[0]
            _wrx.CloseKey(_cle_verbe)
            check('clic droit : le sous-menu se résout, sans « \\shell » en trop',
                  _trouve == _attendu and not _trouve.endswith('shell'),
                  f'ExtendedSubCommandsKey = {_trouve!r}')

            _shm.retirer()
            import winreg as _wr
            _restes = 0
            for _suf in _shm.EXTENSIONS:
                for _ch in (_shm.CLASSES + chr(92) + 'SystemFileAssociations'
                            + chr(92) + _suf + chr(92) + 'shell' + chr(92)
                            + _shm.VERBE,
                            _shm.CLASSES + chr(92) + _shm._cle_sous_menu(_suf)):
                    try:
                        _wr.CloseKey(_wr.OpenKey(_wr.HKEY_CURRENT_USER, _ch))
                        _restes += 1
                    except OSError:
                        pass
            check('clic droit : posé puis retiré sans laisser une clé',
                  _pose == len(_shm.EXTENSIONS) and _vu and _restes == 0,
                  f'{_pose} extensions · {_restes} clé(s) restante(s) · '
                  f'HKEY_CURRENT_USER seul, aucun droit administrateur')
        else:
            check('clic droit : état lisible sans toucher à ce qui est posé',
                  isinstance(_shm.verifier(), tuple),
                  _shm.verifier()[1])

        _n_dessin = _vex.export(_doc_ex, _bac / 'd.dxf', toolpaths=False)
        _n_traj = _vex.export(_doc_ex, _bac / 't.dxf', toolpaths=True)
        check('export : dessin et trajectoires sont deux contenus distincts',
              _n_traj > _n_dessin * 5,
              f'{_n_dessin} contours → {_n_traj} trajectoires')
        shutil.rmtree(_bac, ignore_errors=True)

        _etat_conv = _vec.converter_status()
        check('convertisseurs : version détectée et bornée',
              _vec._too_old('0.92', '1.0') and not _vec._too_old('1.3', '1.0')
              and not _vec._too_old('1.0.2', '1.0')
              and set(_vec.MIN_VERSIONS) == {'inkscape', 'soffice'}
              and all(v[1].startswith('https://')
                      for v in _vec.MIN_VERSIONS.values()),
              (f'{_etat_conv["genre"]} {_etat_conv["version"]}'
               if _etat_conv.get('trouve') else 'aucun installé'))

        from engrave.guide import formats_html as _fh
        _page_f = _fh()
        check('aide : la page des formats dit les versions et les liens',
              'Inkscape' in _page_f and '1.0' in _page_f
              and 'LibreOffice' in _page_f and '6.0' in _page_f
              and 'inkscape.org' in _page_f and 'libreoffice.org' in _page_f,
              f'{len(_page_f)} caractères')

        # --- import vectoriel : PDF, Illustrator, EPS, CorelDRAW ---------------

        import shutil
        import struct
        import tempfile
        from engrave import dxfimport as _dxi
        from engrave import vecimport as _vec

        # un fichier dont le suffixe ment : c'est le contenu qui tranche.
        # (Le controle portait sur l'existence d'une docstring, ce qui ne
        # prouvait rien — et devenait faux des qu'on les depouille.)
        _bac_sniff = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-sniff-'))
        _menteur = _bac_sniff / 'faux.dxf'
        _menteur.write_bytes(b'%!PS-Adobe-3.0 EPSF-3.0' + bytes([10]))
        check('import : les formats sont reconnus au contenu, non au suffixe',
              _vec.sniff(str(_menteur)) == 'eps'
              and set(_vec.SUFFIXES) >= {'.pdf', '.ai', '.eps', '.cdr'}
              and '.ai' in _dxi.ALL_SUFFIXES,
              ' '.join(_vec.SUFFIXES))
        shutil.rmtree(_bac_sniff, ignore_errors=True)

        # un PDF fabriqué à la volée, de géométrie connue au micron près
        _pdf = pathlib.Path(tempfile.gettempdir()) / 'taudrive-essai-import.pdf'
        _pdf.write_bytes(_pdf_essai())
        _polys, _rap = _vec.read(_pdf)
        _l, _h = _rap.size_mm()
        check('import PDF : la géométrie sort à la cote',
              _vec.sniff(_pdf) == 'pdf' and len(_polys) == 2
              and abs(_l - 80.0) < 0.001 and abs(_h - 40.0) < 0.001,
              f'{len(_polys)} tracés · {_l:.4f} × {_h:.4f} mm '
              f'(226,7717 × 113,3858 pt)')

        _formes, _ = _vec.to_shapes(_pdf, recipe=PRESET_RECIPES[1])
        _xs = [x for f in _formes for p in f.polylines for x, _ in p]
        check('import PDF : une forme Path centrée, prête à poser',
              len(_formes) == 1 and abs((min(_xs) + max(_xs)) / 2) < 0.01
              and _formes[0].recipe is PRESET_RECIPES[1],
              f'centre {(min(_xs) + max(_xs)) / 2:.4f} mm')
        _pdf.unlink(missing_ok=True)

        # l'en-tête binaire DOS d'un EPS Windows ne doit pas être pris pour du
        # PostScript
        _eps = pathlib.Path(tempfile.gettempdir()) / 'taudrive-essai.eps'
        _corps = (b'%!PS-Adobe-3.0 EPSF-3.0' + bytes([10])
                  + b'%%BoundingBox: 0 0 288 144' + bytes([10])
                  + b'%%EndPageSetup' + bytes([10])
                  + b'0 0 mo 288 0 li 288 144 li 0 144 li cp f' + bytes([10]))
        _eps.write_bytes(struct.pack('<4sII', bytes.fromhex('c5d0d3c6'), 30,
                                     len(_corps))[:12]
                         + bytes(18) + _corps)
        _pe, _re = _vec.read(_eps)
        _le, _he = _re.size_mm()
        check('import EPS : en-tête binaire DOS franchi, cotes justes',
              _vec.sniff(_eps) == 'eps' and len(_pe) == 1
              and abs(_le - 101.6) < 0.05 and abs(_he - 50.8) < 0.05,
              f'{_le:.2f} × {_he:.2f} mm (288 × 144 pt)')
        _eps.unlink(missing_ok=True)

        check('import : les deux vocabulaires Illustrator sont lus',
              all(o in _vec._PS_PATH for o in ('m', 'mo', 'l', 'li', 'c', 'cv'))
              and '@' in _vec._PS_END and 'f' in _vec._PS_END,
              'AI 8 (m l c) et AI 9+ (mo li cv)')

        check('import : les courbes de Bézier sont aplaties à la tolérance',
              _vec.TOLERANCE_MM == 0.02
              and abs(_vec.PT_TO_MM - 25.4 / 72) < 1e-12,
              f'{_vec.TOLERANCE_MM} mm · 1 pt = {_vec.PT_TO_MM:.5f} mm')

        check('import CDR : refus explicite, et non silencieux',
              'CorelDRAW' in _vec.CDR_NOTE and 'Inkscape' in _vec.CDR_NOTE
              and 'PDF' in _vec.CDR_NOTE,
              'convertisseur : '
              + (pathlib.Path(_vec.converter()[0]).name if _vec.converter()
                 else 'aucun installé'))

    if domaine('gravure'):
        # --- remplissage, oscillation, guide ------------------------------------

        import dataclasses
        import math as _math
        from engrave import advice as _adv, wobble as _wob
        from engrave import geometry as _geo
        from engrave import preflight
        from engrave.toolpath import build_passes
        from engrave.toolpath import build_shape_pass as _bsp

        # --- moins d allumages : enchainer les traces ------------------------
        #
        # Sur cette machine c est l allumage qui coute, pas la gravure :
        # chaque allumage paie des rampes SkyWrite d autant plus longues
        # que la vitesse est haute. Mesure a l atelier sur un DataMatrix
        # hachure (2 666 allumages) : 7 s a 50 m/min, 15 s a 200.
        from engrave import toolpath as _tp_en
        from engrave.model import Path as _PathEn, Code as _CodeEn
        from engrave import textvec as _tv_tr

        def _cercle_en(cx, cy, r, n=48):
            return [(cx + r * _math.cos(2 * _math.pi * k / n),
                     cy + r * _math.sin(2 * _math.pi * k / n))
                    for k in range(n + 1)]

        # un anneau et trois carres : des iles, un trou, des bords penches
        _zone_en = [_cercle_en(0, 0, 4), _cercle_en(0, 0, 2)[::-1]]
        for _k in range(3):
            _x0 = 6 + _k * 2.5
            _zone_en.append([(_x0, -1), (_x0 + 1.5, -1), (_x0 + 1.5, 1),
                             (_x0, 1), (_x0, -1)])
        _plat = _geo.hatch(_zone_en, 0.05, 0)
        _lie = _geo.hatch_linked(_zone_en, 0.05, 0)
        _hors = 0
        for _ch in _lie:
            for (_ax, _ay), (_bx, _by) in zip(_ch, _ch[1:]):
                if abs(_by - _ay) < 1e-12:
                    continue
                for _t in (0.1, 0.5, 0.9):
                    _xx = _ax + _t * (_bx - _ax)
                    _yy = _ay + _t * (_by - _ay)
                    if not any(_a - 1e-3 <= _xx <= _b + 1e-3 for _a, _b
                               in _geo.intervals_at(_zone_en, _yy)):
                        _hors += 1
                        break
        _rangs_en = {}
        for _ch in _lie:
            for (_ax, _ay), (_bx, _by) in zip(_ch, _ch[1:]):
                if abs(_by - _ay) < 1e-12:
                    _rangs_en.setdefault(round(_ay, 9), []).append(
                        (min(_ax, _bx), max(_ax, _bx)))
        _manque_en = sum(
            1 for _sg in _plat if not any(
                _p <= min(_sg[0][0], _sg[1][0]) + 1e-9
                and _q >= max(_sg[0][0], _sg[1][0]) - 1e-9
                for _p, _q in _rangs_en.get(round(_sg[0][1], 9), [])))
        check('enchainer : un trait par ile, rien hors du dessin, tout couvert',
              _geo.laser_ons(_lie) * 4 < _geo.laser_ons(_plat)
              and _hors == 0 and _manque_en == 0,
              f'{_geo.laser_ons(_plat)} → {_geo.laser_ons(_lie)} allumages · '
              f'0 lien hors zone · {len(_plat)} segments couverts')

        # les tranches d aretes rendent les memes intervalles, plus vite :
        # un texte de soixante lettres s enchainait en 3 s, 0,5 desormais
        import random as _rnd_tr
        import time as _time_tr
        _txt_tr = _tv_tr.outline('TAUDRIVE 0123456789 ABCDEFGHIJ', 4.0, '',
                                 tolerance_mm=0.01)
        _tr = _geo.EdgeSlices(_txt_tr, 0.05)
        _gen_tr = _rnd_tr.Random(3)
        _diff_tr = sum(1 for _ in range(200)
                       for _y in [_gen_tr.uniform(-1.0, 5.0)]
                       if _tr.intervals(_y) != _geo.intervals_at(_txt_tr, _y))
        _t0_tr = _time_tr.perf_counter()
        _lie_tr = _geo.hatch_linked(_txt_tr, 0.05)
        _dt_tr = _time_tr.perf_counter() - _t0_tr
        check('enchainer : les memes intervalles, sans balayer tout le texte',
              _diff_tr == 0 and _lie_tr and _dt_tr < 2.0,
              f'200 hauteurs identiques · {_geo.laser_ons(_lie_tr)} traits '
              f'en {_dt_tr:.2f} s')

        # un code : la plaque en negatif de production, et sans cadre
        _res_code = []
        for _cadre in ('rect', 'none'):
            _rs = []
            for _lien in (False, True):
                _rc = dataclasses.replace(PRESET_RECIPES[1], hatch_mm=0.05,
                                          link_paths=_lien)
                _cd = _CodeEn(kind='datamatrix', data='B000181',
                              fit_w_mm=15, fit_h_mm=7, dm_shape='auto',
                              frame=_cadre, frame_margin_mm=0.5, recipe=_rc)
                _rs.append(_geo.laser_ons(_tp_en.code_fill(_cd)))
            _res_code.append((_cadre, _rs[0], _rs[1]))
        check('enchainer : un DataMatrix se remplit d un tenant ou presque',
              all(_apres * 8 < _avant for _, _avant, _apres in _res_code),
              ' · '.join(f'{_c} {_a} → {_b}' for _c, _a, _b in _res_code))

        # des fragments de contour qui se touchent sont joints, point
        # pour point — et une boucle fermee n est pas touchee
        _frag = [[(0, 0), (5, 0)], [(5, 0), (5, 3)], [(0, 3), (5, 3)],
                 [(0, 3), (0, 0)], [(8, 0), (9, 1), (10, 0), (8, 0)]]
        _joint = _geo.chain_open(_frag)

        def _segs(_q):
            return sorted(tuple(sorted((tuple(map(lambda v: round(v, 6), _a)),
                                        tuple(map(lambda v: round(v, 6), _b)))))
                          for _pl in _q for _a, _b in zip(_pl, _pl[1:]))
        check('enchainer : les fragments qui se touchent sont joints',
              _geo.laser_ons(_joint) == 2 and _segs(_joint) == _segs(_frag)
              and [(8, 0), (9, 1), (10, 0), (8, 0)] in _joint,
              f'{_geo.laser_ons(_frag)} → {_geo.laser_ons(_joint)} allumages, '
              f'memes segments, la boucle fermee intacte')

        # par la process : faux par defaut, et une process d avant le relit
        # faux ; coche, il change la trajectoire et la cle de cache
        _forme_en = _PathEn(polylines=_zone_en, recipe=dataclasses.replace(
            PRESET_RECIPES[1], hatch_mm=0.05))
        _doc_en = Document(name='enchaine', shapes=[_forme_en])
        _n_off = sum(_geo.laser_ons(_p.polylines)
                     for _p in build_passes(_doc_en, optimize=True))
        _forme_en.recipe = dataclasses.replace(_forme_en.recipe,
                                               link_paths=True)
        _n_on = sum(_geo.laser_ons(_p.polylines)
                    for _p in build_passes(_doc_en, optimize=True))
        check('enchainer : une case de la process, decochee par defaut',
              PRESET_RECIPES[1].link_paths is False and _n_on * 4 < _n_off,
              f'decoche {_n_off} allumages · coche {_n_on}')

        # --- plaque : ce qu une retouche apprend a la suivante ----------
        from engrave import codeplate as _cp_rt
        _tf_rt = None
        _tailles_rt = []
        for _i_rt in range(4):
            _pl_rt = _cp_rt.build_plate(PRESET_RECIPES[1],
                                        frame=(0.0, 0.0, 15.0, 7.0),
                                        text_frame=_tf_rt)
            _tailles_rt.append(_pl_rt[1].size_mm)
            _reg_rt = _cp_rt.plate_settings(_pl_rt[0], _pl_rt[1])
            _dx_rt, _dy_rt, _tw_rt, _th_rt = _reg_rt['text_offset']
            _tf_rt = (_dx_rt, _dy_rt, _tw_rt, _th_rt)
        # un rectangle choisi pour toutes les plaques reste choisi
        _rect_rt = _cp_rt.plate_settings(_pl_rt[0], _pl_rt[1], 'rect')
        _pl_rt[0].rotation_deg = 90.0
        check('plaque : retouchee puis reposee, son texte garde sa taille',
              max(_tailles_rt) - min(_tailles_rt) < 1e-6
              and _reg_rt['code_frame'] == 'auto'
              and _rect_rt['code_frame'] == 'rect'
              and 'text_offset' not in _cp_rt.plate_settings(_pl_rt[0],
                                                              _pl_rt[1]),
              f'{len(_tailles_rt)} cycles a {_tailles_rt[-1]:.4f} mm · '
              f'cadre toujours « selon le code » · tournee : texte non retenu')

        # --- anneaux : le remplissage qui suit le contour ---------------
        #
        # Le zigzag supprime les allumages, pas les demi-tours : sur un
        # bord penche, chacun est un virage SkyWrite. Les anneaux n en ont
        # pas. Rien hors de la zone, et aucun point a plus de 0,6 pas d un
        # trait (contour compris) — le hachurage garantit 0,5.
        from engrave import rings as _rings_an, ordering as _ord_an
        from shapely.geometry import Polygon as _PolyAn, LineString as _LsAn
        from shapely.ops import unary_union as _uu_an
        _an = _rings_an.fill(_zone_en, 0.05)
        _sp = _rings_an.fill(_zone_en, 0.05, link=True)
        _zsh = _rings_an._pair_impair([_PolyAn(_c) for _c in _zone_en])
        _dans_an = _zsh.buffer(1e-6)
        _hors_an = sum(1 for _pl in _an + _sp
                       if not _dans_an.covers(_LsAn(_pl)))
        _traits_an = _uu_an([_LsAn(_pl) for _pl in _sp]
                            + [_LsAn(_c) for _c in _zone_en])
        _trou_an = _zsh.difference(_traits_an.buffer(
            0.6 * 0.05 * 1.02, quad_segs=4)).area / _zsh.area
        check('anneaux : tout dedans, tout couvert a 0,6 pas pres',
              len(_an) > 10 and _hors_an == 0 and _trou_an < 0.002,
              f'{len(_an)} anneaux, {_geo.laser_ons(_sp)} spirales · '
              f'0 hors zone · {_trou_an * 100:.3f} % a plus de 0,6 pas')

        def _vir_an(_q):
            return sum(_tp_en.sharp_corners(_pl) for _pl in _q)

        def _du_an(_q):
            return _tp_en.polylines_duration_s(_ord_an.optimize(_q), 100000)
        _zz_an = _geo.hatch_linked(_zone_en, 0.05)
        check('anneaux : ni allumages ni demi-tours, bien plus court',
              _vir_an(_sp) * 4 < _vir_an(_zz_an)
              and _du_an(_sp) * 1.5 < _du_an(_zz_an)
              and _geo.laser_ons(_sp) < _geo.laser_ons(_an),
              f'zigzag {_geo.laser_ons(_zz_an)} allumages, '
              f'{_vir_an(_zz_an)} virages, {_du_an(_zz_an):.2f} s · '
              f'spirales {_geo.laser_ons(_sp)}, {_vir_an(_sp)}, '
              f'{_du_an(_sp):.2f} s a 100 m/min')

        # par la process : hachures par defaut ; sans shapely, hachures
        _f_an = _PathEn(polylines=_zone_en, recipe=dataclasses.replace(
            PRESET_RECIPES[1], hatch_mm=0.05))
        _p_h_an = _tp_en.local_polylines(_f_an)
        _f_an.recipe = dataclasses.replace(_f_an.recipe, fill_style='rings')
        _p_r_an = _tp_en.local_polylines(_f_an)
        _fill_orig = _rings_an.fill
        _rings_an.fill = lambda *_a, **_k: None
        try:
            _tp_en.clear_cache()
            _p_sans_an = _tp_en.local_polylines(_f_an)
        finally:
            _rings_an.fill = _fill_orig
            _tp_en.clear_cache()
        # un triangle de trois points, non referme, reste un trou ; et un
        # document de codes seuls n entend pas parler d anneaux
        _carre_an = [(-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5)]
        _tri_an = [(-2, -2), (0, 2), (2, -2)]
        _r_tri = _rings_an.fill([_carre_an, _tri_an], 0.1)
        _dans_tri = sum(1 for _pl in _r_tri for _x, _y in _pl
                        if _PolyAn(_tri_an + [_tri_an[0]]).buffer(-1e-6)
                        .contains(__import__('shapely.geometry', fromlist=[
                            'Point']).Point(_x, _y)))
        _rap_cd = preflight.inspect(Document(name='codes', shapes=[_CodeEn(
            kind='datamatrix', data='B000181', fit_w_mm=15, fit_h_mm=7,
            frame='rect', recipe=dataclasses.replace(
                PRESET_RECIPES[1], hatch_mm=0.05))]), optimize=True)
        check('anneaux : un trou de trois points reste un trou, un code '
              'n en parle pas',
              _r_tri and _dans_tri == 0
              and not any('anneaux' in _t for _, _t in _rap_cd.notes),
              f'{len(_r_tri)} anneaux, aucun point dans le triangle · '
              f'DataMatrix seul : pas de conseil d anneaux')

        check('anneaux : un choix de la process, hachures par defaut et '
              'sans shapely',
              PRESET_RECIPES[1].fill_style == 'hatch'
              and _p_r_an != _p_h_an and _p_sans_an == _p_h_an,
              f'hachures {len(_p_h_an)} traces · anneaux {len(_p_r_an)} · '
              f'sans shapely : les hachures')

        # --- lignes paralleles : dedans, dehors, ou des deux cotes --------
        _emprises = {}
        for _cote in ('both', 'inside', 'outside'):
            _rr = Rect(width=10, height=10, recipe=PRESET_RECIPES[1],
                       line_width_mm=0.3, line_step_mm=0.05, line_side=_cote)
            _xs = [_x for _pl in _tp_en.local_polylines(_rr)
                   for _x, _ in _pl]
            _emprises[_cote] = (min(_xs), max(_xs))
        _sq = [(-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5)]
        _sens = []
        for _pts in (_sq, _sq[::-1]):
            _pp = _PathEn(polylines=[_pts], recipe=PRESET_RECIPES[1],
                          line_width_mm=0.3, line_step_mm=0.05,
                          line_side='outside')
            _sens.append(max(_x for _pl in _tp_en.local_polylines(_pp)
                             for _x, _ in _pl))
        check('cotes : les lignes paralleles vont dedans, dehors ou des deux',
              abs(_emprises['both'][1] - 5.15) < 1e-6
              and abs(_emprises['inside'][1] - 5.0) < 1e-6
              and abs(_emprises['outside'][1] - 5.3) < 1e-6
              and abs(_sens[0] - _sens[1]) < 1e-9,
              f'des deux {_emprises["both"][1]:.2f} · dedans '
              f'{_emprises["inside"][1]:.2f} · dehors '
              f'{_emprises["outside"][1]:.2f} · sens du contour sans effet')
        def _bornes_c(_q):
            return (min(x for c in _q for x, _ in c),
                    max(x for c in _q for x, _ in c),
                    min(y for c in _q for _, y in c),
                    max(y for c in _q for _, y in c))
        _ouv_c = _bornes_c(_tp_en.thicken([[(0, 0), (10, 0)]], 0.3, 0.05,
                                          'inside'))
        _rem_c = []
        for _lie_c in (False, True):
            _rr_c = Rect(width=10, height=10, recipe=dataclasses.replace(
                PRESET_RECIPES[1], hatch_mm=0.1, link_paths=_lie_c),
                line_width_mm=0.3, line_step_mm=0.05, line_side='inside')
            _rem_c.append(_bornes_c(_tp_en.local_polylines(_rr_c)))
        _quatre_c = [[(0, 0), (10, 0)], [(10, 0), (10, 10)],
                     [(10, 10), (0, 10)], [(0, 10), (0, 0)]]
        _lignes_c = _bornes_c(_tp_en.local_polylines(_PathEn(
            polylines=_quatre_c, recipe=PRESET_RECIPES[1],
            line_width_mm=0.3, line_step_mm=0.05, line_side='inside')))
        check('cotes : dedans, rien ne deborde de la piece',
              abs(_ouv_c[3] - 0.15) < 1e-6
              and all(abs(max(map(abs, _b)) - 5.0) < 1e-6 for _b in _rem_c)
              and _lignes_c == (0, 10, 0, 10),
              f'ligne ouverte ±{_ouv_c[3]:.2f} · carre rempli, enchaine ou '
              f'non, dans ±5 · quatre LINE dans 0..10')

        def _cercle_c(_r, _sens=1, _n=96):
            _q = [(_r * _math.cos(2 * _math.pi * _k / _n),
                   _r * _math.sin(2 * _math.pi * _k / _n))
                  for _k in range(_n)][::_sens]
            return _q + [_q[0]]
        _ray_c = {}
        for _cote_c in ('outside', 'inside'):
            _ray_c[_cote_c] = sorted({round(_math.hypot(x, y), 2) for c in
                                      _tp_en.local_polylines(_PathEn(
                                          polylines=[_cercle_c(10),
                                                     _cercle_c(6, -1)],
                                          recipe=PRESET_RECIPES[1],
                                          line_width_mm=0.5,
                                          line_step_mm=0.1,
                                          line_side=_cote_c))
                                      for x, y in c})
        check('cotes : le bord d un trou a son dehors dans le trou',
              _ray_c['outside'][0] == 5.5 and _ray_c['outside'][-1] == 10.5
              and _ray_c['inside'][0] == 6.0 and _ray_c['inside'][-1] == 10.0,
              f'matiere de r 6 a 10 · dehors : {_ray_c["outside"][0]} et '
              f'{_ray_c["outside"][-1]} · dedans : de '
              f'{_ray_c["inside"][0]} a {_ray_c["inside"][-1]}')

        # deux carres qui se touchent par un coin ne sont pas des trous ;
        # quatre LINE refermees a 5 microns pres ont bien un dedans
        def _hors_c(_polys, _zones):
            from shapely.geometry import Polygon as _PgC, LineString as _LsC
            from shapely.ops import unary_union as _uuC
            _z = _uuC([_PgC(_q) for _q in _zones]).buffer(1e-6)
            return sum(_LsC(_q).difference(_z).length for _q in _polys
                       if len(_q) > 1)
        _coins_c = [[(1, 0), (2, 0), (2, 1), (1, 1), (1, 0)],
                    [(1, 0), (0, 0), (0, -1), (1, -1), (1, 0)]]
        _ecart_c = [[(0, 0), (10, 0)], [(10, 0), (10, 10)],
                    [(10, 10), (0, 10)], [(0, 10), (0, 5e-6)]]
        _h1_c = _hors_c(_tp_en.thicken(_coins_c, 0.2, 0.05, 'inside'),
                        _coins_c)
        _h2_c = _hors_c(_tp_en.thicken(_ecart_c, 0.3, 0.05, 'inside'),
                        [[(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]])
        _code_c = _CodeEn(kind='datamatrix', data='B000123', module_mm=0.5,
                          recipe=PRESET_RECIPES[1], line_width_mm=0.15,
                          line_step_mm=0.05, line_side='inside')
        _p_ins_c = _tp_en.local_polylines(_code_c)
        _code_c.line_side = 'both'
        _p_both_c = _tp_en.local_polylines(_code_c)
        check('cotes : coins qui se touchent, LINE presque jointes, code',
              _h1_c < 1e-6 and _h2_c < 1e-6 and _p_ins_c == _p_both_c,
              f'hors piece : {_h1_c:.4f} et {_h2_c:.4f} mm · un code '
              f's elargit des deux cotes')

        # un jambage plus etroit que l epaisseur : les passages d un bord
        # traversaient jusqu a l autre et ressortaient — rognes a la matiere
        _lettres_c = _tv_tr.outline('OB8A', 5.0, '', tolerance_mm=0.01)
        _cotes_c = {}
        for _cote_c in ('inside', 'outside'):
            _aj_c = _tp_en.thicken([list(_q) for _q in _lettres_c], 0.3, 0.05,
                                   _cote_c)[len(_lettres_c):]
            from shapely.geometry import (Polygon as _PgL,
                                          LineString as _LsL)
            from engrave import rings as _rg_l
            _mat_c = _rg_l._pair_impair([_PgL(_q).buffer(0)
                                         for _q in _lettres_c])
            _cotes_c[_cote_c] = sum(
                (_LsL(_q).difference(_mat_c.buffer(1e-5)).length
                 if _cote_c == 'inside'
                 else _LsL(_q).intersection(_mat_c.buffer(-1e-5)).length)
                for _q in _aj_c if len(_q) > 1)
        check('cotes : un jambage fin ne fait pas deborder « dedans »',
              _cotes_c['inside'] < 1e-6 and _cotes_c['outside'] < 1e-6,
              f'« OB8A » de 5 mm, 0,3 mm d un seul cote : '
              f'{_cotes_c["inside"]:.4f} mm hors matiere, '
              f'{_cotes_c["outside"]:.4f} mm dans la matiere')

        # une LINE recopiee, avalee par une chaine, ne se grave pas deux fois
        _dbl_c = _PathEn(polylines=_quatre_c + [[(10, 10), (0, 10)]],
                         recipe=dataclasses.replace(PRESET_RECIPES[1],
                                                    link_paths=True))
        _lg_c = sum(_math.dist(_a, _b) for c in _tp_en.local_polylines(_dbl_c)
                    for _a, _b in zip(c, c[1:]))
        check('enchainer : un doublon de DXF ne se grave qu une fois',
              abs(_lg_c - 40.0) < 1e-6,
              f'rectangle de 40 mm + un cote recopie : {_lg_c:.3f} mm graves')

        # l arrondi binaire ne vole plus un passage : 0,3 / 0,05 / 2 = 3
        check('cotes : un trait de 0,3 mm fait 0,3 mm, pas 0,2',
              abs((_emprises['both'][1] - 5.0) * 2 - 0.3) < 1e-6,
              f'{(_emprises["both"][1] - 5.0) * 2:.2f} mm de part et '
              f'd autre du trace')

        # Normalisation (EX-258) : un passage retenu se range en segments,
        # non plus en échantillons, et un segment à rogner se juge d'un
        # bloc. Un long passage au pas d'un dixième de micron remplissait
        # le plafond de quatre millions d'échantillons — des minutes et des
        # gigaoctets ; rien ne l'approche, il est gardé tel quel, et le
        # plafond atteint laisse les suivants intacts, comme avant. Le test
        # d'occupation, lui, répond comme celui d'avant, qui éprouvait les
        # échantillons un à un ; et un tronçon jugé couvert d'un bloc l'est
        # en chacun de ses points.
        import random as _rnd_nl
        import time as _time_nl
        _base_nl = [[(9000.0, 4500.0), (9000.08, 4500.0),
                     (9000.08, 4500.05), (9000.0, 4500.0)]]
        _ajout_nl = [[(0.0, 0.0), (300.0, 40.0), (120.0, 260.0)],
                     [(10.0, 10.0), (250.0, -90.0)],
                     [(5.0, 5.0), (-200.0, 80.0)]]
        _t_nl = _time_nl.perf_counter()
        _sortie_nl = _tp_en.normalise(_base_nl, _ajout_nl, 0.0001)
        _t_nl = _time_nl.perf_counter() - _t_nl
        _hasard_nl = _rnd_nl.Random(258)
        _lat_nl = _tp_en._Lattice(0.1)
        _retenus_nl = [[(_hasard_nl.uniform(0, 3), _hasard_nl.uniform(0, 3))
                        for _ in range(_hasard_nl.randint(2, 6))]
                       for _ in range(5)] + [[(1.5, 1.5)]]
        _echant_nl = []
        for _q in _retenus_nl:
            _lat_nl.occupy(_q)
            if len(_q) < 2:
                _echant_nl.extend(_q)
                continue
            for (_x1, _y1), (_x2, _y2) in zip(_q, _q[1:]):
                _n = max(1, int(_math.hypot(_x2 - _x1, _y2 - _y1)
                                / _lat_nl.sample))
                _echant_nl.extend((_x1 + (_x2 - _x1) * (_k / _n),
                                   _y1 + (_y2 - _y1) * (_k / _n))
                                  for _k in range(_n))
            _echant_nl.append(_q[-1])
        _seuil_nl = _lat_nl.threshold * _lat_nl.threshold

        def _occupe_nl(_x, _y):
            return any((_px - _x) ** 2 + (_py - _y) ** 2 < _seuil_nl
                       for _px, _py in _echant_nl)

        _desacc_nl = _faux_nl = _couverts_nl = 0
        for _ in range(600):
            _x, _y = _hasard_nl.choice(_echant_nl)
            _x += _hasard_nl.uniform(-0.15, 0.15)
            _y += _hasard_nl.uniform(-0.15, 0.15)
            _desacc_nl += (_lat_nl.occupe(_x, _y,
                                          _lat_nl.proches(_x, _y, _x, _y),
                                          _lat_nl._marge(_x, _y, _x, _y))
                           != _occupe_nl(_x, _y))
            # un tronçon de 0,3 mm le long d'un passage, un peu de biais
            _q = _hasard_nl.choice(_retenus_nl[:5])
            _i = _hasard_nl.randrange(len(_q) - 1)
            (_x1, _y1), (_x2, _y2) = _q[_i], _q[_i + 1]
            _t = _hasard_nl.random()
            _x = _x1 + (_x2 - _x1) * _t + _hasard_nl.uniform(-0.08, 0.08)
            _y = _y1 + (_y2 - _y1) * _t + _hasard_nl.uniform(-0.08, 0.08)
            _a_nl = (_math.atan2(_y2 - _y1, _x2 - _x1)
                     + _hasard_nl.uniform(-0.3, 0.3))
            _xb = _x + 0.3 * _math.cos(_a_nl)
            _yb = _y + 0.3 * _math.sin(_a_nl)
            if _lat_nl.couvre(_x, _y, _xb, _yb,
                              _lat_nl.proches(_x, _y, _xb, _yb)):
                _couverts_nl += 1
                _faux_nl += not all(
                    _occupe_nl(_x + (_xb - _x) * _k / 15,
                               _y + (_yb - _y) * _k / 15)
                    for _k in range(16))
        check("normalisation : un passage au pas fin ne fige plus, "
              "l'occupation est celle d'avant (EX-258)",
              _t_nl < 5.0 and _sortie_nl == _ajout_nl and _desacc_nl == 0
              and _faux_nl == 0 and _couverts_nl > 0,
              f'passage de 580 mm au pas de 0,0001 mm : {_t_nl:.2f} s · '
              f'{_desacc_nl} désaccord(s) sur 600 points avec les '
              f'échantillons un à un · {_couverts_nl} tronçons jugés '
              f'couverts, {_faux_nl} à tort')

        # Plafond des passages (EX-261). Une épaisseur de 1 000 mm au pas
        # courant demandait vingt mille passages d'un cercle de 1,4 m, que
        # le rognage à la matière ne finissait pas : le fichier figeait
        # TauDrive. Au-delà de `MAX_PASSAGES`, le tracé reste seul et la
        # vérification le dit ; en deçà, rien ne change.
        import time as _time_pa
        _demesure_pa = _PathEn(polylines=[_cercle_en(0, 0, 700, 720)],
                               recipe=PRESET_RECIPES[1],
                               line_width_mm=1000.0, line_step_mm=0.05,
                               line_side='inside')
        _t_pa = _time_pa.perf_counter()
        _seul_pa = _tp_en.local_polylines(_demesure_pa)
        _t_pa = _time_pa.perf_counter() - _t_pa
        _notes_pa = [_t for _n, _t in preflight.inspect(Document(
            name='epais', shapes=[_demesure_pa])).notes if 'trop épais' in _t]
        _juste_pa = _tp_en.local_polylines(_PathEn(
            polylines=[_cercle_en(0, 0, 5)], recipe=PRESET_RECIPES[1],
            line_width_mm=0.3, line_step_mm=0.05, line_side='inside'))
        check("épaisseur : au-delà de deux mille passages, le tracé reste "
              "seul et la vérification le dit (EX-261)",
              _t_pa < 5.0 and len(_seul_pa) == 1 and len(_notes_pa) == 1
              and len(_juste_pa) == 7
              and not _tp_en.thicken_too_large(20, 0.01)
              and _tp_en.thicken_too_large(20, 0.001),
              f'1 000 mm au pas de 0,05 : {len(_seul_pa)} tracé en '
              f'{_t_pa:.2f} s, {len(_notes_pa)} note · 0,3 mm : '
              f'{len(_juste_pa) - 1} passages')

        # Normalisation dense (EX-264). Les barres d'un code serrées à
        # quelques microns, puis épaissies : chaque passage ajouté a des
        # dizaines de rangés à portée, que `proches` éprouvait un à un. Au-
        # delà de `_EN_BLOC`, ils se jugent d'un bloc, par numpy — et la
        # sortie est celle du calcul un à un, au bit près : le bloc retient
        # tout ce que `_ecart_rang` retient, et ce qu'il garde de plus est
        # au milliardième de la marge, trop loin pour occuper quoi que ce
        # soit.
        import random as _rnd_dn
        import time as _time_dn
        import numpy as _np_dn
        _barres_dn = [[(_i * 0.003, 0.0), (_i * 0.003 + 0.0015, 0.0),
                       (_i * 0.003 + 0.0015, 0.6), (_i * 0.003, 0.6),
                       (_i * 0.003, 0.0)] for _i in range(40)]
        _t_dn = _time_dn.perf_counter()
        _bloc_dn = _tp_en.thicken(_barres_dn, 0.2, 0.05)
        _t_dn = _time_dn.perf_counter() - _t_dn
        _seuil_dn = _tp_en._EN_BLOC
        _tp_en._EN_BLOC = 10 ** 9
        try:
            _un_dn = _tp_en.thicken(_barres_dn, 0.2, 0.05)
        finally:
            _tp_en._EN_BLOC = _seuil_dn
        _hasard_dn = _rnd_dn.Random(264)
        _manques_dn = _trop_dn = _retenus_dn = 0
        for _ in range(300):
            _o = _hasard_dn.choice([0.0, 9000.0, -1234.5])
            _e = _hasard_dn.choice([1.0, 0.01, 50.0])

            def _pt_dn():
                return (_o + _hasard_dn.random() * _e,
                        _o + _hasard_dn.random() * _e)

            _ax, _ay = _pt_dn()
            _bx, _by = ((_ax, _ay) if _hasard_dn.random() < 0.1
                        else _pt_dn())
            _rangs_dn = []
            for _k in range(30):
                _g = _hasard_dn.random()
                _cx, _cy = _pt_dn()
                if _g < 0.2:
                    # point rangé, ou segment nul
                    _ex, _ey, _n = _cx, _cy, int(_g < 0.05)
                elif _g < 0.35:
                    # partant de [a, b] : touché, ou croisé
                    _t = _hasard_dn.random()
                    _cx, _cy = (_ax + (_bx - _ax) * _t,
                                _ay + (_by - _ay) * _t)
                    (_ex, _ey), _n = _pt_dn(), 3
                else:
                    (_ex, _ey), _n = _pt_dn(), 4
                _rangs_dn.append((_cx, _cy, _ex, _ey, _n,
                                  _math.hypot(_ex - _cx, _ey - _cy), _k))
            _marge_dn = _hasard_dn.uniform(0.01, 0.3) * _e
            _masque_dn = _tp_en._proches_en_bloc(
                _ax, _ay, _bx, _by,
                _np_dn.array([_r[:4] for _r in _rangs_dn]), _marge_dn)
            for _r, _m in zip(_rangs_dn, _masque_dn.tolist()):
                _d = _tp_en._ecart_rang(_ax, _ay, _bx, _by, _r)
                _manques_dn += _d < _marge_dn and not _m
                _trop_dn += _m and _d >= _marge_dn * (1 + 1e-6)
                _retenus_dn += _m
        check("normalisation dense : les rangés se jugent d'un bloc, la "
              "sortie est celle du calcul un à un (EX-264)",
              _bloc_dn == _un_dn and len(_bloc_dn) > len(_barres_dn)
              and _t_dn < 10.0 and _manques_dn == 0 and _trop_dn == 0
              and _retenus_dn > 0,
              f'40 barres au pas de 3 microns, épaissies de 0,2 mm : '
              f'{len(_bloc_dn)} tracés en {_t_dn:.2f} s, '
              f'{"les mêmes" if _bloc_dn == _un_dn else "AUTRES"} un à un · '
              f"{_retenus_dn} rangés retenus d'un bloc, {_manques_dn} "
              f'manqué(s), {_trop_dn} de trop')

        # --- la duree : allumages et SkyWrite comptes ----------------------
        #
        # Le modele est ajuste sur les trois mesures de l atelier ; ici ses
        # proprietes : beaucoup de petits traits vont plus vite lentement,
        # un long trait va plus vite vite, et la consigne est ecretee.
        _petits = [[(_i * 0.2, 0.0), (_i * 0.2 + 0.1, 0.0)]
                   for _i in range(400)]
        _long = [[(0.0, 0.0), (100.0, 0.0)]]
        _d = _tp_en.polylines_duration_s
        check('duree : sur de petits traits, 200 m/min est plus lent que 50',
              _d(_petits, 200000) > _d(_petits, 50000)
              and _d(_long, 200000) < _d(_long, 50000)
              and abs(_d(_petits, 500000) - _d(_petits, 200000)) < 1e-12,
              f'400 petits traits : {_d(_petits, 50000):.2f} s a 50, '
              f'{_d(_petits, 200000):.2f} s a 200 · un trait de 100 mm : '
              f'{_d(_long, 50000):.2f} s a 50, {_d(_long, 200000):.2f} s a 200')
        _v_best, _d_best = preflight.best_speed(_petits, 200000)
        check('duree : la vitesse la plus rapide pour un dessin se calcule',
              _v_best < 200000 and _d_best < _d(_petits, 200000)
              and _tp_en.ACCEL_MM_S2 == 1.5e6
              and _tp_en.SPEED_MAX_MM_MIN == 200000,
              f'{_v_best / 1000:g} m/min, {_d_best:.2f} s · modele : '
              f'{_tp_en.ACCEL_MM_S2 / 1000:g} m/s2, '
              f'{_tp_en.LASER_ON_WAIT_S * 1000:g} ms par allumage')

        # la verification avant export le dit, chiffre
        _nb_petits = Document(name='petits', shapes=[_PathEn(
            polylines=[[(_i * 0.2 - 40, (_i % 20) * 0.5), (_i * 0.2 - 39.9,
                        (_i % 20) * 0.5)] for _i in range(400)],
            recipe=dataclasses.replace(PRESET_RECIPES[1], hatch_mm=0.0,
                                       speed_mm_min=200000.0))])
        _rap_v = preflight.inspect(_nb_petits, optimize=True)
        from engrave import codeplate as _cp_vf
        _rap_l = preflight.inspect(_doc_en.__class__(
            name='plaque', shapes=_cp_vf.build_plate(dataclasses.replace(
                PRESET_RECIPES[1], hatch_mm=0.05))), optimize=True)
        # un gain d allumages sans gain de temps ne se conseille pas : une
        # bande penchee a 45°, dont chaque demi-tour de zigzag est un
        # virage SkyWrite — les anneaux, eux, s y conseillent
        _bande_vf = _PathEn(polylines=[[(-20, -20), (-19, -20), (21, 20),
                                        (20, 20), (-20, -20)]],
                            recipe=dataclasses.replace(
                                PRESET_RECIPES[1], name='bande',
                                hatch_mm=0.05))
        _rap_neg = preflight.inspect(Document(name='bande',
                                              shapes=[_bande_vf]),
                                     optimize=True)
        _vain_vf = [_t for _, _t in _rap_neg.notes
                    if 'Enchaîner les tracés' in _t]
        _vain_vf += ([] if any('anneaux' in _t for _, _t in _rap_neg.notes)
                     else ['pas de conseil d anneaux'])
        check('verification : elle chiffre la vitesse et l enchainement',
              any('m/min' in _t and 'allumages' in _t
                  for _, _t in _rap_v.notes)
              and any('Enchaîner les tracés' in _t for _, _t in _rap_l.notes)
              and not _vain_vf,
              'vitesse plus lente proposee · enchainement chiffre sur la '
              'plaque · rien quand il ne fait pas gagner de temps, '
              'les anneaux a la place')

        # et les anneaux, quand ils font gagner — quatre disques penches
        _disques = [_cercle_en(_k * 9.0 - 13.5, 0, 4) for _k in range(4)]
        _rap_an = preflight.inspect(Document(name='disques', shapes=[_PathEn(
            polylines=_disques, recipe=dataclasses.replace(
                PRESET_RECIPES[1], hatch_mm=0.05, speed_mm_min=80000.0))]),
            optimize=True)
        _note_an = [_t for _, _t in _rap_an.notes if 'anneaux' in _t]
        check('verification : elle chiffre le remplissage en anneaux',
              len(_note_an) == 1 and 'coupon' in _note_an[0],
              _note_an[0][:110] if _note_an else 'aucune note')

        _base = dataclasses.replace(PRESET_RECIPES[1], hatch_mm=0.2, passes=1)

        def _mesure(**kw):
            f = Rect(width=10, height=10,
                     recipe=dataclasses.replace(_base, **kw))
            p = _bsp(f)
            return len(p.polylines), p.length_mm()

        _simple = _mesure()
        _croise = _mesure(hatch_cross=True)
        _retrait = _mesure(hatch_inset_mm=0.5)
        check('remplissage : croisé double la nappe, retrait la resserre',
              _croise[1] > _simple[1] * 1.8
              and _retrait[1] < _simple[1]
              and _simple[1] > 0,
              f'{_simple[1]:.0f} → croisé {_croise[1]:.0f} → '
              f'retrait {_retrait[1]:.0f} mm')

        _doc_r = Document()
        _doc_r.add(Rect(width=10, height=10,
                        recipe=dataclasses.replace(_base, hatch_mm=0.3, passes=3,
                                                   hatch_angle_step_deg=60)))
        _tours = build_passes(_doc_r)
        _doc_f = Document()
        _doc_f.add(Rect(width=10, height=10,
                        recipe=dataclasses.replace(_base, hatch_mm=0.3,
                                                   passes=3)))
        _fixes = build_passes(_doc_f)
        check('remplissage : la rotation par passe change la géométrie',
              len({len(p.polylines) for p in _tours}) > 1
              and len({len(p.polylines) for p in _fixes}) == 1
              and len(_tours) == 3,
              f'tournant {[len(p.polylines) for p in _tours]} · '
              f'fixe {[len(p.polylines) for p in _fixes]}')

        _droit = [(0.0, 0.0), (50.0, 0.0)]
        _osc = _wob.apply_polyline(_droit, 0.1, 0.4, 'circle')
        _largeur = max(y for _, y in _osc) - min(y for _, y in _osc)
        check('oscillation : la bande fait deux fois l' + chr(39) + 'amplitude',
              abs(_largeur - 0.2) < 1e-6 and len(_osc) > 100,
              f'{_largeur:.3f} mm sur {len(_osc)} points')
        check('oscillation : les bouts restent sur le tracé',
              _osc[0] == (0.0, 0.0) and _osc[-1] == (50.0, 0.0),
              'contour refermable')
        _carre = _wob.apply_polyline(_geo.rect_contour(10, 6), 0.08, 0.4)
        check('oscillation : un contour fermé le reste',
              _carre[0] == _carre[-1], 'fermé')

        # la phase suit la longueur parcourue, non le paramètre du segment :
        # deux segments de longueurs très différentes reçoivent la même densité
        _court = _wob.apply_polyline([(0.0, 0.0), (1.0, 0.0)], 0.1, 0.4)
        _long = _wob.apply_polyline([(0.0, 0.0), (20.0, 0.0)], 0.1, 0.4)
        _d_court = len(_court) / 1.0
        _d_long = len(_long) / 20.0
        check('oscillation : la densité ne dépend pas de la longueur du segment',
              abs(_d_court - _d_long) / _d_long < 0.2,
              f'{_d_court:.0f} vs {_d_long:.0f} points/mm')

        _pire = 0.0
        for _f in ('circle', 'eight', 'transverse'):
            for _a, _p in ((0.1, 0.5), (0.2, 0.4), (0.05, 0.3)):
                _o = _wob.apply_polyline(_droit, _a, _p, _f)
                _reel = sum(_math.dist(x, y)
                            for x, y in zip(_o, _o[1:])) / 50.0
                _pire = max(_pire,
                            abs(_wob.length_factor(_a, _p, _f) - _reel) / _reel)
        check('oscillation : le facteur de longueur annoncé est mesuré',
              _pire < 0.10, f'écart maximal {_pire * 100:.1f} %')

        check('oscillation : la cadence du scanner est calculée et bornée',
              abs(_wob.scanner_hz(80000, 0.1) - 13333) < 2
              and _wob.max_speed_mm_min(0.1) == 3000
              and any(n[0] == 'bloquant'
                      for n in _wob.check(80000, 0.1, 0.1, 'circle'))
              and not _wob.check(3000, 0.1, 0.1, 'circle'),
              f'{_wob.scanner_hz(80000, 0.1):.0f} Hz à 80 m/min, pas 0,1 mm')

        _doc_w = Document()
        _doc_w.add(Rect(width=10, height=10, recipe=dataclasses.replace(
            _base, wobble='circle', wobble_amp_mm=0.1, wobble_pitch_mm=0.1,
            speed_mm_min=80000)))
        _notes_w = preflight.inspect(_doc_w).blocking()
        check('oscillation : la vérification avant export refuse l' + chr(39)
              + 'infaisable',
              any('scanner' in n for n in _notes_w),
              _notes_w[0][:60] if _notes_w else 'aucune note')

        # audit des recommandations
        _verdicts = _adv.audited()
        _tenus = [v for v in _verdicts if v.level == _adv.TENU]
        check('recommandations : auditées contre la table de la source',
              len(_verdicts) == 7 and len(_tenus) == 3
              and not any(v.level == _adv.REFUSE for v in _verdicts)
              and all(_adv.audit(_adv.corrected(v.advice)).level == _adv.TENU
                      for v in _verdicts if _adv.corrected(v.advice)),
              f'{len(_tenus)} tenues sur {len(_verdicts)}, '
              f'les autres rabattues sur un couple réel')
        check('recommandations : hors table = réserve, hors physique = refus',
              _adv.audit(_adv.Advice('e', 'x', 180, 30, 600)).level
              == _adv.RESERVE
              and _adv.audit(_adv.Advice('e', 'x', 135, 30, 600)).level
              == _adv.TENU
              and _adv.audit(_adv.Advice('e', 'x', 100, 900, 600)).level
              == _adv.REFUSE
              and _adv.audit(_adv.Advice('e', 'x', 1000, 300, 600)).level
              == _adv.REFUSE,
              '180-30 réserve · 135-30 tenu · 900 ns et 30 % refusés')
        check('recommandations : le magasin sert de contre-épreuve à la table',
              _adv.observed_max(30) == 450.0 and _adv.observed_max(20) == 500.0
              and any('magasin' in n for n in
                      _adv.audit(_adv.Advice('e', 'x', 180, 30, 600)).notes),
              f'30 ns : table 135 kHz, magasin {_adv.observed_max(30):g} kHz')
        check('recommandations : le pas d' + chr(39) + 'impulsion est mesuré',
              abs(_adv.Advice('e', 'x', 80, 100, 1200).pitch_mm() - 0.015) < 1e-9
              and abs(_adv.Advice('e', 'x', 80, 100, 1200).overlap() - 2.0) < 1e-9,
              'spot 0,03 mm, recouvrement 2x')

        from engrave.guide import Guide as _Guide
        _guide = _Guide(window)
        _pages = [_guide.w_tabs.widget(i).toPlainText()
                  for i in range(_guide.w_tabs.count())]
        check('guide : trois pages, nourries des données du programme',
              len(_pages) == 3 and all(len(t) > 1500 for t in _pages)
              and '37-500' in _pages[1] or '500' in _pages[1],
              ' · '.join(_guide.w_tabs.tabText(i)
                         for i in range(_guide.w_tabs.count())))
        check('guide : l' + chr(39) + 'audit y figure, refus compris',
              'refusé' in _pages[1] and 'tenu' in _pages[1]
              and 'scanner' in _pages[2],
              f'{len(_pages[1])} caractères sur la source')
        _guide.deleteLater()
        check('guide : ouvert par le bouton « ? » du gestionnaire de process',
              window.recipes_panel.w_guide.text() == '?'
              and hasattr(window.recipes_panel, '_open_guide'),
              'bouton en tête de la barre du gestionnaire')
        # Le bouton « ? » était posé deux fois de suite dans la même barre :
        # deux points d'interrogation côte à côte, ouvrant le même guide.
        from PySide6.QtWidgets import QPushButton as _QPushButton
        _barre = window.recipes_panel.w_done.parentWidget()
        _interro = [b for b in _barre.findChildren(_QPushButton)
                    if b.text() == '?' and b.parentWidget() is _barre]
        check('gestionnaire de process : un seul bouton « ? »',
              len(_interro) == 1, f'{len(_interro)} bouton(s)')

        # --- coupon : couples F-T et motif des cases ----------------------------

        from engrave import couples as _couples
        from engrave.coupon import CouponDialog
        from engrave.model import Path as PathShape

        table = _couples.factory()
        check('couples : les treize formes d' + chr(39) + 'onde de la source',
              [c.key() for c in table]
              == ['1300-2', '375-9', '250-13', '170-20', '135-30', '110-45',
                  '100-60', '90-80', '80-100', '37-200', '37-250', '37-350',
                  '37-500']
              and all(c.origin == 'constructeur' for c in table),
              f'{len(table)} couples · '
              + ' '.join(c.key() for c in table[:4]) + ' …')
        check('couples : la table est cohérente, aucun rapport cyclique '
              'aberrant',
              all(c.duty_percent() < 5.0 for c in table)
              and all(a.pulse_width_ns < b.pulse_width_ns
                      for a, b in zip(table, table[1:]))
              and all(a.frequency_khz >= b.frequency_khz
                      for a, b in zip(table, table[1:])),
              f'{min(c.duty_percent() for c in table):.2f} % → '
              f'{max(c.duty_percent() for c in table):.2f} %')
        check('couples : « 1300-2 », « 1300/2 » et « 1300 2 » se lisent pareil',
              _couples.parse('1300-2') == _couples.parse('1300/2')
              == _couples.parse('1300 2')
              and _couples.parse('1300-2').values()
              == {'frequency_khz': 1300.0, 'pulse_width_ns': 2}
              and _couples.parse('nawak') is None,
              _couples.parse('1300-2').key())
        magasin = _couples.from_magazine()
        check('couples : ceux du magasin se récoltent, ils ont gravé',
              len(magasin) == 15 and all(c.origin == 'magasin' for c in magasin),
              f'{len(magasin)} couple(s) dans le magasin d essai')
        check('couples : table seule en mode normal, et en expert sans atelier',
              len(_couples.available(False)) == len(table)
              and len(_couples.available(True))
              == len(table) + len([c for c in _couples.custom()
                                   if c.key() not in {t.key() for t in table}]),
              f'{len(_couples.available(False))} → '
              f'{len(_couples.available(True))}')
        check('couples : aucun couple d' + chr(39) + 'atelier au cœur libre',
              _couples.workshop() == [] and _couples.WORKSHOP == (),
              'le plugin de l atelier les apporte, a son nom')

        trois_c = table[:3]
        grille_c = coupon.build(
            PRESET_RECIPES[1], x_field='couple',
            x_couples=[c.key() for c in trois_c],
            y_field='power_percent', y_from=40, y_to=100, y_count=2)
        cases_c = [f for f in grille_c if isinstance(f, Rect)]
        reglages_c = {(f.recipe.frequency_khz, f.recipe.pulse_width_ns)
                      for f in cases_c}
        check('coupon : un couple pose fréquence **et** impulsion d' + chr(39)
              + 'un bloc',
              len(cases_c) == 6
              and reglages_c == {(1300.0, 2), (375.0, 9), (250.0, 13)}
              and any('1300-2' in f.name for f in cases_c),
              ' · '.join(sorted(f'{f:g}-{t:g}' for f, t in reglages_c)))

        fenetre_c = CouponDialog(window, PRESET_RECIPES[1], list(PRESET_RECIPES),
                                 expert=True)
        rang_c = fenetre_c.w_x.w_field.findData('couple')
        fenetre_c.w_x.w_field.setCurrentIndex(rang_c)
        app.processEvents()
        check('coupon : l' + chr(39) + 'axe des couples remplace les bornes par '
              'la table',
              rang_c >= 0 and fenetre_c.w_x.w_couples.isVisibleTo(fenetre_c)
              and not fenetre_c.w_x.w_from.isVisibleTo(fenetre_c)
              and len(fenetre_c.w_x.couples())
              == len(_couples.available(True)),
              f'{len(fenetre_c.w_x.couples())} couples cochés')
        check('coupon : gestionnaire des couples réservé au mode expert',
              fenetre_c.w_x.w_manage.isEnabled(),
              'expert : ouvert')
        fenetre_c.deleteLater()

        fenetre_n = CouponDialog(window, PRESET_RECIPES[1], list(PRESET_RECIPES),
                                 expert=False)
        fenetre_n.w_x.w_field.setCurrentIndex(
            fenetre_n.w_x.w_field.findData('couple'))
        app.processEvents()
        check('coupon : en mode normal, table constructeur et rien d' + chr(39)
              + 'autre',
              not fenetre_n.w_x.w_manage.isEnabled()
              and fenetre_n.w_x.w_couples.count() == len(table)
              and fenetre_n.w_x.w_field.findData('frequency_khz') < 0,
              f'{fenetre_n.w_x.w_couples.count()} couple(s), sans gestionnaire')
        fenetre_n.deleteLater()

        gestionnaire = _couples.CoupleManager(window)
        avant_c = len(gestionnaire._couples)
        gestionnaire.w_f.setValue(600)
        gestionnaire.w_t.setValue(14)
        gestionnaire._add()
        plein = gestionnaire.w_list.count()
        gestionnaire._harvest()
        apres_c = len(gestionnaire._couples)
        check('couples : le gestionnaire ajoute, récolte et protège la table',
              apres_c > avant_c + 1 and plein > len(table)
              and all(c.origin == 'poste' for c in gestionnaire._couples),
              f'{avant_c} → {apres_c} couple(s) du poste')
        check('couples : un rapport cyclique élevé est signalé',
              _couples.Couple(1000, 250).duty_percent() > 5.0
              and _couples.Couple(80, 20).duty_percent() < 1.0,
              f'1000-250 : {_couples.Couple(1000, 250).duty_percent():.0f} %')
        gestionnaire.reject()
        gestionnaire.deleteLater()

        # motif : la case grave le dessin réel, pas un carré
        motif_essai = coupon.motif_from_shapes(
            [Text(text='AB', size_mm=6, recipe=PRESET_RECIPES[1])])
        check('coupon : une sélection devient le motif des cases',
              len(motif_essai) >= 2
              and abs(sum(x for poly in motif_essai for x, _ in poly)
                      / max(1, sum(len(p) for p in motif_essai))) < 5.0,
              f'{len(motif_essai)} tracé(s), centré')
        grille_m = coupon.build(PRESET_RECIPES[1], motif=motif_essai,
                                x_field='power_percent', x_from=40, x_to=100,
                                x_count=3, y_field='', cell_mm=8.0)
        cases_m = [f for f in grille_m if isinstance(f, PathShape)]
        larg_m = coupon.motif_size(cases_m[0].polylines)[0] if cases_m else 0
        check('coupon : le motif est ajusté à la case sans être étiré',
              len(cases_m) == 3 and larg_m <= 8.0 * coupon.MOTIF_FILL + 1e-6
              and not any(isinstance(f, Rect) for f in grille_m),
              f'{len(cases_m)} case(s), motif {larg_m:.2f} mm dans 8 mm')

        fenetre_m = CouponDialog(window, PRESET_RECIPES[1], list(PRESET_RECIPES),
                                 expert=True, motif=motif_essai)
        porte_motif = any(isinstance(f, PathShape) for f in fenetre_m.shapes())
        fenetre_m._drop_motif()
        check('coupon : le motif se règle et se retire dans le formulaire',
              porte_motif
              and any(isinstance(f, Rect) for f in fenetre_m.shapes())
              and 'carré' in fenetre_m.w_motif.text(),
              fenetre_m.w_motif.text()[:44])
        fenetre_m.deleteLater()

        # `inspect.getsource` ne peut rien lire d'un binaire figé — aucun code
        # source n'est distribué. Le contrôle porte donc sur le comportement :
        # sans sélection, la commande refuse et le dit ; avec, elle donne un
        # motif.
        window.canvas.select_many([])
        window._coupon_from_selection()
        refus = window.statusBar().currentMessage()
        motif_menu = coupon.motif_from_shapes(
            [Text(text='Z', size_mm=4, recipe=PRESET_RECIPES[1])])
        check('coupon : le clic droit d' + chr(39) + 'une forme en fait un coupon',
              hasattr(window, '_coupon_from_selection')
              and 'lectionnez' in refus and bool(motif_menu),
              refus[:52] or 'sans message')

        # --- propriétés du lot --------------------------------------------------

        from engrave import lot as _lot
        doc_lot = Document(name='Lot')
        onglet_lot = window.new_tab(doc_lot)
        app.processEvents()
        ids_lot = [doc_lot.add(Rect(x=10 + 20 * i, y=10, width=8, height=6,
                                    recipe=PRESET_RECIPES[1])).id
                   for i in range(3)]
        onglet_lot.reload()
        window._refresh_list()
        onglet_lot.select_many(ids_lot)
        app.processEvents()
        check('lot : plusieurs formes ouvrent le formulaire de lot',
              window._insp_stack.currentIndex() == 1
              and '3 formes' in window.lot.w_title.text(),
              window.lot.w_title.text()[:60])

        formes_lot = [doc_lot.get(i) for i in ids_lot]
        check('lot : centre, cotes et nombre de formes affichés',
              abs(window.lot.w_cx.value() - 30.0) < 1e-6
              and abs(window.lot.w_dx.value() - 48.0) < 1e-6
              and abs(window.lot.w_dy.value() - 6.0) < 1e-6
              and window.lot.w_count.text() == '3',
              f'centre {window.lot.w_cx.value():g} · '
              f'{window.lot.w_dx.value():g} × {window.lot.w_dy.value():g} mm')

        window.lot.w_cx.setValue(0.0)
        app.processEvents()
        check('lot : le centre déplace tout le lot d' + chr(39) + 'un bloc',
              abs(_lot.resize.selection_center(formes_lot)[0]) < 1e-6
              and abs((formes_lot[2].x - formes_lot[0].x) - 40.0) < 1e-6,
              f'centre {_lot.resize.selection_center(formes_lot)[0]:g} mm')

        window.lot.w_keep.setChecked(True)
        window.lot.w_dx.setValue(96.0)
        app.processEvents()
        largeur, hauteur = _lot.resize.selection_size(formes_lot)
        check('lot : les cotes mettent à l' + chr(39) + 'échelle, proportions tenues',
              abs(largeur - 96.0) < 0.01 and abs(hauteur - 12.0) < 0.01,
              f'{largeur:.2f} × {hauteur:.2f} mm')

        formes_lot[0].recipe = PRESET_RECIPES[0]
        window.lot.set_lot(formes_lot, doc_lot)
        melee = _lot.common_recipe(formes_lot) is None
        window.lot.set_recipes(list(PRESET_RECIPES))
        window.lot.set_lot(formes_lot, doc_lot)
        window.lot.w_recipe.setCurrentIndex(
            window.lot.w_recipe.findText(
                f'T{PRESET_RECIPES[2].tool_number} · {PRESET_RECIPES[2].name}'))
        window.lot._apply_recipe()
        app.processEvents()
        check('lot : une process s' + chr(39) + 'applique à toutes les formes',
              melee and {f.recipe.name for f in formes_lot}
              == {PRESET_RECIPES[2].name}
              and _lot.common_recipe(formes_lot) is not None,
              f'mêlée → {PRESET_RECIPES[2].name}')

        window.lot.w_offset.setValue(0.25)
        window.lot.w_margin.setValue(3.0)
        app.processEvents()
        check('lot : cadre, marge et décalage communs appliqués à tous',
              all(abs(f.frame_offset_mm - 0.25) < 1e-9 for f in formes_lot)
              and all(abs(f.frame_margin_mm - 3.0) < 1e-9 for f in formes_lot),
              f'décalage {formes_lot[0].frame_offset_mm:g} mm · '
              f'marge {formes_lot[0].frame_margin_mm:g} mm')

        longueur_lot, duree_lot = _lot.measure(formes_lot, doc_lot)
        check('lot : longueur gravée et durée mesurées comme à l' + chr(39)
              + 'export',
              longueur_lot > 0 and duree_lot > 0
              and window.lot.w_length.text().strip() != ''
              and window.lot.w_time.text().strip() != '',
              f'{longueur_lot:.0f} mm · {window.lot.w_time.text()}')

        # disposer : aligner, répartir, centrer — un groupe bouge d'un bloc
        from engrave import disposition as _disp
        _a_d = doc_lot.add(Rect(x=-30, y=4, width=10, height=4,
                                recipe=PRESET_RECIPES[1]))
        _g1_d = doc_lot.add(Rect(x=0, y=-3, width=6, height=8,
                                 recipe=PRESET_RECIPES[1]))
        _g2_d = doc_lot.add(Rect(x=9, y=-3, width=2, height=2,
                                 recipe=PRESET_RECIPES[1]))
        _c_d = doc_lot.add(Rect(x=40, y=12, width=4, height=2,
                                recipe=PRESET_RECIPES[1]))
        doc_lot.group([_g1_d.id, _g2_d.id])
        onglet_lot.reload()
        _ids_d = [_a_d.id, _g1_d.id, _g2_d.id, _c_d.id]
        onglet_lot.select_many(_ids_d)
        app.processEvents()
        _ecart_g = _g2_d.x - _g1_d.x
        window.lot.w_align['gauche'].click()
        app.processEvents()
        _gauches = [round(_s.x - _s.width / 2, 6) for _s in (_a_d, _g1_d,
                                                              _c_d)]
        window.lot.w_align['haut'].click()
        app.processEvents()
        _hauts = [round(_s.y + _s.height / 2, 6) for _s in (_a_d, _g1_d,
                                                             _c_d)]
        check('disposer : aligner à gauche, en haut — le groupe d' + chr(39)
              + 'un bloc',
              len(set(_gauches)) == 1 and len(set(_hauts)) == 1
              and abs((_g2_d.x - _g1_d.x) - _ecart_g) < 1e-9,
              f'bords gauches {_gauches} · hauts {_hauts}')

        _a_d.x, _g1_d.x, _g2_d.x, _c_d.x = -30.0, 2.0, 11.0, 40.0
        onglet_lot.reload()
        onglet_lot.select_many(_ids_d)
        app.processEvents()
        window.lot.w_spread_x.click()
        app.processEvents()
        _bords = sorted((_disp._emprise(_b) for _b in _disp.blocs(
            [_a_d, _g1_d, _g2_d, _c_d])), key=lambda _e: _e[0])
        _espaces = [round(_bords[_k + 1][0] - _bords[_k][2], 6)
                    for _k in range(len(_bords) - 1)]
        window.lot.w_center.click()
        app.processEvents()
        _cx_d, _cy_d = _lot.resize.selection_center([_a_d, _g1_d, _g2_d,
                                                     _c_d])
        window.lot.w_center.click()
        app.processEvents()
        # le résumé dû ensuite attend la fin du message (NoteBar)
        window._status_due()
        check('disposer : répartir égalise les espaces, centrer pose au '
              'milieu du champ',
              len(set(_espaces)) == 1 and _bords[0][0] == -35.0
              and abs(_cx_d) < 1e-9 and abs(_cy_d) < 1e-9
              and 'rien n' in window.statusBar().currentMessage(),
              f'espaces {_espaces} · centre ({_cx_d:g}, {_cy_d:g}) · '
              f'« {window.statusBar().currentMessage()} »')
        _seul_g = _disp.blocs([_g1_d, _g2_d])
        check('disposer : un groupe seul se dispose membre par membre',
              len(_seul_g) == 2 and _disp.aligner([_g1_d, _g2_d], 'bas') == 1
              and abs((_g1_d.y - _g1_d.height / 2)
                      - (_g2_d.y - _g2_d.height / 2)) < 1e-9,
              f'{len(_seul_g)} blocs pour un groupe de deux')
        onglet_lot.select_many(ids_lot)
        app.processEvents()

        # répéter en grille : une plaque par case, chacune son groupe
        from engrave import repetition as _rep
        from engrave.model import Code as _Code_r
        _doc_r = Document(name='Grille')
        _code_r = _doc_r.add(_Code_r(kind='datamatrix', data='B1',
                                     module_mm=0.4,
                                     recipe=PRESET_RECIPES[1]))
        _txt_r = _doc_r.add(Text(text='B1', size_mm=2, y=-4,
                                 recipe=PRESET_RECIPES[1]))
        _txt_r.follows = _code_r.id
        _doc_r.group([_code_r.id, _txt_r.id])
        _seul_r = _doc_r.add(Rect(width=5, height=3, x=30,
                                  recipe=PRESET_RECIPES[1]))
        _copies_r = _rep.repeter(_doc_r, [_txt_r, _code_r], 3, 2, 12.0, 9.0)
        _codes_r = [_f for _f in _doc_r.shapes if isinstance(_f, _Code_r)]
        _textes_r = [_f for _f in _doc_r.shapes if isinstance(_f, Text)]
        _places_r = sorted((round(_f.x, 6), round(_f.y, 6))
                           for _f in _codes_r)
        _seuls_r = _rep.repeter(_doc_r, [_seul_r], 2, 1, 10.0, 10.0)
        check('grille : une plaque par case, chacune son groupe et son code',
              len(_copies_r) == 10
              and len({_f.group for _f in _codes_r}) == 6
              and all(any(_c.id == _t.follows and _c.group == _t.group
                          for _c in _codes_r) for _t in _textes_r)
              and _places_r == [(0.0, -9.0), (0.0, 0.0), (12.0, -9.0),
                                (12.0, 0.0), (24.0, -9.0), (24.0, 0.0)]
              and [type(_f).__name__ for _f in _copies_r[:2]]
              == ['Code', 'Text']
              and not _seuls_r[0].group,
              f'{len(_copies_r)} copies · {len({_f.group for _f in _codes_r})}'
              f' groupes · codes en {_places_r}')
        _dlg_r = _rep.RepetitionDialog(None, [_code_r, _txt_r], _doc_r)
        _dlg_r.w_cols.setValue(4)
        _dlg_r.w_rows.setValue(3)
        _note_r = _dlg_r.w_note.text()
        _ok_r = _dlg_r.w_buttons.button(
            _dlg_r.w_buttons.StandardButton.Ok).isEnabled()
        _dlg_r.w_cols.setValue(50)
        _dlg_r.w_rows.setValue(20)
        _trop_r = not _dlg_r.w_buttons.button(
            _dlg_r.w_buttons.StandardButton.Ok).isEnabled()
        _dlg_r.w_cols.setValue(30)
        _dlg_r.w_rows.setValue(2)
        _hors_r = 'sort du champ' in _dlg_r.w_note.text()
        _dlg_r.deleteLater()
        check('grille : le formulaire compte, cote, et refuse l' + chr(39)
              + 'impossible',
              '12 case(s)' in _note_r and _ok_r and _trop_r and _hors_r,
              _note_r.replace('<b>', '').replace('</b>', ''))

        # répéter en cercle : graduations d'un cadran, plaques autour d'un axe
        import math as _math_o
        _doc_o = Document(name='cercle')
        _trait_o = _doc_o.add(Rect(width=0.3, height=3.0, x=0.0, y=20.0,
                                   recipe=PRESET_RECIPES[1]))
        _code_o = _doc_o.add(_Code_r(kind='datamatrix', data='C1',
                                           module_mm=0.3, x=30.0, y=0.0,
                                           recipe=PRESET_RECIPES[1]))
        _txt_o = _doc_o.add(Text(text='C1', size_mm=1.5, x=30.0, y=-3.0,
                                 recipe=PRESET_RECIPES[1]))
        _txt_o.follows = _code_o.id
        _doc_o.group([_code_o.id, _txt_o.id])
        _grad_o = _rep.repeter_en_cercle(_doc_o, [_trait_o], 60)
        _pos_ok = all(
            abs(_math_o.hypot(_c.x, _c.y) - 20.0) < 1e-9
            and abs((_math_o.degrees(_math_o.atan2(_c.y, _c.x)) - 90.0
                     - _c.rotation_deg + 540.0) % 360.0 - 180.0) < 1e-6
            for _c in _grad_o)
        _plaques_o = _rep.repeter_en_cercle(_doc_o, [_code_o, _txt_o], 4,
                                            angle_deg=-90.0, orienter=False)
        _codes_o = [_c for _c in _plaques_o
                    if isinstance(_c, _Code_r)]
        _textes_o = [_c for _c in _plaques_o if isinstance(_c, Text)]
        _groupes_o = {_c.group for _c in _plaques_o}
        check('cercle : soixante graduations au pas de 6°, plaques en arc '
              'qui suivent leur code',
              len(_grad_o) == 59 and _pos_ok
              and _rep.angles_cercle(60)[1] == 6.0
              and _rep.angles_cercle(4, -90.0) == [0.0, -30.0, -60.0, -90.0]
              and len(_codes_o) == 3 and len(_textes_o) == 3
              and all(_t.follows in {_c.id for _c in _codes_o}
                      for _t in _textes_o)
              and len(_groupes_o) == 3 and '' not in _groupes_o
              and all(_c.rotation_deg == 0.0 for _c in _plaques_o)
              and abs(_codes_o[-1].x) < 1e-9
              and abs(_codes_o[-1].y + 30.0) < 1e-9,
              f'{len(_grad_o)} copies · dernière plaque en '
              f'({_codes_o[-1].x:.1f}, {_codes_o[-1].y:.1f})')

        _dlg_o = _rep.CercleDialog(None, [_trait_o], _doc_o)
        _note_o = _dlg_o.w_note.text()
        _ok_o = _dlg_o.w_buttons.button(
            _dlg_o.w_buttons.StandardButton.Ok).isEnabled()
        _dlg_o.w_cx.setValue(-50.0)
        _hors_o = 'sort du champ' in _dlg_o.w_note.text()
        _dlg_o.w_angle.setValue(0.0)
        _nul_o = not _dlg_o.w_buttons.button(
            _dlg_o.w_buttons.StandardButton.Ok).isEnabled()
        _dlg_o.deleteLater()
        _env_o = _rep.emprise_cercle([_trait_o], 4, 0.0, 0.0, 360.0, True)
        check('cercle : le formulaire dit pas et rayon, refuse l'
              + chr(39) + 'impossible',
              'pas 30°' in _note_o and 'rayon 20.0' in _note_o and _ok_o
              and _hors_o and _nul_o
              and abs(_env_o[3] - 21.5) < 1e-9
              and abs(_env_o[1] + 21.5) < 1e-9,
              _note_o.replace('<b>', '').replace('</b>', ''))

        # une planche de plaques n'est pas un montage : au-delà de
        # MAX_POSTES, la sélection va au lot
        from engrave import montage as _mtg_p
        def _plaques_p(_n):
            _formes = []
            for _i in range(_n):
                _c = _Code_r(kind='datamatrix', data=f'P{_i}',
                             module_mm=0.3, recipe=PRESET_RECIPES[1])
                _t = Text(text=f'P{_i}', recipe=PRESET_RECIPES[1])
                _t.follows = _c.id
                _formes += [_c, _t]
            return _formes
        check('montage : trois plaques en sont un, une planche de '
              f'{_mtg_p.MAX_POSTES + 1} non',
              _mtg_p.is_montage(_plaques_p(3))
              and _mtg_p.is_montage(_plaques_p(_mtg_p.MAX_POSTES))
              and not _mtg_p.is_montage(_plaques_p(_mtg_p.MAX_POSTES + 1)),
              'tout sélectionner sur trois cents plaques ouvre le lot')

        onglet_lot.select(ids_lot[0])
        app.processEvents()
        check('lot : une forme seule rend la main aux propriétés',
              window._insp_stack.currentIndex() == 0,
              f'pile {window._insp_stack.currentIndex()}')
        window._close_tab(window.tabs.indexOf(onglet_lot))
        app.processEvents()

        # --- bibliothèque de dessins -------------------------------------------

        from engrave import drawings
        from engrave import plugins as _pl_des
        _liv_autotest = _pl_des.REGISTRY.drawings_dir
        _pl_des.REGISTRY.drawings_dir = None
        try:
            _libres = [e for e in drawings.entries() if e.delivered]
            _dossier_libre = drawings.delivered_dir()
        finally:
            _pl_des.REGISTRY.drawings_dir = _liv_autotest
        check('bibliothèque : aucun dessin livré au cœur libre',
              not _libres, str(_dossier_libre))
        # ceux qu'un plugin livre : les dessins d'essai posés par l'autotest
        livres = [e for e in drawings.entries() if e.delivered]
        check('bibliothèque : les dessins livrés par un plugin paraissent',
              [e.name for e in livres] == ['Essai', 'Essai lourd'],
              ', '.join(e.name for e in livres) or str(_liv_autotest))
        if livres:
            formes = drawings.load(livres[0], recipe=PRESET_RECIPES[1])
            traces, emprise = drawings.preview(livres[0],
                                               recipe=PRESET_RECIPES[1])
            check('bibliothèque : un dessin livré se charge et s\'aperçoit',
                  bool(formes) and bool(traces) and emprise is not None,
                  f'{livres[0].name} · {len(traces)} tracé(s) · '
                  f'{emprise[2] - emprise[0]:.0f} × {emprise[3] - emprise[1]:.0f} mm'
                  if emprise else 'sans emprise')
            check('bibliothèque : un dessin livré est en lecture seule',
                  not livres[0].editable())

        # Un DXF qui se dit en mètres sans l'être arrivait de la
        # bibliothèque à 156 m de large, et perdait ses points au premier
        # « refaire » : au-delà de dix mètres, il est relu en millimètres.
        # Le dialogue d'import, lui, refuse plutôt que de perdre.
        import ezdxf as _ezdxf_b
        from engrave import sketch as _sk_b
        from engrave.dxfdialog import DxfImportDialog as _Dlg_b
        from engrave.geometry import bounds as _bornes_b
        from engrave.history import History as _Hist_b
        _dir_b = pathlib.Path(tempfile.mkdtemp())

        def _dxf_b(nom, unite, x0, lg, ht):
            _d = _ezdxf_b.new()
            _d.header['$INSUNITS'] = unite
            _d.modelspace().add_lwpolyline(
                [(x0, 0), (x0 + lg, 0), (x0 + lg, ht), (x0, ht)], close=True)
            _f = _dir_b / f'{nom}.dxf'
            _d.saveas(_f)
            return drawings.Entry(name=nom, path=_f, delivered=False)

        def _taille_b(polys):
            _b = _bornes_b(polys)
            return (round(_b[2] - _b[0], 3), round(_b[3] - _b[1], 3)) \
                if _b else None

        def _polys_b(formes):
            return [p for f in formes for p in f.polylines]

        _faux_b = _dxf_b('faux metres', 6, 0, 30, 10)
        _vrai_b = _dxf_b('vrais metres', 6, 0, 3, 1)
        _f_b = drawings.load(_faux_b, recipe=PRESET_RECIPES[1])
        _v_b = drawings.load(_vrai_b, recipe=PRESET_RECIPES[1])
        _doc_b = Document(name='biblio')
        _h_b = _Hist_b(_doc_b)
        for _s_b in _f_b:
            _doc_b.add(_s_b)
        _h_b.record(_doc_b)
        _h_b.undo()
        _refait_b = _h_b.redo()
        _loin_b = _dxf_b('loin', 4, 50000, 100, 20)
        _dlg_b = _Dlg_b(window, str(_loin_b.path), window.document,
                        PRESET_RECIPES[1])
        _dlg_b.w_center.setChecked(False)
        _refus_b = (not _dlg_b._ok.isEnabled()
                    and 'dix mètres' in _dlg_b.w_summary.text()
                    and 'Centrer' in _dlg_b.w_summary.text())
        _dlg_b.w_center.setChecked(True)
        _rendu_b = _dlg_b._ok.isEnabled()
        _dlg_b.deleteLater()
        check('bibliothèque : une unité déclarée invraisemblable est relue '
              'en millimètres',
              _taille_b(_polys_b(_f_b)) == (30.0, 10.0)
              and _taille_b(_sk_b.dxf_outline(_faux_b.path).polys)
              == (30.0, 10.0)
              and _taille_b(_polys_b(_v_b)) == (3000.0, 1000.0)
              and _taille_b(_sk_b.dxf_outline(_vrai_b.path).polys)
              == (3000.0, 1000.0)
              and _refait_b is not None
              and len(_polys_b(_refait_b.shapes)) == len(_polys_b(_f_b))
              and _refus_b and _rendu_b,
              f'30 m déclarés → {_taille_b(_polys_b(_f_b))} mm · '
              f'3 m → {_taille_b(_polys_b(_v_b))} mm · refaire : '
              f'{len(_polys_b(_refait_b.shapes)) if _refait_b else 0} tracé(s)'
              f' · dialogue loin de l\'origine refusé {_refus_b}, '
              f'centré accepté {_rendu_b}')

        # Relecture d'EX-251 (EX-256). « Centrer » centre les calques
        # retenus : un calque choisi seul, loin des autres, était refusé
        # en conseillant une case déjà cochée. Un DXF en mils arrivait
        # 25 fois trop petit. Un dessin déjà lu en millimètres n'est pas
        # relu pour rien, et une vignette d'avant EX-251 n'est pas reprise.
        from PySide6.QtCore import Qt as _Qt_r
        from engrave import dxfimport as _dxi_r, thumbs as _th_r
        import hashlib as _hash_r
        _d_r = _ezdxf_b.new()
        _d_r.header['$INSUNITS'] = 4
        for _calque_r, _x_r in (('A', 0.0), ('B', 30000.0)):
            _d_r.modelspace().add_lwpolyline(
                [(_x_r, 0), (_x_r + 10, 0), (_x_r + 10, 10), (_x_r, 10)],
                close=True, dxfattribs={'layer': _calque_r})
        _f_r = _dir_b / 'deux calques.dxf'
        _d_r.saveas(_f_r)
        _dlg_r = _Dlg_b(window, str(_f_r), window.document,
                        PRESET_RECIPES[1])
        for _i_r in range(_dlg_r.w_layers.count()):
            _it_r = _dlg_r.w_layers.item(_i_r)
            if _it_r.data(_Qt_r.UserRole) == 'A':
                _it_r.setCheckState(_Qt_r.Unchecked)
        _dlg_r._update_summary()
        _seul_r = _bornes_b(_polys_b(_dlg_r.selected_shapes()))
        _ok_r = _dlg_r._ok.isEnabled()
        _dlg_r.deleteLater()
        _mils_r = _taille_b(_polys_b(drawings.load(
            _dxf_b('mils', 9, 0, 1000, 500), recipe=PRESET_RECIPES[1])))
        _lectures_r = []
        _lire_r = _dxi_r.any_to_shapes

        def _compte_r(*a, **k):
            _lectures_r.append(k.get('units_mm'))
            return _lire_r(*a, **k)
        _immense_r = _dxf_b('immense', 4, 0, 30000, 10)
        _dxi_r.any_to_shapes = _compte_r
        try:
            drawings.load(_immense_r, recipe=PRESET_RECIPES[1])
            _refus_mm_r = False
        except ValueError:
            _refus_mm_r = True
        finally:
            _dxi_r.any_to_shapes = _lire_r
        _etat_r = _f_r.stat()
        _ancienne_r = _hash_r.sha1(
            f'{_f_r.resolve()}|{int(_etat_r.st_mtime)}|{_etat_r.st_size}'
            .encode('utf-8')).hexdigest()[:20]
        check('import : un calque seul se centre, les mils sont des mils',
              _ok_r and _seul_r is not None
              and abs(_seul_r[0] + _seul_r[2]) < 1e-6
              and abs(_seul_r[1] + _seul_r[3]) < 1e-6
              and _taille_b([[(_seul_r[0], _seul_r[1]),
                              (_seul_r[2], _seul_r[3])]]) == (10.0, 10.0)
              and _mils_r == (25.4, 12.7)
              and _dxi_r.INSUNITS_TO_MM[8] == 2.54e-5
              and _dxi_r.INSUNITS_TO_MM[13] == 1e-3
              and _sk_b.INSUNITS_TO_MM is _dxi_r.INSUNITS_TO_MM
              and _refus_mm_r and len(_lectures_r) == 1
              and _th_r.key_for(_f_r) != _ancienne_r,
              f'calque B seul : OK {_ok_r}, emprise {_seul_r} · 1000 × 500 '
              f'mils → {_mils_r} mm · {len(_lectures_r)} lecture(s) d\'un '
              f'DXF en mm trop loin · vignette d\'avant écartée '
              f'{_th_r.key_for(_f_r) != _ancienne_r}')

        # Banc de documents au hasard (EX-257). `{n:c}` hors de l'Unicode
        # faisait tomber l'export ; un code inencodable disparaissait de
        # l'ISO sans un mot, ou d'une série après la première pièce ; un
        # pas de code négatif valait un micron ; le mot F passait en
        # notation exponentielle ; un process négatif se relisait tel quel.
        import json as _json_z
        from engrave import (iso as _iso_z, preflight as _pf_z,
                             serialize as _ser_z, toolpath as _tp_z,
                             variables as _var_z, vecexport as _vec_z)
        from engrave.model import Code as _Code_z
        _car_z = _var_z.expand('{n:c}', _var_z.make_context(serial=-1))
        _serie_z = Document(name='serie', copies=2,
                            serial_start=999_999_999_999)
        _serie_z.add(_Code_z(kind='ean13', data='{n:012}'))
        _serie_z.add(Rect(x=40.0))
        _bloque_z = [t for lvl, t in _pf_z.inspect(_serie_z).notes
                     if lvl == _pf_z.BLOQUANT and 'pièce 2' in t]
        with tempfile.TemporaryDirectory() as _tmp_z:
            try:
                _iso_z.export(_serie_z, _tmp_z)
                _refus_z = ''
            except ValueError as _e_z:
                _refus_z = str(_e_z)
            _laisse_z = list(pathlib.Path(_tmp_z).iterdir())
        _seul_z = Document(name='seul')
        _seul_z.add(_Code_z(kind='ean13', data='12345'))
        _seul_z.add(Rect())
        try:
            _vec_z.toolpath_layers(_seul_z)
            _vec_refus_z = False
        except _vec_z.ExportError:
            _vec_refus_z = True
        _c39_z = _Code_z(kind='code39', data='A')
        _n0_z = len(_tp_z.shape_polylines(_c39_z))
        _c39_z.fill_step_mm = -1.0
        _n1_z = len(_tp_z.shape_polylines(_c39_z))
        _dm_z = _Code_z(kind='datamatrix', data='X' * 200, module_mm=5.0,
                     fill_step_mm=0.001)
        _trop_z = _tp_z.code_fill_too_large(_dm_z)
        _f_z = [_iso_z._vitesse(v) for v in (80000.0, 1234567.0, 2500.5)]
        _brut_z = _json_z.loads(_ser_z.dumps(_seul_z))
        for _s_z in _brut_z['shapes']:
            _s_z['recipe'].update(power_percent=-9.2, speed_mm_min=-50,
                                  tool_number=-1, hatch_mm=-1)
        _rep_z = []
        _relu_z = _ser_z.loads(_json_z.dumps(_brut_z), _rep_z).shapes[0]
        check('banc : un champ, un code, un pas, une vitesse (EX-257)',
              _car_z == '-1' and len(_bloque_z) == 1
              and 'pièce 2' in _refus_z and not _laisse_z
              and _vec_refus_z and _n1_z == _n0_z and _trop_z
              and _f_z == ['80000', '1234567', '2500.5']
              and (_relu_z.recipe.power_percent, _relu_z.recipe.speed_mm_min,
                   _relu_z.recipe.tool_number, _relu_z.recipe.hatch_mm)
              == (100.0, 40000.0, 1, 0.0) and len(_rep_z) == 8,
              f'{{n:c}} à -1 → {_car_z!r} · série : vérif {len(_bloque_z)} '
              f'bloquant, export « {_refus_z[:40]} », {len(_laisse_z)} '
              f'fichier(s) laissé(s) · vectoriel refusé {_vec_refus_z} · '
              f'code 39 pas -1 : {_n1_z}/{_n0_z} tracés · remplissage '
              f'démesuré omis {_trop_z} · F {_f_z} · {len(_rep_z)} '
              f'remplacement(s) à la relecture')

        with tempfile.TemporaryDirectory() as tmp:
            ancien = drawings.user_dir()
            drawings.set_user_dir(tmp)
            session.forget_reachability()
            ajoute = drawings.add(livres[0].path, 'Essai auto')
            renomme = drawings.rename(ajoute, 'Essai renommé')
            noms = [e.name for e in drawings.entries() if not e.delivered]
            drawings.remove(renomme)
            reste = [e.name for e in drawings.entries() if not e.delivered]
            check('bibliothèque : ajouter, renommer, effacer',
                  noms == ['Essai renommé'] and not reste,
                  ' → '.join(['Essai auto', 'Essai renommé', '(effacé)']))

            # rayons : de vrais sous-dossiers, créés, remplis, vidés
            drawings.make_folder('Clients/Renault')
            range_ = drawings.add(livres[0].path, 'Essai rayon',
                                  folder='Clients/Renault')
            dedans = [e.key() for e in drawings.entries('Clients/Renault')]
            racine = [e.key() for e in drawings.entries()
                      if not e.delivered and not e.folder]
            plein = True
            try:
                drawings.drop_folder('Clients/Renault')
            except ValueError:
                plein = False
            check('bibliothèque : rayons, un dessin s' + chr(39) + 'y range',
                  dedans == ['Clients/Renault/Essai rayon'] and not racine
                  and 'Clients/Renault' in drawings.folders() and not plein,
                  ' · '.join(drawings.folders()))
            remis = drawings.move(range_, '')
            drawings.drop_folder('Clients/Renault')
            check('bibliothèque : rayon vidé puis effacé',
                  remis.folder == '' and not remis.path.parent.name.startswith(
                      'Renault')
                  and 'Clients/Renault' not in drawings.folders(),
                  ' · '.join(drawings.folders()) or 'plus aucun rayon')
            check('bibliothèque : un rayon ne sort pas de la bibliothèque',
                  drawings.clean_folder('../../Windows') == 'Windows'
                  and '..' not in drawings.clean_folder('a/../../b')
                  and ':' not in drawings.clean_folder('C:/Windows'),
                  repr(drawings.clean_folder('../../Windows')))
            drawings.remove(remis)
            drawings.set_user_dir(str(ancien))
            session.forget_reachability()

        # La bibliothèque est un **panneau** : aperçu en colonne 2, arbre
        # rayon ▸ dessin en colonne 3, comme le gestionnaire de process.
        window._library()
        app.processEvents()
        biblio = window.library_panel
        check('bibliothèque : panneau en colonne 2, arbre en colonne 3',
              window.center.currentIndex() == 2
              and window._dock_biblio.isVisible()
              and not window._dock_insp.isVisible()
              and window._dock_biblio.widget() is biblio.tree,
              f'{biblio.tree.topLevelItemCount()} entrée(s) de tête')
        check('bibliothèque : l' + chr(39) + 'arbre désigne un dessin',
              biblio.current() is not None
              and hasattr(biblio, 'b_move') and hasattr(biblio, 'w_preview'),
              biblio.current().name if biblio.current() else '')
        check('bibliothèque : plus de note « lecture seule »',
              'lecture seule' not in biblio.w_info.text().lower(),
              biblio.w_info.text()[:56])
        from engrave.librarypanel import decimate as _dec
        _gros = [[(float(i), float(i % 7)) for i in range(9000)]]
        _petit = _dec(_gros, 4000)
        check('bibliothèque : aperçu allégé, extrémités gardées',
              sum(len(p) for p in _petit) < 9000
              and _petit[0][0] == _gros[0][0] and _petit[0][-1] == _gros[0][-1]
              and _dec([[(0.0, 0.0), (1.0, 1.0)]], 4000)
              == [[(0.0, 0.0), (1.0, 1.0)]],
              f'9000 → {sum(len(p) for p in _petit)} points, bouts gardés')
        # l'esquisse le dit, et donne une cote approchée ; la pleine
        # définition le dit aussi, et donne la cote exacte
        _lourd = [[(float(i), float(i % 5)) for i in range(9000)]]
        biblio._paint(biblio.current(), _dec(_lourd), (0.0, 0.0, 9000.0, 5.0),
                      hq=False)
        _esquisse = 'esquisse' in biblio.w_info.text()
        _approche = '≈' in biblio.w_info.text()
        biblio._paint(biblio.current(), _lourd, (0.0, 0.0, 9000.0, 5.0), hq=True)
        check('bibliothèque : l' + chr(39) + 'aperçu dit s' + chr(39) + 'il est '
              'une esquisse ou la pleine définition',
              _esquisse and _approche and 'esquisse' not in biblio.w_info.text()
              and 'pleine définition' in biblio.w_info.text(),
              biblio.w_info.text()[-46:])
        _dossiers = [biblio.tree.topLevelItem(i)
                     for i in range(biblio.tree.topLevelItemCount())]
        check('bibliothèque : un rayon porte l' + chr(39) + 'icône dossier, '
              'plus le mot « rayon »',
              all(n.icon(0).isNull() == (n.data(0, _Qt.UserRole) is not None)
                  for n in _dossiers)
              and not hasattr(biblio, 'w_shelf'),
              f'{len(_dossiers)} entrée(s) de tête')
        # --- esquisse : parcourir ne coûte plus lire ---------------------------
        #
        # Le point douloureux : une bibliothèque livrée de plusieurs dizaines
        # de mégaoctets. Chaque clic de liste lisait un dessin en entier —
        # plusieurs secondes, et autant de fils qu'on pressait de fois la
        # flèche du bas. L'esquisse doit être franchement plus rapide, et
        # donner la même emprise à un dixième de millimètre près.
        import time

        from engrave import dxfimport
        from engrave import librarypanel as _lp
        from engrave import sketch as _sk
        _lourds = [e for e in drawings.entries()
                   if e.delivered and e.suffix() == '.dxf'
                   and e.path.stat().st_size > 1_000_000]
        if _lourds:
            _cible = max(_lourds, key=lambda e: e.path.stat().st_size)
            _t = time.time()
            _esq = _sk.dxf_outline(_cible.path)
            _t_esq = time.time() - _t
            _t = time.time()
            _exact, _rapport = dxfimport.read(_cible.path)
            _t_exact = time.time() - _t
            _eb, _xb = _esq.bounds, _rapport.extent
            _ecart = max(abs((_eb[2] - _eb[0]) - (_xb[2] - _xb[0])),
                         abs((_eb[3] - _eb[1]) - (_xb[3] - _xb[1])))
            check('esquisse : bien plus rapide que la lecture exacte',
                  _t_esq * 3 < _t_exact,
                  f'{_cible.name} {_cible.path.stat().st_size / 1e6:.1f} Mo · '
                  f'{_t_esq * 1000:.0f} ms contre {_t_exact * 1000:.0f} ms')
            check('esquisse : même nombre de tracés, même emprise',
                  len(_esq.polys) == _rapport.polylines and _ecart < 0.5,
                  f'{len(_esq.polys)} tracés contre {_rapport.polylines} · '
                  f'écart {_ecart:.3f} mm')
            # Le budget vise les points, pas les tracés : deux mille huit cents
            # contours ne peuvent pas descendre sous deux points chacun sans
            # disparaître. La borne tenue est donc « budget + deux par tracé ».
            _leger = sum(len(p) for p in _dec(_esq.polys))
            check('esquisse : l' + chr(39) + 'aperçu ne peint que du léger',
                  _leger <= _lp.BQ_POINTS + 2 * len(_esq.polys)
                  and _leger * 5 < _esq.points(),
                  f'{_esq.points()} → {_leger} points pour '
                  f'{len(_esq.polys)} tracés')

        # Un fichier qu'aucun lecteur d'esquisse ne couvre, ou trop lourd,
        # n'est pas lu en silence : il le dit et attend « Visualiser ».
        check('esquisse : un format sans lecteur rapide attend qu' + chr(39)
              + 'on demande',
              drawings.HEAVY_BYTES > 0 and _sk.MAX_BYTES > drawings.HEAVY_BYTES,
              f'{drawings.HEAVY_BYTES / 1e6:.0f} Mo · '
              f'{_sk.MAX_BYTES / 1e6:.0f} Mo')

        # --- Visualiser : pleine définition, barre, et annulation --------------
        check('bibliothèque : le bouton « Visualiser » est là, à côté d'
              + chr(39) + 'Insérer',
              hasattr(biblio, 'w_view')
              and biblio.w_view.text() == 'Visualiser'
              and biblio.w_view.isEnabled(),
              biblio.w_view.text())
        if _lourds:
            # Le compte rendu est ce qui fait vivre la barre : sans lui, elle
            # resterait à zéro pendant toute la lecture.
            _vus = []

            def _suivre(part, _texte):
                _vus.append(part)
                return True

            drawings.load(_cible, recipe=PRESET_RECIPES[1], progress=_suivre)
            check('Visualiser : la lecture rend des comptes tout du long',
                  len(_vus) >= 8 and _vus[0] == 0.0 and _vus[-1] == 1.0
                  and any(0.05 < p < 0.35 for p in _vus),
                  f'{len(_vus)} comptes rendus, dont '
                  f'{sum(1 for p in _vus if p < 0.4)} avant le tiers')

            # *Annuler* n'est qu'un compte rendu à qui l'on répond « non » :
            # la lecture doit alors s'arrêter là, sans crier à l'erreur.
            _coupes = []

            def _couper(part, _texte):
                _coupes.append(part)
                return len(_coupes) < 6

            _t = time.time()
            try:
                drawings.load(_cible, recipe=PRESET_RECIPES[1],
                              progress=_couper)
                _arret, _delai = 'lecture allée jusqu' + chr(39) + 'au bout', 0.0
            except dxfimport.Cancelled:
                _arret, _delai = '', time.time() - _t
            check('Visualiser : « Annuler » coupe court, sans crier à l' + chr(39)
                  + 'erreur',
                  not _arret and 0 < _delai < _t_exact / 2,
                  f'arrêté à {_coupes[-1]:.2f} en {_delai:.2f} s — '
                  f'lecture entière : {_t_exact:.2f} s')

        check('bibliothèque : la réserve d' + chr(39) + 'aperçus est bornée',
              _lp.CACHE_ENTRIES > 0
              and len(biblio._loader._cache) <= _lp.CACHE_ENTRIES,
              f'{len(biblio._loader._cache)} / {_lp.CACHE_ENTRIES}')

        window._library()
        app.processEvents()
        check('bibliothèque : le bouton la referme aussi',
              window.center.currentIndex() == 0
              and window._dock_insp.isVisible()
              and window.w_library_action.text() == 'Bibliothèque…',
              window.w_library_action.text())

        # --- offset du dessin sous un cadre ------------------------------------

        from engrave.toolpath import offset_contours as _offset
        from engrave import geometry as _geo
        plein = _geo.rect_contour(20, 20)
        creux = _geo.rect_contour(8, 8)

        def _aire(poly):
            from engrave.toolpath import _signed_area
            return abs(_signed_area(poly))

        grossi = _offset([plein, creux], 0.5)
        aminci = _offset([plein, creux], -0.5)
        check('offset : le plein grossit, la contre-forme se referme',
              _aire(grossi[0]) > _aire(plein) and _aire(grossi[1]) < _aire(creux),
              f'{_aire(plein):.0f} → {_aire(grossi[0]):.0f} mm² · '
              f'{_aire(creux):.0f} → {_aire(grossi[1]):.0f} mm²')
        check('offset : le signe inverse s\'inverse aussi',
              _aire(aminci[0]) < _aire(plein) and _aire(aminci[1]) > _aire(creux))
        check('offset : une nervure plus fine que l\'offset disparaît',
              not _offset([_geo.rect_contour(0.4, 20)], -0.5))

        nu = Rect(width=30, height=20, recipe=PRESET_RECIPES[1])
        nu.frame_offset_mm = 0.3
        encadre = Rect(width=30, height=20, recipe=PRESET_RECIPES[1],
                       frame='rect')
        encadre.frame_offset_mm = 0.3
        demi_nu = max(x for x, _ in shape_contours(nu)[0])
        demi_encadre = max(x for x, _ in shape_contours(encadre)[1])
        check('offset : agit avec **ou sans** cadre',
              demi_nu > 15.0 and demi_encadre > 15.0
              and abs(demi_nu - demi_encadre) < 1e-9,
              f'sans cadre {demi_nu:.2f} mm · sous cadre {demi_encadre:.2f} mm')

        # --- vérification avant export ----------------------------------------

        from engrave import preflight
        controle = Document(name='Contrôle')
        controle.add(Rect(width=20, height=10, recipe=PRESET_RECIPES[1]))
        masquee = Rect(x=8, width=5, height=5, recipe=PRESET_RECIPES[1])
        masquee.visible = False
        controle.add(masquee)
        rapport = preflight.inspect(controle, destination_root=tempfile.gettempdir())
        check('vérification : formes masquées signalées',
              rapport.hidden == 1 and any('masquée' in w for w in
                                          rapport.warnings()),
              f'{len(rapport.notes)} note(s)')
        check('vérification : mesures reprises de l\'export',
              rapport.passes == 1 and rapport.length_mm > 0,
              f'{rapport.length_mm:.1f} mm')
        dehors = Document()
        dehors.add(Rect(x=300, width=20, height=10, recipe=PRESET_RECIPES[1]))
        check('vérification : hors champ bloquant',
              len(preflight.inspect(dehors).blocking()) == 1)

        # un fichier abîmé rend des points NaN ou infinis : écartés, le
        # tracé coupé là où ils étaient, l'emprise recalculée
        import ezdxf as _ezdxf_n
        from engrave import dxfimport as _dxi_n
        from engrave import svgread as _svg_n
        from engrave import geometry as _geo_n
        _nan_n = float('nan')
        _cr_n = _dxi_n.ImportReport()
        _sains_n = [[(0, 0), (1, 0)]]
        _net_n = _dxi_n.assainir(
            [[(0, 0), (10, 0), (_nan_n, 5), (10, 10), (0, 10)],
             [(0, 0), (float('inf'), 3)], [(2e9, 0), (5, 5), (6, 6)]], _cr_n)
        _d_n = _ezdxf_n.new()
        _d_n.header['$INSUNITS'] = 4
        _d_n.modelspace().add_lwpolyline(
            [(0, 0), (10, 0), (_nan_n, 5), (10, 10), (0, 10), (0, 0)])
        _d_n.modelspace().add_line((20, 0), (30, 3))
        _f_n = pathlib.Path(tempfile.mkdtemp()) / 'abime.dxf'
        _d_n.saveas(_f_n)
        _formes_n, _crd_n = _dxi_n.any_to_shapes(str(_f_n))
        # un arc à 10¹⁹ unités se discrétisait sans fin : entité illisible,
        # montrée au bilan ; un DXF tronqué est refusé, pas un plantage
        _d_g = _ezdxf_n.new()
        _d_g.header['$INSUNITS'] = 4
        _d_g.modelspace().add_lwpolyline(
            [(0, 0, 0, 0, 1.0), (1e19, 5e18, 0, 0, 0.7), (0, 1e18)],
            format='xyseb')
        _d_g.modelspace().add_line((0, 0), (10, 5))
        _f_g = _f_n.with_name('geant.dxf')
        _d_g.saveas(_f_g)
        import time as _time_n
        _t0_n = _time_n.perf_counter()
        _formes_g, _crg_n = _dxi_n.any_to_shapes(str(_f_g))
        _dt_n = _time_n.perf_counter() - _t0_n
        _f_t = _f_n.with_name('tronque.dxf')
        _f_t.write_text('  0\nSECTION\n  2\nHEADER\n  9\n$ACADVER\n')
        try:
            _dxi_n.any_to_shapes(str(_f_t))
            _refus_n = ''
        except _dxi_n.DxfError as _e_n:
            _refus_n = str(_e_n)
        check('import : points NaN, infinis ou démesurés écartés et dits',
              _net_n == [[(0, 0), (10, 0)], [(10, 10), (0, 10)],
                         [(5, 5), (6, 6)]]
              and _cr_n.extent == (0, 0, 10, 10)
              and '3 point(s) illisible(s)' in _cr_n.notes[0]
              and _dxi_n.assainir(_sains_n, _dxi_n.ImportReport())
              is _sains_n
              and len(_formes_n) == 1
              and len(_formes_n[0].polylines) == 3
              and _crd_n.extent == (0, 0, 30, 10)
              and len(_crd_n.notes) == 1
              # à la lecture même : une courbe ou un arc au point illisible
              # ne fait plus planter le compte de ses segments
              and _geo_n.flatten_cubic((0, 0), (_nan_n, 1), (2, 2),
                                       (3, 3))
              == [(3, 3)]
              and _svg_n.arc_steps(float('inf'), 1.0, 0.01)
              == _svg_n.arc_steps(5.0, _nan_n, 0.01) == _svg_n.MIN_STEPS
              and len(_geo_n.flatten_cubic((0, 0), (1e306, 0), (0, 0),
                                           (1, 1))) == 64
              and _crg_n.skipped_other == {'LWPOLYLINE': 1}
              and len(_formes_g) == 1 and _dt_n < 2.0
              and 'illisible' in _refus_n,
              f'{_net_n} {_cr_n.extent} {_crd_n.notes} {_crd_n.extent}')

        # un cercle au centre NaN — ce qu'écrit un exportateur C sous
        # Linux — faisait tourner ezdxf sans fin, Annuler compris ; un SVG
        # dont tous les points sont démesurés rendait une forme vide, et
        # le dialogue d'import tombait en la mesurant
        _d_c = _ezdxf_n.new()
        _d_c.modelspace().add_line((0, 0), (10, 10))
        _d_c.modelspace().add_circle((0, 0), 5)
        _f_c = _f_n.with_name('cercle_nan.dxf')
        _d_c.saveas(_f_c)
        _txt_c = _f_c.read_text(encoding='utf-8', errors='replace')
        _i_c = _txt_c.index('CIRCLE')
        _j_c = _txt_c.index('\n 10\n', _i_c) + len('\n 10\n')
        _f_c.write_text(_txt_c[:_j_c] + 'nan'
                        + _txt_c[_txt_c.index('\n', _j_c):], encoding='utf-8')
        _t0_c = _time_n.perf_counter()
        _formes_c, _crc_n = _dxi_n.any_to_shapes(str(_f_c))
        _dt_c = _time_n.perf_counter() - _t0_c
        _f_s = _f_n.with_name('absurde.svg')
        _f_s.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
            'height="100mm" viewBox="0 0 100 100"><path d="M 1e12 1e12 '
            'L 2e12 2e12 L 3e12 1e12 Z" stroke="black" fill="none"/></svg>',
            encoding='utf-8')
        try:
            _dxi_n.any_to_shapes(str(_f_s))
            _refus_s = ''
        except _dxi_n.DxfError as _e_s:
            _refus_s = str(_e_s)
        check('import : une courbe au point NaN est écartée sans bloquer, '
              'un fichier tout entier illisible est refusé',
              _dt_c < 2.0 and len(_formes_c) == 1
              and len(_formes_c[0].polylines) == 1
              and _crc_n.skipped_other == {'CIRCLE': 1}
              and _crc_n.polylines == 1
              and _refus_s.startswith('aucun point lisible'),
              f'cercle NaN : {_dt_c:.2f} s, {_crc_n.skipped_other} · '
              f'SVG démesuré : {_refus_s[:40]}')

        # démesurée — un fichier abîmé, une unité d'import fausse — une
        # forme n'est pas remplie : quarante mètres au vingtième, c'était
        # un hachurage sans fin
        import time as _time_g
        from dataclasses import replace as _rep_g
        from engrave import toolpath as _tp_g
        _rec_g = _rep_g(PRESET_RECIPES[1], hatch_mm=0.05)
        _geant_g = Rect(width=40_000, height=40_000, recipe=_rec_g)
        _t0_g = _time_g.perf_counter()
        _pl_g = _tp_g.shape_polylines(_geant_g)
        _dt_g = _time_g.perf_counter() - _t0_g
        _doc_g = Document()
        _doc_g.add(_geant_g)
        _normal_g = Document()
        _normal_g.add(Rect(width=20, height=10, recipe=_rec_g))
        check('remplissage : une forme démesurée garde son seul contour, '
              'et le contrôle le dit',
              len(_pl_g) == 1 and _dt_g < 2.0
              and any('trop grande' in w for w in
                      preflight.inspect(_doc_g).warnings())
              and len(_tp_g.shape_polylines(_normal_g.shapes[0])) > 100
              and not any('trop grande' in w for w in
                          preflight.inspect(_normal_g).warnings())
              # un champ de 300 mm au millième reste rempli
              and not _tp_g.fill_too_large((0, 0, 300, 300), 0.001)
              and _tp_g.fill_too_large((0, 0, 300, 300), 0.0005),
              f'{len(_pl_g)} tracé(s) en {_dt_g:.2f} s')
        vue = preflight.PreflightDialog(window, rapport)
        check('vérification : dialogue construit et récapitulatif rempli',
              'Longueur gravée' in preflight.summary_html(rapport)
              and vue.w_skip is not None)
        vue.deleteLater()
        check('vérification : réglable dans Paramètres',
              window.w_preflight.isCheckable(),
              'activée' if session.preflight() else 'désactivée')

        # --- enroulement boucle par boucle ------------------------------------
        #
        # Une boucle ne compte que dans son emprise : le compte se fait
        # boucle par boucle. Contre un compte direct sur toutes les arêtes :
        # anneaux imbriqués, de sens contraires, superposés, et un anneau
        # qui repasse par son départ (un huit).
        import random as _rnd_e
        from engrave import geometry as _geo_e

        def _direct_e(segs, px, py):
            w = 0
            for ax, ay, bx, by in segs:
                g = (bx - ax) * (py - ay) - (px - ax) * (by - ay)
                if ay <= py < by and g > 0:
                    w += 1
                elif by <= py < ay and g < 0:
                    w -= 1
            return w

        _anneaux_e = _geo_e._anneaux([
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [(2, 2), (2, 8), (8, 8), (8, 2)],
            [(5, -3), (14, -3), (14, 6), (5, 6)],
            [(20, 0), (30, 10), (30, 0), (20, 10)],
            [(-5, -5), (25, -5), (15, 0), (25, 5), (-5, 5), (5, 0)],
            [(42, 2), (40, 0), (44, 0), (42, 2), (44, 4), (40, 4)]])
        _segs_e = _geo_e._aretes(_anneaux_e)
        _enr_e = _geo_e._Enroulement(_segs_e)
        _g_e = _rnd_e.Random(7)
        _faux_e = sum(
            _enr_e(x, y) != _direct_e(_segs_e, x, y)
            for x, y in ((_g_e.uniform(-8, 48), _g_e.uniform(-8, 13))
                         for _ in range(4000)))
        check('non nul : l\'enroulement boucle par boucle égale le compte '
              'direct', _faux_e == 0 and len(_enr_e.boucles) == 7,
              f'{len(_enr_e.boucles)} boucles, {_faux_e} écart(s) sur 4000 '
              f'points')

        # --- rejouer le parcours -----------------------------------------------

        from engrave import parcours as _pc
        from engrave import toolpath as _tp_p
        _doc_p = Document()
        for _i_p in range(4):
            _doc_p.add(Rect(x=-30 + 16 * _i_p, width=12, height=8,
                            recipe=PRESET_RECIPES[4 if _i_p % 2 else 1]))
        _passes_p = _tp_p.build_passes(_doc_p, optimize=True,
                                       time_budget_s=0.2)
        _rej_p = _pc.Parcours(_passes_p)
        _n_p = sum(1 for p in _passes_p for poly in p.polylines
                   if len(poly) >= 2)
        _mi_p = _rej_p.etat(_rej_p.duree_s / 2)
        _fin_p = _rej_p.etat(_rej_p.duree_s + 1)
        # un point isolé n'est pas gravé : la tête n'y va pas, ni dans le
        # trajet à vide ni dans le parcours rejoué
        _isole_p = Document()
        _isole_p.add(_PathH(polylines=[[(0, 0), (10, 0)], [(30, 30)],
                                       [(5, 5), (6, 6)]],
                            recipe=PRESET_RECIPES[1]))
        _isole_p.add(_PathH(polylines=[[(1, 1), (2, 2)], [(50, 50)]],
                            recipe=PRESET_RECIPES[2]))
        _pi_p = _tp_p.build_passes(_isole_p)
        _ri_p = _pc.Parcours(_pi_p)
        _nul_p = _pc.etapes([_tp_p.Pass(
            recipe=_rep_g(PRESET_RECIPES[1], speed_mm_min=0),
            polylines=[[(0.0, 0.0), (1.0, 0.0)]])], minimum_s=1e-4)
        check('parcours : chaque allumage, dans l\'ordre, au temps du modèle',
              len(_rej_p.etapes) == _n_p > 4
              and abs(_rej_p.duree_s - _tp_p.total_duration_s(_passes_p))
              < 1e-9 * _rej_p.duree_s
              and abs(_rej_p.vide_total_mm
                      - _tp_p.total_travel_mm(_passes_p)) < 1e-6
              and abs(_rej_p.grave_total_mm
                      - _tp_p.total_length_mm(_passes_p)) < 1e-6
              and all(a.fin_s <= b.debut_s + 1e-12 and
                      b.debut_s <= b.allume_s <= b.fin_s
                      for a, b in zip(_rej_p.etapes, _rej_p.etapes[1:]))
              and 0 < _mi_p.faits < _n_p
              and 0 < _mi_p.grave_mm < _rej_p.grave_total_mm
              and _fin_p.faits == _n_p
              and _fin_p.tete == _rej_p.etapes[-1].poly[-1]
              and _rej_p.etat(0.0).tete == (0.0, 0.0)
              # une process à vitesse nulle se parcourt quand même
              and len(_nul_p) == 1 and _nul_p[0].fin_s == 1e-4
              and abs(_ri_p.vide_total_mm - _tp_p.total_travel_mm(_pi_p))
              < 1e-9 and _tp_p.total_travel_mm(_pi_p) < 20
              and _pi_p[0].end_point() == (6, 6)
              and _pc.horloge(65.34) == '1:05,3'
              and _pc.horloge(3725.0) == '1 h 02:05,0',
              f'{_n_p} allumages, {_pc.horloge(_rej_p.duree_s)}')
        _dlg_p = _pc.ParcoursDialog(window, _passes_p, (300.0, 300.0))
        _dlg_p.show()
        app.processEvents()
        _dlg_p._avancer(0.01)
        _avance_p = _dlg_p.t
        _dlg_p._sauter(+1)
        _apres_p = _dlg_p.t
        _dlg_p._sauter(-1)
        _dlg_p.w_regle.setValue(_dlg_p.PAS)
        _bout_p = _dlg_p.t
        _dlg_p._sauter(-1)
        _recul_p = _dlg_p.t
        _image_p = _dlg_p.grab()
        _texte_p = _dlg_p.w_info.text()
        # le clavier va au dialogue : → saute à l'allumage suivant, même à
        # l'ouverture, quand la réglette avait le focus ; Espace lit
        from PySide6.QtGui import QKeyEvent as _QKE_p
        from PySide6.QtCore import QEvent as _QEv_p, Qt as _Qt_p
        _dlg_p.w_regle.setValue(0)
        _dlg_p.activateWindow()
        _dlg_p.setFocus()
        app.processEvents()
        _app_focus_p = QApplication.focusWidget()
        QApplication.sendEvent(_app_focus_p or _dlg_p, _QKE_p(
            _QEv_p.KeyPress, _Qt_p.Key_Right, _Qt_p.NoModifier))
        _droite_p = _dlg_p.t
        QApplication.sendEvent(_app_focus_p or _dlg_p, _QKE_p(
            _QEv_p.KeyPress, _Qt_p.Key_Space, _Qt_p.NoModifier))
        _espace_p = _dlg_p._minuteur.isActive()
        _dlg_p._basculer()
        _clavier_p = (_droite_p == _rej_p.etapes[1].debut_s and _espace_p
                      and all(w.focusPolicy() == _Qt_p.NoFocus for w in (
                          _dlg_p.w_regle, _dlg_p.w_lire, _dlg_p.w_prec,
                          _dlg_p.w_suiv, _dlg_p.w_vitesse, _dlg_p.w_sauts))
                      and not _dlg_p.w_prec.autoDefault())
        # au bout, la lecture repart du début
        _dlg_p.w_regle.setValue(_dlg_p.PAS)
        _dlg_p._basculer()
        _relance_p = _dlg_p.t == 0.0 and _dlg_p._minuteur.isActive()
        _dlg_p.done(0)
        _dlg_p.deleteLater()
        # l'entrée du menu, sans ouvrir de fenêtre modale
        _vus_p = []
        _exec_p = _pc.ParcoursDialog.exec
        _pc.ParcoursDialog.exec = lambda self: _vus_p.append(self) or 0
        try:
            window._rejouer_parcours()
        finally:
            _pc.ParcoursDialog.exec = _exec_p
        _menu_p = [a for a in window.findChildren(_QAction)
                   if a.text() == 'Rejouer le parcours…']
        check('parcours : lecture, pas à pas, réglette, et entrée du menu',
              _clavier_p
              and _pc.horloge(59.96) == '1:00,0'
              and _pc.horloge(3599.97) == '1 h 00:00,0'
              and 0 < _avance_p < _apres_p
              and _bout_p == _dlg_p.parcours.duree_s
              and _recul_p == _rej_p.etapes[-1].debut_s
              and not _image_p.isNull()
              and _texte_p.startswith(f'Allumage {_n_p} / {_n_p}')
              and _relance_p and not _dlg_p._minuteur.isActive()
              and len(_menu_p) == 1
              and _menu_p[0].shortcut().toString() == 'Ctrl+Shift+L'
              and (bool(_vus_p) and bool(_vus_p[0].parcours.etapes)
                   or 'Rien à graver' in window.statusBar().currentMessage()),
              _texte_p)

        # --- vérification : mesure unique, oscillation, essais ------------------

        import math as _m_v
        import random as _rnd_v
        from engrave import preflight as _pf_v
        from engrave import toolpath as _tp_v
        from engrave import wobble as _wob_v2
        _g_v = _rnd_v.Random(7)
        _tr_v = []
        for _ in range(120):
            _q_v = [(_g_v.uniform(0, 40), _g_v.uniform(0, 40))]
            for _ in range(_g_v.randint(1, 9)):
                _t_v = _g_v.random()
                _q_v.append(_q_v[-1] if _t_v < 0.1 else
                            (_q_v[-1][0] + _g_v.uniform(-3, 3),
                             _q_v[-1][1] + _g_v.uniform(-3, 3)))
            _tr_v.append(_q_v)
        # la version rapide de l'oscillation refait les opérations de la
        # définition, dans le même ordre : le tracé est identique au bit
        _osc_v = all(
            _wob_v2.apply_polyline(_q, 0.05, 0.04, _f)
            == _wob_v2._apply_generic(_q, 0.05, 0.04, _f)
            for _f in ('circle', 'eight', 'transverse') for _q in _tr_v)

        # longueur et virages en un passage : ce que comptaient les deux
        # mesures séparées — une épingle à cheveux en est un, l'angle droit
        # n'en est pas un (le SkyWrite part sous 89°)
        def _direct_v(q):
            n = 0
            for a, b_, c in zip(q, q[1:], q[2:]):
                u = (b_[0] - a[0], b_[1] - a[1])
                w = (c[0] - b_[0], c[1] - b_[1])
                nu, nw = _m_v.hypot(*u), _m_v.hypot(*w)
                if nu >= 1e-9 and nw >= 1e-9 and (
                        u[0] * w[0] + u[1] * w[1]) / (nu * nw) \
                        < _tp_v._COS_SKYWRITE:
                    n += 1
            return (sum(_m_v.hypot(b_[0] - a[0], b_[1] - a[1])
                        for a, b_ in zip(q, q[1:])), n)
        _mes_v = all(_tp_v._mesure(_q) == _direct_v(_q) for _q in _tr_v)
        _virages_v = (_tp_v.sharp_corners([(0, 0), (5, 0), (0, 0.1)]),
                      _tp_v.sharp_corners([(0, 0), (5, 0), (5, 5)]),
                      _tp_v.sharp_corners([(0, 0)]),
                      _tp_v.sharp_corners([]))
        # le mémo : même profil, et la polyligne gardée avec sa mesure
        _memo_v = {}
        _p1_v = _tp_v.duration_profile(_tr_v, (3, 4), _memo_v)
        _p2_v = _tp_v.duration_profile(_tr_v, (3, 4), _memo_v)
        _p0_v = _tp_v.duration_profile(_tr_v, (3, 4))
        _garde_v = all(_memo_v[id(_q)][0] is _q for _q in _tr_v)
        _doc_v = Document()
        _osc_rec_v = _rep_g(PRESET_RECIPES[1], name='Oscillée', hatch_mm=0.2,
                            wobble='circle', wobble_amp_mm=0.05,
                            wobble_pitch_mm=0.1)
        _doc_v.add(Text(text='OSC 42', size_mm=6, recipe=_osc_rec_v))
        # sans réordonnancement ; le travail réordonné est contrôlé plus
        # bas, construit avec les réglages de l'export
        _rap_v = _pf_v.inspect(_doc_v)
        _ref_v = _tp_v.total_duration_s(_tp_v.build_passes(_doc_v))
        check('vérification : une mesure des tracés, oscillation au bit près',
              _osc_v and _mes_v and _virages_v == (1, 0, 0, 0)
              and _p1_v == _p2_v == _p0_v and _garde_v
              and len(_memo_v) == sum(1 for _q in _tr_v if len(_q) >= 2)
              and abs(_rap_v.duration_s - _ref_v) < 1e-9 * _ref_v,
              f'{len(_tr_v)} tracés · virages {_virages_v} · '
              f'{_rap_v.duration_s:.2f} s')

        # Un essai de la vérification ne chasse plus du cache la géométrie
        # du document : il ne prend que la place libre.
        _plafond_v = _tp_v._CACHE_MAX_POINTS
        _tp_v.clear_cache()
        try:
            _a_v = Rect(width=10, height=10, recipe=_rep_g(
                PRESET_RECIPES[1], hatch_mm=0.5))
            _b_v = Rect(width=10, height=10, recipe=_rep_g(
                PRESET_RECIPES[1], hatch_mm=0.25))
            _ka_v = _tp_v.geometry_key(_a_v)
            _kb_v = _tp_v.geometry_key(_b_v)
            _tp_v.shape_polylines(_a_v)
            # la place d'un seul des deux
            _tp_v._CACHE_MAX_POINTS = _tp_v._CACHE_TOTAL[0] + 10
            with _tp_v.trial_cache():
                _tp_v.shape_polylines(_b_v)
            _essai_v = (_ka_v in _tp_v._CACHE, _kb_v in _tp_v._CACHE)
            _tp_v._CACHE_MAX_POINTS = 10 ** 9
            with _tp_v.trial_cache():
                _tp_v.shape_polylines(_b_v)
            _libre_v = (_kb_v in _tp_v._CACHE
                        and _tp_v._CACHE_ORDER[0] == _kb_v)
            _tp_v.clear_cache()
            _tp_v.shape_polylines(_a_v)
            _tp_v._CACHE_MAX_POINTS = _tp_v._CACHE_TOTAL[0] + 10
            _tp_v.shape_polylines(_b_v)
            _reel_v = (_ka_v in _tp_v._CACHE, _kb_v in _tp_v._CACHE)
        finally:
            _tp_v._CACHE_MAX_POINTS = _plafond_v
            _tp_v.clear_cache()
        check('vérification : un essai ne chasse pas la géométrie du document',
              _essai_v == (True, False) and _libre_v
              and _reel_v == (False, True) and _tp_v._ESSAI[0] == 0,
              f'essai {_essai_v} · réel {_reel_v}')

        # L'ordonnancement se compte en évaluations, plus à l'horloge :
        # même document, même ordre, quelle que soit la charge du poste.
        # La vérification construit ce que l'export écrit — son budget,
        # partagé entre les pièces, et les champs de la première —, et
        # mesure donc exactement sa durée.
        from engrave import ordering as _ord_v
        from engrave.model import Code as _Code_o
        _doc_o = Document(name='Ordre {n}')
        _doc_o.add(Text(text='TAU 26', size_mm=6, recipe=_rep_g(
            PRESET_RECIPES[1], hatch_mm=0.1)))
        _doc_o.add(_Code_o(data='TAU-{n:04}', module_mm=0.4, x=24,
                           recipe=PRESET_RECIPES[1]))
        _doc_o.copies = 3
        _regl_o = iso.reglages_premiere_piece(_doc_o)
        _e1_o = iso._passes_a_graver(_doc_o, optimize=True, **_regl_o)
        _e2_o = iso._passes_a_graver(_doc_o, optimize=True, **_regl_o)
        _meme_o = [q.polylines for q in _e1_o] == [q.polylines for q in _e2_o]
        _rap_o = _pf_v.inspect(_doc_o, optimize=True)
        _ref_o = _tp_v.total_duration_s(_e1_o)
        # le 2-opt seul : jamais plus long que le plus proche voisin, sans
        # budget il le laisse tel quel, et rien ne se perd en route
        _brut_o = [q for p in _tp_v.build_passes(_doc_o) for q in p.polylines
                   if len(q) >= 2]
        _ppv_o = _ord_v.nearest_neighbour(_brut_o, (0.0, 0.0))
        _opt_o = _ord_v.two_opt(_ppv_o, (0.0, 0.0), 0.2)

        def _cle_o(q):
            return min(tuple(q), tuple(reversed(q)))
        check('ordonnancement : même ordre à chaque calcul, durée de '
              'l\'export mesurée',
              _meme_o and _regl_o['time_budget_s'] == iso.BUDGET_S / 3
              and _regl_o['context']['n'] == _doc_o.serial_for(0)
              and abs(_rap_o.duration_s - _ref_o) < 1e-9 * _ref_o
              and _ord_v.two_opt(_ppv_o, (0.0, 0.0), 0.0) == _ppv_o
              and _ord_v.two_opt(_ppv_o, (0.0, 0.0), 0.2) == _opt_o
              and _ord_v.travel_distance(_opt_o)
              <= _ord_v.travel_distance(_ppv_o)
              and sorted(map(_cle_o, _opt_o)) == sorted(map(_cle_o, _ppv_o)),
              f'{len(_brut_o)} tracés · à vide '
              f'{_ord_v.travel_distance(_ppv_o):.1f} → '
              f'{_ord_v.travel_distance(_opt_o):.1f} mm · '
              f'{_rap_o.duration_s:.2f} s')

        # Plus proche voisin, cases chargées (EX-263). La maille de la
        # grille suit l'emprise : un trait égaré à 5 m la portait à 25 mm,
        # et vingt mille traits dans 20 mm tombaient dans une seule case,
        # relue en entier à chaque recherche — deux minutes. Une case de
        # plus de `CASE_LOURDE` extrémités passe dans un arbre, qui rend ce
        # que rendait le balayage de sa liste : même ordre, égalités et
        # extrémités confondues comprises.
        import random as _rnd_pv
        import time as _time_pv
        _h_pv = _rnd_pv.Random(263)

        def _traits_pv(_n):
            _t = []
            for _ in range(_n):
                _x, _y = _h_pv.uniform(0, 20), _h_pv.uniform(0, 20)
                _a = _h_pv.uniform(0, 2 * _math.pi)
                _t.append([(_x, _y), (_x + 0.3 * _math.cos(_a),
                                      _y + 0.3 * _math.sin(_a))])
            return _t
        _loin_pv = [[(5000.0, 5000.0), (5000.5, 5000.0)]]
        _grand_pv = _traits_pv(20000) + _loin_pv
        _t_pv = _time_pv.perf_counter()
        _ordre_pv = _ord_v.nearest_neighbour(_grand_pv, (0.0, 0.0))
        _t_pv = _time_pv.perf_counter() - _t_pv
        # des rayons d'un même centre et un trait en triple : des
        # extrémités confondues, des égalités à départager
        _petit_pv = (_traits_pv(1500)
                     + [[(10.0, 10.0), (10.0 + _math.cos(_k),
                                        10.0 + _math.sin(_k))]
                        for _k in range(60)]
                     + [[(3.0, 3.0), (4.0, 4.0)]] * 3 + _loin_pv)
        _arbre_pv = _ord_v.nearest_neighbour(_petit_pv, (0.0, 0.0))
        _seuil_pv = _ord_v.CASE_LOURDE
        _ord_v.CASE_LOURDE = 10 ** 9          # le balayage d'avant
        try:
            _balaye_pv = _ord_v.nearest_neighbour(_petit_pv, (0.0, 0.0))
        finally:
            _ord_v.CASE_LOURDE = _seuil_pv
        check('ordonnancement : une case chargée se trie à l\'arbre, '
              'même ordre qu\'au balayage (EX-263)',
              _t_pv < 10.0 and len(_ordre_pv) == len(_grand_pv)
              and _ordre_pv[-1] == _loin_pv[0]
              and _arbre_pv == _balaye_pv,
              f'20 000 traits dans 20 mm et un à 5 m : {_t_pv:.2f} s · '
              f'{len(_petit_pv)} traits en une case : ordre '
              f'{"identique" if _arbre_pv == _balaye_pv else "DIFFÉRENT"}')

        # Une série : la forme qui ne change pas d'une pièce à l'autre est
        # ordonnée et mise en texte une fois, pas une par pièce — et chaque
        # fichier est celui qu'un calcul à neuf de sa pièce écrirait.
        from engrave import variables as _var_s
        _doc_s = Document(name='Serie')
        _doc_s.add(Text(text='TAU', size_mm=6, recipe=_rep_g(
            PRESET_RECIPES[1], hatch_mm=0.1)))
        _doc_s.add(Text(text='{n}', size_mm=4, y=-8,
                        recipe=PRESET_RECIPES[1]))
        _doc_s.copies = 4
        _appels_s = {'ordre': 0, 'iso': 0}
        _ordre_s, _iso_s = _tp_v.ordering.ordre_optimal, iso.render_iso

        def _compte_ordre_s(*a, **k):
            _appels_s['ordre'] += 1
            return _ordre_s(*a, **k)

        def _compte_iso_s(*a, **k):
            _appels_s['iso'] += 1
            return _iso_s(*a, **k)
        _dir_s = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-serie-'))
        _tp_v.clear_cache()
        _tp_v.ordering.ordre_optimal = _compte_ordre_s
        iso.render_iso = _compte_iso_s
        try:
            iso.export(_doc_s, _dir_s, optimize=True)
        finally:
            _tp_v.ordering.ordre_optimal = _ordre_s
            iso.render_iso = _iso_s
        _neufs_s = []
        for _k_s in range(_doc_s.copies):
            _tp_v.clear_cache()
            _ctx_s = _var_s.make_context(
                serial=_doc_s.serial_for(_k_s), index=_k_s + 1,
                total=_doc_s.copies, job='Serie')
            _ps_s = _tp_v.build_passes(
                _doc_s, optimize=True, context=_ctx_s,
                time_budget_s=iso.BUDGET_S / _doc_s.copies)
            _st_s = f'Serie_p{_k_s + 1:04d}'
            _neufs_s += [
                (_dir_s / _st_s / f'{_st_s}_Z{_i_s:04d}.ISO').read_text(
                    encoding='ascii')
                == iso.render_iso(_p_s, header_comment=_p_s.source_name)
                for _i_s, _p_s in enumerate(_ps_s, 1)]
        check('série : une forme inchangée ordonnée et écrite une fois',
              _appels_s == {'ordre': 5, 'iso': 5} and len(_neufs_s) == 8
              and all(_neufs_s),
              f'{_appels_s["ordre"]} ordres et {_appels_s["iso"]} textes '
              f'pour 8 passes · {sum(_neufs_s)}/8 fichiers identiques')

        # Une grosse entrée est rangée compacte : sept fois moins de place,
        # et la géométrie relue est identique au bit. Deux formes qui ne
        # tenaient pas ensemble se gardent désormais toutes deux, au lieu
        # de s'évincer l'une l'autre à chaque construction. Seuils abaissés
        # le temps du contrôle.
        _seuils_v = (_tp_v._COMPACT_POINTS, _tp_v._CACHE_MAX_POINTS)
        _tp_v.clear_cache()
        try:
            _osc_c = _rep_g(PRESET_RECIPES[1], hatch_mm=0.3, wobble='eight',
                            wobble_amp_mm=0.05, wobble_pitch_mm=0.2)
            _c1_v = Rect(width=12, height=6, x=4, y=-3, rotation_deg=12,
                         recipe=_osc_c)
            _c2_v = Text(text='C', size_mm=5, x=-8, recipe=_osc_c)
            _froid_v = [_tp_v.shape_polylines(_c) for _c in (_c1_v, _c2_v)]
            _loc_froid_v = [_tp_v.local_polylines(_c)
                            for _c in (_c1_v, _c2_v)]
            _n_v = [sum(len(_q) for _q in _f) for _f in _froid_v]
            _tp_v.clear_cache()
            _tp_v._COMPACT_POINTS = min(_n_v)
            # en couples, les deux ne tiendraient pas ensemble
            _tp_v._CACHE_MAX_POINTS = max(_n_v) + min(_n_v) // 2
            _k_v = [_tp_v.geometry_key(_c) for _c in (_c1_v, _c2_v)]
            _cuits_v = [_tp_v.shape_polylines(_c) for _c in (_c1_v, _c2_v)]
            _gardes_v = [_k in _tp_v._CACHE for _k in _k_v]
            _compacts_v = [type(_tp_v._CACHE.get(_k)) is _tp_v._Compact
                           for _k in _k_v]
            _poids_v = [_tp_v._CACHE_POINTS.get(_k) for _k in _k_v]
            _chauds_v = [_tp_v.shape_polylines(_c) for _c in (_c1_v, _c2_v)]
            _loc_chaud_v = [_tp_v.local_polylines(_c)
                            for _c in (_c1_v, _c2_v)]
        finally:
            _tp_v._COMPACT_POINTS, _tp_v._CACHE_MAX_POINTS = _seuils_v
            _tp_v.clear_cache()
        check('cache : une grosse entrée rangée compacte, relue au bit près',
              _gardes_v == [True, True] and _compacts_v == [True, True]
              and _poids_v == [_n // _tp_v._COMPACT_POIDS + 1
                               for _n in _n_v]
              and repr(_cuits_v) == repr(_froid_v)
              and repr(_chauds_v) == repr(_froid_v)
              and repr(_loc_chaud_v) == repr(_loc_froid_v),
              f'{_n_v} points → poids {_poids_v}')

        # Une forme lourde se peint une fois, dans une image que la vue
        # déplace : défiler ne la repeint plus. Une légère se peint
        # toujours directement.
        from PySide6.QtGui import QPixmapCache as _QPC_v
        from PySide6.QtWidgets import QGraphicsItem as _QGI_v
        from engrave.app import ShapeItem as _SI_v
        _lourd_v = _SI_v(Rect(width=20, height=10, recipe=_rep_g(
            PRESET_RECIPES[1], hatch_mm=0.2, wobble='circle',
            wobble_amp_mm=0.05, wobble_pitch_mm=0.2)), lambda *a: None)
        _leger_v = _SI_v(Rect(width=10, height=5, recipe=PRESET_RECIPES[1]),
                         lambda *a: None)
        _el_v = (_lourd_v.path().elementCount(),
                 _leger_v.path().elementCount())
        check('plan : une forme lourde se peint une fois, puis se déplace',
              _el_v[0] > _SI_v.CACHE_FROM > _el_v[1]
              and _lourd_v.cacheMode() == _QGI_v.DeviceCoordinateCache
              and _leger_v.cacheMode() == _QGI_v.NoCache
              and _QPC_v.cacheLimit() >= _SI_v.PIXMAPS_KO,
              f'{_el_v[0]} et {_el_v[1]} éléments · images Qt '
              f'{_QPC_v.cacheLimit() // 1024} Mo')

        # Un pas d'oscillation tapé cent fois trop fin : compté avant d'être
        # calculé, il laisse le trait sans oscillation au lieu de figer
        # TauDrive ; la vérification le bloque, et les deux exports le
        # refusent — même coupée, la vérification ne laisse pas graver un
        # trait fin à la place de la bande demandée.
        import time as _time_v
        from engrave import morceaux as _mx_v
        _compte_v = all(
            _wob_v2.point_count([_q], _p) == len(
                _wob_v2.apply_polyline(_q, 0.05, _p, 'circle'))
            for _q in _tr_v[:60] for _p in (0.07, 0.4))
        _fine_v = _rep_g(PRESET_RECIPES[1], name='Oscillation fine',
                         hatch_mm=0.05, wobble='circle', wobble_amp_mm=0.1,
                         wobble_pitch_mm=0.001)
        _dense_v = Document(name='pas trop fin')
        _dense_v.add(Text(text='TAU', size_mm=8, recipe=_fine_v))
        _sans_v = _rep_g(_dense_v.shapes[0], recipe=_rep_g(
            _fine_v, wobble='none'))
        _t0_v = _time_v.perf_counter()
        _vu_v = _tp_v.local_polylines(_dense_v.shapes[0])
        _duree_v = _time_v.perf_counter() - _t0_v
        _plan_v = _vu_v == _tp_v.local_polylines(_sans_v)
        with _tp_v.dense_wobble() as _rel_v:
            _tp_v.build_passes(_dense_v)        # lu dans le cache, cette fois
        _note_v = [n for n in _pf_v.inspect(_dense_v).notes
                   if n[0] == _pf_v.BLOQUANT and 'trop dense' in n[1]]
        _refus_v = []
        for _ecrire_v in (
                lambda d: iso.export(_dense_v, d),
                lambda d: iso.export_morceaux(
                    _dense_v, d, _mx_v.plan(_dense_v.bounds(), 110, 110))):
            try:
                _ecrire_v(tempfile.mkdtemp(prefix='taudrive-dense-'))
                _refus_v.append('écrit')
            except ValueError as _e_v:
                _refus_v.append('trop dense' in str(_e_v))
        # un pas ordinaire n'est pas touché
        _normal_v = Document()
        _normal_v.add(Text(text='T', size_mm=4, recipe=_rep_g(
            _fine_v, hatch_mm=0, wobble_pitch_mm=0.1)))
        with _tp_v.dense_wobble() as _rel_n_v:
            _np_v = _tp_v.build_passes(_normal_v)
        check('oscillation trop dense : montrée sans, bloquée, refusée',
              _compte_v and _plan_v and _duree_v < 5
              and list(_rel_v.values())[0][0] > _wob_v2.MAX_POINTS
              and len(_note_v) == 1 and _refus_v == [True, True]
              and not _rel_n_v and sum(len(q) for q in _np_v[0].polylines)
              > 16 * len(_tp_v.local_polylines(_rep_g(
                  _normal_v.shapes[0], recipe=_rep_g(
                      _normal_v.shapes[0].recipe, wobble='none')))[0]),
              f'{list(_rel_v.values())[0][0] / 1e6:.1f} M points évités en '
              f'{_duree_v:.2f} s · exports {_refus_v}')

        # Relecture d'EX-243 à 245. Le relevé des oscillations abandonnées
        # se tient par forme et non par nom, remonte d'un relevé imbriqué,
        # et compte toutes les passes quand le hachurage tourne ; une série
        # dont une pièce est trop dense est refusée avant toute écriture,
        # vérification et export vectoriel compris ; un compte s'arrondit
        # au-dessus du plafond.
        from engrave import vecexport as _vx_r
        _deux_r = Document(name='deux TAU')
        _deux_r.add(Text(text='TAU', size_mm=8, recipe=_fine_v))
        _deux_r.add(Text(text='TAU', size_mm=8, x=30, recipe=_fine_v))
        _homonymes_r = len(_tp_v.formes_trop_denses(_deux_r))
        with _tp_v.dense_wobble() as _ext_r:
            with _tp_v.dense_wobble() as _int_r:
                _tp_v.build_passes(_dense_v)
        _imbrique_r = bool(_int_r) and bool(_ext_r)
        # six passes qui tournent : chacune sous le plafond, ensemble
        # au-dessus — la forme est trop dense
        _tourne_r = _rep_g(PRESET_RECIPES[1], hatch_mm=0.1, passes=6,
                           hatch_angle_step_deg=30, wobble='circle',
                           wobble_amp_mm=0.05, wobble_pitch_mm=0.1)
        _rot_r = Rect(width=10, height=10, recipe=_tourne_r)
        _nappe_r = _tp_v._local_cached(_rep_g(_rot_r, recipe=_rep_g(
            _tourne_r, wobble='none')), None, 0)
        _n01_r = _wob_v2.point_count(_nappe_r, 0.1)
        _pas_r = 0.1 * _n01_r / (_wob_v2.MAX_POINTS / 3)
        _rot_r = _rep_g(_rot_r, recipe=_rep_g(_tourne_r,
                                              wobble_pitch_mm=_pas_r))
        _par_nappe_r = _wob_v2.point_count(_nappe_r, _pas_r)
        _doc_rot_r = Document()
        _doc_rot_r.add(_rot_r)
        with _tp_v.dense_wobble() as _rel_rot_r:
            _tp_v.build_passes(_doc_rot_r)
        _nappes_r = (_par_nappe_r < _wob_v2.MAX_POINTS and bool(_rel_rot_r)
                     and list(_rel_rot_r.values())[0][0]
                     > _wob_v2.MAX_POINTS)
        # une série : « 1 » passe, « 1111111111 » est trop dense
        _court_r = Text(text='1', size_mm=6, recipe=_rep_g(
            PRESET_RECIPES[1], hatch_mm=0))
        _long_r = _rep_g(_court_r, text='1111111111')
        _n_long_r = _wob_v2.point_count(_tp_v.local_polylines(_long_r), 0.1)
        _pas_s_r = 0.1 * _n_long_r / (1.5 * _wob_v2.MAX_POINTS)
        _serie_r = Document(name='serie dense')
        _serie_r.add(Text(text='{n}', size_mm=6, recipe=_rep_g(
            PRESET_RECIPES[1], hatch_mm=0, wobble='circle',
            wobble_amp_mm=0.05, wobble_pitch_mm=_pas_s_r)))
        _serie_r.copies = 2
        _serie_r.serial_start = 1
        _serie_r.serial_step = 1111111110
        _vides_r = []
        for _ecrire_r in (
                lambda d: iso.export(_serie_r, d),
                lambda d: iso.export_morceaux(
                    _serie_r, d, _mx_v.plan(_serie_r.bounds(), 110, 110))):
            _d_r = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-serie-'))
            try:
                _ecrire_r(_d_r)
                _vides_r.append('écrit')
            except ValueError as _e_r:
                _vides_r.append('trop dense' in str(_e_r)
                                and not any(_d_r.rglob('*.*')))
        _vue_r = any(n[0] == _pf_v.BLOQUANT and 'trop dense' in n[1]
                     for n in _pf_v.inspect(_serie_r).notes)
        try:
            _vx_r.export(_dense_v, pathlib.Path(tempfile.mkdtemp(
                prefix='taudrive-vec-')) / 'traj.svg', toolpaths=True)
            _vec_r = False
        except _vx_r.ExportError as _e_r:
            _vec_r = 'trop dense' in str(_e_r)
        _arrondi_r = (iso._millions(3_000_001), iso._millions(2_950_000))
        check('relecture : oscillation trop dense comptée par forme, série '
              'refusée avant écriture',
              _homonymes_r == 2 and _imbrique_r and _nappes_r
              and _vides_r == [True, True] and _vue_r and _vec_r
              and _arrondi_r == ('3,1', '3,0'),
              f'homonymes {_homonymes_r} · nappes {_nappes_r} · série '
              f'{_vides_r} · vectoriel {_vec_r} · {_arrondi_r}')

        # Deux fils sur le même cache — le plan et l'esquisse de la
        # bibliothèque : rien n'y est compté deux fois, et une oscillation
        # abandonnée est toujours signalée, même évincée entre-temps.
        import sys as _sys_r
        import threading as _th_r
        _plafond_r = _tp_v._CACHE_MAX_POINTS
        _bascule_r = _sys_r.getswitchinterval()
        _formes_r = [Rect(width=3 + _k, height=2, recipe=_rep_g(
            PRESET_RECIPES[1], hatch_mm=0.25)) for _k in range(6)]
        _fin_r = Rect(width=2, height=1, recipe=_rep_g(
            PRESET_RECIPES[1], hatch_mm=0, wobble='circle',
            wobble_amp_mm=0.05, wobble_pitch_mm=1e-5))
        _rates_r = []

        def _fil_r():
            for _ in range(60):
                for _f in _formes_r:
                    _tp_v.shape_polylines(_f)
        _tp_v.clear_cache()
        _tp_v._CACHE_MAX_POINTS = 400
        _sys_r.setswitchinterval(1e-5)
        try:
            _autre_r = _th_r.Thread(target=_fil_r, daemon=True)
            _autre_r.start()
            for _ in range(300):
                with _tp_v.dense_wobble() as _rel_f:
                    _tp_v.shape_polylines(_fin_r)
                    _tp_v.shape_polylines(_formes_r[_ % 6])
                if not _rel_f:
                    _rates_r.append(_)
            _autre_r.join()
            _ordre_r = list(_tp_v._CACHE_ORDER)
            _sain_r = (len(_ordre_r) == len(set(_ordre_r))
                       == len(_tp_v._CACHE)
                       and set(_tp_v._CACHE_POINTS) == set(_tp_v._CACHE)
                       and _tp_v._CACHE_TOTAL[0]
                       == sum(_tp_v._CACHE_POINTS.values())
                       and set(_tp_v._DENSES) <= set(_tp_v._CACHE))
        finally:
            _sys_r.setswitchinterval(_bascule_r)
            _tp_v._CACHE_MAX_POINTS = _plafond_r
            _tp_v.clear_cache()
        check('cache : deux fils, rien de compté deux fois ni de perdu',
              _sain_r and not _rates_r,
              f'{len(_rates_r)} signal(aux) perdu(s) sur 300')

        # L'affichage lit une grosse entrée telle qu'elle est rangée, sans
        # la déplier : même chemin, au point près.
        _seuil_r = _tp_v._COMPACT_POINTS
        _lourd_r = Text(text='OSC', size_mm=5, recipe=_rep_g(
            PRESET_RECIPES[1], hatch_mm=0.2, wobble='eight',
            wobble_amp_mm=0.05, wobble_pitch_mm=0.2))
        try:
            _tp_v.clear_cache()
            _tp_v._COMPACT_POINTS = 10 ** 12
            _couples_r = _SI_v(_lourd_r, lambda *a: None).path()
            _tp_v.clear_cache()
            _tp_v._COMPACT_POINTS = 1000
            _SI_v(_lourd_r, lambda *a: None)          # rangée compacte
            _compact_r = type(_tp_v._CACHE.get(_tp_v.geometry_key(
                _lourd_r))) is _tp_v._Compact
            _relu_r = _SI_v(_lourd_r, lambda *a: None).path()
        finally:
            _tp_v._COMPACT_POINTS = _seuil_r
            _tp_v.clear_cache()
        check('plan : une grosse entrée se dessine sans être dépliée',
              _compact_r and _relu_r == _couples_r
              and _relu_r.elementCount() > 1000,
              f'{_relu_r.elementCount()} éléments')

        # Relecture des cycles EX-246 à 248. Le nombre de passes entre dans
        # la clé quand il décide de l'oscillation : passer de huit passes à
        # quatre ne rejoue pas le refus. La vérification relève toutes les
        # pièces d'une série, comme l'export.
        from engrave.model import Circle as _Cercle_r, Code as _Code_r
        _cap_r = _wob_v2.MAX_POINTS
        _osc_r = _rep_g(PRESET_RECIPES[1], hatch_mm=0.2, passes=8,
                        hatch_angle_step_deg=45, wobble='circle',
                        wobble_amp_mm=0.05, wobble_pitch_mm=0.1)
        _rect_p_r = Rect(width=6, height=4, recipe=_osc_r)
        _doc_p_r = Document(name='passes')
        _doc_p_r.add(_rect_p_r)
        _nus_r = [_wob_v2.point_count(_tp_v._local_cached(_rep_g(
            _rect_p_r, recipe=_rep_g(_osc_r, wobble='none')), None, _i),
            0.1) for _i in range(8)]
        _dm_r = Document(name='serie DM')
        _dm_r.add(_Code_r(data='{n:04}', module_mm=0.3, recipe=_rep_g(
            PRESET_RECIPES[1], hatch_mm=0.15, wobble='circle',
            wobble_amp_mm=0.04, wobble_pitch_mm=0.05)))
        _dm_r.copies = 12
        _dm_nu_r = _rep_g(_dm_r.shapes[0], recipe=_rep_g(
            _dm_r.shapes[0].recipe, wobble='none'))
        _par_piece_r = [_wob_v2.point_count(_tp_v._local_cached(
            _dm_nu_r, iso.contexte_piece(_dm_r, _k), 0), 0.05)
            for _k in range(12)]
        _bouts_r = max(_par_piece_r[0], _par_piece_r[-1])
        try:
            _tp_v.clear_cache()
            _wob_v2.MAX_POINTS = 6 * max(_nus_r)
            _huit_r = bool(_tp_v.formes_trop_denses(_doc_p_r))
            _rect_p_r.recipe = _rep_g(_osc_r, passes=4)
            _quatre_r = not _tp_v.formes_trop_denses(_doc_p_r)
            _tp_v.clear_cache()
            _wob_v2.MAX_POINTS = (_bouts_r + max(_par_piece_r)) // 2
            _milieu_r = (max(_par_piece_r) > _bouts_r
                         and any('trop dense' in _n[1] for _n in
                                 _pf_v.inspect(_dm_r).notes))
        finally:
            _wob_v2.MAX_POINTS = _cap_r
            _tp_v.clear_cache()
        # un seul instant pour tout l'export, relevé préalable compris
        _mk_r = _var_s.make_context
        _instants_r = []

        def _note_instant_r(**_kw):
            _ctx = _mk_r(**_kw)
            _instants_r.append(_ctx['_now'])
            return _ctx
        _heure_r = Document(name='heure')
        _heure_r.add(Text(text='{heure} {n}', size_mm=3,
                          recipe=_rep_g(PRESET_RECIPES[1], hatch_mm=0)))
        _heure_r.copies = 3
        _var_s.make_context = _note_instant_r
        try:
            iso.export(_heure_r, pathlib.Path(tempfile.mkdtemp(
                prefix='taudrive-heure-')))
        finally:
            _var_s.make_context = _mk_r
        # groupées par process, des formes au hachurage tournant gravent
        # l'angle de chaque passe, comme chacune seule
        _tourne_g_r = _rep_g(PRESET_RECIPES[1], hatch_mm=0.5, passes=3,
                             hatch_angle_step_deg=90, wobble='none')
        _doc_g_r = Document(name='groupe tournant')
        _doc_g_r.add(Rect(width=10, height=6, recipe=_tourne_g_r))
        _doc_g_r.add(_Cercle_r(x=15, width=8, height=8, recipe=_tourne_g_r))

        def _par_passe_r(_passes):
            _out = {}
            for _p in _passes:
                _out.setdefault(_p.index, []).extend(
                    tuple(map(tuple, _q)) for _q in _p.polylines)
            return {_i: sorted(_v) for _i, _v in _out.items()}
        _seules_r = _par_passe_r(_tp_v.build_passes(_doc_g_r))
        _groupees_r = _par_passe_r(_tp_v.build_passes(
            _doc_g_r, group_by_recipe=True))
        _angles_r = (_seules_r == _groupees_r and len(_groupees_r) == 3
                     and _groupees_r[0] != _groupees_r[1])
        check('relecture : passes dans la clé, toutes les pièces vérifiées, '
              'un seul instant, passes groupées tournantes',
              _huit_r and _quatre_r and _milieu_r and _angles_r
              and len(_instants_r) >= 6 and len(set(_instants_r)) == 1,
              f'8 → 4 passes : refus levé {_quatre_r} · pièce du milieu '
              f'vue {_milieu_r} · {len(_instants_r)} contexte(s), '
              f'{len(set(_instants_r))} instant(s) · passes groupées '
              f'{_angles_r}')

        # Le sablier pendant la vérification et l'écriture, et rendu même
        # quand l'écriture échoue.
        from PySide6.QtWidgets import QDialog as _QDlg_v, QMessageBox as _QMB_v
        _tab_v = window.new_tab()
        window.document.add(Rect(width=8, height=4, recipe=PRESET_RECIPES[1]))
        _vus_v = []
        _sauve_v = (window._export_destination, _pf_v.inspect,
                    _pf_v.PreflightDialog, iso.export, _QMB_v.critical,
                    session.preflight())
        _dossier_v = pathlib.Path(tempfile.mkdtemp(prefix='taudrive-sab-'))

        class _Recap_v:
            def __init__(self, *_a):
                pass

            def exec(self):
                return _QDlg_v.DialogCode.Accepted

            def skip_next_time(self):
                return False

        def _inspect_v(*a, **k):
            _vus_v.append(('vérif', QApplication.overrideCursor() is not None
                           and QApplication.overrideCursor().shape()
                           == _Qt.WaitCursor))
            return _sauve_v[1](*a, **k)

        def _export_v(*a, **k):
            _vus_v.append(('écriture', QApplication.overrideCursor()
                           is not None))
            raise OSError('disque plein (essai)')
        try:
            session.set_preflight(True)
            window._export_destination = lambda: (
                str(_dossier_v), _dossier_v / 'travail', '', 'travail')
            _pf_v.inspect = _inspect_v
            _pf_v.PreflightDialog = _Recap_v
            iso.export = _export_v
            _QMB_v.critical = staticmethod(lambda *a, **k: None)
            window._export()
        finally:
            (window._export_destination, _pf_v.inspect,
             _pf_v.PreflightDialog, iso.export, _QMB_v.critical) = _sauve_v[:5]
            del window._export_destination
            session.set_preflight(_sauve_v[5])
        check('export : sablier pendant la vérification et l\'écriture',
              _vus_v == [('vérif', True), ('écriture', True)]
              and QApplication.overrideCursor() is None
              and 'Export échoué' in window.statusBar().currentMessage(),
              f'{_vus_v} · {window.statusBar().currentMessage()[:40]}')

        # Un gros dessin importé ne se remet plus en texte à chaque
        # retouche : l'historique partage ses points, immuables, au lieu
        # de les refaire un à un, et l'instantané de session reprend le
        # texte de ce qui n'a pas bougé — le même texte, au caractère près.
        import dataclasses as _dc_l
        import json as _json_l
        import random as _rnd_l
        from engrave import serialize as _ser_l
        from engrave.history import History as _Hist_l
        from engrave.model import Path as _Path_l
        _g_l = _rnd_l.Random(7)
        _doc_l = Document(name='gros « dessin »')
        _doc_l.add(_Path_l(polylines=[
            [(_g_l.uniform(-40, 40), _g_l.uniform(-40, 40))
             for _ in range(500)] for _ in range(100)], layer='L'))
        _doc_l.add(Text(text='REF {n}', size_mm=4, recipe=PRESET_RECIPES[1]))
        _f_l = _doc_l.shapes[0]
        _ancien_l = {'type': 'path', **{
            _k: _v for _k, _v in _dc_l.asdict(_f_l).items()
            if _k != 'recipe'}, 'recipe': _dc_l.asdict(_f_l.recipe)}
        _meme_dict_l = (_json_l.dumps(_ancien_l, ensure_ascii=False)
                        == _json_l.dumps(_ser_l.shape_to_dict(_f_l),
                                         ensure_ascii=False))
        _h_l = _Hist_l(_doc_l)
        _doc_l.shapes[1].x += 1
        _h_l.record(_doc_l)
        _partage_l = (_h_l._states[-1]['shapes'][0]['polylines'][0][0]
                      is _f_l.polylines[0][0])
        session._FRAGMENTS.clear()
        _textes_l, _traces_l = [], []
        for _geste_l in range(4):
            if _geste_l == 1:
                _doc_l.shapes[1].x += 1             # le texte bouge
            elif _geste_l == 2:
                _f_l.x += 1                         # le dessin bouge
            elif _geste_l == 3:
                _f_l.polylines[0][0] = (0.5, 0.5)   # un point, en place
            _ent_l = [{'path': None, 'dirty': True,
                       'document': _ser_l.document_to_dict(_doc_l)}]
            _textes_l.append(session.snapshot_text(_ent_l)
                             == _json_l.dumps({'documents': _ent_l},
                                              ensure_ascii=False))
            _traces_l.append(session._FRAGMENTS[_f_l.id][2][1])
        # repris tant que les polylignes n'ont pas changé, réécrit ensuite
        _repris_l = (_traces_l[0] is _traces_l[1] is _traces_l[2]
                     and _traces_l[3] is not _traces_l[2])
        check('session : un gros dessin ne se réécrit pas à chaque retouche',
              _meme_dict_l and _partage_l and all(_textes_l) and _repris_l,
              f'points partagés {_partage_l} · texte identique '
              f'{sum(_textes_l)}/4 · polylignes reprises {_repris_l}')

        # --- annuler / refaire -------------------------------------------------

        tab = window.new_tab()
        for _ in range(3):
            tab.document.add(Rect(width=5, height=5, recipe=PRESET_RECIPES[1]))
            tab.history.record(tab.document)
        annulables, refaisables = tab.history.depth()
        tab.history.undo()
        apres = tab.history.depth()
        check('annuler / refaire : pile cohérente',
              (annulables, refaisables) == (3, 0) and apres == (2, 1),
              f'{annulables} annulable(s) → {apres}')

        # Le rechargement provoqué par un « annuler » reprogrammait un
        # instantané, que le « refaire » posait avant de se déplacer : la
        # branche refaisable était coupée par le geste censé la parcourir.
        tab.history.redo()
        window.tabs.setCurrentWidget(tab)
        app.processEvents()
        window.document.add(Rect(width=7, height=7, recipe=PRESET_RECIPES[1]))
        window._record_history()
        plein = len(window.document.shapes)
        window._undo()
        app.processEvents()
        vide = len(window.document.shapes)
        window._redo()
        app.processEvents()
        check('refaire restitue bien ce qui vient d\'être annulé',
              len(window.document.shapes) == plein and vide == plein - 1,
              f'{plein} → {vide} → {len(window.document.shapes)} formes')

        check('interface en français',
              QApplication.translate('QPlatformTheme', 'Cancel') == 'Annuler',
              QApplication.translate('QPlatformTheme', 'Cancel'))

        # --- mode simple : ce qui ne doit pas se voir ---------------------------

        caches = [(d.windowTitle(), d.isVisible(),
                   d.toggleViewAction().isVisible()) for d in window._expert_docks]
        check('mode simple : source laser et lot/série masqués',
              len(caches) == len(window._expert_docks) == 2
              and not any(v or m for _, v, m in caches),
              ' · '.join(t for t, _, _ in caches))

        from engrave.app import CONTACT
        aide = next((a for a in window.menuBar().actions() if a.text() == '&?'),
                    None)
        entrees = [x.text() for x in aide.menu().actions()] if aide else []
        check('menu « ? » présent, avec le contact',
              bool(entrees) and any(CONTACT in e for e in entrees),
              ' · '.join(entrees))

        # Une étiquette d'unité rendue visible avant d'avoir un parent devient
        # une fenêtre : Windows refuse sa géométrie et le journal se remplit.
        from engrave.widgets import Spin
        champ = Spin(1.0, 0, 10, 1, 3, ' mm')
        check('les champs ne créent pas de fenêtre parasite',
              not champ._unit.isWindow() and champ._unit.parent() is champ)
        champ.deleteLater()

        try:
            import ezdxf                                    # noqa: F401
            from engrave import dxfimport                   # noqa: F401
            check('import DXF disponible', True, ezdxf.__version__)
        except Exception as exc:
            check('import DXF disponible', False, exc)

        try:
            from serial.tools import list_ports
            check('port série disponible', True,
                  f'{len(list(list_ports.comports()))} port(s)')
        except Exception as exc:
            check('port série disponible', False, exc)

        try:
            from jpt.client import JptClient, SimulatedSource
            with JptClient(SimulatedSource()) as laser:
                ok = laser.set_power_percent(50)
            check('client laser JPT', ok)
        except Exception as exc:
            check('client laser JPT', False, exc)

    if domaine('plugins'):
        _plugins_grappe(check)

    rates = [l for l, ok, _ in checks if not ok]
    print(f'\n{len(checks) - len(rates)}/{len(checks)} contrôles passés')
    if rates:
        print('\nÉchecs :')
        for label in rates:
            print(f'  · {label}')
    return 1 if rates else 0


def _plugins_grappe(check) -> None:
    """Grappe `plugins` : le mécanisme, puis les plugins posés.

    Le mécanisme s'éprouve avec un plugin d'essai écrit dans un dossier
    temporaire, et un plugin cassé qui ne doit rien empêcher. Viennent
    ensuite les plugins posés à côté de l'exécutable (ou dans le dossier de
    l'utilisateur) : chargés sans erreur, puis leurs propres contrôles —
    ceux de l'édition d'un atelier portent sur ses données.
    """
    import tempfile
    from engrave import app as _app_pl, couples, model, plugins
    plugins.reset()
    with tempfile.TemporaryDirectory() as tmp:
        essai = pathlib.Path(tmp) / 'atelier_autotest'
        essai.mkdir()
        (essai / '__init__.py').write_text(
            "PLUGIN = {'nom': 'Essai', 'version': '0.1', 'api': 1}\n"
            "def register(api):\n"
            "    from engrave.model import Recipe\n"
            "    api.add_recipes([Recipe('Atelier', 50.0, 80.0, 100, 70000.0,\n"
            "                            tool_number=7)])\n"
            "    api.set_recipe_defaults(tool_number=9)\n"
            "    api.add_couples([(200, 60, 'Client A')])\n"
            "    api.set_machine('Machine essai')\n"
            "    api.add_autotest('essai', lambda check: check('x', True))\n",
            encoding='utf-8')
        casse = pathlib.Path(tmp) / 'atelier_autotest_casse'
        casse.mkdir()
        (casse / '__init__.py').write_text("raise RuntimeError('casse')\n",
                                           encoding='utf-8')
        vus = plugins.load([tmp], force=True)
        check('plugins : un plugin cassé n\'empêche rien, il est dit',
              sorted((p.module, p.ok) for p in vus)
              == [('atelier_autotest', True), ('atelier_autotest_casse', False)]
              and any('non chargé' in x for x in plugins.about_lines()),
              ' · '.join(p.label() for p in vus))
        check('plugins : process, défauts, couples, machine apportés',
              [r.name for r in model.factory_recipes()] == ['Atelier']
              and model.default_recipe().tool_number == 9
              and [c.name for c in couples.workshop()] == ['Client A']
              and _app_pl.machine_label() == 'Machine essai'
              and len(plugins.REGISTRY.autotests) == 1,
              f'{len(model.factory_recipes())} process · '
              f'T{model.default_recipe().tool_number} · '
              f'{_app_pl.machine_label()}')
        plugins.reset()
        for nom in ('atelier_autotest', 'atelier_autotest_casse'):
            sys.modules.pop(nom, None)
        if tmp in sys.path:
            sys.path.remove(tmp)
    check('plugins : oubliés, le cœur retrouve ses valeurs neutres',
          model.factory_recipes() == model.PRESET_RECIPES
          and model.default_recipe() == model.Recipe()
          and _app_pl.machine_label() == _app_pl.MACHINE)

    # les plugins posés : à côté de l'exécutable, chez l'utilisateur
    vus = plugins.load(force=True)
    check('plugins : ceux posés se chargent sans erreur',
          all(p.ok for p in vus),
          ' · '.join(p.label() for p in vus) or 'aucun plugin posé')
    for nom, fn in list(plugins.REGISTRY.autotests):
        try:
            fn(check)
        except Exception as exc:                    # noqa: BLE001
            check(nom, False, f'{type(exc).__name__} : {exc}')


def main() -> int:
    if '--autotest' in sys.argv:
        return autotest()
    if '--convert' in sys.argv:
        return _convertir()
    from engrave.app import main as run
    return run()


def _convertir() -> int:
    """Conversion en ligne de commande, sans ouvrir de fenêtre.

    Sert au menu contextuel de l'explorateur. Une application Qt est
    quand même créée — sans elle, `QSettings` n'aurait pas d'identité et
    les réglages de l'atelier (tolérance, chemins des convertisseurs)
    seraient ignorés — mais aucune fenêtre n'est montrée.
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName('Cielle')
    app.setApplicationName('TauDrive')
    # les process par défaut de l'atelier vont aux formes converties
    from engrave import plugins
    plugins.load()
    from engrave.convert import run
    return run()


if __name__ == '__main__':
    raise SystemExit(main())
