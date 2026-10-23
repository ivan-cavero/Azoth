//! The region and world registry: the live state the channel document is rendered from.
//!
//! WHY THIS IS NOT A FILE
//! ======================
//! The Python prototype reads `data/worlds.json` and hot-reloads it by mtime
//! (`routes/registry.py`). That is a good prototype and a bad design: it makes "open a region" a
//! file edit on a machine, which means the fleet's shape lives in a checkout rather than in the
//! service that owns it. This module is the same data with the ownership fixed — the registry is
//! state, and `regiond` is its single writer.
//!
//! WHAT IS AUTHORITATIVE HERE
//! ==========================
//! Only the **committed projection**. The world owns its own placement and publishes it; the region
//! stores what it was last told. That is the research's rule ("the world server owns topology and
//! placement; directories and gateways store committed location projections and cache forwarding
//! routes"), and it is why [`WorldPlacement`] carries a `placement_epoch`: a stale projection is
//! detectable rather than silently believed.

use crate::RegionError;
use crate::{RegionId, REQUIRED_CLIENT_TAGS, WorldId};
use serde::{Deserialize, Serialize};

/// Whether a region is accepting logins.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RegionStatus {
    /// Accepting logins and issuing tickets.
    Active,
    /// Listed, but refusing new logins. Existing sessions keep playing.
    Maintenance,
}

impl RegionStatus {
    /// The wire string the client parses.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Active => "ACTIVE",
            Self::Maintenance => "MAINTENANCE",
        }
    }
}

/// Whether a world can be allocated.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum WorldStatus {
    /// Eligible for new tickets.
    Active,
    /// Listed, not eligible.
    Maintenance,
    /// Refusing new tickets while existing players finish.
    Draining,
}

impl WorldStatus {
    /// The wire string the client parses.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Active => "ACTIVE",
            Self::Maintenance => "MAINTENANCE",
            Self::Draining => "DRAINING",
        }
    }
}

/// One entry of a region's `publicApis`.
///
/// The client looks these up by `clientTag`; everything else is metadata it tolerates but does not
/// need. `clientTag` is therefore the only required field.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PublicApi {
    /// One of [`REQUIRED_CLIENT_TAGS`].
    pub client_tag: String,
    /// The host (or host:port) the client talks to for this purpose.
    pub api_endpoint: String,
    /// The cloud region the endpoint lives in, when the original supplied one.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub aws_region: Option<String>,
    /// API version, when the original supplied one.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    /// Stage name, when the original supplied one.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stage: Option<String>,
}

/// A region: a key in the channel document with its own endpoint set.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Region {
    /// The document key, e.g. `fra-prod`.
    pub id: RegionId,
    /// What the client shows in the region dropdown.
    pub display_name: String,
    /// The localization key beside it, e.g. `@mm_eu_central`.
    pub localized_name: String,
    /// The pool id, `us-east-1:<uuid>`.
    ///
    /// **Not cosmetic.** The client uses it verbatim as a path segment in its remote-config
    /// requests (`…/configuration-sets/CognitoId/us-east-1:0de93f7c-…/versionless`, 155 hits in
    /// `research/atlas/observed-endpoints.json`), so it must be allocated when the region is
    /// created and never changed.
    pub pool_id: String,
    /// The region's API endpoints.
    pub public_apis: Vec<PublicApi>,
    /// Whether it is accepting logins.
    pub status: RegionStatus,
    /// The `omni.privacy-settings.*` values this region overrides, if any.
    ///
    /// A **Vec, not a map**, because these are flat dotted keys inside the region object whose
    /// order the served document fixes. A `BTreeMap` would sort them alphabetically and change the
    /// bytes, which the parity test catches and which no client-visible behaviour would reveal.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub privacy_settings: Vec<(String, String)>,
}

impl Region {
    /// Whether this region may issue a ticket right now.
    #[must_use]
    pub const fn accepts_logins(&self) -> bool {
        matches!(self.status, RegionStatus::Active)
    }

    /// The endpoint for `client_tag`, if the region supplies one.
    #[must_use]
    pub fn endpoint_for(&self, client_tag: &str) -> Option<&str> {
        self.public_apis
            .iter()
            .find(|api| api.client_tag == client_tag)
            .map(|api| api.api_endpoint.as_str())
    }
}

