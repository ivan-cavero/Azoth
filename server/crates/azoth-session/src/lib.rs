//! Session state for one player: the machine that turns a DTLS transport into an authenticated
//! game session.
//!
//! WHY THIS CRATE EXISTS
//! =====================
//! `docs/PLAN-backend-rust.md` §6.3 draws the connection's life as five states with two owners.
//! The Python prototype has the same information spread across `PeerSession` fields and a chain of
//! `if`s, which is why a stalled login shows up server-side as "nothing happened" rather than as
//! "this arrow never fired". Making the machine an enum with named deadlines is the whole point:
//! a stall becomes reportable instead of invisible.
//!
//! THE FIVE STATES AND WHO OWNS THEM
//! =================================
//! | State | Meaning | Deadline / rule |
//! | --- | --- | --- |
//! | [`SessionState::Transport`] | DTLS is up, no V3 registration yet | the **authentication deadline**; the prototype had none and relied on the client's own 15 s registration timeout, so a failed handshake left no trace server-side |
//! | [`SessionState::Authenticated`] | the V3 arrived and the ticket validated | identity is bound here — this is the handoff §6.3 says the prototype skips, because it accepted any registration and rewrote the character id per session |
//! | [`SessionState::Active`] | the player is in the world | idle timeout; heartbeats exist because the client's state watchdog (`FUN_146445e10`) counts frames without an expected message and tears down when its budget is spent |
//! | [`SessionState::Draining`] | no new spawns, the existing player finishes | bounded by a drain grace, then [`CloseReason::DrainComplete`] |
//! | [`SessionState::Closed`] | terminal | release the ticket, emit an audit record |
//!
//! `worldd` owns all five. `regiond` owns the *claim* that produces the login ticket (§7.2) and
//! learns about it through the world's `ClaimConsumed`; it never drives a session state.
//!
//! TICKET EXPIRY NEVER CLOSES AN AUTHENTICATED SESSION
//! ==================================================
//! The login ticket's job ends at [`SessionState::Authenticated`]. On success the session mints a
//! [`ReconnectTicket`] with its own expiry and a generation counter, and the client keeps only the
//! latest. The two are separate types precisely so the mistake is unrepresentable: the binding this
//! session keeps after authentication has **no expiry field at all** ([`ticket`]), so no code path
//! can close a live player because their login budget ran out. See [`ticket`] for the rule.
//!
//! THE ACK WINDOW MUST SLIDE
//! =========================
//! MEASURED 2026-10-14 (`services/world/src/azoth_world/rep.py`, `ACK_WINDOW`). The `CT_ACKS` reply
//! carries `ack_first` and `ack_last` as two 16-bit fields, so a wrap-aware reader can represent a
//! range narrower than half the sequence space (32,768). The prototype pinned `ack_first` to the
//! session's first inbound sequence, so the range grew by one per datagram and crossed that limit
//! at ~26 minutes of play. The client did not report an error: it stopped treating its reliable
//! records as delivered and retransmitted every one of them, roughly 200 times (140,174 records
//! carrying only 660 distinct sequences), with `OnLocalNetworkConnectionWarning` climbing
//! throughout. [`AckWindow`] therefore acks the most recent 16,384 sequences and slides.
//!
//! THE TRANSPORT AND THE TICK ARE SEPARATE CONCERNS
//! ===============================================
//! `azoth-dtls` owns the socket and the handshake, and its `pump` is blocking and returns events so
//! a handshake can never run inside the 20 ms tick (§8.1 budgets 4 µs per player there). This crate
//! owns neither the socket nor the thread: it owns the *state*, and it is driven by
//! [`Session::advance`] with a `now` the caller supplies.
//!
//! THE CALLER OWNS THE CLOCK, AND `advance` IS THE ONLY DOOR
//! ========================================================
//! Nothing in this crate sleeps, spawns, or reads a socket. Every deadline is compared against the
//! `now` passed to [`Session::advance`], so the same code that takes 15 real seconds in production is
//! exercised in microseconds by a test — and the two defects documented below were only visible at
//! real play speed, which is why they survived so long. An `Instant::now()` inside each method would
//! make most of this measurable only as a symptom on the client.
//!
//! The one wall-clock read is the anchor taken when a session starts ([`ticket::TicketClock`]),
//! because a [`ReconnectTicket`] carries an absolute Unix expiry and `Instant` is not convertible to
//! one. Every later conversion is a pure function of the caller's clock.
//!
//! [`Session::advance`] takes `&mut self` because advancing time is what stages a retransmission, and
//! staging one **must** charge a try to the record being retransmitted: otherwise the next tick
//! stages the same record again, forever, which is the resend storm [`resend`] documents. So the
//! contract is one-way — a sequence returned in [`SessionEvent::Retransmit`] has already been charged
//! as sent at that `now`, and the caller must transmit it. A second `confirm_sent` call would be one
//! forgotten call away from an unbounded loop of duplicate datagrams.
//!
//! [`Session::register`] cannot return events, so the reconnect ticket it mints is queued and comes
//! back from the next [`Session::advance`]. That is the only deferred event in the crate.
//!
//! WHAT THIS CRATE DOES NOT OWN
//! ============================
//! Sockets, threads, retransmission *transmission* (it says which sequences are due; the caller
//! sends the bytes), heartbeats, persistence, and the `regiond` claim.

