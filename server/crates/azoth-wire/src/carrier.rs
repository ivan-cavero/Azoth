//! The Carrier connection layer: the `CT_ACKS` record every datagram carries, and the retired flight.
//!
//! WHY THE ACK IS THE CONNECTION LAYER NOW
//! ======================================
//! MEASURED against the official server (live capture, one REP flow): it sends 61.8 datagrams/s at a
//! 16.1 ms median inter-packet gap while the client sends 20.5/s at 48.1 ms, and a census of 465 MB
//! of the Python prototype's own traffic (`services/world/rep_traffic.jsonl`, 1,338,802 lines) counts
//! 313,578 `CT_ACKS` (sys 6) against **zero** `CLOCK_SYNC` (sys 4) and **zero** `CONNECT_ACK`
//! (sys 2). The ACK is not an event that gets answered: it rides on every datagram the world emits,
//! and [`acks_payload`] is the one encoder for it.
//!
//! WHY AN ACK AT ALL: measured against `worldd` before it acknowledged anything, the client sent its
//! keep-alives (~51-byte records, 189 of them), **never** its V3 registration, and reported
//! `@mm_csdkerr_connection_failed (0)` plus `Errors::unknown` 20 s later. The missing step was the
//! third record below (`rep.py::carrier_state_datagram`: *"the fix that broke the V3 retry storm in
//! first-light PR #5"*).
//!
//! THE SYS ID IS THE LAST PAYLOAD BYTE OF EVERY CHANNEL-3 RECORD
//! ============================================================
//! Not the first: a channel-3 payload is *data then id*, which is why [`MessageRecord::system_msg_id`]
//! reads the last byte and every payload here pushes its id last.
//!
//! THE ACK RANGE NAMES EVERY DATAGRAM RECEIVED, AND STOPS GROWING
//! ============================================================
//! `ack_first` is not the echoed sequence: a degenerate range (`ack_first == ack_last`, only the
//! datagram that carried the request) is **not** an acknowledgement the client accepts. MEASURED
//! 2026-09-18 (`Game.log` 20:15:08→18; `rep.py::ct_acks_datagram`): after the first
//! `RegistrationResponse` the client retransmits its 1115-byte channel-0 record for ~10 s, then
//! reports `@mm_csdkerr_disconnect (4)`. The opposite mistake is worse: a range half the 16-bit space
//! cannot be disambiguated by a wrap-aware reader, and the client answers by retransmitting everything
//! (2026-10-14, `rep.py::ACK_WINDOW`: 32,768 crossed at 08:42:44, then 140,174 records carrying 660
//! distinct sequences), so [`ack_window_first`] slides a range of at most `window`.
//!
//! THE RETIRED ACCEPTANCE FLIGHT
//! =============================
//! [`AcceptanceFlight`] is the prototype's three-record shape (`rep.py::carrier_state_datagram`), one
//! datagram on channel 3 in this order:
//! ```text
//! record       sys  reliable  flags  seq  relSeq   payload
//! CLOCK_SYNC    4   no        0x20   0    0xFFFF   u32 BE server clock ms, then the byte 4
//! CONNECT_ACK   2   YES       0x21   1    0        the welcome bytes, then the byte 2
//! CT_ACKS       6   no        0x18   —    —        0x40, u16 BE ack_last, u16 BE ack_first, then 6
//! ```
//! `0x20` is `MF_DATA_CHANNEL` alone, `0x21` adds `MF_RELIABLE`, and `0x18` is
//! `MF_SEQUENTIAL_ID | MF_SEQUENTIAL_REL_ID`: CT_ACKS inherits both sequences from CONNECT_ACK.
//!
//! NOTHING SENDS IT ANY MORE, AND THAT IS MEASURED: the census above counts zero CLOCK_SYNC and zero
//! CONNECT_ACK, so `worldd` builds neither — the ACK rides on every datagram instead (`worldd`'s
//! `egress`) and the flight's only caller is its own tests. It stays because its two useful pieces are
//! still in use ([`acks_payload`], shared with the clock's keepalive, and [`ack_window_first`]) and
//! because deleting an encoder that reproduces captured bytes would delete the only statement of what
//! those bytes were. Read it as unused-if-referenced.
//!
//! WHAT THE FLIGHT HAD TO GET RIGHT, AND STILL STATES
//! =================================================
//! 1. **The envelope sequence echoes the client's inbound sequence.** Not a server counter: without
//!    the echo the client keeps retransmitting as if our reply never arrived (first-light "Mixed
//!    Nuts", 2026-05-04), which is why [`AcceptanceFlight::datagram`] takes it as a parameter.
//! 2. **A reliable record with a mirrored relSeq blocks the client's reliable queue forever** (live
//!    capture 2026-09-16 20:23). So CLOCK_SYNC is **unreliable** with relSeq `0xFFFF` — the value an
//!    unreliable record carries before anything reliable arrives — and CONNECT_ACK is **reliable**
//!    with relSeq `0`.
//! 3. **The CONNECT_ACK payload is the client's version echoed verbatim**, then the sys id byte
//!    (`DefaultHandshake`: `OnInitiate` writes the version into the ACK buffer and `OnReceiveRequest`
//!    echoes it). A datagram-ACK-shaped payload (`40 0002 0002`) was tried on 2026-09-17 and did
//!    **not** advance the client. [`connect_welcome`] is that rule.
//! 4. **Its bytes are written by hand.** [`crate::marshal`] derives flag bytes from each record's
//!    fields plus the datagram's cross-record state, and here that derivation differs from the
//!    measured bytes twice: it omits CONNECT_ACK's sequence (`0x09` where the client was sent
//!    `0x21`) and never emits `MF_SEQUENTIAL_REL_ID` for an unreliable record (so CT_ACKS would lose
//!    its `0x10` and write a relSeq instead). The flight is a captured byte pattern.
//!
//! WHAT A RECORD PAYLOAD CARRIES: the rest of this module is pure framing — [`Reassembly`] joins the
//! chunks a message is cut into, and [`registration_body`] finds the V3 registration in any of the
//! three framings that can carry it.

