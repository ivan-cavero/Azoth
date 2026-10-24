//! The 50 Hz tick: the world's own clock, and the only thread that decides what to send.
//!
//! WHY THE TICK IS A SEPARATE THREAD FROM THE SOCKET
//! ================================================
//! The socket must block — a handshake is expensive crypto and pretending otherwise stalls whatever
//! waits on it. The tick must never block — it has a 20 ms budget and overrunning it makes updates
//! bunch up and players see rubber-banding. On one thread one waits for the other, and the measured
//! cost is a tick that tracks the client's traffic instead of its own clock: the prototype's
//! `Pearson(inbound datagrams, server replies) = 0.995`.
//!
//! WHAT THIS MODULE OWNS
//! ====================
//! The clock, the overrun counter, and **the peer state** — since this phase, the [`WorldEntry`]
//! itself: two peer tables would be two answers to "is this peer registered", so the entry is the
//! only one. The tick does not own the socket; it hands the datagrams it decides on to a writer
//! channel, and one it cannot hand over is **dropped** rather than queued (see [`Tick::deliver`]).

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::mpsc::{Receiver, SyncSender};
use std::time::{Duration, Instant};

use crate::entry::{EntryOutcome, Outbound, WorldEntry};

/// What the network thread tells the tick.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TickEvent {
    /// A peer's DTLS handshake completed.
    Established(SocketAddr),
    /// Decrypted application data from a peer.
    Data {
        /// Who sent it.
        peer: SocketAddr,
        /// The plaintext of one record.
        bytes: Vec<u8>,
    },
    /// A peer went away: handshake timeout, protocol rejection, or a fresh handshake replaced it.
    Dropped(SocketAddr),
}

/// A rolling window of tick durations: mean, p50 and p99 over the last N ticks.
///
/// A server that cannot state its p99 tick time cannot claim 50 Hz, so the window is part of the
/// clock rather than a reporting afterthought.
#[derive(Debug, Clone)]
pub struct TickWindow {
    samples: Vec<Duration>,
    capacity: usize,
    next: usize,
}

impl TickWindow {
    /// A window over the last `capacity` ticks.
    #[must_use]
    pub fn new(capacity: usize) -> Self {
        Self {
            samples: Vec::with_capacity(capacity.max(1)),
            capacity: capacity.max(1),
            next: 0,
        }
    }

    /// Record one tick's duration.
    pub fn record(&mut self, duration: Duration) {
        if self.samples.len() < self.capacity {
            self.samples.push(duration);
        } else {
            self.samples[self.next] = duration;
            self.next = (self.next + 1) % self.capacity;
        }
    }

    /// How many ticks are in the window.
    #[must_use]
    pub fn len(&self) -> usize {
        self.samples.len()
    }

    /// Whether the window has no samples yet.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.samples.is_empty()
    }

    /// A percentile of the window, by nearest rank. `p` is in `0.0..=1.0`.
    ///
    /// Nearest rank (`ceil(p * n) - 1`), not linear interpolation: the two differ by one sample, and
    /// for a latency budget that sample is the difference between "p99 is 9.8 ms" and "10.1 ms".
    /// A first version used `round(p * (n-1))`, which reported 51 µs as the median of 1..=100 µs.
    #[must_use]
    pub fn percentile(&self, p: f64) -> Option<Duration> {
        if self.samples.is_empty() {
            return None;
        }
        let mut sorted = self.samples.clone();
        sorted.sort_unstable();
        let n = sorted.len();
        let rank = (p.clamp(0.0, 1.0) * n as f64).ceil() as usize;
        sorted.get(rank.saturating_sub(1).min(n - 1)).copied()
    }

    /// The mean of the window.
    #[must_use]
    pub fn mean(&self) -> Option<Duration> {
        if self.samples.is_empty() {
            return None;
        }
        let total: Duration = self.samples.iter().sum();
        Some(total / self.samples.len() as u32)
    }
}

/// The tick loop's state.
pub struct Tick {
    interval: Duration,
    events: Receiver<TickEvent>,
    /// The peers, their sessions and their ladders; `None` until a caller attaches one, which is
    /// what lets the clock be tested without a world.
    entry: Option<WorldEntry>,
    /// The ticket file to re-read each tick, so a login after startup can still register.
    ticket_path: Option<PathBuf>,
    /// Where decided datagrams go. `None` in a test that only inspects the clock.
    writer: Option<SyncSender<Outbound>>,
    window: TickWindow,
    overruns: u64,
    ticks: u64,
    started: Instant,
    /// Kept so a test can inspect the sender side without a socket.
    _sender: SyncSender<TickEvent>,
}

