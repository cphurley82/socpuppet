"""The stage before OpenSBI hands it two registers, as OpenSBI expects.

🎓 Every RISC-V stage of a boot starts the next with the hart's number in
`a0` and the address of a devicetree in `a1`: OpenSBI takes them so, and
so does what OpenSBI starts. socpuppet's boot ROM does it with the
argument an image's header carries, and 🎭 for a boot with no ROM program
QEMU's reset vector does it, a few instructions in the ROM that load the
two and jump.

⚠️ Every socpuppet CPU is hart 0, and a register starts at zero, so the
`a0` half of these checks would pass if nothing wrote it. The `a1` half
is the one that can fail.
"""

import pytest

import socpuppet as sp
from cast import ROM_FOR_A_64_BIT_CPU
from riscv_program import ARGUMENTS_AT, stores_its_arguments
from socpuppet.boards import host as the_host
from socpuppet.boards.boot import ROM_BASE, from_rom, reset_stub
from socpuppet.boot_image import BootImage

#: An argument with something in both halves.
ARGUMENT = 0x12_8220_0000
#: Where the platforms the stub starts have their RAM.
RAM = 0x8000_0000
#: Long enough for the ROM to copy a few instructions and jump, and for
#: them to run. The ROM checks its image a byte at a time.
LONG_ENOUGH = sp.ms(1)


@pytest.mark.platform
class TestWhenTheRomStartsAnImageThatCarriesAnArgument:
    def test_the_program_finds_the_harts_number_in_a0_and_the_argument_in_a1(
        self, firmware
    ):
        board = a_host_whose_rom_starts(
            the_program(argument=ARGUMENT), firmware
        )

        assert what_the_host_was_handed(board) == (0, ARGUMENT)


@pytest.mark.platform
class TestWhenTheRomStartsAnImageWithNoArgument:
    def test_the_program_finds_zero_in_a1(self, firmware):
        board = a_host_whose_rom_starts(the_program(), firmware)

        _, a1 = what_the_host_was_handed(board)
        assert a1 == 0


@pytest.mark.platform
class TestWhenQemusResetVectorStartsAProgramOnA64BitCpu:
    def test_the_program_finds_the_harts_number_in_a0_and_the_argument_in_a1(
        self,
    ):
        platform = a_cpu_started_by_the_reset_stub(xlen=64, argument=ARGUMENT)

        assert what_it_was_handed(platform, start=RAM, xlen=64) == (
            0,
            ARGUMENT,
        )


@pytest.mark.platform
class TestWhenQemusResetVectorStartsAProgramOnA32BitCpu:
    def test_the_program_finds_the_harts_number_in_a0_and_the_argument_in_a1(
        self,
    ):
        platform = a_cpu_started_by_the_reset_stub(
            xlen=32, argument=0x8220_0000
        )

        assert what_it_was_handed(platform, start=RAM, xlen=32) == (
            0,
            0x8220_0000,
        )


def a_host_whose_rom_starts(image, firmware):
    """A host that boots from its ROM, with `image` in its flash, run."""
    board = the_host.host(boot=from_rom)
    platform = board.platform
    platform.build()
    platform.load_elf(firmware(ROM_FOR_A_64_BIT_CPU), via=board.cpu.socket)
    platform.poke(
        board.syscon.component.boot_address,
        image.to_bytes(),
        via=board.cpu.socket,
    )
    ready_to_be_handed(platform, start=the_host.RAM_BASE, via=board.cpu.socket)
    platform.run(LONG_ENOUGH)
    return board


def the_program(**argument):
    """An image of the program that stores its arguments, for the host."""
    return BootImage(
        name="arguments",
        xlen=64,
        load_address=the_host.RAM_BASE,
        entry=the_host.RAM_BASE,
        payload=stores_its_arguments(xlen=64),
        **argument,
    )


def what_the_host_was_handed(board):
    """The `a0` and `a1` the program in the host's RAM found."""
    return what_it_was_handed(
        board.platform,
        start=the_host.RAM_BASE,
        xlen=64,
        via=board.cpu.socket,
    )


def a_cpu_started_by_the_reset_stub(*, xlen, argument):
    """A CPU whose ROM holds QEMU's reset vector, and the program at RAM.

    The stub starts the program with `argument`. The platform is run.
    """
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.DbtRiseCpu(xlen=xlen, reset_vector=ROM_BASE))
    bus = platform.add("bus", sp.Router())
    rom = platform.add("rom", sp.Rom(size=0x100))
    memory = platform.add("ram", sp.Memory(size=0x1000))
    platform.connect(cpu.socket, bus.target)
    bus.map(rom.socket, base=ROM_BASE)
    bus.map(memory.socket, base=RAM)
    platform.build()
    platform.poke(ROM_BASE, reset_stub(start=RAM, argument=argument, xlen=xlen))
    platform.poke(RAM, stores_its_arguments(xlen=xlen))
    ready_to_be_handed(platform, start=RAM)
    platform.run(LONG_ENOUGH)
    return platform


def ready_to_be_handed(platform, *, start, via=None):
    """Fill where `stores_its_arguments` at `start` leaves what it found.

    With ones, so that zero is what the program stored and not what was
    there before it ran.
    """
    platform.poke(start + ARGUMENTS_AT, b"\xff" * 16, via=via)


def what_it_was_handed(platform, *, start, xlen, via=None):
    """The `a0` and `a1` that `stores_its_arguments` at `start` found."""
    size = xlen // 8
    found = platform.peek(start + ARGUMENTS_AT, 2 * size, via=via)
    return (
        int.from_bytes(found[:size], "little"),
        int.from_bytes(found[size:], "little"),
    )
