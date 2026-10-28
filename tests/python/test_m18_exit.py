"""M18's exit: the small essentials, under Zephyr's own samples and tests.

The host's boot flash is SiFive's SPI controller with a W25Q-kind chip of
socpuppet's behind it, on the IO die:

    compute.cpu ─▶ ... ─▶ io.bus ─┬─▶ io.uart              (the console)
                                  └─▶ io.boot_flash.socket (the controller)
                                        └─ chip select 0: the chip

Each image is one of Zephyr's own, built for `socpuppet_host`, and drives
the flash through Zephyr's own drivers, `spi_sifive` and `spi_nor`.

🐧 Then Linux, a stock kernel, drives the same flash through its own
drivers (`test_linux_boot_flash.py`, which is handed out with the other
boots).
"""

import itertools

import pytest

import socpuppet as sp
from cast import boot
from processes import run_socpuppet
from socpuppet import ztest
from socpuppet.boards.host import (
    GPIO_LED,
    GPIO_LOOPBACK_WIRES,
    I2C_RAM_ADDRESS,
    SPI_LOOPBACK_CHIP_SELECT,
    host,
)
from socpuppet.i2c import Ram
from socpuppet.spi import Loopback

#: Zephyr's `samples/drivers/spi_flash`.
SPI_FLASH = "spi_flash_socpuppet_host.elf"
#: Zephyr's `tests/drivers/spi/spi_loopback`, with the shield that puts its
#: two devices on the boot flash's bus, at chip select 1.
SPI_LOOPBACK = "spi_loopback_socpuppet_host.elf"
#: Zephyr's `tests/drivers/gpio/gpio_basic_api`, with the shield that names
#: its two pins: one it drives, and one wired to it that it reads.
GPIO_BASIC_API = "gpio_basic_api_socpuppet_host.elf"
#: Zephyr's `tests/drivers/i2c/i2c_ram`, with the shield that names the
#: I2C controller whose bus its RAM is on.
I2C_RAM = "i2c_ram_socpuppet_host.elf"
#: Zephyr's `samples/basic/blinky`, which blinks the board's LED.
BLINKY = "blinky_socpuppet_host.elf"
#: What the sample says when it passes, in order: its `sample.yaml` has them
#: as the lines its console must show. Copied here, as `cast.GREETING` is:
#: CI's test job has the images and not Zephyr's tree to read them from.
WHAT_THE_SPI_FLASH_SAMPLE_SAYS = (
    "Test 1: Flash erase",
    "Flash erase succeeded!",
    "Test 2: Flash write",
    "Attempting to write 4 bytes",
    "Data read matches data written. Good!!",
)
#: The sample is done in 4.8 ms of simulated time; about ten times that
#: still ends a run that never is.
LIMIT = sp.ms(50)
#: The loopback test gives its verdict at 473 ms of simulated time; about
#: twice that leaves room for the quantum to move its timed transfers, and
#: still ends a run that never gives one.
LOOPBACK_LIMIT = sp.ms(1000)
#: The I2C test gives its verdict at 15.5 ms of simulated time, its bytes
#: taking their time on a bus of 100 kHz; about six times that still ends
#: a run that never gives one.
I2C_LIMIT = sp.ms(100)
#: Blinky turns its LED over a second apart, from boot on: its four
#: changes take two seconds, and twice that ends a run that never makes
#: them.
BLINKY_LIMIT = sp.ms(4000)
#: The GPIO test gives its verdict at 19.7 s of simulated time, most of it
#: the sleeps of its tests of interrupts; about twice that still ends a run
#: that never gives one.
GPIO_LIMIT = sp.ms(40_000)


@pytest.mark.platform
class TestWhenZephyrsSpiFlashSampleRunsOnTheHostsBootFlash:
    def test_it_erases_writes_and_reads_back_through_zephyrs_own_drivers(
        self, firmware
    ):
        board = host()
        boot(board, firmware, host=SPI_FLASH)

        board.platform.run_until(
            lambda: WHAT_THE_SPI_FLASH_SAMPLE_SAYS[-1] in board.uart.output,
            timeout=LIMIT,
        )

        assert heard_in_order(board.uart.output) == list(
            WHAT_THE_SPI_FLASH_SAMPLE_SAYS
        )


