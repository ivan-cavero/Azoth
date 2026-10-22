//! The Javelin/AZ "prefix varint" used across every inbound typed message.
//!
//! THE ENCODING
//! ============
//! The number of LEADING 1-BITS in the first byte gives the number of
//! continuation bytes that follow. The first byte's remaining low bits are the
//! LOWEST bits of the value; the continuation bytes are a little-endian integer
//! placed above them.
//!
//! ```text
//! n = count of leading 1-bits in b0        (0..=4)
//! shift = 7 - n
//! value = (LE(continuation_bytes) << shift) | (b0 & ((1 << shift) - 1))
//! ```
//!
//! | first byte      | n | bytes | low bits | capacity |
//! | --------------- | - | ----- | -------- | -------- |
//! | `0x00..=0x7f`   | 0 | 1     | 7        | 2^7      |
//! | `0x80..=0xbf`   | 1 | 2     | 6        | 2^14     |
//! | `0xc0..=0xdf`   | 2 | 3     | 5        | 2^21     |
//! | `0xe0..=0xef`   | 3 | 4     | 4        | 2^28     |
//! | `0xf0..=0xff`   | 4 | 5     | 3        | 2^35     |
//!
//! WHY THE CONTINUATION BYTES ARE LITTLE-ENDIAN
//! ============================================
//! A decompiler renders the three-byte branch as a `CONCAT21(...) << 4`, which
//! reads like big-endian assembly. That is an artifact: the observed three-byte
//! value `d9 a9 05` is 46393, reachable only as `(0x05a9 << 5) | 25`. A
//! big-endian reading gives 1384633, larger than the 46407-byte message that
//! contains it, so the data falsifies it.
//!
//! WHY THIS MATTERS MORE THAN IT LOOKS
//! ===================================
//! The encoding was originally implemented LSB-first with 7-bit groups, and the
//! client read `a2 63` (meant for 12706) as 6370: the two halves were in the
//! wrong order, so every value over 63 bits decoded wrongly, truncating a
//! 12,706-byte message to 6,370 and desynchronising every message after it
//! (measured live 2026-09-24). The tests below pin the boundary values that
//! make that class of mistake visible.

use crate::error::WireError;

/// Largest value the encoding can represent: four continuation bytes give 35 bits.
pub const MAX_VALUE: u64 = (1 << 35) - 1;

/// Number of continuation bytes implied by the leading 1-bits of `first`.
#[must_use]
pub fn continuation_count(first: u8) -> usize {
    // count_leading_ones on a u8 gives exactly the run of 1s from the top, and
    // the format never uses more than four, so a 0xf0..=0xff byte reads as 4.
    first.leading_ones() as usize
}

/// Decode one prefix varint, returning `(value, next_offset)`.
///
/// # Errors
/// [`WireError::Truncated`] when a continuation byte is missing, and
/// [`WireError::VarintTooLong`] when the first byte announces more than four.
pub fn decode(data: &[u8], offset: usize) -> Result<(u64, usize), WireError> {
    let first = *data
        .get(offset)
        .ok_or_else(|| WireError::truncated("varint", 1, 0))?;
    let n = continuation_count(first);
    if n > 4 {
        return Err(WireError::VarintTooLong {
            offset,
            continuation: n,
        });
    }
    let end = offset + 1 + n;
    if end > data.len() {
        return Err(WireError::truncated(
            "varint continuation",
            n,
            data.len() - offset - 1,
        ));
    }
    if n == 0 {
        return Ok((u64::from(first), offset + 1));
    }
    let shift = 7 - n;
    let mut cont: u64 = 0;
    for (i, &byte) in data[offset + 1..end].iter().enumerate() {
        cont |= u64::from(byte) << (8 * i);
    }
    let low_mask = (1u64 << shift) - 1;
    let value = (cont << shift) | (u64::from(first) & low_mask);
    Ok((value, end))
}

/// Decode one prefix varint and return only its value.
///
/// # Errors
/// As [`decode`].
pub fn decode_from(data: &[u8], offset: usize) -> Result<u64, WireError> {
    decode(data, offset).map(|(value, _)| value)
}

/// Encoded byte length of `value`.
///
/// Capacity is `7 + 7n` bits for `n` continuation bytes, so the thresholds are
/// 2^7, 2^14, 2^21, 2^28, 2^35.
#[must_use]
pub fn size_of(value: u64) -> usize {
    if value < 0x80 {
        1
    } else if value < (1 << 14) {
        2
    } else if value < (1 << 21) {
        3
    } else if value < (1 << 28) {
        4
    } else {
        5
    }
}

