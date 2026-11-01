//! Generic framing for the type-0x08 replicated-state bundle.
//!
//! A bundle body is `00 01 08`, an eight-byte prologue (`0x01`, the prefix-varint
//! replication counter, then six bytes that never vary), the prefix-varint
//! payload length, and the payload. The payload is a sequence of records, each
//! `[u8 record_id][u8 fragment_count][fragment*]`, and a fragment is
//! `[varint key][varint type_index][payload]` with NO length field.
//!
//! Because a fragment has no length, where one ends is not derivable from the
//! bytes: the width is implied by the type's own reader. The extent is therefore
//! stated once ([`FragmentExtent`], from the client's own measured walk) and
//! checked here against what the bytes and the codec actually consume, so a wrong
//! extent fails loudly instead of re-emitting its own guess.
//!
//! This module names no card. It asks [`StateComponent`] for the type index and
//! the body, so the assembly below is generic over every replicated component,
//! and a fragment whose type has no recovered payload layout stays an [`Opaque`]
//! run that keeps the field id it was read from.

use core::fmt;
use core::ops::Range;

use crate::framing::{RECORD_TYPE_MARKER, Reader, WireError, Writer};
use crate::opaque::Opaque;

/// The message type of a replicated-state bundle.
pub const STATE_BUNDLE_TYPE: u64 = 0x08;

/// The byte that opens the prologue, before the replication counter.
pub const PROLOGUE_HEAD: u8 = 0x01;

/// The six bytes that follow the replication counter in every observed body.
pub const PROLOGUE_TAIL: [u8; 6] = [0x01, 0x01, 0x01, 0x01, 0x00, 0x00];

/// Largest bundle byte count the transport delivers in one chunk.
///
/// A record far smaller than this was acknowledged and never delivered when sent
/// as one datagram, so this is the cut the working transport uses: one chunk per
/// 50 Hz tick.
pub const CHUNK_LIMIT: usize = 1100;

/// Largest datagram the transport accepts.
pub const DATAGRAM_CEILING: usize = 1200;

/// Bytes a datagram spends on everything that is not the chunk.
///
/// The cut exists because the ceiling does: a chunk of [`CHUNK_LIMIT`] bytes
/// leaves this much for the carrier layer that has to wrap it.
pub const CARRIER_HEADROOM: usize = DATAGRAM_CEILING - CHUNK_LIMIT;

/// Field id for a fragment run whose type payload has no Atlas card.
///
/// Not a card id. The bundle envelope is framing, not a card, and the Atlas has
/// no card for a state type whose payload layout is unrecovered, so the run is
/// tagged with the field it belongs to rather than pretending to be a card.
pub const UNRECOVERED_FRAGMENT_PAYLOAD: &str = "envelope.state-bundle.fragment.payload";

/// Cut an encoded bundle into the pieces the transport can carry.
///
/// Returns offsets, not bytes: how a chunk is labelled, ordered and wrapped is
/// the carrier layer, and that layer does not exist yet.
#[must_use]
pub fn chunk_ranges(total: usize) -> Vec<Range<usize>> {
    let mut out = Vec::new();
    let mut start = 0;
    while start < total {
        let end = start.saturating_add(CHUNK_LIMIT).min(total);
        out.push(start..end);
        start = end;
    }
    out
}

/// One replicated-state component whose payload layout the Atlas names.
///
/// The generated codec for a card supplies one impl. The framing never names a
/// card: it asks the trait for the type index and the body.
pub trait StateComponent: Sized + fmt::Debug + PartialEq {
    /// The Atlas card id of the component.
    const UID: &'static str;

    /// The state type index the client binds the card to.
    ///
    /// A fragment's second varint is this index, and the client maps it through
    /// its type registry to the card's own reader and writer.
    const TYPE_INDEX: u64;

