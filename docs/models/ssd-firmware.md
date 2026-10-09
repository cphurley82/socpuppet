# 🎭 SSD firmware

`sp.SsdFirmware(frontend=..., dma=..., flash=..., buffer=...)` · Python only, `python/socpuppet/ssd_firmware.py`

## What it stands in for

The firmware of an SSD's controller: the program on the SSD's own CPU that decides what the drive does with each thing the host asks of it. On the finished platform that is Zephyr, running on the SSD's RISC-V core: the application in `firmware/ssd`. This stands in for it where there is no CPU, and it is kept on purpose, as the firmware for anyone who is bringing up a host, or who wants to read what an SSD does without reading C.

🧦 The two are written alike, section for section, and held to the same tests. So what this page says the firmware does is true of both, and [the real one](#the-real-one) says where they part.

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
from socpuppet.boards.scripted_host import bring_up_the_drive
from socpuppet.boards.ssd import ssd, stand_in_firmware

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
- **What it refuses** comes back as the status the specification gives it, as from the [stand-in drive](behavioral-nvme.md): an opcode it does not have, a block past the end, a namespace other than number 1, a queue identifier or an interrupt vector the drive does not have, a queue that already exists, a queue of one entry, a submission queue before its completion queue, data at an address in the host's memory where nothing answers, and a list of data pages that does not start where a pointer can.

### Where the data goes: a very small FTL

🎓 A NAND page is 4 KiB here, which is eight of the drive's 512-byte blocks. The part of firmware that turns blocks into NAND pages is the flash translation layer (FTL), and this one is a table and nothing more:

```text
 the drive, in pages of 8 blocks         the NAND
 page 0   ───────────────────────────▶   page 1
 page 1   (never written: reads as zeros, and is nowhere)
 ...
 page 511 ───────────────────────────▶   page 0
```

- **A page written for the first time** takes the next NAND page nobody has. So pages land on the NAND in the order they were first written, whatever their place on the drive. `firmware.page_map` is the table. 🎓 An FTL calls it the logical-to-physical table, L2P for short, and the host's block numbers are logical block addresses, LBAs.
- **A page that was never written** is in no NAND page, and reads as zeros. 💡 An erased NAND page reads as all ones. The zeros a host expects of a new drive come from the firmware, which knows what was never written.
- **A write of part of a page** has to keep the rest, so the firmware reads the page into the buffer, has the DMA engine lay the host's blocks over it, and programs it again. It does that once for each page of the drive a command touches, however many pieces the host's memory cuts the data into.
- **A page that is written again is programmed where it is.** ⚠️ Only the [ideal NAND](ideal-nand.md) allows that. A real chip has to be given a fresh page, the table changed, and the old page left as rubbish until its whole block can be erased. That is where garbage collection begins, and where this FTL stops.

### A command's data

🎓 NVMe says where a command's data is in the host's memory page by page (PRPs, physical region pages). The first pointer may start anywhere in a page. If the rest fits in one more page the second pointer is that page, and otherwise it points to a list of them. The firmware works out the list, fetching it through the DMA engine when there is one, and then asks for one copy per piece. `_data_of` is that, in one function.

## What it leaves out

- **A CPU.** Nothing is executed. Each step of the script is one access on the SSD's bus.
- **Time.** The firmware takes none. A real one takes most of the time a command takes.
- **Remembering where things are.** ⚠️ The table is kept in Python, and not on the NAND or in the SSD's buffer. Real firmware writes it to the flash as well and finds it again at power-on. A controller reset, which is the host's doing, loses nothing. 🚧 A reset of the SSD's own CPU is not something the board can do yet.
- **More than one thing at a time.** One command, one page of buffer.
- **Garbage collection, wear levelling, bad blocks.** Everything a real FTL spends its life on.
- **A write that fails half-way** has written the pages before the failure.
- **Most of the command set**, as the stand-in drive does: no deleting queues, no Get Features or log pages, no Dataset Management.

## The real one

`firmware/ssd` is the same firmware as a Zephyr application for the board `socpuppet_ssd`. Leave the script out of the description and the SSD has a CPU to load it into:

```python
board = ssd(host=host)                  # no firmware=: the SSD gets a CPU
board.platform.build()
board.platform.load_elf("build/firmware/ssd_socpuppet_ssd.elf",
                        via=board.ssd.cpu.socket)
```

`examples/ssd_firmware_hello.py` is that show, and [boot-your-firmware.md](../boot-your-firmware.md#bring-up-your-ssd-firmware) says how to build the image, or one of your own.

A host cannot tell the two apart by what they answer. This is what differs behind the curtain:

| | 🎭 The script | Zephyr, in `firmware/ssd` |
|---|---|---|
| Runs on | nothing: each step is one access on the SSD's bus | the SSD's 32-bit RISC-V core |
| Reaches the hardware | by reading and writing the three devices' registers | through three Zephyr drivers: the NAND through Zephyr's own flash API, the frontend and the DMA engine through small APIs of their own |
| Waits for the host | on the frontend's interrupt line | asleep, until the frontend's interrupt handler wakes it |
| Takes | no simulated time | a few milliseconds to boot, and about a millisecond for a command |
| Keeps its table | in a Python dict, `firmware.page_map` | in the SSD's buffer, after the page of scratch and the page of the drive: four bytes for each page of the drive |
| Biggest drive | any | 2 GiB |
| A device that never finishes | the script gives up, and its error says which device | its driver gives up after a tenth of a second |
| Says what went wrong | in a Python exception, which ends the run | on the SSD's console, and then waits there for ever |

- 💡 **The time is the CPU's.** The core runs about ten million instructions in a simulated second, and clearing a 4 KiB page a byte at a time is four thousand of them. Nothing else on the SSD takes time yet, so for now the firmware is all of a command's latency.
- **The table is made empty at every start**, an entry at a time, which takes the firmware about half a microsecond of simulated time for each page of the drive: a quarter of a second for 2 GiB. The host waits, as it would for a real drive. 🎓 An NVMe controller tells its host how long to be patient (`CAP.TO`), and [the frontend](nvme-frontend.md) says one second.
- 🔧 **When it cannot be a drive it says why, and what to change**: a NAND too big for it, a flash controller that reports an error or never answers, a NAND page bigger than the driver was built for. A line that starts `E:` is from a driver, in Zephyr's log, and comes before Zephyr's own banner, because drivers start first.
- ⚠️ **2 GiB is Zephyr's limit, and not the hardware's.** Zephyr's flash API names a place on a flash with a signed 32-bit number on this CPU. The firmware checks, and given a bigger NAND it says so on its console and stops. [upstream.md](../upstream.md) has the details.

## Under the hood

- `python/socpuppet/ssd_firmware.py` is all of the stand-in: the registers it uses of the three devices, at the top, and then the firmware from the loop down.
- `firmware/ssd/src` is the Zephyr application, a file for each section of the script, and `python/socpuppet/zephyr_module/drivers/ssd` its three drivers.
- `tests/python/test_ssd_firmware.py` runs each of them on the SSD's hardware, every test once with the script and once with Zephyr, with the [driver stand-in](nvme-host.md) for what a driver does and a bare host of the tests' own (`tests/python/raw_nvme.py`) for what a drive refuses.
- `tests/python/test_m4_exit.py` gives the SSD with Zephyr on it and 🎭 the [stand-in drive](behavioral-nvme.md) the same writes, and reads both back whole.
- `tests/python/test_ssd_zephyr_firmware.py` is what only the real one has, a console, and `test_ssd_stand_in_firmware.py` what only the script has: a table that Python can read.
- `tests/cpp/support/ssd_firmware.h` is the same firmware again in C++, for the NVMe contract. It is a test's own, and the two share nothing but the specification.
