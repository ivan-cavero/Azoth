//! The transport boundary, and the one place wire and domain meet.
//!
//! One inbound channel-0 body comes in: it is decoded by [`everfall_wire`],
//! converted to an [`everfall_sim`] domain value, decided there, and reported as
//! a [`DecisionRecord`]. Nothing is encoded on the way out, because the atlas
//! says there is no reply to encode.

use core::fmt;

use everfall_sim::{ActorId, ClientState, Decision, ObjectiveId, ObjectiveRequest, ScreenId, Sim};
use everfall_wire::WireError;
use everfall_wire::generated::{
    MsgObjectivesNotifyOpenUiScreen, MsgObjectivesSetObjectiveAutoPinning,
    MsgObjectivesUpdateTrackedObjectives, MsgServerEquipItem,
    MsgTerritoryDetectorAttemptTerritoryUnlock,
};

/// The reply wire id for the Objectives family, which has none.
///
/// Both atlas cards state it in their own words --
/// `msg.objectives-update-tracked-objectives` and
/// `msg.objectives-set-objective-auto-pinning` read "The server changes the
/// objectives replicated state; the Objectives family has no reply for this
/// request" -- and `research/atlas/meanings.md` records the registry check
/// behind it (2026-10-14): the family's only client facets are
/// `OnObjectiveWarning` (0xd6b), `OnMilestoneCorrection` (0xefc),
/// `SetObjectiveInstanceDisabled` (0x1634) and a debug one, and none of them
/// hands state back. So the answer is a state change, never a message.
pub const OBJECTIVES_REPLY_WIRE_ID: Option<u32> = None;

/// An inbound record this world cannot turn into a decision.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum DispatchError {
    /// A wire id outside the families this world maps.
    UnsupportedWireId {
        /// The wire id that arrived.
        wire_id: u32,
    },
    /// The body did not match its Atlas card.
    Malformed {
        /// The wire id that arrived.
        wire_id: u32,
        /// Which field of the card the body broke.
        source: WireError,
    },
}

impl fmt::Display for DispatchError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsupportedWireId { wire_id } => write!(f, "wire id {wire_id:#x} is not mapped"),
            Self::Malformed { wire_id, source } => {
                write!(f, "wire id {wire_id:#x} body: {source}")
            }
        }
    }
}

impl std::error::Error for DispatchError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::UnsupportedWireId { .. } => None,
            Self::Malformed { source, .. } => Some(source),
        }
    }
}

/// One decided request: who asked and what the world decided.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecisionRecord {
    /// The Atlas card that carried the request.
    pub card: &'static str,
    /// The sending facet's local id, kept so a reply could be addressed to it.
    pub facet_id: u64,
    /// The player the request names.
    pub actor: ActorId,
    /// The simulation's decision.
    pub decision: Decision,
}

/// The world process: it decodes, routes, decides, and records.
#[derive(Debug, Clone, Default)]
pub struct World {
    sim: Sim,
    client: ClientState,
}

impl World {
    /// A world whose objective definitions are `known`.
    pub fn new(known: impl IntoIterator<Item = ObjectiveId>) -> Self {
        Self {
            sim: Sim::new(known),
            client: ClientState::default(),
        }
    }

    /// The simulation this world drives.
    pub fn sim(&self) -> &Sim {
        &self.sim
    }

    /// The simulation this world drives, for a caller inside the process.
    pub fn sim_mut(&mut self) -> &mut Sim {
        &mut self.sim
    }

    /// The client-reported state this world holds.
    pub fn client_state(&self) -> &ClientState {
        &self.client
    }

    /// Route one inbound body to the simulation.
    ///
    /// # Errors
    /// Returns [`DispatchError::UnsupportedWireId`] for a family this world does
    /// not map, and [`DispatchError::Malformed`] when the body does not match
    /// its Atlas card.
    pub fn dispatch(&mut self, wire_id: u32, body: &[u8]) -> Result<DecisionRecord, DispatchError> {
        match wire_id {
            MsgObjectivesUpdateTrackedObjectives::WIRE_ID => {
                let decoded = MsgObjectivesUpdateTrackedObjectives::decode(body)
                    .map_err(|source| DispatchError::Malformed { wire_id, source })?;
                let actor = ActorId::new(decoded.local_actor_id_word0);
                let ids = decoded
                    .tracked_objective_ids
                    .into_iter()
                    .map(ObjectiveId::new)
                    .collect();
                let decision = self
                    .sim
                    .decide(actor, ObjectiveRequest::SetTrackedObjectives(ids));
                Ok(DecisionRecord {
                    card: MsgObjectivesUpdateTrackedObjectives::UID,
                    facet_id: decoded.local_facet_id,
                    actor,
                    decision,
                })
            }
            MsgObjectivesSetObjectiveAutoPinning::WIRE_ID => {
                let decoded = MsgObjectivesSetObjectiveAutoPinning::decode(body)
                    .map_err(|source| DispatchError::Malformed { wire_id, source })?;
                let actor = ActorId::new(decoded.local_actor_id_word0);
                let decision = self.sim.decide(
                    actor,
                    ObjectiveRequest::SetAutoPinning(decoded.auto_pinning_flags),
                );
                Ok(DecisionRecord {
                    card: MsgObjectivesSetObjectiveAutoPinning::UID,
                    facet_id: decoded.local_facet_id,
                    actor,
                    decision,
                })
            }
            MsgServerEquipItem::WIRE_ID => {
                let decoded = MsgServerEquipItem::decode(body)
                    .map_err(|source| DispatchError::Malformed { wire_id, source })?;
                let actor = ActorId::new(decoded.local_actor_id_word0);
                let decision = self.client.note_equip_request(actor);
                Ok(DecisionRecord {
                    card: MsgServerEquipItem::UID,
                    facet_id: decoded.local_facet_id,
                    actor,
                    decision,
                })
            }
            MsgObjectivesNotifyOpenUiScreen::WIRE_ID => {
                let decoded = MsgObjectivesNotifyOpenUiScreen::decode(body)
                    .map_err(|source| DispatchError::Malformed { wire_id, source })?;
                let actor = ActorId::new(decoded.local_actor_id_word0);
                let decision = self
                    .client
                    .note_screen(actor, ScreenId::new(decoded.screen_id));
                Ok(DecisionRecord {
                    card: MsgObjectivesNotifyOpenUiScreen::UID,
                    facet_id: decoded.local_facet_id,
                    actor,
                    decision,
                })
            }
            MsgTerritoryDetectorAttemptTerritoryUnlock::WIRE_ID => {
                let decoded = MsgTerritoryDetectorAttemptTerritoryUnlock::decode(body)
                    .map_err(|source| DispatchError::Malformed { wire_id, source })?;
                let actor = ActorId::new(decoded.local_actor_id_word0);
                let decision = self.client.note_unlock_attempt(actor);
                Ok(DecisionRecord {
                    card: MsgTerritoryDetectorAttemptTerritoryUnlock::UID,
                    facet_id: decoded.local_facet_id,
                    actor,
                    decision,
                })
            }
            other => Err(DispatchError::UnsupportedWireId { wire_id: other }),
        }
    }
}
