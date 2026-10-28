"""🧵 Python on an I2C bus: a device a controller talks to by its address.

🎓 I2C is a bus of two wires, a clock and a data line, which many chips
share. A transfer starts with an address, seven bits that pick one
device, and a bit for the direction. Then bytes go one way or the other,
each acknowledged by whoever received it, until a stop, or a start again.

A device here is any object with the four methods of `I2cDevice`. Hand it
to a controller by address: `sp.I2cController(devices={0x51: it})`.
"""

from typing import Protocol


class I2cDevice(Protocol):
    """What a controller calls on a device on its bus."""

    def start(self, read: bool) -> bool:
        """A start, addressed to this device: `read` says which way.

        Return whether the device acknowledges.
        """
        ...

    def write(self, byte: int) -> bool:
        """A byte from the controller. Return whether it is acknowledged."""
        ...

    def read(self, last: bool) -> int:
        """A byte to the controller. `last` says it ends the read."""
        ...

    def stop(self) -> None:
        """A stop: the transfer is over."""


class Ram:
    """A memory of `size` bytes, addressed with two bytes, high one first.

    🎓 It is the shape of the small memories boards have on I2C, a FRAM or
    an EEPROM, and what Zephyr's `i2c_ram` test writes and reads back: a
    write sends the address the bytes go to and then the bytes, and a read
    goes on from where the last write or read left off, so a read of a
    place is a write of its address alone and then a start again, to read.
    Past its last byte it goes on from its first.
    """

    #: How many bytes of address a write starts with.
    ADDRESS_BYTES = 2
    #: The bits those bytes have.
    _ADDRESS_BITS = (1 << 8 * ADDRESS_BYTES) - 1

    def __init__(self, size: int = 0x1_0000) -> None:
        self.memory = bytearray(size)
        self._address = 0
        self._address_bytes_to_come = 0

    def start(self, read: bool) -> bool:
        """A start: a write begins with the address, a read reads on."""
        self._address_bytes_to_come = 0 if read else self.ADDRESS_BYTES
        return True

    def write(self, byte: int) -> bool:
        """The next byte of the address, or of the data."""
        if self._address_bytes_to_come:
            self._address = (self._address << 8 | byte) & self._ADDRESS_BITS
            self._address_bytes_to_come -= 1
        else:
            self.memory[self._address % len(self.memory)] = byte
            self._step()
        return True

    def read(self, last: bool) -> int:
        """The byte where the RAM has got to, and on to the next."""
        byte = self.memory[self._address % len(self.memory)]
        self._step()
        return byte

    def stop(self) -> None:
        """Nothing to do: where it has got to stays for the next read."""

    def _step(self) -> None:
        self._address = (self._address + 1) % len(self.memory)
