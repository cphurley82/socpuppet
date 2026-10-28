"""Linux's root filesystem on the drive.

🐧 The drive is the SSD with its own Zephyr firmware, across the die-to-die link,
on the full bootchain's board: the IO manager trains the link and lets the host
out of reset, and the host boots OpenSBI and a stock Linux, whose own NVMe
driver, loaded by the initramfs, finds the drive behind the root complex. The
root filesystem is the drive's first partition, which Python programmed into the
SSD's NAND as a factory would.
"""

import re

import pytest

from console import plain
from devicetree_compiler import needs_dtc
from ext4_image import file_in
from linux_shell import (
    LONG_ENOUGH_THROUGH_UEFI,
    a_host_with_its_root_on_the_drive,
    a_host_with_uefi_and_its_root_on_the_drive,
    messages_taken,
    run_to_the_prompt,
    switch_off_at_the_prompt,
    type_and_wait_for_the_prompt,
)
from socpuppet import ftl, gpt

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. A boot
#: of Linux takes minutes on the interpreter, so the tests are handed out
#: first.
pytestmark = [needs_dtc, pytest.mark.long]


@pytest.fixture
def linux_on_the_drive(firmware):
    """The full bootchain's board at Linux's prompt, its root on the drive."""
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


#: The file Linux writes, and what is in it: the numbers from 1 to 20000, a
#: line each, 106 KiB. A new file takes new pages of the drive, which no
#: NAND page held when the factory programmed it, so only the table the
#: firmware saves at the shutdown can find them; this one takes many.
FILE = "/root/numbers"
LAST = 20000
NUMBERS = "".join(f"{number}\n" for number in range(1, LAST + 1)).encode()


@pytest.mark.platform
class TestWhenLinuxWritesAFileAndSwitchesOff:
    """🎓 What Linux wrote is on the drive, for Python to read.

    Linux's `poweroff` unmounts the root, which writes out what it holds,
    and shuts the drive down, which has the SSD's firmware keep its table
    in the NAND's reserve. Python then reads the drive out of the NAND as
    the firmware would, and the file out of the drive's first partition.
    """

    def test_python_reads_the_file_back_from_the_nand_byte_for_byte(
        self, linux_on_the_drive
    ):
        board = linux_on_the_drive
        type_and_wait_for_the_prompt(board, f"seq 1 {LAST} > {FILE}")

        switched = switch_off_at_the_prompt(board)

        assert switched, plain(board.virtio.console.output)[-3000:]
        assert file_in(root_filesystem_on(board), FILE) == NUMBERS

    def test_linux_does_not_give_up_waiting_for_the_drive_to_shut_down(
        self, linux_on_the_drive
    ):
        # 🐧 Linux waits five seconds for a drive's shutdown, and says so
        # when it gives up.
        board = linux_on_the_drive
        before = len(board.virtio.console.output)

        switched = switch_off_at_the_prompt(board)

        said = plain(board.virtio.console.output[before:])
        assert switched, said[-3000:]
        assert not re.search(r"nvme\S*: .*shutdown", said, re.I), said


@pytest.mark.on_demand("Linux booted the server's way, from the drive")
@pytest.mark.platform
class TestWhenUefiBootsTheKernelFromTheDrive:
    def test_uefis_own_nvme_driver_finds_it_and_linux_mounts_its_root(
        self, firmware
    ):
        # 🎓 The server's way: UEFI's own NVMe driver finds the drive, its
        # boot manager the shell on the EFI system partition, and the
        # shell's startup.nsh starts the kernel with its initramfs, which
        # mounts the root from the drive's second partition.
        board = a_host_with_uefi_and_its_root_on_the_drive(firmware)

        prompted = run_to_the_prompt(board, within=LONG_ENOUGH_THROUGH_UEFI)
        assert prompted, (
            f"Linux never prompted. UEFI's console:\n"
            f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
            f"{plain(board.virtio.console.output)[-3000:]}"
        )
        mounts = type_and_wait_for_the_prompt(board, "cat /proc/mounts")

        assert "/dev/nvme0n1p2 / ext4 rw," in mounts


def root_filesystem_on(board):
    """The root filesystem, as the SSD's NAND holds it: the drive's first
    partition, the drive read by the table the firmware keeps."""
    nand = board.drive.ssd.nand
    drive = ftl.drive_image(nand.contents, nand.component)
    first, *_ = gpt.partitions(drive)
    return first.data