#![forbid(unsafe_code)]

pub mod acks;
pub mod resend;
pub mod state;
pub mod ticket;

pub use acks::AckWindow;
pub use resend::ResendTable;
pub use state::Session;
pub use ticket::{LoginTicket, ReconnectTicket};

use std::time::Duration;

/// The width of the sliding ACK window, in inbound envelope sequences.
///
/// 16,384 is half of the largest range the two 16-bit ACK fields can carry unambiguously (32,768),
/// and at the measured ~21 inbound datagrams/s it still covers about 13 minutes of history. The
/// measurement that makes the window mandatory — and that a *pinned* range costs the session — is
/// in the crate docs and in [`acks`].
pub const ACK_WINDOW_DEFAULT: u16 = 16_384;

/// Minimum time before the same reliable record is retransmitted again.
///
/// 0.3 s is the long-standing value from the Python prototype. Lower values were measured to
/// produce an in-flight resend storm (650 resends in one second) that lines up with a burst of
/// `OnLocalNetworkConnectionWarning`.
pub const RESEND_INTERVAL_DEFAULT: Duration = Duration::from_millis(300);

/// How many times one reliable record may be retransmitted before it is dropped.
///
/// The cap exists because resending a 12.7 KB record 4,229 times made the client's condition worse,
/// not better (`rep.py`, 2026-09-20). See [`resend`].
pub const MAX_RESEND_TRIES_DEFAULT: u8 = 6;

/// How long a DTLS peer may sit in [`SessionState::Transport`] without registering.
///
/// Matches the client's own 15 s registration timeout (§6.3): waiting much longer than the client
/// does only wastes session slots on players who are already gone.
pub const AUTHENTICATION_TIMEOUT_DEFAULT: Duration = Duration::from_secs(15);

/// How long an authenticated session may receive nothing before it closes as idle.
///
/// The client's own in-game watchdog gives up after ~30 s of silence (`rep.py`), so the server closes
/// first and gets to write down why.
pub const IDLE_TIMEOUT_DEFAULT: Duration = Duration::from_secs(30);

/// How long a draining session may keep its player connected.
///
/// A policy value, not a measurement: long enough for a flight out of a fight, short enough that a
/// shutting world does not hold a lease forever.
pub const DRAIN_GRACE_DEFAULT: Duration = Duration::from_secs(30);

