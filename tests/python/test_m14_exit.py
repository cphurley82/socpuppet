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
from cast import GREETING, HELLO_WORLD
from link_trace import sent_to_the_io_die
from socpuppet import boot_image
from socpuppet.boards.boot import from_rom
from socpuppet.boards.cpu_kit import BOOT_FLASH_BASE
from socpuppet.boards.host import IO_BASE, RAM_BASE, UART_OFFSET, host
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd
from socpuppet.regs import boot_image_header

HOST_ROM = "rom_rv64.elf"
ROM_FOR_A_32_BIT_CPU = "rom_rv32.elf"
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
    board.platform.load_elf(firmware(HOST_ROM), via=board.cpu.socket)
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


def an_ssd_with_hello_world_in_its_flash(firmware):
    """The SSD board with a ROM, and Zephyr's `hello_world` in its flash."""
    board = ssd(host=idle_host, boot=from_rom)
    board.platform.build()
    cpu = board.ssd.cpu
    board.platform.load_elf(firmware(ROM_FOR_A_32_BIT_CPU), via=cpu.socket)
    board.platform.poke(
        BOOT_FLASH_BASE,
        boot_image.wrap(firmware(SSD_HELLO_WORLD)),
        via=cpu.socket,
    )
    return board


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
