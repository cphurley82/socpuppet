"""Zephyr's driver for the SSD's flash controller, held to Zephyr's own test.

The SSD's firmware reaches its NAND through Zephyr's flash interface
(`flash_read` and friends), and the driver behind it is socpuppet's, in
its Zephyr module. Zephyr has a test for any driver of that kind, its
`tests/drivers/flash/common`, and `firmware/flash_test` builds it, as it
is, for the board `socpuppet_ssd`. It writes, reads back, erases, copies
and asks the driver about itself, in the first two blocks of the NAND.

So this is the driver's contract, and most of it was not written here: it
is what Zephyr expects of every flash driver. Four cases beside it are
socpuppet's, for what only a NAND does: a write of more than one page, and
what the driver refuses.

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

#: Zephyr's cases that are about this flash, and then socpuppet's own
#: (firmware/flash_test/src/nand.c), for what only a NAND does.
CASES = [
    "flash_driver.test_flash_copy",
    "flash_driver.test_flash_erase",
    "flash_driver.test_flash_fill",
    "flash_driver.test_flash_flatten",
    "flash_driver.test_flash_page_layout",
    "flash_driver.test_get_size",
    "flash_driver.test_read_unaligned_address",
    "nand.test_a_write_of_two_pages_reads_back_in_one_read",
    "nand.test_a_write_that_is_not_of_whole_pages_is_refused_and_writes_nothing",
    "nand.test_an_erase_that_is_not_of_whole_blocks_is_refused_and_erases_nothing",
    "nand.test_a_read_that_runs_past_the_end_of_the_nand_is_refused",
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
        assert f"PASS - [{case}]" in what_the_test_printed
