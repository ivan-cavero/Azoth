//! Compose presence S2C bodies from domain ids.
//!
//! WHY THIS MODULE EXISTS
//! ======================
//! `azoth-wire::presence` owns layouts; `azoth-model::ActorId` owns identity.
//! World entry still ships a captured state-bundle spawn (meanings of many fields
//! unproven), but AOI / peer visibility must not invent a second codec. This
//! module is the only place `worldd` turns an [`ActorId`] into a typed
//! `SpawnActorsMsg` record payload (`msg.spawn-actors`).
//!
//! Not yet on the entry ladder — sending it without a proven meaning would be a
//! guess. The encode path is still **called** at entry construction so the seed
//! is ready when AOI work starts.

use azoth_model::ActorId;
use azoth_wire::error::WireError;
use azoth_wire::ladder::typed_record_payload;
use azoth_wire::presence::{SpawnActorsMsg, SPAWN_ACTORS_MSG};

/// Typed-record payload for `SpawnActorsMsg` (wire 574) naming `actor`.
///
/// Mapping `ActorId.0` → the message's sole `u64` is the measured layout shape;
/// whether that u64 *is* the runtime actor id remains unproven (atlas).
///
/// # Errors
/// Propagates a wire encode failure (should not happen for a fixed 8-byte body).
pub fn encode_spawn_actors(actor: ActorId) -> Result<Vec<u8>, WireError> {
    let body = SpawnActorsMsg { id: actor.0 }.encode();
    typed_record_payload(SPAWN_ACTORS_MSG, &body)
}

#[cfg(test)]
mod tests {
    use super::*;
    use azoth_wire::presence::SpawnActorsMsg;

    #[test]
    fn spawn_actors_body_is_big_endian_actor_id() {
        let actor = ActorId(0x1122_3344_5566_7788);
        let typed = encode_spawn_actors(actor).expect("encodes");
        // typed = [VLQ len][00 01][varint type][8-byte BE id]
        assert!(typed.len() > 8);
        let id_bytes = &typed[typed.len() - 8..];
        assert_eq!(
            SpawnActorsMsg::decode(id_bytes).expect("tail is body").id,
            actor.0
        );
    }
}
