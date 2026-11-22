"""Modèle de document de gravure / Engraving document model.

Toutes les longueurs sont en **millimètres**, repère machine : X vers la
droite, **Y vers le haut**, origine au centre du champ de marquage.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field, replace

from . import plugins as _plugins

# --- machine ---------------------------------------------------------------

#: Champ de marquage de la TAU 10x10 SMART (lentille f-theta 160 mm).
#: Les vitesses se **saisissent et s'affichent en m/min**, comme la
#: machine les rapporte (`Vel.=80.000m/min`) et comme ses propres outils
#: se nomment (`OT_SGROSSA_130KHz_80m/min`). Le modèle et l'ISO, eux,
#: restent en mm/min : c'est l'unité du mot `F`, et la convertir là serait
#: introduire un facteur 1000 sur le chemin de la machine.
SPEED_UNIT = 'm/min'
SPEED_TO_DISPLAY = 0.001
SPEED_FROM_DISPLAY = 1000.0

FIELD_W_MM = 110.0
FIELD_H_MM = 110.0


@dataclass(frozen=True)
class Treatment:
    """Réglages de mise en négatif, figés dans une recette.

    Une recette peut porter un **traitement** : cadre, marge, offset de
    contour et épaisseur de trait, appliqués au dessin avant la gravure.

    Les valeurs sont **copiées**, jamais référencées. Le nom du modèle
    dont elles viennent n'est gardé que pour mémoire : supprimer ce modèle
    de la bibliothèque **ne casse aucune recette**, puisque plus rien ne
    va le chercher. C'est la seule façon d'avoir des modèles qu'on ose
    ranger.
    """
    name: str = ''
    frame: str = 'rect'
    margin_mm: float = 1.0
    offset_mm: float = 0.0
    line_width_mm: float = 0.0
    line_step_mm: float = 0.05

    def describe(self) -> str:
        if self.frame == 'none' and not self.line_width_mm:
            return 'sans effet'
        bouts = []
        if self.frame != 'none':
            bouts.append(f'cadre {self.frame}, marge {self.margin_mm:g} mm')
        if self.offset_mm:
            bouts.append(f'offset {self.offset_mm:+g} mm')
        if self.line_width_mm:
            bouts.append(f'trait {self.line_width_mm:g} mm')
        return ' · '.join(bouts)


@dataclass(frozen=True)
class Recipe:
    """Jeu de paramètres laser — équivalent d'un « utensile » Cielle.

    Les valeurs par défaut sont neutres : un marquage sur le couple
    constructeur 80 kHz / 100 ns. Un atelier apporte les siennes par un
    plugin ; une process neuve se fait donc par `default_recipe`, qui les
    applique, et non par `Recipe()`.
    """
    name: str = 'Process'
    power_percent: float = 100.0
    frequency_khz: float = 80.0        # 80 kHz  (recette machine : 80000 Hz)
    pulse_width_ns: int = 100
    speed_mm_min: float = 40000.0      # mot F du dialecte ISO Cielle
    #: **Nb_passe** du magasin d'outils : nombre de passages.
    passes: int = 1
    #: Pas de hachurage pour le remplissage, en mm. 0 = contour seul.
    hatch_mm: float = 0.0
    #: Angle du hachurage, en degrés.
    hatch_angle_deg: float = 0.0
    #: Angle ajouté au hachurage **à chaque passe**, en degrés.
    #:
    #: 0 = toutes les passes dans le même sens, ce qui creuse des sillons :
    #: les creux du premier passage guident le second, et le fond sort
    #: strié. Une rotation de 45° ou 90° entre passes croise les
    #: trajectoires et donne un fond plat. C'est la manière classique de
    #: creuser proprement, et elle ne coûte rien de plus qu'un calcul.
    hatch_angle_step_deg: float = 0.0
    #: Hachurage croisé : une seconde nappe à +90° dans la **même** passe.
    #:
    #: À distinguer de la rotation par passe : ici les deux directions
    #: sont gravées l'une après l'autre au même Z. Deux fois plus de
    #: trajet, mais une surface homogène en un seul passage — ce qu'on
    #: veut sur un marquage noir, où la profondeur n'entre pas en jeu.
    hatch_cross: bool = False
    #: Retrait du hachurage par rapport au contour, en mm.
    #:
    #: Le remplissage s'arrête sur la frontière ; le faisceau, lui, a une
    #: largeur, et déborde donc d'un demi-spot. Rentrer le remplissage de
    #: 0,015 mm — la moitié du spot — met le bord de la zone gravée
    #: exactement sur le contour. Sans retrait, une contre-forme se
    #: referme d'un demi-spot de chaque côté.
    hatch_inset_mm: float = 0.0
    #: **Enchaîner les tracés** : moins d'allumages du laser.
    #:
    #: Sur cette machine, ce qui coûte est d'allumer, pas de graver :
    #: chaque allumage paie les rampes du SkyWrite, d'autant plus longues
    #: que la vitesse est haute. Un DataMatrix hachuré au vingtième en
    #: comptait 2 666, et prenait 15 s à 200 m/min pour 0,5 s de gravure
    #: utile. Coché :
    #:
    #: * les rangées successives d'une même île de remplissage se gravent
    #:   d'un seul trait (2 666 → 503 sur ce DataMatrix) ;
    #: * le remplissage d'un code aussi (649 → 39 sur la plaque en
    #:   négatif de production) ;
    #: * les fragments ouverts d'un contour qui se touchent par leurs
    #:   bouts sont joints (1 069 raccords sur un plan de production).
    #:
    #: Rien n'est gravé hors du dessin : un lien de remplissage longe le
    #: bord de la zone, un raccord de contour ne fait que relier deux
    #: tracés qui se touchaient déjà. Faux par défaut : une process
    #: enregistrée sans ce champ — toutes celles du poste de production
    #: — grave exactement comme avant.
    link_paths: bool = False
    #: **Style de remplissage** : 'hatch' (rangées parallèles) ou 'rings'
    #: (anneaux qui suivent le contour, voir `rings.py`).
    #:
    #: Le zigzag a supprimé les allumages, pas les demi-tours : au bout de
    #: chaque rangée, dès que le bord n'est pas perpendiculaire, le virage
    #: est plus fermé que les 89° du SkyWrite et le miroir freine comme
    #: pour un allumage. Les anneaux n'en ont pas — sur le DataMatrix
    #: dessiné de l'atelier, 2,3 s estimées à 100 m/min au lieu de 8,4.
    #: L'aspect change : des boucles concentriques au lieu de rangées.
    #: Angle, rotation par passe et croisement ne s'y appliquent pas.
    #: 'hatch' par défaut : une process d'avant grave comme avant, et
    #: l'ancienne version, qui ignore le champ, hachure.
    fill_style: str = 'hatch'

    # --- oscillation du faisceau ---
    #: Forme de l'oscillation superposée : 'none' | 'circle' | 'eight' |
    #: 'transverse'. Voir `wobble.py`.
    #:
    #: Elle élargit le trait en un seul passage — un spot de 0,03 mm trace
    #: une bande de 0,2 mm — avec une densité homogène d'un bord à
    #: l'autre. La machine ne l'offre pas : elle se fait dans la
    #: géométrie, avant l'export.
    wobble: str = 'none'
    #: Amplitude de l'oscillation, en mm. La bande fait deux fois cela.
    wobble_amp_mm: float = 0.0
    #: Avance par tour d'oscillation, en mm.
    #:
    #: C'est aussi ce qui fixe la **cadence demandée au scanner** :
    #: `v / pas`. À 80 m/min avec 0,1 mm de pas, 13 kHz — dix fois trop.
    #: La vérification avant export le signale.
    wobble_pitch_mm: float = 0.0
    #: Numéro d'outil émis dans l'ISO (`T<n>`). Doit correspondre à une
    #: entrée du magasin `dbpunte.mag` de la machine — voir export-iso.md.
    tool_number: int = 1

    #: Comment se règle la profondeur : `step` = **Profondeur_par_passe**
    #: imposée, comme le magasin d'outils la porte ; `total` = profondeur
    #: finale visée, dont le pas se déduit.
    depth_mode: str = 'step'
    #: **Zpasse** : descente entre deux passes, en mm.
    #:
    #: Le magasin d'outils de la machine porte toujours ce champ à côté du
    #: nombre de passes ; la valeur par défaut est celle relevée dans ses
    #: fichiers ISO — 4,673 µm. Une recette à un seul passage n'en subit
    #: aucun effet.
    depth_step_mm: float = 0.004673
    #: Profondeur finale visée, en mm, quand `depth_mode` vaut `total`.
    depth_total_mm: float = 0.0

    #: Traitement appliqué au dessin avant gravure, ou None.
    #:
    #: Les valeurs sont figées dans la recette : le modèle qui les a
    #: fournies peut disparaître sans rien casser.
    treatment: 'Treatment | None' = None

    #: Dossier de rangement dans la bibliothèque. Vide = à la racine.
    #:
    #: Une bibliothèque d'atelier finit à cinquante entrées : sans
    #: rangement, on ne retrouve plus la recette laiton parmi les essais.
    folder: str = ''

    #: Notes libres : sur quelle matière, avec quel résultat, quand.
    #:
    #: Une recette validée sur chute vaut par ce qu'on en sait, pas par ses
    #: chiffres. « 2 mm de laiton poli, très bon rendu, coupon du 14/03 »
    #: en dit plus que n'importe quel nom. Ce champ **part avec la
    #: recette** — bibliothèque partagée comprise — mais **jamais dans
    #: l'ISO** : la machine n'en a que faire.
    comment: str = ''

    def depth_of(self, index: int) -> float:
        """Cote Z de la passe `index` (0 pour la première), en mm.

        Négative vers le bas, comme dans les fichiers de la machine : le
        travail à trois passes relevé sur `EASY_LASER_Z0001_2.ISO` grave à
        `Z0`, `Z-0.004673` puis `Z-0.009347`.
        """
        return -self.depth_step() * max(0, index)

    def depth_step(self) -> float:
        """Pas effectif entre deux passes, quelle que soit la façon de le
        régler. Une recette à un seul passage n'a pas de pas."""
        if self.depth_mode == 'total':
            if self.passes <= 1:
                return 0.0
            return max(0.0, self.depth_total_mm) / (self.passes - 1)
        return max(0.0, self.depth_step_mm)

    def label(self) -> str:
        depth = self.depth_step()
        return (f'{self.name} — {self.power_percent:g} %, '
                f'{self.frequency_khz:g} kHz, '
                f'{self.speed_mm_min * SPEED_TO_DISPLAY:g} {SPEED_UNIT}'
                + (f', hachure {self.hatch_mm:g} mm' if self.hatch_mm else '')
                + (f', {self.passes} passes'
                   + (f' de {depth * 1000:g} µm' if depth > 0 else
                      ' en surface')
                   if self.passes > 1 else ''))


