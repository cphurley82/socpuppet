"""🐧 This machine as the host: its own Linux, and its own NVMe driver.

    this machine's Linux ══ pciem ══ host ─▶ the drive's registers
                                      ▲───── the drive's DMA and lines

A drive's host is usually played in the simulation, by a CPU or a script
behind a root complex and a PCIe link. Here it is the machine the
simulation runs on: `sp.PciemHost` puts the drive on this machine's own
PCIe bus, through pciem, and Linux finds it there and binds its `nvme`
driver to it, as it would a card in a slot. Then `lsblk` lists it, and
`mkfs.ext4` and `mount` use it.

    board = ssd(host=this_machine)
    board.platform.build()
    board.host.start()

Only a build of socpuppet with pciem has the host, on a machine whose
Linux has pciem loaded (docs/setup.md, and `tools/doctor.py pciem`).
"""

from __future__ import annotations

from typing import NamedTuple

from socpuppet.boards.drive import (
    DEVICE_ID,
    NVME_CLASS,
    VECTORS,
    VENDOR_ID,
    connect_the_function,
)
from socpuppet.components import BehavioralNvme, PciemHost
from socpuppet.placed import Placed
from socpuppet.platform import Group, Platform

#: A class code no driver of Linux's claims, for a drive that is to be
#: found on the bus and left alone: 0xFF is "a device that fits no class".
UNCLAIMED_CLASS = 0xFF_00_00


class RealHost(NamedTuple):
    """This machine as a drive's host, and what the drive says it is there.

    `class_code` is what kind of device the drive says it is: an NVMe
    drive, which Linux's `nvme` driver binds, or `UNCLAIMED_CLASS`, which
    no driver does.
    """

    class_code: int = NVME_CLASS


#: This machine as the host of an NVMe drive.
this_machine = RealHost()


def add_real_host(
    platform: Platform,
    real_host: RealHost,
    *,
    function_size: int,
    group: Group | None = None,
) -> Placed:
    """Describe this machine as the host of a drive's function.

    The drive says the puppet's own IDs, as it does behind a PCIe
    endpoint. `function_size` is how many bytes its registers take. What
    is left to connect is the function: `host.bar0` to its registers, its
    DMA to `host.dma`, and its lines to `host.irq0` and so on.
    """
    place = platform if group is None else group
    return place.add(
        "host",
        PciemHost(
            vendor_id=VENDOR_ID,
            device_id=DEVICE_ID,
            class_code=real_host.class_code,
            function_size=function_size,
            vectors=VECTORS,
        ),
    )


class BehavioralDriveBoard(NamedTuple):
    """🎭 The stand-in drive with this machine as its host."""

    platform: Platform
    nvme: Placed
    host: Placed


def behavioral_drive(
    *, blocks: int, host: RealHost = this_machine
) -> BehavioralDriveBoard:
    """Describe the 🎭 stand-in drive, with this machine as its host.

    `blocks` is how many 512-byte blocks it holds. With no CPU behind it,
    it is ready as soon as the host enables it.
    """
    platform = Platform()
    nvme = platform.add("nvme", BehavioralNvme(blocks=blocks, vectors=VECTORS))
    real_host = add_real_host(
        platform, host, function_size=BehavioralNvme.mapped_size
    )
    connect_the_function(platform, nvme, real_host)
    return BehavioralDriveBoard(platform, nvme, real_host)
