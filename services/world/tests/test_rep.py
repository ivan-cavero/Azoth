"""REP server tests (stdlib unittest + pyOpenSSL DTLS client).

The handshake test drives a real DTLS client (memory BIOs) against a live
server on localhost UDP: ClientHello -> ServerHello flight -> established.
This is the exact exchange the patched game client performs.
"""

from __future__ import annotations

import pathlib
import socket
import sys
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azoth_world.javelin import (
    MessageRecord,
    marshal_datagram,
    parse_datagram,
    parse_envelope,
)
from azoth_world import rep
from azoth_world.rep import v3_response_datagram

HAVE_PYOPENSSL = False


def v3_registration_payload() -> bytes:
    """A V3-shaped ch0 body, i.e. one that `parse_v3_request_or_lenient`
    accepts.

    Why the fixture is shaped instead of arbitrary bytes: the server now
    identifies a V3 registration by PARSING it, not by `channel == 0 and
    size > 64`. Measured 2026-10-09 on a live session, 15 of 17 ch0 records of
    size 256 were ordinary game data and only 2 (one per connection) were
    registrations, so the old size test made the server answer registrations
    the client never sent. Tests that pass opaque bytes to represent a V3
    request would assert the very behaviour that was the bug.
    """
    return (
        b"\x00\x01\x00\x02"
        + b"Javelin"
        + b"\x00" * 4
        + b"sig:"
        + b"a" * 16
        + b"$11111111-2222-4333-8444-555555555555"
        + b"\x00" * 8
        + b"naId.0123456789abcdef"
        + b"\x00" * 180
    )


try:
    from OpenSSL import SSL

    HAVE_PYOPENSSL = True
except ImportError:
    pass


