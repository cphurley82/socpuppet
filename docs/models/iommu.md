# IOMMU

`sp.Iommu()` · C++ `socpuppet::Iommu` · registry name `iommu`

## What it stands for

An IOMMU as the RISC-V IOMMU specification describes one, the kind QEMU's `riscv-iommu-sys` is. 🎓 IOMMU is short for input-output memory management unit, and it is to a device what the MMU is to a program. A device that does DMA writes wherever it is told to, and a driver with a bug, or a device with a bad firmware, can tell it to write anywhere. With an IOMMU in the way, every address a device uses goes through page tables the operating system owns, and an access that is not mapped is refused and reported.

It finds a device's page tables by the device's ID, which for a PCIe device is its *requester ID*, its bus, device and function numbers, which the [PCIe endpoint](pcie-endpoint.md) marks its accesses with. The ID indexes a *device directory* in memory, a small tree of tables whose leaves are *device contexts*: one for each device, saying whether it may do DMA at all and which page tables its addresses go through. Two rings in memory carry the rest: a *command queue* that software writes to, to say a table changed, and a *fault queue* the IOMMU writes a *fault record* to for every access it refuses.

## What it does

```python
iommu = io.add("iommu", sp.Iommu())
io_bus.map(iommu.socket, base=0x000E_0000)
platform.connect(root_complex.dma, iommu.target)   # what the device sends
platform.connect(iommu.initiator, up.add_input())  # a bus that leads to memory
platform.connect(iommu.irq, aplic.source24)
```

`host(drive_blocks=..., iommu=True)` puts one there on the host, between the PCIe root complex and the link to the compute die ([address-map.md](../address-map.md)).

```text
 the drive      a write to 0x1000,        IOMMU                                       RAM
 ──────────▶   from requester ID 0  ──▶  device directory: ID 0's context  ──▶   a write to 0x8123_4000
                                          its page tables: 0x1000 is 0x8123_4000
                                          not mapped: refused, a fault record, irq
```

| | |
|---|---|
| **Devices' accesses in** (`target`) | Each marked with who sent it. One that is not is refused, with no fault record, since there is no device to name in one. |
| **Out to memory** (`initiator`) | What was translated, at its new address; and the IOMMU's own reads of its tables and its writes of records and fences. |
| **Registers on the bus** (`socket`) | Where firmware sets it up. A page. |
| **Interrupt** (`irq`) | High while a queue that may interrupt has something for software. |

### What firmware does

1. It reads **`capabilities`**: version 1.0, a first stage of Sv39, device contexts in the 32-byte base format, and wired interrupts.
2. It puts the two queues in memory and says where, and how big, in **`cqb`** and **`fqb`**. It turns each on, with its interrupt, in **`cqcsr`** and **`fqcsr`**, and waits until they say they are on.
3. It builds a device directory and says where its root is, and how many levels it has, in **`ddtp`**. Out of reset the mode there is Off, and every access is refused. Bare lets every access through untranslated.
4. For each device it fills in a device context. Its first stage is Bare, which lets the device's accesses through as they are, or Sv39, with the root of the device's page tables. A page a device may use has U set, since a device's access counts as user mode's, and A, and D for a write, since this IOMMU sets neither itself. ⚠️ A device's interrupt messages are its accesses too, and go through the same page tables: map the IMSIC's page (`0x2400_0000` on the host) at its own address, or every interrupt is a fault record. A Bare first stage, which is what Linux gives a device, lets them through by itself.
5. Each time it changes a table, it says so in the command queue: IODIR.INVAL_DDT for the directory, IOTINVAL.VMA for page tables, and IOFENCE.C to wait for the commands before it. It moves **`cqt`** past them and waits for **`cqh`** to get there, or for a fence with AV to write its word.
6. When a device does what it may not, the IOMMU writes a record to the fault queue, moves **`fqt`**, sets FIP in **`ipsr`** and raises `irq`. Firmware reads the records from **`fqh`** to the tail, moves `fqh`, and clears FIP by writing it.

💡 **Linux brings it up and does not translate through it.** In Linux 6.18 the DMA API's IOMMU layer is not built for RISC-V, so every device gets an identity domain: Linux's `riscv-iommu` driver programs the queues, the directory and the interrupt, and gives the drive a context with a Bare first stage. socpuppet's Zephyr driver is what puts a device behind page tables.

### The registers

64 bits where the specification has them so, the rest 32.

