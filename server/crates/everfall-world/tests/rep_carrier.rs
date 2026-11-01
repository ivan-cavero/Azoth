//! The REP carrier layer, replayed against REAL captured datagrams.
//!
//! Source of the bytes below:
//!
//! * the `SM_CONNECT_REQUEST` is the `app-data handshake seq 2` datagram in
//!   `server/crates/everfall-wire/tests/fixtures/carrier_datagrams.rs`, lifted
//!   verbatim from `.azoth/logs/world.log` (session 2026-10-19T20:52:39Z, client
//!   build `1.400.6031.6004151`); and
//! * the V3 registration request is the compressed (`0x81`) datagram at envelope
//!   sequence 5 in `.azoth/logs/world.log.fix2` (2026-10-13), the client's
//!   `RegistrationRequestV3Msg` retry body carrying session
//!   `17148200-ab8f-4020-9942-6fcc87cbf9f4`.
//!
//! The expected replies are the reference's own bytes
//! (`services/world/src/azoth_world/rep.py::handle_app_data`), so the Rust path is
//! checked against the implementation it was ported from. The one deliberate
//! difference is the registration body's 32-byte token: the reference echoes the
//! client's `session_uuid`, which lives in an uncarded request body this server
//! does not parse, so the card's redacted slot is filled with the reference's own
//! stub. The expected bytes below carry that stub.

use everfall_world::{
    REGISTRATION_REQUEST_WIRE_ID, RepRequest, RepSession, SERVER_VERSION, SESSION_TOKEN,
    handle_app_data,
};

/// The real `SM_CONNECT_REQUEST` datagram, envelope sequence 2.
const CONNECT_REQUEST: &str =
    "80010002a00005030000ffff0000000501880006ffff000000050101880002ffff2006";

/// The real V3 registration request datagram, envelope sequence 5 (LZ4 `0x81`).
const V3_REGISTRATION: &str = "81010005f00205045b000300000000890bd9290000099d0c00090200f00e0113970c0a5d06000000040436303331000000030334303000000002010e00f00501074a6176656c696e00000005073630303431351800f23700085b52455441494c5d00287369673a31373134383230302d616238662d343032302d393934322d3666636338376362663966340e3132372e302e302e313a393030302430300200102d0700702d343030302d380500000f00030200333124310100102d08000b0500040200ff473d616d7a6e312e646576656c6f706572506572736f6e6149642e66633930366330372d343261322d326464312d663539662d39633536636634663231326300103b321137363536313139373936303238373933300024d300116000006ace96fe0400045701520a000001010d002f01015b0003af8620737465616d7c61350200ffffad506135613561";

/// A real stand-alone `SM_CT_ACKS` datagram, envelope sequence 6.
const CT_ACKS_ONLY: &str = "80010006200006030000ffff400006000206";

/// The reference's acceptance flight for [`CONNECT_REQUEST`] (clock `0x99479cb9`).
const EXPECTED_FLIGHT: &str =
    "80010002200005030000ffff99479cb90421000503000100000000000502180006400002000206";

/// The expected registration response built from the `flow.world-entry.rung.registration` card.
const EXPECTED_REGISTRATION: &str = "80010006210059000000000058000103000000000b888d68706c415b20415a4f54482d737475622d73657373696f6e2d746f6b656e2d33326279746573235b52455441494c5d2e4a6176656c696e2e312e3430302e363033312e3630303431353100000000";

/// The expected stand-alone `SM_CT_ACKS` for the V3 datagram.
const EXPECTED_CT_ACKS: &str = "80010005200006030000ffff400005000506";

/// The server clock the flight is built with, so the sync bytes are fixed.
const CLOCK_MS: u32 = 0x9947_9CB9;

fn hex_bytes(hex: &str) -> Vec<u8> {
    assert!(hex.len().is_multiple_of(2), "odd hex length: {}", hex.len());
    (0..hex.len() / 2)
        .map(|index| {
            u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16).expect("hex digit pair")
        })
        .collect()
}

fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;
    bytes.iter().fold(String::new(), |mut out, byte| {
        write!(out, "{byte:02x}").expect("formatting into a String cannot fail");
        out
    })
}

