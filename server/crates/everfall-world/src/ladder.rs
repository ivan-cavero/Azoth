//! The post-registration ladder: the rungs the server SENDS after `0x3`.
//!
//! Once the client accepts the registration response it needs, in the order the
//! capture itself uses:
//!
//! 1. the heartbeat ping (`0x15d`), which the capture sends first (seq `0x02`) and
//!    then repeats about once a second for the rest of the session;
//! 2. `CalendarConnectedMsg` (`0x40a`, seq `0x04`) once;
//! 3. `CoatlicueTimingConfigurationConnectedMsg` (`0x1be`, seq `0x05`) once;
//! 4. the self-identification record (`0x65c`, seq `0x06`);
//! 5. level info (`0x663`); and
//! 6. the replicated-state bundle (`0x08`).
//!
//! This module turns those rungs into the ordered Carrier datagrams a transport
//! sends, at the pacing the reference uses
//! (`services/world/src/azoth_world/rep.py::maybe_send_post_v3`,
//! `::maybe_pump_replay` and `::maybe_heartbeat`).
//!
//! Every rung is assembled from an Atlas card, never a bare byte vector:
//!
//! * the ping, calendar-connected and coatlicue-timing bodies come from
//!   [`FlowWorldEntryRungPing`], [`FlowWorldEntryRungCalendarConnected`] and
//!   [`FlowWorldEntryRungCoatlicueTiming`];
//! * the self-identification and level-info bodies come from
//!   [`FlowWorldEntryRungSelfIdentification`] and [`FlowWorldEntryRungLevelInfo`],
//!   re-encoded by their generated codecs; and
//! * the state rung is the [`Emission`] the emitter authors from typed
//!   components.
//!
//! ## Why the ping repeats outside the plan
//!
//! The heartbeat is not one rung like the others: it is due before the first of
//! them and then again every [`HEARTBEAT_PERIOD_MS`], for as long as the
//! session lasts, which a finite plan cannot express. So the plan holds the
//! once-each rungs and [`PostV3Ladder::heartbeat`] holds the ping, which is due
//! [`HEARTBEAT_OFFSET_MS`] after the registration answer -- one
//! [`MESSAGE_INTERVAL_MS`] before the plan's first record, so the capture's
//! order (ping, calendar, coatlicue, self-ident) and its spacing both hold.
//!
//! The tick the ping carries is AUTHORED, not replayed: the card names the
//! measured 48-bit counter as `tick_high`/`tick_low`, so
//! [`Heartbeat::payload`] can continue the captured series one second
//! ([`HEARTBEAT_TICK_STEP`] nanoseconds) at a time. The client only echoes it.
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
use everfall_wire::generated::{
    FlowWorldEntryRungCalendarConnected, FlowWorldEntryRungCoatlicueTiming,
    FlowWorldEntryRungLevelInfo, FlowWorldEntryRungPing, FlowWorldEntryRungSelfIdentification,
};
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

/// When the heartbeat is due: the same quiet period, but before the plan, because
/// the capture's first post-registration record IS the `0x15d` ping (seq `0x02`).
pub const HEARTBEAT_OFFSET_MS: u32 = POST_V3_DELAY_MS;

/// The reference's heartbeat period (`HEARTBEAT_PERIOD_S` = 1.0 s).
pub const HEARTBEAT_PERIOD_MS: u32 = 1000;

/// How far the heartbeat's tick advances per period: one second in nanoseconds
/// (`HEARTBEAT_TICK_STEP`), which is what the captured bodies measure.
pub const HEARTBEAT_TICK_STEP: u64 = 1_000_000_000;

/// The tick is 6 bytes wide on the wire, so only its low 48 bits are carried.
const HEARTBEAT_TICK_MASK: u64 = 0xFFFF_FFFF_FFFF;

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

/// `ReceivePlayerSpawnPointMsg`, wire `0x651`.
///
/// A body-less signal, so there is no Atlas card to encode it through: the
/// record is `00 01` then the prefix varint of 1617, i.e. `00 01 91 19`. That
/// is exactly the four bytes `0x7_T0x651_R.bin` in the committed corpus holds,
/// and the name is the client's own - the registration hook resolves
/// `typeIndex[1617]` to `ReceivePlayerSpawnPointMsg@ClientViewListenerTrait@Javelin`.
/// It sits between the self-identification and the level info in the capture
/// (`research/atlas/meanings.md`, "The first typed exchange, measured").
const SPAWN_POINT_WIRE_ID: u32 = 0x651;

