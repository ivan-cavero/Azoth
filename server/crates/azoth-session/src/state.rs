//! The machine itself: [`Session`], its deadlines, and the two tables underneath it.
//!
//! WHY THIS FILE IS ONLY THE MACHINE
//! ================================
//! The vocabulary a caller touches — the five states, the events, the close reasons, the
//! configuration and the error type — lives in the crate root, and the tickets, the identity binding
//! and the clock anchor live in [`crate::ticket`]. What is left is one struct and the transitions
//! between its states, which is what this file should have to be read for; the cross-cutting rules
//! are stated once, on the crate root, rather than repeated per module.
//!
//! Every transition either returns events or defers them to [`Session::advance`]; none of them
//! transmits, sleeps or observes the network.

use std::net::SocketAddr;
use std::time::Instant;

use azoth_wire::v3::RegistrationRequest;

use crate::acks::AckWindow;
use crate::resend::ResendTable;
use crate::ticket::{LoginTicket, ReconnectTicket, SessionBinding, TicketClock};
use crate::{CloseReason, SessionConfig, SessionError, SessionEvent, SessionState};

/// One player's session.
///
/// Construct it when the DTLS handshake completes — the authentication deadline starts there, not at
/// the first datagram — and drive it with the tick's own `now`.
#[derive(Debug)]
pub struct Session {
    peer: SocketAddr,
    config: SessionConfig,
    state: SessionState,
    /// Maps the caller's `now` onto the absolute Unix expiries tickets carry.
    clock: TicketClock,
    /// When [`SessionState::Transport`] stops being acceptable.
    auth_deadline: Instant,
    /// The last time anything arrived from the peer.
    last_inbound: Instant,
    /// The login ticket, before it is consumed.
    ticket: Option<LoginTicket>,
    /// What authentication bound, after the ticket is consumed.
    binding: Option<SessionBinding>,
    /// The id of the ticket this session consumed, kept for errors and audit after the ticket is
    /// gone.
    consumed_ticket_id: Option<String>,
    /// How many reconnect tickets this session has minted.
    reconnect_generation: u32,
    /// Inbound acknowledgement window.
    ack: AckWindow,
    /// Outbound reliable records awaiting acknowledgement.
    resend: ResendTable,
    /// Events produced by a call that cannot return them (only [`Session::register`] qualifies).
    pending: Vec<SessionEvent>,
    /// When a draining session must be closed.
    drain_deadline: Option<Instant>,
}

impl Session {
    /// A session in [`SessionState::Transport`] for `peer`, started at `Instant::now()`.
    ///
    /// A caller with a tick clock should use [`Session::new_at`]: deadlines are compared against the
    /// `now` passed to [`Session::advance`], so anchoring them to an internal read shifts every
    /// deadline by however long the construction itself took.
    #[must_use]
    pub fn new(peer: SocketAddr, config: SessionConfig) -> Self {
        Self::new_at(peer, config, Instant::now())
    }

    /// A session in [`SessionState::Transport`] for `peer`, started at `now`.
    ///
    /// The form a tick clock wants, and the form every test uses: with the start supplied, a deadline
    /// is a pure function of the caller's clock and needs no sleeping to exercise.
    #[must_use]
    pub fn new_at(peer: SocketAddr, config: SessionConfig, now: Instant) -> Self {
        let ack = AckWindow::new(config.ack_width);
        let resend = ResendTable::new(config.resend_interval, config.max_resend_tries);
        let auth_deadline = now + config.authentication_timeout;
        Self {
            peer,
            config,
            state: SessionState::Transport,
            clock: TicketClock::new(now),
            auth_deadline,
            last_inbound: now,
            ticket: None,
            binding: None,
            consumed_ticket_id: None,
            reconnect_generation: 0,
            ack,
            resend,
            pending: Vec::new(),
            drain_deadline: None,
        }
    }

    /// The peer address this session belongs to.
    #[must_use]
    pub fn peer(&self) -> SocketAddr {
        self.peer
    }

    /// The current state.
    #[must_use]
    pub fn state(&self) -> SessionState {
        self.state
    }

    /// The Unix second that corresponds to `now` for this session.
    ///
    /// Every absolute expiry in this crate is expressed in Unix seconds, so the caller needs the same
    /// conversion to mint or check one — a reconnect ticket handed to a client must carry a deadline
    /// both ends agree on.
    #[must_use]
    pub fn unix_at(&self, now: Instant) -> i64 {
        self.clock.unix_at(now)
    }

    /// The character this session is bound to, once authenticated.
    #[must_use]
    pub fn character_id(&self) -> Option<&str> {
        self.binding.as_ref().map(SessionBinding::character_id)
    }

    /// The world this session is bound to, once authenticated.
    #[must_use]
    pub fn world_id(&self) -> Option<&str> {
        self.binding.as_ref().map(SessionBinding::world_id)
    }

