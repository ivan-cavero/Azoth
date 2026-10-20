"""Tests for server-owned entities: the server decides where an entity is.

WHY THIS EXISTS. Until now every record in the state stream was a captured body forwarded verbatim,
except the local player's own. The server could follow the player but could not put anything of its
OWN into the world. This is the first place it owns an entity's state.

THE TEMPLATE IS A CAPTURED RECORD, and that is deliberate: the record id selects a client handler
(`state + 0x608 + record_id*0x10`) and the fragment type indices select per-component codecs this
project has not decoded, so composing an entity from scratch would mean inventing all of that. The
server starts from a captured entity and changes only its position - the same method that produced
the first authoritative effect for the player (2026-10-14, 0.0000 u).

MEASURED TEMPLATE, record 70 (replay seq 0xb0): 2 fragments, 162-byte payload, the world position
appearing TWICE at payload offsets 6 and 74 as the same big-endian float32 pair.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT / "src")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from azoth_world import entities  # noqa: E402
from azoth_world.javelin import bundle as javelin_bundle  # noqa: E402


class TestTheTemplate(unittest.TestCase):
    """The template is protocol data for this build, pinned so a layout change is visible."""

    def test_record_70_is_the_measured_one(self) -> None:
        t = entities.RECORD_70
        self.assertEqual(t.record_id, 70)
        self.assertEqual(t.position_offsets, (6, 74))
        self.assertEqual(t.payload_length, 162)
        self.assertAlmostEqual(t.captured_position[0], 9375.5410, places=3)
        self.assertAlmostEqual(t.captured_position[1], 2655.7583, places=3)

    def test_it_is_already_in_the_stream(self) -> None:
        """seq 0xb0 is at or above the stream floor, so the client already receives this record.

        That makes the change one variable - the bytes it carries - rather than a new message.
        """
        from azoth_world import rep

        self.assertGreaterEqual(0xB0, rep.STATE_STREAM_MIN_SEQ)

    def test_the_capture_really_has_two_occurrences(self) -> None:
        """The template's two offsets must both hold the captured pair, or the reader is wrong."""
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        body = next(
            m.body for m in store.messages if m.seq == 0xB0 and m.direction == "R"
        )
        payload = javelin_bundle.decode_bundle(body).payload
        self.assertEqual(len(payload), entities.RECORD_70.payload_length)
        self.assertEqual(payload[0], entities.RECORD_70.record_id)
        captured = entities.RECORD_70.captured_bytes()
        self.assertEqual(payload.count(captured), 2)
        for offset in entities.RECORD_70.position_offsets:
            self.assertEqual(payload[offset:offset + 8], captured)


class TestReplacePosition(unittest.TestCase):
    """Rewriting an entity's position, anchored on the captured value."""

    @staticmethod
    def _body() -> bytes:
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        return next(m.body for m in store.messages if m.seq == 0xB0 and m.direction == "R")

    def test_both_occurrences_are_rewritten_together(self) -> None:
        """A body where only one of the two moved would be a body the client never produces."""
        new = (9400.0, 2700.0)
        body, count = entities.replace_position(self._body(), entities.RECORD_70, new)
        self.assertEqual(count, 2)
        payload = javelin_bundle.decode_bundle(body).payload
        for offset in entities.RECORD_70.position_offsets:
            self.assertEqual(
                struct.unpack_from(">ff", payload, offset), new,
                f"offset {offset} must carry the new position",
            )
        self.assertNotIn(entities.RECORD_70.captured_bytes(), payload)

    def test_the_payload_length_does_not_change(self) -> None:
        body, _ = entities.replace_position(
            self._body(), entities.RECORD_70, (1.0, 2.0)
        )
        self.assertEqual(len(body), len(self._body()))

    def test_a_foreign_body_is_returned_untouched(self) -> None:
        """Zero replacements means 'not this entity', so the caller forwards it unchanged."""
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        other = next(m.body for m in store.messages if m.seq == 0xA2 and m.direction == "R")
        body, count = entities.replace_position(
            other, entities.RECORD_70, (1.0, 2.0)
        )
        self.assertEqual(count, 0)
        self.assertEqual(body, other)

    def test_a_body_whose_layout_changed_is_refused(self) -> None:
        """If the capture's value is not where it was measured, do not write anything."""
        original = self._body()
        payload = javelin_bundle.decode_bundle(original).payload
        # Corrupt one occurrence so the count no longer matches the template.
        broken = bytearray(payload)
        broken[6:10] = b"\x00\x00\x00\x00"
        body = javelin_bundle.encode_bundle(1, bytes(broken))
        patched, count = entities.replace_position(body, entities.RECORD_70, (1.0, 2.0))
        self.assertEqual(count, 0)
        self.assertEqual(patched, body)


