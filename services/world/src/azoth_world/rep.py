"""DTLS-terminating Javelin REP server (UDP).

Frozen spawn contract (services/docs/WORLD.md):
  UDP bind -> DTLS handshake -> Carrier CONNECT_REQUEST/ACK
  -> V3 registration (request parsed, response 88B) -> rep.ready 0->1
  -> post-V3 ladder (SelfIdent / LevelInfoChanged / NewProxy — TODO).

Trust: the client pins an embedded `CN=New World` cert, so the handshake
only completes after the runtime verify-bypass patch
(services/launcher/runtime-tools/frida-trust-patch.py + research/atlas/levers.md "DTLS verify
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
import traceback
from dataclasses import dataclass, replace
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
from .javelin import bundle as javelin_bundle

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
LOG_PATH = Path(
    os.environ.get("AZOTH_REP_TRAFFIC_JSONL")
    or REPO_ROOT / "services" / "world" / "rep_traffic.jsonl"
)
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
# 2026-09-24 (live probe, reverse/probes/client/frida-reader-capture.py): the client
# consumed replay seq 2/4/5 (12B, 76B, 76B) and then the typed-stream reader
# stopped receiving forever -- seq 6 (0x65c, 12706B) never arrived. The
# messages that DO arrive are <= 76B; the first one past that is 12.7KB and
# it is delivered as a SINGLE datagram because it fits under the old limit.
# That single oversized record is what breaks the client's stream: it acks
# the datagram (so the transport looks perfect, 1306/1306 acked) and then
# never delivers the message upward. So cap the single-datagram path well
# below the observed failure point: anything above a few hundred bytes gets
# MF_CHUNKS-split to REPLAY_CHUNK_SIZE, which the client has always
# reassembled correctly.
REPLAY_SINGLE_LIMIT = 256
REPLAY_RESEND_LIMIT = 6      # max resends per reliable datagram (2026-09-20:
# seq 12 (12.7KB StateBundle) was resent 4229x and never acked — the client
# drops oversized datagrams during load and re-bombing it made everything
# worse. After the cap, split-retransmit or drop: the 30s InGame timeout
# clears the session anyway.)
# After replay-complete-quiet, maybe_resend runs once per inbound datagram.
# On 2026-10-03 11:14:39 the type-0x08 tail (seq 888/889/890, try 1, 1114 B)
# was retransmitted at ~250/s — 4 per call times the inbound rate — and that
# burst lined up with OnLocalNetworkConnectionWarning. Those seqs sit next
# to the ack high-water, so "512 behind" does not catch them. Once the
# replay has finished, transmit at most 2 resends per 200 ms and skip seqs
# more than 512 below the highest acked seq. Do not apply either gate while
# the replay queue is still live or before greetings_after_replay:
# possession needs the in-burst cap of 4. A skipped resend must not consume
# a try, or the 6-try cap expires a datagram the client was never offered
# again.
POST_REPLAY_RESEND_MAX = 2
POST_REPLAY_RESEND_WINDOW_S = 0.2
POST_REPLAY_STALE_GAP = 512
# maybe_resend is invoked from the per-datagram pump, so its "4 per call" cap
# really means "4 x client traffic". Measured 2026-10-09 on a possession run:
# 232 resends in one second, 485 distinct seqs retried, 54 of them exhausting
# all 6 tries. Throttle the CALL rate here instead of weakening the per-call
# cap, which the replay burst genuinely needs for lost possession chunks.
RESEND_PUMP_MIN_INTERVAL_S = float(
    os.environ.get("AZOTH_RESEND_PUMP_INTERVAL_S", "0.05")
)
# Authoritative tick. The server must emit on its OWN clock, not in proportion
# to what the client sends. Before this, every periodic emitter was called from
# on_app_data (once per inbound datagram) and a different, smaller subset was
# called on socket timeout — so with no traffic the replay pump simply stopped,
# and with heavy traffic the server's emission rate tracked the client's.
# Measured 2026-10-09: Pearson(inbound datagrams, server replies) = 0.995, up to
# 286 outbound in one second, and the client stalled under the flood. All
# emitters already gate themselves on their own `_next_at`, so calling them from
# a fixed cadence is safe: they fire only when due.
TICK_HZ = float(os.environ.get("AZOTH_TICK_HZ", "50"))
TICK_INTERVAL_S = (1.0 / TICK_HZ) if TICK_HZ > 0 else 0.02
# Coalesce the CT_ACKS replies. The 0x40 continuous form acknowledges a RANGE,
# so answering once per window carries the same information as answering once
# per inbound datagram, at a fraction of the outbound rate. Measured
# 2026-10-09: uncoalesced 1:1 replies made the server emit 286 datagrams in
# one second for 185 inbound, the client stalled under the flood, stopped
# sending, and its ClientSDK dropped the transport at 10 s of silence
# (`transportError 4`, the red cable). The official capture shows the server
# sending ~3041 ch0 datagrams for 867 inbound ch0 — it does not answer 1:1.
ACK_COALESCE_S = float(os.environ.get("AZOTH_ACK_COALESCE_S", "0.05"))
# Width of the continuous ACK window, in inbound envelope sequences.
#
# MEASURED 2026-10-14, and this is a real server bug that costs the session: the CT_ACKS was
# `[ack_first=inbound_first, ack_last=current]` with `ack_first` PINNED to the session's first
# sequence, so the acknowledged range grew by one per datagram for the whole session. The two
# fields are 16 bits, so a wrap-aware reader can only represent a range narrower than half the
# space (32768); past that the range is ambiguous and the client stops treating its reliable
# records as delivered. It does not report an error - it RETRANSMITS. Measured in one session:
#
#   last envelope seq below 32768 : 32767 at 08:42:44
#   first at/above                : 32768 at 08:42:44   (ACK width 32766)
#   first retransmitted client record: relSeq 1836 at 08:42:45
#
# From that instant the client re-sent every reliable record ~200 times: 140 174 channel-0
# ping records in 10 minutes carrying only **660 distinct sequences** (212x), against 1.2x
# earlier in the same session, with OnLocalNetworkConnectionWarning climbing ~1/s throughout.
# The server's own outbound rate, ACK range and reliable-sequence stream stayed correct and
# constant, so this is an addressing-window defect, not a load or transport failure.
#
# The fix is a sliding window: acknowledge the most recent ACK_WINDOW sequences instead of
# everything since the session started. 16384 is half the safe maximum and, at the measured
# ~21 inbound datagrams/s, still covers ~13 minutes of history.
ACK_WINDOW = int(os.environ.get("AZOTH_ACK_WINDOW", "16384"), 0)
# Minimum seconds before the SAME reliable datagram is retransmitted again.
# 0.3 is the long-standing value. Raising it throttles the in-flight resend
# storm that peaks while the paced replay drains (measured 650 resends in one
# second, which lines up with a burst of OnLocalNetworkConnectionWarning).
# Default unchanged; A/B with AZOTH_RESEND_INTERVAL_S.
RESEND_INTERVAL_S = float(os.environ.get("AZOTH_RESEND_INTERVAL_S", "0.3"))
# 2026-09-24: with the limit above, 12 chunked datagrams of the 12.7 KB
# message (type 0x65c) reach the client but it only reassembles 6370 of
# 12706 bytes, then the stream turns to garbage (`num_bytes=0`). The client
# acks every datagram, so nothing is lost on the wire: the chunks arrive
# back-to-back faster than the client's Carrier drains them. Pace them.
# AZOTH_CHUNK_GAP_MS tunes the delay; 0 restores the burst form.
REPLAY_CHUNK_GAP_MS = float(os.environ.get("AZOTH_CHUNK_GAP_MS", "4"))
# 2026-09-24: with pacing the stream flows (4 -> 176 messages reach the CSDK
# reader) but the 12.7 KB message is still reassembled to exactly 6370 bytes,
# every attempt, so it is a protocol convention and not a race. Two readings
# of the MF_CHUNKS `numChunks` u16 are possible: a countdown (12,11,...,1) or
# the constant total (12,12,...,12). This knob selects which one we emit.
#   total (default) = every record carries the same count
#   downcount       = each record carries the remaining chunk count
REPLAY_CHUNK_COUNT_TOTAL = os.environ.get("AZOTH_CHUNK_COUNT", "total") == "total"
# Post-replay heartbeat (type 0x15d). The capture shows the official server
# pinging the client with a 12-byte ch0 message every ~1s:
#
#     body = 00 01 9d 05 00 03 <6-byte LE-ish tick>
#
# and the client answering with a 36-byte 0x15d that ECHOES our tick verbatim
# (plus a 4-byte value and 16 zero bytes it fills in itself). The tick is a
# monotonic nanosecond counter: consecutive captured values differ by ~1e9
# (exactly one second), e.g. 6ef6af912d74 -> 6ef6eb43dd6b -> 6ef726e74673.
#
# Why this matters: the client's state watchdog (FUN_146445e10) counts ticks
# in which NO expected message for the current state arrived, and tears the
# connection down when the counter reaches the state's budget. Measured
# 2026-09-27: once the replay stream ends the server goes quiet, the client
# sits in InGame for ~44 s and then reports
# `State(InGame) is timeout : frames 10, currentTimeoutIntervalTimeoutCount 1`
# followed by `connection_ingame_timeout`. Continuing the ping keeps the
# exchange alive. The tick never has to match the client's own clock — the
# client only echoes it — so we continue the captured series.
HEARTBEAT_ENABLED = os.environ.get("AZOTH_REPLAY_HEARTBEAT", "1") != "0"
# Diagnostic: log every inbound UDP datagram (size + head) before DTLS. A
# failed REP handshake is otherwise invisible server-side: the client times
# out in WaitingForREPConnection while this process logs nothing, so we cannot
# tell "packets never arrived" from "DTLS rejected them". Off by default.
RAW_LOG = os.environ.get("AZOTH_LOG_RAW", "0") != "0"
OUTBOUND_PAYLOAD_LOG = os.environ.get("AZOTH_LOG_OUTBOUND_PAYLOADS", "1") != "0"
# Persistent append handle for the event log (see log_event).
_LOG_HANDLE = None
HEARTBEAT_PERIOD_S = float(os.environ.get("AZOTH_REPLAY_HEARTBEAT_PERIOD_S", "1.0"))
# Captured tick of the LAST 0x15d the replay streamed (seq 0x8e).
HEARTBEAT_TICK_START = int(
    os.environ.get("AZOTH_REPLAY_HEARTBEAT_TICK", "0x6ef8c888af44"), 0
)
HEARTBEAT_TICK_STEP = int(os.environ.get("AZOTH_REPLAY_HEARTBEAT_TICK_STEP", "1000000000"), 0)
# Historical post-replay activity-stream experiment (type 0x1b88), not a
# current connection or red-cable fix. The 2026-10-04 A/B included one
# 40-minute REP session followed by a disconnect; it did not prove that this
# message refreshed the relevant clock or deliver a stable user-visible ALC
# connection. Later live ALC probes found +0xAA0 stayed closed and the HUD
# +0xAA8 response stamp stopped advancing, while REP transport and the HUD
# indicator could disagree. Keep this experiment opt-in and document its
# results in research/atlas/client-functions.json. The capture contains 23
# identical 42-byte 0x1b88 bodies; whether their GUID takes the old miss-path
# clock update remains unproven. Do NOT extend this to 0x08: replaying the
# captured tail bundles already cost the ClientContext once
# (AZOTH_REPLAY_STATE_STREAM lesson).
ACTIVITY_STREAM_ENABLED = os.environ.get("AZOTH_REPLAY_ACTIVITY_STREAM", "0") == "1"
ACTIVITY_STREAM_PERIOD_S = float(
    os.environ.get("AZOTH_REPLAY_ACTIVITY_STREAM_PERIOD_S", "0.5")
)
ACTIVITY_STREAM_TYPE = 0x1B88
# Post-replay state-bundle stream (type 0x08). The capture's steady state is
# dominated by R-direction 0x08 bundles: 79 of them, and the last 17
# (seq 0xa0..0xb0, every one under REPLAY_CHUNK_SIZE so it stays a single
# datagram) run right up to the end of the capture. Our replay stops at 0xb0
# and the server then only pings 0x15d, while the real server kept streaming
# 0x08. Measured consequence: `OnLocalNetworkConnectionWarning` climbs
# monotonically (1 -> 117 between 21:26 and 21:45 UTC on 2026-10-03) and the
# client finally logs `disconnected from REP` -> state Disconnected. So
# continue the real stream instead of inventing bodies: cycle the captured
# tail bundles in order, each with a fresh outbound seq/rel, exactly as
# _send_replay_message does. No body is synthesised.
# MEASURED 2026-10-04: this stream BREAKS THE CONNECTION and is therefore OFF by
# default. With it on, a fresh client did this: spawn 06:54:49 UTC, ClientContext
# created 06:54:53, then at 06:55:12 `disconnected from REP` +
# `@mm_csdkerr_disconnect (4)` + `JavelinGame::OnConnectionFail`, the client
# reconnected from scratch, and on that second connection `clientContext->Initialize`
# never ran again, so Game.log filled with 758
# `HandleUnexpectedMessage skipping ReceiveStateBundle ... clientContext == nullptr`
# and every world state update was dropped. With the stream OFF (same build, same
# world): ONE spawn, Initialize ran, exactly ONE skipped bundle, no disconnect, no
# Connection fail, and `OnLocalNetworkConnectionWarning` stayed at 1. So looping the
# captured tail bundles re-triggers the client's login/spawn path and costs the
# ClientContext. Do not re-enable this as a fix; the cable needs a different
# continuation (see the ClientContext note below).
# MEASURED 2026-10-13: this is no longer experimental - it is what makes the session
# correct. The real server never stopped sending type-0x08 state, and with our replay
# stopping at 0xb0 the client's ALC "last response" stamp ages out and the HUD cable goes
# red (see RED_CABLE_FIXED_record1_state_stream_refreshes_the_alc_stamp_20261013).
# Two measured facts set the defaults:
#   * the LOCAL PLAYER's own state is record_id 1 and lives only in the bundles at replay
#     seq 0x98/0x9A/0x9C/0x9E, all BELOW the old floor of 0xA0, so the old default never
#     re-sent the player's state at all - the floor is now 0x94;
#   * the cable clears when the player's record is re-sent more often than the amber
#     threshold (~2 s), so it gets its own faster period while the rest of the world
#     state keeps the original's ~1/s rate.
STATE_STREAM_ENABLED = os.environ.get("AZOTH_REPLAY_STATE_STREAM", "1") == "1"
STATE_STREAM_PERIOD_S = float(os.environ.get("AZOTH_REPLAY_STATE_STREAM_PERIOD_S", "1.0"))
STATE_STREAM_MIN_SEQ = int(os.environ.get("AZOTH_REPLAY_STATE_STREAM_MIN_SEQ", "0x94"), 0)
# Record id of the local player's own state record (the client logs "Received new local
# player metadata" for record 1). These bundles are additionally sent on their own, faster
# timer so the ALC stamp stays young and the cable stays clear.
STATE_STREAM_PLAYER_RECORD = int(os.environ.get("AZOTH_REPLAY_STATE_STREAM_PLAYER_RECORD", "1"), 0)
STATE_STREAM_PLAYER_PERIOD_S = float(
    os.environ.get("AZOTH_REPLAY_STATE_STREAM_PLAYER_PERIOD_S", "0.25")
)
# MEASURED 2026-10-13: the local player's own state record is what refreshes the ALC
# local client's "last response" stamp, and that stamp IS the red HUD cable
# (age = clock() - *(alc + 0xAA8); amber ~2 s, red ~15 s).
#
# In the capture the local-player record is `record_id 1` and it appears only in the
# four 7154-byte bundles at replay seq 0x98/0x9A/0x9C/0x9E (152/154/156/158) - all of
# which sit BELOW the stream's old default floor of 0xA0, so the stream never re-sent
# them. Measured consequence: with the floor at 0xA0 the stamp NEVER moved (age grew
# 110 s -> 250 s, cable RED); with the floor at 0x94 it refreshed 12 times in 140 s and
# the cable dropped from RED to YELLOW.
#
# This knob restricts the stream to bundles whose FIRST record id equals the given
# value, so every send is a refresh instead of one in 29. 1 = the local-player record.
# -1 (default) keeps every bundle at or above the floor.
STATE_STREAM_ONLY_RECORD = int(os.environ.get("AZOTH_REPLAY_STATE_STREAM_ONLY_RECORD", "-1"), 0)
# The client deduplicates replication by seq: FUN_14643e7b0 accepts an unreliable
# replication message only when `msg.clientContextInstanceId == port[+0x80]` AND
# `*(u64*)(msg+0x28) > port[+0x78]` (m_lastUnreliableReplicationSeq); FUN_1406d97b0
# is just `return msg+0x28` and FUN_1406c10a0 is `return byte [msg+0x30]`.
# Measured 2026-10-03: the high-water sat at 53 and every re-sent captured bundle
# carried its ORIGINAL seq (0xa0 -> 0x25=37 ... 0xb0 -> 0x35=53), so all 255 were
# rejected as already seen. The seq is a plain byte at body offset 4 of a 0x08
# bundle (`00 01 08 01 <seq> ...`). Re-sending a captured bundle therefore has to
# continue the counter above the high-water; that is the same thing the real
# server did, not a synthesised body. STATE_STREAM_SEQ_BASE is one past the
# highest captured seq.
# The counter is a PREFIX VARINT, not a raw byte. Overwriting one byte with a
# value that needs two bytes (0x80 and up) turns a one-byte varint into a
# two-byte one and shifts the whole fragment list, so the client reports
# `Failed to unmarshal MessageEnvelope::m_message` /
# `unmarshalError: ValidationError`. That is the real cause of the 2026-10-09
# A/B below, where the rewrite looked like it corrupted "any write to body[4]":
#   FLOOR=0x80 (old default) -> 32 `Failed to unmarshal` (0x80 = 2-byte varint)
#   FLOOR=0x36               -> 32 `Failed to unmarshal` (1 byte, but the
#                               capture's own re-applied records also fail)
#   REWRITE=OFF              ->  0 `Failed to unmarshal`, 1 skip, 7.4 min stable
# With REWRITE=OFF the bundles are not fixed, they are DROPPED: their counter is
# at or below the client's high-water, so the replication gate discards them
# before any deserialization is attempted. "0 failures" therefore does not mean
# they applied. The rewrite now re-encodes the varint through the verified
# parser (`javelin.bundle.with_replication_seq`), which fixes the width problem;
# the remaining open question is whether re-applying a captured record is
# idempotent client-side, which needs a live run to settle.
# Default ON: with the rewrite OFF the re-sent bundles keep their captured counter, which
# is at or below the client's high-water, so the replication gate DISCARDS every one of
# them (measured: a session sent 697 bundles with zero client-side errors and behaved as if
# nothing had been sent). The rewrite re-encodes the varint through the verified parser, so
# it does not have the width bug that made an earlier version corrupt the body.
STATE_STREAM_REWRITE_SEQ = os.environ.get("AZOTH_REPLAY_STATE_STREAM_SEQ", "1") != "0"
# Byte offset of the counter in the capture's bundles, where its varint happens
# to be one byte wide. Kept for the tests and for reading a captured body by
# eye; the live path decodes the varint instead of indexing this.
STATE_STREAM_SEQ_OFFSET = 4
# Measured 2026-10-03: the replay itself pushed the client's high-water to 127,
# so a stream starting at 54 spent ~70 messages being dropped before it passed
# it. Start above any captured seq instead of just above the armed bundles.
STATE_STREAM_SEQ_FLOOR = int(os.environ.get("AZOTH_REPLAY_STATE_STREAM_SEQ_FLOOR", "0x80"), 0)
# Post-replay INPUT RESPONSE (types 0x1096/0x1097). In the capture the server
# answers the client's local-player state stream (type 0x635, client->server)
# with these two short messages immediately after the 0x635 burst (replay seq
# 0x75 = 0x1096 80 B, 0x76 = 0x1097 24 B). Both carry the local-player key and
# some state floats. Our replay sends them ONCE and then goes quiet, which is
# exactly when the client HUD's "Time since last response" starts climbing.
# Re-send the captured bodies verbatim on a period so the client keeps seeing a
# server response to its input. Default off; A/B with the env var.
INPUT_RESPONSE_ENABLED = os.environ.get("AZOTH_REPLAY_INPUT_RESPONSE", "0") == "1"
INPUT_RESPONSE_PERIOD_S = float(
    os.environ.get("AZOTH_REPLAY_INPUT_RESPONSE_PERIOD_S", "1.0")
)
INPUT_RESPONSE_TYPES = (0x1096, 0x1097)
# MEASURED 2026-10-13: the captured 0x1096/0x1097 bodies carry a 16-byte TARGET at
# body offset 4 (right after `00 01 <type varint>`), and it is
# `93a3e477cb5fd51ebf85314bbc4a951a` - the capture session's own local id for the
# client's `TimeComponentClientFacet`. Our replay sends that body verbatim, and the
# client rejects it: `RMIDispatch: The facet target ID couldn't be found
# {targetLocalId: 10638597947943539998}` (0x93a3e477cb5fd51e). The facet EXISTS in our
# session (`TimeComponentClientFacet` is bound at `component + 0x80` on component 65,
# measured), so only its LOCAL id differs: the registry assigns ids per session. This
# knob re-addresses those two messages to an id discovered at runtime.
#   unset        -> send the captured target (previous behaviour)
#   <32 hex>     -> use that 16-byte target
#   file         -> re-read INPUT_RESPONSE_TARGET_FILE on every send, so a live probe
#                   (reverse/probes/client/frida-facet-target-id.py) can publish the id
#                   mid-session without restarting the client
# MEASURED 2026-10-13: our input-response goes out on CHANNEL 0 in the capture's
# `[vlq32 len]` container, because that is what `_send_replay_message` does. But the
# message it answers arrives on CHANNEL 1 (the client's 0x635 stream), and the client's
# own channel-1 records use a different container and a different field order:
#     client -> server:  [u32 BE crc32][u32 BE len][16-byte target][00 01][type][body]
#     capture server -> : [vlq32 len][00 01][type][16-byte target][payload]
# (measured: 9997 channel-1 records with flags 0x20 in one session, all carrying the
# crc32+len container). Nobody has yet sent the ALC answer as a proper channel-1
# record, so these two knobs exist to test exactly that - a one-variable A/B.
INPUT_RESPONSE_CHANNEL = int(os.environ.get("AZOTH_REPLAY_INPUT_RESPONSE_CHANNEL", "0"), 0)
INPUT_RESPONSE_CONTAINER = os.environ.get(
    "AZOTH_REPLAY_INPUT_RESPONSE_CONTAINER", "server"
).strip().lower()
INPUT_RESPONSE_TARGET = os.environ.get("AZOTH_REPLAY_INPUT_RESPONSE_TARGET", "").strip().lower()
INPUT_RESPONSE_TARGET_FILE = os.environ.get(
    "AZOTH_REPLAY_INPUT_RESPONSE_TARGET_FILE", ".azoth/state/alc-target.txt"
)
# EXPERIMENTAL (default off): echo the client's own channel-1 player-state
# record back on channel 1. The capture has NO server->client channel-1 traffic
# (see SERVER-CONTRACT.md "The 0x635 stream"), so this is a synthetic probe to
# test whether the client needs ANY channel-1 inbound record to keep simulating
# the local player. It reuses the client's own bytes, so the body is not
# invented; only the direction and the envelope seq are new. Do not treat a
# negative result as final until the client's channel-1 reader is decompiled.
CHANNEL1_ECHO_ENABLED = os.environ.get("AZOTH_REPLAY_CHANNEL1_ECHO", "0") == "1"
CHANNEL1_ECHO_PERIOD_S = float(os.environ.get("AZOTH_REPLAY_CHANNEL1_ECHO_PERIOD_S", "0.5"))
CHANNEL1_ECHO_MAX_BODY = int(os.environ.get("AZOTH_REPLAY_CHANNEL1_ECHO_MAX_BODY", "256"))
# EXPERIMENTAL (default off): answer the client's channel-1 local-player state stream
# with a real, TYPED movement message instead of an echo.
#
# WHY THIS IS THE BEST CANDIDATE YET. The measured asymmetry is the strongest signal
# in the whole protocol: the client sends its local-player state on channel 1 about
# 20 times a second and the server has NEVER answered on channel 1 or 2. The client's
# own cvars name the contract that is missing:
#
#     javelin.alc-server-timeout-for-input / -for-ui / -for-ui-high
#     javelin-server.enable-alc-movement-reporting
#     javelin-server.alc-movement-reporting-period-seconds
#     javelin-server.ALC-max-input-to-combine
#     javelin-server.alc-update-parametric-blend-params-on-server
#
# ALC = Actor Local Control: the client sends INPUT, the server COMBINES it and
# answers with authoritative position. Without that answer the client has no
# authority to move, which is exactly what is observed.
#
# WHAT IS SENT. `ReceivePlayerPositionClientMsg` (wire type 4216, GUID
# 39ca8bca-2ee8-4104-b0e9-7c2a51b52fb4). Its wire layout was decoded statically from
# the client's own object-vtable marshal (FUN_143f97c70) and unmarshal
# (FUN_143f97d10), which agree, so the 36 bytes below are the client's format and not
# a guess:
#
#     8 bytes  u64 BE   \ 16-byte actor id (the player entity) split in two
#     8 bytes  u64 BE   /
#     8 bytes  u64 BE      local-player key
#     4 bytes  u32 BE   \  position group
#     4 bytes  u32 BE    |
#     4 bytes  u32 BE   /
#
# Framing is the same typed envelope the ch0 stream uses: `[00 01 <prefix-varint>]`
# then the body. The default channel is 1, because that is the channel the client's
# own input stream uses.
#
# The three u32s are the position group by static evidence (they are handed to a
# 16-byte compound that a transform-like setter consumes); their SCALE and AXIS ORDER
# are unknown, so this is an experiment to be A/B'd, not a finished feature. A wrong
# scale cannot crash the client: the unmarshal reads fixed widths in this order.
POSITION_REPLY_ENABLED = os.environ.get("AZOTH_REPLAY_POSITION_REPLY", "0") == "1"
POSITION_REPLY_PERIOD_S = float(os.environ.get("AZOTH_REPLAY_POSITION_REPLY_PERIOD_S", "0.1"))
POSITION_REPLY_CHANNEL = int(os.environ.get("AZOTH_REPLAY_POSITION_REPLY_CHANNEL", "0"))
POSITION_REPLY_TYPE = 0x1078  # ReceivePlayerPositionClientMsg
# RELIABLE BY DEFAULT: required for the client to decode wire 4216. This is
# NOT a measured movement fix; the client currently fails the RMI facet lookup.
#
# Every position reply before that date went out with
# `flags_override = 0x20` (unreliable), and the client's Carrier ACKs an
# unreliable channel-0 record but never hands it to the inbound message decoder
# `FUN_146b6eb70`. The observable signature was a CLEAN client log plus ZERO
# calls into the client's own reader `FUN_143f97d10`, which was misread three
# times as "wire type 4216 is not receivable". It is receivable: with
# `flags 0x21` the typed dispatcher resolves index 4216 and the reader runs
# 1:1 with the sends. An earlier claim that this moved the player used an invalid
# screenshot-diff metric and was retracted. Game.log now shows 4216 dispatch
# failing because targetLocalId has no facet target. Keep reliable as the
# decode-tested variant; do not describe it as movement until transform motion
# and successful facet delivery are measured.
POSITION_REPLY_RELIABLE = os.environ.get("AZOTH_REPLAY_POSITION_REPLY_RELIABLE", "1") == "1"
# Fixed point or float, selected by env so the scale can be A/B'd without a code edit.
POSITION_REPLY_SCALE = float(os.environ.get("AZOTH_REPLAY_POSITION_REPLY_SCALE", "100"))
# The u64 "local-player key" slot (body offset 16). "0" keeps the placeholder;
# "actor" copies the actor id's first 8 bytes, which is the cheapest way to test
# whether the client matches the reply to the local player by that field.
POSITION_REPLY_KEY = os.environ.get("AZOTH_REPLAY_POSITION_REPLY_KEY", "0").lower()
# The position group. "offset" (default) sends a small constant offset so a visible
# move is attributable; "zero" sends the origin; "raw" passes
# POSITION_REPLY_XYZ as three integer triplets (scale applies).
POSITION_REPLY_MODE = os.environ.get("AZOTH_REPLAY_POSITION_REPLY_MODE", "offset").lower()
# EXPERIMENTAL (default off): send StartMovementCommunicationMsg (wire 726,
# 0x2d6, 20 bytes = 16-byte actor blob + u32 BE) once, right before the first
# position reply. Static layout is in
# .azoth/night/subagent-movement-codecs.md §2.3; the real server is expected to
# open the movement channel before it asserts positions.
START_MOVEMENT_ENABLED = os.environ.get("AZOTH_REPLAY_START_MOVEMENT", "0") == "1"
START_MOVEMENT_TYPE = 0x2D6  # StartMovementCommunicationMsg
# RELIABLE ON CHANNEL 0 BY DEFAULT, like the position reply, and for the same measured
# reason: the client's inbound decoder only sees a Carrier record with MF_RELIABLE set.
# The first attempt at this message (2026-10-11) went out unreliable (`flags 0x20`) on
# channel 1, so it was Carrier-ACKed and never decoded -- which is why its "accepted
# without error" reading was weak evidence (an undecoded message is dropped silently).
# Body layout is byte-verified against the client's own reader FUN_146a55240 (16-byte raw
# blob + u32 BE = 20 bytes, `.azoth/night/subagent-movement-codecs.md` 2.3), so the body
# was never the problem; the framing was.
START_MOVEMENT_CHANNEL = int(os.environ.get("AZOTH_REPLAY_START_MOVEMENT_CHANNEL", "0"))
START_MOVEMENT_COMM = int(os.environ.get("AZOTH_REPLAY_START_MOVEMENT_COMM", "1"))
START_MOVEMENT_RELIABLE = os.environ.get("AZOTH_REPLAY_START_MOVEMENT_RELIABLE", "1") == "1"
# The record container the reply is wrapped in.
#
# "server" (default): `[vlq32 len][00 01][type][body]`, the form the capture's own
#   server->client stream uses. The client accepts it on channel 0.
# "client": `[u32 BE crc32][u32 BE len][16-byte target][00 01][type][body]`, which is
#   what the client itself puts on channels 0 and 1. Verified over one live session:
#   285/294 channel-0 records and 40279/40279 channel-1 records satisfy BOTH the CRC
#   and the length field. The client's streaming channel (1, type 0x635) uses this
#   container exclusively, so a reply that must be read as a channel-1 record has to
#   use it too.
POSITION_REPLY_CONTAINER = os.environ.get("AZOTH_REPLAY_POSITION_REPLY_CONTAINER", "server").lower()
# The message's 16-byte target blob (body[0:16] and, in the "client" container, the
# record target). Empty = the client's actor id from the replay.
#
# MEASURED 2026-10-11 (probe reverse/probes/client/frida-rmi-targets.py, live client):
# the RMI target id of this message is its body's first 8 bytes, and the client's
# target registry holds 37063 entries (capacity 131072). The actor id the server has
# been sending (`1a954abc4b3185bf`) is NOT one of them: 601 lookups, 0 hits, which is
# the `facet target ID couldn't be found` line in Game.log. The 16-byte blob that the
# capture's own input-response messages carry (`93a3e477cb5fd51ebf85314bbc4a951a`)
# IS registered: 136 lookups, 136 hits, same session. So this knob exists to send the
# position reply to a target the client actually has; it is a one-variable A/B, not a
# finished feature. See `rmi_dispatch_facet_target_registry_20261011` in the atlas.
POSITION_REPLY_TARGET = os.environ.get("AZOTH_REPLAY_POSITION_REPLY_TARGET", "").strip().lower()
# Controlled replay A/B for the six explicitly redacted 36-byte UUID slots.
# off preserves the capture; character|session fills only the allowlisted
# offsets in javelin.replay_store. Never inferred from arbitrary body text.
# ---------------------------------------------------------------------------------------------
# CLIENT-FACET RESPONSES: SEND THEM WHEN THE CLIENT CAN RECEIVE THEM
# ---------------------------------------------------------------------------------------------
# MEASURED 2026-10-13, and this is the whole of the "our replay talks to a different client"
# problem. A clean session logged 29 `RMIDispatch: The facet target ID couldn't be found`
# errors, ALL of them inside a single millisecond, 1 ms BEFORE `player spawn succeeds`, while
# the replay itself drains 8 s AFTER it. So the replay blasts responses at a client whose
# object graph does not exist yet, and because the replay sends each message once, that data
# is lost for the rest of the session.
#
# Which action is correct depends on whether the client has the facet AT ALL, which was
# measured against the live player entity's 107 bound client facets:
#
#   PRESENT (so the message is fine, it is just early) -> DEFER until the replay drains
#     TimeComponent, GameModeParticipant, GridTracking, Contracts
#   ABSENT  (so there is no target and never will be) -> DROP
#     GlobalStorage, EventNotification, VoiceChat
#
# A dropped message here is not data loss: it answers a request our client never made (the
# replay is another client's capture), so the client has nothing waiting for it. Measured: the
# client sends 43 distinct request types in a session and `GlobalStorageComponentServerFacet_
# RequestReplicateStorageSearchResults` (wire 7039), the request behind the 23 storage-search
# replies, is not one of them.
REPLAY_DROP_UNRECEIVABLE = os.environ.get("AZOTH_REPLAY_DROP_UNRECEIVABLE", "1") == "1"
REPLAY_DEFER_CLIENT_FACETS = os.environ.get("AZOTH_REPLAY_DEFER_CLIENT_FACETS", "1") == "1"
# Request-correlated gating. ON (default) sends a captured typed response only when the
# client actually sent the request it answers; OFF restores the older static behaviour
# (defer everything in the table, then send it unconditionally) so the two can be A/B'd.
REPLAY_REQUEST_GATING = os.environ.get("AZOTH_REPLAY_REQUEST_GATING", "1") == "1"
# How long a request-gated response is held waiting for its request before it is given up on.
# The client sends most of its startup requests inside the first seconds after spawn.
DEFER_DECISION_TIMEOUT_S = float(os.environ.get("AZOTH_REPLAY_DEFER_TIMEOUT_S", "20"))

# ---------------------------------------------------------------------------------------------
# RESPONSE -> REQUEST: a captured response is only answerable if OUR client asked for it
# ---------------------------------------------------------------------------------------------
# MEASURED 2026-10-14. This replaces a static "facet absent -> drop" table with the rule the
# measurement actually supports: a typed `*ComponentClientFacet_*` response exists because some
# client sent the `*ComponentServerFacet_*` request it answers, and OUR client is not that
# client. The replay is another client's capture, so it contains answers to requests ours never
# makes; the server used to blast them at a client with no target and lose them silently.
#
# Pairs are derived two ways and both are recorded in research/docs/INBOUND-REQUESTS.md:
#   * ORDERING: in the capture the response follows its request. Contracts seq 59 -> 67,
#     VoiceChat seq 100 -> 101, the input burst seq 110-114 -> the time pair 117/118.
#   * NAMING: `XComponentServerFacet_M` / `XComponentClientFacet_OnM` in the same component
#     family (regenerate the name table with reverse/tools/scan-wire-names.py).
#
# An EMPTY tuple means the response has no identifiable request in the capture: it is an
# unsolicited server push, and it is handled by ABSENT_FACET_RESPONSES instead.
RESPONSE_REQUESTS: dict[int, tuple[int, ...]] = {
    # response -> request(s) that justify it
    0x08E6: (0x09FC,),                       # Contracts OnLookup <- LookupContractsByParticipant
    0x1067: (0x066B,),                       # VoiceChat OnVoiceChatServiceRegistered <- Register
    0x1096: (0x1098, 0x0635),                # Time SyncTimeChange <- SyncToClient / input stream
    0x1097: (0x1098, 0x0635),                # Time SyncDayPhase  <- SyncToClient / input stream
    0x1033: (0x101D, 0x101E, 0x102E, 0x102F, 0x192C),  # GridTracking UpdatePhasing family
    0x1B88: (0x1B7F,),                       # GlobalStorage Receive <- RequestReplicate...
    0x136A: (0x0CED,),                       # GameModeParticipant OnLeftQueue <- RequestLeave
    0x16A0: (0x169D,),                       # Inventories OnQueryInventories <- QueryInventories
    0x0CA4: (),                              # EventNotification SyncNotifications: unsolicited
}

# Unsolicited responses whose client facet was measured ABSENT on the live player entity: there
# is no target and never will be, so no request can justify them. This is the ONLY remaining
# static drop, and it is one type. (0x1B88 and 0x1067 used to be here; 0x1B88 is now dropped
# because the client never sends 0x1B7F, and 0x1067 is now SENT because the client does send
# 0x066B -- a request-correlated rule is a sharper instrument than the facet survey was.)
ABSENT_FACET_RESPONSES: dict[int, str] = {
    0x0CA4: "EventNotificationComponentClientFacet_SyncNotifications",
}

# The PRE-2026-10-14 drop set, kept ONLY so `AZOTH_REPLAY_REQUEST_GATING=0` reproduces the old
# behaviour exactly for an A/B. With gating on it is not used at all: 0x1B88 is dropped by
# request correlation and 0x1067 is sent because the client asks for it.
LEGACY_UNRECEIVABLE_TYPES: dict[int, str] = {
    0x1B88: "GlobalStorageComponentClientFacet_ReceiveStorageSearchItems",
    0x0CA4: "EventNotificationComponentClientFacet_SyncNotifications",
    0x1067: "VoiceChatComponentClientFacet_OnVoiceChatServiceRegistered",
}
# Back-compat alias: the name the old code and its tests used for the static drop set.
UNRECEIVABLE_RESPONSE_TYPES: dict[int, str] = dict(LEGACY_UNRECEIVABLE_TYPES)

# Which captured types are held back from the immediate replay burst: every one of these is a
# typed `*ClientFacet_*` RMI and the facet does not exist until the client is in the world. The
# held set is exactly the union of the request-mapped responses and the absent-facet drops.
DEFERRED_RESPONSE_TYPES: dict[int, str] = {
    0x1B88: "GlobalStorageComponentClientFacet_ReceiveStorageSearchItems",
    0x0CA4: "EventNotificationComponentClientFacet_SyncNotifications",
    0x136A: "GameModeParticipantComponentClientFacet_OnLeftQueueForGameModeMsg",
    0x16A0: "InventoriesComponentClientFacet_OnQueryInventories",
    0x08E6: "ContractsComponentClientFacet_OnLookupContractsByParticipant",
    0x1067: "VoiceChatComponentClientFacet_OnVoiceChatServiceRegistered",
    0x1033: "GridTrackingComponentClientFacet_UpdatePhasing",
    0x1096: "TimeComponentClientFacet_SyncTimeChange",
    0x1097: "TimeComponentClientFacet_SyncDayPhase",
}
# ---------------------------------------------------------------------------------------------
# INBOUND TYPED REQUESTS: the client asks, the server answers
# ---------------------------------------------------------------------------------------------
# MEASURED 2026-10-14. Until now the server had NO inbound typed dispatcher at all: every typed
# request the client made was acknowledged at the transport level and then ignored. Measured with
# scripts/inbound-inventory.py: 19 requests in a short session, 29 in one that exercises more UI.
#
# The shape is uniform and was measured, not guessed. Every client->server typed request is
#
#     [u32 BE crc32][u32 BE len][16-byte facet target][00 01][prefix-varint type][params]
#
# i.e. after the type marker the FIRST 16 BYTES ARE THE TARGET FACET'S LOCAL ID, and that id is
# exactly what a reply has to address. Two consequences the dispatcher uses:
#
#   * `0x1098` TimeComponentServerFacet_SyncToClient carries the TimeComponent client facet's
#     local id. That is the target the captured 0x1096/0x1097 reply needs, so the client HANDS US
#     the address instead of us guessing it from the capture or publishing it with a Frida probe.
#     Measured: the request's target was 93a3e477cb5fd51ebf85314bbc4a951a, the same value the
#     `frida-facet-target-id.py` probe had to discover live.
#   * `0x09FC` ContractsComponentServerFacet_LookupContractsByParticipant carries
#     4c0c0ed6478a69dabf85314bbc4a951a, which is byte-for-byte the target of the captured 0x08E6
#     response body - so the captured answer is addressed correctly when sent to the requester.
INBOUND_DISPATCH_ENABLED = os.environ.get("AZOTH_INBOUND_DISPATCH", "1") == "1"
# The 16-byte facet target that prefixes every request's parameters.
REQUEST_TARGET_PREFIX = 16
# Requests whose params we keep for inspection. Nothing here changes wire behaviour by itself.
INBOUND_KNOWN_REQUESTS: dict[int, str] = {
    0x0183: "GlobalStorageComponentServerFacet_SetReplicateStorage",
    0x05B2: "ObjectivesComponentServerFacet_UpdateTrackedObjectives",
    0x09D3: "PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient",
    0x09FC: "ContractsComponentServerFacet_LookupContractsByParticipant",
    0x0A95: "ObjectivesComponentServerFacet_SetObjectiveAutoPinning",
    0x1098: "TimeComponentServerFacet_SyncToClient",
}
# The request that teaches us the TimeComponent client facet's local id, and the replies it serves.
TIME_SYNC_REQUEST = 0x1098
TIME_SYNC_REPLIES = (0x1096, 0x1097)
# The request that asks for contracts, and the captured answer body it gets.
CONTRACTS_LOOKUP_REQUEST = 0x09FC
CONTRACTS_LOOKUP_RESPONSE = 0x08E6
# Responses the DISPATCHER owns: it sends them when the client asks, so the replay must not send
# them once and forget. Measured: the client asks for contracts twice in a session and for time
# sync once, and the replay answers each exactly once, ever.
DISPATCHER_OWNED_RESPONSES: set[int] = {CONTRACTS_LOOKUP_RESPONSE}
# Floor between two answers to the same request, so a client that asks in a loop cannot make the
# server flood it (the client asked 15x in one session for SetObjectiveAutoPinning).
INBOUND_ANSWER_MIN_INTERVAL_S = float(
    os.environ.get("AZOTH_INBOUND_ANSWER_INTERVAL_S", "0.25")
)


@dataclass(frozen=True)
class InboundRequest:
    """One decoded client->server typed request.

    ``target`` is the 16-byte facet local id the request addresses, or None when the record is
    too short to carry one; ``params`` is everything after it.
    """

    channel: int
    type_id: int
    target: bytes | None
    params: bytes
    size: int


def parse_inbound_request(payload: bytes, channel: int = 0) -> InboundRequest | None:
    """Decode one client record into {type, target, params}, or None if it is not typed.

    The client's own container puts the typed marker at offset 24; the server's form has it at 0.
    Both are tried, exactly as `_note_inbound_typed` does, so a container change shows up as an
    undecodable record rather than as a crash.
    """
    for offset in (0, 24):
        try:
            type_id, end = javelin_bundle.read_type_marker(payload[offset:])
        except Exception:
            continue
        rest = payload[offset + end:]
        target = rest[:REQUEST_TARGET_PREFIX] if len(rest) >= REQUEST_TARGET_PREFIX else None
        return InboundRequest(
            channel=channel,
            type_id=type_id,
            target=target,
            params=rest[REQUEST_TARGET_PREFIX:],
            size=len(payload),
        )
    return None


REPLAY_IDENTITY_REMAP = os.environ.get(
    "AZOTH_REPLAY_IDENTITY_REMAP", "off"
).lower()
# Controlled A/B for the redacted binary GUID at the head of 0x65c.
# off|session|character; the UUID is encoded in network byte order.
REPLAY_SELFIDENT_GUID = os.environ.get(
    "AZOTH_REPLAY_SELFIDENT_GUID", "off"
).lower()
# Controlled A/B for the duplicate LevelInfo record at replay seq 0x4d.
# off|session|character; only its serialized 8-byte context key is changed.
REPLAY_FRESH_LEVELINFO = os.environ.get(
    "AZOTH_REPLAY_FRESH_LEVELINFO", "off"
).lower()
# Controlled A/B for every redacted span in the captured StateBundle burst.
# off|character|session|persona|mixed: fills the 16-byte binary GUIDs (the
# local-player record lives in the first large bundle), the 36-byte text
# UUIDs, the 18/19/20-byte display names and the 61-byte persona string.
# The 8-byte AzCore hashes stay zero-filled; unknown lengths stay untouched.
REPLAY_SPAN_SUBSTITUTION = os.environ.get(
    "AZOTH_REPLAY_SPAN_SUBSTITUTION", "off"
).lower()
REPLAY_SPAN_DISPLAY_NAME = os.environ.get(
    "AZOTH_REPLAY_SPAN_DISPLAY_NAME", "Azoth"
)


def _parse_seq_set(raw: str) -> set[int] | None:
    """Parse '0x8c,0xae' or '0x80-0x8c' into a set of replay seqs."""
    items = [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]
    if not items:
        return None
    out: set[int] = set()
    for item in items:
        if "-" in item:
            lo, hi = item.split("-", 1)
            out.update(range(int(lo, 0), int(hi, 0) + 1))
        else:
            out.add(int(item, 0))
    return out


# Optional surgical scope: only these replay seqs get span substitution.
# Empty = every message with redactions (broad A/B).
REPLAY_SPAN_SEQS = _parse_seq_set(os.environ.get("AZOTH_REPLAY_SPAN_SEQS", ""))
# Optional length filter, e.g. '16' fills only the binary GUID slots.
# Empty = every known redaction length (16/18/19/20/36/61).
REPLAY_SPAN_LENGTHS = _parse_seq_set(os.environ.get("AZOTH_REPLAY_SPAN_LENGTHS", ""))
# Optional second pass for a different identity per seq group (the init
# burst needs the persona UUID while the interest=91 owner record needs the
# character UUID). Pass 2 never overwrites a span pass 1 already filled.
REPLAY_SPAN_SUBSTITUTION2 = os.environ.get(
    "AZOTH_REPLAY_SPAN_SUBSTITUTION2", "off"
).lower()
REPLAY_SPAN_SEQS2 = _parse_seq_set(os.environ.get("AZOTH_REPLAY_SPAN_SEQS2", ""))
REPLAY_SPAN_LENGTHS2 = _parse_seq_set(
    os.environ.get("AZOTH_REPLAY_SPAN_LENGTHS2", "")
)
# Fill ONLY the redacted UUID of the captured player's own facet record: a
# 16-byte zero span immediately followed by a length-prefixed display name.
# Measured 2026-10-01: that UUID is what the local-player gate compares with
# the character UUID in the client's local option store, and it is the one
# identity the capture redacted for the author's own player. See
# replay_store.fill_local_player_uuid for the evidence.
REPLAY_LOCAL_PLAYER_UUID = os.environ.get(
    "AZOTH_REPLAY_LOCAL_PLAYER_UUID", "off"
).lower()
REPLAY_LOCAL_PLAYER_UUID_SEQS = _parse_seq_set(
    os.environ.get("AZOTH_REPLAY_LOCAL_PLAYER_UUID_SEQS", "")
)
# Optional replay split: hold every message with seq >= SPLIT_SEQ until the
# client has had time to load the world (the capture's server streamed them
# over seconds, not in one burst; bundles that arrive before the client's
# context/level exist get queued or dropped).
REPLAY_SPLIT_SEQ = int(os.environ.get("AZOTH_REPLAY_SPLIT_SEQ", "0"), 0)
REPLAY_SPLIT_DELAY_S = float(os.environ.get("AZOTH_REPLAY_SPLIT_DELAY_S", "12"))

_REPLAY = None


def replay_store():
    global _REPLAY
    if _REPLAY is None:
        from .javelin.replay_store import ReplayStore

        _REPLAY = ReplayStore(REPLAY_PATH)
    return _REPLAY


def _is_client_hello(data: bytes) -> bool:
    """True for a DTLS ClientHello record.

    Record layout: [content_type:1][version:2][epoch:2][seq:6][length:2]
    followed by the handshake message, whose first byte is the handshake type
    (1 = ClientHello). The client retries this record with an increasing
    sequence number, so only the type byte matters here.
    """
    return len(data) > 13 and data[0] == 0x16 and data[13] == 0x01


def log_event(event: dict) -> None:
    event = {"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **event}
    line = json.dumps(event, ensure_ascii=False)
    print(f"[rep] {line}")
    # Keep the file handle open instead of open/write/close per event. The old
    # form paid an open+close on a file that reaches ~90 MB, for every single
    # event, inside the UDP loop. Measured 2026-10-09: under a client burst of
    # 287 records in one second the server stopped logging entirely for 27 s
    # (16:57:55 -> 16:58:22), and because the keepalive/heartbeat also run in
    # that loop it went silent — the client drops the transport after 10 s of
    # silence, which is the `transportError 4` seen at ~35 s after spawn.
    _log_write(line)


def _log_write(line: str) -> None:
    global _LOG_HANDLE
    try:
        if _LOG_HANDLE is None:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _LOG_HANDLE = LOG_PATH.open("a", encoding="utf-8", buffering=1)
        _LOG_HANDLE.write(line + "\n")
    except (OSError, ValueError):
        # Never let a logging failure kill the UDP loop; reopen next time.
        _LOG_HANDLE = None


def _u16(value: int) -> bytes:
    """Encode a 16-bit wire field, wrapping like the Carrier writer does.

    The envelope sequence and the ACK range fields are 16-bit on the wire while
    the server's counters grow without bound, and `int.to_bytes` raises
    `OverflowError` for anything above 65535. An unmasked counter therefore
    kills the emitter that uses it permanently: measured 2026-10-10, the last
    successful `maybe_keepalive` was at 22:10:22Z with seq 65533, and from
    22:10:23Z every tick raised `OverflowError: int too big to convert` --
    7395 consecutive tick errors over two hours, with no CLOCK_SYNC sent at all
    in that window. Wrapping is what the protocol does anyway, so mask here
    rather than trusting every caller to have masked first.
    """
    return (value & 0xFFFF).to_bytes(2, "big")


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
                        "world_id": req.world_id,
                        "character_id": req.character_id,
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
    return b"\x80\x01" + _u16(seq) + marshal_datagram([rec])


def _az_string(s: str) -> bytes:
    """AzCore wire form for AZStd::string: [u32 length_LE][raw bytes]."""
    raw = s.encode("utf-8")
    return len(raw).to_bytes(4, "little") + raw


def heartbeat_body(tick: int) -> bytes:
    """Server 0x15d ping body: the 12 bytes the capture shows.

    `00 01 9d 05` is the typed-stream preamble for type 0x15d, `00 03` is a
    constant the capture repeats verbatim, and the trailing 6 bytes are the
    monotonic tick in BIG-endian (verified against the capture: consecutive
    values differ by ~1e9, i.e. one second in nanoseconds). The client echoes
    the whole body back in its pong.
    """
    return bytes((0x00, 0x01, 0x9D, 0x05, 0x00, 0x03)) + (
        tick & 0xFFFFFFFFFFFF
    ).to_bytes(6, "big")


def position_reply_body(actor: bytes, scale: float) -> bytes | None:
    """36-byte body for `ReceivePlayerPositionClientMsg` (wire type 4216).

    The layout is the client's own, read from the marshal it uses to SEND this type
    and cross-checked against the unmarshal it uses to RECEIVE it (both agree):

        8 bytes  u64 BE   [ the 16-byte actor id, split in two
        8 bytes  u64 BE   ]
        8 bytes  u64 BE      local-player key (0 here: the client's own key is not
                             known to the server, and the actor id already selects it)
        4 bytes  u32 BE   [  position group
        4 bytes  u32 BE    |
        4 bytes  u32 BE   ]

    Every integer is BIG-endian: the client writes them with `htonl`/
    `bswap64` (FUN_140876cd0 / FUN_1408770e0) and reads them back with the
    matching byte-swapping readers. The position's SCALE and axis order are unknown,
    so `scale` is a knob for the experiment, not a decoded constant.
    """
    if len(actor) != 16:
        return None
    x = y = z = 0
    if POSITION_REPLY_MODE == "zero":
        pass
    elif POSITION_REPLY_MODE == "offset":
        # A small non-zero probe offset, scaled; keeps the value representable and
        # distinct from zero so a visible move would be attributable to this message.
        if scale:
            x = int(1.0 * scale)
            y = int(0.0 * scale)
            z = int(1.0 * scale)
    body = bytearray()
    body += actor[0:8]          # u64 BE
    body += actor[8:16]         # u64 BE
    if POSITION_REPLY_KEY == "actor":
        body += actor[0:8]      # u64 BE, the actor's first half as the key
    else:
        body += (0).to_bytes(8, "big")   # u64 BE, local-player key placeholder
    body += (x & 0xFFFFFFFF).to_bytes(4, "big")
    body += (y & 0xFFFFFFFF).to_bytes(4, "big")
    body += (z & 0xFFFFFFFF).to_bytes(4, "big")
    return bytes(body)


def position_reply_target(actor: bytes) -> bytes | None:
    """The 16-byte target blob for a position reply.

    Default: the actor id (the previous behaviour). With POSITION_REPLY_TARGET set,
    that hex blob is used instead, so the reply can be addressed to a target the
    client has registered (measured: the capture's input-response blob).
    """
    if not POSITION_REPLY_TARGET:
        return actor if len(actor) == 16 else None
    try:
        blob = bytes.fromhex(POSITION_REPLY_TARGET)
    except ValueError:
        return None
    return blob if len(blob) == 16 else None

def _partition_replay(messages: list) -> tuple[list, list, list]:
    """Split a replay into (send now, hold until the client can receive it, drop).

    Everything in DEFERRED_RESPONSE_TYPES is a typed `*ClientFacet_*` RMI, and the facet does
    not exist until the client is in the world, so it is held and decided later by
    `_deferred_decision`. The only immediate drop is the measured absent-facet set, and only
    when request gating is off; with gating on it is held too, so every suppression is decided
    and logged in one place. Anything not in a table is sent exactly as before.
    """
    now: list = []
    defer: list = []
    drop: list = []
    for msg in messages:
        if (
            REPLAY_DROP_UNRECEIVABLE
            and not REPLAY_REQUEST_GATING
            and msg.type_id in LEGACY_UNRECEIVABLE_TYPES
        ):
            drop.append(msg)
        elif (
            (REPLAY_REQUEST_GATING and msg.type_id in ABSENT_FACET_RESPONSES)
            or (REPLAY_DEFER_CLIENT_FACETS and msg.type_id in DEFERRED_RESPONSE_TYPES)
        ):
            defer.append(msg)
        else:
            now.append(msg)
    return now, defer, drop


def _counts_as_request(channel: int, type_id: int) -> bool:
    """Whether an inbound record is a typed REQUEST the client may be waiting on.

    Only channel 0 carries the typed stream. Channel 1 is the client's own input stream
    (wire 1589) and channel 3 is the Carrier/system channel, which is not Javelin-typed at
    all, so counting either as an unanswered request makes the coverage report misleading -
    measured 2026-10-14: a raw report listed 13 Carrier transport records among the
    'waiting on us' types. The heartbeat and the V3 re-registration ride channel 0 but are
    transport/handshake, not requests.
    """
    if channel != 0:
        return False
    return type_id not in (0x15D, 0x13)  # PingMsg, RegistrationRequestV3Msg


def _deferred_decision(
    msg, seen_types: set[int], *, now: float, deadline: float
) -> str:
    """Decide one held client-facet response: 'send', 'hold', or 'drop'.

    Rules, in order:
      * the response has a known request -> send once the client has sent it, otherwise hold
        until the deadline and then drop. This is the "we were answering questions nobody
        asked" fix, stated as a rule instead of a guess;
      * no known request but the facet is measured ABSENT -> drop, there is no target and the
        request cannot arrive;
      * otherwise -> send (an unsolicited push whose target exists).
    """
    if REPLAY_REQUEST_GATING and msg.type_id in RESPONSE_REQUESTS:
        required = RESPONSE_REQUESTS[msg.type_id]
        if required:
            if any(r in seen_types for r in required):
                return "send"
            return "drop" if now >= deadline else "hold"
        if msg.type_id in ABSENT_FACET_RESPONSES:
            return "drop"
    elif REPLAY_DROP_UNRECEIVABLE and msg.type_id in LEGACY_UNRECEIVABLE_TYPES:
        return "drop"
    return "send"


def _state_stream_selected(msg) -> bool:
    """Whether a bundle passes `STATE_STREAM_ONLY_RECORD`.

    A NEGATIVE value means "no record filter" and must select everything. Writing the
    filter as a plain equality against the sentinel was a real bug: the default -1 then
    matched nothing, the stream armed with ZERO bundles, and the cable stayed RED while the
    config event happily reported `state_stream: True` - a silent no-op, which is the exact
    failure mode this project keeps hitting.
    """
    if STATE_STREAM_ONLY_RECORD < 0:
        return True
    return _state_stream_record_id(msg) == STATE_STREAM_ONLY_RECORD


def _state_stream_record_id(msg) -> int:
    """The FIRST record id of a type-0x08 state bundle, or -1 if it is not one.

    A bundle body is `[00 01 08][8-byte prologue][varint payload length][records]`, and a
    record is `[u8 record_id][u8 fragment_count][fragments...]`. Record id 1 is the
    local-player metadata slot (the client logs "Received new local player metadata" for
    it), which is what `STATE_STREAM_ONLY_RECORD=1` selects.
    """
    try:
        body = javelin_bundle.decode_bundle(msg.body).payload
    except Exception:
        return -1
    return body[0] if body else -1


def _read_input_response_target() -> bytes | None:
    """The 16-byte target to re-address 0x1096/0x1097 to, or None to keep the captured one.

    `file` re-reads on every call on purpose: the local id is assigned by the client per
    session, so a probe can discover it and publish it while the session is live.
    """
    value = INPUT_RESPONSE_TARGET
    if not value:
        return None
    if value == "file":
        try:
            value = Path(INPUT_RESPONSE_TARGET_FILE).read_text(encoding="utf-8").strip().lower()
        except OSError:
            return None
    try:
        blob = bytes.fromhex(value)
    except ValueError:
        return None
    return blob if len(blob) == 16 else None


def retarget_typed_body(body: bytes, target: bytes) -> bytes | None:
    """Return ``body`` with its 16-byte target replaced.

    Layout, verified on the capture's own 0x1096/0x1097 (`read_type_marker` puts the
    target at offset 4 for both): `[00 01][type varint][16-byte target][payload]`.
    Returns None when the body does not look like that shape, so a caller can fall back
    to sending it untouched instead of corrupting it.
    """
    from .javelin import bundle as _bundle

    if len(target) != 16:
        return None
    try:
        _type_id, offset = _bundle.read_type_marker(body)
    except Exception:
        return None
    if len(body) < offset + 16:
        return None
    return body[:offset] + target + body[offset + 16 :]


def start_movement_body(actor: bytes, comm: int = 1) -> bytes | None:
    """20-byte body for `StartMovementCommunicationMsg` (wire type 726, 0x2d6).

    Layout decoded statically (`.azoth/night/subagent-movement-codecs.md` §2.3),
    shared with `MoveActorToHubMsg`:

        16 bytes  raw blob   actor id
        4 bytes   u32 BE     communication id (meaning guessed)
    """
    if len(actor) != 16:
        return None
    return bytes(actor) + (comm & 0xFFFFFFFF).to_bytes(4, "big")


def client_container(payload: bytes) -> bytes:
    """Wrap a typed payload the way the CLIENT wraps its own records.

    Measured over one live session: every non-chunked client->server DATA record on
    channels 0 and 1 is `[u32 BE crc32(payload)][u32 BE len(payload)][payload]`, with
    `payload = [16-byte target id][00 01][prefix-varint wire type][body]`. 40 279 of
    40 279 channel-1 records and 285 of 294 channel-0 records satisfy both fields.

    The server's own container (`[vlq32 len][00 01][type][body]`) is what the capture's
    server used; the client accepted it on channel 0. Which container a *channel-1*
    reply must use is exactly the open question this helper exists to A/B.
    """
    import zlib

    return (zlib.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big") + len(payload).to_bytes(
        4, "big"
    ) + payload


def wrap_reply(container: str, actor: bytes, wire_type: int, msg_body: bytes) -> bytes:
    """Frame one typed reply in the selected container.

    "server": the capture's form, `[vlq32 len][00 01][type][body]`. The client
        accepts it on channel 0.
    "client": `[u32 BE crc32][u32 BE len][16-byte target][00 01][type][body]`, the
        form every client record uses on channels 0 and 1.

    Single-sourced on purpose: an earlier version logged the container from the env
    var while the body was still built by the other branch, so the log claimed
    "client" for a 41-byte server-framed message. One function, one truth.
    """
    from .javelin.varint import encode as encode_prefix_varint
    from .javelin.wire import encode_vlq32

    if container == "client":
        inner = bytes(actor) + b"\x00\x01" + encode_prefix_varint(wire_type) + msg_body
        return client_container(inner)
    inner = b"\x00\x01" + encode_prefix_varint(wire_type) + msg_body
    return encode_vlq32(len(inner)) + inner


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
    return b"\x80\x01" + _u16(seq) + marshal_datagram([self_ident])


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
            + _u16(ack_last)
            + _u16(ack_first)
            + bytes([SystemMessageId.SM_CT_ACKS])
        ),
        sequence=0,  # inherited (flags 0x18 omits both SEQ fields)
        reliable_sequence=0,  # inherited
        reliable=False,
        connecting=False,
        flags_override=0x18,  # SEQUENTIAL_ID | SEQUENTIAL_REL_ID
    )
    return b"\x80\x01" + _u16(seq) + marshal_datagram(
        [clock_sync, ack, piggyback]
    )


def ack_window_first(ack_last: int, datagrams_seen: int, window: int = ACK_WINDOW) -> int:
    """First envelope sequence of the continuous ACK range.

    Sliding, not pinned: while the session is younger than ``window`` this is the session's
    first sequence (the strongest true claim), and after that it advances so the range never
    exceeds ``window``. See ACK_WINDOW for the measured reason a pinned range breaks the
    client at 32768.

    The subtraction is done in 16-bit wrap space, so it stays correct after the envelope
    sequence wraps at 65536 - which a pinned range could not survive either.
    """
    width = max(1, min(datagrams_seen, window))
    return (ack_last - (width - 1)) & 0xFFFF


def ct_acks_datagram(seq: int, *, ack_first: int, ack_last: int) -> bytes:
    """Standalone CT_ACKS (sys6) so the client's reliable V3 is marked
    delivered. Without this, after the first RegistrationResponse the
    client retransmits ch0 1115B for ~10s then
    `@mm_csdkerr_disconnect (4)` (Game.log 2026-09-18 20:15:08→18)."""
    rec = MessageRecord(
        channel=3,
        payload=(
            bytes([0x40])
            + _u16(ack_last)
            + _u16(ack_first)
            + bytes([SystemMessageId.SM_CT_ACKS])
        ),
        sequence=0,
        reliable_sequence=0xFFFF,
        reliable=False,
        connecting=False,
        flags_override=0x20,
    )
    return b"\x80\x01" + _u16(seq) + marshal_datagram([rec])


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
    return b"\x80\x01" + _u16(seq) + marshal_datagram([rec])


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
        + _u16(env_seq)
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
    ack_allowed: bool = True,
    ack_first: int | None = None,
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
    client disconnected.

    ack_first: the first sequence of the CONTINUOUS ACK range. The caller supplies the sliding
    window (see ACK_WINDOW and `ack_window_first`); when omitted it falls back to
    `inbound_first`, which is what the tests and the one-shot plain server use.
    """
    from .javelin.lz4 import decompress_lz4_block

    if ack_first is None:
        ack_first = inbound_first

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
                ack_first=ack_first,
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
    # A record is a V3 registration only if it PARSES as one. The old test was
    # `channel == 0 and size > 64`, which also matched the client's ordinary ch0
    # game messages. Measured 2026-10-09 on a live session: of 17 ch0 records of
    # size 256, exactly 2 parsed as V3 (one per connection) while 15 were game
    # data — the same size. The server answered every one of them, so
    # `v3-registered` fired ~8 times while the client logged "received
    # registration response from REP" only twice, once per real connection.
    # Answering a registration the client never sent makes it restart transport
    # handling it is already past, and the client showed continuous
    # OnLocalNetworkConnectionWarning until the transport dropped at ~35 s.
    v3_records = []
    for rec in result.messages:
        if rec.channel != 0 or rec.size <= 64:
            continue
        try:
            parse_v3_request_or_lenient(rec.payload)
        except ValueError:
            continue
        v3_records.append(rec)
    if v3_records and (not v3_done or time.monotonic() - v3_last_reply > 5.0):
        # V3 registration: extract session_uuid and echo it as the session
        # token (first-light doc: "the 32-char hex form of the client's
        # session_uuid echoed back" — the client stores it via vtable+0x110).
        session_token = None
        try:
            req = parse_v3_request_or_lenient(v3_records[0].payload)
            if req.session_uuid:
                session_token = req.session_uuid.replace("-", "").encode("ascii")
        except ValueError:
            pass
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
    if needs_ack and ack_allowed:
        # ACK data envelopes so reliable V3 retries stop. Do not ACK
        # the client's own CT_ACKS/CLOCK_SYNC or we loop (seq 500 in
        # 40s, live 2026-09-18 20:20). Empty replies after v3_done
        # used to let ClientSDK hit disconnect (4) at 10s.
        #
        # ack_allowed coalesces these. The 0x40 form already covers a RANGE
        # (ack_first..ack_last), so one datagram per window conveys the same
        # information as one per inbound datagram. Measured 2026-10-09: the
        # uncoalesced 1:1 reply made the server answer 286 datagrams in one
        # second for 185 inbound, the client stalled under the flood, stopped
        # sending, and its ClientSDK dropped the transport at 10 s of silence
        # (`transportError 4`). See ACK_COALESCE_S.
        replies.append(
            ct_acks_datagram(
                client_env_seq,
                ack_first=ack_first,
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
        # Monotonic count of inbound datagrams. The ACK window is expressed as a count rather
        # than as a difference of wire sequences so it stays correct across the 16-bit wrap
        # (see ACK_WINDOW).
        self.inbound_count = 0
        # Inbound typed-request dispatcher (see INBOUND_* above).
        # type_id -> {count, first_ts, last_ts, target, params} for the requests we know, and
        # type_id -> count for anything else typed.
        self.inbound_requests: dict[int, dict] = {}
        # The TimeComponent client facet's local id, learned from the client's OWN 0x1098
        # request, so the 0x1096/0x1097 reply is addressed by the client instead of by a guess.
        self.time_facet_target: bytes | None = None
        # Per-request answer pacing and counters.
        self.inbound_answer_next_at: dict[int, float] = {}
        self.inbound_answers_sent = 0
        self.inbound_answers_suppressed = 0
        self.v3_responded = False  # V3 response has been sent at least once
        self.v3_session_uuid = ""
        self.v3_character_id = ""
        self.v3_persona_id = ""
        self.v3_first_time = 0.0  # monotonic timestamp of first V3 response
        self.v3_last_time = 0.0  # monotonic timestamp of the LAST V3 response
        self.next_out_seq = 1  # envelope seq for unsolicited server datagrams
        self.post_v3_sent = False  # post-V3 flight sent
        self.last_keepalive = 0.0
        # Captured-official-login replay state (see REPLAY_* above).
        self.replay_queue: list = []
        self.replay_split_done = False
        self.replay_next_at = 0.0
        self.out_msg_seq = 0
        self.out_rel_seq = 0
        # Reliable retransmission (2026-09-19 InGame-era fix): the client
        # drops ~40% of the replay burst while loading (decoded CT_ACKS
        # bitmaps) and GridMate reliable delivery requires the SENDER to
        # resend lost datagrams. Track them until acked.
        self.sent_reliable: dict[int, tuple[float, bytes]] = {}
        self.resend_tries: dict[int, int] = {}
        # Counts transmissions in the post-replay window, not skips — a
        # rate-limit skip must not feed REPLAY_RESEND_LIMIT.
        self.resend_window_start = 0.0
        self.resend_window_count = 0
        self.last_resend_pump = 0.0
        self.last_ack_at = 0.0
        self.acked_seqs: set[int] = set()
        self.greetings_after_replay = False
        # Post-replay 0x15d ping/pong (see HEARTBEAT_* above).
        self.heartbeat_next_at = 0.0
        self.heartbeat_tick = HEARTBEAT_TICK_START
        # Post-replay 0x1b88 activity stream (see ACTIVITY_STREAM_* above).
        self.activity_body: bytes | None = None
        self.activity_next_at = 0.0
        self.activity_sent = 0
        # Post-replay 0x08 state-bundle stream (see STATE_STREAM_* above).
        # Client-facet responses held until the replay drains, so they land after the client
        # has built its object graph (see REPLAY_DEFER_CLIENT_FACETS above).
        self.deferred_replay: list = []
        self.deferred_replay_sent = 0
        self.deferred_replay_dropped = 0
        self.defer_deadline: float | None = None
        self.request_coverage_logged = False
        # The captured contracts reply, kept so the dispatcher can answer EVERY time the client
        # asks rather than once per session (see DISPATCHER_OWNED_RESPONSES).
        self.contracts_response = None
        self.replay_dropped_unreceivable = 0
        self.state_stream_all: list = []
        self.state_stream_queue: list = []
        self.state_stream_player: list = []
        self.state_stream_player_queue: list = []
        self.state_stream_next_at = 0.0
        self.state_stream_player_next_at = 0.0
        self.state_stream_player_sent = 0
        self.state_stream_sent = 0
        self.state_stream_seq = 0
        # Post-replay 0x1096/0x1097 input-response stream (see INPUT_RESPONSE_*).
        self.input_response_msgs: list = []
        self.input_response_next_at = 0.0
        self.input_response_sent = 0
        # Latest channel-1 client body, captured for the experimental echo.
        self.channel1_last_body: bytes | None = None
        self.channel1_echo_next_at = 0.0
        self.channel1_echo_sent = 0
        # Experimental typed position reply (see POSITION_REPLY_* above).
        self.position_reply_next_at = 0.0
        self.position_reply_sent = 0
        # Experimental StartMovementCommunicationMsg, sent once before the first
        # position reply (see START_MOVEMENT_* above).
        self.start_movement_sent = 0
        # The 16-byte actor id parsed out of the client's own channel-1 record, so the
        # reply addresses the actor the client is actually talking about.
        self.client_actor_id: bytes | None = None

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
        # Envelope 0x81 is LZ4-compressed (handle_app_data decompresses it too).
        # The raw body is NOT a record stream, so parsing it directly yielded
        # garbage: on 2026-10-11 a compressed client datagram decoded a bogus
        # channel 4, raised IndexError inside parse_datagram, and the UDP loop's
        # feed-error handler dropped the peer — the client then logged
        # `transportError 4`. Decompress before the Carrier parse so the ACK
        # decode and the channel-1 capture below see the client's real records.
        if inbound_env.is_compressed:
            from .javelin.lz4 import decompress_lz4_block

            try:
                inbound_body = decompress_lz4_block(inbound_body)
            except ValueError:
                inbound_body = b""
        event = describe_datagram(app)
        event.update(event="app-data", peer=f"{self.peer[0]}:{self.peer[1]}")
        # Full plaintext hex (no truncation): the V3 request (~832B) and
        # 0x81 LZ4 bodies (~269B) do not fit in 96 bytes; truncated logs
        # made them undecodable (2026-09-17).
        event["raw_full"] = app.hex()
        log_event(event)
        if self.inbound_first is None:
            self.inbound_first = inbound_env.sequence
        self.inbound_count += 1
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
        self._note_inbound_typed(inbound_recs)
        if INBOUND_DISPATCH_ENABLED:
            self._dispatch_inbound(server, inbound_recs)
        self._process_acks(inbound_recs)
        if CHANNEL1_ECHO_ENABLED:
            # Keep the most recent client player-state body so the echo sends
            # real client bytes, not a synthesised one.
            for rec in inbound_recs:
                if (
                    rec.channel == 1
                    and rec.payload
                    and 0 < len(rec.payload) <= CHANNEL1_ECHO_MAX_BODY
                ):
                    self.channel1_last_body = rec.payload
                    # The client's channel-1 body carries its actor id at offset 8
                    # (measured: [hash4][0000][0x6f][16-byte entity UUID]...). Keep it
                    # so a position reply can address the same actor.
                    if len(rec.payload) >= 24:
                        self.client_actor_id = bytes(rec.payload[8:24])
        # describe_datagram() already transparently decompresses envelope
        # 0x81, which the raw Carrier parse above cannot do. Use its decoded
        # identity so compressed live V3 retries can key replay remapping.
        v3_event = event.get("v3")
        if isinstance(v3_event, dict) and v3_event.get("session_uuid"):
            session_uuid = str(v3_event["session_uuid"])
            if self.v3_session_uuid and session_uuid != self.v3_session_uuid:
                log_event(
                    {
                        "event": "v3-session-conflict",
                        "peer": f"{self.peer[0]}:{self.peer[1]}",
                        "kept": self.v3_session_uuid,
                        "ignored": session_uuid,
                    }
                )
            else:
                self.v3_session_uuid = session_uuid
                self.v3_character_id = str(v3_event.get("character_id") or "")
                self.v3_persona_id = str(v3_event.get("persona_id") or "")
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
        # Coalesce ACKs by time (see ACK_COALESCE_S). This pump runs once per
        # inbound datagram, so an unconditional ACK reply is 1:1 with client
        # traffic and floods a client that is already busy.
        ack_now = time.monotonic()
        ack_allowed = ack_now - self.last_ack_at >= ACK_COALESCE_S
        if ack_allowed:
            self.last_ack_at = ack_now
        for reply in handle_app_data(
            app,
            inbound_env.sequence,
            handshake_done=self.carrier_connected,
            inbound_first=self.inbound_first,
            v3_done=self.v3_responded,
            v3_last_reply=self.v3_last_time,
            ack_allowed=ack_allowed,
            ack_first=ack_window_first(inbound_env.sequence, self.inbound_count),
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
        # Everything periodic is emitted by tick(), not here: on_app_data is the
        # REACTIVE path (handshake replies, ACKs, the V3 answer) and must not
        # drive the server's output rate. See PeerSession.tick().

    def tick(self, server) -> None:
        """Emit everything that is due on the server's own clock.

        This is the authoritative tick: it runs from the UDP loop on a fixed
        cadence (TICK_INTERVAL_S) whether or not a datagram arrived, so
        emission is decoupled from inbound traffic. Each emitter gates itself
        on its own `_next_at`, so calling this more often than needed costs a
        few comparisons and emits nothing extra.

        Before this existed, the periodic emitters were called from
        on_app_data, which made the server's output rate proportional to the
        client's input rate (measured Pearson 0.995) and made the replay stop
        when the client went quiet. Reactive work — handshake replies, ACKs,
        the V3 answer — stays in on_app_data, because that genuinely is a
        response to an inbound datagram.
        """
        if self.gone:
            return
        self.maybe_keepalive(server)
        self.maybe_send_post_v3(server)
        self.maybe_inject(server)
        self.maybe_pump_replay(server)
        self.maybe_pump_deferred(server)
        self.maybe_heartbeat(server)
        self.maybe_activity_stream(server)
        self.maybe_state_stream(server)
        self.maybe_input_response(server)
        self.maybe_channel1_echo(server)
        self.maybe_position_reply(server)
        now_mono = time.monotonic()
        if now_mono - self.last_resend_pump >= RESEND_PUMP_MIN_INTERVAL_S:
            self.last_resend_pump = now_mono
            self.maybe_resend(server)

    def _arm_replay(self) -> None:
        if not REPLAY_ENABLED:
            return
        try:
            store = replay_store()
        except Exception as exc:  # noqa: BLE001
            log_event({"event": "replay-load-error", "error": str(exc)[:200]})
            return
        armed = store.replay_messages_after_v3(
            REPLAY_MAX_SEQ, include_redacted=True
        )
        # The dispatcher OWNS some responses: it sends them when the client asks, so the replay
        # must not also send them once and forget. Filtering here rather than inside
        # `_partition_replay` keeps that function's contract (now / defer / drop) unchanged, and
        # keeps the captured body so the answer is the real one.
        if INBOUND_DISPATCH_ENABLED:
            owned = [m for m in armed if m.type_id in DISPATCHER_OWNED_RESPONSES]
            if owned:
                armed = [m for m in armed if m.type_id not in DISPATCHER_OWNED_RESPONSES]
                self.contracts_response = next(
                    (m for m in owned if m.type_id == CONTRACTS_LOOKUP_RESPONSE), None
                )
                log_event(
                    {
                        "event": "inbound-dispatcher-owned",
                        "types": sorted({hex(m.type_id) for m in owned}),
                        "count": len(owned),
                        "requests": sorted(
                            hex(t) for t in INBOUND_KNOWN_REQUESTS
                            if t in (CONTRACTS_LOOKUP_REQUEST, TIME_SYNC_REQUEST)
                        ),
                    }
                )
        self.replay_queue, self.deferred_replay, dropped = _partition_replay(armed)
        self.replay_dropped_unreceivable = len(dropped)
        self.defer_deadline = None
        self.request_coverage_logged = False
        if dropped or self.deferred_replay:
            log_event(
                {
                    "event": "replay-response-scheduling",
                    "request_gating": REPLAY_REQUEST_GATING,
                    "dropped_unreceivable": len(dropped),
                    "dropped_types": sorted({hex(m.type_id) for m in dropped}),
                    "deferred": len(self.deferred_replay),
                    "deferred_types": sorted({hex(m.type_id) for m in self.deferred_replay}),
                    "absent_facet": sorted({hex(t) for t in ABSENT_FACET_RESPONSES}),
                }
            )
        self.out_msg_seq = 1
        self.out_rel_seq = 1
        self.replay_next_at = time.monotonic()
        log_event({"event": "replay-armed", "count": len(self.replay_queue)})
        if ACTIVITY_STREAM_ENABLED:
            copies = [
                m
                for m in store.messages
                if m.type_id == ACTIVITY_STREAM_TYPE
                and m.direction == "R"
                and not m.has_redaction
            ]
            # All 23 captured copies are byte-identical; keep one body and
            # send it verbatim with a fresh envelope seq each time.
            self.activity_body = copies[0].body if copies else None
            log_event(
                {
                    "event": "activity-stream-armed",
                    "copies": len(copies),
                    "body_len": len(self.activity_body) if self.activity_body else 0,
                }
            )
        if STATE_STREAM_ENABLED:
            self.state_stream_all = [
                m
                for m in store.replay_messages_after_v3(
                    REPLAY_MAX_SEQ, include_redacted=True
                )
                if m.type_id == 0x08
                and m.seq >= STATE_STREAM_MIN_SEQ
                and _state_stream_selected(m)
            ]
            self.state_stream_queue = list(self.state_stream_all)
            self.state_stream_player = [
                m for m in self.state_stream_all
                if _state_stream_record_id(m) == STATE_STREAM_PLAYER_RECORD
            ]
            self.state_stream_player_queue = list(self.state_stream_player)
            highest = 0
            for msg in self.state_stream_all:
                # The counter the client's replication gate compares is the
                # record-id varint, not a raw byte. Read it through the
                # verified parser so a multi-byte value cannot be misread.
                try:
                    highest = max(
                        highest,
                        javelin_bundle.decode_bundle(msg.body).replication_seq,
                    )
                except javelin_bundle.BundleError:
                    continue
            self.state_stream_seq = max(highest + 1, STATE_STREAM_SEQ_FLOOR)
            log_event(
                {
                    "event": "state-stream-armed",
                    "count": len(self.state_stream_all),
                    "seqs": [hex(m.seq) for m in self.state_stream_all],
                    "period_s": STATE_STREAM_PERIOD_S,
                    "only_record": STATE_STREAM_ONLY_RECORD,
                    "player_record": STATE_STREAM_PLAYER_RECORD,
                    "player_bundles": len(self.state_stream_player),
                    "player_period_s": STATE_STREAM_PLAYER_PERIOD_S,
                    "loop": True,
                    "rewrite_seq": STATE_STREAM_REWRITE_SEQ,
                    "seq_base": self.state_stream_seq,
                }
            )
        if INPUT_RESPONSE_ENABLED:
            self.input_response_msgs = [
                m
                for m in store.messages
                if m.type_id in INPUT_RESPONSE_TYPES and m.direction == "R"
            ]
            log_event(
                {
                    "event": "input-response-armed",
                    "count": len(self.input_response_msgs),
                    "types": [hex(m.type_id) for m in self.input_response_msgs],
                    "period_s": INPUT_RESPONSE_PERIOD_S,
                }
            )

    def maybe_pump_replay(self, server) -> None:
        """Send the next captured R-message (official login replay)."""
        if not self.replay_queue or self.gone:
            return
        now = time.monotonic()
        if now < self.replay_next_at:
            return
        if (
            REPLAY_SPLIT_SEQ
            and not self.replay_split_done
            and self.replay_queue
            and self.replay_queue[0].seq >= REPLAY_SPLIT_SEQ
        ):
            self.replay_split_done = True
            self.replay_next_at = now + REPLAY_SPLIT_DELAY_S
            log_event(
                {
                    "event": "replay-split-wait",
                    "next_seq": self.replay_queue[0].seq,
                    "delay_s": REPLAY_SPLIT_DELAY_S,
                }
            )
            return
        msg = self.replay_queue.pop(0)
        if REPLAY_IDENTITY_REMAP != "off":
            from .javelin.replay_store import remap_replay_identity

            remapped = remap_replay_identity(
                msg,
                selector=REPLAY_IDENTITY_REMAP,
                session_uuid=self.v3_session_uuid,
                character_id=self.v3_character_id,
            )
            if remapped is not msg:
                log_event(
                    {
                        "event": "replay-identity-remap",
                        "seq": msg.seq,
                        "type": hex(msg.type_id),
                        "selector": REPLAY_IDENTITY_REMAP,
                    }
                )
                msg = remapped
        if REPLAY_SELFIDENT_GUID != "off":
            from .javelin.replay_store import remap_selfident_guid

            remapped = remap_selfident_guid(
                msg,
                selector=REPLAY_SELFIDENT_GUID,
                session_uuid=self.v3_session_uuid,
                character_id=self.v3_character_id,
            )
            if remapped is not msg:
                log_event(
                    {
                        "event": "replay-selfident-guid-remap",
                        "seq": msg.seq,
                        "type": hex(msg.type_id),
                        "selector": REPLAY_SELFIDENT_GUID,
                    }
                )
                msg = remapped
        if REPLAY_FRESH_LEVELINFO != "off":
            from .javelin.replay_store import remap_fresh_levelinfo_key

            remapped = remap_fresh_levelinfo_key(
                msg,
                selector=REPLAY_FRESH_LEVELINFO,
                session_uuid=self.v3_session_uuid,
                character_id=self.v3_character_id,
            )
            if remapped is not msg:
                log_event(
                    {
                        "event": "replay-fresh-levelinfo-remap",
                        "seq": msg.seq,
                        "type": hex(msg.type_id),
                        "selector": REPLAY_FRESH_LEVELINFO,
                    }
                )
                msg = remapped
        if REPLAY_SPAN_SUBSTITUTION != "off":
            from .javelin.replay_store import apply_span_substitution

            remapped = apply_span_substitution(
                msg,
                selector=REPLAY_SPAN_SUBSTITUTION,
                session_uuid=self.v3_session_uuid,
                character_id=self.v3_character_id,
                persona_id=self.v3_persona_id,
                display_name=REPLAY_SPAN_DISPLAY_NAME,
                seqs=REPLAY_SPAN_SEQS,
                lengths=REPLAY_SPAN_LENGTHS,
            )
            if remapped is not msg:
                log_event(
                    {
                        "event": "replay-span-substitution",
                        "seq": msg.seq,
                        "type": hex(msg.type_id),
                        "selector": REPLAY_SPAN_SUBSTITUTION,
                        "spans": remapped.substituted_spans,
                        "spans_total": len(msg.redacted_spans),
                        "pass": 1,
                    }
                )
                msg = remapped
        if REPLAY_SPAN_SUBSTITUTION2 != "off":
            from .javelin.replay_store import apply_span_substitution

            remapped = apply_span_substitution(
                msg,
                selector=REPLAY_SPAN_SUBSTITUTION2,
                session_uuid=self.v3_session_uuid,
                character_id=self.v3_character_id,
                persona_id=self.v3_persona_id,
                display_name=REPLAY_SPAN_DISPLAY_NAME,
                seqs=REPLAY_SPAN_SEQS2,
                lengths=REPLAY_SPAN_LENGTHS2,
            )
            if remapped is not msg:
                log_event(
                    {
                        "event": "replay-span-substitution",
                        "seq": msg.seq,
                        "type": hex(msg.type_id),
                        "selector": REPLAY_SPAN_SUBSTITUTION2,
                        "spans": remapped.substituted_spans,
                        "spans_total": len(msg.redacted_spans),
                        "pass": 2,
                    }
                )
                msg = remapped
        if REPLAY_LOCAL_PLAYER_UUID != "off":
            from .javelin.replay_store import fill_local_player_uuid

            remapped = fill_local_player_uuid(
                msg,
                selector=REPLAY_LOCAL_PLAYER_UUID,
                character_id=self.v3_character_id,
                session_uuid=self.v3_session_uuid,
                seqs=REPLAY_LOCAL_PLAYER_UUID_SEQS,
            )
            if remapped is not msg:
                log_event(
                    {
                        "event": "replay-local-player-uuid",
                        "seq": msg.seq,
                        "type": hex(msg.type_id),
                        "selector": REPLAY_LOCAL_PLAYER_UUID,
                        "spans": remapped.substituted_spans,
                        "spans_total": len(msg.redacted_spans),
                    }
                )
                msg = remapped
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
            # The capture stops here, but the official server did not: it kept
            # pinging 0x15d every ~1 s. Start the continuation so the client's
            # state watchdog sees progress instead of silence.
            self.heartbeat_next_at = time.monotonic()
        self.replay_next_at = now + REPLAY_INTERVAL_S

    def _post_replay_started(self) -> bool:
        """True once the post-V3 flight has gone out.

        This deliberately does NOT require the replay queue to be empty. The
        emitters that keep the client's InGame activity clock alive
        (heartbeat, input-response, activity stream) used to wait for the
        replay to drain, and measured 2026-10-10 that is fatal: the replay is
        ~1090 chunks (24 of the captured bodies are 46 KB), so at the
        recommended AZOTH_CHUNK_GAP_MS=20 it needs ~22 s, while the client's
        watchdog tears the connection down at ~27 s of not receiving an
        expected message. In that run the log contained ZERO `heartbeat` and
        ZERO `input-response` events for the whole session, the client's
        OnLocalNetworkConnectionWarning climbed to 22, and the transport
        dropped with `transportError 4` at 00:30:14Z, 27 s after the spawn at
        00:29:47Z.

        The real server pings while it streams, so running these concurrently
        with the replay is what the capture shows.

        REGRESSION, measured 2026-10-10 on a live run (this predicate used to
        return `self.greetings_after_replay`, which is NOT "the post-V3 flight
        went out"): that flag is only set when the replay queue drains, so the
        concurrency fix above was a silent no-op and the failure returned. The
        run logged replay-chunk 19:30:40Z..19:31:09Z (29 s), `replay-complete-
        quiet` at 19:31:09Z, and the FIRST heartbeat at 19:31:09Z -- i.e. not
        one ping for the whole replay window -- while the client's
        OnLocalNetworkConnectionWarning burst 1 -> 104 between 19:30:44Z and
        19:31:07Z. The honest predicate is `v3_responded`: the V3 registration
        has been answered, so the flight is out and the state watchdog is
        armed. `greetings_after_replay` keeps its real meaning and is still
        used by `maybe_state_stream`, which MUST wait for the drain.
        """
        return self.v3_responded

    def _note_inbound_typed(self, records) -> None:
        """Log each distinct typed message the CLIENT sends, once per session.

        WHY THIS EXISTS: there is no inbound typed-message dispatcher at all, so every request
        the client makes is acknowledged at the transport level and then ignored, and nothing
        in the logs said so. Measured 2026-10-13: a session's client sent **43 distinct request
        types** and the server answered none of them. Logging the first occurrence of each
        (channel, type) pair makes that visible in every future session at a cost of at most a
        few dozen lines, without flooding the log with the 14k channel-1 input records.

        The type id is logged raw; `scripts/inbound-inventory.py` names them from the same
        derived table the analysis uses, so the server does not need to carry a name table.
        """
        seen = getattr(self, "inbound_types_seen", None)
        if seen is None:
            seen = set()
            self.inbound_types_seen = seen
        for rec in records:
            payload = getattr(rec, "payload", b"")
            # The client's own container is `[u32 crc32][u32 len][16-byte target][00 01][type]`,
            # so its typed marker sits at offset 24; the server's form has it at 0. Try both.
            type_id = None
            for offset in (0, 24):
                try:
                    type_id, _ = javelin_bundle.read_type_marker(payload[offset:])
                except Exception:
                    continue
                break
            if type_id is None:
                continue
            key = (rec.channel, type_id)
            if key in seen:
                continue
            seen.add(key)
            log_event(
                {
                    "event": "inbound-typed",
                    "channel": rec.channel,
                    "type": hex(type_id),
                    "type_dec": type_id,
                    "size": getattr(rec, "size", len(payload)),
                }
            )

    def _dispatch_inbound(self, server, records) -> None:
        """Decode the client's typed requests and act on the ones we handle.

        The receive half of the contract. Until 2026-10-14 the server had NO inbound typed
        dispatcher, so every request was acknowledged at the transport level and then ignored,
        with nothing in any log saying so (measured: 19 requests in a short session, 29 in a
        richer one).

        Two things happen here, deliberately separable:

        * every KNOWN request type gets its target and params recorded once per session, so the
          actual wire shape of a request is in the log next to its name instead of nothing;
        * the requests we can ACT on are acted on. `0x1098` hands us the TimeComponent client
          facet's local id - the exact address its `0x1096/0x1097` reply needs - and `0x09FC`
          is queued for the captured contracts answer, every time it is asked rather than once
          per session.

        Answering happens inline because this genuinely is a response to an inbound datagram;
        the periodic emitters stay in the tick (see `tick`).
        """
        for rec in records:
            if rec.channel != 0:
                continue
            req = parse_inbound_request(rec.payload, rec.channel)
            if req is None:
                continue
            state = self.inbound_requests.get(req.type_id)
            if state is None:
                state = {
                    "count": 0,
                    "known": req.type_id in INBOUND_KNOWN_REQUESTS,
                    "target": None,
                    "params_len": len(req.params),
                }
                self.inbound_requests[req.type_id] = state
                # Log the shape once per session, and only for the types we recognise: the
                # unnamed runtime-registered types have no schema to check against yet.
                if state["known"]:
                    log_event(
                        {
                            "event": "inbound-request-shape",
                            "type": hex(req.type_id),
                            "name": INBOUND_KNOWN_REQUESTS[req.type_id],
                            "size": req.size,
                            "target": req.target.hex() if req.target else None,
                            "params_len": len(req.params),
                            "params_head": req.params[:24].hex(),
                        }
                    )
            state["count"] += 1
            if req.target is not None:
                state["target"] = req.target.hex()

            if req.type_id == TIME_SYNC_REQUEST and req.target is not None:
                # The client just told us where its time facet lives. Prefer this over the
                # captured id and over the file lever: it is per-session and authoritative.
                if self.time_facet_target != req.target:
                    self.time_facet_target = req.target
                    log_event(
                        {
                            "event": "inbound-time-target-learned",
                            "target": req.target.hex(),
                            "serves": [hex(t) for t in TIME_SYNC_REPLIES],
                        }
                    )
            elif req.type_id == CONTRACTS_LOOKUP_REQUEST:
                self._answer_contracts_lookup(server, req)

    def _answer_contracts_lookup(self, server, req: InboundRequest) -> None:
        """Answer `LookupContractsByParticipant` with the captured contracts reply.

        The client asks for contracts 2x in a measured session and the replay answers exactly
        once, ever, because it sends each captured body a single time. This answers every time.
        The captured body's target was measured to be byte-for-byte the target of the request
        that asks for it, so no retargeting is needed; it is asserted rather than assumed, and a
        mismatch is logged and left alone instead of being sent to the wrong facet.
        """
        if not INBOUND_DISPATCH_ENABLED or self.contracts_response is None:
            return
        now = time.monotonic()
        if now < self.inbound_answer_next_at.get(req.type_id, 0.0):
            self.inbound_answers_suppressed += 1
            return
        body = self.contracts_response.body
        sent = body
        if req.target is not None:
            start = len(body)
            try:
                _type_id, start = javelin_bundle.read_type_marker(body)
            except Exception:
                start = -1
            if start >= 0 and len(body) >= start + REQUEST_TARGET_PREFIX:
                captured = body[start : start + REQUEST_TARGET_PREFIX]
                if captured != req.target:
                    log_event(
                        {
                            "event": "inbound-answer-target-mismatch",
                            "type": hex(self.contracts_response.type_id),
                            "captured": captured.hex(),
                            "request": req.target.hex(),
                        }
                    )
                else:
                    sent = body
        self.inbound_answer_next_at[req.type_id] = now + INBOUND_ANSWER_MIN_INTERVAL_S
        self._send_replay_message(server, replace(self.contracts_response, body=sent))
        self.inbound_answers_sent += 1
        log_event(
            {
                "event": "inbound-answer",
                "request": hex(req.type_id),
                "response": hex(self.contracts_response.type_id),
                "size": len(sent),
                "n": self.inbound_answers_sent,
            }
        )

    def maybe_pump_deferred(self, server) -> None:
        """Decide each held client-facet response once the client's object graph exists.

        The replay drains ~8 s AFTER the client reports spawn (measured 2026-10-13), which is
        exactly when the client's facets exist; sending these in the pre-spawn burst is what
        produced 29 `facet target ID couldn't be found` errors in one millisecond. From then on
        each held message is decided by `_deferred_decision`, so a response whose request the
        client never sent is dropped instead of aimed at a target that does not exist, and a
        response whose request it did send goes out. Request-gated messages wait up to
        DEFER_DECISION_TIMEOUT_S for a late request before being given up on.
        """
        if not self.deferred_replay or self.gone or not self.v3_responded:
            return
        if self.replay_queue or not self.greetings_after_replay:
            return  # the client's object graph is not built yet
        now = time.monotonic()
        if self.defer_deadline is None:
            self.defer_deadline = now + DEFER_DECISION_TIMEOUT_S
            log_event(
                {
                    "event": "replay-defer-start",
                    "held": len(self.deferred_replay),
                    "types": sorted({hex(m.type_id) for m in self.deferred_replay}),
                    "request_gating": REPLAY_REQUEST_GATING,
                    "deadline_s": DEFER_DECISION_TIMEOUT_S,
                }
            )
        raw_seen = getattr(self, "inbound_types_seen", set())
        seen = {t for (_channel, t) in raw_seen}
        held: list = []
        for msg in self.deferred_replay:
            verdict = _deferred_decision(msg, seen, now=now, deadline=self.defer_deadline)
            if verdict == "hold":
                held.append(msg)
                continue
            if verdict == "drop":
                required = RESPONSE_REQUESTS.get(msg.type_id, ())
                self.deferred_replay_dropped += 1
                log_event(
                    {
                        "event": "replay-response-suppressed",
                        "seq": hex(msg.seq),
                        "type": hex(msg.type_id),
                        "name": DEFERRED_RESPONSE_TYPES.get(msg.type_id, "?"),
                        "required_requests": [hex(r) for r in required],
                        "reason": "request-not-seen" if required else "facet-absent",
                        "n": self.deferred_replay_dropped,
                    }
                )
                continue
            self._send_replay_message(server, msg)
            self.deferred_replay_sent += 1
            log_event(
                {
                    "event": "replay-deferred-sent",
                    "seq": hex(msg.seq),
                    "type": hex(msg.type_id),
                    "name": DEFERRED_RESPONSE_TYPES.get(msg.type_id, "?"),
                    "n": self.deferred_replay_sent,
                }
            )
        self.deferred_replay = held
        if not held:
            self._log_request_coverage(raw_seen)

    def _log_request_coverage(self, seen: set[tuple[int, int]]) -> None:
        """One line per session: what the client asked for vs what our replay can answer.

        `seen` is the set of (channel, type) pairs the client has sent. This is the inbound
        half of the contract made visible. There is still no inbound typed dispatcher, so a
        request in `no_replay_response` is one the client is waiting on and the server
        currently ignores; the line makes that measurable per session instead of invisible.
        It is a report, not a verdict: many `*ServerFacet_*` messages are setters answered by
        replicated state rather than by a typed reply.
        """
        if self.request_coverage_logged:
            return
        self.request_coverage_logged = True
        answerable = {r for reqs in RESPONSE_REQUESTS.values() for r in reqs}
        requests = {t for (ch, t) in seen if _counts_as_request(ch, t)}
        log_event(
            {
                "event": "inbound-request-coverage",
                "inbound_types": len(seen),
                "request_types": len(requests),
                "answerable_by_replay": sorted(hex(t) for t in requests if t in answerable),
                "no_replay_response": sorted(hex(t) for t in requests if t not in answerable),
                "deferred_sent": self.deferred_replay_sent,
                "deferred_dropped": self.deferred_replay_dropped,
            }
        )

    def maybe_heartbeat(self, server) -> None:
        """Continue the captured 0x15d ping/pong once the replay is drained.

        The official stream ends at seq 0xb0 and the server then goes quiet;
        the client's state watchdog (FUN_146445e10) counts intervals with no
        expected message and tears the connection down with
        `State(InGame) is timeout` -> `connection_ingame_timeout` after ~44 s.
        The capture shows the real server pinging 0x15d every ~1 s and the
        client echoing it, so we keep that exchange going.
        """
        if not HEARTBEAT_ENABLED or self.gone or not self.v3_responded:
            return
        if not self._post_replay_started():
            return  # the replay itself still carries the captured pings
        now = time.monotonic()
        if now < self.heartbeat_next_at:
            return
        self.heartbeat_next_at = now + HEARTBEAT_PERIOD_S
        self.heartbeat_tick += HEARTBEAT_TICK_STEP
        from .javelin.wire import encode_vlq32

        body = heartbeat_body(self.heartbeat_tick)
        inner = encode_vlq32(len(body)) + body
        seq = self.out_msg_seq
        self.out_msg_seq = (seq + 1) & 0xFFFF
        rel = self.out_rel_seq
        self.out_rel_seq = (rel + 1) & 0xFFFF
        rec = MessageRecord(
            channel=0,
            payload=inner,
            sequence=seq,
            reliable_sequence=rel,
            reliable=True,  # the official 0x15d stream is RELIABLE (the
            # capture's R-direction pings arrive in order and the client
            # advances its state on them; flags 0x20 made the client drop
            # every post-replay heartbeat silently, 2026-09-30).
            connecting=False,
            flags_override=0x21,  # RELIABLE | DATA_CHANNEL, like the replay
        )
        # Not tracked for retransmission: see _send_datagram(track_reliable).
        self._send_datagram(server, [rec], track_reliable=False)
        log_event(
            {
                "event": "heartbeat",
                "tick": hex(self.heartbeat_tick),
                "out_seq": seq,
            }
        )

    def maybe_activity_stream(self, server) -> None:
        """Serve the captured 0x1b88 body periodically once the replay drains.

        Replay the historical 0x1b88 A/B as an opt-in wire experiment. Its
        temporary session improvement did not prove a stable user-visible
        connection: later ALC tracing still found the connection pointer
        closed and the HUD response stamp stale. It does not clear the cable
        or establish movement; see the dated evidence in
        research/atlas/client-functions.json. The 42-byte body is captured
        verbatim; only the Carrier envelope seq is fresh.
        """
        if not ACTIVITY_STREAM_ENABLED or self.activity_body is None:
            return
        if self.gone or not self.v3_responded:
            return
        if not self._post_replay_started():
            return  # the replay itself is still streaming
        now = time.monotonic()
        if now < self.activity_next_at:
            return
        self.activity_next_at = now + ACTIVITY_STREAM_PERIOD_S
        from types import SimpleNamespace

        msg = SimpleNamespace(
            seq=-1,  # marker: not a captured replay seq, keeps the dup-levelinfo skip inert
            type_id=ACTIVITY_STREAM_TYPE,
            body=self.activity_body,
        )
        self._send_replay_message(server, msg)
        self.activity_sent += 1
        log_event(
            {
                "event": "activity-stream",
                "type": hex(ACTIVITY_STREAM_TYPE),
                "size": len(self.activity_body),
                "n": self.activity_sent,
                "out_seq": (self.out_msg_seq - 1) & 0xFFFF,
            }
        )

    def maybe_state_stream(self, server) -> None:
        """Keep the captured 0x08 state flowing after the replay drains.

        The bodies are the captured ones, verbatim; only the replication counter and the
        outbound envelope seq are new.

        WHY THIS IS THE DEFAULT AND WHY IT MATTERS (measured 2026-10-13). The real server
        never stopped sending type-0x08 state; our replay stops at seq 0xb0. Two symptoms
        followed from that, and both are fixed by this method:

          * MOVEMENT: the client only simulates the local player while it is receiving the
            player's OWN state. With the stream off, the position sits at the historical
            constant (9343.6416, 2786.7327, 87.538) and W does nothing; with it on, W/S/A/D
            move the player in the correct directions.
          * THE RED HUD CABLE: the icon is a client-side age of the ALC local client's
            +0xAA8 stamp. The player's own state refreshes that stamp; nothing else we send
            does (measured: the 0x1096/0x1097 input response is delivered 828 times with the
            stamp frozen).

        THE RECORD THAT DOES IT is `record_id 1`, the local player's metadata slot, which in
        the capture lives only in the four 7154-byte bundles at seq 0x98/0x9A/0x9C/0x9E -
        all BELOW the old default floor of 0xA0. So the old default re-sent every other
        entity's state and never the player's. Hence the floor is 0x94, and the player's
        bundles additionally get their own faster timer (`STATE_STREAM_PLAYER_PERIOD_S`)
        because the cable only clears when the stamp is refreshed faster than its ~2 s amber
        threshold.

        This must wait for the replay to drain: it re-applies the same captured bundles the
        replay is still delivering, and double-applying state is not idempotent client-side.
        """
        if not STATE_STREAM_ENABLED or self.gone or not self.v3_responded:
            return
        # Unlike the heartbeat and input-response, this one MUST wait for the
        # replay to drain: it re-applies the same captured bundles the replay
        # is still delivering, and double-applying state is not idempotent
        # client-side (see the state-stream notes above).
        if self.replay_queue or not self.greetings_after_replay:
            return  # the replay itself still carries the captured bundles
        if not (self.state_stream_all or self.state_stream_queue
                or self.state_stream_player_queue):
            return
        now = time.monotonic()
        # Two rates, because the two kinds of state matter differently (measured):
        # the LOCAL PLAYER's own record has to keep the ALC stamp younger than the
        # cable's amber threshold (~2 s), while the rest of the world state only has
        # to keep flowing at roughly the rate the real server used.
        if self.state_stream_player_queue and now >= self.state_stream_player_next_at:
            self.state_stream_player_next_at = now + STATE_STREAM_PLAYER_PERIOD_S
            player_msg = self.state_stream_player_queue.pop(0)
            if not self.state_stream_player_queue:
                self.state_stream_player_queue = list(self.state_stream_player)
            self._send_state_bundle(server, player_msg, "player")
        if now < self.state_stream_next_at:
            return
        if not self.state_stream_queue:
            # The real server never stopped sending 0x08, so loop the captured
            # tail instead of going quiet after one pass.
            self.state_stream_queue = list(self.state_stream_all)
        self.state_stream_next_at = now + STATE_STREAM_PERIOD_S
        self._send_state_bundle(server, self.state_stream_queue.pop(0), "world")

    def _send_state_bundle(self, server, msg, kind: str) -> None:
        """Send one captured state bundle with a fresh, gate-passing counter.

        `kind` is "player" or "world" and is only used for the log, so an A/B can tell
        which of the two rates produced a given send.
        """
        self.state_stream_sent += 1
        if kind == "player":
            self.state_stream_player_sent += 1
        sent_seq = None
        if STATE_STREAM_REWRITE_SEQ:
            # Continue the counter above the client's high-water, or the bundle
            # is dropped by the replication gate as already seen.
            #
            # This MUST re-encode the field as a varint instead of overwriting
            # one raw byte. The counter is a prefix varint, so a value that
            # needs two bytes (0x80 and up) would otherwise shift the whole
            # fragment list and the client reports
            # `Failed to unmarshal ... ValidationError`. That is exactly the
            # failure DECOMP-BACKLOG section 12.3 measured and blamed on "any
            # write to body[4]": the old code wrote `self.state_stream_seq &
            # 0xFF`, and STATE_STREAM_SEQ_FLOOR defaulted to 0x80, whose high
            # bit turns a one-byte varint into a two-byte one.
            try:
                msg = replace(
                    msg,
                    body=javelin_bundle.with_replication_seq(
                        msg.body, self.state_stream_seq
                    ),
                )
            except javelin_bundle.BundleError as exc:
                log_event(
                    {
                        "event": "state-stream-seq-rewrite-failed",
                        "seq": hex(msg.seq),
                        "error": str(exc)[:160],
                    }
                )
            else:
                sent_seq = self.state_stream_seq
            self.state_stream_seq += 1
        self._send_replay_message(server, msg)
        log_event(
            {
                "event": "state-stream",
                "kind": kind,
                "seq": hex(msg.seq),
                "size": len(msg.body),
                "n": self.state_stream_sent,
                "wire_seq": sent_seq,
                "remaining": len(self.state_stream_queue),
            }
        )

    def maybe_input_response(self, server) -> None:
        """Keep answering the local player's input stream after the replay drains.

        See INPUT_RESPONSE_* above: the capture's server answers the client's
        0x635 burst with 0x1096/0x1097 (replay seq 0x75/0x76). Our replay sends
        them once, then the client HUD's "Time since last response" climbs.
        Re-send the captured bodies verbatim with fresh outbound seqs.
        """
        if not INPUT_RESPONSE_ENABLED or self.gone or not self.v3_responded:
            return
        if not self._post_replay_started():
            return  # let the replay itself deliver the captured copies first
        # MEASURED 2026-10-14, and it is the difference between the heartbeat and this: the
        # heartbeat is a TRANSPORT ping and must not wait for the replay (the client's watchdog
        # tears the connection down after ~27 s without one), but this is a CLIENT-FACET RMI
        # and the facet does not exist until the client is in the world. Sharing one predicate
        # sent the first input-response 1 s BEFORE `player spawn succeeds`, which is exactly the
        # two `TimeComponentClientFacet` dispatch failures a clean session still logged. The
        # replay drains ~8 s after spawn at the default pacing, so waiting for it is the
        # measured proxy for "the client's object graph is up".
        if not self.greetings_after_replay:
            return
        if not self.input_response_msgs:
            return
        now = time.monotonic()
        if now < self.input_response_next_at:
            return
        self.input_response_next_at = now + INPUT_RESPONSE_PERIOD_S
        # Address the reply from the client's OWN request when it has told us (measured: its
        # 0x1098 carries the TimeComponent client facet's local id). That beats both the captured
        # id and the file lever a Frida probe has to publish, because it is per-session and comes
        # from the authority on the question. The env/file lever remains the fallback.
        target = self.time_facet_target or _read_input_response_target()
        target_source = "client-request" if self.time_facet_target else "lever-or-captured"
        retargeted = 0
        for msg in self.input_response_msgs:
            if INPUT_RESPONSE_CONTAINER == "client":
                if self._send_input_response_client_container(server, msg, target):
                    retargeted += 1 if target is not None else 0
                    continue
                # fall through to the capture container if the body did not parse
            send = msg
            if target is not None:
                body = retarget_typed_body(msg.body, target)
                if body is not None:
                    send = replace(msg, body=body)
                    retargeted += 1
            self._send_replay_message(server, send)
            self.input_response_sent += 1
        log_event(
            {
                "event": "input-response",
                "sent": self.input_response_sent,
                "types": [hex(m.type_id) for m in self.input_response_msgs],
                "retargeted": retargeted,
                "target": target.hex() if target is not None else "captured",
                "target_source": target_source,
                "channel": INPUT_RESPONSE_CHANNEL,
                "container": INPUT_RESPONSE_CONTAINER,
            }
        )

    def _send_input_response_client_container(self, server, msg, target) -> bool:
        """Send one input response as the CLIENT's own channel-1 record form.

        `[u32 BE crc32][u32 BE len][16-byte target][00 01][type][payload]` on channel 1
        with flags 0x20 - the exact shape every client channel-1 record uses (measured
        9997/9997 in one session). The captured body is `[00 01][type][target][payload]`,
        so the type and payload are lifted out of it and re-framed with the target in
        front. Returns False (so the caller can fall back) if the body does not parse.
        """
        try:
            wire_type, offset = javelin_bundle.read_type_marker(msg.body)
        except Exception:
            return False
        if len(msg.body) < offset + 16:
            return False
        tgt = target if target is not None else msg.body[offset : offset + 16]
        payload = msg.body[offset + 16 :]
        inner = wrap_reply("client", tgt, wire_type, payload)
        seq = self.out_msg_seq
        self.out_msg_seq = (seq + 1) & 0xFFFF
        rel = self.out_rel_seq
        self.out_rel_seq = (rel + 1) & 0xFFFF
        rec = MessageRecord(
            channel=INPUT_RESPONSE_CHANNEL,
            payload=inner,
            sequence=seq,
            reliable_sequence=rel,
            reliable=False,
            connecting=False,
            flags_override=0x20,  # unreliable + DATA_CHANNEL, the client's own form
        )
        self._send_datagram(server, [rec])
        self.input_response_sent += 1
        return True

    def maybe_channel1_echo(self, server) -> None:
        """EXPERIMENTAL: echo the client's channel-1 player-state record back.

        See CHANNEL1_ECHO_* above. The capture has no server->client channel-1
        traffic, so this is a synthetic probe with real client bytes. Default
        off; enable with AZOTH_REPLAY_CHANNEL1_ECHO=1 for one A/B run.
        """
        if not CHANNEL1_ECHO_ENABLED or self.gone or not self.v3_responded:
            return
        # Experimental probe; keep it behind the drained replay so an A/B of it
        # never overlaps the replay's own channel-0 traffic.
        if self.replay_queue or not self.greetings_after_replay:
            return  # let the replay finish first
        if self.channel1_last_body is None:
            return
        now = time.monotonic()
        if now < self.channel1_echo_next_at:
            return
        self.channel1_echo_next_at = now + CHANNEL1_ECHO_PERIOD_S
        body = self.channel1_last_body
        seq = self.out_msg_seq
        self.out_msg_seq = (seq + 1) & 0xFFFF
        rel = self.out_rel_seq
        self.out_rel_seq = (rel + 1) & 0xFFFF
        rec = MessageRecord(
            channel=1,
            payload=body,
            sequence=seq,
            reliable_sequence=rel,
            reliable=False,
            connecting=False,
            flags_override=0x20,  # unreliable + DATA_CHANNEL (the client's form)
        )
        self._send_datagram(server, [rec])
        self.channel1_echo_sent += 1
        log_event(
            {
                "event": "channel1-echo",
                "sent": self.channel1_echo_sent,
                "size": len(body),
            }
        )

    def maybe_position_reply(self, server) -> None:
        """EXPERIMENTAL: answer the channel-1 input stream with a position message.

        See POSITION_REPLY_* above for why this is the best-supported candidate and
        for the decoded wire layout. The body is built here from the client's own
        actor id so the reply addresses the actor the client is streaming about.
        """
        if not POSITION_REPLY_ENABLED or self.gone or not self.v3_responded:
            return
        # Keep it behind the drained replay: the replay is the only state the client
        # has been observed to accept wholesale, and overlapping them makes an A/B
        # unreadable.
        if self.replay_queue or not self.greetings_after_replay:
            return
        now = time.monotonic()
        if now < self.position_reply_next_at:
            return
        self.position_reply_next_at = now + POSITION_REPLY_PERIOD_S

        actor = self.client_actor_id or bytes.fromhex(
            "1a954abc4b3185bfbe37c3d8592618e0"
        )
        target = position_reply_target(actor)
        if target is None:
            return
        body = position_reply_body(target, POSITION_REPLY_SCALE)
        if body is None:
            return
        # One framing implementation: `wrap_reply`. It reads
        # POSITION_REPLY_CONTAINER itself, so the log and the bytes cannot
        # disagree (see its docstring).
        def wrap(wire_type: int, msg_body: bytes) -> bytes:
            return wrap_reply(POSITION_REPLY_CONTAINER, target, wire_type, msg_body)

        # Open the movement channel once, before the first position assertion. The
        # static layout says this is the message that starts the client's movement
        # communication; without it a bare position update may be ignored.
        if START_MOVEMENT_ENABLED and not self.start_movement_sent:
            mv_body = start_movement_body(actor, START_MOVEMENT_COMM)
            if mv_body is not None:
                mv_payload = wrap(START_MOVEMENT_TYPE, mv_body)
                mv_seq = self.out_msg_seq
                self.out_msg_seq = (mv_seq + 1) & 0xFFFF
                mv_rel = self.out_rel_seq
                self.out_rel_seq = (mv_rel + 1) & 0xFFFF
                self._send_datagram(
                    server,
                    [
                        MessageRecord(
                            channel=START_MOVEMENT_CHANNEL,
                            payload=mv_payload,
                            sequence=mv_seq,
                            reliable_sequence=mv_rel,
                            reliable=START_MOVEMENT_RELIABLE,
                            connecting=False,
                            flags_override=0x21 if START_MOVEMENT_RELIABLE else 0x20,
                        )
                    ],
                    track_reliable=START_MOVEMENT_RELIABLE,
                )
                self.start_movement_sent += 1
                log_event(
                    {
                        "event": "start-movement",
                        "channel": START_MOVEMENT_CHANNEL,
                        "type": hex(START_MOVEMENT_TYPE),
                        "size": len(mv_payload),
                        "actor": actor.hex(),
                        "reliable": START_MOVEMENT_RELIABLE,
                    }
                )

        payload = wrap(POSITION_REPLY_TYPE, body)
        seq = self.out_msg_seq
        self.out_msg_seq = (seq + 1) & 0xFFFF
        rel = self.out_rel_seq
        self.out_rel_seq = (rel + 1) & 0xFFFF
        rec = MessageRecord(
            channel=POSITION_REPLY_CHANNEL,
            payload=payload,
            sequence=seq,
            reliable_sequence=rel,
            reliable=POSITION_REPLY_RELIABLE,
            connecting=False,
            # The client's own channel-1 records use unreliable+DATA_CHANNEL (0x20).
            flags_override=0x21 if POSITION_REPLY_RELIABLE else 0x20,
        )
        self._send_datagram(server, [rec], track_reliable=POSITION_REPLY_RELIABLE)
        self.position_reply_sent += 1
        if self.position_reply_sent <= 5 or self.position_reply_sent % 100 == 0:
            log_event(
                {
                    "event": "position-reply",
                    "sent": self.position_reply_sent,
                    "channel": POSITION_REPLY_CHANNEL,
                    "type": hex(POSITION_REPLY_TYPE),
                    "size": len(payload),
                    "actor": actor.hex(),
                    "target": target.hex(),
                    "container": POSITION_REPLY_CONTAINER,
                }
            )

    def _send_replay_message(self, server, msg) -> None:
        """Wrap a captured typed-stream body in a Carrier record + envelope.

        Mirrors the V3 response wrap (ch=0, flag=0x21, VLQ32 length-prefixed
        body). The replay body already carries the [00 01 <type>] preamble,
        so it is forwarded verbatim. Bodies above the DTLS plaintext cap are
        split with MF_CHUNKS (total-count by default; countdown is selectable).
        """
        from .javelin.wire import chunk_replay_payload, encode_vlq32

        # 2026-09-30: the duplicate LevelInfo (type 0x663) at replay seq 0x4d
        # fires a SECOND LevelInfoChanged ~15 s after the first; from then on
        # the message port reports clientContext == nullptr on EVERY bundle
        # (no Cleanup() in the log — the duplicate swaps/replaces the context
        # the port reads). Suppress the duplicate; the first (seq 0x10) stays.
        # Allowlist env override for A/B: AZOTH_REPLAY_SEND_DUP_LEVELINFO=1.
        if msg.seq == 0x4D and msg.type_id == 0x663:
            if os.environ.get("AZOTH_REPLAY_SEND_DUP_LEVELINFO", "") != "1":
                log_event({"event": "replay-skip-dup-levelinfo", "seq": msg.seq})
                return

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
                num_chunks=(len(chunks) if REPLAY_CHUNK_COUNT_TOTAL else remaining),
                flags_override=0x25,  # RELIABLE | CHUNKS | DATA_CHANNEL
            )
            self._send_datagram(
                server,
                [rec],
                replay_chunk={
                    "replay_seq": msg.seq,
                    "chunk_index": i,
                    "chunk_count": len(chunks),
                },
            )
            if REPLAY_CHUNK_GAP_MS > 0 and i + 1 < len(chunks):
                # The client's Carrier queue drains on its own tick; a burst
                # of N chunks overruns it and the reassembly truncates.
                time.sleep(REPLAY_CHUNK_GAP_MS / 1000.0)
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

    def _send_datagram(
        self,
        server,
        records: list[MessageRecord],
        *,
        replay_chunk: dict | None = None,
        track_reliable: bool = True,
    ) -> None:
        carrier_seq = self.next_out_seq & 0xFFFF
        datagram = (
            b"\x80\x01"
            + carrier_seq.to_bytes(2, "big")
            + marshal_datagram(records)
        )
        if replay_chunk is not None:
            log_event(
                {
                    "event": "replay-chunk",
                    "carrier_seq": carrier_seq,
                    **replay_chunk,
                }
            )
        # Reliable records ride this datagram: keep it for retransmission
        # until the client's CT_ACKS bitmap covers it (GridMate WriteAckData).
        #
        # track_reliable=False is for records that carry a reliable WIRE flag
        # but must not be retransmitted: periodic ones that supersede
        # themselves. The post-replay 0x15d heartbeat is exactly that — it
        # must stay flags 0x21 (flags 0x20 made the client drop it silently,
        # 2026-09-30) but the client never ACKs it, so tracking it meant every
        # heartbeat was retried to the 6-try cap. Measured 2026-10-09 over a
        # 23-minute session: 1106 heartbeats produced 5437 resends — 46% of
        # all outbound datagrams — and the resent 13-byte ch0 records were the
        # single largest traffic class (5435). Losing one heartbeat is
        # harmless because the next tick replaces it a second later.
        if track_reliable and any(rec.reliable for rec in records):
            self.sent_reliable[carrier_seq] = (time.monotonic(), datagram)
        self.next_out_seq += 1
        self.send(server, datagram)

    def _process_acks(self, recs: list) -> None:
        """Decode the client's SM_CT_ACKS (Carrier.cpp WriteAckData format).

        flags 0x20 = keepalive-only; 0x40 = continuous [first..last];
        0x8n = bitmap of n bytes covering last-1 backwards.

        2026-10-02 REVERTED: an earlier change also read p[3:5] as an ack
        of OUR envelope seq. That is correct ONLY for the 0x40 continuous
        form (where the elif below already covers it) and CORRUPT for the
        0x8n bitmap forms (p[3:] is the bitmap): bogus seqs got marked
        acked and maybe_resend suppressed legitimate retransmissions.
        Live effect: a possession run came up with the manager context
        setter never called (mgrSet 0 vs 2 in session 232). The resend
        storm is benign in-flight retransmission, not a decode bug."""
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
        # Safety valve: a long-lived session that never receives acks (or whose
        # ack bitmaps lag) must not grow this table without bound — iterating a
        # huge dict every tick starves the UDP loop. Drop the oldest entries.
        if len(self.sent_reliable) > 4096:
            for stale in sorted(self.sent_reliable)[: len(self.sent_reliable) - 2048]:
                del self.sent_reliable[stale]
                self.resend_tries.pop(stale, None)
        now = time.monotonic()
        sent = 0
        # Same "replay finished" predicate as maybe_heartbeat: queue drained
        # AND the quiet-complete flag. Before that, lost possession chunks
        # still need this call's burst of 4.
        replay_done = not self.replay_queue and self.greetings_after_replay
        ack_hw = max(self.acked_seqs) if replay_done and self.acked_seqs else None
        if (
            replay_done
            and now - self.resend_window_start >= POST_REPLAY_RESEND_WINDOW_S
        ):
            self.resend_window_start = now
            self.resend_window_count = 0
        for seq in sorted(self.sent_reliable):
            if seq in self.acked_seqs:
                del self.sent_reliable[seq]
                continue
            t, dgram = self.sent_reliable[seq]
            if now - t < RESEND_INTERVAL_S:
                continue
            if replay_done:
                # More than 512 below the ack high-water is stale. The
                # type-0x08 tail (888 vs ~890) is not — only the window
                # slows it. Either skip leaves the seq unacked and untried.
                if ack_hw is not None and ack_hw - seq > POST_REPLAY_STALE_GAP:
                    continue
                if self.resend_window_count >= POST_REPLAY_RESEND_MAX:
                    return
            elif sent >= 4:
                return
            # Attempt count: stored in the tuple slot via a dict of counts.
            tries = self.resend_tries.get(seq, 0)
            if tries >= REPLAY_RESEND_LIMIT:
                continue
            self.resend_tries[seq] = tries + 1
            self.sent_reliable[seq] = (now, dgram)
            self.send(server, dgram)
            sent += 1
            if replay_done:
                self.resend_window_count += 1
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
        if OUTBOUND_PAYLOAD_LOG:
            event = describe_datagram(datagram)
            event.pop("raw", None)
            event.update(
                event="outbound-app-data",
                peer=f"{self.peer[0]}:{self.peer[1]}",
                raw_full=datagram.hex(),
            )
            log_event(event)
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
            if RAW_LOG:
                log_event(
                    {
                        "event": "raw-datagram-out",
                        "peer": f"{self.peer[0]}:{self.peer[1]}",
                        "size": len(out),
                        "raw_full": out.hex(),
                    }
                )
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
        log_event(
            {
                "event": "config",
                "replay_identity_remap": REPLAY_IDENTITY_REMAP,
                "replay_selfident_guid": REPLAY_SELFIDENT_GUID,
                "replay_fresh_levelinfo": REPLAY_FRESH_LEVELINFO,
                "replay_span_substitution": REPLAY_SPAN_SUBSTITUTION,
                "replay_span_seqs": (
                    sorted(REPLAY_SPAN_SEQS) if REPLAY_SPAN_SEQS else "all"
                ),
                "replay_span_lengths": (
                    sorted(REPLAY_SPAN_LENGTHS) if REPLAY_SPAN_LENGTHS else "all"
                ),
                "replay_span_substitution2": REPLAY_SPAN_SUBSTITUTION2,
                "replay_span_seqs2": (
                    sorted(REPLAY_SPAN_SEQS2) if REPLAY_SPAN_SEQS2 else "all"
                ),
                "replay_span_lengths2": (
                    sorted(REPLAY_SPAN_LENGTHS2) if REPLAY_SPAN_LENGTHS2 else "all"
                ),
                "replay_local_player_uuid": REPLAY_LOCAL_PLAYER_UUID,
                "replay_local_player_uuid_seqs": (
                    sorted(REPLAY_LOCAL_PLAYER_UUID_SEQS)
                    if REPLAY_LOCAL_PLAYER_UUID_SEQS
                    else "all"
                ),
                "replay_split_seq": hex(REPLAY_SPLIT_SEQ) if REPLAY_SPLIT_SEQ else "off",
                "replay_split_delay_s": REPLAY_SPLIT_DELAY_S,
                "chunk_gap_ms": REPLAY_CHUNK_GAP_MS,
                "heartbeat": HEARTBEAT_ENABLED,
                "heartbeat_period_s": HEARTBEAT_PERIOD_S,
                # Experimental levers. Logged so an A/B run can be attributed
                # from the log alone: on 2026-10-11 a run set
                # AZOTH_REPLAY_START_MOVEMENT=1 but the config event did not
                # record it, and the missing `start-movement` event could not be
                # told apart from "the env never reached the world process".
                "position_reply": POSITION_REPLY_ENABLED,
                "position_reply_channel": POSITION_REPLY_CHANNEL,
                "position_reply_container": POSITION_REPLY_CONTAINER,
                "position_reply_reliable": POSITION_REPLY_RELIABLE,
                "position_reply_target": POSITION_REPLY_TARGET or "actor",
                "start_movement": START_MOVEMENT_ENABLED,
                "start_movement_channel": START_MOVEMENT_CHANNEL,
                "start_movement_reliable": START_MOVEMENT_RELIABLE,
                # Post-replay continuation levers. These decide whether the
                # client keeps seeing server traffic after the replay drains,
                # which is what the HUD cable and the state watchdog react to.
                # Logging them here is the only way to tell an A/B run's
                # configuration from the server log alone.
                "state_stream": STATE_STREAM_ENABLED,
                "activity_stream": ACTIVITY_STREAM_ENABLED,
                "input_response": INPUT_RESPONSE_ENABLED,
                "input_response_period_s": INPUT_RESPONSE_PERIOD_S,
                "input_response_target": INPUT_RESPONSE_TARGET or "captured",
                "input_response_channel": INPUT_RESPONSE_CHANNEL,
                "input_response_container": INPUT_RESPONSE_CONTAINER,
                "channel1_echo": CHANNEL1_ECHO_ENABLED,
                "replay_enabled": REPLAY_ENABLED,
                "replay_drop_unreceivable": REPLAY_DROP_UNRECEIVABLE,
                "replay_defer_client_facets": REPLAY_DEFER_CLIENT_FACETS,
                "replay_request_gating": REPLAY_REQUEST_GATING,
                "replay_defer_timeout_s": DEFER_DECISION_TIMEOUT_S,
                "inbound_dispatch": INBOUND_DISPATCH_ENABLED,
                "inbound_answer_interval_s": INBOUND_ANSWER_MIN_INTERVAL_S,
                "replay_max_seq": hex(REPLAY_MAX_SEQ),
                "ack_window": ACK_WINDOW,
                "ack_coalesce_s": ACK_COALESCE_S,
            }
        )
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
        log_event(
            {
                "event": "listening-dtls",
                "addr": f"{self.host}:{self.port}",
                "tick_hz": TICK_HZ,
            }
        )
        # The socket timeout IS the tick period: with no traffic the loop still
        # wakes this often and the tick still runs, so the server keeps emitting
        # on its own clock instead of only when the client speaks.
        self.sock.settimeout(TICK_INTERVAL_S)
        while True:
            # Authoritative tick: every session, every iteration, both on a
            # datagram and on an idle timeout.
            for session in list(self.peers.values()):
                try:
                    session.tick(self)
                except Exception as exc:  # noqa: BLE001
                    # Log the traceback, not just the message. A tick error that
                    # repeats every second is invisible without it: 7395
                    # consecutive `OverflowError: int too big to convert` lines
                    # (2026-10-10) named no function, so the keepalive being dead
                    # for two hours looked like nothing at all in the log.
                    log_event(
                        {
                            "event": "tick-error",
                            "error": f"{type(exc).__name__}: {exc}"[:200],
                            "traceback": traceback.format_exc()[-1200:],
                        }
                    )
            try:
                data, peer = self.sock.recvfrom(65536)
                if RAW_LOG:
                    # Diagnostic: prove whether a client datagram reached the
                    # socket at all, before any DTLS handling. Needed because a
                    # failed REP handshake is otherwise invisible here (the
                    # client times out in WaitingForREPConnection while the
                    # server logs nothing).
                    log_event(
                        {
                            "event": "raw-datagram",
                            "peer": f"{peer[0]}:{peer[1]}",
                            "size": len(data),
                            "raw_full": data.hex(),
                        }
                    )
            except TimeoutError:
                # Nothing to read this tick; the tick itself already ran above.
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
            if session is not None and _is_client_hello(data):
                # A fresh ClientHello from a peer we already hold a session for:
                # the client reused its source port after a previous session
                # ended. Feeding the new handshake into the old DTLS state
                # machine leaves it stuck — observed live 2026-09-27: the client
                # retried its ClientHello 12 times from 127.0.0.1:27000, the
                # server never replied and logged NO error, and the client gave
                # up with `@mm_csdkerr_connection_failed` after 15 s in
                # WaitingForREPConnection. That is the whole "flaky REP" story:
                # the second and later world attempts in a session reuse a port
                # the server still had a dead session for. Drop and rebuild.
                log_event(
                    {
                        "event": "dtls-session-reset",
                        "peer": f"{peer[0]}:{peer[1]}",
                    }
                )
                self.drop(peer)
                session = None
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
                # Log the TRACEBACK, not just the message. Measured 2026-10-11:
                # a live session died with `transportError: 4` on the client and a
                # bare `feed-error: IndexError: list index out of range` here, with
                # no way to tell which parse step raised — the same blindness that
                # kept the 16-bit overflow hidden for two hours (see the tick-error
                # note). The loop must survive the error, so the exception is still
                # swallowed; it just has to be identifiable next time.
                import traceback

                log_event(
                    {
                        "event": "feed-error",
                        "peer": f"{peer[0]}:{peer[1]}",
                        "error": f"{type(exc).__name__}: {exc}"[:200],
                        "traceback": traceback.format_exc()[-1200:],
                        "datagram_size": len(data),
                        "datagram_head": data[:32].hex(),
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
