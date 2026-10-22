"""M24's exit test: Linux's root filesystem on the drive.

🐧 The drive is the SSD with its own Zephyr firmware, across the
die-to-die link, on M8's board: the IO manager trains the link and lets
the host out of reset, and the host boots OpenSBI and a stock Linux,
whose own NVMe driver, loaded by the initramfs, finds the drive behind
the root complex.
"""

import pytest

from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    a_host_with_the_bootchain_and_the_initramfs,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)
from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. A boot
#: of Linux takes minutes on the interpreter, so the tests are handed out
#: first.
pytestmark = [needs_dtc, pytest.mark.long]

#: How big the drive is, in blocks of 512 bytes: eight of the SSD's NAND
#: blocks.
DRIVE_BLOCKS = 8 * DRIVE_BLOCKS_PER_NAND_BLOCK


@pytest.fixture
def linux_on_the_bootchain(firmware):
    """M8's board, booted to Linux's prompt, its root on the virtio disk."""
    board = a_host_with_the_bootchain_and_the_initramfs(
        firmware, drive_blocks=DRIVE_BLOCKS
    )
    prompted = run_to_the_prompt(board)
    assert prompted, (
        "Linux never prompted. OpenSBI's console:\n"
        f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
        f"{plain(board.virtio.console.output)[-3000:]}\nThe SSD's console:\n"
        f"{plain(board.drive.ssd.cpu_kit.uart.output)[-3000:]}"
    )
    return board


@pytest.mark.platform
class TestWhenLinuxMeetsTheZephyrSsdAcrossTheLink:
    def test_the_drive_is_nvme0n1_of_the_blocks_it_was_described_with(
        self, linux_on_the_bootchain
    ):
        board = linux_on_the_bootchain

        size = type_and_wait_for_the_prompt(
            board, "cat /sys/block/nvme0n1/size"
        )

        assert size.strip() == str(DRIVE_BLOCKS)
