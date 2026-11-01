//! A state bundle produced from a DECISION, not from the recording.
//!
//! Every unit before this one made the server consume traffic. This file is the
//! other direction: one real bundle (`0x9e_T0x8_R.bin`, 7,167 bytes, record 1,
//! nine fragments) is decoded, the simulation decides a request that drops an
//! objective it has no definition for, and the world assembles the bytes it would
//! emit. The claims checked here are the ones that make the emission meaningful:
//!
//! 1. the emitted bundle is well formed under the documented framing -- it parses
//!    back into the same typed records with only the decided change, and
//!    re-encodes to the same bytes;
//! 2. its bytes are identical to the recorded bundle everywhere the decision did
//!    not change data, and the changed span is exactly one count prefix byte plus
//!    one deleted 56-byte element;
//! 3. six of the nine fragments (keys 55, 19, 9, 74, 22 and 44) are AUTHORED
//!    from typed values rather than replayed, so 6,546 of the record's 7,126
//!    payload bytes come from the server's own model; the three that remain are
//!    named;
//! 4. the chunking respects the measured 1,100-byte working cut, which exists
//!    because 1,200 bytes is the datagram ceiling.
//!
//! Nothing here opens a socket. There is no carrier layer yet, so this file
//! proves the bundle, not the send.

use std::fs;
use std::ops::Range;
use std::path::{Path, PathBuf};

use everfall_sim::{ActorId, Decision, Dropped, ObjectiveId, ObjectiveRequest, Sim};
use everfall_wire::generated::{
    CodecObjectivesActiveObjectives, CodecObjectivesReplicatedState,
    CodecObjectivesReplicatedStateEntry, CodecObjectivesTaskStates,
};
use everfall_wire::{
    Bundle, CARRIER_HEADROOM, CHUNK_LIMIT, DATAGRAM_CEILING, FragmentExtent, LocalPlayerState,
};
use everfall_world::emit;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn read(relative: &str) -> String {
    let path = repo_root().join(Path::new(relative));
    fs::read_to_string(&path).expect("read the committed fixture file")
}

fn hex_bytes(hex: &str) -> Vec<u8> {
    assert!(hex.len().is_multiple_of(2), "odd hex length: {}", hex.len());
    (0..hex.len() / 2)
        .map(|index| {
            u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16).expect("hex digit pair")
        })
        .collect()
}

fn bundle_body(source: &str) -> Vec<u8> {
    let text = read("research/fixtures/wire/wire-fixtures.json");
    let needle = format!("\"source\": \"{source}\"");
    let entry_at = text.find(&needle).expect("bundle source present");
    let body_key = "\"body\": \"";
    let body_at = text[..entry_at]
        .rfind(body_key)
        .expect("body before source")
        + body_key.len();
    let rest = &text[body_at..];
    let end = rest.find('"').expect("closing quote after body");
    hex_bytes(&rest[..end])
}

fn measured_extents() -> Vec<FragmentExtent> {
    let text = read("research/derived/state-bundle-fragments.json");
    let mut out: Vec<FragmentExtent> = Vec::new();
    let mut current: Option<FragmentExtent> = None;
    for line in text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("\"key\": ") {
            if let Some(done) = current.take() {
                out.push(done);
            }
            current = Some(FragmentExtent {
                key: number(rest),
                type_index: 0,
                payload_len: 0,
            });
        } else if let (Some(rest), Some(slot)) =
            (line.strip_prefix("\"type_index\": "), current.as_mut())
        {
            slot.type_index = number(rest);
        } else if let (Some(rest), Some(slot)) =
            (line.strip_prefix("\"payload_length\": "), current.as_mut())
        {
            slot.payload_len = number(rest) as usize;
        }
    }
    if let Some(done) = current {
        out.push(done);
    }
    assert_eq!(out.len(), 9, "the measured record carries nine fragments");
    out
}

fn number(field: &str) -> u64 {
    field
        .trim_end_matches(',')
        .parse()
        .expect("a number in the measured layout")
}

/// A decision the simulation actually makes: one id it cannot resolve is dropped
/// from the request, so the answer is a correction and not an acceptance.
fn correction() -> Decision {
    let known = ObjectiveId::new(0x0b4d_0d4f_bf1a_285d);
    let unknown = ObjectiveId::new(0xdead_beef);
    let mut sim = Sim::new([known]);
    let decision = sim.decide(
        ActorId::new(1),
        ObjectiveRequest::SetTrackedObjectives(vec![known, unknown]),
    );
    assert_eq!(
        decision,
        Decision::Corrected(Dropped {
            duplicates: 0,
            unknown: 1
        })
    );
    decision
}

