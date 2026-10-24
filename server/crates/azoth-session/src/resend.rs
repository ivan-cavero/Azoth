//! The retransmission table: which reliable records are still owed, and when they may be re-sent.
//!
//! WHY THE INTERVAL AND THE CAP ARE NOT NEGOTIABLE
//! ==============================================
//! Both numbers are measured, and both were measured the same way: a change that looked reasonable
//! made the client's connection condition worse.
//!
//! * **0.3 s between retransmissions of the same record** (`rep.py`, `RESEND_INTERVAL_S`). Lower
//!   values were measured to produce an in-flight resend storm that peaks while the paced replay
//!   drains — 650 resends in one second — and lines up with a burst of
//!   `OnLocalNetworkConnectionWarning`.
//! * **6 tries, then drop** (`rep.py`, `REPLAY_RESEND_LIMIT`). MEASURED 2026-09-20: a 12.7 KB
//!   `StateBundle` was resent **4,229 times** and never acknowledged; the client drops oversized
//!   datagrams during load, so re-bombing it drained the link and made load slower, not faster. The
//!   cap turns an unbounded storm into "split it differently, or let the session deadline end it".
//!
//! A SKIPPED RESEND MUST NOT COST A TRY
//! ====================================
//! `rep.py` states it in one line: "A skipped resend must not consume a try, or the 6-try cap
//! expires a datagram the client was never offered again." A sequence that is skipped because it is
//! not due yet, or because a per-call burst cap was reached, was never transmitted — so it cannot be
//! charged against the cap that limits transmissions. In this table only [`ResendTable::mark_sent`]
//! moves `tries`, and it is called only for a sequence that is actually going out.
//!
//! WHAT THIS TYPE DOES NOT OWN
//! ===========================
//! Transmission. It returns sequences; the caller writes the bytes. It also does not own the
//! per-advance burst cap (`rep.py`'s `POST_REPLAY_RESEND_MAX`), which is a caller policy: a replay
//! burst genuinely needs a wider cap than steady-state play does.

use std::collections::BTreeMap;
use std::time::{Duration, Instant};

/// One reliable record awaiting acknowledgement.
#[derive(Debug, Clone)]
struct Entry {
    /// The datagram as it goes on the wire. Kept so a retransmission is byte-identical to the
    /// original: the client matches records by sequence, and a body that changed would be applied
    /// twice.
    bytes: Vec<u8>,
    /// When it was last transmitted.
    last_sent: Instant,
    /// Resends charged so far. A fresh record starts at 0 because the first transmission is not a
    /// resend.
    tries: u8,
}

/// Reliable records awaiting acknowledgement, ordered by sequence.
///
/// A `BTreeMap` because [`ResendTable::due`] must be deterministic: a retransmission order that
/// changed between runs would make a resend-related defect impossible to reproduce.
#[derive(Debug, Clone)]
pub struct ResendTable {
    interval: Duration,
    max_tries: u8,
    entries: BTreeMap<u16, Entry>,
}

impl ResendTable {
    /// A table with the given interval and resend budget.
    #[must_use]
    pub const fn new(interval: Duration, max_tries: u8) -> Self {
        Self {
            interval,
            max_tries,
            entries: BTreeMap::new(),
        }
    }

    /// Add a record that was just transmitted for the first time at `now`.
    ///
    /// Replaces any record with the same sequence; callers that must not replace use
    /// [`Self::contains`] first, which is what [`crate::Session::send_reliable`] does.
    pub fn queue(&mut self, sequence: u16, bytes: Vec<u8>, now: Instant) {
        self.entries.insert(
            sequence,
            Entry {
                bytes,
                last_sent: now,
                tries: 0,
            },
        );
    }

    /// Whether a record with this sequence is still unacknowledged.
    #[must_use]
    pub fn contains(&self, sequence: u16) -> bool {
        self.entries.contains_key(&sequence)
    }

    /// The datagram queued for `sequence`, so the caller can transmit it.
    #[must_use]
    pub fn payload(&self, sequence: u16) -> Option<&[u8]> {
        self.entries.get(&sequence).map(|entry| entry.bytes.as_slice())
    }

    /// Resends charged against `sequence` so far.
    ///
    /// Exists so a test can prove that a skipped sequence did not spend a try.
    #[must_use]
    pub fn tries(&self, sequence: u16) -> Option<u8> {
        self.entries.get(&sequence).map(|entry| entry.tries)
    }

    /// Sequences due for retransmission at `now`, in ascending order.
    ///
    /// "Due" is exactly "the interval has elapsed since the last transmission". It consults nothing
    /// else and costs nothing: the try budget is spent by [`Self::mark_sent`], so calling this
    /// repeatedly, or early, has no side effect.
    #[must_use]
    pub fn due(&self, now: Instant) -> Vec<u16> {
        self.entries
            .iter()
            .filter(|(_, entry)| now.saturating_duration_since(entry.last_sent) >= self.interval)
            .map(|(sequence, _)| *sequence)
            .collect()
    }

    /// Charge a resend to `sequence`, returning whether the record may be transmitted now.
    ///
    /// `true` charges a try and allows the send; `false` means the record must be dropped, and it is
    /// removed here rather than left for the caller to forget — a record that is never acknowledged
    /// would elsewise be retried for the life of the session, which is the 4,229-resend defect in
    /// the module docs. With the default budget that is six resends and then a seventh attempt that
    /// refuses and drops, which is exactly the prototype's `tries >= REPLAY_RESEND_LIMIT` check.
    ///
    /// Only a send reaches this method, so a sequence that was skipped — not due yet, or cut by a
    /// caller-side burst cap — never spends a try.
    pub fn mark_sent(&mut self, sequence: u16, now: Instant) -> bool {
        let Some(entry) = self.entries.get_mut(&sequence) else {
            return false;
        };
        if entry.tries >= self.max_tries {
            self.entries.remove(&sequence);
            return false;
        }
        entry.tries += 1;
        entry.last_sent = now;
        true
    }

    /// The client acknowledged this sequence; stop owing it.
    pub fn acknowledge(&mut self, sequence: u16) {
        self.entries.remove(&sequence);
    }

    /// How many records are still unacknowledged.
    #[must_use]
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Whether nothing is owed.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

impl Default for ResendTable {
    fn default() -> Self {
        Self::new(crate::RESEND_INTERVAL_DEFAULT, crate::MAX_RESEND_TRIES_DEFAULT)
    }
}
