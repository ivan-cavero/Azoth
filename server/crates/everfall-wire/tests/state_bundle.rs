//! The type-0x08 state bundle: decode one real body, then reproduce it.
//!
//! The body is `0x9e_T0x8_R.bin` from `research/fixtures/wire/wire-fixtures.json`
//! -- 7,167 bytes, replication counter 0x24, one record (id 1, nine fragments).
//! The fragment boundaries are NOT derivable from the bytes (a fragment is
//! `[varint key][varint type index][payload]` with no length field), so they come
//! from `research/derived/state-bundle-fragments.json`, where the client probe
//! recorded them. This test feeds the framing those measured widths and then
//! checks the framing agrees with what the bytes and the generated codec consume,
//! so a wrong model fails here instead of silently re-emitting its own guess.
//!
//! The arbitration is byte equality: decode the body into typed records, encode
//! it back, and require the 7,167 bytes to come out identical.

use std::fs;
use std::path::{Path, PathBuf};

use everfall_wire::generated::{
    CodecEntitlementReplicatedStateEntry, CodecObjectivesActiveObjectives,
    CodecObjectivesReplicatedState, CodecObjectivesReplicatedStateEntry, CodecObjectivesTaskStates,
    CodecPlayerComponentReplicatedStateEntry, CodecSeasonsRewardsTrackedStatReplicatedState,
    CodecSeasonsRewardsTrackedStatReplicatedStateEntry, CodecSocialReplicatedState,
    CodecSocialReplicatedStateEntry, CodecStatusEffectsComponentReplicatedState,
    CodecStatusEffectsComponentReplicatedStateEntry, CodecTransmogReplicatedStateEntry,
};
use everfall_wire::{
    Bundle, BundleError, Fragment, FragmentExtent, FragmentPayload, LocalPlayerState, PROLOGUE_TAIL,
};

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

/// The committed body of one state bundle, keyed by the datagram it rode in.
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

/// The fragment extents the client probe measured for record 1.
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

fn first_divergence(left: &[u8], right: &[u8]) -> Option<usize> {
    let shorter = left.len().min(right.len());
    if let Some(index) = (0..shorter).find(|index| left[*index] != right[*index]) {
        return Some(index);
    }
    (left.len() != right.len()).then_some(shorter)
}

fn byte_at(bytes: &[u8], index: usize) -> String {
    bytes
        .get(index)
        .map_or_else(|| "past end".to_owned(), |byte| format!("{byte:#04x}"))
}

/// Assert byte equality, reporting the first divergent offset when it fails.
fn assert_same_bytes(produced: &[u8], expected: &[u8]) {
    let divergence = first_divergence(produced, expected);
    let detail = divergence.map(|index| {
        format!(
            "at {index}: produced {}, expected {}",
            byte_at(produced, index),
            byte_at(expected, index)
        )
    });
    assert!(
        divergence.is_none(),
        "first divergence {detail:?} (produced {} bytes, expected {} bytes)",
        produced.len(),
        expected.len()
    );
}

fn decode() -> (Vec<u8>, Bundle<LocalPlayerState>) {
    let body = bundle_body("0x9e_T0x8_R.bin");
    let bundle = Bundle::decode(&body, &measured_extents()).expect("the measured bundle decodes");
    (body, bundle)
}

/// The two containers the objectives group 1 carries, in registration order.
fn containers(
    state: &CodecObjectivesReplicatedState,
) -> (&CodecObjectivesActiveObjectives, &CodecObjectivesTaskStates) {
    let entry = &state.groups[0].entries;
    let active = entry
        .iter()
        .find_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::ActiveObjectives(active) => Some(active),
            _ => None,
        })
        .expect("group 1 carries activeObjectives");
    let tasks = entry
        .iter()
        .find_map(|entry| match entry {
            CodecObjectivesReplicatedStateEntry::TaskStates(tasks) => Some(tasks),
            _ => None,
        })
        .expect("group 1 carries taskStates");
    (active, tasks)
}

#[test]
fn the_measured_bundle_decodes_into_typed_fragments() {
    let (body, bundle) = decode();
    assert_eq!(body.len(), 7167, "the committed body is 7,167 bytes");
    assert_eq!(bundle.replication_seq(), 0x24);
    assert_eq!(bundle.records().len(), 1);

    let record = &bundle.records()[0];
    assert_eq!(record.record_id(), 1, "record 1 is the local player slot");
    assert_eq!(record.fragments().len(), 9, "nine fragments");

    let keys: Vec<u64> = record.fragments().iter().map(Fragment::key).collect();
    assert_eq!(keys, [55, 19, 73, 9, 72, 74, 16, 22, 44]);

    let types: Vec<u64> = record
        .fragments()
        .iter()
        .map(|f| f.payload().type_index())
        .collect();
    assert_eq!(types, [4176, 3133, 5606, 3935, 5485, 5691, 11, 3857, 4236]);
}

