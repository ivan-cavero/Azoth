//! Print the rendered channel document, for comparing against the Python gateway by hand.
//!
//! Exists so a parity failure can be inspected without editing a test: `cargo run -p azoth-region
//! --example dump-channel` writes the same bytes the renderer serves.

use azoth_region::channel::{ChannelConfig, render};
use azoth_region::registry::{Registry, Region, RegionStatus, PublicApi};
use azoth_region::RegionId;
use serde_json::Value;

fn main() {
    let fixture = include_str!("../tests/fixtures/channel-parity.json");
    let value: Value = serde_json::from_str(fixture).expect("fixture json");
    let mut registry = Registry::new();
    for region in value["registry"]["regions"].as_array().expect("regions") {
        let public_apis = region["public_apis"]
            .as_array()
            .expect("apis")
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
                localized_name: region["localized_name"].as_str().unwrap_or_default().to_string(),
                pool_id: region["pool_id"].as_str().unwrap_or_default().to_string(),
                public_apis,
                status: RegionStatus::Active,
                privacy_settings: Default::default(),
            })
            .expect("adds");
    }
    let config = ChannelConfig {
        channel_name: value["config"]["channel_name"].as_str().unwrap_or_default().to_string(),
        platform_metadata: value["config"]["platform_metadata"].clone(),
        omni: value["config"]["omni"].clone(),
        top_level_privacy: Vec::new(),
    };
    let rendered = render(&config, &registry).expect("renders");
    print!("{}", rendered.body_str().expect("utf8"));
    eprintln!("--- etag {}", rendered.etag);
}
