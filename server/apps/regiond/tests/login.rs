//! The login ladder, driven end to end through the real router.
//!
//! WHY THE MODULES ARE INCLUDED BY `#[path]`
//! ========================================
//! `regiond` is a binary crate, so an integration test cannot `use regiond::…`. Including the same
//! source files by path compiles the **real** router, the real seeding and the real bodies into the
//! test binary — a copy of the logic in a test would prove nothing about what the binary serves.
//!
//! WHAT THESE TESTS ARE FOR
//! ========================
//! Each one is a client-visible property whose absence is a specific, expensive failure: a token body
//! OmniSDK parses (code 203 if not), a numeric `expiration` (an ISO string crashes the client), both
//! world schemas in `getlogininfo` (the dropdown renders 0/0 without them), a non-empty `Signature`
//! (the handoff gate never fires), and the persistence acceptance — restart, and the same character
//! comes back.

#[path = "../src/config.rs"]
mod config;
#[path = "../src/identity.rs"]
mod identity;
#[path = "../src/routes/mod.rs"]
mod routes;

use std::path::PathBuf;
use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use azoth_store::Store;
use serde_json::Value;
use tower::ServiceExt;

use config::Config;
use identity::{AZOTH_ACCOUNT_ID, AZOTH_DISPLAY_NAME, AZOTH_PERSONA, Identity};
use routes::AppState;

/// A scratch directory under the system temp dir, removed when the test ends.
///
/// Never inside the worktree: a test that leaves a database in the checkout is a test that dirties
/// `git status`.
struct TempDir(PathBuf);

impl TempDir {
    fn new(tag: &str) -> Self {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |elapsed| elapsed.as_nanos());
        let path = std::env::temp_dir().join(format!(
            "azoth-regiond-{tag}-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir_all(&path).expect("create the scratch directory");
        Self(path)
    }

    fn path(&self) -> &PathBuf {
        &self.0
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

/// The seed data the running service reads, resolved from the crate directory.
fn seed_data_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../services/gateway/src/azoth_gateway/data")
}

/// A seeded identity on a fresh database.
struct Fixture {
    config: Config,
    identity: Arc<Identity>,
    /// Kept alive for the whole test so the database file outlives the assertion.
    _dir: TempDir,
}

fn fixture(tag: &str) -> Fixture {
    let dir = TempDir::new(tag);
    let config = Config {
        host: "127.0.0.1".to_string(),
        port: 0,
        data_dir: seed_data_dir(),
        database_path: dir.path().join("identity.db"),
        ticket_out: dir.path().join("tickets.json"),
    };
    let identity = Arc::new(Identity::load(&config).expect("seeds the identity database"));
    Fixture {
        config,
        identity,
        _dir: dir,
    }
}

impl Fixture {
    fn state(&self) -> AppState {
        AppState::new(Arc::clone(&self.identity), self.config.ticket_out.clone())
    }
}

/// Send a request through the real router and return the status and the parsed body.
async fn send(state: &AppState, method: &str, uri: &str) -> (StatusCode, Value) {
    let request = Request::builder()
        .method(method)
        .uri(uri)
        .body(Body::empty())
        .expect("request builds");
    let response = routes::router(std::sync::Arc::new(state.clone()))
        .oneshot(request)
        .await
        .expect("the router answers");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    // A body that is not JSON is a failure of the route, not of the assertion; `Value::Null` makes
    // the following assertion say so.
    let body = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, body)
}

#[tokio::test]
async fn one_the_token_set_is_parseable_and_carries_the_persona() {
    let fixture = fixture("tokens");
    let (status, body) = send(&fixture.state(), "POST", "/games/new-world/tokens").await;
    assert_eq!(status, StatusCode::OK);
    // `jwt_reader` needs two dots in the access token.
    let access = body["accessToken"].as_str().expect("accessToken is a string");
    assert_eq!(access.matches('.').count(), 2, "{access}");
    assert_eq!(body["platformAccount"]["personaId"], AZOTH_PERSONA);
    assert_eq!(body["account"]["type"], "shadow");
    // OmniSDK reads the fields in this order; a body in another order is the shape that 203'd.
    let keys: Vec<&str> = body
        .as_object()
        .expect("an object")
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(
        keys,
        [
            "region",
            "limitedUseToken",
            "platformAccount",
            "account",
            "isNewAccount",
            "accessToken",
            "expiresIn",
            "fallbackToken",
        ]
    );
}

#[tokio::test]
async fn two_the_credentials_expiration_is_a_number() {
    let fixture = fixture("credentials");
    let (status, body) = send(&fixture.state(), "GET", "/prod/credentials/omni").await;
    assert_eq!(status, StatusCode::OK);
    // A NUMBER of unix seconds. The PascalCase/ISO form crashes NewWorld.exe at +0x7465476.
    assert!(
        body["expiration"].is_number(),
        "expiration must be a number, got {:?}",
        body["expiration"]
    );
    assert_eq!(body["expiration"].as_str(), None, "an ISO string crashes the client");
    assert_eq!(body["personaId"], AZOTH_PERSONA);
    assert!(
        body["accessKeyId"]
            .as_str()
            .is_some_and(|key| key.starts_with("ASIA")),
        "the key is STS-shaped"
    );
}

#[tokio::test]
async fn three_the_entitlement_list_is_the_paginated_shape() {
    let fixture = fixture("entitlements");
    let uri = format!(
        "/players/{AZOTH_PERSONA}/games/new-world/platforms/steam/entitlements"
    );
    let (status, body) = send(&fixture.state(), "GET", &uri).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["hasMoreResults"], false);
    assert_eq!(body["lineItems"].as_array().map(Vec::len), Some(1));
    assert_eq!(body["lineItems"][0]["type"], "BaseGame");
    assert!(body["lineItems"][0]["amount"].is_number());