class TestParsePosition(unittest.TestCase):
    def test_it_parses_a_pair(self) -> None:
        self.assertEqual(entities.parse_position("100.5,200.25"), (100.5, 200.25))
        self.assertEqual(entities.parse_position("100.5;200.25"), (100.5, 200.25))

    def test_a_typo_moves_nothing(self) -> None:
        for bad in ("", "1", "1,2,3", "a,b", "1,,2"):
            self.assertIsNone(entities.parse_position(bad), f"{bad!r} must be refused")

    def test_an_absurd_value_moves_nothing(self) -> None:
        self.assertIsNone(entities.parse_position("1e9,0"))
        self.assertIsNone(entities.parse_position("0,1e9"))


if __name__ == "__main__":
    unittest.main()


class TestDuplicatingAnEntity(unittest.TestCase):
    """Creating an entity, not moving one.

    MEASURED 2026-10-19, decompiled from the client's record dispatcher `FUN_141717fc0`: it looks up
    `state + 0x608 + record_id*0x10` and

      * slot EMPTY   -> CREATION: builds the entity and applies the whole record in one call;
      * slot PRESENT -> UPDATE: applies only when `byte[msg+8]` is zero, else skips silently.

    So a record id the capture never used is a CREATION slot. Re-emitting a captured entity record
    under such an id makes the client build a second entity from the same fragments - the body it
    already parses, with a different handler index.
    """

    @staticmethod
    def _body() -> bytes:
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        return next(m.body for m in store.messages if m.seq == 0xA1 and m.direction == "R")

    def test_a_free_slot_is_accepted(self) -> None:
        body, report = entities.duplicate_entity(self._body(), record_id=95)
        self.assertNotIn("error", report)
        self.assertEqual(report["record_id"], 95)
        self.assertEqual(report["fragments"], 19)
        payload = javelin_bundle.decode_bundle(body).payload
        self.assertEqual(payload[0], 95)
        self.assertEqual(payload[1], 19)

    def test_the_fragments_are_untouched(self) -> None:
        """Only the record id changes, so every undecoded byte stays as the client produced it."""
        original = javelin_bundle.decode_bundle(self._body()).payload
        body, _ = entities.duplicate_entity(self._body(), record_id=96)
        patched = javelin_bundle.decode_bundle(body).payload
        self.assertEqual(patched[2:], original[2:])

    def test_an_id_the_capture_uses_is_refused(self) -> None:
        """Using a captured id would be an UPDATE to an existing entity, not a creation."""
        body, report = entities.duplicate_entity(self._body(), record_id=29)
        self.assertIn("error", report)
        self.assertIn("already allocated", report["error"])
        self.assertEqual(body, self._body())

    def test_it_can_be_placed_somewhere_else(self) -> None:
        captured = (9345.4609375, 2781.259521484375)
        target = (9300.0, 2800.0)
        body, report = entities.duplicate_entity(
            self._body(), record_id=95, position=target, captured_position=captured
        )
        self.assertNotIn("error", report)
        self.assertEqual(report["replacements"], 1)
        payload = javelin_bundle.decode_bundle(body).payload
        self.assertEqual(
            struct.unpack_from(">ff", payload, 238), target
        )

    def test_a_position_that_is_not_there_is_refused(self) -> None:
        """A pair the body does not contain must not be silently ignored.

        NOTE: `(0.0, 0.0)` is NOT a safe "absent" value here - it occurs 9 times in this payload as
        zero padding. The first version of this test used it and failed for that reason.
        """
        body, report = entities.duplicate_entity(
            self._body(), record_id=95, position=(1.0, 2.0), captured_position=(99999.0, 88888.0)
        )
        self.assertIn("error", report)
        self.assertEqual(body, self._body())

    def test_the_captured_ids_are_the_measured_set(self) -> None:
        self.assertIn(29, entities.CAPTURED_RECORD_IDS)
        self.assertIn(1, entities.CAPTURED_RECORD_IDS)
        self.assertNotIn(3, entities.CAPTURED_RECORD_IDS)

    def test_free_slots_start_at_95_not_at_three(self) -> None:
        """The capture-derived set is a LOWER BOUND, and using it chose an occupied slot.

        MEASURED 2026-10-19 on a live world with `frida-record-slots`: the client's slot table
        (`state + 0x608 + record_id*0x10`) has ids **1..94 occupied and 95..255 NULL**. The first
        version of this module derived "free" from the capture, which only ever sees the FIRST
        record of a payload, so it reported 3 as free - and the dispatcher then reported
        `slotEmpty: false` for every send, i.e. the message was an update, not a creation.
        """
        free = entities.free_record_ids()
        self.assertEqual(free[0], 95)
        for occupied in (1, 2, 3, 29, 94):
            self.assertNotIn(occupied, free)
        self.assertEqual(len(free), 256 - 95)

    def test_an_allocated_slot_is_refused_even_when_the_capture_never_showed_it(self) -> None:
        """Slot 3 is the exact id the first attempt used. It is allocated, so it must be refused."""
        body, report = entities.duplicate_entity(self._body(), record_id=3)
        self.assertIn("error", report)
        self.assertIn("already allocated", report["error"])
        self.assertEqual(body, self._body())

    def test_a_genuinely_free_slot_is_accepted(self) -> None:
        body, report = entities.duplicate_entity(self._body(), record_id=95)
        self.assertNotIn("error", report)
        payload = javelin_bundle.decode_bundle(body).payload
        self.assertEqual(payload[0], 95)


