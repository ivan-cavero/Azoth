//! Configuration, validated at startup.
//!
//! WHY THIS IS ONE STRUCT AND NOT ENVIRONMENT LOOKUPS
//! ==================================================
//! `apps/channeld/src/config.rs` records the failure this shape prevents: the Python prototype read
//! three `AZOTH_*` environment variables, a missing one was **not** an error, and the result was a
//! silently different experiment that cost a session. `regiond` inherits the rule unchanged —
//! every path is a field, every field has a default, and a missing required file or directory is a
//! startup error whose message names the path. Nothing is read from the environment.
//!
//! WHY THE DATABASE PATH IS A FLAG AND NOT A CONSTANT
//! ==================================================
//! The acceptance for this phase is "restart the region, log in again, and the same character
//! returns". Proving that needs a database a test can point at a scratch file, and an operator needs
//! to point a second `regiond` at the same file to see the same account. A constant would make both
//! impossible, so `--database` exists with the private runtime's path as its default.
//!
//! WHY THE SEED DOCUMENTS ARE READ HERE
//! ====================================
//! This module already owns the two paths, and the mapping from those files to a registry is a
//! translation rather than a rule: every value comes from the seed. Keeping it beside the paths is
//! what lets `identity` be about the player and this module be about "where the data lives and how
//! it is read". The mapping is the one `apps/channeld/src/state.rs` performs, so a world opened in
//! one service is visible in the other without a second copy to drift.

use std::path::{Path, PathBuf};

use azoth_region::registry::{
    PublicApi, Region, RegionStatus, Registry, WorldPlacement, WorldStatus,
};
use azoth_region::{CHANNEL_BUILD_SHA256, CLIENT_VERSION, RegionId, WorldId};
use serde_json::Value;

/// The port the prototype's Caddy routes `/prod/game/*` and `/players/*` to.
///
/// 8080 is the Python gateway and 8081 is `channeld`; a distinct port is what lets both be started
/// and compared against the same client.
pub const DEFAULT_PORT: u16 = 8082;

/// Where the prototype keeps its seed data, relative to the repository root.
///
/// The same default as `channeld` on purpose: both services read the **same** `worlds.json`, so a
/// world opened in one is visible in the other, and there is no second copy to drift.
pub const DEFAULT_DATA_DIR: &str = "services/gateway/src/azoth_gateway/data";

/// Where the identity database lives, relative to the repository root.
///
/// `private-client/runtime/` is git-ignored, so a login written during a session never reaches the
/// repository — the same rule that keeps raw captures and certificates out of Git.
pub const DEFAULT_TICKET_OUT: &str = "private-client/runtime/tickets.json";

const DEFAULT_DATABASE_PATH: &str = "private-client/runtime/identity.db";

/// The region's runtime configuration.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Config {
    /// Bind host.
    pub host: String,
    /// Bind port. 8082 by default, behind Caddy on 443 in a deployment.
    pub port: u16,
    /// Where the checked-in seed data lives: `channel-azoth.json`, `worlds.json`.
    pub data_dir: PathBuf,
    /// The identity database file. Created on first start; its directory must already exist.
    pub database_path: PathBuf,
    /// Where to publish the login tickets this region mints, for the world to validate.
    ///
    /// **This file is the phase-3 stand-in for a region-to-world message.** The durable design has
    /// the region tell the world about a claim directly (plan §7.2/§7.3); a file is what a single
    /// machine can do today without inventing a control channel first. It is written atomically
    /// (temp file then rename) so a world reading it never sees a half-written array.
    pub ticket_out: PathBuf,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_string(),
            port: DEFAULT_PORT,
            // Repo-relative defaults, resolved from the working directory at runtime.
            data_dir: PathBuf::from(DEFAULT_DATA_DIR),
            database_path: PathBuf::from(DEFAULT_DATABASE_PATH),
            ticket_out: PathBuf::from(DEFAULT_TICKET_OUT),
        }
    }
}

impl Config {
    /// Parse `--host`, `--port`, `--data-dir` and `--database` from arguments.
    ///
    /// Hand-rolled for the same reason `channeld`'s is: four flags with defaults do not justify a
    /// dependency, and an error written for these four is more useful than a generated one.
    ///
    /// # Errors
    /// A message naming the flag when a value is missing or unparseable, and the usage text for an
    /// unknown flag.
    pub fn from_args<I: IntoIterator<Item = String>>(args: I) -> Result<Self, String> {
        let mut config = Self::default();
        let mut iter = args.into_iter();
        while let Some(arg) = iter.next() {
            match arg.as_str() {
                "--host" => config.host = iter.next().ok_or("--host needs a value")?,
                "--port" => {
                    let value = iter.next().ok_or("--port needs a value")?;
                    config.port = value
                        .parse()
                        .map_err(|_| format!("--port {value:?} is not a number"))?;
                }
                "--data-dir" => {
                    config.data_dir = PathBuf::from(iter.next().ok_or("--data-dir needs a value")?)
                }
                "--ticket-out" => {
                    config.ticket_out =
                        PathBuf::from(iter.next().ok_or("--ticket-out needs a value")?)
                }
                "--database" => {
                    config.database_path =
                        PathBuf::from(iter.next().ok_or("--database needs a value")?)
                }
                "--help" | "-h" => return Err(Self::usage()),
                other => return Err(format!("unknown argument {other:?}\n\n{}", Self::usage())),
            }
        }
        Ok(config)
    }