use crate::envelope::Envelope;
use crate::error::WireError;
use crate::record::{MessageRecord, flags};
use crate::{CHANNEL_SYSTEM, container, v3, varint};

/// `SM_CONNECT_REQUEST`: the client's first channel-3 record. Its ACK rides on the next datagram, and
/// the retired flight was the only thing that ever answered it.
pub const SYS_CONNECT_REQUEST: u8 = 1;

/// `SM_CLOCK_SYNC`: the first record of the retired flight, and zero occurrences in the prototype's
/// own traffic census (`services/world/rep_traffic.jsonl`, 1,338,802 lines).
pub const SYS_CLOCK_SYNC: u8 = 4;

/// `SM_CONNECT_ACK`: the acceptance itself, the flight's only reliable record, and zero occurrences in
/// the same census.
pub const SYS_CONNECT_ACK: u8 = 2;

/// `SM_CT_ACKS`: the acknowledgement of the client's inbound envelope-sequence range.
pub const SYS_CT_ACKS: u8 = 6;

/// `AHF_CONTINUOUS_ACK`: the ACK-flags byte `CT_ACKS` carries ahead of its two sequences.
pub const ACK_CONTINUOUS: u8 = 0x40;

/// CLOCK_SYNC's flag byte: `MF_DATA_CHANNEL` alone — unreliable, and not the connecting form.
const CLOCK_SYNC_FLAGS: u8 = 0x20;

/// CONNECT_ACK's flag byte: `MF_RELIABLE | MF_DATA_CHANNEL`.
const CONNECT_ACK_FLAGS: u8 = 0x21;

/// CT_ACKS's flag byte: `MF_SEQUENTIAL_ID | MF_SEQUENTIAL_REL_ID` — both sequence fields inherited.
const CT_ACKS_FLAGS: u8 = 0x18;

/// The reliable sequence an unreliable record carries before any reliable record has been received.
const NO_RELIABLE_YET: u16 = 0xFFFF;

/// The welcome a `SM_CONNECT_REQUEST` too short to carry a version is answered with.
const DEFAULT_WELCOME: [u8; 4] = [0x00, 0x00, 0x00, 0x05];

