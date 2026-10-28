"""An I2C controller on a platform, with Python's devices on its bus.

What the controller does with its registers is held in C++
(`tests/cpp/unit/i2c_controller_logic_test.cpp`). These tests are of a
script driving it as firmware would.
"""

import pytest

import socpuppet as sp
from socpuppet.i2c import Ram
from socpuppet.regs import i2c_controller as regs

CONTROLLER = 0x1000_0000
#: The RAM's address on the bus, as Zephyr's i2c_ram test has it.
RAM = 0x51
#: The controller at 100 kHz: its clock over 5 (prescale + 1).
PRESCALE = sp.I2cController.CLOCK_HZ // (5 * 100_000) - 1
#: A start, which is written with the byte after it, the address.
START = regs.COMMAND_START | regs.COMMAND_WRITE
#: 🎓 The bit of the address's byte that makes the transfer a read.
READ = 1


@pytest.mark.platform
class TestWhenAScriptWritesToARamOnTheBusAndReadsItBack:
    def test_the_ram_holds_the_byte_and_gives_it_back(self):
        ram = Ram()
        received = []

        def script():
            yield from switch_on_at_100_khz()
            yield from write_to(RAM, 0x0102, 0xA5)
            received.append((yield from read_from(RAM, 0x0102)))

        platform = master_with_a_controller(script, {RAM: ram})
        platform.build()

        platform.run()

        assert ram.memory[0x0102] == 0xA5
        assert received == [0xA5]


def master_with_a_controller(script, devices):
    """A bus master running `script`, with a controller and its `devices`."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    controller = platform.add("i2c", sp.I2cController(devices=devices))
    platform.connect(cpu.socket, bus.target)
    bus.map(controller.cpu, base=CONTROLLER)
    return platform


def switch_on_at_100_khz():
    """Switches the controller on, its bus at 100 kHz, as Zephyr's driver
    does."""
    yield sp.write32(CONTROLLER + regs.PRESCALE_LOW, PRESCALE & 0xFF)
    yield sp.write32(CONTROLLER + regs.PRESCALE_HIGH, PRESCALE >> 8)
    yield sp.write32(CONTROLLER + regs.CONTROL, regs.CONTROL_ENABLE)


def write_to(device, address, byte):
    """Writes `byte` at `address` of the RAM at `device`, and stops."""
    yield from command(START, device << 1)
    yield from command(regs.COMMAND_WRITE, address >> 8)
    yield from command(regs.COMMAND_WRITE, address & 0xFF)
    yield from command(regs.COMMAND_WRITE | regs.COMMAND_STOP, byte)


def read_from(device, address):
    """Reads the byte at `address` of the RAM at `device`: its address
    written, and then a start again, to read the one byte."""
    yield from command(START, device << 1)
    yield from command(regs.COMMAND_WRITE, address >> 8)
    yield from command(regs.COMMAND_WRITE, address & 0xFF)
    yield from command(START, device << 1 | READ)
    yield from command(
        regs.COMMAND_READ | regs.COMMAND_NACK | regs.COMMAND_STOP
    )
    return (yield sp.read32(CONTROLLER + regs.RECEIVE))


def command(bits, byte=0):
    """Gives the controller a command, as Zephyr's driver does, and waits
    until it is done.

    It gives up after ten milliseconds, far longer than a byte at 100 kHz
    (90 µs) takes.
    """
    yield sp.write32(CONTROLLER + regs.TRANSMIT, byte)
    yield sp.write32(CONTROLLER + regs.COMMAND, bits)
    for _ in range(1_000):
        status = yield sp.read32(CONTROLLER + regs.STATUS)
        if not status & regs.STATUS_TRANSFER_IN_PROGRESS:
            return
        # A driver's look takes time on a real bus; here it has to be made
        # to, or simulated time would never move on to the end of the byte.
        yield sp.wait(sp.us(10))
    raise AssertionError(f"Command {bits:#04x} was still in progress.")
