//! Serializing records: the write side of the MessageRecord framing.
//!
//! WHY THIS IS A SEPARATE MODULE FROM [`crate::record`]
//! ====================================================
//! Reading and writing have different reasons to change and different failure
//! modes. Reading must survive whatever a client sends and reject it precisely;
//! writing must reproduce the exact byte choices the client's own writer makes,
//! because the client *validates* flag bytes rather than tolerating them.
//!
//! THE FIELD-OMISSION STATE MACHINE
//! ================================
//! A datagram is not a bag of independent records: the writer omits a field when
//! it would merely repeat an auto-increment, and the receiver reconstructs it
//! from the same state. So serialization carries cross-record state — the
//! previous channel, and the last sequence and reliable sequence per channel —
//! and a record cannot be serialized in isolation. That is why [`marshal`] takes
//! the whole list.
//!
//! Two measured rules that are easy to get wrong:
//!
//! * **A non-reliable record still writes its relSeq.** The omission applies only
//!   to reliable records. Applying it more broadly produced flag bytes the client
//!   rejects.
//! * **The `NO_LENGTH` form writes a sub-header byte** after the size field, and
//!   the first-attempt form writes two. See [`crate::record`].

use crate::MAX_CHANNEL;
use crate::error::WireError;
use crate::record::{MessageRecord, flags};

/// Cross-record state within one datagram.
///
/// `prev_channel` starts at **0**, not -1, because that is what the client's own
/// writer does: 8 of 107 captured datagrams omit the channel byte on their FIRST
/// record, and every one of those is a channel-0 record. A writer that starts at
/// -1 emits a redundant `DATA_CHANNEL` flag plus a byte on every such datagram.
///
/// Measured by comparing a re-marshal against the capture: the client's byte
/// stream is reproduced exactly at 0 and differs by one byte at -1. The Python
/// prototype uses -1, so it is the one that is wrong here — by one byte per
/// datagram, on the outbound path.
#[derive(Debug, Clone)]
struct MarshalState {
    prev_channel: u8,
    last_seq: [u16; 4],
    last_rel_seq: [u16; 4],
    has_written: [bool; 4],
}

impl MarshalState {
    fn new() -> Self {
        Self {
            prev_channel: 0,
            last_seq: [0; 4],
            last_rel_seq: [0; 4],
            has_written: [false; 4],
        }
    }
}

/// Serialize one record into `out`, updating the datagram's cross-record state.
fn marshal_record(
    out: &mut Vec<u8>,
    record: &MessageRecord,
    state: &mut MarshalState,
) -> Result<(), WireError> {
    if record.channel > MAX_CHANNEL {
        return Err(WireError::BadChannel {
            channel: record.channel,
        });
    }
    let slot = usize::from(record.channel);

    // The writer omits a field when it would just repeat the auto-increment.
    let seq_seq =
        state.has_written[slot] && state.last_seq[slot].wrapping_add(1) == record.sequence;
    let rel_seq_seq = state.has_written[slot]
        && record.reliable
        && state.last_rel_seq[slot].wrapping_add(1) == record.reliable_sequence;
    let channel_changed = state.prev_channel != record.channel;

    let mut computed = 0u8;
    if record.reliable {
        computed |= flags::RELIABLE;
    }
    if record.num_chunks > 1 {
        computed |= flags::CHUNKS;
    }
    if seq_seq {
        computed |= flags::SEQUENTIAL_ID;
    }
    if rel_seq_seq {
        computed |= flags::SEQUENTIAL_REL_ID;
    }
    if channel_changed {
        computed |= flags::DATA_CHANNEL;
    }
    if record.connecting {
        computed |= flags::CONNECTING;
    }

    out.push(computed);
    let size = u16::try_from(record.payload.len()).map_err(|_| WireError::OutOfRange {
        field: "record size",
        value: record.payload.len() as u64,
        limit: u64::from(u16::MAX) + 1,
    })?;
    out.extend_from_slice(&size.to_be_bytes());
    if computed & flags::NO_LENGTH != 0 {
        out.push(0);
        if computed & flags::SEQUENTIAL_REL_ID != 0 {
            out.push(0);
        }
    }
    if channel_changed {
        out.push(record.channel);
    }
    if computed & flags::CHUNKS != 0 {
        out.extend_from_slice(&record.num_chunks.to_be_bytes());
    }
    if !seq_seq {
        out.extend_from_slice(&record.sequence.to_be_bytes());
    }
    if !rel_seq_seq {
        out.extend_from_slice(&record.reliable_sequence.to_be_bytes());
    }
    out.extend_from_slice(&record.payload);

    state.prev_channel = record.channel;
    state.last_seq[slot] = record.sequence;
    if record.reliable {
        state.last_rel_seq[slot] = record.reliable_sequence;
    }
    state.has_written[slot] = true;
    Ok(())
}

