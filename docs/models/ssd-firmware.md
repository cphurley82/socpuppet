# 🎭 SSD firmware

`sp.SsdFirmware(frontend=..., dma=..., flash=..., buffer=...)` · Python only, `python/socpuppet/ssd_firmware.py`

## What it stands in for

The firmware of an SSD's controller: the program on the SSD's own CPU that decides what the drive does with each thing the host asks of it. On the finished platform that is Zephyr, running on the SSD's RISC-V core. 🚧 Until that boots, this stands in for it, and it stays on afterwards as the firmware for anyone who is bringing up a host, or who wants to read what an SSD does without reading C.

🎓 The hardware around it keeps the queues and moves the data (see the [NVMe frontend](nvme-frontend.md)). What is left for firmware is the judgement:

- **Is the controller ready?** The host enables it and waits. The firmware says when.
- **What does this command mean?** Identify, a queue to create, a read, a write.
- **May the host have what it asks for?** A queue identifier the drive has, a block that is on the drive, a namespace that exists.
- **Where is the data, really?** The host says "block 7". On a NAND chip there is no block 7, only pages that someone has to keep track of.

## What it does

It is not a component. It is a script for the [scripted bus master](scripted-bus-master.md), in the place of the SSD's CPU:

```python
firmware = sp.SsdFirmware(frontend=0x1001_0000, dma=0x1002_0000,
                          flash=0x1003_0000, buffer=0x4000_0000)
cpu = ssd.add("cpu", sp.ScriptedBusMaster(firmware.script))
```

`socpuppet.boards.ssd` does that for you, with the whole SSD around it:

```python
from socpuppet.boards.ssd import bring_up_the_drive, ssd, stand_in_firmware

def host():
    nvme = yield from bring_up_the_drive()
    yield from nvme.write_blocks(first=0, data=bytes(512))

board = ssd(host=host, firmware=stand_in_firmware().script)
board.platform.build()
board.platform.run()
```

`examples/ssd_hello.py` is the whole show.

### The loop

```text
 start up: identify the NAND chip, ask the frontend what it has,
           ask to be interrupted
     │
     ▼
 wait for the frontend's line ◀───────────────────────────────────┐
     │                                                             │
     ├─ the host reset the controller? forget the queues,          │
     │                                 then acknowledge            │
     ├─ the host enabled it?           acknowledge, say "ready"    │
     └─ a command is waiting?          read it, do it,             │
                                       have its completion posted ─┘
```

The reset comes first, on purpose. If the host has reset the controller and enabled it again before the firmware looked, both are waiting, and the controller the host enabled is the one after the reset. [The frontend's page](nvme-frontend.md) has the handshake.

### The commands

- **Admin**: Identify (the controller, the namespace, the list of namespaces), Set Features for the number of queues, and the two commands that create an I/O queue pair.
- **I/O**: Read, Write and Flush, on one namespace of 512-byte blocks.
- **What it refuses** comes back as the status the specification gives it, as from the [stand-in drive](behavioral-nvme.md): an opcode it does not have, a block past the end, a namespace other than number 1, a queue identifier or an interrupt vector the drive does not have, a queue that already exists, a queue of one entry, a submission queue before its completion queue, and data at an address in the host's memory where nothing answers.

### Where the data goes: a very small FTL

🎓 A NAND page is 4 KiB here, which is eight of the drive's 512-byte blocks. The part of firmware that turns blocks into NAND pages is the flash translation layer (FTL), and this one is a table and nothing more:

```text
 the drive, in pages of 8 blocks         the NAND
 page 0   ───────────────────────────▶   page 1
 page 1   (never written: reads as zeros, and is nowhere)
 ...
 page 511 ───────────────────────────▶   page 0
```

- **A page written for the first time** takes the next NAND page nobody has. So pages land on the NAND in the order they were first written, whatever their place on the drive. `firmware.page_map` is the table.
- **A page that was never written** is in no NAND page, and reads as zeros. 💡 An erased NAND page reads as all ones. The zeros a host expects of a new drive come from the firmware, which knows what was never written.
- **A write of part of a page** has to keep the rest, so the firmware reads the page into the buffer, has the DMA engine lay the host's blocks over it, and programs it again.
- **A page that is written again is programmed where it is.** ⚠️ Only the [ideal NAND](ideal-nand.md) allows that. A real chip has to be given a fresh page, the table changed, and the old page left as rubbish until its whole block can be erased. That is where garbage collection begins, and where this FTL stops.

### A command's data

🎓 NVMe says where a command's data is in the host's memory page by page (PRPs, physical region pages). The first pointer may start anywhere in a page. If the rest fits in one more page the second pointer is that page, and otherwise it points to a list of them. The firmware works out the list, fetching it through the DMA engine when there is one, and then asks for one copy per piece. `_data_of` is that, in one function.

## What it leaves out

- **A CPU.** Nothing is executed. Each step of the script is one access on the SSD's bus.
- **Time.** The firmware takes none. A real one takes most of the time a command takes.
- **Remembering where things are.** ⚠️ The table is kept in Python, and not on the NAND. Real firmware writes it to the flash as well and finds it again at power-on. Here a reset of the SSD's CPU starts the script afresh with an empty table, and what was written is no longer found. A controller reset, which is the host's doing, loses nothing.
- **More than one thing at a time.** One command, one page of buffer.
- **Garbage collection, wear levelling, bad blocks.** Everything a real FTL spends its life on.
- **A write that fails half-way** has written the pages before the failure.
- **Most of the command set**, as the stand-in drive does: no deleting queues, no Get Features or log pages, no Dataset Management.

## Under the hood

- `python/socpuppet/ssd_firmware.py` is all of it: the registers it uses of the three devices, at the top, and then the firmware from the loop down.
- `tests/python/test_ssd_firmware.py` runs it on the SSD's hardware, with the [driver stand-in](nvme-host.md) for what a driver does and a bare host of the tests' own (`tests/python/raw_nvme.py`) for what a drive refuses.
- `tests/cpp/support/ssd_firmware.h` is the same firmware again in C++, for the NVMe contract. It is a test's own, and the two share nothing but the specification.
