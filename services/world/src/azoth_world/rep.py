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
import json
import socket
import time
from datetime import UTC, datetime
from pathlib import Path

from .javelin import (
    MessageRecord,
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

REPO_ROOT = Path(__file__).resolve().parents[4]  # .../Azoth (src/azoth_world/ -> up 4)
LOG_PATH = REPO_ROOT / "services" / "world" / "rep_traffic.jsonl"
CERT_DIR = Path(__file__).resolve().parents[2] / "certs"  # services/world/certs


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
    event: dict = {"size": len(data)}
    try:
        env, body = parse_envelope(data)
        event["envelope"] = {
            "type": hex(env.type_byte),
            "proto": env.proto,
            "seq": env.sequence,
            "compressed": env.is_compressed,
        }
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


def v3_response_datagram(seq: int) -> bytes:
    """RegistrationResponseMsg wrapped in a Carrier data-channel record."""
    rec = MessageRecord(
        channel=0,
        payload=V3RegistrationResponse().encode(),
        sequence=1,
        reliable_sequence=1,
        reliable=True,
        connecting=True,
        flags_override=0xE0,  # DATA_CHANNEL | NO_LENGTH | CONNECTING (V3 form)
    )
    return b"\x80\x01" + seq.to_bytes(2, "big") + marshal_datagram([rec])


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
        self.handshaken = False
        self.seq = 0

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
        event = describe_datagram(app)
        event.update(event="app-data", peer=f"{self.peer[0]}:{self.peer[1]}")
        log_event(event)
        # V3 data-channel record present -> answer the registration.
        try:
            _, body = parse_envelope(app)
            if any(r.size > 64 for r in parse_datagram(body).messages):
                server.v3_seen(self.peer, event)
                self.send(server, v3_response_datagram(self.next_seq()))
        except (ValueError, StopIteration):
            pass

    def send(self, server, datagram: bytes) -> None:
        try:
            self.conn.send(datagram)
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

    def next_seq(self) -> int:
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
        crt, key = make_self_signed_cert()
        self.ctx = SSL.Context(SSL.DTLS_METHOD)
        self.ctx.use_certificate_chain_file(str(crt))
        self.ctx.use_privatekey_file(str(key))
        self.peers: dict[tuple[str, int], PeerSession] = {}
        self.v3_count = 0

    def serve_forever(self) -> None:  # type: ignore[override]
        log_event({"event": "listening-dtls", "addr": f"{self.host}:{self.port}"})
        while True:
            try:
                data, peer = self.sock.recvfrom(65536)
            except OSError as exc:
                log_event({"event": "recv-error", "error": str(exc)[:120]})
                return
            session = self.peers.get(peer)
            if session is None:
                session = PeerSession(self.ctx, peer)
                self.peers[peer] = session
            session.feed(self, data)

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
        self.peers: dict[tuple[str, int], int] = {}
        self.v3_count = 0

    def serve_forever(self) -> None:  # type: ignore[override]
        log_event({"event": "listening-plain", "addr": f"{self.host}:{self.port}"})
        while True:
            data, peer = self.sock.recvfrom(65536)
            event = describe_datagram(data)
            event.update(event="datagram", peer=f"{peer[0]}:{peer[1]}")
            log_event(event)
            try:
                _, body = parse_envelope(data)
                if any(r.size > 64 for r in parse_datagram(body).messages):
                    self.v3_count += 1
                    n = self.peers.get(peer, 0) + 1
                    self.peers[peer] = n
                    self.sock.sendto(v3_response_datagram(n), peer)
            except ValueError:
                pass


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
