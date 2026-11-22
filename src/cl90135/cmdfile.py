"""Décodeur du flux .CMD de ClTerm / ClTerm .CMD stream decoder.

Un fichier `cl_temp\\T*.CMD` est le tampon de trajectoire calculé par ClTerm
avant émission vers la carte CL90135.

    [ en-tête 492 octets (0x1EC) ] [ suite d'enregistrements ] EOF

Chaque enregistrement : `op:int32` little-endian suivi d'un payload de
longueur fixe par opcode. Le flux n'est PAS aligné sur 4 octets : l'opcode 4
mesure 41 octets (champ u8 au milieu), ce qui décale tout ce qui suit.

Table validée : parse exact jusqu'à EOF sur 173/173 fichiers du corpus.

    op  3 :  4 o  — marqueur nu, précède toujours un op 7
    op  4 : 41 o  — f64 vitesse | i32 masque axes | u8 | 3 x f64 X,Y,Z
    op  5 :  8 o  — i32
    op  6 : 20 o  — 4 x i32
    op  7 : 32 o  — 3 x f64 X,Y,Z | i32 drapeau (0 ou 1)
    op  8 : 28 o  — 3 x f64 X,Y,Z          (sans drapeau)
    op 18 : 16 o  — i32 | f64              (premier enregistrement du flux)
    op 24 : 24 o  — 5 x i32

La valeur 3.402823466e38 (FLT_MAX en double) sert de sentinelle
« axe non commandé » sur X, Y ou Z.

Ambiguïté formelle assumée : op 7 = 32 o avec drapeau final est équivalent,
au niveau octets, à op 7 = 28 o suivi d'un opcode nu 0 ou 1. La lecture
retenue est celle à 32 o, parce que op 8 (28 o, mêmes 3 doubles, sans
drapeau) serait sinon structurellement identique à op 7 — deux opcodes
distincts pour un même format n'aurait pas de sens.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator

HEADER_SIZE = 0x1EC

#: Sentinelle « axe non commandé » (FLT_MAX stocké en double).
AXIS_UNSET = 3.4028234663852886e38

#: opcode -> longueur totale de l'enregistrement, opcode inclus.
RECORD_SIZE: dict[int, int] = {
    3: 4,
    4: 41,
    5: 8,
    6: 20,
    7: 32,
    8: 28,
    18: 16,
    24: 24,
}


@dataclass(frozen=True)
class Record:
    offset: int
    op: int
    payload: bytes

    def i32(self, at: int) -> int:
        return struct.unpack_from('<i', self.payload, at)[0]

    def f64(self, at: int) -> float:
        return struct.unpack_from('<d', self.payload, at)[0]

    def u8(self, at: int) -> int:
        return self.payload[at]

    # --- accès typés pour les opcodes de mouvement ---

    @property
    def xyz(self) -> tuple[float, float, float] | None:
        """Coordonnées X, Y, Z ; None si l'opcode n'est pas un mouvement.

        Une composante vaut `AXIS_UNSET` quand l'axe n'est pas commandé.
        """
        if self.op in (7, 8):
            return self.f64(0), self.f64(8), self.f64(16)
        if self.op == 4:
            return self.f64(13), self.f64(21), self.f64(29)
        return None

    @property
    def flag(self) -> int | None:
        """Drapeau final de l'opcode 7 (0 ou 1)."""
        return self.i32(24) if self.op == 7 else None

    @property
    def feed(self) -> float | None:
        """Vitesse portée par l'opcode 4."""
        return self.f64(0) if self.op == 4 else None

    @property
    def axis_mask(self) -> int | None:
        """Masque d'axes de l'opcode 4."""
        return self.i32(8) if self.op == 4 else None

    def __repr__(self) -> str:
        return f'<Record {self.offset:#x} op={self.op} len={4 + len(self.payload)}>'


class CmdParseError(ValueError):
    """Opcode inconnu ou enregistrement tronqué."""


def iter_records(data: bytes, *, start: int = HEADER_SIZE,
                 strict: bool = True) -> Iterator[Record]:
    """Itère les enregistrements du flux.

    `strict=True` lève CmdParseError sur opcode inconnu ; sinon s'arrête.
    """
    i = start
    n = len(data)
    while i + 4 <= n:
        op = struct.unpack_from('<i', data, i)[0]
        size = RECORD_SIZE.get(op)
        if size is None:
            if strict:
                raise CmdParseError(
                    f'opcode inconnu {op} à {i:#x} '
                    f'({n - i} octets restants sur {n})')
            return
        if i + size > n:
            if strict:
                raise CmdParseError(f'enregistrement tronqué à {i:#x}')
            return
        yield Record(i, op, data[i + 4:i + size])
        i += size


def parse_file(path: str, *, strict: bool = True) -> list[Record]:
    with open(path, 'rb') as fh:
        return list(iter_records(fh.read(), strict=strict))


def header(data: bytes) -> bytes:
    return data[:HEADER_SIZE]


def is_unset(value: float) -> bool:
    """Vrai si la composante correspond à un axe non commandé."""
    return value > 1e38
