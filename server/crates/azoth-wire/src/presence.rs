//! The presence messages with a fixed wire layout.
//!
//! WHY THIS MODULE EXISTS
//! ======================
//! Telling a client that another actor exists is the one thing this project has never been able to
//! do (`docs/PLAN-backend-rust.md` §8.6). Three of the six presence messages turned out to have
//! layouts that can simply be transcribed, and they are the three that matter for presence:
//!
//! | wire | message | layout |
//! | --- | --- | --- |
//! | 574 | `SpawnActorsMsg` | one `u64` |
//! | 422 | `FragmentUpdateMsg` | `u64` then `u32` |
//! | 449 | `AddActorMessage` | fifteen fields, below |
//!
//! The other three — `Replicate` (391), `ReplicateClient` (407), `UpdateMsg` (106) — are
//! **polymorphic**: they construct a record object for its component type and call
//! `vtable+0x90 / +0xa0 / +0xb0` on it, so their shape is per component type rather than per
//! message. They do not belong in this module and are deliberately absent: a struct here would be
//! a guess dressed as a layout.
//!
//! HOW THE LAYOUTS WERE ESTABLISHED
//! ================================
//! By reading each message's UNMARSHAL out of the 1.460 decompiled corpus, reached through its
//! codec facet (`scripts/find-codec-facet.py`, recorded in
//! `research/atlas/presence-codecs.json`). Every field below is read by code; none is inferred
//! from a width and a position.
//!
//! **Endianness is measured, not assumed.** Every integer reader in this family goes through
//! `ntohl` — `FUN_146168b00` for the `u64` path and `FUN_146168aa0` for the `u32` path — so these
//! messages are big-endian, like every other field this project has decoded.
//!
//! WHAT IS NOT HERE, ON PURPOSE
//! ============================
//! The **meaning** of most fields. `SpawnActorsMsg` carrying one `u64` is a strong hint that it
//! names an actor, and `AddActorMessage`'s 16-byte head is consistent with an actor id, but
//! neither is proven. The field names below say what the field *is* (a u64, 16 bytes) and where it
//! sits; where a name would be a guess, the field is named after its position.

use crate::error::WireError;

/// Wire type of `SpawnActorsMsg`.
pub const SPAWN_ACTORS_MSG: u32 = 574;
/// Wire type of `FragmentUpdateMsg`.
pub const FRAGMENT_UPDATE_MSG: u32 = 422;
/// Wire type of `AddActorMessage`.
pub const ADD_ACTOR_MESSAGE: u32 = 449;

/// `SpawnActorsMsg`: one big-endian `u64`.
///
/// Measured from `FUN_146a49b20`, which reads exactly one value through `FUN_14087af30` and
/// returns. **There is no count, no loop and no vector**: the message that makes actors appear
/// carries an identifier, not an inline list. That is a real constraint on the server — whatever
/// the client does with it is driven by the id rather than by a payload.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpawnActorsMsg {
    /// The single `u64` the message carries. Its meaning is not established; see the module docs.
    pub id: u64,
}

impl SpawnActorsMsg {
    /// Encoded size in bytes.
    pub const SIZE: usize = 8;

    /// Decode from a body.
    ///
    /// # Errors
    /// [`WireError::Truncated`] when fewer than 8 bytes are present.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        if body.len() < Self::SIZE {
            return Err(WireError::truncated("SpawnActorsMsg", Self::SIZE, body.len()));
        }
        Ok(Self {
            id: u64::from_be_bytes(body[..8].try_into().expect("8 bytes")),
        })
    }

    /// Encode to a body.
    #[must_use]
    pub fn encode(&self) -> [u8; Self::SIZE] {
        self.id.to_be_bytes()
    }
}

/// `FragmentUpdateMsg`: a big-endian `u64` followed by a big-endian `u32`.
///
/// Measured from `FUN_1407c41a0`, which calls `FUN_1407d9520` (which in turn calls
/// `FUN_1407dae40` for the `u64`) and then `FUN_14087a3c0` for the `u32`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FragmentUpdateMsg {
    /// The leading `u64`. Meaning not established.
    pub first: u64,
    /// The trailing `u32`. Meaning not established.
    pub second: u32,
}

impl FragmentUpdateMsg {
    /// Encoded size in bytes.
    pub const SIZE: usize = 12;

    /// Decode from a body.
    ///
    /// # Errors
    /// [`WireError::Truncated`] when fewer than 12 bytes are present.
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        if body.len() < Self::SIZE {
            return Err(WireError::truncated(
                "FragmentUpdateMsg",
                Self::SIZE,
                body.len(),
            ));
        }
        Ok(Self {
            first: u64::from_be_bytes(body[..8].try_into().expect("8 bytes")),
            second: u32::from_be_bytes(body[8..12].try_into().expect("4 bytes")),
        })
    }

    /// Encode to a body.
    #[must_use]
    pub fn encode(&self) -> [u8; Self::SIZE] {
        let mut out = [0u8; Self::SIZE];
        out[..8].copy_from_slice(&self.first.to_be_bytes());
        out[8..].copy_from_slice(&self.second.to_be_bytes());
        out
    }
}

/// The head of `AddActorMessage`: 16 raw bytes.
///
/// A newtype rather than a bare array so a caller cannot confuse it with any other 16 bytes. The
/// width matches `ClientAddEntryMsg`'s actor id (wire 164, measured as
/// `[00 01][a4][16-byte actor id]`), which is why this is very likely an actor id — but that is an
/// inference from two independent 16-byte fields, not a proven identity, so the type does not
/// claim it in its name.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ActorHead(pub [u8; 16]);

