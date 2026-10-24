//! The ladder: what the world sends a client, and in what order.
//!
//! WHY THE ORDER IS A MODULE AND NOT A SEQUENCE OF CALLS
//! ====================================================
//! The client walks a state machine, and each rung is only valid in the state the previous one
//! leaves it in. Sending two of them in one burst **crashed the client** (recorded in the
//! prototype), and sending them out of order leaves it stuck with no error anywhere. So the order
//! is data — a list of steps — rather than an accident of how a function happens to be written.
//!
//! | rung | client state it advances | evidence |
//! | --- | --- | --- |
//! | V3 response | `WaitingForREPConnection` → `WaitingForActorGameConnection` | captured, 88 B |
//! | greetings | GridMate peer handshake | stock protocol |
//! | self-identification | → `WaitingForSpawnPoint` | first-light RE, validated live here |
//! | level info changed | → `WaitingForPlayerSpawn`, the map loads | **captured**, wire `0x663` |
//! | the spawn record | → `InGame`, the player appears | **captured**, record 1, 48 fragments |
//! | the state stream | keeps the ALC cable clear | measured: record 1 re-sent ~1 Hz |
//!
//! The spawn record's payload is NOT owned here: 46,393 captured bytes whose dimensions live in
//! `azoth-wire::spawn`, with their provenance. This module decides when to send it and how to cut
//! it up.
//!
//! WHY A RUNG CAN BE MORE THAN ONE DATAGRAM, AND WHY THE CUT IS 1100 BYTES
//! =====================================================================
//! The spawn does not fit one datagram, and a record that does not fit is **not delivered** even
//! when the transport looks perfect. Measured 2026-09-24 (`rep.py`, `REPLAY_SINGLE_LIMIT`): a
//! 12,706-byte record sent as one datagram was acknowledged by the client and never reached its
//! reader, while every record under ~256 bytes arrived; it was re-sent **4,229 times** with no
//! progress. What works is `MF_CHUNKS`: chunks of `REPLAY_CHUNK_SIZE` = **1100** bytes, one chunk
//! per datagram, each carrying the chunk count.
//!
//! 1100 is not a round number chosen for comfort: the largest captured UDP payloads are 1,152 B
//! client→server and 1,166 B server→client, and the transport's ceiling is 1200
//! (`azoth_dtls::DtlsConfig::max_datagram`). Above the path MTU a datagram is IP-fragmented and one
//! lost fragment loses all of it. 1100 + a 4-byte envelope + 8 bytes of record framing is 1112.
//!
//! Chunks are paced by the caller: one datagram per call, so a 43-chunk spawn leaves the socket
//! across 43 ticks instead of as one burst. Measured 2026-09-24 again: twelve chunks back-to-back
//! were all acknowledged and the client reassembled exactly 6,370 of 12,706 bytes, every attempt,
//! while the prototype's working value is a 4 ms gap between chunks — which one chunk per 50 Hz
//! tick reproduces without a timer.
//! Nothing here is composed from the prototype's source: `level_info_changed_body()` is dead code
//! claiming 92 bytes for a 106-byte message, and the spawn record has never been composed at all.
//! Every rung comes from the capture or from a measured, validated source, and says which.

use std::collections::VecDeque;
use std::net::SocketAddr;

use azoth_wire::ladder::{
    datagram, greetings_payload, self_identification_body, typed_record_payload,
    LEVEL_INFO_CHANGED_TYPE, SELF_IDENTIFICATION_TYPE,
};
use azoth_wire::record::{flags, MessageRecord};
use azoth_wire::v3::RegistrationResponse;
use azoth_wire::{bundle, varint, WireError};

/// The largest record payload the client takes in a single datagram.
///
/// `REPLAY_SINGLE_LIMIT` in the prototype, measured 2026-09-24: every message that arrived was
/// ≤ 76 B, the first one above a few hundred bytes was acknowledged and never delivered, and
/// splitting it is what made the stream flow. 256 is the value the prototype has shipped since.
pub const SINGLE_DATAGRAM_LIMIT: usize = 256;

/// The chunk payload size for a record too large for one datagram.
///
/// `REPLAY_CHUNK_SIZE` in the prototype; the measurement and the MTU arithmetic are in the module
/// docs.
pub const CHUNK_PAYLOAD: usize = 1100;

