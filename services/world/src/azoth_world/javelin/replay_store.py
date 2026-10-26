"""
Replay store for the redacted login dump at
info/nw-login-safe-20260502-153840/messages-redacted.txt.

Parses Mixed Nuts' xxd-style capture of a working login (177 messages) into
ReplayMessage records keyed by seq. Redacted spans (XX) are preserved as
0x00 bytes plus an explicit (offset, length) span list, so callers can decide
whether to skip a message or substitute their own bytes.

R-direction messages start with the typed-stream marker:
    [0x00 0x01] <prefix varint type>

i.e. a two-byte tag then the type encoded by the shared prefix varint (see
`varint.py`). The earlier description here -- `[(type & 0x3F) | 0x80]
[(type >> 6) & 0xFF]` -- was wrong and produced 80 spurious marker warnings out
of 138 server->client messages. It only ever looked right for types below 0x40,
and it misread every two-byte type such as 0x15d (`9d 05`). W-direction
messages have a 24-byte client-only header before that marker, so we don't
enforce it there.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path


# Explicit 36-byte UUID slots redacted to zero in the 1.365 capture. The
# offsets include the four-byte typed-stream header. Keep this allowlist
# narrow: broad replacement would corrupt unrelated replica identities.
REPLAY_IDENTITY_TARGETS: dict[int, tuple[int, int, int]] = {
    0x28: (0x16A0, 0x5C, 36),  # player-spawn candidate before ItemPool data
    0x73: (0x0008, 0x21, 36),
    0x98: (0x0008, 0x21, 36),
    0x9A: (0x0008, 0x21, 36),
    0x9C: (0x0008, 0x21, 36),
    0x9E: (0x0008, 0x21, 36),
}


@dataclass
class ReplayMessage:
    seq: int
    type_id: int
    direction: str
    body: bytes
    has_redaction: bool
    redacted_spans: list[tuple[int, int]] = field(default_factory=list)
    # Diagnostics: how many spans the last substitution actually rewrote.
    substituted_spans: int = 0


def remap_replay_identity(
    message: ReplayMessage,
    *,
    selector: str,
    session_uuid: str = "",
    character_id: str = "",
) -> ReplayMessage:
    """Return a same-length copy with one proven redacted UUID slot filled.

    The selector is deliberately explicit. Unknown selectors fail closed by
    returning the original message; the caller can log the attempted mode.
    """
    mode = selector.lower()
    if mode == "off":
        return message
    if mode == "session":
        value = session_uuid
    elif mode == "character":
        value = character_id
    else:
        return message
    replacement = value.encode("ascii") if value else b""
    target = REPLAY_IDENTITY_TARGETS.get(message.seq)
    if target is None or len(replacement) != 36:
        return message
    expected_type, offset, length = target
    end = offset + length
    if message.type_id != expected_type or end > len(message.body):
        return message
    # Only replace the exact redaction representation. If the capture ever
    # changes or another tool already filled it, leave the message untouched.
    if message.body[offset:end] != b"\x00" * length:
        return message
    body = message.body[:offset] + replacement + message.body[end:]
    return replace(message, body=body)


# Wire type 0x65c IS self-identification. MEASURED 2026-10-25 on build
# 30fe6461 by walking the client's own registration hook: lambda TypeDescriptor
# 0x14a15a2b0 (its name at 0x14a15a2c0 spells
# `InstallRegistrationHook@VPlayerManagerSelfIdentificationMsg@ClientMessagesTrait@Javelin`),
# thunk 0x1414f2b00, record 0x148012b10 slot4 0x1414f2940, which calls
# 0x1416ec940 whose `lea r11,[rip+0x6917808]` at 0x1416ec9f1 points at
# 0x148004200 = `169443e0-a508-4653-b437-49b7a195f69c` = typeIndex[1628] = 0x65c.
# The control is LevelInfoChangedMsg, which the same method resolves to 0x663.
# An earlier version of this comment claimed the opposite from .rdata adjacency
# (the string `LastSpawnedBotCharacterId` sits three names before that GUID at
# 0x1480041e0/0x148004200); that heuristic is disproven by the control, because
# research/derived/wire-type-names.json gives the proven LevelInfoChangedMsg GUID
# no name at all. (That file is the retired adjacency heuristic; the hook-based
# research/derived/replay-type-names.json does name it, 40/40 of the replay.)
# So filling this slot does target player identity.
#
# The 0x65c record has TWO separate binary GUID fields, both left as sixteen
# zero bytes by redaction (measured 2026-10-26): this prefix slot at record
# 0x05 and a second at record 0x3192, the last 16 bytes of the record. Both are
# preceded by the byte 0x05, so the message plausibly carries two identity
# slots of the same shape. This target fills only the prefix one; nothing
# fills the tail one, and which of the two the client consumes is unmeasured.
# Keep this target explicit and preserve the source message unless the exact
# slot is zero.
REPLAY_SELFIDENT_GUID_TARGET = (0x06, 0x065C, 0x05, 16)
# The capture repeats seq 0x663 at 0x4d with the same context key. After the
# first context load consumes that key, the duplicate is ignored by the
# client-side dedup check. This is the exact serialized key field.
REPLAY_FRESH_LEVELINFO_TARGET = (0x4D, 0x0663, 0x66, 8)
REPLAY_CAPTURED_LEVELINFO_KEY = bytes.fromhex("000000c17f9be48f")


def remap_fresh_levelinfo_key(
    message: ReplayMessage,
    *,
    selector: str,
    session_uuid: str = "",
    character_id: str = "",
) -> ReplayMessage:
    """Give the repeated LevelInfo record a fresh, session-derived key."""
    mode = selector.lower()
    if mode == "session":
        value = session_uuid
    elif mode == "character":
        value = character_id
    else:
        return message
    try:
        replacement = uuid.UUID(value).bytes[:8]
    except (ValueError, AttributeError):
        return message
    seq, expected_type, offset, length = REPLAY_FRESH_LEVELINFO_TARGET
    end = offset + length
    if (
        message.seq != seq
        or message.type_id != expected_type
        or end > len(message.body)
        or message.body[offset:end] != REPLAY_CAPTURED_LEVELINFO_KEY
        or message.body[offset:end] == replacement
    ):
        return message
    body = message.body[:offset] + replacement + message.body[end:]
    return replace(message, body=body)


def remap_selfident_guid(
    message: ReplayMessage,
    *,
    selector: str,
    session_uuid: str = "",
    character_id: str = "",
) -> ReplayMessage:
    """Fill the redacted 0x65c GUID with a selected live UUID.

    The message is `PlayerManagerSelfIdentificationMsg` (wire 0x65c), measured
    through the client's registration hook with a validated control; see the note
    on REPLAY_SELFIDENT_GUID_TARGET. Filling this slot therefore does target
    player identity, which is why the 2026-09-24 negative result matters.

    ``session`` and ``character`` use RFC/network byte order, which is also
    the order consumed by the 1.400 GUID formatter. Unknown selectors and
    invalid UUIDs fail closed by returning the original message.
    """
    mode = selector.lower()
    if mode == "off":
        return message
    if mode == "session":
        value = session_uuid
    elif mode == "character":
        value = character_id
    else:
        return message
    try:
        replacement = uuid.UUID(value).bytes
    except (ValueError, AttributeError):
        return message
    seq, expected_type, offset, length = REPLAY_SELFIDENT_GUID_TARGET
    end = offset + length
    if (
        message.seq != seq
        or message.type_id != expected_type
        or end > len(message.body)
        or message.body[offset:end] != b"\x00" * length
    ):
        return message
    body = message.body[:offset] + replacement + message.body[end:]
    return replace(message, body=body)


# Full redacted-span substitution for the 1.365 capture. The earlier
# remap_replay_identity() only handled six allowlisted 36-byte text UUID
# slots; first-light's StateBundle analysis shows most identity redactions
# are 16-byte binary GUIDs inside the large init bundles (record 1 is the
# local-player metadata record). This mode fills every redacted span of a
# known length, leaving the 8-byte AzCore hashes zero-filled. Default off:
# each selector is an A/B knob, never applied to the live path implicitly.
SPAN_SUBSTITUTION_SELECTORS = ("character", "session", "persona", "mixed")


def _span_uuid_bytes(value: str) -> bytes:
    """Parse a dashed UUID into its 16 RFC/network-order bytes."""
    try:
        return uuid.UUID(value).bytes
    except (ValueError, AttributeError):
        return b""


def _span_uuid_text(value: str) -> str:
    """Canonical dashed text for a UUID, or '' when the input is invalid."""
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return ""


def _persona_text_uuid(persona_id: str) -> str:
    """Trailing UUID of 'amzn1.developerPersonaId.<uuid>' ('' if absent)."""
    if len(persona_id) < 36:
        return ""
    return _span_uuid_text(persona_id[-36:])


def _fit_bytes(data: bytes, length: int) -> bytes:
    if len(data) >= length:
        return data[:length]
    return data + b"\x00" * (length - len(data))


def _pad_name(text: str, length: int) -> bytes:
    raw = text.encode("ascii", errors="replace")
    if len(raw) >= length:
        return raw[:length]
    return raw + b"0" * (length - len(raw))


def apply_span_substitution(
    message: ReplayMessage,
    *,
    selector: str,
    session_uuid: str = "",
    character_id: str = "",
    persona_id: str = "",
    display_name: str = "NWPrivateTester01",
    seqs: set[int] | None = None,
    lengths: set[int] | None = None,
) -> ReplayMessage:
    """Fill every redacted span of a known length with a live identity value.

    Length classes follow first-light's capture conventions:

        8        AzCore-CRC hash; stays zero-filled (no source available)
        16       raw-binary UUID (character / session / persona)
        18,19,20 length-prefixed character display name
        36       dashed UUID text
        61       'amzn1.developerPersonaId.<uuid>' text

    ``character`` and ``mixed`` use the character UUID for the 16/36-byte
    player fields; ``session`` uses the live V3 session UUID; ``persona``
    uses the persona UUID for 16/36 and the full persona text for 61.
    Unknown selectors and invalid UUIDs fail closed (original message).
    """
    mode = selector.lower()
    if mode == "off" or not message.has_redaction:
        return message
    if mode not in SPAN_SUBSTITUTION_SELECTORS:
        return message
    if seqs is not None and message.seq not in seqs:
        return message

    character_bytes = _span_uuid_bytes(character_id)
    character_text = _span_uuid_text(character_id)
    session_bytes = _span_uuid_bytes(session_uuid)
    session_text = _span_uuid_text(session_uuid)
    persona_uuid_text = _persona_text_uuid(persona_id)
    persona_uuid_bytes = _span_uuid_bytes(persona_uuid_text)
    persona_text = persona_id.encode("ascii") if persona_id else b""

    if mode == "session":
        uuid_16, uuid_36 = session_bytes, session_text
    elif mode == "persona":
        uuid_16, uuid_36 = persona_uuid_bytes, persona_uuid_text
    elif mode == "mixed":
        # first-light's captured conventions: 16-byte = persona UUID,
        # 36-byte dashed text = session UUID, 61-byte = persona id text.
        uuid_16, uuid_36 = persona_uuid_bytes, session_text
    else:  # character -> player-owned identity
        uuid_16, uuid_36 = character_bytes, character_text
    if not uuid_16 and not uuid_36:
        return message  # fail closed: the selector's UUID source is invalid

    values: dict[int, bytes] = {
        16: uuid_16,
        36: uuid_36.encode("ascii") if uuid_36 else b"",
        61: persona_text,
    }
    for length in (18, 19, 20):
        values[length] = _pad_name(display_name, length)

    out = bytearray(message.body)
    written = 0
    for offset, length in message.redacted_spans:
        if lengths is not None and length not in lengths:
            continue
        replacement = values.get(length)
        if not replacement or len(replacement) != length:
            continue
        end = offset + length
        if end > len(out):
            continue
        if out[offset:end] != b"\x00" * length:
            continue  # only the zero-filled capture form is a valid target
        out[offset:end] = replacement
        written += 1
    if not written:
        return message
    return replace(message, body=bytes(out), substituted_spans=written)


def _looks_like_prefixed_name(body: bytes, offset: int) -> bool:
    """True when ``body[offset]`` is a length followed by that many ASCII bytes.

    This is the wire shape of the player-name field that follows the player
    UUID inside a PlayerComponentClientFacet record: ``[u8 len][name]``.
    """
    if offset >= len(body):
        return False
    length = body[offset]
    if not 1 <= length <= 40:
        return False
    end = offset + 1 + length
    if end > len(body):
        return False
    return all(0x20 <= b < 0x7F for b in body[offset + 1 : end])


def fill_local_player_uuid(
    message: ReplayMessage,
    *,
    character_id: str = "",
    session_uuid: str = "",
    selector: str = "character",
    seqs: set[int] | None = None,
) -> ReplayMessage:
    """Fill the redacted UUID of the captured player's OWN facet record.

    WHY this exists separately from ``apply_span_substitution``. The client's
    local-player gate compares the UUID carried by a PlayerComponentClientFacet
    against the character UUID in its local option store, and only a match
    lets the manager context be set (measured 2026-10-01: 26/26 comparisons
    returned status 2, 26/26 of them with a successful local lookup). In the
    capture EVERY player's facet carries that UUID in clear text except the
    capture author's own, which is redacted to zeros - and that one is the
    record that has to be *ours*.

    The slot is unambiguous: it is a redacted 16-byte span immediately
    followed by the length-prefixed display name of the same record
    (``<16 zero bytes> <len> <name>``). In the 46 KB state bundles that
    selects exactly one span per message (verified on seqs 0x25-0x6c: the
    other two 16-byte spans are not followed by a printable name), so a
    broad length-based substitution is not needed and the interest=91
    bundles stay untouched.

    ``character`` writes the live character UUID, ``session`` the V3 session
    UUID. Unknown selectors and invalid UUIDs fail closed.
    """
    mode = selector.lower()
    if mode == "off" or not message.has_redaction:
        return message
    if seqs is not None and message.seq not in seqs:
        return message
    if mode == "character":
        replacement = _span_uuid_bytes(character_id)
    elif mode == "session":
        replacement = _span_uuid_bytes(session_uuid)
    else:
        return message
    if len(replacement) != 16:
        return message

    out = bytearray(message.body)
    written = 0
    for offset, length in message.redacted_spans:
        if length != 16:
            continue
        end = offset + length
        if end > len(out):
            continue
        if out[offset:end] != b"\x00" * 16:
            continue  # only the zero-filled capture form is a valid target
        if not _looks_like_prefixed_name(bytes(out), end):
            continue
        out[offset:end] = replacement
        written += 1
    if not written:
        return message
    return replace(message, body=bytes(out), substituted_spans=written)


_HEADER_RE = re.compile(
    r"^seq:\s*0x([0-9a-fA-F]+)\s*\((\d+)\)\s*$"
)
_TYPE_RE = re.compile(
    r"^type:\s*0x([0-9a-fA-F]+)\s*\((\d+)\)\s*$"
)
_DIR_RE = re.compile(r"^direction:\s*([WR])\s*$")
_SIZE_RE = re.compile(r"^size:\s*(\d+)\s*bytes\s*$")
_HEX_ROW_RE = re.compile(
    r"^([0-9a-fA-F]{8})\s+((?:[0-9a-fA-FxX]{2}\s+){1,16})\|"
)
_SEPARATOR = "=" * 16  # any line with >= 16 '=' chars marks a block boundary


def _parse_hex_row(line: str) -> tuple[int, list[str]] | None:
    m = _HEX_ROW_RE.match(line)
    if not m:
        return None
    offset = int(m.group(1), 16)
    tokens = m.group(2).split()
    return offset, tokens


def _decode_body(
    hex_rows: list[tuple[int, list[str]]],
) -> tuple[bytes, list[tuple[int, int]]]:
    body = bytearray()
    spans: list[tuple[int, int]] = []
    cur_span_start: int | None = None

    for offset, tokens in hex_rows:
        if offset != len(body):
            raise ValueError(
                f"hex row offset 0x{offset:x} does not match body length "
                f"0x{len(body):x} (rows out of order or gap)"
            )
        for tok in tokens:
            pos = len(body)
            if tok in ("XX", "xx"):
                body.append(0x00)
                if cur_span_start is None:
                    cur_span_start = pos
            else:
                if cur_span_start is not None:
                    spans.append((cur_span_start, pos - cur_span_start))
                    cur_span_start = None
                body.append(int(tok, 16))

    if cur_span_start is not None:
        spans.append((cur_span_start, len(body) - cur_span_start))

    return bytes(body), spans


class ReplayStore:
    def __init__(self, dump_path: Path):
        self._path = Path(dump_path)
        self._messages: list[ReplayMessage] = []
        self._by_seq: dict[int, ReplayMessage] = {}
        self.validation_warnings: list[str] = []
        self._parse()

    @property
    def messages(self) -> list[ReplayMessage]:
        return list(self._messages)

    def get(self, seq: int) -> ReplayMessage | None:
        return self._by_seq.get(seq)

    def messages_in_range(
        self,
        start_seq: int,
        end_seq: int,
        direction: str | None = None,
    ) -> list[ReplayMessage]:
        out = []
        for m in self._messages:
            if not (start_seq <= m.seq <= end_seq):
                continue
            if direction is not None and m.direction != direction:
                continue
            out.append(m)
        return out

    def replay_messages_after_v3(
        self, max_seq: int = 0x24, *, include_redacted: bool = False,
    ) -> list[ReplayMessage]:
        return [
            m
            for m in self._messages
            if 0x2 <= m.seq <= max_seq
            and m.direction == "R"
            and (include_redacted or not m.has_redaction)
        ]

    def _parse(self) -> None:
        text = self._path.read_text(encoding="utf-8", errors="strict")
        lines = text.splitlines()

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            if line.startswith(_SEPARATOR) and set(line.strip()) == {"="}:
                i += 1
                i = self._parse_block(lines, i)
            else:
                i += 1

        self._messages.sort(key=lambda m: m.seq)

    def _parse_block(self, lines: list[str], i: int) -> int:
        n = len(lines)
        seq: int | None = None
        type_id: int | None = None
        direction: str | None = None
        size: int | None = None

        while i < n:
            line = lines[i]
            stripped = line.strip()
            if line.startswith(_SEPARATOR) and set(stripped) == {"="}:
                break
            if stripped == "raw:":
                i += 1
                break
            m = _HEADER_RE.match(stripped)
            if m:
                seq = int(m.group(1), 16)
                i += 1
                continue
            m = _TYPE_RE.match(stripped)
            if m:
                type_id = int(m.group(1), 16)
                i += 1
                continue
            m = _DIR_RE.match(stripped)
            if m:
                direction = m.group(1)
                i += 1
                continue
            m = _SIZE_RE.match(stripped)
            if m:
                size = int(m.group(1))
                i += 1
                continue
            i += 1

        hex_rows: list[tuple[int, list[str]]] = []
        while i < n:
            line = lines[i]
            stripped = line.strip()
            if line.startswith(_SEPARATOR) and set(stripped) == {"="}:
                break
            row = _parse_hex_row(line)
            if row is not None:
                hex_rows.append(row)
            i += 1

        if seq is None or type_id is None or direction is None or size is None:
            return i

        body, spans = _decode_body(hex_rows)

        if len(body) != size:
            raise ValueError(
                f"seq=0x{seq:x} type=0x{type_id:x} dir={direction}: "
                f"body length {len(body)} != header size {size}"
            )

        if direction == "R":
            # seq 0x25 is the first message of its datagram and carries a
            # datagram-level preamble, so its body does not start with the
            # typed marker (see javelin/bundle.py).
            from . import varint as _varint

            marker_ok = False
            if len(body) >= 3 and body[:2] == b"\x00\x01":
                try:
                    marker_ok = _varint.decode(body, 2)[0] == type_id
                except _varint.VarintError:
                    marker_ok = False
            if seq != 0x25 and not marker_ok:
                got = body[:4].hex() if len(body) >= 4 else body.hex()
                self.validation_warnings.append(
                    f"seq=0x{seq:x} type=0x{type_id:x} dir=R: marker "
                    f"mismatch (expected 0001 + varint(0x{type_id:x}), "
                    f"got {got})"
                )

        msg = ReplayMessage(
            seq=seq,
            type_id=type_id,
            direction=direction,
            body=body,
            has_redaction=bool(spans),
            redacted_spans=spans,
        )
        self._messages.append(msg)
        self._by_seq[seq] = msg
        return i


if __name__ == "__main__":
    dump = (
        Path(__file__).resolve().parents[2]
        / "info"
        / "nw-login-safe-20260502-153840"
        / "messages-redacted.txt"
    )
    store = ReplayStore(dump)

    total = len(store.messages)
    by_dir: dict[str, int] = {}
    redacted_by_dir: dict[str, int] = {}
    clean_by_dir: dict[str, int] = {}
    redacted_total = 0

    for m in store.messages:
        by_dir[m.direction] = by_dir.get(m.direction, 0) + 1
        if m.has_redaction:
            redacted_total += 1
            redacted_by_dir[m.direction] = redacted_by_dir.get(m.direction, 0) + 1
        else:
            clean_by_dir[m.direction] = clean_by_dir.get(m.direction, 0) + 1

    print(f"total messages: {total}")
    for d in sorted(by_dir):
        print(
            f"  dir={d}: {by_dir[d]} "
            f"(redacted={redacted_by_dir.get(d, 0)}, "
            f"clean={clean_by_dir.get(d, 0)})"
        )
    print(f"redacted total: {redacted_total}")
    print(f"fully recoverable: {total - redacted_total}")

    replayable = store.replay_messages_after_v3()
    print(
        f"replay_messages_after_v3(max_seq=0x24): {len(replayable)} clean R-msgs"
    )
    for m in replayable:
        print(
            f"  seq=0x{m.seq:x} type=0x{m.type_id:x} size={len(m.body)}"
        )

    if store.validation_warnings:
        print(f"\nvalidation warnings ({len(store.validation_warnings)}):")
        for w in store.validation_warnings:
            print(f"  {w}")
    else:
        print("\nno validation warnings")
