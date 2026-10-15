"""How a board's CPU gets its firmware: two ways, and a board has either.

🎭 The quick way is the default. Python is the stand-in for a boot ROM:
`platform.load_elf` writes the image into RAM before anything runs, and
the CPU starts in it. It is what to use to try an image.

The other way is the one silicon has, and it is one more thing a board
can be described with:

    board = host(boot=from_rom)

The CPU's reset vector is then in a ROM, at `ROM_BASE`, and nothing is
loaded into RAM. The ROM's program asks the CPU's system controller where
its image is, finds it in the board's flash, checks it, copies it to RAM
and jumps to it. So there are two things to load, neither of them into
RAM: the ROM's own program, and an image for the flash.

    platform.load_elf("rom_rv64.elf", via=board.cpu.socket)
    platform.poke(BOOT_FLASH_BASE, boot_image.wrap("zephyr.elf"),
                  via=board.cpu.socket)

`firmware/rom` is the ROM, built for each kind of CPU by
`firmware/build.sh`.

A stage that wants two registers set as it starts, as OpenSBI does, is
started the quick way from a ROM too, which holds `reset_stub`: 🎭 QEMU's
few instructions that set them and jump to what Python put in RAM.
"""

from __future__ import annotations

from typing import Protocol

from socpuppet.components import Rom
from socpuppet.placed import Placed, PlacedRouter
from socpuppet.platform import Group, Platform

#: Where a boot ROM is, and so where a CPU that has one starts. QEMU's
#: `virt` machine has its own at the same address.
ROM_BASE = 0x1000
#: 60 KiB, which ends the ROM at 64 KiB. The ROM's program is under one.
ROM_SIZE = 60 * 1024


class Boot(Protocol):
    """A function that describes the boot ROM a CPU starts in.

    `from_rom` is the one there is. A board that is given none starts its
    CPU in RAM, where Python has put the image.
    """

    def __call__(self, place: Platform | Group, bus: PlacedRouter) -> Placed:
        """Describe the ROM on `bus`, at `ROM_BASE`, and return it."""


#: Where `reset_stub` keeps its two words, after its six instructions of
#: four bytes each: where to start, and then the argument.
_START = 24
_ARGUMENT = 32


def reset_stub(*, start: int, argument: int, xlen: int) -> bytes:
    """A program for a ROM that starts `start` as the stage before OpenSBI.

    🎭 It is QEMU's reset vector (`reset_vec` in QEMU's `hw/riscv/boot.c`),
    which QEMU's `virt` machine has in its ROM at 0x1000 for the same
    reason: the next stage wants the hart's number in `a0` and `argument`,
    a devicetree's address, in `a1`, and nothing outside a CPU can set its
    registers. So the ROM reads `mhartid`, loads the two words after its
    code and jumps. QEMU's also points `a2` at a table for OpenSBI's
    `fw_dynamic`, which `fw_jump` does not read, and this one does not. It
    stands in for the boot ROM's program, which does the same from an
    image in the flash, and it is the quick way: what it starts is already
    in RAM.

        platform.poke(ROM_BASE, reset_stub(start=RAM_BASE, argument=dtb,
                                           xlen=64))

    `xlen` is the CPU's, 32 or 64: a 32-bit CPU loads the low half of each
    word.
    """
    code = (
        0x0000_0297,  # auipc t0, 0: t0 is where the ROM starts
        0xF140_2573,  # csrr a0, mhartid
        _load(11, _ARGUMENT, xlen=xlen),  # a1 = the argument
        _load(5, _START, xlen=xlen),  # t0 = where to start
        0x0002_8067,  # jr t0
        0x0000_0013,  # nop: never run, it puts the words on 8 bytes
    )
    return b"".join(
        (
            *(each.to_bytes(4, "little") for each in code),
            start.to_bytes(8, "little"),
            argument.to_bytes(8, "little"),
        )
    )


def _load(rd: int, offset: int, *, xlen: int) -> int:
    """Load `xlen` bits from `offset` past t0 into rd: `lw` or `ld`."""
    width = {32: 2, 64: 3}[xlen]
    return (offset << 20) | (5 << 15) | (width << 12) | (rd << 7) | 0x03


def from_rom(place: Platform | Group, bus: PlacedRouter) -> Placed:
    """Put a boot ROM on a CPU's bus, for the CPU to start in."""
    rom = place.add("rom", Rom(size=ROM_SIZE))
    bus.map(rom.socket, base=ROM_BASE)
    return rom
