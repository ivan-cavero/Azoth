//! The REP carrier layer: one decrypted datagram in, the datagrams to answer
//! with out.
//!
//! This is the world's half of the REP connection. The DTLS transport hands it
//! plaintext application datagrams; it decodes the Carrier envelope and records
//! with [`everfall_wire`], recognises the two messages that stall the client
//! before registration, and answers them:
//!
//! * a Carrier `SM_CONNECT_REQUEST` is answered with the acceptance flight
//!   (`SM_CLOCK_SYNC` + `SM_CONNECT_ACK` + `SM_CT_ACKS`), echoing the client's
//!   envelope sequence, every time the client asks and the retransmit cooldown
//!   allows it -- not only the first time; and
//! * the client's `RegistrationRequestV3Msg` (`wire 0x13`) is answered with the
//!   Atlas card `flow.world-entry.rung.registration` (`wire 0x3`), whose body the
//!   generated codec produces and which moves the client from
//!   `WaitingForREPConnection` to `WaitingForActorGameConnection`.
//!
//! Once the registration is answered the session also keeps the connection alive:
//! the reference's `maybe_keepalive` sends an `SM_CLOCK_SYNC` datagram every
//! second for the rest of the session, and without it the client's transport
//! times the server out after ten seconds of silence (`transportError 4`). That
//! keepalive takes the envelope slot immediately after the `0x3` answer, which is
//! why the post-registration ladder starts one sequence later.
//!
//! ## Why a second `SM_CONNECT_REQUEST` is answered
//!
//! `WaitingForActorGameConnection` is left when the client's Carrier connection
//! reaches state 2, and `GridMate` reaches state 2 on the `CONNECT_ACK` path
//! (`conn->m_state = CST_CONNECTED`, the sequence the reference's
//! `carrier_state_datagram` quotes from `Carrier.cpp`). Our session used to answer
//! that handshake exactly once, then go silent: every later request on the same
//! transport -- which is the only shape a second, late Carrier connection attempt
//! can take -- was dropped as "no carrier reply". The cooldown below is the
//! client's own retransmit cadence, so re-answering cannot flood it.
//!
//! It mirrors the reference's `handle_app_data` in
//! `services/world/src/azoth_world/rep.py`. Nothing here opens a socket: it takes
//! bytes and returns the bytes to send, so the DTLS loop owns the transport and
//! this owns the protocol.

use core::fmt;

use everfall_wire::generated::FlowWorldEntryRungRegistration;
use everfall_wire::{
    CarrierError, Compression, Datagram, Envelope, MF_DATA_CHANNEL, MF_RELIABLE, MessageRecord,
    Opaque, RECORD_TYPE_MARKER, SM_CLOCK_SYNC, SM_CT_ACKS, SYSTEM_CHANNEL, WireError,
    acceptance_flight, clock_sync, connect_request_welcome, ct_acks, decode_records,
    decompress_block, is_connect_request, typed_record,
};

use crate::ladder::{LadderError, PostV3Ladder};

/// The wire id of the client's `RegistrationRequestV3Msg`, which opens the ladder.
///
/// The Atlas card `flow.world-entry.rung.registration` lists it as the alias
/// `wire:0x13`, but gives the request body no layout of its own, so the id is the
/// only thing the server can recognise it by. The live client's request carries
/// the marker `00 01 13` in the first bytes of its record payload (measured on the
/// official corpus record `0x0_T0x13_W.bin` and on the live retry datagram in
/// `.azoth/logs/world.log.fix2`).
pub const REGISTRATION_REQUEST_WIRE_ID: u32 = 0x13;

/// The smallest record payload a registration request can be.
///
/// The reference's own coarse filter was `size > 64`, which alone was too broad;
/// this is only half of the rule, and it is paired with the type marker below.
const REGISTRATION_MIN_PAYLOAD: usize = 64;

/// How far into a record payload the type marker is looked for.
const REGISTRATION_MARKER_WINDOW: usize = 64;

