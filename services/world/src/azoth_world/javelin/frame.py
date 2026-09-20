"""Javelin per-message framing (Carrier envelope + MessageRecords).

Mirrors Javelin_Carrier_ParseMessages / _WriteMessages; see
research/docs/REP-PROTOCOL.md for the wire layout and evidence.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class MessageFlags(enum.IntFlag):
    MF_RELIABLE = 0x01
    MF_CHUNKS = 0x04
    MF_SEQUENTIAL_ID = 0x08  # set: sequence auto-increments (field omitted)
    MF_SEQUENTIAL_REL_ID = 0x10  # set: relSeq auto-increments (field omitted)
    MF_DATA_CHANNEL = 0x20  # set: channel byte follows
    MF_NO_LENGTH = 0x40  # payload extends to end of datagram
    MF_CONNECTING = 0x80


class SystemMessageId(enum.IntEnum):
    SM_CONNECT_REQUEST = 1
    SM_CONNECT_ACK = 2
    SM_DISCONNECT = 3
    SM_CLOCK_SYNC = 4
    SM_CT_FIRST = 5
    SM_CT_ACKS = 6
    SM_CT_CONN_CONTROL = 7
    SM_CT_BANDWIDTH = 8


@dataclass
class CarrierEnvelope:
    """4-byte header on every post-DTLS datagram."""

    type_byte: int  # 0x80 plaintext / 0x81 LZ4-compressed (bit 7 always set)
    proto: int  # always 0x01
    sequence: int  # u16 BE

    @property
    def is_compressed(self) -> bool:
        return bool(self.type_byte & 1)


def parse_envelope(data: bytes) -> tuple[CarrierEnvelope, bytes]:
    """Strip the 4-byte Carrier envelope; validate magic + proto."""
    if len(data) < 4:
        raise ValueError(f"datagram too short ({len(data)}B) for envelope")
    type_byte, proto = data[0], data[1]
    if not (type_byte & 0x80) or (type_byte & 0x7E):
        raise ValueError(f"bad envelope type byte 0x{type_byte:02X}")
    if proto != 0x01:
        raise ValueError(f"bad envelope proto byte 0x{proto:02X}")
    seq = (data[2] << 8) | data[3]
    return CarrierEnvelope(type_byte, proto, seq), data[4:]


@dataclass
class MessageRecord:
    """One message record (mirrors the 0x38-byte in-memory struct)."""

    channel: int
    payload: bytes
    sequence: int = 0
    reliable_sequence: int = 0
    reliable: bool = False
    connecting: bool = False
    num_chunks: int = 1
    flags: int = 0
    # Override the writer's computed flag byte (piggyback ACK records etc.).
    flags_override: int | None = None

    @property
    def size(self) -> int:
        return len(self.payload)

    @property
    def is_system(self) -> bool:
        return self.channel == 3

    @property
    def system_msg_id(self) -> int | None:
        # System messages place the 1-byte msgId at the END of the payload.
        if not self.is_system or not self.payload:
            return None
        return self.payload[-1]


@dataclass
class ParseResult:
    messages: list[MessageRecord] = field(default_factory=list)
    error: str | None = None
    trailing_bits: int = 0


@dataclass
class MarshalState:
    """Cross-record state within one datagram (Carrier::WriteMessages)."""

    prev_channel: int = -1
    last_seq: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    last_rel_seq: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    has_written: list[bool] = field(default_factory=lambda: [False] * 4)


def parse_datagram(data: bytes, *, start_bit: int = 0) -> ParseResult:
    """Parse the record stream AFTER the 4-byte envelope has been stripped."""
    from .bitstream import BitStream, BitStreamError

    stream = BitStream(data, start_bit=start_bit)
    result = ParseResult()
    prev_channel = 0
    per_seq = [0, 0, 0, 0]
    per_rel = [0, 0, 0, 0]

    while stream.remaining() > 0:
        try:
            flags = stream.read_u8()
            size = stream.read_u16_be()
            no_length = bool(flags & MessageFlags.MF_NO_LENGTH)
            first_attempt = no_length and bool(flags & MessageFlags.MF_SEQUENTIAL_REL_ID)
            if no_length:
                stream.read_u8()  # 3-byte sub-header (4 for first-attempt form)
                if first_attempt:
                    stream.read_u8()

            reliable = bool(flags & MessageFlags.MF_RELIABLE)
            connecting = bool(flags & MessageFlags.MF_CONNECTING)

            if flags & MessageFlags.MF_DATA_CHANNEL:
                channel = stream.read_u8()
            else:
                channel = prev_channel
            if channel > 4:
                result.error = f"invalid channel {channel} (max 4)"
                return result
            prev_channel = channel

            if flags & MessageFlags.MF_CHUNKS:
                num_chunks = stream.read_u16_be()
            else:
                num_chunks = 1

            if not (flags & MessageFlags.MF_SEQUENTIAL_ID):
                sequence = stream.read_u16_be()
                per_seq[channel] = sequence
            else:
                per_seq[channel] = (per_seq[channel] + 1) & 0xFFFF
                sequence = per_seq[channel]

            if not (flags & MessageFlags.MF_SEQUENTIAL_REL_ID):
                rel_seq = stream.read_u16_be()
                per_rel[channel] = rel_seq
            elif reliable:
                per_rel[channel] = (per_rel[channel] + 1) & 0xFFFF
                rel_seq = per_rel[channel]
            else:
                rel_seq = per_rel[channel]

            n_bits = stream.remaining() if no_length else size * 8
            if not no_length and n_bits > stream.remaining():
                result.error = (
                    f"payload truncated: need {n_bits} bits, have {stream.remaining()}"
                )
                return result
            payload = stream.read_bits(n_bits)
            result.messages.append(
                MessageRecord(
                    flags=flags,
                    channel=channel,
                    sequence=sequence,
                    reliable_sequence=rel_seq,
                    reliable=reliable,
                    connecting=connecting,
                    num_chunks=num_chunks,
                    payload=payload,
                )
            )
        except BitStreamError as exc:
            result.error = str(exc)
            break
    result.trailing_bits = stream.remaining()
    return result


def marshal_record(writer, rec: MessageRecord, state: MarshalState) -> None:
    """Serialize one record (mirrors Javelin_Carrier_WriteMessages)."""
    if rec.channel not in (0, 1, 2, 3):
        raise ValueError(f"invalid channel {rec.channel} (must be 0..3)")
    c = rec.channel

    if rec.flags_override is not None:
        flags = rec.flags_override
        seq_seq = bool(flags & MessageFlags.MF_SEQUENTIAL_ID)
        rel_seq_seq = bool(flags & MessageFlags.MF_SEQUENTIAL_REL_ID)
        channel_changed = bool(flags & MessageFlags.MF_DATA_CHANNEL)
    else:
        # Writer optimization: seq == last+1 (u16 wrap) => omit the field.
        seq_seq = state.has_written[c] and ((state.last_seq[c] + 1) & 0xFFFF) == rec.sequence
        rel_seq_seq = (
            state.has_written[c]
            and rec.reliable
            and ((state.last_rel_seq[c] + 1) & 0xFFFF) == rec.reliable_sequence
        )
        # The canonical writer ALWAYS writes rel_seq (even non-reliable) —
        # the bandwidth optimization produced flag bytes the client rejects.
        channel_changed = state.prev_channel != c
        flags = 0
        if rec.reliable:
            flags |= MessageFlags.MF_RELIABLE
        if rec.num_chunks > 1:
            flags |= MessageFlags.MF_CHUNKS
        if seq_seq:
            flags |= MessageFlags.MF_SEQUENTIAL_ID
        if rel_seq_seq:
            flags |= MessageFlags.MF_SEQUENTIAL_REL_ID
        if channel_changed:
            flags |= MessageFlags.MF_DATA_CHANNEL
        if rec.connecting:
            flags |= MessageFlags.MF_CONNECTING

    writer.write_u8(flags)
    writer.write_u16_be(rec.size)
    if flags & MessageFlags.MF_NO_LENGTH:
        # NO_LENGTH layout (V3 data-channel form): a sub-header byte follows
        # the size; the payload then runs to the end of the datagram.
        writer.write_u8(0)
        if flags & MessageFlags.MF_SEQUENTIAL_REL_ID:  # first-attempt form
            writer.write_u8(0)
    if channel_changed:
        writer.write_u8(c)
    if flags & MessageFlags.MF_CHUNKS:
        writer.write_u16_be(rec.num_chunks)
    if not seq_seq:
        writer.write_u16_be(rec.sequence & 0xFFFF)
    if not rel_seq_seq:
        writer.write_u16_be(rec.reliable_sequence & 0xFFFF)
    writer.write_bits(rec.payload, rec.size * 8)

    state.prev_channel = c
    state.last_seq[c] = rec.sequence & 0xFFFF
    if rec.reliable:
        state.last_rel_seq[c] = rec.reliable_sequence & 0xFFFF
    state.has_written[c] = True


def marshal_datagram(records: list[MessageRecord]) -> bytes:
    from .bitstream import BitStreamWriter

    writer = BitStreamWriter()
    state = MarshalState()
    for rec in records:
        marshal_record(writer, rec, state)
    return writer.to_bytes()
