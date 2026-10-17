"""🎭 The host's virtio slots: stand-in devices every Linux has drivers for.

🎓 **Virtio** is the family of devices a virtual machine offers its guest
when it does not pretend to be real hardware: a block device, a network
card, a console and a few more, each a small register block
(`virtio-mmio`) and rings of descriptors in the guest's memory. No real
SoC has one. The host has them as stand-ins, in the sense socpuppet has
used since its first milestone: each holds a real block's place so that
the rest of the cast can rehearse, and tells a kernel that will not boot
from a device that does not work.

The slots are where QEMU's `virt` machine has its own, `0x1000_1000` and
every 4 KiB after, which is inside the IO die's window: so each device is
on the IO die, and its interrupt line is a source of the IO die's APLIC,
from 18 on, after the UART's. They are not on the host unless asked for
(`host(virtio=Virtio())`), so the board's checked-in devicetree and every
image built for it stay as they were; the Zephyr images that use them get
the shield `socpuppet_host_virtio`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple

from socpuppet.components import VirtioRng
from socpuppet.placed import Placed, PlacedRouter
from socpuppet.platform import Group, Platform

if TYPE_CHECKING:
    from socpuppet.boards.host import Host

#: Where the first slot is, counted from the start of the IO die's window,
#: and how far apart the slots are: QEMU's `virt` has the same.
VIRTIO_SLOT_OFFSET = 0x1000
VIRTIO_SLOT_STRIDE = 0x1000
#: Which source of the IO die's APLIC the first slot's line is: the number
#: after the UART's. The compute die's APLIC has 17 for the watchdog, and
#: no number is a source at both.
VIRTIO_FIRST_SOURCE = 18


@dataclass(frozen=True)
class Virtio:
    """What the host's virtio devices are told when the host is described.

    `seed` is what the entropy device's bytes come from, so that a run can
    be repeated.
    """

    seed: int = 1


class VirtioSlots(NamedTuple):
    """The host's virtio devices, at their places."""

    #: 🎭 The entropy device, in slot 0.
    rng: Placed


def add_virtio(
    platform: Platform,
    place: Group,
    bus: PlacedRouter,
    up: PlacedRouter,
    aplic: Placed,
    settings: Virtio,
) -> VirtioSlots:
    """Describe the virtio devices on the IO die, one to a slot.

    `bus` is the die's bus, where the slots are; `up` is the die's way up
    the link, which each device's DMA takes to the host's RAM; `aplic` is
    the die's interrupt controller, which each device's line goes to.
    """
    rng = place.add("rng", VirtioRng(seed=settings.seed))
    for slot, device in enumerate([rng]):
        bus.map(device.cpu, base=VIRTIO_SLOT_OFFSET + slot * VIRTIO_SLOT_STRIDE)
        platform.connect(
            device.irq, getattr(aplic, f"source{VIRTIO_FIRST_SOURCE + slot}")
        )
        platform.connect(device.dma, up.add_input())
    return VirtioSlots(rng)


def virtio_overlay(board: Host[Any] | None = None) -> str:
    """The devicetree the host with its virtio slots has beyond the board.

    It is the overlay of the Zephyr shield `socpuppet_host_virtio`: a
    `virtio,mmio` node for each slot, with the child node Zephyr's driver
    for that kind of device binds to, and what `chosen` says of them.

    `board` is a host with its slots, and by default the host with them as
    they come. The shield's copy is checked in, and a test holds it to
    this. To write the file again, print what this returns into
    `boards/shields/socpuppet_host_virtio/socpuppet_host_virtio.overlay`
    in the Zephyr module, with no newline added, as `drive_overlay`'s
    docstring has it.
    """
    if board is None:
        from socpuppet.boards.host import host

        board = host(virtio=Virtio())
    slots = board.virtio
    assert slots is not None
    return board.platform.devicetree_overlay(list(slots), via=board.cpu.socket)


__all__ = [
    "VIRTIO_FIRST_SOURCE",
    "VIRTIO_SLOT_OFFSET",
    "VIRTIO_SLOT_STRIDE",
    "Virtio",
    "VirtioSlots",
    "add_virtio",
    "virtio_overlay",
]
