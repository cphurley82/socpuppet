"""🧦 The host: a 64-bit RISC-V computer, split over two dies.

    compute die                                IO die
    🧠 cpu ─▶ bus ─┬─▶ ram
       ▲  ▲        ├─▶ imsic ◀─── messages ────────────────────┐
       │  │        ├─▶ timer ─┐                                │
       │  └────────│──────────┘                                │
     imsic         ├─▶ aplic ─▶ messages, onto this bus        │
                   └─▶ link endpoint ══ link endpoint ─▶ bus ─┬─▶ aplic
                                                              └─▶ uart ─irq─▲

This is the platform behind the Zephyr board `socpuppet_host`. The compute
die has the CPU, its RAM, the interrupt controller, the timer, the system
controller, which drives the CPU's reset, and an APLIC of its own. The IO
die has the UART, an APLIC that the UART's interrupt line goes to, and
the flash the host boots from.
🎭 The link between the dies is a stand-in that passes every access
straight through, unless the host is given a `manager`.

💡 Transactions and messages cross the link, and no wires. A real
die-to-die link has nowhere for an interrupt line to go down, so the
timer is on the die its CPU is on, and the interrupt controller is one
that is sent messages: an IMSIC. A device interrupts by writing a number
to the IMSIC's page, from whichever die it is on. A UART only has a
wire, so the APLIC beside it does the writing for it, and the message
goes back across the link the way a drive's does. A wire stays on its
die, so the compute die has an APLIC of its own, for a device there that
only has a wire.

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
       └ reset ─ syscon ◀─ hold       │  └─ irq ─────────────▶ manager
                                      └─ its registers ◀─ bus ◀──┘

The link's end on the compute die holds the host's CPU in reset, by a
line to the CPU's system controller, which is what drives the reset. The
manager starts the training, waits for the link to say it is up, and lets
the CPU go with a message to the other end. It has a bus of its own, with
the link's registers on it and, but for the flash both of them boot from,
nothing the host reaches. So the host's firmware sees the same map with
either link and is the same image.

The Zephyr board is the host with no drive. Firmware for the host with
one is built with a shield as well, `socpuppet_host_drive`. A shield is
Zephyr's word for hardware plugged into a board, and `drive_overlay()`
writes the devicetree this one adds.

Run it:                 python -m socpuppet.boards.host path/to/zephyr.elf
See its devicetree:     socpuppet devicetree <this file>
"""

from __future__ import annotations

import os
import sys
import textwrap
from typing import Any, Literal, NamedTuple, Protocol, overload

from socpuppet import devicetree
from socpuppet.boards.boot import ROM_BASE, Boot
from socpuppet.boards.cpu_kit import (
    BOOT_FLASH_BASE,
    BOOT_FLASH_CONTROLLER_BASE,
    BOOT_FLASH_SIZE,
    COMPUTE_DIE,
    HOST_IMAGE_OFFSET,
    PLIC_BASE,
    TIMER_BASE,
    TIMER_HZ,
    add_system_controller,
    add_watchdog,
)
from socpuppet.boards.drive import (
    VECTORS,
    BehavioralDrive,
    add_behavioral_drive,
)
from socpuppet.boards.manager import Manager
from socpuppet.boards.virtio import Virtio, VirtioSlots, add_virtio
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
    QboxCpu,
    Router,
    SpiFlash,
)
from socpuppet.placed import Placed, PlacedRouter, PlacedUart
from socpuppet.platform import Group, Link, Platform
from socpuppet.time import ms

#: Which of its two CPUs the host has: socpuppet's own, or QEMU's.
type HostCpu = Literal["dbt_rise_cpu", "qbox_cpu"]

