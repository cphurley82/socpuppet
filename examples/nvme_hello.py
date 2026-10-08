"""🧦 A host finds an NVMe drive over PCIe and writes to it. No CPUs.

 compute die                            IO die                 the SSD
 host ─▶ bus ─┬─▶ ram                   bus ─┬─▶ root complex ══ endpoint
  ▲      ▲    ├─▶ msi receiver ─▶ host       └─▶ (both windows)     │
  │      │    └─▶ link ═════════▶ bus                               ▼
  │      └─────── link ◀═════════ root complex               behavioral NVMe
  └── msi receiver                (the drive's DMA and interrupts)

Four things here are stand-ins. 🎭 The host's firmware is a Python script.
🎭 The drive answers for itself, with no firmware of its own. 🎭 The link
between the host's two dies passes everything straight through. 🎭 What
takes the drive's interrupt messages is one register, where a real host
has an interrupt controller. The PCIe in between is real enough for a
driver: the script has to find the drive,
give its registers a place in memory and say where its interrupts go
before it can read a single block.

Run it:                    python examples/nvme_hello.py
"""

import socpuppet as sp
from socpuppet.boards.ssd import add_ssd

RAM_BASE = 0x8000_0000
MSI_BASE = 0x2000_0000
# Everything on the IO die is inside this window of the compute die's map.
IO_BASE = 0x3000_0000
IO_SIZE = 0x1000_0000
# The root complex's two windows, counted from the start of the IO window.
ECAM_OFFSET = 0x0000_0000
WINDOW_OFFSET = 0x0800_0000

MESSAGE = b"Hello from the host, by way of PCIe."

# What the script learns along the way, for printing at the end.
found = {}


def script():
    """What the host does. Each step hands over with `yield from`."""
    # 1. Find the drive. Nothing tells a host what is on its PCIe bus.
    pci = sp.PcieHost(ecam=IO_BASE + ECAM_OFFSET)
    (drive,) = yield from pci.scan()
    found["drive"] = drive

    # 2. Give its registers a place in memory, and say where its
    #    interrupts are to be sent.
    msi = sp.MsiHost(receiver=MSI_BASE)
    registers = IO_BASE + WINDOW_OFFSET
    yield from pci.place(drive, registers)
    yield from pci.route_interrupts(drive, to=msi)

    # 3. Only now can an NVMe driver talk to it.
    nvme = sp.NvmeHost(registers=registers, memory=RAM_BASE, interrupt=msi.wait)
    yield from nvme.enable()
    found["namespace"] = yield from nvme.identify_namespace()

    # 4. Write a block, and read it back.
    block = MESSAGE.ljust(found["namespace"].block_size, b"\0")
    yield from nvme.write_blocks(first=7, data=block)
    found["read back"] = yield from nvme.read_blocks(first=7, count=1)


# Describe the platform. Nothing is simulated yet.
platform = sp.Platform()
compute = platform.group("compute")
io = platform.group("io")
ssd = platform.group("ssd")

host = compute.add("host", sp.ScriptedBusMaster(script))
compute_bus = compute.add("bus", sp.Router())
ram = compute.add("ram", sp.Memory(size=1024 * 1024))
msi_receiver = compute.add("msi", sp.MsiReceiver())
d2d = platform.link("d2d", sp.PassThroughLink(), compute, io)
io_bus = io.add("bus", sp.Router())
rc = io.add("rc", sp.PcieRootComplex())
# The SSD: 🎭 a stand-in NVMe drive, and the PCIe endpoint that fronts for
# it, connected to the root complex (see socpuppet/boards/ssd.py).
add_ssd(platform, rc, blocks=2048, group=ssd)

# The host's view: its own memory, the MSI receiver, and the IO die
# through the link.
platform.connect(host.socket, compute_bus.target)
compute_bus.map(ram.socket, base=RAM_BASE)
compute_bus.map(msi_receiver.socket, base=MSI_BASE)
compute_bus.map(d2d.a.target, base=IO_BASE, size=IO_SIZE)
platform.connect(msi_receiver.irq, host.irq)
# On the IO die: the root complex's two windows.
platform.connect(d2d.b.initiator, io_bus.target)
io_bus.map(rc.ecam, base=ECAM_OFFSET, size=0x10_0000)
io_bus.map(rc.mmio, base=WINDOW_OFFSET, size=0x10_0000)
# What the drive sends up (DMA and interrupt messages) crosses the link
# the other way and comes onto the compute die's bus. trace=True: watch it.
platform.connect(rc.dma, d2d.b.target)
platform.connect(d2d.a.initiator, compute_bus.add_input(), trace=True)

if __name__ == "__main__":
    platform.build()
    platform.run()

    drive, namespace = found["drive"], found["namespace"]
    megabytes = namespace.blocks * namespace.block_size / 1e6
    print(
        f"Found a device at {drive}: vendor {drive.vendor_id:#06x}, device "
        f"{drive.device_id:#06x}, class {drive.class_code:#08x}, "
        "which is an NVMe drive."
    )
    print(
        f"It holds {namespace.blocks} blocks of {namespace.block_size} "
        f"bytes: {megabytes:.1f} MB."
    )
    # Everything the drive did on its own initiative crossed the link.
    from_the_drive = platform.trace
    messages = sum(record.address == MSI_BASE for record in from_the_drive)
    print(
        f"{len(from_the_drive)} accesses came up the link from the drive, "
        f"{messages} of them interrupt messages."
    )
    text = found["read back"].rstrip(b"\0").decode()
    print(f'\n✅ Wrote a block and read it back: "{text}"')
