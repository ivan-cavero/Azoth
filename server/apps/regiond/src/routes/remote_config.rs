//! The remote-config layers: the `configuration-sets` documents.
//!
//! WHY THIS MODULE EXISTS, AND WHAT IT IS NOT
//! ==========================================
//! After the Omni token exchange the client pulls StackConfig layers from
//! `ags-javelin-remote-config` for four identity kinds — `ProductId`, `RegionId`, `CognitoId`,
//! `WorldId` — in two trees (`applications/public` and `applications/publicGameplay`), each in a
//! `versionless` form and a versioned one. Twelve requests per login.
//!
//! **The shapes were never captured in the clear**: those requests go out over TLS to an S3 endpoint
//! and the extraction recorded sizes, not bodies. So this module does what the prototype does and
//! says so: it serves a document whose *content* is the set of keys the client has been measured
//! reading, padded to the captured `Content-Length`. That is a length fallback, not shape guessing —
//! the difference matters, because a guessed shape would be a protocol claim and a length fallback
//! is an observation.
//!
//! THE KEYS ARE LOAD-BEARING, AND EACH HAS A MEASUREMENT
//! ====================================================
//! * **`enable-anticheat` (the BARE key)** is read by `FUN_146193620` on the `WorldId` layer. Without
//!   it, REP registration fails with `Errors::connection_server_requires_anticheat`. The lookup is a
//!   bare key on the layer document, so nested `game-security.enable-anticheat` and dotted copies are
//!   invisible to it — the prototype serves bare, nested and dotted on every layer so that a
//!   ProductId-first merge cannot leave the default `true` in place.
//! * **`javelin.offline-id-version` and `javelin.enable-offline-capitals`** are the portrayal gate
//!   (`FUN_146165f20`). Without them the gate stays closed, no `GameSystemData` is inserted, the local
//!   player actor is never built, and the world renders black.
//! * **`eos-product-id` and `eos-client-id` are deliberately absent.** Including them makes ClientSDK
//!   try to initialise EOS, which does not exist on the private runtime, and the login fails with
//!   `@eos_unknown_error` / `server_requires_anticheat` (measured 2026-09-18, 5 ms after the REP
//!   socket opened).
//!
//! The `javelin.*` values were derived on 1.400. They are carried forward because the failure mode of
//! omitting them is visible (a black world) and the failure mode of including them is not — but that
//! is an assumption, and it is listed as one rather than presented as a measurement.

use serde_json::{Map, Value, json};

/// The `game-security` flags the client reads, all disabled.
///
/// Disabled is not a placeholder: it is what the official `WorldId` layer carries (146 bytes, flags
/// only), and what makes the client skip the anti-cheat requirement on a private runtime.
const GAME_SECURITY: [(&str, bool); 5] = [
    ("enable-anticheat", false),
    ("enable-anticheat-kicking", false),
    ("enable-heat-tracking", false),
    ("eos-kick-all", false),
    ("eos-enable-gm-ac", false),
];

/// The Javelin portrayal gates.
///
/// Version 2 plus capitals passes the odd u64 entity keys, which is what makes the local player
/// actor get built at all.
const JAVELIN_OFFLINE_ID_VERSION: i64 = 2;
/// See [`JAVELIN_OFFLINE_ID_VERSION`].
const JAVELIN_OFFLINE_CAPITALS: bool = true;

/// The captured `Content-Length` for each layer, longest key first.
///
/// Order matters: `publicGameplay/configuration-sets/CognitoId` must be matched before
/// `configuration-sets/CognitoId`, or every gameplay layer would be served the public size.
const SIZES: [(&str, usize); 8] = [
    ("publicGameplay/configuration-sets/CognitoId", 5887),
    ("publicGameplay/configuration-sets/ProductId", 1856),
    ("publicGameplay/configuration-sets/RegionId", 872),
    ("publicGameplay/configuration-sets/WorldId", 146),
    ("applications/public/configuration-sets/CognitoId", 1070),
    ("applications/public/configuration-sets/RegionId", 542),
    ("applications/public/configuration-sets/ProductId", 190),
    ("applications/public/configuration-sets/WorldId", 146),
];

/// The captured size for a layer path, if it is one.
#[must_use]
pub fn size_for(path: &str) -> Option<usize> {
    let path = path.split('?').next().unwrap_or(path);
    SIZES
        .iter()
        .find(|(needle, _)| path.contains(needle))
        .map(|(_, size)| *size)
}

/// The layer document, before padding.
///
/// Every `game-security` key appears three times — bare, nested, and dotted — because the client's
/// lookup is a bare-key lookup on the merged layer document and the merge order across layers is not
/// something a server controls.
#[must_use]
pub fn layer_document() -> Value {
    let mut root = Map::new();
    root.insert("azoth".to_string(), Value::Bool(true));

    let mut nested = Map::new();
    for (key, value) in GAME_SECURITY {
        nested.insert(key.to_string(), Value::Bool(value));
    }
    root.insert("game-security".to_string(), Value::Object(nested));

    for (key, value) in GAME_SECURITY {
        root.insert(key.to_string(), Value::Bool(value));
        root.insert(format!("game-security.{key}"), Value::Bool(value));
    }

    root.insert(
        "javelin.offline-id-version".to_string(),
        json!(JAVELIN_OFFLINE_ID_VERSION),
    );
    root.insert(
        "javelin.enable-offline-capitals".to_string(),
        json!(JAVELIN_OFFLINE_CAPITALS),
    );

    Value::Object(root)
}

