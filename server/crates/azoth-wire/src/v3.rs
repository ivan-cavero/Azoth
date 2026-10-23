//! V3 registration: the client's first message to the world, and the server's reply.
//!
//! WHY THIS EXISTS
//! ===============
//! Before the client will do anything else it sends `RegistrationRequestV3Msg` — a strict
//! **832-byte** body carrying the ticket, the persona, the character and the platform identity —
//! and waits for `RegistrationResponseMsg`, an 88-byte reply that flips its `rep.ready` from 0 to 1.
//! Without that reply the client sits in `WaitingForREPConnection` and times out.
//!
//! This is also where the server **validates the ticket**. The Python prototype accepted any
//! registration and rewrote the character id per session, which is why two private clients were the
//! same player on the wire. The parsed identity here is what makes real validation possible.
//!
//! THE ROUND-TRIP INVARIANT
//! ========================
//! `parse` followed by `encode` must reproduce the input byte for byte. That is not ceremony: the
//! layout has **opaque regions whose meaning is not established** (a 33-byte prelude, eleven gaps
//! between fields, a world-id prefix region, an auth blob), and a parser that discards them cannot
//! prove it read the right bytes. Keeping them verbatim makes the parser falsifiable — if the walk
//! drifts, the round trip fails.
//!
//! THE TWO FORMATS
//! ===============
//! The client sends the strict form on a first attempt and a **retry form** (six tagged records
//! after a 32-byte prelude) on a subsequent one. Both are parsed; [`RegistrationRequest::format`]
//! says which arrived.
//!
//! THE RESPONSE TRAILER IS DELIBERATELY NOT THE CAPTURED ONE
//! ========================================================
//! The official capture carries `01 00 00 01`; this serves `00 00 00 00`. Measured 2026-09-27: the
//! official trailer makes the client fail registration outright with `registration_failed` /
//! `eos_unknown_error` and pop back to the main menu, because it reads as "anti-cheat required".
//! The cleared form is the one that works, and the reason is recorded here so nobody "fixes" it back.

use crate::error::WireError;
use crate::{TYPE_MARKER, varint};

/// The strict body length the client sends.
pub const EXPECTED_BODY_LEN: usize = 832;
/// End of the opaque prelude, and the first field's offset.
const PRELUDE_END: usize = 0x21;
/// Where the 12-byte trailer begins.
const TRAILER_OFF: usize = 0x334;
/// The 12-byte trailer the request must end with.
const REQUEST_TRAILER: [u8; 12] = [
    0x00, 0x43, 0x02, 0x80, 0, 0, 0, 0, 0, 0, 0, 0,
];
/// The response's type byte.
const RESPONSE_TYPE_BYTE: u8 = 0x03;
/// The 8 bytes the captured response carries between the error code and the token length.
const RESPONSE_MYSTERY: [u8; 8] = [0x0B, 0x88, 0x8D, 0x68, 0x70, 0x6C, 0x41, 0x5B];
/// The response trailer that works. See the module docs for why it is not the captured one.
const RESPONSE_TRAILER: [u8; 4] = [0, 0, 0, 0];
/// The server version string that is measured working against this client.
///
/// It names 1.400 because that is what the prototype sends and what the 1.460 client accepts. The
/// 1.460 string is **untested**; changing it would be an unmeasured change to a field the client
/// may compare.
pub const DEFAULT_SERVER_VERSION: &str = "[RETAIL].Javelin.1.400.6031.6004151";

/// Which wire format a request arrived in.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RequestFormat {
    /// The strict 832-byte body.
    Strict,
    /// The six-tagged-record retry body.
    Retry,
}

/// The field schedule of the strict form: `(offset, index into the field array)`.
///
/// The offsets are fixed and measured; they are not derived from the strings, because the strings'
/// lengths vary and the layout does not.
const SCHEDULE: [usize; 12] = [
    0x021, 0x02A, 0x038, 0x044, 0x050, 0x05A, 0x083, 0x0A8, 0x0CD, 0x110, 0x144, 0x157,
];

/// Index of `session_uuid` in [`SCHEDULE`], whose preceding gap is the world-id region.
const SESSION_UUID_SLOT: usize = 7;

