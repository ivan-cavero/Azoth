//! The whole loop in memory, on a real captured request.
//!
//! Source of the captured bodies: `research/fixtures/wire/wire-bodies.json`,
//! exported by `scripts/export/export-wire-body.py` from a live session on
//! client build `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.
//! The path runs decode (wire) -> domain -> sim decision -> record, and the
//! captured body must survive the round trip byte for byte, so a layout that
//! only happens to fit one sample cannot pass.
//!
//! There is no reply to encode. `OBJECTIVES_REPLY_WIRE_ID` is `None` because the
//! atlas states the Objectives family has no reply message; asserting that here
//! is what stops a later change from inventing one.

use std::fs;
use std::path::PathBuf;

use everfall_sim::{
    ActorId, Decision, Dropped, ObjectiveId, ObjectiveRequest, Rejection, TRACKED_LIMIT,
};
use everfall_wire::WireError;
use everfall_wire::generated::{
    MsgObjectivesSetObjectiveAutoPinning, MsgObjectivesUpdateTrackedObjectives,
};
use everfall_world::{DecisionRecord, DispatchError, OBJECTIVES_REPLY_WIRE_ID, World};

fn fixture_text() -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../research/fixtures/wire/wire-bodies.json");
    fs::read_to_string(&path).expect("read committed wire-body fixture")
}

fn hex_bytes(hex: &str) -> Vec<u8> {
    assert!(hex.len().is_multiple_of(2), "odd hex length: {}", hex.len());
    (0..hex.len() / 2)
        .map(|index| {
            u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16).expect("hex digit pair")
        })
        .collect()
}

/// Every committed body for one wire id, in fixture order.
fn bodies_for(wire_id: u32) -> Vec<Vec<u8>> {
    let fixture = fixture_text();
    let needle = format!("\"wire_id\": {wire_id},");
    let body_key = "\"body\": \"";
    let mut out = Vec::new();
    let mut rest = fixture.as_str();
    while let Some(start) = rest.find(&needle) {
        let after_id = &rest[start..];
        let body_start = after_id.find(body_key).expect("body key after wire id") + body_key.len();
        let after_body = &after_id[body_start..];
        let end = after_body.find('"').expect("closing quote after body");
        out.push(hex_bytes(&after_body[..end]));
        rest = &after_body[end..];
    }
    assert!(!out.is_empty(), "wire id {wire_id} absent from the fixture");
    out
}

/// The richest captured body for one wire id (the tracked set carries ids, not
/// only an empty count).
fn captured_body(wire_id: u32) -> Vec<u8> {
    bodies_for(wire_id)
        .into_iter()
        .max_by_key(Vec::len)
        .expect("at least one body")
}

/// A world that has definitions for exactly the ids the captured request names,
/// so the captured request is decidable rather than corrected.
fn world_that_knows(ids: &[u64]) -> World {
    World::new(ids.iter().copied().map(ObjectiveId::new))
}

fn expect_decided(record: &DecisionRecord) -> &Decision {
    assert!(!record.card.is_empty(), "the record names its Atlas card");
    &record.decision
}

