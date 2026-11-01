//! The Carrier datagram envelope and its message-record framing.
//!
//! Every post-DTLS datagram is a 4-byte Carrier envelope, then a run of message
//! records:
//!
//! ```text
//! envelope : [type:u8][proto:u8][sequence:u16 BE]
//! record   : [flags:u8][size:u16 BE]
//!            [sub-header:u8                         (only MF_NO_LENGTH)]
//!            [sub-header:u8                         (only MF_NO_LENGTH|MF_SEQUENTIAL_REL_ID)]
//!            [channel:u8                            (only MF_DATA_CHANNEL)]
//!            [num_chunks:u16 BE                      (only MF_CHUNKS)]
//!            [sequence:u16 BE                        (unless MF_SEQUENTIAL_ID)]
//!            [reliable_sequence:u16 BE               (unless MF_SEQUENTIAL_REL_ID)]
//!            [payload:size bytes, or to the end      (MF_NO_LENGTH)]
//! ```
//!
//! `size` is the payload byte count. `sequence` and `reliable_sequence` are
//! per-channel and continue across the records of one datagram: `MF_SEQUENTIAL_ID`
//! omits the field and uses the previous value plus one, and `MF_SEQUENTIAL_REL_ID`
//! does the same, advancing only for a reliable record. `MF_DATA_CHANNEL` omits
//! the channel byte when it repeats the previous record's channel. The first
//! record always carries its channel because the writer starts with no previous
//! channel.
//!
//! This is framing, not a card. It mirrors the reference's `parse_envelope` /
//! `parse_datagram` / `marshal_datagram` from `javelin/frame.py`, which in turn
//! mirrors the client's `Javelin_Carrier_ParseMessages` / `_WriteMessages`. It
//! never decompresses a compressed body: `type_byte` bit 0 marks an LZ4 payload,
//! and that payload is a separate layer's problem.

use crate::framing::{Reader, WireError};

/// The record is reliable; its reliable sequence advances.
pub const MF_RELIABLE: u8 = 0x01;

/// The record carries a `num_chunks` field.
pub const MF_CHUNKS: u8 = 0x04;

/// The `sequence` field is omitted; it is the previous value plus one.
pub const MF_SEQUENTIAL_ID: u8 = 0x08;

/// The `reliable_sequence` field is omitted; it is the previous value plus one.
pub const MF_SEQUENTIAL_REL_ID: u8 = 0x10;

/// A `channel` byte follows, overriding the previous record's channel.
pub const MF_DATA_CHANNEL: u8 = 0x20;

/// The payload runs to the end of the datagram; `size` is not used for its width.
pub const MF_NO_LENGTH: u8 = 0x40;

/// The record belongs to the connection handshake.
pub const MF_CONNECTING: u8 = 0x80;

/// Bytes the envelope header occupies before the first record.
const ENVELOPE_LEN: usize = 4;

/// Channel that carries system messages, whose id is the payload's last byte.
const SYSTEM_CHANNEL: u8 = 3;

/// The largest valid channel (0..=3).
const MAX_CHANNEL: u8 = 3;

/// The 4-byte header on every post-DTLS datagram.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Envelope {
    type_byte: u8,
    proto: u8,
    sequence: u16,
}

/// The only choice the envelope's type byte encodes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Compression {
    /// The body is a plaintext record stream.
    Plaintext,
    /// The body is an LZ4 block.
    Compressed,
}

impl Compression {
    /// The envelope type byte this choice writes.
    #[must_use]
    pub const fn type_byte(self) -> u8 {
        match self {
            Self::Plaintext => Envelope::PLAINTEXT,
            Self::Compressed => Envelope::COMPRESSED,
        }
    }
}

impl Envelope {
    /// `type_byte` for a plaintext datagram.
    pub const PLAINTEXT: u8 = 0x80;

    /// `type_byte` for an LZ4-compressed datagram (its bit 0 is set).
    pub const COMPRESSED: u8 = 0x81;

    /// The only `proto` byte the envelope carries.
    pub const PROTO: u8 = 0x01;

