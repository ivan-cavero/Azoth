//! The next three inbound request families, on real captured bodies.
//!
//! Source of the captured bodies: `research/fixtures/wire/wire-bodies.json`,
//! exported by `scripts/export/export-wire-bodies.py` from a live session on
//! client build `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.
//! The path runs decode (wire) -> domain -> sim decision -> record, and each
//! captured body must survive the round trip byte for byte, so a layout that
//! only happens to fit one sample cannot pass.
//!
//! Each family changes replicated state and has no reply message, so `dispatch`
//! returns a [`DecisionRecord`] and nothing is encoded on the way out.

use std::fs;
use std::path::PathBuf;

use everfall_sim::{ActorId, Decision, ScreenId};
use everfall_wire::generated::{
    MsgObjectivesNotifyOpenUiScreen, MsgServerEquipItem, MsgTerritoryDetectorAttemptTerritoryUnlock,
};
use everfall_world::{DispatchError, World};

const ACTOR: u64 = 0xbf85_314b_bc4a_951a;

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

/// The richest captured body for one wire id.
fn captured_body(wire_id: u32) -> Vec<u8> {
    bodies_for(wire_id)
        .into_iter()
        .max_by_key(Vec::len)
        .expect("at least one body")
}

/// Every committed body round-trips through the generated codec byte for byte.
fn round_trips(wire_id: u32, mut decode_then_encode: impl FnMut(&[u8]) -> Vec<u8>) {
    for body in bodies_for(wire_id) {
        assert_eq!(
            decode_then_encode(&body),
            body,
            "wire {wire_id:#x}: a captured body did not round-trip"
        );
    }
}

#[test]
fn the_world_maps_the_next_three_inbound_requests() {
    for wire_id in [
        MsgServerEquipItem::WIRE_ID,
        MsgObjectivesNotifyOpenUiScreen::WIRE_ID,
        MsgTerritoryDetectorAttemptTerritoryUnlock::WIRE_ID,
    ] {
        let body = captured_body(wire_id);
        let result = World::new([]).dispatch(wire_id, &body);
        assert!(
            result.is_ok(),
            "wire {wire_id:#x} is not mapped: {:?}",
            result.as_ref().err()
        );
        let record = result.expect("a mapped wire decodes its captured body");
        assert!(!record.card.is_empty(), "the record names its Atlas card");
        assert_eq!(record.decision, Decision::Accepted);
        assert_eq!(record.actor, ActorId::new(ACTOR));
    }
}

#[test]
fn captured_equip_request_is_recorded_and_round_trips() {
    let body = captured_body(MsgServerEquipItem::WIRE_ID);
    let request = MsgServerEquipItem::decode(&body).expect("decode captured 0xf37 body");
    assert_eq!(request.local_actor_id_word0, ACTOR);
    assert_eq!(request.item_id.len(), 16, "the item id is a 16-byte run");

    let mut world = World::new([]);
    let record = world
        .dispatch(MsgServerEquipItem::WIRE_ID, &body)
        .expect("dispatch captured 0xf37");

    assert_eq!(record.card, "msg.server-equip-item");
    assert_eq!(record.facet_id, request.local_facet_id);
    assert_eq!(record.decision, Decision::Accepted);
    assert!(
        world.client_state().has_equip_request(record.actor),
        "the equip report reaches the recorded state"
    );

    round_trips(MsgServerEquipItem::WIRE_ID, |body| {
        let mut out = Vec::new();
        MsgServerEquipItem::decode(body)
            .expect("decode")
            .encode(&mut out)
            .expect("encode");
        out
    });
}

#[test]
fn captured_open_ui_screen_stores_the_screen_and_round_trips() {
    // The screen id is a plain u32 the card names, so the world holds its value.
    let bodies = bodies_for(MsgObjectivesNotifyOpenUiScreen::WIRE_ID);
    assert!(
        bodies.len() >= 2,
        "more than one captured screen transition"
    );
    let mut world = World::new([]);
    for body in &bodies {
        let request =
            MsgObjectivesNotifyOpenUiScreen::decode(body).expect("decode captured 0xa39 body");
        let record = world
            .dispatch(MsgObjectivesNotifyOpenUiScreen::WIRE_ID, body)
            .expect("dispatch captured 0xa39");
        assert_eq!(record.card, "msg.objectives-notify-open-ui-screen");
        assert_eq!(record.facet_id, request.local_facet_id);
        assert_eq!(record.decision, Decision::Accepted);
        assert_eq!(
            world.client_state().screen(record.actor),
            Some(ScreenId::new(request.screen_id)),
            "the world holds the last screen the client showed"
        );
    }
    // The measured HUD id appears in the fixture: a1126b78 after a dismissal.
    assert!(
        bodies.iter().any(|body| {
            MsgObjectivesNotifyOpenUiScreen::decode(body).is_ok_and(|r| r.screen_id == 0xa112_6b78)
        }),
        "the captured set carries the HUD screen id"
    );

    round_trips(MsgObjectivesNotifyOpenUiScreen::WIRE_ID, |body| {
        let mut out = Vec::new();
        MsgObjectivesNotifyOpenUiScreen::decode(body)
            .expect("decode")
            .encode(&mut out)
            .expect("encode");
        out
    });
}

#[test]
fn captured_territory_unlock_attempt_is_recorded_and_round_trips() {
    let body = captured_body(MsgTerritoryDetectorAttemptTerritoryUnlock::WIRE_ID);
    assert_eq!(body.len(), 54, "the captured unlock body is 54 bytes");
    let request = MsgTerritoryDetectorAttemptTerritoryUnlock::decode(&body)
        .expect("decode captured 0x8f9 body");
    assert_eq!(request.local_actor_id_word0, ACTOR);
    assert_eq!(request.unlock_token.len(), 16);

    let mut world = World::new([]);
    let record = world
        .dispatch(MsgTerritoryDetectorAttemptTerritoryUnlock::WIRE_ID, &body)
        .expect("dispatch captured 0x8f9");

    assert_eq!(
        record.card,
        "msg.territory-detector-attempt-territory-unlock"
    );
    assert_eq!(record.facet_id, request.local_facet_id);
    assert_eq!(record.decision, Decision::Accepted);
    assert!(
        world.client_state().has_unlock_attempt(record.actor),
        "the unlock attempt reaches the recorded state"
    );

    round_trips(
        MsgTerritoryDetectorAttemptTerritoryUnlock::WIRE_ID,
        |body| {
            let mut out = Vec::new();
            MsgTerritoryDetectorAttemptTerritoryUnlock::decode(body)
                .expect("decode")
                .encode(&mut out)
                .expect("encode");
            out
        },
    );
}

#[test]
fn a_truncated_body_is_a_named_malformed_error_and_writes_no_state() {
    let body = captured_body(MsgServerEquipItem::WIRE_ID);
    let mut world = World::new([]);
    let error = world
        .dispatch(MsgServerEquipItem::WIRE_ID, &body[..body.len() - 1])
        .expect_err("a 44-byte 0xf37 body is not the card's 45 bytes");
    assert!(
        matches!(error, DispatchError::Malformed { wire_id, .. } if wire_id == 0xf37),
        "the refusal names the message, got {error:?}"
    );
    assert!(!world.client_state().has_equip_request(ActorId::new(ACTOR)));
}

#[test]
fn a_family_still_outside_the_mapper_is_refused() {
    let mut world = World::new([]);
    let error = world
        .dispatch(0xda2, &[])
        .expect_err("Groups RequestTargetPing is not mapped by this world");
    assert_eq!(error, DispatchError::UnsupportedWireId { wire_id: 0xda2 });
}
