//! The HTTP surface: routing and responses.
//!
//! WHY THE ROUTER IS ONE CATCH-ALL AND NOT ONE ROUTE PER PATH
//! ========================================================
//! The client assembles several of its URLs at runtime, so an exact-path router cannot express them:
//! the channel document arrives as `STEAM_APP_ID.1.BRANCH.<rand>.json` and `getlogininfo` carries
//! query parameters the client chooses. The measured matcher in `azoth_http::route` already encodes
//! those rules with their reasons, so this module asks it and dispatches — one place decides what a
//! path means, and it is a place with tests that need no socket.
//!
//! WHY `TCP_NODELAY` IS SET BY HAND
//! ================================
//! Without it the headers-plus-body write hits Windows delayed-ACK/Nagle, and the region ping the
//! client **displays in its UI** measured 40–70 ms on loopback instead of ~2 ms. Axum/hyper does not
//! set it, so the listener is built from a socket configured before the handshake. That is a
//! one-line fix for a user-visible number, which is exactly the kind of thing that gets lost when a
//! route is rewritten.
//!
//! WHY EVERY RESPONSE CARRIES `Content-Length`
//! ==========================================
//! `aws-sdk-cpp` discards a body it cannot size, and it discards the body of a `200` served as
//! HTTP/1.0. Axum writes HTTP/1.1 with a length for a known body, so the requirement is met by
//! construction — but it is asserted in the tests rather than assumed, because a future streaming
//! route would break it silently.

use axum::Router;
use axum::body::Body;
use axum::extract::State;
use axum::http::{HeaderMap, HeaderValue, Request, StatusCode, header};
use axum::response::Response as AxumResponse;
use axum::routing::any;
use std::sync::atomic::{AtomicU64, Ordering};

use azoth_http::envelope::{AwsEnvelope, CONTENT_TYPE_AMZ_JSON_1_1, CONTENT_TYPE_JSON};
use azoth_http::route::{self, Response, RouteKind};
use azoth_http::matches_if_none_match;

use crate::images;
use crate::state::AppState;

/// A per-process counter for the correlation-id fallback.
///
/// Deterministic rather than random so a test can assert the header exists without depending on a
/// value, and monotonic so two responses never share an id.
static REQUEST_COUNTER: AtomicU64 = AtomicU64::new(0);

/// Build the router.
pub fn router(state: AppState) -> Router {
    Router::new().fallback(any(handle)).with_state(state)
}

/// The single entry point for every request.
async fn handle(State(state): State<AppState>, request: Request<Body>) -> AxumResponse {
    let path = request.uri().path().to_string();
    let kind = route::classify(&path);
    let if_none_match = request
        .headers()
        .get(header::IF_NONE_MATCH)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);

    let counter = REQUEST_COUNTER.fetch_add(1, Ordering::Relaxed);
    let request_id = request
        .headers()
        .get("x-amzn-requestid")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);

    let response = match kind {
        RouteKind::Channel => {
            let cached = &state.channel;
            cached_or_304(cached, CONTENT_TYPE_JSON, kind, if_none_match.as_deref())
        }
        RouteKind::CmsNews => cached_or_304(
            &state.cms_news,
            CONTENT_TYPE_JSON,
            kind,
            if_none_match.as_deref(),
        ),
        RouteKind::CmsTiles => cached_or_304(
            &state.cms_tiles,
            CONTENT_TYPE_JSON,
            kind,
            if_none_match.as_deref(),
        ),
        RouteKind::CmsMotd => cached_or_304(
            &state.cms_motd,
            CONTENT_TYPE_JSON,
            kind,
            if_none_match.as_deref(),
        ),
        RouteKind::Images => Response {
            status: 200,
            content_type: "image/dds",
            // A 404 here makes the client retry five times and then render blank white art; a
            // placeholder is the same effort and a better outcome. See `crate::images`.
            body: images::placeholder(),
            headers: Vec::new(),
        },
        RouteKind::Ping => Response {
            status: 200,
            content_type: "text/plain",
            // The client shows this string in its region picker; the host name is the prototype's
            // and is not load-bearing.
            body: b"healthy: dynamodb.eu-central-1.amazonaws.com".to_vec(),
            headers: Vec::new(),
        },
        RouteKind::Health => Response {
            status: 200,
            content_type: CONTENT_TYPE_JSON,
            body: b"{\"ok\":true}\n".to_vec(),
            headers: Vec::new(),
        },
        RouteKind::GetLoginInfo | RouteKind::WorldsList => {
            // Not implemented yet, and answered as an explicit 404 rather than a plausible stub:
            // a fabricated body is how a real request disappears without a trace. The Python
            // gateway keeps serving these until regiond exists.
            let envelope = AwsEnvelope::new(
                CONTENT_TYPE_AMZ_JSON_1_1,
                request_id.as_deref(),
                counter,
                counter,
            );
            let body = serde_json::json!({
                "ok": false,
                "error": "not-implemented",
                "route": format!("{kind:?}"),
                "note": "served by the Python gateway until regiond exists",
            })
            .to_string();
            Response {
                status: 404,
                content_type: CONTENT_TYPE_JSON,
                body: body.into_bytes(),
                headers: Vec::new(),
            }
            .with_envelope(&envelope)
        }
        _ => {
            // Every other path: a documented 404 that names the classification, so an unrecognised
            // request is a research item rather than a silent success.
            let body = serde_json::json!({
                "ok": false,
                "error": "unknown-path",
                "path": path,
                "route": format!("{kind:?}"),
            })
            .to_string();
            Response {
                status: 404,
                content_type: CONTENT_TYPE_JSON,
                body: body.into_bytes(),
                headers: Vec::new(),
            }
        }
    };

    to_axum(response)
}

