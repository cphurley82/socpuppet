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
from socpuppet.boards.host import host

#: Zephyr's `samples/drivers/spi_flash`.
SPI_FLASH = "spi_flash_socpuppet_host.elf"
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


def heard_in_order(output):
    """The sample's pass lines that `output` has, in the order it has them."""
    return [
        expected
        for line in output.splitlines()
        for expected in WHAT_THE_SPI_FLASH_SAMPLE_SAYS
        if expected in line
    ]
