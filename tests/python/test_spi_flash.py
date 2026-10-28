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


#: Where the flash's controller is, and its registers, SiFive's (the
#: FE310's manual has them).
CONTROLLER = 0x100D_0000
CHIP_SELECT_ID = CONTROLLER + 0x10
CHIP_SELECT_MODE = CONTROLLER + 0x18
TRANSMIT = CONTROLLER + 0x48
RECEIVE = CONTROLLER + 0x4C
#: The chip select modes: hold the selected chip's line low, or drive none.
HOLD = 2
OFF = 3
#: Set in the receive register when there was nothing to receive.
RECEIVE_EMPTY = 1 << 31


def master_with_a_flash(script=None, devices=None):
    """A bus master with a flash of FLASH_SIZE bytes, its window at FLASH_BASE.

    `devices` are on the flash's SPI bus beside its chip, by chip select.
    """
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    flash = platform.add(
        "flash", sp.SpiFlash(size=FLASH_SIZE, devices=devices or {})
    )
    platform.connect(cpu.socket, bus.target)
    bus.map(flash.xip, base=FLASH_BASE)
    bus.map(flash.socket, base=CONTROLLER)
    return platform


def select(chip_select):
    """Selects a chip and holds its line low, as Zephyr's driver does."""
    yield sp.write32(CHIP_SELECT_ID, chip_select)
    yield sp.write32(CHIP_SELECT_MODE, HOLD)


def send(byte):
    """Sends a byte and returns its answer, as Zephyr's driver does.

    It gives up after a millisecond, far longer than a byte takes.
    """
    yield sp.write32(TRANSMIT, byte)
    for _ in range(10_000):
        received = yield sp.read32(RECEIVE)
        if not received & RECEIVE_EMPTY:
            return received & 0xFF
        # A driver's look takes time on a real bus; here it has to be made
        # to, or simulated time would never move on to the answer.
        yield sp.wait(sp.ns(100))
    raise AssertionError(f"No answer to {byte:#04x} came back.")


def let_go():
    """Lets the selected chip go, as Zephyr's driver does: no line driven."""
    yield sp.write32(CHIP_SELECT_MODE, OFF)


class NotingDevice:
    """A device on the SPI bus that answers 0x3C and notes what happens."""

    def __init__(self):
        self.happened = []

    def select(self):
        self.happened.append("select")

    def transfer(self, byte):
        self.happened.append(byte)
        return 0x3C

    def deselect(self):
        self.happened.append("deselect")


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


@pytest.mark.platform
class TestWhenPythonIsADeviceOnAFlashsSpiBus:
    def test_it_is_selected_sent_the_byte_its_answer_is_read_and_let_go(self):
        device = NotingDevice()
        answers = []

        def script():
            yield from select(1)
            answers.append((yield from send(0xA5)))
            yield from let_go()

        platform = master_with_a_flash(script, devices={1: device})
        platform.build()

        platform.run()

        assert device.happened == ["select", 0xA5, "deselect"]
        assert answers == [0x3C]


class TestAFlashsWindow:
    def test_is_as_big_as_the_flash(self):
        [window] = [
            each
            for each in master_with_a_flash().address_map()
            if each.port == "xip"
        ]

        assert window.size == FLASH_SIZE