/// Lifetime handed to a freshly minted [`ReconnectTicket`], in seconds.
///
/// Deliberately longer than the login ticket's window: it exists so a player who drops mid-session
/// can come back to the same character without a new login round-trip.
pub const RECONNECT_TICKET_TTL_SECS_DEFAULT: i64 = 300;

/// Everything a [`Session`] needs to know that is not the session itself.
///
/// Every field is a policy knob with a measured default, so a test or one deployment can change one
/// without reimplementing the machine. Construct with `..SessionConfig::default()`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionConfig {
    /// Width of the sliding ACK window, in inbound envelope sequences.
    pub ack_width: u16,
    /// Minimum time between retransmissions of the same reliable record.
    pub resend_interval: Duration,
    /// Retransmissions allowed per reliable record before it is dropped.
    pub max_resend_tries: u8,
    /// How long a [`SessionState::Transport`] peer may take to register.
    pub authentication_timeout: Duration,
    /// How long an authenticated session may stay silent.
    pub idle_timeout: Duration,
    /// How long a draining session may keep its player.
    pub drain_grace: Duration,
    /// Lifetime, in seconds, of a minted [`ReconnectTicket`].
    pub reconnect_ticket_ttl_secs: i64,
}

impl Default for SessionConfig {
    fn default() -> Self {
        Self {
            ack_width: ACK_WINDOW_DEFAULT,
            resend_interval: RESEND_INTERVAL_DEFAULT,
            max_resend_tries: MAX_RESEND_TRIES_DEFAULT,
            authentication_timeout: AUTHENTICATION_TIMEOUT_DEFAULT,
            idle_timeout: IDLE_TIMEOUT_DEFAULT,
            drain_grace: DRAIN_GRACE_DEFAULT,
            reconnect_ticket_ttl_secs: RECONNECT_TICKET_TTL_SECS_DEFAULT,
        }
    }
}

/// Which stage of its life a session is in.
///
/// `worldd` owns all five (plan §6.3); `regiond` owns the claim that produces the login ticket and
/// never drives a state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SessionState {
    /// DTLS is up, and no V3 registration has been accepted yet.
    Transport,
    /// The V3 was accepted and the ticket validated: identity is bound.
    Authenticated,
    /// The player is in the world.
    Active,
    /// No new spawns; the existing player is finishing.
    Draining,
    /// Terminal. The ticket has been released and an audit record is due.
    Closed,
}

impl SessionState {
    /// The state's name, for logs and audit records.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Transport => "transport",
            Self::Authenticated => "authenticated",
            Self::Active => "active",
            Self::Draining => "draining",
            Self::Closed => "closed",
        }
    }

    /// Whether the session may still carry game traffic.
    #[must_use]
    pub fn is_open(self) -> bool {
        !matches!(self, Self::Closed)
    }
}

/// Something the caller must act on.
///
/// Events are returned, never dispatched: this crate has no channel, no callback and no thread, so
/// "who sends the bytes" stays the caller's decision.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SessionEvent {
    /// The authentication deadline passed without a V3 registration.
    AuthenticationTimedOut,
    /// A fresh reconnect ticket was issued. The client keeps only the latest.
    ReconnectTicketIssued {
        /// The ticket to hand to the client.
        ticket: ReconnectTicket,
    },
    /// These reliable sequences are due for retransmission.
    ///
    /// They have already been charged at the `advance` that produced them, so the caller must
    /// transmit them and must not call anything to confirm it.
    Retransmit(Vec<u16>),
    /// The session should close, with the reason.
    Close(CloseReason),
    /// The session became active: the first application datagram arrived.
    Activated,
}

/// Why a session closed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CloseReason {
    /// No V3 registration arrived within the authentication deadline.
    AuthenticationTimeout,
    /// Nothing arrived for longer than the idle timeout.
    Idle,
    /// The transport reported the peer gone.
    PeerGone,
    /// A draining session finished.
    DrainComplete,
    /// The peer broke the protocol.
    ProtocolError,
}