/// The server version the registration response carries.
///
/// The card records that the client does NOT require an exact version match: the
/// captured client reported `1.400.6031.6004151` while the captured server
/// answered `1.365.6031.6006993`, and the client still advanced. This is the
/// reference's own default, kept so a private server identifies itself in the
/// client's own format.
pub const SERVER_VERSION: &str = "[RETAIL].Javelin.1.400.6031.6004151";

/// The 32-byte session token placeholder the registration response carries.
///
/// The reference echoes the client's `session_uuid` here when its (uncarded)
/// request parses, and falls back to this stub otherwise; the Atlas marks the
/// slot's captured value fully redacted, so the content is lost. Since the
/// request body has no card this server does not parse, the stub is used and the
/// choice is stated here rather than hidden.
pub const SESSION_TOKEN: [u8; 32] = *b"AZOTH-stub-session-token-32bytes";

/// The card's measured `unresolved_u64` field (f2): `0x0b888d68706c415b`.
const REGISTRATION_UNRESOLVED_U64: u64 = 0x0B88_8D68_706C_415B;

/// The flag byte of a reliable data-channel record: `MF_RELIABLE | MF_DATA_CHANNEL`.
const RELIABLE_DATA_CHANNEL: u8 = MF_RELIABLE | MF_DATA_CHANNEL;

/// How long a session waits before it answers another `SM_CONNECT_REQUEST`.
///
/// The client's Carrier resends its request until one of our datagrams is
/// acknowledged, and it gives up on a lost datagram after 1000 ms
/// (`DefaultTrafficControl`'s lost-packet timeout, quoted by the reference at
/// `PeerSession.on_app_data` and by [`acceptance_flight`]'s own note). One answer
/// per second is therefore one answer per request the client actually makes: it
/// re-answers a late handshake without ever flooding a client that repeats itself.
pub const CONNECT_REPLY_COOLDOWN_MS: u32 = 1000;

/// Whether a `SM_CONNECT_REQUEST` in this datagram may be answered now.
///
/// A bool would be the fourth one on [`RepRequest`], and the distinction is a
/// decision rather than a flag: the caller has already compared the cooldown.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectReply {
    /// Answer the request: this is the first one, or the cooldown has elapsed.
    Allowed,
    /// Stay silent: the client asked again inside its own retransmit cooldown.
    Cooldown,
}

impl ConnectReply {
    /// Whether the request may be answered.
    #[must_use]
    pub const fn is_allowed(self) -> bool {
        matches!(self, Self::Allowed)
    }
}

/// One inbound application datagram and the session facts its answer depends on.
#[derive(Debug, Clone, Copy)]
pub struct RepRequest<'a> {
    /// The decrypted application datagram.
    pub app: &'a [u8],
    /// The datagram's Carrier envelope sequence, echoed in the acceptance flight.
    pub client_env_seq: u16,
    /// Whether the acceptance flight has already gone out.
    pub handshake_done: bool,
    /// Whether a `SM_CONNECT_REQUEST` in this datagram may be answered now. The
    /// caller coalesces this with [`CONNECT_REPLY_COOLDOWN_MS`], so a client that
    /// keeps asking is answered once per retransmit rather than once per datagram.
    pub connect_reply: ConnectReply,
    /// Whether the registration response has already gone out.
    pub v3_done: bool,
    /// Whether an ACK may be sent now (coalesced by the caller's clock).
    pub ack_allowed: bool,
    /// The first envelope sequence of the continuous ACK range.
    pub ack_first: u16,
    /// The server clock in milliseconds, for the sync record.
    pub clock_ms: u32,
}

/// A reply datagram that could not be framed.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum RepError {
    /// A reply's Carrier framing refused a value.
    Carrier(CarrierError),
    /// A reply body's card codec refused a value.
    Codec(WireError),
    /// A planned post-registration datagram could not be assembled.
    Ladder(LadderError),
}

