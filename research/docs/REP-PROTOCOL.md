# Javelin REP protocol (game server wire)

Everything here is RE'd from `NewWorld.exe` (1.400.6031.6004151) or verified
against a live client session. External ground truth: the nw-private-server
(first-light) project decompiled the same stack on build 1.365.6031.6006993 —
their function VAs differ from ours, the wire layout matches. Re-derive every
VA on OUR build before trusting it (`research/tools/reversing/bytepat.py`).

## Where REP sits in the login chain

```
gateway queue ticket (LoginQueueResponse.RepAddress, e.g. 127.0.0.1:9000)
  -> GameConnection state QueueGameLogin -> WaitingForQueuedLogin
  -> StartREPConnection -> DTLS handshake against RepAddress
  -> RegistrationRequestV3Msg (client -> server)
  -> RegistrationResponseMsg (server -> client): rep.ready 0 -> 1
  -> post-V3 server messages (state ladder 10 -> 14, see below)
```

The client destroys the session ~30s after V3 if the post-V3 ladder does not
advance (observed externally; our own timeout TBD once the REP server exists).

## DTLS trust (the gate before any byte flows)

The DTLS layer accepts any certificate when its verify callback is the
permissive one; otherwise it builds a CA bundle and enforces normal OpenSSL
validation against the **embedded** self-signed `CN=New World` cert
(`.rdata` PEM blob — our own CA can never validate). External Ghidra trace
(their build, RE-DERIVE on ours):

- Driver init ≈ `Javelin_SecureSocketDriver_Initialize`
- Verify callback returns constant `1` (always trust)
- Branch site: `CMP qword ptr [RDI + 0x288], 0x0` / `JZ <permissive path>`
- Runtime patch: force the jump unconditionally (`JZ rel32` -> `JMP rel32`,
  same target). In-memory only, via `scripts/frida-trust-patch.py`, against
  OUR private runtime (no EAC there — the EAC ban in `EAC.md` covers the
  official process, not our own exe copy).

**VERIFIED on our build 1.400.6031.6004151 (2026-09-14,
`bytepat.py dtls-verify`):** the site is byte-identical AND at the same VA —
CMP at `0x145dce8ad` (`48 83 BF 88 02 00 00 00`), JZ at `0x145dce8b5`
(`0F 84 19 01 00 00` -> `0x145dce9d4`). Patch bytes recomputed:
`E9 1A 01 00 00 90`. (The externally archived `E9 19 01 00 00 90` is off by
one — a 5-byte JMP in a 6-byte slot must use rel32 = 0x11A, not the JZ's
0x119. `scripts/frida-trust-patch.py` always recomputes.) Both builds share
the `6031` branch and this code did not move. Keep re-deriving on every
client update anyway.

Lever entry: `research/atlas/levers.md` ("DTLS verify bypass").

## Carrier envelope (every post-DTLS datagram, 4 bytes)

```
byte 0: type — 0x80 = plaintext records, 0x81 = LZ4-compressed
         (bit 7 always set; bit 0 = compression; bits 1-6 must be 0)
byte 1: proto — always 0x01
bytes 2-3: datagram sequence, u16 big-endian
```

## MessageRecord stream (1..N per datagram)

Bit-packed header per record:

```
flags     : u8   (see MessageFlags)
size      : u16 BE (payload bytes; absent when MF_NO_LENGTH is set)
channel   : u8   present only when MF_DATA_CHANNEL is set (else = previous)
numChunks : u16 BE present only when MF_CHUNKS is set (else implicit 1)
sequence  : u16 BE present only when MF_SEQUENTIAL_ID is CLEAR
            (set => auto-increment per channel)
relSeq    : u16 BE present only when MF_SEQUENTIAL_REL_ID is CLEAR
            (set => auto-increment per channel when reliable)
payload   : `size` bytes (to end of datagram when MF_NO_LENGTH)
```

Flag bits:

| Bit | Name | Meaning |
| --- | --- | --- |
| 0x01 | MF_RELIABLE | reliable delivery |
| 0x04 | MF_CHUNKS | chunked payload (`numChunks` follows) |
| 0x08 | MF_SEQUENTIAL_ID | omit `sequence` (receiver auto-increments) |
| 0x10 | MF_SEQUENTIAL_REL_ID | omit `relSeq`; with MF_NO_LENGTH = first-attempt connect form (4-byte sub-header + 5-byte CONNECT-INIT blob) |
| 0x20 | MF_DATA_CHANNEL | `channel` byte follows |
| 0x40 | MF_NO_LENGTH | payload runs to end of datagram (V3 data-channel record: flag 0xe0/0xf0) |
| 0x80 | MF_CONNECTING | connecting |

