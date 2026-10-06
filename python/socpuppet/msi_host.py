"""🎭 The part of a host's firmware that takes message-signalled interrupts.

A PCIe device interrupts by writing a message to an address the host
chose. On this platform an `MsiReceiver` is at that address, and turns the
message into a rise of the host's interrupt line. This is the host's side
of that arrangement, in one place: what a device is to be told to send,
and what the host does when the line rises.
"""

from __future__ import annotations

from socpuppet.ops import Steps, read32, wait_irq


class MsiHost:
    """🎭 Stand-in for the host's handling of an `MsiReceiver`.

    `receiver` is where the receiver is in the host's address map.
    """

    def __init__(self, *, receiver: int) -> None:
        self._receiver = receiver

    @property
    def address(self) -> int:
        """Where a device is to send its interrupt messages."""
        return self._receiver

    def data_for(self, vector: int) -> int:
        """What the message for one of a device's vectors is to say.

        The receiver takes a message's data for the number of the vector,
        so that is what it is.
        """
        return vector

    def wait(self) -> Steps[int]:
        """Wait for an interrupt, and take it.

        Returns which vectors have had a message since the last time, one
        bit each. Reading that from the receiver is also what makes the
        interrupt line fall again.
        """
        yield wait_irq()
        waiting: int = yield read32(self._receiver)
        return waiting
