"""The live-session preflight: refuse to launch against a world with the wrong replay config.

WHY THIS EXISTS. Measured 2026-10-27: a session was launched against a world that had
come up with `AZOTH_REPLAY_LOCAL_PLAYER_UUID` unset, so its own `config` event logged
`replay_local_player_uuid: off`. The client then hung on the loading screen (0
`[WARNING] Slice:` lines) and the operator's screen stayed black for the whole attempt.
The lever must be set on the WORLD process, so the check reads what the world logged, not
this process's environment. These tests pin the pure logic on synthetic logs, where the
right answer is known rather than measured.

The module under test lives under `scripts/session/`; this directory is only used because
it is the repo's runnable unittest home (each file runs as `python <file>`).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[1]


def load_tool():
    for entry in (str(TOOLS), str(TOOLS / "type")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    sys.path.insert(0, str(REPO / "services" / "world" / "src"))
    spec = importlib.util.spec_from_file_location(
        "private_run_under_test", REPO / "scripts" / "session" / "private-run.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config_line(**overrides) -> str:
    row = {"ts": "2026-10-27T21:40:21Z", "event": "config",
           "replay_local_player_uuid": "character", "state_stream": True}
    row.update(overrides)
    return "[rep] " + json.dumps(row)


class WorldReplayConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def _log(self, *lines: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8")
        for line in lines:
            handle.write(line + "\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        return Path(handle.name)

    def test_the_last_config_event_wins(self):
        """The world logs one config per start, so the newest describes the live world."""
        path = self._log(
            config_line(ts="2026-10-27T18:07:41Z"),
            '[rep] {"event": "heartbeat"}',
            config_line(ts="2026-10-27T21:40:21Z", replay_local_player_uuid="off"),
        )
        self.assertEqual(self.tool.world_replay_config(path)["ts"], "2026-10-27T21:40:21Z")
        self.assertEqual(self.tool.world_replay_config(path)["replay_local_player_uuid"], "off")

    def test_a_log_without_a_config_event_is_none(self):
        self.assertIsNone(self.tool.world_replay_config(self._log('[rep] {"event": "heartbeat"}')))

    def test_a_missing_log_is_none(self):
        self.assertIsNone(self.tool.world_replay_config(Path("does-not-exist-world.log")))

    def test_a_malformed_config_line_does_not_raise(self):
        path = self._log('[rep] {"event": "config", broken', config_line())
        cfg = self.tool.world_replay_config(path)
        self.assertIsNotNone(cfg, "the good line after the broken one must still be read")


class PreflightTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def _log(self, *lines: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8")
        for line in lines:
            handle.write(line + "\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        return Path(handle.name)

    def test_the_mandatory_lever_present_passes(self):
        self.assertIsNone(self.tool.preflight(self._log(config_line())))

    def test_the_mandatory_lever_off_fails_with_a_usable_message(self):
        problem = self.tool.preflight(
            self._log(config_line(replay_local_player_uuid="off"))
        )
        self.assertIsNotNone(problem, "a world with the lever off must refuse to launch")
        self.assertIn("replay_local_player_uuid", problem)
        self.assertIn("AZOTH_REPLAY_LOCAL_PLAYER_UUID", problem)

    def test_no_world_config_does_not_block(self):
        """A world that has not logged a config yet must not be a false refusal."""
        self.assertIsNone(self.tool.preflight(self._log('[rep] {"event": "heartbeat"}')))


if __name__ == "__main__":
    unittest.main()
