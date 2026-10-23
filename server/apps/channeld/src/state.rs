//! The loaded state every request reads.
//!
//! WHY EVERYTHING IS PRELOADED AND PRE-RENDERED
//! ============================================
//! The prototype preloads its bodies once and says why: "bodies + ETags preloaded once; per-request
//! work is routing, one dict lookup and header compares" (`app.py`). That is the right shape for a
//! route the client polls 4,339 times, and it is kept here.
//!
//! The channel document is pre-rendered for the same reason, but with a consequence worth stating:
//! **a registry change requires a restart** until the registry is mutable at runtime. That is
//! deliberate for now — the plan's Phase 1 is "serve the right bytes", and making the document live
//! is Phase 2's job, where `regiond` becomes its writer. Doing it here first would put two owners on
//! one document.
//!
//! WHAT IS CACHED
//! ==============
//! Only bytes and their ETags. Nothing per-request is stored, so there is no cache to invalidate and
//! no state to grow.

use std::sync::Arc;

use azoth_http::Response;
use azoth_region::channel::{ChannelConfig, RenderedChannel, render};
use azoth_region::registry::{
    PublicApi, Region, RegionStatus, Registry, WorldPlacement, WorldStatus,
};
use azoth_region::RegionId;
use serde_json::Value;

use crate::config::Config;

/// A pre-rendered body with its ETag.
#[derive(Debug, Clone)]
pub struct Cached {
    /// The exact bytes to serve.
    pub body: Vec<u8>,
    /// The strong ETag for those bytes.
    pub etag: String,
}

impl Cached {
    /// Cache a body, deriving its ETag.
    #[must_use]
    pub fn new(body: Vec<u8>) -> Self {
        let etag = azoth_http::etag_for(&body);
        Self { body, etag }
    }

    /// The `200` response for this body.
    #[must_use]
    pub fn response(&self, content_type: &'static str) -> Response {
        Response::ok(content_type, self.body.clone(), self.etag.clone())
    }
}

/// Everything a request needs, shared across tasks.
#[derive(Debug, Clone)]
pub struct AppState {
    /// The channel document.
    pub channel: Arc<Cached>,
    /// The news metadata body.
    pub cms_news: Arc<Cached>,
    /// The marketing-tiles body.
    pub cms_tiles: Arc<Cached>,
    /// The MOTD body, rendered from the registry.
    pub cms_motd: Arc<Cached>,
    /// The registry, for the routes that answer from state.
    pub registry: Arc<Registry>,
}

impl AppState {
    /// Load and pre-render everything, failing loudly on a missing file.
    ///
    /// # Errors
    /// A message naming the file and what it is for.
    pub fn load(config: &Config) -> Result<Self, Box<dyn std::error::Error>> {
        config.require(&config.channel_seed(), "the channel seed document")?;
        config.require(&config.registry_seed(), "the world/region registry")?;
        config.require(&config.cms_news(), "the captured news body")?;
        config.require(&config.cms_tiles(), "the captured marketing-tiles body")?;

        let seed: Value = serde_json::from_slice(&std::fs::read(config.channel_seed())?)?;
        let worlds: Value = serde_json::from_slice(&std::fs::read(config.registry_seed())?)?;
        let registry = registry_from(&seed, &worlds)?;
        registry.validate()?;

        let channel_config = channel_config_from(&seed)?;
        let rendered: RenderedChannel = render(&channel_config, &registry)?;

        Ok(Self {
            channel: Arc::new(Cached {
                body: rendered.body,
                etag: rendered.etag,
            }),
            cms_news: Arc::new(Cached::new(std::fs::read(config.cms_news())?)),
            cms_tiles: Arc::new(Cached::new(std::fs::read(config.cms_tiles())?)),
            cms_motd: Arc::new(Cached::new(render_motd(&registry)?)),
            registry: Arc::new(registry),
        })
    }

    /// A one-line description for the startup log.
    #[must_use]
    pub fn summary(&self) -> String {
        format!(
            "{} region(s), {} world(s), channel document {} bytes etag {}",
            self.registry.regions.len(),
            self.registry.worlds.len(),
            self.channel.body.len(),
            self.channel.etag
        )
    }
}

