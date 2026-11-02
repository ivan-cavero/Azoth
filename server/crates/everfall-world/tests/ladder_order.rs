//! The three records the capture sends BEFORE the self-identification record.
//!
//! The official corpus opens, after the `0x3` registration answer, with a
//! `0x15d` ping (seq `0x02`), `0x40a` `CalendarConnectedMsg` (seq `0x04`),
//! `0x1be` `CoatlicueTimingConfigurationConnectedMsg` (seq `0x05`) and only then
//! the `0x65c` self-identification record (seq `0x06`). This server used to send
//! self-ident first, which is the ladder difference the live client stalls on at
//! `WaitingForActorGameConnection`.
//!
//! EVIDENCE LEVEL OF EACH BODY, and why there is no `partial` in this file:
//! every one of the three is `measured`. Each body parses end to end from the
//! committed corpus and round-trips byte-for-byte through its generated card, so
//! each assertion below is byte equality with the capture rather than "carried
//! verbatim, unverified". What is NOT claimed for `0x40a`/`0x1be` is a MEANING:
//! their 32-byte run and the shared 36-byte run are unnamed (see
//! `research/atlas/meanings.md`), so the server may only ever send the captured
//! bytes for them, which is exactly what the test pins.

use std::fs;
use std::path::PathBuf;

use everfall_wire::Datagram;
use everfall_wire::generated::{
    FlowWorldEntryRungCalendarConnected, FlowWorldEntryRungCoatlicueTiming,
    FlowWorldEntryRungLevelInfo, FlowWorldEntryRungPing, FlowWorldEntryRungSelfIdentification,
};
use everfall_world::Decision;
use everfall_world::ladder::{
    CapturedRungs, HEARTBEAT_PERIOD_MS, HEARTBEAT_TICK_STEP, PostV3Ladder, Rung,
};
use everfall_world::rep::RepSession;

const PING_WIRE_ID: u32 = 0x15d;
const CALENDAR_WIRE_ID: u32 = 0x40a;
const COATLICUE_WIRE_ID: u32 = 0x1be;
const SELF_IDENT_WIRE_ID: u32 = 0x65c;
const LEVEL_INFO_WIRE_ID: u32 = 0x663;
const STATE_WIRE_ID: u32 = 0x08;

/// The driver's poll step: the DTLS loop wakes at least this often.
const POLL_MS: u32 = 20;

/// The real `SM_CONNECT_REQUEST` datagram, envelope sequence 2.
const CONNECT_REQUEST: &str =
    "80010002a00005030000ffff0000000501880006ffff000000050101880002ffff2006";

/// The real V3 registration request datagram, envelope sequence 5 (LZ4 `0x81`).
const V3_REGISTRATION: &str = "81010005f00205045b000300000000890bd9290000099d0c00090200f00e0113970c0a5d06000000040436303331000000030334303000000002010e00f00501074a6176656c696e00000005073630303431351800f23700085b52455441494c5d00287369673a31373134383230302d616238662d343032302d393934322d3666636338376362663966340e3132372e302e302e313a393030302430300200102d0700702d343030302d380500000f00030200333124310100102d08000b0500040200ff473d616d7a6e312e646576656c6f706572506572736f6e6149642e66633930366330372d343261322d326464312d663539662d39633536636634663231326300103b321137363536313139373936303238373933300024d300116000006ace96fe0400045701520a000001010d002f01015b0003af8620737465616d7c61350200ffffad506135613561";

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn read(relative: &str) -> String {
    fs::read_to_string(repo_root().join(relative)).expect("read the committed fixture")
}

fn hex_bytes(hex: &str) -> Vec<u8> {
    assert!(hex.len().is_multiple_of(2), "odd hex length: {}", hex.len());
    (0..hex.len() / 2)
        .map(|index| {
            u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16).expect("hex digit pair")
        })
        .collect()
}

/// One committed body for a wire id from `wire-bodies.json`.
fn wire_body(wire_id: u32) -> Vec<u8> {
    let text = read("research/fixtures/wire/wire-bodies.json");
    let needle = format!("\"wire_id\": {wire_id},");
    let at = text.find(&needle).expect("wire id present");
    let body_key = "\"body\": \"";
    let body_at = text[at..].find(body_key).expect("body after the id") + body_key.len() + at;
    let rest = &text[body_at..];
    let end = rest.find('"').expect("closing quote after body");
    hex_bytes(&rest[..end])
}

/// The captured `0x9e` state bundle body, marker included.
fn state_bundle_body() -> Vec<u8> {
    let text = read("research/fixtures/wire/wire-fixtures.json");
    let needle = "\"source\": \"0x9e_T0x8_R.bin\"";
    let at = text.find(needle).expect("bundle source present");
    let body_key = "\"body\": \"";
    let body_at = text[..at].rfind(body_key).expect("body before source") + body_key.len();
    let rest = &text[body_at..];
    let end = rest.find('"').expect("closing quote after body");
    hex_bytes(&rest[..end])
}

