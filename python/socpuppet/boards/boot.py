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


def from_rom(place: Platform | Group, bus: PlacedRouter) -> Placed:
    """Put a boot ROM on a CPU's bus, for the CPU to start in."""
    rom = place.add("rom", Rom(size=ROM_SIZE))
    bus.map(rom.socket, base=ROM_BASE)
    return rom