class TestTheDuplicateIsWired(unittest.TestCase):
    """The server can arm and re-send a duplicated entity on its own timer.

    WHY A SEPARATE EMITTER: the duplicated record uses a record id the capture never used, so it is
    NOT in `state_stream_all` and the stream would never send it. It is armed once from the source
    record and re-sent on its own period, which is what makes the entity persist - a creation slot
    written once and never refreshed is an entity the client has no reason to keep.
    """

    def test_it_is_off_by_default(self) -> None:
        import inspect

        from azoth_world import rep

        self.assertIn('"AZOTH_NPC_DUPLICATE", "0"', inspect.getsource(rep))

    def test_the_emitter_exists_and_is_called_from_the_tick(self) -> None:
        import inspect

        from azoth_world import rep

        self.assertTrue(hasattr(rep.PeerSession, "maybe_npc_duplicate"))
        self.assertIn("maybe_npc_duplicate", inspect.getsource(rep.PeerSession.tick))

    def test_the_source_record_is_a_character_with_many_fragments(self) -> None:
        """Record 29 has 19 fragments; a structure (record 70) has 2."""
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        source = next(
            m for m in store.messages if m.seq == 0xA1 and m.direction == "R"
        )
        payload = javelin_bundle.decode_bundle(source.body).payload
        self.assertEqual(payload[0], 29)
        self.assertEqual(payload[1], 19)

    def test_the_default_slot_is_free(self) -> None:
        """A captured slot would make the message an update, not a creation."""
        import inspect

        from azoth_world import rep

        source = inspect.getsource(rep)
        self.assertIn('"AZOTH_NPC_DUPLICATE", "0"', source)
        # And the documented example slot, 95, is genuinely free in the client's own table.
        self.assertIn(95, entities.free_record_ids())