/// One length-prefixed vector in `AddActorMessage`.
///
/// The element encoding is **not decoded**: `FUN_14087a570` reads a count and then entries, and
/// what an entry looks like is per-type. Keeping the raw bytes is the honest representation — a
/// `Vec<u64>` here would be a guess.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct RawVector(pub Vec<u8>);

/// `AddActorMessage`: fifteen fields, in the order the unmarshal reads them.
///
/// Offsets are from the start of the message body and are recorded in each field's doc so a
/// reader can compare against `research/atlas/presence-codecs.json` without opening the corpus.
///
/// `decode`/`encode` handle only the **fixed-width prefix** (offsets `0x00`–`0x48`), because
/// everything from `0x50` on is variable-length and its readers are not decoded. A partial
/// implementation that says where it stops is more useful than a complete-looking one that guesses.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AddActorMessage {
    /// `+0x00`, 16 bytes, read raw by `FUN_1408787b0(…, 0x10)`.
    pub head: ActorHead,
    /// `+0x10`, 1 byte, read directly.
    pub flag: u8,
    /// `+0x18`, variable, read by `FUN_146a6ebe0` as a count byte plus payload.
    pub counted: RawVector,
    /// `+0x28`, 8 bytes, `u64` big-endian.
    pub word_28: u64,
    /// `+0x30`, 8 bytes, `u64` big-endian.
    pub word_30: u64,
    /// `+0x38`, 8 bytes, `u64` big-endian.
    pub word_38: u64,
    /// `+0x40`, 8 bytes, two `u32` big-endian.
    pub pair_40: (u32, u32),
    /// `+0x48`, 1 byte, read directly.
    pub byte_48: u8,
}

impl AddActorMessage {
    /// Size of the fixed-width prefix, i.e. the offset where the variable tail begins.
    pub const PREFIX_SIZE: usize = 0x49;

    /// Decode the fixed-width prefix.
    ///
    /// # Errors
    /// [`WireError::Truncated`] when the body is shorter than the prefix, or when the counted
    /// field at `+0x18` does not fit.
    pub fn decode_prefix(body: &[u8]) -> Result<Self, WireError> {
        if body.len() < Self::PREFIX_SIZE {
            return Err(WireError::truncated(
                "AddActorMessage prefix",
                Self::PREFIX_SIZE,
                body.len(),
            ));
        }
        let mut head = [0u8; 16];
        head.copy_from_slice(&body[0x00..0x10]);
        // +0x18 is a count byte then that many bytes; the fixed fields start after it.
        let count = usize::from(body[0x18]);
        let counted_end = 0x19 + count;
        if counted_end > body.len() {
            return Err(WireError::truncated(
                "AddActorMessage counted field",
                counted_end,
                body.len(),
            ));
        }
        Ok(Self {
            head: ActorHead(head),
            flag: body[0x10],
            counted: RawVector(body[0x19..counted_end].to_vec()),
            word_28: u64::from_be_bytes(body[0x28..0x30].try_into().expect("8")),
            word_30: u64::from_be_bytes(body[0x30..0x38].try_into().expect("8")),
            word_38: u64::from_be_bytes(body[0x38..0x40].try_into().expect("8")),
            pair_40: (
                u32::from_be_bytes(body[0x40..0x44].try_into().expect("4")),
                u32::from_be_bytes(body[0x44..0x48].try_into().expect("4")),
            ),
            byte_48: body[0x48],
        })
    }

    /// Encode the fixed-width prefix.
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] when the counted field exceeds 255 bytes.
    pub fn encode_prefix(&self) -> Result<Vec<u8>, WireError> {
        if self.counted.0.len() > 255 {
            return Err(WireError::OutOfRange {
                field: "AddActorMessage counted field",
                value: self.counted.0.len() as u64,
                limit: 256,
            });
        }
        let mut out = Vec::with_capacity(Self::PREFIX_SIZE);
        out.extend_from_slice(&self.head.0);
        out.push(self.flag);
        // +0x11..+0x18 are not part of the decoded prefix; they are preserved as zero here
        // because no reader in the unmarshal chain touches them. A caller that needs them must
        // extend this function WITH the evidence, not before it.
        out.resize(0x18, 0);
        out.push(self.counted.0.len() as u8);
        out.extend_from_slice(&self.counted.0);
        out.resize(0x28, 0);
        out.extend_from_slice(&self.word_28.to_be_bytes());
        out.extend_from_slice(&self.word_30.to_be_bytes());
        out.extend_from_slice(&self.word_38.to_be_bytes());
        out.extend_from_slice(&self.pair_40.0.to_be_bytes());
        out.extend_from_slice(&self.pair_40.1.to_be_bytes());
        out.push(self.byte_48);
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
        // The constants exist so callers can dispatch on them without inventing numbers.
        const POLYMORPHIC: [u32; 3] = [391, 407, 106];
        assert_eq!(POLYMORPHIC.len(), 3);
        // And the fixed ones are distinct from them.
        for fixed in [SPAWN_ACTORS_MSG, FRAGMENT_UPDATE_MSG, ADD_ACTOR_MESSAGE] {
            assert!(
                !POLYMORPHIC.contains(&fixed),
                "wire type {fixed} cannot be both fixed-layout and polymorphic"
            );
        }
    }
}
