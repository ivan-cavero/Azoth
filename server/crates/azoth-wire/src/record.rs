//! MessageRecord framing: the 1..N records inside one Carrier datagram.
//!
//! ```text
//! flags   u8            (see [`Flags`])
//! size    u16 BE        absent when MF_NO_LENGTH
//! channel u8            present only when MF_DATA_CHANNEL (else the previous one)
//! numChunks u16 BE      present only when MF_CHUNKS (else implicit 1)
//! sequence  u16 BE      absent when MF_SEQUENTIAL_ID (auto-increment)
//! relSeq    u16 BE      absent when MF_SEQUENTIAL_REL_ID (auto-increment)
//! payload size bytes    (to end of datagram when MF_NO_LENGTH)
//! ```
//!
//! A field is present only when its flag says so, so this is a walk and not a
//! fixed struct. Two details are easy to get wrong and both were measured:
//!
//! * **The NO_LENGTH form carries a sub-header.** When `MF_NO_LENGTH` is set a
//!   byte follows the size field, and the first-attempt form
//!   (`NO_LENGTH | SEQUENTIAL_REL_ID`) carries two. The payload then runs to the
//!   end of the datagram.
//! * **A non-reliable record still writes its relSeq.** The writer's
//!   "omit the field when it auto-increments" optimisation applies only to
//!   reliable records; applying it more broadly produced flag bytes the client
//!   rejects.
//!
//! BYTE ALIGNMENT
//! ==============
//! Every field is a byte multiple, and the payload is always `size * 8` bits, so
//! a record stream is byte-aligned throughout. The Python prototype carries a
//! general bit-stream reader for a `start_bit` it never uses; this port reads
//! bytes, which is both simpler and faster, and the parity harness proves the
//! two agree over the whole corpus.

use crate::error::WireError;
use crate::MAX_CHANNEL;

/// MessageRecord flag bits.
pub mod flags {
    /// Reliable delivery.
    pub const RELIABLE: u8 = 0x01;
    /// Chunked payload; a `numChunks` u16 follows.
    pub const CHUNKS: u8 = 0x04;
    /// The sequence field is omitted and auto-increments per channel.
    pub const SEQUENTIAL_ID: u8 = 0x08;
    /// The reliable-sequence field is omitted and auto-increments per channel.
    pub const SEQUENTIAL_REL_ID: u8 = 0x10;
    /// A channel byte follows.
    pub const DATA_CHANNEL: u8 = 0x20;
    /// The payload runs to the end of the datagram; no length field.
    pub const NO_LENGTH: u8 = 0x40;
    /// Connecting (pre-registration) form.
    pub const CONNECTING: u8 = 0x80;
}

/// One message record.
///
/// The `flags` field is an OUTPUT of parsing and is IGNORED by marshalling: the
/// writer computes the flag byte from the record's own fields plus the datagram's
/// cross-record state, because a field is omitted when it would merely repeat an
/// auto-increment. A caller that sets `flags` and expects it on the wire will be
/// surprised, so the field is documented rather than removed — a capture
/// comparison needs to see the byte that was actually received.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MessageRecord {
    /// The raw flag byte, as parsed. Ignored when marshalling.
    pub flags: u8,
    /// Channel 0..=3.
    pub channel: u8,
    /// Per-channel sequence.
    pub sequence: u16,
    /// Per-channel reliable sequence.
    pub reliable_sequence: u16,
    /// Whether the record is reliable.
    pub reliable: bool,
    /// Whether this is the connecting (pre-registration) form.
    pub connecting: bool,
    /// Number of chunks when chunked, else 1.
    pub num_chunks: u16,
    /// The payload bytes.
    pub payload: Vec<u8>,
}

impl MessageRecord {
    /// A plain data record on `channel` with the given sequences.
    #[must_use]
    pub fn data(
        channel: u8,
        sequence: u16,
        reliable_sequence: u16,
        payload: Vec<u8>,
    ) -> Self {
        Self {
            flags: 0,
            channel,
            sequence,
            reliable_sequence,
            reliable: false,
            connecting: false,
            num_chunks: 1,
            payload,
        }
    }

    /// Whether the record's channel is the system channel.
    #[must_use]
    pub const fn is_system(&self) -> bool {
        self.channel == crate::CHANNEL_SYSTEM
    }