#: Where the RAM starts, and where the CPU starts executing.
RAM_BASE = 0x8000_0000
RAM_SIZE = 64 * 1024 * 1024
# The timer and the system controller have no constants here: they are at
# `cpu_kit.TIMER_BASE` and `cpu_kit.SYSCON_BASE`, where every other
# socpuppet CPU has its own.
#: The interrupt controller's two pages, which are where messages are sent:
#: the one for machine mode, and the one for supervisor mode. They are
#: where QEMU's `virt` machine has them.
IMSIC_BASE = 0x2400_0000
IMSIC_SUPERVISOR_BASE = 0x2800_0000
#: Everything on the IO die is inside this window of the compute die's map.
#: 32 MiB, so that it reaches past the PCIe memory window, which is after
#: the 16 MiB boot flash.
IO_BASE = 0x1000_0000
IO_SIZE = 0x0200_0000
#: Where things are on the IO die, counted from the start of its window.
UART_OFFSET = 0x0000
#: The IO die's interrupt controller, which sends a message for each
#: device there that only has a wire. (On QEMU's `virt` machine an APLIC
#: is at 0x0C00_0000. This one has to be on the IO die, so it has the same
#: digits inside the window.)
APLIC_OFFSET = 0x0C_0000
#: The compute die's own, for a device there that only has a wire: an
#: interrupt line does not cross to another die, so each die that has such
#: a device has an APLIC. It is where `virt` has its APLIC, which is also
#: where a 32-bit socpuppet CPU has its PLIC.
COMPUTE_APLIC_BASE = PLIC_BASE
#: Which source of the compute die's APLIC the watchdog's line is: the
#: number after the UART's, since no number is a source at both APLICs.
WATCHDOG_SOURCE = 17
#: Which source of the IO die's APLIC the UART's line is. The first 15
#: numbers are kept clear, as they are the CPU's own lines to Zephyr, which
#: knows an interrupt by one number.
UART_SOURCE = 16
#: How much address space lies behind the link for what the IO die sends
#: up: all a 64-bit address can say but its top bit, which is more than
#: the compute die has anything at.
UPLINK_REACH = 1 << 63
#: With a drive: the PCIe root complex's configuration window and its
#: memory window, which is where the host places the drive's registers.
#: Both are on the IO die, counted from the start of its window. The
#: configuration window is 1 MiB, which is one bus, and the memory window
#: is after the boot flash.
ECAM_OFFSET = 0x10_0000
ECAM_SIZE = 0x10_0000
PCIE_WINDOW_OFFSET = 0x120_0000
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
    #: The system controller, which drives the CPU's reset and tells its
    #: boot ROM where the host's image is.
    syscon: Placed
    #: The watchdog, which has the system controller reset the CPU when
    #: firmware stops feeding it.
    wdt: Placed
    #: The flash on the IO die that the host boots from, and with a manager
    #: the manager too. Fill it through the CPU:
    #: `platform.load_binary(image, at=BOOT_FLASH_BASE, via=board.cpu.socket)`.
    boot_flash: Placed
    #: The SSD and its way in, if the host was described with one.
    drive: HostDrive[Drive] | None = None
    #: The IO die's manager, if the host was described with one.
    manager: Manager | None = None
    #: The boot ROM the CPU starts in, if the host was described with one.
    #: Its program is loaded through the CPU:
    #: `platform.load_elf("rom_rv64.elf", via=board.cpu.socket)`.
    rom: Placed | None = None
    #: 🎭 The virtio devices, one to a slot on the IO die, if the host was
    #: described with them (`virtio=Virtio()`).
    virtio: VirtioSlots | None = None


