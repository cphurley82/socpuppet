"""Milestone M14's exit test: a CPU boots from its ROM and a flash.

Until now a CPU woke up with its firmware already in RAM, because Python
put it there. Here nothing is loaded into RAM at all. The CPU's reset
vector is in a boot ROM, whose program asks the system controller where
its image is, finds it in the flash, copies it to RAM and jumps to it.

The firmware is the same image the other milestones' tests load: what is
in the flash is that ELF file, wrapped (`socpuppet.boot_image`). The ROM
is `firmware/rom`, which `firmware/build.sh` builds for each kind of CPU.
"""

import pytest

import socpuppet as sp
from cast import (
    DISK_TEST,
    FROM_THEIR_ROMS,
    GREETING,
    HELLO_WORLD,
    MANAGER,
    ROM_FOR_A_32_BIT_CPU,
    ROM_FOR_A_64_BIT_CPU,
    SSD,
    boot,
)
from link_trace import sent_to_the_io_die
from socpuppet import boot_image
from socpuppet.boards.boot import from_rom
from socpuppet.boards.cpu_kit import BOOT_FLASH_BASE
from socpuppet.boards.host import IO_BASE, RAM_BASE, UART_OFFSET, host
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd
from socpuppet.regs import boot_image_header

SSD_HELLO_WORLD = "hello_world_socpuppet_ssd.elf"
SSD_GREETING = "Hello World! socpuppet_ssd"
#: The ROM copies `hello_world`, which is 12 KiB, in about a millisecond
#: and a half of its CPU's time, and Zephyr greets a millisecond after
#: that. This leaves room and still ends a run that never prints.
LONG_ENOUGH = sp.ms(200)


def a_host_with_a_rom(firmware, **described):
    """The host, built, with the ROM's program in its ROM and nothing else."""
    board = host(boot=from_rom, **described)
    board.platform.build()
    board.platform.load_elf(
        firmware(ROM_FOR_A_64_BIT_CPU), via=board.cpu.socket
    )
    return board


def a_host_with_in_its_flash(image, firmware, **described):
    """The host with a ROM, and `image`, a `BootImage`, in its flash."""
    board = a_host_with_a_rom(firmware, **described)
    board.platform.poke(BOOT_FLASH_BASE, image.to_bytes(), via=board.cpu.socket)
    return board


def a_host_with_hello_world_in_its_flash(firmware, **described):
    """The host with a ROM, and Zephyr's `hello_world` in its flash."""
    return a_host_with_in_its_flash(
        boot_image.from_elf(firmware(HELLO_WORLD)), firmware, **described
    )


@pytest.mark.platform
class TestWhenTheHostBootsFromItsRomWithZephyrsHelloWorldInItsFlash:
    def test_it_prints_its_greeting(self, firmware):
        board = a_host_with_hello_world_in_its_flash(firmware)

        board.platform.run_until(
            lambda: GREETING in board.uart.output, timeout=LONG_ENOUGH
        )

        assert GREETING in board.uart.output

    def test_nothing_was_in_its_ram_before_it_ran(self, firmware):
        # Which is what makes the greeting the ROM's doing.
        image = boot_image.from_elf(firmware(HELLO_WORLD))
        board = a_host_with_in_its_flash(image, firmware)
        empty = bytes(len(image.payload))

        assert board.platform.peek(image.load_address, len(empty)) == empty

    def test_the_rom_says_what_it_loaded_before_zephyr_says_anything(
        self, firmware
    ):
        image = boot_image.from_elf(firmware(HELLO_WORLD))
        board = a_host_with_in_its_flash(image, firmware)

        board.platform.run_until(
            lambda: GREETING in board.uart.output, timeout=LONG_ENOUGH
        )

        first, *_ = board.uart.output.splitlines()
        assert first == (
            f"rom: {image.name}: {len(image.payload)} bytes to "
            f"{image.load_address:#x}, jumping to {image.entry:#x}"
        )

    def test_the_rom_reads_the_whole_program_across_the_link_before_it_speaks(
        self, firmware
    ):
        # The flash is on the IO die and the CPU on the compute die, so
        # every byte of the program crosses the link, a read at a time.
        image = boot_image.from_elf(firmware(HELLO_WORLD))
        board = a_host_with_in_its_flash(image, firmware, trace=True)

        board.platform.run_until(
            lambda: GREETING in board.uart.output, timeout=LONG_ENOUGH
        )

        assert the_flash_read_across_the_link(
            board, before=when_the_host_first_spoke(board)
        ) >= where_the_program_is_in_the_flash(image)


