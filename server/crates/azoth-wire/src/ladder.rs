//! The post-V3 ladder: the messages that take a client from "registered" to "in the world".
//!
//! WHY THIS EXISTS
//! ===============
//! Registration alone leaves the client sitting in `WaitingForActorGameConnection`. Getting to
//! `InGame` needs four more messages, in order, and the order is not optional — sending two of them
//! in one burst **crashed the client** (measured, recorded in the prototype).
//!
//! ```text
//!   V3 registration response      rep.ready 0 -> 1
//!   Cmd_Greetings                 GridMate's peer handshake
//!   SelfIdentification (0x5d1)    WaitingForActorGameConnection -> WaitingForSpawnPoint
//!   LevelInfoChanged              WaitingForSpawnPoint -> WaitingForPlayerSpawn, the map loads
//!   the spawn record (record-1)   WaitingForPlayerSpawn -> InGame, the player appears
//!   the ongoing state stream      keeps the ALC cable clear
//! ```
//!
//! WHERE THE SHAPES COME FROM, AND WHY THE DISTINCTION MATTERS
//! ==========================================================
//! **Two of the three are composed, one is captured**, and the difference is load-bearing:
//!
//! * `Cmd_Greetings` is GridMate's stock protocol.
//! * `SelfIdentification` was reverse-engineered by another emulator (first-light) and then
//!   validated live here. It is inherited evidence, and the only thing this port can add is byte
//!   parity against the implementation that already works.
//! * `LevelInfoChanged` is **captured**, because the prototype's composer for it is **dead code with
//!   a wrong layout**: `level_info_changed_body()` claims 92 bytes and is never called, while the
//!   real message (wire `0x663`) is 106 bytes and its second string is a `coatlicue/`-prefixed path
//!   rather than the plain level name. Porting from that function would send a malformed message.
//!   So this module exports the type number and the measured structure, and **does not compose one**.
//!
//! `tests/fixtures/ladder.json` carries all three as the oracle.
//!
//! WHY THE CLIENT IS FORGIVING HERE AND STRICT ELSEWHERE
//! ====================================================
//! These bodies are mostly zeros, and the client reads them as a state trigger rather than as data
//! it validates. That is exactly why they are worth pinning with a byte test: nothing will complain
//! if a field drifts, and the symptom would be a client stuck one state earlier with no error.
//!
//! WHAT IS NOT HERE
//! ================
//! The spawn record and the ongoing state stream. Their payloads are captured bytes, and they live
//! in `crate::player_record` and in the caller's fixtures. This module owns only the messages whose
//! shape can be *composed*.

use crate::bundle::Record;
use crate::fragment::Fragment;
use crate::marshal::marshal;
use crate::record::MessageRecord;
use crate::varint;
use crate::error::WireError;

/// Wire type of `PlayerManagerSelfIdentificationMsg`.
pub const SELF_IDENTIFICATION_TYPE: u32 = 0x5D1;
/// Wire type of `LevelInfoChangedMsg`.
///
/// **Measured from the capture**, replay seqs `0x10` and `0x4d`, which are byte-identical. The
/// prototype's composer for this message is dead code and its layout disagrees with the capture, so
/// the number comes from the wire rather than from the source.
pub const LEVEL_INFO_CHANGED_TYPE: u32 = 0x663;
/// The command id of GridMate's `Cmd_Greetings`.
const CMD_GREETINGS: u8 = 1;
/// The peer id the prototype uses. Crc32-derived in the reference implementation; a stable
/// placeholder here, because the client does not verify it.
const PEER_ID: u32 = 0x415A_4F54; // 'AZOT'
/// The replica id seed. Any value works; a small non-zero one is what the reference sends.
const REP_ID_SEED: u32 = 1 << 25;

/// The level the captured `LevelInfoChanged` names.
pub const DEFAULT_LEVEL: &str = "NewWorld_VitaeEterna";

/// The second string in the captured body: the level with its package prefix.
///
/// It is **not** a copy of [`DEFAULT_LEVEL`], which is what the prototype's dead composer assumed.
pub const DEFAULT_LEVEL_PREFIX: &str = "coatlicue/NewWorld_VitaeEterna";

/// The four big-endian `f32` values the captured body carries after the two strings.
///
/// Their meaning is **not established**. They are identical in both captured copies, so they are
/// constants of this level rather than per-session values — which is the only claim made here.
pub const LEVEL_BOUNDS: [f32; 4] = [2048.0, 16.0, 12272.0, 10250.0];

