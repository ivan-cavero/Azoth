"""HTTP dispatch (stdlib ThreadingHTTPServer).

Performance: bodies + ETags preloaded once; per-request work is routing,
one dict lookup and header compares. Discovery dumps are best-effort and
capped. Gateway is login-only (never on the world tick hot path).
"""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config
from .routes.channel import channel_response, is_channel_path
from .routes.characters import (
    characters_response,
    characters_validator_response,
    is_characters_path,
    is_characters_validator_path,
)
from .routes.cms import CmsDoc, is_cms_path, load_cms
from .routes.credentials import credentials_response, is_credentials_path
from .routes.discovery import DiscoveryLog
from .routes.entitlements import (
    entitlements_response,
    entitlements_sync_response,
    is_entitlements_path,
    is_entitlements_sync_path,
)
from .routes.getlogininfo import (
    getlogininfo_response,
    is_getlogininfo_path,
    is_platform_user_code_path,
    region_from_headers,
)
from .routes.health import Metrics
from .routes.images import images_response, is_images_path
from .routes.omni import is_tokens_path, tokens_response
from .routes.privacy import is_privacy_path, privacy_response
from .routes.queue import is_queue_path, queue_response
from .routes.registry import motd_body
from .routes.s3 import is_s3_path, s3_body
from .routes.traffic import TrafficLog
from .routes.worlds_list import is_worlds_list_path, worlds_list_response
from .util.etag import etag_for, matches_if_none_match

# Repo layout: services/gateway/src/azoth_gateway/app.py
GATEWAY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]


class State:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.cms: dict[str, CmsDoc] = load_cms(cfg.schemas)
        self.metrics = Metrics()
        self.discovery = DiscoveryLog(cfg.discovery_dir)
        import os

        if os.environ.get("AZOTH_NO_TRAFFIC"):
            self.traffic = None  # tests / offline runs: no atlas writes
        else:
            self.traffic = TrafficLog(
                jsonl_path=GATEWAY_ROOT / "traffic.jsonl",
                atlas_path=REPO_ROOT / "research" / "atlas" / "observed-endpoints.json",
            )


