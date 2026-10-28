"""🧵 Python at the far end of a GPIO's pins.

What the GPIO does with its registers is held in C++
(`tests/cpp/contracts/gpio_contract.h`). These tests are of what Python
sees of its pins, and does to them, while a script drives the registers as
firmware would.
"""

import pytest

import socpuppet as sp

#: Each test builds a platform, which a process can do once.
pytestmark = pytest.mark.platform

GPIO_BASE = 0x1000_0000
#: SiFive's GPIO registers, a bit for each pin (the FE310's manual has
#: them).
VALUE = GPIO_BASE + 0x00
OUTPUT_ENABLE = GPIO_BASE + 0x08
PORT = GPIO_BASE + 0x0C
#: How long the tests give a pin to settle after a change: the far end
#: hears of it a delta cycle on, and firmware reads what it drives a delta
#: cycle after that.
A_MOMENT = sp.ns(1)


def master_with_a_gpio(script):
    """A bus master running `script`, with a GPIO at GPIO_BASE."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    gpio = platform.add("gpio", sp.Gpio())
    platform.connect(cpu.socket, bus.target)
    bus.map(gpio.socket, base=GPIO_BASE)
    return platform, gpio


class TestWhenFirmwareMakesAPinAnOutput:
    def test_python_sees_nothing_driven_and_then_what_the_port_says(self):
        seen = []

        def script():
            seen.append(gpio.level(3))
            yield sp.write32(OUTPUT_ENABLE, 1 << 3)
            yield sp.write32(PORT, 1 << 3)
            seen.append(gpio.level(3))

        platform, gpio = master_with_a_gpio(script)
        platform.build()

        platform.run()

        assert seen == [None, True]


class TestWhenPythonDrivesAPin:
    def test_firmware_reads_it_in_the_value_register(self):
        read = []

        def script():
            gpio.drive(5, True)
            yield sp.wait(A_MOMENT)
            read.append((yield sp.read32(VALUE)))

        platform, gpio = master_with_a_gpio(script)
        platform.build()

        platform.run()

        (value,) = read
        assert value & (1 << 5)


class TestWhenWhatAPinDrivesChanges:
    def test_python_is_told_the_pin_and_its_level_in_order(self):
        def script():
            yield sp.write32(OUTPUT_ENABLE, 1 << 3)
            yield sp.write32(PORT, 1 << 3)
            yield sp.write32(OUTPUT_ENABLE, 0)
            # For the last change to reach the listener before the run ends.
            yield sp.wait(A_MOMENT)

        platform, gpio = master_with_a_gpio(script)
        changes = []
        platform.build()
        gpio.on_change(lambda pin, level: changes.append((pin, level)))

        platform.run()

        assert changes == [(3, False), (3, True), (3, None)]

    def test_a_pin_python_drives_in_answer_reads_so_to_firmware(self):
        # 🎓 A wire from one pin to another, as a board's loopback has.
        read = []

        def script():
            yield sp.write32(OUTPUT_ENABLE, 1 << 0)
            yield sp.write32(PORT, 1 << 0)
            yield sp.wait(A_MOMENT)
            read.append((yield sp.read32(VALUE)))

        platform, gpio = master_with_a_gpio(script)
        platform.build()
        gpio.on_change(
            lambda pin, level: gpio.drive(1, level) if pin == 0 else None
        )

        platform.run()

        (value,) = read
        assert value & (1 << 1)


class TestAPinAGpioHasNot:
    def test_is_refused_and_the_error_gives_the_pins_it_has(self):
        platform, gpio = master_with_a_gpio(None)
        platform.build()

        with pytest.raises(IndexError, match="pins 0 to 31"):
            gpio.drive(32, True)
