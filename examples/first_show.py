"""🌱 Your first show: a chip that answers when you type at it.

The host boots Zephyr's shell. Python is the other end of the console's
cable: `uart.write` is the keyboard and `uart.output` is the screen. Type a
command, give the chip a moment of its own time, and read the answer.
docs/first-show.md is the page this is from, and says which line to change.

Run it:                        python examples/first_show.py

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

IMAGE = "shell_module_socpuppet_host.elf"
PROMPT = "uart:~$ "

if __name__ == "__main__":
    try:
        image = images.find(IMAGE)
    except FileNotFoundError as missing:
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            sys.exit(str(missing))
        print(missing)
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)

    board = host()  # 🧵 the chip, described in Python
    board.platform.build()  # make the simulation
    board.platform.load_elf(image)  # Zephyr's shell, built for this chip

    prompted = board.platform.run_until(  # boot, until the shell prompts
        lambda: PROMPT in board.uart.output, timeout=sp.ms(200)
    )
    if not prompted:
        sys.exit("❌ The shell never prompted.")
    board.uart.write("kernel version\n")  # 🧵 type a command. Change this line!
    board.platform.run(sp.ms(200))  # give the chip 200 ms to answer
    print(board.uart.output)

    # The shell prompts again once it has answered, whatever was typed.
    if board.uart.output.count(PROMPT) < 2:
        sys.exit("❌ The shell did not answer in 200 ms.")

    elapsed = board.platform.time / sp.ms(1)
    print(f"\n✅ The chip answered in {elapsed:.1f} ms of its own time.")
