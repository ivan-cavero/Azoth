"""Traffic capture + OpenAPI generation tests (stdlib unittest)."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REPO = ROOT.parents[1]


def _schema_for(value, depth=0):
    """Mirror of gen_openapi.infer_schema (kept local to avoid script import)."""
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        return {"type": "array"}
    if isinstance(value, dict):
        return {"type": "object", "properties": list(value.keys())}
    return {}


class TestNormalize(unittest.TestCase):
    def test_uuid_and_tokens_collapse(self):
        from azoth_gateway.routes.traffic import normalize_path

        self.assertEqual(
            normalize_path(
                "/prod/game/worlds/86ae8332-ed32-420e-985c-61011022847a/characters/jwt/omni"
            ),
            "/prod/game/worlds/{id}/characters/jwt/omni",
        )
        self.assertEqual(
            normalize_path("/STEAM_APP_ID.1063730.json"),
            "/STEAM_APP_ID.json",
        )
        self.assertEqual(
            normalize_path(
                "/prod/game/login/queue/v2/86ae8332-ed32-420e-985c-61011022847a_7978b8a9-1234-5678-9abc-def012345678/jwt/omni"
            ),
            "/prod/game/login/queue/v2/{id}/jwt/omni",
        )


class TestCaptureEndToEnd(unittest.TestCase):
    def test_full_capture_and_openapi(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        os.environ["AZOTH_TRAFFIC_JSONL"] = str(tmp / "traffic.jsonl")
        os.environ["AZOTH_ATLAS_JSONL"] = str(tmp / "observed.json")
        os.environ.pop("AZOTH_NO_TRAFFIC", None)

        from azoth_gateway.app import run_in_thread
        from azoth_gateway.config import Config

        cfg = Config(port=18084, discovery_dir=tmp)
        srv, _th = run_in_thread(cfg)
        try:
            post = urllib.request.Request(
                "http://127.0.0.1:18084/games/new-world/tokens",
                data=b"{}",
                method="POST",
            )
            body = urllib.request.urlopen(post).read()
            self.assertIn(b"accessToken", body)
        finally:
            srv.shutdown()

        recs = [json.loads(line) for line in (tmp / "traffic.jsonl").read_text().splitlines()]
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        # Full capture: request headers, request body, pure-JSON response body.
        self.assertIn("req_headers", rec)
        self.assertIn("req_body", rec)
        self.assertIn("json", rec["resp_body"])
        self.assertIn("accessToken", rec["resp_body"]["json"])
        self.assertEqual(rec["status"], 200)
        self.assertEqual(rec["norm"], "/games/new-world/tokens")
        # Sensitive headers redacted.
        for k, v in rec["req_headers"].items():
            if k.lower() in ("authorization", "x-nw-auth"):
                self.assertEqual(v, "<redacted>")
        # Atlas summary got the family with an example.
        atlas = json.loads((tmp / "observed.json").read_text(encoding="utf-8"))
        fams = {e["path"]: e for e in atlas["endpoints"]}
        self.assertIn("/games/new-world/tokens", fams)
        ex = fams["/games/new-world/tokens"]["example"]
        self.assertIn("request", ex)
        self.assertIn("response", ex)

    def test_gen_openapi(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gen_openapi", REPO / "scripts" / "gen_openapi.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "traffic.jsonl").write_text(
            json.dumps(
                {
                    "n": 1,
                    "method": "POST",
                    "path": "/games/new-world/tokens",
                    "norm": "/games/new-world/tokens",
                    "status": 200,
                    "req_body": {"json": {}},
                    "resp_body": {"json": {"accessToken": "x", "expiresIn": 3600}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        out = tmp / "openapi.json"
        orig_traffic, orig_out = mod.TRAFFIC, mod.OUT
        mod.TRAFFIC, mod.OUT = tmp / "traffic.jsonl", out  # type: ignore[attr-defined]
        try:
            rc = mod.main()
        finally:
            mod.TRAFFIC, mod.OUT = orig_traffic, orig_out  # type: ignore[attr-defined]
        self.assertEqual(rc, 0)
        doc = json.loads(out.read_text(encoding="utf-8"))
        op = doc["paths"]["/games/new-world/tokens"]["post"]
        self.assertIn("requestBody", op)
        props = op["responses"]["200"]["content"]["application/json"]["schema"]["properties"]
        self.assertIn("accessToken", props)
        self.assertIn("expiresIn", props)


if __name__ == "__main__":
    unittest.main()
