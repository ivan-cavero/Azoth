//! The local player's own state record (`record_id` 1): parse, substitute, re-emit.
//!
//! WHY THIS EXISTS
//! ===============
//! `record_id` 1 is the record that carries the local player's metadata to the client, and it is the
//! one record the server has ever been able to *change* rather than forward. It arrives in two
//! variants, and confusing them has cost this project whole sessions:
//!
//! | variant | fragments | payload | carries a position? |
//! | --- | --- | --- | --- |
//! | **spawn** | 48 | 46,393 B | **yes** — x/y at payload offsets 38332/38336 |
//! | **ongoing** | 9 | 7,154 B | **no** — `key=16` has a 49-byte payload and no position at all |
//!
//! The ongoing variant is what the 1 Hz state stream re-sends. Because it carries no position, **no
//! substitution inside it can move the player** — that was measured four ways and closed on
//! 2026-10-18. The position is spawn-only by design, and the ongoing position is client-authoritative.
//!
//! So this module exists to do the substitution the server CAN do (any fragment's payload), and its
//! docs record the one substitution that cannot work, so nobody re-derives it.
//!
//! THE BOUNDARIES ARE NOT COMPUTABLE
//! =================================
//! A fragment carries no length: its payload length is implied by its component type, which is
//! decoded by the client. So a record cannot be walked from its bytes alone, and the fragment
//! boundaries must come from the client. They are build-scoped measured data, supplied by the caller
//! — **not** embedded here, because a captured byte string is not production data and this crate has
//! no business carrying one.

use crate::error::WireError;
use crate::fragment::{Fragment, read_header};

/// The `record_id` of the local player's own state record.
pub const PLAYER_RECORD_ID: u8 = 1;

/// Fragment boundaries of the **ongoing** variant, as offsets into the record payload.
///
/// Measured from the client: nine fragments, and the last runs to the end. A first boundary of 2 is
/// the record header — one byte of `record_id` plus one of fragment count.
///
/// The bytes after this table are a *different* record: the 48-fragment spawn variant has its own
/// boundaries and its own length. Passing one variant's boundaries with the other's payload is the
/// mistake this constant's name is meant to prevent.
pub const ONGOING_BOUNDARIES: [usize; 9] = [2, 60, 3955, 4295, 4301, 4498, 5335, 5386, 7125];

/// The payload length of the ongoing variant.
pub const ONGOING_PAYLOAD_LEN: usize = 7154;

/// The component slot whose payload the server can substitute.
///
/// `key=16 type=11`, a 49-byte payload. It **varies across captured copies** (at payload bytes 8, 9
/// and 10) while every other fragment is byte-identical, which is why it is the interesting one —
/// and why the fact that it carries no position is worth stating loudly. See the module docs.
pub const MUTABLE_KEY: u64 = 16;

/// A `record_id 1` payload, parsed into its fragments.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlayerRecord {
    /// The record id, which must be [`PLAYER_RECORD_ID`].
    pub record_id: u8,
    /// The fragments, in wire order.
    pub fragments: Vec<Fragment>,
}

impl PlayerRecord {
    /// Parse a payload using the given boundaries.
    ///
    /// # Errors
    /// [`WireError::LengthMismatch`] when the payload's `record_id` or fragment count disagrees with
    /// what the caller expects, [`WireError::BadBoundaries`] from the split, or a fragment header
    /// error. The fragment count check is the one that catches a spawn payload handed ongoing
    /// boundaries: it is 48 against 9, and it fails immediately instead of producing nonsense.
    pub fn parse(payload: &[u8], boundaries: &[usize]) -> Result<Self, WireError> {
        if payload.len() < 2 {
            return Err(WireError::truncated("record header", 2, payload.len()));
        }
        let record_id = payload[0];
        let declared = usize::from(payload[1]);
        if declared != boundaries.len() {
            return Err(WireError::LengthMismatch {
                declared,
                actual: boundaries.len(),
            });
        }
        let slices = crate::fragment::split_record_payload(payload, boundaries)?;
        let mut fragments = Vec::with_capacity(slices.len());
        for slice in slices {
            let header = read_header(slice, 0)?;
            fragments.push(Fragment::new(
                header.key,
                header.type_index,
                slice[header.header_size..].to_vec(),
            ));
        }
        Ok(Self {
            record_id,
            fragments,
        })
    }

