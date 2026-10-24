//! The Carrier connection layer: the acceptance flight that ends CONNECTING, plus the two things a
//! record payload carries before the game starts.
//!
//! WHY THE SERVER MUST SPEAK FIRST
//! ===============================
//! A client completes its DTLS handshake and then waits. Measured against `worldd`: it sends its
//! keep-alives (~51-byte application records, 189 of them) and **never** sends its V3 registration,
//! then reports `@mm_csdkerr_connection_failed (0)` and
//! `JavelinGame::OnConnectionFail: Reason: Errors::unknown` twenty seconds later. The missing step
//! is GridMate's `CarrierImpl::ProcessSystemMessages` → `CST_CONNECTED`, which sends `SendSyncTime()`
//! and `SendSystemMessage(SM_CONNECT_ACK, …, SEND_RELIABLE)` and acknowledges the client's datagrams.
//! Without the third record below the client's Carrier never considers its own datagrams delivered
//! and never sends V3 (`services/world/src/azoth_world/rep.py`, `carrier_state_datagram`: *"the fix
//! that broke the V3 retry storm in first-light PR #5"*).
//!
//! ONE DATAGRAM, THREE RECORDS, CHANNEL 3, IN THIS ORDER
//! ====================================================
//! ```text
//! record       sys  reliable  flags  seq  relSeq   payload
//! CLOCK_SYNC    4   no        0x20   0    0xFFFF   u32 BE server clock ms, then the byte 4
//! CONNECT_ACK   2   YES       0x21   1    0        the welcome bytes, then the byte 2
//! CT_ACKS       6   no        0x18   —    —        0x40, u16 BE ack_last, u16 BE ack_first, then 6
//! ```
//! `0x20` is `MF_DATA_CHANNEL` alone, `0x21` adds `MF_RELIABLE`, and `0x18` is
//! `MF_SEQUENTIAL_ID | MF_SEQUENTIAL_REL_ID`: CT_ACKS inherits both sequences from CONNECT_ACK on
//! the same channel instead of writing them.
//!
//! THE SYS ID IS THE LAST PAYLOAD BYTE OF EVERY CHANNEL-3 RECORD
//! ============================================================
//! Not the first: a channel-3 payload is *data then id*, which is why
//! [`MessageRecord::system_msg_id`] reads the last byte and why every payload here pushes its id
//! last. Moving it to the front makes the client read the id as data.
//!
//! THREE MEASURED TRAPS
//! ====================
//! 1. **The envelope sequence ECHOES the client's inbound sequence.** It is not a server counter.
//!    Without the echo the client keeps retransmitting as if our reply never arrived (first-light
//!    "Mixed Nuts", 2026-05-04). That is why [`AcceptanceFlight::datagram`] takes the sequence as a
//!    parameter instead of numbering datagrams itself.
//! 2. **A reliable record with a mirrored relSeq blocks the client's reliable queue forever.** An
//!    earlier ACK that copied the client's own `0xFFFF` left the client in CONNECTING even though it
//!    had stopped resending (live capture 2026-09-16 20:23). So CLOCK_SYNC is **unreliable** with
//!    relSeq `0xFFFF` — the value an unreliable record carries before anything reliable has been
//!    received — and CONNECT_ACK is **reliable** with relSeq `0`.
//! 3. **The CONNECT_ACK payload is the client's version echoed verbatim**, then the sys id byte
//!    (`DefaultHandshake` semantics: `OnInitiate` writes the version into the ACK buffer and
//!    `OnReceiveRequest` echoes it). A datagram-ACK-shaped payload (`40 0002 0002`) was tried on
//!    2026-09-17 and did **not** advance the client; the version echo made it stop resending and
//!    acknowledge our datagram (2026-09-16). A caller that has not seen the client's request must
//!    not send the flight at all rather than invent a version string — see below.
//!
//! THE TRIGGER IS THE CLIENT'S REQUEST, NOT THE HANDSHAKE
//! =====================================================
//! The version to echo only exists once the client has spoken, so the flight is the answer to its
//! first `SM_CONNECT_REQUEST` (sys id 1, channel 3), not to the DTLS handshake. The prototype is
//! explicit (`rep.py::handle_app_data`: `if requests and not handshake_done`), and it takes the
//! version from that request — `welcome = first.payload[:-1][:4]` — with a `00 00 00 05` fallback
//! when the payload is shorter than five bytes. [`connect_welcome`] is that rule, so the server has
//! one implementation of it instead of one per call site.
//! WHY THESE BYTES ARE WRITTEN BY HAND
//! ==================================
//! [`crate::marshal`] derives each flag byte from the record's own fields plus the datagram's
//! cross-record state, and for this flight that derivation differs from the measured bytes in two
//! places: it omits CONNECT_ACK's sequence (`0x09` where the client was sent `0x21`) and it never
//! emits `MF_SEQUENTIAL_REL_ID` for an unreliable record (so CT_ACKS would lose its `0x10` and write
//! a relSeq instead). The flight is a captured byte pattern rather than a derived one, so it is
//! written literally and the test parses it back with [`crate::record::parse`].
//!
//! WHAT A RECORD PAYLOAD CARRIES
//! =============================
//! The rest of this module is the pre-game half of the record layer: [`Reassembly`] joins the
//! chunks a message is cut into, and [`registration_body`] finds the V3 registration in any of the
//! three framings that can carry it. Both are pure framing — no world state — which is why they live
//! here and not in the server that calls them.