    /// The usage text.
    #[must_use]
    pub fn usage() -> String {
        "usage: regiond [--host H] [--port P] [--data-dir DIR] [--database FILE]".to_string()
    }

    /// The channel seed document: the per-region `publicApis` and the dotted privacy keys.
    #[must_use]
    pub fn channel_seed(&self) -> PathBuf {
        self.data_dir.join("channel-azoth.json")
    }

    /// The world/region registry seed.
    #[must_use]
    pub fn registry_seed(&self) -> PathBuf {
        self.data_dir.join("worlds.json")
    }

    /// Fail when a required file is absent, naming the path and what it is for.
    ///
    /// # Errors
    /// The path and what it is for.
    pub fn require(&self, path: &Path, what: &str) -> Result<(), String> {
        if path.is_file() {
            Ok(())
        } else {
            Err(format!("{what} not found at {}", path.display()))
        }
    }

    /// Fail when a required directory is absent, naming the path and what it is for.
    ///
    /// The identity database's directory is checked separately from the file because
    /// `azoth_store::Store::open` deliberately does not create it: a mistyped path must fail at
    /// startup rather than silently create a database somewhere nobody looks.
    ///
    /// # Errors
    /// The path and what it is for.
    pub fn require_directory(&self, path: &Path, what: &str) -> Result<(), String> {
        if path.is_dir() {
            Ok(())
        } else {
            Err(format!("{what} not found at {}", path.display()))
        }
    }

    /// The region/world registry, built from the two seed documents this configuration names.
    ///
    /// # Errors
    /// A message naming the missing or unparseable file, and the registry's own error when a world
    /// names an unregistered region or a region lacks a `clientTag` the client requires.
    pub fn registry(&self) -> Result<Registry, String> {
        let channel_seed = self.read_json(&self.channel_seed(), "the channel seed document")?;
        let worlds = self.read_json(&self.registry_seed(), "the world/region registry")?;
        let registry = registry_from(&channel_seed, &worlds)?;
        registry.validate().map_err(|err| err.to_string())?;
        Ok(registry)
    }

    /// Read a seed document, naming it in every failure.
    fn read_json(&self, path: &Path, what: &str) -> Result<Value, String> {
        self.require(path, what)?;
        let bytes = std::fs::read(path)
            .map_err(|err| format!("cannot read {}: {err}", path.display()))?;
        serde_json::from_slice(&bytes)
            .map_err(|err| format!("{} is not valid JSON: {err}", path.display()))
    }
}

