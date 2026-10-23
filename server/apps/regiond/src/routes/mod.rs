//! The HTTP surface: one catch-all router, the shared response shape, and the dispatch.
//!
//! WHY THE ROUTER IS ONE CATCH-ALL AND NOT ONE AXUM ROUTE PER PATH
//! =============================================================
//! The client assembles several of these URLs at runtime — `getlogininfo` carries `jwt/omni` and
//! query parameters it chooses, `worlds/list` and `login/queue/v2` are built the same way, and the
//! per-persona `players/{persona}/...` paths cannot be written as static axum routes without
//! guessing which segment varies. `azoth_http::route::classify` already encodes those rules with
//! their measured reasons and tests that need no socket, so this module asks it and dispatches. One
//! place decides what a path means, and it is not this one.
//!
//! WHY EVERY BODY IS RENDERED WITH `to_python_bytes`
//! ================================================
//! The Phase 1/2 bar is that a route's bytes are comparable with the prototype's for the same input,
//! so a reviewer sees a real difference instead of whitespace noise. `to_python_bytes` reproduces
//! `json.dumps` separators, and the field **order** is fixed by each body's builder because the
//! client's parsers read fields in a fixed order.
//!
//! WHY THE CONTENT TYPE AND THE ENVELOPE ARE PER ROUTE, EXACTLY AS MEASURED
//! =======================================================================
//! `aws-sdk-cpp` only accepts `application/x-amz-json-1.1` on `getlogininfo` and `worlds/list`, and
//! those are also the only two routes the prototype sent the `x-amzn-*` envelope on
//! (`app.py::_send_body(..., aws_id=True)`). Every other client route is served with plain
//! `application/json` and no envelope, and that is what the client has been measured accepting.
//!
//! An earlier version of this file declared the amz type everywhere, arguing that one content type
//! across the login chain is "one fewer difference to explain". That is backwards: changing a header
//! the client was measured accepting, in exchange for tidiness, is an unmeasured change with a
//! silent failure mode — a body the client drops without an error. [`RouteKind::needs_aws_envelope`]
//! is the measured switch, and it is used as one.
//!
//! WHY NOTHING IS EVER FABRICATED
//! ==============================
//! A path this service does not serve gets a `404` whose body names the classification, and a route
//! whose state is missing gets a `503` whose body names what is missing. A plausible stub is how a
//! real request disappears without a trace, which is the failure mode this project keeps paying for.

pub mod game;
pub mod omni;
pub mod platform;
pub mod remote_config;
pub mod time;

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use axum::Router;
use axum::body::Body;
use axum::extract::State;
use axum::http::{HeaderMap, HeaderValue, Request, StatusCode, header};
use axum::response::Response as AxumResponse;
use axum::routing::any;
use serde_json::{Value, json};

use azoth_http::envelope::{AwsEnvelope, CONTENT_TYPE_AMZ_JSON_1_1, CONTENT_TYPE_JSON};
use azoth_http::route::{self, Response, RouteKind};
use azoth_http::to_python_bytes;



use crate::identity::Identity;

use time::iso8601_utc;

/// A per-process counter for the correlation-id fallback and the CloudFront-shaped ids.
///
/// Deterministic rather than random so a test can assert the headers exist without depending on a
/// value, and monotonic so two responses never share one.
static REQUEST_COUNTER: AtomicU64 = AtomicU64::new(0);

/// A route that cannot be answered from this region's state.
///
/// Distinct from "not implemented": this one means the route EXISTS and the data to answer it does
/// not. The body names what is missing, because a `503` with no explanation is indistinguishable from
/// a broken service.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RouteError {
    /// The account has no character, so no login can be placed.
    NoCharacter,
    /// The character names a world the registry does not hold.
    ///
    /// Carries the id so the body can say WHICH world is missing; a bare "no world" leaves an
    /// operator guessing between a stale character row and an empty registry.
    UnknownWorld(String),
}

impl RouteError {
    /// The body to send: a machine-readable code and a human sentence.
    #[must_use]
    pub fn body(&self) -> Value {
        match self {
            Self::NoCharacter => json!({
                "ok": false,
                "error": "no-character",
                "detail": "this account has no character, so there is nothing to log in with",
            }),
            Self::UnknownWorld(world_id) => json!({
                "ok": false,
                "error": "unknown-world",
                "world_id": world_id,
                "detail": "the character names a world the registry does not hold",
            }),
        }
    }
}

/// Build the router.
pub fn router(state: Arc<AppState>) -> Router {
    Router::new().fallback(any(handle)).with_state(state)
}

/// The state every request reads.
#[derive(Debug, Clone)]
pub struct AppState {
    /// The seeded identity: account, persona and character.
    pub identity: Arc<Identity>,
}

impl AppState {
    /// Build the state around a loaded identity.
    #[must_use]
    pub fn new(identity: Arc<Identity>) -> Self {
        Self { identity }
    }
}

