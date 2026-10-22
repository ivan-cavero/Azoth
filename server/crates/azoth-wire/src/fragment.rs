//! The fragment grammar: `[varint key][varint type_index][payload]`.
//!
//! THERE IS NO LENGTH FIELD
//! ========================
//! This is the fact that shapes everything else about the state bundle. A
//! fragment's payload length is implied by its type — the client consumes it
//! through that type object's reader — so a fragment cannot be walked from its
//! bytes alone. That is why:
//!
//! * [`parse_fragment`] needs a fragment already sliced at a known boundary;
//! * [`split_record_payload`] takes the boundaries from the client rather than
//!   computing them;
//! * the per-type payload encodings are a separate, still-open decode (§8.6 of
//!   the plan), and decoding them is the only way to walk a record unaided.
//!
//! THE HEADER WAS MEASURED, NOT GUESSED
//! ====================================
//! A probe hooked the record reader (`FUN_146af20d0`), the fragment reader
//! (`FUN_146af2340`) and the shared prefix-varint reader (`FUN_14087b5c0`), and
//! logged each fragment's offset from the record start plus every varint read
//! inside it. Across **300 fragments** the first two varints sit at offset 0 and
//! 1 in every single one, with no exceptions; further varints begin at offset 5
//! or later and are payload-internal. That is the evidence for a two-varint
//! header and no length prefix.
//!
//! Keys and types bind one-to-one: 48 distinct keys and 47 distinct types across
//! the spawn record, with no key ever mapping to two types. The keys are sparse
//! (0, 1, 2, 4, 5, 9, 10, 12, 13, 14, 16, 19, 20, 22, 27, 29, 31, … 77), which
//! is what a component slot table with freed slots looks like.

use crate::error::WireError;
use crate::varint;

/// One `[varint key][varint type_index][payload]` fragment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Fragment {
    /// The component slot. Sparse, and bound one-to-one with `type_index`.
    pub key: u64,
    /// The component type, which selects the payload's reader.
    pub type_index: u64,
    /// The payload, whose length only the type's reader knows.
    pub payload: Vec<u8>,
}

/// The two varints that begin a fragment, and how many bytes they occupy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FragmentHeader {
    /// The component slot.
    pub key: u64,
    /// The component type.
    pub type_index: u64,
    /// Bytes the two varints occupy.
    pub header_size: usize,
}

impl Fragment {
    /// Build a fragment from its parts.
    #[must_use]
    pub fn new(key: u64, type_index: u64, payload: Vec<u8>) -> Self {
        Self {
            key,
            type_index,
            payload,
        }
    }

    /// Encode back to the wire form.
    ///
    /// # Errors
    /// Propagates a varint range error.
    pub fn encode(&self) -> Result<Vec<u8>, WireError> {
        let mut out = varint::encode(self.key)?;
        varint::encode_into(self.type_index, &mut out)?;
        out.extend_from_slice(&self.payload);
        Ok(out)
    }
}

/// Read the two header varints at `offset`.
///
/// # Errors
/// [`WireError::Truncated`] or [`WireError::VarintTooLong`] from either varint.
pub fn read_header(data: &[u8], offset: usize) -> Result<FragmentHeader, WireError> {
    let (key, after_key) = varint::decode(data, offset)?;
    let (type_index, after_type) = varint::decode(data, after_key)?;
    Ok(FragmentHeader {
        key,
        type_index,
        header_size: after_type - offset,
    })
}

/// Decode one fragment that has already been sliced at a known boundary.
///
/// # Errors
/// As [`read_header`].
pub fn parse(fragment: &[u8]) -> Result<Fragment, WireError> {
    let header = read_header(fragment, 0)?;
    Ok(Fragment {
        key: header.key,
        type_index: header.type_index,
        payload: fragment[header.header_size..].to_vec(),
    })
}

