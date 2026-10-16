"""Server-side movement validation, built on the position the client streams about itself.

WHY THIS MODULE EXISTS, AND WHAT IT IS NOT
=========================================
This project spent a long time trying to make the server IMPOSE the player's position, through three
independent routes, and all three are now measured dead ends:

* the 4216 / `IPositionReceiver` route — the client-side method the delivery calls is
  `0x140294860`, a `ret 0` **stub** in this build, so even a perfect address and a bound object do
  nothing;
* re-sending the spawn record (48 fragments) with a changed position — accepted, ignored;
* re-sending a minimal 1-fragment record-1 bundle with a changed position — accepted, ignored
  (540 sends, the outbound datagrams decoded to prove the wire carried the new value, and the
  client's own accessor never moved across 358 samples).

And the capture explains why: the local player's position is replicated state that is sent **only
when it changes** — the spawn copies carry 7 position pairs, every delta copy carries none — so
there is no example of a server position correction anywhere in the record. In ALC ("Actor Local
Control") the **client is authoritative over its own position**; the server's job is to VALIDATE it
and correct on desync, not to drive it.

So this module does the part the protocol actually asks for, and it does it from data the server
already receives: the client streams its own position ~20x/s on channel 1 (see `javelin/alc.py`),
and the server now parses it. `MovementValidator` turns that stream into verdicts.

WHAT IT FLAGS, AND HOW THE BOUNDS WERE CHOSEN
============================================
Measured on a live session (2026-10-16), speed between consecutive reports while walking normally:
median **2.7–3.9 u/s**, p90 **5.8–6.4 u/s**, max **~5.8–14.5 u/s**. Two artifacts must not be
mistaken for cheating:

* the **spawn transition** produces a one-time jump of ~18 u between two consecutive records
  (~0.05 s apart), which reads as **239–366 u/s**. It is excluded by a settle window, and the
  exclusion is the reason the window exists rather than a guessed convention;
* a single 1 s-sampled measurement is coarser than the 20/s stream, so the per-sample speed from the
  stream is the meaningful one.

The defaults are therefore deliberately LOOSE (a teleport needs >50 u in one sample, a speed
violation >30 u/s) so that a normal session never trips them, and every flag is LOGGED rather than
acted on: the point is to measure what real movement looks like before choosing a policy, and the
log is the measurement. A caller that wants a stricter policy passes its own bounds.

This is validation, not enforcement: with the client authoritative, the server can flag and record,
and cannot correct through any path this build offers.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

__all__ = [
    "MovementSample",
    "MovementFlag",
    "MovementValidator",
    "MAX_SPEED",
    "MAX_TELEPORT_DISTANCE",
    "SETTLE_S",
    "MIN_DT_S",
    "SPEED_WINDOW_S",
    "DESYNC_THRESHOLD",
    "DesyncTracker",
]

# Loose on purpose (see the module docstring): a normal session must not trip them.
MAX_SPEED = float(os.environ.get("AZOTH_MOVEMENT_MAX_SPEED", "30.0"))
MAX_TELEPORT_DISTANCE = float(os.environ.get("AZOTH_MOVEMENT_MAX_TELEPORT", "50.0"))
# The spawn/LOAD transition is not movement and must be excluded. MEASURED 2026-10-16: after the
# state stream armed at 21:05:26 the client reported genuine 40-73 u/s samples up to 21:06:23 -
# i.e. the transition lasts ~57 s, much longer than the 10 s this default used to be, and with a
# 10 s window every one of those samples was flagged (17 flags in a session that was walking
# normally). 60 s is that measurement rounded up; it should be replaced by a real "loading
# finished" signal when one exists, and until then it is a measured number rather than a guess.
SETTLE_S = float(os.environ.get("AZOTH_MOVEMENT_SETTLE_S", "60.0"))
# Two consecutive reports closer together than this are a BURST (the server drained several
# datagrams back to back), not a sample interval: the client streams at ~20/s = 50 ms, and a
# measured flag had dt = 1.4 ms, which turns a 0.28 u step into "204 u/s". Below this floor the
# speed is not computed at all. The teleport check is dt-independent and still runs.
MIN_DT_S = float(os.environ.get("AZOTH_MOVEMENT_MIN_DT_S", "0.02"))
# Speed is measured over a WINDOW, not between consecutive reports. MEASURED 2026-10-16: with
# per-report speeds a session that was merely WALKING reported peaks of 33-67 u/s (distance
# 1.6-2.8 u over dt 25-59 ms) and tripped a 30 u/s bound 7 times, while the SAME stream sampled
# once a second says the player walks at 2.7-5.8 u/s. The cause is aliasing: the ALC stream runs
# at ~20/s but the client's position only changes on its own tick, so several reports repeat a
# value and then one carries a step. A window is also what a real server does, and it makes the
# number comparable to the measurements the bound was chosen from.
SPEED_WINDOW_S = float(os.environ.get("AZOTH_MOVEMENT_WINDOW_S", "0.5"))

# ---------------------------------------------------------------------------------------------
# DESYNC: the client's position versus the server's own belief
# ---------------------------------------------------------------------------------------------
# The server cannot CORRECT the client's position in this build - all three shapes of the local
# player's record are measured dead (the full spawn record, a minimal 1-fragment bundle, and the
# delta-shaped 9-fragment record tested with the player deliberately desynced), and the message the
# client would receive a position through (`IPositionReceiver`) is a `ret 0` stub. What the server CAN
# do, and what a real server does, is DETECT the drift and escalate on it. That is this tracker.
#
# CHOOSING THE THRESHOLD. The two positions are not the same measurement: the client streams its own
# viewpoint and the server's asserted value is the capture's, and the measured reference offset between
# them is **2-3.7 u** and DIFFERS BETWEEN SESSIONS (it is geometric, not a lag). So a tight threshold
# would fire on the instrument difference rather than on cheating. The default is **25 u**, roughly
# 10x the measured noise floor, and the deviation is logged continuously so a tighter number can be
# chosen from data once the offset is calibrated per session.
DESYNC_THRESHOLD = float(os.environ.get("AZOTH_MOVEMENT_DESYNC_U", "25.0"))


@dataclass(frozen=True)
class DesyncReport:
    """How far the client's reported position is from the server's own belief."""

    distance: float
    server_x: float
    server_y: float
    client_x: float
    client_y: float


class DesyncTracker:
    """Compares the position the SERVER believes against the position the CLIENT reports.

    `note_server(x, y)` records the server's belief - the position it asserted (a spawn override, a
    captured spawn value, or an authoritative simulation once one exists). `observe(x, y)` records the
    client's claim and returns a report when the two are farther apart than `threshold`.

    Deliberately tiny and stateless apart from two points: this is a measurement, and the moment it
    starts holding state is the moment it can be wrong in a way that is hard to see.
    """

    def __init__(self, threshold: float = DESYNC_THRESHOLD) -> None:
        self.threshold = threshold
        self.server: tuple[float, float] | None = None
        self.client: tuple[float, float] | None = None
        self.max_deviation = 0.0
        self.reports = 0

    def note_server(self, x: float, y: float) -> None:
        """Record the position the server believes / last asserted."""
        self.server = (x, y)

    def observe(self, x: float, y: float) -> DesyncReport | None:
        """Record the client's claim; report only when it exceeds the threshold.

        Returns None when either side is unknown: without the server's belief there is nothing to
        compare against, and reporting on a missing half would be a guess.
        """
        self.client = (x, y)
        if self.server is None:
            return None
        distance = math.dist(self.server, self.client)
        # The maximum deviation is tracked on EVERY sample, not only on the ones above the threshold:
        # that number is what a tighter threshold has to be chosen from.
        self.max_deviation = max(self.max_deviation, distance)
        if distance <= self.threshold:
            return None
        self.reports += 1
        return DesyncReport(
            distance=distance,
            server_x=self.server[0],
            server_y=self.server[1],
            client_x=x,
            client_y=y,
        )

    def stats(self) -> dict:
        return {
            "threshold_u": self.threshold,
            "reports": self.reports,
            "max_deviation_u": round(self.max_deviation, 3),
            "server": [round(v, 4) for v in self.server] if self.server else None,
            "client": [round(v, 4) for v in self.client] if self.client else None,
        }


@dataclass(frozen=True)
class MovementSample:
    """One position the client reported about itself, with the clock it arrived on."""

    at: float
    x: float
    y: float


@dataclass(frozen=True)
class MovementFlag:
    """A validation verdict. `kind` is "teleport" or "speed"."""

    kind: str
    distance: float
    dt: float
    speed: float
    x: float
    y: float


class MovementValidator:
    """Turns a stream of client-reported positions into speed/teleport verdicts.

    Deliberately stateless apart from the last sample and the settle clock, so it is trivial to
    test and cannot itself become a source of state bugs.
    """

    def __init__(
        self,
        max_speed: float = MAX_SPEED,
        max_teleport_distance: float = MAX_TELEPORT_DISTANCE,
        settle_s: float = SETTLE_S,
        min_dt_s: float = MIN_DT_S,
        window_s: float = SPEED_WINDOW_S,
    ) -> None:
        self.max_speed = max_speed
        self.max_teleport_distance = max_teleport_distance
        self.settle_s = settle_s
        self.min_dt_s = min_dt_s
        self.window_s = window_s
        # Recent samples, oldest first, pruned to `window_s` plus one older reference. Small by
        # construction (a 0.5 s window at 20/s is 10 entries).
        self.recent: list[MovementSample] = []
        self.first_at: float | None = None
        self.last: MovementSample | None = None
        self.samples = 0
        self.flags = 0
        self.max_speed_seen = 0.0
        self.max_distance_seen = 0.0
        self.last_speed: float | None = None
        self.settled = False

    def observe(self, at: float, x: float, y: float) -> MovementFlag | None:
        """Feed one sample. Returns a flag when it violates a bound, else None.

        Two checks, deliberately of different natures:

        * TELEPORT is a distance between CONSECUTIVE reports, and is dt-independent, so it works
          even in a burst. It is the check that catches a genuine jump.
        * SPEED is measured over `window_s`, because per-report speeds alias (see SPEED_WINDOW_S).

        Nothing is flagged during the settle window, and nothing is flagged for the FIRST sample
        (there is no previous position to compare against). A non-monotonic clock is ignored rather
        than treated as a teleport: a clock jump is not movement.
        """
        if self.first_at is None:
            self.first_at = at
        self.samples += 1
        previous = self.last
        self.last = MovementSample(at=at, x=x, y=y)
        if not self.settled and at - self.first_at >= self.settle_s:
            self.settled = True
        if previous is None or not self.settled:
            return None
        dt = at - previous.at
        if dt <= 0:
            return None
        distance = math.dist((previous.x, previous.y), (x, y))
        # The teleport check is a distance check and does not need a sane interval.
        if distance > self.max_teleport_distance:
            self.flags += 1
            self.max_distance_seen = max(self.max_distance_seen, distance)
            return MovementFlag(
                kind="teleport", distance=distance, dt=dt,
                speed=distance / dt if dt > 0 else float("inf"), x=x, y=y,
            )
        # Windowed speed. The reference is the newest sample at least `window_s` old, so the
        # interval is real and the aliasing above averages out.
        self.recent.append(self.last)
        self.recent = [s for s in self.recent if at - s.at <= self.window_s * 2]
        reference = None
        for s in self.recent:
            if at - s.at >= self.window_s:
                reference = s
            else:
                break
        if reference is None:
            return None
        window_dt = at - reference.at
        if window_dt < self.min_dt_s:
            return None
        windowed = math.dist((reference.x, reference.y), (x, y)) / window_dt
        self.last_speed = windowed
        self.max_speed_seen = max(self.max_speed_seen, windowed)
        self.max_distance_seen = max(self.max_distance_seen, distance)
        if windowed <= self.max_speed:
            return None
        self.flags += 1
        return MovementFlag(
            kind="speed", distance=math.dist((reference.x, reference.y), (x, y)),
            dt=window_dt, speed=windowed, x=x, y=y,
        )

    def stats(self) -> dict:
        """A snapshot for the log, so a bound can be chosen from measurement."""
        return {
            "samples": self.samples,
            "flags": self.flags,
            "max_speed_seen": round(self.max_speed_seen, 3),
            "max_distance_seen": round(self.max_distance_seen, 3),
            "last_speed": round(self.last_speed, 3) if self.last_speed is not None else None,
            "settled": self.settled,
            "min_dt_s": self.min_dt_s,
            "window_s": self.window_s,
        }
