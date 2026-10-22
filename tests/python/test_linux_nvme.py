"""Linux meets the drive: its own NVMe driver, loaded by the initramfs.

🐧 `defconfig` builds the NVMe driver as modules, so a kernel boots with
the initramfs `firmware/build.py` packs, whose `/init` loads them before
it mounts the root. Here the root is still 🎭 the virtio disk, and the
drive is 🎭 the behavioral NVMe stand-in behind the root complex, which
Linux finds as a generic ECAM host (`pci-host-ecam-generic`) and whose
interrupts reach it as MSI-X messages to the IMSIC. The drive as the
root is M24's exit test, `test_m24_exit.py`.
"""

import re

import pytest

from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    a_host_with_the_initramfs,
    messages_taken,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)
from socpuppet import linux

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. A boot
#: of Linux takes minutes on the interpreter, so the tests are handed out
#: first.
pytestmark = [needs_dtc, pytest.mark.long]

#: How big the stand-in drive is, in blocks of 512 bytes: 2 MiB.
DRIVE_BLOCKS = 4096
#: The root the command line names, which the initramfs mounts.
ROOT = re.search(r"root=(\S+)", linux.BOOTARGS)[1]


@pytest.fixture
def linux_with_the_drive(firmware):
    """A host with the stand-in drive, booted through the initramfs to
    Linux's prompt, its root on the virtio disk."""
    board = a_host_with_the_initramfs(firmware, drive_blocks=DRIVE_BLOCKS)
    prompted = run_to_the_prompt(board)
    assert prompted, (
        "Linux never prompted. OpenSBI's console:\n"
        f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
        f"{plain(board.virtio.console.output)[-3000:]}"
    )
    return board


@pytest.mark.platform
class TestWhenLinuxBootsThroughTheInitramfs:
    def test_its_init_mounts_the_root_the_command_line_names(
        self, linux_with_the_drive
    ):
        # 🎓 The kernel runs /init when there is an initramfs, and
        # /sbin/init from the root it mounted itself when there is not.
        board = linux_with_the_drive

        mounts = type_and_wait_for_the_prompt(board, "cat /proc/mounts")

        said = plain(board.uart.output) + plain(board.virtio.console.output)
        assert "Run /init as init process" in said
        assert f"{ROOT} / ext4 rw," in mounts


@pytest.mark.platform
class TestWhenLinuxsNvmeDriverFindsTheDrive:
    def test_the_drive_is_nvme0n1_of_the_blocks_it_was_described_with(
        self, linux_with_the_drive
    ):
        board = linux_with_the_drive

        size = type_and_wait_for_the_prompt(
            board, "cat /sys/block/nvme0n1/size"
        )

        assert size.strip() == str(DRIVE_BLOCKS)

    def test_its_admin_and_io_queues_each_take_msi_x_messages(
        self, linux_with_the_drive
    ):
        # 🎓 Linux names an NVMe queue's interrupt after the queue: nvme0q0
        # is the admin queue, nvme0q1 the first I/O queue. Each counts the
        # messages its vector brought, through the IMSIC.
        board = linux_with_the_drive

        interrupts = type_and_wait_for_the_prompt(board, "cat /proc/interrupts")

        for queue in ("nvme0q0", "nvme0q1"):
            assert re.search(rf"PCI-MSIX-.* {queue}\s*$", interrupts, re.M)
            assert messages_taken(interrupts, queue) > 0, interrupts
