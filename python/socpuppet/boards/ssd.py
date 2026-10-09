"""The SSD: an NVMe drive with a controller of its own.

    link ══ endpoint ─▶ frontend ◀─ registers ─ cpu ─ registers ─▶ dma, flash
               ▲           │                                     │      │
               └──────── uplink ◀────────────────────────────────┘      ▼
                                  dma, flash ─▶ bus ─▶ buffer         nand

The host sees an NVMe drive behind a PCIe endpoint, as it does with the
🎭 stand-in drive (`socpuppet.boards.drive`). Behind the endpoint this
one is built the way a real one is:

- the **NVMe frontend** keeps the queues, fetches the host's commands and
  posts their completions,
- the **CPU** runs the firmware, which decides what each command means,
- the **DMA engine** copies a command's data between the host's memory
  and the SSD's buffer,
- the **flash controller** moves pages between the buffer and the
  **NAND**, which is where the data is kept.

🎭 Until the SSD has a CPU model of its own, a script stands in for the
firmware (`sp.SsdFirmware`), in the CPU's place.

To use an SSD from a Python host, with nothing else to build:

    from socpuppet.boards.scripted_host import bring_up_the_drive

    def my_host():
        nvme = yield from bring_up_the_drive()
        yield from nvme.write_blocks(first=0, data=bytes(512))

    board = ssd(host=my_host, firmware=stand_in_firmware().script)
    board.platform.build()
    board.platform.run()
"""

from __future__ import annotations

from typing import NamedTuple

from socpuppet.boards.drive import DEVICE_ID, NVME_CLASS, VECTORS, VENDOR_ID
from socpuppet.boards.scripted_host import ScriptedHost, add_scripted_host
from socpuppet.components import (
    DmaEngine,
    FlashController,
    IdealNand,
    Memory,
    NvmeFrontend,
    PcieEndpoint,
    Router,
    Script,
    ScriptedBusMaster,
)
from socpuppet.placed import Placed, PlacedRouter
from socpuppet.platform import Group, Platform
from socpuppet.ssd_firmware import SsdFirmware

# ---- The SSD's own address map: what its CPU sees. The host sees none of
# it, only the endpoint.
#: The registers of the NVMe frontend, the DMA engine and the flash
#: controller.
FRONTEND_BASE = 0x1001_0000
DMA_BASE = 0x1002_0000
FLASH_BASE = 0x1003_0000
#: The buffer: 4 MiB of memory that data passes through on its way
#: between the host and the NAND.
BUFFER_BASE = 0x4000_0000
BUFFER_SIZE = 4 * 1024 * 1024

# ---- The NAND. A page is 4 KiB, which is eight of the drive's 512-byte
# blocks, and 64 pages make a NAND block.
NAND_PAGE_SIZE = 4096
NAND_PAGES_PER_BLOCK = 64
#: How many of the drive's blocks one NAND block holds. A drive is a whole
#: number of NAND blocks.
DRIVE_BLOCKS_PER_NAND_BLOCK = NAND_PAGES_PER_BLOCK * NAND_PAGE_SIZE // 512

#: How much of the host's address space the SSD can reach for its DMA,
#: from address 0 up: the lower half of what 64 bits can say, which is more
#: than any host has. It is how big a range to map onto an SSD's `uplink`.
UPLINK_REACH = 1 << 63


class Ssd(NamedTuple):
    """An SSD at its place in a platform, part by part."""

    #: The SSD's CPU, or what stands in for it.
    cpu: Placed
    #: The bus the CPU reaches the three devices and the buffer through.
    bus: PlacedRouter
    frontend: Placed
    dma: Placed
    flash: Placed
    nand: Placed
    buffer: Placed
    #: The one way up to the host's memory, which the frontend and the DMA
    #: engine share.
    uplink: PlacedRouter
    #: Its PCIe endpoint, if it has one (see `add_ssd_function`).
    endpoint: Placed | None = None


def stand_in_firmware() -> SsdFirmware:
    """🎭 The firmware stand-in, told where this board's devices are.

    Its `script` goes in the SSD's CPU slot:
    `add_ssd(..., firmware=stand_in_firmware().script)`.
    """
    return SsdFirmware(
        frontend=FRONTEND_BASE,
        dma=DMA_BASE,
        flash=FLASH_BASE,
        buffer=BUFFER_BASE,
    )


