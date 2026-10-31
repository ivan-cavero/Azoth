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

use everfall_wire::objectives_state::{
    ActiveObjective, ActiveObjectives, ObjectivesStateBody, StateEntry, StateError, TaskState,
    TaskStates, decode, encode,
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

fn body() -> (Vec<u8>, ObjectivesStateBody) {
    let raw = fixture_body();
    let model = decode(&raw).expect("the measured body decodes");
    (raw, model)
}

/// The two containers group 1 carries, in registration order.
fn containers(model: &ObjectivesStateBody) -> (&ActiveObjectives, &TaskStates) {
    let active: Vec<&ActiveObjectives> = model.groups[0]
        .entries
        .iter()
        .filter_map(|entry| match entry {
            StateEntry::ActiveObjectives(active) => Some(active),
            StateEntry::TaskStates(_) => None,
        })
        .collect();
    let tasks: Vec<&TaskStates> = model.groups[0]
        .entries
        .iter()
        .filter_map(|entry| match entry {
            StateEntry::TaskStates(tasks) => Some(tasks),
            StateEntry::ActiveObjectives(_) => None,
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
                StateEntry::ActiveObjectives(_) => "activeObjectives",
                StateEntry::TaskStates(_) => "taskStates",
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
    assert_eq!(active.elements.len(), 17);
    assert_eq!(tasks.delta, Some(7));
    assert_eq!(tasks.elements.len(), 43);
}

#[test]
fn the_first_elements_hold_the_values_the_readers_walked() {
    let (_, model) = body();
    let (active, tasks) = containers(&model);
    assert_eq!(
        active.elements[0],
        ActiveObjective {
            u32_a08: 0x4ca4_1ac5,
            u64_a10: 0x2747_fb3e_8054_9fde,
            u32_a18: 0,
            guid_a1c: [0; 16],
            u64_a38: 0,
            u16_a40: 0,
            u8_a42: 1,
            u8_a43: 0,
            u8_a44: 0,
            u8_a45: 0,
            u64_a50: 0,
            u8_a58: 0,
            index_list: Vec::new(),
        }
    );
    assert_eq!(
        tasks.elements[0],
        TaskState {
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
    assert_eq!(encode(&model).expect("the model encodes"), raw);
}

#[test]
fn a_presence_byte_above_one_is_refused_as_the_client_refuses_it() {
    let mut raw = fixture_body();
    // byte 3 is the delta presence flag: 0x01 is 1, 0x02 is out of range.
    raw[3] = 0x02;
    assert!(matches!(
        decode(&raw),
        Err(StateError::NotBoolean { value: 2, .. })
    ));
}

#[test]
fn a_truncated_body_is_refused_instead_of_guessed() {
    let raw = fixture_body();
    assert!(matches!(
        decode(&raw[..raw.len() - 1]),
        Err(StateError::Wire(_))
    ));
}

#[test]
fn a_trailing_byte_is_refused_instead_of_ignored() {
    let mut raw = fixture_body();
    raw.push(0);
    assert!(matches!(decode(&raw), Err(StateError::Wire(_))));
}

#[test]
fn a_group_whose_reader_is_not_recovered_is_refused_by_name() {
    let mut raw = fixture_body();
    raw[0] = 0x01;
    assert!(matches!(
        decode(&raw),
        Err(StateError::Unsupported {
            what: "state group",
            value: 0,
        })
    ));
}
