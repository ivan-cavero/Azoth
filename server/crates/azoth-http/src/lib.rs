//! The HTTP semantics the New World client requires.
//!
//! WHY THIS CRATE EXISTS
//! =====================
//! The client's HTTP stack is `aws-sdk-cpp` over WinHTTP, and it is strict in ways that cost this
//! project real sessions to discover. Those rules are not "how HTTP works"; they are **how this
//! client behaves**, and every one of them is measured. Putting them in one crate means a route
//! cannot accidentally re-invent them, and each rule has a test.
//!
//! THE FOUR MEASURED RULES
//! =======================
//! 1. **HTTP/1.1 is mandatory, with `Content-Length`.** `aws-sdk-cpp` discards the body of a `200`
//!    served as HTTP/1.0 (`services/gateway/src/azoth_gateway/app.py`). A response with the right
//!    bytes and the wrong protocol version is a response the client ignores.
//! 2. **`TCP_NODELAY` is mandatory.** Without it, the headers-write plus body-write hit Windows
//!    delayed-ACK/Nagle and the region ping the client displays measured 40–70 ms on loopback; with
//!    it, ~2 ms. That is a number in the client's UI, so it is part of the contract.
//! 3. **An ETag is mandatory.** A CMS response without one crashes the client
//!    (`routes/cms.py`, `docs/CLIENT_CONTRACT.md`).
//! 4. **The `x-amzn-*` envelope is mandatory on the `aws-sdk-cpp` routes.** The SDK correlates a
//!    response by request id, and the landing-screen GETs went out without one until it was added.
//!
//! WHAT IS NOT HERE
//! ================
//! The server itself. This crate is the *rules* — pure functions over bytes and headers — so they
//! can be tested without a socket and reused by any transport. The async HTTP stack is a separate
//! decision and a separate dependency.

pub mod cache;
pub mod envelope;
pub mod pyjson;
pub mod route;

pub use cache::{cache_control, etag_for, matches_if_none_match};
pub use envelope::{AwsEnvelope, CONTENT_TYPE_JSON, CONTENT_TYPE_AMZ_JSON_1_0, CONTENT_TYPE_AMZ_JSON_1_1};
pub use pyjson::to_python_bytes;
pub use route::{Response, RouteKind};

/// The only HTTP version the client accepts a body under.
///
/// `aws-sdk-cpp` on WinHTTP discards the body of a `200` served as HTTP/1.0, which presents as a
/// request that succeeded and returned nothing.
pub const REQUIRED_HTTP_VERSION: &str = "HTTP/1.1";

#[cfg(test)]
mod tests {
    #[test]
    fn the_required_version_is_one_point_one() {
        assert_eq!(super::REQUIRED_HTTP_VERSION, "HTTP/1.1");
    }
}
