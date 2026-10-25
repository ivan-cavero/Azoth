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


class TestTruncation(unittest.TestCase):
    def test_oversize_json_stays_valid(self):
        from azoth_gateway.routes.traffic import _body_field

        big = {"token": "x" * 5000, "small": 1}
        body = json.dumps(big).encode()
        out = _body_field(body, 1024)
        self.assertIn("json", out)  # never degrades to padded "text"
        self.assertTrue(out.get("truncated"))
        json.dumps(out["json"])  # still serializable
        self.assertLessEqual(len(json.dumps(out["json"])), 1100)

    def test_small_json_not_flagged(self):
        from azoth_gateway.routes.traffic import _body_field

        out = _body_field(b'{"a":1}', 1024)
        self.assertEqual(out, {"json": {"a": 1}})


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

    def test_an_empty_session_does_not_erase_the_atlas(self):
        """A fresh run must MERGE into observed-endpoints.json, not replace it.

        MEASURED 2026-10-25: the committed atlas held 99 endpoint families accumulated
        across months. Starting the lab for one short session rewrote the file from only
        that session's hits and deleted 1,359 lines. The loss is silent: the file stays
        valid JSON and every reader just sees a smaller world.
        """
        tmp = pathlib.Path(tempfile.mkdtemp())
        atlas_path = tmp / "observed.json"
        atlas_path.write_text(
            json.dumps(
                {
                    "$comment": "pre-existing",
                    "generated": "2026-10-22T21:50:45Z",
                    "endpoints": [
                        {
                            "path": "/prod/game/old-family",
                            "methods": ["GET"],
                            "hits": 8223,
                            "first": "2026-09-13T15:07:54Z",
                            "last": "2026-10-22T21:50:45Z",
                            "example": {"response": {"kept": True}},
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        from azoth_gateway.routes.traffic import TrafficLog

        rec = TrafficLog(jsonl_path=tmp / "traffic.jsonl", atlas_path=atlas_path)
        rec.record_full(
            method="GET",
            path="/prod/game/worlds/86ae8332-ed32-420e-985c-61011022847a/characters",
            status=200,
            req_headers={},
            req_body=b"",
            resp_body=b"{}",
        )

        atlas = json.loads(atlas_path.read_text(encoding="utf-8"))
        fams = {e["path"]: e for e in atlas["endpoints"]}
        # The new family is present...
        self.assertIn("/prod/game/worlds/{id}/characters", fams)
        # ...and the pre-existing family survived with its accumulated count and example.
        self.assertIn("/prod/game/old-family", fams)
        self.assertEqual(fams["/prod/game/old-family"]["hits"], 8223)
        self.assertEqual(fams["/prod/game/old-family"]["first"], "2026-09-13T15:07:54Z")
        self.assertEqual(fams["/prod/game/old-family"]["example"], {"response": {"kept": True}})

    def test_gen_openapi(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gen_openapi", REPO / "scripts" / "ops" / "gen_openapi.py"
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
