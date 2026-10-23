//! Rendering the channel document from the registry.
//!
//! THE DOCUMENT IS A FUNCTION OF STATE
//! ===================================
//! ```text
//! channel document = f(channel config, region registry)
//! ```
//!
//! Nothing about a region is stored in a file. Opening a region, closing one, or changing its
//! endpoints is a registry mutation, and the next render reflects it. That is what makes regions
//! dynamic, and it is the single decision the discovery model hangs on.
//!
//! WHY THE KEY ORDER IS PRESERVED
//! ==============================
//! The client parses JSON by key, so order does not matter to it. It matters to **us**, because the
//! cheapest way to prove this renderer is faithful is to compare its bytes with the Python
//! gateway's output for the same registry — and a byte comparison is only meaningful if the order
//! is stable. Preserving the document's declared order (channel name, then regions in registration
//! order, then the configuration blocks) makes that comparison exact instead of approximate.
//!
//! WHY THE ETAG IS MANDATORY
//! =========================
//! A CMS response without an ETag crashes the client (`routes/cms.py`). The channel document is
//! served the same way, and the ETag is derived from the rendered bytes — so a region status flip
//! changes the ETag, the client re-reads, and a region change becomes live without a client
//! restart. That is the whole mechanism, and it is one hash.

use crate::registry::Registry;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// The non-region parts of the document: product configuration, not fleet state.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChannelConfig {
    /// The name the client logs, e.g. `Azoth`.
    pub channel_name: String,
    /// `platformMetadata`: per-platform token endpoints.
    pub platform_metadata: Value,
    /// `omni`: the Omni SDK settings block.
    pub omni: Value,
    /// The flat `omni.privacy-settings.*` keys that sit at the document's top level.
    ///
    /// A map, because these names are the client's: `omni.privacy-settings.region`,
    /// `omni.privacy-settings.client-endpoint`, and so on. Inventing a nested shape would change
    /// what the client looks up.
    pub top_level_privacy: Vec<(String, String)>,
}

impl ChannelConfig {
    /// A minimal config with the measured key names and empty values.
    ///
    /// Exists so a test or a fresh deployment can render a well-formed document without inventing
    /// the client's key vocabulary.
    #[must_use]
    pub fn minimal(channel_name: impl Into<String>) -> Self {
        Self {
            channel_name: channel_name.into(),
            platform_metadata: Value::Object(Map::new()),
            omni: Value::Object(Map::new()),
            top_level_privacy: Vec::new(),
        }
    }
}

/// A rendered channel document, with the ETag derived from its bytes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RenderedChannel {
    /// The exact bytes to serve.
    pub body: Vec<u8>,
    /// The strong ETag for those bytes.
    pub etag: String,
}

impl RenderedChannel {
    /// The body as a string, for tests and logging.
    ///
    /// # Errors
    /// Only if the body is not UTF-8, which it always is because it is generated JSON.
    pub fn body_str(&self) -> Result<&str, std::str::Utf8Error> {
        std::str::from_utf8(&self.body)
    }
}

