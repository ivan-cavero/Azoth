//! Route classification and the response shape.
//!
//! WHY THE MATCHERS ARE NOT OBVIOUS
//! ================================
//! The client builds some URLs from strings it assembles at runtime, so several routes cannot be
//! matched by an exact path. Each rule below is measured, and each one has a reason recorded next
//! to it — a "cleaner" matcher here breaks the client in a way that looks like a server outage.
//!
//! * **The channel document matches by basename prefix.** The client builds garbage channel URLs
//!   (`STEAM_APP_ID.1.BRANCH.<rand>.json`), so the match is `basename.starts_with("STEAM_APP_ID")`
//!   and it must come after the CMS checks, because `/newsstories/STEAM_APP_ID/...` also contains
//!   the token.
//! * **`getlogininfo` matches by substring**, because the client appends `jwt/omni` and query
//!   parameters it chooses.
//! * **The AWS routes must be matched before the catch-all**, or a real request becomes a discovery
//!   entry and the client gets a 404 with a helpful JSON body it cannot parse.
//!
//! WHAT A RESPONSE IS
//! ==================
//! Bytes, a status, a content type and headers. Deliberately not tied to any server library: the
//! rules are testable without a socket, and the transport is a separate decision.

use crate::envelope::AwsEnvelope;

/// A route the server knows how to answer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RouteKind {
    /// `GET /STEAM_APP_ID*.json` — the channel document.
    Channel,
    /// `/newsstories/<app>/metadata.json`.
    CmsNews,
    /// `/marketingtiles/<app>/metadata.json`.
    CmsTiles,
    /// `/motd/worlds_<app>.json`.
    CmsMotd,
    /// `/prod/game/getlogininfo/...`
    GetLoginInfo,
    /// `/prod/game/worlds/list/...`
    WorldsList,
    /// `/prod/game/login/queue/v2/...`
    LoginQueue,
    /// `/prod/credentials/omni`
    Credentials,
    /// `/games/new-world/tokens`
    Tokens,
    /// `/players/.../entitlements` and its `/sync`.
    Entitlements,
    /// `/privacy-settings` and its RPC names.
    Privacy,
    /// `/images/...` — content images.
    Images,
    /// `configuration-sets` — the remote-config layers.
    RemoteConfig,
    /// `/ping` — the region latency probe the client displays.
    Ping,
    /// `/healthz`, `/health` — ours, not the client's.
    Health,
    /// Anything else. Recorded, answered 404, never silently defaulted.
    Unknown,
}

impl RouteKind {
    /// Whether this route belongs to the `aws-sdk-cpp` gateway and therefore needs the correlation
    /// envelope. Getting this wrong returns a body the SDK will not parse.
    #[must_use]
    pub const fn needs_aws_envelope(self) -> bool {
        matches!(self, Self::GetLoginInfo | Self::WorldsList)
    }

    /// The `Cache-Control` freshness for this route, in seconds.
    ///
    /// The values are the prototype's, and they are a **product decision**: the TTL is how long a
    /// runtime change takes to reach a client that is already running. `None` means the route is
    /// not cacheable and gets no `Cache-Control`.
    #[must_use]
    pub const fn max_age_seconds(self) -> Option<u32> {
        match self {
            // The channel document's TTL is the region-open latency floor.
            Self::Channel => Some(30),
            // The client polls these; a shorter TTL costs bandwidth, a longer one delays content.
            Self::CmsNews | Self::CmsTiles | Self::CmsMotd => Some(60),
            _ => None,
        }
    }
}

