//! The crate that owns the world process: wire in, decision out, state back out.
//!
//! This is the only place where a wire struct and a domain value meet. It
//! depends on [`everfall_sim`] and [`everfall_wire`]; neither depends on it, so
//! the game rules cannot see a byte layout and the codec cannot see a rule.
//!
//! It opens no socket. The atlas states that the Objectives family has no reply
//! message, so [`OBJECTIVES_REPLY_WIRE_ID`] is `None` and this world decides and
//! records instead of sending: the client learns the outcome from replicated
//! state, which is the encoder in [`emitter`].
//!
//! [`rep`] is the other direction: it turns one decrypted REP datagram into the
//! datagrams to answer with, which is what carries the client past registration.
//! It opens no socket either -- the DTLS loop owns the transport and hands it
//! bytes.

mod dispatcher;
pub mod emitter;
pub mod rep;

pub use crate::dispatcher::{DecisionRecord, DispatchError, OBJECTIVES_REPLY_WIRE_ID, World};
pub use crate::emitter::{Emission, EmitError, emit};
pub use crate::rep::{
    REGISTRATION_REQUEST_WIRE_ID, RepError, RepRequest, RepSession, SERVER_VERSION, SESSION_TOKEN,
    ack_window_first, handle_app_data,
};
