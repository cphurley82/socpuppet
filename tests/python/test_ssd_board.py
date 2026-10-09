"""The SSD as a board: how it is described, before anything is simulated."""

import pytest

import socpuppet as sp
from socpuppet.boards.drive import DEVICE_ID, NVME_CLASS, VENDOR_ID
from socpuppet.boards.scripted_host import ECAM_BASE
from socpuppet.boards.ssd import ssd, stand_in_firmware
from socpuppet.pcie_host import PcieFunction


def nothing():
    """A host that does nothing."""
    yield from ()


class TestAnSsdOfSoManyBlocks:
    # A NAND page is eight of the drive's blocks, and 64 pages make a NAND
    # block: 512 of the drive's blocks.
    def test_has_a_nand_of_that_many_blocks_in_whole_nand_blocks(self):
        board = ssd(
            host=nothing, blocks=2048, firmware=stand_in_firmware().script
        )

        assert board.ssd.nand.component.parameters == {
            "blocks": 4,
            "pages_per_block": 64,
            "page_size": 4096,
        }

    @pytest.mark.parametrize("blocks", [100, 513])
    def test_is_refused_if_that_is_not_whole_nand_blocks(self, blocks):
        with pytest.raises(
            ValueError, match=rf"\b{blocks} blocks were asked for"
        ) as refused:
            ssd(
                host=nothing, blocks=blocks, firmware=stand_in_firmware().script
            )

        assert "512, or a multiple of it" in str(refused.value)

    def test_is_refused_if_that_is_no_blocks_at_all(self):
        with pytest.raises(ValueError, match="at least one"):
            ssd(host=nothing, blocks=0, firmware=stand_in_firmware().script)


class TestAnSsdWithNothingInItsCpusPlace:
    # 🚧 Until the SSD has a CPU model of its own.
    def test_is_refused_and_the_error_says_what_to_put_there(self):
        with pytest.raises(NotImplementedError, match="stand_in_firmware"):
            ssd(host=nothing)


@pytest.mark.platform
class TestWhenAHostScansThePcieBusTheSsdIsOn:
    # So that a host, and its driver, cannot tell the two apart by looking.
    def test_it_finds_what_the_stand_in_drive_says_it_is(self):
        found = []

        def host():
            found.extend((yield from sp.PcieHost(ecam=ECAM_BASE).scan()))

        board = ssd(host=host, firmware=stand_in_firmware().script)
        board.platform.build()

        board.platform.run()

        assert found == [
            PcieFunction(
                bus=0,
                device=0,
                function=0,
                vendor_id=VENDOR_ID,
                device_id=DEVICE_ID,
                class_code=NVME_CLASS,
            )
        ]


class TestTheScriptedHostInFrontOfTheSsd:
    # So that a script written for one host finds its way around the other.
    def test_has_its_devices_where_the_real_host_board_has_them(self):
        from socpuppet.boards import host, scripted_host

        assert scripted_host.RAM_BASE == host.RAM_BASE
        assert scripted_host.MSI_BASE == host.MSI_BASE
        assert scripted_host.ECAM_BASE == host.IO_BASE + host.ECAM_OFFSET
        assert (
            scripted_host.PCIE_WINDOW_BASE
            == host.IO_BASE + host.PCIE_WINDOW_OFFSET
        )