    let sync = format!("{uri}/sync");
    let (status, body) = send(&fixture.state(), "POST", &sync).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, Value::Object(serde_json::Map::new()), "sync parses nothing");
}

#[tokio::test]
async fn four_getlogininfo_carries_both_world_schemas() {
    let fixture = fixture("getlogininfo");
    let (status, body) = send(&fixture.state(), "GET", "/prod/game/getlogininfo/jwt/omni").await;
    assert_eq!(status, StatusCode::OK);
    // The dropdown: lowercase keys, integer enums.
    let worlds = body["worlds"].as_array().expect("a lowercase worlds array");
    assert!(!worlds.is_empty(), "the dropdown must list a world");
    assert_eq!(worlds[0]["status"], 1, "the dropdown's status is an int");
    assert!(worlds[0]["status"].is_number());
    assert!(worlds[0]["type"].is_number());
    // The gate: a `LoginInfoList` OBJECT with PascalCase arrays.
    let list = body["LoginInfoList"]
        .as_object()
        .expect("LoginInfoList must be an object, not an array");
    assert!(!list["Worlds"].as_array().expect("Worlds").is_empty());
    assert_eq!(
        list["Characters"].as_array().map(Vec::len),
        Some(1),
        "the gate needs one character to render and start a login from"
    );
    assert_eq!(list["Characters"][0]["PersonaId"], AZOTH_PERSONA);
    assert_eq!(list["Worlds"][0]["WorldStatus"], "ACTIVE");
}

#[tokio::test]
async fn five_the_queue_issues_a_ticket_with_a_signature() {
    let fixture = fixture("queue");
    let (status, body) = send(
        &fixture.state(),
        "POST",
        "/prod/game/login/queue/v2/jwt/omni",
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let ticket = &body["LoginQueueResponse"];
    let signature = ticket["Signature"].as_str().expect("Signature");
    assert!(!signature.is_empty(), "an empty Signature never fires the handoff gate");
    let rep = ticket["RepAddress"].as_str().expect("RepAddress");

    // AND IT IS PUBLISHED. The world validates a registration against this file, so a ticket the
    // client holds but the world never heard of is a login that fails at the REP handshake with no
    // server-side explanation. This is the phase-3 stand-in for a region-to-world message.
    let published: Vec<serde_json::Value> = serde_json::from_str(
        &std::fs::read_to_string(&fixture.config.ticket_out).expect("the ticket file exists"),
    )
    .expect("the ticket file is a JSON array");
    assert_eq!(published.len(), 1, "one login, one published ticket");
    assert_eq!(
        published[0]["TicketId"], ticket["TicketId"],
        "the published ticket is the one the client received"
    );
    assert_eq!(
        published[0]["CharacterId"], ticket["CharacterId"],
        "the character the world will bind to"
    );
    assert!(!rep.is_empty(), "the client learns the world's UDP address here");
    let character = fixture
        .identity
        .primary_character()
        .expect("the seed created a character");
    assert_eq!(ticket["WorldId"], character.world_id);
    assert_eq!(ticket["CharacterId"], character.character_id);
}

#[tokio::test]
async fn six_the_queue_refresh_is_ready_with_position_zero() {
    let fixture = fixture("refresh");
    let (status, body) = send(
        &fixture.state(),
        "POST",
        "/prod/game/login/queue/v2/abc-123/jwt/omni",
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let ready = &body["LoginQueueResponse"];
    assert_eq!(ready["Position"], 0, "Position 0 ends the local queue wait");
    let token = ready["Token"].as_object().expect("a full Token");
    assert_eq!(token["TicketId"], ready["TicketId"]);
    assert!(token["Signature"].as_str().is_some_and(|s| !s.is_empty()));
    assert!(ready["QueueName"].as_str().is_some_and(|q| q.contains('-')));
}

#[tokio::test]
async fn seven_a_restart_returns_the_same_character() {
    let fixture = fixture("persistence");
    let before = fixture
        .identity
        .primary_character()
        .expect("the seed created a character")
        .clone();

    // A second load on the same database file is the restart: nothing is re-seeded.
    let restarted = Identity::load(&fixture.config).expect("reloads");
    let after = restarted
        .primary_character()
        .expect("the character survived");
    assert_eq!(after.character_id, before.character_id);
    assert_eq!(after.name, before.name);
    assert_eq!(after.world_id, before.world_id);
    assert_eq!(
        restarted.characters_for(AZOTH_ACCOUNT_ID).len(),
        1,
        "seeding must not add a second character"
    );

    // And the row is on disk, not in the process: a fresh connection reads it.
    let store = Store::open(&fixture.config.database_path).expect("open the database");
    let rows = store
        .characters_for(AZOTH_ACCOUNT_ID)
        .expect("read characters");
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].character_id, before.character_id);
}