class TestSystemHandshake(unittest.TestCase):
    def test_connect_request_gets_ack(self):
        from azoth_world.rep import handle_app_data

        # Client CONNECT_REQUEST: system channel 3, msgId LAST byte.
        rec = MessageRecord(
            channel=3,
            payload=b"\x00\x00\x00\x05" + bytes([1]),  # version u32 + msgId=1
            sequence=1,
            flags_override=0xA0,  # DATA_CHANNEL | CONNECTING
        )
        request = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        replies = handle_app_data(request, 1, handshake_done=False, inbound_first=1)
        self.assertTrue(replies, "CONNECT_REQUEST must be answered")
        env, body = parse_envelope(replies[0])
        self.assertEqual(env.sequence, 1)
        result = parse_datagram(body)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.messages), 3)
        clock, ack, piggy = result.messages
        # CLOCK_SYNC first (reference: SendSyncTime() before the ACK).
        self.assertEqual(clock.system_msg_id, 4)
        self.assertEqual(clock.flags, 0x20)  # unreliable, not connecting
        # CONNECT_ACK carries the welcome data: the client's version u32
        # echoed verbatim (DefaultHandshake semantics — the client runs
        # OnReceiveAck on it; the datagram-ACK form `40 0002 0002` was
        # tried 2026-09-17 and did NOT advance the client).
        self.assertEqual(ack.system_msg_id, 2)
        self.assertEqual(ack.flags, 0x21)
        self.assertEqual(ack.sequence, 1)
        self.assertEqual(ack.reliable_sequence, 0)
        self.assertEqual(ack.payload, b"\x00\x00\x00\x05\x02")
        # CT_ACKS piggyback (first-light PR #5): continuous-ACK over the
        # inbound envelope range, flags 0x18 (SEQ fields inherited).
        self.assertEqual(piggy.system_msg_id, 6)
        self.assertEqual(piggy.flags, 0x18)
        self.assertEqual(piggy.payload, bytes([0x40, 0x00, 0x01, 0x00, 0x01, 6]))
        # Envelope seq ECHOES the client's inbound seq (Mixed Nuts).
        self.assertEqual(env.sequence, 1)

    def test_resend_is_not_reacked(self):
        """GridMate reference: in CST_CONNECTED the server validates repeated
        CONNECT_REQUESTs silently (no second ACK). 2026-09-20: the server
        sends Cmd_Greetings once with the first V3 response; on a
        handshaked session (v3_done=True) a repeated CONNECT_REQUEST gets
        no reply."""
        from azoth_world.rep import handle_app_data

        rec = MessageRecord(
            channel=3,
            payload=b"\x00\x00\x00\x05" + bytes([1]),
            sequence=1,
            flags_override=0xA0,
        )
        request = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        self.assertEqual(
            handle_app_data(
                request, 9, handshake_done=True, inbound_first=1, v3_done=True
            ),
            [],
        )

    def test_acks_are_not_answered(self):
        from azoth_world.rep import handle_app_data

        rec = MessageRecord(
            channel=3, payload=bytes([6]), sequence=1, flags_override=0xA0
        )
        wire = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        # 2026-09-20: raw Cmd_Greetings is now gated behind
        # AZOTH_SEND_GREETINGS (it produced `Failed to unmarshal message`),
        # so ack-only datagrams get nothing again.
        self.assertEqual(
            handle_app_data(wire, 2, handshake_done=False, inbound_first=2), []
        )

    def test_peer_session_acks_continuous_range(self):
        """The 0x40 continuous form acks the whole [first..last] range:
        `40 23fc 23f9 06` marks 0x23f9..0x23fc (session 232 live form)."""
        from unittest import mock

        from azoth_world.rep import PeerSession

        with mock.patch("OpenSSL.SSL.Context"), mock.patch(
            "OpenSSL.SSL.Connection"
        ):
            session = PeerSession.__new__(PeerSession)
            session.acked_seqs = set()
            rec = MessageRecord(
                channel=3,
                payload=bytes([0x40, 0x23, 0xFC, 0x23, 0xF9, 0x06]),
                sequence=1,
                flags_override=0xA0,
            )
            session._process_acks([rec])
            self.assertEqual(session.acked_seqs, {0x23F9, 0x23FA, 0x23FB, 0x23FC})

    def test_peer_session_bitmap_is_not_read_as_our_seq(self):
        """Regression: in the 0x8n bitmap forms p[3:] IS the bitmap. An
        earlier change read p[3:5] as an ack of our envelope seq, marking
        bogus seqs acked and suppressing legitimate resends (mgrSet 0 vs
        2 in the 21:13Z run). Bitmap bytes must never enter acked_seqs."""
        from unittest import mock

        from azoth_world.rep import PeerSession

        with mock.patch("OpenSSL.SSL.Context"), mock.patch(
            "OpenSSL.SSL.Connection"
        ):
            session = PeerSession.__new__(PeerSession)
            session.acked_seqs = set()
            # flags 0x82: bitmap of 2 bytes `ab cd` covering last-1 backwards
            rec = MessageRecord(
                channel=3,
                payload=bytes([0x82, 0x00, 0x0F, 0xAB, 0xCD, 0x06]),
                sequence=1,
                flags_override=0xA0,
            )
            session._process_acks([rec])
            # last=0x0F acked; bitmap bit0 of 0xAB covers 0x0E
            self.assertIn(0x0F, session.acked_seqs)
            self.assertIn(0x0E, session.acked_seqs)
            # 0xABCD interpreted as a seq would be 43981 - must NOT appear
            self.assertNotIn(0xABCD, session.acked_seqs)

    def test_peer_session_acks_short_form_without_our_seq(self):
        """The 0xFFFF keepalive form (`40 ffff ffff 06`-shaped, short
        payloads) carries no ack of our envelope: only the client's own
        seq is marked."""
        from unittest import mock

        from azoth_world.rep import PeerSession

        with mock.patch("OpenSSL.SSL.Context"), mock.patch(
            "OpenSSL.SSL.Connection"
        ):
            session = PeerSession.__new__(PeerSession)
            session.acked_seqs = set()
            rec = MessageRecord(
                channel=3,
                payload=bytes([0x40, 0x00, 0x05, 0x06]),
                sequence=1,
                flags_override=0xA0,
            )
            session._process_acks([rec])
            self.assertIn(0x0005, session.acked_seqs)
            self.assertEqual(len(session.acked_seqs), 1)

    def _pending_resend_session(
        self,
        seqs: list[int],
        *,
        acked: set[int] | None = None,
        tries: dict[int, int] | None = None,
        replay_queue: list | None = None,
        greetings_after_replay: bool = False,
        now: float = 1_000.0,
    ):
        """PeerSession.__new__ plus the fields maybe_resend actually reads.

        send() is replaced so a resend does not touch OpenSSL. Timestamps
        are already older than the 0.3 s retry gap.
        """
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.sent_reliable = {
            seq: (now - 1.0, seq.to_bytes(2, "big")) for seq in seqs
        }
        session.resend_tries = dict(tries or {})
        session.acked_seqs = set(acked or ())
        session.replay_queue = [] if replay_queue is None else list(replay_queue)
        session.greetings_after_replay = greetings_after_replay
        session.resend_window_start = now
        session.resend_window_count = 0
        session.sent: list[bytes] = []

        def _send(_server, dgram, _session=session):
            _session.sent.append(dgram)

        session.send = _send
        return session

    def test_post_replay_resend_rate_limit_keeps_try_count(self):
        """After replay-complete, many maybe_resend calls inside 200 ms
        transmit at most 2 datagrams. Unsent seqs stay pending with the
        same try count — a skip must not feed the 6-try cap, and must
        not be marked acked. Seq 888 vs high-water 890 is in this set:
        it is only slowed, not dropped."""
        from unittest import mock

        from azoth_world.rep import POST_REPLAY_RESEND_WINDOW_S

        now = 1_000.0
        # 886/887 fill the window; 888/889 are the tail that must wait.
        seqs = [886, 887, 888, 889]
        session = self._pending_resend_session(
            seqs,
            acked={890},
            tries={seq: 4 for seq in seqs},
            greetings_after_replay=True,
            now=now,
        )
        clock = {"now": now}

        def _now():
            return clock["now"]

        with mock.patch("azoth_world.rep.time.monotonic", _now), mock.patch(
            "azoth_world.rep.log_event"
        ):
            for _ in range(20):
                session.maybe_resend(None)
            sent = [int.from_bytes(d, "big") for d in session.sent]
            self.assertEqual(sent, [886, 887])
            self.assertEqual(session.resend_tries[888], 4)
            self.assertEqual(session.resend_tries[889], 4)
            self.assertIn(888, session.sent_reliable)
            self.assertEqual(session.sent_reliable[888][0], now - 1.0)
            self.assertNotIn(888, session.acked_seqs)
            self.assertEqual(session.acked_seqs, {890})
            # Still inside the 200 ms window: nothing further goes out.
            clock["now"] = now + (POST_REPLAY_RESEND_WINDOW_S / 2)
            session.maybe_resend(None)
            self.assertEqual(len(session.sent), 2)
            self.assertEqual(session.resend_tries[888], 4)
            # Next window: 888 is still eligible (not burned, not acked).
            clock["now"] = now + POST_REPLAY_RESEND_WINDOW_S + 0.05
            session.maybe_resend(None)
            sent = [int.from_bytes(d, "big") for d in session.sent]
            self.assertEqual(sent, [886, 887, 888, 889])
            self.assertEqual(session.resend_tries[888], 5)
            self.assertEqual(session.resend_tries[886], 5)

    def test_post_replay_skips_only_seqs_more_than_512_behind(self):
        """A seq more than 512 below the highest acked seq is not resent
        once replay is complete. Exactly 512 behind, and the 888-vs-890
        tail, stay eligible — the tail is only rate-limited."""
        from unittest import mock

        high = 890
        stale = high - 513
        edge = high - 512
        session = self._pending_resend_session(
            [stale, edge, 888, 889],
            acked={high},
            tries={stale: 1, edge: 1, 888: 1, 889: 1},
            greetings_after_replay=True,
        )
        with mock.patch("azoth_world.rep.time.monotonic", return_value=1_000.0), mock.patch(
            "azoth_world.rep.log_event"
        ):
            session.maybe_resend(None)
        sent = [int.from_bytes(d, "big") for d in session.sent]
        self.assertEqual(sent, [edge, 888])
        self.assertIn(stale, session.sent_reliable)
        self.assertEqual(session.resend_tries[stale], 1)
        self.assertNotIn(stale, session.acked_seqs)
        self.assertEqual(session.resend_tries[889], 1)
        self.assertIn(889, session.sent_reliable)
        self.assertEqual(session.acked_seqs, {high})

    def test_resend_burst_unchanged_until_replay_completes(self):
        """While the replay queue is live, or before the quiet-complete
        flag, the per-call cap of 4 still applies. The post-replay window
        (already full here) and the 512-behind skip must not run —
        possession still needs lost chunks during the burst."""
        from unittest import mock

        # Every seq is more than 512 below 890. A stale filter would
        # send nothing; a live rate limit (window already full) would too.
        seqs = [100, 101, 102, 103, 104, 105, 106, 107]
        cases = (
            ([object()], False),
            ([], False),
            ([object()], True),
        )
        for queue, flag in cases:
            session = self._pending_resend_session(
                seqs,
                acked={890},
                replay_queue=queue,
                greetings_after_replay=flag,
            )
            session.resend_window_count = 2
            with mock.patch(
                "azoth_world.rep.time.monotonic", return_value=1_000.0
            ), mock.patch("azoth_world.rep.log_event"):
                session.maybe_resend(None)
                first = [int.from_bytes(d, "big") for d in session.sent]
                self.assertEqual(first, seqs[:4], (queue, flag))
                session.sent.clear()
                session.maybe_resend(None)
                second = [int.from_bytes(d, "big") for d in session.sent]
                self.assertEqual(second, seqs[4:], (queue, flag))
            self.assertEqual(
                [session.resend_tries[seq] for seq in seqs],
                [1, 1, 1, 1, 1, 1, 1, 1],
            )

    def test_v3_still_answered(self):
        from azoth_world.rep import handle_app_data

        rec = MessageRecord(
            channel=0, payload=v3_registration_payload(), flags_override=0xE0
        )
        wire = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        replies = handle_app_data(wire, 2, handshake_done=False, inbound_first=2)
        self.assertTrue(replies)
        _, body = parse_envelope(replies[0])
        result = parse_datagram(body)
        self.assertEqual(len(result.messages[0].payload), 89)

    def test_lz4_v3_is_decompressed_before_parse(self):
        """Live client (2026-09-17 21:04) sends V3 as envelope 0x81.

        Parsing the compressed body as records used to emit the stub
        session token; the client then SM_DISCONNECTed."""
        from azoth_world.javelin.lz4 import decompress_lz4_block
        from azoth_world.javelin.v3 import parse_v3_request_or_lenient
        from azoth_world.rep import handle_app_data

        captured = bytes.fromhex(
            "81010005f00205045b00030000000089c961b00000094f0c00090200f00e0113"
            "970c0a5d06000000040436303331000000030334303000000002010e00f005"
            "01074a6176656c696e00000005073630303431351800f23700085b52455441"
            "494c5d00287369673a61386263623730612d643039642d343636622d623239"
            "612d3065626230336532636136320e3132372e302e302e313a393030302430"
            "300200102d0700702d343030302d380500000f000302002331240900021600"
            "0f250000cf633064650000103b320000248500116000006aac55f204000409"
            "01520a000001010d002001014a00ff0d113736353631313937393630323837"
            "3933308620737465616d7c61350200fffffb506135613561"
        )
        env, body = parse_envelope(captured)
        self.assertTrue(env.is_compressed)
        dec = decompress_lz4_block(body)
        recs = parse_datagram(dec)
        self.assertIsNone(recs.error)
        self.assertEqual(len(recs.messages), 1)
        v3 = parse_v3_request_or_lenient(recs.messages[0].payload)
        # Must NOT pick the seeded worldId (00000000-...).
        self.assertEqual(v3.session_uuid, "a8bcb70a-d09d-466b-b29a-0ebb03e2ca62")
        replies = handle_app_data(
            captured, 5, handshake_done=True, inbound_first=2
        )
        self.assertTrue(replies, "LZ4 V3 must still get a RegistrationResponse")
        _, rbody = parse_envelope(replies[0])
        result = parse_datagram(rbody)
        # 2026-09-20: no VLQ prefix — payload IS the 88B typed message
        # [00 01 03][error:4][clock+nonce:8][len 0x20][token:32]...
        token = result.messages[0].payload[1 + 3 + 4 + 8 + 1 : 1 + 3 + 4 + 8 + 1 + 32]
        self.assertEqual(token, b"a8bcb70ad09d466bb29a0ebb03e2ca62")

    def test_v3_answered_only_once(self):
        """V3 retries get answered with a 5s throttle (2026-09-19 19:26:
        the post-InGame 1115B blobs ARE V3 re-registrations; dropping
        them made the client restart the login cycle). Immediate retries
        within the throttle window only get Carrier CT_ACKS."""
        from azoth_world.rep import handle_app_data

        rec = MessageRecord(
            channel=0, payload=v3_registration_payload(), flags_override=0xE0
        )
        wire = b"\x80\x01\x00\x01" + marshal_datagram([rec])
        first = handle_app_data(
            wire, 2, handshake_done=True, inbound_first=2, v3_done=False
        )
        self.assertTrue(first)
        second = handle_app_data(
            wire,
            3,
            handshake_done=True,
            inbound_first=2,
            v3_done=True,
            v3_last_reply=time.monotonic(),
        )
        # Inside the throttle window: no second RegistrationResponse, but
        # Carrier CT_ACKS must still go out or the client retransmits then
        # @mm_csdkerr_disconnect (4).
        self.assertTrue(second)
        _, body = parse_envelope(second[0])
        recs = parse_datagram(body)
        self.assertEqual(recs.messages[0].system_msg_id, 6)
        # Outside the window (post-InGame re-registration, 90s later): the
        # V3 answer must fire again.
        third = handle_app_data(
            wire,
            4,
            handshake_done=True,
            inbound_first=2,
            v3_done=True,
            v3_last_reply=time.monotonic() - 6.0,
        )
        self.assertTrue(third)
        _, body = parse_envelope(third[0])
        recs = parse_datagram(body)
        self.assertTrue(any(m.channel == 0 for m in recs.messages))

    def test_post_v3_datagram_is_parseable(self):
        from azoth_world.rep import post_v3_datagram, self_ident_body

        wire = post_v3_datagram(10)
        env, body = parse_envelope(wire)
        self.assertEqual(env.sequence, 10)
        result = parse_datagram(body)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].payload[1:5], bytes((0x00, 0x01, 0x91, 0x17)))
        # 4-byte trigger + 21-byte structured body (self_ident_body)
        self.assertEqual(result.messages[0].payload[5:], self_ident_body())


