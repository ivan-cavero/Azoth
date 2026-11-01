//! Which generated card owns which state type index.
//!
//! The bundle framing is generic: it asks [`StateComponent`] for a type index and
//! a body, and never names a card itself. This module is the one place that binds
//! a recovered card to the number the client's registry resolves, so the binding
//! is stated once instead of being threaded through the framing.
//!
//! The binding is the Atlas card's own, not a guess: the card
//! `codec.objectives-replicated-state` carries the aliases `wire-type:3857` and
//! `state-fragment:key22`, and the dispatcher (`FUN_146af38c0`) resolves the type
//! index to the AZ id that selects the card's reader (`0x1417b5080`) and writer
//! (`0x141728b30`).

use crate::framing::{Reader, WireError, Writer};
use crate::generated::CodecObjectivesReplicatedState;
use crate::state_bundle::StateComponent;

impl StateComponent for CodecObjectivesReplicatedState {
    const UID: &'static str = "codec.objectives-replicated-state";

    /// `wire-type:3857`, the alias the card itself states.
    const TYPE_INDEX: u64 = 3857;

    fn read_body(reader: &mut Reader<'_>) -> Result<Self, WireError> {
        Self::read_from(reader)
    }

    fn write_body(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        self.write_to(writer)
    }
}
