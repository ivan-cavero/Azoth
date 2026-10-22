//! The LZ4 block format, as the client uses it for `0x81` datagrams.
//!
//! WHY DECOMPRESS ONLY
//! ===================
//! The client compresses its own datagrams (measured: the first V3 registration
//! arrives as `0x81`, 269 bytes compressed from 1,124 — `rep.py` 2026-09-17), so
//! a server must decompress to read them. The server does **not** compress its
//! outbound records: the Python prototype sends `0x80` and the client accepts
//! it, and there is no measurement of the client's tolerance for a compressed
//! server datagram. Writing a compressor with no oracle to check it against
//! would be exactly the unverified code this crate exists to avoid. If outbound
//! compression is ever wanted, it arrives with a measurement and a parity
//! fixture.
//!
//! THE FORMAT
//! ==========
//! A sequence of: token byte, literal run, optional match. The token's high
//! nibble is the literal length and its low nibble the match length minus four;
//! either extends by 255-chained bytes when the nibble is 15. A match is a
//! two-byte little-endian offset backwards, copied byte by byte (so overlapping
//! copies work), and the block ends after a literal run with no match.
//!
//! THE TRAP
//! ========
//! Parsing a compressed body as if it were a record stream "worked" on a live
//! session in the sense that it produced a session token — a stub one — and a
//! stream that looked plausible. It was garbage. The type byte is the only thing
//! that says which parser to use, so [`crate::envelope`] validates it before
//! anything else runs.

use crate::error::WireError;

/// Decompress one LZ4 block.
///
/// # Errors
/// [`WireError::Lz4`] for a truncated literal run, a truncated match length, or
/// an offset that reaches before the start of the output.
pub fn decompress(block: &[u8]) -> Result<Vec<u8>, WireError> {
    let mut out: Vec<u8> = Vec::with_capacity(block.len().saturating_mul(4));
    let mut i = 0usize;
    let n = block.len();

    while i < n {
        let token = block[i];
        i += 1;
        let mut literal_len = usize::from(token >> 4);
        if literal_len == 15 {
            loop {
                let byte = *block.get(i).ok_or(WireError::Lz4 {
                    reason: "truncated literal length",
                    offset: i,
                })?;
                i += 1;
                literal_len += usize::from(byte);
                if byte != 255 {
                    break;
                }
            }
        }
        if i + literal_len > n {
            return Err(WireError::Lz4 {
                reason: "truncated literals",
                offset: i,
            });
        }
        out.extend_from_slice(&block[i..i + literal_len]);
        i += literal_len;

        if i >= n {
            // Last literals: a block may end here with no match following.
            break;
        }
        if i + 2 > n {
            return Err(WireError::Lz4 {
                reason: "truncated offset",
                offset: i,
            });
        }
        let offset = usize::from(block[i]) | (usize::from(block[i + 1]) << 8);
        i += 2;
        if offset == 0 || offset > out.len() {
            return Err(WireError::Lz4 {
                reason: "offset reaches before the output",
                offset: i,
            });
        }
        let mut match_len = usize::from(token & 0x0F) + 4;
        if token & 0x0F == 15 {
            loop {
                let byte = *block.get(i).ok_or(WireError::Lz4 {
                    reason: "truncated match length",
                    offset: i,
                })?;
                i += 1;
                match_len += usize::from(byte);
                if byte != 255 {
                    break;
                }
            }
        }
        // Byte at a time on purpose: the copy may overlap, which is how LZ4
        // expresses a run, so a slice copy would be wrong.
        let start = out.len() - offset;
        for k in 0..match_len {
            let byte = out[start + k];
            out.push(byte);
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Literals only, with no match: token high nibble 5, then five bytes.
    #[test]
    fn decompresses_a_literal_run() {
        let block = [0x50, b'h', b'e', b'l', b'l', b'o'];
        assert_eq!(decompress(&block).expect("ok"), b"hello");
    }

    /// An overlapping match: `ab` then a match at offset 2 for length 6 gives
    /// `abababab`, which a slice copy cannot express.
    #[test]
    fn decompresses_an_overlapping_match() {
        // token: literal len 2, match len 6-4=2
        // literals "ab", offset 0x0002
        let block = [0x22, b'a', b'b', 0x02, 0x00];
        assert_eq!(decompress(&block).expect("ok"), b"abababab");
    }

    /// A long literal run: 15 in the nibble, then 255-chained extension bytes.
    #[test]
    fn decompresses_a_long_literal_run() {
        let payload: Vec<u8> = (0..300u16).map(|i| (i % 251) as u8).collect();
        // Token high nibble 15, then the extension: 300 - 15 = 285, encoded as
        // 255 followed by 30 (the chain stops on a byte below 255).
        let extra = payload.len() - 15;
        let mut block = vec![0xF0, 255, (extra - 255) as u8];
        block.extend_from_slice(&payload);
        assert_eq!(decompress(&block).expect("ok"), payload);
    }

    #[test]
    fn rejects_a_bad_offset() {
        let err = decompress(&[0x10, b'a', 0x05, 0x00]).expect_err("must fail");
        assert!(matches!(err, WireError::Lz4 { .. }), "{err}");
    }

    #[test]
    fn rejects_truncated_literals() {
        let err = decompress(&[0x50, b'a']).expect_err("must fail");
        assert!(matches!(err, WireError::Lz4 { .. }), "{err}");
    }

    #[test]
    fn rejects_a_zero_offset() {
        let err = decompress(&[0x12, b'a', b'b', 0x00, 0x00]).expect_err("must fail");
        assert!(matches!(err, WireError::Lz4 { .. }), "{err}");
    }
}