/// Serialize a datagram's records, envelope excluded.
///
/// # Errors
/// [`WireError::BadChannel`] for a channel above 3, or
/// [`WireError::OutOfRange`] when a payload exceeds the `u16` size field.
pub fn marshal(records: &[MessageRecord]) -> Result<Vec<u8>, WireError> {
    let mut out = Vec::new();
    let mut state = MarshalState::new();
    for record in records {
        marshal_record(&mut out, record, &mut state)?;
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::record::parse;

    /// Compare everything except the flag byte, which the writer derives.
    fn strip(record: &MessageRecord) -> MessageRecord {
        MessageRecord {
            flags: 0,
            ..record.clone()
        }
    }

    #[test]
    fn round_trips_one_record() {
        let record = MessageRecord {
            reliable: true,
            ..MessageRecord::data(0, 7, 9, vec![1, 2, 3])
        };
        let bytes = marshal(&[record.clone()]).expect("marshal");
        let parsed = parse(&bytes).expect("parse");
        assert_eq!(parsed.records.len(), 1);
        assert_eq!(strip(&parsed.records[0]), strip(&record));
        assert_eq!(parsed.trailing_bytes, 0);
    }

    /// Two records on one channel: the second omits the channel byte and both
    /// sequence fields, because both would auto-increment.
    #[test]
    fn omits_repeating_fields() {
        let first = MessageRecord::data(0, 7, 9, vec![0xAA]);
        let second = MessageRecord::data(0, 8, 10, vec![0xBB]);
        let bytes = marshal(&[first, second]).expect("marshal");
        let parsed = parse(&bytes).expect("parse");
        assert_eq!(parsed.records.len(), 2);
        assert_eq!(parsed.records[1].sequence, 8);
        assert_eq!(parsed.records[1].channel, 0);
        // The second record's flag byte carries no DATA_CHANNEL and no
        // SEQUENTIAL_ID: the fields were omitted, not repeated.
        let second_flags = bytes[4];
        assert_eq!(second_flags & flags::DATA_CHANNEL, 0);
        assert_eq!(second_flags & flags::SEQUENTIAL_ID, 0);
    }

    /// The first record of a datagram omits its channel byte when that channel
    /// is 0, because the client's writer starts with a previous channel of 0.
    /// Measured: 8 of 107 captured datagrams do exactly this.
    #[test]
    fn the_first_record_omits_a_channel_zero() {
        let bytes = marshal(&[MessageRecord::data(0, 1, 1, vec![])]).expect("marshal");
        assert_eq!(bytes[0] & flags::DATA_CHANNEL, 0, "channel 0 is implicit");
        // And the reader reconstructs it.
        let parsed = parse(&bytes).expect("parse");
        assert_eq!(parsed.records[0].channel, 0);
    }

    /// A first record on any OTHER channel must still write the byte, because the
    /// reader's implicit value is 0.
    #[test]
    fn the_first_record_writes_a_non_zero_channel() {
        for channel in 1..=3u8 {
            let bytes =
                marshal(&[MessageRecord::data(channel, 1, 1, vec![])]).expect("marshal");
            assert_ne!(
                bytes[0] & flags::DATA_CHANNEL,
                0,
                "channel {channel} must be written"
            );
            let parsed = parse(&bytes).expect("parse");
            assert_eq!(parsed.records[0].channel, channel);
        }
    }

    /// A non-reliable record still writes its relSeq, even when consecutive:
    /// the omission is only valid for reliable records. Its SEQUENCE, however,
    /// may still be omitted, because that omission has no reliability condition.
    #[test]
    fn a_non_reliable_record_writes_its_rel_seq() {
        let first = MessageRecord::data(0, 1, 1, vec![]);
        let second = MessageRecord::data(0, 2, 2, vec![]);
        // Where the second record starts: marshal the first alone and measure.
        let head = marshal(&[first.clone()]).expect("marshal");
        let bytes = marshal(&[first, second]).expect("marshal");
        let second_flags = bytes[head.len()];
        assert_eq!(
            second_flags & flags::SEQUENTIAL_REL_ID,
            0,
            "relSeq must be written for a non-reliable record"
        );
        assert_ne!(
            second_flags & flags::SEQUENTIAL_ID,
            0,
            "the sequence may be omitted: that omission has no reliability condition"
        );
        assert_eq!(second_flags & flags::DATA_CHANNEL, 0, "channel omitted");
        let parsed = parse(&bytes).expect("parse");
        assert_eq!(parsed.records[1].sequence, 2);
        assert_eq!(parsed.records[1].reliable_sequence, 2);
    }

    #[test]
    fn handles_two_channels_in_one_datagram() {
        let system = MessageRecord::data(3, 1, 1, vec![0x00, 0x06]);
        let data = MessageRecord::data(1, 1, 1, vec![0xEE]);
        let bytes = marshal(&[system, data]).expect("marshal");
        let parsed = parse(&bytes).expect("parse");
        assert_eq!(parsed.records.len(), 2);
        assert_eq!(parsed.records[0].channel, 3);
        assert_eq!(parsed.records[0].system_msg_id(), Some(6));
        assert_eq!(parsed.records[1].channel, 1);
        assert_eq!(parsed.records[1].system_msg_id(), None);
    }

    #[test]
    fn rejects_a_channel_above_three() {
        let bad = MessageRecord::data(4, 1, 1, vec![]);
        let err = marshal(&[bad]).expect_err("must fail");
        assert!(matches!(err, WireError::BadChannel { .. }), "{err}");
    }

    #[test]
    fn chunked_records_keep_their_count() {
        let record = MessageRecord {
            num_chunks: 12,
            ..MessageRecord::data(0, 1, 1, vec![0x01, 0x02])
        };
        let bytes = marshal(&[record.clone()]).expect("marshal");
        let parsed = parse(&bytes).expect("parse");
        assert_eq!(parsed.records[0].num_chunks, 12);
        assert_eq!(strip(&parsed.records[0]), strip(&record));
    }

    /// A reliable record whose relSeq auto-increments omits the field.
    #[test]
    fn a_reliable_record_omits_an_incrementing_rel_seq() {
        let first = MessageRecord {
            reliable: true,
            ..MessageRecord::data(0, 1, 5, vec![])
        };
        let second = MessageRecord {
            reliable: true,
            ..MessageRecord::data(0, 2, 6, vec![])
        };
        let head = marshal(&[first.clone()]).expect("marshal");
        let bytes = marshal(&[first, second]).expect("marshal");
        let second_flags = bytes[head.len()];
        assert_ne!(second_flags & flags::SEQUENTIAL_REL_ID, 0);
        let parsed = parse(&bytes).expect("parse");
        assert_eq!(parsed.records[1].reliable_sequence, 6);
    }
}
