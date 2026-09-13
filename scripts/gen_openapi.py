#!/usr/bin/env python3
"""Generate an OpenAPI 3.1 document from captured gateway traffic.

Reads services/gateway/traffic.jsonl (written by routes/traffic.py) and writes
research/atlas/openapi.json: one path entry per endpoint family, methods,
observed request/response example schemas.

Usage:
  python scripts/gen_openapi.py                 # from traffic.jsonl
  python az.py doc                              # same thing
"""

from __future__ import annotations

import json
import sys
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRAFFIC = REPO / "services" / "gateway" / "traffic.jsonl"
OUT = REPO / "research" / "atlas" / "openapi.json"


def infer_schema(value, depth: int = 0) -> dict:
    """Naive JSON -> JSON-Schema-ish. Examples stay inline; types are hints."""
    if depth > 6:
        return {}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        if value:
            return {"type": "array", "items": infer_schema(value[0], depth + 1)}
        return {"type": "array"}
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {k: infer_schema(v, depth + 1) for k, v in value.items()},
        }
    return {}


def body_schema(entry: dict, key: str) -> dict | None:
    body = entry.get(key) or {}
    if "json" in body:
        return infer_schema(body["json"])
    if "text" in body:
        return {"type": "string"}
    return None  # b64/missing: skip (opaque or HEAD)


def main() -> int:
    if not TRAFFIC.exists():
        print(f"no traffic log at {TRAFFIC} — run the gateway and use the game first")
        return 1
    families: dict[str, dict] = {}
    with TRAFFIC.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            norm = rec.get("norm") or rec.get("path", "/")
            fam = families.setdefault(
                norm, {"methods": set(), "example": None, "status": set()}
            )
            fam["methods"].add(rec.get("method", "GET"))
            fam["status"].add(rec.get("status", 0))
            if fam["example"] is None and (rec.get("req_body") or rec.get("resp_body")):
                fam["example"] = rec

    paths: OrderedDict[str, dict] = OrderedDict()
    for norm in sorted(families):
        fam = families[norm]
        item: dict = {}
        for method in sorted(fam["methods"]):
            op: dict = {"summary": norm.strip("/"), "tags": ["observed"]}
            op["x-observed-status"] = sorted(s for s in fam["status"] if s)
            if fam["example"]:
                req = body_schema(fam["example"], "req_body")
                if req and method in ("POST", "PUT", "PATCH"):
                    op["requestBody"] = {
                        "content": {"application/json": {"schema": req}}
                    }
                resp = body_schema(fam["example"], "resp_body")
                status = next(iter(sorted(fam["status"]))) or 200
                content = {"application/json": {"schema": resp}} if resp else {}
                op["responses"] = {str(status or 200): {"content": content}}
            else:
                op["responses"] = {"200": {}}
            item[method.lower()] = op
        paths[norm] = item

    doc = {
        "openapi": "3.1.0",
        "info": {
            "title": "Azoth — observed New World client traffic",
            "version": "0.1.0",
            "description": (
                "Auto-generated from gateway captures (services/gateway/traffic.jsonl). "
                "Paths are endpoint families: volatile ids collapsed to {id}. Curated "
                "field-level notes live in endpoints.json / models.json."
            ),
        },
        "paths": paths,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"{len(paths)} endpoint families -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
