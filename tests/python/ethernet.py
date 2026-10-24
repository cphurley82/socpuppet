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


def tcp(
    *,
    source: Station,
    destination: Station,
    flags: int,
    seq: int,
    ack: int = 0,
    payload: bytes = b"",
) -> bytes:
    """A TCP segment with `payload`, in an IPv4 packet, in a frame.

    `flags` are dpkt's, such as `dpkt.tcp.TH_SYN | dpkt.tcp.TH_ACK`.
    """
    (source_mac, source_address, source_port) = source
    (destination_mac, destination_address, destination_port) = destination
    segment = dpkt.tcp.TCP(
        sport=source_port,
        dport=destination_port,
        seq=seq,
        ack=ack,
        flags=flags,
        data=payload,
    )
    packet = dpkt.ip.IP(
        src=source_address,
        dst=destination_address,
        p=dpkt.ip.IP_PROTO_TCP,
        data=segment,
    )
    return bytes(
        dpkt.ethernet.Ethernet(
            dst=destination_mac,
            src=source_mac,
            type=dpkt.ethernet.ETH_TYPE_IP,
            data=packet,
        )
    )


def tcp_segments(frames: Iterable[bytes], *, port: int) -> list[dpkt.tcp.TCP]:
    """The TCP segments among `frames` sent to `port`, in order."""
    segments = []
    for frame in frames:
        packet = dpkt.ethernet.Ethernet(frame).data
        segment = packet.data if isinstance(packet, dpkt.ip.IP) else None
        if isinstance(segment, dpkt.tcp.TCP) and segment.dport == port:
            segments.append(segment)
    return segments


def echo_request(
    *, source: Station, destination: Station, payload: bytes
) -> bytes:
    """A ping: an ICMP echo request with `payload`, in a packet, in a frame.

    The stations' ports are not used: ICMP has none.
    """
    (source_mac, source_address, _) = source
    (destination_mac, destination_address, _) = destination
    packet = dpkt.ip.IP(
        src=source_address,
        dst=destination_address,
        p=dpkt.ip.IP_PROTO_ICMP,
        data=dpkt.icmp.ICMP(
            type=dpkt.icmp.ICMP_ECHO, data=dpkt.icmp.ICMP.Echo(data=payload)
        ),
    )
    return bytes(
        dpkt.ethernet.Ethernet(
            dst=destination_mac,
            src=source_mac,
            type=dpkt.ethernet.ETH_TYPE_IP,
            data=packet,
        )
    )


def echo_replies(frames: Iterable[bytes]) -> list[bytes]:
    """The payloads of the ICMP echo replies among `frames`."""
    payloads = []
    for frame in frames:
        packet = dpkt.ethernet.Ethernet(frame).data
        message = packet.data if isinstance(packet, dpkt.ip.IP) else None
        if (
            isinstance(message, dpkt.icmp.ICMP)
            and message.type == dpkt.icmp.ICMP_ECHOREPLY
        ):
            payloads.append(bytes(message.data.data))
    return payloads


def udp_payloads(frames: Iterable[bytes], *, port: int) -> list[bytes]:
    """The payloads of the UDP datagrams among `frames` sent to `port`."""
    payloads = []
    for frame in frames:
        packet = dpkt.ethernet.Ethernet(frame).data
        datagram = packet.data if isinstance(packet, dpkt.ip.IP) else None
        if isinstance(datagram, dpkt.udp.UDP) and datagram.dport == port:
            payloads.append(bytes(datagram.data))
    return payloads


def dhcp_discover(sender: bytes) -> bytes:
    """A broadcast from `sender`, a MAC, asking any DHCP server for an
    address."""
    request = dpkt.dhcp.DHCP(
        op=dpkt.dhcp.DHCP_OP_REQUEST,
        chaddr=sender + bytes(10),
        opts=((dpkt.dhcp.DHCP_OPT_MSGTYPE, bytes([dpkt.dhcp.DHCPDISCOVER])),),
    )
    return udp(
        source=(sender, ipv4("0.0.0.0"), 68),
        destination=(BROADCAST, ipv4("255.255.255.255"), 67),
        payload=bytes(request),
    )


def dhcp_offers(frames: Iterable[bytes]) -> list[bytes]:
    """The addresses offered by the DHCP offers among `frames`."""
    offers = []
    for payload in udp_payloads(frames, port=68):
        answer = dpkt.dhcp.DHCP(payload)
        if (dpkt.dhcp.DHCP_OPT_MSGTYPE, bytes([dpkt.dhcp.DHCPOFFER])) in list(
            answer.opts
        ):
            offers.append(answer.yiaddr.to_bytes(4, "big"))
    return offers


class Neighbour:
    """🎭 A host on the wire that answers ARP and ping, and nothing else.

    It stands for the machine next to the firmware on a LAN: asked who has
    its `address`, it says its `mac`, and an echo request to it comes back
    as an echo reply with the same identifier, sequence and data.
    """

    def __init__(self, *, mac: bytes, address: bytes) -> None:
        self.mac = mac
        self.address = address

    def answers(self, frames: Iterable[bytes]) -> list[bytes]:
        """What it sends back to `frames`, one answer each at most."""
        answers = []
        for frame in frames:
            heard = dpkt.ethernet.Ethernet(frame)
            answer = self._answer_arp(heard) or self._answer_ping(heard)
            if answer is not None:
                answers.append(answer)
        return answers

    def _answer_arp(self, heard: dpkt.ethernet.Ethernet) -> bytes | None:
        arp = heard.data
        if not (
            isinstance(arp, dpkt.arp.ARP)
            and arp.op == dpkt.arp.ARP_OP_REQUEST
            and arp.tpa == self.address
        ):
            return None
        return bytes(
            dpkt.ethernet.Ethernet(
                dst=arp.sha,
                src=self.mac,
                type=dpkt.ethernet.ETH_TYPE_ARP,
                data=dpkt.arp.ARP(
                    op=dpkt.arp.ARP_OP_REPLY,
                    sha=self.mac,
                    spa=self.address,
                    tha=arp.sha,
                    tpa=arp.spa,
                ),
            )
        )

    def _answer_ping(self, heard: dpkt.ethernet.Ethernet) -> bytes | None:
        packet = heard.data
        if not (
            isinstance(packet, dpkt.ip.IP)
            and packet.dst == self.address
            and isinstance(packet.data, dpkt.icmp.ICMP)
            and packet.data.type == dpkt.icmp.ICMP_ECHO
        ):
            return None
        return bytes(
            dpkt.ethernet.Ethernet(
                dst=heard.src,
                src=self.mac,
                type=dpkt.ethernet.ETH_TYPE_IP,
                data=dpkt.ip.IP(
                    src=self.address,
                    dst=packet.src,
                    p=dpkt.ip.IP_PROTO_ICMP,
                    data=dpkt.icmp.ICMP(
                        type=dpkt.icmp.ICMP_ECHOREPLY,
                        data=packet.data.data,
                    ),
                ),
            )
        )
