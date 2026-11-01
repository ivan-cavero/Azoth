# Private client runbook — DTLS-spike live attempt

Operational reference for one narrow experiment: **point the real New World
client's REP connection at the Rust DTLS server in `server/crates/everfall-net`
and watch whether the DTLS handshake completes.** This is a handshake probe, not
a world run. The client will not reach character select through this server: the
carrier handshake, the registration ladder and application data are out of scope.

The spike is now **OpenSSL** presenting an **RSA 2048 self-signed certificate**
(`CN=New World`), matching the Python lab. That was decided by measurement:
`dimpl` (pure-Rust, ECDSA-only) was bound on the REP port and the client sent
**twelve 159-byte ClientHellos and `dimpl` produced no flight at all**
(`dtls error: timeout: connect`), while the client's DTLS works against the
Python world that signs with RSA 2048. So the remaining open question is only
whether the stock client completes a handshake with *this* server's certificate;
the local loopback proof (`cargo test -p everfall-net`) shows the crate is wired,
not that this client accepts it.

## Preconditions

- The client's REP address is `127.0.0.1:9000`; it comes from
  `services/gateway/src/azoth_gateway/data/worlds.json`. No edit is needed to aim
  the client at the spike server — free that port instead.
- `services/world` (the Python REP server) also binds `127.0.0.1:9000`, so the
  world must **not** be running.
- `python ef.py dev` starts gateway **and** world **and** Caddy. Do not use it
  here; it would bind 9000.

## Commands

```powershell
# 1. free 127.0.0.1:9000 — stop the world (and anything else on the stack)
python ef.py dev status
python ef.py dev stop

# 2. start ONLY the gateway (port 8080); the world stays down
python ef.py gateway start
python ef.py gateway status

# 3. start the DTLS spike server on 127.0.0.1:9000 (leave it in the foreground)
cd server
cargo run -p everfall-net --bin everfall-netd
#    port override:  cargo run -p everfall-net --bin everfall-netd -- 9000
#    or:             $env:EVERFALL_NET_PORT = '9000'

# 4. in a second shell, launch the private client and drive it
python ef.py game
#    unattended driver (stops at character select is enough to see DTLS):
#    python scripts/session/private-run.py --no-play

# 5. when done: Ctrl-C the server, then
python ef.py gateway stop
```

Environment: `EVERFALL_NET_PORT` selects the bind port (default `9000`). The
server always binds `127.0.0.1`. The certificate is an **RSA 2048 self-signed**
cert with `CN=New World`, minted in memory at process start; nothing is written
to disk. `everfall-net` links a **prebuilt OpenSSL development package** (the
Windows OpenSSL installer, e.g. `ShiningLight.OpenSSL.Dev`); it does not build
OpenSSL from source, and the package is a prerequisite like the Windows SDK.

## What to watch (server stdout, timestamped)

| Line | Meaning |
| --- | --- |
| `datagram received: N bytes from …` | the client's DTLS stack reached our port and sent bytes |
| `flight sent: N bytes to …` | we answered with a real DTLS record |
| `Connected` | the DTLS 1.2 handshake completed end-to-end |
| `fatal Error: …` | OpenSSL gave up; the connection must be dropped |

The expected shape of a successful handshake is: `datagram received` (ClientHello)
→ `flight sent` (HelloVerifyRequest / cookie) → `datagram received` (ClientHello
with cookie) → one or more `flight sent` (ServerHello, Certificate, ServerHelloDone,
… ) → `Connected`.

## What falsifies the choice

| Observation | Reading |
| --- | --- |
| No `datagram received` at all while the client reports connecting | The client never tried our port. Wrong host/port or wrong `RepAddress`; or it aborted before REP. **Not** a certificate result. |
| `datagram received`, `flight sent` (HelloVerifyRequest), then only repeats with no `Connected` and no `fatal Error` | Cookie roundtrip stuck: the client ignored or replayed the HelloVerifyRequest. Look for a second ClientHello datagram. |
| `datagram received`, `flight sent` (ServerHello/Certificate), then `fatal Error` naming a certificate or signature failure | The client reached our `ServerHello` and rejected the certificate. A "no" for this cert shape, not necessarily for RSA. |
| `Connected` | The client completed a DTLS 1.2 handshake with this RSA 2048 certificate. Proceed to the carrier work. |

Report the server's lines verbatim: the exact `fatal Error` text is the evidence.

## Local proof

`cargo test -p everfall-net` runs `openssl_dtls12_handshake_and_round_trip_over_loopback`:
an `openssl`-crate DTLS 1.2 client against this server over loopback, asserting
`Connected` on both sides plus one application-data round trip, and
`certificate_is_rsa_2048_with_cn_new_world`, which pins the certificate shape.
Both require the prebuilt OpenSSL development package (see `server/README.md`);
with it installed, a plain shell with no environment variables runs them.