    /// Start an envelope from a sequence and a compression choice.
    #[must_use]
    pub const fn new(sequence: u16, compression: Compression) -> Self {
        Self {
            type_byte: compression.type_byte(),
            proto: Self::PROTO,
            sequence,
        }
    }

    /// Read the envelope, returning it and the body that follows it.
    ///
    /// # Errors
    /// Returns [`CarrierError::EnvelopeTooShort`] when fewer than four bytes
    /// arrive, [`CarrierError::BadEnvelopeType`] when the type byte is not
    /// `0x80`/`0x81`, and [`CarrierError::BadEnvelopeProto`] when `proto` is not
    /// `0x01`.
    pub fn decode(datagram: &[u8]) -> Result<(Self, &[u8]), CarrierError> {
        if datagram.len() < ENVELOPE_LEN {
            return Err(CarrierError::EnvelopeTooShort {
                have: datagram.len(),
            });
        }
        let type_byte = datagram[0];
        // Bit 7 must be set and bits 1..=6 clear: the only valid bytes are
        // 0x80 (plaintext) and 0x81 (compressed).
        if type_byte & 0x80 == 0 || type_byte & 0x7E != 0 {
            return Err(CarrierError::BadEnvelopeType { found: type_byte });
        }
        let proto = datagram[1];
        if proto != Self::PROTO {
            return Err(CarrierError::BadEnvelopeProto { found: proto });
        }
        let sequence = u16::from_be_bytes([datagram[2], datagram[3]]);
        Ok((
            Self {
                type_byte,
                proto,
                sequence,
            },
            &datagram[ENVELOPE_LEN..],
        ))
    }

    /// Append the four header bytes to `out`.
    pub fn encode(&self, out: &mut Vec<u8>) {
        out.push(self.type_byte);
        out.push(self.proto);
        out.extend_from_slice(&self.sequence.to_be_bytes());
    }

    /// The raw type byte, `0x80` or `0x81`.
    #[must_use]
    pub const fn type_byte(&self) -> u8 {
        self.type_byte
    }

    /// The protocol byte, always `0x01`.
    #[must_use]
    pub const fn proto(&self) -> u8 {
        self.proto
    }

    /// The 16-bit envelope sequence.
    #[must_use]
    pub const fn sequence(&self) -> u16 {
        self.sequence
    }

    /// True when the body is an LZ4 block, not a record stream.
    #[must_use]
    pub const fn is_compressed(&self) -> bool {
        self.type_byte & 1 != 0
    }
}

/// One message record inside a datagram.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MessageRecord {
    channel: u8,
    payload: Vec<u8>,
    sequence: u16,
    reliable_sequence: u16,
    reliable: bool,
    connecting: bool,
    num_chunks: u16,
    flags: u8,
    flags_override: Option<u8>,
}

impl MessageRecord {
    /// Start a non-reliable record on `channel` carrying `payload`.
    #[must_use]
    pub fn new(channel: u8, payload: Vec<u8>) -> Self {
        Self {
            channel,
            payload,
            sequence: 0,
            reliable_sequence: 0,
            reliable: false,
            connecting: false,
            num_chunks: 1,
            flags: 0,
            flags_override: None,
        }
    }

    /// The channel the record rides on (0..=3).
    #[must_use]
    pub const fn channel(&self) -> u8 {
        self.channel
    }

    /// The payload bytes.
    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    /// The per-channel message sequence.
    #[must_use]
    pub const fn sequence(&self) -> u16 {
        self.sequence
    }

    /// The per-channel reliable sequence.
    #[must_use]
    pub const fn reliable_sequence(&self) -> u16 {
        self.reliable_sequence
    }

    /// Whether the record is reliable.
    #[must_use]
    pub const fn is_reliable(&self) -> bool {
        self.reliable
    }

    /// Whether the record belongs to the connection handshake.
    #[must_use]
    pub const fn is_connecting(&self) -> bool {
        self.connecting
    }

    /// The declared chunk count; `1` when the record is not chunked.
    #[must_use]
    pub const fn num_chunks(&self) -> u16 {
        self.num_chunks
    }

    /// The flag byte the record was decoded from.
    #[must_use]
    pub const fn flags(&self) -> u8 {
        self.flags
    }

