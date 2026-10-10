"""🧦 The host: a 64-bit RISC-V computer, split over two dies.

    compute die                                IO die
    🧠 cpu ─▶ bus ─┬─▶ ram
       ▲  ▲        ├─▶ plic
       │  │        ├─▶ timer ─┐
       │  └────────│──────────┘
     plic          └─▶ link endpoint ══ link endpoint ─▶ bus ─▶ uart

This is the platform behind the Zephyr board `socpuppet_host`. The compute
die has the CPU, its RAM, the interrupt controller and the timer. The IO
die has the UART. 🎭 The link between the dies is a stand-in that passes
every access straight through, unless the host is given a `manager`.

💡 Transactions and messages cross the link, and no wires. A real
die-to-die link has nowhere for an interrupt line to go down, so the
timer is on the die its CPU is on.

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

🎭 That SSD is the stand-in drive, which answers the host itself. With
`drive=add_ssd` as well it is the real one (`socpuppet.boards.ssd`), which
has a CPU and firmware of its own. The host cannot tell which it has.

With `manager`, the link between the dies is the real one
(`sp.D2dLink`), which carries no traffic until it has been trained, and
the IO die has a manager to train it:

    compute die                         IO die
    🧠 cpu ─▶ bus ─▶ link end ═════ link end ─▶ bus ─▶ uart ...
       ▲                │             ▲  │
       └──── reset ─────┘             │  └─ irq ─────────────▶ manager
                                      └─ its registers ◀─ bus ◀──┘

The link's end on the compute die holds the host's CPU in reset. The
manager starts the training, waits for the link to say it is up, and lets
the CPU go with a message to the other end. It has a bus of its own, with
the link's registers on it and nothing the host reaches, so the host's
firmware sees the same map with either link and is the same image.

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
from typing import Any, NamedTuple, Protocol, overload

from socpuppet import devicetree
from socpuppet.boards.cpu_kit import TIMER_BASE, TIMER_HZ
from socpuppet.boards.drive import (
    VECTORS,
    BehavioralDrive,
    add_behavioral_drive,
)
from socpuppet.boards.manager import Manager
from socpuppet.components import (
    D2dLink,
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
from socpuppet.placed import Placed, PlacedRouter, PlacedUart
from socpuppet.platform import Group, Link, Platform
from socpuppet.time import ms

#: Where the RAM starts, and where the CPU starts executing.
RAM_BASE = 0x8000_0000
RAM_SIZE = 64 * 1024 * 1024
# The timer has no constant here: it is at `cpu_kit.TIMER_BASE`, where
# every other socpuppet CPU has its timer.
#: The interrupt controller.
PLIC_BASE = 0x0C00_0000
#: Everything on the IO die is inside this window of the compute die's map.
IO_BASE = 0x1000_0000
IO_SIZE = 0x0100_0000
#: Where things are on the IO die, counted from the start of its window.
UART_OFFSET = 0x0000
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
MSI_BASE = 0x0300_0000
MSI_SOURCE = 1


class PcieDrive(Protocol):
    """What a host asks of whatever is on its PCIe link."""

    @property
    def endpoint(self) -> Placed | None:
        """The drive's PCIe endpoint: what it says of itself to a host."""


class AddDrive[Drive: PcieDrive](Protocol):
    """A function that describes a drive on a root complex's PCIe link.

    `add_behavioral_drive` is one and `socpuppet.boards.ssd.add_ssd` is
    another. Which of them a host is given is how much of an SSD it has.
    """

    def __call__(
        self,
        platform: Platform,
        root_complex: Placed,
        *,
        blocks: int,
        group: Group,
    ) -> Drive:
        """Describe a drive of `blocks` 512-byte blocks, in `group`."""


class AddManager(Protocol):
    """A function that describes the IO die's manager.

    `socpuppet.boards.manager.add_manager` is one, and with a `script`
    filled in it is another. Which of them a host is given is how much of
    a manager it has.
    """

    def __call__(
        self,
        platform: Platform,
        place: Group,
        bus: PlacedRouter,
        *,
        link_end: Placed,
    ) -> Manager:
        """Describe the manager on `bus`, with this die's end of the link."""


class HostDrive[Drive: PcieDrive](NamedTuple):
    """The host's SSD, and what the host has for its sake."""

    #: What the host's `drive` function returned: 🎭 the stand-in drive
    #: unless the host was given another.
    ssd: Drive
    #: The bridge that takes the SSD's interrupt messages.
    msi: Placed
    #: The host's end of the PCIe link the SSD is on.
    root_complex: Placed


class Host[Drive: PcieDrive](NamedTuple):
    """The host platform, and the parts of it a test or a script wants."""

    platform: Platform
    cpu: Placed
    uart: PlacedUart
    #: The link between the two dies: `link.a` is the compute die's end,
    #: `link.b` the IO die's.
    link: Link
    #: The SSD and its way in, if the host was described with one.
    drive: HostDrive[Drive] | None = None
    #: The IO die's manager, if the host was described with one.
    manager: Manager | None = None