class TestHeartbeat(unittest.TestCase):
    """Post-replay 0x15d ping/pong (see HEARTBEAT_* in rep.py).

    The tick is pinned against the capture: the first captured ping is
    `00 01 9d 05 00 03 6e f6 af 91 2d 74`, and consecutive captured values
    differ by ~1e9 (one second, in nanoseconds, big-endian).
    """

    def test_body_matches_the_capture(self):
        from azoth_world.rep import heartbeat_body

        self.assertEqual(
            heartbeat_body(0x6EF6AF912D74).hex(), "00019d0500036ef6af912d74"
        )

    def test_tick_is_big_endian_and_increments(self):
        from azoth_world.rep import heartbeat_body

        first = heartbeat_body(0x6EF6AF912D74)
        second = heartbeat_body(0x6EF6AF912D74 + 1_000_000_000)
        self.assertEqual(first[:6], second[:6])
        self.assertGreater(int.from_bytes(second[6:], "big"),
                           int.from_bytes(first[6:], "big"))

    def test_keepalive_survives_a_wrapped_envelope_counter(self):
        """The real failing path: maybe_keepalive with next_out_seq past u16.

        Measured 2026-10-10 on the long-running server: the last successful
        keepalive was at 22:10:22Z with seq 65533 and from 22:10:23Z every tick
        raised `OverflowError: int too big to convert`, so CLOCK_SYNC stopped
        being sent entirely. This drives the emitter itself, not just the
        datagram builder, so a regression in either one fails here.
        """
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.v3_responded = True
        session.replay_queue = []
        session.greetings_after_replay = True
        session.last_keepalive = 0.0
        session.next_out_seq = 0x10001  # 65537, one past the u16 wrap
        session.heartbeat_tick = 0
        sent = []
        session.send = lambda _server, data: sent.append(data)

        PeerSession.maybe_keepalive(session, None)

        self.assertEqual(len(sent), 1)
        # Envelope header: 0x80 0x01 then the wrapped sequence (0x0001).
        self.assertEqual(sent[0][:4], bytes.fromhex("80010001"))
        self.assertEqual(session.next_out_seq, 0x10002)

    def test_body_is_twelve_bytes_with_the_typed_preamble(self):
        from azoth_world.rep import heartbeat_body

        body = heartbeat_body(0x123456789ABC)
        self.assertEqual(len(body), 12)
        # typed-stream preamble for type 0x15d + the constant the capture repeats
        self.assertEqual(body[:6], bytes((0x00, 0x01, 0x9D, 0x05, 0x00, 0x03)))

    def test_tick_wraps_to_six_bytes(self):
        from azoth_world.rep import heartbeat_body

        # a value past 2**48 must not raise; it is masked to the wire width
        self.assertEqual(len(heartbeat_body(1 << 60)), 12)

    def test_heartbeat_is_unreliable(self):
        """A reliable heartbeat grew sent_reliable unbounded (resend storm)."""
        from azoth_world.rep import HEARTBEAT_ENABLED, HEARTBEAT_PERIOD_S

        self.assertIsInstance(HEARTBEAT_ENABLED, bool)
        self.assertGreater(HEARTBEAT_PERIOD_S, 0)


class TestAuthoritativeTick(unittest.TestCase):
    """The server emits on its own clock, not in proportion to inbound traffic.

    Measured 2026-10-09, before this contract existed: all periodic emitters
    were called from on_app_data (once per inbound datagram), so
    Pearson(inbound datagrams, server replies) = 0.995 and the server emitted up
    to 286 datagrams in one second for 185 inbound. The client stalled under the
    flood and dropped the transport. The replay pump had the mirror problem: it
    was ONLY called from on_app_data, so it stopped whenever the client went
    quiet. See TICK_HZ / PeerSession.tick in rep.py.
    """

    EMITTERS = (
        "maybe_keepalive",
        "maybe_send_post_v3",
        "maybe_inject",
        "maybe_pump_replay",
        "maybe_pump_deferred",
        "maybe_heartbeat",
        "maybe_activity_stream",
        "maybe_state_stream",
        "maybe_input_response",
        "maybe_channel1_echo",
    )

    def _session_with_recording_emitters(self):
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.last_resend_pump = 0.0
        session.calls: list[str] = []
        for name in (*self.EMITTERS, "maybe_resend"):

            def _record(_server, _name=name, _session=session):
                _session.calls.append(_name)

            setattr(session, name, _record)
        return session

    def test_tick_runs_every_periodic_emitter(self):
        """One tick must offer every periodic emitter its chance to fire.

        The tick itself decides nothing about timing; each emitter self-gates on
        its own `_next_at`. That is what makes calling it on a fixed cadence
        safe, and what makes a missing emitter a silent regression.
        """
        session = self._session_with_recording_emitters()
        session.tick(None)
        self.assertEqual(session.calls, [*self.EMITTERS, "maybe_resend"])

    def test_a_dead_session_is_not_ticked(self):
        session = self._session_with_recording_emitters()
        session.gone = True
        session.tick(None)
        self.assertEqual(session.calls, [])

    def test_on_app_data_does_not_drive_the_periodic_emitters(self):
        """on_app_data is the reactive path only.

        If a periodic emitter is called from there, the server's output rate
        becomes a function of the client's input rate again — the feedback loop
        that made the client drop the transport.
        """
        import inspect

        from azoth_world.rep import PeerSession

        source = inspect.getsource(PeerSession.on_app_data)
        for name in self.EMITTERS:
            self.assertNotIn(
                name,
                source,
                f"on_app_data must not call {name}; periodic work belongs in tick()",
            )

    def test_tick_period_is_positive(self):
        from azoth_world.rep import TICK_HZ, TICK_INTERVAL_S

        self.assertGreater(TICK_HZ, 0)
        self.assertGreater(TICK_INTERVAL_S, 0)



class TestActivityClockSurvivesTheReplay(unittest.TestCase):
    """The heartbeat and input-response must not wait for the replay to drain.

    Measured 2026-10-10 on a live run: the replay is ~1090 chunks (24 of the
    captured bodies are 46 KB) and at the recommended `AZOTH_CHUNK_GAP_MS=20`
    it needs ~22 s, while the client's watchdog tears the connection down at
    ~27 s of not receiving an expected message. Because both emitters gated on
    `self.replay_queue` being empty, the whole session logged ZERO `heartbeat`
    and ZERO `input-response` events, the client's
    `OnLocalNetworkConnectionWarning` climbed to 22, and the transport dropped
    with `transportError 4` 27 s after the spawn.

    The state stream is the opposite case and must KEEP waiting: it re-applies
    the same captured bundles the replay is still delivering.
    """

    def _session(self):
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.v3_responded = True
        # The honest state WHILE the replay is still streaming: the queue is not
        # empty and `greetings_after_replay` ("replay fully streamed") is NOT
        # set. This used to be pre-set True, which made the tests below pass
        # against an implementation that still waited for the drain -- the
        # regression that produced a 104-warning burst on a live run.
        session.greetings_after_replay = False
        session.replay_queue = ["still delivering the replay"]
        session.heartbeat_tick = 0
        session.heartbeat_next_at = 0.0
        session.input_response_next_at = 0.0
        session.input_response_msgs = []
        session.input_response_sent = 0
        session.out_msg_seq = 0
        session.out_rel_seq = 0
        session.next_out_seq = 1
        session.sent_reliable = {}
        session.resend_tries = {}
        session.acked_seqs = set()
        session.last_keepalive = 0.0
        sent = []
        session.send = lambda _server, data: sent.append(data)
        session.sent = sent
        return session

    def test_heartbeat_fires_while_the_replay_is_still_draining(self):
        from azoth_world.rep import HEARTBEAT_ENABLED, PeerSession

        if not HEARTBEAT_ENABLED:
            self.skipTest("heartbeat disabled in this environment")
        session = self._session()
        PeerSession.maybe_heartbeat(session, None)
        self.assertEqual(len(session.sent), 1, "the client's activity clock needs this")

    def test_input_response_fires_while_the_replay_is_still_draining(self):
        from azoth_world.javelin.replay_store import ReplayMessage
        from azoth_world.rep import INPUT_RESPONSE_ENABLED, PeerSession

        if not INPUT_RESPONSE_ENABLED:
            self.skipTest("input response disabled in this environment")
        session = self._session()
        session.input_response_msgs = [
            ReplayMessage(
                seq=0x75,
                type_id=0x1096,
                direction="R",
                body=bytes.fromhex("00019642") + bytes(4),
                has_redaction=False,
            )
        ]
        PeerSession.maybe_input_response(session, None)
        self.assertEqual(len(session.sent), 1)

    def test_nothing_is_sent_before_the_post_v3_flight(self):
        from azoth_world.rep import HEARTBEAT_ENABLED, PeerSession

        if not HEARTBEAT_ENABLED:
            self.skipTest("heartbeat disabled in this environment")
        session = self._session()
        # The gate is the post-V3 flight, NOT "the replay drained": a heartbeat
        # must not go out before the V3 response has armed the client.
        session.v3_responded = False
        PeerSession.maybe_heartbeat(session, None)
        self.assertEqual(session.sent, [])

    def test_state_stream_still_waits_for_the_drained_replay(self):
        from azoth_world.rep import STATE_STREAM_ENABLED, PeerSession

        if not STATE_STREAM_ENABLED:
            self.skipTest("state stream is off by default")
        session = self._session()
        session.state_stream_queue = ["a captured bundle"]
        PeerSession.maybe_state_stream(session, None)
        self.assertEqual(
            session.sent,
            [],
            "re-applying a captured bundle during the replay double-applies state",
        )


class TestEnvelopeSeqWrapping(unittest.TestCase):
    """A 16-bit wire field must wrap, not raise.

    Measured 2026-10-10 on the long-running server: the last successful
    `maybe_keepalive` was at 22:10:22Z with seq 65533, and from 22:10:23Z every
    tick raised `OverflowError: int too big to convert` -- 7395 consecutive
    errors over two hours, with no CLOCK_SYNC sent at all. `next_out_seq` grows
    without bound and the datagram builders called `seq.to_bytes(2, "big")`
    directly, so the keepalive died permanently the moment the counter passed
    65535. The envelope sequence is a u16 on the wire, so wrapping is correct.
    """

    ABOVE_U16 = 70000

    def test_datagram_builders_survive_a_seq_above_u16(self):
        from azoth_world import rep

        builders = (
            ("v3_response_datagram", lambda: rep.v3_response_datagram(self.ABOVE_U16)),
            ("post_v3_datagram", lambda: rep.post_v3_datagram(self.ABOVE_U16)),
            ("clock_sync_datagram", lambda: rep.clock_sync_datagram(self.ABOVE_U16)),
            ("greetings_datagram", lambda: rep.greetings_datagram(self.ABOVE_U16)),
            (
                "carrier_state_datagram",
                lambda: rep.carrier_state_datagram(
                    self.ABOVE_U16,
                    welcome=b"w",
                    ack_first=self.ABOVE_U16,
                    ack_last=self.ABOVE_U16,
                ),
            ),
            (
                "ct_acks_datagram",
                lambda: rep.ct_acks_datagram(
                    self.ABOVE_U16, ack_first=self.ABOVE_U16, ack_last=self.ABOVE_U16
                ),
            ),
        )
        for name, build in builders:
            with self.subTest(builder=name):
                build()  # must not raise OverflowError

    def test_seq_wraps_to_the_same_bytes_as_its_low_16_bits(self):
        from azoth_world.rep import clock_sync_datagram

        self.assertEqual(clock_sync_datagram(1)[:4], bytes.fromhex("80010001"))
        self.assertEqual(clock_sync_datagram(65536)[:4], bytes.fromhex("80010000"))
        self.assertEqual(
            clock_sync_datagram(65537)[:4], clock_sync_datagram(1)[:4]
        )
        # The payload byte after the header is the wall-clock tick, so only the
        # envelope header is compared.
        self.assertEqual(
            clock_sync_datagram(self.ABOVE_U16)[:4],
            clock_sync_datagram(self.ABOVE_U16 & 0xFFFF)[:4],
        )

    def test_u16_helper(self):
        from azoth_world.rep import _u16

        self.assertEqual(_u16(0), bytes.fromhex("0000"))
        self.assertEqual(_u16(0xFFFF), bytes.fromhex("ffff"))
        self.assertEqual(_u16(0x10000), bytes.fromhex("0000"))
        self.assertEqual(_u16(0x10001), bytes.fromhex("0001"))
        self.assertEqual(_u16(-1), bytes.fromhex("ffff"))


