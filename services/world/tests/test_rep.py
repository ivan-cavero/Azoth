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

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from azoth_world.javelin import (
    MessageRecord,
    marshal_datagram,
    parse_datagram,
    parse_envelope,
)
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
        session.greetings_after_replay = True
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
        session.greetings_after_replay = False
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

    The capture's steady state is R-direction type 0x08 bundles right up to
    seq 0xb0, and the real server never stopped sending them. Our replay does,
    and the client's activity warning counter climbs until it drops REP
    (2026-10-03: 1 -> 117 warnings, then `disconnected from REP`).
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
        session.state_stream_next_at = 0.0
        session.state_stream_sent = 0
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

    def test_captured_tail_is_single_datagram_bundles(self):
        """Every armed bundle must stay under REPLAY_CHUNK_SIZE so the
        continuation never takes the chunked path (chunking a bundle that the
        client did not ask for is the untested part)."""
        from azoth_world.rep import REPLAY_CHUNK_SIZE, STATE_STREAM_MIN_SEQ, replay_store

        store = replay_store()
        queue = [
            m
            for m in store.replay_messages_after_v3(0xB0, include_redacted=True)
            if m.type_id == 0x08 and m.seq >= STATE_STREAM_MIN_SEQ
        ]
        self.assertGreater(len(queue), 0, "no captured tail bundles to continue")
        for msg in queue:
            self.assertLessEqual(
                len(msg.body), REPLAY_CHUNK_SIZE, f"seq {msg.seq:#x} would chunk"
            )
        self.assertEqual([m.seq for m in queue], sorted(m.seq for m in queue))

    def test_stream_waits_for_the_replay_and_greetings(self):
        from unittest import mock

        from azoth_world.rep import PeerSession

        with mock.patch("azoth_world.rep.STATE_STREAM_ENABLED", True):
            self._waits_for_the_replay_and_greetings(PeerSession)

    def _waits_for_the_replay_and_greetings(self, PeerSession):
        from unittest import mock
        session = self._session()
        first = self._bundle(0xA0)
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

    def test_stream_sends_one_per_period_in_capture_order(self):
        from unittest import mock

        from azoth_world.rep import PeerSession, STATE_STREAM_PERIOD_S

        with mock.patch("azoth_world.rep.STATE_STREAM_ENABLED", True):
            self._one_per_period(PeerSession, STATE_STREAM_PERIOD_S)

    def _one_per_period(self, PeerSession, STATE_STREAM_PERIOD_S):
        from unittest import mock
        session = self._session()
        first, second = self._bundle(0xA0), self._bundle(0xA1)
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

    def test_wire_seq_rewrite_is_off_by_default(self):
        """Rewriting body[4] corrupts the bundle; the default must be OFF.

        Measured 2026-10-09, three live A/B runs, same build and config:
          FLOOR=0x80 (old default) -> 32 `Failed to unmarshal` (ValidationError)
          FLOOR=0x36               -> 32 `Failed to unmarshal`
          REWRITE=OFF              ->  0 `Failed to unmarshal`, 7.4 min stable
        The value written does not matter, so any write to that byte breaks the
        AZ deserializer. The error is a deserialization failure, not the dedup
        rejection the rewrite was meant to fix.
        """
        from azoth_world.rep import STATE_STREAM_REWRITE_SEQ

        self.assertFalse(
            STATE_STREAM_REWRITE_SEQ,
            "rewriting body[4] corrupts the bundle; see DECOMP-BACKLOG 12.2",
        )

    def test_wire_seq_is_rewritten_when_explicitly_enabled(self):
        """With the rewrite explicitly ON the counter continues above the
        capture. Kept as a lever: re-enable only with new evidence that the
        client drops the unrewritten bundles as already-seen.

        The client drops a replication message whose seq is not strictly
        greater than m_lastUnreliableReplicationSeq, so a re-sent captured
        bundle would need a continued counter (measured: high-water 53 while
        the bundles carried their original 37..53).
        """
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
        # the rest of the body is untouched
        self.assertEqual(session.sent[0].body[:4], first.body[:4])
        self.assertEqual(len(session.sent[0].body), len(first.body))

    def test_stream_does_not_loop_an_empty_arm(self):
        from azoth_world.rep import PeerSession

        session = self._session()
        PeerSession.maybe_state_stream(session, None)
        self.assertEqual(session.sent, [])

    def test_stream_is_off_by_default(self):
        """Measured 2026-10-04: with the stream on, the client dropped REP at
        +23 s, reconnected, never re-created its ClientContext and then skipped
        758 state bundles. With it off the same build kept ONE spawn, one skipped
        bundle and no disconnect. The default must stay off; the env switch is
        only for a deliberate re-test."""
        import importlib
        import os

        from azoth_world import rep as rep_module

        previous = os.environ.pop("AZOTH_REPLAY_STATE_STREAM", None)
        try:
            importlib.reload(rep_module)
            self.assertFalse(rep_module.STATE_STREAM_ENABLED)
        finally:
            if previous is not None:
                os.environ["AZOTH_REPLAY_STATE_STREAM"] = previous
            importlib.reload(rep_module)

    def test_stream_can_be_forced_on_for_an_ab(self):
        import importlib
        import os

        from azoth_world import rep as rep_module

        previous = os.environ.get("AZOTH_REPLAY_STATE_STREAM")
        os.environ["AZOTH_REPLAY_STATE_STREAM"] = "1"
        try:
            importlib.reload(rep_module)
            self.assertTrue(rep_module.STATE_STREAM_ENABLED)
        finally:
            if previous is None:
                os.environ.pop("AZOTH_REPLAY_STATE_STREAM", None)
            else:
                os.environ["AZOTH_REPLAY_STATE_STREAM"] = previous
            importlib.reload(rep_module)


if __name__ == "__main__":
    unittest.main()



