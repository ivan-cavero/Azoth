//! ETags, `If-None-Match`, and `Cache-Control`.
//!
//! WHY AN ETAG IS NOT OPTIONAL HERE
//! ================================
//! A CMS response without an ETag **crashes the client** (`routes/cms.py`, and the module doc in
//! `docs/CLIENT_CONTRACT.md` says so for the MOTD route too). It is not a caching nicety in this
//! stack; it is a required header.
//!
//! WHAT THE ETAG IS FOR
//! ====================
//! Two jobs, and the second is the interesting one:
//!
//! * it lets the client skip a re-download, which matters because the news metadata route was
//!   requested **4,339** times in the measured inventory;
//! * it is the **change signal** that makes a region change live. The channel document's ETag is
//!   derived from its rendered bytes, so opening a region changes the tag, the client re-reads, and
//!   the new region appears — with no client restart and no redeploy.
//!
//! THE ALGORITHM
//! =============
//! FNV-1a 64-bit, rendered as a quoted 16-hex-digit strong tag. Not a cryptographic hash, and it
//! does not need to be: the requirement is "changes when the bytes change", not "cannot be forged".
//! A route the client polls is the wrong place to spend SHA-256.
//!
//! It deliberately does **not** match the Python prototype, which uses MD5. The client requires a
//! tag, not a particular algorithm; matching would be cargo-culting a hash choice rather than
//! honouring a contract.

/// Compute a strong ETag for `body`: a quoted 16-hex-digit FNV-1a 64 digest.
#[must_use]
pub fn etag_for(body: &[u8]) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for &byte in body {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("\"{hash:016x}\"")
}

/// Whether an `If-None-Match` header value matches `etag`.
///
/// Handles the forms the client actually sends and the ones RFC 9110 defines that it might:
///
/// * a single tag, `"abc123"`;
/// * a comma-separated list, `"a", "b"` — matched if any entry matches;
/// * `*`, which matches any current representation;
/// * a weak tag, `W/"abc123"`, which matches a strong tag with the same opaque part.
///
/// A missing or empty header never matches, because "the client sent nothing" is not "the client
/// has the current version".
#[must_use]
pub fn matches_if_none_match(header: Option<&str>, etag: &str) -> bool {
    let Some(header) = header else {
        return false;
    };
    let header = header.trim();
    if header.is_empty() {
        return false;
    }
    if header == "*" {
        return true;
    }
    let wanted = strip_weak(etag);
    header
        .split(',')
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .any(|entry| strip_weak(entry) == wanted)
}

/// Strip a `W/` weak marker and surrounding whitespace from a tag.
fn strip_weak(tag: &str) -> &str {
    let tag = tag.trim();
    tag.strip_prefix("W/").unwrap_or(tag).trim()
}

/// The `Cache-Control` value for a route, given its freshness in seconds.
///
/// The TTL is a **product decision, not a tuning knob**: it is how long a runtime change takes to
/// become visible to a client that is already running. The channel document's TTL is therefore the
/// region-open latency floor, and the plan says so rather than leaving it implicit.
#[must_use]
pub fn cache_control(max_age_seconds: u32) -> String {
    format!("max-age={max_age_seconds}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_etag_is_quoted_hex_of_fixed_length() {
        let tag = etag_for(b"{}");
        assert!(tag.starts_with('"') && tag.ends_with('"'), "{tag}");
        assert_eq!(tag.len(), 18, "quote + 16 hex + quote");
        assert!(tag[1..17].chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn the_etag_is_stable_for_the_same_bytes() {
        assert_eq!(etag_for(b"hello"), etag_for(b"hello"));
    }

    #[test]
    fn the_etag_changes_when_the_bytes_change() {
        assert_ne!(etag_for(b"hello"), etag_for(b"hellp"));
        // Even a single trailing byte matters: the document ends with a newline and a renderer
        // that dropped it would otherwise look identical.
        assert_ne!(etag_for(b"hello"), etag_for(b"hello\n"));
    }

    #[test]
    fn an_empty_body_has_a_tag() {
        // Not the empty string: the client must still receive a tag.
        let tag = etag_for(b"");
        assert!(tag.starts_with('"'));
        assert_ne!(tag, "\"\"");
    }

    #[test]
    fn a_missing_header_never_matches() {
        assert!(!matches_if_none_match(None, "\"abc\""));
        assert!(!matches_if_none_match(Some(""), "\"abc\""));
        assert!(!matches_if_none_match(Some("   "), "\"abc\""));
    }

    #[test]
    fn a_single_matching_tag_matches() {
        assert!(matches_if_none_match(Some("\"abc\""), "\"abc\""));
    }

    #[test]
    fn a_different_tag_does_not_match() {
        assert!(!matches_if_none_match(Some("\"abc\""), "\"abd\""));
    }

    #[test]
    fn a_list_matches_on_any_entry() {
        assert!(matches_if_none_match(Some("\"x\", \"abc\", \"y\""), "\"abc\""));
        assert!(!matches_if_none_match(Some("\"x\", \"y\""), "\"abc\""));
    }

    #[test]
    fn a_wildcard_matches_anything() {
        assert!(matches_if_none_match(Some("*"), "\"abc\""));
    }

    #[test]
    fn a_weak_tag_matches_the_same_strong_tag() {
        // RFC 9110: If-None-Match uses weak comparison.
        assert!(matches_if_none_match(Some("W/\"abc\""), "\"abc\""));
        assert!(matches_if_none_match(Some("\"abc\""), "W/\"abc\""));
    }

    #[test]
    fn surrounding_whitespace_is_tolerated() {
        assert!(matches_if_none_match(Some("  \"abc\"  "), "\"abc\""));
    }

    #[test]
    fn cache_control_is_the_measured_form() {
        // The prototype serves the channel document at 30 and CMS at 60.
        assert_eq!(cache_control(30), "max-age=30");
        assert_eq!(cache_control(60), "max-age=60");
        assert_eq!(cache_control(0), "max-age=0");
    }
}
