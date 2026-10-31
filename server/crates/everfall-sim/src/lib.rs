//! Objective state, and the rules that decide whether a change is legal.
//!
//! This crate owns the world's objective bookkeeping and nothing else. It reads
//! no file, opens no socket, and encodes no bytes: a change arrives as a domain
//! value and leaves as a [`Decision`]. That is the point of the boundary -- the
//! game rules here cannot be welded to a wire layout, because this crate cannot
//! name one.
//!
//! Every bound below is the atlas's, not a guess:
//! `msg.objectives-update-tracked-objectives` states at most 8 tracked ids, and
//! `msg.objectives-set-objective-auto-pinning` states at most 36 pin flags.
//! Both cards are in `research/atlas/ontology/concepts/`.

mod objectives;

pub use crate::objectives::{
    ActorId, Decision, Dropped, ObjectiveId, ObjectiveRequest, PIN_FLAG_LIMIT, Rejection, Sim,
    TRACKED_LIMIT, TrackedObjectives,
};
