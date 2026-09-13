"""Gateway minimo tests (stdlib unittest, no pytest needed)."""

import json
import pathlib
import struct
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Schemas live in research/ at the monorepo root (services/gateway/tests -> parents[2]).
SCHEMAS = ROOT.parents[1] / "research" / "schemas" / "live"

from azoth_gateway.app import run_in_thread
from azoth_gateway.config import Config

WORLD_ID = "00000000-0000-4000-8000-000000000001"

# Tests follow the registry data (data/worlds.json) so ops edits don't break them.
REGISTRY = json.loads(
    (ROOT / "src" / "azoth_gateway" / "data" / "worlds.json").read_text(encoding="utf-8")
)
WORLD = REGISTRY["worlds"][0]


def get(port: int, path: str, headers: dict | None = None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = Config(
            host="127.0.0.1",
            port=18080,
            schemas=SCHEMAS,
            discovery_dir=pathlib.Path(cls.tmp.name),
        )
        import os
        os.environ["AZOTH_NO_TRAFFIC"] = "1"  # tests must not touch the atlas
        cls.srv, cls.th = run_in_thread(cfg)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def test_health(self):
        code, _, body = get(18080, "/healthz")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_channel_garbage_path(self):
        code, h, body = get(18080, "/STEAM_APP_ID.1.BRANCH.xyz123.json")
        self.assertEqual(code, 200)
        self.assertIn("ETag", h)
        self.assertIn("azoth-1", body.decode())
        # 304 on If-None-Match
        code2, _, _ = get(18080, "/STEAM_APP_ID.1063730.json", {"If-None-Match": h["ETag"]})
        self.assertEqual(code2, 304)

    def test_cms_has_etag(self):
        for p in (
            "/newsstories/STEAM_APP_ID.1063730/metadata.json",
            "/marketingtiles/STEAM_APP_ID.1063730/metadata.json",
            "/motd/worlds_STEAM_APP_ID.1063730.json",
        ):
            code, h, _ = get(18080, p)
            self.assertEqual(code, 200, p)
            self.assertIn("ETag", h, p)

    def test_cms_is_not_channel(self):
        _, ch_h, ch_body = get(18080, "/STEAM_APP_ID.1063730.json")
        for p in (
            "/newsstories/STEAM_APP_ID.1063730/metadata.json",
            "/marketingtiles/STEAM_APP_ID.1063730/metadata.json",
            "/motd/worlds_STEAM_APP_ID.1063730.json",
        ):
            _, h, body = get(18080, p)
            self.assertNotEqual(body, ch_body, p)
            self.assertNotEqual(h.get("ETag"), ch_h.get("ETag"), p)

    def test_unknown_goes_to_discovery(self):
        code, _, body = get(18080, "/prod/some/unknown/route")
        self.assertEqual(code, 404)
        self.assertIn("unknown-path", body.decode())

    def test_credentials_omni_mock(self):
        import json as _json

        for method in ("GET", "POST"):
            data = b"{}" if method == "POST" else None
            req = urllib.request.Request(
                "http://127.0.0.1:18080/prod/credentials/omni",
                data=data,
                headers={"Content-Type": "application/json"},
                method=method,
            )
            with urllib.request.urlopen(req) as r:
                self.assertEqual(r.status, 200)
                doc = _json.loads(r.read().decode())
        # Client parser (RE) reads camelCase; missing key => client crash.
        self.assertTrue(doc["accessKeyId"].startswith("ASIA"))
        self.assertIn("secretAccessKey", doc)
        self.assertIn("sessionToken", doc)
        self.assertIsInstance(doc["expiration"], int)
        self.assertGreater(doc["expiration"], 1_600_000_000)
        self.assertIn("region", doc)
        # Legacy flat copies kept for tooling.
        self.assertTrue(doc["AccessKeyId"].startswith("ASIA"))
        self.assertIn("SecretKey", doc)

    def test_s3_remotecfg_sizes(self):
        for path, size in (
            (
                "/applications/public/configuration-sets/ProductId/STEAM_APP_ID.1063730/versionless",
                190,
            ),
            ("/applications/publicGameplay/configuration-sets/CognitoId/x/versionless", 5887),
        ):
            with urllib.request.urlopen(f"http://127.0.0.1:18080{path}") as r:
                self.assertEqual(r.status, 200)
                body = r.read()
            self.assertEqual(len(body), size)
            json.loads(body.decode())  # still valid JSON

    def test_post_goes_to_discovery(self):
        req = urllib.request.Request(
            "http://127.0.0.1:18080/prod/some/future/endpoint",
            data=b'{"hello":"azoth"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                code, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read()
        self.assertEqual(code, 404)
        self.assertIn("unknown-path", body.decode())

    def test_omni_tokens_mock(self):
        req = urllib.request.Request(
            "http://127.0.0.1:18080/games/new-world/tokens",
            data=b'{"platformIdentityType":"steam"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 200)
            doc = json.loads(r.read().decode())
        # RE-derived shape (see omni.py docstring): any malformed field
        # => SDK result 203. These keys were verified against the client:
        # CreateSession result 0 on 2026-09-09.
        self.assertTrue(doc["accessToken"].count(".") == 2)
        self.assertTrue(doc["fallbackToken"].count(".") == 2)
        self.assertIsInstance(doc["expiresIn"], int)
        self.assertIn("limitedUseToken", doc)
        self.assertIn("isNewAccount", doc)
        self.assertIn("region", doc)
        pa = doc["platformAccount"]
        self.assertEqual(pa["identityType"], "steam")
        self.assertIn("ageGroup", pa)
        self.assertIn("personaId", pa)
        self.assertIn("identityId", pa)
        acc = doc["account"]
        self.assertIn(acc["type"], ("shadow", "full"))
        self.assertIn("ageGroup", acc)
        self.assertTrue(acc["personaId"].startswith("amzn1."))

    def test_getlogininfo_mock(self):
        code, _, body = get(18080, "/prod/game/getlogininfo/jwt/omni")
        self.assertEqual(code, 200)
        doc = json.loads(body.decode())
        # GetLoginInfoResult has LoginInfoList, not Worlds (that's ListWorlds).
        # WorldMetadata wire keys are camelCase (symbols.json
        # worldmetadata_property_table); PascalCase is decorative.
        info = doc["LoginInfoList"][0]
        self.assertEqual(info["name"], WORLD["name"])
        self.assertEqual(info["status"], WORLD["status"])
        self.assertEqual(info["type"], "OpenWorld")
        self.assertEqual(info["publicName"], WORLD["displayName"])
        self.assertEqual(info["characters"], [])
        self.assertEqual(info["RepAddress"], "127.0.0.1:9000")
        self.assertNotIn("Worlds", doc)
        self.assertNotIn("worlds", doc)

    def test_getlogininfo_override_file(self):
        override = pathlib.Path(self.tmp.name) / "getlogininfo.json"
        override.write_text('{"custom":true}\n', encoding="utf-8")
        try:
            code, _, body = get(18080, "/prod/game/getlogininfo/jwt/omni")
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body.decode()), {"custom": True})
        finally:
            override.unlink()

    def test_queue_v2_mock(self):
        # GET and POST both hit the queue mock.
        for method, data in (("GET", None), ("POST", b"{}")):
            req = urllib.request.Request(
                "http://127.0.0.1:18080/prod/game/login/queue/v2/enqueue",
                data=data,
                headers={"Content-Type": "application/json"},
                method=method,
            )
            with urllib.request.urlopen(req) as r:
                self.assertEqual(r.status, 200)
                doc = json.loads(r.read().decode())
            # Fields the live client consumed (client_expect.json).
            self.assertIn("_", doc["ticket"])
            self.assertEqual(doc["RepAddress"], "127.0.0.1:9000")
            self.assertEqual(doc["WorldName"], WORLD["name"])
            self.assertTrue(doc["WorldId"])
            self.assertEqual(doc["location"], "")
            self.assertTrue(doc["CharacterId"])

    def test_characters_list_and_validator(self):
        code, _, body = get(18080, "/characters")
        self.assertEqual(code, 200)
        doc = json.loads(body.decode())
        self.assertIsInstance(doc, list)
        self.assertTrue(doc[0]["characterId"])
        self.assertTrue(doc[0]["name"])

        code, _, body = get(18080, "/characters/validator")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body.decode())["valid"])

    def test_motd_from_registry(self):
        code, _, body = get(18080, "/motd/worlds_STEAM_APP_ID.1063730.json")
        self.assertEqual(code, 200)
        doc = json.loads(body.decode())
        # Registry world id + worldSet names (data/worlds.json).
        self.assertIn(WORLD_ID, doc["worlds"])
        self.assertEqual(doc["worlds"][WORLD_ID]["announcement"], "")
        self.assertEqual(doc["worldSets"][WORLD["worldSet"]]["setName"], WORLD["displayName"])
        self.assertEqual(doc["globalAnnouncement"]["title"], "")

    def test_channel_registry_display_name(self):
        code, _, body = get(18080, "/STEAM_APP_ID.1063730.json")
        self.assertEqual(code, 200)
        doc = json.loads(body.decode())
        # Region names come from the registry, not live @mm_ cluster ids.
        self.assertEqual(doc["azoth-1"]["displayName"], "Azoth EU")
        self.assertEqual(doc["azoth-1"]["localizedName"], "Azoth EU")
        self.assertNotIn("@mm_", body.decode())

    def test_images_dds_placeholder(self):
        code, h, body = get(18080, "/images/newstile2.dds")
        self.assertEqual(code, 200)
        self.assertEqual(h.get("Content-Type"), "image/dds")
        self.assertEqual(body[:4], b"DDS ")
        self.assertEqual(struct.unpack("<I", body[4:8])[0], 124)  # header dwSize
        self.assertEqual(len(body), 256 * 256 * 4 + 128)

    def test_registry_override_hot_reload(self):
        # Ops flow: drop a worlds.json override -> gateway reflects it without
        # restart; remove it -> back to the packaged registry.
        override = pathlib.Path(self.tmp.name) / "worlds.json"
        override.write_text(
            json.dumps(
                {
                    "regions": [
                        {
                            "id": "azoth-1",
                            "displayName": "Azoth-1",
                            "awsRegion": "us-east-1",
                            "status": "ACTIVE",
                        }
                    ],
                    "worlds": [
                        {
                            "id": WORLD_ID,
                            "name": "azoth-1",
                            "regionId": "azoth-1",
                            "displayName": "Azoth-1",
                            "worldSet": "Azoth",
                            "status": "MAINTENANCE",
                            "type": "eWorldType_OpenWorld",
                            "maxPlayers": 500,
                            "repAddress": "127.0.0.1:9000",
                            "announcement": "Back at 21:00 UTC",
                            "version": "1.0.0",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            _, _, body = get(18080, "/prod/game/getlogininfo/jwt/omni")
            info = json.loads(body.decode())["LoginInfoList"][0]
            self.assertEqual(info["status"], "MAINTENANCE")
            self.assertFalse(info["isRecommended"])
            self.assertEqual(info["type"], "OpenWorld")
            _, _, body = get(18080, "/prod/game/worlds/list/jwt/omni")
            self.assertEqual(json.loads(body.decode())["worlds"][0]["status"], "MAINTENANCE")

            _, _, body = get(18080, "/motd/worlds_STEAM_APP_ID.1063730.json")
            motd = json.loads(body.decode())
            self.assertEqual(motd["worlds"][WORLD_ID]["announcement"], "Back at 21:00 UTC")

            # Queue keeps serving a parseable ticket off the fallback world.
            _, _, body = get(18080, "/prod/game/login/queue/v2/enqueue")
            self.assertEqual(json.loads(body.decode())["WorldName"], "azoth-1")
        finally:
            override.unlink()
        # Hot-reload back: packaged registry (ACTIVE) is served again.
        _, _, body = get(18080, "/prod/game/getlogininfo/jwt/omni")
        self.assertEqual(json.loads(body.decode())["LoginInfoList"][0]["status"], "ACTIVE")
        _, _, body = get(18080, "/motd/worlds_STEAM_APP_ID.1063730.json")
        self.assertEqual(json.loads(body.decode())["worlds"][WORLD_ID]["announcement"], "")


if __name__ == "__main__":
    unittest.main()
