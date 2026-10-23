//! The registry's rules, as integration tests.
//!
//! WHY THESE LIVE HERE AND NOT IN THE MODULE
//! =========================================
//! They exercise only the public API, and `registry.rs` is close to the workspace's 400-line limit
//! — a limit that exists because a file past it usually means a boundary is wrong. Keeping the
//! rules next to the code was nice; keeping the code reviewable is more important, and an
//! integration test is the honest form for assertions that need nothing private.
//!
//! Each rule here is a failure that would otherwise reach a player as "the world list is empty" or
//! "the login went to the wrong region", with nothing in a log to explain it.

use azoth_region::registry::{
    PublicApi, Region, RegionStatus, Registry, WorldPlacement, WorldStatus,
};
use azoth_region::{RegionError, RegionId, WorldId};

fn api(tag: &str, host: &str) -> PublicApi {
    PublicApi {
        client_tag: tag.to_string(),
        api_endpoint: host.to_string(),
        aws_region: None,
        version: None,
        stage: None,
    }
}

fn region(id: &str) -> Region {
    Region {
        id: RegionId::new(id),
        display_name: "Test".to_string(),
        localized_name: "@mm_test".to_string(),
        pool_id: "us-east-1:00000000-0000-4000-8000-000000000000".to_string(),
        public_apis: azoth_region::REQUIRED_CLIENT_TAGS
            .iter()
            .map(|tag| api(tag, "127.0.0.1"))
            .collect(),
        status: RegionStatus::Active,
        privacy_settings: Vec::new(),
    }
}

fn world(id: &str, region_id: &str, population: u32, capacity: u32) -> WorldPlacement {
    WorldPlacement {
        id: WorldId(id.to_string()),
        name: format!("w{id}"),
        display_name: format!("W{id}"),
        region_id: RegionId::new(region_id),
        world_set: region_id.to_string(),
        status: WorldStatus::Active,
        world_type: "OpenWorld".to_string(),
        version: azoth_region::CLIENT_VERSION.to_string(),
        capacity,
        rep_address: "127.0.0.1:9000".to_string(),
        build_sha256: azoth_region::CHANNEL_BUILD_SHA256.to_string(),
        placement_epoch: 1,
        population,
    }
}

#[test]
fn an_empty_registry_is_valid() {
    // A fresh deployment renders a document with no regions rather than failing.
    assert!(Registry::new().validate().is_ok());
}

#[test]
fn refuses_a_duplicate_region() {
    let mut registry = Registry::new();
    registry.add_region(region("fra-prod")).expect("first");
    let err = registry.add_region(region("fra-prod")).expect_err("must fail");
    assert!(matches!(err, RegionError::DuplicateRegion(_)), "{err}");
}

#[test]
fn refuses_a_world_under_an_unknown_region() {
    let mut registry = Registry::new();
    registry
        .add_world(world("1", "nowhere", 0, 10))
        .expect("adds");
    let err = registry.validate().expect_err("must fail");
    assert!(matches!(err, RegionError::UnknownRegion { .. }), "{err}");
}

#[test]
fn refuses_a_region_missing_a_client_tag() {
    let mut registry = Registry::new();
    let mut r = region("fra-prod");
    r.public_apis.retain(|a| a.client_tag != "JavelinGatewayService-CF");
    registry.add_region(r).expect("adds");
    let err = registry.validate().expect_err("must fail");
    assert!(
        matches!(err, RegionError::MissingClientTag { ref tag, .. } if tag == "JavelinGatewayService-CF"),
        "{err}"
    );
}

#[test]
fn a_world_for_another_build_is_not_eligible() {
    let mut registry = Registry::new();
    registry.add_region(region("fra-prod")).expect("adds");
    let mut w = world("1", "fra-prod", 0, 10);
    w.build_sha256 = "8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e".to_string();
    registry.add_world(w).expect("adds");
    assert!(
        registry
            .allocate(&RegionId::new("fra-prod"), azoth_region::CHANNEL_BUILD_SHA256)
            .is_none(),
        "a 1.400 world must never be handed a 1.460 client"
    );
}

#[test]
fn a_full_world_is_not_eligible() {
    let mut registry = Registry::new();
    registry.add_region(region("fra-prod")).expect("adds");
    registry
        .add_world(world("1", "fra-prod", 10, 10))
        .expect("adds");
    assert!(
        registry
            .allocate(&RegionId::new("fra-prod"), azoth_region::CHANNEL_BUILD_SHA256)
            .is_none()
    );
}

#[test]
fn allocation_prefers_headroom_then_name() {
    let mut registry = Registry::new();
    registry.add_region(region("fra-prod")).expect("adds");
    registry.add_world(world("a", "fra-prod", 5, 10)).expect("adds"); // 5 free
    registry.add_world(world("b", "fra-prod", 1, 10)).expect("adds"); // 9 free
    registry.add_world(world("c", "fra-prod", 1, 10)).expect("adds"); // 9 free, name "wc"
    let chosen = registry
        .allocate(&RegionId::new("fra-prod"), azoth_region::CHANNEL_BUILD_SHA256)
        .expect("one is eligible");
    // 9 free beats 5; between the two 9s, "wb" < "wc".
    assert_eq!(chosen.name, "wb");
}

#[test]
fn allocation_is_deterministic() {
    let mut registry = Registry::new();
    registry.add_region(region("fra-prod")).expect("adds");
    for (i, pop) in [3u32, 3, 3].iter().enumerate() {
        registry
            .add_world(world(&format!("{i}"), "fra-prod", *pop, 10))
            .expect("adds");
    }
    let first = registry
        .allocate(&RegionId::new("fra-prod"), azoth_region::CHANNEL_BUILD_SHA256)
        .map(|w| w.id.clone());
    for _ in 0..10 {
        let again = registry
            .allocate(&RegionId::new("fra-prod"), azoth_region::CHANNEL_BUILD_SHA256)
            .map(|w| w.id.clone());
        assert_eq!(first, again, "allocation must not depend on iteration luck");
    }
}

#[test]
fn a_draining_world_is_not_eligible() {
    let mut registry = Registry::new();
    registry.add_region(region("fra-prod")).expect("adds");
    let mut w = world("1", "fra-prod", 0, 10);
    w.status = WorldStatus::Draining;
    registry.add_world(w).expect("adds");
    assert!(
        registry
            .allocate(&RegionId::new("fra-prod"), azoth_region::CHANNEL_BUILD_SHA256)
            .is_none()
    );
}

#[test]
fn a_maintenance_region_still_lists_its_worlds() {
    let mut registry = Registry::new();
    let mut r = region("fra-prod");
    r.status = RegionStatus::Maintenance;
    registry.add_region(r).expect("adds");
    registry.add_world(world("1", "fra-prod", 0, 10)).expect("adds");
    // The world is still in the registry; the region just refuses logins.
    assert_eq!(registry.worlds_in(&RegionId::new("fra-prod")).len(), 1);
    assert!(!registry.region(&RegionId::new("fra-prod")).expect("present").accepts_logins());
}
