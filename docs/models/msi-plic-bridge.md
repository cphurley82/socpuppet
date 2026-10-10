# MSI-to-PLIC bridge

`sp.MsiPlicBridge(vectors=...)` · C++ `socpuppet::MsiPlicBridge` · registry name `msi_plic_bridge`

## What it stands for

The piece of a host that lets a PCIe device interrupt a CPU whose interrupt controller only has wires.

🎓 A PCIe device has no interrupt wire to the host. It interrupts by writing a small message to an address the host chose (see the [endpoint](pcie-endpoint.md)). This is a message-signalled interrupt, MSI for short. A RISC-V host with an IMSIC takes such a message as it is. A host with only a [PLIC](plic.md) needs something at that address to turn the write back into a wire, and this is that something.

RISC-V has no standard block of this kind. The nearest real one is the MSI frame of Arm's GICv2m, which does the same job for a GIC that only has wires: a write of an interrupt's number to one register pulses that interrupt.

## What it does

```python
msi = compute.add("msi", sp.MsiPlicBridge(vectors=2))
bus.map(msi.socket, base=0x0300_0000)
platform.connect(msi.irq0, plic.source1)
platform.connect(msi.irq1, plic.source2)
```

It is one 32-bit register and one wire for each vector.

| | |
|---|---|
| **A write** | is a message. Its data is the number of a vector, counted from 0, and that vector's line pulses. |
| **`irq0`, `irq1`, ...** | one line for each vector. A pulse is as short as a pulse can be: the line rises, and falls again one delta cycle later. |
| **A read** | returns zero. A message is sent, not kept. |

So the host tells a device to send each interrupt to this register's address, with the vector's own number as the data. Zephyr does exactly that for the host board's drive. Its driver for the root complex (`socpuppet,pcie`, in socpuppet's Zephyr module) reads the address and the PLIC source of each line from the devicetree.

### Why a pulse

```text
 the drive        message         bridge            PLIC             CPU
 ──────────▶  write of "1"  ──▶  irq1 ▁▁█▁▁▁  ──▶  source 2  ──▶  interrupt
                                                   pending          │
                                                   until claimed ◀──┘ claim, handle, complete
```

Nothing ever tells the bridge that an interrupt was handled. The handler talks to the device and to the PLIC, and neither of them talks to the bridge. A line left high would be a device that never stops asking. So the bridge only passes the edge on, and the PLIC does the remembering: the source is pending from the pulse until the handler claims it.

That asks one thing of the PLIC, which socpuppet's is held to. 💡 A pulse that comes while the handler is still running must not be lost, because the handler may already have looked at its device. See "A request made while the handler runs is remembered" on the [PLIC's page](plic.md).

### Two messages at once

A message that arrives before the line has risen for the one before is the same interrupt: there is one rise, after both. A message that arrives while the line is still high gets a rise of its own, since the rise on the line came before it. Either way no message is left without a rise after it.

## What it leaves out

- **A range of interrupts to choose from.** A real MSI frame is told which of the controller's interrupts it may raise, and a message can name any of them. Here vector N is line N, and the platform's wiring says which source that is.
- **Telling devices apart.** Two devices that are given the same vector numbers cannot be told apart. The host board has one device.
- **Anything to read.** No pending bits and no identification register.
- **Timing.** A line pulses a delta cycle after its message, at the same simulated time.

A message naming a vector the bridge has no line for gets a bus error, and so does an access that is not a 32-bit access to the register.

## In a devicetree

```dts
compute_msi: msi-controller@2000000 {
	compatible = "socpuppet,msi-plic-bridge";
	reg = <0x0 0x2000000 0x0 0x4>;
	msi-controller;
	interrupts-extended = <&compute_plic 1 1 &compute_plic 2 1>;
};
```

`interrupts-extended` names the PLIC source of each line, in the order of the vectors and whatever order the wires were connected in. A root complex's node points here with `msi-parent`.

## Under the hood

`src/socpuppet/models/msi_plic_bridge.h`. The lines are driven by one process of its own, because a message arrives in the sending device's process and a SystemC signal takes one writer. That process reads back its own lines to see which are high, so it runs at most once in a delta cycle.

🎭 Its sibling is the [MSI receiver](msi-receiver.md), which a scripted host with no interrupt controller uses: one line for all vectors, held high until the host reads which ones.