#: Préréglages du cœur libre : des exemples neutres, chacun sur un couple
#: constructeur de la source (`couples.FACTORY`), outil 1. Ils ne viennent
#: d'aucun atelier et sont à valider sur chute comme toute process.
#:
#: Les process relevées sur une machine, et les process par matière,
#: sont des **données d'atelier** : un plugin les apporte
#: (`plugins.Api.add_recipes`), et ses préréglages remplacent ceux-ci —
#: voir `factory_recipes`.
PRESET_RECIPES: tuple[Recipe, ...] = (
    Recipe('Repérage', 20.0, 170.0, 20, 60000.0),
    Recipe('Marquage', 100.0, 80.0, 100, 40000.0),
    Recipe('Gravure en deux passes', 100.0, 80.0, 100, 40000.0, passes=2),
    Recipe('Satinage', 20.0, 250.0, 13, 200000.0),
    Recipe('Remplissage hachuré', 100.0, 80.0, 100, 40000.0, hatch_mm=0.05),
)


#: Process par matière : aucune au cœur libre. Celles d'un atelier — ses
#: paramètres repris du magasin d'outils de sa machine — viennent de son
#: plugin (`plugins.Api.add_recipes(..., material=True)`).
MATERIAL_RECIPES: tuple[Recipe, ...] = ()


