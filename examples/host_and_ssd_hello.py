"""🧦 Two firmwares in one simulation: the host's, and its SSD's.

 the host (64-bit, Zephyr)               the SSD (32-bit, Zephyr)
 cpu ─▶ bus ─┬─▶ ram                     endpoint ─▶ frontend ◀─▶ cpu
  ▲     ▲    ├─▶ plic ◀─ msi bridge         ▲           │          ▲
  │     │    └─▶ root complex ══════════════╝           ▼          ▼
  │     └─────── root complex ◀══ endpoint ◀──────── uplink ◀── dma, flash
  └── plic                                                          │
                                                                    ▼ nand

In host_hello.py the host booted alone, and in ssd_firmware_hello.py the
SSD's firmware answered 🎭 a script. Here both are the real thing, in one
simulation with one clock:

- the host runs Zephyr's own test of its disk interface, built for the
  board `socpuppet_host` with the shield `socpuppet_host_drive`,
- the SSD runs the Zephyr application in firmware/ssd, built for the
  board `socpuppet_ssd`.

Neither image was built for this. The host's is the one that passes
against 🎭 the stand-in drive, and the SSD's is the one that answers a
scripted host. Each CPU has a console of its own, and this prints the two
as one story, in the order things were said. 🎓 That order is good to a
quantum, the tenth of a millisecond each CPU may run ahead of the other.

Build the firmware first:      firmware/build.sh
Run it:                        python examples/host_and_ssd_hello.py

The images are looked for in build/firmware, or in SOCPUPPET_FIRMWARE_DIR
if that is set. With an image missing the example says so and counts as
not run, unless SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where a
missing image is a failure.

Each firmware sees a board of its own. To see them:

    socpuppet devicetree examples/host_and_ssd_hello.py --via compute.cpu.socket
    socpuppet devicetree examples/host_and_ssd_hello.py --via ssd.cpu.socket
    socpuppet address-map examples/host_and_ssd_hello.py
"""

import os
import pathlib
import sys

import socpuppet as sp
from socpuppet.boards.host import host
from socpuppet.boards.ssd import add_ssd

IMAGES = pathlib.Path(
    os.environ.get("SOCPUPPET_FIRMWARE_DIR", "build/firmware")
)
HOST_IMAGE = IMAGES / "disk_access_socpuppet_host.elf"
SSD_IMAGE = IMAGES / "ssd_socpuppet_ssd.elf"
#: What Zephyr's test framework ends with, when no test failed and when
#: one did.
PASSED = "PROJECT EXECUTION SUCCESSFUL"
FAILED = "PROJECT EXECUTION FAILED"

# Describe the platform: the host, with a drive of 2 MiB. `drive=add_ssd`
# is what makes it the SSD with a CPU of its own. With no `drive` the
# host gets 🎭 the stand-in drive, which the same host image passes
# against, and there is no second image to load and no second console.
board = host(drive_blocks=4096, drive=add_ssd)
#: What `socpuppet devicetree` and `socpuppet address-map` look for.
platform = board.platform


if __name__ == "__main__":
    missing = next(
        (image for image in (HOST_IMAGE, SSD_IMAGE) if not image.exists()),
        None,
    )
    if missing:
        message = (
            f"There is no {missing} yet. Build the firmware with "
            "`firmware/build.sh`, which takes a few minutes the first time."
        )
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            sys.exit(message)
        print(message)
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)

    platform.build()
    # ⚠️ There are two CPUs, so say whose firmware each image is.
    platform.load_elf(HOST_IMAGE, via=board.cpu.socket)
    platform.load_elf(SSD_IMAGE, via=board.drive.ssd.cpu.socket)

    # Who said what, and when: each whole line either console prints,
    # noted each time the run is about to move the clock on. The run is
    # the transcript's own, which listens as it goes.
    story = sp.Transcript(
        platform, {"host": board.uart, "ssd": board.drive.ssd.cpu_kit.uart}
    )

    def verdict():
        """The host's verdict, once it has printed the whole line."""
        return next(
            (
                line.text
                for line in story.lines
                if line.who == "host" and line.text in (PASSED, FAILED)
            ),
            None,
        )

    # A CPU never runs out of things to do, so the run ends at the host's
    # verdict, or after two seconds of simulated time, which is three
    # times what this takes.
    story.run_until(lambda: verdict() is not None, timeout=sp.ms(2000))

    print(
        sp.render_transcript(
            line
            for line in story.lines
            # Zephyr's test framework rules lines between its tests.
            if line.text.strip("= -")
        )
    )
    elapsed = platform.time / sp.ms(1)
    if verdict() is None:
        sys.exit(
            f"\n❌ No verdict after {elapsed:.1f} ms of simulated time. If "
            "the SSD said nothing above, look at its image first: a host "
            "waits for ever for a drive whose firmware never starts."
        )
    if verdict() == FAILED:
        sys.exit("\n❌ The host's disk test failed.")
    print(
        f"\n✅ Two firmwares, one clock: the host's disk test passed "
        f"against the SSD's firmware in {elapsed:.1f} ms of simulated time."
    )
    print(
        "💡 The lines that start `W:` are the test doing its job: it reads "
        "and writes past the end of the drive, to see that it is refused."
    )
