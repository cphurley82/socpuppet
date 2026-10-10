"""🧦 The IO-die manager: the die that brings the die-to-die link up.

    compute die (🎭 a stand-in)                 IO die
    🎭 master ─▶ bus ─┬─▶ d2d.a ════ d2d.b ─▶ bus ─┬─▶ scratch
                      └─▶ ram          │           └─▶ the link's registers
               reset ◀─────────────────┤                     ▲
                                  irq ─┴─▶ 🎭 the manager ───┘

This is the platform behind the Zephyr board `socpuppet_iomgr`. With 🎭 a
script in the manager's place (`stand_in_manager()`) there is no CPU on
the IO die at all; with none, there is a 32-bit RISC-V core with the
usual kit around it (`boards/cpu_kit.py`), and the firmware is loaded
into it.

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

from socpuppet.boards.cpu_kit import CpuKit, add_cpu_kit
from socpuppet.components import (
    D2dLink,
    Memory,
    Router,
    Script,
    ScriptedBusMaster,
)
from socpuppet.io_manager import IoManager
from socpuppet.ops import Steps, expect32, write32
from socpuppet.placed import Placed, PlacedRouter
from socpuppet.platform import Group, Link, Platform
from socpuppet.time import ms

#: Where things are on the IO die, at the addresses the SSD board uses for
#: the same kinds of thing: the link's registers where the SSD has its
#: frontend's, so that both boards can share the SoC `socpuppet_rv32`.
LINK_BASE = 0x1001_0000
#: ⚠️ The scratch has to stay above the manager's SRAM (0x2000_0000): a
#: devicetree names the lower of two memories as the firmware's own.
SCRATCH_BASE = 0x3000_0000
SCRATCH_SIZE = 0x1000
#: Which of the interrupt controller's sources the link's line goes to.
LINK_SOURCE = 1
#: The compute die's own memory, and so the top of its window onto the IO
#: die: everything below this address is the other die's.
RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
#: What 🎭 the compute die's round trip writes across the link.
HELLO = 0xC0FFEE


class IoManagerBoard(NamedTuple):
    """The board, and the parts of it a test or a script wants."""

    platform: Platform
    #: The IO die's CPU, or 🎭 the script in its place. Firmware is loaded
    #: through it: `platform.load_elf(file, via=board.manager.socket)`.
    manager: Placed
    #: 🎭 The compute die's stand-in, held in reset until the link is up.
    compute: Placed
    #: The link: `link.a` is the compute die's end, `link.b` the IO die's.
    link: Link
    #: The IO die's bus, which the manager reaches everything through and
    #: the compute die reaches across the link.
    bus: PlacedRouter
    #: What a real CPU has around it. None when a script is in its place.
    cpu_kit: CpuKit | None = None


class Manager(NamedTuple):
    """The IO die's manager, as `add_manager` describes it."""

    #: The manager's CPU, or 🎭 the script in its place. Firmware is
    #: loaded through it: `platform.load_elf(file, via=manager.cpu.socket)`.
    cpu: Placed
    #: What a real CPU has around it. None when a script is in its place.
    cpu_kit: CpuKit | None = None


def stand_in_manager() -> IoManager:
    """🎭 The manager stand-in, told where this board's link registers are.

    Its `script` goes in the IO die's CPU slot:
    `io_manager(..., manager=stand_in_manager().script)`.
    """
    return IoManager(link=LINK_BASE)


def add_manager(
    platform: Platform,
    place: Platform | Group,
    bus: PlacedRouter,
    *,
    link_end: Placed,
    script: Script | None = None,
    gdb_port: int = 0,
) -> Manager:
    """Put the IO die's manager on `bus`, with the link's registers.

    `link_end` is this die's end of the die-to-die link the manager
    brings up. Its registers go on `bus` at `LINK_BASE`, and its interrupt
    line goes to the manager.

    With no `script` the manager is a 32-bit CPU with the usual kit around
    it, and the firmware is loaded into it. `gdb_port` is where a debugger
    can attach to it. 🎭 With a `script`, that is in the CPU's place and
    there is no kit: `add_manager(..., script=stand_in_manager().script)`.
    """
    if script is not None and gdb_port:
        raise ValueError(
            f"gdb_port={gdb_port} was asked for, and a debugger attaches to "
            "a CPU. With a script standing in for it the manager has none. "
            "Leave out the script for a manager with a CPU, or leave out "
            "`gdb_port`."
        )
    bus.map(link_end.sideband, base=LINK_BASE)
    cpu_kit = None
    if script is None:
        cpu, cpu_kit = add_cpu_kit(
            platform,
            place,
            bus,
            sources={LINK_SOURCE: link_end.irq},
            gdb_port=gdb_port,
        )
    else:
        # 🎭 A script has one interrupt input, and the link is the only
        # thing a manager has a line from, so it goes straight to it.
        cpu = place.add("cpu", ScriptedBusMaster(script=script))
        platform.connect(link_end.irq, cpu.irq)
    platform.connect(cpu.socket, bus.target)
    return Manager(cpu, cpu_kit)


def io_manager(
    *,
    compute: Script,
    manager: Script | None = None,
    gdb_port: int = 0,
    trace: bool = False,
) -> IoManagerBoard:
    """Describe the board. Nothing is simulated until `platform.build()`.

    `compute` is 🎭 the script in the compute die's place, which runs once
    the manager has let that die out of reset. `manager` is 🎭 a script in
    the IO die's CPU slot; with none, the IO die has a real CPU and the
    firmware is loaded into it, and `gdb_port` is where a debugger can
    attach to it. With `trace=True`, everything that crosses the link is
    recorded, the sideband apart from the mainband (`socpuppet.ucie` reads
    the packets back).
    """
    platform = Platform()
    compute_die = platform.group("compute")
    io = platform.group("io")

    # The link's times are the model's own defaults, which come to 5 ms
    # from power-on to a link that carries anything: 4 ms of UCIe's reset
    # hold, and a millisecond of training (models/d2d-link.md).
    link = platform.link("d2d", D2dLink(), compute_die, io, trace=trace)

    # The IO die: its bus, the manager with the link's registers, and the
    # scratch the compute die reaches across the link.
    bus = io.add("bus", Router())
    placed_manager = add_manager(
        platform, io, bus, link_end=link.b, script=manager, gdb_port=gdb_port
    )
    scratch = io.add("scratch", Memory(size=SCRATCH_SIZE))
    bus.map(scratch.socket, base=SCRATCH_BASE)
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
        platform=platform,
        manager=placed_manager.cpu,
        compute=compute_cpu,
        link=link,
        bus=bus,
        cpu_kit=placed_manager.cpu_kit,
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


#: What `socpuppet devicetree` looks for in a description file.
platform = io_manager(compute=one_round_trip).platform

if __name__ == "__main__":
    board = io_manager(
        compute=one_round_trip, manager=stand_in_manager().script
    )
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
