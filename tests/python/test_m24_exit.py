"""M24's exit test: Linux's root filesystem on the drive.

🐧 The drive is the SSD with its own Zephyr firmware, across the
die-to-die link, on M8's board: the IO manager trains the link and lets
the host out of reset, and the host boots OpenSBI and a stock Linux,
whose own NVMe driver, loaded by the initramfs, finds the drive behind
the root complex. The root filesystem is the drive's first partition,
which Python programmed into the SSD's NAND as a factory would.
"""

import re

import pytest

from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    a_host_with_its_root_on_the_drive,
    messages_taken,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. A boot
#: of Linux takes minutes on the interpreter, so the tests are handed out
#: first.
pytestmark = [needs_dtc, pytest.mark.long]


@pytest.fixture
def linux_on_the_drive(firmware):
    """M8's board, booted to Linux's prompt, its root on the drive."""
    board = a_host_with_its_root_on_the_drive(firmware)
    prompted = run_to_the_prompt(board)
    assert prompted, (
        "Linux never prompted. OpenSBI's console:\n"
        f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
        f"{plain(board.virtio.console.output)[-3000:]}\nThe SSD's console:\n"
        f"{plain(board.drive.ssd.cpu_kit.uart.output)[-3000:]}"
    )
    return board


@pytest.mark.platform
class TestWhenLinuxBootsWithItsRootOnTheDrive:
    def test_its_root_is_the_drives_first_partition_writable(
        self, linux_on_the_drive
    ):
        mounts = type_and_wait_for_the_prompt(
            linux_on_the_drive, "cat /proc/mounts"
        )

        assert "/dev/nvme0n1p1 / ext4 rw," in mounts

    def test_the_drives_admin_and_io_queues_take_msi_x_messages(
        self, linux_on_the_drive
    ):
        # 🎓 Each NVMe queue's interrupt is named after it: nvme0q0 is the
        # admin queue, nvme0q1 the first I/O queue, which the root's reads
        # came through.
        interrupts = type_and_wait_for_the_prompt(
            linux_on_the_drive, "cat /proc/interrupts"
        )

        for queue in ("nvme0q0", "nvme0q1"):
            assert re.search(rf"PCI-MSIX-.* {queue}\s*$", interrupts, re.M)
            assert messages_taken(interrupts, queue) > 0, interrupts
