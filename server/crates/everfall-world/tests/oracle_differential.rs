//! The post-V3 stream, held byte for byte against the Python reference.
//!
//! `services/world/src/azoth_world/rep.py` is the oracle: its
//! `javelin.frame.marshal_datagram` writer, `javelin.wire.chunk_replay_payload`,
//! the `_send_replay_message` single/chunk split and the `clock_sync_datagram`
//! keepalive, composed in the reference's own tick order
//! (`PeerSession.tick`: `maybe_keepalive` before `maybe_pump_replay`). Running
//! that composition over THIS ladder's three bodies is the committed
//! `tests/fixtures/oracle_ladder.py`, which reads the reference and prints the
//! table below; the table is its output, unchanged.
//!
//! The ladder's records matched the oracle on the first comparison, down to
//! every payload byte, so the divergence is not in them: it is the one datagram
//! the reference sends BEFORE them, the keepalive. Since 2026-11-07 the ladder
//! also carries the capture's three pre-self-ident records -- the `0x15d` ping
//! (which then repeats every second), `0x40a` and `0x1be` -- so the table below
//! opens with a ping row and the plan's rows start one message later. `maybe_keepalive` fires on the first
//! tick after the V3 answer and then at most once a second, forever, and it is
//! what holds the client's transport open -- the reference's own words are
//! "`CLOCK_SYNC` ~1/s after V3 so `ClientSDK` does not disconnect (4) at 10s of
//! server silence". This session sent the ladder and then nothing.
//!
//! The heartbeat row is separate from `ORACLE_LADDER` because it REPEATS: the
//! reference re-sends it every second, so it is not one of the plan's records.
//! Its bytes come from the reference's own `rep.py::heartbeat_body(tick)`, which
//! reproduces the captured 12-byte `0x15d` record from the tick alone.
//!
//! The keepalive also fixes the ladder's envelope arithmetic: the reference's
//! `next_out_seq` is `inbound + 1` when the V3 answer goes out and the V3 answer
//! does not consume it, so the keepalive takes `inbound + 1` and the first record
//! takes `inbound + 2`. Starting the ladder at `+ 2` while sending no keepalive
//! leaves the reference's `+ 1` datagram missing from the stream.
//!
//! A row is `(envelope, flags, size, numChunks, sequence, relSeq, FNV-1a 64 of
//! the whole datagram)`. The digest covers the payload bytes, the channel and
//! the total datagram length, so a changed payload byte, length or channel fails
//! the row even though the readable columns are only the header's.

use std::fs;

use everfall_wire::Datagram;
use everfall_world::ladder::CapturedRungs;
use everfall_world::{Decision, PostV3Ladder, RepSession};

const CONNECT_REQUEST: &str =
    "80010002a00005030000ffff0000000501880006ffff000000050101880002ffff2006";
const V3_REGISTRATION: &str = "81010005f00205045b000300000000890bd9290000099d0c00090200f00e0113970c0a5d06000000040436303331000000030334303000000002010e00f00501074a6176656c696e00000005073630303431351800f23700085b52455441494c5d00287369673a31373134383230302d616238662d343032302d393934322d3666636338376362663966340e3132372e302e302e313a393030302430300200102d0700702d343030302d380500000f00030200333124310100102d08000b0500040200ff473d616d7a6e312e646576656c6f706572506572736f6e6149642e66633930366330372d343261322d326464312d663539662d39633536636634663231326300103b321137363536313139373936303238373933300024d300116000006ace96fe0400045701520a000001010d002f01015b0003af8620737465616d7c61350200ffffad506135613561";

/// The V3 registration's own envelope sequence (`81 01 00 05`).
const INBOUND_V3_ENV_SEQ: u16 = 5;

/// The reference's server clock for this capture: the value `acceptance_flight`
/// already carries in `everfall-wire`'s parity test.
const CLOCK_MS: u32 = 0x9947_9CB9;

/// The reference's keepalive period (`maybe_keepalive`: `now - last < 1.0`).
const KEEPALIVE_MS: u32 = 1000;

/// The driver's poll (`everfall-netd`'s `IDLE_STEP_MS`).
const POLL_MS: u32 = 20;

