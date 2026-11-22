"""Validation du client JPT contre la source simulée.

Aucun matériel requis. Vérifie l'acquittement par écho, la mise à jour de
l'état, la conversion de puissance et le garde-fou d'émission.

Usage : python test_jpt_client.py
"""
from __future__ import annotations

import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from jpt import protocol as P                                   # noqa: E402
from jpt.client import JptClient, SimulatedSource, EmissionNotAllowed  # noqa: E402


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f'  [{"OK " if ok else "KO "}] {label}')
    if not ok:
        print(f'         obtenu : {got!r}\n         attendu: {want!r}')
    return ok


def settle(delay: float = 0.15) -> None:
    time.sleep(delay)


def main() -> int:
    r = []
    sim = SimulatedSource()

    with JptClient(sim) as laser:
        print('acquittement par écho :')
        r.append(check('SET_POWER_BITS acquitté', laser.set_power_percent(50), True))
        r.append(check('la source a bien reçu 2048 bits', sim.power_bits, 2048))
        r.append(check('SET_FREQUENCY (80 kHz) acquitté',
                       laser.set_frequency_khz(80), True))
        r.append(check('SET_PULSE_WIDTH (100 ns) acquitté',
                       laser.set_pulse_width_ns(100), True))
        try:
            laser.set_frequency_khz(80000)
            r.append(check('80000 kHz rejeté (hors u16)', 'accepté', 'ValueError'))
        except ValueError:
            r.append(check('80000 kHz rejeté (hors u16)', True, True))
        r.append(check('READ_SERIAL_NUMBER acquitté', laser.read_serial_number(), True))
        settle()
        r.append(check('numéro de série remonté',
                       laser.state.get('serial_number'), 'SIMULATED-0000'))

        print('\nrafale d\'état (POLL) :')
        laser.set_red_pointer(True)
        laser.poll()
        settle()
        r.append(check('puissance relue', laser.state.get('power_percent'), 50))
        r.append(check('pointeur rouge dans les LED',
                       laser.state.get('leds', {}).get('RED'), True))
        r.append(check('aucune alarme', laser.state.get('alarm_active'), []))
        r.append(check('signaux analogiques', laser.state.get('analog'), [32, 32, 32, 32]))

        print('\naucune émission possible :')
        r.append(check('ni set_emission ni set_mo ni allow_emission',
                       [hasattr(laser, n) for n in
                        ('set_emission', 'set_mo', '_allow_emission')],
                       [False, False, False]))
        try:
            laser.send_u16(P.Cmd.LASER_EMISSION, 1)
            r.append(check('LASER_EMISSION à 1 refusé', 'aucune erreur', 'EmissionNotAllowed'))
        except EmissionNotAllowed:
            r.append(check('LASER_EMISSION à 1 refusé', True, True))
        try:
            laser.send(P.Cmd.MO_ENABLE, b'\x01\x00')
            r.append(check('MO_ENABLE à 1 refusé', 'aucune erreur', 'EmissionNotAllowed'))
        except EmissionNotAllowed:
            r.append(check('MO_ENABLE à 1 refusé', True, True))
        r.append(check('la source n\'a jamais émis', (sim.emission, sim.mo), (False, False)))

        print('\ncoupure d\'urgence (toujours permise) :')
        sim.emission = sim.mo = True          # état d'une source armée ailleurs
        laser.shutdown_emission()
        settle()
        r.append(check('émission et MO à zéro', (sim.emission, sim.mo), (False, False)))

    print('\nabsence d\'écho -> échec après réémissions :')

    class Mute(SimulatedSource):
        def write(self, data: bytes) -> None:
            pass

    with JptClient(Mute(), ack_timeout=0.05, retries=2) as laser:
        r.append(check('retourne False', laser.set_frequency_khz(100), False))

    total, ok = len(r), sum(r)
    print(f'\n{ok}/{total} contrôles passés')
    return 0 if ok == total else 1


if __name__ == '__main__':
    raise SystemExit(main())