/// Translate the two seed documents into a registry.
///
/// `worlds.json` carries the regions and worlds; `channel-azoth.json` carries each region's
/// `publicApis` under the region id, which is what the client looks up by `clientTag` and what
/// [`Registry::validate`] requires. Only the fields this service reads are mapped: `regiond` does
/// not render the channel document, so a region's dotted privacy keys stay where `channeld` reads
/// them rather than being copied into a second owner.
fn registry_from(channel_seed: &Value, worlds: &Value) -> Result<Registry, String> {
    let mut registry = Registry::new();
    for region in worlds["regions"].as_array().into_iter().flatten() {
        let id = region["id"].as_str().unwrap_or_default();
        let entry = channel_seed.get(id).cloned().unwrap_or(Value::Null);
        let public_apis: Vec<PublicApi> = entry["publicApis"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|api| PublicApi {
                client_tag: api["clientTag"].as_str().unwrap_or_default().to_string(),
                api_endpoint: api["apiEndpoint"].as_str().unwrap_or_default().to_string(),
                aws_region: api["awsRegion"].as_str().map(str::to_string),
                version: api["version"].as_str().map(str::to_string),
                stage: api["stage"].as_str().map(str::to_string),
            })
            .collect();
        let display_name = region["displayName"].as_str().unwrap_or_default();
        registry
            .add_region(Region {
                id: RegionId::new(id),
                display_name: display_name.to_string(),
                // The prototype overrides localizedName with the display name at render time.
                localized_name: display_name.to_string(),
                pool_id: entry["poolId"].as_str().unwrap_or_default().to_string(),
                public_apis,
                status: RegionStatus::Active,
                privacy_settings: Vec::new(),
            })
            .map_err(|err| err.to_string())?;
    }

    for world in worlds["worlds"].as_array().into_iter().flatten() {
        registry
            .add_world(WorldPlacement {
                id: WorldId(world["id"].as_str().unwrap_or_default().to_string()),
                name: world["name"].as_str().unwrap_or_default().to_string(),
                display_name: world["displayName"].as_str().unwrap_or_default().to_string(),
                region_id: RegionId::new(world["regionId"].as_str().unwrap_or_default()),
                world_set: world["worldSet"].as_str().unwrap_or_default().to_string(),
                status: match world["status"].as_str() {
                    Some("MAINTENANCE") => WorldStatus::Maintenance,
                    Some("DRAINING") => WorldStatus::Draining,
                    _ => WorldStatus::Active,
                },
                world_type: world["type"].as_str().unwrap_or("OpenWorld").to_string(),
                version: world["version"].as_str().unwrap_or(CLIENT_VERSION).to_string(),
                capacity: u32::try_from(world["maxPlayers"].as_u64().unwrap_or(2500))
                    .unwrap_or(2500),
                rep_address: world["repAddress"]
                    .as_str()
                    .unwrap_or("127.0.0.1:9000")
                    .to_string(),
                build_sha256: CHANNEL_BUILD_SHA256.to_string(),
                placement_epoch: 1,
                population: 0,
            })
            .map_err(|err| err.to_string())?;
    }
    Ok(registry)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_defaults_are_the_documented_ones() {
        let config = Config::default();
        assert_eq!(config.host, "127.0.0.1");
        assert_eq!(config.port, 8082, "8080 is the prototype and 8081 is channeld");
        assert_eq!(config.data_dir, PathBuf::from(DEFAULT_DATA_DIR));
        assert_eq!(config.database_path, PathBuf::from(DEFAULT_DATABASE_PATH));
    }

    #[test]
    fn parses_every_flag() {
        let config = Config::from_args(
            [
                "--host",
                "0.0.0.0",
                "--port",
                "9001",
                "--data-dir",
                "/tmp/data",
                "--database",
                "/tmp/identity.db",
            ]
            .into_iter()
            .map(String::from),
        )
        .expect("parses");
        assert_eq!(config.host, "0.0.0.0");
        assert_eq!(config.port, 9001);
        assert_eq!(config.data_dir, PathBuf::from("/tmp/data"));
        assert_eq!(config.database_path, PathBuf::from("/tmp/identity.db"));
    }

    #[test]
    fn a_missing_value_is_an_error_not_a_default() {
        for flag in ["--host", "--port", "--data-dir", "--database"] {
            let err = Config::from_args([flag].into_iter().map(String::from)).expect_err("fails");
            assert!(err.contains(flag), "{err}");
        }
    }

    #[test]
    fn a_bad_port_is_an_error() {
        let err = Config::from_args(["--port", "eighty"].into_iter().map(String::from))
            .expect_err("fails");
        assert!(err.contains("eighty"), "{err}");
    }

    #[test]
    fn an_unknown_flag_is_an_error_with_usage() {
        let err = Config::from_args(["--nope"].into_iter().map(String::from)).expect_err("fails");
        assert!(err.contains("--nope"), "{err}");
        assert!(err.contains("usage:"), "the message must say how to use it");
    }

    #[test]
    fn no_arguments_gives_the_defaults() {
        let config = Config::from_args(std::iter::empty()).expect("parses");
        assert_eq!(config, Config::default());
    }

    #[test]
    fn the_seed_paths_are_built_from_the_data_dir() {
        let config = Config::default();
        assert!(config.channel_seed().ends_with("channel-azoth.json"));
        assert!(config.registry_seed().ends_with("worlds.json"));
    }

    #[test]
    fn require_names_the_missing_path() {
        let config = Config::default();
        let err = config
            .require(Path::new("/definitely/not/here.json"), "the registry seed")
            .expect_err("must fail");
        assert!(err.contains("the registry seed"), "{err}");
        assert!(err.contains("/definitely/not/here.json"), "{err}");
    }

    #[test]
    fn the_seed_documents_load_into_a_valid_registry() {
        // The real seed files, resolved from the crate directory: a mapping that only works on a
        // fixture would not prove the service starts.
        let config = Config {
            data_dir: PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../../services/gateway/src/azoth_gateway/data"),
            ..Config::default()
        };
        let registry = config.registry().expect("the seed documents load");
        assert_eq!(registry.regions.len(), 5);
        assert_eq!(registry.worlds.len(), 5);
        assert_eq!(registry.worlds[0].name, "everfall");
        assert_eq!(registry.worlds[0].region_id.as_str(), "fra-prod");
    }

    #[test]
    fn a_missing_seed_document_names_its_path() {
        let config = Config {
            data_dir: PathBuf::from("/definitely/not/here"),
            ..Config::default()
        };
        // The channel seed is read first, so its absence is what is reported.
        let err = config.registry().expect_err("must fail");
        assert!(err.contains("the channel seed document"), "{err}");
        assert!(err.contains("channel-azoth.json"), "{err}");
    }

    #[test]
    fn require_directory_names_the_missing_path() {
        let config = Config::default();
        let err = config
            .require_directory(Path::new("/definitely/not/here"), "the identity directory")
            .expect_err("must fail");
        assert!(err.contains("the identity directory"), "{err}");
        assert!(err.contains("/definitely/not/here"), "{err}");
    }
}