def add_ssd_function(
    platform: Platform,
    *,
    blocks: int,
    group: Group | None = None,
    firmware: Script | None = None,
) -> Ssd:
    """Describe an SSD with no PCIe around it: an NVMe function.

    That is everything behind the endpoint, for a host that reaches a
    drive's registers straight from its bus. What is left to connect is
    what an endpoint would be connected to: `frontend.bar0` (the drive's
    registers), `uplink` (map the host's bus onto it, from address 0 and
    `UPLINK_REACH` long), and the frontend's interrupt lines,
    `frontend.irq0` and so on.

    `blocks` is how many 512-byte blocks the drive holds, which has to be
    a whole number of NAND blocks. `firmware` is the script that stands
    in for the SSD's firmware (see `stand_in_firmware`). The SSD's parts
    go in `group`, or at the top of the platform if there is none.
    """
    if blocks < DRIVE_BLOCKS_PER_NAND_BLOCK or (
        blocks % DRIVE_BLOCKS_PER_NAND_BLOCK
    ):
        raise ValueError(
            f"An SSD holds a whole number of NAND blocks, and at least one. "
            f"A NAND block is {DRIVE_BLOCKS_PER_NAND_BLOCK} of the drive's "
            f"512-byte blocks, and {blocks} blocks were asked for. Ask for "
            f"{DRIVE_BLOCKS_PER_NAND_BLOCK}, or a multiple of it."
        )
    place = platform if group is None else group
    bus = place.add("bus", Router())
    frontend = place.add("frontend", NvmeFrontend(vectors=VECTORS))
    dma = place.add("dma", DmaEngine())
    flash = place.add("flash", FlashController())
    nand = place.add(
        "nand",
        IdealNand(
            blocks=blocks // DRIVE_BLOCKS_PER_NAND_BLOCK,
            pages_per_block=NAND_PAGES_PER_BLOCK,
            page_size=NAND_PAGE_SIZE,
        ),
    )
    buffer = place.add("buffer", Memory(size=BUFFER_SIZE))
    uplink = place.add("uplink", Router())

    # Whatever is in the CPU's place, with the frontend's line to tell it
    # when there is work.
    cpu = _add_scripted_cpu(platform, place, frontend, firmware)
    # What the CPU sees: the three devices' registers, and the buffer.
    platform.connect(cpu.socket, bus.target)
    bus.map(frontend.cpu, base=FRONTEND_BASE)
    bus.map(dma.cpu, base=DMA_BASE)
    bus.map(flash.cpu, base=FLASH_BASE)
    bus.map(buffer.socket, base=BUFFER_BASE)
    # The two devices that move data reach the buffer over the same bus,
    # and the flash controller has the NAND behind it.
    platform.connect(dma.local, bus.add_input())
    platform.connect(flash.local, bus.add_input())
    platform.connect(flash.nand, nand.socket)
    # The way up to the host's memory, for the frontend's commands and
    # completions and for the DMA engine's data.
    platform.connect(frontend.dma, uplink.target)
    platform.connect(dma.host, uplink.add_input())
    return Ssd(
        cpu=cpu,
        bus=bus,
        frontend=frontend,
        dma=dma,
        flash=flash,
        nand=nand,
        buffer=buffer,
        uplink=uplink,
    )


def _add_scripted_cpu(
    platform: Platform,
    place: Platform | Group,
    frontend: Placed,
    firmware: Script | None,
) -> Placed:
    """🎭 Put a script in the SSD's CPU slot, to stand in for its firmware.

    The frontend's line goes straight to the script, which has one
    interrupt input and no interrupt controller.
    """
    if firmware is None:
        raise NotImplementedError(
            "🚧 The SSD has no CPU of its own yet, so it needs a script to "
            "stand in for its firmware: "
            "firmware=socpuppet.boards.ssd.stand_in_firmware().script."
        )
    cpu = place.add("cpu", ScriptedBusMaster(script=firmware))
    platform.connect(frontend.cpu_irq, cpu.irq)
    return cpu


def add_ssd(
    platform: Platform,
    root_complex: Placed,
    *,
    blocks: int,
    group: Group | None = None,
    firmware: Script | None = None,
) -> Ssd:
    """Describe an SSD on the PCIe link of `root_complex`.

    It is `add_ssd_function` with a PCIe endpoint around it, so that a
    host finds the drive the way it finds a real one: by scanning its
    bus. The endpoint says the same of itself as the 🎭 stand-in drive's
    does, so a host cannot tell the two apart by looking.
    """
    ssd = add_ssd_function(
        platform, blocks=blocks, group=group, firmware=firmware
    )
    place = platform if group is None else group
    endpoint = place.add(
        "endpoint",
        PcieEndpoint(
            vendor_id=VENDOR_ID,
            device_id=DEVICE_ID,
            class_code=NVME_CLASS,
            function_size=NvmeFrontend.BAR0_SIZE,
            vectors=VECTORS,
        ),
    )
    # The PCIe link, one direction each.
    platform.connect(root_complex.to_device, endpoint.from_host)
    platform.connect(endpoint.to_host, root_complex.from_device)
    # The function behind the endpoint: its registers, its way to the
    # host's memory, and one interrupt line per vector.
    platform.connect(endpoint.bar0, ssd.frontend.bar0)
    ssd.uplink.map(endpoint.dma, base=0, size=UPLINK_REACH)
    for vector in range(VECTORS):
        platform.connect(
            getattr(ssd.frontend, f"irq{vector}"),
            getattr(endpoint, f"irq{vector}"),
        )
    return ssd._replace(endpoint=endpoint)


class SsdBoard(NamedTuple):
    """The SSD with a 🎭 scripted host in front of it, and their parts."""

    platform: Platform
    ssd: Ssd
    host: ScriptedHost


def ssd(
    *,
    host: Script,
    blocks: int = 4096,
    firmware: Script | None = None,
    trace: bool = False,
) -> SsdBoard:
    """Describe the SSD, with a 🎭 scripted host on its PCIe link.

    Nothing is simulated until `platform.build()`. `host` is the script
    that plays the host: it starts with `bring_up_the_drive()` (see
    `socpuppet.boards.scripted_host`). `blocks` is how many 512-byte
    blocks the drive holds, and `firmware` is the script that stands in
    for the SSD's firmware. With `trace`, everything the drive sends up to
    the host is recorded in `platform.trace`.
    """
    platform = Platform()
    scripted_host = add_scripted_host(
        platform, host, group=platform.group("host"), trace=trace
    )
    drive = add_ssd(
        platform,
        scripted_host.root_complex,
        blocks=blocks,
        group=platform.group("ssd"),
        firmware=firmware,
    )
    return SsdBoard(platform, drive, scripted_host)
