//! The `aws-sdk-cpp` response envelope: content type and correlation headers.
//!
//! WHY THIS IS A TYPE AND NOT A HELPER
//! ===================================
//! `aws-sdk-cpp` correlates a response with its request by id, and the landing-screen GETs went out
//! without one until these headers were added (`app.py::_send_body`). The failure is not a clean
//! error: the client keeps waiting or discards the body, and nothing in the gateway's log says why.
//! Making it a type means a route either produces an envelope or does not, and there is no middle
//! state where someone forgot.
//!
//! THE TWO CONTENT TYPES ARE NOT INTERCHANGEABLE
//! =============================================
//! * `application/json` for the routes the prototype serves with `_send_json` — channel document,
//!   CMS, health.
//! * `application/x-amz-json-1.1` for the `JavelinGatewayService` routes. The `aws-sdk-cpp`
//!   deserializer **only** accepts this one on `getlogininfo` and `worlds/list` (measured: the
//!   request carries it and the response must match).
//! * `application/x-amz-json-1.0` for the DynamoDB-shaped POST target.
//!
//! A route that picks the wrong one returns a body the client will not parse, and the symptom is
//! indistinguishable from an empty result.

/// `application/json`.
pub const CONTENT_TYPE_JSON: &str = "application/json";
/// `application/x-amz-json-1.1`, required by the `aws-sdk-cpp` gateway routes.
pub const CONTENT_TYPE_AMZ_JSON_1_1: &str = "application/x-amz-json-1.1";
/// `application/x-amz-json-1.0`, used by the DynamoDB-shaped POST target.
pub const CONTENT_TYPE_AMZ_JSON_1_0: &str = "application/x-amz-json-1.0";

/// A correlation id, as a hex string.
///
/// Opaque to us: the client echoes it and the SDK matches on it. The only requirement is that it is
/// present and stable for the response.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CorrelationId(pub String);

impl CorrelationId {
    /// Use the request's id when it supplied one, otherwise mint a deterministic fallback.
    ///
    /// The fallback is derived from the request path and a counter rather than randomness, so a
    /// test can assert the header is present without depending on a random value.
    #[must_use]
    pub fn for_request(request_id: Option<&str>, fallback_seed: u64) -> Self {
        match request_id.filter(|value| !value.trim().is_empty()) {
            Some(value) => Self(value.to_string()),
            None => Self(format!("azoth-{fallback_seed:08x}")),
        }
    }

    /// The id as a string slice.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// The `aws-sdk-cpp` response envelope: a content type plus the correlation headers.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AwsEnvelope {
    /// The `Content-Type` the route must declare.
    pub content_type: &'static str,
    /// The request id the SDK correlates on.
    pub request_id: CorrelationId,
    /// A CloudFront-shaped distribution id, present because the official responses carry one.
    pub apigw_id: String,
    /// A CloudFront request id.
    pub cf_id: String,
    /// A CloudFront point of presence.
    pub cf_pop: &'static str,
}

impl AwsEnvelope {
    /// The point of presence the prototype reports, kept because the official responses carried one
    /// and there is no measurement saying the client ignores it.
    pub const CF_POP: &'static str = "FRA56-P3";

    /// Build an envelope for a request.
    #[must_use]
    pub fn new(
        content_type: &'static str,
        request_id: Option<&str>,
        fallback_seed: u64,
        counter: u64,
    ) -> Self {
        Self {
            content_type,
            request_id: CorrelationId::for_request(request_id, fallback_seed),
            apigw_id: format!("azoth-apigw/{counter:08x}"),
            cf_id: format!("{counter:016x}"),
            cf_pop: Self::CF_POP,
        }
    }

    /// The headers to emit, as name/value pairs in the order the prototype writes them.
    #[must_use]
    pub fn headers(&self) -> Vec<(&'static str, String)> {
        vec![
            ("x-amzn-RequestId", self.request_id.0.clone()),
            ("x-amz-apigw-id", self.apigw_id.clone()),
            ("x-amz-cf-id", self.cf_id.clone()),
            ("x-amz-cf-pop", self.cf_pop.to_string()),
            ("x-cache", "Miss from cloudfront".to_string()),
            (
                "via",
                format!("1.1 {}.cloudfront.net (CloudFront)", self.cf_id),
            ),
            ("age", "0".to_string()),
        ]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_three_content_types_are_the_measured_strings() {
        assert_eq!(CONTENT_TYPE_JSON, "application/json");
        assert_eq!(CONTENT_TYPE_AMZ_JSON_1_1, "application/x-amz-json-1.1");
        assert_eq!(CONTENT_TYPE_AMZ_JSON_1_0, "application/x-amz-json-1.0");
    }

    #[test]
    fn the_request_id_is_echoed_when_supplied() {
        let id = CorrelationId::for_request(Some("abc-123"), 7);
        assert_eq!(id.as_str(), "abc-123");
    }

    #[test]
    fn a_blank_request_id_is_replaced() {
        // An empty id would be as good as no id: the SDK has nothing to match on.
        let id = CorrelationId::for_request(Some("   "), 0x2a);
        assert_eq!(id.as_str(), "azoth-0000002a");
    }

    #[test]
    fn a_missing_request_id_gets_a_deterministic_fallback() {
        let a = CorrelationId::for_request(None, 1);
        let b = CorrelationId::for_request(None, 1);
        assert_eq!(a, b, "a test must be able to assert this without randomness");
        assert_ne!(a, CorrelationId::for_request(None, 2));
    }

    #[test]
    fn the_envelope_carries_every_header_the_sdk_correlates_on() {
        let envelope = AwsEnvelope::new(CONTENT_TYPE_AMZ_JSON_1_1, None, 1, 0xAB);
        let headers = envelope.headers();
        let names: Vec<&str> = headers.iter().map(|(name, _)| *name).collect();
        for required in [
            "x-amzn-RequestId",
            "x-amz-apigw-id",
            "x-amz-cf-id",
            "x-amz-cf-pop",
            "x-cache",
            "via",
            "age",
        ] {
            assert!(names.contains(&required), "missing {required}");
        }
    }

    #[test]
    fn the_headers_have_the_measured_shapes() {
        let envelope = AwsEnvelope::new(CONTENT_TYPE_JSON, Some("req-1"), 0, 0xAB);
        let headers = envelope.headers();
        let get = |name: &str| {
            headers
                .iter()
                .find(|(n, _)| *n == name)
                .map(|(_, v)| v.clone())
                .expect(name)
        };
        assert_eq!(get("x-amzn-RequestId"), "req-1");
        assert!(get("x-amz-apigw-id").starts_with("azoth-apigw/"));
        assert!(get("via").ends_with(".cloudfront.net (CloudFront)"));
        assert_eq!(get("x-amz-cf-pop"), AwsEnvelope::CF_POP);
        assert_eq!(get("age"), "0");
    }

    #[test]
    fn the_envelope_is_not_shared_between_requests() {
        // Two requests must not collide on a correlation id, or the SDK may match the wrong one.
        let a = AwsEnvelope::new(CONTENT_TYPE_JSON, None, 1, 1);
        let b = AwsEnvelope::new(CONTENT_TYPE_JSON, None, 2, 2);
        assert_ne!(a.request_id, b.request_id);
        assert_ne!(a.apigw_id, b.apigw_id);
        assert_ne!(a.cf_id, b.cf_id);
    }
}
