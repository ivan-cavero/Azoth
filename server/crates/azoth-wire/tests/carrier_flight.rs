//! The acceptance flight as bytes: one datagram, three channel-3 records, in the measured order.
//!
//! WHY THESE ASSERTIONS ARE BYTE-LEVEL
//! ==================================
//! The client validates this datagram instead of tolerating it: a flag byte that merely repeats a
//! field, a mirrored reliable sequence, or a sys id anywhere but the payload's last byte all leave
//! the client in CONNECTING with no error on either side. So each test below names one measured
//! property of `services/world/src/azoth_world/rep.py::carrier_state_datagram` and checks it through
//! `azoth_wire::record::parse` — the reader the client's framing mirrors — never through a private
//! encoder detail.

use azoth_wire::carrier::{ACK_CONTINUOUS, AcceptanceFlight, SYS_CLOCK_SYNC, SYS_CONNECT_ACK, SYS_CT_ACKS};
use azoth_wire::record::MessageRecord;
use azoth_wire::{envelope, record};

/// The clock the flight under test carries, chosen so a byte-order mistake is visible.
const CLOCK_MS: u32 = 0x0102_0304;
/// The welcome bytes, deliberately not a version number: the encoder must echo what it is given.
const WELCOME: &[u8] = b"V3";
/// The inbound range under test, both values distinct so a swap is visible.
const ACK_FIRST: u16 = 0x0056;
const ACK_LAST: u16 = 0x1234;

/// The records of a flight, plus the envelope it arrived in.
fn parsed(envelope_sequence: u16) -> (envelope::Envelope, Vec<MessageRecord>) {
    let flight = AcceptanceFlight {
        clock_ms: CLOCK_MS,
        welcome: WELCOME.to_vec(),
        ack_first: ACK_FIRST,
        ack_last: ACK_LAST,
    };
    let datagram = flight.datagram(envelope_sequence).expect("the flight encodes");
    let (head, body) = envelope::parse(&datagram).expect("the flight starts with an envelope");
    let parsed = record::parse(body).expect("the body parses as records");
    assert_eq!(
        parsed.trailing_bytes, 0,
        "the flight must consume its datagram exactly"
    );
    (head, parsed.records)
}

/// 1. One datagram, exactly three records, in order, all on the system channel.
#[test]
fn the_flight_is_one_datagram_of_three_system_channel_records() {
    let (head, records) = parsed(7);
    assert!(
        !head.is_compressed(),
        "the flight is a plaintext record stream"
    );
    assert_eq!(records.len(), 3, "one datagram, three records, no more");
    for (index, message) in records.iter().enumerate() {
        assert_eq!(message.channel, 3, "record {index} rides channel 3");
        assert!(message.is_system(), "record {index} is a system message");
        assert_eq!(message.num_chunks, 1, "record {index} is not chunked");
    }
    let ids: Vec<Option<u8>> = records.iter().map(MessageRecord::system_msg_id).collect();
    assert_eq!(
        ids,
        vec![Some(SYS_CLOCK_SYNC), Some(SYS_CONNECT_ACK), Some(SYS_CT_ACKS)],
        "CLOCK_SYNC, then CONNECT_ACK, then CT_ACKS"
    );
}

/// 2. The ids are 4, 2 and 6, and each is the LAST byte of its own payload.
#[test]
fn each_system_id_is_the_last_payload_byte() {
    let (_, records) = parsed(7);

    // CLOCK_SYNC: the clock, then the id.
    let mut clock = CLOCK_MS.to_be_bytes().to_vec();
    clock.push(SYS_CLOCK_SYNC);
    assert_eq!(records[0].payload, clock, "u32 BE clock, then the byte 4");
    assert_eq!(records[0].payload.last(), Some(&4u8));

    // CONNECT_ACK: the welcome verbatim, then the id.
    let mut ack = WELCOME.to_vec();
    ack.push(SYS_CONNECT_ACK);
    assert_eq!(records[1].payload, ack, "the welcome bytes, then the byte 2");
    assert_eq!(records[1].payload.last(), Some(&2u8));

    // CT_ACKS: the range, then the id.
    assert_eq!(records[2].payload.last(), Some(&6u8));
    assert_eq!(
        records[2].payload.first(),
        Some(&ACK_CONTINUOUS),
        "the ACK range opens with the continuous-ACK flags byte"
    );
}

