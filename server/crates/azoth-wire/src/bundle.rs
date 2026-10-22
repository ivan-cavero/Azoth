//! The type-0x08 state bundle: the entity/component replication record.
//!
//! THE LAYOUT
//! ==========
//! ```text
//! [00 01 <varint 0x08>]      typed marker
//! [8-byte prologue]          `01 <varint SEQ> 01 01 01 01 00 00`
//! [varint payload_length]
//! [payload]                  a SEQUENCE OF RECORDS, each:
//!                              [u8 record_id][u8 fragment_count][fragments…]
//! ```
//!
//! `SEQ` is the replication counter the client's unreliable-replication gate
//! compares against its high-water mark. The six bytes after it are invariant
//! across all 78 captured bundles, which makes them a layout tripwire: if they
//! move, the build changed and every offset here is suspect.
//!
//! HOW THE RECORD GRAMMAR WAS ESTABLISHED
//! ======================================
//! An earlier model read the prologue's bytes as `[kind][record_id][fragment_count]`
//! and then treated the whole length-prefixed payload as ONE fragment's payload.
//! That model consumed every captured body exactly — which is why it looked right —
//! but "consumes exactly" cannot discriminate when the remainder is opaque.
//!
//! The discriminating evidence is the client's own behaviour, measured with a
//! probe on `FUN_146af20d0` (one record) and `FUN_146af2340` (one fragment):
//! the record's `fragment_count` byte **equals the measured nested-call count in
//! every one of 90 distinct records** (`01 30`→48, `01 09`→9, `02 03`→3,
//! `03 01`→1, `0d 06`→6, `1d 13`→19). Byte-exact on the 78-byte bundle at capture
//! seq 0xab: payload length 66, and it is two records of exactly 33 bytes each.
//!
//! So the real `fragment_count` for the spawn record is **48**, not 1.
//!
//! THE REPLICATION GATE, AND WHY A COUNTER MUST BE RE-ENCODED
//! ==========================================================
//! The client accepts an unreliable replication message only when its context id
//! matches and its counter is strictly greater than its stored high-water mark
//! (`FUN_14643e7b0`). Because the counter is a varint, raising it past the
//! client's high-water can widen it: 53 is one byte, 0x80 is two. Writing the
//! byte in place shifts everything after it and produces the measured
//! `Failed to unmarshal … ValidationError`. [`with_replication_seq`] therefore
//! re-encodes rather than overwrites, and that is the whole reason it exists.

use crate::error::WireError;
use crate::varint;
use crate::{STATE_BUNDLE_TYPE, TYPE_MARKER};

/// The six prologue bytes that follow the replication counter.
///
/// Invariant across every captured bundle. A mismatch is a build change.
pub const PROLOGUE_TAIL: [u8; 6] = [0x01, 0x01, 0x01, 0x01, 0x00, 0x00];

/// The prologue's leading byte.
const PROLOGUE_HEAD: u8 = 0x01;

/// Offset of the replication counter, from the start of the body.
const SEQ_OFFSET: usize = 4;

/// A parsed type-0x08 body.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BundleBody {
    /// The replication counter the client's gate compares against.
    pub replication_seq: u64,
    /// The record sequence, kept raw because walking it needs the per-type codecs.
    pub payload: Vec<u8>,
}

/// One `[u8 record_id][u8 fragment_count][fragments…]` record.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Record {
    /// Indexes the client's handler table at `state + 0x608 + record_id*0x10`.
    pub record_id: u8,
    /// Fragments, in order. The FIRST one selects the client's apply path.
    pub fragments: Vec<crate::fragment::Fragment>,
}

impl Record {
    /// Encode the record.
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] when there are more than 255 fragments, or a
    /// fragment's own encoding fails.
    pub fn encode(&self) -> Result<Vec<u8>, WireError> {
        let count = u8::try_from(self.fragments.len()).map_err(|_| WireError::OutOfRange {
            field: "fragment count",
            value: self.fragments.len() as u64,
            limit: 256,
        })?;
        let mut out = vec![self.record_id, count];
        for fragment in &self.fragments {
            out.extend_from_slice(&fragment.encode()?);
        }
        Ok(out)
    }
}

/// Encode a typed marker: `00 01 <varint type>`.
///
/// # Errors
/// Propagates a varint range error.
pub fn encode_type_marker(type_id: u32) -> Result<Vec<u8>, WireError> {
    let mut out = TYPE_MARKER.to_vec();
    varint::encode_into(u64::from(type_id), &mut out)?;
    Ok(out)
}