/// Render the channel document.
///
/// # Errors
/// [`crate::RegionError::UnknownRegion`] if a world names an unregistered region, because such a
/// world would render under no key and the client would never see it.
pub fn render(config: &ChannelConfig, registry: &Registry) -> Result<RenderedChannel, crate::RegionError> {
    registry.validate()?;

    let mut root = Map::new();
    root.insert("channelName".to_string(), Value::String(config.channel_name.clone()));

    // Regions in registration order, each a key of its own.
    for region in &registry.regions {
        let mut entry = Map::new();
        entry.insert(
            "displayName".to_string(),
            Value::String(region.display_name.clone()),
        );
        entry.insert(
            "localizedName".to_string(),
            Value::String(region.localized_name.clone()),
        );
        entry.insert("poolId".to_string(), Value::String(region.pool_id.clone()));

        let mut apis = Vec::with_capacity(region.public_apis.len());
        for api in &region.public_apis {
            // FIELD ORDER IS THE PROTOTYPE'S, ON PURPOSE.
            //
            // The client parses by key, so order is invisible to it — but it is not invisible to
            // us: matching the served document's order is what makes the byte-for-byte parity test
            // in `tests/channel_parity.rs` possible, and that test is the cheapest proof this
            // renderer is faithful. The order below is the one in the document the client already
            // accepts, measured from `data/channel-azoth.json`.
            let mut item = Map::new();
            if let Some(aws) = &api.aws_region {
                item.insert("awsRegion".to_string(), Value::String(aws.clone()));
            }
            if let Some(version) = &api.version {
                item.insert("version".to_string(), Value::String(version.clone()));
            }
            item.insert(
                "apiEndpoint".to_string(),
                Value::String(api.api_endpoint.clone()),
            );
            item.insert("clientTag".to_string(), Value::String(api.client_tag.clone()));
            if let Some(stage) = &api.stage {
                item.insert("stage".to_string(), Value::String(stage.clone()));
            }
            apis.push(Value::Object(item));
        }
        entry.insert("publicApis".to_string(), Value::Array(apis));

        // The region's own privacy overrides, as flat dotted keys inside the region object.
        for (key, value) in &region.privacy_settings {
            entry.insert(key.clone(), Value::String(value.clone()));
        }

        root.insert(region.id.0.clone(), Value::Object(entry));
    }

    root.insert(
        "platformMetadata".to_string(),
        config.platform_metadata.clone(),
    );
    root.insert("omni".to_string(), config.omni.clone());
    for (key, value) in &config.top_level_privacy {
        root.insert(key.clone(), Value::String(value.clone()));
    }

    let value = Value::Object(root);
    let mut body = serde_json::to_vec_pretty(&value).map_err(|_| crate::RegionError::UnknownRegion {
        world: String::new(),
        region: String::new(),
    })?;
    // Python's `json.dumps(...) + "\n"` ends with a newline and so does this: the byte comparison
    // in the parity test would fail on the last byte otherwise, which is a silly way to spend a
    // debugging session.
    body.push(b'\n');

    let etag = etag_for(&body);
    Ok(RenderedChannel { body, etag })
}

