"""Reading UCIe's sideband packets, as a trace of a link carries them."""

import struct

import pytest

from socpuppet import ucie
from socpuppet.trace import TraceRecord


def a_packet(header: int, data: bytes = b"") -> bytes:
    """The bytes of a packet with `header` and whatever data it carries."""
    return struct.pack("<Q", header) + data


class TestWhenASidebandPacketIsRead:
    def test_each_field_is_where_ucie_has_it(self):
        # opcode [4:0], msgcode [21:14], srcid [31:29], msgsubcode [39:32],
        # msginfo [55:40], dstid [58:56], cp [62], dp [63].
        packet = ucie.SidebandPacket.from_bytes(
            a_packet(
                0x4212_3402_2029_401B, struct.pack("<Q", 0x0123_4567_89AB_CDEF)
            )
        )

        assert packet == ucie.SidebandPacket(
            opcode=ucie.Opcode.MESSAGE_WITH_64B_DATA,
            srcid=1,
            dstid=2,
            msgcode=0xA5,
            msgsubcode=0x02,
            msginfo=0x1234,
            control_parity=True,
            data_parity=False,
            data=0x0123_4567_89AB_CDEF,
        )

    def test_fewer_bytes_than_a_header_are_no_packet(self):
        assert ucie.SidebandPacket.from_bytes(b"\x00" * 7) is None

    def test_a_length_no_opcode_has_is_no_packet(self):
        one_too_many = a_packet(int(ucie.Opcode.MESSAGE_WITHOUT_DATA), b"\xff")

        assert ucie.SidebandPacket.from_bytes(one_too_many) is None

    def test_an_opcode_ucie_does_not_assign_is_no_packet(self):
        # 0b00010 is in none of the published tables, so there is no
        # saying how long the packet would be.
        assert ucie.SidebandPacket.from_bytes(a_packet(0b0_0010)) is None


class TestWhenASidebandPacketIsDescribed:
    def test_a_training_message_is_named_as_ucie_names_it(self):
        out_of_reset = ucie.SidebandPacket(
            opcode=ucie.Opcode.MESSAGE_WITHOUT_DATA,
            msgcode=0x91,
            msgsubcode=0x00,
        )

        assert out_of_reset.description() == "{SBINIT Out of Reset}"

    def test_a_register_access_says_what_it_does_and_where(self):
        # An address is the low eight bits of its field and the sixteen
        # above them: 0x1234 here.
        write = ucie.SidebandPacket(
            opcode=ucie.Opcode.MEMORY_WRITE_32B,
            msgsubcode=0x34,
            msginfo=0x12,
            data=0xDECA_FBAD,
        )

        assert write.description() == "MemoryWrite_32b 0x1234 = 0xdecafbad"

    def test_a_refused_access_says_how_it_was_refused(self):
        refused = ucie.SidebandPacket(
            opcode=ucie.Opcode.COMPLETION_WITHOUT_DATA,
            msgcode=int(ucie.Status.UNSUPPORTED_REQUEST),
        )

        assert refused.description() == "Completion, unsupported request"

    def test_a_message_nothing_here_knows_is_given_by_its_numbers(self):
        strange = ucie.SidebandPacket(
            opcode=ucie.Opcode.MESSAGE_WITHOUT_DATA,
            msgcode=0x77,
            msgsubcode=0x03,
        )

        assert strange.description() == "message 0x77/0x03"


class TestWhenATraceIsReadForItsSidebandPackets:
    def test_each_sideband_record_comes_with_the_packet_it_carried(self):
        asked = a_record(
            "io.d2d.sideband_peer_initiator",
            a_packet(int(ucie.Opcode.MESSAGE_WITHOUT_DATA)),
        )

        assert ucie.sideband_packets([asked]) == [
            (
                asked,
                ucie.SidebandPacket(opcode=ucie.Opcode.MESSAGE_WITHOUT_DATA),
            )
        ]

    def test_what_crossed_the_mainband_is_left_out_though_it_reads_as_a_packet(
        self,
    ):
        # A die's own traffic is whatever bytes it likes, and eight of
        # them can be a header by chance.
        looks_like_one = a_record(
            "io.d2d.peer_initiator",
            a_packet(int(ucie.Opcode.MESSAGE_WITHOUT_DATA)),
        )

        assert ucie.sideband_packets([looks_like_one]) == []

    def test_a_sideband_record_that_is_no_packet_is_refused_by_name(self):
        # A link only ever sends packets on its sideband. Bytes that do
        # not read as one mean this module and the model have come apart,
        # which a shorter capture would hide.
        short = a_record("io.d2d.sideband_peer_initiator", b"\x00" * 7)

        with pytest.raises(
            ValueError, match=r"io\.d2d\.sideband_peer_initiator"
        ):
            ucie.sideband_packets([short])


def a_record(source: str, data: bytes) -> TraceRecord:
    """A write of `data` seen leaving the port `source`."""
    return TraceRecord(
        time=0,
        source=source,
        sink="the other end",
        command="write",
        address=0,
        data=data,
        ok=True,
    )