/// One step of the ladder.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Step {
    /// `Cmd_Greetings`, the GridMate handshake.
    Greetings,
    /// `PlayerManagerSelfIdentificationMsg`, 21 zero bytes.
    SelfIdentification,
    /// `LevelInfoChangedMsg`, the captured 106-byte body.
    ///
    /// Carried, not composed: `azoth-wire::ladder` has no builder for it because 26 of its bytes are
    /// unexplained.
    LevelInfoChanged {
        /// The captured body.
        body: Vec<u8>,
    },
    /// The spawn record, whose payload `azoth-wire::spawn` owns: `record_id 1`, 48 fragments.
    Spawn {
        /// The record payload, `record_id 1` and 48 fragments.
        payload: Vec<u8>,
    },
}

impl Step {
    /// Ontology concept this rung advances (`research/atlas/ontology/concepts/`).
    ///
    /// Bytes without a named purpose are how the prototype stayed a replayer. Every
    /// send path should be able to answer this; when a rung is still a capture seed,
    /// the concept still names *why* the client needs it.
    #[must_use]
    pub const fn ontology_uid(&self) -> &'static str {
        match self {
            Self::Greetings => "flow.world-entry.rung.greetings",
            Self::SelfIdentification => "flow.world-entry.rung.self-identification",
            Self::LevelInfoChanged { .. } => "flow.world-entry.rung.level-info",
            Self::Spawn { .. } => "flow.world-entry.rung.spawn",
        }
    }
}

/// One datagram to write, with the reliable sequence it was queued under.
///
/// The sequence is carried out because the caller hands the bytes to the session's resend table,
/// which is keyed by reliable sequence and is what retransmits them when the client misses one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outgoing {
    /// The record's reliable sequence, which the resend table is keyed by.
    pub reliable_sequence: u16,
    /// The datagram to write, Carrier envelope included.
    pub datagram: Vec<u8>,
    /// Why this datagram exists (ontology uid); see [`Step::ontology_uid`].
    pub ontology_uid: &'static str,
}

/// The ladder for one peer: the steps still to send, and the counters that order them.
#[derive(Debug, Clone)]
pub struct Ladder {
    peer: SocketAddr,
    remaining: Vec<Step>,
    queued: VecDeque<Outgoing>,
    next_sequence: u16,
    next_reliable: u16,
    next_envelope: u16,
}

impl Ladder {
    /// Build the ladder a client walks after registering.
    ///
    /// The spawn payload is passed in rather than fetched, so this module never depends on where a
    /// captured template lives.
    #[must_use]
    pub fn for_peer(peer: SocketAddr, level_info_body: Vec<u8>, spawn_payload: Vec<u8>) -> Self {
        Self {
            peer,
            remaining: vec![
                Step::Greetings,
                Step::SelfIdentification,
                Step::LevelInfoChanged {
                    body: level_info_body,
                },
                Step::Spawn {
                    payload: spawn_payload,
                },
            ],
            queued: VecDeque::new(),
            next_sequence: 1,
            next_reliable: 1,
            next_envelope: 1,
        }
    }

    /// Who this ladder belongs to.
    #[must_use]
    pub fn peer(&self) -> SocketAddr {
        self.peer
    }

    /// Steps that have not been started yet.
    #[must_use]
    pub fn remaining(&self) -> usize {
        self.remaining.len()
    }

    /// Whether every rung has been handed out.
    #[must_use]
    pub fn is_complete(&self) -> bool {
        self.remaining.is_empty() && self.queued.is_empty()
    }

    /// The V3 registration response, as the datagram that flips the client's `rep.ready` to 1.
    ///
    /// A method rather than a free function so it consumes the same envelope and record counters as
    /// the rungs that follow: two counters on one socket cost the prototype a session at ~26
    /// minutes (see `azoth_wire::envelope`).
    ///
    /// # Errors
    /// A wire encoding failure, which for this fixed 88-byte body means a bug.
    pub fn registration(&mut self, session_token: [u8; 32]) -> Result<Outgoing, WireError> {
        let payload = RegistrationResponse::success(session_token).encode_record()?;
        let record = self.reliable_record(payload, 1);
        self.pack(record, "flow.world-entry.rung.v3-response")
    }

    /// The next datagram of the next rung, or `None` once the ladder is done.
    ///
    /// **One datagram per call**, which is the measured constraint twice over: batching two rungs
    /// crashed the client, and batching several chunks of one rung truncated its reassembly. So a
    /// rung that needs many datagrams is drained by calling this repeatedly.
    ///
    /// # Errors
    /// A wire encoding failure, which for these fixed bodies means a bug rather than bad input.
    pub fn next(&mut self) -> Result<Option<Outgoing>, WireError> {
        if self.queued.is_empty() {
            let Some(step) = self.remaining.first().cloned() else {
                return Ok(None);
            };
            self.remaining.remove(0);
            self.encode_step(step)?;
        }
        Ok(self.queued.pop_front())
    }

