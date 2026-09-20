"""V3 registration: request parser (round-trip) + response encoder.

Wire layout + evidence in research/docs/REP-PROTOCOL.md. Nothing is guessed:
unknown regions are preserved verbatim as bytes so the request body
round-trips byte-for-byte (a parser that cannot reproduce its input is
wrong — the tests enforce it).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

# Region offsets into the strict 832-byte body (REP-PROTOCOL.md).
PRELUDE_END = 0x21
TRAILER_OFF = 0x334
TRAILER = bytes.fromhex("00430280" + "00" * 8)
EXPECTED_BODY_LEN = 832

RESPONSE_TYPE_BYTE = 0x03
DEFAULT_SERVER_VERSION = "[RETAIL].Javelin.1.400.6031.6004151"
# Official Mixed-Nuts capture is `01 00 00 01`. On 1.400 that trailer
# plus a live RegistrationResponse still yields
# @mm_csdkerr_server_requires_anticheat 24ms after the socket
# (Game.log 2026-09-18 19:18:04) even with enable-anticheat stored 0.
# First byte / last byte are the only non-zero flags; clear them so the
# client does not treat this private world as an AC-required official
# server. Revert if the client then rejects the response entirely.
DEFAULT_TRAILER = bytes.fromhex("00000000")

_UUID_RE = re.compile(
    rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_PERSONA_RE = re.compile(rb"amzn1\.developerPersonaId\.[0-9a-f-]{36}")


@dataclass
class V3RegistrationRequest:
    """Decoded V3 RegistrationRequest body.

    Visible AZStd::string elements are u8-length-prefixed; every opaque
    region is kept verbatim so serialize() reproduces the input exactly.
    """

    prelude: bytes = b""
    build_version: str = ""  # "6031"
    unknown_400: str = ""  # "400"
    sdk_name: str = ""  # "Javelin"
    sdk_version: str = ""  # "600415" (+1 tail byte below)
    sdk_version_tail: int = 0
    build_flavor: str = ""  # "[RETAIL]"
    client_signature: str = ""  # "sig:<ticket-uuid>"
    client_endpoint: str = ""  # "127.0.0.1:<port>"
    session_uuid: str = ""
    persona_id: str = ""
    platform_app_tag: str = ""  # "STEAM_APP_ID.1063730"
    platform_user_id: str = ""  # SteamID64
    platform_name_blob: str = ""  # "steam|14" (length byte 0x08)
    gaps: list[bytes] = field(default_factory=list)
    unknown_worldid_region: bytes = b""
    auth_blob: bytes = b""
    trailer: bytes = TRAILER
    # Retry-format (tagged records) round-trip support:
    retry_prelude: bytes = b""
    retry_records: list[tuple[int, str]] = field(default_factory=list)
    retry_tail: bytes = b""


def _read_str(buf: bytes, off: int) -> tuple[str, int]:
    ln = buf[off]
    end = off + 1 + ln
    if end > len(buf):
        raise ValueError(f"string length {ln} at {off:#x} overruns buffer")
    return buf[off + 1 : end].decode("latin-1"), end


def parse_v3_request(body: bytes) -> V3RegistrationRequest:
    """Strict 832-byte walk. Raises ValueError on any layout mismatch."""
    if len(body) != EXPECTED_BODY_LEN:
        raise ValueError(f"expected {EXPECTED_BODY_LEN}B body, got {len(body)}")
    if not body.endswith(TRAILER):
        raise ValueError("missing standard 12B trailer")

    msg = V3RegistrationRequest()
    msg.prelude = body[:PRELUDE_END]
    schedule = [
        (0x021, "build_version"),
        (0x02A, "unknown_400"),
        (0x038, "sdk_name"),
        (0x044, "sdk_version_raw"),
        (0x050, "build_flavor"),
        (0x05A, "client_signature"),
        (0x083, "client_endpoint"),
        (0x0A8, "session_uuid"),
        (0x0CD, "persona_id"),
        (0x110, "platform_app_tag"),
        (0x144, "platform_user_id"),
        (0x157, "platform_name_blob"),
    ]
    cursor = PRELUDE_END
    for slot_idx, (off, attr) in enumerate(schedule):
        if slot_idx > 0:
            msg.gaps.append(body[cursor:off])
        text, cursor = _read_str(body, off)
        if attr == "sdk_version_raw":
            msg.sdk_version = text[:-1]
            msg.sdk_version_tail = ord(text[-1])
        else:
            setattr(msg, attr, text)

    # worldId-prefix region sits between client_endpoint and session_uuid.
    msg.unknown_worldid_region = body[0x93:0xA8]
    session_gap_idx = 6
    if session_gap_idx < len(msg.gaps) and msg.gaps[session_gap_idx] == body[0x93:0xA8]:
        msg.gaps[session_gap_idx] = b""

    msg.auth_blob = body[cursor:TRAILER_OFF]
    msg.trailer = body[TRAILER_OFF:]
    return msg


def parse_v3_request_retry(body: bytes) -> V3RegistrationRequest | None:
    """Retry format: 6 tagged records (u32 BE type_id + u8 len + string)
    after a 32-byte prelude; identity fields recovered from the tail."""
    PRELUDE_LEN = 32
    if len(body) < PRELUDE_LEN + 5 * 6:
        return None
    msg = V3RegistrationRequest()
    msg.retry_prelude = body[:PRELUDE_LEN]
    off = PRELUDE_LEN
    records: list[tuple[int, str]] = []
    for _ in range(6):
        if off + 5 > len(body):
            return None
        (type_id,) = struct.unpack_from(">I", body, off)
        if type_id > 0xFFFF:
            return None
        ln = body[off + 4]
        end = off + 5 + ln
        if end > len(body):
            return None
        records.append((type_id, body[off + 5 : end].decode("latin-1", "replace")))
        off = end
    if {tid for tid, _ in records} != {0, 1, 2, 3, 4, 5}:
        return None
    msg.retry_records = records
    msg.retry_tail = body[off:]
    for tid, text in records:
        if tid == 4:
            msg.build_version = text
        elif tid == 3:
            msg.unknown_400 = text
        elif tid == 1:
            msg.sdk_name = text
        elif tid == 0:
            msg.build_flavor = text
    lenient = parse_v3_request_lenient(msg.retry_tail)
    if lenient is not None:
        msg.session_uuid = lenient.session_uuid or msg.session_uuid
        msg.persona_id = lenient.persona_id or msg.persona_id
    return msg


def parse_v3_request_lenient(body: bytes) -> V3RegistrationRequest | None:
    """Best-effort identity extraction (session uuid + persona id)."""
    session_uuid = ""
    for m in _UUID_RE.finditer(body):
        pre = body[max(0, m.start() - 8) : m.start()]
        if b"sig:" in pre or b"naId." in pre:
            continue
        if m.start() > 0 and body[m.start() - 1] == 0x24:
            candidate = m.group(0).decode("ascii")
            # Seeded world/character ids are also 0x24-prefixed UUIDs and
            # sit earlier in the V3 blob than the ticket uuid. Skip them
            # or we echo the worldId as the session token.
            if candidate.startswith("00000000-"):
                continue
            session_uuid = candidate
            break
    persona = ""
    if m := _PERSONA_RE.search(body):
        persona = m.group(0).decode("ascii")
    if not session_uuid and not persona:
        return None
    out = V3RegistrationRequest()
    out.session_uuid = session_uuid
    out.persona_id = persona
    return out


def parse_v3_request_or_lenient(body: bytes) -> V3RegistrationRequest:
    """Strict -> retry -> lenient. Raises ValueError only if all three fail."""
    try:
        return parse_v3_request(body)
    except ValueError as strict_err:
        retry = parse_v3_request_retry(body)
        if retry is not None:
            return retry
        lenient = parse_v3_request_lenient(body)
        if lenient is not None:
            return lenient
        raise ValueError(f"all V3 parsers failed; strict error: {strict_err}") from None


def serialize_v3_request(msg: V3RegistrationRequest) -> bytes:
    """Re-emit the strict body (round-trips parse output exactly)."""
    if msg.retry_records:
        out = bytearray(msg.retry_prelude)
        for type_id, text in msg.retry_records:
            out.extend(struct.pack(">I", type_id))
            encoded = text.encode("latin-1")
            if len(encoded) > 0xFF:
                raise ValueError("retry record value too long for u8 length")
            out.append(len(encoded))
            out.extend(encoded)
        out.extend(msg.retry_tail)
        return bytes(out)

    out = bytearray(msg.prelude)
    strings = [
        ("build_version", msg.build_version),
        ("unknown_400", msg.unknown_400),
        ("sdk_name", msg.sdk_name),
        ("sdk_version_raw", msg.sdk_version + chr(msg.sdk_version_tail)),
        ("build_flavor", msg.build_flavor),
        ("client_signature", msg.client_signature),
        ("client_endpoint", msg.client_endpoint),
        ("session_uuid", msg.session_uuid),
        ("persona_id", msg.persona_id),
        ("platform_app_tag", msg.platform_app_tag),
        ("platform_user_id", msg.platform_user_id),
        ("platform_name_blob", msg.platform_name_blob),
    ]
    for i, (attr, text) in enumerate(strings):
        if i > 0:
            if attr == "session_uuid":
                out.extend(msg.unknown_worldid_region)
            else:
                gap_idx = i - 1
                out.extend(msg.gaps[gap_idx] if gap_idx < len(msg.gaps) else b"")
        encoded = text.encode("latin-1")
        out.append(len(encoded))
        out.extend(encoded)
    out.extend(msg.auth_blob)
    out.extend(msg.trailer)
    return bytes(out)


@dataclass
class V3RegistrationResponse:
    """Server -> client RegistrationResponseMsg (88 bytes by default).

    Layout captured from a real successful login; NO type-GUID prefix.
    Accepting this flips the client's rep.ready 0 -> 1.
    """

    session_token: bytes = b"AZOTH-stub-session-token-32bytes"
    server_version: str = DEFAULT_SERVER_VERSION
    error_code: int = 0
    mystery8: bytes = (0x0B888D68).to_bytes(4, "big") + (0x706C415B).to_bytes(4, "big")
    trailer: bytes = DEFAULT_TRAILER

    def __post_init__(self) -> None:
        if len(self.session_token) != 32:
            raise ValueError(f"session_token must be 32 bytes, got {len(self.session_token)}")
        if len(self.mystery8) != 8:
            raise ValueError(f"mystery8 must be 8 bytes, got {len(self.mystery8)}")
        if len(self.trailer) != 4:
            raise ValueError(f"trailer must be 4 bytes, got {len(self.trailer)}")
        if len(self.server_version.encode()) > 0xFF:
            raise ValueError("server_version too long for u8 prefix")

    def encode(self) -> bytes:
        out = bytearray()
        out += b"\x00\x01"
        out.append(RESPONSE_TYPE_BYTE)
        out += int(self.error_code).to_bytes(4, "big", signed=True)
        out += self.mystery8
        out.append(0x20)
        out += self.session_token
        ver = self.server_version.encode()
        out.append(len(ver))
        out += ver
        out += self.trailer
        return bytes(out)
