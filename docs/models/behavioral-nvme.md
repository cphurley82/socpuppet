# 🎭 Behavioral NVMe

`sp.BehavioralNvme(blocks=..., vectors=2)` · C++ `socpuppet::BehavioralNvme` · registry name `behavioral_nvme`

## What it stands in for

An NVMe SSD, as the host's driver sees it. 🎓 NVMe (Non-Volatile Memory Express) is the protocol a computer speaks to a modern SSD. It is built around queues that live in the host's own memory:

```text
 host driver                 host memory                    controller
      │ 1. write a command ─▶ submission queue
      │ 2. ring the doorbell ─────────────────────────────▶ registers
      │                       submission queue ── 3. ─────▶ fetch the command (DMA read)
      │                       data pages ◀─────── 4. ─────▶ blocks
      │                       completion queue ◀─ 5. ────── post a completion (DMA write)
      │ ◀──────────────────── 6. interrupt ────────────────
      │ 7. read the completion, ring the other doorbell ──▶ registers
```

- A **doorbell** is a register the host writes to say "I have put something in the queue, up to here".
- **DMA** (direct memory access) means the device reads and writes the host's memory itself. Nobody copies a command to the device: the device comes and gets it.
- There is one pair of **admin** queues, for commands that manage the controller, and one or more pairs of **I/O** queues, for reads and writes.

🎭 This model is a stand-in for the SSD. It hits the same marks (queues, Identify, reads and writes), so a host can rehearse against it, but there is no CPU or firmware behind the curtain. The controller's logic is a plain C++ class. When the real SSD arrives, with its own firmware, this one stays on as the reference to check it against.

## What it does

It is an NVMe **function with no PCIe around it**: the three things a PCIe endpoint would wrap.

```python
nvme = platform.add("nvme", sp.BehavioralNvme(blocks=2048))
bus.map(nvme.bar0, base=0x1000_0000)            # its registers
platform.connect(nvme.dma, bus.add_input())     # its way into host memory
platform.connect(nvme.irq0, cpu.irq)            # its interrupt
```

🧵 A script can then talk to it through `sp.NvmeHost`, the stand-in for the host's driver: `yield from nvme.enable()`, then `read_blocks` and `write_blocks`.

| Port | What it is |
|---|---|
| `bar0` | The register block: controller registers in the first 4 KiB, doorbells after them. 🎓 "BAR0" is the first base address register of a PCIe device, which is where a host finds these registers on real hardware. Map it straight onto a bus, as here, or connect it to a [PCIe endpoint](pcie-endpoint.md). |
| `dma` | How the controller reads and writes the host's memory. Connect it to an input of the bus the host's memory is on. |
| `irq0`, `irq1`, ... | One interrupt line per vector. The admin queue uses `irq0`, and the host names a vector for each I/O queue when it creates it. A line may be left unconnected. |

- **The drive** is `blocks` blocks of 512 bytes, kept in RAM, all zeros until written. It has one namespace, number 1. 🎓 A namespace is NVMe's word for a drive's worth of blocks, and a controller can have several.
- **Enable and reset.** Setting `CC.EN` makes it ready at once. Clearing it resets the controller: every queue is gone, and what is on the drive stays.
- **Admin commands**: Identify (the controller, a namespace, the list of namespaces), Set Features for the number of queues, and the two commands that create an I/O queue pair. Up to 8 pairs.
- **I/O commands**: Read, Write and Flush.
- **Data pages.** A command says where its data is page by page (🎓 PRPs, physical region pages), and the pages need not be next to each other. Transfers of any length are followed through, lists and all.
- **Errors a driver can cause** come back as the status the specification gives them: an unknown opcode, a block past the end of the drive, a queue identifier or an interrupt vector it does not have, a submission queue made before its completion queue.
- **Timing.** A doorbell write returns at once, and the controller does the work a delta cycle later, at the same simulated time. So a command takes no time, but its completion is never there yet when the doorbell write returns, which is how a real controller looks to a driver too.

### Interrupt lines

A line is high while a completion queue on its vector holds a completion the host has not acknowledged. When the host acknowledges (by writing the completion queue's head doorbell) the line falls, and if completions are still waiting it rises again a delta cycle later.

💡 Why fall and rise again? On a real PCIe device the line does not reach the host as a wire. Each rise becomes a message (MSI-X). A driver reads what it finds, acknowledges once and waits for the next message. If the line just stayed high for the completions still waiting, no message would come, and they would sit there like a parrot nailed to its perch.

## What it leaves out

- **PCIe.** No configuration space, no base address registers, no MSI-X table. That is the [PCIe endpoint](pcie-endpoint.md)'s job, and the two are connected port for port: `bar0`, `dma`, and each `irq`.
- **Everything behind the registers of a real SSD**: a CPU, firmware, a flash translation layer, NAND flash, wear, garbage collection.
- **Time.** Nothing takes any. There is no latency, and the controller never falls behind or pushes back.
- **Most of the command set.** No deleting queues, no Get Features or log pages, no asynchronous events, no Dataset Management (TRIM), no namespaces beyond the first, and block size is fixed at 512.
- **Sharing a vector.** Each completion queue is expected to have a vector to itself.
- **Checks a real controller makes** on the host's good behaviour. A full completion queue is written over. The page size and entry sizes in `CC` are taken as read. Creating a queue that already exists replaces it. Read, Write and Flush do not look at the namespace number.
- **Switching interrupts off.** A queue always interrupts: its interrupt-enable bit and the mask registers (`INTMS`, `INTMC`) are ignored.
- **A name.** Identify says how many namespaces there are and how big, and nothing else: no model, no serial number, no version.
- **DMA failures.** An access to host memory that goes nowhere is not noticed.
- ⚠️ A doorbell write the controller cannot make sense of (a queue that does not exist, a slot past the end of the queue) gets a bus error. A real controller accepts the write and reports the mistake later, as an asynchronous event.

## Under the hood

- `src/socpuppet/core/nvme_controller.h` is the controller: registers, queues and commands, with no simulator in it. `src/socpuppet/core/prp.h` works out where a command's data is.
- `src/socpuppet/models/behavioral_nvme.h` is the SystemC wrapper: the sockets, the interrupt lines, and the process that does the controller's work.
- The layouts of every register, command and data structure are not ours. They come from [SPDK](https://github.com/spdk/spdk)'s `nvme_spec.h`, the Storage Performance Development Kit's rendering of the NVMe specification as C structs.
- What every NVMe function must do is written down as tests, in `tests/cpp/contracts/nvme_contract.h`. The real SSD will be held to the same ones.
