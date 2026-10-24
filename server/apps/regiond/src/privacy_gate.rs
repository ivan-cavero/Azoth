//! Privacy evaluation for any future public player read on regiond.
//!
//! Calls [`azoth_privacy::allows`] so the crate is on the region binary's
//! dependency graph and cannot rot unused. Routes that expose player fields
//! must go through [`may_read`].

use azoth_privacy::{allows, FieldClass, PrivacySettings, Viewer};

/// Whether a viewer may read `field` for an owner with `settings`.
#[must_use]
pub fn may_read(settings: &PrivacySettings, viewer: Viewer, field: FieldClass) -> bool {
    allows(settings, viewer, field)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stranger_blocked_from_private_character_list() {
        let settings = PrivacySettings::default();
        assert!(!may_read(
            &settings,
            Viewer::Stranger,
            FieldClass::CharacterList
        ));
    }
}
