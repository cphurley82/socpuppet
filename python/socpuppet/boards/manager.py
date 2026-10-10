"""The IO die's manager: what brings the die-to-die link up.

    this die's end of the link ── irq ──▶ 🧠 the manager
                 ▲                              │
                 └── its registers ◀── bus ◀────┘

A chiplet's dies cannot talk until the link between them has been
trained, and something has to do the training. On the IO die that is the
manager: a small CPU whose firmware starts the link, waits for it to say
it is up, and then lets the other die out of reset.

`add_manager()` puts one on a bus, with the link's registers. It is a
32-bit CPU with the usual kit around it (`boards/cpu_kit.py`), or 🎭 a
script in the CPU's place and no kit. The IO manager board
(`boards/io_manager.py`) is built around it, and the host
(`boards/host.py`) is handed it as its `manager`.
"""

from __future__ import annotations

from typing import NamedTuple

from socpuppet.boards.cpu_kit import CpuKit, add_cpu_kit
from socpuppet.components import Script, ScriptedBusMaster
from socpuppet.io_manager import IoManager
from socpuppet.placed import Placed, PlacedRouter
from socpuppet.platform import Group, Platform

#: Where the link's registers are in the manager's map: where the SSD has
#: its frontend's, so that both boards can share the SoC `socpuppet_rv32`.
LINK_BASE = 0x1001_0000
#: Which of the interrupt controller's sources the link's line goes to.
LINK_SOURCE = 1


class Manager(NamedTuple):
    """The IO die's manager, as `add_manager` describes it."""

    #: The manager's CPU, or 🎭 the script in its place. Firmware is
    #: loaded through it: `platform.load_elf(file, via=manager.cpu.socket)`.
    cpu: Placed
    #: What a real CPU has around it. None when a script is in its place.
    cpu_kit: CpuKit | None = None


def stand_in_manager() -> IoManager:
    """🎭 The manager stand-in, told where `add_manager` puts the registers.

    Its `script` goes in the manager's CPU's place:
    `add_manager(..., script=stand_in_manager().script)`, or on the IO
    manager board `io_manager(..., manager=stand_in_manager().script)`.
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