#: Bibliothèque d'usine du cœur seul : ses préréglages neutres.
FACTORY_RECIPES: tuple[Recipe, ...] = PRESET_RECIPES + MATERIAL_RECIPES


def preset_recipes() -> tuple[Recipe, ...]:
    """Préréglages : ceux des plugins s'il y en a, ceux du cœur sinon."""
    apport = _plugins.REGISTRY.recipes
    return tuple(apport) if apport else PRESET_RECIPES


def material_recipes() -> tuple[Recipe, ...]:
    """Process par matière, apportées par les plugins."""
    apport = _plugins.REGISTRY.material_recipes
    return tuple(apport) if apport else MATERIAL_RECIPES


def factory_recipes() -> tuple[Recipe, ...]:
    """Bibliothèque d'usine : préréglages, puis process par matière.

    **Le seul point de consultation** : le cœur ne lit jamais
    `FACTORY_RECIPES` directement, sans quoi les process d'un atelier
    n'apparaîtraient pas dans son édition.
    """
    return preset_recipes() + material_recipes()


def default_recipe(**values) -> Recipe:
    """Process neuve : valeurs par défaut des plugins, puis `values`.

    Sert aussi à relire un fichier (`recipe_from_dict`) : un champ absent
    y prend la valeur de l'atelier, comme avant le partage en plugin.
    """
    defauts = _plugins.REGISTRY.recipe_defaults
    return Recipe(**{**defauts, **values}) if defauts else Recipe(**values)


# --- formes ----------------------------------------------------------------

def _new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Shape:
    """Base commune. `x`, `y` = centre de la forme."""
    x: float = 0.0
    y: float = 0.0
    rotation_deg: float = 0.0
    recipe: Recipe = field(default_factory=default_recipe)
    id: str = field(default_factory=_new_id)

    #: Nom **donné à la main**, vide sinon. Ne jamais y écrire un nom
    #: calculé.
    #:
    #: Un nom rempli est figé : plus rien ne le remet d'accord avec le
    #: contenu. C'est voulu — quelqu'un a tapé ce nom et il doit tenir.
    #: Mais y ranger un nom **dérivé** de la donnée transforme cette
    #: promesse en piège : `Datamatrix.taudrive` affichait « B000179 »
    #: pour un code qui valait B000181, et c'est en lisant la liste des
    #: formes qu'on croit avoir posé la bonne pièce.
    #:
    #: Tout ce qui se déduit du contenu appartient à `default_name()`,
    #: qui le recalcule à chaque affichage et ne peut donc pas mentir.
    name: str = ''

    #: Qualificatif **stable** : le poste sur un montage, la place dans un
    #: ensemble. Il ne se déduit pas de la donnée et ne change pas avec
    #: elle — le DataMatrix du HAUT reste celui du haut quelle que soit sa
    #: référence. Il complète le nom dérivé sans le figer.
    role: str = ''
    #: Identifiant de groupe, vide si la forme n'est groupée avec aucune
    #: autre. Le groupe n'est **pas** une forme conteneur : chaque membre
    #: garde sa recette et son entrée dans la liste. Sélectionner un membre
    #: sélectionne tout le groupe, et ce qui vaut pour la sélection —
    #: déplacement, redimensionnement — vaut pour le groupe entier.
    #:
    #: Le groupe est aussi **l'unité du pair-impair** : un contour englobé
    #: par un autre membre y est un trou, celui qu'il englobe à son tour
    #: est de nouveau gravé. Un logo séparé, retouché puis regroupé se
    #: remplit donc comme le dessin d'origine — voir
    #: `toolpath.group_zones`.
    group: str = ''

    #: Cadre entourant la forme : 'none' | 'rect' | 'circle'.
    #:
    #: Associé à un hachurage, il produit une **gravure en négatif** : la
    #: matière est enlevée entre le cadre et le dessin, qui reste en
    #: relief. La règle pair-impair du hachurage s'en charge seule, les
    #: contre-formes comprises — le trou du « O » d'un texte comme
    #: l'intérieur d'un contour DXF.
    #:
    #: Le cadre appartient à la forme de base et non au seul texte : un
    #: tracé importé d'un DXF — un logo, une signature — se creuse
    #: exactement de la même façon.
    frame: str = 'none'
    #: Marge entre le dessin et le cadre, en mm.
    frame_margin_mm: float = 2.0
    #: Décalage du contour du dessin, en mm.
    #:
    #: Positif = matière épaissie : les pleins grossissent et les
    #: contre-formes se referment d'autant. Compense la largeur du
    #: faisceau, qui amincit tout relief laissé par une gravure en
    #: négatif.
    #:
    #: Agit **avec ou sans cadre**. Sous un cadre, c'est la compensation
    #: du faisceau sur un négatif ; seul, c'est le tracé lui-même qu'on
    #: grossit ou qu'on amincit — ce qu'on veut aussi bien pour rattraper
    #: un logo trop maigre que pour affiner un texte qui se bouche.
    frame_offset_mm: float = 0.0
    #: Dimensions imposées du cadre. 0 = ajusté au dessin + marge.
    #: Pour un cercle, `frame_w` vaut le diamètre.
    frame_w: float = 0.0
    frame_h: float = 0.0

    #: Épaisseur du trait gravé, en mm. 0 = un seul passage sur le tracé.
    #:
    #: Au-delà, le trait est élargi par passages parallèles de part et
    #: d'autre du tracé d'origine : c'est ainsi qu'on obtient un trait
    #: lisible sur une pièce, là où un passage unique laisse une rayure.
    line_width_mm: float = 0.0
    #: Écart entre deux passages parallèles, en mm. 0 = reprend le pas de
    #: hachurage de la recette, ou 0,05 mm à défaut.
    line_step_mm: float = 0.0
    #: De quel côté d'un contour fermé vont les passages parallèles :
    #: 'both' (de part et d'autre, comme avant), 'inside' ou 'outside'.
    #:
    #: Des lignes de cote parallèles au contour de référence, **toutes à
    #: l'intérieur** — une bordure qui ne doit pas déborder de la pièce —
    #: ou **toutes à l'extérieur** — un liseré autour d'un logo qui ne doit
    #: pas le mordre. D'un seul côté, toute l'épaisseur y passe. Un tracé
    #: ouvert n'a ni dedans ni dehors : il reste élargi des deux côtés.
    line_side: str = 'both'

    #: Forme active. Masquée, elle n'est **ni affichée ni gravée**.
    #:
    #: C'est le seul sens utile sur une machine : masquer une forme qu'on
    #: graverait quand même reviendrait à marquer une pièce avec un élément
    #: qu'on ne voit pas à l'écran. Le nombre de formes masquées est
    #: rappelé en permanence dans la barre d'état, pour qu'un masquage
    #: oublié ne parte jamais en silence.
    visible: bool = True

    #: Vrai pour le **cadre** qu'un dessin encadré a laissé en le séparant
    #: — voir `splitting.explode`. Il creuse le remplissage de son groupe
    #: comme il creusait le dessin entier, mais **n'entre pas dans le
    #: compte du décalage** : dans la forme d'origine, le décalage ne
    #: voyait que le dessin, jamais son cadre. Seul ce marquage le
    #: distingue d'un contour extérieur du dessin, de même géométrie.
    #: Une version antérieure l'ignore à la lecture.
    detached_frame: bool = False

    def renamed(self) -> bool:
        """Vrai si quelqu'un a tapé ce nom à la main."""
        return bool(self.name)

    def display_name(self) -> str:
        """Le nom montré : celui qu'on a tapé, sinon celui qui se déduit.

        Le nom dérivé se recalcule à chaque appel. Il ne peut donc pas
        rester en arrière de la donnée, et c'est tout l'intérêt.
        """
        if self.name:
            return self.name
        base = self.default_name()
        return f'{base} — {self.role}' if self.role else base

    def default_name(self) -> str:
        return 'forme'


