//! The ladder: what the world sends a client, and in what order.
//!
//! WHY THE ORDER IS A MODULE AND NOT A SEQUENCE OF CALLS
//! ====================================================
//! The client walks a state machine, and each rung is only valid in the state the previous one
//! leaves it in. Sending two of them in one burst **crashed the client** (recorded in the
//! prototype), and sending them out of order leaves it stuck with no error anywhere. So the order
//! is data — a list of steps — rather than an accident of how a function happens to be written.
//!
//! WHAT EACH RUNG DOES, AND THE EVIDENCE FOR IT
//! ============================================
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
//! THE ONE RUNG THIS MODULE DOES NOT OWN
//! ====================================
//! The spawn record. It is 46,393 bytes of captured payload and it lives in `azoth-wire::spawn`,
//! which is where its provenance is stated. This module decides *when* to send it, not what it is.
//!
//! WHY NOTHING HERE IS COMPOSED FROM THE PROTOTYPE'S SOURCE
//! ======================================================
//! Because two of its composers are wrong. `level_info_changed_body()` is dead code claiming 92
//! bytes for a 106-byte message, and the spawn record has never been composed at all. Every rung
//! below either comes from the capture or from a measured, validated source — and each one says
//! which.

use std::net::SocketAddr;

use azoth_wire::ladder::{
    datagram, greetings_payload, self_identification_body, typed_record, SELF_IDENTIFICATION_TYPE,
};
use azoth_wire::record::MessageRecord;

/// One step of the ladder.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Step {
    /// `Cmd_Greetings`, the GridMate handshake.
    Greetings,
    /// `PlayerManagerSelfIdentificationMsg`, 21 zero bytes.
    SelfIdentification,
    /// `LevelInfoChangedMsg`, the captured 106-byte body.
    ///
    /// The body is carried, not composed: `azoth-wire::ladder` has no builder for it because 26 of
    /// its bytes are unexplained.
    LevelInfoChanged {
        /// The captured body.
        body: Vec<u8>,
    },
    /// The spawn record, whose payload `azoth-wire::spawn` owns.
    Spawn {
        /// The record payload, `record_id 1` and 48 fragments.
        payload: Vec<u8>,
    },
}

/// The ladder for one peer: the steps still to send, and the counters that order them.
#[derive(Debug, Clone)]
pub struct Ladder {
    peer: SocketAddr,
    remaining: Vec<Step>,
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

    /// Steps still to send.
    #[must_use]
    pub fn remaining(&self) -> usize {
        self.remaining.len()
    }

    /// Whether every rung has been sent.
    #[must_use]
    pub fn is_complete(&self) -> bool {
        self.remaining.is_empty()
    }

    /// Take the next rung and turn it into the datagram to send.
    ///
    /// **One rung per call, and one datagram per rung.** That is the measured constraint: batching
    /// two of them crashed the client, so the API makes batching awkward on purpose.
    ///
    /// # Errors
    /// A wire encoding failure, which for these fixed bodies means a bug rather than bad input.
    pub fn next_datagram(&mut self) -> Result<Option<Vec<u8>>, azoth_wire::WireError> {
        let Some(step) = self.remaining.first().cloned() else {
            return Ok(None);
        };
        self.remaining.remove(0);

        let record = match step {
            Step::Greetings => MessageRecord {
                reliable: true,
                connecting: false,
                channel: 0,
                sequence: self.take_sequence(),
                reliable_sequence: self.take_reliable(),
                num_chunks: 1,
                payload: greetings_payload(),
                flags: azoth_wire::record::flags::RELIABLE
                    | azoth_wire::record::flags::DATA_CHANNEL,
            },
            Step::SelfIdentification => typed_record(
                SELF_IDENTIFICATION_TYPE,
                &self_identification_body(),
                self.take_sequence(),
                self.take_reliable(),
            )?,
            Step::LevelInfoChanged { body } => typed_record(
                azoth_wire::ladder::LEVEL_INFO_CHANGED_TYPE,
                &body,
                self.take_sequence(),
                self.take_reliable(),
            )?,
            Step::Spawn { payload } => {
                // The spawn travels as a state bundle: the record payload inside the bundle's
                // prologue and length. The replication counter is what the client's unreliable gate
                // compares, and it must strictly advance or every bundle is discarded.
                let bundle = azoth_wire::bundle::encode(u64::from(self.next_envelope), &payload)?;
                MessageRecord {
                    reliable: true,
                    connecting: false,
                    channel: 0,
                    sequence: self.take_sequence(),
                    reliable_sequence: self.take_reliable(),
                    num_chunks: 1,
                    payload: bundle,
                    flags: azoth_wire::record::flags::RELIABLE
                        | azoth_wire::record::flags::DATA_CHANNEL,
                }
            }
        };

        let envelope = self.next_envelope;
        self.next_envelope = self.next_envelope.wrapping_add(1);
        datagram(envelope, &[record]).map(Some)
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
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ladder() -> Ladder {
        Ladder::for_peer(
            "127.0.0.1:27000".parse().expect("addr"),
            vec![0xAB; 106],
            vec![0xCD; 64],
        )
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
        for expected in (1..=4).rev() {
            let datagram = ladder.next_datagram().expect("encodes").expect("a rung");
            assert_eq!(ladder.remaining(), expected - 1);
            // A Carrier envelope plus at least one record.
            assert!(datagram.len() > 4, "a datagram, not a bare payload");
            assert_eq!(datagram[0] & 0x80, 0x80, "plaintext envelope");
        }
        assert!(ladder.is_complete());
        assert!(ladder.next_datagram().expect("ok").is_none());
    }

    #[test]
    fn the_envelope_sequence_advances_per_rung() {
        // The envelope counter is a different counter from the record sequences, and the ACK range
        // is expressed over it. Conflating them cost the prototype a session at ~26 minutes.
        let mut ladder = ladder();
        let mut seen = Vec::new();
        while let Some(datagram) = ladder.next_datagram().expect("encodes") {
            seen.push(u16::from_be_bytes([datagram[2], datagram[3]]));
        }
        assert_eq!(seen, vec![1, 2, 3, 4]);
    }

    #[test]
    fn the_spawn_rung_is_a_state_bundle() {
        let mut ladder = ladder();
        // Skip greetings, self-ident, level-info.
        for _ in 0..3 {
            ladder.next_datagram().expect("encodes");
        }
        let spawn = ladder.next_datagram().expect("encodes").expect("rung");
        // The record payload after the 4-byte envelope is the bundle, which starts 00 01 08.
        let body = &spawn[4..];
        // The record prefix is flags(1) + size(2) + seq(2) + rel(2) = 7 bytes: the CHANNEL byte is
        // omitted for channel 0, because the writer's previous-channel starts at 0. A first version
        // of this test assumed 8 and read one byte late.
        let payload_at = 1 + 2 + 2 + 2;
        assert_eq!(
            &body[payload_at..payload_at + 3],
            &[0x00, 0x01, 0x08],
            "the spawn must travel as a type-0x08 state bundle"
        );
    }

    #[test]
    fn the_first_rung_is_the_greeting() {
        let mut ladder = ladder();
        let first = ladder.next_datagram().expect("encodes").expect("rung");
        // The greeting payload is 10 bytes and starts with Cmd_Greetings = 1.
        let body = &first[4..];
        // 7 bytes of record prefix, for the reason given in the spawn test.
        let payload_at = 1 + 2 + 2 + 2;
        assert_eq!(body[payload_at], 1, "Cmd_Greetings");
    }
}
