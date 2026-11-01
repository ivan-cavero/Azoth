//! The measured body of state type index 3857, decoded field by field.
//!
//! The fixture `research/fixtures/wire/state-fragment-3857.hex` is the payload of
//! fragment index 7 of record 1: 1736 bytes that recur byte-identically in five
//! committed bundles, behind the fragment header `16 91 3c` (key 22, type 3857).
//! The layout these tests assert is the one the client's own reader walks —
//! class reader `0x1417b5080`, group reader `0x1417b5330`, then the in-group
//! member readers `0x143a69a10` (activeObjectives) and `0x143a69710`
//! (taskStates) — so a decode that drifts from those readers turns this file
//! red instead of quietly producing a plausible model.
//!
//! These assertions used to pin a hand-written module. They now pin the
//! GENERATED codec, derived from the Atlas cards
//! (`codec.objectives-replicated-state` plus its nested records), so this file
//! is the evidence that the closed vocabulary — not hand-written code — carries
//! the shape.

use everfall_wire::WireError;
use everfall_wire::generated::{
    CodecObjectivesActiveObjective, CodecObjectivesActiveObjectives,
    CodecObjectivesCompletedObjectives, CodecObjectivesReplicatedState,
    CodecObjectivesReplicatedStateEntry, CodecObjectivesReplicatedStateGroup,
    CodecObjectivesTaskState, CodecObjectivesTaskStates, CodecObjectivesTrackedObjective,
    CodecObjectivesTrackedObjectives,
};

const FIXTURE: &str = include_str!("../../../../research/fixtures/wire/state-fragment-3857.hex");

fn fixture_body() -> Vec<u8> {
    let hex: String = FIXTURE
        .lines()
        .filter(|line| !line.trim_start().starts_with('#'))
        .flat_map(|line| line.chars().filter(|c| !c.is_whitespace()))
        .collect();
    assert!(hex.len().is_multiple_of(2), "odd hex length: {}", hex.len());
    (0..hex.len() / 2)
        .map(|index| {
            u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16).expect("hex digit pair")
        })
        .collect()
}

fn body() -> (Vec<u8>, CodecObjectivesReplicatedState) {
    let raw = fixture_body();
    let model = CodecObjectivesReplicatedState::decode(&raw).expect("the measured body decodes");
    (raw, model)
}

fn encode(model: &CodecObjectivesReplicatedState) -> Vec<u8> {
    let mut out = Vec::new();
    model.encode(&mut out).expect("the model encodes");
    out
}

/// The two containers group 1 carries, in registration order.
fn containers(
    model: &CodecObjectivesReplicatedState,
) -> (&CodecObjectivesActiveObjectives, &CodecObjectivesTaskStates) {
    let active: Vec<&CodecObjectivesActiveObjectives> = model.groups[0]
        .entries
        .iter()
        .filter_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::ActiveObjectives(active) => Some(active),
            _ => None,
        })
        .collect();
    let tasks: Vec<&CodecObjectivesTaskStates> = model.groups[0]
        .entries
        .iter()
        .filter_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::TaskStates(tasks) => Some(tasks),
            _ => None,
        })
        .collect();
    assert_eq!(active.len(), 1, "group 1 carries one activeObjectives");
    assert_eq!(tasks.len(), 1, "group 1 carries one taskStates");
    (active[0], tasks[0])
}

#[test]
fn the_fixture_is_the_measured_1736_byte_payload() {
    assert_eq!(fixture_body().len(), 1736);
    assert_eq!(&fixture_body()[..3], &[0x02, 0x18, 0x00]);
}

#[test]
fn the_group_mask_selects_one_group_and_its_entry_mask_two_members() {
    let (_, model) = body();
    assert_eq!(
        model.group_mask, 0x02,
        "bit 1 of the registered member mask"
    );
    assert_eq!(model.groups.len(), 1);
    let group = &model.groups[0];
    assert_eq!(group.entry_mask, 0x18, "bits 3 and 4 of the in-group mask");
    assert_eq!(
        group
            .entries
            .iter()
            .map(|entry| match entry {
                CodecObjectivesReplicatedStateEntry::ActiveObjectives(_) => "activeObjectives",
                CodecObjectivesReplicatedStateEntry::TaskStates(_) => "taskStates",
                CodecObjectivesReplicatedStateEntry::TrackedObjectives(_) => "trackedObjectives",
                CodecObjectivesReplicatedStateEntry::CompletedObjectives(_) =>
                    "completedObjectives",
            })
            .collect::<Vec<_>>(),
        ["activeObjectives", "taskStates"],
        "members 3 and 4 in registration order"
    );
}