    /// Turn one step into one or more queued datagrams.
    fn encode_step(&mut self, step: Step) -> Result<(), WireError> {
        let ontology_uid = step.ontology_uid();
        match step {
            // `Cmd_Greetings` is a Carrier message, not a typed one: no VLQ prefix, no marker.
            Step::Greetings => {
                let record = self.reliable_record(greetings_payload(), 1);
                self.queue(record, ontology_uid)
            }
            Step::SelfIdentification => {
                let inner =
                    typed_record_payload(SELF_IDENTIFICATION_TYPE, &self_identification_body())?;
                self.pack_message(inner, ontology_uid)
            }
            Step::LevelInfoChanged { body } => {
                let inner = typed_record_payload(LEVEL_INFO_CHANGED_TYPE, &body)?;
                self.pack_message(inner, ontology_uid)
            }
            Step::Spawn { payload } => {
                // The spawn travels as a state bundle: the record payload inside the bundle's
                // prologue and length. The replication counter is what the client's unreliable gate
                // compares and it must strictly advance, or every bundle is discarded. It is fixed
                // once, here, because the chunks are one message and share it.
                let body = bundle::encode(u64::from(self.next_envelope), &payload)?;
                let mut inner = varint::encode(body.len() as u64)?;
                inner.extend_from_slice(&body);
                self.pack_message(inner, ontology_uid)
            }
        }
    }

    /// A reliable channel-0 record on the ladder's own counters.
    fn reliable_record(&mut self, payload: Vec<u8>, num_chunks: u16) -> MessageRecord {
        MessageRecord {
            reliable: true,
            connecting: false,
            channel: 0,
            sequence: self.take_sequence(),
            reliable_sequence: self.take_reliable(),
            num_chunks,
            payload,
            flags: flags::RELIABLE | flags::DATA_CHANNEL,
        }
    }

    /// Build one record's datagram on the ladder's own counters.
    fn pack(
        &mut self,
        record: MessageRecord,
        ontology_uid: &'static str,
    ) -> Result<Outgoing, WireError> {
        let reliable_sequence = record.reliable_sequence;
        let envelope = self.take_envelope();
        let datagram = datagram(envelope, &[record])?;
        Ok(Outgoing {
            reliable_sequence,
            datagram,
            ontology_uid,
        })
    }

    /// Queue one record as one datagram.
    fn queue(&mut self, record: MessageRecord, ontology_uid: &'static str) -> Result<(), WireError> {
        let out = self.pack(record, ontology_uid)?;
        self.queued.push_back(out);
        Ok(())
    }

    /// Queue a typed message, chunked when it does not fit one datagram.
    ///
    /// The count is the **total** in every chunk, not a countdown: that is what the prototype ships
    /// (`REPLAY_CHUNK_COUNT_TOTAL`) and the only form this writer can express, since `marshal`
    /// derives `MF_CHUNKS` from `num_chunks > 1` and a countdown would drop the flag on the last
    /// chunk — the one the client needs it for.
    fn pack_message(&mut self, inner: Vec<u8>, ontology_uid: &'static str) -> Result<(), WireError> {
        if inner.len() <= SINGLE_DATAGRAM_LIMIT {
            let record = self.reliable_record(inner, 1);
            return self.queue(record, ontology_uid);
        }
        // A payload above the single-datagram limit is always cut into at least two chunks: one
        // chunk carrying `numChunks 1` is the same oversized single datagram that is measured never
        // to be delivered, because nothing tells the client to reassemble it.
        let chunk = if inner.len() > CHUNK_PAYLOAD {
            CHUNK_PAYLOAD
        } else {
            inner.len().div_ceil(2)
        };
        let total = inner.len().div_ceil(chunk);
        let num_chunks = u16::try_from(total).map_err(|_| WireError::OutOfRange {
            field: "chunk count",
            value: total as u64,
            limit: u64::from(u16::MAX) + 1,
        })?;
        let mut pieces: Vec<Vec<u8>> = inner.chunks(chunk).map(<[u8]>::to_vec).collect();
        for piece in pieces.drain(..) {
            let mut record = self.reliable_record(piece, num_chunks);
            record.flags |= flags::CHUNKS;
            self.queue(record, ontology_uid)?;
        }
        Ok(())
    }

    fn take_sequence(&mut self) -> u16 {
        let value = self.next_sequence;
        self.next_sequence = self.next_sequence.wrapping_add(1);
        value
    }

    fn take_reliable(&mut self) -> u16 {
        let value = self.next_reliable;
        self.next_reliable = self.next_reliable.wrapping_add(1);
        value
    }

