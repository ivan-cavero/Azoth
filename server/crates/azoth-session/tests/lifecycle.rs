//! The session lifecycle, as integration tests.
//!
//! WHY THESE LIVE HERE AND NOT IN THE MODULE
//! =========================================
//! They exercise only the public API, and the crate's rules are the kind that must be readable
//! without the implementation next to them: a reader checking "does ticket expiry close a live
//! session?" should find one test that answers it. `src/state.rs` also sits close enough to the
//! workspace's 400-line limit that a boundary change, not a bigger limit, would be the fix.
//!
//! WHY THERE IS NO SLEEPING
//! ========================
//! Every deadline is compared against the `now` the test passes in, so the same code path that takes
//! 15 real seconds in production is exercised here in microseconds, with `Instant::now()` plus an
//! offset as the clock. Two of the defects this crate prevents — the ACK range crossing 32,768 after
//! ~26 minutes and a record being resent 4,229 times — were only visible at real play speed, which is
//! exactly why they survived as long as they did.

use std::net::SocketAddr;
use std::time::{Duration, Instant};

use azoth_session::{
    AckWindow, CloseReason, LoginTicket, ReconnectTicket, ResendTable, Session, SessionConfig,
    SessionError, SessionEvent, SessionState,
};
use azoth_wire::v3::{RegistrationRequest, RequestFormat};

const TICKET_ID: &str = "0b5f3f2a-6d1e-4b9c-8f7a-2c3d4e5f6a7b";

fn peer() -> SocketAddr {
    "127.0.0.1:27000".parse().expect("a literal address parses")
}

fn login_ticket(expires_at_unix: i64) -> LoginTicket {
    LoginTicket {
        ticket_id: TICKET_ID.to_string(),
        signature: "queue-handoff-signature".to_string(),
        world_id: "world-1".to_string(),
        character_id: "11111111-2222-4333-8444-555555555555".to_string(),
        persona_id: "persona-1".to_string(),
        rep_address: "127.0.0.1:27000".to_string(),
        expires_at_unix,
    }
}

/// A strict-format V3 body carrying `sig:<ticket_id>` and nothing else. The strict form keeps the
/// character id out of the wire entirely, so the rest of the schedule is irrelevant here.
fn strict_request(ticket_id: &str) -> RegistrationRequest {
    let mut fields: [Vec<u8>; 12] = std::array::from_fn(|_| Vec::new());
    fields[5] = format!("sig:{ticket_id}").into_bytes();
    RegistrationRequest {
        format: RequestFormat::Strict,
        prelude: Vec::new(),
        fields,
        gaps: Vec::new(),
        world_id_region: Vec::new(),
        auth_blob: Vec::new(),
        trailer: Vec::new(),
        retry_records: Vec::new(),
        retry_tail: Vec::new(),
    }
}

/// The retry format, which carries the identity in `session_uuid` instead of the schedule.
fn retry_request(ticket_id: &str, session_uuid: &str) -> RegistrationRequest {
    let mut request = strict_request(ticket_id);
    request.format = RequestFormat::Retry;
    request.fields[7] = session_uuid.as_bytes().to_vec();
    request
}

/// A session with a valid ticket bound, expiring `ttl` seconds after `now`.
fn bound_session(now: Instant, ttl: i64) -> Session {
    let mut session = Session::new_at(peer(), SessionConfig::default(), now);
    let expiry = session.unix_at(now) + ttl;
    session.bind_ticket(login_ticket(expiry)).expect("binds");
    session
}

/// Register, then let the queued reconnect ticket surface, which is what a tick does.
fn activate(session: &mut Session, now: Instant) {
    session
        .register(&strict_request(TICKET_ID), now)
        .expect("a valid ticket authenticates");
    let events = session.advance(now);
    assert!(reconnect_ticket(&events).is_some(), "registers: {events:?}");
}

fn reconnect_ticket(events: &[SessionEvent]) -> Option<&ReconnectTicket> {
    events.iter().find_map(|event| match event {
        SessionEvent::ReconnectTicketIssued { ticket } => Some(ticket),
        _ => None,
    })
}

fn closed_with(events: &[SessionEvent]) -> Option<CloseReason> {
    events.iter().find_map(|event| match event {
        SessionEvent::Close(reason) => Some(*reason),
        _ => None,
    })
}

#[test]
fn one_a_session_that_never_registers_times_out() {
    let t0 = Instant::now();
    let mut session = Session::new_at(peer(), SessionConfig::default(), t0);
    assert!(session.advance(t0 + Duration::from_millis(14_900)).is_empty());
    assert_eq!(session.state(), SessionState::Transport);

    let events = session.advance(t0 + Duration::from_millis(15_000));
    assert!(
        events.contains(&SessionEvent::AuthenticationTimedOut),
        "the deadline reports itself: {events:?}"
    );
    assert_eq!(
        closed_with(&events),
        Some(CloseReason::AuthenticationTimeout),
        "the deadline also closes the session: {events:?}"
    );
    assert_eq!(session.state(), SessionState::Closed);
    // A closed session reports nothing further, however often it is advanced.
    assert!(session.advance(t0 + Duration::from_secs(600)).is_empty());
}