#[test]
fn seven_fragments_are_typed_components_and_two_are_replayed_runs() {
    let (_, bundle) = decode();
    let record = &bundle.records()[0];

    let typed: Vec<u64> = record
        .fragments()
        .iter()
        .filter(|fragment| matches!(fragment.payload(), FragmentPayload::Component(_)))
        .map(Fragment::key)
        .collect();
    assert_eq!(
        typed,
        [55, 19, 73, 9, 74, 22, 44],
        "keys 55, 19, 73, 9, 74, 22 and 44 carry recovered layouts"
    );

    // The rest stay measured runs: the Atlas has no payload card for types
    // 5485 and 11.
    let widths: Vec<usize> = record
        .fragments()
        .iter()
        .filter_map(|fragment| match fragment.payload() {
            FragmentPayload::Unrecovered { run, .. } => Some(run.len()),
            FragmentPayload::Component(_) => None,
        })
        .collect();
    assert_eq!(widths, [194, 49]);

    let components: Vec<&LocalPlayerState> = bundle.components().collect();
    assert_eq!(components.len(), 7, "one component per typed fragment");

    let player = components
        .iter()
        .find_map(|state| state.player())
        .expect("key 9 carries the player component");
    assert_eq!(player.group_mask, 0x02, "group 1 is present");
    assert_eq!(player.groups[0].entry_mask, 0x08, "member 3 is present");
    assert!(matches!(
        player.groups[0].entries[0],
        CodecPlayerComponentReplicatedStateEntry::LookingThroughLoadout(_)
    ));

    let objectives = components
        .iter()
        .find_map(|state| state.objectives())
        .expect("key 22 carries the objectives state");
    let (active, tasks) = containers(objectives);
    assert_eq!(active.delta, Some(7));
    assert_eq!(active.elements.len(), 17);
    assert_eq!(tasks.delta, Some(7));
    assert_eq!(tasks.elements.len(), 43);

    let entitlement = components
        .iter()
        .find_map(|state| state.entitlement())
        .expect("key 19 carries the entitlement state");
    assert_eq!(entitlement.group_mask, 0x01);
    assert_eq!(entitlement.groups[0].entry_mask, 0x07);
    let members: Vec<&CodecEntitlementReplicatedStateEntry> =
        entitlement.groups[0].entries.iter().collect();
    assert_eq!(
        members.len(),
        3,
        "all three entitlement members are present"
    );
    assert!(matches!(
        members[0],
        CodecEntitlementReplicatedStateEntry::Entitlements(_)
    ));
    assert!(matches!(
        members[1],
        CodecEntitlementReplicatedStateEntry::Balances(_)
    ));
    assert!(matches!(
        members[2],
        CodecEntitlementReplicatedStateEntry::EntitlementsReceived(_)
    ));

    let transmog = components
        .iter()
        .find_map(|state| state.transmog())
        .expect("key 74 carries the transmog state");
    assert_eq!(transmog.group_mask, 0x01);
    assert_eq!(transmog.groups[0].entry_mask, 0x13);
    let members: Vec<&CodecTransmogReplicatedStateEntry> =
        transmog.groups[0].entries.iter().collect();
    assert_eq!(members.len(), 3, "members 0, 1 and 4 are present");
    assert!(matches!(
        members[0],
        CodecTransmogReplicatedStateEntry::CapturedArmorAppearances(_)
    ));
    assert!(matches!(
        members[1],
        CodecTransmogReplicatedStateEntry::CapturedWeaponAppearances(_)
    ));
    assert!(matches!(
        members[2],
        CodecTransmogReplicatedStateEntry::InventoryServicesReady(_)
    ));

    let social = components
        .iter()
        .find_map(|state| state.social())
        .expect("key 55 carries the social state");
    assert_social(social);

    let status = components
        .iter()
        .find_map(|state| state.status_effects())
        .expect("key 44 carries the status-effects state");
    assert_status_effects(status);
}

#[test]
fn the_tracked_stat_fragment_is_a_typed_component() {
    let (_, bundle) = decode();
    let tracked = bundle
        .components()
        .find_map(|state| match state {
            LocalPlayerState::SeasonsRewardsTrackedStat(value) => Some(value),
            _ => None,
        })
        .expect("key 73 carries the tracked-stat state");
    assert_tracked_stat(tracked);
}

