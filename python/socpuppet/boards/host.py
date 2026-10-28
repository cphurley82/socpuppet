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
die has the UART, an APLIC that the UART's interrupt line goes to, the
flash the host boots from, and a GPIO with four pins brought out, 🧵 with
Python at the far end of them.
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
from collections.abc import Mapping
from types import MappingProxyType
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
    SYSCON_BASE,
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
    Gpio,
    I2cController,
    Imsic,
    Iommu,
    MachineTimer,
    Memory,
    Ns16550,
    PassThroughLink,
    PcieRootComplex,
    QboxCpu,
    Router,
    SpiFlash,
)
from socpuppet.i2c import I2cDevice
from socpuppet.placed import Placed, PlacedGpio, PlacedRouter, PlacedUart
from socpuppet.platform import Group, Link, Platform
from socpuppet.regs import system_controller
from socpuppet.spi import SpiDevice
from socpuppet.time import ms

#: Which of its two CPUs the host has: socpuppet's own, or QEMU's.
type HostCpu = Literal["dbt_rise_cpu", "qbox_cpu"]

#: The name socpuppet gives the host in its devicetree (`model`), which
#: OpenSBI's banner repeats as the platform's name.
MODEL = "socpuppet host"
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
#: 🎭 With virtio devices: where their slots start, counted from the start
#: of the IO die's window, which is where QEMU's `virt` has its first
#: slot; and which source of the IO die's APLIC the first slot's line is,
#: the number after the watchdog's at the compute die's, since no number
#: is a source at both. The slots are a page apart (`VIRTIO_SLOT_STRIDE`).
VIRTIO_SLOT_OFFSET = 0x1000
VIRTIO_FIRST_SOURCE = 18
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
#: With an IOMMU: where its registers are, counted from the start of the IO
#: die's window, the page after the boot flash's controller; and which
#: source of the IO die's APLIC its line is, the number after the virtio
#: slots'.
IOMMU_OFFSET = 0x0E_0000
IOMMU_SOURCE = 24
#: The GPIO: where its registers are, counted from the start of the IO
#: die's window, the page after the IOMMU's; how many of its pins the board
#: brings out; and which source of the IO die's APLIC the first pin's line
#: is, the number after the IOMMU's, with the other pins' after it.
GPIO_OFFSET = 0x0F_0000
GPIO_PINS = 4
GPIO_FIRST_SOURCE = 25
#: The pin the board has its LED on, which Zephyr knows as `led0`: not
#: one of the two the shield `socpuppet_host_gpio_loopback` wires
#: (`GPIO_LOOPBACK_OUT`, `GPIO_LOOPBACK_IN`).
GPIO_LED = 2
#: Which source of the IO die's APLIC the boot flash's controller's line
#: is: the number after the GPIO's pins'.
BOOT_FLASH_SOURCE = GPIO_FIRST_SOURCE + GPIO_PINS
#: The I2C controller: where its registers are, counted from the start of
#: the IO die's window, the page after the GPIO's; and which source of the
#: IO die's APLIC its line is, the number after the boot flash's.
I2C_OFFSET = 0x0F_1000
I2C_SOURCE = BOOT_FLASH_SOURCE + 1
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
#: The chip select on the boot flash's bus that the shield
#: `socpuppet_host_spi_loopback` puts its devices at.
SPI_LOOPBACK_CHIP_SELECT = 1
#: The GPIO's pins that the shield `socpuppet_host_gpio_loopback` has a wire
#: between: the one a test drives, and the one it reads.
GPIO_LOOPBACK_OUT = 0
GPIO_LOOPBACK_IN = 1
#: The address on the I2C controller's bus at which the shield
#: `socpuppet_host_i2c_ram` puts a RAM: the one Zephyr's `i2c_ram` test
#: talks to.
I2C_RAM_ADDRESS = 0x51
#: The shield's wire, as `host(gpio_wires=...)` takes it.
GPIO_LOOPBACK_WIRES: Mapping[int, int] = MappingProxyType(
    {GPIO_LOOPBACK_OUT: GPIO_LOOPBACK_IN}
)


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
    #: What the SSD's accesses go through on their way to memory, if the
    #: host was described with one (`iommu=True`).
    iommu: Placed | None


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
    #: The GPIO on the IO die, with `GPIO_PINS` pins brought out. 🧵 Python
    #: is at the far end of them.
    gpio: PlacedGpio
    #: The I2C controller on the IO die. 🧵 Its devices are Python's.
    i2c: Placed
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
    iommu: bool = False,
    boot_flash_devices: Mapping[int, SpiDevice] = MappingProxyType({}),
    gpio_wires: Mapping[int, int] = MappingProxyType({}),
    i2c_devices: Mapping[int, I2cDevice] = MappingProxyType({}),
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
    iommu: bool = False,
    boot_flash_devices: Mapping[int, SpiDevice] = MappingProxyType({}),
    gpio_wires: Mapping[int, int] = MappingProxyType({}),
    i2c_devices: Mapping[int, I2cDevice] = MappingProxyType({}),
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
    iommu: bool = False,
    boot_flash_devices: Mapping[int, SpiDevice] = MappingProxyType({}),
    gpio_wires: Mapping[int, int] = MappingProxyType({}),
    i2c_devices: Mapping[int, I2cDevice] = MappingProxyType({}),
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
    waits for one to attach before it executes anything, whichever CPU it
    is: each has a GDB server of its own.

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
    `functools.partial(add_manager, script=scripted_manager().script)`
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

    With `iommu=True`, the drive's accesses go through an IOMMU on the IO
    die (`sp.Iommu`), which confines the drive to the memory firmware gave
    it. It needs a drive to put behind it, so `drive_blocks` too. Without
    it the drive reaches all of memory, as it always has.

    🧵 `boot_flash_devices` are on the boot flash's SPI bus beside its chip,
    by chip select, 1 to 3: Python's own devices (`socpuppet.spi`). And
    `gpio_wires` are wires between the GPIO's pins, from a pin to the pin
    it drives, 0 to 3 (`sp.Gpio`'s `wires`). And `i2c_devices` are on
    the I2C controller's bus, by address: Python's own (`socpuppet.i2c`).
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
    if iommu and drive_blocks is None:
        raise ValueError(
            "The host was given an IOMMU and no drive to put behind it. "
            "Give it a drive too: host(drive_blocks=4096, iommu=True)."
        )
    named_by = "SOCPUPPET_CPU" if cpu is None else "The host's cpu"
    chosen = cpu or os.environ.get("SOCPUPPET_CPU", DbtRiseCpu.implementation)
    if chosen not in HOST_CPUS:
        raise ValueError(
            f'{named_by} is "{chosen}", and the CPUs the host can have are '
            + " and ".join(f'"{name}"' for name in HOST_CPUS)
            + "."
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
    io = _io_die(
        platform,
        io_group,
        messages_to=messages_to,
        boot_flash_devices=boot_flash_devices,
        gpio_wires=gpio_wires,
        i2c_devices=i2c_devices,
    )
    slots = (
        None
        if virtio is None
        else add_virtio(
            platform,
            io_group,
            bus=io.bus,
            up=io.up,
            aplic=io.aplic,
            base=VIRTIO_SLOT_OFFSET,
            first_source=VIRTIO_FIRST_SOURCE,
            settings=virtio,
        )
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
        io.gpio,
        io.i2c,
        drive=(
            None
            if drive_blocks is None
            else _drive(
                platform,
                io_group,
                io,
                blocks=drive_blocks,
                add=drive or add_behavioral_drive,
                iommu=iommu,
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
        QboxCpu(xlen=64, reset_vector=reset_vector, gdb_port=gdb_port)
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
    gpio: PlacedGpio
    i2c: Placed
    #: The way to the flash's window. A socket takes one connection, and
    #: the flash has two readers when the die has a manager, so each comes
    #: in by an input of this.
    boot_flash_bus: PlacedRouter


def _io_die(
    platform: Platform,
    place: Group,
    *,
    messages_to: int,
    boot_flash_devices: Mapping[int, SpiDevice],
    gpio_wires: Mapping[int, int],
    i2c_devices: Mapping[int, I2cDevice],
) -> _IoDie:
    """Describe the die the devices are on, up to its end of the link."""
    bus = place.add("bus", Router())
    uart = place.add("uart", Ns16550())
    aplic = place.add("aplic", Aplic(messages_to=messages_to))
    up = place.add("up", Router())
    boot_flash = place.add(
        "boot_flash",
        SpiFlash(size=BOOT_FLASH_SIZE, devices=boot_flash_devices),
    )
    boot_flash_bus = place.add("boot_flash_bus", Router())
    gpio = place.add(
        "gpio", Gpio(pins=GPIO_PINS, wires=gpio_wires, leds=(GPIO_LED,))
    )
    bus.map(uart.socket, base=UART_OFFSET)
    bus.map(gpio.socket, base=GPIO_OFFSET)
    i2c = place.add("i2c", I2cController(devices=i2c_devices))
    bus.map(i2c.cpu, base=I2C_OFFSET)
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
    # A device's interrupt is a wire as far as the APLIC, on its own die,
    # and a message from there: it crosses the die-to-die link the other
    # way and comes onto the compute die's bus, where the IMSIC's page is.
    platform.connect(uart.irq, getattr(aplic, f"source{UART_SOURCE}"))
    platform.connect(
        boot_flash.irq, getattr(aplic, f"source{BOOT_FLASH_SOURCE}")
    )
    for pin in range(GPIO_PINS):
        platform.connect(
            getattr(gpio, f"irq{pin}"),
            getattr(aplic, f"source{GPIO_FIRST_SOURCE + pin}"),
        )
    platform.connect(i2c.irq, getattr(aplic, f"source{I2C_SOURCE}"))
    platform.connect(aplic.msi, up.target)
    return _IoDie(bus, uart, aplic, up, boot_flash, gpio, i2c, boot_flash_bus)


def _drive[Drive: PcieDrive](
    platform: Platform,
    place: Group,
    io: _IoDie,
    *,
    blocks: int,
    add: AddDrive[Drive],
    iommu: bool,
) -> HostDrive[Drive]:
    """Describe a PCIe root complex on the IO die, and the SSD on its link.

    With `iommu`, what the SSD sends up goes through an IOMMU.
    """
    root_complex = place.add("rc", PcieRootComplex())
    io.bus.map(root_complex.ecam, base=ECAM_OFFSET, size=ECAM_SIZE)
    io.bus.map(
        root_complex.mmio, base=PCIE_WINDOW_OFFSET, size=PCIE_WINDOW_SIZE
    )
    # What the drive sends up goes the way the APLIC's messages do: its
    # DMA to the RAM, and its interrupt messages to the IMSIC's page. With
    # an IOMMU, through it, messages too: it translates whatever the drive
    # sends.
    sends_up = root_complex.dma
    placed_iommu = None
    if iommu:
        placed_iommu = place.add("iommu", Iommu())
        io.bus.map(placed_iommu.socket, base=IOMMU_OFFSET)
        platform.connect(root_complex.dma, placed_iommu.target)
        platform.connect(
            placed_iommu.irq, getattr(io.aplic, f"source{IOMMU_SOURCE}")
        )
        sends_up = placed_iommu.initiator
    platform.connect(sends_up, io.up.add_input())
    ssd = add(
        platform, root_complex, blocks=blocks, group=platform.group("ssd")
    )
    return HostDrive(ssd, root_complex, placed_iommu)


def switched_off(board: Host[Any]) -> bool:
    """Whether the host's CPU has been switched off, by its system controller.

    OpenSBI's test payload asks to be, and so does a kernel's `poweroff`.
    """
    power_off = SYSCON_BASE + system_controller.POWER_OFF
    return board.platform.peek32(power_off, via=board.cpu.socket) == (
        system_controller.POWER_OFF_OFF
    )


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


def spi_loopback_overlay() -> str:
    """The devicetree that Zephyr's `spi_loopback` test wants of the host.

    It is the overlay of the Zephyr shield `socpuppet_host_spi_loopback`:
    the test's two devices, a slow one and a fast one, on the boot flash's
    SPI bus at chip select 1, where 🧵 Python's `socpuppet.spi.Loopback`
    answers each byte with itself. The fast one is as fast as the bus goes.

    The shield's copy is checked in, and a test holds it to this. To write
    the file again, print what this returns into it, with no newline added,
    as for `drive_overlay`.
    """
    flash = devicetree.label(host().boot_flash.path)
    fastest = SpiFlash.FASTEST_HZ
    cs = SPI_LOOPBACK_CHIP_SELECT
    return textwrap.dedent(
        f"""\
        &{flash} {{
        \tslow@{cs} {{
        \t\tcompatible = "test-spi-loopback-slow";
        \t\treg = <{cs}>;
        \t\tspi-max-frequency = <500000>;
        \t}};

        \tfast@{cs} {{
        \t\tcompatible = "test-spi-loopback-fast";
        \t\treg = <{cs}>;
        \t\tspi-max-frequency = <{fastest}>;
        \t}};
        }};
        """
    )


def gpio_loopback_overlay() -> str:
    """The devicetree that Zephyr's `gpio_basic_api` test wants of the host.

    It is the overlay of the Zephyr shield `socpuppet_host_gpio_loopback`:
    the test's two pins on the GPIO, the one it drives and the one it
    reads, which 🧵 a wire of Python's joins (`host(gpio_wires=...)`).

    The shield's copy is checked in, and a test holds it to this. To write
    the file again, print what this returns into it, with no newline added,
    as for `drive_overlay`.
    """
    gpio = devicetree.label(host().gpio.path)
    return textwrap.dedent(
        f"""\
        / {{
        \tresources {{
        \t\tcompatible = "test-gpio-basic-api";
        \t\tout-gpios = <&{gpio} {GPIO_LOOPBACK_OUT} 0>;
        \t\tin-gpios = <&{gpio} {GPIO_LOOPBACK_IN} 0>;
        \t}};
        }};
        """
    )


def i2c_ram_overlay() -> str:
    """The devicetree that Zephyr's `i2c_ram` test wants of the host.

    It is the overlay of the Zephyr shield `socpuppet_host_i2c_ram`: the
    alias by which the test finds the I2C controller whose bus 🧵 Python's
    RAM (`socpuppet.i2c.Ram`) is on, at `I2C_RAM_ADDRESS`, which the test
    knows already.

    The shield's copy is checked in, and a test holds it to this. To write
    the file again, print what this returns into it, with no newline added,
    as for `drive_overlay`.
    """
    i2c = devicetree.label(host().i2c.path)
    return textwrap.dedent(
        f"""\
        / {{
        \taliases {{
        \t\ti2c-ram = &{i2c};
        \t}};
        }};
        """
    )


def iommu_overlay(board: Host[Any] | None = None) -> str:
    """The devicetree that the host with an IOMMU has more than with a drive.

    It is the overlay of the Zephyr shield `socpuppet_host_iommu`, which
    goes on after `socpuppet_host_drive`'s: the IOMMU, and in the root
    complex's node which device IDs the IOMMU knows its devices by
    (`iommus`), which is what has Zephyr's driver for the IOMMU start
    before the one for the root complex.

    `board` is a host with a drive and an IOMMU, and by default the host
    with 🎭 the stand-in drive. The shield's copy is checked in, and a test
    holds it to this. To write the file again, print what this returns into
    it, with no newline added, as for `drive_overlay`.
    """
    if board is None:
        board = host(drive_blocks=1, iommu=True)
    drive = board.drive
    assert drive is not None
    assert drive.iommu is not None
    root_complex = drive.root_complex
    behind = "\n".join(
        f"\t{each}"
        for each in root_complex.component.iommu_properties(
            devicetree.label(drive.iommu.path), dialect="zephyr"
        )
    )
    return (
        board.platform.devicetree_overlay([drive.iommu], via=board.cpu.socket)
        + f"\n&{devicetree.label(root_complex.path)} {{\n{behind}\n}};\n"
    )


def virtio_overlay(board: Host[Any] | None = None) -> str:
    """The devicetree the host with its virtio slots has beyond the board.

    It is the overlay of the Zephyr shield `socpuppet_host_virtio`: a
    `virtio,mmio` node for each slot, with the child node Zephyr's driver
    for that kind of device binds to, and what `chosen` and `aliases`
    say of them.

    `board` is a host with its slots, and by default the host with them as
    they come. The shield's copy is checked in, and a test holds it to
    this. To write the file again, print what this returns into it, with
    no newline added, as for `drive_overlay`.
    """
    if board is None:
        board = host(virtio=Virtio())
    slots = board.virtio
    assert slots is not None
    return board.platform.devicetree_overlay(list(slots), via=board.cpu.socket)


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
