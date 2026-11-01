//! The Carrier's system-channel messages: the connection-acceptance flight and
//! its stand-alone ACK.
//!
//! These are TRANSPORT commands, not typed messages. They ride the Carrier system
//! channel (3), their wire id is the payload's LAST byte rather than a typed
//! envelope, and the Atlas gives them no card -- [`crate::generated`] cannot name
//! them. So this module is framing, like [`crate::carrier`]: it mirrors the
//! reference's `carrier_state_datagram` / `ct_acks_datagram` / `clock_sync_datagram`
//! in `services/world/src/azoth_world/rep.py`, which in turn mirrors `GridMate`'s
//! `CarrierImpl::ProcessSystemMessages`.
//!
//! The acceptance flight is three records in one datagram, in this order:
//!
//! 1. `SM_CLOCK_SYNC` (sys 4): unreliable, flags `0x20`, sequence 0, reliable
//!    sequence `0xffff` (an unreliable record carries the last reliable sequence,
//!    which starts at `0xffff`). Payload: a `u32 BE` server clock in
//!    milliseconds, then the id byte.
//! 2. `SM_CONNECT_ACK` (sys 2): reliable, flags `0x21`. Payload: the welcome
//!    data the client sent, then the id byte.
//! 3. `SM_CT_ACKS` (sys 6): unreliable piggyback, flags `0x18` (both sequence
//!    fields omitted, inherited). Payload: `0x40`, the acknowledged range's last
//!    and first envelope sequences (`u16 BE` each), then the id byte.
//!
//! The reply envelope echoes the client's inbound envelope sequence; the caller
//! passes it in. Every byte here is the reference's, proved field for field in
//! `.azoth/logs/world.log` captures (see
//! `server/crates/everfall-wire/tests/carrier_parity.rs`).

use crate::carrier::{CarrierError, Compression, Datagram, Envelope, MessageRecord};

/// The Carrier's system channel, whose records end in a system message id.
pub const SYSTEM_CHANNEL: u8 = 3;

/// `SM_CONNECT_REQUEST`: the client's connection request.
pub const SM_CONNECT_REQUEST: u8 = 1;

/// `SM_CONNECT_ACK`: the server's connection acceptance.
pub const SM_CONNECT_ACK: u8 = 2;

/// `SM_DISCONNECT`: either peer dropping the connection.
pub const SM_DISCONNECT: u8 = 3;

/// `SM_CLOCK_SYNC`: the server's time sync.
pub const SM_CLOCK_SYNC: u8 = 4;

/// `SM_CT_ACKS`: the continuous datagram acknowledgement.
pub const SM_CT_ACKS: u8 = 6;

/// The flag byte of an unreliable record that carries its channel: `0x20`.
const FLAGS_UNRELIABLE_DATA_CHANNEL: u8 = 0x20;

/// The flag byte of a reliable record that carries its channel: `0x21`.
const FLAGS_RELIABLE_DATA_CHANNEL: u8 = 0x21;

/// The flag byte whose two sequence fields are inherited: `0x18`.
const FLAGS_SEQUENTIAL_SEQUENCES: u8 = 0x18;

/// The leading byte of a continuous ACK payload.
const CT_ACKS_PREFIX: u8 = 0x40;

/// The first reliable sequence on a channel before any reliable record: `0xffff`.
const INITIAL_RELIABLE_SEQUENCE: u16 = 0xFFFF;

/// True when `record` is an `SM_CONNECT_REQUEST` on the system channel.
#[must_use]
pub fn is_connect_request(record: &MessageRecord) -> bool {
    record.channel() == SYSTEM_CHANNEL
        && record.system_message_id() == Some(SM_CONNECT_REQUEST)
        && !record.payload().is_empty()
}

/// The welcome data of a `SM_CONNECT_REQUEST`: the version the client wrote into
/// it.
///
/// The reference takes `payload[:-1][:4]` (the payload without its id byte, then
/// its first four bytes) and falls back to `00 00 00 05` when the record is
/// shorter than the five bytes that needs. Returning `None` lets the caller
/// choose the same fallback.
#[must_use]
pub fn connect_request_welcome(record: &MessageRecord) -> Option<[u8; 4]> {
    if !is_connect_request(record) {
        return None;
    }
    let payload = record.payload();
    if payload.len() < 5 {
        return None;
    }
    let mut welcome = [0u8; 4];
    welcome.copy_from_slice(&payload[..4]);
    Some(welcome)
}

/// The reference's fallback welcome when a `SM_CONNECT_REQUEST` is too short.
pub const DEFAULT_WELCOME: [u8; 4] = [0x00, 0x00, 0x00, 0x05];

