"""Server authority over the player's movement: claim, plausibility, desync, correction.

WHY THIS MODULE EXISTS
=====================
`azoth_world.javelin.alc` reads what the client *says* about its position. This module
decides what the server does with that claim. The two are separate on purpose: the reader
is a wire format, this is policy, and policy is where the desync argument lives.

THE FOUR STEPS, AND WHICH ONE IS ACTUALLY BLOCKED
=================================================
1. **Read** the claim — `javelin.alc`. Measured working.
2. **Validate** plausibility — `MovementValidator`. This is anti-cheat: is the movement
   physically possible? It is not desync detection.
3. **Detect** divergence — `DesyncTracker`. The client's claim against the server's own
   truth.
4. **Correct** — send authoritative state. **This is the step that is blocked**, and it is
   blocked on a specific channel, not in general: `ReceivePlayerPositionClientMsg` (4216)
   needs a client-side `IPositionReceiver` that this build never instantiates (installer 0,
   register 0, 0 of 225 registered vtables over 37,063 targets). The channel that DOES
   work is replicated state: writing the position into the record-1 state bundle moved the
   client's own accessor to the server's value with **0.0000 u** error on 2026-10-14.

So correction is not "unavailable". It is available as replicated state and unavailable as
an RMI. Everything in this module is the half that works today.

THREE VERDICTS, NOT ONE BOOLEAN
===============================
The classic failure is collapsing "the numbers differ" into "desync". A per-sample equality
test answers all three of these wrongly:

* **ignore** — the error is at or below the noise floor. Correcting here is what produces
  rubber-banding: the client is jittering, not diverging.
* **correct** — the error is real and *sustained*. One bad sample is a dropped datagram;
  a run of them is a divergence.
* **reject** — the movement is impossible (speed or teleport). That is adversarial or a
  bug, and it is the validator's verdict, not the tracker's.

THE NOISE FLOOR IS NOT A MAGIC NUMBER
=====================================
The client is *predicted*: its claim leads the server's truth by roughly one round trip, so
a perfectly honest client shows error proportional to `speed * rtt`. A threshold below that
value reports every moving player as desynced. `DesyncTracker` therefore derives its floor
as `max(configured_floor, max_speed * rtt_s)` and lets a caller raise it with a measured
value.

THE REFERENCE OFFSET IS AN INSTRUMENT PROPERTY, AND IT MUST BE SUBTRACTED
=======================================================================
Measured 2026-10-18 against the client's own `nw_getPlayerPosition` accessor: the wire claim
differs from what the accessor reports by **2.04 u to 4.03 u**, and that offset varies per
session. It is tempting to treat it as a desync and correct it — that is wrong, and it is
exactly the mistake that makes a threshold impossible to tighten.

**A live run then refuted the first version of this design.** The first `DesyncTracker`
compared the raw claim with the server's own position and argued that no offset was needed
because both were "the same quantity". Measured live on 2026-10-18 (session
`session-20261018T0917Z`): the error was **exactly 4.0311 u in all 2,562 samples over two
minutes**, with a single distinct position — the player never moved. A perfectly in-sync
player therefore sat permanently 4.03 u above a 2.0 u floor and was reported as desynced.
The claim and the server's position are NOT the same quantity; they differ by the instrument
offset.

So the offset IS part of the comparison, and the honest consequence is a hard rule:

* the offset is calibrated per session from paired samples (claim minus truth), and
* **an uncalibrated instrument must never emit a desync verdict.** With the offset unknown, a
  4 u difference is indistinguishable from a real divergence, so reporting either way would
  be a guess. `DesyncTracker` therefore fails open — it returns IGNORE with an explicit
  "uncalibrated" reason — until a calibration with a small enough residual exists.

The offset can be calibrated without a probe: at spawn the client is at the position the
server wrote, so the constant difference over the first samples after load IS the offset. A
wide spread there means the player was already moving, and the calibration is rejected rather
than averaged into a wrong value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class Verdict(Enum):
    """What the server should do about one observation."""

    IGNORE = "ignore"
    CORRECT = "correct"
    REJECT = "reject"


@dataclass(frozen=True)
class Validation:
    """The plausibility verdict for one movement sample."""

    verdict: Verdict
    reason: str
    speed: float | None = None
    distance: float | None = None


@dataclass(frozen=True)
class DesyncReport:
    """One claim-versus-truth comparison."""

    verdict: Verdict
    error: float
    threshold: float
    streak: int
    reason: str


class MovementValidator:
    """Is this movement physically possible?

    Deliberately separate from desync detection. A validator answers "could a player have
    done this"; a tracker answers "does the server agree with where the client thinks it
    is". Conflating them produces a threshold that fires on lag and misses on cheating.

    Two checks, both from the recorded design:

    * **speed** over a window (default 0.5 s) — the claim cannot move faster than the
      game's own limit, allowing for the prediction lead.
    * **teleport** — a single jump larger than anything the movement system can produce.
      This is the check that catches a client that simply rewrites its position.
    """

    def __init__(
        self,
        *,
        max_speed: float = 12.0,
        teleport_distance: float = 50.0,
        window_s: float = 0.5,
    ) -> None:
        if max_speed <= 0:
            raise ValueError("max_speed must be positive")
        if teleport_distance <= 0:
            raise ValueError("teleport_distance must be positive")
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self.max_speed = max_speed
        self.teleport_distance = teleport_distance
        self.window_s = window_s
        self._last: tuple[float, float, float] | None = None
        self._window: list[tuple[float, float, float]] = []

    def reset(self) -> None:
        self._last = None
        self._window.clear()

    def observe(self, x: float, y: float, now: float) -> Validation:
        """Check one sample. ``now`` is any monotonic clock in seconds."""
        if self._last is None:
            self._last = (x, y, now)
            self._window.append((x, y, now))
            return Validation(Verdict.IGNORE, "first sample")

        lx, ly, lt = self._last
        dt = now - lt
        if dt <= 0:
            return Validation(Verdict.IGNORE, "non-monotonic sample")

        step = math.hypot(x - lx, y - ly)
        if step > self.teleport_distance:
            self._last = (x, y, now)
            self._window = [(x, y, now)]
            return Validation(
                Verdict.REJECT,
                f"teleport: {step:.3f} u in {dt:.3f} s",
                distance=step,
            )

        # Speed over the window, not between two adjacent samples: at 20 Hz a single
        # sample is too noisy to distinguish a sprint from a stall.
        self._window.append((x, y, now))
        while self._window and now - self._window[0][2] > self.window_s:
            self._window.pop(0)
        ox, oy, ot = self._window[0]
        span = now - ot
        self._last = (x, y, now)
        if span <= 0:
            return Validation(Verdict.IGNORE, "window not yet full", distance=step)

        speed = math.hypot(x - ox, y - oy) / span
        if speed > self.max_speed:
            return Validation(
                Verdict.REJECT,
                f"speed {speed:.3f} u/s over {span:.3f} s exceeds {self.max_speed:.3f}",
                speed=speed,
                distance=step,
            )
        return Validation(Verdict.IGNORE, "plausible", speed=speed, distance=step)


class DesyncTracker:
    """Does the server agree with where the client thinks it is?

    The claim is corrected by the calibrated instrument offset before comparison, because the
    wire value and the server's position are different quantities (see the module docstring,
    and the live run that refuted the no-offset version).

    While the instrument is UNCALIBRATED this tracker never reports a desync: a 4 u difference
    is indistinguishable from a real divergence, so any verdict would be a guess. It fails
    open with an explicit reason instead of silently comparing raw values.
    """

    def __init__(
        self,
        *,
        floor: float = 1.0,
        sustained_samples: int = 5,
        rtt_s: float = 0.0,
        max_speed: float = 12.0,
        offset: tuple[float, float] | None = None,
    ) -> None:
        if floor < 0:
            raise ValueError("floor cannot be negative")
        if sustained_samples < 1:
            raise ValueError("sustained_samples must be at least 1")
        if rtt_s < 0:
            raise ValueError("rtt_s cannot be negative")
        self.floor = floor
        self.sustained_samples = sustained_samples
        self.rtt_s = rtt_s
        self.max_speed = max_speed
        self._offset = offset
        self._streak = 0

    @property
    def offset(self) -> tuple[float, float] | None:
        return self._offset

    @property
    def calibrated(self) -> bool:
        return self._offset is not None

    def set_offset(self, offset: tuple[float, float]) -> None:
        """Install a calibrated offset. Clears any streak built on the old frame."""
        self._offset = offset
        self._streak = 0

    @property
    def threshold(self) -> float:
        """The floor a corrected claim must exceed, including the prediction lead.

        A predicted client legitimately leads the server by about one round trip, so the
        honest error while moving is on the order of ``speed * rtt``. A threshold below
        that reports every moving player as desynced.
        """
        return max(self.floor, self.max_speed * self.rtt_s)

    def rebaseline(self) -> None:
        """Forget the streak. Call this after the server corrects the client.

        The correction changes the truth the claim is compared against, so a streak that
        started before it says nothing about the divergence after it.
        """
        self._streak = 0

    def observe(self, claim: tuple[float, float], truth: tuple[float, float]) -> DesyncReport:
        if self._offset is None:
            return DesyncReport(
                Verdict.IGNORE, 0.0, self.threshold, 0,
                "instrument uncalibrated: a difference cannot be told from the offset",
            )
        cx = claim[0] - self._offset[0]
        cy = claim[1] - self._offset[1]
        error = math.hypot(cx - truth[0], cy - truth[1])
        limit = self.threshold
        if error <= limit:
            self._streak = 0
            return DesyncReport(
                Verdict.IGNORE, error, limit, 0,
                f"{error:.3f} u is within the {limit:.3f} u floor",
            )
        self._streak += 1
        if self._streak < self.sustained_samples:
            return DesyncReport(
                Verdict.IGNORE, error, limit, self._streak,
                f"{error:.3f} u over the floor for {self._streak} of "
                f"{self.sustained_samples} samples",
            )
        return DesyncReport(
            Verdict.CORRECT, error, limit, self._streak,
            f"{error:.3f} u over the floor for {self._streak} samples",
        )


@dataclass(frozen=True)
class Calibration:
    """The measured instrument offset between the wire claim and the accessor."""

    dx: float
    dy: float
    samples: int
    residual: float
    """RMS distance of the samples from the calibrated offset: the instrument's precision."""

    @property
    def magnitude(self) -> float:
        return math.hypot(self.dx, self.dy)


