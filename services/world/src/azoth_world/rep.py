"""DTLS-terminating Javelin REP server (UDP).

Frozen spawn contract (services/docs/WORLD.md):
  UDP bind -> DTLS handshake -> Carrier CONNECT_REQUEST/ACK
  -> V3 registration (request parsed, response 88B) -> rep.ready 0->1
  -> post-V3 ladder (SelfIdent / LevelInfoChanged / NewProxy — TODO).

Trust: the client pins an embedded `CN=New World` cert, so the handshake
only completes after the runtime verify-bypass patch
(scripts/frida-trust-patch.py + research/atlas/levers.md "DTLS verify
bypass"). No cert authority we control can ever validate.

Every datagram is logged (like the gateway's traffic capture): parsed
envelope/records + decoded V3 identity, to stdout and
services/world/rep_traffic.jsonl (gitignored) so live sessions become
ground truth for the post-V3 work.

DTLS implementation notes:
- pyOpenSSL is this service's ONE deliberate non-stdlib dependency
  (stdlib ssl has no DTLS). It ships a prebuilt OpenSSL — nothing compiles.
- pyOpenSSL has no socket API: each peer gets an SSL.Connection driven
  through its internal memory-BIO pair (bio_write in, bio_read out).
- No retransmit timers on loopback (pyOpenSSL does not expose
  DTLSv1_handle_timeout); localhost does not lose datagrams.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import time
from datetime import UTC, datetime
from pathlib import Path

from .javelin import (
    MessageRecord,
    SystemMessageId,
    V3RegistrationResponse,
    marshal_datagram,
    parse_datagram,
    parse_envelope,
    parse_v3_request_or_lenient,
)

try:
    from OpenSSL import SSL, crypto

    HAVE_PYOPENSSL = True
except ImportError:  # pragma: no cover — only without the dependency
    HAVE_PYOPENSSL = False

# Synthesized SelfIdent+LIC with the 21-byte body crashed live 1.400
# (AV 0x146b6f1be, 2026-09-18). The captured official replay now drives the
# post-V3 ladder; keep the synthetic SelfIdent off until the replay is proven.
POST_V3_ENABLED = False

REPO_ROOT = Path(__file__).resolve().parents[4]  # .../Azoth (src/azoth_world/ -> up 4)
LOG_PATH = REPO_ROOT / "services" / "world" / "rep_traffic.jsonl"
CERT_DIR = Path(__file__).resolve().parents[2] / "certs"  # services/world/certs

# Captured official login replay (first-light, build 1.365). Replaying the
# full R-stream (seq 0x2..0xb0, including the ~46 KB StateBundle init burst)
# is what makes the local player actor resolve as the client's master actor
# (first-light info/.../handoff-notes.md). first-light only replayed up to
# 0x24, which is why their client stalled at state 10.
REPLAY_PATH = REPO_ROOT / "services" / "world" / "replay" / "messages-redacted.txt"
REPLAY_ENABLED = True
REPLAY_MAX_SEQ = 0xB0
REPLAY_INTERVAL_S = 0.03
REPLAY_CHUNK_SIZE = 1100
# 2026-09-20: the 12.7KB datagram (46KB StateBundle at 1100/chunk → 12
# chunks but ~12.7KB after marshaling) was NEVER acked by the client —
# dropped wholesale while loading, 4229 resends didn't help. Bundle the
# chunks into ~4KB datagrams instead of one giant datagram: a lost
# datagram then costs 3 chunks, not 12.
REPLAY_DGRAM_TARGET = 4000
REPLAY_SINGLE_LIMIT = 14000  # DTLS plaintext cap ~16 KB minus overhead
REPLAY_RESEND_LIMIT = 6      # max resends per reliable datagram (2026-09-20:
# seq 12 (12.7KB StateBundle) was resent 4229x and never acked — the client
# drops oversized datagrams during load and re-bombing it made everything
# worse. After the cap, split-retransmit or drop: the 30s InGame timeout
# clears the session anyway.)

_REPLAY = None


def replay_store():
    global _REPLAY
    if _REPLAY is None:
        from .javelin.replay_store import ReplayStore

        _REPLAY = ReplayStore(REPLAY_PATH)
    return _REPLAY


def log_event(event: dict) -> None:
    event = {"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **event}
    print(f"[rep] {json.dumps(event, ensure_ascii=False)}")
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def describe_datagram(data: bytes) -> dict:
    """Best-effort decode: envelope + records + V3 identity if present."""
    from .javelin.lz4 import decompress_lz4_block

    event: dict = {"size": len(data), "raw": data.hex()}
    try:
        env, body = parse_envelope(data)
        event["envelope"] = {
            "type": hex(env.type_byte),
            "proto": env.proto,
            "seq": env.sequence,
            "compressed": env.is_compressed,
        }
        if env.is_compressed:
            try:
                body = decompress_lz4_block(body)
                event["decompressed_size"] = len(body)
            except ValueError as exc:
                return {**event, "lz4_error": str(exc)[:120]}
        result = parse_datagram(body)
        event["records"] = [
            {
                "channel": r.channel,
                "flags": hex(r.flags),
                "size": r.size,
                "system": int(r.system_msg_id) if r.system_msg_id is not None else None,
            }
            for r in result.messages
        ]
        if result.error:
            event["parse_error"] = result.error
        for r in result.messages:
            if r.channel == 0 and r.size > 64:  # V3 data-channel record
                try:
                    req = parse_v3_request_or_lenient(r.payload)
                    event["v3"] = {
                        "session_uuid": req.session_uuid,
                        "persona_id": req.persona_id,
                        "endpoint": req.client_endpoint,
                        "build": req.build_flavor,
                    }
                except ValueError as exc:
                    event["v3_error"] = str(exc)[:120]
        return event
    except ValueError as exc:
        return {"size": len(data), "raw": data[:64].hex(), "error": str(exc)}


def v3_response_datagram(seq: int, *, session_token: bytes | None = None) -> bytes:
    """RegistrationResponseMsg wrapped in a Carrier data-channel record.

    Wire form: flags 0x21 (RELIABLE|DATA_CHANNEL), channel 0, then
    [VLQ32 body-size][88B typed envelope]. The V3 registration parser
    REQUIRES the VLQ prefix (2026-09-20 19:35: the un-prefixed form died
    with @mm_csdkerr_registration_unmarshal_error before InGame). The
    ClientSDK replica reader logs `Failed to unmarshal num_bytes=90` on
    this record — cosmetic: the game proceeded to InGame anyway. Both
    consumers share ch0 0x21; separating them needs the official channel
    layout, which the redacted capture does not preserve."""
    if session_token and len(session_token) == 32:
        resp = V3RegistrationResponse(session_token=session_token)
    else:
        resp = V3RegistrationResponse()
    body = resp.encode()
    rec = MessageRecord(
        channel=0,
        payload=bytes([len(body)]) + body,  # VLQ32 size (88 < 128 = 1 byte)
        sequence=0,
        reliable_sequence=0,
        reliable=True,
        connecting=False,
        flags_override=0x21,  # RELIABLE | DATA_CHANNEL
    )
    return b"\x80\x01" + seq.to_bytes(2, "big") + marshal_datagram([rec])


def _az_string(s: str) -> bytes:
    """AzCore wire form for AZStd::string: [u32 length_LE][raw bytes]."""
    raw = s.encode("utf-8")
    return len(raw).to_bytes(4, "little") + raw


def self_ident_body() -> bytes:
    """PlayerManagerSelfIdentificationMsg body (wire type 0x5d1).

    Per first-light self_ident.py: the state-10 -> 11 advance trigger.
    Handler FUN_146454c00 reads a 56-byte in-memory struct; the AzCore
    wire form drops the in-memory alignment padding:
    [u32 field0][u32 vec_count][vec u32s][u8 debug][u64 field2c][u32 field34].
    """
    return (
        (0).to_bytes(4, "little")       # field_0
        + (0).to_bytes(4, "little")     # vector count = 0
        + b"\x00"                        # debug_flag = 0
        + (0).to_bytes(8, "little")     # field_2c
        + (0).to_bytes(4, "little")     # field_34
    )


def level_info_changed_body(
    level_name: str = "NewWorld_VitaeEterna",
    instance_id: int = 1,
) -> bytes:
    """LevelInfoChangedMsg body. Per first-light level_info_changed.py.

    Advances the client past state 12 (WaitingForSpawnPoint).
    Wire: [azstr level][azstr other][u32x4 quad][u64][u32 count][4 flags][u64 id]."""
    return (
        _az_string(level_name)
        + _az_string(level_name)             # other_name = same
        + (0).to_bytes(4, "little") * 4      # quad = zeros
        + (0).to_bytes(8, "little")          # field_60
        + (0).to_bytes(4, "little")          # extended count = 0
        + bytes((0, 1, 1, 0))                # flags: level_is_loading=1, in_game=1
        + instance_id.to_bytes(8, "little")  # client_context_instance_id
    )


def _typed_record(channel: int, type_header: bytes, body: bytes, seq: int, rel: int) -> MessageRecord:
    """A typed-envelope data-channel record: [VLQ32 size][type header][body]."""
    inner = type_header + body
    vlq = bytes([len(inner)]) if len(inner) < 128 else (
        bytes([(len(inner) & 0x7F) | 0x80, len(inner) >> 7])
    )
    payload = vlq + inner
    return MessageRecord(
        channel=channel,
        payload=payload,
        sequence=seq,
        reliable_sequence=rel,
        reliable=True,
        connecting=False,
        flags_override=0x21,  # RELIABLE | DATA_CHANNEL
    )


def post_v3_datagram(seq: int) -> bytes:
    """Post-V3 flight: the 4-byte SelfIdentification trigger (phase 9b,
    state 10->11). LevelInfoChanged is sent separately once the actor
    exists (sending both in one burst crashed the client)."""
    self_ident = _typed_record(
        0, bytes((0x00, 0x01, 0x91, 0x17)), self_ident_body(), seq=1, rel=1
    )
    return b"\x80\x01" + seq.to_bytes(2, "big") + marshal_datagram([self_ident])


def system_record(msg_id: int, body: bytes, *, connecting: bool = False) -> MessageRecord:
    """System-channel (3) record: msgId is the LAST payload byte."""
    return MessageRecord(
        channel=3,
        payload=body + bytes([msg_id]),
        sequence=1,
        reliable_sequence=1,
        reliable=False,
        connecting=connecting,
    )


def carrier_state_datagram(seq: int, *, welcome: bytes, ack_first: int, ack_last: int) -> bytes:
    """The server's connection-acceptance flight, verbatim per the GridMate
    reference (aws/lumberyard Carrier.cpp, CarrierImpl::ProcessSystemMessages
    -> SM_CONNECT_REQUEST / CST_CONNECTING):

        conn->m_state = CST_CONNECTED;
        SendSyncTime();                                          // 1. CLOCK_SYNC
        SendSystemMessage(SM_CONNECT_ACK, wb, conn, SEND_RELIABLE);  // 2. ACK

    All records on the system channel (3) with our OWN message counters
    (init 0xFFFF, pre-increment => first seq = 0, first reliable relSeq = 0):

    - CLOCK_SYNC (sys4): UNRELIABLE, flags 0x20, seq 0, relSeq 0xFFFF
      (unreliable records carry the last reliable seq; delivering one
      requires relSeq == last received reliable seq, which starts 0xFFFF).
      Payload: u32 BE server clock (ms).
    - CONNECT_ACK (sys2): RELIABLE, flags 0x21 (RELIABLE|DATA_CHANNEL), NO
      MF_CONNECTING (the server is already CONNECTED when it sends), seq 1,
      relSeq 0. Payload: the welcome data = the client's version u32 echoed
      VERBATIM (DefaultHandshake semantics: OnInitiate writes the version
      into the ACK buffer; OnReceiveRequest echoes it back). The client runs
      OnReceiveAck on this payload — a datagram-ACK-shaped payload
      (`40 0002 0002`) was tried 2026-09-17 and did NOT advance the client,
      while the version echo at least made it stop resending and ACK our
      datagram (2026-09-16 20:23 session).
    - CT_ACKS (sys6): UNRELIABLE piggyback, flags 0x18 (both SEQ fields
      omitted — inherited from the previous record on the channel), payload
      `40 <last BE> <first BE> 06` (AHF_CONTINUOUS_ACK over the inbound
      envelope-seq range we have received). This is the fix that broke the
      V3 retry storm in first-light PR #5: without it the client's Carrier
      never considers its datagrams delivered and never sends V3.

    Envelope seq ECHO (first-light "Mixed Nuts" finding 2026-05-04): the
    reply datagram carries the CLIENT's inbound envelope seq, not an
    independent server counter. Without the echo the client keeps
    retransmitting as if our reply never arrived.

    A RELIABLE record with a mirrored/wrong relSeq (e.g. the client's own
    0xFFFF) blocks the client's reliable-delivery queue forever — the
    earlier mirror-the-request ACK kept the client in CONNECTING even
    though it stopped resending (live capture 2026-09-16 20:23)."""
    clock = int(time.time() * 1000) & 0xFFFFFFFF
    clock_sync = MessageRecord(
        channel=3,
        payload=clock.to_bytes(4, "big") + bytes([SystemMessageId.SM_CLOCK_SYNC]),
        sequence=0,
        reliable_sequence=0xFFFF,
        reliable=False,
        connecting=False,
        flags_override=0x20,  # DATA_CHANNEL only (unreliable, not connecting)
    )
    ack = MessageRecord(
        channel=3,
        payload=welcome + bytes([SystemMessageId.SM_CONNECT_ACK]),
        sequence=1,
        reliable_sequence=0,
        reliable=True,
        connecting=False,
        flags_override=0x21,  # RELIABLE | DATA_CHANNEL
    )
    piggyback = MessageRecord(
        channel=3,
        payload=(
            bytes([0x40])
            + ack_last.to_bytes(2, "big")
            + ack_first.to_bytes(2, "big")
            + bytes([SystemMessageId.SM_CT_ACKS])
        ),
        sequence=0,  # inherited (flags 0x18 omits both SEQ fields)
        reliable_sequence=0,  # inherited
        reliable=False,
        connecting=False,
        flags_override=0x18,  # SEQUENTIAL_ID | SEQUENTIAL_REL_ID
    )
    return b"\x80\x01" + seq.to_bytes(2, "big") + marshal_datagram(
        [clock_sync, ack, piggyback]
    )


def ct_acks_datagram(seq: int, *, ack_first: int, ack_last: int) -> bytes:
    """Standalone CT_ACKS (sys6) so the client's reliable V3 is marked
    delivered. Without this, after the first RegistrationResponse the
    client retransmits ch0 1115B for ~10s then
    `@mm_csdkerr_disconnect (4)` (Game.log 2026-09-18 20:15:08→18)."""
    rec = MessageRecord(
        channel=3,
        payload=(
            bytes([0x40])
            + ack_last.to_bytes(2, "big")
            + ack_first.to_bytes(2, "big")
            + bytes([SystemMessageId.SM_CT_ACKS])
        ),
        sequence=0,
        reliable_sequence=0xFFFF,
        reliable=False,
        connecting=False,
        flags_override=0x20,
    )
    return b"\x80\x01" + seq.to_bytes(2, "big") + marshal_datagram([rec])


def clock_sync_datagram(seq: int) -> bytes:
    """Unreliable SM_CLOCK_SYNC keepalive (GridMate SendSyncTime)."""
    clock = int(time.time() * 1000) & 0xFFFFFFFF
    rec = MessageRecord(
        channel=3,
        payload=clock.to_bytes(4, "big") + bytes([SystemMessageId.SM_CLOCK_SYNC]),
        sequence=0,
        reliable_sequence=0xFFFF,
        reliable=False,
        connecting=False,
        flags_override=0x20,
    )
    return b"\x80\x01" + seq.to_bytes(2, "big") + marshal_datagram([rec])


def greetings_datagram(env_seq: int) -> bytes:
    """Cmd_Greetings (stock GridMate §7.3) wrapped in a Carrier record.

    [CmdId=1][PeerId u32 BE][isHost bool][RepIdSeed u32 BE]. PeerId is
    Crc32-derived (ReplicaDefs.h:39) — 'AZOT' as a stable placeholder."""
    peer_id = 0x415A4F54  # 'AZOT'
    greetings = (
        bytes([1])  # Cmd_Greetings
        + peer_id.to_bytes(4, "big")
        + bytes([1])  # peerIsHost = true (we are the server)
        + (1 << 25).to_bytes(4, "big")  # RepIdSeed
    )
    rec = MessageRecord(
        channel=0,
        payload=greetings,
        sequence=1,
        reliable_sequence=1,
        reliable=True,
        connecting=False,
        flags_override=0x21,  # RELIABLE | DATA_CHANNEL
    )
    return (
        b"\x80\x01"
        + env_seq.to_bytes(2, "big")
        + marshal_datagram([rec])
    )


def handle_app_data(
    app: bytes,
    client_env_seq: int,
    *,
    handshake_done: bool,
    inbound_first: int,
    v3_done: bool = False,
    v3_last_reply: float = 0.0,
) -> list[bytes]:
    """Server logic for one decrypted datagram -> 0..n reply datagrams.

    v3_last_reply: monotonic timestamp of the last V3 response for this
    peer — throttles the retry answer to 1 per 5s (the caller passes
    PeerSession.v3_last_time).

    Handshake per the GridMate reference: the FIRST sys1 record flips the
    peer to CONNECTED and triggers the CLOCK_SYNC+ACK flight. The client's
    Carrier resends the CONNECT_REQUEST until OUR datagram is acked
    (DefaultTrafficControl lost-packet timeout = 1000ms), so every re-sent
    request re-triggers the flight until the client stops asking (the
    caller flips `handshake_done` only when the requests actually stop —
    see PeerSession.on_app_data). The reply datagram ECHOES the client's
    inbound envelope seq (first-light "Mixed Nuts" finding) and carries a
    CT_ACKS piggyback over the inbound range (first-light PR #5 fix).
    The V3 registration on channel 0 gets the 88B RegistrationResponseMsg.

    Envelope type 0x81 is LZ4-compressed (live client, 2026-09-17 21:04:
    the first V3 is 269B compressed / 1124B decompressed). Parsing the
    compressed body as records produced a stub session token and the
    client disconnected."""
    from .javelin.lz4 import decompress_lz4_block

    try:
        env, body = parse_envelope(app)
    except ValueError:
        return []
    if env.is_compressed:
        try:
            body = decompress_lz4_block(body)
        except ValueError:
            return []
    result = parse_datagram(body)
    requests = [
        rec
        for rec in result.messages
        if rec.is_system
        and rec.system_msg_id == SystemMessageId.SM_CONNECT_REQUEST
        and rec.payload
    ]
    replies: list[bytes] = []
    if requests and not handshake_done:
        first = requests[0]
        # Welcome data = the version u32 the client sent (DefaultHandshake
        # semantics: OnInitiate writes the version into the ACK buffer).
        welcome = first.payload[:-1][:4] if len(first.payload) >= 5 else b"\x00\x00\x00\x05"
        replies.append(
            carrier_state_datagram(
                client_env_seq,
                welcome=welcome,
                ack_first=inbound_first,
                ack_last=client_env_seq,
            )
        )
    # Live 2026-09-18 19:38: client accepted the FIRST RegistrationResponse
    # then streamed ch0 blobs; treating every one as V3 re-emitted ~700
    # responses → answer-once was introduced.
    #
    # UPDATE 2026-09-19 19:26 (InGame era): the ch0 1115B chunked blobs
    # DECODED as V3 retry bodies (tagged format, "Javelin" sdk name in the
    # payload). After every InGame timeout the client re-registers; we
    # silently dropped retries (v3_done=True) so it restarted the whole
    # login cycle — the UI "queue 0<->1" loop. Answer every V3-shaped
    # record, throttled to 1 per 5s: handshake retries (1/s for 15s) get
    # deduplicated, post-InGame re-registrations (90s apart) get answered.
    v3_records = [rec for rec in result.messages if rec.channel == 0 and rec.size > 64]
    if v3_records and (not v3_done or time.monotonic() - v3_last_reply > 5.0):
        # V3 registration: extract session_uuid and echo it as the session
        # token (first-light doc: "the 32-char hex form of the client's
        # session_uuid echoed back" — the client stores it via vtable+0x110).
        session_token = None
        for rec in v3_records:
            try:
                req = parse_v3_request_or_lenient(rec.payload)
                if req.session_uuid:
                    session_token = req.session_uuid.replace("-", "").encode("ascii")
            except ValueError:
                pass
            break
        replies.append(v3_response_datagram(client_env_seq + 1, session_token=session_token))
        v3_replied = True
        # Post-V3 flight (SelfIdent + LevelInfoChanged) is NOT sent here.
        # The client needs time to process the V3 response first. Sending
        # post-V3 in the same burst crashes the client (2026-09-17 20:43).
        # See PeerSession.maybe_send_post_v3.
    # Replica-layer handshake (2026-09-20): stock GridMate §7.3 Greetings
    # does NOT apply — Javelin replica messages ride the typed stream, and
    # a raw Greetings produced `Failed to unmarshal message` (18:58).
    # Kept as a lever only if explicitly requested; default OFF.
    if not v3_done and os.environ.get("AZOTH_SEND_GREETINGS"):
        replies.append(greetings_datagram(client_env_seq + 1))
    needs_ack = handshake_done and not requests and any(
        (not rec.is_system)
        or rec.system_msg_id
        not in (SystemMessageId.SM_CT_ACKS, SystemMessageId.SM_CLOCK_SYNC)
        for rec in result.messages
    )
    if needs_ack:
        # ACK data envelopes so reliable V3 retries stop. Do not ACK
        # the client's own CT_ACKS/CLOCK_SYNC or we loop (seq 500 in
        # 40s, live 2026-09-18 20:20). Empty replies after v3_done
        # used to let ClientSDK hit disconnect (4) at 10s.
        replies.append(
            ct_acks_datagram(
                client_env_seq,
                ack_first=inbound_first,
                ack_last=client_env_seq,
            )
        )
    return replies

def make_self_signed_cert(cert_dir: Path = CERT_DIR) -> tuple[Path, Path]:
    """Generate certs/rep.crt + rep.key. CN=New World — the client validates
    NOTHING after the verify patch, so the CN is cosmetic (nice in logs)."""
    cert_dir.mkdir(parents=True, exist_ok=True)
    crt, key = cert_dir / "rep.crt", cert_dir / "rep.key"
    if crt.exists() and key.exists():
        return crt, key
    pkey = crypto.PKey()
    pkey.generate_key(crypto.TYPE_RSA, 2048)
    cert = crypto.X509()
    cert.get_subject().CN = "New World"
    cert.set_serial_number(int(time.time()))
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(10 * 365 * 24 * 3600)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(pkey)
    cert.sign(pkey, "sha256")
    key.write_bytes(crypto.dump_privatekey(crypto.FILETYPE_PEM, pkey))
    crt.write_bytes(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    log_event({"event": "cert-generated", "path": str(crt)})
    return crt, key


class PeerSession:
    """Per-peer DTLS connection driven through pyOpenSSL memory BIOs."""

    def __init__(self, ctx, peer: tuple[str, int]) -> None:
        self.conn = SSL.Connection(ctx)
        self.conn.set_accept_state()  # server side (vs set_connect_state)
        self.peer = peer
        self.gone = False  # SM_DISCONNECT seen; do not send more DTLS
        self.handshaken = False
        self.carrier_connected = False  # our acceptance flight has been sent
        self.inbound_first: int | None = None  # first inbound envelope seq
        self.v3_responded = False  # V3 response has been sent at least once
        self.v3_first_time = 0.0  # monotonic timestamp of first V3 response
        self.v3_last_time = 0.0  # monotonic timestamp of the LAST V3 response
        self.next_out_seq = 1  # envelope seq for unsolicited server datagrams
        self.post_v3_sent = False  # post-V3 flight sent
        self.last_keepalive = 0.0
        # Captured-official-login replay state (see REPLAY_* above).
        self.replay_queue: list = []
        self.replay_next_at = 0.0
        self.out_msg_seq = 0
        self.out_rel_seq = 0
        # Reliable retransmission (2026-09-19 InGame-era fix): the client
        # drops ~40% of the replay burst while loading (decoded CT_ACKS
        # bitmaps) and GridMate reliable delivery requires the SENDER to
        # resend lost datagrams. Track them until acked.
        self.sent_reliable: dict[int, tuple[float, bytes]] = {}
        self.resend_tries: dict[int, int] = {}
        self.acked_seqs: set[int] = set()
        self.greetings_after_replay = False

    def feed(self, server, data: bytes) -> None:
        """Feed one datagram in; send everything OpenSSL produced."""
        try:
            self.conn.bio_write(data)
            if not self.handshaken:
                try:
                    self.conn.do_handshake()
                    self.handshaken = True
                    log_event({"event": "dtls-established", "peer": f"{self.peer[0]}:{self.peer[1]}"})
                except SSL.WantReadError:
                    pass  # flight sent below; keep the session for the next datagram
                except SSL.Error as exc:
                    log_event({"event": "dtls-handshake-error", "peer": f"{self.peer[0]}:{self.peer[1]}", "error": str(exc)[:200]})
                    server.drop(self.peer)
                    return
            if self.handshaken:
                try:
                    while app := self.conn.recv(65536):
                        self.on_app_data(server, app)
                except SSL.WantReadError:
                    pass
        except SSL.Error as exc:
            log_event({"event": "dtls-error", "peer": f"{self.peer[0]}:{self.peer[1]}", "error": str(exc)[:200]})
            server.drop(self.peer)
        finally:
            self.flush(server)

    def on_app_data(self, server, app: bytes) -> None:
        try:
            inbound_env, inbound_body = parse_envelope(app)
        except ValueError:
            return
        event = describe_datagram(app)
        event.update(event="app-data", peer=f"{self.peer[0]}:{self.peer[1]}")
        # Full plaintext hex (no truncation): the V3 request (~832B) and
        # 0x81 LZ4 bodies (~269B) do not fit in 96 bytes; truncated logs
        # made them undecodable (2026-09-17).
        event["raw_full"] = app.hex()
        log_event(event)
        if self.inbound_first is None:
            self.inbound_first = inbound_env.sequence
        # System handshake (CONNECT_REQUEST -> CLOCK_SYNC+ACK+CT_ACKS) and
        # V3 registration. Replies are logged too: what WE send is half of
        # the ground truth.
        # The client's Carrier resends the CONNECT_REQUEST until OUR
        # datagram is acked (DefaultTrafficControl: lost-packet timeout
        # 1000ms). Every re-sent request re-triggers the acceptance flight
        # until the client stops asking (then carrier_connected flips).
        # The reply ECHOES the client's inbound envelope seq (first-light
        # "Mixed Nuts" finding) instead of using an independent counter.
        inbound_recs = parse_datagram(inbound_body).messages
        self._process_acks(inbound_recs)
        if any(
            rec.is_system and rec.system_msg_id == SystemMessageId.SM_DISCONNECT
            for rec in inbound_recs
        ):
            # Client already left. A later conn.send() of post-V3 on this
            # DTLS session blocked the whole UDP loop (2026-09-18 17:03:23
            # last log; 17:08 Play never reached dtls-established).
            self.gone = True
            server.drop(self.peer)
            return
        had_request = any(
            rec.is_system and rec.system_msg_id == SystemMessageId.SM_CONNECT_REQUEST
            for rec in inbound_recs
        )
        self.next_out_seq = max(self.next_out_seq, inbound_env.sequence + 1)
        for reply in handle_app_data(
            app,
            inbound_env.sequence,
            handshake_done=self.carrier_connected,
            inbound_first=self.inbound_first,
            v3_done=self.v3_responded,
            v3_last_reply=self.v3_last_time,
        ):
            log_event(
                {
                    "event": "reply",
                    "size": len(reply),
                    "raw": reply[:96].hex(),
                    "peer": f"{self.peer[0]}:{self.peer[1]}",
                }
            )
            if len(reply) > 100:
                server.v3_seen(self.peer, event)
                if not self.v3_responded:
                    self.v3_responded = True
                    self.v3_first_time = time.monotonic()
                    self._arm_replay()
                self.v3_last_time = time.monotonic()
            elif had_request and not self.carrier_connected:
                self.carrier_connected = True  # the acceptance flight went out
            self.send(server, reply)
        self.maybe_keepalive(server)
        self.maybe_send_post_v3(server)
        self.maybe_inject(server)
        self.maybe_pump_replay(server)
        self.maybe_resend(server)

    def _arm_replay(self) -> None:
        if not REPLAY_ENABLED:
            return
        try:
            store = replay_store()
        except Exception as exc:  # noqa: BLE001
            log_event({"event": "replay-load-error", "error": str(exc)[:200]})
            return
        self.replay_queue = store.replay_messages_after_v3(
            REPLAY_MAX_SEQ, include_redacted=True
        )
        self.out_msg_seq = 1
        self.out_rel_seq = 1
        self.replay_next_at = time.monotonic()
        log_event({"event": "replay-armed", "count": len(self.replay_queue)})

    def maybe_pump_replay(self, server) -> None:
        """Send the next captured R-message (official login replay)."""
        if not self.replay_queue or self.gone:
            return
        now = time.monotonic()
        if now < self.replay_next_at:
            return
        msg = self.replay_queue.pop(0)
        self._send_replay_message(server, msg)
        if not self.replay_queue and not self.greetings_after_replay:
            # Replay fully streamed. 2026-09-20 19:11 lesson: re-sending
            # r2/r4/r5 here DUPLICATES messages the client already has and
            # collides out_msg_seq — the client died with
            # @mm_csdkerr_registration_unmarshal_error + ValidationError.
            # The raw Cmd_Greetings experiment also failed (Failed to
            # unmarshal, num_bytes=1/90). Post-replay the server must send
            # NEW typed messages (the official capture stops at r176; the
            # missing ones are the server's replica updates W-direction
            # counterparts). Nothing known to send yet — leave the stream
            # quiet and rely on keepalives until that is RE'd.
            self.greetings_after_replay = True
            log_event({"event": "replay-complete-quiet"})
        self.replay_next_at = now + REPLAY_INTERVAL_S

    def _send_replay_message(self, server, msg) -> None:
        """Wrap a captured typed-stream body in a Carrier record + envelope.

        Mirrors the V3 response wrap (ch=0, flag=0x21, VLQ32 length-prefixed
        body). The replay body already carries the [00 01 <type>] preamble,
        so it is forwarded verbatim. Bodies above the DTLS plaintext cap are
        split with MF_CHUNKS (chunks-countdown convention).
        """
        from .javelin.wire import chunk_replay_payload, encode_vlq32

        body = msg.body
        inner = encode_vlq32(len(body)) + body
        seq = self.out_msg_seq
        self.out_msg_seq = (seq + 1) & 0xFFFF
        rel = self.out_rel_seq
        self.out_rel_seq = (rel + 1) & 0xFFFF
        if len(inner) <= REPLAY_SINGLE_LIMIT:
            rec = MessageRecord(
                channel=0,
                payload=inner,
                sequence=seq,
                reliable_sequence=rel,
                reliable=True,
                connecting=False,
                flags_override=0x21,
            )
            self._send_datagram(server, [rec])
            log_event(
                {
                    "event": "replay",
                    "seq": msg.seq,
                    "type": hex(msg.type_id),
                    "size": len(body),
                    "chunks": 0,
                    "remaining": len(self.replay_queue),
                }
            )
            return
        chunks = chunk_replay_payload(inner, REPLAY_CHUNK_SIZE)
        # One chunk per datagram (the 2026-09-19 proven form: replay
        # completed to rem=0 with NO BAD_PACKETS). The 4KB bundling
        # experiment (2026-09-20) triggered client reason BAD_PACKETS
        # (SM_DISCONNECT payload 0203) right after r37 — bundling several
        # MF_CHUNKS records of one message per datagram breaks the
        # receiver's reassembly. Loss is handled by maybe_resend instead.
        for i, (remaining, sl) in enumerate(chunks):
            if i == 0:
                c_seq, c_rel = seq, rel
            else:
                c_seq = self.out_msg_seq
                self.out_msg_seq = (c_seq + 1) & 0xFFFF
                c_rel = self.out_rel_seq
                self.out_rel_seq = (c_rel + 1) & 0xFFFF
            rec = MessageRecord(
                channel=0,
                payload=sl,
                sequence=c_seq,
                reliable_sequence=c_rel,
                reliable=True,
                connecting=False,
                num_chunks=remaining,
                flags_override=0x25,  # RELIABLE | CHUNKS | DATA_CHANNEL
            )
            self._send_datagram(server, [rec])
        log_event(
            {
                "event": "replay",
                "seq": msg.seq,
                "type": hex(msg.type_id),
                "size": len(body),
                "chunks": len(chunks),
                "remaining": len(self.replay_queue),
            }
        )

    def _send_datagram(self, server, records: list[MessageRecord]) -> None:
        datagram = (
            b"\x80\x01"
            + (self.next_out_seq & 0xFFFF).to_bytes(2, "big")
            + marshal_datagram(records)
        )
        # Reliable records ride this datagram: keep it for retransmission
        # until the client's CT_ACKS bitmap covers it (GridMate WriteAckData).
        if any(rec.reliable for rec in records):
            self.sent_reliable[self.next_out_seq & 0xFFFF] = (
                time.monotonic(),
                datagram,
            )
        self.next_out_seq += 1
        self.send(server, datagram)

    def _process_acks(self, recs: list) -> None:
        """Decode the client's SM_CT_ACKS (Carrier.cpp WriteAckData format).

        flags 0x20 = keepalive-only; 0x40 = continuous [first..last];
        0x8n = bitmap of n bytes covering last-1 backwards."""
        for rec in recs:
            if not rec.is_system or rec.system_msg_id != SystemMessageId.SM_CT_ACKS:
                continue
            p = rec.payload
            if len(p) < 3:
                continue
            flags = p[0]
            last = int.from_bytes(p[1:3], "big")
            self.acked_seqs.add(last)
            if flags & 0x80:
                n = min(flags & 0x7F, len(p) - 3)
                bitmap = p[3 : 3 + n]
                for b in range(n):
                    for i in range(8):
                        if bitmap[b] & (1 << i):
                            seq = last - 1 - (b * 8 + i)
                            if seq >= 0:
                                self.acked_seqs.add(seq)
            elif flags & 0x40 and len(p) >= 5:
                first = int.from_bytes(p[3:5], "big")
                for s in range(first, last + 1):
                    self.acked_seqs.add(s)
            # AHF_KEEP_ALIVE (0x20): nothing to mark

    def maybe_resend(self, server) -> None:
        """Retransmit reliable datagrams the client's acks show as lost.

        Capped per tick AND per datagram: seq 12 (12.7KB StateBundle) was
        resent 4229x live without ever being acked — the client drops it
        while loading and re-bombing starves the rest of the stream."""
        if self.gone or not self.sent_reliable:
            return
        now = time.monotonic()
        sent = 0
        for seq in sorted(self.sent_reliable):
            if seq in self.acked_seqs:
                del self.sent_reliable[seq]
                continue
            t, dgram = self.sent_reliable[seq]
            if now - t < 0.3:
                continue
            if sent >= 4:
                return
            # Attempt count: stored in the tuple slot via a dict of counts.
            tries = self.resend_tries.get(seq, 0)
            if tries >= REPLAY_RESEND_LIMIT:
                continue
            self.resend_tries[seq] = tries + 1
            self.sent_reliable[seq] = (now, dgram)
            self.send(server, dgram)
            sent += 1
            log_event({"event": "resend", "seq": seq, "try": tries + 1, "size": len(dgram)})

    def maybe_inject(self, server) -> None:
        """Dev lever: send a raw Carrier datagram from a hex file.

        Write <repo>/services/world/inject.hex (a full datagram hex) and
        the next tick sends it to this peer and deletes the file. Lets us
        probe post-V3 message bodies against a LIVE session without a
        game restart (the panel does not re-render, so restarting is the
        only alternative). See scripts/world-inject.py.
        """
        if self.gone or not self.v3_responded:
            return
        path = REPO_ROOT / "services" / "world" / "inject.hex"
        try:
            raw = path.read_text(encoding="ascii").strip()
        except OSError:
            return
        with contextlib.suppress(OSError):
            path.unlink()
        if not raw:
            return
        try:
            datagram = bytes.fromhex(raw)
        except ValueError as exc:
            log_event({"event": "inject-bad-hex", "error": str(exc)[:120]})
            return
        log_event({"event": "inject", "size": len(datagram), "raw": datagram[:96].hex()})
        self.send(server, datagram)

    def maybe_keepalive(self, server) -> None:
        """CLOCK_SYNC ~1/s after V3 so ClientSDK does not disconnect (4)
        at 10s of server silence (Game.log 2026-09-18 20:15:08→18)."""
        if self.gone or not self.v3_responded:
            return
        now = time.monotonic()
        if self.last_keepalive and now - self.last_keepalive < 1.0:
            return
        self.last_keepalive = now
        pkt = clock_sync_datagram(self.next_out_seq)
        self.next_out_seq += 1
        log_event({"event": "keepalive", "seq": self.next_out_seq - 1})
        self.send(server, pkt)

    def maybe_send_post_v3(self, server) -> None:
        """Post-V3: 300ms after the first V3 response, SelfIdent+LIC.

        Same-burst as V3 crashes the client (2026-09-17 20:43). Waiting
        for V3 *silence* never fires: after accept the client streams
        ch0 1115B/161B blobs for the whole 2 min timeout (Game.log
        2026-09-18 19:38:18→19:40:18, 700 bogus v3-registered). Tick
        this from the UDP recv timeout as well as on_app_data.
        """
        # Hypothesized SelfIdent+LIC (0x91/0x17 + 0x86/0x14) AV'd the
        # client at NewWorld+0x6b6f1be (FUN_146b6f190: vtable+0x30
        # returned NULL → `mov r15,[rax]`). Dump
        # CrashDumps\NewWorld.exe.3664.dmp 2026-09-18 21:58:36.
        # Do not emit until a captured body exists (first-light caveat).
        if (
            POST_V3_ENABLED
            and not self.gone
            and self.v3_responded
            and not self.post_v3_sent
            and (time.monotonic() - self.v3_first_time) > 0.3
        ):
            log_event({"event": "post-v3-sending", "out_seq": self.next_out_seq})
            post = post_v3_datagram(self.next_out_seq)
            self.next_out_seq += 1
            log_event(
                {
                    "event": "reply",
                    "size": len(post),
                    "raw": post[:96].hex(),
                    "peer": f"{self.peer[0]}:{self.peer[1]}",
                }
            )
            self.send(server, post)
            self.post_v3_sent = True

    def send(self, server, datagram: bytes) -> None:
        try:
            self.conn.send(datagram)
        except (SSL.WantReadError, SSL.WantWriteError):
            pass
        except SSL.Error as exc:
            log_event({"event": "send-error", "error": str(exc)[:120]})
        self.flush(server)

    def flush(self, server) -> None:
        while True:
            try:
                out = self.conn.bio_read(65536)
            except SSL.WantReadError:
                return
            if not out:
                return
            server.sock.sendto(out, self.peer)

    def next_seq(self) -> int:  # legacy counter (kept for PlainRepServer)
        if not hasattr(self, "seq"):
            self.seq = 0
        self.seq += 1
        return self.seq


class RepServer:
    """UDP + DTLS loop. Every raw datagram is logged before decryption
    (sizes/timing) and every decrypted app-data after the handshake."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9000) -> None:
        if not HAVE_PYOPENSSL:
            raise SystemExit(
                "pyOpenSSL missing (the only non-stdlib dep of services/world): "
                "pip install pyOpenSSL  — or run with --no-dtls for the raw logger"
            )
        self.host, self.port = host, port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        # Windows: a sendto() to a client that already closed is answered
        # with ICMP port-unreachable; the NEXT recvfrom() then raises
        # WSAECONNRESET (10054) and we used to treat that as fatal —
        # the whole REP process exited (2026-09-18 16:37:19), so the
        # next Play sat in WaitingForREPConnection for 15s and popped
        # Errors::connection_rep_registration_timeout.
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        crt, key = make_self_signed_cert()
        self.ctx = SSL.Context(SSL.DTLS_METHOD)
        self.ctx.use_certificate_chain_file(str(crt))
        self.ctx.use_privatekey_file(str(key))
        self.peers: dict[tuple[str, int], PeerSession] = {}
        self.v3_count = 0

    def serve_forever(self) -> None:  # type: ignore[override]
        log_event({"event": "listening-dtls", "addr": f"{self.host}:{self.port}"})
        self.sock.settimeout(0.2)
        while True:
            try:
                data, peer = self.sock.recvfrom(65536)
            except TimeoutError:
                for session in list(self.peers.values()):
                    try:
                        session.maybe_keepalive(self)
                        session.maybe_send_post_v3(self)
                        session.maybe_resend(self)
                    except Exception as exc:  # noqa: BLE001
                        log_event(
                            {
                                "event": "tick-error",
                                "error": f"{type(exc).__name__}: {exc}"[:200],
                            }
                        )
                continue
            except OSError as exc:
                winerr = getattr(exc, "winerror", None) or exc.errno
                # 10054 = client gone (ICMP). 10035/11 = would-block.
                # Keep listening. 10038 = we closed the socket (tests).
                if winerr in (10054, 10060, 10035, 11):
                    continue
                log_event({"event": "recv-error", "error": str(exc)[:120]})
                if winerr == 10038:
                    return
                continue
            session = self.peers.get(peer)
            if session is None:
                try:
                    session = PeerSession(self.ctx, peer)
                except Exception as exc:  # noqa: BLE001
                    log_event({"event": "session-error", "error": f"{type(exc).__name__}: {exc}"[:200]})
                    continue
                self.peers[peer] = session
            try:
                session.feed(self, data)
            except Exception as exc:  # noqa: BLE001 — never kill the UDP loop
                log_event(
                    {
                        "event": "feed-error",
                        "peer": f"{peer[0]}:{peer[1]}",
                        "error": f"{type(exc).__name__}: {exc}"[:200],
                    }
                )
                self.drop(peer)

    def drop(self, peer: tuple[str, int]) -> None:
        self.peers.pop(peer, None)

    def v3_seen(self, peer: tuple[str, int], event: dict) -> None:
        self.v3_count += 1
        log_event({"event": "v3-registered", "n": self.v3_count, "peer": f"{peer[0]}:{peer[1]}", "identity": event.get("v3")})


class PlainRepServer(RepServer):
    """No-DTLS fallback: logs raw UDP and answers the V3 record in
    plaintext (useful to watch a live client before the trust patch)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9000) -> None:
        self.host, self.port = host, port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        self.peers: dict[tuple[str, int], int] = {}
        self.v3_count = 0

    def serve_forever(self) -> None:  # type: ignore[override]
        log_event({"event": "listening-plain", "addr": f"{self.host}:{self.port}"})
        while True:
            data, peer = self.sock.recvfrom(65536)
            event = describe_datagram(data)
            event.update(event="datagram", peer=f"{peer[0]}:{peer[1]}")
            log_event(event)
            connected = self.peers.get(peer, 0) > 0
            try:
                inbound_env, _ = parse_envelope(data)
                first = self.peers.get(("first", peer), inbound_env.sequence)
                self.peers[("first", peer)] = first
                replies = handle_app_data(
                    data,
                    inbound_env.sequence,
                    handshake_done=connected,
                    inbound_first=first,
                )
            except ValueError:
                replies = []
            if replies:
                self.peers[peer] = 1
                for reply in replies:
                    self.sock.sendto(reply, peer)


def serve(host: str = "127.0.0.1", port: int = 9000, dtls: bool = True):
    return RepServer(host, port) if dtls else PlainRepServer(host, port)


def run_forever(host: str = "127.0.0.1", port: int = 9000, dtls: bool = True) -> int:
    serve(host, port, dtls).serve_forever()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Azoth Javelin REP server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--no-dtls", action="store_true", help="raw UDP logger (no TLS)")
    args = ap.parse_args()
    return run_forever(args.host, args.port, dtls=not args.no_dtls)


if __name__ == "__main__":
    raise SystemExit(main())