    /// Read one body. The fragment carries no length, so the card's layout
    /// decides where the body ends.
    ///
    /// # Errors
    /// Returns [`WireError`] when the body does not match the card.
    fn read_body(reader: &mut Reader<'_>) -> Result<Self, WireError>;

    /// Append one body.
    ///
    /// # Errors
    /// Returns [`WireError`] when a value exceeds a width the card states.
    fn write_body(&self, writer: &mut Writer<'_>) -> Result<(), WireError>;
}

/// One fragment's measured extent inside a record.
///
/// A fragment is `[varint key][varint type_index][payload]` with no length field,
/// so its width cannot be recovered from the bytes. The extent comes from the
/// client's measured walk of the record reader; the framing checks it against
/// what the fragment header and the codec actually consume.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FragmentExtent {
    /// The fragment key (the component slot).
    pub key: u64,
    /// The state type index bound to the key.
    pub type_index: u64,
    /// Bytes the payload occupies.
    pub payload_len: usize,
}

/// One fragment of a record: a component slot, a type index and a body.
#[derive(Debug, Clone, PartialEq)]
pub struct Fragment<T> {
    key: u64,
    payload: FragmentPayload<T>,
}

/// What a fragment carries.
#[derive(Debug, Clone, PartialEq)]
pub enum FragmentPayload<T> {
    /// A component the Atlas names, so its card owns the body.
    Component(T),
    /// A component whose type payload layout is not recovered: the bytes stay a
    /// tagged run and the type index is all that is known about them.
    Unrecovered {
        /// The state type index bound to the fragment key.
        type_index: u64,
        /// The payload bytes, tagged with the field they came from.
        run: Opaque,
    },
}

impl<T: StateComponent> FragmentPayload<T> {
    /// The state type index this payload is bound to.
    pub fn type_index(&self) -> u64 {
        match self {
            Self::Component(_) => T::TYPE_INDEX,
            Self::Unrecovered { type_index, .. } => *type_index,
        }
    }
}

impl<T> Fragment<T> {
    /// The fragment key (the component slot).
    pub const fn key(&self) -> u64 {
        self.key
    }

    /// What this fragment carries.
    pub const fn payload(&self) -> &FragmentPayload<T> {
        &self.payload
    }
}

/// One record of a bundle: `[u8 record_id][u8 fragment_count][fragment*]`.
#[derive(Debug, Clone, PartialEq)]
pub struct Record<T> {
    record_id: u64,
    fragments: Vec<Fragment<T>>,
}

impl<T> Record<T> {
    /// The record id, which selects the client's state slot for it.
    pub const fn record_id(&self) -> u64 {
        self.record_id
    }

    /// The fragments, in the order the record carries them.
    pub fn fragments(&self) -> &[Fragment<T>] {
        &self.fragments
    }
}

/// A type-0x08 replicated-state bundle.
///
/// The prologue and the payload length are framing, never a field: a caller sees
/// the replication counter and the records, and the framing writes the rest.
#[derive(Debug, Clone, PartialEq)]
pub struct Bundle<T> {
    replication_seq: u64,
    records: Vec<Record<T>>,
}

impl<T: StateComponent> Bundle<T> {
    /// Read one bundle body, marker included.
    ///
    /// `extents` are the measured widths of every fragment in the body. A
    /// fragment whose key is absent from them cannot be walked, because nothing
    /// in the bytes says where it ends.
    ///
    /// # Errors
    /// Returns [`BundleError`] when the body is not a bundle, when a byte the
    /// layout pins has moved, when an extent disagrees with the bytes, or when a
    /// card's codec consumes a different width than its extent states.
    pub fn decode(body: &[u8], extents: &[FragmentExtent]) -> Result<Self, BundleError> {
        let mut reader = Reader::new(body);

        let marker = reader.take("record_marker", RECORD_TYPE_MARKER.len())?;
        if marker != &RECORD_TYPE_MARKER[..] {
            let mut found = [0_u8; 2];
            found.copy_from_slice(marker);
            return Err(BundleError::MarkerMoved { found });
        }

        let wire_type = reader.prefix_varint("wire_type")?;
        if wire_type != STATE_BUNDLE_TYPE {
            return Err(BundleError::NotAStateBundle { wire_type });
        }

        let head = reader.u8("prologue_head")?;
        if head != PROLOGUE_HEAD {
            return Err(BundleError::PrologueMoved {
                field: "prologue_head",
                expected: PROLOGUE_HEAD,
                found: head,
            });
        }

        let replication_seq = reader.prefix_varint("replication_seq")?;

        let tail = reader.take("prologue_tail", PROLOGUE_TAIL.len())?;
        if let Some(index) = tail
            .iter()
            .zip(PROLOGUE_TAIL.iter())
            .position(|(found, expected)| found != expected)
        {
            return Err(BundleError::PrologueMoved {
                field: "prologue_tail",
                expected: PROLOGUE_TAIL[index],
                found: tail[index],
            });
        }

        // The declared length must reach the end of the body exactly: the record
        // is the whole body, so a short or long payload is a moved layout, not a
        // tolerated tail.
        let declared = reader.prefix_varint("payload_length")?;
        let available = reader.remaining();
        if declared != available as u64 {
            return Err(BundleError::PayloadLength {
                declared,
                available,
            });
        }
        let payload = reader.take("payload", available)?;

        let mut inner = Reader::new(payload);
        let mut records = Vec::new();
        while !inner.is_empty() {
            let record_id = u64::from(inner.u8("record_id")?);
            let fragment_count = usize::from(inner.u8("fragment_count")?);
            let mut fragments = Vec::with_capacity(fragment_count);
            for _ in 0..fragment_count {
                fragments.push(read_fragment(&mut inner, extents)?);
            }
            records.push(Record {
                record_id,
                fragments,
            });
        }

        Ok(Self {
            replication_seq,
            records,
        })
    }

