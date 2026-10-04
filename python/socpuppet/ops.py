"""The operations a script can yield to its bus master.

A script is a generator. It yields one operation at a time and the bus
master carries it out; a read sends its value back into the generator:

    def script():
        yield sp.write32(0x1000, 0xC0FFEE)
        value = yield sp.read32(0x1000)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    """One thing for a bus master to do. Make these with the functions below."""

    kind: str
    operands: tuple = ()


def read32(address):
    """Read a 32-bit value. The value is sent back into the script."""
    return Operation("read32", (address,))


def write32(address, value):
    """Write a 32-bit value."""
    return Operation("write32", (address, _fits_32_bits(value)))


def expect32(address, value):
    """Read a 32-bit value and stop the run with ExpectationFailed if it is not `value`."""
    return Operation("expect32", (address, _fits_32_bits(value)))


def wait(duration):
    """Let `duration` of simulated time pass (see `ns`, `us`)."""
    return Operation("wait", (duration,))


def wait_irq():
    """Wait until the master's interrupt line is high."""
    return Operation("wait_irq")


def to_native(yielded):
    """What the simulator needs to carry out something a script yielded: (kind, *operands)."""
    if not isinstance(yielded, Operation):
        raise TypeError(
            f"A script yielded {yielded!r}, which is not a bus operation. Yield "
            "operations such as sp.write32(address, value), sp.read32(address) "
            "or sp.wait(sp.ns(10))."
        )
    return (yielded.kind, *yielded.operands)


def _fits_32_bits(value):
    if not 0 <= value < 2**32:
        shown = f"{value:#x}" if value >= 0 else str(value)
        raise ValueError(f"{shown} does not fit in 32 bits (0 to 0xffffffff).")
    return value