/// How long the stream is observed: the ladder plus two keepalive periods.
const WINDOW_MS: u32 = 2200;

/// The wire id of the repeating heartbeat, `PingMsg`.
const HEARTBEAT_WIRE_ID: u32 = 0x15d;

/// The oracle's first heartbeat, the record that opens the plan.
const ORACLE_HEARTBEAT: (u16, u8, u16, u16, u16, u16, u64) =
    (0x0007, 0x21, 13, 1, 1, 1, 0x7bed_54d1_1179_21cc);

/// The oracle's twenty-three planned records: `0x40a`, `0x1be`, the chunked
/// `0x65c`, the body-less `0x651` spawn-point signal, level info and the
/// emitted state bundle.
const ORACLE_LADDER: [(u16, u8, u16, u16, u16, u16, u64); 23] = [
    (0x0008, 0x21, 77, 1, 2, 2, 0xb154_f80f_527f_e273),
    (0x0009, 0x21, 77, 1, 3, 3, 0x758f_4ff3_006b_c4ed),
    (0x000a, 0x25, 1100, 12, 4, 4, 0x0803_58a3_73b4_32f0),
    (0x000b, 0x25, 1100, 12, 5, 5, 0x7ff3_aadf_78a2_eeea),
    (0x000c, 0x25, 1100, 12, 6, 6, 0x3ccb_e092_7a2c_f493),
    (0x000d, 0x25, 1100, 12, 7, 7, 0xc58e_df73_eaf5_5334),
    (0x000e, 0x25, 1100, 12, 8, 8, 0x9439_19eb_0eee_73ce),
    (0x000f, 0x25, 1100, 12, 9, 9, 0xa485_762c_9f5c_28bf),
    (0x0010, 0x25, 1100, 12, 10, 10, 0x650b_e5ba_624e_0f26),
    (0x0011, 0x25, 1100, 12, 11, 11, 0x74bb_0558_1c9e_ce54),
    (0x0012, 0x25, 1100, 12, 12, 12, 0xad7d_472b_8cb3_6abe),
    (0x0013, 0x25, 1100, 12, 13, 13, 0x30f0_60ca_9cf4_c2c2),
    (0x0014, 0x25, 1100, 12, 14, 14, 0x9087_d012_f7d0_42ab),
    (0x0015, 0x25, 608, 12, 15, 15, 0xdc09_c573_9424_2b56),
    // `0x651` `ReceivePlayerSpawnPointMsg`: the typed header alone, five
    // bytes once the record's own length prefix is counted.
    (0x0016, 0x21, 5, 1, 16, 16, 0x477d_bf2d_1d89_7b3d),
    (0x0017, 0x21, 111, 1, 17, 17, 0xa2dc_0180_7dce_c89c),
    (0x0018, 0x25, 1100, 7, 18, 18, 0xd32a_ad1b_3cab_fac0),
    (0x0019, 0x25, 1100, 7, 19, 19, 0x9b44_e848_491c_437e),
    (0x001a, 0x25, 1100, 7, 20, 20, 0xcb2b_59be_e95d_c866),
    (0x001b, 0x25, 1100, 7, 21, 21, 0xb4b2_cc98_3b9f_60d6),
    (0x001c, 0x25, 1100, 7, 22, 22, 0x9001_8414_cc6b_54ed),
    (0x001d, 0x25, 1100, 7, 23, 23, 0x94fc_0a2c_690d_f5b5),
    (0x001e, 0x25, 569, 7, 24, 24, 0xe924_192b_6fd8_d3ff),
];

/// FNV-1a 64 of the oracle's keepalive, the datagram that opens the stream.
const ORACLE_KEEPALIVE: u64 = 0xd683_3eef_32be_c157;

/// FNV-1a 64 over the whole datagram, so one changed payload byte fails the row.
fn fnv1a64(data: &[u8]) -> u64 {
    let mut value: u64 = 0xCBF2_9CE4_8422_2325;
    for byte in data {
        value ^= u64::from(*byte);
        value = value.wrapping_mul(0x100_0000_01B3);
    }
    value
}

