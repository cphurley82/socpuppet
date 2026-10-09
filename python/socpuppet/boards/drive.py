"""🎭 A stand-in drive behind a PCIe endpoint.

    PCIe link ══ endpoint ─▶ nvme     (the endpoint's bar0 to the drive's)
                     ▲─────── nvme    (the drive's DMA and interrupt lines)

The drive is the behavioral NVMe, which answers the host itself. The
endpoint puts PCIe around it, so that a host finds it the way it finds a
real drive: by scanning its bus.
"""

from __future__ import annotations

from typing import NamedTuple

from socpuppet.components import BehavioralNvme, PcieEndpoint
from socpuppet.placed import Placed
from socpuppet.platform import Group, Platform

#: Who the drive says made it, and which device it is. The vendor is "SP"
#: in ASCII, which no real vendor has.
VENDOR_ID = 0x5350
DEVICE_ID = 0xC0DE
#: What kind of device it is, as class, subclass and programming
#: interface: mass storage, non-volatile memory, NVMe.
NVME_CLASS = 0x01_08_02
#: How many interrupt vectors the drive has: one for the admin queue, and
#: one for an I/O queue.
VECTORS = 2


class BehavioralDrive(NamedTuple):
    """The drive at its place in a platform, and its PCIe endpoint."""

    nvme: Placed
    endpoint: Placed


def add_behavioral_drive(
    platform: Platform,
    root_complex: Placed,
    *,
    blocks: int,
    group: Group | None = None,
) -> BehavioralDrive:
    """Describe a stand-in drive on the PCIe link of `root_complex`.

    `blocks` is how many 512-byte blocks it holds. Its two components go in
    `group`, or at the top of the platform if there is none.
    """
    place = platform if group is None else group
    nvme = place.add("nvme", BehavioralNvme(blocks=blocks, vectors=VECTORS))
    endpoint = place.add(
        "endpoint",
        PcieEndpoint(
            vendor_id=VENDOR_ID,
            device_id=DEVICE_ID,
            class_code=NVME_CLASS,
            function_size=BehavioralNvme.mapped_size,
            vectors=VECTORS,
        ),
    )
    # The PCIe link, one direction each.
    platform.connect(root_complex.to_device, endpoint.from_host)
    platform.connect(endpoint.to_host, root_complex.from_device)
    # The function behind the endpoint: its registers, its DMA and one
    # interrupt line per vector.
    platform.connect(endpoint.bar0, nvme.bar0)
    platform.connect(nvme.dma, endpoint.dma)
    for vector in range(VECTORS):
        platform.connect(
            getattr(nvme, f"irq{vector}"), getattr(endpoint, f"irq{vector}")
        )
    return BehavioralDrive(nvme, endpoint)