/// The client's V3 registration request.
///
/// Every string is kept as raw bytes: the wire is latin-1 and byte-preserving, so storing `Vec<u8>`
/// makes the round trip exact and lets the accessors decide how to interpret a field.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RegistrationRequest {
    /// Which format arrived.
    pub format: RequestFormat,
    /// The opaque 33-byte prelude (strict) or 32-byte prelude (retry).
    pub prelude: Vec<u8>,
    /// The twelve length-prefixed strings, in schedule order.
    pub fields: [Vec<u8>; 12],
    /// The eleven opaque gaps between consecutive fields (strict only).
    ///
    /// The gap before `session_uuid` is stored in [`Self::world_id_region`] instead, because the
    /// world-id prefix region is named and the others are not.
    pub gaps: Vec<Vec<u8>>,
    /// The opaque region that precedes `session_uuid`.
    pub world_id_region: Vec<u8>,
    /// Everything between the last field and the trailer (strict only).
    pub auth_blob: Vec<u8>,
    /// The trailing bytes.
    pub trailer: Vec<u8>,
    /// The retry form's six tagged records, when that format arrived.
    pub retry_records: Vec<(u32, Vec<u8>)>,
    /// The retry form's tail after the tagged records.
    pub retry_tail: Vec<u8>,
}

/// Field indices, named so the accessors do not index with magic numbers.
mod field {
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

impl RegistrationRequest {
    /// A field as ASCII, or `None` when it is not valid UTF-8.
    ///
    /// The wire is latin-1; these fields are ASCII in every capture, so a non-ASCII value means the
    /// parse is wrong rather than that the client sent something exotic.
    #[must_use]
    pub fn field_str(&self, index: usize) -> Option<&str> {
        std::str::from_utf8(&self.fields[index]).ok()
    }

    /// The character id, which is what the world binds the session to.
    ///
    /// **Not a schedule field.** The character id lives in the opaque `auth_blob` on this build: the
    /// capture's schedule has no character slot, and the prototype recovers it from the auth region.
    /// Returning `None` is honest — a caller must not guess.
    #[must_use]
    pub fn character_id(&self) -> Option<&str> {
        find_uuid(&self.auth_blob)
    }

    /// The persona id.
    #[must_use]
    pub fn persona_id(&self) -> Option<&str> {
        self.field_str(field::PERSONA_ID)
    }

    /// The session UUID, or the ticket UUID when the retry form omitted it.
    ///
    /// Measured: all 883 captured 1.400 retry bodies carry the session UUID inside the ticket
    /// signature, so the signature is the authoritative identity when the field is absent.
    #[must_use]
    pub fn session_uuid(&self) -> Option<&str> {
        match self.field_str(field::SESSION_UUID) {
            Some(value) if !value.is_empty() => Some(value),
            _ => self.ticket_uuid(),
        }
    }

    /// The ticket UUID, stripped of its `sig:` prefix.
    #[must_use]
    pub fn ticket_uuid(&self) -> Option<&str> {
        self.field_str(field::CLIENT_SIGNATURE)
            .map(|value| value.strip_prefix("sig:").unwrap_or(value))
    }

    /// The opaque 21-byte region that precedes `session_uuid`, as raw bytes.
    ///
    /// **It is not a world id, and a world id cannot be recovered from it.** The region is
    /// `0x93..0xA8`, twenty-one bytes, while a UUID string needs thirty-six; the prototype's own
    /// name for it is `unknown_worldid_region` — a *prefix*. The authoritative world id comes from
    /// the login **ticket** (`LoginTicket.WorldId`), and the session's world is whatever the ticket
    /// said. This accessor exists so a caller can log the bytes and so the round trip stays exact.
    #[must_use]
    pub fn world_id_region(&self) -> &[u8] {
        &self.world_id_region
    }

    /// The platform app tag, e.g. `STEAM_APP_ID.1063730`.
    #[must_use]
    pub fn platform_app_tag(&self) -> Option<&str> {
        self.field_str(field::PLATFORM_APP_TAG)
    }

