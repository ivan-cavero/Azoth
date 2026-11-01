//! Encode and decode the named fields of the Everfall wire protocol.
//!
//! `everfall-wire` turns named state into bytes and back. Every struct in
//! [`generated`] is one Atlas card: its fields are that card's `fields[]` under
//! the card's own names, and a raw byte run is an [`Opaque`] that carries its
//! Atlas id instead of a bare byte vector. A card that declares a two-level
//! presence mask gets a group/member structure instead of a flat struct, and a
//! card that names a nested record gets that record's generated type.
//!
//! [`state_bundle`] is the other half: the type-0x08 replicated-state envelope
//! that carries those cards as fragments. It is generic over
//! [`StateComponent`], so the assembly names no message, and a fragment whose
//! type payload is not recovered stays an [`Opaque`] run.
//!
//! The crate owns no game rules and no I/O: it never reads a file, opens a
//! socket, or plays back a recording. The record envelope (`00 01` then the
//! prefix-varint message type) is framing owned by [`framing`] and is never a
//! field.

mod framing;
mod opaque;
mod state_bundle;
mod state_component;

pub mod generated;

pub use crate::framing::{RECORD_TYPE_MARKER, Reader, WireError, Writer};
pub use crate::opaque::Opaque;
pub use crate::state_bundle::{
    Bundle, BundleError, CARRIER_HEADROOM, CHUNK_LIMIT, DATAGRAM_CEILING, Fragment, FragmentExtent,
    FragmentPayload, PROLOGUE_HEAD, PROLOGUE_TAIL, Record, STATE_BUNDLE_TYPE, StateComponent,
    UNRECOVERED_FRAGMENT_PAYLOAD, chunk_ranges,
};
pub use crate::state_component::LocalPlayerState;
