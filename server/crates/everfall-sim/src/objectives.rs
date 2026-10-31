//! Tracked objectives, pin flags, and the decision that applies one change.

use std::collections::{BTreeMap, BTreeSet};

/// Most tracked objectives one player may hold.
///
/// `msg.objectives-update-tracked-objectives`: "prefix-varint count (stated
/// <= 8)".
pub const TRACKED_LIMIT: usize = 8;

/// Most auto-pinning flags one player may hold.
///
/// `msg.objectives-set-objective-auto-pinning`: "prefix-varint count (stated
/// <= 36)".
pub const PIN_FLAG_LIMIT: usize = 36;

/// A player, as the requests address them.
///
/// This is the first 64 bits of the player's actor id: the atlas field
/// `local_actor_id_word0`, measured in every committed request head.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ActorId(u64);

impl ActorId {
    /// The player whose actor id starts with `word0`.
    pub const fn new(word0: u64) -> Self {
        Self(word0)
    }

    /// The first 64 bits of the actor id.
    pub const fn word0(self) -> u64 {
        self.0
    }
}

impl From<u64> for ActorId {
    fn from(word0: u64) -> Self {
        Self::new(word0)
    }
}

/// One objective the world can have a definition for.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ObjectiveId(u64);

impl ObjectiveId {
    /// The objective the client names with `value`.
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    /// The value the client named.
    pub const fn value(self) -> u64 {
        self.0
    }
}

impl From<u64> for ObjectiveId {
    fn from(value: u64) -> Self {
        Self::new(value)
    }
}

/// A change a client asked the world to make.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ObjectiveRequest {
    /// Replace the player's tracked set: these ids, in this order.
    SetTrackedObjectives(Vec<ObjectiveId>),
    /// Replace the player's auto-pinning flags: one per journal slot.
    SetAutoPinning(Vec<bool>),
}

/// What the world dropped from a request it otherwise applied.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Dropped {
    /// Ids listed more than once; the first occurrence was kept.
    pub duplicates: usize,
    /// Ids this world has no definition for, so there is nothing to track.
    pub unknown: usize,
}

/// Why a request was refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Rejection {
    /// More tracked ids than [`TRACKED_LIMIT`].
    TooManyTrackedObjectives {
        /// Ids the request carried, duplicates included.
        offered: usize,
        /// The atlas cap.
        limit: usize,
    },
    /// More pin flags than [`PIN_FLAG_LIMIT`].
    TooManyPinFlags {
        /// Flags the request carried.
        offered: usize,
        /// The atlas cap.
        limit: usize,
    },
}

/// What the world decided about one request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Decision {
    /// Applied exactly as asked.
    Accepted,
    /// Applied after the world changed it.
    Corrected(Dropped),
    /// Not applied. The player's state is unchanged.
    Rejected(Rejection),
}

/// One player's objective state, as the world holds it.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TrackedObjectives {
    tracked: Vec<ObjectiveId>,
    pin_flags: Vec<bool>,
}

impl TrackedObjectives {
    /// The tracked ids, in the order the world holds them.
    pub fn tracked(&self) -> &[ObjectiveId] {
        &self.tracked
    }

    /// The auto-pinning flags, one per journal slot.
    pub fn pin_flags(&self) -> &[bool] {
        &self.pin_flags
    }
}

/// The objective half of the world: which objectives exist, and what each
/// player holds.
#[derive(Debug, Clone, Default)]
pub struct Sim {
    known: BTreeSet<ObjectiveId>,
    players: BTreeMap<ActorId, TrackedObjectives>,
}

impl Sim {
    /// A world that has definitions for `known` and has seen no player yet.
    pub fn new(known: impl IntoIterator<Item = ObjectiveId>) -> Self {
        Self {
            known: known.into_iter().collect(),
            players: BTreeMap::new(),
        }
    }

    /// Whether this world has a definition for `id`.
    pub fn knows(&self, id: ObjectiveId) -> bool {
        self.known.contains(&id)
    }

    /// The player's objective state, or `None` before their first applied
    /// request.
    pub fn tracked(&self, actor: ActorId) -> Option<&TrackedObjectives> {
        self.players.get(&actor)
    }

    /// Decide one change and apply it unless it is rejected.
    pub fn decide(&mut self, actor: ActorId, request: ObjectiveRequest) -> Decision {
        match request {
            ObjectiveRequest::SetTrackedObjectives(ids) => self.set_tracked(actor, ids),
            ObjectiveRequest::SetAutoPinning(flags) => self.set_pin_flags(actor, flags),
        }
    }

