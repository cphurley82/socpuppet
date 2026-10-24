"""🔌 What socpuppet relies on of libslirp, through `socpuppet.slirp`.

libslirp is the network stack of QEMU's user-mode network: it answers a
guest's frames as a router and this machine would, with sockets of this
machine's own, so no root is needed. Here the test is the guest, and
plays its frames by hand with dpkt, with no platform at all.

    test (the guest) ── frames ──▶ Slirp ── sockets ──▶ this machine
                     ◀── frames ──
"""

import re
import socket
import time

import dpkt
import pytest

import ethernet
import socpuppet as sp
from cable_area import needs_cable
from socpuppet import slirp
from this_machine import PATIENCE

#: The guest's MAC: that of the 🎭 virtio network device.
GUEST_MAC = ethernet.mac("02:00:5e:00:53:01")


@needs_cable
class TestWhenLibslirpIsInstalled:
    def test_its_version_is_read(self):
        assert re.fullmatch(r"\d+\.\d+\.\d+", slirp.version())


class TestWhereLibslirpIsLookedFor:
    def test_homebrews_place_on_an_apple_silicon_mac_is_among_them(self):
        # 🎓 Which is not where a Mac looks for libraries.
        assert "/opt/homebrew/lib/libslirp.0.dylib" in slirp.places()


class TestWhenLibslirpIsNotInstalled:
    def test_using_it_fails_saying_how_to_install_it(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            slirp, "places", lambda: [str(tmp_path / "libslirp.so.0")]
        )

        with pytest.raises(sp.SlirpUnavailable, match=r"doctor\.py cable"):
            slirp.version()


@needs_cable
class TestWhenTheGuestAsksForAnAddress:
    def test_it_is_offered_the_first_of_slirps_network(self):
        sent = []
        with slirp.Slirp(send=sent.append) as stack:
            stack.input(ethernet.dhcp_discover(GUEST_MAC))

        assert ethernet.dhcp_offers(sent) == [ethernet.ipv4("10.0.2.15")]


@needs_cable
class TestWhenTheGuestAsksWhoHasItsGatewaysAddress:
    def test_slirp_answers_for_it(self):
        sent = []
        with slirp.Slirp(send=sent.append) as stack:
            stack.input(
                ethernet.arp_request(
                    sender=GUEST_MAC,
                    sender_address=ethernet.ipv4("10.0.2.15"),
                    target=ethernet.ipv4("10.0.2.2"),
                )
            )

        assert ethernet.who_has(sent, ethernet.ipv4("10.0.2.2")) is not None


@needs_cable
class TestWhenAProgramHereConnectsToAForwardedPort:
    def test_the_guest_is_asked_to_connect_and_bytes_flow_both_ways(self):
        sent: list[bytes] = []
        with slirp.Slirp(send=sent.append) as stack:
            guest = Guest(stack, sent)
            port = a_free_port()
            stack.forward(port, 22)

            with socket.create_connection(("127.0.0.1", port)) as program:
                guest.accept(guest.asked_to_connect(port=22))
                program.sendall(b"spam")
                assert guest.received(b"spam")
                guest.send(b"eggs")
                program.settimeout(PATIENCE)

                assert program.recv(100) == b"eggs"


@needs_cable
class TestWhenAPortToForwardIsTakenAlready:
    def test_forwarding_it_is_refused_naming_it(self):
        with (
            socket.create_server(("127.0.0.1", 0)) as taken,
            slirp.Slirp(send=lambda frame: None) as stack,
        ):
            port = taken.getsockname()[1]

            with pytest.raises(OSError, match=f"port {port} "):
                stack.forward(port, 22)


@needs_cable
class TestWhenSlirpIsClosedTwice:
    def test_the_second_close_does_nothing(self):
        stack = slirp.Slirp(send=lambda frame: None)
        stack.close()

        stack.close()


class Guest:
    """🎭 The guest at the far end of `stack`, with TCP played by hand.

    `sent` is where the frames slirp sends the guest are put. It introduces
    itself first, as a guest that has just come up does, asking who has
    its gateway's address: so slirp learns its MAC, and it learns slirp's.
    It accepts one connection, and keeps that connection's numbers.
    """

    def __init__(self, stack: slirp.Slirp, sent: list[bytes]) -> None:
        self._stack = stack
        self._sent = sent
        stack.input(
            ethernet.arp_request(
                sender=GUEST_MAC,
                sender_address=slirp.GUEST.packed,
                target=slirp.GATEWAY.packed,
            )
        )
        self._slirp_mac = ethernet.who_has(sent, slirp.GATEWAY.packed)
        self._seq = 1000
        self._ack = 0
        self._port = 0
        self._here: ethernet.Station
        self._there: ethernet.Station

    def asked_to_connect(self, *, port: int) -> dpkt.tcp.TCP:
        """The SYN slirp sends to `port`, once it has been sent."""
        assert polled_until(self._stack, lambda: self._segments_to(port))
        (syn,) = self._segments_to(port)
        assert syn.flags & dpkt.tcp.TH_SYN
        return syn

    def accept(self, syn: dpkt.tcp.TCP) -> None:
        """Answer `syn` with a SYN-ACK."""
        self._port = syn.dport
        self._here = (GUEST_MAC, slirp.GUEST.packed, syn.dport)
        self._there = (self._slirp_mac, slirp.GATEWAY.packed, syn.sport)
        self._ack = syn.seq + 1
        self._segment(dpkt.tcp.TH_SYN | dpkt.tcp.TH_ACK)
        self._seq += 1

    def received(self, payload: bytes) -> bool:
        """Whether `payload` comes on the connection within PATIENCE."""
        if not polled_until(self._stack, lambda: payload in self._payloads()):
            return False
        self._ack += len(payload)
        return True

    def send(self, payload: bytes) -> None:
        """Send `payload` on the connection."""
        self._segment(dpkt.tcp.TH_ACK | dpkt.tcp.TH_PUSH, payload)
        self._seq += len(payload)

    def _segment(self, flags: int, payload: bytes = b"") -> None:
        self._stack.input(
            ethernet.tcp(
                source=self._here,
                destination=self._there,
                flags=flags,
                seq=self._seq,
                ack=self._ack,
                payload=payload,
            )
        )

    def _payloads(self) -> bytes:
        segments = self._segments_to(self._port)
        return b"".join(bytes(each.data) for each in segments)

    def _segments_to(self, port: int) -> list[dpkt.tcp.TCP]:
        return ethernet.tcp_segments(self._sent, port=port)


def a_free_port() -> int:
    """A TCP port of this machine's that nothing listens on, just now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def polled_until(stack: slirp.Slirp, condition) -> bool:
    """Poll `stack` until `condition`, or PATIENCE runs out.

    Returns whether `condition` came true.
    """
    deadline = time.monotonic() + PATIENCE
    while not condition() and (left := deadline - time.monotonic()) > 0:
        stack.poll(left)
    return bool(condition())