    /// Where the client was told to reach this world, once authenticated.
    #[must_use]
    pub fn rep_address(&self) -> Option<&str> {
        self.binding.as_ref().map(SessionBinding::rep_address)
    }

    /// The login ticket this session consumed, if any.
    #[must_use]
    pub fn consumed_ticket_id(&self) -> Option<&str> {
        self.consumed_ticket_id.as_deref()
    }

    /// How many reconnect tickets this session has minted.
    #[must_use]
    pub fn reconnect_generation(&self) -> u32 {
        self.reconnect_generation
    }

    /// The current acknowledgement range, `(first, last)`.
    #[must_use]
    pub fn ack_range(&self) -> (u16, u16) {
        self.ack.range()
    }

    /// How many reliable records are still unacknowledged.
    #[must_use]
    pub fn outstanding(&self) -> usize {
        self.resend.len()
    }

    /// Give this session the login ticket the region's claim produced (plan §7.2).
    ///
    /// The world learns the ticket out of band — from `regiond`, before the client's V3 can arrive —
    /// so it is bound here rather than carried by the registration body. Binding twice, or binding
    /// after authentication, is refused: a session has exactly one identity.
    ///
    /// # Errors
    /// [`SessionError::TicketAlreadyBound`] when the session already holds a ticket or is no longer
    /// in [`SessionState::Transport`].
    pub fn bind_ticket(&mut self, ticket: LoginTicket) -> Result<(), SessionError> {
        let ticket_id = ticket.ticket_id.clone();
        if self.ticket.is_some() || self.state != SessionState::Transport {
            return Err(SessionError::TicketAlreadyBound { ticket_id });
        }
        self.ticket = Some(ticket);
        Ok(())
    }

    /// A V3 registration arrived. Validates the ticket and moves to [`SessionState::Authenticated`].
    ///
    /// The reconnect ticket this mints is queued rather than returned — this signature has no room for
    /// events — so the caller acts on it in the next [`Session::advance`]. A rejected registration
    /// leaves the session in [`SessionState::Transport`] **with its ticket intact**, so the client's
    /// retry form can still succeed.
    ///
    /// # Errors
    /// * [`SessionError::TicketConsumed`] when this session already authenticated. That is the check
    ///   which stops two clients from being the same player.
    /// * [`SessionError::NoTicketBound`] when no claim was bound before the registration arrived.
    /// * whatever [`LoginTicket::validate_against`] reports: an empty signature, a ticket mismatch, a
    ///   retry body naming another identity, or an expired ticket.
    pub fn register(
        &mut self,
        request: &RegistrationRequest,
        now: Instant,
    ) -> Result<(), SessionError> {
        if self.state != SessionState::Transport {
            let ticket_id = self
                .consumed_ticket_id
                .clone()
                .or_else(|| request.ticket_uuid().map(str::to_owned))
                .unwrap_or_default();
            return Err(SessionError::TicketConsumed { ticket_id });
        }

        match self.ticket.as_ref() {
            Some(ticket) => ticket.validate_against(request, self.unix_at(now))?,
            None => return Err(SessionError::NoTicketBound),
        }
        let Some(ticket) = self.ticket.take() else {
            return Err(SessionError::NoTicketBound);
        };

        self.consumed_ticket_id = Some(ticket.ticket_id.clone());
        self.binding = Some(SessionBinding::consume(ticket));
        self.state = SessionState::Authenticated;
        self.last_inbound = now;

        let ticket = self.mint_reconnect(now);
        self.pending
            .push(SessionEvent::ReconnectTicketIssued { ticket });
        Ok(())
    }

    /// An application datagram arrived (already decrypted).
    ///
    /// Updates the acknowledgement window, treats a repeat as a duplicate, and moves
    /// [`SessionState::Authenticated`] to [`SessionState::Active`] on the first world message — the
    /// only signal that the client got far enough to enter the world.
    ///
    /// # Errors
    /// [`SessionError::NotAuthenticated`] before a registration is accepted, and
    /// [`SessionError::Closed`] afterwards.
    pub fn on_datagram(
        &mut self,
        sequence: u16,
        now: Instant,
    ) -> Result<Vec<SessionEvent>, SessionError> {
        match self.state {
            SessionState::Transport => return Err(SessionError::NotAuthenticated(self.peer)),
            SessionState::Closed => return Err(SessionError::Closed(self.peer)),
            SessionState::Authenticated | SessionState::Active | SessionState::Draining => {}
        }
        self.last_inbound = now;

        if self.ack.is_duplicate(sequence) {
            // A duplicate still proves the peer is alive, which `last_inbound` recorded, and it is
            // already inside the acknowledged range, so it changes nothing else.
            return Ok(Vec::new());
        }

        let mut events = Vec::new();
        if self.state == SessionState::Authenticated {
            self.state = SessionState::Active;
            events.push(SessionEvent::Activated);
        }
        Ok(events)
    }

