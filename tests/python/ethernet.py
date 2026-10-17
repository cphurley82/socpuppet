"""Ethernet frames for 🧵 Python at the far end of 🎭 the virtio network
device, made and read with dpkt.

A frame is `bytes`, as `PlacedNet.send` takes and `PlacedNet.received`
gives. dpkt works out the lengths and sums as it packs a frame, and sets
nothing it is not asked to: the rest is zeros, or dpkt's defaults (an
IPv4 packet lives 64 hops).
"""

from collections.abc import Iterable

import dpkt

#: The MAC every station on the wire takes a frame for.
BROADCAST = b"\xff" * 6

#: Where a station is: its MAC, its IPv4 address and a UDP port.
Station = tuple[bytes, bytes, int]


def mac(text: str) -> bytes:
    """`02:00:5e:00:53:01` as six bytes."""
    return bytes.fromhex(text.replace(":", ""))


def ipv4(text: str) -> bytes:
    """`192.0.2.1` as four bytes."""
    return bytes(int(part) for part in text.split("."))


def arp_request(
    *, sender: bytes, sender_address: bytes, target: bytes
) -> bytes:
    """A broadcast that asks who has the IPv4 address `target`.

    `sender` and `sender_address` are the MAC and the address of whoever
    asks, which the answer is sent to.
    """
    return bytes(
        dpkt.ethernet.Ethernet(
            dst=BROADCAST,
            src=sender,
            type=dpkt.ethernet.ETH_TYPE_ARP,
            data=dpkt.arp.ARP(
                op=dpkt.arp.ARP_OP_REQUEST,
                sha=sender,
                spa=sender_address,
                tha=bytes(6),
                tpa=target,
            ),
        )
    )


def who_has(frames: Iterable[bytes], address: bytes) -> bytes | None:
    """The MAC that an ARP reply among `frames` says has `address`."""
    for frame in frames:
        arp = dpkt.ethernet.Ethernet(frame).data
        if (
            isinstance(arp, dpkt.arp.ARP)
            and arp.op == dpkt.arp.ARP_OP_REPLY
            and arp.spa == address
        ):
            return bytes(arp.sha)
    return None


def udp(*, source: Station, destination: Station, payload: bytes) -> bytes:
    """A UDP datagram with `payload`, in an IPv4 packet, in a frame."""
    (source_mac, source_address, source_port) = source
    (destination_mac, destination_address, destination_port) = destination
    datagram = dpkt.udp.UDP(
        sport=source_port, dport=destination_port, data=payload
    )
    # dpkt works out an IPv4 packet's length as it packs it, and not a UDP
    # datagram's.
    datagram.ulen = len(datagram)
    packet = dpkt.ip.IP(
        src=source_address,
        dst=destination_address,
        p=dpkt.ip.IP_PROTO_UDP,
        data=datagram,
    )
    return bytes(
        dpkt.ethernet.Ethernet(
            dst=destination_mac,
            src=source_mac,
            type=dpkt.ethernet.ETH_TYPE_IP,
            data=packet,
        )
    )


def udp_payloads(frames: Iterable[bytes], *, port: int) -> list[bytes]:
    """The payloads of the UDP datagrams among `frames` sent to `port`."""
    payloads = []
    for frame in frames:
        packet = dpkt.ethernet.Ethernet(frame).data
        datagram = packet.data if isinstance(packet, dpkt.ip.IP) else None
        if isinstance(datagram, dpkt.udp.UDP) and datagram.dport == port:
            payloads.append(bytes(datagram.data))
    return payloads
