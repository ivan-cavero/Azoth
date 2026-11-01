//! The LZ4 block decompressor the Carrier envelope's `0x81` body needs.
//!
//! The envelope type byte's low bit marks an LZ4 block (see [`crate::carrier`]),
//! and the Carrier layer deliberately never decompresses it. This module is that
//! separate layer, ported from the reference's stdlib-only
//! `services/world/src/azoth_world/javelin/lz4.py`. It is pure and holds no
//! bytes, records, or messages of its own: it turns one compressed block into the
//! record stream that [`crate::carrier::decode_records`] then reads.
//!
//! It implements the LZ4 block format only (no frame header): token nibbles for
//! literal/match lengths, 255-extended lengths, 2-byte little-endian offsets, and
//! a minimum match length of four. That is the whole of what the client's
//! Javelin `0x81` datagrams use.

use core::fmt;

/// An LZ4 block that does not match the block format.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum Lz4Error {
    /// A literal length ran past the end of the block.
    TruncatedLiteralLength,
    /// The declared literals ran past the end of the block.
    TruncatedLiterals,
    /// A match ended before its two-byte offset was complete.
    TruncatedOffset,
    /// A match length ran past the end of the block.
    TruncatedMatchLength,
    /// A match named an offset of zero or one past the bytes produced so far.
    BadOffset {
        /// The offset the block declared.
        offset: usize,
        /// Bytes produced before the match, which the offset must not exceed.
        produced: usize,
    },
}

impl fmt::Display for Lz4Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TruncatedLiteralLength => write!(f, "lz4: truncated literal length"),
            Self::TruncatedLiterals => write!(f, "lz4: truncated literals"),
            Self::TruncatedOffset => write!(f, "lz4: truncated offset"),
            Self::TruncatedMatchLength => write!(f, "lz4: truncated match length"),
            Self::BadOffset { offset, produced } => {
                write!(
                    f,
                    "lz4: bad offset {offset} with {produced} byte(s) produced"
                )
            }
        }
    }
}

impl std::error::Error for Lz4Error {}

/// Decompress one LZ4 block.
///
/// # Errors
/// Returns an [`Lz4Error`] for any sequence the block format does not allow.
/// A block always ends after a literal run, so running out of input after
/// literals is the normal terminal case, not an error.
pub fn decompress_block(input: &[u8]) -> Result<Vec<u8>, Lz4Error> {
    let mut out = Vec::new();
    let mut index = 0;
    let length = input.len();
    while index < length {
        let token = input[index];
        index += 1;

        let mut literals = usize::from(token >> 4);
        if literals == 15 {
            loop {
                if index >= length {
                    return Err(Lz4Error::TruncatedLiteralLength);
                }
                let extension = input[index];
                index += 1;
                literals += usize::from(extension);
                if extension != 255 {
                    break;
                }
            }
        }
        let literals_end = index.saturating_add(literals);
        if literals_end > length {
            return Err(Lz4Error::TruncatedLiterals);
        }
        out.extend_from_slice(&input[index..literals_end]);
        index = literals_end;
        if index >= length {
            break;
        }

        if index + 2 > length {
            return Err(Lz4Error::TruncatedOffset);
        }
        let offset = usize::from(input[index]) | (usize::from(input[index + 1]) << 8);
        index += 2;
        if offset == 0 || offset > out.len() {
            return Err(Lz4Error::BadOffset {
                offset,
                produced: out.len(),
            });
        }

        let mut match_length = usize::from(token & 0x0F) + 4;
        if token & 0x0F == 15 {
            loop {
                if index >= length {
                    return Err(Lz4Error::TruncatedMatchLength);
                }
                let extension = input[index];
                index += 1;
                match_length += usize::from(extension);
                if extension != 255 {
                    break;
                }
            }
        }
        for _ in 0..match_length {
            let byte = out[out.len() - offset];
            out.push(byte);
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_literals_only_block_round_trips() {
        // Token 0x40: four literals, no match.
        let block = [0x40, b'a', b'b', b'c', b'd'];
        assert_eq!(decompress_block(&block).expect("decompress"), b"abcd");
    }

    #[test]
    fn a_block_with_a_back_reference_expands() {
        // 4 literals "abcd", then a match of 4 at offset 4 -> "abcdabcd".
        let block = [0x40, b'a', b'b', b'c', b'd', 0x04, 0x00];
        assert_eq!(decompress_block(&block).expect("decompress"), b"abcdabcd");
    }

    #[test]
    fn a_bad_offset_is_refused() {
        assert_eq!(
            decompress_block(&[0x10, b'a', 0x00, 0x00]),
            Err(Lz4Error::BadOffset {
                offset: 0,
                produced: 1
            })
        );
    }
}
