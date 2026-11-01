//! Which generated card owns which state type index.
//!
//! The bundle framing is generic: it asks [`StateComponent`] for its type indices
//! and its body, and never names a card itself. This module is the one place that
//! binds a recovered card to the number the client's registry resolves, so the
//! binding is stated once instead of being threaded through the framing.
//!
//! Each binding is the Atlas card's own, not a guess. The dispatcher
//! (`FUN_146af38c0`) reads the type-index varint, maps it to a 16-byte AZ id
//! through the flat table at `registry+0x40`, hashes that id through
//! `FUN_146166220` to the type's descriptor, and calls the descriptor facet's own
//! object at `+0x88` (writer) and `+0x90` (reader). For a replicated-state class
//! those two slots are the two-level presence-mask pair, so every binding here
//! resolves to a card whose body is `[group mask][member mask][members]`.
//!
//! Three fragments of the local-player record are typed today:
//!
//! | key | type | card | writer / reader |
//! | --- | --- | --- | --- |
//! | 22 | 3857 | `codec.objectives-replicated-state` | `0x141728b30` / `0x1417b5080` |
//! | 19 | 3133 | `codec.entitlement-replicated-state` | `0x141728b30` / `0x1417b5080` |
//! | 74 | 5691 | `codec.transmog-replicated-state` | `0x141728b30` / `0x1417b5080` |
//!
//! The three classes share the generic mask pair because the pair belongs to the
//! replicated-state container base, not to a specific component. What differs per
//! component is the registered member list its constructor builds.

use crate::framing::{Reader, WireError, Writer};
use crate::generated::{
    CodecEntitlementReplicatedState, CodecObjectivesReplicatedState, CodecTransmogReplicatedState,
};
use crate::state_bundle::StateComponent;

impl StateComponent for CodecObjectivesReplicatedState {
    const UID: &'static str = "codec.objectives-replicated-state";

    /// `wire-type:3857`, the alias the card itself states.
    fn type_indices() -> &'static [u64] {
        &[Self::OBJECTIVES_TYPE_INDEX]
    }

    fn type_index(&self) -> u64 {
        Self::OBJECTIVES_TYPE_INDEX
    }

    fn read_body(type_index: u64, reader: &mut Reader<'_>) -> Result<Self, WireError> {
        check(type_index, Self::OBJECTIVES_TYPE_INDEX)?;
        Self::read_from(reader)
    }

    fn write_body(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        self.write_to(writer)
    }
}

impl CodecObjectivesReplicatedState {
    /// `wire-type:3857`: the objectives replicated state, fragment key 22.
    pub const OBJECTIVES_TYPE_INDEX: u64 = 3857;
}

impl StateComponent for CodecEntitlementReplicatedState {
    const UID: &'static str = "codec.entitlement-replicated-state";

    /// `wire-type:3133`, the alias the card itself states.
    fn type_indices() -> &'static [u64] {
        &[Self::ENTITLEMENT_TYPE_INDEX]
    }

    fn type_index(&self) -> u64 {
        Self::ENTITLEMENT_TYPE_INDEX
    }

    fn read_body(type_index: u64, reader: &mut Reader<'_>) -> Result<Self, WireError> {
        check(type_index, Self::ENTITLEMENT_TYPE_INDEX)?;
        Self::read_from(reader)
    }

    fn write_body(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        self.write_to(writer)
    }
}

impl CodecEntitlementReplicatedState {
    /// `wire-type:3133`: the entitlement replicated state, fragment key 19.
    pub const ENTITLEMENT_TYPE_INDEX: u64 = 3133;
}

impl StateComponent for CodecTransmogReplicatedState {
    const UID: &'static str = "codec.transmog-replicated-state";

    /// `wire-type:5691`, the alias the card itself states.
    fn type_indices() -> &'static [u64] {
        &[Self::TRANSMOG_TYPE_INDEX]
    }

    fn type_index(&self) -> u64 {
        Self::TRANSMOG_TYPE_INDEX
    }

    fn read_body(type_index: u64, reader: &mut Reader<'_>) -> Result<Self, WireError> {
        check(type_index, Self::TRANSMOG_TYPE_INDEX)?;
        Self::read_from(reader)
    }

    fn write_body(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        self.write_to(writer)
    }
}

impl CodecTransmogReplicatedState {
    /// `wire-type:5691`: the transmog replicated state, fragment key 74.
    pub const TRANSMOG_TYPE_INDEX: u64 = 5691;
}

