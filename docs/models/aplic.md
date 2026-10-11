# Interrupt controller (APLIC)

`sp.Aplic()` · C++ `socpuppet::Aplic` · registry name `aplic`

## What it stands for

The interrupt controller that speaks for devices that only have a wire, on a platform whose CPU is sent its interrupts as messages. 🎓 APLIC is short for advanced platform-level interrupt controller. It is the other half of RISC-V's Advanced Interrupt Architecture (AIA), beside the [IMSIC](imsic.md).

An IMSIC takes messages: a device interrupts by writing a number, an interrupt identity, to the IMSIC's page. A PCIe device can do that itself. A UART cannot. It has one interrupt line and no way to write to anything. The APLIC is where such lines go, and for each one that asks it does the writing.

💡 This is what lets a console sit on another die than the CPU. A die-to-die link carries transactions and has nowhere for a wire to go down. So the UART's line stops at an APLIC on its own die, and what crosses the link is a write like any other.

## What it does

```python
aplic = io.add("aplic", sp.Aplic())
io_bus.map(aplic.socket, base=0x000C_0000)
platform.connect(uart.irq, aplic.source16)
platform.connect(aplic.msi, up.add_input())   # a bus that leads to the IMSIC's page
```

```text
 a device        its line         APLIC                     message            IMSIC
 ──────────▶  rises at source 16 ──▶ source 16 pending ──▶  write of "16"  ──▶ identity 16
                                     and enabled: send      to the hart's page    pending
```

| | |
|---|---|
| **Lines in** (`source1` to `source31`) | One for each device. A line left unconnected is low. |
| **Registers on the bus** (`socket`) | Where firmware sets it up. 32 KiB, 32 bits each. |
| **Messages out** (`msi`) | A 32-bit write of an interrupt identity, to the address firmware gave for the hart's page. Connect it to a bus the IMSIC's `machine` page is on, or to something that leads to one. |

### What firmware does

1. It says where messages go, in **`mmsiaddrcfg`**: the address of hart 0's page with its low twelve bits dropped. It switches the domain's interrupts on with the IE bit of **`domaincfg`**.
2. For each source it wants to hear of, it writes a mode to **`sourcecfg`** (6, "asks while its line is high", for every device in socpuppet), an identity to **`target`**, and the source's number to **`setienum`** to enable it.
3. The line rises. The source becomes pending, and since it is enabled the APLIC sends its identity and clears the pending bit. That is the whole interrupt, as far as the APLIC goes: there is no claim and no "complete". The handler runs because the IMSIC interrupts the CPU.

💡 **Which identity a source sends is firmware's choice.** It need not be the source's number. socpuppet's module for Zephyr gives source N identity N, because Zephyr knows an interrupt by one number.

⚠️ **A level is sent once, when it rises.** With a wire to a [PLIC](plic.md), a device that is still asking when its handler returns interrupts again at once, because the level is still there. A message is a moment, and a line that never fell has nothing to rise. Take a UART with a received byte waiting and room to transmit. The handler sees to the byte and returns, the line is still high for the transmitter, and no message follows. So after a handler, firmware asks the APLIC to look at the source again by writing its number to **`setipnum_le`**: if the line is still asking, the source is pending and is sent again. Linux's driver does this. Zephyr 4.4's does not, and socpuppet's module does it for it (see [upstream.md](../upstream.md)).

💡 **A source set up while its line is already asking is pending at once.** A byte typed at a console while the firmware was still booting is not lost.

### The registers

| Offset | Register | |
|---|---|---|
| `0x0000` | `domaincfg` | Bit 8, IE, switches the domain's interrupts on. Bit 2, DM, says it delivers by message, and here it is always one. |
| `0x0004` + 4 × (N − 1) | `sourcecfg` for source N | The mode: 0 inactive (out of reset), 4 and 5 an edge, 6 and 7 a high or a low level. |
| `0x1BC0`, `0x1BC4` | `mmsiaddrcfg`, `mmsiaddrcfgh` | Where messages go, and how the pages of further harts are laid out. |
| `0x1EDC`, `0x1FDC` | `setienum`, `clrienum` | Written with a source's number, to enable and to disable it. |
| `0x2000` | `setipnum_le` | Written with a source's number, to have it looked at again. |
| `0x3004` + 4 × (N − 1) | `target` for source N | The hart in bits 31 to 18 and the identity in the low eleven. The bits between read as zero. |

A source above 31 does not exist: its `sourcecfg` and `target` read as zero and ignore writes, so it stays inactive. So do the parts of the 32 KiB that the specification keeps or that this APLIC has nothing for. The borrowed model's other registers are still there: `setip`, `in_clrip`, `setie` and `clrie`, which work a bit for each source, and the ones for delivering over a line, which hold what is written and do nothing here.

## What it leaves out

- **Delivering over a line.** An APLIC can also interrupt a hart the way a PLIC does, and firmware chooses with the DM bit. This one has no line to a hart, so DM is one and a write cannot clear it, which the specification allows. Zephyr's driver relies on it, since it never sets the bit.
- **Small things the specification asks for.** `domaincfg` does not read `0x80` in its top byte, `mmsiaddrcfgh` has no lock bit, and a `target` can be written while its source is inactive.
- **A domain for supervisor mode.** There is one domain, for machine mode. `smsiaddrcfg` reads as zero and ignores writes.
- **`genmsi`**, which sends a message of firmware's own making, and `setipnum`, `clripnum` and `setipnum_be`, the other registers that work by a source's number.
- **A debugger's look.** A debug read of the registers is not answered.
- **Timing.** A message is sent a delta cycle after what caused it. Each waits for the one before to arrive.

## In a devicetree

```dts
io_aplic: interrupt-controller@100c0000 {
	compatible = "riscv,aplic";
	reg = <0x0 0x100c0000 0x0 0x8000>;
	#address-cells = <0>;
	#interrupt-cells = <3>;
	interrupt-controller;
	riscv,num-sources = <31>;
	msi-parent = <&compute_imsic>;
};
```

`msi-parent` is the IMSIC that the APLIC's messages reach. It is found by following the `msi` socket's connections, the way an address map is, so it is there only if the platform really does lead there. ⚠️ The APLIC has to find the page at the address the CPU does, because firmware reads the address from the IMSIC's node and tells the APLIC to send there. If the two differ, `platform.devicetree()` refuses and gives both. A device at one of the sources names it with three numbers, `16 1 4`: the source, a priority, and 4, the devicetree's number for a line that asks while it is high. The host's UART has them as `interrupt-parent = <&io_aplic>` and `interrupts = <16 1 4>`.

## Under the hood

💡 This one is borrowed. The model is the APLIC from [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals), written at Qualcomm, which delivered over a line only. Delivery by message is added by `cmake/patches/vpv-peripherals-aplic-msi-mode.patch`, which is written up in [upstream.md](../upstream.md) as a feature to offer.

socpuppet wraps it in an adapter (`src/socpuppet/models/aplic.cpp`) that:

- brings out 31 of its 1,022 sources, ties the rest low, and keeps firmware from setting one of the rest up;
- holds it in delivery by message, from reset and whatever is written;
- passes its messages on from the kind of socket the borrowed model has to an ordinary one;
- answers for the reserved parts of the register map, which the borrowed model refuses.

The messages are sent by one thread of the model's own. A line changes in a method and a register is written in the caller's thread, and neither may be kept waiting by whatever is between the APLIC and the hart. On the host that is a die-to-die link, which takes its time, and the register write may have come over the same link.

It is held to `AplicContract` (`tests/cpp/contracts/aplic_contract.h`).