use crate::envelope::Envelope;
use crate::error::WireError;
use crate::record::{MessageRecord, flags};
use crate::{CHANNEL_SYSTEM, container, v3, varint};

/// `SM_CONNECT_REQUEST`: the client's first channel-3 record, and the flight's trigger.
pub const SYS_CONNECT_REQUEST: u8 = 1;

/// `SM_CLOCK_SYNC`: the server's clock, the first record of the flight.
pub const SYS_CLOCK_SYNC: u8 = 4;

/// `SM_CONNECT_ACK`: the acceptance itself, and the only reliable record of the flight.
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
/// The payload is *data then id*, so the version is the bytes before the trailing sys-id byte,
/// truncated to the four bytes of the `u32` the client wrote. A payload under five bytes has no
/// version to echo and falls back to `00 00 00 05` — the prototype's own fallback, not an invented
/// one (`rep.py::handle_app_data`).
#[must_use]
pub fn connect_welcome(payload: &[u8]) -> Vec<u8> {
    if payload.len() < 5 {
        return DEFAULT_WELCOME.to_vec();
    }
    payload[..payload.len() - 1].iter().copied().take(4).collect()
}

/// The flight's trigger inside one client datagram: `(inbound envelope sequence, welcome)`.
///
/// Both values come off the client's own datagram and neither is invented: the sequence is echoed in
/// the reply's envelope and ACK range, and the welcome is what `CONNECT_ACK` echoes back. `None`
/// when the datagram is not a Carrier envelope, does not parse as records, or carries no channel-3
/// `SM_CONNECT_REQUEST` — an empty payload has no sys id, which is the prototype's own
/// `and rec.payload` condition.
#[must_use]
pub fn connect_request(bytes: &[u8]) -> Option<(u16, Vec<u8>)> {
    let (envelope, body) = crate::envelope::parse(bytes).ok()?;
    let parsed = crate::record::parse(body).ok()?;
    let request = parsed.records.iter().find(|message| {
        message.is_system() && message.system_msg_id() == Some(SYS_CONNECT_REQUEST)
    })?;
    Some((envelope.sequence, connect_welcome(&request.payload)))
}