/// The three type indices the local-player record carries a layout for, ascending.
const LOCAL_PLAYER_TYPE_INDICES: [u64; 3] = [
    CodecEntitlementReplicatedState::ENTITLEMENT_TYPE_INDEX,
    CodecObjectivesReplicatedState::OBJECTIVES_TYPE_INDEX,
    CodecTransmogReplicatedState::TRANSMOG_TYPE_INDEX,
];

/// The replicated state of the local-player record, one variant per typed fragment.
///
/// The bundle is one record with one fragment per component slot, so a bundle
/// whose fragments are typed has more than one payload type. This enum is that
/// set: it is the frame's type parameter, and each variant delegates to the card
/// the fragment's type index binds.
#[derive(Debug, Clone, PartialEq)]
pub enum LocalPlayerState {
    /// Fragment key 19, type index 3133.
    Entitlement(CodecEntitlementReplicatedState),
    /// Fragment key 22, type index 3857.
    Objectives(CodecObjectivesReplicatedState),
    /// Fragment key 74, type index 5691.
    Transmog(CodecTransmogReplicatedState),
}

impl LocalPlayerState {
    /// The objectives component, if this fragment carries it.
    pub const fn objectives(&self) -> Option<&CodecObjectivesReplicatedState> {
        match self {
            Self::Objectives(value) => Some(value),
            Self::Entitlement(_) | Self::Transmog(_) => None,
        }
    }

    /// The objectives component, mutably, if this fragment carries it.
    pub fn objectives_mut(&mut self) -> Option<&mut CodecObjectivesReplicatedState> {
        match self {
            Self::Objectives(value) => Some(value),
            Self::Entitlement(_) | Self::Transmog(_) => None,
        }
    }

    /// The entitlement component, if this fragment carries it.
    pub const fn entitlement(&self) -> Option<&CodecEntitlementReplicatedState> {
        match self {
            Self::Entitlement(value) => Some(value),
            Self::Objectives(_) | Self::Transmog(_) => None,
        }
    }

    /// The transmog component, if this fragment carries it.
    pub const fn transmog(&self) -> Option<&CodecTransmogReplicatedState> {
        match self {
            Self::Transmog(value) => Some(value),
            Self::Entitlement(_) | Self::Objectives(_) => None,
        }
    }
}

impl StateComponent for LocalPlayerState {
    /// Not a card id: the bundle envelope is framing, not a card, so the family is
    /// tagged with the field it belongs to.
    const UID: &'static str = "envelope.state-bundle.local-player";

    fn type_indices() -> &'static [u64] {
        &LOCAL_PLAYER_TYPE_INDICES
    }

    fn type_index(&self) -> u64 {
        match self {
            Self::Entitlement(_) => CodecEntitlementReplicatedState::ENTITLEMENT_TYPE_INDEX,
            Self::Objectives(_) => CodecObjectivesReplicatedState::OBJECTIVES_TYPE_INDEX,
            Self::Transmog(_) => CodecTransmogReplicatedState::TRANSMOG_TYPE_INDEX,
        }
    }

    fn read_body(type_index: u64, reader: &mut Reader<'_>) -> Result<Self, WireError> {
        match type_index {
            CodecEntitlementReplicatedState::ENTITLEMENT_TYPE_INDEX => Ok(Self::Entitlement(
                CodecEntitlementReplicatedState::read_from(reader)?,
            )),
            CodecObjectivesReplicatedState::OBJECTIVES_TYPE_INDEX => Ok(Self::Objectives(
                CodecObjectivesReplicatedState::read_from(reader)?,
            )),
            CodecTransmogReplicatedState::TRANSMOG_TYPE_INDEX => Ok(Self::Transmog(
                CodecTransmogReplicatedState::read_from(reader)?,
            )),
            other => Err(WireError::UnsupportedType { type_index: other }),
        }
    }

    fn write_body(&self, writer: &mut Writer<'_>) -> Result<(), WireError> {
        match self {
            Self::Entitlement(value) => value.write_to(writer),
            Self::Objectives(value) => value.write_to(writer),
            Self::Transmog(value) => value.write_to(writer),
        }
    }
}

/// Refuse a type index the caller already knows is not this card's.
///
/// A single-card impl is reached through [`StateComponent::type_indices`], so the
/// index always matches; stating the refusal keeps the impl total, and keeps a
/// hand-written `read_body` call honest instead of silently reading the body as
/// the wrong card.
///
/// # Errors
/// Returns [`WireError::UnsupportedType`] when `found` is not `expected`.
fn check(found: u64, expected: u64) -> Result<(), WireError> {
    if found == expected {
        Ok(())
    } else {
        Err(WireError::UnsupportedType { type_index: found })
    }
}
