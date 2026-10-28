"""🐧 Linux drives the host's boot flash, as part of M18's exit.

The boot flash is SiFive's SPI controller with a W25Q-kind chip of
socpuppet's behind it, on the host's IO die. A stock kernel drives it
through its own drivers, `spi-sifive` and `spi-nor`, which show it as an
MTD device, the kind of block Linux gives a flash: it reads what Python
put there, and Python reads what it writes. Zephyr's half of the exit is
`test_zephyr_peripheral_samples.py`.
"""

import pytest

from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    a_host_with_linux,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)
from socpuppet.boards.host import BOOT_FLASH_BASE, BOOT_FLASH_SIZE

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. A boot
#: of Linux takes seconds on QBox's hart and minutes on the interpreter, so
#: the tests are handed out first.
pytestmark = [needs_dtc, pytest.mark.long, pytest.mark.platform]

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
