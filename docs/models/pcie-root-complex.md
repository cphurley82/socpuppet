# PCIe root complex

`sp.PcieRootComplex()` · C++ `socpuppet::PcieRootComplex` · registry name `pcie_root_complex`

## What it stands for

The host's end of PCI Express. 🎓 PCIe is how a computer talks to its plug-in devices: graphics cards, network cards, and NVMe drives. A device is not at a fixed address. The host finds it, asks what it is, and gives its registers a place in memory. The root complex is the piece of the host that makes this possible: a bridge between the host's ordinary memory-mapped bus and the PCIe link to the device.

## What it does

```python
rc = io.add("rc", sp.PcieRootComplex())
bus.map(rc.ecam, base=0x3000_0000, size=0x10_0000)   # configuration window
bus.map(rc.mmio, base=0x4000_0000, size=0x10_0000)   # memory window
platform.connect(rc.dma, bus.add_input())            # what the device sends
platform.connect(rc.to_device, endpoint.from_host)   # the link, down
platform.connect(endpoint.to_host, rc.from_device)   # the link, up
```

```text
 host bus                                   the link
 ecam ─────▶ configuration accesses ─┐
 mmio ─────▶ memory accesses ────────┴───▶ to_device
 dma  ◀───── the device's own accesses ◀── from_device
```

The host sees two windows in its address map.

- **The configuration window, `ecam`.** Every function a bus could hold gets 4 KiB of it, laid out by bus, device and function number. 🎓 This layout is called ECAM, the enhanced configuration access mechanism. Reading the first register of each slot is how a host finds out what it has: an empty slot reads as all ones, with no error.
- **The memory window, `mmio`.** The host places the device's registers somewhere inside it, by writing an address to the device's base address register. An access to the window goes down the link, and the device answers it if the address is one it was given.
- **What comes up the link** goes out of `dma` onto the host's bus, untouched: the device's DMA into host memory, and its interrupts, which on PCIe are small writes too (see [MSI receiver](msi-receiver.md)).

💡 The root complex has to know where the host sees the memory window, because a bus hands a target offsets into its window and the device compares addresses on the host's bus. It works that out from where `mmio` is mapped, through routers and links, so there is nothing to tell it. A description that leaves `mmio` unmapped is refused when it is built, before the simulation exists.

## What it leaves out

- **The link itself.** No packets, lanes, training, flow control or errors. The link is a pair of ordinary TLM sockets, and a transaction on it is marked only with whether it is a configuration access.
- **A tree.** One device sits on the link, and it is function 0 of device 0 on bus 0. There are no root ports, bridges or switches, and no bus beyond the first.
- **Who sent it.** 🚧 A real packet names its sender, which is what lets a host confine a device to its own memory. Nothing here carries or checks that yet.
- **Translation.** An address means the same on the link as on the host's bus.
- **Legacy.** No I/O ports and no interrupt pins.
- **Debug and DMI.** A peek from the host does not reach the device, and neither does direct memory access.

## Under the hood

`src/socpuppet/models/pcie_root_complex.h`, and `src/socpuppet/models/pcie_link.h` for what a transaction on the link carries.

⚠️ This is modelled from public sources: the PCI specifications are not free to read. The layouts follow what open drivers expect (Zephyr's `drivers/pcie`), and the model makes no claim to conform to the specifications. socpuppet looked at borrowing VCML's PCI model first and decided to write its own. [pcie-spike.md](../pcie-spike.md) says why.