/// Bytes of the captured body that follow the decoded structure and are not explained.
///
/// Twenty-six bytes: the body is 106, and the two length-prefixed strings plus the sixteen bytes of
/// `f32`, two `u32` and four flag bytes account for 80. Until those 26 are decoded,
/// `LevelInfoChanged` **cannot be composed**, only served from a captured template — which is why
/// this module has no builder for it. (A first version of this constant said 38; that was arithmetic
/// done in prose instead of in a test, and the test is what caught it.)
pub const LEVEL_INFO_CHANGED_TAIL: usize = 26;

/// `Cmd_Greetings`: `[CmdId][PeerId u32 BE][isHost][RepIdSeed u32 BE]`.
///
/// Sent as a reliable data-channel record. The client treats a greeting from a peer marked as host
/// as the start of a GridMate session.
#[must_use]
pub fn greetings_payload() -> Vec<u8> {
    let mut out = Vec::with_capacity(10);
    out.push(CMD_GREETINGS);
    out.extend_from_slice(&PEER_ID.to_be_bytes());
    out.push(1); // peerIsHost
    out.extend_from_slice(&REP_ID_SEED.to_be_bytes());
    out
}

/// `PlayerManagerSelfIdentificationMsg` body: 21 bytes, all zero in every captured instance.
///
/// The handler reads a 56-byte in-memory struct; the wire form drops the alignment padding, which
/// is why the body is shorter than the struct. That mismatch is measured, not an error.
#[must_use]
pub fn self_identification_body() -> Vec<u8> {
    let mut out = Vec::with_capacity(21);
    out.extend_from_slice(&0u32.to_le_bytes()); // field_0
    out.extend_from_slice(&0u32.to_le_bytes()); // vector count = 0
    out.push(0); // debug flag
    out.extend_from_slice(&0u64.to_le_bytes()); // field_2c
    out.extend_from_slice(&0u32.to_le_bytes()); // field_34
    out
}

/// An `AZStd::string`: a `u8` length then the bytes.
///
/// # Panics
/// Never in practice: the level names the client accepts are far shorter than 255 bytes. The
/// `debug_assert` documents the limit without making the signature awkward.
fn push_az_string(out: &mut Vec<u8>, text: &str) {
    debug_assert!(text.len() < 256, "AZStd::string length is a u8");
    out.push(text.len() as u8);
    out.extend_from_slice(text.as_bytes());
}

/// Wrap a typed message body in the server's data-channel record.
///
/// The payload is `[VLQ32 length][00 01][varint type][body]`, and the length covers everything after
/// itself. Measured 2026-09-20: a record without the VLQ prefix dies with
/// `registration_unmarshal_error`, so the prefix is not optional.
///
/// # Errors
/// Propagates a varint range error.
pub fn typed_record_payload(wire_type: u32, body: &[u8]) -> Result<Vec<u8>, WireError> {
    let mut inner = crate::TYPE_MARKER.to_vec();
    varint::encode_into(u64::from(wire_type), &mut inner)?;
    inner.extend_from_slice(body);
    let mut payload = varint::encode(inner.len() as u64)?;
    payload.extend_from_slice(&inner);
    Ok(payload)
}

/// A reliable data-channel record carrying a typed message.
///
/// # Errors
/// Propagates an encode error.
pub fn typed_record(
    wire_type: u32,
    body: &[u8],
    sequence: u16,
    reliable_sequence: u16,
) -> Result<MessageRecord, WireError> {
    Ok(MessageRecord {
        reliable: true,
        connecting: false,
        channel: 0,
        sequence,
        reliable_sequence,
        num_chunks: 1,
        payload: typed_record_payload(wire_type, body)?,
        flags: crate::record::flags::RELIABLE | crate::record::flags::DATA_CHANNEL,
    })
}

/// Wrap records into one datagram, envelope included.
///
/// The envelope sequence numbers the datagram, which is a different counter from the per-channel
/// record sequences: an ACK range is expressed over the envelope counter, and conflating the two is
/// the mistake that cost the prototype a session at ~26 minutes.
///
/// # Errors
/// Propagates a marshal error.
pub fn datagram(envelope_sequence: u16, records: &[MessageRecord]) -> Result<Vec<u8>, WireError> {
    let body = marshal(records)?;
    let mut out = Vec::with_capacity(body.len() + 4);
    out.push(0x80); // plaintext
    out.push(0x01); // protocol
    out.extend_from_slice(&envelope_sequence.to_be_bytes());
    out.extend_from_slice(&body);
    Ok(out)
}