/// Everything this crate can refuse.
///
/// There is one error type because every failure in a session machine is either a rejected input
/// (a registration that must not authenticate) or a call made in the wrong state, and the caller
/// distinguishes them by which call returned the error. A rejected registration is **not** fatal:
/// the session stays in [`SessionState::Transport`] and its bound ticket survives, so the client's
/// retry form can still succeed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SessionError {
    /// The V3 `client_signature` named a different ticket than the one this session was given.
    TicketMismatch {
        /// The ticket id the session holds.
        expected: String,
        /// The id the request presented, with the `sig:` prefix stripped.
        presented: Option<String>,
    },
    /// The bound ticket's expiry has passed at the time the registration arrived.
    TicketExpired {
        /// The ticket that expired.
        ticket_id: String,
    },
    /// This session's ticket was already consumed, so a second registration cannot use it.
    ///
    /// This is the check that stops two clients from being the same player.
    TicketConsumed {
        /// The ticket that was already consumed, when it is still known.
        ticket_id: String,
    },
    /// No login ticket was bound, so there is nothing to validate the registration against.
    ///
    /// The world learns the ticket from the region's claim (§7.2) before the V3 can arrive; a
    /// session that receives one anyway must not authenticate.
    NoTicketBound,
    /// The ticket carries an empty signature.
    ///
    /// The queue handoff gate compares the signature, so an empty one is not a weak credential —
    /// it is a ticket that cannot be handed off at all.
    EmptySignature {
        /// The ticket whose signature is empty.
        ticket_id: String,
    },
    /// The retry form's `session_uuid` is not the ticket id.
    ///
    /// On the retry format the session identity travels in `session_uuid`, so a mismatch means the
    /// body belongs to another ticket.
    SessionUuidMismatch {
        /// The ticket id this session holds.
        expected: String,
        /// The `session_uuid` the request carried.
        presented: Option<String>,
    },
    /// A login ticket was bound twice, or bound after the session left
    /// [`SessionState::Transport`].
    TicketAlreadyBound {
        /// The ticket already bound.
        ticket_id: String,
    },
    /// An application datagram arrived before the V3 registration was accepted.
    NotAuthenticated(std::net::SocketAddr),
    /// The session is already closed.
    Closed(std::net::SocketAddr),
    /// A reliable record with this sequence is already queued.
    SequenceAlreadyQueued {
        /// The duplicate sequence.
        sequence: u16,
    },
}

impl std::fmt::Display for SessionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::TicketMismatch { expected, presented } => match presented {
                Some(presented) => write!(f, "ticket {presented} is not the bound ticket {expected}"),
                None => write!(f, "registration names no ticket, expected {expected}"),
            },
            Self::TicketExpired { ticket_id } => write!(f, "ticket {ticket_id} has expired"),
            Self::TicketConsumed { ticket_id } => write!(f, "ticket {ticket_id} was already consumed"),
            Self::NoTicketBound => write!(f, "no login ticket is bound to this session"),
            Self::EmptySignature { ticket_id } => write!(f, "ticket {ticket_id} has an empty signature"),
            Self::SessionUuidMismatch { expected, presented } => match presented {
                Some(presented) => write!(f, "session_uuid {presented} is not the ticket {expected}"),
                None => write!(f, "retry body carries no session_uuid, expected {expected}"),
            },
            Self::TicketAlreadyBound { ticket_id } => {
                write!(f, "ticket {ticket_id} is already bound to this session")
            }
            Self::NotAuthenticated(addr) => write!(f, "{addr} has not registered yet"),
            Self::Closed(addr) => write!(f, "the session for {addr} is closed"),
            Self::SequenceAlreadyQueued { sequence } => {
                write!(f, "reliable sequence {sequence} is already queued")
            }
        }
    }
}

impl std::error::Error for SessionError {}