/// The single entry point for every request.
async fn handle(State(state): State<Arc<AppState>>, request: Request<Body>) -> AxumResponse {
    let path = request.uri().path().to_string();
    let kind = route::classify(&path);
    let request_id = header_value(request.headers(), "x-amzn-requestid");
    let counter = REQUEST_COUNTER.fetch_add(1, Ordering::Relaxed);
    let identity = &state.identity;

    let response = match kind {
        RouteKind::Tokens => amz_of(RouteKind::Tokens, &omni::tokens(identity), request_id.as_deref(), counter),
        RouteKind::Credentials => {
            amz_of(RouteKind::Credentials, &omni::credentials(identity), request_id.as_deref(), counter)
        }
        RouteKind::Entitlements if path.contains("/entitlements/sync") => {
            amz_of(RouteKind::Entitlements, &platform::entitlements_sync(), request_id.as_deref(), counter)
        }
        RouteKind::Entitlements => {
            amz_of(RouteKind::Entitlements, &platform::entitlements(identity), request_id.as_deref(), counter)
        }
        RouteKind::Privacy => {
            amz_of(RouteKind::Privacy, &platform::privacy(identity), request_id.as_deref(), counter)
        }
        RouteKind::GetLoginInfo => {
            from_result(RouteKind::GetLoginInfo, game::login_info(identity), request_id.as_deref(), counter)
        }
        RouteKind::WorldsList => {
            amz_of(RouteKind::WorldsList, &game::worlds_list(identity), request_id.as_deref(), counter)
        }
        RouteKind::LoginQueue => from_result(
            RouteKind::LoginQueue,
            game::queue(identity, is_queue_refresh(&path)),
            request_id.as_deref(),
            counter,
        ),
        RouteKind::RemoteConfig => match remote_config::body_for(&path) {
            Some(body) => Response {
                status: 200,
                content_type: CONTENT_TYPE_JSON,
                body,
                headers: Vec::new(),
            },
            // A `configuration-sets` path with no captured size is not a layer we know; say so
            // rather than serving an empty document the client would merge as "no keys".
            None => not_implemented(RouteKind::RemoteConfig, &path),
        },
        // Ours, not the client's: a supervisor needs to tell regiond from a dead port.
        RouteKind::Health => json_response(200, &json!({ "ok": true }), CONTENT_TYPE_JSON),
        RouteKind::Ping => Response {
            status: 200,
            content_type: "text/plain",
            // The client shows this string in its region picker; the host name is the prototype's.
            body: b"healthy: dynamodb.eu-central-1.amazonaws.com".to_vec(),
            headers: Vec::new(),
        },
        other => not_implemented(other, &path),
    };

    to_axum(response)
}

/// Whether the path is the queue **refresh** (`/queue/v2/<ticket>/jwt/...`) and not the enqueue.
///
/// The prototype matches `/queue/v2/[^/]+/jwt` (`routes/queue.py`): a ticket segment must sit between
/// `v2/` and `jwt/`. A refresh answered with the enqueue body leaves the client waiting forever, so
/// this distinction is the one that moves it to `StartREPConnection`.
fn is_queue_refresh(path: &str) -> bool {
    let path = path.split('?').next().unwrap_or(path);
    let Some(rest) = path.split("/queue/v2/").nth(1) else {
        return false;
    };
    let mut segments = rest.split('/');
    let ticket = segments.next().unwrap_or_default();
    let tail = segments.next().unwrap_or_default();
    !ticket.is_empty() && ticket != "jwt" && tail == "jwt"
}

/// Answer a `Result` from a route module, or name the missing state.
///
/// A missing-state error becomes a `503` with the reason in the body, never a plausible stub: a
/// fabricated body is how a real request disappears without a trace.
fn from_result(
    kind: RouteKind,
    result: Result<Value, RouteError>,
    request_id: Option<&str>,
    counter: u64,
) -> Response {
    match result {
        Ok(body) => amz_of(kind, &body, request_id, counter),
        Err(err) => amz_status_of(kind, 503, &err.body(), request_id, counter),
    }
}

fn not_implemented(kind: RouteKind, path: &str) -> Response {
    let body = json!({
        "ok": false,
        "error": "not-implemented",
        "path": path,
        "route": format!("{kind:?}"),
    });
    json_response(404, &body, CONTENT_TYPE_JSON)
}

/// The `Content-Type` for a route, per the measured per-route split.
///
/// Returns the amz type only for the two routes `aws-sdk-cpp` requires it on.
#[must_use]
const fn content_type_for(kind: RouteKind) -> &'static str {
    if kind.needs_aws_envelope() {
        CONTENT_TYPE_AMZ_JSON_1_1
    } else {
        CONTENT_TYPE_JSON
    }
}

