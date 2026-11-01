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

mod dispatcher;
pub mod emitter;

pub use crate::dispatcher::{DecisionRecord, DispatchError, OBJECTIVES_REPLY_WIRE_ID, World};
pub use crate::emitter::{Emission, EmitError, emit};