/// Encode `value` as a prefix varint.
///
/// # Errors
/// [`WireError::OutOfRange`] when `value` exceeds [`MAX_VALUE`].
pub fn encode(value: u64) -> Result<Vec<u8>, WireError> {
    if value > MAX_VALUE {
        return Err(WireError::OutOfRange {
            field: "prefix varint",
            value,
            limit: MAX_VALUE + 1,
        });
    }
    if value < 0x80 {
        return Ok(vec![value as u8]);
    }
    let n = size_of(value) - 1;
    let shift = 7 - n;
    let low_mask = (1u64 << shift) - 1;
    let low = (value & low_mask) as u8;
    let high = value >> shift;
    // The leading byte's top n bits are 1s; its low `shift` bits are the low
    // bits of the value.
    let prefix = 0xFFu16 << (8 - n);
    let leading = ((prefix & 0xFF) as u8) | low;
    let mut out = Vec::with_capacity(1 + n);
    out.push(leading);
    out.extend_from_slice(&high.to_le_bytes()[..n]);
    Ok(out)
}

/// Append `value` to `out` as a prefix varint.
///
/// The hot path encodes into a buffer it already owns, so this avoids the
/// allocation [`encode`] makes.
///
/// # Errors
/// As [`encode`].
pub fn encode_into(value: u64, out: &mut Vec<u8>) -> Result<(), WireError> {
    out.extend_from_slice(&encode(value)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The values the format's own thresholds sit on, plus the observed corpus
    /// values. These are the cases a wrong bit order breaks.
    const ROUND_TRIP: &[u64] = &[
        0,
        1,
        0x7f,
        0x80,
        0xff,
        0x3fff,
        0x4000,
        0x1f_ffff,
        0x20_0000,
        0x0fff_ffff,
        0x1000_0000,
        MAX_VALUE,
        // Measured corpus values.
        349,  // 0x15d heartbeat
        7048, // 0x1b88
        692,  // a message length
        46393,
    ];

    #[test]
    fn round_trips_every_boundary() {
        for &value in ROUND_TRIP {
            let encoded = encode(value).expect("in range");
            let (decoded, next) = decode(&encoded, 0).expect("decodes");
            assert_eq!(decoded, value, "value {value} round-trip");
            assert_eq!(next, encoded.len(), "value {value} consumed all bytes");
        }
    }

    #[test]
    fn size_matches_encoded_length() {
        for &value in ROUND_TRIP {
            let encoded = encode(value).expect("in range");
            assert_eq!(
                size_of(value),
                encoded.len(),
                "size_of({value}) disagrees with encode"
            );
        }
    }

    /// The measured corpus anchors, as raw bytes. If the bit order regresses,
    /// these fail with the actual value in the message.
    #[test]
    fn decodes_the_corpus_anchors() {
        let cases: &[(&[u8], u64)] = &[
            (&[0x9d, 0x05], 349),         // type 0x15d
            (&[0x88, 0x6e], 7048),        // type 0x1b88
            (&[0xa3, 0x19], 1635),        // type 0x663
            (&[0xa0, 0x5a], 5792),        // type 0x16a0
            (&[0xb4, 0x0a], 692),         // a length
            (&[0xd9, 0xa9, 0x05], 46393), // the spawn record length
        ];
        for (bytes, expected) in cases {
            let (value, next) = decode(bytes, 0).expect("decodes");
            assert_eq!(value, *expected, "bytes {bytes:02x?}");
            assert_eq!(next, bytes.len());
            assert_eq!(&encode(value).expect("in range"), bytes, "re-encode");
        }
    }

    /// The live defect of 2026-09-24: a value written as LSB-first 7-bit groups
    /// is read back as a different number. 12706 must be `a2 c6`; the wrong
    /// order produced `a2 63`, which the client read as 6370.
    #[test]
    fn the_lsb_first_mistake_is_visible() {
        let encoded = encode(12706).expect("in range");
        assert_eq!(encoded, vec![0xa2, 0xc6]);
        let (value, _) = decode(&encoded, 0).expect("decodes");
        assert_eq!(value, 12706);
        // The bytes the old encoder produced, and what they actually mean.
        let (wrong, _) = decode(&[0xa2, 0x63], 0).expect("decodes");
        assert_eq!(wrong, 6370, "the 2026-09-24 truncation, reproduced");
    }

    #[test]
    fn rejects_a_truncated_varint() {
        // 0xc0 announces two continuation bytes; only one is present.
        let err = decode(&[0xc0, 0x01], 0).expect_err("must fail");
        assert!(matches!(err, WireError::Truncated { .. }), "{err}");
    }

    #[test]
    fn rejects_more_than_four_continuation_bytes() {
        // 0xfe has seven leading ones.
        let err = decode(&[0xfe, 0, 0, 0, 0, 0, 0, 0], 0).expect_err("must fail");
        assert!(matches!(err, WireError::VarintTooLong { .. }), "{err}");
    }

    #[test]
    fn rejects_out_of_range_encode() {
        let err = encode(MAX_VALUE + 1).expect_err("must fail");
        assert!(matches!(err, WireError::OutOfRange { .. }), "{err}");
    }

    /// Decoding at a non-zero offset must not read the prefix byte.
    #[test]
    fn decodes_at_an_offset() {
        let mut buf = vec![0xff, 0xff];
        buf.extend_from_slice(&encode(46393).expect("in range"));
        let (value, next) = decode(&buf, 2).expect("decodes");
        assert_eq!(value, 46393);
        assert_eq!(next, buf.len());
    }
}
