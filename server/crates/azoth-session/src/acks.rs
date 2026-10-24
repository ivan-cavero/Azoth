//! The sliding acknowledgement window for inbound envelope sequences.
//!
//! WHY IT MUST SLIDE
//! =================
//! MEASURED 2026-10-14 (`services/world/src/azoth_world/rep.py`, `ACK_WINDOW` and
//! `ack_window_first`). The `CT_ACKS` reply carries `ack_first` and `ack_last` as two **16-bit**
//! fields, and a wrap-aware reader can therefore only represent a range narrower than half the
//! sequence space (32,768). The Python prototype pinned `ack_first` to the session's first inbound
//! sequence, so the acknowledged range grew by one per datagram for as long as the session lasted.
//!
//! At 08:42:44 the session's last envelope sequence crossed 32,768 and the range became ambiguous.
//! The client did **not** report an error: it stopped treating its own reliable records as delivered
//! and began retransmitting all of them, roughly 200 times over ten minutes — 140,174 channel-0
//! records carrying only **660 distinct** sequences, against 1.2x earlier in the same session — with
//! `OnLocalNetworkConnectionWarning` climbing about once a second throughout. The server's outbound
//! rate, ACK range and reliable-sequence stream all stayed correct and constant, which is why this
//! was an addressing-window defect rather than a transport or load failure, and why it survived so
//! long: nothing anywhere logged a problem.
//!
//! So the window acknowledges the **most recent** [`crate::ACK_WINDOW_DEFAULT`] sequences. 16,384 is
//! half the largest unambiguous range and still covers ~13 minutes of history at the measured
//! ~21 inbound datagrams/s. A test drives 40,000 sequences and asserts the reported width stays at
//! the configured width.
//!
//! WHY A BITMAP AND NOT A RANGE
//! ============================
//! [`AckWindow::is_duplicate`] answers "was this exact sequence already observed?", and a single
//! low/high pair cannot: within the window a record may be missing, retransmitted, and then arrive
//! out of order. One bit per sequence costs 2 KB per session at the default width, which is cheap
//! against the cost of applying a duplicated reliable record twice. Slots are cleared as they leave
//! the window, because a stale bit would otherwise alias onto `sequence + 65,536` much later.
//!
//! Sequences older than the window cannot be named by a 16-bit range any more, so they are ignored
//! rather than acknowledged: claiming them would be a lie the client notices.

/// Half of the 16-bit sequence space. A range must fit strictly inside one of the two halves, or a
/// wrap-aware reader cannot tell "just ahead" from "far behind".
const SEQUENCE_SPACE_HALF: u16 = 32_768;

/// A sliding window over the inbound envelope sequence space.
#[derive(Debug, Clone)]
pub struct AckWindow {
    /// The widest range this window will ever report.
    width: u16,
    /// One bit per sequence in the window, indexed by `sequence % width`.
    bits: Vec<u64>,
    /// The highest sequence observed so far.
    last: u16,
    /// The lowest sequence the window can still name.
    first: u16,
    /// Observations recorded, saturating. The reported range is `min(observed, width)` wide, which
    /// mirrors the prototype's fixed `ack_window_first` so the two can be compared directly.
    observed: u32,
    /// Whether anything has been observed at all; `0` is a legal sequence.
    any: bool,
}

impl AckWindow {
    /// A window that will never report a range wider than `width` sequences.
    ///
    /// `width` is clamped to `1..=32,768`. Above 32,768 a 16-bit range stops being unambiguous —
    /// that is the defect documented in the module docs — so accepting a larger value would let one
    /// configuration mistake reintroduce it.
    #[must_use]
    pub fn new(width: u16) -> Self {
        let width = width.clamp(1, SEQUENCE_SPACE_HALF);
        Self {
            width,
            bits: vec![0; usize::from(width).div_ceil(64)],
            last: 0,
            first: 0,
            observed: 0,
            any: false,
        }
    }