/// A record built from fragments, as the state bundle carries them.
///
/// Present so a caller composing a state record does not have to reach into `bundle` and `fragment`
/// itself; the two crates' types meet here.
///
/// # Errors
/// Propagates a fragment encode error.
pub fn fragment_record(record_id: u8, fragments: Vec<Fragment>) -> Result<Record, WireError> {
    for fragment in &fragments {
        // Encoding validates the varints; the bytes are discarded because `Record` holds the parts.
        let _ = fragment.encode()?;
    }
    Ok(Record {
        record_id,
        fragments,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_greeting_is_ten_bytes_and_names_us_host() {
        let payload = greetings_payload();
        assert_eq!(payload.len(), 10);
        assert_eq!(payload[0], CMD_GREETINGS);
        assert_eq!(u32::from_be_bytes(payload[1..5].try_into().expect("4")), PEER_ID);
        assert_eq!(payload[5], 1, "peerIsHost must be true");
        assert_eq!(
            u32::from_be_bytes(payload[6..10].try_into().expect("4")),
            REP_ID_SEED
        );
    }

    #[test]
    fn self_identification_is_twenty_one_zero_bytes() {
        let body = self_identification_body();
        assert_eq!(body.len(), 21);
        // The handler reads a 56-byte struct; the wire form drops the alignment padding. Every
        // captured instance is zero, so a non-zero byte here would be a layout error.
        assert!(body.iter().all(|b| *b == 0), "every field is zero");
    }

    #[test]
    fn the_level_info_type_is_the_measured_one() {
        // 0x663, from the capture. The prototype's composer used no number at all (dead code), and
        // a first version of this module guessed 0x08D3, which was wrong.
        assert_eq!(LEVEL_INFO_CHANGED_TYPE, 0x663);
    }

    #[test]
    fn the_two_level_strings_are_not_the_same_string() {
        // The captured body's second string carries a package prefix; the prototype's dead
        // composer sent the plain name twice, which is one of the ways its layout was wrong.
        assert_ne!(DEFAULT_LEVEL, DEFAULT_LEVEL_PREFIX);
        assert!(DEFAULT_LEVEL_PREFIX.ends_with(DEFAULT_LEVEL));
    }

    #[test]
    fn the_captured_body_has_the_measured_shape() {
        // 2 azstr + 4 f32 + 2 u32 + 4 flag bytes + the unexplained tail.
        let body_len = (1 + DEFAULT_LEVEL.len())
            + (1 + DEFAULT_LEVEL_PREFIX.len())
            + 4 * 4 + 2 * 4 + 4 + LEVEL_INFO_CHANGED_TAIL;
        assert_eq!(body_len, 106, "the captured body is 106 bytes");
    }

    #[test]
    fn a_typed_record_payload_starts_with_its_own_length() {
        let payload = typed_record_payload(SELF_IDENTIFICATION_TYPE, &self_identification_body())
            .expect("encodes");
        let (declared, after) = varint::decode(&payload, 0).expect("length varint");
        assert_eq!(declared as usize, payload.len() - after, "length covers the rest");
        assert_eq!(&payload[after..after + 2], &crate::TYPE_MARKER);
    }

    #[test]
    fn a_datagram_carries_the_envelope_sequence() {
        let record = typed_record(SELF_IDENTIFICATION_TYPE, &self_identification_body(), 1, 1)
            .expect("record");
        let bytes = datagram(0x1234, &[record]).expect("datagram");
        assert_eq!(bytes[0] & 0x80, 0x80, "plaintext envelope");
        assert_eq!(bytes[1], 0x01);
        assert_eq!(u16::from_be_bytes([bytes[2], bytes[3]]), 0x1234);
    }

    #[test]
    fn a_fragment_record_keeps_its_parts() {
        let record = fragment_record(
            1,
            vec![
                Fragment::new(16, 11, vec![1, 2]),
                Fragment::new(22, 3857, vec![3]),
            ],
        )
        .expect("record");
        assert_eq!(record.record_id, 1);
        assert_eq!(record.fragments.len(), 2);
    }
}