    /// Encode back to the wire form.
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] when a field exceeds 255 bytes, which the `u8` length cannot carry.
    pub fn encode(&self) -> Result<Vec<u8>, WireError> {
        if self.format == RequestFormat::Retry {
            let mut out = self.prelude.clone();
            for (type_id, value) in &self.retry_records {
                out.extend_from_slice(&type_id.to_be_bytes());
                push_len_prefixed(&mut out, value)?;
            }
            out.extend_from_slice(&self.retry_tail);
            return Ok(out);
        }

        let mut out = self.prelude.clone();
        for (index, offset) in SCHEDULE.iter().enumerate() {
            if index > 0 {
                if index == SESSION_UUID_SLOT {
                    out.extend_from_slice(&self.world_id_region);
                } else {
                    let gap = self.gaps.get(index - 1);
                    out.extend_from_slice(gap.map(Vec::as_slice).unwrap_or_default());
                }
            }
            debug_assert_eq!(out.len(), *offset, "schedule drift at field {index}");
            push_len_prefixed(&mut out, &self.fields[index])?;
        }
        out.extend_from_slice(&self.auth_blob);
        out.extend_from_slice(&self.trailer);
        Ok(out)
    }
}

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

/// The server's reply: the message that flips the client's `rep.ready` to 1.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RegistrationResponse {
    /// The 32-byte session token.
    pub session_token: [u8; 32],
    /// The server version string the client displays.
    pub server_version: String,
    /// Error code; 0 means success.
    pub error_code: i32,
}

impl RegistrationResponse {
    /// A successful response carrying `session_token`.
    ///
    /// # Errors
    /// [`WireError::LengthMismatch`] when the token is not exactly 32 bytes.
    pub fn success(session_token: [u8; 32]) -> Self {
        Self {
            session_token,
            server_version: DEFAULT_SERVER_VERSION.to_string(),
            error_code: 0,
        }
    }

