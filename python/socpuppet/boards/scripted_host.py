"""🎭 A scripted host with a PCIe link: what a drive needs in front of it.

    host ─▶ bus ─┬─▶ ram
     ▲      ▲    ├─▶ msi receiver ─▶ host
     │      │    └─▶ root complex ══ (the drive goes here)
     │      └─────── root complex    (the drive's DMA and interrupts)
     └── msi receiver

It is the least a host can be and still use an NVMe drive over PCIe: a
script in the CPU's place, some memory, a root complex, and one register
to take the drive's interrupt messages. Its devices are where the real
host board has them (`socpuppet.boards.host`), so a script written for one
finds its way around the other.

    def my_host():
        nvme = yield from bring_up_the_drive()
        yield from nvme.write_blocks(first=0, data=bytes(512))

    platform = sp.Platform()
    host = add_scripted_host(platform, my_host)
    add_behavioral_drive(platform, host.root_complex, blocks=2048)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import NamedTuple

from socpuppet.components import (
    Memory,
    MsiReceiver,
    PcieRootComplex,
    Router,
    Script,
    ScriptedBusMaster,
)
from socpuppet.msi_host import MsiHost
from socpuppet.nvme_host import NvmeHost
from socpuppet.ops import Operation, Steps
from socpuppet.pcie_host import PcieHost
from socpuppet.placed import Placed, PlacedRouter
from socpuppet.platform import Group, Platform

#: The host's memory: 1 MiB, which is room for an NVMe driver's queues and
#: a few hundred pages of data.
RAM_BASE = 0x8000_0000
RAM_SIZE = 1024 * 1024
#: The register that takes the drive's interrupt messages.
MSI_BASE = 0x0200_0000
#: The root complex's two windows: configuration space, and the memory
#: window a device's registers are placed in.
ECAM_BASE = 0x1010_0000
ECAM_SIZE = 1024 * 1024
PCIE_WINDOW_BASE = 0x1080_0000
PCIE_WINDOW_SIZE = 1024 * 1024


class ScriptedHost(NamedTuple):
    """The scripted host at its place in a platform, part by part."""

    #: The script, in the place of the host's CPU.
    cpu: Placed
    bus: PlacedRouter
    ram: Placed
    #: What turns the drive's interrupt messages into the script's wake-up.
    msi: Placed
    #: The host's end of the PCIe link: a drive is connected to this.
    root_complex: Placed


def add_scripted_host(
    platform: Platform,
    script: Script,
    *,
    group: Group | None = None,
    trace: bool = False,
) -> ScriptedHost:
    """Describe a scripted host with a PCIe link and nothing on it yet.

    `script` plays the host: it starts with `bring_up_the_drive()`. The
    host's parts go in `group`, or at the top of the platform if there is
    none. With `trace`, everything the drive sends up to the host is
    recorded in `platform.trace`: its DMA, and its interrupts, which are
    messages.
    """
    place = platform if group is None else group
    cpu = place.add("cpu", ScriptedBusMaster(script=script))
    bus = place.add("bus", Router())
    ram = place.add("ram", Memory(size=RAM_SIZE))
    msi = place.add("msi", MsiReceiver())
    root_complex = place.add("rc", PcieRootComplex())

    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(msi.socket, base=MSI_BASE)
    bus.map(root_complex.ecam, base=ECAM_BASE, size=ECAM_SIZE)
    bus.map(root_complex.mmio, base=PCIE_WINDOW_BASE, size=PCIE_WINDOW_SIZE)
    platform.connect(msi.irq, cpu.irq)
    # What the drive sends up (DMA, and interrupts as messages) comes onto
    # the host's bus.
    platform.connect(root_complex.dma, bus.add_input(), trace=trace)
    return ScriptedHost(
        cpu=cpu, bus=bus, ram=ram, msi=msi, root_complex=root_complex
    )


def idle_host() -> Iterator[Operation]:
    """A host script that does nothing: for when only the drive matters."""
    yield from ()


def bring_up_the_drive() -> Steps[NvmeHost]:
    """What the scripted host does before any I/O: find the drive, enable it.

    A piece of a host script, to hand over to with `yield from`. It scans
    the PCIe bus, gives the drive's registers a place, has its interrupts
    sent to the host's MSI receiver, and enables the controller. What
    comes back is the host's NVMe driver, 🎭 a stand-in too:
    `read_blocks`, `write_blocks` and `identify_namespace`.
    """
    pci = PcieHost(ecam=ECAM_BASE)
    (drive,) = yield from pci.scan()
    yield from pci.place(drive, PCIE_WINDOW_BASE)
    msi = MsiHost(receiver=MSI_BASE)
    yield from pci.route_interrupts(drive, to=msi)
    nvme = NvmeHost(
        registers=PCIE_WINDOW_BASE, memory=RAM_BASE, interrupt=msi.wait
    )
    yield from nvme.enable()
    return nvme
