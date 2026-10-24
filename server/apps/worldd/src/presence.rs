//! Compose presence S2C bodies from domain ids.
//!
//! WHY THIS MODULE EXISTS
//! ======================
//! `azoth-wire::presence` owns layouts; `azoth-model` owns identities.
//! Phase 4 (plan §8.6) is the **wire-level** half: originate typed presence
//! records the client can unmarshal. Render of remote bodies is a separate,
//! known client defect — this module does not claim visibility on screen.
//!
//! `SpawnActorsMsg`'s sole `u64` is **not** emitted here: its meaning is still
//! unproven. `AddActorMessage` is emitted with the measured 16-byte spawn
//! actor guid in the head and zeroed undecoded fields (candidate mapping).

use std::collections::HashMap;
use std::net::SocketAddr;

use azoth_model::ActorGuid;
use azoth_wire::error::WireError;
use azoth_wire::ladder::typed_record_payload;
use azoth_wire::presence::{
    ActorHead, AddActorMessage, RawVector, SpawnActorsMsg, ADD_ACTOR_MESSAGE, SPAWN_ACTORS_MSG,
};
use azoth_wire::spawn::{SpawnRecord, ACTOR_ID_LEN};

use crate::ladder::{Ladder, Outgoing};
use crate::peer::Peer;

/// Read the 16-byte actor guid from a spawn-record payload, if the anchor holds.
#[must_use]
pub fn guid_from_spawn_payload(payload: &[u8]) -> Option<ActorGuid> {
    let record = SpawnRecord::from_template(payload).ok()?;
    let offset = record.actor_id_offset()?;
    let bytes = record.payload().get(offset..offset + ACTOR_ID_LEN)?;
    let mut guid = [0u8; ACTOR_ID_LEN];
    guid.copy_from_slice(bytes);
    Some(ActorGuid(guid))
}

/// Typed-record payload for `SpawnActorsMsg` (wire 574).
///
/// # Errors
/// Propagates a wire encode failure.
pub fn encode_spawn_actors(id: azoth_model::ActorId) -> Result<Vec<u8>, WireError> {
    let body = SpawnActorsMsg { id: id.0 }.encode();
    typed_record_payload(SPAWN_ACTORS_MSG, &body)
}

/// Fixed-prefix body of `AddActorMessage` with `guid` in the 16-byte head.
///
/// Undecoded fields are zeroed — that is deliberate, not a claim they are zero
/// on the official server. Ontology: `msg.add-actor` (confidence still layout;
/// head→guid is candidate).
///
/// # Errors
/// Propagates encode failures from the wire crate.
pub fn encode_add_actor_prefix(guid: ActorGuid) -> Result<Vec<u8>, WireError> {
    AddActorMessage {
        head: ActorHead(guid.0),
        flag: 0,
        counted: RawVector::default(),
        word_28: 0,
        word_30: 0,
        word_38: 0,
        pair_40: (0, 0),
        byte_48: 0,
    }
    .encode_prefix()
}

/// Typed-record payload for `AddActorMessage` (wire 449), prefix only.
///
/// # Errors
/// Propagates encode failures.
pub fn encode_add_actor(guid: ActorGuid) -> Result<Vec<u8>, WireError> {
    typed_record_payload(ADD_ACTOR_MESSAGE, &encode_add_actor_prefix(guid)?)
}

/// Queue one `AddActorMessage` on `ladder`'s reliable counters for AOI fanout.
///
/// # Errors
/// Propagates encode / pack failures.
pub fn compose_add_actor(
    ladder: &mut Ladder,
    subject: ActorGuid,
) -> Result<Vec<Outgoing>, WireError> {
    let inner = encode_add_actor(subject)?;
    ladder.compose_typed(inner, "msg.add-actor")
}

/// After the entry ladder finishes, queue `AddActor` sight between `joined` and every other peer.
pub fn maybe_queue_aoi(peers: &mut HashMap<SocketAddr, Peer>, joined: SocketAddr) {
    let ready = peers.get(&joined).is_some_and(|state| {
        !state.presence_announced && state.ladder.as_ref().is_some_and(Ladder::is_complete)
    });
    if !ready {
        return;
    }
    let Some(joined_guid) = peers.get(&joined).map(|s| s.actor_guid) else {
        return;
    };
    let others: Vec<(SocketAddr, ActorGuid)> = peers
        .iter()
        .filter(|(addr, _)| **addr != joined)
        .map(|(addr, state)| (*addr, state.actor_guid))
        .collect();
    for (other, other_guid) in &others {
        if let Some(state) = peers.get_mut(other) {
            if let Some(ladder) = state.ladder.as_mut() {
                if let Ok(chunks) = compose_add_actor(ladder, joined_guid) {
                    state.presence_out.extend(chunks);
                }
            }
        }
        if let Some(state) = peers.get_mut(&joined) {
            if let Some(ladder) = state.ladder.as_mut() {
                if let Ok(chunks) = compose_add_actor(ladder, *other_guid) {
                    state.presence_out.extend(chunks);
                }
            }
        }
    }
    if let Some(state) = peers.get_mut(&joined) {
        state.presence_announced = true;
        eprintln!(
            "[worldd] presence fanout peer={joined} others={} ontology=msg.add-actor",
            others.len()
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use azoth_model::ActorId;
    use azoth_wire::presence::{AddActorMessage, SpawnActorsMsg};

    #[test]
    fn spawn_actors_body_is_big_endian_actor_id() {
        let actor = ActorId(0x1122_3344_5566_7788);
        let id = actor.0;
        let typed = encode_spawn_actors(actor).expect("encodes");
        assert!(typed.len() > 8);
        let id_bytes = &typed[typed.len() - 8..];
        assert_eq!(SpawnActorsMsg::decode(id_bytes).expect("tail is body").id, id);
    }

    #[test]
    fn add_actor_prefix_round_trips_guid_head() {
        let guid = ActorGuid([
            0x1a, 0x95, 0x4a, 0xbc, 0x4b, 0x31, 0x85, 0xbf, 0xbe, 0x37, 0xc3, 0xd8, 0x59, 0x26,
            0x18, 0xe0,
        ]);
        let body = encode_add_actor_prefix(guid).expect("encodes");
        let decoded = AddActorMessage::decode_prefix(&body).expect("decodes");
        assert_eq!(decoded.head.0, guid.0);
    }

    #[test]
    fn guid_from_spawn_fixture_matches_template() {
        let payload =
            include_bytes!("../../../crates/azoth-wire/tests/fixtures/spawn-record-1.bin");
        let guid = guid_from_spawn_payload(payload).expect("fixture actor id");
        assert_eq!(
            guid.0,
            [
                0x1a, 0x95, 0x4a, 0xbc, 0x4b, 0x31, 0x85, 0xbf, 0xbe, 0x37, 0xc3, 0xd8, 0x59, 0x26,
                0x18, 0xe0
            ]
        );
    }
}
