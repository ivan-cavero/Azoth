//! The local player's SPAWN record: a captured template, served verbatim.
//!
//! WHY THIS EXISTS
//! ===============
//! `record_id` 1 arrives in two variants, and they are not interchangeable:
//!
//! | variant | fragments | payload | carries a position? |
//! | --- | --- | --- | --- |
//! | **spawn** (this module) | 48 | 46,393 B | **yes** — x/y at payload offsets 38332/38336 |
//! | **ongoing** ([`crate::player_record`]) | 9 | 7,154 B | **no** — `key=16` has no position at all |
//!
//! The spawn variant is the record that moves the client from `WaitingForPlayerSpawn` to `InGame`
//! (`odd/tasks/phase-3-world.md` S3). Because the ongoing variant carries no position, **this record
//! is the server's only lever on where a player starts**: nothing in the 1 Hz state stream can
//! correct it afterwards. That asymmetry is why this module exists separately instead of being a
//! case inside `player_record`.
//!
//! THIS IS A CAPTURED TEMPLATE, NOT A COMPOSED MESSAGE
//! ==================================================
//! The record cannot be composed. Its 48 fragments are per-component payloads whose per-type codecs
//! are still an open decode — [`crate::fragment`] documents why a fragment cannot be walked unaided,
//! and plan §8.6 is the plan's own statement that these layouts are not decoded — so there is no way
//! to write one from fields; a composer here would be a guess wearing a struct.
//!
//! Serving captured bytes is sanctioned rather than tolerated: `odd/tasks/phase-3-world.md` S7
//! requires captured payloads to live as templates **with their capture id and a test that they
//! still parse**, and forbids the captured byte string itself from living in a library crate. This
//! module keeps that rule: no payload bytes are embedded here — the payload is a test fixture, and
//! what this module carries is its measured shape. It is the boundary that makes the provenance
//! explicit: the dimensions are checked, the capture block and build SHA-256 are named in
//! `tests/fixtures/spawn-template.json`, and nothing here is a decompiler guess.
//!
//! THE ONLY MUTATION IS THE ACTOR ID
//! ================================
//! [`SpawnRecord::with_actor_id`] rewrites 16 bytes at [`ACTOR_ID_OFFSET`] and nothing else, and
//! `tests/spawn_template.rs` asserts that exactly those 16 bytes differ. Everything else is
//! byte-preserved on purpose: a fragment carries no length field, so a rewrite that shifted one byte
//! would not be recoverable — the boundaries cannot be recomputed from the payload.
//!
//! The offset is *verified*, not assumed: the four bytes `00 00 00 02` precede the field in the
//! captured bytes, which is the shape the census records, and the value matches the actor id
//! measured live in `research/docs/PRIVATE-CLIENT-RUNBOOK.md`. If that anchor is not there,
//! [`SpawnRecord::actor_id_offset`] returns `None` and the rewrite is an error rather than a silent
//! no-op — a no-op would be indistinguishable from a rewrite the client ignored.
//!
//! WHAT IS NOT REAL IN THE TEMPLATE
//! ===============================
//! The capture is redacted: 1,802 bytes of this payload are zeros where the source held identifiers.
//! The prototype replays these same bytes and reaches `InGame`, so this is the proven shape, but the
//! fixture declares the redaction and the tests assert that neither the actor id nor the position
//! falls inside a redacted span.

use crate::error::WireError;

/// The `record_id` of the local player's spawn record.
pub const SPAWN_RECORD_ID: u8 = 1;

/// Fragment count of the spawn variant.
///
/// This is the client's own measured nested-call count for the record (`FUN_146af20d0` →
/// `FUN_146af2340`), not an inference from the bytes: a fragment carries no length, so the count
/// cannot be recovered from the payload alone.
pub const SPAWN_FRAGMENT_COUNT: usize = 48;

/// Payload length of the spawn variant, in bytes.
pub const SPAWN_PAYLOAD_LEN: usize = 46_393;

/// Payload offset of the local player's 16-byte actor id.
pub const ACTOR_ID_OFFSET: usize = 29_731;

/// Length of the actor id field, in bytes.
pub const ACTOR_ID_LEN: usize = 16;

/// The four bytes that immediately precede the actor id in the captured payload.
///
/// Their presence is the structural check that the field at [`ACTOR_ID_OFFSET`] is still the actor
/// id: the census records the shape as `<slice GUID><00 00 00 02><16-byte actor id>`.
const ACTOR_ID_ANCHOR: [u8; 4] = [0x00, 0x00, 0x00, 0x02];

/// Payload offset of the spawn position's x coordinate, a big-endian `f32`.
pub const POSITION_X_OFFSET: usize = 38_332;