/// True when the datagram is one of the repeating `0x15d` heartbeats.
///
/// The heartbeat rides the data channel like the plan's records, so a channel
/// test cannot separate them; its typed header can.
fn is_heartbeat(datagram: &[u8]) -> bool {
    let Ok(decoded) = Datagram::decode(datagram) else {
        return false;
    };
    let Some(record) = decoded.records().first() else {
        return false;
    };
    if record.channel() != 0 {
        return false;
    }
    let payload = record.payload();
    let vlq_len = 1 + payload[0].leading_ones() as usize;
    if payload.len() <= vlq_len + 2 || payload[vlq_len..vlq_len + 2] != [0x00, 0x01] {
        return false;
    }
    let mut reader = everfall_wire::Reader::new(&payload[vlq_len + 2..]);
    matches!(reader.prefix_varint("type"), Ok(id) if id == u64::from(HEARTBEAT_WIRE_ID))
}

/// The decoded view of one datagram: envelope plus its single record's header.
#[derive(Debug, PartialEq, Eq)]
struct Frame {
    envelope: u16,
    flags: u8,
    size: u16,
    channel: u8,
    num_chunks: u16,
    sequence: u16,
    reliable_sequence: u16,
    length: usize,
    digest: u64,
}
fn decode(datagram: &[u8]) -> Frame {
    let envelope = u16::from_be_bytes([datagram[2], datagram[3]]);
    let tail = &datagram[4..];
    let flags = tail[0];
    let size = u16::from_be_bytes([tail[1], tail[2]]);
    let mut cursor = 3;
    let mut channel = 0;
    if flags & 0x20 != 0 {
        channel = tail[cursor];
        cursor += 1;
    }
    let mut num_chunks = 1;
    if flags & 0x04 != 0 {
        num_chunks = u16::from_be_bytes([tail[cursor], tail[cursor + 1]]);
        cursor += 2;
    }
    let sequence = u16::from_be_bytes([tail[cursor], tail[cursor + 1]]);
    cursor += 2;
    let reliable_sequence = u16::from_be_bytes([tail[cursor], tail[cursor + 1]]);
    Frame {
        envelope,
        flags,
        size,
        channel,
        num_chunks,
        sequence,
        reliable_sequence,
        length: datagram.len(),
        digest: fnv1a64(datagram),
    }
}