/// Classify a request path.
///
/// The order of the checks is part of the contract, not a style choice: `Channel` must come after
/// the CMS checks because both contain `STEAM_APP_ID`, and the specific AWS routes must come before
/// anything that could swallow them.
#[must_use]
pub fn classify(path: &str) -> RouteKind {
    let path = path.split('?').next().unwrap_or(path);

    // CMS first: these also carry STEAM_APP_ID in their paths.
    if path.contains("newsstories") && path.ends_with("metadata.json") {
        return RouteKind::CmsNews;
    }
    if path.contains("marketingtiles") && path.ends_with("metadata.json") {
        return RouteKind::CmsTiles;
    }
    if path.contains("/motd/") && path.ends_with(".json") {
        return RouteKind::CmsMotd;
    }
    // Then the channel document, by basename prefix.
    if path.ends_with(".json") {
        let base = path.rsplit('/').next().unwrap_or("");
        if base.starts_with("STEAM_APP_ID") {
            return RouteKind::Channel;
        }
    }
    if path.contains("/prod/game/getlogininfo") {
        return RouteKind::GetLoginInfo;
    }
    if path.contains("/game/worlds/list") {
        return RouteKind::WorldsList;
    }
    if path.contains("/prod/game/login/queue/v2") {
        return RouteKind::LoginQueue;
    }
    if path.trim_end_matches('/').ends_with("/prod/credentials/omni") {
        return RouteKind::Credentials;
    }
    if path.trim_end_matches('/').ends_with("/games/new-world/tokens") {
        return RouteKind::Tokens;
    }
    if path.contains("/entitlements") {
        return RouteKind::Entitlements;
    }
    if path.contains("/privacy-settings")
        || path.contains("/GetPrivacySettingsForPlayer")
        || path.contains("/CreateOrUpdatePrivacySettingsForPlayer")
    {
        return RouteKind::Privacy;
    }
    if path.contains("/images/") {
        return RouteKind::Images;
    }
    if path.contains("configuration-sets") {
        return RouteKind::RemoteConfig;
    }
    if path == "/ping" {
        return RouteKind::Ping;
    }
    if path == "/healthz" || path == "/health" {
        return RouteKind::Health;
    }
    RouteKind::Unknown
}

/// A response, ready to write.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Response {
    /// HTTP status code.
    pub status: u16,
    /// The declared content type.
    pub content_type: &'static str,
    /// The body. Empty for a 304.
    pub body: Vec<u8>,
    /// Extra headers, in emission order.
    pub headers: Vec<(&'static str, String)>,
}

impl Response {
    /// A `200` with a body and an ETag.
    #[must_use]
    pub fn ok(content_type: &'static str, body: Vec<u8>, etag: String) -> Self {
        Self {
            status: 200,
            content_type,
            body,
            headers: vec![("ETag", etag)],
        }
    }

    /// A `304 Not Modified`: no body, but the ETag must still be present so the client can keep it.
    #[must_use]
    pub fn not_modified(etag: String) -> Self {
        Self {
            status: 304,
            content_type: crate::envelope::CONTENT_TYPE_JSON,
            body: Vec::new(),
            headers: vec![("ETag", etag)],
        }
    }

    /// The `Content-Length` this response must declare.
    ///
    /// Always present, including on a `304` (where it is `0`): the client's stack discards a body
    /// it cannot size, and a missing length is a truncated response as far as it is concerned.
    #[must_use]
    pub fn content_length(&self) -> usize {
        self.body.len()
    }

    /// Attach a `Cache-Control` header.
    #[must_use]
    pub fn with_cache_control(mut self, max_age_seconds: u32) -> Self {
        self.headers
            .push(("Cache-Control", crate::cache::cache_control(max_age_seconds)));
        self
    }