/// Payload offset of the spawn position's y coordinate, a big-endian `f32`.
pub const POSITION_Y_OFFSET: usize = 38_336;

/// A captured `record_id 1` spawn payload.
///
/// The payload is held whole and unparsed. Splitting it into fragments needs the 48 boundaries,
/// which only the client knows, so a caller that wants a fragment must supply them; the record
/// itself is only ever served or retargeted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpawnRecord {
    /// The record id, which must be [`SPAWN_RECORD_ID`].
    pub record_id: u8,
    /// The payload bytes, from `record_id` to the end of the record.
    pub payload: Vec<u8>,
}

impl SpawnRecord {
    /// Serve the template verbatim, retargeted to a character.
    ///
    /// "Verbatim" is enforced, not promised: the record id, the fragment count and the exact payload
    /// length are all checked, because the offsets this module documents (actor id, position) are
    /// only valid for this length. A caller that needs a different record needs a different module.
    ///
    /// # Errors
    /// [`WireError::Truncated`] when the payload is shorter than the two-byte record header,
    /// [`WireError::OutOfRange`] when the record id is not [`SPAWN_RECORD_ID`], and
    /// [`WireError::LengthMismatch`] when the fragment count or the payload length is not the
    /// measured one. The fragment-count check follows [`crate::player_record`], which uses the same
    /// variant for the same reason: a count that disagrees with the expected layout is a length
    /// disagreement, not a range violation.
    pub fn from_template(payload: &[u8]) -> Result<Self, WireError> {
        if payload.len() < 2 {
            return Err(WireError::truncated("spawn record header", 2, payload.len()));
        }
        let record_id = payload[0];
        if record_id != SPAWN_RECORD_ID {
            return Err(WireError::OutOfRange {
                field: "spawn record id",
                value: u64::from(record_id),
                limit: u64::from(SPAWN_RECORD_ID) + 1,
            });
        }
        let declared = usize::from(payload[1]);
        if declared != SPAWN_FRAGMENT_COUNT {
            return Err(WireError::LengthMismatch {
                declared: SPAWN_FRAGMENT_COUNT,
                actual: declared,
            });
        }
        if payload.len() != SPAWN_PAYLOAD_LEN {
            return Err(WireError::LengthMismatch {
                declared: SPAWN_PAYLOAD_LEN,
                actual: payload.len(),
            });
        }
        Ok(Self {
            record_id,
            payload: payload.to_vec(),
        })
    }

    /// The record payload, unchanged.
    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    /// Locate the local player's actor id inside the payload, if it is present.
    ///
    /// This does not search: 38 occurrences of the four-byte anchor exist in the payload, so a
    /// search would find the wrong one. It verifies the documented offset against its documented
    /// neighbours — the `<00 00 00 02>` anchor before it, and 16 non-zero bytes in it (a redacted or
    /// absent field is zeros, and an all-zero actor id is not an actor id).
    #[must_use]
    pub fn actor_id_offset(&self) -> Option<usize> {
        let anchor_start = ACTOR_ID_OFFSET.checked_sub(ACTOR_ID_ANCHOR.len())?;
        let end = ACTOR_ID_OFFSET.checked_add(ACTOR_ID_LEN)?;
        let bytes = self.payload.get(..end)?;
        if bytes[anchor_start..ACTOR_ID_OFFSET] != ACTOR_ID_ANCHOR {
            return None;
        }
        if bytes[ACTOR_ID_OFFSET..].iter().all(|b| *b == 0) {
            return None;
        }
        Some(ACTOR_ID_OFFSET)
    }

    /// Rewrite the actor id, leaving every other byte alone.
    ///
    /// This is the only mutation the server performs on this record: a spawned actor must carry an
    /// identity the server can address afterwards, and the captured one belongs to the capture's
    /// character.
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] when [`actor_id_offset`](Self::actor_id_offset) is unknown. The
    /// crate uses that variant for "the substitution target does not exist" — see
    /// [`crate::player_record::PlayerRecord::with_payload`] — and reporting it is the point: a
    /// silent no-op is indistinguishable from a rewrite the client ignored.
    pub fn with_actor_id(&self, actor: [u8; ACTOR_ID_LEN]) -> Result<Self, WireError> {
        let offset = self.actor_id_offset().ok_or(WireError::OutOfRange {
            field: "spawn record actor id offset",
            value: 0,
            limit: 0,
        })?;
        let mut payload = self.payload.clone();
        payload[offset..offset + ACTOR_ID_LEN].copy_from_slice(&actor);
        Ok(Self {
            record_id: self.record_id,
            payload,
        })
    }
}
