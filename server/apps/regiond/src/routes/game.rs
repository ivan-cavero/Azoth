//! `/prod/game/*`: the login surface the client walks to reach character select.
//!
//! WHY `getlogininfo` CARRIES **TWO** WORLD SCHEMAS
//! ===============================================
//! The body is read by two different parsers and both are required
//! (`services/gateway/src/azoth_gateway/routes/registry.py::getlogininfo_doc`):
//!
//! * a top-level lowercase `worlds` array whose enums are **integers**, feeding the UI dropdown
//!   (`big_parser` reflection table `0x144f40780`), and
//! * a top-level `LoginInfoList` **object** (not an array) whose PascalCase `Worlds` and `Characters`
//!   feed the create-character gate (`FUN_1474e42e0` / `FUN_1474e1f60`).
//!
//! The gate parser reads only the `LoginInfoList` root key and recurses into it; without that
//! envelope the candidate vector stays zeroed and the dropdown renders 0/0. A strict parse of either
//! schema drops the whole object on an unknown-typed key, which is why the two shapes are kept apart
//! instead of merged into one union.
//!
//! WHY THE GATE'S ENUMS ARE STRINGS AND THE DROPDOWN'S ARE NUMBERS
//! =============================================================
//! They are different reflection models, not different spellings of one. The gate needs
//! `WorldStatus: "ACTIVE"` + `WorldType: "OpenWorld"` + `PublicStatusCode: 0` to pass the candidate
//! check `FUN_1464460d0` (`(psc & 0xffffe8b7) == 0`); the dropdown renders `status: 1` and
//! `publicStatusCode: 1`. Copying one into the other is the mistake that produces an empty world
//! list with no error anywhere.
//!
//! WHY THE CHARACTER'S DATES COME FROM THE DIRECTORY ROW
//! ====================================================
//! The prototype stamps every date with `now` (`_seed_character`), which is fine for a hardcoded
//! placeholder and wrong for a stored character: a `CreatedDate` that moves on every login is not a
//! directory row, it is a fabrication, and the client's savedata is keyed by the character. The dates
//! here come from `created_at`/`modified_at`, so a restart returns the same character with the same
//! dates — which is exactly what the persistence acceptance asks for.
//!
//! WHY THE QUEUE TICKET IS A SEPARATE ENVELOPE FROM THE REFRESH
//! ==========================================================
//! The parser reads the top-level `LoginQueueResponse` key and then PascalCase fields inside; a flat
//! `{ticket, worldId, …}` object is ignored with "No login ticket received". `Signature` is the
//! handoff gate (`FUN_14643d110` → `FUN_14114b200` compares the transformed token's leading string
//! field, which comes from `Signature`), so an empty string never triggers the next stage, and the
//! refresh path is what moves the client from `WaitingForQueuedLogin` to `StartREPConnection` — it
//! must carry `Position: 0` and a full `Token`.

use azoth_region::registry::{Region, WorldPlacement, WorldStatus};
use azoth_store::Character;
use serde_json::{Value, json};

use crate::identity::{AZOTH_STEAM_APP_ID, AZOTH_STEAM_ID, Identity, mint_uuid_v4, now_unix_seconds};

use super::{RouteError, iso8601_utc};

/// The `worldtype_mapper` (`0x1417c40a0`): `FTUE` and `OpenWorld` are the only wire values, and
/// anything else maps to `OpenWorld`.
const WORLD_TYPE_OPEN: &str = "OpenWorld";

/// `GET /prod/game/getlogininfo/...` — both schemas, in one document.
///
/// # Errors
/// [`RouteError`] when the account has no character or the registry cannot place it.
pub fn login_info(identity: &Identity) -> Result<Value, RouteError> {
    let worlds = ordered_worlds(identity)?;
    let character = identity.primary_character().ok_or(RouteError::NoCharacter)?;
    let persona = identity.persona();
    let dropdown: Vec<Value> = worlds.iter().map(|world| dropdown_world(world)).collect();
    let gate: Vec<Value> = worlds.iter().map(|world| gate_world(world)).collect();
    Ok(json!({
        "worlds": dropdown,
        "recommendedWorlds": [],
        "LoginInfoList": {
            "Worlds": gate,
            "Characters": [character_body(character, persona)],
            "MaxChannelCharacters": 4,
            "CrossRegionTransferCooldownMins": 0,
            "NameReservations": [],
            "PendingWorldMerges": [],
        },
    }))
}

