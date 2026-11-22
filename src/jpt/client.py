"""Client série de la source JPT / JPT laser source serial client.

Bâti sur `jpt.protocol`. Deux transports :

  * `SerialTransport`   — liaison réelle (pyserial), COM4 57600 8N1
  * `SimulatedSource`   — source factice, pour développer sans matériel

>>> SÉCURITÉ <<<
Ce client **ne fait jamais émettre** le laser de classe 4. Les deux
commandes d'émission (`LASER_EMISSION`, `MO_ENABLE`) ne partent qu'à 0,
pour couper (`shutdown_emission`) ; toute autre valeur est refusée
(`EmissionNotAllowed`), y compris par `send` et `send_u16`. Toutes les
autres méthodes lisent l'état ou règlent des paramètres sans émission.

Ce refus ne remplace **jamais** la chaîne d'interlocks matérielle
(contact de cabine, arrêts d'urgence).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Protocol

from . import protocol as P

log = logging.getLogger(__name__)


class EmissionNotAllowed(RuntimeError):
    """Commande d'émission à une autre valeur que 0 : refusée, toujours."""


#: Commandes qui font émettre le laser : elles ne partent qu'à 0.
EMISSION_CMDS = frozenset((int(P.Cmd.LASER_EMISSION), int(P.Cmd.MO_ENABLE)))


class AckTimeout(TimeoutError):
    """La source n'a pas renvoyé l'écho de la commande."""


# --------------------------------------------------------------------------
# Transports
# --------------------------------------------------------------------------

class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, size: int) -> bytes: ...
    def close(self) -> None: ...


class SerialTransport:
    """Liaison série réelle via pyserial."""

    def __init__(self, port: str, baudrate: int = P.BAUDRATE,
                 timeout: float = 0.05) -> None:
        import serial  # importé tardivement : inutile en simulation
        self._port = serial.Serial(
            port=port, baudrate=baudrate, bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
            timeout=timeout)

    def write(self, data: bytes) -> None:
        self._port.write(data)

    def read(self, size: int) -> bytes:
        return self._port.read(size)

    def close(self) -> None:
        self._port.close()


class SimulatedSource:
    """Source JPT factice.

    Répond à chaque commande par son écho, et au POLL par une rafale d'état
    plausible. Permet de développer et de tester le client, l'UI et la
    couche de gravure sans matériel — et sans le moindre risque.

    Les valeurs renvoyées sont inventées, pas mesurées.
    """

    def __init__(self) -> None:
        self._out = bytearray()
        self._lock = threading.Lock()
        self.power_bits = 0
        self.frequency = 80000
        self.pulse_width = 100
        self.emission = False
        self.mo = False
        self.red = False

    # -- côté client -------------------------------------------------------

    def write(self, data: bytes) -> None:
        for cmd, payload in P.decode(data):
            self._handle(cmd, payload)

    def read(self, size: int) -> bytes:
        with self._lock:
            chunk = bytes(self._out[:size])
            del self._out[:len(chunk)]
        if not chunk:
            time.sleep(0.005)
        return chunk

    def close(self) -> None:
        pass

    # -- logique interne ---------------------------------------------------

    def _emit(self, cmd: int, data: bytes = b'') -> None:
        with self._lock:
            self._out += P.encode(cmd, data)

    def _u16(self, data: bytes) -> int:
        return int.from_bytes(data[:2], 'little') if len(data) >= 2 else 0

    def _handle(self, cmd: int, payload: bytes) -> None:
        if cmd == P.Cmd.SET_POWER_BITS:
            self.power_bits = self._u16(payload)
        elif cmd == P.Cmd.SET_FREQUENCY:
            self.frequency = self._u16(payload)
        elif cmd == P.Cmd.SET_PULSE_WIDTH:
            self.pulse_width = self._u16(payload)
        elif cmd == P.Cmd.LASER_EMISSION:
            self.emission = bool(self._u16(payload))
        elif cmd == P.Cmd.MO_ENABLE:
            self.mo = bool(self._u16(payload))
        elif cmd == P.Cmd.RED_POINTER:
            self.red = bool(self._u16(payload))
        elif cmd == P.Cmd.READ_SERIAL_NUMBER:
            self._emit(P.Reply.SERIAL_NUMBER, b'SIMULATED-0000')
            return

        self._emit(cmd, payload)          # écho d'acquittement

        if cmd == P.Cmd.POLL:
            self._burst()

    def _burst(self) -> None:
        leds = {'PA': self.mo, 'MO': self.mo, 'RED': self.red,
                'ENABLE': self.emission}
        self._emit(P.Reply.LED_STATUS, P.pack_bits(leds, P.LED_BITS))
        self._emit(P.Reply.POWER_PERCENT,
                   int(P.bits_to_percent(self.power_bits)).to_bytes(2, 'little'))
        self._emit(P.Reply.FREQUENCY, (self.frequency & 0xFFFF).to_bytes(2, 'little'))
        self._emit(P.Reply.PULSE_WIDTH, (self.pulse_width & 0xFFFF).to_bytes(2, 'little'))
        self._emit(P.Reply.ALARM_STATUS, P.pack_bits({}, P.ALARM_BITS))
        self._emit(P.Reply.ANALOG_SIGNALS, (32).to_bytes(2, 'little') * 4)


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

