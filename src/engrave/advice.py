"""Recommandations de paramètres, et leur audit / Parameter advice.

Des jeux de paramètres circulent : forums, notices de constructeurs,
assistants conversationnels. Ils sont souvent **justes en physique et faux
sur la machine** — parce qu'ils viennent d'une source différente, d'une
lentille différente, ou d'aucune machine en particulier.

Ce module fait deux choses.

1. Il porte une **table de recommandations** par matière et par rendu.
2. Il les **audite** contre ce que la machine sait réellement faire :
   la table des formes d'onde de sa source, sa vitesse maximale, son
   diamètre de spot. Chaque recommandation sort avec un verdict, et
   celles qui ne passent pas sont **montrées barrées, pas cachées** —
   savoir qu'un réglage est hors d'atteinte vaut mieux que de le
   chercher.

Rien ici n'est appliqué automatiquement. Une recommandation est un point
de départ à valider sur chute, jamais un réglage de production : c'est le
rôle du coupon d'essai.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import couples

#: Verdicts d'audit, du plus grave au plus anodin.
REFUSE, RESERVE, TENU = 'refusé', 'réserve', 'tenu'

#: Diamètre de spot de la majorité des outils du magasin, en mm.
#: Cf. `reference/magasin-outils.md` §3.
SPOT_MM = 0.03

#: Vitesse maximale des axes optiques, en mm/min.
#: Cf. `reference/limites-machine.md` §1 — trois sources concordantes.
V_MAX_MM_MIN = 200_000.0

#: Recouvrement minimal voulu entre deux impulsions.
#:
#: Le faisceau avance de v/f entre deux tirs. Si ce pas dépasse le
#: diamètre de spot, la gravure devient pointillée. Deux fois le
#: recouvrement est la règle d'un marquage propre.
OVERLAP_MIN = 1.0
OVERLAP_CLEAN = 2.0


@dataclass(frozen=True)
class Advice:
    """Un jeu de paramètres recommandé, avec sa raison d'être."""
    material: str
    goal: str
    frequency_khz: float
    pulse_width_ns: int
    speed_mm_s: float
    #: Ce que ces valeurs cherchent à obtenir, en une phrase.
    why: str = ''
    #: D'où vient la recommandation.
    source: str = ''

    def speed_mm_min(self) -> float:
        return self.speed_mm_s * 60.0

    def speed_m_min(self) -> float:
        return self.speed_mm_s * 0.06

    def pitch_mm(self) -> float:
        """Pas entre deux impulsions : v / f."""
        if self.frequency_khz <= 0:
            return 0.0
        return self.speed_mm_s / (self.frequency_khz * 1000.0)

    def overlap(self) -> float:
        """Recouvrement : combien de fois le spot couvre le pas."""
        pas = self.pitch_mm()
        return SPOT_MM / pas if pas > 0 else 0.0

    def duty_percent(self) -> float:
        return self.pulse_width_ns * 1e-9 * self.frequency_khz * 1e3 * 100.0

    def label(self) -> str:
        return f'{self.material} — {self.goal}'

    def couple(self) -> str:
        return f'{self.frequency_khz:g}-{self.pulse_width_ns:g}'


@dataclass
class Verdict:
    """Ce que l'audit d'une recommandation a trouvé."""
    advice: Advice
    level: str = TENU
    #: Fréquence maximale admise pour cette durée d'impulsion, ou None si
    #: la durée n'est pas une forme d'onde de la source.
    f_max_khz: float | None = None
    notes: list[str] = field(default_factory=list)

    def kept(self) -> bool:
        return self.level != REFUSE


#: Durée d'impulsion la plus longue que la source produise, en ns.
TAU_MAX_NS = 500

#: Rapport cyclique au-delà duquel la source ne tient plus sa puissance
#: de crête. C'est une limite de physique, pas de table.
DUTY_MAX = 5.0


def max_frequency(pulse_ns: float) -> tuple[float | None, int | None]:
    """Fréquence de la table constructeur pour cette durée d'impulsion.

    Rend `(f_table, tau_reference)`, la référence étant la forme d'onde
    **la plus proche** — la source n'en connaît que treize, et une durée
    intermédiaire n'existe pas.

    Rend `(None, None)` au-delà de la plus longue forme d'onde.
    """
    table = sorted(couples.factory(), key=lambda c: c.pulse_width_ns)
    if not table or pulse_ns > TAU_MAX_NS + 1e-9:
        return None, None
    proche = min(table, key=lambda c: abs(c.pulse_width_ns - pulse_ns))
    return proche.frequency_khz, proche.pulse_width_ns


_OBSERVED: dict[int, float] | None = None