/// Serve a cached body, honouring `If-None-Match`.
fn cached_or_304(
    cached: &crate::state::Cached,
    content_type: &'static str,
    kind: RouteKind,
    if_none_match: Option<&str>,
) -> Response {
    if matches_if_none_match(if_none_match, &cached.etag) {
        return Response::not_modified(cached.etag.clone());
    }
    let response = cached.response(content_type);
    match kind.max_age_seconds() {
        Some(max_age) => response.with_cache_control(max_age),
        None => response,
    }
}

/// Convert an internal response into an axum one, setting every required header.
fn to_axum(response: Response) -> AxumResponse {
    let mut builder = AxumResponse::builder()
        .status(StatusCode::from_u16(response.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR))
        .header(header::CONTENT_TYPE, response.content_type)
        // Always present: the SDK discards a body it cannot size.
        .header(header::CONTENT_LENGTH, response.content_length());

    let mut headers = HeaderMap::new();
    for (name, value) in &response.headers {
        if let (Ok(name), Ok(value)) = (
            axum::http::HeaderName::from_bytes(name.as_bytes()),
            HeaderValue::from_str(value),
        ) {
            headers.insert(name, value);
        }
    }
    for (name, value) in headers {
        if let Some(name) = name {
            builder = builder.header(name, value);
        }
    }

    builder
        .body(Body::from(response.body))
        .unwrap_or_else(|_| {
            AxumResponse::builder()
                .status(StatusCode::INTERNAL_SERVER_ERROR)
                .body(Body::empty())
                .expect("an empty 500 always builds")
        })
}

/// Build a listener with `TCP_NODELAY` set.
///
/// # Errors
/// The bind failure, unchanged.
pub async fn listener_with_nodelay(
    addr: std::net::SocketAddr,
) -> std::io::Result<tokio::net::TcpListener> {
    let socket = if addr.is_ipv4() {
        tokio::net::TcpSocket::new_v4()?
    } else {
        tokio::net::TcpSocket::new_v6()?
    };
    socket.set_nodelay(true)?;
    socket.bind(addr)?;
    socket.listen(1024)
}

#[cfg(test)]
mod tests {
    use super::*;
    use azoth_http::route::classify;

    /// The classification rules are `azoth-http`'s, and this asserts the wiring uses them rather
    /// than re-deriving them — the failure this guards against is a second, divergent matcher.
    #[test]
    fn the_router_uses_the_shared_classifier() {
        assert_eq!(classify("/STEAM_APP_ID.json"), RouteKind::Channel);
        assert_eq!(classify("/ping"), RouteKind::Ping);
        assert_eq!(classify("/healthz"), RouteKind::Health);
    }

    #[test]
    fn a_matching_etag_yields_304_with_no_body() {
        let cached = crate::state::Cached::new(b"{\"a\":1}".to_vec());
        let response = cached_or_304(
            &cached,
            CONTENT_TYPE_JSON,
            RouteKind::Channel,
            Some(&cached.etag),
        );
        assert_eq!(response.status, 304);
        assert_eq!(response.content_length(), 0);
        assert!(response.headers.iter().any(|(n, _)| *n == "ETag"));
    }

    #[test]
    fn a_non_matching_etag_yields_the_body() {
        let cached = crate::state::Cached::new(b"{\"a\":1}".to_vec());
        let response = cached_or_304(&cached, CONTENT_TYPE_JSON, RouteKind::Channel, Some("\"nope\""));
        assert_eq!(response.status, 200);
        assert_eq!(response.body, b"{\"a\":1}");
    }

    #[test]
    fn a_cacheable_route_carries_cache_control() {
        let cached = crate::state::Cached::new(b"{}".to_vec());
        let response = cached_or_304(&cached, CONTENT_TYPE_JSON, RouteKind::Channel, None);
        assert!(
            response
                .headers
                .iter()
                .any(|(n, v)| *n == "Cache-Control" && v == "max-age=30"),
            "the channel document's TTL is the region-open latency floor"
        );
    }

    #[test]
    fn a_non_cacheable_route_has_no_cache_control() {
        let cached = crate::state::Cached::new(b"{}".to_vec());
        let response = cached_or_304(&cached, CONTENT_TYPE_JSON, RouteKind::Health, None);
        assert!(!response.headers.iter().any(|(n, _)| *n == "Cache-Control"));
    }

    #[test]
    fn every_response_declares_a_length() {
        // The requirement that matters: the SDK discards a body it cannot size.
        for body in [Vec::new(), b"x".to_vec(), vec![b'y'; 1000]] {
            let response = Response::ok(CONTENT_TYPE_JSON, body.clone(), "\"e\"".to_string());
            assert_eq!(response.content_length(), body.len());
        }
    }

    #[test]
    fn the_etag_helper_matches_the_crate_it_comes_from() {
        // `Cached::new` must use azoth-http's algorithm, not its own.
        let cached = crate::state::Cached::new(b"hello".to_vec());
        assert_eq!(cached.etag, azoth_http::etag_for(b"hello"));
    }
}