/// The version a `SM_CONNECT_REQUEST` payload carries, which `CONNECT_ACK` echoes verbatim.
///
/// The payload is *data then id*, so the version is the bytes before the trailing sys-id byte, cut to
/// the `u32` the client wrote; under five bytes there is none, and `00 00 00 05` is the prototype's
/// own fallback (`rep.py::handle_app_data`).#[must_use]
pub fn connect_welcome(payload: &[u8]) -> Vec<u8> {
    if payload.len() < 5 {
        return DEFAULT_WELCOME.to_vec();
    }
    payload[..payload.len() - 1].iter().copied().take(4).collect()
}

/// The first envelope sequence of the continuous ACK range.
///
/// Sliding, not pinned: while the session is younger than `window` this is the session's first
/// sequence (the strongest true claim), and after that it advances so the range never exceeds
/// `window`. The subtraction is in 16-bit wrap space, so it survives the 65,536 wrap. The width is
/// `max(1, min(datagrams_seen, window))`: a session that has counted nothing still names its own
/// datagram. `window` is `azoth_session::ACK_WINDOW_DEFAULT` (16,384 — half the largest unambiguous
/// range, ~13 minutes at the measured ~21 datagrams/s).
#[must_use]
pub fn ack_window_first(ack_last: u16, datagrams_seen: u32, window: u16) -> u16 {
    let width = u32::from(window).min(datagrams_seen).max(1);
    ack_last.wrapping_sub((width - 1) as u16)
}

/// The `CT_ACKS` payload: the ACK flags byte, `ack_last`, `ack_first`, then the sys id.
///
/// `ack_last` before `ack_first`: the range is written high-then-low, and swapping them makes the
/// client acknowledge a range it can never reach. This is the one encoder for the ACK, shared by the
/// retired flight and the clock's keepalive, so neither can drift from `rep.py::ct_acks_datagram`.
#[must_use]
pub fn acks_payload(ack_first: u16, ack_last: u16) -> Vec<u8> {
    let mut acks = Vec::with_capacity(6);
    acks.push(ACK_CONTINUOUS);
    acks.extend_from_slice(&ack_last.to_be_bytes());
    acks.extend_from_slice(&ack_first.to_be_bytes());
    acks.push(SYS_CT_ACKS);
    acks
}

/// The flight's trigger inside one client datagram: `(inbound envelope sequence, request payload)`.
///
/// The payload is the channel-3 `SM_CONNECT_REQUEST` record's own bytes — *data then id* — which is
/// what [`connect_welcome`] trims and what the server's diagnostics dump whole. `None` when the
/// datagram is not a Carrier envelope, does not parse as records, or carries no channel-3
/// `SM_CONNECT_REQUEST` — an empty payload has no sys id, the prototype's own `and rec.payload`.
#[must_use]
pub fn connect_request(bytes: &[u8]) -> Option<(u16, Vec<u8>)> {
    let (envelope, body) = crate::envelope::parse(bytes).ok()?;
    let parsed = crate::record::parse(body).ok()?;
    let request = parsed.records.iter().find(|message| {
        message.is_system() && message.system_msg_id() == Some(SYS_CONNECT_REQUEST)
    })?;
    Some((envelope.sequence, request.payload.clone()))
}

/// The Carrier connection-acceptance flight: the three-record shape that once ended CONNECTING.
///
/// UNREFERENCED BY `worldd`: the census in the module docs counts zero CLOCK_SYNC and zero CONNECT_ACK
/// in 1,338,802 lines of real traffic. Kept as the statement of what those captured bytes were, and as
/// the home of [`acks_payload`] and [`ack_window_first`], which the live path does use.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AcceptanceFlight {
    /// The server clock in milliseconds, as `CLOCK_SYNC` carries it.
    pub clock_ms: u32,
    /// The client's version, echoed verbatim (DefaultHandshake semantics).
    pub welcome: Vec<u8>,
    /// The first inbound envelope sequence the ACK range names.
    pub ack_first: u16,
    /// The last inbound envelope sequence the ACK range names.
    pub ack_last: u16,
}

impl AcceptanceFlight {
    /// The flight answering one inbound datagram, from its payload and the peer's inbound counters.
    ///
    /// `ack_first` comes from [`ack_window_first`] and `ack_last` / `datagrams_seen` are the peer's own
    /// counters, so no caller can pin the range. [`Self::datagram`] takes the echoed sequence, which
    /// the flight does not own.
    #[must_use]
    pub fn answering(
        clock_ms: u32,
        payload: &[u8],
        ack_last: u16,
        datagrams_seen: u32,
        window: u16,
    ) -> Self {
        Self {
            clock_ms,
            welcome: connect_welcome(payload),
            ack_first: ack_window_first(ack_last, datagrams_seen, window),
            ack_last,
        }
    }

