"""🧦 The whole cast: three firmwares boot one chiplet system.

    compute die                 IO die                       the SSD
    🧠 host ─▶ bus ─▶ link ════ link ─▶ bus ─▶ root complex ═══ endpoint
       ▲        │      end      end      └─▶ uart                  │
       │        └─▶ ram │        ▲                             frontend
       └─── reset ──────┘        └─ its registers                  ▲
                                         ▲                         │
                                    🧠 manager                   🧠 ssd

Every earlier example had a script somewhere, playing a CPU and its
firmware. This one has none. Three RISC-V CPUs each run a Zephyr image of
their own, in one simulation with one clock:

- the IO die's manager (32-bit) runs firmware/iomgr, which trains the
  die-to-die link and then lets the compute die out of reset,
- the host (64-bit) runs Zephyr's own test of its disk interface, which
  finds its drive across that link and over PCIe,
- the SSD (32-bit) runs firmware/ssd, which is the drive: it answers the
  host's NVMe commands out of its NAND. 🎭 That NAND is the one stand-in
  left, a chip that never wears and never fails.

When the power comes on only two of them can run. The link carries
nothing until it has been trained, and its end on the compute die holds
the host's CPU in reset. So the boot has an order, and this prints it:
first the link's bring-up out of the trace, packet by packet, and then
the three consoles as one story. 🎓 Within a quantum, the tenth of a
millisecond one CPU may run ahead of another, the order of two consoles'
lines is not known, and they are printed in the order manager, ssd, host.

None of the images was built for this. Each is the one that boots on its
own board: socpuppet_iomgr, socpuppet_host with its drive, socpuppet_ssd.

Build the firmware first:      firmware/build.sh
Run it:                        python examples/full_bootchain.py

The images are looked for in build/firmware, or in SOCPUPPET_FIRMWARE_DIR
if that is set. With an image missing the example says so and counts as
not run, unless SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where a
missing image is a failure.

Each firmware sees a board of its own. To see them:

    socpuppet address-map examples/full_bootchain.py
    socpuppet devicetree examples/full_bootchain.py --via io.manager.cpu.socket
    socpuppet devicetree examples/full_bootchain.py --via compute.cpu.socket
    socpuppet devicetree examples/full_bootchain.py --via ssd.cpu.socket

To debug all three at once, give each CPU a `gdb_port`
(docs/boot-your-firmware.md, "Debugging three CPUs at once").
"""

import os
import pathlib
import sys

import socpuppet as sp
from socpuppet import ucie
from socpuppet.boards.host import host
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import add_ssd

IMAGES = pathlib.Path(
    os.environ.get("SOCPUPPET_FIRMWARE_DIR", "build/firmware")
)
MANAGER_IMAGE = IMAGES / "iomgr_socpuppet_iomgr.elf"
HOST_IMAGE = IMAGES / "disk_access_socpuppet_host.elf"
SSD_IMAGE = IMAGES / "ssd_socpuppet_ssd.elf"
#: What Zephyr's test framework ends with, when no test failed and when
#: one did.
PASSED = "PROJECT EXECUTION SUCCESSFUL"
FAILED = "PROJECT EXECUTION FAILED"

# Describe the platform: the host, with a drive of 2 MiB. `manager` and
# `drive` are the two choices of fidelity. `add_manager` is the manager
# with a CPU, where a script filled in would be 🎭 the stand-in, and
# `add_ssd` is the SSD with a CPU, where leaving `drive` out would be 🎭
# the stand-in drive. `trace=True` records what crosses the link.
board = host(drive_blocks=4096, manager=add_manager, drive=add_ssd, trace=True)
#: What `socpuppet devicetree` and `socpuppet address-map` look for.
platform = board.platform


def die_of(record):
    """Which die sent what a trace record saw."""
    return "io" if record.source.startswith("io.") else "compute"


if __name__ == "__main__":
    missing = next(
        (
            image
            for image in (MANAGER_IMAGE, HOST_IMAGE, SSD_IMAGE)
            if not image.exists()
        ),
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
    # ⚠️ There are three CPUs, so say whose firmware each image is.
    platform.load_elf(MANAGER_IMAGE, via=board.manager.cpu.socket)
    platform.load_elf(HOST_IMAGE, via=board.cpu.socket)
    platform.load_elf(SSD_IMAGE, via=board.drive.ssd.cpu.socket)

    # Who said what, and when: each whole line a console prints, noted
    # each time the run is about to move the clock on.
    story = sp.Transcript(
        platform,
        {
            "manager": board.manager.cpu_kit.uart,
            "ssd": board.drive.ssd.cpu_kit.uart,
            "host": board.uart,
        },
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

    print("🧦 the power is on. The link is in reset, and the host with it.")
    # A CPU never runs out of things to do, so the run ends at the host's
    # verdict, or after two seconds of simulated time, which is three
    # times what this takes.
    story.run_until(lambda: verdict() is not None, timeout=sp.ms(2000))

    print("\n📻 what the two ends of the link said on the sideband:")
    for record, packet in ucie.sideband_packets(platform.trace):
        print(
            f"  {record.time / sp.ms(1):>8.3f} ms  {die_of(record):>7} ─▶ "
            f"{packet.description()}"
        )

    print("\n🖥️  and what the three firmwares said, as one story:")
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
            f"\n❌ No verdict after {elapsed:.1f} ms of simulated time. "
            "Read the story from the top: a host that says nothing was "
            "never let go, which is the manager's to do, and a host that "
            "waits for ever for its drive is waiting on the SSD's firmware."
        )
    if verdict() == FAILED:
        sys.exit("\n❌ The host's disk test failed.")
    print(
        f"\n✅ Three firmwares, one clock: the manager trained the link and "
        f"let the host go, and the host's disk test passed against the "
        f"SSD's firmware, in {elapsed:.1f} ms of simulated time."
    )
    print(
        "💡 The lines that start `W:` are the test doing its job: it reads "
        "and writes past the end of the drive, to see that it is refused."
    )