class ReferenceOffset:
    """Calibrates the gap between the wire claim and the server's own position.

    This offset MUST be subtracted before a desync comparison (see the module docstring and
    the live run that refuted the no-offset version: a perfectly in-sync player sat 4.0311 u
    above a 2.0 u floor for two minutes).

    It needs no probe. At spawn the client is at the position the server wrote, so the
    constant difference over the first samples after load IS the offset. A wide spread means
    the player was already moving, in which case the calibration is REJECTED rather than
    averaged into a wrong value - a wrong offset silently hides real desync, which is worse
    than having none.
    """

    def __init__(self, *, samples: int = 20, max_residual: float = 0.5) -> None:
        if samples < 1:
            raise ValueError("samples must be at least 1")
        if max_residual < 0:
            raise ValueError("max_residual cannot be negative")
        self.samples_required = samples
        self.max_residual = max_residual
        self._pairs: list[tuple[float, float]] = []

    def reset(self) -> None:
        self._pairs.clear()

    @property
    def count(self) -> int:
        return len(self._pairs)

    def observe(self, claim: tuple[float, float], truth: tuple[float, float]) -> None:
        """Record one paired sample: what the wire said and what the server believes."""
        if len(self._pairs) < self.samples_required:
            self._pairs.append((claim[0] - truth[0], claim[1] - truth[1]))

    def calibrate(self) -> Calibration | None:
        """The mean offset and its spread, or ``None`` with no samples."""
        if not self._pairs:
            return None
        n = len(self._pairs)
        dx = sum(p[0] for p in self._pairs) / n
        dy = sum(p[1] for p in self._pairs) / n
        rms = math.sqrt(
            sum((p[0] - dx) ** 2 + (p[1] - dy) ** 2 for p in self._pairs) / n
        )
        return Calibration(dx=dx, dy=dy, samples=n, residual=rms)

    def accepted(self) -> Calibration | None:
        """The calibration, but only if it is complete AND tight enough to trust.

        ``None`` means "do not compare yet". Returning a plausible-looking offset from a
        window in which the player was moving would hide real divergence, so the caller is
        told to keep waiting instead.
        """
        if len(self._pairs) < self.samples_required:
            return None
        calibration = self.calibrate()
        if calibration is None or calibration.residual > self.max_residual:
            return None
        return calibration

    def to_accessor(self, claim: tuple[float, float], calibration: Calibration) -> tuple[float, float]:
        """Translate a wire claim into what the accessor would report for the same instant."""
        return (claim[0] - calibration.dx, claim[1] - calibration.dy)