impl From<CarrierError> for RepError {
    fn from(source: CarrierError) -> Self {
        Self::Carrier(source)
    }
}

impl From<WireError> for RepError {
    fn from(source: WireError) -> Self {
        Self::Codec(source)
    }
}

impl From<LadderError> for RepError {
    fn from(source: LadderError) -> Self {
        Self::Ladder(source)
    }
}

impl fmt::Display for RepError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Carrier(source) => write!(f, "reply framing: {source}"),
            Self::Codec(source) => write!(f, "reply codec: {source}"),
            Self::Ladder(source) => write!(f, "post-registration ladder: {source}"),
        }
    }
}

impl std::error::Error for RepError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Carrier(source) => Some(source),
            Self::Codec(source) => Some(source),
            Self::Ladder(source) => Some(source),
        }
    }
}

/// Answer one application datagram, statelessly.
///
/// This is the reference's `handle_app_data`: the caller supplies the session
/// facts ([`RepRequest`]) and gets back zero or more reply datagrams. A datagram
/// that is not valid Carrier framing, or whose body does not decompress, yields
/// no replies, exactly as the reference's `ValueError` paths do.
///
/// # Errors
/// Returns a [`RepError`] only when one of the server's own replies cannot be
/// framed, which is a bug in this crate rather than bad client input.
pub fn handle_app_data(request: &RepRequest<'_>) -> Result<Vec<Vec<u8>>, RepError> {
    process(request).map(|outcome| outcome.replies)
}

/// The first envelope sequence of the continuous ACK range.
///
/// Sliding, not pinned: while the session is younger than `window` this is the
/// session's first sequence, and after that it advances so the range never
/// exceeds `window`. The subtraction is in 16-bit wrap space. Mirrors the
/// reference's `ack_window_first`.
#[must_use]
pub fn ack_window_first(ack_last: u16, datagrams_seen: u32, window: u16) -> u16 {
    let window = u32::from(window.max(1));
    let width = datagrams_seen.max(1).min(window) as u16;
    ack_last.wrapping_sub(width.saturating_sub(1))
}

/// The reply datagrams plus the session facts that changed.
struct Outcome {
    replies: Vec<Vec<u8>>,
    /// A `SM_CONNECT_REQUEST` was answered with the acceptance flight.
    had_connect_request: bool,
    /// A registration request was answered with the `0x3` response.
    answered_v3: bool,
}

impl Outcome {
    const fn empty() -> Self {
        Self {
            replies: Vec::new(),
            had_connect_request: false,
            answered_v3: false,
        }
    }
}

/// Decode one datagram, decide, and build the replies.
fn process(request: &RepRequest<'_>) -> Result<Outcome, RepError> {
    let Ok((envelope, body)) = Envelope::decode(request.app) else {
        return Ok(Outcome::empty());
    };
    let body = if envelope.is_compressed() {
        match decompress_block(body) {
            Ok(decoded) => decoded,
            Err(_) => return Ok(Outcome::empty()),
        }
    } else {
        body.to_vec()
    };
    let Ok(records) = decode_records(&body) else {
        return Ok(Outcome::empty());
    };

    let connect_requests: Vec<&MessageRecord> = records
        .iter()
        .filter(|record| is_connect_request(record))
        .collect();
    let registrations: Vec<&MessageRecord> = records
        .iter()
        .filter(|record| is_registration_request(record))
        .collect();

    let mut outcome = Outcome::empty();
    // A `SM_CONNECT_REQUEST` is answered every time the cooldown allows it, not
    // only the first time.
    //
    // GridMate puts a Carrier connection in state 2 on the CONNECT_ACK path
    // (`conn->m_state = CST_CONNECTED`, quoted by the reference's own
    // `carrier_state_datagram`), and the client's Carrier resends the request until
    // one of our datagrams is acknowledged. A session that answers only the first
    // request goes silent for every later handshake on the same transport, which is
    // what a second, late Carrier connection attempt looks like on the wire. The
    // cooldown in [`CONNECT_REPLY_COOLDOWN_MS`] is the client's own retransmit
    // cadence, so this re-answers a request the client made without ever answering
    // twice for one datagram burst.
    if let Some(first) = connect_requests.first()
        && request.connect_reply.is_allowed()
    {
        let welcome = connect_request_welcome(first).unwrap_or(everfall_wire::DEFAULT_WELCOME);
        outcome.replies.push(acceptance_flight(
            request.client_env_seq,
            request.clock_ms,
            welcome,
            request.ack_first,
            request.client_env_seq,
        )?);
        outcome.had_connect_request = true;
    }
    if !registrations.is_empty() && !request.v3_done {
        outcome.replies.push(registration_response(
            request.client_env_seq.wrapping_add(1),
        )?);
        outcome.answered_v3 = true;
    }
    let needs_ack = request.handshake_done
        && connect_requests.is_empty()
        && records.iter().any(needs_acknowledgement);
    if needs_ack && request.ack_allowed {
        outcome.replies.push(ct_acks(
            request.client_env_seq,
            request.ack_first,
            request.client_env_seq,
        )?);
    }
    Ok(outcome)
}