#[test]
fn the_two_containers_carry_the_measured_counts_and_delta() {
    let (_, model) = body();
    let (active, tasks) = containers(&model);
    assert_eq!(active.delta, Some(7));
    assert_eq!(active.delta_count, 0);
    assert_eq!(active.elements.len(), 17);
    assert_eq!(tasks.delta, Some(7));
    assert_eq!(tasks.delta_count, 0);
    assert_eq!(tasks.elements.len(), 43);
}

#[test]
fn the_first_elements_hold_the_values_the_readers_walked() {
    let (_, model) = body();
    let (active, tasks) = containers(&model);
    let first: &CodecObjectivesActiveObjective = &active.elements[0];
    assert_eq!(first.u32_a08, 0x4ca4_1ac5);
    assert_eq!(first.u64_a10, 0x2747_fb3e_8054_9fde);
    assert_eq!(first.u32_a18, 0);
    // Sixteen unnamed bytes: the run keeps its Atlas id and width instead of
    // exposing the bytes, so its content is pinned by the round trip below.
    assert_eq!(first.guid_a1c.len(), 16);
    assert_eq!(
        first.guid_a1c.describe(),
        "codec.objectives-active-objective.guid_a1c[16]"
    );
    assert_eq!(first.u64_a38, 0);
    assert_eq!(first.u16_a40, 0);
    assert_eq!(first.u8_a42, 1);
    assert_eq!(first.u8_a43, 0);
    assert_eq!(first.u8_a44, 0);
    assert_eq!(first.u8_a45, 0);
    assert_eq!(first.u64_a50, 0);
    assert_eq!(first.u8_a58, 0);
    assert_eq!(first.index_list, Vec::<u32>::new());
    assert_eq!(
        tasks.elements[0],
        CodecObjectivesTaskState {
            u64_a10: 0x0b4d_0d4f_bf1a_285d,
            u8_a18: 0,
            u32_a1c: 0x4597_e1ed,
            u32_a20: 0,
            u8_a24: 1,
        }
    );
}

#[test]
fn decode_then_encode_returns_the_measured_body_byte_for_byte() {
    let (raw, model) = body();
    assert_eq!(encode(&model), raw);
}

#[test]
fn a_presence_byte_above_one_is_refused_as_the_client_refuses_it() {
    let mut raw = fixture_body();
    // byte 3 is the delta presence flag: 0x01 is 1, 0x02 is out of range.
    raw[3] = 0x02;
    assert!(matches!(
        CodecObjectivesReplicatedState::decode(&raw),
        Err(WireError::NotBoolean { value: 2, .. })
    ));
}

#[test]
fn a_truncated_body_is_refused_instead_of_guessed() {
    let raw = fixture_body();
    assert!(matches!(
        CodecObjectivesReplicatedState::decode(&raw[..raw.len() - 1]),
        Err(WireError::Truncated { .. })
    ));
}

#[test]
fn a_trailing_byte_is_refused_instead_of_ignored() {
    let mut raw = fixture_body();
    raw.push(0);
    assert!(matches!(
        CodecObjectivesReplicatedState::decode(&raw),
        Err(WireError::TrailingBytes { .. })
    ));
}

#[test]
fn a_group_whose_reader_is_not_recovered_is_refused_by_name() {
    let mut raw = fixture_body();
    raw[0] = 0x01;
    assert!(matches!(
        CodecObjectivesReplicatedState::decode(&raw),
        Err(WireError::UnknownPresence {
            what: "group",
            index: 0,
        })
    ));
}

// --- trackedObjectives and completedObjectives: NO LIVE RECORD EXISTS --------
//
// `research/atlas/meanings.md`, "The lab cannot drive server-authoritative
// state", records that the world replays a fixed capture, so no session can
// produce a body with either member's mask bit set. These tests therefore do
// NOT compare against capture bytes. They assert the STRUCTURE of our own
// encoding: the two-level presence mask carries the right bits, a member's
// element count agrees with the elements it carries, and decode(encode(model))
// is the model. The element layout itself is read from the client's reader
// `0x143a69460` and writer `0x142f882a0`, so its evidence is `partial`, never
// `measured`.

/// A state carrying only trackedObjectives and completedObjectives, no capture.
fn tracked_and_completed_model() -> CodecObjectivesReplicatedState {
    CodecObjectivesReplicatedState {
        group_mask: 0b0000_0010,
        groups: vec![CodecObjectivesReplicatedStateGroup {
            entry_mask: 0b0000_0110,
            entries: vec![
                CodecObjectivesReplicatedStateEntry::TrackedObjectives(
                    CodecObjectivesTrackedObjectives {
                        elements: vec![
                            CodecObjectivesTrackedObjective {
                                id: 3,
                                delta: None,
                                value: 0x11,
                            },
                            CodecObjectivesTrackedObjective {
                                id: 7,
                                delta: Some(9),
                                value: 0x22,
                            },
                        ],
                    },
                ),
                CodecObjectivesReplicatedStateEntry::CompletedObjectives(
                    CodecObjectivesCompletedObjectives {
                        elements: vec![CodecObjectivesTrackedObjective {
                            id: 1,
                            delta: Some(2),
                            value: 0x33,
                        }],
                    },
                ),
            ],
        }],
    }
}

