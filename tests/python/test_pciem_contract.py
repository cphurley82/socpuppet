"""🐧 What socpuppet relies on of pciem, on this machine's own bus.

pciem (https://github.com/cakehonolulu/pciem) lets a program be a PCIe
device: `sp.PciemHost` uses it to put a drive on this machine's bus, and
these tests hold it to what PciemHost relies on. They run only where the
doctor's `pciem` area is well (pciem_area.py), and each puts the 🎭
behavioral drive on the bus: one that says it is a device no driver
claims, for what the host sees with no driver in the way, and one that
says it is an NVMe drive, which Linux's own `nvme` driver binds.
"""

import subprocess
import sys

import pytest

from pciem_area import needs_pciem
from processes import environment
from socpuppet.boards.real_host import (
    UNCLAIMED_CLASS,
    RealHost,
    behavioral_drive,
    puppet_function,
)
from this_machine import (
    block_device,
    block_size,
    let_go,
    pumped_until,
    read_block,
    what_the_host_reads,
    write_block,
)

pytestmark = [needs_pciem, pytest.mark.platform]

# The drive's registers, where the NVMe specification has them, and how
# many bytes each takes.
#: CAP, the controller's capabilities.
CAP = (0x00, 8)
#: CMBLOC and CMBSZ, where a controller memory buffer is and how big: none.
CMB = (0x38, 8)
#: The registers the host writes: CC, the configuration, then AQA, ASQ
#: and ACQ, how big the admin queues are and where.
WRITTEN_BY_THE_HOST = ((0x14, 4), (0x24, 0x38 - 0x24))
#: CSTS, the controller's status, and its SHST field, which says how far a
#: shutdown has got: 2 is complete.
CSTS = 0x1C
SHST = 3 << 2
SHUTDOWN_COMPLETE = 2 << 2


#: A drive that is on the bus for as long as it takes to fill its
#: registers with ones, then goes, in a process of its own: a process has
#: one platform, and the test's drive is to be given the memory it left.
SCRIBBLER = """
from socpuppet.boards.real_host import UNCLAIMED_CLASS, RealHost, behavioral_drive
from socpuppet.components import BehavioralNvme
from socpuppet.boards.real_host import puppet_function
from this_machine import scribble_on

board = behavioral_drive(blocks=64, host=RealHost(class_code=UNCLAIMED_CLASS))
board.platform.build()
board.host.start()
scribble_on(puppet_function(), b"\\xff" * BehavioralNvme.mapped_size)
"""


@pytest.fixture
def unclaimed_drive():
    """The behavioral drive on this machine's bus, which no driver claims."""
    return unclaimed_drive_on_the_bus()


@pytest.fixture
def unclaimed_drive_after_a_scribbler():
    """The unclaimed drive, in the memory a drive before it left full of
    ones. pciem gives each drive the first of its memory that is free."""
    subprocess.run(
        [sys.executable, "-c", SCRIBBLER], env=environment(), check=True
    )
    return unclaimed_drive_on_the_bus()


@pytest.fixture
def nvme_drive():
    """The behavioral drive on this machine's bus, which Linux's driver has
    bound, and the name of its namespace's block device. Let go of after."""
    board = behavioral_drive(blocks=64)
    board.platform.build()
    board.host.start()
    function = puppet_function()
    assert pumped_until(board, lambda: block_device(function) is not None)
    yield board, f"/dev/{block_device(function)}"
    let_go(board)


def unclaimed_drive_on_the_bus():
    board = behavioral_drive(
        blocks=64, host=RealHost(class_code=UNCLAIMED_CLASS)
    )
    board.platform.build()
    board.host.start()
    return board


class TestWhenTheDriveIsOnThisMachinesBus:
    def test_the_host_reads_the_capabilities_the_drive_says(
        self, unclaimed_drive
    ):
        board = unclaimed_drive
        offset, size = CAP

        seen = what_the_host_reads(puppet_function(), offset, size)

        assert seen == board.platform.peek(offset, size, via=board.host.bar0)


class TestWhenTheDriveIsGivenMemoryADriveBeforeItLeftFullOfOnes:
    def test_a_register_nobody_wrote_reads_as_zero(
        self, unclaimed_drive_after_a_scribbler
    ):
        # pciem's memory holds whatever was there before: an earlier
        # drive's registers, or, at first, what was in it before boot.
        # Linux reads CMBLOC and CMBSZ, and trips over anything but zero.
        offset, size = CMB

        assert what_the_host_reads(puppet_function(), offset, size) == bytes(
            size
        )


class TestWhenLinuxsOwnDriverBindsTheDrive:
    def test_the_registers_it_wrote_are_on_the_drive_as_it_wrote_them(
        self, nvme_drive
    ):
        board, _ = nvme_drive

        for offset, size in WRITTEN_BY_THE_HOST:
            assert board.platform.peek(
                offset, size, via=board.host.bar0
            ) == what_the_host_reads(puppet_function(), offset, size)

    def test_a_block_written_reads_back_the_same(self, nvme_drive):
        board, device = nvme_drive
        block = bytes(range(256)) * (block_size(device) // 256)

        write_block(board, device, block)

        assert read_block(board, device) == block

    def test_letting_it_go_shuts_the_drive_down(self, nvme_drive):
        board, _ = nvme_drive

        let_go(board)

        assert shutdown_state(board) == SHUTDOWN_COMPLETE


def shutdown_state(board) -> int:
    """How far the drive says a shutdown has got: CSTS.SHST."""
    status = board.platform.peek(CSTS, 4, via=board.host.bar0)
    return int.from_bytes(status, "little") & SHST
