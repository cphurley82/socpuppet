"""What only 🎭 the Python stand-in for an SSD's firmware does.

What a host sees of an SSD's firmware is in test_ssd_firmware.py, where
the stand-in and the Zephyr application are held to the same tests. These
are about the stand-in as a Python object: it can be asked what is in its
table, and when it cannot go on it raises an error that says why.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.ssd import stand_in_firmware
from socpuppet.regs import flash_controller
from ssd_on_a_bus import NVME_BASE, RAM_BASE, host_with_an_ssd


@pytest.mark.platform
class TestWhenADriverHasWrittenToPagesOfTheSsd:
    # A NAND page is eight of the drive's blocks, so block 504 is in page
    # 63 of the drive and block 0 in page 0. The firmware gives each the
    # next NAND page nobody has, in the order they were first written.
    def test_the_stand_in_can_say_which_nand_page_holds_each(self):
        firmware = stand_in_firmware()

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=504, data=bytes(512))
            yield from nvme.write_blocks(first=0, data=bytes(512))
            yield from nvme.write_blocks(first=505, data=bytes(512))

        platform, _ = host_with_an_ssd(script, firmware=firmware)
        platform.run()

        assert firmware.page_map == {63: 0, 0: 1}


def firmware_with_a_flash_controller_whose_status_is(status):
    """The firmware stand-in alone on a bus, with a memory where the flash
    controller's registers would be, whose status register reads `status`.
    Built."""
    flash = 0x3000
    firmware = sp.SsdFirmware(
        frontend=0x1000, dma=0x2000, flash=flash, buffer=0x4000
    )
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(firmware.script))
    bus = platform.add("bus", sp.Router())
    registers = platform.add("flash", sp.Memory(size=flash_controller.SIZE))
    platform.connect(cpu.socket, bus.target)
    bus.map(registers.socket, base=flash)
    platform.build()
    platform.poke32(flash + flash_controller.STATUS, status)
    return platform


@pytest.mark.platform
class TestWhenTheFlashControllerNeverFinishes:
    def test_the_stand_in_gives_up_and_says_which_device(self):
        platform = firmware_with_a_flash_controller_whose_status_is(
            flash_controller.STATUS_BUSY
        )

        with pytest.raises(RuntimeError, match="0x3000 is still busy"):
            platform.run()


@pytest.mark.platform
class TestWhenTheFlashControllerCannotIdentifyTheNand:
    # With no geometry there is no drive.
    def test_the_stand_in_stops_and_says_so(self):
        platform = firmware_with_a_flash_controller_whose_status_is(
            flash_controller.STATUS_ERROR
        )

        with pytest.raises(RuntimeError, match="identify the NAND"):
            platform.run()