@dataclass
class Rect(Shape):
    width: float = 20.0
    height: float = 10.0

    def default_name(self) -> str:
        return f'rectangle {self.width:g}×{self.height:g}'


@dataclass
class Circle(Shape):
    """Cercle ou ellipse. `width` et `height` sont les deux diamètres."""
    width: float = 20.0
    height: float = 20.0

    def default_name(self) -> str:
        if abs(self.width - self.height) < 1e-9:
            return f'cercle ⌀{self.width:g}'
        return f'ellipse {self.width:g}×{self.height:g}'


@dataclass
class Text(Shape):
    #: Peut contenir des retours à la ligne et des champs variables
    #: (`{n}`, `{date}`… — voir `engrave.variables`).
    text: str = 'TEXTE'
    #: Hauteur de capitale visée, en mm.
    size_mm: float = 5.0
    font_path: str = ''
    #: Alignement horizontal : 'left' | 'center' | 'right'. C'est aussi
    #: l'**ancrage** du bloc sur (x, y) : à gauche, x est le bord gauche
    #: et le texte pousse vers la droite quand on le rallonge ; à droite,
    #: l'inverse ; centré, il pousse des deux côtés.
    align: str = 'center'
    #: Vrai quand la hauteur de capitale est **mesurée** sur la police
    #: qui ne la déclare pas (textes créés depuis octobre 2026).
    #:
    #: 284 polices sur 489 ne déclarent pas leur hauteur de capitale, et
    #: TauDrive prenait alors une hauteur qui compte les accents : un
    #: texte demandé à 10 mm sortait à 7,14 mm en Century Gothic. Corrigé
    #: — mais **pas pour les documents déjà écrits** : une plaque dont le
    #: texte a été ajusté à son cadre déborderait de 40 %. Ils n'ont pas
    #: ce champ, et `serialize` le pose à faux à leur relecture : ils se
    #: gravent exactement comme avant.
    cap_measured: bool = True
    #: Vrai quand `align` ancre le bloc (documents écrits depuis
    #: septembre 2026). Les documents antérieurs posaient tout bloc
    #: centré sur x, quel que soit l'alignement ; ils n'ont pas ce champ,
    #: et `serialize` décale leur origine à la relecture pour que le
    #: texte ne bouge pas. Ne sert qu'à cette relecture.
    anchored: bool = True
    #: Position du bloc par rapport à (x, y) :
    #: 'top' | 'middle' | 'baseline' | 'bottom'.
    valign: str = 'middle'
    #: Interligne, en multiples de `size_mm`.
    line_spacing: float = 1.4
    #: Étirement horizontal, appliqué après la mise en page. 1 = police
    #: à ses proportions d'origine. Sert au redimensionnement libre (F2) :
    #: `size_mm` porte la hauteur, `stretch` la largeur.
    stretch: float = 1.0

    #: Identifiant du code dont ce texte reproduit la donnée, vide sinon.
    #:
    #: Le texte lisible d'une plaque **ne peut pas diverger** du symbole
    #: qu'il accompagne : marquer une pièce dont le code et le numéro en
    #: clair se contredisent est pire que ne rien marquer. Modifier la
    #: donnée du code met donc le texte à jour, champs variables compris.
    follows: str = ''

    def default_name(self) -> str:
        first = self.text.split('\n')[0]
        lines = self.text.count('\n') + 1
        suffix = f' +{lines - 1} ligne(s)' if lines > 1 else ''
        return f'texte « {first[:20]} »{suffix}'


