//! The walk that turns a V3 registration body into a [`RegistrationRequest`], plus its helpers.
//!
//! WHY IT IS SEPARATE FROM THE TYPES
//! ================================
//! The walk is positional: it follows the fixed offset schedule, keeps every opaque gap verbatim so
//! that `parse` → `encode` reproduces the input byte for byte, and recognises the retry form by its
//! six tagged records. Naming a request's fields is a different job, and this is the half that
//! drifts when a client build changes, so it sits alone in one file. The types, the two formats and
//! the reason the round trip matters are documented in the parent module.
//!
//! The `field` index names live here because the schedule they index is what this walk reads.

use super::{
    EXPECTED_BODY_LEN, PRELUDE_END, REQUEST_TRAILER, RegistrationRequest, RequestFormat, SCHEDULE,
    SESSION_UUID_SLOT, TRAILER_OFF,
};
use crate::error::WireError;

/// Parse a V3 registration body, accepting either format.
///
/// # Errors
/// [`WireError::LengthMismatch`] when the body is neither 832 bytes nor a valid retry body, and
/// [`WireError::Truncated`] when a length-prefixed string overruns.
pub fn parse(body: &[u8]) -> Result<RegistrationRequest, WireError> {
    if body.len() == EXPECTED_BODY_LEN && body.ends_with(&REQUEST_TRAILER) {
        return parse_strict(body);
    }
    parse_retry(body).ok_or(WireError::LengthMismatch {
        declared: EXPECTED_BODY_LEN,
        actual: body.len(),
    })
}

/// Parse the strict 832-byte form.
fn parse_strict(body: &[u8]) -> Result<RegistrationRequest, WireError> {
    let mut fields: [Vec<u8>; 12] = std::array::from_fn(|_| Vec::new());
    let mut gaps: Vec<Vec<u8>> = Vec::with_capacity(11);
    let mut cursor = PRELUDE_END;

    for (index, offset) in SCHEDULE.iter().enumerate() {
        if index > 0 {
            if cursor > *offset {
                return Err(WireError::LengthMismatch {
                    declared: *offset,
                    actual: cursor,
                });
            }
            gaps.push(body[cursor..*offset].to_vec());
        }
        let (value, next) = read_len_prefixed(body, *offset)?;
        fields[index] = value;
        cursor = next;
    }
    if cursor > TRAILER_OFF {
        return Err(WireError::LengthMismatch {
            declared: TRAILER_OFF,
            actual: cursor,
        });
    }

    // The gap before `session_uuid` IS the world-id region. Naming it separately is what lets
    // `world_id()` find it, and the gap list keeps its slot empty so the schedule stays aligned.
    let world_id_region = gaps[SESSION_UUID_SLOT - 1].clone();
    gaps[SESSION_UUID_SLOT - 1] = Vec::new();

    Ok(RegistrationRequest {
        format: RequestFormat::Strict,
        prelude: body[..PRELUDE_END].to_vec(),
        fields,
        gaps,
        world_id_region,
        auth_blob: body[cursor..TRAILER_OFF].to_vec(),
        trailer: body[TRAILER_OFF..].to_vec(),
        retry_records: Vec::new(),
        retry_tail: Vec::new(),
    })
}