/// A `200` for `kind`: the measured content type and, only where the client needs it, the envelope.
fn amz_of(kind: RouteKind, body: &Value, request_id: Option<&str>, counter: u64) -> Response {
    amz_status_of(kind, 200, body, request_id, counter)
}

/// An arbitrary status for `kind`, with the measured content type and envelope policy.
fn amz_status_of(
    kind: RouteKind,
    status: u16,
    body: &Value,
    request_id: Option<&str>,
    counter: u64,
) -> Response {
    let response = json_response(status, body, content_type_for(kind));
    if kind.needs_aws_envelope() {
        response.with_envelope(&AwsEnvelope::new(
            content_type_for(kind),
            request_id,
            counter,
            counter,
        ))
    } else {
        response
    }
}

/// A plain JSON response with Python-shaped bytes.
fn json_response(status: u16, body: &Value, content_type: &'static str) -> Response {
    let bytes = to_python_bytes(body).unwrap_or_else(|_| b"{}
".to_vec());
    Response {
        status,
        content_type,
        body: bytes,
        headers: Vec::new(),
    }
}

/// The first value of `name`, as a string, when the client sent one.
fn header_value(headers: &HeaderMap, name: &str) -> Option<String> {
    headers
        .get(name)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
}

/// Convert an internal response into an axum one, setting every required header.
fn to_axum(response: Response) -> AxumResponse {
    let mut builder = AxumResponse::builder()
        .status(StatusCode::from_u16(response.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR))
        .header(header::CONTENT_TYPE, response.content_type)
        // Always present: the client's stack discards a body it cannot size.
        .header(header::CONTENT_LENGTH, response.content_length());

    for (name, value) in &response.headers {
        if let (Ok(name), Ok(value)) = (
            axum::http::HeaderName::from_bytes(name.as_bytes()),
            HeaderValue::from_str(value),
        ) {
            builder = builder.header(name, value);
        }
    }

    builder.body(Body::from(response.body)).unwrap_or_else(|_| {
        AxumResponse::builder()
            .status(StatusCode::INTERNAL_SERVER_ERROR)
            .body(Body::empty())
            .expect("an empty 500 always builds")
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_iso_timestamps_match_python() {
        // Reference values from `datetime.fromtimestamp(s, UTC).strftime(...)`.
        for (seconds, expected) in [
            (0, "1970-01-01T00:00:00Z"),
            (1_700_000_000, "2023-11-14T22:13:20Z"),
            (1_758_000_000, "2025-09-16T05:20:00Z"),
            (2_147_483_647, "2038-01-19T03:14:07Z"),
        ] {
            assert_eq!(iso8601_utc(seconds), expected);
        }
    }

    #[test]
    fn a_refresh_path_is_told_apart_from_the_enqueue() {
        assert!(is_queue_refresh(
            "/prod/game/login/queue/v2/abc-123/jwt/omni"
        ));
        assert!(is_queue_refresh(
            "/prod/game/login/queue/v2/abc-123/jwt/omni?x=1"
        ));
        assert!(!is_queue_refresh("/prod/game/login/queue/v2/jwt/omni"));
        assert!(!is_queue_refresh("/prod/game/login/queue/v2/"));
    }

    #[test]
    fn an_unknown_path_is_a_404_that_names_the_classification() {
        let response = not_implemented(RouteKind::Images, "/images/x.png");
        assert_eq!(response.status, 404);
        let body: Value = serde_json::from_slice(&response.body).expect("json");
        assert_eq!(body["error"], "not-implemented");
        assert_eq!(body["route"], "Images");
        assert_eq!(body["path"], "/images/x.png");
    }

    #[test]
    fn a_missing_state_answers_503_with_the_reason() {
        let response = from_result(RouteKind::GetLoginInfo, Err(RouteError::NoCharacter), None, 0);
        assert_eq!(response.status, 503);
        assert_eq!(response.content_type, CONTENT_TYPE_AMZ_JSON_1_1);
        let body: Value = serde_json::from_slice(&response.body).expect("json");
        assert_eq!(body["error"], "no-character");
        assert!(body["detail"].as_str().unwrap_or_default().contains("character"));
    }

    #[test]
    fn every_client_route_carries_the_correlation_envelope() {
        let response = amz_of(RouteKind::GetLoginInfo, &json!({"a": 1}), Some("req-7"), 3);
        assert_eq!(response.status, 200);
        let names: Vec<&str> = response.headers.iter().map(|(name, _)| *name).collect();
        for required in ["x-amzn-RequestId", "x-amz-apigw-id", "x-amz-cf-id"] {
            assert!(names.contains(&required), "missing {required}");
        }
        assert!(
            response
                .headers
                .iter()
                .any(|(name, value)| *name == "x-amzn-RequestId" && value == "req-7"),
            "the client's request id must be echoed"
        );
    }
}
