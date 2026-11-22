"""Aimant du plan de travail / Snapping.

Poser trois plaques au même niveau, centrer un logo sur l'axe, caler un
texte contre le bord d'un cadre : à la souris, on approchait à quelques
dixièmes près, puis on finissait au clavier ou dans les cotes. Le plan
de travail n'aidait en rien.

Désormais, ce qu'on traîne **s'accroche** : son bord gauche, son milieu
ou son bord droit — et de même en hauteur — vient se poser exactement
sur un bord ou le milieu d'une autre forme, sur un axe, ou sur un bord
du champ, dès qu'il en passe à moins de `PORTEE_PX` pixels d'écran. Une
ligne de repère montre à quoi la forme s'est accrochée. La portée se
compte à l'écran et non en millimètres : de près, on peut poser à côté
d'un bord sans s'y coller ; de loin, on attrape sans viser.

**Alt** tenu pendant le geste déplace librement ; *Affichage ▸
Magnétisme* coupe l'aimant pour de bon, et le choix est retenu.

Seul le geste à la souris est aimanté : les flèches du clavier et les
cotes tapées restent exactes au pas près, comme avant.

Fonctions pures, sans Qt : la colle avec le plan de travail est dans
`app.ShapeItem`.
"""
from __future__ import annotations

import bisect

#: Portée de l'aimant, en pixels d'écran.
PORTEE_PX = 6.0


def traits(bas: float, haut: float) -> tuple[float, float, float]:
    """Les trois prises d'une emprise sur un axe : bords et milieu."""
    return bas, (bas + haut) / 2.0, haut


def accroche(prises: tuple[float, ...], cibles: list[float],
             deplacement: float, portee: float) -> tuple[float, float | None]:
    """Le déplacement corrigé, et la cible prise — ou None.

    `prises` sont les bords et le milieu de ce qu'on déplace, **au début
    du geste** ; `cibles`, triées, ce à quoi ils peuvent s'accrocher. La
    prise la plus proche d'une cible, à moins de `portee`, l'emporte :
    le déplacement est corrigé pour qu'elle tombe exactement dessus.
    Hors de portée, le déplacement est rendu tel quel.
    """
    meilleur: tuple[float, float] | None = None
    for prise in prises:
        v = prise + deplacement
        i = bisect.bisect_left(cibles, v)
        for j in (i - 1, i):
            if 0 <= j < len(cibles):
                ecart = cibles[j] - v
                if abs(ecart) <= portee and (
                        meilleur is None or abs(ecart) < abs(meilleur[0])):
                    meilleur = (ecart, cibles[j])
    if meilleur is None:
        return deplacement, None
    return deplacement + meilleur[0], meilleur[1]
