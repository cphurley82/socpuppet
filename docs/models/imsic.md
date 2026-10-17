# Interrupt controller (IMSIC)

`sp.Imsic(identities=...)` · C++ `socpuppet::Imsic` · registry name `imsic`

## What it stands for

The interrupt controller a RISC-V CPU is sent messages at. 🎓 IMSIC is short for incoming message-signalled interrupt controller, and it is half of RISC-V's Advanced Interrupt Architecture (AIA). The other half, the APLIC, is for devices that only have a wire.

With a [PLIC](plic.md), every device has a wire to the controller. With an IMSIC there are no wires. A device interrupts by writing a number to an address, and that write is the whole interrupt. The number is called an interrupt identity, and it says which interrupt this is, as a PLIC's source number does.

💡 This is what a die-to-die link wants. A link carries transactions and has nowhere for a wire to go down, and a write is a transaction like any other. A PCIe device's interrupt has always been such a message (MSI), so the host's drive interrupts with no translation at all.

An IMSIC belongs to one hart, RISC-V's word for a CPU as software sees it. It keeps two **interrupt files**, one for machine mode and one for supervisor mode, so that an operating system and the monitor under it each have their own. A file is a set of pending bits, a set of enable bits and a threshold.

## What it does

```python
imsic = compute.add("imsic", sp.Imsic())
bus.map(imsic.machine, base=0x2400_0000)
bus.map(imsic.supervisor, base=0x2800_0000)
platform.connect(imsic.irq, cpu.irq)
platform.connect(imsic.supervisor_irq, cpu.supervisor_irq)
platform.connect(cpu.csr, imsic.csr)
```

```text
 a device          message           IMSIC                    CPU
 ──────────▶  write of "32"  ──▶  identity 32 pending  ──▶  interrupt
                to the page       irq high while an          │
                                  enabled one is pending ◀───┘ claim: irq falls
```

Each file has three ways in and out:

| | |
|---|---|
| **A page on the bus** (`machine`, `supervisor`) | 4 KiB. A 32-bit write of an identity to its first word makes that identity pending. The AIA specification calls the register `seteipnum_le`. The page reads as zero everywhere, and a write anywhere else in it does nothing. |
| **Registers, through the CPU** (`csr`) | They are not on the bus at all. Firmware reaches them with the CPU's own register instructions, so connect the CPU's `csr` to the IMSIC's. A file cannot interrupt until firmware has switched it on there. |
| **A line to the CPU** (`irq`, `supervisor_irq`) | High while an identity that firmware enabled is pending and delivery is switched on. These are the machine and the supervisor external interrupt. |

### What firmware does

1. It writes 1 to **`eidelivery`**, which lets the file interrupt at all, and sets a bit in **`eie`** for each identity it wants to hear of.
2. A message arrives, the identity's bit in **`eip`** is set, and the CPU's line rises.
3. The handler reads **`mtopei`** and writes it, in one instruction. The read is the identity to see to, and the write takes it: its pending bit is cleared. That is a **claim**. The line falls if nothing else is waiting.

There is no "complete" step, as a PLIC has. A device that needs attention again sends another message.

💡 **No device comes with an identity.** A device sends whatever number firmware told it to. For a PCIe device that is a field of its MSI-X table, which the driver fills in. So it is firmware, or the board it was built for, that shares the identities out. The host sets 32 and 33 aside for its drive.

💡 **A lower identity has the higher priority.** Of two that are pending, the lower is claimed first. A **threshold** (`eithreshold`) holds back identities at or above it, and zero holds nothing back.

💡 **What is pending is a bit and not a count.** Two messages for one identity before it is claimed are one interrupt, as a wire that stayed high would be.

### The registers, and how they are reached

A file's registers are selected by number. Firmware writes the number to the CPU's `miselect` register and then finds the register at `mireg`.