def when_the_host_first_spoke(board):
    """When the first byte for the host's console crossed the link."""
    # An address in a record is the IO die's own, counted from the start
    # of its window.
    return min(
        each.time
        for each in sent_to_the_io_die(board)
        if each.command == "write" and each.address == UART_OFFSET
    )


def the_flash_read_across_the_link(board, before):
    """Each byte of the flash that was read across the link, by its offset."""
    flash = BOOT_FLASH_BASE - IO_BASE
    read = set()
    for each in sent_to_the_io_die(board):
        if each.command == "read" and each.time < before:
            at = each.address - flash
            read.update(range(at, at + len(each.data)))
    return read


def where_the_program_is_in_the_flash(image):
    """The offset in the flash of each byte of an image's program."""
    return set(
        range(
            boot_image_header.SIZE, boot_image_header.SIZE + len(image.payload)
        )
    )


@pytest.mark.platform
class TestWhenTheHostBootsFromItsRomWithNothingInItsFlash:
    def test_the_rom_says_there_is_no_image_and_where_it_looked(self, firmware):
        board = a_host_with_a_rom(firmware)

        # The ROM has spoken within microseconds. The rest is to see that
        # it then says nothing more.
        board.platform.run(sp.ms(10))

        assert board.uart.output == f"rom: no image at {BOOT_FLASH_BASE:#x}\n"


#: A program of an odd number of bytes, none of them zero, so that the last
#: few are not a whole register's worth, and a name that fills its place in
#: the header, with no zero after it. No CPU could run it: where it is
#: "entered" is an address of the host's with nothing at it, and the ROM's
#: CPU stops there.
AN_AWKWARD_IMAGE = boot_image.BootImage(
    name="a_name_that_fills_all_32_bytes__",
    xlen=64,
    load_address=RAM_BASE + 0x1000,
    entry=0x4000_0000,
    payload=bytes(1 + each % 251 for each in range(0x123)),
)


@pytest.mark.platform
class TestWhenTheHostsRomLoadsAnImageOfAnOddLengthWithANameThatFillsItsPlace:
    def test_every_byte_of_the_program_is_in_ram(self, firmware):
        image = AN_AWKWARD_IMAGE
        board = a_host_with_in_its_flash(image, firmware)

        board.platform.run(sp.ms(10))

        assert board.platform.peek(
            image.load_address, len(image.payload) + 8
        ) == image.payload + bytes(8)

    def test_the_rom_says_the_name_and_no_more_than_the_name(self, firmware):
        image = AN_AWKWARD_IMAGE
        board = a_host_with_in_its_flash(image, firmware)

        board.platform.run(sp.ms(10))

        assert board.uart.output.startswith(f"rom: {image.name}: ")


def an_ssd_with_in_its_flash(image_file, firmware):
    """The SSD board with a ROM, and the image of an ELF file in its flash."""
    board = ssd(host=idle_host, boot=from_rom)
    board.platform.build()
    cpu = board.ssd.cpu
    board.platform.load_elf(firmware(ROM_FOR_A_32_BIT_CPU), via=cpu.socket)
    board.platform.poke(
        BOOT_FLASH_BASE, boot_image.wrap(firmware(image_file)), via=cpu.socket
    )
    return board


def an_ssd_with_hello_world_in_its_flash(firmware):
    """The SSD board with a ROM, and Zephyr's `hello_world` in its flash."""
    return an_ssd_with_in_its_flash(SSD_HELLO_WORLD, firmware)


