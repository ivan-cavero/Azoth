"""Bit-level I/O matching Javelin_BitStream_ReadBits / _WriteBits.

Semantics (from the decompilation, see REP-PROTOCOL.md): a cursor over a
byte buffer; reads/writes either memcpy aligned runs or shift byte-by-byte
through unaligned regions. Lower bits of each source byte map to lower bits
of each output byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class BitStreamError(Exception):
    """A read/write went past the end of the buffer."""


@dataclass
class BitStream:
    """Read-only bit-level view over a fixed buffer."""

    data: bytes
    start_bit: int = 0
    cursor_bit: int = 0
    end_bit: int = -1

    def __post_init__(self) -> None:
        if self.end_bit < 0:
            self.end_bit = len(self.data) * 8 - self.start_bit

    def remaining(self) -> int:
        return self.end_bit - self.cursor_bit

    def read_bits(self, n_bits: int) -> bytes:
        if n_bits > self.remaining():
            raise BitStreamError(
                f"read_bits({n_bits}) past end (cursor={self.cursor_bit}, "
                f"end={self.end_bit})"
            )
        out_len = (n_bits + 7) // 8
        out = bytearray(out_len)
        abs_bit = self.start_bit + self.cursor_bit
        byte_off = abs_bit >> 3
        bit_in_byte = abs_bit & 7
        if bit_in_byte == 0:
            out[:] = self.data[byte_off : byte_off + out_len]
        else:
            written = 0
            while written < n_bits:
                abs_bit = self.start_bit + self.cursor_bit + written
                byte_off = abs_bit >> 3
                bit_in_byte = abs_bit & 7
                lo = self.data[byte_off] >> bit_in_byte
                if byte_off + 1 < len(self.data) and bit_in_byte:
                    hi_mask = (1 << bit_in_byte) - 1
                    hi = (self.data[byte_off + 1] & hi_mask) << (8 - bit_in_byte)
                else:
                    hi = 0
                out[written // 8] = (hi | lo) & 0xFF
                written += 8
        # Keep only the requested bits: stream bit k lives at output bit k
        # (LSB-first), so mask the tail byte above n_bits % 8.
        tail = n_bits % 8
        if tail:
            out[-1] &= (1 << tail) - 1
        self.cursor_bit += n_bits
        return bytes(out)

    def read_u8(self) -> int:
        return self.read_bits(8)[0]

    def read_u16_be(self) -> int:
        return int.from_bytes(self.read_bits(16), "big")


@dataclass
class BitStreamWriter:
    """Grow-able bit-level writer; zero-pads to byte alignment on output."""

    buf: bytearray = field(default_factory=bytearray)
    cursor_bit: int = 0

    def write_bits(self, data: bytes, n_bits: int) -> None:
        if n_bits == 0:
            return
        if len(data) * 8 < n_bits:
            raise BitStreamError(
                f"write_bits: data has {len(data) * 8} bits, asked to write {n_bits}"
            )
        needed = (self.cursor_bit + n_bits + 7) // 8
        if needed > len(self.buf):
            self.buf.extend(b"\x00" * (needed - len(self.buf)))
        cursor_byte = self.cursor_bit >> 3
        bit_in_byte = self.cursor_bit & 7
        if bit_in_byte == 0:
            full, tail = n_bits // 8, n_bits % 8
            if full:
                self.buf[cursor_byte : cursor_byte + full] = data[:full]
            if tail:
                mask = (1 << tail) - 1
                self.buf[cursor_byte + full] = data[full] & mask
        else:
            written = 0
            while written < n_bits:
                src = data[written // 8]
                take = min(8, n_bits - written)
                abs_bit = self.cursor_bit + written
                dst = abs_bit >> 3
                dst_bit = abs_bit & 7
                space = 8 - dst_bit
                lo_bits = min(space, take)
                lo_mask = (1 << lo_bits) - 1
                self.buf[dst] &= ~(lo_mask << dst_bit) & 0xFF
                self.buf[dst] |= (src & lo_mask) << dst_bit
                if take > lo_bits:
                    hi_bits = take - lo_bits
                    hi_mask = (1 << hi_bits) - 1
                    self.buf[dst + 1] &= ~hi_mask & 0xFF
                    self.buf[dst + 1] |= (src >> lo_bits) & hi_mask
                written += take
        self.cursor_bit += n_bits

    def write_u8(self, value: int) -> None:
        self.write_bits(bytes([value & 0xFF]), 8)

    def write_u16_be(self, value: int) -> None:
        self.write_bits((value & 0xFFFF).to_bytes(2, "big"), 16)

    def to_bytes(self) -> bytes:
        return bytes(self.buf[: (self.cursor_bit + 7) // 8])