    /// The system message id, which lives in the payload's LAST byte.
    #[must_use]
    pub fn system_msg_id(&self) -> Option<u8> {
        if self.is_system() {
            self.payload.last().copied()
        } else {
            None
        }
    }

    /// Payload length.
    #[must_use]
    pub fn size(&self) -> usize {
        self.payload.len()
    }
}

/// A parse outcome: the records read, plus a failure if the walk stopped early.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Parsed {
    /// Records decoded before any failure.
    pub records: Vec<MessageRecord>,
    /// Bytes left over at the end, if the stream did not consume exactly.
    pub trailing_bytes: usize,
}

/// Parse the record stream that follows the 4-byte Carrier envelope.
///
/// # Errors
/// [`WireError::BadChannel`] for a channel above 3, [`WireError::Truncated`] for
/// a stream that ends mid-field, or [`WireError::LengthMismatch`] when a payload
/// claims more bytes than remain.
///
/// The caller decides whether a partial result is usable: on error nothing is
/// returned, because a half-decoded record is not a record. The Python prototype
/// returned the records it had plus an error string, and a caller that ignored
/// the error acted on garbage.
pub fn parse(data: &[u8]) -> Result<Parsed, WireError> {
    let mut records = Vec::new();
    let mut prev_channel: u8 = 0;
    let mut per_seq = [0u16; 4];
    let mut per_rel = [0u16; 4];
    let mut off = 0usize;

    while off < data.len() {
        let flags = read_u8(data, &mut off, "flags")?;
        let no_length = flags & flags::NO_LENGTH != 0;
        let first_attempt = no_length && flags & flags::SEQUENTIAL_REL_ID != 0;

        let size = if no_length {
            // The size field is absent; a sub-header byte (two for the
            // first-attempt form) takes its place.
            read_u8(data, &mut off, "no-length sub-header")?;
            if first_attempt {
                read_u8(data, &mut off, "no-length first-attempt sub-header")?;
            }
            0usize
        } else {
            read_u16_be(data, &mut off, "size")? as usize
        };

        let reliable = flags & flags::RELIABLE != 0;
        let connecting = flags & flags::CONNECTING != 0;

        let channel = if flags & flags::DATA_CHANNEL != 0 {
            read_u8(data, &mut off, "channel")?
        } else {
            prev_channel
        };
        if channel > MAX_CHANNEL {
            return Err(WireError::BadChannel { channel });
        }
        prev_channel = channel;
        let slot = usize::from(channel);

        let num_chunks = if flags & flags::CHUNKS != 0 {
            read_u16_be(data, &mut off, "numChunks")?
        } else {
            1
        };

        let sequence = if flags & flags::SEQUENTIAL_ID != 0 {
            per_seq[slot] = per_seq[slot].wrapping_add(1);
            per_seq[slot]
        } else {
            let value = read_u16_be(data, &mut off, "sequence")?;
            per_seq[slot] = value;
            value
        };

        let reliable_sequence = if flags & flags::SEQUENTIAL_REL_ID == 0 {
            let value = read_u16_be(data, &mut off, "relSeq")?;
            per_rel[slot] = value;
            value
        } else if reliable {
            per_rel[slot] = per_rel[slot].wrapping_add(1);
            per_rel[slot]
        } else {
            per_rel[slot]
        };

        let payload = if no_length {
            let rest = data.len() - off;
            let slice = &data[off..off + rest];
            off += rest;
            slice.to_vec()
        } else {
            if off + size > data.len() {
                return Err(WireError::LengthMismatch {
                    declared: size,
                    actual: data.len() - off,
                });
            }
            let slice = &data[off..off + size];
            off += size;
            slice.to_vec()
        };

        records.push(MessageRecord {
            flags,
            channel,
            sequence,
            reliable_sequence,
            reliable,
            connecting,
            num_chunks,
            payload,
        });
    }

    Ok(Parsed {
        records,
        trailing_bytes: data.len() - off,
    })
}

fn read_u8(data: &[u8], off: &mut usize, field: &'static str) -> Result<u8, WireError> {
    let byte = *data
        .get(*off)
        .ok_or_else(|| WireError::truncated(field, 1, 0))?;
    *off += 1;
    Ok(byte)
}