    /// Build the flight as one datagram.
    ///
    /// `envelope_sequence` MUST be the client's inbound envelope sequence, echoed — not a server
    /// counter (module docs).
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] if a payload does not fit the `u16` size field, which needs a
    /// welcome above 65,522 bytes.
    pub fn datagram(&self, envelope_sequence: u16) -> Result<Vec<u8>, WireError> {
        let mut clock = Vec::with_capacity(5);
        clock.extend_from_slice(&self.clock_ms.to_be_bytes());
        clock.push(SYS_CLOCK_SYNC);

        let mut ack = Vec::with_capacity(self.welcome.len() + 1);
        ack.extend_from_slice(&self.welcome);
        ack.push(SYS_CONNECT_ACK);

        let acks = acks_payload(self.ack_first, self.ack_last);

        let mut out = Envelope::new(envelope_sequence, false).encode().to_vec();
        push_record(&mut out, CLOCK_SYNC_FLAGS, (0, NO_RELIABLE_YET), &clock)?;
        push_record(&mut out, CONNECT_ACK_FLAGS, (1, 0), &ack)?;
        push_record(&mut out, CT_ACKS_FLAGS, (0, 0), &acks)?;
        Ok(out)
    }
}

/// Append one channel-3 record with an explicit flag byte, mirroring [`crate::record::parse`].
///
/// Each field is written exactly when its flag says the reader must read it, so a clear
/// `MF_SEQUENTIAL_ID` / `MF_SEQUENTIAL_REL_ID` writes that sequence and `MF_DATA_CHANNEL` writes the
/// channel byte. The first version wrote the channel unconditionally, and CT_ACKS's `0x18` omits it,
/// so the reader lost the stream.
fn push_record(
    out: &mut Vec<u8>,
    flag_byte: u8,
    sequences: (u16, u16),
    payload: &[u8],
) -> Result<(), WireError> {
    let size = u16::try_from(payload.len()).map_err(|_| WireError::OutOfRange {
        field: "record size",
        value: payload.len() as u64,
        limit: u64::from(u16::MAX) + 1,
    })?;
    out.push(flag_byte);
    out.extend_from_slice(&size.to_be_bytes());
    if flag_byte & flags::DATA_CHANNEL != 0 {
        out.push(CHANNEL_SYSTEM);
    }
    if flag_byte & flags::SEQUENTIAL_ID == 0 {
        out.extend_from_slice(&sequences.0.to_be_bytes());
    }
    if flag_byte & flags::SEQUENTIAL_REL_ID == 0 {
        out.extend_from_slice(&sequences.1.to_be_bytes());
    }
    out.extend_from_slice(payload);
    Ok(())
}

/// Inbound chunk reassembly for one message stream.
///
/// The client chunks its own registration (`numChunks 3` measured), so a body exists only once its
/// last chunk arrives; every chunk carries the **total**, which recognises a complete message without
/// a timer, and out-of-order delivery loses the message rather than corrupting it.
#[derive(Debug, Default)]
pub struct Reassembly {
    expected: u16,
    next: u16,
    parts: Vec<Vec<u8>>,
}

impl Reassembly {
    /// Append one record's payload, returning the body once it is complete.
    #[must_use]
    pub fn push(&mut self, message: &MessageRecord) -> Option<Vec<u8>> {
        if message.num_chunks <= 1 {
            return Some(message.payload.clone());
        }
        // A chunk continues the message in progress only when it is the next one; anything else starts
        // over, which drops a duplicate instead of concatenating it twice.
        if self.expected != message.num_chunks || message.sequence != self.next {
            self.expected = message.num_chunks;
            self.parts.clear();
            self.next = message.sequence;
        }
        self.parts.push(message.payload.clone());
        self.next = self.next.wrapping_add(1);
        if self.parts.len() < usize::from(self.expected) {
            return None;
        }
        Some(self.parts.drain(..).flatten().collect())
    }
}

