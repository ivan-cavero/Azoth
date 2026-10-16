//! The Javelin type-0x08 StateBundle: the entity/component replication record.
//!
//! Ported from `services/world/src/azoth_world/javelin/bundle.py`, which is the
//! reference implementation. Two models passed every self-consistency check before it
//! and were still wrong, so the shape below is the one the CLIENT's own readers
//! measured, not the one that "consumes the body exactly" (an opaque-remainder model
//! always consumes exactly, which is why that check cannot discriminate).
//!
//! THE VERIFIED LAYOUT
//!
//! ```text
//! [00 01 <varint 0x08>]      typed marker
//! [8-byte prologue]          offsets 3..10: `01 <varint SEQ> 01 01 01 01 00 00`
//!                            the six bytes after the seq varint are INVARIANT
//! [varint payload_length]
//! [payload]                  a SEQUENCE OF RECORDS, each:
//!                                [u8 record_id][u8 fragment_count][fragments…]
//! ```
//!
//! A FRAGMENT is `[varint KEY][varint TYPE_INDEX][type-specific payload]` with **no
//! length field** — the payload length is implied by the type. Across 300 fragments the
//! client's own reader reported the first two varints at offsets 0 and 1 in every single
//! one, with 48 distinct keys and a 1:1 key→type binding.
//!
//! THE REPLICATION GATE. The client accepts an unreliable replication message only when
//! its `clientContextInstanceId` matches `port[+0x80]` AND its counter is strictly
//! greater than `port[+0x78]`. That counter is the `SEQ` varint here, and because it is a
//! varint, advancing it must RE-ENCODE it: writing a byte `>= 0x80` turns a one-byte
//! varint into a two-byte one and shifts everything after it, which is the measured
//! `Failed to unmarshal … ValidationError`.
//!
//! WHAT THIS MODULE DOES NOT DO: decode a fragment's payload. The per-type payload
//! encoding is the remaining long tail; a fragment is exposed as `key`, `type_index` and
//! raw `payload` bytes.

use crate::varint;

/// The state-bundle type id.
pub const STATE_BUNDLE_TYPE: u64 = 0x08;
/// A typed message begins with a two-byte tag then the varint type.
pub const TYPE_MARKER: [u8; 2] = [0x00, 0x01];
/// The replication counter varint sits here in the body.
const SEQ_OFFSET: usize = 4;
/// The prologue is `01 <varint SEQ> <6 invariant bytes>`.
const PROLOGUE_HEAD: u8 = 0x01;
/// The six bytes after the seq varint never vary across the capture, which makes them a
/// layout check: if they move, the build changed and every offset here is suspect.
pub const PROLOGUE_TAIL: [u8; 6] = [0x01, 0x01, 0x01, 0x01, 0x00, 0x00];

/// A state bundle body that does not match the verified layout.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BundleError(pub String);

impl std::fmt::Display for BundleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for BundleError {}

impl From<varint::VarintError> for BundleError {
    fn from(err: varint::VarintError) -> Self {
        BundleError(err.0)
    }
}

/// A parsed type-0x08 body. `payload` is the length-prefixed blob, a sequence of records.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BundleBody {
    pub replication_seq: u64,
    pub payload: Vec<u8>,
}

impl BundleBody {
    /// Serialize back to the 0x08 body (everything after the type marker).
    pub fn encode_body(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(16 + self.payload.len());
        out.push(PROLOGUE_HEAD);
        out.extend_from_slice(&varint::encode(self.replication_seq).expect("seq in range"));
        out.extend_from_slice(&PROLOGUE_TAIL);
        out.extend_from_slice(&varint::encode(self.payload.len() as u64).expect("len in range"));
        out.extend_from_slice(&self.payload);
        out
    }
}

/// `00 01 <varint type>` — the tag every inbound typed message carries.
pub fn encode_type_marker(type_id: u64) -> Vec<u8> {
    let mut out = TYPE_MARKER.to_vec();
    out.extend_from_slice(&varint::encode(type_id).expect("type id in range"));
    out
}

/// Read the typed marker. Returns `(type_id, offset_after_marker)`.
pub fn read_type_marker(body: &[u8]) -> Result<(u64, usize), BundleError> {
    if body.len() < 3 || body[..2] != TYPE_MARKER {
        let got = if body.len() >= 2 {
            format!("{:02x}{:02x}", body[0], body[1])
        } else {
            body.iter().map(|b| format!("{b:02x}")).collect::<String>()
        };
        return Err(BundleError(format!(
            "missing typed marker (expected 0001, got {got})"
        )));
    }
    let (type_id, offset) = varint::decode(body, 2)?;
    Ok((type_id, offset))
}

