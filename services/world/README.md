# world

The Azoth **Javelin REP server** (the "game server"): UDP + DTLS 1.2 on the
`RepAddress` from the login-queue ticket (default `127.0.0.1:9000`).

```powershell
python az.py world start      # server window, :9000
python az.py world test       # javelin lib + DTLS handshake tests
```

Layout (mirrors services/gateway):

```
src/azoth_world/
  javelin/        wire library (no server concerns)
    bitstream.py    BitStream / BitStreamWriter (LSB-first, masked reads)
    frame.py        Carrier envelope + MessageRecord parse/marshal
    v3.py           V3 registration request (round-trip) + response (88 B)
  rep.py            DTLS server, per-peer memory-BIO sessions, traffic log
tests/              unittest (stdlib)
certs/              rep.crt/rep.key, auto-generated (gitignored)
rep_traffic.jsonl   live capture: every datagram, decoded (gitignored)
```

The world log stores complete decrypted client payloads as `raw_full`, and
complete plaintext server sends as `outbound-app-data.raw_full`. Set
`AZOTH_LOG_OUTBOUND_PAYLOADS=0` to disable server plaintext capture. For full
encrypted UDP datagrams in both directions, set `AZOTH_LOG_RAW=1`; those rows
are tagged `raw-datagram` / `raw-datagram-out`. These local captures can contain
session IDs and private payloads; keep them under ignored `research/sessions/`
and never add them to the atlas or Git.
Set `AZOTH_REP_TRAFFIC_JSONL` to redirect the append-only log for isolated
tests or a separate capture run.

## Replay levers (world env, all default off)

The replay is the captured official session replayed into our client. The
levers that matter for possession:

| Env | Default | What it does |
| --- | --- | --- |
| `AZOTH_REPLAY_LOCAL_PLAYER_UUID` | `off` | `character` or `session`. **Fills the ONE redacted 16-byte span that is immediately followed by that record's length-prefixed display name** — the UUID of the capture author's own `PlayerComponentClientFacet`, which the capture zeroed while every other player's facet UUID is in clear text. The local-player gate compares exactly that UUID with the character UUID in the client's local option store, so with the span left zeroed the gate never opens and the player is never possessed. `character` makes it render (verified 2026-10-02). Scope it with `AZOTH_REPLAY_LOCAL_PLAYER_UUID_SEQS`. |
| `AZOTH_REPLAY_SPAN_SUBSTITUTION` / `_SEQS` / `_LENGTHS` | `off` | Broad, length-based substitution of every redacted span of the listed lengths. Documented negative results in `research/atlas/levers.md`; prefer the targeted lever above. |
| `AZOTH_REPLAY_SPLIT_SEQ` / `_DELAY_S` | off | Hold every message with `seq >= SPLIT` until the client has loaded the level. |
| `AZOTH_REPLAY_HEARTBEAT` / `_PERIOD_S` | on / 1.0 | Continue the captured `0x15d` ping/pong after the replay drains. |
| `AZOTH_LOG_RAW` | `0` | Log every inbound datagram pre-DTLS. `python az.py dev` does **not** forward it (its own environment wins); start the world server directly to use it. |

All of them log a `replay-*` event per applied message, so a run can be audited
from `rep_traffic.jsonl` alone.

**The one non-stdlib dependency:** `pyOpenSSL` (`python -m pip install
pyOpenSSL`). stdlib `ssl` has no DTLS and rustls does not speak DTLS either;
pyOpenSSL ships a prebuilt OpenSSL so nothing compiles. Gateway stays
stdlib-only; this exception is world-only.

Trust model: the client pins an embedded `CN=New World` cert, so the
handshake only completes after the runtime verify-bypass
(`scripts/frida-trust-patch.py`; see `research/atlas/levers.md` and
`research/docs/REP-PROTOCOL.md`). Our server cert is self-signed with
`CN=New World` — cosmetic after the patch, honest in logs.

Protocol reference: `research/docs/REP-PROTOCOL.md`. Wire tests enforce the
round-trip rule: a parser that cannot reproduce its input byte-for-byte is
wrong.

Frozen spawn MVP (what is left after `rep.ready` flips):

1. ~~UDP bind~~ done
2. ~~DTLS handshake~~ done (needs the client trust patch)
3. Carrier `CONNECT_REQUEST` → `CONNECT_ACK`
4. V3 registration → response (server answers it today)
5. `LevelInfoChanged`
6. `Cmd_NewProxy` for the player → Game.log `player spawn succeeds, in game`