@dataclass
class LoadGate:
    """The real "the player is in the world" signal, replacing a fixed grace period.

    Measured 2026-10-18 over 12 recorded sessions: the client's input body grows
    `93 → 108 → 123 → 138 → 153 → 154` bytes and only carries a position once it crosses
    roughly 280 bytes, which happened at **t+8s to t+14s** after the first channel-1 record
    in 11 of the 12. The twelfth never grew at all — a failed load, which this gate reports
    as "never ready" instead of letting the server validate a stream that carries no claim.

    A fixed 60 s timer is therefore both too slow (it blinds the server for 45-50 s of a
    window in which the player is already controllable) and uninformative (it cannot tell a
    loaded session from a failed one).
    """

    ready_at: float | None = None
    ready_after_s: float | None = None
    observations: int = 0
    _first_seen: float | None = field(default=None, repr=False)

    def observe(self, *, ready: bool, now: float) -> bool:
        """Feed one sample; returns True only on the transition into ready."""
        self.observations += 1
        if self._first_seen is None:
            self._first_seen = now
        if self.ready_at is not None or not ready:
            return False
        self.ready_at = now
        self.ready_after_s = now - self._first_seen
        return True

    @property
    def is_ready(self) -> bool:
        return self.ready_at is not None


class Authority(Enum):
    """Who decided the position the server currently holds."""

    UNKNOWN = "unknown"
    """No claim seen yet."""

    CLIENT = "client"
    """The server adopted a validated client claim. This is the design: the client is
    authoritative over its own locomotion and the server validates plausibility."""

    HELD = "held"
    """The client's claim was implausible, so the server kept its previous position and
    counted the violation. This is the only moment the server overrides the client."""