    /// Encode the response body.
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] when the version string exceeds 255 bytes.
    pub fn encode(&self) -> Result<Vec<u8>, WireError> {
        let mut out = Vec::with_capacity(88);
        out.extend_from_slice(&TYPE_MARKER);
        out.push(RESPONSE_TYPE_BYTE);
        out.extend_from_slice(&self.error_code.to_be_bytes());
        out.extend_from_slice(&RESPONSE_MYSTERY);
        out.push(0x20); // token length
        out.extend_from_slice(&self.session_token);
        push_len_prefixed(&mut out, self.server_version.as_bytes())?;
        out.extend_from_slice(&RESPONSE_TRAILER);
        Ok(out)
    }

    /// Encode as the record the client expects: a VLQ32 length, then the body.
    ///
    /// The VLQ prefix is **required**. Measured 2026-09-20: the un-prefixed form dies with
    /// `registration_unmarshal_error` before the client ever reaches `InGame`.
    ///
    /// # Errors
    /// Propagates an encode error.
    pub fn encode_record(&self) -> Result<Vec<u8>, WireError> {
        let body = self.encode()?;
        let mut out = varint::encode(body.len() as u64)?;
        out.extend_from_slice(&body);
        Ok(out)
    }
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
fn push_len_prefixed(out: &mut Vec<u8>, value: &[u8]) -> Result<(), WireError> {
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
fn find_uuid(data: &[u8]) -> Option<&str> {
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

    /// Build a strict body with the given field values, padding the opaque regions with a marker.
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

    #[test]
    fn the_strict_body_is_832_bytes() {
        assert_eq!(strict_body(sample_fields()).len(), EXPECTED_BODY_LEN);
    }

    #[test]
    fn strict_round_trips_byte_for_byte() {
        let body = strict_body(sample_fields());
        let parsed = parse(&body).expect("parses");
        assert_eq!(parsed.format, RequestFormat::Strict);
        assert_eq!(parsed.encode().expect("encodes"), body);
    }

    #[test]
    fn the_identity_fields_are_readable() {
        let parsed = parse(&strict_body(sample_fields())).expect("parses");
        assert_eq!(parsed.persona_id(), Some("amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c"));
        assert_eq!(parsed.ticket_uuid(), Some("01234567-89ab-4cde-8f01-23456789abcd"));
        assert_eq!(parsed.session_uuid(), Some("01234567-89ab-4cde-8f01-23456789abcd"));
        assert_eq!(parsed.platform_app_tag(), Some("STEAM_APP_ID.1063730"));
        assert_eq!(parsed.field_str(field::SDK_NAME), Some("Javelin"));
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
    fn a_short_body_is_rejected() {
        let err = parse(&[0u8; 100]).expect_err("must fail");
        assert!(matches!(err, WireError::LengthMismatch { .. }), "{err}");
    }

    #[test]
    fn a_body_without_the_trailer_is_rejected() {
        let mut body = strict_body(sample_fields());
        let last = body.len() - 1;
        body[last] = 0xFF;
        assert!(parse(&body).is_err());
    }

    #[test]
    fn the_response_carries_the_token_and_a_length_prefix() {
        let response = RegistrationResponse::success([0x5A; 32]);
        let body = response.encode().expect("encodes");
        assert_eq!(&body[..2], &TYPE_MARKER);
        assert_eq!(body[2], RESPONSE_TYPE_BYTE);
        assert_eq!(&body[3..7], &0i32.to_be_bytes());
        assert_eq!(body[15], 0x20, "token length byte");
        assert_eq!(&body[16..48], &[0x5A; 32]);
        // The record form prefixes the body with its length.
        let record = response.encode_record().expect("encodes");
        assert_eq!(record[0] as usize, body.len(), "VLQ32 length prefix");
        assert_eq!(&record[1..], body.as_slice());
    }

    #[test]
    fn the_response_trailer_is_cleared_not_captured() {
        // The captured `01 00 00 01` makes the client fail registration with
        // registration_failed / eos_unknown_error. This pins the working form.
        let body = RegistrationResponse::success([0; 32]).encode().expect("encodes");
        assert_eq!(&body[body.len() - 4..], &[0, 0, 0, 0]);
    }

    #[test]
    fn the_retry_form_is_recognised_and_round_trips() {
        // 32-byte prelude, six tagged records, then a separator and identity strings.
        let mut body = vec![0x11; 32];
        let records: [(u32, &[u8]); 6] = [
            (0, b"[RETAIL]"),
            (1, b"Javelin"),
            (2, b""),
            (3, b"400"),
            (4, b"6033"),
            (5, b"6024067x"),
        ];
        for (type_id, value) in records {
            body.extend_from_slice(&type_id.to_be_bytes());
            body.push(value.len() as u8);
            body.extend_from_slice(value);
        }
        body.push(0x00); // separator
        for value in [
            &b"sig:01234567-89ab-4cde-8f01-23456789abcd"[..],
            b"127.0.0.1:27000",
            b"STEAM_APP_ID.1063730",
            b"76561197960287930",
            b"01234567-89ab-4cde-8f01-23456789abcd",
        ] {
            body.push(value.len() as u8);
            body.extend_from_slice(value);
        }

        let parsed = parse(&body).expect("parses");
        assert_eq!(parsed.format, RequestFormat::Retry);
        assert_eq!(parsed.field_str(field::SDK_NAME), Some("Javelin"));
        assert_eq!(parsed.ticket_uuid(), Some("01234567-89ab-4cde-8f01-23456789abcd"));
        assert_eq!(parsed.encode().expect("encodes"), body);
    }

    #[test]
    fn a_retry_form_with_missing_tags_is_rejected() {
        let mut body = vec![0x11; 32];
        for type_id in [0u32, 1, 2, 3, 4] {
            // only five records
            body.extend_from_slice(&type_id.to_be_bytes());
            body.push(1);
            body.push(b'x');
        }
        assert!(parse(&body).is_err());
    }

    #[test]
    fn the_uuid_shape_is_strict() {
        assert!(is_uuid("01234567-89ab-4cde-8f01-23456789abcd"));
        assert!(!is_uuid("01234567-89ab-4cde-8f01-23456789abc")); // short
        assert!(!is_uuid("0123456789ab4cde8f0123456789abcd0")); // no dashes
        assert!(!is_uuid("01234567-89ab-4cde-8f01-23456789abcg")); // non-hex
    }
}