@pytest.mark.platform
class TestWhenAnSsdBootsFromItsRomWithZephyrsHelloWorldInItsFlash:
    # The SSD's CPU is a 32-bit one, with the ROM built for that.

    def test_it_prints_its_greeting(self, firmware):
        board = an_ssd_with_hello_world_in_its_flash(firmware)
        console = board.ssd.cpu_kit.uart

        board.platform.run_until(
            lambda: SSD_GREETING in console.output, timeout=LONG_ENOUGH
        )

        assert SSD_GREETING in console.output

    def test_nothing_was_in_its_sram_before_it_ran(self, firmware):
        image = boot_image.from_elf(firmware(SSD_HELLO_WORLD))
        board = an_ssd_with_hello_world_in_its_flash(firmware)
        empty = bytes(len(image.payload))

        assert (
            board.platform.peek(
                image.load_address, len(empty), via=board.ssd.cpu.socket
            )
            == empty
        )


WATCHDOG_ON_THE_HOST = "watchdog_socpuppet_host.elf"
WATCHDOG_ON_THE_SSD = "watchdog_socpuppet_ssd.elf"
#: What the watchdog firmware says (firmware/watchdog): why it started,
#: each time it does, and what it does between.
RESET_CAUSE = "reset cause: "
RAN_OUT_AND_INTERRUPTED = "watchdog: ran out, and interrupted"
FED = "watchdog: fed "
NO_MORE_FEEDING = "watchdog: no more feeding"
#: What every line of a boot ROM starts with (firmware/rom).
ROM_SAYS = "rom: "
#: How long that firmware's watchdog gives it between feeds, and how many
#: times it is fed: for twice that long, a third of it apart.
PERIOD = sp.ms(90)
FEEDS = 6
#: Three starts, with two periods of feeding and one of waiting in the
#: second. This leaves room and still ends a run that hangs.
LONG_ENOUGH_FOR_THREE_STARTS = sp.ms(1000)


def three_starts_of(console, platform):
    """The story a console tells, run until its firmware has started thrice."""
    story = sp.Transcript(platform, {"cpu": console})
    story.run_until(
        lambda: len(the_causes_in(story)) == 3,
        timeout=LONG_ENOUGH_FOR_THREE_STARTS,
    )
    return story


def the_causes_in(story):
    """Why the firmware says it started, each time it has so far."""
    return [
        line.text.removeprefix(RESET_CAUSE)
        for line in story.lines
        if line.text.startswith(RESET_CAUSE)
    ]


def the_loads_and_starts_in(story):
    """Each time a ROM loaded an image and each time the firmware started."""
    return [
        "load" if line.text.startswith(ROM_SAYS) else "start"
        for line in story.lines
        if line.text.startswith((ROM_SAYS, RESET_CAUSE))
    ]


def said_in(story):
    """Every line of a story, without its time."""
    return [line.text for line in story.lines]


@pytest.fixture
def the_hosts_story(firmware):
    """The host's console while its firmware gets itself reset twice."""
    board = a_host_with_in_its_flash(
        boot_image.from_elf(firmware(WATCHDOG_ON_THE_HOST)), firmware
    )
    return three_starts_of(board.uart, board.platform)


@pytest.mark.platform
class TestWhenTheHostsFirmwareAsksForAResetAndThenStopsFeedingItsWatchdog:
    def test_it_starts_three_times_and_reads_why_each_time(
        self, the_hosts_story
    ):
        assert the_causes_in(the_hosts_story) == [
            "power-on",
            "software",
            "watchdog",
        ]

    def test_a_watchdog_told_to_interrupt_and_not_reset_interrupts_it_when_it_runs_out(
        self, the_hosts_story
    ):
        # The watchdog is on the compute die, and its line goes to that
        # die's own APLIC. The firmware says this only when the interrupt
        # has come.
        assert RAN_OUT_AND_INTERRUPTED in said_in(the_hosts_story)

    def test_its_rom_loads_it_from_the_flash_again_before_each_start(
        self, the_hosts_story
    ):
        assert the_loads_and_starts_in(the_hosts_story) == ["load", "start"] * 3

    def test_the_watchdog_does_not_bite_while_it_is_fed(self, the_hosts_story):
        # It is fed for two periods, so one that took no notice of a feed
        # would have bitten half way.
        said = said_in(the_hosts_story)

        while_fed = said[
            said.index(RESET_CAUSE + "software") : said.index(NO_MORE_FEEDING)
        ]
        assert [text for text in while_fed if text.startswith(FED)] == [
            f"{FED}{fed}" for fed in range(1, FEEDS + 1)
        ]
        assert not [text for text in while_fed if text.startswith(ROM_SAYS)]

    def test_the_watchdog_bites_one_period_after_it_was_last_fed(
        self, the_hosts_story
    ):
        lines = the_hosts_story.lines
        # The ROM says its line when it has copied the image, which takes
        # it as long each time: as long as the first, from power-on at 0.
        rom_takes, *_ = (
            line.time for line in lines if line.text.startswith(ROM_SAYS)
        )
        [last_fed] = [
            line.time for line in lines if line.text == f"{FED}{FEEDS}"
        ]
        [loaded_again] = [
            line.time
            for line in lines[said_in(the_hosts_story).index(NO_MORE_FEEDING) :]
            if line.text.startswith(ROM_SAYS)
        ]

        # To within the time it takes to say a line, and the tenth of a
        # millisecond a console's times come in.
        assert loaded_again - last_fed - rom_takes == pytest.approx(
            PERIOD, abs=sp.us(200)
        )