@dataclass(frozen=True)
class SimulationResult:
    """What one consumed claim did to the server's authoritative position."""

    authority: Authority
    position: tuple[float, float]
    moved: float
    """Distance the server's own position changed on this sample."""

    rejected: bool
    reason: str
    violations: int
    """How many implausible claims this session, so a run can see escalation."""


class MovementSimulator:
    """The SERVER'S OWN player position, derived from what the client reports.

    WHY THIS EXISTS. Until now the server had no position of its own: it replayed a captured
    constant. `alc.read_claim` gives it a reported value and `DesyncTracker` compares the two,
    but nothing held an authoritative value of its own. This class is that value.

    READ THIS BEFORE TRUSTING IT (measured 2026-10-18, and it is a correction). The value the
    channel-1 body carries is **NOT a live position feed**. It is a spawn/reference anchor that
    changes only on teleport or respawn. Measured with the client's own accessor polled at 20 Hz
    while the player walked 23 u: the accessor moved, the channel-1 value did **not** (0 changes
    across 1050 samples in that minute; 2 distinct values and 1 change - a 243 u respawn jump -
    across the whole hour). See
    `the_channel_one_position_is_a_spawn_anchor_not_a_live_feed_20261018`.

    So this simulator is fed by an anchor. It will therefore report `moved: 0.0` and
    `Authority.CLIENT` with an unchanged position for a player who is walking, and it only sees a
    change when the anchor itself jumps - at which point the validator correctly rejects it as a
    teleport. That is not a bug in this class: it is the honest consequence of the input being what
    it is, and the class is kept because (a) it correctly holds a position the server owns, (b) it
    correctly refuses implausible jumps, and (c) it is the right shape to be fed by a real position
    feed once one is found.

    THE DESIGN IT IMPLEMENTS, taken from the client's own cvars rather than guessed:

        javelin.alc-correct-position-desync-during-attack-slow-down
        javelin.alc-correct-lateral-desyncs-during-attack-slow-down
        javelin-server.alc-speed-hack-fix-v2-enabled / -wipe-inputs / -max-buffered-inputs
        javelin-server.player-teleport-2d-distance-metrics-threshold
        javelin.alc-validate-sector-bounds

    Those names say where the authority sits: the CLIENT owns its own locomotion and corrects its
    own desync, while the SERVER validates plausibility and reacts to violations. So the server's
    job is not to impose a position every tick - that is what a naive authoritative server would
    do, and it is what produced the rubber-banding the earlier attempts were chasing. Its job is
    to hold a live, validated position and refuse the implausible.

    `Authority` records which of the two decided the current value on every sample, so a run can
    show whether the server ever had to override the client.

    This is deliberately separate from `DesyncTracker`. The tracker answers "do the two disagree?";
    this answers "what does the server hold, and why". A server can hold a validated position that
    still differs from its own prediction - that is a desync, not an authority failure.
    """

    def __init__(
        self,
        *,
        start: tuple[float, float] | None = None,
        validator: MovementValidator | None = None,
    ) -> None:
        self.position: tuple[float, float] | None = start
        self.validator = validator or MovementValidator()
        # A seeded start is the SERVER's decision (it is where the server put the player), so the
        # authority is HELD from the beginning rather than UNKNOWN.
        self.authority = Authority.HELD if start is not None else Authority.UNKNOWN
        self.violations = 0
        self.samples = 0
        self.adopted = 0
        self.held = 0
        self._last_claim: tuple[float, float] | None = None

    def seed(self, position: tuple[float, float]) -> None:
        """Adopt a starting position without counting it as a client decision.

        Used at spawn, where the server itself decides where the player appears - which is the
        one moment the server genuinely owns the position (measured 2026-10-14, 0.0000 u).
        """
        self.position = position
        self.authority = Authority.HELD
        self.validator.reset()

    def consume(self, claim: tuple[float, float], now: float) -> SimulationResult:
        """Fold one client claim into the server's position."""
        self.samples += 1
        if self.position is None:
            # No seeded start: the first claim defines it. Nothing to validate against yet.
            self.position = claim
            self.authority = Authority.CLIENT
            self.adopted += 1
            self._last_claim = claim
            self.validator.observe(claim[0], claim[1], now)
            return SimulationResult(
                Authority.CLIENT, claim, 0.0, False, "first claim defines the position", 0
            )

        before = self.position
        # THE STEP IS MEASURED AGAINST THE SERVER'S OWN POSITION, not against the client's previous
        # claim. This matters: `MovementValidator` resets its reference on a rejected teleport, so
        # measuring there would refuse a teleport ONCE and then accept the teleported position on
        # the next sample - a client that insisted would win after one refusal. Measuring against
        # the server's held position keeps refusing for as long as the claim stays far away.
        step = math.hypot(claim[0] - before[0], claim[1] - before[1])
        validation = self.validator.observe(claim[0], claim[1], now)
        too_far = step > self.validator.teleport_distance
        if validation.verdict is Verdict.REJECT or too_far:
            # The only override: hold the server's own position and count it.
            self.violations += 1
            self.held += 1
            self.authority = Authority.HELD
            reason = (
                f"teleport from the server's position: {step:.3f} u"
                if too_far else validation.reason
            )
            return SimulationResult(
                Authority.HELD,
                before,
                0.0,
                True,
                reason,
                self.violations,
            )

        # Plausible: the client is authoritative over its own locomotion, so the server adopts
        # the claim. This is not "trusting the client blindly" - it is the validated result.
        self.position = claim
        self.authority = Authority.CLIENT
        self.adopted += 1
        moved = math.hypot(claim[0] - before[0], claim[1] - before[1])
        self._last_claim = claim
        return SimulationResult(
            Authority.CLIENT, claim, moved, False, validation.reason, self.violations
        )

    @property
    def ready(self) -> bool:
        return self.position is not None

    def as_dict(self) -> dict:
        return {
            "position": (
                [round(self.position[0], 3), round(self.position[1], 3)]
                if self.position else None
            ),
            "authority": self.authority.value,
            "samples": self.samples,
            "adopted": self.adopted,
            "held": self.held,
            "violations": self.violations,
        }


