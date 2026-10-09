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
       └─▶ msi bridge ═▶ plic                    (a line for each vector)

The root complex's two windows are on the IO die. What the drive sends up
(DMA, and its interrupts, as messages) comes back across the die-to-die
link onto the compute die's bus. There the MSI bridge turns each message
into a pulse on a line of the interrupt controller, one line for each of
the drive's interrupt vectors.

The Zephyr board is the host with no drive. Firmware for the host with
one is built with a shield as well, `socpuppet_host_drive`. A shield is
Zephyr's word for hardware plugged into a board, and `drive_overlay()`
writes the devicetree this one adds.

Run it:                 python -m socpuppet.boards.host path/to/zephyr.elf
See its devicetree:     socpuppet devicetree <this file>
"""

from __future__ import annotations

import sys
import textwrap
from typing import NamedTuple

from socpuppet import devicetree
from socpuppet.boards.drive import (
    VECTORS,
    BehavioralDrive,
    add_behavioral_drive,
)
from socpuppet.components import (
    DbtRiseCpu,
    MachineTimer,
    Memory,
    MsiPlicBridge,
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
#: the interrupt controller's source that the first vector comes out on.
#: The vectors after it take the sources after it.
MSI_BASE = 0x0200_0000
MSI_SOURCE = 1
#: How many times a second the timer counts. The firmware has to be told
#: the same number: CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC in Zephyr.
TIMER_HZ = 10_000_000


class HostDrive(NamedTuple):
    """The host's SSD, and what the host has for its sake."""

    ssd: BehavioralDrive
    #: The bridge that takes the SSD's interrupt messages.
    msi: Placed
    #: The host's end of the PCIe link the SSD is on.
    root_complex: Placed


class Host(NamedTuple):
    """The host platform, and the parts of it a test or a script wants."""

    platform: Platform
    cpu: Placed
    uart: PlacedUart
    #: The SSD and its way in, if the host was described with one.
    drive: HostDrive | None = None


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

    msi = compute.add("msi", MsiPlicBridge(vectors=VECTORS))
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
    for vector in range(VECTORS):
        platform.connect(
            getattr(msi, f"irq{vector}"),
            getattr(plic, f"source{MSI_SOURCE + vector}"),
        )
    ssd = add_behavioral_drive(
        platform, root_complex, blocks=drive_blocks, group=platform.group("ssd")
    )
    return Host(platform, cpu, uart, HostDrive(ssd, msi, root_complex))


def drive_overlay() -> str:
    """The devicetree that the host with a drive has more than the board.

    It is the overlay of the Zephyr shield `socpuppet_host_drive`: the MSI
    bridge and the PCIe root complex, and in the root complex's node what
    only this board can say of it.

    - Where a device's interrupt messages go: `msi-parent`, the bridge.
    - A node for the drive. 🎓 A device on a PCIe link is found by
      scanning, so a devicetree need not list it. Zephyr wants a node all
      the same, to attach its driver to, and matches it to what the scan
      finds by the vendor and device numbers.

    The shield's copy is checked in, and a test holds it to this. To write
    the file again, print what this returns into it, with no newline added.
    """
    # The devicetree does not say how big the drive is, so any size will do.
    board = host(drive_blocks=1)
    drive = board.drive
    assert drive is not None
    endpoint = drive.ssd.endpoint.component
    root_complex = devicetree.label(drive.root_complex.path)
    msi = devicetree.label(drive.msi.path)
    return board.platform.devicetree_overlay(
        [drive.msi, drive.root_complex]
    ) + textwrap.dedent(
        f"""
        &{root_complex} {{
        \tmsi-parent = <&{msi}>;

        \tnvme0: nvme0 {{
        \t\tcompatible = "nvme-controller";
        \t\tvendor-id = <{endpoint.parameters["vendor_id"]:#x}>;
        \t\tdevice-id = <{endpoint.parameters["device_id"]:#x}>;
        \t}};
        }};
        """
    )


#: What `socpuppet devicetree` looks for in a description file.
platform = host().platform

if __name__ == "__main__":
    board = host()
    board.platform.build()
    board.platform.load_elf(sys.argv[1])
    board.platform.run(ms(100))
    print(board.uart.output, end="")
