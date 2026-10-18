"""🎭 The host's virtio slots: stand-in devices every Linux has drivers for.

🎓 **Virtio** is the family of devices a virtual machine offers its guest
when it does not pretend to be real hardware: a block device, a network
card, a console and a few more, each a small register block
(`virtio-mmio`) and rings of descriptors in the guest's memory. No real
SoC has one. The host has them as stand-ins, in the sense socpuppet has
used since its first milestone: each holds a real block's place so that
the rest of the cast can rehearse, and tells a kernel that will not boot
from a device that does not work.

A board puts them where it likes, one to a slot, a page apart as QEMU's
`virt` machine has its own. The host puts them on its IO die
(`socpuppet.boards.host`), and only when asked (`host(virtio=Virtio())`),
so that its checked-in devicetree and every image built for it stay as
they were; the Zephyr images that use them get the shield
`socpuppet_host_virtio`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import NamedTuple

from socpuppet.components import (
    Virtio9p,
    VirtioBlk,
    VirtioConsole,
    VirtioFs,
    VirtioNet,
    VirtioRng,
)
from socpuppet.placed import (
    Placed,
    PlacedBlock,
    PlacedConsole,
    PlacedNet,
    PlacedRouter,
)
from socpuppet.platform import Group, Platform

#: How far apart the slots are: QEMU's `virt` has the same, a page each.
VIRTIO_SLOT_STRIDE = 0x1000


@dataclass(frozen=True)
class Virtio:
    """What the host's virtio devices are told when the host is described.

    `seed` is what the entropy device's bytes come from, so that a run can
    be repeated. `blocks` is how many 512-byte sectors the disk has: 1 MiB
    unless told otherwise. `mac` is the network device's address, as a
    48-bit number with its first byte highest (`VirtioNet`). `share` is a
    directory of this machine that the file system device and the 9P
    transport both serve, by `tag` (`VirtioFs`, `Virtio9p`): Zephyr mounts
    the one and Linux the other. With none, nothing serves it.
    """

    seed: int = 1
    blocks: int = 2048
    mac: int = VirtioNet.mac
    tag: str = VirtioFs.tag
    share: str | os.PathLike[str] | None = None


class VirtioSlots(NamedTuple):
    """The host's virtio devices, at their places."""

    #: 🎭 The entropy device, in slot 0.
    rng: Placed
    #: 🎭 The console, in slot 1.
    console: PlacedConsole
    #: 🎭 The disk, in slot 2.
    blk: PlacedBlock
    #: 🎭 The network device, in slot 3.
    net: PlacedNet
    #: 🎭 The file system device, in slot 4.
    fs: Placed
    #: 🎭 The 9P transport, in slot 5: the shared directory Linux mounts.
    ninep: Placed


def add_virtio(
    platform: Platform,
    place: Group,
    *,
    bus: PlacedRouter,
    up: PlacedRouter,
    aplic: Placed,
    base: int,
    first_source: int,
    settings: Virtio,
) -> VirtioSlots:
    """Describe the virtio devices, one to a slot, on a die.

    `bus` is the die's bus, where the slots start at `base`; `up` is the
    die's way up to the host's RAM, which each device's DMA takes; `aplic`
    is the die's interrupt controller, which each device's line goes to,
    the first as source `first_source` and the rest after it.
    """
    rng = place.add("rng", VirtioRng(seed=settings.seed))
    console = place.add("console", VirtioConsole())
    blk = place.add("blk", VirtioBlk(blocks=settings.blocks))
    net = place.add("net", VirtioNet(mac=settings.mac))
    fs = place.add("fs", VirtioFs(tag=settings.tag, directory=settings.share))
    ninep = place.add(
        "ninep", Virtio9p(tag=settings.tag, directory=settings.share)
    )
    for slot, device in enumerate([rng, console, blk, net, fs, ninep]):
        bus.map(device.cpu, base=base + slot * VIRTIO_SLOT_STRIDE)
        platform.connect(
            device.irq, getattr(aplic, f"source{first_source + slot}")
        )
        platform.connect(device.dma, up.add_input())
    return VirtioSlots(rng, console, blk, net, fs, ninep)


__all__ = ["VIRTIO_SLOT_STRIDE", "Virtio", "VirtioSlots", "add_virtio"]