/// True when `body` starts with a well-formed type-0x08 marker.
pub fn looks_like_state_bundle(body: &[u8]) -> bool {
    if body.len() < 3 || body[..2] != TYPE_MARKER {
        return false;
    }
    matches!(varint::decode(body, 2), Ok((STATE_BUNDLE_TYPE, _)))
}

/// Parse a full state bundle body, marker included.
///
/// `strict` requires the payload length to reach the end of the body exactly. Unlike the
/// old opaque-payload model, that check is meaningful now: the payload is a record
/// sequence with its own internal structure, so a mismatch is a real signal.
pub fn decode_bundle(body: &[u8], strict: bool) -> Result<BundleBody, BundleError> {
    let (type_id, _) = read_type_marker(body)?;
    if type_id != STATE_BUNDLE_TYPE {
        return Err(BundleError(format!("not a state bundle: type 0x{type_id:x}")));
    }
    if body.len() <= SEQ_OFFSET {
        return Err(BundleError(
            "state bundle truncated inside the prologue".to_string(),
        ));
    }
    let (seq, after_seq) = varint::decode(body, SEQ_OFFSET)?;
    let tail_end = after_seq + PROLOGUE_TAIL.len();
    if tail_end > body.len() || body[after_seq..tail_end] != PROLOGUE_TAIL {
        let got: String = body[after_seq..tail_end.min(body.len())]
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        let want: String = PROLOGUE_TAIL.iter().map(|b| format!("{b:02x}")).collect();
        return Err(BundleError(format!(
            "prologue tail mismatch (expected {want}, got {got})"
        )));
    }
    let (length, after_len) = varint::decode(body, tail_end)?;
    let payload = body[after_len..].to_vec();
    if strict && payload.len() as u64 != length {
        return Err(BundleError(format!(
            "payload length says {length} but {} bytes remain",
            payload.len()
        )));
    }
    Ok(BundleBody {
        replication_seq: seq,
        payload,
    })
}

/// Return `body` with its replication counter set to `seq`.
///
/// The counter is a varint, so raising it past the client's high-water can widen it
/// (53 → 0x80 needs two bytes). This re-encodes rather than overwriting a byte, so the
/// prologue and payload stay aligned whatever width the new value needs.
pub fn with_replication_seq(body: &[u8], seq: u64) -> Result<Vec<u8>, BundleError> {
    let parsed = decode_bundle(body, true)?;
    Ok(encode_bundle(seq, &parsed.payload))
}

/// Wrap an already-built record payload into a type-0x08 body.
///
/// The inverse of `decode_bundle`, and the right tool when a caller has patched bytes
/// inside a payload WITHOUT changing its length.
pub fn encode_bundle(replication_seq: u64, payload: &[u8]) -> Vec<u8> {
    let mut out = encode_type_marker(STATE_BUNDLE_TYPE);
    out.push(PROLOGUE_HEAD);
    out.extend_from_slice(&varint::encode(replication_seq).expect("seq in range"));
    out.extend_from_slice(&PROLOGUE_TAIL);
    out.extend_from_slice(&varint::encode(payload.len() as u64).expect("len in range"));
    out.extend_from_slice(payload);
    out
}

/// One `[varint key][varint type_index][payload]` fragment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Fragment {
    pub key: u64,
    pub type_index: u64,
    pub payload: Vec<u8>,
}

impl Fragment {
    /// Decode one fragment sliced by a known boundary.
    pub fn parse(bytes: &[u8]) -> Result<Fragment, BundleError> {
        let (key, after_key) = varint::decode(bytes, 0)?;
        let (type_index, after_type) = varint::decode(bytes, after_key)?;
        Ok(Fragment {
            key,
            type_index,
            payload: bytes[after_type..].to_vec(),
        })
    }

    pub fn encode(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(self.payload.len() + 8);
        out.extend_from_slice(&varint::encode(self.key).expect("key in range"));
        out.extend_from_slice(&varint::encode(self.type_index).expect("type in range"));
        out.extend_from_slice(&self.payload);
        out
    }

    /// The two varints' encoded size.
    pub fn header_size(&self) -> usize {
        varint::encode(self.key).expect("key").len()
            + varint::encode(self.type_index).expect("type").len()
    }
}

/// One `[u8 record_id][u8 fragment_count][fragments…]` record.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Record {
    pub record_id: u8,
    pub fragments: Vec<Fragment>,
}

impl Record {
    pub fn encode(&self) -> Result<Vec<u8>, BundleError> {
        if self.fragments.len() > 0xFF {
            return Err(BundleError(format!(
                "{} fragments outside a byte",
                self.fragments.len()
            )));
        }
        let mut out = vec![self.record_id, self.fragments.len() as u8];
        for fragment in &self.fragments {
            out.extend_from_slice(&fragment.encode());
        }
        Ok(out)
    }
}