**System messages (channel 3):** the 1-byte msgId is the LAST byte of the
payload, not the first. Known ids: 1 = CONNECT_REQUEST, 2 = CONNECT_ACK,
3 = DISCONNECT, 4 = CLOCK_SYNC, 5 = CT_FIRST, 6 = CT_ACKS,
7 = CT_CONN_CONTROL, 8 = CT_BANDWIDTH.

### CONNECT_REQUEST resend signature (observed 2026-09-15, build 1.400.6031)

Post-DTLS (Frida bypass active, `dtls-established` in ~0ms), the client
streams datagrams on channel 3 with MULTIPLE records each, ~1/s for ~15-30s,
then aborts with "No se puede conectar al servidor" (the "(2) conexión segura"
variant only appears WITHOUT the DTLS bypass = cert reject):

```
seq 2 : sys1/a0/5B  + sys1/88/6B  + sys6/88/2B     <- first datagram
seq 3 : sys1/a0/6B  + sys6/88/2B
seq 4 : sys1/a0/7B  + sys6/88/6B
...        sys1/a0 grows EXACTLY +1 byte per resend (5B -> 27B over 15s)
seq 143: sys1/a0/27B + sys6/88/2B                  <- last, then disconnect
```

Interpretation (working hypothesis, verify by decompiling the ACK path):
the client never sees its CONNECT_REQUEST reliably acked, so the reliable
resend buffer accumulates one byte per cycle. Our current reply
(`connect_ack_datagram`: single sys2/0xa0 record echoing
`[u32 len][cookie]` verbatim, envelope seq of the request) is NOT accepted.
Candidate defects, in order to test:
1. We answer only the FIRST sys1 in the datagram — the parallel
   `sys1/0x88/6B` record may be the real request (flag 0x88 vs 0xa0).
2. We never emit CT_ACKS (sys6) ourselves; client may require them.
3. The ACK may need to reference the client's relSeq (per-record), not the
   envelope seq, or carry the MF_CONNECTING flag cleared.
Next lever: hook/decompile the client's CONNECT_ACK handler (cookie-compare)
to read the exact expected shape.


## RegistrationRequestV3Msg (client -> server, 832 bytes body)

AzCore-serialized. Visible `AZStd::string` elements are u8-length-prefixed
ASCII; inter-field framing and the Steam auth blob are opaque (kept verbatim
for round-trip). Layout:

```
[0x000..0x021] prelude (33 B, type-id + AzCore class metadata)
0x021 build_version      "6031"
0x02a unknown_400        "400"
0x038 sdk_name           "Javelin"
0x044 sdk_version        "600415" + 1 tail byte (0x18)
0x050 build_flavor       "[RETAIL]"
0x05a client_signature   "sig:<ticket-uuid>"
0x083 client_endpoint    "127.0.0.1:<port>"
0x093..0x0a8 worldId-prefix region (opaque, 21 B)
0x0a8 session_uuid       <uuid>
0x0cd persona_id         "amzn1.developerPersonaId.<uuid>"
0x110 platform_app_tag   "STEAM_APP_ID.1063730"
0x144 platform_user_id   <SteamID64>
0x157 platform_name_blob "steam|14" (length byte 0x08, not 0x05)
[..0x15D] auth_blob      Steam ticket + JWT region (opaque)
[0x334..0x340] trailer   `00 43 02 80` + 8 zero bytes (12 B)
```

Retry bodies use a different tagged-record format (6 records: u32 BE type_id
in [0..7] + u8 length + string); the tail carries the same identity fields.
Lenient fallback: regex for the session UUID (preceded by `$` = 0x24 length
byte) and `amzn1.developerPersonaId.<uuid>`.

## RegistrationResponseMsg (server -> client, 88 bytes)

```
offset 0x00  00 01 03            preamble: marker + type = 3
offset 0x03  00 00 00 00         error_code (u32 BE, 0 = success)
offset 0x07  8 mystery bytes     session_clock (u32 BE) + nonce (u32 BE)
offset 0x0f  0x20                length-prefix = 32
offset 0x10  32-byte session token
offset 0x30  0x23                length-prefix = 35
offset 0x31  "[RETAIL].Javelin.1.365.6031.6006993" (server-version string)
offset 0x54  01 00 00 01         trailer (4 B)
```

NO 16-byte type GUID prefix (a guess that was proven wrong by a real
capture). Caller wraps the body in a Carrier data-channel record + envelope.
Accepting this response flips `rep.ready` 0 -> 1.

## Post-V3 state ladder (external map, verify on our build)

States 10 -> 14 form the player-spawn ladder; all four transition writers and
trigger chains are mapped externally. MVP server-side estimate: **3 messages
minimum** — SelfIdent (state 10->11) + LevelInfoChanged (12->13) + a
replica-creation message (likely GridMate `NewProxy` carrying the player
actor, 13->14). The 11->12 transition auto-fires once 10->11 lands.

Reference: O3DE GridMate source is the Javelin wire-format reference
(Carrier/Replica semantics); the game calls it "REP" (Replication Protocol).
