"""Programs in RISC-V machine code, so that a test needs no toolchain.

Just enough of an assembler for a program that speaks and then sleeps.
Every instruction here is in the base integer set and is encoded the same
for a 32-bit CPU and a 64-bit one.
"""

from elf_files import elf_file
from socpuppet.boards import cpu_kit

# Registers, by their number.
ZERO = 0
T0 = 5
T1 = 6
#: The first two arguments of a call, which is how one stage of a boot
#: hands the next its hart's number and its devicetree.
A0 = 10
A1 = 11

#: Sleep until an interrupt.
WFI = 0x10500073
#: Jump back to the instruction before this one.
BACK_ONE = 0xFFDFF06F
#: Jump to this same instruction, for ever.
SPIN = 0x0000006F


def sleeps():
    """A program that sleeps for good, waking only to sleep again."""
    return b"".join(word.to_bytes(4, "little") for word in (WFI, BACK_ONE))


def lui(rd, upper20):
    """rd = upper20 << 12."""
    return (upper20 << 12) | (rd << 7) | 0x37


def li(rd, value):
    """rd = value, which is 0 to 2047."""
    return (value << 20) | (ZERO << 15) | (rd << 7) | 0x13


def sb(rs2, rs1):
    """Store the low byte of rs2 at the address in rs1."""
    return (rs2 << 20) | (rs1 << 15) | 0x23


def auipc(rd):
    """rd = the address of this instruction."""
    return (rd << 7) | 0x17


def store(rs2, rs1, offset, *, xlen):
    """Store rs2, all `xlen` bits of it, at `offset` (below 2048) past rs1."""
    width = {32: 2, 64: 3}[xlen]
    return (
        ((offset >> 5) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (width << 12)
        | ((offset & 0x1F) << 7)
        | 0x23
    )


#: How far past its own first instruction `stores_its_arguments` leaves
#: what it found.
ARGUMENTS_AT = 0x100


def stores_its_arguments(*, xlen):
    """A program that stores `a0` and then `a1`, and sleeps for good.

    They go one after the other, a register's width each, `ARGUMENTS_AT`
    bytes past the program's first instruction, wherever it runs.
    """
    size = xlen // 8
    program = [
        auipc(T0),
        store(A0, T0, ARGUMENTS_AT, xlen=xlen),
        store(A1, T0, ARGUMENTS_AT + size, xlen=xlen),
        WFI,
        BACK_ONE,
    ]
    return b"".join(word.to_bytes(4, "little") for word in program)


def says(text, *, uart, then=WFI):
    """A program that prints `text` and then sleeps for good.

    Or does what the instruction `then` does, for good: `SPIN` keeps the
    CPU at work.

    `uart` is where the program finds a 16550, whose first register is the
    one a byte to send is written to. It must be a whole number of 4 KiB
    pages, which is what one instruction can load. The text is ASCII.
    """
    assert uart % 0x1000 == 0
    program = [lui(T0, uart >> 12)]
    for byte in text.encode("ascii"):
        program += [li(T1, byte), sb(T1, T0)]
    program += [then, BACK_ONE]
    return b"".join(word.to_bytes(4, "little") for word in program)


def a_program_that_says(text, directory, *, then=WFI):
    """An ELF file for the board `socpuppet_ssd`: say `text`, then sleep.

    Or `then` do something else, for good.
    """
    program = says(text, uart=cpu_kit.UART_BASE, then=then)
    return elf_file(
        directory,
        xlen=32,
        entry=cpu_kit.SRAM_BASE,
        segments=[(cpu_kit.SRAM_BASE, program)],
    )
