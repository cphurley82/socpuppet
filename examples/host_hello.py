"""🧦 The host boots Zephyr and says hello.

The host is a 64-bit RISC-V CPU with its RAM and interrupt controller on one
die, and a UART and a timer on another (see socpuppet/boards/host.py). This
loads Zephyr's hello_world, built for the board `socpuppet_host`, runs it
and prints what the firmware printed.

Build the firmware first:      firmware/build.sh
Run it:                        python examples/host_hello.py
"""

import pathlib
import sys

import socpuppet as sp
from socpuppet.boards.host import host

IMAGE = pathlib.Path("build/firmware/hello_world_socpuppet_host.elf")

if __name__ == "__main__":
    if not IMAGE.exists():
        print(
            f"There is no {IMAGE} yet. Build the firmware with "
            "`firmware/build.sh`, which takes a few minutes the first time."
        )
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)

    board = host()
    board.platform.build()
    board.platform.load_elf(IMAGE)

    # Run until the greeting is out, or give up after 50 ms of simulated
    # time, which is far more than a boot needs.
    booted = board.platform.run_until(
        lambda: "Hello World!" in board.uart.output, timeout=sp.ms(50)
    )
    board.platform.run(sp.ms(1))  # let the line finish

    print(board.uart.output, end="")
    elapsed = board.platform.time / sp.ms(1)
    if booted:
        print(f"\n✅ Zephyr booted in {elapsed:.1f} ms of simulated time.")
    else:
        sys.exit(f"\n❌ No greeting after {elapsed:.1f} ms of simulated time.")