/// Build the registry from the seed files.
///
/// The seed is the prototype's two data files, adapted rather than copied: `worlds.json` carries the
/// regions and worlds, and `channel-azoth.json` carries each region's `publicApis` and its dotted
/// privacy keys. Splitting the data that way is the prototype's shape, and reusing it means the
/// first Rust deployment starts from the same state the Python one had.
fn registry_from(seed: &Value, worlds: &Value) -> Result<Registry, Box<dyn std::error::Error>> {
    let mut registry = Registry::new();
    for region in worlds["regions"].as_array().into_iter().flatten() {
        let id = region["id"].as_str().unwrap_or_default();
        let entry = seed.get(id).cloned().unwrap_or(Value::Null);
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
        // The region's dotted privacy keys, in the seed's own order.
        let privacy_settings: Vec<(String, String)> = entry
            .as_object()
            .into_iter()
            .flatten()
            .filter(|(key, value)| {
                key.starts_with("omni.privacy-settings.") && value.is_string()
            })
            .map(|(key, value)| {
                (
                    key.clone(),
                    value.as_str().unwrap_or_default().to_string(),
                )
            })
            .collect();
        registry.add_region(Region {
            id: RegionId::new(id),
            display_name: region["displayName"].as_str().unwrap_or_default().to_string(),
            // The prototype overrides localizedName with the display name at render time.
            localized_name: region["displayName"].as_str().unwrap_or_default().to_string(),
            pool_id: entry["poolId"].as_str().unwrap_or_default().to_string(),
            public_apis,
            status: RegionStatus::Active,
            privacy_settings,
        })?;
    }

    for world in worlds["worlds"].as_array().into_iter().flatten() {
        registry.add_world(WorldPlacement {
            id: azoth_region::WorldId(world["id"].as_str().unwrap_or_default().to_string()),
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
            version: world["version"]
                .as_str()
                .unwrap_or(azoth_region::CLIENT_VERSION)
                .to_string(),
            capacity: u32::try_from(world["maxPlayers"].as_u64().unwrap_or(2500))
                .unwrap_or(2500),
            rep_address: world["repAddress"]
                .as_str()
                .unwrap_or("127.0.0.1:9000")
                .to_string(),
            build_sha256: azoth_region::CHANNEL_BUILD_SHA256.to_string(),
            placement_epoch: 1,
            population: 0,
        })?;
    }
    Ok(registry)
}

/// Extract the configuration blocks from the seed document.
fn channel_config_from(seed: &Value) -> Result<ChannelConfig, Box<dyn std::error::Error>> {
    let top_level_privacy = seed
        .as_object()
        .into_iter()
        .flatten()
        .filter(|(key, value)| key.starts_with("omni.privacy-settings.") && value.is_string())
        .map(|(key, value)| (key.clone(), value.as_str().unwrap_or_default().to_string()))
        .collect();
    Ok(ChannelConfig {
        channel_name: seed["channelName"].as_str().unwrap_or_default().to_string(),
        platform_metadata: seed["platformMetadata"].clone(),
        omni: seed["omni"].clone(),
        top_level_privacy,
    })
}

/// Render the MOTD document from the registry.
///
/// Shape measured from `research/schemas/live/cms_motd.json` and reproduced by the prototype's
/// `registry.motd_doc`: per world, an `announcement` plus a `warning` and per-locale variants; per
/// world set, a `setName`; then a global title and description with the same locale fan-out.
fn render_motd(registry: &Registry) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    // The prototype's locale list, which came from the captured body.
    const LOCALES: [&str; 7] = ["es-ES", "es-MX", "fr-FR", "de-DE", "pl-PL", "it-IT", "pt-BR"];

    let mut worlds = serde_json::Map::new();
    let mut world_sets = serde_json::Map::new();
    for world in &registry.worlds {
        let announcement = if matches!(world.status, WorldStatus::Maintenance) {
            // The registry has no per-world announcement field yet; the prototype reads one from
            // its JSON. An empty string is the same thing the prototype serves for an ACTIVE world.
            String::new()
        } else {
            String::new()
        };
        let mut doc = serde_json::Map::new();
        doc.insert("announcement".to_string(), Value::String(announcement));
        for locale in LOCALES {
            doc.insert(
                format!("{locale}-announcement"),
                Value::String(String::new()),
            );
        }
        doc.insert("warning".to_string(), Value::String(String::new()));
        for locale in LOCALES {
            doc.insert(format!("{locale}-warning"), Value::String(String::new()));
        }
        worlds.insert(world.id.0.clone(), Value::Object(doc));
        let mut set = serde_json::Map::new();
        set.insert(
            "setName".to_string(),
            Value::String(world.display_name.clone()),
        );
        world_sets.insert(world.world_set.clone(), Value::Object(set));
    }

    let mut global = serde_json::Map::new();
    global.insert("title".to_string(), Value::String(String::new()));
    for locale in LOCALES {
        global.insert(format!("{locale}-title"), Value::String(String::new()));
    }
    global.insert("description".to_string(), Value::String(String::new()));
    for locale in LOCALES {
        global.insert(format!("{locale}-description"), Value::String(String::new()));
    }

    let mut root = serde_json::Map::new();
    root.insert("worlds".to_string(), Value::Object(worlds));
    root.insert("worldSets".to_string(), Value::Object(world_sets));
    root.insert("globalAnnouncement".to_string(), Value::Object(global));

    // Python-shaped separators so this route is byte-comparable with the prototype, which is what
    // the Phase 1 acceptance asks for. See `azoth_http::pyjson`.
    azoth_http::to_python_bytes(&Value::Object(root)).map_err(Into::into)
}
