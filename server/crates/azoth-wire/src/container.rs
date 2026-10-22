//! The two typed-record containers: the client's and the server's.
//!
//! THEY ARE NOT THE SAME, AND BOTH MATTER
//! ======================================
//! Every non-chunked DATA record the CLIENT sends on channels 0 and 1 is:
//!
//! ```text
//! u32 BE  crc32(payload)
//! u32 BE  len(payload)
//! payload = [16-byte target id][00 01][prefix-varint wire type][body]
//! ```
//!
//! Verified over one live session: 285/294 channel-0 records and **40,279 of
//! 40,279** channel-1 records satisfy BOTH the CRC and the length field
//! (`research/docs/JAVELIN-PROTOCOL.md` §1f). Re-measured on 1.460: 229,304 of
//! 229,304 channel-1 records pass both.
//!
//! The SERVER does not use this container. Its records are
//! `[prefix-varint len][00 01][type][body]`, and the client accepts that form on
//! channel 0.
//!
//! WHY THE DISTINCTION IS WORTH A MODULE
//! =====================================
//! The client's container is **self-validating**: a wrong walk shows up as a
//! length mismatch or a CRC mismatch instead of as silently wrong offsets. That
//! makes it the best available check that a parser is aligned, which is exactly
//! what the parity harness needs. A server that guessed at the container and got
//! the CRC field's endianness wrong would produce records the client silently
//! drops.
//!
//! The CRC is IEEE 802.3 (the zlib/PNG polynomial), reflected, init and final
//! XOR `0xFFFF_FFFF`. It is implemented here rather than pulled from a crate
//! because it is twenty lines and this crate's dependency tree is deliberately
//! empty.

use crate::error::WireError;
use crate::varint;
use crate::TYPE_MARKER;

/// Size of the client container's fixed prefix: `crc32` + `len`.
const CLIENT_PREFIX: usize = 8;
/// Size of the 16-byte target actor id.
pub const TARGET_ID_SIZE: usize = 16;

/// The CRC-32/ISO-HDLC table, built once at first use.
///
/// A `const fn` table would be neater, but the loop form keeps the polynomial
/// visible next to the code that uses it.
const fn make_table() -> [u32; 256] {
    let mut table = [0u32; 256];
    let mut i = 0;
    while i < 256 {
        let mut crc = i as u32;
        let mut bit = 0;
        while bit < 8 {
            crc = if crc & 1 != 0 {
                (crc >> 1) ^ 0xEDB8_8320
            } else {
                crc >> 1
            };
            bit += 1;
        }
        table[i] = crc;
        i += 1;
    }
    table
}

static CRC_TABLE: [u32; 256] = make_table();

/// CRC-32/ISO-HDLC over `data`, as the client computes it.
#[must_use]
pub fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for &byte in data {
        let index = ((crc ^ u32::from(byte)) & 0xFF) as usize;
        crc = (crc >> 8) ^ CRC_TABLE[index];
    }
    crc ^ 0xFFFF_FFFF
}

/// A parsed client-container record.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClientRecord<'a> {
    /// The 16-byte target actor id.
    pub target: [u8; TARGET_ID_SIZE],
    /// The typed wire type, decoded from the prefix varint.
    pub wire_type: u64,
    /// The message body, after the type varint.
    pub body: &'a [u8],
}

/// Parse the client's `[crc32][len][target][00 01][varint type][body]` container.
///
/// Both self-validating fields are checked, and a mismatch is an error rather
/// than a warning: the whole value of this container is that it catches a
/// misaligned parse.
///
/// # Errors
/// [`WireError::Truncated`] for a short buffer, [`WireError::LengthMismatch`]
/// when the length field disagrees, [`WireError::CrcMismatch`] when the CRC does
/// not cover the payload, and the varint errors from the type field.
pub fn parse_client(payload: &[u8]) -> Result<ClientRecord<'_>, WireError> {
    if payload.len() < CLIENT_PREFIX {
        return Err(WireError::truncated(
            "client container prefix",
            CLIENT_PREFIX,
            payload.len(),
        ));
    }
    let declared_crc = u32::from_be_bytes([payload[0], payload[1], payload[2], payload[3]]);
    let declared_len = u32::from_be_bytes([payload[4], payload[5], payload[6], payload[7]]);
    let rest = &payload[CLIENT_PREFIX..];
    if declared_len as usize != rest.len() {
        return Err(WireError::LengthMismatch {
            declared: declared_len as usize,
            actual: rest.len(),
        });
    }
    let actual_crc = crc32(rest);
    if actual_crc != declared_crc {
        return Err(WireError::CrcMismatch {
            declared: declared_crc,
            computed: actual_crc,
        });
    }
    if rest.len() < TARGET_ID_SIZE + 2 {
        return Err(WireError::truncated(
            "client container target",
            TARGET_ID_SIZE + 2,
            rest.len(),
        ));
    }
    let mut target = [0u8; TARGET_ID_SIZE];
    target.copy_from_slice(&rest[..TARGET_ID_SIZE]);
    let marker = &rest[TARGET_ID_SIZE..TARGET_ID_SIZE + 2];
    if marker != TYPE_MARKER {
        let mut found = [0u8; 2];
        found.copy_from_slice(marker);
        return Err(WireError::MissingTypeMarker { found });
    }
    let (wire_type, after_type) = varint::decode(rest, TARGET_ID_SIZE + 2)?;
    Ok(ClientRecord {
        target,
        wire_type,
        body: &rest[after_type..],
    })
}