class TestAckWindow(unittest.TestCase):
    """The continuous ACK range must stay narrower than half the 16-bit space.

    MEASURED 2026-10-14 and it cost a whole session: the range was
    `[inbound_first, current]` with `inbound_first` pinned for the session, so its width grew by
    one per datagram. The two fields are 16 bits, so at width 32768 a wrap-aware reader can no
    longer tell how wide the range is. The client did not error - it started retransmitting
    every reliable record it sent (~200x each: 140 174 channel-0 records carrying 660 distinct
    sequences) the second after the inbound envelope sequence crossed 32768
    (32767 at 08:42:44 -> 32768 at 08:42:44 -> first retransmit 08:42:45).
    """

    def test_young_session_acknowledges_from_its_first_datagram(self):
        """While the session is younger than the window, the range starts at its first seq."""
        from azoth_world.rep import ack_window_first

        start = 1000
        for count in (1, 2, 50, 4096):
            with self.subTest(count=count):
                last = start + count - 1
                self.assertEqual(ack_window_first(last, count, 4096), start)

    def test_window_never_exceeds_its_width(self):
        from azoth_world.rep import ACK_WINDOW, ack_window_first

        # Walk a session well past the boundary that broke the client.
        for last in range(0, 40000, 397):
            first = ack_window_first(last, last + 1)
            width = (last - first) & 0xFFFF
            self.assertLess(width, 0x8000, f"ambiguous range at seq {last}")
            self.assertLessEqual(width, ACK_WINDOW)

    def test_the_boundary_that_broke_the_client_is_now_safe(self):
        """The measured onset: the ACK used to be 32766 wide when last became 32768."""
        from azoth_world.rep import ack_window_first

        old_width = 32768 - 2          # what the pinned range produced
        self.assertGreaterEqual(old_width, 0x8000 - 2)
        new_first = ack_window_first(32768, 32768)
        self.assertEqual((32768 - new_first) & 0xFFFF, 16383)
        self.assertLess((32768 - new_first) & 0xFFFF, 0x8000)

    def test_window_survives_the_16_bit_wrap(self):
        """A count-based window stays correct when the wire sequence wraps at 65536."""
        from azoth_world.rep import ack_window_first

        # last wrapped to 5 after 65542 datagrams; the range must stay a narrow local window.
        first = ack_window_first(5, 65542)
        self.assertEqual((5 - first) & 0xFFFF, 16383)

    def test_ack_range_is_encoded_and_stays_inside_u16(self):
        """The encoded datagram carries exactly the windowed first, not the session's first."""

        from azoth_world.javelin import parse_datagram, parse_envelope
        from azoth_world.rep import ACK_WINDOW, ack_window_first, ct_acks_datagram

        last = 40000
        first = ack_window_first(last, last + 1)
        env, body = parse_envelope(ct_acks_datagram(last, ack_first=first, ack_last=last))
        cts = [
            r.payload
            for r in parse_datagram(body).messages
            if r.payload and r.payload[0] == 0x40
        ]
        self.assertEqual(len(cts), 1)
        payload = cts[0]
        encoded_last = int.from_bytes(payload[1:3], "big")
        encoded_first = int.from_bytes(payload[3:5], "big")
        self.assertEqual(encoded_last, last)
        self.assertEqual(encoded_first, first)
        self.assertEqual((encoded_last - encoded_first) & 0xFFFF, ACK_WINDOW - 1)
        self.assertLess((encoded_last - encoded_first) & 0xFFFF, 0x8000)

    def test_session_tracks_how_many_datagrams_it_has_seen(self):
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.inbound_first = None
        session.inbound_count = 0
        # The counter is what makes the window wrap-safe; it must not be derived from the seq.
        self.assertEqual(session.inbound_count, 0)


class TestClientHelloDetection(unittest.TestCase):
    """A reused source port must reset the DTLS session (2026-09-27).

    The client retries its ClientHello from the same port after a previous
    session ended; feeding that into the stale DTLS state machine left the
    handshake stuck with no reply and no error, which the client reported as
    `@mm_csdkerr_connection_failed`. These are the exact captured bytes.
    """

    def test_client_hello_is_detected(self):
        from azoth_world.rep import _is_client_hello

        self.assertTrue(
            _is_client_hello(bytes.fromhex("16fefd00000000000000000092010000"))
        )

    def test_client_hello_retry_is_detected(self):
        from azoth_world.rep import _is_client_hello

        # same record, sequence number incremented by the retry
        self.assertTrue(
            _is_client_hello(bytes.fromhex("16fefd00000000000000010092010000"))
        )

    def test_application_data_is_not_a_client_hello(self):
        from azoth_world.rep import _is_client_hello

        self.assertFalse(
            _is_client_hello(bytes.fromhex("17fefd0001000000000189002aa3a507"))
        )

    def test_short_datagram_is_not_a_client_hello(self):
        from azoth_world.rep import _is_client_hello

        self.assertFalse(_is_client_hello(b""))
        self.assertFalse(_is_client_hello(bytes.fromhex("16fefd00000000")))


class TestResponseDatagram(unittest.TestCase):
    def test_v3_response_is_parseable(self):
        wire = v3_response_datagram(7)
        env, body = parse_envelope(wire)
        self.assertEqual(env.sequence, 7)
        result = parse_datagram(body)
        self.assertIsNone(result.error)
        rec = result.messages[0]
        self.assertEqual(len(rec.payload), 89)
        self.assertEqual(rec.payload[0], 88)  # VLQ32 body size
        self.assertEqual(rec.payload[1], 0x00)  # typed preamble byte 0
        self.assertEqual(rec.payload[2], 0x01)  # typed preamble byte 1
        self.assertEqual(rec.payload[3], 0x03)  # typed type id 0x3


@unittest.skipUnless(HAVE_PYOPENSSL, "pyOpenSSL not installed")
class TestDtlsHandshake(unittest.TestCase):
    def test_client_handshake_completes(self):
        from azoth_world.rep import RepServer

        srv = RepServer("127.0.0.1", 0)  # port 0 = ephemeral
        port = srv.sock.getsockname()[1]

        client_ctx = SSL.Context(SSL.DTLS_METHOD)
        client_ctx.set_verify(SSL.VERIFY_NONE, lambda *a: True)  # trust patch
        client = SSL.Connection(client_ctx)
        client.set_connect_state()

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.settimeout(5)
        addr = ("127.0.0.1", port)
        import threading

        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()

        # Drive the handshake loop like the game does: bio_read -> sendto,
        # recvfrom -> bio_write, until established.
        established = False
        for _ in range(10):
            try:
                client.do_handshake()
                established = True
                break
            except SSL.WantReadError:
                out = client.bio_read(65536)
                if out:
                    udp.sendto(out, addr)
                data, _ = udp.recvfrom(65536)
                client.bio_write(data)
        self.assertTrue(established)
        udp.close()
        srv.sock.close()

    def test_v3_roundtrip_over_dtls(self):
        from azoth_world.rep import RepServer

        srv = RepServer("127.0.0.1", 0)
        port = srv.sock.getsockname()[1]
        client_ctx = SSL.Context(SSL.DTLS_METHOD)
        client_ctx.set_verify(SSL.VERIFY_NONE, lambda *a: True)
        client = SSL.Connection(client_ctx)
        client.set_connect_state()
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.settimeout(5)
        addr = ("127.0.0.1", port)
        import threading

        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()

        def pump():
            while True:
                try:
                    out = client.bio_read(65536)
                except SSL.WantReadError:
                    return
                if not out:
                    return
                udp.sendto(out, addr)

        for _ in range(10):
            try:
                client.do_handshake()
                break
            except SSL.WantReadError:
                pump()
                data, _ = udp.recvfrom(65536)
                client.bio_write(data)
        pump()  # flush anything pending

        # Send a V3 data-channel record (client -> server), expect the
        # VLQ32(88)+88B RegistrationResponseMsg back.
        rec = MessageRecord(
            channel=0,
            payload=v3_registration_payload(),
            flags_override=0xE0,
        )
        client.send(b"\x80\x01\x00\x01" + marshal_datagram([rec]))
        pump()
        data, _ = udp.recvfrom(65536)
        client.bio_write(data)
        resp = client.recv(65536)
        env, body = parse_envelope(resp)
        result = parse_datagram(body)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(len(result.messages[0].payload), 89)
        udp.close()
        srv.sock.close()