/// True when a record should be acknowledged at the transport level.
///
/// The reference ACKs data envelopes so a reliable registration retry stops, but
/// never ACKs the client's own `CT_ACKS`/`CLOCK_SYNC`, which would loop.
fn needs_acknowledgement(record: &MessageRecord) -> bool {
    record.channel() != SYSTEM_CHANNEL
        || !matches!(record.system_message_id(), Some(SM_CT_ACKS | SM_CLOCK_SYNC))
}

/// True when a record carries the (uncarded) V3 registration request.
///
/// The request body has no card, so it is recognised by the typed-envelope marker
/// for wire `0x13` in the head of the record payload, together with the coarse
/// size floor. Both captured request forms carry it: the official corpus record
/// at payload offset 20 and the live retry body at offset 24.
fn is_registration_request(record: &MessageRecord) -> bool {
    if record.channel() != 0 {
        return false;
    }
    let payload = record.payload();
    if payload.len() <= REGISTRATION_MIN_PAYLOAD {
        return false;
    }
    let marker = [
        RECORD_TYPE_MARKER[0],
        RECORD_TYPE_MARKER[1],
        REGISTRATION_REQUEST_WIRE_ID as u8,
    ];
    let window = &payload[..payload.len().min(REGISTRATION_MARKER_WINDOW)];
    window.windows(marker.len()).any(|window| window == marker)
}

/// Build the `wire 0x3` registration response datagram.
///
/// The body comes from the Atlas card's generated codec; the record is a reliable
/// channel-0 record whose payload is the typed envelope (`VLQ32 length`, the type
/// marker, the type, the body).
fn registration_response(envelope_seq: u16) -> Result<Vec<u8>, RepError> {
    let card = FlowWorldEntryRungRegistration {
        unresolved_u32: 0,
        unresolved_u64: REGISTRATION_UNRESOLVED_U64,
        unresolved_block: Opaque::new(
            "flow.world-entry.rung.registration.unresolved_block",
            SESSION_TOKEN.to_vec(),
        ),
        server_version: SERVER_VERSION.to_owned(),
        trailing_bool_0: false,
        trailing_bool_1: false,
        trailing_bool_2: false,
        trailing_bool_3: false,
    };
    let mut body = Vec::new();
    card.encode(&mut body)?;
    let payload = typed_record(FlowWorldEntryRungRegistration::WIRE_ID, &body)?;
    let record = MessageRecord::new(0, payload)
        .with_reliable()
        .with_flags_override(RELIABLE_DATA_CHANNEL);
    Ok(Datagram::new(
        Envelope::new(envelope_seq, Compression::Plaintext),
        vec![record],
    )
    .encode()?)
}

