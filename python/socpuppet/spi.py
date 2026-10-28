"""🧵 Python on an SPI bus: a device a controller talks to by chip select.

🎓 SPI is a serial bus of four wires: a clock, a wire out and a wire back,
and a chip select for each device, which the controller pulls low to talk
to that one. Every byte out is a byte back, whether the device had anything
to say or not. A frame is everything between the select and the let-go: a
command, often an address, then data.

A device here is any object with the three methods of `SpiDevice`. Hand it
to a controller by chip select: `sp.SpiFlash(size=..., devices={1: it})`.
"""

from typing import Protocol


class SpiDevice(Protocol):
    """What a controller calls on a device on its bus."""

    def select(self) -> None:
        """The device's chip select has gone low: a frame starts."""

    def transfer(self, byte: int) -> int:
        """One byte each way: `byte` from the controller, and the answer."""
        ...

    def deselect(self) -> None:
        """The chip select has gone high again: the frame is over."""


class Loopback:
    """A device whose answer to every byte is the byte itself.

    🎓 It is what a wire from the controller's data out to its data in
    does, which is how Zephyr's `spi_loopback` test is meant to be run on a
    board: the test checks that what it receives is what it sent.
    """

    def select(self) -> None:
        """Nothing to do: a wire has no frames."""

    def transfer(self, byte: int) -> int:
        """The byte that was sent, back."""
        return byte

    def deselect(self) -> None:
        """Nothing to do: a wire has no frames."""
