"""Question 4 of M14's boot spike, taken one step past building.

Zephyr's shell, built by `spikes/boot/zephyr/build.sh` for a host whose
devicetree has two APLICs, is run on a host that has two: the board's
own on the IO die, and one more put on the compute die here, by hand.
Python types a command and the shell answers, as in M13's exit test, so
Zephyr's APLIC driver runs with two instances and the module's glue finds
the console's source on the right one.

Run it:    PYTHONPATH=python uv run python spikes/boot/two_aplics.py
"""

import sys

import socpuppet as sp
from socpuppet.boards.host import host

PROMPT = "uart:~$ "

board = host()
platform = board.platform
# The spike reaches into the board: M14's step 6 puts this in `host()`.
bus = platform.port("compute.bus.target").placed
aplic = platform.add("compute.aplic", sp.Aplic())
bus.map(aplic.socket, base=0x0C00_0000)
platform.connect(aplic.msi, bus.add_input())
platform.build()
platform.load_elf("build/spikes/boot/zephyr/shell_module.elf")

prompted = platform.run_until(
    lambda: PROMPT in board.uart.output, timeout=sp.ms(200)
)
board.uart.write("kernel version\n")
answered = platform.run_until(
    lambda: "Zephyr version" in board.uart.output, timeout=sp.ms(200)
)
print(board.uart.output)
print("✅" if prompted and answered else "❌", "the shell answered")
sys.exit(0 if prompted and answered else 1)
