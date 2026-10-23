//! The platform surface: Steam entitlements and the privacy settings round-trip.
//!
//! WHY THE ENTITLEMENT LIST IS `{hasMoreResults, lineItems[]}`
//! ========================================================
//! `sync` has no JSON response parser — `{}` is the intended stub — and the list is a **generic
//! paginated list**, not `{entitlements: [...]}`. That wrapper was invented, and the client ignored
//! it. Per entry every value is a string except the numeric `amount`
//! (`routes/entitlements.py`, RE'd from the URL builder `FUN_1474caa10` and the parser
//! `FUN_1474c2420`).
//!
//! WHY THE PRIVACY RESPONSE IS A PERMISSIVE SUPERSET
//! ================================================
//! This route is not cosmetic. The client's `LevelInfoChanged` handler (`FUN_146446800`) drops the
//! world load with `javContext.IsMasterPlayer is false` unless byte `+0xa2` of the javContext is `1`,
//! and the only writer of that byte in `.text` (`0x14160a754`) is inside the
//! `AgsPrivacySettingsService` endpoint client. Until the client completes a privacy-settings
//! round-trip for our persona, the world never loads: no `LevelInfoChanged` processing, black screen,
//! `connection_player_timeout` (`routes/privacy.py`).
//!
//! The client hashes keys at runtime (FNV-1a), so only registered property hashes match: unknown
//! keys are free and a **missing** key is the risk. Hence every setting present, allowing, in the
//! shapes the string table names (`lastUpdateDate`, `errorCode`, `allowedValues`, `x-amzn-token`),
//! with the master-player flags repeated in each casing the client might look up.

use serde_json::{Value, json};

use crate::identity::Identity;

use super::iso8601_utc;

/// The game alias the privacy service is asked about.
const GAME_ALIAS: &str = "new-world";

/// The AWS region our privacy settings live in, as the channel document declares.
const PRIVACY_REGION: &str = "us-west-2";

/// The Steam app the base-game entitlement is granted for.
const STEAM_APP_PRODUCT: &str = "STEAM_APP_ID.1063730";

/// `GET /players/{persona}/games/new-world/platforms/steam/entitlements`.
#[must_use]
pub fn entitlements(identity: &Identity) -> Value {
    let persona = identity.persona();
    let now = iso8601_utc(crate::identity::now_unix_seconds());
    json!({
        "hasMoreResults": false,
        "lineItems": [
            {
                "acquisitionPersonaId": persona,
                "acquisitionType": "Grant",
                "amount": 1,
                "createdDate": now,
                "productId": STEAM_APP_PRODUCT,
                "transactionId": "azoth-base-game",
                "type": "BaseGame",
            },
        ],
    })
}

/// `POST …/entitlements/sync`: the stub the client expects, because it parses nothing.
#[must_use]
pub fn entitlements_sync() -> Value {
    json!({})
}

/// `GET /players/{persona}/games/new-world/privacy-settings` and the two RPC names.
///
/// The persona in the path is not trusted and not echoed: `regiond` serves exactly one identity, and
/// echoing a path segment would let a request claim a persona the account does not own. The value
/// the client was issued in the token exchange is the only one it can match against its session.
#[must_use]
pub fn privacy(identity: &Identity) -> Value {
    let persona = identity.persona();
    let now = iso8601_utc(crate::identity::now_unix_seconds());
    json!({
        "PlayerId": persona,
        "GameAlias": GAME_ALIAS,
        "lastUpdateDate": now,
        "errorCode": 0,
        "region": PRIVACY_REGION,
        "client-mode": "online",
        "settings": {
            "region": PRIVACY_REGION,
            // The byte the LevelInfoChanged handler requires, in every spelling it might hash.
            "isMasterPlayer": true,
            "masterPlayer": true,
            "MasterPlayer": true,
            "presence": "online",
            "Presence": "online",
            "allowInvites": true,
            "canInvite": true,
            "isVisible": true,
        },
        "allowedValues": ["online", "offline", "busy"],
        "x-amzn-token": "azoth-privacy-token",
    })
}