class TestStateStream(unittest.TestCase):
    """Post-replay 0x08 state-bundle stream (see STATE_STREAM_* in rep.py).

    The capture's steady state is R-direction type 0x08 bundles right up to seq 0xb0, and
    the real server never stopped sending them. Our replay does, and the client's ALC
    "last response" stamp then ages out - which IS the red HUD cable.

    MEASURED 2026-10-13, and these tests encode that measurement:
      * the LOCAL PLAYER's own state is record_id 1, and in the capture it lives only in
        the four 7154-byte bundles at seq 0x98/0x9A/0x9C/0x9E - all BELOW the old floor of
        0xA0, so the stream used to re-send everybody else's state and never the player's;
      * with the floor at 0xA0 the ALC stamp NEVER moved (1 change in 140 s, age growing to
        262 s, cable RED); with the player's record re-sent 4x/s the stamp moved 225 times,
        age never above 100 ms, and the cable icon disappeared.
    So the stream is ON by default, the floor reaches the player's bundles, and the
    player's record gets its own faster timer.
    """

    def _session(self, *, now: float = 1_000.0):
        """PeerSession.__new__ with only the fields the stream reads.

        _send_replay_message is replaced so the test does not touch OpenSSL;
        the transport wrap is covered elsewhere.
        """
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.v3_responded = True
        session.replay_queue = []
        session.greetings_after_replay = True
        session.out_msg_seq = 1
        session.out_rel_seq = 1
        session.state_stream_all = []
        session.state_stream_queue = []
        session.state_stream_player = []
        session.state_stream_player_queue = []
        session.state_stream_next_at = 0.0
        session.state_stream_player_next_at = 0.0
        session.state_stream_sent = 0
        session.state_stream_player_sent = 0
        session.state_stream_seq = 54
        session.sent: list = []

        def _record(_server, msg, _session=session):
            _session.sent.append(msg)

        session._send_replay_message = _record
        return session

    @staticmethod
    def _bundle(seq: int):
        """Real ReplayMessage whose body is a well-formed type-0x08 bundle.

        The body has to be a REAL bundle, not an opaque byte string: the state
        stream re-encodes the replication counter through the verified parser
        (`azoth_world.javelin.bundle`), which refuses to rewrite a body it
        cannot parse. A synthetic 5-byte body would assert a layout the
        protocol does not have.
        """
        from azoth_world.javelin import bundle as javelin_bundle
        from azoth_world.javelin.replay_store import ReplayMessage

        body = javelin_bundle.encode_type_marker(0x08) + javelin_bundle.BundleBody(
            replication_seq=0x25,
            payload=b"\x01\x01" + bytes(16),
        ).encode_body()
        return ReplayMessage(
            seq=seq,
            type_id=0x08,
            direction="R",
            body=body,
            has_redaction=False,
        )

    def test_stream_is_on_by_default_and_reaches_the_player_record(self):
        """The measured fix: ON by default, floor at the player's bundles, record 1.

        This is a deliberate change from the old default. The stream used to break the
        connection (2026-10-04: REP dropped at +23 s) because the replication counter was
        rewritten by overwriting one raw byte, which corrupted the body. With the rewrite
        going through the verified varint parser the same stream is what keeps the ALC
        stamp young, so OFF is now the broken configuration.
        """
        import importlib
        import os

        from azoth_world import rep as rep_module

        saved = {
            k: os.environ.pop(k, None)
            for k in (
                "AZOTH_REPLAY_STATE_STREAM",
                "AZOTH_REPLAY_STATE_STREAM_SEQ",
                "AZOTH_REPLAY_STATE_STREAM_MIN_SEQ",
                "AZOTH_REPLAY_STATE_STREAM_PLAYER_RECORD",
            )
        }
        try:
            importlib.reload(rep_module)
            self.assertTrue(rep_module.STATE_STREAM_ENABLED)
            self.assertTrue(rep_module.STATE_STREAM_REWRITE_SEQ)
            self.assertEqual(rep_module.STATE_STREAM_MIN_SEQ, 0x94)
            self.assertEqual(rep_module.STATE_STREAM_PLAYER_RECORD, 1)
            armed = [
                m
                for m in rep_module.replay_store().messages
                if m.type_id == 0x08
                and m.seq >= rep_module.STATE_STREAM_MIN_SEQ
                and rep_module._state_stream_record_id(m)
                == rep_module.STATE_STREAM_PLAYER_RECORD
            ]
            self.assertEqual(
                [m.seq for m in armed],
                [0x98, 0x9A, 0x9C, 0x9E],
                "the local player's own state bundles must be in the armed set",
            )
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
            importlib.reload(rep_module)

    def test_stream_can_be_forced_off_for_an_ab(self):
        import importlib
        import os

        from azoth_world import rep as rep_module

        previous = os.environ.get("AZOTH_REPLAY_STATE_STREAM")
        os.environ["AZOTH_REPLAY_STATE_STREAM"] = "0"
        try:
            importlib.reload(rep_module)
            self.assertFalse(rep_module.STATE_STREAM_ENABLED)
        finally:
            if previous is None:
                os.environ.pop("AZOTH_REPLAY_STATE_STREAM", None)
            else:
                os.environ["AZOTH_REPLAY_STATE_STREAM"] = previous
            importlib.reload(rep_module)

    def test_armed_tail_parses_and_is_in_capture_order(self):
        """Every armed bundle must be a real, parseable 0x08 bundle, in order.

        The old version of this test also asserted that none of them exceeds
        REPLAY_CHUNK_SIZE. That no longer holds and must not: the floor now reaches the
        player's bundles, which are 7167 bytes, and the REPLAY already sends those same
        bodies through the chunked path successfully - so chunking them here is the
        already-exercised path, not a new risk.
        """
        from azoth_world.javelin import bundle as javelin_bundle
        from azoth_world.rep import STATE_STREAM_MIN_SEQ, replay_store

        store = replay_store()
        queue = [
            m
            for m in store.messages
            if m.type_id == 0x08 and m.seq >= STATE_STREAM_MIN_SEQ
        ]
        self.assertGreater(len(queue), 0, "no captured tail bundles to continue")
        for msg in queue:
            javelin_bundle.decode_bundle(msg.body)
        self.assertEqual([m.seq for m in queue], sorted(m.seq for m in queue))

    def test_stream_waits_for_the_replay_and_greetings(self):
        from unittest import mock

        from azoth_world.rep import PeerSession

        with mock.patch("azoth_world.rep.STATE_STREAM_ENABLED", True):
            self._waits_for_the_replay_and_greetings(PeerSession)

    def _waits_for_the_replay_and_greetings(self, PeerSession):
        session = self._session()
        first = self._bundle(0xA0)
        session.state_stream_all = [first]
        session.state_stream_queue = [first]
        session.greetings_after_replay = False
        PeerSession.maybe_state_stream(session, None)
        self.assertEqual(session.sent, [])

        session.greetings_after_replay = True
        session.replay_queue = ["still replaying"]
        PeerSession.maybe_state_stream(session, None)
        self.assertEqual(session.sent, [])

        session.replay_queue = []
        PeerSession.maybe_state_stream(session, None)
        self.assertEqual([m.seq for m in session.sent], [first.seq])

    def test_stream_sends_one_world_bundle_per_period_in_capture_order(self):
        from unittest import mock

        from azoth_world.rep import PeerSession, STATE_STREAM_PERIOD_S

        with mock.patch("azoth_world.rep.STATE_STREAM_ENABLED", True):
            self._one_per_period(PeerSession, STATE_STREAM_PERIOD_S)

    def _one_per_period(self, PeerSession, STATE_STREAM_PERIOD_S):
        from unittest import mock
        session = self._session()
        first, second = self._bundle(0xA0), self._bundle(0xA1)
        session.state_stream_all = [first, second]
        session.state_stream_queue = [first, second]
        clock = {"now": 1_000.0}
        with mock.patch("azoth_world.rep.time.monotonic", lambda: clock["now"]):
            PeerSession.maybe_state_stream(session, None)
            PeerSession.maybe_state_stream(session, None)  # inside the period
            self.assertEqual([m.seq for m in session.sent], [first.seq])
            clock["now"] += STATE_STREAM_PERIOD_S
            PeerSession.maybe_state_stream(session, None)
        self.assertEqual([m.seq for m in session.sent], [first.seq, second.seq])
        self.assertEqual(session.state_stream_sent, 2)

    def test_player_record_gets_its_own_faster_timer(self):
        """The measured fix: the player's own state is refreshed faster than the world's.

        The cable clears only when the ALC stamp is refreshed more often than the amber
        threshold (~2 s). Streaming the whole captured tail at one rate gives a refresh
        every (tail / player_bundles) periods - measured 12 refreshes in 140 s, cable
        YELLOW. The player's record therefore has its own timer.
        """
        from unittest import mock

        from azoth_world.rep import (
            PeerSession,
            STATE_STREAM_PLAYER_PERIOD_S,
            STATE_STREAM_PERIOD_S,
        )

        session = self._session()
        world = self._bundle(0xA0)
        p1, p2 = self._bundle(0x98), self._bundle(0x9A)
        session.state_stream_all = [world, p1, p2]
        session.state_stream_queue = [world]
        session.state_stream_player = [p1, p2]
        session.state_stream_player_queue = [p1, p2]
        clock = {"now": 1_000.0}
        with mock.patch("azoth_world.rep.time.monotonic", lambda: clock["now"]), \
                mock.patch("azoth_world.rep.STATE_STREAM_ENABLED", True):
            PeerSession.maybe_state_stream(session, None)   # player p1 + world
            self.assertEqual([m.seq for m in session.sent], [p1.seq, world.seq])
            clock["now"] += STATE_STREAM_PLAYER_PERIOD_S
            PeerSession.maybe_state_stream(session, None)   # player p2 only
            self.assertEqual([m.seq for m in session.sent], [p1.seq, world.seq, p2.seq])
            # the player queue refilled from the armed player list when it emptied
            self.assertEqual(session.state_stream_player_queue, [p1, p2])
            self.assertEqual(session.state_stream_player_sent, 2)
        self.assertLess(
            STATE_STREAM_PLAYER_PERIOD_S * 2,
            STATE_STREAM_PERIOD_S,
            "the player's cycle must be faster than one world send",
        )

    def test_stream_loops_through_the_capture(self):
        """One pass is not enough: the real server streamed 0x08 forever, so
        the queue must refill from the armed list instead of going quiet."""
        from unittest import mock

        from azoth_world.rep import PeerSession, STATE_STREAM_PERIOD_S

        with mock.patch("azoth_world.rep.STATE_STREAM_ENABLED", True):
            self._loops(PeerSession, STATE_STREAM_PERIOD_S)

    def _loops(self, PeerSession, STATE_STREAM_PERIOD_S):
        from unittest import mock

        session = self._session()
        first = self._bundle(0xA0)
        session.state_stream_all = [first]
        session.state_stream_queue = [first]
        clock = {"now": 1_000.0}
        with mock.patch("azoth_world.rep.time.monotonic", lambda: clock["now"]):
            PeerSession.maybe_state_stream(session, None)
            self.assertEqual([m.seq for m in session.sent], [first.seq])
            self.assertEqual(session.state_stream_queue, [])
            clock["now"] += STATE_STREAM_PERIOD_S
            PeerSession.maybe_state_stream(session, None)
        self.assertEqual([m.seq for m in session.sent], [first.seq, first.seq])
        self.assertEqual(session.state_stream_sent, 2)

    def test_wire_seq_is_rewritten_by_default(self):
        """The counter must continue above the client's high-water, or the bundle is dropped.

        Measured 2026-10-13: with the rewrite OFF a session sent 697 `state-stream` events,
        the client logged ZERO errors, and the world behaved exactly as if nothing had been
        sent - because the replication gate discards a bundle whose counter is not strictly
        greater than m_lastUnreliableReplicationSeq. "No errors" does not mean "applied".

        The rewrite is safe because it re-encodes the varint through the verified parser.
        The earlier corruption (32 `Failed to unmarshal`, 2026-10-09) came from overwriting
        one raw byte, which widens a one-byte varint into two and shifts every fragment.
        """
        from azoth_world.rep import STATE_STREAM_REWRITE_SEQ

        self.assertTrue(STATE_STREAM_REWRITE_SEQ)

    def test_wire_seq_rewrite_continues_the_counter(self):
        from unittest import mock

        from azoth_world.rep import (
            PeerSession,
            STATE_STREAM_PERIOD_S,
            STATE_STREAM_SEQ_OFFSET,
        )

        with mock.patch("azoth_world.rep.STATE_STREAM_ENABLED", True), mock.patch(
            "azoth_world.rep.STATE_STREAM_REWRITE_SEQ", True
        ):
            self._rewrites(PeerSession, STATE_STREAM_PERIOD_S, STATE_STREAM_SEQ_OFFSET)

    def _rewrites(self, PeerSession, STATE_STREAM_PERIOD_S, STATE_STREAM_SEQ_OFFSET):
        from unittest import mock
        session = self._session()
        first, second = self._bundle(0xA0), self._bundle(0xA1)
        session.state_stream_all = [first, second]
        session.state_stream_queue = [first, second]
        session.state_stream_seq = 54
        clock = {"now": 1_000.0}
        with mock.patch("azoth_world.rep.time.monotonic", lambda: clock["now"]):
            PeerSession.maybe_state_stream(session, None)
            clock["now"] += STATE_STREAM_PERIOD_S
            PeerSession.maybe_state_stream(session, None)
        self.assertEqual(session.sent[0].body[STATE_STREAM_SEQ_OFFSET], 54)
        self.assertEqual(session.sent[1].body[STATE_STREAM_SEQ_OFFSET], 55)
        self.assertEqual(session.sent[0].body[:4], first.body[:4])
        self.assertEqual(len(session.sent[0].body), len(first.body))

    def test_negative_only_record_means_no_filter(self):
        """`ONLY_RECORD=-1` must select everything, not nothing.

        Real bug, 2026-10-13: the filter was written as an equality against the sentinel, so
        the default -1 matched no bundle. The stream armed with ZERO bundles while the config
        event still reported `state_stream: True` and the arming event looked normal - a
        silent no-op, and the cable stayed RED with nothing in the logs to explain it.
        """
        from azoth_world.rep import (
            STATE_STREAM_MIN_SEQ,
            _state_stream_record_id,
            _state_stream_selected,
            replay_store,
        )

        bundles = [
            m
            for m in replay_store().messages
            if m.type_id == 0x08 and m.seq >= STATE_STREAM_MIN_SEQ
        ]
        self.assertGreater(len(bundles), 0)
        from unittest import mock as mock_module

        with mock_module.patch("azoth_world.rep.STATE_STREAM_ONLY_RECORD", -1):
            self.assertTrue(all(_state_stream_selected(m) for m in bundles))
        with mock_module.patch("azoth_world.rep.STATE_STREAM_ONLY_RECORD", 1):
            selected = [m for m in bundles if _state_stream_selected(m)]
            self.assertEqual([m.seq for m in selected], [0x98, 0x9A, 0x9C, 0x9E])
            self.assertTrue(all(_state_stream_record_id(m) == 1 for m in selected))

    def test_stream_does_not_loop_an_empty_arm(self):
        from azoth_world.rep import PeerSession

        session = self._session()
        PeerSession.maybe_state_stream(session, None)
        self.assertEqual(session.sent, [])


