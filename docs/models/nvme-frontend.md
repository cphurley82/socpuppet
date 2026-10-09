# NVMe frontend

`sp.NvmeFrontend(vectors=2)` · C++ `socpuppet::NvmeFrontend` · registry name `nvme_frontend`

## What it stands for

The part of an SSD's controller chip that speaks NVMe to the host. It is where an SSD stops being the [stand-in drive](behavioral-nvme.md), which answers every command itself, and becomes hardware with firmware behind it.

🎓 A real controller splits the work between the two. Hardware does what has to be done the same way every time and fast: keeping track of the queues, fetching commands, writing completions, raising interrupts. Firmware does what takes judgement: what each command means, whether the host may have what it asks for, and where the data really is. The frontend is the hardware's half.

```text
 the host                     the frontend                       the SSD's CPU
    │ write a command ─▶ submission queue (host memory)
    │ ring the doorbell ──────▶ │
    │                           │ fetch the command ─▶ one slot
    │                           │ ───────────── cpu_irq ───────────▶ │
    │                           │ ◀──────── read the command ────── │
    │                           │        (firmware does the work)
    │                           │ ◀── what the completion says ──── │
    │ completion queue ◀─────── │ post it
    │ ◀──────── interrupt ───── │ fetch the next command ...
```

## What it does

```python
frontend = ssd.add("frontend", sp.NvmeFrontend())
platform.connect(endpoint.bar0, frontend.bar0)                  # the host's registers
platform.connect(frontend.dma, uplink.target)                   # its way to the host's memory
platform.connect(frontend.irq0, endpoint.irq0)                  # its interrupts to the host
bus.map(frontend.cpu, base=0x1001_0000)                         # the CPU's registers
platform.connect(frontend.cpu_irq, plic.source1)                # its interrupt to the CPU
```

It has two faces.

| Port | What it is |
|---|---|
| `bar0` | The host's register block, 8 KiB: an NVMe controller's registers, and the doorbells after them. Connect it to a [PCIe endpoint](pcie-endpoint.md), as the stand-in drive's is. |
| `dma` | How it reads commands from the host's memory and writes completions to it. |
| `irq0`, `irq1`, ... | One interrupt line to the host per vector. The admin queue uses `irq0`. A line may be left unconnected. |
| `cpu` | The register block of the SSD's own CPU, 128 bytes. |
| `cpu_irq` | High while the frontend has something to tell the CPU that the CPU asked to be told. Firmware that polls can leave it unconnected. |

### To the host

