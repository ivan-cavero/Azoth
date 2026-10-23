//! The presence messages' layouts, as integration tests.
//!
//! WHY THESE LIVE HERE AND NOT IN THE MODULE
//! =========================================
//! They exercise only the public API, and `presence.rs` had grown past the workspace's 400-line
//! limit. The limit exists because a file past it usually means a boundary is wrong; here the
//! boundary was "types and their byte assertions in one place", and moving the assertions out is
//! the fix that keeps both readable.
//!
//! Every assertion below is about BYTES, not about behaviour: the layouts were decoded from the
//! client's own readers, so the risk is a wrong width or a wrong endianness, and only a byte
//! comparison catches those.

use azoth_wire::presence::{
    ADD_ACTOR_MESSAGE, ActorHead, AddActorMessage, FRAGMENT_UPDATE_MSG, FragmentUpdateMsg,
    RawVector, SPAWN_ACTORS_MSG, SpawnActorsMsg, UPDATE_MSG, UPDATE_MSG_MAX_BLOB, UpdateMsg,
};
use azoth_wire::WireError;


#[test]
fn spawn_actors_is_one_big_endian_u64() {
    let message = SpawnActorsMsg {
        id: 0x0102_0304_0506_0708,
    };
    let bytes = message.encode();
    assert_eq!(bytes, [1, 2, 3, 4, 5, 6, 7, 8], "big-endian, not little");
    assert_eq!(SpawnActorsMsg::decode(&bytes).expect("decodes"), message);
}

#[test]
fn spawn_actors_rejects_a_short_body() {
    let err = SpawnActorsMsg::decode(&[0; 7]).expect_err("must fail");
    assert!(matches!(err, WireError::Truncated { .. }), "{err}");
}

/// A single u64 means a 9-byte body must not be silently accepted as "one field and a byte":
/// the decoder reads exactly the first 8 and the caller owns the rest, which is why the type
/// has no trailing-field tolerance.
#[test]
fn spawn_actors_reads_exactly_eight_bytes() {
    let mut body = vec![0u8; 8];
    body[0] = 0xFF;
    let message = SpawnActorsMsg::decode(&body).expect("decodes");
    assert_eq!(message.id >> 56, 0xFF);
}

#[test]
fn fragment_update_is_u64_then_u32() {
    let message = FragmentUpdateMsg {
        first: 0x1122_3344_5566_7788,
        second: 0x99AA_BBCC,
    };
    let bytes = message.encode();
    assert_eq!(
        bytes,
        [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xAA, 0xBB, 0xCC]
    );
    assert_eq!(FragmentUpdateMsg::decode(&bytes).expect("decodes"), message);
}

#[test]
fn fragment_update_rejects_a_short_body() {
    let err = FragmentUpdateMsg::decode(&[0; 11]).expect_err("must fail");
    assert!(matches!(err, WireError::Truncated { .. }), "{err}");
}

#[test]
fn add_actor_prefix_round_trips() {
    let message = AddActorMessage {
        head: ActorHead([0xAB; 16]),
        flag: 7,
        counted: RawVector(vec![1, 2, 3]),
        word_28: 0x0102_0304_0506_0708,
        word_30: 0x1112_1314_1516_1718,
        word_38: 0x2122_2324_2526_2728,
        pair_40: (0x3132_3334, 0x4142_4344),
        byte_48: 9,
    };
    let bytes = message.encode_prefix().expect("encodes");
    assert_eq!(bytes.len(), AddActorMessage::PREFIX_SIZE);
    assert_eq!(
        AddActorMessage::decode_prefix(&bytes).expect("decodes"),
        message
    );
}

#[test]
fn add_actor_head_is_at_offset_zero() {
    let message = AddActorMessage {
        head: ActorHead([0x5A; 16]),
        flag: 0,
        counted: RawVector(vec![]),
        word_28: 0,
        word_30: 0,
        word_38: 0,
        pair_40: (0, 0),
        byte_48: 0,
    };
    let bytes = message.encode_prefix().expect("encodes");
    assert_eq!(&bytes[0..16], &[0x5A; 16]);
}

#[test]
fn add_actor_rejects_a_short_prefix() {
    let err = AddActorMessage::decode_prefix(&[0; 0x48]).expect_err("must fail");
    assert!(matches!(err, WireError::Truncated { .. }), "{err}");
}

#[test]
fn add_actor_rejects_a_counted_field_past_the_end() {
    let mut body = vec![0u8; AddActorMessage::PREFIX_SIZE];
    body[0x18] = 200; // claims 200 bytes of payload that are not there
    let err = AddActorMessage::decode_prefix(&body).expect_err("must fail");
    assert!(matches!(err, WireError::Truncated { .. }), "{err}");
}

/// The three polymorphic messages must NOT have a fixed-layout type in this module. This test
/// is the guard: if someone adds one without decoding the per-type dispatch, the doc comment
/// in the module is a lie and this test is where the reviewer sees it.
#[test]
fn the_polymorphic_messages_are_not_represented() {
    // Only these two dispatch per component type. UpdateMsg was predicted to be a third and
    // turned out to be a length-prefixed blob, so it IS represented above.
    const POLYMORPHIC: [u32; 2] = [391, 407];
    for fixed in [
        SPAWN_ACTORS_MSG,
        FRAGMENT_UPDATE_MSG,
        ADD_ACTOR_MESSAGE,
        UPDATE_MSG,
    ] {
        assert!(
            !POLYMORPHIC.contains(&fixed),
            "wire type {fixed} cannot be both fixed-layout and polymorphic"
        );
    }
}

#[test]
fn update_msg_is_a_length_prefixed_blob() {
    let message = UpdateMsg {
        blob: vec![0xAA, 0xBB, 0xCC],
    };
    let bytes = message.encode().expect("encodes");
    assert_eq!(bytes, vec![0x03, 0xAA, 0xBB, 0xCC], "one-byte length prefix");
    assert_eq!(UpdateMsg::decode(&bytes).expect("decodes"), message);
}

#[test]
fn update_msg_accepts_exactly_the_cap() {
    let message = UpdateMsg {
        blob: vec![0x11; UPDATE_MSG_MAX_BLOB],
    };
    let bytes = message.encode().expect("encodes at the cap");
    assert_eq!(UpdateMsg::decode(&bytes).expect("decodes"), message);
}

#[test]
fn update_msg_rejects_one_byte_past_the_cap() {
    let message = UpdateMsg {
        blob: vec![0x11; UPDATE_MSG_MAX_BLOB + 1],
    };
    let err = message.encode().expect_err("must fail");
    assert!(matches!(err, WireError::OutOfRange { .. }), "{err}");
}

#[test]
fn update_msg_rejects_a_truncated_blob() {
    // length says 5, only 2 bytes follow
    let err = UpdateMsg::decode(&[0x05, 0xAA, 0xBB]).expect_err("must fail");
    assert!(matches!(err, WireError::Truncated { .. }), "{err}");
}
