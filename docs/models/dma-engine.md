# DMA engine

`sp.DmaEngine()` · C++ `socpuppet::DmaEngine` · registry name `dma_engine`

## What it stands for

The part of an SSD's controller chip that moves data between the host's memory and the SSD's own.

🎓 DMA is direct memory access: a device reading and writing memory by itself. An NVMe drive is never handed data. A read command says where in the host's memory the answer is to go, a write command says where the data is waiting, and the drive goes there and puts it or gets it. The firmware works out the addresses, and this block does the copying, because a CPU copying a megabyte a word at a time would be the slowest part of the drive.

```text
 the host's memory  ◀── host ──┐
                               │  DMA engine  ◀── registers ── CPU
 the SSD's own      ◀── local ─┘      │
 memory (its buffer)                  └──▶ irq, when done
```

## What it does

```python
dma = ssd.add("dma", sp.DmaEngine())
bus.map(dma.cpu, base=0x1002_0000)              # its registers
platform.connect(dma.host, uplink.add_input())  # its way to the host's memory
platform.connect(dma.local, bus.add_input())    # its way into the SSD's own
```

| Port | What it is |
|---|---|
| `cpu` | The register block, 32 bytes. |
| `host` | How it reads and writes the host's memory. In an SSD this goes up through the [PCIe endpoint](pcie-endpoint.md). |
| `local` | How it reads and writes the SSD's own memory. Connect it to an input of the bus that memory is on. |
| `irq` | High while the engine has something to tell the CPU that the CPU asked to be told. Firmware that polls can leave it unconnected. |

### The registers

Each is 32 bits wide.

<!-- regs:dma_engine start -->

| Offset | Name | Access | What it is |
| --- | --- | --- | --- |
| `0x00` | `COMMAND` | write | Write a command to start a copy of what the other registers say. Reads as zero. 1 `FROM_HOST`: Copy from the host's memory into the SSD's own. 2 `TO_HOST`: Copy from the SSD's own memory to the host's. |
| `0x04` | `STATUS` | read, write | How the last command went. Giving the next command forgets it. Bit 0 `DONE` (write one to clear): The command was carried out. Bit 1 `ERROR` (write one to clear): The command was not carried out, or not all of it. Bit 2 `BUSY` (read only): A command has been given and is not yet carried out. No other is taken meanwhile. |
| `0x08` | `INTERRUPT_ENABLE` | read, write | Which bits of `STATUS` raise the interrupt line while they are set. Bit 0 `DONE`. Bit 1 `ERROR`. |
| `0x0C` | `HOST_ADDRESS_LOW` | read, write | Where in the host's memory, the low 32 bits. |
| `0x10` | `HOST_ADDRESS_HIGH` | read, write | The high 32 bits. A host's memory can be above 4 GiB even when the SSD's CPU is a 32-bit one. |
| `0x14` | `LOCAL_ADDRESS` | read, write | Where in the SSD's own memory. |
| `0x18` | `LENGTH` | read, write | How many bytes. |

<!-- regs:dma_engine end -->

`0x1C` is reserved, with nothing there. The first three work exactly as the [flash controller](flash-controller.md)'s do, so a driver for one is most of a driver for the other.

- **A command is about what the registers said when it was given.** The firmware may describe the next copy while this one is still busy.
- **One command at a time.** A write to `COMMAND` while the engine is busy is refused.
- **Any length, at any address.** 🎓 NVMe describes a transfer as a list of memory pages (PRPs, physical region pages), and the first of them may start in the middle of a page. So firmware asks for one copy per entry, and the first is often an odd length.
- **`ERROR`** means the copy was not made, or not all of it: nothing answered at an address, on either side, or the length was zero. The engine copies 4 KiB at a time, and when a piece fails the pieces before it have already arrived. A copy of nothing is more likely a mistake in the firmware than something it meant, so the engine says so.
- **Timing.** A write to `COMMAND` returns at once, and the copy is made by the engine a delta cycle later, at the same simulated time. So `BUSY` is always what firmware sees first.

## What it leaves out

- **Time.** A copy is immediate, however long. 🚧 This register block is where a transfer starts taking time, once a milestone wants a drive that is no faster than its link.
- **A list of pieces.** Real engines take a chain of descriptors and walk it themselves, and many walk the host's PRP list too. Here firmware walks the list and asks for each piece, so that the walking is there to read.
- **Checking.** No checksums, no protection information.
- **Refusals as status.** ⚠️ A write the engine refuses (a command it does not have, any command while busy, an access that is not 32 bits wide or is beside a register) gets a bus error. Real hardware would more likely ignore it.
- **A debugger's hands.** A debugger can read the registers and cannot write them.

## Under the hood

- `src/socpuppet/core/dma_engine_logic.h` is the registers and the copy, with no simulator in it.
- `src/socpuppet/core/command_status.h` is what the engine and the flash controller share: busy, done and error, and what interrupts for them.
- `src/socpuppet/models/dma_engine.h` is the SystemC wrapper, which adds two sockets to `CommandDevice` (`src/socpuppet/models/command_device.h`), the shell of any device its CPU gives one command at a time: the process that does the work, and the one process that drives `irq`.
- `tests/cpp/unit/dma_engine_logic_test.cpp` and `tests/cpp/platform/dma_engine_test.cpp` say what it does, one behaviour each.
- `python/socpuppet/zephyr_module/drivers/ssd/dma_engine.c` is Zephyr's driver for it, two functions in `<socpuppet/drivers/dma_engine.h>`. `command_status.h` beside it is the part it shares with the flash controller's driver, as the models share theirs.