# The two declarations are for a type checker. They say that the host
# has the kind of drive its `drive` function makes, so that after
# `host(drive=add_ssd)` it knows `board.drive.ssd` has a CPU.
@overload
def host(
    *,
    gdb_port: int = 0,
    drive_blocks: int | None = None,
    manager: AddManager | None = None,
    trace: bool = False,
) -> Host[BehavioralDrive]: ...
@overload
def host[Drive: PcieDrive](
    *,
    gdb_port: int = 0,
    drive_blocks: int | None = None,
    drive: AddDrive[Drive],
    manager: AddManager | None = None,
    trace: bool = False,
) -> Host[Drive]: ...
def host(
    *,
    gdb_port: int = 0,
    drive_blocks: int | None = None,
    drive: AddDrive[Any] | None = None,
    manager: AddManager | None = None,
    trace: bool = False,
) -> Host[Any]:
    """Describe the host. Nothing is simulated until `platform.build()`.

    With a `gdb_port`, the CPU listens for a debugger on that TCP port and
    waits for one to attach before it executes anything. With
    `drive_blocks`, the host has an SSD of that many 512-byte blocks on a
    PCIe link.

    `drive` is the function that describes that SSD. 🎭 With none it is
    the stand-in drive, `add_behavioral_drive`. `drive=add_ssd`, from
    `socpuppet.boards.ssd`, is the SSD with a CPU of its own, and its
    firmware is then a second image to load:
    `platform.load_elf(file, via=board.drive.ssd.cpu.socket)`.

    `manager` is the function that describes the IO die's manager, and
    with one the link between the dies is the real one, `sp.D2dLink`,
    whose end holds the host's CPU in reset until the manager has trained
    the link and let it go. 🎭 With none the link is the pass-through
    stand-in and the CPU starts at once. `add_manager`, from
    `socpuppet.boards.manager`, is that function, and with
    `functools.partial(add_manager, script=stand_in_manager().script)`
    the manager is 🎭 a script. ⚠️ A host with a manager has two bus
    masters, so say whose: `platform.load_elf(file, via=board.cpu.socket)`.

    With `trace=True`, everything that crosses the link between the dies
    is recorded, in `platform.trace`: what each die sends the other, and
    on the real link its management traffic, the sideband, apart from
    that (`socpuppet.ucie` reads its packets back).
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
    timer = compute.add("timer", MachineTimer(frequency_hz=TIMER_HZ))
    link_model = PassThroughLink() if manager is None else D2dLink()
    d2d = platform.link("d2d", link_model, compute, io, trace=trace)
    placed_manager = None
    if manager is not None:
        platform.connect(d2d.a.reset, cpu.reset)
        # The manager has a bus of its own, with the link's registers on
        # it and nothing the host reaches. On the IO die's main bus it
        # would find the root complex's window at another address than
        # the host's CPU does, which a platform refuses, and the host's
        # devicetree would gain the link's registers.
        management = io.group("manager")
        placed_manager = manager(
            platform,
            management,
            management.add("bus", Router()),
            link_end=d2d.b,
        )
    io_bus = io.add("bus", Router())
    uart = io.add("uart", Ns16550())

    platform.connect(cpu.socket, compute_bus.target)
    compute_bus.map(ram.socket, base=RAM_BASE)
    compute_bus.map(timer.socket, base=TIMER_BASE)
    compute_bus.map(plic.socket, base=PLIC_BASE)
    compute_bus.map(d2d.a.target, base=IO_BASE, size=IO_SIZE)
    platform.connect(d2d.b.initiator, io_bus.target)
    io_bus.map(uart.socket, base=UART_OFFSET)

    platform.connect(plic.irq, cpu.irq)
    platform.connect(timer.irq, cpu.timer_irq)
    if drive_blocks is None:
        if drive is not None:
            raise ValueError(
                "The host was given a `drive` and not told how big it is. "
                "Say how many 512-byte blocks it holds: "
                "host(drive_blocks=4096, drive=...)."
            )
        return Host(
            platform, cpu, uart, d2d, drive=None, manager=placed_manager
        )

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
    ssd = (drive or add_behavioral_drive)(
        platform, root_complex, blocks=drive_blocks, group=platform.group("ssd")
    )
    return Host(
        platform,
        cpu,
        uart,
        d2d,
        drive=HostDrive(ssd, msi, root_complex),
        manager=placed_manager,
    )


def drive_overlay(board: Host[Any] | None = None) -> str:
    """The devicetree that the host with a drive has more than the board.

    It is the overlay of the Zephyr shield `socpuppet_host_drive`: the MSI
    bridge and the PCIe root complex, and in the root complex's node what
    only this board can say of it.

    - Where a device's interrupt messages go: `msi-parent`, the bridge.
    - A node for the drive. 🎓 A device on a PCIe link is found by
      scanning, so a devicetree need not list it. Zephyr wants a node all
      the same, to attach its driver to, and matches it to what the scan
      finds by the vendor and device numbers.

    `board` is a host with a drive, and by default the host with 🎭 the
    stand-in drive. The overlay is what the host's CPU sees, which is the
    same with the SSD on the link, so there is one shield for both.

    The shield's copy is checked in, and a test holds it to this. To write
    the file again, print what this returns into it, with no newline added.
    """
    if board is None:
        # The devicetree does not say how big the drive is, so any size
        # will do.
        board = host(drive_blocks=1)
    drive = board.drive
    assert drive is not None
    endpoint = drive.ssd.endpoint
    assert endpoint is not None
    root_complex = devicetree.label(drive.root_complex.path)
    msi = devicetree.label(drive.msi.path)
    return board.platform.devicetree_overlay(
        [drive.msi, drive.root_complex], via=board.cpu.socket
    ) + textwrap.dedent(
        f"""
        &{root_complex} {{
        \tmsi-parent = <&{msi}>;

        \tnvme0: nvme0 {{
        \t\tcompatible = "nvme-controller";
        \t\tvendor-id = <{endpoint.component.parameters["vendor_id"]:#x}>;
        \t\tdevice-id = <{endpoint.component.parameters["device_id"]:#x}>;
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
