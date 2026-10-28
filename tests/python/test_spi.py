"""Python's devices for an SPI bus (`socpuppet.spi`), with no platform."""

from socpuppet.spi import Loopback


class TestALoopback:
    def test_answers_each_byte_with_the_byte_itself(self):
        loopback = Loopback()
        loopback.select()

        answers = [loopback.transfer(byte) for byte in (0x00, 0x5A, 0xFF)]

        assert answers == [0x00, 0x5A, 0xFF]
