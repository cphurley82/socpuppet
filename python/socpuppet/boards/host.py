"""🧦 The host: a 64-bit RISC-V computer, split over two dies.

    compute die                                IO die
    🧠 cpu ─▶ bus ─┬─▶ ram
       ▲  ▲        ├─▶ plic
       │  │        └─▶ link endpoint ══ link endpoint ─▶ bus ─┬─▶ uart
     plic └────────────────────────────────────────── timer ◀─┘

This is the platform behind the Zephyr board `socpuppet_host`. The compute
die has the CPU, its RAM and the interrupt controller. The IO die has the
UART and the timer. 🎭 The link between the dies is a stand-in that passes
every access straight through.

Firmware sees one flat memory map and cannot tell where the die boundary
is, which is the point: the split can change without the firmware changing.

With `drive_blocks`, the host also has an SSD on a PCIe link:

    compute die                 IO die                        SSD
       bus ─▶ link ════ link ─▶ bus ─▶ root complex ═══ endpoint ─▶ nvme
       ▲                 │                  │
       └──── link ◀══════╧══════════════════╛    DMA and interrupt messages
       └─▶ msi receiver ─▶ plic

The root complex's two windows are on the IO die. What the drive sends up
(DMA, and its interrupts, as messages) comes back across the die-to-die
link onto the compute die's bus, where the MSI receiver turns a message
into a line for the interrupt controller.

Run it:                 python -m socpuppet.boards.host path/to/zephyr.elf
See its devicetree:     socpuppet devicetree <this file>
"""

from __future__ import annotations

import sys
from typing import NamedTuple

from socpuppet.boards.ssd import Ssd, add_ssd
from socpuppet.components import (
    DbtRiseCpu,
    MachineTimer,
    Memory,
    MsiReceiver,
    Ns16550,
    PassThroughLink,
    PcieRootComplex,
    Plic,
    Router,
)
from socpuppet.placed import Placed, PlacedUart
from socpuppet.platform import Platform
from socpuppet.time import ms

#: Where the RAM starts, and where the CPU starts executing.
RAM_BASE = 0x8000_0000
RAM_SIZE = 64 * 1024 * 1024
PLIC_BASE = 0x0C00_0000
#: Everything on the IO die is inside this window of the compute die's map.
IO_BASE = 0x1000_0000
IO_SIZE = 0x0100_0000
#: Where things are on the IO die, counted from the start of its window.
UART_OFFSET = 0x0000
TIMER_OFFSET = 0x1_0000
#: With a drive: the PCIe root complex's configuration window and its
#: memory window, which is where the host places the drive's registers.
#: Both are on the IO die, counted from the start of its window. The
#: configuration window is 1 MiB, which is one bus.
ECAM_OFFSET = 0x10_0000
ECAM_SIZE = 0x10_0000
PCIE_WINDOW_OFFSET = 0x80_0000
PCIE_WINDOW_SIZE = 0x10_0000
#: Where the drive's interrupt messages are sent, on the compute die, and
#: the interrupt controller's source they come out on.
MSI_BASE = 0x0200_0000
MSI_SOURCE = 1
#: How many times a second the timer counts. The firmware has to be told
#: the same number: CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC in Zephyr.
TIMER_HZ = 10_000_000


class Host(NamedTuple):
    """The host platform, and the parts of it a test or a script wants."""

    platform: Platform
    cpu: Placed
    uart: PlacedUart
    #: The SSD, if the host was described with one.
    drive: Ssd | None = None


def host(*, gdb_port: int = 0, drive_blocks: int | None = None) -> Host:
    """Describe the host. Nothing is simulated until `platform.build()`.

    With a `gdb_port`, the CPU listens for a debugger on that TCP port and
    waits for one to attach before it executes anything. With
    `drive_blocks`, the host has an SSD of that many 512-byte blocks on a
    PCIe link.
    """
    platform = Platform()
    compute = platform.group("compute")
    io = platform.group("io")

    cpu = compute.add(
        "cpu", DbtRiseCpu(xlen=64, reset_vector=RAM_BASE, gdb_port=gdb_port)
    )
    compute_bus = compute.add("bus", Router())
    ram = compute.add("ram", Memory(size=RAM_SIZE))
    plic = compute.add("plic", Plic())
    d2d = platform.link("d2d", PassThroughLink(), compute, io)
    io_bus = io.add("bus", Router())
    uart = io.add("uart", Ns16550())
    timer = io.add("timer", MachineTimer(frequency_hz=TIMER_HZ))

    platform.connect(cpu.socket, compute_bus.target)
    compute_bus.map(ram.socket, base=RAM_BASE)
    compute_bus.map(plic.socket, base=PLIC_BASE)
    compute_bus.map(d2d.a.target, base=IO_BASE, size=IO_SIZE)
    platform.connect(d2d.b.initiator, io_bus.target)
    io_bus.map(uart.socket, base=UART_OFFSET)
    io_bus.map(timer.socket, base=TIMER_OFFSET)

    platform.connect(plic.irq, cpu.irq)
    platform.connect(timer.irq, cpu.timer_irq)
    if drive_blocks is None:
        return Host(platform, cpu, uart)

    msi = compute.add("msi", MsiReceiver())
    root_complex = io.add("rc", PcieRootComplex())
    io_bus.map(root_complex.ecam, base=ECAM_OFFSET, size=ECAM_SIZE)
    io_bus.map(
        root_complex.mmio, base=PCIE_WINDOW_OFFSET, size=PCIE_WINDOW_SIZE
    )
    # What the drive sends up crosses the die-to-die link the other way and
    # comes onto the compute die's bus.
    platform.connect(root_complex.dma, d2d.b.target)
    platform.connect(d2d.a.initiator, compute_bus.add_input())
    compute_bus.map(msi.socket, base=MSI_BASE)
    platform.connect(msi.irq, getattr(plic, f"source{MSI_SOURCE}"))
    drive = add_ssd(
        platform, root_complex, blocks=drive_blocks, group=platform.group("ssd")
    )
    return Host(platform, cpu, uart, drive)


#: What `socpuppet devicetree` looks for in a description file.
platform = host().platform

if __name__ == "__main__":
    board = host()
    board.platform.build()
    board.platform.load_elf(sys.argv[1])
    board.platform.run(ms(100))
    print(board.uart.output, end="")