/// 3. CLOCK_SYNC is unreliable with relSeq 0xFFFF, CONNECT_ACK is reliable with relSeq 0, and
///    CT_ACKS carries flags 0x18 — the combination that does not block the client's queue.
#[test]
fn the_reliability_of_each_record_is_the_measured_one() {
    let (_, records) = parsed(7);

    assert_eq!(records[0].flags, 0x20, "CLOCK_SYNC: MF_DATA_CHANNEL only");
    assert!(!records[0].reliable, "CLOCK_SYNC is unreliable");
    assert_eq!(records[0].sequence, 0);
    assert_eq!(
        records[0].reliable_sequence, 0xFFFF,
        "an unreliable record before anything reliable carries 0xFFFF, never the client's value"
    );

    assert_eq!(
        records[1].flags, 0x21,
        "CONNECT_ACK: MF_RELIABLE | MF_DATA_CHANNEL"
    );
    assert!(records[1].reliable, "CONNECT_ACK is the reliable record");
    assert_eq!(records[1].sequence, 1);
    assert_eq!(
        records[1].reliable_sequence, 0,
        "a mirrored relSeq blocks the client's reliable queue forever"
    );

    assert_eq!(
        records[2].flags, 0x18,
        "CT_ACKS: MF_SEQUENTIAL_ID | MF_SEQUENTIAL_REL_ID"
    );
    assert!(!records[2].reliable, "CT_ACKS is an unreliable piggyback");
    assert_eq!(
        (records[2].sequence, records[2].reliable_sequence),
        (2, 0),
        "both sequence fields are inherited from CONNECT_ACK on channel 3"
    );
}

/// 4. The envelope sequence is exactly the one passed in: the client's inbound sequence, echoed.
#[test]
fn the_envelope_sequence_is_the_one_passed_in() {
    for sequence in [0u16, 1, 0x00FF, 0x1234, 0xFFFF] {
        let (head, _) = parsed(sequence);
        assert_eq!(
            head.sequence, sequence,
            "the reply must echo the client's inbound sequence, not count its own"
        );
    }
}

/// 5. The CT_ACKS payload is `0x40`, then `ack_last`, then `ack_first`, then the sys id.
#[test]
fn the_ct_acks_payload_is_flags_then_last_then_first() {
    let (_, records) = parsed(7);
    let expected = vec![
        ACK_CONTINUOUS,
        (ACK_LAST >> 8) as u8,
        (ACK_LAST & 0xFF) as u8,
        (ACK_FIRST >> 8) as u8,
        (ACK_FIRST & 0xFF) as u8,
        SYS_CT_ACKS,
    ];
    assert_eq!(records[2].payload, expected, "0x40, last, first, id");
    assert_eq!(records[2].payload.len(), 6);
}

/// The whole datagram against the prototype's encoder, byte for byte.
///
/// This is the parity oracle rather than a restatement of the tests above: `python -c` on
/// `services/world/src/azoth_world/rep.py::carrier_state_datagram(7, welcome=b"V3",
/// ack_first=0x0056, ack_last=0x1234)` with the clock pinned to `0x01020304` prints these 37 bytes,
/// and that function is the one that took the client to V3. A difference here is a difference the
/// client would see.
#[test]
fn the_datagram_is_the_prototypes_bytes_verbatim() {
    let flight = AcceptanceFlight {
        clock_ms: CLOCK_MS,
        welcome: WELCOME.to_vec(),
        ack_first: ACK_FIRST,
        ack_last: ACK_LAST,
    };
    let datagram = flight.datagram(7).expect("the flight encodes");
    let expected: Vec<u8> = vec![
        0x80, 0x01, 0x00, 0x07, // envelope: plaintext, protocol 1, sequence 7
        0x20, 0x00, 0x05, 0x03, 0x00, 0x00, 0xFF, 0xFF, 0x01, 0x02, 0x03, 0x04, 0x04, // CLOCK_SYNC
        0x21, 0x00, 0x03, 0x03, 0x00, 0x01, 0x00, 0x00, 0x56, 0x33, 0x02, // CONNECT_ACK
        0x18, 0x00, 0x06, 0x40, 0x12, 0x34, 0x00, 0x56, 0x06, // CT_ACKS
    ];
    assert_eq!(datagram, expected);
}
