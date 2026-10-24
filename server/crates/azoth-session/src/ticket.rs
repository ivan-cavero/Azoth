//! The two tickets, and the rules that keep them apart.
//!
//! WHY THERE ARE TWO TYPES
//! =======================
//! `docs/PLAN-backend-rust.md` §6.3 draws it as two structs on purpose. A [`LoginTicket`] is the
//! only thing that can enter a world: `regiond` mints it from a claim (§7.2), the world validates
//! it against the V3 registration, and it is consumed exactly once. A [`ReconnectTicket`] is what
//! an already authenticated session uses to come back; it has its own expiry and a `generation`
//! counter because the client keeps only the latest one it was issued.
//!
//! One type with an optional generation, or one type whose expiry was reused for both jobs, is the
//! conflation this crate exists to prevent: it makes "the login budget ran out" indistinguishable
//! from "this session is over".
//!
//! THE CRITICAL RULE
//! =================
//! **Ticket expiry never closes an authenticated session.** The login ticket's job ends the moment
//! the V3 is accepted ([`crate::SessionState::Authenticated`]). After that the session keeps a
//! *binding* — ticket id, world, character, persona, REP address — and that binding deliberately
//! has **no expiry field at all**, so no code path in [`crate::state`] can read a login expiry once
//! authentication succeeded. The unrepresentable mistake is the point: a live player must not be
//! disconnected mid-fight because the login window they used minutes ago has closed, and the client
//! has no recovery path from that except a full re-login.
//!
//! WHAT THE TICKET SUPPLIES, AND WHAT THE V3 CANNOT
//! ================================================
//! On the **strict** format the character id is not in any V3 field — the measured schedule has no
//! character slot (`azoth_wire::v3::RegistrationRequest::character_id` recovers it from the opaque
//! auth region at best) — so the ticket is the authority for it. That is why [`LoginTicket`] carries
//! `character_id` and why [`LoginTicket::validate_against`] does not compare a character id: there
//! is nothing trustworthy on the other side to compare against.
//!
//! On the **retry** format the identity travels in the V3 `session_uuid`, so that field *is*
//! compared against the ticket id.
//!
//! `signature` must be non-empty: the queue handoff gate compares it, so an empty signature is not
//! a weak credential but a ticket that cannot be handed off at all.

use std::time::{Instant, SystemTime, UNIX_EPOCH};

use azoth_wire::v3::{RegistrationRequest, RequestFormat};

use crate::SessionError;

/// The login ticket: the only thing that can enter a world. Consumed once.
///
/// Minted by `regiond` from a claim (§7.2) and validated by the world against the V3 registration.
/// After [`crate::Session::register`] accepts it, the ticket is finished: its expiry is never
/// consulted again. See the module docs for why that matters.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LoginTicket {
    /// The ticket id the claim recorded; the V3 `client_signature` must name it.
    pub ticket_id: String,
    /// The handoff signature. Must be non-empty: the queue handoff gate compares it.
    pub signature: String,
    /// The world this ticket is for. The world id is **not** recoverable from the V3 body — the
    /// region in it is a 21-byte opaquely-named prefix (`azoth_wire::v3`), not a world id — so the
    /// ticket is the only authority for it.
    pub world_id: String,
    /// The character the player will occupy. On the strict V3 format this value comes only from
    /// here.
    pub character_id: String,
    /// The persona the character belongs to.
    pub persona_id: String,
    /// Where the client should reach the world, as the ticket advertises it.
    pub rep_address: String,
    /// Absolute expiry, in Unix seconds, as the claim recorded it.
    pub expires_at_unix: i64,
}

impl LoginTicket {
    /// Whether the ticket has expired at `unix_now`.
    ///
    /// The comparison is inclusive: a ticket is not valid during the second it expires in.
    #[must_use]
    pub fn is_expired(&self, unix_now: i64) -> bool {
        unix_now >= self.expires_at_unix
    }

    /// Validate this ticket against a V3 registration body.
    ///
    /// `unix_now` is the wall-clock second that corresponds to the caller's `now`; the session
    /// derives it with [`crate::Session::unix_at`], so the check stays a pure function of the
    /// caller's clock.
    ///
    /// The order of the checks is the order a client's mistakes should be reported in: a ticket
    /// that cannot be handed off, then a body that names another ticket, then a body whose retry
    /// identity disagrees, then expiry.
    ///
    /// # Errors
    /// [`SessionError::EmptySignature`], [`SessionError::TicketMismatch`],
    /// [`SessionError::SessionUuidMismatch`] or [`SessionError::TicketExpired`].
    pub fn validate_against(
        &self,
        request: &RegistrationRequest,
        unix_now: i64,
    ) -> Result<(), SessionError> {
        if self.signature.trim().is_empty() {
            return Err(SessionError::EmptySignature {
                ticket_id: self.ticket_id.clone(),
            });
        }

        // The signature field is `sig:<ticket_id>`; `ticket_uuid` strips the prefix.
        let presented = request.ticket_uuid();
        if presented != Some(self.ticket_id.as_str()) {
            return Err(SessionError::TicketMismatch {
                expected: self.ticket_id.clone(),
                presented: presented.map(str::to_owned),
            });
        }

        // The retry form carries the identity in `session_uuid` instead of in the schedule, so that
        // is the field that has to agree with the ticket there.
        if request.format == RequestFormat::Retry {
            let session_uuid = request.session_uuid();
            if session_uuid != Some(self.ticket_id.as_str()) {
                return Err(SessionError::SessionUuidMismatch {
                    expected: self.ticket_id.clone(),
                    presented: session_uuid.map(str::to_owned),
                });
            }
        }

        if self.is_expired(unix_now) {
            return Err(SessionError::TicketExpired {
                ticket_id: self.ticket_id.clone(),
            });
        }

        Ok(())
    }
}

