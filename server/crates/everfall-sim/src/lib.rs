//! Objective state and client-reported state, and the rules that apply a change.
//!
//! This crate owns the world's objective bookkeeping and the reports the client
//! sends about itself, and nothing else. It reads no file, opens no socket, and
//! encodes no bytes: a change arrives as a domain value and leaves as a
//! [`Decision`]. That is the point of the boundary -- the game rules here cannot
//! be welded to a wire layout, because this crate cannot name one.
//!
//! Every bound below is the atlas's, not a guess:
//! `msg.objectives-update-tracked-objectives` states at most 8 tracked ids, and
//! `msg.objectives-set-objective-auto-pinning` states at most 36 pin flags.
//! Both cards are in `research/atlas/ontology/concepts/`. The three
//! client-reported families state no bound, so their rule is a state write.

mod client_state;
mod objectives;

pub use crate::client_state::{ClientState, ScreenId};
pub use crate::objectives::{
    ActorId, Decision, Dropped, ObjectiveId, ObjectiveRequest, PIN_FLAG_LIMIT, Rejection, Sim,
    TRACKED_LIMIT, TrackedObjectives,
};
