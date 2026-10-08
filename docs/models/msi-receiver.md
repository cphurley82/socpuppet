# 🎭 MSI receiver

`sp.MsiReceiver()` · C++ `socpuppet::MsiReceiver` · registry name `msi_receiver`

## What it stands in for

The part of a host's interrupt controller that takes message-signalled interrupts. A PCIe device interrupts by writing a message to an address the host chose (see the [endpoint](pcie-endpoint.md)), and something at that address has to turn the write back into an interrupt for the CPU. On a RISC-V host that is an IMSIC (incoming message-signalled interrupt controller), and on a PC it is the local APIC.

💡 This is for a host with no CPU and no interrupt controller: a script reads the register to learn which vector woke it. The host board, which runs real firmware, has an [MSI-to-PLIC bridge](msi-plic-bridge.md) in this place, with a line for each vector.

## What it does

```python
msi = compute.add("msi", sp.MsiReceiver())
bus.map(msi.socket, base=0x2000_0000)
platform.connect(msi.irq, cpu.irq)
```

It is one 32-bit register and one wire.

| | |
|---|---|
| **A write** | is a message. Its data is the number of a vector, 0 to 31, and that vector is then waiting. |
| **`irq`** | is high while any vector is waiting. |
| **A read** | returns the waiting vectors, one bit each, and none is waiting afterwards, so `irq` falls. |

So the host tells a device to send every interrupt to this register's address, with the vector's own number as the data. 🧵 In a script, [`sp.MsiHost`](pcie-host.md) is the host's side of this: it says what a device is to be told, and it waits for the line and reads the register.

## What it leaves out

- **Everything a real interrupt controller has**: priorities, enables, a separate file of interrupts per CPU, claiming and completing.
- **More than 32 vectors.** A message naming a higher one gets a bus error.
- **Telling devices apart.** Two devices that are given the same vector numbers cannot be told apart.

## Under the hood

`src/socpuppet/models/msi_receiver.h`. The line is driven by one process of its own, because a message arrives in the device's process and a read in the host's, and a SystemC signal takes one writer at a time.
