"""Server-side movement validation over the position the client reports about itself.

WHY THIS EXISTS. Three independent ways of making the server IMPOSE the local player's position are
measured dead ends (the 4216 delivery's method is a `ret 0` stub; re-sending the spawn record with a
changed position is accepted and ignored; a minimal 1-fragment record-1 bundle likewise). The
capture says why: the local player's position is replicated state sent only WHEN IT CHANGES - the
spawn copies carry 7 position pairs and every delta copy carries none - so ALC has the CLIENT
authoritative over its own position and the server validating it.

The numbers in these tests are all MEASURED, and each names its artifact, because a naive check
flags a normal session. Three artifacts were found live on 2026-10-16:

* the world-LOAD transition: genuine 40-73 u/s samples for ~57 s after the stream armed;
* BURSTS: two reports 1.4 ms apart, which turns a 0.28 u step into "204 u/s";
* ALIASING: the stream runs at ~20/s but the client's position changes on its own tick, so
  per-report speeds read 33-67 u/s while the player merely WALKS at 2.7-5.8 u/s.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT / "src")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from azoth_world.movement import MovementValidator  # noqa: E402


def feed(v: MovementValidator, samples):
    """Feed (at, x, y) samples; return the flags raised."""
    out = []
    for at, x, y in samples:
        flag = v.observe(at, x, y)
        if flag is not None:
            out.append(flag)
    return out


class TestBasicVerdicts(unittest.TestCase):
    def test_the_first_sample_never_flags(self):
        v = MovementValidator(settle_s=0.0)
        self.assertIsNone(v.observe(0.0, 9343.0, 2786.0))
        self.assertEqual(v.samples, 1)
        self.assertEqual(v.flags, 0)

    def test_normal_walking_does_not_flag(self):
        """Walking at ~5 u/s for 3 s, twice per window, must stay clean."""
        v = MovementValidator(settle_s=0.0, window_s=0.5)
        samples = [(i * 0.05, 9343.0 + i * 0.25, 2786.0) for i in range(60)]  # 5 u/s
        self.assertEqual(feed(v, samples), [])
        self.assertAlmostEqual(v.max_speed_seen, 5.0, places=6)

    def test_a_teleport_flags_and_is_dt_independent(self):
        v = MovementValidator(settle_s=0.0)
        v.observe(0.0, 9343.0, 2786.0)
        flag = v.observe(0.001, 9443.0, 2786.0)  # 100 u in 1 ms
        self.assertIsNotNone(flag)
        self.assertEqual(flag.kind, "teleport")
        self.assertAlmostEqual(flag.distance, 100.0, places=6)

    def test_a_speed_violation_flags_over_the_window(self):
        """40 u/s sustained: the windowed speed is the real speed, not an aliased spike."""
        v = MovementValidator(max_speed=30.0, max_teleport_distance=50.0, settle_s=0.0, window_s=0.5)
        samples = [(i * 0.05, 9343.0 + i * 2.0, 2786.0) for i in range(20)]  # 40 u/s
        flags = feed(v, samples)
        self.assertTrue(flags, "40 u/s must flag against a 30 u/s bound")
        self.assertEqual(flags[0].kind, "speed")
        self.assertAlmostEqual(v.max_speed_seen, 40.0, delta=0.5)

    def test_a_non_monotonic_clock_is_not_a_teleport(self):
        """A clock jump is not movement; treating it as one would flag on a scheduler hiccup."""
        v = MovementValidator(settle_s=0.0)
        v.observe(10.0, 9343.0, 2786.0)
        self.assertIsNone(v.observe(9.0, 9943.0, 2786.0))
        self.assertEqual(v.flags, 0)


class TestMeasuredArtifacts(unittest.TestCase):
    """The three artifacts a real session produced, which the first version flagged."""

    def test_the_load_transition_is_covered_by_the_settle_window(self):
        """Measured: genuine 40-73 u/s samples up to 57 s after the stream armed."""
        v = MovementValidator(settle_s=60.0)
        v.observe(0.0, 9343.0, 2786.0)
        # the load phase: 3.579 u in 49.2 ms = 72.8 u/s, at t=57 s
        samples = [(57.0 + i * 0.05, 9343.0 + i * 3.64, 2786.0) for i in range(20)]  # 72.8 u/s
        self.assertEqual(feed(v, samples), [])
        self.assertFalse(v.settled)

    def test_a_load_sized_speed_after_settling_still_flags(self):
        """The exclusion is a window, not a blind spot: the same speed later must flag."""
        v = MovementValidator(settle_s=60.0, max_speed=30.0, window_s=0.5)
        v.observe(0.0, 9343.0, 2786.0)
        v.observe(70.0, 9343.0, 2786.0)
        self.assertTrue(v.settled)
        samples = [(70.0 + i * 0.05, 9343.0 + i * 3.64, 2786.0) for i in range(20)]
        flags = feed(v, samples)
        self.assertTrue(flags)
        self.assertEqual(flags[0].kind, "speed")

    def test_a_burst_does_not_create_a_speed_sample(self):
        """Measured: 0.282 u in 1.4 ms read as 204 u/s. A burst is not a sample interval."""
        v = MovementValidator(settle_s=0.0, min_dt_s=0.02, window_s=0.5)
        v.observe(0.0, 9343.0, 2786.0)
        # a drained queue: three reports microseconds apart
        v.observe(0.0014, 9343.282, 2786.0)
        v.observe(0.0028, 9343.400, 2786.0)
        self.assertEqual(v.flags, 0)
        self.assertLess(v.max_speed_seen, 1.0)

    def test_aliasing_does_not_flag_a_walking_player(self):
        """THE regression that mattered: the client's position changes on its own tick.

        Measured while merely walking: the stream runs at 20/s but the position only moves every
        ~0.3 s, so per-report speeds read 33-67 u/s (distance 1.6-2.8 u over dt 25-59 ms) and a
        30 u/s bound fired 7 times. Reproduce that pattern exactly: a step every 6 reports with a
        real speed of 5.8 u/s.
        """
        v = MovementValidator(settle_s=0.0, max_speed=30.0, window_s=0.5)
        samples = []
        for i in range(60):
            step = i // 6  # the position changes once every 6 reports
            samples.append((i * 0.05, 9343.0 + step * 1.74, 2786.0))  # 1.74 u / 0.3 s = 5.8 u/s
        self.assertEqual(feed(v, samples), [], "aliasing must not be mistaken for speed")
        # The WINDOWED value oscillates around the true speed, because a 0.5 s window over a
        # 0.3 s tick contains one step or two. What matters is the band: it sits far below the
        # bound, where the per-report view (0.87-2.8 u in 25-59 ms = 17-67 u/s) crossed it.
        self.assertGreater(v.max_speed_seen, 1.0)
        self.assertLess(v.max_speed_seen, 10.0, "the windowed speed must be the real speed")
        # And the comparison that shows why the window exists: per-report speed peaks far higher.
        per_report_peak = 1.74 / 0.05
        self.assertGreater(per_report_peak, v.max_speed_seen * 2)

    def test_the_defaults_carry_the_measured_values(self):
        from azoth_world.movement import MIN_DT_S, SETTLE_S, SPEED_WINDOW_S

        self.assertGreater(SETTLE_S, 57.0)          # the load phase lasted ~57 s
        self.assertGreaterEqual(MIN_DT_S, 0.02)     # the stream is ~20/s = 50 ms
        self.assertLess(MIN_DT_S, 0.05)
        # A window at least as long as the client's own position tick (measured ~0.3 s).
        self.assertGreaterEqual(SPEED_WINDOW_S, 0.3)

    def test_the_default_speed_bound_clears_the_measured_walking_maximum(self):
        from azoth_world.movement import MAX_SPEED

        # Measured walking: 2.7-5.8 u/s averaged, and the windowed value must sit in that band.
        self.assertGreater(MAX_SPEED, 6.4)   # p90 of the averaged measurement
        self.assertLess(MAX_SPEED, 50.0)     # still meaningful as a clamp


class TestStats(unittest.TestCase):
    def test_stats_report_what_a_bound_should_be_chosen_from(self):
        v = MovementValidator(settle_s=0.0, window_s=0.5)
        samples = [(i * 0.05, 9343.0 + i * 0.25, 2786.0) for i in range(20)]
        feed(v, samples)
        stats = v.stats()
        self.assertEqual(stats["samples"], 20)
        self.assertEqual(stats["flags"], 0)
        self.assertAlmostEqual(stats["max_speed_seen"], 5.0, places=6)
        self.assertIsNotNone(stats["last_speed"])
        self.assertIn("window_s", stats)
        self.assertIn("min_dt_s", stats)

    def test_it_reports_no_speed_until_a_full_window_exists(self):
        v = MovementValidator(settle_s=0.0, window_s=0.5)
        v.observe(0.0, 9343.0, 2786.0)
        v.observe(0.05, 9343.25, 2786.0)
        self.assertIsNone(v.last_speed, "0.5 s of samples is required before a speed exists")
        self.assertEqual(v.flags, 0)


if __name__ == "__main__":
    unittest.main()


class TestDesyncTracker(unittest.TestCase):
    """The drift between the client's claim and the server's own belief.

    The server cannot CORRECT the client's position in this build - all three shapes of the local
    player's record are measured dead and the position interface is a `ret 0` stub - so detecting and
    escalating is the honest half of authority.
    """

    def test_a_lagging_client_is_reported(self):
        from azoth_world.movement import DesyncTracker

        t = DesyncTracker(threshold=25.0)
        t.note_server(9343.6416, 2786.7327)
        # walks away: measured ~23 u in the delta experiment, then ~55 u
        self.assertIsNone(t.observe(9351.6084, 2769.4785))  # ~17.5 u, under the threshold
        report = t.observe(9300.0, 2750.0)                  # ~55 u, over it
        self.assertIsNotNone(report)
        self.assertEqual(report.server_x, 9343.6416)
        self.assertEqual(report.client_x, 9300.0)
        self.assertEqual(t.reports, 1)

    def test_the_measured_reference_offset_does_not_trip_it(self):
        """The two positions are different measurements; the offset is 2-3.7 u and varies."""
        from azoth_world.movement import DesyncTracker

        t = DesyncTracker(threshold=25.0)
        t.note_server(9343.6416, 2786.7327)
        for dx, dy in ((2.0, 1.2), (-1.4, 3.4), (2.6, -0.9)):
            with self.subTest(offset=(dx, dy)):
                self.assertIsNone(t.observe(9343.6416 + dx, 2786.7327 + dy))
        self.assertEqual(t.reports, 0)
        # and the deviation is still tracked, which is what a tighter threshold needs
        self.assertGreater(t.max_deviation, 2.0)

    def test_without_a_server_belief_there_is_nothing_to_report(self):
        """A missing half must not be guessed at."""
        from azoth_world.movement import DesyncTracker

        t = DesyncTracker()
        self.assertIsNone(t.observe(9300.0, 2750.0))
        self.assertEqual(t.reports, 0)

    def test_the_max_deviation_is_tracked_even_below_the_threshold(self):
        from azoth_world.movement import DesyncTracker

        t = DesyncTracker(threshold=100.0)
        t.note_server(9343.0, 2786.0)
        t.observe(9353.0, 2786.0)  # 10 u
        t.observe(9343.0, 2794.0)  # 8 u
        self.assertEqual(t.reports, 0)
        self.assertAlmostEqual(t.max_deviation, 10.0, places=6)

    def test_stats_carry_both_sides_and_the_threshold(self):
        from azoth_world.movement import DesyncTracker

        t = DesyncTracker(threshold=25.0)
        t.note_server(9343.0, 2786.0)
        t.observe(9300.0, 2750.0)
        stats = t.stats()
        self.assertEqual(stats["threshold_u"], 25.0)
        self.assertEqual(stats["reports"], 1)
        self.assertEqual(stats["server"], [9343.0, 2786.0])
        self.assertEqual(stats["client"], [9300.0, 2750.0])

    def test_the_default_threshold_is_far_above_the_measured_noise_floor(self):
        from azoth_world.movement import DESYNC_THRESHOLD

        # The instrument offset is measured at 2-3.7 u; the threshold must not fire on it.
        self.assertGreater(DESYNC_THRESHOLD, 3.7 * 5)