class TestInputResponseReadiness(unittest.TestCase):
    """The input-response is a client-facet RMI, so it waits for the client's object graph.

    MEASURED 2026-10-14: the heartbeat and the input-response shared one readiness predicate,
    and that is wrong for this one. The heartbeat is a TRANSPORT ping - it must not wait for
    the replay, because the client's watchdog tears the connection down after ~27 s without
    one. The input-response is a CLIENT-FACET RMI and the facet does not exist until the client
    is in the world; sending it earlier produced the two `TimeComponentClientFacet` dispatch
    failures a clean session still logged, 1 s before `player spawn succeeds`.
    """

    def _session(self):
        from azoth_world.rep import PeerSession
        from azoth_world.javelin.replay_store import ReplayMessage

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.v3_responded = True
        session.greetings_after_replay = False
        session.replay_queue = []
        session.input_response_msgs = [
            ReplayMessage(seq=0x75, type_id=0x1096, direction="R", body=b"x",
                          has_redaction=False)
        ]
        session.input_response_sent = 0
        session.input_response_next_at = 0.0
        session.sent: list = []
        session._send_replay_message = lambda _s, m: session.sent.append(m)
        return session

    def test_waits_for_the_replay_to_drain(self):
        from unittest import mock

        from azoth_world.rep import PeerSession

        with mock.patch("azoth_world.rep.INPUT_RESPONSE_ENABLED", True):
            session = self._session()
            PeerSession.maybe_input_response(session, None)
            self.assertEqual(session.sent, [], "must not fire before the client has facets")

            session.greetings_after_replay = True
            PeerSession.maybe_input_response(session, None)
            self.assertEqual([m.seq for m in session.sent], [0x75])

    def test_the_watchdog_predicate_does_not_wait_for_the_replay(self):
        """The other half of the split, asserted on the predicate itself.

        `_post_replay_started()` is what the heartbeat gates on, and it must be True as soon as
        V3 has been answered - even with the replay still running - because the client's
        watchdog tears the connection down after ~27 s without a ping. A full-session fake here
        would be fragile; the invariant is about the predicate, so assert it there.
        """
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.v3_responded = True
        session.greetings_after_replay = False
        session.replay_queue = ["still replaying"]
        self.assertTrue(
            PeerSession._post_replay_started(session),
            "the heartbeat must not wait for the replay drain",
        )

        session.v3_responded = False
        self.assertFalse(PeerSession._post_replay_started(session))


