"""🐧 Linux on the whole cast, its root on the SSD, 🎭 stand-ins to choose.

    compute die                 IO die                       the SSD
    🧠 host ─▶ bus ─▶ link ════ link ─▶ bus ─▶ root complex ═══ endpoint
       ▲        │      end      end      └─▶ 🎭 virtio console     │
       │        └─▶ ram │        ▲                             frontend
       └─── reset ──────┘        └─ its registers                  ▲
                                         ▲                         │
                                    🧠 manager                   🧠 ssd

Three CPUs, as in `full_bootchain.py`, and this time the host runs
OpenSBI and a stock Linux kernel, whose root filesystem is on the SSD:
Linux's own NVMe driver finds the drive across the die-to-die link and
over PCIe, and mounts its first partition. The IO die's manager trains
the link and lets the host go; the SSD's firmware is the drive.

🎭 Two of the three CPUs can be swapped for a stand-in, a Python script in
the CPU's place that does the same job with no CPU, no firmware image and
no console, and the host cannot tell:

    --manager script     scripted_manager(), an sp.IoManager, for the CPU
                         running firmware/iomgr
    --ssd script         scripted_firmware(), an sp.SsdFirmware, for the
                         CPU running firmware/ssd

What changes is what you can see: a stand-in has no console, so its lines
leave the story, and it takes no time of its own, so the host is let go a
little sooner. Linux boots the same either way, which is the point of a
stand-in. The link is traced, so what crossed it is counted at the end,
and the link's own bring-up is printed first, packet by packet.

Build the firmware first:   uv run firmware/build.py
Run it:                     python examples/linux_on_the_drive.py
With stand-ins:             add --manager script --ssd script

The prompt comes after a minute or two on the wall on the DBT-RISE CPU
and in seconds on QBox's (SOCPUPPET_CPU=qbox_cpu). The images are looked
for in build/firmware, or in SOCPUPPET_FIRMWARE_DIR if that is set. With
an image missing the example says so and counts as not run, unless
SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where a missing image
is a failure.
"""

import argparse
import functools
import os
import pathlib
import sys
import time

import socpuppet as sp
from socpuppet import linux
from socpuppet.boards.host import switched_off
from socpuppet.boards.manager import add_manager, scripted_manager
from socpuppet.boards.ssd import add_ssd, scripted_firmware

IMAGES = pathlib.Path(
    os.environ.get("SOCPUPPET_FIRMWARE_DIR", "build/firmware")
)
#: How long the kernel may take to prompt, in simulated time.
PROMPTS_WITHIN = sp.ms(400_000)
#: How long `poweroff` may take to reach the system controller.
SWITCHES_OFF_WITHIN = sp.ms(30_000)
#: Who plays each part: the CPU running its Zephyr image, or 🎭 the script.
MANAGERS = {
    "zephyr": add_manager,
    "script": functools.partial(add_manager, script=scripted_manager().script),
}
SSDS = {
    "zephyr": add_ssd,
    "script": functools.partial(add_ssd, firmware=scripted_firmware().script),
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.partition("\n")[0])
    parser.add_argument(
        "--manager",
        choices=MANAGERS,
        default="zephyr",
        help="the IO die's manager: a CPU running firmware/iomgr, or 🎭 a "
        "script in its place (the default is %(default)s)",
    )
    parser.add_argument(
        "--ssd",
        choices=SSDS,
        default="zephyr",
        help="the SSD's firmware: a CPU running firmware/ssd, or 🎭 a "
        "script in its place (the default is %(default)s)",
    )
    options = parser.parse_args()

    # 🎭 Each stand-in is the same function as the real thing, with the
    # script filled in. `host_with_linux` loads an image only into a CPU.
    try:
        board = linux.host_with_linux(
            IMAGES,
            root="drive",
            drive=SSDS[options.ssd],
            manager=MANAGERS[options.manager],
            trace=True,
        )
    except FileNotFoundError as missing:
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            sys.exit(str(missing))
        print(missing)
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)
    platform = board.platform
    console = board.virtio.console
    cpu = board.cpu.component.implementation
    print(
        f"🧦 Booting 🐧 Linux on the host's {cpu}, with {options.manager} for "
        f"the manager and {options.ssd} for the SSD. The power is on; the "
        "link is in reset, and the host with it.",
        flush=True,
    )

    # Who said what, and when: a stand-in has no console, so it is not here.
    # The host has two: OpenSBI and the kernel's first words go to the UART,
    # and the rest to the virtio console once its driver is up.
    consoles = {}
    if board.manager.cpu_kit is not None:
        consoles["manager"] = board.manager.cpu_kit.uart
    if board.drive.ssd.cpu_kit is not None:
        consoles["ssd"] = board.drive.ssd.cpu_kit.uart
    consoles["host uart"] = board.uart
    consoles["host"] = console
    story = sp.Transcript(platform, consoles)

    started = time.monotonic()
    prompted = story.run_until(
        lambda: linux.PROMPT.search(console.output) is not None,
        timeout=PROMPTS_WITHIN,
    )
    wall = time.monotonic() - started
    simulated = platform.time / sp.s(1)

    print("\n📻 What the two ends of the link said on the sideband:")
    print(sp.render_sideband(platform.trace))

    print("\n🖥️  What the consoles said, as one story:")
    print(sp.render_transcript(story.lines))

    if not prompted:
        sys.exit(
            f"\n❌ No prompt after {simulated:.0f} s of simulated time. A host "
            "that says nothing was never let go, which is the manager's to "
            "do; a kernel that stops at the drive is waiting on the SSD."
        )
    print(
        f"\n✅ The shell prompted at {simulated:.0f} s of simulated time, "
        f"{wall:.0f} s on the wall."
    )

    for command in ("cat /proc/partitions", "dmesg | grep -i nvme"):
        print(f"\n🧵 {command}")
        print(linux.ask(board, command), end="")

    console.write("poweroff\n")
    if not platform.run_until(
        lambda: switched_off(board), timeout=SWITCHES_OFF_WITHIN
    ):
        sys.exit("\n❌ Linux did not switch the host off.")

    # What crossed the link's mainband, each way. ⚠️ Every record is kept,
    # so a traced boot costs memory; this is why `trace` is off by default.
    to_io = sum(
        1
        for each in platform.trace
        if each.source == board.link.a.peer_initiator.path
    )
    to_compute = sum(
        1
        for each in platform.trace
        if each.source == board.link.b.peer_initiator.path
    )
    print(
        f"\n🐧 Linux switched the host off. The host sent {to_io} accesses "
        f"across the link to the IO die, and {to_compute} came back: the "
        "drive's DMA into the host's RAM, and its interrupts as messages."
    )
