"""M18's exit: the small essentials, under Zephyr's own samples and tests.

The host's boot flash is SiFive's SPI controller with a W25Q-kind chip of
socpuppet's behind it, on the IO die:

    compute.cpu ─▶ ... ─▶ io.bus ─┬─▶ io.uart              (the console)
                                  └─▶ io.boot_flash.socket (the controller)
                                        └─ chip select 0: the chip

Each image is one of Zephyr's own, built for `socpuppet_host`, and drives
the flash through Zephyr's own drivers, `spi_sifive` and `spi_nor`.

🐧 Then Linux, a stock kernel, drives the same flash through its own
drivers, `spi-sifive` and `spi-nor`, which show it as an MTD device, the
kind of block Linux gives a flash: it reads what Python put there, and
Python reads what it writes.
"""

import pytest

import socpuppet as sp
from cast import boot
from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    a_host_with_linux,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)
from processes import run_socpuppet
from socpuppet import ztest
from socpuppet.boards.host import (
    BOOT_FLASH_BASE,
    BOOT_FLASH_SIZE,
    SPI_LOOPBACK_CHIP_SELECT,
    host,
)
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


#: What Python puts at the start of the flash before Linux boots.
WHAT_PYTHON_PUT = b"spam, spam, eggs"
#: An erase block of the flash, away from Python's bytes, for Linux to
#: write in: the chip's smallest erase is 4 KiB.
LINUXS_BLOCK = 0x1000
#: What Linux writes there.
WHAT_LINUX_WROTE = b"eggs"


@pytest.fixture
def linux_with_bytes_in_the_flash(firmware):
    """A host booted to Linux's prompt with `WHAT_PYTHON_PUT` in its flash."""
    board = a_host_with_linux(firmware)
    board.platform.poke(BOOT_FLASH_BASE, WHAT_PYTHON_PUT, via=board.cpu.socket)
    prompted = run_to_the_prompt(board)
    assert prompted, (
        "Linux never prompted. OpenSBI's console:\n"
        f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
        f"{plain(board.virtio.console.output)[-3000:]}"
    )
    return board


@needs_dtc
@pytest.mark.platform
@pytest.mark.long
class TestWhenLinuxDrivesTheHostsBootFlash:
    def test_spi_nor_names_the_chip_and_shows_the_whole_flash(
        self, linux_with_bytes_in_the_flash
    ):
        # 🎓 A W25Q chip's name gives its size in megabits.
        board = linux_with_bytes_in_the_flash
        megabits = BOOT_FLASH_SIZE * 8 // 2**20

        name = type_and_wait_for_the_prompt(
            board, "cat /sys/bus/spi/devices/*/spi-nor/partname"
        )
        mtds = type_and_wait_for_the_prompt(board, "cat /proc/mtd")

        assert name.strip() == f"w25q{megabits}"
        # The host's one flash is the first MTD device, which the next
        # test reads and writes.
        assert f"mtd0: {BOOT_FLASH_SIZE:08x} " in mtds

    def test_linux_reads_what_python_put_and_python_reads_what_linux_wrote(
        self, linux_with_bytes_in_the_flash
    ):
        board = linux_with_bytes_in_the_flash

        read = type_and_wait_for_the_prompt(
            board,
            f"head -c {len(WHAT_PYTHON_PUT)} /dev/mtd0 | hexdump -e "
            "'16/1 \"%02x\"'",
        )
        type_and_wait_for_the_prompt(
            board,
            f"printf {WHAT_LINUX_WROTE.decode()} | "
            f"dd of=/dev/mtd0 bs=1 seek={LINUXS_BLOCK}",
        )

        assert bytes.fromhex(read.strip()) == WHAT_PYTHON_PUT
        assert (
            board.platform.peek(
                BOOT_FLASH_BASE + LINUXS_BLOCK,
                len(WHAT_LINUX_WROTE),
                via=board.cpu.socket,
            )
            == WHAT_LINUX_WROTE
        )


def heard_in_order(output):
    """The sample's pass lines that `output` has, in the order it has them."""
    return [
        expected
        for line in output.splitlines()
        for expected in WHAT_THE_SPI_FLASH_SAMPLE_SAYS
        if expected in line
    ]