# The two declarations are for a type checker. They say that the host
# has the kind of drive its `drive` function makes, so that after
# `host(drive=add_ssd)` it knows `board.drive.ssd` has a CPU.
@overload
def host(
    *,
    cpu: HostCpu | None = None,
    gdb_port: int = 0,
    boot: Boot | None = None,
    drive_blocks: int | None = None,
    manager: AddManager | None = None,
    trace: bool = False,
    ram: int = RAM_SIZE,
    sbi: bool = False,
    virtio: Virtio | None = None,
) -> Host[BehavioralDrive]: ...
@overload
def host[Drive: PcieDrive](
    *,
    cpu: HostCpu | None = None,
    gdb_port: int = 0,
    boot: Boot | None = None,
    drive_blocks: int | None = None,
    drive: AddDrive[Drive],
    manager: AddManager | None = None,
    trace: bool = False,
    ram: int = RAM_SIZE,
    sbi: bool = False,
    virtio: Virtio | None = None,
) -> Host[Drive]: ...
def host(
    *,
    cpu: HostCpu | None = None,
    gdb_port: int = 0,
    boot: Boot | None = None,
    drive_blocks: int | None = None,
    drive: AddDrive[Any] | None = None,
    manager: AddManager | None = None,
    trace: bool = False,
    ram: int = RAM_SIZE,
    sbi: bool = False,
    virtio: Virtio | None = None,
) -> Host[Any]:
    """Describe the host. Nothing is simulated until `platform.build()`.

    `cpu` is which RISC-V CPU it has, by its name in the simulator:
    `"dbt_rise_cpu"`, socpuppet's own, or `"qbox_cpu"`, QEMU's, which only
    a build of socpuppet with QBox has (`sp.QboxCpu`). Either is RV64GC
    with supervisor and user mode, and the board is the same around it.
    With none it is the one the environment variable SOCPUPPET_CPU names,
    and else socpuppet's own: so one variable runs every host a program
    describes on the other CPU.

    With a `gdb_port`, the CPU listens for a debugger on that TCP port and
    waits for one to attach before it executes anything.

    `boot` is what the CPU starts in. 🎭 With none it starts in its RAM,
    where `platform.load_elf` has put its firmware, which is the quick way
    to try an image. With `boot=from_rom`, from `socpuppet.boards.boot`,
    it starts in a boot ROM, which finds the firmware in the IO die's
    flash, copies it to RAM and jumps to it, as silicon does. That module
    says what is then loaded, and where.

    With `drive_blocks`, the host has an SSD of that many 512-byte blocks on a
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

    `ram` is how many bytes of RAM the CPU has: 64 MiB unless it is said,
    and with a ROM no less, since the ROM keeps its stack at the top of
    64 MiB.

    With `sbi=True` the host is described for firmware that is a monitor
    in machine mode with an operating system below it in supervisor mode,
    as OpenSBI is with Linux: both APLICs send their messages to the
    IMSIC's page for supervisor mode, since neither of those says where.
    Without it nobody has said, and Zephyr's driver says where when it
    reads that.
    """
    if boot is not None and ram < RAM_SIZE:
        raise ValueError(
            f"The host was given {ram:#x} bytes of RAM and a ROM, whose "
            "program keeps its stack at the top of 64 MiB of RAM. Give it "
            "64 MiB or more."
        )
    if drive is not None and drive_blocks is None:
        raise ValueError(
            "The host was given a `drive` and not told how big it is. "
            "Say how many 512-byte blocks it holds: "
            "host(drive_blocks=4096, drive=...)."
        )
    named_by = "SOCPUPPET_CPU" if cpu is None else "The host's cpu"
    chosen = cpu or os.environ.get("SOCPUPPET_CPU", DbtRiseCpu.implementation)
    if chosen not in HOST_CPUS:
        raise ValueError(
            f'{named_by} is "{chosen}", and the CPUs the host can have are '
            + " and ".join(f'"{name}"' for name in HOST_CPUS)
            + "."
        )
    if chosen == QboxCpu.implementation and gdb_port:
        raise ValueError(
            "The host was given a gdb_port with QBox's CPU, and the GDB "
            'server is the other one\'s. Debug on the "dbt_rise_cpu".'
        )
    platform = Platform()
    compute_group = platform.group("compute")
    io_group = platform.group("io")
    # Where an APLIC sends its messages before firmware says, if it never
    # will.
    messages_to = IMSIC_SUPERVISOR_BASE if sbi else 0
    compute = _compute_die(
        platform,
        compute_group,
        cpu=chosen,
        gdb_port=gdb_port,
        boot=boot,
        ram=ram,
        messages_to=messages_to,
    )
    link_model = PassThroughLink() if manager is None else D2dLink()
    d2d = platform.link("d2d", link_model, compute_group, io_group, trace=trace)
    io = _io_die(platform, io_group, messages_to=messages_to)
    slots = (
        None
        if virtio is None
        else add_virtio(platform, io_group, io.bus, io.up, io.aplic, virtio)
    )
    placed_manager = None
    if manager is not None:
        # The link's end holds the host's CPU until the manager lets it
        # go. The CPU's reset is its system controller's to drive, so the
        # line goes to that.
        platform.connect(d2d.a.reset, compute.syscon.hold)
        # The manager has a bus of its own, with the link's registers on
        # it and, but for the flash, nothing the host reaches. On the IO
        # die's main bus it would find the root complex's window at
        # another address than the host's CPU does, which a platform
        # refuses, and the host's devicetree would gain the link's
        # registers.
        management = io_group.group("manager")
        management_bus = management.add("bus", Router())
        placed_manager = manager(
            platform, management, management_bus, link_end=d2d.b
        )
        # The one thing on both buses: the flash both CPUs boot from, which
        # the manager finds where the host's CPU does.
        management_bus.map(
            io.boot_flash_bus.add_input(),
            base=BOOT_FLASH_BASE,
            size=BOOT_FLASH_SIZE,
        )
    # Down the link: the compute die sees the IO die's bus in a window.
    compute.bus.map(d2d.a.target, base=IO_BASE, size=IO_SIZE)
    platform.connect(d2d.b.initiator, io.bus.target)
    # And up it: what the IO die sends comes onto the compute die's bus.
    io.up.map(d2d.b.target, base=0, size=UPLINK_REACH)
    platform.connect(d2d.a.initiator, compute.bus.add_input())
    return Host(
        platform,
        compute.cpu,
        io.uart,
        compute.imsic,
        d2d,
        compute.syscon,
        compute.wdt,
        io.boot_flash,
        drive=(
            None
            if drive_blocks is None
            else _drive(
                platform,
                io_group,
                io,
                blocks=drive_blocks,
                add=drive or add_behavioral_drive,
            )
        ),
        manager=placed_manager,
        rom=compute.rom,
        virtio=slots,
    )