@dataclass(frozen=True)
class PredictionCheck:
    """What the server's own prediction said about one movement sample."""

    predicted: tuple[float, float]
    actual: tuple[float, float]
    error: float
    agreed: bool
    reason: str


class PredictiveSimulator(MovementSimulator):
    """The server PREDICTS the next position from the client's movement state, then checks it.

    CAVEAT, measured 2026-10-18: the input this predicts from is a spawn anchor that does not move
    while the player walks, so the prediction error reported here measures arithmetic on a constant
    rather than a real prediction. The class is correct in shape and will produce meaningful numbers
    only once it is fed a live position. Do not quote its error as evidence of prediction quality.

    WHY THIS IS DIFFERENT FROM `MovementSimulator`. That class adopts a validated claim: the server
    ends up holding whatever the client said. This one derives its own expected position from the
    client's reported movement state and only then compares. When the two agree the server still
    adopts - the client remains authoritative over its locomotion, as the design says - but it now
    has an independent expectation, which is what lets it say "that step does not follow from what
    you reported" rather than only "that step was too fast".

    THE INPUTS, decoded from the client's own stream (`javelin.alc.MovementState`): the block at body
    offset 119 carries `a`, `b` and the world `x`,`y`. The `x`,`y` there match the position claim
    byte-exactly (201 of 201 samples), so they are the same quantity read twice and cannot be used
    as an independent check by themselves. What IS independent is the pair `(a, b)`, which varies
    with movement and whose meaning is NOT established - so this class does not invent one.

    What it does instead is honest and useful: it holds a *velocity* estimated from consecutive
    server-held positions, predicts the next position with it, and reports the prediction error.
    That is a real prediction the server makes on its own, and its error is a measurable quantity
    rather than a guess about `a` and `b`. When `a`/`b` are decoded later they can be substituted
    for the estimate without changing this interface.
    """

    def __init__(
        self,
        *,
        start: tuple[float, float] | None = None,
        validator: MovementValidator | None = None,
        prediction_tolerance: float = 2.0,
    ) -> None:
        super().__init__(start=start, validator=validator)
        self.prediction_tolerance = prediction_tolerance
        self._velocity: tuple[float, float] = (0.0, 0.0)
        self._last_time: float | None = None
        self.prediction_errors: list[float] = []
        self.disagreements = 0
        self.last_check: PredictionCheck | None = None

    def consume(self, claim: tuple[float, float], now: float) -> SimulationResult:
        """Fold a claim in, and record how far the server's own prediction was from it."""
        before = self.position
        before_time = self._last_time
        result = super().consume(claim, now)

        if before is not None and before_time is not None and result.authority is Authority.CLIENT:
            dt = now - before_time
            if dt > 0:
                predicted = (
                    before[0] + self._velocity[0] * dt,
                    before[1] + self._velocity[1] * dt,
                )
                error = math.hypot(result.position[0] - predicted[0],
                                   result.position[1] - predicted[1])
                agreed = error <= self.prediction_tolerance
                self.prediction_errors.append(error)
                if not agreed:
                    self.disagreements += 1
                self.last_check = PredictionCheck(
                    predicted=predicted,
                    actual=result.position,
                    error=error,
                    agreed=agreed,
                    reason=(
                        "prediction agreed" if agreed
                        else f"prediction off by {error:.3f} u"
                    ),
                )
                # Re-estimate the velocity from what actually happened, so the next prediction
                # starts from the server's own observation rather than from the client's word.
                self._velocity = (
                    (result.position[0] - before[0]) / dt,
                    (result.position[1] - before[1]) / dt,
                )
        self._last_time = now
        return result

    @property
    def mean_prediction_error(self) -> float | None:
        if not self.prediction_errors:
            return None
        return sum(self.prediction_errors) / len(self.prediction_errors)

    def as_dict(self) -> dict:
        d = super().as_dict()
        d.update(
            {
                "velocity": [round(self._velocity[0], 3), round(self._velocity[1], 3)],
                "predictions": len(self.prediction_errors),
                "disagreements": self.disagreements,
                "mean_prediction_error_u": (
                    round(self.mean_prediction_error, 4)
                    if self.mean_prediction_error is not None else None
                ),
            }
        )
        return d