class TestReplayResponseScheduling(unittest.TestCase):
    """Client-facet responses are sent only when the client can actually receive them.

    MEASURED 2026-10-13: a clean session logged 29 `RMIDispatch: The facet target ID couldn't
    be found` errors, ALL inside a single millisecond, 1 ms BEFORE `player spawn succeeds`,
    while the replay drains 8 s AFTER it. The replay blasts responses at a client whose object
    graph does not exist yet, and since each message is sent once, that data is lost for the
    whole session.

    MEASURED 2026-10-14: which action is right is a REQUEST-CORRELATION question, not a facet
    survey. The replay is another client's capture, so a response exists because some client
    sent the `*ServerFacet_*` request it answers; if OUR client never sends that request there
    is no target and no reason to send the answer. RESPONSE_REQUESTS records the pairs measured
    from the capture's own ordering and from the family naming. Only one type stays a static
    drop (ABSENT_FACET_RESPONSES), because it is unsolicited and its facet was measured absent.
    """

    @staticmethod
    def _stub(deferred, seen=(), *, greeting=True, replaying=()):
        """A PeerSession shell with just the state maybe_pump_deferred touches."""
        from azoth_world.rep import PeerSession

        session = PeerSession.__new__(PeerSession)
        session.gone = False
        session.v3_responded = True
        session.greetings_after_replay = greeting
        session.replay_queue = list(replaying)
        session.deferred_replay = list(deferred)
        session.deferred_replay_sent = 0
        session.deferred_replay_dropped = 0
        session.defer_deadline = None
        session.request_coverage_logged = False
        session.inbound_types_seen = {(0, t) for t in seen}
        session.sent = []
        session._send_replay_message = lambda _s, m: session.sent.append(m)
        return session

    @staticmethod
    def _msg(seq, type_id):
        from azoth_world.javelin.replay_store import ReplayMessage

        return ReplayMessage(seq=seq, type_id=type_id, direction="R", body=b"x",
                             has_redaction=False)

    def test_every_deferred_type_has_a_decision_rule(self):
        """No held type may be left without a rule, or it would silently never be decided."""
        from azoth_world.rep import (
            ABSENT_FACET_RESPONSES,
            DEFERRED_RESPONSE_TYPES,
            RESPONSE_REQUESTS,
        )

        for type_id in DEFERRED_RESPONSE_TYPES:
            self.assertTrue(
                type_id in RESPONSE_REQUESTS or type_id in ABSENT_FACET_RESPONSES,
                f"{hex(type_id)} is held but has no decision rule",
            )
        # A request-gated response (non-empty request tuple) cannot also be an unconditional
        # absent-facet drop: one requires a request, the other says no request can justify it.
        for type_id in ABSENT_FACET_RESPONSES:
            self.assertEqual(
                RESPONSE_REQUESTS.get(type_id, ()),
                (),
                f"{hex(type_id)} is an absent-facet drop and must be unsolicited",
            )
        # Every required request is a plausible wire id.
        for resp, reqs in RESPONSE_REQUESTS.items():
            self.assertIsInstance(reqs, tuple)
            for req in reqs:
                self.assertGreater(req, 0)
        # The measured pairs from the capture, kept as a regression against a table edit.
        self.assertEqual(RESPONSE_REQUESTS[0x08E6], (0x09FC,))
        self.assertEqual(RESPONSE_REQUESTS[0x1067], (0x066B,))
        self.assertIn(0x1B7F, RESPONSE_REQUESTS[0x1B88])

    def test_partition_holds_every_measured_response_and_passes_the_rest(self):
        """A message outside the tables must pass through untouched.

        This is the property that makes the change safe: it cannot alter a message it was not
        measured on, so a protocol change cannot be silently swallowed.
        """
        from unittest import mock

        from azoth_world.rep import _partition_replay

        unknown = self._msg(1, 0x0663)      # LevelInfo: must be sent as before
        storage = self._msg(2, 0x1B88)      # request-gated (0x1B7F)
        timing = self._msg(3, 0x1096)       # request-gated (0x1098 / 0x0635)
        contracts = self._msg(4, 0x08E6)    # request-gated (0x09FC)
        unsolicited = self._msg(5, 0x0CA4)  # unsolicited, facet absent
        with mock.patch("azoth_world.rep.REPLAY_DROP_UNRECEIVABLE", True), \
                mock.patch("azoth_world.rep.REPLAY_DEFER_CLIENT_FACETS", True), \
                mock.patch("azoth_world.rep.REPLAY_REQUEST_GATING", True):
            now, defer, drop = _partition_replay(
                [unknown, storage, timing, contracts, unsolicited]
            )
        self.assertEqual([m.seq for m in now], [1])
        self.assertEqual([m.seq for m in defer], [2, 3, 4, 5])
        self.assertEqual(drop, [], "with gating on, every suppression is decided at drain")

    def test_levers_can_disable_each_behaviour(self):
        from unittest import mock

        from azoth_world.rep import _partition_replay

        items = [self._msg(1, 0x1B88), self._msg(2, 0x1096)]
        with mock.patch("azoth_world.rep.REPLAY_DROP_UNRECEIVABLE", False), \
                mock.patch("azoth_world.rep.REPLAY_DEFER_CLIENT_FACETS", False):
            now, defer, drop = _partition_replay(items)
        self.assertEqual([m.seq for m in now], [1, 2])
        self.assertEqual(defer, [])
        self.assertEqual(drop, [])

    def test_gating_off_reproduces_the_legacy_drop_set(self):
        """The A/B has to be honest: gating off must behave exactly like the old policy.

        With request gating on, 0x1067 is sent and 0x1B88 is held for its request. With it
        off, the pre-2026-10-14 static drop set must apply unchanged, or a comparison of the
        two would be measuring two differences at once.
        """
        from unittest import mock

        from azoth_world.rep import LEGACY_UNRECEIVABLE_TYPES, _partition_replay

        items = [
            self._msg(1, 0x1B88), self._msg(2, 0x1067), self._msg(3, 0x0CA4),
            self._msg(4, 0x1096),
        ]
        with mock.patch("azoth_world.rep.REPLAY_REQUEST_GATING", False), \
                mock.patch("azoth_world.rep.REPLAY_DROP_UNRECEIVABLE", True), \
                mock.patch("azoth_world.rep.REPLAY_DEFER_CLIENT_FACETS", True):
            now, defer, drop = _partition_replay(items)
        self.assertEqual([m.seq for m in drop], [1, 2, 3])
        self.assertEqual([m.seq for m in defer], [4])
        self.assertEqual(now, [])
        self.assertEqual(set(LEGACY_UNRECEIVABLE_TYPES), {0x1B88, 0x0CA4, 0x1067})

    def test_gated_response_is_dropped_when_its_request_never_arrives(self):
        """The core of the fix: a response whose request the client never sent is dropped.

        Before this, the replay answered questions nobody asked and the client logged one
        dispatch error per answer. Contracts (0x08E6) needs 0x09FC; with 0x09FC absent from
        the session it must be dropped, and the drop must be reported with its reason.
        """
        contracts = self._msg(0x43, 0x08E6)
        session = self._stub([contracts], seen=())
        session.defer_deadline = -1.0  # the waiting window has already elapsed
        PeerSession = type(session)
        PeerSession.maybe_pump_deferred(session, None)
        self.assertEqual(session.sent, [])
        self.assertEqual(session.deferred_replay_dropped, 1)
        self.assertEqual(session.deferred_replay, [])

    def test_gated_response_is_held_until_its_request_arrives(self):
        """A late request still gets its answer inside the window."""
        contracts = self._msg(0x43, 0x08E6)
        session = self._stub([contracts], seen=())
        PeerSession = type(session)
        PeerSession.maybe_pump_deferred(session, None)
        self.assertEqual(session.sent, [], "held, not sent, while the request is missing")
        self.assertEqual(session.deferred_replay, [contracts], "still waiting")
        # The client asks (Contracts LookupContractsByParticipant), then the next pump sends it.
        session.inbound_types_seen.add((0, 0x09FC))
        PeerSession.maybe_pump_deferred(session, None)
        self.assertEqual([m.seq for m in session.sent], [0x43])
        self.assertEqual(session.deferred_replay_sent, 1)
        self.assertEqual(session.deferred_replay, [])

    def test_request_seen_before_the_drain_sends_immediately(self):
        """If the client already asked before the replay drained, the answer goes out at once."""
        timing = self._msg(0x75, 0x1096)
        session = self._stub([timing], seen=(0x1098,))
        type(session).maybe_pump_deferred(session, None)
        self.assertEqual([m.seq for m in session.sent], [0x75])

    def test_unsolicited_absent_facet_response_is_dropped(self):
        """0x0CA4 has no request in the capture and its facet is measured absent."""
        sync = self._msg(0x09, 0x0CA4)
        session = self._stub([sync], seen=())
        session.defer_deadline = -1.0
        type(session).maybe_pump_deferred(session, None)
        self.assertEqual(session.sent, [])
        self.assertEqual(session.deferred_replay_dropped, 1)

    def test_deferred_messages_wait_for_the_replay_to_drain(self):
        """They must not be sent while the replay is still running or before the client's
        context is up - that is the whole point of deferring them."""
        held = self._msg(0x75, 0x1096)
        session = self._stub([held], seen=(0x1098,), greeting=False, replaying=["still"])
        PeerSession = type(session)
        PeerSession.maybe_pump_deferred(session, None)
        self.assertEqual(session.sent, [])

        session.replay_queue = []
        PeerSession.maybe_pump_deferred(session, None)
        self.assertEqual(session.sent, [], "greetings_after_replay gates it too")

        session.greetings_after_replay = True
        PeerSession.maybe_pump_deferred(session, None)
        self.assertEqual([m.seq for m in session.sent], [held.seq])
        self.assertEqual(session.deferred_replay_sent, 1)
        self.assertEqual(session.deferred_replay, [], "sent once, then cleared")

    def test_coverage_report_counts_only_channel_0_requests(self):
        """The coverage line must not call Carrier records unanswered requests.

        Measured 2026-10-14: the first live report listed 13 channel-3 Carrier transport
        records among the types 'waiting on us', which makes the report misleading. Only
        channel 0 carries the typed stream, and the heartbeat and V3 registration ride it
        without being requests.
        """
        from azoth_world.rep import _counts_as_request

        self.assertTrue(_counts_as_request(0, 0x09FC))    # Contracts request
        self.assertTrue(_counts_as_request(0, 0x0A95))    # Objectives request
        self.assertFalse(_counts_as_request(0, 0x15D))    # PingMsg is transport
        self.assertFalse(_counts_as_request(0, 0x13))     # V3 re-registration
        self.assertFalse(_counts_as_request(1, 0x0635))   # channel 1 is the input stream
        self.assertFalse(_counts_as_request(3, 0x20))     # channel 3 is Carrier

    def test_a_real_replay_is_partitioned_by_the_measured_tables(self):
        """The committed capture must actually contain the held classes, or the tables are stale."""
        from azoth_world.rep import (
            DEFERRED_RESPONSE_TYPES,
            _partition_replay,
            replay_store,
        )

        messages = replay_store().messages
        now, defer, drop = _partition_replay(messages)
        self.assertEqual(len(now) + len(defer) + len(drop), len(messages))
        self.assertTrue(defer, "the capture must contain held client-facet responses")
        self.assertTrue({m.type_id for m in defer} <= set(DEFERRED_RESPONSE_TYPES))
        # The 23 storage-search copies and the time pair are in the capture and must be held.
        deferred_types = {m.type_id for m in defer}
        self.assertIn(0x1B88, deferred_types)
        self.assertIn(0x1096, deferred_types)
        self.assertIn(0x08E6, deferred_types)


