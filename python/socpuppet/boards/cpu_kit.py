"""What a RISC-V CPU has around it on a socpuppet board.

A CPU on its own can do nothing: it needs a memory to run from, somewhere
to print, a timer to count time with and an interrupt controller for its
devices' lines. Every board that has a CPU of its own wants the same four,
at the same addresses, which is what lets them share one SoC in Zephyr
(`socpuppet_rv32`) and what makes a devicetree for one board read like a
devicetree for another.

    🧠 cpu ─▶ bus ─┬─▶ sram   the firmware, loaded and run from here
       ▲  ▲        ├─▶ uart   its console
       │  │        ├─▶ timer ─┐
       │  └────────────────── ┘
       └── plic ◀── the devices' interrupt lines
         ◀─┘

`add_cpu_kit()` puts the five on a board's bus and wires them up. The board
says which of its devices' lines go on which of the interrupt
controller's sources; everything else is the same every time.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

from socpuppet.components import (
    DbtRiseCpu,
    MachineTimer,
    Memory,
    Ns16550,
    Plic,
)
from socpuppet.placed import Placed, PlacedRouter, PlacedUart, Port
from socpuppet.platform import Group, Platform

#: The machine timer, and how many times a second it counts. The firmware
#: has to be told the same number: CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC in
#: Zephyr.
TIMER_BASE = 0x0200_0000
TIMER_HZ = 10_000_000
#: The interrupt controller.
PLIC_BASE = 0x0C00_0000
#: The UART, which is the firmware's console.
UART_BASE = 0x1000_0000
#: The memory the firmware is loaded into, and where the CPU starts at its
#: first instruction.
#: ⚠️ It has to stay below any other memory on the same bus. A devicetree
#: tells firmware which memory is its own (`zephyr,sram`), and of two
#: memories the generator names the one at the lower address.
SRAM_BASE = 0x2000_0000
SRAM_SIZE = 256 * 1024


class CpuKit(NamedTuple):
    """What a board's CPU has around it, when it is a real one."""

    #: Where the firmware is loaded, and runs from.
    sram: Placed
    #: The firmware's console: `uart.output` is what it has printed.
    uart: PlacedUart
    timer: Placed
    plic: Placed


def add_cpu_kit(
    platform: Platform,
    place: Platform | Group,
    bus: PlacedRouter,
    *,
    sources: Mapping[int, Port],
    gdb_port: int = 0,
) -> tuple[Placed, CpuKit]:
    """Put a 32-bit CPU on `bus`, with what a CPU needs around it.

    `sources` says which of the interrupt controller's sources each of the
    board's device lines goes to, numbered from 1 (source 0 means "no
    interrupt"). With a `gdb_port`, the CPU listens for a debugger on that
    TCP port and waits for one to attach before it executes anything.

    💡 A CPU has one interrupt input for all of its devices, and asks the
    controller which of them it was.
    """
    cpu = place.add(
        "cpu", DbtRiseCpu(xlen=32, reset_vector=SRAM_BASE, gdb_port=gdb_port)
    )
    sram = place.add("sram", Memory(size=SRAM_SIZE))
    uart = place.add("uart", Ns16550())
    timer = place.add("timer", MachineTimer(frequency_hz=TIMER_HZ))
    plic = place.add("plic", Plic())
    bus.map(timer.socket, base=TIMER_BASE)
    bus.map(plic.socket, base=PLIC_BASE)
    bus.map(uart.socket, base=UART_BASE)
    bus.map(sram.socket, base=SRAM_BASE)
    for source, line in sources.items():
        platform.connect(line, getattr(plic, f"source{source}"))
    platform.connect(plic.irq, cpu.irq)
    platform.connect(timer.irq, cpu.timer_irq)
    return cpu, CpuKit(sram=sram, uart=uart, timer=timer, plic=plic)
