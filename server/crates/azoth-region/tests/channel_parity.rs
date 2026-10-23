//! Parity between the Rust channel renderer and the Python gateway's.
//!
//! WHAT THIS PROVES
//! ================
//! That the document the client fetches before it can do anything — `/STEAM_APP_ID.json`, 187
//! requests in the measured inventory — is rendered by the Rust code **byte for byte** as the
//! prototype renders it, for the same registry. Not "equivalent JSON": the same bytes.
//!
//! Byte equality is the right bar here because the renderer's whole job is to be boring. Any
//! difference means either a missing key, a wrong type, a changed order or a formatting drift, and
//! all four are things a reviewer should see rather than infer from a semantic comparison that
//! would pass on all of them.
//!
//! WHAT IT DOES NOT PROVE
//! ======================
//! Nothing about the ETag matching. It deliberately does not: the prototype uses MD5 and this uses
//! FNV-1a 64. The client requires an ETag that *changes when the body changes*, not a particular
//! algorithm, and a non-cryptographic digest is cheaper on a route the client polls. The test
//! asserts the property that matters — stability for identical bytes and change for different ones
//! — in the crate's unit tests.

use azoth_region::channel::{ChannelConfig, render};
use azoth_region::registry::{Registry, Region, RegionStatus, PublicApi};
use azoth_region::RegionId;
use serde_json::Value;

const FIXTURE: &str = include_str!("fixtures/channel-parity.json");

fn fixture() -> Value {
    serde_json::from_str(FIXTURE).expect("the fixture must be valid JSON")
}

/// Build the registry the fixture describes.
fn registry_from(value: &Value) -> Registry {
    let mut registry = Registry::new();
    for region in value["registry"]["regions"].as_array().expect("regions") {
        let privacy: Vec<(String, String)> = region["privacy_settings"]
            .as_object()
            .map(|map| {
                map.iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect()
            })
            .unwrap_or_default();
        let public_apis: Vec<PublicApi> = region["public_apis"]
            .as_array()
            .expect("public_apis")
            .iter()
            .map(|api| PublicApi {
                client_tag: api["client_tag"].as_str().unwrap_or_default().to_string(),
                api_endpoint: api["api_endpoint"].as_str().unwrap_or_default().to_string(),
                aws_region: api["aws_region"].as_str().map(str::to_string),
                version: api["version"].as_str().map(str::to_string),
                stage: api["stage"].as_str().map(str::to_string),
            })
            .collect();
        registry
            .add_region(Region {
                id: RegionId::new(region["id"].as_str().unwrap_or_default()),
                display_name: region["display_name"].as_str().unwrap_or_default().to_string(),
                localized_name: region["localized_name"]
                    .as_str()
                    .unwrap_or_default()
                    .to_string(),
                pool_id: region["pool_id"].as_str().unwrap_or_default().to_string(),
                public_apis,
                status: RegionStatus::Active,
                privacy_settings: privacy,
            })
            .expect("the fixture has no duplicate regions");
    }
    registry
}

fn config_from(value: &Value) -> ChannelConfig {
    let top_level_privacy = value["config"]["top_level_privacy"]
        .as_array()
        .map(|pairs| {
            pairs
                .iter()
                .filter_map(|pair| {
                    let key = pair[0].as_str()?.to_string();
                    let value = pair[1].as_str()?.to_string();
                    Some((key, value))
                })
                .collect()
        })
        .unwrap_or_default();
    ChannelConfig {
        channel_name: value["config"]["channel_name"]
            .as_str()
            .unwrap_or_default()
            .to_string(),
        platform_metadata: value["config"]["platform_metadata"].clone(),
        omni: value["config"]["omni"].clone(),
        top_level_privacy,
    }
}

#[test]
fn the_fixture_is_populated() {
    let f = fixture();
    assert!(
        f["registry"]["regions"]
            .as_array()
            .is_some_and(|r| !r.is_empty()),
        "the fixture must describe at least one region"
    );
    assert!(
        f["expected_body"].as_str().is_some_and(|b| b.len() > 1000),
        "the expected body must be a real document"
    );
    assert_eq!(
        f["build_sha256"].as_str(),
        Some(azoth_region::CHANNEL_BUILD_SHA256),
        "the fixture is build-scoped and must match the crate's build"
    );
}

/// The headline assertion: same registry in, same bytes out.
#[test]
fn the_rendered_document_matches_the_python_gateway_byte_for_byte() {
    let f = fixture();
    let registry = registry_from(&f);
    let config = config_from(&f);
    let rendered = render(&config, &registry).expect("renders");
    let expected = f["expected_body"].as_str().expect("expected_body");

    let actual = rendered.body_str().expect("utf-8");
    if actual != expected {
        // Show the first divergence with context rather than dumping 7 KB twice.
        let at = actual
            .bytes()
            .zip(expected.bytes())
            .position(|(a, b)| a != b)
            .unwrap_or_else(|| actual.len().min(expected.len()));
        let from = at.saturating_sub(60);
        let actual_slice: String = actual.chars().skip(from).take(140).collect();
        let expected_slice: String = expected.chars().skip(from).take(140).collect();
        panic!(
            "channel document differs at byte {at}\n\
             --- rust ---\n{actual_slice}\n\
             --- python ---\n{expected_slice}\n\
             (rust {} bytes, python {} bytes)",
            actual.len(),
            expected.len()
        );
    }
}

/// Every region in the registry must appear as a top-level key of the document.
#[test]
fn every_registered_region_appears_in_the_document() {
    let f = fixture();
    let registry = registry_from(&f);
    let config = config_from(&f);
    let rendered = render(&config, &registry).expect("renders");
    let document: Value = serde_json::from_slice(&rendered.body).expect("valid json");
    for region in &registry.regions {
        assert!(
            document.get(region.id.as_str()).is_some(),
            "region {} is registered but absent from the document",
            region.id
        );
    }
}

/// The document must be parseable JSON with a trailing newline, which is what the prototype serves.
#[test]
fn the_document_is_well_formed() {
    let f = fixture();
    let registry = registry_from(&f);
    let config = config_from(&f);
    let rendered = render(&config, &registry).expect("renders");
    assert_eq!(rendered.body.last(), Some(&b'\n'), "must end with a newline");
    let parsed: Value = serde_json::from_slice(&rendered.body).expect("valid json");
    assert!(parsed.is_object());
    assert_eq!(
        parsed["channelName"].as_str(),
        Some(config.channel_name.as_str())
    );
}