| Offset | Register | |
|---|---|---|
| `0x000` | `capabilities` | What this IOMMU is. Nothing writes it. |
| `0x008` | `fctl` | WSI, bit 1, set: it interrupts by wire, which Linux reads before it asks for wires. Nothing writes it. |
| `0x010` | `ddtp` | The directory's mode, bits 3:0 (Off, Bare, one to three levels), and the page its root table is at, bits 53:10. A mode the specification reserves is not taken, and the register keeps the one it had. `busy` is never seen set. |
| `0x018`, `0x020`, `0x024` | `cqb`, `cqh`, `cqt` | The command queue: where it is and how big, LOG2SZ in bits 4:0 being one less than the log of its entries; the next command the IOMMU runs; and where software puts the next. |
| `0x028`, `0x030`, `0x034` | `fqb`, `fqh`, `fqt` | The fault queue: the same, with software at the head and the IOMMU at the tail. |
| `0x048` | `cqcsr` | The command queue on and its interrupt on, and what went wrong: CMD_ILL, a command this IOMMU does not have, and CQMF, a command it could not read. Either stops the queue at the command, and is cleared by writing it. |
| `0x04C` | `fqcsr` | The same for the fault queue: FQOF, a record with no room, and FQMF, a record nothing took. |
| `0x054` | `ipsr` | Which queue wants attention: CIP and FIP, cleared by writing them. |
| `0x2F8` | `icvec` | Which of the IOMMU's interrupt lines each cause goes to. There is one, so every cause is on it, and the register reads zero whatever is written. |

A debugger can read a register (`platform.peek`), and cannot write one: a write would set the IOMMU running, as one of firmware's does.

## What it leaves out

- **A second stage**, the page tables a hypervisor has its guests' addresses go through. A context that asks for one is misconfigured.
- **Process contexts**, ATS, page requests and the remapping of interrupt messages. A context that asks for any is misconfigured, and their commands stop the command queue.
- **A cache of what it walked.** Every access walks the directory and the page tables from the top, and on the host each of those reads crosses the link to the compute die. A real IOMMU caches translations, which is why the invalidation commands exist; here they have nothing to do. 🎓 It shows: Zephyr's disk test crosses the link 378 times with no IOMMU, 1,894 times with the drive behind one untranslated, since every access reads the drive's 32-byte context as four 8-byte reads, and 2,723 times through page tables (`tests/python/test_m15_exit.py`).
- **The page tables' A and D**, which it checks and never sets, and DTF, which a context may not set yet.
- **Device IDs for a device with no PCIe link behind it.** One is refused. 🚧 M19's AI processor brings an ID given as a parameter.
- **The counters, the debug translation registers and the MSI configuration table**, which drivers need only with the features above.
- **Timing.** The IOMMU takes no time of its own: a walk takes what its reads take.

## In a devicetree

```dts
io_iommu: iommu@100e0000 {
	compatible = "riscv,iommu";
	reg = <0x0 0x100e0000 0x0 0x1000>;
	#iommu-cells = <1>;
	interrupt-parent = <&io_aplic>;
	interrupts = <24 1 4>;
};
```

A device names it with one cell, the device ID it is known to the IOMMU by. The devicetree says which devices are behind it in the node of whatever is in front of them, found by following its connections: for the root complex, the one whose `dma` comes in at `target`. In Zephyr's dialect that is `iommus = <&io_iommu 0x0>`, a list of the IDs the IOMMU will see, of which the one device on the link has one; socpuppet's module has the bindings for both nodes, and the property is what has Zephyr start the IOMMU's driver first. In Linux's it is `iommu-map = <0x0 &io_iommu 0x0 0x10000>`: requester IDs from 0, all 65536 of them, are the IOMMU's device IDs from 0.

`msi-parent` in the root complex's node is unchanged by an IOMMU in the way: the devicetree's walk to what takes the drive's messages goes through it, as the messages do, and takes them to arrive at the address they were sent to, which they do if firmware has mapped the IMSIC's page at its own address.

## Under the hood

The model is socpuppet's own, written for [VPV-Peripherals](https://github.com/VP-Vibes/VPV-Peripherals)' `rvi/` directory, beside its APLIC, to be offered upstream ([upstream.md](../upstream.md)). It is in `src/vpvper/rvi/`, laid out as VPV's tree is and in MINRES's style: `iommu_walker.h`, which walks the tables and names what is wrong, and is unit-tested on its own (`tests/cpp/unit/iommu_walker_test.cpp`); `iommu.h` and `iommu.cpp`, the SystemC model; and `iommu.rdl`, its register map, with `gen/iommu_regs.h` written by hand in the shape MINRES's generator makes, which `tests/tooling/test_vpvper_registers.py` holds to the map.

socpuppet wraps it in an adapter (`src/socpuppet/models/iommu.cpp`), as it does the borrowed models, that:

- marks each access with the device it is from as the model wants it, from the access's PCIe requester ID;
- passes what the model sends out on from the kind of socket it has to an ordinary one;
- answers a debugger's read of a register, and refuses its write.

Commands run on a thread of the model's own, woken by a write of `cqt`: a register write never waits, and the IOMMU's reads of the queue may cross the link the write came over. One method drives `irq`, from `ipsr` and the queues' interrupt enables, so no two processes write the line.

It is held to `IommuContract` (`tests/cpp/contracts/iommu_contract.h`).