    /// Write the whole body, marker and prologue included.
    ///
    /// # Errors
    /// Returns [`BundleError`] when a record id or fragment count does not fit
    /// its one byte, or when a card's codec refuses a value.
    pub fn encode(&self) -> Result<Vec<u8>, BundleError> {
        let payload = self.encode_payload()?;

        let mut out = Vec::new();
        out.extend_from_slice(&RECORD_TYPE_MARKER);
        let mut writer = Writer::new(&mut out);
        writer.prefix_varint(STATE_BUNDLE_TYPE)?;
        writer.u8(PROLOGUE_HEAD);
        writer.prefix_varint(self.replication_seq)?;
        writer.raw(&PROLOGUE_TAIL);
        writer.prefix_varint(payload.len() as u64)?;
        out.extend_from_slice(&payload);
        Ok(out)
    }

    fn encode_payload(&self) -> Result<Vec<u8>, BundleError> {
        let mut out = Vec::new();
        for record in &self.records {
            if record.record_id > u64::from(u8::MAX) {
                return Err(BundleError::HeaderOutOfRange {
                    field: "record_id",
                    value: record.record_id,
                    max: u64::from(u8::MAX),
                });
            }
            if record.fragments.len() > usize::from(u8::MAX) {
                return Err(BundleError::HeaderOutOfRange {
                    field: "fragment_count",
                    value: record.fragments.len() as u64,
                    max: u64::from(u8::MAX),
                });
            }
            out.push(record.record_id as u8);
            out.push(record.fragments.len() as u8);
            for fragment in &record.fragments {
                fragment.encode(&mut out)?;
            }
        }
        Ok(out)
    }

    /// The replication counter the client's unreliable-replication gate reads.
    pub const fn replication_seq(&self) -> u64 {
        self.replication_seq
    }

    /// The same bundle with a different replication counter.
    ///
    /// The counter is a prefix varint, so raising it past a width boundary widens
    /// it and every following byte moves. Re-encoding is the only correct way to
    /// change it; writing the byte in place is what produced the measured
    /// `ValidationError` on the client.
    #[must_use]
    pub fn with_replication_seq(mut self, replication_seq: u64) -> Self {
        self.replication_seq = replication_seq;
        self
    }

    /// The records, in wire order.
    pub fn records(&self) -> &[Record<T>] {
        &self.records
    }

    /// Every typed component the bundle carries, in wire order.
    pub fn components(&self) -> impl Iterator<Item = &T> + '_ {
        self.records
            .iter()
            .flat_map(|record| record.fragments.iter())
            .filter_map(|fragment| match &fragment.payload {
                FragmentPayload::Component(component) => Some(component),
                FragmentPayload::Unrecovered { .. } => None,
            })
    }

    /// Every typed component, mutably, in wire order.
    pub fn components_mut(&mut self) -> impl Iterator<Item = &mut T> + '_ {
        self.records
            .iter_mut()
            .flat_map(|record| record.fragments.iter_mut())
            .filter_map(|fragment| match &mut fragment.payload {
                FragmentPayload::Component(component) => Some(component),
                FragmentPayload::Unrecovered { .. } => None,
            })
    }
}

impl<T: StateComponent> Fragment<T> {
    fn encode(&self, out: &mut Vec<u8>) -> Result<(), BundleError> {
        let mut writer = Writer::new(out);
        writer.prefix_varint(self.key)?;
        writer.prefix_varint(self.payload.type_index())?;
        match &self.payload {
            FragmentPayload::Component(component) => component.write_body(&mut writer)?,
            FragmentPayload::Unrecovered { run, .. } => writer.raw(run.as_slice()),
        }
        Ok(())
    }
}

