"""🧦 The host boots Zephyr and says hello.

The host is a 64-bit RISC-V CPU with its RAM, a timer and an interrupt
controller on one die, and a UART on another (see socpuppet/boards/host.py).
This loads Zephyr's hello_world, built for the board `socpuppet_host`, runs
it and prints what the firmware printed.

Run it:                        python examples/host_hello.py

The image is found as `socpuppet.images` finds any: in SOCPUPPET_FIRMWARE_DIR,
in build/firmware in a checkout, or else fetched into your cache the first
time. With none to be had the example says so and counts as not run, unless
SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where that is a failure.
"""

import os
import sys

import socpuppet as sp
from socpuppet import images
from socpuppet.boards.host import host

IMAGE = "hello_world_socpuppet_host.elf"

if __name__ == "__main__":
    try:
        image = images.find(IMAGE)
    except FileNotFoundError as missing:
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            sys.exit(str(missing))
        print(missing)
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)

    board = host()
    board.platform.build()
    board.platform.load_elf(image)

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