/// Parse the retry form: a 32-byte prelude, six `(u32 type, u8 len, value)` records, then a tail.
fn parse_retry(body: &[u8]) -> Option<RegistrationRequest> {
    const PRELUDE_LEN: usize = 32;
    if body.len() < PRELUDE_LEN + 6 * 5 {
        return None;
    }
    let mut records: Vec<(u32, Vec<u8>)> = Vec::with_capacity(6);
    let mut offset = PRELUDE_LEN;
    for _ in 0..6 {
        if offset + 5 > body.len() {
            return None;
        }
        let type_id = u32::from_be_bytes(body[offset..offset + 4].try_into().ok()?);
        if type_id > 0xFFFF {
            return None;
        }
        let (value, next) = read_len_prefixed(body, offset + 4).ok()?;
        records.push((type_id, value));
        offset = next;
    }
    let seen: std::collections::BTreeSet<u32> = records.iter().map(|(id, _)| *id).collect();
    if seen != (0..=5).collect() {
        return None;
    }

    let mut fields: [Vec<u8>; 12] = std::array::from_fn(|_| Vec::new());
    for (type_id, value) in &records {
        match type_id {
            0 => fields[field::BUILD_FLAVOR].clone_from(value),
            1 => fields[field::SDK_NAME].clone_from(value),
            3 => fields[field::UNKNOWN_400].clone_from(value),
            4 => fields[field::BUILD_VERSION].clone_from(value),
            5 => fields[field::SDK_VERSION_RAW].clone_from(value),
            _ => {}
        }
    }

    let tail = body[offset..].to_vec();
    // The identity fields follow one separator byte, then a run of length-prefixed values. Fixed
    // offsets are NOT stable: a live client may insert a bare persona UUID between `character_id`
    // and `session_uuid`, so the walk is positional and stops at the first zero length.
    let mut walk = 1usize;
    for slot in [
        field::CLIENT_SIGNATURE,
        field::CLIENT_ENDPOINT,
        field::PLATFORM_APP_TAG,
        field::PLATFORM_USER_ID,
    ] {
        let Some((value, next)) = read_len_prefixed(&tail, walk).ok() else {
            break;
        };
        fields[slot] = value;
        walk = next;
    }
    // The remaining length-prefixed values are the session and character ids; take the ones that
    // look like UUIDs, in order.
    let mut uuids: Vec<Vec<u8>> = Vec::new();
    while walk < tail.len() {
        let Ok((value, next)) = read_len_prefixed(&tail, walk) else {
            break;
        };
        if value.is_empty() {
            break;
        }
        if find_uuid(&value).is_some() {
            uuids.push(value);
        }
        walk = next;
    }
    if let Some(first) = uuids.first() {
        fields[field::SESSION_UUID].clone_from(first);
    }

    Some(RegistrationRequest {
        format: RequestFormat::Retry,
        prelude: body[..PRELUDE_LEN].to_vec(),
        fields,
        gaps: Vec::new(),
        world_id_region: Vec::new(),
        auth_blob: Vec::new(),
        trailer: Vec::new(),
        retry_records: records,
        retry_tail: tail,
    })
}

/// Field indices, named so the accessors and the walk do not index with magic numbers.
pub(super) mod field {
    /// Build version, e.g. `6031`.
    pub const BUILD_VERSION: usize = 0;
    /// An unknown `400` string.
    pub const UNKNOWN_400: usize = 1;
    /// The SDK name, e.g. `Javelin`.
    pub const SDK_NAME: usize = 2;
    /// The SDK version plus one trailing byte.
    pub const SDK_VERSION_RAW: usize = 3;
    /// The build flavor, e.g. `[RETAIL]`.
    pub const BUILD_FLAVOR: usize = 4;
    /// The ticket signature, e.g. `sig:<ticket-uuid>`.
    pub const CLIENT_SIGNATURE: usize = 5;
    /// The client's endpoint, e.g. `127.0.0.1:<port>`.
    pub const CLIENT_ENDPOINT: usize = 6;
    /// The session UUID.
    pub const SESSION_UUID: usize = 7;
    /// The persona id.
    pub const PERSONA_ID: usize = 8;
    /// The platform app tag, e.g. `STEAM_APP_ID.1063730`.
    pub const PLATFORM_APP_TAG: usize = 9;
    /// The Steam id.
    pub const PLATFORM_USER_ID: usize = 10;
    /// The platform name blob.
    pub const PLATFORM_NAME_BLOB: usize = 11;
}

/// Read a `u8`-length-prefixed string at `offset`.
fn read_len_prefixed(data: &[u8], offset: usize) -> Result<(Vec<u8>, usize), WireError> {
    let len = *data
        .get(offset)
        .ok_or_else(|| WireError::truncated("v3 string length", 1, 0))?;
    let start = offset + 1;
    let end = start + usize::from(len);
    if end > data.len() {
        return Err(WireError::truncated(
            "v3 string",
            usize::from(len),
            data.len().saturating_sub(start),
        ));
    }
    Ok((data[start..end].to_vec(), end))
}

