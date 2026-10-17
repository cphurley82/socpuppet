"""The Ethernet frames Python sends to firmware and reads back.

🎓 A frame on an Ethernet is the two ends' hardware addresses (MACs), a
type, and a packet: here an ARP request, which asks who has an IPv4
address, or an IPv4 packet with a UDP datagram or a ping in it. `ethernet` makes and
reads them with dpkt; these tests read what it makes with dpkt as well,
and check the sums by adding them up again by hand.
"""

import dpkt

import ethernet

ME = ethernet.mac("02:00:00:00:00:02")
MY_ADDRESS = ethernet.ipv4("192.0.2.2")
IT = ethernet.mac("02:00:5e:00:53:01")
ITS_ADDRESS = ethernet.ipv4("192.0.2.1")


class TestWhenPythonAsksWhoHasAnAddress:
    def test_the_request_is_broadcast_and_says_who_asks(self):
        frame = dpkt.ethernet.Ethernet(
            ethernet.arp_request(
                sender=ME, sender_address=MY_ADDRESS, target=ITS_ADDRESS
            )
        )

        assert frame.dst == ethernet.BROADCAST
        assert frame.type == dpkt.ethernet.ETH_TYPE_ARP
        assert (frame.arp.op, frame.arp.sha, frame.arp.spa, frame.arp.tpa) == (
            dpkt.arp.ARP_OP_REQUEST,
            ME,
            MY_ADDRESS,
            ITS_ADDRESS,
        )


class TestWhenFramesHoldAnAnswerToThatRequest:
    def test_the_answer_gives_the_mac_that_has_the_address(self):
        frames = [
            an_arp(dpkt.arp.ARP_OP_REQUEST, IT, ITS_ADDRESS, MY_ADDRESS),
            an_arp(dpkt.arp.ARP_OP_REPLY, IT, ITS_ADDRESS, MY_ADDRESS),
        ]

        assert ethernet.who_has(frames, ITS_ADDRESS) == IT

    def test_no_answer_for_another_address_gives_none(self):
        frames = [an_arp(dpkt.arp.ARP_OP_REPLY, IT, MY_ADDRESS, ITS_ADDRESS)]

        assert ethernet.who_has(frames, ITS_ADDRESS) is None


class TestWhenPythonSendsADatagram:
    def test_its_lengths_and_both_sums_are_right(self):
        frame = dpkt.ethernet.Ethernet(
            ethernet.udp(
                source=(ME, MY_ADDRESS, 5000),
                destination=(IT, ITS_ADDRESS, 4242),
                payload=b"spam",
            )
        )
        ip = frame.ip

        assert (ip.len, ip.udp.ulen, ip.udp.data) == (32, 12, b"spam")
        # A header with its sum right adds up to all ones (RFC 1071), and a
        # UDP datagram's sum covers a pseudo-header of the addresses too.
        pseudo = ip.src + ip.dst + bytes([0, ip.p]) + ip.udp.ulen.to_bytes(2)
        assert added_up(bytes(ip)[: ip.hl * 4]) == 0xFFFF
        assert added_up(pseudo + bytes(ip.udp)) == 0xFFFF


class TestWhenFramesHoldDatagramsToSeveralPorts:
    def test_the_payloads_to_one_port_are_picked_out_in_order(self):
        frames = [
            ethernet.udp(
                source=(IT, ITS_ADDRESS, 4242),
                destination=(ME, MY_ADDRESS, port),
                payload=payload,
            )
            for port, payload in [
                (5000, b"spam"),
                (6000, b"eggs"),
                (5000, b"ham"),
            ]
        ]

        assert ethernet.udp_payloads(frames, port=5000) == [b"spam", b"ham"]


class TestWhenANeighbourHearsAnArpRequestForItsAddress:
    def test_it_answers_with_its_mac_to_whoever_asked(self):
        neighbour = ethernet.Neighbour(mac=ME, address=MY_ADDRESS)

        [answer] = neighbour.answers(
            [an_arp(dpkt.arp.ARP_OP_REQUEST, IT, ITS_ADDRESS, MY_ADDRESS)]
        )

        assert ethernet.who_has([answer], MY_ADDRESS) == ME
        assert dpkt.ethernet.Ethernet(answer).dst == IT

    def test_it_keeps_quiet_about_another_address(self):
        neighbour = ethernet.Neighbour(mac=ME, address=MY_ADDRESS)

        assert (
            neighbour.answers(
                [an_arp(dpkt.arp.ARP_OP_REQUEST, IT, ITS_ADDRESS, ITS_ADDRESS)]
            )
            == []
        )


class TestWhenANeighbourIsPinged:
    def test_it_echoes_the_request_back_with_its_sums_right(self):
        neighbour = ethernet.Neighbour(mac=ME, address=MY_ADDRESS)

        [answer] = neighbour.answers([a_ping(to=MY_ADDRESS)])

        frame = dpkt.ethernet.Ethernet(answer)
        ip = frame.ip
        echo = ip.icmp
        assert (frame.dst, ip.src, ip.dst) == (IT, MY_ADDRESS, ITS_ADDRESS)
        assert (echo.type, echo.data.id, echo.data.seq, echo.data.data) == (
            dpkt.icmp.ICMP_ECHOREPLY,
            7,
            1,
            b"spam",
        )
        assert added_up(bytes(ip)[: ip.hl * 4]) == 0xFFFF
        assert added_up(bytes(echo)) == 0xFFFF

    def test_it_keeps_quiet_about_a_ping_to_another_address(self):
        neighbour = ethernet.Neighbour(mac=ME, address=MY_ADDRESS)

        assert neighbour.answers([a_ping(to=ITS_ADDRESS)]) == []


def a_ping(*, to):
    """An echo request from `IT` to the address `to`: id 7, sequence 1."""
    return bytes(
        dpkt.ethernet.Ethernet(
            dst=ME,
            src=IT,
            type=dpkt.ethernet.ETH_TYPE_IP,
            data=dpkt.ip.IP(
                src=ITS_ADDRESS,
                dst=to,
                p=dpkt.ip.IP_PROTO_ICMP,
                data=dpkt.icmp.ICMP(
                    type=dpkt.icmp.ICMP_ECHO,
                    data=dpkt.icmp.ICMP.Echo(id=7, seq=1, data=b"spam"),
                ),
            ),
        )
    )


def an_arp(op, sender, sender_address, target_address):
    return bytes(
        dpkt.ethernet.Ethernet(
            dst=ethernet.BROADCAST,
            src=sender,
            type=dpkt.ethernet.ETH_TYPE_ARP,
            data=dpkt.arp.ARP(
                op=op,
                sha=sender,
                spa=sender_address,
                tha=bytes(6),
                tpa=target_address,
            ),
        )
    )


def added_up(data):
    """The ones'-complement sum of `data` in 16-bit words, as the IPv4 and
    UDP checksums are worked out (RFC 1071)."""
    if len(data) % 2:
        data += b"\0"
    total = sum(int.from_bytes(data[i : i + 2]) for i in range(0, len(data), 2))
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return total