It is an NVMe controller, and what the [stand-in drive's page](behavioral-nvme.md) says of registers, doorbells and interrupt lines holds here too: the two share that code. Two things differ, because there is firmware.

- **Ready is the firmware's to say.** Setting `CC.EN` does not make the controller ready. `CSTS.RDY` is what the firmware said of the controller the host has enabled now, and the firmware says so when it has finished starting up. A reset takes it back at once.
- **So the host is told to wait.** `CAP.TO` says one second. A host that has just enabled the controller may find the firmware still booting.

### To the SSD's CPU: the registers

Each is 32 bits wide, except the command.

| Offset | Name | | |
|---|---|---|---|
| `0x00` | `CONTROL` | read, write | Bit 0 `READY`: the host sees it as `CSTS.RDY`. |
| `0x04` | `STATUS` | read, write one to clear | See below. |
| `0x08` | `INT_ENABLE` | read, write | Bits 0 to 2: which of the status bits raise `cpu_irq`. |
| `0x0C` | `LIMITS` | read | How many I/O queue pairs the frontend has, in the low half, which is eight, and how many interrupt vectors, in the high half. |
| `0x10` | `COMMAND_QUEUE` | read | Which submission queue the waiting command came from. 0 is the admin queue. |
| `0x14` | `COMPLETION_RESULT` | read, write | The first 32 bits of the completion: the command's answer, for the few that have one. |
| `0x18` | `COMPLETION_STATUS` | read, write | How the command went, laid out as the status field of a completion is, less the phase bit: the status code in the low byte, zero for success, and in bits 8 to 10 which list of codes it is from. The other bits read back as zero. |
| `0x1C` | `COMPLETION_POST` | write | Write 1 to have the completion posted. |
| `0x20` | `QUEUE_ID` | read, write | A queue to create: which, |
| `0x24` | `QUEUE_BASE_LOW` | read, write | where it is in the host's memory, |
| `0x28` | `QUEUE_BASE_HIGH` | read, write | |
| `0x2C` | `QUEUE_LAST` | read, write | its last slot, which is its size less one, |
| `0x30` | `QUEUE_LINK` | read, write | and what goes with it: a completion queue's interrupt vector, or the completion queue a submission queue's completions go to. |
| `0x34` | `QUEUE_CREATE` | write | Write 1 to create that completion queue, 2 for a submission queue. |
| `0x40` | `COMMAND` | read | The waiting command, 64 bytes, read whole or a piece at a time. Zeros when none is waiting. |

`0x38` and `0x3C` are reserved, with nothing there. `STATUS` and `INT_ENABLE` are where the [DMA engine](dma-engine.md) and the [flash controller](flash-controller.md) have theirs.

`STATUS` has two kinds of bit:

| Bit | Name | |
|---|---|---|
| 0 | `ENABLED` | The host has enabled the controller. Stays set until the CPU writes a one to it. |
| 1 | `DISABLED` | The host has disabled it, which is a controller reset. Stays set until the CPU writes a one to it, and that write means something: see "A reset" below. |
| 2 | `COMMAND_WAITING` | A command is waiting. Set for exactly as long as one is. |

### One command at a time

The frontend holds one command for the CPU. It fetches the next when the firmware has had this one's completion posted.

- **`COMMAND_WAITING` falls and rises once per command.** The command stops waiting the moment the CPU writes `COMPLETION_POST`, and the next one, if there is one, starts waiting a delta cycle or two later. So `cpu_irq` has a rise for every command, and an interrupt controller that hears rises hears them all.
- **The frontend fills in what it knows.** The completion says which command it is for, which queue that came from and how far the queue has been read, and the firmware never has to. The firmware supplies only how it went.
- **Which command comes next** is the frontend's choice: the lowest-numbered queue with one, so admin commands go first. A command whose completion queue is full is not fetched until the host has made room, which is what keeps a full queue from being written over.

### Queues

The admin queues are the frontend's own: the host says where they are in registers, and the frontend sets them up when the host enables the controller. An I/O queue exists once the firmware has had it created. 🎓 The host asks for one with an admin command, and the firmware decides: is the identifier one the drive has, is the queue a sensible size, does the completion queue it names exist? If so, it passes on where the queue is, and the frontend takes that queue's doorbell from then on.

### A reset

When the host clears `CC.EN` the frontend does its part at once: every queue is gone, the waiting command is gone, a completion not yet posted never will be, the host's interrupt lines fall, and the controller is no longer ready. It sets `DISABLED`, and the firmware does the rest, which is to forget its own record of the queues.

⚠️ The firmware may be in the middle of a command when the reset comes, and the host may enable the controller again and submit before the firmware has even noticed. So the frontend keeps the two apart, with a handshake:

```text
 host: CC.EN = 0 ──▶ frontend: queues gone, command gone, not ready, DISABLED set
                     │
                     │   until the firmware acknowledges:
                     │     no command is fetched
                     │     COMPLETION_POST is taken, and nothing is posted
                     │     QUEUE_CREATE is taken, and nothing is created
                     │     READY is not heard
                     │
 firmware: forget the queues, write 1 to DISABLED ──▶ "I have let go of everything from before"
                     │
 firmware: write 1 to ENABLED, set READY ──▶ the host sees the controller ready
```

- **The acknowledgement is a promise.** Writing a one to `DISABLED` says the firmware holds nothing from before the reset: no command it will still complete, no queue it will still ask for. Firmware does that from wherever it does its work, and not from an interrupt handler while a thread is still busy.
- **Nothing in the window is the firmware's mistake.** The completion of a command the reset took away has nowhere to go, so it is dropped, and not refused.
- **`READY` is only heard when it is true**: the host has the controller enabled, and no reset is waiting to be acknowledged. So firmware that finds both `DISABLED` and `ENABLED` set deals with the reset first, then says it is ready, and need not ask which came last. If the host has disabled the controller again by then, the frontend does not hear it.

## What it leaves out

- **More than one command at a time.** A real frontend hands firmware many commands at once, and firmware works on them in whatever order suits the flash. Here they go one by one, which is easy to follow and would be slow. 🚧 Nothing takes time yet, so nothing notices.
- **Deleting a queue.** A queue lasts until the next reset.
- **Checking the host.** The page size and entry sizes in `CC` are taken as read, as on the stand-in drive, and interrupts cannot be masked.
- **`CSTS.CFS`**, the bit by which a controller says it has failed.
- **DMA failures.** A queue at an address where nothing answers is not noticed: the command fetched from it is zeros, and a completion posted to it goes nowhere.
- **Refusals as status.** ⚠️ A write the frontend refuses gets a bus error: a completion with no command waiting, a queue it cannot create (one that exists, an identifier or a vector it does not have, a submission queue whose completion queue is missing, any queue while the host does not have the controller enabled), a write to a register that only says something. Firmware that checks before it asks never sees one, because what a reset takes from under it is not refused.
- **A debugger's hands, on the CPU's side.** A debugger can read the CPU's registers and cannot write them. On the host's side it can do both, as on the stand-in drive, and a write there starts nothing.

## Under the hood

- `src/socpuppet/core/nvme_frontend_logic.h` is the CPU's registers, the one slot, and when a command is fetched and a completion posted, with no simulator in it.
- `src/socpuppet/core/nvme_queues.h` and `nvme_host_registers.h` are what it shares with the stand-in drive: the queues, and the host's register block.
- `src/socpuppet/models/nvme_frontend.h` is the SystemC wrapper: the sockets, the process that does the frontend's work in the host's memory, and the lines.
- `tests/cpp/unit/nvme_frontend_logic_test.cpp` and `tests/cpp/platform/nvme_frontend_test.cpp` say what it does, one behaviour each.
- 🎭 With a firmware stand-in in the CPU's place (`tests/cpp/support/ssd_firmware.h`), the frontend, the [DMA engine](dma-engine.md), the [flash controller](flash-controller.md) and the [ideal NAND](ideal-nand.md) together pass the NVMe contract, `tests/cpp/contracts/nvme_contract.h`, every item the stand-in drive is held to.
