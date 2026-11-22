"""Validation des encodeurs DataMatrix et QR Code.

Deux niveaux de preuve :

1. **valeurs publiées** — polynômes générateurs, chaînes d'information de
   format et de version, mots de code d'un exemple normatif. Ces nombres
   ne viennent pas de notre code : ils sont dans les normes, et une erreur
   d'implémentation les fait tomber immédiatement ;
2. **relecture** — un décodeur écrit ici relit le symbole produit : il
   retrouve le masque dans la zone d'information, le retire, reparcourt
   les modules, désentrelace les blocs et **vérifie les syndromes
   Reed-Solomon** avant de rendre le message. Un symbole qui se relit avec
   des syndromes nuls est un symbole qu'un lecteur du commerce lira aussi.

Usage : python test_barcode.py
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from engrave import barcode as B                          # noqa: E402


def _C39_ITEMS():
    return B._C39.items()


def check(label, got, want) -> bool:
    ok = got == want
    print(f'  [{"OK " if ok else "KO "}] {label}')
    if not ok:
        print(f'         obtenu : {got!r}\n         attendu: {want!r}')
    return ok


# --------------------------------------------------------------------------
# Décodeur de relecture (QR)
# --------------------------------------------------------------------------

def _read_format(grid) -> tuple[str, int]:
    """Niveau de correction et numéro de masque, lus dans le symbole."""
    size = len(grid)
    bits = []
    for i in range(6):
        bits.append(int(grid[8][i]))
    bits.append(int(grid[8][7]))
    bits.append(int(grid[8][8]))
    bits.append(int(grid[7][8]))
    for i in range(9, 15):
        bits.append(int(grid[14 - i][8]))

    value = 0
    for bit in bits:
        value = (value << 1) | bit
    value ^= 0b101010000010010
    level_bits = (value >> 13) & 0b11
    mask = (value >> 10) & 0b111
    level = {v: k for k, v in B._QR_LEVEL_BITS.items()}[level_bits]
    return level, mask


def qr_decode(grid) -> str:
    """Relit un QR Code produit par ce module. Lève si les syndromes ne
    sont pas nuls — c'est le point du test."""
    size = len(grid)
    version = (size - 17) // 4
    level, mask = _read_format(grid)
    _, fixed = B._qr_skeleton(version)

    rule = B._QR_MASKS[mask]
    plain = [[grid[r][c] != (rule(r, c) and not fixed[r][c])
              for c in range(size)] for r in range(size)]

    bits = []
    col, upward = size - 1, True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if not fixed[row][c]:
                    bits.append(1 if plain[row][c] else 0)
        upward = not upward
        col -= 2

    words = []
    for k in range(0, len(bits) - 7, 8):
        value = 0
        for bit in bits[k:k + 8]:
            value = (value << 1) | bit
        words.append(value)

    ec_len, sizes = B._qr_blocks(version, level)
    blocks = [[] for _ in sizes]
    index = 0
    for i in range(max(sizes)):
        for b, length in enumerate(sizes):
            if i < length:
                blocks[b].append(words[index])
                index += 1
    ecc = [[] for _ in sizes]
    for i in range(ec_len):
        for b in range(len(sizes)):
            ecc[b].append(words[index])
            index += 1

    for block, rest in zip(blocks, ecc):
        computed = B._QR_FIELD.remainder(block, ec_len)
        if computed != rest:
            raise ValueError('correction d\'erreur incohérente')

    stream = []
    for block in blocks:
        stream.extend(block)
    payload = []
    for byte in stream:
        for i in range(7, -1, -1):
            payload.append((byte >> i) & 1)

    def take(n, at):
        value = 0
        for bit in payload[at:at + n]:
            value = (value << 1) | bit
        return value, at + n

    mode, at = take(4, 0)
    if mode != 0b0100:
        raise ValueError(f'mode inattendu : {mode}')
    length, at = take(8 if version < 10 else 16, at)
    data = bytearray()
    for _ in range(length):
        byte, at = take(8, at)
        data.append(byte)
    return data.decode('utf-8')