| Number | Register | |
|---|---|---|
| `0x70` | `eidelivery` | 1 to let the file interrupt its hart. |
| `0x72` | `eithreshold` | Identities at or above this are held back. Zero holds nothing back. |
| `0x80`, `0x82`, ... | `eip0`, `eip2`, ... | Pending bits, 64 identities to a register. Firmware may write them, to ask for an interrupt itself. |
| `0xC0`, `0xC2`, ... | `eie0`, `eie2`, ... | Enable bits, laid out the same way. |

With registers of 64 bits the odd-numbered ones do not exist, and selecting one is an illegal instruction. Identity 0 means "none", so its bit is always zero. `0x71` and `0x73` to `0x7F` are the specification's to use later, and read as zero.

`mtopei` (and `stopei` for the supervisor's file) has the identity twice over: in bits 26 to 16, and again in the low eleven as its priority, which with an IMSIC is the same number. Zephyr's driver reads the low copy and Linux's the high one.

## What it leaves out

- **The page's second register**, `seteipnum_be`, which takes a message with its bytes the other way round. A write there does nothing.
- **Guest interrupt files**, which a hypervisor's guests have.
- **Registers of 32 bits**, which a 32-bit hart has twice as many of.
- **The other way of delivering** that the specification allows, from a PLIC, which is what a value of `0x40000000` in `eidelivery` asks for.
- **Timing.** A line changes in the same instant as the message or the register write that caused it, a delta cycle on.

An access to a page that is not of 32 bits gets a bus error.

## In a devicetree

```dts
compute_imsic: interrupt-controller@24000000 {
	compatible = "riscv,imsic";
	reg = <0x0 0x24000000 0x0 0x1000>;
	#address-cells = <0>;
	#interrupt-cells = <1>;
	interrupt-controller;
	msi-controller;
	riscv,num-ids = <63>;
	riscv,hart-id = <0>;
	interrupts-extended = <&compute_cpu_intc 11>;
};
```

The node is the page for machine mode's messages and that mode's line, since machine mode is where the firmware a devicetree is generated for runs. A root complex's node points here with `msi-parent`. The CPU's node gains `smcsrind` in its list of extensions when its `csr` is connected, which is what Zephyr switches its IMSIC driver on for, and `ssaia` beside it on a core with supervisor mode, which is what Linux's looks for.

In Linux's dialect it is a node for each page, `riscv,imsics`, and the mode is said only by which of the CPU's interrupts each names: 11, machine mode's external interrupt, and 9, the supervisor's. A hart is found the same way, so there is no `riscv,hart-id`. OpenSBI keeps machine mode's for itself and marks its node disabled before it hands the tree on, so Linux sees only the supervisor's.

```dts
compute_imsic_s: interrupt-controller@28000000 {
	compatible = "riscv,imsics";
	reg = <0x0 0x28000000 0x0 0x1000>;
	#address-cells = <0>;
	#interrupt-cells = <0>;
	interrupt-controller;
	msi-controller;
	#msi-cells = <0>;
	riscv,num-ids = <63>;
	interrupts-extended = <&compute_cpu_intc 9>;
};
```

⚠️ `identities` is the highest identity a file has, and the specification allows 63, 127 and so on up to 2047. The host has 63. Zephyr 4.4's driver enables the wrong register for an identity above 63 on a 64-bit hart, which is in [upstream.md](../upstream.md).

## Under the hood

`src/socpuppet/models/imsic.h` is a thin SystemC model around two `InterruptFile` objects (`src/socpuppet/core/interrupt_file.h`), which are plain C++ with no simulator attached and have unit tests of their own.

How the CPU reaches the registers is in `src/socpuppet/models/hart_registers.h`: a pair of ordinary TLM sockets, where an access's address is the number of the CPU's register, twelve bits up, with what `miselect` selected in the low twelve. On a chip that is wires between the hart and its IMSIC.

The lines are driven by one process of the model's own, because a message arrives in the sending device's process and a register is written in the CPU's, and a SystemC signal takes one writer.

It is held to `MessageControllerContract` (`tests/cpp/contracts/message_controller_contract.h`), whose devices send from threads of their own, as devices on a platform do.

🎭 Its stand-in sibling, a simplified model, is the [MSI receiver](msi-receiver.md), which a scripted host with no CPU uses.