/// The measured `SeasonsRewardsTrackedStat` body: group 0, members 0 to 4.
fn assert_tracked_stat(tracked: &CodecSeasonsRewardsTrackedStatReplicatedState) {
    assert_eq!(tracked.group_mask, 0x01, "group 0 is present");
    assert_eq!(tracked.groups[0].entry_mask, 0x1F, "members 0 to 4");
    let entries = &tracked.groups[0].entries;
    assert_eq!(entries.len(), 5, "all five members are present");
    let initialized = entries
        .iter()
        .find_map(|entry| match entry {
            CodecSeasonsRewardsTrackedStatReplicatedStateEntry::Initialized(value) => Some(value),
            _ => None,
        })
        .expect("member 0 is initialized");
    assert!(*initialized);
    let group_list = entries
        .iter()
        .find_map(|entry| match entry {
            CodecSeasonsRewardsTrackedStatReplicatedStateEntry::GroupList(value) => Some(value),
            _ => None,
        })
        .expect("member 1 is groupList");
    assert_eq!(group_list.delta_count, 0);
    assert_eq!(group_list.delta, Some(8));
    assert_eq!(group_list.elements, [572_611_289, 2_365_596_905]);
    let group_count = entries
        .iter()
        .find_map(|entry| match entry {
            CodecSeasonsRewardsTrackedStatReplicatedStateEntry::GroupCountList(value) => {
                Some(value)
            }
            _ => None,
        })
        .expect("member 2 is groupCountList");
    assert_eq!(group_count.delta, Some(8));
    assert_eq!(group_count.elements, [30, 21]);
    let stat_index = entries
        .iter()
        .find_map(|entry| match entry {
            CodecSeasonsRewardsTrackedStatReplicatedStateEntry::GroupStatIndex(value) => {
                Some(value)
            }
            _ => None,
        })
        .expect("member 3 is groupStatIndex");
    assert_eq!(stat_index.elements.len(), 51);
    let stat_value = entries
        .iter()
        .find_map(|entry| match entry {
            CodecSeasonsRewardsTrackedStatReplicatedStateEntry::GroupStatValue(value) => {
                Some(value)
            }
            _ => None,
        })
        .expect("member 4 is groupStatValue");
    assert_eq!(stat_value.elements.len(), 51);
    assert_eq!(stat_value.elements[19], 4);
    assert_eq!(stat_value.elements[30], 49);
}

/// The measured Social body: group 1, members 3, 4 and 5.
fn assert_social(social: &CodecSocialReplicatedState) {
    assert_eq!(social.group_mask, 0x02, "group 1 is present");
    assert_eq!(social.groups[0].entry_mask, 0x38, "members 3, 4 and 5");
    let entries = &social.groups[0].entries;
    assert_eq!(entries.len(), 3, "members 3, 4 and 5 are present");
    let reset = entries
        .iter()
        .find_map(|entry| match entry {
            CodecSocialReplicatedStateEntry::LastDailyResetTime(value) => Some(value),
            _ => None,
        })
        .copied()
        .expect("member 3 is lastDailyResetTime");
    assert_eq!(reset, 0x18AB_B402_9A5C_FB9C);
    let friends = entries
        .iter()
        .find_map(|entry| match entry {
            CodecSocialReplicatedStateEntry::Friends(value) => Some(value),
            _ => None,
        })
        .expect("member 4 is friends");
    assert_eq!(friends.delta_count, 0);
    assert_eq!(friends.delta, Some(7));
    assert_eq!(friends.elements.len(), 1);
    assert_eq!(friends.elements[0].value.len(), 36);
    assert!(friends.elements[0].value.bytes().all(|byte| byte == 0));
    let invites = entries
        .iter()
        .find_map(|entry| match entry {
            CodecSocialReplicatedStateEntry::FriendInvites(value) => Some(value),
            _ => None,
        })
        .expect("member 5 is friendInvites");
    assert_eq!(invites.delta, Some(7));
    assert!(invites.elements.is_empty());
}

/// The measured `StatusEffects` body: group 1, member 1 only.
fn assert_status_effects(status: &CodecStatusEffectsComponentReplicatedState) {
    assert_eq!(status.group_mask, 0x02, "group 1 is present");
    assert_eq!(status.groups[0].entry_mask, 0x02, "member 1 is present");
    let CodecStatusEffectsComponentReplicatedStateEntry::MLightweightLocalEffectsMap(effects) =
        &status.groups[0].entries[0];
    assert_eq!(effects.delta_count, 0);
    assert_eq!(effects.delta, Some(8));
    assert_eq!(effects.elements.len(), 2);
    assert_eq!(effects.elements[0].u16_a00, 0x0728);
    assert_eq!(effects.elements[0].u64_a08, 0xFFE5);
    assert_eq!(effects.elements[1].u16_a00, 0x010F);
    assert_eq!(effects.elements[1].u64_a08, 0xFFE5);
}