#[test]
fn captured_tracked_objectives_is_accepted_and_held() {
    let body = captured_body(MsgObjectivesUpdateTrackedObjectives::WIRE_ID);
    let request =
        MsgObjectivesUpdateTrackedObjectives::decode(&body).expect("decode captured 0x5b2 body");
    let mut world = world_that_knows(&request.tracked_objective_ids);

    let record = world
        .dispatch(MsgObjectivesUpdateTrackedObjectives::WIRE_ID, &body)
        .expect("dispatch captured 0x5b2");

    assert_eq!(record.card, "msg.objectives-update-tracked-objectives");
    assert_eq!(
        record.facet_id, 0x180f_8d4e_5736_97c6,
        "the captured sending facet's local id reaches the record"
    );
    assert_eq!(
        record.actor,
        ActorId::new(0xbf85_314b_bc4a_951a),
        "the captured player's actor id word 0 addresses the simulation"
    );
    assert_eq!(
        expect_decided(&record),
        &Decision::Accepted,
        "a known id list inside the cap is applied as asked"
    );

    let held: Vec<u64> = world
        .sim()
        .tracked(record.actor)
        .expect("state after an accepted request")
        .tracked()
        .iter()
        .map(|id| id.value())
        .collect();
    assert_eq!(
        held, request.tracked_objective_ids,
        "the simulation holds the captured ids in the captured order"
    );
    assert_eq!(
        held.len(),
        6,
        "the rich captured 0x5b2 body carries six tracked ids"
    );

    assert!(
        OBJECTIVES_REPLY_WIRE_ID.is_none(),
        "the atlas states the Objectives family has no reply; encoding one would be inventing it"
    );

    let mut out = Vec::new();
    request.encode(&mut out).expect("encode captured 0x5b2");
    assert_eq!(
        out, body,
        "the captured body did not round-trip byte for byte"
    );
}

#[test]
fn captured_tracked_objectives_is_corrected_by_a_world_that_knows_nothing() {
    let body = captured_body(MsgObjectivesUpdateTrackedObjectives::WIRE_ID);
    let request =
        MsgObjectivesUpdateTrackedObjectives::decode(&body).expect("decode captured 0x5b2 body");
    let mut world = World::new([]);

    let record = world
        .dispatch(MsgObjectivesUpdateTrackedObjectives::WIRE_ID, &body)
        .expect("dispatch captured 0x5b2");

    assert_eq!(
        expect_decided(&record),
        &Decision::Corrected(Dropped {
            duplicates: 0,
            unknown: request.tracked_objective_ids.len(),
        }),
        "every captured id is unknown to an empty world, and the reason says so"
    );
    assert_eq!(
        world.sim().tracked(record.actor).expect("state").tracked(),
        &[],
        "the request is still applied: the player tracks nothing it cannot resolve"
    );
}

#[test]
fn captured_auto_pinning_is_accepted_and_held() {
    let body = captured_body(MsgObjectivesSetObjectiveAutoPinning::WIRE_ID);
    let request =
        MsgObjectivesSetObjectiveAutoPinning::decode(&body).expect("decode captured 0xa95 body");
    let mut world = World::new([]);

    let record = world
        .dispatch(MsgObjectivesSetObjectiveAutoPinning::WIRE_ID, &body)
        .expect("dispatch captured 0xa95");

    assert_eq!(record.card, "msg.objectives-set-objective-auto-pinning");
    assert_eq!(record.facet_id, 0x180f_8d4e_5736_97c6);
    assert_eq!(record.actor, ActorId::new(0xbf85_314b_bc4a_951a));
    assert_eq!(expect_decided(&record), &Decision::Accepted);
    assert_eq!(
        request.auto_pinning_flags.len(),
        36,
        "the captured 0xa95 body carries all 36 slots"
    );
    assert_eq!(
        world
            .sim()
            .tracked(record.actor)
            .expect("state")
            .pin_flags(),
        request.auto_pinning_flags.as_slice()
    );

    let mut out = Vec::new();
    request.encode(&mut out).expect("encode captured 0xa95");
    assert_eq!(
        out, body,
        "the captured body did not round-trip byte for byte"
    );
}

