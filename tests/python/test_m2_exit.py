"""The M2 exit test: a Python host finds an NVMe drive over PCIe and uses it.

There are no CPUs. The host's firmware is a Python script, and the drive
answers for itself.

 compute die                            IO die                 the SSD
 host ─▶ bus ─┬─▶ ram                   bus ─┬─▶ root complex ══ endpoint
  ▲      ▲    ├─▶ msi receiver ─▶ host       └─▶ (both windows)     │
  │      │    └─▶ link ═════════▶ bus                               ▼
  │      └─────── link ◀═════════ root complex               behavioral NVMe
  └── msi receiver                (the drive's DMA and interrupts)
"""

import pytest

import socpuppet as sp

RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
MSI_BASE = 0x2000_0000
# Everything on the IO die is inside this window of the compute die's map.
IO_BASE = 0x3000_0000
IO_SIZE = 0x1000_0000
# Where the root complex's two windows are on the IO die, counted from the
# start of the IO window.
ECAM_OFFSET = 0x0000_0000
ECAM_SIZE = 0x10_0000
WINDOW_OFFSET = 0x0800_0000
WINDOW_SIZE = 0x10_0000
BLOCKS = 256


def host_and_ssd(script):
    """The host, split over two dies, and an SSD on its PCIe link, built."""
    platform = sp.Platform()
    compute = platform.group("compute")
    io = platform.group("io")
    ssd = platform.group("ssd")

    host = compute.add("host", sp.ScriptedBusMaster(script))
    compute_bus = compute.add("bus", sp.Router())
    ram = compute.add("ram", sp.Memory(size=RAM_SIZE))
    msi = compute.add("msi", sp.MsiReceiver())
    d2d = platform.link("d2d", sp.PassThroughLink(), compute, io)
    io_bus = io.add("bus", sp.Router())
    rc = io.add("rc", sp.PcieRootComplex())
    nvme = ssd.add("nvme", sp.BehavioralNvme(blocks=BLOCKS))
    endpoint = ssd.add(
        "endpoint",
        sp.PcieEndpoint(
            vendor_id=0x5350,
            device_id=0xC0DE,
            class_code=0x01_08_02,
            function_size=sp.BehavioralNvme.mapped_size,
            vectors=2,
        ),
    )

    # The host's view: its own memory, the MSI receiver, and the IO die
    # through the link.
    platform.connect(host.socket, compute_bus.target)
    compute_bus.map(ram.socket, base=RAM_BASE)
    compute_bus.map(msi.socket, base=MSI_BASE)
    compute_bus.map(d2d.a.target, base=IO_BASE, size=IO_SIZE)
    platform.connect(msi.irq, host.irq)
    # On the IO die: the root complex's two windows.
    platform.connect(d2d.b.initiator, io_bus.target)
    io_bus.map(rc.ecam, base=ECAM_OFFSET, size=ECAM_SIZE)
    io_bus.map(rc.mmio, base=WINDOW_OFFSET, size=WINDOW_SIZE)
    # What the drive sends up (DMA, interrupt messages) crosses the link
    # the other way and comes onto the compute die's bus.
    platform.connect(rc.dma, d2d.b.target)
    platform.connect(d2d.a.initiator, compute_bus.add_input(), trace=True)
    # The PCIe link, and the function behind the endpoint.
    platform.connect(rc.to_device, endpoint.from_host)
    platform.connect(endpoint.to_host, rc.from_device)
    platform.connect(endpoint.bar0, nvme.bar0)
    platform.connect(nvme.dma, endpoint.dma)
    platform.connect(nvme.irq0, endpoint.irq0)
    platform.connect(nvme.irq1, endpoint.irq1)
    platform.build()
    return platform


def bring_up_the_drive():
    """What the host does before any I/O: find the drive, and enable it."""
    pci = sp.PcieHost(ecam=IO_BASE + ECAM_OFFSET)
    (drive,) = yield from pci.scan()
    registers = IO_BASE + WINDOW_OFFSET
    yield from pci.place(drive, registers)
    msi = sp.MsiHost(receiver=MSI_BASE)
    yield from pci.route_interrupts(drive, to=msi)
    nvme = sp.NvmeHost(registers=registers, memory=RAM_BASE, interrupt=msi.wait)
    yield from nvme.enable()
    return nvme


@pytest.mark.platform
class TestWhenAPythonHostBringsUpAnNvmeDriveOverPcie:
    def test_the_drive_says_how_big_it_is(self):
        learned = []

        def script():
            nvme = yield from bring_up_the_drive()
            learned.append((yield from nvme.identify_namespace()))

        platform = host_and_ssd(script)

        platform.run()

        assert learned == [sp.NvmeNamespace(blocks=BLOCKS, block_size=512)]

    def test_blocks_read_back_as_they_were_written(self):
        # Three pages of memory, so the drive has to follow a list of them.
        written = bytes(index * 7 % 251 for index in range(24 * 512))
        read_back = []

        def script():
            nvme = yield from bring_up_the_drive()
            yield from nvme.write_blocks(first=8, data=written)
            read_back.append((yield from nvme.read_blocks(first=8, count=24)))

        platform = host_and_ssd(script)

        platform.run()

        assert read_back == [written]

    def test_every_interrupt_arrives_as_a_message_across_the_link(self):
        def script():
            nvme = yield from bring_up_the_drive()
            yield from nvme.identify_namespace()

        platform = host_and_ssd(script)

        platform.run()

        # Everything the drive sends to the host crosses the traced
        # connection. A command ends with a 16-byte completion written into
        # the host's memory, and each must come with one message: a write
        # of the admin vector's number, 0, to the MSI receiver.
        writes = [
            record for record in platform.trace if record.command == "write"
        ]
        completions = [
            record
            for record in writes
            if len(record.data) == 16 and record.address >= RAM_BASE
        ]
        messages = [
            record.data for record in writes if record.address == MSI_BASE
        ]
        assert completions
        assert messages == [bytes(4)] * len(completions)