    fn set_tracked(&mut self, actor: ActorId, offered: Vec<ObjectiveId>) -> Decision {
        // The cap is checked against what was asked, duplicates included: an
        // over-cap list is not the list the client meant, so the world refuses it
        // whole rather than guessing which ids to keep.
        if offered.len() > TRACKED_LIMIT {
            return Decision::Rejected(Rejection::TooManyTrackedObjectives {
                offered: offered.len(),
                limit: TRACKED_LIMIT,
            });
        }

        let mut kept: Vec<ObjectiveId> = Vec::with_capacity(offered.len());
        let mut duplicates = 0_usize;
        for id in offered {
            if kept.contains(&id) {
                duplicates += 1;
            } else {
                kept.push(id);
            }
        }

        let offered_count = kept.len();
        kept.retain(|id| self.known.contains(id));
        let dropped = Dropped {
            duplicates,
            unknown: offered_count - kept.len(),
        };

        self.players.entry(actor).or_default().tracked = kept;
        if dropped.duplicates == 0 && dropped.unknown == 0 {
            Decision::Accepted
        } else {
            Decision::Corrected(dropped)
        }
    }

    fn set_pin_flags(&mut self, actor: ActorId, offered: Vec<bool>) -> Decision {
        if offered.len() > PIN_FLAG_LIMIT {
            return Decision::Rejected(Rejection::TooManyPinFlags {
                offered: offered.len(),
                limit: PIN_FLAG_LIMIT,
            });
        }
        self.players.entry(actor).or_default().pin_flags = offered;
        Decision::Accepted
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn known(count: u64) -> Vec<ObjectiveId> {
        (0..count).map(ObjectiveId::new).collect()
    }

    fn world_with(ids: &[ObjectiveId]) -> Sim {
        Sim::new(ids.iter().copied())
    }

    #[test]
    fn tracked_update_accepts_eight_known_ids() {
        let ids = known(8);
        let mut sim = world_with(&ids);
        let decision = sim.decide(
            ActorId::new(1),
            ObjectiveRequest::SetTrackedObjectives(ids.clone()),
        );
        assert_eq!(decision, Decision::Accepted);
        assert_eq!(
            sim.tracked(ActorId::new(1))
                .expect("state after accept")
                .tracked(),
            ids.as_slice(),
            "the eight ids are held in the order asked"
        );
    }

    #[test]
    fn tracked_update_accepts_an_empty_set() {
        let mut sim = world_with(&known(2));
        let decision = sim.decide(
            ActorId::new(1),
            ObjectiveRequest::SetTrackedObjectives(Vec::new()),
        );
        assert_eq!(decision, Decision::Accepted);
        assert_eq!(
            sim.tracked(ActorId::new(1))
                .expect("state after accept")
                .tracked(),
            &[],
            "an empty tracked set is legal and is not the same as no state"
        );
    }

    #[test]
    fn tracked_update_collapses_duplicates_keeping_the_first_order() {
        let ids = known(3);
        let mut sim = world_with(&ids);
        let decision = sim.decide(
            ActorId::new(1),
            ObjectiveRequest::SetTrackedObjectives(vec![ids[0], ids[1], ids[0]]),
        );
        assert_eq!(
            decision,
            Decision::Corrected(Dropped {
                duplicates: 1,
                unknown: 0
            })
        );
        assert_eq!(
            sim.tracked(ActorId::new(1)).expect("state").tracked(),
            &[ids[0], ids[1]],
            "a duplicate collapses onto its first position"
        );
    }

    #[test]
    fn tracked_update_drops_unknown_ids() {
        let ids = known(2);
        let stranger = ObjectiveId::new(0xdead_beef);
        let mut sim = world_with(&ids);
        let decision = sim.decide(
            ActorId::new(1),
            ObjectiveRequest::SetTrackedObjectives(vec![ids[0], stranger, ids[1]]),
        );
        assert_eq!(
            decision,
            Decision::Corrected(Dropped {
                duplicates: 0,
                unknown: 1
            })
        );
        assert_eq!(
            sim.tracked(ActorId::new(1)).expect("state").tracked(),
            &[ids[0], ids[1]],
            "an id this world cannot resolve is not trackable"
        );
    }

    #[test]
    fn correction_reports_both_drops_at_once() {
        let ids = known(1);
        let mut sim = world_with(&ids);
        let decision = sim.decide(
            ActorId::new(1),
            ObjectiveRequest::SetTrackedObjectives(vec![
                ids[0],
                ids[0],
                ObjectiveId::new(0xdead_beef),
            ]),
        );
        assert_eq!(
            decision,
            Decision::Corrected(Dropped {
                duplicates: 1,
                unknown: 1
            })
        );
        assert_eq!(
            sim.tracked(ActorId::new(1)).expect("state").tracked(),
            &[ids[0]]
        );
    }

    #[test]
    fn tracked_update_rejects_nine_ids_and_creates_no_state() {
        let ids = known(9);
        let mut sim = world_with(&ids);
        let decision = sim.decide(ActorId::new(1), ObjectiveRequest::SetTrackedObjectives(ids));
        assert_eq!(
            decision,
            Decision::Rejected(Rejection::TooManyTrackedObjectives {
                offered: 9,
                limit: TRACKED_LIMIT
            })
        );
        assert!(
            sim.tracked(ActorId::new(1)).is_none(),
            "a refused request must not mint a player record"
        );
    }

    #[test]
    fn a_rejected_update_leaves_the_previous_state_alone() {
        let ids = known(9);
        let mut sim = world_with(&ids);
        let accepted = sim.decide(
            ActorId::new(1),
            ObjectiveRequest::SetTrackedObjectives(vec![ids[0], ids[1]]),
        );
        assert_eq!(accepted, Decision::Accepted);

        let rejected = sim.decide(
            ActorId::new(1),
            ObjectiveRequest::SetTrackedObjectives(ids.clone()),
        );
        assert!(matches!(rejected, Decision::Rejected(_)));
        assert_eq!(
            sim.tracked(ActorId::new(1)).expect("state").tracked(),
            &[ids[0], ids[1]],
            "a refusal is not an instruction to clear the set"
        );
    }

    #[test]
    fn pinning_accepts_thirty_six_flags() {
        let mut sim = Sim::new([]);
        let mut flags = vec![false; PIN_FLAG_LIMIT];
        flags[0] = true;
        flags[PIN_FLAG_LIMIT - 1] = true;
        let decision = sim.decide(
            ActorId::new(1),
            ObjectiveRequest::SetAutoPinning(flags.clone()),
        );
        assert_eq!(decision, Decision::Accepted);
        assert_eq!(
            sim.tracked(ActorId::new(1)).expect("state").pin_flags(),
            flags.as_slice()
        );
    }

    #[test]
    fn pinning_rejects_thirty_seven_flags_and_creates_no_state() {
        let mut sim = Sim::new([]);
        let decision = sim.decide(
            ActorId::new(1),
            ObjectiveRequest::SetAutoPinning(vec![false; PIN_FLAG_LIMIT + 1]),
        );
        assert_eq!(
            decision,
            Decision::Rejected(Rejection::TooManyPinFlags {
                offered: 37,
                limit: PIN_FLAG_LIMIT
            })
        );
        assert!(sim.tracked(ActorId::new(1)).is_none());
    }

    #[test]
    fn tracked_ids_and_pin_flags_are_separate_state() {
        let ids = known(2);
        let mut sim = world_with(&ids);
        assert_eq!(
            sim.decide(
                ActorId::new(1),
                ObjectiveRequest::SetTrackedObjectives(ids.clone())
            ),
            Decision::Accepted
        );
        assert_eq!(
            sim.decide(
                ActorId::new(1),
                ObjectiveRequest::SetAutoPinning(vec![true, false])
            ),
            Decision::Accepted
        );
        let state = sim.tracked(ActorId::new(1)).expect("state");
        assert_eq!(state.tracked(), ids.as_slice());
        assert_eq!(state.pin_flags(), &[true, false]);
    }

    #[test]
    fn players_hold_independent_state() {
        let ids = known(2);
        let mut sim = world_with(&ids);
        assert_eq!(
            sim.decide(
                ActorId::new(1),
                ObjectiveRequest::SetTrackedObjectives(vec![ids[0]])
            ),
            Decision::Accepted
        );
        assert_eq!(
            sim.decide(
                ActorId::new(2),
                ObjectiveRequest::SetTrackedObjectives(vec![ids[1]])
            ),
            Decision::Accepted
        );
        assert_eq!(
            sim.tracked(ActorId::new(1)).expect("player 1").tracked(),
            &[ids[0]]
        );
        assert_eq!(
            sim.tracked(ActorId::new(2)).expect("player 2").tracked(),
            &[ids[1]]
        );
    }
}