/// The nine measured `(key, type_index, payload_len)` extents of the bundle.
fn state_extents() -> Vec<(u64, u64, usize)> {
    let text = read("research/derived/state-bundle-fragments.json");
    let mut out = Vec::new();
    let mut current: Option<(u64, u64, usize)> = None;
    for line in text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("\"key\": ") {
            if let Some(done) = current.take() {
                out.push(done);
            }
            current = Some((number(rest), 0, 0));
        } else if let (Some(rest), Some(slot)) =
            (line.strip_prefix("\"type_index\": "), current.as_mut())
        {
            slot.1 = number(rest);
        } else if let (Some(rest), Some(slot)) =
            (line.strip_prefix("\"payload_length\": "), current.as_mut())
        {
            slot.2 = number(rest) as usize;
        }
    }
    if let Some(done) = current {
        out.push(done);
    }
    assert_eq!(out.len(), 9, "the captured record carries nine fragments");
    out
}

fn number(field: &str) -> u64 {
    field
        .trim_end_matches(',')
        .parse()
        .expect("a number in the measured layout")
}

fn ladder() -> PostV3Ladder {
    PostV3Ladder::from_captured(
        &CapturedRungs {
            ping: &wire_body(PING_WIRE_ID),
            calendar_connected: &wire_body(CALENDAR_WIRE_ID),
            coatlicue_timing: &wire_body(COATLICUE_WIRE_ID),
            self_identification: &wire_body(SELF_IDENT_WIRE_ID),
            level_info: &wire_body(LEVEL_INFO_WIRE_ID),
            state_bundle: &state_bundle_body(),
        },
        &state_extents(),
        &Decision::Accepted,
    )
    .expect("the captured corpus builds the ladder")
}

/// Decode one Carrier record payload into `(wire id, body)`.
fn split_payload(payload: &[u8]) -> (u32, Vec<u8>) {
    let vlq_len = 1 + payload[0].leading_ones() as usize;
    assert_eq!(&payload[vlq_len..vlq_len + 2], &[0x00, 0x01], "type marker");
    let mut reader = everfall_wire::Reader::new(&payload[vlq_len + 2..]);
    let wire_id = reader.prefix_varint("type").expect("type varint") as u32;
    let header = vlq_len + 2 + reader.position();
    (wire_id, payload[header..].to_vec())
}

/// One data-channel datagram's `(wire id, body)`.
///
/// `None` for the transport keepalive (which rides the system channel and
/// carries no wire type) and for every chunk after the first of a chunked
/// record: a continuation chunk starts in the middle of the typed envelope, so it
/// has no type marker to read. The first chunk of a chunked rung does start with
/// the envelope, which is how the `0x65c` and `0x08` rungs are recognised below.
fn record_payload(datagram: &[u8]) -> Option<(u32, Vec<u8>)> {
    let decoded = Datagram::decode(datagram).expect("the reply is a plaintext datagram");
    let record = decoded.records().first().expect("one record per datagram");
    if record.channel() != 0 {
        return None;
    }
    let payload = record.payload();
    let vlq_len = 1 + payload[0].leading_ones() as usize;
    if payload.len() <= vlq_len + 2 || payload[vlq_len..vlq_len + 2] != [0x00, 0x01] {
        return None;
    }
    Some(split_payload(payload))
}

/// Drive a session through the handshake and collect `(elapsed_ms, wire id)` for
/// every data-channel datagram it emits, one release per poll until `until_ms`.
fn flight(until_ms: u32) -> Vec<(u32, u32)> {
    let clock = 0x9947_9CB9;
    let mut session = RepSession::new();
    session.set_ladder(ladder());
    session
        .on_app_data(&hex_bytes(CONNECT_REQUEST), clock)
        .expect("flight builds");
    session
        .on_app_data(&hex_bytes(V3_REGISTRATION), clock)
        .expect("registration builds");

    let mut sent = Vec::new();
    for elapsed in (0..=until_ms).step_by(POLL_MS as usize) {
        for datagram in session.tick(clock + elapsed).expect("tick") {
            if let Some((wire_id, _)) = record_payload(&datagram) {
                sent.push((elapsed, wire_id));
            }
        }
    }
    sent
}

#[test]
fn the_capture_order_puts_the_three_records_before_the_self_identification() {
    let sent = flight(1_200);
    let order: Vec<u32> = sent.iter().map(|&(_, wire_id)| wire_id).collect();
    let head: Vec<u32> = order.iter().copied().take(6).collect();
    assert_eq!(
        head,
        vec![
            PING_WIRE_ID,
            CALENDAR_WIRE_ID,
            COATLICUE_WIRE_ID,
            SELF_IDENT_WIRE_ID,
            LEVEL_INFO_WIRE_ID,
            STATE_WIRE_ID,
        ],
        "the capture's order is ping, calendar, coatlicue timing, THEN self-ident, level info, state: {order:?}"
    );
    assert!(
        sent.iter().any(|&(_, wire_id)| wire_id == STATE_WIRE_ID),
        "the state rung follows the level info"
    );
}

