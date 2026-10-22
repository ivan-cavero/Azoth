//! The crate's error type.
//!
//! One enum, not `String`: the client's own failure vocabulary is specific
//! (`Failed to unmarshal`, `ValidationError`, `@mm_csdkerr_*`), and a wire error
//! has to be mappable back onto it. A free-form message cannot be.

use std::fmt;

/// A wire-format violation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WireError {
    /// The buffer ended before the field did.
    Truncated {
        /// What was being read.
        field: &'static str,
        /// Bytes the field needed.
        needed: usize,
        /// Bytes actually available.
        available: usize,
    },
    /// A varint used more continuation bytes than the format allows.
    VarintTooLong {
        /// Offset the varint started at.
        offset: usize,
        /// Continuation bytes the first byte announced.
        continuation: usize,
    },
    /// A value did not fit the encoding's width.
    OutOfRange {
        /// What was being encoded.
        field: &'static str,
        /// The offending value.
        value: u64,
        /// The exclusive upper bound.
        limit: u64,
    },
    /// The Carrier envelope's first byte was not a recognised type.
    BadEnvelopeType {
        /// The byte that failed.
        byte: u8,
    },
    /// The Carrier envelope's protocol byte was not 1.
    BadEnvelopeProtocol {
        /// The byte that failed.
        byte: u8,
    },
    /// A record claimed a channel the protocol does not define.
    BadChannel {
        /// The channel byte.
        channel: u8,
    },
    /// A payload length disagreed with the bytes that remained.
    LengthMismatch {
        /// What the length field claimed.
        declared: usize,
        /// What was actually present.
        actual: usize,
    },
    /// The typed marker (`00 01`) was absent where a typed message was expected.
    MissingTypeMarker {
        /// The two bytes found instead.
        found: [u8; 2],
    },
    /// The client container's CRC did not cover its payload.
    CrcMismatch {
        /// The CRC the container declared.
        declared: u32,
        /// The CRC computed over the payload.
        computed: u32,
    },
    /// A state bundle's six invariant prologue bytes did not match.
    ///
    /// This is the layout tripwire: if those bytes move, the client build
    /// changed and every offset in this crate is suspect.
    PrologueMismatch {
        /// The six bytes the layout requires.
        expected: [u8; 6],
        /// The six bytes found.
        found: [u8; 6],
    },
    /// An LZ4 block was malformed.
    Lz4 {
        /// What was wrong.
        reason: &'static str,
        /// Offset inside the compressed block.
        offset: usize,
    },
    /// A caller supplied fragment boundaries that cannot describe the payload.
    BadBoundaries {
        /// What was wrong.
        reason: &'static str,
    },
}

impl fmt::Display for WireError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated {
                field,
                needed,
                available,
            } => write!(
                f,
                "{field}: needed {needed} bytes, {available} available"
            ),
            Self::VarintTooLong {
                offset,
                continuation,
            } => write!(
                f,
                "varint at {offset} announces {continuation} continuation bytes (max 4)"
            ),
            Self::OutOfRange {
                field,
                value,
                limit,
            } => write!(f, "{field}: {value} is outside 0..{limit}"),
            Self::BadEnvelopeType { byte } => {
                write!(f, "bad Carrier envelope type byte 0x{byte:02x}")
            }
            Self::BadEnvelopeProtocol { byte } => {
                write!(f, "bad Carrier envelope protocol byte 0x{byte:02x}")
            }
            Self::BadChannel { channel } => {
                write!(f, "invalid channel {channel} (max 3)")
            }
            Self::LengthMismatch { declared, actual } => write!(
                f,
                "length field says {declared} but {actual} bytes remain"
            ),
            Self::MissingTypeMarker { found } => write!(
                f,
                "missing typed marker (expected 0001, got {:02x}{:02x})",
                found[0], found[1]
            ),
            Self::CrcMismatch { declared, computed } => write!(
                f,
                "crc mismatch (declared 0x{declared:08x}, computed 0x{computed:08x})"
            ),
            Self::PrologueMismatch { expected, found } => write!(
                f,
                "prologue tail mismatch (expected {}, got {})",
                hex(expected),
                hex(found)
            ),
            Self::Lz4 { reason, offset } => {
                write!(f, "lz4 at {offset}: {reason}")
            }
            Self::BadBoundaries { reason } => write!(f, "bad fragment boundaries: {reason}"),
        }
    }
}

impl std::error::Error for WireError {}

impl WireError {
    /// A truncation error, for a read that ran past the end.
    #[must_use]
    pub fn truncated(field: &'static str, needed: usize, available: usize) -> Self {
        Self::Truncated {
            field,
            needed,
            available,
        }
    }
}

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        use std::fmt::Write as _;
        let _ = write!(out, "{b:02x}");
    }
    out
}