#[test]
fn two_registering_authenticates_and_issues_a_reconnect_ticket() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, 60);

    session
        .register(&strict_request(TICKET_ID), t0)
        .expect("a valid ticket authenticates");
    assert_eq!(session.state(), SessionState::Authenticated);
    assert_eq!(session.character_id(), Some("11111111-2222-4333-8444-555555555555"));
    assert_eq!(session.world_id(), Some("world-1"));
    assert_eq!(session.consumed_ticket_id(), Some(TICKET_ID));

    let events = session.advance(t0);
    let ticket = reconnect_ticket(&events).expect("a reconnect ticket is issued");
    assert_eq!(ticket.generation, 1);
    assert_eq!(
        ticket.expires_at_unix,
        session.unix_at(t0) + 300,
        "the reconnect ticket has its own expiry, not the login one"
    );
    assert!(ticket.ticket_id.starts_with(TICKET_ID));
    // It is issued once, not on every tick.
    assert!(reconnect_ticket(&session.advance(t0 + Duration::from_secs(1))).is_none());
}

#[test]
fn three_an_expired_ticket_is_refused_and_the_session_stays_in_transport() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, -1);

    let err = session
        .register(&strict_request(TICKET_ID), t0)
        .expect_err("an expired ticket must not authenticate");
    assert!(matches!(err, SessionError::TicketExpired { .. }), "{err}");
    assert_eq!(session.state(), SessionState::Transport);
    // The deadline is still the transport deadline: the session has not been closed by the refusal.
    assert!(session.advance(t0 + Duration::from_secs(1)).is_empty());
    assert_eq!(session.state(), SessionState::Transport);
}

#[test]
fn four_a_second_registration_with_the_same_ticket_is_refused() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, 60);
    let request = strict_request(TICKET_ID);

    session.register(&request, t0).expect("first registration");
    let err = session
        .register(&request, t0 + Duration::from_secs(1))
        .expect_err("the ticket is consumed exactly once: two clients must not be one player");
    assert!(matches!(err, SessionError::TicketConsumed { .. }), "{err}");
    assert_eq!(session.state(), SessionState::Authenticated);
}

#[test]
fn five_ticket_expiry_after_authentication_does_not_close_the_session() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, 2);
    session
        .register(&strict_request(TICKET_ID), t0)
        .expect("registers before the ticket expires");

    let later = t0 + Duration::from_secs(10);
    assert!(
        session.unix_at(later) >= session.unix_at(t0) + 2,
        "the login ticket has expired at `later`"
    );

    let events = session.advance(later);
    assert!(
        closed_with(&events).is_none(),
        "a login expiry is not a session deadline: {events:?}"
    );
    assert_eq!(session.state(), SessionState::Authenticated);
    assert!(session.state().is_open());
}

#[test]
fn six_the_ack_window_slides() {
    let mut window = AckWindow::new(16_384);
    for sequence in 0..40_000u16 {
        window.observe(sequence);
    }

    let (first, last) = window.range();
    let width = u32::from(last.wrapping_sub(first).wrapping_add(1));
    assert_eq!(last, 39_999, "the range ends at the highest observed sequence");
    assert_eq!(first, 23_616, "the range starts where the window now begins");
    assert!(width <= 16_384, "the reported width is {width}");
    assert_eq!(width, 16_384, "the window is full, and no wider");
    // 40,000 observations is well past the 32,768 where a pinned range made the client retransmit
    // every reliable record ~200 times.
    assert_eq!(window.width(), 16_384);
}

#[test]
fn seven_a_duplicate_is_reported_and_does_not_advance_the_window() {
    let mut window = AckWindow::new(16_384);
    window.observe(10);
    window.observe(11);
    let before = window.range();

    assert!(window.is_duplicate(11), "11 was already observed");
    assert_eq!(window.range(), before, "a duplicate does not move the range");

    assert!(!window.is_duplicate(12), "12 is new");
    assert_eq!(window.range(), (10, 12), "a new sequence extends the range");
}