class Handler(BaseHTTPRequestHandler):
    state: State  # injected by serve()
    server_version = "AzothGateway/0.1"
    # ponytail: Amazon responde HTTP/1.1; aws-sdk-cpp (WinHTTP) descarta bodies
    # de un 200 HTTP/1.0.
    protocol_version = "HTTP/1.1"
    # ponytail: sin TCP_NODELAY, el write de headers + write de body sufre el
    # stall delayed-ACK(~40ms)/Nagle de Windows -> el "ping de región" que el
    # cliente muestra sobre /ping medía ~40-70ms en loopback. Con NODELAY: ~2ms.
    disable_nagle_algorithm = True

    def log_message(self, format: str, *args: object) -> None:  # stdlib signature
        print(f"[gw] {self.command} {self.path} " + (format % args))

    # -- durable full-traffic capture (routes/traffic.py) --------------
    def setup(self) -> None:
        super().setup()
        self._az_req_body = b""
        self._az_resp_buf = bytearray()
        inner = self.wfile

        class _Tee:
            @staticmethod
            def write(b):
                if getattr(self, "_az_body_on", False):
                    self._az_resp_buf.extend(b[:65536])
                return inner.write(b)

            def __getattr__(self, name):
                return getattr(inner, name)

        self.wfile = _Tee()  # type: ignore[assignment] — duck-typed tee wrapper

    def end_headers(self) -> None:
        super().end_headers()
        # Body capture starts after the header block is written.
        self._az_body_on = True

    def handle_one_request(self) -> None:  # keep-alive: per-request capture
        self._az_resp_buf = bytearray()
        self._az_body_on = False
        self._az_status = 0
        super().handle_one_request()
        st = type(self).state
        if st is not None and st.traffic is not None and self._az_status:
            try:
                st.traffic.record_full(
                    self.command,
                    self.path,
                    self._az_status,
                    dict(self.headers.items()),
                    self._az_req_body,
                    bytes(self._az_resp_buf),
                )
            except (OSError, ValueError) as exc:  # capture must never break responses
                print(f"[gw] traffic capture failed: {exc}")

    def send_response(self, code: int, message: str | None = None) -> None:
        self._az_status = code
        super().send_response(code, message)

    # -- helpers ------------------------------------------------------
    def _send_json(self, body: bytes, etag: str, max_age: int, code: int = 200) -> None:
        inm = self.headers.get("If-None-Match")
        if code == 200 and matches_if_none_match(inm, etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", f"max-age={max_age}")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_body(
        self, payload: bytes, code: int = 200, ctype: str = "application/json", aws_id: bool = False
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        if aws_id:
            # Mirror the POST routes: aws-sdk-cpp correlates responses by the
            # request id, and the landing-screen GETs went out without one.
            req_id = self.headers.get("X-Amzn-Requestid") or "azoth-" + uuid.uuid4().hex[:8]
            self.send_header("x-amzn-RequestId", req_id)
            self.send_header("x-amz-apigw-id", "azoth-apigw/" + uuid.uuid4().hex[:8])
            cf_id = uuid.uuid4().hex[:16]
            self.send_header("x-amz-cf-id", cf_id)
            self.send_header("x-amz-cf-pop", "FRA56-P3")
            self.send_header("x-cache", "Miss from cloudfront")
            self.send_header("via", f"1.1 {cf_id}.cloudfront.net (CloudFront)")
            self.send_header("age", "0")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _try_game_mocks(self) -> bool:
        """Post-login game routes, shared by GET and POST dispatch."""
        st = self.state
        path = self.path
        if is_worlds_list_path(path):
            # ListWorlds: the landing screen's world list (Game.GetWorldList).
            key, payload = "worlds:list", worlds_list_response(st.cfg.discovery_dir)
            self._send_body(payload, ctype="application/x-amz-json-1.1", aws_id=True)
            st.metrics.hit(key)
            keep = {k: v[:200] for k, v in self.headers.items()}
            st.discovery.dump(self.command, path, dict(keep))
            print(f"[gw] {self.command} {path} -> {key} mock")
            return True
        if is_getlogininfo_path(path):
            # aws-sdk-cpp JavelinGatewayService client: the deserializer only
            # accepts the x-amz-json content type (observed on its requests).
            key = "getlogininfo"
            region_id = region_from_headers(self.headers)
            payload = getlogininfo_response(
                st.cfg.discovery_dir, region_id, self.headers.get("X-Azoth-Instance")
            )
            self._send_body(payload, ctype="application/x-amz-json-1.1", aws_id=True)
            st.metrics.hit(key)
            keep = {k: v[:200] for k, v in self.headers.items()}
            st.discovery.dump(self.command, path, dict(keep))
            print(f"[gw] {self.command} {path} -> {key} mock")
            return True
        if is_platform_user_code_path(path):
            # Omni account-link code request: client POSTs {token, type:ags}
            # and expects a link code. 404 makes Omni log
            # 'AGS account link error ... code: 202'. Serve a stub code.
            key = "platform:user-code"
            payload = b'{"code": "AZOTH-PRIVATE", "statusCode": 0}'
            self._send_body(payload)
            st.metrics.hit(key)
            keep = {k: v[:200] for k, v in self.headers.items()}
            st.discovery.dump(self.command, path, dict(keep))
            print(f"[gw] {self.command} {path} -> {key} mock")
            return True
        elif is_characters_validator_path(path):
            key, payload = (
                "characters:validator",
                characters_validator_response(st.cfg.discovery_dir),
            )
        elif is_characters_path(path):
            key, payload = "characters", characters_response(st.cfg.discovery_dir)
        elif is_privacy_path(path):
            key, payload = "privacy", privacy_response(st.cfg.discovery_dir)
        elif is_queue_path(path):
            key, payload = "queue", queue_response(
                st.cfg.discovery_dir,
                path,
                region_from_headers(self.headers),
                self.headers.get("X-Azoth-Instance"),
            )
        elif is_entitlements_sync_path(path):
            key, payload = (
                "entitlements:sync",
                entitlements_sync_response(st.cfg.discovery_dir),
            )
        elif is_entitlements_path(path):
            key, payload = (
                "entitlements",
                entitlements_response(st.cfg.discovery_dir),
            )
        elif is_images_path(path):
            payload = images_response(st.cfg.discovery_dir)
            st.metrics.hit("images")
            print(f"[gw] {self.command} {path} -> images placeholder")
            self.send_response(200)
            self.send_header("Content-Type", "image/dds")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            return True
        else:
            return False
        st.metrics.hit(key)
        keep = {k: v[:200] for k, v in self.headers.items()}
        st.discovery.dump(self.command, path, dict(keep))
        print(f"[gw] {self.command} {path} -> {key} mock")
        self._send_body(payload)
        return True

    def _route(self) -> None:
        st = self.state
        path = self.path
        if path in ("/healthz", "/health"):
            st.metrics.hit("health")
            body = b'{"ok":true}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        if path == "/metrics":
            st.metrics.hit("metrics")
            body = st.metrics.snapshot()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        cms_key = is_cms_path(path)
        if cms_key == "motd":
            # Registry-driven MOTD (hot-reloads with data/worlds.json).
            st.metrics.hit("cms:motd")
            motd = motd_body(st.cfg.discovery_dir)
            self._send_json(motd, etag_for(motd), max_age=60)
            return
        if cms_key and cms_key in st.cms:
            st.metrics.hit(f"cms:{cms_key}")
            doc = st.cms[cms_key]
            self._send_json(doc.body, doc.etag, max_age=60)
            return
        if is_channel_path(path):
            st.metrics.hit("channel")
            body, etag = channel_response(st.cfg.discovery_dir)
            self._send_json(body, etag, max_age=30)
            return
        if self.path == "/ping":
            # Region latency probe: client GETs /ping on the DynamoDB host.
            body = b"healthy: dynamodb.eu-central-1.amazonaws.com"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        if self.command == "POST" and self.path in ("/", ""):
            # DynamoDB mock: client POSTs SigV4'd queries (worlds tables).
            body = getattr(self, "_req_body", b"")
            target = self.headers.get("X-Amz-Target", "")
            print(f"[gw] DYNAMODB target={target!r} body={body[:300]!r}")
            resp = b'{"Items":[],"Count":0,"ScannedCount":0}'
            self.send_response(200)
            self.send_header("Content-Type", "application/x-amz-json-1.0")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return
        s3 = s3_body(path) if is_s3_path(path) else None
        if s3 is not None:
            st.metrics.hit("s3")
            print(f"[gw] {self.command} {path} {len(s3)}B -> s3 remoteCfg mock")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(s3)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(s3)
            return
        if is_credentials_path(path):
            st.metrics.hit("omni:credentials")
            keep = {k: v[:200] for k, v in self.headers.items()}
            st.discovery.dump(self.command, path, dict(keep))
            payload = credentials_response(st.cfg.discovery_dir)
            print(f"[gw] {self.command} {path} -> omni credentials mock")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            req_id = self.headers.get("X-Amzn-Requestid") or "azoth-" + uuid.uuid4().hex[:8]
            self.send_header("x-amzn-RequestId", req_id)
            self.send_header("x-amz-apigw-id", "azoth-apigw/" + uuid.uuid4().hex[:8])
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            return
        if self._try_game_mocks():
            return
        # discovery
        st.metrics.hit("discovery")
        keep = {k: v[:200] for k, v in self.headers.items()}
        n = st.discovery.dump(self.command, path, dict(keep))
        body = (
            json.dumps({"ok": False, "error": "unknown-path", "n": n, "path": path}) + "\n"
        ).encode()
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route()

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""
        self._az_req_body = body  # full-traffic capture
        st = self.state
        keep = {k: v[:200] for k, v in self.headers.items()}
        if is_tokens_path(self.path):
            st.metrics.hit("omni:tokens")
            st.discovery.dump(self.command, self.path, dict(keep), body)
            payload = tokens_response(st.cfg.discovery_dir)
            print(f"[gw] POST {self.path} {len(body)}B -> omni tokens mock")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            req_id = self.headers.get("X-Amzn-Requestid") or "azoth-" + uuid.uuid4().hex[:8]
            self.send_header("x-amzn-RequestId", req_id)
            self.send_header("x-amz-apigw-id", "azoth-apigw/" + uuid.uuid4().hex[:8])
            self.end_headers()
            self.wfile.write(payload)
            return
        if is_credentials_path(self.path):
            st.metrics.hit("omni:credentials")
            st.discovery.dump(self.command, self.path, dict(keep), body)
            payload = credentials_response(st.cfg.discovery_dir)
            print(f"[gw] POST {self.path} {len(body)}B -> omni credentials mock")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            req_id = self.headers.get("X-Amzn-Requestid") or "azoth-" + uuid.uuid4().hex[:8]
            self.send_header("x-amzn-RequestId", req_id)
            self.send_header("x-amz-apigw-id", "azoth-apigw/" + uuid.uuid4().hex[:8])
            self.end_headers()
            self.wfile.write(payload)
            return
        if self._try_game_mocks():
            return
        # Unknown POST/PUT/DELETE: dump + clean 404 until mocked.
        st.metrics.hit("discovery")
        n = st.discovery.dump(self.command, self.path, dict(keep), body)
        print(f"[gw] POST {self.path} {len(body)}B -> discovery #{n}")
        payload = (
            json.dumps({"ok": False, "error": "unknown-path", "n": n, "path": self.path}) + "\n"
        ).encode()
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_PUT(self) -> None:
        self.do_POST()

    def do_DELETE(self) -> None:
        self.do_POST()


def serve(cfg: Config) -> ThreadingHTTPServer:
    state = State(cfg)
    Handler.state = state
    srv = ThreadingHTTPServer((cfg.host, cfg.port), Handler)
    srv.daemon_threads = True
    print(f"[gw] listening {cfg.host}:{cfg.port} schemas={cfg.schemas}")
    return srv


def run_forever(cfg: Config) -> None:
    serve(cfg).serve_forever()


def run_in_thread(cfg: Config) -> tuple[ThreadingHTTPServer, threading.Thread]:
    srv = serve(cfg)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, th
