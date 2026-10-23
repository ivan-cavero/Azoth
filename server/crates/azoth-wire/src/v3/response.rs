//! The server's reply: the message that flips the client's `rep.ready` to 1.
//!
//! WHY IT IS SEPARATE
//! ==================
//! The reply is built, never parsed, and it is the only thing in the crate that writes an
//! outbound registration record. Keeping it apart from the request keeps the two directions of the
//! exchange from being edited as if they were one layout.
//!
//! The trailer is `00 00 00 00` and not the captured `01 00 00 01` on purpose; the parent module's
//! docs record the measurement (`registration_failed` / `eos_unknown_error`) so nobody "fixes" it
//! back to the captured bytes.

use super::{
    DEFAULT_SERVER_VERSION, RESPONSE_MYSTERY, RESPONSE_TRAILER, RESPONSE_TYPE_BYTE,
    push_len_prefixed,
};
use crate::error::WireError;
use crate::{TYPE_MARKER, varint};

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