    /// The flag byte the writer must emit instead of recomputing one.
    #[must_use]
    pub const fn flags_override(&self) -> Option<u8> {
        self.flags_override
    }

    /// The id of a system message, which is the payload's last byte on channel 3.
    #[must_use]
    pub fn system_message_id(&self) -> Option<u8> {
        if self.channel != SYSTEM_CHANNEL {
            return None;
        }
        self.payload.last().copied()
    }

    /// The same record marked reliable.
    #[must_use]
    pub const fn with_reliable(mut self) -> Self {
        self.reliable = true;
        self
    }

    /// The same record marked as belonging to the handshake.
    #[must_use]
    pub const fn with_connecting(mut self) -> Self {
        self.connecting = true;
        self
    }

    /// The same record with a message sequence.
    #[must_use]
    pub const fn with_sequence(mut self, sequence: u16) -> Self {
        self.sequence = sequence;
        self
    }

    /// The same record with a reliable sequence.
    #[must_use]
    pub const fn with_reliable_sequence(mut self, reliable_sequence: u16) -> Self {
        self.reliable_sequence = reliable_sequence;
        self
    }

    /// The same record with a declared chunk count.
    #[must_use]
    pub const fn with_num_chunks(mut self, num_chunks: u16) -> Self {
        self.num_chunks = num_chunks;
        self
    }

    /// The same record with its flag byte pinned.
    ///
    /// Needed for the record forms the canonical writer would not compute on its
    /// own, such as the reference's piggyback ACK (flags `0x18`) in a reply.
    #[must_use]
    pub const fn with_flags_override(mut self, flags: u8) -> Self {
        self.flags_override = Some(flags);
        self
    }
}

/// Cross-record state while writing one datagram.
#[derive(Debug)]
struct EncodeState {
    prev_channel: Option<u8>,
    last_seq: [u16; 4],
    last_rel_seq: [u16; 4],
    has_written: [bool; 4],
}

impl EncodeState {
    const fn new() -> Self {
        Self {
            prev_channel: None,
            last_seq: [0; 4],
            last_rel_seq: [0; 4],
            has_written: [false; 4],
        }
    }
}

/// Cross-record state while reading one datagram.
#[derive(Debug)]
struct DecodeState {
    prev_channel: u8,
    per_seq: [u16; 4],
    per_rel: [u16; 4],
}

impl DecodeState {
    const fn new() -> Self {
        Self {
            prev_channel: 0,
            per_seq: [0; 4],
            per_rel: [0; 4],
        }
    }
}

/// Read every record in a datagram body, which is the bytes after the envelope.
///
/// # Errors
/// Returns [`CarrierError::InvalidChannel`] for a channel above 3 and
/// [`CarrierError::Wire`] when a field is cut short by the end of the body.
pub fn decode_records(body: &[u8]) -> Result<Vec<MessageRecord>, CarrierError> {
    let mut reader = Reader::new(body);
    let mut state = DecodeState::new();
    let mut records = Vec::new();
    while !reader.is_empty() {
        records.push(read_record(&mut reader, &mut state)?);
    }
    Ok(records)
}

fn read_record(
    reader: &mut Reader<'_>,
    state: &mut DecodeState,
) -> Result<MessageRecord, CarrierError> {
    let flags = reader.u8("flags")?;
    let size = reader.u16be("size")?;

    let no_length = flags & MF_NO_LENGTH != 0;
    let first_attempt = no_length && flags & MF_SEQUENTIAL_REL_ID != 0;
    if no_length {
        reader.u8("sub_header")?;
        if first_attempt {
            reader.u8("sub_header_first_attempt")?;
        }
    }

    let reliable = flags & MF_RELIABLE != 0;
    let connecting = flags & MF_CONNECTING != 0;

    let channel = if flags & MF_DATA_CHANNEL != 0 {
        reader.u8("channel")?
    } else {
        state.prev_channel
    };
    if channel > MAX_CHANNEL {
        return Err(CarrierError::InvalidChannel { channel });
    }
    state.prev_channel = channel;
    let slot = usize::from(channel);

    let num_chunks = if flags & MF_CHUNKS != 0 {
        reader.u16be("num_chunks")?
    } else {
        1
    };

    let sequence = if flags & MF_SEQUENTIAL_ID != 0 {
        state.per_seq[slot] = state.per_seq[slot].wrapping_add(1);
        state.per_seq[slot]
    } else {
        let sequence = reader.u16be("sequence")?;
        state.per_seq[slot] = sequence;
        sequence
    };

    let reliable_sequence = if flags & MF_SEQUENTIAL_REL_ID == 0 {
        let reliable_sequence = reader.u16be("reliable_sequence")?;
        state.per_rel[slot] = reliable_sequence;
        reliable_sequence
    } else if reliable {
        state.per_rel[slot] = state.per_rel[slot].wrapping_add(1);
        state.per_rel[slot]
    } else {
        state.per_rel[slot]
    };

    let payload_len = if no_length {
        reader.remaining()
    } else {
        usize::from(size)
    };
    let payload = reader.take("payload", payload_len)?.to_vec();

    Ok(MessageRecord {
        channel,
        payload,
        sequence,
        reliable_sequence,
        reliable,
        connecting,
        num_chunks,
        flags,
        flags_override: None,
    })
}