#[tokio::test]
async fn eight_an_unknown_path_is_a_404() {
    let fixture = fixture("unknown");
    for path in ["/nope", "/cms/manifest", "/prod/game/not-a-route"] {
        let (status, body) = send(&fixture.state(), "GET", path).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{path} must not answer 200");
        assert_eq!(body["error"], "not-implemented", "{path}");
        assert_eq!(body["path"], path);
    }
}

#[tokio::test]
async fn nine_the_privacy_settings_are_the_permissive_superset() {
    // Not cosmetic: without this round-trip the client's LevelInfoChanged handler drops the world
    // load and the screen stays black.
    let fixture = fixture("privacy");
    for path in [
        format!("/players/{AZOTH_PERSONA}/games/new-world/privacy-settings"),
        format!("/players/{AZOTH_PERSONA}/games/new-world/GetPrivacySettingsForPlayer"),
        format!("/players/{AZOTH_PERSONA}/games/new-world/CreateOrUpdatePrivacySettingsForPlayer"),
    ] {
        let (status, body) = send(&fixture.state(), "GET", &path).await;
        assert_eq!(status, StatusCode::OK, "{path}");
        assert_eq!(body["PlayerId"], AZOTH_PERSONA, "{path}");
        assert_eq!(body["settings"]["isMasterPlayer"], true, "{path}");
        assert_eq!(body["errorCode"], 0, "{path}");
        assert!(body["allowedValues"].is_array(), "{path}");
    }
}

#[tokio::test]
async fn ten_the_seeded_character_is_a_v4_uuid_named_from_the_persona() {
    let fixture = fixture("identity");
    let character = fixture
        .identity
        .primary_character()
        .expect("the seed created a character");
    // A v4 UUID, because the client's character reader expects one.
    assert_eq!(character.character_id.len(), 36);
    assert_eq!(character.character_id.as_bytes()[14], b'4');
    assert!(
        matches!(character.character_id.as_bytes()[19], b'8' | b'9' | b'a' | b'b'),
        "the variant nibble must be RFC 4122"
    );
    // Derived from the persona, so a restart (and a different persona) behaves predictably.
    assert_eq!(character.name, identity::character_name_for(AZOTH_PERSONA));
    assert_ne!(
        character.name,
        identity::character_name_for("amzn1.developerPersonaId.other")
    );
    assert_eq!(fixture.identity.persona_for(AZOTH_ACCOUNT_ID), Some(AZOTH_PERSONA));
    assert_eq!(fixture.identity.persona_for("someone-else"), None);
}

#[tokio::test]
async fn eleven_the_startup_summary_names_what_was_loaded() {
    let fixture = fixture("summary");
    // The startup log is the only thing that distinguishes "working" from "started with nothing".
    let summary = fixture.identity.summary();
    assert!(summary.contains(AZOTH_ACCOUNT_ID), "{summary}");
    assert!(summary.contains(AZOTH_DISPLAY_NAME), "{summary}");
    assert!(summary.contains("1 character(s)"), "{summary}");
    assert!(summary.contains("5 world(s)"), "{summary}");
    assert_eq!(fixture.identity.account().display_name, AZOTH_DISPLAY_NAME);
}