#[test]
fn the_heartbeat_repeats_once_a_second_after_the_ladder_has_drained() {
    let pings: Vec<u32> = flight(3_400)
        .into_iter()
        .filter(|&(_, wire_id)| wire_id == PING_WIRE_ID)
        .map(|(elapsed, _)| elapsed)
        .collect();
    assert!(
        pings.len() >= 4,
        "the heartbeat keeps running after the ladder drained: {pings:?}"
    );
    assert!(
        pings
            .windows(2)
            .all(|pair| pair[1] - pair[0] >= HEARTBEAT_PERIOD_MS),
        "no two heartbeats are closer than the reference's {HEARTBEAT_PERIOD_MS} ms period: {pings:?}"
    );
    assert!(
        pings
            .windows(2)
            .all(|pair| pair[1] - pair[0] <= HEARTBEAT_PERIOD_MS + POLL_MS),
        "the heartbeat is not later than one poll after its period: {pings:?}"
    );
}

#[test]
fn each_pre_self_ident_body_round_trips_through_its_card_unchanged() {
    let plan = ladder();
    let heartbeat = plan.heartbeat();

    // The first heartbeat carries the captured tick, re-encoded by the card.
    let ping_body = heartbeat
        .payload(heartbeat.tick())
        .expect("the ping card encodes");
    assert_eq!(
        ping_body,
        wire_body(PING_WIRE_ID),
        "the first ping re-encodes to the captured 8-byte body"
    );
    let ping = FlowWorldEntryRungPing::decode(&ping_body).expect("the ping decodes");
    let mut re_encoded = Vec::new();
    ping.encode(&mut re_encoded).expect("the ping re-encodes");
    assert_eq!(re_encoded, ping_body, "the ping card round-trips");

    // The tick is AUTHORED, not replayed: the next ping is one second later.
    let next = heartbeat
        .payload(heartbeat.tick() + HEARTBEAT_TICK_STEP)
        .expect("the next ping card encodes");
    let next_ping = FlowWorldEntryRungPing::decode(&next).expect("the next ping decodes");
    assert_eq!(
        next_ping.tick_high, ping.tick_high,
        "one second does not carry the tick into its high half"
    );
    assert_eq!(
        next_ping.tick_low,
        (u64::from(ping.tick_low) + HEARTBEAT_TICK_STEP) as u32,
        "the tick advances by exactly one second of nanoseconds"
    );

    // The two connected notices: unnamed runs, so the captured bytes are the
    // only legal body and the card must reproduce them byte for byte.
    for (rung, wire_id) in [
        (Rung::CalendarConnected, CALENDAR_WIRE_ID),
        (Rung::CoatlicueTiming, COATLICUE_WIRE_ID),
    ] {
        let captured = wire_body(wire_id);
        let emitted = plan.rung_payload(rung);
        let (emitted_wire_id, emitted_body) = split_payload(&emitted);
        assert_eq!(emitted_wire_id, wire_id, "{rung:?} carries its own type");
        assert_eq!(
            emitted_body, captured,
            "{rung:?} must send the captured body: its 32-byte run and shared 36-byte run are unnamed"
        );
    }

    // And the cards themselves round-trip those bodies.
    let calendar = FlowWorldEntryRungCalendarConnected::decode(&wire_body(CALENDAR_WIRE_ID))
        .expect("the calendar body decodes");
    let mut calendar_body = Vec::new();
    calendar
        .encode(&mut calendar_body)
        .expect("the calendar card encodes");
    assert_eq!(calendar_body, wire_body(CALENDAR_WIRE_ID));

    let coatlicue = FlowWorldEntryRungCoatlicueTiming::decode(&wire_body(COATLICUE_WIRE_ID))
        .expect("the coatlicue body decodes");
    let mut coatlicue_body = Vec::new();
    coatlicue
        .encode(&mut coatlicue_body)
        .expect("the coatlicue card encodes");
    assert_eq!(coatlicue_body, wire_body(COATLICUE_WIRE_ID));

    // The two records share their last 36 bytes; the cards carry one layout each
    // but must agree on that run, which is the second signal the atlas records.
    assert_eq!(
        &calendar_body[calendar_body.len() - 36..],
        &coatlicue_body[coatlicue_body.len() - 36..],
        "0x40a and 0x1be carry a byte-identical shared 36-byte run"
    );

    // The rungs that already existed are still the captured bodies.
    let (self_ident_wire, self_ident) = split_payload(&plan.rung_payload(Rung::SelfIdentification));
    assert_eq!(self_ident_wire, SELF_IDENT_WIRE_ID);
    let decoded = FlowWorldEntryRungSelfIdentification::decode(&self_ident)
        .expect("the self-ident body matches its card");
    let mut re_encoded = Vec::new();
    decoded
        .encode(&mut re_encoded)
        .expect("the self-ident card encodes");
    assert_eq!(re_encoded, self_ident);

    let (level_info_wire, level_info) = split_payload(&plan.rung_payload(Rung::LevelInfo));
    assert_eq!(level_info_wire, LEVEL_INFO_WIRE_ID);
    FlowWorldEntryRungLevelInfo::decode(&level_info).expect("the level-info body matches its card");
}