#: Recettes proposées dans l'interface. Remplacé par la bibliothèque du
#: poste au chargement des process — voir `set_recipe_library`.
RECIPE_LIBRARY: list[Recipe] = list(FACTORY_RECIPES)


def set_recipe_library(recipes: list[Recipe]) -> None:
    """Remplace les process proposées. Retombe sur la bibliothèque d'usine
    (plugins compris) si vide."""
    RECIPE_LIBRARY[:] = list(recipes) if recipes else list(factory_recipes())


#: Ce que rend `value_like` pour une valeur qui ne se prête pas au champ.
ILLISIBLE = object()

#: Au-delà, une longueur n'a plus de sens sur une machine au champ de
#: 110 mm : dix mètres. Une cote de 10¹² mm hachurée au vingtième ne finit
#: jamais de se calculer — TauDrive se figeait sur un document abîmé.
LONGUEUR_MAX_MM = 1e4


def hors_borne(emprise) -> bool:
    """L'emprise `(x1, y1, x2, y2)` passe-t-elle `LONGUEUR_MAX_MM` ?

    Un point au-delà ne survit ni à l'enregistrement ni à « annuler » : la
    relecture l'écarte (`serialize._polylines`). Une forme qui en porte ne
    doit donc pas entrer dans un document. `None` — rien à mesurer — ne
    déborde pas.
    """
    if emprise is None:
        return False
    x1, y1, x2, y2 = emprise
    return max(-x1, -y1, x2, y2) > LONGUEUR_MAX_MM

#: En deçà, un pas n'est plus un pas : 0,1 µm. Un hachurage à 10⁻⁹ mm
#: compte cent milliards de rangées sur le champ.
PAS_MIN_MM = 1e-4

#: Champs qui sont des pas : nuls, ils veulent dire « pas de pas ».
_PAS = frozenset({'hatch_mm', 'line_step_mm', 'wobble_pitch_mm',
                  'fill_step_mm'})

#: Champs à choix fermé, et leurs valeurs. Une valeur inconnue — un
#: document écrit par une version plus récente, ou abîmé — ne se gravait
#: pas comme on l'attendait, sans rien dire : une oscillation inconnue
#: arrêtait le calcul, un niveau de correction inconnu effaçait le code.
#: Recopiés ici pour que le modèle reste sans dépendance ; un contrôle de
#: l'autotest vérifie qu'ils suivent `barcode`, `wobble` et `textvec`.
#: Le type d'un code n'y est pas : inconnu, il fait refuser le document —
#: voir `serialize.shape_from_dict`.
CHOIX: dict[str, tuple[str, ...]] = {
    'frame': ('none', 'rect', 'circle'),
    'align': ('left', 'center', 'right'),
    'valign': ('top', 'middle', 'baseline', 'bottom'),
    'level': ('L', 'M', 'Q', 'H'),
    'dm_shape': ('square', 'rect', 'auto'),
    'wobble': ('none', 'circle', 'eight', 'transverse'),
    'fill_style': ('hatch', 'rings'),
    'depth_mode': ('step', 'total'),
    'line_side': ('both', 'inside', 'outside'),
}

#: Symbologies connues — voir `barcode.KINDS`.
CODE_KINDS = ('datamatrix', 'qr', 'code39', 'ean13', 'code128')

#: Symbologies que **toute** version de TauDrive connaît. Une plus récente
#: s'écrit à part dans les réglages, préréglages et montages — voir
#: `ecrire_symbologie`.
CODE_KINDS_COMMUNS = ('datamatrix', 'qr', 'code39', 'ean13')


def ecrire_symbologie(reglage: dict, kind: str) -> None:
    """Range `kind` dans un réglage que d'autres versions liront.

    Ces réglages circulent : préréglages et montages d'un poste à l'autre,
    réglages retenus entre deux versions installées côte à côte. Une
    version antérieure au Code 128 posait telle quelle la symbologie lue,
    et la plaque ne se rouvrait plus nulle part. Une symbologie qu'elle
    ignore va donc dans `kind_recent`, qu'elle ne lit pas ; `kind` garde
    la dernière qu'elle connaît, ou disparaît.

    `kind_commun` retient ce `kind` gardé. Une version antérieure qui
    retouche le réglage — un montage passé en QR à son gestionnaire —
    réécrit `kind` sans rien savoir du reste : `kind` n'est plus alors
    celui qui accompagnait `kind_recent`, et c'est son choix, le dernier,
    qui compte (`lire_symbologie`)."""
    if kind in CODE_KINDS_COMMUNS:
        reglage['kind'] = kind
        reglage.pop('kind_recent', None)
        reglage.pop('kind_commun', None)
    else:
        reglage['kind_recent'] = kind
        if reglage.get('kind') in CODE_KINDS_COMMUNS:
            reglage['kind_commun'] = reglage['kind']
        else:
            reglage.pop('kind', None)
            reglage.pop('kind_commun', None)


