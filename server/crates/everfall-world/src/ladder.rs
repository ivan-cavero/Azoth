//! The post-registration ladder: the rungs the server SENDS after `0x3`.
//!
//! Once the client accepts the registration response it needs, in order, the
//! self-identification record (`0x65c`), level info (`0x663`) and the
//! replicated-state bundle (`0x08`). This module turns those three rungs into
//! the ordered Carrier datagrams a transport sends, at the pacing the reference
//! uses (`services/world/src/azoth_world/rep.py::maybe_send_post_v3` and
//! `::maybe_pump_replay`).
//!
//! Every rung is assembled from an Atlas card, never a bare byte vector:
//!
//! * the self-identification and level-info bodies come from
//!   [`FlowWorldEntryRungSelfIdentification`] and [`FlowWorldEntryRungLevelInfo`],
//!   re-encoded by their generated codecs; and
//! * the state rung is the [`Emission`] the emitter authors from typed
//!   components.
//!
//! ## Provenance of the values
//!
//! The BYTES here are the server's: the codecs frame them, the emitter authors
//! its fragments, and no emitted fragment is a replayed run. The VALUES are
//! still the capture's: `from_captured` decodes a captured body into a card and
//! re-encodes it, and the emitter's input bundle is a captured one, because the
//! simulation does not own these values yet. That distinction is the honest state
//! of this rung and is why the constructor is named `from_captured`.

use core::fmt;

use everfall_sim::Decision;
use everfall_wire::generated::{FlowWorldEntryRungLevelInfo, FlowWorldEntryRungSelfIdentification};
use everfall_wire::{
    Bundle, BundleError, CarrierError, Compression, Datagram, Envelope, FragmentExtent,
    LocalPlayerState, MF_CHUNKS, MF_DATA_CHANNEL, MF_RELIABLE, MessageRecord, WireError, Writer,
    chunk_ranges, typed_record,
};

use crate::emitter::{Emission, EmitError, emit};

/// The reference's quiet period after the V3 answer before the post-V3 flight
/// (`POST_V3_ENABLED` path: `time.monotonic() - v3_first_time > 0.3`). Sending
/// the flight in the same burst as the registration crashes the client.
pub const POST_V3_DELAY_MS: u32 = 300;

/// The reference's spacing between two rungs (`REPLAY_INTERVAL_S` = 0.03 s).
pub const MESSAGE_INTERVAL_MS: u32 = 30;

/// The reference's spacing between two chunks of one message
/// (`REPLAY_CHUNK_GAP_MS` = 4 ms): the client's Carrier queue truncates a burst.
pub const CHUNK_GAP_MS: u32 = 4;

/// The largest record payload the reference sends as one record before it
/// chunks (`REPLAY_SINGLE_LIMIT` = 256): an oversized single record is
/// acknowledged and then never delivered upward.
pub const SINGLE_RECORD_LIMIT: usize = 256;

/// The flag byte of a reliable single-record datagram: `MF_RELIABLE | MF_DATA_CHANNEL`.
const RELIABLE_DATA_CHANNEL: u8 = MF_RELIABLE | MF_DATA_CHANNEL;

/// The flag byte of a reliable chunked datagram, the reference's `0x25`.
const RELIABLE_CHUNKS_DATA_CHANNEL: u8 = MF_RELIABLE | MF_CHUNKS | MF_DATA_CHANNEL;

/// Which rung of the post-registration ladder a planned record belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Rung {
    /// `PlayerManagerSelfIdentificationMsg`, wire `0x65c`.
    SelfIdentification,
    /// `LevelInfoChangedMsg`, wire `0x663`.
    LevelInfo,
    /// The type-`0x08` replicated-state bundle the emitter authors.
    State,
}

/// One chunk of a chunked rung: its index and the record's declared count.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Chunk {
    index: usize,
    count: usize,
}

impl Chunk {
    /// The zero-based index of this chunk.
    #[must_use]
    pub const fn index(self) -> usize {
        self.index
    }

    /// How many chunks the record declares in total.
    #[must_use]
    pub const fn count(self) -> usize {
        self.count
    }
}

/// One Carrier record the ladder plans to send: a rung, when it is due, the
/// record payload, and its chunk position when it is chunked.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlannedRecord {
    rung: Rung,
    offset_ms: u32,
    payload: Vec<u8>,
    chunk: Option<Chunk>,
}