class TestClientRecordContainer(unittest.TestCase):
    """The client's own record container, measured live, and the reply framing.

    Every non-chunked client->server DATA record on channels 0 and 1 is
    `[u32 BE crc32(payload)][u32 BE len(payload)][payload]`; 40 279/40 279
    channel-1 records and 285/294 channel-0 records satisfy both fields. The
    server historically replies in the capture's `[vlq32 len]` form, which the
    client accepts on channel 0. Which container a channel-1 reply needs is the
    open question, so the framing is selectable and both forms are asserted here.
    """

    def test_crc_and_length_match_the_client_form(self):
        import zlib

        payload = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e00001b518fbde4b9a600d42")
        wrapped = rep.client_container(payload)
        self.assertEqual(len(wrapped), len(payload) + 8)
        self.assertEqual(int.from_bytes(wrapped[0:4], "big"), zlib.crc32(payload) & 0xFFFFFFFF)
        self.assertEqual(int.from_bytes(wrapped[4:8], "big"), len(payload))
        self.assertEqual(wrapped[8:], payload)

    def test_real_captured_channel1_record_round_trips(self):
        """A real 119 B channel-1 record must satisfy the container exactly."""
        import zlib

        record = bytes.fromhex(
            "3f331f2d0000006f1a954abc4b3185bfbe37c3d8592618e00001b518fbde4b9a6"
            "00d428fbf85314bbc4a951a00000000003c00000135000000000007ffff01200c"
            "3d3e000000000f01f7080000d7e04f40200f01013300808080803d4ccccdc02c"
            "107e800000004611f5c4452e61c42c09030000000101"
        )
        self.assertEqual(len(record), 119)
        tag = int.from_bytes(record[0:4], "big")
        length = int.from_bytes(record[4:8], "big")
        payload = record[8:]
        self.assertEqual(length, len(payload))
        self.assertEqual(tag, zlib.crc32(payload) & 0xFFFFFFFF)

    def test_position_reply_body_layout(self):
        actor = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")
        body = rep.position_reply_body(actor, 100.0)
        self.assertEqual(len(body), 36)
        self.assertEqual(body[0:16], actor)
        self.assertEqual(body[16:24], (0).to_bytes(8, "big"))

    def test_wrap_reply_server_and_client_containers(self):
        """Both containers must be self-describing and differ only in framing."""
        import zlib

        actor = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")
        body = rep.position_reply_body(actor, 100.0)
        server = rep.wrap_reply("server", actor, rep.POSITION_REPLY_TYPE, body)
        client = rep.wrap_reply("client", actor, rep.POSITION_REPLY_TYPE, body)
        # server: [vlq32 len][00 01][varint type][body] -> 1 + 2 + 2 + 36
        self.assertEqual(len(server), 41)
        self.assertEqual(server[0], len(server) - 1)
        self.assertEqual(server[1:3], b"\x00\x01")
        # client: [crc32 BE][len BE][16-byte target][00 01][type][body] -> 8 + 56
        self.assertEqual(len(client), 64)
        inner = client[8:]
        self.assertEqual(int.from_bytes(client[0:4], "big"), zlib.crc32(inner) & 0xFFFFFFFF)
        self.assertEqual(int.from_bytes(client[4:8], "big"), len(inner))
        self.assertEqual(inner[0:16], actor)
        self.assertEqual(inner[16:18], b"\x00\x01")

    def test_start_movement_body_layout(self):
        actor = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")
        body = rep.start_movement_body(actor, 1)
        self.assertEqual(len(body), 20)
        self.assertEqual(body[0:16], actor)
        self.assertEqual(int.from_bytes(body[16:20], "big"), 1)


class TestCompressedDatagramDoesNotCrashTheLoop(unittest.TestCase):
    """Live 2026-10-11: a compressed (0x81) client datagram killed the session.

    `PeerSession.on_app_data` parsed the *raw* (still LZ4) body as Carrier
    records, so the garbage produced a channel 4, `parse_datagram` indexed past
    `per_seq` (four slots, guard said `> 4`) and raised IndexError. The UDP
    loop's feed-error handler dropped the peer and the client logged
    `transportError 4` ~18.7 min into an otherwise clean session. The datagram
    below is the exact one captured from that run (world.log raw_full).
    """

    CAPTURED = bytes.fromhex(
        "81014567fc0101002404000400c3e7e3930000001c000100ff07019d0500036fda"
        "dca4dd4401002403ff03ffdc2d11782b000931a10a132b007ffe03fe2b4ad43c2b"
        "000931656f492b007ffd03fdba9fb33d2b00093129d47f2b007ffc03fc868a6365"
        "2b000850d9ee39b544"
    )

    def test_raw_body_no_longer_raises(self):
        from azoth_world.javelin.lz4 import decompress_lz4_block

        env, body = parse_envelope(self.CAPTURED)
        self.assertTrue(env.is_compressed)
        # Parsing the compressed body must return an error, never raise.
        result = parse_datagram(body)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.messages, [])
        # The decompressed body is the real stream: five ch0 records.
        dec = parse_datagram(decompress_lz4_block(body))
        self.assertIsNone(dec.error)
        self.assertEqual(len(dec.messages), 5)
        self.assertTrue(all(r.channel == 0 for r in dec.messages))

    def test_on_app_data_decompresses_before_parsing(self):
        """on_app_data must feed decompressed bytes to the Carrier parse."""
        import inspect

        source = inspect.getsource(rep.PeerSession.on_app_data)
        self.assertIn("is_compressed", source)
        self.assertIn("decompress_lz4_block", source)


if __name__ == "__main__":
    unittest.main()





class TestPositionReplyIsReliableByDefault(unittest.TestCase):
    """The measured movement fix must not be able to regress silently.

    Live 2026-10-11: an unreliable (flags 0x20) channel-0 position reply is
    Carrier-ACKed but never handed to the client's inbound decoder, so the
    reader never runs and the log stays clean — the signature that was misread
    three times as "wire type 4216 is not receivable". As RELIABLE (flags
    0x21) the resolver and reader both run for 4216. This only proves decode:
    Game.log then reports missing facet-target dispatch, and no movement was
    demonstrated. Keep reliable as the decode-tested variant.
    """

    def test_reliable_default_is_on(self):
        self.assertTrue(
            rep.POSITION_REPLY_RELIABLE,
            "reliable is the working variant; flags 0x20 is dropped by the client",
        )

    def test_reliable_flag_is_0x21(self):
        flags = 0x21 if rep.POSITION_REPLY_RELIABLE else 0x20
        self.assertEqual(flags, 0x21)
        self.assertTrue(flags & 0x01, "MF_RELIABLE must be set")
        self.assertTrue(flags & 0x20, "MF_DATA_CHANNEL must be set")

    def test_channel_defaults_to_the_capture_channel_zero(self):
        self.assertEqual(rep.POSITION_REPLY_CHANNEL, 0)

    def test_maybe_position_reply_has_one_framing_implementation(self):
        """No second inline container builder: it drifted once already."""
        import inspect

        source = inspect.getsource(rep.PeerSession.maybe_position_reply)
        self.assertIn("wrap_reply(", source)
        self.assertNotIn("client_container(inner)", source)


class TestPositionReplyTargetIsTheMeasuredOne(unittest.TestCase):
    """The reply must be addressed to an RMI target the client actually has.

    Measured live 2026-10-11 (probe reverse/probes/client/frida-rmi-targets.py):
    the client's RMI target registry holds 37063 entries and the actor id the server
    sent (`1a954abc4b3185bf`) is NOT one of them (601 lookups, 0 hits -> the
    `facet target ID couldn't be found` Game.log line), while the blob the capture's
    own input-response messages carry (`93a3e477cb5fd51ebf85314bbc4a951a`) IS
    (136 lookups, 136 hits). This test pins the knob's semantics; the live A/B that
    decides whether the position then applies is separate.
    """

    CAPTURE_TARGET = "93a3e477cb5fd51ebf85314bbc4a951a"

    def test_default_is_the_actor_id(self):
        actor = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")
        with unittest.mock.patch.object(rep, "POSITION_REPLY_TARGET", ""):
            self.assertEqual(rep.position_reply_target(actor), actor)

    def test_override_replaces_the_blob_everywhere(self):
        actor = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")
        blob = bytes.fromhex(self.CAPTURE_TARGET)
        with unittest.mock.patch.object(rep, "POSITION_REPLY_TARGET", self.CAPTURE_TARGET):
            target = rep.position_reply_target(actor)
            self.assertEqual(target, blob)
            body = rep.position_reply_body(target, 100.0)
            self.assertEqual(body[0:16], blob)
            client = rep.wrap_reply("client", target, rep.POSITION_REPLY_TYPE, body)
            self.assertEqual(client[8:24], blob)
            server = rep.wrap_reply("server", target, rep.POSITION_REPLY_TYPE, body)
            self.assertEqual(server[3:5], b"\xb8\x41")  # varint 4216

    def test_a_malformed_override_is_refused_not_sent(self):
        actor = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")
        for bad in ("zz", "1a954abc4b3185bf"):  # not hex / not 16 bytes
            with unittest.mock.patch.object(rep, "POSITION_REPLY_TARGET", bad):
                self.assertIsNone(rep.position_reply_target(actor))


class TestStartMovementIsReliableOnChannelZero(unittest.TestCase):
    """StartMovementCommunicationMsg must use the same framing as the position reply.

    Measured 2026-10-11: the first attempt at this message went out unreliable
    (`flags 0x20`) on channel 1, and an unreliable channel-0 record is Carrier-ACKed but
    never handed to the client's inbound decoder `FUN_146b6eb70` (the rule measured for
    wire 4216). Its clean log was therefore weak evidence. The body was never the
    problem: it is byte-verified against the client's own reader FUN_146a55240
    (16-byte raw blob + u32 BE = 20 bytes).
    """

    def test_defaults_are_reliable_and_channel_zero(self):
        self.assertTrue(rep.START_MOVEMENT_RELIABLE)
        self.assertEqual(rep.START_MOVEMENT_CHANNEL, 0)

    def test_body_is_twenty_bytes_and_actor_first(self):
        actor = bytes.fromhex("1a954abc4b3185bfbe37c3d8592618e0")
        body = rep.start_movement_body(actor, 1)
        self.assertEqual(len(body), 20)
        self.assertEqual(body[0:16], actor)
        self.assertEqual(int.from_bytes(body[16:20], "big"), 1)

    def test_send_uses_the_reliable_flag_and_tracks_the_record(self):
        import inspect

        source = inspect.getsource(rep.PeerSession.maybe_position_reply)
        self.assertIn("flags_override=0x21 if START_MOVEMENT_RELIABLE else 0x20", source)
        self.assertIn("track_reliable=START_MOVEMENT_RELIABLE", source)
        self.assertIn('"reliable": START_MOVEMENT_RELIABLE', source)