class TestCreatingANewActor(unittest.TestCase):
    """A NEW actor, not a moved one.

    MEASURED 2026-10-19: an entity record declares its OWN actor id. In record 29 the slice instance
    at payload offset 642 reads `00 0a 01 03 <remoteplayer.dynamicslice GUID> 00 00 00 02 <16-byte
    actor id>`, and the 48-fragment spawn record carries the same shape at payload offset 29707 with
    the local player's actor id. So creating an entity is: register an actor id with
    `ClientAddEntryMsg`, then send a record whose slice instance points at that actor id.
    """

    @staticmethod
    def _body(seq: int = 0xA1) -> bytes:
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        return next(
            m.body for m in store.messages if m.seq == seq and m.direction == "R"
        )

    def test_client_add_entry_is_the_measured_20_byte_body(self) -> None:
        """`[00 01][a4][16-byte actor id]` - the capture's own bytes, for the player's id."""
        player = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")
        self.assertEqual(
            entities.client_add_entry(player),
            bytes.fromhex("0001a402") + player,
        )
        self.assertEqual(len(entities.client_add_entry(player)), 20)

    def test_client_add_entry_refuses_a_short_id(self) -> None:
        with self.assertRaises(ValueError):
            entities.client_add_entry(bytes(15))

    def test_the_slice_instance_is_where_it_was_measured(self) -> None:
        payload = javelin_bundle.decode_bundle(self._body()).payload
        found = entities.slice_actor_ids(payload)
        self.assertEqual(len(found), 1)
        offset, actor = found[0]
        self.assertEqual(offset, 662)
        self.assertEqual(actor.hex(), "3c757da5b2549230fdd559012f5bb05e")

    def test_the_spawn_record_declares_the_local_player(self) -> None:
        """The same shape carries the LOCAL PLAYER's actor id in the 48-fragment spawn record.

        That is the independent confirmation that this field is the actor id and not a neighbour:
        two different records, two different entities, one shape.
        """
        payload = javelin_bundle.decode_bundle(self._body(0x2A)).payload
        found = entities.slice_actor_ids(payload)
        self.assertEqual(len(found), 1)
        offset, actor = found[0]
        self.assertEqual(offset, 29731)
        self.assertEqual(actor.hex(), "1a954abc4b3185bfbe37c3d8592618e0")

    def test_rewriting_the_actor_id_changes_exactly_16_bytes(self) -> None:
        """Everything undecoded must stay byte-identical, or the client parses a different record."""
        original = javelin_bundle.decode_bundle(self._body()).payload
        new_id = bytes.fromhex("cafebabedeadbeef0123456789abcdef")
        body, report = entities.rewrite_actor_id(self._body(), new_id)
        self.assertNotIn("error", report)
        self.assertEqual(report["replacements"], 1)
        self.assertEqual(report["previous"], ["3c757da5b2549230fdd559012f5bb05e"])
        patched = javelin_bundle.decode_bundle(body).payload
        self.assertEqual(len(patched), len(original))
        differing = sum(1 for a, b in zip(original, patched) if a != b)
        self.assertEqual(differing, 16)
        self.assertEqual(entities.slice_actor_ids(patched)[0][1], new_id)

    def test_it_refuses_a_record_with_no_slice_instance(self) -> None:
        """Record 70 (a structure, 2 fragments) declares no actor, so there is nothing to rewrite."""
        body, report = entities.rewrite_actor_id(self._body(0xB0), bytes(16))
        self.assertIn("error", report)
        self.assertEqual(body, self._body(0xB0))

    def test_it_refuses_to_write_the_id_it_already_has(self) -> None:
        """A no-op write would be reported as a success and prove nothing."""
        payload = javelin_bundle.decode_bundle(self._body()).payload
        current = entities.slice_actor_ids(payload)[0][1]
        body, report = entities.rewrite_actor_id(self._body(), current)
        self.assertIn("error", report)
        self.assertEqual(body, self._body())

    def test_it_refuses_a_short_actor_id(self) -> None:
        body, report = entities.rewrite_actor_id(self._body(), bytes(8))
        self.assertIn("error", report)
        self.assertEqual(body, self._body())