/// Append a `u8`-length-prefixed string.
pub(super) fn push_len_prefixed(out: &mut Vec<u8>, value: &[u8]) -> Result<(), WireError> {
    let len = u8::try_from(value.len()).map_err(|_| WireError::OutOfRange {
        field: "v3 string",
        value: value.len() as u64,
        limit: 256,
    })?;
    out.push(len);
    out.extend_from_slice(value);
    Ok(())
}

/// Find the first `8-4-4-4-12` hex UUID inside `data`.
///
/// The identity fields sit inside opaque regions whose internal layout is not decoded, so the UUID
/// is located by its shape. That is a heuristic, and it is labelled as one: it works because a
/// UUID's shape is unambiguous in these buffers, but a caller that needs certainty should use a
/// named schedule field.
pub(super) fn find_uuid(data: &[u8]) -> Option<&str> {
    let text = std::str::from_utf8(data).ok()?;
    let bytes = text.as_bytes();
    if bytes.len() < 36 {
        return None;
    }
    for start in 0..=bytes.len() - 36 {
        let candidate = &text[start..start + 36];
        if is_uuid(candidate) {
            return Some(candidate);
        }
    }
    None
}

/// Whether `text` has the exact `8-4-4-4-12` hex shape.
fn is_uuid(text: &str) -> bool {
    let bytes = text.as_bytes();
    if bytes.len() != 36 {
        return false;
    }
    for (index, byte) in bytes.iter().enumerate() {
        let ok = match index {
            8 | 13 | 18 | 23 => *byte == b'-',
            _ => byte.is_ascii_hexdigit(),
        };
        if !ok {
            return false;
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The two tests here assert on `find_uuid`/`is_uuid`, which are private to this file, so an
    /// integration test cannot reach them. Everything expressible through the public API lives in
    /// `tests/v3_layouts.rs`; these two stay, with the fixture builder they need, rather than
    /// widening the crate's public surface for a test.
    fn strict_body(fields: [&[u8]; 12]) -> Vec<u8> {
        let mut out = vec![0xAA; PRELUDE_END];
        for (index, offset) in SCHEDULE.iter().enumerate() {
            while out.len() < *offset {
                out.push(0xBB); // an opaque gap
            }
            assert_eq!(out.len(), *offset);
            out.push(fields[index].len() as u8);
            out.extend_from_slice(fields[index]);
        }
        while out.len() < TRAILER_OFF {
            out.push(0xCC); // the auth blob
        }
        out.extend_from_slice(&REQUEST_TRAILER);
        out
    }

    /// The field values of a real capture, because the offsets only line up for their lengths:
    /// the gap before `session_uuid` is 21 bytes only when the endpoint field is 15 characters.
    fn sample_fields() -> [&'static [u8]; 12] {
        [
            b"6033",
            b"400",
            b"Javelin",
            b"6024067x",
            b"[RETAIL]",
            b"sig:01234567-89ab-4cde-8f01-23456789abcd",
            b"127.0.0.1:27000",
            b"01234567-89ab-4cde-8f01-23456789abcd",
            b"amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c",
            b"STEAM_APP_ID.1063730",
            b"76561197960287930",
            b"steam|14",
        ]
    }

    /// The region before `session_uuid` is 21 bytes and is NOT a world id.
    ///
    /// This test exists because the first version of this module exposed a `world_id()` accessor
    /// that searched the region for a UUID — which can never succeed, since a UUID string needs 36
    /// bytes and the region holds 21. The authoritative world comes from the login ticket.
    #[test]
    fn the_world_id_region_is_a_prefix_not_an_id() {
        let parsed = parse(&strict_body(sample_fields())).expect("parses");
        assert_eq!(
            parsed.world_id_region().len(),
            0xA8 - 0x93,
            "the region is 21 bytes; a UUID string needs 36, so it cannot hold one"
        );
        assert!(
            find_uuid(parsed.world_id_region()).is_none(),
            "no UUID can fit, so no accessor should claim to find one"
        );
    }

    #[test]
    fn the_uuid_shape_is_strict() {
        assert!(is_uuid("01234567-89ab-4cde-8f01-23456789abcd"));
        assert!(!is_uuid("01234567-89ab-4cde-8f01-23456789abc")); // short
        assert!(!is_uuid("0123456789ab4cde8f0123456789abcd0")); // no dashes
        assert!(!is_uuid("01234567-89ab-4cde-8f01-23456789abcg")); // non-hex
    }
}