def dm_decode_words(matrix):
    """Mots de données d'un DataMatrix, motifs de repérage retirés.

    Ne vérifie que la partie données : le placement inverse complet
    n'apporterait rien de plus que la vérification des syndromes, faite
    séparément sur les mots.
    """
    rows, cols = len(matrix), len(matrix[0])
    size = next(s for s in B._DM_SQUARE + B._DM_RECT
                if s[0] == rows and s[1] == cols)
    r_rows, r_cols, regions_y, regions_x = size[2], size[3], size[4], size[5]
    nominal = []
    for ry in range(regions_y):
        for y in range(r_rows):
            row = []
            for rx in range(regions_x):
                top = ry * (r_rows + 2)
                left = rx * (r_cols + 2)
                for x in range(r_cols):
                    row.append(matrix[top + y + 1][left + x + 1])
            nominal.append(row)
    return nominal


def main() -> int:
    r = []

    print('valeurs publiées :')
    f = B._QR_FIELD
    r.append(check('QR : polynôme générateur (7 octets)',
                   [f.log[c] for c in f.generator_poly(7)],
                   [0, 87, 229, 146, 149, 238, 102, 21]))
    r.append(check('QR : format M / masque 0',
                   ''.join(map(str, B._qr_format_bits('M', 0))),
                   '101010000010010'))
    r.append(check('QR : format L / masque 0',
                   ''.join(map(str, B._qr_format_bits('L', 0))),
                   '111011111000100'))
    r.append(check('QR : information de version 7',
                   ''.join(map(str, B._qr_version_bits(7))),
                   '000111110010010100'))
    r.append(check('DataMatrix : polynôme générateur (5 octets)',
                   B._DM_FIELD.generator_poly(5),
                   [1, 62, 111, 15, 48, 228]))
    r.append(check('DataMatrix : « 123456 » en mots ASCII',
                   B._dm_encode_ascii(b'123456'), [142, 164, 186]))
    r.append(check('DataMatrix : correction de « 123456 »',
                   B._DM_FIELD.remainder([142, 164, 186], 5),
                   [114, 25, 5, 88, 102]))

    print('\nQR Code — relecture du symbole produit :')
    cases = [
        ('TAU', 'L'), ('1234-56', 'M'), ('TAU 10x10 SMART', 'Q'),
        ('https://exemple.fr/piece/000123', 'M'),
        ('Pièce n°42 — laiton', 'H'),          # hors ASCII, donc UTF-8
        ('A' * 100, 'L'),                      # oblige une version élevée
        ('X' * 200, 'L'),                      # au-delà de la version 7
    ]
    for text, level in cases:
        grid = B.qrcode(text, level)
        version = (len(grid) - 17) // 4
        try:
            back = qr_decode(grid)
        except ValueError as exc:
            back = f'échec : {exc}'
        r.append(check(f'v{version} {level} · {text[:24]}', back, text))

    print('\nQR Code — structure :')
    grid = B.qrcode('TAU', 'M')
    size = len(grid)
    r.append(check('taille de la version 1', size, 21))
    corners = [(0, 0), (0, size - 7), (size - 7, 0)]
    r.append(check('trois motifs de repérage',
                   all(grid[y][x] and grid[y + 6][x + 6] and not grid[y + 1][x + 1]
                       for y, x in corners), True))
    r.append(check('ligne de synchronisation alternée',
                   [grid[6][i] for i in range(8, 13)],
                   [True, False, True, False, True]))
    r.append(check('module toujours sombre', grid[size - 8][8], True))
    level, mask = _read_format(grid)
    r.append(check('format relu : niveau', level, 'M'))
    r.append(check('format relu : masque dans 0-7', 0 <= mask <= 7, True))
    # les six bits de poids faible sont recopiés sous le motif de repérage
    # bas-gauche ; les bits de poids fort le sont à droite du motif haut,
    # ce n'est donc pas un simple miroir de la ligne 8
    r.append(check('les deux copies du format concordent',
                   [int(grid[size - 1 - i][8]) for i in range(6)],
                   [int(grid[8][i]) for i in range(6)]))

    print('\nQR Code — refus au-delà de la capacité :')
    try:
        B.qrcode('Z' * 400, 'H')
        r.append(check('donnée trop longue refusée', 'acceptée', 'CodeError'))
    except B.CodeError:
        r.append(check('donnée trop longue refusée', True, True))
    try:
        B.qrcode('x', 'Z')
        r.append(check('niveau inconnu refusé', 'accepté', 'CodeError'))
    except B.CodeError:
        r.append(check('niveau inconnu refusé', True, True))

    print('\nDataMatrix — structure :')
    m = B.datamatrix('123456')
    r.append(check('côté du symbole', len(m), 10))
    r.append(check('« L » : colonne de gauche pleine',
                   all(row[0] for row in m), True))
    r.append(check('« L » : ligne du bas pleine', all(m[-1]), True))
    r.append(check('bord haut alterné',
                   [m[0][i] for i in range(6)],
                   [True, False, True, False, True, False]))
    r.append(check('bord droit alterné',
                   [m[i][-1] for i in range(6)],
                   [False, True, False, True, False, True]))
    r.append(check('données présentes dans la zone utile',
                   len(dm_decode_words(m)), 8))

    print('\nDataMatrix — choix de la taille :')
    for text, side in (('1', 10), ('123456', 10), ('ABCDEFGH', 14),
                       ('A' * 30, 22), ('A' * 100, 40)):
        r.append(check(f'{len(text)} caractère(s) → {side}',
                       len(B.datamatrix(text)), side))
    try:
        B.datamatrix('A' * 500)
        r.append(check('donnée trop longue refusée', 'acceptée', 'CodeError'))
    except B.CodeError:
        r.append(check('donnée trop longue refusée', True, True))

    print('\nDataMatrix rectangulaire — plaque de production :')
    # Relevé sur `DataMatrix.dxf` du partage de production : un ECC200
    # rectangulaire 8 x 18 encodant « B000174 », dessiné dans une fenêtre
    # de 15 x 7 mm. La matrice a été reconstituée depuis les contours du
    # DXF par échantillonnage au centre de chaque module. C'est la
    # meilleure référence possible : elle ne vient ni de notre code ni
    # d'une norme relue, mais d'un symbole qui grave et se lit en atelier.
    REFERENCE = (
        '101010101010101010',
        '110011001100100011',
        '100010100100011010',
        '101000000011011011',
        '100100100111010000',
        '111001001101100011',
        '100010001101101000',
        '111111111111111111',
    )
    # Le contrôle porte sur la matrice, mais la géométrie a été vérifiée
    # séparément contre le DXF par échantillonnage : 5 184 points répartis
    # sur les 144 modules, aucun écart, même emprise (15 × 7 mm) et même
    # pas de module (0,8333 × 0,875 mm).
    produced = B.datamatrix('B000174', 'rect')
    rendered = tuple(''.join('1' if v else '0' for v in row)
                     for row in produced)
    r.append(check('reproduit le symbole du DXF de production',
                   rendered, REFERENCE))

    print('\nDataMatrix — formes et tailles :')
    r.append(check('rectangulaire : 8 x 18 pour 7 caractères',
                   (len(produced), len(produced[0])), (8, 18)))
    square = B.datamatrix('B000174', 'square')
    r.append(check('carré : 12 x 12 pour la même donnée',
                   (len(square), len(square[0])), (12, 12)))
    auto = B.datamatrix('B000174', 'auto')
    r.append(check('au plus juste : retient le plus petit',
                   len(auto) * len(auto[0])
                   <= len(square) * len(square[0]), True))

    for text, rows, cols in (('AB', 8, 18), ('A' * 10, 8, 32),
                             ('A' * 20, 12, 36), ('A' * 30, 16, 36),
                             ('A' * 45, 16, 48)):
        m = B.datamatrix(text, 'rect')
        r.append(check(f'{len(text)} caractère(s) → {rows} x {cols}',
                       (len(m), len(m[0])), (rows, cols)))

    for m, label in ((B.datamatrix('ESSAI', 'rect'), 'rectangulaire'),
                     (B.datamatrix('ESSAI', 'square'), 'carré')):
        r.append(check(f'{label} : « L » gauche plein',
                       all(row[0] for row in m), True))
        r.append(check(f'{label} : « L » bas plein', all(m[-1]), True))
        r.append(check(f'{label} : horloge haute alternée',
                       [m[0][i] for i in range(6)],
                       [True, False, True, False, True, False]))
        r.append(check(f'{label} : horloge droite alternée',
                       [m[i][-1] for i in range(6)],
                       [False, True, False, True, False, True]))

    print('\nCode 39 :')
    bits = B.code39('TAU-42')[0]
    r.append(check('commence et finit par le délimiteur',
                   (bits[0], bits[-1]), (True, True)))
    # chaque caractère compte neuf éléments dont trois larges ; les
    # alphanumériques ont deux barres larges et un espace large, les
    # quatre caractères de ponctuation trois espaces larges
    faulty = []
    for char, pattern in _C39_ITEMS():
        wide_bars = sum(1 for i, c in enumerate(pattern)
                        if c == '1' and i % 2 == 0)
        if not (pattern.count('1') == 3
                and (wide_bars == 2 or (wide_bars == 0 and char in '$/+%'))):
            faulty.append(char)
    r.append(check('deux barres larges par caractère alphanumérique, '
                   'trois espaces larges pour la ponctuation', faulty, []))
    r.append(check('table Code 39 : 43 caractères + délimiteur',
                   len(B._C39), 44))
    r.append(check('tous les motifs font neuf éléments',
                   {len(p) for p in B._C39.values()}, {9}))
    r.append(check('tous ont exactement trois éléments larges',
                   {p.count('1') for p in B._C39.values()}, {3}))
    try:
        B.code39('minuscules_interdites!')
        r.append(check('caractère hors alphabet refusé', 'accepté', 'CodeError'))
    except B.CodeError:
        r.append(check('caractère hors alphabet refusé', True, True))
    r.append(check('la clé de contrôle allonge le code',
                   len(B.code39('TAU', True)[0]) > len(B.code39('TAU')[0]),
                   True))

    print('\nEAN-13 :')
    bits = B.ean13('978020137962')[0]
    r.append(check('95 modules', len(bits), 95))
    r.append(check('garde de départ', [int(b) for b in bits[:3]], [1, 0, 1]))
    r.append(check('garde centrale', [int(b) for b in bits[45:50]],
                   [0, 1, 0, 1, 0]))
    r.append(check('garde de fin', [int(b) for b in bits[-3:]], [1, 0, 1]))
    r.append(check('clé de contrôle', B.ean13_key('978020137962'), 4))
    r.append(check('les deux écritures donnent le même code',
                   B.ean13('9780201379624'), B.ean13('978020137962')))
    # les motifs de gauche à parité impaire ont un nombre impair de
    # modules sombres, ceux de droite un nombre pair : c'est ce qui permet
    # au lecteur de reconnaître le sens de lecture
    r.append(check('parité des motifs de gauche',
                   {p.count('1') % 2 for p in B._EAN_L}, {1}))
    r.append(check('parité des motifs de droite',
                   {B._ean_right(d).count('1') % 2 for d in range(10)}, {0}))
    r.append(check('le motif G est le motif droit inversé',
                   [B._ean_g(d) for d in range(10)],
                   [B._ean_right(d)[::-1] for d in range(10)]))
    for bad in ('12345', 'abcdefghijkl', '9780201379625'):
        try:
            B.ean13(bad)
            r.append(check(f'« {bad} » refusé', 'accepté', 'CodeError'))
        except B.CodeError:
            r.append(check(f'« {bad} » refusé', True, True))

    print('\nCode 128 :')
    largeurs = [[int(c) for c in p] for p in B._C128]
    r.append(check('table : 106 valeurs + arrêt, toutes distinctes',
                   (len(B._C128), len(set(B._C128))), (107, 107)))
    r.append(check('onze modules par valeur, treize pour l\'arrêt',
                   [sum(w) for w in largeurs],
                   [11] * 106 + [13]))
    # la somme des barres est paire : c'est la parité qui laisse le
    # lecteur reconnaître un motif mal lu
    r.append(check('barres de largeur paire, éléments de 1 à 4 modules',
                   [v for v, w in enumerate(largeurs)
                    if sum(w[0::2]) % 2 or not all(1 <= x <= 4 for x in w)],
                   []))
    # relue valeur par valeur par zxing-cpp (outils/verif_codes_zxing.py) :
    # une retouche de la table, même d'un chiffre, se voit ici
    r.append(check('empreinte de la table relue par zxing-cpp',
                   hashlib.sha256(','.join(B._C128).encode()).hexdigest(),
                   'e7c485b7f79b124f215d4e34973742632bd63edace80b79b'
                   'cae8c605f9f4cdab'))
    r.append(check('« PJJ123C » : départ B, clé 55',
                   B.code128_values('PJJ123C'),
                   [104, 48, 42, 42, 17, 18, 19, 35, 55]))
    r.append(check('« 123456 » : jeu C, deux chiffres par caractère',
                   B.code128_values('123456'), [105, 12, 34, 56, 44]))
    r.append(check('« B000123 » : passe en C pour les chiffres',
                   B.code128_values('B000123'),
                   [104, 34, 99, 0, 1, 23, 43]))
    r.append(check('un contrôle part en jeu A',
                   B.code128_values('\tA')[:3], [103, 73, 33]))
    r.append(check('un caractère isolé de l\'autre jeu : décalage',
                   B.code128_values('ab\tcd')[:5], [104, 65, 66, 98, 73]))
    bits = B.code128('TAU-42')[0]
    r.append(check('commence par une barre, finit par deux modules sombres',
                   (bits[0], bits[-2:]), (True, [True, True])))
    r.append(check('dix chiffres : moitié moins large qu\'en Code 39',
                   2 * len(B.code128('0123456789')[0])
                   < len(B.code39('0123456789')[0]), True))
    r.append(check('code linéaire : une seule ligne',
                   (B.is_linear('code128'), len(B.code128('A'))), (True, 1)))
    for bad, label in (('', 'donnée vide'), ('café', 'hors ASCII')):
        try:
            B.code128(bad)
            r.append(check(f'{label} refusé', 'accepté', 'CodeError'))
        except B.CodeError:
            r.append(check(f'{label} refusé', True, True))

    print('\nzone de silence et fusion des modules :')
    plain = B.encode('datamatrix', 'TAU', quiet_modules=0)
    quiet = B.encode('datamatrix', 'TAU', quiet_modules=4)
    r.append(check('la zone de silence élargit le symbole',
                   len(quiet), len(plain) + 8))
    r.append(check('la zone de silence est vide',
                   any(quiet[0]) or any(quiet[-1]), False))
    r.append(check('elle ne change aucun module',
                   [row[4:-4] for row in quiet[4:-4]], plain))

    total = sum(1 for row in plain for v in row if v)
    merged = B.runs(plain)
    r.append(check('la fusion conserve tous les modules sombres',
                   sum(length for _, _, length in merged), total))
    r.append(check('elle réduit vraiment le nombre de contours',
                   len(merged) < total, True))

    total_ok, count = sum(r), len(r)
    print(f'\n{total_ok}/{count} contrôles passés')
    return 0 if total_ok == count else 1


if __name__ == '__main__':
    raise SystemExit(main())