/// `GET|POST /prod/game/worlds/list/...` — the world list (`WorldsInfo`).
///
/// The camelCase reflection model with string enums, which is a **third** shape: `publicStatusCode`
/// is `0` here because the usable-check `FUN_1464460d0` rejects anything else, and the per-world
/// object carries exactly the model's keys because a strict parse drops the element on an
/// unknown-typed one.
#[must_use]
pub fn worlds_list(identity: &Identity) -> Value {
    let worlds: Vec<Value> = identity
        .registry()
        .worlds
        .iter()
        .map(world_metadata)
        .collect();
    json!({ "worlds": worlds, "recommendedWorlds": [] })
}

/// `POST /prod/game/login/queue/v2/jwt/omni` and its refresh form.
///
/// # Errors
/// [`RouteError`] when the character has no world the registry can place.
pub fn queue(
    identity: &Identity,
    refresh: bool,
    ticket_out: &std::path::Path,
) -> Result<Value, RouteError> {
    let (world, region) = placement(identity)?;
    let ticket = ticket(identity, world)?;
    // Publish it for the world to validate. A failure to publish is NOT fatal to the login: the
    // client gets its ticket either way, and a world that cannot find it will refuse the
    // registration, which is a visible failure rather than a silent one.
    publish_ticket(ticket_out, &ticket);
    if !refresh {
        return Ok(json!({ "LoginQueueResponse": ticket }));
    }
    Ok(json!({
        "LoginQueueResponse": {
            "AllowQueueTransfer": false,
            "EstimatedTime": 0,
            // Position 0 with a full Token is what ends the queue wait locally.
            "Position": 0,
            "QueueName": queue_name(region),
            "RecommendedTransferWorldId": "",
            "RefreshInterval": 15,
            "TicketId": ticket["TicketId"],
            "Token": ticket,
        },
    }))
}

/// The worlds this response lists, with the character's own world first.
///
/// The prototype binds the character to `worlds[0]` and lists every world of the client's region.
/// `regiond` serves one region, so its registry *is* the client's region; the character's world is
/// moved to the front so the dropdown's default selection matches the row the character is bound to
/// (a character bound to a world the list does not show renders as "world unavailable" and its Play
/// button does nothing).
fn ordered_worlds(identity: &Identity) -> Result<Vec<&WorldPlacement>, RouteError> {
    let registry = identity.registry();
    if registry.worlds.is_empty() {
        return Err(RouteError::UnknownWorld(String::new()));
    }
    let character = identity.primary_character().ok_or(RouteError::NoCharacter)?;
    let own = registry
        .worlds
        .iter()
        .find(|world| world.id.0 == character.world_id)
        .ok_or_else(|| RouteError::UnknownWorld(character.world_id.clone()))?;
    let mut ordered = Vec::with_capacity(registry.worlds.len());
    ordered.push(own);
    ordered.extend(
        registry
            .worlds
            .iter()
            .filter(|world| world.id.0 != character.world_id),
    );
    Ok(ordered)
}

/// The character's world and its region, or the reason there is none.
fn placement(identity: &Identity) -> Result<(&WorldPlacement, Option<&Region>), RouteError> {
    let registry = identity.registry();
    let character = identity.primary_character().ok_or(RouteError::NoCharacter)?;
    let world = registry
        .worlds
        .iter()
        .find(|world| world.id.0 == character.world_id)
        .ok_or_else(|| RouteError::UnknownWorld(character.world_id.clone()))?;
    Ok((world, registry.region(&world.region_id)))
}

