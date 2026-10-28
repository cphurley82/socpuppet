"""🐧 The drives with this machine as their host, as they are described.

Before anything is simulated, so these run anywhere: describing a
`PciemHost` opens nothing. tests/python/test_pciem_contract.py and
test_this_machines_linux_mounts_the_ssd.py put the drives on this machine's bus.
"""

from typing import NamedTuple

import pytest

import socpuppet as sp
from socpuppet.boards.drive import DEVICE_ID, NVME_CLASS, VECTORS, VENDOR_ID
from socpuppet.boards.real_host import (
    UNCLAIMED_CLASS,
    RealHost,
    behavioral_drive,
    this_machine,
)
from socpuppet.boards.ssd import ssd
from socpuppet.placed import Placed
from wiring import implementations_in, what_drives


class ADrive(NamedTuple):
    """A drive's board, its host, and its NVMe function."""

    platform: sp.Platform
    host: Placed
    function: Placed


@pytest.fixture(params=["the ssd", "the behavioral drive"])
def drive(request):
    """A drive with this machine as its host: the SSD, or the stand-in."""
    if request.param == "the ssd":
        board = ssd(host=this_machine)
        return ADrive(board.platform, board.host, board.ssd.frontend)
    board = behavioral_drive(blocks=64)
    return ADrive(board.platform, board.host, board.nvme)


class TestADriveWithThisMachineAsItsHost:
    def test_has_a_pciem_host_that_says_it_is_the_puppets_nvme_drive(
        self, drive
    ):
        host = drive.host.component

        assert isinstance(host, sp.PciemHost)
        assert (host.vendor_id, host.device_id, host.class_code) == (
            VENDOR_ID,
            DEVICE_ID,
            NVME_CLASS,
        )
        assert host.vectors == VECTORS

    def test_the_host_reaches_the_drives_registers_and_no_more(self, drive):
        assert what_drives(drive.platform, drive.function.bar0) == [
            drive.host.bar0.path
        ]
        assert drive.host.component.function_size == (
            drive.function.component.size_at("bar0")
        )

    def test_each_of_the_drives_interrupt_lines_goes_to_the_host(self, drive):
        for vector in range(VECTORS):
            assert what_drives(
                drive.platform, getattr(drive.host, f"irq{vector}")
            ) == [getattr(drive.function, f"irq{vector}").path]

    def test_has_no_pcie_endpoint_and_no_scripted_host(self, drive):
        implementations = implementations_in(drive.platform)

        assert sp.PcieEndpoint.implementation not in implementations
        assert sp.ScriptedBusMaster.implementation not in implementations


class TestTheSsdWithThisMachineAsItsHost:
    def test_its_dma_goes_up_to_the_host_through_the_ssds_one_way_up(self):
        board = ssd(host=this_machine)

        (source,) = what_drives(board.platform, board.host.dma)
        assert source.startswith(board.ssd.uplink.path + ".")

    def test_refuses_a_trace_since_there_is_no_scripted_host_to_record(self):
        with pytest.raises(ValueError, match=r"trace.*scripted host"):
            ssd(host=this_machine, trace=True)  # type: ignore[call-overload]


class TestTheBehavioralDriveWithThisMachineAsItsHost:
    def test_its_dma_goes_straight_to_the_host(self):
        board = behavioral_drive(blocks=64)

        assert what_drives(board.platform, board.host.dma) == [
            board.nvme.dma.path
        ]

    def test_can_say_it_is_a_device_no_driver_of_the_hosts_claims(self):
        board = behavioral_drive(
            blocks=64, host=RealHost(class_code=UNCLAIMED_CLASS)
        )

        assert board.host.component.class_code == UNCLAIMED_CLASS
