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
//!
//! WHY THIS IS THREE FILES
//! =======================
//! The boundary is responsibility, not length. This file is the vocabulary a caller touches: the
//! measured constants, the two formats, and [`RegistrationRequest`] with its accessors and its
//! encoder. The walk that turns bytes into a request — the offset schedule's index names and the
//! UUID heuristic included — lives in `parse`, because only a parser needs it and it is the part
//! that drifts when a build changes. The reply the server builds lives in `response`. Both are
//! re-exported here, so `azoth_wire::v3::parse` and `azoth_wire::v3::RegistrationResponse` resolve
//! exactly as they did when this was one file. The byte assertions moved to `tests/v3_layouts.rs`
//! for the same reason they sit outside `presence.rs`: they exercise only the public API.

use crate::error::WireError;

use self::parse::{field, find_uuid, push_len_prefixed};

mod parse;
mod response;

pub use self::parse::parse;
pub use self::response::RegistrationResponse;

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
