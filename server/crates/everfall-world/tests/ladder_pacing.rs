//! The ladder under the driver's coarse poll.
//!
//! The DTLS driver polls the session on a ~20 ms step. Before the scheduler
//! re-armed from the send time it swept a deadline and released every overdue
//! record in one call, so a 20 ms poll sent a whole rung's chunks back to back.
//! This test pins the property the live run depends on: whatever the poll
//! cadence, one poll never releases more than one datagram, and the chunks of a
//! message stay separated in time.

use std::fs;
use std::path::PathBuf;

use everfall_world::Decision;
use everfall_world::ladder::{CHUNK_GAP_MS, PostV3Ladder};
use everfall_world::rep::RepSession;

const CONNECT_REQUEST: &str =
    "80010002a00005030000ffff0000000501880006ffff000000050101880002ffff2006";
const V3_REGISTRATION: &str = "81010005f00205045b000300000000890bd9290000099d0c00090200f00e0113970c0a5d06000000040436303331000000030334303000000002010e00f00501074a6176656c696e00000005073630303431351800f23700085b52455441494c5d00287369673a31373134383230302d616238662d343032302d393934322d3666636338376362663966340e3132372e302e302e313a393030302430300200102d0700702d343030302d380500000f00030200333124310100102d08000b0500040200ff473d616d7a6e312e646576656c6f706572506572736f6e6149642e66633930366330372d343261322d326464312d663539662d39633536636634663231326300103b321137363536313139373936303238373933300024d300116000006ace96fe0400045701520a000001010d002f01015b0003af8620737465616d7c61350200ffffad506135613561";

const POLL_MS: u32 = 20;

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

fn wire_body(wire_id: u32) -> Vec<u8> {
    let text = read("research/fixtures/wire/wire-bodies.json");
    let needle = format!("\"wire_id\": {wire_id},");
    let at = text.find(&needle).expect("wire id present");
    let key = "\"body\": \"";
    let body_at = text[at..].find(key).expect("body after the id") + key.len() + at;
    let rest = &text[body_at..];
    let end = rest.find('"').expect("closing quote after body");
    hex_bytes(&rest[..end])
}

fn state_bundle_body() -> Vec<u8> {
    let text = read("research/fixtures/wire/wire-fixtures.json");
    let needle = "\"source\": \"0x9e_T0x8_R.bin\"";
    let at = text.find(needle).expect("bundle source present");
    let key = "\"body\": \"";
    let body_at = text[..at].rfind(key).expect("body before source") + key.len();
    let rest = &text[body_at..];
    let end = rest.find('"').expect("closing quote after body");
    hex_bytes(&rest[..end])
}

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
        &wire_body(0x65c),
        &wire_body(0x663),
        &state_bundle_body(),
        &state_extents(),
        &Decision::Accepted,
    )
    .expect("the captured corpus builds the ladder")
}

#[test]
fn a_coarse_poll_never_batches_the_ladder() {
    let clock = 0x9947_9CB9;
    let mut session = RepSession::new();
    session.set_ladder(ladder());
    session
        .on_app_data(&hex_bytes(CONNECT_REQUEST), clock)
        .expect("flight builds");
    session
        .on_app_data(&hex_bytes(V3_REGISTRATION), clock)
        .expect("registration builds");

    let mut sent_at: Vec<u32> = Vec::new();
    for elapsed in (0..=1_000).step_by(POLL_MS as usize) {
        let datagrams = session.tick(clock + elapsed).expect("tick");
        assert!(
            datagrams.len() <= 1,
            "the {} ms poll released {} datagrams at {elapsed} ms",
            POLL_MS,
            datagrams.len()
        );
        for _ in datagrams {
            sent_at.push(elapsed);
        }
    }

    assert!(sent_at.len() > 1, "the ladder drains under the coarse poll");
    let gaps: Vec<u32> = sent_at.windows(2).map(|pair| pair[1] - pair[0]).collect();
    assert!(
        gaps.iter().all(|&gap| gap >= CHUNK_GAP_MS),
        "no two records leave within a chunk gap: {gaps:?}"
    );
}
