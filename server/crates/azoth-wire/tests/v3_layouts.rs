//! The V3 registration layouts, as integration tests.
//!
//! WHY THESE LIVE HERE AND NOT IN THE MODULE
//! =========================================
//! They exercise only the public API, and `v3.rs` had grown past the workspace's 400-line limit.
//! The limit exists because a file past it usually means a boundary is wrong; here the boundary was
//! "the request's vocabulary and its byte assertions in one place", and moving the assertions out is
//! the fix that keeps both readable. The two tests that need the private `find_uuid`/`is_uuid`
//! helpers stayed beside them in `src/v3/parse.rs`, because an integration test cannot reach them
//! and widening the public surface for a test would be the worse trade.
//!
//! Every assertion below is about BYTES, not about behaviour: the layout was decoded from the
//! client's own readers, so the risk is a wrong offset or a wrong width, and only a byte comparison
//! catches those. The offset schedule is repeated here as a local constant for that reason — a test
//! that imported the schedule from the parser could not notice the schedule being wrong.

use azoth_wire::v3::{EXPECTED_BODY_LEN, RegistrationResponse, RequestFormat, parse};
use azoth_wire::{TYPE_MARKER, WireError};

/// End of the opaque prelude, and the first field's offset.
const PRELUDE_END: usize = 0x21;
/// The measured field offsets of the strict form.
const SCHEDULE: [usize; 12] = [
    0x021, 0x02A, 0x038, 0x044, 0x050, 0x05A, 0x083, 0x0A8, 0x0CD, 0x110, 0x144, 0x157,
];
/// Where the 12-byte trailer begins.
const TRAILER_OFF: usize = 0x334;
/// The 12-byte trailer the request must end with.
const REQUEST_TRAILER: [u8; 12] = [0x00, 0x43, 0x02, 0x80, 0, 0, 0, 0, 0, 0, 0, 0];
/// The response's type byte.
const RESPONSE_TYPE_BYTE: u8 = 0x03;

/// Build a strict body with the given field values, padding the opaque regions with a marker.
fn strict_body(fields: [&[u8]; 12]) -> Vec<u8> {
    let mut out = vec![0xAA; PRELUDE_END];
    for (index, offset) in SCHEDULE.iter().enumerate() {
        while out.len() < *offset {
            out.push(0xBB); // an opaque gap
        }
        assert_eq!(out.len(), *offset);
        out.push(fields[index].len() as u8);
        out.extend_from_slice(fields[index]);
    }
    while out.len() < TRAILER_OFF {
        out.push(0xCC); // the auth blob
    }
    out.extend_from_slice(&REQUEST_TRAILER);
    out
}

/// A real capture's field values, because the offsets only line up for their lengths.
fn sample_fields() -> [&'static [u8]; 12] {
    [
        b"6033",
        b"400",
        b"Javelin",
        b"6024067x",
        b"[RETAIL]",
        b"sig:01234567-89ab-4cde-8f01-23456789abcd",
        b"127.0.0.1:27000",
        b"01234567-89ab-4cde-8f01-23456789abcd",
        b"amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c",
        b"STEAM_APP_ID.1063730",
        b"76561197960287930",
        b"steam|14",
    ]
}

#[test]
fn the_strict_body_is_832_bytes() {
    assert_eq!(strict_body(sample_fields()).len(), EXPECTED_BODY_LEN);
}

#[test]
fn strict_round_trips_byte_for_byte() {
    let body = strict_body(sample_fields());
    let parsed = parse(&body).expect("parses");
    assert_eq!(parsed.format, RequestFormat::Strict);
    assert_eq!(parsed.encode().expect("encodes"), body);
}

#[test]
fn the_identity_fields_are_readable() {
    let parsed = parse(&strict_body(sample_fields())).expect("parses");
    assert_eq!(
        parsed.persona_id(),
        Some("amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c")
    );
    assert_eq!(
        parsed.ticket_uuid(),
        Some("01234567-89ab-4cde-8f01-23456789abcd")
    );
    assert_eq!(
        parsed.session_uuid(),
        Some("01234567-89ab-4cde-8f01-23456789abcd")
    );
    assert_eq!(parsed.platform_app_tag(), Some("STEAM_APP_ID.1063730"));
    assert_eq!(parsed.field_str(2), Some("Javelin"), "index 2 is the SDK name");
}

#[test]
fn a_short_body_is_rejected() {
    let err = parse(&[0u8; 100]).expect_err("must fail");
    assert!(matches!(err, WireError::LengthMismatch { .. }), "{err}");
}

#[test]
fn a_body_without_the_trailer_is_rejected() {
    let mut body = strict_body(sample_fields());
    let last = body.len() - 1;
    body[last] = 0xFF;
    assert!(parse(&body).is_err());
}

#[test]
fn the_response_carries_the_token_and_a_length_prefix() {
    let response = RegistrationResponse::success([0x5A; 32]);
    let body = response.encode().expect("encodes");
    assert_eq!(&body[..2], &TYPE_MARKER);
    assert_eq!(body[2], RESPONSE_TYPE_BYTE);
    assert_eq!(&body[3..7], &0i32.to_be_bytes());
    assert_eq!(body[15], 0x20, "token length byte");
    assert_eq!(&body[16..48], &[0x5A; 32]);
    // The record form prefixes the body with its length.
    let record = response.encode_record().expect("encodes");
    assert_eq!(record[0] as usize, body.len(), "VLQ32 length prefix");
    assert_eq!(&record[1..], body.as_slice());
}

#[test]
fn the_response_trailer_is_cleared_not_captured() {
    // The captured `01 00 00 01` makes the client fail registration with
    // registration_failed / eos_unknown_error. This pins the working form.
    let body = RegistrationResponse::success([0; 32])
        .encode()
        .expect("encodes");
    assert_eq!(&body[body.len() - 4..], &[0, 0, 0, 0]);
}

#[test]
fn the_retry_form_is_recognised_and_round_trips() {
    // 32-byte prelude, six tagged records, then a separator and identity strings.
    let mut body = vec![0x11; 32];
    let records: [(u32, &[u8]); 6] = [
        (0, b"[RETAIL]"),
        (1, b"Javelin"),
        (2, b""),
        (3, b"400"),
        (4, b"6033"),
        (5, b"6024067x"),
    ];
    for (type_id, value) in records {
        body.extend_from_slice(&type_id.to_be_bytes());
        body.push(value.len() as u8);
        body.extend_from_slice(value);
    }
    body.push(0x00); // separator
    for value in [
        &b"sig:01234567-89ab-4cde-8f01-23456789abcd"[..],
        b"127.0.0.1:27000",
        b"STEAM_APP_ID.1063730",
        b"76561197960287930",
        b"01234567-89ab-4cde-8f01-23456789abcd",
    ] {
        body.push(value.len() as u8);
        body.extend_from_slice(value);
    }

    let parsed = parse(&body).expect("parses");
    assert_eq!(parsed.format, RequestFormat::Retry);
    assert_eq!(parsed.field_str(2), Some("Javelin"), "index 2 is the SDK name");
    assert_eq!(
        parsed.ticket_uuid(),
        Some("01234567-89ab-4cde-8f01-23456789abcd")
    );
    assert_eq!(parsed.encode().expect("encodes"), body);
}

#[test]
fn a_retry_form_with_missing_tags_is_rejected() {
    let mut body = vec![0x11; 32];
    for type_id in [0u32, 1, 2, 3, 4] {
        // only five records
        body.extend_from_slice(&type_id.to_be_bytes());
        body.push(1);
        body.push(b'x');
    }
    assert!(parse(&body).is_err());
}