class _ComputeDie(NamedTuple):
    """What the rest of the host wants of its compute die."""

    cpu: Placed
    bus: PlacedRouter
    imsic: Placed
    syscon: Placed
    wdt: Placed
    rom: Placed | None


#: The CPUs the host can have, by their names in the simulator, which are
#: what `host(cpu=)`, `socpuppet run --cpu` and SOCPUPPET_CPU take.
HOST_CPUS: tuple[HostCpu, ...] = ("dbt_rise_cpu", "qbox_cpu")


def _compute_die(
    platform: Platform,
    place: Group,
    *,
    cpu: str,
    gdb_port: int,
    boot: Boot | None,
    ram: int,
    messages_to: int,
) -> _ComputeDie:
    """Describe the die the CPU is on, up to its end of the link."""
    bus = place.add("bus", Router())
    rom = None if boot is None else boot(place, bus)
    # RV64GC with supervisor and user mode: the core an application
    # processor has, and the one Linux needs. Zephyr runs on it in machine
    # mode and leaves floating point and the other two modes alone. This
    # core has no PMP, which the RV64IMAC one had.
    reset_vector = RAM_BASE if rom is None else ROM_BASE
    placed_cpu = place.add(
        "cpu",
        QboxCpu(xlen=64, reset_vector=reset_vector)
        if cpu == QboxCpu.implementation
        else DbtRiseCpu(
            xlen=64,
            reset_vector=reset_vector,
            gdb_port=gdb_port,
            isa="gc",
            modes="msu",
        ),
    )
    placed_ram = place.add("ram", Memory(size=ram))
    imsic = place.add("imsic", Imsic())
    timer = place.add("timer", MachineTimer(frequency_hz=TIMER_HZ))
    # For a device on this die that only has a wire. Its messages go onto
    # this die's own bus, where the IMSIC's page is.
    aplic = place.add("aplic", Aplic(messages_to=messages_to))
    platform.connect(placed_cpu.socket, bus.target)
    syscon = add_system_controller(
        platform,
        place,
        bus,
        placed_cpu,
        die=COMPUTE_DIE,
        boot_address=BOOT_FLASH_BASE + HOST_IMAGE_OFFSET,
    )
    bus.map(placed_ram.socket, base=RAM_BASE)
    bus.map(timer.socket, base=TIMER_BASE)
    bus.map(imsic.machine, base=IMSIC_BASE)
    bus.map(imsic.supervisor, base=IMSIC_SUPERVISOR_BASE)
    bus.map(aplic.socket, base=COMPUTE_APLIC_BASE)
    platform.connect(aplic.msi, bus.add_input())
    wdt = add_watchdog(
        platform,
        place,
        bus,
        syscon,
        irq=getattr(aplic, f"source{WATCHDOG_SOURCE}"),
    )
    platform.connect(imsic.irq, placed_cpu.irq)
    platform.connect(imsic.supervisor_irq, placed_cpu.supervisor_irq)
    # The IMSIC's registers are the CPU's to reach, and not on the bus.
    platform.connect(placed_cpu.csr, imsic.csr)
    platform.connect(timer.irq, placed_cpu.timer_irq)
    # The CPU's `time` register is the timer's count.
    platform.connect(placed_cpu.time, timer.time)
    return _ComputeDie(placed_cpu, bus, imsic, syscon, wdt, rom)