    /// The configured window width.
    #[must_use]
    pub fn width(&self) -> u16 {
        self.width
    }

    /// Record an inbound sequence.
    ///
    /// A duplicate is harmless: it sets a bit that is already set and never moves the window. A
    /// sequence ahead of the window slides it forward, clearing the slots that leave; a sequence
    /// behind the window is ignored, because a 16-bit range can no longer name it.
    pub fn observe(&mut self, sequence: u16) {
        if !self.any {
            self.any = true;
            self.last = sequence;
            self.first = sequence;
            self.observed = 1;
            self.mark(sequence);
            return;
        }

        let ahead = sequence.wrapping_sub(self.last);
        if ahead == 0 {
            // Equal to the high-water mark: already accounted for.
            return;
        }
        if ahead >= SEQUENCE_SPACE_HALF {
            // Behind the window. Record it only if the window can still name it, so an obviously
            // stale duplicate does not widen the range.
            if self.in_window(sequence) {
                self.mark(sequence);
            }
            return;
        }

        // Ahead: slide forward and drop the slots that leave the window.
        let old_first = self.first;
        self.last = sequence;
        self.observed = self.observed.saturating_add(1);
        self.first = self.window_first();
        let leaving = self.first.wrapping_sub(old_first);
        if u32::from(leaving) > u32::from(self.width) {
            // The window moved further than its own width, so no old sequence survives.
            self.bits.fill(0);
        } else {
            for offset in 0..leaving {
                self.clear(old_first.wrapping_add(offset));
            }
        }
        self.mark(sequence);
    }

    /// The range to acknowledge: `(first, last)`, both wrap-relative.
    ///
    /// `(0, 0)` means nothing has been observed yet, so there is nothing to acknowledge. The width
    /// is `last - first + 1` in wrapping arithmetic and never exceeds [`Self::width`].
    #[must_use]
    pub fn range(&self) -> (u16, u16) {
        if !self.any {
            return (0, 0);
        }
        (self.first, self.last)
    }

    /// Whether `sequence` was already observed within the window; records it when it was not.
    ///
    /// This is the call the datagram path makes: one question — "have I already applied this?" —
    /// and it keeps the window current either way. A duplicate does not advance the window.
    pub fn is_duplicate(&mut self, sequence: u16) -> bool {
        if self.any && self.in_window(sequence) && self.marked(sequence) {
            return true;
        }
        self.observe(sequence);
        false
    }

    /// How many sequences the current range spans.
    fn span(&self) -> u16 {
        if !self.any {
            return 0;
        }
        // Bounded by `width`, which is at most 32,768, so the cast cannot truncate.
        self.observed.min(u32::from(self.width)) as u16
    }

    /// The first sequence the current range names.
    fn window_first(&self) -> u16 {
        let span = self.span();
        if span == 0 {
            self.last
        } else {
            self.last.wrapping_sub(span - 1)
        }
    }

    /// Whether the current range can still name `sequence`.
    fn in_window(&self, sequence: u16) -> bool {
        self.any && self.last.wrapping_sub(sequence) < self.span()
    }

    /// The bit slot for `sequence`.
    fn slot(&self, sequence: u16) -> (usize, u64) {
        let index = usize::from(sequence % self.width);
        (index / 64, 1u64 << (index % 64))
    }

    fn mark(&mut self, sequence: u16) {
        let (word, mask) = self.slot(sequence);
        self.bits[word] |= mask;
    }

    fn clear(&mut self, sequence: u16) {
        let (word, mask) = self.slot(sequence);
        self.bits[word] &= !mask;
    }

    fn marked(&self, sequence: u16) -> bool {
        let (word, mask) = self.slot(sequence);
        self.bits[word] & mask != 0
    }
}

impl Default for AckWindow {
    fn default() -> Self {
        Self::new(crate::ACK_WINDOW_DEFAULT)
    }
}