#[test]
fn eight_a_reliable_record_redelivers_and_then_is_dropped() {
    let t0 = Instant::now();
    let mut table = ResendTable::default();
    table.queue(7, vec![0xAA, 0xBB], t0);

    assert!(table.due(t0).is_empty(), "not due before the interval");
    assert_eq!(table.due(t0 + Duration::from_millis(300)), vec![7]);

    let mut now = t0;
    for attempt in 1..=6 {
        now += Duration::from_millis(300);
        assert!(table.mark_sent(7, now), "resend {attempt} is allowed");
    }
    assert_eq!(table.tries(7), Some(6));

    // The seventh attempt is refused and the record is dropped rather than re-bombed.
    assert!(!table.mark_sent(7, now + Duration::from_millis(300)));
    assert!(table.payload(7).is_none(), "the record is gone");
    assert!(table.is_empty());
    assert!(table.due(now + Duration::from_secs(60)).is_empty());
}

#[test]
fn nine_a_skipped_resend_does_not_spend_a_try() {
    let t0 = Instant::now();
    let mut table = ResendTable::default();
    table.queue(9, vec![0x01], t0);

    assert!(table.due(t0 + Duration::from_millis(100)).is_empty());
    assert!(table.due(t0 + Duration::from_millis(299)).is_empty());
    assert_eq!(
        table.tries(9),
        Some(0),
        "a sequence the client was never offered again must not lose a try"
    );
}

#[test]
fn ten_the_first_world_datagram_activates_the_session() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, 60);
    session
        .register(&strict_request(TICKET_ID), t0)
        .expect("registers");

    let events = session
        .on_datagram(0, t0 + Duration::from_millis(50))
        .expect("the first datagram is accepted");
    assert_eq!(events, vec![SessionEvent::Activated]);
    assert_eq!(session.state(), SessionState::Active);
    assert_eq!(session.ack_range(), (0, 0));

    // A second datagram is just traffic; only the first activation is reported.
    let events = session.on_datagram(1, t0 + Duration::from_millis(60)).expect("accepted");
    assert!(events.is_empty());
    assert_eq!(session.ack_range(), (0, 1));
}

#[test]
fn a_datagram_before_registration_is_refused() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, 60);
    let err = session
        .on_datagram(0, t0)
        .expect_err("nothing may enter before the ticket validates");
    assert!(matches!(err, SessionError::NotAuthenticated(_)), "{err}");
    assert_eq!(session.state(), SessionState::Transport);
}

#[test]
fn the_retry_format_must_carry_the_ticket_id() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, 60);

    let err = session
        .register(&retry_request(TICKET_ID, "9e8d7c6b-0000-4000-8000-000000000000"), t0)
        .expect_err("the retry body names another identity");
    assert!(matches!(err, SessionError::SessionUuidMismatch { .. }), "{err}");
    assert_eq!(session.state(), SessionState::Transport);

    session
        .register(&retry_request(TICKET_ID, TICKET_ID), t0)
        .expect("the retry body that carries the ticket id authenticates");
    assert_eq!(session.state(), SessionState::Authenticated);
}

#[test]
fn a_body_naming_another_ticket_is_refused() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, 60);
    let err = session
        .register(&strict_request("ffffffff-1111-4222-8333-444444444444"), t0)
        .expect_err("the signature names another ticket");
    assert!(matches!(err, SessionError::TicketMismatch { .. }), "{err}");
    assert_eq!(session.state(), SessionState::Transport);
}

#[test]
fn an_acknowledged_record_stops_being_retransmitted() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, 60);
    activate(&mut session, t0);
    session.send_reliable(4, vec![0x10], t0).expect("queues");
    assert_eq!(session.outstanding(), 1);

    let events = session.advance(t0 + Duration::from_millis(300));
    assert_eq!(events, vec![SessionEvent::Retransmit(vec![4])]);

    session.acknowledge(4);
    assert_eq!(session.outstanding(), 0);
    let events = session.advance(t0 + Duration::from_millis(600));
    assert!(events.is_empty(), "nothing is owed after the ack: {events:?}");
}

#[test]
fn a_draining_session_closes_after_its_grace() {
    let t0 = Instant::now();
    let mut session = bound_session(t0, 60);
    activate(&mut session, t0);

    session.drain(t0);
    assert_eq!(session.state(), SessionState::Draining);
    // Re-draining must not extend the deadline.
    session.drain(t0 + Duration::from_secs(5));

    assert!(session.advance(t0 + Duration::from_secs(29)).is_empty());
    let events = session.advance(t0 + Duration::from_secs(30));
    assert_eq!(closed_with(&events), Some(CloseReason::DrainComplete));
    assert_eq!(session.state(), SessionState::Closed);
}

#[test]
fn the_ack_window_survives_a_sequence_wrap() {
    let mut window = AckWindow::new(16_384);
    for sequence in 65_530u16..=65_535 {
        window.observe(sequence);
    }
    for sequence in 0u16..=5 {
        window.observe(sequence);
    }
    let (first, last) = window.range();
    assert_eq!(last, 5);
    assert_eq!(first, 65_530);
    assert_eq!(last.wrapping_sub(first).wrapping_add(1), 12);
}
