//! Encode and decode the named fields of the Everfall wire protocol.
//!
//! `everfall-wire` turns named state into bytes and back. Every struct in
//! [`generated`] is one Atlas card: its fields are that card's `fields[]` under
//! the card's own names, and a raw byte run is an [`Opaque`] that carries its
//! Atlas id instead of a bare byte vector.
//!
//! The crate owns no game rules and no I/O: it never reads a file, opens a
//! socket, or plays back a recording. The record envelope (`00 01` then the
//! prefix-varint message type) is framing owned by [`framing`] and is never a
//! field.

mod framing;
mod opaque;

pub mod generated;
/// The hand-written codec for the mask-selected state body of Atlas card 3857.
pub mod objectives_state;

pub use crate::framing::{RECORD_TYPE_MARKER, Reader, WireError, Writer};
pub use crate::opaque::Opaque;
