"""🧦 The host: a 64-bit RISC-V computer, split over two dies.

    compute die                                IO die
    🧠 cpu ─▶ bus ─┬─▶ ram
       ▲  ▲        ├─▶ imsic ◀─── messages ────────────────────┐
       │  │        ├─▶ timer ─┐                                │
       │  └────────│──────────┘                                │
     imsic         └─▶ link endpoint ══ link endpoint ─▶ bus ─┬─▶ aplic
                                                              └─▶ uart ─irq─▲

This is the platform behind the Zephyr board `socpuppet_host`. The compute
die has the CPU, its RAM, the interrupt controller and the timer. The IO
die has the UART, and an APLIC that the UART's interrupt line goes to.
🎭 The link between the dies is a stand-in that passes every access
straight through, unless the host is given a `manager`.

💡 Transactions and messages cross the link, and no wires. A real
die-to-die link has nowhere for an interrupt line to go down, so the
timer is on the die its CPU is on, and the interrupt controller is one
that is sent messages: an IMSIC. A device interrupts by writing a number
to the IMSIC's page, from whichever die it is on. A UART only has a
wire, so the APLIC beside it does the writing for it, and the message
goes back across the link the way a drive's does.

Firmware sees one flat memory map and cannot tell where the die boundary
is, which is the point: the split can change without the firmware changing.

With `drive_blocks`, the host also has an SSD on a PCIe link:

    compute die                 IO die                        SSD
       bus ─▶ link ════ link ─▶ bus ─▶ root complex ═══ endpoint ─▶ nvme
       ▲                 │                  │
       └──── link ◀══════╧══════════════════╛    DMA and interrupt messages
       └─▶ imsic

The root complex's two windows are on the IO die. What the drive sends up
(DMA, and its interrupts, as messages) comes back across the die-to-die
link onto the compute die's bus. A PCIe device's interrupt is a message
already, so it goes to the IMSIC as it is.

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
    Aplic,
    D2dLink,
    DbtRiseCpu,
    Imsic,
    MachineTimer,
    Memory,
    Ns16550,
    PassThroughLink,
    PcieRootComplex,
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
#: The interrupt controller's two pages, which are where messages are sent:
#: the one for machine mode, and the one for supervisor mode. They are
#: where QEMU's `virt` machine has them.
IMSIC_BASE = 0x2400_0000
IMSIC_SUPERVISOR_BASE = 0x2800_0000
#: Everything on the IO die is inside this window of the compute die's map.
IO_BASE = 0x1000_0000
IO_SIZE = 0x0100_0000
#: Where things are on the IO die, counted from the start of its window.
UART_OFFSET = 0x0000
#: The IO die's interrupt controller, which sends a message for each
#: device there that only has a wire. (On QEMU's `virt` machine an APLIC
#: is at 0x0C00_0000. Here it has to be on the IO die, so it has the same
#: digits inside the window.)
APLIC_OFFSET = 0x0C_0000
#: Which of the APLIC's sources the UART's line is. The first 15 numbers
#: are kept clear, as they are the CPU's own lines to Zephyr, which knows
#: an interrupt by one number.
UART_SOURCE = 16
#: How much address space lies behind the link for what the IO die sends
#: up: all a 64-bit address can say but its top bit, which is more than
#: the compute die has anything at.
UPLINK_REACH = 1 << 63
#: With a drive: the PCIe root complex's configuration window and its
#: memory window, which is where the host places the drive's registers.
#: Both are on the IO die, counted from the start of its window. The
#: configuration window is 1 MiB, which is one bus.
ECAM_OFFSET = 0x10_0000
ECAM_SIZE = 0x10_0000
PCIE_WINDOW_OFFSET = 0x80_0000
PCIE_WINDOW_SIZE = 0x10_0000
#: The identities the board sets aside at its interrupt controller for the
#: drive's interrupt vectors, one each. The drive does not know them:
#: firmware writes one into the drive for each vector, and that is the
#: number the drive then sends.
#:
#: 💡 Zephyr knows an interrupt by one number, whichever way it comes, so
#: the numbers are shared out. Up to 15 are the CPU's own lines, such as
#: the timer's. From 32 are for devices that send messages themselves, of
#: which the drive is the first. The 16 between are kept for devices that
#: only have a wire.
DRIVE_IDENTITIES = tuple(range(32, 32 + VECTORS))


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
    #: The host's end of the PCIe link the SSD is on.
    root_complex: Placed


class Host[Drive: PcieDrive](NamedTuple):
    """The host platform, and the parts of it a test or a script wants."""

    platform: Platform
    cpu: Placed
    uart: PlacedUart
    #: The interrupt controller, which every interrupt but the timer's
    #: comes to, as a message.
    imsic: Placed
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

    # RV64GC with supervisor and user mode: the core an application
    # processor has, and the one Linux needs. Zephyr runs on it in machine
    # mode and leaves floating point and the other two modes alone. This
    # core has no PMP, which the RV64IMAC one had.
    cpu = compute.add(
        "cpu",
        DbtRiseCpu(
            xlen=64,
            reset_vector=RAM_BASE,
            gdb_port=gdb_port,
            isa="gc",
            modes="msu",
        ),
    )
    compute_bus = compute.add("bus", Router())
    ram = compute.add("ram", Memory(size=RAM_SIZE))
    imsic = compute.add("imsic", Imsic())
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
    aplic = io.add("aplic", Aplic())
    # The way up to the compute die, for what the IO die sends of its own
    # accord: the APLIC's messages, and with a drive what the drive sends.
    up = io.add("up", Router())

    platform.connect(cpu.socket, compute_bus.target)
    compute_bus.map(ram.socket, base=RAM_BASE)
    compute_bus.map(timer.socket, base=TIMER_BASE)
    compute_bus.map(imsic.machine, base=IMSIC_BASE)
    compute_bus.map(imsic.supervisor, base=IMSIC_SUPERVISOR_BASE)
    compute_bus.map(d2d.a.target, base=IO_BASE, size=IO_SIZE)
    platform.connect(d2d.b.initiator, io_bus.target)
    io_bus.map(uart.socket, base=UART_OFFSET)
    io_bus.map(aplic.socket, base=APLIC_OFFSET)
    # The UART's interrupt is a wire as far as the APLIC, on its own die,
    # and a message from there: it crosses the die-to-die link the other
    # way and comes onto the compute die's bus, where the IMSIC's page is.
    platform.connect(uart.irq, getattr(aplic, f"source{UART_SOURCE}"))
    platform.connect(aplic.msi, up.target)
    up.map(d2d.b.target, base=0, size=UPLINK_REACH)
    platform.connect(d2d.a.initiator, compute_bus.add_input())

    platform.connect(imsic.irq, cpu.irq)
    platform.connect(imsic.supervisor_irq, cpu.supervisor_irq)
    # The IMSIC's registers are the CPU's to reach, and not on the bus.
    platform.connect(cpu.csr, imsic.csr)
    platform.connect(timer.irq, cpu.timer_irq)
    # The CPU's `time` register is the timer's count.
    platform.connect(cpu.time, timer.time)
    if drive_blocks is None:
        if drive is not None:
            raise ValueError(
                "The host was given a `drive` and not told how big it is. "
                "Say how many 512-byte blocks it holds: "
                "host(drive_blocks=4096, drive=...)."
            )
        return Host(
            platform,
            cpu,
            uart,
            imsic,
            d2d,
            drive=None,
            manager=placed_manager,
        )

    root_complex = io.add("rc", PcieRootComplex())
    io_bus.map(root_complex.ecam, base=ECAM_OFFSET, size=ECAM_SIZE)
    io_bus.map(
        root_complex.mmio, base=PCIE_WINDOW_OFFSET, size=PCIE_WINDOW_SIZE
    )
    # What the drive sends up goes the way the APLIC's messages do: its
    # DMA to the RAM, and its interrupt messages to the IMSIC's page.
    platform.connect(root_complex.dma, up.add_input())
    ssd = (drive or add_behavioral_drive)(
        platform, root_complex, blocks=drive_blocks, group=platform.group("ssd")
    )
    return Host(
        platform,
        cpu,
        uart,
        imsic,
        d2d,
        drive=HostDrive(ssd, root_complex),
        manager=placed_manager,
    )


def drive_overlay(board: Host[Any] | None = None) -> str:
    """The devicetree that the host with a drive has more than the board.

    It is the overlay of the Zephyr shield `socpuppet_host_drive`: the PCIe
    root complex, and in its node what only this board can say of it.

    - Where a device's interrupt messages go: `msi-parent`, the IMSIC.
    - Which identities are set aside there for the device's vectors. A
      message is an identity and nothing more, and no device comes with
      one: the driver writes one into the device for each vector, and that
      is the number the device then sends.
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
    imsic = devicetree.label(board.imsic.path)
    identities = " ".join(str(each) for each in DRIVE_IDENTITIES)
    return board.platform.devicetree_overlay(
        [drive.root_complex], via=board.cpu.socket
    ) + textwrap.dedent(
        f"""
        &{root_complex} {{
        \tmsi-parent = <&{imsic}>;
        \tsocpuppet,msi-identities = <{identities}>;

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