class YawAwareSimulator(PredictiveSimulator):
    """The predictive simulator, told the client's camera yaw when it is available.

    WHY THE YAW MATTERS. `PredictiveSimulator` estimates velocity from a finite difference of
    consecutive positions, which is a lagging estimate: it can only describe the step that already
    happened. The client's input stream carries its camera yaw (`alc.MovementState.camera_yaw`,
    measured 2026-10-18: 1008 displacements classify as strafe/back/strafe/forward relative to it),
    which is a real input, available in the same sample as the position.

    With the yaw the server can express its prediction in the frame the player actually moves in:
    it decomposes the observed velocity into a forward component along the yaw and a lateral one
    across it. That is what makes a prediction *interpretable* - "the client is moving 5 u/s
    forward" - rather than a bare vector, and it is the frame in which a correction has to be
    expressed if the server is ever to send one.

    It does NOT yet predict from intent: that needs the movement intent (which keys are held), and
    the input stream has not been shown to carry it. What it does is record the velocity in the
    player's own frame, which is the precondition for that step.
    """

    def __init__(
        self,
        *,
        start: tuple[float, float] | None = None,
        validator: MovementValidator | None = None,
        prediction_tolerance: float = 2.0,
    ) -> None:
        super().__init__(
            start=start, validator=validator, prediction_tolerance=prediction_tolerance
        )
        self.last_yaw: float | None = None
        self.last_pitch: float | None = None
        self.forward_speed = 0.0
        self.lateral_speed = 0.0
        self.yaw_samples = 0

    def consume_with_yaw(
        self,
        claim: tuple[float, float],
        yaw: float | None,
        now: float,
        pitch: float | None = None,
    ) -> SimulationResult:
        """Consume a claim, and decompose the resulting velocity into the camera's frame.

        `pitch` is recorded but NOT used in the decomposition, and that is deliberate: the wire
        carries a 2D position (z is derived by the client), so movement happens in the plane and the
        pitch cannot contribute to it. Keeping it lets a caller see the full camera orientation
        without inventing a vertical component that the protocol does not have.
        """
        before = self.position
        result = super().consume(claim, now)
        if pitch is not None:
            self.last_pitch = pitch
        if yaw is not None and before is not None and result.authority is Authority.CLIENT:
            self.last_yaw = yaw
            self.yaw_samples += 1
            vx, vy = self._velocity
            # THE YAW IS MEASURED FROM +Y, NOT FROM +X. Measured 2026-10-18 over 79 displacements
            # during a real walk: `(movement heading - yaw)` is **+90.0 deg** in 77 of them (and
            # +90..+105 in the other 2) - a constant, not a spread. So the forward direction is
            # `(-sin(yaw), cos(yaw))`, which for the measured yaw of -154.04 deg gives
            # (0.438, -0.899), exactly the direction the player actually walked.
            #
            # Using `(cos, sin)` here - the obvious reading - reports a player walking forward as
            # walking sideways by 90 deg. It was measured doing exactly that before this fix.
            fx, fy = -math.sin(yaw), math.cos(yaw)
            self.forward_speed = vx * fx + vy * fy
            self.lateral_speed = -vx * fy + vy * fx
        return result

    def as_dict(self) -> dict:
        d = super().as_dict()
        d.update(
            {
                "camera_yaw": round(self.last_yaw, 4) if self.last_yaw is not None else None,
                "camera_yaw_degrees": (
                    round(math.degrees(self.last_yaw), 2)
                    if self.last_yaw is not None else None
                ),
                "forward_speed": round(self.forward_speed, 3),
                "lateral_speed": round(self.lateral_speed, 3),
                "camera_pitch": (
                    round(self.last_pitch, 4) if self.last_pitch is not None else None
                ),
                "camera_pitch_degrees": (
                    round(math.degrees(self.last_pitch), 2)
                    if self.last_pitch is not None else None
                ),
                "yaw_samples": self.yaw_samples,
            }
        )
        return d


