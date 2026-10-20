"""Tests for movement authority: validation, desync, reference offset, load gate.

The numbers are the ones measured on 2026-10-18 from the recorded sessions, so the tests
assert the *measured* relationship rather than a convenient one:

* the wire claim sits 2.04-4.03 u from the client's own `nw_getPlayerPosition` accessor
  while the player stands still, and that offset is per session;
* the load signal arrives 8-14 s after the first channel-1 record, not at 60 s;
* a predicted client legitimately leads the server by about `speed * rtt`.
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

from azoth_world.movement import (  # noqa: E402
    DesyncTracker,
    LoadGate,
    MovementValidator,
    ReferenceOffset,
    Verdict,
)

# Measured while the player stood still, session 1791979976 (2026-10-14 10:12:56Z):
# the accessor's value and the wire claim for the same instant.
ACCESSOR_A = (9343.6416015625, 2786.732666015625)
CLAIM_A = (9341.44140625, 2790.10986328125)

# The same pair for session 1791992558 (14:02:38Z). The offset is DIFFERENT, which is why
# it has to be calibrated per session instead of hard-coded.
ACCESSOR_B = (9341.66162109375, 2791.99560546875)
CLAIM_B = (9341.44140625, 2790.10986328125)


class TestMovementValidator(unittest.TestCase):
    """Is the movement physically possible? Anti-cheat, not desync."""

    def test_first_sample_is_ignored(self) -> None:
        v = MovementValidator()
        self.assertEqual(v.observe(100.0, 100.0, 0.0).verdict, Verdict.IGNORE)

    def test_a_walk_is_plausible(self) -> None:
        v = MovementValidator(max_speed=12.0, window_s=0.5)
        for i in range(12):
            result = v.observe(100.0 + i * 0.1, 100.0, i * 0.05)
        self.assertEqual(result.verdict, Verdict.IGNORE)
        self.assertLess(result.speed or 0, 12.0)

    def test_a_sprint_beyond_the_limit_is_rejected(self) -> None:
        """1.0 u every 0.05 s is 20 u/s, above the 12 u/s limit."""
        v = MovementValidator(max_speed=12.0, window_s=0.5)
        for i in range(12):
            result = v.observe(100.0 + i * 1.0, 100.0, i * 0.05)
        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("speed", result.reason)

    def test_a_teleport_is_rejected_on_the_single_step(self) -> None:
        v = MovementValidator(teleport_distance=50.0)
        v.observe(100.0, 100.0, 0.0)
        result = v.observe(100.0, 300.0, 0.05)
        self.assertEqual(result.verdict, Verdict.REJECT)
        self.assertIn("teleport", result.reason)

    def test_reset_forgets_history(self) -> None:
        v = MovementValidator()
        v.observe(100.0, 100.0, 0.0)
        v.observe(100.0, 300.0, 0.05)
        v.reset()
        self.assertEqual(v.observe(500.0, 500.0, 1.0).verdict, Verdict.IGNORE)

    def test_rejects_nonsense_configuration(self) -> None:
        with self.assertRaises(ValueError):
            MovementValidator(max_speed=0)
        with self.assertRaises(ValueError):
            MovementValidator(window_s=0)


class TestDesyncTracker(unittest.TestCase):
    """Does the server agree with where the client thinks it is?"""

    def test_an_uncalibrated_instrument_never_reports_desync(self) -> None:
        """The live run that refuted the no-offset design, encoded as a rule.

        With the offset unknown, a 4 u difference cannot be told from a real divergence, so
        the tracker must fail open instead of guessing.
        """
        t = DesyncTracker(floor=1.0, sustained_samples=1)
        self.assertFalse(t.calibrated)
        for _ in range(50):
            report = t.observe((100.0, 104.0), (100.0, 100.0))
            self.assertEqual(report.verdict, Verdict.IGNORE)
            self.assertIn("uncalibrated", report.reason)
            self.assertEqual(report.streak, 0)

    def test_the_offset_is_subtracted_before_comparing(self) -> None:
        """MEASURED 2026-10-18: in sync, raw claim minus truth was exactly 4.0311 u."""
        t = DesyncTracker(floor=1.0, sustained_samples=3, offset=(-2.201, 3.377))
        # claim = truth + offset  ->  corrected claim == truth
        claim = (9343.642 - 2.201, 2786.733 + 3.377)
        report = t.observe(claim, (9343.642, 2786.733))
        self.assertEqual(report.verdict, Verdict.IGNORE)
        self.assertAlmostEqual(report.error, 0.0, places=6)

    def test_error_below_the_floor_is_ignored(self) -> None:
        t = DesyncTracker(floor=1.0, sustained_samples=3, offset=(0.0, 0.0))
        report = t.observe((100.0, 100.0), (100.0, 100.5))
        self.assertEqual(report.verdict, Verdict.IGNORE)
        self.assertAlmostEqual(report.error, 0.5)

    def test_one_sample_over_the_floor_is_not_a_desync(self) -> None:
        """A single bad sample is a dropped datagram. Correcting it is the rubber band."""
        t = DesyncTracker(floor=1.0, sustained_samples=3, offset=(0.0, 0.0))
        for _ in range(2):
            report = t.observe((100.0, 105.0), (100.0, 100.0))
            self.assertEqual(report.verdict, Verdict.IGNORE)
        self.assertEqual(report.streak, 2)

    def test_a_sustained_error_is_a_desync(self) -> None:
        t = DesyncTracker(floor=1.0, sustained_samples=3, offset=(0.0, 0.0))
        for _ in range(3):
            report = t.observe((100.0, 105.0), (100.0, 100.0))
        self.assertEqual(report.verdict, Verdict.CORRECT)
        self.assertEqual(report.streak, 3)

    def test_recovering_resets_the_streak(self) -> None:
        t = DesyncTracker(floor=1.0, sustained_samples=3, offset=(0.0, 0.0))
        t.observe((100.0, 105.0), (100.0, 100.0))
        t.observe((100.0, 105.0), (100.0, 100.0))
        t.observe((100.0, 100.0), (100.0, 100.0))
        report = t.observe((100.0, 105.0), (100.0, 100.0))
        self.assertEqual(report.verdict, Verdict.IGNORE)
        self.assertEqual(report.streak, 1)

    def test_rebaseline_forgets_a_pre_correction_streak(self) -> None:
        """After the server corrects, the old streak says nothing about the new divergence."""
        t = DesyncTracker(floor=1.0, sustained_samples=3, offset=(0.0, 0.0))
        t.observe((100.0, 105.0), (100.0, 100.0))
        t.observe((100.0, 105.0), (100.0, 100.0))
        t.rebaseline()
        report = t.observe((100.0, 105.0), (100.0, 100.0))
        self.assertEqual(report.verdict, Verdict.IGNORE)
        self.assertEqual(report.streak, 1)

    def test_the_floor_includes_the_prediction_lead(self) -> None:
        """A predicted client leads the server by ~speed*rtt, so the floor must cover it."""
        still = DesyncTracker(floor=1.0, rtt_s=0.0, max_speed=12.0, offset=(0.0, 0.0))
        self.assertAlmostEqual(still.threshold, 1.0)

        laggy = DesyncTracker(floor=1.0, rtt_s=0.2, max_speed=12.0, offset=(0.0, 0.0))
        self.assertAlmostEqual(laggy.threshold, 2.4)

        # An honest moving client at 200 ms RTT shows ~2.4 u. Below a 1.0 u floor that
        # would be reported as desync; with the derived floor it is correctly ignored.
        report = laggy.observe((102.0, 100.0), (100.0, 100.0))
        self.assertEqual(report.verdict, Verdict.IGNORE)

    def test_rejects_nonsense_configuration(self) -> None:
        with self.assertRaises(ValueError):
            DesyncTracker(floor=-1)
        with self.assertRaises(ValueError):
            DesyncTracker(sustained_samples=0)


class TestReferenceOffset(unittest.TestCase):
    """The instrument offset: a property of the measurement, not of the player."""

    def test_calibrates_the_measured_offset(self) -> None:
        ref = ReferenceOffset()
        ref.observe(CLAIM_A, ACCESSOR_A)
        calibration = ref.calibrate()
        self.assertIsNotNone(calibration)
        assert calibration is not None
        self.assertAlmostEqual(calibration.dx, -2.2001953125, places=6)
        self.assertAlmostEqual(calibration.dy, 3.377197265625, places=6)
        # The magnitude is the 2.04-4.03 u band the sessions measured.
        self.assertGreater(calibration.magnitude, 2.0)
        self.assertLess(calibration.magnitude, 4.1)

    def test_a_constant_offset_has_no_residual(self) -> None:
        ref = ReferenceOffset()
        for _ in range(10):
            ref.observe(CLAIM_A, ACCESSOR_A)
        calibration = ref.calibrate()
        assert calibration is not None
        self.assertAlmostEqual(calibration.residual, 0.0, places=9)
        self.assertEqual(calibration.samples, 10)

    def test_a_moving_player_shows_up_as_residual(self) -> None:
        """Mixed samples mean the calibration is not trustworthy for tightening a threshold."""
        ref = ReferenceOffset()
        ref.observe(CLAIM_A, ACCESSOR_A)
        ref.observe(CLAIM_B, ACCESSOR_B)
        calibration = ref.calibrate()
        assert calibration is not None
        self.assertGreater(calibration.residual, 0.5)

    def test_the_offset_is_per_session(self) -> None:
        """Two sessions, two different offsets: this is why it cannot be a constant."""
        a, b = ReferenceOffset(), ReferenceOffset()
        a.observe(CLAIM_A, ACCESSOR_A)
        b.observe(CLAIM_B, ACCESSOR_B)
        ca, cb = a.calibrate(), b.calibrate()
        assert ca is not None and cb is not None
        self.assertNotAlmostEqual(ca.dx, cb.dx, places=2)
        self.assertNotAlmostEqual(ca.magnitude, cb.magnitude, places=2)

    def test_translates_a_claim_into_an_accessor_value(self) -> None:
        ref = ReferenceOffset()
        ref.observe(CLAIM_A, ACCESSOR_A)
        calibration = ref.calibrate()
        assert calibration is not None
        x, y = ref.to_accessor(CLAIM_A, calibration)
        self.assertAlmostEqual(x, ACCESSOR_A[0], places=6)
        self.assertAlmostEqual(y, ACCESSOR_A[1], places=6)

    def test_no_samples_means_no_calibration(self) -> None:
        self.assertIsNone(ReferenceOffset().calibrate())


class TestLoadGate(unittest.TestCase):
    """The real "the player is in the world" signal, replacing a fixed grace period."""

    def test_fires_once_on_the_transition(self) -> None:
        gate = LoadGate()
        self.assertFalse(gate.observe(ready=False, now=0.0))
        self.assertFalse(gate.observe(ready=False, now=5.0))
        self.assertTrue(gate.observe(ready=True, now=11.0))
        self.assertFalse(gate.observe(ready=True, now=12.0))
        self.assertTrue(gate.is_ready)

    def test_records_how_long_the_load_took(self) -> None:
        gate = LoadGate()
        gate.observe(ready=False, now=100.0)
        gate.observe(ready=True, now=111.0)
        self.assertAlmostEqual(gate.ready_after_s or 0.0, 11.0)

    def test_a_failed_load_never_becomes_ready(self) -> None:
        """One recorded session never grew past 154 bytes; the gate must stay closed."""
        gate = LoadGate()
        for i in range(200):
            gate.observe(ready=False, now=float(i))
        self.assertFalse(gate.is_ready)
        self.assertIsNone(gate.ready_at)
        self.assertEqual(gate.observations, 200)


if __name__ == "__main__":
    unittest.main()


class TestMovementObservationWiring(unittest.TestCase):
    """`rep.PeerSession._observe_movement_claim` — the step-3 wiring.

    The observation must be free when it is silent (a session that never reaches the world
    pays nothing) and must log on TRANSITIONS only: at 20 Hz, per-sample logging would bury
    the session log it exists to inform.
    """

    def _session(self):
        class Stub:
            movement_gate = None
            movement_tracker = None
            movement_validator = None
            movement_calibrator = None
            movement_simulator = None
            movement_simulation_last = None
            movement_policy = None
            movement_last_action = None
            movement_summary_at = 0.0
            movement_truth = None
            movement_desync_logged = False
            movement_reject_logged = False
            movement_corrections_sent = 0
            movement_cap_logged = False
            state_stream_position = []
            state_stream_position_queue = []
            state_stream_position_next_at = 0.0

        return Stub()

    def _record(self, payload: bytes):
        from types import SimpleNamespace

        return SimpleNamespace(channel=1, payload=payload)

    def _run(self, stub, payloads):
        """Feed payloads through the real method with the event log captured."""
        from azoth_world import rep

        events: list[dict] = []
        original = rep.log_event
        rep.log_event = lambda event: events.append(event)
        try:
            for payload in payloads:
                rep.PeerSession._observe_movement_claim(stub, [self._record(payload)])
        finally:
            rep.log_event = original
        return events

    def test_a_session_that_never_loads_logs_nothing(self) -> None:
        from test_alc import PRELOAD_154

        events = self._run(self._session(), [PRELOAD_154] * 5)
        self.assertEqual(events, [])

    def test_the_load_transition_is_logged_exactly_once(self) -> None:
        from test_alc import LOADED_311, PRELOAD_154

        stub = self._session()
        events = self._run(stub, [PRELOAD_154, LOADED_311, LOADED_311, LOADED_311])
        ready = [e for e in events if e.get("event") == "movement-ready"]
        self.assertEqual(len(ready), 1)
        self.assertIn("after_s", ready[0])
        self.assertEqual(ready[0]["source"], "channel-1 position marker")
        self.assertTrue(stub.movement_gate.is_ready)

    def test_no_offset_gate_and_no_false_desync(self) -> None:
        """THE FRAME FIX, pinned by a test.

        This used to assert a calibrated 4.0311 u offset and wait for it before comparing. That
        number came from comparing an ACCESSOR value (the captured position) against a WIRE value
        (the claim) - two different frames - and it made an in-sync player look permanently
        desynced. Now the claim is the live position and the truth is the server's own position,
        which adopts it: same quantity, same frame, offset 0 by construction, so the gate is gone.

        MEASURED LIVE 2026-10-18 after the fix: `movement-calibrated offset [0.0, -0.0]
        magnitude_u 0.0`.
        """
        from test_alc import LOADED_311

        stub = self._session()
        events = self._run(stub, [LOADED_311] * 60)

        self.assertEqual(
            [e for e in events if e.get("event") == "movement-calibrated"], [],
            "the offset gate is gone: there is nothing to calibrate",
        )
        self.assertEqual(
            [e for e in events if e.get("event") == "movement-desync"], [],
            "an in-sync player must never be reported as desynced",
        )
        self.assertTrue(stub.movement_tracker.calibrated)
        self.assertEqual(stub.movement_tracker.offset, (0.0, 0.0))

    def test_a_sustained_divergence_is_logged_once(self) -> None:
        """A real divergence: the server refuses the claim, so the two positions differ."""
        from test_alc import LOADED_311

        stub = self._session()
        self._run(stub, [LOADED_311] * 30)
        self.assertTrue(stub.movement_tracker.calibrated)

        # A claim far from where the server holds the player: the validator rejects it, the server
        # keeps its own position, and the tracker reports the divergence once. The claim is patched
        # at the movement-buffer offset (payload 131) so it is the LIVE position that moves.
        far = LOADED_311[:131] + struct.pack(">ff", 9500.0, 2600.0) + LOADED_311[139:]
        events = self._run(stub, [far] * 12)
        desync = [e for e in events if e.get("event") == "movement-desync"]
        self.assertEqual(len(desync), 1, f"expected one episode, got {len(desync)}")
        self.assertGreater(desync[0]["error_u"], desync[0]["threshold_u"])
        self.assertFalse(desync[0]["correct"], "correction is off by default")

    def test_a_moving_calibration_is_rejected_not_averaged(self) -> None:
        """A wide spread means the player was moving; a wrong offset hides real desync."""
        from azoth_world import movement

        cal = movement.ReferenceOffset(samples=10, max_residual=0.5)
        for i in range(10):
            cal.observe((100.0 + i * 3.0, 100.0), (100.0, 100.0))
        self.assertIsNone(cal.accepted())
        self.assertIsNotNone(cal.calibrate())  # it can report, it just must not be trusted

    def test_a_tight_calibration_is_accepted(self) -> None:
        from azoth_world import movement

        cal = movement.ReferenceOffset(samples=10, max_residual=0.5)
        for _ in range(10):
            cal.observe((102.2, 96.6), (100.0, 100.0))
        accepted = cal.accepted()
        self.assertIsNotNone(accepted)
        assert accepted is not None
        self.assertAlmostEqual(accepted.dx, 2.2, places=6)
        self.assertAlmostEqual(accepted.dy, -3.4, places=6)
        self.assertAlmostEqual(accepted.residual, 0.0, places=9)

    def test_an_incomplete_calibration_is_not_accepted(self) -> None:
        from azoth_world import movement

        cal = movement.ReferenceOffset(samples=10)
        for _ in range(5):
            cal.observe((102.2, 96.6), (100.0, 100.0))
        self.assertIsNone(cal.accepted())

    def test_the_observation_never_mutates_the_claim_path(self) -> None:
        """It is a read-only observer: no send, no state, no reply."""
        import inspect

        from azoth_world import rep

        source = inspect.getsource(rep.PeerSession._observe_movement_claim)
        for forbidden in ("server.send", "marshal_datagram", "self.state_stream"):
            self.assertNotIn(forbidden, source)


class TestEventDrivenCorrection(unittest.TestCase):
    """Correction is ONE send per divergence episode, never a stream.

    The 1 Hz stream attempt (2026-10-18) sent 93 bundles before it was stopped, and it made
    the local character invisible while every protocol counter stayed clean: 0
    `Failed to unmarshal`, 0 `ValidationError`, 0 `transportError`. Valid bytes, wrong message,
    at the wrong time. These tests pin the properties that make that impossible to repeat.
    """

    def _stub(self, bundles=None):
        from azoth_world.movement import DesyncTracker

        class Stub:
            movement_gate = None
            movement_tracker = DesyncTracker(floor=1.0, sustained_samples=1, offset=(0.0, 0.0))
            movement_validator = None
            movement_calibrator = None
            movement_truth = (9342.1785390625, 2801.318556640625)
            movement_desync_logged = False
            movement_reject_logged = False
            movement_corrections_sent = 0
            movement_cap_logged = False
            state_stream_position = bundles or []
            state_stream_position_queue = []
            state_stream_position_next_at = 0.0
            # The correction sends the MINIMAL bundle (record 1 + position fragment only),
            # never the 46 KB area spawn.
            state_position_minimal_body = bytes(103) if bundles else None
            state_position_correction_body = bytes(7256) if bundles else None

        return Stub()

    def _report(self, error: float):
        from azoth_world.movement import DesyncReport, Verdict

        return DesyncReport(Verdict.CORRECT, error, 2.0, 5, "test")

    def _queue(self, stub, report):
        from azoth_world import rep

        events: list[dict] = []
        original = rep.log_event
        rep.log_event = lambda e: events.append(e)
        try:
            rep.PeerSession._queue_movement_correction(stub, report)
        finally:
            rep.log_event = original
        return events

    def test_one_hybrid_bundle_is_queued_not_a_stream(self) -> None:
        stub = self._stub([object()])
        self._queue(stub, self._report(3.4))
        self.assertEqual(len(stub.state_stream_position_queue), 1)
        queued = stub.state_stream_position_queue[0]
        self.assertEqual(queued.type_id, 0x08)
        # It MUST be a dataclass: `_send_state_bundle` calls dataclasses.replace(msg, body=...),
        # and a SimpleNamespace raised `TypeError: replace() should be called on dataclass
        # instances`, which killed a live session on 2026-10-18.
        import dataclasses

        self.assertTrue(
            dataclasses.is_dataclass(queued),
            f"the correction must be a dataclass, got {type(queued).__name__}",
        )
        dataclasses.replace(queued, body=b"x")  # must not raise
        self.assertEqual(len(queued.body), 7256, "the correction must be the HYBRID bundle")
        self.assertEqual(stub.movement_corrections_sent, 1)

    def test_a_second_detection_does_not_stack(self) -> None:
        """The queue is REPLACED, not extended, so two detections cannot queue two bundles."""
        stub = self._stub([object(), object()])
        self._queue(stub, self._report(3.4))
        self._queue(stub, self._report(4.0))
        self.assertEqual(len(stub.state_stream_position_queue), 1)

    def test_a_missing_hybrid_body_is_reported_not_faked(self) -> None:
        stub = self._stub([object()])
        stub.state_position_correction_body = None
        events = self._queue(stub, self._report(3.4))
        self.assertEqual(stub.state_stream_position_queue, [])
        self.assertEqual(stub.movement_corrections_sent, 0)
        unavailable = [e for e in events if e.get("event") == "movement-correction-unavailable"]
        self.assertEqual(len(unavailable), 1)
        self.assertIn("hybrid", unavailable[0]["reason"])

    def test_the_tracker_is_rebaselined_after_queuing(self) -> None:
        """Otherwise the same divergence is corrected again on the next sample."""
        from azoth_world.movement import DesyncTracker

        stub = self._stub([object()])
        stub.movement_tracker = DesyncTracker(floor=1.0, sustained_samples=1, offset=(0.0, 0.0))
        for _ in range(3):
            stub.movement_tracker.observe((100.0, 105.0), (100.0, 100.0))
        self._queue(stub, self._report(5.0))
        report = stub.movement_tracker.observe((100.0, 105.0), (100.0, 100.0))
        self.assertEqual(report.streak, 1, "the streak must restart after a correction")

    def test_a_hard_cap_stops_an_unbounded_loop(self) -> None:
        from azoth_world import rep

        stub = self._stub([object()])
        original = rep.MOVEMENT_CORRECT_MAX
        rep.MOVEMENT_CORRECT_MAX = 2
        try:
            for _ in range(10):
                self._queue(stub, self._report(3.4))
        finally:
            rep.MOVEMENT_CORRECT_MAX = original
        self.assertEqual(stub.movement_corrections_sent, 2)

    def test_the_cap_is_logged_when_it_bites(self) -> None:
        from azoth_world import rep

        stub = self._stub([object()])
        original = rep.MOVEMENT_CORRECT_MAX
        rep.MOVEMENT_CORRECT_MAX = 1
        try:
            self._queue(stub, self._report(3.4))
            events = self._queue(stub, self._report(3.4))
        finally:
            rep.MOVEMENT_CORRECT_MAX = original
        capped = [e for e in events if e.get("event") == "movement-correction-capped"]
        self.assertEqual(len(capped), 1, "the cap must be logged once, not per sample")
        self.assertEqual(capped[0]["sent"], 1)

    def test_no_armed_bundle_is_reported_not_faked(self) -> None:
        stub = self._stub([])
        events = self._queue(stub, self._report(3.4))
        self.assertEqual(stub.state_stream_position_queue, [])
        self.assertEqual(stub.movement_corrections_sent, 0)
        unavailable = [e for e in events if e.get("event") == "movement-correction-unavailable"]
        self.assertEqual(len(unavailable), 1)

    def test_correction_is_off_by_default(self) -> None:
        import inspect

        from azoth_world import rep

        source = inspect.getsource(rep)
        self.assertIn('"AZOTH_MOVEMENT_CORRECT", "0"', source)

    def test_a_one_shot_never_refills_into_a_loop(self) -> None:
        """The exact failure mode: period 0 must consume the bundle and stop."""
        import inspect

        from azoth_world import rep

        source = inspect.getsource(rep.PeerSession.maybe_state_stream)
        self.assertIn("STATE_STREAM_POSITION_PERIOD_S > 0", source)
        # The refill must be inside that guard, not outside it.
        guard = source.index("if STATE_STREAM_POSITION_PERIOD_S > 0:")
        refill = source.index("list(self.state_stream_position)", guard)
        self.assertGreater(refill, guard)


class TestTheQueueMustStartEmptyInCorrectionMode(unittest.TestCase):
    """The 2026-10-18 defect that made the local character invisible.

    The queue was initialised as `list(state_stream_position)` regardless of mode. With
    `STATE_STREAM_POSITION_PERIOD_S == 0` the timer never advanced, so a full queue drained at
    tick rate and the server re-sent 4-5 spawn records (46 KB each) per second. The client showed
    0 `Failed to unmarshal`, 0 `ValidationError` and 0 `transportError` while the character was
    invisible: valid bytes, wrong message, at the wrong rate.

    The rule: a CORRECTION is one bundle on a detection, never a queue that drains on its own.
    """

    def test_arming_does_not_prefill_the_queue_in_correction_mode(self) -> None:
        import inspect

        from azoth_world import rep

        source = inspect.getsource(rep.PeerSession)
        # The prefill must be conditional on loop mode.
        marker = "state_stream_position_queue = ("
        self.assertIn(marker, source)
        at = source.index(marker)
        window = source[at:at + 260]
        self.assertIn("STATE_STREAM_POSITION_PERIOD_S > 0", window)
        self.assertIn("else []", window)

    def test_an_empty_queue_sends_nothing(self) -> None:
        """With correction mode on and no detection, the stream must be silent."""
        from unittest import mock

        from azoth_world import rep

        session = self._stream_session()
        self.assertEqual(session.state_stream_position_queue, [])
        clock = {"now": 1_000.0}
        with mock.patch("azoth_world.rep.time.monotonic", lambda: clock["now"]):
            for _ in range(50):
                rep.PeerSession.maybe_state_stream(session, None)
                clock["now"] += 0.02
        # The world stream keeps flowing; only the POSITION stream must be silent.
        self.assertEqual(
            session.state_stream_position_sent, 0,
            "no position bundle may be sent without a detection",
        )
        self.assertNotIn(0x2A, [m.seq for m in session.sent])

    def test_a_queued_correction_is_sent_exactly_once(self) -> None:
        from unittest import mock

        from azoth_world import rep

        session = self._stream_session()
        bundle = self._bundle(0x2A)
        session.state_stream_position = [bundle]
        session.state_stream_position_queue = [bundle]
        clock = {"now": 1_000.0}
        with mock.patch("azoth_world.rep.time.monotonic", lambda: clock["now"]):
            for _ in range(50):
                rep.PeerSession.maybe_state_stream(session, None)
                clock["now"] += 0.02
        sent = [m for m in session.sent if m.seq == 0x2A]
        self.assertEqual(len(sent), 1, "a one-shot correction must not repeat")
        self.assertEqual(session.state_stream_position_queue, [])

    def _bundle(self, seq: int):
        from types import SimpleNamespace

        return SimpleNamespace(seq=seq, type_id=0x08, body=b"\x00\x01\x08\x01\x40\x01\x01")

    def _stream_session(self):
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.v3_responded = True
        session.replay_queue = []
        session.greetings_after_replay = True
        session.out_msg_seq = 1
        session.out_rel_seq = 1
        world = self._bundle(0xA0)
        session.state_stream_all = [world]
        session.state_stream_queue = [world]
        session.state_stream_player = []
        session.state_stream_player_queue = []
        session.state_stream_position = []
        session.state_stream_position_queue = []
        session.state_stream_position_next_at = 0.0
        session.state_stream_position_sent = 0
        session.state_position_last_written = None
        session.state_stream_next_at = 0.0
        session.state_stream_player_next_at = 0.0
        session.state_stream_seq = 0x200
        session.state_stream_sent = 0
        session.state_stream_player_sent = 0
        session.state_authoritative_sent = 0
        session.sent = []
        session._send_replay_message = lambda _server, msg, **_kw: session.sent.append(msg)
        return session


class TestTheCorrectionFlagByte(unittest.TestCase):
    """The Carrier flag byte selects which gate the client runs, and only one advances the seq.

    Decompiled `FUN_14643e7b0` (2026-10-18):

        byte[msg+8] == 0  -> the RELIABLE path: the dispatcher runs, `port[0x78]` (the
                             replication high-water) is NOT advanced;
        byte[msg+8] != 0  -> the UNRELIABLE gate: the instance id must match and the seq must be
                             strictly greater than the high-water, THEN `port[0x78] = seq` and
                             the dispatcher runs.

    Every captured state bundle the client applies arrived through the second path (flags 0x20);
    this server sent 0x21. A correction sent reliable is therefore accepted with zero errors and
    never moves the client's notion of the latest replicated state.
    """

    def test_the_default_is_the_clients_own_form(self) -> None:
        from azoth_world import rep

        self.assertEqual(rep.MOVEMENT_CORRECT_FLAGS, 0x20)
        self.assertTrue(rep.MOVEMENT_CORRECT_FLAGS & 0x20, "DATA_CHANNEL must be set")
        self.assertFalse(rep.MOVEMENT_CORRECT_FLAGS & 0x01, "RELIABLE must NOT be set")

    def test_the_position_send_carries_the_configured_flag(self) -> None:
        """The correction must not silently fall back to the reliable 0x21."""
        import inspect

        from azoth_world import rep

        source = inspect.getsource(rep.PeerSession.maybe_state_stream)
        self.assertIn("flags=MOVEMENT_CORRECT_FLAGS", source)

    def test_other_state_sends_keep_their_form(self) -> None:
        """Only the correction is an A/B variable; the world and player rates are unchanged."""
        import inspect

        from azoth_world import rep

        source = inspect.getsource(rep.PeerSession.maybe_state_stream)
        self.assertIn('self._send_state_bundle(server, player_msg, "player")', source)
        self.assertIn('self._send_state_bundle(server, self.state_stream_queue.pop(0), "world")', source)

    def test_the_flag_reaches_the_record(self) -> None:
        """A flag passed down must appear on the Carrier record, not be dropped on the way."""
        import inspect

        from azoth_world import rep

        source = inspect.getsource(rep.PeerSession._send_replay_message)
        self.assertIn("0x21 if flags is None else flags", source)
        self.assertIn("0x25 if flags is None else (flags | 0x04)", source)

    def test_the_signature_accepts_flags(self) -> None:
        """A body that reads `flags` is useless if the SIGNATURE does not accept it.

        MEASURED 2026-10-18: the signature was left as `(self, server, msg)` while the body
        already referenced `flags`, so every replay send raised
        `NameError: name 'flags' is not defined` inside the tick loop. 104 tick errors later the
        client had re-registered 46 times and never reached the world. A source-string test on
        the body alone passed throughout - this one checks the actual parameter list.
        """
        import inspect

        from azoth_world import rep

        params = inspect.signature(rep.PeerSession._send_replay_message).parameters
        self.assertIn("flags", params)
        self.assertIsNone(params["flags"].default)


class TestMovementSimulator(unittest.TestCase):
    """The server's OWN position, derived from the client's input stream.

    Until this existed the server had no position: it replayed a captured constant. `alc` read the
    client's claim and `DesyncTracker` compared the two, but nothing held a live authoritative value.

    The design comes from the client's own cvars: the CLIENT owns its locomotion and corrects its
    own desync (`javelin.alc-correct-position-desync-*`), while the SERVER validates plausibility
    and reacts to violations (`javelin-server.alc-speed-hack-fix-v2-*`,
    `javelin-server.player-teleport-2d-distance-metrics-threshold`). So the server holds a live
    validated position and refuses the implausible - it does not impose one every tick.
    """

    def test_the_first_claim_defines_the_position(self) -> None:
        from azoth_world import movement

        sim = movement.MovementSimulator()
        self.assertFalse(sim.ready)
        result = sim.consume((100.0, 200.0), 0.0)
        self.assertTrue(sim.ready)
        self.assertEqual(result.authority, movement.Authority.CLIENT)
        self.assertEqual(sim.position, (100.0, 200.0))
        self.assertFalse(result.rejected)

    def test_a_seeded_start_is_not_a_client_decision(self) -> None:
        """At spawn the SERVER decides where the player appears - the one moment it truly owns it."""
        from azoth_world import movement

        sim = movement.MovementSimulator(start=(9343.64, 2786.73))
        self.assertTrue(sim.ready)
        self.assertEqual(sim.authority, movement.Authority.HELD)
        self.assertEqual(sim.adopted, 0)

    def test_a_plausible_walk_is_adopted(self) -> None:
        from azoth_world import movement

        sim = movement.MovementSimulator(start=(100.0, 100.0))
        moved = 0.0
        for i in range(1, 20):
            result = sim.consume((100.0 + i * 0.1, 100.0), i * 0.05)
            moved += result.moved
        self.assertEqual(result.authority, movement.Authority.CLIENT)
        self.assertEqual(sim.violations, 0)
        self.assertAlmostEqual(moved, 1.9, places=6)

    def test_a_teleport_is_refused_and_the_position_held(self) -> None:
        """The only moment the server overrides the client."""
        from azoth_world import movement

        sim = movement.MovementSimulator(start=(100.0, 100.0))
        sim.consume((100.0, 100.0), 0.0)
        result = sim.consume((100.0, 400.0), 0.05)   # 300 u in 50 ms
        self.assertTrue(result.rejected)
        self.assertEqual(result.authority, movement.Authority.HELD)
        self.assertEqual(result.position, (100.0, 100.0), "the server keeps its own value")
        self.assertEqual(sim.position, (100.0, 100.0))
        self.assertEqual(sim.violations, 1)
        self.assertEqual(sim.held, 1)

    def test_violations_accumulate_for_escalation(self) -> None:
        """A client that INSISTS on a teleport must keep being refused.

        The step is measured against the SERVER's position, not against the client's previous
        claim. `MovementValidator` resets its reference on a rejected teleport, so measuring there
        would refuse once and then accept the teleported position on the next sample - the client
        would win after a single refusal.
        """
        from azoth_world import movement

        sim = movement.MovementSimulator(start=(0.0, 0.0))
        sim.consume((0.0, 0.0), 0.0)
        for i in range(3):
            result = sim.consume((0.0, 900.0), 0.05 + i * 0.05)
            self.assertTrue(result.rejected, f"sample {i} must stay refused")
        self.assertEqual(sim.violations, 3)
        self.assertEqual(sim.position, (0.0, 0.0), "the server never moves to the claim")

    def test_the_server_position_is_its_own_not_the_claim_after_a_refusal(self) -> None:
        """This is the difference between a server and a replayer."""
        from azoth_world import movement

        sim = movement.MovementSimulator(start=(10.0, 10.0))
        sim.consume((10.0, 10.0), 0.0)
        claim = (500.0, 500.0)
        sim.consume(claim, 0.05)
        self.assertNotEqual(sim.position, claim)
        self.assertEqual(sim.position, (10.0, 10.0))

    def test_as_dict_reports_authority(self) -> None:
        from azoth_world import movement

        sim = movement.MovementSimulator(start=(1.0, 2.0))
        d = sim.as_dict()
        self.assertEqual(d["position"], [1.0, 2.0])
        self.assertEqual(d["authority"], "held")
        self.assertEqual(d["samples"], 0)


class TestTheServerPublishesItsOwnPosition(unittest.TestCase):
    """`AZOTH_STATE_POSITION=sim` makes the send path write the SIMULATED position."""

    def test_sim_mode_converts_the_frame(self) -> None:
        """THE 4.03 u BUG, pinned by a test.

        The simulator's position comes from the channel-1 claim, which is in the WIRE frame. The
        state bundle carries the position in the ACCESSOR frame - proven by the 2026-10-14
        experiment, where writing a value into the spawn record made the client's accessor report
        exactly that value, 0.0000 u error. The two frames differ by `MOVEMENT_FRAME_OFFSET`:

            spawn record   (9343.6416, 2786.7327)   <- accessor frame
            channel-1 claim (9341.4414, 2790.1104)   <- wire frame, same instant

        So the write path must convert wire -> accessor. Writing the raw simulated value would send
        a position 4.03 u from the one the server believes, on every send.
        """
        from azoth_world import rep
        from azoth_world.javelin import alc

        original = rep.STATE_POSITION
        try:
            rep.STATE_POSITION = "sim"
            rep.set_simulated_position((1234.5, 678.9))
            written = rep.state_position_spec()
            assert written is not None
            self.assertAlmostEqual(
                written[0], 1234.5 - alc.MOVEMENT_FRAME_OFFSET[0], places=4
            )
            self.assertAlmostEqual(
                written[1], 678.9 - alc.MOVEMENT_FRAME_OFFSET[1], places=4
            )
            # And the conversion is exactly the inverse of the forward one.
            back = (
                written[0] + alc.MOVEMENT_FRAME_OFFSET[0],
                written[1] + alc.MOVEMENT_FRAME_OFFSET[1],
            )
            self.assertAlmostEqual(back[0], 1234.5, places=4)
            self.assertAlmostEqual(back[1], 678.9, places=4)
        finally:
            rep.STATE_POSITION = original
            rep.set_simulated_position(None)

    def test_the_two_frames_are_the_measured_ones(self) -> None:
        """The concrete numbers, so a frame change cannot drift silently."""
        import struct

        from azoth_world import rep
        from azoth_world.javelin import alc

        captured = struct.unpack(">ff", rep.CAPTURED_PLAYER_POSITION)
        self.assertAlmostEqual(captured[0], 9343.6416, places=3)
        self.assertAlmostEqual(captured[1], 2786.7327, places=3)
        wire = (
            captured[0] + alc.MOVEMENT_FRAME_OFFSET[0],
            captured[1] + alc.MOVEMENT_FRAME_OFFSET[1],
        )
        self.assertAlmostEqual(wire[0], 9341.4414, places=3)
        self.assertAlmostEqual(wire[1], 2790.1104, places=3)

    def test_sim_mode_falls_through_until_the_simulator_has_a_value(self) -> None:
        """Switching the simulator on must not blank the position before the first claim."""
        from azoth_world import rep

        original = rep.STATE_POSITION
        try:
            rep.STATE_POSITION = "sim"
            rep.set_simulated_position(None)
            # Falls through to the empty spec, i.e. leave the capture alone.
            self.assertIsNone(rep.state_position_spec())
        finally:
            rep.STATE_POSITION = original

    def test_other_modes_ignore_the_simulator(self) -> None:
        from azoth_world import rep

        original = rep.STATE_POSITION
        try:
            rep.set_simulated_position((1.0, 2.0))
            rep.STATE_POSITION = ""
            self.assertIsNone(rep.state_position_spec())
            rep.STATE_POSITION = "50.5,60.5"
            self.assertEqual(rep.state_position_spec(), (50.5, 60.5))
        finally:
            rep.STATE_POSITION = original
            rep.set_simulated_position(None)


class TestPredictiveSimulator(unittest.TestCase):
    """The server derives its OWN expected position, then checks the client against it.

    `MovementSimulator` adopts a validated claim: the server ends up holding whatever the client
    said. This one estimates a velocity from consecutive server-held positions, predicts the next
    one, and records how far the client's claim was from that prediction. When they agree the
    server still adopts - the client stays authoritative over its locomotion, as the design says -
    but the server now has an independent expectation, which is what lets it say "that step does not
    follow from what you reported" rather than only "that step was too fast".
    """

    def test_it_predicts_from_its_own_velocity(self) -> None:
        from azoth_world import movement

        sim = movement.PredictiveSimulator(start=(0.0, 0.0), prediction_tolerance=1.0)
        sim.consume((0.0, 0.0), 0.0)
        sim.consume((1.0, 0.0), 0.1)          # 10 u/s
        self.assertIsNotNone(sim.last_check)
        # The next claim at 10 u/s for 0.1 s should be predicted within tolerance.
        sim.consume((2.0, 0.0), 0.2)
        check = sim.last_check
        assert check is not None
        self.assertTrue(check.agreed, check.reason)
        self.assertAlmostEqual(sim._velocity[0], 10.0, places=4)

    def test_a_step_that_does_not_follow_is_recorded(self) -> None:
        from azoth_world import movement

        sim = movement.PredictiveSimulator(start=(0.0, 0.0), prediction_tolerance=0.5)
        sim.consume((0.0, 0.0), 0.0)
        sim.consume((0.1, 0.0), 0.1)          # slow
        sim.consume((1.5, 0.0), 0.2)          # sudden acceleration, but still plausible speed
        check = sim.last_check
        assert check is not None
        self.assertFalse(check.agreed, "a 14 u/s jump from 1 u/s must be flagged")
        self.assertEqual(sim.disagreements, 1)
        self.assertGreater(check.error, 0.5)

    def test_it_still_adopts_a_plausible_claim(self) -> None:
        """The client stays authoritative; the prediction is an expectation, not an override."""
        from azoth_world import movement

        sim = movement.PredictiveSimulator(start=(0.0, 0.0), prediction_tolerance=0.01)
        sim.consume((0.0, 0.0), 0.0)
        sim.consume((1.0, 0.0), 0.1)
        result = sim.consume((2.0, 0.0), 0.2)
        self.assertEqual(result.authority, movement.Authority.CLIENT)
        self.assertEqual(sim.position, (2.0, 0.0))

    def test_an_implausible_claim_is_still_refused(self) -> None:
        """The validator still wins over the prediction: authority has not moved."""
        from azoth_world import movement

        sim = movement.PredictiveSimulator(start=(0.0, 0.0))
        sim.consume((0.0, 0.0), 0.0)
        result = sim.consume((900.0, 0.0), 0.05)
        self.assertTrue(result.rejected)
        self.assertEqual(sim.position, (0.0, 0.0))

    def test_prediction_stats_are_reported(self) -> None:
        from azoth_world import movement

        sim = movement.PredictiveSimulator(start=(0.0, 0.0))
        for i in range(5):
            sim.consume((i * 0.1, 0.0), i * 0.1)
        d = sim.as_dict()
        self.assertGreaterEqual(d["predictions"], 1)
        self.assertIsNotNone(d["mean_prediction_error_u"])
        self.assertIn("velocity", d)


class TestYawAwareSimulator(unittest.TestCase):
    """The velocity is expressed in the player's own frame, using the client's camera yaw.

    `PredictiveSimulator` estimates velocity from a finite difference, which can only describe the
    step that already happened. The client's input sample also carries its camera yaw (measured
    2026-10-18), so the server can say *how* the player is moving, not just how fast.

    MEASURED on 3001 real captured samples: 10 violations, 4 prediction disagreements, mean
    prediction error 0.0334 u, yaw captured on 2990 of them.
    """

    def test_forward_motion_reads_as_positive_forward_speed(self) -> None:
        """The yaw is measured from +Y, so `yaw = 0` means forward is +Y.

        MEASURED 2026-10-18: `(movement heading - yaw)` is **+90.0 deg** in 77 of 79 displacements
        during a real walk - a constant, not a spread. The obvious reading, forward = (cos, sin),
        reports a player walking forward as walking sideways by 90 deg, which is exactly what it did
        before this was measured.
        """
        from azoth_world import movement

        sim = movement.YawAwareSimulator(start=(0.0, 0.0))
        t = 0.0
        for i in range(1, 11):
            t += 0.05
            sim.consume_with_yaw((0.0, i * 0.25), 0.0, t)   # +Y is forward at yaw 0
        self.assertAlmostEqual(sim.forward_speed, 5.0, places=2)
        self.assertAlmostEqual(sim.lateral_speed, 0.0, places=2)

    def test_strafe_reads_as_lateral_speed(self) -> None:
        """Moving perpendicular to the yaw must show up as lateral, not forward."""
        from azoth_world import movement

        sim = movement.YawAwareSimulator(start=(0.0, 0.0))
        t = 0.0
        for i in range(1, 11):
            t += 0.05
            sim.consume_with_yaw((i * 0.25, 0.0), 0.0, t)   # +X is lateral at yaw 0
        self.assertAlmostEqual(sim.forward_speed, 0.0, places=2)
        self.assertAlmostEqual(abs(sim.lateral_speed), 5.0, places=2)

    def test_moving_against_the_yaw_reads_as_negative_forward(self) -> None:
        from azoth_world import movement

        sim = movement.YawAwareSimulator(start=(0.0, 0.0))
        t = 0.0
        for i in range(1, 11):
            t += 0.05
            sim.consume_with_yaw((0.0, -i * 0.25), 0.0, t)   # forward is +Y, so -Y is backwards
        self.assertAlmostEqual(sim.forward_speed, -5.0, places=2)

    def test_the_measured_walk_reads_as_forward(self) -> None:
        """The real walk, with the real yaw: -154.04 deg gives forward = (0.438, -0.899)."""
        import math

        from azoth_world import movement

        yaw = math.radians(-154.04)
        sim = movement.YawAwareSimulator(start=(0.0, 0.0))
        t = 0.0
        # Walk in the direction the player actually walked: +x, -y.
        for i in range(1, 11):
            t += 0.05
            sim.consume_with_yaw((i * 0.2195, -i * 0.4495), yaw, t)
        self.assertGreater(sim.forward_speed, 4.0, "the measured walk must read as forward")
        self.assertLess(abs(sim.lateral_speed), 0.5, "and not as lateral")

    def test_without_a_yaw_it_still_works(self) -> None:
        """A body without the movement block must not break the simulator."""
        from azoth_world import movement

        sim = movement.YawAwareSimulator(start=(0.0, 0.0))
        for i in range(1, 6):
            sim.consume_with_yaw((i * 0.1, 0.0), None, i * 0.05)
        self.assertIsNone(sim.last_yaw)
        self.assertEqual(sim.yaw_samples, 0)
        self.assertAlmostEqual(sim.position[0], 0.5, places=3)

    def test_the_report_carries_the_frame(self) -> None:
        from azoth_world import movement

        sim = movement.YawAwareSimulator(start=(0.0, 0.0))
        for i in range(1, 6):
            sim.consume_with_yaw((i * 0.2, 0.0), 0.5, i * 0.05)
        d = sim.as_dict()
        for key in ("camera_yaw", "camera_yaw_degrees", "forward_speed",
                    "lateral_speed", "yaw_samples"):
            self.assertIn(key, d)
        self.assertAlmostEqual(d["camera_yaw"], 0.5, places=4)


class TestCorrectionPolicy(unittest.TestCase):
    """The server's DECISION layer: what it does about a divergence, and how it escalates.

    The design comes from the client's own cvars: the CLIENT owns its locomotion and corrects its own
    desync, while the SERVER validates and reacts. So a correction is the server refusing or limiting
    what it accepts — not pushing a position (this build has no working position-push channel:
    `IPositionReceiver`'s apply is `ret 0`, measured).

    The levers that DO exist, in order of severity:
      HOLD        keep the server's own position, do not adopt (the client now diverges)
      FREEZE      stop refreshing the player state stream — MEASURED 2026-10-13 to freeze the
                  client's simulation and make W do nothing
      DISCONNECT  drop a client that keeps claiming the impossible
    """

    def _sim(self, **kw):
        from azoth_world import movement

        return movement.YawAwareSimulator(start=(0.0, 0.0), **kw)

    def _result(self, rejected: bool, violations: int, position=(0.0, 0.0)):
        from azoth_world import movement

        return movement.SimulationResult(
            movement.Authority.HELD if rejected else movement.Authority.CLIENT,
            position,
            0.0,
            rejected,
            "teleport",
            violations,
        )

    def test_a_plausible_sample_is_accepted(self) -> None:
        from azoth_world import movement

        policy = movement.CorrectionPolicy()
        d = policy.observe(self._result(False, 0), (0.0, 0.0))
        self.assertEqual(d.action, movement.CorrectionAction.ACCEPT)
        self.assertTrue(policy.stream_should_flow)

    def test_a_single_rejection_is_only_held(self) -> None:
        """A lag spike must not escalate: one bad claim is normal."""
        from azoth_world import movement

        policy = movement.CorrectionPolicy(freeze_after=5)
        d = policy.observe(self._result(True, 1), (500.0, 0.0))
        self.assertEqual(d.action, movement.CorrectionAction.HOLD)
        self.assertAlmostEqual(d.error, 500.0, places=3)
        self.assertTrue(policy.stream_should_flow, "one violation must not freeze anything")

    def test_repeated_rejections_escalate_to_freeze(self) -> None:
        from azoth_world import movement

        policy = movement.CorrectionPolicy(freeze_after=3, disconnect_after=10)
        actions = [
            policy.observe(self._result(True, n), (500.0, 0.0)).action
            for n in range(1, 4)
        ]
        self.assertEqual(actions[:2], [movement.CorrectionAction.HOLD] * 2)
        self.assertEqual(actions[2], movement.CorrectionAction.FREEZE)
        self.assertFalse(policy.stream_should_flow, "freeze must stop the stream")

    def test_a_client_that_never_converges_is_disconnected(self) -> None:
        from azoth_world import movement

        policy = movement.CorrectionPolicy(freeze_after=2, disconnect_after=5)
        actions = [
            policy.observe(self._result(True, n), (500.0, 0.0)).action
            for n in range(1, 6)
        ]
        self.assertEqual(actions[-1], movement.CorrectionAction.DISCONNECT)

    def test_recovery_resumes_the_stream(self) -> None:
        from azoth_world import movement

        policy = movement.CorrectionPolicy(
            freeze_after=2, disconnect_after=10, recover_after=3
        )
        for n in (1, 2):
            policy.observe(self._result(True, n), (500.0, 0.0))
        self.assertFalse(policy.stream_should_flow)
        # The client starts behaving: three clean samples resume the stream.
        d1 = policy.observe(self._result(False, 2), (0.0, 0.0))
        d2 = policy.observe(self._result(False, 2), (0.0, 0.0))
        self.assertFalse(policy.stream_should_flow, "not yet")
        d3 = policy.observe(self._result(False, 2), (0.0, 0.0))
        self.assertEqual(d3.action, movement.CorrectionAction.ACCEPT)
        self.assertIn("recovered", d3.reason)
        self.assertTrue(policy.stream_should_flow)

    def test_the_divergence_is_the_claim_versus_the_server(self) -> None:
        """The error reported must be the real distance, not zero."""
        from azoth_world import movement

        policy = movement.CorrectionPolicy()
        d = policy.observe(self._result(True, 1, position=(0.0, 0.0)), (3.0, 4.0))
        self.assertAlmostEqual(d.error, 5.0, places=3)

    def test_it_reports_its_decisions(self) -> None:
        from azoth_world import movement

        policy = movement.CorrectionPolicy(
            freeze_after=2, disconnect_after=10, recover_after=3
        )
        for n in (1, 2):
            policy.observe(self._result(True, n), (500.0, 0.0))
        self.assertTrue(policy.frozen)
        # Recovery takes `recover_after` clean samples, so give it that many.
        for _ in range(3):
            policy.observe(self._result(False, 2), (0.0, 0.0))
        d = policy.as_dict()
        self.assertFalse(d["frozen"])
        self.assertEqual(d["decisions"], 5, "2 violations + 3 clean samples")
        self.assertIn("hold", d["by_action"])
        self.assertIn("freeze", d["by_action"])
        self.assertIn("accept", d["by_action"])

    def test_it_rejects_nonsense_configuration(self) -> None:
        from azoth_world import movement

        with self.assertRaises(ValueError):
            movement.CorrectionPolicy(freeze_after=0)
        with self.assertRaises(ValueError):
            movement.CorrectionPolicy(freeze_after=10, disconnect_after=5)
        with self.assertRaises(ValueError):
            movement.CorrectionPolicy(recover_after=0)


class TestTheFreezeGatesTheStream(unittest.TestCase):
    """The correction lever that actually exists: withholding the player state stream.

    MEASURED 2026-10-13: with the local player's state stream off, the client's position is frozen
    and W does nothing. So withholding it is the server's strongest available response to a client
    that keeps claiming impossible movement - it is crude (it stops the client's simulation rather
    than steering it) and it is why the policy only reaches it after HOLD has failed repeatedly.
    """

    def _stream_session(self):
        from azoth_world.rep import PeerSession
        from types import SimpleNamespace

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.v3_responded = True
        session.replay_queue = []
        session.greetings_after_replay = True
        session.out_msg_seq = 1
        session.out_rel_seq = 1
        bundle = SimpleNamespace(seq=0x98, type_id=0x08, body=b"\x00\x01\x08\x01\x40\x01\x01")
        session.state_stream_all = [bundle]
        session.state_stream_queue = [bundle]
        session.state_stream_player = [bundle]
        session.state_stream_player_queue = [bundle]
        session.state_stream_position = []
        session.state_stream_position_queue = []
        session.state_stream_position_next_at = 0.0
        session.state_stream_position_sent = 0
        session.state_position_last_written = None
        session.state_stream_next_at = 0.0
        session.state_stream_player_next_at = 0.0
        session.state_stream_seq = 0x200
        session.state_stream_sent = 0
        session.state_stream_player_sent = 0
        session.state_authoritative_sent = 0
        session.sent = []
        session._send_replay_message = lambda _s, m, **_k: session.sent.append(m)
        session.movement_policy = None
        return session

    def test_a_frozen_policy_stops_the_stream(self) -> None:
        from unittest import mock

        from azoth_world import movement, rep

        session = self._stream_session()
        policy = movement.CorrectionPolicy(freeze_after=1, disconnect_after=10)
        policy.observe(
            movement.SimulationResult(
                movement.Authority.HELD, (0.0, 0.0), 0.0, True, "teleport", 1
            ),
            (500.0, 0.0),
        )
        self.assertFalse(policy.stream_should_flow)
        session.movement_policy = policy

        clock = {"now": 1_000.0}
        with mock.patch("azoth_world.rep.time.monotonic", lambda: clock["now"]):
            for _ in range(30):
                rep.PeerSession.maybe_state_stream(session, None)
                clock["now"] += 0.05
        self.assertEqual(session.sent, [], "a frozen policy must send nothing")

    def test_an_unfrozen_policy_keeps_streaming(self) -> None:
        from unittest import mock

        from azoth_world import movement, rep

        session = self._stream_session()
        session.movement_policy = movement.CorrectionPolicy()
        clock = {"now": 1_000.0}
        with mock.patch("azoth_world.rep.time.monotonic", lambda: clock["now"]):
            for _ in range(30):
                rep.PeerSession.maybe_state_stream(session, None)
                clock["now"] += 0.05
        self.assertTrue(session.sent, "a healthy policy must keep the stream flowing")


class TestTheProvocationLever(unittest.TestCase):
    """The only way to observe the escalation ladder live.

    An honest client never claims impossible movement, so HOLD/FREEZE/DISCONNECT can never fire by
    just playing. `AZOTH_MOVEMENT_FORCE` moves the SERVER's position out from under the client, which
    makes the client's next claim diverge by construction. It exists for tests and is off by default.
    """

    def test_it_is_off_by_default(self) -> None:
        import inspect

        from azoth_world import rep

        self.assertIn('"AZOTH_MOVEMENT_FORCE", ""', inspect.getsource(rep))

    def test_it_reads_the_file_every_call(self) -> None:
        """A test must be able to move the server mid-session without a restart."""
        import tempfile
        import os

        from azoth_world import rep

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("9400.5,2700.25\n")
            path = fh.name
        original = rep.MOVEMENT_FORCE, rep.MOVEMENT_FORCE_FILE
        try:
            rep.MOVEMENT_FORCE = "1"
            rep.MOVEMENT_FORCE_FILE = path
            self.assertEqual(rep.movement_force_spec(), (9400.5, 2700.25))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("9500.75,2650.5\n")
            self.assertEqual(rep.movement_force_spec(), (9500.75, 2650.5))
        finally:
            rep.MOVEMENT_FORCE, rep.MOVEMENT_FORCE_FILE = original
            os.unlink(path)

    def test_a_missing_file_provokes_nothing(self) -> None:
        import pathlib

        from azoth_world import rep

        original = rep.MOVEMENT_FORCE, rep.MOVEMENT_FORCE_FILE
        try:
            rep.MOVEMENT_FORCE = "1"
            rep.MOVEMENT_FORCE_FILE = str(pathlib.Path("does-not-exist-force.txt"))
            self.assertIsNone(rep.movement_force_spec())
        finally:
            rep.MOVEMENT_FORCE, rep.MOVEMENT_FORCE_FILE = original

    def test_a_forced_position_makes_the_next_claim_diverge(self) -> None:
        """The mechanism the live test depends on: moving the server makes the client's claim wrong."""
        from azoth_world import movement

        sim = movement.YawAwareSimulator(start=(0.0, 0.0), prediction_tolerance=2.0)
        sim.consume((0.0, 0.0), 0.0)
        # The provocation: the server jumps 300 u away.
        sim.position = (300.0, 0.0)
        # The client keeps claiming where it really is.
        result = sim.consume((0.1, 0.0), 0.05)
        self.assertTrue(result.rejected, "the client's claim must now be refused")
        self.assertGreater(result.violations, 0)

        policy = movement.CorrectionPolicy(freeze_after=2, disconnect_after=10)
        actions = []
        for _ in range(3):
            r = sim.consume((0.1, 0.0), 0.1)
            actions.append(policy.observe(r, (0.1, 0.0)).action)
        self.assertIn(movement.CorrectionAction.FREEZE, actions)
        self.assertFalse(policy.stream_should_flow)
