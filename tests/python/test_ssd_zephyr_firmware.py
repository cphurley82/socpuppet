"""What the SSD's Zephyr firmware says for itself, on its console.

What a host sees of the firmware is in test_ssd_firmware.py, where the
Zephyr application in firmware/ssd and 🎭 its Python stand-in are held to
the same tests. A console is something only the real one has.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.cpu_kit import (
    PLIC_BASE,
    SRAM_BASE,
    SRAM_SIZE,
    TIMER_BASE,
    TIMER_HZ,
    UART_BASE,
)
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import FLASH_BASE, ssd
from socpuppet.regs import flash_controller
from ssd_zephyr_firmware import BANNER
from ssd_zephyr_firmware import IMAGE as SSD_IMAGE

# The drive's blocks are 512 bytes, and there are this many in a GiB.
BLOCKS_PER_GIB = (1 << 30) // 512


def console_of_an_ssd(firmware, *, blocks, until, and_then=0):
    """Boots the firmware on an SSD of `blocks` blocks, with an idle host.

    Runs until `until` is on the console and for `and_then` longer, and
    returns all that is there.
    """
    board = ssd(host=idle_host, blocks=blocks)
    board.platform.build()
    board.platform.load_elf(firmware(SSD_IMAGE), via=board.ssd.cpu.socket)
    console = board.ssd.cpu_kit.uart
    # The firmware starts by making an empty table of the drive's pages,
    # which takes it about half a microsecond of simulated time a page:
    # a quarter of a second for 2 GiB. A second leaves room and still ends
    # a run that never prints.
    board.platform.run_until(
        lambda: until in console.output, timeout=sp.ms(1000)
    )
    board.platform.run(and_then)
    return console.output


@pytest.mark.platform
class TestWhenTheSsdsFirmwareStarts:
    def test_it_says_what_drive_it_found(self, firmware):
        # 512 blocks of 512 bytes are 64 NAND pages of 4 KiB.
        banner = f"{BANNER} 64 pages of 4096 bytes\r\n"

        assert banner in console_of_an_ssd(firmware, blocks=512, until=banner)


@pytest.mark.platform
class TestWhenTheNandIsBiggerThanZephyrsFlashApiCanReach:
    """Zephyr names a place on a flash with an `off_t`.

    On a 32-bit CPU that is 32 bits and signed, so the last place it can
    name is just short of 2 GiB (docs/upstream.md).
    """

    def test_the_firmware_says_so_and_stops(self, firmware):
        refusal = (
            "The NAND is 3072 MiB, and Zephyr's flash API reaches only "
            "the first 2048 MiB of one on this CPU."
        )

        # Firmware that carried on would make its table next, which takes
        # it 0.4 s of simulated time for a drive this size, and then say
        # what drive it is. 0.6 s is time for both.
        said = console_of_an_ssd(
            firmware,
            blocks=3 * BLOCKS_PER_GIB,
            until=refusal,
            and_then=sp.ms(600),
        )

        assert refusal in said
        assert "a drive of" not in said

    def test_a_nand_of_exactly_what_it_can_reach_is_a_drive(self, firmware):
        banner = "a drive of 524288 pages of 4096 bytes\r\n"

        said = console_of_an_ssd(
            firmware, blocks=2 * BLOCKS_PER_GIB, until=banner
        )

        assert banner in said


# The flash controller's registers that these tests set, and the bits of
# its status: its register map's own names for them.
STATUS = flash_controller.STATUS
PAGE_SIZE = flash_controller.PAGE_SIZE
PAGES_PER_BLOCK = flash_controller.PAGES_PER_BLOCK
BLOCKS = flash_controller.BLOCKS
DONE = flash_controller.STATUS_DONE
ERROR = flash_controller.STATUS_ERROR
BUSY = flash_controller.STATUS_BUSY


def console_with_a_flash_controller_that_says(registers, firmware):
    """Boots the firmware with something broken where its NAND should be.

    It is the SSD's CPU with what a CPU needs, and a memory where the
    flash controller's registers would be. `registers` is what they read,
    by offset, whatever the firmware tells them. Runs until the firmware
    says it stops, and returns all that is on the console.
    """
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.DbtRiseCpu(xlen=32, reset_vector=SRAM_BASE))
    bus = platform.add("bus", sp.Router())
    sram = platform.add("sram", sp.Memory(size=SRAM_SIZE))
    console = platform.add("uart", sp.Ns16550())
    timer = platform.add("timer", sp.MachineTimer(frequency_hz=TIMER_HZ))
    plic = platform.add("plic", sp.Plic())
    flash = platform.add("flash", sp.Memory(size=flash_controller.SIZE))
    platform.connect(cpu.socket, bus.target)
    bus.map(sram.socket, base=SRAM_BASE)
    bus.map(console.socket, base=UART_BASE)
    bus.map(timer.socket, base=TIMER_BASE)
    bus.map(plic.socket, base=PLIC_BASE)
    bus.map(flash.socket, base=FLASH_BASE)
    platform.connect(plic.irq, cpu.irq)
    platform.connect(timer.irq, cpu.timer_irq)
    platform.build()
    platform.load_elf(firmware(SSD_IMAGE))
    for offset, value in registers.items():
        platform.poke32(FLASH_BASE + offset, value)
    # The firmware gives a device a tenth of a second of simulated time to
    # answer. A second is time for that and still ends a run that never
    # prints.
    platform.run_until(lambda: STOPS in console.output, timeout=sp.ms(1000))
    return console.output


#: What the firmware says last when it has no NAND to be a drive with.
STOPS = (
    "The flash controller's driver did not start (it says why above), so "
    "there is no NAND.\r\nThe SSD's firmware stops.\r\n"
)


def reason_and_what_follows(said):
    """What a console says from the driver's reason on, without Zephyr's
    banner, which comes between the reason and the firmware's last words:
    drivers start before Zephyr says it is booting. "E:" is how Zephyr
    marks an error in its log."""
    reason, _, rest = said.partition("*** Booting Zephyr OS")
    return reason + rest.partition("\r\n")[2]


@pytest.mark.platform
class TestWhenTheFlashControllerCannotIdentifyTheNand:
    # With no geometry there is no drive.
    def test_the_firmware_says_so_and_stops(self, firmware):
        said = console_with_a_flash_controller_that_says(
            {STATUS: ERROR}, firmware
        )

        assert reason_and_what_follows(said) == (
            "E: The flash controller could not identify its NAND.\r\n" + STOPS
        )


@pytest.mark.platform
class TestWhenTheFlashControllerNeverFinishes:
    def test_the_firmware_gives_up_says_so_and_stops(self, firmware):
        said = console_with_a_flash_controller_that_says(
            {STATUS: BUSY}, firmware
        )

        assert reason_and_what_follows(said) == (
            "E: The flash controller did not answer in 100 ms.\r\n" + STOPS
        )


@pytest.mark.platform
class TestWhenTheNandsPagesAreBiggerThanTheDriverWasBuiltFor:
    """The driver keeps one NAND page of its own, of a size fixed when it
    is built: 4096 bytes, unless the firmware's configuration says more."""

    def test_the_firmware_says_what_to_change_and_stops(self, firmware):
        said = console_with_a_flash_controller_that_says(
            {STATUS: DONE, PAGE_SIZE: 8192, PAGES_PER_BLOCK: 64, BLOCKS: 1},
            firmware,
        )

        assert reason_and_what_follows(said) == (
            "E: The NAND's pages are 8192 bytes, and this driver was built "
            "for pages of up to 4096. Build the firmware with a bigger "
            "CONFIG_SOCPUPPET_FLASH_CONTROLLER_LARGEST_PAGE.\r\n" + STOPS
        )