class CorrectionAction(Enum):
    """What the server does about one divergence.

    THE DESIGN, from the client's own cvars rather than guessed: the CLIENT owns its locomotion and
    corrects its own desync (`javelin.alc-correct-position-desync-during-attack-slow-down`), while the
    SERVER validates and reacts (`javelin-server.alc-speed-hack-fix-v2-wipe-inputs`,
    `-max-buffered-inputs`, `player-teleport-2d-distance-metrics-threshold`). So a "correction" is the
    server refusing or limiting what it accepts - not pushing a position.

    WHAT LEVERS ACTUALLY EXIST IN THIS BUILD, in order of severity:

    ACCEPT      nothing to do; the claim was plausible and was adopted.

    HOLD        the server keeps its own position and does not adopt. The client and the server now
                disagree, and the server has recorded it.

    FREEZE      the server stops refreshing the client's local-player state. MEASURED 2026-10-13: with
                that stream off, the client's position is frozen and W does nothing - so this IS a
                real, working lever, and it is the strongest one short of disconnecting. It is crude
                (it stops the client's simulation rather than steering it) and it is why it is only
                used after HOLD has failed repeatedly.

    DISCONNECT  last resort, for a client that keeps claiming impossible movement.
    """

    ACCEPT = "accept"
    HOLD = "hold"
    FREEZE = "freeze"
    DISCONNECT = "disconnect"


