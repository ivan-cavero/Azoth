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
