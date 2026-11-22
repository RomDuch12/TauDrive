"""Guide des paramètres laser / Laser parameter guide.

Ce que le bouton **?** du gestionnaire de process ouvre : ce qu'il faut
savoir pour régler une process sur *cette* machine, et non sur une machine
en général.

Trois parties, dans l'ordre où l'on en a besoin :

1. **la physique** — ce que chaque réglage fait au métal ;
2. **ce que la source tient** — les treize formes d'onde, et l'audit des
   recommandations qui circulent ;
3. **remplissage et oscillation** — les deux transformations de
   trajectoire que TauDrive ajoute, et ce qu'elles coûtent ;
4. **formats de fichier** — ce qui s'importe, ce qui s'exporte, et ce
   qu'il faut installer pour le CorelDRAW.

Le guide est produit **à partir des données du programme** : la table des
couples, l'audit des recommandations, les constantes d'oscillation. Il ne
peut donc pas dériver de ce que le programme fait réellement — un guide
qui décrirait une autre version serait pire qu'aucun guide.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QTabWidget,
                               QTextBrowser, QVBoxLayout)

from . import advice, couples, wobble
from .widgets import fit_to_screen


def _escape(text: str) -> str:
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


def style() -> str:
    """La feuille de style de l'aide, prise dans le thème courant.

    Une constante ne pouvait pas convenir : l'aide s'ouvre sous le thème
    de l'atelier, et un gris fixe y était mesuré à 3,06 de contraste sur
    les huit thèmes clairs — sous le seuil lisible de 4,5.
    """
    from . import theme
    return """
<style>
 body { line-height: 1.45; }
 h2 { margin-top: 18px; }
 table { border-collapse: collapse; margin: 8px 0; }
 td, th { padding: 3px 12px 3px 0; text-align: left; vertical-align: top; }
 th { border-bottom: 1px solid %(bord)s; }
 .refuse { color: %(alarm)s; }
 .reserve { color: %(warn)s; }
 .tenu { color: %(ok)s; }
 .note { color: %(dim)s; }
 code { font-family: Consolas, monospace; }
</style>
""" % {'bord': theme.hex_of('border'), 'alarm': theme.hex_of('alarm'),
       'warn': theme.hex_of('warn'), 'ok': theme.hex_of('ok'),
       'dim': theme.hex_of('text_dim')}


def physics_html() -> str:
    """Ce que chaque réglage fait au métal."""
    return style() + """
<h2>Les quatre réglages, et ce qu'ils font</h2>

<p>Une source <b>MOPA</b> — celle de cette machine — permet de régler la
durée d'impulsion <b>indépendamment</b> de la fréquence. C'est ce qui la
sépare d'une source Q-switch, et c'est le réglage le plus puissant dont on
dispose pour commander la physique de l'impact.</p>

<table>
<tr><th>Réglage</th><th>Ce qu'il commande</th><th>Ce qu'on obtient</th></tr>
<tr><td><b>Durée d'impulsion</b> τ</td>
    <td>la façon dont l'énergie est délivrée</td>
    <td><b>courte</b> (2 à 13 ns) : forte puissance de crête, peu de
        chaleur transmise — marquage fin, sans bavure ni relief.<br>
        <b>longue</b> (200 à 500 ns) : l'énergie s'accumule — c'est ainsi
        qu'on creuse ou qu'on fait fondre.</td></tr>
<tr><td><b>Fréquence</b> f</td>
    <td>le nombre de tirs par seconde</td>
    <td>à puissance moyenne constante, monter la fréquence <b>divise
        l'énergie de chaque tir</b>. Haute fréquence = surface travaillée
        finement ; basse fréquence = chaque impact creuse.</td></tr>
<tr><td><b>Puissance</b> P</td>
    <td>l'énergie moyenne</td>
    <td>le réglage le plus évident, et le moins fin. On l'ajuste en
        dernier, une fois le couple f-τ choisi.</td></tr>
<tr><td><b>Vitesse</b> v</td>
    <td>l'espacement des impacts</td>
    <td>le faisceau avance de <code>v / f</code> entre deux tirs. C'est le
        <b>pas d'impulsion</b>, et c'est lui qui décide si la gravure est
        continue ou pointillée.</td></tr>