#[test]
fn the_authored_fraction_is_the_typed_payload_bytes() {
    let (_, bundle) = decode();
    let extents = measured_extents();

    let mut authored = 0;
    let mut replayed = 0;
    for record in bundle.records() {
        for fragment in record.fragments() {
            let extent = extents
                .iter()
                .find(|extent| extent.key == fragment.key())
                .expect("every fragment key is measured");
            match fragment.payload() {
                FragmentPayload::Component(_) => authored += extent.payload_len,
                FragmentPayload::Unrecovered { .. } => replayed += extent.payload_len,
            }
        }
    }

    assert_eq!(
        authored,
        3892 + 834 + 1736 + 3 + 55 + 26 + 337,
        "3133, 5691, 3857, 3935, 4176, 4236 and 5606"
    );
    assert_eq!(replayed, 194 + 49, "the two runs");
    assert_eq!(
        authored + replayed,
        7126,
        "every payload byte of the record"
    );
    // 6883 / 7126 = 96.6 %, up from 1736 / 7126 = 24.4 % with one typed type.
    assert!(authored * 100 > 96 * (authored + replayed));
}

#[test]
fn a_typed_fragment_whose_extent_disagrees_with_its_codec_is_refused() {
    let body = bundle_body("0x9e_T0x8_R.bin");
    for (key, type_index) in [(19_u64, 3133_u64), (74, 5691), (55, 4176), (44, 4236)] {
        let mut extents = measured_extents();
        let extent = extents
            .iter_mut()
            .find(|extent| extent.key == key)
            .expect("the key is measured");
        assert_eq!(extent.type_index, type_index);
        extent.payload_len -= 1;
        let refused = Bundle::<LocalPlayerState>::decode(&body, &extents);
        assert!(
            matches!(refused, Err(BundleError::ComponentWidth { key: found, .. }) if found == key),
            "key {key} with a short extent must be refused, got {refused:?}"
        );
    }
}

#[test]
fn the_measured_bundle_reproduces_byte_for_byte() {
    let (body, bundle) = decode();
    let produced = bundle.encode().expect("the bundle encodes");
    assert_same_bytes(&produced, &body);
}

#[test]
fn the_payload_length_is_the_measured_7154_bytes() {
    // 7167 body bytes minus the 13-byte prologue: `00 01 08`, the head flag, the
    // one-byte counter, the six pinned bytes and the two-byte length varint.
    let (body, bundle) = decode();
    let produced = bundle.encode().expect("the bundle encodes");
    assert_eq!(produced.len(), body.len());
    assert_eq!(produced[3], 0x01, "prologue head");
    assert_eq!(&produced[5..11], &PROLOGUE_TAIL, "six pinned bytes");
    assert_eq!(&produced[11..13], &[0xb2, 0x6f], "length varint of 7154");
}

#[test]
fn widening_the_replication_counter_does_not_move_the_payload() {
    let (body, bundle) = decode();
    let widened = bundle.with_replication_seq(0x80).encode().expect("encodes");
    assert_eq!(widened.len(), body.len() + 1, "0x80 needs a second byte");
    assert_eq!(&widened[..4], &body[..4], "marker, type and head flag");
    assert_eq!(&widened[4..6], &[0x80, 0x02], "the counter re-encoded");
    assert_eq!(&widened[6..12], &body[5..11], "the pinned bytes follow it");
    assert_eq!(&widened[12..14], &body[11..13], "length field unchanged");
    assert_eq!(&widened[14..], &body[13..], "payload byte-identical");
}

#[test]
fn a_payload_width_the_codec_does_not_consume_is_refused() {
    let body = bundle_body("0x9e_T0x8_R.bin");
    let mut extents = measured_extents();
    let objectives = extents
        .iter_mut()
        .find(|extent| extent.key == 22)
        .expect("key 22 measured");
    objectives.payload_len += 1;
    assert!(matches!(
        Bundle::<CodecObjectivesReplicatedState>::decode(&body, &extents),
        Err(BundleError::ComponentWidth {
            key: 22,
            expected: 1737,
            consumed: 1736
        })
    ));
}

#[test]
fn a_fragment_with_no_measured_extent_is_refused_by_key() {
    let body = bundle_body("0x9e_T0x8_R.bin");
    let extents: Vec<FragmentExtent> = measured_extents()
        .into_iter()
        .filter(|extent| extent.key != 16)
        .collect();
    assert!(matches!(
        Bundle::<CodecObjectivesReplicatedState>::decode(&body, &extents),
        Err(BundleError::NoExtent { key: 16 })
    ));
}

#[test]
fn a_moved_prologue_byte_is_refused_instead_of_ignored() {
    let mut body = bundle_body("0x9e_T0x8_R.bin");
    body[5] = 0x02;
    assert!(matches!(
        Bundle::<CodecObjectivesReplicatedState>::decode(&body, &measured_extents()),
        Err(BundleError::PrologueMoved {
            field: "prologue_tail",
            expected: 0x01,
            found: 0x02
        })
    ));
}
