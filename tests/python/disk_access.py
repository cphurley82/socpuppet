"""Zephyr's test of its disk interface, as a test runs it on a host.

The image is `disk_access_socpuppet_host.elf`: Zephyr's own
`tests/drivers/disk/disk_access`, built for the board `socpuppet_host`
with the shield `socpuppet_host_drive`. It is the same image whichever
drive the host has and whichever link is between the host's dies.
"""

import socpuppet as sp
from socpuppet import ztest

IMAGE = "disk_access_socpuppet_host.elf"
#: The verdict comes at about half a second of simulated time with 🎭 the
#: stand-in drive, and a quarter of a second later under the slowest SSD
#: the tests have. 2 s leaves room and still ends a run that never gives
#: one.
LIMIT = sp.ms(2000)


def run_to_a_verdict(board):
    """Run until the host's firmware says how its tests went.

    Returns what it said of them, as a `socpuppet.ztest.Report`.
    """
    gave_a_verdict = board.platform.run_until(
        lambda: ztest.verdict_of(board.uart.output) is not None,
        timeout=LIMIT,
    )
    assert gave_a_verdict, no_verdict(board)
    return ztest.parse(board.uart.output)


def assert_it_read_and_wrote(console):
    """Fail unless the test's read and write cases passed, on this console.

    The verdict alone does not say so: a case that skips itself does not
    spoil it, and the test's third case, erase, does skip itself.
    """
    report = ztest.parse(console)
    for case in ("disk_driver.test_read", "disk_driver.test_write"):
        assert report.case(case).result == "PASS", (
            f"The host's firmware printed:\n{console}"
        )


def no_verdict(board):
    """What to say when the host's firmware never finished.

    An SSD's console is the first place to look: a host that waits for
    ever is most often waiting for its drive.
    """
    said = (
        "The host's firmware gave no verdict in the time it was given. "
        "It printed:\n"
        f"{board.uart.output or '(nothing)'}"
    )
    # 🎭 The stand-in drive and an SSD with a script for its firmware have
    # no CPU, and so no console.
    kit = getattr(board.drive.ssd, "cpu_kit", None)
    if kit is None:
        return said
    return (
        f"{said}\nAnd the SSD's firmware printed:\n"
        f"{kit.uart.output or '(nothing)'}"
    )