impl PlannedRecord {
    /// The rung this record belongs to.
    #[must_use]
    pub const fn rung(&self) -> Rung {
        self.rung
    }

    /// Milliseconds after the V3 answer this record becomes due.
    #[must_use]
    pub const fn offset_ms(&self) -> u32 {
        self.offset_ms
    }

    /// The Carrier record payload.
    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    /// The chunk position, or `None` for a single-record rung.
    #[must_use]
    pub const fn chunk(&self) -> Option<Chunk> {
        self.chunk
    }
}

/// The ordered post-registration rungs, paced from the V3 answer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PostV3Ladder {
    plan: Vec<PlannedRecord>,
}

impl PostV3Ladder {
    /// Build the ladder from the captured corpus bodies, through the cards.
    ///
    /// The two message bodies are the committed corpus records; they are decoded
    /// into their generated cards and re-encoded, so the emitted bytes are the
    /// server's framing, not a copied record. The state bundle is decoded and
    /// re-emitted by [`emit`], so a body byte is a typed component, not a replay.
    ///
    /// # Errors
    /// Returns [`LadderError`] when a captured body does not match its card, when
    /// the bundle's extents do not agree with it, or when the emitter refuses the
    /// decision.
    pub fn from_captured(
        self_identification_body: &[u8],
        level_info_body: &[u8],
        state_bundle_body: &[u8],
        state_extents: &[(u64, u64, usize)],
        decision: &Decision,
    ) -> Result<Self, LadderError> {
        let self_identification =
            FlowWorldEntryRungSelfIdentification::decode(self_identification_body)?;
        let level_info = FlowWorldEntryRungLevelInfo::decode(level_info_body)?;
        let extents: Vec<FragmentExtent> = state_extents
            .iter()
            .map(|&(key, type_index, payload_len)| FragmentExtent {
                key,
                type_index,
                payload_len,
            })
            .collect();
        let bundle = Bundle::<LocalPlayerState>::decode(state_bundle_body, &extents)?;
        let emission = emit(bundle, decision)?;
        Self::from_emission(&self_identification, &level_info, &emission)
    }

    /// Build the ladder from already-decoded card values and an emission.
    ///
    /// # Errors
    /// Returns [`LadderError`] when a card refuses to encode.
    pub fn from_emission(
        self_identification: &FlowWorldEntryRungSelfIdentification,
        level_info: &FlowWorldEntryRungLevelInfo,
        state: &Emission,
    ) -> Result<Self, LadderError> {
        let mut body = Vec::new();
        self_identification.encode(&mut body)?;
        let self_ident = typed_record(FlowWorldEntryRungSelfIdentification::WIRE_ID, &body)?;

        let mut body = Vec::new();
        level_info.encode(&mut body)?;
        let level_info_payload = typed_record(FlowWorldEntryRungLevelInfo::WIRE_ID, &body)?;

        let inner = state.encode()?;
        let mut state_payload = Vec::new();
        Writer::new(&mut state_payload).vlq32(inner.len() as u64)?;
        state_payload.extend_from_slice(&inner);

        Ok(Self {
            plan: plan_rungs([
                (Rung::SelfIdentification, self_ident),
                (Rung::LevelInfo, level_info_payload),
                (Rung::State, state_payload),
            ]),
        })
    }

    /// The planned records, in send order.
    #[must_use]
    pub fn records(&self) -> &[PlannedRecord] {
        &self.plan
    }

    /// One rung's whole record payload, its chunks rejoined.
    #[must_use]
    pub fn rung_payload(&self, rung: Rung) -> Vec<u8> {
        self.plan
            .iter()
            .filter(|record| record.rung == rung)
            .flat_map(|record| record.payload.iter().copied())
            .collect()
    }

    /// Build one planned datagram with the caller's Carrier counters.
    ///
    /// # Errors
    /// Returns [`LadderError::NoSuchRecord`] when `index` is past the plan, and
    /// [`LadderError`] when the record cannot be framed.
    pub fn datagram(
        &self,
        index: usize,
        envelope_seq: u16,
        message_seq: u16,
        reliable_seq: u16,
    ) -> Result<Vec<u8>, LadderError> {
        let record = self
            .plan
            .get(index)
            .ok_or(LadderError::NoSuchRecord { index })?;
        build_datagram(record, envelope_seq, message_seq, reliable_seq)
    }
}

