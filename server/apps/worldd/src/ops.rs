//! Local ops command gate (until `opsd` owns the bus).
//!
//! WHY THIS MODULE EXISTS
//! ======================
//! Commands must be authorized before any world mutation. This module is the
//! in-process stand-in so `azoth-commands` is **called** from the world binary
//! and scenario tests can prove RBAC without a separate ops process yet.

use azoth_commands::{authorize, Command, Forbidden, Role};

/// Attempt to accept an ops command under `role`.
///
/// Does not apply side effects yet — only the authorization gate. Application
/// lands with the command bus (master plan P10).
///
/// # Errors
/// [`Forbidden`] when `role` is insufficient.
pub fn accept(role: Role, command: &Command) -> Result<(), Forbidden> {
    authorize(role, command)
}

#[cfg(test)]
mod tests {
    use super::*;
    use azoth_model::CharacterId;

    #[test]
    fn gm_cannot_grant_economy_items() {
        let cmd = Command::Grant {
            character: CharacterId::from("hero"),
            content_id: "item.ore".into(),
            qty: 3,
        };
        assert!(accept(Role::Gm, &cmd).is_err());
        assert!(accept(Role::Economy, &cmd).is_ok());
    }
}
