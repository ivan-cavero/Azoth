//! Per-connection session state held by [`crate::entry::WorldEntry`].

use std::collections::{HashMap, VecDeque};
use std::net::SocketAddr;

use azoth_model::ActorGuid;
use azoth_session::Session;
use azoth_wire::carrier::Reassembly;

use crate::entry::egress::PeerView;
use crate::ladder::{Ladder, Outgoing};

#[derive(Debug)]
pub(crate) struct Peer {
    pub(crate) session: Session,
    pub(crate) ladder: Option<Ladder>,
    /// Bytes queued under each reliable sequence for retransmission.
    pub(crate) outbox: HashMap<u16, Vec<u8>>,
    pub(crate) inbound: Reassembly,
    /// Inbound datagram count and last envelope sequence (ACK range).
    pub(crate) inbound_datagrams: u32,
    pub(crate) last_inbound_seq: u16,
    /// Outbound envelope counter shared by ladder rungs and keepalives.
    pub(crate) outbound_sequence: u16,
    /// Local player's actor guid (from spawn template); used for AOI AddActor.
    pub(crate) actor_guid: ActorGuid,
    /// Whether AOI presence fanout has run after the entry ladder completed.
    pub(crate) presence_announced: bool,
    /// Composed presence datagrams waiting for the output clock (one per tick).
    pub(crate) presence_out: VecDeque<Outgoing>,
}

impl Peer {
    /// Open session, empty queues, no datagrams counted yet.
    pub(crate) fn new(session: Session, actor_guid: ActorGuid) -> Self {
        Self {
            session,
            ladder: None,
            outbox: HashMap::new(),
            inbound: Reassembly::default(),
            inbound_datagrams: 0,
            last_inbound_seq: 0,
            outbound_sequence: 0,
            actor_guid,
            presence_announced: false,
            presence_out: VecDeque::new(),
        }
    }

    /// Borrow as the egress view of this peer.
    pub(crate) fn view(&mut self, peer: SocketAddr) -> PeerView<'_> {
        PeerView {
            peer,
            session: &mut self.session,
            ladder: self.ladder.as_mut(),
            outbox: &mut self.outbox,
            datagrams_seen: self.inbound_datagrams,
            ack_last: self.last_inbound_seq,
            outbound_sequence: &mut self.outbound_sequence,
            presence_out: &mut self.presence_out,
        }
    }
}
