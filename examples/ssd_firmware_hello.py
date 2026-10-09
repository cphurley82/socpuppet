"""🧦 A host writes to an SSD that runs its own firmware.

 the host                          the SSD
 host ─▶ bus ─┬─▶ ram              endpoint ─▶ frontend ◀─▶ cpu (Zephyr)
  ▲      ▲    ├─▶ msi receiver        ▲           │            ▲
  │      │    └─▶ root complex ═══════╝           ▼            ▼
  │      └─────── root complex ◀══ endpoint ◀── uplink ◀── dma, flash ─▶ nand
  └── msi receiver

In ssd_hello.py a Python script played the SSD's firmware. Here the SSD
has its CPU, a 32-bit RISC-V core, and on it the real thing: the Zephyr
application in firmware/ssd, built for the board `socpuppet_ssd`.

🎭 The host is still a script, and it is ssd_hello.py's, unchanged. It
cannot tell which firmware it got.

Build the firmware first:      firmware/build.sh
Run it:                        python examples/ssd_firmware_hello.py

The image is looked for in build/firmware, or in SOCPUPPET_FIRMWARE_DIR if
that is set. With no image there the example says so and counts as not
run, unless SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where a
missing image is a failure.
"""

import os
import pathlib
import sys

import socpuppet as sp
from socpuppet.boards.scripted_host import bring_up_the_drive
from socpuppet.boards.ssd import ssd

IMAGE = (
    pathlib.Path(os.environ.get("SOCPUPPET_FIRMWARE_DIR", "build/firmware"))
    / "ssd_socpuppet_ssd.elf"
)
MESSAGE = b"Hello from the host, by way of PCIe, Zephyr and a page of NAND."

# What the host's script learns along the way, for printing at the end.
found = {}


def host():
    """What the host does. Each step hands over with `yield from`."""
    # 1. Find the drive on the PCIe bus, place it, and enable it. The
    #    host waits here while the SSD's firmware boots, until it says
    #    it is ready.
    nvme = yield from bring_up_the_drive()
    found["up at"] = board.platform.time
    found["namespace"] = yield from nvme.identify_namespace()

    # 2. Write a block near the end of the drive, then one at the start,
    #    and read the first back.
    block = MESSAGE.ljust(found["namespace"].block_size, b"\0")
    last = found["namespace"].blocks - 1
    yield from nvme.write_blocks(first=last, data=block)
    yield from nvme.write_blocks(first=0, data=block[::-1])
    found["read back"] = yield from nvme.read_blocks(first=last, count=1)


# Describe the platform: the SSD, with a scripted host on its PCIe link.
# With no script for its firmware, the SSD gets a CPU.
board = ssd(host=host, blocks=4096)

if __name__ == "__main__":
    if not IMAGE.exists():
        missing = (
            f"There is no {IMAGE} yet. Build the firmware with "
            "`firmware/build.sh`, which takes a few minutes the first time."
        )
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            sys.exit(missing)
        print(missing)
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)

    board.platform.build()
    # ⚠️ There are two CPUs' worth of bus here, so say whose firmware it is.
    board.platform.load_elf(IMAGE, via=board.ssd.cpu.socket)

    # A CPU never runs out of things to do, so the run ends when the host
    # has its block back, or after a second of simulated time, which is
    # far more than this takes.
    done = board.platform.run_until(
        lambda: "read back" in found, timeout=sp.ms(1000)
    )

    print("The SSD's console:")
    for line in board.ssd.cpu_kit.uart.output.splitlines():
        print(f"    {line}")
    elapsed = board.platform.time / sp.ms(1)
    if not done:
        sys.exit(
            f"\n❌ No block back after {elapsed:.1f} ms of simulated time."
        )

    namespace = found["namespace"]
    megabytes = namespace.blocks * namespace.block_size / 1e6
    print(
        f"The host found a drive of {namespace.blocks} blocks of "
        f"{namespace.block_size} bytes: {megabytes:.1f} MB."
    )
    # A script took no simulated time to play the firmware. A CPU does:
    # Zephyr has to boot before the drive says it is ready, and after
    # that every command is instructions to run.
    up = found["up at"] / sp.ms(1)
    print(
        f"The host had the drive up {up:.1f} ms after power-on, and its "
        f"four commands took {elapsed - up:.1f} ms more."
    )
    text = found["read back"].rstrip(b"\0").decode()
    print(f'\n✅ Wrote two blocks and read the first back: "{text}"')