#[test]
fn a_real_connect_request_is_answered_with_the_acceptance_flight() {
    let app = hex_bytes(CONNECT_REQUEST);
    let request = RepRequest {
        app: &app,
        client_env_seq: 2,
        handshake_done: false,
        v3_done: false,
        ack_allowed: true,
        ack_first: 2,
        clock_ms: CLOCK_MS,
    };
    let replies = handle_app_data(&request).expect("flight builds");
    assert_eq!(replies.len(), 1, "the request gets exactly one reply");
    assert_eq!(hex(&replies[0]), EXPECTED_FLIGHT);
}

#[test]
fn a_real_v3_registration_is_answered_with_the_card_response() {
    let app = hex_bytes(V3_REGISTRATION);
    let request = RepRequest {
        app: &app,
        client_env_seq: 5,
        handshake_done: true,
        v3_done: false,
        ack_allowed: true,
        ack_first: 5,
        clock_ms: CLOCK_MS,
    };
    let replies = handle_app_data(&request).expect("registration builds");
    assert_eq!(replies.len(), 2, "the registration answer and its ACK");
    assert_eq!(hex(&replies[0]), EXPECTED_REGISTRATION);
    assert_eq!(hex(&replies[1]), EXPECTED_CT_ACKS);
}

#[test]
fn the_registration_reply_is_the_card_the_atlas_names() {
    // Decode the reply's card body back through the generated codec and check that
    // every value is the one the world chose, rather than a replayed capture.
    let app = hex_bytes(V3_REGISTRATION);
    let request = RepRequest {
        app: &app,
        client_env_seq: 5,
        handshake_done: true,
        v3_done: false,
        ack_allowed: true,
        ack_first: 5,
        clock_ms: CLOCK_MS,
    };
    let reply = handle_app_data(&request)
        .expect("registration builds")
        .remove(0);

    // envelope(4) + record header(8) + VLQ32 length(1) + marker(2) + type(1)
    let body = &reply[16..];
    let card = everfall_wire::generated::FlowWorldEntryRungRegistration::decode(body)
        .expect("the reply body is the registration card");
    assert_eq!(card.server_version, SERVER_VERSION);
    assert_eq!(card.unresolved_block.len(), SESSION_TOKEN.len());
    assert_eq!(
        card.unresolved_block.id(),
        "flow.world-entry.rung.registration.unresolved_block"
    );
    assert!(!card.trailing_bool_0 && !card.trailing_bool_3);
}

#[test]
fn a_datagram_without_the_handshake_messages_is_not_answered() {
    let app = hex_bytes(CT_ACKS_ONLY);
    let request = RepRequest {
        app: &app,
        client_env_seq: 6,
        handshake_done: false,
        v3_done: false,
        ack_allowed: true,
        ack_first: 6,
        clock_ms: CLOCK_MS,
    };
    assert!(handle_app_data(&request).expect("no replies").is_empty());
}

#[test]
fn a_second_connect_request_after_the_flight_is_not_answered_again() {
    let app = hex_bytes(CONNECT_REQUEST);
    let request = RepRequest {
        app: &app,
        client_env_seq: 2,
        handshake_done: true,
        v3_done: false,
        ack_allowed: true,
        ack_first: 2,
        clock_ms: CLOCK_MS,
    };
    assert!(handle_app_data(&request).expect("no replies").is_empty());
}

#[test]
fn the_registration_type_is_the_uncarded_request_the_card_aliases() {
    assert_eq!(REGISTRATION_REQUEST_WIRE_ID, 0x13);
}

#[test]
fn a_session_answers_the_flight_then_the_registration() {
    let mut session = RepSession::new();
    assert!(!session.handshake_done() && !session.v3_responded());

    let flight = session
        .on_app_data(&hex_bytes(CONNECT_REQUEST), CLOCK_MS)
        .expect("flight builds");
    assert_eq!(flight.len(), 1);
    assert!(session.handshake_done());

    let registration = session
        .on_app_data(&hex_bytes(V3_REGISTRATION), CLOCK_MS + 100)
        .expect("registration builds");
    assert_eq!(registration.len(), 2);
    assert!(session.v3_responded());
}