fn encode_model(model: &CodecObjectivesReplicatedState) -> Vec<u8> {
    let mut out = Vec::new();
    model.encode(&mut out).expect("our own encoding succeeds");
    out
}

fn tracked(model: &CodecObjectivesReplicatedState) -> &CodecObjectivesTrackedObjectives {
    model.groups[0]
        .entries
        .iter()
        .find_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::TrackedObjectives(value) => Some(value),
            _ => None,
        })
        .expect("the model carries trackedObjectives")
}

fn completed(model: &CodecObjectivesReplicatedState) -> &CodecObjectivesCompletedObjectives {
    model.groups[0]
        .entries
        .iter()
        .find_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::CompletedObjectives(value) => Some(value),
            _ => None,
        })
        .expect("the model carries completedObjectives")
}

#[test]
fn no_live_record_so_tracked_and_completed_round_trip_our_own_encoding() {
    let model = tracked_and_completed_model();
    let raw = encode_model(&model);
    let decoded = CodecObjectivesReplicatedState::decode(&raw).expect("our own body decodes");
    assert_eq!(decoded, model);
}

#[test]
fn the_presence_mask_carries_the_tracked_and_completed_bits() {
    let raw = encode_model(&tracked_and_completed_model());
    assert_eq!(raw[0], 0b0000_0010, "group 1 is present");
    assert_eq!(raw[1], 0b0000_0110, "in-group members 1 and 2 are present");
    let decoded = CodecObjectivesReplicatedState::decode(&raw).expect("our own body decodes");
    assert_eq!(decoded.groups[0].entry_mask, 0b0000_0110);
}

#[test]
fn a_tracked_element_count_agrees_with_the_elements_it_carries() {
    let raw = encode_model(&tracked_and_completed_model());
    // [group_mask][entry_mask], then trackedObjectives is member 1, first.
    assert_eq!(raw[2], 2, "the tracked element count");
    assert_eq!(
        raw[3], 0b0000_0011,
        "both tracked elements declare their u64"
    );
    let decoded = CodecObjectivesReplicatedState::decode(&raw).expect("our own body decodes");
    assert_eq!(tracked(&decoded).elements.len(), 2);
    assert_eq!(
        u8::try_from(tracked(&decoded).elements.len()).unwrap(),
        raw[2]
    );
    assert_eq!(completed(&decoded).elements.len(), 1);
}

#[test]
fn nine_elements_carry_one_mask_byte_per_chunk_of_eight() {
    let elements = (0..9)
        .map(|id| CodecObjectivesTrackedObjective {
            id,
            delta: None,
            value: id,
        })
        .collect();
    let model = CodecObjectivesReplicatedState {
        group_mask: 0b0000_0010,
        groups: vec![CodecObjectivesReplicatedStateGroup {
            entry_mask: 0b0000_0010,
            entries: vec![CodecObjectivesReplicatedStateEntry::TrackedObjectives(
                CodecObjectivesTrackedObjectives { elements },
            )],
        }],
    };
    let raw = encode_model(&model);
    // Each element is id (1 byte) + delta flag (1) + u64 (8) = 10 bytes.
    // [group][entry][count 9][mask 0xff][8 x 10][mask 0x01][1 x 10]
    assert_eq!(raw.len(), 3 + 1 + 80 + 1 + 10);
    assert_eq!(raw[2], 9, "the element count");
    assert_eq!(raw[3], 0xFF, "all eight elements of the first chunk");
    assert_eq!(raw[84], 0x01, "the one element of the second chunk");
    let decoded = CodecObjectivesReplicatedState::decode(&raw).expect("our own body decodes");
    assert_eq!(tracked(&decoded).elements.len(), 9);
}

#[test]
fn a_clear_element_mask_bit_is_refused_not_guessed() {
    let mut raw = encode_model(&tracked_and_completed_model());
    assert_eq!(raw[3], 0b0000_0011);
    raw[3] = 0b0000_0001;
    assert!(matches!(
        CodecObjectivesReplicatedState::decode(&raw),
        Err(WireError::UnknownPresence {
            what: "elements",
            ..
        })
    ));
}

#[test]
fn a_delta_presence_byte_above_one_is_refused_as_the_client_refuses_it() {
    let mut raw = encode_model(&tracked_and_completed_model());
    // Element 0 has no delta: raw[4] is its id, raw[5] is its presence flag.
    assert_eq!(raw[4], 3);
    assert_eq!(raw[5], 0);
    raw[5] = 2;
    assert!(matches!(
        CodecObjectivesReplicatedState::decode(&raw),
        Err(WireError::NotBoolean { value: 2, .. })
    ));
}