/// The connection-acceptance flight: `SM_CLOCK_SYNC`, `SM_CONNECT_ACK`, `SM_CT_ACKS`.
///
/// `envelope_seq` is echoed from the client's inbound datagram, `clock_ms` is the
/// server clock the sync record carries, `welcome` is the version echoed back in
/// the ACK, and `ack_first`/`ack_last` are the acknowledged envelope range.
///
/// # Errors
/// Returns a [`CarrierError`] only if a record's payload cannot be framed, which
/// the fixed five- and six-byte payloads here cannot trigger.
pub fn acceptance_flight(
    envelope_seq: u16,
    clock_ms: u32,
    welcome: [u8; 4],
    ack_first: u16,
    ack_last: u16,
) -> Result<Vec<u8>, CarrierError> {
    let mut clock = clock_ms.to_be_bytes().to_vec();
    clock.push(SM_CLOCK_SYNC);
    let clock_sync = MessageRecord::new(SYSTEM_CHANNEL, clock)
        .with_flags_override(FLAGS_UNRELIABLE_DATA_CHANNEL)
        .with_reliable_sequence(INITIAL_RELIABLE_SEQUENCE);

    let mut ack = welcome.to_vec();
    ack.push(SM_CONNECT_ACK);
    let connect_ack = MessageRecord::new(SYSTEM_CHANNEL, ack)
        .with_reliable()
        .with_flags_override(FLAGS_RELIABLE_DATA_CHANNEL)
        .with_sequence(1);

    let piggyback = MessageRecord::new(SYSTEM_CHANNEL, ct_acks_payload(ack_first, ack_last))
        .with_flags_override(FLAGS_SEQUENTIAL_SEQUENCES);

    Datagram::new(
        Envelope::new(envelope_seq, Compression::Plaintext),
        vec![clock_sync, connect_ack, piggyback],
    )
    .encode()
}

/// A stand-alone `SM_CT_ACKS` datagram, so the client treats its reliable
/// registration as delivered.
///
/// # Errors
/// Returns a [`CarrierError`] only if the six-byte payload cannot be framed.
pub fn ct_acks(envelope_seq: u16, ack_first: u16, ack_last: u16) -> Result<Vec<u8>, CarrierError> {
    let record = MessageRecord::new(SYSTEM_CHANNEL, ct_acks_payload(ack_first, ack_last))
        .with_flags_override(FLAGS_UNRELIABLE_DATA_CHANNEL)
        .with_reliable_sequence(INITIAL_RELIABLE_SEQUENCE);
    Datagram::new(
        Envelope::new(envelope_seq, Compression::Plaintext),
        vec![record],
    )
    .encode()
}

/// The `SM_CT_ACKS` payload: `0x40`, the range's last then first sequence, the id.
fn ct_acks_payload(ack_first: u16, ack_last: u16) -> Vec<u8> {
    let mut payload = Vec::with_capacity(6);
    payload.push(CT_ACKS_PREFIX);
    payload.extend_from_slice(&ack_last.to_be_bytes());
    payload.extend_from_slice(&ack_first.to_be_bytes());
    payload.push(SM_CT_ACKS);
    payload
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::carrier::decode_records;

    #[test]
    fn the_acceptance_flight_matches_the_reference_bytes() {
        let raw = acceptance_flight(2, 0x9947_9CB9, [0, 0, 0, 5], 2, 2).expect("flight encodes");
        assert_eq!(
            raw,
            [
                0x80, 0x01, 0x00, 0x02, // envelope
                0x20, 0x00, 0x05, 0x03, 0x00, 0x00, 0xff, 0xff, 0x99, 0x47, 0x9c, 0xb9, 0x04, 0x21,
                0x00, 0x05, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05, 0x02, 0x18, 0x00,
                0x06, 0x40, 0x00, 0x02, 0x00, 0x02, 0x06,
            ]
        );
        let body = &raw[4..];
        let records = decode_records(body).expect("records decode");
        assert_eq!(records.len(), 3);
        assert_eq!(records[0].system_message_id(), Some(SM_CLOCK_SYNC));
        assert_eq!(records[1].system_message_id(), Some(SM_CONNECT_ACK));
        assert_eq!(records[2].system_message_id(), Some(SM_CT_ACKS));
    }

    #[test]
    fn the_standalone_ct_acks_matches_the_reference_bytes() {
        let raw = ct_acks(5, 5, 5).expect("acks encodes");
        assert_eq!(
            raw,
            [
                0x80, 0x01, 0x00, 0x05, 0x20, 0x00, 0x06, 0x03, 0x00, 0x00, 0xff, 0xff, 0x40, 0x00,
                0x05, 0x00, 0x05, 0x06,
            ]
        );
    }

    #[test]
    fn a_connect_request_is_recognised_and_its_welcome_read() {
        let mut payload = 0x0000_0005u32.to_be_bytes().to_vec();
        payload.push(SM_CONNECT_REQUEST);
        let record = MessageRecord::new(SYSTEM_CHANNEL, payload);
        assert!(is_connect_request(&record));
        assert_eq!(connect_request_welcome(&record), Some([0, 0, 0, 5]));

        let short = MessageRecord::new(SYSTEM_CHANNEL, vec![0x01]);
        assert!(is_connect_request(&short));
        assert_eq!(connect_request_welcome(&short), None);
    }
}