def observed_max(pulse_ns: float) -> float | None:
    """Fréquence la plus haute que le **magasin** porte à cette durée.

    C'est la contre-épreuve indispensable de la table constructeur : les
    72 outils de `dbpunte.mag` ont gravé, et plusieurs tournent bien
    au-dessus du plafond annoncé — 30 ns y va jusqu'à 450 kHz là où la
    table s'arrête à 135. Voir §2 de `parametres-laser.md`.

    Rend `None` si aucun outil n'emploie cette durée.
    """
    global _OBSERVED
    if _OBSERVED is None:
        vus: dict[int, float] = {}
        for c in couples.from_magazine():
            tau = int(c.pulse_width_ns)
            vus[tau] = max(vus.get(tau, 0.0), c.frequency_khz)
        _OBSERVED = vus
    if not _OBSERVED:
        return None
    tau = min(_OBSERVED, key=lambda t: abs(t - pulse_ns))
    return _OBSERVED[tau] if abs(tau - pulse_ns) <= 6 else None


def audit(advice: Advice) -> Verdict:
    """Confronte une recommandation à ce que la machine sait faire.

    **Deux degrés, et ils ne disent pas la même chose.**

    *Refusé* est réservé à ce qui est hors de portée physique : une durée
    d'impulsion que la source ne produit pas, une vitesse que les axes
    n'atteignent pas, un rapport cyclique auquel la puissance de crête
    s'effondre. Ce sont des murs.

    *Réserve* couvre ce qui **sort de la table constructeur sans sortir
    de la machine**. La contre-épreuve est le magasin : ses 72 outils ont
    gravé, et plusieurs tournent bien au-dessus du plafond annoncé —
    30 ns y va jusqu'à 450 kHz là où la table s'arrête à 135. La table
    est donc vraisemblablement **nominale et non impérative**, et
    refuser sur elle seule serait crier au loup.
    """
    verdict = Verdict(advice=advice)
    f_max, tau_ref = max_frequency(advice.pulse_width_ns)
    verdict.f_max_khz = f_max

    def abaisser(niveau: str) -> None:
        rang = {TENU: 0, RESERVE: 1, REFUSE: 2}
        if rang[niveau] > rang[verdict.level]:
            verdict.level = niveau

    if f_max is None:
        verdict.level = REFUSE
        verdict.notes.append(
            f'Impulsion de {advice.pulse_width_ns:g} ns : au-delà des '
            f'{TAU_MAX_NS} ns de la source.')
        return verdict

    if advice.duty_percent() > DUTY_MAX:
        abaisser(REFUSE)
        verdict.notes.append(
            f'Rapport cyclique {advice.duty_percent():.1f} % : au-delà de '
            f'{DUTY_MAX:g} %, la source ne tient pas sa puissance de '
            f'crête. C\'est une limite de physique, pas de table.')

    if advice.speed_mm_min() > V_MAX_MM_MIN + 1e-6:
        abaisser(REFUSE)
        verdict.notes.append(
            f'{advice.speed_m_min():.0f} m/min dépasse les '
            f'{V_MAX_MM_MIN * 0.001:.0f} m/min des axes optiques.')

    if tau_ref != advice.pulse_width_ns:
        abaisser(RESERVE)
        verdict.notes.append(
            f'{advice.pulse_width_ns:g} ns n\'est pas une des treize '
            f'formes d\'onde ; la plus proche est {tau_ref:g} ns.')

    if advice.frequency_khz > f_max + 1e-9:
        abaisser(RESERVE)
        vu = observed_max(advice.pulse_width_ns)
        if vu is not None and vu >= advice.frequency_khz - 1e-9:
            verdict.notes.append(
                f'{advice.frequency_khz:g} kHz dépasse les {f_max:g} kHz '
                f'que la table donne à {tau_ref:g} ns — mais le magasin de '
                f'la machine y monte jusqu\'à {vu:g} kHz. La table est '
                f'donc nominale, et non impérative : à essayer sur chute.')
        else:
            plafond = (f', et le magasin ne dépasse pas {vu:g} kHz'
                       if vu else '')
            verdict.notes.append(
                f'{advice.frequency_khz:g} kHz dépasse les {f_max:g} kHz '
                f'de la forme d\'onde {tau_ref:g} ns{plafond}. À cette '
                f'fréquence, la table demande '
                f'{_shortest_for(advice.frequency_khz)}.')

    recouvrement = advice.overlap()
    if recouvrement and recouvrement < OVERLAP_MIN:
        abaisser(RESERVE)
        verdict.notes.append(
            f'Pas d\'impulsion {advice.pitch_mm():.4f} mm pour un spot de '
            f'{SPOT_MM:g} mm : impulsions disjointes, marquage pointillé.')
    elif recouvrement and recouvrement < OVERLAP_CLEAN:
        verdict.notes.append(
            f'Recouvrement {recouvrement:.1f}× seulement : correct, mais '
            f'2× est la règle d\'un marquage propre.')
    elif recouvrement > 12:
        verdict.notes.append(
            f'Recouvrement {recouvrement:.0f}× : chaque point de la pièce '
            f'reçoit autant d\'impulsions. Cohérent pour noircir ou '
            f'nettoyer, mais beaucoup de chaleur — à essayer sur chute.')
    return verdict


