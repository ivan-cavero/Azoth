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
from azoth_gateway.routes.identity import (
    AZOTH_CHARACTER_ID,
    AZOTH_PERSONA,
    AZOTH_STEAM_ID,
)

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
        self.assertIn("fra-prod", body.decode())
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
        self.assertEqual(doc["personaId"], AZOTH_PERSONA)
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
            doc = json.loads(body.decode())
            self.assertIs(doc["enable-anticheat"], False)
            # Official captured sizes are a floor: game-security keys may
            # grow the body past the capture (ProductId 190 -> ~500).
            self.assertGreaterEqual(len(body), size)

    def test_s3_worldid_nests_game_security(self):
        path = (
            "/applications/publicGameplay/configuration-sets/WorldId/"
            f"{WORLD_ID}/6031%3B6004151"
        )
        with urllib.request.urlopen(f"http://127.0.0.1:18080{path}") as r:
            self.assertEqual(r.status, 200)
            doc = json.loads(r.read().decode())
        self.assertIn("game-security", doc)
        self.assertIs(doc["game-security"]["enable-anticheat"], False)
        # FUN_146193620 looks up the bare key on the layer document.
        self.assertIs(doc["enable-anticheat"], False)
        self.assertIs(doc["game-security.enable-anticheat"], False)

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
        self.assertEqual(acc["personaId"], AZOTH_PERSONA)
        self.assertEqual(pa["personaId"], AZOTH_PERSONA)
        self.assertEqual(pa["identityId"], AZOTH_STEAM_ID)

    def test_getlogininfo_mock(self):
        code, _, body = get(18080, "/prod/game/getlogininfo/jwt/omni")
        self.assertEqual(code, 200)
        doc = json.loads(body.decode())
        # Two schemas in one body (first-light-verified, FUN_1474e01e0 /
        # FUN_1474e42e0 / FUN_144f40780):
        # - top-level lowercase `worlds` -> dropdown, INT enums,
        # - `LoginInfoList` OBJECT with PascalCase Worlds/Characters -> gate.
        self.assertIn("worlds", doc)
        self.assertIn("recommendedWorlds", doc)
        lil = doc["LoginInfoList"]
        self.assertIsInstance(lil, dict)
        world = lil["Worlds"][0]
        self.assertEqual(world["WorldName"], WORLD["name"])
        self.assertEqual(world["WorldStatus"], WORLD["status"])
        self.assertEqual(world["WorldType"], "OpenWorld")
        self.assertEqual(world["PublicStatusCode"], 0)
        self.assertEqual(doc["worlds"][0]["publicName"], WORLD["displayName"])
        self.assertEqual(doc["worlds"][0]["status"], 1)
        self.assertNotIn("name", doc["worlds"][0])  # extra keys drop the object
        self.assertEqual(lil["Characters"][0]["WorldId"], world["WorldId"])
        self.assertEqual(lil["Characters"][0]["Name"], WORLD.get("characterName", "Azoth_Dev"))
        self.assertEqual(lil["Characters"][0]["CharacterId"], AZOTH_CHARACTER_ID)
        self.assertEqual(lil["Characters"][0]["PersonaId"], AZOTH_PERSONA)

    def test_getlogininfo_region_scoped(self):
        # The client talks to the gateway-CF of ITS region; the world list is
        # scoped so each region only sees its own worlds.
        hdrs = {"X-Forwarded-Host": "d1w0bfy6smo4d1.cloudfront.net"}  # fra-prod
        _, _, body = get(18080, "/prod/game/getlogininfo/jwt/omni", hdrs)
        doc = json.loads(body.decode())
        names = [w["publicName"] for w in doc["worlds"]]
        self.assertEqual(names, ["Everfall"])  # fra-prod has exactly one world
        self.assertEqual(doc["LoginInfoList"]["Worlds"][0]["WorldName"], "everfall")
        # Another region -> its own world.
        hdrs["X-Forwarded-Host"] = "d2oeuvxi3kfsrw.cloudfront.net"  # iad-prod
        _, _, body = get(18080, "/prod/game/getlogininfo/jwt/omni", hdrs)
        names = [w["publicName"] for w in json.loads(body.decode())["worlds"]]
        self.assertEqual(names, ["First Light"])
        # Unknown host -> falls back to every world (tests' Host is 127.0.0.1).
        _, _, body = get(18080, "/prod/game/getlogininfo/jwt/omni")
        self.assertEqual(len(json.loads(body.decode())["worlds"]), 5)

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
        # Initial enqueue issues a parseable ticket.
        req = urllib.request.Request(
            "http://127.0.0.1:18080/prod/game/login/queue/v2/enqueue",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 200)
            doc = json.loads(r.read().decode())
        # LoginQueueResponse envelope (first-light RE: FUN_1474e4f20).
        t = doc["LoginQueueResponse"]
        self.assertTrue(t["TicketId"])
        self.assertEqual(t["Signature"], f"sig:{t['TicketId']}")
        self.assertEqual(t["RepAddress"], "127.0.0.1:9000")
        self.assertEqual(t["WorldName"], WORLD["name"])
        self.assertEqual(t["WorldId"], WORLD["id"])
        self.assertEqual(t["CharacterId"], AZOTH_CHARACTER_ID)
        self.assertEqual(t["PersonaId"], AZOTH_PERSONA)
        self.assertEqual(t["SteamUserId"], AZOTH_STEAM_ID)

        # Refresh path (with ticket id) returns the READY envelope whose
        # Token carries the ticket — this moves the client to the REP.
        with urllib.request.urlopen(
            "http://127.0.0.1:18080/prod/game/login/queue/v2/"
            "86ae8332-ed32-420e-985c-61011022847a/jwt/omni?tokenVersion=10"
        ) as r:
            doc = json.loads(r.read().decode())
        q = doc["LoginQueueResponse"]
        self.assertEqual(q["Position"], 0)
        self.assertEqual(q["QueueName"], "eu-central-1")
        self.assertEqual(q["Token"]["RepAddress"], "127.0.0.1:9000")
        self.assertTrue(q["Token"]["Signature"])

    def test_characters_list_and_validator(self):
        code, _, body = get(18080, "/characters")
        self.assertEqual(code, 200)
        doc = json.loads(body.decode())
        self.assertIsInstance(doc, list)
        self.assertEqual(doc[0]["characterId"], AZOTH_CHARACTER_ID)
        self.assertTrue(doc[0]["name"])
        self.assertEqual(doc[0]["worldId"], WORLD_ID)

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
        self.assertEqual(doc["fra-prod"]["displayName"], "EU Central")
        self.assertEqual(doc["fra-prod"]["localizedName"], "EU Central")
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
            lil = json.loads(body.decode())["LoginInfoList"]
            self.assertEqual(lil["Worlds"][0]["WorldStatus"], "MAINTENANCE")
            self.assertFalse(lil["Worlds"][0]["IsRecommended"])
            self.assertEqual(lil["Worlds"][0]["WorldType"], "OpenWorld")
            _, _, body = get(18080, "/prod/game/worlds/list/jwt/omni")
            self.assertEqual(json.loads(body.decode())["worlds"][0]["status"], "MAINTENANCE")

            _, _, body = get(18080, "/motd/worlds_STEAM_APP_ID.1063730.json")
            motd = json.loads(body.decode())
            self.assertEqual(motd["worlds"][WORLD_ID]["announcement"], "Back at 21:00 UTC")

            # Queue keeps serving a parseable ticket off the fallback world.
            _, _, body = get(18080, "/prod/game/login/queue/v2/enqueue")
            self.assertEqual(
                json.loads(body.decode())["LoginQueueResponse"]["WorldName"], "azoth-1"
            )
        finally:
            override.unlink()
        # Hot-reload back: packaged registry (ACTIVE) is served again.
        _, _, body = get(18080, "/prod/game/getlogininfo/jwt/omni")
        self.assertEqual(
            json.loads(body.decode())["LoginInfoList"]["Worlds"][0]["WorldStatus"], "ACTIVE"
        )
        _, _, body = get(18080, "/motd/worlds_STEAM_APP_ID.1063730.json")
        self.assertEqual(json.loads(body.decode())["worlds"][WORLD_ID]["announcement"], "")


if __name__ == "__main__":
    unittest.main()
