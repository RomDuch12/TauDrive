"""Protocole série de la source JPT / JPT laser source serial protocol.

Source : décompilation de `JPTLaserGUI20220104/JPT_Laser.exe` (.NET 4.5.2,
livré avec son PDB complet). Classes `JPT_Laser.RS232Class.RS232_send`,
`JPT_Laser.MainWindow` (`SerialPortWrite`, `ReceivedDataHandler`) et les
quatre `RS232_Data_processing` des ViewModels.

Liaison sur la machine : **COM4, 57600 bauds, 8N1** — `Config/default.conf`
de la GUI JPT et `P_06_01_01_018_02 = 3` (index 0-based dans COM1…COM24).

>>> ATTENTION <<<
Les commandes LASER_EMISSION (9) et MO_ENABLE (10) déclenchent l'émission
d'un laser de classe 4. Tout le reste de ce module est en lecture ou en
réglage de paramètre, sans émission.
"""
from __future__ import annotations

import struct
from enum import IntEnum

SOF = 0x24  # '$'  début de trame / start of frame
EOF = 0x2A  # '*'  fin de trame   / end of frame

BAUDRATE = 57600
BYTESIZE = 8
PARITY = 'N'
STOPBITS = 1

#: Délai d'attente de l'écho avant réémission (ms), 3 tentatives maximum.
ACK_TIMEOUT_MS = 500
MAX_RETRIES = 3


class Cmd(IntEnum):
    """Commandes PC -> source. / Host-to-source commands."""

    SET_POWER_BITS = 1        # u16, 0..4096  (voir percent_to_bits)
    SET_FREQUENCY = 2         # u16
    SET_PULSE_WIDTH = 3       # u16
    SET_DEFAULT_SIMMER = 4    # u16
    SET_DEFAULT_PULSE = 5     # u16
    SET_DEFAULT_FREQ = 6      # u16
    SET_EXT_FREQ_PINS = 7     # bitfield pin9 / pin23
    SET_CONTROL_SOURCE = 8    # interne / externe
    LASER_EMISSION = 9        # u16 0|1   <<< ÉMISSION >>>
    MO_ENABLE = 10            # u16 0|1   <<< MASTER OSCILLATOR >>>
    RED_POINTER = 11          # u16 0|1   pointeur rouge (classe 2M)
    SET_WAVE_COF = 12
    SET_MODEL_PUBLIC = 13
    SET_SERIAL_NUMBER = 14    # chaîne
    SET_ALARM_MASK = 15       # 2 octets, voir ALARM_BITS
    ALARM_RESET = 16          # u16 1
    SYS_17 = 17
    SYS_20 = 20
    SET_WAVE_COFS = 21
    GUI_CONTROL_MODE = 22     # 0 = Free Ctrl, 1 = GUI Full Ctrl
    SET_LOCK_POWER = 23       # u16 en bits
    SET_RED_POWER = 24         # u16
    SET_LOCK_ARRAY = 25
    SET_PREFERRED_WAY = 30     # 0 | 1 | 2
    SET_PRI_MODEL_PUBLIC = 31
    SET_FORMULA_FACTOR_A = 33
    SET_FORMULA_FACTOR_B = 34
    READ_SERIAL_NUMBER = 63
    REQ_80 = 80                # émise une fois à la connexion
    POLL = 81                  # tick périodique d'interrogation d'état
    READ_ALARM_RECORD = 82


class Reply(IntEnum):
    """Réponses source -> PC. / Source-to-host replies."""

    PREFERRED_WAY = 40
    DEFAULT_SIMMER = 50
    DEFAULT_PULSE_WIDTH = 51
    DEFAULT_FREQUENCY = 52
    EXT_FREQ_PINS = 53
    INSIDE_CONTROL = 54
    STATUS_55 = 55
    LED_STATUS = 56            # bitfield 16 bits, voir LED_BITS
    POWER_PERCENT = 57         # u16
    PULSE_WIDTH = 58           # u16
    FREQUENCY = 59             # u16
    ANALOG_SIGNALS = 60        # tableau de u16 (températures, etc.)
    MCU_VERSION = 61           # chaîne
    FPGA_VERSION = 62          # chaîne
    SERIAL_NUMBER = 63         # chaîne
    ALARM_STATUS = 64          # bitfield 8 bits, voir ALARM_BITS
    ALARM_MASK = 65
    ALARM_TIMES = 66
    MONITOR_STD = 67
    LASER_TIMES = 70
    LOCK_POWER = 71            # u16, pourcentage = valeur / 40.96
    RED_POWER = 72
    LOCK_ARRAY = 73
    STATUS_75 = 75
    ALARM_RECORD = 82
    MONITOR_EM7 = 83
    CW_POWER = 100
    FORMULA_FACTOR_A = 101
    FORMULA_FACTOR_B = 102
    FEEDBACK_POWER = 103       # u16, en watts
    HIDE_SYSTEM_TAB = 104
    SHOW_STRENGTH_MODEL = 105
    LASER_TYPE_Q = 123


