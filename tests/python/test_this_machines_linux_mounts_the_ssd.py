"""M31's exit test: this machine's own Linux formats and mounts the SSD.

🐧 The drive is the SSD with its own Zephyr firmware, and its host is the
machine the simulation runs on: `sp.PciemHost` puts it on this machine's
PCIe bus through pciem, and Linux's own `nvme` driver binds it, as it
would a card in a slot. `mkfs.ext4` formats it, `mount` mounts it, a file
is written, and when Linux lets go of the drive Python reads the file
back out of the SSD's NAND.

The tests run only where the doctor's `pciem` area is well
(pciem_area.py), and they format a drive: the puppet's, found by its
place on pciem's bus, and never one of this machine's own.
"""

import subprocess

import pytest

from ext4_image import file_in
from pciem_area import needs_pciem
from socpuppet import ftl
from socpuppet.boards.real_host import puppet_function, this_machine
from socpuppet.boards.ssd import ssd
from socpuppet.time import ms
from ssd_zephyr_firmware import BANNER
from ssd_zephyr_firmware import IMAGE as SSD_IMAGE
from this_machine import (
    as_root_while_pumping,
    block_device,
    let_go,
    pumped_until,
)

pytestmark = [needs_pciem, pytest.mark.long, pytest.mark.platform]

#: How big the drive is: 64 MiB, in 512-byte blocks.
BLOCKS = 131072
#: The file Linux writes, and what is in it: the numbers from 1 to 20000, a
#: line each, 106 KiB. A new file takes pages of the drive that only the
#: table the firmware saves when Linux lets go of the drive can find.
FILE = "numbers"
LAST = 20000
NUMBERS = "".join(f"{number}\n" for number in range(1, LAST + 1)).encode()


@pytest.fixture
def zephyr_ssd(firmware):
    """The SSD with its Zephyr firmware on this machine's bus, which
    Linux's driver has bound, and the name of its namespace's block device.
    Let go of after."""
    board = ssd(host=this_machine, blocks=BLOCKS)
    board.platform.build()
    board.platform.load_elf(firmware(SSD_IMAGE), via=board.ssd.cpu.socket)
    # The firmware is up before Linux enables the drive, and has a CPU to
    # boot: Linux waits for the drive to be ready only so long.
    console = board.ssd.cpu_kit.uart
    board.platform.run_until(lambda: BANNER in console.output, timeout=ms(1000))
    assert BANNER in console.output, console.output
    board.host.start()
    function = puppet_function()
    assert pumped_until(board, lambda: block_device(function) is not None)
    yield board, f"/dev/{block_device(function)}"
    let_go(board)


class TestWhenThisMachinesLinuxFindsTheZephyrSsd:
    def test_lsblk_lists_it_as_a_64_mib_drive(self, zephyr_ssd):
        _, device = zephyr_ssd

        listed = subprocess.run(
            ["lsblk", "--bytes", "--noheadings", "--output", "SIZE", device],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        assert int(listed) == 64 * 1024 * 1024


class TestWhenThisMachinesLinuxFormatsAndMountsTheZephyrSsd:
    """🎓 The exit test: what Linux wrote is on the drive, for Python to read.

    Unmounting writes out what Linux holds of the file, and letting go of
    the drive shuts it down, which has the SSD's firmware keep its table
    in the NAND's reserve. Python then reads the drive out of the NAND as
    the firmware would, and the file out of the filesystem on it.
    """

    def test_python_reads_the_file_back_from_the_nand_byte_for_byte(
        self, zephyr_ssd, tmp_path
    ):
        board, device = zephyr_ssd
        mounted = tmp_path / "drive"
        mounted.mkdir()

        as_root_while_pumping(board, "mkfs.ext4", "-F", "-q", device)
        as_root_while_pumping(board, "mount", device, str(mounted))
        as_root_while_pumping(
            board, "sh", "-c", f"seq 1 {LAST} > {mounted / FILE}"
        )
        as_root_while_pumping(board, "umount", str(mounted))
        let_go(board)

        assert file_in(filesystem_on(board), f"/{FILE}") == NUMBERS


def filesystem_on(board):
    """The filesystem, as the SSD's NAND holds it: the whole drive, read by
    the table the firmware keeps. mkfs.ext4 was given the whole drive, with
    no partition table."""
    nand = board.ssd.nand
    return ftl.drive_image(nand.contents, nand.component)
