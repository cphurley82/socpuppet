"""🧦 The IO-die manager: the die that brings the die-to-die link up.

    compute die (🎭 a stand-in)                 IO die
    🎭 master ─▶ bus ─┬─▶ d2d.a ════ d2d.b ─▶ bus ─┬─▶ scratch
                      └─▶ ram          │           └─▶ the link's registers
               reset ◀─────────────────┤                     ▲
                                  irq ─┴─▶ 🎭 the manager ───┘

🚧 M5b makes this the platform behind the Zephyr board `socpuppet_iomgr`,
and gives it the `platform` that `socpuppet devicetree` looks for; today
the manager is 🎭 a script, so there is no firmware to write a devicetree
for.

The IO die is the one with the management CPU on it: it trains the link
and then lets the compute die out of reset, which is how a chiplet host
starts. 🎭 The compute die is a stand-in here, a script with a RAM,
standing in for the whole of what M7 will put there.

The compute die's window onto the IO die is an **identity map**: an
address below the compute die's own RAM is the same address on the IO
die, which is the address the manager's firmware uses for it too. 💡 A
router hands its target the offset from the window's base, so a window
that started anywhere else would reach the IO die's bus at the wrong
addresses.

Run it:                 python -m socpuppet.boards.io_manager
"""

from __future__ import annotations

import sys
from typing import NamedTuple

from socpuppet.components import (
    D2dLink,
    Memory,
    Router,
    Script,
    ScriptedBusMaster,
)
from socpuppet.io_manager import IoManager
from socpuppet.ops import Steps, expect32, write32
from socpuppet.placed import Placed
from socpuppet.platform import Link, Platform
from socpuppet.time import ms

#: Where things are on the IO die. The link's registers sit beside where
#: the SSD board has its UART, and the scratch above them.
LINK_BASE = 0x1001_0000
SCRATCH_BASE = 0x3000_0000
SCRATCH_SIZE = 0x1000
#: The compute die's own memory, and so the top of its window onto the IO
#: die: everything below this address is the other die's.
RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
#: What 🎭 the compute die's round trip writes across the link.
HELLO = 0xC0FFEE


class IoManagerBoard(NamedTuple):
    """The board, and the parts of it a test or a script wants."""

    platform: Platform
    #: The IO die's CPU slot: 🎭 the manager script, for now.
    manager: Placed
    #: 🎭 The compute die's stand-in, held in reset until the link is up.
    compute: Placed
    #: The link: `link.a` is the compute die's end, `link.b` the IO die's.
    link: Link


def io_manager(*, compute: Script, trace: bool = False) -> IoManagerBoard:
    """Describe the board. Nothing is simulated until `platform.build()`.

    `compute` is 🎭 the script in the compute die's place, which runs once
    the manager has let that die out of reset. With `trace=True`,
    everything that crosses the link is recorded, the sideband apart from
    the mainband (`socpuppet.ucie` reads the packets back).
    """
    platform = Platform()
    compute_die = platform.group("compute")
    io = platform.group("io")

    # The link's times are the model's own defaults, which come to 5 ms
    # from power-on to a link that carries anything: 4 ms of UCIe's reset
    # hold, and a millisecond of training (models/d2d-link.md).
    link = platform.link("d2d", D2dLink(), compute_die, io, trace=trace)

    # The IO die: the manager, its bus, the link's registers and the
    # scratch the compute die reaches across the link.
    manager = io.add(
        "cpu", ScriptedBusMaster(script=IoManager(link=LINK_BASE).script)
    )
    bus = io.add("bus", Router())
    scratch = io.add("scratch", Memory(size=SCRATCH_SIZE))
    platform.connect(manager.socket, bus.target)
    bus.map(link.b.sideband, base=LINK_BASE)
    bus.map(scratch.socket, base=SCRATCH_BASE)
    platform.connect(link.b.irq, manager.irq)
    platform.connect(link.b.initiator, bus.add_input())

    # 🎭 The compute die: a script with a memory of its own, held in reset
    # by its end of the link until the IO die lets it go.
    compute_cpu = compute_die.add("cpu", ScriptedBusMaster(script=compute))
    compute_bus = compute_die.add("bus", Router())
    ram = compute_die.add("ram", Memory(size=RAM_SIZE))
    platform.connect(compute_cpu.socket, compute_bus.target)
    compute_bus.map(link.a.target, base=0, size=RAM_BASE)
    compute_bus.map(ram.socket, base=RAM_BASE)
    platform.connect(link.a.reset, compute_cpu.reset)

    return IoManagerBoard(
        platform=platform, manager=manager, compute=compute_cpu, link=link
    )


def one_round_trip() -> Steps[None]:
    """🎭 What the compute die does once it is let go: one round trip.

    It writes a word into the IO die's scratch memory across the link and
    reads it back, which is the whole of what M5's compute die is for. The
    read is an expectation, so a word that does not come back whole stops
    the run and says so.
    """
    yield write32(SCRATCH_BASE, HELLO)
    yield expect32(SCRATCH_BASE, HELLO)


if __name__ == "__main__":
    board = io_manager(compute=one_round_trip)
    board.platform.build()
    reached = board.platform.run_until(
        lambda: (
            board.platform.peek32(SCRATCH_BASE, via=board.manager.socket)
            == HELLO
        ),
        timeout=ms(20),
    )
    if not reached:
        sys.exit("🧦 ❌ the compute die never reached the IO die")
    print("🧦 ✅ the compute die reached the IO die across the link")
