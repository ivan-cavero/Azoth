//! Domain types for Azoth's authoritative simulation.
//!
//! WHY THIS CRATE EXISTS
//! =====================
//! `azoth-wire` owns bytes. Apps must not invent gameplay meaning by sprinkling
//! `f32` offsets through `worldd`. Identities and transforms live here so the
//! sim and session layers can speak the game, and ontology concepts can name
//! the same types (`research/atlas/ontology/`).
//!
//! WHAT IT DELIBERATELY IS NOT
//! ===========================
//! No I/O, no DTLS, no fragment layouts. A type that needs a wire offset does
//! not belong here until a codec in `azoth-wire` owns that offset.

#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};

/// Stable character identity as the region/world ticket understands it.
///
/// Ontology: part of `flow.world-entry`. The ticket is authority for this id on
/// the strict V3 path (`azoth-session::LoginTicket`).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct CharacterId(pub String);

impl CharacterId {
    /// Borrow the raw id string (HTTP/ticket spelling).
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<String> for CharacterId {
    fn from(value: String) -> Self {
        Self(value)
    }
}

impl From<&str> for CharacterId {
    fn from(value: &str) -> Self {
        Self(value.to_owned())
    }
}

impl std::fmt::Display for CharacterId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(f)
    }
}

/// Persona the character belongs to (account-facing identity facet).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct PersonaId(pub String);

impl PersonaId {
    /// Borrow the raw persona id string.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<String> for PersonaId {
    fn from(value: String) -> Self {
        Self(value)
    }
}

impl From<&str> for PersonaId {
    fn from(value: &str) -> Self {
        Self(value.to_owned())
    }
}

/// Horizontal position as the protocol and map feed use it (2D; height derived).
///
/// Ontology: `sys.movement-authority`. Wire carries x/y; z is not in the measured
/// spawn payload encodings this project trusts.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Transform2 {
    /// World X (same axis as the wire claim).
    pub x: f32,
    /// World Y (same axis as the wire claim).
    pub y: f32,
}

impl Transform2 {
    /// Construct a 2D transform.
    #[must_use]
    pub const fn new(x: f32, y: f32) -> Self {
        Self { x, y }
    }
}

/// Opaque handle used by `SpawnActorsMsg` (one BE `u64` on the wire).
///
/// Ontology: `msg.spawn-actors`. **Meaning unproven** — do not equate with
/// [`ActorGuid`] without a second measured signal.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ActorId(pub u64);

/// 16-byte actor identity as carried in the local spawn record and (candidate)
/// as `AddActorMessage` head / `ClientAddEntryMsg` body.
///
/// Measured spawn template id: see `azoth-wire::spawn` / `spawn-template.json`
/// (`1a954abc4b3185bfbe37c3d8592618e0` on build 1.460). Mapping that head onto
/// wire 449 is still `candidate` until live unmarshal proves it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ActorGuid(pub [u8; 16]);

impl ActorGuid {
    /// Borrow the raw 16 bytes.
    #[must_use]
    pub fn as_bytes(&self) -> &[u8; 16] {
        &self.0
    }
}

impl From<[u8; 16]> for ActorGuid {
    fn from(value: [u8; 16]) -> Self {
        Self(value)
    }
}

/// World id as tickets and placement speak it (string today; opaque).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct WorldId(pub String);

impl WorldId {
    /// Borrow the raw world id.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<&str> for WorldId {
    fn from(value: &str) -> Self {
        Self(value.to_owned())
    }
}

/// Character + persona bound after a successful world entry.
///
/// Apps should thread this instead of parallel `String` fields when logging or
/// composing snapshots. Wire still carries strings; this is the domain view.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PlayerIdentity {
    /// Character admitted by the login ticket.
    pub character: CharacterId,
    /// Persona that owns the character.
    pub persona: PersonaId,
    /// World the ticket was minted for.
    pub world: WorldId,
}

impl PlayerIdentity {
    /// Build from ticket string fields.
    #[must_use]
    pub fn new(character: impl Into<CharacterId>, persona: impl Into<PersonaId>, world: impl Into<WorldId>) -> Self {
        Self {
            character: character.into(),
            persona: persona.into(),
            world: world.into(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn character_id_round_trips_display() {
        let id = CharacterId::from("char-1");
        assert_eq!(id.as_str(), "char-1");
        assert_eq!(id.to_string(), "char-1");
    }

    #[test]
    fn transform2_is_plain_data() {
        let t = Transform2::new(1.0, 2.0);
        assert_eq!(t.x, 1.0);
        assert_eq!(t.y, 2.0);
    }

    #[test]
    fn player_identity_holds_ids() {
        let p = PlayerIdentity::new("c1", "p1", "w1");
        assert_eq!(p.character.as_str(), "c1");
        assert_eq!(p.persona.as_str(), "p1");
        assert_eq!(p.world.as_str(), "w1");
    }
}
