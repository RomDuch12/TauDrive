"""Couche de trame CL90135 / CL90135 frame layer.

Structure de trame (validée sur 107/107 trames de COMANDI_USB_0.LOG) :

    10 02 | A5 | len:u16le | payload[len] | crc:u16le | 10 03
    DLE STX  ^addr                                      DLE ETX

  * addr  : 0xA5 sur toutes les trames observées (adresse de la carte).
  * len   : longueur du payload *après* dé-stuffing, little-endian.
  * crc   : CRC-16/ARC (poly 0x8005, init 0x0000, refin, refout, xorout 0x0000)
            calculé sur  len:u16le + payload  (donc len inclus, addr exclu),
            transmis little-endian.
  * Byte-stuffing : tout octet 0x10 du corps est émis en double (10 10).
            Le stuffing s'applique entre DLE STX et DLE ETX, addr et crc inclus.

Le contrôle du CRC peut être désactivé côté ClTerm via
DATITERMCFG.INI -> EnableNoUsoCheckCRC.
"""
from __future__ import annotations

DLE = 0x10
STX = 0x02
ETX = 0x03
ADDR_BOARD = 0xA5

_CRC_TABLE: list[int] = []


def _build_table() -> None:
    """Table CRC-16/ARC (polynôme réfléchi 0xA001)."""
    for byte in range(256):
        reg = byte
        for _ in range(8):
            reg = (reg >> 1) ^ 0xA001 if reg & 1 else reg >> 1
        _CRC_TABLE.append(reg)


_build_table()


def crc16(data: bytes) -> int:
    """CRC-16/ARC sur `data`."""
    reg = 0x0000
    for byte in data:
        reg = (reg >> 8) ^ _CRC_TABLE[(reg ^ byte) & 0xFF]
    return reg


def stuff(data: bytes) -> bytes:
    """Double chaque DLE. / Escape every DLE by doubling it."""
    out = bytearray()
    for byte in data:
        out.append(byte)
        if byte == DLE:
            out.append(DLE)
    return bytes(out)


def unstuff(data: bytes) -> bytes:
    """Inverse de `stuff`. / Inverse of `stuff`."""
    out = bytearray()
    i = 0
    while i < len(data):
        out.append(data[i])
        if data[i] == DLE and i + 1 < len(data) and data[i + 1] == DLE:
            i += 2
        else:
            i += 1
    return bytes(out)


class FrameError(ValueError):
    """Trame mal formée ou CRC invalide."""


def encode(payload: bytes, addr: int = ADDR_BOARD) -> bytes:
    """Construit une trame complète prête à émettre."""
    header = bytes([len(payload) & 0xFF, (len(payload) >> 8) & 0xFF])
    crc = crc16(header + payload)
    body = bytes([addr]) + header + payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    return bytes([DLE, STX]) + stuff(body) + bytes([DLE, ETX])


def decode(frame: bytes, *, check_crc: bool = True) -> tuple[int, bytes]:
    """Décode une trame complète. Retourne (addr, payload)."""
    if len(frame) < 9:
        raise FrameError(f'trame trop courte ({len(frame)} octets)')
    if frame[0] != DLE or frame[1] != STX:
        raise FrameError('en-tête DLE STX absent')
    if frame[-2] != DLE or frame[-1] != ETX:
        raise FrameError('terminateur DLE ETX absent')

    body = unstuff(frame[2:-2])
    if len(body) < 5:
        raise FrameError('corps trop court')

    addr = body[0]
    length = body[1] | (body[2] << 8)
    payload = body[3:3 + length]
    if len(payload) != length:
        raise FrameError(f'payload tronqué ({len(payload)}/{length})')

    crc_bytes = body[3 + length:3 + length + 2]
    if len(crc_bytes) != 2:
        raise FrameError('CRC absent')

    if check_crc:
        expected = crc16(body[1:3 + length])
        received = crc_bytes[0] | (crc_bytes[1] << 8)
        if expected != received:
            raise FrameError(f'CRC invalide : reçu {received:#06x}, calculé {expected:#06x}')

    return addr, payload


def split_stream(data: bytes) -> list[bytes]:
    """Découpe un flux d'octets en trames complètes.

    Le stuffing garantit qu'un DLE isolé suivi de STX/ETX est bien un délimiteur.
    Les octets hors trame sont ignorés.
    """
    frames: list[bytes] = []
    i = 0
    n = len(data)
    while i < n - 1:
        if data[i] != DLE or data[i + 1] != STX:
            i += 1
            continue
        j = i + 2
        while j < n - 1:
            if data[j] == DLE:
                if data[j + 1] == DLE:      # octet échappé
                    j += 2
                    continue
                if data[j + 1] == ETX:      # fin de trame
                    frames.append(data[i:j + 2])
                    i = j + 2
                    break
            j += 1
        else:
            break
    return frames