def lire_symbologie(reglage: dict, defaut=None):
    """La symbologie d'un réglage écrit par `ecrire_symbologie` :
    `kind_recent` si cette version la connaît et que `kind` n'a pas
    changé depuis, sinon `kind`, sinon `defaut`. Une symbologie inconnue
    n'est jamais rendue."""
    recente, kind = reglage.get('kind_recent'), reglage.get('kind')
    if (isinstance(recente, str) and recente in CODE_KINDS
            and kind == reglage.get('kind_commun')):
        return recente
    if isinstance(kind, str) and kind in CODE_KINDS:
        return kind
    return defaut

#: Bornes des multiplicateurs et des nombres : (plus petit, plus grand),
#: bornes comprises. Un étirement de 10⁹ ou des points à 10⁹ mm faisaient
#: tourner le calcul des trajectoires sans fin, sans rien signaler. Plus
#: larges que les formulaires — une valeur qu'on peut régler à la main
#: doit se relire —, assez serrées pour qu'aucune ne fige TauDrive.
BORNES: dict[str, tuple[float, float]] = {
    'stretch': (1e-3, 100.0),
    'line_spacing': (1e-3, 100.0),
    'passes': (1, 10_000),
    'quiet_modules': (0, 100),
    'copies': (1, 1_000_000),
    # Le process part tel quel dans l'ISO : `T-1`, `G108 P-9.200`, `F-50`
    # se lisaient d'un fichier sans un mot, et la vérification annonçait
    # « 0 % de puissance » pour -9,2. Une taille de texte négative rendait
    # un texte vide.
    'power_percent': (0.0, 100.0),
    'frequency_khz': (0.0, math.inf),
    'pulse_width_ns': (0, math.inf),
    'speed_mm_min': (0.0, math.inf),
    'tool_number': (0, math.inf),
    'size_mm': (0.0, math.inf),
    # Un champ de 0,01 mm se relisait : le plan de morceaux en tirait un
    # par millimètre de dessin — des millions, et la mémoire épuisée.
    # Aucune tête n'a un champ de moins d'un millimètre.
    'field_w': (1.0, math.inf),
    'field_h': (1.0, math.inf),
}

#: Remplacements faits **sans compte rendu où les noter** : la
#: bibliothèque de process, un import de réglages, un collage, un dessin
#: inséré. Plus aucune lecture ne remet une valeur à son défaut en
#: silence : TauDrive les relève ici et les montre — voir
#: `unreported_repairs`. Bornée : un lecteur sans fenêtre ne la vide pas.
_NON_DITS: list[str] = []
_NON_DITS_MAX = 200


def note_repair(report: list | None, ligne: str) -> None:
    """Note un remplacement dans `report`, ou parmi les non-dits."""
    if report is not None:
        report.append(ligne)
    elif len(_NON_DITS) < _NON_DITS_MAX:
        _NON_DITS.append(ligne)


def unreported_repairs() -> list[str]:
    """Les remplacements faits sans compte rendu depuis le dernier appel —
    rendus une fois, puis oubliés."""
    sortie = list(_NON_DITS)
    _NON_DITS.clear()
    return sortie


def value_like(champ: str, default, value):
    """`value` si elle convient au champ dont `default` est la valeur par
    défaut, sinon `ILLISIBLE`.

    Le type du défaut fait la règle : un nombre attend un nombre fini — un
    entier convient à un décimal et inversement, tel qu'il est écrit —, un
    booléen attend un booléen, ou 0 et 1 ; un texte attend un texte. Les
    longueurs sont bornées à `LONGUEUR_MAX_MM`, les pas à `PAS_MIN_MM`.
    Un champ sans défaut typé — `None` — passe tel quel.

    Une valeur relue d'un document abîmé ou écrit à la main était prise
    telle quelle : une liste à la place d'une amplitude, et c'est le calcul
    des trajectoires qui tombait, plus tard, loin de la cause — au
    démarrage même, si l'instantané de séance était en cause.
    """
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and value in (0, 1)):
            return bool(value)
        return ILLISIBLE
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return ILLISIBLE
        if not math.isfinite(value):
            return ILLISIBLE
        longueur = (champ.endswith('_mm') or champ in (
            'x', 'y', 'width', 'height', 'frame_w', 'frame_h', 'field_w',
            'field_h', 'plate_w', 'plate_h', 'work_center_x',
            'work_center_y'))
        if longueur and abs(value) > LONGUEUR_MAX_MM:
            return ILLISIBLE
        # négatif, un pas n'en est pas un non plus : nul, c'est « aucun »
        if champ in _PAS and (value < 0 or 0 < value < PAS_MIN_MM):
            return ILLISIBLE
        borne = BORNES.get(champ)
        if borne is not None and not borne[0] <= value <= borne[1]:
            return ILLISIBLE
        if isinstance(default, int):
            # un nombre de passes, un numéro d'outil : un décimal entier
            # se convertit, un décimal fractionnaire n'a pas de sens —
            # `range(2.5)` arrêtait le calcul des passes
            if isinstance(value, float):
                return int(value) if value.is_integer() else ILLISIBLE
        return value
    if isinstance(default, str):
        if not isinstance(value, str):
            return ILLISIBLE
        if champ in CHOIX and value not in CHOIX[champ]:
            return ILLISIBLE
        return value
    return value


def _conformes(cls, data: dict, report: list | None, where: str,
               exclus=()) -> dict:
    """Les champs de `data` qui conviennent à `cls`, défaut pour les autres,
    chaque remplacement noté dans `report`."""
    import dataclasses as _dc
    defaut = cls()
    valeurs = {}
    for f in _dc.fields(cls):
        if f.name in exclus or f.name not in data:
            continue
        v = value_like(f.name, getattr(defaut, f.name), data[f.name])
        if v is ILLISIBLE:
            note_repair(report, f'{where}{f.name} = {data[f.name]!r:.40}')
            continue
        valeurs[f.name] = v
    return valeurs


