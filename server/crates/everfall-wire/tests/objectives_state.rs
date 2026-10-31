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
    CodecObjectivesReplicatedState, CodecObjectivesReplicatedStateEntry, CodecObjectivesTaskState,
    CodecObjectivesTaskStates,
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
            CodecObjectivesReplicatedStateEntry::TaskStates(_) => None,
        })
        .collect();
    let tasks: Vec<&CodecObjectivesTaskStates> = model.groups[0]
        .entries
        .iter()
        .filter_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::TaskStates(tasks) => Some(tasks),
            CodecObjectivesReplicatedStateEntry::ActiveObjectives(_) => None,
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