/// Which rung of the post-registration ladder a planned record belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Rung {
    /// `CalendarConnectedMsg`, wire `0x40a`.
    CalendarConnected,
    /// `CoatlicueTimingConfigurationConnectedMsg`, wire `0x1be`.
    CoatlicueTiming,
    /// `PlayerManagerSelfIdentificationMsg`, wire `0x65c`.
    SelfIdentification,
    /// `ReceivePlayerSpawnPointMsg`, wire `0x651`.
    ///
    /// A signal with no body: the record is the typed header and nothing else,
    /// so this rung is framed directly from its wire id instead of through a
    /// card. See `spawn_point` below.
    SpawnPoint,
    /// `LevelInfoChangedMsg`, wire `0x663`.
    LevelInfo,
    /// The type-`0x08` replicated-state bundle the emitter authors.
    State,
}

/// The captured bodies one ladder is assembled from.
///
/// Grouped in a struct because the ladder is now six bodies and a positional
/// signature of that width says nothing about which is which. Every body is the
/// committed corpus record; [`PostV3Ladder::from_captured`] decodes it into its
/// card and re-encodes it, so the bytes on the wire are the server's.
#[derive(Debug, Clone, Copy)]
pub struct CapturedRungs<'a> {
    /// The `0x15d` ping (`0x2_T0x15d_R.bin`).
    pub ping: &'a [u8],
    /// The `0x40a` calendar-connected record (`0x4_T0x40a_R.bin`).
    pub calendar_connected: &'a [u8],
    /// The `0x1be` coatlicue-timing record (`0x5_T0x1be_R.bin`).
    pub coatlicue_timing: &'a [u8],
    /// The `0x65c` self-identification body (`0x6_T0x65c_R.bin`).
    pub self_identification: &'a [u8],
    /// The `0x663` level-info body (`0x10_T0x663_R.bin`).
    pub level_info: &'a [u8],
    /// The `0x08` state bundle body (`0x9e_T0x8_R.bin`).
    pub state_bundle: &'a [u8],
}

/// The repeating `0x15d` ping: the rung that is due before the plan and then
/// once a second, which is why it is not one of the plan's records.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Heartbeat {
    card: FlowWorldEntryRungPing,
    offset_ms: u32,
    period_ms: u32,
}

impl Heartbeat {
    /// Milliseconds after the registration answer the first ping is due.
    #[must_use]
    pub const fn first_offset_ms(&self) -> u32 {
        self.offset_ms
    }

    /// Milliseconds between two pings.
    #[must_use]
    pub const fn period_ms(&self) -> u32 {
        self.period_ms
    }

    /// The captured tick: the 48-bit big-endian nanosecond counter the ping held,
    /// rejoined from the card's `tick_high` and `tick_low`.
    #[must_use]
    pub const fn tick(&self) -> u64 {
        (self.card.tick_high as u64) << 32 | self.card.tick_low as u64
    }