#: Réponse 56 — bit -> signification. LSB en premier.
LED_BITS = ('PA', 'MO', 'RED', 'ENABLE',
            'D7', 'D6', 'D5', 'D4', 'D3', 'D2', 'D1', 'D0')

#: Réponse 64 et commande 15 — bit -> alarme. LSB en premier.
ALARM_BITS = ('OpticalTempOT', 'BoardTempOT', 'PreCurrentLow', 'SeedTEC',
              'SeedPulseLose', 'PowerSupplyLow', 'OpticalTempLT', 'BoardTempLT')

MAX_POWER_BITS = 4096

#: Plage de fréquence annoncée par le constructeur pour cette source (kHz).
#: Le champ de la commande 2 étant un u16, l'unité ne peut pas être le hertz :
#: 1300 kHz tient dans 16 bits, 1 300 000 Hz non.
FREQ_KHZ_MIN = 37
FREQ_KHZ_MAX = 1300


class JptFrameError(ValueError):
    """Trame JPT mal formée."""


def percent_to_bits(percent: float) -> int:
    """Pourcentage de puissance -> valeur brute (0..4096)."""
    return int(MAX_POWER_BITS * percent / 100)


def bits_to_percent(bits: int) -> float:
    """Valeur brute -> pourcentage. Réciproque de `percent_to_bits`."""
    return bits * 100 / MAX_POWER_BITS


def encode(cmd: int, data: bytes = b'') -> bytes:
    """Construit une trame à émettre.

        '$' | cmd:u16le | len:u8 | data[len] | '*'
    """
    if len(data) > 0xFF:
        raise JptFrameError(f'payload trop long ({len(data)} octets, max 255)')
    return (bytes([SOF]) + struct.pack('<H', int(cmd))
            + bytes([len(data)]) + data + bytes([EOF]))


def encode_u16(cmd: int, value: int) -> bytes:
    """Trame dont le payload est un seul u16 little-endian."""
    return encode(cmd, struct.pack('<H', value))


def decode(stream: bytes) -> list[tuple[int, bytes]]:
    """Extrait les réponses d'un flux d'octets.

    Réplique la machine à états de `MainWindow.ReceivedDataHandler` :
    resynchronisation sur '$', puis cmd:u16le, len:u8, data[len].
    Les octets hors trame (dont le '*' final) sont ignorés.
    """
    out: list[tuple[int, bytes]] = []
    i = 0
    n = len(stream)
    while i < n:
        if stream[i] != SOF:
            i += 1
            continue
        if i + 4 > n:
            break
        cmd = struct.unpack_from('<H', stream, i + 1)[0]
        length = stream[i + 3]
        if i + 4 + length > n:
            break                      # trame incomplète, on attend la suite
        out.append((cmd, stream[i + 4:i + 4 + length]))
        i += 4 + length
    return out


def bits(data: bytes, names: tuple[str, ...]) -> dict[str, bool]:
    """Décode un champ de bits little-endian selon `names` (LSB en premier).

    Reproduit `ByteBoolConverter.getBooleanArray` : bit i du u16 formé par
    data[0] (poids faible) et data[1] (poids fort).
    """
    value = data[0] | (data[1] << 8 if len(data) > 1 else 0)
    return {name: bool(value >> i & 1) for i, name in enumerate(names)}


def pack_bits(flags: dict[str, bool], names: tuple[str, ...]) -> bytes:
    """Réciproque de `bits`, sur 2 octets."""
    value = 0
    for i, name in enumerate(names):
        if flags.get(name):
            value |= 1 << i
    return struct.pack('<H', value)


def u16_array(data: bytes) -> list[int]:
    """Découpe un payload en u16 little-endian (réponse 60 notamment)."""
    return list(struct.unpack(f'<{len(data) // 2}H', data[:len(data) // 2 * 2]))
