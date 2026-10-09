"""An SSD with no PCIe around it, for tests of its firmware.

The drive's registers are mapped straight onto the host's bus, and its
first interrupt line goes straight to the host. What is behind the
registers is the whole SSD.

    host ─▶ bus ─┬─▶ ram
     ▲      ▲    └─▶ ssd.frontend.bar0 ...
     │      └──────── ssd.uplink
     └─────────────── ssd.frontend.irq0
"""

import socpuppet as sp
from socpuppet.boards.ssd import UPLINK_REACH, add_ssd_function

RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
NVME_BASE = 0x1000_0000
# One NAND block of 64 pages of 4 KiB.
BLOCKS = 512


def host_with_an_ssd(script, *, firmware, blocks=BLOCKS):
    """A scripted host with a RAM and an SSD of `blocks` blocks, built.

    `firmware` is the stand-in for the SSD's firmware, or None for an SSD
    with a CPU, into which firmware is still to be loaded. Returns the
    platform and the SSD.
    """
    platform = sp.Platform()
    host = platform.add("host", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=RAM_SIZE))
    ssd = add_ssd_function(
        platform,
        blocks=blocks,
        group=platform.group("ssd"),
        firmware=None if firmware is None else firmware.script,
    )
    platform.connect(host.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(ssd.frontend.bar0, base=NVME_BASE)
    ssd.uplink.map(bus.add_input(), base=0, size=UPLINK_REACH)
    platform.connect(ssd.frontend.irq0, host.irq)
    platform.build()
    return platform, ssd