/// A world's placement: the region it belongs to, and where the client should connect.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorldPlacement {
    /// The world's UUID.
    pub id: WorldId,
    /// The internal name, e.g. `everfall`.
    pub name: String,
    /// What the client shows.
    pub display_name: String,
    /// Which region it belongs to. **This is the field a move changes.**
    pub region_id: RegionId,
    /// The world set it belongs to, which the client groups by.
    pub world_set: String,
    /// Whether it can be allocated.
    pub status: WorldStatus,
    /// `OpenWorld` or `FTUE`; the client maps anything else to `OpenWorld`.
    pub world_type: String,
    /// The client version this world serves.
    pub version: String,
    /// Maximum concurrent players.
    pub capacity: u32,
    /// The UDP `host:port` the client connects to for gameplay.
    ///
    /// This is the only place the client learns where the world is: the queue ticket carries it and
    /// the client speaks DTLS straight to it. A gateway hop never sees gameplay traffic.
    pub rep_address: String,
    /// The build this world was started for.
    pub build_sha256: String,
    /// Monotonic counter bumped on every placement change, so a stale projection is detectable.
    pub placement_epoch: u64,
    /// Current population, for allocation.
    #[serde(default)]
    pub population: u32,
}

impl WorldPlacement {
    /// Whether this world may be handed to a new login.
    ///
    /// A pure function of the projection, which is what makes it testable without a world running.
    #[must_use]
    pub fn is_eligible(&self, build_sha256: &str) -> bool {
        matches!(self.status, WorldStatus::Active)
            && self.build_sha256 == build_sha256
            && self.population < self.capacity
    }

    /// Remaining capacity.
    #[must_use]
    pub fn headroom(&self) -> u32 {
        self.capacity.saturating_sub(self.population)
    }
}

/// The registry: regions and world placements.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Registry {
    /// Every region, in the order the document should list them.
    pub regions: Vec<Region>,
    /// Every world placement.
    pub worlds: Vec<WorldPlacement>,
}

impl Registry {
    /// An empty registry. Renders a valid document with no regions, which is what a fresh
    /// deployment looks like.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a region, refusing a duplicate id.
    ///
    /// # Errors
    /// [`RegionError::DuplicateRegion`].
    pub fn add_region(&mut self, region: Region) -> Result<(), RegionError> {
        if self.regions.iter().any(|r| r.id == region.id) {
            return Err(RegionError::DuplicateRegion(region.id.0));
        }
        self.regions.push(region);
        Ok(())
    }

    /// Add a world placement, refusing a duplicate id.
    ///
    /// # Errors
    /// [`RegionError::DuplicateWorld`].
    pub fn add_world(&mut self, world: WorldPlacement) -> Result<(), RegionError> {
        if self.worlds.iter().any(|w| w.id == world.id) {
            return Err(RegionError::DuplicateWorld(world.id.0));
        }
        self.worlds.push(world);
        Ok(())
    }

    /// The region with `id`, if registered.
    #[must_use]
    pub fn region(&self, id: &RegionId) -> Option<&Region> {
        self.regions.iter().find(|r| &r.id == id)
    }

    /// Every world in `region`, in registration order.
    #[must_use]
    pub fn worlds_in(&self, region: &RegionId) -> Vec<&WorldPlacement> {
        self.worlds
            .iter()
            .filter(|w| &w.region_id == region)
            .collect()
    }

    /// Check the registry is renderable and allocatable.
    ///
    /// Run at startup and after every mutation. Each rule here is a failure that would otherwise
    /// show up as a client that silently never sees a world.
    ///
    /// # Errors
    /// [`RegionError::UnknownRegion`] for a world under an unregistered region, and
    /// [`RegionError::MissingClientTag`] for a region lacking a tag the client requires.
    pub fn validate(&self) -> Result<(), RegionError> {
        for world in &self.worlds {
            if self.region(&world.region_id).is_none() {
                return Err(RegionError::UnknownRegion {
                    world: world.id.0.clone(),
                    region: world.region_id.0.clone(),
                });
            }
        }
        for region in &self.regions {
            for tag in REQUIRED_CLIENT_TAGS {
                if region.endpoint_for(tag).is_none() {
                    return Err(RegionError::MissingClientTag {
                        region: region.id.0.clone(),
                        tag: tag.to_string(),
                    });
                }
            }
        }
        Ok(())
    }

    /// Allocate: the best eligible world in `region` for a new login.
    ///
    /// Ordering is by **headroom descending**, then by name, so the choice is deterministic: two
    /// identical registries always allocate the same world. Determinism matters because a
    /// non-deterministic allocator makes a load test unreproducible.
    #[must_use]
    pub fn allocate(&self, region: &RegionId, build_sha256: &str) -> Option<&WorldPlacement> {
        let mut candidates: Vec<&WorldPlacement> = self
            .worlds_in(region)
            .into_iter()
            .filter(|w| w.is_eligible(build_sha256))
            .collect();
        candidates.sort_by(|a, b| {
            b.headroom()
                .cmp(&a.headroom())
                .then_with(|| a.name.cmp(&b.name))
        });
        candidates.first().copied()
    }
}