#[test]
fn nine_tracked_ids_are_refused_at_the_wire_and_at_the_rule() {
    let ids: Vec<u64> = (1..=9).collect();
    let request = MsgObjectivesUpdateTrackedObjectives {
        local_facet_id: 0x180f_8d4e_5736_97c6,
        local_actor_id_word0: 0xbf85_314b_bc4a_951a,
        tracked_objective_ids: ids.clone(),
    };
    let mut body = Vec::new();
    request.encode(&mut body).expect("encode a nine-id body");

    let mut world = world_that_knows(&ids);
    let error = world
        .dispatch(MsgObjectivesUpdateTrackedObjectives::WIRE_ID, &body)
        .expect_err("nine ids are over the card's cap");
    assert_eq!(
        error,
        DispatchError::Malformed {
            wire_id: MsgObjectivesUpdateTrackedObjectives::WIRE_ID,
            source: WireError::OutOfRange {
                field: "tracked_objective_ids",
                max: 8,
                value: 9,
            },
        },
        "the refusal names the message and the cap it broke"
    );
    assert!(
        world
            .sim()
            .tracked(ActorId::new(0xbf85_314b_bc4a_951a))
            .is_none(),
        "an over-cap body never reaches the rules"
    );

    // The decoder is a boundary, not the rule: a caller inside the process must
    // still be refused here, and the refusal must leave state alone.
    let decision = world.sim_mut().decide(
        ActorId::new(0xbf85_314b_bc4a_951a),
        ObjectiveRequest::SetTrackedObjectives(ids.iter().copied().map(ObjectiveId::new).collect()),
    );
    assert_eq!(
        decision,
        Decision::Rejected(Rejection::TooManyTrackedObjectives {
            offered: 9,
            limit: TRACKED_LIMIT,
        })
    );
    assert!(
        world
            .sim()
            .tracked(ActorId::new(0xbf85_314b_bc4a_951a))
            .is_none()
    );
}

#[test]
fn duplicate_tracked_ids_collapse_in_the_loop() {
    let first = 0x1111_2222_3333_4444_u64;
    let second = 0x5555_6666_7777_8888_u64;
    let request = MsgObjectivesUpdateTrackedObjectives {
        local_facet_id: 0x180f_8d4e_5736_97c6,
        local_actor_id_word0: 0xbf85_314b_bc4a_951a,
        tracked_objective_ids: vec![first, second, first],
    };
    let mut body = Vec::new();
    request.encode(&mut body).expect("encode a duplicated body");
    let mut world = world_that_knows(&[first, second]);

    let record = world
        .dispatch(MsgObjectivesUpdateTrackedObjectives::WIRE_ID, &body)
        .expect("dispatch a duplicated body");

    assert_eq!(
        expect_decided(&record),
        &Decision::Corrected(Dropped {
            duplicates: 1,
            unknown: 0,
        })
    );
    let held: Vec<u64> = world
        .sim()
        .tracked(record.actor)
        .expect("state")
        .tracked()
        .iter()
        .map(|id| id.value())
        .collect();
    assert_eq!(
        held,
        vec![first, second],
        "the first occurrence keeps its place"
    );
}

#[test]
fn unknown_tracked_id_is_dropped_in_the_loop() {
    let known = 0x1111_2222_3333_4444_u64;
    let stranger = 0x9999_aaaa_bbbb_cccc_u64;
    let request = MsgObjectivesUpdateTrackedObjectives {
        local_facet_id: 0x180f_8d4e_5736_97c6,
        local_actor_id_word0: 0xbf85_314b_bc4a_951a,
        tracked_objective_ids: vec![known, stranger],
    };
    let mut body = Vec::new();
    request
        .encode(&mut body)
        .expect("encode a body with a stranger");
    let mut world = world_that_knows(&[known]);

    let record = world
        .dispatch(MsgObjectivesUpdateTrackedObjectives::WIRE_ID, &body)
        .expect("dispatch a body with a stranger");

    assert_eq!(
        expect_decided(&record),
        &Decision::Corrected(Dropped {
            duplicates: 0,
            unknown: 1,
        })
    );
    let held: Vec<u64> = world
        .sim()
        .tracked(record.actor)
        .expect("state")
        .tracked()
        .iter()
        .map(|id| id.value())
        .collect();
    assert_eq!(
        held,
        vec![known],
        "the id the world cannot resolve is not tracked"
    );
}

#[test]
fn a_family_this_world_does_not_map_is_refused() {
    let mut world = World::new([]);
    let error = world
        .dispatch(0x9d3, &[])
        .expect_err("PlayerSettings is not mapped by this world");
    assert_eq!(error, DispatchError::UnsupportedWireId { wire_id: 0x9d3 });
}