/// Write every record into one datagram body, without the envelope.
///
/// # Errors
/// Returns [`CarrierError::InvalidChannel`] for a channel above 3,
/// [`CarrierError::PayloadTooLong`] when a payload needs more than a `u16` byte
/// count, and [`CarrierError::Wire`] when a card's codec refuses a value.
pub fn encode_records(records: &[MessageRecord]) -> Result<Vec<u8>, CarrierError> {
    let mut out = Vec::new();
    let mut state = EncodeState::new();
    for record in records {
        write_record(&mut out, record, &mut state)?;
    }
    Ok(out)
}

fn write_record(
    out: &mut Vec<u8>,
    record: &MessageRecord,
    state: &mut EncodeState,
) -> Result<(), CarrierError> {
    if record.channel > MAX_CHANNEL {
        return Err(CarrierError::InvalidChannel {
            channel: record.channel,
        });
    }
    let slot = usize::from(record.channel);

    let payload_len =
        u16::try_from(record.payload.len()).map_err(|_| CarrierError::PayloadTooLong {
            len: record.payload.len(),
        })?;

    let (flags, seq_seq, rel_seq_seq, channel_changed) = if let Some(flags) = record.flags_override
    {
        (
            flags,
            flags & MF_SEQUENTIAL_ID != 0,
            flags & MF_SEQUENTIAL_REL_ID != 0,
            flags & MF_DATA_CHANNEL != 0,
        )
    } else {
        // Writer optimization: a sequence that is the previous value plus one
        // is left out of the byte stream, exactly as the reference writer does.
        let seq_seq =
            state.has_written[slot] && state.last_seq[slot].wrapping_add(1) == record.sequence;
        let rel_seq_seq = state.has_written[slot]
            && record.reliable
            && state.last_rel_seq[slot].wrapping_add(1) == record.reliable_sequence;
        let channel_changed = state.prev_channel != Some(record.channel);
        let mut flags = 0;
        if record.reliable {
            flags |= MF_RELIABLE;
        }
        if record.num_chunks > 1 {
            flags |= MF_CHUNKS;
        }
        if seq_seq {
            flags |= MF_SEQUENTIAL_ID;
        }
        if rel_seq_seq {
            flags |= MF_SEQUENTIAL_REL_ID;
        }
        if channel_changed {
            flags |= MF_DATA_CHANNEL;
        }
        if record.connecting {
            flags |= MF_CONNECTING;
        }
        (flags, seq_seq, rel_seq_seq, channel_changed)
    };

    out.push(flags);
    out.extend_from_slice(&payload_len.to_be_bytes());
    if flags & MF_NO_LENGTH != 0 {
        out.push(0);
        if flags & MF_SEQUENTIAL_REL_ID != 0 {
            out.push(0);
        }
    }
    if channel_changed {
        out.push(record.channel);
    }
    if flags & MF_CHUNKS != 0 {
        out.extend_from_slice(&record.num_chunks.to_be_bytes());
    }
    if !seq_seq {
        out.extend_from_slice(&record.sequence.to_be_bytes());
    }
    if !rel_seq_seq {
        out.extend_from_slice(&record.reliable_sequence.to_be_bytes());
    }
    out.extend_from_slice(&record.payload);

    state.prev_channel = Some(record.channel);
    state.last_seq[slot] = record.sequence;
    if record.reliable {
        state.last_rel_seq[slot] = record.reliable_sequence;
    }
    state.has_written[slot] = true;
    Ok(())
}

