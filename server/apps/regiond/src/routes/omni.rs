//! The Omni token exchange and the credentials the client's login stack reads next.
//!
//! WHY THE TOKEN BODY'S FIELD ORDER IS PART OF THE CONTRACT
//! ======================================================
//! OmniSDK 1.6.7 reads the response fields in a fixed order —
//! `region`, `limitedUseToken`, `platformAccount`, `account`, `isNewAccount`, `accessToken`,
//! `expiresIn`, `fallbackToken` — and a malformed body comes back as SDK result **203** (a parse
//! error, not a semantic code). That is why every hand-guessed shape 203'd for weeks
//! (`services/gateway/src/azoth_gateway/routes/omni.py`). The body below is written in that order,
//! with the prototype's values: `platformAccount` is the Steam persona account, `account.type` is
//! `shadow` (the official flow for an unlinked Steam account, and what makes the client skip the
//! full-account entitlements path), and the session persona is `account.personaId`.
//!
//! `conflictingAccount` is absent on purpose: the prototype omits it and the client logs
//! `CreateSession result 0` with this exact set, so adding a field nobody asked for would be an
//! unmeasured change to the one shape that is known to work.
//!
//! WHY THE TOKENS ARE JWT-SHAPED WITH AN EMPTY SIGNATURE
//! ====================================================
//! The client's `jwt_reader` requires two dots and parses the payload; the signature is never
//! verified locally, so `alg: none` with an empty third segment parses fine. `iat`/`exp` are in
//! **milliseconds** ("AGS Auth token iat %lldms"), which is why they come from
//! [`crate::identity::now_unix_millis`].
//!
//! WHY THE CREDENTIALS ARE camelCase WITH A NUMERIC `expiration`
//! ===========================================================
//! The game-side credentials parser (`OmniAuthBackend` / `AuthStackCredentialsProvider`) looks up
//! `accessKeyId`, `secretAccessKey`, `sessionToken`, `expiration` and `region` by member name and
//! **crashes** — an access violation reading a parsed double — when one is missing. `expiration` is
//! a unix-seconds **number**, not an ISO string: the old STS-shaped `Expiration` ISO body made the
//! member lookup return null and `NewWorld.exe` died at `+0x7465476` right after
//! `Calling Http API: …/prod/credentials/omni` (`routes/credentials.py`). The PascalCase copies are
//! kept flat beside them for the tools that still read the old shape.

use serde_json::{Value, json};

use crate::identity::{AZOTH_STEAM_ID, Identity, Rng, now_unix_millis, now_unix_seconds};

/// The issuer the access token claims.
const TOKEN_ISSUER: &str = "https://tokenservice.amazongames.com";

/// The audience the access token claims: the game alias the client asked for.
const TOKEN_AUDIENCE: &str = "new-world";

/// The access token's lifetime in seconds, as the prototype reports it in `expiresIn`.
const ACCESS_TOKEN_SECONDS: i64 = 7_200;

/// The credentials' lifetime in seconds: 55 minutes, so a login never races the expiry.
const CREDENTIALS_SECONDS: i64 = 55 * 60;

/// `POST /games/new-world/tokens`: the token set, in OmniSDK's parser order.
#[must_use]
pub fn tokens(identity: &Identity) -> Value {
    let now_ms = now_unix_millis();
    let persona = identity.persona();
    let access = jwt(&json!({
        "sub": persona,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "iat": now_ms,
        "exp": now_ms + ACCESS_TOKEN_SECONDS * 1_000,
    }));
    let fallback = jwt(&json!({
        "sub": persona,
        "refresh": true,
        "iat": now_ms,
        "exp": now_ms + 86_400_000,
    }));
    json!({
        "region": "us-east-1",
        "limitedUseToken": "",
        "platformAccount": {
            "ageGroup": 1,
            "identityType": "steam",
            "platform": "steam",
            "identityId": AZOTH_STEAM_ID,
            "personaId": persona,
        },
        "account": {
            "type": "shadow",
            "ageGroup": 1,
            "identityId": persona,
            "personaId": persona,
        },
        "isNewAccount": false,
        "accessToken": access,
        "expiresIn": ACCESS_TOKEN_SECONDS,
        "fallbackToken": fallback,
    })
}

/// `GET|POST /prod/credentials/omni`: the STS-shaped body with camelCase keys.
#[must_use]
pub fn credentials(identity: &Identity) -> Value {
    let mut rng = Rng::from_clock();
    let access_key = format!("ASIA{}", alnum(&mut rng, 16));
    let secret = alnum(&mut rng, 40);
    let session = alnum(&mut rng, 128);
    // A NUMBER of unix seconds. An ISO string here crashes the client; see the module docs.
    let expiration = now_unix_seconds() + CREDENTIALS_SECONDS;
    let persona = identity.persona();
    json!({
        // The keys the client's parser reads. A missing one is a crash, not an error code.
        "accessKeyId": access_key,
        "secretAccessKey": secret,
        "sessionToken": session,
        "expiration": expiration,
        "region": "us-east-1",
        // Flat legacy copies, kept because other consumers and tools read the old shape.
        "AccessKeyId": access_key,
        "SecretKey": secret,
        "SecretAccessKey": secret,
        "SessionToken": session,
        "Expiration": expiration,
        "type": "Full",
        "accountType": "Full",
        "ownership": "permanent",
        "personaId": persona,
    })
}