fn read_u16_be(data: &[u8], off: &mut usize, field: &'static str) -> Result<u16, WireError> {
    if *off + 2 > data.len() {
        return Err(WireError::truncated(field, 2, data.len().saturating_sub(*off)));
    }
    let value = u16::from_be_bytes([data[*off], data[*off + 1]]);
    *off += 2;
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_a_channel_above_three() {
        // flags 0x20 (channel follows), size 0, channel 4.
        let bytes = vec![0x20, 0x00, 0x00, 0x04, 0x00, 0x01, 0x00, 0x01];
        let err = parse(&bytes).expect_err("must fail");
        assert!(matches!(err, WireError::BadChannel { channel: 4 }), "{err}");
    }

    #[test]
    fn rejects_a_payload_past_the_end() {
        // flags 0x20 (channel follows), size 0x00FF, channel 0, seq, rel, one byte
        let bytes = vec![0x20, 0x00, 0xFF, 0x00, 0x00, 0x01, 0x00, 0x01, 0xAA];
        let err = parse(&bytes).expect_err("must fail");
        assert!(matches!(err, WireError::LengthMismatch { .. }), "{err}");
    }

    #[test]
    fn rejects_a_truncated_stream() {
        let err = parse(&[0x20]).expect_err("must fail");
        assert!(matches!(err, WireError::Truncated { .. }), "{err}");
    }

    /// Two records on one channel. The second omits the channel byte, and with
    /// `SEQUENTIAL_ID` its sequence auto-increments instead of being read; a
    /// non-reliable record carrying `SEQUENTIAL_REL_ID` keeps the previous
    /// reliable sequence rather than incrementing it.
    #[test]
    fn reconstructs_omitted_fields() {
        // Record 1: flags 0x20 (channel follows) | size 1 | channel 0 | seq 7 | rel 9 | AA
        // Record 2: flags 0x18 (SEQ_ID|SEQ_REL_ID) | size 1 | payload BB
        let bytes = vec![
            0x20, 0x00, 0x01, 0x00, 0x00, 0x07, 0x00, 0x09, 0xAA, //
            0x18, 0x00, 0x01, 0xBB,
        ];
        let parsed = parse(&bytes).expect("parse");
        assert_eq!(parsed.records.len(), 2);
        assert_eq!(parsed.records[0].channel, 0);
        assert_eq!(parsed.records[0].sequence, 7);
        assert_eq!(parsed.records[0].reliable_sequence, 9);
        assert_eq!(parsed.records[1].channel, 0, "channel carried over");
        assert_eq!(parsed.records[1].sequence, 8, "sequence auto-incremented");
        assert_eq!(
            parsed.records[1].reliable_sequence, 9,
            "non-reliable SEQUENTIAL_REL_ID keeps the previous value"
        );
        assert_eq!(parsed.records[1].payload, vec![0xBB]);
        assert_eq!(parsed.trailing_bytes, 0);
    }

    /// A `SEQUENTIAL_ID` record auto-increments instead of reading a field.
    #[test]
    fn auto_increments_a_sequential_id() {
        // Record 1: channel 0, seq 7, rel 9.
        // Record 2: flags 0x08 (SEQUENTIAL_ID) -> seq becomes 8.
        let bytes = vec![
            0x20, 0x00, 0x00, 0x00, 0x00, 0x07, 0x00, 0x09, //
            0x08, 0x00, 0x00, 0x00, 0x09,
        ];
        let parsed = parse(&bytes).expect("parse");
        assert_eq!(parsed.records.len(), 2);
        assert_eq!(parsed.records[1].sequence, 8);
        assert_eq!(parsed.records[1].reliable_sequence, 9);
    }

    /// The system message id lives in the payload's LAST byte.
    #[test]
    fn system_message_id_is_the_last_payload_byte() {
        let record = MessageRecord {
            payload: vec![0x00, 0x06],
            ..MessageRecord::data(3, 1, 1, vec![])
        };
        assert!(record.is_system());
        assert_eq!(record.system_msg_id(), Some(6));
        assert_eq!(MessageRecord::data(1, 1, 1, vec![6]).system_msg_id(), None);
    }
}