def _shortest_for(f_khz: float) -> str:
    """La forme d'onde la plus longue qui tienne cette fréquence."""
    tenables = [c for c in couples.factory() if c.frequency_khz >= f_khz]
    if not tenables:
        return 'aucune forme d\'onde de la source'
    meilleur = max(tenables, key=lambda c: c.pulse_width_ns)
    return f'{meilleur.pulse_width_ns:g} ns au plus'


#: Recommandations soumises à l'audit.
#:
#: Elles viennent d'un assistant conversationnel interrogé sur les
#: réglages MOPA, et sont conservées **telles qu'elles ont été données**,
#: y compris celles que l'audit refuse : c'est l'audit qui tranche, et
#: masquer ce qui ne passe pas priverait de la raison pour laquelle cela
#: ne passe pas.
#:
#: La physique qu'elles invoquent est juste, et vaut d'être retenue :
#:
#: * **impulsion courte** (2 à 13 ns) — forte puissance de crête, peu de
#:   chaleur transmise : marquage fin, sans bavure ni relief ;
#: * **impulsion longue** (200 à 500 ns) — l'énergie s'accumule : c'est
#:   ainsi qu'on creuse ou qu'on fait fondre.
#:
#: Ce qui ne l'est pas, c'est la disponibilité des couples sur *cette*
#: source : trois des sept recommandations demandent une fréquence que la
#: forme d'onde ne tient pas.
SUGGESTED: tuple[Advice, ...] = (
    Advice('Acier (inox, carbone)', 'gravure profonde 3D',
           35, 500, 400,
           'Maximiser l\'énergie par impact pour éjecter le plus de '
           'matière à chaque tir.', 'assistant'),
    Advice('Acier (inox, carbone)', 'marquage noir intense',
           180, 30, 600,
           'L\'impulsion courte carbonise la surface sans la faire '
           'gonfler ni creuser.', 'assistant'),
    Advice('Acier inox', 'marquage couleur',
           1000, 6, 1500,
           'Impulsions ultra-courtes et cadence élevée : une couche '
           'd\'oxydation nanométrique qui diffracte la lumière.',
           'assistant'),
    Advice('Laiton et métaux précieux', 'gravure profonde',
           25, 500, 300,
           'Le laiton dissipe vite : il faut le maximum de durée '
           'd\'impulsion pour transférer l\'énergie avant qu\'elle ne '
           'parte dans la masse.', 'assistant'),
    Advice('Laiton', 'nettoyage, polissage de fond',
           1200, 4, 2000,
           'Puissance de crête infime : vaporiser les micro-rugosités '
           'pour rendre le fond brillant.', 'assistant'),
    Advice('Aluminium', 'marquage noir profond',
           500, 10, 500,
           'Micro-structures qui piègent la lumière, sans faire fondre '
           'le métal.', 'assistant'),
    Advice('Aluminium', 'marquage blanc givré',
           80, 100, 1200,
           'Blanchir et nettoyer la surface de l\'alu brut.',
           'assistant'),
)


def audited() -> list[Verdict]:
    """Toutes les recommandations, auditées, les tenues d'abord."""
    rang = {TENU: 0, RESERVE: 1, REFUSE: 2}
    return sorted((audit(a) for a in SUGGESTED),
                  key=lambda v: (rang[v.level], v.advice.material))


def corrected(advice: Advice) -> Advice | None:
    """La recommandation ramenée sur un couple que la source tient.

    Deux gestes, dans cet ordre :

    1. la durée d'impulsion est **ramenée à la forme d'onde la plus
       proche** — la source n'en connaît que treize, et une valeur
       intermédiaire n'existe simplement pas ;
    2. la fréquence est **rabattue** sous le plafond de cette forme
       d'onde, si elle le dépassait.

    L'intention est ainsi préservée : une impulsion courte reste courte,
    elle tire seulement moins souvent. Le résultat est toujours un couple
    de la table constructeur, donc un point de fonctionnement réel.

    Rend `None` quand il n'y a rien à corriger.
    """
    import dataclasses
    table = couples.factory()
    if not table:
        return None
    proche = min(table,
                 key=lambda c: abs(c.pulse_width_ns - advice.pulse_width_ns))
    tau = proche.pulse_width_ns
    f = min(advice.frequency_khz, proche.frequency_khz)
    if (tau == advice.pulse_width_ns
            and abs(f - advice.frequency_khz) < 1e-9):
        return None
    changes = []
    if tau != advice.pulse_width_ns:
        changes.append(f'impulsion {advice.pulse_width_ns:g} → {tau:g} ns')
    if abs(f - advice.frequency_khz) > 1e-9:
        changes.append(f'{advice.frequency_khz:g} → {f:g} kHz')
    return dataclasses.replace(
        advice, frequency_khz=f, pulse_width_ns=int(tau),
        source=' · '.join([advice.source] + changes))