/// The post-authentication reconnect ticket.
///
/// Separate from [`LoginTicket`] because it answers a different question — "may this already
/// authenticated client come back?" rather than "may this client enter?" — and because conflating
/// the two is what closes a live session at its login expiry (§6.3). The `generation` counter exists
/// because the client keeps only the latest ticket it was issued; a reconnect presenting an older
/// generation is stale, not authenticated.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReconnectTicket {
    /// The ticket id handed to the client.
    pub ticket_id: String,
    /// Absolute expiry, in Unix seconds.
    pub expires_at_unix: i64,
    /// Which issue this is. Increments for every ticket this session mints.
    pub generation: u32,
}

impl ReconnectTicket {
    /// Whether the ticket has expired at `unix_now`.
    #[must_use]
    pub fn is_expired(&self, unix_now: i64) -> bool {
        unix_now >= self.expires_at_unix
    }

    /// The ticket for the next generation, derived from the identity it belongs to.
    ///
    /// Deriving the id from the login ticket id plus the generation keeps a reconnect traceable back
    /// to the session that issued it without keeping a registry of issued tickets.
    #[must_use]
    pub fn mint(base: &str, generation: u32, expires_at_unix: i64) -> Self {
        Self {
            ticket_id: format!("{base}-r{generation}"),
            expires_at_unix,
            generation,
        }
    }
}

/// What authentication bound a session to.
///
/// Deliberately has **no expiry field**: once a session is authenticated there is no login-ticket
/// deadline left to read, so no code path can close a live player because their login budget ran
/// out. The field list is the ticket's identity without the ticket's clock, and that is the
/// type-level form of the rule in the module docs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionBinding {
    /// The consumed login ticket this binding came from.
    pub ticket_id: String,
    /// The world the ticket was minted for.
    pub world_id: String,
    /// The character the player occupies.
    pub character_id: String,
    /// The persona the character belongs to.
    pub persona_id: String,
    /// The REP address the client was told to reach.
    pub rep_address: String,
}

impl SessionBinding {
    /// Take the identity out of a consumed ticket, deliberately dropping its expiry.
    #[must_use]
    pub fn consume(ticket: LoginTicket) -> Self {
        Self {
            ticket_id: ticket.ticket_id,
            world_id: ticket.world_id,
            character_id: ticket.character_id,
            persona_id: ticket.persona_id,
            rep_address: ticket.rep_address,
        }
    }

    /// The character the session is bound to.
    #[must_use]
    pub fn character_id(&self) -> &str {
        &self.character_id
    }

    /// The world the session is bound to.
    #[must_use]
    pub fn world_id(&self) -> &str {
        &self.world_id
    }

    /// Where the client was told to reach this world.
    #[must_use]
    pub fn rep_address(&self) -> &str {
        &self.rep_address
    }
}

/// The bridge between the caller's monotonic clock and the absolute Unix expiries tickets carry.
///
/// `Instant` is not convertible to a wall clock, so exactly one `SystemTime::now()` is read when a
/// session starts and every later conversion goes through [`TicketClock::unix_at`] — a pure function
/// of the caller's `now`. That is what lets a test put a ticket's expiry in the future or in the past
/// without touching the machine clock, and it keeps the state machine itself free of ambient time.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TicketClock {
    /// `(instant, unix second)` captured once, at session start.
    anchor: (Instant, i64),
}

impl TicketClock {
    /// Anchor the clock at `now`.
    #[must_use]
    pub fn new(now: Instant) -> Self {
        let unix_now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |elapsed| i64::try_from(elapsed.as_secs()).unwrap_or(i64::MAX));
        Self {
            anchor: (now, unix_now),
        }
    }

    /// The Unix second that corresponds to `now` for this session.
    ///
    /// A `now` before the anchor saturates at the anchor, so the result never runs backwards.
    #[must_use]
    pub fn unix_at(&self, now: Instant) -> i64 {
        let (anchor_instant, anchor_unix) = self.anchor;
        let elapsed = now.saturating_duration_since(anchor_instant).as_secs();
        anchor_unix.saturating_add(i64::try_from(elapsed).unwrap_or(i64::MAX))
    }

    /// The Unix second `seconds` after `now`, for stamping an expiry.
    #[must_use]
    pub fn expiry_after(&self, now: Instant, seconds: i64) -> i64 {
        self.unix_at(now).saturating_add(seconds)
    }
}