/// The dropdown entry: lowercase `WorldMetadata` with **integer** enums.
fn dropdown_world(world: &WorldPlacement) -> Value {
    let maintenance = matches!(world.status, WorldStatus::Maintenance);
    json!({
        "worldId": world.id.0,
        "type": 1,           // eWorldType_OpenWorld
        "status": 1,         // ACTIVE
        "publicStatusCode": 1, // the dropdown's render value
        "worldMetrics": {
            "worldAgeDays": 1,
            "queueSize": 0,
            "queueWaitTimeSec": 0,
            "worldPopulationStatus": 1, // LOW
        },
        "publicName": world.display_name,
        "version": world.version,
        "maxAccountCharacters": 4,
        "worldSet": world.world_set,
        "transferToRegion": "",
        "isFull": false,
        "isRecommended": !maintenance,
    })
}

/// The gate entry: PascalCase `WorldMetadata` with **string** enums.
fn gate_world(world: &WorldPlacement) -> Value {
    let maintenance = matches!(world.status, WorldStatus::Maintenance);
    json!({
        "WorldId": world.id.0,
        "WorldName": world.name,
        "PublicName": world.display_name,
        "WorldStatus": world.status.as_str(),
        "WorldType": wire_world_type(&world.world_type),
        "WorldSet": world.world_set,
        "WorldVersion": world.version,
        "PublicStatusCode": 0, // the gate value: (psc & 0xffffe8b7) == 0 passes
        "MaxAccountCharacters": 4,
        "MaxConnectionCount": world.capacity,
        "ConnectionCount": 0,
        "IsFull": false,
        "IsRecommended": !maintenance,
        "TransferToRegion": "",
        "WorldMetrics": {
            "WorldAgeDays": 1,
            "QueueSize": 0,
            "QueueWaitTimeSec": 0,
            "WorldPopulationStatus": 1,
        },
    })
}

/// The `worlds/list` entry: camelCase, string enums, exactly the model's keys.
fn world_metadata(world: &WorldPlacement) -> Value {
    let maintenance = matches!(world.status, WorldStatus::Maintenance);
    json!({
        "worldId": world.id.0,
        "name": world.name,
        "type": wire_world_type(&world.world_type),
        "status": world.status.as_str(),
        "version": world.version,
        "publicStatusCode": 0,
        "publicName": world.display_name,
        "maxAccountCharacters": 4,
        "worldSet": world.world_set,
        "worldMetrics": {
            "worldAgeDays": 1,
            "queueSize": 0,
            "queueWaitTimeSec": 0,
            "worldPopulationStatus": "LOW",
        },
        "transferToRegion": "",
        "isFull": false,
        "isRecommended": !maintenance,
        "regionId": world.region_id.0,
    })
}

/// The wire world type: `FTUE` or `OpenWorld`, everything else `OpenWorld`.
fn wire_world_type(raw: &str) -> String {
    match raw.trim_start_matches("eWorldType_") {
        "FTUE" => "FTUE".to_string(),
        _ => WORLD_TYPE_OPEN.to_string(),
    }
}

/// The character as `CharacterMetadata` (32 fields, `FUN_1474e1f60`).
///
/// The client renders the panel from these and then validates and queues instead of stalling on an
/// empty `Characters` vector. Dates come from the directory row; see the module docs.
fn character_body(character: &Character, persona: &str) -> Value {
    let created = iso8601_utc(character.created_at);
    let modified = iso8601_utc(character.modified_at);
    json!({
        "CharacterId": character.character_id,
        "Name": character.name,
        "PersonaId": persona,
        "WorldId": character.world_id,
        "CreatedDate": created,
        "ModifiedDate": modified,
        "NameModifiedDate": modified,
        "NameLatentDate": modified,
        "NeedsTransferDate": modified,
        "TransferDate": modified,
        "RegionTransferDate": modified,
        "LocationGroupId": "",
        "LocationId": "",
        "MustRenameReason": "",
        "OwnerState": "",
        "PublishedData": "",
        "PublishedSource": "",
        "PublishedElapsedSeconds": 0,
        "PublishedSocialSource": "",
        "PublishedSocialElapsedSeconds": 0,
        "SocialData": "",
        "TransferCrossRegionCooldownEndTime": 0,
        "TransferFreeCooldownEndTime": 0,
        "TransferData": "",
        "TransferReason": "",
        "FtueCompleted": true,
        "IsFreshStart": false,
        "IsNameLatent": false,
        "IsTrialOwner": false,
        "MustRename": false,
        "NeedsTransfer": false,
        "Transferrable": false,
    })
}

