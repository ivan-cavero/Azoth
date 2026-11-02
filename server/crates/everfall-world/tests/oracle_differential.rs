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
//! The ladder's twenty records matched the oracle on the first comparison, down
//! to every payload byte, so the divergence is not in them: it is the one
//! datagram the reference sends BEFORE them. `maybe_keepalive` fires on the first
//! tick after the V3 answer and then at most once a second, forever, and it is
//! what holds the client's transport open -- the reference's own words are
//! "`CLOCK_SYNC` ~1/s after V3 so `ClientSDK` does not disconnect (4) at 10s of
//! server silence". This session sent the ladder and then nothing.
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

/// The oracle's twenty ladder records.
const ORACLE_LADDER: [(u16, u8, u16, u16, u16, u16, u64); 20] = [
    (0x0007, 0x25, 1100, 12, 1, 1, 0xc003_ead1_9efb_455f),
    (0x0008, 0x25, 1100, 12, 2, 2, 0x99f8_c23f_d6c7_650f),
    (0x0009, 0x25, 1100, 12, 3, 3, 0x7dd3_9db5_da92_3600),
    (0x000a, 0x25, 1100, 12, 4, 4, 0x5e1b_d427_f25c_af99),
    (0x000b, 0x25, 1100, 12, 5, 5, 0x83de_e93e_4c9f_c481),
    (0x000c, 0x25, 1100, 12, 6, 6, 0x6604_bd78_018a_075a),
    (0x000d, 0x25, 1100, 12, 7, 7, 0xab9f_238f_3599_4685),
    (0x000e, 0x25, 1100, 12, 8, 8, 0x0462_e778_fb1f_e719),
    (0x000f, 0x25, 1100, 12, 9, 9, 0x5bb6_482f_63e9_3891),
    (0x0010, 0x25, 1100, 12, 10, 10, 0x9ff4_2e65_8060_0707),
    (0x0011, 0x25, 1100, 12, 11, 11, 0xe096_a5db_b7c5_f1f8),
    (0x0012, 0x25, 608, 12, 12, 12, 0x92af_bb69_2534_9e33),
    (0x0013, 0x21, 111, 1, 13, 13, 0x1ea9_7a51_2359_62d0),
    (0x0014, 0x25, 1100, 7, 14, 14, 0xf512_8529_6ad3_1c7c),
    (0x0015, 0x25, 1100, 7, 15, 15, 0x1e7a_88a0_4dce_096a),
    (0x0016, 0x25, 1100, 7, 16, 16, 0x817a_ad46_a3de_77fa),
    (0x0017, 0x25, 1100, 7, 17, 17, 0xbeeb_5c99_82d1_2502),
    (0x0018, 0x25, 1100, 7, 18, 18, 0x5189_8e66_9d7c_e6e9),
    (0x0019, 0x25, 1100, 7, 19, 19, 0xbf7a_4e1b_333f_a579),
    (0x001a, 0x25, 569, 7, 20, 20, 0x7465_48a8_8aa5_4213),
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
        &wire_body(0x65c),
        &wire_body(0x663),
        &state_bundle_body(),
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
    let stream = observed_stream();
    let digests: Vec<u64> = stream
        .iter()
        .map(|(_, datagram)| fnv1a64(datagram))
        .collect();
    let mut expected = vec![ORACLE_KEEPALIVE];
    expected.extend(ORACLE_LADDER.iter().map(|row| row.6));
    assert_eq!(
        &digests[..expected.len()],
        &expected[..],
        "the post-V3 stream is the reference's: the keepalive, then the twenty records"
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
fn the_twenty_ladder_records_are_the_reference_bytes() {
    let stream = observed_stream();
    // The reference's tick order puts the keepalive first, then one replay
    // message per tick; `everfall-netd` polls at 20 ms and the plan's offsets
    // are 300 ms + 4 ms per chunk + 30 ms per rung, so the ladder is the twenty
    // datagrams after the first keepalive.
    let ladder: Vec<&(u32, Vec<u8>)> = stream
        .iter()
        .filter(|(_, datagram)| decode(datagram).channel == 0)
        .collect();
    assert_eq!(ladder.len(), ORACLE_LADDER.len(), "twenty records");
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
            (KEEPALIVE_MS, 0x001b),
            (KEEPALIVE_MS * 2, 0x001c),
        ],
        "one keepalive per period, on the envelope counter the ladder shares"
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