def recipe_from_dict(data: dict, report: list | None = None,
                     where: str = '') -> Recipe:
    """Process depuis un dictionnaire, champs inconnus ignorés.

    Une valeur qui ne convient pas à son champ — voir `value_like` — est
    remplacée par le défaut, et le remplacement noté dans `report`.
    """
    if not isinstance(data, dict):
        note_repair(report, f'{where}process illisible, remplacée par défaut')
        data = {}
    values = _conformes(Recipe, data, report, where, exclus=('treatment',))
    brut = data.get('treatment')
    if isinstance(brut, dict):
        values['treatment'] = Treatment(**_conformes(
            Treatment, brut, report, f'{where}traitement, '))
    elif isinstance(brut, Treatment):
        values['treatment'] = brut
    elif brut is not None:
        note_repair(report, f'{where}traitement illisible, retiré')
    return default_recipe(**values)


def recipe_to_dict(recipe: Recipe) -> dict:
    import dataclasses as _dc
    return _dc.asdict(recipe)


@dataclass
class Code(Shape):
    """Code à barres, 2D ou linéaire.

    `module_mm` est le côté d'un module — le petit carré élémentaire.
    C'est lui qui fixe la taille du symbole : le nombre de modules découle
    de la donnée et de la symbologie, il ne se règle pas.
    """
    #: 'datamatrix' | 'qr' | 'code39' | 'ean13' | 'code128'
    kind: str = 'datamatrix'
    #: Donnée encodée. Accepte les champs variables (`{n}`, `{date}`…).
    data: str = '{n:06}'
    #: Côté d'un module, en mm.
    module_mm: float = 0.5
    #: Niveau de correction d'erreur, QR seulement : L, M, Q ou H.
    level: str = 'M'
    #: Zone de silence, en modules. La norme en demande 4 pour un QR,
    #: 1 pour un DataMatrix ; 0 est admis si le fond est déjà neutre.
    quiet_modules: int = 2

    #: Forme du DataMatrix : 'square', 'rect' ou 'auto'.
    dm_shape: str = 'square'
    #: Clé de contrôle, Code 39 seulement.
    checksum: bool = False
    #: Hauteur des barres d'un code linéaire, en mm.
    bar_height_mm: float = 6.0

    #: Pas de remplissage des modules, en mm. 0 = automatique.
    #:
    #: Un code n'est **lisible que plein** : un contour de module laisse
    #: un carré vide que le lecteur ne verra pas. Le remplissage est donc
    #: produit par la forme elle-même, sans dépendre du hachurage de la
    #: recette — une recette de marquage à hachurage nul donnerait sinon
    #: un code parfaitement dessiné et parfaitement illisible.
    fill_step_mm: float = 0.0

    #: Fenêtre imposée, en mm. Quand les deux sont renseignées, le symbole
    #: est **étiré pour la remplir exactement** : c'est ainsi que sont
    #: faites les plaques de production, où un cadre réserve la place du
    #: code et où celui-ci ne doit ni déborder ni flotter dedans.
    #: 0 = taille libre, commandée par `module_mm`.
    fit_w_mm: float = 0.0
    fit_h_mm: float = 0.0

    def default_name(self) -> str:
        labels = {'datamatrix': 'DataMatrix', 'qr': 'QR',
                  'code39': 'Code 39', 'ean13': 'EAN-13',
                  'code128': 'Code 128'}
        return f'{labels.get(self.kind, self.kind)} « {self.data[:16]} »'


@dataclass
class Path(Shape):
    """Géométrie importée — DXF notamment.

    `polylines` est exprimé dans le repère local de la forme, déjà centré
    sur son origine ; `x`, `y`, `rotation_deg` la placent comme toute autre
    forme.
    """
    polylines: list = field(default_factory=list)
    source: str = ''
    layer: str = ''

    def default_name(self) -> str:
        origin = f' — {self.layer}' if self.layer else ''
        return f'tracé {len(self.polylines)} polyligne(s){origin}'