/// Read a typed marker, returning `(type_id, offset_after_marker)`.
///
/// # Errors
/// [`WireError::MissingTypeMarker`] or [`WireError::Truncated`].
pub fn read_type_marker(body: &[u8]) -> Result<(u64, usize), WireError> {
    if body.len() < 2 {
        return Err(WireError::truncated("typed marker", 2, body.len()));
    }
    let found = [body[0], body[1]];
    if found != TYPE_MARKER {
        return Err(WireError::MissingTypeMarker { found });
    }
    varint::decode(body, 2)
}

/// True when `body` starts with a well-formed type-0x08 marker.
#[must_use]
pub fn looks_like_state_bundle(body: &[u8]) -> bool {
    matches!(read_type_marker(body), Ok((id, _)) if id == u64::from(STATE_BUNDLE_TYPE))
}

/// Parse a full state bundle body, marker included.
///
/// When `strict`, the payload length must reach the end of the body exactly.
/// That check is meaningful now that the payload is a record sequence with its
/// own structure, rather than a tautology over an opaque blob.
///
/// # Errors
/// [`WireError::MissingTypeMarker`], [`WireError::Truncated`],
/// [`WireError::PrologueMismatch`] (the build tripwire), or
/// [`WireError::LengthMismatch`] in strict mode.
pub fn decode(body: &[u8], strict: bool) -> Result<BundleBody, WireError> {
    let (type_id, _after_marker) = read_type_marker(body)?;
    if type_id != u64::from(STATE_BUNDLE_TYPE) {
        return Err(WireError::OutOfRange {
            field: "bundle type",
            value: type_id,
            limit: u64::from(STATE_BUNDLE_TYPE) + 1,
        });
    }
    if body.len() <= SEQ_OFFSET {
        return Err(WireError::truncated("bundle prologue", SEQ_OFFSET + 1, body.len()));
    }
    let (seq, after_seq) = varint::decode(body, SEQ_OFFSET)?;
    let tail_start = after_seq;
    let tail_end = tail_start + PROLOGUE_TAIL.len();
    if tail_end > body.len() {
        return Err(WireError::truncated(
            "bundle prologue tail",
            PROLOGUE_TAIL.len(),
            body.len() - tail_start,
        ));
    }
    let mut found = [0u8; 6];
    found.copy_from_slice(&body[tail_start..tail_end]);
    if found != PROLOGUE_TAIL {
        return Err(WireError::PrologueMismatch {
            expected: PROLOGUE_TAIL,
            found,
        });
    }
    let (length, after_len) = varint::decode(body, tail_end)?;
    let payload = &body[after_len..];
    if strict && payload.len() != length as usize {
        return Err(WireError::LengthMismatch {
            declared: length as usize,
            actual: payload.len(),
        });
    }
    Ok(BundleBody {
        replication_seq: seq,
        payload: payload.to_vec(),
    })
}

/// Encode a type-0x08 body around an already-built record payload.
///
/// The inverse of [`decode`]. This is the right tool when a caller has patched
/// bytes inside a payload WITHOUT changing its length: going through here keeps
/// the prologue and the length field aligned whatever width the counter needs,
/// which a raw byte write does not.
///
/// # Errors
/// Propagates a varint range error.
pub fn encode(replication_seq: u64, payload: &[u8]) -> Result<Vec<u8>, WireError> {
    let mut out = encode_type_marker(STATE_BUNDLE_TYPE)?;
    out.push(PROLOGUE_HEAD);
    varint::encode_into(replication_seq, &mut out)?;
    out.extend_from_slice(&PROLOGUE_TAIL);
    varint::encode_into(payload.len() as u64, &mut out)?;
    out.extend_from_slice(payload);
    Ok(out)
}

/// Build a body from records the SERVER owns.
///
/// This is the difference between forwarding a captured bundle and sending one
/// we composed: the caller supplies the counter, the record ids, and every
/// fragment's key, type and payload. Composing the captured local-player record
/// from its fragments reproduces the captured body byte for byte, which is what
/// makes the composition trustworthy.
///
/// # Errors
/// Propagates a record or varint encoding error.
pub fn compose(replication_seq: u64, records: &[Record]) -> Result<Vec<u8>, WireError> {
    let mut payload = Vec::new();
    for record in records {
        payload.extend_from_slice(&record.encode()?);
    }
    encode(replication_seq, &payload)
}

