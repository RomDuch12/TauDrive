"""Nos encodeurs de codes relus par un décodeur indépendant.

    python outils/verif_codes_zxing.py

Demande `zxing-cpp` et `numpy` (`pip install zxing-cpp numpy`), sur le
poste de développement seulement : l'application n'en dépend pas, et
`test_barcode` tourne sans eux.

`test_barcode` vérifie les encodeurs contre des valeurs normatives et le
symbole de production. Ce banc-ci les fait **lire** : chaque symbole est
dessiné en image, puis décodé par zxing-cpp, qui ne partage rien avec nos
tables. Une table fausse donne un code de bonne allure et illisible ; ici,
il ne se relit pas.

* DataMatrix carré et rectangulaire, QR aux quatre niveaux, Code 39 avec
  et sans clé, EAN-13, Code 128 : des données tirées au hasard, toutes
  tailles de symbole confondues ;
* Code 128 : **chacune des 106 valeurs** de la table, posée à la main dans
  un symbole — départs, changements de jeu, décalage et FNC compris.
"""
from __future__ import annotations

import pathlib
import random
import sys
from collections import Counter

try:
    import numpy as np
    import zxingcpp
except ImportError:
    print('zxing-cpp et numpy sont nécessaires : pip install zxing-cpp numpy')
    sys.exit(2)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from engrave import barcode as B  # noqa: E402

F = zxingcpp.BarcodeFormat
PX = 4


def _image(matrix, linear: bool):
    if linear:
        matrix = [matrix[0]] * 40
    a = np.array(matrix, dtype=bool)
    img = np.where(a, 0, 255).astype(np.uint8)
    return np.kron(img, np.ones((PX, PX), dtype=np.uint8))


def lit(matrix, fmt, linear: bool = False):
    res = zxingcpp.read_barcodes(_image(matrix, linear), formats=fmt)
    return res[0] if res else None


def main() -> int:
    rnd = random.Random(7)
    essais, echecs, exemples = Counter(), Counter(), {}

    def note(cle, ok, detail):
        essais[cle] += 1
        if not ok:
            echecs[cle] += 1
            exemples.setdefault(cle, detail)

    ascii_ = ''.join(chr(c) for c in range(32, 127))
    latin = ascii_ + ''.join(chr(c) for c in range(160, 256))
    for forme in ('square', 'rect'):
        for _ in range(600):
            n = rnd.choice([1, 2, 3, 5, 8, 13, 20, 30, 44, 60, 90, 120, 200])
            alphabet = rnd.choice([ascii_, '0123456789', latin])
            texte = ''.join(rnd.choice(alphabet) for _ in range(n))
            try:
                m = B.encode('datamatrix', texte, shape=forme,
                             quiet_modules=2)
            except B.CodeError:
                continue
            r = lit(m, F.DataMatrix)
            note(f'datamatrix {forme}', r is not None
                 and r.bytes == texte.encode('latin-1'), texte)

    for niveau in 'LMQH':
        for _ in range(300):
            n = rnd.choice([1, 5, 10, 17, 30, 50, 80, 120, 200, 300])
            alphabet = rnd.choice([ascii_, '0123456789', latin])
            texte = ''.join(rnd.choice(alphabet) for _ in range(n))
            try:
                m = B.encode('qr', texte, level=niveau, quiet_modules=4)
            except B.CodeError:
                continue
            r = lit(m, F.QRCode)
            # le QR porte la donnée en UTF-8
            note(f'qr {niveau}', r is not None and r.text == texte, texte)

    c39 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%'
    for somme in (False, True):
        for _ in range(400):
            texte = ''.join(rnd.choice(c39)
                            for _ in range(rnd.randint(1, 25)))
            m = B.encode('code39', texte, checksum=somme, quiet_modules=12)
            # Code39Std : en mode étendu, zxing lirait « $N » comme un
            # caractère de contrôle
            r = lit(m, F.Code39Std, linear=True)
            lu = r.text if r else None
            note(f'code39 clé={somme}', lu is not None and (
                lu == texte or (somme and lu[:-1] == texte)), texte)

    for _ in range(400):
        douze = ''.join(rnd.choice('0123456789') for _ in range(12))
        r = lit(B.encode('ean13', douze, quiet_modules=12), F.EAN13,
                linear=True)
        note('ean13', r is not None
             and r.text == douze + str(B.ean13_key(douze)), douze)

    familles = ('0123456789',
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-. ',
                'abcdefghijklmnopqrstuvwxyz0123456789',
                ''.join(chr(c) for c in range(128)),
                'abcAB12' + ''.join(chr(c) for c in range(32)))
    for alphabet in familles:
        for _ in range(500):
            texte = ''.join(rnd.choice(alphabet)
                            for _ in range(rnd.randint(1, 40)))
            r = lit(B.encode('code128', texte, quiet_modules=12), F.Code128,
                    linear=True)
            note('code128', r is not None
                 and r.bytes == texte.encode('ascii'), texte)

    # chaque valeur de la table Code 128, posée à la main
    vues = set()

    def symbole(valeurs, attendu, nom):
        cle = (valeurs[0]
               + sum(i * v for i, v in enumerate(valeurs[1:], 1))) % 103
        bits: list[bool] = []
        for v in valeurs + [cle, B._C128_ARRET]:
            for i, largeur in enumerate(B._C128[v]):
                bits.extend([i % 2 == 0] * int(largeur))
        r = lit([[False] * 12 + bits + [False] * 12], F.Code128, linear=True)
        ok = r is not None and (attendu is None or r.bytes == attendu)
        note('code128 table', ok, nom)
        if ok:
            vues.update(valeurs + [cle])

    for v in range(96):
        symbole([104, v], bytes([v + 32]), f'B{v}')
    for v in range(64, 96):
        symbole([103, v], bytes([v - 64]), f'A{v}')
    for v in range(100):
        symbole([105, v], f'{v:02d}'.encode(), f'C{v}')
    symbole([104, 33, 98, 65, 33], b'A\x01A', 'SHIFT')
    symbole([104, 33, 99, 12], b'A12', 'CODE C')
    symbole([103, 33, 100, 65], b'Aa', 'CODE B')
    symbole([104, 33, 101, 65], b'A\x01', 'CODE A')
    symbole([105, 12, 100, 33], b'12A', 'CODE B depuis C')
    symbole([105, 12, 101, 65], b'12\x01', 'CODE A depuis C')
    symbole([105, 102, 12, 34], None, 'FNC1')
    symbole([104, 33, 97, 34], None, 'FNC2')
    symbole([104, 96, 33], None, 'FNC3')
    symbole([104, 100, 33], None, 'FNC4')
    manquantes = sorted(set(range(106)) - vues)

    for cle in sorted(essais):
        ligne = f'  {cle:22} {essais[cle] - echecs[cle]}/{essais[cle]}'
        if echecs[cle]:
            ligne += f'   ex. {exemples[cle]!r:.60}'
        print(ligne)
    print(f'  table Code 128 : {106 - len(manquantes)}/106 valeurs relues'
          + (f', manquent {manquantes}' if manquantes else ''))
    total, rates = sum(essais.values()), sum(echecs.values())
    print(f'\n{total - rates}/{total} symboles relus')
    return 0 if not rates and not manquantes else 1


if __name__ == '__main__':
    sys.exit(main())