@dataclass(frozen=True)
class CorrectionDecision:
    """The server's response to one movement sample, with the evidence behind it."""

    action: CorrectionAction
    reason: str
    violations: int
    error: float
    """Distance between what the client claimed and what the server holds."""


class CorrectionPolicy:
    """Turns a stream of validated claims into server decisions.

    WHY THIS IS A SEPARATE LAYER FROM THE SIMULATOR. The simulator answers "what position does the
    server hold, and why". This answers "given that, what does the server DO". Keeping them apart is
    what makes the escalation testable without a running game: the policy is a pure function of the
    observation stream.

    THE ESCALATION IS DELIBERATELY GRADUAL, and the thresholds come from the design rather than from
    tuning: a single rejected claim is normal (a lag spike, a dropped input) and is only held. The
    server escalates only when the client KEEPS claiming the impossible, because that is the
    signature of a client that is not going to converge - the same thing the vendor's
    `speed-hack-fix-v2` cvars are named after.
    """

    def __init__(
        self,
        *,
        freeze_after: int = 5,
        disconnect_after: int = 20,
        recover_after: int = 3,
    ) -> None:
        if freeze_after < 1:
            raise ValueError("freeze_after must be at least 1")
        if disconnect_after <= freeze_after:
            raise ValueError("disconnect_after must exceed freeze_after")
        if recover_after < 1:
            raise ValueError("recover_after must be at least 1")
        self.freeze_after = freeze_after
        self.disconnect_after = disconnect_after
        self.recover_after = recover_after
        self._clean_streak = 0
        self.frozen = False
        self.decisions: list[CorrectionDecision] = []

    def observe(
        self, result: SimulationResult, claim: tuple[float, float] | None = None
    ) -> CorrectionDecision:
        """Decide what to do about one sample.

        ``claim`` is the position the client reported. The divergence the server cares about is the
        distance between that claim and the position the server holds - which is non-zero exactly
        when the server refused to adopt the claim.
        """
        error = 0.0
        if claim is not None and result.position is not None:
            error = math.hypot(
                claim[0] - result.position[0], claim[1] - result.position[1]
            )
        if result.rejected:
            self._clean_streak = 0
            violations = result.violations
            if violations >= self.disconnect_after:
                decision = CorrectionDecision(
                    CorrectionAction.DISCONNECT,
                    f"{violations} implausible claims; the client is not converging",
                    violations,
                    error,
                )
            elif violations >= self.freeze_after:
                self.frozen = True
                decision = CorrectionDecision(
                    CorrectionAction.FREEZE,
                    f"{violations} implausible claims; freezing the player state stream",
                    violations,
                    error,
                )
            else:
                decision = CorrectionDecision(
                    CorrectionAction.HOLD, result.reason, violations, error
                )
        else:
            self._clean_streak += 1
            if self.frozen and self._clean_streak >= self.recover_after:
                # The client has been plausible for several samples: let it simulate again.
                self.frozen = False
                decision = CorrectionDecision(
                    CorrectionAction.ACCEPT,
                    f"recovered after {self._clean_streak} plausible claims; stream resumed",
                    result.violations,
                    error,
                )
            else:
                decision = CorrectionDecision(
                    CorrectionAction.ACCEPT, result.reason, result.violations, error
                )
        self.decisions.append(decision)
        return decision

    @property
    def stream_should_flow(self) -> bool:
        """Whether the player state stream may be sent right now."""
        return not self.frozen

    def as_dict(self) -> dict:
        counts: dict[str, int] = {}
        for d in self.decisions:
            counts[d.action.value] = counts.get(d.action.value, 0) + 1
        return {
            "frozen": self.frozen,
            "decisions": len(self.decisions),
            "by_action": counts,
            "clean_streak": self._clean_streak,
            "freeze_after": self.freeze_after,
            "disconnect_after": self.disconnect_after,
        }