/// Per-connection REP state, so a caller can drive datagrams one at a time.
///
/// It holds the two facts the answers gate on (whether the flight and the
/// registration response have gone out), the sliding ACK window, and -- when a
/// caller arms one -- the post-registration [`PostV3Ladder`], which [`Self::tick`]
/// releases on the connection's own clock.
#[derive(Debug)]
pub struct RepSession {
    handshake_done: bool,
    v3_responded: bool,
    inbound_count: u32,
    ack_window: u16,
    ack_coalesce_ms: u32,
    next_ack_ms: u32,
    ladder: Option<PostV3Ladder>,
    armed_at_ms: Option<u32>,
    next_release_at_ms: Option<u32>,
    next_post_v3: usize,
    post_v3_envelope_seq: u16,
    post_v3_message_seq: u16,
    post_v3_reliable_seq: u16,
    keepalive_ms: u32,
    next_keepalive_at_ms: Option<u32>,
    next_connect_reply_ms: Option<u32>,
    connect_replies: u32,
}

impl RepSession {
    /// The reference's continuous-ACK window (`AZOTH_ACK_WINDOW`).
    pub const DEFAULT_ACK_WINDOW: u16 = 16_384;

    /// The reference's ACK coalescing interval (`AZOTH_ACK_COALESCE_S` = 0.05 s).
    pub const DEFAULT_ACK_COALESCE_MS: u32 = 50;

    /// The reference's `SM_CLOCK_SYNC` keepalive period after the V3 answer.
    ///
    /// `maybe_keepalive` sends one datagram and then stays quiet until a second
    /// has passed. The reference's own note on why it exists: "`CLOCK_SYNC` ~1/s
    /// after V3 so `ClientSDK` does not disconnect (4) at 10s of server silence".
    pub const DEFAULT_KEEPALIVE_MS: u32 = 1000;

