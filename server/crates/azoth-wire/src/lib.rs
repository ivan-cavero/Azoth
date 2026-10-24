//! Javelin wire codecs: the exact bytes the New World client sends and accepts.
//!
//! WHY THIS CRATE EXISTS
//! =====================
//! Every other crate in the workspace sits on top of these encodings, and the
//! client is unforgiving about them: a varint written in the wrong bit order
//! silently desynchronises a whole message stream, and a length field that is
//! off by one produces "Failed to unmarshal" with no indication of which field
//! was wrong. Isolating the codecs means their correctness is one crate's
//! problem, provable against the captured corpus with no I/O and no state.
//!
//! WHAT IS AND IS NOT HERE
//! =======================
//! This crate owns *formats*: the prefix varint, VLQ32, the Carrier envelope,
//! the MessageRecord framing, the type-0x08 state-bundle grammar, the fragment
//! grammar, the LZ4 block, and V3 registration. [`carrier`] adds the one format
//! that is not derived but captured — the connection-acceptance flight — because
//! a client will not send V3 until it has received those exact bytes.
//!
//! It does **not** own *field maps*. Which offset inside a fragment is the
//! player's x coordinate is build-scoped and lives with the caller, because a
//! format survives a client build and a field map does not
//! (`docs/PLAN-backend-rust.md` §0.2).
//!
//! The one deliberate exception is [`spawn`]: the spawn record is a *captured
//! template*, not a format, so its dimensions and the two offsets it is used at
//! travel with it. Keeping them apart would leave a caller holding a captured
//! byte string and no statement of what it is, which is exactly the ambiguity
//! `docs/archive/odd-tasks/phase-3-world.md` S7 asks this boundary to remove.
//!
//! EVIDENCE
//! ========
//! Every layout below is derived from measured client behaviour, recorded in
//! `research/docs/JAVELIN-PROTOCOL.md` and `research/docs/REP-PROTOCOL.md`, and
//! checked byte-for-byte against `services/world/replay/messages-redacted.txt`.
//! Nothing here is a decompiler guess.
//!
//! The parity contract is mechanical: `xtask parity` runs the Python encoders and
//! these ones over the same fixtures and fails on any byte difference.

#![forbid(unsafe_code)]

pub mod bundle;
pub mod carrier;
pub mod container;
pub mod envelope;
pub mod error;
pub mod fragment;
pub mod ladder;
pub mod lz4;
pub mod marshal;
pub mod player_record;
pub mod presence;
pub mod record;
pub mod spawn;
pub mod v3;
pub mod varint;
pub mod vlq32;

pub use error::WireError;

/// The two-byte tag that begins every inbound typed message.
///
/// Measured across every captured typed record: the client's own container and
/// the server's both place this marker immediately before the type varint
/// (`research/docs/JAVELIN-PROTOCOL.md` §1f).
pub const TYPE_MARKER: [u8; 2] = [0x00, 0x01];

/// Wire type of the state bundle: the entity/component replication record.
pub const STATE_BUNDLE_TYPE: u32 = 0x08;

/// Channel that carries Carrier system messages (connect, ACK, clock, bandwidth).
pub const CHANNEL_SYSTEM: u8 = 3;

/// The highest channel index the protocol defines. A record claiming anything
/// higher is a parse error, not a value to store: a bogus channel 4 indexed past
/// the per-channel tables and crashed the Python world server's parse path
/// (measured 2026-10-11, `frame.py`).
pub const MAX_CHANNEL: u8 = 3;
