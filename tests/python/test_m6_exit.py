"""Milestone M6's exit test: the host's firmware with the SSD's firmware.

It is M3b's exit test with the drive swapped. The host's firmware is the
same image, Zephyr's own test of its disk interface, built for the board
`socpuppet_host` with the shield `socpuppet_host_drive`. Where M3b's host
had 🎭 the stand-in drive on its PCIe link, this one has the SSD of
`socpuppet.boards.ssd`, which is hardware that does nothing until
firmware tells it to.

Nothing was built again for this. The host cannot tell which drive it
has, so its image is M3b's.
"""

import functools

import pytest

import socpuppet as sp
from socpuppet.boards.host import host
from socpuppet.boards.ssd import add_ssd, stand_in_firmware

#: What Zephyr's test framework ends with, when no test failed and when
#: one did.
VERDICTS = ("PROJECT EXECUTION SUCCESSFUL", "PROJECT EXECUTION FAILED")
#: The verdict comes at about half a second of simulated time, as it does
#: with the stand-in drive. 2 s leaves room and still ends a run that
#: never gives one.
LIMIT = sp.ms(2000)


@pytest.fixture(params=["a script for the SSD's firmware"])
def host_with_the_ssd(firmware):
    """Builds the host with the SSD, with Zephyr's disk test loaded.

    🎭 The SSD's firmware is the Python stand-in, in its CPU's place.
    """
    host_image = firmware("disk_access_socpuppet_host.elf")

    def build(blocks):
        board = host(
            drive_blocks=blocks,
            drive=functools.partial(
                add_ssd, firmware=stand_in_firmware().script
            ),
        )
        board.platform.build()
        # With two bus masters, the platform has to be told whose
        # firmware an image is.
        board.platform.load_elf(host_image, via=board.cpu.socket)
        return board

    return build


@pytest.mark.platform
class TestWhenZephyrsDiskTestRunsOnTheHostWithTheSsd:
    def test_its_read_and_write_tests_pass(self, host_with_the_ssd):
        # 2 MiB, as in M3b.
        board = host_with_the_ssd(blocks=4096)

        gave_a_verdict = board.platform.run_until(
            lambda: any(each in board.uart.output for each in VERDICTS),
            timeout=LIMIT,
        )

        assert gave_a_verdict, no_verdict(board)
        assert "PASS - [disk_driver.test_read]" in board.uart.output
        assert "PASS - [disk_driver.test_write]" in board.uart.output


def no_verdict(board):
    """What to say when the host's firmware never finished."""
    return (
        "The host's firmware gave no verdict in 2 s. It printed:\n"
        f"{board.uart.output or '(nothing)'}"
    )