fn containers(
    state: &CodecObjectivesReplicatedState,
) -> (&CodecObjectivesActiveObjectives, &CodecObjectivesTaskStates) {
    let entries = &state.groups[0].entries;
    let active = entries
        .iter()
        .find_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::ActiveObjectives(active) => Some(active),
            _ => None,
        })
        .expect("group 1 carries activeObjectives");
    let tasks = entries
        .iter()
        .find_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::TaskStates(tasks) => Some(tasks),
            _ => None,
        })
        .expect("group 1 carries taskStates");
    (active, tasks)
}

fn first_divergence(left: &[u8], right: &[u8]) -> Option<usize> {
    let shorter = left.len().min(right.len());
    if let Some(index) = (0..shorter).find(|index| left[*index] != right[*index]) {
        return Some(index);
    }
    (left.len() != right.len()).then_some(shorter)
}

#[test]
fn the_emitted_bundle_is_well_formed_and_carries_the_decision() {
    let emission =
        emit(recorded_bundle(), &correction()).expect("the world assembles the emission");
    assert_eq!(emission.removed(), 1);

    let produced = emission.encode().expect("the emission encodes");
    let extents = emission.extents().expect("the emission states its extents");
    let redecoded = Bundle::<LocalPlayerState>::decode(&produced, &extents)
        .expect("the emitted bytes parse under the documented framing");

    assert_eq!(redecoded.replication_seq(), 0x24);
    assert_eq!(redecoded.records().len(), 1);
    assert_eq!(redecoded.records()[0].record_id(), 1);
    assert_eq!(redecoded.records()[0].fragments().len(), 9);

    let component = redecoded
        .components()
        .find_map(LocalPlayerState::objectives)
        .expect("the bundle carries the objectives component");
    let (active, tasks) = containers(component);
    assert_eq!(
        active.elements.len(),
        16,
        "the decision dropped one objective"
    );
    assert_eq!(active.delta, Some(7), "the delta is not the decision");
    assert_eq!(tasks.elements.len(), 43, "task states are untouched");

    // Re-encoding the parsed emission must close on itself: no hidden state.
    assert_eq!(
        redecoded.encode().expect("re-encodes"),
        produced,
        "the emission is not stable under its own framing"
    );
    assert_eq!(&produced[..3], &[0x00, 0x01, 0x08], "marker and type");
    assert_eq!(produced.len(), 7167 - 56, "one 56-byte element gone");
}

#[test]
fn the_emitted_bundle_differs_only_where_the_decision_changed_data() {
    let recorded = bundle_body("0x9e_T0x8_R.bin");
    let emission = emit(recorded_bundle(), &correction()).expect("assembles");
    let produced = emission.encode().expect("encodes");

    // The framing owes the decision one edit here: the payload length varint must
    // say 7098 instead of 7154, so it is RE-ENCODED rather than overwritten. That
    // is why the first divergent byte is 11, not 5407: a raw byte write would
    // have left a two-byte varint claiming 7154 over a 7098-byte payload.
    assert_eq!(first_divergence(&produced, &recorded), Some(11));
    assert_eq!(&recorded[11..13], &[0xb2, 0x6f], "the recorded 7154");
    assert_eq!(&produced[11..13], &[0xba, 0x6e], "the emitted 7098");

    // Everything the decision did not touch: marker, type, prologue, record
    // header and the eight unrecovered fragments up to the component's count.
    assert_eq!(&produced[..11], &recorded[..11], "marker and prologue");
    assert_eq!(
        &produced[13..5_407],
        &recorded[13..5_407],
        "record header and payload up to the count"
    );

    // The decided byte: the activeObjectives snapshot count, 17 -> 16.
    assert_eq!(recorded[5_407], 0x11, "17 elements recorded");
    assert_eq!(produced[5_407], 0x10, "16 elements emitted");

    // The deleted element is the LAST one, so the 16 survivors are byte-identical
    // in place and only what follows them shifts down by 56 bytes.
    let survivors = 16 * 56;
    assert_eq!(
        &produced[5_408..5_408 + survivors],
        &recorded[5_408..5_408 + survivors],
        "the surviving elements are unchanged"
    );
    assert_eq!(
        &produced[5_408 + survivors..],
        &recorded[5_408 + survivors + 56..],
        "everything after the deleted element is the recorded bytes, shifted"
    );
    assert_eq!(
        recorded.len() - produced.len(),
        56,
        "the only length change is the deleted element"
    );
}

