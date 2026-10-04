"""Simulated time.

Durations are whole numbers of picoseconds, which is the simulator's own
resolution. Use these helpers rather than counting zeros.
"""


def ns(count):
    """`count` nanoseconds."""
    return count * 1_000


def us(count):
    """`count` microseconds."""
    return count * 1_000_000

