"""Zephyr's driver for the SSD's flash controller, held to Zephyr's own test.

The SSD's firmware reaches its NAND through Zephyr's flash interface
(`flash_read` and friends), and the driver behind it is socpuppet's, in
its Zephyr module. Zephyr has a test for any driver of that kind, its
`tests/drivers/flash/common`, and `firmware/flash_test` builds it, as it
is, for the board `socpuppet_ssd`. It writes, reads back, erases, copies
and asks the driver about itself, in the first two blocks of the NAND.

So this is the driver's contract, and it was not written here: it is what
Zephyr expects of every flash driver.

Two of the test's cases skip themselves. One is for a flash on a bus that
limits the size of a transfer, and one for a flash with a power switch.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd

#: What Zephyr's test framework ends with, when no test failed and when
#: one did.
VERDICTS = ("PROJECT EXECUTION SUCCESSFUL", "PROJECT EXECUTION FAILED")

#: The cases that are about this flash.
CASES = [
    "test_flash_copy",
    "test_flash_erase",
    "test_flash_fill",
    "test_flash_flatten",
    "test_flash_page_layout",
    "test_get_size",
    "test_read_unaligned_address",
]


@pytest.fixture
def what_the_test_printed(firmware):
    """Runs Zephyr's flash test on the SSD, and returns its console.

    Each test that asks runs it again, which takes a tenth of a second: a
    test that builds a platform has a process to itself.
    """
    # The NAND is the size the firmware was built to expect: the SSD's,
    # when `ssd()` is not told one.
    board = ssd(host=idle_host)
    board.platform.build()
    board.platform.load_elf(
        firmware("flash_test_socpuppet_ssd.elf"),
        via=board.ssd.cpu.socket,
    )
    console = board.ssd.cpu_kit.uart

    # The verdict comes at about a tenth of a second of simulated time. A
    # second leaves room and still ends a run that never gives one.
    board.platform.run_until(
        lambda: any(each in console.output for each in VERDICTS),
        timeout=sp.ms(1000),
    )
    return console.output


@pytest.mark.platform
class TestWhenZephyrsFlashTestRunsOnTheSsdsNand:
    def test_it_gives_a_verdict_and_nothing_failed(self, what_the_test_printed):
        assert "PROJECT EXECUTION SUCCESSFUL" in what_the_test_printed, (
            f"Zephyr's flash test printed:\n{what_the_test_printed}"
        )

    @pytest.mark.parametrize("case", CASES)
    def test_the_case_passes_and_does_not_skip_itself(
        self, what_the_test_printed, case
    ):
        assert f"PASS - [flash_driver.{case}]" in what_the_test_printed