/// A JWT-looking token: base64url header, base64url claims, empty signature.
fn jwt(claims: &Value) -> String {
    let header = compact(&json!({ "alg": "none", "typ": "JWT" }));
    format!("{}.{}.", base64url(header.as_bytes()), base64url(
        compact(claims).as_bytes()
    ))
}

/// Serialize without spaces, the way the prototype's `json.dumps(..., separators=(",", ":"))` does.
fn compact(value: &Value) -> String {
    // A `Value` has no non-string keys, so serialization cannot fail; the fallback keeps this total.
    serde_json::to_string(value).unwrap_or_else(|_| String::from("null"))
}

/// The base64url alphabet, without padding: the client's `jwt_reader` splits on `.` only.
const BASE64URL: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

/// Base64url-encode `bytes` with no padding.
fn base64url(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let first = u32::from(chunk[0]);
        let second = chunk.get(1).copied().map_or(0, u32::from);
        let third = chunk.get(2).copied().map_or(0, u32::from);
        let triple = (first << 16) | (second << 8) | third;
        out.push(BASE64URL[(triple >> 18) as usize & 0x3f] as char);
        out.push(BASE64URL[(triple >> 12) as usize & 0x3f] as char);
        if chunk.len() > 1 {
            out.push(BASE64URL[(triple >> 6) as usize & 0x3f] as char);
        }
        if chunk.len() > 2 {
            out.push(BASE64URL[triple as usize & 0x3f] as char);
        }
    }
    out
}

/// `nchars` characters of strict `[A-Za-z0-9]`.
///
/// The charset is the requirement, not the entropy: the prototype's comment records that some
/// clients validate the key charset, and `+`, `/` and `=` are the characters that break them. The
/// modulo bias of a 62-way split is irrelevant to a value nothing verifies.
fn alnum(rng: &mut Rng, nchars: usize) -> String {
    const ALNUM: &[u8; 62] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    (0..nchars)
        .map(|_| ALNUM[(rng.next_u64() % 62) as usize] as char)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64url_matches_python() {
        // Reference values from `base64.urlsafe_b64encode(...).rstrip(b"=")`.
        for (input, expected) in [
            ("f", "Zg"),
            ("fo", "Zm8"),
            ("foo", "Zm9v"),
            ("foob", "Zm9vYg"),
            ("fooba", "Zm9vYmE"),
            ("foobar", "Zm9vYmFy"),
            (r#"{"alg":"none","typ":"JWT"}"#, "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0"),
        ] {
            assert_eq!(base64url(input.as_bytes()), expected, "input {input:?}");
        }
        // The two characters that differ from standard base64, and no padding.
        assert_eq!(base64url(&[0xfb, 0xff]), "-_8");
    }

    #[test]
    fn a_token_has_two_dots_and_no_padding() {
        let token = jwt(&json!({"sub": "x"}));
        assert_eq!(token.matches('.').count(), 2, "jwt_reader needs exactly two dots");
        assert!(token.ends_with('.'), "alg none means an empty signature");
        assert!(!token.contains('='), "padding is not part of the base64url form");
    }

    #[test]
    fn the_claims_round_trip_through_the_token() {
        let token = jwt(&json!({"sub": "amzn1.x", "refresh": true}));
        let payload = token.split('.').nth(1).expect("payload segment");
        // Only ASCII claims are used, so a 4-character-aligned decode is not needed.
        assert_eq!(base64url_decode(payload), r#"{"sub":"amzn1.x","refresh":true}"#);
    }

    #[test]
    fn generated_keys_are_alphanumeric_only() {
        let mut rng = Rng::from_clock();
        let key = alnum(&mut rng, 128);
        assert_eq!(key.len(), 128);
        assert!(key.chars().all(|c| c.is_ascii_alphanumeric()), "{key}");
    }

    /// Decode a base64url string the tests produced. Test-only: the service never decodes.
    fn base64url_decode(input: &str) -> String {
        let mut bits: u32 = 0;
        let mut count = 0;
        let mut out = Vec::new();
        for byte in input.bytes() {
            let value = BASE64URL
                .iter()
                .position(|candidate| *candidate == byte)
                .expect("alphabet") as u32;
            bits = (bits << 6) | value;
            count += 6;
            if count >= 8 {
                count -= 8;
                out.push((bits >> count) as u8);
            }
        }
        String::from_utf8(out).expect("utf8")
    }
}
