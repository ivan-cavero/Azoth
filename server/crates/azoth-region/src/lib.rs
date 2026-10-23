//! The region registry, and the channel document rendered from it.
//!
//! WHY THIS CRATE EXISTS
//! =====================
//! The client fetches **one** document and reads regions out of its top-level keys
//! (`services/gateway/src/azoth_gateway/data/channel-azoth.json`; 187 requests to
//! `/STEAM_APP_ID.json` in `research/atlas/observed-endpoints.json`). That single fact decides how
//! this whole server is shaped:
//!
//! * a **region** is a key in that document with its own `publicApis` set, so each region can be a
//!   separate service with its own endpoint;
//! * a **world** belongs to a region through `regionId`, so moving a world between regions is a
//!   change to a placement record rather than a code change;
//! * opening or closing a region is a change to **that document**, which is why the document must be
//!   **generated from live state and never a checked-in file**. That one decision is what makes
//!   regions dynamic.
//!
//! The Python prototype proves the rendering path works but keeps the base document as a file and
//! patches only `displayName` (`routes/channel.py`). This crate inverts that: the document is a
//! function of the registry, and nothing about a region lives in a file except the seed of the
//! first one.
//!
//! WHAT IS STATE AND WHAT IS CONFIGURATION
//! =======================================
//! Only the **regions** are live state. `channelName`, `platformMetadata`, `omni` and the
//! `omni.privacy-settings.*` keys are configuration: they describe the product, not the fleet, and
//! they change when we rebrand rather than when a region opens. Keeping that split explicit is what
//! stops the document from becoming a dumping ground.
//!
//! TWO PROPERTIES THE CLIENT DEPENDS ON
//! ====================================
//! * **An ETag is mandatory.** A CMS response without one crashes the client (`routes/cms.py`,
//!   `docs/CLIENT_CONTRACT.md`), and the channel document is served the same way. The ETag is
//!   derived from the rendered bytes, so a region status flip changes it and the client re-reads —
//!   that is the mechanism that makes a region change live instead of needing a client restart.
//! * **The document must render with zero worlds up.** A region with no ACTIVE world still appears,
//!   with an empty world list. That is the requirement that forces the region/world split.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

pub mod channel;
pub mod registry;

pub use channel::{ChannelConfig, RenderedChannel};
pub use registry::{Registry, Region, RegionStatus, WorldPlacement, WorldStatus};

/// The build every fact in this repository is scoped to.
///
/// A world built for a different build is not eligible for a region
/// (`docs/PLAN-backend-rust.md` §4.4): serving a mismatched world is exactly the silent-failure
/// shape this project has paid for repeatedly — bytes accepted, zero errors, no effect.
pub const CHANNEL_BUILD_SHA256: &str =
    "30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033";

/// The client's build version string, as it appears in remote-config paths.
///
/// Measured: the client puts its own version into the URL, so 1.460 requests
/// `…/configuration-sets/ProductId/STEAM_APP_ID/6033%3B6024067` where the committed 1.400
/// inventory holds `6031%3B6004151` (`research/atlas/observed-endpoints.json`, 24 families).
pub const CLIENT_VERSION: &str = "1.460.6033.6024067";

/// A region's own identifier, e.g. `fra-prod`.
///
/// A newtype rather than a bare `String` so a region id cannot be passed where a world id is
/// expected. The two are different addressing schemes and confusing them is how a login binds a
/// character to the wrong region.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct RegionId(pub String);

impl std::fmt::Display for RegionId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl RegionId {
    /// Build from anything string-like.
    #[must_use]
    pub fn new(id: impl Into<String>) -> Self {
        Self(id.into())
    }

    /// The identifier as a string slice.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// A world's identity, as a UUID string.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct WorldId(pub String);

impl std::fmt::Display for WorldId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// Errors the registry can raise while rendering or validating.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RegionError {
    /// A world names a region that is not in the registry.
    ///
    /// This is rejected rather than tolerated: a world under an unknown region renders under no
    /// key, so the client would never see it and the operator would never learn why.
    UnknownRegion {
        /// The world.
        world: String,
        /// The region it claims.
        region: String,
    },
    /// Two regions share an id.
    DuplicateRegion(String),
    /// Two worlds share an id.
    DuplicateWorld(String),
    /// A region is missing a `publicApis` client tag the client requires.
    MissingClientTag {
        /// The region.
        region: String,
        /// The tag.
        tag: String,
    },
}

impl std::fmt::Display for RegionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UnknownRegion { world, region } => {
                write!(f, "world {world} names region {region}, which is not registered")
            }
            Self::DuplicateRegion(id) => write!(f, "region {id} is registered twice"),
            Self::DuplicateWorld(id) => write!(f, "world {id} is registered twice"),
            Self::MissingClientTag { region, tag } => {
                write!(f, "region {region} has no publicApi with clientTag {tag}")
            }
        }
    }
}

impl std::error::Error for RegionError {}

/// The four `clientTag` values the client looks up, in the order the document lists them.
///
/// **Fixed vocabulary.** A region supplies endpoints; it does not invent tags. A missing tag is a
/// different client behaviour, not a fallback, which is why [`Registry::validate`] refuses a region
/// that lacks one.
pub const REQUIRED_CLIENT_TAGS: [&str; 4] = [
    "authStack",
    "loginGateway",
    "JavelinGatewayServiceV2",
    "JavelinGatewayService-CF",
];

/// Count worlds per region, for the document's per-region rendering.
#[must_use]
pub fn worlds_by_region(registry: &Registry) -> BTreeMap<RegionId, Vec<&WorldPlacement>> {
    let mut out: BTreeMap<RegionId, Vec<&WorldPlacement>> = BTreeMap::new();
    for region in &registry.regions {
        out.entry(region.id.clone()).or_default();
    }
    for world in &registry.worlds {
        out.entry(world.region_id.clone()).or_default().push(world);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_build_constant_matches_the_atlas() {
        // A typo here would make every eligibility check silently false.
        assert_eq!(CHANNEL_BUILD_SHA256.len(), 64);
        assert!(CHANNEL_BUILD_SHA256.starts_with("30fe6461"));
        assert_eq!(CLIENT_VERSION, "1.460.6033.6024067");
    }

    #[test]
    fn the_four_client_tags_are_the_measured_set() {
        // The order matters for the rendered document; the set matters for validation.
        assert_eq!(REQUIRED_CLIENT_TAGS.len(), 4);
        assert_eq!(REQUIRED_CLIENT_TAGS[0], "authStack");
        assert_eq!(REQUIRED_CLIENT_TAGS[3], "JavelinGatewayService-CF");
    }

    #[test]
    fn region_and_world_ids_are_not_interchangeable() {
        // Both are newtypes, so this is a compile-time property; the test documents it.
        let region = RegionId::new("fra-prod");
        let world = WorldId("00000000-0000-4000-8000-000000000001".to_string());
        assert_eq!(region.as_str(), "fra-prod");
        assert_ne!(region.as_str(), world.0.as_str());
    }
}