    /// Re-emit the payload.
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] when there are more than 255 fragments.
    pub fn encode(&self) -> Result<Vec<u8>, WireError> {
        let count = u8::try_from(self.fragments.len()).map_err(|_| WireError::OutOfRange {
            field: "player record fragment count",
            value: self.fragments.len() as u64,
            limit: 256,
        })?;
        let mut out = vec![self.record_id, count];
        for fragment in &self.fragments {
            out.extend_from_slice(&fragment.encode()?);
        }
        Ok(out)
    }

    /// The fragment with component slot `key`, if present.
    #[must_use]
    pub fn fragment(&self, key: u64) -> Option<&Fragment> {
        self.fragments.iter().find(|f| f.key == key)
    }

    /// Replace one fragment's payload, leaving its key and type alone.
    ///
    /// This is the only mutation the server performs on this record, and it is why the module exists.
    /// The key and type are preserved because they are what the client dispatches on: changing them
    /// would make the fragment a different component rather than a different value.
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] when no fragment has that key — a silent no-op would be
    /// indistinguishable from a substitution the client ignored, which is the failure mode this
    /// project has spent the most time on.
    pub fn with_payload(&self, key: u64, payload: Vec<u8>) -> Result<Self, WireError> {
        let mut fragments = self.fragments.clone();
        let slot = fragments
            .iter_mut()
            .find(|f| f.key == key)
            .ok_or(WireError::OutOfRange {
                field: "player record fragment key",
                value: key,
                limit: u64::MAX,
            })?;
        slot.payload = payload;
        Ok(Self {
            record_id: self.record_id,
            fragments,
        })
    }

    /// Total payload length this record encodes to.
    ///
    /// # Errors
    /// Propagates an encode error.
    pub fn encoded_len(&self) -> Result<usize, WireError> {
        Ok(self.encode()?.len())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The captured ongoing payload, exported by the fragment census.
    ///
    /// A test fixture, not production data: it lives in `tests/fixtures` and is `include_bytes!`d
    /// here only so the parse/substitute/encode machinery can be checked against real bytes.
    const CAPTURED: &[u8] = include_bytes!("../tests/fixtures/player-record-1.bin");

    #[test]
    fn the_captured_payload_has_the_documented_length() {
        assert_eq!(CAPTURED.len(), ONGOING_PAYLOAD_LEN);
        assert_eq!(CAPTURED[0], PLAYER_RECORD_ID);
        assert_eq!(usize::from(CAPTURED[1]), ONGOING_BOUNDARIES.len());
    }

    #[test]
    fn parsing_then_encoding_reproduces_the_capture() {
        let record = PlayerRecord::parse(CAPTURED, &ONGOING_BOUNDARIES).expect("parses");
        assert_eq!(record.encode().expect("encodes"), CAPTURED);
    }

    #[test]
    fn the_nine_fragments_have_the_measured_keys_and_types() {
        let record = PlayerRecord::parse(CAPTURED, &ONGOING_BOUNDARIES).expect("parses");
        let pairs: Vec<(u64, u64)> = record
            .fragments
            .iter()
            .map(|f| (f.key, f.type_index))
            .collect();
        assert_eq!(
            pairs,
            vec![
                (55, 4176),
                (19, 3133),
                (73, 5606),
                (9, 3935),
                (72, 5485),
                (74, 5691),
                (16, 11),
                (22, 3857),
                (44, 4236),
            ]
        );
    }

    /// The measured negative, encoded as a test so it cannot be re-derived by accident:
    /// the mutable fragment carries no position, so substituting it cannot move the player.
    #[test]
    fn the_mutable_fragment_carries_no_position() {
        let record = PlayerRecord::parse(CAPTURED, &ONGOING_BOUNDARIES).expect("parses");
        let fragment = record.fragment(MUTABLE_KEY).expect("key 16 is present");
        assert_eq!(fragment.type_index, 11, "key 16 binds to type 11");
        assert_eq!(
            fragment.payload.len(),
            49,
            "the documented 49-byte payload with no position"
        );
        // No big-endian f32 pair in the world coordinate range anywhere in it.
        let payload = &fragment.payload;
        let mut found = false;
        for offset in 0..payload.len().saturating_sub(7) {
            let x = f32::from_be_bytes([
                payload[offset],
                payload[offset + 1],
                payload[offset + 2],
                payload[offset + 3],
            ]);
            let y = f32::from_be_bytes([
                payload[offset + 4],
                payload[offset + 5],
                payload[offset + 6],
                payload[offset + 7],
            ]);
            if (9000.0..10000.0).contains(&x) && (2000.0..3000.0).contains(&y) {
                found = true;
            }
        }
        assert!(
            !found,
            "a position here would contradict the 2026-10-18 measurement"
        );
    }

    #[test]
    fn substituting_a_payload_changes_only_that_fragment() {
        let record = PlayerRecord::parse(CAPTURED, &ONGOING_BOUNDARIES).expect("parses");
        let replacement = vec![0xAB; 49];
        let edited = record
            .with_payload(MUTABLE_KEY, replacement.clone())
            .expect("key 16 exists");

        // The edited fragment changed.
        assert_eq!(edited.fragment(MUTABLE_KEY).expect("present").payload, replacement);
        // Every other fragment is byte-identical.
        for (before, after) in record.fragments.iter().zip(&edited.fragments) {
            if before.key == MUTABLE_KEY {
                continue;
            }
            assert_eq!(before, after, "key {} must not change", before.key);
        }
        // And the record still parses.
        let reencoded = edited.encode().expect("encodes");
        let reparsed = PlayerRecord::parse(&reencoded, &ONGOING_BOUNDARIES).expect("reparses");
        assert_eq!(reparsed, edited);
    }

    #[test]
    fn substituting_a_same_length_payload_keeps_the_record_length() {
        // Length preservation is what lets a caller patch a payload without re-deriving boundaries.
        let record = PlayerRecord::parse(CAPTURED, &ONGOING_BOUNDARIES).expect("parses");
        let original = record.fragment(MUTABLE_KEY).expect("present").payload.clone();
        let edited = record
            .with_payload(MUTABLE_KEY, vec![0x11; original.len()])
            .expect("exists");
        assert_eq!(
            edited.encoded_len().expect("len"),
            ONGOING_PAYLOAD_LEN,
            "a same-length substitution must not shift the record"
        );
    }

    #[test]
    fn substituting_an_unknown_key_is_an_error_not_a_no_op() {
        let record = PlayerRecord::parse(CAPTURED, &ONGOING_BOUNDARIES).expect("parses");
        let err = record
            .with_payload(999, vec![0])
            .expect_err("must fail");
        assert!(matches!(err, WireError::OutOfRange { .. }), "{err}");
    }

    /// Handing the ongoing boundaries a payload with a different fragment count fails immediately.
    ///
    /// This is the guard against mixing the two variants: the spawn record has 48 fragments.
    #[test]
    fn a_spawn_sized_fragment_count_is_rejected() {
        let mut spawn_like = CAPTURED.to_vec();
        spawn_like[1] = 48; // claim 48 fragments
        let err = PlayerRecord::parse(&spawn_like, &ONGOING_BOUNDARIES).expect_err("must fail");
        assert!(matches!(err, WireError::LengthMismatch { declared: 48, actual: 9 }), "{err}");
    }

    #[test]
    fn a_truncated_payload_is_rejected() {
        let err = PlayerRecord::parse(&[1], &ONGOING_BOUNDARIES).expect_err("must fail");
        assert!(matches!(err, WireError::Truncated { .. }), "{err}");
    }
}
