//! The 50 Hz tick: the world's own clock.
//!
//! WHY THE TICK IS A SEPARATE THREAD FROM THE SOCKET
//! ================================================
//! The two have different, incompatible timing needs. The socket must block — a handshake is
//! expensive crypto and pretending otherwise stalls whatever is waiting on it. The tick must never
//! block — it has a 20 ms budget and overrunning it makes updates bunch up and players see
//! rubber-banding. Putting them on one thread means one waits for the other; the measured cost is a
//! tick that tracks the client's traffic instead of its own clock, which is exactly the defect the
//! prototype documents (`Pearson(inbound datagrams, server replies) = 0.995`).
//!
//! WHY A FIXED TIMESTEP WITH AN ACCUMULATOR
//! ========================================
//! The simulation advances in ticks, not in wall-clock time. A tick that took 24 ms does not get a
//! longer step; the accumulator notices and runs the next tick immediately, and the overrun is
//! counted. That keeps the simulation deterministic and makes "the rate sagged" a number rather than
//! a feeling.
//!
//! WHAT THIS MODULE OWNS
//! ====================
//! The clock, the overrun counter, and the per-peer session map. It does **not** own the socket and
//! does not know what a datagram contains beyond routing it to a session.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::mpsc::{Receiver, SyncSender};
use std::time::{Duration, Instant};

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

/// A rolling window of tick durations.
///
/// A server that cannot state its p99 tick time cannot claim 50 Hz, so the window is part of the
/// clock rather than an afterthought: it reports mean, p50, p99 and the overrun count over the last
/// N ticks.
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
    /// Nearest rank, not linear interpolation: `ceil(p * n) - 1` in the sorted array. The two differ
    /// by one sample, and for a latency budget that one sample is the difference between "p99 is
    /// 9.8 ms" and "p99 is 10.1 ms" — a claim about whether the tick fits. A first version used
    /// `round(p * (n-1))`, which reported 51 µs as the median of 1..=100 µs; the test caught it.
    #[must_use]
    pub fn percentile(&self, p: f64) -> Option<Duration> {
        if self.samples.is_empty() {
            return None;
        }
        let mut sorted = self.samples.clone();
        sorted.sort_unstable();
        let n = sorted.len();
        let rank = (p.clamp(0.0, 1.0) * n as f64).ceil() as usize;
        let index = rank.saturating_sub(1).min(n - 1);
        sorted.get(index).copied()
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
    sessions: HashMap<SocketAddr, PeerState>,
    window: TickWindow,
    overruns: u64,
    ticks: u64,
    started: Instant,
    /// Kept so a test can inspect the sender side without a socket.
    _sender: SyncSender<TickEvent>,
}

/// What the tick knows about one peer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PeerState {
    /// Datagrams received from this peer since it was established.
    pub datagrams: u64,
    /// Bytes received, for the bandwidth budget the plan states.
    pub bytes: u64,
    /// Whether the ladder has been sent to this peer.
    pub greeted: bool,
}

impl Tick {
    /// Build a tick loop at `tick_hz`.
    #[must_use]
    pub fn new(tick_hz: f64, sender: SyncSender<TickEvent>) -> Self {
        let (_, receiver) = std::sync::mpsc::sync_channel(1);
        Self::with_channel(
            Duration::from_secs_f64(1.0 / tick_hz),
            receiver,
            sender,
        )
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
            sessions: HashMap::new(),
            window: TickWindow::new(600), // 12 s at 50 Hz
            overruns: 0,
            ticks: 0,
            started: Instant::now(),
            _sender: sender,
        }
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

    /// The peers the tick is tracking.
    #[must_use]
    pub fn sessions(&self) -> &HashMap<SocketAddr, PeerState> {
        &self.sessions
    }

