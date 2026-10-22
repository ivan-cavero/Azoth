//! The Carrier envelope: the 4-byte header on every post-DTLS datagram.
//!
//! ```text
//! byte 0    type   0x80 = plaintext record stream, 0x81 = LZ4-compressed block
//! byte 1    proto  always 0x01
//! bytes 2-3         datagram sequence, u16 big-endian
//! ```
//!
//! The type byte is validated by mask rather than by equality, which is what the
//! client's reader does: bit 7 must be set and bits 1..=6 must be clear, so the
//! only accepted values are `0x80` and `0x81`. Bit 0 selects compression.
//!
//! WHY THE SEQUENCE IS PER DATAGRAM, NOT PER MESSAGE
//! =================================================
//! This counter numbers datagrams. The per-channel record sequences inside the
//! payload are separate counters with their own wrap behaviour, and conflating
//! them is a mistake the Python prototype made once: an ACK range pinned to the
//! session's first sequence passed the 16-bit half-space at ~26 minutes and the
//! client began retransmitting every reliable record 212 times
//! (`docs/ROADMAP.md` §2). The envelope sequence is one of the counters the ACK
//! range is expressed over, so it is a `u16` here and not widened.

use crate::error::WireError;

/// Size of the envelope, in bytes.
pub const ENVELOPE_SIZE: usize = 4;

/// The protocol byte every envelope carries.
pub const PROTOCOL: u8 = 0x01;

/// Bit 7 of the type byte: always set.
const TYPE_PRESENT: u8 = 0x80;
/// Bits 1..=6 of the type byte: always clear.
const TYPE_RESERVED: u8 = 0x7E;
/// Bit 0 of the type byte: the payload is an LZ4-compressed block.
const TYPE_COMPRESSED: u8 = 0x01;

/// A parsed Carrier envelope.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Envelope {
    /// The raw type byte, kept because it is what a capture comparison needs.
    pub type_byte: u8,
    /// The datagram sequence number.
    pub sequence: u16,
}

impl Envelope {
    /// Whether the payload is an LZ4-compressed block.
    #[must_use]
    pub const fn is_compressed(self) -> bool {
        self.type_byte & TYPE_COMPRESSED != 0
    }

    /// Encode the envelope to its four bytes.
    #[must_use]
    pub fn encode(self) -> [u8; ENVELOPE_SIZE] {
        let [hi, lo] = self.sequence.to_be_bytes();
        [self.type_byte, PROTOCOL, hi, lo]
    }

    /// Build an envelope, choosing the type byte from `compressed`.
    #[must_use]
    pub const fn new(sequence: u16, compressed: bool) -> Self {
        Self {
            type_byte: TYPE_PRESENT | if compressed { TYPE_COMPRESSED } else { 0 },
            sequence,
        }
    }
}

/// Parse the envelope and return it with the bytes that follow it.
///
/// # Errors
/// [`WireError::Truncated`] for a datagram shorter than four bytes,
/// [`WireError::BadEnvelopeType`] or [`WireError::BadEnvelopeProtocol`] when the
/// fixed bytes do not match the format.
pub fn parse(data: &[u8]) -> Result<(Envelope, &[u8]), WireError> {
    if data.len() < ENVELOPE_SIZE {
        return Err(WireError::truncated(
            "carrier envelope",
            ENVELOPE_SIZE,
            data.len(),
        ));
    }
    let type_byte = data[0];
    if type_byte & TYPE_PRESENT == 0 || type_byte & TYPE_RESERVED != 0 {
        return Err(WireError::BadEnvelopeType { byte: type_byte });
    }
    if data[1] != PROTOCOL {
        return Err(WireError::BadEnvelopeProtocol { byte: data[1] });
    }
    let sequence = u16::from_be_bytes([data[2], data[3]]);
    Ok((
        Envelope {
            type_byte,
            sequence,
        },
        &data[ENVELOPE_SIZE..],
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_both_types() {
        for compressed in [false, true] {
            let envelope = Envelope::new(0x0106, compressed);
            let bytes = envelope.encode();
            let (parsed, rest) = parse(&bytes).expect("parses");
            assert_eq!(parsed, envelope);
            assert_eq!(parsed.is_compressed(), compressed);
            assert!(rest.is_empty());
        }
    }

    /// The measured envelope bytes from a live 1.460 session: a plaintext
    /// datagram at sequence 106 and a compressed one at 125.
    #[test]
    fn parses_the_measured_envelopes() {
        let (plain, _) = parse(&[0x80, 0x01, 0x00, 0x6a]).expect("parses");
        assert_eq!(plain.sequence, 106);
        assert!(!plain.is_compressed());

        let (packed, _) = parse(&[0x81, 0x01, 0x00, 0x7d]).expect("parses");
        assert_eq!(packed.sequence, 125);
        assert!(packed.is_compressed());
    }

    #[test]
    fn rejects_a_short_datagram() {
        let err = parse(&[0x80, 0x01, 0x00]).expect_err("must fail");
        assert!(matches!(err, WireError::Truncated { .. }), "{err}");
    }

    #[test]
    fn rejects_reserved_type_bits() {
        // Bit 7 set but bit 1 also set: not a value the reader accepts.
        let err = parse(&[0x82, 0x01, 0x00, 0x00]).expect_err("must fail");
        assert!(matches!(err, WireError::BadEnvelopeType { .. }), "{err}");
    }

    #[test]
    fn rejects_a_missing_present_bit() {
        let err = parse(&[0x00, 0x01, 0x00, 0x00]).expect_err("must fail");
        assert!(matches!(err, WireError::BadEnvelopeType { .. }), "{err}");
    }

    #[test]
    fn rejects_a_bad_protocol_byte() {
        let err = parse(&[0x80, 0x02, 0x00, 0x00]).expect_err("must fail");
        assert!(matches!(err, WireError::BadEnvelopeProtocol { .. }), "{err}");
    }
}
