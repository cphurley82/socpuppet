"""Question 3 of M14's boot spike: does a flat binary, copied in, boot?

A boot ROM copies an image's bytes to RAM and jumps. Python's loader has
only ever written an ELF's segments, each where its program header says.
This writes Zephyr's `zephyr.bin` at the start of RAM in one piece, which
is what a ROM would have copied, and runs it.

Run it:    PYTHONPATH=python uv run python spikes/boot/bin_in_ram.py
"""

import pathlib
import sys

import socpuppet as sp
from socpuppet.boards.host import RAM_BASE, host

IMAGE = pathlib.Path("build/firmware/hello_world_socpuppet_host.bin")
GREETING = "Hello World! socpuppet_host"

board = host()
board.platform.build()
board.platform.poke(RAM_BASE, IMAGE.read_bytes())
board.platform.run_until(
    lambda: GREETING in board.uart.output, timeout=sp.ms(50)
)
greeted = GREETING in board.uart.output
print("✅" if greeted else "❌", "Zephyr's hello_world from a flat copy")
sys.exit(0 if greeted else 1)
