"""🔌 `sp.EthernetCable`: a network card plugged into this machine's network.

The cable is a far end the platform is pumped with (`socpuppet.pump`):
what the firmware sends on the card goes to libslirp, and what slirp
sends comes in on the card. Here the firmware is 🧵 Python's driver of
the 🎭 virtio network device, on a scripted host.

    host ─▶ bus ─┬─▶ ram
     ▲      ▲    └─▶ net.cpu ─ ─ ─ cable ─ ─ ─▶ slirp ─▶ this machine
     │      └──────── net.dma
     └─────────────── net.irq
"""

import socket
import time

import pytest

import ethernet
import socpuppet as sp
from cable_area import needs_cable
from sockets import a_free_port
from socpuppet import slirp
from socpuppet.pump import pump

pytestmark = [pytest.mark.platform, needs_cable]

RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
NET_BASE = 0x1000_1000
#: The card's MAC.
CARD_MAC = 0x0200_5E00_5301
#: How long, on the wall, a test waits for what it waits for, so that
#: something that never comes fails the test and does not hang it.
PATIENCE = 10.0


class TestWhenTheFirmwareAsksForAnAddressOverTheCable:
    def test_it_is_offered_one_by_slirp(self):
        heard = []
        platform, net = a_host_whose_firmware_sends(
            ethernet.dhcp_discover(CARD_MAC.to_bytes(6)), heard
        )

        with sp.EthernetCable(net) as cable:
            pumped_until(platform, cable, lambda: ethernet.dhcp_offers(heard))

        assert ethernet.dhcp_offers(heard) == [ethernet.ipv4("10.0.2.15")]


class TestWhenAProgramHereConnectsToAPortForwardedOverTheCable:
    def test_the_firmware_is_asked_to_connect_on_the_port_it_is_forwarded_to(
        self,
    ):
        heard = []
        platform, net = a_host_whose_firmware_sends(an_introduction(), heard)
        port = a_free_port()

        with (
            sp.EthernetCable(net, forward={port: 22}) as cable,
            socket.create_connection(("127.0.0.1", port)),
        ):
            assert pumped_until(
                platform,
                cable,
                lambda: ethernet.tcp_segments(heard, port=22),
            )


class TestWhenAPortToForwardOverTheCableIsTaken:
    def test_the_cable_is_refused_and_the_ports_forwarded_before_are_freed(
        self,
    ):
        _, net = a_host_whose_firmware_sends(an_introduction(), [])
        forwarded = a_free_port()

        with (
            socket.create_server(("127.0.0.1", 0)) as taken,
            pytest.raises(OSError, match="is it taken"),
        ):
            sp.EthernetCable(
                net, forward={forwarded: 22, taken.getsockname()[1]: 23}
            )

        with socket.create_server(("127.0.0.1", forwarded)):
            pass


def an_introduction() -> bytes:
    """🎓 What a card that has just come up sends: who has its gateway's
    address? So slirp learns the card's MAC, to send it frames."""
    return ethernet.arp_request(
        sender=CARD_MAC.to_bytes(6),
        sender_address=slirp.GUEST.packed,
        target=slirp.GATEWAY.packed,
    )


def a_host_whose_firmware_sends(frame: bytes, heard: list[bytes]):
    """A scripted host whose firmware sends `frame` on its network device,
    and then puts each frame it receives in `heard`, built.

    Returns the platform and the device at its place.
    """

    def script():
        net = sp.VirtioNetHost(registers=NET_BASE, memory=RAM_BASE)
        yield from net.start()
        yield from net.send_frame(frame)
        while True:
            heard.append((yield from net.receive_frame()))

    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=RAM_SIZE))
    net = platform.add("net", sp.VirtioNet(mac=CARD_MAC))
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(net.cpu, base=NET_BASE)
    platform.connect(net.dma, bus.add_input())
    platform.connect(net.irq, cpu.irq)
    platform.build()
    return platform, net


def pumped_until(platform, cable, condition) -> bool:
    """Pump `platform` with `cable` until `condition`, or PATIENCE runs out.

    Returns whether `condition` came true.
    """
    started = time.monotonic()
    pump(
        platform,
        far_ends=[cable],
        until=lambda: (
            bool(condition()) or time.monotonic() - started > PATIENCE
        ),
    )
    return bool(condition())