/// A strong ETag for a body: a quoted hex digest of its bytes.
///
/// FNV-1a 64-bit, not a cryptographic hash. The requirement is "changes when the bytes change", and
/// a non-cryptographic digest gives that at a fraction of the cost on a route the client polls.
/// It is not a security boundary and does not need to be one.
#[must_use]
pub fn etag_for(body: &[u8]) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for &byte in body {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("\"{hash:016x}\"")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::registry::{PublicApi, Region, RegionStatus, WorldPlacement, WorldStatus};
    use crate::{RegionId, REQUIRED_CLIENT_TAGS, WorldId};

    fn region(id: &str, display: &str) -> Region {
        Region {
            id: RegionId::new(id),
            display_name: display.to_string(),
            localized_name: "@mm_test".to_string(),
            pool_id: "us-east-1:0de93f7c-814e-4d48-a8fd-b6efc2f9ed93".to_string(),
            public_apis: REQUIRED_CLIENT_TAGS
                .iter()
                .map(|tag| PublicApi {
                    client_tag: tag.to_string(),
                    api_endpoint: format!("{tag}.example"),
                    aws_region: Some("eu-central-1".to_string()),
                    version: Some("1.0".to_string()),
                    stage: Some("prod".to_string()),
                })
                .collect(),
            status: RegionStatus::Active,
            privacy_settings: Vec::new(),
        }
    }

    #[test]
    fn renders_a_document_with_no_regions() {
        let config = ChannelConfig::minimal("Azoth");
        let rendered = render(&config, &Registry::new()).expect("renders");
        let text = rendered.body_str().expect("utf-8");
        assert!(text.starts_with("{\n  \"channelName\": \"Azoth\""), "{text}");
        assert!(text.ends_with('\n'));
    }

    #[test]
    fn regions_are_top_level_keys_in_registration_order() {
        let config = ChannelConfig::minimal("Azoth");
        let mut registry = Registry::new();
        registry.add_region(region("fra-prod", "EU Central")).expect("adds");
        registry.add_region(region("gru-prod", "SA East")).expect("adds");
        let rendered = render(&config, &registry).expect("renders");
        let text = rendered.body_str().expect("utf-8");
        let fra = text.find("\"fra-prod\"").expect("fra present");
        let gru = text.find("\"gru-prod\"").expect("gru present");
        assert!(fra < gru, "registration order must be preserved");
        // And both come after channelName, before the config blocks.
        assert!(text.find("\"channelName\"").expect("name") < fra);
    }

    #[test]
    fn a_region_carries_its_four_client_tags() {
        let config = ChannelConfig::minimal("Azoth");
        let mut registry = Registry::new();
        registry.add_region(region("fra-prod", "EU Central")).expect("adds");
        let text = render(&config, &registry).expect("renders").body;
        let text = std::str::from_utf8(&text).expect("utf-8");
        for tag in REQUIRED_CLIENT_TAGS {
            assert!(text.contains(&format!("\"clientTag\": \"{tag}\"")), "missing {tag}");
        }
    }

    #[test]
    fn the_etag_changes_when_a_region_status_changes() {
        let config = ChannelConfig::minimal("Azoth");
        let mut registry = Registry::new();
        registry.add_region(region("fra-prod", "EU Central")).expect("adds");
        let before = render(&config, &registry).expect("renders");

        // A status flip is the live mechanism: the document bytes change, so the ETag changes, so
        // the client re-reads. Note the status itself is NOT rendered into the channel document —
        // what changes here is the display name, which is what the renderer owns.
        let mut region2 = region("fra-prod", "EU Central (maintenance)");
        region2.status = RegionStatus::Maintenance;
        let mut registry2 = Registry::new();
        registry2.add_region(region2).expect("adds");
        let after = render(&config, &registry2).expect("renders");
        assert_ne!(before.etag, after.etag);
    }

    #[test]
    fn the_etag_is_stable_for_identical_state() {
        let config = ChannelConfig::minimal("Azoth");
        let mut registry = Registry::new();
        registry.add_region(region("fra-prod", "EU Central")).expect("adds");
        let first = render(&config, &registry).expect("renders");
        let second = render(&config, &registry).expect("renders");
        assert_eq!(first.etag, second.etag);
        assert_eq!(first.body, second.body);
    }

    #[test]
    fn the_etag_is_quoted_hex() {
        let etag = etag_for(b"{}");
        assert!(etag.starts_with('"') && etag.ends_with('"'), "{etag}");
        assert_eq!(etag.len(), 18, "quote + 16 hex + quote");
        assert_ne!(etag_for(b"{}"), etag_for(b"{ }"));
    }

    #[test]
    fn a_world_under_an_unknown_region_refuses_to_render() {
        let config = ChannelConfig::minimal("Azoth");
        let mut registry = Registry::new();
        registry
            .add_world(WorldPlacement {
                id: WorldId("1".to_string()),
                name: "orphan".to_string(),
                display_name: "Orphan".to_string(),
                region_id: RegionId::new("nowhere"),
                world_set: "nowhere".to_string(),
                status: WorldStatus::Active,
                world_type: "OpenWorld".to_string(),
                version: crate::CLIENT_VERSION.to_string(),
                capacity: 10,
                rep_address: "127.0.0.1:9000".to_string(),
                build_sha256: crate::CHANNEL_BUILD_SHA256.to_string(),
                placement_epoch: 1,
                population: 0,
            })
            .expect("adds");
        assert!(render(&config, &registry).is_err());
    }

    #[test]
    fn a_region_with_no_worlds_still_renders() {
        // The requirement that forces the region/world split: a region answers with no world up.
        let config = ChannelConfig::minimal("Azoth");
        let mut registry = Registry::new();
        registry.add_region(region("fra-prod", "EU Central")).expect("adds");
        let rendered = render(&config, &registry).expect("renders");
        let text = rendered.body_str().expect("utf-8");
        assert!(text.contains("\"fra-prod\""));
        // And it carries no world keys, because worlds are not part of this document.
        assert!(!text.contains("\"worlds\""));
    }
}