</table>

<h2>Le pas d'impulsion, ce qui lie vitesse et fréquence</h2>

<p>Le spot fait <b>0,03 mm</b> sur la majorité des outils de cette
machine. Si <code>v / f</code> dépasse ce diamètre, les impacts ne se
touchent plus et la gravure devient pointillée.</p>

<p>La règle utilisable :</p>

<p><code>v_max (mm/min) &asymp; 60 &times; f (Hz) &times; &Oslash;spot (mm)
/ k</code></p>

<p><code>k</code> est le recouvrement voulu : <b>2 pour un marquage
propre</b>, 1 à la limite du pointillé. TauDrive calcule ce recouvrement
pour chaque recommandation, et le signale quand il descend sous 2.</p>

<p class="note">C'est ce qu'on retrouve dans un magasin d'outils bien
réglé : à 200 m/min, il faut 120 kHz ou plus ; à 80 m/min, 80 kHz
suffisent — pas de 0,0167 mm, soit un recouvrement de 2×.</p>

<h2>Le rapport cyclique</h2>

<p><code>&tau; &times; f</code> donne la fraction du temps pendant
laquelle la source émet. Au-delà de <b>5 %</b>, une MOPA de cette classe
ne tient plus sa puissance de crête : l'impulsion s'affaisse, et le
réglage ne fait plus ce qu'il annonce.</p>

