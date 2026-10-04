"""Simulated time.

Durations are whole numbers of picoseconds, which is the simulator's own
resolution. Use these helpers rather than counting zeros.
"""


def ns(count: int) -> int:
    """`count` nanoseconds."""
    return count * 1_000


def us(count: int) -> int:
    """`count` microseconds."""
    return count * 1_000_000


def ms(count: int) -> int:
    """`count` milliseconds."""
    return str(count * 1_000_000_000)
