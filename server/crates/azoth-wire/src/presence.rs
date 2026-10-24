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
//! `Replicate` (391) and `ReplicateClient` (407) are **polymorphic**: each constructs a record
//! for its component type and calls `vtable+0x90 / +0xa0 / +0xb0`, so shape is per component,
//! not per message. They stay out of this module. `UpdateMsg` (106) is fixed (prefix-varint
//! length ≤512 + blob) and is included below — earlier notes that lumped it with the
//! polymorphic pair were wrong (`presence-codecs.json`).
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
/// Wire type of `UpdateMsg`.
pub const UPDATE_MSG: u32 = 106;

/// The largest blob `UpdateMsg` accepts, in bytes.
///
/// Measured from `FUN_1407d8d50`, which rejects a length of `0x201` or more before copying.
pub const UPDATE_MSG_MAX_BLOB: usize = 512;

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

/// `UpdateMsg`: a prefix-varint length followed by that many raw bytes.
///
/// Measured from `FUN_1407c5840` → `FUN_1407d8d50`, which reads the length with the prefix-varint
/// ladder and rejects anything at or above `0x201`. **This message is not polymorphic** — an
/// earlier prediction that it would be a third per-type dispatcher was wrong.
///
/// A length-prefixed blob capped at 512 bytes is the natural carrier for one component fragment's
/// payload, with [`FragmentUpdateMsg`] supplying the identity. That reading is consistent with the
/// state-bundle model this project already decodes, but it is a reading: nothing here proves what
/// the blob contains.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdateMsg {
    /// The payload bytes, already length-stripped.
    pub blob: Vec<u8>,
}

impl UpdateMsg {
    /// Decode from a body.
    ///
    /// # Errors
    /// [`WireError::Truncated`] when the length prefix or the declared bytes are missing, and
    /// [`WireError::OutOfRange`] when the length exceeds [`UPDATE_MSG_MAX_BLOB`].
    pub fn decode(body: &[u8]) -> Result<Self, WireError> {
        let (declared, after_len) = crate::varint::decode(body, 0)?;
        let declared = declared as usize;
        if declared > UPDATE_MSG_MAX_BLOB {
            return Err(WireError::OutOfRange {
                field: "UpdateMsg length",
                value: declared as u64,
                limit: UPDATE_MSG_MAX_BLOB as u64 + 1,
            });
        }
        let available = body.len() - after_len;
        if available < declared {
            return Err(WireError::truncated(
                "UpdateMsg blob",
                declared,
                available,
            ));
        }
        Ok(Self {
            blob: body[after_len..after_len + declared].to_vec(),
        })
    }

    /// Encode to a body.
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] when the blob exceeds [`UPDATE_MSG_MAX_BLOB`].
    pub fn encode(&self) -> Result<Vec<u8>, WireError> {
        if self.blob.len() > UPDATE_MSG_MAX_BLOB {
            return Err(WireError::OutOfRange {
                field: "UpdateMsg blob",
                value: self.blob.len() as u64,
                limit: UPDATE_MSG_MAX_BLOB as u64 + 1,
            });
        }
        let mut out = crate::varint::encode(self.blob.len() as u64)?;
        out.extend_from_slice(&self.blob);
        Ok(out)
    }
}
