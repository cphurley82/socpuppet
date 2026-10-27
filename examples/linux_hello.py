"""🐧 Linux boots on the host, and Python types at its shell.

    compute die                        IO die
    🧠 host ─▶ bus ─▶ link ════ link ─▶ bus ─┬─▶ uart      (OpenSBI's console)
       │        └─▶ ram                      ├─▶ 🎭 virtio console  (Linux's)
       └─ OpenSBI, then a stock kernel       └─▶ 🎭 virtio disk     (its root)

The kernel is Linux's own `defconfig` for RISC-V, with nothing of
socpuppet's in it. Its first words go through OpenSBI to the UART, and
the rest to 🎭 the virtio console, a stand-in for a serial port that
every Linux has a driver for. Python waits for the shell's prompt, types
two commands and reads the answers, as a test would, then switches the
host off.

Build the firmware first:  uv run firmware/build.py
Run it:                    python examples/linux_hello.py
On QBox's hart:            SOCPUPPET_CPU=qbox_cpu python examples/linux_hello.py
With a debugger waiting:   python examples/linux_hello.py --gdb 1234

The prompt comes after a minute or two on the wall on the DBT-RISE CPU,
most of it the kernel's own start-up, and in seconds on QBox's. With
`--gdb`, the CPU waits for a debugger before its first instruction:
`riscv64-zephyr-elf-gdb build/firmware/linux.elf`, then `target remote
:1234`, `break start_kernel`, `continue` (docs/linux.md, "When it does
not boot").

The images are looked for in build/firmware, or in SOCPUPPET_FIRMWARE_DIR
if that is set. With an image missing the example says so and counts as
not run, unless SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where a
missing image is a failure.
"""

import argparse
import os
import pathlib
import sys
import time

import socpuppet as sp
from socpuppet import linux
from socpuppet.boards.host import switched_off

IMAGES = pathlib.Path(
    os.environ.get("SOCPUPPET_FIRMWARE_DIR", "build/firmware")
)
#: How long the kernel may take to prompt, in simulated time: it prompts
#: at about 180 s of the CPU's time on one hart and 210 s on the other.
PROMPTS_WITHIN = sp.ms(400_000)
#: How long `poweroff` may take to reach the system controller: busybox
#: stops every process and unmounts the disk first.
SWITCHES_OFF_WITHIN = sp.ms(30_000)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.partition("\n")[0])
    parser.add_argument(
        "--gdb",
        type=int,
        default=0,
        metavar="PORT",
        help="hold the CPU for a debugger on this TCP port",
    )
    options = parser.parse_args()

    try:
        board = linux.host_with_linux(IMAGES, gdb_port=options.gdb)
    except FileNotFoundError as missing:
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            sys.exit(str(missing))
        print(missing)
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)
    console = board.virtio.console
    cpu = board.cpu.component.implementation
    print(f"🧦 Booting 🐧 Linux on the host's {cpu}.", flush=True)
    if options.gdb:
        print(f"🔍 The CPU waits for a debugger on port {options.gdb}.")

    started = time.monotonic()
    prompted = board.platform.run_until(
        lambda: linux.PROMPT.search(console.output) is not None,
        timeout=PROMPTS_WITHIN,
    )
    wall = time.monotonic() - started
    simulated = board.platform.time / sp.s(1)

    print("\n📻 What the UART heard: OpenSBI, and the kernel's first words")
    print("   (earlycon=sbi), until the virtio console was up:\n")
    print(board.uart.output, end="")
    print(
        "\n🖥️  What the virtio console heard, which is the kernel's console:\n"
    )
    print(console.output, end="")
    if not prompted:
        sys.exit(
            f"\n❌ No prompt after {simulated:.0f} s of simulated time. Read "
            "both consoles from the end: docs/linux.md says where to look."
        )
    print(
        f"\n✅ The shell prompted at {simulated:.0f} s of simulated time, "
        f"{wall:.0f} s on the wall."
    )

    # 🧵 Type at the shell and read the answer, as a test does.
    for command in ("uname -a", "cat /proc/cpuinfo"):
        print(f"\n🧵 {command}")
        print(linux.ask(board, command), end="")

    console.write("poweroff\n")
    off = board.platform.run_until(
        lambda: switched_off(board), timeout=SWITCHES_OFF_WITHIN
    )
    if not off:
        sys.exit("\n❌ Linux did not switch the host off.")
    print("\n🐧 Linux switched the host off, through the system controller.")