/// A plaintext datagram: an envelope and the records it carries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Datagram {
    envelope: Envelope,
    records: Vec<MessageRecord>,
}

impl Datagram {
    /// Build a datagram from an envelope and its records.
    #[must_use]
    pub const fn new(envelope: Envelope, records: Vec<MessageRecord>) -> Self {
        Self { envelope, records }
    }

    /// Read a plaintext datagram.
    ///
    /// # Errors
    /// Returns [`CarrierError::CompressedBody`] when the body is an LZ4 block,
    /// plus every error [`Envelope::decode`] and [`decode_records`] can raise.
    pub fn decode(datagram: &[u8]) -> Result<Self, CarrierError> {
        let (envelope, body) = Envelope::decode(datagram)?;
        if envelope.is_compressed() {
            return Err(CarrierError::CompressedBody);
        }
        let records = decode_records(body)?;
        Ok(Self { envelope, records })
    }

    /// The envelope header.
    #[must_use]
    pub const fn envelope(&self) -> &Envelope {
        &self.envelope
    }

    /// The records, in wire order.
    #[must_use]
    pub fn records(&self) -> &[MessageRecord] {
        &self.records
    }

    /// The records, mutably, so a caller can pin each `flags` byte to reproduce a
    /// captured datagram byte for byte.
    #[must_use]
    pub fn records_mut(&mut self) -> &mut [MessageRecord] {
        &mut self.records
    }

    /// Write the whole datagram, envelope included.
    ///
    /// # Errors
    /// Returns every error [`encode_records`] can raise.
    pub fn encode(&self) -> Result<Vec<u8>, CarrierError> {
        let mut out = Vec::new();
        self.envelope.encode(&mut out);
        out.extend_from_slice(&encode_records(&self.records)?);
        Ok(out)
    }
}

/// A datagram or record that does not match the Carrier framing.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum CarrierError {
    /// The datagram ended before the four envelope bytes were complete.
    EnvelopeTooShort {
        /// Bytes that arrived.
        have: usize,
    },
    /// The envelope type byte is neither `0x80` nor `0x81`.
    BadEnvelopeType {
        /// The byte found.
        found: u8,
    },
    /// The envelope protocol byte is not `0x01`.
    BadEnvelopeProto {
        /// The byte found.
        found: u8,
    },
    /// A record names a channel above 3.
    InvalidChannel {
        /// The channel found.
        channel: u8,
    },
    /// A payload needs more bytes than a `u16` byte count can hold.
    PayloadTooLong {
        /// The payload length offered.
        len: usize,
    },
    /// The body is an LZ4 block, so it is not a record stream.
    CompressedBody,
    /// The body's own bytes are cut short.
    Wire(WireError),
}

impl From<WireError> for CarrierError {
    fn from(source: WireError) -> Self {
        Self::Wire(source)
    }
}

impl std::fmt::Display for CarrierError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::EnvelopeTooShort { have } => {
                write!(
                    f,
                    "datagram has {have} byte(s), too short for the 4-byte envelope"
                )
            }
            Self::BadEnvelopeType { found } => {
                write!(f, "envelope type byte is {found:#04x}, not 0x80 or 0x81")
            }
            Self::BadEnvelopeProto { found } => {
                write!(f, "envelope proto byte is {found:#04x}, not 0x01")
            }
            Self::InvalidChannel { channel } => {
                write!(f, "record channel {channel} is above the max of 3")
            }
            Self::PayloadTooLong { len } => {
                write!(f, "payload of {len} byte(s) does not fit a u16 size field")
            }
            Self::CompressedBody => write!(f, "body is LZ4-compressed, not a record stream"),
            Self::Wire(source) => write!(f, "record framing: {source}"),
        }
    }
}