fn read_fragment<T: StateComponent>(
    reader: &mut Reader<'_>,
    extents: &[FragmentExtent],
) -> Result<Fragment<T>, BundleError> {
    let key = reader.prefix_varint("fragment_key")?;
    let type_index = reader.prefix_varint("fragment_type_index")?;
    let extent = extents
        .iter()
        .find(|extent| extent.key == key)
        .ok_or(BundleError::NoExtent { key })?;
    if extent.type_index != type_index {
        return Err(BundleError::ExtentMismatch {
            key,
            field: "type_index",
            expected: extent.type_index,
            found: type_index,
        });
    }

    let payload = if type_index == T::TYPE_INDEX {
        let before = reader.position();
        let component = T::read_body(reader)?;
        let consumed = reader.position() - before;
        if consumed != extent.payload_len {
            return Err(BundleError::ComponentWidth {
                key,
                expected: extent.payload_len,
                consumed,
            });
        }
        FragmentPayload::Component(component)
    } else {
        let run = reader.take("fragment_payload", extent.payload_len)?;
        FragmentPayload::Unrecovered {
            type_index,
            run: Opaque::new(UNRECOVERED_FRAGMENT_PAYLOAD, run.to_vec()),
        }
    };

    Ok(Fragment { key, payload })
}

/// A bundle body that does not match the documented framing.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum BundleError {
    /// The two-byte type marker is not [`RECORD_TYPE_MARKER`].
    MarkerMoved {
        /// The bytes found where the marker belongs.
        found: [u8; 2],
    },
    /// The message type is not [`STATE_BUNDLE_TYPE`].
    NotAStateBundle {
        /// The message type that arrived.
        wire_type: u64,
    },
    /// A prologue byte the layout pins to one value carried another.
    PrologueMoved {
        /// The field that moved.
        field: &'static str,
        /// The byte every observed body carries.
        expected: u8,
        /// The byte found.
        found: u8,
    },
    /// A one-byte record header field does not fit in its byte.
    HeaderOutOfRange {
        /// The field being written.
        field: &'static str,
        /// The value offered.
        value: u64,
        /// The largest value the header byte holds.
        max: u64,
    },
    /// A fragment key has no measured extent.
    NoExtent {
        /// The key that was not measured.
        key: u64,
    },
    /// A measured extent disagrees with the fragment's own header.
    ExtentMismatch {
        /// The fragment key.
        key: u64,
        /// The field that disagrees.
        field: &'static str,
        /// The value the extent states.
        expected: u64,
        /// The value the bytes carry.
        found: u64,
    },
    /// A card's codec and the measured extent disagree on the payload width.
    ComponentWidth {
        /// The fragment key.
        key: u64,
        /// The width the extent states.
        expected: usize,
        /// The width the codec consumed.
        consumed: usize,
    },
    /// The payload length field does not reach the end of the body.
    PayloadLength {
        /// The length the prologue declares.
        declared: u64,
        /// The bytes actually left in the body.
        available: usize,
    },
    /// The body's own bytes are malformed.
    Wire(WireError),
}

impl From<WireError> for BundleError {
    fn from(source: WireError) -> Self {
        Self::Wire(source)
    }
}

impl fmt::Display for BundleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MarkerMoved { found } => {
                let expected = RECORD_TYPE_MARKER;
                write!(f, "type marker is {found:02x?}, not {expected:02x?}")
            }
            Self::NotAStateBundle { wire_type } => {
                write!(f, "wire type {wire_type} is not {STATE_BUNDLE_TYPE}")
            }
            Self::PrologueMoved {
                field,
                expected,
                found,
            } => write!(f, "{field} is {found:#04x}, not {expected:#04x}"),
            Self::HeaderOutOfRange { field, value, max } => {
                write!(f, "{field} {value} does not fit one byte (max {max})")
            }
            Self::NoExtent { key } => write!(f, "fragment key {key} has no measured extent"),
            Self::ExtentMismatch {
                key,
                field,
                expected,
                found,
            } => write!(
                f,
                "fragment key {key} {field} is {found}, measured {expected}"
            ),
            Self::ComponentWidth {
                key,
                expected,
                consumed,
            } => write!(
                f,
                "fragment key {key} codec consumed {consumed} byte(s), extent states {expected}"
            ),
            Self::PayloadLength {
                declared,
                available,
            } => write!(
                f,
                "payload length field says {declared}, {available} byte(s) follow"
            ),
            Self::Wire(source) => write!(f, "body: {source}"),
        }
    }
}

impl std::error::Error for BundleError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Wire(source) => Some(source),
            _ => None,
        }
    }
}