/// Return `body` with its replication counter set to `seq`.
///
/// Re-encodes rather than overwriting the counter's byte, because the counter is
/// a varint and a wider value would shift the prologue and the payload. A raw
/// byte write here is the measured `ValidationError` of 2026-10-14.
///
/// # Errors
/// Propagates a decode or encode error.
pub fn with_replication_seq(body: &[u8], seq: u64) -> Result<Vec<u8>, WireError> {
    let parsed = decode(body, true)?;
    encode(seq, &parsed.payload)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fragment::Fragment;

    fn player_record_payload() -> Vec<u8> {
        // record 1, three fragments, byte-identical re-encoding.
        let record = Record {
            record_id: 1,
            fragments: vec![
                Fragment::new(16, 11, vec![0xAA; 4]),
                Fragment::new(19, 3, vec![0xBB; 2]),
                Fragment::new(20, 5, vec![]),
            ],
        };
        record.encode().expect("encodes")
    }

    #[test]
    fn round_trips_a_composed_bundle() {
        let payload = player_record_payload();
        let body = encode(53, &payload).expect("encodes");
        let parsed = decode(&body, true).expect("decodes");
        assert_eq!(parsed.replication_seq, 53);
        assert_eq!(parsed.payload, payload);
        assert_eq!(encode(53, &parsed.payload).expect("encodes"), body);
    }

    #[test]
    fn prologue_bytes_are_exact() {
        let body = encode(0x26, &[0x00]).expect("encodes");
        // 00 01 08 | 01 26 01 01 01 01 00 00 | 01 | 00
        assert_eq!(
            body,
            vec![0x00, 0x01, 0x08, 0x01, 0x26, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00]
        );
    }

    /// The gate's counter is a varint: crossing 0x80 widens it and shifts the
    /// prologue and payload. Re-encoding keeps them aligned; overwriting a byte
    /// does not.
    #[test]
    fn widening_the_counter_keeps_the_body_aligned() {
        let payload = player_record_payload();
        let narrow = encode(0x26, &payload).expect("encodes");
        let wide = with_replication_seq(&narrow, 0x80).expect("widens");
        assert_eq!(wide.len(), narrow.len() + 1, "the counter grew by a byte");
        let parsed = decode(&wide, true).expect("decodes");
        assert_eq!(parsed.replication_seq, 0x80);
        assert_eq!(parsed.payload, payload, "the payload must not shift");
    }

    #[test]
    fn compose_matches_encode_of_the_joined_records() {
        let records = vec![
            Record {
                record_id: 1,
                fragments: vec![Fragment::new(16, 11, vec![1, 2])],
            },
            Record {
                record_id: 2,
                fragments: vec![Fragment::new(0, 7, vec![])],
            },
        ];
        let composed = compose(9, &records).expect("composes");
        let mut joined = Vec::new();
        for record in &records {
            joined.extend_from_slice(&record.encode().expect("encodes"));
        }
        assert_eq!(composed, encode(9, &joined).expect("encodes"));
    }

    #[test]
    fn detects_a_prologue_mismatch() {
        let mut body = encode(1, &[0x00]).expect("encodes");
        // Break one of the six invariant bytes.
        body[6] = 0x02;
        let err = decode(&body, true).expect_err("must fail");
        assert!(matches!(err, WireError::PrologueMismatch { .. }), "{err}");
    }

    #[test]
    fn detects_a_length_mismatch_in_strict_mode() {
        let mut body = encode(1, &[0x00, 0x00]).expect("encodes");
        body.push(0xFF); // one byte more than the length field says
        let err = decode(&body, true).expect_err("must fail");
        assert!(matches!(err, WireError::LengthMismatch { .. }), "{err}");
        // Lenient mode accepts it, which is what a caller inspecting a
        // suspect body needs.
        assert!(decode(&body, false).is_ok());
    }

    #[test]
    fn rejects_a_non_bundle_type() {
        let body = vec![0x00, 0x01, 0x09, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00];
        let err = decode(&body, true).expect_err("must fail");
        assert!(matches!(err, WireError::OutOfRange { .. }), "{err}");
        assert!(!looks_like_state_bundle(&body));
    }

    #[test]
    fn rejects_a_missing_marker() {
        let err = decode(&[0xAA, 0xBB, 0x08], true).expect_err("must fail");
        assert!(matches!(err, WireError::MissingTypeMarker { .. }), "{err}");
    }

    #[test]
    fn rejects_a_record_with_too_many_fragments() {
        let record = Record {
            record_id: 1,
            fragments: vec![Fragment::new(0, 0, vec![]); 256],
        };
        let err = record.encode().expect_err("must fail");
        assert!(matches!(err, WireError::OutOfRange { .. }), "{err}");
    }
}
