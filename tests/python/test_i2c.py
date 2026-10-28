"""Python's devices for an I2C bus (`socpuppet.i2c`), with no platform."""

from socpuppet.i2c import Ram


def write(ram, address, data):
    """A write to `ram` as Zephyr's test makes it: the address, then data."""
    ram.start(read=False)
    for byte in (address >> 8, address & 0xFF, *data):
        assert ram.write(byte)
    ram.stop()


def read(ram, address, count):
    """A read from `ram`: the address written, then a start again to read."""
    ram.start(read=False)
    ram.write(address >> 8)
    ram.write(address & 0xFF)
    ram.start(read=True)
    got = [ram.read(last=index == count - 1) for index in range(count)]
    ram.stop()
    return bytes(got)


class TestARam:
    def test_acknowledges_its_address(self):
        assert Ram().start(read=False)

    def test_reads_back_what_was_written_from_where_it_was_written(self):
        ram = Ram()

        write(ram, 0x0102, b"spam")

        assert read(ram, 0x0102, 4) == b"spam"

    def test_starts_again_at_its_first_byte_past_its_last(self):
        ram = Ram(size=0x100)

        write(ram, 0x00FF, b"ab")

        assert read(ram, 0x0000, 1) == b"b"

    def test_of_a_size_that_is_no_power_of_two_writes_where_it_is_told(self):
        ram = Ram(size=1000)

        write(ram, 3, b"spam")
        write(ram, 5, b"e")

        assert read(ram, 3, 4) == b"spem"