/// The login ticket: the handoff to the world server.
///
/// `Signature` is never empty because the client's handoff gate compares it; `RepAddress` is the
/// only place the client learns where the world's UDP endpoint is.
fn ticket(identity: &Identity, world: &WorldPlacement) -> Result<Value, RouteError> {
    let character = identity.primary_character().ok_or(RouteError::NoCharacter)?;
    let now = now_unix_seconds();
    let ticket_id = mint_uuid_v4();
    Ok(json!({
        "AccountAge": 0,
        "AccountIsLocked": false,
        "CharacterId": character.character_id,
        "ClientCapabilities": "",
        "GenerateTime": now,
        "HostHash": "",
        "IsPermanentAppOwner": true,
        "IsTrialOwner": false,
        "IssueTime": now,
        "Location": "",
        "LocationGroupId": "",
        "LocationId": "",
        "PersonaId": identity.persona(),
        "RepAddress": world.rep_address,
        "Signature": format!("sig:{ticket_id}"),
        "SteamAppId": AZOTH_STEAM_APP_ID,
        "SteamUserId": AZOTH_STEAM_ID,
        "TicketId": ticket_id,
        "TokenVersion": 10,
        "WorldId": world.id.0,
        "WorldName": world.name,
        // NOT a client field: the world reads it to decide whether a registration is still valid.
        // The client never parses it (it is not in any measured response shape), and the world
        // cannot validate a ticket without an expiry. Kept in the published copy, not in the wire
        // body, by `publish_ticket` -- see the note there.
        "ExpiresAtUnix": now + TICKET_TTL_SECONDS,
    }))
}

/// How long a minted ticket stays valid.
///
/// Long enough to cover the login ladder and a client restart, short enough that a leaked ticket is
/// not durable. The world enforces it; the client never sees it.
const TICKET_TTL_SECONDS: i64 = 15 * 60;

/// `QueueName` for the ready envelope.
///
/// It maps through the client's `@mm_loginservices_location_` table, so it must be an AWS region
/// token. The region's `loginGateway` endpoint is the one its clients use, so its `awsRegion` is the
/// honest value; `us-east-1` is the prototype's constant and the fallback when a region does not
/// declare one.
/// Append a minted ticket to the world's ticket file, atomically.
///
/// **This is the phase-3 stand-in for a region-to-world message.** The durable design has the
/// region tell the world about a claim directly; a file is what one machine can do today. It is
/// rewritten whole (temp file, then rename) so a reader never sees a half-written array, and the
/// array is capped so it cannot grow without bound across a long-running region.
fn publish_ticket(path: &std::path::Path, ticket: &Value) {
    const MAX_TICKETS: usize = 64;

    let mut tickets: Vec<Value> = std::fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str::<Vec<Value>>(&text).ok())
        .unwrap_or_default();
    tickets.push(ticket.clone());
    if tickets.len() > MAX_TICKETS {
        let excess = tickets.len() - MAX_TICKETS;
        tickets.drain(0..excess);
    }

    let Some(parent) = path.parent() else { return };
    if std::fs::create_dir_all(parent).is_err() {
        return;
    }
    let temp = path.with_extension("json.tmp");
    let Ok(encoded) = serde_json::to_vec_pretty(&tickets) else {
        return;
    };
    if std::fs::write(&temp, encoded).is_err() {
        return;
    }
    // A rename over an existing file is atomic on both NTFS and POSIX, which is why the reader can
    // never observe a partial array.
    let _ = std::fs::rename(&temp, path);
}

fn queue_name(region: Option<&Region>) -> String {
    region
        .and_then(|region| {
            region
                .public_apis
                .iter()
                .find(|api| api.client_tag == "loginGateway")
        })
        .and_then(|api| api.aws_region.clone())
        .unwrap_or_else(|| "us-east-1".to_string())
}
