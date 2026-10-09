# Flash controller

`sp.FlashController()` · C++ `socpuppet::FlashController` · registry name `flash_controller`

## What it stands for

The part of an SSD's controller chip that works the [NAND flash](ideal-nand.md). The SSD's CPU does not move data itself: it would be far too slow, and on a real chip the NAND's pins are not even connected to it. The firmware says *which page* and *where in memory*, and this block moves the page.

```text
              registers                         the chip
   CPU ─────────────────────▶ ┌────────────┐ ──────────────▶ NAND
                              │   flash    │    a page
   the SSD's own memory ◀───▶ │ controller │
                    a page    └────────────┘ ───▶ irq, when done
```

## What it does

```python
flash = ssd.add("flash", sp.FlashController())
bus.map(flash.cpu, base=0x1003_0000)            # its registers
platform.connect(flash.local, bus.add_input())  # its way into the SSD's memory
platform.connect(flash.nand, nand.socket)       # the chip
```

| Port | What it is |
|---|---|
| `cpu` | The register block, 48 bytes. |
| `local` | How it reads and writes the SSD's own memory. Connect it to an input of the bus that memory is on. |
| `nand` | The chip. |
| `irq` | High while the controller has something to tell the CPU that the CPU asked to be told. Firmware that polls can leave it unconnected. |

### The registers

Each is 32 bits wide.

| Offset | Name | | |
|---|---|---|---|
| `0x00` | `COMMAND` | write | 1 reads a page, 2 programs a page, 3 erases a block, 4 identifies the chip. Reads as zero. |
| `0x04` | `STATUS` | read, write one to clear | bit 0 `DONE`, bit 1 `ERROR`, bit 2 `BUSY`. |
| `0x08` | `INT_ENABLE` | read, write | bits 0 and 1: which of `DONE` and `ERROR` raise `irq`. |
| `0x0C` | `BLOCK` | read, write | Which block of the chip. |
| `0x10` | `PAGE` | read, write | Which page of that block. |
| `0x14` | `LOCAL_ADDRESS` | read, write | Where the page is, or goes, in the SSD's own memory. |
| `0x20` | `PAGE_SIZE` | read | A page, in bytes. |
| `0x24` | `PAGES_PER_BLOCK` | read | |
| `0x28` | `BLOCKS` | read | |

The gaps at `0x18`, `0x1C` and `0x2C` are reserved, with nothing there.

### Giving it a command

```text
 firmware                          controller
    │ write BLOCK, PAGE, LOCAL_ADDRESS
    │ write COMMAND ──────────────▶ STATUS = BUSY
    │                               (a delta cycle later) moves the page
    │                               STATUS = DONE, or ERROR
    │ ◀──────────────────────────── irq rises, if enabled
    │ read STATUS
    │ write STATUS, to clear it ──▶ irq falls
```

- **Identify first.** The geometry registers read as zero until the controller has been told to identify the chip (command 4), and it cannot move a page before it knows how big one is: a read or a program before then ends in `ERROR`. 🎓 Real firmware does the same at start-up, by reading the chip's parameter page.
- **A command is about what the registers said when it was given.** The firmware may write `BLOCK`, `PAGE` and `LOCAL_ADDRESS` for the next command while this one is still busy.
- **One command at a time.** A write to `COMMAND` while the controller is busy is refused.
- **`STATUS` is about the last command.** Giving a new command clears `DONE` and `ERROR`, so firmware that polls need not clear them itself. Writing a one to either clears it, which is what makes `irq` fall. `BUSY` is the controller's to say and cannot be written away.
- **`ERROR`** means the command was not carried out: the chip has no such block or page, it would not answer, or nothing in the SSD's memory took the page or gave it. A program that cannot get its page from memory leaves the chip untouched.
- **Timing.** A write to `COMMAND` returns at once, and the work is done by the controller a delta cycle later, at the same simulated time. So `BUSY` is always what firmware sees first, as on real hardware, and then nothing takes any time.

💡 Why a delta cycle later, when nothing takes time? Moving a page puts an access on the SSD's bus, and the CPU's own write to `COMMAND` is still crossing that bus when the command arrives. Real hardware works alongside its CPU too.

## What it leaves out

- **Time.** The work is immediate, because the [ideal NAND](ideal-nand.md) is.
- **Error correction.** A real flash controller adds an error-correcting code to every page it programs and checks it on every read, because NAND flips bits. Here what goes in comes out.
- **More than a page at a time.** No queue of commands, no multi-page transfers, one chip.
- **Refusals as status.** ⚠️ A write the controller refuses (a command it does not have, any command while busy, a write to the geometry, an access that is not 32 bits wide or is beside a register) gets a bus error. Real hardware would more likely ignore it. Firmware that waits for `BUSY` to clear never sees one.
- **A debugger's hands.** A debugger can read the registers, and they look as they do to the CPU. It cannot write them: a command given that way would be work the firmware never asked for.

## Under the hood

- `src/socpuppet/core/flash_controller_logic.h` is the registers and what a command does, with no simulator in it. It reaches the chip and the memory through two small interfaces (`core/nand_port.h`, `core/memory_port.h`), so its tests need neither.
- `src/socpuppet/core/command_status.h` is what it shares with the [DMA engine](dma-engine.md): busy, done and error, and what interrupts for them.
- `src/socpuppet/models/flash_controller.h` is the SystemC wrapper, which adds two sockets to `CommandDevice` (`src/socpuppet/models/command_device.h`), the shell of any device its CPU gives one command at a time: the process that does the work, and the one process that drives `irq`.
- `tests/cpp/unit/flash_controller_logic_test.cpp` and `tests/cpp/platform/flash_controller_test.cpp` say what it does, one behaviour each.
- `python/socpuppet/zephyr_module/drivers/ssd/flash_controller.c` is Zephyr's driver for it, and it is a driver of Zephyr's flash class: firmware writes whole NAND pages with `flash_write`, erases whole NAND blocks with `flash_erase`, and reads with `flash_read`. ⚠️ What Zephyr's flash class calls a page is the unit of erasing, which a NAND calls a block.
- 💡 Zephyr asks every flash driver to read any bytes at all, and this controller can only fetch a whole page. So the driver keeps a page of its own for a read of part of one. A read of whole pages goes straight to the caller's memory, which is the kind the SSD's firmware does.
- `firmware/flash_test` holds the driver to Zephyr's own test of a flash driver, unchanged, and `tests/python/test_zephyr_flash_driver.py` runs it.