    /// Attach the `aws-sdk-cpp` correlation envelope.
    #[must_use]
    pub fn with_envelope(mut self, envelope: &AwsEnvelope) -> Self {
        self.content_type = envelope.content_type;
        self.headers.extend(envelope.headers());
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_channel_document_matches_by_basename_prefix() {
        // The client builds the URL from a string it assembles, so the prefix is the contract.
        assert_eq!(classify("/STEAM_APP_ID.json"), RouteKind::Channel);
        assert_eq!(classify("/STEAM_APP_ID.1063730.json"), RouteKind::Channel);
        assert_eq!(
            classify("/STEAM_APP_ID.1.BRANCH.abc123.json"),
            RouteKind::Channel
        );
    }

    #[test]
    fn cms_paths_win_over_the_channel_matcher() {
        // Both contain STEAM_APP_ID; the CMS routes must be classified first or the client gets a
        // channel document where it asked for news.
        assert_eq!(
            classify("/newsstories/STEAM_APP_ID.1063730/metadata.json"),
            RouteKind::CmsNews
        );
        assert_eq!(
            classify("/marketingtiles/STEAM_APP_ID.1063730/metadata.json"),
            RouteKind::CmsTiles
        );
        assert_eq!(
            classify("/motd/worlds_STEAM_APP_ID.1063730.json"),
            RouteKind::CmsMotd
        );
    }

    #[test]
    fn getlogininfo_matches_by_substring() {
        assert_eq!(
            classify("/prod/game/getlogininfo/jwt/omni"),
            RouteKind::GetLoginInfo
        );
        assert_eq!(
            classify("/prod/game/getlogininfo/jwt/omni?channelId=STEAM_APP_ID.1063730"),
            RouteKind::GetLoginInfo
        );
    }

    #[test]
    fn the_aws_routes_need_the_envelope_and_the_others_do_not() {
        assert!(RouteKind::GetLoginInfo.needs_aws_envelope());
        assert!(RouteKind::WorldsList.needs_aws_envelope());
        assert!(!RouteKind::Channel.needs_aws_envelope());
        assert!(!RouteKind::CmsNews.needs_aws_envelope());
        assert!(!RouteKind::Ping.needs_aws_envelope());
    }

    #[test]
    fn the_cacheable_routes_carry_the_measured_ttls() {
        assert_eq!(RouteKind::Channel.max_age_seconds(), Some(30));
        assert_eq!(RouteKind::CmsNews.max_age_seconds(), Some(60));
        assert_eq!(RouteKind::CmsMotd.max_age_seconds(), Some(60));
        assert_eq!(RouteKind::GetLoginInfo.max_age_seconds(), None);
        assert_eq!(RouteKind::Ping.max_age_seconds(), None);
    }

    #[test]
    fn the_queue_and_credentials_routes_are_recognised() {
        assert_eq!(
            classify("/prod/game/login/queue/v2/jwt/omni"),
            RouteKind::LoginQueue
        );
        assert_eq!(
            classify("/prod/game/login/queue/v2/abc/jwt/omni"),
            RouteKind::LoginQueue
        );
        assert_eq!(classify("/prod/credentials/omni"), RouteKind::Credentials);
        assert_eq!(classify("/games/new-world/tokens"), RouteKind::Tokens);
    }

    #[test]
    fn the_remote_config_layers_are_recognised() {
        assert_eq!(
            classify("/applications/public/configuration-sets/ProductId/STEAM_APP_ID/versionless"),
            RouteKind::RemoteConfig
        );
    }

    #[test]
    fn an_unknown_path_is_unknown_not_a_default() {
        // Never silently defaulted: an unrecognised route is a research item, and answering it with
        // a plausible body is how a real request disappears without a trace.
        assert_eq!(classify("/nope"), RouteKind::Unknown);
        assert_eq!(classify("/cms/manifest"), RouteKind::Unknown);
    }

    #[test]
    fn the_ping_and_health_routes_are_exact() {
        assert_eq!(classify("/ping"), RouteKind::Ping);
        assert_eq!(classify("/healthz"), RouteKind::Health);
        assert_eq!(classify("/health"), RouteKind::Health);
        // Not a prefix match: a path that merely contains /ping is not the probe.
        assert_eq!(classify("/ping/extra"), RouteKind::Unknown);
    }

    #[test]
    fn a_200_declares_its_length() {
        let response = Response::ok(
            crate::envelope::CONTENT_TYPE_JSON,
            b"{\"a\":1}".to_vec(),
            "\"x\"".to_string(),
        );
        assert_eq!(response.status, 200);
        assert_eq!(response.content_length(), 7);
        assert!(response.headers.iter().any(|(n, _)| *n == "ETag"));
    }

    #[test]
    fn a_304_has_no_body_but_keeps_its_etag() {
        let response = Response::not_modified("\"abc\"".to_string());
        assert_eq!(response.status, 304);
        assert_eq!(response.content_length(), 0);
        assert!(
            response.headers.iter().any(|(n, v)| *n == "ETag" && v == "\"abc\""),
            "a 304 must still carry the ETag"
        );
    }

    #[test]
    fn the_envelope_overrides_the_content_type() {
        let envelope = AwsEnvelope::new(
            crate::envelope::CONTENT_TYPE_AMZ_JSON_1_1,
            Some("req"),
            0,
            1,
        );
        let response = Response::ok(
            crate::envelope::CONTENT_TYPE_JSON,
            b"{}".to_vec(),
            "\"x\"".to_string(),
        )
        .with_envelope(&envelope);
        assert_eq!(
            response.content_type,
            crate::envelope::CONTENT_TYPE_AMZ_JSON_1_1,
            "the SDK route must declare the amz type, not the generic one"
        );
    }
}