#[test]
fn a_rejection_emits_the_recorded_bundle_unchanged() {
    let recorded = bundle_body("0x9e_T0x8_R.bin");
    let mut sim = Sim::new((0..9).map(ObjectiveId::new));
    let rejected = sim.decide(
        ActorId::new(1),
        ObjectiveRequest::SetTrackedObjectives((0..9).map(ObjectiveId::new).collect()),
    );
    assert!(matches!(rejected, Decision::Rejected(_)));

    let emission = emit(recorded_bundle(), &rejected).expect("assembles");
    assert_eq!(emission.removed(), 0);
    assert_eq!(emission.encode().expect("encodes"), recorded);
}

#[test]
fn the_emission_authors_the_typed_fragments_and_names_the_replayed_ones() {
    // A rejection changes nothing, so the census is the record's own.
    let mut sim = Sim::new((0..9).map(ObjectiveId::new));
    let rejected = sim.decide(
        ActorId::new(1),
        ObjectiveRequest::SetTrackedObjectives((0..9).map(ObjectiveId::new).collect()),
    );
    assert!(matches!(rejected, Decision::Rejected(_)));

    let emission = emit(recorded_bundle(), &rejected).expect("assembles");
    assert_eq!(
        emission.state().components().count(),
        6,
        "keys 55, 19, 9, 74, 22 and 44 are typed components"
    );

    // The anti-emulator KPI, from the bytes rather than from a comment: 3892
    // (type 3133) + 1736 (3857) + 834 (5691) + 3 (3935) + 55 (4176) + 26 (4236)
    // of 7126 payload bytes.
    assert_eq!(emission.authored_payload_bytes().expect("authors"), 6_546);
    assert_eq!(emission.total_payload_bytes().expect("total"), 7_126);

    // Every fragment the server cannot author, named with its type index and its
    // recorded width, in wire order.
    assert_eq!(
        emission.replayed_fragments(),
        [(73, 5_606, 337), (72, 5_485, 194), (16, 11, 49)]
    );

    // The decided path authors the objectives fragment at its new width: the
    // decision deleted one 56-byte element, so 1736 - 56 = 1680.
    let decided = emit(recorded_bundle(), &correction()).expect("assembles");
    assert_eq!(
        decided.authored_payload_bytes().expect("authors"),
        6_490,
        "3892 + 1680 + 834 + 3 + 55 + 26"
    );
    assert_eq!(decided.total_payload_bytes().expect("total"), 7_070);
}

#[test]
fn the_emitted_bundle_chunks_under_the_measured_cut() {
    let emission = emit(recorded_bundle(), &correction()).expect("assembles");
    let produced = emission.encode().expect("encodes");
    assert!(
        produced.len() > CHUNK_LIMIT,
        "a {} byte bundle cannot ride one chunk",
        produced.len()
    );

    let chunks: Vec<Range<usize>> = emission.chunk_ranges().expect("chunks");
    assert_eq!(chunks.len(), 7, "ceil(7111 / 1100)");
    assert_eq!(chunks[0], 0..1_100);
    assert_eq!(chunks[6], 6_600..7_111, "the last chunk is the remainder");

    let mut covered = 0;
    for (index, chunk) in chunks.iter().enumerate() {
        assert_eq!(
            chunk.start, covered,
            "chunk {index} starts where the last ended"
        );
        assert!(
            chunk.len() <= CHUNK_LIMIT,
            "chunk {index} is {} bytes, over the 1,100-byte cut",
            chunk.len()
        );
        assert!(
            chunk.len() + CARRIER_HEADROOM <= DATAGRAM_CEILING,
            "chunk {index} plus the carrier leaves no room under the 1,200-byte ceiling"
        );
        covered = chunk.end;
    }
    assert_eq!(covered, produced.len(), "the chunks cover the whole bundle");
}

fn recorded_bundle() -> Bundle<LocalPlayerState> {
    let body = bundle_body("0x9e_T0x8_R.bin");
    Bundle::decode(&body, &measured_extents()).expect("the measured bundle decodes")
}
