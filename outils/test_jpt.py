"""Validation du codec JPT contre le comportement de la GUI du fabricant.

Aucune capture réelle n'est disponible : les vecteurs de test sont
construits à partir de ce que la GUI livrée avec la source émet.

Usage : python test_jpt.py
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from jpt import protocol as J     # noqa: E402


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f'  [{"OK " if ok else "KO "}] {label}')
    if not ok:
        print(f'         obtenu : {got!r}')
        print(f'         attendu: {want!r}')
    return ok


def main() -> int:
    results = []

    print('trame émise :')
    # commande 9 à 0 (couper) -> cmd 09 00, len 02, data 00 00, entre $ et *
    results.append(check('LASER_EMISSION=0 (couper)',
                         J.encode_u16(J.Cmd.LASER_EMISSION, 0).hex(' '),
                         '24 09 00 02 00 00 2a'))
    results.append(check('POLL',
                         J.encode_u16(J.Cmd.POLL, 1).hex(' '),
                         '24 51 00 02 01 00 2a'))
    results.append(check('payload vide',
                         J.encode(J.Cmd.ALARM_RESET).hex(' '),
                         '24 10 00 00 2a'))

    print('\nconversion de puissance (PercentToBit / BitToPercent) :')
    results.append(check('100 % -> 4096', J.percent_to_bits(100), 4096))
    results.append(check('50 % -> 2048', J.percent_to_bits(50), 2048))
    results.append(check('15 % -> 614', J.percent_to_bits(15), 614))
    # lecture réponse 71 : percent = valeur / 40.96
    results.append(check('4096 -> 100 %', J.bits_to_percent(4096), 100.0))

    print('\ndécodage de flux (ReceivedDataHandler) :')
    stream = bytes.fromhex('24 38 00 02 e8 03 2a 24 3b 00 02 20 4e 2a')
    results.append(check('deux réponses enchaînées',
                         J.decode(stream),
                         [(56, b'\xe8\x03'), (59, b'\x20\x4e')]))
    results.append(check('resynchronisation sur octets parasites',
                         J.decode(b'\xff\xff' + stream[:7]),
                         [(56, b'\xe8\x03')]))
    results.append(check('trame incomplète ignorée',
                         J.decode(bytes.fromhex('24 38 00 08 01 02')),
                         []))

    print('\nchamps de bits (ByteBoolConverter.getBooleanArray) :')
    # LED status : PA + ENABLE actifs -> bits 0 et 3 -> 0x0009
    results.append(check('LED PA+ENABLE',
                         {k: v for k, v in
                          J.bits(b'\x09\x00', J.LED_BITS).items() if v},
                         {'PA': True, 'ENABLE': True}))
    # alarme : SeedPulseLose -> bit 4 -> 0x10
    results.append(check('alarme SeedPulseLose',
                         [k for k, v in
                          J.bits(b'\x10\x00', J.ALARM_BITS).items() if v],
                         ['SeedPulseLose']))
    results.append(check('aller-retour masque d\'alarme',
                         J.bits(J.pack_bits({'BoardTempLT': True,
                                             'SeedTEC': True}, J.ALARM_BITS),
                                J.ALARM_BITS),
                         {n: n in ('BoardTempLT', 'SeedTEC')
                          for n in J.ALARM_BITS}))

    print('\nréglages de port :')
    results.append(check('57600 8N1',
                         (J.BAUDRATE, J.BYTESIZE, J.PARITY, J.STOPBITS),
                         (57600, 8, 'N', 1)))

    total, ok = len(results), sum(results)
    print(f'\n{ok}/{total} contrôles passés')
    return 0 if ok == total else 1


if __name__ == '__main__':
    raise SystemExit(main())