    fn take_envelope(&mut self) -> u16 {
        let value = self.next_envelope;
        self.next_envelope = self.next_envelope.wrapping_add(1);
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use azoth_wire::{envelope, record};

    fn ladder() -> Ladder {
        // The spawn payload is large enough to need chunking, because that is the measured case.
        Ladder::for_peer(
            "127.0.0.1:27000".parse().expect("addr"),
            vec![0xAB; 106],
            vec![0xCD; 3000],
        )
    }

    /// The single record in `datagram`.
    fn message(datagram: &[u8]) -> MessageRecord {
        let (_, body) = envelope::parse(datagram).expect("envelope");
        record::parse(body).expect("records").records.remove(0)
    }

    #[test]
    fn the_ladder_has_four_rungs() {
        let ladder = ladder();
        assert_eq!(ladder.remaining(), 4);
        assert!(!ladder.is_complete());
    }

    #[test]
    fn each_call_returns_exactly_one_datagram() {
        // Batching two rungs in one datagram crashed the client, so one-per-call is the contract.
        let mut ladder = ladder();
        let mut seen = 0;
        while let Some(out) = ladder.next().expect("encodes") {
            seen += 1;
            assert!(out.datagram.len() > 4, "a datagram, not a bare payload");
            assert_eq!(out.datagram[0] & 0x80, 0x80, "plaintext envelope");
            assert!(seen <= 64, "the ladder must end");
        }
        assert!(ladder.is_complete());
        assert_eq!(ladder.remaining(), 0);
    }

    #[test]
    fn the_envelope_sequence_advances_per_datagram() {
        // The envelope counter is a different counter from the record sequences, and the ACK range
        // is expressed over it. Conflating them cost the prototype a session at ~26 minutes.
        let mut ladder = ladder();
        let mut expected = 1u16;
        while let Some(out) = ladder.next().expect("encodes") {
            assert_eq!(u16::from_be_bytes([out.datagram[2], out.datagram[3]]), expected);
            expected += 1;
        }
        assert!(expected > 4, "the spawn alone is many datagrams");
    }

    #[test]
    fn the_first_rung_is_the_greeting() {
        let mut ladder = ladder();
        let first = ladder.next().expect("encodes").expect("rung");
        // The greeting payload is 10 bytes and starts with Cmd_Greetings = 1. The record prefix is
        // flags(1) + size(2) + seq(2) + rel(2): the CHANNEL byte is omitted for channel 0, because
        // the writer's previous-channel starts at 0.
        assert_eq!(first.datagram[4 + 1 + 2 + 2 + 2], 1, "Cmd_Greetings");
    }

    #[test]
    fn the_spawn_rung_is_a_chunked_state_bundle() {
        let mut ladder = ladder();
        for _ in 0..3 {
            ladder.next().expect("encodes");
        }
        let spawn = ladder.next().expect("encodes").expect("rung");
        let message = message(&spawn.datagram);
        assert!(message.num_chunks > 1, "the spawn must be chunked");
        // A chunk is a slice of the message, so the first one starts with the message's VLQ length
        // and then the type marker.
        let (_, after) = varint::decode(&message.payload, 0).expect("VLQ length");
        assert_eq!(&message.payload[after..after + 3], &[0x00, 0x01, 0x08]);
    }

    #[test]
    fn the_registration_rung_carries_the_response() {
        let mut ladder = ladder();
        let response = ladder.registration([0x5A; 32]).expect("encodes");
        let message = message(&response.datagram);
        assert_eq!(message.payload[0] as usize, 88, "VLQ32 length of the body");
        assert_eq!(&message.payload[1..3], &[0x00, 0x01], "the typed marker");
        assert_eq!(message.payload[3], 0x03, "RegistrationResponseMsg");
        assert_eq!(response.ontology_uid, "flow.world-entry.rung.v3-response");
        let greeting = ladder.next().expect("encodes").expect("rung");
        assert_eq!(greeting.reliable_sequence, 2, "the greeting shares the counters");
        assert_eq!(greeting.ontology_uid, "flow.world-entry.rung.greetings");
    }

    #[test]
    fn every_ladder_step_names_an_ontology_concept() {
        let steps = [
            Step::Greetings,
            Step::SelfIdentification,
            Step::LevelInfoChanged { body: vec![0] },
            Step::Spawn { payload: vec![0] },
        ];
        for step in steps {
            assert!(
                step.ontology_uid().starts_with("flow.world-entry."),
                "{}",
                step.ontology_uid()
            );
        }
    }
}