<p>Les treize formes d'onde de la source vont de 0,26 % à 1,85 % — la
table est cohérente d'un bout à l'autre. Six outils du magasin dépassent
5 %, dont un à 25 % : ceux-là n'ont probablement jamais été validés sur
pièce.</p>
"""


def source_html() -> str:
    """Les formes d'onde, et l'audit des recommandations."""
    table = couples.factory()
    lignes = [style(), '<h2>Les treize formes d\'onde de la source</h2>',
              '<p>Chaque durée d\'impulsion a sa <b>fréquence de répétition '
              'nominale</b>. La section suivante montre que ce n\'est pas '
              'un plafond dur — mais c\'est le point de fonctionnement '
              'annoncé, et le repère à partir duquel juger.</p>',
              '<table><tr><th>&tau; (ns)</th><th>f nominale (kHz)</th>'
              '<th>rapport cyclique</th><th>usage typique</th></tr>']
    usages = {
        2: 'marquage couleur, nettoyage de fond',
        9: 'marquage fin, couleur',
        13: 'marquage fin',
        20: 'marquage courant',
        30: 'marquage noir sur acier',
        45: 'marquage contrasté',
        60: 'marquage courant, satinage',
        80: 'satinage, blanchiment',
        100: 'blanc givré sur alu',
        200: 'gravure, début de relief',
        250: 'gravure',
        350: 'gravure profonde',
        500: 'gravure profonde, sublimation du laiton',
    }
    for c in table:
        lignes.append(
            f'<tr><td><b>{c.pulse_width_ns:g}</b></td>'
            f'<td>{c.frequency_khz:g}</td>'
            f'<td>{c.duty_percent():.2f} %</td>'
            f'<td class="note">{usages.get(c.pulse_width_ns, "")}</td></tr>')
    lignes.append('</table>')
    lignes.append(
        '<p class="note">Relevée sur la machine : la table est dans le '
        'firmware de la source, que la GUI JPT interroge en RS-232 au '
        'démarrage. Aucun fichier livré ne la porte.</p>')
    lignes.append(
        '<h2>La table est nominale, pas impérative</h2>'
        '<p>Le magasin de la machine — 72 outils qui <b>ont gravé</b> — '
        'dépasse régulièrement ces plafonds :</p>'
        '<table><tr><th>&tau; (ns)</th><th>table</th><th>magasin</th>'
        '<th>rapport</th></tr>')
    from . import advice as _a
    for c in table:
        vu = _a.observed_max(c.pulse_width_ns)
        if vu is None or vu <= c.frequency_khz:
            continue
        lignes.append(
            f'<tr><td>{c.pulse_width_ns:g}</td>'
            f'<td>{c.frequency_khz:g}</td><td><b>{vu:g}</b></td>'
            f'<td>&times;{vu / c.frequency_khz:.1f}</td></tr>')
    lignes.append('</table>')
    lignes.append(
        '<p>Les dépassements modérés ont tous un rapport cyclique sain : '
        'la table est donc vraisemblablement la liste des formes d\'onde '
        'avec leur <b>fréquence nominale</b>, et non un plafond dur.</p>'
        '<p>C\'est pourquoi l\'audit ne <span class="refuse">refuse</span> '
        'que ce qui est hors de portée physique — au-delà de 500 ns, de '
        '200 m/min, ou de 5 % de rapport cyclique — et se contente d\'une '
        '<span class="reserve">réserve</span> pour ce qui sort de la table '
        'sans sortir de la machine. Refuser sur la seule table serait '
        'crier au loup.</p>')

    atelier = couples.workshop()
    if atelier:
        lignes.append('<h2>Les couples d\'atelier</h2>')
        lignes.append('<p>Mesurés sur pièce, gardés parce qu\'ils '
                      'marchent, et nommés d\'après le travail qu\'ils '
                      'servent.</p><table>')
        for c in atelier:
            lignes.append(f'<tr><td><b>{c.key()}</b></td>'
                          f'<td>{_escape(c.name)}</td></tr>')
        lignes.append('</table>')

    lignes.append('<h2>Recommandations, et ce qu\'elles valent ici</h2>')
    lignes.append(
        '<p>Des jeux de paramètres circulent : forums, notices, assistants '
        'conversationnels. Ils sont souvent <b>justes en physique et faux '
        'sur la machine</b> — parce qu\'ils viennent d\'une autre source, '
        'd\'une autre lentille, ou d\'aucune machine en particulier.</p>'
        '<p>Chacune est confrontée à ce que la machine sait faire. Les '
        'refusées sont <b>montrées, pas cachées</b> : savoir qu\'un réglage '
        'est hors d\'atteinte vaut mieux que de le chercher.</p>')

    verdicts = advice.audited()
    tenues = sum(1 for v in verdicts if v.level == advice.TENU)
    lignes.append(
        f'<p><b>{tenues} sur {len(verdicts)}</b> tiennent telles quelles.</p>')
    lignes.append(
        '<table><tr><th>Matière — rendu</th><th>Couple</th>'
        '<th>Vitesse</th><th>Pas · recouvrement</th><th>Verdict</th></tr>')
    for v in verdicts:
        a = v.advice
        classe = {advice.TENU: 'tenu', advice.RESERVE: 'reserve'}.get(
            v.level, 'refuse')
        corrige = advice.corrected(a)
        verdict = v.level
        if corrige is not None:
            verdict += f' &rarr; <b>{corrige.couple()}</b>'
        lignes.append(
            f'<tr><td>{_escape(a.label())}</td>'
            f'<td><code>{a.couple()}</code></td>'
            f'<td>{a.speed_m_min():.0f} m/min</td>'
            f'<td>{a.pitch_mm():.4f} mm · {a.overlap():.1f}&times;</td>'
            f'<td class="{classe}">{verdict}</td></tr>')
        if a.why:
            lignes.append(f'<tr><td colspan="5" class="note">'
                          f'{_escape(a.why)}</td></tr>')
        for note in v.notes:
            lignes.append(f'<tr><td colspan="5" class="{classe}">· '
                          f'{_escape(note)}</td></tr>')
    lignes.append('</table>')
    lignes.append(
        '<p class="note">Une recommandation est un <b>point de départ à '
        'valider sur chute</b>, jamais un réglage de production. C\'est le '
        'rôle du coupon d\'essai — et l\'axe « couple F-T » y fait varier '
        'les formes d\'onde une par une.</p>')
    return '\n'.join(lignes)


def strategy_html() -> str:
    """Remplissage et oscillation : ce qu'ils font, ce qu'ils coûtent."""
    lignes = [style(), '<h2>Le remplissage</h2>',
              '<p>Quatre réglages, qui ne changent rien au laser et tout '
              'au résultat.</p>',
              '<table><tr><th>Réglage</th><th>Effet</th></tr>',
              '<tr><td><b>Pas de hachure</b></td>'
              '<td>l\'écart entre deux lignes de remplissage. Plus fin que '
              'le spot (0,03 mm), les lignes se recouvrent et la surface '
              'est pleine ; plus large, elle est striée.</td></tr>',
              '<tr><td><b>Angle</b></td>'
              '<td>l\'orientation des lignes. Sur une pièce longue, '
              'hachurer en travers évite les longs allers-retours.</td></tr>',
              '<tr><td><b>Rotation par passe</b></td>'
              '<td>l\'angle ajouté à chaque passe. À 0, toutes les passes '
              'suivent le même sens : les creux du premier passage guident '
              'le second, et le fond sort strié. À 45 ou 90°, les '
              'trajectoires se croisent et le fond est plat. <b>C\'est la '
              'manière classique de creuser proprement</b>, et elle ne '
              'coûte qu\'un calcul.</td></tr>',
              '<tr><td><b>Croisé</b></td>'
              '<td>une seconde nappe à +90° dans la <b>même</b> passe. À '
              'distinguer de la rotation par passe : ici les deux '
              'directions sont gravées au même Z. Deux fois le trajet, '
              'mais une surface homogène en un seul passage — ce qu\'on '
              'veut sur un marquage noir, où la profondeur n\'entre pas en '
              'jeu.</td></tr>',
              '<tr><td><b>Retrait</b></td>'
              '<td>le remplissage s\'arrête sur la frontière, mais le '
              'faisceau a une largeur et déborde d\'un demi-spot. Rentrer '
              'de <b>0,015 mm</b> met le bord de la zone gravée exactement '
              'sur le contour.</td></tr>',
              '</table>',
              '<h2>L\'oscillation du faisceau</h2>',
              '<p>Superposer une oscillation au déplacement élargit le '
              'trait <b>en un seul passage</b> : un spot de 0,03 mm trace '
              'une bande de 0,2 mm, avec une densité homogène d\'un bord à '
              'l\'autre.</p>',
              '<p>La machine ne l\'offre pas : TauDrive la fait dans la '
              'géométrie, avant l\'export. C\'est une transformation de '
              'trajectoire, au même titre que le hachurage.</p>',
              '<table><tr><th>Forme</th><th>Ce qu\'elle donne</th>'
              '<th>Longueur × (a = 0,1 · pas = 0,4)</th></tr>']
    for cle, nom, note in wobble.SHAPES:
        if cle == 'none':
            continue
        facteur = wobble.length_factor(0.1, 0.4, cle)
        lignes.append(f'<tr><td><b>{nom}</b></td><td>{_escape(note)}</td>'
                      f'<td>&times;{facteur:.1f}</td></tr>')
    lignes.append('</table>')

    lignes.append('<h2>Ce que l\'oscillation coûte — et sa vraie limite</h2>')
    lignes.append(
        '<p>Le piège n\'est pas la longueur gravée, qu\'on voit tout de '
        'suite. C\'est la <b>cadence demandée au scanner</b> : une '
        'oscillation par pas parcouru, soit <code>v / pas</code>.</p>')
    lignes.append('<table><tr><th>Vitesse</th>'
                  '<th>pas 0,1 mm</th><th>pas 0,4 mm</th>'
                  '<th>pas 1,0 mm</th></tr>')
    for v_m in (3, 6, 12, 24, 80):
        cellules = []
        for pas in (0.1, 0.4, 1.0):
            hz = wobble.scanner_hz(v_m * 1000, pas)
            classe = ('refuse' if hz > wobble.SCANNER_MAX_HZ
                      else 'reserve' if hz > wobble.SCANNER_SAFE_HZ
                      else 'tenu')
            cellules.append(f'<td class="{classe}">{hz:.0f} Hz</td>')
        lignes.append(f'<tr><td><b>{v_m} m/min</b></td>'
                      + ''.join(cellules) + '</tr>')
    lignes.append('</table>')
    lignes.append(
        f'<p>Un galvo de marquage tient <b>{wobble.SCANNER_SAFE_HZ:.0f} Hz</b> '
        f'sans faiblir, <b>{wobble.SCANNER_MAX_HZ:.0f} Hz</b> à la limite. '
        f'Au-delà, la commande part mais le miroir ne suit pas : '
        f'l\'oscillation s\'arrondit, puis s\'efface, et la bande n\'est '
        f'pas plus large qu\'un trait simple — sans que rien ne '
        f'l\'annonce sur l\'écran.</p>')
    lignes.append(
        '<p><b>C\'est la conséquence pratique à retenir : sur cette '
        'machine, osciller impose de ralentir.</b> Une bande de 0,2 mm au '
        'pas de 0,4 mm ne tient que jusqu\'à 12 m/min. TauDrive calcule '
        'cette limite sous les champs, et la vérification avant export '
        'refuse un travail qui la dépasse.</p>')
    lignes.append(
        '<p class="note">La phase de l\'oscillation suit la <b>longueur '
        'parcourue</b>, pas le paramètre du segment. C\'est le piège de la '
        'formule qu\'on trouve partout : avec θ = t × f et t de 0 à 1 le '
        'long du segment, un DXF dont les segments vont de 0,1 mm à 20 mm '
        'reçoit une oscillation deux cents fois plus serrée sur l\'un que '
        'sur l\'autre.</p>')
    return '\n'.join(lignes)


def formats_html() -> str:
    """Ce qui s\'importe, ce qui s\'exporte, et ce qu\'il faut
    installer."""
    from . import vecimport, vecexport
    etat = vecimport.converter_status()

    lignes = [style(), '<h2>Ce que TauDrive lit</h2>',
              '<table><tr><th>Format</th><th>Ce que c\'est '
              'réellement</th><th>Lecture</th></tr>',
              '<tr><td><code>.dxf</code></td><td>DXF</td>'
              '<td class="tenu">native, un calque par calque</td></tr>',
              '<tr><td><code>.pdf</code></td><td>PDF</td>'
              '<td class="tenu">native</td></tr>',
              '<tr><td><code>.ai</code> v9 et au-delà</td>'
              '<td><b>un PDF</b>, avec un flux privé Adobe en plus</td>'
              '<td class="tenu">native</td></tr>',
              '<tr><td><code>.ai</code> v8 et avant</td>'
              '<td><b>un EPS</b> PostScript</td>'
              '<td class="tenu">native</td></tr>',
              '<tr><td><code>.eps</code> <code>.ps</code></td>'
              '<td>PostScript encapsulé</td>'
              '<td class="tenu">native</td></tr>',
              '<tr><td><code>.cdr</code></td><td>CorelDRAW</td>'
              '<td class="reserve">par convertisseur externe</td></tr>',
              '</table>',
              '<p class="note">Le format est reconnu <b>au contenu, pas au '
              'suffixe</b> : un <code>.ai</code> est un PDF ou un EPS selon '
              'la version qui l\'a écrit.</p>',

              '<h2>Ce que TauDrive écrit</h2>',
              '<p><i>Fichier ▸ Exporter le dessin</i> — pour un bureau '
              'd\'études, un client, un graphiste. L\'export '
              'machine, lui, reste sur le bouton <b>Exporter</b>.</p>',
              '<table><tr><th>Format</th><th>Qui l\'ouvre</th></tr>']
    for cle, libelle, _ in vecexport.FORMATS:
        qui = {'dxf': 'AutoCAD, SolidWorks, LibreCAD, CorelDRAW, Inkscape…',
               'eps': 'Illustrator, CorelDRAW, Inkscape, toute imprimante '
                      'PostScript',
               'ai': 'Illustrator — le fichier produit est un EPS, que '
                     'toutes ses versions savent ouvrir'}.get(cle, '')
        lignes.append(f'<tr><td><code>.{cle}</code> — {libelle}</td>'
                      f'<td>{qui}</td></tr>')
    lignes.append('</table>')
    lignes.append(
        '<p>Deux contenus au choix : le <b>dessin</b> — les contours tels '
        'qu\'on les a posés — ou les <b>trajectoires</b>, tout ce qui '
        'part à la machine, hachurage et oscillation compris. Le second est '
        'souvent cent fois plus lourd.</p>')

    lignes.append('<h2>Le CorelDRAW, et ce qu\'il faut installer</h2>')
    lignes.append(
        '<p>Le <code>.cdr</code> est propriétaire, non documenté, et change '
        'à chaque version majeure depuis 1989. Aucun lecteur libre n\'en '
        'couvre toutes les versions, et TauDrive n\'en embarque pas.</p>'
        '<p><b>La voie la plus sûre reste d\'exporter depuis '
        'CorelDRAW</b> en PDF, EPS, AI ou DXF : TauDrive lit les quatre '
        'nativement, sans perte, et le dessin passe par le moteur de Corel '
        'lui-même.</p>'
        '<p>À défaut, TauDrive emploie un convertisseur installé sur le '
        'poste :</p>')
    lignes.append(
        '<table><tr><th>Convertisseur</th><th>Version minimale</th>'
        '<th>Pourquoi cette borne</th><th>Où l\'obtenir</th></tr>'
        '<tr><td><b>Inkscape</b></td><td>1.0</td>'
        '<td>c\'est la version qui a introduit '
        '<code>--export-type</code>. La lecture du CDR elle-même remonte à '
        '0.91, par <code>libcdr</code> — TauDrive sait encore appeler '
        'l\'ancienne forme <code>--export-pdf</code>.</td>'
        '<td>inkscape.org/release</td></tr>'
        '<tr><td><b>LibreOffice</b></td><td>6.0</td>'
        '<td><code>--headless --convert-to</code> est stable bien avant, et '
        '<code>libcdr</code> lit le CDR depuis LibreOffice 4.0 : 6.0 est '
        'simplement le plus ancien millésime encore raisonnable à installer '
        'aujourd\'hui.</td>'
        '<td>libreoffice.org/download</td></tr></table>')
    lignes.append(
        '<p class="note">Les deux emploient le même lecteur, '
        '<code>libcdr</code>. Inkscape est préféré : le chemin est plus '
        'court et le PDF plus fidèle.</p>')

    lignes.append('<h2>Sur ce poste</h2>')
    if not etat.get('trouve'):
        lignes.append(
            '<p class="reserve"><b>Aucun convertisseur installé.</b> Les '
            'fichiers <code>.cdr</code> seront refusés — avec le message '
            'qui dit quoi faire. Tous les autres formats se lisent.</p>')
    else:
        version = etat.get('version') or 'version inconnue'
        classe = 'refuse' if etat.get('trop_vieux') else 'tenu'
        verdict = ('trop ancien pour cette commande'
                   if etat.get('trop_vieux') else 'convient')
        lignes.append(
            f'<table><tr><td><b>{etat["genre"]}</b></td>'
            f'<td>{version}</td>'
            f'<td class="{classe}">{verdict}</td></tr>'
            f'<tr><td colspan="3" class="note">'
            f'{_escape(etat["chemin"])}</td></tr></table>')
    return chr(10).join(lignes)


class Guide(QDialog):
    """Le guide des paramètres, ouvert par le bouton **?**."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Guide des paramètres laser')
        self.setMinimumSize(760, 560)

        dehors = QVBoxLayout(self)
        self.w_tabs = QTabWidget()
        for titre, contenu in (('Physique', physics_html()),
                               ('La source', source_html()),
                               ('Remplissage et oscillation',
                                strategy_html()),
                               ('Formats de fichier', formats_html())):
            vue = QTextBrowser()
            vue.setOpenExternalLinks(False)
            vue.setHtml(contenu)
            self.w_tabs.addTab(vue, titre)
        dehors.addWidget(self.w_tabs, 1)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        boutons.button(QDialogButtonBox.StandardButton.Close).setText(
            'Fermer')
        boutons.rejected.connect(self.reject)
        boutons.accepted.connect(self.accept)
        dehors.addWidget(boutons)
        fit_to_screen(self)
