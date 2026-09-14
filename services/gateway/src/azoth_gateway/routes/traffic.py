"""Durable full-traffic capture: every request AND response is logged and
summarized into the atlas.

Outputs:
- services/gateway/traffic.jsonl  one JSON line per request: method, path,
  status, request headers/body, response body (gitignored, local only).
- research/atlas/observed-endpoints.json  tracked summary that grows as the
  client hits new endpoint families; includes one captured request/response
  example per family. Feed for scripts/gen_openapi.py.

Paths can be overridden with AZOTH_TRAFFIC_JSONL / AZOTH_ATLAS_JSONL (tests).
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_TOKEN_RE = re.compile(r"^(?:[0-9a-fA-F]{16,}|[A-Za-z0-9_-]{40,}|\d{6,})$")
STEAM_APP_ID = "1063730"
MAX_RAW_BYTES = 64 * 1024  # per body in traffic.jsonl
MAX_EXAMPLE_BYTES = 4 * 1024  # per body example in the atlas summary

SENSITIVE_HEADERS = {"authorization", "x-nw-auth", "x-amz-security-token"}


def _truncate_json(raw: bytes, cap: int) -> tuple[object, bool]:
    """Parse the FULL body, then shrink the decoded object until it fits.

    Truncating the raw bytes first (the old behavior) produced invalid JSON
    that fell through to the "text" branch — hence the padded garbage in
    observed-endpoints.json. Here the body is parsed whole and the resulting
    object is pruned depth-first (longest strings/lists first) so the example
    stays valid JSON. Returns (value, truncated).
    """
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, False

    def size(v: object) -> int:
        return len(json.dumps(v, ensure_ascii=False))

    truncated = False
    while size(value) > cap:
        truncated = True
        if isinstance(value, dict):
            # Prune the longest string/list child first.
            key = max(
                value,
                key=lambda k: (
                    len(value[k]) if isinstance(value[k], (str, list, dict)) else 0
                ),
            )
            child = value[key]
            if isinstance(child, str) and len(child) > 64:
                value[key] = child[:64] + "…<truncated>"
            elif isinstance(child, list) and child:
                value[key] = child[: max(1, len(child) // 2)]
            elif isinstance(child, dict) and child:
                sub = next(iter(child))
                del child[sub]
            else:
                del value[key]
                if not value:
                    break
        elif isinstance(value, list) and value:
            value = value[: max(1, len(value) // 2)]
        elif isinstance(value, str):
            value = value[:cap] + "…<truncated>"
            break
        else:
            break
    return value, truncated


def normalize_path(path: str) -> str:
    """Collapse volatile path segments so one atlas entry = one endpoint family."""
    clean = path.split("?")[0]
    clean = clean.replace(f"STEAM_APP_ID.{STEAM_APP_ID}", "STEAM_APP_ID")
    out = []
    for seg in clean.strip("/").split("/"):
        if not seg:
            continue
        if _UUID_RE.match(seg) or _TOKEN_RE.match(seg):
            out.append("{id}")
        else:
            out.append(seg)
    return "/" + "/".join(out)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _body_field(body: bytes | None, cap: int) -> dict:
    """Encode a body: JSON inline, text inline, or base64 with length.

    JSON is parsed from the FULL body and pruned to `cap` (never sliced raw:
    slicing first yields invalid JSON that degrades to padded "text").
    """
    if not body:
        return {}
    value, truncated = _truncate_json(body, cap)
    if value is not None:
        out: dict = {"json": value}
        if truncated:
            out["truncated"] = True
        return out
    raw = body[:cap]
    try:
        return {"text": raw.decode("utf-8")[:cap]}
    except UnicodeDecodeError:
        return {"b64": base64.b64encode(raw).decode("ascii"), "len": len(body)}


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    out = {}
    for k, v in headers.items():
        out[k] = "<redacted>" if k.lower() in SENSITIVE_HEADERS else v[:200]
    return out


class TrafficLog:
    """Append-only JSONL + growing atlas summary. Best-effort, never raises."""

    def __init__(self, jsonl_path: Path, atlas_path: Path) -> None:
        self.jsonl_path = Path(os.environ.get("AZOTH_TRAFFIC_JSONL") or jsonl_path)
        self.atlas_path = Path(os.environ.get("AZOTH_ATLAS_JSONL") or atlas_path)
        self._lock = threading.Lock()
        self._hits: dict[str, dict] = {}
        self._seq = 0
        # Rebuild counters from any existing jsonl so restarts keep totals.
        try:
            if self.jsonl_path.exists():
                for line in self.jsonl_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines():
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("norm"):
                        self._bump(rec["norm"], rec.get("method", ""), rec.get("ts", ""))
                self._write_atlas()
        except OSError:
            pass

    # -- public -------------------------------------------------------
    def record_full(
        self,
        method: str,
        path: str,
        status: int,
        req_headers: dict[str, str] | None = None,
        req_body: bytes = b"",
        resp_body: bytes = b"",
    ) -> None:
        try:
            norm = normalize_path(path)
            ts = _now()
            with self._lock:
                self._seq += 1
                n = self._seq
            rec: dict = {
                "n": n,
                "ts": ts,
                "method": method,
                "path": path,
                "norm": norm,
                "status": status,
            }
            if req_headers:
                rec["req_headers"] = _safe_headers(req_headers)
            if req_body:
                rec["req_body"] = _body_field(req_body, MAX_RAW_BYTES)
            if resp_body:
                rec["resp_body"] = _body_field(resp_body, MAX_RAW_BYTES)
            with self.jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            self._bump(norm, method, ts, req_body, resp_body)
        except OSError:
            pass

    def _bump(
        self,
        norm: str,
        method: str,
        ts: str,
        req_body: bytes = b"",
        resp_body: bytes = b"",
    ) -> None:
        new_family = norm not in self._hits
        with self._lock:
            entry = self._hits.setdefault(
                norm,
                {
                    "methods": set(),
                    "hits": 0,
                    "first": ts or _now(),
                    "last": ts or _now(),
                },
            )
            entry["hits"] += 1
            if method:
                entry["methods"].add(method)
            entry["last"] = ts or _now()
            # Keep the first GOOD example per family for the atlas/OpenAPI.
            # A family whose first capture exceeded the cap keeps a truncated
            # stub; replace it when a later capture fits whole.
            if new_family or "example" not in entry:
                example: dict = {}
                if req_body:
                    ex = _body_field(req_body, MAX_EXAMPLE_BYTES)
                    if ex:
                        example["request"] = ex
                if resp_body:
                    ex = _body_field(resp_body, MAX_EXAMPLE_BYTES)
                    if ex:
                        example["response"] = ex
                if example:
                    entry["example"] = example
            elif entry["example"].get("response", {}).get("truncated") and resp_body:
                ex = _body_field(resp_body, MAX_EXAMPLE_BYTES)
                if ex and not ex.get("truncated"):
                    entry["example"]["response"] = ex
        self._write_atlas()
        if new_family:
            print(f"[gw] TRAFFIC new endpoint family: {method} {norm}")

    def _write_atlas(self) -> None:
        try:
            self.atlas_path.parent.mkdir(parents=True, exist_ok=True)
            doc = {
                "$comment": (
                    "Auto-generated by the gateway (routes/traffic.py): every endpoint "
                    "family the New World client actually requested, with one captured "
                    "example. OpenAPI rendering: scripts/gen_openapi.py. Curated field "
                    "notes live in endpoints.json / models.json next to this file."
                ),
                "generated": _now(),
                "endpoints": [
                    {
                        "path": norm,
                        "methods": sorted(e["methods"]),
                        "hits": e["hits"],
                        "first": e["first"],
                        "last": e["last"],
                        **({"example": e["example"]} if "example" in e else {}),
                    }
                    for norm, e in sorted(self._hits.items(), key=lambda kv: -kv[1]["hits"])
                ],
            }
            self.atlas_path.write_text(
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError:
            pass