    /// Queue a reliable outbound record; it stays in the resend table until acknowledged.
    ///
    /// The record counts as transmitted when queued: the caller writes it as it calls this, and the
    /// interval before the first resend is measured from `now`.
    ///
    /// # Errors
    /// [`SessionError::NotAuthenticated`] before the registration is accepted — nothing may be
    /// retransmitted to a peer that has not proven its identity — [`SessionError::Closed`], or
    /// [`SessionError::SequenceAlreadyQueued`].
    pub fn send_reliable(
        &mut self,
        sequence: u16,
        bytes: Vec<u8>,
        now: Instant,
    ) -> Result<(), SessionError> {
        match self.state {
            SessionState::Transport => return Err(SessionError::NotAuthenticated(self.peer)),
            SessionState::Closed => return Err(SessionError::Closed(self.peer)),
            SessionState::Authenticated | SessionState::Active | SessionState::Draining => {}
        }
        if self.resend.contains(sequence) {
            return Err(SessionError::SequenceAlreadyQueued { sequence });
        }
        self.resend.queue(sequence, bytes, now);
        Ok(())
    }

    /// Acknowledge an outbound reliable sequence: the peer reported it delivered.
    ///
    /// Acks arrive as a range in `CT_ACKS`, so the caller walks the range and calls this per sequence.
    /// Acknowledging something already gone is a no-op: a duplicate ACK is normal, not an error.
    pub fn acknowledge(&mut self, sequence: u16) {
        self.resend.acknowledge(sequence);
    }

    /// Mark the session draining: no new spawns, the existing player finishes.
    ///
    /// A session that has not authenticated has nothing to drain, and one that is already draining or
    /// closed keeps its original deadline — re-draining must not extend a shutdown.
    pub fn drain(&mut self, now: Instant) {
        if !matches!(self.state, SessionState::Authenticated | SessionState::Active) {
            return;
        }
        self.state = SessionState::Draining;
        self.drain_deadline = Some(now + self.config.drain_grace);
    }

    /// Close the session for a reason the caller observed, such as the transport reporting the peer
    /// gone or the peer breaking the protocol.
    ///
    /// Idempotent: a closed session reports nothing further.
    #[must_use]
    pub fn close(&mut self, reason: CloseReason) -> Vec<SessionEvent> {
        if !self.state.is_open() {
            return Vec::new();
        }
        vec![self.close_with(reason)]
    }

    /// Drive time forward. Returns events the caller must act on.
    ///
    /// The order is deliberate: an event queued by [`Session::register`], then whichever state
    /// deadline applies, then retransmissions. A deadline that fires closes the session and ends the
    /// call, so nothing is staged for a session that just died.
    ///
    /// Any sequence returned in [`SessionEvent::Retransmit`] has been charged as sent at `now`.
    #[must_use]
    pub fn advance(&mut self, now: Instant) -> Vec<SessionEvent> {
        let mut events = std::mem::take(&mut self.pending);
        if !self.state.is_open() {
            return events;
        }

        if self.state == SessionState::Transport && now >= self.auth_deadline {
            events.push(SessionEvent::AuthenticationTimedOut);
            events.push(self.close_with(CloseReason::AuthenticationTimeout));
            return events;
        }

        if let Some(deadline) = self.drain_deadline
            && now >= deadline
        {
            events.push(self.close_with(CloseReason::DrainComplete));
            return events;
        }

        let idle = matches!(
            self.state,
            SessionState::Authenticated | SessionState::Active
        ) && now.saturating_duration_since(self.last_inbound) >= self.config.idle_timeout;
        if idle {
            events.push(self.close_with(CloseReason::Idle));
            return events;
        }

        let mut due = Vec::new();
        for sequence in self.resend.due(now) {
            // A refused sequence has spent its resend budget and was dropped. That is the remedy for
            // the 4,229-resend defect, so it is not an error and needs no event.
            if self.resend.mark_sent(sequence, now) {
                due.push(sequence);
            }
        }
        if !due.is_empty() {
            events.push(SessionEvent::Retransmit(due));
        }
        events
    }

    fn mint_reconnect(&mut self, now: Instant) -> ReconnectTicket {
        self.reconnect_generation = self.reconnect_generation.saturating_add(1);
        let base = match &self.binding {
            Some(binding) => binding.ticket_id.clone(),
            None => self.peer.to_string(),
        };
        ReconnectTicket::mint(
            &base,
            self.reconnect_generation,
            self.clock
                .expiry_after(now, self.config.reconnect_ticket_ttl_secs),
        )
    }

    fn close_with(&mut self, reason: CloseReason) -> SessionEvent {
        self.state = SessionState::Closed;
        // Release the ticket: a closed session must not hold a claim that blocks the next login.
        self.ticket = None;
        SessionEvent::Close(reason)
    }
}
