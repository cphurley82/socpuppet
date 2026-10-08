# PCIe endpoint

`sp.PcieEndpoint(vendor_id=..., device_id=..., class_code=..., function_size=..., vectors=...)` · C++ `socpuppet::PcieEndpoint` · registry name `pcie_endpoint`

## What it stands for

The part of a PCIe device that the bus sees. A device's real work is done by a *function* behind it: here an NVMe controller, which knows nothing about PCIe. The endpoint is the wrapping that makes the function findable and placeable, and that carries its DMA and its interrupts to the host. On a real chip it is usually a block of licensed IP between the PCIe pins and the device's own logic.

## What it does

```python
endpoint = ssd.add("endpoint", sp.PcieEndpoint(
    vendor_id=0x5350, device_id=0xC0DE,
    class_code=0x01_08_02,                              # an NVMe drive
    function_size=sp.BehavioralNvme.mapped_size, vectors=2))
platform.connect(rc.to_device, endpoint.from_host)      # the link, down
platform.connect(endpoint.to_host, rc.from_device)      # the link, up
platform.connect(endpoint.bar0, nvme.bar0)              # the function's registers
platform.connect(nvme.dma, endpoint.dma)                # its DMA
platform.connect(nvme.irq0, endpoint.irq0)              # its interrupt lines
platform.connect(nvme.irq1, endpoint.irq1)
```

```text
 the link                                       the function
 from_host ──▶ configuration space
           ──▶ memory accesses ───────────────▶ bar0
 to_host   ◀── the function's DMA ◀──────────── dma
           ◀── interrupts, as messages ◀─────── irq0, irq1, ...
```

It has three jobs.

- **Saying what the device is.** 🎓 Every function has 4 KiB of *configuration space*. It starts with who made the device (`vendor_id`), which of their devices it is (`device_id`) and what kind of thing it is (`class_code`, three bytes: 01 08 02 is mass storage, non-volatile memory, NVMe). A host picks a driver by these.
- **Giving the function's registers a place.** 🎓 A *base address register* (BAR) is how a device asks for a piece of the host's address map. The host writes all ones to it and reads back, and the bits that stay zero say how big the piece has to be. Then it writes the address it has chosen. This endpoint has one BAR, the first, 64 bits wide. Nothing behind it answers until the host switches on *memory decoding* in the command register.
- **Carrying the function's side to the host.** The function's DMA goes up the link as it is, and each rise of one of its interrupt lines becomes one message (below). Neither happens until the host makes the device a *bus master*, with another bit of the command register: until then DMA is refused with a bus error, and an interrupt is remembered as pending and sent afterwards. A message that nobody on the host's bus answers sets the *received master abort* bit of the status register, as it would on a real bus, which is the one place a driver can see that its interrupts are going nowhere.

### Interrupts: MSI-X

🎓 A PCIe device has no interrupt wire to the host. It interrupts by writing a small message into the host's memory map, at an address the host chose, and something at that address turns the write into an interrupt for the CPU. This is called a message-signalled interrupt, and MSI-X is the current form of it.

```text
 BAR0:  ┌─────────────────────────┐ 0
        │ the function's own      │
        │ registers               │
        ├─────────────────────────┤ function_size, rounded up to a page
        │ MSI-X table             │ 16 bytes per vector: address, data, mask
        ├─────────────────────────┤ the next page after the table
        │ pending bits            │ one per vector
        └─────────────────────────┘
```

- The host finds MSI-X by walking the *capability list* in configuration space, which says how many vectors there are (`vectors`) and where the table is.
- For each vector the host writes an address and 32 bits of data into the table. When the function's interrupt line for that vector rises, the endpoint writes that data to that address, up the link.
- A vector can be masked, one at a time or all at once. An interrupt that arrives meanwhile is remembered as *pending* and sent when the mask comes off.

## What it leaves out

- **Everything about the link** that the [root complex](pcie-root-complex.md) leaves out too: packets, training, errors, and who sent what.
- **More than one of anything.** One function, one BAR. No expansion ROM, no I/O ports.
- **Other interrupts.** No interrupt pin and no plain MSI, only MSI-X. With MSI-X off, a rising line is not an interrupt at all.
- **Other capabilities.** The list holds MSI-X and nothing else: no power management and no PCI Express capability, which real devices also have and some drivers look for. The registers underneath can take more (`PcieEndpointRegisters::AddCapability`), read-only for now, so adding one is a few lines when a driver asks.
- **Forgetting.** A pending interrupt stays pending even if the function's line has fallen again by the time the mask comes off. Real hardware would forget it.
- **Timing.** A message goes out a delta cycle after its line rises, at the same simulated time.
- ⚠️ An access the endpoint does not claim (outside BAR0, or with memory decoding off) gets a bus error. A real bus answers a stray read with all ones.

## Under the hood

- `src/socpuppet/core/pcie_endpoint_registers.h` holds the registers and every decision that hangs on them, as plain C++ with no simulator: what a write may change, whose a memory access is, whether a message can be sent now.
- `src/socpuppet/models/pcie_endpoint.h` is the SystemC wrapper: the sockets, the interrupt lines, and the process that sends messages.
- `tests/cpp/platform/pcie_test.cpp` drives it the way a host does, through a root complex.

⚠️ This is modelled from public sources (the register definitions in Zephyr's `drivers/pcie` headers among them), because the PCI specifications are not free to read. It makes no claim to conform to them.