@dataclass
class Document:
    """Un plan de travail et ses formes."""
    shapes: list[Shape] = field(default_factory=list)
    field_w: float = FIELD_W_MM
    field_h: float = FIELD_H_MM
    #: Position du centre du travail dans le repère machine, reportée dans
    #: le CLJOB (`CENTROLAVOROX` / `CENTROLAVOROY`). La valeur relevée sur
    #: une TAU 10×10 SMART est (50, 50).
    work_center_x: float = 50.0
    work_center_y: float = 50.0
    #: Encombrement de la **plaque** posée sur la machine, en mm. Reporté
    #: dans `INGOMBRO_TARGA_*` du CLJOB — c'est le support, pas le dessin.
    plate_w: float = 100.0
    plate_h: float = 100.0
    name: str = 'gravure'

    # --- lot et sérialisation ---
    #: Nombre de pièces à produire. Chaque pièce reçoit son propre jeu de
    #: fichiers, avec les champs variables réévalués.
    copies: int = 1
    #: Numéro de série de la première pièce.
    serial_start: int = 1
    #: Incrément entre deux pièces.
    serial_step: int = 1

    #: Dernière process employée dans cet onglet, ou `None`.
    #:
    #: Ce qu'on pose après avoir réglé une process doit porter la même :
    #: dans un travail d'acier satiné, toutes les formes le sont. La
    #: bibliothèque donnait sa première entrée, qui n'a aucune raison
    #: d'être celle du travail en cours. Mémorisée **par onglet**, elle
    #: suit le document — rouvrir le travail de la semaine dernière
    #: retrouve sa process.
    last_recipe: Recipe | None = None

    #: Réglages du coupon d'essai qui a produit ce document, s'il en vient.
    #:
    #: Un coupon n'est pas un dessin qu'on rouvre pour le retoucher à la
    #: souris : c'est le résultat d'un formulaire. Le garder avec le
    #: document permet de **rouvrir ce formulaire tel qu'il était** et de
    #: régénérer la grille — resaisir dix champs pour changer une borne
    #: reviendrait à jeter le coupon et à recommencer.
    coupon: dict = field(default_factory=dict)

    def serial_for(self, index: int) -> int:
        """Numéro de série de la pièce `index` (0 pour la première)."""
        return self.serial_start + index * self.serial_step

    def add(self, shape: Shape) -> Shape:
        self.shapes.append(shape)
        return shape

    def remove(self, shape_id: str) -> None:
        self.shapes = [s for s in self.shapes if s.id != shape_id]

    def get(self, shape_id: str) -> Shape | None:
        return next((s for s in self.shapes if s.id == shape_id), None)

    def move_shape(self, shape_id: str, delta: int) -> bool:
        """Déplace une forme dans la liste. Vrai si elle a bougé.

        L'ordre de la liste est **l'ordre de gravure** quand le
        regroupement par recette est coupé : monter une forme, c'est la
        graver plus tôt.
        """
        rang = next((i for i, s in enumerate(self.shapes)
                     if s.id == shape_id), -1)
        cible = rang + delta
        if rang < 0 or not (0 <= cible < len(self.shapes)):
            return False
        self.shapes.insert(cible, self.shapes.pop(rang))
        return True

    def duplicate(self, shape_id: str, dx: float = 5.0, dy: float = -5.0) -> Shape | None:
        src = self.get(shape_id)
        if src is None:
            return None
        copy = replace(src, id=_new_id(), x=src.x + dx, y=src.y + dy)
        self.shapes.append(copy)
        return copy

    # --- groupes ---

    def group_members(self, shape_id: str) -> list[Shape]:
        """Formes du même groupe que celle donnée, elle comprise."""
        shape = self.get(shape_id)
        if shape is None:
            return []
        if not shape.group:
            return [shape]
        return [s for s in self.shapes if s.group == shape.group]

    def expand_selection(self, shape_ids) -> list[str]:
        """Complète une sélection avec tous les membres des groupes touchés."""
        groups = {s.group for s in self.shapes
                  if s.id in set(shape_ids) and s.group}
        wanted = set(shape_ids)
        return [s.id for s in self.shapes
                if s.id in wanted or (s.group and s.group in groups)]

    def group(self, shape_ids) -> str | None:
        """Réunit les formes données en un groupe. Rend son identifiant.

        Grouper des formes déjà groupées absorbe les groupes existants dans
        le nouveau : c'est le comportement attendu quand on sélectionne un
        groupe et une forme isolée pour n'en faire qu'un.
        """
        chosen = [s for s in self.shapes if s.id in set(shape_ids)]
        if len(chosen) < 2:
            return None
        absorbed = {s.group for s in chosen if s.group}
        key = _new_id()
        for s in self.shapes:
            if s in chosen or (s.group and s.group in absorbed):
                s.group = key
        return key

    def regroup_copies(self, pairs) -> None:
        """Donne aux copies les groupes de leurs originaux, sous des noms
        neufs. `pairs` : (copie, groupe de l'original).

        Les copies d'un même groupe forment un groupe neuf ; la copie d'une
        forme qui n'était pas groupée reste seule. Grouper d'office toute
        une sélection copiée changeait ce que la copie grave : le groupe
        est l'unité du pair-impair, et un texte posé sur un rectangle
        sortait creusé dans la copie, plein dans l'original.
        """
        compte: dict[str, int] = {}
        for _copie, groupe in pairs:
            if groupe:
                compte[groupe] = compte.get(groupe, 0) + 1
        neufs: dict[str, str] = {}
        for copie, groupe in pairs:
            if groupe and compte[groupe] > 1:
                copie.group = neufs.setdefault(groupe, _new_id())
            else:
                copie.group = ''

    def ungroup(self, shape_ids) -> int:
        """Défait les groupes touchés par la sélection. Rend le nombre de
        formes libérées."""
        groups = {s.group for s in self.shapes
                  if s.id in set(shape_ids) and s.group}
        freed = 0
        for s in self.shapes:
            if s.group and s.group in groups:
                s.group = ''
                freed += 1
        return freed

    def bounds(self) -> tuple[float, float, float, float] | None:
        """Emprise (x1, y1, x2, y2) de toutes les formes, ou None si vide.

        Calculée sur les seuls contours : le hachurage y est contenu par
        construction, le calculer ici ne changerait rien au résultat et
        coûterait le prix fort à chaque rafraîchissement.

        Les formes masquées en sont exclues : elles ne partent pas à la
        gravure, elles n'ont donc pas à déclencher une alerte de champ.
        """
        from .toolpath import shape_extent
        boxes = [b for b in (shape_extent(s) for s in self.shapes
                             if s.visible) if b]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def out_of_field(self, tolerance_mm: float = 1e-6) -> bool:
        """Vrai si une trajectoire sort du champ de marquage.

        La tolérance évite qu'une pièce ajustée exactement au champ soit
        signalée à cause d'un arrondi flottant.
        """
        b = self.bounds()
        if b is None:
            return False
        x1, y1, x2, y2 = b
        hw, hh = self.field_w / 2 + tolerance_mm, self.field_h / 2 + tolerance_mm
        return x1 < -hw or x2 > hw or y1 < -hh or y2 > hh
