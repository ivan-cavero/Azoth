//! Typed commands for the ops / GM bus.
//!
//! WHY THIS CRATE EXISTS
//! =====================
//! Admin mutations must not be free-form strings inside `worldd`. Every kick,
//! ban, grant, or teleport is a value that declares the minimum [`Role`] and
//! the resource it touches. `opsd` (later) authenticates; this crate only
//! answers "may this role run this command?"
//!
//! Ontology: future `cmd.*` concepts. Not decorative — [`authorize`] is the
//! gate callers must use before applying side effects.

#![forbid(unsafe_code)]

use azoth_model::CharacterId;
use serde::{Deserialize, Serialize};

/// Operator / player capability level (lowest → highest).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    /// Read-only observer.
    Viewer,
    /// Kick / mute within policy.
    Moderator,
    /// In-world GM tools.
    Gm,
    /// Economy grants / ledger.
    Economy,
    /// Full realm admin.
    Admin,
    /// Owner break-glass.
    Owner,
}

/// A command that may mutate the realm. Extend deliberately; each variant needs
/// an ontology uid when wired to the bus.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Command {
    /// Disconnect a character's live session.
    Kick {
        /// Target character.
        character: CharacterId,
        /// Operator-visible reason (audited).
        reason: String,
    },
    /// Ban an account / persona (store applies; this is the intent).
    Ban {
        /// Target character (resolved to account by ops).
        character: CharacterId,
        /// Operator-visible reason.
        reason: String,
    },
    /// Grant an item or currency (economy role).
    Grant {
        /// Target character.
        character: CharacterId,
        /// Content id (stable string until content crate owns typed ids).
        content_id: String,
        /// Quantity.
        qty: u32,
    },
}

impl Command {
    /// Minimum role that may attempt this command.
    #[must_use]
    pub const fn min_role(&self) -> Role {
        match self {
            Self::Kick { .. } => Role::Moderator,
            Self::Ban { .. } => Role::Admin,
            Self::Grant { .. } => Role::Economy,
        }
    }

    /// Ontology-ish purpose tag for logs (stable string until cmd.* files land).
    #[must_use]
    pub const fn purpose(&self) -> &'static str {
        match self {
            Self::Kick { .. } => "cmd.kick",
            Self::Ban { .. } => "cmd.ban",
            Self::Grant { .. } => "cmd.grant",
        }
    }
}

/// Error when a role is too weak for a command.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Forbidden {
    /// Role that attempted the command.
    pub role: Role,
    /// Role required.
    pub required: Role,
    /// Command purpose tag.
    pub purpose: &'static str,
}

/// Return `Ok(())` if `role` may run `command`.
///
/// # Errors
/// [`Forbidden`] when the role is below [`Command::min_role`].
pub fn authorize(role: Role, command: &Command) -> Result<(), Forbidden> {
    let required = command.min_role();
    if role >= required {
        Ok(())
    } else {
        Err(Forbidden {
            role,
            required,
            purpose: command.purpose(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn moderator_can_kick_but_not_ban() {
        let kick = Command::Kick {
            character: CharacterId::from("c1"),
            reason: "afk".into(),
        };
        let ban = Command::Ban {
            character: CharacterId::from("c1"),
            reason: "cheat".into(),
        };
        assert!(authorize(Role::Moderator, &kick).is_ok());
        assert!(authorize(Role::Moderator, &ban).is_err());
        assert!(authorize(Role::Admin, &ban).is_ok());
    }

    #[test]
    fn grant_requires_economy() {
        let grant = Command::Grant {
            character: CharacterId::from("c1"),
            content_id: "item.wood".into(),
            qty: 1,
        };
        assert!(authorize(Role::Gm, &grant).is_err());
        assert!(authorize(Role::Economy, &grant).is_ok());
    }
}
