"""Reading UCIe's sideband packets, as a trace of a link carries them."""

import struct

from socpuppet import ucie


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