fn repo_root() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn fixture(relative: &str) -> String {
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

fn wire_body(wire_id: u32) -> Vec<u8> {
    let text = fixture("research/fixtures/wire/wire-bodies.json");
    let needle = format!("\"wire_id\": {wire_id},");
    let at = text.find(&needle).expect("wire id present");
    let key = "\"body\": \"";
    let body_at = text[at..].find(key).expect("body after the id") + key.len() + at;
    let rest = &text[body_at..];
    hex_bytes(&rest[..rest.find('"').expect("closing quote after body")])
}

fn state_bundle_body() -> Vec<u8> {
    let text = fixture("research/fixtures/wire/wire-fixtures.json");
    let needle = "\"source\": \"0x9e_T0x8_R.bin\"";
    let at = text.find(needle).expect("bundle source present");
    let key = "\"body\": \"";
    let body_at = text[..at].rfind(key).expect("body before source") + key.len();
    let rest = &text[body_at..];
    hex_bytes(&rest[..rest.find('"').expect("closing quote after body")])
}

fn number(field: &str) -> u64 {
    field
        .trim_end_matches(',')
        .parse()
        .expect("a number in the measured layout")
}

fn state_extents() -> Vec<(u64, u64, usize)> {
    let text = fixture("research/derived/state-bundle-fragments.json");
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
    out
}

fn ladder() -> PostV3Ladder {
    PostV3Ladder::from_captured(
        &CapturedRungs {
            ping: &wire_body(0x15d),
            calendar_connected: &wire_body(0x40a),
            coatlicue_timing: &wire_body(0x1be),
            self_identification: &wire_body(0x65c),
            level_info: &wire_body(0x663),
            state_bundle: &state_bundle_body(),
        },
        &state_extents(),
        &Decision::Accepted,
    )
    .expect("the captured corpus builds the ladder")
}

/// A session that has answered the connect request and the V3 registration, then
/// polled for `WINDOW_MS`; returns each released datagram with its release time.
fn observed_stream() -> Vec<(u32, Vec<u8>)> {
    let mut session = RepSession::new();
    session.set_ladder(ladder());
    session
        .on_app_data(&hex_bytes(CONNECT_REQUEST), CLOCK_MS)
        .expect("the flight builds");
    session
        .on_app_data(&hex_bytes(V3_REGISTRATION), CLOCK_MS)
        .expect("the V3 answer builds");
    let mut sent = Vec::new();
    for elapsed in (0..=WINDOW_MS).step_by(POLL_MS as usize) {
        for datagram in session.tick(CLOCK_MS + elapsed).expect("tick") {
            sent.push((elapsed, datagram));
        }
    }
    sent
}

#[test]
fn the_whole_post_v3_stream_is_the_reference_stream() {
    // The heartbeat repeats, so it is not one of the plan's rows: its own test
    // below pins it against its own oracle row.
    let stream = observed_stream();
    let digests: Vec<u64> = stream
        .iter()
        .filter(|(_, datagram)| !is_heartbeat(datagram))
        .map(|(_, datagram)| fnv1a64(datagram))
        .collect();
    let mut expected = vec![ORACLE_KEEPALIVE];
    expected.extend(ORACLE_LADDER.iter().map(|row| row.6));
    assert_eq!(
        &digests[..expected.len()],
        &expected[..],
        "the post-V3 stream is the reference's: the keepalive, then the plan's records"
    );
}

#[test]
fn the_reference_keepalive_opens_the_post_v3_stream() {
    let stream = observed_stream();
    let (at, first) = stream.first().expect("the session sends after V3");
    assert_eq!(*at, 0, "the keepalive is due on the first tick after V3");
    assert_eq!(
        first,
        &[
            0x80, 0x01, 0x00, 0x06, // envelope: the reference's next_out_seq = inbound + 1
            0x20, 0x00, 0x05, // flags 0x20 unreliable|data channel, size 5
            0x03, // channel 3, the system channel
            0x00, 0x00, // sequence 0
            0xff, 0xff, // reliable sequence 0xffff, unreliables inherit it
            0x99, 0x47, 0x9c, 0xb9, // the server clock, big-endian
            0x04, // SM_CLOCK_SYNC
        ],
        "the first post-V3 datagram is the reference's SM_CLOCK_SYNC keepalive"
    );
}

#[test]
fn the_ladder_records_are_the_reference_bytes() {
    let stream = observed_stream();
    // The reference's tick order puts the keepalive first, then the heartbeat,
    // then one replay message per tick; `everfall-netd` polls at 20 ms and the
    // plan's offsets are 330 ms + 4 ms per chunk + 30 ms per rung, so the plan is
    // the datagrams between the heartbeat and the keepalives.
    let ladder: Vec<&(u32, Vec<u8>)> = stream
        .iter()
        .filter(|(_, datagram)| decode(datagram).channel == 0 && !is_heartbeat(datagram))
        .collect();
    assert_eq!(
        ladder.len(),
        ORACLE_LADDER.len(),
        "the plan's records are all there"
    );
    for (index, (expected, (at, datagram))) in ORACLE_LADDER.iter().zip(&ladder).enumerate() {
        let (envelope, flags, size, num_chunks, sequence, rel, digest) = *expected;
        let got = decode(datagram);
        assert_eq!(
            got.envelope, envelope,
            "record {index} envelope, at {at} ms"
        );
        assert_eq!(got.flags, flags, "record {index} flag byte, at {at} ms");
        assert_eq!(got.size, size, "record {index} payload size, at {at} ms");
        assert_eq!(got.channel, 0, "record {index} rides the data channel");
        assert_eq!(
            got.num_chunks, num_chunks,
            "record {index} numChunks, at {at} ms"
        );
        assert_eq!(
            got.sequence, sequence,
            "record {index} sequence, at {at} ms"
        );
        assert_eq!(
            got.reliable_sequence, rel,
            "record {index} relative sequence, at {at} ms"
        );
        // Total length: the envelope, the record header and the payload.
        let header = if flags & 0x04 != 0 { 14 } else { 12 };
        assert_eq!(
            got.length,
            header + usize::from(size),
            "record {index} total datagram length, at {at} ms"
        );
        assert_eq!(
            got.digest, digest,
            "record {index} bytes (payload included) differ from the oracle, at {at} ms"
        );
    }
}

#[test]
fn the_heartbeat_is_the_references_ping_and_opens_the_plan() {
    let stream = observed_stream();
    let pings: Vec<&(u32, Vec<u8>)> = stream
        .iter()
        .filter(|(_, datagram)| is_heartbeat(datagram))
        .collect();
    assert_eq!(
        pings.len(),
        2,
        "the heartbeat repeats: one per second inside the window"
    );

    let (at, first) = pings[0];
    let (envelope, flags, size, num_chunks, sequence, rel, digest) = ORACLE_HEARTBEAT;
    let got = decode(first);
    assert_eq!(
        *at, 300,
        "the ping is the first post-V3 record after the keepalive"
    );
    assert_eq!(got.envelope, envelope, "the ping's envelope sequence");
    assert_eq!(got.flags, flags, "the ping rides reliable channel 0");
    assert_eq!(
        got.size, size,
        "the 12-byte ping: the typed header and 8 bytes"
    );
    assert_eq!(got.num_chunks, num_chunks, "the ping is one record");
    assert_eq!(
        got.sequence, sequence,
        "the ping takes the first message seq"
    );
    assert_eq!(got.reliable_sequence, rel);
    assert_eq!(
        got.digest, digest,
        "the ping's bytes are the reference's heartbeat_body output"
    );

    let (second_at, second) = pings[1];
    assert_eq!(
        *second_at,
        KEEPALIVE_MS + 300,
        "the second ping is one heartbeat period after the first"
    );
    let second = decode(second);
    assert_eq!(
        second.size, size,
        "a later ping is the same size: only the 6-byte tick changes"
    );
    assert_ne!(
        second.digest, digest,
        "and its tick advanced, so its bytes are not the captured ones"
    );
}

#[test]
fn the_keepalive_continues_after_the_ladder_drains() {
    let stream = observed_stream();
    // Records are the channel-0 datagrams; everything else is a keepalive.
    let keepalives: Vec<(u32, u16)> = stream
        .iter()
        .filter(|(_, datagram)| decode(datagram).channel == 3)
        .map(|(at, datagram)| (*at, decode(datagram).envelope))
        .collect();
    assert_eq!(
        keepalives,
        vec![
            (0, 0x0006),
            (KEEPALIVE_MS, 0x001f),
            (KEEPALIVE_MS * 2, 0x0021),
        ],
        "one keepalive per period, on the envelope counter the ladder and the heartbeat share"
    );
}

#[test]
fn a_session_with_no_ladder_still_holds_the_transport_open() {
    // `maybe_keepalive` gates on `v3_responded` alone, not on the replay.
    let mut session = RepSession::new();
    session
        .on_app_data(&hex_bytes(CONNECT_REQUEST), CLOCK_MS)
        .expect("the flight builds");
    session
        .on_app_data(&hex_bytes(V3_REGISTRATION), CLOCK_MS)
        .expect("the V3 answer builds");
    let mut envelopes = Vec::new();
    for elapsed in (0..=WINDOW_MS).step_by(POLL_MS as usize) {
        for datagram in session.tick(CLOCK_MS + elapsed).expect("tick") {
            envelopes.push(decode(&datagram).envelope);
        }
    }
    assert_eq!(envelopes, vec![0x0006, 0x0007, 0x0008]);
}

#[test]
fn the_keepalive_sequence_does_not_collide_with_the_v3_answer() {
    // The reference's V3 answer uses `inbound + 1` without consuming
    // `next_out_seq`, so the keepalive legitimately repeats it; the ladder then
    // starts at `inbound + 2`. This pins the arithmetic the ladder inherits.
    let stream = observed_stream();
    let envelopes: Vec<u16> = stream.iter().map(|(_, d)| decode(d).envelope).collect();
    assert_eq!(envelopes[0], INBOUND_V3_ENV_SEQ + 1);
    assert_eq!(envelopes[1], INBOUND_V3_ENV_SEQ + 2);
    assert!(
        envelopes.windows(2).all(|pair| pair[1] == pair[0] + 1),
        "envelope sequences are consecutive: {envelopes:?}"
    );
}
