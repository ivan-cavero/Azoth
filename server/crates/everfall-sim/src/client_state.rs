//! Client-reported state the world records, and the rules that apply it.
//!
//! Three inbound families carry a report rather than a request with an answer:
//! the UI screen the client showed (`0xa39`), the equip request it made
//! (`0xf37`), and the territory-unlock attempt it made (`0x8f9`). Each family
//! has no reply message, so the server changes replicated state instead.
//!
//! The atlas states no legality condition for any of the three, so no rule here
//! rejects: the rule is the state write, and the decision is [`Decision::Accepted`].
//! Two of the identity fields (`item_id`, `unlock_token`) are `guid16` runs that
//! the codec keeps opaque; the boundary names the field but does not read the
//! bytes, so the rule records the report rather than inventing a meaning for an
//! unnamed run. `screen_id` is a plain `u32be` and is stored.

use std::collections::{BTreeMap, BTreeSet};

use crate::objectives::{ActorId, Decision};

/// A UI screen class id: the `u32be` field `0xa39` carries.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ScreenId(u32);

impl ScreenId {
    /// The screen id the client named.
    pub const fn new(value: u32) -> Self {
        Self(value)
    }

    /// The value the client named.
    pub const fn value(self) -> u32 {
        self.0
    }
}

impl From<u32> for ScreenId {
    fn from(value: u32) -> Self {
        Self::new(value)
    }
}

/// The client-reported state the world holds, one entry per player.
///
/// The sets keep only presence: an equip request or an unlock attempt is a
/// report with no condition attached, so there is nothing to hold beyond the
/// fact that it happened. The screen is the one report that carries a value the
/// card names, so it is stored.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ClientState {
    screens: BTreeMap<ActorId, ScreenId>,
    equip_requests: BTreeSet<ActorId>,
    unlock_attempts: BTreeSet<ActorId>,
}

impl ClientState {
    /// Record the screen the player just showed.
    pub fn note_screen(&mut self, actor: ActorId, screen: ScreenId) -> Decision {
        self.screens.insert(actor, screen);
        Decision::Accepted
    }

    /// The screen the player last showed, or `None` before their first report.
    pub fn screen(&self, actor: ActorId) -> Option<ScreenId> {
        self.screens.get(&actor).copied()
    }

    /// Record that the player asked to equip an item.
    pub fn note_equip_request(&mut self, actor: ActorId) -> Decision {
        self.equip_requests.insert(actor);
        Decision::Accepted
    }

    /// Whether the player has an equip request on record.
    pub fn has_equip_request(&self, actor: ActorId) -> bool {
        self.equip_requests.contains(&actor)
    }

    /// Record that the player attempted a territory unlock.
    pub fn note_unlock_attempt(&mut self, actor: ActorId) -> Decision {
        self.unlock_attempts.insert(actor);
        Decision::Accepted
    }

    /// Whether the player has a territory-unlock attempt on record.
    pub fn has_unlock_attempt(&self, actor: ActorId) -> bool {
        self.unlock_attempts.contains(&actor)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn screen_report_is_held_per_player() {
        let mut state = ClientState::default();
        assert_eq!(
            state.note_screen(ActorId::new(1), ScreenId::new(0xa112_6b78)),
            Decision::Accepted
        );
        assert_eq!(
            state.screen(ActorId::new(1)),
            Some(ScreenId::new(0xa112_6b78))
        );
        assert_eq!(state.screen(ActorId::new(2)), None);
    }

    #[test]
    fn equip_and_unlock_reports_are_presence_only() {
        let mut state = ClientState::default();
        assert_eq!(
            state.note_equip_request(ActorId::new(7)),
            Decision::Accepted
        );
        assert_eq!(
            state.note_unlock_attempt(ActorId::new(7)),
            Decision::Accepted
        );
        assert!(state.has_equip_request(ActorId::new(7)));
        assert!(state.has_unlock_attempt(ActorId::new(7)));
        assert!(!state.has_equip_request(ActorId::new(8)));
    }
}