impl Tick {
    /// Build a tick loop at `tick_hz` over the channel the network thread feeds.
    #[must_use]
    pub fn new(tick_hz: f64, events: Receiver<TickEvent>, sender: SyncSender<TickEvent>) -> Self {
        Self::with_channel(Duration::from_secs_f64(1.0 / tick_hz), events, sender)
    }

    /// Build a tick loop over an existing channel, which is what a test drives.
    #[must_use]
    pub fn with_channel(
        interval: Duration,
        events: Receiver<TickEvent>,
        sender: SyncSender<TickEvent>,
    ) -> Self {
        Self {
            interval,
            events,
            entry: None,
            ticket_path: None,
            writer: None,
            window: TickWindow::new(600), // 12 s at 50 Hz
            overruns: 0,
            ticks: 0,
            started: Instant::now(),
            _sender: sender,
        }
    }

    /// Give the tick the world's peer state and somewhere to send what it decides.
    pub fn attach_entry(&mut self, entry: WorldEntry, writer: SyncSender<Outbound>) {
        self.entry = Some(entry);
        self.writer = Some(writer);
    }

    /// Re-read this ticket file each tick, so a ticket minted after startup still registers.
    pub fn attach_ticket_file(&mut self, path: PathBuf) {
        self.ticket_path = Some(path);
    }

    /// The entry the tick is driving, for logs and tests.
    #[must_use]
    pub fn entry(&self) -> Option<&WorldEntry> {
        self.entry.as_ref()
    }

    /// The tick interval.
    #[must_use]
    pub fn interval(&self) -> Duration {
        self.interval
    }

    /// Ticks completed since start.
    #[must_use]
    pub fn ticks(&self) -> u64 {
        self.ticks
    }

    /// Ticks that ran past their budget.
    #[must_use]
    pub fn overruns(&self) -> u64 {
        self.overruns
    }

    /// The tick-duration window, for reporting.
    #[must_use]
    pub fn window(&self) -> &TickWindow {
        &self.window
    }

    /// Seconds since the tick loop started.
    #[must_use]
    pub fn uptime(&self) -> Duration {
        self.started.elapsed()
    }

    /// Drain the network events into the entry, then let it advance.
    /// Non-blocking: `try_recv` until empty, which keeps the tick from waiting on the socket.
    pub fn drain_events(&mut self) {
        while let Ok(event) = self.events.try_recv() {
            let Some(entry) = self.entry.as_mut() else {
                continue;
            };
            let outcome = match event {
                TickEvent::Established(peer) => entry.established(peer),
                TickEvent::Data { peer, bytes } => entry.data(peer, &bytes),
                TickEvent::Dropped(peer) => {
                    entry.dropped(peer);
                    continue;
                }
            };
            self.deliver(outcome);
        }
    }

    /// Hand one outcome to the writer, logging a rejection.
    fn deliver(&mut self, outcome: EntryOutcome) {
        let (outbound, rejected) = outcome.split();
        if let Some((peer, reason)) = rejected {
            eprintln!("[worldd] rejecting {peer}: {reason}");
        }
        let Some(writer) = self.writer.as_ref() else {
            return;
        };
        for datagram in outbound {
            // A full channel drops the datagram: a rung is retransmitted by the session, and a lost
            // Carrier flight is re-answered on the client's retry (`crate::entry`), never blocked.
            let _ = writer.try_send(datagram);
        }
    }

    /// Run one tick and record how long it took, returning the duration so a caller can assert on
    /// it without reaching into the window.
    pub fn step(&mut self) -> Duration {
        let began = Instant::now();
        // A ticket minted after this world started still has to register, so the file is reloaded
        // here: one `metadata` call per tick, and a read only when the region minted something.
        if let (Some(path), Some(entry)) = (self.ticket_path.as_deref(), self.entry.as_mut()) {
            entry.refresh_tickets(path);
        }
        self.drain_events();
        // `tick` serves one peer per call, so it is called until it has nothing left: one tick must
        // reach every peer, or a busy world starves whoever is late in the rotation.
        loop {
            let outcome = match self.entry.as_mut() {
                Some(entry) => entry.tick(),
                None => break,
            };
            if outcome == EntryOutcome::Nothing {
                break;
            }
            self.deliver(outcome);
        }
        self.ticks += 1;
        let elapsed = began.elapsed();
        self.window.record(elapsed);
        if elapsed > self.interval {
            self.overruns += 1;
        }
        elapsed
    }