class JptClient:
    """Dialogue avec la source JPT.

        with JptClient(SimulatedSource()) as laser:
            laser.poll()
            print(laser.state)
    """

    def __init__(self, transport: Transport, *,
                 ack_timeout: float = P.ACK_TIMEOUT_MS / 1000,
                 retries: int = P.MAX_RETRIES) -> None:
        self._tr = transport
        self._ack_timeout = ack_timeout
        self._retries = retries

        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._last_cmd: int | None = None
        self._ack = threading.Event()
        self._stop = threading.Event()

        #: Dernier état connu, alimenté par les réponses.
        self.state: dict[str, object] = {}
        #: Appelé à chaque réponse décodée : (cmd, payload).
        self.on_reply: Callable[[int, bytes], None] | None = None

        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name='jpt-reader')
        self._reader.start()

    # -- cycle de vie ------------------------------------------------------

    def __enter__(self) -> 'JptClient':
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._stop.set()
        self._reader.join(timeout=1.0)
        self._tr.close()

    # -- boucle de lecture -------------------------------------------------

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._tr.read(256)
            except Exception:                      # port fermé, débranché…
                if not self._stop.is_set():
                    log.exception('lecture série interrompue')
                return
            if not chunk:
                continue
            self._buffer += chunk
            frames = P.decode(bytes(self._buffer))
            if not frames:
                continue
            # retire du tampon ce qui a été consommé
            consumed = sum(4 + len(d) for _, d in frames)
            idx = bytes(self._buffer).find(P.SOF)
            del self._buffer[:max(idx, 0) + consumed]
            for cmd, payload in frames:
                self._dispatch(cmd, payload)

    def _dispatch(self, cmd: int, payload: bytes) -> None:
        with self._lock:
            if cmd == self._last_cmd:
                self._ack.set()
        self._update_state(cmd, payload)
        if self.on_reply:
            try:
                self.on_reply(cmd, payload)
            except Exception:
                log.exception('rappel on_reply en échec')

    def _update_state(self, cmd: int, payload: bytes) -> None:
        R = P.Reply
        try:
            if cmd == R.LED_STATUS and len(payload) >= 2:
                self.state['leds'] = P.bits(payload, P.LED_BITS)
            elif cmd == R.ALARM_STATUS and len(payload) >= 1:
                flags = P.bits(payload, P.ALARM_BITS)
                self.state['alarms'] = flags
                self.state['alarm_active'] = [k for k, v in flags.items() if v]
            elif cmd == R.POWER_PERCENT and len(payload) >= 2:
                self.state['power_percent'] = int.from_bytes(payload[:2], 'little')
            elif cmd == R.FREQUENCY and len(payload) >= 2:
                self.state['frequency'] = int.from_bytes(payload[:2], 'little')
            elif cmd == R.PULSE_WIDTH and len(payload) >= 2:
                self.state['pulse_width'] = int.from_bytes(payload[:2], 'little')
            elif cmd == R.FEEDBACK_POWER and len(payload) >= 2:
                self.state['feedback_power_w'] = int.from_bytes(payload[:2], 'little')
            elif cmd == R.ANALOG_SIGNALS:
                self.state['analog'] = P.u16_array(payload)
            elif cmd in (R.SERIAL_NUMBER,):
                self.state['serial_number'] = payload.decode('latin1').strip('\x00')
            elif cmd == R.MCU_VERSION:
                self.state['mcu_version'] = payload.decode('latin1').strip('\x00')
            elif cmd == R.FPGA_VERSION:
                self.state['fpga_version'] = payload.decode('latin1').strip('\x00')
            elif cmd == R.LOCK_POWER and len(payload) >= 2:
                self.state['lock_power_percent'] = \
                    int.from_bytes(payload[:2], 'little') / 40.96
        except Exception:
            log.exception('décodage de la réponse %s en échec', cmd)

    # -- émission de commandes --------------------------------------------

    def send(self, cmd: int, data: bytes = b'', *, expect_ack: bool = True) -> bool:
        """Émet une commande. Retourne True si l'écho a été reçu.

        Réémet jusqu'à `retries` fois, comme le fait la GUI d'origine.
        Ne lève pas si `expect_ack` est faux (cas du POLL, dont l'écho
        n'est pas garanti).

        Une commande d'émission (`EMISSION_CMDS`) ne part qu'à 0 : toute
        autre valeur lève `EmissionNotAllowed`, sans rien écrire.
        """
        if int(cmd) in EMISSION_CMDS and any(data):
            raise EmissionNotAllowed(
                f'commande {int(cmd)} refusée : TauDrive ne fait jamais '
                'émettre le laser (classe 4), il ne sait que couper.')
        frame = P.encode(cmd, data)
        for attempt in range(1, self._retries + 1):
            with self._lock:
                self._last_cmd = int(cmd)
                self._ack.clear()
            self._tr.write(frame)
            if not expect_ack:
                return True
            if self._ack.wait(self._ack_timeout):
                return True
            log.warning('pas d\'écho pour la commande %s (essai %d/%d)',
                        cmd, attempt, self._retries)
        return False

    def send_u16(self, cmd: int, value: int, **kw) -> bool:
        return self.send(cmd, int(value).to_bytes(2, 'little'), **kw)

    # -- lectures (sans émission) -----------------------------------------

    def poll(self) -> None:
        """Demande une rafale d'état. Sans écho garanti."""
        self.send_u16(P.Cmd.POLL, 1, expect_ack=False)

    def read_serial_number(self) -> bool:
        return self.send_u16(P.Cmd.READ_SERIAL_NUMBER, 1)

    def read_alarm_record(self) -> bool:
        return self.send_u16(P.Cmd.READ_ALARM_RECORD, 1)

    def reset_alarms(self) -> bool:
        return self.send_u16(P.Cmd.ALARM_RESET, 1)

    # -- réglages (sans émission) -----------------------------------------

    def set_power_percent(self, percent: float) -> bool:
        if not 0 <= percent <= 100:
            raise ValueError(f'puissance hors bornes : {percent}')
        return self.send_u16(P.Cmd.SET_POWER_BITS, P.percent_to_bits(percent))

    def set_frequency_khz(self, khz: float) -> bool:
        """Fréquence de répétition, **en kHz**.

        Le champ étant un u16, la valeur ne peut pas être en Hz : 1300 kHz
        tient dans 16 bits, 1 300 000 Hz non. La plage annoncée par le
        constructeur pour cette source est 37…1300 kHz.

        Inféré de la largeur du champ, **pas encore mesuré sur le fil**.
        """
        value = int(round(khz))
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f'fréquence hors bornes u16 : {khz} kHz')
        if not P.FREQ_KHZ_MIN <= value <= P.FREQ_KHZ_MAX:
            log.warning('fréquence %d kHz hors plage constructeur (%d-%d kHz)',
                        value, P.FREQ_KHZ_MIN, P.FREQ_KHZ_MAX)
        return self.send_u16(P.Cmd.SET_FREQUENCY, value)

    def set_pulse_width_ns(self, ns: int) -> bool:
        """Largeur d'impulsion, **en nanosecondes** (u16).

        Cohérent avec les process de la machine (100, 120, 200 ns) et avec
        le « <200 ns » du manuel.
        """
        value = int(round(ns))
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f'largeur d\'impulsion hors bornes u16 : {ns} ns')
        return self.send_u16(P.Cmd.SET_PULSE_WIDTH, value)

    def set_gui_control(self, enabled: bool) -> bool:
        """Bascule en contrôle interne (GUI Full Ctrl) ou libre (Free Ctrl)."""
        return self.send_u16(P.Cmd.GUI_CONTROL_MODE, int(bool(enabled)))

    # -- pointeur : classe 2M, visible, sans danger de gravure -------------

    def set_red_pointer(self, on: bool) -> bool:
        return self.send_u16(P.Cmd.RED_POINTER, int(bool(on)))

    # -- ÉMISSION : classe 4 — couper seulement ---------------------------

    def shutdown_emission(self) -> None:
        """Coupe émission et MO, puis rend la main à la GUI.

        Séquence d'arrêt de la GUI du fabricant. C'est le seul usage des
        commandes d'émission : à 0.
        """
        self.send_u16(P.Cmd.LASER_EMISSION, 0)
        time.sleep(0.1)
        self.send_u16(P.Cmd.MO_ENABLE, 0)
        time.sleep(0.1)
        self.send_u16(P.Cmd.GUI_CONTROL_MODE, 0)