/// Build a type-0x08 body from records the SERVER owns.
///
/// This is the difference between forwarding a captured bundle and sending one we
/// composed: the caller supplies the replication counter, the record ids, and every
/// fragment's key, type and payload. Verified as such — composing the captured
/// local-player record from its fragments reproduces the captured body byte for byte.
pub fn compose_bundle(replication_seq: u64, records: &[Record]) -> Result<Vec<u8>, BundleError> {
    let mut payload = Vec::new();
    for record in records {
        payload.extend_from_slice(&record.encode()?);
    }
    Ok(encode_bundle(replication_seq, &payload))
}

/// Slice one record's payload into fragments using KNOWN boundaries.
///
/// The boundaries cannot be recomputed from the bytes alone — a fragment carries no
/// length and its payload length is implied by its type — so they come from the client
/// (`tests/fixtures/state-bundles.txt`) or from a caller that knows the layout.
///
/// `boundaries` are offsets into `payload`, in order, where each fragment STARTS; the
/// last fragment runs to the end. They are normally relative to the record, so the first
/// one is the record header's size (2: one byte of record id plus one of fragment count)
/// and the bytes before it are that header, not a fragment. A first boundary of 0 is
/// also accepted, for a caller that passes the fragment region alone.
pub fn split_record_payload(
    payload: &[u8],
    boundaries: &[usize],
) -> Result<Vec<Vec<u8>>, BundleError> {
    if boundaries.is_empty() {
        return Err(BundleError("no boundaries given".to_string()));
    }
    if boundaries.windows(2).any(|w| w[0] >= w[1]) {
        return Err(BundleError(
            "boundaries must be strictly ascending".to_string(),
        ));
    }
    if boundaries[boundaries.len() - 1] >= payload.len() {
        return Err(BundleError(format!(
            "last boundary {} is past the payload ({} bytes)",
            boundaries[boundaries.len() - 1],
            payload.len()
        )));
    }
    let mut out = Vec::with_capacity(boundaries.len());
    for (i, start) in boundaries.iter().enumerate() {
        let end = if i + 1 < boundaries.len() {
            boundaries[i + 1]
        } else {
            payload.len()
        };
        out.push(payload[*start..end].to_vec());
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn synthetic_body() -> Vec<u8> {
        encode_bundle(0x25, &[0x01, 0x01, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    }

    #[test]
    fn encode_is_the_inverse_of_decode() {
        let body = synthetic_body();
        let parsed = decode_bundle(&body, true).expect("decode");
        assert_eq!(parsed.replication_seq, 0x25);
        assert_eq!(encode_bundle(parsed.replication_seq, &parsed.payload), body);
    }

    #[test]
    fn the_prologue_tail_is_a_layout_check() {
        let mut body = synthetic_body();
        // Flip one invariant byte.
        body[6] = 0x02;
        assert!(decode_bundle(&body, true).is_err());
    }

    #[test]
    fn a_widening_counter_re_encodes_instead_of_shifting_the_body() {
        let body = synthetic_body();
        let wide = with_replication_seq(&body, 0x1234).expect("rewrite");
        let parsed = decode_bundle(&wide, true).expect("decode");
        assert_eq!(parsed.replication_seq, 0x1234);
        assert_eq!(parsed.payload, decode_bundle(&body, true).unwrap().payload);
        assert_eq!(wide.len(), body.len() + 1);
    }

    #[test]
    fn compose_reproduces_a_record_from_its_fragments() {
        let fragments = vec![
            Fragment {
                key: 16,
                type_index: 11,
                payload: vec![1, 2, 3],
            },
            Fragment {
                key: 22,
                type_index: 3857,
                payload: vec![9; 5],
            },
        ];
        let record = Record {
            record_id: 1,
            fragments: fragments.clone(),
        };
        let composed = compose_bundle(7, &[record]).expect("compose");
        let parsed = decode_bundle(&composed, true).expect("decode");
        assert_eq!(parsed.replication_seq, 7);
        // payload = [01 02] + fragment0 + fragment1
        let split = split_record_payload(&parsed.payload, &[2, 2 + fragments[0].encode().len()])
            .expect("split");
        assert_eq!(Fragment::parse(&split[0]).unwrap(), fragments[0]);
        assert_eq!(Fragment::parse(&split[1]).unwrap(), fragments[1]);
    }

    #[test]
    fn split_rejects_bad_boundaries() {
        let payload = vec![0u8; 10];
        assert!(split_record_payload(&payload, &[]).is_err());
        assert!(split_record_payload(&payload, &[5, 5]).is_err());
        assert!(split_record_payload(&payload, &[20]).is_err());
    }
}