@pytest.fixture
def the_ssds_story(firmware):
    """An SSD's console while its firmware gets itself reset twice."""
    board = an_ssd_with_in_its_flash(WATCHDOG_ON_THE_SSD, firmware)
    return three_starts_of(board.ssd.cpu_kit.uart, board.platform)


@pytest.mark.platform
class TestWhenAnSsdsFirmwareAsksForAResetAndThenStopsFeedingItsWatchdog:
    # A 32-bit CPU, whose watchdog interrupts at a PLIC and not an APLIC.

    def test_it_starts_three_times_and_reads_why_each_time(
        self, the_ssds_story
    ):
        assert the_causes_in(the_ssds_story) == [
            "power-on",
            "software",
            "watchdog",
        ]

    def test_a_watchdog_told_to_interrupt_and_not_reset_interrupts_it_when_it_runs_out(
        self, the_ssds_story
    ):
        assert RAN_OUT_AND_INTERRUPTED in said_in(the_ssds_story)


@pytest.fixture
def three_cpus_with_roms(firmware):
    """A host whose three CPUs boot from ROMs, built, and nothing run yet.

    Gives the board, and the story its three consoles will tell.
    """
    # 2 MiB of drive, as in M8's own test of the three.
    board = host(drive_blocks=4096, **FROM_THEIR_ROMS)
    story = boot(board, firmware, host=DISK_TEST, manager=MANAGER, ssd=SSD)
    return board, story


@pytest.mark.platform
class TestWhenAllThreeCpusOfAHostBootFromTheirRoms:
    # What the three firmwares then do is M8's, and its exit test runs
    # this way too (test_m8_exit.py).

    def test_nothing_is_in_any_cpus_ram_before_it_runs(
        self, three_cpus_with_roms, firmware
    ):
        board, _ = three_cpus_with_roms

        for image_file, cpu in (
            (DISK_TEST, board.cpu),
            (MANAGER, board.manager.cpu),
            (SSD, board.drive.ssd.cpu),
        ):
            image = boot_image.from_elf(firmware(image_file))
            assert board.platform.peek(
                image.load_address, len(image.payload), via=cpu.socket
            ) == bytes(len(image.payload)), image.name

    def test_the_first_thing_each_cpu_says_is_its_rom_naming_that_cpus_image(
        self, three_cpus_with_roms, firmware
    ):
        _, story = three_cpus_with_roms
        everyone = {"host": DISK_TEST, "manager": MANAGER, "ssd": SSD}

        # The host is the last to speak: it is held until the link is up,
        # five milliseconds in, and its image is the largest and the only
        # one copied across the link. It is a few milliseconds more.
        all_spoke = story.run_until(
            lambda: {line.who for line in story.lines} == set(everyone),
            timeout=LONG_ENOUGH,
        )

        assert all_spoke, said_in(story)
        for who, image_file in everyone.items():
            first, *_ = (line.text for line in story.lines if line.who == who)
            image = boot_image.from_elf(firmware(image_file))
            assert first.startswith(f"{ROM_SAYS}{image.name}: ")