/// Encode the client's container around `body`.
///
/// # Errors
/// Propagates a varint range error for `wire_type`.
pub fn encode_client(
    target: &[u8; TARGET_ID_SIZE],
    wire_type: u64,
    body: &[u8],
) -> Result<Vec<u8>, WireError> {
    let mut inner = Vec::with_capacity(TARGET_ID_SIZE + 3 + body.len());
    inner.extend_from_slice(target);
    inner.extend_from_slice(&TYPE_MARKER);
    varint::encode_into(wire_type, &mut inner)?;
    inner.extend_from_slice(body);

    let mut out = Vec::with_capacity(CLIENT_PREFIX + inner.len());
    out.extend_from_slice(&crc32(&inner).to_be_bytes());
    let len = u32::try_from(inner.len()).map_err(|_| WireError::OutOfRange {
        field: "client container length",
        value: inner.len() as u64,
        limit: u64::from(u32::MAX) + 1,
    })?;
    out.extend_from_slice(&len.to_be_bytes());
    out.extend_from_slice(&inner);
    Ok(out)
}

/// Parse the SERVER's `[prefix-varint len][00 01][type][body]` container.
///
/// Note the difference from the client's: no CRC, no target id, and the length
/// is a prefix varint rather than a fixed u32. The length covers the marker, the
/// type and the body.
///
/// # Errors
/// [`WireError::Truncated`], [`WireError::MissingTypeMarker`],
/// [`WireError::LengthMismatch`], or a varint error.
pub fn parse_server(payload: &[u8]) -> Result<(u64, &[u8]), WireError> {
    let (declared, after_len) = varint::decode(payload, 0)?;
    let rest = &payload[after_len..];
    if declared as usize != rest.len() {
        return Err(WireError::LengthMismatch {
            declared: declared as usize,
            actual: rest.len(),
        });
    }
    if rest.len() < 2 {
        return Err(WireError::truncated("server container marker", 2, rest.len()));
    }
    let found = [rest[0], rest[1]];
    if found != TYPE_MARKER {
        return Err(WireError::MissingTypeMarker { found });
    }
    let (wire_type, after_type) = varint::decode(rest, 2)?;
    Ok((wire_type, &rest[after_type..]))
}

/// Encode the SERVER's container around `body`.
///
/// # Errors
/// Propagates a varint range error.
pub fn encode_server(wire_type: u64, body: &[u8]) -> Result<Vec<u8>, WireError> {
    let mut inner = TYPE_MARKER.to_vec();
    varint::encode_into(wire_type, &mut inner)?;
    inner.extend_from_slice(body);
    let mut out = Vec::with_capacity(inner.len() + 5);
    varint::encode_into(inner.len() as u64, &mut out)?;
    out.extend_from_slice(&inner);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The reference CRC of "123456789" is 0xCBF43926 for CRC-32/ISO-HDLC.
    /// A wrong polynomial or a missing final XOR fails this immediately.
    #[test]
    fn crc32_matches_the_reference_vector() {
        assert_eq!(crc32(b"123456789"), 0xCBF4_3926);
    }

    #[test]
    fn crc32_of_empty_is_zero() {
        assert_eq!(crc32(b""), 0);
    }

    #[test]
    fn round_trips_the_client_container() {
        let target = [0xABu8; TARGET_ID_SIZE];
        let encoded = encode_client(&target, 0x635, &[1, 2, 3]).expect("encodes");
        let parsed = parse_client(&encoded).expect("parses");
        assert_eq!(parsed.target, target);
        assert_eq!(parsed.wire_type, 0x635);
        assert_eq!(parsed.body, &[1, 2, 3]);
    }

    #[test]
    fn detects_a_crc_mismatch() {
        let target = [0u8; TARGET_ID_SIZE];
        let mut encoded = encode_client(&target, 0x635, &[1, 2, 3]).expect("encodes");
        let last = encoded.len() - 1;
        encoded[last] ^= 0xFF; // corrupt the body, leave the CRC
        let err = parse_client(&encoded).expect_err("must fail");
        assert!(matches!(err, WireError::CrcMismatch { .. }), "{err}");
    }

    #[test]
    fn detects_a_length_mismatch() {
        let target = [0u8; TARGET_ID_SIZE];
        let mut encoded = encode_client(&target, 0x635, &[1, 2, 3]).expect("encodes");
        encoded[7] = encoded[7].wrapping_add(1);
        let err = parse_client(&encoded).expect_err("must fail");
        assert!(matches!(err, WireError::LengthMismatch { .. }), "{err}");
    }

    #[test]
    fn round_trips_the_server_container() {
        let encoded = encode_server(0x16a0, &[9, 9]).expect("encodes");
        let (wire_type, body) = parse_server(&encoded).expect("parses");
        assert_eq!(wire_type, 0x16a0);
        assert_eq!(body, &[9, 9]);
    }

    #[test]
    fn the_two_containers_differ_in_shape() {
        let target = [0u8; TARGET_ID_SIZE];
        let client = encode_client(&target, 1, &[]).expect("encodes");
        let server = encode_server(1, &[]).expect("encodes");
        // The client's carries 8 bytes of crc+len and 16 of target; the server's
        // carries a one-byte length. They must never be interchangeable.
        assert_eq!(client.len(), 8 + 16 + 2 + 1);
        assert_eq!(server.len(), 1 + 2 + 1);
        assert!(parse_server(&client).is_err());
    }
}
