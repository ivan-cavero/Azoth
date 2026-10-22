//! VLQ32: the variable-length length field in the client's own container.
//!
//! SAME ENCODING, TWO NAMES
//! ========================
//! The protocol vocabulary carries two names for one encoding. `varint` is what
//! the type table calls the prefix varint on message types and record ids;
//! `VLQ32` is what the length field in the client's `[crc32][len]` container
//! calls it. Comparing the two implementations field by field:
//!
//! ```text
//!            varint                    VLQ32
//! < 2^7      1 byte, 7 low bits        n=1, prefix 0x00, 7 low bits
//! < 2^14     2 bytes, 6 low bits       n=2, prefix 0x80, 6 low bits
//! < 2^21     3 bytes, 5 low bits       n=3, prefix 0xC0, 5 low bits
//! < 2^28     4 bytes, 4 low bits       n=4, prefix 0xE0, 4 low bits
//! < 2^35     5 bytes, 3 low bits       n=5, prefix 0xF0, 3 low bits
//! ```
//!
//! They are identical. This module exists anyway, and delegates rather than
//! re-implementing, for two reasons: callers name the format they mean, so a
//! reader of a length-field site does not have to know it shares a bit layout
//! with message types; and there is exactly one implementation, so the two
//! cannot drift. The test below pins the equivalence over every boundary, and
//! the parity harness checks both against the Python encoders.
//!
//! THE DEFECT THIS ENCODING CAUSED
//! ===============================
//! The first implementation wrote the two halves of a two-byte value in the
//! wrong order. A 12,706-byte message was decoded by the client as 6,370, the
//! stream desynchronised, and every message after it was garbage — with the
//! transport layer reporting a perfect ACK ratio the whole time. See
//! [`crate::varint`] for the boundary tests that make that class visible.

pub use crate::varint::{MAX_VALUE, decode, decode_from, encode, encode_into, size_of};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn is_the_prefix_varint_over_every_boundary() {
        let values = [
            0u64, 1, 0x7e, 0x7f, 0x80, 0x3ffe, 0x3fff, 0x4000, 0x1f_fffe, 0x1f_ffff, 0x20_0000,
            0x0fff_fffe, 0x0fff_ffff, 0x1000_0000, MAX_VALUE,
        ];
        for value in values {
            let encoded = encode(value).expect("in range");
            let (decoded, next) = decode(&encoded, 0).expect("decodes");
            assert_eq!(decoded, value);
            assert_eq!(next, encoded.len());
        }
    }

    /// The length field of the client's container, as measured on the wire: a
    /// 119-byte channel-1 payload declares `len = 0x0000006f` = 111, which is
    /// `0x6f` in one byte, and a 46,393-byte record declares itself in three.
    #[test]
    fn encodes_the_measured_lengths() {
        assert_eq!(encode(111).expect("in range"), vec![0x6f]);
        assert_eq!(encode(692).expect("in range"), vec![0xb4, 0x0a]);
        assert_eq!(encode(46393).expect("in range"), vec![0xd9, 0xa9, 0x05]);
    }
}
