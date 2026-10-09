"""🧦 A host writes to an SSD that is built like one. Still no CPUs.

 the host                          the SSD
 host ─▶ bus ─┬─▶ ram              endpoint ─▶ frontend ◀─▶ firmware
  ▲      ▲    ├─▶ msi receiver        ▲           │            ▲
  │      │    └─▶ root complex ═══════╝           ▼            ▼
  │      └─────── root complex ◀══ endpoint ◀── uplink ◀── dma, flash ─▶ nand
  └── msi receiver

In nvme_hello.py the drive answered for itself. This one is taken apart
the way a real SSD is. Hardware keeps the queues and moves the data: an
NVMe frontend, a DMA engine, a flash controller, and a NAND chip to keep
it in. Firmware makes the decisions: what each command means, and where
on the NAND each of the drive's blocks really is.

Two things are still stand-ins. 🎭 The host's firmware is a Python
script, and 🎭 so is the SSD's: `sp.SsdFirmware`, which is short enough
to read in one sitting (python/socpuppet/ssd_firmware.py).

The host cannot tell any of this. It runs what nvme_hello.py's host ran.

Run it:                    python examples/ssd_hello.py
"""

from socpuppet.boards.ssd import (
    HOST_MSI_BASE,
    bring_up_the_drive,
    ssd,
    stand_in_firmware,
)

MESSAGE = b"Hello from the host, by way of PCIe and a page of NAND."

# What the host's script learns along the way, for printing at the end.
found = {}


def host():
    """What the host does. Each step hands over with `yield from`."""
    # 1. Find the drive on the PCIe bus, place it, and enable it. The
    #    host waits here until the SSD's firmware says it is ready.
    nvme = yield from bring_up_the_drive()
    found["namespace"] = yield from nvme.identify_namespace()

    # 2. Write a block near the end of the drive, then one at the start,
    #    and read the first back.
    block = MESSAGE.ljust(found["namespace"].block_size, b"\0")
    last = found["namespace"].blocks - 1
    yield from nvme.write_blocks(first=last, data=block)
    yield from nvme.write_blocks(first=0, data=block[::-1])
    found["read back"] = yield from nvme.read_blocks(first=last, count=1)


# Describe the platform: the SSD, with a scripted host on its PCIe link.
# Nothing is simulated yet. trace=True: watch what the drive sends up.
firmware = stand_in_firmware()
board = ssd(host=host, blocks=4096, firmware=firmware.script, trace=True)
platform = board.platform

if __name__ == "__main__":
    platform.build()
    platform.run()

    namespace = found["namespace"]
    megabytes = namespace.blocks * namespace.block_size / 1e6
    print(
        f"The SSD holds {namespace.blocks} blocks of "
        f"{namespace.block_size} bytes: {megabytes:.1f} MB."
    )
    # Everything the SSD did in the host's memory came up the link: the
    # commands its frontend fetched, the data its DMA engine moved, the
    # completions, and an interrupt message for each.
    from_the_drive = platform.trace
    messages = sum(record.address == HOST_MSI_BASE for record in from_the_drive)
    print(
        f"{len(from_the_drive)} accesses came up the link from the drive, "
        f"{messages} of them interrupt messages."
    )
    # The firmware's flash translation layer: where each page of the
    # drive that was written really is.
    for drive_page, nand_page in firmware.page_map.items():
        print(
            f"The firmware keeps page {drive_page} of the drive in NAND "
            f"page {nand_page}."
        )
    text = found["read back"].rstrip(b"\0").decode()
    print(f'\n✅ Wrote two blocks and read the first back: "{text}"')