/// Serialize a layer, padded to the captured size when the document fits in it.
///
/// The padding replaces the closing brace with spaces and puts it back, so the document stays valid
/// JSON while matching the captured length. A caller that wanted the bytes to be *pretty* would be
/// wrong: the client parses them, and the length is the only captured property.
///
/// **When the document is LARGER than the captured size it is served unpadded**, and the size is
/// then a lower bound rather than a match. The official `WorldId` layer was 146 bytes — flags only —
/// while the document here carries the bare, nested and dotted forms of five flags plus the two
/// `javelin.*` gates, because the bare-key lookup has to find them after an unknown merge order. The
/// client parses by key and ignores what it does not know, so a longer document is the safe
/// direction; truncating to match a length would delete keys the client reads. The alternative —
/// serving the 146-byte official body — is not available, because those bodies were never captured
/// in the clear.
#[must_use]
pub fn body_for(path: &str) -> Option<Vec<u8>> {
    let size = size_for(path)?;
    let raw = serde_json::to_vec(&layer_document()).ok()?;
    if raw.len() >= size {
        // Larger than the capture: serve it whole. See the doc comment for why the length is a
        // lower bound here rather than a target.
        return Some(raw);
    }
    let pad = size - raw.len();
    let mut out = Vec::with_capacity(size);
    out.extend_from_slice(&raw[..raw.len() - 1]);
    out.extend(std::iter::repeat_n(b' ', pad));
    out.push(b'}');
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_captured_sizes_are_matched_longest_key_first() {
        // A gameplay Cognito layer must get the gameplay size, not the public one.
        assert_eq!(
            size_for("/applications/publicGameplay/configuration-sets/CognitoId/us-east-1:x/versionless"),
            Some(5887)
        );
        assert_eq!(
            size_for("/applications/public/configuration-sets/CognitoId/us-east-1:x/versionless"),
            Some(1070)
        );
        assert_eq!(
            size_for("/applications/public/configuration-sets/ProductId/STEAM_APP_ID/versionless"),
            Some(190)
        );
    }

    #[test]
    fn the_versioned_form_matches_the_versionless_one() {
        // The client asks for both `versionless` and `<version>`; both must be served.
        let versionless = "/applications/public/configuration-sets/RegionId/fra-prod/versionless";
        let versioned = "/applications/public/configuration-sets/RegionId/fra-prod/6033%3B6024067";
        assert_eq!(size_for(versionless), Some(542));
        assert_eq!(size_for(versioned), Some(542));
    }

    #[test]
    fn a_non_layer_path_has_no_size() {
        assert_eq!(size_for("/ping"), None);
        assert_eq!(size_for("/prod/credentials/omni"), None);
    }

    /// The captured length is a target when the document fits, and a lower bound when it does not.
    ///
    /// The `WorldId` layer is the case that does not fit: 146 bytes captured, and this document
    /// carries fifteen keys because the bare-key lookup must find them after an unknown merge order.
    #[test]
    fn the_body_matches_the_captured_length_when_it_fits() {
        for (needle, size) in SIZES {
            let path = format!("/applications/{needle}/versionless");
            let body = body_for(&path).expect("layer");
            let unpadded = serde_json::to_vec(&layer_document()).expect("serializes");
            if unpadded.len() <= size {
                assert_eq!(body.len(), size, "{needle} must be exactly {size} bytes");
            } else {
                assert_eq!(
                    body.len(),
                    unpadded.len(),
                    "{needle} is larger than the captured {size}; it must be served whole"
                );
            }
        }
    }

    #[test]
    fn the_body_is_valid_json_despite_the_padding() {
        let body = body_for("/applications/public/configuration-sets/ProductId/x/versionless")
            .expect("layer");
        let parsed: Value = serde_json::from_slice(&body).expect("padding must keep it valid");
        assert_eq!(parsed["azoth"], json!(true));
    }

    #[test]
    fn the_bare_anticheat_key_is_present_on_every_layer() {
        // FUN_146193620 looks up the BARE key. A layer without it leaves the default `true` and REP
        // registration fails with connection_server_requires_anticheat.
        let doc = layer_document();
        assert_eq!(doc["enable-anticheat"], json!(false));
        assert_eq!(doc["game-security"]["enable-anticheat"], json!(false));
        assert_eq!(doc["game-security.enable-anticheat"], json!(false));
    }

    #[test]
    fn the_eos_keys_are_absent() {
        // Including them makes ClientSDK try to init EOS, which does not exist here.
        let doc = layer_document();
        let text = doc.to_string();
        assert!(!text.contains("eos-product-id"), "{text}");
        assert!(!text.contains("eos-client-id"), "{text}");
    }

    #[test]
    fn the_javelin_portrayal_gates_are_present() {
        let doc = layer_document();
        assert_eq!(doc["javelin.offline-id-version"], json!(2));
        assert_eq!(doc["javelin.enable-offline-capitals"], json!(true));
    }

    #[test]
    fn every_game_security_flag_is_disabled() {
        let doc = layer_document();
        for (key, value) in GAME_SECURITY {
            assert_eq!(doc[key], json!(value), "bare {key}");
            assert_eq!(doc[format!("game-security.{key}")], json!(value), "dotted {key}");
            assert_eq!(doc["game-security"][key], json!(value), "nested {key}");
        }
    }

    #[test]
    fn a_query_string_does_not_change_the_match() {
        assert_eq!(
            size_for("/applications/public/configuration-sets/WorldId/x/versionless?foo=1"),
            Some(146)
        );
    }
}
