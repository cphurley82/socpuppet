"""M18's exit: the small essentials, under Zephyr's own samples and tests.

The host's boot flash is SiFive's SPI controller with a W25Q-kind chip of
socpuppet's behind it, on the IO die:

    compute.cpu ─▶ ... ─▶ io.bus ─┬─▶ io.uart              (the console)
                                  └─▶ io.boot_flash.socket (the controller)
                                        └─ chip select 0: the chip

Each image is one of Zephyr's own, built for `socpuppet_host`, and drives
the flash through Zephyr's own drivers, `spi_sifive` and `spi_nor`.
"""

import pytest

import socpuppet as sp
from cast import boot
from processes import run_socpuppet
from socpuppet import ztest
from socpuppet.boards.host import SPI_LOOPBACK_CHIP_SELECT, host
from socpuppet.spi import Loopback

#: Zephyr's `samples/drivers/spi_flash`.
SPI_FLASH = "spi_flash_socpuppet_host.elf"
#: Zephyr's `tests/drivers/spi/spi_loopback`, with the shield that puts its
#: two devices on the boot flash's bus, at chip select 1.
SPI_LOOPBACK = "spi_loopback_socpuppet_host.elf"
#: What the sample says when it passes, in order: its `sample.yaml` has them
#: as the lines its console must show. Copied here, as `cast.GREETING` is:
#: CI's test job has the images and not Zephyr's tree to read them from.
WHAT_THE_SPI_FLASH_SAMPLE_SAYS = (
    "Test 1: Flash erase",
    "Flash erase succeeded!",
    "Test 2: Flash write",
    "Attempting to write 4 bytes",
    "Data read matches data written. Good!!",
)
#: The sample is done in 4.8 ms of simulated time; about ten times that
#: still ends a run that never is.
LIMIT = sp.ms(50)
#: The loopback test gives its verdict at 473 ms of simulated time; about
#: twice that leaves room for the quantum to move its timed transfers, and
#: still ends a run that never gives one.
LOOPBACK_LIMIT = sp.ms(1000)


@pytest.mark.platform
class TestWhenZephyrsSpiFlashSampleRunsOnTheHostsBootFlash:
    def test_it_erases_writes_and_reads_back_through_zephyrs_own_drivers(
        self, firmware
    ):
        board = host()
        boot(board, firmware, host=SPI_FLASH)

        board.platform.run_until(
            lambda: WHAT_THE_SPI_FLASH_SAMPLE_SAYS[-1] in board.uart.output,
            timeout=LIMIT,
        )

        assert heard_in_order(board.uart.output) == list(
            WHAT_THE_SPI_FLASH_SAMPLE_SAYS
        )


@pytest.mark.platform
class TestWhenZephyrsSpiLoopbackTestRunsWithPythonAtTheFarEnd:
    def test_it_gives_a_verdict_and_nothing_failed(self, firmware):
        # 🧵 Python is the wire from the controller's data out to its data
        # in, which the test wants a board to have.
        board = host(boot_flash_devices={SPI_LOOPBACK_CHIP_SELECT: Loopback()})
        boot(board, firmware, host=SPI_LOOPBACK)

        board.platform.run_until(
            lambda: ztest.verdict_of(board.uart.output) is not None,
            timeout=LOOPBACK_LIMIT,
        )

        assert ztest.parse(board.uart.output).passed, board.uart.output


class TestWhenZephyrsSpiLoopbackTestIsRunAsTwisterRunsIt:
    def test_the_shield_puts_python_at_the_far_end_and_nothing_failed(
        self, firmware
    ):
        # `socpuppet run` with the shield is how twister runs the image.
        result = run_socpuppet(
            "run",
            str(firmware(SPI_LOOPBACK)),
            "--board",
            "socpuppet_host",
            "--shield",
            "socpuppet_host_spi_loopback",
        )

        assert ztest.parse(result.stdout).passed, result.stdout


def heard_in_order(output):
    """The sample's pass lines that `output` has, in the order it has them."""
    return [
        expected
        for line in output.splitlines()
        for expected in WHAT_THE_SPI_FLASH_SAMPLE_SAYS
        if expected in line
    ]
