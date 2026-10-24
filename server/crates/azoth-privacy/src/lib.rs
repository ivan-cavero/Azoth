//! Player data visibility — default deny.
//!
//! WHY THIS CRATE EXISTS
//! =====================
//! Public `/v1/players/…` reads must not leak inventory or online status because
//! a route forgot an `if`. Policy is evaluated **before** the read model.
//! See master plan §4.3 and `docs/SECURITY.md`.

#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};

/// Who may see a field class.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Visibility {
    /// Anyone authenticated or anonymous public surface.
    Public,
    /// Only the owner's friends list (friend graph later).
    Friends,
    /// Only the owner (and audited ops bypass).
    Private,
}

/// Field classes the API can request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FieldClass {
    /// Online / in-world presence bit.
    OnlineStatus,
    /// Character list on the account.
    CharacterList,
    /// Level / gear score summary.
    LevelGear,
    /// Inventory / equipment detail.
    InventoryDetail,
    /// Rankings participation.
    Rankings,
}

/// Per-account privacy knobs (defaults are private-leaning).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PrivacySettings {
    /// Online status visibility.
    pub online_status: Visibility,
    /// Character list visibility.
    pub character_list: Visibility,
    /// Level / gear visibility.
    pub level_gear: Visibility,
    /// Inventory detail — never `Public` by default policy.
    pub inventory_detail: Visibility,
    /// Opt into rankings.
    pub rankings_opt_in: bool,
}

impl Default for PrivacySettings {
    fn default() -> Self {
        Self {
            online_status: Visibility::Friends,
            character_list: Visibility::Private,
            level_gear: Visibility::Private,
            inventory_detail: Visibility::Private,
            rankings_opt_in: false,
        }
    }
}

impl PrivacySettings {
    /// Visibility configured for a field class.
    #[must_use]
    pub fn visibility_for(&self, field: FieldClass) -> Visibility {
        match field {
            FieldClass::OnlineStatus => self.online_status,
            FieldClass::CharacterList => self.character_list,
            FieldClass::LevelGear => self.level_gear,
            FieldClass::InventoryDetail => self.inventory_detail,
            FieldClass::Rankings => {
                if self.rankings_opt_in {
                    Visibility::Public
                } else {
                    Visibility::Private
                }
            }
        }
    }
}

/// Relationship of the viewer to the profile owner.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Viewer {
    /// Anonymous or unrelated account.
    Stranger,
    /// On the owner's friends list.
    Friend,
    /// The owner themselves.
    Self_,
    /// Operator with audit bypass (still logged upstream).
    Ops,
}

/// Whether `viewer` may read `field` under `settings`.
///
/// Inventory is never visible as `Public` even if misconfigured — harden here.
#[must_use]
pub fn allows(settings: &PrivacySettings, viewer: Viewer, field: FieldClass) -> bool {
    if matches!(viewer, Viewer::Ops | Viewer::Self_) {
        return true;
    }
    let mut vis = settings.visibility_for(field);
    if field == FieldClass::InventoryDetail && vis == Visibility::Public {
        vis = Visibility::Private;
    }
    match vis {
        Visibility::Public => true,
        Visibility::Friends => matches!(viewer, Viewer::Friend),
        Visibility::Private => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_denies_stranger_inventory_and_characters() {
        let s = PrivacySettings::default();
        assert!(!allows(&s, Viewer::Stranger, FieldClass::InventoryDetail));
        assert!(!allows(&s, Viewer::Stranger, FieldClass::CharacterList));
        assert!(allows(&s, Viewer::Self_, FieldClass::InventoryDetail));
    }

    #[test]
    fn public_inventory_misconfig_is_clamped() {
        let mut s = PrivacySettings::default();
        s.inventory_detail = Visibility::Public;
        assert!(!allows(&s, Viewer::Stranger, FieldClass::InventoryDetail));
        s.online_status = Visibility::Friends;
        assert!(allows(&s, Viewer::Friend, FieldClass::OnlineStatus));
        assert!(!allows(&s, Viewer::Stranger, FieldClass::OnlineStatus));
    }

    #[test]
    fn rankings_require_opt_in() {
        let mut s = PrivacySettings::default();
        assert!(!allows(&s, Viewer::Stranger, FieldClass::Rankings));
        s.rankings_opt_in = true;
        assert!(allows(&s, Viewer::Stranger, FieldClass::Rankings));
    }
}