    /// Run forever at the configured rate, with a time accumulator.
    ///
    /// The simulation advances in ticks, not wall-clock time: a slow tick leaves debt the next
    /// iteration pays immediately, and the debt is visible in [`Self::overruns`] rather than
    /// absorbed, so the rate does not depend on how long a tick took.
    pub fn run(&mut self) -> ! {
        let mut next = Instant::now() + self.interval;
        loop {
            let now = Instant::now();
            if now >= next {
                self.step();
                next += self.interval;
                // If the loop fell more than one interval behind, resynchronise rather than
                // spinning through a backlog of ticks nobody can see.
                if next < Instant::now() {
                    next = Instant::now() + self.interval;
                }
            } else {
                std::thread::sleep(next - now);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tickets::TicketStore;

    fn peer(port: u16) -> SocketAddr {
        format!("127.0.0.1:{port}").parse().expect("addr")
    }

    fn channel() -> (SyncSender<TickEvent>, Receiver<TickEvent>) {
        std::sync::mpsc::sync_channel(64)
    }

    fn wired(interval: Duration) -> (SyncSender<TickEvent>, Tick, Receiver<Outbound>) {
        let (tx, rx) = channel();
        let mut tick = Tick::with_channel(interval, rx, tx.clone());
        let (writer, outbound) = std::sync::mpsc::sync_channel(64);
        tick.attach_entry(
            WorldEntry::new(TicketStore::empty(), vec![0xAB; 106], vec![0xCD; 64]),
            writer,
        );
        (tx, tick, outbound)
    }

    #[test]
    fn a_fifty_hertz_tick_is_twenty_milliseconds() {
        let (tx, rx) = channel();
        let tick = Tick::new(50.0, rx, tx);
        assert_eq!(tick.interval(), Duration::from_millis(20));
    }

    /// The events the network thread sends must reach the entry: the tick used to build a receiver
    /// nobody could write to, so every event was silently discarded.
    #[test]
    fn an_established_event_reaches_the_entry() {
        let (tx, mut tick, _outbound) = wired(Duration::from_millis(20));
        tx.send(TickEvent::Established(peer(1000))).expect("send");
        tick.step();
        let state = tick.entry().and_then(|entry| entry.session_state(peer(1000)));
        assert_eq!(state, Some(azoth_session::SessionState::Transport));
    }

    #[test]
    fn draining_does_not_block_on_an_empty_channel() {
        let (_, mut tick, _outbound) = wired(Duration::from_millis(20));
        let began = Instant::now();
        for _ in 0..100 {
            tick.step();
        }
        assert!(
            began.elapsed() < Duration::from_secs(2),
            "100 empty ticks must not block"
        );
    }

    #[test]
    fn an_overrun_is_counted_when_a_tick_exceeds_its_budget() {
        // A one-nanosecond budget makes any tick an overrun without depending on a sleep.
        let (_, mut tick, _outbound) = wired(Duration::from_nanos(1));
        tick.step();
        assert_eq!(tick.overruns(), 1, "any tick exceeds a 1 ns budget");
    }

    #[test]
    fn the_window_reports_a_percentile() {
        let mut window = TickWindow::new(100);
        for i in 1..=100u64 {
            window.record(Duration::from_micros(i));
        }
        assert_eq!(window.len(), 100);
        // 100 samples of 1..=100 µs: the 50th value is 50 µs by nearest rank.
        assert_eq!(window.percentile(0.5), Some(Duration::from_micros(50)));
        assert_eq!(window.percentile(1.0), Some(Duration::from_micros(100)));
        assert_eq!(window.percentile(0.0), Some(Duration::from_micros(1)));
    }

    #[test]
    fn the_window_keeps_only_its_capacity() {
        let mut window = TickWindow::new(10);
        for i in 0..50u64 {
            window.record(Duration::from_micros(i));
        }
        assert_eq!(window.len(), 10, "a rolling window, not a growing one");
        // The window holds the LAST ten: 40..49 microseconds.
        assert_eq!(window.percentile(1.0), Some(Duration::from_micros(49)));
    }

    #[test]
    fn an_empty_window_reports_nothing_rather_than_zero() {
        // Zero would be indistinguishable from "every tick was instant".
        let window = TickWindow::new(10);
        assert_eq!(window.percentile(0.5), None);
        assert_eq!(window.mean(), None);
    }

    #[test]
    fn the_mean_is_the_mean() {
        let mut window = TickWindow::new(10);
        window.record(Duration::from_millis(10));
        window.record(Duration::from_millis(20));
        assert_eq!(window.mean(), Some(Duration::from_millis(15)));
    }
}