/// The Carrier connection-acceptance flight: what makes a client leave CONNECTING and send V3.
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
    /// Build the flight as one datagram.
    ///
    /// `envelope_sequence` MUST be the client's inbound envelope sequence, echoed — not a server
    /// counter. See the module docs.
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] if a record's payload cannot be expressed in the `u16` size field,
    /// which needs a welcome above 65,522 bytes.
    pub fn datagram(&self, envelope_sequence: u16) -> Result<Vec<u8>, WireError> {
        let mut clock = Vec::with_capacity(5);
        clock.extend_from_slice(&self.clock_ms.to_be_bytes());
        clock.push(SYS_CLOCK_SYNC);

        let mut ack = Vec::with_capacity(self.welcome.len() + 1);
        ack.extend_from_slice(&self.welcome);
        ack.push(SYS_CONNECT_ACK);

        // `ack_last` before `ack_first`: the range is written high-then-low, and swapping them makes
        // the client acknowledge a range it can never reach.
        let mut acks = Vec::with_capacity(6);
        acks.push(ACK_CONTINUOUS);
        acks.extend_from_slice(&self.ack_last.to_be_bytes());
        acks.extend_from_slice(&self.ack_first.to_be_bytes());
        acks.push(SYS_CT_ACKS);

        let mut out = Envelope::new(envelope_sequence, false).encode().to_vec();
        push_record(&mut out, CLOCK_SYNC_FLAGS, (0, NO_RELIABLE_YET), &clock)?;
        push_record(&mut out, CONNECT_ACK_FLAGS, (1, 0), &ack)?;
        push_record(&mut out, CT_ACKS_FLAGS, (0, 0), &acks)?;
        Ok(out)
    }
}

/// Append one channel-3 record with an explicit flag byte, mirroring [`crate::record::parse`].
///
/// Each field is written exactly when its flag says the reader must read it: `MF_DATA_CHANNEL` puts
/// the channel byte on the wire, and a clear `MF_SEQUENTIAL_ID` / `MF_SEQUENTIAL_REL_ID` puts that
/// sequence on the wire. Deriving this from the flag byte rather than from a separate argument is
/// deliberate — the first version wrote the channel unconditionally, and CT_ACKS's `0x18` omits it,
/// so the reader treated the extra byte as the next record's flag and lost the stream.
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
/// The client chunks its own registration (`numChunks 3` measured), so a body only exists once its
/// last chunk arrives; every chunk carries the **total**, which is what lets a complete message be
/// recognised without a timer. Out-of-order delivery loses the message rather than corrupting it.
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
        // A chunk continues the message in progress only when it is the next one; anything else
        // starts over, which drops a duplicate instead of concatenating it twice.
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

    /// The moved reassembler, pinned where it now lives: a body exists only once the last chunk of
    /// the message has arrived.
    #[test]
    fn a_chunked_message_exists_only_once_its_last_chunk_arrives() {
        let mut reassembly = Reassembly::default();
        assert_eq!(reassembly.push(&chunk(0, 3, b"ab")), None);
        assert_eq!(reassembly.push(&chunk(1, 3, b"cd")), None);
        assert_eq!(
            reassembly.push(&chunk(2, 3, b"ef")),
            Some(b"abcdef".to_vec())
        );
    }

    /// A repeated chunk restarts the message instead of concatenating it twice, which is what makes
    /// an out-of-order or duplicated delivery lose the message rather than corrupt it.
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
        assert_eq!(
            connect_welcome(&[0xAA, 0xBB, 0xCC, 0xDD, SYS_CONNECT_REQUEST]),
            vec![0xAA, 0xBB, 0xCC, 0xDD]
        );
        // Longer than the version field: the extra data is truncated, never echoed.
        assert_eq!(
            connect_welcome(&[0xAA, 0xBB, 0xCC, 0xDD, 0xEE, SYS_CONNECT_REQUEST]),
            vec![0xAA, 0xBB, 0xCC, 0xDD]
        );
        // Shorter than the version field plus its id: nothing to echo.
        assert_eq!(
            connect_welcome(&[0xAA, SYS_CONNECT_REQUEST]),
            vec![0x00, 0x00, 0x00, 0x05]
        );
    }

    /// An unchunked record is its own body, which is every record that is not a V3 registration.
    #[test]
    fn an_unchunked_record_is_its_own_body() {
        let mut reassembly = Reassembly::default();
        let record = MessageRecord::data(0, 5, 5, vec![0xAA]);
        assert_eq!(reassembly.push(&record), Some(vec![0xAA]));
    }
}
