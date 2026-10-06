"""The operations a script can yield to its bus master.

A script is a generator. It yields one operation at a time and the bus
master carries it out; a read sends its value back into the generator:

    def script():
        yield sp.write32(0x1000, 0xC0FFEE)
        value = yield sp.read32(0x1000)
"""

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Operation:
    """One thing for a bus master to do. Make these with the functions below."""

    kind: str
    operands: tuple[int | bytes, ...] = ()


#: A piece of a script that can be handed over to with `yield from`: a
#: generator of operations, which returns a `Result` when it is done.
type Steps[Result] = Generator[Operation, Any, Result]


def read32(address: int) -> Operation:
    """Read a 32-bit value. The value is sent back into the script."""
    return Operation("read32", (address,))


def write32(address: int, value: int) -> Operation:
    """Write a 32-bit value."""
    return Operation("write32", (address, _fits_32_bits(value)))


def read(address: int, length: int) -> Operation:
    """Read `length` bytes in one access. They are sent back into the script."""
    if length < 0:
        raise ValueError(f"Cannot read {length} bytes: a length is 0 or more.")
    return Operation("read", (address, length))


def write(address: int, data: bytes) -> Operation:
    """Write the bytes of `data` in one access."""
    if not isinstance(data, bytes | bytearray | memoryview):
        raise TypeError(
            f"sp.write() writes bytes, and was given {data!r}. To write a "
            "number, use sp.write32(address, value), or turn it into bytes "
            'first with value.to_bytes(length, "little").'
        )
    return Operation("write", (address, bytes(data)))


def expect32(address: int, value: int) -> Operation:
    """Read a 32-bit value, and stop the run if it is not `value`.

    The run stops with ExpectationFailed.
    """
    return Operation("expect32", (address, _fits_32_bits(value)))


def wait(duration: int) -> Operation:
    """Let `duration` of simulated time pass (see `ns`, `us`)."""
    return Operation("wait", (duration,))


def wait_irq() -> Operation:
    """Wait until the master's interrupt line is high."""
    return Operation("wait_irq")


def to_native(yielded: object) -> tuple[str | int | bytes, ...]:
    """What the simulator needs to carry out something a script yielded.

    That is (kind, *operands).
    """
    if not isinstance(yielded, Operation):
        raise TypeError(
            f"A script yielded {yielded!r}, which is not a bus operation. "
            "Yield operations such as sp.write32(address, value), "
            "sp.read(address, length) or sp.wait(sp.ns(10))."
        )
    return (yielded.kind, *yielded.operands)


def _fits_32_bits(value: int) -> int:
    if not 0 <= value < 2**32:
        shown = f"{value:#x}" if value >= 0 else str(value)
        raise ValueError(f"{shown} does not fit in 32 bits (0 to 0xffffffff).")
    return value