class TestACreatedActorIsTwoMessages(unittest.TestCase):
    """The full creation, composed end to end: a registration plus a record under a free slot."""

    def test_the_pair_is_self_consistent(self) -> None:
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        source = next(m.body for m in store.messages if m.seq == 0xA1 and m.direction == "R")
        actor = bytes.fromhex("cafebabedeadbeef0123456789abcdef")
        slot = 95

        registration = entities.client_add_entry(actor)
        self.assertEqual(registration[:4], bytes.fromhex("0001a402"))

        moved, moved_report = entities.duplicate_entity(
            source,
            record_id=slot,
            position=(9350.0, 2780.0),
            captured_position=(9345.4609375, 2781.259521484375),
        )
        self.assertNotIn("error", moved_report)
        moved, actor_report = entities.rewrite_actor_id(moved, actor)
        self.assertNotIn("error", actor_report)

        payload = javelin_bundle.decode_bundle(moved).payload
        # The record slot, the position AND the actor id all point at the new entity.
        self.assertEqual(payload[0], slot)
        self.assertEqual(struct.unpack_from(">ff", payload, 238), (9350.0, 2780.0))
        self.assertEqual(entities.slice_actor_ids(payload)[0][1], actor)
        # And it is still the character: 19 fragments, not a structure's 2.
        self.assertEqual(payload[1], 19)

class TestMovingACapturedActor(unittest.TestCase):
    """The re-scope of the entity work: move a body that already renders, do not create one.

    MEASURED 2026-10-19, four independent ways: creating a NEW visible actor is unreachable from the
    server in this build (duplicating the 48-fragment spawn record produces no body; the Transform gate
    registers 0 of 30; 0 of 31 objects in the world answer the interface that would give a remote slice
    a Transform). The bodies that DO appear are the capture's own, and their position is a big-endian
    f32 pair inside a bundle the stream already re-sends - so they can be MOVED.
    """

    def test_the_captured_actor_has_a_locatable_position(self) -> None:
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        body = next(m.body for m in store.messages if m.seq == 0xA1 and m.direction == "R")
        payload = javelin_bundle.decode_bundle(body).payload
        # record 29's position is at payload offset 238, and occurs exactly once, so the rewrite
        # anchored on the captured value cannot touch a different entity.
        x, y = struct.unpack_from(">ff", payload, 238)
        self.assertAlmostEqual(x, 9345.4609, places=3)
        self.assertAlmostEqual(y, 2781.2595, places=3)
        self.assertEqual(payload.count(struct.pack(">ff", x, y)), 1)

    def test_moving_it_rewrites_the_pair_and_nothing_else(self) -> None:
        from azoth_world.javelin.replay_store import ReplayStore

        store = ReplayStore(str(ROOT / "replay" / "messages-redacted.txt"))
        body = next(m.body for m in store.messages if m.seq == 0xA1 and m.direction == "R")
        original = javelin_bundle.decode_bundle(body).payload
        captured = struct.unpack_from(">ff", original, 238)

        moved, count = entities.replace_entity_position(body, captured, (9360.0, 2790.0))
        self.assertEqual(count, 1)
        patched = javelin_bundle.decode_bundle(moved).payload
        self.assertEqual(len(patched), len(original))
        self.assertEqual(struct.unpack_from(">ff", patched, 238), (9360.0, 2790.0))
        # ONLY the 8 bytes of the pair may change: no fragment is disturbed. The count of bytes that
        # actually differ is <= 8 and depends on how many bytes the two float encodings share - the
        # first version of this test asserted exactly 8 and failed with 5, which is correct behaviour
        # (0x461205d8 -> 0x46124000 shares the leading 0x46 0x12), so the assertion is on the BOUND.
        differing = [i for i, (a, b) in enumerate(zip(original, patched)) if a != b]
        self.assertLessEqual(len(differing), 8)
        self.assertTrue(all(238 <= i < 246 for i in differing),
                        f"only the pair's 8 bytes may change, got {differing}")

    def test_the_actor_records_the_stream_already_resends(self) -> None:
        """Moving needs no new message: the actor is in the stream, so every cycle carries the move."""
        from azoth_world import rep

        self.assertGreaterEqual(0xA1, rep.STATE_STREAM_MIN_SEQ)

    def test_moving_is_off_by_default(self) -> None:
        import inspect

        from azoth_world import rep

        self.assertIn('"AZOTH_MOVE_ACTOR_SEQ", "0"', inspect.getsource(rep))