    /// A session that has answered nothing yet.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            handshake_done: false,
            v3_responded: false,
            inbound_count: 0,
            ack_window: Self::DEFAULT_ACK_WINDOW,
            ack_coalesce_ms: Self::DEFAULT_ACK_COALESCE_MS,
            next_ack_ms: 0,
            ladder: None,
            armed_at_ms: None,
            next_release_at_ms: None,
            next_post_v3: 0,
            post_v3_envelope_seq: 0,
            post_v3_message_seq: 1,
            post_v3_reliable_seq: 1,
            keepalive_ms: Self::DEFAULT_KEEPALIVE_MS,
            next_keepalive_at_ms: None,
            next_connect_reply_ms: None,
            connect_replies: 0,
        }
    }

    /// Give the session the post-registration rungs to send after the V3 answer.
    pub fn set_ladder(&mut self, ladder: PostV3Ladder) {
        self.ladder = Some(ladder);
    }

    /// Whether the post-registration ladder has been armed by a V3 answer.
    #[must_use]
    pub const fn post_v3_armed(&self) -> bool {
        self.armed_at_ms.is_some()
    }

    /// Emit the one datagram that is now due, if any.
    ///
    /// The reference's `PeerSession.tick` runs `maybe_keepalive` before
    /// `maybe_pump_replay`, so the keepalive owns the tick it falls due on and
    /// the ladder waits for the next one. Neither emitter sweeps a deadline: the
    /// reference sends one replay message per `REPLAY_INTERVAL_S` and sleeps the
    /// chunk gap BETWEEN the chunks of one message (`maybe_pump_replay` /
    /// `_send_replay_message`). This session keeps the same shape: it releases at
    /// most one datagram per call and re-arms [`Self::next_release_at_ms`] from the
    /// clock of the release plus the plan's gap to the next record. A late or
    /// coarse tick therefore cannot dump the backlog, which is what a deadline
    /// sweep does.
    ///
    /// The keepalive is armed by the registration answer alone, so a session with
    /// no ladder still keeps the client's transport alive; a ladder that has
    /// drained does not stop it either.
    ///
    /// # Errors
    /// Returns a [`RepError`] only when one of the server's own planned
    /// datagrams cannot be framed.
    pub fn tick(&mut self, clock_ms: u32) -> Result<Vec<Vec<u8>>, RepError> {
        if let Some(due) = self.next_keepalive_at_ms
            && clock_ms.wrapping_sub(due).cast_signed() >= 0
        {
            self.next_keepalive_at_ms = Some(clock_ms.wrapping_add(self.keepalive_ms));
            let datagram = clock_sync(self.post_v3_envelope_seq, clock_ms)?;
            self.post_v3_envelope_seq = self.post_v3_envelope_seq.wrapping_add(1);
            return Ok(vec![datagram]);
        }
        let Some(ladder) = self.ladder.as_ref() else {
            return Ok(Vec::new());
        };
        let Some(due) = self.next_release_at_ms else {
            return Ok(Vec::new());
        };
        // Signed wrap-space compare: a negative difference means "not yet".
        if clock_ms.wrapping_sub(due).cast_signed() < 0 {
            return Ok(Vec::new());
        }
        let Some(record) = ladder.records().get(self.next_post_v3) else {
            self.next_release_at_ms = None;
            return Ok(Vec::new());
        };

        let datagram = ladder.datagram(
            self.next_post_v3,
            self.post_v3_envelope_seq,
            self.post_v3_message_seq,
            self.post_v3_reliable_seq,
        )?;
        self.post_v3_envelope_seq = self.post_v3_envelope_seq.wrapping_add(1);
        self.post_v3_message_seq = self.post_v3_message_seq.wrapping_add(1);
        self.post_v3_reliable_seq = self.post_v3_reliable_seq.wrapping_add(1);
        self.next_post_v3 += 1;

        self.next_release_at_ms = ladder.records().get(self.next_post_v3).map(|next| {
            // The plan's own offset difference is the reference's gap: 4 ms
            // between chunks of one message, 30 ms between messages.
            let gap = next.offset_ms().saturating_sub(record.offset_ms());
            clock_ms.wrapping_add(gap)
        });
        Ok(vec![datagram])
    }

    /// Milliseconds until the next ladder record is due, once armed.
    ///
    /// `None` when the ladder is not armed or has drained. `Some(0)` when a
    /// record is already due. A caller that sleeps for this long (capped by its
    /// own tick) honours the reference's 4 ms chunk gap without polling.
    #[must_use]
    pub fn ladder_wait_ms(&self, clock_ms: u32) -> Option<u32> {
        let due = self.next_release_at_ms?;
        self.ladder.as_ref()?.records().get(self.next_post_v3)?;
        let ahead = due.wrapping_sub(clock_ms);
        // Signed wrap-space: a "negative" remaining time is already due.
        Some(if ahead.cast_signed() <= 0 { 0 } else { ahead })
    }

    /// Whether the acceptance flight has gone out.
    #[must_use]
    pub const fn handshake_done(&self) -> bool {
        self.handshake_done
    }

    /// Whether the registration response has gone out.
    #[must_use]
    pub const fn v3_responded(&self) -> bool {
        self.v3_responded
    }

    /// How many `SM_CONNECT_REQUEST` datagrams this session has answered.
    ///
    /// One is the handshake the client needs to open the REP connection; more than
    /// one means the client asked again after that connection was already
    /// accepted, which is the only wire shape a late Carrier connection handshake
    /// can take. The caller logs it, because it is the measurement that decides
    /// whether the client's actor game connection is a transport handshake it
    /// expects us to answer or a condition it owns.
    #[must_use]
    pub const fn connect_replies(&self) -> u32 {
        self.connect_replies
    }

    /// Answer one decrypted application datagram.
    ///
    /// # Errors
    /// Returns a [`RepError`] only when one of the server's own replies cannot be
    /// framed; bad client input yields an empty reply list.
    pub fn on_app_data(
        &mut self,
        datagram: &[u8],
        clock_ms: u32,
    ) -> Result<Vec<Vec<u8>>, RepError> {
        let Ok((envelope, _)) = Envelope::decode(datagram) else {
            return Ok(Vec::new());
        };
        let sequence = envelope.sequence();
        self.inbound_count = self.inbound_count.saturating_add(1);

        let ack_allowed = self.ack_coalesce_ms == 0
            || clock_ms.wrapping_sub(self.next_ack_ms) >= self.ack_coalesce_ms;
        if ack_allowed {
            self.next_ack_ms = clock_ms.wrapping_add(self.ack_coalesce_ms);
        }
        let ack_first = ack_window_first(sequence, self.inbound_count, self.ack_window);
        let connect_reply = if self
            .next_connect_reply_ms
            .is_none_or(|due| clock_ms.wrapping_sub(due).cast_signed() >= 0)
        {
            ConnectReply::Allowed
        } else {
            ConnectReply::Cooldown
        };

        let request = RepRequest {
            app: datagram,
            client_env_seq: sequence,
            handshake_done: self.handshake_done,
            connect_reply,
            v3_done: self.v3_responded,
            ack_allowed,
            ack_first,
            clock_ms,
        };
        let outcome = process(&request)?;
        if outcome.had_connect_request {
            self.handshake_done = true;
            self.connect_replies = self.connect_replies.saturating_add(1);
            self.next_connect_reply_ms = Some(clock_ms.wrapping_add(CONNECT_REPLY_COOLDOWN_MS));
        }
        if outcome.answered_v3 {
            self.v3_responded = true;
            // The post-V3 stream goes out on the SERVER's clock, starting on the
            // first tick after the registration answer.
            //
            // The outbound envelope counter is the reference's `next_out_seq`:
            // `max(1, inbound + 1)`, and the V3 answer is built from
            // `inbound + 1` WITHOUT consuming it. So the keepalive takes
            // `inbound + 1` and the ladder's first record takes `inbound + 2`,
            // exactly as `PeerSession.on_app_data` -> `maybe_keepalive` ->
            // `maybe_pump_replay` order them.
            self.post_v3_envelope_seq = sequence.wrapping_add(1);
            self.post_v3_message_seq = 1;
            self.post_v3_reliable_seq = 1;
            self.next_keepalive_at_ms = Some(clock_ms);
            if self.ladder.is_some() && self.armed_at_ms.is_none() {
                self.armed_at_ms = Some(clock_ms);
                self.next_post_v3 = 0;
                self.next_release_at_ms = self
                    .ladder
                    .as_ref()
                    .and_then(|ladder| ladder.records().first())
                    .map(|first| clock_ms.wrapping_add(first.offset_ms()));
            }
        }
        Ok(outcome.replies)
    }
}

impl Default for RepSession {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_ack_window_slides_after_the_window_width() {
        assert_eq!(ack_window_first(2, 1, 16_384), 2);
        assert_eq!(ack_window_first(10, 3, 16_384), 8);
        assert_eq!(ack_window_first(100, 10, 4), 97);
        // Wrap-safe: a range that crosses the 16-bit boundary stays one short range.
        assert_eq!(ack_window_first(1, 2, 16_384), 0);
    }

    #[test]
    fn a_registration_request_is_recognised_by_its_marker() {
        let mut payload = vec![0u8; 68];
        payload[20] = RECORD_TYPE_MARKER[0];
        payload[21] = RECORD_TYPE_MARKER[1];
        payload[22] = REGISTRATION_REQUEST_WIRE_ID as u8;
        assert!(is_registration_request(&MessageRecord::new(0, payload)));

        // Same bytes on a different channel, or below the size floor, are not it.
        assert!(!is_registration_request(&MessageRecord::new(
            1,
            vec![0u8; 68]
        )));
        assert!(!is_registration_request(&MessageRecord::new(
            0,
            vec![0u8; 8]
        )));
    }
}