/// Slice one record's payload into fragments at the given boundaries.
///
/// `boundaries` are offsets into `payload` where each fragment STARTS, in
/// strictly ascending order; the last fragment runs to the end. They come from
/// the client (`research/derived/state-bundle-fragments.json`) or from a caller
/// that knows the layout, because a fragment carries no length of its own.
///
/// A first boundary of 2 is the normal case: the record header is one byte of
/// record id plus one of fragment count, and those two bytes are not a fragment.
/// A first boundary of 0 is also accepted, for a caller passing the fragment
/// region alone.
///
/// # Errors
/// [`WireError::BadBoundaries`] when the list is empty, not strictly ascending,
/// negative in effect, or when its last entry is past the payload.
pub fn split_record_payload<'a>(
    payload: &'a [u8],
    boundaries: &[usize],
) -> Result<Vec<&'a [u8]>, WireError> {
    if boundaries.is_empty() {
        return Err(WireError::BadBoundaries {
            reason: "no boundaries given",
        });
    }
    for pair in boundaries.windows(2) {
        if pair[0] >= pair[1] {
            return Err(WireError::BadBoundaries {
                reason: "boundaries must be strictly ascending",
            });
        }
    }
    let last = boundaries[boundaries.len() - 1];
    if last >= payload.len() {
        return Err(WireError::BadBoundaries {
            reason: "last boundary is past the payload",
        });
    }
    let mut out = Vec::with_capacity(boundaries.len());
    for (i, &start) in boundaries.iter().enumerate() {
        let end = boundaries.get(i + 1).copied().unwrap_or(payload.len());
        out.push(&payload[start..end]);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_a_fragment() {
        let fragment = Fragment::new(16, 11, vec![1, 2, 3, 4]);
        let encoded = fragment.encode().expect("encodes");
        // key 16 is one byte, type 11 is one byte, then the payload.
        assert_eq!(encoded, vec![16, 11, 1, 2, 3, 4]);
        assert_eq!(parse(&encoded).expect("parses"), fragment);
    }

    /// A key above 127 widens its varint, which is why a writer may never
    /// overwrite a key in place.
    #[test]
    fn a_wide_key_shifts_the_header() {
        let fragment = Fragment::new(200, 3, vec![0xAA]);
        let encoded = fragment.encode().expect("encodes");
        assert_eq!(encoded.len(), 4); // 2 + 1 + 1
        let header = read_header(&encoded, 0).expect("header");
        assert_eq!(header.key, 200);
        assert_eq!(header.type_index, 3);
        assert_eq!(header.header_size, 3);
    }

    /// The header is two varints at offset 0 and 1 for every measured fragment.
    #[test]
    fn header_is_two_leading_varints() {
        let encoded = Fragment::new(1, 1, vec![9, 9, 9]).encode().expect("encodes");
        let header = read_header(&encoded, 0).expect("header");
        assert_eq!(header.header_size, 2);
        assert_eq!(&encoded[header.header_size..], &[9, 9, 9]);
    }

    #[test]
    fn splits_at_known_boundaries() {
        let payload = vec![0, 3, 0xAA, 0xBB, 0xCC, 0xDD];
        let parts = split_record_payload(&payload, &[2, 3]).expect("splits");
        assert_eq!(parts.len(), 2);
        assert_eq!(parts[0], &[0xAA]);
        assert_eq!(parts[1], &[0xBB, 0xCC, 0xDD]);
    }

    #[test]
    fn rejects_unsorted_boundaries() {
        let payload = vec![0; 8];
        let err = split_record_payload(&payload, &[4, 2]).expect_err("must fail");
        assert!(matches!(err, WireError::BadBoundaries { .. }), "{err}");
    }

    #[test]
    fn rejects_a_boundary_past_the_payload() {
        let payload = vec![0; 4];
        let err = split_record_payload(&payload, &[4]).expect_err("must fail");
        assert!(matches!(err, WireError::BadBoundaries { .. }), "{err}");
    }

    #[test]
    fn rejects_empty_boundaries() {
        let err = split_record_payload(&[0, 1, 2], &[]).expect_err("must fail");
        assert!(matches!(err, WireError::BadBoundaries { .. }), "{err}");
    }
}