class _IoDie(NamedTuple):
    """What the rest of the host wants of its IO die."""

    bus: PlacedRouter
    uart: PlacedUart
    #: The die's interrupt controller, for a device there with a line.
    aplic: Placed
    #: The way up to the compute die, for what the IO die sends of its own
    #: accord: the APLIC's messages, and with a drive what the drive sends.
    up: PlacedRouter
    boot_flash: Placed
    #: The way to the flash's window. A socket takes one connection, and
    #: the flash has two readers when the die has a manager, so each comes
    #: in by an input of this.
    boot_flash_bus: PlacedRouter


def _io_die(platform: Platform, place: Group, *, messages_to: int) -> _IoDie:
    """Describe the die the devices are on, up to its end of the link."""
    bus = place.add("bus", Router())
    uart = place.add("uart", Ns16550())
    aplic = place.add("aplic", Aplic(messages_to=messages_to))
    up = place.add("up", Router())
    boot_flash = place.add("boot_flash", SpiFlash(size=BOOT_FLASH_SIZE))
    boot_flash_bus = place.add("boot_flash_bus", Router())
    bus.map(uart.socket, base=UART_OFFSET)
    bus.map(aplic.socket, base=APLIC_OFFSET)
    # The flash is where every socpuppet CPU has its own, which for this
    # die's devices is a place in the window the compute die sees them in.
    bus.map(boot_flash.socket, base=BOOT_FLASH_CONTROLLER_BASE - IO_BASE)
    bus.map(
        boot_flash_bus.target,
        base=BOOT_FLASH_BASE - IO_BASE,
        size=BOOT_FLASH_SIZE,
    )
    boot_flash_bus.map(boot_flash.xip, base=0)
    # The UART's interrupt is a wire as far as the APLIC, on its own die,
    # and a message from there: it crosses the die-to-die link the other
    # way and comes onto the compute die's bus, where the IMSIC's page is.
    platform.connect(uart.irq, getattr(aplic, f"source{UART_SOURCE}"))
    platform.connect(aplic.msi, up.target)
    return _IoDie(bus, uart, aplic, up, boot_flash, boot_flash_bus)


def _drive[Drive: PcieDrive](
    platform: Platform,
    place: Group,
    io: _IoDie,
    *,
    blocks: int,
    add: AddDrive[Drive],
) -> HostDrive[Drive]:
    """Describe a PCIe root complex on the IO die, and the SSD on its link."""
    root_complex = place.add("rc", PcieRootComplex())
    io.bus.map(root_complex.ecam, base=ECAM_OFFSET, size=ECAM_SIZE)
    io.bus.map(
        root_complex.mmio, base=PCIE_WINDOW_OFFSET, size=PCIE_WINDOW_SIZE
    )
    # What the drive sends up goes the way the APLIC's messages do: its
    # DMA to the RAM, and its interrupt messages to the IMSIC's page.
    platform.connect(root_complex.dma, io.up.add_input())
    ssd = add(
        platform, root_complex, blocks=blocks, group=platform.group("ssd")
    )
    return HostDrive(ssd, root_complex)


def drive_overlay(board: Host[Any] | None = None) -> str:
    """The devicetree that the host with a drive has more than the board.

    It is the overlay of the Zephyr shield `socpuppet_host_drive`: the PCIe
    root complex, with where a device's interrupt messages go (`msi-parent`,
    which the root complex's own description finds: it is whatever takes
    messages that its `dma` reaches). And in its node, what only this board
    can say of it.

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
    identities = " ".join(str(each) for each in DRIVE_IDENTITIES)
    return board.platform.devicetree_overlay(
        [drive.root_complex], via=board.cpu.socket
    ) + textwrap.dedent(
        f"""
        &{root_complex} {{
        \tsocpuppet,msi-identities = <{identities}>;

        \tnvme0: nvme0 {{
        \t\tcompatible = "nvme-controller";
        \t\tvendor-id = <{endpoint.component.parameters["vendor_id"]:#x}>;
        \t\tdevice-id = <{endpoint.component.parameters["device_id"]:#x}>;
        \t}};
        }};
        """
    )


#: What `socpuppet devicetree` looks for in a description file. The
#: devicetree is the same with either CPU, and this one does not depend on
#: what SOCPUPPET_CPU says.
platform = host(cpu="dbt_rise_cpu").platform

if __name__ == "__main__":
    board = host()
    board.platform.build()
    board.platform.load_elf(sys.argv[1])
    board.platform.run(ms(100))
    print(board.uart.output, end="")
