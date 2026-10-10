"""🧦 A chiplet host starts up: the link is trained, then Zephyr boots.

    compute die                         IO die
    🧠 cpu ─▶ bus ─▶ link end ═════ link end ─▶ bus ─▶ uart
       ▲                │             ▲  │
       └──── reset ─────┘             │  └─ irq ─────────▶ 🎭 the manager
                                      └─ its registers ◀─ bus ◀──┘

The host is a 64-bit RISC-V CPU on one die with its console on another
(see socpuppet/boards/host.py). In `host_hello.py` the link between the
dies is 🎭 a stand-in that passes everything straight through. Here it is
the real one, `sp.D2dLink`, in the style of UCIe: when the power comes on
it carries nothing, and its end on the compute die holds the host's CPU
in reset.

So the show has two acts. First the IO die's manager trains the link and
lets the host go, which is printed out of the trace, packet by packet.
🎭 The manager is a script here (`sp.IoManager`). Then Zephyr boots, and
every character of its greeting crosses the link to reach the UART.

The firmware is `host_hello.py`'s, the same image. It cannot tell which
link it has.

Build the firmware first:      firmware/build.sh
Run it:                        python examples/chiplet_host_hello.py

The image is looked for in build/firmware, or in SOCPUPPET_FIRMWARE_DIR if
that is set. With no image there the example says so and counts as not
run, unless SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where a
missing image is a failure.

The host's CPU and the manager each see a map of their own. To see them:

    socpuppet address-map examples/chiplet_host_hello.py
    socpuppet devicetree examples/chiplet_host_hello.py --via compute.cpu.socket
"""

import functools
import os
import pathlib
import sys

import socpuppet as sp
from socpuppet import ucie
from socpuppet.boards.host import host
from socpuppet.boards.manager import add_manager, stand_in_manager

IMAGE = (
    pathlib.Path(os.environ.get("SOCPUPPET_FIRMWARE_DIR", "build/firmware"))
    / "hello_world_socpuppet_host.elf"
)

# Describe the platform: the host, with a manager on its IO die, which is
# what makes the link between the dies the real one. `add_manager` alone
# is a manager with a CPU of its own, and with a script filled in it is
# 🎭 the stand-in. `trace=True` records everything that crosses the link.
board = host(
    manager=functools.partial(add_manager, script=stand_in_manager().script),
    trace=True,
)
#: What `socpuppet devicetree` and `socpuppet address-map` look for.
platform = board.platform


def microseconds(picoseconds):
    """A time of the simulation's, as a trace line shows it."""
    return f"{picoseconds / sp.us(1):.3f} us"


def die_of(record):
    """Which die sent what a trace record saw."""
    return "io" if record.source.startswith("io.") else "compute"


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

    platform.build()
    # With two bus masters, the platform has to be told whose firmware an
    # image is.
    platform.load_elf(IMAGE, via=board.cpu.socket)

    print("🧦 the power is on. The link is in reset, and the host with it.")
    # Run until the greeting is out, or give up after 50 ms of simulated
    # time: the link takes 5 ms to come up, and a boot about one more.
    booted = platform.run_until(
        lambda: "Hello World!" in board.uart.output, timeout=sp.ms(50)
    )
    platform.run(sp.ms(1))  # let the line finish

    print("\n📻 what the two ends said to each other on the sideband:")
    for record, packet in ucie.sideband_packets(platform.trace):
        print(
            f"  {microseconds(record.time):>12}  {die_of(record):>7} ─▶ "
            f"{packet.description()}"
        )

    crossings = [
        record
        for record in platform.trace
        if record.source
        in (board.link.a.peer_initiator.path, board.link.b.peer_initiator.path)
    ]
    print("\n🖥️  and then what the host printed, across the link:")
    print(board.uart.output, end="")

    elapsed = platform.time / sp.ms(1)
    if not booted:
        sys.exit(f"\n❌ No greeting after {elapsed:.1f} ms of simulated time.")
    print(
        f"\n✅ Zephyr booted across the link in {elapsed:.1f} ms of "
        f"simulated time. {len(crossings)} accesses crossed it, the first "
        f"{microseconds(crossings[0].time)} after power-on. 💡 The "
        "first 4 ms is UCIe's reset hold and the next is this link's "
        "training time: the host's CPU does not run an instruction before "
        "the manager's write to its reset register."
    )