impl std::error::Error for CarrierError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Wire(source) => Some(source),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_canonical_flag_byte_matches_the_reference_writer() {
        let records = vec![
            MessageRecord::new(0, vec![0xaa]).with_reliable(),
            MessageRecord::new(0, vec![0xbb])
                .with_reliable()
                .with_sequence(1)
                .with_reliable_sequence(1),
        ];
        let produced = encode_records(&records).expect("records encode");
        // First record: RELIABLE|DATA_CHANNEL, fields all written.
        // Second record: RELIABLE|SEQUENTIAL_ID|SEQUENTIAL_REL_ID, both fields omitted.
        assert_eq!(
            produced,
            vec![
                0x21, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0xaa, 0x19, 0x00, 0x01, 0xbb
            ]
        );
    }

    #[test]
    fn a_chunked_record_round_trips() {
        let records = vec![MessageRecord::new(0, vec![1, 2, 3, 4]).with_num_chunks(3)];
        let produced = encode_records(&records).expect("records encode");
        let decoded = decode_records(&produced).expect("records decode");
        assert_eq!(decoded.len(), 1);
        assert_eq!(decoded[0].payload(), &[1, 2, 3, 4]);
        assert_eq!(decoded[0].num_chunks(), 3);
        assert_eq!(
            encode_records(&decoded).expect("records re-encode"),
            produced
        );
    }

    #[test]
    fn a_no_length_record_runs_to_the_end_of_the_datagram() {
        let records = vec![
            MessageRecord::new(0, vec![0xde, 0xad, 0xbe, 0xef]).with_flags_override(MF_NO_LENGTH),
        ];
        let produced = encode_records(&records).expect("records encode");
        let decoded = decode_records(&produced).expect("records decode");
        assert_eq!(decoded[0].payload(), &[0xde, 0xad, 0xbe, 0xef]);
        assert_ne!(decoded[0].flags() & MF_NO_LENGTH, 0);
    }

    #[test]
    fn a_no_length_first_attempt_record_round_trips() {
        let records = vec![
            MessageRecord::new(0, vec![0x01, 0x02])
                .with_flags_override(MF_NO_LENGTH | MF_SEQUENTIAL_REL_ID),
        ];
        let produced = encode_records(&records).expect("records encode");
        let decoded = decode_records(&produced).expect("records decode");
        assert_eq!(decoded[0].payload(), &[0x01, 0x02]);
        assert_ne!(decoded[0].flags() & MF_NO_LENGTH, 0);
    }

    #[test]
    fn a_channel_above_three_is_refused_by_name() {
        let record = MessageRecord::new(4, Vec::new());
        assert_eq!(
            encode_records(&[record]),
            Err(CarrierError::InvalidChannel { channel: 4 })
        );

        // flags MF_DATA_CHANNEL, size 0, channel 4, sequence 0, reliable 0.
        let body = [0x20, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00];
        assert_eq!(
            decode_records(&body),
            Err(CarrierError::InvalidChannel { channel: 4 })
        );
    }

    #[test]
    fn a_short_or_malformed_envelope_is_refused() {
        assert_eq!(
            Envelope::decode(&[0x80, 0x01, 0x00]),
            Err(CarrierError::EnvelopeTooShort { have: 3 })
        );
        assert_eq!(
            Envelope::decode(&[0x00, 0x01, 0x00, 0x00]),
            Err(CarrierError::BadEnvelopeType { found: 0x00 })
        );
        assert_eq!(
            Envelope::decode(&[0x82, 0x01, 0x00, 0x00]),
            Err(CarrierError::BadEnvelopeType { found: 0x82 })
        );
        assert_eq!(
            Envelope::decode(&[0x80, 0x02, 0x00, 0x00]),
            Err(CarrierError::BadEnvelopeProto { found: 0x02 })
        );
    }

    #[test]
    fn a_system_id_is_only_read_on_channel_three() {
        let system = MessageRecord::new(3, vec![0x00, 0x06]);
        assert_eq!(system.system_message_id(), Some(6));
        let data = MessageRecord::new(0, vec![0x00, 0x06]);
        assert_eq!(data.system_message_id(), None);
        let empty = MessageRecord::new(3, Vec::new());
        assert_eq!(empty.system_message_id(), None);
    }
}
