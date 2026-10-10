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


#: What is in the SSD's CPU's place.
A_SCRIPT = "a script for the SSD's firmware"
ZEPHYR = "Zephyr for the SSD's firmware"


@pytest.fixture(params=[A_SCRIPT, ZEPHYR])
def host_with_the_ssd(request, firmware):
    """Builds the host with the SSD, with every image loaded.

    The host's image is Zephyr's disk test. Every test that asks for this
    runs twice: once with 🎭 the Python stand-in for the SSD's firmware,
    in its CPU's place, and once with the real thing, the Zephyr
    application in firmware/ssd on the SSD's own CPU. A test of what only
    the real thing does asks for that one alone, with `only_with_zephyr`.
    """
    host_image = firmware("disk_access_socpuppet_host.elf")
    ssd_image = (
        firmware("ssd_socpuppet_ssd.elf") if request.param == ZEPHYR else None
    )

    def build(blocks):
        board = host(
            drive_blocks=blocks,
            drive=add_ssd
            if ssd_image
            else functools.partial(
                add_ssd, firmware=stand_in_firmware().script
            ),
        )
        board.platform.build()
        # With two bus masters, the platform has to be told whose
        # firmware an image is.
        board.platform.load_elf(host_image, via=board.cpu.socket)
        if ssd_image:
            board.platform.load_elf(ssd_image, via=board.drive.ssd.cpu.socket)
        return board

    return build


only_with_zephyr = pytest.mark.parametrize(
    "host_with_the_ssd", [ZEPHYR], indirect=True
)


@pytest.mark.platform
class TestWhenZephyrsDiskTestRunsOnTheHostWithTheSsd:
    def test_its_read_and_write_tests_pass(self, host_with_the_ssd):
        # 2 MiB, as in M3b.
        board = host_with_the_ssd(blocks=4096)

        run_to_a_verdict(board)

        assert "PASS - [disk_driver.test_read]" in board.uart.output
        assert "PASS - [disk_driver.test_write]" in board.uart.output

    @only_with_zephyr
    def test_each_firmware_prints_on_its_own_console(self, host_with_the_ssd):
        board = host_with_the_ssd(blocks=4096)
        ssds_console = board.drive.ssd.cpu_kit.uart

        run_to_a_verdict(board)

        assert "socpuppet SSD firmware" in ssds_console.output
        assert "socpuppet SSD firmware" not in board.uart.output
        assert "disk_driver" in board.uart.output
        assert "disk_driver" not in ssds_console.output


def run_to_a_verdict(board):
    """Run until the host's firmware says how its tests went."""
    gave_a_verdict = board.platform.run_until(
        lambda: any(each in board.uart.output for each in VERDICTS),
        timeout=LIMIT,
    )
    assert gave_a_verdict, no_verdict(board)


def no_verdict(board):
    """What to say when the host's firmware never finished.

    The SSD's console is the first place to look: a host that waits for
    ever is most often waiting for the SSD.
    """
    ssd = board.drive.ssd
    return (
        "The host's firmware gave no verdict in 2 s. It printed:\n"
        f"{board.uart.output or '(nothing)'}\n"
        "And the SSD's firmware printed:\n"
        + (
            ssd.cpu_kit.uart.output or "(nothing)"
            if ssd.cpu_kit
            else "(nothing: a script has no console)"
        )
    )
