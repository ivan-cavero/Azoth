//! The Javelin/AZ "prefix varint" used across every typed message.
//!
//! Ported from `services/world/src/azoth_world/javelin/varint.py`, which is the
//! reference implementation: it was derived from the client's own reader
//! (`FUN_14087b5c0`) and checked against every server->client message in the capture
//! (137 of 138 types round-trip; the exception is the first message of a datagram,
//! which carries a preamble the record layer does not model).
//!
//! THE ENCODING. The number of LEADING 1-BITS in the first byte gives the number of
//! continuation bytes that follow. The first byte's remaining low bits are the LOWEST
//! bits of the value; the continuation bytes are a little-endian integer placed above
//! them.
//!
//! ```text
//! n = count of leading 1-bits in b0        (0..4)
//! shift = 7 - n
//! value = (LE(continuation_bytes) << shift) | (b0 & ((1 << shift) - 1))
//! ```
//!
//! | first byte | n | bytes | low bits | capacity |
//! | ---------- | - | ----- | -------- | -------- |
//! | 0x00..0x7f | 0 | 1     | 7        | 2^7      |
//! | 0x80..0xbf | 1 | 2     | 6        | 2^14     |
//! | 0xc0..0xdf | 2 | 3     | 5        | 2^21     |
//! | 0xe0..0xef | 3 | 4     | 4        | 2^28     |
//! | 0xf0..0xff | 4 | 5     | 3        | 2^35     |
//!
//! WHY THE CONTINUATION BYTES ARE LITTLE-ENDIAN. Ghidra renders the 3-byte branch as a
//! big-endian assembly with a 4-bit shift. That is a decompiler artifact: the observed
//! 3-byte value `d9 a9 05` is 46393, reachable only as `(0x05a9 << 5) | 25`. A
//! big-endian reading gives 1384633, which is larger than the 46407-byte message that
//! contains it, so the data falsifies it.

/// 4 continuation bytes = 35 usable bits.
pub const MAX_VALUE: u64 = (1 << 35) - 1;

/// A malformed prefix varint (truncated, or larger than 5 bytes).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VarintError(pub String);

impl std::fmt::Display for VarintError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for VarintError {}

/// Number of continuation bytes implied by the leading 1-bits of `first`.
fn continuation_count(first: u8) -> usize {
    let mut n = 0usize;
    let mut mask = 0x80u8;
    while first & mask != 0 {
        n += 1;
        mask >>= 1;
    }
    n
}

/// Decode one prefix varint. Returns `(value, next_offset)`.
pub fn decode(data: &[u8], offset: usize) -> Result<(u64, usize), VarintError> {
    if offset >= data.len() {
        return Err(VarintError(format!("varint at {offset}: out of data")));
    }
    let first = data[offset];
    let n = continuation_count(first);
    let end = offset + 1 + n;
    if end > data.len() {
        return Err(VarintError(format!(
            "varint at {offset}: first byte 0x{first:02x} needs {n} more byte(s) but only {} remain",
            data.len() - offset - 1
        )));
    }
    if n == 0 {
        return Ok((u64::from(first), offset + 1));
    }
    let shift = 7 - n;
    let mut cont = 0u64;
    for (i, byte) in data[offset + 1..end].iter().enumerate() {
        cont |= u64::from(*byte) << (8 * i);
    }
    let value = (cont << shift) | u64::from(first & ((1u8 << shift) - 1));
    Ok((value, end))
}

/// Decode one prefix varint and return only its value.
pub fn decode_from(data: &[u8], offset: usize) -> Result<u64, VarintError> {
    decode(data, offset).map(|(value, _)| value)
}

/// Encoded byte length of `value`.
///
/// Capacity is `7 + 7n` bits for `n` continuation bytes (the leading byte keeps
/// `7 - n` low bits and the `n` continuation bytes add `8n`), so the thresholds are
/// 2^7, 2^14, 2^21, 2^28, 2^35.
pub fn size_of(value: u64) -> Result<usize, VarintError> {
    if value > MAX_VALUE {
        return Err(VarintError(format!(
            "value {value} outside 0..{MAX_VALUE}"
        )));
    }
    if value < 0x80 {
        return Ok(1);
    }
    for n in 1..=3usize {
        if value < (1u64 << (7 + 7 * n)) {
            return Ok(1 + n);
        }
    }
    Ok(5)
}

/// Encode `value` as a prefix varint.
pub fn encode(value: u64) -> Result<Vec<u8>, VarintError> {
    let size = size_of(value)?;
    if size == 1 {
        return Ok(vec![value as u8]);
    }
    let n = size - 1;
    let shift = 7 - n;
    let low = (value & ((1u64 << shift) - 1)) as u8;
    let high = value >> shift;
    // The leading byte's high `n` bits are 1s; its low `shift` bits are the low bits
    // of the value.
    let leading = ((0xFFu16 << (8 - n)) & 0xFF) as u8 | low;
    let mut out = Vec::with_capacity(size);
    out.push(leading);
    for i in 0..n {
        out.push(((high >> (8 * i)) & 0xFF) as u8);
    }
    Ok(out)
}

/// Convenience for the tests and for callers that build bodies from literals.
pub fn encode_into(out: &mut Vec<u8>, value: u64) -> Result<(), VarintError> {
    out.extend_from_slice(&encode(value)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_every_width_boundary() {
        for value in [
            0u64,
            1,
            0x7E,
            0x7F,
            0x80,
            0xBF,
            0xC0,
            0x1FFF,
            0x2000,
            0x3FFF,
            (1 << 21) - 1,
            1 << 21,
            (1 << 28) - 1,
            1 << 28,
            MAX_VALUE,
        ] {
            let encoded = encode(value).expect("encode");
            assert_eq!(encoded.len(), size_of(value).expect("size"));
            let (decoded, next) = decode(&encoded, 0).expect("decode");
            assert_eq!(decoded, value, "value {value} did not round-trip");
            assert_eq!(next, encoded.len());
        }
    }

    #[test]
    fn rejects_truncated_and_oversized_input() {
        assert!(decode(&[0x80], 0).is_err());
        assert!(decode(&[], 0).is_err());
        assert!(encode(MAX_VALUE + 1).is_err());
    }

    #[test]
    fn the_hand_verified_capture_values_decode() {
        // From varint.py's docstring, checked against messages-redacted.txt.
        assert_eq!(decode_from(&[0x9d, 0x05], 0).unwrap(), 349);
        assert_eq!(decode_from(&[0x88, 0x6e], 0).unwrap(), 7048);
        assert_eq!(decode_from(&[0xa3, 0x19], 0).unwrap(), 1635);
        assert_eq!(decode_from(&[0xa0, 0x5a], 0).unwrap(), 5792);
        assert_eq!(decode_from(&[0xb4, 0x0a], 0).unwrap(), 692);
        assert_eq!(decode_from(&[0xd9, 0xa9, 0x05], 0).unwrap(), 46393);
    }
}