/// Frame one planned record as a plaintext Carrier datagram.
///
/// # Errors
/// Returns [`LadderError`] when the chunk count does not fit a `u16` or the
/// Carrier framing refuses a value.
pub fn build_datagram(
    record: &PlannedRecord,
    envelope_seq: u16,
    message_seq: u16,
    reliable_seq: u16,
) -> Result<Vec<u8>, LadderError> {
    let mut carrier = MessageRecord::new(0, record.payload.clone())
        .with_reliable()
        .with_sequence(message_seq)
        .with_reliable_sequence(reliable_seq);
    let flags = match record.chunk {
        None => RELIABLE_DATA_CHANNEL,
        Some(chunk) => {
            let count = u16::try_from(chunk.count)
                .map_err(|_| LadderError::ChunkCount { count: chunk.count })?;
            carrier = carrier.with_num_chunks(count);
            RELIABLE_CHUNKS_DATA_CHANNEL
        }
    };
    carrier = carrier.with_flags_override(flags);
    let datagram = Datagram::new(
        Envelope::new(envelope_seq, Compression::Plaintext),
        vec![carrier],
    );
    Ok(datagram.encode()?)
}

/// Cut each rung into its planned records, paced from the V3 answer.
fn plan_rungs(rungs: [(Rung, Vec<u8>); 3]) -> Vec<PlannedRecord> {
    let mut plan = Vec::new();
    let mut at = POST_V3_DELAY_MS;
    for (rung, payload) in rungs {
        if payload.len() <= SINGLE_RECORD_LIMIT {
            plan.push(PlannedRecord {
                rung,
                offset_ms: at,
                payload,
                chunk: None,
            });
        } else {
            let ranges = chunk_ranges(payload.len());
            let count = ranges.len();
            for (index, range) in ranges.into_iter().enumerate() {
                plan.push(PlannedRecord {
                    rung,
                    offset_ms: at,
                    payload: payload[range].to_vec(),
                    chunk: Some(Chunk { index, count }),
                });
                if index + 1 < count {
                    at = at.saturating_add(CHUNK_GAP_MS);
                }
            }
        }
        at = at.saturating_add(MESSAGE_INTERVAL_MS);
    }
    plan
}

/// Why a post-registration rung could not be assembled or framed.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum LadderError {
    /// A captured body did not match its Atlas card.
    Card(WireError),
    /// The state bundle's framing refused a value.
    Bundle(BundleError),
    /// The emitter refused the decision.
    Emission(EmitError),
    /// A reply's Carrier framing refused a value.
    Carrier(CarrierError),
    /// A chunked record declares more chunks than a `u16` holds.
    ChunkCount {
        /// The declared chunk count.
        count: usize,
    },
    /// A planned record was requested past the end of the plan.
    NoSuchRecord {
        /// The index that was requested.
        index: usize,
    },
}

impl From<WireError> for LadderError {
    fn from(source: WireError) -> Self {
        Self::Card(source)
    }
}

impl From<BundleError> for LadderError {
    fn from(source: BundleError) -> Self {
        Self::Bundle(source)
    }
}

impl From<EmitError> for LadderError {
    fn from(source: EmitError) -> Self {
        Self::Emission(source)
    }
}

impl From<CarrierError> for LadderError {
    fn from(source: CarrierError) -> Self {
        Self::Carrier(source)
    }
}

impl fmt::Display for LadderError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Card(source) => write!(f, "ladder card body: {source}"),
            Self::Bundle(source) => write!(f, "ladder state bundle: {source}"),
            Self::Emission(source) => write!(f, "ladder emission: {source}"),
            Self::Carrier(source) => write!(f, "ladder framing: {source}"),
            Self::ChunkCount { count } => {
                write!(f, "a chunked record declares {count} chunks, over a u16")
            }
            Self::NoSuchRecord { index } => write!(f, "no planned record at index {index}"),
        }
    }
}

impl std::error::Error for LadderError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Card(source) => Some(source),
            Self::Bundle(source) => Some(source),
            Self::Emission(source) => Some(source),
            Self::Carrier(source) => Some(source),
            _ => None,
        }
    }
}
