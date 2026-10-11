"""A flash on a platform: filled from a file, and read like memory.

What the model does with each kind of access is held in C++
(`tests/cpp/platform/spi_flash_test.cpp`). These tests are of what a
description and a script see of it.
"""

import pytest

import socpuppet as sp

FLASH_BASE = 0x1020_0000
#: Not a page, which is what the controller's registers take: a window
#: of the wrong one of the two sizes would show.
FLASH_SIZE = 0x2000
SPAM = bytes.fromhex("5350414d2c207370616d21")


def master_with_a_flash(script=None):
    """A bus master with a flash of FLASH_SIZE bytes, its window at FLASH_BASE."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    flash = platform.add("flash", sp.SpiFlash(size=FLASH_SIZE))
    platform.connect(cpu.socket, bus.target)
    bus.map(flash.xip, base=FLASH_BASE)
    bus.map(flash.socket, base=0x100D_0000)
    return platform


@pytest.mark.platform
class TestWhenAFileIsLoadedIntoAFlash:
    def test_its_bus_master_reads_the_files_bytes_through_the_window(
        self, tmp_path
    ):
        image = tmp_path / "spam.img"
        image.write_bytes(SPAM)
        read = []

        def script():
            read.append((yield sp.read32(FLASH_BASE + 0x10)))

        platform = master_with_a_flash(script)
        platform.build()
        platform.load_binary(image, at=FLASH_BASE + 0x10)

        platform.run()

        assert read == [int.from_bytes(SPAM[:4], "little")]


@pytest.mark.platform
class TestWhenAFlashsBusMasterWritesThroughItsWindow:
    def test_the_run_stops_with_a_bus_error_that_gives_the_address(self):
        def script():
            yield sp.write32(FLASH_BASE + 0x10, 0xDEAD_BEEF)

        platform = master_with_a_flash(script)
        platform.build()

        with pytest.raises(sp.BusError, match="0x10200010"):
            platform.run()


class TestAFlashsWindow:
    def test_is_as_big_as_the_flash(self):
        [window] = [
            each
            for each in master_with_a_flash().address_map()
            if each.port == "xip"
        ]

        assert window.size == FLASH_SIZE