/// The V3 body inside a record payload, in any of the three framings that could carry it.
#[must_use]
pub fn registration_body(payload: &[u8]) -> Option<v3::RegistrationRequest> {
    // The measured form: the body verbatim (see `worldd::entry`'s module docs).
    if let Ok(request) = v3::parse(payload) {
        return Some(request);
    }
    // The client's self-validating container, documented for non-chunked channel-0 records; its CRC
    // is what makes this a check rather than a guess.
    if let Ok(inner) = container::parse_client(payload)
        && let Ok(request) = v3::parse(inner.body)
    {
        return Some(request);
    }
    // The server's own framing: a VLQ32 length, then the body.
    let (declared, after) = varint::decode(payload, 0).ok()?;
    if usize::try_from(declared).ok()? != payload.len() - after {
        return None;
    }
    v3::parse(&payload[after..]).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A chunk of a message cut into `total` pieces.
    fn chunk(sequence: u16, total: u16, payload: &[u8]) -> MessageRecord {
        MessageRecord {
            num_chunks: total,
            ..MessageRecord::data(0, sequence, sequence, payload.to_vec())
        }
    }

    /// The moved reassembler, pinned where it now lives: a body exists only once the last chunk arrives.
    #[test]
    fn a_chunked_message_exists_only_once_its_last_chunk_arrives() {
        let mut reassembly = Reassembly::default();
        assert_eq!(reassembly.push(&chunk(0, 3, b"ab")), None);
        assert_eq!(reassembly.push(&chunk(1, 3, b"cd")), None);
        assert_eq!(reassembly.push(&chunk(2, 3, b"ef")), Some(b"abcdef".to_vec()));
    }

    /// A repeated chunk restarts the message instead of doubling it, which loses the message rather
    /// than corrupting it.
    #[test]
    fn a_repeated_chunk_restarts_instead_of_doubling_the_message() {
        let mut reassembly = Reassembly::default();
        assert_eq!(reassembly.push(&chunk(0, 2, b"ab")), None);
        assert_eq!(reassembly.push(&chunk(0, 2, b"ab")), None);
        assert_eq!(reassembly.push(&chunk(1, 2, b"cd")), Some(b"abcd".to_vec()));
    }

    /// The welcome is the request's data, sys id stripped and truncated to four bytes; a payload too
    /// short to carry one falls back to `00 00 00 05`.
    #[test]
    fn the_welcome_is_the_requests_data_without_its_sys_id() {
        let welcome = |payload: &[u8]| connect_welcome(payload);
        assert_eq!(welcome(&[0xAA, 0xBB, 0xCC, 0xDD, SYS_CONNECT_REQUEST]), vec![0xAA, 0xBB, 0xCC, 0xDD]);
        // Longer than the version field: the extra data is truncated, never echoed.
        let long = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, SYS_CONNECT_REQUEST];
        assert_eq!(welcome(&long), vec![0xAA, 0xBB, 0xCC, 0xDD]);
        // Shorter than the version field plus its id: nothing to echo.
        assert_eq!(welcome(&[0xAA, SYS_CONNECT_REQUEST]), vec![0x00, 0x00, 0x00, 0x05]);
    }

    /// The measured window rule: one datagram acknowledges itself, N acknowledge all N, a low
    /// `ack_last` borrows through the wrap, a count past the window clamps, and `0` behaves as `1`.
    #[test]
    fn the_range_covers_everything_received_and_never_exceeds_the_window() {
        for (ack_last, seen, window, expected) in [
            (7, 1, 16_384, 7),
            (7, 5, 16_384, 3),
            (0x1234, 5, 16_384, 0x1230),
            (2, 5, 16_384, 0xFFFE),
            (0, 2, 16_384, 0xFFFF),
            (0x8000, 40_000, 16_384, 0x4001),
            (100, 40_000, 1, 100),
            (9, 0, 16_384, 9),
        ] {
            assert_eq!(
                ack_window_first(ack_last, seen, window),
                expected,
                "ack_last {ack_last:#06x}, {seen} seen, window {window}"
            );
        }
    }

    /// An unchunked record is its own body, which is every record that is not a V3 registration.
    #[test]
    fn an_unchunked_record_is_its_own_body() {
        let mut reassembly = Reassembly::default();
        let record = MessageRecord::data(0, 5, 5, vec![0xAA]);
        assert_eq!(reassembly.push(&record), Some(vec![0xAA]));
    }
}
