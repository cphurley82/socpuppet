"""Question 2 of M14's boot spike, taken one step past building.

The spike's ROM (`spikes/boot/rom`, built by its `build.sh`) is put where
the host's CPU starts, with Zephyr's `hello_world` behind a header in a
memory that stands in for the flash, and nothing at all in the RAM.

🎭 Both the ROM and the flash are plain `sp.Memory` here. What this shows
is the firmware half: a program built with the Zephyr SDK's compiler and
no Zephyr starts a CPU, copies an image and jumps to it.

Run it:    PYTHONPATH=python uv run python spikes/boot/rom_boots.py
"""

import pathlib
import struct
import sys

import socpuppet as sp
from socpuppet.boards.host import RAM_BASE, host

ROM_BASE = 0x1000
FLASH_BASE = 0x2000_0000
MAGIC = 0x50504F53
GREETING = "Hello World! socpuppet_host"

board = host(trace=False)
platform = board.platform
# The spike reaches into the board: M14's `boot=from_rom` is the way in.
board.cpu.component.reset_vector = ROM_BASE
bus = platform.port("compute.bus.target").placed
rom = platform.add("compute.rom", sp.Memory(size=60 * 1024))
flash = platform.add("compute.flash", sp.Memory(size=4 * 1024 * 1024))
bus.map(rom.socket, base=ROM_BASE)
bus.map(flash.socket, base=FLASH_BASE)
platform.build()

platform.load_elf("build/spikes/boot/rom_rv64.elf")
image = pathlib.Path(
    "build/firmware/hello_world_socpuppet_host.bin"
).read_bytes()
platform.poke(
    FLASH_BASE,
    struct.pack("<IIII", MAGIC, RAM_BASE, RAM_BASE, len(image)) + image,
)
assert platform.peek(RAM_BASE, 16) == bytes(16), "the RAM is not empty"

platform.run_until(lambda: GREETING in board.uart.output, timeout=sp.ms(100))
print(board.uart.output, end="")
print(f"({platform.time / sp.ms(1):.2f} ms of simulated time)")
sys.exit(0 if GREETING in board.uart.output else 1)