    /// The 8-byte body for `tick`, re-encoded through the card.
    ///
    /// The tick is masked to the 6 bytes the wire carries, so continuing the
    /// series cannot silently widen the field.
    ///
    /// # Errors
    /// Returns [`LadderError`] when the card refuses to encode.
    pub fn payload(&self, tick: u64) -> Result<Vec<u8>, LadderError> {
        let tick = tick & HEARTBEAT_TICK_MASK;
        let card = FlowWorldEntryRungPing {
            unresolved_prefix: self.card.unresolved_prefix.clone(),
            tick_high: (tick >> 32) as u16,
            tick_low: (tick & 0xFFFF_FFFF) as u32,
        };
        let mut body = Vec::new();
        card.encode(&mut body)?;
        Ok(body)
    }
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
    heartbeat: Heartbeat,
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
        rungs: &CapturedRungs<'_>,
        state_extents: &[(u64, u64, usize)],
        decision: &Decision,
    ) -> Result<Self, LadderError> {
        let heartbeat = FlowWorldEntryRungPing::decode(rungs.ping)?;
        let calendar_connected =
            FlowWorldEntryRungCalendarConnected::decode(rungs.calendar_connected)?;
        let coatlicue_timing = FlowWorldEntryRungCoatlicueTiming::decode(rungs.coatlicue_timing)?;
        let self_identification =
            FlowWorldEntryRungSelfIdentification::decode(rungs.self_identification)?;
        let level_info = FlowWorldEntryRungLevelInfo::decode(rungs.level_info)?;
        let extents: Vec<FragmentExtent> = state_extents
            .iter()
            .map(|&(key, type_index, payload_len)| FragmentExtent {
                key,
                type_index,
                payload_len,
            })
            .collect();
        let bundle = Bundle::<LocalPlayerState>::decode(rungs.state_bundle, &extents)?;
        let emission = emit(bundle, decision)?;
        Self::from_emission(
            &heartbeat,
            &calendar_connected,
            &coatlicue_timing,
            &self_identification,
            &level_info,
            &emission,
        )
    }

    /// Build the ladder from already-decoded card values and an emission.
    ///
    /// # Errors
    /// Returns [`LadderError`] when a card refuses to encode.
    pub fn from_emission(
        heartbeat: &FlowWorldEntryRungPing,
        calendar_connected: &FlowWorldEntryRungCalendarConnected,
        coatlicue_timing: &FlowWorldEntryRungCoatlicueTiming,
        self_identification: &FlowWorldEntryRungSelfIdentification,
        level_info: &FlowWorldEntryRungLevelInfo,
        state: &Emission,
    ) -> Result<Self, LadderError> {
        let mut body = Vec::new();
        calendar_connected.encode(&mut body)?;
        let calendar = framed(FlowWorldEntryRungCalendarConnected::WIRE_ID, &body)?;

        let mut body = Vec::new();
        coatlicue_timing.encode(&mut body)?;
        let coatlicue = framed(FlowWorldEntryRungCoatlicueTiming::WIRE_ID, &body)?;

        let mut body = Vec::new();
        self_identification.encode(&mut body)?;
        let self_ident = framed(FlowWorldEntryRungSelfIdentification::WIRE_ID, &body)?;

        let spawn_point = framed(SPAWN_POINT_WIRE_ID, &[])?;

        let mut body = Vec::new();
        level_info.encode(&mut body)?;
        let level_info_payload = framed(FlowWorldEntryRungLevelInfo::WIRE_ID, &body)?;

        let inner = state.encode()?;
        let mut state_payload = Vec::new();
        Writer::new(&mut state_payload).vlq32(inner.len() as u64)?;
        state_payload.extend_from_slice(&inner);

        Ok(Self {
            heartbeat: Heartbeat {
                card: heartbeat.clone(),
                offset_ms: HEARTBEAT_OFFSET_MS,
                period_ms: HEARTBEAT_PERIOD_MS,
            },
            plan: plan_rungs([
                (Rung::CalendarConnected, calendar),
                (Rung::CoatlicueTiming, coatlicue),
                (Rung::SelfIdentification, self_ident),
                (Rung::SpawnPoint, spawn_point),
                (Rung::LevelInfo, level_info_payload),
                (Rung::State, state_payload),
            ]),
        })
    }

    /// The repeating `0x15d` ping this ladder opens with.
    #[must_use]
    pub const fn heartbeat(&self) -> &Heartbeat {
        &self.heartbeat
    }

    /// One heartbeat datagram for `tick`, framed like every other rung.
    ///
    /// # Errors
    /// Returns [`LadderError`] when the ping card or the Carrier framing refuses a
    /// value.
    pub fn heartbeat_datagram(
        &self,
        tick: u64,
        envelope_seq: u16,
        message_seq: u16,
        reliable_seq: u16,
    ) -> Result<Vec<u8>, LadderError> {
        let payload = framed(
            FlowWorldEntryRungPing::WIRE_ID,
            &self.heartbeat.payload(tick)?,
        )?;
        build_datagram(&payload, None, envelope_seq, message_seq, reliable_seq)
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
        build_datagram(
            record.payload(),
            record.chunk,
            envelope_seq,
            message_seq,
            reliable_seq,
        )
    }
}

/// Frame one record payload into the typed envelope: a VLQ32 length, the type
/// marker, the prefix-varint wire type, then the body.
fn framed(wire_id: u32, body: &[u8]) -> Result<Vec<u8>, LadderError> {
    Ok(typed_record(wire_id, body)?)
}

/// Frame one record payload as a plaintext Carrier datagram.
///
/// # Errors
/// Returns [`LadderError`] when the chunk count does not fit a `u16` or the
/// Carrier framing refuses a value.
pub fn build_datagram(
    payload: &[u8],
    chunk: Option<Chunk>,
    envelope_seq: u16,
    message_seq: u16,
    reliable_seq: u16,
) -> Result<Vec<u8>, LadderError> {
    let mut carrier = MessageRecord::new(0, payload.to_vec())
        .with_reliable()
        .with_sequence(message_seq)
        .with_reliable_sequence(reliable_seq);
    let flags = match chunk {
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
///
/// The plan starts one [`MESSAGE_INTERVAL_MS`] after the heartbeat, because the
/// heartbeat owns [`HEARTBEAT_OFFSET_MS`]: the capture's spacing has to hold
/// from the first record, and the first record is the ping.
fn plan_rungs(rungs: [(Rung, Vec<u8>); 6]) -> Vec<PlannedRecord> {
    let mut plan = Vec::new();
    let mut at = HEARTBEAT_OFFSET_MS.saturating_add(MESSAGE_INTERVAL_MS);
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
