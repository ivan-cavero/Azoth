"""Tests for the server-owned inventory: answering OnQueryInventories from server state.

WHY THIS EXISTS. The client asks for its inventories and the server answers with a captured body,
replayed verbatim. This is the first place the server owns that answer.

MEASURED 2026-10-19 from the committed replay (seq 0x29, 99 819 bytes): **428 entries**, each anchored
by the marker `00 01 82 5a` at a fixed offset, with a container name (`w-world|`), a type name
(`SkinCollection`), a GUID, flags, and a decimal-ASCII item id.

THE TRAP THIS FILE PINS: an entry is **223 + id_length** bytes - 233 for a 10-digit id, 232 for 9, 231
for 8. A parser that assumes a fixed stride reads 19 of 428 entries and then walks into padding. The
walk must anchor on the marker.

THE DECISIVE PROPERTY: re-encoding the captured entries is **byte-identical** to the capture. That is
what makes it safe to change one entry's id and send the result.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT / "src")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from azoth_world import inventory  # noqa: E402


def _bodies() -> tuple[bytes, bytes]:
    from azoth_world.javelin.replay_store import ReplayStore

    store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
    big = next(m.body for m in store.messages if m.type_id == 0x16A0 and len(m.body) > 1000)
    small = next(m.body for m in store.messages if m.type_id == 0x16A0 and len(m.body) < 1000)
    return big, small


class TestParse(unittest.TestCase):
    def test_the_populated_body_has_428_entries(self) -> None:
        big, _ = _bodies()
        self.assertEqual(len(inventory.split_entries(big)), 428)

    def test_the_empty_body_has_none(self) -> None:
        _, small = _bodies()
        self.assertEqual(inventory.split_entries(small), [])
        self.assertEqual(len(small), 153)

    def test_the_fields_are_readable(self) -> None:
        big, _ = _bodies()
        first = inventory.split_entries(big)[0]
        self.assertEqual(first.container, b"w-world|")
        self.assertEqual(first.type_name, b"SkinCollection")
        self.assertEqual(first.id_text, "1027224182")

    def test_the_sizes_vary_with_the_id_length(self) -> None:
        """THE TRAP: 223 + id_length. A fixed stride reads 19 of 428 entries."""
        import collections

        big, _ = _bodies()
        sizes = collections.Counter(len(e.raw) for e in inventory.split_entries(big))
        self.assertEqual(sizes[233], 338, "10-digit ids")
        self.assertEqual(sizes[232], 79, "9-digit ids")
        self.assertEqual(sizes[231], 10, "8-digit ids")

    def test_every_entry_carries_its_marker(self) -> None:
        big, _ = _bodies()
        for entry in inventory.split_entries(big):
            self.assertIn(inventory.ENTRY_MARKER, entry.raw)


class TestRoundTrip(unittest.TestCase):
    def test_re_encoding_is_byte_identical(self) -> None:
        """The decisive property: an unmodified list reproduces the capture exactly."""
        big, _ = _bodies()
        entries = inventory.split_entries(big)
        self.assertEqual(inventory.render_body(big, entries), big)

    def test_the_entries_account_for_the_whole_body(self) -> None:
        big, _ = _bodies()
        entries = inventory.split_entries(big)
        total = inventory.ENTRIES_START + sum(len(e.raw) for e in entries)
        self.assertEqual(total, len(big))


class TestPatchingAnId(unittest.TestCase):
    def test_the_id_can_be_changed(self) -> None:
        big, _ = _bodies()
        entry = inventory.split_entries(big)[0]
        patched = entry.with_id("9999999999")
        self.assertEqual(patched.id_text, "9999999999")

    def test_the_length_byte_follows_the_id(self) -> None:
        """The size is 223 + id_length, so a shorter id must also shorten the entry."""
        big, _ = _bodies()
        entry = inventory.split_entries(big)[0]
        patched = entry.with_id("12345678")
        self.assertEqual(len(patched.raw), len(entry.raw) - 2)
        self.assertEqual(patched.id_text, "12345678")

    def test_the_rest_of_the_entry_is_untouched(self) -> None:
        big, _ = _bodies()
        entry = inventory.split_entries(big)[0]
        patched = entry.with_id("9999999999")
        self.assertEqual(patched.container, entry.container)
        self.assertEqual(patched.type_name, entry.type_name)

    def test_a_patched_list_still_renders(self) -> None:
        big, _ = _bodies()
        entries = inventory.split_entries(big)
        entries[0] = entries[0].with_id("9999999999")
        rendered = inventory.render_body(big, entries)
        reparsed = inventory.split_entries(rendered)
        self.assertEqual(reparsed[0].id_text, "9999999999")
        self.assertEqual(len(reparsed), len(entries))


if __name__ == "__main__":
    unittest.main()


class TestTheGatingBugWasSuppressingTheInventory(unittest.TestCase):
    """A REAL BUG IN THE EXISTING CODE, fixed 2026-10-19 and pinned here.

    `RESPONSE_REQUESTS[0x16A0]` used to be `(0x169D,)`, so `_deferred_decision` held both captured
    inventory responses and then dropped them as "request-not-seen". Measured:

      * the committed capture has **0** client messages of type 0x169D (of 39),
      * no live session ever logged an `inbound-typed` 0x169D,
      * and yet the REAL server sent 0x16A0 at seq 0x28 and 0x29, unsolicited, and the client
        accepted both.

    Requiring a request that never arrives therefore suppressed a legitimate push. The empty tuple
    means "no request required", which is what the capture shows.
    """

    def test_the_inventory_response_requires_no_request(self) -> None:
        from azoth_world import rep

        self.assertEqual(rep.RESPONSE_REQUESTS[0x16A0], ())

    def test_it_is_not_dropped_as_request_not_seen(self) -> None:
        from azoth_world import rep

        decision = rep._deferred_decision(
            type("M", (), {"type_id": 0x16A0})(),
            seen_types=set(),
            now=1_000.0,
            deadline=500.0,   # well past the deadline: it would have been dropped
        )
        self.assertEqual(decision, "send")

    def test_the_capture_really_has_no_query_request(self) -> None:
        """The evidence for the fix, asserted so it cannot silently become false."""
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        client_types = {m.type_id for m in store.messages if m.direction == "W"}
        self.assertNotIn(0x169D, client_types)
        # And the real server sent the response anyway.
        server_responses = [
            m for m in store.messages if m.direction == "R" and m.type_id == 0x16A0
        ]
        self.assertEqual(len(server_responses), 2)


class TestComposeFromTheServersOwnList(unittest.TestCase):
    """The server re-renders the inventory response from its own list of item ids.

    SAFE BY CONSTRUCTION: an unmodified list reproduces the capture byte-for-byte, so switching the
    composition on cannot change behaviour by accident - the only way the bytes differ is the id list.
    """

    def test_an_unmodified_list_reproduces_the_capture(self) -> None:
        from azoth_world import rep

        big, _ = _bodies()
        original = rep.INVENTORY_IDS_FILE
        try:
            rep.INVENTORY_IDS_FILE = str(ROOT / "does-not-exist-ids.txt")
            body, report = rep.compose_inventory_body(big)
            self.assertEqual(body, big)
            self.assertEqual(report["source"], "capture")
            self.assertEqual(report["entries"], 428)
        finally:
            rep.INVENTORY_IDS_FILE = original

    def test_a_file_of_ids_replaces_them(self) -> None:
        import os
        import tempfile

        from azoth_world import rep

        big, _ = _bodies()
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("1111111111\n2222222222\n")
            path = fh.name
        original = rep.INVENTORY_IDS_FILE
        try:
            rep.INVENTORY_IDS_FILE = path
            body, report = rep.compose_inventory_body(big)
            self.assertEqual(report["source"], "file")
            self.assertEqual(report["changed"], 2)
            entries = inventory.split_entries(body)
            self.assertEqual(entries[0].id_text, "1111111111")
            self.assertEqual(entries[1].id_text, "2222222222")
            # The rest are untouched.
            self.assertEqual(entries[2].id_text, "1030849125")
        finally:
            rep.INVENTORY_IDS_FILE = original
            os.unlink(path)

    def test_a_non_numeric_id_is_skipped_not_written(self) -> None:
        import os
        import tempfile

        from azoth_world import rep

        big, _ = _bodies()
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("not-an-id\n")
            path = fh.name
        original = rep.INVENTORY_IDS_FILE
        try:
            rep.INVENTORY_IDS_FILE = path
            body, report = rep.compose_inventory_body(big)
            self.assertEqual(report["changed"], 0)
            self.assertEqual(inventory.split_entries(body)[0].id_text, "1027224182")
        finally:
            rep.INVENTORY_IDS_FILE = original
            os.unlink(path)

    def test_the_empty_form_is_left_alone(self) -> None:
        from azoth_world import rep

        _, small = _bodies()
        body, report = rep.compose_inventory_body(small)
        self.assertEqual(body, small)
        self.assertEqual(report["entries"], 0)

    def test_it_is_off_by_default(self) -> None:
        import inspect

        from azoth_world import rep

        self.assertIn('"AZOTH_INVENTORY_COMPOSE", "0"', inspect.getsource(rep))