@pytest.mark.platform
class TestWhenZephyrsSpiLoopbackTestRunsWithPythonAtTheFarEnd:
    def test_it_gives_a_verdict_and_nothing_failed(self, firmware):
        # 🧵 Python is the wire from the controller's data out to its data
        # in, which the test wants a board to have.
        board = host(boot_flash_devices={SPI_LOOPBACK_CHIP_SELECT: Loopback()})
        boot(board, firmware, host=SPI_LOOPBACK)

        board.platform.run_until(
            lambda: ztest.verdict_of(board.uart.output) is not None,
            timeout=LOOPBACK_LIMIT,
        )

        assert ztest.parse(board.uart.output).passed, board.uart.output


@pytest.mark.platform
class TestWhenZephyrsGpioTestRunsWithPythonWiringItsPins:
    def test_it_gives_a_verdict_and_nothing_failed(self, firmware):
        # 🧵 Python is the wire from the pin the test drives to the pin it
        # reads, which the test wants a board to have.
        board = host(gpio_wires=GPIO_LOOPBACK_WIRES)
        boot(board, firmware, host=GPIO_BASIC_API)

        board.platform.run_until(
            lambda: ztest.verdict_of(board.uart.output) is not None,
            timeout=GPIO_LIMIT,
        )

        assert ztest.parse(board.uart.output).passed, board.uart.output


@pytest.mark.platform
class TestWhenZephyrsBlinkySampleRuns:
    def test_the_led_is_lit_and_then_goes_off_and_on_each_second(
        self, firmware
    ):
        # 🎓 It lights the LED as it makes its pin an output, and then
        # turns it the other way, a second between each.
        board = host()
        boot(board, firmware, host=BLINKY)
        changes = changes_of_pin(board, GPIO_LED)

        board.platform.run_until(
            lambda: len(changes) == 4, timeout=BLINKY_LIMIT
        )

        levels = [level for _, level in changes]
        times = [at for at, _ in changes]
        assert levels == [True, False, True, False]
        assert [b - a for a, b in itertools.pairwise(times[1:])] == [
            pytest.approx(sp.ms(1000), abs=sp.ms(10))
        ] * 2


@pytest.mark.platform
class TestWhenZephyrsI2cRamTestRunsWithPythonsRamOnTheBus:
    def test_it_gives_a_verdict_and_nothing_failed(self, firmware):
        # 🧵 Python is the RAM at the address the test talks to.
        board = host(i2c_devices={I2C_RAM_ADDRESS: Ram()})
        boot(board, firmware, host=I2C_RAM)

        board.platform.run_until(
            lambda: ztest.verdict_of(board.uart.output) is not None,
            timeout=I2C_LIMIT,
        )

        assert ztest.parse(board.uart.output).passed, board.uart.output


class TestWhenZephyrsI2cRamTestIsRunAsTwisterRunsIt:
    def test_the_shield_puts_pythons_ram_on_the_bus_and_nothing_failed(
        self, firmware
    ):
        result = run_socpuppet(
            "run",
            str(firmware(I2C_RAM)),
            "--board",
            "socpuppet_host",
            "--shield",
            "socpuppet_host_i2c_ram",
        )

        assert ztest.parse(result.stdout).passed, result.stdout


class TestWhenZephyrsGpioTestIsRunAsTwisterRunsIt:
    def test_the_shield_wires_its_pins_and_nothing_failed(self, firmware):
        result = run_socpuppet(
            "run",
            str(firmware(GPIO_BASIC_API)),
            "--board",
            "socpuppet_host",
            "--shield",
            "socpuppet_host_gpio_loopback",
        )

        assert ztest.parse(result.stdout).passed, result.stdout


class TestWhenZephyrsSpiLoopbackTestIsRunAsTwisterRunsIt:
    def test_the_shield_puts_python_at_the_far_end_and_nothing_failed(
        self, firmware
    ):
        # `socpuppet run` with the shield is how twister runs the image.
        result = run_socpuppet(
            "run",
            str(firmware(SPI_LOOPBACK)),
            "--board",
            "socpuppet_host",
            "--shield",
            "socpuppet_host_spi_loopback",
        )

        assert ztest.parse(result.stdout).passed, result.stdout


def changes_of_pin(board, pin):
    """The (time, level) of each change the host's GPIO makes to `pin`."""
    changes = []

    def heard(changed, level):
        if changed == pin:
            changes.append((board.platform.time, level))

    board.gpio.on_change(heard)
    return changes


def heard_in_order(output):
    """The sample's pass lines that `output` has, in the order it has them."""
    return [
        expected
        for line in output.splitlines()
        for expected in WHAT_THE_SPI_FLASH_SAMPLE_SAYS
        if expected in line
    ]