    /// Drain the network events and fold them into per-peer state.
    ///
    /// Non-blocking: `try_recv` until empty. This is what keeps the tick from waiting on the socket.
    pub fn drain_events(&mut self) {
        while let Ok(event) = self.events.try_recv() {
            match event {
                TickEvent::Established(peer) => {
                    self.sessions.entry(peer).or_insert(PeerState {
                        datagrams: 0,
                        bytes: 0,
                        greeted: false,
                    });
                }
                TickEvent::Data { peer, bytes } => {
                    let state = self.sessions.entry(peer).or_insert(PeerState {
                        datagrams: 0,
                        bytes: 0,
                        greeted: false,
                    });
                    state.datagrams += 1;
                    state.bytes += bytes.len() as u64;
                }
                TickEvent::Dropped(peer) => {
                    self.sessions.remove(&peer);
                }
            }
        }
    }

    /// Run one tick and record how long it took.
    ///
    /// Returns the duration, so a caller can assert on it without reaching into the window.
    pub fn step(&mut self) -> Duration {
        let began = Instant::now();
        self.drain_events();
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
    /// The accumulator is what makes the rate independent of how long a tick actually took: a slow
    /// tick leaves debt that the next iteration pays immediately, and the debt is visible in
    /// [`Self::overruns`] rather than silently absorbed.
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

    /// Seconds since the tick loop started.
    #[must_use]
    pub fn uptime(&self) -> Duration {
        self.started.elapsed()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn peer(port: u16) -> SocketAddr {
        format!("127.0.0.1:{port}").parse().expect("addr")
    }

    fn channel() -> (SyncSender<TickEvent>, Receiver<TickEvent>) {
        std::sync::mpsc::sync_channel(64)
    }

    #[test]
    fn a_fifty_hertz_tick_is_twenty_milliseconds() {
        let (tx, _rx) = channel();
        let tick = Tick::new(50.0, tx);
        assert_eq!(tick.interval(), Duration::from_millis(20));
    }

    #[test]
    fn an_established_peer_is_tracked() {
        let (tx, rx) = channel();
        let mut tick = Tick::with_channel(Duration::from_millis(20), rx, tx.clone());
        tx.send(TickEvent::Established(peer(1000))).expect("send");
        tick.step();
        assert!(tick.sessions().contains_key(&peer(1000)));
    }

    #[test]
    fn data_counts_datagrams_and_bytes() {
        let (tx, rx) = channel();
        let mut tick = Tick::with_channel(Duration::from_millis(20), rx, tx.clone());
        tx.send(TickEvent::Established(peer(1001))).expect("send");
        tx.send(TickEvent::Data {
            peer: peer(1001),
            bytes: vec![0; 100],
        })
        .expect("send");
        tick.step();
        let state = tick.sessions().get(&peer(1001)).expect("tracked");
        assert_eq!(state.datagrams, 1);
        assert_eq!(state.bytes, 100);
    }

    #[test]
    fn a_dropped_peer_is_forgotten() {
        let (tx, rx) = channel();
        let mut tick = Tick::with_channel(Duration::from_millis(20), rx, tx.clone());
        tx.send(TickEvent::Established(peer(1002))).expect("send");
        tick.step();
        tx.send(TickEvent::Dropped(peer(1002))).expect("send");
        tick.step();
        assert!(!tick.sessions().contains_key(&peer(1002)));
    }

    /// The tick must never wait for the socket: draining is non-blocking.
    #[test]
    fn draining_does_not_block_on_an_empty_channel() {
        let (tx, rx) = channel();
        let mut tick = Tick::with_channel(Duration::from_millis(20), rx, tx);
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

    #[test]
    fn an_overrun_is_counted_when_a_tick_exceeds_its_budget() {
        // The budget has to be smaller than the work for this to be a real measurement. A first
        // version slept BEFORE calling step(), so the sleep was never inside the timed region and
        // the test asserted a sleep it had not measured. A one-nanosecond budget makes any tick an
        // overrun without depending on a sleep.
        let (tx, rx) = channel();
        let mut tick = Tick::with_channel(Duration::from_nanos(1), rx, tx);
        tick.step();
        assert_eq!(tick.overruns(), 1, "any tick exceeds a 1 ns budget");
    }
}
